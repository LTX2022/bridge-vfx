"""F1 multi-round integration using durable stores and explicit FAKE host seams."""
from __future__ import annotations
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from vfx_pipeline.graph_jobs import GraphJobService
from vfx_pipeline.service import ModelSafePipeline, PipelineExecutionError
from vfx_pipeline.task_graph import TaskGraphCoordinator
from test_task_b_integration import proposal
from test_vfx_pipeline import raw_spec

REPO=Path(__file__).resolve().parents[2]


class ConstructionRoundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='FAKE_HOST_rounds_')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.pipeline=ModelSafePipeline(self.root/'pipeline.sqlite3')
        self.task=self.pipeline.store.create_task(raw_spec('pyro_smoke_v1','synthetic iterative construction'))
        self.calls=[]
        self.behavior=lambda job:{'construction_executed':True}
        def fake_host(job):
            self.calls.append(job['operation_id'])
            return self.behavior(job)
        self.factory=fake_host
        self.jobs=self.new_jobs()
        self.coordinator=self.new_parent(self.jobs)
        self.graph=self.coordinator.propose(proposal(),'proposal_rounds')['graph_id']

    def new_jobs(self):
        result=GraphJobService(self.root/'jobs',REPO,'FAKE_HOST_ONLY',
            scheduler_root=self.root/'installation',worker_factory=self.factory)
        self.addCleanup(result.close)
        return result

    def new_parent(self,jobs):
        pipeline=ModelSafePipeline(self.root/'pipeline.sqlite3')
        return TaskGraphCoordinator(pipeline,self.task,jobs,run_id='synthetic-run',
            session_id='synthetic-session',construction_authorized=True)

    def wait(self,operation,predicate,coordinator=None):
        coordinator=coordinator or self.coordinator
        deadline=time.monotonic()+3
        while True:
            current=coordinator.status(operation)
            if predicate(current): return current
            if time.monotonic()>=deadline: self.fail('FAKE host state deadline: '+repr(current))
            time.sleep(.01)

    def first_success(self):
        op=self.coordinator.trial(self.graph,'trial_1')['operation_id']
        result=self.wait(op,lambda item:item['state']=='SUCCEEDED')
        self.assertTrue(result['completed'])
        self.assertEqual(result['parent_status']['state'],'AWAITING_INPUT')
        return op

    def projection(self):
        return self.pipeline.store.records(self.task,'graph_construction_parent')[0]

    def assert_no_poll_events(self,coordinator,operation):
        before=len(self.pipeline.store.events(self.task))
        before_stage=len(self.pipeline.store.records(self.task,'graph_construction_event'))
        for _ in range(3): coordinator.status(operation)
        self.assertEqual(len(self.pipeline.store.events(self.task)),before)
        self.assertEqual(len(self.pipeline.store.records(self.task,'graph_construction_event')),before_stage)

    def test_second_starting_replay_stale_query_and_cold_parent_follow_active_round(self):
        first=self.first_success()
        gate=threading.Event();entered=threading.Event()
        def second(job):
            entered.set()
            if not gate.wait(3): raise RuntimeError('FAKE_HOST release missing')
            return {'construction_executed':True}
        self.behavior=second
        self.addCleanup(gate.set)
        current=self.coordinator.trial(self.graph,'trial_2')
        # trial returns a snapshot, not a live view. A queued launch is allowed
        # to be PREPARED; check that its parent already follows the new round.
        self.assertIn(current['state'],{'PREPARED','STARTING'})
        self.assertEqual(current['parent_status']['state'],'ANALYZING')
        second_op=current['operation_id']
        self.assertTrue(entered.wait(1),'second fake worker did not enter')
        # The event orders the worker entry, but cannot refresh `current`.
        current=self.coordinator.status(second_op)
        self.assertEqual(current['state'],'STARTING')
        self.assertEqual(current['parent_status']['state'],'ANALYZING')
        self.assertEqual(self.projection()['active_round'],2)
        stale=self.coordinator.status(first)
        self.assertTrue(stale['success'])
        self.assertEqual(stale['parent_status']['state'],'ANALYZING')
        self.assertIn('active',stale['parent_status']['message'])
        self.assertEqual(self.projection()['active_operation_id'],second_op)
        self.assertEqual(self.coordinator.trial(self.graph,'trial_2')['operation_id'],second_op)
        self.assertEqual(len(self.calls),2)
        cold=self.new_parent(self.jobs)
        self.assertEqual(cold.status(first)['parent_status']['state'],'ANALYZING')
        self.assert_no_poll_events(cold,second_op)
        self.assertEqual(len(self.pipeline.store.records(self.task,'graph_trial_intent')),2)
        gate.set()
        final=self.wait(second_op,lambda item:item['state']=='SUCCEEDED',cold)
        self.assertEqual(final['parent_status']['state'],'AWAITING_INPUT')
        self.assertNotEqual(final['parent_status']['state'],'COMPLETED')

    def test_delayed_second_launch_prepared_to_starting_replays_exactly_once(self):
        first=self.first_success()
        allow_claim=threading.Event();claim_entered=threading.Event()
        release_worker=threading.Event();worker_entered=threading.Event()
        self.addCleanup(allow_claim.set)
        self.addCleanup(release_worker.set)
        actual_claim=self.jobs._claim_start

        def delayed_claim(operation,token):
            # Gate only the scheduling seam. The public trial still starts the
            # real launch thread and commits the real PREPARED operation; after
            # release, the original durable claim/lease/worker path runs.
            claim_entered.set()
            if not allow_claim.wait(3):
                raise RuntimeError('FAKE_HOST claim release missing')
            return actual_claim(operation,token)

        def delayed_worker(job):
            worker_entered.set()
            if not release_worker.wait(3):
                raise RuntimeError('FAKE_HOST worker release missing')
            return {'construction_executed':True}

        self.behavior=delayed_worker
        with patch.object(self.jobs,'_claim_start',side_effect=delayed_claim), \
                patch.object(self.jobs,'_schedule',wraps=self.jobs._schedule) as schedule:
            try:
                initial=self.coordinator.trial(self.graph,'trial_2')
                second=initial['operation_id']
                self.assertEqual(initial['state'],'PREPARED')
                self.assertEqual(initial['parent_status']['state'],'ANALYZING')
                self.assertEqual(self.projection()['active_round'],2)
                self.assertEqual(self.projection()['active_operation_id'],second)
                self.assertTrue(claim_entered.wait(1),'fake launch did not reach gate')
                self.assertEqual(self.calls,[first])
                for _ in range(3):
                    replay=self.coordinator.trial(self.graph,'trial_2')
                    self.assertEqual(replay['operation_id'],second)
                    self.assertEqual(replay['state'],'PREPARED')
                    self.assertEqual(replay['parent_status']['state'],'ANALYZING')
                self.assertEqual(schedule.call_count,1)
                self.assertEqual(self.calls,[first])
                historical=self.coordinator.status(first)
                self.assertTrue(historical['success'])
                self.assertEqual(historical['parent_status']['state'],'ANALYZING')
                self.assert_no_poll_events(self.coordinator,second)

                allow_claim.set()
                self.assertTrue(worker_entered.wait(1),'second fake worker did not enter')
                current=self.coordinator.status(second)
                self.assertEqual(current['state'],'STARTING')
                self.assertEqual(current['parent_status']['state'],'ANALYZING')
                # A later query must not retroactively mutate the old snapshot.
                self.assertEqual(initial['state'],'PREPARED')
                self.assertEqual(self.calls,[first,second])
                replay=self.coordinator.trial(self.graph,'trial_2')
                self.assertEqual(replay['operation_id'],second)
                self.assertEqual(replay['state'],'STARTING')
                self.assertEqual(schedule.call_count,1)
                self.assertEqual(self.projection()['active_round'],2)
                cold=self.new_parent(self.jobs)
                self.assertEqual(cold.status(first)['parent_status']['state'],'ANALYZING')
                self.assertEqual(self.projection()['active_operation_id'],second)
                self.assert_no_poll_events(cold,second)

                release_worker.set()
                final=self.wait(second,lambda item:item['state']=='SUCCEEDED',cold)
                self.assertTrue(final['completed'])
                self.assertEqual(final['parent_status']['state'],'AWAITING_INPUT')
                self.assertNotEqual(final['parent_status']['state'],'COMPLETED')
                self.assertEqual(cold.trial(self.graph,'trial_2')['operation_id'],second)
                self.assertEqual(schedule.call_count,1)
                self.assertEqual(self.calls,[first,second])
                self.assertEqual(len(self.pipeline.store.records(self.task,'graph_trial_intent')),2)
                self.assertEqual(cold.status(first)['parent_status']['state'],'AWAITING_INPUT')
            finally:
                # Release only test-owned gates, including on an assertion
                # failure; existing service cleanup joins the worker.
                allow_claim.set()
                release_worker.set()

    def test_second_failure_retains_history_and_third_candidate_is_allowed(self):
        first=self.first_success()
        self.behavior=lambda job:{'construction_executed':False,'errors':['synthetic candidate failure']}
        second=self.coordinator.trial(self.graph,'trial_2')['operation_id']
        failed=self.wait(second,lambda item:item['state']=='FAILED')
        self.assertTrue(failed['completed']);self.assertFalse(failed['success'])
        self.assertTrue(failed['stopped'])
        self.assertEqual(failed['parent_status']['state'],'DIAGNOSING')
        self.assertEqual(self.coordinator.status(first)['parent_status']['state'],'DIAGNOSING')
        self.assert_no_poll_events(self.coordinator,second)
        self.behavior=lambda job:{'construction_executed':True}
        third=self.coordinator.trial(self.graph,'trial_3')['operation_id']
        final=self.wait(third,lambda item:item['state']=='SUCCEEDED')
        self.assertEqual(final['parent_status']['state'],'AWAITING_INPUT')
        self.assertEqual(self.projection()['active_round'],3)
        historical=self.coordinator.status(second)
        self.assertEqual(historical['state'],'FAILED')
        self.assertEqual(historical['parent_status']['state'],'AWAITING_INPUT')
        self.assertEqual(len(self.calls),3)
        self.assertEqual(len(self.pipeline.store.records(self.task,'graph_construction_stage')),3)

    def test_second_unknown_survives_full_service_reopen_and_never_resubmits(self):
        first=self.first_success()
        def uncertain(job): raise RuntimeError('FAKE host outcome deliberately unknown')
        self.behavior=uncertain
        second=self.coordinator.trial(self.graph,'trial_2')['operation_id']
        unknown=self.wait(second,lambda item:item['state']=='RECONCILIATION_REQUIRED')
        self.assertFalse(unknown['completed']);self.assertFalse(unknown['stopped'])
        self.assertEqual(unknown['parent_status']['state'],'DIAGNOSING')
        self.assertEqual(self.coordinator.status(first)['parent_status']['state'],'DIAGNOSING')
        with self.assertRaises(PipelineExecutionError): self.coordinator.trial(self.graph,'trial_3')
        self.jobs.close()
        reopened_jobs=self.new_jobs();cold=self.new_parent(reopened_jobs)
        repeated=cold.trial(self.graph,'trial_2')
        self.assertEqual(repeated['operation_id'],second)
        self.assertEqual(cold.status(first)['parent_status']['state'],'DIAGNOSING')
        checked=cold.reconcile(second)
        self.assertEqual(checked['state'],'RECONCILIATION_REQUIRED')
        self.assertFalse(checked['success'])
        self.assertEqual(len(self.calls),2)
        self.assert_no_poll_events(cold,second)

    def test_second_cancel_unconfirmed_then_stopped_reconcile_keeps_task_open(self):
        first=self.first_success()
        gate=threading.Event();entered=threading.Event()
        def delayed(job):
            entered.set()
            if not gate.wait(3): raise RuntimeError('FAKE_HOST release missing')
            return {'construction_executed':True}
        self.behavior=delayed;self.addCleanup(gate.set)
        second=self.coordinator.trial(self.graph,'trial_2')['operation_id']
        self.assertTrue(entered.wait(1))
        cancel=self.coordinator.cancel(second)  # Actual lower cancellation; no status monkeypatch.
        self.assertTrue(cancel['cancellation_requested'])
        self.assertFalse(cancel['stopped'])
        self.assertEqual(cancel['parent_status']['state'],'DIAGNOSING')
        self.assertEqual(self.coordinator.status(first)['parent_status']['state'],'DIAGNOSING')
        with self.assertRaises(PipelineExecutionError): self.coordinator.trial(self.graph,'trial_3')
        gate.set()
        self.wait(second,lambda item:item['stop_confirmed'])
        cancelled=self.coordinator.reconcile(second)
        self.assertEqual(cancelled['state'],'CANCELLED')
        self.assertTrue(cancelled['stopped']);self.assertFalse(cancelled['success'])
        self.assertEqual(cancelled['parent_status']['state'],'AWAITING_INPUT')
        self.assertIn('cancelled',cancelled['parent_status']['message'])
        self.assertEqual(len(self.calls),2)
        self.assert_no_poll_events(self.coordinator,second)

    def test_second_running_owned_fake_handle_cancel_does_not_claim_stopped(self):
        first=self.first_success()
        class FakeProcess:
            pid=8000001
            stopped=False
            terminate_calls=0
            def poll(self): return 0 if self.stopped else None
            def terminate(self): self.terminate_calls+=1  # deliberately uncooperative fake handle
        process=FakeProcess()
        self.behavior=lambda job:process
        self.addCleanup(setattr,process,'stopped',True)
        with patch('vfx_pipeline.graph_jobs.process_identity',return_value={'pid':process.pid,'birth_token':'FAKE_ONLY'}):
            second=self.coordinator.trial(self.graph,'trial_2')['operation_id']
            running=self.wait(second,lambda item:item['state']=='RUNNING')
            self.assertEqual(running['parent_status']['state'],'ANALYZING')
            self.assertEqual(self.coordinator.status(first)['parent_status']['state'],'ANALYZING')
            cancelled=self.coordinator.cancel(second)
            self.assertFalse(cancelled['stopped'])
            self.assertEqual(cancelled['state'],'RECONCILIATION_REQUIRED')
            self.assertEqual(process.terminate_calls,1)
            self.assertEqual(cancelled['parent_status']['state'],'DIAGNOSING')
            process.stopped=True
            done=self.wait(second,lambda item:item['state']=='CANCELLED')
            self.assertEqual(done['parent_status']['state'],'AWAITING_INPUT')
            self.assertEqual(len(self.calls),2)

    def test_state_machine_illegal_edges_remain_illegal_with_message_refresh(self):
        self.first_success()
        with self.assertRaises(ValueError):
            self.pipeline.store.transition(self.task,'QUEUED','not allowed',refresh_message=True)
        self.assertEqual(self.pipeline.store.status(self.task)['state'],'AWAITING_INPUT')

    def test_historical_poll_rejects_tampered_active_snapshot_without_parent_regression(self):
        first=self.first_success()
        self.behavior=lambda job:{'construction_executed':False,'errors':['synthetic failed candidate']}
        second=self.coordinator.trial(self.graph,'trial_2')['operation_id']
        self.wait(second,lambda item:item['state']=='FAILED')
        record=next(row for row in self.pipeline.store.records(self.task,'graph_construction_stage')
                    if row['operation_id']==second)
        record['lower_state']='SUCCEEDED'  # Untrusted edit, not a host observation.
        self.pipeline.store.put_record(self.task,'graph_construction_stage',second,record)
        before=self.pipeline.store.status(self.task)
        with self.assertRaises(PipelineExecutionError):self.coordinator.status(first)
        self.assertEqual(self.pipeline.store.status(self.task),before)
        self.assertEqual(len(self.calls),2)
        # Polling the actual active lower operation repairs its materialized snapshot.
        repaired=self.coordinator.status(second)
        self.assertEqual(repaired['state'],'FAILED')
        self.assertEqual(repaired['parent_status']['state'],'DIAGNOSING')
