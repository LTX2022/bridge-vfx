"""Public save admission with actual addon producers and explicit HOM/transport fakes."""
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

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
sys.path.insert(0, str(ROOT / 'tools'))

from houdini_bridge.operation_receipt_store import load_record, record_path
from houdini_bridge.operation_receipts import (
    canonical_sha256, operation_receipt_sha256, validate_operation_receipt,
)
from source_host_fixture import FakeSourceHost
from vfx_pipeline.feedback_versions import FeedbackVersions
from vfx_pipeline.production_hosts import _scene_transition_operation_store_path
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary, ProductionBoundaryError
from vfx_pipeline.workbuddy_graph_mcp import GraphRun


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AddonSaveTransport:
    def __init__(self, addon):
        self.addon = addon
        self.calls = []
        self.health_reads = []
        self.produced = []
        self.after_save = None

    def health(self):
        result = self.addon.dispatch('health', {})
        self.health_reads.append(deepcopy(result['task_host_identity']))
        return result

    def call(self, command, params):
        if command != 'scene.save_hip':
            raise AssertionError('public save fixture permits only native HIP saves')
        self.calls.append((command, deepcopy(params)))
        result = self.addon.dispatch(command, params)
        self.produced.append(deepcopy(result))
        if self.after_save is not None:
            self.after_save(result)
        return result


