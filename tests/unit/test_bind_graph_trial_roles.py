"""Targeted role-binding coverage for the formal graph-trial handoff.

Covers the 22nd repair: a verified registered schedule keeps the compiler's
exact role mapping, no ``output``/``source`` alias is guessed for packs without
such roles, the legacy no-schedule branch keeps its historical fallback, and
registered leaf-name collisions fail closed instead of dropping real nodes.
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


def load_tool(name):
    spec = importlib.util.spec_from_file_location('bind_roles_test_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BindGraphTrialRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bind-graph-roles-')
        self.addCleanup(self.temp.cleanup)
        self.root_dir = Path(self.temp.name).resolve()
        self.modules = patch.dict(sys.modules)
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.environment = patch.dict(os.environ, {'BRIDGE_SKILLS_STATE_ROOT': str(self.root_dir / 'state'),
            'HOUDINI_BRIDGE_STATE_DIR': str(self.root_dir / 'houdini'), 'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.root_dir / 'scheduler')})
        self.environment.start(); self.addCleanup(self.environment.stop)
        from vfx_pipeline.workbuddy_assembly import software_host_client
        self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.root_dir / 'host')
        boundary = load_tool('native_schema_test_boundary')
        self.api = load_tool('software_render_api_boundary')
        interfaces, states, ports = self.api.static_scene_interface_profiles(ROOT, '21.0.631')
        boundary.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', '21.0.631',
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        self.api.install_stage_api(self.hou)
        self.api.install_material_binding_api()
        self.api.install_graph_native_layout_api(self.hou)
        from vfx_pipeline import graph_catalog
        from vfx_pipeline.graph_trial import GraphExecutor
        from vfx_pipeline.scene_lease import SceneLeaseStore, SceneLeaseGuard
        selector = {'schema': 'bridge.registered-domain-construction/1', 'domain_pack': 'material_lookdev_v1',
                    'houdini_version': '21.0.631', 'scene_profile': 'sphere_ground_v2'}
        compiled = graph_catalog.compile_proposal(selector)
        self.task_id = 'bind-graph-roles'
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(), task_id=self.task_id,
            pid=os.getpid(), launch_nonce='bind-roles-unit',
            plugin_build=self.addon._FX_LOADED_ADDON_SHA256, version='21.0.631')
        self.selector, self.compiled = selector, compiled
        self.root_path = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(
            (self.task_id + ':' + compiled.graph_hash).encode()).hexdigest()
        host = self.addon.graph_worker_identity()
        store = SceneLeaseStore(self.root_dir / 'leases.json')
        lease = store.acquire(task_id=self.task_id, root=self.root_path,
            **{key: host[key] for key in ('session_id', 'process_generation', 'scene_id')})
        guard = SceneLeaseGuard(lease, lambda: store.current(lease.session_id, lease.scene_id), self.addon.graph_worker_identity)
        with store.operation(lease):
            built = GraphExecutor(self.client, {}, lease_guard=guard).execute(self.task_id, compiled)
            self.assertTrue(built['construction_executed'], built)
            self.built = built
        # Embed the graph worker's manifest directly (its producer is covered
        # elsewhere); the handoff under test only reads the embedded schedule.
        schedule = graph_catalog.bounded_domain_schedule(compiled)
        self.assertIsNotNone(schedule)
        roles = {address.rsplit('/', 1)[-1]: path for address, path in built['topology']['nodes'].items()}
        root = self.hou.node(self.root_path)
        root.setUserData('bridge_fx_owned', '1')
        self.addon._fx_store_manifest(root, {
            'schema': 'houdini.fx.scene_manifest/1.0', 'task_id': self.task_id,
            'domain_pack': 'material_lookdev_v1', 'pack_version': '1.0.0',
            'execution_root': self.root_path, 'nodes': roles,
            'build_state': 'BUILT_VERIFIED', 'graph_hash': compiled.graph_hash,
            'registered_domain_schedule': schedule,
        })
        hip = self.root_dir / 'graph-trial.hip'
        hip.write_bytes(b'bind-graph-roles-trial-hip')
        self.hou.hipFile.setName(str(hip))
        self.hip_sha = hashlib.sha256(hip.read_bytes()).hexdigest()
        self.topology = built['topology']

    def _receipt(self, topology):
        return {
            'state': 'SUCCEEDED', 'stop_confirmed': True, 'operation_id': 'graph-trial-roles-op',
            'result': {
                'construction_executed': True, 'reconciliation_required': False,
                'operation_id': 'graph-trial-roles-op',
                'verification': {'nodes_verified': True, 'parameters_verified': True,
                                 'connections_verified': True},
                'artifact': {'sha256': self.hip_sha},
                'topology': topology, 'graph_hash': self.compiled.graph_hash,
            },
        }

    def _bind(self, topology):
        return self.addon._fx_bind_graph_trial({'task_id': self.task_id, 'trial_receipt': self._receipt(topology)})

    def _bound_manifest(self):
        return self.addon._fx_manifest(self.task_id, required=False, root_path=self.root_path)[1]

    def _renamed_nodes(self, replacements):
        """Rename address leaves: {address_suffix: replacement_address} -> (node_map, pairs)."""
        renamed, pairs = {}, []
        for address, path in self.topology['nodes'].items():
            replacement = next((new for suffix, new in replacements.items() if address.endswith(suffix)), None)
            renamed[replacement or address] = path
            pairs.append((address, replacement or address))
        return renamed, pairs

    def _patched_catalog(self, pairs):
        """Patch the catalog verification to a fabricated layout keeping each node's real path."""
        from vfx_pipeline import graph_catalog
        real_layout = graph_catalog.native_layout(self.compiled, self.root_path)
        root_type = graph_catalog.native_root_type(self.compiled)
        schedule = self._bound_manifest().get('registered_domain_schedule')
        self.assertIsNotNone(schedule)
        fabricated = {renamed: {'path': real_layout[original]['path']} for original, renamed in pairs}
        return patch.multiple(graph_catalog, compile_proposal=lambda proposal: SimpleNamespace(
            graph_hash=self.compiled.graph_hash),
            bounded_domain_schedule=lambda graph: schedule,
            native_layout=lambda graph, root: fabricated,
            native_root_type=lambda graph: root_type)

    def test_registered_material_binding_keeps_exact_roles_without_output_alias(self):
        result = self._bind(self.topology)
        self.assertTrue(result['graph_ready'])
        nodes = self._bound_manifest()['nodes']
        exact = {address.rsplit('/', 1)[-1]: path for address, path in self.topology['nodes'].items()}
        self.assertEqual(nodes, exact)
        self.assertEqual(len(nodes), len(self.topology['nodes']))
        self.assertNotIn('output', nodes)
        self.assertEqual(nodes['source'], exact['source'])
        self.assertEqual(len(set(nodes.values())), len(nodes))
        contract = self.addon._fx_capture_scene_contract(self.task_id)
        self.assertIsNotNone(contract)
        contract_paths = [node['path'] for node in contract['nodes']]
        self.assertEqual(len(set(contract_paths)), len(contract_paths))

    def test_registered_schedule_with_genuine_output_role_keeps_it(self):
        renamed, pairs = self._renamed_nodes({'/render_network/render': 'houdini_rop:/render_network/output'})
        with self._patched_catalog(pairs):
            self._bind({**self.topology, 'nodes': renamed})
        nodes = self._bound_manifest()['nodes']
        by_leaf = {address.rsplit('/', 1)[-1]: path for address, path in self.topology['nodes'].items()}
        self.assertEqual(nodes['output'], by_leaf['render'])
        self.assertNotIn('render', nodes)
        self.assertEqual(len(nodes), len(renamed))
        self.assertEqual(len(set(nodes.values())), len(nodes))

    def test_registered_leaf_collision_is_rejected_fail_closed(self):
        renamed, pairs = self._renamed_nodes(
            {'/material_network/displacement': 'houdini_vop:/material_network_duplicate/normal_map'})
        before = self._bound_manifest()
        with self._patched_catalog(pairs):
            with self.assertRaisesRegex(self.addon.BridgeCommandError, 'registered roles collide'):
                self._bind({**self.topology, 'nodes': renamed})
        after = self._bound_manifest()
        self.assertNotEqual(after.get('maturity'), 'software_formal_graph_binding')
        self.assertEqual(after.get('nodes'), before.get('nodes'))

    def test_legacy_handoff_without_schedule_keeps_source_output_fallback(self):
        root, embedded = self.addon._fx_manifest(self.task_id, required=False, root_path=self.root_path)
        embedded.pop('registered_domain_schedule', None)
        self.addon._fx_store_manifest(root, embedded)
        result = self._bind(self.topology)
        self.assertTrue(result['graph_ready'])
        nodes = self._bound_manifest()['nodes']
        exact = {address.rsplit('/', 1)[-1]: path for address, path in self.topology['nodes'].items()}
        by_leaf = {address.rsplit('/', 1)[-1]: path for address, path in self.topology['nodes'].items()}
        legacy_output = list(self.topology['nodes'].values())[-1]
        self.assertEqual(nodes, {**exact, 'source': by_leaf['source'], 'output': legacy_output})


if __name__ == '__main__':
    unittest.main()
