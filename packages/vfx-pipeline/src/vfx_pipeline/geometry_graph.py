"""有限模型SOP子图与固定渲染rig的纯组合；不生成案例答案或执行HOM。"""
from __future__ import annotations

from dcc_task_runtime.graph_compiler import GraphProposal, GraphNodeProposal, GraphConnection, GraphOutput, GraphCompileError

SCHEMA = 'bridge.geometry-construction/1'
PROFILE = 'bounded_geometry_rig_v1'
VERSION = '21.0.631'
DOMAIN = 'material_lookdev_v1'
MAX_NODES = 8
MAX_CONNECTIONS = 16
MODEL_PREFIX = 'm_'
MODEL_PARENT = ('geometry_network',)
MODEL_OUTPUT = 'model_output'
BOX = 'h21.sop.geometry_box'
TRANSFORM = 'h21.sop.geometry_transform'
MERGE = 'sop.geometry_merge'
OUTPUT = 'sop.geometry_output'
ALLOWED_TYPES = frozenset((BOX, TRANSFORM, MERGE, OUTPUT))


def _catalog():
    from . import graph_catalog
    return graph_catalog


def _fail(reason):
    raise ValueError('GEOMETRY_GRAPH_' + reason)


def model_proposal(value):
    """编译有限的平面SOP提案；所有节点都须实际流向唯一显式输出。"""
    proposal = value if isinstance(value, GraphProposal) else GraphProposal.from_mapping(value)
    if (not 1 <= len(proposal.nodes) <= MAX_NODES or len(proposal.connections) > MAX_CONNECTIONS
            or len(proposal.outputs) != 1):
        _fail('BOUNDS_REQUIRED')
    if any(node.node_type not in ALLOWED_TYPES or node.context != 'houdini_sop'
           or node.subnet_path or len(node.node_id) > 96 for node in proposal.nodes):
        _fail('FINITE_SOP_TYPES_REQUIRED')
    if not any(node.node_type == BOX for node in proposal.nodes):
        _fail('BOX_REQUIRED')
    # 同一可信编译器执行参数范围、端口、地址和无环检查；这里不复制其执行逻辑。
    compiler = _catalog().compiler()
    compiled = compiler.compile(proposal)
    by_address = {node.address: node for node in compiled.nodes}
    output = compiled.outputs[0]
    if (output.output_id != MODEL_OUTPUT or output.port != 'geometry'
            or by_address[output.node_id].node_type != OUTPUT):
        _fail('EXPLICIT_NULL_OUTPUT_REQUIRED')
    upstream = {output.node_id}
    while True:
        expanded = upstream | {edge.source_node for edge in compiled.connections if edge.target_node in upstream}
        if expanded == upstream:
            break
        upstream = expanded
    if upstream != set(by_address):
        _fail('UNUSED_NODE')
    # Box尺寸必须由提案明确给出，不把工厂默认几何当作模型选择。
    for node in compiled.nodes:
        if node.node_type == BOX and not {'sizex','sizey','sizez'} <= set(node.parameters):
            _fail('EXPLICIT_BOX_SIZE_REQUIRED')
    # HOM的float参数读回为float；只编码已经通过有限目录验证的新Box/Xform字段。
    # 有界整数与同值float含义一致，但严格原生读回合同要求写入时也使用float。
    def encoded_parameters(node):
        floats={p.name for p in compiler.node_catalog[node.node_type].parameters if p.value_type=='float'} if node.node_type in {BOX,TRANSFORM} else set()
        return {name:float(value) if name in floats else value for name,value in node.parameters.items()}
    return GraphProposal(
        tuple(GraphNodeProposal(n.node_id, n.node_type, n.context, n.subnet_path, encoded_parameters(n)) for n in compiled.nodes),
        tuple(GraphConnection(c.source_node, c.source_port, c.target_node, c.target_port, c.target_index) for c in compiled.connections),
        tuple(GraphOutput(o.output_id, o.node_id, o.port) for o in compiled.outputs),
    )


def selector(model_graph):
    """控制侧仅加固定身份；模型节点图及参数保持来自已验证提案。"""
    return {'schema':SCHEMA, 'domain_pack':DOMAIN, 'houdini_version':VERSION,
            'scene_profile':PROFILE, 'model_graph':model_proposal(model_graph).to_dict()}


