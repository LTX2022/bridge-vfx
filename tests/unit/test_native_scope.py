"""Software accounting and signed supervisor-receipt fixtures; no DCC execution."""
import copy
import hashlib
import json
import secrets
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/dcc-task-runtime/src'))
from dcc_task_runtime import native_scope, owned_process


def software_scope(root, **scope_fields):
    """Initialize an explicitly authorized software-only budget fixture."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path = root/'scope.json'
    value = {'schema':'bridge.engineering-closure-scope/1',
             'output_root':str(root), 'budget':copy.deepcopy(native_scope._BUDGET),
             'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION', 'execution_authorized':True,
             'evidence_source':'software_test',
             'accounting':{'key_path':str(root/'.native-control/key'),
                           'key_sha256':hashlib.sha256(key).hexdigest()}}
    value.update(scope_fields)
    path.write_text(json.dumps(value),encoding='utf-8')
    binding = {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    native_scope.NativeScope.initialize(binding,key=key)
    return binding


class NativeScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'scope.json'
        self.binding = software_scope(self.root)
        self.scope = native_scope.NativeScope(self.binding)

    def stop(self, ticket, code=0):
        directory = Path(ticket['directory']); directory.mkdir(exist_ok=True)
        scope_root = next(root for root in directory.parents if (root / 'scope.json').is_file())
        scope_path = scope_root / 'scope.json'
        binding = {'path': str(scope_path), 'sha256': hashlib.sha256(scope_path.read_bytes()).hexdigest()}
        admitted = native_scope.NativeScope(binding).snapshot()['tickets']
        stopped_at = max(value['admitted_at'] for value in admitted) + .1
        (directory / 'receipt.key').write_bytes(b'fixture-secret')
        start = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': ticket['identity'],
                 'pid': 123, 'execution_protocol': 1, 'observed_at': ticket['admitted_at']}
        owned_process._signed_write(directory, start)
        stop = dict(start, event='stopped', observed_at=stopped_at,
            started_sha256=hashlib.sha256(owned_process._canonical(start)).hexdigest(),
            observed_by='owned_child_wait', exit_code=code, descendant_result_unobserved=False,
            stop_reason=None, supervisor_exit_code=0, execution_result='failed' if code else 'succeeded')
        owned_process._signed_write(directory, stop)

    def test_slow_disk_observation_does_not_hold_accounting_transaction(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def disk_usage(budget):
            if threading.current_thread().name == 'slow-scope-observer':
                entered.set()
                if not release.wait(5): raise AssertionError('disk barrier was not released')
            return 0
        def check(*, signal=False):
            try: self.scope.check()
            except BaseException as error: failures.append(error)
            finally:
                if signal: completed.set()
        with mock.patch.object(owned_process, '_disk_usage', side_effect=disk_usage):
            first = threading.Thread(target=check, name='slow-scope-observer')
            second = threading.Thread(target=lambda: check(signal=True))
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                second.start()
                self.assertTrue(completed.wait(2), 'independent scope check waited for recursive disk traversal')
                ticket = self.scope.admit('alpha-husk', self.root/'concurrent', {'op':'concurrent'})
            finally:
                release.set(); first.join(5)
                if second.ident is not None: second.join(5)
        self.assertFalse(failures, [str(error) for error in failures])
        state = self.scope.snapshot()
        self.assertEqual(state['dcc_starts'], 1)
        self.assertEqual(state['tickets'][0]['id'], ticket['id'])
        self.assertIsNone(state['tickets'][0]['stopped_at'])

    def test_restart_idempotency_unknown_stop_and_signed_release(self):
        self.assertEqual(self.scope.snapshot()['dcc_starts'], 0)
        before = self.scope.state_path.read_bytes()
        self.scope.snapshot()
        self.assertEqual(self.scope.state_path.read_bytes(), before)
        ticket = self.scope.admit('alpha-husk', self.root/'a', {'op': 'a'})
        self.assertFalse(ticket['reused'])
        restored = native_scope.NativeScope(self.binding)
        self.assertTrue(restored.admit('alpha-husk', self.root/'a', {'op': 'a'})['reused'])
        with mock.patch.object(restored, '_save', wraps=restored._save) as save:
            self.assertEqual(restored.check()['dcc_starts'], 1)
            save.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'STOP_UNKNOWN'): restored.finish(ticket)
        with self.assertRaisesRegex(ValueError, 'HEAVY_BUSY'):
            restored.admit('alpha-nuke', self.root/'b', {'op':'b'})
        self.stop(ticket)
        original_state=restored.state_path.read_bytes()
        original_journal=restored.journal_path.read_bytes()
        resumed=native_scope.NativeScope(self.binding)
        observed=resumed.snapshot()
        self.assertIsNotNone(observed['tickets'][0]['stopped_at'])
        self.assertEqual(resumed.state_path.read_bytes(),original_state)
        self.assertEqual(resumed.journal_path.read_bytes(),original_journal)
        resumed.admit('alpha-nuke', self.root/'b', {'op':'b'})
        self.assertIsNotNone(resumed.finish(ticket)['stopped_at'])

    def test_failure_and_tampered_receipt_do_not_enable_more_launches(self):
        ticket = self.scope.admit('alpha-husk', self.root/'a', {'op':'a'})
        self.stop(ticket, code=1)
        with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'): self.scope.finish(ticket)
        with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
            native_scope.NativeScope(self.binding).admit('alpha-nuke', self.root/'b', {'op':'b'})

    def test_parent_tree_stop_releases_child_but_wrong_parent_is_rejected(self):
        parent = self.scope.admit('houdini-host', self.root/'host', {'op':'host'}, heavy=False)
        with self.assertRaisesRegex(ValueError, 'PARENT_INVALID'):
            self.scope.admit('main-husk', self.root/'wrong', {'op':'wrong'}, parent=parent)
        child = self.scope.admit('main-husk', parent['directory'], parent['identity'], parent=parent)
        with self.assertRaisesRegex(ValueError, 'STOP_UNKNOWN'): self.scope.finish(child)
        self.stop(parent)
        self.scope.finish(parent)
        self.assertIsNotNone(self.scope.finish(child)['stopped_at'])
        self.assertEqual(self.scope.check()['dcc_starts'], 2)

    def test_drift_symlink_and_original_six_launch_scope_are_rejected(self):
        prepared_root=self.root/'prepared'
        binding=software_scope(prepared_root,execution_authorized=False,
            status='PREPARED_REQUIRES_EXPLICIT_LIVE_SCOPE_APPROVAL')
        prepared=native_scope.NativeScope(binding)
        with self.assertRaisesRegex(ValueError,'EXECUTION_NOT_AUTHORIZED'):
            prepared.admit('alpha-husk',prepared_root/'operation',{'op':'not-approved'})
        self.assertEqual(prepared.snapshot()['dcc_starts'],0)
        self.path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'CHANGED'): self.scope.check()
        other = self.root/'link'; other.symlink_to(self.path)
        with self.assertRaises(ValueError): native_scope.NativeScope(dict(self.binding,path=str(other)))
        budget = copy.deepcopy(native_scope._BUDGET); budget['max_dcc_starts']=6
        self.path.write_text(json.dumps({'schema':'bridge.engineering-closure-scope/1',
            'output_root':str(self.root),'budget':budget}))
        with self.assertRaisesRegex(ValueError, 'BUDGET_INVALID'):
            native_scope.NativeScope(dict(self.binding,sha256=hashlib.sha256(self.path.read_bytes()).hexdigest()))

    def test_bad_stop_disk_exhaustion_and_validation_failure_remain_closed(self):
        for failure in ('bad-stop', 'wrong-start', 'nonfinite-state', 'disk', 'alpha-validation', 'delete-state', 'rollback', 'drop-ticket', 'fake-stop'):
            with self.subTest(failure=failure):
                root = self.root/failure; root.mkdir()
                path = root/'scope.json'
                key=secrets.token_bytes(32)
                path.write_text(json.dumps({'schema':'bridge.engineering-closure-scope/1',
                    'output_root':str(root), 'budget':native_scope._BUDGET,
                    'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION', 'execution_authorized':True,
                    'evidence_source':'software_test',
                    'accounting':{'key_path':str(root/'.native-control/key'),
                                  'key_sha256':hashlib.sha256(key).hexdigest()}}))
                binding = {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                scope = native_scope.NativeScope.initialize(binding,key=key)
                initial_state = scope.state_path.read_bytes()
                initial_journal = scope.journal_path.read_bytes()
                ticket = scope.admit('alpha-husk', root/'a', {'op':failure})
                if failure == 'bad-stop':
                    self.stop(ticket)
                    stop_path = Path(ticket['directory'])/'stopped.json'
                    receipt = json.loads(stop_path.read_text()); receipt['payload']['exit_code']=5
                    stop_path.write_text(json.dumps(receipt))
                    with self.assertRaisesRegex(ValueError, 'STOP_INVALID'): scope.check()
                elif failure == 'wrong-start':
                    self.stop(ticket)
                    path = Path(ticket['directory'])/'stopped.json'
                    payload = json.loads(path.read_text())['payload']
                    payload['started_sha256'] = '0'*64
                    owned_process._signed_write(Path(ticket['directory']), payload)
                    with self.assertRaisesRegex(ValueError, 'STOP_INVALID'): scope.check()
                elif failure == 'nonfinite-state':
                    state = json.loads(scope.state_path.read_text())
                    state['payload']['state']['tickets'][0]['admitted_at'] = float('nan')
                    scope.state_path.write_text(json.dumps(state))
                    with self.assertRaises(ValueError): scope.check()
                elif failure == 'disk':
                    with mock.patch.object(owned_process, '_disk_usage', return_value=536870913):
                        with self.assertRaisesRegex(ValueError, 'DISK_EXHAUSTED'): scope.check()
                elif failure == 'delete-state':
                    scope.state_path.unlink()
                    with self.assertRaises(ValueError): native_scope.NativeScope(binding)
                    with self.assertRaises(ValueError): native_scope.NativeScope.initialize(binding,key=key)
                elif failure == 'rollback':
                    scope.state_path.write_bytes(initial_state)
                    scope.journal_path.write_bytes(initial_journal)
                    with self.assertRaises(ValueError): native_scope.NativeScope(binding)
                elif failure in ('drop-ticket','fake-stop'):
                    value=json.loads(scope.state_path.read_text())
                    if failure=='drop-ticket': value['payload']['state']['tickets']=[]
                    else: value['payload']['state']['tickets'][0]['stopped_at']=ticket['admitted_at']+.1
                    scope.state_path.write_text(json.dumps(value))
                    with self.assertRaises(ValueError): native_scope.NativeScope(binding)
                else:
                    scope.fail('ALPHA_VALIDATION_FAILED')
                with self.assertRaises(ValueError):
                    native_scope.NativeScope(binding).admit('alpha-nuke', root/'b', {'op':'next'})

    def test_role_limits_time_and_disk_are_persistent(self):
        with self.assertRaisesRegex(ValueError, 'ADMISSION_INVALID'):
            self.scope.admit('alpha-husk', self.root/'a', {'op':'a'}, heavy=False)
        self.scope.admit('houdini-host', self.root/'a', {'op':'a'}, heavy=False)
        with self.assertRaisesRegex(ValueError, 'STARTS_EXHAUSTED'):
            self.scope.admit('houdini-host', self.root/'b', {'op':'b'}, heavy=False)
            self.scope.admit('houdini-host', self.root/'c', {'op':'c'}, heavy=False)
        with mock.patch.object(native_scope.time, 'time', return_value=100000000000):
            with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'): self.scope.check()
        with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'): native_scope.NativeScope(self.binding).check()

if __name__ == '__main__': unittest.main()
