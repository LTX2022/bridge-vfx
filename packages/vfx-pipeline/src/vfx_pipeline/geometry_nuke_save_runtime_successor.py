"""041未派发保存尾段的042执行代码后继；同计划、同操作、原预算及产物来源不变。"""
from __future__ import annotations
import copy,hashlib,hmac,json,math,os,time
from dataclasses import dataclass
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope,_accounting_lock
from dcc_task_runtime.platform_support import process_status
from houdini_bridge.official_karma_observation import file_record
from .geometry_render_resume import _path,_read,_object,_load

_SCHEMA='bridge.geometry-nuke-save-runtime-successor/1'
_SOURCE='bridge.geometry-nuke-save-runtime-source/1'
_AUTH='geometry-nuke-save-runtime-successor-authorization.json'
_DOMAIN=b'bridge.geometry-nuke-save-runtime-successor/1\x00'
_AUDIT='geometry-nuke-save-runtime-successor-audit'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_nuke_save_runtime_successor.py','runtime/tools/migrate_geometry_nuke_save_runtime.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_nuke_save_resume','geometry_session','geometry_runtime_binding')}
_CHANGED.add('runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py')
_TOKEN=object()


def _fail():raise ValueError('GEOMETRY_NUKE_SAVE_RUNTIME_SUCCESSOR_INVALID')


def _sign(native,p):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest();return hmac.new(key,native._canonical(p),hashlib.sha256).hexdigest()


def _packages(original,active):
    from .geometry_runtime_binding import _package
    old,of,osources=_package(original,'0.4.1');new,nf,nsources=_package(active,'0.4.2');changed={k for k in of if k in nf and of[k]!=nf[k]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':osources+nsources,
        'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
        'differences':[{'name':n,'before':file_record(original/n) if n in of else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}


def _predecessor(preparation,authority,native,formal):
    """旧041完整签名和source保持原件；只把已签cache路径精确重定位到永久正式包。"""
    from . import geometry_nuke_save_resume as old
    from .geometry_runtime_binding import _rebase_package
    p,details=old.validate(preparation,authority,native)
    if authority['path']!=str(native.root/'geometry-nuke-save-resume-authorization.json'):_fail()
    former=_path(p['active_plugin_root']);packages=old._packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],former,formal)!=value for k,value in packages.items()):_fail()
    if p['consumer_runtime']!=old._consumer(formal):_fail()
    return p,details


def _stop(record,native,p,*,creation=False):
    value=_object(_read(record));operator=value.get('operator') or {};ended=value.get('termination') or {}
    identity=operator.get('process_identity') or {};argv=operator.get('argv');request=_object(_read(p['request']))
    expected=str(Path(p['active_plugin_root'])/'runtime/tools/resume_geometry_nuke_save.py')
    if (record['path']!=str(native.root/_AUDIT/'metadata-stop.json') or value.get('schema')!='bridge.geometry-nuke-save-metadata-stop/1'
            or value.get('preparation')!=p['preparation'] or value.get('operation_id')!=request['new_operation_id']
            or type(operator.get('pid')) is not int or identity.get('pid')!=operator['pid']
            or identity.get('state')!='alive' or not isinstance(identity.get('birth'),str) or not identity['birth']
            or not isinstance(argv,list) or not all(isinstance(v,str) for v in argv) or argv.count(expected)!=1
            or '--job' not in argv or argv.index('--job')+1>=len(argv) or argv[argv.index('--job')+1]!=request['failed_job']['path']
            or ended.get('observed_by')!='parent_exec_wait' or type(ended.get('session_id')) is not int
            or type(ended.get('exit_code')) is not int or type(ended.get('observed_at')) not in (int,float)
            or not math.isfinite(ended['observed_at']) or ended['observed_at']>time.time()+1
            or (value.get('post_identity') or {}).get('pid')!=operator['pid'] or value['post_identity'].get('state')!='stopped'):_fail()
    raw=value.get('raw_observation') or {}
    if not _path(raw.get('path','')).is_relative_to(native.root/_AUDIT):_fail()
    _read(raw)
    if creation and process_status(identity)!='stopped':_fail()
    return value


def _dispatch(record,native,p):
    value=_object(_read(record));body=value.get('payload');key=hmac.new(native._key(),b'bridge.geometry-nuke-save-dispatch/1\x00',hashlib.sha256).digest();request=_object(_read(p['request']))
    if (record['path']!=str(native.root/'geometry-nuke-save-resume-dispatch.json') or set(value)!={'payload','signature'} or type(body) is not dict
            or not hmac.compare_digest(str(value['signature']),hmac.new(key,native._canonical(body),hashlib.sha256).hexdigest())
            or body.get('schema')!='bridge.geometry-nuke-save-dispatch/1' or body.get('state')!='INTENT'
            or body.get('preparation')!=p['preparation'] or body.get('request')!=p['request']
            or body.get('authority')!=file_record(native.root/'geometry-nuke-save-resume-authorization.json')
            or body.get('operation_id')!=request['new_operation_id'] or body.get('failed_job')!=request['failed_job']
            or 'accepted' in body):_fail()
    source=_object(_read(p['source']))
    if body.get('budget_authority')!=source['budget_authority']:_fail()
    return request


