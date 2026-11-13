"""Fixed registered graph and sealed input schema for the H21 DiskLight case.

The graph uses the original 22 SOP recipes and the native SOPCreate import /
transform / payload operators. It creates neither materials nor shaders.
"""
from __future__ import annotations
import copy
import re
from pathlib import Path

from dcc_task_runtime.render_profiles import OFFICIAL
from .official_karma import SOP_TYPES, VERSION, RESOLUTION

SCHEMA = 'bridge.official-karma-scene/1'
DOMAIN = 'lighting_camera_render_v1'
SOP_WIRES = (
 ('reverse2','output0',0), ('merge1','null1',0), ('grid1','polyextrude1',0),
 ('grid1','merge1',0), ('polyextrude1','polyextrude2',0), ('polyextrude2','reverse1',0),
 ('group1','polyextrude3',0), ('color2','polyextrude4',0), ('polyextrude4','reverse2',0),
 ('group2','group1',0), ('grid2','group2',0), ('sort1','grouprange1',0),
 ('group3','sort1',0), ('group5','group3',0), ('group4','sort2',0),
 ('polyextrude3','group4',0), ('polyextrude3','group5',0),
 ('grouprange1','group6',0), ('group6','color1',0), ('color1','color2',0),
)
LOP_TYPES = {
 'geometry_import':'sopimport','geometry_payloadinfo':'loftpayloadinfo','geometry_transform':'xform',
 'camera':'camera','settings':'karmarenderproperties','camera_transform':'xform',
 'light':'light::2.0','settings_binding':'editproperties','beauty_binding':'editproperties',
}
SOURCE_ROLES = {
 'camera':'/stage/lights/camera1','settings':'/stage/lights/karmarendersettings',
 'camera_transform':'/stage/lights/transform3','light':'/stage/lights/disklight',
}
IMPORT_ROLES = {'geometry_import':'sopimport','geometry_transform':'xform','geometry_payloadinfo':'loftpayloadinfo1'}


def layout(version):
    if version != VERSION:
        raise ValueError('OFFICIAL_SCENE_VERSION_UNSUPPORTED')
    nodes = [{'role':name,'category':'obj','types':[typ],'required_parms':[]}
             for name,typ in (('geometry_network','geo'),('usd_network','lopnet'),('render_network','ropnet'))]
    nodes += [{'role':name,'category':'sop','types':[typ],'parent_role':'geometry_network','required_parms':[]}
              for name,typ in SOP_TYPES.items()]
    nodes += [{'role':name,'category':'lop','types':[typ],'parent_role':'usd_network','required_parms':[]}
              for name,typ in LOP_TYPES.items()]
    nodes += [{'role':'render','category':'rop','types':['usdrender'],'parent_role':'render_network',
               'required_parms':[['loppath'],['renderer'],['rendersettings'],['outputimage'],['execute']]}]
    wires = [{'source_role':a,'source_output':0,'destination_role':b,'destination_input':i,'require_same_parent':True}
             for a,b,i in SOP_WIRES]
    lops = tuple(LOP_TYPES)
    wires += [{'source_role':a,'source_output':0,'destination_role':b,'destination_input':0,'require_same_parent':True}
              for a,b in zip(lops,lops[1:])]
    return copy.deepcopy(nodes),copy.deepcopy(wires)


def _binding(value,fields,label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('OFFICIAL_SCENE_'+label+'_INVALID')
    digest=value.get('sha256')
    if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}',digest):
        raise ValueError('OFFICIAL_SCENE_'+label+'_INVALID')
    key='directory' if 'directory' in fields else 'path'
    if type(value[key]) is not str or ('identity' in fields and (type(value['identity']) is not dict or not value['identity'])):
        raise ValueError('OFFICIAL_SCENE_'+label+'_INVALID')
    path=Path(value[key])
    if not path.is_absolute() or path != path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('OFFICIAL_SCENE_'+label+'_INVALID')


