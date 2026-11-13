"""只支持已核实官方RectLight分支的来源、有限迁移和逐字段读回。"""
from __future__ import annotations
from contextlib import contextmanager
import copy,json,os,re
from pathlib import Path
from .official_karma import _index,SOURCE_HIP_SHA256,canonical_sha256
from .official_karma_observation import checked_bytes,file_record

CASE_ID='karma_lights_rectlight_v1'
LIGHT='/stage/lights/rectlight'
USD='/World/UsdLuxRectLight'
RADIUS='xn__inputsradius_mva'
WIDTH='xn__inputswidth_zta'
HEIGHT='xn__inputsheight_mva'
EXPOSURE='xn__inputsexposure_vya'
CHANGES={'lighttype':4,'primpath':USD,'primtype':'UsdLuxRectLight',RADIUS:.5,WIDTH:.9,HEIGHT:.9,EXPOSURE:0.}
PLUGIN_BEFORE='''            with _undo("Houdini Bridge set parameters"):
                values = _set_parms(node, changes)'''
PLUGIN_AFTER='''            with _undo("Houdini Bridge set parameters"):
                # 只有当前跨案例范围认证的固定迁移能同步更新工程来源合同。
                from houdini_bridge.official_case_variant import transition_context
                with transition_context(hou,node,params,globals()):
                    values = _set_parms(node, changes)'''

def plugin_case_update(text):
    """兼容证明只接受既有编辑围栏中的精确上下文扩展。"""
    if text.count(PLUGIN_BEFORE)!=1:raise ValueError('ALPHA_REUSE_CASE_TRANSFORM_MISMATCH')
    return text.replace(PLUGIN_BEFORE,PLUGIN_AFTER)

def inspect_contract(original,base_configuration,base_hip,official_hip):
    """只读CPIO原件，固定两分支全部参数差异，不执行HIP表达式。"""
    raw=checked_bytes(original)
    if original['sha256']!=SOURCE_HIP_SHA256:raise ValueError('RECT_ORIGINAL_SOURCE_REQUIRED')
    index=_index(raw)
    configuration=json.loads(checked_bytes(base_configuration));template_record=configuration['parameter_templates']
    templates=json.loads(checked_bytes(template_record));dialog=''.join(templates['roles']['light']['dialog_lines'])
    menu=re.search(r'name\s+"lighttype".*?menu\s*\{(.*?)\}',dialog,re.S)
    tokens=re.findall(r'^\s*"([^"\n]+)"\s+"[^"\n]+"',menu[1],re.M) if menu else []
    expected=['UsdLuxCylinderLight','UsdLuxDistantLight','UsdLuxDiskLight','point','UsdLuxRectLight','UsdLuxSphereLight']
    if tokens!=expected or tokens.index('UsdLuxRectLight')!=CHANGES['lighttype']:raise ValueError('RECT_STATIC_MENU_MAPPING_REQUIRED')
    def member(name):
        row=index[name];return raw[row['offset']:row['offset']+row['bytes']].decode()
    def fields(name):
        text=member('stage/lights/'+name+'.parm')
        return {m[1]:m[0] for m in re.finditer(r'^(\w+)\t+\[[^\n]*\]\t+\([^\n]*\)$',text,re.M)}
    disk,rect=fields('disklight'),fields('rectlight')
    expected={'lighttype','t',RADIUS,WIDTH,HEIGHT}
    if set(disk)!=set(rect) or {n for n in disk if disk[n]!=rect[n]}!=expected:
        raise ValueError('RECT_SOURCE_DIFFERENCE_NOT_WHITELISTED')
    # 保存值与相关驱动原件同时绑定，实际frame1数值还必须由原生观察核对。
    snippets={'lighttype':'UsdLuxRectLight',RADIUS:'0.5',WIDTH:'0.9',HEIGHT:'0.9'}
    if any(v not in rect[k] for k,v in snippets.items()):raise ValueError('RECT_SOURCE_VALUE_MISMATCH')
    for name,parent in [('rectlight','transform3'),('render_rectlight','rectlight')]:
        text=member('stage/lights/'+name+'.def')
        if not re.search(r'^0\s+'+parent+r'\s+0\s+1$',text,re.M):raise ValueError('RECT_SOURCE_BRANCH_MISMATCH')
    names=['stage/lights/'+n+s for n in ('rectlight','disklight','render_rectlight','render_disklight','switch3') for s in ('.init','.def','.parm','.chn') if 'stage/lights/'+n+s in index]
    return {'schema':'bridge.official-rectlight-source/1','case_id':CASE_ID,'source_hip':original,
        'branch':LIGHT,'render_branch':'/stage/lights/render_rectlight','switch_input':0,
        'usd_light':USD,'usd_type':'RectLight','members':{n:index[n] for n in names},
        'parameter_differences':{n:{'disk':disk[n],'rect':rect[n]} for n in sorted(expected)},
        'transition_parameters':CHANGES,'menu_template':template_record,'light_menu_tokens':tokens,'base_configuration':base_configuration,'base_hip':base_hip,'official_work_hip':official_hip}

