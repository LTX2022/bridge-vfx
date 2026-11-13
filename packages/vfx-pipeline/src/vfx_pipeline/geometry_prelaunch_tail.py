"""047仅续原Geometry操作未准入的冷消费；旧046原件与已激活低许可保持。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os,sqlite3,time
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.platform_support import process_status
from houdini_bridge.official_karma_observation import file_record
from .geometry_render_resume import _path,_read,_object,_load
from .geometry_registration_resume import _context
_SCHEMA='bridge.geometry-prelaunch-tail-runtime/1'
_SOURCE='bridge.geometry-prelaunch-tail-source/1'
_AUTH='geometry-prelaunch-tail-authorization.json'
_SOURCE_NAME='geometry-prelaunch-tail-source.json'
_DOMAIN=b'bridge.geometry-prelaunch-tail-runtime/1\x00'
_DIR='prelaunch-047'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_prelaunch_tail.py','runtime/tools/resume_geometry_prelaunch_tail.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+name+'.py' for name in ('geometry_seed_cold_resume','geometry_cold_preflight_runtime','geometry_job','geometry_session','geometry_runtime_binding')}
_CHANGED|={'runtime/packages/nuke-bridge/src/nuke_bridge/'+name+'.py' for name in ('task_host','owned_render_worker','operation_receipts')}
_CHANGED|={'runtime/tools/recover_disklight_nuke.py','runtime/plugins/nuke/nuke_bridge_addon.py'}
_TOKEN=object()

def _fail():raise ValueError('GEOMETRY_PRELAUNCH_TAIL_INVALID')
def _sign(native,p,domain=_DOMAIN):return hmac.new(hmac.new(native._key(),domain,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()
def _bytes(record):
    from nuke_bridge.task_host import _cold_bytes
    return _cold_bytes(record)
def _record(path):
    from nuke_bridge.task_host import _cold_record
    return _cold_record(path)

def _packages(original,active):
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.6');b,bf,brs=_package(active,'0.4.7');changed={name for name in af if name in bf and af[name]!=bf[name]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {key:value for key,value in a.items() if key!='version'}!={key:value for key,value in b.items() if key!='version'}
            or set(af)-set(bf) or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,'active_worker':file_record(active/'runtime/tools/resume_geometry_prelaunch_tail.py'),
            'differences':[{'name':name,'before':file_record(original/name) if name in af else None,'after':file_record(active/name)} for name in sorted(changed|_ADDED)]}

def _slot(native):
    path=native.root/'scheduler/graph_scheduler.sqlite3'
    # readonly observation必须包括现有WAL，不能写journal mode或伪造空槽。
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM heavy_slot WHERE slot=1').fetchone()
        return dict(row) if row is not None else None

def _slot_binding(row):
    return {key:row.get(key) for key in ('generation','active','owner_root','operation_id','token','phase','cancel_requested','process_json')}

def _stop(source,native,formal,*,realtime=False):
    report=_object(_bytes(source['metadata_stop']));processes=report.get('processes')
    if report.get('schema')!='bridge.geometry046-metadata-stop-observation/1' or report.get('state')!='STOP_CONFIRMED' or not isinstance(processes,list) or len(processes)!=2:_fail()
    expected_paths={str(Path(source['job']['path']).parent/name) for name in ('controller-started.json','execute-owner.json')}
    if {item.get('record',{}).get('path') for item in processes}!=expected_paths:_fail()
    for item in processes:
        owner=_object(_bytes(item['record']));identity=owner.get('process_identity')
        if identity!=item.get('original_identity') or item.get('exact_original_status')!='stopped' or (item.get('current_identity') or {}).get('state')!='stopped':_fail()
        if realtime and process_status(identity)!='stopped':_fail()
    if report.get('native_tickets')!=16 or report.get('all_native_stopped') is not True or report.get('error')!=source['error']:_fail()
    implementation=report['run_job_implementation'];relative=Path('runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_job.py')
    former=Path(source['old_active_plugin_root'])/relative;actual=_record(formal/relative)
    if implementation['path']!=str(former) or any(implementation[key]!=actual[key] for key in ('bytes','sha256')):_fail()
    if source['stop_implementation']!=actual:_fail()
    _bytes(report['stderr'])
    return report

def _frozen_session(source,job,request):
    """047签源只承接原QUEUED主job；后续活动状态由受签continuation另行投影。"""
    state=source['session_state'];op=job['operation_id'];pid=job['plan']['plan_id'];rid=request['request_id'];entry=state.get('jobs',{}).get(op,{})
    if (state.get('preparation')!=source['preparation'] or state.get('task_id')!=source['task_id'] or state.get('revision')!=1
            or not isinstance(state.get('completed'),list) or len(state['completed'])!=1 or op in state['completed']
            or entry.get('state')!='QUEUED' or entry.get('prelaunch_continuation') is not None
            or any(entry.get(key)!=value for key,value in {'operation_id':op,'revision':2,'plan_id':pid,'job_file':source['job'],'directory':job['directory']}.items())
            or state.get('plans',{}).get(pid)!=job['plan'] or state.get('plan_operations',{}).get(pid)!=op
            or state.get('execution_requests',{}).get(rid)!={'request_sha256':canonical_sha256({'plan_id':pid}),'operation_id':op}):_fail()


def _original(source,native,*,realtime=False):
    from . import geometry_cold_preflight_runtime as old
    fields={'schema','preparation','task_id','original_authority','formal046','old_active_plugin_root','job','job_preparation','journal','error','old_task','records','original_dispatch','metadata_stop','stop_implementation','old_slot','session_state','accounting_envelope','journal_prefix','cold_attempt'}
    if type(source) is not dict or set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id'] or source.get('preparation',{}).get('path')!=str(native.root/'geometry-preparation.json'):_fail()
    p,original=old.validate(source['preparation'],source['original_authority'],native)
    formal=_path(source['formal046']);proof=_object(_read(source['original_authority']))['payload']
    if p['consumer_runtime']['package_root']!=str(formal) or source['old_active_plugin_root']!=proof['active_plugin_root']:_fail()
    job=_object(_bytes(source['job']));directory=native.root/'jobs'/job['operation_id'];request=_object(_read(p['request']))
    if (source['job']['path']!=str(directory/'job.json') or job.get('directory')!=str(directory) or job.get('preparation')!=source['preparation']
            or job.get('operation_id')!=request['new_operation_id'] or job.get('plan')!=request['new_plan'] or job.get('runtime_continuation')!=source['original_authority']
            or job.get('execution_worker')!=p['active_worker']):_fail()
    _frozen_session(source,job,request)
    names=('job.json','job-preparation.json','error.json','incremental-state.json','controller-started.json','controller-launch-intent.json','execute-owner.json','controller.stderr.log','controller-error.log')
    old_request=job['operation_id']+'_nuke';old_nr='nrend-'+hashlib.sha256(old_request.encode()).hexdigest()[:16]
    expected={name:str(directory/name) for name in names}
    expected.update({'old_nr'+suffix:str(native.root/'state/nuke_renders'/(old_nr+suffix)) for suffix in ('.json','.nk','.inputs.json')})
    if type(source['records']) is not dict or set(source['records'])!=set(expected):_fail()
    for name,path in expected.items():
        if source['records'][name].get('path')!=path:_fail()
        _bytes(source['records'][name])
    for alias,name in (('job','job.json'),('job_preparation','job-preparation.json'),('journal','incremental-state.json'),('error','error.json'),('old_task','old_nr.json')):
        if source[alias]!=source['records'][name]:_fail()
    if source['original_dispatch']['path']!=str(native.root/'geometry-seed-cold-resume-dispatch.json'):_fail()
    journal=_object(_bytes(source['journal']));error=_object(_bytes(source['error']));stages=journal.get('stages',{})
    if (source['journal']['path']!=str(directory/'incremental-state.json') or journal.get('job')!=source['job'] or set(stages)!={'reuse_seed_cold_source','text_finalize','nuke_cold','nuke_launch_intent'}
            or stages['nuke_cold'].get('state')!='INTENT' or any(stages[key].get('state')!='DONE' for key in ('reuse_seed_cold_source','text_finalize','nuke_launch_intent'))
            or error.get('operation_id')!=job['operation_id'] or error.get('preparation_record')!=source['preparation'] or error.get('state')!='FAILED' or error.get('stop_confirmed') is not True):_fail()
    old_request=job['operation_id']+'_nuke';old_nr='nrend-'+hashlib.sha256(old_request.encode()).hexdigest()[:16];task=_object(_bytes(source['old_task']))
    if (source['old_task']['path']!=str(native.root/'state/nuke_renders'/(old_nr+'.json')) or task.get('task_id')!=old_nr or task.get('request_id')!=old_request
            or task.get('owner_task_id')!=native.scope['task_id'] or task.get('state')!='RUNNING' or any(task.get(key) is not None for key in ('process','supervisor_intent','execution_fact'))
            or source['old_slot']['operation_id']!=old_nr or source['old_slot']['active']!=1 or source['old_slot']['phase']!='DISPATCHING' or source['old_slot']['process_json'] is not None or source['old_slot']['cancel_requested']!=0
            or any(task['slot'][key]!=source['old_slot'][key] for key in ('owner_root','operation_id','token','generation'))):_fail()
    for path in (native.root/'state/nuke_renders'/(old_nr+'.supervisor'),native.root/'state/nuke_renders'/(old_nr+'.proof.json')):
        if path.exists() or path.is_symlink():_fail()
    if any((native.root/'state/nuke_renders').glob(old_nr+'.*.input-proof.json')):_fail()
    dispatch=_object(_bytes(source['original_dispatch']));body=dispatch.get('payload')
    if (set(dispatch)!={'payload','signature'} or type(body) is not dict
            or not hmac.compare_digest(str(dispatch['signature']),_sign(native,body,b'bridge.geometry-seed-cold-dispatch/1\x00'))
            or body.get('state')!='ACCEPTED' or body.get('authority')!=source['original_authority'] or body.get('operation_id')!=job['operation_id'] or body.get('request')!=p['request']):_fail()
    _stop(source,native,formal,realtime=realtime)
    expected_request=job['operation_id']+'_prelaunch047_nuke';attempt=source['cold_attempt']
    if attempt!={'main_operation_id':job['operation_id'],'request_id':expected_request,'operation_id':'nrend-'+hashlib.sha256(expected_request.encode()).hexdigest()[:16],'journal_directory':str(directory/_DIR)}:_fail()
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    initial=_prefix(native,source['journal_prefix'],source['accounting_envelope'])['state'];current=native._read()
    if (len(initial['tickets'])!=16 or any(ticket['stopped_at'] is None for ticket in initial['tickets']) or initial.get('closed_reason') is not None
            or initial.get('geometry_seed_cold_recovery')!=original['budget_authority'] or current['tickets'][:16]!=initial['tickets'] or current.get('geometry_seed_cold_recovery')!=initial['geometry_seed_cold_recovery']):_fail()
    return p,original,job,initial,current


def inspect_source(preparation,formal046,metadata_stop):
    """prepare-only：封存可靠未准入证据，既有OPEN16和g7槽原样保持。"""
    from . import geometry_cold_preflight_runtime as old
    _,native=_context(preparation);authority=file_record(native.root/old._AUTH);p,original=old.validate(preparation,authority,native);request=_object(_read(p['request']));directory=native.root/'jobs'/request['new_operation_id'];job=file_record(directory/'job.json');jobdata=_object(_bytes(job));old_nr='nrend-'+hashlib.sha256((jobdata['operation_id']+'_nuke').encode()).hexdigest()[:16];render=native.root/'state/nuke_renders';raw=native.journal_path.read_bytes();former=_object(_read(authority))['payload']['active_plugin_root'];formal=_path(formal046)
    records={name:_record(directory/name) for name in ('job.json','job-preparation.json','error.json','incremental-state.json','controller-started.json','controller-launch-intent.json','execute-owner.json','controller.stderr.log','controller-error.log')}
    for suffix in ('.json','.nk','.inputs.json'):records['old_nr'+suffix]=_record(render/(old_nr+suffix))
    cold_request=jobdata['operation_id']+'_prelaunch047_nuke'
    source={'schema':_SOURCE,'preparation':preparation,'task_id':native.scope['task_id'],'original_authority':authority,'formal046':str(formal),'old_active_plugin_root':former,'job':job,
            'job_preparation':records['job-preparation.json'],'journal':records['incremental-state.json'],'error':records['error.json'],'old_task':records['old_nr.json'],'records':records,
            'original_dispatch':file_record(native.root/'geometry-seed-cold-resume-dispatch.json'),'metadata_stop':metadata_stop,'stop_implementation':_record(formal/'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_job.py'),
            'old_slot':_slot_binding(_slot(native)),'session_state':_load(native.root/'geometry-state.json'),'accounting_envelope':_load(native.state_path),
            'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
            'cold_attempt':{'main_operation_id':jobdata['operation_id'],'request_id':cold_request,'operation_id':'nrend-'+hashlib.sha256(cold_request.encode()).hexdigest()[:16],'journal_directory':str(directory/_DIR)}}
    _original(source,native,realtime=True)
    if _slot_binding(_slot(native))!=source['old_slot'] or native._read()!=source['accounting_envelope']['payload']['state']:_fail()
    if any((render/(source['cold_attempt']['operation_id']+suffix)).exists() for suffix in ('.json','.supervisor','.proof.json')):_fail()
    return source


def _receipt_path(source):return Path(source['cold_attempt']['journal_directory'])/'slot-release.json'

def _verified_release(native,source):
    path=_receipt_path(source)
    if not path.exists():return None
    value=_load(path);p=value.get('payload')
    if (set(value)!={'payload','signature'} or type(p) is not dict or not hmac.compare_digest(str(value['signature']),_sign(native,p,b'bridge.geometry-prelaunch-release/1\x00'))
            or p.get('schema')!='bridge.geometry-prelaunch-release/1' or p.get('scope')!=native.binding or p.get('old_slot')!=source['old_slot']
            or p.get('cold_attempt')!=source['cold_attempt'] or p.get('authority')!=file_record(native.root/_AUTH) or p.get('released') is not True):_fail()
    after=p.get('after') or {}
    if (any(after.get(key)!=source['old_slot'][key] for key in ('generation','owner_root','operation_id','token'))
            or after.get('active')!=0 or after.get('phase')!='RELEASED' or after.get('process_json') is not None):_fail()
    return file_record(path)


def validate(preparation,record,native=None):
    _,n=_context(preparation);native=n if native is None else native
    if record.get('path')!=str(native.root/_AUTH) or _path(record['path']).stat().st_mode&0o077:_fail()
    value=_object(_read(record));p=value.get('payload');fields={'schema','preparation','native_scope','task_id','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(value)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p['schema']!=_SCHEMA or p['preparation']!=preparation or p['native_scope']!=native.binding or p['task_id']!=native.scope['task_id'] or p['source']['path']!=str(native.root/_SOURCE_NAME)):_fail()
    source=_object(_read(p['source']));old,original,job,initial,current=_original(source,native)
    if source['preparation']!=preparation or source['formal046']!=p['original_plugin_root']:_fail()
    from .geometry_runtime_binding import _package,_rebase_package
    formal=_path(p['consumer_runtime']['package_root']);_,_,indices=_package(formal,'0.4.7')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':indices}:_fail()
    packages=_packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[key],_path(p['active_plugin_root']),formal)!=item for key,item in packages.items()):_fail()
    release=_verified_release(native,source)
    if release is None:
        if current!=initial or _slot_binding(_slot(native))!=source['old_slot']:_fail()
    state=_load(native.root/'geometry-state.json');frozen=source['session_state'];op=job['operation_id']
    for section in ('plans','execution_requests','plan_operations'):
        if state.get(section)!=frozen.get(section):_fail()
    if set(state['jobs'])!=set(frozen['jobs']) or any(state['jobs'][key]!=entry for key,entry in frozen['jobs'].items() if key!=op):_fail()
    entry=state['jobs'][op];before=frozen['jobs'][op]
    if any(entry.get(key)!=before.get(key) for key in ('operation_id','revision','plan_id','job_file','directory','accepted_at')):_fail()
    if entry.get('prelaunch_continuation') not in (None,record):_fail()
    if release is None and entry!=before:_fail()
    if state.get('revision') not in (1,2) or state.get('completed') not in (frozen['completed'],frozen['completed']+[op]):_fail()
    effective=copy.deepcopy(old);effective.update(active_worker=p['active_worker'],consumer_runtime=p['consumer_runtime'],cold_attempt=source['cold_attempt'],prelaunch_authority=record)
    effective['readset']=[*old['readset'],p['source'],source['original_authority'],source['metadata_stop'],source['stop_implementation'],source['original_dispatch'],*source['records'].values(),*packages['package_sources']]
    if release is not None:effective['readset'].append(release)
    return effective,original


def create_authorization(preparation,source_record,formal046,active047,formal047):
    prep,native=_context(preparation);source=_object(_read(source_record));original=_path(formal046);active=_path(active047);formal=_path(formal047)
    if (source_record['path']!=str(native.root/_SOURCE_NAME) or source.get('preparation')!=preparation or source.get('formal046')!=str(original)
            or active!=Path(prep['worker']).parents[2].with_name('0.4.7')):_fail()
    _,_,_,initial,current=_original(source,native,realtime=True)
    if current!=initial or _slot_binding(_slot(native))!=source['old_slot'] or _load(native.root/'geometry-state.json')!=source['session_state']:_fail()
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.7');b,bf,indices=_package(formal,'0.4.7')
    if a!=b or af!=bf or active==formal or formal.is_relative_to(native.root):_fail()
    payload={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'consumer_runtime':{'package_root':str(formal),'package_sources':indices},**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(native._canonical({'payload':payload,'signature':_sign(native,payload)})+b'\n');stream.flush();os.fsync(stream.fileno())
    return file_record(path)


def attempt_for(preparation,authority,native=None):return copy.deepcopy(validate(preparation,authority,native)[0]['cold_attempt'])


def reconcile_slot(preparation,authority):
    """只在锁内证明确认的旧prelaunch才能fence/release；不改变Native计账。"""
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    from .geometry_job import _write
    _,native=_context(preparation);p,_=validate(preparation,authority,native);source=_object(_read(_object(_read(authority))['payload']['source']))
    existing=_verified_release(native,source)
    if existing is not None:return existing
    scheduler=GraphScheduler(native.root/'scheduler');old=source['old_slot']
    def check(row):
        if _slot_binding(row)!=old:_fail()
        _,_,_,initial,current=_original(source,native,realtime=True)
        if initial!=current:_fail()
    scheduler._fence_verified_prelaunch_dispatch(old['owner_root'],old['operation_id'],old['token'],old['generation'],check)
    scheduler.release(old['owner_root'],old['operation_id'],old['token'],unstarted=True)
    after=_slot_binding(_slot(native));payload={'schema':'bridge.geometry-prelaunch-release/1','scope':native.binding,'authority':authority,'old_slot':old,'cold_attempt':source['cold_attempt'],'released':True,'after':after,'observed_at':time.time()}
    directory=Path(source['cold_attempt']['journal_directory']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    return _write(directory/'slot-release.json',{'payload':payload,'signature':_sign(native,payload,b'bridge.geometry-prelaunch-release/1\x00')},new=True)


def cold_binding(native,*,operation_id,snapshot_record,input_contract_record,result_path,observation=False,pre_admission=False):
    """只接受047受签的新NR子attempt；保原Geometry主job及全部实际消费身份门。"""
    from .geometry_seed_cold_resume import _verify_finalization
    preparation=file_record(native.root/'geometry-preparation.json');authority=file_record(native.root/_AUTH);p,original=validate(preparation,authority,native);source=_object(_read(_object(_read(authority))['payload']['source']));attempt=p['cold_attempt'];state=native._read()
    if operation_id!=attempt['operation_id']:_fail()
    snapshot=_bytes(snapshot_record);contract=_object(_bytes(input_contract_record));expected=original['nk_binding']['final_nk'];result=_path(result_path)
    if (snapshot_record['bytes']!=expected['bytes'] or snapshot_record['sha256']!=expected['sha256'] or file_record(expected['path'])!=expected
            or contract.get('schema')!='bridge.nuke.registered-input-contract/1.0' or contract.get('owner_task_id')!=native.scope['task_id']
            or contract.get('registry_root')!=str(native.root/'artifact_ledger')):_fail()
    _verify_finalization(preparation,p['finalization_authority'],original['nk_binding'])
    task_path=native.root/'state/nuke_renders'/(operation_id+'.json');matches=[]
    if observation:
        if (_verified_release(native,source) is not None or state!=source['accounting_envelope']['payload']['state']
                or task_path.exists() or (Path(attempt['journal_directory'])/'dispatch.json').exists() or result.is_relative_to(native.root)
                or any((native.root/'state/nuke_renders').glob(operation_id+'*.input-proof.json'))
                or (native.root/'state/nuke_renders'/(operation_id+'.supervisor')).exists()):_fail()
        if _slot_binding(_slot(native))!=source['old_slot']:_fail()
    else:
        if _verified_release(native,source) is None:_fail()
        if (input_contract_record['path']!=str(native.root/'state/nuke_renders'/(operation_id+'.inputs.json')) or snapshot_record['path']!=str(native.root/'state/nuke_renders'/(operation_id+'.nk'))
                or result!=native.root/'state/nuke_renders'/(operation_id+'.worker-result.json')):_fail()
        task=_load(task_path);slot=task.get('slot') or {}
        if (task.get('task_id')!=operation_id or task.get('request_id')!=attempt['request_id'] or task.get('owner_task_id')!=native.scope['task_id']
                or task.get('input_contract')!=contract or task.get('script_snapshot')!=snapshot_record['path'] or task.get('scene_fingerprint')!=expected['sha256']
                or task.get('frame_set')!=[1] or task.get('node')!='Write1' or task.get('pattern')!=original['nk_binding']['output_pattern']
                or slot.get('owner_root')!=source['old_slot']['owner_root'] or slot.get('operation_id')!=operation_id or slot.get('generation')!=source['old_slot']['generation']+1):_fail()
        row=_slot(native)
        if row is None or any(row.get(key)!=slot.get(key) for key in ('owner_root','operation_id','token','generation')) or row.get('active')!=1 or row.get('phase')!='DISPATCHING':_fail()
        if pre_admission:
            if state!=source['accounting_envelope']['payload']['state'] or row.get('process_json') is not None:_fail()
        else:
            from dcc_task_runtime import owned_process
            matches=[ticket for ticket in state['tickets'][16:] if ticket['role']=='nuke-render' and ticket['identity'].get('task_id')==operation_id and ticket['stopped_at'] is None]
            if len(state['tickets'])!=17 or len(matches)!=1:_fail()
            ticket=matches[0];started=owned_process.read_receipt(ticket['directory'],'started',identity=ticket['identity']);intent=_load(Path(ticket['directory'])/'intent.json')
            if (not started or started.get('pid')!=os.getpid() or ticket['identity'].get('snapshot_sha256')!=snapshot_record['sha256']
                    or ticket['identity'].get('input_contract_sha256')!=canonical_sha256(contract) or started.get('argv_sha256')!=canonical_sha256(intent.get('command'))):_fail()
    return {'schema':'bridge.geometry-seed-cold-worker-binding/1','owner_task_id':native.scope['task_id'],'main_job_record':source['job'],'operation_id':attempt['main_operation_id'],
            'approved_pattern':original['nk_binding']['output_pattern'],'authority':authority,'low_authority':original['budget_authority'],'input_source':original['input_source'],
            'final_nk':expected,'readset':[authority,*p['readset'],snapshot_record,input_contract_record],
            'accounting_prefix':source['journal_prefix'],'accounting_envelope':source['accounting_envelope'],'current_ticket':matches[0] if matches else None,'observation_only':bool(observation)}


def validate_unstarted_attempt(native,operation,task,permit,row):
    """047异常清理的可信事务内门；未知启动不得释放，普通路由不使用此门。"""
    preparation=file_record(native.root/'geometry-preparation.json');authority=file_record(native.root/_AUTH);p,original=validate(preparation,authority,native);source=_object(_read(_object(_read(authority))['payload']['source']));attempt=p['cold_attempt']
    if operation!=attempt['operation_id'] or task is None or task.get('task_id')!=operation or task.get('request_id')!=attempt['request_id'] or task.get('owner_task_id')!=native.scope['task_id']:_fail()
    slot=task.get('slot') or {}
    if (any(slot.get(key)!=permit.get(key) for key in ('owner_root','operation_id','token','generation'))
            or any(row.get(key)!=permit.get(key) for key in ('owner_root','operation_id','token','generation'))
            or row.get('phase')!='DISPATCHING' or row.get('process_json') is not None or row.get('cancel_requested')!=0
            or slot.get('generation')!=source['old_slot']['generation']+1 or native._read()!=source['accounting_envelope']['payload']['state']):_fail()
    snapshot=native.root/'state/nuke_renders'/(operation+'.nk');inputs=native.root/'state/nuke_renders'/(operation+'.inputs.json')
    expected=original['nk_binding']['final_nk'];contract=_load(inputs);record=file_record(snapshot)
    if (record['bytes']!=expected['bytes'] or record['sha256']!=expected['sha256'] or task.get('script_snapshot')!=str(snapshot)
            or task.get('scene_fingerprint')!=expected['sha256'] or task.get('input_contract')!=contract
            or contract.get('schema')!='bridge.nuke.registered-input-contract/1.0' or contract.get('owner_task_id')!=native.scope['task_id']
            or contract.get('registry_root')!=str(native.root/'artifact_ledger') or task.get('frame_set')!=[1] or task.get('node')!='Write1'
            or task.get('pattern')!=original['nk_binding']['output_pattern'] or task.get('process') is not None or task.get('supervisor_intent') is not None
            or task.get('execution_fact') is not None):_fail()
    if any((native.root/'state/nuke_renders').glob(operation+'*.input-proof.json')) or (native.root/'state/nuke_renders'/(operation+'.supervisor')).exists():_fail()


def effective(preparation,runtime,authority):
    """047仅服务已签续尾入口，不能用作新Geometry作业分派。"""
    prep,native=_context(preparation);runtime=_path(runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.7')/'runtime':_fail()
    p,source=validate(preparation,authority,native)
    packages=_packages(_path(_object(_read(authority))['payload']['original_plugin_root']),runtime.parent)
    if packages['active_worker']!=p['active_worker']:_fail()
    native.check();return p,source


def _dispatch(native,source,authority):
    """同主操作的增量派发只有一次，不能拿047代码授权直接执行。"""
    path=Path(source['cold_attempt']['journal_directory'])/'dispatch.json';value=_load(path);p=value.get('payload')
    if (set(value)!={'payload','signature'} or type(p) is not dict or not hmac.compare_digest(str(value['signature']),_sign(native,p,b'bridge.geometry-prelaunch-dispatch/1\x00'))
            or p.get('schema')!='bridge.geometry-prelaunch-dispatch/1' or p.get('state')!='INTENT' or p.get('authority')!=authority
            or p.get('preparation')!=source['preparation'] or p.get('job')!=source['job'] or p.get('cold_attempt')!=source['cold_attempt']
            or p.get('slot_release')!=_verified_release(native,source)):_fail()
    return file_record(path),p


def verify_result_extension(native,job,result,*,_metadata_context=None):
    """canonical结果可覆盖观察优先级，但必须证明它来自唯一047子attempt。"""
    if (result.get('prelaunch_continuation') or {}).get('schema') in ('bridge.geometry-prelaunch-metadata-result/1','bridge.geometry-prelaunch-metadata-result/2'):
        from .geometry_metadata_completion import verify_result_extension as metadata_verify
        return metadata_verify(native,job,result,_metadata_context=_metadata_context)
    extension=result.get('prelaunch_continuation');authority=file_record(native.root/_AUTH);p,_=validate(job['preparation'],authority,native)
    source=_object(_read(_object(_read(authority))['payload']['source']));attempt=p['cold_attempt'];directory=Path(attempt['journal_directory'])
    if not isinstance(extension,dict) or set(extension)!={'payload','signature'}:_fail()
    payload=extension['payload'];base={k:v for k,v in result.items() if k!='prelaunch_continuation'}
    expected={'schema':'bridge.geometry-prelaunch-result/1','authority':authority,'source':_object(_read(authority))['payload']['source'],
              'job':source['job'],'prior_error':source['error'],'journal':file_record(directory/'incremental-state.json'),
              'dispatch':_dispatch(native,source,authority)[0],'slot_release':_verified_release(native,source),'cold_attempt':attempt,'result_sha256':canonical_sha256(base)}
    if (payload!=expected or not hmac.compare_digest(str(extension['signature']),_sign(native,payload,b'bridge.geometry-prelaunch-result/1\x00'))
            or file_record(Path(job['directory'])/'job.json')!=source['job'] or result.get('nuke',{}).get('operation_id')!=attempt['operation_id']):_fail()
    _bytes(payload['journal']);task=_load(native.root/'state/nuke_renders'/(attempt['operation_id']+'.json'))
    if task.get('request_id')!=attempt['request_id'] or task.get('task_id')!=attempt['operation_id'] or task.get('owner_task_id')!=native.scope['task_id']:_fail()
    return directory/'incremental-state.json'


def run_tail(job_path,authority):
    """新控制器只运行已认证seed的冷消费尾段；不改原046 job/error/journal。"""
    from dcc_task_runtime.execution_lock import execution_lock
    from dcc_task_runtime.platform_support import process_identity
    from .geometry_job import JobJournal,_write,_finish_seed_cold_resume,validate_result,ROOT
    from .geometry_seed_cold_resume import _check_job
    job_path=_path(job_path);job=_load(job_path);prep,native=_context(job['preparation']);p,original=effective(job['preparation'],ROOT,authority)
    source=_object(_read(_object(_read(authority))['payload']['source']));attempt=p['cold_attempt'];directory=Path(attempt['journal_directory'])
    if file_record(job_path)!=source['job'] or (Path(job['directory'])/'result.json').exists():_fail()
    _dispatch(native,source,authority)
    with execution_lock(directory,'geometry-prelaunch-tail'):
        if (directory/'execute-owner.json').exists() or (directory/'error.json').exists():_fail()
        _write(directory/'execute-owner.json',{'schema':'bridge.geometry-prelaunch-execute-owner/1','job':source['job'],'authority':authority,'process_identity':process_identity(os.getpid())},new=True)
        try:
            # 原046身份校验后，仅内存执行映射改为受签047子attempt。
            from .geometry_cold_preflight_runtime import validate as validate_old
            old,_=validate_old(job['preparation'],source['original_authority'],native);details=_check_job(job,old,original)
            jobprep=_object(_bytes(source['job_preparation']));journal=JobJournal(directory,source['job']);previous=_object(_bytes(source['journal']))
            for name in ('reuse_seed_cold_source','text_finalize'):
                journal.action(name,lambda name=name:copy.deepcopy(previous['stages'][name]['result']))
            os.environ.clear();os.environ.update(prep['environment']);execution_job=copy.deepcopy(job);execution_job['runtime_continuation']=authority
            result=_finish_seed_cold_resume(prep,execution_job,jobprep,details,journal)
            payload={'schema':'bridge.geometry-prelaunch-result/1','authority':authority,'source':_object(_read(authority))['payload']['source'],
                     'job':source['job'],'prior_error':source['error'],'journal':file_record(journal.path),'dispatch':_dispatch(native,source,authority)[0],
                     'slot_release':_verified_release(native,source),'cold_attempt':attempt,'result_sha256':canonical_sha256(result)}
            result['prelaunch_continuation']={'payload':payload,'signature':_sign(native,payload,b'bridge.geometry-prelaunch-result/1\x00')}
            validate_result(job['preparation'],job,result);_write(Path(job['directory'])/'result.json',result,new=True)
        except BaseException as error:
            _write(directory/'error.json',{'schema':'bridge.geometry-prelaunch-error/1','authority':authority,'job':source['job'],'operation_id':job['operation_id'],
                   'code':type(error).__name__,'message':str(error),'notes':getattr(error,'__notes__',[]),'native_dispatch_attempted':len(native._read()['tickets'])>16},new=True)
            raise


def observe_continuation(native,entry,job):
    """续尾活动时观察新控制器；原046失败仍作为永久前置事实。"""
    authority=entry.get('prelaunch_continuation');p,_=validate(job['preparation'],authority,native);source=_object(_read(_object(_read(authority))['payload']['source']))
    if source['job']!=entry['job_file']:_fail()
    directory=Path(p['cold_attempt']['journal_directory']);_dispatch(native,source,authority)
    error=directory/'error.json'
    if error.exists():
        value=_load(error)
        if value.get('authority')!=authority or value.get('job')!=source['job']:_fail()
        return {'operation_id':job['operation_id'],'state':'FAILED' if all(t['stopped_at'] is not None for t in native._read()['tickets']) else 'UNKNOWN','error':file_record(error),'native_dispatch_attempted':value.get('native_dispatch_attempted')}
    started=directory/'controller-started.json'
    if not started.exists():return {'operation_id':job['operation_id'],'state':'UNKNOWN','native_dispatch_attempted':False}
    value=_load(started)
    if value.get('authority')!=authority or value.get('job')!=source['job']:_fail()
    status=process_status(value['process_identity'])
    return {'operation_id':job['operation_id'],'state':'RUNNING' if status=='running' else 'UNKNOWN','native_dispatch_attempted':len(native._read()['tickets'])>16,'continuation_authority':authority}
