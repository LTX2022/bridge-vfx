"""官方RectLight等面积宽高目标：只认证本任务配置和三处有限插件适配。"""
from __future__ import annotations
import copy,json,math,os
from pathlib import Path
from .official_karma_observation import checked_bytes

WIDTH='xn__inputswidth_zta';HEIGHT='xn__inputsheight_mva'
WIDTH_GATE='xn__inputswidth_control_06a';HEIGHT_GATE='xn__inputsheight_control_n8a'
EXPOSURE='xn__inputsexposure_vya';EXPOSURE_GATE='xn__inputsexposure_control_wcb'
LIGHT='/stage/lights/rectlight';USD='/World/UsdLuxRectLight'
PACK_BEFORE='return pack_id, overlay_host_pack(pack,hou.applicationVersionString())'
PACK_AFTER='return pack_id, overlay_host_pack(pack,hou.applicationVersionString(),configuration=params.get("frozen_render_scene"))'
CHECK_BEFORE='        validate_native_feedback(hou, manifest, changes)'
CHECK_AFTER='        manifest = validate_native_feedback(hou, manifest, changes, configuration=params.get("frozen_render_scene"))'
CAPTURE_BEFORE='    if scope.resource_profile not in (OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE):'
CAPTURE_AFTER='    from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE\n    if scope.resource_profile not in (OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE, RECT_SHAPE_PROFILE):'

def plugin_shape_update(text):
    """alpha兼容仅认可控制入参、局部manifest及受监督capture三处精确变换。"""
    if text.count(PACK_BEFORE)!=1 or text.count(CHECK_BEFORE)!=1 or text.count(CAPTURE_BEFORE)!=1:
        raise ValueError('RECT_SHAPE_PLUGIN_TRANSFORM_REQUIRED')
    return text.replace(PACK_BEFORE,PACK_AFTER).replace(CHECK_BEFORE,CHECK_AFTER).replace(CAPTURE_BEFORE,CAPTURE_AFTER)

def shape_values(changes):
    """宽高必须成对、有限且等面积；不接受曝光或任意原生字段。"""
    if type(changes) is not dict or set(changes)!={'width','height'}:
        raise ValueError('RECT_SHAPE_WIDTH_HEIGHT_ONLY')
    w,h=changes['width'],changes['height']
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (w,h)):
        raise ValueError('RECT_SHAPE_FINITE_VALUES_REQUIRED')
    if not .9<=w<=1.8 or not .45<=h<=.9 or not 2<=w/h<=4 or abs(w*h-.81)>1e-6:
        raise ValueError('RECT_SHAPE_AREA_OR_BOUNDS_REQUIRED')
    return {'width':float(w),'height':float(h)}

def authority_for_configuration(configuration):
    """有效配置只能由本轮已认证新scope及原配置的精确重定位派生。"""
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
    if type(configuration) is not dict or 'rectlight_shape_target' not in configuration:
        raise ValueError('RECT_SHAPE_TARGET_CONFIGURATION_REQUIRED')
    native=NativeScope(configuration['native_scope'])
    authority_record=configuration['rectlight_shape_target']
    if native.resource_profile!=RECT_SHAPE_PROFILE or native.scope.get('shape_authority')!=authority_record:
        raise ValueError('RECT_SHAPE_SCOPE_AUTHORITY_REQUIRED')
    authority=json.loads(checked_bytes(authority_record));original=json.loads(checked_bytes(authority['sources']['configuration']))
    expected=copy.deepcopy(original);expected['native_scope']=native.binding;expected['rectlight_shape_target']=authority_record
    expected['scene']['output_image']=str(native.root/'baseline/project/saves/main.0001.exr')
    if configuration!=expected:
        raise ValueError('RECT_SHAPE_CONFIGURATION_DIFFERENCE_NOT_ALLOWED')
    return authority

def effective_configuration(preparation):
    """新任务重定位保持源配置原字节；当前输出仅落新任务根。"""
    value=json.loads(checked_bytes(preparation['configuration']));value=copy.deepcopy(value)
    value['native_scope']=preparation['scope'];value['rectlight_shape_target']=preparation['target_authority']
    value['scene']['output_image']=str(Path(preparation['scope']['path']).parent/'baseline/project/saves/main.0001.exr')
    authority_for_configuration(value)
    return value

def baseline_observation(configuration,version=None):
    """认证原官方观察，不把旧scope当当前执行权限。"""
    authority=authority_for_configuration(configuration)
    from .official_karma_scene import load_observation
    original=json.loads(checked_bytes(authority['sources']['configuration']))
    return load_observation(original,version)

def shape_contract(configuration):
    """仅授权目标配置暴露两个真实Rect宽高控制及既有set门。"""
    authority_for_configuration(configuration)
    return {name:{'role':'light','aliases':[parm],'minimum':low,'maximum':high,
                  'value_type':'float','application':'houdini','invalidates_from':'lighting',
                  'required_gates':[('light',gate,'set')]}
            for name,parm,gate,low,high in [('width',WIDTH,WIDTH_GATE,.9,1.8),('height',HEIGHT,HEIGHT_GATE,.45,.9)]}