def validate_contract(record):
    value=json.loads(checked_bytes(record))
    expected=inspect_contract(value['source_hip'],value['base_configuration'],value['base_hip'],value['official_work_hip'])
    if value!=expected:raise ValueError('RECT_CASE_CONTRACT_CHANGED')
    for key in ('base_configuration','base_hip','official_work_hip'):checked_bytes(value[key])
    return value

def expected_light_parameters(observed):
    """静态来源白名单仅改变受控实值与原本由lighttype求值的两个prim字段。"""
    value=copy.deepcopy(observed['nodes']['/stage/lights/disklight']['parameters'])
    for name,number in CHANGES.items():value[name]['value']=[number]
    value['primpath']['value']=[USD]
    return value

def common_stage(stage):
    """去除唯一光源后用于共同几何/相机/渲染语义的严格对照。"""
    value=copy.deepcopy(stage)
    value['prims']={p:r for p,r in value['prims'].items() if p not in ('/World/UsdLuxDiskLight',USD)}
    return value

def variant_payload(configuration):
    """重新认证官方原生观察及可信停止，配置不能自报RectLight成功。"""
    from dcc_task_runtime import owned_process
    from dcc_task_runtime.native_scope import NativeScope
    record=configuration['case_variant'];variant=json.loads(checked_bytes(record))
    fields={'schema','case_id','contract','scope','directory','identity','observation','hip','usd','reference','reference_render'}
    if set(variant)!=fields or variant['schema']!='bridge.official-case-variant/1' or variant['case_id']!=CASE_ID:
        raise ValueError('RECT_CASE_VARIANT_REQUIRED')
    scope=NativeScope(configuration['native_scope']);phase=scope.scope.get('creative_phase',{})
    if phase.get('schema')!='bridge.official-case-creative-phase/1' or phase.get('case_contract')!=variant['contract'] or variant['scope']!=scope.binding:
        raise ValueError('RECT_CASE_SCOPE_MISMATCH')
    contract=validate_contract(variant['contract'])
    directory=Path(variant['directory']);identity=variant['identity']
    started=owned_process.read_receipt(directory,'started',identity=identity)
    stopped=owned_process.read_receipt(directory,'stopped',identity=identity)
    fact=owned_process.read_receipt(directory,'official-rectlight-observation',identity=identity)
    tickets=scope.snapshot()['tickets']
    selected=[t for t in tickets if t['directory']==str(directory) and t['identity']==identity and t['role']=='houdini-host']
    if (len(selected)!=1 or selected[0].get('stopped_at') is None or not started or not stopped or not fact
            or owned_process.execution_returncode(stopped)!=0 or stopped.get('stop_reason') is not None
            or fact.get('scope_binding')!=scope.binding or fact.get('case_contract')!=variant['contract']
            or fact.get('started_sha256')!=canonical_sha256(started) or fact.get('captured_pid')!=started['pid']
            or any(fact.get(k)!=variant[k] for k in ('observation','hip','usd'))):
        raise ValueError('RECT_SIGNED_SOURCE_STOP_REQUIRED')
    for key in ('observation','hip','usd','reference'):checked_bytes(variant[key])
    observed=json.loads(checked_bytes(variant['observation']))
    if observed.get('case_id')!=CASE_ID or observed.get('source_contract')!=variant['contract'] or observed.get('switch_input')!=0:
        raise ValueError('RECT_OBSERVATION_CASE_MISMATCH')
    rendering=variant['reference_render'];render_dir=Path(rendering['directory']);rid=rendering['identity']
    rstopped=owned_process.read_receipt(render_dir,'stopped',identity=rid)
    rstarted=owned_process.read_receipt(render_dir,'started',identity=rid)
    intent=json.loads((render_dir/'intent.json').read_text())
    rt=[t for t in tickets if t['directory']==str(render_dir) and t['identity']==rid and t['role']=='official-case-husk']
    command=intent.get('command',[])
    if (len(rt)!=1 or rt[0].get('stopped_at') is None or not rstopped or not rstarted
            or owned_process.execution_returncode(rstopped)!=0 or rstopped.get('stop_reason') is not None
            or command[0]!=scope.scope['hosts']['husk']['path'] or command[-1]!=variant['usd']['path']
            or intent['resource_budget']['native_scope']!=scope.binding
            or rstarted['argv_sha256']!=canonical_sha256(command)
            or observed['output']!=variant['reference']['path']):
        raise ValueError('RECT_REFERENCE_RENDER_REQUIRED')
    return variant,contract,observed

