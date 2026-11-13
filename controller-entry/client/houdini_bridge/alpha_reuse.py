"""复用渲染逻辑未变的原生 alpha 校准，保留原签名及原插件构建身份。"""
from __future__ import annotations

import copy
from .official_karma_observation import checked_bytes

LEGACY_RULE = 'scene_capture_limits_cache_v1'
RULE = 'scene_capture_limits_cache_incremental_scope_v1'
SCHEMA = 'bridge.alpha-plugin-reuse/1'
FEEDBACK_RULE = 'scene_capture_limits_cache_incremental_feedback_v1'
CASE_RULE = 'scene_capture_limits_cache_incremental_feedback_case_v1'
GEOMETRY_RULE = 'scene_capture_limits_cache_incremental_feedback_case_geometry_v1'


def _capture_limits_update(text):
    """只接受两处既定读取优化；渲染、颜色、alpha 及其他源码必须逐字保持。"""
    replacements = (
        (
            '    records = []\n    for node in sorted(nodes, key=lambda item: item.path()):',
            '    limits = _fx_current_capture_limits()\n    records = []\n    for node in sorted(nodes, key=lambda item: item.path()):',
            1,
        ),
        (
            'if len(parms) > _fx_current_capture_limits()["parameters_per_node"]:',
            'if len(parms) > limits["parameters_per_node"]:',
            2,
        ),
        (
            '    contract = {"schema": "houdini.task_scene_contract/2.0", "task_id": task_id,',
            '    if _fx_current_capture_limits() != limits:\n        raise BridgeCommandError("SCENE_CONTRACT_SCOPE_INVALID", "capture limits changed during native readback")\n    contract = {"schema": "houdini.task_scene_contract/2.0", "task_id": task_id,',
            1,
        ),
        (
            '    nodes, boundaries = _fx_scene_contract_nodes(owned_roots, nodes, capture_policy=capture_policy)\n    records = []',
            '    nodes, boundaries = _fx_scene_contract_nodes(owned_roots, nodes, capture_policy=capture_policy)\n    limits = _fx_current_capture_limits()\n    records = []',
            1,
        ),
        (
            '    contract = {"schema": "houdini.task_scene_contract/2.0", "task_id": str(task_id),',
            '    if _fx_current_capture_limits() != limits:\n        raise BridgeCommandError("SCENE_CONTRACT_SCOPE_INVALID", "capture limits changed during task readback")\n    contract = {"schema": "houdini.task_scene_contract/2.0", "task_id": str(task_id),',
            1,
        ),
    )
    for before, after, count in replacements:
        if text.count(before) != count:
            raise ValueError('ALPHA_REUSE_CAPTURE_TRANSFORM_MISMATCH')
        text = text.replace(before, after)
    return text


def _incremental_scope_update(text):
    """只扩展已认证官方范围的识别，不改变采集上限、宿主准入或渲染逻辑。"""
    replacements = (
        (
            '    from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE' + chr(10),
            '    # 新增量范围沿用原官方 HDA 上限，范围认证和当前宿主准入检查保持不变。' + chr(10)
            + '    from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE' + chr(10),
        ),
        (
            '    if scope.resource_profile != OFFICIAL_RESOURCE_PROFILE:' + chr(10),
            '    if scope.resource_profile not in (OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE):' + chr(10),
        ),
    )
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError('ALPHA_REUSE_INCREMENTAL_SCOPE_TRANSFORM_MISMATCH')
        text = text.replace(before, after)
    return text


def validate_plugin_reuse(value, expected_plugin_build):
    """重新读取两版源码，只接受所选规则的精确变换，拒绝其他构建的校准迁移。"""
    if (type(value) is not dict
            or set(value) != {'schema', 'rule', 'source_plugin', 'active_plugin'}
            or value['schema'] != SCHEMA or value['rule'] not in (LEGACY_RULE, RULE, FEEDBACK_RULE, CASE_RULE, GEOMETRY_RULE)):
        raise ValueError('ALPHA_REUSE_PROOF_INVALID')
    source, active = value['source_plugin'], value['active_plugin']
    if active.get('sha256') != expected_plugin_build or source.get('sha256') == expected_plugin_build:
        raise ValueError('ALPHA_REUSE_PLUGIN_BINDING_MISMATCH')
    original = checked_bytes(source).decode('utf-8')
    current = checked_bytes(active).decode('utf-8')
    expected = _capture_limits_update(original)
    if value['rule'] in (RULE, FEEDBACK_RULE, CASE_RULE, GEOMETRY_RULE):
        expected = _incremental_scope_update(expected)
    if value['rule'] in (FEEDBACK_RULE, CASE_RULE, GEOMETRY_RULE):
        from .official_karma_feedback import plugin_feedback_update
        expected = plugin_feedback_update(expected)
    if value['rule'] in (CASE_RULE, GEOMETRY_RULE):
        from .official_case_variant import plugin_case_update
        expected=plugin_case_update(expected)
    if value['rule']==GEOMETRY_RULE:
        from .geometry_render_scene import plugin_geometry_update
        expected=plugin_geometry_update(expected)
    if expected != current:
        raise ValueError('ALPHA_REUSE_RENDER_SOURCE_CHANGED')
    return copy.deepcopy(value)


