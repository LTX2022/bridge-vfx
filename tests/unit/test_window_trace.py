"""Window correlation and signed events only. No native DCC or profiler launches."""
import hashlib,importlib.util,json,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dcc_task_runtime import owned_process,window_trace as w,native_scope as ns
from dcc_task_runtime.writer_tool_trace import file_record
from test_startup_trace import StartupFixture

class WindowTests(StartupFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.parent['pid']=os.getpid();self.child['supervisor_pid']=os.getpid();self.child['supervisor_identity']=self.parent
        owned_process._signed_write(self.root,self.child)
        self.scope.scope.update(execution_mode=ns.OFFICIAL_WINDOW_DIAGNOSTIC_MODE,stack_qualification={'path':'explicit-software-fixture','bytes':1,'sha256':'b'*64})
        self.scope.scope['writer_trace_tools']['vmmap']=file_record('/usr/bin/vmmap')
    def witness(self):
        return w.WindowWitness(self.scope,self.root,self.identity,self.command,began=time.monotonic(),deadline=time.monotonic()+60)
    def receipts(self,error='ValueError:SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT'):
        start={'schema':owned_process.SCHEMA,'event':'started','identity':self.identity,'pid':999,'writer_process_binding_error':error}
        owned_process._signed_write(self.root,start)
        owned_process._signed_write(self.root,{'schema':owned_process.SCHEMA,'event':'stopped','identity':self.identity,'pid':999,
            'observed_by':'owned_child_wait','exit_code':-15,'observed_at':time.time(),
            'started_sha256':hashlib.sha256(owned_process._canonical(start)).hexdigest()})
    def capture(self,argv,deadline,cancel,**kwargs):
        now=time.monotonic()
        if argv[-1]=='lstart=,stat=':data=b'Tue Oct 27 11:15:39 2026 S\n'
        else:
            pid=int(argv[2] if argv[0]=='/bin/ps' else argv[1]);path='/fixture/hython' if pid==999 else '/usr/bin/vmmap'
            if argv[0]=='/bin/ps':data=(f'{pid} {os.getpid()} Tue Oct 27 11:15:39 2026 S {path}\n').encode()
            else:data=(f'Analysis of sampling {Path(path).name} (pid {pid}) every 1 millisecond\nCall graph:\n    1 Thread_1\n      1 fixture_frame (in libfixture) + 1 [0x123]\nTotal number in stack:\n').encode()
        return {'argv':argv,'pid':333,'spawned':True,'complete':True,'stdout':data,'stderr':b'',
            'started_monotonic':now,'ended_monotonic':time.monotonic(),'deadline_monotonic':deadline,'termination_reason':'RETURNED',
            'cleanup':{'leader_reaped':True,'group_absent':True,'errors':[]}}
    def test_startup_snapshot_is_bound_to_same_signed_timeout(self):
        calls=[]
        def capture(argv,*args,**kwargs):
            value=self.capture(argv,*args,**kwargs);calls.append(argv)
            if argv[0]=='/bin/ps' and argv[-1]!='lstart=,stat=' and len(calls)==4:self.receipts()
            return value
        witness=self.witness()
        with patch.object(w,'POINTS',(0.,)),patch.object(w,'_capture',side_effect=capture),patch('dcc_task_runtime.startup_trace._capture',side_effect=capture):
            witness.start(SimpleNamespace(pid=os.getpid()));witness.thread.join(2)
        self.assertFalse(witness.thread.is_alive());account=witness.finish()
        report=json.loads((self.root/'window-captures.json').read_text())['payload']
        self.assertTrue(account['diagnostic_complete'],report);self.assertEqual(report['same_timeout_stack_count'],1)
        self.assertEqual(len(calls),4);self.assertTrue(report['rows'][0]['valid_stack'])
    def source(self):
        return w.SignedToolEvents(self.root,identity=self.identity,scope_binding=self.binding,writer_pid=999,spec=self.intent)
    def test_signed_vmmap_start_end_and_original_timeout_are_correlated(self):
        witness=self.witness();source=self.source();now=time.monotonic()
        index=source.spawned(SimpleNamespace(pid=555),['/usr/bin/vmmap','-w','-interleaved','-summary','999'],now-1.22,now+3.78)
        start=source.rows[0]['start'];start['popen_monotonic']=now-1.21;owned_process._signed_write(self.root,start)
        owned_process._signed_write(self.root,{'schema':owned_process.SCHEMA,'event':'runtime-ready','identity':self.identity,
            'pid':999,'runtime_nonce':self.child['runtime_nonce'],'argv_sha256':self.child['argv_sha256'],'observed_at':time.time()})
        count=[0]
        def capture(argv,*args,**kwargs):
            value=self.capture(argv,*args,**kwargs)
            if argv[0]=='/bin/ps' and argv[-1]!='lstart=,stat=':
                count[0]+=1
                if count[0]==2:
                    source.finished(index,-9,{'reason':'PROCESS_IMAGE_TIMEOUT','cleanup':{'leader_reaped':True,'errors':[]}});source.close();self.receipts('ProcessImageError:PROCESS_IMAGE_TIMEOUT')
            return value
        with patch.object(w,'POINTS',()),patch.object(w,'_capture',side_effect=capture),patch('dcc_task_runtime.startup_trace._capture',side_effect=capture):
            witness.start(SimpleNamespace(pid=os.getpid()));witness.thread.join(2)
        self.assertFalse(witness.thread.is_alive());account=witness.finish()
        report=json.loads((self.root/'window-captures.json').read_text())['payload']
        self.assertTrue(account['diagnostic_complete'],report);self.assertEqual(report['same_timeout_stack_count'],1)
        self.assertEqual(report['rows'][0]['kind'],'vmmap')
    def test_short_natural_vmmap_finishes_before_late_capture_admission(self):
        import threading
        witness=self.witness();source=self.source();now=time.monotonic();calls=[]
        index=source.spawned(SimpleNamespace(pid=555),['/usr/bin/vmmap','-w','-interleaved','-summary','999'],now,now+5)
        owned_process._signed_write(self.root,{'schema':owned_process.SCHEMA,'event':'runtime-ready','identity':self.identity,
            'pid':999,'runtime_nonce':self.child['runtime_nonce'],'argv_sha256':self.child['argv_sha256'],'observed_at':time.time()})
        def complete():
            source.finished(index,0,None);source.close();self.receipts(error='')
        timer=threading.Timer(.6,complete)
        def capture(argv,*args,**kwargs):
            calls.append(argv);return self.capture(argv,*args,**kwargs)
        with patch.object(w,'_capture',side_effect=capture),patch('dcc_task_runtime.startup_trace._capture',side_effect=capture):
            timer.start();witness.start(SimpleNamespace(pid=os.getpid()));witness.thread.join(2)
        timer.join();account=witness.finish()
        self.assertTrue(account['diagnostic_complete'])
        self.assertEqual([argv for argv in calls if argv[0]=='/usr/bin/sample'],[])
        report=json.loads((self.root/'window-captures.json').read_text())['payload']
        self.assertEqual(report['rows'],[])

    def test_wrong_ticket_or_negative_child_pid_never_samples(self):
        for key,value in (('ticket_id','different'),('pid',-1)):
            with self.subTest(key=key):
                old=dict(self.child);self.child[key]=value;owned_process._signed_write(self.root,self.child)
                witness=self.witness()
                with patch('dcc_task_runtime.startup_trace._capture',side_effect=self.capture),patch.object(w,'_capture',side_effect=AssertionError('must not sample')):
                    witness.start(SimpleNamespace(pid=os.getpid()));witness.thread.join(1)
                self.assertIn('CHILD_FACT_MISMATCH',witness.reason);self.child=old
                for name in ('startup-supervisor.stdout','startup-supervisor.stderr'):
                    (self.root/name).unlink(missing_ok=True)
    def test_foreign_vmmap_event_and_short_effective_window_rejected(self):
        witness=self.witness();witness.child=self.child;witness.intent=self.intent
        source=self.source();now=time.monotonic();source.spawned(SimpleNamespace(pid=555),['/usr/bin/vmmap','-w','-interleaved','-summary','999'],now,now+4)
        value=owned_process.read_receipt(self.root,'window-tool-start-0',identity=self.identity);value['ticket_id']='foreign';owned_process._signed_write(self.root,value)
        with self.assertRaisesRegex(ValueError,'EVENT_IDENTITY'):witness._refresh()
    def test_source_limit_and_unsupported_command_do_not_invent_more_vmmap(self):
        source=self.source();now=time.monotonic()
        for index in range(4):source.spawned(SimpleNamespace(pid=555+index),['/usr/bin/vmmap','-w','-interleaved','-summary','999'],now,now+4)
        with self.assertRaisesRegex(ValueError,'LIMIT'):source.spawned(SimpleNamespace(pid=600),['/usr/bin/vmmap','-w','-interleaved','-summary','999'],now,now+4)
        self.assertEqual(len(source.rows),4)
    def test_deadline_is_not_masked_by_normal_tool_finish_and_no_post_probe_is_started(self):
        witness=self.witness();witness.child=self.child;witness.intent=self.intent;calls=[]
        def capture(argv,*args,**kwargs):
            calls.append(argv);value=self.capture(argv,*args,**kwargs)
            if argv[0]=='/usr/bin/sample':value.update(complete=False,termination_reason='DEADLINE')
            return value
        with patch.object(w,'_capture',side_effect=capture),patch.object(witness,'_normal_done',return_value=True):
            with self.assertRaisesRegex(ValueError,'SAMPLE_INCOMPLETE'):
                witness._capture_window('vmmap',0,555,'/usr/bin/vmmap',time.monotonic()+4)
        self.assertEqual(len(calls),2);self.assertFalse(witness.rows[0]['valid_stack'])

    def test_normal_tool_cancellation_requires_known_cleanup(self):
        for clean in (True,False):
            with self.subTest(clean=clean):
                witness=self.witness();witness.child=self.child;witness.intent=self.intent
                def capture(argv,*args,**kwargs):
                    value=self.capture(argv,*args,**kwargs)
                    if argv[0]=='/usr/bin/sample':
                        value.update(complete=False,termination_reason='CANCELLED')
                        value['cleanup']['group_absent']=clean
                    return value
                with patch.object(w,'_capture',side_effect=capture),patch.object(witness,'_normal_done',return_value=True):
                    if clean:witness._capture_window('vmmap',0,555,'/usr/bin/vmmap',time.monotonic()+4)
                    else:
                        with self.assertRaisesRegex(ValueError,'CLEANUP_UNKNOWN'):witness._capture_window('vmmap',0,555,'/usr/bin/vmmap',time.monotonic()+4)
                self.assertFalse(witness.rows[0]['valid_stack'])
                for name in (self.root/'startup-trace').glob('vmmap-*'):name.unlink()

    def test_late_admission_does_not_launch_auxiliary_tools(self):
        now=time.monotonic();self.child['popen_return_monotonic']=now-20;self.child['collection_end_monotonic']=now+1
        self.intent['writer_runtime']['collection_end']=now+1;(self.root/'intent.json').write_text(json.dumps(self.intent))
        owned_process._signed_write(self.root,self.child);witness=self.witness()
        with patch('dcc_task_runtime.startup_trace._capture',side_effect=self.capture),patch.object(w,'_capture',side_effect=AssertionError('late sampling forbidden')):
            witness.start(SimpleNamespace(pid=os.getpid()));witness.thread.join(1)
        self.assertIn('TIME_INSUFFICIENT',witness.reason);self.assertEqual(witness.rows,[])

    def test_scope_budget_and_role_gate_are_one_start_sixty_seconds(self):
        import test_native_scope as fixture
        from dcc_task_runtime.render_profiles import OFFICIAL
        from test_official_karma_preparation import tool
        folder=self.root/'scope';folder.mkdir()
        binding=fixture.software_scope(folder,schema=ns.OFFICIAL_SCOPE_SCHEMA,resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,
            scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_WINDOW_DIAGNOSTIC_MODE,budget=ns.OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET,
            writer_trace_tools=self.scope.scope['writer_trace_tools'],stack_qualification=self.scope.scope['stack_qualification'])
        scope=ns.NativeScope(binding);self.assertEqual(scope.role_seconds('official-open-save'),60)
        self.assertEqual(tool('run_alpha_calibration')._limits(scope.scope)['max_dcc_starts'],1)
        with self.assertRaises(ValueError):scope.admit('official-cold-export',folder/'forbidden',{'op':'fixture'})

    def test_qualification_gate_requires_frames_bound_stop_and_same_tools(self):
        from houdini_bridge.official_karma_observation import validate_stack_qualification
        def save(name,value):
            path=self.root/name;path.write_text(json.dumps(value));return file_record(path)
        dummy=save('dummy.json',{'explicit':'software fixture'})
        review=save('qreview.json',{'tools':self.scope.scope['writer_trace_tools'],'target_runtime_image':{'path':'/fixture/Python'}})
        value={'state':'VERIFIED_ORDINARY_TARGET_STACK_EVIDENCE_ONLY','H21_authorized':False,'offline_verifier_observed_exit_code':0,
            'new_targets_or_sample_or_ps_calls':0,'raw_inputs':[save(name+'.'+stream,{'explicit':'stream fixture'}) for name in ('before','sample','after') for stream in ('stdout','stderr')],
            'original_native_stop_and_all_auxiliary_cleanup_verified':True,'sample_seconds':.4,'total_measured_before_original_final_write':.5,
            'binding':{'pid':999,'parent_pid':888,'birth':'fixed fixture','native_frames':['1 frame (in fixture) + 1 [0x123]'],'path':'/fixture/Python','not_host_image_proof':True}}
        for name in ('parser_source','verifier','original_result','original_signed_started','original_signed_stopped','original_live_evidence','offline_verification'):value[name]=dummy
        value['review']=review;record=save('proof.json',value)
        validate_stack_qualification(record,self.scope.scope['writer_trace_tools'])
        value['binding']['native_frames']=[];record=save('proof.json',value)
        with self.assertRaisesRegex(ValueError,'EVIDENCE_INCOMPLETE'):validate_stack_qualification(record,self.scope.scope['writer_trace_tools'])
        value['binding']['native_frames']=['1 frame (in fixture) + 1 [0x123]'];record=save('proof.json',value)
        changed=dict(self.scope.scope['writer_trace_tools']);changed['sample']=dict(changed['sample'],sha256='f'*64)
        with self.assertRaisesRegex(ValueError,'TOOLS_CHANGED'):validate_stack_qualification(record,changed)

    def test_empty_diagnostic_stream_is_checked_without_relaxing_business_artifacts(self):
        from houdini_bridge.official_karma_observation import checked_capture_stream,checked_bytes
        path=self.root/'before.stderr';path.write_bytes(b'');record=file_record(path)
        self.assertEqual(checked_capture_stream(record),b'')
        with self.assertRaisesRegex(ValueError,'FILE_RECORD_INVALID'):checked_bytes(record)
        record=dict(record,sha256='f'*64)
        with self.assertRaisesRegex(ValueError,'STREAM_CHANGED'):checked_capture_stream(record)

    def test_early_checkpoint_precedes_standard_library_entry_and_never_runs_business(self):
        from houdini_bridge import official_karma_worker as worker
        with patch.dict(os.environ,{'BRIDGE_OWNED_WINDOW_MODE':'1','BRIDGE_OWNED_STARTUP_TRACE_DIR':str(self.root/'startup-trace'),'BRIDGE_OWNED_SUPERVISOR_DIR':str(self.root)}):
            spec=importlib.util.spec_from_file_location('_window_early_fixture',worker.__file__);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        first=json.loads((self.root/'startup-trace/worker_minimal_python_entry.json').read_text())
        second=json.loads((self.root/'startup-trace/worker_python_entry.json').read_text())
        self.assertEqual(first['pid'],os.getpid());self.assertLessEqual(first['monotonic'],second['monotonic'])

if __name__=='__main__':unittest.main()