def apply_observation(configuration,base):
    """原始Disk共同上游保持来源认证，实际Rect原生观察只替代对应灯光与stage。"""
    variant,contract,rect=variant_payload(configuration)
    if rect['light_parameters']!=expected_light_parameters(base):raise ValueError('RECT_NATIVE_PARAMETERS_MISMATCH')
    from .official_karma_native import semantic_compare
    check=semantic_compare(common_stage(base['stage']),common_stage(rect['stage']),reference_output=base['output'],actual_output=rect['output'])
    if check['state']!='PASS':raise ValueError('RECT_COMMON_UPSTREAM_MISMATCH:'+str(check['differences']))
    result=copy.deepcopy(base)
    result['nodes'][LIGHT]=result['nodes'].pop('/stage/lights/disklight')
    result['nodes'][LIGHT]['parameters']=rect['light_parameters']
    result['stage']=rect['stage'];result['output']=rect['output']
    return result

@contextmanager
def transition_context(hou,node,params,addon):
    """沿用typed编辑及租约围栏，只允许已认证新case的固定迁移并原生核验。"""
    record=params.get('official_case_configuration')
    if record is None:
        yield;return
    from dcc_task_runtime.native_scope import NativeScope
    from .official_karma_scene_host import readback,_binding_writes,_native_write,_equal
    from .official_karma_native import scalar_write,menu_token_write
    from .official_karma_scene import validate_configuration
    configuration=validate_configuration(json.loads(checked_bytes(record)))
    variant_payload(configuration)
    active=NativeScope(json.loads(os.environ['BRIDGE_NATIVE_SCOPE_BINDING']))
    if active.binding!=configuration['native_scope'] or params.get('parms')!=CHANGES or hou.applicationVersionString()!='21.0.631':
        raise ValueError('RECT_FIXED_TRANSITION_REQUIRED')
    root,manifest=addon['_fx_manifest'](params['task_id'],root_path=addon['_root_for_path'](node.path()))
    if node.path()!=manifest['nodes']['light'] or 'case_variant' in manifest['frozen_render_scene']:
        raise ValueError('RECT_TRANSITION_SOURCE_REQUIRED')
    old=copy.deepcopy(manifest);oldconfig=old['frozen_render_scene']
    readback(hou,oldconfig,manifest['nodes'],candidate_patch=old.get('candidate_patch'))
    from .official_karma_native import menu_token_readback
    menu_token_readback(node,'lighttype','UsdLuxDiskLight')
    if tuple(node.parm('lighttype').menuItems())[CHANGES['lighttype']]!='UsdLuxRectLight':raise ValueError('RECT_MENU_TOKEN_MAPPING_REQUIRED')
    # 先保存所有可能变更的字段，异常时恢复；原件文件和旧登记不参与写入。
    roles=manifest['nodes'];writes=_binding_writes(configuration,roles,apply_observation(configuration,__import__('houdini_bridge.official_karma_scene',fromlist=['load_observation']).load_observation(oldconfig)))
    targets={roles['light']:{k:node.parm(k).eval() for k in CHANGES}}
    targets[roles['settings']]={'picture':hou.node(roles['settings']).parm('picture').eval()}
    for role,values in writes.items():targets[roles[role]]={k:hou.node(roles[role]).parm(k).eval() for k in values}
    try:
        yield
        menu_token_readback(node,'lighttype','UsdLuxRectLight')
        scalar_write(hou.node(roles['settings']),'picture',configuration['scene']['output_image'])
        for role,values in writes.items():
            for name,value in values.items():
                if name=='createprims':menu_token_write(hou.node(roles[role]),name,value)
                else:scalar_write(hou.node(roles[role]),name,value)
        proof=readback(hou,configuration,roles)
        manifest.update(frozen_render_scene=configuration,frozen_render_scene_sha256=canonical_sha256(configuration),candidate_patch={},native_initialization=proof)
        manifest['official_case_transition']={'case_id':CASE_ID,'configuration':record,'source_configuration_sha256':canonical_sha256(oldconfig),'native_readback':proof}
        addon['_fx_store_manifest'](root,manifest)
    except BaseException:
        for path,values in targets.items():
            for name,value in values.items():hou.node(path).parm(name).set(value,follow_parm_reference=False)
        addon['_fx_store_manifest'](root,old)
        raise


