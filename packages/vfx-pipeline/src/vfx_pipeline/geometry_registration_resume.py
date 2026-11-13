"""第二版仅续登记及Nuke下游；原保存/冷开/渲染事实保留原操作身份。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os,sqlite3,sys,types
from pathlib import Path
from contextlib import contextmanager,closing
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope,_accounting_lock
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from .geometry_render_resume import _path,_read,_object,_load,_source_closure

_SOURCE='bridge.geometry-registration-source/1'
_SCHEMA='bridge.geometry-registration-authorization/1'
_AUTH='geometry-registration-resume-authorization.json'
_DOMAIN=b'bridge.geometry-registration-authorization/1\x00'
_STAGES={'baseline_reopen','feedback_0','feedback_1','feedback_2','save','warm_geometry','edit_host_stop','cold_reopen','cold_geometry','evaluate','render','render_completed','render_host_stop','verify'}
_NAMES=('canonical','models','errors','contracts','windows_process','platform_support','pipeline_store','project_color','exr_codec','artifact_registry')
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_registration_resume.py','runtime/tools/resume_geometry_registration.py'}
_CHANGED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py','runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py'}|{'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_job','geometry_session','geometry_runtime_binding','feedback_versions','workbuddy_graph_mcp','production_hosts')}


def _fail():raise ValueError('GEOMETRY_REGISTRATION_RESUME_INVALID')


def _context(record,*,native=None):
    """已有上下文只复验同准备/scope身份；默认仍完整构造并认证NativeScope。"""
    prep=_object(_read(record));native=NativeScope(prep['scope']) if native is None else native
    if (Path(record['path'])!=native.root/'geometry-preparation.json' or prep.get('schema')!='bridge.geometry-creative-preparation/1'
            or prep.get('scope')!=native.binding or prep.get('task_id')!=native.scope['task_id']):_fail()
    return prep,native


@contextmanager
def _database(path):
    path=_path(path)
    if any(Path(str(path)+suffix).exists() and Path(str(path)+suffix).stat().st_size for suffix in ('-wal',)):_fail()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:yield db


def _registry_state(prep):
    with _database(Path(prep['ledger_root'])/'artifacts.sqlite3') as db:
        row=db.execute("SELECT payload_json FROM artifact_versions WHERE artifact_id='geometry_main' AND version=1").fetchone()
        invalid=db.execute("SELECT reason FROM artifact_invalidations WHERE artifact_id='geometry_main' AND version=1").fetchone()
        later=db.execute("SELECT version FROM artifact_versions WHERE artifact_id='geometry_main' AND version>1").fetchall()
    if not row or not invalid:_fail()
    return {'version1':json.loads(row[0]),'invalidation':invalid[0],'version2_absent':not later}


def _chain(control,graph):
    from .feedback_versions import FeedbackVersions
    from .official_graph_resume import _VerifiedCompiledGraph
    run=types.SimpleNamespace(pipeline_task_id=graph['task_id'],jobs=_VerifiedCompiledGraph(graph),_connect=lambda:_database(Path(control)/'diagnostic.sqlite3'))
    reader=object.__new__(FeedbackVersions);reader.run=run
    return reader.completed_revision_chain(graph['graph_id'],0,3)


@contextmanager
def metadata_facade(prep,details,registry):
    """只装配按需边界；登记只允许原output.verify.status，不调用宿主激活。"""
    from .official_graph_resume import resume_graph_facade
    control=Path(details['control']);graph=details['graph_source'];native=NativeScope(prep['scope'])
    with resume_graph_facade(control/'run.json',graph,repo_root=control/'snapshot',scheduler_root=native.root/'scheduler',checkpoint_task_copy=True) as facade:
        facade.artifact_registry=registry;facade.host_client.bind_artifact_registry(registry)
        yield facade


def _details(source,native,*,full_native=False):
    fields={'schema','preparation','task_id','operation_id','job','execution_preparation','journal','error','control','files','stage_sha256','graph_source','base_result','base_acceptance','feedback_chain','registration_observation','accounting_envelope','journal_prefix'}
    if set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id']:_fail()
    prep=_object(_read(source['preparation']));job=_object(_read(source['job']));directory=native.root/'jobs'/source['operation_id'];control=directory/'project/control'
    if (source['preparation']['path']!=str(native.root/'geometry-preparation.json') or prep.get('scope')!=native.binding
            or source['job']['path']!=str(directory/'job.json') or job.get('preparation')!=source['preparation']
            or job.get('task_id')!=source['task_id'] or job.get('operation_id')!=source['operation_id'] or job.get('directory')!=str(directory)
            or job.get('revision')!=2 or any(n in job for n in ('registration_source','nuke_source','render_source','source_checkpoint'))
            or source['control']!=str(control)):_fail()
    journal=_object(_read(source['journal']));error=_object(_read(source['error']));jobprep=_object(_read(source['execution_preparation']))
    if (source['journal']['path']!=str(directory/'incremental-state.json') or source['error']['path']!=str(directory/'error.json')
            or source['execution_preparation']['path']!=str(directory/'job-preparation.json') or jobprep.get('job')!=source['job']
            or jobprep.get('control')!=str(control) or journal.get('job')!=source['job']
            or error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='FEEDBACK_REVISION_CONTENT_VERSION_REQUIRED' or error.get('stop_confirmed') is not True
            or error.get('preparation_record')!=source['preparation'] or error.get('operation_id')!=source['operation_id']):_fail()
    stages=journal.get('stages',{})
    if (set(stages)!=_STAGES|{'register'} or any(stages[n].get('state')!='DONE' for n in _STAGES)
            or stages['register'].get('state')!='INTENT' or 'result' in stages['register']
            or source['stage_sha256']!={n:canonical_sha256(stages[n]['result']) for n in _STAGES}):_fail()
    details={n:copy.deepcopy(stages[n]['result']) for n in _STAGES}
    details.update(control=str(control),project=str(control.parent),operation_id=source['operation_id'],graph_source=source['graph_source'])
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    prefix=_prefix(native,source['journal_prefix'],source['accounting_envelope']);original=prefix['state'];tickets=original.get('tickets',[])
    with _accounting_lock(native.state_path):current=native._read()
    if (original.get('closed_reason') is not None or len(tickets)!=14 or any(t.get('stopped_at') is None for t in tickets)
            or current['tickets'][:14]!=tickets or original.get('scope_sha256')!=native.binding['sha256']
            or sorted(t['role'] for t in tickets)!=sorted(['graph-worker']*2+['houdini-host']*7+['main-husk']*2+['nuke-host']+['nuke-render']*2)):_fail()
    for t in tickets:
        stop=native._stop(t)
        if not stop or hashlib.sha256(native._canonical(stop)).hexdigest()!=t['stopped_sha256']:_fail()
    files=source['files'];expected={'hip','main','verified_output','owners','manifest','snapshot_manifest','deployment'}
    if set(files)!=expected:_fail()
    for r in files.values():_read(r)
    saved=details['save'];cold=details['cold_geometry'];reopened=details['cold_reopen'];verified=details['verify'];fact=verified['execution_fact']
    if (files['hip']!=file_record(Path(saved['path'])) or saved['sha256']!=files['hip']['sha256']
            or files['main']!=file_record(control.parent/'saves/main.0001.exr') or canonical_sha256(saved['scene_contract'])!=saved['scene_contract_sha256']
            or reopened.get('sha256')!=saved['sha256'] or reopened.get('load_warnings')!=[]
            or any(reopened.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))
            or reopened.get('scene_contract_sha256')!=saved['scene_contract_sha256']):_fail()
    from .geometry_native_evidence import verify_historical
    from .geometry_job import _verify_cold_geometry,_accepted_result
    verify_historical(details['warm_geometry'],saved,native.binding,source['operation_id']+'_warm','warm',accounting_prefix=source['journal_prefix'],accounting_envelope=source['accounting_envelope'])
    verify_historical(cold,saved,native.binding,source['operation_id']+'_cold','cold',transition=reopened,accounting_prefix=source['journal_prefix'],accounting_envelope=source['accounting_envelope']);_verify_cold_geometry(cold,reopened)
    if cold['geometry_observation']!=details['warm_geometry']['geometry_observation']:_fail()
    session=_load(native.root/'geometry-state.json');completed=session['completed']
    if len(completed) not in (1,2):_fail()
    entry=session['jobs'][completed[0]]
    if entry.get('result')!=source['base_result'] or entry.get('acceptance')!=source['base_acceptance']:_fail()
    _read(source['base_result']);_read(source['base_acceptance']);base=_accepted_result(source['preparation'],completed[0])
    from .geometry_evaluation import evaluate_feedback
    if evaluate_feedback(base['geometry']['geometry_observation'],cold['geometry_observation'],_object(_read(prep['criteria'])))!=details['evaluate']:_fail()
    from .official_graph_resume import inspect_resume_source,_snapshot
    graph=source['graph_source']
    if graph!=inspect_resume_source(graph['preparation']['path'],graph['operation_id']) or graph!=base['graph_source']:_fail()
    if _chain(control,graph)!=source['feedback_chain']:_fail()
    for name,path in {'verified_output':control/'host-state'/('verified-output-'+source['operation_id']+'_verify.json'),
            'owners':control/'host-state/houdini-operation-owners.json','manifest':control/'run.json','snapshot_manifest':control/'snapshot-manifest.json','deployment':control/'production-hosts.json'}.items():
        if files[name]!=file_record(path):_fail()
    if (_object(_read(files['verified_output']))!=fact or fact.get('operation_id')!=source['operation_id']+'_verify'
            or fact.get('parent_operation_id')!=source['operation_id']+'_render' or fact.get('task_id')!=source['task_id']
            or fact.get('state')!='COMPLETED' or fact.get('stop_confirmed') is not True or fact.get('frame_set')!=[1]
            or fact.get('output_pattern')!=str(control.parent/'saves/main.%04d.exr') or _snapshot(control)!=files['snapshot_manifest']):_fail()
    snapshot=fact['frame_snapshots']['1']
    if any(snapshot[k]!=files['main'][k] for k in ('path','bytes','sha256')):_fail()
    prior=_registry_state(prep);observation=source['registration_observation']
    if (observation.get('version2_absent') is not True or observation.get('version1')!=prior['version1']
            or observation.get('invalidation')!=prior['invalidation']):_fail()
    if full_native:
        if not prior['version2_absent'] or current!=original:_fail()
        from .artifact_registry import ArtifactRegistry
        with metadata_facade(prep,details,ArtifactRegistry(prep['ledger_root'])) as f:
            actual=f.operation_query(source['operation_id']+'_verify').get('execution_fact')
            if actual!=fact:_fail()
    return details


def inspect_source(failed_job_path):
    path=_path(failed_job_path);job=_load(path);prep,native=_context(job['preparation']);directory=path.parent;control=directory/'project/control'
    journal=_load(directory/'incremental-state.json');stages=journal['stages'];session=_load(native.root/'geometry-state.json');baseentry=session['jobs'][session['completed'][0]]
    base=_object(_read(baseentry['result']));graph=base['graph_source'];native.completed_snapshot();raw=native.journal_path.read_bytes()
    source={'schema':_SOURCE,'preparation':job['preparation'],'task_id':job['task_id'],'operation_id':job['operation_id'],
        'job':file_record(path),'execution_preparation':file_record(directory/'job-preparation.json'),'journal':file_record(directory/'incremental-state.json'),
        'error':file_record(directory/'error.json'),'control':str(control),'stage_sha256':{n:canonical_sha256(stages[n]['result']) for n in _STAGES},
        'graph_source':graph,'base_result':baseentry['result'],'base_acceptance':baseentry['acceptance'],'feedback_chain':_chain(control,graph),
        'registration_observation':_registry_state(prep),'accounting_envelope':_load(native.state_path),
        'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
        'files':{'hip':file_record(Path(stages['save']['result']['path'])),'main':file_record(control.parent/'saves/main.0001.exr'),
            'verified_output':file_record(control/'host-state'/('verified-output-'+job['operation_id']+'_verify.json')),
            'owners':file_record(control/'host-state/houdini-operation-owners.json'),'manifest':file_record(control/'run.json'),
            'snapshot_manifest':file_record(control/'snapshot-manifest.json'),'deployment':file_record(control/'production-hosts.json')}}
    _details(source,native,full_native=True);return source


def _packages(original,active):
    from .geometry_runtime_binding import _package
    old,of,osources=_package(original,'0.3.8');new,nf,nsources=_package(active,'0.3.9');changed={n for n in of if n in nf and of[n]!=nf[n]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':osources+nsources,
        'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
        'differences':[{'name':n,'before':file_record(original/n) if n in of else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}


def _runtime(root):
    from .geometry_runtime_binding import _package
    _,index,_=_package(root,'0.3.9');files={}
    for name in _NAMES:
        rel='runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+name+'.py';r=file_record(root/rel)
        if index[rel]['sha256']!=r['sha256']:_fail()
        files[name]=r
    return {'package_root':str(root),'files':files}


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest();return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _request(record,prep,source,native):
    r=_object(_read(record));job=_object(_read(source['job']));plan=copy.deepcopy(job['plan']);plan['plan_id']+='_registration_resume01'
    plan['operator_repair']={'schema':'bridge.geometry-registration-resume/1','failed_operation_id':job['operation_id'],'authorization_path':str(native.root/_AUTH)}
    plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'});rid='operator_registration_resume01_'+job['operation_id'];op='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
    if (set(r)!={'schema','preparation','task_id','failed_operation_id','failed_job','registration_source','new_plan','request_id','new_operation_id','original_plan_sha256'}
            or record['path']!=str(native.root/'geometry-registration-resume-request.json') or r.get('schema')!='bridge.geometry-registration-request/1'
            or r.get('preparation')!=prep or r.get('task_id')!=native.scope['task_id'] or r.get('failed_operation_id')!=job['operation_id']
            or r.get('failed_job')!=source['job'] or _object(_read(r['registration_source']))!=source
            or r['registration_source']['path']!=str(native.root/'geometry-registration-resume-source.json')
            or r.get('new_plan')!=plan or r.get('request_id')!=rid or r.get('new_operation_id')!=op or r.get('original_plan_sha256')!=job['plan']['plan_sha256']):_fail()
    return r


def _closure(source,details,native):
    """原账本按签名prefix认证，不能把可增长journal误当不可变整文件。"""
    fixed=copy.deepcopy(source);fixed.pop('journal_prefix',None)
    return _source_closure(fixed,details,native)


def validate(preparation_record,authority,native=None):
    prep,current=_context(preparation_record);native=current if native is None else native
    if authority.get('path')!=str(native.root/_AUTH) or _path(authority['path']).stat().st_mode&0o077:_fail()
    v=_object(_read(authority));p=v.get('payload')
    fields={'schema','preparation','native_scope','task_id','source','request','authority','source_closure','registration_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(v)!={'payload','signature'} or not isinstance(p,dict) or set(p)!=fields or not hmac.compare_digest(str(v['signature']),_sign(native,p))
            or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation_record or p.get('native_scope')!=native.binding or p.get('task_id')!=native.scope['task_id']
            or p.get('source',{}).get('path')!=str(native.root/'geometry-registration-resume-source.json')
            or set(p.get('authority',{}))!={'authority','instruction'} or p['authority']['authority']!='current_user_instruction'
            or not isinstance(p['authority'].get('instruction'),str) or not 10<=len(p['authority']['instruction'])<=16000):_fail()
    source=_object(_read(p['source']));details=_details(source,native)
    if p['source_closure']!=_closure(source,details,native) or p['registration_runtime']!=_runtime(_path(p['registration_runtime']['package_root'])):_fail()
    _request(p['request'],preparation_record,source,native);return p,details


def create_authorization(preparation_record,original038formal,active039cache,registration039formal,failed_job_path,source_record,request_record,instruction):
    prep,native=_context(preparation_record);formal=_path(original038formal);active=_path(active039cache);registration=_path(registration039formal)
    if (active!=Path(prep['worker']).parents[2].with_name('0.3.9') or not isinstance(instruction,str) or not 10<=len(instruction)<=16000):_fail()
    source=_object(_read(source_record));details=_details(source,native,full_native=True)
    if source['job']!=file_record(_path(failed_job_path)) or source['preparation']!=preparation_record:_fail()
    from .geometry_nuke_resume import validate as prior_validate,_packages as prior_packages
    from .geometry_runtime_binding import _rebase_package,_package
    job=_object(_read(source['job']));prior,_=prior_validate(preparation_record,job['runtime_continuation'],native)
    old=prior_packages(_path(prior['original_plugin_root']),formal);former=_path(prior['active_plugin_root'])
    if any(_rebase_package(prior.get(k),former,formal)!=v for k,v in old.items()):_fail()
    packages=_packages(formal,active)
    a,af,_=_package(active,'0.3.9');b,bf,_=_package(registration,'0.3.9')
    if a!=b or af!=bf or registration==active or registration.is_relative_to(native.root):_fail()
    _request(request_record,preparation_record,source,native)
    p={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'request':request_record,
        'authority':{'authority':'current_user_instruction','instruction':instruction},'source_closure':_closure(source,details,native),
        'registration_runtime':_runtime(registration),**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    record=file_record(path);validate(preparation_record,record,native);return record


def _effective(preparation_record,runtime_root):
    prep,native=_context(preparation_record);runtime=_path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.9')/'runtime':_fail()
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
    p,details=validate(job['preparation'],job.get('runtime_continuation',{}),native);r=_object(_read(p['request']))
    if (job.get('revision')!=2 or any(n in job for n in ('render_source','nuke_source','source_checkpoint')) or job.get('task_id')!=p['task_id']
            or job.get('operation_id')!=r['new_operation_id'] or job.get('plan')!=r['new_plan'] or job.get('registration_source')!=p['source']
            or job.get('execution_worker')!=p['active_worker']):_fail()
    if for_execution:
        if _effective(job['preparation'],runtime_root)[2]!=job['runtime_continuation']:_fail()
    return details


def implementation(preparation_record,authority,native):
    p,_=validate(preparation_record,authority,native)
    return {'schema':'bridge.geometry-registration-implementation/1','authorization':authority,**p['registration_runtime']}


def registration_registry_class(implementation,scope,task_id,*,source=None):
    """同一永久正式039实现负责登记和消费，生产snapshot及生产事实不改。"""
    if (not isinstance(implementation,dict) or set(implementation)!={'schema','authorization','package_root','files'}
            or implementation.get('schema')!='bridge.geometry-registration-implementation/1' or task_id!=scope.scope['task_id']):_fail()
    prep=file_record(scope.root/'geometry-preparation.json');p,details=validate(prep,implementation['authorization'],scope)
    if {k:implementation[k] for k in ('package_root','files')}!=p['registration_runtime']:_fail()
    if source is not None:
        records=_object(_read(p['source']))['files'];receipt=source.get('registry_operation_receipt') or {}
        if (source.get('schema')!='bridge.geometry-nuke-source/2' or source.get('task_id')!=task_id or source.get('producer_control')!=details['control']
                or source.get('producer_scope')!=file_record(scope.path) or source.get('producer_ledger')!=str(scope.root/'artifact_ledger')
                or source.get('registration_implementation')!=implementation or receipt.get('registry_path')!=str(scope.root/'artifact_ledger/artifacts.sqlite3')
                or source.get('artifact_id')!='geometry_main' or source.get('artifact_version')!=2
                or source.get('producer_fact_sha256')!=canonical_sha256(details['verify']['execution_fact'])
                or any(source.get(key)!=records[name] for key,name in (('producer_manifest','manifest'),('producer_snapshot_manifest','snapshot_manifest'),('producer_deployment','deployment'),('producer_owners','owners')))
                or receipt.get('artifact_id')!='geometry_main' or receipt.get('version')!=2 or receipt.get('task_id')!=task_id
                or receipt.get('operation_id')!=details['operation_id']+'_verify'):_fail()
    names=implementation['files'];alias='_bridge_geometry_registration_'+canonical_sha256(implementation['package_root'])
    if alias not in sys.modules:
        package=types.ModuleType(alias);package.__package__,package.__path__=alias,[];sys.modules[alias]=package
        try:
            for name in _NAMES:
                r=names[name];module=types.ModuleType(alias+'.'+name);module.__package__,module.__file__=alias,r['path'];sys.modules[module.__name__]=module;setattr(package,name,module)
                exec(compile(_read(r),r['path'],'exec'),module.__dict__)
        except BaseException:
            for key in tuple(sys.modules):
                if key==alias or key.startswith(alias+'.'):sys.modules.pop(key,None)
            raise
    return sys.modules[alias+'.artifact_registry'].ArtifactRegistry
