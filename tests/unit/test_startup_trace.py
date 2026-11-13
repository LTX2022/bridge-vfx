"""Startup evidence boundaries only; commercial software is never launched."""
import hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dcc_task_runtime import owned_process,native_scope as ns,startup_trace as startup
from dcc_task_runtime.writer_tool_trace import file_record


class StartupFixture:
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();(self.root/'startup-trace').mkdir()
        (self.root/'receipt.key').write_bytes(b'explicit startup software test fixture')
        self.identity={'task_id':'fixture','operation_id':'official-open-save'}
        self.binding={'path':str(self.root/'scope.json'),'sha256':'a'*64}
        self.command=['/fixture/hython','/fixture/worker.py']
        self.parent={'pid':888,'birth':'Tue Oct 27 11:15:39 2026','state':'alive','platform':'posix'}
        self.scope=SimpleNamespace(binding=self.binding,scope={'hosts':{'hython':{'path':'/fixture/hython'}},
            'writer_trace_tools':{name:file_record(path) for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}},
            _envelope=lambda payload:{'payload':payload,'signature':'explicit software fixture, not native authority'})
        now=time.monotonic()
        self.intent={'native_scope_ticket':{'id':'ticket'},'writer_runtime':{'nonce':'b'*32,'collection_end':now+20},'command':self.command}
        (self.root/'intent.json').write_text(json.dumps(self.intent))
        self.child={'schema':owned_process.SCHEMA,'event':'diagnostic-child','identity':self.identity,
            'purpose':'STARTUP_DIAGNOSTIC_ONLY_NO_IMAGE_PROOF','scope_binding':self.binding,'pid':999,'supervisor_pid':888,
            'supervisor_identity':self.parent,'ticket_id':'ticket','runtime_nonce':'b'*32,
            'argv_sha256':hashlib.sha256(owned_process._canonical(self.command)).hexdigest(),
            'popen_return_monotonic':now,'popen_time_origin':'owned_popen_return','collection_end_monotonic':now+20}
        owned_process._signed_write(self.root,self.child)

    def witness(self):
        return startup.StartupWitness(self.scope,self.root,self.identity,self.command,began=time.monotonic(),deadline=time.monotonic()+60)

    def capture(self,argv,deadline,cancel,**kwargs):
        if argv[-1]=='lstart=,stat=':data=b'Tue Oct 27 11:15:39 2026 S\n'
        elif argv[0]=='/usr/bin/sample':
            data=b'Process: hython [999]\nPath: /fixture/hython\nParent Process: Python [888]\nLaunch Time: 2026-10-27 11:15:39.123 +0000\nCall graph:\n    10 Thread_1\n    + 10 actual (in libfixture) + 1 [0x123]\nTotal number in stack: 1\n'
        else:data=b'999 888 Tue Oct 27 11:15:39 2026 S /fixture/hython\n'
        return {'argv':argv,'pid':333,'spawned':True,'complete':True,'stdout':data,'stderr':b'',
            'started_monotonic':time.monotonic(),'ended_monotonic':time.monotonic(),'termination_reason':'RETURNED',
            'cleanup':{'leader_reaped':True,'group_absent':True,'errors':[]}}

    def supervisor_only(self,argv,deadline,cancel,**kwargs):
        if argv[-1]!='lstart=,stat=':raise AssertionError('unexpected child sample')
        return self.capture(argv,deadline,cancel,**kwargs)


