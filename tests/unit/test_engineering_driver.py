"""Driver orchestration and persisted producer readback; no native DCC execution."""
from __future__ import annotations
import importlib.util
import io
from contextlib import contextmanager
import json
import os
import queue
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(ROOT/'tests/unit'))
import run_controlled_engineering as driver


class EngineeringDriverTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()

    def test_final_engineering_acceptance_requires_actual_rgba_header(self):
        def entry(channels, width=128):
            return {'payload':{'completion_metadata':{'1':{
                'width':width,'height':128,'channels':channels}}}}
        driver._verify_engineering_images(entry(['A','B','G','R']))
        for invalid in (entry(['R','G','B']),entry(['R','G','B','A'],64),
                        entry(['R','G','B','A','A']),{'payload':{'completion_metadata':{}}}):
            with self.subTest(entry=invalid),self.assertRaisesRegex(ValueError,'ENGINEERING_(RGBA_OUTPUT|IMAGE_METADATA)_REQUIRED'):
                driver._verify_engineering_images(invalid)

    def test_controller_logs_bounded_json_digest_without_truncating_business_reply(self):
        controller=driver.Controller.__new__(driver.Controller)
        controller.lines=queue.Queue();controller.log_bytes=0;controller.error=None
        controller.log_lock=threading.Lock();controller.log=self.root/'controller.log'
        original=json.dumps({'jsonrpc':'2.0','id':7,'result':{'scene':'x'*(2*1024*1024)}})+'\n'
        controller._read(io.StringIO(original),True)
        self.assertIsNone(controller.error)
        self.assertEqual(controller.lines.get_nowait(),original)
        self.assertIsNone(controller.lines.get_nowait())
        summary=json.loads(controller.log.read_text())
        self.assertEqual(summary['bytes'],len(original.encode()))
        self.assertEqual(summary['sha256'],driver.hashlib.sha256(original.encode()).hexdigest())
        self.assertEqual(summary['id'],7)
        self.assertLess(controller.log_bytes,1024)
        controller._read(io.StringIO('stderr failure'+('x'*(1024*1024))),False)
        self.assertEqual(controller.error,'ENGINEERING_CONTROLLER_LOG_BUDGET')
        self.assertLess(controller.log.stat().st_size,1024)

    def test_frozen_preflight_and_execution_gate_without_native_start(self):
        from test_engineering_preparation import EngineeringPreparationTests
        fixture=EngineeringPreparationTests('test_complete_snapshot_preparation_and_repeat_preserve_all_frozen_bytes')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        result=fixture.prepare()
        bindings_path=Path(result['bindings']['path'])
        bindings=json.loads(bindings_path.read_text())
        entry=Path(result['snapshot_root'])/'tools/run_controlled_engineering.py'
        completed=subprocess.run([sys.executable,'-I',str(entry),'--scope',str(fixture.scope_path),
            '--bindings',str(bindings_path)],capture_output=True,text=True,timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['native_execution_status'],'NOT_RUN')
        self.assertFalse(list(Path(result['snapshot_root']).rglob('*.pyc')))
        spec=importlib.util.spec_from_file_location('software_frozen_driver',entry)
        frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)
        with self.assertRaisesRegex(ValueError,'EXPLICIT_REAL_HOST_AUTHORIZATION_REQUIRED'):
            frozen.execute(fixture.scope_path,bindings_path,approved_scope_sha256=fixture.binding['sha256'],
                           approved_bindings_sha256=result['bindings']['sha256'])
        bindings['outputs']['nuke_pattern']=str(fixture.root/'outside.%04d.exr')
        bindings_path.write_text(json.dumps(bindings))
        report,_=frozen.preflight(fixture.scope_path,bindings_path)
        self.assertEqual(report['state'],'BLOCKED')
        self.assertIn('ENGINEERING_FROZEN_PLAN_INVALID',report['blockers'])
        self.assertEqual(fixture.native.snapshot()['dcc_starts'],0)

    def test_fresh_protocol_order_and_exact_frozen_requests(self):
        """Transport protocol unit test; final native authority is a separate boundary."""
        control=self.root/'project/control';control.mkdir(parents=True)
        (control/'production-hosts.json').write_text(json.dumps({'hosts':{'houdini':{'software_protocol':True}}}))
        phase_budget=self.enterContext(mock.patch('vfx_pipeline.production_hosts.host_phase_budget',return_value=43.0))
        asset=control/'reference.png'
        asset.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+struct.pack('>II',128,128))
        data={'scope':{},'root':self.root,'project':control.parent,'control':control,
              'scope_path':self.root/'scope.json','bindings_path':self.root/'bindings.json',
              'scope_sha256':'a'*64,'bindings_sha256':'b'*64,
              'outputs':{'houdini_pattern':str(control.parent/'saves/main.%04d.exr'),
                         'nuke_pattern':str(control.parent/'saves/nuke.%04d.exr'),
                         'nuke_script':str(control.parent/'saves/composite.nk')},
              'manifest':{'assets':[{'asset_id':'ref','file':'reference.png',
                 'sha256':driver._alpha_module().file_record(asset)['sha256']}]}}
        events=[];instances=[];pending_nuke=False
        class ProtocolController:
            def __init__(self,data,budget):
                self.budget=budget;self.index=len(instances);instances.append(self);events.append(('controller',self.index))
            def tool(self,name,args):
                events.append((name,args))
                if name=='catalog':return {'assets':[{'asset_id':'ref'}]}
                if name=='submit_observation':
                    self_observation=args['observation']['description']
                    assert 'metadata_only; no visual/model analysis' in self_observation
                    assert 'PNG=128x128' in self_observation
                    return {'accepted':True}
                if name=='graph_propose':
                    assert args['proposal']=={'schema':'bridge.registered-domain-construction/1',
                        'domain_pack':'material_lookdev_v1','houdini_version':'21.0.631','scene_profile':'sphere_ground_v2'}
                    return {'graph_id':'graph-1'}
                if name=='graph_trial':
                    if sum(1 for key,_ in events if key=='graph_trial')==1:
                        return {'operation_id':'build-1','state':'RUNNING'}
                    return {'operation_id':'build-1','state':'SUCCEEDED',
                            'host_binding':{'graph_binding':{'graph_ready':True}}}
                if name=='graph_status':return {'operation_id':'build-1','state':'SUCCEEDED'}
                if name=='task_save':return {'saved_scene_id':'saved-1','scene_contract':{
                    'nodes':[{'role':'render','path':'/stage/task/render'}],
                    'frozen_scene_parameters':{'profile':'sphere_ground_v2'}}}
                if name=='task_reopen':return {'opened':True}
                if name=='houdini_render_bounded':
                    assert args=={'request_id':'engineering_h21_render','saved_scene_id':'saved-1',
                        'render_target':'/stage/task/render','pattern':data['outputs']['houdini_pattern'],
                        'frames':[1],'budget_seconds':43.0}
                    return {'operation_id':'render-1','state':'RUNNING'}
                if name=='operation_query':return {'kind':'nuke-render' if args['operation_id']=='nuke-1' else 'houdini-render',
                    'operation':({'state':'NEEDS_RECONCILE','ledger_state':'PENDING'}
                        if pending_nuke and args['operation_id']=='nuke-1' else {'state':'COMPLETED'})}
                if name=='consume_artifact':return {'artifact_id':'engineering_h21_main','usable_as_render_input':True}
                if name=='nuke_render_bounded':
                    assert args=={'request_id':'engineering_h21_nuke','artifact_id':'engineering_h21_main',
                                  'pattern':data['outputs']['nuke_pattern'],'frames':[1]}
                    return {'operation_id':'nuke-1','artifact_id':'nuke-render-nuke-1','state':'RUNNING'}
                raise AssertionError(name)
            def close(self):events.append(('close',self.index))
        budget=types.SimpleNamespace(remaining=lambda:600,fail=mock.Mock(side_effect=AssertionError('ledger outage must not close scope')))
        alpha=driver._alpha_module()
        modules={'run_alpha_calibration':types.SimpleNamespace(execute=lambda *a,**k:{'evidence_source':'software_test'}),
                 'verify_controlled_output':types.SimpleNamespace(resume=lambda *a,**k:events.append(('verify',k)) or {'software_protocol':True}),
                 'prepare_nuke_project':types.SimpleNamespace(prepare_nuke_project=lambda *a,**k:events.append(('nuke_prepare',k)) or {'software_protocol':True})}
        # Native subprocess/authority adapters are bounded substitutes here;
        # the driver itself, stage persistence, metadata reading and polling run.
        original_tool_module=driver.tool_module
        modules['run_alpha_calibration'].file_record=alpha.file_record
        modules['run_alpha_calibration'].load=alpha.load
        journal=driver.StageJournal(self.root/'stages.json','a'*64,'b'*64)
        with mock.patch.object(driver,'Controller',ProtocolController), \
             mock.patch.object(driver,'tool_module',side_effect=lambda n:modules.get(n) or original_tool_module(n)), \
             mock.patch.object(driver,'_stop_host',side_effect=lambda d,k:events.append(('stop',k)) or {'stopped':True}), \
             mock.patch.object(driver,'_final_result',return_value={'state':'SOFTWARE_PROTOCOL_CHECKED','evidence_source':'software_test'}) as final:
            result=driver._fresh(data,journal,budget)
        self.assertEqual(result['evidence_source'],'software_test')
        final.assert_called_once_with(data,journal,budget)
        self.assertEqual([v for k,v in events if k=='stop'],['houdini','houdini','nuke'])
        self.assertEqual([v for k,v in events if k=='controller'],[0,1])
        self.assertEqual([v for k,v in events if k=='graph_trial'],[
            {'graph_id':'graph-1','request_id':'engineering_h21_build'}]*2)
        keys=[key for key,_ in events]
        self.assertLess(keys.index('verify'),keys.index('nuke_prepare'))
        self.assertLess(keys.index('nuke_prepare'),keys.index('nuke_render_bounded'))
        self.assertEqual(journal.result('nuke_render')['operation_id'],'nuke-1')
        self.assertEqual(journal.result('complete')['state'],'SOFTWARE_PROTOCOL_CHECKED')
        phase_budget.assert_called_once_with({'software_protocol':True},requested_seconds=120.)
        for phase in ('houdini','nuke'):
            events.clear();instances.clear();pending_nuke=phase=='nuke'
            outage=driver.StageJournal(self.root/(phase+'-outage.json'),'a'*64,'b'*64)
            modules['verify_controlled_output'].resume=(mock.Mock(side_effect=OSError('ledger unavailable'))
                if phase=='houdini' else lambda *a,**k:{'software_protocol':True})
            with mock.patch.object(driver,'Controller',ProtocolController), \
                 mock.patch.object(driver,'tool_module',side_effect=lambda n:modules.get(n) or original_tool_module(n)), \
                 mock.patch.object(driver,'_stop_host',side_effect=lambda d,k:events.append(('stop',k)) or {'stopped':True}), \
                 mock.patch.object(driver,'_houdini_original',return_value={'state':'COMPLETED','stop_confirmed':True}), \
                 mock.patch.object(driver,'_nuke_original',return_value={'execution_fact':{'ledger_state':'PENDING'},'stop_confirmed':True}), \
                 mock.patch.object(driver,'_final_result',side_effect=AssertionError('pending is not complete')):
                pending=driver._fresh(data,outage,budget)
            self.assertEqual(pending['state'],'REGISTRATION_PENDING')
            self.assertEqual(pending['phase'],phase)
            self.assertEqual([v for k,v in events if k=='stop'],['houdini','houdini'])
            budget.fail.assert_not_called()
            if phase=='houdini':
                modules['verify_controlled_output'].resume=lambda *a,**k:{'software_protocol':True}
                with mock.patch.object(driver,'tool_module',side_effect=lambda n:modules.get(n) or original_tool_module(n)), \
                     mock.patch.object(driver,'Controller',side_effect=AssertionError('no new native continuation')):
                    recovered=driver._resume(data,outage,budget)
                self.assertEqual(recovered['reason'],'NEXT_UNSTARTED_NUKE_TAIL_REQUIRES_CONTINUATION')
                self.assertEqual(outage.result('verify'),{'software_protocol':True})
                self.assertNotIn('registration_pending',outage.value)
        # An invalid/missing controlled verification is a real failure even
        # when a raw producer happened to stop successfully.
        events.clear();instances.clear();pending_nuke=False
        invalid=driver.StageJournal(self.root/'invalid-verification.json','a'*64,'b'*64)
        modules['verify_controlled_output'].resume=mock.Mock(side_effect=ValueError('invalid alpha/output verification'))
        with mock.patch.object(driver,'Controller',ProtocolController), \
             mock.patch.object(driver,'tool_module',side_effect=lambda n:modules.get(n) or original_tool_module(n)), \
             mock.patch.object(driver,'_stop_host',return_value={'stopped':True}), \
             mock.patch.object(driver,'_houdini_original',side_effect=ValueError('no persisted verified original')):
            with self.assertRaisesRegex(ValueError,'invalid alpha/output verification'):
                driver._fresh(data,invalid,budget)
        budget.fail.assert_called_once_with('ENGINEERING_DRIVER_FAILED')
        self.assertNotIn('registration_pending',invalid.value)

    def test_interrupted_intent_does_not_replay_and_hash_binding_is_enforced(self):
        journal=driver.StageJournal(self.root/'stages.json','a'*64,'b'*64)
        journal.intent('render',{'request_id':'engineering_h21_render'})
        resumed=driver.StageJournal(journal.path,'a'*64,'b'*64)
        with mock.patch.object(driver,'Controller',side_effect=AssertionError('no controller restart')), \
             mock.patch.object(driver,'_stop_host',side_effect=AssertionError('unknown operation stays held')):
            result=driver._resume({},resumed,None)
        self.assertEqual(result['state'],'QUERY_REQUIRED')
        with self.assertRaisesRegex(ValueError,'QUERY_REQUIRED'):resumed.intent('render',{})
        with self.assertRaisesRegex(ValueError,'BINDING_CHANGED'):
            driver.StageJournal(journal.path,'c'*64,'b'*64)
        report={'state':'PREPARED','scope_sha256':'a'*64,'bindings_sha256':'b'*64,'blockers':[]}
        data={'root':self.root,'snapshot':driver.ROOT,'scope':{'execution_authorized':True,
            'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION','evidence_source':'real_host'},'bindings':{'evidence_source':'real_host'}}
        @contextmanager
        def contended_lock(path,owner):
            other=driver.StageJournal(path,'a'*64,'b'*64)
            other.intent('complete',{});other.done('complete',{'state':'already-completed'})
            yield
        def inspect_resume(data,current,budget):
            self.assertEqual(current.result('complete')['state'],'already-completed')
            return {'state':'QUERY_REQUIRED'}
        activation=types.SimpleNamespace(validate_activation=mock.Mock(return_value={'authorization':'explicit_local_terminal_controller'}))
        with mock.patch.object(driver,'preflight',return_value=(report,data)), \
             mock.patch.object(driver,'_alpha_module',return_value=types.SimpleNamespace(ScopeBudget=lambda *a:types.SimpleNamespace(native=object()),load=json.loads)), \
             mock.patch.object(driver,'tool_module',return_value=activation), \
             mock.patch('dcc_task_runtime.native_scope.NativeScope',return_value=object()), \
             mock.patch('dcc_task_runtime.execution_lock.execution_lock',side_effect=contended_lock), \
             mock.patch.object(driver,'load',side_effect=lambda path:json.loads(Path(path).read_text())), \
             mock.patch.object(driver,'_resume',side_effect=inspect_resume) as resume, \
             mock.patch.object(driver,'_fresh',side_effect=AssertionError('completed call must not replay')):
            driver.execute(self.root/'scope.json',self.root/'bindings.json',
                approved_scope_sha256='a'*64,approved_bindings_sha256='b'*64)
        resume.assert_called_once()
        self.assertEqual(activation.validate_activation.call_count,2)
        activation.validate_activation.side_effect=ValueError('ENGINEERING_ACTIVATION_RECEIPT_MISMATCH')
        with mock.patch.object(driver,'preflight',return_value=(report,data)), \
             mock.patch.object(driver,'_alpha_module',return_value=types.SimpleNamespace(ScopeBudget=lambda *a:types.SimpleNamespace(native=object()))), \
             mock.patch.object(driver,'tool_module',return_value=activation), \
             mock.patch('dcc_task_runtime.native_scope.NativeScope',return_value=object()), \
             mock.patch.object(driver,'StageJournal',side_effect=AssertionError('invalid activation cannot access stages')):
            with self.assertRaisesRegex(ValueError,'ACTIVATION_RECEIPT_MISMATCH'):
                driver.execute(self.root/'scope.json',self.root/'bindings.json',
                    approved_scope_sha256='a'*64,approved_bindings_sha256='b'*64)
        activation.validate_activation.side_effect=None
        activation.validate_activation.return_value={'authorization':'explicit_software_test_controller'}
        with mock.patch.object(driver,'preflight',return_value=(report,data)), \
             mock.patch.object(driver,'tool_module',return_value=activation), \
             mock.patch('dcc_task_runtime.native_scope.NativeScope',return_value=object()), \
             mock.patch.object(driver,'_alpha_module',side_effect=AssertionError('must reject before budget construction')):
            with self.assertRaisesRegex(ValueError,'EXPLICIT_LOCAL_ACTIVATION_REQUIRED'):
                driver.execute(self.root/'scope.json',self.root/'bindings.json',
                    approved_scope_sha256='a'*64,approved_bindings_sha256='b'*64)

    def test_original_nuke_record_uses_formal_host_runtime_path(self):
        from test_nuke_render_persistence import NukeRenderPersistenceTests
        fixture=NukeRenderPersistenceTests('test_typed_completed_operation_uses_real_source_ledger_and_fails_closed')
        self.enterContext(mock.patch.object(tempfile,'tempdir','/private/tmp'))
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        control=fixture.tmp/'project/control';control.mkdir(parents=True)
        fixture.addon._RENDER_RECORDS_DIR=fixture.tmp/'state/nuke_renders'
        sys.modules['nuke'].execute=lambda write,first,last:fixture._write_fresh_frames(range(first,last+1))
        result=fixture.addon.dispatch('render_write',{'node':'Write1','background':False,
            'frame_set':[1],'request_id':'driver-production-path'})
        original=fixture.addon._nuke_operation_fact(result['task_id'])
        (control/'production-hosts.json').write_text(json.dumps({'task_id':original['task_id'],
            'hosts':{'nuke':{'task_root':str(fixture.tmp),
                            'render_records_root':str(fixture.tmp/'state/nuke_renders')}}}))
        data={'root':fixture.tmp,'control':control,'outputs':{'nuke_pattern':fixture.pattern}}
        loaded=driver._nuke_original(data,result['task_id'])
        self.assertEqual(loaded['completion_metadata_status'],'AVAILABLE')
        self.assertEqual(loaded['formal_receipt'],original['formal_receipt'])
        Path(fixture.pattern%1).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'ORIGINAL_REQUIRED'):
            driver._nuke_original(data,result['task_id'])
        # An actual fixed Python worker produces signed stopped evidence.
        # Its completed output remains registrable after the host is gone.
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        from dcc_task_runtime import owned_process
        source=str(fixture.tmp/'worker-input.%03d.exr')
        Path(source%1).write_bytes(encode_tiny_exr(.25))
        def save_snapshot():
            (fixture.tmp/'script.nk').write_text(json.dumps({'schema':'bridge.software_nuke_snapshot/1',
                'root':{'first_frame':1,'last_frame':1},'nodes':{
                    'Read1':{'class':'Read','file':source,'inputs':[]},
                    'Write1':{'class':'Write','file':fixture.pattern,'inputs':['Read1'],
                        'knobs':{'colorspace':'linear','premultiplied':True,'raw':False}}}}))
        sys.modules['nuke'].scriptSave=save_snapshot
        handles=[]
        def launch(task_id,script,node,first,last):
            identity=fixture.addon._launch_owned_render_subprocess(task_id,script,node,first,last,
                pattern=fixture.pattern,frame_set=[1],route={'executable':sys.executable,
                    'supervisor_executable':sys.executable,'software_api':True,
                    'worker_script':str(ROOT/'packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py')})
            handles.append(identity['handle']);return identity
        with mock.patch.object(fixture.addon,'_NUKE_BACKGROUND_LAUNCHER',side_effect=launch):
            submitted=fixture.addon.dispatch('render_write',{'node':'Write1','background':True,
                'frame_set':[1],'request_id':driver.PREFIX+'_nuke'})
        self.addCleanup(lambda:[(handle.terminate(),handle.wait(timeout=10)) for handle in handles if handle.poll() is None])
        self.assertEqual(handles[0].wait(timeout=15),0)
        with mock.patch.object(fixture.addon,'_register_render_artifact',side_effect=OSError('ledger temporarily unavailable')):
            pending=fixture.addon.dispatch('render_status',{'task_id':submitted['task_id']})
        self.assertEqual(pending['state'],'NEEDS_RECONCILE')
        pending_id=submitted['task_id']
        pending_fact=driver._nuke_original(data,pending_id)
        self.assertEqual(pending_fact['execution_fact']['ledger_state'],'PENDING')
        self.assertEqual(pending_fact['execution_kind'],'owned_subprocess')
        self.assertEqual(owned_process.execution_returncode(handles[0].receipt()),0)
        client=types.SimpleNamespace(bind_task=lambda task:None,call=mock.Mock(side_effect=AssertionError('host transport is offline')),
            _load_operation_owners=lambda:{pending_id:original['task_id']})
        journal=driver.StageJournal(self.root/'recovery.json','a'*64,'b'*64)
        journal.intent('nuke_render',{'request_id':driver.PREFIX+'_nuke'})
        journal.intent('nuke_stop',{});journal.done('nuke_stop',{'stopped':True})
        with mock.patch('vfx_pipeline.workbuddy_assembly.production_nuke_client',return_value=client), \
             mock.patch.object(owned_process,'launch',side_effect=AssertionError('registration must not start any process')), \
             mock.patch.object(driver,'_final_result',return_value={'state':'SOFTWARE_PROTOCOL_CHECKED'}), \
             mock.patch.object(driver,'Controller',side_effect=AssertionError('recovery must not launch')), \
             mock.patch.object(driver,'_stop_host',side_effect=AssertionError('already stopped')):
            recovered=driver._resume(data,journal,None)
        self.assertTrue(recovered['revalidated'])
        client.call.assert_not_called()
        self.assertEqual(driver._nuke_original(data,pending_id)['execution_fact']['ledger_state'],'REGISTERED')
        self.assertEqual(driver._nuke_original(data,pending_id)['formal_receipt']['execution_fact']['worker_receipt']['execute_calls'],[1])
        self.assertEqual(len(handles),1)
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        self.assertIsNotNone(ArtifactRegistry(control/'artifact_ledger').lookup('nuke-render-'+pending_id))

    def test_explicit_continuation_dispatches_only_unstarted_tail_and_rejects_input_drift(self):
        """Orchestration unit; native authorities are exercised by separate fixtures."""
        control=self.root/'project/control';control.mkdir(parents=True)
        artifact={'artifact_id':driver.PREFIX+'_main','version':1,'operation_id':driver.PREFIX+'_verify',
            'operation_receipt_sha256':'c'*64,'payload':{'completion_snapshot':{'1':{'sha256':'d'*64}}}}
        verification={'artifact':artifact}
        data={'scope':{},'root':self.root,'project':control.parent,'control':control,'scope':{},'bindings':{},
              'scope_sha256':'a'*64,'bindings_sha256':'b'*64,
              'outputs':{'nuke_script':str(control.parent/'saves/composite.nk'),
                         'nuke_pattern':str(control.parent/'saves/nuke.%04d.exr')}}
        def stopped_h_journal(name):
            journal=driver.StageJournal(self.root/name,'a'*64,'b'*64)
            for key,result in [('render',{'operation_id':'h-render'}),('houdini_reopen_stop',{'stopped':True}),
                               ('verify',verification)]:
                journal.intent(key,{});journal.done(key,result)
            return journal
        events=[]
        class NukeServices:
            def __init__(self,data,budget):self.budget=budget;events.append('attach_existing')
            def tool(self,name,args):
                events.append(name)
                if name=='consume_artifact':return {'usable_as_render_input':True}
                if name=='nuke_render_bounded':
                    assert args=={'request_id':driver.PREFIX+'_nuke','artifact_id':driver.PREFIX+'_main',
                        'pattern':data['outputs']['nuke_pattern'],'frames':[1]}
                    return {'operation_id':'nuke-first-tail'}
                if name=='operation_query':return {'operation':{'state':'COMPLETED'}}
                raise AssertionError(name)
            def close(self):events.append('close')
        budget=types.SimpleNamespace(remaining=lambda:120)
        helper=types.SimpleNamespace(prepare_nuke_project=mock.Mock(return_value={'software_protocol':True}))
        current=mock.Mock(return_value=verification)
        with mock.patch.object(driver,'_alpha_original',return_value={'software_protocol':True}), \
             mock.patch.object(driver,'_verify_registered',current), \
             mock.patch.object(driver,'_tail_admission',return_value={'identity':'unchanged'}), \
             mock.patch.object(driver,'tool_module',return_value=helper), \
             mock.patch.object(driver,'ExistingNukeController',NukeServices), \
             mock.patch.object(driver,'Controller',side_effect=AssertionError('no controller or Houdini restart')), \
             mock.patch.object(driver,'_nuke_original',return_value={'execution_fact':{'ledger_state':'REGISTERED'}}), \
             mock.patch.object(driver,'_stop_host',return_value={'stopped':True}), \
             mock.patch.object(driver,'_final_result',return_value={'state':'SOFTWARE_PROTOCOL_CHECKED','evidence_source':'software_test'}):
            journal=stopped_h_journal('tail.json')
            journal.intent('nuke_prepare',{'script':data['outputs']['nuke_script']})
            self.assertEqual(driver._resume(data,journal,budget)['state'],'QUERY_REQUIRED')
            self.assertEqual(events,[])
            with mock.patch.object(driver,'_tail_admission',return_value=None):
                unresolved=driver._resume(data,journal,budget,continue_nuke_tail=True)
                self.assertEqual(unresolved['reason'],'ENGINEERING_NUKE_SAVE_RECONCILE_HOST_REQUIRED')
            helper.prepare_nuke_project.assert_not_called()
            helper.prepare_nuke_project.side_effect=ValueError('ENGINEERING_NUKE_SAVE_RECONCILE_UNRESOLVED')
            unresolved=driver._resume(data,journal,budget,continue_nuke_tail=True)
            self.assertEqual(unresolved['state'],'QUERY_REQUIRED')
            self.assertTrue(helper.prepare_nuke_project.call_args.kwargs['reconcile_saved'])
            self.assertEqual(journal.value['stages']['nuke_prepare']['state'],'INTENT')
            self.assertEqual(events,[])
            helper.prepare_nuke_project.side_effect=None
            completed=driver._resume(data,journal,budget,continue_nuke_tail=True)
            self.assertEqual(completed['evidence_source'],'software_test')
            driver._resume(data,journal,budget,continue_nuke_tail=True)
            self.assertEqual(events.count('nuke_render_bounded'),1)
            self.assertEqual(helper.prepare_nuke_project.call_count,2)
            self.assertTrue(all(call.kwargs['reconcile_saved'] for call in helper.prepare_nuke_project.call_args_list))
            drift=stopped_h_journal('drift.json')
            current.return_value={'artifact':dict(artifact,version=2)}
            with self.assertRaisesRegex(ValueError,'CONTINUATION_INPUT_CHANGED'):
                driver._resume(data,drift,budget,continue_nuke_tail=True)
            self.assertEqual(events.count('nuke_render_bounded'),1)
        unresolved=stopped_h_journal('unknown-intent.json')
        unresolved.intent('nuke_render',{'request_id':driver.PREFIX+'_nuke'})
        (control/'production-hosts.json').write_text(json.dumps({'task_id':'owner','hosts':{'nuke':{}}}))
        client=types.SimpleNamespace(bind_task=lambda task:None,_load_operation_owners=lambda:{})
        with mock.patch('vfx_pipeline.workbuddy_assembly.production_nuke_client',return_value=client), \
             mock.patch.object(driver,'_nuke_addon',return_value=object()), \
             mock.patch.object(driver,'ExistingNukeController',side_effect=AssertionError('unknown intent never dispatches')):
            self.assertEqual(driver._resume(data,unresolved,budget,continue_nuke_tail=True)['state'],'QUERY_REQUIRED')

    def test_continuation_admission_uses_authenticated_tickets_and_existing_python_host(self):
        from test_native_scope import software_scope,NativeScopeTests
        from dcc_task_runtime.native_scope import NativeScope
        from dcc_task_runtime import owned_process
        binding=software_scope(self.root)
        scope=NativeScope(binding)
        def stopped(role,index,heavy=True):
            ticket=scope.admit(role,self.root/('prior-'+str(index)),{'op':str(index)},heavy=heavy)
            NativeScopeTests.stop(self,ticket);scope.finish(ticket)
            return ticket
        stopped('alpha-husk',1);stopped('alpha-nuke',2);stopped('graph-worker',3)
        stopped('houdini-host',4,False)
        h=scope.admit('houdini-host',self.root/'prior-5',{'op':'5'},heavy=False)
        scope.admit('main-husk',h['directory'],h['identity'],parent=h)
        NativeScopeTests.stop(self,h);scope.finish(h)
        budget=driver._alpha_module().ScopeBudget(binding['path'])
        control=self.root/'project/control';control.mkdir(parents=True)
        data={'scope':scope.scope,'control':control,'scope_path':Path(binding['path']),'scope_sha256':binding['sha256']}
        saved={'task_id':'software-owner','hosts':{}}
        (control/'production-hosts.json').write_text(json.dumps(saved))
        self.assertIsNone(driver._tail_admission(data,budget))
        work=self.root/'nuke-host-existing';work.mkdir()
        stop_file=work/'exit'
        identity={'task_id':'software-owner','session_id':'fixture-session','launch_nonce':'fixture-nonce',
                  'process_generation':1,'plugin_build':'fixture-build'}
        child="from pathlib import Path\nimport sys,time\np=Path(sys.argv[1])\nwhile not p.exists():time.sleep(.01)\n"
        handle=owned_process.launch([sys.executable,'-c',child,str(stop_file)],directory=work/'supervisor',
            identity=identity,supervisor_executable=sys.executable,budget_seconds=30,
            resource_budget=budget.resource_budget,scope_role='nuke-host',scope_heavy=False)
        def cleanup():
            stop_file.touch();handle.wait(timeout=10)
        self.addCleanup(cleanup)
        (work/'launch.json').write_text(json.dumps({'identity':identity}))
        config={'work_dir':str(work),'native_scope':binding,'expected_identity':dict(identity,pid=handle.pid)}
        saved['hosts']['nuke']=config
        (control/'production-hosts.json').write_text(json.dumps(saved))
        client=types.SimpleNamespace(bind_task=lambda task:None,health=lambda:{'task_host_identity':config['expected_identity']})
        with mock.patch('vfx_pipeline.workbuddy_assembly.production_nuke_client',return_value=client):
            admitted=driver._tail_admission(data,budget,require_nuke=True)
            self.assertEqual(admitted['identity'],identity)
            config['expected_identity']['launch_nonce']='different'
            (control/'production-hosts.json').write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,'HOST_TICKET_MISMATCH'):
                driver._tail_admission(data,budget,require_nuke=True)
            config['expected_identity']['launch_nonce']=identity['launch_nonce']
            (control/'production-hosts.json').write_text(json.dumps(saved))
            stop_file.touch();self.assertEqual(handle.wait(timeout=10),0)
            with self.assertRaisesRegex(ValueError,'HOST_STOPPED_NO_RESTART'):
                driver._tail_admission(data,budget,require_nuke=True)


if __name__=='__main__':unittest.main()
