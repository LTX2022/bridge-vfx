"""Real file-sharing boundaries, without DCC operations or completion fixtures."""
import ctypes
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from houdini_bridge import client
from houdini_bridge import render_observation_budget as budget


class RenderStoreSnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix='快照 sharing '))
        self.path = Path(directory) / 'operations.json'
        self.path.write_text('{"state":"RUNNING"}', encoding='utf-8')

    def test_snapshot_is_read_without_mutation(self):
        before = self.path.read_bytes()
        self.assertEqual(client._read_render_store_snapshot(self.path), {'state': 'RUNNING'})
        self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_json_is_not_retried(self):
        self.path.write_text('{', encoding='utf-8')
        with patch.object(client, 'read_store_payload', return_value='{') as reads:
            with self.assertRaises(json.JSONDecodeError):
                client._read_render_store_snapshot(self.path)
        self.assertEqual(reads.call_count, 1)

    def test_missing_snapshot_is_not_retried(self):
        self.path.unlink()
        with patch.object(client.time, 'sleep', side_effect=AssertionError('missing file must propagate')):
            with self.assertRaises(FileNotFoundError):
                client._read_render_store_snapshot(self.path)

    def test_symlink_is_rejected_before_read(self):
        with patch.object(Path, 'is_symlink', return_value=True), \
                patch.object(client, 'read_store_payload', side_effect=AssertionError('linked snapshot must not be read')):
            with self.assertRaisesRegex(client.BridgeError, 'symlink'):
                client._read_render_store_snapshot(self.path)

    def test_store_and_render_record_limits_preserve_original_files(self):
        for kind in ('whole-store', 'render-record'):
            with self.subTest(kind=kind):
                if kind == 'whole-store':
                    with self.path.open('wb') as stream:
                        stream.truncate(budget.MAX_STORE_BYTES + 1)
                else:
                    self.path.write_text(json.dumps({'operations': {'render-one': {
                        'kind': 'render', 'padding': 'X' * budget.MAX_OPERATION_BYTES}}}), encoding='utf-8')
                before = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
                with self.assertRaises(client.BridgeError) as error:
                    client._read_render_store_snapshot(self.path)
                self.assertEqual(error.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
                self.assertEqual((self.path.stat().st_size, self.path.stat().st_mtime_ns), before)
                self.assertEqual(list(self.path.parent.glob('*.corrupt*')), [])

    def test_operation_budget_counts_full_nested_values_and_utf8(self):
        for value in ({'kind': 'render', 'padding': '\U0001f600' * (budget.MAX_OPERATION_BYTES // 3)},
                      {'kind': 'render', 'padding': [None] * budget.MAX_OPERATION_VALUES}):
            with self.subTest(value_type=type(value['padding']).__name__):
                with self.assertRaises(budget.RenderObservationLimit):
                    budget.validate_render_record(value)
        budget.validate_render_record({'kind': 'render', 'frame_config': {
            str(frame): {'color': 'scene-linear', 'snapshot': 'a' * 64} for frame in range(12)}})

    def test_render_start_reserves_terminal_fact_copies(self):
        budget.reserve_render_completion({'kind': 'render', 'frames': list(range(12)),
                                           'render_config': {'1': {'observed': 'linear'}}})
        record = {'kind': 'render', 'render_config': {'1': {
            'padding': 'X' * (budget.MAX_OPERATION_BYTES // 4)}}}
        budget.validate_render_record(record)
        with self.assertRaisesRegex(budget.RenderObservationLimit, 'completion-record'):
            budget.reserve_render_completion(record)

    def test_addon_budget_refusal_is_not_corruption_or_a_partial_save(self):
        from test_operation_runner_recovery import build_runner_module
        addon = build_runner_module(self.path.parent)
        runner = addon.OperationRunner('budget-task', self.path.parent)
        runner.path = self.path
        original = self.path.read_bytes()
        oversized = {'task_id': 'budget-task', 'operations': {
            'render-one': {'kind': 'render', 'padding': 'X' * budget.MAX_OPERATION_BYTES}}}
        with self.assertRaises(addon.BridgeCommandError) as saved_error:
            runner._save(oversized)
        self.assertEqual(saved_error.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
        self.assertEqual(self.path.read_bytes(), original)
        self.path.write_text(json.dumps(oversized), encoding='utf-8')
        before = self.path.read_bytes()
        with self.assertRaises(addon.BridgeCommandError) as loaded_error:
            runner._load()
        self.assertEqual(loaded_error.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.corrupt*')), [])

    def test_invalid_store_shapes_fail_closed_and_addon_preserves_corrupt_evidence(self):
        from test_operation_runner_recovery import build_runner_module
        addon = build_runner_module(self.path.parent)
        runner = addon.OperationRunner('budget-task', self.path.parent)
        cases = [json.dumps(value) for value in (
            [], None, {'operations': []}, {'operations': None},
            {'operations': {'invalid-record': []}}, {'operations': {'invalid-record': 0}})]
        cases.append('{"operations":{"invalid-record":' + '[' * 2000 + '0' + ']' * 2000 + '}}')
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                path = self.path.parent / ('invalid-' + str(index) + '.json')
                path.write_text(payload, encoding='utf-8')
                with self.assertRaises(client.BridgeError) as client_error:
                    client._read_render_store_snapshot(path)
                self.assertEqual(client_error.exception.code, 'OPERATION_STORE_INVALID')
                self.assertTrue(path.is_file())
                runner.path = path
                with self.assertRaises(addon.BridgeCommandError) as addon_error:
                    runner._load()
                self.assertEqual(addon_error.exception.code, 'CORRUPT_STORE')
                self.assertTrue(path.with_name(path.name + '.corrupt-blocked').is_file())
                self.assertTrue(list(path.parent.glob(path.name + '.corrupt-*')))

    def test_legacy_active_render_cannot_reset_read_allowance_or_release_unknown_slot(self):
        import sys
        from test_operation_runner_recovery import build_runner_module
        addon = build_runner_module(self.path.parent)
        runner = addon.OperationRunner('budget-task', self.path.parent)
        record = {'kind': 'render', 'request_id': 'legacy', 'state': 'QUEUED'}
        store = {'task_id': 'budget-task', 'operations': {'legacy': record}}
        permit = addon._test_scheduler.reserve(str(runner.path), 'legacy')
        with patch.dict(sys.modules, {'hou': addon.hou}):
            runner._advance_render(record, store)
        self.assertEqual(record['state'], 'RECONCILE')
        self.assertNotIn('ocio_read_budget', record)
        self.assertTrue(addon._test_scheduler.snapshot()['active'])
        addon._test_scheduler.release(str(runner.path), 'legacy', permit['token'], stopped=True)

    def test_existing_startup_attempt_requires_same_identity_and_durable_allowance(self):
        self.path.write_text(json.dumps({'task_id': 'task', 'request_id': 'request'}))
        original = self.path.read_bytes()
        for task_id, operation_id, has_budget in (
                ('task', 'request', False), ('other', 'request', True), ('task', 'other', True)):
            with self.subTest(task_id=task_id, operation_id=operation_id, has_budget=has_budget):
                with self.assertRaisesRegex(ValueError, 'unreconciled'):
                    budget.validate_preflight_attempt(self.path, task_id=task_id,
                        operation_id=operation_id, has_budget=has_budget)
                self.assertEqual(self.path.read_bytes(), original)
        budget.validate_preflight_attempt(self.path, task_id='task', operation_id='request', has_budget=True)

    def test_whole_store_reserves_terminal_capacity_and_uses_shared_writer(self):
        from houdini_bridge import operation_store
        store = {'task_id': 't', 'operations': {
            'old': {'task_id': 't', 'request_id': 'old', 'state': 'COMPLETED', 'padding': 'x' * 1400},
            'old-two': {'task_id': 't', 'request_id': 'old-two', 'state': 'COMPLETED', 'padding': 'x' * 1400},
            'live': {'task_id': 't', 'request_id': 'live', 'kind': 'render', 'state': 'RUNNING'}}}
        before = self.path.read_bytes()
        with patch.object(budget, 'MAX_STORE_BYTES', 4096), patch.object(budget, 'MAX_OPERATION_BYTES', 2048):
            budget.validate_store(store)  # Old capacity check accepted this store.
            with self.assertRaisesRegex(budget.RenderObservationLimit, 'reserved terminal capacity'):
                operation_store.write_snapshot(self.path, store)
        self.assertEqual(self.path.read_bytes(), before)
        history = {str(index): {'request_sha256': 'a' * 64,
                    'budget': {'schema': budget.FILE_BUDGET_SCHEMA, 'used_bytes': index}}
                   for index in range(9)}
        for active in ({}, {'live': {'task_id': 't', 'request_id': 'live', 'state': 'RUNNING'}},
                       {'live': {'task_id': 't', 'request_id': 'live', 'state': 'COMPLETED'}}):
            with self.subTest(active=bool(active)), patch.object(budget, 'MAX_STORE_BYTES', 6144), \
                    patch.object(budget, 'MAX_OPERATION_BYTES', 2048):
                snapshot = {'task_id': 't', 'operations': active, 'render_observation_intents': history}
                operation_store.write_snapshot(self.path, snapshot)
                self.assertEqual(json.loads(self.path.read_text())['render_observation_intents'], history)

    def test_capacity_maintenance_preserves_history_retry_and_unknown_slot_across_interruption(self):
        import copy
        from dcc_task_runtime import platform_support
        from test_operation_runner_recovery import build_runner_module, control_auth
        self.enterContext(patch.dict(os.environ, {'HOUDINI_BRIDGE_APPROVAL_SECRET': 'unit-test-control-secret-0123456789abcdef'}))
        addon = build_runner_module(self.path.parent)
        runner = addon.OperationRunner('t', self.path.parent)
        first = runner.submit({'step_params': {'frames': [2]}}, 'p', {}, request_id='completed')
        runner.cancel(first['request_id'])
        terminal = runner.status('completed')
        active = runner.submit({'step_params': {'frames': [2]}}, 'p', {}, request_id='unknown')
        store = runner._load()
        for index in range(5):
            record = copy.deepcopy(terminal)
            record['request_id'] = 'completed' if index == 0 else 'historical-' + str(index)
            record['padding'] = 'x' * 2500
            store['operations'][record['request_id']] = record
        runner.path.write_text(json.dumps(store), encoding='utf-8')
        original, slot = runner.path.read_bytes(), addon._test_scheduler.snapshot()
        authority = control_auth('compact_store', {'task_id': 't'})
        with patch.object(budget, 'MAX_STORE_BYTES', 12 * 1024), patch.object(budget, 'MAX_OPERATION_BYTES', 8 * 1024):
            self.assertGreater(len(original), budget.MAX_STORE_BYTES)
            with self.assertRaises(addon.BridgeCommandError) as too_large:
                runner._load()
            self.assertEqual(too_large.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
            # The compact writer must preserve the original if final commit fails.
            real_write = platform_support.atomic_write
            def fail_commit(path, data, **kwargs):
                if Path(path) == runner.path:
                    raise OSError('injected final snapshot failure')
                return real_write(path, data, **kwargs)
            with patch.object(platform_support, 'atomic_write', side_effect=fail_commit):
                with self.assertRaises(addon.BridgeCommandError) as failed:
                    runner.compact_store(authority)
                self.assertEqual(failed.exception.code, 'STORE_MAINTENANCE_FAILED')
            self.assertEqual(runner.path.read_bytes(), original)
            self.assertEqual(addon._test_scheduler.snapshot(), slot)
            report = runner.compact_store(authority)
            self.assertEqual(Path(report['preserved_snapshot']).read_bytes(), original)
            self.assertEqual(report['archived_operations'], 5)
            current = runner._load()
            self.assertTrue(current['operations']['completed'].get('archive_sha256'))
            self.assertEqual(runner.status('completed'), store['operations']['completed'])
            retried = runner.submit({'step_params': {'frames': [2]}}, 'p', {}, request_id='completed')
            self.assertTrue(retried['idempotent'])
            self.assertEqual(retried['record'], store['operations']['completed'])
            with self.assertRaises(addon.BridgeCommandError) as changed:
                runner.submit({'step_params': {'frames': [3]}}, 'p', {}, request_id='completed')
            self.assertEqual(changed.exception.code, 'CONTENT_CHANGED')
            self.assertEqual(addon._test_scheduler.snapshot(), slot)
            self.assertEqual(runner.status('unknown'), active['record'])
            # A real confirmed terminal can now consume its reserved room.
            runner.cancel('unknown')
            self.assertFalse(addon._test_scheduler.snapshot()['active'])
            ref = runner._load()['operations']['completed']
            archive = runner.path.with_name(runner.path.name + '.archive') / (ref['archive_sha256'] + '.json')
            archive.write_bytes(archive.read_bytes() + b' ')
            with self.assertRaises(addon.BridgeCommandError) as corrupt:
                runner.status('completed')
            self.assertEqual(corrupt.exception.code, 'OPERATION_ARCHIVE_INVALID')

    def test_maintenance_stream_parser_preserves_chunked_json_values(self):
        from houdini_bridge.operation_store import _JsonStream
        class Chunks:
            def __init__(self, parts):
                self.parts = iter(parts)
            def read(self, _size):
                return next(self.parts, '')
        for parts, expected in ((['1e', '-3'], .001), (['1.', '5'], 1.5),
                                (['"\\u4e', '2d"'], '中'), (['"中', '文"'], '中文'),
                                (['"a\\', 'n"'], 'a\n')):
            with self.subTest(parts=parts):
                parser = _JsonStream(Chunks(parts))
                self.assertEqual(parser.value(), expected)
                parser.whitespace()
                self.assertTrue(parser.eof)
                self.assertFalse(parser.buffer)
        for parts in (['{"same":1,', '"same":2}'], ['"\\uZZ', 'ZZ"']):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                _JsonStream(Chunks(parts)).value()

    def test_maintenance_rejects_unsigned_wrong_task_and_duplicate_json(self):
        from test_operation_runner_recovery import build_runner_module, control_auth
        self.enterContext(patch.dict(os.environ, {'HOUDINI_BRIDGE_APPROVAL_SECRET': 'unit-test-control-secret-0123456789abcdef'}))
        addon = build_runner_module(self.path.parent)
        runner = addon.OperationRunner('task', self.path.parent)
        cases = ('{"task_id":"other","operations":{}}',
                 '{"task_id":"task","operations":{},"operations":{}}')
        for payload in cases:
            runner.path.write_text(payload, encoding='utf-8')
            with self.assertRaises(addon.BridgeCommandError):
                runner.compact_store({'verified_by': 'not-a-signature'})
            with self.assertRaises(addon.BridgeCommandError) as denied:
                runner.compact_store(control_auth('compact_store', {'task_id': 'task'}))
            self.assertEqual(denied.exception.code, 'STORE_MAINTENANCE_FAILED')
            self.assertEqual(runner.path.read_text(encoding='utf-8'), payload)

    @unittest.skipUnless(os.name == 'nt', 'Windows error classification')
    def test_nonsharing_error_is_not_retried(self):
        with patch.object(client, 'read_store_payload', side_effect=ctypes.WinError(21)) as reads, \
                patch.object(client.time, 'sleep', side_effect=AssertionError('nonsharing error must propagate')):
            with self.assertRaises(OSError) as caught:
                client._read_render_store_snapshot(self.path)
        self.assertEqual(caught.exception.winerror, 21)
        self.assertEqual(reads.call_count, 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows native file sharing')
    def test_actual_sharing_denial_recovers_after_holder_releases(self):
        from dcc_task_runtime import windows_process
        handle = windows_process.kernel32.CreateFileW(str(self.path), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        release = threading.Event()

        def holder():
            try:
                release.wait(.06)
            finally:
                windows_process.kernel32.CloseHandle(handle)

        worker = threading.Thread(target=holder)
        worker.start()
        try:
            with self.assertRaises(PermissionError):
                self.path.read_text(encoding='utf-8')
            self.assertEqual(client._read_render_store_snapshot(self.path), {'state': 'RUNNING'})
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    @unittest.skipUnless(os.name == 'nt', 'Windows native file sharing')
    def test_persistent_actual_sharing_denial_is_bounded_and_propagates(self):
        from dcc_task_runtime import windows_process
        handle = windows_process.kernel32.CreateFileW(str(self.path), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        started = time.monotonic()
        try:
            with self.assertRaises(PermissionError) as caught:
                client._read_render_store_snapshot(self.path)
            self.assertEqual(caught.exception.errno, errno.EACCES)
        finally:
            windows_process.kernel32.CloseHandle(handle)
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == '__main__':
    unittest.main()
