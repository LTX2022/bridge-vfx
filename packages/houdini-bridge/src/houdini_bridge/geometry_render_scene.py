"""有限模型几何与已验Karma通用rig的配置、来源及只读几何事实。"""
from __future__ import annotations
import copy, hashlib, json, math
from .official_karma_observation import checked_bytes

SCHEMA = 'bridge.geometry-render-scene/1'
PROFILE = 'bounded_geometry_rig_v1'
VERSION = '21.0.631'
CONTRACT_SHA256 = hashlib.sha256(b'bridge.bounded-geometry-rig/1:H21.0.631:420x300:RGBA:ACEScg:frame1').hexdigest()


def _source(record):
    """每次读取原配置身份；原配置不因新几何或分辨率调整而改写。"""
    if not isinstance(record, dict) or set(record) != {'path','bytes','sha256'}:
        raise ValueError('GEOMETRY_RIG_SOURCE_RECORD_REQUIRED')
    from .native_render_scene import validate_configuration as validate_native
    source = json.loads(checked_bytes(record))
    if source.get('profile') != 'sphere_ground_v2':
        raise ValueError('GEOMETRY_RIG_SOURCE_PROFILE_REQUIRED')
    return validate_native(source, VERSION)


def _scene(source):
    scene = copy.deepcopy(source['scene'])
    del scene['sphere']
    scene['resolution'] = [420, 300]
    scene['frames'] = [1]
    return scene


def from_source(record):
    """复用源rig，仅显式调整新profile的输出尺寸，不生成模型几何。"""
    return validate_configuration({'schema':SCHEMA, 'profile':PROFILE,
        'supported_versions':[VERSION], 'source_rig':copy.deepcopy(record),
        'source_contract_sha256':CONTRACT_SHA256, 'scene':_scene(_source(record))}, VERSION)


def validate_configuration(value, version=None):
    """只接受本profile和原rig派生的完整场景；不可塞入另一套渲染配置。"""
    fields = {'schema','profile','supported_versions','source_rig','source_contract_sha256','scene'}
    if (not isinstance(value,dict) or set(value)!=fields or value['schema']!=SCHEMA
            or value['profile']!=PROFILE or value['supported_versions']!=[VERSION]
            or value['source_contract_sha256']!=CONTRACT_SHA256
            or version is not None and version!=VERSION):
        raise ValueError('GEOMETRY_RENDER_CONFIGURATION_REQUIRED')
    from dcc_task_runtime.canonical import canonical_sha256
    if canonical_sha256(value['scene']) != canonical_sha256(_scene(_source(value['source_rig']))):
        raise ValueError('GEOMETRY_RENDER_RIG_CHANGED')
    return copy.deepcopy(value)


def parameter_plan(config, version, *, revision=2):
    """复用原生rig参数写入，严格排除原Sphere source参数。"""
    from .native_render_scene import parameter_plan as native_plan
    value=validate_configuration(config,version)
    plan=native_plan(_source(value['source_rig']), version, revision=revision)
    plan=[copy.deepcopy(w) for w in plan if w['role']!='source']
    for w in plan:
        if w['parm']=='resolution' and w['role'] in ('settings','settings_binding'):
            w['value']=(420,300)
    return plan


def overlay_pack(pack):
    """角色source只接受模型输出null；旧材质rig的其他接口保持原合同。"""
    result=copy.deepcopy(pack)
    selected=[r for r in result['nodes'] if r['role']=='source']
    if len(selected)!=1 or selected[0]['types']!=['sphere']:
        raise ValueError('GEOMETRY_RIG_SOURCE_ROLE_REQUIRED')
    selected[0]['types']=['null']
    selected[0]['required_parms']=[]
    result['scene_profile']=PROFILE
    return result


def observe_geometry(hou, roles):
    """从实际输出读取有界世界空间点、面和连通部件，不预测模型几何。"""
    source=hou.node(roles.get('source',''))
    network=hou.node(roles.get('geometry_network',''))
    if (source is None or network is None or source.parent()!=network
            or source.type().name()!='null'):
        raise ValueError('GEOMETRY_OBSERVATION_SOURCE_REQUIRED')
    geometry=source.geometry()
    points=geometry.points();prims=geometry.prims()
    if not 1<=len(points)<=256 or not 1<=len(prims)<=256:
        raise ValueError('GEOMETRY_OBSERVATION_SIZE_REQUIRED')
    matrix=network.worldTransform()
    positions=[]
    for index,point in enumerate(points):
        if point.number()!=index:
            raise ValueError('GEOMETRY_OBSERVATION_POINT_ORDER_REQUIRED')
        position=[float(v) for v in point.position()*matrix]
        if len(position)!=3 or any(not math.isfinite(v) or abs(v)>10000 for v in position):
            raise ValueError('GEOMETRY_OBSERVATION_FINITE_REQUIRED')
        positions.append(position)
    faces=[];parents=list(range(len(points)))
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for prim in prims:
        if str(prim.type()).rsplit('.',1)[-1]!='Polygon':
            raise ValueError('GEOMETRY_OBSERVATION_POLYGON_REQUIRED')
        vertices=[v.point().number() for v in prim.vertices()]
        if not 3<=len(vertices)<=16 or len(set(vertices))!=len(vertices):
            raise ValueError('GEOMETRY_OBSERVATION_FACE_REQUIRED')
        faces.append(vertices)
        for i in vertices[1:]:parents[root(i)]=root(vertices[0])
    groups={}
    for i in range(len(points)):groups.setdefault(root(i),[]).append(i)
    def bounds(indices):
        return {'minimum':[min(positions[i][axis] for i in indices) for axis in range(3)],
                'maximum':[max(positions[i][axis] for i in indices) for axis in range(3)]}
    components=[{'point_indices':indices,'point_count':len(indices),
        'primitive_count':sum(face[0] in indices for face in faces),'bounds':bounds(indices)} for indices in groups.values()]
    components.sort(key=lambda c:c['bounds']['minimum'])
    body={'schema':'bridge.geometry-observation/1','source_path':source.path(),
        'points':positions,'faces':faces,'components':components,'bounds':bounds(range(len(points))),
        'point_count':len(points),'primitive_count':len(prims),'frame':float(hou.frame()),
        'space':'world','units':'metres','up_axis':'Y'}
    from dcc_task_runtime.canonical import canonical_sha256
    body['geometry_sha256']=canonical_sha256(body)
    return body


