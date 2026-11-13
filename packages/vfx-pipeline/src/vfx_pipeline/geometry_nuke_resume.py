"""只续接已保存NK的确定导入失败；不启动Houdini、不重做生产或原生保存。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope,_accounting_lock
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from .geometry_render_resume import _path,_read,_object,_load,_source_closure

_SOURCE='bridge.geometry-nuke-resume-source/1'
_SCHEMA='bridge.geometry-nuke-resume-authorization/1'
_DOMAIN=b'bridge.geometry-nuke-resume-authorization/1\x00'
_AUTH='geometry-nuke-resume-authorization.json'
_STAGES={'reuse_source','render','render_completed','render_host_stop','verify','register','input_source','nuke_save','nuke_launch_intent'}
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_nuke_resume.py',
        'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_nuke_recovery.py',
        'runtime/tools/resume_geometry_nuke.py'}
_CHANGED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+name+'.py' for name in
          ('native_scope','geometry_recovery','geometry_budget_addendum')}
_CHANGED|={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+name+'.py' for name in
           ('geometry_job','geometry_session','geometry_runtime_binding','geometry_render_resume')}
_CHANGED.add('runtime/tools/nuke_owned_render_worker.py')
_CHANGED.add('runtime/packages/houdini-bridge/src/houdini_bridge/controlled_output.py')


def _fail():raise ValueError('GEOMETRY_NUKE_RESUME_INVALID')


def _context(record):
    prep=_object(_read(record));native=NativeScope(prep['scope'])
    if (record['path']!=str(native.root/'geometry-preparation.json') or prep.get('schema')!='bridge.geometry-creative-preparation/1'
            or prep.get('task_id')!=native.scope['task_id'] or native.scope.get('schema')!='bridge.geometry-creative-scope/1'):_fail()
    return prep,native


def _consumer(native,job,journal,*,require_output_absent=False):
    """未执行Write的确定失败必须对应原持久化冷渲染身份与signed exit2。"""
    operation=journal['stages']['nuke_launch_intent']['result']['operation_id']
    expected='nrend-'+hashlib.sha256((job['operation_id']+'_nuke').encode()).hexdigest()[:16]
    if operation!=expected:_fail()
    path=native.root/'state/nuke_renders'/(operation+'.json');task=_load(path)
    if (task.get('task_id')!=operation or task.get('owner_task_id')!=job['task_id'] or task.get('request_id')!=job['operation_id']+'_nuke'
            or task.get('entry')!='render_write' or task.get('node')!='Write1' or task.get('frame_set')!=[1]
            or task.get('frame_range')!=[1,1] or task.get('backend')!='owned_subprocess' or task.get('dispatch_state')!='launched'):_fail()
    from nuke_bridge.operation_receipts import validate_registered_input_contract
    if require_output_absent:validate_registered_input_contract(task['input_contract'])
    from .geometry_job import _tools
    _tools();from recover_disklight_nuke import cold_request_digest
    if task.get('request_sha256')!=cold_request_digest(task):_fail()
    process=task.get('process') or {};directory=native.root/'state/nuke_renders'/(operation+'.supervisor')
    identity=process.get('supervisor_identity')
    if (process.get('supervisor_directory')!=str(directory) or not isinstance(identity,dict)
            or identity.get('operation_id')!=operation or identity.get('task_id')!=operation
            or identity.get('input_contract_sha256')!=canonical_sha256(task['input_contract'])):_fail()
    from dcc_task_runtime.owned_process import read_receipt,execution_returncode
    started=read_receipt(directory,'started',identity=identity);stopped=read_receipt(directory,'stopped',identity=identity)
    if (not started or not stopped or started.get('pid')!=process.get('pid') or execution_returncode(stopped)!=2
            or stopped.get('supervisor_exit_code')!=0 or stopped.get('stop_reason') is not None
            or stopped.get('descendant_result_unobserved') is not False):_fail()
    stderr=directory/'child.stderr.log'
    if stderr.read_bytes().strip()!=b"No module named 'houdini_bridge'":_fail()
    result=native.root/'state/nuke_renders'/(operation+'.worker-result.json')
    if process.get('worker_result')!=str(result) or result.exists() or (require_output_absent and Path(task['pattern']%1).exists()):_fail()
    snapshot=_path(task['script_snapshot']);nk=journal['stages']['nuke_save']['result']
    if (file_record(snapshot)['sha256']!=nk['file']['sha256'] or task.get('scene_fingerprint')!=nk['file']['sha256']
            or identity.get('snapshot_sha256')!=nk['file']['sha256'] or task['pattern']!=nk['pattern']):_fail()
    records={name:file_record(directory/name) for name in ('started.json','stopped.json','intent.json','child.stderr.log')}
    return task,path,records


def inspect_before(failed_job_path):
    """只读采集原失败；调用方先封存raw记录，不能把尚占槽的记录当作终态。"""
    path=_path(failed_job_path);job=_load(path);prep,native=_context(job['preparation']);directory=path.parent
    if (path!=native.root/'jobs'/job['operation_id']/'job.json' or job.get('revision')!=1
            or job.get('directory')!=str(directory) or job.get('task_id')!=prep['task_id'] or 'render_source' not in job):_fail()
    journal=_load(directory/'incremental-state.json');error=_load(directory/'error.json')
    if (journal.get('job')!=file_record(path) or set(journal.get('stages',{}))!=_STAGES|{'nuke_cold'}
            or any(journal['stages'][name].get('state')!='DONE' for name in _STAGES)
            or journal['stages']['nuke_cold'].get('state')!='INTENT' or 'result' in journal['stages']['nuke_cold']
            or error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='NATIVE_SCOPE_EXECUTION_FAILED' or error.get('preparation_record')!=job['preparation']
            or error.get('operation_id')!=job['operation_id'] or error.get('task_id')!=prep['task_id'] or error.get('revision')!=1):_fail()
    usage=native.completed_snapshot();roles=['graph-worker']*2+['houdini-host']*5+['main-husk','nuke-host','nuke-render']
    actual=usage['tickets']
    if (usage['closed_reason']!='NATIVE_SCOPE_EXECUTION_FAILED' or len(actual)!=10
            or sorted(t['role'] for t in actual)!=sorted(roles)):_fail()
    task,record,supervisor=_consumer(native,job,journal,require_output_absent=True)
    if task.get('state') not in ('RUNNING','FAILED'):_fail()
    return {'schema':'bridge.geometry-nuke-before-source/1','preparation':job['preparation'],'task_id':prep['task_id'],
            'job':file_record(path),'operation_id':job['operation_id'],'consumer_operation_id':task['task_id'],
            'cold_render':file_record(record),'supervisor_files':supervisor,'native_snapshot':usage}


def close_failed_consumer(preparation_record,before_source,before_archive_record):
    """唯一副作用是正式status负终态及资源槽释放；不启动进程、不修改job/error/签名停止。"""
    prep,native=_context(preparation_record);job=_object(_read(before_source['job']))
    if (before_source!=inspect_before(before_source['job']['path'])
            or before_archive_record.get('path')!=str(native.root/'geometry-nuke-resume-audit/before-operation.json')
            or _read(before_archive_record)!=_read(before_source['cold_render'])):_fail()
    from .geometry_job import _load_nuke
    addon=_load_nuke(prep);slot_before=addon._NUKE_SCHEDULER.snapshot();operation=before_source['consumer_operation_id']
    if not slot_before or slot_before.get('active')!=1 or slot_before.get('operation_id')!=operation:_fail()
    preserved={name:copy.deepcopy(record) for name,record in before_source['supervisor_files'].items()}
    accounting=native.journal_path.read_bytes();terminal=addon.nuke_render_status(operation)
    slot_after=addon._NUKE_SCHEDULER.snapshot()
    if (terminal.get('state')!='FAILED' or terminal.get('stop_confirmed') is not True or terminal.get('slot_released') is not True
            or terminal.get('exit_code')!=2 or not slot_after or slot_after.get('active')!=0
            or slot_after.get('operation_id')!=operation or slot_after.get('phase')!='RELEASED'
            or native.journal_path.read_bytes()!=accounting):_fail()
    for record in preserved.values():_read(record)
    return {'schema':'bridge.geometry-nuke-negative-closure/1','preparation':preparation_record,'job':before_source['job'],
            'operation_id':operation,'before':before_archive_record,'after':file_record(native.root/'state/nuke_renders'/(operation+'.json')),
            'supervisor_files':preserved,'native_snapshot':before_source['native_snapshot'],
            'slot_before':slot_before,'slot_after':slot_after,'state':'FAILED','stop_confirmed':True,'slot_released':True,
            'native_execution_claimed':False}


def _source_details(source,native,*,full_native=False):
    fields={'schema','preparation','task_id','operation_id','job','execution_preparation','journal','error','control',
            'files','negative_closure','render_source','native_snapshot','stage_sha256'}
    if set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id']:_fail()
    job=_object(_read(source['job']));prep=_object(_read(source['preparation']));directory=native.root/'jobs'/source['operation_id']
    if (source['job']['path']!=str(directory/'job.json') or job.get('directory')!=str(directory)
            or job.get('operation_id')!=source['operation_id'] or job.get('revision')!=1
            or job.get('preparation')!=source['preparation'] or prep.get('scope')!=native.binding
            or source['preparation']['path']!=str(native.root/'geometry-preparation.json')
            or source['render_source']!=job.get('render_source')):_fail()
    from .geometry_render_resume import verify_job as verify_render_source
    original=verify_render_source(job,native)
    journal=_object(_read(source['journal']));error=_object(_read(source['error']));jobprep=_object(_read(source['execution_preparation']))
    control=directory/'project/control';stages=journal.get('stages',{})
    if (source['control']!=str(control) or source['journal']['path']!=str(directory/'incremental-state.json')
            or source['error']['path']!=str(directory/'error.json') or jobprep.get('job')!=source['job']
            or source['execution_preparation']['path']!=str(directory/'job-preparation.json') or jobprep.get('control')!=str(control)
            or journal.get('job')!=source['job'] or set(stages)!=_STAGES|{'nuke_cold'}
            or any(stages[name].get('state')!='DONE' for name in _STAGES)
            or stages['nuke_cold'].get('state')!='INTENT' or 'result' in stages['nuke_cold']
            or source['stage_sha256']!={name:canonical_sha256(stages[name]['result']) for name in _STAGES}
            or error.get('state')!='FAILED' or error.get('code')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or error.get('preparation_record')!=source['preparation'] or error.get('operation_id')!=source['operation_id']):_fail()
    closure=_object(_read(source['negative_closure']));task,path,supervisor=_consumer(native,job,journal,require_output_absent=full_native)
    if (source['negative_closure']['path']!=str(native.root/'geometry-nuke-resume-audit/negative-closure.json')
            or closure.get('schema')!='bridge.geometry-nuke-negative-closure/1' or closure.get('preparation')!=source['preparation']
            or closure.get('job')!=source['job'] or closure.get('operation_id')!=task['task_id'] or closure.get('state')!='FAILED'
            or closure.get('stop_confirmed') is not True or closure.get('slot_released') is not True
            or closure.get('native_execution_claimed') is not False or closure.get('supervisor_files')!=supervisor
            or closure.get('after')!=file_record(path) or task.get('state')!='FAILED' or not task.get('stop_confirmed_at')
            or task.get('slot_released') is not True or task.get('exit_code')!=2
            or closure.get('slot_before',{}).get('active')!=1 or closure.get('slot_after',{}).get('active')!=0
            or closure.get('slot_after',{}).get('phase')!='RELEASED'):_fail()
    before=_object(_read(closure['before']))
    if (closure['before']['path']!=str(native.root/'geometry-nuke-resume-audit/before-operation.json')
            or before.get('task_id')!=task['task_id'] or before.get('state')!='RUNNING'
            or any(before.get(k)!=task.get(k) for k in ('owner_task_id','request_id','pattern','scene_fingerprint','input_binding','input_contract','script_snapshot','process','slot'))):_fail()
    usage=source['native_snapshot'];tickets=usage.get('tickets',[])
    with _accounting_lock(native.state_path):current=native._read()
    if (closure.get('native_snapshot')!=usage or usage.get('dcc_starts')!=10 or len(tickets)!=10
            or usage.get('scope_sha256')!=native.binding['sha256'] or usage.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or any(t.get('stopped_at') is None for t in tickets) or current['tickets'][:10]!=tickets):_fail()
    files=source['files'];expected={'hip','main','nk','input_source','context','consumer','snapshot'}
    if set(files)!=expected:_fail()
    for record in files.values():_read(record)
    registered=stages['register']['result'];verified=stages['verify']['result'];nk=stages['nuke_save']['result'];source_record=stages['input_source']['result']
    if (files['hip']!=file_record(Path(original['save']['path'])) or files['nk']!=nk['file']
            or files['main']!=file_record(Path(registered['pattern']%1)) or files['input_source']!=source_record
            or files['context']!=stages['nuke_launch_intent']['result']['context'] or files['consumer']!=closure['after']
            or files['snapshot']['path']!=task['script_snapshot'] or files['snapshot']['sha256']!=nk['file']['sha256']
            or registered.get('artifact_id')!='geometry_main' or registered.get('version')!=1
            or nk['pattern']!=str(directory/'project/saves/nuke.%04d.exr') or nk['file']['path']!=str(directory/'project/saves/composite.nk')):_fail()
    source_payload=_object(_read(source_record));context=_object(_read(files['context']))
    if (context!={'schema':'bridge.geometry-cold-context/1','native_scope':native.binding,'task_id':source['task_id'],'input_artifact_source':source_record}
            or source_payload.get('schema')!='bridge.geometry-nuke-source/1' or source_payload.get('producer_control')!=str(control)
            or source_payload.get('producer_ledger')!=prep['ledger_root'] or source_payload.get('artifact_id')!='geometry_main'
            or source_payload.get('artifact_version')!=1 or source_payload.get('registry_operation_receipt')!=registered.get('registry_operation_receipt')
            or source_payload.get('producer_fact_sha256')!=canonical_sha256(verified['execution_fact'])):_fail()
    if full_native:
        from .geometry_job import _load_nuke
        from nuke_bridge.task_host import input_artifact_registry
        addon=_load_nuke(prep);registry=input_artifact_registry(source_payload,scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact,observe_completed=True)
        if (registry.lookup('geometry_main')!=registered or registry.verify_operation_receipt(registered['registry_operation_receipt'])!=registered['registry_operation_receipt']
                or registry.verify('geometry_main').get('usable') is not True or registry.lookup('nuke-render-'+task['task_id']) is not None):_fail()
    base={'saved':original['save'],'warm_geometry':original['warm_geometry'],'geometry':original['cold_geometry'],
          'cold_reopen':original['cold_reopen'],'evaluation':original['evaluate'],'graph_source':original['graph_source'],
          'artifact':registered,'source_record':source_record}
    return {'operation_id':source['operation_id'],'observation_operation_id':original['operation_id'],'control':str(control),
            'project':str(control.parent),'base':base,'nuke_save':nk,'failed_consumer':task['task_id'],
            'source_record':source_record,'files':files,'output_pattern':nk['pattern']}


def inspect_source(failed_job_path,before_archive_record,negative_closure_record):
    """负终态已正式对账后固定来源；本函数不修改原生产记录。"""
    path=_path(failed_job_path);job=_load(path);prep,native=_context(job['preparation']);directory=path.parent
    journal=_load(directory/'incremental-state.json');stages=journal['stages'];closure=_object(_read(negative_closure_record))
    if closure.get('before')!=before_archive_record:_fail()
    from .geometry_render_resume import verify_job as verify_render_source
    original=verify_render_source(job,native);nk=stages['nuke_save']['result'];task=_load(closure['after']['path'])
    source={'schema':_SOURCE,'preparation':job['preparation'],'task_id':job['task_id'],'operation_id':job['operation_id'],
            'job':file_record(path),'execution_preparation':file_record(directory/'job-preparation.json'),
            'journal':file_record(directory/'incremental-state.json'),'error':file_record(directory/'error.json'),
            'control':str(directory/'project/control'),'negative_closure':negative_closure_record,'render_source':job['render_source'],
            'native_snapshot':closure['native_snapshot'],'stage_sha256':{name:canonical_sha256(stages[name]['result']) for name in _STAGES},
            'files':{'hip':file_record(Path(original['save']['path'])),'main':file_record(Path(stages['register']['result']['pattern']%1)),
                     'nk':nk['file'],'input_source':stages['input_source']['result'],'context':stages['nuke_launch_intent']['result']['context'],
                     'consumer':closure['after'],'snapshot':file_record(Path(task['script_snapshot']))}}
    _source_details(source,native,full_native=True);return source


def _closure(source,details,native):
    """登记头可被正常v2追加；历史只冻结原receipt及原生产文件，不冻结全局SQLite。"""
    mutable=native.root/'artifact_ledger/artifacts.sqlite3'
    excluded={str(mutable)+suffix for suffix in ('','-wal','-shm')}
    def strip(value):
        if isinstance(value,dict):
            if set(value)=={'path','bytes','sha256'} and value.get('path') in excluded:return None
            return {key:strip(item) for key,item in value.items()}
        if isinstance(value,list):return [strip(item) for item in value]
        return value
    return _source_closure(strip(source),strip(details),native)


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest();return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _packages(original,active):
    from .geometry_runtime_binding import _package
    if (original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes():_fail()
    old,of,osources=_package(original,'0.3.6');new,nf,nsources=_package(active,'0.3.8');changed={n for n in of if n in nf and of[n]!=nf[n]}
    if ({k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'} or set(of)-set(nf)
            or set(nf)-set(of)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':osources+nsources,
            'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
            'differences':[{'name':n,'before':file_record(original/n) if n in of else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}


def _request(record,prep_record,source,native):
    value=_object(_read(record));old=_object(_read(source['job']))['plan'];plan=copy.deepcopy(old)
    plan['plan_id']+='_nuke_resume01';plan['operator_repair']={'schema':'bridge.geometry-nuke-resume/1','failed_operation_id':source['operation_id'],'authorization_path':str(native.root/_AUTH)}
    plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'});rid='operator_nuke_resume01_'+source['operation_id'];op='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
    fields={'schema','preparation','task_id','failed_operation_id','failed_job','nuke_source','new_plan','request_id','new_operation_id','original_plan_sha256'}
    if (set(value)!=fields or record['path']!=str(native.root/'geometry-nuke-resume-request.json') or value.get('schema')!='bridge.geometry-nuke-resume-request/1'
            or value.get('preparation')!=prep_record or value.get('task_id')!=native.scope['task_id'] or value.get('failed_operation_id')!=source['operation_id']
            or value.get('failed_job')!=source['job'] or value.get('nuke_source',{}).get('path')!=str(native.root/'geometry-nuke-resume-source.json')
            or _object(_read(value['nuke_source']))!=source or value.get('new_plan')!=plan or value.get('request_id')!=rid
            or value.get('new_operation_id')!=op or value.get('original_plan_sha256')!=old['plan_sha256']):_fail()
    return value


def validate(preparation_record,authority_record,native=None):
    prep,current=_context(preparation_record);native=current if native is None else native
    if native.binding!=prep['scope'] or authority_record.get('path')!=str(native.root/_AUTH):_fail()
    value=_object(_read(authority_record));p=value.get('payload')
    fields={'schema','preparation','native_scope','task_id','source','request','recovery_grant','authority','source_closure',
            'original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(value)!={'payload','signature'} or not isinstance(p,dict) or set(p)!=fields
            or not hmac.compare_digest(str(value['signature']),_sign(native,p)) or p.get('schema')!=_SCHEMA
            or p.get('preparation')!=preparation_record or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or authority_record.get('path')!=str(native.root/_AUTH) or _path(authority_record['path']).stat().st_mode&0o077
            or p.get('source',{}).get('path')!=str(native.root/'geometry-nuke-resume-source.json')
            or not isinstance(p.get('authority'),dict) or set(p['authority'])!={'authority','instruction'}
            or p['authority'].get('authority')!='current_user_instruction'
            or not isinstance(p['authority'].get('instruction'),str) or not 10<=len(p['authority']['instruction'])<=16000):_fail()
    from dcc_task_runtime.geometry_nuke_recovery import validate as grant_validate
    grant,_,closed=grant_validate(native,p['recovery_grant']);source=_object(_read(p['source']))
    if grant.get('preparation')!=preparation_record or source['native_snapshot']['tickets']!=closed['tickets']:_fail()
    details=_source_details(source,native)
    if p['source_closure']!=_closure(source,details,native):_fail()
    _request(p['request'],preparation_record,source,native);return p,details


def create_authorization(preparation_record,original036formal,active037cache,failed_job_path,source_record,request_record,recovery_grant_record,instruction):
    prep,native=_context(preparation_record);formal=_path(original036formal);active=_path(active037cache)
    if (not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip()
            or active!=Path(prep['worker']).parents[2].with_name('0.3.8') or Path(prep['worker']).parents[2].name!='0.3.1'):_fail()
    source=_object(_read(source_record));details=_source_details(source,native,full_native=True)
    if source['preparation']!=preparation_record or source['job']!=file_record(_path(failed_job_path)):_fail()
    from dcc_task_runtime.geometry_nuke_recovery import validate as grant_validate
    grant,_,closed=grant_validate(native,recovery_grant_record)
    if grant.get('preparation')!=preparation_record or native._read()!=closed or closed['tickets']!=source['native_snapshot']['tickets']:_fail()
    from .geometry_render_resume import validate as prior_validate,_packages as prior_packages
    from .geometry_runtime_binding import _rebase_package
    oldjob=_object(_read(source['job']));prior,_=prior_validate(preparation_record,oldjob['runtime_continuation'],native)
    former=_path(prior['active_plugin_root']);oldpackages=prior_packages(_path(prior['original_plugin_root']),formal)
    if any(_rebase_package(prior.get(k),former,formal)!=v for k,v in oldpackages.items()):_fail()
    packages=_packages(formal,active);_request(request_record,preparation_record,source,native)
    payload={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],
             'source':source_record,'request':request_record,'recovery_grant':recovery_grant_record,
             'authority':{'authority':'current_user_instruction','instruction':instruction},'source_closure':_closure(source,details,native),**packages}
    path=native.root/_AUTH;descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(native._canonical({'payload':payload,'signature':_sign(native,payload)})+b'\n');stream.flush();os.fsync(stream.fileno())
    record=file_record(path);validate(preparation_record,record,native);return record


def _effective(preparation_record,runtime_root):
    prep,native=_context(preparation_record);runtime=_path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.8')/'runtime':_fail()
    record=file_record(native.root/_AUTH);payload,details=validate(preparation_record,record,native)
    if native._read().get('geometry_nuke_recovery')!=payload['recovery_grant']:_fail()
    packages=_packages(_path(payload['original_plugin_root']),runtime.parent)
    if any(payload.get(k)!=v for k,v in packages.items()):_fail()
    native.collector_policy();native.check();return native,payload,record,details


def resolve_worker(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[1]['active_worker']
def authorization_record(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[2]
def verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root):
    native,payload,record,_=_effective(preparation_record,runtime_root);request=_object(_read(payload['request']))
    if authority_record!=record or plan!=request['new_plan'] or request_id!=request['request_id']:_fail()
    return record

def source_record_for_job(preparation_record,plan,request_id,authority_record,runtime_root):
    record=verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root)
    return _object(_read(record))['payload']['source']

def verify_job(job,native,*,for_execution=False,runtime_root=None):
    payload,details=validate(job['preparation'],job.get('runtime_continuation',{}),native);request=_object(_read(payload['request']))
    if (job.get('revision')!=1 or 'render_source' in job or 'source_checkpoint' in job
            or job.get('task_id')!=payload['task_id'] or job.get('operation_id')!=request['new_operation_id']
            or job.get('plan')!=request['new_plan'] or job.get('nuke_source')!=payload['source']
            or job.get('execution_worker')!=payload['active_worker']):_fail()
    if for_execution:
        _,_,record,_=_effective(job['preparation'],runtime_root)
        if record!=job['runtime_continuation']:_fail()
    return details
