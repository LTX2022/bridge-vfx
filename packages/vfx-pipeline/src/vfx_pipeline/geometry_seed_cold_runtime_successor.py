"""044零原生预检后的045执行代码后继；同计划、同操作、原费用及定稿证明保持。"""
from __future__ import annotations
import copy,hashlib,hmac,os
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import file_record
from .geometry_render_resume import _path,_read,_object,_load
from .geometry_registration_resume import _context
_SCHEMA='bridge.geometry-seed-cold-runtime-successor/1'
_SOURCE='bridge.geometry-seed-cold-runtime-source/1'
_AUTH='geometry-seed-cold-runtime-successor-authorization.json'
_SOURCE_NAME='geometry-seed-cold-runtime-successor-source.json'
_DOMAIN=b'bridge.geometry-seed-cold-runtime-successor/1\x00'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_seed_cold_runtime_successor.py','runtime/tools/migrate_geometry_seed_cold_runtime.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_seed_cold_resume','geometry_session','geometry_runtime_binding')}
_CHANGED|={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+n+'.py' for n in ('geometry_nuke_recovery','geometry_nuke_save_recovery','geometry_seed_cold_recovery')}
_CHANGED.add('runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py')

def _fail():raise ValueError('GEOMETRY_SEED_COLD_RUNTIME_SUCCESSOR_INVALID')
def _sign(native,p):return hmac.new(hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()

def _packages(original,active):
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.4');b,bf,brs=_package(active,'0.4.5');changed={n for n in af if n in bf and af[n]!=bf[n]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {k:v for k,v in a.items() if k!='version'}!={k:v for k,v in b.items() if k!='version'}
            or set(af)-set(bf) or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,
            'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
            'differences':[{'name':n,'before':file_record(original/n) if n in af else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}

def _predecessor(preparation,authority,native,formal):
    from . import geometry_seed_cold_resume as old
    from .geometry_runtime_binding import _rebase_package
    p,source=old._validate_original(preparation,authority,native)
    if authority['path']!=str(native.root/old._AUTH):_fail()
    packages=old._packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=v for k,v in packages.items()):_fail()
    if p['consumer_runtime']['package_root']!=str(formal):_fail()
    old._verify_finalization(preparation,authority,source['nk_binding'])
    context=Path(source['producer']['control'])/'cold-context.json'
    expected={'schema':'bridge.geometry-cold-context/1','native_scope':native.binding,'task_id':native.scope['task_id'],'input_artifact_source':source['input_source']}
    if _load(context)!=expected:_fail()
    return p,source,file_record(context)

def _source(source,native,p,original,*,creation=False):
    from dcc_task_runtime import geometry_seed_cold_recovery as low
    fields={'schema','preparation','task_id','predecessor_authorization','request','input_source','budget_authority','finalization','cold_context','evidence','session_state','accounting_envelope','journal_prefix'}
    if (set(source)!=fields or source['schema']!=_SOURCE or source['preparation']!=p['preparation'] or source['task_id']!=p['task_id']
            or source['predecessor_authorization']!=file_record(native.root/'geometry-seed-cold-resume-authorization.json')
            or source['request']!=p['request'] or source['input_source']!=original['input_source'] or source['budget_authority']!=original['budget_authority']
            or source['finalization']!=file_record(native.root/'geometry-seed-cold-finalization.json')
            or source['cold_context']!=file_record(Path(original['producer']['control'])/'cold-context.json')):_fail()
    if type(source['evidence']) is not dict or set(source['evidence'])!={'readonly_failure','factory_diagnostic'}:_fail()
    evidence={name:_object(_read(record)) for name,record in source['evidence'].items()}
    for report in evidence.values():
        if report.get('native_started')!=0 or report.get('real_job_created') is not False or report.get('scope_persist_calls')!=0 or report.get('source_fact_stubs') is not False:_fail()
    failure=evidence['readonly_failure'];diagnostic=evidence['factory_diagnostic']
    if (failure.get('schema')!='bridge.nuke044-actual-cold-observation-failure/1' or failure.get('status')!='FAIL_PERFORMANCE'
            or failure.get('execution_authorized') is not False or failure.get('completed_full_factories')!=0
            or diagnostic.get('schema')!='bridge.nuke044-direct-factory-diagnostic/1' or diagnostic.get('status')!='PASS_DIAGNOSTIC_ONLY'
            or diagnostic.get('read_capture_used') is not False or diagnostic.get('cold_chain_pass') is not False):_fail()
    # 两份证据仅记录零原生观测和性能诊断；不能据此增加启动次数或改变原失败账目。
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    frozen=_prefix(native,source['journal_prefix'],source['accounting_envelope'])['state'];_,_,closed=low.validate(native,original['budget_authority'])
    if frozen!=closed or 'geometry_seed_cold_recovery' in frozen or len(frozen['tickets'])!=16:_fail()
    request=_object(_read(p['request']));op=request['new_operation_id'];rid=request['request_id'];plan=request['new_plan'];pid=plan['plan_id'];live=_load(native.root/'geometry-state.json');state=source['session_state'];current=native._read()
    if (state.get('preparation')!=p['preparation'] or state.get('task_id')!=p['task_id'] or state.get('revision')!=1 or len(state.get('completed',[]))!=1
            or op in state.get('jobs',{}) or pid in state.get('plans',{}) or rid in state.get('execution_requests',{}) or pid in state.get('plan_operations',{})
            or any(j.get('state') not in ('COMPLETE','FAILED','CANCELLED') for j in state.get('jobs',{}).values())
            or current['tickets'][:16]!=closed['tickets']):_fail()
    directory=native.root/'jobs'/op;dispatch=native.root/'geometry-seed-cold-resume-dispatch.json';output=_path(original['nk_binding']['output_pattern']%1)
    if creation:
        if current!=closed or live!=state or any(path.exists() or path.is_symlink() for path in (directory,dispatch,output)):_fail()
    else:
        for section in ('plans','jobs','execution_requests','plan_operations'):
            if any(live.get(section,{}).get(k)!=v for k,v in state[section].items()):_fail()
        if live.get('preparation')!=p['preparation'] or live.get('task_id')!=p['task_id']:_fail()
        if op not in live['jobs']:
            expected=copy.deepcopy(state)
            if pid in live['plans']:expected['plans'][pid]=plan
            open16=dict(closed,closed_reason=None,geometry_seed_cold_recovery=original['budget_authority'])
            if live!=expected or directory.exists() or current not in (closed,open16):_fail()
        else:
            if (set(live['jobs'])!=set(state['jobs'])|{op} or set(live['plans'])!=set(state['plans'])|{pid}
                    or live['plans'][pid]!=plan or set(live['execution_requests'])!=set(state['execution_requests'])|{rid}
                    or set(live['plan_operations'])!=set(state['plan_operations'])|{pid}
                    or live['execution_requests'][rid]!={'request_sha256':canonical_sha256({'plan_id':pid}),'operation_id':op} or live['plan_operations'][pid]!=op):_fail()
    return request

def inspect_source(preparation,formal044,readonly_failure,factory_diagnostic):
    """只冻结已认证044原件和closed16，没有HOM重放、预算签发或原生启动。"""
    _,native=_context(preparation);authority=file_record(native.root/'geometry-seed-cold-resume-authorization.json');p,original,context=_predecessor(preparation,authority,native,_path(formal044));raw=native.journal_path.read_bytes()
    value={'schema':_SOURCE,'preparation':preparation,'task_id':p['task_id'],'predecessor_authorization':authority,'request':p['request'],'input_source':original['input_source'],'budget_authority':original['budget_authority'],
           'finalization':file_record(native.root/'geometry-seed-cold-finalization.json'),'cold_context':context,'evidence':{'readonly_failure':readonly_failure,'factory_diagnostic':factory_diagnostic},
           'session_state':_load(native.root/'geometry-state.json'),'accounting_envelope':_load(native.state_path),'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
    _source(value,native,p,original,creation=True);return value

def validate(preparation,record,native=None):
    _,n=_context(preparation);native=n if native is None else native
    if record.get('path')!=str(native.root/_AUTH) or _path(record['path']).stat().st_mode&0o077:_fail()
    value=_object(_read(record));p=value.get('payload');fields={'schema','preparation','native_scope','task_id','predecessor_authorization','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(value)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p['schema']!=_SCHEMA or p['preparation']!=preparation or p['native_scope']!=native.binding or p['task_id']!=native.scope['task_id'] or p['source']['path']!=str(native.root/_SOURCE_NAME)):_fail()
    old,original,_=_predecessor(preparation,p['predecessor_authorization'],native,_path(p['original_plugin_root']));source=_object(_read(p['source']));_source(source,native,old,original)
    if source['predecessor_authorization']!=p['predecessor_authorization']:_fail()
    from .geometry_runtime_binding import _package,_rebase_package
    formal=_path(p['consumer_runtime']['package_root']);_,_,sources=_package(formal,'0.4.5')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':sources}:_fail()
    packages=_packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=v for k,v in packages.items()):_fail()
    request=_object(_read(old['request']));jobpath=native.root/'jobs'/request['new_operation_id']/'job.json'
    if jobpath.exists():
        job=_load(jobpath)
        if job.get('runtime_continuation')!=record or job.get('execution_worker')!=p['active_worker']:_fail()
    effective=copy.deepcopy(old);effective.update(active_worker=p['active_worker'],consumer_runtime=p['consumer_runtime'],finalization_authority=p['predecessor_authorization'])
    effective['readset']=[*old['readset'],p['source'],p['predecessor_authorization'],source['finalization'],source['cold_context'],*source['evidence'].values(),*packages['package_sources']]
    return effective,original

def create_authorization(preparation,source_record,formal044,active045,formal045):
    """仅签同操作的新消费者证明；原low许可保持未激活，原定稿授权保持044。"""
    prep,native=_context(preparation);original=_path(formal044);active=_path(active045);formal=_path(formal045)
    if active!=Path(prep['worker']).parents[2].with_name('0.4.5') or source_record['path']!=str(native.root/_SOURCE_NAME):_fail()
    source=_object(_read(source_record));old,previous,_=_predecessor(preparation,source['predecessor_authorization'],native,original);_source(source,native,old,previous,creation=True);packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.5');b,bf,sources=_package(formal,'0.4.5')
    if a!=b or af!=bf or active==formal or formal.is_relative_to(native.root):_fail()
    payload={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'predecessor_authorization':source['predecessor_authorization'],'source':source_record,
             'consumer_runtime':{'package_root':str(formal),'package_sources':sources},**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':payload,'signature':_sign(native,payload)})+b'\n');f.flush();os.fsync(f.fileno())
    return file_record(path)

def effective(preparation,runtime,authority):
    prep,native=_context(preparation);runtime=_path(runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.5')/'runtime' or authority!=file_record(native.root/_AUTH):_fail()
    value,source=validate(preparation,authority,native);proof=_object(_read(authority))['payload'];packages=_packages(_path(proof['original_plugin_root']),runtime.parent)
    if any(proof[k]!=v for k,v in packages.items()):_fail()
    native.check();return value,source
