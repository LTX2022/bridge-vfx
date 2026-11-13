"""RectLight新目标的执行胶水；复用既有GraphRun及真实生产收据，不重新建图。"""
from __future__ import annotations
import copy,hashlib,json,sqlite3,sys,time
from contextlib import closing
from pathlib import Path
from houdini_bridge.official_karma_observation import checked_bytes,file_record,write_new
from dcc_task_runtime.native_scope import NativeScope
from houdini_bridge.rectlight_shape_target import effective_configuration,shape_values,WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE,EXPOSURE,EXPOSURE_GATE

ROOT=Path(__file__).resolve().parents[4]
def _object(record):return json.loads(checked_bytes(record))
def readonly_shape_scope(binding):
    """仅已登记软箱范围使用无写锁读取；仍执行原授权、会计签名及停止事实校验。"""
    from dcc_task_runtime.native_scope import _plain
    if type(binding) is not dict or set(binding)!={'path','sha256'}:raise ValueError('RECT_SHAPE_SCOPE_BINDING_REQUIRED')
    record=file_record(_plain(binding['path']))
    if record['sha256']!=binding['sha256'] or _object(record).get('schema')!='bridge.rectlight-shape-scope/1':
        raise ValueError('RECT_SHAPE_SCOPE_BINDING_REQUIRED')
    # shape的_setup只读固定授权，不含旧范围的阶段构造或会计初始化。
    native=NativeScope.__new__(NativeScope);native._setup(binding);native._read()
    return native

def _completed_usage(native):
    """只认证生产时的已停止票据，不刷新目录占用或回写历史关闭状态。"""
    state=native._read();tickets=state['tickets'];now=time.time()
    if (len(tickets)>native.scope['budget']['max_dcc_starts']
            or any(t.get('stopped_at') is None or t['admitted_at']>now or t['stopped_at']>now+1 for t in tickets)):
        raise ValueError('RECT_SHAPE_ALL_OWNED_STOPS_REQUIRED')
    charges=[max(t['charged_seconds'],t['stopped_at']-t['admitted_at']) for t in tickets]
    if sum(charges)>native.scope['budget']['total_seconds'] or any(c>native.role_seconds(t['role']) for t,c in zip(tickets,charges)):
        raise ValueError('RECT_SHAPE_COMPLETED_BUDGET_REQUIRED')
    return tickets

def _stop_ticket(native,tickets,supervisor,role):
    """将原签名停止回执精确绑定同scope、角色、目录和identity。"""
    from dcc_task_runtime.owned_process import read_receipt,execution_returncode,_canonical
    started=read_receipt(supervisor['directory'],'started',identity=supervisor['identity'])
    stopped=read_receipt(supervisor['directory'],'stopped',identity=supervisor['identity'])
    matches=[t for t in tickets if t['role']==role and t['directory']==supervisor['directory'] and t['identity']==supervisor['identity']]
    if (len(matches)!=1 or not started or not stopped or execution_returncode(stopped)!=0
            or started.get('pid')!=stopped.get('pid') or stopped.get('stop_reason') is not None
            or (started.get('resource_budget') or {}).get('native_scope')!=native.binding
            or matches[0]['stopped_at']!=stopped.get('observed_at')
            or matches[0]['stopped_sha256']!=hashlib.sha256(_canonical(stopped)).hexdigest()):
        raise ValueError('RECT_SHAPE_ORIGINAL_STOP_TICKET_REQUIRED')
    return started,stopped

def _readonly_database(path):
    """完成账本必须已checkpoint；immutable只读不会创建原目录的WAL/SHM。"""
    from dcc_task_runtime.native_scope import _plain
    path=_plain(path);wal=Path(str(path)+'-wal')
    if not path.is_file() or wal.exists() and wal.stat().st_size:
        raise ValueError('RECT_SHAPE_COMPLETED_DATABASE_NOT_CHECKPOINTED')
    db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True);db.row_factory=sqlite3.Row
    return db

