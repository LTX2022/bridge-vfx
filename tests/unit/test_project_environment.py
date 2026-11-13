"""Fresh project resources through real controllers and explicit bottom HOM/USD APIs."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
sys.path.insert(0, str(ROOT / 'tools'))

from houdini_bridge.operation_receipts import canonical_sha256, validate_operation_receipt
from vfx_pipeline.workbuddy_assembly import software_host_client


def tool(name):
    spec = importlib.util.spec_from_file_location('project_environment_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegisteredEnvironmentHost:
    """Real registered build/init with only the existing native API boundary."""
    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
                dir='/private/tmp', prefix='project-environment-'))).resolve()
            self.stack.enter_context(patch.dict(sys.modules))
            self.stack.enter_context(patch.dict(os.environ, {
                'BRIDGE_SKILLS_STATE_ROOT': str(self.root / 'installation'),
                'HOUDINI_BRIDGE_STATE_DIR': str(self.root / 'houdini'),
                'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.root / 'scheduler')}))
            self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.root / 'host')
            self.hou = sys.modules['hou']
            self.api, self.boundary = tool('software_render_api_boundary'), tool('native_schema_test_boundary')
            interfaces, states, ports = self.api.static_scene_interface_profiles(ROOT, '21.0.631')
            self.boundary.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', '21.0.631',
                instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
            self.api.install_stage_api(self.hou)
            self.api.install_material_binding_api()
            self.api.install_graph_native_layout_api(self.hou)
            from vfx_pipeline import graph_catalog
            from vfx_pipeline.graph_trial import GraphExecutor
            from vfx_pipeline.scene_lease import SceneLeaseStore, SceneLeaseGuard
            self.task_id = 'project-environment-unit'
            self.selector = {'schema': 'bridge.registered-domain-construction/1', 'domain_pack': 'material_lookdev_v1',
                'houdini_version': '21.0.631', 'scene_profile': 'sphere_ground_v2'}
            self.compiled = graph_catalog.compile_proposal(self.selector)
            self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(), task_id=self.task_id,
                pid=os.getpid(), launch_nonce='explicit-project-environment-unit',
                plugin_build=self.addon._FX_LOADED_ADDON_SHA256, version='21.0.631')
            self.execution_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(
                (self.task_id + ':' + self.compiled.graph_hash).encode()).hexdigest()
            self.leases = SceneLeaseStore(self.root / 'leases.json')
            identity = self.addon.graph_worker_identity()
            self.lease = self.leases.acquire(task_id=self.task_id, root=self.execution_root,
                **{key: identity[key] for key in ('session_id', 'process_generation', 'scene_id')})
            guard = SceneLeaseGuard(self.lease, lambda: self.leases.current(self.lease.session_id, self.lease.scene_id),
                                   self.addon.graph_worker_identity)
            with self.leases.operation(self.lease):
                self.built = GraphExecutor(self.client, {}, lease_guard=guard).execute(self.task_id, self.compiled)
            if not self.built['construction_executed']:
                raise AssertionError(self.built)
            layout = graph_catalog.native_layout(self.compiled, self.execution_root)
            self.roles = {node.node_id: layout[node.address]['path'] for node in self.compiled.nodes}
            self.scene_root = self.hou.node(self.execution_root)
            self.project_root = self.root / 'render'
            self.project_root.mkdir()
            configuration = ROOT / 'docs/official-baselines/karma/frozen-scene-v2.json'
            raw = configuration.read_bytes()
            self.frozen = [{'index': 0, 'asset_id': 'karma-static-scene', 'semantic_role': 'render_scene_configuration',
                'source_uri': str(configuration), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}]
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def initialize(self):
        with self.leases.operation(self.lease):
            return self.addon.graph_initialize_registered_domain(self.task_id, self.selector, self.built['topology'],
                self.compiled.graph_hash, self.project_root, frozen_input_manifest=self.frozen)

    def manifest(self):
        return self.addon._fx_manifest(self.task_id)[1]

    def values(self, manifest=None):
        env = (manifest or self.manifest())['project_environment']
        return {(item['path'], item['parameter']): (
            self.hou.node(item['path']).parm(item['parameter']).unexpandedString(),
            self.hou.node(item['path']).parm(item['parameter']).eval()) for item in env['resources']}


class ProjectEnvironmentTests(unittest.TestCase):
    def test_registered_fresh_entry_freezes_factory_resources_without_creating_data(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            manifest = host.manifest()
            env = manifest['project_environment']
            self.assertEqual(env['schema'], 'houdini.project_environment/1.0')
            self.assertEqual(Path(env['project_root']), host.project_root)
            self.assertEqual(manifest['project_environment_sha256'], canonical_sha256(env))
            self.assertEqual({item['parameter'] for item in env['resources']},
                             {'rendergallerysource', 'dcmfilename', 'productName'})
            for item in env['resources']:
                parm = host.hou.node(item['path']).parm(item['parameter'])
                self.assertEqual(parm.unexpandedString(), item['raw'])
                self.assertNotIn('$HIP', item['raw'])
                self.assertFalse(Path(item['resource_directory']).exists())
                self.assertEqual(parm.parmTemplate().defaultValue(), (item['factory_default'],))
            captured = host.addon._fx_capture_scene_contract(host.task_id)
            self.assertEqual(captured['project_environment'], host.addon._fx_project_environment_readback(manifest, host.task_id))

    def test_public_fresh_entry_and_two_uuid_saves_keep_complete_contract_and_resources(self):
        from test_formal_public_task_save import FormalPublicTaskSaveTests, file_digest
        fixture = FormalPublicTaskSaveTests()
        try:
            fixture.setUp()
            manifest = fixture.host.manifest()
            env = manifest['project_environment']
            self.assertEqual({item['parameter'] for item in env['resources']},
                {'rendergallerysource', 'dcmfilename', 'productName', 'checkpoint_basedir', 'checkpoint_basename'})
            before = {(item['path'], item['parameter']): (
                fixture.host.hou.node(item['path']).parm(item['parameter']).unexpandedString(),
                fixture.host.hou.node(item['path']).parm(item['parameter']).eval()) for item in env['resources']}
            saved = [fixture.facade.task_save(), fixture.facade.task_save()]
            self.assertNotEqual(saved[0]['path'], saved[1]['path'])
            self.assertNotEqual(saved[0]['saved_scene_id'], saved[1]['saved_scene_id'])
            for value in saved:
                record = value['operation_receipt']
                validate_operation_receipt(record)
                self.assertEqual(record['before_scene']['scene_contract'], record['after_scene']['scene_contract'])
                self.assertEqual(value['scene_contract'], record['after_scene']['scene_contract'])
                self.assertEqual(value['scene_contract_sha256'], canonical_sha256(value['scene_contract']))
                self.assertEqual(file_digest(value['path']), value['sha256'])
                self.assertEqual(Path(record['facts']['saved_scene']['snapshot_path']).read_bytes(), Path(value['path']).read_bytes())
                self.assertEqual(value['feedback_dependencies'], ['graph:abc123:public-save-graph:output:domain_output',
                                                                  'graph:abc123:public-save-graph:version:0'])
            after = {(item['path'], item['parameter']): (
                fixture.host.hou.node(item['path']).parm(item['parameter']).unexpandedString(),
                fixture.host.hou.node(item['path']).parm(item['parameter']).eval()) for item in env['resources']}
            self.assertEqual(before, after)
            solver = fixture.host.hou.node(manifest['nodes']['solver'])
            self.assertTrue(solver.parm('checkpoint_basedir').isDisabled())
            self.assertEqual(solver.parm('savecheckpoints').eval(), 0)
            self.assertFalse(Path(solver.parm('checkpoint_basename').unexpandedString()).is_absolute())
        finally:
            fixture.doCleanups()

    def test_registered_two_saves_reopen_full_contract_and_stable_resources(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            interior = host.hou.node(host.roles['settings']).allSubChildren()[0]
            interior.setUserData(host.boundary.STATE_KEY, 'actual user data at the fixture reserved key')
            user_data = {node.path(): dict(node.userDataDict()) for node in host.scene_root.allSubChildren()}
            contract_before = host.addon._fx_capture_scene_contract(host.task_id)
            before = host.values()
            saved = []
            for _ in range(2):
                operation = 'project-save-' + uuid4().hex
                value = host.addon.dispatch('scene.save_hip', {'task_id': host.task_id,
                    'path': str(host.root / (operation + '.hip')), 'operation_id': operation,
                    'request_id': operation, 'frozen_input_manifest': host.frozen})
                validate_operation_receipt(value['operation_receipt'])
                self.assertEqual(value['operation_receipt']['before_scene']['scene_contract'], value['scene_contract'])
                self.assertEqual(host.values(), before)
                self.assertEqual({node.path(): dict(node.userDataDict()) for node in host.scene_root.allSubChildren()}, user_data)
                self.assertEqual(host.addon._fx_capture_scene_contract(host.task_id), contract_before)
                saved.append(value)
            self.assertNotEqual(saved[0]['path'], saved[1]['path'])
            value = saved[-1]
            reopened = host.addon.dispatch('scene.reopen_task_hip', {'task_id': host.task_id, 'path': value['path'],
                'sha256': value['sha256'], 'scene_contract_sha256': value['scene_contract_sha256'],
                'operation_id': 'project-environment-reopen', 'request_id': 'project-environment-reopen'})
            self.assertTrue(reopened['parameters_verified'])
            self.assertTrue(reopened['nodes_verified'])
            self.assertTrue(reopened['connections_verified'])
            self.assertEqual(reopened['frozen_scene_parameters'], value['scene_contract']['frozen_scene_parameters'])
            self.assertEqual(host.addon._fx_capture_scene_contract(host.task_id), value['scene_contract'])
            self.assertEqual(host.values(), before)
            self.assertEqual(host.hou.node(interior.path()).userData(host.boundary.STATE_KEY),
                             'actual user data at the fixture reserved key')

    def test_custom_driver_or_existing_resource_is_never_rewritten(self):
        for condition in ('custom', 'driver', 'existing', 'symlink_project_root'):
            with self.subTest(condition=condition), RegisteredEnvironmentHost() as host:
                gallery = host.hou.node(host.roles['usd_network']).parm('rendergallerysource')
                if condition == 'custom':
                    gallery.set(str(host.root / 'custom.db'))
                elif condition == 'driver':
                    gallery.setExpression('custom_expression()', language=host.hou.exprLanguage.Hscript)
                elif condition == 'existing':
                    specs = host.addon._fx_project_environment_targets(host.task_id, host.execution_root,
                                                                      host.roles, host.project_root)
                    Path(specs[0]['resource_directory']).mkdir(parents=True)
                else:
                    target = host.root / 'foreign-project'
                    target.mkdir()
                    host.project_root.rmdir()
                    host.project_root.symlink_to(target, target_is_directory=True)
                raw = gallery.unexpandedString()
                expected = {'custom': 'PROJECT_ENVIRONMENT_DEFAULT_REQUIRED', 'driver': 'PROJECT_ENVIRONMENT_DEFAULT_REQUIRED',
                            'existing': 'PROJECT_ENVIRONMENT_RESOURCE_EXISTS'}
                with self.assertRaises((host.addon.BridgeCommandError, ValueError)) as rejected:
                    host.initialize()
                if condition == 'symlink_project_root':
                    self.assertTrue(getattr(rejected.exception, 'code', '') == 'PROJECT_ENVIRONMENT_SCOPE_INVALID'
                                    or str(rejected.exception) == 'TASK_PATH_LINK', rejected.exception)
                else:
                    self.assertEqual(rejected.exception.code, expected[condition])
                self.assertEqual(gallery.unexpandedString(), raw)
                self.assertIsNone(host.scene_root.userData('bridge_project_environment_v1'))

    def test_parameter_or_manifest_write_failure_restores_resources_and_persistence(self):
        for failure in ('parameter', 'manifest'):
            with self.subTest(failure=failure), RegisteredEnvironmentHost() as host:
                specs = host.addon._fx_project_environment_targets(host.task_id, host.execution_root,
                                                                  host.roles, host.project_root)
                original = {(item['path'], item['parameter']): host.hou.node(item['path']).parm(item['parameter']).unexpandedString()
                            for item in specs}
                parm_class, node_class = host.hou._native_schema_parm_class, type(host.scene_root)
                old_set, old_userdata = parm_class.set, node_class.setUserData
                captured, failed = {}, []
                def set_value(parm, value, **kwargs):
                    if parm.name() == 'rendergallerysource' and str(value).startswith(str(host.project_root)) and not captured:
                        captured.update(host.scene_root.userDataDict())
                    if failure == 'parameter' and parm.path() == host.roles['settings'] + '/productName' and str(value).startswith(str(host.project_root)) and not failed:
                        failed.append(True)
                        raise OSError('explicit native parameter write failure')
                    return old_set(parm, value, **kwargs)
                def set_userdata(node, key, value):
                    if failure == 'manifest' and node.path() == host.execution_root and key == 'bridge_fx_manifest_v1' and not failed:
                        failed.append(True)
                        raise OSError('explicit native manifest user-data write failure')
                    return old_userdata(node, key, value)
                with patch.object(parm_class, 'set', set_value), patch.object(node_class, 'setUserData', set_userdata):
                    with self.assertRaises(OSError):
                        host.initialize()
                self.assertTrue(failed)
                self.assertEqual(host.scene_root.userDataDict(), captured)
                self.assertFalse(host.addon._fx_state_path(host.task_id).exists())
                self.assertEqual({key: host.hou.node(key[0]).parm(key[1]).unexpandedString() for key in original}, original)

    def test_incomplete_rollback_requires_reconciliation(self):
        for failure in ('rollback_write', 'callback_resource'):
            with self.subTest(failure=failure), RegisteredEnvironmentHost() as host:
                parm_class = host.hou._native_schema_parm_class
                old_set = parm_class.set
                failed, created = [], []
                def set_value(parm, value, **kwargs):
                    if failure == 'rollback_write':
                        if parm.path() == host.roles['settings'] + '/productName' and str(value).startswith(str(host.project_root)) and not failed:
                            failed.append(True)
                            raise OSError('explicit native write failure')
                        if failed and parm.name() == 'rendergallerysource' and value == '$HIP/galleries/$HIPNAME.$OS/rendergallery.db':
                            raise OSError('explicit native rollback failure')
                    result = old_set(parm, value, **kwargs)
                    if failure == 'callback_resource' and parm.name() == 'rendergallerysource' and str(value).startswith(str(host.project_root)) and not created:
                        database = Path(value)
                        database.parent.mkdir(parents=True)
                        database.write_bytes(b'explicit native callback data')
                        created.append(database)
                    return result
                with patch.object(parm_class, 'set', set_value):
                    with self.assertRaises(host.addon.BridgeCommandError) as rejected:
                        host.initialize()
                    self.assertEqual(rejected.exception.code, 'PROJECT_ENVIRONMENT_RECONCILE_REQUIRED')
                self.assertIsNotNone(host.scene_root.userData('bridge_project_environment_reconcile'))
                if created:
                    self.assertEqual(created[0].read_bytes(), b'explicit native callback data')
                with self.assertRaises(host.addon.BridgeCommandError) as rejected:
                    with host.addon._fx_project_environment_transaction(host.scene_root, host.task_id, host.roles,
                            host.project_root, fresh=True):
                        self.fail('an incomplete rollback cannot resume automatically')
                self.assertEqual(rejected.exception.code, 'PROJECT_ENVIRONMENT_RECONCILE_REQUIRED')

    def test_environment_hash_and_live_parameter_drift_reject(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            manifest = host.manifest()
            for field in ('project_environment', 'project_environment_sha256'):
                changed = deepcopy(manifest)
                changed.pop(field)
                with self.subTest(field=field), self.assertRaises(host.addon.BridgeCommandError) as rejected:
                    host.addon._fx_project_environment_readback(changed, host.task_id)
                self.assertEqual(rejected.exception.code, 'PROJECT_ENVIRONMENT_INVALID')
            changed = deepcopy(manifest)
            changed['project_environment']['project_root'] = str(host.root / 'foreign')
            changed['project_environment_sha256'] = canonical_sha256(changed['project_environment'])
            with self.assertRaises(host.addon.BridgeCommandError) as rejected:
                host.addon._fx_project_environment_readback(changed, host.task_id)
            self.assertEqual(rejected.exception.code, 'PROJECT_ENVIRONMENT_INVALID')
            resource = manifest['project_environment']['resources'][0]
            host.hou.node(resource['path']).parm(resource['parameter']).set(str(host.root / 'drift.db'))
            with self.assertRaises(host.addon.BridgeCommandError) as rejected:
                host.addon._fx_project_environment_readback(manifest, host.task_id)
            self.assertEqual(rejected.exception.code, 'PROJECT_ENVIRONMENT_DRIFT')

    def test_existing_legacy_manifest_is_not_migrated(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            legacy = deepcopy(host.manifest())
            legacy.pop('project_environment')
            legacy.pop('project_environment_sha256')
            host.scene_root.destroyUserData('bridge_project_environment_v1')
            host.scene_root.destroyUserData('bridge_project_environment_sha256')
            before = host.values()
            with host.addon._fx_project_environment_transaction(host.scene_root, host.task_id, host.roles,
                    host.root / 'other-project', fresh=False, existing=legacy) as result:
                self.assertIsNone(result)
            self.assertEqual(host.values(), before)

    def test_cold_host_state_directory_does_not_change_saved_project_anchor(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            manifest, before = host.manifest(), host.values()
            saved = host.addon.dispatch('scene.save_hip', {'task_id': host.task_id, 'path': str(host.root / 'cold.hip')})
            first_identity = host.addon._host_identity()
            host.addon.bridge_scene_identity()
            host.hou.hipFile.load(saved['path'])
            self.assertEqual(host.addon._host_identity()['scene_epoch'], first_identity['scene_epoch'] + 1)
            first_state = host.addon._BRIDGE_SCENE_STATE
            cold_root = host.root / 'different-host-state'
            with patch.dict(os.environ, {'BRIDGE_SKILLS_STATE_ROOT': str(cold_root / 'installation'),
                    'HOUDINI_BRIDGE_STATE_DIR': str(cold_root / 'houdini'),
                    'BRIDGE_SKILLS_SCHEDULER_ROOT': str(cold_root / 'scheduler')}):
                _client, cold_addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', cold_root / 'host')
                cold_hou = sys.modules['hou']
                cold_state = cold_addon._BRIDGE_SCENE_STATE
                cold_identity = cold_addon._host_identity()
                self.assertEqual(cold_identity['scene_epoch'], 0)
                self.assertIsNot(cold_state, first_state)
                for field in ('session_id', 'process_generation'):
                    self.assertNotEqual(cold_identity[field], first_identity[field])
                reload_spec = importlib.util.spec_from_file_location('project_environment_same_host_reload',
                    ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
                reloaded = importlib.util.module_from_spec(reload_spec)
                reload_spec.loader.exec_module(reloaded)
                self.assertIs(reloaded._BRIDGE_SCENE_STATE, cold_state)
                self.assertEqual(reloaded._host_identity(), cold_identity)
                with self.assertRaises(FileNotFoundError):
                    software_host_client(host.root / 'missing-addon.py', cold_root / 'failed-host')
                self.assertIs(sys.modules['hou'], cold_hou)
                self.assertIs(sys.modules['_houdini_bridge_scene_identity_state'], cold_state)
                with patch.dict(sys.modules):
                    sys.modules.pop('hou')
                    sys.modules.pop('_houdini_bridge_scene_identity_state')
                    with self.assertRaises(FileNotFoundError):
                        software_host_client(host.root / 'missing-addon.py', cold_root / 'failed-empty-host')
                    self.assertNotIn('hou', sys.modules)
                    self.assertNotIn('_houdini_bridge_scene_identity_state', sys.modules)
                boundary = tool('native_schema_test_boundary')
                interfaces, states, ports = host.api.static_scene_interface_profiles(ROOT, '21.0.631')
                boundary.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', '21.0.631',
                    instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
                host.api.install_stage_api(cold_hou)
                host.api.install_material_binding_api()
                host.api.install_graph_native_layout_api(cold_hou)
                cold_addon.bridge_scene_identity()
                cold_hou.hipFile.load(saved['path'])
                self.assertEqual(cold_addon._host_identity(), {**cold_identity, 'scene_epoch': 1})
                self.assertEqual(first_state.scene_epoch, first_identity['scene_epoch'] + 1)
                observed = cold_addon._fx_project_environment_readback(manifest, host.task_id)
                self.assertEqual(observed['project_root'], manifest['project_environment']['project_root'])
                self.assertEqual({(item['path'], item['parameter']): (
                    cold_hou.node(item['path']).parm(item['parameter']).unexpandedString(),
                    cold_hou.node(item['path']).parm(item['parameter']).eval()) for item in observed['resources']}, before)

    def test_reference_classification_requires_actual_role_and_frozen_relative_inputs(self):
        with RegisteredEnvironmentHost() as host:
            host.initialize()
            gallery_node = host.hou.node(host.roles['usd_network'])
            gallery = gallery_node.parm('rendergallerysource')
            nodes = {host.execution_root: host.scene_root, gallery_node.path(): gallery_node}
            with patch.object(host.hou, 'fileReferences', return_value=[(gallery, gallery.unexpandedString())], create=True):
                observed = host.addon._scene_external_reference_fingerprint(nodes, [])
            self.assertTrue(observed['identity_complete'], observed)
            self.assertEqual(observed['reference_count'], 0)
            unknown_node = host.hou.node('/stage')
            unknown = unknown_node.parm('rendergallerysource')
            self.assertIsInstance(unknown_node, host.hou.LopNetwork)
            self.assertEqual(unknown_node.childTypeCategory().name(), 'Lop')
            with patch.object(host.hou, 'fileReferences', return_value=[(unknown, unknown.unexpandedString())], create=True):
                global_factory = host.addon._scene_external_reference_fingerprint({'/stage': unknown_node}, [])
            self.assertTrue(global_factory['identity_complete'], global_factory)
            self.assertEqual(global_factory['reference_count'], 0)
            class NodeProxy:
                def __init__(self, node): self.native = node
                def __getattr__(self, name): return getattr(self.native, name)
                def __eq__(self, other): return other is self.native or isinstance(other, NodeProxy) and other.native is self.native
            original_node = host.hou.node
            proxy = NodeProxy(unknown_node)
            self.assertIsNot(proxy, unknown_node)
            self.assertEqual(proxy, unknown_node)
            with patch.object(host.hou, 'node', side_effect=lambda path: NodeProxy(unknown_node) if path == '/stage' else original_node(path)), \
                    patch.object(host.hou, 'fileReferences', return_value=[(unknown, unknown.unexpandedString())], create=True):
                proxy_factory = host.addon._scene_external_reference_fingerprint({'/stage': proxy}, [])
            self.assertTrue(proxy_factory['identity_complete'], proxy_factory)
            self.assertEqual(proxy_factory['reference_count'], 0)
            host.hou.hipFile.setName(str(host.root / 'unsaved.hip'))
            unknown.set('$HIP/relative.input')
            source = host.root / 'relative.input'
            source.write_bytes(b'frozen input')
            frozen = [{'index': 0, 'source_uri': str(source), 'uri': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                       'bytes': source.stat().st_size}]
            with patch.object(host.hou, 'fileReferences', return_value=[(unknown, unknown.unexpandedString())], create=True):
                missing = host.addon._scene_external_reference_fingerprint({'/stage': unknown_node}, [])
                self.assertFalse(missing['identity_complete'])
                self.assertEqual(missing['references'][0]['parm_path'], '/stage/rendergallerysource')
                host.addon._rehash_frozen_input_manifest(frozen)
                covered = host.addon._scene_external_reference_fingerprint({'/stage': unknown_node}, frozen)
                self.assertTrue(covered['identity_complete'], covered)
                source.write_bytes(b'changed bytes')
                with self.assertRaises(host.addon.BridgeCommandError) as rejected:
                    host.addon._rehash_frozen_input_manifest(frozen)
                self.assertEqual(rejected.exception.code, 'SCENE_STATE_DRIFT')


if __name__ == '__main__':
    unittest.main()
