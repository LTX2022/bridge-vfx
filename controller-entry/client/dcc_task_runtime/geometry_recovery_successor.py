"""第二次且最后一次几何检查点恢复；保留首许可及四张已结算票据。"""
from __future__ import annotations
import copy
import hashlib
import hmac
import os
from pathlib import Path

from . import geometry_recovery as first

_SCHEMA='bridge.geometry-recovery-authorization/2'
_DOMAIN=b'bridge.geometry-recovery-authorization/2\x00'
_MARKER='geometry_recovery_successor'
_NAME='geometry-recovery-authorization-v2.json'
_CHANGED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+n+'.py' for n in
          ('native_scope','geometry_recovery','process_image','window_trace','writer_tool_trace')}
_CHANGED|={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in
           ('geometry_session','geometry_runtime_binding')}
_CHANGED|={'runtime/tools/recover_geometry_checkpoint.py'}
_ADDED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_recovery_successor.py'}


def _fail():raise ValueError('GEOMETRY_RECOVERY_SUCCESSOR_INVALID')


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _packages(original,active):
    """正式0.3.4到实际0.3.5仅接纳本次已经审核的采集、状态与续接文件。"""
    from vfx_pipeline.geometry_runtime_binding import _package
    if (original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes():_fail()
    old,of,osources=_package(original,'0.3.4');new,nf,nsources=_package(active,'0.3.5')
    changes={name for name in of if name in nf and of[name]!=nf[name]}
    if ({k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED
            or not changes<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),
            'package_sources':osources+nsources,
            'differences':[{'name':name,'before':first._record(original/name) if name in of else None,
                            'after':first._record(active/name)} for name in sorted(changes|_ADDED)],
            'active_worker':first._record(active/'runtime/tools/run_geometry_creative.py')}


def _request(record,preparation,prep,native,job,checkpoint):
    """恢复仍使用原模型内容，只另登记一次明确关联的控制器操作身份。"""
    if Path(record['path'])!=native.root/'geometry-checkpoint-recovery-request-v2.json':_fail()
    r=first._object(first._bytes(record));old=job['plan']
    fields={'schema','preparation','task_id','failed_operation_id','failed_job','source_checkpoint','new_plan',
            'request_id','new_operation_id','original_plan_sha256'}
    expected=copy.deepcopy(old);expected['plan_id']=old['plan_id']+'_host_resume02'
    expected['operator_repair']={'schema':'bridge.geometry-operator-checkpoint-recovery/2',
        'failed_operation_id':job['operation_id'],'authorization_path':str(native.root/_NAME)}
    expected['plan_sha256']=hashlib.sha256(native._canonical({k:v for k,v in expected.items() if k!='plan_sha256'})).hexdigest()
    request_id='operator_host_resume02_'+job['operation_id']
    operation='geo_'+hashlib.sha256((request_id+expected['plan_sha256']).encode()).hexdigest()[:24]
    if (set(r)!=fields or r['schema']!='bridge.geometry-checkpoint-recovery-request/2'
            or r['preparation']!=preparation or r['task_id']!=prep['task_id']
            or r['failed_operation_id']!=job['operation_id']
            or r['failed_job']!=first._record(Path(job['directory'])/'job.json') or r['source_checkpoint']!=checkpoint
            or r['original_plan_sha256']!=old['plan_sha256']
            or native._canonical(r['new_plan'])!=native._canonical(expected)
            or r['request_id']!=request_id or r['new_operation_id']!=operation):_fail()
    return r


def _closed(native,record,previous_record,previous_payload,previous_closed):
    """从真实sample符号处理失败的四票关闭状态续接，不接受任意停机。"""
    raw=first._bytes(record);p=native._verify_envelope(first._object(raw));state=p['state']
    lines=native.journal_path.read_bytes().splitlines();tickets=state.get('tickets',[])
    if (type(p.get('seq')) is not int or not 0<=p['seq']<len(lines) or lines[p['seq']]!=raw
            or state.get('scope_sha256')!=native.binding['sha256']
            or state.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or len(tickets)!=4 or tickets[:3]!=previous_closed['tickets']
            or [t['role'] for t in tickets]!=['graph-worker','graph-worker','houdini-host','houdini-host']
            or any(t.get('stopped_at') is None for t in tickets)
            or state.get('geometry_recovery_authorization')!=previous_record or _MARKER in state):_fail()
    from . import owned_process
    for ticket in tickets:
        stop=native._stop(ticket)
        if (not stop or ticket['stopped_at']!=stop['observed_at']
                or ticket['stopped_sha256']!=hashlib.sha256(native._canonical(stop)).hexdigest()):_fail()
    host=tickets[3];directory=first._path(host['directory'])
    start=owned_process.read_receipt(directory,'started',identity=host['identity'])
    stop=owned_process.read_receipt(directory,'stopped',identity=host['identity'])
    if (not start or not stop or owned_process.execution_returncode(stop)!=-15
            or start.get('writer_process_binding_error')!='ProcessImageError:PROCESS_IMAGE_TIMEOUT'):_fail()
    diag=start.get('writer_process_binding_diagnostic') or {};timing=diag.get('timing') or {}
    try:stderr=bytes.fromhex(diag.get('stderr_hex','')).decode('utf-8')
    except (ValueError,UnicodeError):_fail()
    if (diag.get('schema')!='bridge.process-image.tool-diagnostic/1' or diag.get('reason')!='PROCESS_IMAGE_TIMEOUT'
            or diag.get('tool_argv')!=['/usr/bin/sample',str(start['pid']),'1','1000','-file','/dev/stdout']
            or timing.get('tool_limit_seconds')!=8.0 or not 8.0<=timing.get('elapsed_seconds',0)<9.0
            or diag.get('stdout_observed_bytes')!=0 or 'Sampling completed, processing symbols...' not in stderr
            or (diag.get('cleanup') or {}).get('leader_reaped') is not True):_fail()
    return p,state,[first._record(directory/name) for name in ('started.json','stopped.json','intent.json')]


def _failure(native,preparation,previous_record,previous_payload,state,job_record,checkpoint_record):
    """原错误发布时未记到停止，改用当前四票签名停止事实；原错误不改写。"""
    jobpath=first._path(job_record['path']);job=first._object(first._bytes(job_record))
    request=first._object(first._bytes(previous_payload['request']))
    if (jobpath!=native.root/'jobs'/job.get('operation_id','')/'job.json'
            or job.get('directory')!=str(jobpath.parent) or job.get('preparation')!=preparation
            or job.get('task_id')!=native.scope['task_id'] or job.get('revision')!=1
            or job.get('runtime_continuation')!=previous_record
            or job.get('execution_worker')!=previous_payload['active_worker']
            or job.get('operation_id')!=request['new_operation_id']
            or native._canonical(job.get('plan'))!=native._canonical(request['new_plan'])
            or job.get('source_checkpoint')!=checkpoint_record
            or checkpoint_record!=previous_payload['source_checkpoint']):_fail()
    error_record=first._record(jobpath.parent/'error.json');error=first._object(first._bytes(error_record))
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='PRODUCTION_HOUDINI_START_FAILED' or error.get('stop_confirmed') is not False
            or error.get('native_snapshot') is not None or error.get('task_id')!=native.scope['task_id']
            or error.get('operation_id')!=job['operation_id'] or error.get('revision')!=1
            or error.get('preparation_record')!=preparation
            or Path(state['tickets'][3]['directory']).parent!=jobpath.parent/'project/control/houdini-task-host'):_fail()
    checkpoint=first._object(first._bytes(checkpoint_record));first._checkpoint_header(native,checkpoint)
    return job,error_record,checkpoint