class FormalPublicTaskSaveTests(unittest.TestCase):
    def setUp(self):
        output = ROOT / 'outputs/all-domain-20261009/public-save-tests'
        output.mkdir(parents=True, exist_ok=True)
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix='public-save-', dir=output)))
        self.control = self.directory / 'control'
        self.control.mkdir()
        self.save_root = self.directory / 'saves'
        self.save_root.mkdir()
        self.owner = 'abc123'
        self.manifest = self.control / 'run.json'
        self.manifest.write_text(json.dumps({
            'schema': 'bridge.workbuddy.diagnostic_run/1.0',
            'run_id': 'public-save-unit', 'assets': [], 'construction_authorized': True,
        }), encoding='utf-8')
        names = (
            'plugins/houdini/_impl/houdini_bridge_addon.py',
            'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py',
            'packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py',
            'packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py',
        )
        entries = []
        for name in names:
            frozen = self.control / 'snapshot' / name
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes((ROOT / name).read_bytes())
            entries.append({'path': name, 'sha256': file_digest(frozen)})
        index = self.control / 'snapshot-manifest.json'
        index.write_text(json.dumps({'files': entries}), encoding='utf-8')
        self.source = {
            'backend': 'production', 'manifest_path': str(self.manifest),
            'manifest_sha256': file_digest(self.manifest),
            'repo_root': str(self.control / 'snapshot'),
            'snapshot_manifest_sha256': file_digest(index),
        }
        addon_path = self.control / 'snapshot' / names[0]
        spec = importlib.util.spec_from_file_location('_formal_public_save_addon', ROOT / names[0])
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)
        self.host = self.enterContext(FakeSourceHost(self.addon))
        self.host.state_path = self.control / 'houdini-instances' / 'source-state.json'
        self.enterContext(patch.object(self.addon, '_state_dir',
            return_value=self.control / 'houdini-instances' / 'instances'))
        self.enterContext(patch.object(self.addon, '_fx_state_path',
            return_value=self.host.state_path))
        self.addon._FX_OPERATIONS = None
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(),
            task_id=self.owner, pid=os.getpid(), launch_nonce='public-save-unit-launch',
            plugin_build=file_digest(addon_path), version=self.host.version)
        self.host.build()
        self.transport = AddonSaveTransport(self.addon)
        self.client = _ConfiguredBoundary(kind='houdini', transport=self.transport, config={
            'expected_identity': self.addon._host_identity(), 'evidence_source': 'software_test',
            'application': 'houdini', 'version': self.host.version,
            'plugin_build': file_digest(addon_path), 'transport': 'http',
            'host': '127.0.0.1', 'port': 54321, 'executable': '/not-started/houdini',
            'task_root': str(self.directory), 'controller_root': str(self.control),
        }, state_dir=self.control / 'client')
        self.client.bind_task(self.owner)
        self.facade = self.open_facade()
        FeedbackVersions(self.facade).register_completed('public-save-graph', {
            'graph_hash': self.host.manifest().get('graph_hash', ''),
            'outputs': [{'output_id': 'domain_output'}],
        })
        self.runner_path = _scene_transition_operation_store_path(self.control, self.owner)

    def open_facade(self):
        facade = GraphRun(self.manifest, None, task_id=self.owner,
            host_client=self.client, save_root=str(self.save_root))
        facade.backend_kind = 'production'
        facade.controller_source = dict(self.source)
        return facade

    def assert_no_saved_scene(self):
        with self.open_facade()._connect() as database:
            self.assertEqual(database.execute('SELECT * FROM save_receipts').fetchall(), [])

    def assert_rejected_after_save(self, error, message):
        with self.assertRaisesRegex(error, message):
            self.facade.task_save()
        self.assertEqual(len(self.transport.produced), 1)
        validate_operation_receipt(self.transport.produced[0]['operation_receipt'])
        self.assertEqual(self.transport.produced[0]['operation_receipt']['state'], 'COMPLETED')
        self.assert_no_saved_scene()

    def replace_persisted_record(self, result, record):
        record['operation_receipt_sha256'] = operation_receipt_sha256(record)
        validate_operation_receipt(record)
        path = Path(result['operation_store_path'])
        path.write_text(json.dumps(record), encoding='utf-8')
        self.assertEqual(load_record(self.runner_path, self.owner, record['operation_id']), record)

    def test_public_save_persists_actual_producer_hip_snapshot_contract_and_dependencies(self):
        saved = self.facade.task_save()
        produced = self.transport.produced[0]
        record = produced['operation_receipt']
        validate_operation_receipt(record)
        self.assertEqual(self.transport.calls, [('scene.save_hip', record['request'])])
        self.assertTrue(record['operation_id'].startswith('task-save-'))
        self.assertEqual(record['request_id'], record['operation_id'])
        self.assertEqual(record['execution_boundary'], 'software_hou_api')
        self.assertEqual(record['host_identity']['pid'], os.getpid())
        self.assertEqual(len(self.transport.health_reads), 3)
        self.assertTrue(all(identity == record['host_identity']
                            for identity in self.transport.health_reads))
        self.assertEqual(Path(produced['operation_store_path']),
            record_path(self.runner_path, self.owner, record['operation_id']))
        self.assertEqual(load_record(self.runner_path, self.owner, record['operation_id']), record)
        hip = Path(saved['path'])
        snapshot = Path(record['facts']['saved_scene']['snapshot_path'])
        self.assertEqual(hip.parent, self.save_root)
        self.assertTrue(hip.read_bytes())
        self.assertEqual(snapshot.read_bytes(), hip.read_bytes())
        self.assertEqual(file_digest(hip), saved['sha256'])
        self.assertEqual(saved['scene_contract'], self.addon._fx_capture_scene_contract(self.owner))
        self.assertEqual(saved['scene_contract_sha256'], canonical_sha256(saved['scene_contract']))
        self.assertEqual(saved['feedback_dependencies'], [
            'graph:abc123:public-save-graph:output:domain_output',
            'graph:abc123:public-save-graph:version:0',
        ])
        stored = self.open_facade()._resolve_receipt(saved['saved_scene_id'])
        self.assertEqual(stored, {key: value for key, value in saved.items() if key != 'saved_scene_id'})
        second = self.facade.task_save()
        self.assertNotEqual(second['path'], saved['path'])
        self.assertNotEqual(second['saved_scene_id'], saved['saved_scene_id'])
        self.assertEqual(file_digest(hip), saved['sha256'])

    def test_attached_boundary_without_optional_controller_root_saves_owned_producer(self):
        self.client.production_config.pop('controller_root')
        saved = self.facade.task_save()
        record = saved['operation_receipt']
        self.assertEqual(load_record(self.runner_path, self.owner, record['operation_id']), record)
        self.assertEqual(file_digest(saved['path']), saved['sha256'])
        self.assertEqual(self.open_facade()._resolve_receipt(saved['saved_scene_id'])['path'], saved['path'])

    def test_changed_live_pid_after_native_save_is_rejected(self):
        def change_pid(result):
            self.addon._TASK_HOST_IDENTITY['pid'] += 1

        self.transport.after_save = change_pid
        self.assert_rejected_after_save(ProductionBoundaryError, 'PRODUCTION_HOST_IDENTITY_MISMATCH:pid')

    def test_rehashed_receipt_from_another_pid_is_rejected(self):
        def change_pid(result):
            record = result['operation_receipt']
            record['host_identity']['pid'] += 1
            for phase in ('before_scene', 'after_scene'):
                record[phase]['host_identity'] = deepcopy(record['host_identity'])
            self.replace_persisted_record(result, record)

        self.transport.after_save = change_pid
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_HOST_MISMATCH')

    def test_missing_actual_hip_after_native_save_is_rejected(self):
        self.transport.after_save = lambda result: Path(result['path']).unlink()
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_BINDING_MISMATCH')

    def test_changed_actual_hip_after_native_save_is_rejected(self):
        def change_hip(result):
            path = Path(result['path'])
            path.write_bytes(path.read_bytes() + b'changed HIP')

        self.transport.after_save = change_hip
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_BINDING_MISMATCH')

    def test_valid_but_different_persisted_producer_is_rejected(self):
        def change_store(result):
            record = deepcopy(result['operation_receipt'])
            record['completed_at'] = '2000-01-01T00:00:00+00:00'
            self.replace_persisted_record(result, record)

        self.transport.after_save = change_store
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_STORAGE_MISMATCH')

    def test_identical_producer_at_noncanonical_store_path_is_rejected(self):
        def relocate(result):
            copied = self.control / 'other-producer.json'
            copied.write_bytes(Path(result['operation_store_path']).read_bytes())
            result['operation_store_path'] = str(copied)

        self.transport.after_save = relocate
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_STORAGE_MISMATCH')

    def test_changed_frozen_hip_snapshot_after_native_save_is_rejected(self):
        def change_snapshot(result):
            snapshot = Path(result['operation_receipt']['facts']['saved_scene']['snapshot_path'])
            snapshot.chmod(0o600)
            snapshot.write_bytes(snapshot.read_bytes() + b'changed frozen HIP')

        self.transport.after_save = change_snapshot
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_BINDING_MISMATCH')

    def test_changed_frozen_controller_source_after_native_save_is_rejected(self):
        def change_source(result):
            source = self.control / 'snapshot/packages/houdini-bridge/src/houdini_bridge/operation_receipts.py'
            source.write_bytes(source.read_bytes() + b'\nchanged frozen dependency')

        self.transport.after_save = change_source
        self.assert_rejected_after_save(ValueError, 'configured producer source bytes changed')

    def test_rehashed_handler_contract_different_from_actual_scene_is_rejected(self):
        def change_contract(result):
            result['scene_contract']['execution_root'] = '/obj/foreign-scene'
            result['scene_contract_sha256'] = canonical_sha256(result['scene_contract'])
            record = result['operation_receipt']
            record['result'] = {key: deepcopy(value) for key, value in result.items() if key not in {
                'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent'}}
            record['facts']['handler_result_sha256'] = canonical_sha256(record['result'])
            self.replace_persisted_record(result, record)

        self.transport.after_save = change_contract
        self.assert_rejected_after_save(ValueError, 'FORMAL_TYPED_SAVE_BINDING_MISMATCH')


if __name__ == '__main__':
    unittest.main(verbosity=2)
