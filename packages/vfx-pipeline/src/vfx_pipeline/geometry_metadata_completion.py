"""048只接收047已完成的几何结果；不重放阶段，不提供执行或任意历史替换接口。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os,sqlite3
from contextlib import closing
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.platform_support import ensure_private_directory,process_status
from houdini_bridge.official_karma_observation import file_record
from .geometry_registration_resume import _context
from .geometry_render_resume import _path
_SCHEMA='bridge.geometry-metadata-completion/1'
_SOURCE='bridge.geometry-metadata-completion-source/1'
_AUTH='geometry-metadata-completion-authorization.json'
_SOURCE_NAME='geometry-metadata-completion-source.json'
_DIR='metadata-048'
_EXTENSION='bridge.geometry-prelaunch-metadata-result/1'
_DOMAIN=b'bridge.geometry-metadata-completion/1\x00'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_metadata_completion.py','runtime/tools/complete_geometry_metadata.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_job','geometry_session','geometry_prelaunch_tail','geometry_runtime_binding')}
_CHANGED|={'runtime/packages/nuke-bridge/src/nuke_bridge/'+n+'.py' for n in ('task_host','operation_receipts')}
_STAGES={'reuse_seed_cold_source','text_finalize','nuke_cold','nuke_launch_intent','nuke_completed','compare','preview','local_preview'}
_CODE={'worker_module':'runtime/packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py','proof_module':'runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py','addon':'runtime/plugins/nuke/nuke_bridge_addon.py','worker_script':'runtime/tools/nuke_owned_render_worker.py'}

def _fail():raise ValueError('GEOMETRY_METADATA_COMPLETION_INVALID')
def _bytes(record):
    from nuke_bridge.task_host import _cold_bytes
    return _cold_bytes(record)
def _record(path):
    from nuke_bridge.task_host import _cold_record
    return _cold_record(path)
def _object(raw):
    def unique(items):
        result={}
        for key,value in items:
            if key in result:_fail()
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    if type(value) is not dict:_fail()
    return value
def _read(record):return _object(_bytes(record))
def _sign(native,p):return hmac.new(hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()
def _raw(path,data):
    path=_path(path);ensure_private_directory(path.parent)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return _record(path)
def _write(path,value):return _raw(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
def _expected(path,data):return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

def _packages(original,active):
    """048仅允许已审只读验证与本次接收入口，不改047正式包。"""
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.7');b,bf,brs=_package(active,'0.4.8');changed={name for name in af if name in bf and af[name]!=bf[name]}
    if ({k:v for k,v in a.items() if k!='version'}!={k:v for k,v in b.items() if k!='version'} or set(af)-set(bf)
            or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,
            'active_worker':file_record(active/'runtime/tools/complete_geometry_metadata.py'),
            'differences':[{'name':name,'before':file_record(original/name) if name in af else None,'after':file_record(active/name)} for name in sorted(changed|_ADDED)]}

def _upper(native,record,module,schema):
    value=_read(record);p=value.get('payload')
    if (set(value)!={'payload','signature'} or type(p) is not dict or p.get('schema')!=schema or p.get('native_scope')!=native.binding
            or p.get('task_id')!=native.scope['task_id'] or not hmac.compare_digest(str(value['signature']),module._sign(native,p))):_fail()
    _bytes(p['source']);return p

def _ancestry(native,source):
    """旧授权按原域认证；原044源已认证投影复用，046现时coverage不重放。"""
    from . import geometry_prelaunch_tail as v47,geometry_cold_preflight_runtime as v46,geometry_seed_cold_runtime_successor as v45,geometry_seed_cold_resume as base
    p47=_upper(native,source['original_authority'],v47,v47._SCHEMA);s47=_read(p47['source'])
    if source['original_authority']['path']!=str(native.root/v47._AUTH) or p47['source']!=source['original_source'] or p47['consumer_runtime']['package_root']!=source['formal047']:_fail()
    p46=_upper(native,s47['original_authority'],v46,v46._SCHEMA);s46=_read(p46['source']);p45=_upper(native,s46['predecessor_authorization'],v45,v45._SCHEMA)
    p44,original=base._validate_original(source['preparation'],s46['finalization_authority'],native)
    if (p45['source']!=s46['predecessor_source'] or _read(p45['source']).get('predecessor_authorization')!=s46['finalization_authority']
            or p44['source']!=s46['original_source'] or p44['request']!=s46['predecessor_effective']['request']
            or s47['job']!=source['job'] or s47['preparation']!=source['preparation']):_fail()
    request=_read(p44['request']);job=_read(source['job']);op=request['new_operation_id'];directory=native.root/'jobs'/op
    if (source['job']['path']!=str(directory/'job.json') or job.get('operation_id')!=op or job.get('preparation')!=source['preparation'] or job.get('task_id')!=native.scope['task_id']
            or job.get('plan')!=request['new_plan'] or job.get('revision')!=2 or job.get('directory')!=str(directory)
            or job.get('runtime_continuation')!=s47['original_authority'] or job.get('seed_cold_source')!=p44['source'] or job.get('execution_worker')!=p46['active_worker']):_fail()
    base._verify_finalization(source['preparation'],s46['finalization_authority'],original['nk_binding'],native=native)
    details=base._check_job(job,p46|{'request':p44['request'],'source':p44['source'],'active_worker':p46['active_worker'],'finalization_authority':s46['finalization_authority']},original)
    return p47,s47,p44,original,job,details

def _transition(source,*,historical,materialized):
    """唯一诊断索引20→23；原执行输入不被当前计数追认替换。"""
    t=source['binding_transition'];before=t['original'];after=t['after'];raw=t['after_text'].encode();value=_object(raw)
    if value.get('rebind_count')!=23 or _expected(after['path'],raw)!=after:_fail()
    prior=copy.deepcopy(value);prior['rebind_count']=20;old=(json.dumps(prior,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    if _expected(before['path'],old)!=before or t['before_text'].encode()!=old or before['path']!=after['path']:_fail()
    if materialized:
        if _bytes(t['before_snapshot'])!=old or _bytes(t['after_snapshot'])!=raw:_fail()
    if not historical and _bytes(after)!=raw:_fail()
    return before

def _mappings(source,proof,p47):
    """只重定位原047四份受签相同代码；原identity/argv字符串保持。"""
    formal=_path(source['formal047']);manifest=_read(file_record(formal/'runtime-manifest.json'));entries={item['path']:item for item in manifest['files']};audit=_read(source['cache_audit']);expected={}
    if len(source['cache_mappings'])!=4 or len(audit.get('permanent_mappings',[]))!=4 or audit.get('cache_reference_count')!=25 or audit.get('fixed_records_checked')!=4328:_fail()
    for key,relative in _CODE.items():
        original=proof['execution_code'][key];path=Path(p47['active_plugin_root'])/relative;permanent=_record(formal/relative);entry=entries.get(relative)
        if (original['path']!=str(path) or any(original[k]!=permanent[k] for k in ('bytes','sha256')) or not entry
                or entry['sha256']!=original['sha256'] or entry.get('bytes',original['bytes'])!=original['bytes']):_fail()
        expected[str(path)]={'original':original,'permanent':permanent,'relative':relative}
    actual={item['original']['path']:item for item in source['cache_mappings']}
    if actual!=expected or set(audit['unique_cache_paths'])!=set(expected):_fail()
    for item in audit['permanent_mappings']:
        x=expected.get(item.get('original'))
        if x is None or item.get('original_record')!=x['original'] or item.get('permanent_record')!=x['permanent'] or item.get('relative')!=x['relative'] or item.get('same_bytes_sha') is not True:_fail()
    return expected

def _ledger_rows(native,entries):
    """历史只固定本次两个版本的已登记行，不冻结未来无关数据库写入。"""
    rows=[];path=native.root/'artifact_ledger/artifacts.sqlite3'
    with closing(sqlite3.connect('file:'+str(_path(path))+'?mode=ro',uri=True)) as db:
        for entry in entries:
            artifact=entry['artifact_id'];version=entry['version']
            history=db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?',(artifact,version)).fetchone()
            receipt=db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',(artifact,version)).fetchone()
            if history is None or (receipt is not None)!=bool(entry.get('registry_operation_receipt')):_fail()
            payload=_object(history[0])
            if payload.get('artifact_id')!=artifact or payload.get('version')!=version or payload.get('operation_id')!=entry.get('operation_id'):_fail()
            rows.append({'artifact_id':artifact,'version':version,'history_payload':history[0],'receipt_payload':receipt[0] if receipt else None})
    return rows


def _facts(native,source,*,historical=False,materialized=True,realtime=False,_collect_rows=False,_progress=None):
    """有限完成证据全验；不实例化旧执行cap，不调用Native或阶段函数。"""
    if _collect_rows and (materialized or historical or source.get('ledger_rows')!=[]):_fail()
    if _progress is not None:_progress.count('facts')
    from nuke_bridge.task_host import _cold_proof_payload
    from dcc_task_runtime import owned_process
    required={'schema','phase','preparation','task_id','job','original_authority','original_source','formal047','diagnosis','cache_audit','metadata_stop','execution_proof','records','cache_mappings','binding_transition','native_snapshot','session_before','ledger_rows'}
    if type(source) is not dict or set(source)!=required:_fail()
    _bytes(source['diagnosis']);_bytes(source['cache_audit']);_bytes(source['metadata_stop'])
    if _progress is not None:_progress.count('ancestry')
    with _phase(_progress,'ancestry'):
        p47,s47,p44,original,job,details=_ancestry(native,source)
    with _phase(_progress,'signed_receipts'):
        proof=_cold_proof_payload(source['execution_proof'],native,observation=False);attempt=s47['cold_attempt'];nr=attempt['operation_id']
        if (source.get('schema')!=_SOURCE or source['task_id']!=native.scope['task_id'] or source['preparation']!=job['preparation'] or source['phase']!='PRIOR047_METADATA_FAILED_NATIVE_COMPLETE'
                or proof['operation_id']!=nr or proof['binding']['authority']!=source['original_authority'] or proof['binding']['main_job_record']!=source['job']
                or proof['binding']['operation_id']!=job['operation_id'] or proof['binding']['final_nk']!=original['nk_binding']['final_nk']
                or proof['owner_task_id']!=native.scope['task_id'] or proof['mode']!='execution'): _fail()
        directory=Path(job['directory']);taildir=Path(attempt['journal_directory']);render=native.root/'state/nuke_renders';owned=render/(nr+'.supervisor')
        expected_paths={'journal':taildir/'incremental-state.json','error':taildir/'error.json','controller_started':taildir/'controller-started.json','execute_owner':taildir/'execute-owner.json',
            'task':render/(nr+'.json'),'worker_result':render/(nr+'.worker-result.json'),'intent':owned/'intent.json','started':owned/'started.json','stopped':owned/'stopped.json','owned_key':owned/'receipt.key',
            'scope_state':native.state_path,'scope_journal':native.journal_path,'scope_anchor':native.anchor_path,'artifact_ledger':native.root/'artifact_ledger/artifacts.sqlite3'}
        if set(source['records'])!=set(expected_paths) or any(source['records'][name]['path']!=str(path) for name,path in expected_paths.items()):_fail()
        t=source['binding_transition'];target=directory/_DIR
        if t.get('before_snapshot',{}).get('path')!=str(target/'binding-before20.json') or t.get('after_snapshot',{}).get('path')!=str(target/'binding-after23.json'):_fail()
        for name,record in source['records'].items():
            if not historical or name!='artifact_ledger':_bytes(record)
        stop=_read(source['metadata_stop']);error=_read(source['records']['error']);journal=_read(source['records']['journal']);task=_read(source['records']['task']);worker=_read(source['records']['worker_result'])
        if (stop.get('schema')!='bridge.geometry047-metadata-stop-observation/1' or stop.get('state')!='STOPPED' or stop.get('observed_process_status')!='stopped'
                or stop.get('error')!=source['records']['error'] or stop.get('journal')!=source['records']['journal'] or stop.get('scope_tickets')!=17 or stop.get('all_native_stopped') is not True
                or stop.get('implementation')!=file_record(Path(source['formal047'])/'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_prelaunch_tail.py')
                or error.get('authority')!=source['original_authority'] or error.get('job')!=source['job'] or error.get('message')!='OFFICIAL_FILE_CHANGED'
                or stop.get('controller_started')!=source['records']['controller_started'] or stop.get('execute_owner')!=source['records']['execute_owner']):_fail()
        started_owner=_read(source['records']['controller_started'])
        if started_owner.get('process_identity')!=stop.get('process_identity') or realtime and process_status(stop['process_identity'])!='stopped':_fail()
        if (set(journal.get('stages',{}))!=_STAGES or journal.get('job')!=source['job'] or any(v.get('state')!='DONE' for v in journal['stages'].values())):_fail()
        stages=journal['stages'];cold=stages['nuke_cold']['result'];completed=stages['nuke_completed']['result'];identity=proof['identity'];owned=Path(task['supervisor_intent']['directory'])
        identity=dict(proof['identity'],cold_proof_sha256=source['execution_proof']['sha256'])
        if (cold.get('operation_id')!=nr or completed.get('task_id')!=nr or completed.get('state')!='COMPLETED' or completed.get('ledger_state')!='REGISTERED'
                or task.get('task_id')!=nr or task.get('request_id')!=attempt['request_id'] or task.get('owner_task_id')!=native.scope['task_id'] or task.get('state')!='COMPLETED' or task.get('ledger_state')!='REGISTERED'
                or task['supervisor_intent']['identity']!=identity):_fail()
        started=owned_process.read_receipt(owned,'started',identity=identity);stopped=owned_process.read_receipt(owned,'stopped',identity=identity);intent=_read(source['records']['intent'])
        if (not started or not stopped or owned_process.execution_returncode(stopped)!=0 or stopped.get('stop_reason') is not None
                or stopped.get('execution_result')!='succeeded' or stopped.get('supervisor_exit_code')!=0 or stopped.get('descendant_result_unobserved') is not False
                or intent.get('identity')!=identity or started.get('argv_sha256')!=canonical_sha256(intent.get('command')) or proof['command_sha256']!=canonical_sha256(intent.get('command'))
                or worker.get('software_api') is not False or worker.get('task_id')!=nr or worker.get('execute_calls')!=[1] or worker.get('script_opened') is not True or worker.get('node_resolved') is not True
                or (worker.get('input_readback') or {}).get('after_verified') is not True):_fail()
        command=[native.scope['hosts']['nuke']['path'],'-t',proof['execution_code']['worker_script']['path'],proof['snapshot']['path'],'Write1','1','1',proof['binding']['approved_pattern'],'[1]']
        if intent.get('command')!=command or task['supervisor_intent']['directory']!=str(owned) or task['supervisor_intent']['worker_result']!=source['records']['worker_result']['path']:_fail()
    before=_transition(source,historical=historical,materialized=materialized);mapping=_mappings(source,proof,p47);fixed=proof.get('fixed_records')
    audit=_read(source['cache_audit'])
    if audit.get('changed_records')!=[{'expected':source['binding_transition']['original'],'actual':source['binding_transition']['after']}]:_fail()
    if not isinstance(fixed,list) or len(fixed)!=4328 or len({r['path'] for r in fixed})!=4328 or sum(r==before for r in fixed)!=1:_fail()
    with _phase(_progress,'fixed_records'):
        for record in fixed:
            if record==before:continue
            if record['path'] in mapping:
                if record!=mapping[record['path']]['original']:_fail()
                _bytes(mapping[record['path']]['permanent'])
            else:_bytes(record)
    with _phase(_progress,'accounting'):
        state=native._read();usage=native.completed_snapshot()
    if (len(state['tickets'])!=17 or any(t['stopped_at'] is None for t in state['tickets']) or usage!=source['native_snapshot']
            or file_record(native.state_path)!=source['records']['scope_state'] or state['tickets'][-1]['identity']!=identity
            or state['tickets'][-1]['directory']!=str(owned)):_fail()
    with _phase(_progress,'ledger_rows'):
        ledger_rows=_ledger_rows(native,[details['artifact'],cold['artifact']])
    if _collect_rows:source['ledger_rows']=ledger_rows
    elif ledger_rows!=source['ledger_rows']:_fail()
    if stages['compare']['result'].get('state')!='PASS' or stages['compare']['result'].get('samples_compared')!=504000 or stages['compare']['result'].get('different_samples')!=0:_fail()
    for record in [*cold['files'].values(),stages['preview']['result']['preview'],stages['local_preview']['result']]:_bytes(record)
    return original,job,details,journal

def inspect_source(preparation,formal047,diagnosis,cache_audit,metadata_stop):
    """只读封存候选；before/after快照在prepare签权前单独O_EXCL落盘。"""
    from . import geometry_prelaunch_tail as old
    prep,native=_context(preparation);authority=file_record(native.root/old._AUTH);p47=_read(authority)['payload'];s47=_read(p47['source']);job=_read(s47['job']);directory=Path(job['directory']);taildir=Path(s47['cold_attempt']['journal_directory']);target=directory/_DIR;nr=s47['cold_attempt']['operation_id'];render=native.root/'state/nuke_renders';task=_read(file_record(render/(nr+'.json')));owned=Path(task['supervisor_intent']['directory']);audit=_read(cache_audit)
    if len(audit.get('changed_records',[]))!=1:_fail()
    difference=audit['changed_records'][0];before=difference['expected'];after=difference['actual'];after_raw=_bytes(after);value=_object(after_raw);prior=copy.deepcopy(value);prior['rebind_count']=20;before_raw=(json.dumps(prior,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    records={name:_record(path) for name,path in {'journal':taildir/'incremental-state.json','error':taildir/'error.json','controller_started':taildir/'controller-started.json','execute_owner':taildir/'execute-owner.json',
        'task':render/(nr+'.json'),'worker_result':Path(task['supervisor_intent']['worker_result']),'intent':owned/'intent.json','started':owned/'started.json','stopped':owned/'stopped.json','owned_key':owned/'receipt.key',
        'scope_state':native.state_path,'scope_journal':native.journal_path,'scope_anchor':native.anchor_path,'artifact_ledger':native.root/'artifact_ledger/artifacts.sqlite3'}.items()}
    mappings=[{'original':item['original_record'],'permanent':item['permanent_record'],'relative':item['relative']} for item in audit['permanent_mappings']]
    source={'schema':_SOURCE,'phase':'PRIOR047_METADATA_FAILED_NATIVE_COMPLETE','preparation':preparation,'task_id':prep['task_id'],'job':s47['job'],'original_authority':authority,'original_source':p47['source'],
            'formal047':str(_path(formal047)),'diagnosis':diagnosis,'cache_audit':cache_audit,'metadata_stop':metadata_stop,'execution_proof':task['controller_input_proof'],'records':records,'cache_mappings':mappings,
            'binding_transition':{'original':before,'after':after,'before_text':before_raw.decode(),'after_text':after_raw.decode(),'before_snapshot':_expected(target/'binding-before20.json',before_raw),'after_snapshot':_expected(target/'binding-after23.json',after_raw)},
            'native_snapshot':native.completed_snapshot(),'session_before':_read(file_record(native.root/'geometry-state.json')),'ledger_rows':[]}
    _facts(native,source,materialized=False,realtime=True,_collect_rows=True)
    if (directory/'result.json').exists() or (directory/'accepted-result.json').exists():_fail()
    return source


def create_authorization(preparation,source_record,formal047,active048,formal048):
    """仅授权此次已完成结果的元数据发布，旧许可及Native状态均不写。"""
    prep,native=_context(preparation);source=_read(source_record);original=_path(formal047);active=_path(active048);formal=_path(formal048)
    if (source_record['path']!=str(native.root/_SOURCE_NAME) or source['preparation']!=preparation or source['formal047']!=str(original)
            or active!=Path(prep['worker']).parents[2].with_name('0.4.8')):_fail()
    _facts(native,source,realtime=True)
    if _read(file_record(native.root/'geometry-state.json'))!=source['session_before']:_fail()
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.8');b,bf,indices=_package(formal,'0.4.8')
    if a!=b or af!=bf or active==formal or formal.is_relative_to(native.root):_fail()
    p={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'consumer_runtime':{'package_root':str(formal),'package_sources':indices},**packages}
    return _write(native.root/_AUTH,{'payload':p,'signature':_sign(native,p)})


def _validate048(preparation,authority,native=None,*,historical=False,_progress=None):
    """首次接收严格23；accepted历史仅认证原快照及其余原件。"""
    _,native=_context(preparation,native=native)
    if authority['path']!=str(native.root/_AUTH) or _path(authority['path']).stat().st_mode&0o077:_fail()
    v=_read(authority);p=v.get('payload')
    fields={'schema','preparation','native_scope','task_id','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(v)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation or p.get('native_scope')!=native.binding
            or p.get('task_id')!=native.scope['task_id'] or not hmac.compare_digest(str(v['signature']),_sign(native,p)) or p['source']['path']!=str(native.root/_SOURCE_NAME)):_fail()
    source=_read(p['source'])
    from .geometry_runtime_binding import _package,_rebase_package
    formal=_path(p['consumer_runtime']['package_root']);_,_,indices=_package(formal,'0.4.8');packages=_packages(_path(p['original_plugin_root']),formal)
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':indices} or any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=value for k,value in packages.items()):_fail()
    original,job,details,journal=_facts(native,source,historical=historical,_progress=_progress)
    if source['formal047']!=p['original_plugin_root'] or source['preparation']!=preparation:_fail()
    return p,source,original,job,details,journal


def _accepted(native,job,authority):
    """只有已签canonical接收回执才允许历史诊断计数推进。"""
    path=Path(job['directory'])/'accepted-result.json'
    if not path.exists():return False
    from .geometry_session import GeometrySession
    value=_read(file_record(path));p=value.get('payload');result_path=Path(job['directory'])/'result.json'
    if (set(value)!={'payload','signature'} or type(p) is not dict or not hmac.compare_digest(str(value['signature']),GeometrySession._acceptance_signature(native,p))
            or p.get('job')!=file_record(Path(job['directory'])/'job.json') or p.get('result')!=file_record(result_path)
            or p.get('prelaunch_continuation',{}).get('payload',{}).get('authority')!=authority):_fail()
    return True


def _extension(native,result,*,_metadata_context=None):
    """048新结果域不会伪造047曾完成canonical发布。"""
    value=result.get('prelaunch_continuation')
    if type(value) is not dict or set(value)!={'schema','payload','signature'} or value.get('schema') not in (_EXTENSION,_EXTENSION49):_fail()
    p=value['payload'];authority=p.get('authority');job=_read(p['job'])
    runtime_authority=p.get('runtime_authority',authority)
    if _metadata_context is None:
        package,source,original,bound,details,journal=validate(job['preparation'],runtime_authority,native,historical=_accepted(native,job,authority))
    else:
        context=_metadata_context;context.check(native=native,job=job,result=result)
        if context.data_authority!=authority or context.authority!=runtime_authority:_fail()
        source,bound,details,journal=context.source,context.job,context.details,context.journal
        package=context.runtime_payload

    expected={'authority':authority,'source':_read(authority)['payload']['source'],'job':source['job'],'prior_metadata_state':'FAILED_BEFORE_CANONICAL_PUBLISH',
              'prior_error':source['records']['error'],'journal':source['records']['journal'],'execution_proof':source['execution_proof'],
              'result_sha256':canonical_sha256({k:v for k,v in result.items() if k!='prelaunch_continuation'})}
    if value['schema']==_EXTENSION49:
        if package.get('runtime_authority')!=runtime_authority:_fail()
        expected.update(runtime_authority=runtime_authority,runtime_source=package['runtime_source'],interrupted_048_inspect=package['interrupted_inspect'])
        signature=_result49_sign(native,{'schema':_EXTENSION49,**p})
    else:signature=_sign(native,{'schema':_EXTENSION,**p})
    if p!=expected or not hmac.compare_digest(str(value['signature']),signature) or bound!=job:_fail()

    return source,job,details,journal


def verify_job_details(native,job,result,*,_metadata_context=None):
    source,bound,details,_=_extension(native,result,_metadata_context=_metadata_context)
    if bound!=job:_fail()
    return details


def verify_result_extension(native,job,result,*,_metadata_context=None):
    source,bound,_,_=_extension(native,result,_metadata_context=_metadata_context)
    if bound!=job:_fail()
    return Path(source['records']['journal']['path'])


def _candidate(preparation,authority,*,_metadata_context=None):
    """从固定八DONE直接构造结果；不使用JobJournal.action。"""
    if _metadata_context is None:
        prep,native=_context(preparation);package,source,original,job,d,journal=validate(preparation,authority,native)
    else:
        context=_metadata_context;context.check();prep=_read(preparation);native=context.native
        if context.preparation!=preparation or context.authority!=authority:_fail()
        package,source,original,job,d,journal=context.runtime_payload,context.source,context.original,context.job,context.details,context.journal

    stages=journal['stages'];nk=copy.deepcopy(stages['text_finalize']['result']);nuke=copy.deepcopy(stages['nuke_cold']['result']);preview=copy.deepcopy(stages['preview']['result']);local=copy.deepcopy(stages['local_preview']['result'])
    result={'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':job['task_id'],'operation_id':job['operation_id'],'revision':2,'plan':job['plan'],'preparation':preparation,'seed_cold_source':job['seed_cold_source'],
        'parent_operation_id':d['operation_id'],'parent_failure_operation_id':d['failure_operation_id'],'control':d['control'],'saved':d['save'],'warm_geometry':d['warm_geometry'],'geometry':d['cold_geometry'],'cold_reopen':d['cold_reopen'],
        'evaluation':d['evaluate'],'graph_source':d['graph_source'],'artifact':d['artifact'],'source_record':d['input_source'],'nk_finalization':nk,'nuke_save_status':'FAILED','delivery_method':'controller_text_finalization+native_cold_open_render',
        'nuke':nuke,'comparison':copy.deepcopy(stages['compare']['result']),'preview':preview,'scope':(native.completed_snapshot() if _metadata_context is None else copy.deepcopy(_metadata_context.usage)),'model_route':prep['model_route'],'human_visual_acceptance':'PENDING',
        'files':{'hip':d['files']['hip'],'main':d['files']['main'],'nk':nk['file'],'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}
    data_authority=package.get('data_authority',authority)
    p={'authority':data_authority,'source':_read(data_authority)['payload']['source'],'job':source['job'],'prior_metadata_state':'FAILED_BEFORE_CANONICAL_PUBLISH','prior_error':source['records']['error'],'journal':source['records']['journal'],'execution_proof':source['execution_proof'],'result_sha256':canonical_sha256(result)}
    if 'runtime_authority' in package:
        p.update(runtime_authority=package['runtime_authority'],runtime_source=package['runtime_source'],interrupted_048_inspect=package['interrupted_inspect'])
        result['prelaunch_continuation']={'schema':_EXTENSION49,'payload':p,'signature':_result49_sign(native,{'schema':_EXTENSION49,**p})}
    else:result['prelaunch_continuation']={'schema':_EXTENSION,'payload':p,'signature':_sign(native,{'schema':_EXTENSION,**p})}
    if _metadata_context is not None:_metadata_context.bind_result(result)
    return job,result



def inspect_completed_result(preparation,authority,*,progress=None):
    """049只在本次事务完整认证一次；原048无共享对象入口仍完整认证。"""
    from .geometry_job import validate_result
    from .geometry_metadata_runtime_successor import _AUTH as runtime_auth
    if Path(authority['path']).name==runtime_auth:
        with metadata_validation(preparation,authority,progress=progress) as context:
            job,result=_candidate(preparation,authority,_metadata_context=context)
            validation=validate_result(preparation,job,result,_metadata_context=context)
            if validation.get('state')!='VERIFIED':_fail()
            return {'state':'VERIFIED','result':result,'validation':validation,'counts':dict(context.progress.counts)}
    job,result=_candidate(preparation,authority);validation=validate_result(preparation,job,result)
    if validation.get('state')!='VERIFIED':_fail()
    return {'state':'VERIFIED','result':result,'validation':validation}


def publish(preparation,authority,*,progress=None):
    """只发布原canonical，首次Session接收留给正式continue_task入口。"""
    from dcc_task_runtime.execution_lock import execution_lock
    from .geometry_metadata_runtime_successor import _AUTH as runtime_auth
    if Path(authority['path']).name==runtime_auth:return _publish49(preparation,authority,progress=progress)
    _,native=_context(preparation)
    with execution_lock(native.root,'geometry-session'):
        source=_read(_read(authority)['payload']['source']);job=_read(source['job']);path=Path(job['directory'])/'result.json'
        if path.exists():
            result=_read(file_record(path));_extension(native,result)
            return {'state':'ORIGINAL_CANONICAL_RETURNED','operation_id':job['operation_id'],'result':file_record(path),'native_dispatch_attempted':False,'accepted_sealed':False}
        inspected=inspect_completed_result(preparation,authority);record=_write(path,inspected['result'])
        return {'state':'METADATA_CANONICAL_PUBLISHED','operation_id':job['operation_id'],'result':record,'native_dispatch_attempted':False,'accepted_sealed':False}


# 049同请求事务只共享本次完整认证结果；原048默认函数仍保留完整路径。
_REQUEST_SEAL=object()
_EXTENSION49='bridge.geometry-prelaunch-metadata-result/2'
_RESULT49_DOMAIN=b'bridge.geometry-prelaunch-metadata-result/2\x00'

class _Progress:
    """阶段日志只含计时、计数和错误类型，不写历史正文或凭据。"""
    def __init__(self,callback=None):
        import time
        self.callback=callback;self.wall=time.monotonic();self.cpu=time.process_time();self.counts={}
    def emit(self,event,phase,**values):
        import time
        value={'event':event,'phase':phase,'wall_seconds':time.monotonic()-self.wall,'cpu_seconds':time.process_time()-self.cpu,'counts':dict(self.counts),**values}
        if self.callback is not None:self.callback(value)
    def count(self,name):self.counts[name]=self.counts.get(name,0)+1
    def phase(self,name):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            import time
            wall=time.monotonic();cpu=time.process_time();self.emit('start',name)
            try:yield
            except BaseException as error:
                self.emit('end',name,status='ERROR',error_type=type(error).__name__,stage_wall_seconds=time.monotonic()-wall,stage_cpu_seconds=time.process_time()-cpu);raise
            else:self.emit('end',name,status='OK',stage_wall_seconds=time.monotonic()-wall,stage_cpu_seconds=time.process_time()-cpu)
        return opened()


def _stamp(path):
    value=_path(path).stat()
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)

class _StartEvidence:
    """入口发现读取立即留首封身份；后续不能换一份新baseline掩盖中途变动。"""
    def __init__(self):self.records={};self.stamps={}
    def add(self,record):
        path=record['path'];before=_stamp(path);raw=_bytes(record);after=_stamp(path)
        if before!=after:_fail()
        if path in self.records:
            if self.records[path]!=record or self.stamps[path]!=before:_fail()
        else:self.records[path]=copy.deepcopy(record);self.stamps[path]=before
        return raw
    def read(self,record):return _object(self.add(record))
    def close_check(self):
        for path,record in self.records.items():
            before=_stamp(path);_bytes(record)
            if before!=self.stamps[path] or _stamp(path)!=before:_fail()


def _session_identity(native,source,job):
    """只固定本操作的计划与请求映射，允许正式接收写入自身终态。"""
    state=_read(file_record(native.root/'geometry-state.json'));op=job['operation_id'];pid=job['plan']['plan_id'];entry=state.get('jobs',{}).get(op,{})
    expected={'operation_id':op,'revision':job['revision'],'plan_id':pid,'job_file':source['job'],'directory':job['directory']}
    requests={key:value for key,value in state.get('execution_requests',{}).items() if value.get('operation_id')==op}
    original={key:value for key,value in source['session_before']['execution_requests'].items() if value.get('operation_id')==op}
    if (any(entry.get(key)!=value for key,value in expected.items()) or state.get('plans',{}).get(pid)!=job['plan'] or state.get('plan_operations',{}).get(pid)!=op or requests!=original):_fail()
    return {'job':expected,'plan':job['plan'],'requests':requests,'plan_operation':op}


_READER_VERSIONS=('0.4.9','0.4.10','0.4.11','0.4.12','0.4.13','0.4.14',
                  '0.4.15','0.4.16','0.4.17','0.4.18','0.4.19','0.4.20',
                  '0.4.21','0.4.22','0.4.23')
_READER_MODULES=(('geometry_metadata_completion','_entry_evidence'),
                 ('geometry_metadata_runtime_successor','resolve'),
                 ('geometry_job','validate_result'),('geometry_session','GeometrySession.query'),
                 ('geometry_seed_cold_resume','_validate_original'),
                 ('geometry_registration_resume','_context'),
                 ('geometry_runtime_binding','_package'),
                 ('geometry_prelaunch_tail','verify_result_extension'))


def _reader_evidence(evidence):
    """当前读取器单独验源；旧授权仍只认证原生产包及原结果。"""
    import importlib
    from .geometry_runtime_binding import _package, _path as plain
    source=plain(__file__);runtime=source.parents[4];package=runtime.parent
    if runtime.name!='runtime' or source!=runtime/'packages/vfx-pipeline/src/vfx_pipeline/geometry_metadata_completion.py':_fail()
    plugin=evidence.read(_record(package/'plugin.json'))
    if plugin.get('name')!='bridge-vfx' or plugin.get('version') not in _READER_VERSIONS:_fail()
    _,entries,records=_package(package,plugin['version'])
    if len(entries)>1024:_fail()
    for record in records:evidence.add(record)
    for relative,entry in entries.items():
        path=plain(package/relative)
        if not path.is_relative_to(package):_fail()
        evidence.add({'path':str(path),'bytes':entry['bytes'],'sha256':entry['sha256']})
    for name,function in _READER_MODULES:
        module_name='vfx_pipeline.'+name;module=importlib.import_module(module_name)
        path=package/('runtime/packages/vfx-pipeline/src/vfx_pipeline/'+name+'.py')
        implementation=module
        for part in function.split('.'):implementation=getattr(implementation,part,None)
        code=getattr(implementation,'__code__',None);spec=getattr(module,'__spec__',None)
        if (module.__name__!=module_name or not getattr(module,'__file__',None)
                or plain(module.__file__)!=path or spec is None or not spec.origin
                or plain(spec.origin)!=path or code is None or plain(code.co_filename)!=path
                or str(path) not in evidence.records):_fail()


def _entry_evidence(preparation,authority,progress,*,result_record=None):
    """只做有界入口发现；完整认证前先固定所有将复用的原件与会计字节。"""
    from .geometry_runtime_binding import _path as plain
    from . import geometry_metadata_runtime_successor as successor
    evidence=_StartEvidence()
    if result_record is not None:evidence.add(result_record)
    prep=evidence.read(preparation);root=plain(Path(preparation['path']).parent)
    if prep.get('schema')!='bridge.geometry-creative-preparation/1' or prep['scope']['path']!=str(root/'scope.json'):_fail()
    scope_record=_record(root/'scope.json')
    if scope_record['sha256']!=prep['scope']['sha256']:_fail()
    scope=evidence.read(scope_record)
    if scope.get('output_root')!=str(root) or scope.get('task_id')!=prep.get('task_id'):_fail()
    envelope=evidence.read(authority);runtime49=Path(authority['path']).name==successor._AUTH
    if runtime49:
        if authority['path']!=str(root/successor._AUTH):_fail()
        runtime_source=evidence.read(envelope['payload']['source']);data_authority=runtime_source['data_authority']
        for name in ('interrupted_inspect','formal048_manifest','scope_state','scope_journal','scope_anchor','job','execution_proof'):evidence.add(runtime_source[name])
    else:
        if authority['path']!=str(root/_AUTH):_fail()
        runtime_source=None;data_authority=authority
    data_envelope=evidence.read(data_authority);data_source_record=data_envelope['payload']['source'];source=evidence.read(data_source_record);proof=evidence.read(source['execution_proof'])['payload'];job=evidence.read(source['job'])
    accepted_path=Path(job['directory'])/'accepted-result.json';canonical_path=Path(job['directory'])/'result.json';historical=accepted_path.exists()
    if canonical_path.exists():evidence.add(_record(canonical_path))
    if historical:evidence.add(_record(accepted_path))
    key_path=plain(scope['accounting']['key_path'])
    if key_path!=root/'.native-control/key':_fail()
    evidence.add(_record(key_path))
    if hashlib.sha256(_bytes(_record(key_path))).hexdigest()!=scope['accounting']['key_sha256']:_fail()
    mapping={item['original']['path']:item['permanent'] for item in source['cache_mappings']};before=source['binding_transition']['original'];records=proof['fixed_records']
    if not isinstance(records,list) or len(records)!=4328:_fail()
    for record in records:
        if record==before:continue
        evidence.add(mapping.get(record['path'],record))
    for name,record in source['records'].items():
        if historical and name=='artifact_ledger':continue
        evidence.add(record)
    for name in ('diagnosis','cache_audit','metadata_stop'):evidence.add(source[name])
    transition=source['binding_transition']
    for name in ('before_snapshot','after_snapshot'):evidence.add(transition[name])
    if not historical:evidence.add(transition['after'])
    roots={Path(data_envelope['payload']['consumer_runtime']['package_root'])}
    if runtime49:roots|={Path(envelope['payload']['active_plugin_root']),Path(envelope['payload']['consumer_runtime']['package_root'])}
    else:roots.add(Path(data_envelope['payload']['active_plugin_root']))
    for package in roots:
        manifest=evidence.read(_record(package/'runtime-manifest.json'))
        if len(manifest.get('files',[]))>1024:_fail()
        evidence.add(_record(package/'runtime-manifest.json'))
        for item in manifest['files']:
            path=plain(package/item['path'])
            if not path.is_relative_to(package):_fail()
            evidence.add({'path':str(path),'bytes':item.get('bytes',path.stat().st_size),'sha256':item['sha256']})
    if runtime49:
        _reader_evidence(evidence)
    progress.emit('sealed','start_evidence',records=len(evidence.records),mode='history' if historical else 'first')
    return evidence,prep,source,job,data_authority,data_source_record,historical,runtime49

class _MetadataValidation:
    """内部创建的单请求完成证据；模式、身份和候选摘要固定，退出即失效。"""
    def __init__(self,token,preparation,authority,*,result=None,result_record=None,progress=None):
        if token is not _REQUEST_SEAL:_fail()
        self._token=token;self._active=True;self._ready=False;self.preparation=copy.deepcopy(preparation);self.authority=copy.deepcopy(authority);self.progress=_Progress(progress);self._result_digest=None
        try:
            with self.phase('start_evidence'):
                (self.evidence,prep,source,job,self.data_authority,self.data_source_record,self.historical,self.runtime49)=_entry_evidence(preparation,authority,self.progress,result_record=result_record)
            with self.phase('context'):
                self.progress.count('metadata_context_builds');_,self.native=_context(preparation)
                if self.native.binding!=prep['scope'] or self.native.root!=Path(preparation['path']).parent:_fail()
                if _accepted(self.native,job,self.data_authority)!=self.historical:_fail()
            with self.phase('complete_facts'):
                p,self.source,self.original,self.job,self.details,self.journal=validate(preparation,authority,self.native,historical=self.historical,_progress=self.progress)
                if self.source!=source or self.job!=job:_fail()
                self.runtime_payload=p;self.usage=copy.deepcopy(self.source['native_snapshot']);self.session_identity=_session_identity(self.native,self.source,self.job)
            self._identity=canonical_sha256({'scope':self.native.binding,'scope_payload':self.native.scope,'preparation':self.preparation,'authority':self.authority,'data_authority':self.data_authority,'source':self.data_source_record,'job':self.source['job'],'proof':self.source['execution_proof'],'historical':self.historical})
            self._facts_digest=canonical_sha256({'source':self.source,'job':self.job,'original':self.original,'details':self.details,'journal':self.journal,'usage':self.usage,'runtime':self.runtime_payload})
            self._ready=True
            if result is not None:self.bind_result(result)
            self.check()
        except BaseException:self._active=False;raise
    def _valid(self):
        if self._token is not _REQUEST_SEAL or not self._active:_fail()
    def phase(self,name):self._valid();return self.progress.phase(name)
    def check(self,*,job=None,result=None,native=None):
        self._valid()
        if not self._ready:return
        current=canonical_sha256({'scope':self.native.binding,'scope_payload':self.native.scope,'preparation':self.preparation,'authority':self.authority,'data_authority':self.data_authority,'source':self.data_source_record,'job':self.source['job'],'proof':self.source['execution_proof'],'historical':self.historical})
        if canonical_sha256({'source':self.source,'job':self.job,'original':self.original,'details':self.details,'journal':self.journal,'usage':self.usage,'runtime':self.runtime_payload})!=self._facts_digest:_fail()
        if current!=self._identity or native is not None and native is not self.native or job is not None and job!=self.job:_fail()
        if result is not None:
            digest=canonical_sha256(result)
            if self._result_digest is None or digest!=self._result_digest:_fail()
    def bind_result(self,result):
        self._valid();digest=canonical_sha256(result)
        if self._result_digest not in (None,digest):_fail()
        self._result_digest=digest
    def finish(self):
        self.check()
        with self.phase('closing_seal'):
            self.evidence.close_check();_transition(self.source,historical=self.historical,materialized=True)
            if _ledger_rows(self.native,[self.details['artifact'],self.journal['stages']['nuke_cold']['result']['artifact']])!=self.source['ledger_rows'] or _session_identity(self.native,self.source,self.job)!=self.session_identity:_fail()
    def close(self):self._active=False;self._ready=False;self._token=None


def metadata_validation(preparation,authority,*,result=None,result_record=None,progress=None):
    """一次请求的入口/退出边界；异常也销毁对象，不建立跨请求缓存。"""
    from contextlib import contextmanager
    @contextmanager
    def opened():
        context=_MetadataValidation(_REQUEST_SEAL,preparation,authority,result=result,result_record=result_record,progress=progress)
        try:yield context;context.finish()
        finally:context.close()
    return opened()


def _phase(progress,name):
    from contextlib import nullcontext
    return nullcontext() if progress is None else progress.phase(name)

def _result49_sign(native,p):
    return hmac.new(hmac.new(native._key(),_RESULT49_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()

def validate(preparation,authority,native=None,*,historical=False,_progress=None):
    """049独立运行时后继；048数据授权与正式048代码仍单独认证。"""
    from . import geometry_metadata_runtime_successor as successor
    if Path(authority['path']).name!=successor._AUTH:return _validate048(preparation,authority,native,historical=historical,_progress=_progress)
    _,native=_context(preparation,native=native)
    with _phase(_progress,'runtime_code'):
        runtime,source49=successor.resolve(preparation,authority,native)
    p,source,original,job,details,journal=_validate048(preparation,source49['data_authority'],native,historical=historical,_progress=_progress)
    effective=copy.deepcopy(p);effective.update(data_authority=source49['data_authority'],runtime_authority=authority,runtime_source=runtime['source'],interrupted_inspect=source49['interrupted_inspect'],active_worker=runtime['active_worker'],consumer_runtime=runtime['consumer_runtime'])
    return effective,source,original,job,details,journal

def checked_context(context,*,preparation=None,job=None,result=None,native=None):
    """只接内部同请求对象，不把外部认证摘要当作可复用事实。"""
    if type(context) is not _MetadataValidation: _fail()
    context.check(job=job,result=result,native=native)
    if preparation is not None and context.preparation!=preparation:_fail()
    return context


def _publish49(preparation,authority,*,progress=None):
    """049外部发布请求新建一次事务，末封通过后才写此前不存在的canonical。"""
    from dcc_task_runtime.execution_lock import execution_lock
    from .geometry_job import validate_result
    root=_path(Path(preparation['path']).parent)
    with execution_lock(root,'geometry-session'):
        with metadata_validation(preparation,authority,progress=progress) as context:
            path=Path(context.job['directory'])/'result.json'
            if path.exists():
                record=file_record(path);result=_read(record);context.bind_result(result);_extension(context.native,result,_metadata_context=context);context.finish()
                return {'state':'ORIGINAL_CANONICAL_RETURNED','operation_id':context.job['operation_id'],'result':record,'native_dispatch_attempted':False,'accepted_sealed':False}
            job,result=_candidate(preparation,authority,_metadata_context=context);validation=validate_result(preparation,job,result,_metadata_context=context)
            if validation.get('state')!='VERIFIED':_fail()
            context.finish();record=_write(path,result)
            return {'state':'METADATA_CANONICAL_PUBLISHED','operation_id':job['operation_id'],'result':record,'native_dispatch_attempted':False,'accepted_sealed':False,'counts':dict(context.progress.counts)}
