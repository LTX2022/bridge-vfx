"""Diagnostic boundaries only: no Houdini, HIP loading, rendering or Nuke."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dcc_task_runtime import process_image as image,writer_tool_trace as trace


class ToolObserverTests(unittest.TestCase):
    def test_optional_callback_errors_preserve_tool_success_and_primary_failure(self):
        errors=[]
        class Broken:
            def spawned(self,*args):raise RuntimeError('explicit diagnostic callback failure')
            def finished(self,*args):raise RuntimeError('explicit diagnostic callback failure')
            def observer_error(self,value):errors.append(value)
        with image.diagnostic_tool_observer(Broken()):
            self.assertEqual(image._run_tool([sys.executable,'-B','-c','print("ok")'],time.monotonic()+2),b'ok\n')
            with self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):
                image._run_tool([sys.executable,'-B','-c','import sys;sys.exit(7)'],time.monotonic()+2)
        self.assertEqual(len(errors),4)
        self.assertIsNone(getattr(image._TOOL_TRACE,'observer',None))

    def test_observer_is_local_to_the_collector_thread(self):
        seen=[]
        class Witness:
            def spawned(self,*args):seen.append('spawn')
            def finished(self,*args):seen.append('finish')
        errors=[]
        def observe_child():
            try:image._run_tool(['/usr/bin/true'],time.monotonic()+2)
            except BaseException as error:errors.append(error)
        with image.diagnostic_tool_observer(Witness()):
            child=threading.Thread(target=observe_child)
            child.start();child.join(3)
            self.assertFalse(child.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(seen,[])


class ToolTraceFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.tools={name:{'path':path,'bytes':1,'sha256':'a'*64} for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}

    def recorder(self):
        with patch.object(trace,'file_record',side_effect=lambda path:self.tools['ps' if str(path)=='/bin/ps' else 'sample']):
            return trace.ToolTrace(self.root/'trace',writer_pid=111,identity={'task':'test'},scope_binding={'path':'fixture','sha256':'b'*64},collection_end=time.monotonic()+10,tools=self.tools)

    def capture(self,argv,deadline,cancel):
        self.assertLessEqual(deadline,self.effective)
        data=(f'Process: vmmap [222]\nPath: /usr/bin/vmmap\nParent Process: Python [{os.getpid()}]\nLaunch Time: 2026-10-27 11:15:39.123 +0000\nCall graph:\n    10 Thread_1\n    + 10 main (in vmmap) + 4 [0x123]\n      + 10 ??? (in Symbolication) + 8 [0x456]\nTotal number in stack: 1\n'.encode() if argv[0]=='/usr/bin/sample' else
              f'222 {os.getpid()} Tue Oct 27 11:15:39 2026 S /usr/bin/vmmap\n'.encode())
        return {'argv':argv,'spawned':True,'complete':True,'ended_monotonic':time.monotonic(),'stdout':data,'stderr':b'',
            'cleanup':{'leader_reaped':True,'group_absent':True,'errors':[]}}

    def start(self,recorder,remaining=5):
        self.effective=time.monotonic()+remaining
        return recorder.spawned(SimpleNamespace(pid=222,returncode=None),['/usr/bin/vmmap','-w','-interleaved','-summary','111'],time.monotonic(),self.effective)

class ToolTraceTests(ToolTraceFixture,unittest.TestCase):
    def test_same_timed_out_call_has_a_bound_nonempty_stack_and_separate_result(self):
        recorder=self.recorder()
        with patch.object(trace,'TRIGGER_SECONDS',0),patch.object(trace,'_capture',side_effect=self.capture):
            row=self.start(recorder);row['thread'].join(2)
        recorder.finished(row,-9,{'reason':'PROCESS_IMAGE_TIMEOUT','tool_pid':222})
        result=recorder.close();value=json.loads(Path(result['record']['path']).read_text())
        self.assertEqual(value['same_timeout_stacks_captured'],[0])
        self.assertTrue(value['cleanup_complete']);self.assertFalse(value['diagnostics_incomplete'])
        self.assertEqual(value['calls'][0]['witness_state'],'CAPTURED')
        self.assertEqual(len(value['calls'][0]['auxiliary_tools']),3)

    def test_short_outer_deadline_cannot_borrow_the_tool_five_seconds(self):
        recorder=self.recorder()
        with patch.object(trace,'TRIGGER_SECONDS',0),patch.object(trace,'_capture',side_effect=AssertionError('must skip')):
            row=self.start(recorder,remaining=.3);row['thread'].join(1)
        recorder.finished(row,-9,{'reason':'PROCESS_IMAGE_TIMEOUT'})
        result=recorder.close();value=json.loads(Path(result['record']['path']).read_text())
        self.assertEqual(value['calls'][0]['reason'],'INSUFFICIENT_WITNESS_TIME')
        self.assertEqual(value['same_timeout_stacks_captured'],[])

    def test_empty_call_graph_never_counts_as_a_captured_timeout_stack(self):
        self.assertFalse(trace.nonempty_call_graph(b'Process: vmmap [222]\nCall graph:\nTotal number in stack: 0',222))
        self.assertFalse(trace.nonempty_call_graph(b'Process: vmmap [999]\nCall graph:\n10 Thread_1\n10 f\n10 g',222))

    def test_diagnostic_capture_caps_and_reaps_ordinary_children(self):
        result=trace._capture([sys.executable,'-B','-c','import sys;print("data");sys.stderr.write("progress")'],time.monotonic()+2,lambda:False)
        self.assertTrue(result['complete']);self.assertEqual(result['stderr'],b'progress')
        self.assertTrue(result['cleanup']['leader_reaped']);self.assertTrue(result['cleanup']['group_absent'])
        result=trace._capture([sys.executable,'-B','-c','import time;time.sleep(5)'],time.monotonic()+.3,lambda:False)
        self.assertFalse(result['complete']);self.assertTrue(result['cleanup']['leader_reaped'])
        self.assertTrue(result['cleanup']['group_absent'])
        with self.assertRaises(ProcessLookupError):os.kill(result['pid'],0)



class IdentityOnlyModeTests(unittest.TestCase):
    def test_one_native_role_and_one_start_cannot_expand_to_business_roles(self):
        from dcc_task_runtime import native_scope as ns
        from dcc_task_runtime.render_profiles import OFFICIAL
        import test_native_scope as fixture
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve()
            tools={name:{'path':path,'bytes':1,'sha256':'a'*64} for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
            binding=fixture.software_scope(root,schema=ns.OFFICIAL_SCOPE_SCHEMA,resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,
                scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_IDENTITY_DIAGNOSTIC_MODE,budget=ns.OFFICIAL_DIAGNOSTIC_BUDGET,
                writer_trace_tools=tools)
            scope=ns.NativeScope(binding)
            for role in ('official-cold-export','official-husk','graph-worker','main-husk','alpha-husk','nuke-host','nuke-render'):
                with self.subTest(role=role),self.assertRaises(ValueError):scope.admit(role,root/role,{'role':role})
            ticket=scope.admit('official-open-save',root/'first',{'op':'one'})
            fixture.NativeScopeTests.stop(self,ticket);scope.finish(ticket)
            with self.assertRaises(ValueError):scope.admit('official-open-save',root/'second',{'op':'two'})
            self.assertEqual(scope.snapshot()['dcc_starts'],1)

    def test_identity_worker_never_calls_scene_business_even_when_identity_succeeds(self):
        from dcc_task_runtime import native_scope as ns,owned_process
        from houdini_bridge import official_karma_worker as worker
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();(root/'receipt.key').write_bytes(b'explicit identity-only software fixture')
            raw=root/'trace.json';raw.write_text('{}')
            record=trace.file_record(raw);identity={'test':'identity-only'}
            scope=SimpleNamespace(scope={'execution_mode':ns.OFFICIAL_IDENTITY_DIAGNOSTIC_MODE},binding={'path':'fixture','sha256':'a'*64})
            case={'paths':{k:str(root/(k+'.unused')) for k in ('official_hip','official_usd','official_image')}}
            start={'writer_tool_trace':{'record':record,'cleanup_complete':True}}
            with patch.object(worker,'current_authority',return_value=(scope,case,root,identity,start)), \
                 patch.object(worker,'_run_owned',side_effect=AssertionError('HIP business forbidden')) as business:
                result=worker.run('explicit-software-fixture','official-open-save')
            business.assert_not_called()
            self.assertEqual(result['hip_business'],'NOT_RUN')
            self.assertEqual(owned_process.read_receipt(root,'official-identity-diagnostic',identity=identity),result)
            start['writer_tool_trace']['cleanup_complete']=False
            with patch.object(worker,'current_authority',return_value=(scope,case,root,identity,start)),self.assertRaisesRegex(ValueError,'TRACE_REQUIRED'):
                worker.run('fixture','official-open-save')

    def test_trace_tools_cannot_enable_observation_in_a_full_or_legacy_scope(self):
        from dcc_task_runtime import native_scope as ns
        import test_native_scope as fixture
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            with self.assertRaisesRegex(ValueError,'TRACE_MODE_REQUIRED'):
                fixture.software_scope(Path(temporary).resolve(),writer_trace_tools={'sample':'unapproved'})

class TraceFailureEvidenceTests(ToolTraceFixture,unittest.TestCase):
    def test_write_failure_cannot_discard_unknown_cleanup(self):
        recorder=self.recorder()
        with patch.object(trace,'TRIGGER_SECONDS',0),patch.object(trace,'_capture',side_effect=self.capture), \
             patch.object(Path,'write_bytes',side_effect=OSError('explicit disk full fixture')):
            original=self.capture
            def unreaped(*args):
                result=original(*args);result['cleanup']={'leader_reaped':False,'group_absent':False,'errors':['fixture']};return result
            with patch.object(trace,'_capture',side_effect=unreaped):
                row=self.start(recorder);row['thread'].join(2)
        recorder.finished(row,-9,{'reason':'PROCESS_IMAGE_TIMEOUT'})
        report=recorder.close();value=json.loads(Path(report['record']['path']).read_text())
        self.assertFalse(report['cleanup_complete'])
        self.assertIn('persistence_error',value['calls'][0]['auxiliary_tools'][0])
        self.assertEqual(value['same_timeout_stacks_captured'],[])

    def test_not_spawned_is_incomplete_but_has_no_unreaped_child(self):
        result=trace._capture(['/bin/ps'],time.monotonic()+1,lambda:True)
        self.assertFalse(result['spawned']);self.assertIsNone(result['cleanup']['leader_reaped'])
        self.assertTrue(trace.cleanup_confirmed(result));self.assertFalse(result['complete'])

    def test_multiple_thread_headers_without_frames_and_changed_birth_are_rejected(self):
        self.assertFalse(trace.nonempty_call_graph(b'Process: vmmap [222]\nCall graph:\n  10 Thread_1\n  10 Thread_2\n  10 Thread_3\nTotal number in stack: 0',222))
        self.effective=time.monotonic()+100
        data=self.capture(['/usr/bin/sample'],self.effective,lambda:False)['stdout']
        self.assertTrue(trace.sample_identity(data,222,os.getpid(),'Tue Oct 27 11:15:39 2026'))
        self.assertFalse(trace.sample_identity(data,222,os.getpid(),'Tue Oct 27 11:15:40 2026'))
        self.assertFalse(trace.sample_identity(data,222,os.getpid()+1,'Tue Oct 27 11:15:39 2026'))



class IdentitySurveyTests(unittest.TestCase):
    def test_fixed_three_roles_share_120_seconds_and_require_prior_stop(self):
        from dcc_task_runtime import native_scope as ns
        from dcc_task_runtime.render_profiles import OFFICIAL
        import test_native_scope as fixture
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();tools={name:{'path':path,'bytes':1,'sha256':'a'*64} for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
            binding=fixture.software_scope(root,schema=ns.OFFICIAL_SCOPE_SCHEMA,resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,
                scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_IDENTITY_SURVEY_MODE,budget=ns.OFFICIAL_IDENTITY_SURVEY_BUDGET,writer_trace_tools=tools)
            scope=ns.NativeScope(binding)
            with self.assertRaises(ValueError):scope.admit(ns.OFFICIAL_IDENTITY_ROLES[1],root/'wrong',{'op':'wrong'})
            for index,role in enumerate(ns.OFFICIAL_IDENTITY_ROLES):
                ticket=scope.admit(role,root/role,{'op':role})
                if index<2:
                    with self.assertRaises(ValueError):scope.admit(ns.OFFICIAL_IDENTITY_ROLES[index+1],root/'next',{'op':'early'})
                fixture.NativeScopeTests.stop(self,ticket);scope.finish(ticket)
            self.assertEqual(scope.snapshot()['dcc_starts'],3)
            self.assertEqual(scope.scope['budget']['total_seconds'],120)
            with self.assertRaises(ValueError):scope.admit(ns.OFFICIAL_IDENTITY_ROLES[0],root/'fourth',{'op':'fourth'})
            for role in ('official-open-save','official-cold-export','official-husk','alpha-husk','graph-worker','nuke-host'):
                with self.assertRaises(ValueError):scope.admit(role,root/role,{'op':role})

    def test_only_expected_original_completion_cancellation_may_advance(self):
        import copy
        normal={'tool_exit_code':0,'tool_diagnostic':None,'thread_joined':True,'witness_state':'INCOMPLETE',
            'reason':'ValueError:TRACE_POST_STATE_UNAVAILABLE','finished_monotonic':10.,'auxiliary_tools':[
                {'spawned':False,'complete':False,'termination_reason':'CANCELLED','ended_monotonic':11.,
                 'cleanup':{'leader_reaped':None,'group_absent':True,'errors':[]}}]}
        summary={'cleanup_complete':True,'observer_errors':[],'same_timeout_stacks_captured':[], 'calls':[copy.deepcopy(normal) for _ in range(4)]}
        self.assertTrue(trace.survey_next_allowed(summary))
        for fault in ('DEADLINE','ERROR','PERSISTENCE','CLEANUP','IDENTITY','TOOL_FAILURE'):
            value=copy.deepcopy(summary);row=value['calls'][0];tool=row['auxiliary_tools'][0]
            if fault in ('DEADLINE','ERROR'):tool['termination_reason']=fault
            elif fault=='PERSISTENCE':tool['persistence_error']='fixture'
            elif fault=='CLEANUP':tool['cleanup']['group_absent']=False
            elif fault=='IDENTITY':row['reason']='ValueError:TRACE_PROCESS_STATE_MISMATCH'
            else:row['tool_diagnostic']={'reason':'PROCESS_IMAGE_TIMEOUT'}
            with self.subTest(fault=fault):self.assertFalse(trace.survey_next_allowed(value))

    def test_auxiliary_deadline_and_cancellation_are_distinct(self):
        cancelled=trace._capture(['/bin/ps'],time.monotonic()+1,lambda:True)
        self.assertEqual(cancelled['termination_reason'],'CANCELLED')
        expired=trace._capture(['/bin/ps'],time.monotonic()-.1,lambda:False)
        self.assertEqual(expired['termination_reason'],'DEADLINE')
        both=trace._capture(['/bin/ps'],time.monotonic()-.1,lambda:True)
        self.assertEqual(both['termination_reason'],'DEADLINE')




class SurveyOrchestrationTests(unittest.TestCase):
    def test_fixed_inventory_and_wrong_budget_are_rejected(self):
        from dcc_task_runtime import native_scope as ns
        from dcc_task_runtime.render_profiles import OFFICIAL
        from test_official_karma_preparation import tool
        import test_native_scope as fixture
        raw={'execution_mode':ns.OFFICIAL_IDENTITY_SURVEY_MODE,'scene_profile':OFFICIAL,'schema':ns.OFFICIAL_SCOPE_SCHEMA,
             'operations':[{'id':role} for role in ns.OFFICIAL_IDENTITY_ROLES]}
        inventory=tool('prepare_controlled_engineering').native_inventory(raw)
        tool('run_alpha_calibration').validate_inventory(inventory,raw)
        with self.assertRaises(ValueError):tool('run_alpha_calibration').validate_inventory(inventory[::-1],raw)
        for extra in ({'max_dcc_starts':4},{'total_seconds':360}):
            with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
                tools={name:{'path':path,'bytes':1,'sha256':'a'*64} for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
                with self.assertRaises(ValueError):fixture.software_scope(Path(temporary).resolve(),schema=ns.OFFICIAL_SCOPE_SCHEMA,
                    resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_IDENTITY_SURVEY_MODE,
                    budget=dict(ns.OFFICIAL_IDENTITY_SURVEY_BUDGET,**extra),writer_trace_tools=tools)

    def test_first_original_failure_closes_whole_batch(self):
        from dcc_task_runtime import native_scope as ns
        from dcc_task_runtime.render_profiles import OFFICIAL
        import test_native_scope as fixture
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();tools={name:{'path':path,'bytes':1,'sha256':'a'*64} for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
            binding=fixture.software_scope(root,schema=ns.OFFICIAL_SCOPE_SCHEMA,resource_profile=ns.OFFICIAL_RESOURCE_PROFILE,
                scene_profile=OFFICIAL,execution_mode=ns.OFFICIAL_IDENTITY_SURVEY_MODE,budget=ns.OFFICIAL_IDENTITY_SURVEY_BUDGET,writer_trace_tools=tools)
            scope=ns.NativeScope(binding);ticket=scope.admit(ns.OFFICIAL_IDENTITY_ROLES[0],root/'first',{'op':'first'})
            fixture.NativeScopeTests.stop(self,ticket,code=7)
            with self.assertRaises(ValueError):scope.finish(ticket)
            with self.assertRaises(ValueError):scope.admit(ns.OFFICIAL_IDENTITY_ROLES[1],root/'second',{'op':'second'})
            self.assertEqual(scope.snapshot()['dcc_starts'],1)

    def test_driver_stops_before_second_sample_on_true_trace_error(self):
        from dcc_task_runtime import native_scope as ns,owned_process
        from houdini_bridge import official_karma_worker as worker,official_karma_observation as observation
        from test_official_karma_preparation import tool
        driver=tool('run_controlled_engineering')
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve();raw=root/'trace.json'
            raw.write_text(json.dumps({'cleanup_complete':True,'observer_errors':['explicit witness error'],
                'same_timeout_stacks_captured':[],'calls':[]}))
            binding={'path':'fixture','sha256':'a'*64}
            start={'pid':123,'writer_tool_trace':{'record':observation.file_record(raw),'cleanup_complete':True}}
            payload={'scope_binding':binding,'started_sha256':__import__('hashlib').sha256(owned_process._canonical(start)).hexdigest(),
                'captured_pid':123,'writer_tool_trace':start['writer_tool_trace'],'hip_business':'NOT_RUN'}
            scope={'execution_mode':ns.OFFICIAL_IDENTITY_SURVEY_MODE,'scope_id':'explicit-software-fixture',
                'hosts':{'hython':{'path':'/fixture/hython','sha256':'b'*64},'supervisor_python':{'path':sys.executable}}}
            budget=SimpleNamespace(native=SimpleNamespace(root=root,check=lambda:None),binding=binding,available=lambda **kw:None,
                remaining=lambda:120.,resource_budget={},fail=lambda reason:None)
            data={'scope':scope,'bindings':{'environment':{}}}
            with patch.object(worker,'check_frozen_case',return_value={'commands':{'official-open-save':['explicit-fixture-never-executed']}}), \
                 patch.object(image,'freeze_executable',return_value={}), \
                 patch.object(owned_process,'launch',return_value=SimpleNamespace(wait=lambda **kw:None)) as launched, \
                 patch.object(owned_process,'read_receipt',side_effect=lambda path,event,**kw:start if event=='started' else payload), \
                 patch.object(observation,'native_original'):
                with self.assertRaisesRegex(ValueError,'SURVEY_TRACE_INCOMPLETE'):
                    driver._official_prefix(data,None,budget,lambda name,request,fn:fn())
            self.assertEqual(launched.call_count,1)




class SurveySampleValidationTests(unittest.TestCase):
    def test_cancelled_post_ps_cannot_hide_a_complete_invalid_sample(self):
        import copy
        row={'tool_exit_code':0,'tool_diagnostic':None,'thread_joined':True,'witness_state':'INCOMPLETE',
            'reason':'ValueError:TRACE_POST_STATE_UNAVAILABLE','finished_monotonic':10.,
            'sample_identity_matches':False,'nonempty_call_graph':False,'auxiliary_tools':[
                {'argv':['/usr/bin/sample'],'spawned':True,'complete':True,'termination_reason':'RETURNED',
                 'cleanup':{'leader_reaped':True,'group_absent':True,'errors':[]}},
                {'argv':['/bin/ps'],'spawned':False,'complete':False,'termination_reason':'CANCELLED','ended_monotonic':11.,
                 'cleanup':{'leader_reaped':None,'group_absent':True,'errors':[]}}]}
        summary={'cleanup_complete':True,'observer_errors':[],'same_timeout_stacks_captured':[], 'calls':[copy.deepcopy(row) for _ in range(4)]}
        self.assertFalse(trace.survey_next_allowed(summary))
        for entry in summary['calls']:
            entry['sample_identity_matches']=True;entry['nonempty_call_graph']=True
        self.assertTrue(trace.survey_next_allowed(summary))


if __name__=='__main__':unittest.main()
