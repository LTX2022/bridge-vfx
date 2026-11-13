"""精确恢复NH15在source2初始化时误用全停门的失败；十五票和旧许可不改。"""
from __future__ import annotations
import copy,hashlib,hmac,os
from pathlib import Path
from . import geometry_recovery as files,geometry_budget_addendum as budget,geometry_nuke_recovery as prior

_SCHEMA='bridge.geometry-nuke-save-recovery/1'
_SOURCE='bridge.geometry-nuke-save-budget-source/1'
_DOMAIN=b'bridge.geometry-nuke-save-recovery/1\x00'
_MARKER='geometry_nuke_save_recovery'
_NAME='geometry-nuke-save-recovery-authorization.json'
_SOURCE_NAME='geometry-nuke-save-budget-source.json'
_PRESERVE=('geometry_recovery_authorization','geometry_recovery_successor','geometry_budget_addendum','geometry_nuke_recovery')


def _fail():raise ValueError('GEOMETRY_NUKE_SAVE_RECOVERY_INVALID')

def _limits():
    b,r=prior._limits();return dict(b,max_dcc_starts=17),dict(r,**{'nuke-host':3})

def _sign(native,p):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(p),hashlib.sha256).hexdigest()


def _registration(native,record,preparation,tickets):
    """低层只认证已签原十四票前缀，完整场景和typed登记由上层复验。"""
    v=files._object(files._bytes(record));p=v.get('payload')
    key=hmac.new(native._key(),b'bridge.geometry-registration-authorization/1\x00',hashlib.sha256).digest()
    if (set(v)!={'payload','signature'} or not isinstance(p,dict)
            or not hmac.compare_digest(str(v['signature']),hmac.new(key,native._canonical(p),hashlib.sha256).hexdigest())
            or p.get('schema')!='bridge.geometry-registration-authorization/1' or p.get('preparation')!=preparation
            or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or record['path']!=str(native.root/'geometry-registration-resume-authorization.json')):_fail()
    source=files._object(files._bytes(p['source']))
    state=budget._prefix(native,source['journal_prefix'],source['accounting_envelope'])['state']
    if len(state.get('tickets',[]))!=14 or state.get('closed_reason') is not None or tickets[:14]!=state['tickets']:_fail()
    return p