def _selector(value):
    if (not isinstance(value, dict)
            or set(value) != {'schema','domain_pack','houdini_version','scene_profile','model_graph'}
            or value.get('schema') != SCHEMA or value.get('domain_pack') != DOMAIN
            or value.get('houdini_version') != VERSION or value.get('scene_profile') != PROFILE):
        _fail('SELECTOR_REQUIRED')
    return model_proposal(value['model_graph'])


def _rig():
    return _catalog()._DOMAIN_DECLARATIONS[(DOMAIN, VERSION, None, PROFILE)]


def compose_proposal(value):
    """把模型子图嵌入固定rig；只有其显式输出连接到模型几何导入端。"""
    model = _selector(value)
    catalog = _catalog()
    base = catalog.registered_domain_proposal(DOMAIN, VERSION, None, 'sphere_ground_v2')
    rig = _rig()
    # 固定rig保留原空间/材质/渲染拓扑，但不携带旧Sphere节点或任何案例尺寸。
    rig_nodes = [GraphNodeProposal(n.node_id, rig['bindings'][n.node_id], n.context, n.subnet_path, {})
                 for n in base.nodes if n.node_id != 'source']
    old_source = next(n.address for n in base.nodes if n.node_id == 'source')
    connections = [GraphConnection(c.source_node, c.source_port, c.target_node, c.target_port, c.target_index)
                   for c in base.connections if c.source_node != old_source and c.target_node != old_source]
    addresses = {n.address:'houdini_sop:/geometry_network/' + MODEL_PREFIX + n.node_id for n in model.nodes}
    model_nodes = [GraphNodeProposal(MODEL_PREFIX+n.node_id, n.node_type, n.context, MODEL_PARENT, dict(n.parameters))
                   for n in model.nodes]
    connections += [GraphConnection(addresses[c.source_node], c.source_port, addresses[c.target_node], c.target_port, c.target_index)
                    for c in model.connections]
    imported = next(n.address for n in rig_nodes if n.node_id == 'geometry_import')
    connections.append(GraphConnection(addresses[model.outputs[0].node_id], 'geometry', imported, 'source_reference'))
    return GraphProposal(tuple(rig_nodes + model_nodes), tuple(connections), base.outputs)


def _recover_model(graph):
    """从已编译组合恢复模型提案，随后必须精确重编译比较整图。"""
    model = [node for node in graph.nodes if node.node_type in ALLOWED_TYPES]
    if not model or any(tuple(node.subnet_path) != MODEL_PARENT or not node.node_id.startswith(MODEL_PREFIX)
                        for node in model):
        _fail('MODEL_PLACEMENT_INVALID')
    addresses = {node.address:'houdini_sop:/' + node.node_id[len(MODEL_PREFIX):] for node in model}
    candidates = [edge for edge in graph.connections
                  if edge.source_node in addresses and edge.target_node == 'houdini_lop:/usd_network/geometry_import'
                  and edge.target_port == 'source_reference']
    if len(candidates) != 1:
        _fail('MODEL_IMPORT_REQUIRED')
    outgoing = candidates[0]
    if outgoing.source_port != 'geometry' or outgoing.target_index is not None:
        _fail('MODEL_IMPORT_REQUIRED')
    nodes = [GraphNodeProposal(n.node_id[len(MODEL_PREFIX):], n.node_type, 'houdini_sop', (), dict(n.parameters)) for n in model]
    connections = [GraphConnection(addresses[c.source_node], c.source_port, addresses[c.target_node], c.target_port, c.target_index)
                   for c in graph.connections if c.source_node in addresses and c.target_node in addresses]
    return model_proposal(GraphProposal(tuple(nodes), tuple(connections),
                                       (GraphOutput(MODEL_OUTPUT, addresses[outgoing.source_node], 'geometry'),)))


def identity(graph):
    """只有模型子图和固定rig逐字段重编译相等，才授予本几何组合身份。"""
    bindings = set(_rig()['bindings'].values())
    if not any(node.node_type in bindings for node in graph.nodes):
        return None
    try:
        value = selector(_recover_model(graph))
        expected = _catalog().compiler().compile(compose_proposal(value))
        return value if expected.to_dict() == graph.to_dict() else None
    except (ValueError, KeyError, TypeError, GraphCompileError):
        return None


