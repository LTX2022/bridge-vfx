"""在任务自有的新节点中恢复封存的 DiskLight 配方并核对读回结果。"""
from __future__ import annotations
import hashlib
from pathlib import Path

from .official_karma import SOP_TYPES, VERSION, canonical_sha256
from .official_karma_native import (configure_output,configure_beauty,beauty_author_readback,menu_token_write,menu_token_readback, scalar_write, native_value, parameter_value, capture_stage,
    semantic_compare, verify_output_stage, PRODUCT, SETTINGS, bounded_json)
from .official_karma_scene import (validate_configuration,load_observation,layout,SOURCE_ROLES,IMPORT_ROLES)


def parameter_recipe(configuration,roles):
    value=validate_configuration(configuration,VERSION)
    observed=load_observation(value,VERSION)
    sources={name:observed['nodes']['/stage/lights/backdrop_shallow/sopnet/create/'+name]
             for name in SOP_TYPES}
    source_roles=dict(SOURCE_ROLES)
    if 'case_variant' in value:source_roles['light']='/stage/lights/rectlight'
    sources.update({name:observed['nodes'][path] for name,path in source_roles.items()})
    sources.update({name:observed['sopcreate_import'][key] for name,key in IMPORT_ROLES.items()})
    plan=[]
    aliases={source:roles[role] for role,source in source_roles.items()}
    aliases.update({'/stage/lights/backdrop_shallow/sopnet/create/'+name:roles[name] for name in SOP_TYPES})
    for role,row in sources.items():
        for name,field in row['parameters'].items():
            values=field['value']
            if role=='geometry_import' and name=='soppath': values=[roles['reverse2']]
            elif role=='settings' and name=='picture': values=[value['scene']['output_image']]
            elif field['kind']=='String':
                values=[aliases.get(v,v) for v in values]
                if any('/stage/lights/' in v for v in values):
                    raise ValueError('OFFICIAL_SCENE_UNMAPPED_NODE_REFERENCE:'+role+'.'+name)
            plan.append({'role':role,'name':name,'field':field,'value':values})
    return observed,plan


def _target(hou,node,name,field):
    parm=node.parmTuple(name)
    if (parm is None or parm.parmTemplate().type().name()!=field['kind']
            or len(tuple(parm))!=field['components']
            or hashlib.sha256(parm.parmTemplate().asCode().encode()).hexdigest()!=field['template_sha256']):
        raise ValueError('OFFICIAL_RECONSTRUCTION_TEMPLATE_MISMATCH:'+node.path()+'.'+name)
    return parm


def _equal(expected,actual):
    if type(expected) is list and type(actual) is list:
        return len(expected)==len(actual) and all(_equal(a,b) for a,b in zip(expected,actual))
    if type(expected) is dict and type(actual) is dict:
        return set(expected)==set(actual) and all(_equal(expected[k],actual[k]) for k in expected)
    if type(expected) is float and type(actual) is float:
        return abs(expected-actual)<=1e-6
    return type(expected) is type(actual) and expected==actual


def _native_write(hou,parm,values,kind):
    """按封存值写入参数；Ramp 的实例通道先解除默认驱动和锁定。"""
    for component in parm:
        if component.isLocked():
            raise ValueError('OFFICIAL_RECONSTRUCTION_LOCKED_FIELD:'+component.path())
        component.deleteAllKeyframes()
    if kind=='Ramp':
        if len(values)!=1 or not isinstance(values[0],dict) or set(values[0])!={'ramp_basis','keys','values'}:
            raise ValueError('OFFICIAL_RECONSTRUCTION_RAMP_INVALID')
        # Ramp 的父参数可写不代表实例通道可写；默认通道驱动会覆盖前段点值。
        for child in parm[0].multiParmInstances():
            if child.isLocked():
                child.lock(False)
            child.deleteAllKeyframes()
        ramp=values[0]
        allowed={'Constant','Linear','CatmullRom','MonotoneCubic','Bezier','BSpline','Hermite'}
        if not ramp['ramp_basis'] or any(v not in allowed for v in ramp['ramp_basis']):
            raise ValueError('OFFICIAL_RECONSTRUCTION_RAMP_BASIS_INVALID')
        basis=tuple(getattr(hou.rampBasis,name) for name in ramp['ramp_basis'])
        vals=tuple(tuple(v) if isinstance(v,list) else v for v in ramp['values'])
        parm[0].set(hou.Ramp(basis,tuple(ramp['keys']),vals))
    else:
        parm.set(tuple(values),follow_parm_references=False)
    if not _equal(values,parameter_value(parm,kind)):
        raise ValueError('OFFICIAL_RECONSTRUCTION_VALUE_MISMATCH:'+parm.name())