def _source(native,s,*,require_unproduced=False):
    fields={'schema','preparation','native_scope','task_id','job','error','journal','input_source','registration_authority','host_launch','supervisor_files','accounting_envelope','journal_prefix','output_observation'}
    if set(s)!=fields or s.get('schema')!=_SOURCE or s.get('native_scope')!=native.binding or s.get('task_id')!=native.scope['task_id']:_fail()
    prep=files._object(files._bytes(s['preparation']))
    if s['preparation']['path']!=str(native.root/'geometry-preparation.json') or prep.get('scope')!=native.binding or prep.get('task_id')!=s['task_id']:_fail()
    envelope=budget._prefix(native,s['journal_prefix'],s['accounting_envelope']);state=envelope['state'];tickets=state.get('tickets',[])
    roles=['graph-worker']*2+['houdini-host']*7+['main-husk']*2+['nuke-host']*2+['nuke-render']*2
    if (state.get('scope_sha256')!=native.binding['sha256'] or state.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
            or len(tickets)!=15 or any(t.get('stopped_at') is None for t in tickets) or _MARKER in state
            or any(k not in state for k in _PRESERVE) or tickets[-1].get('role')!='nuke-host' or sorted(t['role'] for t in tickets)!=sorted(roles)):_fail()
    for ticket in tickets:
        stopped=native._stop(ticket)
        if not stopped or stopped['observed_at']!=ticket['stopped_at'] or hashlib.sha256(native._canonical(stopped)).hexdigest()!=ticket['stopped_sha256']:_fail()
    _,_,original_ten=prior.validate(native,state['geometry_nuke_recovery'])
    if tickets[:10]!=original_ten['tickets']:_fail()
    registration=_registration(native,s['registration_authority'],s['preparation'],tickets)
    job=files._object(files._bytes(s['job']));directory=native.root/'jobs'/job.get('operation_id','')
    if (s['job']['path']!=str(directory/'job.json') or job.get('directory')!=str(directory) or job.get('task_id')!=s['task_id'] or job.get('revision')!=2
            or job.get('preparation')!=s['preparation'] or job.get('registration_source')!=registration['source'] or job.get('runtime_continuation')!=s['registration_authority']):_fail()
    if s['error']['path']!=str(directory/'error.json') or s['journal']['path']!=str(directory/'incremental-state.json'):_fail()
    error=files._object(files._bytes(s['error']));journal=files._object(files._bytes(s['journal']));stages=journal.get('stages',{})
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED' or error.get('code')!='RUNTIMEERROR' or error.get('stop_confirmed') is not True
            or error.get('task_id')!=s['task_id'] or error.get('operation_id')!=job['operation_id'] or error.get('preparation_record')!=s['preparation']
            or journal.get('job')!=s['job'] or set(stages)!={'reuse_registration_source','register','input_source','input_preflight','nuke_save'}
            or any(stages[n].get('state')!='DONE' for n in ('reuse_registration_source','register','input_source','input_preflight'))
            or stages['nuke_save'].get('state')!='INTENT' or 'result' in stages['nuke_save'] or stages['input_source']['result']!=s['input_source']):_fail()
    usage=error.get('native_snapshot') or {}
    if usage.get('tickets')!=tickets or usage.get('dcc_starts')!=15 or usage.get('scope_sha256')!=native.binding['sha256'] or usage.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED':_fail()
    source2=files._object(files._bytes(s['input_source']))
    if (source2.get('schema')!='bridge.geometry-nuke-source/2' or source2.get('task_id')!=s['task_id'] or source2.get('artifact_id')!='geometry_main' or source2.get('artifact_version')!=2
            or (source2.get('registration_implementation') or {}).get('authorization')!=s['registration_authority']):_fail()
    last=tickets[-1];host=files._path(last['directory']);records=s['supervisor_files']
    if set(records)!={'started','stopped','intent','stderr'} or s['host_launch']['path']!=str(host.parent/'launch.json'):_fail()
    for name,filename in {'started':'started.json','stopped':'stopped.json','intent':'intent.json','stderr':'child.stderr.log'}.items():
        if records[name]['path']!=str(host/filename):_fail()
        files._bytes(records[name])
    from . import owned_process
    started=owned_process.read_receipt(host,'started',identity=last['identity']);stopped=owned_process.read_receipt(host,'stopped',identity=last['identity'])
    launch=files._object(files._bytes(s['host_launch']));intent=files._object(files._bytes(records['intent']));text=files._bytes(records['stderr']).decode('utf-8')
    if (not started or not stopped or owned_process.execution_returncode(stopped)!=1 or started.get('budget_seconds')!=120
            or launch.get('identity')!=last['identity'] or launch.get('input_artifact_source')!=s['input_source'] or launch.get('task_root')!=str(native.root)
            or launch.get('controller_root')!=str(directory/'nuke-save-control') or launch.get('nuke_executable')!=native.scope['hosts']['nuke']['path']
            or intent.get('identity')!=last['identity'] or hashlib.sha256(owned_process._canonical(intent.get('command'))).hexdigest()!=started.get('argv_sha256')
            or any(t not in text for t in ('NATIVE_SCOPE_COMPLETED_STOP_REQUIRED','geometry_native_evidence.py','completed_snapshot','registration_registry_class'))):_fail()
    project=files._path(source2['producer_control']).parent
    expected={'nk':{'path':str(project/'saves/composite.nk'),'exists':False},'nuke':{'path':str(project/'saves/nuke.0001.exr'),'exists':False}}
    if s['output_observation']!=expected:_fail()
    # 缺失是首签时的事实；合法后续保存/渲染到同路径不应破坏历史认证。
    if require_unproduced and any(Path(o['path']).exists() or Path(o['path']).is_symlink() for o in expected.values()):_fail()
    return envelope,state


def build_source(preparation_record,failed_job_path):
    """只读固定十五票失败来源，不创建许可或清除闭锁。"""
    prep,native=files._context(preparation_record);native.completed_snapshot();jobpath=files._path(failed_job_path)
    job=files._object(jobpath.read_bytes());journal=files._object((jobpath.parent/'incremental-state.json').read_bytes())
    record=journal['stages']['input_source']['result'];source2=files._object(files._bytes(record));state=native._read()
    host=Path(state['tickets'][-1]['directory']);raw=native.journal_path.read_bytes();project=Path(source2['producer_control']).parent
    s={'schema':_SOURCE,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],'job':files._record(jobpath),'error':files._record(jobpath.parent/'error.json'),
        'journal':files._record(jobpath.parent/'incremental-state.json'),'input_source':record,'registration_authority':job['runtime_continuation'],'host_launch':files._record(host.parent/'launch.json'),
        'supervisor_files':{name:files._record(host/file) for name,file in {'started':'started.json','stopped':'stopped.json','intent':'intent.json','stderr':'child.stderr.log'}.items()},
        'accounting_envelope':files._object(native.state_path.read_bytes()),'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
        'output_observation':{'nk':{'path':str(project/'saves/composite.nk'),'exists':False},'nuke':{'path':str(project/'saves/nuke.0001.exr'),'exists':False}}}
    _source(native,s,require_unproduced=True);return s