def _original_render_fact(native,tickets,control,source):
    """复用原生产typed校验的纯读取部分；不调用会取锁、迁移或reconcile的client入口。"""
    from houdini_bridge import client
    from houdini_bridge.operation_store import resolve_record
    from houdini_bridge.controlled_output import validate_controlled_policy,_configuration,controlled_route_sha256,_decode_snapshot,_validate_exr_color,NATIVE_INTERNAL_UNKNOWNS
    from houdini_bridge.alpha_reuse import validate_output_calibration
    from dcc_task_runtime.project_color import validate_project_color
    from dcc_task_runtime.canonical import canonical_sha256
    owners=_object(source['producer_owners']);verify=source['registry_operation_receipt']['operation_id'];owner=owners.get(verify)
    if (not owner or owner.get('operation_kind')!='output-verification' or owner.get('task_id')!=source['task_id']
            or owner.get('evidence_source')!='real_host'):raise ValueError('RECT_SHAPE_PRODUCER_OWNER_REQUIRED')
    operation=owner['parent_operation_id'];binding=owners.get(operation)
    if not binding or binding.get('task_id')!=source['task_id']:raise ValueError('RECT_SHAPE_PRODUCER_OWNER_REQUIRED')
    for path in (binding['operation_store_path'],binding['supervisor_binding']['directory']):
        if not Path(path).is_relative_to(control):raise ValueError('RECT_SHAPE_PRODUCER_PATH_REQUIRED')
    store_path=Path(binding['operation_store_path']);record=resolve_record(store_path,client._read_render_store_snapshot(store_path),operation)
    original=record.get('execution_fact');producer=client.render_producer_binding(record)
    if (record.get('kind')!='render' or record.get('state')!='COMPLETED' or record.get('task_id')!=source['task_id']
            or record.get('request_id')!=operation or record.get('request_sha256')!=binding.get('request_sha256')
            or record.get('host_identity')!=binding.get('host_identity') or record.get('supervisor_binding')!=binding.get('supervisor_binding')
            or producer!=binding.get('producer_binding') or original!=client.render_execution_fact(record)
            or original.get('operation_receipt_sha256')!=client.render_receipt_digest(original)):
        raise ValueError('RECT_SHAPE_ORIGINAL_RENDER_REQUIRED')
    client._verify_render_terminal(binding,original)
    started,stopped=_stop_ticket(native,tickets,producer['supervisor_binding'],'houdini-host')
    policy=validate_controlled_policy(owner['policy']);readback=_configuration(producer,policy);color=validate_project_color(producer['project_color'])
    if producer.get('output_acceptance')!=policy or original.get('frame_set')!=[1] or original.get('frames_done')!=[1]:
        raise ValueError('RECT_SHAPE_ORIGINAL_RENDER_REQUIRED')
    calibration=validate_output_calibration(owner['alpha_calibration'],expected_version=readback['houdini_version'],
        expected_plugin_build=readback['plugin_build'],expected_route_sha256=controlled_route_sha256(readback,require_color_route=True),
        evidence_source='real_host',shape_scope_binding=native.binding)
    snapshots=copy.deepcopy(original['frame_snapshots'])
    if set(snapshots)!={'1'} or type(calibration.get('associated')) is not bool:raise ValueError('RECT_SHAPE_TYPED_MAIN_REQUIRED')
    image=_decode_snapshot(snapshots['1'],resolution=policy['resolution'],channels=policy['channels'])
    _validate_exr_color(image,color['colorspace']);image.update(copy.deepcopy(snapshots['1']),colorspace=color['colorspace'],
        premultiplied=calibration['associated'],project_color=color,color_metadata_source='human_project_selection',verification_basis='controlled_output_v1')
    fact={key:copy.deepcopy(original[key]) for key in ('frame_set','frames_done','output_pattern','started_at_epoch','scene_fingerprint','dependencies','host_identity')}
    fact.update(schema='bridge.houdini.controlled-output/1.0',command='output.verify',kind='output_verification',operation_id=verify,
        parent_operation_id=operation,task_id=source['task_id'],state='COMPLETED',stop_confirmed=True,completion_metadata_status='AVAILABLE',
        verification_basis='controlled_output_v1',native_internal_status='NOT_OBSERVED',native_internal_unknowns=list(NATIVE_INTERNAL_UNKNOWNS),
        policy=policy,source_receipt_sha256=original['operation_receipt_sha256'],started_receipt_sha256=canonical_sha256(started),
        stopped_receipt_sha256=canonical_sha256(stopped),project_color=color,frame_snapshots=snapshots,metadata={'1':image},
        alpha_calibration=calibration,evidence_source='real_host')
    fact['operation_receipt_sha256']=client.render_receipt_digest(fact)
    if fact!=_object(file_record(control/'host-state'/('verified-output-'+verify+'.json'))) or canonical_sha256(fact)!=source['producer_fact_sha256']:
        raise ValueError('RECT_SHAPE_TYPED_MAIN_CHANGED')
    return fact