def _source(source,native,p,*,creation=False):
    fields={'schema','preparation','task_id','predecessor_authorization','dispatch','metadata_stop','request','session_state','accounting_envelope','journal_prefix'}
    if (type(source) is not dict or set(source)!=fields or source.get('schema')!=_SOURCE or source.get('preparation')!=p['preparation']
            or source.get('task_id')!=p['task_id'] or source['predecessor_authorization']!=file_record(native.root/'geometry-nuke-save-resume-authorization.json')):_fail()
    if source.get('request')!=p['request']:_fail()
    request=_dispatch(source['dispatch'],native,p);_stop(source['metadata_stop'],native,p,creation=creation)
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    from dcc_task_runtime.geometry_nuke_save_recovery import validate as permit_validate
    original=_prefix(native,source['journal_prefix'],source['accounting_envelope'])['state']
    oldsource=_object(_read(p['source']));_,_,closed=permit_validate(native,oldsource['budget_authority'])
    expected=copy.deepcopy(closed);expected.update(closed_reason=None,geometry_nuke_save_recovery=oldsource['budget_authority'])
    current=native._read();frozen=source['session_state'];live=_load(native.root/'geometry-state.json');operation=request['new_operation_id'];plan=request['new_plan'];rid=request['request_id'];planid=plan['plan_id'];directory=native.root/'jobs'/operation
    if (original!=expected or len(original['tickets'])!=15 or current['tickets'][:15]!=original['tickets']
            or frozen.get('preparation')!=p['preparation'] or frozen.get('task_id')!=p['task_id'] or frozen.get('revision')!=1 or len(frozen.get('completed',[]))!=1
            or frozen.get('plans',{}).get(planid)!=plan or operation in frozen.get('jobs',{}) or rid in frozen.get('execution_requests',{})
            or planid in frozen.get('plan_operations',{}) or any(j.get('state') not in ('COMPLETE','FAILED','CANCELLED') for j in frozen.get('jobs',{}).values())):_fail()
    if creation:
        if current!=original or live!=frozen or directory.exists() or directory.is_symlink():_fail()
    else:
        for section in ('plans','jobs','execution_requests','plan_operations'):
            if any(live.get(section,{}).get(k)!=v for k,v in frozen[section].items()):_fail()
        if live.get('preparation')!=p['preparation'] or live.get('task_id')!=p['task_id']:_fail()
        if operation not in live.get('jobs',{}):
            if live!=frozen or directory.exists() or current!=original:_fail()
        else:
            if (set(live['jobs'])!=set(frozen['jobs'])|{operation} or set(live['plans'])!=set(frozen['plans'])
                    or set(live['execution_requests'])!=set(frozen['execution_requests'])|{rid}
                    or set(live['plan_operations'])!=set(frozen['plan_operations'])|{planid}
                    or live['plan_operations'][planid]!=operation
                    or live['execution_requests'][rid]!={'request_sha256':canonical_sha256({'plan_id':planid}),'operation_id':operation}):_fail()
            job=_load(directory/'job.json');entry=live['jobs'][operation]
            if (entry.get('job_file')!=file_record(directory/'job.json') or job.get('plan')!=plan or job.get('preparation')!=p['preparation']
                    or job.get('operation_id')!=operation or job.get('task_id')!=p['task_id'] or job.get('directory')!=str(directory)
                    or job.get('nuke_save_source')!=p['source'] or job.get('revision')!=2):_fail()
    return request


