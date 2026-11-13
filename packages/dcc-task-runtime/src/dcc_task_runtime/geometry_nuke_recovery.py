"""几何Nuke首次冷消费导入失败的一次恢复；原十票、旧许可和费用保持。"""
from __future__ import annotations
import copy
import hashlib
import hmac
import os
from pathlib import Path

from . import geometry_recovery as files
from . import geometry_budget_addendum as prior_budget

_SCHEMA='bridge.geometry-nuke-recovery/1'
_SOURCE='bridge.geometry-nuke-budget-source/1'
_DOMAIN=b'bridge.geometry-nuke-recovery/1\x00'
_MARKER='geometry_nuke_recovery'
_NAME='geometry-nuke-recovery-authorization.json'
_SOURCE_NAME='geometry-nuke-budget-source.json'


def _fail():raise ValueError('GEOMETRY_NUKE_RECOVERY_INVALID')


def _limits():
    budget,roles=prior_budget._limits()
    return dict(budget,max_dcc_starts=16),dict(roles,**{'nuke-render':3})


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _source(native,value,*,require_unproduced=False):
    """只核导入失败、十票停止与预算原件；主图/NK/登记/槽闭包由上层负责。"""
    fields={'schema','preparation','native_scope','task_id','failed_job','error','cold_render','source_files',
            'supervisor_files','worker_result','output_observation','accounting_envelope','journal_prefix'}
    if (not isinstance(value,dict) or set(value)!=fields or value.get('schema')!=_SOURCE
            or value.get('native_scope')!=native.binding or value.get('task_id')!=native.scope['task_id']):_fail()
    prep=files._object(files._bytes(value['preparation']))
    if (Path(value['preparation']['path'])!=native.root/'geometry-preparation.json'
            or prep.get('scope')!=native.binding or prep.get('task_id')!=native.scope['task_id']):_fail()
    accounted=prior_budget._prefix(native,value['journal_prefix'],value['accounting_envelope']);state=accounted['state']
    tickets=state.get('tickets',[])
    if (state.get('scope_sha256')!=native.binding['sha256'] or state.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or len(tickets)!=10 or [t.get('role') for t in tickets]!=['graph-worker']*2+['houdini-host']*5+['main-husk','nuke-host','nuke-render']
            or any(t.get('stopped_at') is None for t in tickets) or _MARKER in state
            or 'geometry_budget_addendum' not in state
            or 'geometry_recovery_authorization' not in state or 'geometry_recovery_successor' not in state):_fail()
    # husk与父控制宿主共用停止来源，NativeScope的_stop保持原语义。
    for ticket in tickets:
        stopped=native._stop(ticket)
        if (not stopped or ticket['stopped_at']!=stopped.get('observed_at')
                or ticket.get('stopped_sha256')!=hashlib.sha256(native._canonical(stopped)).hexdigest()):_fail()
    grant,_,original_six=prior_budget.validate(native,state['geometry_budget_addendum'])
    if grant.get('preparation')!=value['preparation'] or tickets[:6]!=original_six['tickets']:_fail()
    jobpath=files._path(value['failed_job']['path']);job=files._object(files._bytes(value['failed_job']))
    if (jobpath!=native.root/'jobs'/job.get('operation_id','')/'job.json' or job.get('directory')!=str(jobpath.parent)
            or job.get('preparation')!=value['preparation'] or job.get('task_id')!=native.scope['task_id'] or job.get('revision')!=1):_fail()
    if Path(value['error']['path'])!=jobpath.parent/'error.json':_fail()
    error=files._object(files._bytes(value['error']))
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='NATIVE_SCOPE_EXECUTION_FAILED' or error.get('stop_confirmed') is not False
            or error.get('native_snapshot') is not None or error.get('operation_id')!=job['operation_id']
            or error.get('task_id')!=native.scope['task_id'] or error.get('preparation_record')!=value['preparation']
            or error.get('revision')!=1):_fail()
    records=value['source_files']
    if not isinstance(records,list) or len(records)!=1 or Path(records[0]['path'])!=jobpath.parent/'incremental-state.json':_fail()
    journal=files._object(files._bytes(records[0]));stages=journal.get('stages',{})
    if (journal.get('schema')!='bridge.geometry-job-journal/1' or journal.get('job')!=value['failed_job']
            or stages.get('nuke_launch_intent',{}).get('state')!='DONE' or stages.get('nuke_cold',{}).get('state')!='INTENT'
            or 'result' in stages['nuke_cold']):_fail()
    cold=files._object(files._bytes(value['cold_render']));launch=stages['nuke_launch_intent']['result'];last=tickets[-1]
    operation=launch.get('operation_id');directory=files._path(last['directory'])
    if (not isinstance(operation,str) or value['cold_render']['path']!=str(native.root/'state/nuke_renders'/(operation+'.json'))
            or (launch.get('record') or {}).get('path')!=value['cold_render']['path']
            or cold.get('task_id')!=operation or cold.get('owner_task_id')!=native.scope['task_id']
            or cold.get('request_id')!=job['operation_id']+'_nuke' or cold.get('state')!='FAILED'
            or directory!=native.root/'state/nuke_renders'/(operation+'.supervisor')
            or cold.get('frame_set')!=[1] or cold.get('pattern')!=str(jobpath.parent/'project/saves/nuke.%04d.exr')):_fail()
    process=cold.get('process') or {};worker=process.get('worker_result')
    if (process.get('supervisor_directory')!=str(directory) or process.get('supervisor_identity')!=last['identity']
            or worker!=str(native.root/'state/nuke_renders'/(operation+'.worker-result.json'))
            or value['worker_result']!={'path':worker,'exists':False} or Path(worker).exists() or Path(worker).is_symlink()):_fail()
    output=cold['pattern'].replace('%04d','0001')
    if value['output_observation']!={'path':output,'exists':False}:_fail()
    # 首次来源观测固定未产出事实；合法重试沿用NK写入同路径后，历史不能据此失效。
    if require_unproduced and (Path(output).exists() or Path(output).is_symlink()):_fail()
    supervisor=value['supervisor_files']
    if not isinstance(supervisor,dict) or set(supervisor)!={'started','stopped','intent','stderr'}:_fail()
    names={'started':'started.json','stopped':'stopped.json','intent':'intent.json','stderr':'child.stderr.log'}
    for name,filename in names.items():
        if supervisor[name]['path']!=str(directory/filename):_fail()
        files._bytes(supervisor[name])
    from . import owned_process
    started=owned_process.read_receipt(directory,'started',identity=last['identity'])
    stopped=owned_process.read_receipt(directory,'stopped',identity=last['identity'])
    intent=files._object(files._bytes(supervisor['intent']));stderr=files._bytes(supervisor['stderr']).decode('utf-8')
    frozen_ticket=intent.get('native_scope_ticket') or {};command=intent.get('command')
    if (not started or not stopped or owned_process.execution_returncode(stopped)!=2
            or started.get('budget_seconds')!=120 or intent.get('budget_seconds')!=120
            or intent.get('identity')!=last['identity'] or stderr.strip()!="No module named 'houdini_bridge'"
            or not isinstance(command,list) or len(command)!=9 or command[0]!=native.scope['hosts']['nuke']['path']
            or command[1]!='-t' or Path(command[2]).name!='nuke_owned_render_worker.py'
            or command!=process.get('argv') or started.get('argv_sha256')!=hashlib.sha256(owned_process._canonical(command)).hexdigest()
            or (intent.get('env') or {}).get('BRIDGE_NUKE_RESULT_FILE')!=worker
            or any(frozen_ticket.get(k)!=last.get(k) for k in ('id','role','directory','identity','heavy','parent','admitted_at'))):_fail()
    return accounted,state