def make_reuse_binding(binding, source_plugin_record, active_plugin_record):
    """为原绑定添加显式兼容来源；不更改其终态摘要、身份或签名文件。"""
    if not isinstance(binding, dict) or 'plugin_reuse' in binding:
        raise ValueError('ALPHA_REUSE_ORIGINAL_BINDING_REQUIRED')
    from .official_case_variant import PLUGIN_AFTER
    active_text=checked_bytes(active_plugin_record).decode('utf-8')
    rule=GEOMETRY_RULE if "'bounded_geometry_rig_v1'" in active_text else CASE_RULE if PLUGIN_AFTER in active_text else FEEDBACK_RULE
    proof = {'schema': SCHEMA, 'rule': rule,
             'source_plugin': source_plugin_record, 'active_plugin': active_plugin_record}
    validate_plugin_reuse(proof, active_plugin_record['sha256'])
    result = copy.deepcopy(binding)
    result['plugin_reuse'] = copy.deepcopy(proof)
    from pathlib import Path
    from .official_karma_observation import file_record
    origin = Path(source_plugin_record['path']).parents[3]
    result['calibration_source'] = file_record(
        origin / 'packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py')
    return result


def validate_output_calibration(binding, *, expected_version, expected_plugin_build,
                                expected_route_sha256, evidence_source):
    """先认证原校准，再记录受限兼容证明；当前渲染路线仍由调用方独立匹配。"""
    from dcc_task_runtime.alpha_calibration import validate_alpha_calibration
    proof = binding.get('plugin_reuse') if isinstance(binding, dict) else None
    source = binding.get('calibration_source') if isinstance(binding, dict) else None
    expected = dict(expected_version=expected_version, expected_plugin_build=expected_plugin_build,
                    expected_route_sha256=expected_route_sha256, evidence_source=evidence_source)
    if source is not None and proof is None:
        raise ValueError('ALPHA_REUSE_SOURCE_PROOF_REQUIRED')
    if proof is not None:
        from pathlib import Path
        from .official_karma_observation import file_record
        proof = validate_plugin_reuse(proof, expected_plugin_build)
        expected['expected_plugin_build'] = proof['source_plugin']['sha256']
        origin = Path(proof['source_plugin']['path']).parents[3]
        fixed = origin / 'packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py'
        if source is None or source != file_record(fixed):
            raise ValueError('ALPHA_REUSE_SOURCE_VERIFIER_REQUIRED')
    calibration = (validate_source_calibration(binding, source, **expected) if source is not None
                   else validate_alpha_calibration(binding, **expected))
    if proof is not None:
        calibration['reuse_compatibility'] = proof
    return calibration


def validate_source_calibration(binding, source_module_record, **expected):
    """用原路径执行同字节校准验证器，完整保留原固定观察器和签名核验。"""
    import hashlib
    import types
    from pathlib import Path
    from dcc_task_runtime import alpha_calibration
    raw = checked_bytes(source_module_record)
    if raw != Path(alpha_calibration.__file__).read_bytes():
        raise ValueError('ALPHA_REUSE_VERIFIER_SOURCE_CHANGED')
    # 仅执行与当前可信验证器完全相同的源码；__file__保留原观察器路径合同。
    module = types.ModuleType('dcc_task_runtime._reused_alpha_' + hashlib.sha256(raw).hexdigest())
    module.__package__ = 'dcc_task_runtime'
    module.__file__ = source_module_record['path']
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module.validate_alpha_calibration(binding, **expected)
