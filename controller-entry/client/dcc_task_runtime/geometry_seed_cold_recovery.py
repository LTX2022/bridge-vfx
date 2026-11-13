"""精确closed16的最后一票NR-only恢复；沿用17/NH3/NR3和全部原费用。"""
from __future__ import annotations
import copy,hashlib,hmac,os,re
from pathlib import Path
from . import geometry_recovery as files,geometry_budget_addendum as budget,geometry_nuke_save_recovery as prior
_SCHEMA='bridge.geometry-seed-cold-recovery/1';_SOURCE='bridge.geometry-seed-cold-budget-source/1'
_DOMAIN=b'bridge.geometry-seed-cold-recovery/1\x00';_MARKER='geometry_seed_cold_recovery'
_NAME='geometry-seed-cold-recovery-authorization.json';_SOURCE_NAME='geometry-seed-cold-budget-source.json'
_PRESERVE=prior._PRESERVE+('geometry_nuke_save_recovery',)

def _fail():raise ValueError('GEOMETRY_SEED_COLD_RECOVERY_INVALID')
def _sign(native,p):return hmac.new(hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()

def _upper(native,record,domain,schema,*,scope_key="native_scope"):
    v=files._object(files._bytes(record));p=v.get('payload');key=hmac.new(native._key(),domain,hashlib.sha256).digest()
    if (set(v)!={'payload','signature'} or type(p) is not dict or not hmac.compare_digest(str(v['signature']),hmac.new(key,native._canonical(p),hashlib.sha256).hexdigest()) or p.get('schema')!=schema or p.get(scope_key)!=native.binding or p.get('task_id')!=native.scope['task_id']):_fail()
    return p

def seed_binding(preparation,input_source):
    """最终NK只允许原冻结模板的既有路径替换，不能借恢复插入新节点或脚本。"""
    prep=files._object(files._bytes(preparation));source=files._object(files._bytes(input_source));control=files._path(source['producer_control']);project=control.parent
    root=Path(preparation['path']).parent
    if not control.is_relative_to(root/'jobs') or control.parts[-2:]!=('project','control') or source.get('schema')!='bridge.geometry-nuke-source/2' or source.get('artifact_version')!=2:_fail()
    text=files._bytes(prep['nuke_template']).decode('utf-8');names=re.findall(r'^ name (.*\.nk)$',text,re.M)
    if len(names)!=1 or text.count(prep['template_main_pattern'])!=1 or text.count(prep['template_nuke_pattern'])!=2:_fail()
    final=project/'saves/composite.nk';pattern=str(project/'saves/nuke.%04d.exr')
    expected=text.replace(prep['template_main_pattern'],str(project/'saves/main.%04d.exr')).replace(prep['template_nuke_pattern'],pattern).replace(names[0],str(final)).encode('utf-8')
    seed=files._record(project/'saves/composite-seed.nk')
    if files._bytes(seed)!=expected:_fail()
    return {'seed':seed,'template':prep['nuke_template'],'final_nk':{'path':str(final),'bytes':len(expected),'sha256':hashlib.sha256(expected).hexdigest()},'output_pattern':pattern}

def _source(native,s,*,require_unproduced=False):
    fields={'schema','preparation','native_scope','task_id','job','error','journal','late_stop','runtime_authority','input_source','nk_binding','supervisor_files','host_launch','accounting_envelope','journal_prefix'}
    if set(s)!=fields or s.get('schema')!=_SOURCE or s.get('native_scope')!=native.binding or s.get('task_id')!=native.scope['task_id']:_fail()
    prep=files._object(files._bytes(s['preparation']));envelope=budget._prefix(native,s['journal_prefix'],s['accounting_envelope']);state=envelope['state'];tickets=state['tickets']
    roles=['graph-worker']*2+['houdini-host']*7+['main-husk']*2+['nuke-host']*3+['nuke-render']*2
    if (s['preparation']['path']!=str(native.root/'geometry-preparation.json') or prep.get('scope')!=native.binding or len(tickets)!=16 or state.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED' or _MARKER in state or any(k not in state for k in _PRESERVE) or sorted(t['role'] for t in tickets)!=sorted(roles) or any(t['stopped_at'] is None for t in tickets)):_fail()
    _,_,closed15=prior.validate(native,state['geometry_nuke_save_recovery'])
    if tickets[:15]!=closed15['tickets']:_fail()
    from . import owned_process
    for ticket in tickets:
        stop=native._stop(ticket)
        if not stop or stop.get('observed_at')!=ticket['stopped_at'] or hashlib.sha256(native._canonical(stop)).hexdigest()!=ticket['stopped_sha256']:_fail()
    last=tickets[-1];host=files._path(last['directory']);started=owned_process.read_receipt(host,'started',identity=last['identity']);stopped=native._stop(last)
    if not started or last['role']!='nuke-host' or started.get('budget_seconds')!=120 or owned_process.execution_returncode(stopped)!=-15 or stopped.get('stop_reason')!='TIME_BUDGET_EXCEEDED' or stopped.get('supervisor_exit_code')!=0 or stopped.get('descendant_result_unobserved') is not False:_fail()
    records=s['supervisor_files']
    if set(records)!={'started','stopped','intent','stderr'}:_fail()
    for key,name in (('started','started.json'),('stopped','stopped.json'),('intent','intent.json'),('stderr','child.stderr.log')):
        if records[key]['path']!=str(host/name):_fail()
        files._bytes(records[key])
    job=files._object(files._bytes(s['job']));directory=native.root/'jobs'/job['operation_id'];error=files._object(files._bytes(s['error']));journal=files._object(files._bytes(s['journal']));stages=journal.get('stages',{})
    if (s['job']['path']!=str(directory/'job.json') or job.get('directory')!=str(directory) or job.get('task_id')!=s['task_id'] or job.get('preparation')!=s['preparation'] or job.get('revision')!=2 or job.get('runtime_continuation')!=s['runtime_authority'] or s['error']['path']!=str(directory/'error.json') or s['journal']['path']!=str(directory/'incremental-state.json') or journal.get('job')!=s['job'] or set(stages)!={'reuse_nuke_save_source','nuke_save'} or stages['reuse_nuke_save_source'].get('state')!='DONE' or stages['nuke_save'].get('state')!='INTENT' or 'result' in stages['nuke_save'] or error.get('code')!='NATIVE_SCOPE_EXECUTION_FAILED' or error.get('state')!='FAILED' or error.get('stop_confirmed') is not False or error.get('operation_id')!=job['operation_id'] or error.get('preparation_record')!=s['preparation']):_fail()
    auth=_upper(native,s['runtime_authority'],b'bridge.geometry-nuke-save-runtime-successor/1\x00','bridge.geometry-nuke-save-runtime-successor/1')
    old=_upper(native,auth['predecessor_authorization'],b'bridge.geometry-nuke-save-resume-authorization/1\x00','bridge.geometry-nuke-save-resume-authorization/1')
    original_request=files._object(files._bytes(old['request']))
    if (auth['preparation']!=s['preparation'] or auth['predecessor_authorization']['path']!=str(native.root/'geometry-nuke-save-resume-authorization.json') or old['source']!=job.get('nuke_save_source')
            or job.get('operation_id')!=original_request.get('new_operation_id') or job.get('plan')!=original_request.get('new_plan') or job.get('execution_worker')!=auth.get('active_worker')):_fail()
    oldsource=files._object(files._bytes(old['source']))
    if oldsource['input_source']!=s['input_source'] or oldsource['budget_authority']!=state['geometry_nuke_save_recovery']:_fail()
    launch=files._object(files._bytes(s['host_launch']))
    intent=files._object(files._bytes(records['intent']))
    if (s['host_launch']['path']!=str(host.parent/'launch.json') or launch.get('identity')!=last['identity'] or launch.get('input_artifact_source')!=s['input_source'] or launch.get('controller_root')!=str(directory/'nuke-save-control')
            or launch.get('task_root')!=str(native.root) or launch.get('nuke_executable')!=native.scope['hosts']['nuke']['path'] or intent.get('identity')!=last['identity']
            or (intent.get('native_scope_ticket') or {}).get('id')!=last['id'] or hashlib.sha256(native._canonical(intent.get('command'))).hexdigest()!=started.get('argv_sha256')):_fail()
    late=_upper(native,s['late_stop'],b'bridge.geometry-late-stop.key/1','bridge.geometry-late-stop-observation/1',scope_key='scope')
    if (s['late_stop']['path']!=str(directory/'late-stop-observation.json') or late.get('scope')!=native.binding or late.get('preparation')!=s['preparation'] or late.get('job')!=s['job'] or late.get('error')!=s['error'] or late.get('operation_id')!=job['operation_id'] or late.get('native_accounting')!=s['accounting_envelope'] or late.get('journal_prefix')!=s['journal_prefix'] or late.get('native_snapshot',{}).get('tickets')!=tickets):_fail()
    binding=seed_binding(s['preparation'],s['input_source'])
    if binding!=s['nk_binding']:_fail()
    for kind,path in (('nk',Path(binding['final_nk']['path'])),('output',Path(binding['output_pattern']%1))):
        if path.is_symlink() or require_unproduced and path.exists():_fail()
        if kind=='nk' and path.exists() and files._record(path)!=binding['final_nk']:_fail()
    return envelope,state

def build_source(preparation,failed_job_path,late_stop):
    prep,native=files._context(preparation);native.completed_snapshot();path=files._path(failed_job_path);job=files._object(path.read_bytes());state=native._read();host=Path(state['tickets'][-1]['directory']);runtime=files._object(files._bytes(job['runtime_continuation']))['payload'];old=files._object(files._bytes(runtime['predecessor_authorization']))['payload'];input_source=files._object(files._bytes(old['source']))['input_source'];raw=native.journal_path.read_bytes()
    s={'schema':_SOURCE,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'job':files._record(path),'error':files._record(path.parent/'error.json'),'journal':files._record(path.parent/'incremental-state.json'),'late_stop':late_stop,'runtime_authority':job['runtime_continuation'],'input_source':input_source,'nk_binding':seed_binding(preparation,input_source),'host_launch':files._record(host.parent/'launch.json'),'supervisor_files':{k:files._record(host/v) for k,v in {'started':'started.json','stopped':'stopped.json','intent':'intent.json','stderr':'child.stderr.log'}.items()},'accounting_envelope':files._object(native.state_path.read_bytes()),'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
    _source(native,s,require_unproduced=True);return s

def validate(native,record):
    files._scope(native)
    if record['path']!=str(native.root/_NAME) or files._path(record['path']).stat().st_mode&0o077:_fail()
    p=_upper(native,record,_DOMAIN,_SCHEMA)
    if set(p)!={'schema','preparation','native_scope','task_id','source','authority','budget','roles','allowed_role'} or p.get('budget')!=prior._limits()[0] or p.get('roles')!=prior._limits()[1] or p.get('allowed_role')!='nuke-render' or p['source']['path']!=str(native.root/_SOURCE_NAME) or p.get('authority')!={'authority':'inherited_approved_scope','prior_grant':files._object(files._bytes(p['source']))['accounting_envelope']['payload']['state']['geometry_nuke_save_recovery']} :_fail()
    source=files._object(files._bytes(p['source']));predecessor,state=_source(native,source)
    if p['preparation']!=source['preparation']:_fail()
    return p,predecessor,state

def create_authorization(preparation,source_record):
    prep,native=files._context(preparation);s=files._object(files._bytes(source_record));pred,closed=_source(native,s,require_unproduced=True)
    if source_record['path']!=str(native.root/_SOURCE_NAME) or s['preparation']!=preparation or native._read()!=closed or not prior._exact_predecessor(native,pred):_fail()
    b,r=prior._limits();p={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'authority':{'authority':'inherited_approved_scope','prior_grant':closed['geometry_nuke_save_recovery']},'budget':b,'roles':r,'allowed_role':'nuke-render'}
    path=native.root/_NAME;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    return files._record(path)

def transition(native,state):
    record=state.get(_MARKER)
    if record is None:return None
    p,pred,closed=validate(native,record);rows=native.journal_path.read_bytes().splitlines();index=pred['seq']+1;expected=dict(closed,closed_reason=None,geometry_seed_cold_recovery=record)
    if not 0<index<len(rows) or native._verify_envelope(files._object(rows[index-1]))['state']!=closed or native._verify_envelope(files._object(rows[index]))['state']!=expected:_fail()
    return index,closed,expected,record,p

def allows_clear(native,state,sequence,previous,later):
    # 本类标记没有变化时不可能是本类授权的清闭；真正转换仍逐次完整验签。
    if previous.get(_MARKER)==later.get(_MARKER):return False
    t=transition(native,state);return t is not None and (sequence,previous,later)==t[:3]

def verify_state(native,state):
    rows=[native._verify_envelope(files._object(x)) for x in native.journal_path.read_bytes().splitlines()];t=transition(native,state)
    if t is None:
        if any(_MARKER in row['state'] for row in rows):_fail()
        return None
    index,closed,expected,record,p=t
    if any(_MARKER in row['state'] for row in rows[:index]):_fail()
    previous=expected
    for row in rows[index:]:
        later=row['state'];extra=later['tickets'][16:]
        if (later.get(_MARKER)!=record or later['tickets'][:16]!=closed['tickets'] or any(later.get(k)!=closed[k] for k in _PRESERVE) or len(extra)>1 or any(x['role']!='nuke-render' for x in extra) or previous.get('closed_reason') is not None and later.get('closed_reason') is None):_fail()
        previous=later
    return p

def authorized_state(native,state,record):
    _,pred,closed=validate(native,record)
    if _MARKER in state or state!=closed or not prior._exact_predecessor(native,pred):_fail()
    return dict(state,closed_reason=None,geometry_seed_cold_recovery=record)

def historical_closed_state(native):
    path=native.root/_NAME
    if not path.exists():return None
    from .native_scope import _accounting_lock
    with _accounting_lock(native.state_path):
        _,pred,closed=validate(native,files._record(path))
        return closed if native._read()==closed and prior._exact_predecessor(native,pred) else None
