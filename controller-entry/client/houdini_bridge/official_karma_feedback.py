"""官方 DiskLight 唯一曝光控制及原生读回约束。"""
from __future__ import annotations
import copy
import math

EXPOSURE = 'xn__inputsexposure_vya'
GATE = 'xn__inputsexposure_control_wcb'
USD_LIGHT = '/World/UsdLuxDiskLight'

def exposure_value(changes):
    """仅接收一个有限曝光值，保持通用照明合同的取值范围。"""
    if not isinstance(changes, dict) or set(changes) != {'exposure'}:
        raise ValueError('OFFICIAL_FEEDBACK_EXPOSURE_ONLY')
    value = changes['exposure']
    if type(value) not in (int, float) or not math.isfinite(value) or not -30 <= value <= 30:
        raise ValueError('OFFICIAL_FEEDBACK_EXPOSURE_RANGE')
    return float(value)

def control_contract():
    """角色固定为登记图 light；不暴露任意原生字段。"""
    return {'exposure': {'role': 'light', 'aliases': [EXPOSURE], 'minimum': -30,
        'maximum': 30, 'value_type': 'float', 'application': 'houdini',
        'invalidates_from': 'lighting', 'required_gates': [('light', GATE, 'set')]}}

def candidate_write_plan(changes):
    """只写曝光值；既有 set 门必须保持，禁止顺手修改灯光类型。"""
    return [{'role': 'light', 'parm': EXPOSURE, 'value': exposure_value(changes),
        'native_type': 'float', 'require_writable': True, 'require_readback': True,
        'required_gates': [('light', GATE, 'set')]}]

def expected_feedback(observed, plan, changes, *, configuration=None):
    """以封存基线派生唯一允许差异，其余参数与 USD 属性仍严格比较。"""
    if not changes:
        return observed, plan
    value = exposure_value(changes)
    observed, plan = copy.deepcopy(observed), copy.deepcopy(plan)
    rows = [row for row in plan if row['role']=='light' and row['name']==EXPOSURE]
    rect=isinstance(configuration,dict) and 'case_variant' in configuration
    light='/stage/lights/rectlight' if rect else '/stage/lights/disklight'
    usd='/World/UsdLuxRectLight' if rect else USD_LIGHT
    if len(rows)!=1 or observed['nodes'][light]['parameters'][GATE]['value']!=['set']:
        raise ValueError('OFFICIAL_FEEDBACK_BASELINE_MISMATCH')
    rows[0]['value']=[value]
    observed['stage']['prims'][usd]['attributes']['inputs:exposure']['value']=value
    return observed, plan

# 与已校准插件相比只增加受限工程读回；不改渲染、颜色或 alpha 写出。
PLUGIN_BEFORE = """        if candidate_patch:
            raise BridgeCommandError('OFFICIAL_CASE_FEEDBACK_NOT_AUTHORIZED','official comparison has no feedback stage')
        from houdini_bridge.official_karma_scene_host import readback
        result=readback(hou,configuration,roles)"""
PLUGIN_AFTER = """        from houdini_bridge.official_karma_scene_host import readback
        result=readback(hou,configuration,roles,candidate_patch=candidate_patch)"""

def plugin_feedback_update(text):
    """alpha 兼容只承认这一段明确的保存／冷开读回扩展。"""
    if text.count(PLUGIN_BEFORE)!=1:
        raise ValueError('ALPHA_REUSE_FEEDBACK_TRANSFORM_MISMATCH')
    return text.replace(PLUGIN_BEFORE,PLUGIN_AFTER)

NATIVE_BEFORE = '    if render_domain:\n        prepared = _fx_render_domain_prepared(pack_id, changes, manifest.get("nodes") or {}, pack)'
NATIVE_AFTER = '    if pack.get("scene_profile") == "official_karma_disklight_v1":\n        from houdini_bridge.official_karma_feedback import validate_native_feedback\n        validate_native_feedback(hou, manifest, changes)\n    if render_domain:\n        prepared = _fx_render_domain_prepared(pack_id, changes, manifest.get("nodes") or {}, pack)'

def validate_native_feedback(hou, manifest, changes):
    """原生事务写入前验证实际角色、模式和无驱动状态。"""
    exposure_value(changes)
    configuration = manifest.get('frozen_render_scene') or {}
    if configuration.get('profile') != 'official_karma_disklight_v1' or hou.applicationVersionString()!='21.0.631':
        raise ValueError('OFFICIAL_FEEDBACK_SCENE_REQUIRED')
    node = hou.node((manifest.get('nodes') or {}).get('light',''))
    if node is None or node.type().name()!='light::2.0':
        raise ValueError('OFFICIAL_FEEDBACK_LIGHT_TYPE')
    for name in (EXPOSURE,GATE):
        parm=node.parm(name)
        if parm is None or parm.isLocked() or parm.isDisabled() or parm.keyframes():
            raise ValueError('OFFICIAL_FEEDBACK_PARAMETER_STATE')
    if node.parm(GATE).eval()!='set':
        raise ValueError('OFFICIAL_FEEDBACK_GATE_REQUIRED')

_original_plugin_feedback_update = plugin_feedback_update
def plugin_feedback_update(text):
    """只接受官方反馈读回与写入前检查两段确定变换。"""
    text = _original_plugin_feedback_update(text)
    if text.count(NATIVE_BEFORE)!=1:
        raise ValueError('ALPHA_REUSE_FEEDBACK_NATIVE_TRANSFORM_MISMATCH')
    return text.replace(NATIVE_BEFORE,NATIVE_AFTER)