def inspect_source(preparation,metadata_stop,formal041):
    """停止旧metadata后由调用者持会话锁冻结真实no-job/十五票开放状态，不签许可。"""
    from .geometry_nuke_save_resume import _context
    prep,native=_context(preparation);authority=file_record(native.root/'geometry-nuke-save-resume-authorization.json')
    p,_=_predecessor(preparation,authority,native,_path(formal041));raw=native.journal_path.read_bytes()
    source={'schema':_SOURCE,'preparation':preparation,'task_id':prep['task_id'],'predecessor_authorization':authority,
        'dispatch':file_record(native.root/'geometry-nuke-save-resume-dispatch.json'),'metadata_stop':metadata_stop,'request':p['request'],
        'session_state':_load(native.root/'geometry-state.json'),'accounting_envelope':_load(native.state_path),
        'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
    _source(source,native,p,creation=True);return source


def validate(preparation,record,native=None):
    from .geometry_nuke_save_resume import _context,_consumer
    prep,current=_context(preparation);native=current if native is None else native
    if record.get('path')!=str(native.root/_AUTH) or _path(record['path']).stat().st_mode&0o077:_fail()
    value=_object(_read(record));p=value.get('payload');fields={'schema','preparation','native_scope','task_id','predecessor_authorization','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(value)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation or p.get('native_scope')!=native.binding or p.get('task_id')!=prep['task_id']
            or p['source'].get('path')!=str(native.root/'geometry-nuke-save-runtime-successor-source.json')):_fail()
    old,details=_predecessor(preparation,p['predecessor_authorization'],native,_path(p['original_plugin_root']))
    source=_object(_read(p['source']));_source(source,native,old)
    if source['predecessor_authorization']!=p['predecessor_authorization']:_fail()
    formal=_path(p['consumer_runtime']['package_root'])
    from .geometry_runtime_binding import _package
    _,_,sources=_package(formal,'0.4.2')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':sources}:_fail()
    from .geometry_runtime_binding import _rebase_package
    historical=_packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=v for k,v in historical.items()):_fail()
    request=_object(_read(old['request']));jobpath=native.root/'jobs'/request['new_operation_id']/'job.json'
    if jobpath.exists():
        job=_load(jobpath)
        if job.get('runtime_continuation')!=record or job.get('execution_worker')!=p['active_worker']:_fail()
    effective=copy.deepcopy(old);effective.update(active_worker=p['active_worker'],consumer_runtime=p['consumer_runtime'])
    return effective,details


def create_authorization(preparation,source_record,formal041,active042,formal042):
    """仅签执行代码迁移证明；不重签预算、不清闭、不更换plan/request/op。"""
    from .geometry_nuke_save_resume import _context
    prep,native=_context(preparation);original=_path(formal041);active=_path(active042);formal=_path(formal042)
    if active!=Path(prep['worker']).parents[2].with_name('0.4.2'):_fail()
    source=_object(_read(source_record));old,_=_predecessor(preparation,source['predecessor_authorization'],native,original);_source(source,native,old,creation=True)
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.2');b,bf,sources=_package(formal,'0.4.2')
    if a!=b or af!=bf or formal==active or formal.is_relative_to(native.root):_fail()
    p={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],
        'predecessor_authorization':source['predecessor_authorization'],'source':source_record,
        'consumer_runtime':{'package_root':str(formal),'package_sources':sources},**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    return file_record(path)


@dataclass(frozen=True)
class _Dispatch:
    token:object
    preparation:dict
    worker:dict
    authority:dict
    source:dict
    payload:dict
    details:dict


def _effective(preparation,runtime,authority):
    from .geometry_nuke_save_resume import _context
    prep,native=_context(preparation);runtime=_path(runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.2')/'runtime' or authority!=file_record(native.root/_AUTH):_fail()
    effective,details=validate(preparation,authority,native);proof=_object(_read(authority))['payload'];packages=_packages(_path(proof['original_plugin_root']),runtime.parent)
    if any(proof.get(k)!=v for k,v in packages.items()):_fail()
    native.check();return effective,details


def resolve_dispatch(preparation,plan,request_id,authority,runtime):
    """每次execute独立完整认证一次；对象只在可信Python调用栈内使用，不能经MCP提交。"""
    if type(authority) is not dict:_fail()
    p,details=_effective(preparation,runtime,authority);request=_object(_read(p['request']))
    if plan!=request['new_plan'] or request_id!=request['request_id']:_fail()
    return _Dispatch(_TOKEN,copy.deepcopy(preparation),p['active_worker'],authority,p['source'],p,details)


def dispatch_worker(preparation,dispatch):
    if type(dispatch) is not _Dispatch or dispatch.token is not _TOKEN or dispatch.preparation!=preparation:_fail()
    _read(dispatch.authority);_read(dispatch.worker);return dispatch.worker


def resolve_runtime(preparation,runtime):
    from .geometry_nuke_save_resume import _context
    _,native=_context(preparation);authority=file_record(native.root/_AUTH);p,_=_effective(preparation,runtime,authority);return p['active_worker'],authority


def verify_job(job,native,*,for_execution=False,runtime_root=None):
    authority=job.get('runtime_continuation',{});p,details=(_effective(job['preparation'],runtime_root,authority) if for_execution else validate(job['preparation'],authority,native))
    r=_object(_read(p['request']))
    if (job.get('revision')!=2 or any(k in job for k in ('registration_source','nuke_source','render_source','source_checkpoint'))
            or job.get('plan')!=r['new_plan'] or job.get('operation_id')!=r['new_operation_id'] or job.get('task_id')!=p['task_id']
            or job.get('nuke_save_source')!=p['source'] or job.get('execution_worker')!=p['active_worker']):_fail()
    return details