class StartupTraceTests(StartupFixture,unittest.TestCase):
    def test_supervisor_birth_uses_inherited_timezone_while_child_tools_stay_utc(self):
        self.child['supervisor_identity']['birth']='Tue Oct 27 14:06:50 2026'
        owned_process._signed_write(self.root,self.child)
        seen=[]
        def capture(argv,deadline,cancel,**kwargs):
            seen.append((argv,kwargs))
            result=self.capture(argv,deadline,cancel)
            if argv[-1]=='lstart=,stat=':
                self.assertTrue(kwargs.get('inherit_timezone'))
                result['stdout']=b'Tue Oct 27 14:06:50 2026 Rs\n'
            else:self.assertFalse(kwargs.get('inherit_timezone',False))
            return result
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=capture):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        value=witness.finish()
        diagnostic=json.loads((self.root/'startup-diagnostic.json').read_text())['payload']
        self.assertIsNone(diagnostic['reason']);self.assertEqual(diagnostic['state'],'CAPTURED')
        self.assertEqual(len(seen),4);self.assertTrue(value['cleanup_complete'])

    def test_capture_timezone_environment_matches_supervisor_contract_only_when_opted_in(self):
        from dcc_task_runtime.writer_tool_trace import _tool_environment
        with patch.dict(os.environ,{'TZ':'Asia/Shanghai'}):
            self.assertEqual(_tool_environment(inherit_timezone=True)['TZ'],'Asia/Shanghai')
            self.assertEqual(_tool_environment()['TZ'],'UTC')
            self.assertEqual(_tool_environment(inherit_timezone=True)['LC_ALL'],'C')
        with patch.dict(os.environ,{},clear=True):
            self.assertNotIn('TZ',_tool_environment(inherit_timezone=True))
            self.assertEqual(_tool_environment()['TZ'],'UTC')

    def test_different_supervisor_birth_still_rejected_in_same_timezone(self):
        self.child['supervisor_identity']['birth']='Tue Oct 27 11:15:40 2026'
        owned_process._signed_write(self.root,self.child)
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=self.supervisor_only):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        diagnostic=json.loads((self.root/'startup-diagnostic.json').read_text())['payload'] if (self.root/'startup-diagnostic.json').exists() else None
        self.assertFalse(witness.finish()['diagnostic_complete'])
        self.assertIn('STARTUP_CHILD_FACT_MISMATCH',witness.reason)

    def test_same_owned_hython_stack_and_stages_are_separate_from_image_proof(self):
        startup.stage(self.root/'startup-trace','worker_python_entry',pid=999)
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=self.capture):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        self.assertFalse(witness.thread.is_alive());account=witness.finish()
        value=json.loads((self.root/'startup-diagnostic.json').read_text())['payload']
        self.assertEqual(value['state'],'CAPTURED');self.assertTrue(value['sample_identity_matches'])
        self.assertTrue(value['not_host_image_proof']);self.assertEqual(len(value['auxiliary_tools']),4)
        self.assertTrue(account['cleanup_complete']);self.assertTrue(account['includes_auxiliary_tail_and_diagnostic_sealing'])
        self.assertEqual(account['budget_seconds'],60)

    def test_live_target_sampling_has_no_eager_preload_and_requires_post_identity(self):
        def capture(argv,deadline,cancel,**kwargs):
            if argv[0]=='/usr/bin/sample':self.assertNotIn('-mayDie',argv)
            result=self.capture(argv,deadline,cancel,**kwargs)
            if argv[0]=='/bin/ps' and argv[-1]!='lstart=,stat=':
                self.observed_child_ps+=1
                if self.observed_child_ps==2:result['stdout']=b'999 888 Tue Oct 27 11:15:40 2026 S /fixture/hython\n'
            return result
        self.observed_child_ps=0;witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=capture):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        result=witness.finish();diag=json.loads((self.root/'startup-diagnostic.json').read_text())['payload']
        self.assertEqual(self.observed_child_ps,2);self.assertFalse(diag['sample_identity_matches'])
        self.assertFalse(result['diagnostic_complete']);self.assertTrue(result['cleanup_complete'])

    def test_sample_deadline_never_counts_as_stack_and_is_not_retried(self):
        samples=[]
        def capture(argv,deadline,cancel,**kwargs):
            result=self.capture(argv,deadline,cancel,**kwargs)
            if argv[0]=='/usr/bin/sample':
                samples.append(argv);result.update(complete=False,termination_reason='DEADLINE',stdout=b'')
            return result
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=capture):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        result=witness.finish();diag=json.loads((self.root/'startup-diagnostic.json').read_text())['payload']
        self.assertEqual(len(samples),1);self.assertEqual(diag['state'],'INCOMPLETE')
        self.assertFalse(result['diagnostic_complete']);self.assertTrue(result['cleanup_complete'])

    def test_ready_before_trigger_prevents_extra_sampling(self):
        owned_process._signed_write(self.root,{'schema':owned_process.SCHEMA,'event':'runtime-ready','identity':self.identity,
            'pid':999,'argv_sha256':self.child['argv_sha256'],'runtime_nonce':'b'*32,'observed_at':time.time()})
        witness=self.witness()
        with patch.object(startup,'_capture',side_effect=self.supervisor_only):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        account=witness.finish();value=json.loads((self.root/'startup-diagnostic.json').read_text())['payload']
        self.assertEqual(value['state'],'SKIPPED_READY_OR_STOPPED');self.assertTrue(account['cleanup_complete'])

    def test_bad_ticket_or_supervisor_cannot_select_a_pid(self):
        self.child['ticket_id']='wrong';owned_process._signed_write(self.root,self.child)
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=self.supervisor_only):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        value=witness.finish();self.assertFalse(value['diagnostic_complete'])

    def test_startup_only_budget_is_one_start_and_60_seconds(self):
        import test_native_scope as fixture
        from dcc_task_runtime.render_profiles import OFFICIAL
        root=self.root/'scope';root.mkdir()
        tools={name:file_record(path) for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
        binding=fixture.software_scope(root,schema=ns.OFFICIAL_SCOPE_SCHEMA,resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,
            scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_STARTUP_DIAGNOSTIC_MODE,budget=ns.OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET,writer_trace_tools=tools)
        scope=ns.NativeScope(binding);self.assertEqual(scope.role_seconds('official-open-save'),60)
        with self.assertRaises(ValueError):scope.admit('official-identity-1',root/'forbidden',{'op':'bad'})
        self.assertEqual(scope.scope['budget']['max_dcc_starts'],1)

    def test_new_environment_is_opt_in_and_does_not_change_runtime_shape(self):
        plain=owned_process._writer_runtime_spec(self.root,{'env':{},'budget_seconds':60,'identity':self.identity})
        self.assertNotIn(startup.ENV,plain['env'])
        folder=self.root/'fresh';folder.mkdir()
        traced=owned_process._writer_runtime_spec(folder,{'env':{},'budget_seconds':60,'identity':self.identity},startup_diagnostic=True)
        self.assertEqual(set(traced['writer_runtime']),{'nonce','session_end','collection_end'})
        self.assertEqual(traced['env'][startup.ENV],str(folder/'startup-trace'))




class StartupProtocolTests(StartupFixture,unittest.TestCase):
    def test_bad_ready_nonce_is_diagnostic_failure_not_skip(self):
        owned_process._signed_write(self.root,{'schema':owned_process.SCHEMA,'event':'runtime-ready','identity':self.identity,
            'pid':999,'argv_sha256':self.child['argv_sha256'],'runtime_nonce':'wrong','observed_at':time.time()})
        witness=self.witness()
        with patch.object(startup,'_capture',side_effect=self.supervisor_only):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        account=witness.finish();self.assertFalse(account['diagnostic_complete'])

    def test_native_stop_is_not_rewritten_by_parent_tail_sealing(self):
        witness=self.witness()
        with patch.object(startup,'TRIGGER_SECONDS',0),patch.object(startup,'_capture',side_effect=self.capture):
            witness.start(SimpleNamespace(pid=888));witness.thread.join(2)
        start={'schema':owned_process.SCHEMA,'event':'started','identity':self.identity,'pid':999}
        owned_process._signed_write(self.root,start)
        stop={'schema':owned_process.SCHEMA,'event':'stopped','identity':self.identity,'pid':999,
            'observed_by':'owned_child_wait','exit_code':-15,'observed_at':time.time(),
            'started_sha256':hashlib.sha256(owned_process._canonical(start)).hexdigest()}
        owned_process._signed_write(self.root,stop);original=(self.root/'stopped.json').read_bytes()
        account=witness.finish()
        self.assertEqual((self.root/'stopped.json').read_bytes(),original)
        self.assertTrue(account['native_stop_unchanged']);self.assertTrue(account['includes_auxiliary_tail_and_diagnostic_sealing'])

    def test_early_popen_fact_survives_ready_collection_failure(self):
        import subprocess
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(5)'],start_new_session=True)
        scope=SimpleNamespace(scope={'execution_mode':ns.OFFICIAL_STARTUP_DIAGNOSTIC_MODE},binding=self.binding,
            resource_profile=None,check=lambda:None,finish=lambda ticket:None)
        now=time.monotonic();spec={'identity':self.identity,'command':['explicit-software-fixture'],
            'budget_seconds':.5,'writer_executable':{},'native_scope_ticket':{'id':'ticket'},
            'writer_runtime':{'nonce':'b'*32,'collection_end':now+.5,'session_end':now+.5},
            'env':{startup.ENV:str(self.root/'startup-trace')}}
        from dcc_task_runtime import process_image
        images=SimpleNamespace(_ps=lambda *args:(888,123),OBSERVE_TIMEOUT_SECONDS=16,ProcessImageError=process_image.ProcessImageError)
        try:
            with patch.object(owned_process,'_process_images',return_value=images), \
                 patch.object(owned_process,'_freeze_writer_executable',return_value={}), \
                 patch.object(owned_process,'_wait_writer_runtime_ready',side_effect=ValueError('explicit ready failure')):
                owned_process._supervise_owned(self.root,spec,child,native_scope=scope,popen_monotonic=now)
            event=owned_process.read_receipt(self.root,'diagnostic-child',identity=self.identity)
            signed_start=owned_process.read_receipt(self.root,'started',identity=self.identity)
            self.assertEqual(event['pid'],child.pid);self.assertEqual(event['scope_binding'],self.binding)
            self.assertEqual(event['purpose'],'STARTUP_DIAGNOSTIC_ONLY_NO_IMAGE_PROOF')
            self.assertIn('explicit ready failure',signed_start['writer_process_binding_error'])
            self.assertIsNotNone(child.returncode)
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=2)

    def test_startup_worker_returns_before_business_without_vmmap_sampler(self):
        from houdini_bridge import official_karma_worker as worker
        scope=SimpleNamespace(scope={'execution_mode':ns.OFFICIAL_STARTUP_DIAGNOSTIC_MODE},binding=self.binding)
        case={'paths':{k:str(self.root/(k+'.unused')) for k in ('official_hip','official_usd','official_image')}}
        with patch.object(worker,'current_authority',return_value=(scope,case,self.root,self.identity,{'pid':os.getpid()})), \
             patch.object(worker,'_run_owned',side_effect=AssertionError('no HIP business')) as business:
            result=worker.run('software-fixture','official-open-save')
        business.assert_not_called();self.assertIsNone(result['writer_tool_trace'])
        self.assertEqual(result['hip_business'],'NOT_RUN')




