"""一次性几何检查点恢复授权；保留原关闭记账，只追加明确授权的状态。"""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

_SCHEMA='bridge.geometry-recovery-authorization/1'
_DOMAIN=b'bridge.geometry-recovery-authorization/1\x00'
_CHANGED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+n+'.py' for n in
          ('native_scope','platform_support','owned_process','process_image','window_trace','startup_trace')}
_CHANGED|={'runtime/packages/houdini-bridge/src/houdini_bridge/task_host.py'}
_CHANGED|={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in
           ('geometry_job','official_graph_resume','geometry_session','geometry_runtime_binding')}
_ADDED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_recovery.py',
        'runtime/tools/recover_geometry_checkpoint.py'}


def _fail():raise ValueError('GEOMETRY_RECOVERY_AUTHORIZATION_INVALID')


def _path(raw):
    p=Path(raw)
    if not p.is_absolute() or p!=p.resolve() or any(v.is_symlink() for v in (p,*p.parents)):_fail()
    return p


def _object(raw):
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:_fail()
            value[k]=v
        return value
    value=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict):_fail()
    return value


def _record(path):
    p=_path(path);raw=p.read_bytes()
    return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def _record_shape(record):
    """历史包/工具只核已签记录形状，不追踪已卸载cache或更新后的系统文件。"""
    if (not isinstance(record,dict) or set(record)!={'path','bytes','sha256'}
            or not isinstance(record['path'],str) or not Path(record['path']).is_absolute()
            or '\x00' in record['path'] or str(Path(os.path.normpath(record['path'])))!=record['path']
            or type(record['bytes']) is not int or record['bytes']<0
            or not isinstance(record['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',record['sha256'])):_fail()
    return record


def _bytes(record):
    if not isinstance(record,dict) or set(record)!={'path','bytes','sha256'} or _record(record['path'])!=record:_fail()
    return _path(record['path']).read_bytes()


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _scope(native):
    if (native.resource_profile!='h21_geometry_creative_14_1800_v1'
            or native.scope.get('scene_profile')!='bounded_geometry_rig_v1'
            or native.scope.get('versions')!={'houdini':'21.0.631','nuke':'17.0v1'}):_fail()


def _context(preparation_record):
    from .native_scope import NativeScope
    prep=_object(_bytes(preparation_record));native=NativeScope(prep['scope']);_scope(native)
    if (Path(preparation_record['path'])!=native.root/'geometry-preparation.json'
            or prep.get('schema')!='bridge.geometry-creative-preparation/1' or prep.get('task_id')!=native.scope['task_id']):_fail()
    return prep,native


def _packages(original,active):
    from vfx_pipeline.geometry_runtime_binding import _package
    if (original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes():_fail()
    old,of,osources=_package(original,'0.3.3');new,nf,nsources=_package(active,'0.3.4')
    changes={n for n in of if n in nf and of[n]!=nf[n]}
    if ({k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED or not changes<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':osources+nsources,
            'differences':[{'name':n,'before':_record(original/n) if n in of else None,'after':_record(active/n)}
                           for n in sorted(changes|_ADDED)],'active_worker':_record(active/'runtime/tools/run_geometry_creative.py')}


def _previous(preparation_record,prep,native,previous,formal):
    """完整历史分支只在首次创建时调用；不向已关闭范围请求执行准入。"""
    from vfx_pipeline import geometry_runtime_binding as b
    if Path(previous['path'])!=native.root/'runtime-continuation-v033.json':_fail()
    value=_object(_bytes(previous));p=value.get('payload')
    if (set(value)!={'payload','signature'} or not isinstance(p,dict)
            or not hmac.compare_digest(str(value['signature']),b._signature_v033(native,p))
            or p.get('preparation')!=preparation_record or p.get('native_scope')!=prep['scope']
            or p.get('task_id')!=prep['task_id']):_fail()
    former=_path(p['active_plugin_root']);packages=b._v033_packages(_path(p['original_plugin_root']),formal)
    if any(b._rebase_package(p.get(k),former,formal)!=v for k,v in packages.items()):_fail()
    if b._historical_v032(preparation_record,prep,native,p['history']['previous_binding'],_path(p['original_plugin_root']))!=p['history']:_fail()
    failure,job=b._failure_v033(preparation_record,prep,native,p['failure']['job']['path'],_path(p['original_plugin_root']),p['failure']['accounting'])
    if failure!=p['failure']:_fail()
    b._repair_request(p['repair_request'],preparation_record,prep,native,job)
    _bytes(p['source_session'])
    # 每次_read只需重读已经认证并签入本permit的原件，不递归构造NativeScope。
    records=[previous,p['history']['previous_binding'],p['repair_request'],p['source_session'],p['failure']['accounting']]
    records+=p['failure']['source_files']+packages['package_sources']
    for record in records:_bytes(record)
    return records


def _request(record,preparation_record,prep,native,failed_job,checkpoint):
    if Path(record['path'])!=native.root/'geometry-checkpoint-recovery-request.json':_fail()
    r=_object(_bytes(record));old=failed_job['plan']
    fields={'schema','preparation','task_id','failed_operation_id','failed_job','source_checkpoint','new_plan',
            'request_id','new_operation_id','original_plan_sha256'}
    expected=copy.deepcopy(old);expected['plan_id']=old['plan_id']+'_host_resume01'
    expected['operator_repair']={'schema':'bridge.geometry-operator-checkpoint-recovery/1',
        'failed_operation_id':failed_job['operation_id'],'authorization_path':str(native.root/'geometry-recovery-authorization.json')}
    expected['plan_sha256']=hashlib.sha256(native._canonical({k:v for k,v in expected.items() if k!='plan_sha256'})).hexdigest()
    request_id='operator_host_resume01_'+failed_job['operation_id']
    operation='geo_'+hashlib.sha256((request_id+expected['plan_sha256']).encode()).hexdigest()[:24]
    if (set(r)!=fields or r['schema']!='bridge.geometry-checkpoint-recovery-request/1'
            or r['preparation']!=preparation_record or r['task_id']!=prep['task_id']
            or r['failed_operation_id']!=failed_job['operation_id']
            or r['failed_job']!=_record(Path(failed_job['directory'])/'job.json') or r['source_checkpoint']!=checkpoint
            or r['original_plan_sha256']!=old['plan_sha256']
            or native._canonical(r['new_plan'])!=native._canonical(expected)
            or r['request_id']!=request_id or r['new_operation_id']!=operation):_fail()
    return r


def _closed(native,record):
    raw=_bytes(record);envelope=_object(raw);p=native._verify_envelope(envelope);state=p['state']
    lines=native.journal_path.read_bytes().splitlines()
    if (type(p.get('seq')) is not int or p['seq']>=len(lines) or lines[p['seq']]!=raw
            or state.get('scope_sha256')!=native.binding['sha256']
            or state.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or len(state.get('tickets',[]))!=3
            or [t['role'] for t in state['tickets']]!=['graph-worker','graph-worker','houdini-host']
            or any(t.get('stopped_at') is None for t in state['tickets'])
            or 'geometry_recovery_authorization' in state):_fail()
    from . import owned_process
    host=state['tickets'][2];directory=_path(host['directory']);start=owned_process.read_receipt(directory,'started',identity=host['identity'])
    stop=owned_process.read_receipt(directory,'stopped',identity=host['identity'])
    if (not start or not stop or native._stop(host)!=stop or owned_process.execution_returncode(stop)!=-15
            or host['stopped_at']!=stop['observed_at'] or host['stopped_sha256']!=hashlib.sha256(native._canonical(stop)).hexdigest()
            or start.get('writer_process_binding_error')!='ProcessImageError:PROCESS_IMAGE_TIMEOUT'):_fail()
    diag=start.get('writer_process_binding_diagnostic') or {};timing=diag.get('timing') or {}
    if (diag.get('schema')!='bridge.process-image.tool-diagnostic/1' or diag.get('reason')!='PROCESS_IMAGE_TIMEOUT'
            or diag.get('tool_argv')!=['/usr/bin/vmmap','-w','-interleaved','-summary',str(start['pid'])]
            or timing.get('tool_limit_seconds')!=5.0 or not 5.0<=timing.get('elapsed_seconds',0)<6.0
            or (diag.get('cleanup') or {}).get('leader_reaped') is not True):_fail()
    return p,state,[_record(directory/'started.json'),_record(directory/'stopped.json'),_record(directory/'intent.json')]


def _checkpoint_header(native,checkpoint):
    """原resume source的scope为完整FileRecord，保持其三字段合同。"""
    if (checkpoint.get('schema')!='bridge.geometry-graph-resume-source/1'
            or checkpoint.get('task_id')!=native.scope['task_id']
            or checkpoint.get('scope')!=_record(native.path)):_fail()
    _bytes(checkpoint['scope'])
    for record in checkpoint['source_files']+checkpoint['save_sidecars']:_bytes(record)
    return checkpoint


def _validate(native,record):
    """纯文件/HMAC核验，不调用NativeScope构造、_read或执行准入。"""
    _scope(native)
    if Path(record['path'])!=native.root/'geometry-recovery-authorization.json':_fail()
    path=_path(record['path'])
    if path.stat().st_mode&0o077:_fail()
    value=_object(_bytes(record));p=value.get('payload')
    if (set(value)!={'payload','signature'} or not isinstance(p,dict)
            or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('native_scope')!=native.binding
            or p.get('task_id')!=native.scope['task_id']
            or not isinstance(p.get('authority'),dict) or set(p['authority'])!={'authority','instruction'}
            or p['authority'].get('authority')!='current_user_instruction'
            or not isinstance(p['authority'].get('instruction'),str)
            or not 10<=len(p['authority']['instruction'])<=16000):_fail()
    prep=_object(_bytes(p['preparation']))
    if prep.get('scope')!=native.binding or prep.get('task_id')!=native.scope['task_id']:_fail()
    predecessor,state,diagnostic=_closed(native,p['closed_accounting'])
    if diagnostic!=p['diagnostic_files']:_fail()
    reuse=_object(_bytes(native.scope['source_reuse']));old=_object(_bytes(reuse['source_scope']))
    from .process_image import validate_collector_policy
    policy=validate_collector_policy(p['collector_policy'])
    if old.get('process_image_policy')!=policy or policy['policy']!='sample_header_v1':_fail()
    # 历史读保留工程原件核验；包/cache和系统工具的实字节门属于下一次执行。
    for record in p['source_files']:_bytes(record)
    for record in p['package_sources']:_record_shape(record)
    _record_shape(p['active_worker'])
    for difference in p['differences']:
        if difference['before'] is not None:_record_shape(difference['before'])
        _record_shape(difference['after'])
    checkpoint=_object(_bytes(p['source_checkpoint']));job=_object(_bytes(p['failed_job']))
    _checkpoint_header(native,checkpoint)
    _request(p['request'],p['preparation'],prep,native,job,p['source_checkpoint'])
    return p,predecessor,state


def verify_state(native,state):
    """验证每次明确恢复的唯一相邻跃迁；旧授权与已结算前缀始终保留。"""
    lines=native.journal_path.read_bytes().splitlines()
    rows=[native._verify_envelope(_object(line)) for line in lines]
    if 'geometry_recovery_authorization' not in state:
        if any('geometry_recovery_authorization' in row['state']
               or 'geometry_recovery_successor' in row['state'] for row in rows):_fail()
        return None
    record=state['geometry_recovery_authorization'];p,predecessor,closed=_validate(native,record)
    if state['tickets'][:3]!=closed['tickets']:_fail()
    index=predecessor['seq']+1
    if index>=len(rows):_fail()
    expected=copy.deepcopy(closed);expected.update(closed_reason=None,geometry_recovery_authorization=record)
    if rows[index].get('seq')!=index or rows[index].get('state')!=expected:_fail()
    successor=state.get('geometry_recovery_successor');second=None;second_index=None
    if successor is not None:
        from .geometry_recovery_successor import validate
        second,second_predecessor,second_closed=validate(native,successor)
        if second['previous_authorization']!=record:_fail()
        second_index=second_predecessor['seq']+1
        if second_index<=index or second_index>=len(rows):_fail()
        second_expected=copy.deepcopy(second_closed)
        second_expected.update(closed_reason=None,geometry_recovery_successor=successor)
        if (rows[second_index-1]['state']!=second_closed
                or rows[second_index].get('seq')!=second_index
                or rows[second_index]['state']!=second_expected):_fail()
    previous=expected
    for sequence,row in enumerate(rows[index+1:],start=index+1):
        later=row['state']
        if later.get('geometry_recovery_authorization')!=record or later['tickets'][:3]!=closed['tickets']:_fail()
        if second_index is not None and sequence>=second_index:
            if later.get('geometry_recovery_successor')!=successor or later['tickets'][:4]!=second_closed['tickets']:_fail()
        elif 'geometry_recovery_successor' in later:_fail()
        if (previous.get('closed_reason') is not None and later.get('closed_reason') is None
                and sequence!=second_index):
            from .geometry_nuke_recovery import allows_clear
            if not allows_clear(native,state,sequence,previous,later):
                from .geometry_nuke_save_recovery import allows_clear as save_clear
                if not save_clear(native,state,sequence,previous,later):
                    from .geometry_seed_cold_recovery import allows_clear as cold_clear
                    if not cold_clear(native,state,sequence,previous,later):_fail()
        previous=later
    return second if second is not None else p


def authorized_state(native,state,record):
    """只能从精确封存的首次关闭状态恢复一次，收费/票据逐字段保持。"""
    p,_,closed=_validate(native,record)
    if 'geometry_recovery_authorization' in state or state!=closed:_fail()
    _check_policy(p['collector_policy'])
    result=copy.deepcopy(state);result.update(closed_reason=None,geometry_recovery_authorization=record)
    return result


def _check_policy(policy):
    from .process_image import check_collector_tools
    import time
    check_collector_tools(policy,time.monotonic()+5)


def collector_policy(native,state):
    policy=verify_state(native,state)['collector_policy']
    _check_policy(policy)
    return policy


def _copy(path,raw):
    from .platform_support import ensure_private_directory
    path=_path(path);ensure_private_directory(path.parent)
    if path.exists():
        if path.read_bytes()!=raw:_fail()
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return _record(path)


def create_authorization(preparation_record,previous_v033_binding_record,original_v033_formal_plugin,
        active_v034_cache_plugin,failed_job_path,checkpoint_record,request_record,instruction):
    """操作者创建一次恢复许可；此函数本身不清闭或启动任何DCC。"""
    if not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip():_fail()
    prep,native=_context(preparation_record);formal=_path(original_v033_formal_plugin);active=_path(active_v034_cache_plugin)
    if (Path(prep['worker']).parents[2].name!='0.3.1'
            or active!=Path(prep['worker']).parents[2].with_name('0.3.4')):_fail()
    previous=_previous(preparation_record,prep,native,previous_v033_binding_record,formal)
    packages=_packages(formal,active);source=native.root/'geometry-recovery-source'
    closed=_copy(source/'closed-accounting.json',native.state_path.read_bytes());_,state,diagnostic=_closed(native,closed)
    if native._read()!=state:_fail()
    jobpath=_path(failed_job_path);job=_object(jobpath.read_bytes())
    if (jobpath!=native.root/'jobs'/job.get('operation_id','')/'job.json' or job.get('directory')!=str(jobpath.parent)
            or job.get('preparation')!=preparation_record or job.get('task_id')!=prep['task_id'] or job.get('revision')!=1):_fail()
    previous_payload=_object(_bytes(previous_v033_binding_record))['payload']
    previous_request=_object(_bytes(previous_payload['repair_request']))
    if (job.get('runtime_continuation')!=previous_v033_binding_record
            or job.get('execution_worker')!=previous_payload['active_worker']
            or job.get('operation_id')!=previous_request['new_operation_id']
            or native._canonical(job.get('plan'))!=native._canonical(previous_request['new_plan'])):_fail()
    error=_object((jobpath.parent/'error.json').read_bytes())
    if (error.get('code')!='PRODUCTION_HOUDINI_START_FAILED' or error.get('state')!='FAILED' or error.get('stop_confirmed') is not True
            or error.get('operation_id')!=job['operation_id'] or error.get('task_id')!=prep['task_id']
            or error.get('preparation_record')!=preparation_record
            or Path(state['tickets'][2]['directory']).parent!=jobpath.parent/'project/control/houdini-task-host'):_fail()
    if Path(checkpoint_record['path'])!=source/'checkpoint.json':_fail()
    checkpoint=_object(_bytes(checkpoint_record))
    from vfx_pipeline.official_graph_resume import inspect_resume_source
    actual=inspect_resume_source(jobpath.parent/'geometry-execution-preparation.json',checkpoint.get('operation_id'))
    if native._canonical(checkpoint)!=native._canonical(actual):_fail()
    _checkpoint_header(native,checkpoint)
    _request(request_record,preparation_record,prep,native,job,checkpoint_record)
    reuse=_object(_bytes(native.scope['source_reuse']));old=_object(_bytes(reuse['source_scope']))
    policy=old.get('process_image_policy')
    from .process_image import validate_collector_policy
    if validate_collector_policy(policy)['policy']!='sample_header_v1':_fail()
    _check_policy(policy)
    records=previous+diagnostic+[reuse['source_scope'],native.scope['source_reuse'],preparation_record,
        _record(jobpath),_record(jobpath.parent/'error.json'),checkpoint_record,request_record]
    for record in checkpoint['source_files']:
        _bytes(record)
        records.append(record)
    records += checkpoint['save_sidecars']
    payload={'schema':_SCHEMA,'native_scope':native.binding,'task_id':prep['task_id'],'preparation':preparation_record,
        'authority':{'authority':'current_user_instruction','instruction':instruction},'closed_accounting':closed,
        'diagnostic_files':diagnostic,'collector_policy':policy,'failed_job':_record(jobpath),'source_checkpoint':checkpoint_record,
        'request':request_record,'source_files':records,**packages}
    path=native.root/'geometry-recovery-authorization.json';value={'payload':payload,'signature':_sign(native,payload)}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
    record=_record(path);_validate(native,record)
    return record


def _effective(preparation_record,runtime_root):
    if Path(runtime_root).parent.name=='0.3.5':
        from .geometry_recovery_successor import effective
        return effective(preparation_record,runtime_root)
    prep,native=_context(preparation_record);runtime=_path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.4')/'runtime':_fail()
    state=native._read();p=verify_state(native,state)
    if not isinstance(p,dict) or 'geometry_recovery_successor' in state:_fail()
    packages=_packages(_path(p['original_plugin_root']),runtime.parent)
    if any(p.get(k)!=v for k,v in packages.items()):_fail()
    native.collector_policy()
    native.check()
    return prep,native,p,_record(native.root/'geometry-recovery-authorization.json')


def resolve_worker(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[2]['active_worker']


def authorization_record(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[3]


def verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root):
    prep,native,p,record=_effective(preparation_record,runtime_root);request=_object(_bytes(p['request']))
    if (authority_record!=record or native._canonical(plan)!=native._canonical(request['new_plan'])
            or request_id!=request['request_id']):_fail()
    return record


def checkpoint_record(preparation_record,plan,request_id,authority_record,runtime_root):
    verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root)
    return _object(_bytes(authority_record))['payload']['source_checkpoint']


def verify_checkpoint_job(job,native_scope):
    """作业绑定其自身许可；新恢复不能改写旧作业的历史来源。"""
    state=native_scope._read();verify_state(native_scope,state)
    authority=job.get('runtime_continuation')
    if authority==state.get('geometry_recovery_authorization') and authority is not None:
        p,_,_=_validate(native_scope,authority)
    elif authority==state.get('geometry_recovery_successor') and authority is not None:
        from .geometry_recovery_successor import validate
        p,_,_=validate(native_scope,authority)
    else:_fail()
    request=_object(_bytes(p['request']))
    if (job.get('preparation')!=p['preparation'] or job.get('task_id')!=p['task_id']
            or job.get('operation_id')!=request['new_operation_id']
            or native_scope._canonical(job.get('plan'))!=native_scope._canonical(request['new_plan'])
            or job.get('source_checkpoint')!=p['source_checkpoint']
            or job.get('execution_worker')!=p['active_worker']):_fail()
    return _object(_bytes(p['source_checkpoint']))


def checkpoint_policy(job,native_scope):
    """新control只派生有效许可里的策略，不修改原scope或静态默认。"""
    verify_checkpoint_job(job,native_scope)
    return native_scope.collector_policy()