def _add_product_name(hou,node):
    group=node.parmTemplateGroup()
    for name,typ in (('productName_control',None),('productName','token')):
        item=hou.StringParmTemplate(name,name,1,default_value=('none' if typ is None else '',))
        if typ is not None: item.setTags({'usdvaluetype':typ})
        old=group.find(name)
        if old is None: group.append(item)
        elif old.type().name()!='String' or old.numComponents()!=1:
            raise ValueError('OFFICIAL_RECONSTRUCTION_PRODUCT_TEMPLATE_CONFLICT')
    node.setParmTemplateGroup(group)


def _binding_writes(configuration,roles,observed):
    output=configuration['scene']['output_image']
    camera=next(path for path,row in observed['stage']['prims'].items() if row['type']=='Camera')
    parent=str(Path(output).parent)
    return {'settings_binding':{'primpattern':PRODUCT,'createprims':'off',
                                'productName_control':'set','productName':output},
        'render':{'rendercommand':'husk --lock-random 1','renderer':'BRAY_HdKarma','loppath':roles['beauty_binding'],'rendersettings':SETTINGS,
            'override_camera':camera,'outputimage':output,'soho_foreground':1,'husk_tpostframe':0,
            'enableoutputprocessor_savetodirectory':1,'savetodirectory_directory':parent,
            'husk_tiletempdir':parent,'lopoutput':str(Path(parent)/'main.usd')}}


def initialize(hou,configuration,roles):
    """在现有任务图内恢复官方模板、锁状态与参数，不载入或清空场景。"""
    if hou.applicationVersionString()!=VERSION or hou.frame()!=1:
        raise ValueError('OFFICIAL_RECONSTRUCTION_NATIVE_VERSION_OR_FRAME_MISMATCH')
    observed,plan=parameter_recipe(configuration,roles)
    from .official_karma_templates import restore_parameter_templates
    restore_parameter_templates(hou,configuration,roles,observed)
    # 先分配多参数实例，再写开关和分辨率模式，最后写依赖它们的数值。
    def priority(row):
        if row['field']['multiparm']: return 0
        if (row['name'].endswith('_control') or row['name'].startswith('enable')
                or row['name']=='resolutionMenu'): return 1
        return 2
    for row in sorted(plan,key=priority):
        node=hou.node(roles[row['role']]);parm=_target(hou,node,row['name'],row['field'])
        # 锁状态来自已认证观测；不把新建节点的默认锁误认为官方配方的约束。
        for component,locked in zip(parm,row['field']['locked']):
            if component.isLocked()!=locked:
                component.lock(locked)
        if not _equal(row['value'],parameter_value(parm,row['field']['kind'])):
            _native_write(hou,parm,row['value'],row['field']['kind'])
    for name in SOP_TYPES:
        node=hou.node(roles[name]); flags=observed['nodes']['/stage/lights/backdrop_shallow/sopnet/create/'+name]['flags']
        node.setDisplayFlag(flags['display']);node.setRenderFlag(flags['render'])
    author=hou.node(roles['settings_binding'])
    _add_product_name(hou,author)
    for role,values in _binding_writes(configuration,roles,observed).items():
        for name,value in values.items():
            if name=='createprims':menu_token_write(hou.node(roles[role]),name,value)
            else:scalar_write(hou.node(roles[role]),name,value)
    configure_output(hou,author)
    configure_beauty(hou,hou.node(roles['beauty_binding']))
    return readback(hou,configuration,roles)


