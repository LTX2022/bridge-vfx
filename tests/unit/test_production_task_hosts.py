from __future__ import annotations
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_workbuddy_graph import prepare_graph
from vfx_pipeline.production_hosts import ensure_hosts,stop_hosts,validate_deployments
from vfx_pipeline import production_hosts
from vfx_pipeline.domain_readiness import DomainReadinessRunner
from vfx_pipeline.workbuddy_assembly import production_host_client, production_nuke_client
from test_nuke_task_host import FAKE
from test_c3_formal_entry import PROPOSAL
from software_host_bootstrap import HYTHON, SOFTWARE_PYTHON

STRICT_RENDER_NATIVE = '''import importlib.util,json,time,hashlib
native_root=Path(os.environ['BRIDGE_TEST_NATIVE_ROOT'])
def injected_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
native=injected_module('injected_native_schema',native_root/'tools/native_schema_test_boundary.py')
api=injected_module('injected_stage_api',native_root/'tools/software_render_api_boundary.py')
agent_api=injected_module('injected_agent_api',native_root/'tools/software_agent_api_boundary.py')
version=os.environ.get('BRIDGE_TEST_NATIVE_VERSION','21.0.631')
interfaces,states,ports=api.interface_profiles(native_root,version)
native.constrain_hou(native_root/'docs/native-basis/hda-interface-capture.json',version,
    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
hou=sys.modules['hou']
hou._software_agent_api_state={'origin':'test_injected_native_api','clip_sample_rate':30.7,'clip_start_time':12.5}
agent_api.install_agent_api(hou);api.install_stage_api(hou)
hou.expandString=lambda value:os.path.expandvars(value)
Node=type(hou.node('/obj'))
def native_render(self,frame_range=(),res=(),output_file=None,output_format=None,to_flipbook=False,quality=2,ignore_inputs=False,**kwargs):
    assert frame_range[0]==frame_range[1] and frame_range[2]==1
    assert output_format=='exr' and ignore_inputs and not to_flipbook
    path=Path(output_file)
    log=runner.parent/'native-render-calls.jsonl'
    with log.open('a') as stream:stream.write(json.dumps({'frame':frame_range[0],'path':str(path),'pid':os.getpid(),'hip_path':hou.hipFile.path(),'hip_sha256':hashlib.sha256(Path(hou.hipFile.path()).read_bytes()).hexdigest()})+'\\n')
    if 'slow.' in path.name:time.sleep(30)
    path.write_bytes(Path(os.environ['BRIDGE_TEST_EXR_FIXTURE'] % int(frame_range[0])).read_bytes())
    api.execute_postframe_hook(self,hou,int(frame_range[0]))
Node.render=native_render
'''

RENDER_SEAL_PUBLICATION_AUDIT = '''
from houdini_bridge.client import render_producer_binding, _render_terminal_event
from dcc_task_runtime.owned_process import read_receipt
original_operation_save=addon.OperationRunner._save
def observed_terminal_save(self,store):
    for record in (store.get('operations') or {}).values():
        if record.get('kind')!='render':continue
        state=record.get('state')
        sealing=record.get('stage')=='render_terminal_sealing'
        if state!='COMPLETED' and not sealing:continue
        if state=='COMPLETED':
            producer=render_producer_binding(record);binding=producer['supervisor_binding']
            receipt=read_receipt(binding['directory'],_render_terminal_event(producer),identity=binding['identity'])
            assert receipt is not None and receipt['execution_fact']==record['execution_fact'], 'unsealed completion was published'
        else:
            assert state=='RUNNING' and not record.get('execution_fact') and not record.get('lifecycle_fact')
        with (runner.parent/'terminal-publications.jsonl').open('a') as stream:
            stream.write(json.dumps({'operation':record['request_id'],'state':state,'used_bytes':record['ocio_read_budget']['used_bytes']})+'\\n')
    return original_operation_save(self,store)
addon.OperationRunner._save=observed_terminal_save
'''

MATERIAL_REOPEN_READBACK = '''
material_probe=Path(os.environ['BRIDGE_TEST_MATERIAL_REOPEN_PROBE'])
def record_material_readback(phase):
    if not material_probe.is_file():return
    request=json.loads(material_probe.read_text(encoding='utf-8'))
    domain,pack=addon._fx_pack(request['params'])
    roles=request['roles']
    observed=addon._fx_static_domain_readback(domain,roles,pack)
    binding=observed['usd_binding_readback']
    terminal=hou.node(roles['settings_binding'])
    stage=terminal.stage(frame=hou.frame(),apply_viewport_overrides=False,ignore_errors=False)
    targets=[str(path) for path in stage.GetPrimAtPath(binding['geometry_prefix']).GetRelationship('material:binding').GetTargets()]
    config=addon._fx_render_configuration(hou.node(roles['render']),[1,2])
    record={'phase':phase,'pid':os.getpid(),'final_lop_path':terminal.path(),
        'native_static_readback':observed,'material_binding_targets':targets,'render_configuration':config}
    with material_probe.with_suffix('.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(record,sort_keys=True)+'\\n')
def trace_material_hip_boundary(method,phase):
    original=getattr(hou.hipFile,method)
    def traced(*args,**kwargs):
        result=original(*args,**kwargs)
        record_material_readback(phase)
        return result
    setattr(hou.hipFile,method,traced)
trace_material_hip_boundary('save','saved')
trace_material_hip_boundary('load','reopened')
'''