def validate(native,record):
    """独立域历史验签，不读当前cache、工具或重新执行生产。"""
    files._scope(native)
    if record['path']!=str(native.root/_NAME) or files._path(record['path']).stat().st_mode&0o077:_fail()
    value=files._object(files._bytes(record));p=value.get('payload');b,r=_limits()
    if (set(value)!={'payload','signature'} or not isinstance(p,dict) or set(p)!={'schema','preparation','native_scope','task_id','source','authority','budget','roles'}
            or not hmac.compare_digest(str(value['signature']),_sign(native,p)) or p.get('schema')!=_SCHEMA or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or p.get('budget')!=b or p.get('roles')!=r or set(p.get('authority',{}))!={'authority','approval_text'} or p['authority']['authority']!='current_user_instruction'
            or not isinstance(p['authority'].get('approval_text'),str) or not 1<=len(p['authority']['approval_text'])<=16000):_fail()
    s=files._object(files._bytes(p['source']))
    if p['source']['path']!=str(native.root/_SOURCE_NAME) or s['preparation']!=p['preparation']:_fail()
    predecessor,state=_source(native,s);return p,predecessor,state


def transition(native,state):
    record=state.get(_MARKER)
    if record is None:return None
    p,predecessor,closed=validate(native,record);rows=native.journal_path.read_bytes().splitlines();index=predecessor['seq']+1
    expected=copy.deepcopy(closed);expected.update(closed_reason=None,geometry_nuke_save_recovery=record)
    if (not 0<index<len(rows) or native._verify_envelope(files._object(rows[index-1]))['state']!=closed
            or native._verify_envelope(files._object(rows[index]))['state']!=expected):_fail()
    return index,closed,expected,record,p


def allows_clear(native,state,sequence,previous,later):
    # 本类标记没有变化时不可能是本类授权的清闭；真正转换仍逐次完整验签。
    if previous.get(_MARKER)==later.get(_MARKER):return False
    t=transition(native,state);return t is not None and sequence==t[0] and previous==t[1] and later==t[2]


def effective_limits(native,state):
    rows=[native._verify_envelope(files._object(line)) for line in native.journal_path.read_bytes().splitlines()];t=transition(native,state)
    if t is None:
        if any(_MARKER in p['state'] for p in rows):_fail()
        return None
    index,closed,expected,record,p=t
    if any(_MARKER in row['state'] for row in rows[:index]):_fail()
    previous=expected
    for sequence,row in enumerate(rows[index:],start=index):
        later=row['state']
        if (later.get(_MARKER)!=record or later['tickets'][:15]!=closed['tickets'] or any(later.get(k)!=closed[k] for k in _PRESERVE)):_fail()
        if previous.get('closed_reason') is not None and later.get('closed_reason') is None:
            from .geometry_seed_cold_recovery import allows_clear
            if not allows_clear(native,state,sequence,previous,later):_fail()
        previous=later
    return _limits()


def _exact_predecessor(native,predecessor):
    # 相同state但后来追加的另一事件也不能被旧许可清闭；必须是原签名最后一行。
    current=native._verify_envelope(files._object(native.state_path.read_bytes()))
    return native._canonical(current)==native._canonical(predecessor)


def authorized_state(native,state,record):
    _,predecessor,closed=validate(native,record)
    if _MARKER in state or state!=closed or not _exact_predecessor(native,predecessor):_fail()
    result=copy.deepcopy(state);result.update(closed_reason=None,geometry_nuke_save_recovery=record);return result


def create_authorization(preparation_record,source_record,approval_text):
    """只由操作者传入本轮真实17/NH3确认；签发与激活分开。"""
    if not isinstance(approval_text,str) or not 1<=len(approval_text)<=16000 or not approval_text.strip():_fail()
    prep,native=files._context(preparation_record);s=files._object(files._bytes(source_record))
    if source_record['path']!=str(native.root/_SOURCE_NAME) or s['preparation']!=preparation_record:_fail()
    predecessor,closed=_source(native,s,require_unproduced=True)
    if native._read()!=closed or not _exact_predecessor(native,predecessor):_fail()
    b,r=_limits();p={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,
        'authority':{'authority':'current_user_instruction','approval_text':approval_text},'budget':b,'roles':r}
    path=native.root/_NAME;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    record=files._record(path);validate(native,record);return record


def historical_closed_state(native):
    """精确签名closed15只供完成事实观察；本函数不能激活或授权原生执行。"""
    path=native.root/_NAME
    if not path.exists():return None
    from .native_scope import _accounting_lock
    with _accounting_lock(native.state_path):
        _,predecessor,closed=validate(native,files._record(path))
        return closed if native._read()==closed and _exact_predecessor(native,predecessor) else None
