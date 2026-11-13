"""Pure file and caller-lock contracts; no addon, producer or DCC executes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
sys.path.insert(0, str(ROOT / 'tests/helpers'))

from dcc_task_runtime import platform_support
from dcc_task_runtime.execution_lock import execution_lock
from houdini_bridge.operation_receipts import SCHEMA, canonical_sha256, operation_receipt_sha256
from houdini_bridge.operation_receipt_store import record_path, load_record, write_record
from graph_job_process_fixture import directory_alias


def fixture_record(operation_id='native-1', task_id='task-1', state='INTENT'):
    identity = {'task_id': task_id, 'pid': os.getpid(), 'scene_epoch': 0,
                'session_id': 'file-fixture', 'launch_nonce': 'fixture',
                'process_generation': 'fixture', 'plugin_build': 'fixture'}
    request = {'task_id': task_id, 'operation_id': operation_id, 'request_id': operation_id,
               'frozen_input_manifest': [], 'name': '灯光'}
    before = {'host_identity': identity, 'scene_contract': None}
    record = {'schema': SCHEMA, 'kind': 'build', 'stage': 'build', 'command': 'scene.create_task_root',
              'state': state, 'task_id': task_id, 'operation_id': operation_id, 'request_id': operation_id,
              'request': request, 'request_sha256': canonical_sha256({'task_id': task_id,
                  'command': 'scene.create_task_root', 'request_id': operation_id, 'request': request}),
              'host_identity': identity, 'before_scene': before, 'frozen_input_manifest': [],
              'frozen_inputs_sha256': canonical_sha256([]), 'execution_boundary': 'file_fixture',
              'started_at': 'file-fixture'}
    if state == 'COMPLETED':
        contract = {'schema': 'houdini.task_scene_contract/2.0', 'task_id': task_id,
                    'nodes': [{'path': '/obj/file_fixture'}]}
        result = {'path': '/obj/file_fixture'}
        record.update(after_scene={'host_identity': identity, 'scene_contract': contract,
                                  'scene_contract_sha256': canonical_sha256(contract)},
                      result=result, facts={'scope': 'build', 'handler_result_sha256': canonical_sha256(result)})
    if state == 'FAILED':
        record['error'] = {'code': 'FILE_FIXTURE', 'message': 'synthetic native failure'}
    record['operation_receipt_sha256'] = operation_receipt_sha256(record)
    return record


class OperationReceiptStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/private/tmp', prefix='operation-receipt-store-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runner = self.root / 'runner.json'
        self.task_id = 'task-1'

    @contextmanager
    def locked(self):
        with execution_lock(self.runner.parent, self.task_id):
            yield

    def test_missing_load_has_no_side_effect_and_path_hashes_case_and_reserved_ids(self):
        before = list(self.root.iterdir())
        self.assertIsNone(load_record(self.runner, self.task_id, 'Op'))
        self.assertEqual(list(self.root.iterdir()), before)
        for operation_id in ('Op', 'op', 'CON', '..'):
            path = record_path(self.runner, self.task_id, operation_id)
            self.assertEqual(path.name, hashlib.sha256(operation_id.encode()).hexdigest() + '.json')
            self.assertEqual(path.parent.name, hashlib.sha256(self.task_id.encode()).hexdigest())
        self.assertNotEqual(record_path(self.runner, self.task_id, 'Op'), record_path(self.runner, self.task_id, 'op'))
        for invalid in ('', 'a' * 101, '../escape', 'op/name', 'op\\name', 'op:stream', 'op\x00'):
            with self.subTest(operation=invalid), self.assertRaises(ValueError):
                record_path(self.runner, self.task_id, invalid)
        with self.assertRaises(ValueError):
            record_path(Path('runner.json'), self.task_id, 'op')

    def test_intent_completed_and_failed_roundtrip_preserve_exact_schema_private_utf8(self):
        with self.locked():
            for operation_id, terminal in (('normal', 'COMPLETED'), ('failure', 'FAILED')):
                intent = fixture_record(operation_id)
                path = write_record(self.runner, self.task_id, operation_id, intent)
                self.assertTrue(platform_support.private_permissions_valid(path))
                self.assertIn('灯光'.encode('utf-8'), path.read_bytes())
                self.assertEqual(load_record(self.runner, self.task_id, operation_id), intent)
                finished = fixture_record(operation_id, state=terminal)
                write_record(self.runner, self.task_id, operation_id, finished, expected=intent)
                self.assertEqual(load_record(self.runner, self.task_id, operation_id), finished)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), finished)
        self.assertFalse(self.runner.exists())

    def test_no_existing_record_overwrite_or_reexecution_and_terminal_requires_exact_intent(self):
        with self.locked():
            intent = fixture_record()
            completed = fixture_record(state='COMPLETED')
            with self.assertRaises(ValueError):
                write_record(self.runner, self.task_id, 'native-1', completed)
            path = write_record(self.runner, self.task_id, 'native-1', intent)
            original = path.read_bytes()
            stale = copy.deepcopy(intent)
            stale['started_at'] = 'stale'
            for record, expected in ((intent, None), (intent, intent), (completed, stale)):
                with self.assertRaises(ValueError):
                    write_record(self.runner, self.task_id, 'native-1', record, expected=expected)
                self.assertEqual(path.read_bytes(), original)
            changed = fixture_record(state='FAILED')
            changed['started_at'] = 'different-host-attempt'
            changed['operation_receipt_sha256'] = operation_receipt_sha256(changed)
            with self.assertRaises(ValueError):
                write_record(self.runner, self.task_id, 'native-1', changed, expected=intent)
            write_record(self.runner, self.task_id, 'native-1', completed, expected=intent)
            terminal = path.read_bytes()
            with self.assertRaises(ValueError):
                write_record(self.runner, self.task_id, 'native-1', fixture_record(state='FAILED'), expected=completed)
            self.assertEqual(path.read_bytes(), terminal)

    def test_new_policy_roundtrip_preserves_digest_and_rejects_removed_boundary(self):
        from test_scene_contract_header import locked_contract
        with self.locked():
            intent = fixture_record()
            path = write_record(self.runner, self.task_id, 'native-1', intent)
            completed = fixture_record(state='COMPLETED')
            contract = locked_contract(self.task_id)
            completed['after_scene'].update(scene_contract=contract, scene_contract_sha256=canonical_sha256(contract))
            completed['operation_receipt_sha256'] = operation_receipt_sha256(completed)
            broken = copy.deepcopy(completed)
            broken['after_scene']['scene_contract'].pop('hda_boundaries')
            broken['after_scene']['scene_contract_sha256'] = canonical_sha256(broken['after_scene']['scene_contract'])
            broken['operation_receipt_sha256'] = operation_receipt_sha256(broken)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'HDA boundaries'):
                write_record(self.runner, self.task_id, 'native-1', broken, expected=intent)
            self.assertEqual(path.read_bytes(), original)
            write_record(self.runner, self.task_id, 'native-1', completed, expected=intent)
            before = path.read_bytes()
            self.assertEqual(load_record(self.runner, self.task_id, 'native-1'), completed)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(load_record(self.runner, self.task_id, 'native-1')['operation_receipt_sha256'],
                             completed['operation_receipt_sha256'])

    def test_wrong_task_operation_schema_and_digest_rejected_without_modifying_record(self):
        with self.locked():
            intent = fixture_record()
            path = write_record(self.runner, self.task_id, 'native-1', intent)
            original = path.read_bytes()
            for key, value in (('task_id', 'foreign'), ('operation_id', 'foreign'),
                               ('schema', 'foreign'), ('operation_receipt_sha256', '0' * 64)):
                altered = {**intent, key: value}
                with self.subTest(field=key), self.assertRaises(ValueError):
                    write_record(self.runner, self.task_id, 'native-1', altered, expected=intent)
                self.assertEqual(path.read_bytes(), original)
            platform_support.atomic_write(path, json.dumps(fixture_record(task_id='foreign')).encode(), owned_root=self.root)
            with self.assertRaises(ValueError):
                load_record(self.runner, self.task_id, 'native-1')

    def test_atomic_replace_failure_preserves_intent_and_removes_temporary(self):
        with self.locked():
            intent = fixture_record()
            path = write_record(self.runner, self.task_id, 'native-1', intent)
            original = path.read_bytes()
            with mock.patch.object(platform_support, 'atomic_replace', side_effect=OSError('filesystem unavailable')):
                with self.assertRaises(OSError):
                    write_record(self.runner, self.task_id, 'native-1', fixture_record(state='COMPLETED'), expected=intent)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_corrupt_empty_duplicate_or_nonprivate_files_never_become_missing(self):
        with self.locked():
            path = write_record(self.runner, self.task_id, 'native-1', fixture_record())
            for data in (b'', b'{', b'{"task_id":"task-1","task_id":"foreign"}', b'\xff'):
                platform_support.atomic_write(path, data, owned_root=self.root)
                with self.assertRaises(ValueError):
                    load_record(self.runner, self.task_id, 'native-1')
                self.assertEqual(path.read_bytes(), data)
            platform_support.atomic_write(path, json.dumps(fixture_record()).encode(), owned_root=self.root)
            with mock.patch.object(platform_support, 'private_permissions_valid', return_value=False):
                with self.assertRaisesRegex(ValueError, 'FILE_NOT_PRIVATE'):
                    load_record(self.runner, self.task_id, 'native-1')

    def test_actual_directory_link_and_hardlinked_record_rejected(self):
        linked = self.root / 'linked'
        target = self.root / 'target'
        target.mkdir()
        directory_alias(linked, target)
        with self.assertRaises(ValueError):
            load_record(linked / 'runner.json', self.task_id, 'native-1')
        with self.assertRaises(ValueError):
            write_record(linked / 'runner.json', self.task_id, 'native-1', fixture_record())
        if linked.is_symlink():
            linked.unlink()
        else:
            linked.rmdir()
        with self.locked():
            path = write_record(self.runner, self.task_id, 'native-1', fixture_record())
            alias = self.root / 'hardlink.json'
            os.link(path, alias)
            with self.assertRaises(ValueError):
                load_record(self.runner, self.task_id, 'native-1')
            with self.assertRaises(ValueError):
                write_record(self.runner, self.task_id, 'native-1', fixture_record(), expected=fixture_record())

    def test_each_write_touches_one_record_and_preserves_legacy_and_unrelated_files(self):
        self.runner.write_bytes(b'{"producer_operations":{"old":{"state":"INTENT"}}}')
        legacy = self.runner.read_bytes()
        with self.locked():
            first = write_record(self.runner, self.task_id, 'old', fixture_record('old'))
            first_bytes = first.read_bytes()
            unrelated = first.with_name('unrelated.json')
            unrelated.write_bytes(b'corrupt unrelated data must never be read')
            with mock.patch.object(platform_support, 'atomic_write', wraps=platform_support.atomic_write) as writes:
                second = write_record(self.runner, self.task_id, 'new', fixture_record('new'))
            self.assertEqual(writes.call_count, 1)
            self.assertEqual(writes.call_args.args[0], second)
            self.assertEqual(first.read_bytes(), first_bytes)
            self.assertEqual(unrelated.read_bytes(), b'corrupt unrelated data must never be read')
        self.assertEqual(self.runner.read_bytes(), legacy)

    def test_caller_task_lock_excludes_concurrent_writer_without_helper_lock_acquisition(self):
        entered = threading.Event()
        release = threading.Event()
        def owner():
            with self.locked():
                intent = fixture_record()
                write_record(self.runner, self.task_id, 'native-1', intent)
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('caller lock release missing')
                write_record(self.runner, self.task_id, 'native-1', fixture_record(state='COMPLETED'), expected=intent)
        def contender():
            self.assertTrue(entered.wait(5))
            with self.assertRaises(Exception) as rejected:
                with self.locked():
                    write_record(self.runner, self.task_id, 'native-1', fixture_record())
            self.assertIn('another executor', str(rejected.exception))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(owner)
            try:
                pool.submit(contender).result(timeout=5)
            finally:
                release.set()
            first.result(timeout=5)
        with self.locked(), mock.patch('dcc_task_runtime.execution_lock.execution_lock', side_effect=AssertionError('second lock')):
            self.assertEqual(load_record(self.runner, self.task_id, 'native-1')['state'], 'COMPLETED')
            write_record(self.runner, self.task_id, 'next', fixture_record('next'))


if __name__ == '__main__':
    unittest.main()