def _original_completions(native,directory,source,result,stages):
    """仅交付本软箱两版的不可变历史；公共registry当前版本和失效规则保持不变。"""
    from dcc_task_runtime.canonical import canonical_sha256
    from nuke_bridge.task_host import _rectlight_shape_source_binding
    from nuke_bridge.operation_receipts import finalize_render_operation,completed_operation_projection
    tickets=_completed_usage(native);control,ledger=_rectlight_shape_source_binding(source,native,result['task_id'])
    if (control!=directory/'project/control' or source['artifact_version']!=result['revision']
            or source['registry_operation_receipt']!=result['artifact']['registry_operation_receipt']
            or stages['register']['result']!=result['artifact']):raise ValueError('RECT_SHAPE_ORIGINAL_SOURCE_REQUIRED')
    for name,relative in (('producer_manifest','run.json'),('producer_snapshot_manifest','snapshot-manifest.json'),
                          ('producer_deployment','production-hosts.json'),('producer_owners','host-state/houdini-operation-owners.json')):
        if source[name]!=file_record(control/relative):raise ValueError('RECT_SHAPE_ORIGINAL_SOURCE_REQUIRED')
    deployment=_object(source['producer_deployment']);host=deployment.get('hosts',{}).get('houdini',{})
    if (deployment.get('task_id')!=result['task_id'] or host.get('native_scope')!=native.binding
            or host.get('controller_root')!=str(control) or host.get('task_root')!=str(native.root)
            or host.get('feedback_ledger_root')!=str(ledger) or host.get('evidence_source')!='real_host'):
        raise ValueError('RECT_SHAPE_ORIGINAL_DEPLOYMENT_REQUIRED')
    fact=_original_render_fact(native,tickets,control,source);receipt=source['registry_operation_receipt'];unsigned=dict(receipt);digest=unsigned.pop('registry_operation_receipt_sha256')
    if (digest!=canonical_sha256(unsigned) or receipt.get('schema')!='bridge.registry.operation-receipt/1.0'
            or receipt.get('command')!='artifact.register' or receipt.get('stage')!='persisted_output' or receipt.get('state')!='COMPLETED'
            or receipt.get('producer_fact_sha256')!=canonical_sha256(fact) or receipt.get('producer_receipt_sha256')!=fact['operation_receipt_sha256']
            or receipt.get('frame_snapshots')!=fact['frame_snapshots'] or receipt.get('completion_metadata')!=fact['metadata']):
        raise ValueError('RECT_SHAPE_ORIGINAL_REGISTRY_RECEIPT_REQUIRED')
    nuke=result['nuke'];operation='nrend-'+hashlib.sha256((result['operation_id']+'_nuke').encode()).hexdigest()[:16]
    task=_object(file_record(native.root/'state/nuke_renders'/(operation+'.json')));artifact=nuke['artifact']
    if (nuke.get('operation_id')!=operation or task.get('task_id')!=operation or task.get('owner_task_id')!=result['task_id']
            or artifact.get('artifact_id')!='nuke-render-'+operation or artifact.get('operation_id')!=operation
            or artifact.get('pattern')!=str(directory/'project/saves/nuke.%04d.exr')
            or task.get('pattern')!=artifact['pattern'] or task.get('frame_set')!=[1]):
        raise ValueError('RECT_SHAPE_ORIGINAL_NUKE_REQUIRED')
    execution=task['execution_fact'];basis={'task_id':operation,'pattern':task['pattern'],'frame_set':task['frame_set'],
        'scene_fingerprint':task['scene_fingerprint'],'frame_snapshots':execution['frame_snapshots'],'state':execution['state'],'execution_kind':execution['kind']}
    nuke_fact={'task_id':result['task_id'],'scene_fingerprint':task['scene_fingerprint'],'frame_set':task['frame_set'],
        'output_pattern':task['pattern'],'frame_snapshots':execution['frame_snapshots'],'operation_receipt_sha256':canonical_sha256(basis),'execution_fact':execution}
    formal=finalize_render_operation(task,nuke_fact);projection=completed_operation_projection(formal,nuke_fact)
    process=execution['process_identity'];supervisor={'directory':process['supervisor_directory'],'identity':process['supervisor_identity']}
    _stop_ticket(native,tickets,supervisor,'nuke-render')
    if (formal!=nuke.get('formal_operation_receipt') or not projection or projection.get('completion_metadata_status')!='AVAILABLE'
            or task.get('ledger_state')!='REGISTERED' or task.get('slot_released') is not True or task.get('supervisor_stop_reason') is not None
            or task.get('worker_receipt')!=execution.get('worker_receipt')
            or _object(file_record(process['worker_result']))!=execution['worker_receipt']
            or file_record(formal['script_snapshot'])['sha256']!=supervisor['identity']['snapshot_sha256']
            or artifact.get('operation_receipt_sha256')!=nuke_fact['operation_receipt_sha256']
            or artifact.get('payload',{}).get('completion_snapshot')!=formal['frame_snapshots']
            or artifact.get('payload',{}).get('completion_metadata')!=projection['metadata']):
        raise ValueError('RECT_SHAPE_TYPED_NUKE_REQUIRED')
    for snapshot in formal['frame_snapshots'].values():
        if file_record(snapshot['path'])!={k:snapshot[k] for k in ('path','bytes','sha256')}:raise ValueError('RECT_SHAPE_NUKE_BYTES_CHANGED')
    with closing(_readonly_database(ledger/'artifacts.sqlite3')) as db:
        for item in (result['artifact'],artifact):
            row=db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?',(item['artifact_id'],item['version'])).fetchone()
            if row is None or json.loads(row[0])!={k:v for k,v in item.items() if k!='registry_operation_receipt'}:
                raise ValueError('RECT_SHAPE_ORIGINAL_ARTIFACT_HISTORY_REQUIRED')
        row=db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',(receipt['artifact_id'],receipt['version'])).fetchone()
        if row is None or json.loads(row[0])!=receipt or canonical_sha256({k:v for k,v in result['artifact'].items() if k!='registry_operation_receipt'})!=receipt['artifact_payload_sha256']:
            raise ValueError('RECT_SHAPE_ORIGINAL_REGISTRY_RECEIPT_REQUIRED')
    with closing(_readonly_database(native.root/'scheduler/graph_scheduler.sqlite3')) as db:
        slot=task['slot'];row=db.execute('SELECT * FROM heavy_slot WHERE slot=1').fetchone()
        stopped=db.execute('SELECT fact_json FROM stopped_attempts WHERE owner_root=? AND operation_id=? AND token=?',
            (slot['owner_root'],operation,slot['token'])).fetchone()
        if not row or row['active']!=0 or row['phase']!='RELEASED' or row['generation']<slot['generation'] or stopped is None:
            raise ValueError('RECT_SHAPE_ORIGINAL_NUKE_SLOT_REQUIRED')
        released=json.loads(stopped[0])
        if (released.get('observed_stopped') is not True or released.get('generation')!=slot['generation']
                or any(released.get(k)!=slot[k] for k in ('owner_root','operation_id','token'))
                or json.loads(released.get('process_json') or 'null')!=process):
            raise ValueError('RECT_SHAPE_ORIGINAL_NUKE_SLOT_REQUIRED')
    return receipt