def role_nodes(graph, root):
    """返回唯一实际角色；模型输出仅占source角色，避免同节点重复登记。"""
    value = identity(graph)
    if value is None:
        _fail('IDENTITY_REQUIRED')
    layout = _catalog().native_layout(graph, root)
    model = model_proposal(value['model_graph'])
    source = 'houdini_sop:/geometry_network/' + MODEL_PREFIX + next(
        n.node_id for n in model.nodes if n.address == model.outputs[0].node_id)
    result = {}
    for node in graph.nodes:
        role = 'source' if node.address == source else node.node_id
        if role in result:
            _fail('DUPLICATE_ROLE')
        result[role] = dict(layout[node.address])
    if len({row['path'] for row in result.values()}) != len(result):
        _fail('DUPLICATE_ROLE')
    return result


def model_graph_schema():
    """公开编译器已有的有限GraphProposal字段，不提供任何案例节点图或尺寸选择。"""
    compiler=_catalog().compiler()
    identifier={'type':'string','minLength':1,'maxLength':96,'pattern':r'^[A-Za-z][A-Za-z0-9_.:-]{0,95}$'}
    address={'type':'string','minLength':1,'maxLength':109,
             'pattern':r'^(?:houdini_sop:/)?[A-Za-z][A-Za-z0-9_.:-]{0,95}$',
             'description':'引用nodes中已有node_id，可写node_id或houdini_sop:/node_id；不是文件路径。'}
    variants=[]
    for name in sorted(ALLOWED_TYPES):
        parameters={p.name:{'type':'number','minimum':p.minimum,'maximum':p.maximum}
                    for p in compiler.node_catalog[name].parameters}
        required_parms=[p.name for p in compiler.node_catalog[name].parameters if p.required]
        fields={'node_id':dict(identifier),'node_type':{'type':'string','enum':[name]},
                'context':{'type':'string','enum':['houdini_sop']},
                'subnet_path':{'type':'array','maxItems':0,'items':dict(identifier),'default':[],
                               'description':'模型子图只能位于顶层，填写空数组。'},
                'parameters':{'type':'object','properties':parameters,'required':required_parms,
                              'additionalProperties':False}}
        required=['node_id','node_type','context']+(['parameters'] if required_parms else [])
        variants.append({'type':'object','properties':fields,'required':required,'additionalProperties':False})
    connection={'type':'object','properties':{
        'source_node':dict(address),'source_port':{'type':'string','enum':['geometry']},
        'target_node':dict(address),'target_port':{'type':'string','enum':['geometry']},
        'target_index':{'anyOf':[{'type':'integer','minimum':0,'maximum':MAX_CONNECTIONS-1},{'enum':[None]}],
                        'description':'多个输入接到同一个merge时必须显式写不同且从0连续的索引0,1,...；单输入节点只允许0或省略。'}},
        'required':['source_node','source_port','target_node','target_port'],'additionalProperties':False}
    output={'type':'object','properties':{'output_id':{'type':'string','enum':[MODEL_OUTPUT]},
        'node_id':dict(address),'port':{'type':'string','enum':['geometry']}},
        'required':['output_id','node_id','port'],'additionalProperties':False}
    return {'type':'object','properties':{
        'schema_version':{'type':'string','enum':['1.0'],'default':'1.0'},
        'nodes':{'type':'array','minItems':2,'maxItems':MAX_NODES,'items':{'anyOf':variants}},
        'connections':{'type':'array','minItems':1,'maxItems':MAX_CONNECTIONS,'items':connection},
        'outputs':{'type':'array','minItems':1,'maxItems':1,'items':output}},
        'required':['nodes','connections','outputs'],'additionalProperties':False,
        'description':'GraphProposal；至少一个Box；全部模型节点必须流向唯一sop.geometry_output输出。'}