def build_source(preparation_record,failed_job_path):
    """在上层已正式核对并登记旧NR失败后，只读固定预算与停止来源。"""
    prep,native=files._context(preparation_record);jobpath=files._path(failed_job_path)
    journalpath=jobpath.parent/'incremental-state.json';journal=files._object(journalpath.read_bytes())
    operation=journal['stages']['nuke_launch_intent']['result']['operation_id']
    coldpath=native.root/'state/nuke_renders'/(operation+'.json');cold=files._object(coldpath.read_bytes())
    directory=native.root/'state/nuke_renders'/(operation+'.supervisor')
    native.completed_snapshot();envelope=files._object(native.state_path.read_bytes());raw=native.journal_path.read_bytes()
    value={'schema':_SOURCE,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],
        'failed_job':files._record(jobpath),'error':files._record(jobpath.parent/'error.json'),'cold_render':files._record(coldpath),
        'source_files':[files._record(journalpath)],
        'supervisor_files':{name:files._record(directory/filename) for name,filename in
            {'started':'started.json','stopped':'stopped.json','intent':'intent.json','stderr':'child.stderr.log'}.items()},
        'worker_result':{'path':cold['process']['worker_result'],'exists':False},
        'output_observation':{'path':cold['pattern'].replace('%04d','0001'),'exists':False},'accounting_envelope':envelope,
        'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
    _source(native,value,require_unproduced=True);return value