def validate_configuration(value,version=None):
    from .official_karma_native import bounded_json
    value=bounded_json(value)
    required={'schema','profile','supported_versions','source_contract','native_scope','sealed_observation','scene'}
    if (not required.issubset(value) or not (set(value)-required).issubset({'observation_scope','parameter_templates','case_variant','rectlight_shape_target'})
            or value['schema'] != SCHEMA or value['profile'] != OFFICIAL
            or value['supported_versions'] != [VERSION] or version not in (None,VERSION)):
        raise ValueError('OFFICIAL_SCENE_CONFIGURATION_INVALID')
    _binding(value['source_contract'],('path','bytes','sha256'),'SOURCE_CONTRACT')
    if type(value['source_contract']['bytes']) is not int or not 0 < value['source_contract']['bytes'] <= 2*1024*1024:
        raise ValueError('OFFICIAL_SCENE_SOURCE_CONTRACT_INVALID')
    _binding(value['native_scope'],('path','sha256'),'SCOPE')
    if 'observation_scope' in value:
        _binding(value['observation_scope'],('path','sha256'),'OBSERVATION_SCOPE')
    _binding(value['sealed_observation'],('directory','identity','sha256'),'SEALED_OBSERVATION')
    if 'parameter_templates' in value:
        _binding(value['parameter_templates'],('path','bytes','sha256'),'PARAMETER_TEMPLATES')
        size=value['parameter_templates']['bytes']
        if type(size) is not int or not 0<size<=8*1024*1024:
            raise ValueError('OFFICIAL_SCENE_PARAMETER_TEMPLATES_INVALID')
    if 'case_variant' in value:
        _binding(value['case_variant'],('path','bytes','sha256'),'CASE_VARIANT')
    if 'rectlight_shape_target' in value:
        _binding(value['rectlight_shape_target'],('path','bytes','sha256'),'RECT_SHAPE_TARGET')
    scene=value['scene']
    if (type(scene) is not dict or set(scene) != {'engine','resolution','frames','output_image'}
            or scene['engine'] != 'Karma CPU' or scene['resolution'] != RESOLUTION
            or any(type(v) is not int for v in scene['resolution']) or scene['frames'] != [1]
            or type(scene['frames'][0]) is not int):
        raise ValueError('OFFICIAL_SCENE_RENDER_CONTRACT_INVALID')
    if type(scene['output_image']) is not str:
        raise ValueError('OFFICIAL_SCENE_OUTPUT_PATH_INVALID')
    path=Path(scene['output_image'])
    if (not path.is_absolute() or path != path.resolve() or not str(path).endswith('.0001.exr')
            or any(p.is_symlink() for p in (path,*path.parents))):
        raise ValueError('OFFICIAL_SCENE_OUTPUT_PATH_INVALID')
    return value


def load_observation(configuration,version=None):
    """新案例只复用已认证历史观察，旧Disk默认仍执行原完整验证。"""
    value=validate_configuration(configuration,version)
    if 'rectlight_shape_target' in value:
        from .rectlight_shape_target import baseline_observation
        return baseline_observation(value,version)
    if 'case_variant' in value:
        from .case_source_cache import cached_case_observation
        return cached_case_observation(value,version,_load_observation)
    return _load_observation(value,version)


def _load_observation(configuration,version=None):
    from .official_karma_templates import read_source_observation
    value=validate_configuration(configuration,version)
    # 来源范围只认证既有观测；新范围仍独立约束当前任务、输出目录和资源。
    observed=read_source_observation(value)
    if observed['source_contract_sha256'] != value['source_contract']['sha256']:
        raise ValueError('OFFICIAL_SCENE_SEALED_SOURCE_MISMATCH')
    # 当前执行范围提供路径权限，不能借复用旧观测把输出写到旧关闭范围。
    from dcc_task_runtime.native_scope import NativeScope
    native_scope=NativeScope(value['native_scope']).scope
    if value['source_contract']!=native_scope['official_case']['source_contract']:
        raise ValueError('OFFICIAL_SCENE_SOURCE_CONTRACT_RECORD_MISMATCH')
    root=Path(native_scope['output_root'])
    allowed=root/'project'/'saves'
    if 'case_variant' in value:
        from .official_case_variant import apply_observation
        observed=apply_observation(value,observed)
        phase=native_scope['creative_phase']
        allowed=Path(phase['case_contract']['path']).parent/'baseline/project/saves'
    if not Path(value['scene']['output_image']).is_relative_to(allowed):
        raise ValueError('OFFICIAL_SCENE_OUTPUT_OUTSIDE_FROZEN_PROJECT')
    return observed


def overlay_host_pack(base,version,configuration=None):
    nodes,wires=layout(version)
    pack=copy.deepcopy(base)
    from .official_karma_feedback import control_contract
    pack.update(nodes=nodes,connections=wires,controls=control_contract(configuration),native_version=version,
                native_plan_schema='bridge.official-karma-domain/1',scene_profile=OFFICIAL)
    return pack