def model_schema_issue(value):
    """只返回受控字段位置和有限期望，不回显任意输入键、值、文件路径或异常原文。"""
    import math
    def issue(code,path,**expected):return {'code':'GEOMETRY_MODEL_'+code,'field':path,**expected}
    def check(raw,schema,path):
        if 'enum' in schema and raw not in schema['enum']:return issue('ENUM_REQUIRED',path,allowed_values=schema['enum'])
        if 'anyOf' in schema:
            choices=schema['anyOf']
            if not all('node_type' in item.get('properties',{}) for item in choices):
                failures=[check(raw,item,path) for item in choices]
                return None if None in failures else failures[0]
            if not isinstance(raw,dict):return issue('OBJECT_REQUIRED',path)
            branch=next((item for item in choices if raw.get('node_type') in item['properties']['node_type']['enum']),None)
            if branch is None:
                return issue('NODE_TYPE_REQUIRED',path+'.node_type',allowed_types=sorted(ALLOWED_TYPES))
            return check(raw,branch,path)
        kind=schema.get('type')
        if kind=='object':
            if not isinstance(raw,dict):return issue('OBJECT_REQUIRED',path)
            properties=schema.get('properties',{});required=schema.get('required',[])
            if set(raw)-set(properties):
                return issue('UNKNOWN_FIELDS',path,allowed_fields=sorted(properties),required_fields=required)
            missing=[name for name in required if name not in raw]
            if missing:return issue('REQUIRED_FIELDS',path,missing_fields=missing,allowed_fields=sorted(properties))
            for name,child in properties.items():
                if name in raw:
                    result=check(raw[name],child,path+'.'+name)
                    if result:return result
        elif kind=='array':
            if not isinstance(raw,list):return issue('ARRAY_REQUIRED',path)
            if not schema.get('minItems',0)<=len(raw)<=schema.get('maxItems',MAX_CONNECTIONS):
                return issue('ARRAY_BOUNDS',path,minimum=schema.get('minItems',0),maximum=schema.get('maxItems',MAX_CONNECTIONS))
            for index,item in enumerate(raw):
                result=check(item,schema['items'],path+'['+str(index)+']')
                if result:return result
        elif kind=='string':
            if not isinstance(raw,str):return issue('STRING_REQUIRED',path)
            if 'enum' in schema and raw not in schema['enum']:return issue('ENUM_REQUIRED',path,allowed_values=schema['enum'])
            import re
            if (len(raw)<schema.get('minLength',0) or len(raw)>schema.get('maxLength',256)
                    or 'pattern' in schema and re.fullmatch(schema['pattern'],raw) is None):
                return issue('STRING_FORMAT',path,minimum=schema.get('minLength',0),maximum=schema.get('maxLength',256),pattern=schema.get('pattern'))
        elif kind in ('number','integer'):
            if not isinstance(raw,(int,float)) or isinstance(raw,bool) or kind=='integer' and not isinstance(raw,int):
                return issue('FINITE_INTEGER_REQUIRED' if kind=='integer' else 'FINITE_NUMBER_REQUIRED',path)
            try:finite=math.isfinite(raw)
            except OverflowError:finite=False
            if not finite:return issue('FINITE_NUMBER_REQUIRED',path)
            if not schema['minimum']<=raw<=schema['maximum']:
                return issue('NUMBER_RANGE',path,minimum=schema['minimum'],maximum=schema['maximum'])
        return None
    return check(value,model_graph_schema(),'$.model_graph')


def model_catalog():
    """仅公开本任务能用的有限模型节点、完整数据结构和通用连接协议。"""
    compiler = _catalog().compiler()
    return {'schema':SCHEMA, 'scene_profile':PROFILE, 'houdini_version':VERSION,
            'max_nodes':MAX_NODES, 'max_connections':MAX_CONNECTIONS,
            'output_id':MODEL_OUTPUT, 'required_output_type':OUTPUT,
            'model_graph_schema':model_graph_schema(),
            'protocol':{'node_reference':'source_node、target_node和outputs.node_id引用已有node_id或houdini_sop:/node_id。',
                        'ports':'本目录所有连接的source_port和target_port均为geometry。',
                        'merge_fan_in':'同一sop.geometry_merge的geometry端口有多个输入时，每条边必须显式给target_index，互不重复且从0连续；编译器不会自动分配。',
                        'single_input':'transform和output必须各有一个geometry输入；target_index省略或为0。Box没有输入。',
                        'output':'outputs只有一个条目，output_id为model_output，指向sop.geometry_output节点的geometry端口；所有节点都必须流向它。',
                        'defaults':'schema_version省略时为1.0；subnet_path省略时为空；无必填参数的节点可省略parameters。'},
            'nodes':[compiler.node_catalog[name].to_dict() for name in sorted(ALLOWED_TYPES)]}
