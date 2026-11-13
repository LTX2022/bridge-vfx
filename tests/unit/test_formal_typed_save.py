"""Actual addon save facts using explicit in-process HOM only."""
from copy import deepcopy
import unittest

import test_readiness_native_command_evidence as native_evidence
from vfx_pipeline.domain_readiness import DomainReadinessError, DomainReadinessRunner
from houdini_bridge.operation_receipts import canonical_sha256, operation_receipt_sha256


class FormalTypedSaveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_evidence.NativeCommandEvidenceTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        case = self.fixture.prepared_case()
        self.saved = dict(case['save_receipt'], saved_scene_id='actual-native-save')
        self.current = dict(case['stage_receipts'][1]['result'], task_id=self.fixture.owner)
        self.arguments = dict(owner=self.fixture.owner, graph_id=case['graph_id'], source=self.fixture.source,
            host_identity=deepcopy(self.saved['operation_receipt']['host_identity']))

    def validate(self, saved=None, current=None):
        return DomainReadinessRunner._formal_saved_scene(
            self.saved if saved is None else saved, self.current if current is None else current,
            **self.arguments)

    def test_current_native_save_binds_owned_graph_hip_snapshot_and_source(self):
        result = self.validate()
        self.assertTrue(result['typed_save_verified'])
        self.assertEqual(result['operation_id'], self.saved['operation_receipt']['operation_id'])
        self.assertFalse(result['domain_lifecycle_verified'])

    def test_legacy_summary_remains_explicit_typed_gap(self):
        saved = {key: value for key, value in self.saved.items() if key not in {
            'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent'}}
        result = self.validate(saved)
        self.assertFalse(result['typed_save_verified'])
        self.assertEqual(result['blocker'], 'FORMAL_TYPED_TASK_SAVE_MISSING')

    def test_foreign_owner_stale_version_and_rehashed_contract_rejected(self):
        for key, value in (('task_id', 'foreign'), ('version', True), ('version', 1), ('state', 'RUNNING')):
            with self.subTest(key=key, value=value), self.assertRaisesRegex(DomainReadinessError, 'FORMAL_SAVE_INCOMPLETE'):
                self.validate(current={**self.current, key: value})
        for key, value in (('task_id', 'foreign'), ('graph_hash', 'b' * 64)):
            saved = deepcopy(self.saved)
            saved['scene_contract'][key] = value
            saved['scene_contract_sha256'] = canonical_sha256(saved['scene_contract'])
            with self.subTest(key=key), self.assertRaisesRegex(DomainReadinessError, 'FORMAL_SAVE_INCOMPLETE'):
                self.validate(saved)

    def test_changed_current_hip_and_snapshot_rejected(self):
        from pathlib import Path
        for field, blocker in (('path', 'FORMAL_SAVE_STALE'), ('snapshot_path', 'FORMAL_TYPED_SAVE_SNAPSHOT_MISMATCH')):
            path = Path(self.saved['path'] if field == 'path' else
                        self.saved['operation_receipt']['facts']['saved_scene'][field])
            original = path.read_bytes()
            mode = path.stat().st_mode
            try:
                path.chmod(0o600)
                path.write_bytes(original + b'changed')
                with self.subTest(field=field), self.assertRaisesRegex(DomainReadinessError, blocker):
                    self.validate()
            finally:
                path.write_bytes(original)
                path.chmod(mode)

    def test_rehashed_upper_receipt_cannot_replace_persisted_save(self):
        saved = deepcopy(self.saved)
        record = saved['operation_receipt']
        record['operation_id'] = record['request']['operation_id'] = 'foreign-operation'
        record['request_sha256'] = canonical_sha256({'task_id': record['task_id'],
            'command': record['command'], 'request_id': record['request_id'], 'request': record['request']})
        record['operation_receipt_sha256'] = operation_receipt_sha256(record)
        with self.assertRaisesRegex(DomainReadinessError, 'FORMAL_TYPED_SAVE_STORAGE_MISMATCH'):
            self.validate(saved)

    def test_wrong_frozen_source_and_altered_handler_result_rejected(self):
        saved = deepcopy(self.saved)
        saved['path'] = str(self.fixture.directory / 'other.hip')
        from pathlib import Path
        Path(saved['path']).write_bytes(Path(self.saved['path']).read_bytes())
        with self.assertRaisesRegex(DomainReadinessError, 'FORMAL_TYPED_SAVE_BINDING_MISMATCH'):
            self.validate(saved)
        self.arguments['source'] = {**self.arguments['source'], 'snapshot_manifest_sha256': '0' * 64}
        with self.assertRaisesRegex(DomainReadinessError, 'FORMAL_TYPED_SAVE_SOURCE_MISMATCH'):
            self.validate()

    def test_current_host_generation_pid_and_scene_epoch_are_required(self):
        original = self.arguments['host_identity']
        for key, value in (('pid', original['pid'] + 1), ('scene_epoch', original['scene_epoch'] + 1),
                           ('launch_nonce', 'another-launch'), ('process_generation', 'another-generation')):
            self.arguments['host_identity'] = {**original, key: value}
            with self.subTest(key=key), self.assertRaisesRegex(DomainReadinessError, 'FORMAL_TYPED_SAVE_HOST_MISMATCH'):
                self.validate()
        self.arguments['host_identity'] = None
        with self.assertRaisesRegex(DomainReadinessError, 'FORMAL_TYPED_SAVE_HOST_MISMATCH'):
            self.validate()
