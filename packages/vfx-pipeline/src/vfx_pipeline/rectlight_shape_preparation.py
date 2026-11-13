"""从已完成官方Rect工程准备独立软箱任务；只复用原件，不执行DCC。"""
from __future__ import annotations
import copy,hashlib,json,os,re,secrets,sys,uuid
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.rectlight_shape_scope import (SCHEMA,RESOURCE_PROFILE,SCENE_PROFILE,AUTHORITY_SCHEMA,
    PREPARATION_SCHEMA,PLAN_SHA256,BUDGET,ROLES,ROLE_SECONDS,CALL_LIMITS,TARGET,HISTORICAL_SOURCES,
    object_record,read_record,validate_scope,validate_runtime)
from houdini_bridge.official_karma_observation import file_record,write_new


def _plain(value):
    from dcc_task_runtime.native_scope import _plain
    return _plain(value)


def runtime_requirements(execution_plugin):
    """正式411的原索引绑定当前安装实现；开发目录不能假作已安装包。"""
    formal=_plain(execution_plugin);runtime=Path(__file__).resolve().parents[4];current=runtime.parent
    if runtime.name!='runtime':raise ValueError('RECT_SHAPE_INSTALLED_RUNTIME_REQUIRED')
    requirements={'version':'0.4.11','formal_root':str(formal),'plugin':file_record(formal/'plugin.json'),
        'manifest':file_record(formal/'runtime-manifest.json'),
        'historical_sources':{rel:file_record(formal/rel) for rel in HISTORICAL_SOURCES}}
    validate_runtime(requirements)
    for name,record in (('plugin.json',requirements['plugin']),('runtime-manifest.json',requirements['manifest'])):
        local=file_record(current/name)
        if any(local[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('RECT_SHAPE_RUNTIME_INDEX_CHANGED')
    manifest=object_record(requirements['manifest']);index={x['path']:x for x in manifest['files']}
    relative='runtime/packages/vfx-pipeline/src/vfx_pipeline/rectlight_shape_preparation.py'
    own=file_record(Path(__file__))
    if Path(__file__)!=current/relative or index.get(relative)!={'path':relative,'bytes':own['bytes'],'sha256':own['sha256']}:
        raise ValueError('RECT_SHAPE_PREPARER_RUNTIME_CHANGED')
    for rel,record in requirements['historical_sources'].items():
        local=file_record(current/rel)
        if any(local[k]!=record[k] for k in ('bytes','sha256')):raise ValueError('RECT_SHAPE_RUNTIME_SOURCE_CHANGED')
    return requirements


def inspect_source(source_delivery):
    """一次认证原50票全停及固定来源；不装配宿主/工厂或刷新旧scope状态。"""
    from dcc_task_runtime.native_scope import NativeScope
    delivery_record=file_record(_plain(source_delivery));d=object_record(delivery_record)
    if d.get('state')!='TWO_REVISION_CREATIVE_ACCEPTED' or d.get('case_id')!='karma_lights_rectlight_v1' or d.get('native_starts')!=50:
        raise ValueError('RECT_SHAPE_COMPLETED_SOURCE_REQUIRED')
    result_record=d['results'][-1];r=object_record(result_record);prep_record=d['preparation'];p=object_record(prep_record)
    if (r.get('state')!='COMPLETE' or r.get('revision')!=2 or r.get('exposure')!=-0.25
            or r.get('task_id')!=d.get('task_id') or p.get('task_id')!=d.get('task_id')):
        raise ValueError('RECT_SHAPE_SOURCE_REVISION_REQUIRED')
    source_scope_record=file_record(d['scope']['path'])
    if {k:source_scope_record[k] for k in ('path','sha256')}!=d['scope']:raise ValueError('RECT_SHAPE_SOURCE_SCOPE_CHANGED')
    native=NativeScope(d['scope']);usage=native.completed_snapshot()
    if usage['dcc_starts']!=50 or any(t.get('stopped_at') is None for t in usage['tickets']):
        raise ValueError('RECT_SHAPE_SOURCE_STOP_REQUIRED')
    saved=r['saved'];variant=object_record(p['case_variant']);configuration=object_record(p['configuration'])
    manifest=object_record(p['runtime_manifest']);alpha_record=native.scope['reused_inputs']['alpha'];alpha=object_record(alpha_record)
    alpha_binding=copy.deepcopy(manifest['production_host']['alpha_calibration'])
    alpha_source=alpha_binding.get('calibration_source')
    if alpha_source is None:raise ValueError('RECT_SHAPE_ALPHA_SOURCE_REQUIRED')
    read_record(alpha_source)
    sources={'delivery':delivery_record,'latest_result':result_record,'preparation':prep_record,
      'scope':source_scope_record,'scope_state':file_record(native.state_path),'scope_journal':file_record(native.journal_path),
      'scope_anchor':file_record(native.anchor_path),'scope_key':file_record(native.key_path),'saved_hip':file_record(saved['path']),
      'case_variant':p['case_variant'],'configuration':p['configuration'],'reference_exr':variant['reference'],
      'reference_png':p['media']['reference']['preview'],'current_main':r['files']['main'],'current_nuke':r['files']['nuke'],
      'current_nk':r['files']['nk'],'current_preview':r['preview']['preview'],'nuke_template':p['nuke_template'],
      'runtime_manifest':p['runtime_manifest'],'runtime_snapshot_manifest':p['runtime_snapshot_manifest'],
      'baseline_diagnostic':file_record(Path(r['control'])/'diagnostic.sqlite3'),'alpha':alpha_record,'alpha_source':alpha_source,
      'independent_review':d['independent_review'],'technical_evidence':d['technical_evidence']}
    for record in sources.values():read_record(record)
    for record in r['save_sidecars']:read_record(record)
    # 明确新前端任务与原scene task映射；不重写HIP内部task/graph身份。
    return {'sources':sources,'delivery':d,'result':r,'preparation':p,'source_scope':native.scope,
      'source_snapshot':usage,'alpha_binding':alpha_binding,'alpha_calibration':alpha,'configuration':configuration}


def prepare(source_delivery,output_root,creative_task_id,instruction,*,plan_record,execution_plugin):
    """仅新根写authority/scope/空ledger/准备；原输入只链接且不重做基线。"""
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    if (type(creative_task_id) is not str or re.fullmatch('[A-Za-z0-9_-]{1,128}',creative_task_id) is None
            or type(instruction) is not str or not instruction.strip()):raise ValueError('RECT_SHAPE_TASK_AUTHORIZATION_REQUIRED')
    root=_plain(output_root)
    if root.exists() or root.is_symlink():raise ValueError('RECT_SHAPE_FRESH_ROOT_REQUIRED')
    if plan_record.get('sha256')!=PLAN_SHA256:raise ValueError('RECT_SHAPE_APPROVED_PLAN_REQUIRED')
    read_record(plan_record);runtime=runtime_requirements(execution_plugin);source=inspect_source(source_delivery)
    old=source['source_scope'];p=source['preparation'];r=source['result'];sources=source['sources']
    oldroot=_plain(old['output_root'])
    if root.is_relative_to(oldroot) or oldroot.is_relative_to(root) or creative_task_id==r['task_id']:
        raise ValueError('RECT_SHAPE_SOURCE_ROOT_OR_TASK_REUSED')
    for record in sources.values():
        if _plain(record['path']).is_relative_to(root):raise ValueError('RECT_SHAPE_SOURCE_IN_OUTPUT')
    sid='rectshape_'+uuid.uuid4().hex;key=secrets.token_bytes(32)
    authority={'schema':AUTHORITY_SCHEMA,'plan':copy.deepcopy(plan_record),
      'authorization':{'authority':'current_user_instruction','instruction':instruction},
      'creative_task_id':creative_task_id,'source_scene_task_id':r['task_id'],'scope_id':sid,
      'output_root':str(root),'ledger_root':str(root/'artifact_ledger'),'sources':sources,'sidecars':r['save_sidecars'],
      'source_graph':p['source_graph'],'saved_scene_id':r['saved']['saved_scene_id'],
      'scene_contract_sha256':r['saved']['scene_contract_sha256'],'baseline_control':r['control'],
      'target':copy.deepcopy(TARGET),'baseline':{'width':0.9,'height':0.9,'exposure':-0.25},
      'frozen':{'scene_contract':r['saved']['scene_contract_sha256'],'exposure':-0.25,'preserve_except':['rect_width','rect_height']},
      'budget':copy.deepcopy(BUDGET),'roles':copy.deepcopy(ROLES),'role_seconds':copy.deepcopy(ROLE_SECONDS),
      'call_limits':copy.deepcopy(CALL_LIMITS),'hosts':copy.deepcopy(old['hosts']),'versions':copy.deepcopy(old['versions']),
      'project_color':copy.deepcopy(old['project_color']),'runtime_requirements':runtime}
    root.mkdir(parents=True,mode=0o700)
    authority_record=write_new(root/'rectlight-shape-authority.json',authority)
    scope={'schema':SCHEMA,'resource_profile':RESOURCE_PROFILE,'scene_profile':SCENE_PROFILE,'scope_id':sid,
      'task_id':r['task_id'],'creative_task_id':creative_task_id,'output_root':str(root),'shape_authority':authority_record,
      'budget':copy.deepcopy(BUDGET),'role_seconds':copy.deepcopy(ROLE_SECONDS),'authorization':authority['authorization'],
      'accounting':{'key_path':str(root/'.native-control/key'),'key_sha256':hashlib.sha256(key).hexdigest()},
      'execution_authorized':True,'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION','evidence_source':'real_host','host_started':False,
      'hosts':authority['hosts'],'versions':authority['versions'],'project_color':authority['project_color']}
    # 观察器/原路线仅作只读依赖；没有旧phase/continuation字段或旧tickets注入点。
    for name in ('process_image_policy','native_color_tokens','alpha_fixture'):
        if name in old:scope[name]=copy.deepcopy(old[name])
    scope_record=write_new(root/'scope.json',scope);binding={k:scope_record[k] for k in ('path','sha256')}
    native=NativeScope.initialize(binding,key=key)
    usage=native.completed_snapshot()
    if usage['dcc_starts']!=0 or usage['total_seconds']!=0 or usage['tickets']:
        raise ValueError('RECT_SHAPE_INITIAL_ACCOUNTING_NOT_EMPTY')
    validate_scope(native.scope,native.path)
    ArtifactRegistry(root/'artifact_ledger')
    media={'reference':copy.deepcopy(p['media']['reference']),
      'current':{'source':sources['current_main'],'preview':sources['current_preview'],
        'display_sha256':p['display']['sha256'],'processor_cache_id':p['display']['processor_cache_id'],
        'alpha_display':'composite_over_black_opaque'}}
    prep={'schema':PREPARATION_SCHEMA,'task_id':r['task_id'],'source_scene_task_id':r['task_id'],
      'creative_task_id':creative_task_id,'scope':binding,'target_authority':authority_record,
      'source_delivery':sources['delivery'],'source_result':sources['latest_result'],'source_preparation':sources['preparation'],
      'source_scope':sources['scope'],'source_observation_scope':object_record(sources['case_variant'])['scope'],
      'source_graph':p['source_graph'],'baseline_saved':r['saved'],'baseline_sidecars':r['save_sidecars'],
      'baseline_control':r['control'],'baseline_diagnostic':sources['baseline_diagnostic'],
      'configuration':sources['configuration'],'original_configuration':sources['configuration'],
      'case_id':'karma_lights_rectlight_v1','case_variant':sources['case_variant'],'ledger_root':authority['ledger_root'],
      'runtime_manifest':sources['runtime_manifest'],'source_runtime_manifest':sources['runtime_manifest'],
      'source_runtime_snapshot_manifest':sources['runtime_snapshot_manifest'],'runtime_requirements':runtime,
      'nuke_template':sources['nuke_template'],'alpha_binding':source['alpha_binding'],'alpha_result':sources['alpha'],
      'alpha_source':sources['alpha_source'],'alpha_relocation':{'source_plugin':source['alpha_binding']['plugin_reuse']['source_plugin'],
        'active_plugin_relative':'plugins/houdini/_impl/houdini_bridge_addon.py','shape_scope_binding':binding},
      'display':copy.deepcopy(p['display']),'media':media,'protected_files':dict(sources),
      'baseline_exposure':-0.25,'baseline_width':0.9,'baseline_height':0.9,'baseline_feedback_version':2,'baseline_main_version':0,
      'main_artifact_id':'rectlight_shape_main','supervisor_python':old['hosts']['supervisor_python']['path'],
      'worker':str(Path(__file__).resolve().parents[4]/'tools/run_rectlight_shape.py'),
      'environment':copy.deepcopy(p['environment']),
      'model_route':{'route':'CodexDelegatedMCPRoute','selected_model':'gpt-6-luna','reasoning_effort':'low','provider_identity':'unknown'},
      'initial_starts':0,'initial_seconds':0}
    # 临时与宿主状态全部归新根，OCIO/Python等原受控运行条件原样复用。
    for name in ('TMPDIR','TMP','TEMP','HOUDINI_TEMP_DIR','NUKE_TEMP_DIR'):
        prep['environment'][name]=str(root/'runtime/tmp')
    for name,relative in (('HOUDINI_USER_PREF_DIR','runtime/houdini-prefs'),('XDG_CACHE_HOME','runtime/cache'),('XDG_CONFIG_HOME','runtime/config')):
        prep['environment'][name]=str(root/relative)
    (root/'runtime/tmp').mkdir(parents=True)
    prep_record=write_new(root/'rectlight-shape-preparation.json',prep)
    return {'state':'RECT_SHAPE_PREPARED','preparation':prep_record,'scope':binding,'target_authority':authority_record,
      'creative_task_id':creative_task_id,'source_scene_task_id':r['task_id'],'ledger_root':authority['ledger_root'],
      'native_starts':0,'native_dispatch_attempted':False,'source_scope_unchanged':True}