def validate(native,record):
    """历史验证只读绑定原件与HMAC；不读当前插件cache或系统工具。"""
    first._scope(native)
    if Path(record['path'])!=native.root/_NAME:_fail()
    path=first._path(record['path'])
    if path.stat().st_mode&0o077:_fail()
    value=first._object(first._bytes(record));p=value.get('payload')
    if (set(value)!={'payload','signature'} or not isinstance(p,dict)
            or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('native_scope')!=native.binding
            or p.get('task_id')!=native.scope['task_id']
            or not isinstance(p.get('authority'),dict) or set(p['authority'])!={'authority','instruction'}
            or p['authority'].get('authority')!='current_user_instruction'
            or not isinstance(p['authority'].get('instruction'),str)
            or not 10<=len(p['authority']['instruction'])<=16000):_fail()
    previous,_,previous_closed=first._validate(native,p['previous_authorization'])
    if p['preparation']!=previous['preparation']:_fail()
    prep=first._object(first._bytes(p['preparation']))
    predecessor,state,diagnostic=_closed(native,p['closed_accounting'],p['previous_authorization'],previous,previous_closed)
    if p['diagnostic_files']!=diagnostic:_fail()
    from .process_image import validate_collector_policy
    policy=validate_collector_policy(p['collector_policy'])
    if policy!={'policy':'fork_corpse_vmmap_v1','tools':{'vmmap':previous['collector_policy']['tools']['vmmap']}}:_fail()
    job,_,_= _failure(native,p['preparation'],p['previous_authorization'],previous,state,p['failed_job'],p['source_checkpoint'])
    _request(p['request'],p['preparation'],prep,native,job,p['source_checkpoint'])
    for item in p['source_files']:first._bytes(item)
    for item in p['package_sources']:first._record_shape(item)
    first._record_shape(p['active_worker'])
    for item in p['differences']:
        if item['before'] is not None:first._record_shape(item['before'])
        first._record_shape(item['after'])
    return p,predecessor,state


