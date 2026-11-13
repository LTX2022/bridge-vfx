"""Durable HIP budget binding; only the process transport is replaced."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from dcc_task_runtime import native_scope
from test_native_scope import software_scope
from test_graph_jobs import _proposal
from vfx_pipeline.controller_media import MediaReadinessError, OperationBudgetGuard
from vfx_pipeline.graph_job_worker import GraphJobWorker
from vfx_pipeline.graph_jobs import GraphJobError, GraphJobService, JOB_BUDGET_SECONDS
from vfx_pipeline.production_hosts import native_scope_budget


ROOT = Path(__file__).resolve().parents[2]
_UNSET = object()


class HipGraphBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = [time.time()]

    def scope(self, name='scope', *, hip=True, **fields):
        if hip:
            fields = dict(schema=native_scope.HIP_SCOPE_SCHEMA,
                resource_profile=native_scope.HIP_RESOURCE_PROFILE,
                budget=copy.deepcopy(native_scope.HIP_BUDGET),
                role_seconds=copy.deepcopy(native_scope.HIP_ROLE_SECONDS), **fields)
        return software_scope(self.root / name, **fields)

    def service(self, binding=None, *, name='jobs', max_seconds=_UNSET, **options):
        root = Path(binding['path']).parent if binding else self.root
        budget = dict(roots=[str(root)], max_bytes=536870912)
        if max_seconds is not _UNSET:
            budget['max_seconds'] = max_seconds
        if binding:
            budget['native_scope'] = binding
        service = GraphJobService(root / name, ROOT, 'NEVER_START_A_DCC',
            scheduler_root=root / 'scheduler', resource_budget=budget,
            clock=lambda: self.now[0], **options)
        self.addCleanup(service.close)
        return service

    def prepare(self, service):
        graph = service.propose(_proposal(), 'proposal')
        # Exercise a persisted, unstarted operation, as after a controller stop.
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            operation = service.trial(graph, 'trial')
        return operation

    def capture(self, service, operation):
        captured = {}

        def transport(argv, **options):
            captured.update(job=json.loads(argv[-1]), options=options)
            raise OSError('software process transport: no child was started')

        row = service._row(operation)
        with mock.patch('dcc_task_runtime.owned_process.launch', side_effect=transport):
            service._launch(operation, service.compiled_graph(row['graph_id']),
                            row['process_token'], row['attempt_generation'])
        self.assertIn('job', captured)
        return captured

    def rewrite_inputs(self, job, edit):
        updated = copy.deepcopy(job)
        inputs_path = Path(job['inputs_path'])
        inputs = json.loads(inputs_path.read_text())
        edit(updated)
        edit(inputs)
        inputs_path.write_text(json.dumps(inputs))
        return updated

    def test_default_and_legacy_keep_120(self):
        self.assertEqual(JOB_BUDGET_SECONDS, 120)
        for name, binding in [('default', None), ('legacy', self.scope('legacy-scope', hip=False))]:
            with self.subTest(name=name):
                service = self.service(binding, name=name, max_seconds=99999 if binding else _UNSET)
                operation = self.prepare(service)
                row = service._row(operation)
                self.assertEqual(service.operation_deadline(operation), row['created_at'] + 120)
                self.assertEqual(service.controller_binding()['job_budget_seconds'], 120)
                guard = service._budget_guard(operation, row['process_token'])
                self.assertEqual(guard.max_seconds, 120)
                captured = self.capture(service, operation)
                self.assertLessEqual(captured['options']['budget_seconds'], 120)
                self.assertEqual(captured['job']['job_budget_seconds'], 120)
                self.assertEqual(GraphJobWorker(captured['job'], clock=lambda: self.now[0]).deadline_at,
                                 row['created_at'] + 120)
                service.close()

    def test_plain_tighter_budget_is_preserved_and_invalid_budgets_are_rejected(self):
        service = self.service(max_seconds=30)
        operation = self.prepare(service)
        row = service._row(operation)
        self.assertEqual(service.operation_deadline(operation), row['created_at'] + 120)
        guard = service._budget_guard(operation, row['process_token'])
        self.assertEqual(guard.max_seconds, 30)
        self.assertIn('TIME_LIMIT_EXCEEDED', guard.check(owner=guard.owner, elapsed_seconds=31)['reasons'])
        for invalid in (None, True, 0, -1, 121, float('inf'), float('nan'), '30'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'BUDGET_INVALID'):
                self.service(name='invalid', max_seconds=invalid)

    def test_hip_tighter_guard_preserves_240_role_and_original_remaining(self):
        binding = self.scope()
        service = self.service(binding, max_seconds=230)
        operation = self.prepare(service)
        row = service._row(operation)
        self.assertEqual(service.operation_deadline(operation), row['created_at'] + 240)
        self.assertEqual(service.resource_budget['max_seconds'], 230)
        self.assertEqual(service._budget_guard(operation, row['process_token']).max_seconds, 230)
        self.now[0] += 70
        captured = self.capture(service, operation)
        self.assertEqual(captured['options']['budget_seconds'], 170)
        self.assertEqual(captured['options']['resource_budget']['max_seconds'], 230)
        self.assertEqual(GraphJobWorker(captured['job'], clock=lambda: self.now[0]).deadline_at,
                         row['created_at'] + 240)
        for invalid in (None, True, 0, -1, 241, float('inf'), float('nan'), '230'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'BUDGET_INVALID'):
                self.service(binding, name='invalid', max_seconds=invalid)

    def test_hip_persists_240_and_supervisor_only_receives_original_remaining(self):
        binding = self.scope()
        service = self.service(binding)
        operation = self.prepare(service)
        row = service._row(operation)
        deadline = service.operation_deadline(operation)
        self.assertEqual(deadline, row['created_at'] + 240)
        self.now[0] += 70
        captured = self.capture(service, operation)
        job, options = captured['job'], captured['options']
        self.assertEqual(options['budget_seconds'], 170)
        self.assertEqual(options['scope_role'], 'graph-worker')
        self.assertEqual(options['resource_budget']['max_seconds'], 240)
        self.assertEqual(job['deadline_at'], deadline)
        self.assertEqual(job['budget_started_at'], row['created_at'])
        self.assertEqual(job['native_scope_budget'], options['resource_budget'])
        self.assertEqual(GraphJobWorker(job, clock=lambda: self.now[0]).deadline_at, deadline)
        guard = service._budget_guard(operation, row['process_token'])
        self.assertEqual(guard.max_seconds, 240)
        self.assertEqual(native_scope.NativeScope(binding).snapshot()['dcc_starts'], 0)

    def test_worker_rejects_unbound_240_and_drifted_scope_budget(self):
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                service = self.service(self.scope() if scoped else None)
                job = self.capture(service, self.prepare(service))['job']
                original = Path(job['inputs_path']).read_bytes()
                edits = [lambda value: value.update(job_budget_seconds=999),
                         lambda value: value.update(deadline_at=value['deadline_at'] + 1),
                         lambda value: value.update(budget_started_at=value['budget_started_at'] + 1,
                                                    deadline_at=value['deadline_at'] + 1)]
                if scoped:
                    edits += [lambda value: value['native_scope_budget'].update(max_seconds=999),
                              lambda value: value.update(native_scope_budget=None)]
                else:
                    edits += [lambda value: value.update(job_budget_seconds=240,
                                                        deadline_at=value['budget_started_at'] + 240)]
                for edit in edits:
                    Path(job['inputs_path']).write_bytes(original)
                    altered = self.rewrite_inputs(job, edit)
                    with self.assertRaises(ValueError):
                        GraphJobWorker(altered, clock=lambda: self.now[0])
                Path(job['inputs_path']).write_bytes(original)
                altered = copy.deepcopy(job)
                altered['deadline_at'] += 1
                with self.assertRaisesRegex(ValueError, 'original operation'):
                    GraphJobWorker(altered, clock=lambda: self.now[0])
                service.close()

    def test_worker_legacy_compatibility_cannot_erase_an_existing_budget_binding(self):
        service = self.service()
        operation = self.prepare(service)
        job = self.capture(service, operation)['job']
        keys = ('budget_started_at', 'job_budget_seconds', 'native_scope_budget')
        for key in keys:
            job.pop(key)
        inputs_path = Path(job['inputs_path'])
        inputs = json.loads(inputs_path.read_text())
        for key in (*keys, 'deadline_at'):
            inputs.pop(key)
        inputs_path.write_text(json.dumps(inputs))
        with self.assertRaisesRegex(ValueError, 'legacy budget'):
            GraphJobWorker(job, clock=lambda: self.now[0])
        row = service._row(operation)
        intent = json.loads(row['intent_json'])
        for key in (*keys, 'deadline_at'):
            intent.pop(key)
        with service._connect() as database:
            database.execute('UPDATE operations SET intent_json=? WHERE operation_id=?',
                             (json.dumps(intent), operation))
        worker = GraphJobWorker(job, clock=lambda: self.now[0])
        self.assertEqual(worker.deadline_at, row['created_at'] + 120)

    def test_worker_does_not_reset_clock_after_input_validation_or_wall_clock_rollback(self):
        service = self.service(self.scope())
        operation = self.prepare(service)
        job = self.capture(service, operation)['job']
        with mock.patch('vfx_pipeline.graph_job_worker.time.monotonic', return_value=100):
            worker = GraphJobWorker(job, clock=lambda: self.now[0])
        self.now[0] -= 1000
        with mock.patch('vfx_pipeline.graph_job_worker.time.monotonic', return_value=341):
            with self.assertRaises(TimeoutError):
                worker._check_budget()

    def test_restart_retry_and_close_retain_original_deadline(self):
        binding = self.scope()
        first = self.service(binding)
        operation = self.prepare(first)
        original = first.operation_deadline(operation)
        self.now[0] += 75
        second = self.service(binding)
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(second.operation_deadline(operation), original)
        self.assertEqual(second._row(operation)['attempt_generation'], 2)
        remaining = self.capture(second, operation)['options']['budget_seconds']
        self.assertGreater(remaining, 160)
        self.assertLessEqual(remaining, 165)
        second.close(drain_in_process=True, drain_timeout_seconds=0)
        self.assertEqual(second.operation_deadline(operation), original)

    def test_expired_unstarted_restart_cannot_receive_a_new_budget(self):
        binding = self.scope()
        first = self.service(binding)
        operation = self.prepare(first)
        original = first.operation_deadline(operation)
        self.now[0] = original + 1
        second = self.service(binding)
        with self.assertRaisesRegex(GraphJobError, 'expired'):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(second.operation_deadline(operation), original)
        self.assertEqual(second._row(operation)['attempt_generation'], 1)

    def test_old_missing_budget_fields_keep_fenced_unstarted_resume_contract(self):
        first = self.service()
        operation = self.prepare(first)
        original = first._row(operation)
        intent = json.loads(original['intent_json'])
        for key in ('budget_started_at', 'job_budget_seconds', 'deadline_at', 'native_scope_budget'):
            intent.pop(key)
        with first._connect() as database:
            database.execute('UPDATE operations SET intent_json=? WHERE operation_id=?',
                             (json.dumps(intent), operation))
        self.now[0] = original['created_at'] + 130
        second = self.service()
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(second.operation_deadline(operation), self.now[0] + 120)
        self.assertEqual(second._row(operation)['created_at'], original['created_at'])
        third = self.service()
        self.assertEqual(third.operation_deadline(operation), self.now[0] + 120)
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            third.reconcile(operation, resume_not_started=True)
        job = self.capture(third, operation)['job']
        self.assertEqual(GraphJobWorker(job, clock=lambda: self.now[0]).deadline_at, self.now[0] + 120)
        self.assertNotIn('job_budget_seconds', job)

    def test_plain_bound_budget_keeps_fenced_unstarted_resume_contract(self):
        first = self.service()
        operation = self.prepare(first)
        original = first._row(operation)
        self.now[0] = original['created_at'] + 130
        second = self.service()
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(second.operation_deadline(operation), self.now[0] + 120)
        job = self.capture(second, operation)['job']
        self.assertEqual(job['budget_started_at'], self.now[0])
        self.assertEqual(second._row(operation)['created_at'], original['created_at'])
        self.assertEqual(GraphJobWorker(job, clock=lambda: self.now[0]).deadline_at, self.now[0] + 120)

    def test_persisted_scope_and_deadline_tampering_are_rejected(self):
        service = self.service(self.scope())
        operation = self.prepare(service)
        with service._connect() as database:
            database.execute('UPDATE operations SET deadline_at=deadline_at+1 WHERE operation_id=?', (operation,))
        with self.assertRaisesRegex(GraphJobError, 'budget changed'):
            service.operation_deadline(operation)

    def test_guard_only_allows_extended_budget_with_bound_graph_role_and_roots(self):
        binding = self.scope()
        root = Path(binding['path']).parent
        owner = dict(task_id='task', operation_id='operation', launch_nonce='attempt')
        common = dict(max_bytes=1000, owner=owner, stop_callback=lambda _: None, max_seconds=240)
        for kwargs in ({}, {'scope_role': 'graph-worker'},
                       {'native_scope': binding, 'scope_role': 'houdini-host'}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(MediaReadinessError):
                OperationBudgetGuard([root], **common, **kwargs)
        with self.assertRaises(MediaReadinessError):
            OperationBudgetGuard([self.root], **common, native_scope=binding, scope_role='graph-worker')
        guard = OperationBudgetGuard([root], **common, native_scope=binding, scope_role='graph-worker')
        self.assertEqual(guard.max_seconds, 240)
        with self.assertRaisesRegex(ValueError, 'BUDGET_INVALID'):
            native_scope_budget(binding, dict(roots=[str(root)], max_bytes=1000,
                max_seconds=99999), root)


if __name__ == '__main__':
    unittest.main()