def _once(path,value):
    if path.exists():
        record=file_record(path)
        if _object(record)!=value:raise ValueError('RECT_SHAPE_PREPARED_INPUT_CHANGED')
        return record
    path.parent.mkdir(parents=True,exist_ok=True);return write_new(path,value)
def legacy_runner():
    if str(ROOT/'tools') not in sys.path:sys.path.insert(0,str(ROOT/'tools'))
    import run_hy3_creative
    return run_hy3_creative

def execution_job(job_path):
    """原模型job不改写；单独生成冻结执行准备和每job受控代码视图。"""
    job_record=file_record(Path(job_path));job=_object(job_record);prep=_object(job['preparation']);native=NativeScope(prep['scope'])
    if job.get('schema')!='bridge.rectlight-shape-job/1' or Path(job['directory'])!=native.root/'jobs'/job['operation_id']:
        raise ValueError('RECT_SHAPE_JOB_ROOT_REQUIRED')
    shape_values(job['plan']['rectlight_shape'])
    config_record=_once(native.root/'effective-scene.json',effective_configuration(prep))
    from houdini_bridge.alpha_reuse import make_reuse_binding
    source_alpha=_object(prep['alpha_result'])['alpha_calibration']
    active_plugin=file_record(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py')
    alpha=make_reuse_binding(source_alpha,prep['alpha_relocation']['source_plugin'],active_plugin,shape_scope_binding=native.binding)
    authority=_object(prep['target_authority'])
    roots=[str(native.root.parent),str(Path(authority['plan']['path']).parent)]
    if roots[0]==roots[1] or Path(roots[0]).is_relative_to(roots[1]) or Path(roots[1]).is_relative_to(roots[0]):raise ValueError('RECT_SHAPE_DISTINCT_BUDGET_ROOTS_REQUIRED')
    old=_object(prep['runtime_manifest']);hosts={}
    for kind,name in (('houdini','production_host'),('nuke','production_nuke')):
        cfg=copy.deepcopy(old[name])
        for key in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source'):cfg.pop(key,None)
        cfg.update(native_scope=native.binding,task_root=str(native.root),feedback_ledger_root=prep['ledger_root'],
            resource_budget={'roots':roots,'max_bytes':native.scope['budget']['max_disk_bytes'],'native_scope':native.binding})
        if kind=='houdini':cfg['alpha_calibration']=alpha
        hosts[kind]=cfg
    original=_object(prep['source_preparation']);execution=copy.deepcopy(prep)
    execution.update(configuration=config_record,original_configuration=prep['configuration'],original_preparation=job['preparation'],hosts=hosts,
        feedback_preparation=original['feedback_preparation'],budget_roots=roots)
    execution_record=_once(native.root/'execution-preparation.json',execution)
    execution_job_value={**job,'preparation':execution_record,'source_job':job_record}
    execution_path=Path(job['directory'])/'execution-job.json';_once(execution_path,execution_job_value)
    run=legacy_runner();jobprep=run.prepare_job(execution,execution_job_value);control=Path(jobprep['control'])
    # run尚未启动宿主；将本任务controller绑定定稿后封签，不签未来可变部署/PID。
    run_path=control/'run.json';manifest=json.loads(run_path.read_text())
    for name in ('production_host','production_nuke'):
        manifest[name].update(controller_root=str(control),task_root=str(native.root),native_scope=native.binding)
        manifest[name]['resource_budget']['native_scope']=native.binding
    from dcc_task_runtime.platform_support import atomic_write
    atomic_write(run_path,(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(),owned_root=control)
    from dcc_task_runtime.process_image import seal_runtime_view
    view=control/'rectlight-shape-runtime-view.json'
    if not view.exists():seal_runtime_view(native.binding,file_record(execution_path),control)
    return execution_path,jobprep

def execute_job(job_path):
    """只从job已封签代码视图执行原控制流程；所有Native仍由NativeScope计量。"""
    job=json.loads(Path(job_path).read_text());control=Path(job['directory'])/'project/control'
    if ROOT!=control/'snapshot':raise ValueError('RECT_SHAPE_EXECUTE_SIGNED_SNAPSHOT_REQUIRED')
    from dcc_task_runtime.process_image import verify_runtime_view
    preparation=_object(job['preparation'])
    verify_runtime_view(preparation['scope'],control)
    legacy_runner().execute_job(Path(job_path))

def _validate_output_bindings(directory,result,receipt):
    """返回入口只交付本job已验收据指向的文件，拒绝合法旧FR替换。"""
    saves=directory/'project/saves';files=result['files'];artifact=result['artifact']
    if set(files)!={'hip','main','nk','nuke'}:raise ValueError('RECT_SHAPE_FINAL_FILE_SET_REQUIRED')
    hip=file_record(result['saved']['path']);main=file_record(saves/'main.0001.exr')
    nk=file_record(saves/'composite.nk');nuke=file_record(saves/'nuke.0001.exr')
    if (files!={'hip':hip,'main':main,'nk':nk,'nuke':nuke}
        or result['nuke']['files']!={'nk':nk,'exr':nuke}
        or result['preview']['source']!=main
        or result['preview']['preview']!=file_record(saves/'preview.png')):
        raise ValueError('RECT_SHAPE_FINAL_JOB_FILE_BINDING_REQUIRED')
    for key in ('artifact_id','version','task_id','pattern','frame_set'):
        if artifact.get(key)!=receipt.get(key):raise ValueError('RECT_SHAPE_ARTIFACT_RECEIPT_BINDING_REQUIRED')
    if (artifact['artifact_id']!='rectlight_shape_main' or artifact['version']!=result['revision']
        or artifact['task_id']!=result['task_id'] or artifact['frame_set']!=[1]
        or artifact['pattern']!=str(saves/'main.%04d.exr')):
        raise ValueError('RECT_SHAPE_MAIN_FRAME_IDENTITY_REQUIRED')
    metadata=receipt['completion_metadata']['1']
    if any(metadata.get(k)!=main[k] for k in ('path','bytes','sha256')):raise ValueError('RECT_SHAPE_MAIN_RECEIPT_BYTES_REQUIRED')
    compared=result['comparison']
    if (compared.get('state')!='PASS' or compared.get('resolution')!=[420,300]
        or compared.get('samples_compared')!=504000 or compared.get('different_samples')!=0
        or compared.get('require_identical') is not True):raise ValueError('RECT_SHAPE_EXACT_RGBA_COMPARISON_REQUIRED')

def validate_result(preparation,entry,result,*,read_only=False):
    """接受必须有真实保存、冷开、登记和Nuke收据，不能只相信COMPLETE。"""
    prep=_object(preparation);native=readonly_shape_scope(prep['scope']) if read_only else NativeScope(prep['scope']);directory=native.root/'jobs'/entry['operation_id']
    from dcc_task_runtime.process_image import verify_runtime_view
    verify_runtime_view(prep['scope'],directory/'project/control')
    job=_object(entry['job']);execution_record=file_record(directory/'execution-job.json');execution=_object(execution_record)
    if (entry['job']!=file_record(directory/'job.json') or job.get('schema')!='bridge.rectlight-shape-job/1'
        or job.get('preparation')!=preparation or job.get('operation_id')!=entry['operation_id'] or job.get('directory')!=str(directory)
        or entry['revision'] not in (1,2) or job.get('plan',{}).get('revision')!=entry['revision']
        or result.get('schema')!='bridge.hy3-creative-revision/1' or result.get('state')!='COMPLETE'
        or result.get('task_id')!=prep['task_id'] or result.get('creative_task_id')!=prep['creative_task_id']
        or result.get('shape_authority')!=prep['target_authority'] or result.get('operation_id')!=entry['operation_id']
        or result.get('revision')!=entry['revision'] or result.get('plan')!=job['plan']
        or execution.get('source_job')!=entry['job'] or execution.get('plan')!=job['plan']):
        raise ValueError('RECT_SHAPE_RESULT_BINDING_REQUIRED')
    from .creative_results import require_completed_journal
    stages=require_completed_journal(directory,execution_record);dims=shape_values(job['plan']['rectlight_shape'])
    saved=result['saved'];cold=stages['cold_reopen']['result'];changed=result['feedback']
    if (Path(saved['path']).parent!=directory/'project/saves' or file_record(saved['path'])['sha256']!=saved['sha256']
        or cold.get('path')!=saved['path'] or cold.get('sha256')!=saved['sha256']
        or any(cold.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))):raise ValueError('RECT_SHAPE_REAL_COLD_REOPEN_REQUIRED')
    from dcc_task_runtime.canonical import canonical_sha256
    if saved['scene_contract_sha256']!=canonical_sha256(saved['scene_contract']):raise ValueError('RECT_SHAPE_SAVE_CONTRACT_REQUIRED')
    for key,parm in [('width',WIDTH),('height',HEIGHT)]:
        if changed['after'].get(parm)!=dims[key] or changed['before'].get(parm)!=job['plan']['base_shape'][key]:raise ValueError('RECT_SHAPE_NATIVE_PARAMETERS_REQUIRED')
    if stages['cold_readback']['result']['parms']!=changed['after'] or result['comparison'].get('state')!='PASS':raise ValueError('RECT_SHAPE_DOWNSTREAM_MATCH_REQUIRED')
    source_record=file_record(directory/'project/control/creative-input-source.json');source=_object(source_record)
    if read_only:receipt=_original_completions(native,directory,source,result,stages)
    else:
        from .creative_results import completed_registry,validate_nuke_completion
        registry=completed_registry(source,native,prep['task_id']);receipt=registry.verify_operation_receipt(result['artifact']['registry_operation_receipt'])
        validate_nuke_completion(registry,result,native)
    if receipt['artifact_id']!='rectlight_shape_main' or receipt['version']!=entry['revision']:raise ValueError('RECT_SHAPE_REGISTERED_VERSION_REQUIRED')
    _validate_output_bindings(directory,result,receipt)
    for record in result['files'].values():checked_bytes(record)
    checked_bytes(result['preview']['preview'])
    for record in prep['protected_files'].values():checked_bytes(record)
    if read_only:_completed_usage(native)
    elif any(t.get('stopped_at') is None for t in native.snapshot()['tickets']):raise ValueError('RECT_SHAPE_ALL_OWNED_STOPS_REQUIRED')
    return {'state':'VERIFIED','scope':native.binding,'source_record':source_record}
