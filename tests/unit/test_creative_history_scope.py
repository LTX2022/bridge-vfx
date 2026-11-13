"""Signed software accounting plus synthetic stop boundaries; no native hosts."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
for name in ('houdini-bridge','dcc-task-runtime'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.native_scope import NativeScope
from houdini_bridge.official_karma_observation import file_record
from houdini_bridge.creative_history_scope import completed_creative_prefix
from houdini_bridge import controlled_output


class SoftwareScope:
    _canonical=staticmethod(NativeScope._canonical)
    _verify_envelope=NativeScope._verify_envelope
    _envelope=NativeScope._envelope
    _load_accounted=NativeScope._load_accounted
    def _key(self):return b'explicit-software-test-key-no-production-key'
    def _stop(self,ticket):return self.stops.get(ticket['id'])
    def role_seconds(self,role):return 100
    def effective_creative_starts(self):return 10
    def completed_snapshot(self):return self.current


class CreativeHistoryScopeTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(prefix='creative-history-software-')
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name).resolve();self.scope=SoftwareScope();s=self.scope
        s.root=self.root;s.binding={'path':str(self.root/'scope.json'),'sha256':'a'*64}
        s.state_path=self.root/'accounting.json';s.journal_path=self.root/'journal.jsonl';s.anchor_path=self.root/'anchor.json'
        s.scope={'creative_phase':{'task_id':'task','seconds':1000},'budget':{'max_dcc_starts':50,'total_seconds':6000}}
        self.control=self.root/'job/project/control';self.control.mkdir(parents=True)
        self.supervisor={'directory':str(self.control/'houdini-task-host/supervisor'),'identity':{'operation_id':'render'}}
        self.operation='creative-one'
        nuke='nrend-'+hashlib.sha256((self.operation+'_nuke').encode()).hexdigest()[:16]
        s.stops={};tickets=[]
        for i in range(45):
            stop={'exit_code':0 if i<44 else -15,'execution_protocol':1,'descendant_result_unobserved':False,
                  'stop_reason':None if i<44 else 'TIME_BUDGET_EXCEEDED','supervisor_exit_code':0,
                  'execution_result':'succeeded' if i<44 else 'failed','observed_at':float(i*10+2)}
            ticket={'id':str(i),'parent':None,'role':'houdini-host','directory':str(self.root/str(i)),
                    'identity':{'operation_id':str(i)},'admitted_at':float(i*10+1),'charged_seconds':1.,'stopped_at':stop['observed_at']}
            if i in (41,42):ticket.update(directory=self.supervisor['directory'],identity=self.supervisor['identity'])
            if i==42:ticket.update(role='main-husk',parent='41')
            if i==43:ticket.update(role='nuke-render',identity={'operation_id':nuke})
            ticket['stopped_sha256']=hashlib.sha256(s._canonical(stop)).hexdigest()
            s.stops[str(i)]=stop;tickets.append(ticket)
        self.prefix={'scope_sha256':'a'*64,'tickets':tickets[:44],'closed_reason':None}
        s.current={'scope_sha256':'a'*64,'tickets':tickets,'closed_reason':'NATIVE_SCOPE_EXECUTION_FAILED'}
        s._creative_base_state={'tickets':tickets[:40]}
        self.result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':'task',
                     'operation_id':self.operation,'control':str(self.control),'scope':dict(self.prefix,dcc_starts=44),
                     'nuke':{'operation_id':nuke}}
        self.result_path=self.control.parent.parent/'result.json';self.save_result();self.save_journal()

    def save_result(self):
        self.result_path.write_text(json.dumps(self.result));self.record=file_record(self.result_path)

    def save_journal(self,include_prefix=True):
        states=([self.prefix] if include_prefix else [])+[self.scope.current]
        previous=None;lines=[]
        for seq,state in enumerate(states):
            record=self.scope._envelope({'seq':seq,'previous':previous,'state':state})
            raw=self.scope._canonical(record);lines.append(raw);previous=hashlib.sha256(raw).hexdigest()
        self.scope.journal_path.write_bytes(b'\n'.join(lines)+b'\n')
        self.scope.state_path.write_bytes(lines[-1])
        self.scope.anchor_path.write_bytes(self.scope._canonical(self.scope._envelope({'seq':seq,'head':previous})))

    def check(self):
        return completed_creative_prefix(self.scope,self.scope.current,self.record,self.supervisor,self.operation+'_render')

    def test_original_44_completion_survives_later_failed_45_without_writes(self):
        paths=(self.scope.state_path,self.scope.journal_path,self.scope.anchor_path,self.result_path)
        before={p:p.read_bytes() for p in paths}
        with mock.patch('subprocess.Popen',side_effect=AssertionError('no native launch')):
            self.assertEqual(self.check(),self.prefix['tickets'])
        self.assertEqual(before,{p:p.read_bytes() for p in paths})
        self.assertEqual(self.scope.current['closed_reason'],'NATIVE_SCOPE_EXECUTION_FAILED')

    def test_missing_signed_completion_prefix_rejected(self):
        self.save_journal(include_prefix=False)
        with self.assertRaisesRegex(ValueError,'SIGNED_PREFIX_REQUIRED'):self.check()

    def test_bad_producer_stop_rejected(self):
        self.scope.stops['41']=None
        with self.assertRaisesRegex(ValueError,'SIGNED_STOP_REQUIRED'):self.check()

    def test_bad_prefix_signature_rejected(self):
        lines=self.scope.journal_path.read_text().splitlines();r=json.loads(lines[0]);r['signature']='0'*64
        lines[0]=json.dumps(r);self.scope.journal_path.write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(ValueError,'SIGNATURE_INVALID'):self.check()

    def test_prefix_budget_overrun_rejected(self):
        self.scope.scope['budget']['total_seconds']=1
        with self.assertRaisesRegex(ValueError,'BUDGET_EXCEEDED'):self.check()

    def test_manual_close_without_later_failed_stop_rejected(self):
        stop=self.scope.stops['44'];stop.update(exit_code=0,execution_result='succeeded',stop_reason=None)
        self.scope.current['tickets'][44]['stopped_sha256']=hashlib.sha256(self.scope._canonical(stop)).hexdigest()
        self.save_journal()
        with self.assertRaisesRegex(ValueError,'LATER_FAILURE_REQUIRED'):self.check()

    def test_overlapping_later_attempt_rejected(self):
        self.scope.current['tickets'][44]['admitted_at']=self.prefix['tickets'][-1]['stopped_at']
        self.save_journal()
        with self.assertRaisesRegex(ValueError,'LATER_FAILURE_REQUIRED'):self.check()

    def test_live_reader_without_completion_record_still_rejects_failed_scope(self):
        self.scope.scope['schema']='bridge.official-karma-comparison-scope/1';self.scope.resource_profile='software'
        scope_path=Path(self.scope.binding['path']);scope_path.write_text('{}');source=file_record(scope_path)
        self.scope.binding={k:source[k] for k in ('path','sha256')}
        with mock.patch('dcc_task_runtime.native_scope.NativeScope',return_value=self.scope):
            with self.assertRaisesRegex(ValueError,'HISTORICAL_SCOPE_NOT_STOPPED'):
                controlled_output._verify_historical_scope(self.scope.binding,source,self.supervisor,{}, {})


    def assert_stop_change_during_read_rejected(self,index):
        original=self.scope._load_accounted
        calls=0
        def read():
            nonlocal calls
            observed=original();calls+=1
            if calls==2:
                self.scope.stops[str(index)]['concurrent_change']='changed after first authenticated read'
            return observed
        with mock.patch.object(self.scope,'_load_accounted',side_effect=read):
            with self.assertRaisesRegex(ValueError,'SIGNED_STOP_CHANGED'):self.check()

    def test_prefix_karma_and_nuke_stop_changes_during_read_rejected(self):
        for index in (42,43):
            with self.subTest(index=index):
                before=copy.deepcopy(self.scope.stops)
                self.assert_stop_change_during_read_rejected(index)
                self.scope.stops=before

    def test_later_failed_stop_change_during_read_rejected(self):
        self.assert_stop_change_during_read_rejected(44)


if __name__=='__main__':unittest.main()
