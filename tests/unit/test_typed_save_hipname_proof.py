"""Typed saves name the scene under a lease and durable intent.

The actual before-scene remains intact, while a separate named proof binds
HIPNAME-dependent values to the target. Failed naming restores the old name;
possibly effective native saves remain non-replayable reconciliation cases.
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


def load_tool(name):
    spec = importlib.util.spec_from_file_location('typed_save_test_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TypedSaveHipNameProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='typed-save-proof-')
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
        self.task_id = 'typed-save-proof'
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(), task_id=self.task_id,
            pid=os.getpid(), launch_nonce='typed-save-unit',
            plugin_build=self.addon._FX_LOADED_ADDON_SHA256, version='21.0.631')
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
        roles = {address.rsplit('/', 1)[-1]: path for address, path in built['topology']['nodes'].items()}
        graph_root = self.hou.node(self.root_path)
        graph_root.setUserData('bridge_fx_owned', '1')
        self.addon._fx_store_manifest(graph_root, {
            'schema': 'houdini.fx.scene_manifest/1.0', 'task_id': self.task_id,
            'domain_pack': 'material_lookdev_v1', 'pack_version': '1.0.0',
            'execution_root': self.root_path, 'nodes': roles,
            'build_state': 'BUILT_VERIFIED', 'graph_hash': compiled.graph_hash,
            'registered_domain_schedule': graph_catalog.bounded_domain_schedule(compiled),
        })
        hip = self.root_dir / 'graph-trial.hip'
        hip.write_bytes(b'typed-save-proof-trial-hip')
        self.hou.hipFile.setName(str(hip))
        self.hip_sha = hashlib.sha256(hip.read_bytes()).hexdigest()
        receipt = {
            'state': 'SUCCEEDED', 'stop_confirmed': True, 'operation_id': 'graph-trial-op',
            'result': {
                'construction_executed': True, 'reconciliation_required': False,
                'operation_id': 'graph-trial-op',
                'verification': {'nodes_verified': True, 'parameters_verified': True,
                                 'connections_verified': True},
                'artifact': {'sha256': self.hip_sha},
                'topology': built['topology'], 'graph_hash': compiled.graph_hash,
            },
        }
        bound = self.addon._fx_bind_graph_trial({'task_id': self.task_id, 'trial_receipt': receipt})
        self.assertTrue(bound['graph_ready'])
        self.save_root = self.root_dir / 'saves'
        self.save_root.mkdir()

    def _save_request(self, name):
        operation_id = 'task-save-' + name
        path = self.save_root / (operation_id + '.hip')
        return operation_id, {'task_id': self.task_id, 'operation_id': operation_id,
                              'request_id': operation_id, 'path': str(path),
                              'frozen_input_manifest': []}, path

    def _dispatch(self, request):
        return self.addon.dispatch('scene.save_hip', request)

    def test_typed_save_applies_target_name_before_proof_capture(self):
        from houdini_bridge.operation_receipts import validate_operation_receipt
        operation_id, request, path = self._save_request('first')
        original_path = self.hou.hipFile.path()
        original_name = self.hou.hipFile.setName
        def named_after_intent(value):
            runner = self.addon.fx_operation_runner(self.task_id)
            with runner._locked():
                intent, _, _ = self.addon._fx_producer_record(runner, runner._load(), operation_id)
            self.assertEqual(intent['state'], 'INTENT')
            self.assertEqual(intent['save_name_transition']['original_hip_path'], original_path)
            return original_name(value)
        with patch.object(self.hou.hipFile, 'setName', side_effect=named_after_intent):
            result = self._dispatch(request)
        record = result['operation_receipt']
        validate_operation_receipt(record)
        self.assertEqual(record['state'], 'COMPLETED')
        self.assertEqual(record['before_scene']['hip_path'], original_path)
        self.assertEqual(record['after_scene']['hip_path'], str(path))
        self.assertEqual(record['facts']['save_name_transition']['named_scene_contract_sha256'],
                         record['after_scene']['scene_contract_sha256'])
        self.assertTrue(path.is_file())
        self.assertEqual(result['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(len(record['after_scene']['scene_contract']['nodes']),
                         len(self.addon._fx_manifest(self.task_id, required=False,
                             root_path=self.root_path)[1]['nodes']))

    def test_completed_typed_save_replays_idempotently_without_resaving(self):
        operation_id, request, path = self._save_request('replay')
        first = self._dispatch(request)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        second = self._dispatch(request)
        self.assertTrue(second.get('idempotent'))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(second['operation_receipt']['operation_id'], operation_id)
        self.assertEqual(first['operation_receipt']['operation_id'], operation_id)

    def test_non_fresh_target_is_rejected_before_any_rename(self):
        operation_id, request, path = self._save_request('stale')
        path.write_bytes(b'already-exists')
        before_name = self.hou.hipFile.path()
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'explicit fresh HIP path'):
            self._dispatch(request)
        self.assertEqual(self.hou.hipFile.path(), before_name)

    def _stored(self, operation_id):
        runner = self.addon.fx_operation_runner(self.task_id)
        with runner._locked():
            return self.addon._fx_producer_record(runner, runner._load(), operation_id)[0]

    def test_lease_rejection_cannot_rename_or_create_an_intent(self):
        operation_id, request, path = self._save_request('lease-denied')
        request['_scene_save_fenced'] = True
        original = self.hou.hipFile.path()
        with patch.object(self.addon, '_root_lease_check', side_effect=self.addon.BridgeCommandError(
                'SCENE_OWNERSHIP_REQUIRED', 'revoked lease')):
            with self.assertRaisesRegex(self.addon.BridgeCommandError, 'revoked lease'):
                self._dispatch(request)
        self.assertEqual(self.hou.hipFile.path(), original)
        self.assertFalse(path.exists())
        self.assertIsNone(self._stored(operation_id))

    def test_named_capture_failure_restores_original_name_with_failed_intent(self):
        operation_id, request, path = self._save_request('capture-failed')
        original, capture = self.hou.hipFile.path(), self.addon._fx_producer_scene
        calls = []
        def readback(*args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise RuntimeError('named capture failed')
            return capture(*args, **kwargs)
        with patch.object(self.addon, '_fx_producer_scene', side_effect=readback):
            with self.assertRaisesRegex(RuntimeError, 'named capture failed'):
                self._dispatch(request)
        self.assertEqual(self.hou.hipFile.path(), original)
        self.assertFalse(path.exists())
        stored = self._stored(operation_id)
        self.assertEqual(stored['state'], 'FAILED')
        self.assertTrue(stored['save_name_restored'])
        self.assertFalse(stored['reconciliation_required'])

    def test_native_half_save_restores_name_but_requires_reconciliation(self):
        operation_id, request, path = self._save_request('partial-save')
        original, save = self.hou.hipFile.path(), self.hou.hipFile.save
        def write_then_fail(*args, **kwargs):
            save(*args, **kwargs)
            raise RuntimeError('native save interrupted after writing')
        with patch.object(self.hou.hipFile, 'save', side_effect=write_then_fail):
            with self.assertRaises(self.addon.BridgeCommandError) as failure:
                self._dispatch(request)
        self.assertEqual(failure.exception.code, 'PRODUCER_RECONCILE_REQUIRED')
        self.assertEqual(self.hou.hipFile.path(), original)
        self.assertTrue(path.exists())
        self.assertTrue(self._stored(operation_id)['reconciliation_required'])
        with self.assertRaises(self.addon.BridgeCommandError) as replay:
            self._dispatch(request)
        self.assertEqual(replay.exception.code, 'PRODUCER_RECONCILE_REQUIRED')

    def test_failed_name_restoration_keeps_reconciliation_required(self):
        operation_id, request, path = self._save_request('restore-failed')
        capture, rename = self.addon._fx_producer_scene, self.hou.hipFile.setName
        captures, names = [], []
        def readback(*args, **kwargs):
            captures.append(None)
            if len(captures) == 2:
                raise RuntimeError('named capture failed')
            return capture(*args, **kwargs)
        def set_name(value):
            names.append(value)
            if len(names) == 2:
                raise RuntimeError('restore failed')
            return rename(value)
        with patch.object(self.addon, '_fx_producer_scene', side_effect=readback), \
                patch.object(self.hou.hipFile, 'setName', side_effect=set_name):
            with self.assertRaises(self.addon.BridgeCommandError) as failure:
                self._dispatch(request)
        self.assertEqual(failure.exception.code, 'PRODUCER_RECONCILE_REQUIRED')
        self.assertFalse(path.exists())
        self.assertFalse(self._stored(operation_id)['save_name_restored'])
        self.assertTrue(self._stored(operation_id)['reconciliation_required'])


if __name__ == '__main__':
    unittest.main()