def authorized_state(native,state,record):
    """仅接受封存四票前驱；第二许可不能用于第三次清闭或重置消耗。"""
    p,_,closed=validate(native,record)
    if _MARKER in state or state!=closed:_fail()
    first._check_policy(p['collector_policy'])
    result=copy.deepcopy(state);result.update(closed_reason=None,geometry_recovery_successor=record)
    return result


def create_authorization_v2(preparation_record,previous_v1_record,original_v034_formal_plugin,
        active_v035_cache_plugin,failed_job_path,checkpoint_record,request_record,instruction):
    """操作者签发最后一次明确恢复许可；本函数不清闭、不启动DCC。"""
    if not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip():_fail()
    prep,native=first._context(preparation_record);formal=first._path(original_v034_formal_plugin)
    active=first._path(active_v035_cache_plugin)
    if (Path(prep['worker']).parents[2].name!='0.3.1'
            or active!=Path(prep['worker']).parents[2].with_name('0.3.5')):_fail()
    previous,_,previous_closed=first._validate(native,previous_v1_record)
    # 把旧cache包记录核对到仍保留的0.3.4正式包，避免要求已卸载cache继续存在。
    from vfx_pipeline.geometry_runtime_binding import _rebase_package
    historical=first._packages(first._path(previous['original_plugin_root']),formal)
    former=first._path(previous['active_plugin_root'])
    if any(_rebase_package(previous.get(k),former,formal)!=v for k,v in historical.items()):_fail()
    packages=_packages(formal,active);source=native.root/'geometry-recovery-source'
    closed=first._copy(source/'closed-accounting-v2.json',native.state_path.read_bytes())
    _,state,diagnostic=_closed(native,closed,previous_v1_record,previous,previous_closed)
    if native._read()!=state:_fail()
    job_record=first._record(first._path(failed_job_path))
    job,error_record,checkpoint=_failure(native,preparation_record,previous_v1_record,previous,state,job_record,checkpoint_record)
    # 从原检查点已绑定的GraphJob源重新只读认证，不在失败宿主中重建图。
    from vfx_pipeline.official_graph_resume import inspect_resume_source
    actual=inspect_resume_source(checkpoint['preparation']['path'],checkpoint['operation_id'])
    if native._canonical(actual)!=native._canonical(checkpoint):_fail()
    _request(request_record,preparation_record,prep,native,job,checkpoint_record)
    policy={'policy':'fork_corpse_vmmap_v1','tools':{'vmmap':previous['collector_policy']['tools']['vmmap']}}
    first._check_policy(policy)
    records=[previous_v1_record,preparation_record,job_record,error_record,checkpoint_record,request_record]+diagnostic
    records+=checkpoint['source_files']+checkpoint['save_sidecars']
    payload={'schema':_SCHEMA,'native_scope':native.binding,'task_id':prep['task_id'],'preparation':preparation_record,
        'authority':{'authority':'current_user_instruction','instruction':instruction},'previous_authorization':previous_v1_record,
        'closed_accounting':closed,'diagnostic_files':diagnostic,'collector_policy':policy,'failed_job':job_record,
        'source_checkpoint':checkpoint_record,'request':request_record,'source_files':records,**packages}
    value={'payload':payload,'signature':_sign(native,payload)}
    path=native.root/_NAME
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(native._canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
    record=first._record(path);validate(native,record)
    return record


def effective(preparation_record,runtime_root):
    """新派发仍校验当前已安装包、采集工具与原累计预算。"""
    prep,native=first._context(preparation_record);runtime=first._path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.5')/'runtime':_fail()
    state=native._read();record=state.get(_MARKER)
    if record is None:_fail()
    p,_,_=validate(native,record)
    packages=_packages(first._path(p['original_plugin_root']),runtime.parent)
    if any(p.get(k)!=v for k,v in packages.items()):_fail()
    native.collector_policy();native.check()
    return prep,native,p,record
