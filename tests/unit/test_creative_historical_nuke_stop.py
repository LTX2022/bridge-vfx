"""Read-only historical Nuke stop checks with signed software-only receipts."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
for name in ('vfx-pipeline','houdini-bridge','dcc-task-runtime','nuke-bridge'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime import owned_process
from vfx_pipeline.creative_results import validate_historical_nuke_stop,validate_nuke_completion


class CreativeHistoricalNukeStopTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(prefix='creative-nuke-history-software-')
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name).resolve()
        phase={'task_id':'creative-task','schema':'bridge.official-case-creative-phase/1'}
        self.original=SimpleNamespace(root=self.root,path=self.root/'scope04/scope.json',
            binding={'path':str(self.root/'scope04/scope.json'),'sha256':'4'*64},
            scope={'creative_phase':copy.deepcopy(phase)},_continuation_previous=None)
        self.current=SimpleNamespace(root=self.root,path=self.root/'scope08/scope.json',
            binding={'path':str(self.root/'scope08/scope.json'),'sha256':'8'*64},
            scope={'creative_phase':copy.deepcopy(phase)},_continuation_previous=self.original)
        self.operation='nrend-'+hashlib.sha256(b'creative-one_nuke').hexdigest()[:16]
        self.supervisor=self.root/'supervisor';self.supervisor.mkdir()
        (self.supervisor/'receipt.key').write_bytes(b'software-test-receipt-key-only')
        self.identity={'task_id':self.operation,'operation_id':self.operation,'launch_nonce':'test-nonce'}
        self.started={'schema':owned_process.SCHEMA,'event':'started','identity':self.identity,'pid':123,
            'execution_protocol':1,'resource_budget':{'native_scope':self.original.binding}}
        self.stopped={'schema':owned_process.SCHEMA,'event':'stopped','identity':self.identity,'pid':123,
            'observed_by':'owned_child_wait','exit_code':0,'execution_protocol':1,
            'descendant_result_unobserved':False,'stop_reason':None,'supervisor_exit_code':0,
            'execution_result':'succeeded','observed_at':20.}
        self.sign()
        self.task={'task_id':self.operation,'owner_task_id':'creative-task','slot_released':True,
            'slot':{'owner_root':'nuke:test-project','operation_id':self.operation,'token':'original-token','generation':4},
            'state':'COMPLETED','ledger_state':'REGISTERED',
            'supervisor_intent':{'directory':str(self.supervisor),'identity':self.identity}}
        self.task_path=self.root/'state/nuke_renders'/(self.operation+'.json')
        self.task_path.parent.mkdir(parents=True);self.save_task()
        self.attempt=dict(self.task['slot'],observed_stopped=True,
            process_json=json.dumps({'supervisor_identity':self.identity,'supervisor_directory':str(self.supervisor)}))
        self.scheduler=self.original.path.parent/'scheduler/graph_scheduler.sqlite3'
        self.scheduler.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.scheduler)) as db:
            with db:
                db.execute('CREATE TABLE stopped_attempts(owner_root,operation_id,token,fact_json)')
                db.execute('INSERT INTO stopped_attempts VALUES(?,?,?,?)',
                    ('nuke:test-project',self.operation,'original-token',json.dumps(self.attempt)))
        self.result={'task_id':'creative-task','operation_id':'creative-one','nuke':{'operation_id':self.operation}}
        self.formal={'operation_id':self.operation}

    def sign(self):
        self.stopped['started_sha256']=hashlib.sha256(owned_process._canonical(self.started)).hexdigest()
        owned_process._signed_write(self.supervisor,self.started)
        owned_process._signed_write(self.supervisor,self.stopped)

    def save_task(self):
        self.task_path.write_text(json.dumps(self.task))

    def save_attempt(self):
        with closing(sqlite3.connect(self.scheduler)) as db:
            with db:
                db.execute('UPDATE stopped_attempts SET fact_json=?',(json.dumps(self.attempt),))

    def check(self):
        return validate_historical_nuke_stop(self.result,self.current,self.formal)

    def test_original_scope04_attempt_reads_from_scope08_without_writes(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with mock.patch('subprocess.Popen',side_effect=AssertionError('no process launch')):
            self.check()
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse(self.current.path.parent.exists())

    def test_unrelated_scope_is_not_searched(self):
        self.current._continuation_previous=None
        with self.assertRaisesRegex(ValueError,'SCOPE_REQUIRED'):self.check()

    def test_wrong_task_scope_is_rejected(self):
        self.original.scope['creative_phase']['task_id']='other-task'
        with self.assertRaisesRegex(ValueError,'SCOPE_REQUIRED'):self.check()

    def test_wrong_slot_token_is_rejected(self):
        self.task['slot']['token']='other-token';self.save_task()
        with self.assertRaisesRegex(ValueError,'STOP_REQUIRED'):self.check()

    def test_attempt_content_must_match_original_slot(self):
        for field,value in (('token','changed'),('generation',5),('observed_stopped',False)):
            with self.subTest(field=field):
                previous=self.attempt[field];self.attempt[field]=value;self.save_attempt()
                with self.assertRaisesRegex(ValueError,'STOP_REQUIRED'):self.check()
                self.attempt[field]=previous;self.save_attempt()

    def test_attempt_process_identity_must_match_signed_stop(self):
        self.attempt['process_json']=json.dumps({'supervisor_identity':{},'supervisor_directory':str(self.supervisor)})
        self.save_attempt()
        with self.assertRaisesRegex(ValueError,'STOP_REQUIRED'):self.check()

    def test_signed_failure_is_not_success(self):
        self.stopped.update(exit_code=-15,stop_reason='TIME_BUDGET_EXCEEDED',execution_result='failed');self.sign()
        with self.assertRaisesRegex(ValueError,'STOP_REQUIRED'):self.check()

    def test_bad_signature_is_rejected(self):
        path=self.supervisor/'stopped.json';envelope=json.loads(path.read_text());envelope['signature']='0'*64
        path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError,'SUPERVISOR_RECEIPT_MISMATCH'):self.check()

    def test_evidence_changed_during_read_is_rejected(self):
        original=owned_process.read_receipt
        for target in ('task','attempt','started','stopped'):
            with self.subTest(target=target):
                mutated=False
                def read(directory,event,*,identity):
                    nonlocal mutated
                    value=original(directory,event,identity=identity)
                    if event=='stopped' and not mutated:
                        mutated=True
                        if target=='task':self.task['updated_at']=1;self.save_task()
                        elif target=='attempt':self.attempt['updated_at']=1;self.save_attempt()
                        elif target=='started':self.started['updated_at']=1;self.sign()
                        else:self.stopped['observed_at']+=1;self.sign()
                    return value
                with mock.patch.object(owned_process,'read_receipt',side_effect=read):
                    with self.assertRaisesRegex(ValueError,'CHANGED_DURING_READ'):self.check()
                self.task.pop('updated_at',None);self.save_task()
                self.attempt.pop('updated_at',None);self.save_attempt()
                self.started.pop('updated_at',None);self.stopped['observed_at']=20.;self.sign()

    def test_live_completion_still_requires_current_released_slot(self):
        artifact={'artifact_id':'nuke-render-'+self.operation,'pattern':'frame.%04d.exr',
            'scene_fingerprint':'scene','task_id':'creative-task','operation_receipt_sha256':'receipt'}
        self.result['nuke']['artifact']=artifact
        registry=mock.Mock()
        registry._operation_facts.return_value={'formal_receipt':self.formal,'operation_receipt_sha256':'receipt'}
        registry.verify.return_value={'usable':True}
        with mock.patch('nuke_bridge.operation_receipts.receipt_errors',return_value=[]), \
             mock.patch('nuke_bridge.operation_receipts.completed_operation_projection',return_value={
                 'completion_metadata_status':'AVAILABLE','stop_confirmed':True}), \
             mock.patch('vfx_pipeline.creative_results.GraphScheduler') as scheduler:
            scheduler.return_value.snapshot.return_value={'active':0,'phase':'RELEASED','operation_id':'newer-operation'}
            with self.assertRaisesRegex(ValueError,'SLOT_RELEASE_REQUIRED'):
                validate_nuke_completion(registry,self.result,self.current)


if __name__=='__main__':unittest.main()