def readback(hou,configuration,roles,candidate_patch=None):
    """核对保存前后的节点、参数、锁状态和 USD 语义，保留既有拒绝条件。"""
    configuration=validate_configuration(configuration,VERSION)
    observed,plan=parameter_recipe(configuration,roles)
    from .official_karma_feedback import expected_feedback
    observed,plan=expected_feedback(observed,plan,candidate_patch,configuration=configuration)
    nodes,wires=layout(VERSION)
    if set(roles)!={row['role'] for row in nodes}:
        raise ValueError('OFFICIAL_RECONSTRUCTION_ROLE_SET_MISMATCH')
    for row in nodes:
        node=hou.node(roles[row['role']])
        if node is None or node.type().name()!=row['types'][0]:
            raise ValueError('OFFICIAL_RECONSTRUCTION_NODE_TYPE_MISMATCH')
        if node.errors() or node.warnings():
            raise ValueError('OFFICIAL_RECONSTRUCTION_NATIVE_DIAGNOSTIC:'+row['role'])
        if row.get('parent_role') and node.parent().path()!=roles[row['parent_role']]:
            raise ValueError('OFFICIAL_RECONSTRUCTION_PARENT_MISMATCH')
    for wire in wires:
        node=hou.node(roles[wire['destination_role']])
        actual={c.inputIndex():(c.inputNode().path(),c.outputIndex()) for c in node.inputConnections()}
        if actual.get(wire['destination_input'])!=(roles[wire['source_role']],wire['source_output']):
            raise ValueError('OFFICIAL_RECONSTRUCTION_CONNECTION_MISMATCH')
    fields={}
    for row in plan:
        node=hou.node(roles[row['role']]);parm=_target(hou,node,row['name'],row['field'])
        actual=parameter_value(parm,row['field']['kind'])
        if [component.isLocked() for component in parm]!=row['field']['locked']:
            raise ValueError('OFFICIAL_RECONSTRUCTION_LOCK_STATE_DRIFT:'+row['role']+'.'+row['name'])
        if not _equal(row['value'],actual):
            raise ValueError('OFFICIAL_RECONSTRUCTION_FIELD_DRIFT:'+row['role']+'.'+row['name'])
        fields[row['role']+'.'+row['name']]=actual[0] if len(actual)==1 else actual
    for role,values in _binding_writes(configuration,roles,observed).items():
        for name,expected in values.items():
            if name=='createprims':
                menu_token_readback(hou.node(roles[role]),name,expected)
                fields[role+'.'+name]=expected
                continue
            parm=hou.node(roles[role]).parm(name)
            if parm is None or parm.keyframes() or type(parm.eval()) is not type(expected) or parm.eval()!=expected:
                raise ValueError('OFFICIAL_RECONSTRUCTION_RENDER_BINDING_DRIFT:'+role+'.'+name)
            fields[role+'.'+name]=expected
    if fields.get('geometry_import.soppath')!=roles['reverse2']:
        raise ValueError('OFFICIAL_RECONSTRUCTION_GEOMETRY_REFERENCE_DRIFT')
    for name in SOP_TYPES:
        node=hou.node(roles[name]);expected=observed['nodes']['/stage/lights/backdrop_shallow/sopnet/create/'+name]['flags']
        if node.isDisplayFlagSet()!=expected['display'] or node.isRenderFlagSet()!=expected['render']:
            raise ValueError('OFFICIAL_RECONSTRUCTION_FLAG_DRIFT:'+name)
    beauty_author_readback(hou,hou.node(roles['beauty_binding']),roles['settings_binding'])
    stage=hou.node(roles['beauty_binding']).stage(frame=1,apply_viewport_overrides=False,ignore_errors=False)
    verify_output_stage(stage,configuration['scene']['output_image'])
    actual=capture_stage(stage,case_id='karma_lights_rectlight_v1' if 'case_variant' in configuration else None)
    compared=semantic_compare(observed['stage'],actual,reference_output=observed['output'],
                              actual_output=configuration['scene']['output_image'])
    if compared['state']!='PASS':
        raise ValueError('OFFICIAL_RECONSTRUCTION_USD_SEMANTIC_MISMATCH:'+str(compared['differences']))
    return bounded_json({'configuration_sha256':canonical_sha256(configuration),'profile':configuration['profile'],
        'fields':fields,'target_frames':[1],'sealed_observation_sha256':configuration['sealed_observation']['sha256'],
        'observation_sha256':canonical_sha256(parameter_recipe(configuration,roles)[0]),'usd_comparison':compared,
        'native_geometry_validated':False,'render_executed':False,'visual_verified':False})
