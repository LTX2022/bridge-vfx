"""几何创作唯一额外宿主额度：原scope不改，只追加显式用户预算许可。"""
from __future__ import annotations
import copy
import hashlib
import hmac
import os
from pathlib import Path

from . import geometry_recovery as files

_SCHEMA='bridge.geometry-budget-addendum/1'
_SOURCE='bridge.geometry-budget-source/1'
_DOMAIN=b'bridge.geometry-budget-addendum/1\x00'
_MARKER='geometry_budget_addendum'
_NAME='geometry-budget-addendum.json'


def _fail():raise ValueError('GEOMETRY_BUDGET_ADDENDUM_INVALID')


def _limits():
    from .native_scope import GEOMETRY_BUDGET,GEOMETRY_ROLES
    return dict(GEOMETRY_BUDGET,max_dcc_starts=15),dict(GEOMETRY_ROLES,**{'houdini-host':7})


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _context(preparation_record):
    prep,native=files._context(preparation_record)
    if prep.get('scope')!=native.binding or prep.get('task_id')!=native.scope['task_id']:_fail()
    return prep,native


def _prefix(native,record,envelope):
    """账本后续可增长；绑定的是完整已签前缀，不能将当前整文件摘要冒充前缀。"""
    files._record_shape(record)
    if (record['path']!=str(native.journal_path) or not 0<record['bytes']<=8*1024*1024):_fail()
    current=native.journal_path.read_bytes();raw=current[:record['bytes']]
    if (len(raw)!=record['bytes'] or hashlib.sha256(raw).hexdigest()!=record['sha256']
            or not raw.endswith(b'\n')):_fail()
    lines=raw.splitlines();payload=native._verify_envelope(envelope)
    if (payload.get('seq')!=len(lines)-1
            or lines[-1]!=native._canonical(envelope)):_fail()
    # NativeScope._load_accounted已验当前完整链；独立source检查也逐行核验前缀链接。
    previous=None
    for sequence,line in enumerate(lines):
        item=files._object(line);p=native._verify_envelope(item)
        if p.get('seq')!=sequence or p.get('previous')!=previous:_fail()
        previous=hashlib.sha256(native._canonical(item)).hexdigest()
    return payload


def _source(native,value):
    """低层只核预算所需阶段和原件；完整场景/生产来源由上层续接验证负责。"""
    expected={'schema','preparation','native_scope','task_id','failed_job','error','source_files','accounting_envelope','journal_prefix'}
    if (not isinstance(value,dict) or set(value)!=expected or value.get('schema')!=_SOURCE
            or value.get('native_scope')!=native.binding or value.get('task_id')!=native.scope['task_id']):_fail()
    preparation=files._object(files._bytes(value['preparation']))
    if (Path(value['preparation']['path'])!=native.root/'geometry-preparation.json'
            or preparation.get('scope')!=native.binding or preparation.get('task_id')!=native.scope['task_id']):_fail()
    accounted=_prefix(native,value['journal_prefix'],value['accounting_envelope']);state=accounted['state']
    tickets=state.get('tickets',[])
    if (state.get('scope_sha256')!=native.binding['sha256'] or state.get('closed_reason') is not None
            or len(tickets)!=6 or [t.get('role') for t in tickets]!=['graph-worker','graph-worker']+['houdini-host']*4
            or any(t.get('stopped_at') is None for t in tickets) or _MARKER in state
            or 'geometry_recovery_authorization' not in state or 'geometry_recovery_successor' not in state):_fail()
    for ticket in tickets:
        stop=native._stop(ticket)
        if (not stop or stop['observed_at']!=ticket['stopped_at']
                or hashlib.sha256(native._canonical(stop)).hexdigest()!=ticket.get('stopped_sha256')):_fail()
    jobpath=files._path(value['failed_job']['path']);job=files._object(files._bytes(value['failed_job']))
    if (jobpath!=native.root/'jobs'/job.get('operation_id','')/'job.json' or job.get('directory')!=str(jobpath.parent)
            or job.get('preparation')!=value['preparation'] or job.get('task_id')!=native.scope['task_id'] or job.get('revision')!=1
            or job.get('runtime_continuation')!=state['geometry_recovery_successor']):_fail()
    if Path(value['error']['path'])!=jobpath.parent/'error.json':_fail()
    error=files._object(files._bytes(value['error']))
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='PRODUCTION_HOST_DEADLINE_UNVERIFIED' or error.get('stop_confirmed') is not True
            or error.get('task_id')!=native.scope['task_id'] or error.get('operation_id')!=job['operation_id']
            or error.get('revision')!=1 or error.get('preparation_record')!=value['preparation']):_fail()
    usage=error.get('native_snapshot')
    if (not isinstance(usage,dict) or usage.get('closed_reason') is not None or usage.get('dcc_starts')!=6
            or usage.get('scope_sha256')!=native.binding['sha256'] or usage.get('tickets')!=tickets
            or usage.get('total_seconds')!=sum(max(t['charged_seconds'],t['stopped_at']-t['admitted_at']) for t in tickets)):_fail()
    records=value['source_files']
    if not isinstance(records,list) or len(records)!=3:_fail()
    if (Path(records[0]['path'])!=jobpath.parent/'incremental-state.json'
            or Path(records[1]['path'])!=jobpath.parent/'job-preparation.json'):_fail()
    journal=files._object(files._bytes(records[0]));jobprep=files._object(files._bytes(records[1]))
    if (journal.get('schema')!='bridge.geometry-job-journal/1' or journal.get('job')!=value['failed_job']
            or jobprep.get('job')!=value['failed_job']):_fail()
    stages=journal.get('stages',{})
    if (any(stages.get(name,{}).get('state')!='DONE' for name in ('save','warm_geometry','cold_reopen','cold_geometry','evaluate'))
            or stages.get('render',{}).get('state')!='INTENT' or 'result' in stages['render']
            or any(name in stages for name in ('render_completed','render_host_stop','verify','register','input_source','nuke_save','nuke_render'))):_fail()
    saved=stages['save']['result'];hip=records[2]
    files._bytes(hip)
    if (hip['path']!=saved.get('path') or hip['sha256']!=saved.get('sha256')
            or not files._path(hip['path']).is_relative_to(jobpath.parent) or Path(hip['path']).suffix!='.hip'
            or stages['evaluate']['result'].get('state')!='PASS'):_fail()
    return accounted,state


