"""官方RectLight等面积新任务的固定授权；旧任务只作来源，不继承票据。"""
from __future__ import annotations
import hashlib,hmac,json,re
from pathlib import Path

SCHEMA='bridge.rectlight-shape-scope/1'
RESOURCE_PROFILE='h21_rectlight_shape_12_1800_v1'
SCENE_PROFILE='official_karma_disklight_v1'
AUTHORITY_SCHEMA='bridge.rectlight-shape-authority/1'
PREPARATION_SCHEMA='bridge.rectlight-shape-preparation/1'
PLAN_SHA256='223791d34a56f791d2df5b276f71732987d7583c1be56d98c015bba1fe79bff8'
# 最终正常创作阶段硬收紧为两版各四票；前次H1已在旧签名范围单列。
BUDGET={'per_operation_seconds':120,'total_seconds':960,'max_dcc_starts':8,
        'max_disk_bytes':1073741824,'max_heavy_operations':1,'automatic_retries':0}
ROLES={'houdini-host':4,'main-husk':2,'nuke-render':2}
ROLE_SECONDS={role:120 for role in ROLES}
CALL_LIMITS={'tools':80,'schemas':10,'raw':90,'model_sessions':2,'creative_revisions':2,'causal_repairs':1}
TARGET={'area':0.81,'area_tolerance':1e-6,'width':[0.9,1.8],'height':[0.45,0.9],
        'ratio':[2.0,4.0],'exposure':-0.25,'distinct_revisions':True}
HISTORICAL_SOURCES=(
 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py',
 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py',
 'runtime/packages/houdini-bridge/src/houdini_bridge/alpha_reuse.py',
 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/native_scope.py',
 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/rectlight_shape_scope.py',
 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/project_color.py',
 'runtime/packages/houdini-bridge/src/houdini_bridge/rectlight_shape_target.py')
SOURCE_KEYS={'delivery','latest_result','preparation','scope','scope_state','scope_journal','scope_anchor','scope_key',
 'saved_hip','case_variant','configuration','reference_exr','reference_png','current_main','current_nuke','current_nk',
 'current_preview','nuke_template','runtime_manifest','runtime_snapshot_manifest','baseline_diagnostic','alpha',
 'alpha_source','independent_review','technical_evidence'}

def _fail():raise ValueError('RECTLIGHT_SHAPE_AUTHORITY_INVALID')
def _canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def read_record(record):
    """复用原安全FileRecord读取与NativeScope静态来源追踪，不构造来源scope。"""
    from .native_scope import _reuse_record_bytes
    if (type(record) is not dict or set(record)!={'path','bytes','sha256'}
            or type(record.get('bytes')) is not int or not 0<record['bytes']<=64*1024*1024):_fail()
    return _reuse_record_bytes(record)
def object_record(record):
    def unique(pairs):
        v={}
        for key,item in pairs:
            if key in v:_fail()
            v[key]=item
        return v
    v=json.loads(read_record(record),object_pairs_hook=unique)
    if type(v) is not dict:_fail()
    return v

def validate_runtime(runtime):
    """本任务固定0411正式包；新历史实现不能冒充旧0410/049。"""
    from .native_scope import _plain
    if type(runtime) is not dict or set(runtime)!={'version','formal_root','plugin','manifest','historical_sources'} or runtime['version']!='0.4.11':_fail()
    root=_plain(runtime['formal_root'])
    if runtime['plugin']['path']!=str(root/'plugin.json') or runtime['manifest']['path']!=str(root/'runtime-manifest.json'):_fail()
    plugin=object_record(runtime['plugin']);manifest=object_record(runtime['manifest'])
    if plugin.get('name')!='bridge-vfx' or plugin.get('version')!='0.4.11' or manifest.get('schema_version')!=1:_fail()
    entries=manifest.get('files')
    if type(entries) is not list or hashlib.sha256(_canonical(entries)).hexdigest()!=manifest.get('file_manifest_sha256'):_fail()
    index={}
    for entry in entries:
        if type(entry) is not dict or type(entry.get('path')) is not str or entry['path'] in index:_fail()
        index[entry['path']]=entry
    sources=runtime['historical_sources']
    if type(sources) is not dict or set(sources)!=set(HISTORICAL_SOURCES):_fail()
    for relative,record in sources.items():
        entry=index.get(relative)
        if entry is None or record!={'path':str(root/relative),'bytes':entry.get('bytes'),'sha256':entry.get('sha256')}:_fail()
        read_record(record)
    if index.get('plugin.json')!={'path':'plugin.json','bytes':runtime['plugin']['bytes'],'sha256':runtime['plugin']['sha256']}:_fail()
    return runtime

