"""只恢复已登记R2产物的Nuke保存与冷渲染；原几何、渲染和登记事实不改。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope,_accounting_lock
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from .geometry_render_resume import _path,_read,_object,_load,_source_closure
from .geometry_registration_resume import _context

_SOURCE='bridge.geometry-nuke-save-resume-source/1'
_SCHEMA='bridge.geometry-nuke-save-resume-authorization/1'
_AUTH='geometry-nuke-save-resume-authorization.json'
_DOMAIN=b'bridge.geometry-nuke-save-resume-authorization/1\x00'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_nuke_save_resume.py','runtime/tools/resume_geometry_nuke_save.py',
        'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_nuke_save_recovery.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_job','geometry_session','geometry_runtime_binding')}
_CHANGED|={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+n+'.py' for n in ('native_scope','geometry_recovery','geometry_budget_addendum','geometry_nuke_recovery')}
_CHANGED.add('runtime/packages/houdini-bridge/src/houdini_bridge/controlled_output.py')


def _fail():raise ValueError('GEOMETRY_NUKE_SAVE_RESUME_INVALID')


def _details(source,native,*,full_native=False):
    """先认证closed15许可及原typed2来源；此入口不能清闭或启动进程。"""
    fields={'schema','preparation','task_id','operation_id','job','execution_preparation','journal','error','budget_authority','budget_source','input_source','artifact','registration_authority','registration_source'}
    if (type(source) is not dict or set(source)!=fields or source.get('schema')!=_SOURCE
            or source.get('task_id')!=native.scope['task_id']):_fail()
    from dcc_task_runtime.geometry_nuke_save_recovery import validate as budget_validate
    low,_,closed=budget_validate(native,source['budget_authority'])
    if low['source']!=source['budget_source'] or low['preparation']!=source['preparation']:_fail()
    budget=_object(_read(low['source']));job=_object(_read(source['job']));directory=native.root/'jobs'/source['operation_id']
    if (source['job']!=budget['job'] or source['error']!=budget['error'] or source['journal']!=budget['journal']
            or source['input_source']!=budget['input_source'] or source['registration_authority']!=budget['registration_authority']
            or source['preparation']['path']!=str(native.root/'geometry-preparation.json') or source['preparation']!=job.get('preparation')
            or source['job']['path']!=str(directory/'job.json') or job.get('directory')!=str(directory)
            or job.get('operation_id')!=source['operation_id'] or job.get('revision')!=2
            or job.get('runtime_continuation')!=source['registration_authority'] or job.get('registration_source')!=source['registration_source']):_fail()
    from .geometry_registration_resume import verify_job,validate as registration_validate
    original=verify_job(job,native);registration,_=registration_validate(source['preparation'],source['registration_authority'],native)
    prep=_object(_read(source['preparation']));jobprep=_object(_read(source['execution_preparation']))
    journal=_object(_read(source['journal']));stages=journal['stages'];artifact=stages['register']['result'];input2=_object(_read(source['input_source']))
    if (source['execution_preparation']['path']!=str(directory/'job-preparation.json') or jobprep.get('job')!=source['job']
            or jobprep.get('project')!=original['project'] or jobprep.get('control')!=original['control']
            or jobprep.get('consumer_runtime')!=registration['registration_runtime']
            or artifact!=source['artifact'] or artifact.get('artifact_id')!='geometry_main' or artifact.get('version')!=2
            or artifact.get('registry_operation_receipt')!=input2.get('registry_operation_receipt')
            or stages['input_preflight']['result']!={'state':'PASS','registry_operation_receipt':artifact['registry_operation_receipt']}
            or source['input_source']['path']!=str(Path(original['control'])/'geometry-input-source.json')):_fail()
    from nuke_bridge.task_host import _geometry_source_binding,input_artifact_registry
    _geometry_source_binding(input2,native,prep['task_id'])
    details={**original,'artifact':copy.deepcopy(artifact),'source_record':source['input_source'],
             'failed_save_operation_id':source['operation_id'],'original_registration_source':source['registration_source'],
             'accounting_prefix':_object(_read(source['registration_source']))['journal_prefix'],
             'accounting_envelope':_object(_read(source['registration_source']))['accounting_envelope']}
    if full_native:
        before=native._read();raw=native.journal_path.read_bytes()
        if before!=closed:_fail()
        registry=input_artifact_registry(input2,scope=native,task_id=prep['task_id'],observe_completed=True)
        if (registry.verify_operation_receipt(artifact['registry_operation_receipt'])!=artifact['registry_operation_receipt']
                or registry.lookup('geometry_main')!=artifact or not registry.verify('geometry_main').get('usable')):_fail()
        if native._read()!=before or native.journal_path.read_bytes()!=raw:_fail()
    return details


def inspect_source(failed_job_path,*,budget_authority):
    """零原生完整预检；调用者须先签许可，仍保持原closed15。"""
    path=_path(failed_job_path);job=_load(path);prep,native=_context(job['preparation']);directory=path.parent
    from dcc_task_runtime.geometry_nuke_save_recovery import validate as budget_validate
    low,_,_=budget_validate(native,budget_authority);budget=_object(_read(low['source']))
    journal=_load(directory/'incremental-state.json')
    source={'schema':_SOURCE,'preparation':job['preparation'],'task_id':job['task_id'],'operation_id':job['operation_id'],
        'job':file_record(path),'execution_preparation':file_record(directory/'job-preparation.json'),
        'journal':file_record(directory/'incremental-state.json'),'error':file_record(directory/'error.json'),
        'budget_authority':budget_authority,'budget_source':low['source'],'input_source':budget['input_source'],
        'artifact':journal['stages']['register']['result'],'registration_authority':job['runtime_continuation'],
        'registration_source':job['registration_source']}
    _details(source,native,full_native=True);return source


def _closure(source,details,native):
    fixed=copy.deepcopy(details);fixed.pop('accounting_prefix');fixed.pop('accounting_envelope')
    return _source_closure(source,fixed,native)


def _packages(original,active):
    """041只允许已审核的保存恢复改动，040后台连接和已有工具保持原件。"""
    from .geometry_runtime_binding import _package
    old,of,osources=_package(original,'0.4.0');new,nf,nsources=_package(active,'0.4.1')
    changed={n for n in of if n in nf and of[n]!=nf[n]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':osources+nsources,
        'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
        'differences':[{'name':n,'before':file_record(original/n) if n in of else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}


def _consumer(root):
    from .geometry_runtime_binding import _package
    _,_,sources=_package(root,'0.4.1');return {'package_root':str(root),'package_sources':sources}


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest();return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _request(record,preparation,source,native):
    r=_object(_read(record));job=_object(_read(source['job']));plan=copy.deepcopy(job['plan']);plan['plan_id']+='_nuke_save_resume01'
    plan['operator_repair']={'schema':'bridge.geometry-nuke-save-resume/1','failed_operation_id':job['operation_id'],'authorization_path':str(native.root/_AUTH)}
    plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'});rid='operator_nuke_save_resume01_'+job['operation_id'];op='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
    if (set(r)!={'schema','preparation','task_id','failed_operation_id','failed_job','nuke_save_source','new_plan','request_id','new_operation_id','original_plan_sha256'}
            or record['path']!=str(native.root/'geometry-nuke-save-resume-request.json') or r.get('schema')!='bridge.geometry-nuke-save-resume-request/1'
            or r.get('preparation')!=preparation or r.get('task_id')!=native.scope['task_id'] or r.get('failed_operation_id')!=job['operation_id']
            or r.get('failed_job')!=source['job'] or _object(_read(r['nuke_save_source']))!=source
            or r['nuke_save_source']['path']!=str(native.root/'geometry-nuke-save-resume-source.json')
            or r.get('new_plan')!=plan or r.get('request_id')!=rid or r.get('new_operation_id')!=op or r.get('original_plan_sha256')!=job['plan']['plan_sha256']):_fail()
    return r


def validate(preparation_record,authority,native=None):
    """历史验证只读签名前缀与固定正式源，不依赖已卸载的旧039缓存。"""
    if authority.get('path')==str(Path(preparation_record['path']).parent/'geometry-nuke-save-runtime-successor-authorization.json'):
        from .geometry_nuke_save_runtime_successor import validate as validate_successor
        return validate_successor(preparation_record,authority,native)
    prep,current=_context(preparation_record);native=current if native is None else native
    if authority.get('path')!=str(native.root/_AUTH) or _path(authority['path']).stat().st_mode&0o077:_fail()
    v=_object(_read(authority));p=v.get('payload')
    fields={'schema','preparation','native_scope','task_id','source','request','authority','source_closure','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(v)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(v['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation_record or p.get('native_scope')!=native.binding or p.get('task_id')!=prep['task_id']
            or p.get('source',{}).get('path')!=str(native.root/'geometry-nuke-save-resume-source.json')
            or set(p.get('authority',{}))!={'authority','instruction'} or p['authority']['authority']!='current_user_instruction'
            or not isinstance(p['authority'].get('instruction'),str) or not 10<=len(p['authority']['instruction'])<=16000):_fail()
    source=_object(_read(p['source']));details=_details(source,native)
    if (p['source_closure']!=_closure(source,details,native) or p['consumer_runtime']!=_consumer(_path(p['consumer_runtime']['package_root']))):_fail()
    _request(p['request'],preparation_record,source,native);return p,details


def create_authorization(preparation_record,original040formal,active041cache,execution041formal,failed_job_path,source_record,request_record,instruction):
    prep,native=_context(preparation_record);original=_path(original040formal);active=_path(active041cache);execution=_path(execution041formal)
    if (active!=Path(prep['worker']).parents[2].with_name('0.4.1') or not isinstance(instruction,str) or not 10<=len(instruction)<=16000):_fail()
    source=_object(_read(source_record));details=_details(source,native,full_native=True)
    if source['job']!=file_record(_path(failed_job_path)) or source['preparation']!=preparation_record:_fail()
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.1');b,bf,_=_package(execution,'0.4.1')
    if a!=b or af!=bf or execution==active or execution.is_relative_to(native.root):_fail()
    _request(request_record,preparation_record,source,native)
    p={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'request':request_record,
        'authority':{'authority':'current_user_instruction','instruction':instruction},'source_closure':_closure(source,details,native),
        'consumer_runtime':_consumer(execution),**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    record=file_record(path);validate(preparation_record,record,native);return record


def _effective(preparation_record,runtime_root):
    prep,native=_context(preparation_record);runtime=_path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.1')/'runtime':_fail()
    record=file_record(native.root/_AUTH);p,details=validate(preparation_record,record,native)
    packages=_packages(_path(p['original_plugin_root']),runtime.parent)
    if any(p.get(k)!=v for k,v in packages.items()):_fail()
    native.check();return native,p,record,details


def resolve_worker(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[1]['active_worker']
def authorization_record(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[2]

def verify_operator_dispatch(preparation_record,plan,request_id,authority,runtime_root):
    native,p,record,_=_effective(preparation_record,runtime_root);r=_object(_read(p['request']))
    if authority!=record or plan!=r['new_plan'] or request_id!=r['request_id']:_fail()
    return record

def source_record_for_job(preparation_record,plan,request_id,authority,runtime_root):
    record=verify_operator_dispatch(preparation_record,plan,request_id,authority,runtime_root);return _object(_read(record))['payload']['source']

def verify_job(job,native,*,for_execution=False,runtime_root=None):
    if (job.get('runtime_continuation') or {}).get('path')==str(native.root/'geometry-nuke-save-runtime-successor-authorization.json'):
        from .geometry_nuke_save_runtime_successor import verify_job as verify_successor_job
        return verify_successor_job(job,native,for_execution=for_execution,runtime_root=runtime_root)
    p,details=validate(job['preparation'],job.get('runtime_continuation',{}),native);r=_object(_read(p['request']))
    if (job.get('revision')!=2 or any(n in job for n in ('render_source','nuke_source','source_checkpoint','registration_source')) or job.get('task_id')!=p['task_id']
            or job.get('operation_id')!=r['new_operation_id'] or job.get('plan')!=r['new_plan'] or job.get('nuke_save_source')!=p['source']
            or job.get('execution_worker')!=p['active_worker']):_fail()
    if for_execution and _effective(job['preparation'],runtime_root)[2]!=job['runtime_continuation']:_fail()
    return details