def validate(native,record):
    """历史纯文件及独立域HMAC，不查询当前安装包或系统工具。"""
    files._scope(native)
    if Path(record['path'])!=native.root/_NAME:_fail()
    path=files._path(record['path'])
    if path.stat().st_mode&0o077:_fail()
    envelope=files._object(files._bytes(record));p=envelope.get('payload');budget,roles=_limits()
    if (set(envelope)!={'payload','signature'} or not isinstance(p,dict)
            or set(p)!={'schema','preparation','native_scope','task_id','source','authority','budget','roles'}
            or not hmac.compare_digest(str(envelope['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or p.get('budget')!=budget or p.get('roles')!=roles
            or not isinstance(p.get('authority'),dict) or set(p['authority'])!={'authority','approval_text'}
            or p['authority'].get('authority')!='current_user_instruction'
            or not isinstance(p['authority'].get('approval_text'),str) or not 1<=len(p['authority']['approval_text'])<=16000):_fail()
    source=files._object(files._bytes(p['source']))
    if (Path(p['source']['path'])!=native.root/_SOURCE_NAME or source.get('preparation')!=p['preparation']):_fail()
    predecessor,state=_source(native,source)
    return p,predecessor,state


def transition(native,state):
    """唯一明确许可的十票closed→open跃迁，供原两层状态核验精确桥接。"""
    record=state.get(_MARKER)
    if record is None:return None
    p,predecessor,original=validate(native,record);rows=native.journal_path.read_bytes().splitlines();index=predecessor['seq']+1
    expected=copy.deepcopy(original);expected.update(closed_reason=None,geometry_nuke_recovery=record)
    if (not 0<index<len(rows)
            or native._verify_envelope(files._object(rows[index-1]))['state']!=original
            or native._verify_envelope(files._object(rows[index])).get('state')!=expected):_fail()
    return index,original,expected,record,p


def allows_clear(native,state,sequence,previous,later):
    # 本类标记没有变化时不可能是本类授权的清闭；真正转换仍逐次完整验签。
    if previous.get(_MARKER)==later.get(_MARKER):return False
    item=transition(native,state)
    return item is not None and sequence==item[0] and previous==item[1] and later==item[2]


def verify_state(native,state):
    rows=[native._verify_envelope(files._object(line)) for line in native.journal_path.read_bytes().splitlines()]
    item=transition(native,state)
    if item is None:
        if any(_MARKER in row['state'] for row in rows):_fail()
        return None
    index,original,expected,record,p=item
    if any(_MARKER in row['state'] for row in rows[:index]):_fail()
    previous=expected
    for sequence,row in enumerate(rows[index:],start=index):
        later=row['state']
        if (later.get(_MARKER)!=record or later['tickets'][:10]!=original['tickets']
                or any(later.get(name)!=original[name] for name in
                       ('geometry_budget_addendum','geometry_recovery_authorization','geometry_recovery_successor'))):_fail()
        if previous.get('closed_reason') is not None and later.get('closed_reason') is None:
            from .geometry_nuke_save_recovery import allows_clear
            if not allows_clear(native,state,sequence,previous,later):
                from .geometry_seed_cold_recovery import allows_clear as cold_clear
                if not cold_clear(native,state,sequence,previous,later):_fail()
        previous=later
    return p


def effective_limits(native,state):
    return _limits() if verify_state(native,state) is not None else None


def authorized_state(native,state,record):
    p,_,original=validate(native,record)
    if _MARKER in state or state!=original:_fail()
    result=copy.deepcopy(state);result.update(closed_reason=None,geometry_nuke_recovery=record)
    return result


def create_authorization(preparation_record,source_record,approval_text):
    """只由操作者传入本轮新增16/NR3的真人答复；不激活、不启动原生程序。"""
    if not isinstance(approval_text,str) or not 1<=len(approval_text)<=16000 or not approval_text.strip():_fail()
    prep,native=files._context(preparation_record);source=files._object(files._bytes(source_record))
    if Path(source_record['path'])!=native.root/_SOURCE_NAME or source.get('preparation')!=preparation_record:_fail()
    _,state=_source(native,source,require_unproduced=True)
    if native._read()!=state:_fail()
    budget,roles=_limits();payload={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,
        'task_id':prep['task_id'],'source':source_record,'authority':{'authority':'current_user_instruction','approval_text':approval_text},
        'budget':budget,'roles':roles}
    path=native.root/_NAME;envelope={'payload':payload,'signature':_sign(native,payload)}
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(native._canonical(envelope)+b'\n');stream.flush();os.fsync(stream.fileno())
    record=files._record(path);validate(native,record);return record
