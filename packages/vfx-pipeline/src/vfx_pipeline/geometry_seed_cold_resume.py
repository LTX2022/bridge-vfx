"""R2已登记图的最后一票冷消费；文本定稿不冒充Nuke原生保存。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os
from dataclasses import dataclass
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime import geometry_seed_cold_recovery as low
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from .geometry_render_resume import _path,_read,_object,_load,_source_closure
from .geometry_registration_resume import _context
_SCHEMA='bridge.geometry-seed-cold-resume-authorization/1';_SOURCE='bridge.geometry-seed-cold-resume-source/1'
_AUTH='geometry-seed-cold-resume-authorization.json';_DOMAIN=b'bridge.geometry-seed-cold-resume/1\x00';_TOKEN=object()
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_seed_cold_resume.py','runtime/packages/dcc-task-runtime/src/dcc_task_runtime/geometry_seed_cold_recovery.py','runtime/tools/resume_geometry_seed_cold.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_job','geometry_session','geometry_runtime_binding','workbuddy_assembly')}
_CHANGED|={'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/'+n+'.py' for n in ('native_scope','geometry_recovery','geometry_budget_addendum','geometry_nuke_recovery','geometry_nuke_save_recovery')}
_CHANGED|={'runtime/packages/nuke-bridge/src/nuke_bridge/'+n+'.py' for n in ('task_host','owned_render_worker','operation_receipts')}
_CHANGED.add('runtime/packages/houdini-bridge/src/houdini_bridge/controlled_output.py')

def _fail():raise ValueError('GEOMETRY_SEED_COLD_RESUME_INVALID')
def _sign(native,p):return hmac.new(hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()

def _packages(original,active):
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.2');b,bf,brs=_package(active,'0.4.4');changed={n for n in af if n in bf and af[n]!=bf[n]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes() or {k:v for k,v in a.items() if k!='version'}!={k:v for k,v in b.items() if k!='version'} or set(af)-set(bf) or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),'differences':[{'name':n,'before':file_record(original/n) if n in af else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}

def _records(source,native):
    fixed=copy.deepcopy(source);fixed['nk_binding'].pop('final_nk',None);fixed['producer'].pop('accounting_prefix',None);fixed['producer'].pop('accounting_envelope',None)
    return _source_closure(fixed,{},native)

def inspect_source(preparation,failed_job,budget_authority,formal042):
    """新计划登记前完整认证042失败前身与真实main2；随后封存固定原件而非重放旧session语义。"""
    prep,native=_context(preparation);permit,_,closed=low.validate(native,budget_authority);budget_source=_object(_read(permit['source']));job=_object(_read(budget_source['job']))
    if budget_source['job']!=file_record(_path(failed_job)) or budget_source['preparation']!=preparation or native._read()!=closed:_fail()
    from .geometry_nuke_save_runtime_successor import validate as previous_validate,_packages as previous_packages
    from .geometry_runtime_binding import _rebase_package
    effective,details=previous_validate(preparation,job['runtime_continuation'],native);proof=_object(_read(job['runtime_continuation']))['payload'];formal=_path(formal042)
    packages=previous_packages(_path(proof['original_plugin_root']),formal)
    if any(_rebase_package(proof[k],_path(proof['active_plugin_root']),formal)!=v for k,v in packages.items()) or effective['consumer_runtime']['package_root']!=str(formal):_fail()
    from nuke_bridge.task_host import input_artifact_registry
    registry=input_artifact_registry(_object(_read(budget_source['input_source'])),scope=native,task_id=prep['task_id'],observe_completed=True)
    if registry.verify_operation_receipt(details['artifact']['registry_operation_receipt'])!=details['artifact']['registry_operation_receipt'] or registry.lookup('geometry_main')!=details['artifact'] or not registry.verify('geometry_main').get('usable'):_fail()
    if native._read()!=closed:_fail()
    source={'schema':_SOURCE,'preparation':preparation,'task_id':prep['task_id'],'failure_job':budget_source['job'],'previous_runtime_authority':job['runtime_continuation'],'budget_authority':budget_authority,'budget_source':permit['source'],'producer':details,'input_source':budget_source['input_source'],'nk_binding':budget_source['nk_binding']}
    certificate={'schema':'bridge.geometry-seed-cold-source-certificate/1','source_sha256':canonical_sha256(source),'formal042':file_record(formal/'runtime-manifest.json')}
    key=hmac.new(native._key(),b'bridge.geometry-seed-cold-source-certificate/1\x00',hashlib.sha256).digest()
    source['origin_certificate']={'payload':certificate,'signature':hmac.new(key,native._canonical(certificate),hashlib.sha256).hexdigest()}
    return source

def _producer_details(source):
    """从已认证原登记记录补齐消费文件投影，不改写封存的生产者事实。"""
    details=copy.deepcopy(source['producer'])
    registration=_object(_read(details['original_registration_source']))
    files=registration['files'];selected={key:copy.deepcopy(files[key]) for key in ('hip','main')}
    project=_path(details['project']);snapshot=details['artifact']['payload']['completion_snapshot']['1']
    if (details['source_record']!=source['input_source'] or details['control']!=str(project/'control')
            or selected['hip']!=file_record(_path(details['save']['path'])) or selected['hip']['sha256']!=details['save']['sha256']
            or selected['main']!=file_record(project/'saves/main.0001.exr')
            or any(selected['main'][key]!=snapshot[key] for key in ('path','bytes','sha256'))
            or 'files' in details and any(details['files'].get(key)!=record for key,record in selected.items())):_fail()
    details['files']=selected
    return details

def _light_source(source,native):
    fields={'schema','preparation','task_id','failure_job','previous_runtime_authority','budget_authority','budget_source','producer','input_source','nk_binding','origin_certificate'}
    if type(source) is not dict or set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id']:_fail()
    certified=copy.deepcopy(source);certificate=certified.pop('origin_certificate');body=certificate.get('payload')
    key=hmac.new(native._key(),b'bridge.geometry-seed-cold-source-certificate/1\x00',hashlib.sha256).digest()
    if (set(certificate)!={'payload','signature'} or type(body) is not dict or body.get('schema')!='bridge.geometry-seed-cold-source-certificate/1'
            or body.get('source_sha256')!=canonical_sha256(certified) or not hmac.compare_digest(str(certificate['signature']),hmac.new(key,native._canonical(body),hashlib.sha256).hexdigest())):_fail()
    _read(body['formal042'])
    p,_,closed=low.validate(native,source['budget_authority']);s=_object(_read(p['source']))
    if p['source']!=source['budget_source'] or s['job']!=source['failure_job'] or s['runtime_authority']!=source['previous_runtime_authority'] or s['input_source']!=source['input_source'] or s['nk_binding']!=source['nk_binding'] or source['preparation']!=s['preparation']:_fail()
    # 原042只作为已认证失败来源，历史验原HMAC/文件，不再调用其旧session集合门。
    low._upper(native,source['previous_runtime_authority'],b'bridge.geometry-nuke-save-runtime-successor/1\x00','bridge.geometry-nuke-save-runtime-successor/1')
    _producer_details(source)
    return p,s,closed

def _request(record,preparation,source,native):
    r=_object(_read(record));job=_object(_read(source['failure_job']));plan=copy.deepcopy(job['plan']);plan['plan_id']+='_seed_cold_resume01';plan['operator_repair']={'schema':'bridge.geometry-seed-cold-resume/1','failed_operation_id':job['operation_id'],'authorization_path':str(native.root/_AUTH)};plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'});rid='operator_seed_cold_resume01_'+job['operation_id'];op='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
    if (record['path']!=str(native.root/'geometry-seed-cold-resume-request.json') or set(r)!={'schema','preparation','task_id','failed_job','source','new_plan','request_id','new_operation_id'} or r.get('schema')!='bridge.geometry-seed-cold-request/1' or r.get('preparation')!=preparation or r.get('task_id')!=native.scope['task_id'] or r.get('failed_job')!=source['failure_job'] or r.get('source',{}).get('path')!=str(native.root/'geometry-seed-cold-resume-source.json') or _object(_read(r['source']))!=source or r.get('new_plan')!=plan or r.get('request_id')!=rid or r.get('new_operation_id')!=op):_fail()
    return r

def validate(preparation,authority,native=None):
    """原044授权保持原合同；只对精确045后继路径使用执行代码迁移证明。"""
    if isinstance(authority,dict) and Path(authority.get('path','')).name=='geometry-prelaunch-tail-authorization.json':
        from .geometry_prelaunch_tail import validate as tail_validate
        return tail_validate(preparation,authority,native)
    if isinstance(authority,dict) and Path(authority.get('path','')).name=='geometry-cold-preflight-runtime-authorization.json':
        from .geometry_cold_preflight_runtime import validate as preflight_validate
        return preflight_validate(preparation,authority,native)
    if isinstance(authority,dict) and Path(authority.get('path','')).name=='geometry-seed-cold-runtime-successor-authorization.json':
        from .geometry_seed_cold_runtime_successor import validate as successor_validate
        return successor_validate(preparation,authority,native)
    return _validate_original(preparation,authority,native)

def _active_authority(native):
    from .geometry_prelaunch_tail import _AUTH as tail_auth
    if (native.root/tail_auth).exists():return file_record(native.root/tail_auth)
    from .geometry_cold_preflight_runtime import _AUTH as successor_auth
    # 045独立冷消费只承认新后继；原044记录由新证明精确引用。
    return file_record(native.root/successor_auth)

def _validate_original(preparation,authority,native=None):
    prep,native=_context(preparation,native=native)
    if authority.get('path')!=str(native.root/_AUTH) or _path(authority['path']).stat().st_mode&0o077:_fail()
    v=_object(_read(authority));p=v.get('payload');fields={'schema','preparation','native_scope','task_id','source','request','readset','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if set(v)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(v['signature']),_sign(native,p)) or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation or p.get('native_scope')!=native.binding or p.get('task_id')!=prep['task_id'] or p['source'].get('path')!=str(native.root/'geometry-seed-cold-resume-source.json'):_fail()
    source=_object(_read(p['source']));_light_source(source,native)
    if p['readset']!=_records(source,native):_fail()
    for record in p['readset']:_read(record)
    _request(p['request'],preparation,source,native)
    from .geometry_runtime_binding import _rebase_package,_package
    formal=_path(p['consumer_runtime']['package_root']);_,_,sources=_package(formal,'0.4.4')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':sources}:_fail()
    historical=_packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=v for k,v in historical.items()):_fail()
    return p,source

def create_authorization(preparation,source_record,request_record,formal042,active044,formal044):
    prep,native=_context(preparation);source=_object(_read(source_record));_light_source(source,native);_request(request_record,preparation,source,native)
    original,active,formal=_path(formal042),_path(active044),_path(formal044)
    if active!=Path(prep['worker']).parents[2].with_name('0.4.4'):_fail()
    if source['origin_certificate']['payload']['formal042']!=file_record(original/'runtime-manifest.json'):_fail()
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.4');b,bf,sources=_package(formal,'0.4.4')
    if a!=b or af!=bf or formal==active or formal.is_relative_to(native.root):_fail()
    # source必须来自刚完成完整预检的同一正式042前身；签名固定封存内容和readset。
    if source['producer']['source_record']!=source['input_source']:_fail()
    p={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'request':request_record,'readset':_records(source,native),'consumer_runtime':{'package_root':str(formal),'package_sources':sources},**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(native._canonical({'payload':p,'signature':_sign(native,p)})+b'\n');f.flush();os.fsync(f.fileno())
    return file_record(path)

def reuse_partial_source(preparation,failed_job,budget_authority,formal042,request_record):
    """中断于高层初签前时复用原完整验源证书；不重放HOM或写入旧来源。"""
    prep,native=_context(preparation);record=file_record(native.root/'geometry-seed-cold-resume-source.json');source=_object(_read(record))
    _,_,closed=_light_source(source,native)
    if (source['preparation']!=preparation or source['failure_job']!=file_record(_path(failed_job))
            or source['budget_authority']!=budget_authority
            or source['origin_certificate']['payload']['formal042']!=file_record(_path(formal042)/'runtime-manifest.json')):_fail()
    request=_request(request_record,preparation,source,native)
    forbidden=[native.root/_AUTH,native.root/'geometry-seed-cold-finalization.json',native.root/'geometry-seed-cold-resume-dispatch.json',
               native.root/'jobs'/request['new_operation_id'],_path(source['nk_binding']['final_nk']['path']),_path(source['nk_binding']['output_pattern']%1)]
    if any(path.exists() or path.is_symlink() for path in forbidden):_fail()
    _records(source,native)
    if native._read()!=closed:_fail()
    return record

def _effective(preparation,runtime,authority):
    if Path(runtime).parent.name=='0.4.6':
        from .geometry_cold_preflight_runtime import effective
        return effective(preparation,runtime,authority)
    if Path(runtime).parent.name=='0.4.5':
        from .geometry_seed_cold_runtime_successor import effective
        return effective(preparation,runtime,authority)
    prep,native=_context(preparation);runtime=_path(runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.4')/'runtime':_fail()
    p,source=validate(preparation,authority,native);packages=_packages(_path(p['original_plugin_root']),runtime.parent)
    if any(p[k]!=v for k,v in packages.items()):_fail()
    native.check();return p,source

@dataclass(frozen=True)
class _Dispatch:
    token:object;preparation:dict;worker:dict;authority:dict;source:dict;payload:dict;details:dict

def resolve_dispatch(preparation,plan,request_id,authority,runtime):
    if type(authority) is not dict:_fail()
    p,s=_effective(preparation,runtime,authority);r=_object(_read(p['request']))
    if plan!=r['new_plan'] or request_id!=r['request_id']:_fail()
    return _Dispatch(_TOKEN,preparation,p['active_worker'],authority,p['source'],p,_producer_details(s))

def dispatch_worker(preparation,dispatch):
    if type(dispatch) is not _Dispatch or dispatch.token is not _TOKEN or dispatch.preparation!=preparation:_fail()
    _read(dispatch.worker);_read(dispatch.authority);return dispatch.worker

def resolve_runtime(preparation,runtime):
    _,native=_context(preparation);authority=(_active_authority(native) if Path(runtime).parent.name in ('0.4.5','0.4.6') else file_record(native.root/_AUTH));p,_=_effective(preparation,runtime,authority);return p['active_worker'],authority

def _check_job(job,p,s):
    r=_object(_read(p['request']))
    if job.get('seed_cold_source')!=p['source'] or job.get('plan')!=r['new_plan'] or job.get('operation_id')!=r['new_operation_id'] or job.get('task_id')!=p['task_id'] or job.get('revision')!=2 or job.get('execution_worker')!=p['active_worker'] or any(k in job for k in ('nuke_save_source','registration_source','nuke_source','render_source','source_checkpoint')):_fail()
    return {**_producer_details(s),'preparation_record':job['preparation'],'authority_record':p.get('finalization_authority',job['runtime_continuation']),'nk_binding':s['nk_binding'],'failure_operation_id':_object(_read(s['failure_job']))['operation_id'],'input_source':s['input_source'],'budget_authority':s['budget_authority']}

def verify_job(job,native,*,for_execution=False,runtime_root=None):
    authority=job.get('runtime_continuation',{});p,s=(_effective(job['preparation'],runtime_root,authority) if for_execution else validate(job['preparation'],authority,native))
    return _check_job(job,p,s)

def _verify_finalization(preparation,authority,binding,*,native=None):
    _,native=_context(preparation,native=native);receipt_path=native.root/'geometry-seed-cold-finalization.json'
    result={'method':'controller_text_finalization','native_save_performed':False,'seed':binding['seed'],'template':binding['template'],'file':binding['final_nk'],'pattern':binding['output_pattern']}
    payload={'schema':'bridge.geometry-seed-cold-finalization/1','preparation':preparation,'authority':authority,'nk_binding':binding,'result':result}
    receipt=_load(receipt_path);key=hmac.new(native._key(),b'bridge.geometry-seed-cold-finalization/1\x00',hashlib.sha256).digest()
    if receipt.get('payload')!=payload or not hmac.compare_digest(str(receipt.get('signature')),hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()) or file_record(binding['final_nk']['path'])!=binding['final_nk']:_fail()
    return result

def _finalization(preparation,authority,details):
    """定稿可在只读预检阶段完成；执行仅接受同authority签名的原定稿记录。"""
    _,native=_context(preparation);binding=details['nk_binding'];target=_path(binding['final_nk']['path']);receipt_path=native.root/'geometry-seed-cold-finalization.json'
    result={'method':'controller_text_finalization','native_save_performed':False,'seed':binding['seed'],'template':binding['template'],'file':binding['final_nk'],'pattern':binding['output_pattern']}
    payload={'schema':'bridge.geometry-seed-cold-finalization/1','preparation':preparation,'authority':authority,'nk_binding':binding,'result':result}
    key=hmac.new(native._key(),b'bridge.geometry-seed-cold-finalization/1\x00',hashlib.sha256).digest()
    if receipt_path.exists():return _verify_finalization(preparation,authority,binding)
    data=_read(binding['seed'])
    if len(data)!=binding['final_nk']['bytes'] or hashlib.sha256(data).hexdigest()!=binding['final_nk']['sha256']:_fail()
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    if file_record(target)!=binding['final_nk']:_fail()
    from .geometry_job import _write
    _write(receipt_path,{'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()},new=True)
    return result

def finalize_authorized_nk(preparation,authority):
    p,source=validate(preparation,authority)
    return _finalization(preparation,p.get('finalization_authority',authority),{'nk_binding':source['nk_binding']})

def finalize_nk(details):
    return _finalization(details['preparation_record'],details['authority_record'],details)


def prepare_cold_context(preparation,authority):
    """同一新许可的零原生冷入口预检可先创建固定context；执行阶段只能逐字复用。"""
    p,source=validate(preparation,authority);_,native=_context(preparation)
    from .geometry_job import _write
    path=_path(source['producer']['control'])/'cold-context.json'
    value={'schema':'bridge.geometry-cold-context/1','native_scope':native.binding,'task_id':native.scope['task_id'],'input_artifact_source':source['input_source']}
    if path.exists():
        if _load(path)!=value:_fail()
        return file_record(path)
    return _write(path,value,new=True)

def verify_cold_worker_binding(native,*,operation_id,snapshot_record,input_contract_record,result_path,observation=False):
    """冷cap专用纯认证；完整HOM/typed由同cap唯一factory负责，不能单独用作执行准入。"""
    from .geometry_prelaunch_tail import _AUTH as tail_auth,cold_binding
    if (native.root/tail_auth).exists():
        return cold_binding(native,operation_id=operation_id,snapshot_record=snapshot_record,input_contract_record=input_contract_record,result_path=result_path,observation=observation)
    task_path=native.root/'state/nuke_renders'/(operation_id+'.json');task=_load(task_path);request=task.get('request_id','')
    if not request.endswith('_nuke'):_fail()
    mainop=request[:-5];job_record=file_record(native.root/'jobs'/mainop/'job.json');job=_object(_read(job_record));p,source=validate(job['preparation'],job['runtime_continuation'],native);_check_job(job,p,source)
    contract=_object(_read(input_contract_record));expected_nk=source['nk_binding']['final_nk'];state=native._read();result=_path(result_path)
    if (input_contract_record['path']!=str(native.root/'state/nuke_renders'/(operation_id+'.inputs.json')) or contract.get('schema')!='bridge.nuke.registered-input-contract/1.0' or contract.get('owner_task_id')!=native.scope['task_id'] or contract.get('registry_root')!=str(native.root/'artifact_ledger')):_fail()
    if (operation_id!='nrend-'+hashlib.sha256(request.encode()).hexdigest()[:16] or task.get('owner_task_id')!=native.scope['task_id'] or task.get('task_id')!=operation_id or task.get('frame_set')!=[1] or task.get('node')!='Write1' or task.get('pattern')!=source['nk_binding']['output_pattern'] or task.get('script_snapshot')!=snapshot_record['path'] or snapshot_record['sha256']!=expected_nk['sha256'] or snapshot_record['bytes']!=expected_nk['bytes'] or task.get('scene_fingerprint')!=expected_nk['sha256'] or task.get('input_contract')!=contract or result!=native.root/'state/nuke_renders'/(operation_id+'.worker-result.json') or file_record(expected_nk['path'])!=expected_nk):_fail()
    _read(snapshot_record)
    _verify_finalization(job['preparation'],p.get('finalization_authority',job['runtime_continuation']),source['nk_binding'])
    finalization_record=file_record(native.root/'geometry-seed-cold-finalization.json')
    matches=[t for t in state['tickets'] if t['role']=='nuke-render' and t['identity'].get('task_id')==operation_id and t['identity'].get('snapshot_sha256')==expected_nk['sha256'] and t['identity'].get('input_contract_sha256')==canonical_sha256(contract)]
    if not observation and (len(state['tickets'])!=17 or len(matches)!=1 or matches[0].get('stopped_at') is not None):_fail()
    if observation and (len(state['tickets'])!=16 or not all(t['stopped_at'] is not None for t in state['tickets'])):_fail()
    if not observation:
        from dcc_task_runtime import owned_process
        ticket=matches[0];started=owned_process.read_receipt(ticket['directory'],'started',identity=ticket['identity']);intent=_load(Path(ticket['directory'])/'intent.json')
        if not started or started.get('pid')!=os.getpid() or started.get('argv_sha256')!=canonical_sha256(intent.get('command')):_fail()
    s=_object(_read(source['budget_source']))
    return {'schema':'bridge.geometry-seed-cold-worker-binding/1','owner_task_id':native.scope['task_id'],'main_job_record':job_record,'operation_id':mainop,'approved_pattern':task['pattern'],'authority':job['runtime_continuation'],'low_authority':source['budget_authority'],'input_source':source['input_source'],'final_nk':expected_nk,'readset':[p['source'],p['request'],job_record,job['runtime_continuation'],finalization_record,*p['readset'],*p['consumer_runtime']['package_sources']],'accounting_prefix':s['journal_prefix'],'accounting_envelope':s['accounting_envelope'],'current_ticket':matches[0] if matches else None,'observation_only':bool(observation)}


def verify_cold_pre_admission_binding(native,*,operation_id,snapshot_record,input_contract_record,result_path,observation=False):
    """controller签proof前核同一046任务；没有NR票不能代替实际worker准入。"""
    from .geometry_prelaunch_tail import _AUTH as tail_auth,cold_binding
    if (native.root/tail_auth).exists():
        return cold_binding(native,operation_id=operation_id,snapshot_record=snapshot_record,input_contract_record=input_contract_record,result_path=result_path,observation=observation,pre_admission=not observation)
    if observation:
        return verify_cold_observation_binding(native,operation_id=operation_id,snapshot_record=snapshot_record,input_contract_record=input_contract_record,result_path=result_path)
    task_path=native.root/'state/nuke_renders'/(operation_id+'.json');task=_load(task_path);request=task.get('request_id','')
    if not request.endswith('_nuke'):_fail()
    mainop=request[:-5];job_record=file_record(native.root/'jobs'/mainop/'job.json');job=_object(_read(job_record));p,source=validate(job['preparation'],job['runtime_continuation'],native);_check_job(job,p,source)
    contract=_object(_read(input_contract_record));expected_nk=source['nk_binding']['final_nk'];state=native._read();result=_path(result_path)
    if (input_contract_record['path']!=str(native.root/'state/nuke_renders'/(operation_id+'.inputs.json')) or contract.get('schema')!='bridge.nuke.registered-input-contract/1.0' or contract.get('owner_task_id')!=native.scope['task_id'] or contract.get('registry_root')!=str(native.root/'artifact_ledger')):_fail()
    if (operation_id!='nrend-'+hashlib.sha256(request.encode()).hexdigest()[:16] or task.get('owner_task_id')!=native.scope['task_id'] or task.get('task_id')!=operation_id or task.get('frame_set')!=[1] or task.get('node')!='Write1' or task.get('pattern')!=source['nk_binding']['output_pattern'] or task.get('script_snapshot')!=snapshot_record['path'] or snapshot_record['sha256']!=expected_nk['sha256'] or snapshot_record['bytes']!=expected_nk['bytes'] or task.get('scene_fingerprint')!=expected_nk['sha256'] or task.get('input_contract')!=contract or result!=native.root/'state/nuke_renders'/(operation_id+'.worker-result.json') or file_record(expected_nk['path'])!=expected_nk):_fail()
    _read(snapshot_record)
    _verify_finalization(job['preparation'],p.get('finalization_authority',job['runtime_continuation']),source['nk_binding'])
    finalization_record=file_record(native.root/'geometry-seed-cold-finalization.json')
    from .geometry_cold_preflight_runtime import _AUTH as preflight_authority
    if (job['runtime_continuation']['path']!=str(native.root/preflight_authority)
            or len(state['tickets'])!=16 or any(t['stopped_at'] is None for t in state['tickets'])
            or state.get('closed_reason') is not None or state.get('geometry_seed_cold_recovery')!=source['budget_authority']):_fail()
    native.check()
    s=_object(_read(source['budget_source']))
    return {'schema':'bridge.geometry-seed-cold-worker-binding/1','owner_task_id':native.scope['task_id'],'main_job_record':job_record,'operation_id':mainop,'approved_pattern':task['pattern'],'authority':job['runtime_continuation'],'low_authority':source['budget_authority'],'input_source':source['input_source'],'final_nk':expected_nk,'readset':[p['source'],p['request'],job_record,job['runtime_continuation'],finalization_record,*p['readset'],*p['consumer_runtime']['package_sources']],'accounting_prefix':s['journal_prefix'],'accounting_envelope':s['accounting_envelope'],'current_ticket':None,'observation_only':False}

def verify_cold_observation_binding(native,*,operation_id,snapshot_record,input_contract_record,result_path):
    """closed16零原生整冷链观察；同源HMAC/包/readset，但没有执行票据或伪造job。"""
    from .geometry_prelaunch_tail import _AUTH as tail_auth,cold_binding
    if (native.root/tail_auth).exists():
        return cold_binding(native,operation_id=operation_id,snapshot_record=snapshot_record,input_contract_record=input_contract_record,result_path=result_path,observation=True)
    preparation=file_record(native.root/'geometry-preparation.json');authority=_active_authority(native);p,source=validate(preparation,authority,native);request=_object(_read(p['request']))
    mainop=request['new_operation_id'];expected='nrend-'+hashlib.sha256((mainop+'_nuke').encode()).hexdigest()[:16];state=native._read();_,_,closed=low.validate(native,source['budget_authority']);open16=dict(closed,closed_reason=None,geometry_seed_cold_recovery=source['budget_authority'])
    if (operation_id!=expected or len(state['tickets'])!=16 or any(t['stopped_at'] is None for t in state['tickets'])
            or state not in (closed,open16) or (native.root/'jobs'/mainop).exists()
            or (native.root/'state/nuke_renders'/(operation_id+'.json')).exists()):_fail()
    if state==closed and low.historical_closed_state(native)!=closed:_fail()
    _read(snapshot_record);contract=_object(_read(input_contract_record));binding=source['nk_binding'];result=_path(result_path)
    if (snapshot_record['sha256']!=binding['final_nk']['sha256'] or snapshot_record['bytes']!=binding['final_nk']['bytes']
            or contract.get('schema')!='bridge.nuke.registered-input-contract/1.0' or contract.get('owner_task_id')!=native.scope['task_id']
            or contract.get('registry_root')!=str(native.root/'artifact_ledger') or result.is_relative_to(native.root)):_fail()
    budget_source=_object(_read(source['budget_source']));readset=[p['source'],p['request'],authority,*p['readset'],*p['consumer_runtime']['package_sources'],snapshot_record,input_contract_record]
    finalization=native.root/'geometry-seed-cold-finalization.json'
    if finalization.exists():
        _verify_finalization(preparation,p.get('finalization_authority',authority),binding);readset.append(file_record(finalization))
    return {'schema':'bridge.geometry-seed-cold-worker-binding/1','owner_task_id':native.scope['task_id'],'main_job_record':None,'operation_id':mainop,'approved_pattern':binding['output_pattern'],'authority':authority,'low_authority':source['budget_authority'],'input_source':source['input_source'],'final_nk':binding['final_nk'],'readset':readset,'accounting_prefix':budget_source['journal_prefix'],'accounting_envelope':budget_source['accounting_envelope'],'current_ticket':None,'observation_only':True}
