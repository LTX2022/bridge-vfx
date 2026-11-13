"""Pure native API/file boundaries; no Houdini, TCP or child processes."""
import copy
import hashlib
import json
import runpy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
for name in ('dcc-task-runtime','houdini-bridge'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
sys.path.insert(0,str(ROOT/'tests/unit'))
from houdini_bridge import client, render_writer_facts as writer
from houdini_bridge.render_observation_budget import FileReadBudget, MAX_FILE_READ_BYTES, RenderObservationLimit
from dcc_task_runtime.exr_codec import encode_tiny_exr
import test_houdini_output_receipts as receipts
from test_render_color_facts import usd_stage


class Parm:
    def __init__(self,value,kind):self.value=value;self.kind=kind
    def evalAtFrame(self,frame):return self.value
    def unexpandedString(self):return self.value
    def keyframes(self):return ()
    def getReferencedParm(self):return self
    def set(self,value):self.value=value
    def parmTemplate(self):return SimpleNamespace(type=lambda:self.kind)


class RenderWriterFactsTests(unittest.TestCase):
    def setUp(self):
        fixture=receipts.HoudiniOutputReceiptTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.record=fixture.record
        self.record['slot']={'owner_root':str(fixture.root/'operations.json')}
        self.record['render_config']['1']['rendersettings']='/Render/settings'
        self.record['scene_fingerprint']=client.render_receipt_digest({
            'scene':self.record['scene']['snapshot_sha256'],'config':self.record['render_config']})
        self.parms={'husk_tpostframe':Parm(0,'toggle'),'husk_postframe':Parm('','string'),
                    'soho_foreground':Parm(1,'toggle')}
        self.hou=SimpleNamespace(applicationVersionString=lambda:'21.0.631',frame=lambda:1.,
            parmTemplateType=SimpleNamespace(Toggle='toggle',String='string'),
            Color=SimpleNamespace(ocio_configPath=lambda:'unresolved-writer-config'))
        self.node=SimpleNamespace(type=lambda:SimpleNamespace(nameWithCategory=lambda:'Driver/usdrender'),
            path=lambda:self.record['render_target'],parm=lambda name:self.parms.get(name))
        self.root=writer.writer_root(self.record)

    def render(self):
        self.fixture.path.write_bytes(encode_tiny_exr())
        path=Path(self.parms['husk_postframe'].value)
        with mock.patch.dict(sys.modules,{'hou':self.hou}):
            runpy.run_path(str(path),init_globals={'stage':usd_stage(),'settings':{},
                'husk_command':['explicit native API fixture']},run_name='__native_hook_api_fixture__')

    def observed(self):
        with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):
            self.render()
        return self.record['writer_observations']['1']

    def validate(self,observation,frame=1,**kwargs):
        return writer.validate_writer_observation(observation,
            client.render_receipt_digest(client.render_producer_binding(self.record)),frame,
            expected_root=self.root,**kwargs)

    def test_fixed_native_hook_executes_restores_and_formal_client_rechecks(self):
        observed=self.observed()
        self.assertEqual((self.parms['husk_tpostframe'].value,self.parms['husk_postframe'].value),(0,''))
        self.assertEqual(self.validate(observed)['frame'],1)
        self.record['frame_snapshots']['1']=self.fixture.snapshot()
        fact=client.collect_render_output_fact(self.record,1)
        self.assertEqual(fact['writer_observation'],observed)
        self.assertNotIn('PXL_EFFECTIVE_WRITER_OCIO_INSTANCE_UNOBSERVED',fact['missing_facts'])
        self.assertIn('PROJECT_COLOR_SELECTION_REQUIRED',fact['missing_facts'])
        self.assertIn('WRITER_BEAUTY_ALPHA_ASSOCIATION_UNOBSERVED',fact['missing_facts'])
        self.assertIn('WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED',fact['missing_facts'])
        self.record['output_facts']={'1':fact}
        terminal=client.render_execution_fact(self.record)
        self.assertEqual(terminal['completion_metadata_status'],'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(terminal['metadata'],{})
        self.assertNotIn('capture.key',json.dumps(self.record))
        self.assertNotIn('hmac_sha256',json.dumps(self.record))

    def test_wrong_frame_root_and_changed_event_hook_output_are_rejected(self):
        observed=self.observed()
        with self.assertRaisesRegex(ValueError,'producer/frame'):self.validate(observed,frame=2)
        foreign=copy.deepcopy(observed);foreign['directory']=str(self.fixture.root/'foreign')
        with mock.patch.object(writer,'_private_bytes',side_effect=AssertionError('foreign key was read')):
            with self.assertRaisesRegex(ValueError,'owned operation root'):self.validate(foreign)
        for name in ('observation.json','postframe.py'):
            path=Path(observed['directory'])/name;original=path.read_bytes();path.write_bytes(original+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):self.validate(observed)
            path.write_bytes(original)
        original=self.fixture.path.read_bytes();self.fixture.path.write_bytes(original[:-1]+b'X')
        with self.assertRaisesRegex(ValueError,'output bytes changed'):self.validate(observed)

    def test_missing_or_user_hooks_reject_and_render_failure_restores(self):
        for mode in ('missing','user'):
            saved=self.parms.copy()
            if mode=='missing':self.parms.pop('husk_postframe')
            else:self.parms['husk_postframe']=Parm('user.py','string')
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):
                    self.fail('invalid native hook entered rendering')
            if mode=='user':self.assertEqual(self.parms['husk_postframe'].value,'user.py')
            self.parms=saved
        with self.assertRaisesRegex(RuntimeError,'native render failure'):
            with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):
                raise RuntimeError('native render failure')
        self.assertEqual((self.parms['husk_tpostframe'].value,self.parms['husk_postframe'].value),(0,''))
        with self.assertRaises(OSError):
            with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):pass
        self.assertNotIn('writer_observations',self.record)

    def test_output_hash_reads_and_capture_share_the_operation_read_allowance(self):
        observed=self.observed()
        self.assertGreater(self.record['ocio_read_budget']['used_bytes'],2*self.fixture.path.stat().st_size)
        near_limit=FileReadBudget({'schema':FileReadBudget().state['schema'],'used_bytes':MAX_FILE_READ_BYTES-1})
        with mock.patch.object(writer.os,'open',side_effect=AssertionError('over-budget output was opened')):
            with self.assertRaises(RenderObservationLimit):writer._snapshot(self.fixture.path,near_limit)
        budget=FileReadBudget();self.validate(observed,read_budget=budget)
        self.assertGreater(budget.state['used_bytes'],self.fixture.path.stat().st_size)

    def test_foreground_requires_native_undriven_one_and_drift_means_unknown_stop(self):
        parm=self.parms['soho_foreground']
        for mode in ('missing','off','driven','animated','wrong_template'):
            with self.subTest(mode=mode):
                with mock.patch.dict(self.parms,clear=False):
                    if mode=='missing':self.parms.pop('soho_foreground')
                    else:
                        candidate=Parm(0 if mode=='off' else 1,'string' if mode=='wrong_template' else 'toggle')
                        if mode=='driven':candidate.getReferencedParm=lambda:parm
                        if mode=='animated':candidate.keyframes=lambda:('native keyframe',)
                        self.parms['soho_foreground']=candidate
                    with self.assertRaises(ValueError):
                        with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):
                            self.fail('asynchronous or driven render was dispatched')
        for mode in ('off','read_error'):
            with self.subTest(drift=mode):
                try:
                    with self.assertRaises(writer.WriterStopUnconfirmed) as caught:
                        with writer.render_writer_frame(self.node,self.record,1,self.root,hou_module=self.hou):
                            self.render()
                            if mode=='off':parm.value=0
                            else:parm.evalAtFrame=mock.Mock(side_effect=RuntimeError('native read failed'))
                    self.assertEqual(caught.exception.code,'RENDER_WRITER_STOP_UNCONFIRMED')
                    self.assertEqual(self.parms['husk_postframe'].value,'')
                finally:
                    parm.value=1
                    if 'evalAtFrame' in vars(parm):del parm.evalAtFrame

    def test_unknown_hook_global_values_are_bounded_without_coercion(self):
        class Native:
            def __str__(self):raise AssertionError('unknown native object was coerced')
        with self.assertRaises(ValueError):writer._raw(Native())
        with self.assertRaises(ValueError):writer._raw(['x'*8192]*128)

    def test_terminal_quota_publication_stays_running_until_original_is_sealed(self):
        from dcc_task_runtime import owned_process
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from houdini_bridge.operation_store import write_snapshot
        record=self.record
        record['claimed_by_generation']='live-producer-generation'
        record['history']=[{'from':'QUEUED','to':'RUNNING'},
                           {'from':'RUNNING','to':'COMPLETED','note':'all_frames_collected'}]
        record['execution_fact']=client.render_execution_fact(record)
        record['ocio_read_budget']=FileReadBudget().state
        original_fact=copy.deepcopy(record['execution_fact'])
        path=Path(record['slot']['owner_root'])
        binding={key:copy.deepcopy(record[key]) for key in (
            'request_sha256','host_identity','supervisor_binding')}
        binding.update(operation_store_path=str(path),producer_binding=client.render_producer_binding(record))
        observations=[]
        def persist_quota():
            pending=client.render_terminal_pending_record(record)
            write_snapshot(path,{'operations':{record['request_id']:pending}})
            current=client.read_render_operation(binding,task_id=record['task_id'],operation_id=record['request_id'])
            observations.append(current)
        with mock.patch.object(owned_process,'read_receipt',return_value=None), \
                mock.patch.object(GraphScheduler,'release',side_effect=AssertionError('unsealed result released slot')), \
                mock.patch.object(client,'seal_render_terminal',side_effect=AssertionError('status tried sealing')):
            budget=FileReadBudget(record['ocio_read_budget'],persist=persist_quota)
            for count in (1,17,33):budget.reserve(count)
            for observed in observations:
                self.assertEqual(observed['operation']['state'],'RUNNING')
                self.assertEqual(observed['operation']['stage'],'render_terminal_sealing')
                self.assertEqual(observed['operation']['claimed_by_generation'],'live-producer-generation')
                self.assertEqual(observed['operation']['history'][-1]['to'],'RUNNING')
                self.assertIsNone(observed['execution_fact'])
                self.assertNotIn('lifecycle_fact',observed['operation'])
                self.assertNotIn('finished_at',observed['operation'])
            used=[observed['operation']['ocio_read_budget']['used_bytes'] for observed in observations]
            self.assertEqual(used,[1,18,51])
            restarted=FileReadBudget(json.loads(path.read_text())['operations'][record['request_id']]['ocio_read_budget'])
            self.assertEqual(restarted.state['used_bytes'],51)
            self.assertEqual(record['state'],'COMPLETED')
            self.assertEqual(record['execution_fact'],original_fact)
            self.assertEqual(record['history'][-1]['to'],'COMPLETED')
            write_snapshot(path,{'operations':{record['request_id']:record}})
            with self.assertRaises(client.BridgeError) as caught:
                client.read_render_operation(binding,task_id=record['task_id'],operation_id=record['request_id'])
            self.assertEqual(caught.exception.code,'RENDER_TERMINAL_ANCHOR_REQUIRED')
        with self.assertRaises(ValueError):
            client.render_terminal_pending_record({'kind':'render','state':'RUNNING'})

    def test_signed_original_recovers_only_after_real_stop_and_current_byte_verification(self):
        from dcc_task_runtime import owned_process
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from dcc_task_runtime.platform_support import ensure_private_directory
        from houdini_bridge.operation_store import write_snapshot
        for mode in ('valid','missing','corrupt','producer_mismatch','terminal_identity_mismatch',
                     'changed_output','unknown_stop','wrong_stop_operation','wrong_stop_identity'):
            with self.subTest(mode=mode):
                case=RenderWriterFactsTests(methodName='runTest');case.setUp()
                try:
                    record=case.record;case.observed()
                    record['frame_snapshots']['1']=case.fixture.snapshot()
                    record['output_facts']={'1':client.collect_render_output_fact(record,1)}
                    path=Path(record['slot']['owner_root'])
                    scheduler=GraphScheduler(case.fixture.root/'recovery-scheduler')
                    slot=scheduler.reserve(str(path),record['request_id'])
                    record['slot']=dict(slot,owner_root=str(path),operation_id=record['request_id'])
                    record['scheduler_root']=str(scheduler.root)
                    record['budget_token']='explicit-file-fixture-budget'
                    record['execution_fact']=client.render_execution_fact(record)
                    binding={key:copy.deepcopy(record[key]) for key in (
                        'request_sha256','host_identity','supervisor_binding')}
                    binding.update(operation_store_path=str(path),producer_binding=client.render_producer_binding(record))
                    supervisor=ensure_private_directory(Path(record['supervisor_binding']['directory']))
                    key=supervisor/'receipt.key';key.write_bytes(b'explicit-private-file-fixture-key');key.chmod(0o600)
                    identity=record['supervisor_binding']['identity']
                    started={'schema':owned_process.SCHEMA,'event':'started','identity':identity,
                             'pid':record['host_identity']['pid']}
                    owned_process._signed_write(supervisor,started)
                    started_sha=hashlib.sha256(owned_process._canonical(started)).hexdigest()
                    event=client._render_terminal_event(binding['producer_binding'])
                    original={'schema':owned_process.SCHEMA,'event':event,'identity':identity,
                        'pid':started['pid'],'started_sha256':started_sha,
                        'producer_binding_sha256':client.render_receipt_digest(binding['producer_binding']),
                        'execution_fact':copy.deepcopy(record['execution_fact'])}
                    if mode=='producer_mismatch':original['producer_binding_sha256']='0'*64
                    if mode=='terminal_identity_mismatch':original['identity']={'other-producer':True}
                    if mode!='missing':owned_process._signed_write(supervisor,original)
                    if mode=='corrupt':(supervisor/(event+'.json')).write_text('{}')
                    stopped={'schema':owned_process.SCHEMA,'event':'stopped','identity':identity,
                        'pid':started['pid'],'started_sha256':started_sha,'observed_by':'owned_child_wait','exit_code':0,
                        'operation':{'operation_id':record['request_id'],'token':record['budget_token'],
                                     'host_identity':record['host_identity']}}
                    if mode=='wrong_stop_operation':stopped['operation']['operation_id']='other-operation'
                    if mode=='wrong_stop_identity':stopped['identity']={'other-supervisor':True}
                    if mode!='unknown_stop':owned_process._signed_write(supervisor,stopped)
                    pending=client.render_terminal_pending_record(record)
                    write_snapshot(path,{'operations':{record['request_id']:pending}})
                    original_store=path.read_bytes()
                    if mode=='changed_output':case.fixture.path.write_bytes(b'changed final output')
                    with mock.patch.object(client,'seal_render_terminal',side_effect=AssertionError('recovery resealed original')):
                        if mode in ('corrupt','producer_mismatch','terminal_identity_mismatch','changed_output',
                                    'wrong_stop_operation','wrong_stop_identity'):
                            with self.assertRaises((client.BridgeError,ValueError)):
                                client.read_render_operation(binding,task_id=record['task_id'],operation_id=record['request_id'])
                            self.assertEqual(path.read_bytes(),original_store)
                            self.assertEqual(bool(scheduler.snapshot()['active']),mode in ('wrong_stop_operation','wrong_stop_identity'))
                        else:
                            result=client.read_render_operation(binding,task_id=record['task_id'],operation_id=record['request_id'])
                            expected={'valid':'COMPLETED','missing':'FAILED','unknown_stop':'RUNNING'}[mode]
                            self.assertEqual(result['operation']['state'],expected)
                            if mode=='valid':
                                self.assertEqual(result['execution_fact'],original['execution_fact'])
                                self.assertNotIn('stop_receipt',result['operation'])
                                self.assertEqual(result['operation']['terminal_recovery_stop_receipt'],stopped)
                                self.assertEqual(json.loads(path.read_text())['operations'][record['request_id']]['state'],'COMPLETED')
                            if mode=='unknown_stop':
                                self.assertIsNone(result['execution_fact'])
                                self.assertEqual(path.read_bytes(),original_store)
                            self.assertEqual(bool(scheduler.snapshot()['active']),mode=='unknown_stop')
                finally:case.doCleanups()