def expected_shape_feedback(observed,plan,changes,configuration):
    """源曝光固定；只更新宽高的参数计划与USD属性，其余保持严格比较。"""
    authority_for_configuration(configuration);observed,plan=copy.deepcopy(observed),copy.deepcopy(plan)
    patch=changes or {}
    if set(patch)-{'width','height','exposure'} or 'exposure' in patch and patch['exposure']!=-.25:
        raise ValueError('RECT_SHAPE_FROZEN_EXPOSURE_REQUIRED')
    dims=shape_values({k:patch[k] for k in ('width','height') if k in patch}) if 'width' in patch or 'height' in patch else {'width':.9,'height':.9}
    values={EXPOSURE:-.25,WIDTH:dims['width'],HEIGHT:dims['height']}
    for parm,value in values.items():
        rows=[row for row in plan if row['role']=='light' and row['name']==parm]
        if len(rows)!=1:raise ValueError('RECT_SHAPE_PARAMETER_PLAN_REQUIRED')
        rows[0]['value']=[value]
    attrs=observed['stage']['prims'][USD]['attributes']
    for name,value in [('inputs:exposure',-.25),('inputs:width',dims['width']),('inputs:height',dims['height'])]:attrs[name]['value']=value
    return observed,plan

def validate_native_shape(hou,manifest,changes,configuration):
    """写入前认证当前监督scope和原场景；新配置只进入原事务的局部副本。"""
    authority=authority_for_configuration(configuration);shape_values(changes)
    if hou.applicationVersionString()!='21.0.631' or json.loads(os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING','null'))!=configuration['native_scope']:
        raise ValueError('RECT_SHAPE_NATIVE_SCOPE_REQUIRED')
    old=manifest.get('frozen_render_scene') or {};original=json.loads(checked_bytes(authority['sources']['configuration']))
    if old!=configuration:raise ValueError('RECT_SHAPE_BOUND_SOURCE_SCENE_REQUIRED')
    node=hou.node((manifest.get('nodes') or {}).get('light',''))
    if node is None or node.type().name()!='light::2.0' or node.parm('primtype').eval()!='UsdLuxRectLight':raise ValueError('RECT_SHAPE_NATIVE_RECT_REQUIRED')
    for name in (WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE,EXPOSURE,EXPOSURE_GATE):
        p=node.parm(name)
        if p is None or p.isLocked() or p.isDisabled() or p.keyframes():raise ValueError('RECT_SHAPE_NATIVE_PARAMETER_STATE')
    if any(node.parm(g).eval()!='set' for g in (WIDTH_GATE,HEIGHT_GATE,EXPOSURE_GATE)) or node.parm(EXPOSURE).eval()!=-.25:
        raise ValueError('RECT_SHAPE_NATIVE_FROZEN_VALUES')
    from dcc_task_runtime.canonical import canonical_sha256
    result=copy.deepcopy(manifest);result['frozen_render_scene']=configuration;result['frozen_render_scene_sha256']=canonical_sha256(configuration)
    return result

from contextlib import contextmanager
@contextmanager
def rebind_context(hou,node,params,addon):
    """首轮在编辑宿主内重绑输出配置；与原参数事务共用undo及完整回滚。"""
    record=params.get('official_case_configuration');configuration=json.loads(checked_bytes(record));authority=authority_for_configuration(configuration)
    if params.get('parms')!={EXPOSURE:-.25} or json.loads(os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING','null'))!=configuration['native_scope']:
        raise ValueError('RECT_SHAPE_FIXED_SOURCE_REBIND_REQUIRED')
    root,manifest=addon['_fx_manifest'](params['task_id'],root_path=addon['_root_for_path'](node.path()))
    original=json.loads(checked_bytes(authority['sources']['configuration']))
    if node.path()!=manifest['nodes']['light'] or manifest.get('frozen_render_scene') not in (original,configuration):raise ValueError('RECT_SHAPE_REBIND_SOURCE_REQUIRED')
    from .official_karma_scene_host import readback,_binding_writes
    from .official_karma_native import scalar_write,menu_token_write
    from dcc_task_runtime.canonical import canonical_sha256
    old=copy.deepcopy(manifest);roles=manifest['nodes'];before={}
    if manifest['frozen_render_scene']==original:readback(hou,original,roles,candidate_patch=manifest.get('candidate_patch'))
    observed=baseline_observation(configuration);writes=_binding_writes(configuration,roles,observed)
    # 主输出随场景合同一起重绑，并纳入同一before快照及失败回滚。
    writes.setdefault('settings',{})['picture']=configuration['scene']['output_image']
    for role,values in writes.items():
        for name in values:
            parm=hou.node(roles[role]).parm(name)
            if parm is None:raise ValueError('RECT_SHAPE_REBIND_PARAMETER_REQUIRED')
            before[(roles[role],name)]=parm.eval()
    try:
        yield
        for role,values in writes.items():
            for name,value in values.items():
                if name=='createprims':menu_token_write(hou.node(roles[role]),name,value)
                elif hou.node(roles[role]).parm(name).eval()!=value:scalar_write(hou.node(roles[role]),name,value)
        manifest.update(frozen_render_scene=configuration,frozen_render_scene_sha256=canonical_sha256(configuration))
        manifest['rectlight_shape_source_binding']={'authority':record,'source_saved_scene':authority['saved_scene_id']}
        readback(hou,configuration,roles,candidate_patch=manifest.get('candidate_patch'))
        addon['_fx_store_manifest'](root,manifest)
    except BaseException:
        for (path,name),value in before.items():hou.node(path).parm(name).set(value,follow_parm_reference=False)
        addon['_fx_store_manifest'](root,old)
        raise
