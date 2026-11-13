#!/usr/bin/env python3
"""Frozen H21 engineering closure driver. Default is read-only preflight."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
sys.dont_write_bytecode = True
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT/'packages'/package/'src'))
PLAN = {'schema':'bridge.controlled-engineering.plan/1', 'domain_pack':'material_lookdev_v1',
        'scene_profile':'sphere_ground_v2', 'resolution':[128,128], 'frames':[1], 'request_prefix':'engineering_h21'}
PREFIX = 'engineering_h21'
ROLE_COUNTS = {'alpha-husk':1,'alpha-nuke':1,'houdini-host':2,'nuke-host':1,
               'graph-worker':1,'main-husk':1,'nuke-render':1}


def selected_plan(scope):
    from dcc_task_runtime.render_profiles import OFFICIAL
    if scope.get('scene_profile')==OFFICIAL:
        return dict(PLAN,domain_pack='lighting_camera_render_v1',scene_profile=OFFICIAL,resolution=[420,300])
    return dict(PLAN)


def selected_roles(scope):
    from dcc_task_runtime.render_profiles import OFFICIAL
    roles=dict(ROLE_COUNTS)
    if scope.get('scene_profile')==OFFICIAL:
        roles.update({'official-open-save':1,'official-cold-export':1,'official-husk':1})
    return roles


class RegistrationPending(Exception):
    def __init__(self,phase,operation_id,fact,error):
        self.phase,self.operation_id,self.fact=phase,operation_id,fact
        super().__init__(str(error))


def _pending_result(journal,error):
    pending={'phase':error.phase,'operation_id':error.operation_id,'error':str(error),
        'original_fact_sha256':hashlib.sha256(canonical(error.fact)).hexdigest()}
    journal.value['registration_pending']=pending;journal.save()
    return {'schema':'bridge.controlled-engineering.result/1','state':'REGISTRATION_PENDING',
        'machine_checks':{'state':'REGISTRATION_PENDING'},'human_review':'PENDING',**pending}


def tool_module(name):
    path = ROOT/'tools'/(name+'.py')
    spec = importlib.util.spec_from_file_location('engineering_'+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def load(path):
    return _alpha_module().load(path)


def _alpha_module():
    return tool_module('run_alpha_calibration')


def _evidence_source(scope,bindings):
    source=bindings.get('evidence_source')
    if source not in ('real_host','software_test') or scope.get('evidence_source','real_host')!=source:
        raise ValueError('ENGINEERING_EVIDENCE_SOURCE_MISMATCH')
    return source


def _alpha_original(scope, bindings, scope_sha, bindings_sha):
    from dcc_task_runtime.alpha_calibration import validate_alpha_calibration
    path=Path(scope['output_root'])/'alpha-calibration-result.json'
    result=load(path)
    if (result.get('schema')!='bridge.alpha-runner.result/1'
            or result.get('scope_sha256')!=scope_sha or result.get('bindings_sha256')!=bindings_sha):
        raise ValueError('ENGINEERING_ALPHA_ORIGINAL_BINDING_MISMATCH')
    calibrated=validate_alpha_calibration(result['alpha_calibration'],expected_version='21.0.631',
        expected_plugin_build=bindings['plugin_build'],expected_route_sha256=bindings['route_sha256'],
        evidence_source=_evidence_source(scope,bindings))
    if result.get('calibration')!=calibrated:
        raise ValueError('ENGINEERING_ALPHA_ORIGINAL_CHANGED')
    return result


def _project_inputs(alpha, scope, bindings):
    root=alpha.plain(scope['output_root'])
    project=alpha.plain(bindings['project_root'])
    control=alpha.plain(bindings['controller_root'])
    if project!=root/'project' or control!=project/'control':
        raise ValueError('ENGINEERING_PROJECT_ROOT_INVALID')
    outputs={'houdini_pattern':str(project/'saves/main.%04d.exr'),
             'nuke_pattern':str(project/'saves/nuke.%04d.exr'), 'nuke_script':str(project/'saves/composite.nk')}
    if bindings.get('outputs')!=outputs or bindings.get('main_plan')!=selected_plan(scope):
        raise ValueError('ENGINEERING_FROZEN_PLAN_INVALID')
    if alpha.load(alpha.checked(bindings['driver_plan'],2*1024*1024))!=selected_plan(scope):
        raise ValueError('ENGINEERING_DRIVER_PLAN_CHANGED')
    files=bindings.get('project_files')
    expected={'manifest':control/'run.json','snapshot_manifest':control/'snapshot-manifest.json','server':control/'server.py'}
    if not isinstance(files,dict) or set(files)!=set(expected):
        raise ValueError('ENGINEERING_PROJECT_FILES_REQUIRED')
    for name,path in expected.items():
        if alpha.checked(files[name],8*1024*1024)!=path:
            raise ValueError('ENGINEERING_PROJECT_FILE_BINDING_MISMATCH')
    snapshot=control/'snapshot'
    index=alpha.load(expected['snapshot_manifest'])
    for record in index['files']:
        path=snapshot/record['path']
        if not path.resolve().is_relative_to(snapshot) or alpha.file_record(path)['sha256']!=record['sha256']:
            raise ValueError('ENGINEERING_FROZEN_SNAPSHOT_CHANGED')
    sources=bindings['source_freeze']
    for name in ('run_controlled_engineering','run_alpha_calibration','verify_controlled_output','prepare_nuke_project',
                 'activate_controlled_engineering'):
        path=ROOT/'tools'/(name+'.py')
        if sources.get(str(path))!=alpha.file_record(path)['sha256']:
            raise ValueError('ENGINEERING_FROZEN_TOOL_REQUIRED:'+name)
    for path,digest in sources.items():
        if alpha.file_record(path)['sha256']!=digest:
            raise ValueError('ENGINEERING_FROZEN_SOURCE_CHANGED')
    manifest=alpha.load(expected['manifest'])
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    diagnostic=scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES
    if (manifest.get('construction_authorized') is not True or manifest.get('execution_authorized') is not (not diagnostic)
            or manifest.get('render_authorized') is not (not diagnostic) or manifest.get('simulation_authorized') is True
            or manifest.get('cache_authorized') is True or manifest.get('application')!='pipeline'):
        raise ValueError('ENGINEERING_CONTROLLER_PROFILE_INVALID')
    from dcc_task_runtime.render_profiles import OFFICIAL
    pending=False
    if selected_plan(scope)['scene_profile']==OFFICIAL:
        from houdini_bridge.official_karma_inputs import frozen_context,resolve_manifest,derivation_rule
        record=alpha.file_record(root/'runtime-bindings.json')
        if diagnostic:
            from dcc_task_runtime.native_scope import NativeScope
            from houdini_bridge.official_karma_worker import check_frozen_case
            case=check_frozen_case(NativeScope({'path':str(root/'scope.json'),'sha256':bindings['scope_sha256']}))
            if (bindings.get('deployments')!={} or 'production_host' in manifest or 'production_nuke' in manifest
                    or 'construction_input_manifest' in manifest or manifest.get('official_case_derivation')!=derivation_rule(root)):
                raise ValueError('OFFICIAL_DIAGNOSTIC_GRAPH_EXECUTION_FORBIDDEN')
            if any(Path(v).exists() for k,v in derivation_rule(root).items() if k in ('manifest_path','seal_path','binding_path','configuration_path')):
                raise ValueError('OFFICIAL_DIAGNOSTIC_DERIVED_INPUT_FORBIDDEN')
            pending=True
        else:
            context=frozen_context(expected['manifest'],record)
            pending=not Path(context[4]['binding_path']).exists()
            if not pending:
                manifest=alpha.load(resolve_manifest(expected['manifest'],record))
    frozen=manifest.get('construction_input_manifest')
    from vfx_pipeline.graph_construction_inputs import render_scene_configuration
    configuration=render_scene_configuration(frozen,'21.0.631') if not pending else None
    plan=selected_plan(scope)
    if not pending and (configuration is None or configuration['profile']!=plan['scene_profile']
            or configuration['scene']['resolution']!=plan['resolution'] or configuration['scene']['frames']!=[1]):
        raise ValueError('ENGINEERING_FROZEN_SCENE_REQUIRED')
    return {'root':root,'project':project,'control':control,'snapshot':snapshot,'outputs':outputs,
            'manifest':manifest,'official_derivation_pending':pending}


def preflight(scope_path, bindings_path):
    alpha=_alpha_module()
    blockers=[];data={};completed=False
    try:
        scope=alpha.load(scope_path);bindings=alpha.load(bindings_path)
        scope_sha=alpha.file_record(scope_path,2*1024*1024)['sha256']
        bindings_sha=alpha.file_record(bindings_path,2*1024*1024)['sha256']
        from dcc_task_runtime.process_image import scope_collector_policy
        for record in scope_collector_policy(scope)['tools'].values():alpha.checked(record)
        if (Path(scope['output_root'])/'alpha-calibration-result.json').exists():
            _alpha_original(scope,bindings,scope_sha,bindings_sha)
            completed=True
    except (ValueError,OSError,KeyError,TypeError) as error:
        blockers.append(str(error))
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    if not blockers and scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES:
        try:
            budget=alpha.ScopeBudget(scope_path,bindings_path)
            budget.available(starts=1)
            alpha.validate_inventory(bindings['native_start_inventory'],scope)
            report={'blockers':[],'scope_sha256':scope_sha,'bindings_sha256':bindings_sha}
            data={'scope':scope,'bindings':bindings}
        except (ValueError,OSError,KeyError,TypeError) as error:
            report={'blockers':[str(error)],'scope_sha256':scope_sha,'bindings_sha256':bindings_sha}
    else:
        report,data=alpha.preflight(scope_path,bindings_path,allow_completed=completed)
    blockers.extend(report['blockers'])
    try:
        scope=alpha.load(scope_path);bindings=alpha.load(bindings_path)
        paths=_project_inputs(alpha,scope,bindings)
        data.update(scope=scope,bindings=bindings,**paths)
        if ROOT!=paths['snapshot']:
            raise ValueError('ENGINEERING_USE_FROZEN_PROJECT_ENTRY')
    except (ValueError,OSError,KeyError,TypeError) as error:
        blockers.append(str(error))
    query_only=bool(blockers) and all(value=='NATIVE_SCOPE_HEAVY_BUSY' for value in blockers)
    result={'schema':'bridge.controlled-engineering.preflight/1',
        'state':'QUERY_REQUIRED' if query_only else 'BLOCKED' if blockers else 'PREPARED',
        'blockers':blockers,'scope_sha256':report.get('scope_sha256'),
        'bindings_sha256':report.get('bindings_sha256'),'native_execution_status':'NOT_RUN',
        'human_visual_review':'PENDING','alpha_original_reauthenticated':completed,
        'official_derivation_pending':data.get('official_derivation_pending',False),
        'execution_mode':data.get('scope',{}).get('execution_mode'),
        'permitted_native_starts':data.get('scope',{}).get('budget',{}).get('max_dcc_starts')}
    return result,data


class StageJournal:
    """Intent precedes dispatch. An interrupted intent is never automatically replayed."""
    def __init__(self,path,scope_sha,bindings_sha):
        self.path=Path(path)
        self.binding={'scope_sha256':scope_sha,'bindings_sha256':bindings_sha}
        if self.path.exists():
            self.value=load(self.path)
            if self.value.get('schema')!='bridge.engineering-driver-state/1' or any(self.value.get(k)!=v for k,v in self.binding.items()):
                raise ValueError('ENGINEERING_STAGE_BINDING_CHANGED')
            if not isinstance(self.value.get('stages'),dict): raise ValueError('ENGINEERING_STAGE_INVALID')
        else:
            self.value={'schema':'bridge.engineering-driver-state/1',**self.binding,'stages':{}}
        self.existing=self.path.exists()

    def save(self):
        from dcc_task_runtime.platform_support import atomic_write
        atomic_write(self.path,canonical(self.value),owned_root=self.path.parent)

    def intent(self,name,request):
        existing=self.value['stages'].get(name)
        if existing is not None:
            raise ValueError('ENGINEERING_QUERY_REQUIRED:'+name)
        self.value['stages'][name]={'state':'INTENT','request':request}
        self.save()

    def done(self,name,result):
        record=self.value['stages'].get(name)
        if not record or record['state']!='INTENT': raise ValueError('ENGINEERING_STAGE_INVALID')
        record.update(state='DONE',result=result,result_sha256=hashlib.sha256(canonical(result)).hexdigest())
        self.save()

    def result(self,name):
        record=self.value['stages'].get(name) or {}
        if record.get('state')!='DONE': raise ValueError('ENGINEERING_QUERY_REQUIRED:'+name)
        result=record['result']
        if record.get('result_sha256')!=hashlib.sha256(canonical(result)).hexdigest():
            raise ValueError('ENGINEERING_STAGE_RESULT_CHANGED')
        return result


class Controller:
    """Only the generated public stdio MCP entry; no alternate host or RPC route."""
    def __init__(self,data,budget):
        self.data,self.budget=data,budget
        self.sequence=0;self.lines=queue.Queue();self.log_bytes=0;self.error=None
        self.log_lock=threading.Lock()
        self.log=data['root']/'engineering-controller.log'
        command=[data['scope']['hosts']['supervisor_python']['path'],'-I','-B',str(data['control']/'server.py'),'--backend','production']
        from dcc_task_runtime.render_profiles import OFFICIAL
        if selected_plan(data['scope'])['scene_profile']==OFFICIAL:
            if data.get('official_derivation_pending'):
                raise ValueError('OFFICIAL_SEALED_DERIVATION_REQUIRED_BEFORE_GRAPH')
            record=_alpha_module().file_record(data['bindings_path'])
            command.extend(['--official-bindings',record['path'],'--official-bindings-bytes',str(record['bytes']),
                '--official-bindings-sha256',record['sha256']])
        if _evidence_source(data['scope'],data['bindings'])=='software_test':
            command.append('--software-processes')
        environment=dict(data['bindings']['environment'],PYTHONPATH='',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        self.process=subprocess.Popen(command,cwd=data['project'],env=environment,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',start_new_session=True)
        for stream,is_output in ((self.process.stdout,True),(self.process.stderr,False)):
            threading.Thread(target=self._read,args=(stream,is_output),daemon=True).start()
        try:
            self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'controlled-engineering'}})
            self.process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n')
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise

    def _read(self,stream,is_output):
        try:
            for line in iter(stream.readline,''):
                logged=line
                if is_output:
                    try: message=json.loads(line)
                    except ValueError: message=None
                    if isinstance(message,dict):
                        logged=json.dumps({'stream':'stdout','id':message.get('id'),
                            'method':message.get('method'),'bytes':len(line.encode()),
                            'sha256':hashlib.sha256(line.encode()).hexdigest()},sort_keys=True)+'\n'
                with self.log_lock:
                    self.log_bytes+=len(logged.encode())
                    if self.log_bytes>1024*1024:
                        self.error='ENGINEERING_CONTROLLER_LOG_BUDGET';return
                    with self.log.open('a',encoding='utf-8') as output: output.write(logged)
                if is_output:self.lines.put(line)
        finally:
            if is_output:self.lines.put(None)

    def rpc(self,method,params):
        self.sequence+=1;request_id=self.sequence
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params},ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        deadline=time.monotonic()+min(120.,self.budget.remaining())
        while time.monotonic()<deadline:
            self.budget.native.check()
            if self.error: raise ValueError(self.error)
            try: line=self.lines.get(timeout=.1)
            except queue.Empty: continue
            if line is None: raise ValueError(self.error or 'ENGINEERING_CONTROLLER_CLOSED')
            reply=json.loads(line)
            if reply.get('id')!=request_id:continue
            if 'error' in reply: raise ValueError('ENGINEERING_MCP_ERROR:'+str(reply['error']))
            return reply['result']
        raise TimeoutError('ENGINEERING_MCP_TIMEOUT')

    def tool(self,name,arguments):
        result=self.rpc('tools/call',{'name':name,'arguments':arguments})
        if result.get('isError'):raise ValueError('ENGINEERING_TOOL_REJECTED:'+name+':'+str(result.get('content')))
        content=result.get('content') or []
        if len(content)!=1 or content[0].get('type')!='text':raise ValueError('ENGINEERING_MCP_RESULT_INVALID')
        return json.loads(content[0]['text'])

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:raise ValueError('ENGINEERING_CONTROLLER_STOP_UNKNOWN')
        for stream in (self.process.stdout,self.process.stderr):
            if stream and not stream.closed:stream.close()
        if self.process.returncode!=0:raise ValueError('ENGINEERING_CONTROLLER_NONZERO_EXIT')


def metadata_observations(data,catalog):
    """Only file identity and PNG header facts; never invent visual analysis."""
    assets={item['asset_id']:item for item in data['manifest']['assets']}
    result=[]
    alpha=_alpha_module()
    for item in catalog['assets']:
        asset_id=item['asset_id'];declared=assets[asset_id]
        path=(data['control']/declared['file']).resolve()
        if not path.is_relative_to(data['project']):raise ValueError('ENGINEERING_ASSET_OUTSIDE_PROJECT')
        actual=alpha.file_record(path,16*1024*1024)
        if actual['sha256']!=declared['sha256']:raise ValueError('ENGINEERING_ASSET_CHANGED')
        with path.open('rb') as stream:header=stream.read(24)
        if header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':raise ValueError('ENGINEERING_PNG_METADATA_REQUIRED')
        width,height=struct.unpack('>II',header[16:24])
        result.append({'asset_id':asset_id,'request_id':PREFIX+'_metadata_'+str(len(result)),
            'observation':{'description':f'metadata_only; no visual/model analysis; asset_id={asset_id}; PNG={width}x{height}; sha256={actual["sha256"]}'}})
    if set(assets)!={item['asset_id'] for item in catalog['assets']}:raise ValueError('ENGINEERING_CATALOG_CHANGED')
    return result


def _poll(controller,tool,arguments,state_path,done,registration_pending=None):
    deadline=time.monotonic()+min(120.,controller.budget.remaining())
    while time.monotonic()<deadline:
        result=controller.tool(tool,arguments)
        state=result
        for key in state_path:state=state[key]
        operation=result.get('operation') or {}
        if (registration_pending is not None and state in ('NEEDS_RECONCILE','COMPLETED')
                and operation.get('ledger_state')=='PENDING'):
            registration_pending(result)
        if state==done:return result
        if state not in ('PREPARED','STARTING','RUNNING','READY','QUEUED','ACTIVE','SUBMITTED','RENDERING'):
            raise ValueError('ENGINEERING_OPERATION_NOT_SUCCESSFUL:'+str(state))
        time.sleep(.05)
    raise TimeoutError('ENGINEERING_OPERATION_TIMEOUT')


def _stop_host(data,kind):
    from dcc_task_runtime.owned_process import execution_returncode, read_receipt
    saved=load(data['control']/'production-hosts.json')
    config=saved['hosts'][kind]
    if config.get('native_scope')!={'path':str(data['scope_path']),'sha256':data['scope_sha256']}:
        raise ValueError('ENGINEERING_HOST_SCOPE_MISMATCH')
    if kind=='houdini':
        import contextlib,io
        from argparse import Namespace
        from houdini_bridge.task_host import stop
        with contextlib.redirect_stdout(io.StringIO()):
            code=stop(Namespace(work_dir=config['work_dir'],timeout=3,exit_grace=3))
        if code!=0:raise ValueError('ENGINEERING_HOUDINI_STOP_UNKNOWN')
        binding=load(Path(config['work_dir'])/'supervisor-binding.json')
        observed=read_receipt(binding['directory'],'stopped',identity=binding['identity'])
    else:
        from nuke_bridge.task_host import stop
        result=stop(config['work_dir'])
        if not result.get('stopped'):raise ValueError('ENGINEERING_NUKE_STOP_UNKNOWN')
        observed=result['receipt']
    if not observed or execution_returncode(observed)!=0:raise ValueError('ENGINEERING_HOST_NONZERO_STOP')
    return {'kind':kind,'stopped_sha256':hashlib.sha256(canonical(observed)).hexdigest(),'task_id':saved['task_id']}


def _nuke_addon(data):
    saved=load(data['control']/'production-hosts.json')
    config=saved['hosts']['nuke']
    expected=Path(config['task_root'])/'state/nuke_renders'
    if config.get('render_records_root')!=str(expected):
        raise ValueError('ENGINEERING_NUKE_RECORD_ROOT_MISMATCH')
    path=ROOT/'plugins/nuke/nuke_bridge_addon.py'
    spec=importlib.util.spec_from_file_location('engineering_nuke_receipts',path)
    addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
    addon._RENDER_RECORDS_DIR=expected
    return addon


def _nuke_original(data,operation_id):
    """Read the shipped producer projection from its persisted original, without Nuke."""
    saved=load(data['control']/'production-hosts.json')
    addon=_nuke_addon(data)
    fact=addon._nuke_operation_fact(operation_id)
    if (not fact or fact.get('task_id')!=saved['task_id'] or fact.get('stop_confirmed') is not True
            or fact.get('completion_metadata_status')!='AVAILABLE' or fact.get('frame_set')!=[1]
            or fact.get('output_pattern')!=data['outputs']['nuke_pattern']):
        raise ValueError('ENGINEERING_NUKE_ORIGINAL_REQUIRED')
    from nuke_bridge.operation_receipts import completed_operation_projection
    projection=completed_operation_projection(fact.get('formal_receipt'),fact)
    if not projection or projection.get('completion_metadata_status')!='AVAILABLE':
        raise ValueError('ENGINEERING_NUKE_RECEIPT_INVALID')
    return fact


def _houdini_original(data,operation_id):
    from vfx_pipeline.workbuddy_assembly import production_host_client
    saved=load(data['control']/'production-hosts.json')
    client=production_host_client(saved['hosts']['houdini'],data['control']/'host-state')
    client.bind_task(saved['task_id'])
    verification_id=PREFIX+'_verify'
    original=Path(client.boundary_binding_path).with_name('verified-output-'+verification_id+'.json')
    if not original.is_file() or original.is_symlink():
        raise ValueError('ENGINEERING_HOUDINI_VERIFICATION_ORIGINAL_REQUIRED')
    fact=client.call('output.verify.status',{'task_id':saved['task_id'],
        'verification_id':verification_id})['execution_fact']
    if (fact.get('schema')!='bridge.houdini.controlled-output/1.0'
            or fact.get('state')!='COMPLETED' or fact.get('stop_confirmed') is not True
            or fact.get('operation_id')!=verification_id or fact.get('parent_operation_id')!=operation_id
            or fact.get('verification_basis')!='controlled_output_v1'
            or fact.get('completion_metadata_status')!='AVAILABLE' or fact.get('task_id')!=saved['task_id']
            or fact.get('frame_set')!=[1] or fact.get('output_pattern')!=data['outputs']['houdini_pattern']):
        raise ValueError('ENGINEERING_HOUDINI_VERIFICATION_ORIGINAL_REQUIRED')
    return fact


def _verify_registered(data,journal):
    operation_id=journal.result('render')['operation_id']
    try:
        return tool_module('verify_controlled_output').resume(data['project'],operation_id,
            PREFIX+'_verify',PREFIX+'_main',alpha_result_path=data['root']/'alpha-calibration-result.json')
    except Exception as error:
        # A stopped raw render alone cannot prove controlled verification.
        # Only an existing reauthenticated verification allows ledger retry.
        try:fact=_houdini_original(data,operation_id)
        except Exception:raise error
        raise RegistrationPending('houdini',operation_id,fact,error) from error


def _nuke_pending(data,operation_id):
    fact=_nuke_original(data,operation_id)
    if fact.get('execution_fact',{}).get('ledger_state')!='PENDING':
        raise ValueError('ENGINEERING_NUKE_PENDING_ORIGINAL_REQUIRED')
    raise RegistrationPending('nuke',operation_id,fact,'original stopped execution awaits ledger registration')


def _register_existing_nuke(data,operation_id,fact):
    if fact.get('execution_fact',{}).get('ledger_state')!='PENDING':
        raise ValueError('ENGINEERING_NUKE_PENDING_ORIGINAL_REQUIRED')
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    from vfx_pipeline.graph_scheduler import GraphScheduler
    saved=load(data['control']/'production-hosts.json')
    original=_nuke_original(data,operation_id)
    if (original.get('formal_receipt')!=fact.get('formal_receipt')
            or (saved['hosts']['nuke'].get('evidence_source')=='real_host'
                and original.get('execution_kind')!='owned_subprocess')):
        raise ValueError('ENGINEERING_NUKE_PENDING_ORIGINAL_CHANGED')
    addon=_nuke_addon(data)
    registry=ArtifactRegistry(data['control']/'artifact_ledger')
    provenance=original.get('output_verification') or {}
    def operation_source(identifier):
        if identifier==operation_id:return addon._nuke_operation_fact(identifier)
        if identifier==provenance.get('origin_verification_operation_id') and identifier==PREFIX+'_verify':
            return _houdini_original(data,provenance['origin_render_operation_id'])
        return None
    registry.set_operation_source(operation_source)
    addon._NUKE_ARTIFACT_REGISTRY=registry
    addon._NUKE_SCHEDULER=GraphScheduler(data['root']/'scheduler')
    action='complete_recovered'
    secret=addon._fx_approval_secret_value()
    signature=hmac.new(secret.encode(),canonical({'action':action,'task_id':operation_id}),hashlib.sha256).hexdigest()
    return addon.nuke_render_resolve(action,operation_id,
        {'verified_by':'frozen engineering controller: original signed stop and typed execution reauthenticated',
         'signature':signature})


def _input_identity(entry):
    """Freeze the ledger version, producer receipt and original input bytes."""
    return {key:entry.get(key) for key in ('artifact_id','version','task_id','operation_id',
        'operation_receipt_sha256','pattern','frame_set','payload','project_color',
        'output_verification','registry_operation_receipt')}


def _tail_admission(data,budget,*,require_nuke=False):
    from dcc_task_runtime import owned_process
    from dcc_task_runtime.platform_support import process_identity
    from vfx_pipeline.workbuddy_assembly import production_nuke_client
    budget.native.check()
    saved=load(data['control']/'production-hosts.json')
    config=saved['hosts'].get('nuke')
    state=budget.available(starts=1 if config else 2)
    expected=Counter(selected_roles(data['scope']));expected.pop('nuke-render')
    if config is None:expected.pop('nuke-host')
    if (Counter(ticket['role'] for ticket in state['tickets'])!=expected
            or state['dcc_starts']!=sum(expected.values())):
        raise ValueError('ENGINEERING_CONTINUATION_TICKETS_MISMATCH')
    if any(ticket.get('stopped_at') is None for ticket in state['tickets'] if ticket['role']!='nuke-host'):
        raise ValueError('ENGINEERING_CONTINUATION_PRIOR_STOP_UNKNOWN')
    if config is None:
        if require_nuke:raise ValueError('ENGINEERING_CONTINUATION_NUKE_HOST_MISSING')
        return None
    binding={'path':str(data['scope_path']),'sha256':data['scope_sha256']}
    if config.get('native_scope')!=binding:
        raise ValueError('ENGINEERING_CONTINUATION_HOST_SCOPE_MISMATCH')
    ticket=next(ticket for ticket in state['tickets'] if ticket['role']=='nuke-host')
    if ticket.get('stopped_at') is not None:
        raise ValueError('ENGINEERING_CONTINUATION_NUKE_HOST_STOPPED_NO_RESTART')
    work=Path(config['work_dir'])
    launch=load(work/'launch.json')
    if (ticket['directory']!=str(work/'supervisor') or ticket['identity']!=launch['identity']
            or any(config['expected_identity'].get(key)!=value for key,value in ticket['identity'].items())):
        raise ValueError('ENGINEERING_CONTINUATION_HOST_TICKET_MISMATCH')
    started=owned_process.read_receipt(ticket['directory'],'started',identity=ticket['identity'])
    stopped=owned_process.read_receipt(ticket['directory'],'stopped',identity=ticket['identity'])
    if (not started or stopped is not None or started['pid']!=config['expected_identity'].get('pid')):
        raise ValueError('ENGINEERING_CONTINUATION_NUKE_STOP_UNKNOWN')
    observed=process_identity(started['pid'])
    if (observed.get('state')!='alive' or (started.get('process_birth') is not None
            and observed.get('birth')!=started['process_birth'])):
        raise ValueError('ENGINEERING_CONTINUATION_NUKE_PROCESS_UNKNOWN')
    client=production_nuke_client(config,data['control']/'nuke-state')
    client.bind_task(saved['task_id']);client.health()
    return {'directory':ticket['directory'],'identity':ticket['identity']}


class ExistingNukeController:
    """Public GraphRun services attached to the existing task host; no host factory."""
    def __init__(self,data,budget):
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        from vfx_pipeline.workbuddy_assembly import production_host_client,production_nuke_client
        from vfx_pipeline.workbuddy_graph_mcp import GraphRun
        self.budget=budget
        saved=load(data['control']/'production-hosts.json')
        hconfig=tool_module('verify_controlled_output')._alpha_configuration(saved['hosts']['houdini'],
            data['root']/'alpha-calibration-result.json')
        host=production_host_client(hconfig,data['control']/'host-state');host.bind_task(saved['task_id'])
        nuke=production_nuke_client(saved['hosts']['nuke'],data['control']/'nuke-state');nuke.bind_task(saved['task_id'])
        nuke.health()
        registry=ArtifactRegistry(data['control']/'artifact_ledger')
        host.bind_artifact_registry(registry);nuke.bind_artifact_registry(registry)
        self.facade=GraphRun(data['control']/'run.json',None,task_id=saved['task_id'],host_client=host,
            nuke_client=nuke,artifact_registry=registry,save_root=str(data['project']/'saves'))

    def tool(self,name,arguments):
        if name not in ('consume_artifact','nuke_render_bounded','operation_query'):
            raise ValueError('ENGINEERING_CONTINUATION_TOOL_FORBIDDEN')
        self.budget.native.check()
        return getattr(self.facade,name)(**arguments)

    def close(self):
        pass


def _continue_nuke_tail(data,journal,budget):
    stages=journal.value['stages']
    if 'nuke_render' in stages:
        return _resume(data,journal,budget)
    _alpha_original(data['scope'],data['bindings'],data['scope_sha256'],data['bindings_sha256'])
    frozen=journal.result('verify')
    current=_verify_registered(data,journal)
    if _input_identity(frozen['artifact'])!=_input_identity(current['artifact']):
        raise ValueError('ENGINEERING_CONTINUATION_INPUT_CHANGED')
    prepared=stages.get('nuke_prepare')
    reconcile=bool(prepared and prepared.get('state')=='INTENT'
        and not (data['control']/'nuke-save-receipt.json').is_file())
    try:before=_tail_admission(data,budget)
    except Exception as error:
        if not reconcile:raise
        return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'ENGINEERING_NUKE_PREPARE_INTENT_UNRESOLVED','reason_detail':str(error),'human_review':'PENDING'}
    if reconcile and before is None:
        return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'ENGINEERING_NUKE_SAVE_RECONCILE_HOST_REQUIRED','human_review':'PENDING'}
    if prepared is None:journal.intent('nuke_prepare',{'script':data['outputs']['nuke_script']})
    options={'artifact_id':PREFIX+'_main','output_pattern':data['outputs']['nuke_pattern'],'frames':[1],
        'alpha_result_path':data['root']/'alpha-calibration-result.json'}
    if reconcile:options['reconcile_saved']=True
    try:
        receipt=tool_module('prepare_nuke_project').prepare_nuke_project(data['project'],Path(data['outputs']['nuke_script']),**options)
    except Exception as error:
        if not reconcile:raise
        return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'ENGINEERING_NUKE_PREPARE_INTENT_UNRESOLVED','reason_detail':str(error),'human_review':'PENDING'}
    if prepared and prepared.get('state')=='DONE':
        if journal.result('nuke_prepare')!=receipt:raise ValueError('ENGINEERING_CONTINUATION_NUKE_SAVE_CHANGED')
    else:journal.done('nuke_prepare',receipt)
    after=_tail_admission(data,budget,require_nuke=True)
    if before is not None and after!=before:
        raise ValueError('ENGINEERING_CONTINUATION_NUKE_HOST_REPLACED')
    current=_verify_registered(data,journal)
    if _input_identity(frozen['artifact'])!=_input_identity(current['artifact']):
        raise ValueError('ENGINEERING_CONTINUATION_INPUT_CHANGED')
    controller=ExistingNukeController(data,budget)
    try:
        controller.tool('consume_artifact',{'artifact_id':PREFIX+'_main'})
        journal.intent('nuke_render',{'request_id':PREFIX+'_nuke'})
        result=controller.tool('nuke_render_bounded',{'request_id':PREFIX+'_nuke','artifact_id':PREFIX+'_main',
            'pattern':data['outputs']['nuke_pattern'],'frames':[1]})
        journal.done('nuke_render',result)
        operation_id=result['operation_id']
        _poll(controller,'operation_query',{'operation_id':operation_id},('operation','state'),'COMPLETED',
            registration_pending=lambda result:_nuke_pending(data,operation_id))
    except RegistrationPending as error:return _pending_result(journal,error)
    finally:controller.close()
    return _resume(data,journal,budget)


def _resume_nuke_intent(data,journal,budget):
    """Discover only a persisted task-owned operation; an intent never dispatches."""
    from vfx_pipeline.workbuddy_assembly import production_nuke_client
    saved=load(data['control']/'production-hosts.json')
    config=saved['hosts'].get('nuke')
    unresolved={'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
        'reason':'ENGINEERING_NUKE_INTENT_UNRESOLVED_NO_REPLAY','human_review':'PENDING'}
    if config is None:return unresolved
    client=production_nuke_client(config,data['control']/'nuke-state');client.bind_task(saved['task_id'])
    addon=_nuke_addon(data)
    candidates=[]
    for operation_id,owner in client._load_operation_owners().items():
        if owner!=saved['task_id']:continue
        record=addon._load_render_record(operation_id)
        if record and record.get('request_id')==PREFIX+'_nuke':candidates.append(operation_id)
    if len(candidates)!=1:return unresolved
    operation_id=candidates[0]
    try:
        try:fact=_nuke_original(data,operation_id)
        except ValueError:
            client.call('render_status',{'task_id':operation_id})
            fact=_nuke_original(data,operation_id)
        if (fact.get('formal_receipt') or {}).get('request_id')!=PREFIX+'_nuke':return unresolved
    except Exception as error:return dict(unresolved,reason_detail=str(error),operation_id=operation_id)
    journal.done('nuke_render',{'operation_id':operation_id,'recovered_from_original':True})
    return _resume(data,journal,budget)


def _verify_engineering_images(entry,resolution=(128,128)):
    """The engineering deliverable must retain the frozen RGBA frame."""
    metadata = (entry.get('payload') or {}).get('completion_metadata')
    if not isinstance(metadata, dict) or set(metadata) != {'1'}:
        raise ValueError('ENGINEERING_IMAGE_METADATA_REQUIRED')
    image = metadata['1']
    if (not isinstance(image, dict) or image.get('width') != resolution[0] or image.get('height') != resolution[1]
            or not isinstance(image.get('channels'), list)
            or set(image['channels']) != set('RGBA') or len(image['channels']) != 4):
        raise ValueError('ENGINEERING_RGBA_OUTPUT_REQUIRED')


def _completion_scope(data,budget):
    budget.native.check();snapshot=budget.native.snapshot()
    if (snapshot['closed_reason'] or snapshot['dcc_starts']!=sum(selected_roles(data['scope']).values())
            or Counter(t['role'] for t in snapshot['tickets'])!=Counter(selected_roles(data['scope']))
            or any(t.get('stopped_at') is None for t in snapshot['tickets'])):
        raise ValueError('ENGINEERING_ALL_SIGNED_STOPS_REQUIRED')
    return snapshot


def _final_result(data,journal,budget):
    alpha=_alpha_original(data['scope'],data['bindings'],data['scope_sha256'],data['bindings_sha256'])
    verify=_verify_registered(data,journal)
    nuke_id=journal.result('nuke_render')['operation_id']
    nuke=_nuke_original(data,nuke_id)
    if nuke.get('output_verification')!=verify['artifact'].get('output_verification'):
        raise ValueError('ENGINEERING_VERIFICATION_GRADE_CHANGED')
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    registry=ArtifactRegistry(data['control']/'artifact_ledger')
    registry.set_operation_source(lambda op: verify['execution_fact'] if op==PREFIX+'_verify' else nuke if op==nuke_id else None)
    artifacts=[]
    for artifact_id in (PREFIX+'_main','nuke-render-'+nuke_id):
        entry=registry.lookup(artifact_id)
        if not entry or not registry.verify(artifact_id).get('usable'):raise ValueError('ENGINEERING_REGISTERED_OUTPUT_UNUSABLE')
        _verify_engineering_images(entry,selected_plan(data['scope'])['resolution'])
        artifacts.append({'artifact_id':artifact_id,'version':entry['version'],'operation_id':entry['operation_id'],
            'operation_receipt_sha256':entry['operation_receipt_sha256'],'output_verification':entry.get('output_verification'),
            'completion_snapshot':entry['payload']['completion_snapshot']})
    snapshot=_completion_scope(data,budget)
    scene=nuke['formal_receipt']['execution_fact']['worker_receipt']
    final_nk=_alpha_module().checked({'path':scene['snapshot'],'bytes':Path(scene['snapshot']).stat().st_size,'sha256':scene['snapshot_sha256']})
    if _alpha_module().file_record(data['outputs']['nuke_script'])['sha256']!=scene['snapshot_sha256']:
        raise ValueError('ENGINEERING_FINAL_NUKE_SCRIPT_CHANGED')
    source=_evidence_source(data['scope'],data['bindings'])
    if (alpha['calibration']['evidence_source']!=source
            or verify['artifact']['output_verification']['evidence_source']!=source
            or nuke['output_verification']['evidence_source']!=source):
        raise ValueError('ENGINEERING_EVIDENCE_SOURCE_MISMATCH')
    comparison=None;preview_record=None
    from dcc_task_runtime.render_profiles import OFFICIAL
    if selected_plan(data['scope'])['scene_profile']==OFFICIAL:
        from houdini_bridge.official_karma import compare_files
        from houdini_bridge.official_karma_inputs import resolve_manifest
        resolve_manifest(data['control']/'run.json',_alpha_module().file_record(data['bindings_path']))
        main=data['outputs']['houdini_pattern'] % 1
        comparison={'official_to_bridge':compare_files(data['scope']['official_case']['paths']['official_image'],main),
            'bridge_to_nuke':compare_files(main,data['outputs']['nuke_pattern'] % 1,require_identical=True)}
        from houdini_bridge.official_karma_observation import load_record,file_record
        from houdini_bridge.official_karma_inputs import derivation_rule
        from houdini_bridge.official_karma_display import write_previews,validate_previews,check_output_capacity
        seal=load_record(file_record(derivation_rule(budget.native.root)['seal_path']))
        preview_path=data['root']/'official-previews.json'
        from dcc_task_runtime.platform_support import atomic_write
        if not preview_path.exists():
            previews=write_previews(budget.native,seal,main,data['outputs']['nuke_pattern'] % 1)
            payload=canonical(previews)
            check_output_capacity(budget.native,len(payload))
            atomic_write(preview_path,payload,owned_root=data['root'])
        left,right=comparison['official_to_bridge'],comparison['bridge_to_nuke']
        if left['candidate']!=right['reference']:
            raise ValueError('OFFICIAL_COMPARISON_SOURCE_CHANGED')
        preview_record=validate_previews(budget.native,seal,
            {'official':left['reference'],'bridge':left['candidate'],'nuke':right['candidate']})
        if any(value['state']!='PASS' for value in comparison.values()):
            from dcc_task_runtime.platform_support import atomic_write
            atomic_write(data['root']/'official-image-comparison.json',canonical(comparison),owned_root=data['root'])
            raise ValueError('OFFICIAL_IMAGE_COMPARISON_FAILED')
    snapshot=_completion_scope(data,budget)
    checks=({'state':'TECHNICALLY_COMPLETED','native_execution_status':'EXECUTED'} if source=='real_host' else
        {'state':'SOFTWARE_TECHNICALLY_COMPLETED','native_execution_status':'NOT_RUN','software_execution_status':'EXECUTED'})
    return {'schema':'bridge.controlled-engineering.result/1',
        'state':'AWAITING_HUMAN_REVIEW' if source=='real_host' else 'SOFTWARE_CHAIN_COMPLETED','evidence_source':source,
        'machine_checks':checks,'human_review':'PENDING',
        'scope_sha256':data['scope_sha256'],'bindings_sha256':data['bindings_sha256'],
        'project_files':data['bindings']['project_files'],'artifacts':artifacts,
        'nuke_snapshot':_alpha_module().file_record(final_nk),'native_scope':snapshot,
        'alpha_calibration':alpha['alpha_calibration'],'official_comparison':comparison,
        'official_previews':preview_record,'human_visual_review':'PENDING'}


def _run_alpha(data):
    runner=_alpha_module()
    if data.get('bindings',{}).get('evidence_source')=='software_test' and _evidence_source(data['scope'],data['bindings'])=='software_test':
        report,prepared=runner.preflight(data['scope_path'],data['bindings_path'])
        if report['blockers']:raise ValueError(';'.join(report['blockers']))
        scope=prepared['scope']
        if (scope.get('execution_authorized') is not True or
                scope.get('status')!='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION' or
                _evidence_source(scope,prepared['bindings'])!='software_test'):
            raise ValueError('ENGINEERING_SOFTWARE_AUTHORIZATION_REQUIRED')
        return runner._execute_approved(prepared,report,runner.ScopeBudget(data['scope_path'],data['bindings_path']))
    return runner.execute(data['scope_path'],data['bindings_path'],
        approved_scope_sha256=data['scope_sha256'],approved_bindings_sha256=data['bindings_sha256'])


def _official_prefix(data,journal,budget,action):
    from dcc_task_runtime import owned_process,process_image
    from houdini_bridge.official_karma_worker import check_frozen_case
    from houdini_bridge.official_karma_observation import seal_observations,native_original
    from houdini_bridge.official_karma_inputs import materialize
    from uuid import uuid4
    case=check_frozen_case(budget.native)
    originals=[]
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    diagnostic=data['scope'].get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_ROLES,OFFICIAL_IDENTITY_MODES
    survey=data['scope'].get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE
    roles=OFFICIAL_IDENTITY_ROLES if survey else ('official-open-save',) if diagnostic else ('official-open-save','official-cold-export','official-husk')
    for index,role in enumerate(roles):
        budget.available(starts=1 if diagnostic else 11-index)
        if budget.remaining()<=5: raise ValueError('OFFICIAL_STOP_RESERVE_EXHAUSTED')
        host='husk' if role=='official-husk' else 'hython'
        directory=budget.native.root/('supervisor-'+role) if survey else Path(case['paths'][{'official-open-save':'warm_supervisor',
            'official-cold-export':'cold_supervisor','official-husk':'official_husk_supervisor'}[role]])
        identity={'task_id':data['scope']['scope_id'],'operation_id':role,'launch_nonce':uuid4().hex}
        command=case['commands']['official-open-save' if survey else role]
        environment=dict(data['bindings']['environment'],PYTHONPATH='',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        expected=process_image.freeze_executable(data['scope']['hosts'][host]['path'],'21.0.631',
            data['scope']['hosts'][host]['sha256'])
        def run():
            check_frozen_case(budget.native)
            from dcc_task_runtime.native_scope import OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE
            window_mode=data['scope'].get('execution_mode')==OFFICIAL_WINDOW_DIAGNOSTIC_MODE
            startup_mode=data['scope'].get('execution_mode') in (OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE)
            began=time.monotonic();parent_deadline=began+min(60.,budget.remaining())
            witness=None;accounting=None;sealing_error=None;parent_over_budget=False
            handle=None
            if startup_mode:
                from dcc_task_runtime.startup_trace import StartupWitness
                if window_mode:
                    from dcc_task_runtime.window_trace import WindowWitness
                    StartupWitness=WindowWitness
                witness=StartupWitness(budget.native,directory,identity,command,began=began,deadline=parent_deadline)
            launch_options={'on_supervisor_spawned':witness.start} if startup_mode else {}
            try:
                handle=owned_process.launch(command,directory=directory,identity=identity,
                    supervisor_executable=data['scope']['hosts']['supervisor_python']['path'],env=environment,
                    budget_seconds=min(120.,budget.remaining()-5),resource_budget=budget.resource_budget,
                    writer_executable=expected,scope_role=role,scope_heavy=True,**launch_options)
                handle.wait(timeout=min(125.,budget.remaining(),max(.01,parent_deadline-time.monotonic())) if startup_mode else min(125.,budget.remaining()))
            except BaseException:
                try:
                    if handle is not None:handle.terminate();handle.wait(timeout=5)
                    elif startup_mode and directory.is_dir():
                        owned_process._atomic(directory/'cancel.json',{'identity':identity})
                        while time.monotonic()<parent_deadline-1:
                            if owned_process.read_receipt(directory,'stopped',identity=identity) is not None:break
                            time.sleep(.01)
                except Exception:
                    if not startup_mode:raise
                    sys.stderr.write('STARTUP_NATIVE_STOP_UNKNOWN\n')
                finally:
                    if witness is not None:
                        try:witness.finish()
                        except Exception:pass
                raise
            if witness is not None:
                try:accounting=witness.finish()
                except Exception as error:sealing_error=error
                finally:parent_over_budget=time.monotonic()>parent_deadline
            binding={'directory':str(directory),'identity':identity}
            budget.native.check()
            if startup_mode and (parent_over_budget or sealing_error is not None or accounting is None or accounting.get('over_budget')
                    or accounting.get('cleanup_complete') is not True or accounting.get('diagnostic_complete') is not True):
                raise ValueError('OFFICIAL_STARTUP_EXTERNAL_DIAGNOSTIC_INCOMPLETE')
            native_original(budget.native,role,binding)
            check_frozen_case(budget.native)
            if startup_mode and time.monotonic()>parent_deadline:
                raise ValueError('OFFICIAL_STARTUP_EXTERNAL_DIAGNOSTIC_INCOMPLETE')
            return binding
        originals.append(action(role,{'command':command,'directory':str(directory)},run))
        if survey:
            original=originals[-1]
            start=owned_process.read_receipt(original['directory'],'started',identity=original['identity'])
            payload=owned_process.read_receipt(original['directory'],'official-identity-diagnostic',identity=original['identity'])
            if (not payload or payload.get('scope_binding')!=budget.binding
                    or payload.get('started_sha256')!=hashlib.sha256(owned_process._canonical(start)).hexdigest()
                    or payload.get('captured_pid')!=start['pid'] or payload.get('writer_tool_trace')!=start.get('writer_tool_trace')
                    or payload.get('hip_business')!='NOT_RUN'):
                raise ValueError('OFFICIAL_IDENTITY_SURVEY_RECEIPT_REQUIRED')
            from houdini_bridge.official_karma_observation import load_record
            from dcc_task_runtime.writer_tool_trace import survey_next_allowed
            if not survey_next_allowed(load_record(payload['writer_tool_trace']['record']),
                    collector_policy=process_image.scope_collector_policy(data['scope']),scope_binding=budget.binding):
                raise ValueError('OFFICIAL_IDENTITY_SURVEY_TRACE_INCOMPLETE')
    if survey:
        budget.fail('OFFICIAL_IDENTITY_SURVEY_FINISHED')
        return {'schema':'bridge.official-identity-survey-result/1','state':'TIMEOUT_NOT_REPRODUCED',
            'native_scope':budget.native.snapshot(),'full_chain_accepted':False,'hip_business':'NOT_RUN','originals':originals}
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_DIAGNOSTIC_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE
    if data['scope'].get('execution_mode') in (OFFICIAL_IDENTITY_DIAGNOSTIC_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE):
        original=originals[0]
        start=owned_process.read_receipt(original['directory'],'started',identity=original['identity'])
        payload=owned_process.read_receipt(original['directory'],'official-identity-diagnostic',identity=original['identity'])
        if (not payload or payload.get('scope_binding')!=budget.binding
                or payload.get('started_sha256')!=hashlib.sha256(owned_process._canonical(start)).hexdigest()
                or payload.get('captured_pid')!=start['pid'] or payload.get('writer_tool_trace')!=start.get('writer_tool_trace')
                or payload.get('hip_business')!='NOT_RUN'):
            raise ValueError('OFFICIAL_IDENTITY_DIAGNOSTIC_INCOMPLETE')
        from houdini_bridge.official_karma_observation import checked_bytes
        if data['scope'].get('execution_mode')!=OFFICIAL_STARTUP_DIAGNOSTIC_MODE:checked_bytes(payload['writer_tool_trace']['record'])
        budget.fail('OFFICIAL_IDENTITY_DIAGNOSTIC_FINISHED')
        return {'schema':'bridge.official-identity-diagnostic-result/1','state':'IDENTITY_DIAGNOSTIC_FINISHED',
            'native_scope':budget.native.snapshot(),'full_chain_accepted':False,'hip_business':'NOT_RUN','original':original}
    if diagnostic:
        payload=owned_process.read_receipt(originals[0]['directory'],'official-diagnostic',identity=originals[0]['identity'])
        if not payload or payload.get('diagnostics_incomplete') is not False or payload.get('scope_binding')!=budget.binding:
            raise ValueError('OFFICIAL_DIAGNOSTIC_INCOMPLETE')
        from houdini_bridge.official_karma_observation import checked_bytes
        checked_bytes(payload['diagnostic'])
        budget.fail('OFFICIAL_DIAGNOSTIC_FIRST_STAGE_FINISHED')
        return {'schema':'bridge.official-karma-first-stage-diagnostic/1','state':'DIAGNOSTIC_FIRST_STAGE_COMPLETED',
            'native_scope':budget.native.snapshot(),'cold_reopen':'NOT_RUN','render':'NOT_RUN',
            'full_chain_accepted':False,'original':originals[0]}
    seal=action('official_seal',{'scope':budget.binding},lambda:seal_observations(budget.binding,*originals))
    from houdini_bridge.official_karma_display import freeze_display
    action('official_display',{'sealed_observation':seal},lambda:freeze_display(budget.native,seal))
    action('official_derived_inputs',{'sealed_observation':seal},lambda:materialize(
        data['control']/'run.json',_alpha_module().file_record(data['bindings_path']),seal))
    data.update(_project_inputs(_alpha_module(),data['scope'],data['bindings']))


def _fresh(data,journal,budget):
    controllers=[]
    def frozen_inputs():
        from dcc_task_runtime.render_profiles import OFFICIAL
        if selected_plan(data.get('scope',{}))['scene_profile']==OFFICIAL:
            if _alpha_module().file_record(data['bindings_path'])['sha256']!=data['bindings_sha256']:
                raise ValueError('OFFICIAL_RUNTIME_BINDINGS_CHANGED')
            _project_inputs(_alpha_module(),data['scope'],data['bindings'])
    def action(name,request,callback):
        frozen_inputs()
        journal.intent(name,request)
        result=callback()
        frozen_inputs()
        journal.done(name,result)
        return result
    try:
        from dcc_task_runtime.render_profiles import OFFICIAL
        if selected_plan(data['scope'])['scene_profile']==OFFICIAL:
            prefix_result=_official_prefix(data,journal,budget,action)
            if prefix_result is not None:
                journal.intent('complete',{});journal.done('complete',prefix_result)
                return prefix_result
        action('alpha',{'scope_sha256':data['scope_sha256'],'bindings_sha256':data['bindings_sha256']},
            lambda:_run_alpha(data))
        first=Controller(data,budget);controllers.append(first)
        for observation in metadata_observations(data,first.tool('catalog',{})):
            first.tool('submit_observation',observation)
        proposed=action('propose',{'request_id':PREFIX+'_propose'},lambda:first.tool('graph_propose',
            {'request_id':PREFIX+'_propose','proposal':{'schema':'bridge.registered-domain-construction/1',
             'domain_pack':selected_plan(data['scope'])['domain_pack'],'houdini_version':'21.0.631',
             'scene_profile':selected_plan(data['scope'])['scene_profile']}}))
        built=action('build',{'request_id':PREFIX+'_build','graph_id':proposed['graph_id']},
            lambda:first.tool('graph_trial',{'graph_id':proposed['graph_id'],'request_id':PREFIX+'_build'}))
        operation_id=built.get('operation_id')
        if not operation_id:raise ValueError('ENGINEERING_BUILD_OPERATION_REQUIRED')
        built=_poll(first,'graph_status',{'operation_id':operation_id},('state',),'SUCCEEDED')
        handed=first.tool('graph_trial',{'graph_id':proposed['graph_id'],'request_id':PREFIX+'_build'})
        if (handed.get('operation_id')!=operation_id or handed.get('state')!='SUCCEEDED'
                or (handed.get('host_binding') or {}).get('graph_binding',{}).get('graph_ready') is not True):
            raise ValueError('ENGINEERING_GRAPH_HOST_HANDOFF_REQUIRED')
        saved=action('save',{},lambda:first.tool('task_save',{}))
        contract=saved['scene_contract'];roles={item['role']:item['path'] for item in contract['nodes']}
        if contract['frozen_scene_parameters']['profile']!=selected_plan(data['scope'])['scene_profile']:raise ValueError('ENGINEERING_SAVED_SCENE_MISMATCH')
        action('houdini_initial_stop',{},lambda:_stop_host(data,'houdini'))
        first.close();controllers.remove(first)
        second=Controller(data,budget);controllers.append(second)
        action('reopen',{'saved_scene_id':saved['saved_scene_id']},lambda:second.tool('task_reopen',{'saved_scene_id':saved['saved_scene_id']}))
        from vfx_pipeline.production_hosts import host_phase_budget
        hconfig=load(data['control']/'production-hosts.json')['hosts']['houdini']
        render_seconds=host_phase_budget(hconfig,requested_seconds=min(120.,budget.remaining()))
        rendered=action('render',{'request_id':PREFIX+'_render'},lambda:second.tool('houdini_render_bounded',
            {'request_id':PREFIX+'_render','saved_scene_id':saved['saved_scene_id'],'render_target':roles['render'],
             'pattern':data['outputs']['houdini_pattern'],'frames':[1],'budget_seconds':render_seconds}))
        _poll(second,'operation_query',{'operation_id':rendered['operation_id']},('operation','state'),'COMPLETED')
        action('houdini_reopen_stop',{},lambda:_stop_host(data,'houdini'))
        action('verify',{'verification_id':PREFIX+'_verify'},lambda:_verify_registered(data,journal))
        action('nuke_prepare',{'script':data['outputs']['nuke_script']},lambda:tool_module('prepare_nuke_project').prepare_nuke_project(
            data['project'],Path(data['outputs']['nuke_script']),artifact_id=PREFIX+'_main',
            output_pattern=data['outputs']['nuke_pattern'],frames=[1],alpha_result_path=data['root']/'alpha-calibration-result.json'))
        second.tool('consume_artifact',{'artifact_id':PREFIX+'_main'})
        rendered_nuke=action('nuke_render',{'request_id':PREFIX+'_nuke'},lambda:second.tool('nuke_render_bounded',
            {'request_id':PREFIX+'_nuke','artifact_id':PREFIX+'_main','pattern':data['outputs']['nuke_pattern'],'frames':[1]}))
        _poll(second,'operation_query',{'operation_id':rendered_nuke['operation_id']},('operation','state'),'COMPLETED',
            registration_pending=lambda result:_nuke_pending(data,rendered_nuke['operation_id']))
        action('nuke_stop',{},lambda:_stop_host(data,'nuke'))
        second.close();controllers.remove(second)
        result=_final_result(data,journal,budget)
        journal.intent('complete',{});journal.done('complete',result)
        return result
    except RegistrationPending as error:
        # Keep the existing idle Nuke host for authenticated ledger recovery.
        # Closing stdio controllers does not start or stop native hosts.
        for controller in controllers:
            controller.close()
        return _pending_result(journal,error)
    except BaseException as error:
        for controller in controllers:
            try:controller.close()
            except Exception:pass
        cleanup={}
        if (data['control']/'production-hosts.json').is_file():
            for kind in ('houdini','nuke'):
                try:cleanup[kind]=_stop_host(data,kind)
                except Exception as stop_error:cleanup[kind]={'state':'STOP_UNKNOWN','reason':str(stop_error)}
        journal.value['failure']={'error':str(error),'cleanup':cleanup};journal.save()
        try:budget.fail('ENGINEERING_DRIVER_FAILED')
        except Exception:pass
        raise


def _resume(data,journal,budget,*,continue_nuke_tail=False):
    """Reconcile existing work; a separately gated unstarted tail may continue."""
    stages=journal.value['stages']
    if stages.get('nuke_render',{}).get('state')=='INTENT':
        return _resume_nuke_intent(data,journal,budget)
    if 'nuke_render' in stages and stages['nuke_render'].get('state')!='DONE':
        return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'ENGINEERING_NUKE_INTENT_UNRESOLVED_NO_REPLAY','human_review':'PENDING'}
    if stages.get('nuke_render',{}).get('state')=='DONE':
        # No initial NK-save helper here: a legitimate final Read/Write save
        # supersedes its initial file identity before the render snapshot.
        nuke_id=journal.result('nuke_render')['operation_id']
        try:
            nuke=_nuke_original(data,nuke_id)
        except ValueError as original_error:
            # Query an existing task-owned host only. Constructing this client
            # never starts a host or resubmits a render.
            from vfx_pipeline.workbuddy_assembly import production_nuke_client
            saved=load(data['control']/'production-hosts.json')
            client=production_nuke_client(saved['hosts']['nuke'],data['control']/'nuke-state')
            client.bind_task(saved['task_id'])
            try:
                queried=client.call('render_status',{'task_id':nuke_id})
            except Exception as query_error:
                return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
                    'reason':'ENGINEERING_EXISTING_OPERATION_UNRESOLVED','operation_id':nuke_id,
                    'original_error':str(original_error),'query_error':str(query_error),'human_review':'PENDING'}
            if queried.get('state') not in ('COMPLETED','NEEDS_RECONCILE'):
                return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
                    'reason':'ENGINEERING_EXISTING_OPERATION_NOT_COMPLETED','operation':queried,'human_review':'PENDING'}
            nuke=_nuke_original(data,nuke_id)
        if nuke.get('execution_fact',{}).get('ledger_state')=='PENDING':
            try:
                _register_existing_nuke(data,nuke_id,nuke)
                nuke=_nuke_original(data,nuke_id)
                if nuke.get('execution_fact',{}).get('ledger_state')!='REGISTERED':
                    raise ValueError('ENGINEERING_NUKE_LEDGER_STILL_PENDING')
            except Exception as error:
                return _pending_result(journal,RegistrationPending('nuke',nuke_id,nuke,error))
        if stages.get('nuke_stop',{}).get('state')!='DONE':
            stopped=_stop_host(data,'nuke')
            if 'nuke_stop' not in stages:journal.intent('nuke_stop',{})
            journal.done('nuke_stop',stopped)
        try:result=_final_result(data,journal,budget)
        except RegistrationPending as error:return _pending_result(journal,error)
        journal.value.pop('registration_pending',None);journal.save()
        return dict(result,revalidated=True)
    if stages.get('render',{}).get('state')=='DONE' and stages.get('houdini_reopen_stop',{}).get('state')=='DONE':
        try:verify=_verify_registered(data,journal)
        except RegistrationPending as error:return _pending_result(journal,error)
        if stages.get('verify',{}).get('state')=='INTENT':
            journal.done('verify',verify)
        journal.value.pop('registration_pending',None);journal.save()
        if continue_nuke_tail:
            try:return _continue_nuke_tail(data,journal,budget)
            except RegistrationPending as error:return _pending_result(journal,error)
        return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'NEXT_UNSTARTED_NUKE_TAIL_REQUIRES_CONTINUATION','verification':verify,'human_visual_review':'PENDING'}
    return {'schema':'bridge.controlled-engineering.result/1','state':'QUERY_REQUIRED',
            'reason':'ENGINEERING_INTERRUPTED_INTENT_NO_REPLAY','stages':{k:v['state'] for k,v in stages.items()},
            'human_visual_review':'PENDING'}


def _activation_gate(scope_path,bindings_path,scope_sha256):
    from dcc_task_runtime.native_scope import NativeScope
    native=NativeScope({'path':str(Path(scope_path)),'sha256':scope_sha256})
    receipt=tool_module('activate_controlled_engineering').validate_activation(native,bindings_path)
    if receipt.get('authorization') not in ('explicit_local_terminal_controller','explicit_agent_controller'):
        raise ValueError('ENGINEERING_EXPLICIT_LOCAL_ACTIVATION_REQUIRED')


def execute(scope_path,bindings_path,*,approved_scope_sha256,approved_bindings_sha256,continue_nuke_tail=False):
    report,data=preflight(scope_path,bindings_path)
    scope=data.get('scope') or {};bindings=data.get('bindings') or {}
    if (scope.get('execution_authorized') is not True or scope.get('status')!='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or scope.get('evidence_source')!='real_host' or bindings.get('evidence_source')!='real_host'):
        raise ValueError('ENGINEERING_EXPLICIT_REAL_HOST_AUTHORIZATION_REQUIRED')
    if (approved_scope_sha256!=report['scope_sha256'] or approved_bindings_sha256!=report['bindings_sha256']):
        raise ValueError('ENGINEERING_TWO_APPROVED_HASHES_REQUIRED')
    if report['state']=='BLOCKED':raise ValueError(';'.join(report['blockers']))
    if ROOT!=data['snapshot']:raise ValueError('ENGINEERING_USE_FROZEN_PROJECT_ENTRY')
    data.update(scope_path=Path(scope_path),bindings_path=Path(bindings_path),
        scope_sha256=report['scope_sha256'],bindings_sha256=report['bindings_sha256'])
    _activation_gate(scope_path,bindings_path,report['scope_sha256'])
    budget=_alpha_module().ScopeBudget(scope_path,bindings_path)
    from dcc_task_runtime.execution_lock import execution_lock
    journal_path=data['root']/'engineering-driver-state.json'
    with execution_lock(journal_path,'controlled-engineering'):
        # Another invocation may have completed while this caller waited.
        # Reload both immutable inputs and the stage journal after acquiring
        # the execution lock, before deciding whether any start is allowed.
        current,_=preflight(scope_path,bindings_path)
        if (current.get('scope_sha256')!=report['scope_sha256']
                or current.get('bindings_sha256')!=report['bindings_sha256']):
            raise ValueError('ENGINEERING_STAGE_BINDING_CHANGED')
        if current['state']=='BLOCKED':raise ValueError(';'.join(current['blockers']))
        report=current
        _activation_gate(scope_path,bindings_path,report['scope_sha256'])
        journal=StageJournal(journal_path,report['scope_sha256'],report['bindings_sha256'])
        if journal.existing:
            return (_resume(data,journal,budget,continue_nuke_tail=True) if continue_nuke_tail else _resume(data,journal,budget))
        if continue_nuke_tail:raise ValueError('ENGINEERING_CONTINUATION_REQUIRES_STOPPED_REGISTERED_HOUDINI')
        if report['state']!='PREPARED':raise ValueError('ENGINEERING_QUERY_REQUIRED_BEFORE_NEW_START')
        journal.save()
        return _fresh(data,journal,budget)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',required=True);parser.add_argument('--bindings',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--continue-nuke-tail',action='store_true')
    parser.add_argument('--approved-scope-sha256');parser.add_argument('--approved-bindings-sha256')
    args=parser.parse_args()
    if args.continue_nuke_tail and not args.execute:parser.error('--continue-nuke-tail requires --execute')
    result=(execute(args.scope,args.bindings,approved_scope_sha256=args.approved_scope_sha256,
        approved_bindings_sha256=args.approved_bindings_sha256,continue_nuke_tail=args.continue_nuke_tail)
        if args.execute else preflight(args.scope,args.bindings)[0])
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))
    return 0 if result['state'] in ('PREPARED','AWAITING_HUMAN_REVIEW','SOFTWARE_CHAIN_COMPLETED',
        'IDENTITY_DIAGNOSTIC_FINISHED','DIAGNOSTIC_FIRST_STAGE_COMPLETED','TIMEOUT_NOT_REPRODUCED') else 2


if __name__=='__main__':raise SystemExit(main())