def validate_scope(scope,scope_path):
    """核验有限授权、源身份及固定预算；该入口本身从不初始化或写会计。"""
    from .native_scope import _plain
    from .project_color import validate_project_color
    forbidden={'continuation_of','creative_phase','feedback_phase','recovery_phase','execution_mode',
      'replacement_host_allowance','replacement_nuke_host_allowance','case_budget_revision','case_nuke_retry_revision',
      'case_storage_revision','accounting_namespace','source_reuse','roles','role_limits'}
    if forbidden.intersection(scope) or scope.get('schema')!=SCHEMA or scope.get('resource_profile')!=RESOURCE_PROFILE or scope.get('scene_profile')!=SCENE_PROFILE:_fail()
    root=_plain(scope['output_root'])
    if Path(scope_path)!=root/'scope.json' or scope.get('budget')!=BUDGET or scope.get('role_seconds')!=ROLE_SECONDS:_fail()
    if (any(type(x) is not int for x in scope['budget'].values()) or any(type(x) is not int for x in scope['role_seconds'].values())
            or scope.get('evidence_source')!='real_host' or scope.get('execution_authorized') is not True
            or scope.get('status')!='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):_fail()
    for key in ('scope_id','task_id','creative_task_id'):
        if type(scope.get(key)) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',scope[key]) is None:_fail()
    if scope['creative_task_id']==scope['task_id'] or scope.get('versions')!={'houdini':'21.0.631','nuke':'17.0v1'}:_fail()
    accounting=scope.get('accounting')
    if (type(accounting) is not dict or set(accounting)!={'key_path','key_sha256'}
            or accounting['key_path']!=str(root/'.native-control/key')
            or type(accounting['key_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',accounting['key_sha256']) is None):_fail()
    authority_record=scope.get('shape_authority')
    if type(authority_record) is not dict or authority_record.get('path')!=str(root/'rectlight-shape-authority.json'):_fail()
    a=object_record(authority_record)
    fields={'schema','plan','authorization','creative_task_id','source_scene_task_id','scope_id','output_root','ledger_root',
      'sources','sidecars','source_graph','saved_scene_id','scene_contract_sha256','baseline_control','target','frozen',
      'budget','roles','role_seconds','call_limits','hosts','versions','project_color','runtime_requirements','baseline'}
    if set(a)!=fields or a['schema']!=AUTHORITY_SCHEMA:_fail()
    if (a['plan']['sha256']!=PLAN_SHA256 or a['creative_task_id']!=scope['creative_task_id']
            or a['source_scene_task_id']!=scope['task_id'] or a['scope_id']!=scope['scope_id']
            or a['output_root']!=str(root) or a['ledger_root']!=str(root/'artifact_ledger')
            or _canonical(a['target'])!=_canonical(TARGET) or _canonical(a['budget'])!=_canonical(BUDGET)
            or _canonical(a['roles'])!=_canonical(ROLES) or _canonical(a['role_seconds'])!=_canonical(ROLE_SECONDS)
            or a['baseline']!={'width':0.9,'height':0.9,'exposure':-0.25}
            or a['call_limits']!=CALL_LIMITS or a['versions']!=scope['versions'] or a['hosts']!=scope['hosts']
            or a['project_color']!=scope['project_color'] or a['authorization']!=scope.get('authorization')):_fail()
    read_record(a['plan']);auth=a['authorization']
    if (type(auth) is not dict or set(auth)!={'authority','instruction'} or auth['authority']!='current_user_instruction'
            or type(auth['instruction']) is not str or not auth['instruction'].strip()):_fail()
    if validate_project_color(a['project_color'])['colorspace']!='ACEScg':_fail()
    if type(a['hosts']) is not dict or set(a['hosts'])!={'hython','husk','nuke','supervisor_python'}:_fail()
    for record in a['hosts'].values():read_record(record)
    sources=a['sources']
    if type(sources) is not dict or set(sources)!=SOURCE_KEYS:_fail()
    for record in sources.values():
        if _plain(record['path']).is_relative_to(root):_fail()
        read_record(record)
    delivery=object_record(sources['delivery']);result=object_record(sources['latest_result']);prep=object_record(sources['preparation'])
    if (delivery.get('state')!='TWO_REVISION_CREATIVE_ACCEPTED' or delivery.get('case_id')!='karma_lights_rectlight_v1'
            or delivery.get('all_stopped') is not True or delivery.get('slot_released') is not True
            or delivery.get('native_starts')!=50 or delivery.get('scope')!={k:sources['scope'][k] for k in ('path','sha256')}
            or delivery.get('results',[])[-1:]!=[sources['latest_result']] or delivery.get('preparation')!=sources['preparation']
            or delivery.get('independent_review')!=sources['independent_review'] or delivery.get('technical_evidence')!=sources['technical_evidence']):_fail()
    if (result.get('state')!='COMPLETE' or result.get('revision')!=2 or result.get('exposure')!=-0.25
            or any(x.get('task_id')!=scope['task_id'] for x in (delivery,result,prep))
            or prep.get('case_variant')!=sources['case_variant'] or prep.get('configuration')!=sources['configuration']
            or prep.get('source_graph')!=a['source_graph'] or prep.get('runtime_manifest')!=sources['runtime_manifest']
            or prep.get('runtime_snapshot_manifest')!=sources['runtime_snapshot_manifest'] or prep.get('nuke_template')!=sources['nuke_template']):_fail()
    saved=result['saved'];contract=saved['scene_contract']
    if (saved.get('path')!=sources['saved_hip']['path'] or saved.get('sha256')!=sources['saved_hip']['sha256']
            or saved.get('saved_scene_id')!=a['saved_scene_id'] or saved.get('scene_contract_sha256')!=a['scene_contract_sha256']
            or hashlib.sha256(_canonical(contract)).hexdigest()!=a['scene_contract_sha256']
            or contract.get('task_id')!=scope['task_id'] or result.get('control')!=a['baseline_control']
            or result.get('save_sidecars')!=a['sidecars'] or result.get('case_variant')!=sources['case_variant']
            or a['frozen']!={'scene_contract':a['scene_contract_sha256'],'exposure':-0.25,'preserve_except':['rect_width','rect_height']}):_fail()
    for key,source_key in (('main','current_main'),('nuke','current_nuke'),('nk','current_nk')):
        if result['files'][key]!=sources[source_key]:_fail()
    if result['preview']['preview']!=sources['current_preview'] or prep['media']['reference']['preview']!=sources['reference_png']:_fail()
    variant=object_record(sources['case_variant']);configuration=object_record(sources['configuration'])
    if (variant.get('case_id')!='karma_lights_rectlight_v1' or variant.get('reference')!=sources['reference_exr']
            or configuration.get('case_variant')!=sources['case_variant']):_fail()
    runtime_manifest=object_record(sources['runtime_manifest'])
    alpha_binding=runtime_manifest.get('production_host',{}).get('alpha_calibration')
    alpha=object_record(sources['alpha'])
    if (type(alpha_binding) is not dict or alpha_binding.get('calibration_source')!=sources['alpha_source']
            or sources['alpha_source']['sha256']!='1acc81701798ee365357520ed46917b4b84f3d271d080a8b049e948d9705f319'
            or any(alpha_binding.get(k)!=alpha.get('alpha_calibration',{}).get(k) for k in ('directory','identity','terminal_sha256'))):_fail()
    source_scope=object_record(sources['scope']);accounting=source_scope['accounting']
    if (source_scope.get('task_id',scope['task_id'])!=scope['task_id']
            or source_scope.get('output_root')==str(root) or _plain(source_scope['output_root']).is_relative_to(root)
            or root.is_relative_to(_plain(source_scope['output_root']))
            or sources['scope_key']['path']!=accounting['key_path']):_fail()
    state=object_record(sources['scope_state']);key=read_record(sources['scope_key']);payload=state.get('payload')
    if (len(key)!=32 or hashlib.sha256(key).hexdigest()!=accounting['key_sha256'] or type(payload) is not dict
            or not hmac.compare_digest(str(state.get('signature')),hmac.new(key,_canonical(payload),hashlib.sha256).hexdigest())):_fail()
    old=payload.get('state',{});tickets=old.get('tickets')
    if old.get('scope_sha256')!=sources['scope']['sha256'] or type(tickets) is not list or len(tickets)!=50 or any(t.get('stopped_at') is None for t in tickets):_fail()
    if type(a['sidecars']) is not list or not 1<=len(a['sidecars'])<=8:_fail()
    matched=False
    frozen=contract.get('frozen_scene_parameters',{}).get('fields',{})
    if any(frozen.get(k)!=v for k,v in {'light.xn__inputswidth_zta':0.9,'light.xn__inputsheight_mva':0.9,'light.xn__inputsexposure_vya':-0.25}.items()):_fail()
    for record in a['sidecars']:
        sidecar=object_record(record)
        if any(row.get('path')==saved['path'] and row.get('sha256')==saved['sha256']
               and row.get('scene_contract_sha256')==a['scene_contract_sha256']
               for row in sidecar.get('saves',[]) if isinstance(row,dict)):matched=True
    if not matched:_fail()
    if source_scope.get('hosts')!=a['hosts'] or source_scope.get('project_color')!=a['project_color']:_fail()
    validate_runtime(a['runtime_requirements'])
    return a
