"""Strict HIP resource accounting with signed software receipts; no DCC execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from dcc_task_runtime import native_scope, owned_process
from test_native_scope import software_scope


class HipScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def scope(self, name='hip', **changes):
        fields = {'schema': native_scope.HIP_SCOPE_SCHEMA,
                  'resource_profile': native_scope.HIP_RESOURCE_PROFILE,
                  'budget': copy.deepcopy(native_scope.HIP_BUDGET),
                  'role_seconds': copy.deepcopy(native_scope.HIP_ROLE_SECONDS)}
        fields.update(changes)
        binding = software_scope(self.root / name, **fields)
        return native_scope.NativeScope(binding)

    @staticmethod
    def stop(ticket, elapsed, *, code=0):
        directory = Path(ticket['directory']); directory.mkdir(exist_ok=True)
        (directory / 'receipt.key').write_bytes(b'fixture-secret')
        start = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': ticket['identity'],
                 'pid': 123, 'execution_protocol': 1, 'observed_at': ticket['admitted_at']}
        owned_process._signed_write(directory, start)
        owned_process._signed_write(directory, dict(start, event='stopped',
            observed_at=ticket['admitted_at'] + elapsed,
            started_sha256=hashlib.sha256(owned_process._canonical(start)).hexdigest(),
            observed_by='owned_child_wait', exit_code=code, descendant_result_unobserved=False,
            stop_reason=None, supervisor_exit_code=0,
            execution_result='failed' if code else 'succeeded'))

    @staticmethod
    def budget(scope):
        return {'roots': [str(scope.root)], 'max_bytes': 536870912, 'native_scope': scope.binding}

    def test_legacy_defaults_and_scope_are_preserved(self):
        self.assertEqual(native_scope._BUDGET, {'per_operation_seconds': 120, 'total_seconds': 600,
            'max_dcc_starts': 8, 'max_disk_bytes': 536870912, 'max_heavy_operations': 1,
            'automatic_retries': 0})
        legacy = native_scope.NativeScope(software_scope(self.root / 'legacy'))
        self.assertIsNone(legacy.resource_profile)
        self.assertTrue(all(legacy.role_seconds(role) == 120 for role in native_scope._ROLES))
        with mock.patch.object(native_scope.time, 'time', return_value=1000):
            ticket = legacy.admit('alpha-husk', legacy.root / 'graph', {'op': 'old'})
        with mock.patch.object(native_scope.time, 'time', return_value=1121):
            self.assertEqual(legacy.check()['total_seconds'], 121)
        self.assertEqual(owned_process.launch.__kwdefaults__['budget_seconds'], 120)

    def test_profile_budget_and_role_types_must_match_exactly(self):
        cases = [dict(resource_profile='forged'), dict(resource_profile=None),
                 dict(schema='bridge.hip-diagnostic-scope/3'),
                 dict(role_seconds={'graph-worker': 240.0, 'houdini-host': 120}),
                 dict(role_seconds={'graph-worker': 240, 'houdini-host': True}),
                 dict(role_seconds={'graph-worker': 240}),
                 dict(role_seconds={**native_scope.HIP_ROLE_SECONDS, 'nuke-host': 120})]
        for field in native_scope.HIP_BUDGET:
            for value in (float(native_scope.HIP_BUDGET[field]), True):
                cases.append({'budget': {**native_scope.HIP_BUDGET, field: value}})
        cases.append({'budget': {**native_scope.HIP_BUDGET, 'unknown': 1}})
        cases.append({'schema': 'bridge.engineering-closure-scope/1',
                      'budget': copy.deepcopy(native_scope._BUDGET)})
        for index, changes in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.scope(str(index), **changes)
            self.assertFalse((self.root / str(index) / 'native-scope-state.json').exists())

    def test_only_two_exact_roles_and_heavy_flags_are_admitted(self):
        scope = self.scope()
        self.assertEqual(scope.resource_profile, native_scope.HIP_RESOURCE_PROFILE)
        self.assertEqual(scope.role_seconds('graph-worker'), 240)
        self.assertEqual(scope.role_seconds('houdini-host'), 120)
        for role in ('alpha-husk', 'nuke-host', None, []):
            with self.subTest(role=role), self.assertRaises(ValueError):
                scope.role_seconds(role)
            with self.assertRaises(ValueError):
                scope.admit(role, scope.root / 'invalid', {'op': 'bad'})
        for role, heavy in (('graph-worker', False), ('houdini-host', True)):
            with self.assertRaisesRegex(ValueError, 'ADMISSION_INVALID'):
                scope.admit(role, scope.root / 'invalid', {'op': 'bad'}, heavy=heavy)
        self.assertEqual(scope.snapshot()['dcc_starts'], 0)

    def test_host_waits_for_successful_signed_graph_stop_and_roles_are_single_use(self):
        scope = self.scope()
        with mock.patch.object(native_scope.time, 'time', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'GRAPH_STOP_REQUIRED'):
                scope.admit('houdini-host', scope.root / 'host', {'op': 'host'}, heavy=False)
            graph = scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
            with self.assertRaisesRegex(ValueError, 'STOP_UNKNOWN'):
                scope.finish(graph)
            with self.assertRaisesRegex(ValueError, 'GRAPH_STOP_REQUIRED'):
                scope.admit('houdini-host', scope.root / 'host', {'op': 'host'}, heavy=False)
        self.stop(graph, 230)
        with mock.patch.object(native_scope.time, 'time', return_value=1230):
            scope.finish(graph)
            host = scope.admit('houdini-host', scope.root / 'host', {'op': 'host'}, heavy=False)
            self.assertEqual(scope.remaining_seconds(host), 120)
            self.assertEqual(scope.remaining_seconds(), 130)
        self.stop(host, 120)
        with mock.patch.object(native_scope.time, 'time', return_value=1350):
            scope.finish(host)
            self.assertEqual(scope.check()['total_seconds'], 350)
            with self.assertRaisesRegex(ValueError, 'STARTS_EXHAUSTED'):
                scope.admit('graph-worker', scope.root / 'third', {'op': 'third'})
        self.assertEqual(scope.snapshot()['dcc_starts'], 2)

    def test_failure_receipt_never_opens_second_stage(self):
        scope = self.scope()
        with mock.patch.object(native_scope.time, 'time', return_value=1000):
            graph = scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
        self.stop(graph, 1, code=1)
        with mock.patch.object(native_scope.time, 'time', return_value=1001):
            with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
                scope.finish(graph)
            with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
                scope.admit('houdini-host', scope.root / 'host', {'op': 'host'}, heavy=False)

    def test_role_deadlines_and_360_total_include_admission_until_signed_stop(self):
        for role in ('graph-worker', 'houdini-host'):
            with self.subTest(role=role):
                scope = self.scope(role)
                with mock.patch.object(native_scope.time, 'time', return_value=1000):
                    ticket = scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
                if role == 'houdini-host':
                    self.stop(ticket, 240)
                    with mock.patch.object(native_scope.time, 'time', return_value=1240):
                        scope.finish(ticket)
                        ticket = scope.admit('houdini-host', scope.root / 'host', {'op': 'host'}, heavy=False)
                end = ticket['admitted_at'] + scope.role_seconds(role)
                with mock.patch.object(native_scope.time, 'time', return_value=end):
                    self.assertEqual(scope.remaining_seconds(ticket), 0)
                    self.assertEqual(scope.check()['total_seconds'], 240 if role == 'graph-worker' else 360)
                self.stop(ticket, scope.role_seconds(role) + .01)
                with mock.patch.object(native_scope.time, 'time', return_value=end + .01):
                    with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'):
                        scope.finish(ticket)
                    with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'):
                        native_scope.NativeScope(scope.binding).remaining_seconds()

    def test_unknown_and_wrong_identity_cannot_finish_or_supply_remaining_time(self):
        scope = self.scope()
        graph = scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
        for ticket in ('unknown', dict(graph, identity={'op': 'other'}),
                       dict(graph, role='houdini-host'), dict(graph, admitted_at=graph['admitted_at'] + 1)):
            for method in (scope.finish, scope.remaining_seconds):
                with self.subTest(method=method.__name__), self.assertRaises(ValueError):
                    method(ticket)
        self.assertIsNone(scope.snapshot()['tickets'][0]['stopped_at'])

    def test_signed_state_still_enforces_profile_roles_and_start_count(self):
        for change in ('role', 'starts', 'sequence'):
            with self.subTest(change=change):
                scope = self.scope(change)
                scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
                state = scope._read()
                if change == 'role': state['tickets'][0]['role'] = 'alpha-husk'
                elif change == 'sequence':
                    state['tickets'][0].update(role='houdini-host', heavy=False)
                else:
                    state['tickets'] = [dict(state['tickets'][0], id=str(index)) for index in range(3)]
                scope._save(state)
                with self.assertRaisesRegex(ValueError, 'STATE_INVALID'):
                    native_scope.NativeScope(scope.binding)

    def test_launch_budget_is_role_bound_and_invalid_values_do_not_consume_admission(self):
        scope = self.scope()
        legacy = native_scope.NativeScope(software_scope(self.root / 'legacy'))
        cases = [(scope, 'graph-worker', 241), (scope, 'houdini-host', 121),
                 (legacy, 'graph-worker', 121), (None, None, 121)]
        cases += [(scope, 'graph-worker', value) for value in (True, '240', float('nan'), float('inf'))]
        with mock.patch.object(owned_process.subprocess, 'Popen') as start:
            for selected, role, seconds in cases:
                with self.subTest(role=role, seconds=str(seconds)), self.assertRaises(ValueError):
                    owned_process.launch(['software-only'], directory=self.root / 'never-created',
                        identity={'op': 'invalid'}, supervisor_executable='software-only', budget_seconds=seconds,
                        resource_budget=self.budget(selected) if selected else None, scope_role=role,
                        scope_heavy=role != 'houdini-host')
            start.assert_not_called()
        self.assertEqual(scope.snapshot()['dcc_starts'], 0)
        self.assertEqual(legacy.snapshot()['dcc_starts'], 0)

    def test_launch_accepts_only_bound_graph_240_and_unknown_launch_retains_ticket(self):
        scope = self.scope()
        directory = scope.root / 'graph'
        with mock.patch.object(owned_process.subprocess, 'Popen'), \
             mock.patch.object(owned_process.threading, 'Thread'), \
             mock.patch.object(owned_process, 'read_receipt',
                 side_effect=lambda directory, event, **kwargs: {'pid': 123} if event == 'started' else None):
            owned_process.launch(['software-only'], directory=directory, identity={'op': 'graph'},
                supervisor_executable='software-only', budget_seconds=240,
                resource_budget=self.budget(scope), scope_role='graph-worker')
        self.assertEqual(json.loads((directory / 'intent.json').read_text())['budget_seconds'], 240)
        self.assertEqual(scope.snapshot()['dcc_starts'], 1)
        other = self.scope('unknown')
        with mock.patch.object(owned_process.subprocess, 'Popen', side_effect=OSError('software unknown')):
            with self.assertRaises(OSError):
                owned_process.launch(['software-only'], directory=other.root / 'graph', identity={'op': 'graph'},
                    supervisor_executable='software-only', budget_seconds=240,
                    resource_budget=self.budget(other), scope_role='graph-worker')
        self.assertIsNone(other.snapshot()['tickets'][0]['stopped_at'])
        with self.assertRaisesRegex(ValueError, 'GRAPH_STOP_REQUIRED'):
            other.admit('houdini-host', other.root / 'host', {'op': 'host'}, heavy=False)

    def test_supervisor_startup_delay_uses_durable_admission_without_new_window(self):
        for role in ('graph-worker', 'houdini-host'):
            with self.subTest(role=role):
                scope = self.scope(role)
                with mock.patch.object(native_scope.time, 'time', return_value=1000):
                    ticket = scope.admit('graph-worker', scope.root / 'graph', {'op': 'graph'})
                if role == 'houdini-host':
                    self.stop(ticket, 1)
                    with mock.patch.object(native_scope.time, 'time', return_value=1001):
                        scope.finish(ticket)
                        ticket = scope.admit(role, scope.root / 'host', {'op': 'host'}, heavy=False)
                directory = Path(ticket['directory'])
                directory.mkdir(); (directory / 'receipt.key').write_bytes(b'fixture-secret')
                cap = scope.role_seconds(role)
                spec = {'identity': ticket['identity'], 'command': ['software-only'], 'budget_seconds': cap,
                        'resource_budget': self.budget(scope), 'native_scope_ticket': ticket}
                clock = [0.0]; signals = []; hard_remaining = []
                process = SimpleNamespace(pid=123456, poll=lambda: 0 if signals else None, wait=lambda: 0)
                def signal_group(pid, signum):
                    if signum == 0: raise ProcessLookupError()
                    signals.append(clock[0]); hard_remaining.append(scope.remaining_seconds(ticket))
                def supervisor_identity(pid):
                    clock[0] += 5
                    return {'pid': 42}
                # No controller, cancel file, or operation guard participates.
                with mock.patch.object(owned_process.time, 'time',
                         side_effect=lambda: ticket['admitted_at'] + 20 + clock[0]), \
                     mock.patch.object(owned_process.time, 'monotonic', side_effect=lambda: clock[0]), \
                     mock.patch.object(owned_process.time, 'sleep', side_effect=lambda _: clock.__setitem__(0, clock[0] + 1)), \
                     mock.patch.object(owned_process, '_signal_group', side_effect=lambda child, signum: signal_group(child.pid, signum)), \
                     mock.patch.object(owned_process.os, 'killpg', side_effect=signal_group), \
                     mock.patch.object(owned_process, 'process_identity', side_effect=supervisor_identity), \
                     mock.patch.object(owned_process, '_disk_usage', return_value=0):
                    self.assertEqual(owned_process._scope_remaining(directory, spec, scope), cap - 20)
                    self.assertEqual(owned_process._scope_remaining(directory, dict(spec, budget_seconds=30), scope), 10)
                    with self.assertRaisesRegex(ValueError, 'IDENTITY_CONFLICT'):
                        owned_process._scope_remaining(directory, dict(spec, identity={'op': 'other'}), scope)
                    with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
                        owned_process._supervise_owned(directory, spec, process, native_scope=scope)
                self.assertEqual(signals, [cap - 30])
                self.assertEqual(hard_remaining, [10])
                stopped = owned_process.read_receipt(directory, 'stopped', identity=ticket['identity'])
                self.assertEqual(stopped['observed_at'], ticket['admitted_at'] + cap - 9)
                self.assertEqual(stopped['stop_reason'], 'TIME_BUDGET_EXCEEDED')
                self.assertEqual(scope.snapshot()['tickets'][-1]['charged_seconds'], cap - 9)
                self.assertEqual(scope.role_seconds(role), cap)


if __name__ == '__main__':
    unittest.main()