def build_source(preparation_record,failed_job_path):
    """只读形成六票预算来源，不写source/grant、不追加记账或启动原生程序。"""
    prep,native=_context(preparation_record);jobpath=files._path(failed_job_path)
    job=files._object(jobpath.read_bytes());journalpath=jobpath.parent/'incremental-state.json'
    journal=files._object(journalpath.read_bytes());saved=journal['stages']['save']['result']
    native.completed_snapshot();envelope=files._object(native.state_path.read_bytes());raw=native.journal_path.read_bytes()
    value={'schema':_SOURCE,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],
        'failed_job':files._record(jobpath),'error':files._record(jobpath.parent/'error.json'),
        'source_files':[files._record(journalpath),files._record(jobpath.parent/'job-preparation.json'),files._record(saved['path'])],
        'accounting_envelope':envelope,'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
    _source(native,value)
    return value


def validate(native,record):
    """历史纯文件/HMAC认证；不查询当前插件cache、OS工具或刷新资源。"""
    files._scope(native)
    if Path(record['path'])!=native.root/_NAME:_fail()
    path=files._path(record['path'])
    if path.stat().st_mode&0o077:_fail()
    value=files._object(files._bytes(record));p=value.get('payload');budget,roles=_limits()
    if (set(value)!={'payload','signature'} or not isinstance(p,dict)
            or set(p)!={'schema','preparation','native_scope','task_id','source','authority','budget','roles'}
            or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or p.get('budget')!=budget or p.get('roles')!=roles
            or not isinstance(p.get('authority'),dict) or set(p['authority'])!={'authority','approval_text'}
            or p['authority'].get('authority')!='current_user_instruction'
            or not isinstance(p['authority'].get('approval_text'),str) or not 1<=len(p['authority']['approval_text'])<=16000):_fail()
    source=files._object(files._bytes(p['source']))
    if (Path(p['source']['path'])!=native.root/'geometry-render-source.json' or source.get('preparation')!=p['preparation']):_fail()
    predecessor,state=_source(native,source)
    return p,predecessor,state


def verify_state(native,state):
    """追加预算只适用于原六票前缀；不会清闭、重置收费或产生后继加成。"""
    rows=[native._verify_envelope(files._object(line)) for line in native.journal_path.read_bytes().splitlines()]
    record=state.get(_MARKER)
    if record is None:
        if any(_MARKER in row['state'] for row in rows):_fail()
        return None
    p,predecessor,original=validate(native,record);index=predecessor['seq']+1
    if not 0<index<len(rows):_fail()
    expected=copy.deepcopy(original);expected[_MARKER]=record
    if rows[index].get('state')!=expected:_fail()
    if any(_MARKER in row['state'] for row in rows[:index]):_fail()
    previous=expected
    for sequence,row in enumerate(rows[index:],start=index):
        later=row['state']
        if (later.get(_MARKER)!=record or later['tickets'][:6]!=original['tickets']
                or later.get('geometry_recovery_authorization')!=original['geometry_recovery_authorization']
                or later.get('geometry_recovery_successor')!=original['geometry_recovery_successor']):_fail()
        if previous.get('closed_reason') is not None and later.get('closed_reason') is None:
            from .geometry_nuke_recovery import allows_clear
            if not allows_clear(native,state,sequence,previous,later):
                from .geometry_nuke_save_recovery import allows_clear as save_clear
                if not save_clear(native,state,sequence,previous,later):
                    from .geometry_seed_cold_recovery import allows_clear as cold_clear
                    if not cold_clear(native,state,sequence,previous,later):_fail()
        previous=later
    return p


def effective_limits(native,state):
    """每次读账重新认证动态加成，静态setup缓存不能保留已撤换的额度。"""
    p=verify_state(native,state)
    return (_limits() if p is not None else None)


def authorized_state(native,state,record):
    p,_,original=validate(native,record)
    if _MARKER in state or state!=original:_fail()
    result=copy.deepcopy(state);result[_MARKER]=record
    return result


def create_authorization(preparation_record,source_record,approval_text):
    """只由操作者传入本次真实明确答复；签发不等于激活，不启动任何原生程序。"""
    if not isinstance(approval_text,str) or not 1<=len(approval_text)<=16000 or not approval_text.strip():_fail()
    prep,native=_context(preparation_record);source=files._object(files._bytes(source_record))
    if Path(source_record['path'])!=native.root/'geometry-render-source.json' or source.get('preparation')!=preparation_record:_fail()
    _,state=_source(native,source)
    if native._read()!=state:_fail()
    budget,roles=_limits();payload={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,
        'task_id':prep['task_id'],'source':source_record,'authority':{'authority':'current_user_instruction','approval_text':approval_text},
        'budget':budget,'roles':roles}
    path=native.root/_NAME;value={'payload':payload,'signature':_sign(native,payload)}
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(native._canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
    record=files._record(path);validate(native,record)
    return record