# 与已校准插件相比，限定为新几何身份/初始化/只读观察的逐字变换。
# 不修改render.start、writer启动、颜色转换、过滤器或alpha写出实现。
ADDON_REPLACEMENTS = (
('''    return pack_id, pack


def _fx_category''', '''    if (params.get('frozen_render_scene') or {}).get('profile') == 'bounded_geometry_rig_v1':
        from houdini_bridge.geometry_render_scene import overlay_pack
        if pack_id != 'material_lookdev_v1':
            raise BridgeCommandError('STATIC_RENDER_SCENE_REQUIRED', 'geometry rig requires its material domain')
        pack = overlay_pack(pack)
    return pack_id, pack


def _fx_category'''),
("    if configuration['profile'] == 'sphere_ground_v2':\n        geometry = '/World/'", "    if configuration['profile'] in ('sphere_ground_v2', 'bounded_geometry_rig_v1'):\n        geometry = '/World/'"),
("('geometry_import','pathprefix',geometry+'/Sphere','string','value'),", "('geometry_import','pathprefix',geometry+('/Model' if configuration['profile']=='bounded_geometry_rig_v1' else '/Sphere'),'string','value'),"),
("for name,import_role,source_role in [('Sphere','geometry_import','source'),('Ground','ground_import','ground')]:", "for name,import_role,source_role in [('Model' if configuration['profile']=='bounded_geometry_rig_v1' else 'Sphere','geometry_import','source'),('Ground','ground_import','ground')]:"),
("    roles = {node.node_id:expected[node.address] for node in compiled.nodes}\n", "    roles = {node.node_id:expected[node.address] for node in compiled.nodes}\n    if selector.get('scene_profile') == 'bounded_geometry_rig_v1':\n        from vfx_pipeline.geometry_graph import role_nodes\n        roles = {role:row['path'] for role,row in role_nodes(compiled,root_path).items()}\n"),
("if configuration is not None and configuration.get('profile') == 'sphere_ground_v2' else None)", "if configuration is not None and configuration.get('profile') in ('sphere_ground_v2', 'bounded_geometry_rig_v1') else None)"),
("enabled=(configuration is not None and configuration.get('profile') == 'sphere_ground_v2'\n", "enabled=(configuration is not None and configuration.get('profile') in ('sphere_ground_v2', 'bounded_geometry_rig_v1')\n"),
("    exact_nodes = {address.rsplit(\"/\", 1)[-1]: path for address, path in node_map.items()}\n", "    exact_nodes = {address.rsplit(\"/\", 1)[-1]: path for address, path in node_map.items()}\n    if (schedule or {}).get('identity',{}).get('scene_profile') == 'bounded_geometry_rig_v1':\n        from vfx_pipeline.geometry_graph import role_nodes\n        exact_nodes = {role:row['path'] for role,row in role_nodes(compiled,graph_root).items()}\n"),
("            result.update(input_names=list(node.inputNames()),output_names=list(node.outputNames()))\n        return result\n", "            result.update(input_names=list(node.inputNames()),output_names=list(node.outputNames()))\n        if params.get('geometry_observation') is True:\n            from houdini_bridge.geometry_render_scene import observe_geometry\n            task_id = str(params.get('task_id') or '')\n            root, manifest = _fx_manifest(task_id)\n            if ((manifest.get('frozen_render_scene') or {}).get('profile') != 'bounded_geometry_rig_v1'\n                    or (manifest.get('nodes') or {}).get('source') != node.path()):\n                raise BridgeCommandError('GEOMETRY_OBSERVATION_SOURCE_REQUIRED', 'query requires current owned geometry output')\n            _root_lease_check(root.path(),task_id=task_id,scope='sop')\n            result['geometry_observation'] = observe_geometry(hou,manifest['nodes'])\n        return result\n"),
)


def plugin_geometry_update(text):
    """只接受所列初始化/角色/观察差异，其他addon字节必须保持。"""
    for before,after in ADDON_REPLACEMENTS:
        if text.count(before)!=1:
            raise ValueError('ALPHA_REUSE_GEOMETRY_TRANSFORM_MISMATCH')
        text=text.replace(before,after)
    return text