class StartupLaunchBoundaryTests(unittest.TestCase):
    def test_special_observer_starts_before_waiting_for_final_started(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();directory=root/'owned';identity={'task_id':'fixture','operation_id':'official-open-save'}
            binding={'path':'fixture','sha256':'a'*64};order=[]
            scope=SimpleNamespace(scope={'execution_mode':ns.OFFICIAL_STARTUP_DIAGNOSTIC_MODE},resource_profile=None,
                role_seconds=lambda role:60,admit=lambda role,path,ident,**kw:{'id':'ticket','role':role,'identity':ident,'directory':str(path),'reused':False})
            process=SimpleNamespace(pid=888,wait=lambda **kw:None,poll=lambda:None)
            def callback(supervisor):
                self.assertEqual(supervisor.pid,888);order.append('observer')
            def receipt(path,event,**kw):
                if event=='started':order.append('started-read');return {'pid':999}
            with patch.object(owned_process,'_native_scope',return_value=scope), \
                 patch.object(owned_process,'_disk_usage',return_value=0), \
                 patch.object(owned_process,'_freeze_writer_executable',return_value={}), \
                 patch.object(owned_process.subprocess,'Popen',return_value=process), \
                 patch.object(owned_process,'read_receipt',side_effect=receipt):
                handle=owned_process.launch(['fixture-never-executed'],directory=directory,identity=identity,
                    supervisor_executable=sys.executable,writer_executable={},scope_role='official-open-save',
                    budget_seconds=55,resource_budget={'native_scope':binding,'max_bytes':536870912,'roots':[str(root)]},on_supervisor_spawned=callback)
            self.assertEqual(order[0],'observer');self.assertEqual(handle.pid,999)

    def test_early_callback_is_forbidden_on_default_launch(self):
        with patch.object(owned_process.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(owned_process.SupervisorNotStarted,'CALLBACK_FORBIDDEN'):
                owned_process.launch(['fixture'],directory='/unused',identity={'task':'fixture'},supervisor_executable=sys.executable,
                    on_supervisor_spawned=lambda process:None)
            launch.assert_not_called()

    def test_driver_rejects_final_accounting_write_crossing_parent_deadline(self):
        self._driver_rejects_accounting(diagnostic_complete=True,late_sealing=True)

    def test_driver_rejects_incomplete_even_if_native_and_cleanup_succeed(self):
        self._driver_rejects_accounting(diagnostic_complete=False,late_sealing=False)

    def test_driver_rejects_post_sealing_native_validation_crossing_deadline(self):
        self._driver_rejects_accounting(diagnostic_complete=True,late_sealing=False,late_original=True)

    def _driver_rejects_accounting(self,*,diagnostic_complete,late_sealing,late_original=False):
        from test_official_karma_preparation import tool
        from houdini_bridge import official_karma_worker as worker,official_karma_observation as observation
        driver=tool('run_controlled_engineering')
        from dcc_task_runtime import process_image
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();scope={'execution_mode':ns.OFFICIAL_STARTUP_DIAGNOSTIC_MODE,'scope_id':'fixture',
                'hosts':{'hython':{'path':'/fixture/hython','sha256':'a'*64},'supervisor_python':{'path':sys.executable}}}
            budget=SimpleNamespace(native=SimpleNamespace(root=root,check=lambda:None),binding={'path':'fixture','sha256':'b'*64},
                available=lambda **kw:None,remaining=lambda:60.,resource_budget={})
            data={'scope':scope,'bindings':{'environment':{}}}
            clock=[0.]
            def finish():
                account={'over_budget':False,'cleanup_complete':True,'diagnostic_complete':diagnostic_complete}
                if late_sealing:clock[0]=61.
                return account
            witness=SimpleNamespace(start=lambda process:None,finish=finish)
            def launch(*args,**kwargs):
                kwargs['on_supervisor_spawned'](SimpleNamespace(pid=888))
                return SimpleNamespace(wait=lambda **kw:None)
            with patch.object(worker,'check_frozen_case',return_value={'commands':{'official-open-save':['fixture-never-executed']},'paths':{'warm_supervisor':str(root/'owned')}}), \
                 patch.object(process_image,'freeze_executable',return_value={}), \
                 patch.object(owned_process,'launch',side_effect=launch), \
                 patch.object(startup,'StartupWitness',return_value=witness), \
                 patch.object(observation,'native_original',side_effect=lambda *args:clock.__setitem__(0,61.) if late_original else None) as original, \
                 patch.object(driver.time,'monotonic',side_effect=lambda:clock[0]):
                with self.assertRaisesRegex(ValueError,'EXTERNAL_DIAGNOSTIC_INCOMPLETE'):
                    driver._official_prefix(data,None,budget,lambda name,request,fn:fn())
                if late_original:original.assert_called_once()
                else:original.assert_not_called()


if __name__=='__main__':unittest.main()
