"""仅续接已证实未派发的几何渲染：复用原观测、原保存场景与同任务预算。"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing, contextmanager

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope, _accounting_lock
from houdini_bridge.official_karma_observation import checked_bytes, file_record

_SOURCE='bridge.geometry-render-resume-source/1'
_SCHEMA='bridge.geometry-render-resume-authorization/1'
_DOMAIN=b'bridge.geometry-render-resume-authorization/1\x00'
_AUTH='geometry-render-resume-authorization.json'
_STAGES={'graph_source','host_bind','save','warm_geometry','edit_host_stop','cold_reopen','cold_geometry','evaluate'}
# 只允许已审查的本次预算、宿主截止时间与上层续接文件变化。
_CHANGED={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/native_scope.py',
          'runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py'} | {
    'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+name+'.py'
    for name in ('production_hosts','geometry_job','geometry_session','geometry_runtime_binding')}
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_render_resume.py',
        'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_budget_addendum.py',
        'runtime/tools/resume_geometry_render.py'}


def _fail():raise ValueError('GEOMETRY_RENDER_RESUME_INVALID')


def _path(raw):
    path=Path(raw)
    if not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):_fail()
    return path


def _read(record):
    if (not isinstance(record,dict) or set(record)!={'path','bytes','sha256'}
            or type(record.get('bytes')) is not int or record['bytes']<0):_fail()
    _path(record['path']);return checked_bytes(record)


def _object(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:_fail()
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict):_fail()
    return value


def _load(path):return _object(_path(path).read_bytes())


def _context(preparation_record):
    prep=_object(_read(preparation_record));native=NativeScope(prep['scope'])
    if (Path(preparation_record['path'])!=native.root/'geometry-preparation.json'
            or prep.get('schema')!='bridge.geometry-creative-preparation/1'
            or prep.get('task_id')!=native.scope['task_id']
            or native.scope.get('schema')!='bridge.geometry-creative-scope/1'):_fail()
    return prep,native


def _packages(original,active):
    from .geometry_runtime_binding import _package
    if (original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes():_fail()
    old,of,osources=_package(original,'0.3.5');new,nf,nsources=_package(active,'0.3.6')
    changed={name for name in of if name in nf and of[name]!=nf[name]}
    if ({k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(of)-set(nf) or set(nf)-set(of)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),
            'package_sources':osources+nsources,'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
            'differences':[{'name':name,'before':file_record(original/name) if name in of else None,
                            'after':file_record(active/name)} for name in sorted(changed|_ADDED)]}


@contextmanager
def _read_database(path,*,record,stopped_owners):
    # 调用侧先认证原宿主停止票据和原source记录。空WAL没有待合并数据，SHM只含锁/索引元数据。
    # immutable仅读已验摘要的主库，不创建、删除或读取旁车内容；有WAL数据时仍拒绝。
    path=_path(path)
    if (record.get('path')!=str(path) or not isinstance(stopped_owners,list) or not stopped_owners
            or any(not isinstance(owner,dict) or owner.get('role')!='houdini-host' or owner.get('stopped_at') is None
                   or Path(owner.get('directory','')).parent!=path.parent/'houdini-task-host' for owner in stopped_owners)):_fail()
    def checked():
        _read(record)
        for suffix in ('-wal','-shm'):
            sidecar=Path(str(path)+suffix)
            if sidecar.exists() or sidecar.is_symlink():
                sidecar=_path(sidecar)
                if not sidecar.is_file() or (suffix=='-wal' and sidecar.stat().st_size!=0):_fail()
    checked()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:yield db
    checked()


def _source_details(source,native,*,full_native=True):
    """只读核验唯一deadline-before-transport失败；不接受一般UNKNOWN或已派发操作。"""
    fields={'schema','preparation','task_id','operation_id','job','execution_preparation','journal','error',
            'control','files','stage_sha256','native_snapshot'}
    if (set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id']):_fail()
    prep=_object(_read(source['preparation']));job=_object(_read(source['job']));directory=native.root/'jobs'/source['operation_id']
    if (source['preparation']['path']!=str(native.root/'geometry-preparation.json') or prep.get('scope')!=native.binding
            or source['job']['path']!=str(directory/'job.json') or job.get('preparation')!=source['preparation']
            or job.get('operation_id')!=source['operation_id'] or job.get('task_id')!=source['task_id']
            or job.get('directory')!=str(directory) or job.get('revision')!=1 or 'render_source' in job):_fail()
    # 原job必须是已认证的第二次检查点恢复，而非调用者任意新建的失败记录。
    from dcc_task_runtime.geometry_recovery import verify_checkpoint_job
    verify_checkpoint_job(job,native)
    jobprep=_object(_read(source['execution_preparation']));journal=_object(_read(source['journal']));error=_object(_read(source['error']))
    control=directory/'project/control'
    if (source['control']!=str(control) or source['execution_preparation']['path']!=str(directory/'job-preparation.json')
            or jobprep.get('job')!=source['job'] or jobprep.get('control')!=str(control)
            or source['journal']['path']!=str(directory/'incremental-state.json') or journal.get('job')!=source['job']
            or journal.get('schema')!='bridge.geometry-job-journal/1' or source['error']['path']!=str(directory/'error.json')
            or error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='PRODUCTION_HOST_DEADLINE_UNVERIFIED' or error.get('stop_confirmed') is not True
            or error.get('task_id')!=source['task_id'] or error.get('operation_id')!=source['operation_id']
            or error.get('revision')!=1 or error.get('preparation_record')!=source['preparation']):_fail()
    stages=journal.get('stages',{})
    if (set(stages)!=_STAGES|{'render'} or stages['render'].get('state')!='INTENT'
            or set(stages['render'])!={'state','started_at'}
            or any(stages[name].get('state')!='DONE' for name in _STAGES)
            or source['stage_sha256']!={name:canonical_sha256(stages[name]['result']) for name in _STAGES}):_fail()
    details={name:copy.deepcopy(stages[name]['result']) for name in _STAGES}
    details.update(control=str(control),operation_id=source['operation_id'])
    files=source['files'];expected={'hip','task_database','diagnostic_database','producer_store','producer_log','stderr',
                                  'production_hosts','snapshot_manifest','phase_budget_code','assembly_code'}
    if set(files)!=expected:_fail()
    for record in files.values():_read(record)
    saved=details['save'];reopened=details['cold_reopen'];graph=details['graph_source']
    if (files['hip']!=file_record(_path(saved['path'])) or Path(saved['path']).parent!=directory/'project/saves'
            or saved['sha256']!=files['hip']['sha256'] or saved['scene_contract']['task_id']!=source['task_id']
            or canonical_sha256(saved['scene_contract'])!=saved['scene_contract_sha256']):_fail()
    from .official_graph_resume import inspect_resume_source,_snapshot
    if inspect_resume_source(graph['preparation']['path'],graph['operation_id'])!=graph:_fail()
    _snapshot(control)
    from .geometry_native_evidence import verify
    from .geometry_job import _verify_cold_geometry
    if full_native:
        verify(details['warm_geometry'],saved,native.binding,source['operation_id']+'_warm','warm')
        verify(details['cold_geometry'],saved,native.binding,source['operation_id']+'_cold','cold',transition=reopened)
    _verify_cold_geometry(details['cold_geometry'],reopened)
    if details['warm_geometry']['geometry_observation']!=details['cold_geometry']['geometry_observation']:_fail()
    from .geometry_evaluation import evaluate_initial
    if (evaluate_initial(details['cold_geometry']['geometry_observation'],_object(_read(prep['criteria'])))!=details['evaluate']
            or details['evaluate'].get('state')!='PASS'):_fail()
    if (reopened.get('sha256')!=saved['sha256'] or reopened.get('load_warnings')!=[]
            or reopened.get('scene_contract_sha256')!=saved['scene_contract_sha256']
            or any(reopened.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))):_fail()
    snapshot=source['native_snapshot'];tickets=snapshot.get('tickets',[])
    with _accounting_lock(native.state_path):current=native._read()
    if (snapshot!=error.get('native_snapshot') or snapshot.get('scope_sha256')!=native.binding['sha256']
            or snapshot.get('closed_reason') is not None or snapshot.get('dcc_starts')!=6 or len(tickets)!=6
            or [t['role'] for t in tickets]!=['graph-worker','graph-worker']+['houdini-host']*4
            or any(t.get('stopped_at') is None for t in tickets) or current['tickets'][:6]!=tickets):_fail()
    if any(Path(t['directory']).parent!=control/'houdini-task-host' for t in tickets[4:]):_fail()
    producer=_path(files['producer_store']['path']);log=_path(files['producer_log']['path'])
    if (files['task_database']['path']!=str(control/'pipeline.sqlite3')
            or files['diagnostic_database']['path']!=str(control/'diagnostic.sqlite3')
            or producer.parent!=control/'houdini-instances/fx_operations' or producer.suffix!='.json'
            or log!=producer.with_suffix('.jsonl') or files['stderr']['path']!=str(directory/'controller.stderr.log')
            or files['production_hosts']['path']!=str(control/'production-hosts.json')
            or files['snapshot_manifest']['path']!=str(control/'snapshot-manifest.json')):_fail()
    with _read_database(control/'diagnostic.sqlite3',record=files['diagnostic_database'],stopped_owners=tickets[4:]) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('SELECT COUNT(*) FROM operation_registry').fetchone()[0]!=0:_fail()
    if (control/'houdini-operation-owners.json').exists():_fail()
    store=_load(producer)
    if (set(store)!={'scene_transition_cas','scene_transitions','task_id'} or store.get('task_id')!=source['task_id']) or any(
            _object(line).get('active')!=[] or _object(line).get('task_id')!=source['task_id']
            for line in log.read_bytes().splitlines()):_fail()
    if any(p.is_file() and p.suffix.lower() in {'.usd','.usda','.usdc','.exr'} for p in directory.rglob('*') if 'snapshot' not in p.parts):_fail()
    hosts=_load(files['production_hosts']['path'])
    if hosts.get('task_id')!=source['task_id']:_fail()
    config=hosts.get('hosts',{}).get('houdini',{});last=tickets[-1]
    from dcc_task_runtime.owned_process import read_receipt
    started=read_receipt(last['directory'],'started',identity=last['identity'])
    if (not started or started.get('budget_seconds')!=240 or config.get('session_seconds')!=240
            or config.get('native_scope')!=native.binding or config.get('lifecycle')!='task_owned'):_fail()
    code_paths={'phase_budget_code':control/'snapshot/packages/vfx-pipeline/src/vfx_pipeline/production_hosts.py',
                'assembly_code':control/'snapshot/packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py'}
    if any(files[name]['path']!=str(path) for name,path in code_paths.items()):_fail()
    assembly=_read(files['assembly_code']).decode('utf-8');budget=_read(files['phase_budget_code']).decode('utf-8')
    start=assembly.index("params['budget_seconds'] = host_phase_budget")
    transport=assembly.index('result = self._transport.call(command, params)',start)
    if transport<=start or 'not 0 < seconds <= 120' not in budget:_fail()
    stderr=_read(files['stderr']).decode('utf-8')
    required=('ValueError: signed host deadline missing','in houdini_render_bounded','in call',
              "params['budget_seconds'] = host_phase_budget",'in host_phase_budget','PRODUCTION_HOST_DEADLINE_UNVERIFIED')
    if any(text not in stderr for text in required):_fail()
    return details


def inspect_source(failed_job_path):
    """只读形成来源对象，不写真实来源、授权或预算记录。"""
    path=_path(failed_job_path);job=_load(path);prep,native=_context(job['preparation']);directory=path.parent;control=directory/'project/control'
    journal=_load(directory/'incremental-state.json');error=_load(directory/'error.json');stages=journal['stages']
    stores=[p for p in (control/'houdini-instances/fx_operations').glob('ops_*.json') if not p.name.endswith('.saves.json')]
    if len(stores)!=1:_fail()
    files={'hip':file_record(_path(stages['save']['result']['path'])),'task_database':file_record(control/'pipeline.sqlite3'),
           'diagnostic_database':file_record(control/'diagnostic.sqlite3'),'producer_store':file_record(stores[0]),
           'producer_log':file_record(stores[0].with_suffix('.jsonl')),'stderr':file_record(directory/'controller.stderr.log'),
           'production_hosts':file_record(control/'production-hosts.json'),'snapshot_manifest':file_record(control/'snapshot-manifest.json'),
           'phase_budget_code':file_record(control/'snapshot/packages/vfx-pipeline/src/vfx_pipeline/production_hosts.py'),
           'assembly_code':file_record(control/'snapshot/packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py')}
    source={'schema':_SOURCE,'preparation':job['preparation'],'task_id':job['task_id'],'operation_id':job['operation_id'],
            'job':file_record(path),'execution_preparation':file_record(directory/'job-preparation.json'),
            'journal':file_record(directory/'incremental-state.json'),'error':file_record(directory/'error.json'),
            'control':str(control),'files':files,'stage_sha256':{name:canonical_sha256(stages[name]['result']) for name in _STAGES},
            'native_snapshot':error.get('native_snapshot')}
    _source_details(source,native);return source


def _source_closure(source,details,native):
    """首签保存原证明的私有文件闭包；历史重读原件，不依赖已卸载cache或当前OS。"""
    records={}
    def collect(value):
        if isinstance(value,dict):
            if set(value)=={'path','bytes','sha256'}:
                path=_path(value['path'])
                if path.is_relative_to(native.root):
                    prior=records.get(str(path))
                    if prior is not None and prior!=value:_fail()
                    _read(value);records[str(path)]=copy.deepcopy(value)
            else:
                for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(source);collect(details)
    return [records[name] for name in sorted(records)]


def _sign(native,payload):
    key=hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _request(record,preparation,source,native):
    request=_object(_read(record));job=_object(_read(source['job']));plan=copy.deepcopy(job['plan'])
    plan['plan_id']+='_render_resume01';plan['operator_repair']={'schema':'bridge.geometry-render-resume/1',
        'failed_operation_id':job['operation_id'],'authorization_path':str(native.root/_AUTH)}
    plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'})
    rid='operator_render_resume01_'+job['operation_id'];operation='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
    fields={'schema','preparation','task_id','failed_operation_id','failed_job','render_source','new_plan','request_id','new_operation_id','original_plan_sha256'}
    if (set(request)!=fields or record['path']!=str(native.root/'geometry-render-resume-request.json')
            or request.get('schema')!='bridge.geometry-render-resume-request/1' or request.get('preparation')!=preparation
            or request.get('task_id')!=native.scope['task_id'] or request.get('failed_operation_id')!=job['operation_id']
            or request.get('failed_job')!=source['job'] or request.get('render_source',{}).get('path')!=str(native.root/'geometry-render-resume-source.json')
            or _object(_read(request['render_source']))!=source or request.get('new_plan')!=plan
            or request.get('request_id')!=rid or request.get('new_operation_id')!=operation
            or request.get('original_plan_sha256')!=job['plan']['plan_sha256']):_fail()
    return request


def validate(preparation_record,authority_record,native=None):
    """历史观察只验HMAC和原件，不读当前安装缓存、工具或重新授权。"""
    prep,current=_context(preparation_record);native=current if native is None else native
    if native.binding!=prep['scope'] or authority_record.get('path')!=str(native.root/_AUTH):_fail()
    path=_path(authority_record['path'])
    if path.stat().st_mode&0o077:_fail()
    envelope=_object(_read(authority_record));payload=envelope.get('payload')
    if (set(envelope)!={'payload','signature'} or not isinstance(payload,dict)
            or not hmac.compare_digest(str(envelope['signature']),_sign(native,payload))):_fail()
    fields={'schema','preparation','native_scope','task_id','source','request','budget_grant','authority',
            'original_plugin_root','active_plugin_root','package_sources','active_worker','differences','source_closure'}
    if (set(payload)!=fields or payload.get('schema')!=_SCHEMA or payload.get('preparation')!=preparation_record
            or payload.get('native_scope')!=native.binding or payload.get('task_id')!=native.scope['task_id']
            or payload.get('source',{}).get('path')!=str(native.root/'geometry-render-resume-source.json')
            or set(payload.get('authority',{}))!={'authority','instruction'}
            or payload['authority']['authority']!='current_user_instruction'
            or not isinstance(payload['authority']['instruction'],str) or not 10<=len(payload['authority']['instruction'])<=16000):_fail()
    from dcc_task_runtime.geometry_budget_addendum import validate as validate_grant
    grant,_,original=validate_grant(native,payload['budget_grant'])
    if grant.get('preparation')!=preparation_record:_fail()
    source=_object(_read(payload['source']));details=_source_details(source,native,full_native=False)
    if (source['native_snapshot']['tickets']!=original['tickets']
            or payload['source_closure']!=_source_closure(source,details,native)):_fail()
    _request(payload['request'],preparation_record,source,native)
    return payload,details


def create_authorization(preparation_record,original035formal,active036cache,failed_job_path,source_record,request_record,budget_grant_record,instruction):
    """只签上层渲染续接，不激活预算、不清闭、不启动原生程序。"""
    prep,native=_context(preparation_record);original=_path(original035formal);active=_path(active036cache)
    if (not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip()
            or Path(prep['worker']).parents[2].name!='0.3.1'
            or active!=Path(prep['worker']).parents[2].with_name('0.3.6')):_fail()
    source=_object(_read(source_record));details=_source_details(source,native)
    if source['job']!=file_record(_path(failed_job_path)) or source['preparation']!=preparation_record:_fail()
    from dcc_task_runtime.geometry_budget_addendum import validate as validate_grant
    grant,_,original_state=validate_grant(native,budget_grant_record)
    if (grant.get('preparation')!=preparation_record or native._read()!=original_state
            or original_state['tickets']!=source['native_snapshot']['tickets'] or original_state['closed_reason'] is not None):_fail()
    # 原runtime历史由已有v2许可认证；正式035包必须与原cache封存索引逐字节等价。
    from dcc_task_runtime.geometry_recovery_successor import validate as prior_validate,_packages as prior_packages
    from .geometry_runtime_binding import _rebase_package
    prior_record=_object(_read(source['job']))['runtime_continuation'];prior,_,_=prior_validate(native,prior_record)
    historical=prior_packages(_path(prior['original_plugin_root']),original);former=_path(prior['active_plugin_root'])
    if any(_rebase_package(prior.get(key),former,original)!=value for key,value in historical.items()):_fail()
    packages=_packages(original,active)
    for name in ('production_hosts.py','workbuddy_assembly.py'):
        if (_path(source['control'])/'snapshot/packages/vfx-pipeline/src/vfx_pipeline'/name).read_bytes()!=(original/'runtime/packages/vfx-pipeline/src/vfx_pipeline'/name).read_bytes():_fail()
    _request(request_record,preparation_record,source,native)
    payload={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':native.binding,'task_id':prep['task_id'],
             'source':source_record,'request':request_record,'budget_grant':budget_grant_record,
             'authority':{'authority':'current_user_instruction','instruction':instruction},
             'source_closure':_source_closure(source,details,native),**packages}
    path=native.root/_AUTH;value={'payload':payload,'signature':_sign(native,payload)}
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(native._canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
    record=file_record(path);validate(preparation_record,record,native);return record


def _effective(preparation_record,runtime_root):
    prep,native=_context(preparation_record);runtime=_path(runtime_root)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.6')/'runtime':_fail()
    record=file_record(native.root/_AUTH);payload,details=validate(preparation_record,record,native)
    if native._read().get('geometry_budget_addendum')!=payload['budget_grant']:_fail()
    packages=_packages(_path(payload['original_plugin_root']),runtime.parent)
    if any(payload.get(key)!=value for key,value in packages.items()):_fail()
    native.collector_policy();native.check();return native,payload,record,details


def resolve_worker(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[1]['active_worker']


def authorization_record(preparation_record,runtime_root):return _effective(preparation_record,runtime_root)[2]


def verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root):
    native,payload,record,_=_effective(preparation_record,runtime_root);request=_object(_read(payload['request']))
    if authority_record!=record or plan!=request['new_plan'] or request_id!=request['request_id']:_fail()
    return record


def source_record_for_job(preparation_record,plan,request_id,authority_record,runtime_root):
    record=verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root)
    return _object(_read(record))['payload']['source']


def verify_job(job,native):
    """新作业必须绑定唯一上层许可；历史核验不读取当前runtime或工具。"""
    if 'source_checkpoint' in job or job.get('revision')!=1:_fail()
    payload,details=validate(job['preparation'],job.get('runtime_continuation',{}),native)
    request=_object(_read(payload['request']))
    if (job.get('task_id')!=payload['task_id'] or job.get('operation_id')!=request['new_operation_id']
            or job.get('plan')!=request['new_plan'] or job.get('render_source')!=payload['source']
            or job.get('execution_worker')!=payload['active_worker']):_fail()
    return details