class ProductionTaskHostsTests(unittest.TestCase):
    def test_houdini_wrong_version_is_reclaimed_before_deployment_and_retry(self):
        from dcc_task_runtime.owned_process import OwnedProcessHandle
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            native=HYTHON.replace("sys.modules['houdini_bridge_addon']=addon", 
                "sys.modules['houdini_bridge_addon']=addon\nsys.modules['hou'].applicationVersionString=lambda:os.environ.get('BRIDGE_TEST_ACTUAL_HOST_VERSION','21.0.631')")
            hython=root/'fake-hython.py';hython.write_text(native,encoding='utf-8')
            h=self.config(root,'houdini',hython,api);h['version']='22.0.459'
            n=self.config(root,'nuke',SOFTWARE_PYTHON,api)
            kwargs=dict(task_id='version-task',controller_root=root/'control',repo_root=ROOT,
                        scheduler_root=root/'scheduler',allow_software_processes=True)
            work=root/'control/houdini-task-host'
            with mock.patch.dict(os.environ,{'BRIDGE_TEST_ACTUAL_HOST_VERSION':'21.0.631'}):
                with self.assertRaisesRegex(ValueError,'DEPLOYMENT_IDENTITY_MISMATCH_STOP_CONFIRMED'):
                    ensure_hosts(h,n,**kwargs)
            state=json.loads((root/'control/production-hosts.json').read_text())
            self.assertNotIn('houdini',state['hosts']);self.assertFalse((work/'host.ready').exists())
            binding=json.loads((work/'supervisor-binding.json').read_text())
            rejected=OwnedProcessHandle(binding['directory'],binding['identity'])
            self.assertIsNotNone(rejected.poll());self.assertIsNotNone(rejected.receipt())
            with mock.patch.dict(os.environ,{'BRIDGE_TEST_ACTUAL_HOST_VERSION':'22.0.459'}):
                try:
                    accepted=ensure_hosts(h,n,**kwargs)
                    self.assertEqual(accepted[0]['expected_identity']['version'],'22.0.459')
                    self.assertNotEqual(accepted[0]['expected_identity']['launch_nonce'],binding['identity']['launch_nonce'])
                    self.assertEqual(ensure_hosts(h,n,**kwargs),accepted)
                    from houdini_bridge.client import HoudiniClient
                    original_health=HoudiniClient.health;remove_ready=production_hosts.remove_owned_path
                    def changed_health(client):
                        observed=original_health(client)
                        return {**observed,'task_host_identity':{**observed['task_host_identity'],'version':'22.0.429'}}
                    def after_stop_commit(path,**options):
                        if Path(path)==work/'host.ready':raise RuntimeError('after confirmed stop commit')
                        return remove_ready(path,**options)
                    with mock.patch.object(HoudiniClient,'health',new=changed_health), \
                         mock.patch.object(production_hosts,'remove_owned_path',side_effect=after_stop_commit):
                        with self.assertRaisesRegex(RuntimeError,'after confirmed stop commit'):
                            ensure_hosts(h,n,**kwargs)
                    self.assertNotIn('houdini',json.loads((root/'control/production-hosts.json').read_text())['hosts'])
                    self.assertTrue((work/'host.ready').is_file())
                    with mock.patch('houdini_bridge.task_host._reclaim_child',side_effect=AssertionError('must not stop confirmed host twice')):
                        recovered=ensure_hosts(h,n,**kwargs)
                    self.assertNotEqual(recovered[0]['expected_identity']['launch_nonce'],accepted[0]['expected_identity']['launch_nonce'])
                    self.assertEqual(recovered[0]['expected_identity']['version'],'22.0.459')
                finally:
                    current=json.loads((root/'control/production-hosts.json').read_text())
                    if current['hosts']:stop_hosts(root/'control')

    def test_houdini_restart_recovers_before_binding_commit(self):
        from dcc_task_runtime import owned_process
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            hython=root/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
            h=self.config(root,'houdini',hython,api);n=self.config(root,'nuke',SOFTWARE_PYTHON,api)
            kwargs=dict(task_id='restart-task',controller_root=root/'control',repo_root=ROOT,
                        scheduler_root=root/'scheduler',allow_software_processes=True)
            first=ensure_hosts(h,n,**kwargs)
            stop_hosts(root/'control')
            original=owned_process._atomic
            def interrupted(path,value):
                if Path(path).name=='supervisor-binding.json':
                    raise RuntimeError('controller crashed before binding commit')
                return original(path,value)
            with mock.patch.object(owned_process,'_atomic',side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError,'before binding commit'):
                    ensure_hosts(h,n,**kwargs)
            ready=root/'control/houdini-task-host/host.ready'
            old=first[0]['expected_identity']['launch_nonce']
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                try:
                    if json.loads(ready.read_text())['task_host_identity']['launch_nonce']!=old:break
                except (OSError,ValueError,KeyError):pass
                time.sleep(.01)
            else:self.fail('new host did not become ready')
            second=ensure_hosts(h,n,**kwargs)
            self.assertNotEqual(second[0]['expected_identity']['launch_nonce'],old)
            self.assertEqual(ensure_hosts(h,n,**kwargs),second)
            stop_hosts(root/'control')

    def test_restart_record_crash_reconnects_exact_new_host(self):
        for kind in ('houdini','nuke'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
                hython=root/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
                h=self.config(root,'houdini',hython,api);n=self.config(root,'nuke',SOFTWARE_PYTHON,api)
                kwargs=dict(task_id='restart-task',controller_root=root/'control',repo_root=ROOT,
                            scheduler_root=root/'scheduler',allow_software_processes=True)
                try:
                    first=ensure_hosts(h,n,**kwargs)
                    stop_hosts(root/'control')
                    original=production_hosts._atomic;tripped=[False]
                    old=first[0 if kind=='houdini' else 1]['expected_identity']['launch_nonce']
                    def interrupted(path,value):
                        bound=value.get('hosts',{}).get(kind,{})
                        if (not tripped[0] and Path(path).name=='production-hosts.json'
                                and bound.get('expected_identity',{}).get('launch_nonce') not in (None,old)
                                and kind not in value.get('restarts',{})):
                            tripped[0]=True
                            raise RuntimeError('controller crashed before recording new host')
                        return original(path,value)
                    with mock.patch.object(production_hosts,'_atomic',side_effect=interrupted):
                        with self.assertRaisesRegex(RuntimeError,'controller crashed'):
                            ensure_hosts(h,n,**kwargs)
                    self.assertTrue(tripped[0])
                    with self.assertRaisesRegex(ValueError,'RESTART_PENDING'):
                        stop_hosts(root/'control')
                    second=ensure_hosts(h,n,**kwargs)
                    self.assertNotEqual(first[0 if kind=='houdini' else 1]['expected_identity']['pid'],
                                        second[0 if kind=='houdini' else 1]['expected_identity']['pid'])
                    self.assertEqual(ensure_hosts(h,n,**kwargs),second)
                finally:
                    if (root/'control/production-hosts.json').is_file():stop_hosts(root/'control')

    def test_untrusted_stop_receipt_cannot_restart_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            hython=root/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
            h=self.config(root,'houdini',hython,api);n=self.config(root,'nuke',SOFTWARE_PYTHON,api)
            kwargs=dict(task_id='restart-task',controller_root=root/'control',repo_root=ROOT,
                        scheduler_root=root/'scheduler',allow_software_processes=True)
            try:
                first=ensure_hosts(h,n,**kwargs)
                stop_hosts(root/'control')
                previous=first[0]['expected_identity']['launch_nonce']
                receipt=root/'control/houdini-task-host'/('supervisor-'+previous)/'stopped.json'
                original=receipt.read_bytes();receipt.write_text('{"forged":true}')
                try:
                    with self.assertRaises((ValueError,KeyError)):
                        ensure_hosts(h,n,**kwargs)
                    self.assertEqual(len([p for p in (root/'control/houdini-task-host').glob('supervisor-*') if p.is_dir()]),1)
                finally:
                    receipt.write_bytes(original)
            finally:
                if (root/'control/production-hosts.json').is_file():stop_hosts(root/'control')

    def test_confirmed_stop_restarts_both_hosts_with_new_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            hython=root/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
            h=self.config(root,'houdini',hython,api);n=self.config(root,'nuke',SOFTWARE_PYTHON,api)
            kwargs=dict(task_id='restart-task',controller_root=root/'control',repo_root=ROOT,
                        scheduler_root=root/'scheduler',allow_software_processes=True)
            try:
                first=ensure_hosts(h,n,**kwargs)
                stopped=stop_hosts(root/'control')
                self.assertTrue(stopped['nuke']['stopped'])
                self.assertTrue(stopped['houdini']['receipt']['confirmed_exit'])
                second=ensure_hosts(h,n,**kwargs)
                for old,new in zip(first,second):
                    self.assertNotEqual(old['expected_identity']['pid'],new['expected_identity']['pid'])
                    self.assertNotEqual(old['expected_identity']['launch_nonce'],new['expected_identity']['launch_nonce'])
                self.assertGreater(second[1]['expected_identity']['process_generation'],
                                   first[1]['expected_identity']['process_generation'])
                again=ensure_hosts(h,n,**kwargs)
                self.assertEqual([host['expected_identity'] for host in second],
                                 [host['expected_identity'] for host in again])
            finally:
                if (root/'control/production-hosts.json').is_file():
                    stop_hosts(root/'control')

    def config(self,root,kind,executable,api):
        return {'lifecycle':'task_owned','application':kind,'version':'21.0.631' if kind=='houdini' else '17.0v1',
            'executable':str(SOFTWARE_PYTHON),'supervisor_executable':str(SOFTWARE_PYTHON),
            'task_root':str(root),'resource_budget':{'roots':[str(root)],'max_bytes':128*1024*1024},
            'session_seconds':30,'evidence_source':'software_test',
            **({'software_api_dir':str(api)} if kind=='nuke' else
               {'software_launch_script':str(executable)} if Path(executable).resolve() not in
               {SOFTWARE_PYTHON,Path(sys.executable).resolve()} else {})}
    def boot(self,project):
        env=dict(os.environ,PYTHONPATH='',PYTHONNOUSERSITE='1')
        process=subprocess.Popen([str(SOFTWARE_PYTHON),'-I',str(project/'control/server.py'),'--backend','production','--software-processes'],cwd=project,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        process.bridge_stdout=[]
        self.rpc_id=0
        try:
            initialized=self.rpc(process,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test'}})
        except AssertionError as exc:
            process.stdin.close();process.wait(timeout=10)
            detail=json.dumps({'returncode':process.returncode,'stdout':''.join(process.bridge_stdout),
                'stderr':process.stderr.read(),'generated_server':str(project/'control/server.py')},ensure_ascii=False)
            process.stdout.close();process.stderr.close()
            diagnostics=[str(p.relative_to(project))+': '+p.read_text(errors='replace')[-32768:] for p in project.rglob('child.stderr.log')]
            raise AssertionError(str(exc)+'\n'+detail+'\n'+'\n'.join(diagnostics))

        if 'result' not in initialized:
            process.stdin.close();process.wait(timeout=10)
            detail=json.dumps({'returncode':process.returncode,'response':initialized,
                'stdout':''.join(process.bridge_stdout),'stderr':process.stderr.read(),
                'generated_server':str(project/'control/server.py')},ensure_ascii=False)
            process.stdout.close();process.stderr.close()
            diagnostics = []
            for log in sorted(project.rglob('child.stderr.log')):
                diagnostics.append(str(log.relative_to(project)) + ':\n' + log.read_text(errors='replace')[-32768:])
            self.fail('formal generated server boot failed: '+detail+'\n'+'\n'.join(diagnostics))
        process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');process.stdin.flush()
        return process
    def rpc(self,process,method,params):
        self.rpc_id+=1
        request_id=self.rpc_id
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params})+'\n');process.stdin.flush()
        while True:
            line=process.stdout.readline()
            if not line:raise AssertionError('formal generated server closed the MCP session')
            process.bridge_stdout.append(line)
            response=json.loads(line)
            if response.get('id')==request_id:return response
    def tool(self,process,name,arguments):
        response=self.rpc(process,'tools/call',{'name':name,'arguments':arguments})
        if 'result' not in response:raise AssertionError('{} returned JSON-RPC error: {}'.format(name,response))
        if response['result'].get('isError'):
            return {'isError':True,'text':response['result']['content'][0]['text']}
        return json.loads(response['result']['content'][0]['text'])
    def completed_graph_trial(self,process,project,arguments):
        budget=json.loads((project/'control/run.json').read_text(encoding='utf-8'))['trial_budget_seconds']
        deadline=time.monotonic()+float(budget)
        trial=self.tool(process,'graph_trial',arguments)
        operation_id=trial.get('operation_id')
        pending={'PREPARED','STARTING','RUNNING'}
        polled=False
        while operation_id and trial.get('state') in pending and time.monotonic()<deadline:
            time.sleep(.05)
            trial=self.tool(process,'graph_status',{'operation_id':operation_id})
            self.assertEqual(trial.get('operation_id'),operation_id,trial)
            polled=True
        if polled and trial.get('state')=='SUCCEEDED':
            trial=self.tool(process,'graph_trial',arguments)
            self.assertEqual(trial.get('operation_id'),operation_id,trial)
        return trial
    def close(self,process):
        process.stdin.close();process.wait(timeout=5)
        errors=process.stderr.read();process.stdout.close();process.stderr.close()
        self.assertEqual(process.returncode,0,errors)
        self.assertFalse(errors)
    def test_prepared_production_setup_does_not_spend_host_sessions(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();project=base/'project';api=base/'api';api.mkdir()
            (api/'nuke.py').write_text(FAKE)
            hython=base/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
            h=self.config(project,'houdini',hython,api);n=self.config(project,'nuke',SOFTWARE_PYTHON,api)
            prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,
                production_host_config=h,production_nuke_config=n)
            with mock.patch.object(production_hosts,'ensure_hosts',side_effect=AssertionError('setup must not launch')):
                with prepared_graph_facade(project/'control/run.json',repo_root=project/'control/snapshot',
                        scheduler_root=project/'scheduler',allow_software_processes=True) as facade:
                    self.assertEqual(facade.health()['backend_kind'],'production')
                    self.assertIsNone(facade.health()['real_host_bound'])
                    self.assertTrue(callable(facade.host_client.mark_graph_trial_complete))
                    self.assertFalse((project/'control/production-hosts.json').exists())

    def test_formal_generated_entry_launches_both_owned_hosts_and_reconnects(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();project=base/'project';api=base/'native-api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            hython=base/'fake-hython.py';hython.write_text(HYTHON,encoding='utf-8')
            h=self.config(project,'houdini',hython,api);n=self.config(project,'nuke',SOFTWARE_PYTHON,api)
            # Keep the host alive across the bounded construction and controller restart.
            h['session_seconds']=n['session_seconds']=120
            prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,
                simulation_profile=True,
                production_host_config=h,production_nuke_config=n)
            process=None
            try:
                process=self.boot(project)
                self.assertFalse((project/'control/production-hosts.json').exists())
                for index,asset in enumerate(self.tool(process,'catalog',{})['assets']):
                    self.tool(process,'submit_observation',{'asset_id':asset['asset_id'],'request_id':'restart-obs-{}'.format(index),
                        'observation':{'description':'synthetic formal reference','dominant_colors':['grey']}})
                graph=self.tool(process,'graph_propose',{'proposal':PROPOSAL,'request_id':'restart-propose'})
                trial=self.completed_graph_trial(process,project,{'graph_id':graph['graph_id'],'request_id':'restart-trial'})
                if trial.get('state')!='SUCCEEDED':
                    diagnostics=[]
                    for path in sorted(project.rglob('*')):
                        if path.is_file() and path.name == 'journal.sqlite3':
                            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
                                tables = database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                                for (table,) in tables:
                                    quoted = table.replace('"', '""')
                                    diagnostics.append('{} {}: {}'.format(path.relative_to(project), table,
                                        database.execute('SELECT * FROM "' + quoted + '" LIMIT 5').fetchall()))
                        if path.is_file() and (path.name in {'result.json','error.json','completion.json'}
                                or path.name in {'error.txt'} or path.name.endswith('.stderr.log')):
                            diagnostics.append('{}: {}'.format(path.relative_to(project),path.read_text(errors='replace')[-4000:]))
                    self.fail('formal graph construction did not succeed: {}\n{}'.format(trial,'\n'.join(diagnostics)))
                self.assertEqual(trial.get('state'),'SUCCEEDED',trial)
                h_only=json.loads((project/'control/production-hosts.json').read_text())
                self.assertEqual(set(h_only['hosts']), {'houdini'})
                manifest=json.loads((project/'control/run.json').read_text())
                ensure_hosts(manifest['production_host'],manifest['production_nuke'],task_id=h_only['task_id'],
                    controller_root=project/'control',repo_root=project/'control/snapshot',
                    scheduler_root=project/'scheduler',allow_software_processes=True,host_kinds={'nuke'})
                state=json.loads((project/'control/production-hosts.json').read_text())
                self.assertEqual(set(state['hosts']),{'houdini','nuke'})
                config=state['hosts']['nuke'];boundary=production_nuke_client(config,project/'boundary-test')
                boundary.bind_task(state['task_id'])
                self.assertEqual(boundary.call('get_node',{'name':'Read1'})['class'],'Read')
                self.assertFalse(boundary.real_nuke_bound)
                with self.assertRaisesRegex(ValueError,'TASK_CONFLICT'):
                    boundary.call('get_node',{'name':'Read1','task_id':'foreign'})
                for host in state['hosts'].values():
                    self.assertEqual(host['expected_identity']['task_id'],state['task_id'])
                    self.assertEqual(host['ledger_root'],str(project/'control/artifact_ledger'))

                result=trial.get('result') or {}
                self.assertTrue(result.get('construction_executed'),trial)
                for gate in ('nodes_verified','parameters_verified','connections_verified'):
                    self.assertTrue((result.get('verification') or {}).get(gate),trial)
                saved=self.tool(process,'task_save',{})
                self.assertTrue(saved.get('saved_scene_id'),saved)
                # A controlled scene reopen advances only the live host's
                # scene epoch.  Restarting the controller must retain that
                # trusted host instead of treating the stale ready receipt as
                # a foreign identity.
                host_probe=production_host_client(state['hosts']['houdini'],project/'boundary-test')
                host_probe.bind_task(state['task_id'])
                self.assertFalse(host_probe.call('bridge.s06.inspect_scene',{'task_id':state['task_id']}).get('isError',False))
                reopened_in_place=self.tool(process,'task_reopen',{'saved_scene_id':saved['saved_scene_id']})
                self.assertFalse(reopened_in_place.get('isError'),reopened_in_place)
                before_controller_restart=json.loads((project/'control/production-hosts.json').read_text())
                houdini_ready=project/'control/houdini-task-host/host.ready'
                self.close(process);process=None
                process=self.boot(project)
                self.assertIn('saved_scene_id',self.tool(process,'task_save',{}))
                retained=json.loads((project/'control/production-hosts.json').read_text())
                self.assertEqual(retained['hosts']['houdini']['expected_identity']['pid'],
                                 before_controller_restart['hosts']['houdini']['expected_identity']['pid'])
                self.assertGreater(retained['hosts']['houdini']['expected_identity']['scene_epoch'],
                                   before_controller_restart['hosts']['houdini']['expected_identity']['scene_epoch'])
                self.assertEqual(json.loads(houdini_ready.read_text())['task_host_identity'],
                                 retained['hosts']['houdini']['expected_identity'])
                ready_backup=houdini_ready.read_bytes()
                forged=json.loads(ready_backup.decode())
                forged['task_host_identity']['session_id']='foreign-session'
                houdini_ready.write_text(json.dumps(forged),encoding='utf-8')
                try:
                    with self.assertRaisesRegex(ValueError,'PRODUCTION_HEALTH_IDENTITY_MISMATCH'):
                        production_hosts.ensure_hosts(h,n,task_id=state['task_id'],controller_root=project/'control',
                            repo_root=ROOT,scheduler_root=project/'scheduler',allow_software_processes=True)
                finally:
                    houdini_ready.write_bytes(ready_backup)
                stopped=stop_hosts(project/'control')
                self.assertTrue(stopped['nuke']['stopped'])
                self.assertTrue(stopped['houdini']['receipt']['confirmed_exit'])
                self.close(process);process=None
                process=self.boot(project)
                self.assertEqual(json.loads((project/'control/production-hosts.json').read_text()),retained)
                reopened=self.tool(process,'task_reopen',{'saved_scene_id':saved['saved_scene_id']})
                ensure_hosts(manifest['production_host'],manifest['production_nuke'],task_id=state['task_id'],
                    controller_root=project/'control',repo_root=project/'control/snapshot',
                    scheduler_root=project/'scheduler',allow_software_processes=True,host_kinds={'nuke'})
                again=json.loads((project/'control/production-hosts.json').read_text())
                for kind in ('houdini','nuke'):
                    self.assertNotEqual(state['hosts'][kind]['expected_identity']['pid'],
                                        again['hosts'][kind]['expected_identity']['pid'])
                    self.assertNotEqual(state['hosts'][kind]['expected_identity']['launch_nonce'],
                                        again['hosts'][kind]['expected_identity']['launch_nonce'])
                reopened=self.tool(process,'task_reopen',{'saved_scene_id':saved['saved_scene_id']})
                self.assertFalse(reopened.get('isError'),reopened)
                self.assertGreater(reopened.get('structure_verified',0),0,reopened)
                self.assertTrue(reopened.get('nodes_verified'),reopened)
                self.assertTrue(reopened.get('parameters_verified'),reopened)
                self.assertTrue(reopened.get('connections_verified'),reopened)
                task_id=self.tool(process,'health',{})['task_id']
                before=self.tool(process,'graph_version',{'graph_id':graph['graph_id']})
                edit=self.tool(process,'feedback_edit',{'graph_id':graph['graph_id'],'node_id':'raster',
                    'parms':{'voxelsize':0.3},'task_id':task_id})
                self.assertFalse(edit.get('isError'),edit)
                after=self.tool(process,'graph_version',{'graph_id':graph['graph_id']})
                self.assertEqual(after['version'],before['version']+1)
                frames=self.tool(process,'frame_execute',{'request_id':'restart-frames',
                    'frames':[1,2],'budget_seconds':30})
                self.assertTrue(frames.get('operation_id'),frames)
                frame_query=self.tool(process,'operation_query',{'operation_id':frames['operation_id']})
                self.assertEqual(frame_query.get('kind'),'host-frame',frame_query)
                frame_cancel=self.tool(process,'operation_cancel',{'operation_id':frames['operation_id']})
                self.assertEqual(frame_cancel.get('kind'),'host-frame',frame_cancel)
            finally:
                if process is not None:self.close(process)
                if (project/'control/production-hosts.json').exists():
                    stops=stop_hosts(project/'control')
                    self.assertTrue(stops['nuke']['stopped'])
                    self.assertTrue(stops['houdini']['receipt']['confirmed_exit'])

    def test_formal_houdini_render_saved_worker_fact_registration_refusal_and_stop(self):
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from vfx_pipeline.workbuddy_graph_mcp import GraphRun
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();project=base/'project';api=base/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            frame_fixture=base/'library-generated-native.%03d.exr'
            for frame, name in [(1,'openexr-3.4.15-2.exr'),(3,'openexr-3.4.15-2-frame3.exr')]:
                Path(str(frame_fixture) % frame).write_bytes((ROOT/'tests/fixtures/exr'/name).read_bytes())
            fixture_environment=mock.patch.dict(os.environ,{'BRIDGE_TEST_EXR_FIXTURE':str(frame_fixture),
                'BRIDGE_TEST_NATIVE_ROOT':str(ROOT)});fixture_environment.start();self.addCleanup(fixture_environment.stop)
            environment=mock.patch.dict(os.environ,{'HOUDINI_BRIDGE_STATE_DIR':str(project/'bridge-state'),'BRIDGE_SKILLS_STATE_ROOT':str(project/'runtime-state')});environment.start();self.addCleanup(environment.stop)
            native=HYTHON.replace("sys.modules['houdini_bridge_addon']=addon", "sys.modules['houdini_bridge_addon']=addon\n"+STRICT_RENDER_NATIVE+RENDER_SEAL_PUBLICATION_AUDIT)
            hython=base/'fake-hython.py';hython.write_text(native,encoding='utf-8')
            h=self.config(project,'houdini',hython,api);n=self.config(project,'nuke',SOFTWARE_PYTHON,api)
            selection={'schema':'bridge.project-color/1.0','project_id':'software-fixture','revision':1,
                       'colorspace':'linear','source':'human_project_selection'}
            h['project_color']=dict(selection);n['project_color']=dict(selection)
            prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,render_profile=True,
                          production_host_config=h,production_nuke_config=n)
            process=None
            try:
                process=self.boot(project)
                for i,asset in enumerate(self.tool(process,'catalog',{})['assets']):
                    self.tool(process,'submit_observation',{'asset_id':asset['asset_id'],'request_id':'render-obs-'+str(i),
                        'observation':{'description':'synthetic native render reference','dominant_colors':['grey']}})
                graph=self.tool(process,'graph_propose',{'proposal':{'schema':'bridge.registered-domain-construction/1',
                    'domain_pack':'lighting_camera_render_v1','houdini_version':'21.0.631'},'request_id':'render-proposal'})
                self.assertIn('graph_id',graph,graph)
                trial=self.completed_graph_trial(process,project,{'graph_id':graph['graph_id'],'request_id':'render-graph'})
                if trial.get('state') != 'SUCCEEDED':
                    diagnostics=[str(p.relative_to(project))+': '+p.read_text(errors='replace')[-24000:] for p in project.rglob('*') if p.is_file() and p.name in {'result.json','error.json','error.txt','completion.json','child.stderr.log'}]
                    import sqlite3
                    for jp in project.rglob('journal.sqlite3'):
                        with closing(sqlite3.connect(jp)) as db:diagnostics.append(str(jp)+str(db.execute('SELECT * FROM entries').fetchall()))
                    self.fail(str(trial)+'\n'+'\n'.join(diagnostics))
                state=json.loads((project/'control/production-hosts.json').read_text());task=state['task_id']
                host=production_host_client(state['hosts']['houdini'],project/'render-controller');host.bind_task(task)
                topology=trial['result']['topology'];root=topology['root']
                target=topology['nodes']['houdini_rop:/render_network/render']
                self.assertTrue(trial['host_binding']['graph_binding']['graph_ready'])
                self.assertEqual(host.call('node.info',{'path':target})['type'],'Driver/usdrender')
                before_feedback=self.tool(process,'graph_version',{'graph_id':graph['graph_id']})
                rejected=self.tool(process,'feedback_edit',{'graph_id':graph['graph_id'],'node_id':'light',
                    'parms':{'exposure':1.25},'task_id':'foreign-owner'})
                self.assertTrue(rejected.get('isError'))
                changed=self.tool(process,'feedback_edit',{'graph_id':graph['graph_id'],'node_id':'light',
                    'parms':{'exposure':1.25},'task_id':task})
                self.assertFalse(changed.get('isError'),changed)
                self.assertEqual(changed['version'],before_feedback['version']+1)
                self.assertEqual(changed['path'],next(path for address,path in topology['nodes'].items()
                    if address.startswith('houdini_lop:') and address.rsplit('/',1)[-1]=='light'))
                saved=self.tool(process,'task_save',{});self.assertIn('saved_scene_id',saved)
                # New task-owned worker must load the actual saved HIP bytes.
                self.close(process);process=None
                stopped=stop_hosts(project/'control');self.assertTrue(stopped['houdini']['receipt']['confirmed_exit'])
                process=self.boot(project)
                request={'request_id':'formal-render','saved_scene_id':saved['saved_scene_id'],'render_target':target,
                         'pattern':str(project/'saves/render.%03d.exr'),'frames':[1,3],'budget_seconds':20}
                submitted=self.tool(process,'houdini_render_bounded',request);self.assertIn('operation_id',submitted,submitted)
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    queried=self.tool(process,'operation_query',{'operation_id':'formal-render'})
                    if queried.get('operation',{}).get('state') in {'COMPLETED','FAILED'}:break
                    time.sleep(.02)
                self.assertEqual(queried['operation']['state'],'COMPLETED',queried)
                fact=queried['execution_fact'];self.assertEqual(fact['frame_set'],[1,3]);self.assertEqual(set(fact['frame_snapshots']),{'1','3'})
                self.assertEqual(fact['project_color'],selection)
                self.assertNotIn('EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED',fact['completion_metadata_missing_facts'])
                self.assertTrue(all('ocio_configuration_fact' not in value for value in fact['render_config'].values()))
                from readiness_evidence import _formal_receipt_source_errors, _render_file_errors
                self.assertEqual(_formal_receipt_source_errors(fact,'formal-render'),[])
                self.assertEqual(_render_file_errors(fact,'formal-render'),[])
                calls=[json.loads(line) for line in (project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()]
                self.assertEqual([c['frame'] for c in calls],[1,3]);self.assertTrue(all(c['hip_sha256']==saved['sha256'] for c in calls))
                publications=[json.loads(line) for line in (project/'control/houdini-task-host/terminal-publications.jsonl').read_text().splitlines()]
                self.assertIn('RUNNING',[item['state'] for item in publications])
                self.assertEqual(publications[-1]['state'],'COMPLETED')
                self.assertEqual([item['used_bytes'] for item in publications],sorted(item['used_bytes'] for item in publications))
                self.close(process);process=None
                # Reconstructed production boundary reads the persisted render, not controller labels.
                state=json.loads((project/'control/production-hosts.json').read_text())
                host=production_host_client(state['hosts']['houdini'],project/'control/host-state');host.bind_task(task)
                registry=ArtifactRegistry(project/'control/artifact_ledger');host.bind_artifact_registry(registry)
                facade=GraphRun(project/'control/run.json',None,task_id=task,host_client=host,artifact_registry=registry,save_root=str(project/'saves'))
                from dcc_task_runtime.artifact_registry import ArtifactError
                self.assertEqual(fact['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
                self.assertEqual(fact['metadata'], {})
                with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
                    facade.register_render_artifact('render-input','confirmed_cache',request['pattern'],
                        [1,3],'linear',False,'formal-render')
                self.assertIsNone(registry.lookup('render-input'))
                self.assertEqual(registry.history('render-input'), [])
                self.assertEqual(len((project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()),2)
                # Same operation ID freezes content; a new ID may render later.
                with self.assertRaisesRegex(Exception,'different content'):
                    host.call('render.start',{'task_id':task,'request_id':'formal-render','render_target':target,'frames':[2],
                                             'output_pattern':request['pattern'],'budget_seconds':20,'dependencies':[]})
                # Binding drift is refused by the real persistent fact reader.
                binding_record=host._load_operation_owners()['formal-render']
                store_path=Path(binding_record['operation_store_path']);before_store=store_path.read_bytes()
                altered_store=json.loads(before_store);altered_store['operations']['formal-render']['host_identity']['scene_epoch']+=1
                store_path.write_text(json.dumps(altered_store))
                try:
                    with self.assertRaisesRegex(Exception,'frozen binding'):facade.operation_query('formal-render')
                finally:store_path.write_bytes(before_store)
                host.call('render.start',{'task_id':task,'request_id':'slow-render','render_target':target,'frames':[1],
                    'output_pattern':str(project/'saves/slow.%03d.exr'),'budget_seconds':10,'dependencies':[]})
                facade._register_operation('slow-render','houdini-render','houdini','slow-render')
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if len((project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines())==3:break
                    time.sleep(.01)
                # Interrupt THIS renderer worker; an unknown stop must hold its slot.
                facade.operation_cancel('slow-render')
                supervisor=Path(host._load_operation_owners()['slow-render']['supervisor_binding']['directory'])
                deadline=time.monotonic()+6
                while time.monotonic()<deadline and not (supervisor/'stopped.json').is_file():time.sleep(.01)
                stopped_receipt=(supervisor/'stopped.json').read_bytes();(supervisor/'stopped.json').unlink()
                try:
                    unknown=facade.operation_query('slow-render')['operation']
                    self.assertEqual(unknown['state'],'RUNNING')
                    self.assertTrue(GraphScheduler(project/'scheduler').snapshot()['active'])
                finally:(supervisor/'stopped.json').write_bytes(stopped_receipt)
                with mock.patch.object(GraphScheduler,'release',side_effect=OSError('slot release unavailable')):
                    with self.assertRaises(OSError):facade.operation_query('slow-render')
                self.assertTrue(GraphScheduler(project/'scheduler').snapshot()['active'])
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    record=facade.operation_query('slow-render')['operation']
                    if record['state']=='CANCELLED':break
                    time.sleep(.02)
                self.assertEqual(record['state'],'CANCELLED',record)
                self.assertIsNotNone(record.get('stop_receipt'))
                self.assertFalse(GraphScheduler(project/'scheduler').snapshot()['active'])
                self.assertFalse((project/'saves/slow.001.exr').exists())
                self.assertEqual(len((project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()),3)
                # Restart, reopen, and enforce the frozen budget on the real
                # native-substitute worker. Rewriting its budget cannot extend it.
                new_h,new_n=ensure_hosts(h,n,task_id=task,controller_root=project/'control',repo_root=ROOT,
                    scheduler_root=project/'scheduler',allow_software_processes=True)
                host=production_host_client(new_h,project/'control/host-state');host.bind_task(task)
                facade.host_client=host;host.bind_artifact_registry(registry)
                facade.houdini_render_bounded('budget-render',saved['saved_scene_id'],target,
                    str(project/'saves/slow.%03d.exr'),[1],budget_seconds=.5)
                supervisor=Path(host._load_operation_owners()['budget-render']['supervisor_binding']['directory'])
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    if len((project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines())==4:break
                    time.sleep(.01)
                # Wait for the supervisor's signed observation, so the test
                # rewrites a frozen deadline rather than racing initial read.
                from dcc_task_runtime.owned_process import read_receipt
                identity=host._load_operation_owners()['budget-render']['supervisor_binding']['identity']
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    observed=read_receipt(supervisor,'operation-budget-observed',identity=identity)
                    if observed and observed.get('operation_id')=='budget-render':break
                    time.sleep(.01)
                else:self.fail('supervisor did not acknowledge this render budget')
                self.assertEqual(observed['budget_seconds'],.5)
                budget_path=supervisor/'operation-budget.json';altered=json.loads(budget_path.read_text())
                altered['payload']['budget_seconds']=120;altered['payload']['started_at_epoch']=time.time()+100
                from dcc_task_runtime.owned_process import _signed_write
                _signed_write(supervisor,altered['payload'])
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    record=facade.operation_query('budget-render')['operation']
                    if record['state']=='BUDGET_REACHED':break
                    time.sleep(.02)
                self.assertEqual(record['state'],'BUDGET_REACHED',record)
                self.assertEqual(record['stop_receipt']['stop_reason'],'OPERATION_TIME_BUDGET_EXCEEDED')
                self.assertLess(record['stop_receipt']['observed_at']-observed['started_at_epoch'],5)
                self.assertFalse((project/'saves/slow.001.exr').exists())
                self.assertEqual(record['execution_fact']['state'],'BUDGET_REACHED')
                self.assertFalse(GraphScheduler(project/'scheduler').snapshot()['active'])
                evidence_dir=os.environ.get('BRIDGE_RENDER_C_EVIDENCE_DIR')
                if evidence_dir:
                    import shutil
                    evidence=Path(evidence_dir);evidence.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(project/'control/houdini-task-host/native-render-calls.jsonl',evidence/'native-render-calls.jsonl')
                    shutil.copyfile(Path(saved['path']),evidence/'software-saved-task.hip')
                    (evidence/'saved-scene-receipt.json').write_text(json.dumps(saved,sort_keys=True,indent=2))
                    for operation in ('formal-render','slow-render','budget-render'):
                        (evidence/(operation+'.query.json')).write_text(json.dumps(facade.operation_query(operation),sort_keys=True,indent=2))
                    for label in ('slow-render','budget-render'):
                        folder=Path(host._load_operation_owners()[label]['supervisor_binding']['directory'])
                        for filename in ('started.json','stopped.json'):
                            shutil.copyfile(folder/filename,evidence/(label+'.'+filename))
            finally:
                if process is not None:self.close(process)
                if (project/'control/production-hosts.json').is_file():stop_hosts(project/'control')

    def test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen(self):
        from houdini_bridge import native_render_domains
        cases = [
            (native_render_domains.MATERIAL, None, {'roughness':.3,'normal_strength':.7,'ior':1.6}, None),
            (native_render_domains.LIGHTING, None, {'focal_length':45.,'shutter':.4,'exposure':1.5,'filter_width':2.5}, None),
            ('vellum_cloth_v1', None, {'stretch_stiffness':300.,'bend_stiffness':6.,'thickness':.03,'collision_thickness':.03,'substeps':4,'constraint_iterations':20,'damping':2.,'wrinkle_scale':.5},
             {'constraints':{'stretchstiffness':300.,'bendstiffness':6.,'thickness':.03},
              'source':{'rows':17,'cols':17},'solver':{'substeps':4,'niter':20,'veldamping':2.}}),
            ('vellum_softbody_grains_v1', 'softbody', {'stiffness':300.,'cluster_stiffness':2.,'damping':.6},
             {'constraints':{'stretchstiffness':300.},'cluster_constraints':{'stretchstiffness':2.},'solver':{'veldamping':.6}}),
            ('vellum_softbody_grains_v1', 'grains', {'grain_size':.2,'packing':1.5,'cluster_stiffness':2.},
             {'grain_source':{'grainsize':.2,'packingdensity':1.5},'constraints':{'glue_radius':.4},'cluster_constraints':{'stretchstiffness':2.}}),
            ('pyro_smoke_v1', None, {'source_scale':.5,'voxel_size':.2,'volume_samples':7},
             {'source':{'radx':.5,'rady':.5,'radz':.5},'solver':{'divsize':.2},'source_volume':{'voxelsize':.2},
              'render_settings':{'varianceaa_minsamples':1,'varianceaa_maxsamples':1,'volumequality':7.}}),
            ('pyro_fire_v1', None, {'burn_rate':2.,'temperature_scale':2.,'fuel_rate':3.},
             {'solver':{'flames_lifespan':.5,'source_vscale2':2.,'source_vscale3':3.}}),
            ('water_flip_v1', None, {'particle_separation':.2,'substeps':4,'viscosity':25.},
             {'fluid_source':{'particlesep':.2},'container':{'particlesep':.2,'default_viscosity':25.},
              'surface':{'particlesep':.2},'solver':{'minimumsubsteps':4,'substeps':4}}),
            ('hair_fur_v1', None, {'guide_length':.4,'guide_density':20.,'hair_width':.01,'bend_stiffness':1000.,'damping':2.,'clump':.2,'collision_radius':.02,'clump_strength':.7,'wind_strength':-3.},
             {'guide_seed':{'unguidedlength':.4,'density':20.},'guides':{'density':20.,'width':.01},
              'guide_length':{'setlength_length1':.4},'hair':{'density':20.,'thickness':.01},
              'constraints':{'bendstiffness':1000.,'thickness':.02},'solver':{'veldamping':2.,'windy':-1.,'windspeed':3.},
              'hair_clump':{'clumpsize':.2,'tightness':.7/100.}}),
            ('crowd_agents_v1', None, {'speed':3.,'speed_variance':.2,'clip_offset':1.5,'route_weight':75.,'animation_blend':1.25},
             {'source':{'initialvelx':3.,'initialvely':0.,'initialvelz':0.,'randominitvelx':3.,
                'randominitveloffsetx':.2,'randominitveloffsety':0.,'randominitveloffsetz':0.},
              'state':{'globalclipoffset':14.},'route':{'weight':75.},'transition':{'duration':1.25}}),
            ('rbd_destruction_v1', None, {'constraint_strength':8.,'impact_threshold':3.,'substeps':4,'activation_frame':3},
             {'solver':{'glue_strength':8.,'constraint_impactthreshold1':3.,'substeps':4},
              'constraint_strength':{'class':1,'group':'','snippet':'if (s@constraint_name == "Glue") f@strength = 1.0;'}}),
            ('particles_v1', None, {'birth_rate':100.,'life':3.,'speed':2.},
             {'emission':{'constantrate':100.,'life':3.,'velx':0.,'vely':2.,'velz':0.}}),
            ('swarm_flocking_v1', None, {'cohesion':3.,'separation':4.,'goal_attraction':2.},
             {'flock':{'centralforce':3.,'interactionforce':4.},'seek':{'forcescale':2.}}),
            ('water_ocean_v1', None, {'wave_scale':2.,'wind_speed':12.,'wind_direction':30.,'chop':.8,'foam':True,'foam_amount':3.,'crest_threshold':.1},
             {'spectrum':{'ampscale':2.,'windspeed':12.,'winddir':30.,'chopscale':.8},'foam_emit':{'density':3.,'mincusp':.1}}),
            ('procedural_geometry_v1', None, {'scatter_density':12,'seed':3,'scale':1.5},
             {'scatter':{'npts':12,'seed':3},'instance_transform':{'scale':1.5}}),
        ]
        selected = set(filter(None,os.environ.get('BRIDGE_TEST_REGISTERED_DOMAINS','').split(',')))
        unknown = selected - {domain for domain, branch, changes, expected_roles in cases}
        if unknown:
            self.fail('unknown registered-domain filter: ' + ','.join(sorted(unknown)))
        for version in ('21.0.631','22.0.429'):
            for domain,branch,changes,expected_roles in cases:
                if selected and domain not in selected:
                    continue
                with self.subTest(version=version,domain=domain,branch=branch),tempfile.TemporaryDirectory() as temp:
                    base=Path(temp).resolve();project=base/'project';api=base/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
                    with mock.patch.dict(os.environ,{'BRIDGE_TEST_NATIVE_ROOT':str(ROOT),'BRIDGE_TEST_NATIVE_VERSION':version,
                            'BRIDGE_TEST_MATERIAL_REOPEN_PROBE':str(project/'material-reopen-request.json'),
                            'HOUDINI_BRIDGE_STATE_DIR':str(project/'bridge-state'),'BRIDGE_SKILLS_STATE_ROOT':str(project/'runtime-state')}):
                        native=HYTHON.replace("sys.modules['houdini_bridge_addon']=addon", "sys.modules['houdini_bridge_addon']=addon\n"+STRICT_RENDER_NATIVE)
                        if domain==native_render_domains.MATERIAL:
                            native=native.replace(STRICT_RENDER_NATIVE,STRICT_RENDER_NATIVE+MATERIAL_REOPEN_READBACK)
                        hython=base/'fake-hython.py';hython.write_text(native,encoding='utf-8')
                        h=self.config(project,'houdini',hython,api);h['version']=version
                        n=self.config(project,'nuke',SOFTWARE_PYTHON,api)
                        h['session_seconds']=120
                        n['session_seconds']=120
                        prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,render_profile=True,
                                      production_host_config=h,production_nuke_config=n)
                        process=None
                        try:
                            process=self.boot(project)
                            for index,asset in enumerate(self.tool(process,'catalog',{})['assets']):
                                self.tool(process,'submit_observation',{'asset_id':asset['asset_id'],'request_id':'domain-obs-'+str(index),
                                    'observation':{'description':'software native API reference','dominant_colors':['grey']}})
                            selector={'schema':'bridge.registered-domain-construction/1','domain_pack':domain,'houdini_version':version}
                            if branch is not None:selector['native_branch']=branch
                            graph=self.tool(process,'graph_propose',{'proposal':selector,'request_id':'domain-proposal'})
                            self.assertIn('graph_id',graph,graph)
                            trial=self.completed_graph_trial(process,project,{'graph_id':graph['graph_id'],'request_id':'domain-trial'})
                            if trial.get('state')!='SUCCEEDED':
                                errors=[p.read_text(errors='replace') for p in project.rglob('error.txt')]
                                errors.extend(p.read_text(errors='replace') for p in project.rglob('result.json'))
                                import sqlite3
                                for journal in project.rglob('journal.sqlite3'):
                                    with closing(sqlite3.connect(journal)) as db:
                                        errors.extend(row[0] for row in db.execute('SELECT payload FROM entries') if json.loads(row[0]).get('status')!='COMPLETE')
                                self.fail(str(trial)+'\n'+'\n'.join(errors))
                            topology=trial['result']['topology'];roles={address.rsplit('/',1)[-1]:path for address,path in topology['nodes'].items()}
                            state=json.loads((project/'control/production-hosts.json').read_text());task=state['task_id']
                            host=production_host_client(state['hosts']['houdini'],project/'domain-controller');host.bind_task(task)
                            params={'task_id':task,'constraints':{'fx':{'domain_pack':domain,'run_mode':'diagnose','frames':[1,2],'changes':changes}},
                                'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                            if branch is not None:params['constraints']['fx']['vellum_branch']=branch
                            geometry_refusals=[]
                            def geometry_deformation_refused():
                                from houdini_bridge.client import BridgeError
                                path=roles['geometry_deform']
                                before=host.call('node.parms',{'path':path,'names':['snippet']})['parms']
                                refused_params=json.loads(json.dumps(params))
                                refused_params['constraints']['fx']['changes']={'deformation':1.}
                                with self.assertRaises(BridgeError) as refused:
                                    host.call('agent.fx.apply_candidate',refused_params)
                                self.assertEqual(refused.exception.code,'GEOMETRY_REGISTERED_COHORT_REQUIRED')
                                after=host.call('node.parms',{'path':path,'names':['snippet']})['parms']
                                self.assertEqual(after,before)
                                geometry_refusals.append({'host_identity':state['hosts']['houdini']['expected_identity'],
                                    'code':refused.exception.code,'path':path,'before':before,'after':after})
                            if domain=='procedural_geometry_v1':geometry_deformation_refused()
                            diffs=[]
                            regular=[item for item in changes.items() if item[0]!='wrinkle_scale']
                            batches=[dict(regular[offset:offset+5]) for offset in range(0,len(regular),5)]
                            if 'wrinkle_scale' in changes:batches.append({'wrinkle_scale':changes['wrinkle_scale']})
                            for batch in batches:
                                params['constraints']['fx']['changes']=batch
                                changed=host.call('agent.fx.apply_candidate',params)
                                diffs.extend(changed['parameter_diff'])
                            changed={**changed,'parameter_diff':diffs}
                            self.assertEqual({d['semantic_control'] for d in changed['parameter_diff']},set(changes))
                            self.assertTrue(all(d['readback_verified'] for d in changed['parameter_diff']))
                            wave_feedback=[]
                            if domain=='vellum_cloth_v1':
                                def wave_apply(batch):
                                    params['constraints']['fx']['changes']=batch
                                    result=host.call('agent.fx.apply_candidate',params)
                                    wave_feedback.append(result)
                                    return result['native_geometry_readback']
                                wave=wave_apply({'wrinkle_scale':.5})
                                positions=wave['shaped_geometry']['point_positions']
                                self.assertEqual(wave_apply({'wrinkle_scale':.5})['shaped_geometry']['point_positions'],positions)
                                thicker=wave_apply({'thickness':.06})
                                self.assertEqual(thicker['registration']['wrinkle_scale'],.5)
                                self.assertEqual(thicker['registration']['amplitude'],.03)
                                flat=wave_apply({'wrinkle_scale':0.})
                                self.assertEqual(flat['shaped_geometry']['point_positions'],flat['context']['source']['point_positions'])
                                restored=wave_apply({'thickness':changes['thickness'],'wrinkle_scale':.5})
                                self.assertEqual(restored['shaped_geometry']['point_positions'],positions)
                            ocean_feedback=[]
                            if domain=='water_ocean_v1':
                                def ocean_apply(batch):
                                    params['constraints']['fx']['changes']=batch
                                    result=host.call('agent.fx.apply_candidate',params)
                                    ocean_feedback.append(result)
                                    return result
                                measured=ocean_apply({'foam':True})['native_geometry_readback']
                                self.assertGreater(max(measured['masked_geometry']['point_attributes']['foam_mask']['values']),0.)
                                self.assertEqual(ocean_apply({'foam':True})['native_geometry_readback']['masked_geometry'],measured['masked_geometry'])
                                density=ocean_apply({'foam_amount':4.})
                                self.assertEqual(density['native_geometry_readback']['registration']['foam_amount_native_density'],4.)
                                self.assertTrue(any(d.get('dependent_semantic_control')=='foam' for d in density['parameter_diff']))
                                disabled=ocean_apply({'foam':False})['native_geometry_readback']
                                self.assertEqual(disabled['masked_geometry']['point_attributes']['foam_mask']['values'],[0.]*len(measured['masked_geometry']['point_positions']))
                                alias=ocean_apply({'spectrum_amplitude':2.})
                                self.assertIn('source_layout_control',alias['invalidates_from'])
                                ocean_apply({'foam_amount':3.,'foam':True})
                            expected={}
                            if expected_roles is None:
                                targets=native_render_domains.candidate_write_plan(domain,changes,version,shutter_contract=native_render_domains.SHUTTER_CONTRACT)
                                for write in targets:expected.setdefault(roles[write['role']],{})[write['parm']]=write['value']
                            else:
                                expected={roles[role]:values for role,values in expected_roles.items()}
                            geometry_saved={}
                            if domain in ('vellum_cloth_v1','hair_fur_v1','water_ocean_v1','crowd_agents_v1','rbd_destruction_v1'):
                                geometry_saved=host.call('agent.fx.collect_evidence',params)['evidence']['native_geometry_readback']
                                self.assertEqual(set(geometry_saved),{'1','2'})
                                if domain=='vellum_cloth_v1':
                                    expected[roles['cloth_wrinkle']]={'class':2,'group':'','vex_precision':'64',
                                        'snippet':geometry_saved['1']['registration']['program']}
                                if domain=='water_ocean_v1':
                                    a,b=(geometry_saved[str(f)] for f in (1,2))
                                    self.assertNotEqual(a['context']['spectrum']['sample_time'],b['context']['spectrum']['sample_time'])
                                    self.assertNotEqual(a['masked_geometry']['point_attributes']['bridge_ocean_cusp']['values'],b['masked_geometry']['point_attributes']['bridge_ocean_cusp']['values'])
                                    self.assertEqual(a['registration']['sha256'],b['registration']['sha256'])
                                    expected[roles['ocean_masks']]={'class':2,'group':'','vex_precision':'64','snippet':a['registration']['program']}
                            def read():
                                return {path:host.call('node.parms',{'path':path,'names':sorted(values)})['parms'] for path,values in expected.items()}
                            self.assertEqual(read(),expected)
                            before={address:host.call('node.info',{'path':path,**({'native_port_names':True} if expected_roles is None else {})}) for address,path in topology['nodes'].items()}
                            if domain==native_render_domains.MATERIAL:
                                (project/'material-reopen-request.json').write_text(
                                    json.dumps({'params':params,'roles':roles}),encoding='utf-8')
                            saved=self.tool(process,'task_save',{});self.assertIn('saved_scene_id',saved,saved)
                            self.close(process);process=None
                            stopped=stop_hosts(project/'control');self.assertTrue(stopped['houdini']['receipt']['confirmed_exit'])
                            previous_identity=state['hosts']['houdini']['expected_identity']
                            process=self.boot(project)
                            reopened=self.tool(process,'task_reopen',{'saved_scene_id':saved['saved_scene_id']})
                            self.assertTrue(reopened.get('nodes_verified'),reopened)
                            self.assertTrue(reopened.get('parameters_verified'),reopened)
                            self.assertTrue(reopened.get('connections_verified'),reopened)
                            state=json.loads((project/'control/production-hosts.json').read_text())
                            self.assertNotEqual(state['hosts']['houdini']['expected_identity']['pid'],previous_identity['pid'])
                            self.assertNotEqual(state['hosts']['houdini']['expected_identity']['launch_nonce'],previous_identity['launch_nonce'])
                            host=production_host_client(state['hosts']['houdini'],project/'domain-controller');host.bind_task(task)
                            self.assertEqual(read(),expected)
                            if domain=='procedural_geometry_v1':geometry_deformation_refused()
                            material_saved={};material_reopened={}
                            if domain==native_render_domains.MATERIAL:
                                probes=[json.loads(line) for line in (project/'material-reopen-request.jsonl').read_text(encoding='utf-8').splitlines()]
                                material_saved=next(item for item in reversed(probes) if item['phase']=='saved' and item['pid']==previous_identity['pid'])
                                material_reopened=next(item for item in reversed(probes) if item['phase']=='reopened' and item['pid']==state['hosts']['houdini']['expected_identity']['pid'])
                                for observed in (material_saved,material_reopened):
                                    native_static=observed['native_static_readback']
                                    binding=native_static['usd_binding_readback']
                                    self.assertEqual(native_static['output_role'],'settings_binding')
                                    self.assertEqual(native_static['output_kind'],'usd_render_stage')
                                    self.assertTrue(native_static['topology_and_parameters_verified'])
                                    self.assertEqual(observed['final_lop_path'],roles['settings_binding'])
                                    self.assertTrue(binding['imported_prim_paths'])
                                    self.assertEqual(observed['material_binding_targets'],[binding['material_prim_path']])
                                    self.assertEqual(set(observed['render_configuration']),{'1','2'})
                                    self.assertIn(binding['render_config'],
                                        [{frame:config} for frame,config in observed['render_configuration'].items()])
                                    for config in observed['render_configuration'].values():
                                        self.assertEqual(config['loppath'],roles['settings_binding'])
                                        self.assertTrue(config['products']);self.assertTrue(config['aovs']);self.assertTrue(config['lights'])
                                        self.assertEqual(config['exr_format']['storage'],'scanline')
                                    if version=='22.0.429':
                                        filters=binding['pixel_filter']
                                        self.assertEqual(filters['unit'],'pixels')
                                        if filters['usd_legacy_width'] is None:self.assertEqual(filters['width'],2.)
                                        else:self.assertEqual(filters['usd_legacy_width'],filters['width'])
                                self.assertEqual({key:value for key,value in material_saved.items() if key not in {'phase','pid'}},
                                                 {key:value for key,value in material_reopened.items() if key not in {'phase','pid'}})
                            geometry_reopened={}
                            measured_control='wrinkle_scale' if domain=='vellum_cloth_v1' and 'wrinkle_scale' in changes else 'collision_radius' if domain=='hair_fur_v1' and 'collision_radius' in changes else 'foam' if domain=='water_ocean_v1' else 'route_weight' if domain=='crowd_agents_v1' else 'activation_frame' if domain=='rbd_destruction_v1' else None
                            if measured_control:
                                collected=host.call('agent.fx.collect_evidence',params)['evidence']['native_geometry_readback']
                                if domain in ('crowd_agents_v1','rbd_destruction_v1'):
                                    def persistent(value):
                                        if isinstance(value,dict):return {k:persistent(v) for k,v in value.items() if k not in ('identity','instance_id')}
                                        if isinstance(value,list):return [persistent(v) for v in value]
                                        return value
                                    self.assertEqual(persistent(collected),persistent(geometry_saved))
                                if domain=='crowd_agents_v1':
                                    old=geometry_saved['1']['route_context']['identity'];new=collected['1']['route_context']['identity']
                                    self.assertEqual(old['task_id'],new['task_id']);self.assertEqual(old['resource_id'],new['resource_id'])
                                    self.assertNotEqual(old['process_generation'],new['process_generation'])
                                    self.assertNotEqual(old['session_id'],new['session_id'])
                                    self.assertEqual([collected[str(f)]['frame'] for f in (1,2)],[1.,2.])
                                    for frame in ('1','2'):
                                        transition_context=collected[frame]['transition_context']
                                        self.assertEqual(collected[frame]['transition_readback']['animation_blend'],1.25)
                                        snapshot=json.loads(transition_context['geometry']['snapshot_json'])
                                        self.assertEqual([c['name'] for c in snapshot['content']['agents'][0]['clips']],['w5_loop','w5_transition'])
                                        self.assertEqual(snapshot['native_payloads'],json.loads(geometry_saved[frame]['transition_context']['geometry']['snapshot_json'])['native_payloads'])

                                elif domain!='rbd_destruction_v1':self.assertEqual(collected,geometry_saved)
                                geometry_reopened=collected['1']
                                self.assertTrue(geometry_reopened)
                                if measured_control=='wrinkle_scale':
                                    self.assertTrue(geometry_reopened['comparison']['pointwise_formula_matches'])
                                    self.assertTrue(geometry_reopened['comparison']['period_observable'])
                                    self.assertTrue(geometry_reopened['comparison']['amplitude_observable'])
                                elif measured_control=='route_weight':
                                    self.assertEqual(geometry_reopened['route_readback']['route_weight'],75.)
                                    self.assertEqual(geometry_reopened['route_context']['curve']['points'],[[0.,0.,0.],[4.,0.,0.],[8.,0.,3.]])
                                elif measured_control=='foam':
                                    self.assertTrue(geometry_reopened['comparison']['pointwise_mask_formula_matches'])
                                    self.assertTrue(geometry_reopened['comparison']['evaluated_positions_and_topology_unchanged'])
                                elif measured_control=='activation_frame':
                                    channel=geometry_reopened['activation_channel']
                                    self.assertEqual(channel['registration']['activation_frame'],3)
                                    self.assertEqual(channel['samples'],[{'frame':frame,'value':int(frame>=3)} for frame in (1,2,3,4)])
                                    self.assertEqual([sample['active_values'] for sample in geometry_reopened['configure_output_samples']],[[0,0],[0,0],[1,1],[1,1]])
                                    self.assertEqual(channel['pre_extrapolation'],'constant')
                                    self.assertEqual(channel['post_extrapolation'],'constant')
                                else:
                                    self.assertTrue(geometry_reopened['radius_measurement_observable'])
                                    self.assertEqual(set(geometry_reopened['actual_geometry']['point_attribute_values']['pscale']),{changes[measured_control]})
                            self.assertEqual(before,{address:host.call('node.info',{'path':path,**({'native_port_names':True} if expected_roles is None else {})}) for address,path in topology['nodes'].items()})
                            evidence_root=os.environ.get('BRIDGE_REGISTERED_DOMAIN_EVIDENCE_DIR')
                            if evidence_root:
                                import shutil
                                evidence=Path(evidence_root)/version/(domain+('-'+branch if branch else ''));evidence.mkdir(parents=True,exist_ok=True)
                                for label,value in [('trial',trial),('feedback',changed),('wave_feedback',wave_feedback),('ocean_feedback',ocean_feedback),('saved',saved),('reopened',reopened),('targets',expected),('material_saved',material_saved),('material_reopened',material_reopened),('geometry_saved',geometry_saved),('geometry_reopened',geometry_reopened),('geometry_refusals',geometry_refusals),('confirmed_stop',stopped),('host_before_reopen',previous_identity),('host_after_reopen',state['hosts']['houdini']['expected_identity'])]:
                                    (evidence/(label+'.json')).write_text(json.dumps(value,sort_keys=True,indent=2))
                                (evidence/'snapshot-manifest.json').write_bytes((project/'control/snapshot-manifest.json').read_bytes())
                                shutil.copyfile(saved['path'],evidence/'task.hip')
                                for journal in project.rglob('journal.sqlite3'):shutil.copyfile(journal,evidence/'journal.sqlite3')
                        finally:
                            if process is not None:self.close(process)
                            evidence_root=os.environ.get('BRIDGE_REGISTERED_DOMAIN_EVIDENCE_DIR')
                            if evidence_root:
                                import shutil
                                diagnostics=Path(evidence_root)/version/(domain+('-'+branch if branch else ''))/'lifecycle-before-cleanup'
                                for path in project.rglob('*'):
                                    if path.is_file() and (path.name in ('started.json','stopped.json','child.stderr.log','supervisor.stderr.log') or path.name.endswith('.shutdown.json')):
                                        target=diagnostics/path.relative_to(project)
                                        target.parent.mkdir(parents=True,exist_ok=True)
                                        shutil.copyfile(path,target)
                            if (project/'control/production-hosts.json').is_file():stop_hosts(project/'control')

    def test_crowd_prepared_worker_normal_entry(self):
        versions=tuple(filter(None,os.environ.get('BRIDGE_TEST_CROWD_VERSIONS','21.0.631,22.0.429').split(',')))
        self.assertTrue(versions)
        self.assertTrue(set(versions)<={'21.0.631','22.0.429'})
        for version in versions:
            with self.subTest(version=version),tempfile.TemporaryDirectory() as temp:
                base=Path(temp).resolve();project=base/'project';api=base/'api';api.mkdir()
                (api/'nuke.py').write_text(FAKE,encoding='utf-8')
                with mock.patch.dict(os.environ,{'BRIDGE_TEST_NATIVE_ROOT':str(ROOT),
                        'BRIDGE_TEST_NATIVE_VERSION':version,'HOUDINI_BRIDGE_STATE_DIR':str(project/'bridge-state'),
                        'BRIDGE_SKILLS_STATE_ROOT':str(project/'runtime-state')}):
                    trace='''
def trace_crowd_entry(frame,event,arg):
    if event!='call' or frame.f_code.co_filename!=str(addon_source):return
    name=frame.f_code.co_name
    if name not in ('_fx_scene_parameter_readback','_fx_crowd_stash_snapshot',
            '_fx_initialize_crowd_domain','graph_initialize_registered_domain'):return
    parm=frame.f_locals.get('parm')
    if name=='_fx_scene_parameter_readback' and parm.name()!='stash':return
    node=parm.node() if parm is not None else hou.node(frame.f_locals.get('path',''))
    record={'pid':os.getpid(),'function':name,'task_id':frame.f_locals.get('task_id')}
    if node is not None:
        record.update(path=node.path(),node_type=node.type().name(),
            agent_recipe=node.userData('bridge_native_agent_recipe_v1'),
            route_recipe=node.userData('bridge_native_route_recipe_v1'))
    if parm is not None:
        record.update(parameter_type=str(parm.parmTemplate().type()),raw_value=parm.value)
        record['driver']=addon._component_driver_identity(parm)
        for label,read in (('stashfile',lambda:node.parm('stashfile').eval()),
                           ('geometry',lambda:parm.evalAsGeometry())):
            try:
                value=read()
                record[label]=value if value is None or isinstance(value,(str,int,float,bool)) else type(value).__name__
            except Exception as error:record[label]={'error':type(error).__name__+': '+str(error)}
    with (runner.parent/'crowd-entry-calls.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(record,sort_keys=True)+'\\n')
sys.setprofile(trace_crowd_entry)
'''
                    tracing = trace if os.environ.get('BRIDGE_TEST_CROWD_TRACE') == '1' else ''
                    native=HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
                        "sys.modules['houdini_bridge_addon']=addon\n"+STRICT_RENDER_NATIVE+tracing)
                    hython=base/'fake-hython.py';hython.write_text(native,encoding='utf-8')
                    h=self.config(project,'houdini',hython,api);h.update(version=version,session_seconds=120)
                    n=self.config(project,'nuke',SOFTWARE_PYTHON,api);n['session_seconds']=120
                    prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,
                        render_profile=True,production_host_config=h,production_nuke_config=n)
                    process=None;trial=None;stopped=None
                    try:
                        process=self.boot(project)
                        for index,asset in enumerate(self.tool(process,'catalog',{})['assets']):
                            self.tool(process,'submit_observation',{'asset_id':asset['asset_id'],
                                'request_id':'crowd-entry-obs-'+str(index),
                                'observation':{'description':'software native API reference','dominant_colors':['grey']}})
                        selector={'schema':'bridge.registered-domain-construction/1',
                            'domain_pack':'crowd_agents_v1','houdini_version':version}
                        graph=self.tool(process,'graph_propose',{'proposal':selector,'request_id':'crowd-entry-proposal'})
                        self.assertIn('graph_id',graph,graph)
                        trial=self.completed_graph_trial(process,project,
                            {'graph_id':graph['graph_id'],'request_id':'crowd-entry-trial'})
                        errors=[path.read_text(errors='replace') for path in project.rglob('error.txt')]
                        self.assertEqual(trial.get('state'),'SUCCEEDED',str(trial)+'\n'+'\n'.join(errors))
                    finally:
                        try:
                            if process is not None:self.close(process)
                        finally:
                            if (project/'control/production-hosts.json').is_file():
                                stopped=stop_hosts(project/'control')
                            evidence_root=os.environ.get('BRIDGE_REGISTERED_DOMAIN_EVIDENCE_DIR')
                            if evidence_root:
                                import shutil
                                evidence=Path(evidence_root)/version/'crowd-prepared-worker-normal'
                                evidence.mkdir(parents=True,exist_ok=True)
                                (evidence/'trial.json').write_text(json.dumps(trial,sort_keys=True,indent=2),encoding='utf-8')
                                (evidence/'confirmed-stop.json').write_text(json.dumps(stopped,sort_keys=True,indent=2),encoding='utf-8')
                                (evidence/'snapshot-manifest.json').write_bytes((project/'control/snapshot-manifest.json').read_bytes())
                                if process is not None:
                                    (evidence/'mcp-responses.jsonl').write_text(''.join(process.bridge_stdout),encoding='utf-8')
                                for path in project.rglob('*'):
                                    if path.is_file() and (path.name in ('started.json','stopped.json',
                                            'child.stderr.log','child.stdout.log','supervisor.stderr.log','error.txt',
                                            'result.json','journal.sqlite3','crowd-entry-calls.jsonl')
                                            or path.name.endswith('.shutdown.json')):
                                        target=evidence/'lifecycle'/path.relative_to(project)
                                        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)

    def test_registered_domain_filter_rejects_unknown_before_launch(self):
        with mock.patch.dict(os.environ, {'BRIDGE_TEST_REGISTERED_DOMAINS': 'rigid_bodies_v1'}), \
                mock.patch.object(tempfile, 'TemporaryDirectory', side_effect=AssertionError('unexpected launch')), \
                self.assertRaisesRegex(AssertionError, 'unknown registered-domain filter: rigid_bodies_v1'):
            self.test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen()

    def test_native_scope_deployment_shares_frozen_root_and_rejects_scope_escape(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            task = root / 'task'
            task.mkdir()
            color={'schema':'bridge.project-color/1.0','project_id':'scope-test','revision':1,
                   'colorspace':'ACEScg','source':'human_project_selection'}
            binary={'path':str(SOFTWARE_PYTHON),'bytes':SOFTWARE_PYTHON.stat().st_size,
                    'sha256':hashlib.sha256(SOFTWARE_PYTHON.read_bytes()).hexdigest()}
            from test_native_scope import software_scope
            binding = software_scope(root, versions={'houdini':'21.0.631','nuke':'17.0v1'},project_color=color,
                hosts={key:dict(binary) for key in ('hython','nuke','husk','supervisor_python')})
            path = Path(binding['path'])
            accounting_before = (root/'native-scope-state.json').read_bytes()
            policy = {'policy':'controlled_output_v1', 'scene_variant':'sphere_ground_v2',
                'resolution':[128,128], 'frames':[1], 'channels':['R','G','B','A']}
            h = dict(self.config(task,'houdini',SOFTWARE_PYTHON,task), native_scope=binding, output_acceptance=policy, project_color=color)
            n = dict(self.config(task,'nuke',SOFTWARE_PYTHON,task), native_scope=binding, project_color=color)
            kwargs = dict(controller_root=task/'control', repo_root=ROOT, allow_software_processes=True)
            configs = validate_deployments(h,n,**kwargs)
            for config in configs:
                self.assertEqual(config['resource_budget']['native_scope'], binding)
                self.assertEqual(config['resource_budget']['roots'], [str(root)])
            self.assertEqual((root/'native-scope-state.json').read_bytes(),accounting_before)
            from vfx_pipeline.graph_jobs import GraphJobService
            jobs = GraphJobService(task/'jobs', ROOT, str(SOFTWARE_PYTHON),
                scheduler_root=task/'scheduler', resource_budget=configs[0]['resource_budget'])
            self.assertEqual(jobs.resource_budget, configs[0]['resource_budget'])
            jobs.close()
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_SCHEDULER_REQUIRED'):
                GraphJobService(task/'missing-scheduler-jobs', ROOT, str(SOFTWARE_PYTHON),
                    resource_budget=configs[0]['resource_budget'])
            output = task/'deployment.json'
            configured = subprocess.run([str(SOFTWARE_PYTHON), str(ROOT/'tools/configure_production_hosts.py'),
                '--output',str(output),'--task-root',str(task),'--houdini-executable',str(SOFTWARE_PYTHON),
                '--nuke-executable',str(SOFTWARE_PYTHON),'--python-executable',str(SOFTWARE_PYTHON),
                '--houdini-version','21.0.631','--max-bytes','536870912','--session-seconds','120',
                '--native-scope',str(path),'--controlled-output','--husk-executable',str(SOFTWARE_PYTHON),
                '--husk-sha256',binary['sha256'],'--project-id','scope-test',
                '--project-colorspace','ACEScg'], capture_output=True, text=True,
                env=dict(os.environ, PYTHONPATH=os.pathsep.join(str(ROOT/'packages'/name/'src')
                    for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'))), timeout=10)
            self.assertEqual(configured.returncode,0,configured.stderr)
            self.assertFalse(json.loads(configured.stdout)['host_started'])
            deployment = json.loads(output.read_text())
            self.assertEqual(deployment['houdini']['native_scope'],binding)
            self.assertEqual(deployment['nuke']['resource_budget']['native_scope'],binding)
            with mock.patch('houdini_bridge.task_host.start', return_value=0) as start:
                production_hosts._launch_h(configs[0],task/'host','t',task/'control',task/'scheduler',ROOT)
            self.assertEqual(start.call_args.args[0].resource_budget, configs[0]['resource_budget'])
            from houdini_bridge import task_host as h_host
            from nuke_bridge import task_host as n_host
            h_args = start.call_args.args[0]
            with mock.patch('dcc_task_runtime.owned_process.launch', side_effect=RuntimeError('scope-launch-boundary')) as launch:
                with self.assertRaisesRegex(RuntimeError, 'scope-launch-boundary'):
                    h_host.start(h_args)
            self.assertEqual(launch.call_args.kwargs['scope_role'],'houdini-host')
            self.assertIs(launch.call_args.kwargs['scope_heavy'],False)
            with mock.patch('dcc_task_runtime.owned_process.launch', side_effect=RuntimeError('scope-launch-boundary')) as launch:
                with self.assertRaisesRegex(RuntimeError, 'scope-launch-boundary'):
                    n_host.start(task_id='t',task_root=task,nuke_executable=SOFTWARE_PYTHON,
                        addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=SOFTWARE_PYTHON,
                        resource_budget=configs[1]['resource_budget'],ledger_root=task/'ledger',scheduler_root=task/'scheduler')
            self.assertEqual(launch.call_args.kwargs['scope_role'],'nuke-host')
            self.assertIs(launch.call_args.kwargs['scope_heavy'],False)
            plain_n = self.config(task,'nuke',SOFTWARE_PYTHON,task)
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_DEPLOYMENT_MISMATCH'):
                validate_deployments(h,plain_n,**kwargs)
            with self.assertRaisesRegex(ValueError, 'CONTROLLED_OUTPUT_REQUIRED'):
                validate_deployments({key:value for key,value in h.items() if key!='output_acceptance'},n,**kwargs)
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_BUDGET_INVALID'):
                validate_deployments(dict(h,resource_budget={'roots':[str(task)],'max_bytes':512*1024*1024+1}),n,**kwargs)
            with self.assertRaisesRegex(ValueError, 'OUTSIDE_NATIVE_SCOPE'):
                production_hosts.native_scope_budget(binding,configs[0]['resource_budget'],root.parent/'outside-scheduler')
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_VERSION_MISMATCH'):
                validate_deployments(dict(h,version='22.0.459'),n,**kwargs)
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_PROJECT_COLOR_MISMATCH'):
                validate_deployments(dict(h,project_color={**color,'project_id':'another-project'}),n,**kwargs)
            with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_CHANGED'):
                validate_deployments(dict(h,native_scope={**binding,'sha256':'0'*64}),n,**kwargs)

    def test_missing_budget_and_unapproved_software_refused_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();exe=SOFTWARE_PYTHON;h=self.config(root,'houdini',exe,root);n=self.config(root,'nuke',exe,root)
            with self.assertRaisesRegex(ValueError,'NOT_AUTHORIZED'):
                validate_deployments(h,n,controller_root=root,repo_root=ROOT)
            n=dict(n,resource_budget={})
            with mock.patch('dcc_task_runtime.owned_process.launch',side_effect=AssertionError('must not launch')):
                with self.assertRaisesRegex(ValueError,'DISK_BUDGET_REQUIRED'):
                    ensure_hosts(h,n,task_id='t',controller_root=root,repo_root=ROOT,scheduler_root=root/'sched',allow_software_processes=True)

    def test_software_launch_script_requires_explicit_authorization_and_valid_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();script=root/'软件 bootstrap.py';script.write_text(HYTHON,encoding='utf-8')
            h=self.config(root,'houdini',script,root);n=self.config(root,'nuke',SOFTWARE_PYTHON,root)
            for allowed in (False,None,1,'yes'):
                with self.subTest(allowed=allowed),self.assertRaisesRegex(ValueError,'NOT_AUTHORIZED'):
                    validate_deployments(h,n,controller_root=root,repo_root=ROOT,allow_software_processes=allowed)
            for path in ('relative.py',str(root),str(root/'missing.py'),None,''):
                with self.subTest(path=path),self.assertRaisesRegex(ValueError,'SOFTWARE_LAUNCH_SCRIPT_INVALID'):
                    validate_deployments(dict(h,software_launch_script=path),n,controller_root=root,repo_root=ROOT,allow_software_processes=True)
            with mock.patch.object(Path,'is_symlink',lambda path:path==script):
                with self.assertRaisesRegex(ValueError,'SOFTWARE_LAUNCH_SCRIPT_INVALID'):
                    validate_deployments(h,n,controller_root=root,repo_root=ROOT,allow_software_processes=True)

    def test_real_hosts_reject_software_fields_even_when_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();exe=SOFTWARE_PYTHON
            h=dict(self.config(root,'houdini',exe,root),evidence_source='real_host')
            n=dict(self.config(root,'nuke',exe,root),evidence_source='real_host');n.pop('software_api_dir')
            for kind,config in (('houdini',h),('nuke',n)):
                for field in ('software_api_dir','software_launch_script'):
                    for value in (None,'',False):
                        with self.subTest(kind=kind,field=field,value=value),self.assertRaisesRegex(ValueError,'IN_PRODUCTION'):
                            production_hosts._validate(dict(config,**{field:value}),kind,root,ROOT,True)

    def test_software_launch_content_is_bound_to_deployment_and_launcher(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();script=root/'软件 bootstrap.py';script.write_text(HYTHON,encoding='utf-8')
            h=self.config(root,'houdini',script,root);n=self.config(root,'nuke',SOFTWARE_PYTHON,root)
            kwargs=dict(controller_root=root,repo_root=ROOT,allow_software_processes=True)
            configs=validate_deployments(h,n,**kwargs)
            self.assertEqual(configs[0]['executable'],str(SOFTWARE_PYTHON))
            self.assertEqual(configs[0]['supervisor_executable'],str(SOFTWARE_PYTHON))
            self.assertEqual(configs[0]['software_launch_script_sha256'],hashlib.sha256(script.read_bytes()).hexdigest())
            fingerprint=hashlib.sha256(json.dumps(configs,sort_keys=True).encode()).hexdigest()
            production_hosts._atomic(root/'production-hosts.json',{'task_id':'t','config_sha256':fingerprint,'hosts':{}})
            with mock.patch('houdini_bridge.task_host.start',return_value=0) as start:
                production_hosts._launch_h(configs[0],root/'host','t',root,root/'scheduler',ROOT)
            args=start.call_args.args[0]
            self.assertEqual(args.software_launch_script,str(script))
            self.assertEqual(args.software_launch_script_sha256,configs[0]['software_launch_script_sha256'])
            self.assertIs(args.allow_software_processes,True)
            self.assertEqual(args.evidence_source,'software_test')
            script.write_text(HYTHON+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'SCRIPT_CHANGED'):
                validate_deployments(configs[0],n,**kwargs)
            with mock.patch('dcc_task_runtime.owned_process.launch',side_effect=AssertionError('must not launch')):
                with self.assertRaisesRegex(ValueError,'DEPLOYMENT_CHANGED'):
                    ensure_hosts(h,n,task_id='t',scheduler_root=root/'scheduler',**kwargs)

if __name__=='__main__':unittest.main()