def verified_reopen_parameters(result,saved,configuration,expected_identity,names):
    """直接复用本次真实冷开已验证的冻结字段，不重复触发整场景inspect。"""
    from .operation_receipts import operation_receipt_sha256
    transition=result.get('scene_transition') or {};frozen=result.get('frozen_scene_parameters') or {}
    stable=('task_id','pid','launch_nonce','plugin_build','process_generation','session_id')
    identity=transition.get('after_identity') or {}
    if (not isinstance(expected_identity,dict) or any(identity.get(k)!=expected_identity.get(k) or identity.get(k) is None for k in stable)
            or result.get('path')!=saved['path'] or result.get('sha256')!=saved['sha256']
            or result.get('scene_contract_sha256')!=saved['scene_contract_sha256']
            or canonical_sha256(saved['scene_contract'])!=saved['scene_contract_sha256']
            or frozen!=saved['scene_contract'].get('frozen_scene_parameters')
            or transition.get('loaded_snapshot',{}).get('sha256')!=saved['sha256']
            or transition.get('result',{}).get('sha256')!=saved['sha256']
            or transition.get('after_identity',{}).get('launch_nonce')==saved.get('operation_receipt',{}).get('host_identity',{}).get('launch_nonce')
            or any(result.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))
            or result.get('structure_verified')!=len(saved['scene_contract']['nodes']) or result.get('load_warnings')!=[]
            or transition.get('schema')!='bridge.houdini.scene-transition-operation/1.0'
            or transition.get('state')!='COMPLETED' or transition.get('command')!='scene.reopen_task_hip' or transition.get('load_count')!=1
            or transition.get('operation_receipt_sha256')!=operation_receipt_sha256(transition)
            or transition.get('scene_contract_sha256')!=saved['scene_contract_sha256']
            or frozen.get('configuration_sha256')!=canonical_sha256(configuration)
            or frozen.get('usd_comparison',{}).get('state')!='PASS' or frozen.get('target_frames')!=[1]):
        raise ValueError('RECT_ACTUAL_REOPEN_FACT_REQUIRED')
    values={name:frozen['fields']['light.'+name] for name in names}
    if frozen['fields'].get('light.lighttype')!=4 or frozen['fields'].get('light.primpath')!=USD or frozen['fields'].get('light.primtype')!='UsdLuxRectLight':
        raise ValueError('RECT_REOPEN_CASE_MISMATCH')
    return {'parms':values,'source':'verified_native_reopen','reopen_operation_id':transition['operation_id'],'reopen_receipt_sha256':transition['operation_receipt_sha256'],'hip_sha256':result['sha256']}
