"""Trusted, versioned native graph declarations and construction bindings.

Static declarations are software preparation, never native execution evidence.
The context-neutral compiler remains the only compiler. Native binding validation
adds exact parent, port and address checks; callers cannot supply native types.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import re
from typing import Any

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.domain_objective import REQUIRED_CONTROLS
from dcc_task_runtime.graph_compiler import (
    GraphCompiler, GraphCompileError, GraphDiagnostic, GraphContext, NodeSpec,
    ParameterSpec, PortSpec, GraphProposal, GraphNodeProposal, GraphConnection, GraphOutput,
)

VERSION = "2.0.0"
HOUDINI_VERSIONS = ("21.0.631", "22.0.429", "22.0.459")
DOMAIN_IDS = tuple(REQUIRED_CONTROLS)
COMPOSITION_IDS = ("composite__explosion_components", "composite__nuke_delivery")
_SAFE_NATIVE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
LEGACY_SOP_TYPES = frozenset({
    "sop.sphere", "sop.burst_source", "sop.pyro_source", "sop.rasterize",
    "sop.pyro_solver", "sop.volume_merge", "sop.volume_output",
})


@dataclass(frozen=True)
class NativeBinding:
    node_type: str
    context: str
    native_type: str
    category: str
    inputs: tuple[tuple[str, int], ...] = ()
    outputs: tuple[tuple[str, int], ...] = ()
    child_context: str | None = None
    # A boundary is an explicit native reference, never a cross-network wire.
    references: tuple[tuple[str, str], ...] = ()
    execution_blocker: str | None = None
    versions: tuple[str, ...] = HOUDINI_VERSIONS
    basis: tuple[str, ...] = ()
    input_names: tuple[tuple[str, str], ...] = ()
    output_names: tuple[tuple[str, str], ...] = ()

    def to_dict(self):
        return {"node_type": self.node_type, "context": self.context,
                "native_type": self.native_type, "category": self.category,
                "inputs": dict(self.inputs), "outputs": dict(self.outputs),
                "child_context": self.child_context, "references": dict(self.references),
                "execution_blocker": self.execution_blocker, "versions": list(self.versions),
                "basis": list(self.basis), "input_names":dict(self.input_names), "output_names":dict(self.output_names)}


def _port(name, value_type, *, required=False, multiple=False, boundary=False):
    return PortSpec(name, value_type, required, multiple, boundary)


def _float(name, minimum, maximum, default=None):
    return ParameterSpec(name, "float", minimum=minimum, maximum=maximum,
                         **({"default": default} if default is not None else {}))


# Each row explicitly declares native machine type and meaningful port types.
# Parameter names are a strict subset; domain semantic writes remain owned by
# versioned NativeControlContract, not guessed aliases added by this catalog.
_DECLARATIONS: list[tuple[NodeSpec, NativeBinding]] = []


def _declare(identifier, native, inputs=(), outputs=(), parameters=(), *,
             child_context=None, references=(), blocked=None, versions=HOUDINI_VERSIONS,
             basis=()):
    prefix = identifier.split(".")[0]
    if prefix in {"h21", "h22"}:
        prefix = identifier.split(".")[1]
    context = "houdini_" + prefix
    category = {"sop": "Sop", "dop": "Dop", "lop": "Lop", "vop": "Vop", "rop": "Driver", "obj": "Obj"}[prefix]
    wire_inputs = tuple((p.name, i) for i, p in enumerate(inputs) if p.name not in dict(references))
    binding = NativeBinding(identifier, context, native, category, wire_inputs,
                            tuple((p.name, i) for i, p in enumerate(outputs)),
                            child_context, tuple(references), blocked, tuple(versions),
                            tuple(basis) or (f"help/nodes.zip:{'out' if prefix == 'rop' else prefix}/{native.split('::')[0]}.txt",))
    _DECLARATIONS.append((NodeSpec(identifier, tuple(inputs), tuple(outputs), tuple(parameters),
                                   (context,), allow_subnet=True), binding))


G = _port("geometry", "geometry")
V = _port("volume", "volume")
S = _port("stage", "scene")
STREAM = _port("stream", "dop_stream")
_declare("sop.sphere", "sphere", outputs=(G,), parameters=tuple(_float(a, .01, 10., 1.) for a in ("radx", "rady", "radz")))
_declare("sop.burst_source", "pyroburstsource", outputs=(G,))
_declare("sop.pyro_source", "pyrosource", (_port("geometry", "geometry", required=True),), (G,))
_declare("sop.rasterize", "volumerasterizeattributes", (_port("geometry", "geometry", required=True),), (V,), (
    _float("voxelsize", .05, 1., .2),
    ParameterSpec("attributes", "enum", enum_values=("density temperature v", "density temperature v flame"), default="density temperature v"),
))
_declare("sop.pyro_solver", "pyrosolver", (_port("source", "volume", required=True),), (V,))
_declare("sop.volume_merge", "merge", (_port("volumes", "volume", required=True, multiple=True),), (V,))
_declare("sop.volume_output", "null", (_port("volume", "volume", required=True),), (_port("volume", "volume", boundary=True),))
for identifier, native in (("grid", "grid"), ("box", "box")):
    _declare("sop." + identifier, native, outputs=(G,))
for identifier, native in (("transform", "xform"), ("scatter", "scatter::2.0"),
                           ("adjust_float", "attribadjustfloat"), ("adjust_vector", "attribadjustvector"),
                           ("trail", "trail"), ("hair_generate", "hairgen")):
    _declare("sop." + identifier, native, (_port("geometry", "geometry", required=True),), (G,))
_declare("sop.geometry_output", "null", (_port("geometry", "geometry", required=True),), (_port("geometry", "geometry", boundary=True),))
_declare("sop.geometry_merge", "merge", (_port("geometry", "geometry", required=True, multiple=True),), (G,))
# H21有限几何字段有独立类型，避免将新参数扩大到旧图或未接收的H22声明。
_declare("h21.sop.geometry_box", "box", outputs=(G,), parameters=(
    *(ParameterSpec("size" + axis, "float", required=True, minimum=.02, maximum=4.) for axis in "xyz"),
    *(_float("t" + axis, -4., 4.) for axis in "xyz"),
), versions=("21.0.631",), basis=("help/nodes.zip:sop/box.txt:#channels:sizex,sizey,sizez,tx,ty,tz", "toolkit/include/SOP/SOP_Box.proto.h:opSize,opCenter"))
_declare("h21.sop.geometry_transform", "xform", (_port("geometry", "geometry", required=True),), (G,), parameters=(
    *(_float("t" + axis, -4., 4.) for axis in "xyz"),
    *(_float("s" + axis, .05, 4.) for axis in "xyz"),
), versions=("21.0.631",), basis=("help/nodes.zip:sop/xform.txt:t,s", "toolkit/include/SOP/SOP_Transform.proto.h:opT,opS"))
_declare("sop.copy_to_points", "copytopoints::2.0", (_port("geometry", "geometry", required=True), _port("points", "geometry", required=True)), (G,))
_declare("sop.ocean_spectrum", "oceanspectrum", outputs=(_port("spectrum", "ocean_spectrum"),))
_declare("sop.ocean_evaluate", "oceanevaluate::2.0", (_port("geometry", "geometry", required=True), _port("spectrum", "ocean_spectrum", required=True)), (G,))
_declare("sop.ocean_foam", "oceanfoam", (_port("geometry", "geometry", required=True), _port("spectrum", "ocean_spectrum", required=True)), (G,), blocked="DOMAIN_OCEAN_FOAM_NATIVE_CONTRACT_PENDING")
_three = (_port("geometry", "geometry"), _port("constraints", "constraints"), _port("collisions", "geometry"))
for identifier, native in (("vellum_constraints", "vellumconstraints"), ("grain_constraints", "vellumconstraints_grain")):
    _declare("sop." + identifier, native, (_port("geometry", "geometry", required=True), _port("constraints", "constraints"), _port("collisions", "geometry")), _three)
_declare("sop.vellum_solver", "vellumsolver", (_port("geometry", "geometry", required=True), _port("constraints", "constraints", required=True), _port("collisions", "geometry")), _three)
_rbd = (_port("geometry", "geometry"), _port("constraints", "constraints"), _port("proxy", "geometry"))
_declare("sop.rbd_fracture", "rbdmaterialfracture", (_port("geometry", "geometry", required=True),), _rbd)
for identifier, native in (("rbd_configure", "rbdconfigure"), ("rbd_solver", "rbdbulletsolver")):
    _declare("sop." + identifier, native, tuple(_port(p.name, p.value_type, required=True) for p in _rbd), _rbd)
_flip = (_port("source", "flip_source"), _port("container", "flip_container"), _port("collisions", "flip_collisions"))
_declare("sop.flip_source", "flipsource", (_port("geometry", "geometry", required=True),), (G,))
_declare("sop.flip_container", "flipcontainer", (_port("geometry", "geometry", required=True),), _flip)
_declare("sop.flip_collide", "flipcollide", tuple(_port(p.name, p.value_type, required=True) for p in _flip) + (_port("new_collision", "geometry", required=True),), _flip)
_declare("sop.flip_solver", "flipsolver", tuple(_port(p.name, p.value_type, required=True) for p in _flip), (G, _flip[1], _flip[2]))
_declare("sop.fluid_surface", "particlefluidsurface::2.0", (_port("geometry", "geometry", required=True),), (G,))
_declare("sop.guide_groom", "guidegroom", (_port("guides", "geometry", required=True), _port("skin", "geometry", required=True)), (G,), blocked="DOMAIN_PROCEDURAL_GUIDES_NATIVE_DATA_PENDING")
_declare("sop.agent_asset", "null", outputs=(_port("agents", "agents"),), blocked="DOMAIN_AGENT_DEFINITION_HOM_CONSTRUCTION_REQUIRED")
_declare("sop.crowd_source", "crowdsource::3.0", (_port("agents", "agents", required=True), _port("points", "geometry", required=True)), (_port("agents", "agents", boundary=True),))
_declare("obj.subnet", "subnet", child_context="houdini_obj", basis=("pythonlibs/hrecipes/api/utils.py:createRecipeContainer",))
for identifier,native,child in (("geometry","geo","houdini_sop"),("dopnet","dopnet","houdini_dop"),("lopnet","lopnet","houdini_lop"),("matnet","matnet","houdini_vop"),("ropnet","ropnet","houdini_rop")):
    _declare("obj."+identifier,native,child_context=child,basis=("pythonlibs/hrecipes/api/utils.py:createRecipeContainer",))
_declare("sop.subnet", "subnet", child_context="houdini_sop")
# DOP Network SOP is explicitly documented as a native SOP child container.
_declare("sop.dopnet", "dopnet", (_port("simulation", "dop_stream", boundary=True),), (_port("geometry", "geometry", boundary=True),), child_context="houdini_dop", references=(("simulation", "@container_output"),))
# Root layouts for these manager categories require the R owner's I2 proof.
for identifier, native, child in (("lopnet", "lopnet", "houdini_lop"), ("ropnet", "ropnet", "houdini_rop")):
    _declare("sop." + identifier, native, child_context=child, blocked="R_I2_LEGAL_OWNED_CONTEXT_LAYOUT_PENDING", basis=(f"help/nodes.zip:manager/{native}.txt",))
_declare("dop.pop_object", "popobject", outputs=(_port("object", "dop_object"),))
_declare("dop.pop_source", "popsource::2.0", (_port("geometry", "geometry", boundary=True),), (STREAM,), references=(("geometry", "soppath"),), blocked="DOMAIN_POP_SOURCE_MODE_GATE_PENDING")
for identifier, native in (("drag", "popdrag"), ("force", "popforce"), ("flock", "popflock"), ("seek", "popsteerseek")):
    _declare("dop." + identifier, native, (_port("stream", "dop_stream", required=True),), (STREAM,))
_declare("dop.pop_solver", "popsolver::2.0", (_port("object", "dop_object", required=True), _port("pre_solve", "dop_stream"), _port("sources", "dop_stream", required=True)), (STREAM,))
_declare("dop.output", "output", (_port("stream", "dop_stream", required=True),), (_port("stream", "dop_stream", boundary=True),))
_declare("dop.crowd_object", "crowdobject", outputs=(_port("object", "dop_object"),), blocked="DOMAIN_CROWD_OBJECT_SOURCE_CONTRACT_PENDING")
_declare("dop.crowd_state", "crowdstate::3.0", outputs=(_port("state", "crowd_state"),), blocked="DOMAIN_CROWD_STATE_VERSIONED_CONTRACT_PENDING")
_declare("dop.crowd_solver", "crowdsolver::3.0", (_port("object", "dop_object", required=True), _port("source", "dop_stream"), _port("states", "crowd_state", required=True)), (STREAM,))
_declare("lop.import_geometry", "sopimport", (_port("geometry", "geometry", required=True, boundary=True),), (S,), references=(("geometry", "soppath"),), basis=("pythonlibs/dopsparsepyrotools.py:createStageSOPImport:soppath",))
_declare("lop.import_volume", "sopimport", (_port("volume", "volume", required=True, boundary=True),), (S,), references=(("volume", "soppath"),), basis=("pythonlibs/dopsparsepyrotools.py:createStageSOPImport:soppath",))
_declare("lop.merge", "merge", (_port("stages", "scene", required=True, multiple=True),), (S,))
_declare("lop.material_library", "materiallibrary", (_port("stage", "scene"), _port("material", "material", boundary=True)), (S,), child_context="houdini_vop", references=(("material", "@material_child"),), blocked="DOMAIN_MATERIAL_LIBRARY_BINDING_PENDING")
for identifier, native in (("assign_material", "assignmaterial"), ("camera", "camera"), ("dome_light", "domelight::3.0"), ("light", "light"), ("render_settings", "karmarendersettings"), ("render_product", "karmarenderproducts::2.0")):
    _declare("lop." + identifier, native, (_port("stage", "scene", required=True),), (_port("stage", "scene", boundary=True),))
_declare("vop.standard_surface", "mtlxstandard_surface", (_port("normal", "normal"),), (_port("surface", "surface"),), parameters=(_float("specular_IOR", 1., 5.),))
_declare("vop.normal_map", "mtlxnormalmap", outputs=(_port("normal", "normal"),), parameters=(_float("scale", 0., 100.),))
_declare("vop.displacement", "mtlxdisplacement", outputs=(_port("displacement", "displacement"),), parameters=(_float("scale", -1000., 1000.),))
_declare("vop.surface_material", "mtlxsurfacematerial", (_port("surface", "surface", required=True), _port("back_surface", "surface"), _port("displacement", "displacement")), (_port("material", "material", boundary=True),))
for tag, versions, field in (("h21", ("21.0.631",), "renderer"), ("h22", ("22.0.429", "22.0.459"), "renderer")):
    _declare(tag + ".rop.usdrender", "usdrender", (_port("stage", "scene", required=True, boundary=True),), (_port("image", "rendered_image"),),
             parameters=(ParameterSpec(field, "enum", enum_values=("BRAY_HdKarma",)),), references=(("stage", "loppath"),), versions=versions)

# Complete domains are source-owned capability compositions. Public callers
# select an exact versioned capability; they never submit its native inventory.
_DOMAIN_DECLARATIONS = {}
from houdini_bridge import native_render_domains as _render_domains
from houdini_bridge import native_domain_registry as _domain_registry
for _version in HOUDINI_VERSIONS:
    _entries = [(_domain, None, None, _render_domains.node_requirements(_domain, _version),
                 _render_domains.connection_requirements(_domain, _version))
                for _domain in (_render_domains.MATERIAL, _render_domains.LIGHTING)]
    if _version in ('21.0.631', '22.0.459'):
        _requirements = _render_domains.node_requirements(_render_domains.MATERIAL, _version)
        _requirements += [
            {'role':'ground','category':'sop','types':['grid'],'parent_role':'geometry_network'},
            {'role':'geometry_output','category':'sop','types':['merge'],'parent_role':'geometry_network'},
            {'role':'stage_metadata','category':'lop','types':['configurelayer'],'parent_role':'usd_network'},
        ]
        _wires = _render_domains.connection_requirements(_render_domains.MATERIAL, _version)
        _wires = [dict(w,source_role='stage_metadata') if w['source_role']=='geometry_import' and w['destination_role']=='material_library' else w for w in _wires]
        _wires += [
            {'source_role':'source','source_output':0,'destination_role':'geometry_output','destination_input':0},
            {'source_role':'ground','source_output':0,'destination_role':'geometry_output','destination_input':1},
            {'source_role':'geometry_import','source_output':0,'destination_role':'stage_metadata','destination_input':0},
        ]
        _entries.append((_render_domains.MATERIAL,None,'sphere_ground_v1',_requirements,_wires))
    if _version in ('21.0.631', '22.0.459'):
        _requirements = _render_domains.node_requirements(_render_domains.MATERIAL, _version)
        _requirements += [
            {'role':'ground','category':'sop','types':['grid'],'parent_role':'geometry_network'},
            {'role':'ground_import','category':'lop','types':['sopimport'],'parent_role':'usd_network'},
            {'role':'geometry_stage_merge','category':'lop','types':['merge'],'parent_role':'usd_network'},
            {'role':'stage_metadata','category':'lop','types':['configurelayer'],'parent_role':'usd_network'},
        ]
        _wires = _render_domains.connection_requirements(_render_domains.MATERIAL, _version)
        _wires = [dict(w,source_role='stage_metadata') if w['source_role']=='geometry_import' and w['destination_role']=='material_library' else w for w in _wires]
        _wires += [
            {'source_role':'geometry_import','source_output':0,'destination_role':'geometry_stage_merge','destination_input':0},
            {'source_role':'ground_import','source_output':0,'destination_role':'geometry_stage_merge','destination_input':1},
            {'source_role':'geometry_stage_merge','source_output':0,'destination_role':'stage_metadata','destination_input':0},
        ]
        _entries.append((_render_domains.MATERIAL,None,'sphere_ground_v2',_requirements,_wires))
        if _version == '21.0.631':
            # 固定rig不含任何模型几何；真实模型子图在有限geometry selector中组合。
            _geometry_requirements = [dict(row) for row in _requirements if row['role'] != 'source']
            _geometry_wires = [dict(row) for row in _wires if row['source_role'] != 'source' and row['destination_role'] != 'source']
            _entries.append((_render_domains.MATERIAL,None,'bounded_geometry_rig_v1',_geometry_requirements,_geometry_wires))
    if _version == '21.0.631':
        from houdini_bridge import official_karma_scene as _official_case
        _requirements,_wires = _official_case.layout(_version)
        _entries.append((_official_case.DOMAIN,None,'official_karma_disklight_v1',_requirements,_wires))
    for _domain in _domain_registry.DOMAIN_IDS:
        for _branch in _domain_registry.branches(_domain):
            _requirements, _wires = _domain_registry.layout(_domain, _version, _branch)
            _entries.append((_domain, _branch if _domain == 'vellum_softbody_grains_v1' else None, None, _requirements, _wires))
    for _domain, _branch, _profile, _requirements, _wires in _entries:
        _roles = {item['role']:item for item in _requirements}
        _role_bindings = {}
        for _role, _requirement in _roles.items():
            _context = 'houdini_' + _requirement['category']
            _prefix = 'h21' if _version == '21.0.631' else 'h22' if _version == '22.0.429' else 'h22_459'
            _identifier = _prefix + '.' + _requirement['category'] + '.' + _domain + ('_' + _branch if _branch else '') + ('_' + _profile if _profile else '') + '_' + _role
            _inputs, _outputs, _input_names, _output_names = {}, {}, {}, {}
            for _wire in _wires:
                if _wire['destination_role'] == _role:
                    _name = _wire.get('destination_input_name') or 'input_' + str(_wire['destination_input'])
                    _inputs[_name] = _wire.get('destination_input',len(_inputs))
                    if 'destination_input_name' in _wire:_input_names[_name] = _wire['destination_input_name']
                if _wire['source_role'] == _role:
                    _name = _wire.get('source_output_name') or 'output_' + str(_wire['source_output'])
                    _outputs[_name] = _wire.get('source_output',len(_outputs))
                    if 'source_output_name' in _wire:_output_names[_name] = _wire['source_output_name']
            _references = {'source_reference':'soppath'} if _role in {'geometry_import','ground_import'} else {'stage_reference':'loppath'} if _role == 'render' else {}
            _outputs.setdefault('output_0',0)
            _child = {'geo':'houdini_sop','lopnet':'houdini_lop','matnet':'houdini_vop','ropnet':'houdini_rop','dopnet':'houdini_dop'}.get(_requirement['types'][0]) if _requirement['category'] in {'obj','sop'} else None
            _binding = NativeBinding(_identifier,_context,_requirement['types'][0],
                'Driver' if _requirement['category']=='rop' else _requirement['category'].capitalize(),
                tuple(_inputs.items()),tuple(_outputs.items()),_child,tuple(_references.items()),
                versions=(_version,),basis=('same-version registered native domain fixed capability inventory',),
                input_names=tuple(_input_names.items()),output_names=tuple(_output_names.items()))
            _spec = NodeSpec(_identifier,
                tuple(_port(n,'geometry' if _profile == 'bounded_geometry_rig_v1' and _role == 'geometry_import' and n == 'source_reference' else 'native_stream',boundary=n in _references) for n in (*_inputs,*_references)),
                tuple(_port(n,'native_stream',boundary=True) for n in _outputs),(),(_context,),allow_subnet=True)
            _DECLARATIONS.append((_spec,_binding));_role_bindings[_role] = _identifier
        _DOMAIN_DECLARATIONS[(_domain,_version,_branch,_profile)] = {'requirements':_requirements,'wires':_wires,'bindings':_role_bindings,
            'source_reference_role':'reverse2' if _profile == 'official_karma_disklight_v1' else 'geometry_output' if _profile == 'sphere_ground_v1' else 'output' if _domain in _domain_registry.DOMAIN_IDS else 'source'}


def registered_domain_proposal(domain,version,native_branch=None,scene_profile=None):
    if scene_profile == 'bounded_geometry_rig_v1':
        raise ValueError('GEOMETRY_MODEL_SELECTOR_REQUIRED')
    entry = _DOMAIN_DECLARATIONS.get((domain,version,native_branch,scene_profile))
    if entry is None:raise ValueError('exact registered domain capability is unavailable')
    by_role = {item['role']:item for item in entry['requirements']}
    def placement(role):
        parent = by_role[role].get('parent_role')
        return placement(parent)+(parent,) if parent else ()
    addresses = {role:'houdini_'+r['category']+':/'+ '/'.join(placement(role)+(role,)) for role,r in by_role.items()}
    nodes = tuple(GraphNodeProposal(role,entry['bindings'][role],'houdini_'+r['category'],placement(role),{}) for role,r in by_role.items())
    connections = [GraphConnection(addresses[w['source_role']],w.get('source_output_name') or 'output_'+str(w['source_output']),
        addresses[w['destination_role']],w.get('destination_input_name') or 'input_'+str(w['destination_input'])) for w in entry['wires']]
    connections.append(GraphConnection(addresses[entry['source_reference_role']],'output_0',addresses['geometry_import'],'source_reference'))
    if 'ground_import' in by_role:
        connections.append(GraphConnection(addresses['ground'],'output_0',addresses['ground_import'],'source_reference'))
    if 'render' in by_role:
        # DiskLight 的最终 Beauty 输出属性由末端绑定节点提供，ROP 引用须与原生初始化一致。
        render_source = 'beauty_binding' if scene_profile == 'official_karma_disklight_v1' else 'settings_binding'
        connections.append(GraphConnection(addresses[render_source],'output_0',addresses['render'],'stage_reference'))
    output = 'render' if 'render' in by_role else 'material_binding'
    return GraphProposal(nodes=nodes,connections=tuple(connections),outputs=(GraphOutput('domain_output',addresses[output],'output_0'),))


def registered_domain_ids():
    return sorted({key[0] for key in _DOMAIN_DECLARATIONS})


def registered_domain_limits():
    geometry = _DOMAIN_DECLARATIONS[(_render_domains.MATERIAL,'21.0.631',None,'bounded_geometry_rig_v1')]
    return {'nodes':max(max(len(v['requirements']) for v in _DOMAIN_DECLARATIONS.values()), len(geometry['requirements']) + 8),
            'connections':max(max(len(v['wires'])+1+int('render' in v['bindings']) for v in _DOMAIN_DECLARATIONS.values()), len(geometry['wires']) + 16 + 3)}


def compile_proposal(proposal):
    if isinstance(proposal,dict) and proposal.get('schema') == 'bridge.geometry-construction/1':
        from .geometry_graph import compose_proposal
        return compiler().compile(compose_proposal(proposal))
    if isinstance(proposal,dict) and proposal.get('schema') == 'bridge.registered-domain-construction/1':
        fields = {'schema','domain_pack','houdini_version'}
        if set(proposal) not in (fields, fields | {'native_branch'}, fields | {'scene_profile'}):raise ValueError('registered domain selector cannot supply graph fields')
        if 'native_branch' in proposal and proposal['domain_pack'] != 'vellum_softbody_grains_v1':raise ValueError('unexpected native branch selector')
        return compiler().compile(registered_domain_proposal(proposal['domain_pack'],proposal['houdini_version'],proposal.get('native_branch'),proposal.get('scene_profile')))
    return compiler().compile(proposal)


def registered_domain_identity(graph):
    from .geometry_graph import identity as geometry_identity
    geometry = geometry_identity(graph)
    if geometry is not None:
        return geometry
    candidates={(domain,version,branch,profile) for (domain,version,branch,profile),entry in _DOMAIN_DECLARATIONS.items()
        if {n.node_type for n in graph.nodes} == set(entry['bindings'].values())}
    for domain,version,branch,profile in candidates:
        if compiler().compile(registered_domain_proposal(domain,version,branch,profile)).to_dict() == graph.to_dict():
            identity = {'schema':'bridge.registered-domain-construction/1','domain_pack':domain,'houdini_version':version}
            if branch is not None:identity['native_branch'] = branch
            if profile is not None:identity['scene_profile'] = profile
            return identity
    return None


def bounded_domain_schedule(graph):
    identity = registered_domain_identity(graph)
    if identity is None:return None
    layout = native_layout(graph,'/obj/schedule')
    ordered = sorted(graph.execution_order,key=lambda a:(layout[a]['path'].count('/'),graph.execution_order.index(a)))
    stages=[];created=set();connected=set()
    for offset in range(0,len(ordered),8):
        nodes=ordered[offset:offset+8];created.update(nodes)
        wires=[index for index,c in enumerate(graph.connections) if index not in connected and c.source_node in created and c.target_node in created]
        for wire_offset in range(0,max(1,len(wires)),16):
            batch=wires[wire_offset:wire_offset+16];connected.update(batch)
            stages.append({'index':len(stages),'nodes':nodes if wire_offset==0 else [],'connections':batch})
    if created != set(graph.execution_order) or connected != set(range(len(graph.connections))):raise ValueError('domain schedule does not cover the frozen graph')
    creation_parameters = {}
    from houdini_bridge import native_crowd_hair_domains
    if identity['domain_pack'] in (native_crowd_hair_domains.CROWD, native_crowd_hair_domains.HAIR):
        by_role = {node.node_id: node for node in graph.nodes}
        for write in native_crowd_hair_domains.multiparm_allocation_plan(
                identity['domain_pack'], identity['houdini_version'], fresh=True):
            if write['native_type'] != 'multiparm' or write['phase'] != 'allocate':
                raise ValueError('creation initialization requires a trusted multiparm allocation')
            address = by_role[write['role']].address
            creation_parameters.setdefault(address, {})[write['parm']] = write['value']
        if identity['domain_pack'] == native_crowd_hair_domains.CROWD:
            from houdini_bridge.native_crowd_transition_contract import ramp_constructor_plan
            ramp_plan = ramp_constructor_plan(identity['houdini_version'])
            role, parm = ramp_plan['target']
            enum_refs, keys, values = ramp_plan['args']
            creation_parameters.setdefault(by_role[role].address, {})[parm] = {
                'schema': 'bridge.native-float-ramp/1',
                'basis': [reference.rsplit('.', 1)[-1] for reference in enum_refs['native_enum_refs']],
                'keys': list(keys), 'values': list(values),
            }
    if identity['domain_pack'] == 'water_flip_v1':
        container = next(node for node in graph.nodes if node.node_id == 'container')
        if layout[container.address]['type'] != 'flipcontainer':
            raise ValueError('FLIP creation initialization requires the registered native container')
        # Author the new recipe before the producer captures its first scene.
        # This is an explicit empty allocation, not an inferred native default.
        creation_parameters[container.address] = {'customattributes': 0}
    value={'schema':'bridge.registered-domain-schedule/1','identity':identity,'graph_hash':graph.graph_hash,
        'stages':stages,'node_count':len(graph.nodes),'connection_count':len(graph.connections),
        'operation_count':1+len(graph.nodes)+sum(bool(n.parameters) for n in graph.nodes)+len(graph.connections)}
    if creation_parameters:
        value['creation_parameters'] = creation_parameters
    return {**value,'schedule_sha256':canonical_sha256(value)}


_SPECS = MappingProxyType({spec.node_type: spec for spec, _ in _DECLARATIONS})
_BINDINGS = MappingProxyType({binding.node_type: binding for _, binding in _DECLARATIONS})
NATIVE_TYPES = MappingProxyType({key: value.native_type for key, value in _BINDINGS.items()})
del _DECLARATIONS


def native_binding(node_type: str, version: str | None = None) -> NativeBinding:
    binding = _BINDINGS[node_type]
    if version is not None and version not in binding.versions:
        raise ValueError("native binding has no declaration for this exact Houdini version")
    return binding


def _binding_errors(graph):
    errors = []
    placements = {(n.context, tuple(n.subnet_path) + (n.node_id,)): n for n in graph.nodes}
    native_paths = set()
    root_context = "houdini_obj" if any(n.context == "houdini_obj" and not n.subnet_path for n in graph.nodes) else "houdini_sop"
    for n in graph.nodes:
        if not _SAFE_NATIVE_NAME.fullmatch(n.node_id) or any(not _SAFE_NATIVE_NAME.fullmatch(s) for s in n.subnet_path):
            errors.append(GraphDiagnostic("NATIVE_ADDRESS_INVALID", "native names must be bounded Houdini identifiers", n.address))
        key = tuple(n.subnet_path) + (n.node_id,)
        if key in native_paths:
            errors.append(GraphDiagnostic("NATIVE_PATH_COLLISION", "contexts map to the same native path", n.address))
        native_paths.add(key)
        if not n.subnet_path:
            if n.context != root_context:
                errors.append(GraphDiagnostic("NATIVE_PARENT_MISSING", "non-SOP nodes require a declared native parent", n.address))
            continue
        parents = [p for (_, path), p in placements.items() if path == tuple(n.subnet_path)]
        if len(parents) != 1 or native_binding(parents[0].node_type).child_context != n.context:
            errors.append(GraphDiagnostic("NATIVE_PARENT_CONTEXT", "parent is missing or cannot contain this native category", n.address))
    incoming = set()
    for c in graph.connections:
        source = next(n for n in graph.nodes if n.address == c.source_node)
        target = next(n for n in graph.nodes if n.address == c.target_node)
        b = native_binding(target.node_type)
        if c.target_port in dict(b.references):
            if dict(b.references)[c.target_port].startswith("@") and tuple(source.subnet_path) != tuple(target.subnet_path) + (target.node_id,):
                errors.append(GraphDiagnostic("NATIVE_BOUNDARY_PARENT", "container dependency must originate in its own child network", target.address))
            continue
        if source.context != target.context or source.subnet_path != target.subnet_path:
            errors.append(GraphDiagnostic("NATIVE_WIRE_CONTEXT", "wire requires the same native parent; use an explicit import", target.address))
        index = dict(b.inputs)[c.target_port] + (c.target_index or 0)
        key = (target.address, index)
        if key in incoming:
            errors.append(GraphDiagnostic("NATIVE_INPUT_COLLISION", "named ports resolve to the same native input index", target.address))
        incoming.add(key)
        if index >= 64:
            errors.append(GraphDiagnostic("NATIVE_INPUT_BUDGET", "native input index exceeds the bounded construction interface", target.address))
    versions = set(HOUDINI_VERSIONS)
    for n in graph.nodes:
        versions.intersection_update(native_binding(n.node_type).versions)
    if not versions:
        errors.append(GraphDiagnostic("NATIVE_VERSION_MISMATCH", "graph mixes incompatible exact-version declarations"))
    return errors


class _NativeGraphCompiler(GraphCompiler):
    def compile(self, proposal):
        compiled = super().compile(proposal)
        errors = _binding_errors(compiled)
        if errors:
            raise GraphCompileError(errors)
        return compiled

    def validate(self, proposal):
        try:
            self.compile(proposal)
        except GraphCompileError as exc:
            return exc.diagnostics
        return ()


def compiler():
    contexts = tuple(GraphContext(context, tuple(k for k, b in _BINDINGS.items() if b.context == context), allow_subnets=True)
                     for context in ("houdini_sop", "houdini_dop", "houdini_lop", "houdini_vop", "houdini_rop", "houdini_obj"))
    return _NativeGraphCompiler(tuple(_SPECS.values()), contexts, max_nodes=64, max_connections=128)


def validate_catalog():
    """Whole registration equality includes specs, native types and port bindings."""
    instance = compiler()
    if frozenset(instance.node_catalog) != frozenset(_BINDINGS) or not LEGACY_SOP_TYPES <= frozenset(_BINDINGS):
        raise ValueError("trusted native catalog registration is incomplete")
    for key, spec in instance.node_catalog.items():
        b = native_binding(key)
        if set(p.name for p in spec.inputs) != set(dict(b.inputs)) | set(dict(b.references)) or set(p.name for p in spec.outputs) != set(dict(b.outputs)):
            raise ValueError("native port binding differs from compiler declarations")
    return frozenset(_BINDINGS)


def native_root_type(graph):
    errors = _binding_errors(graph)
    if errors:
        raise GraphCompileError(errors)
    return "subnet" if any(n.context == "houdini_obj" and not n.subnet_path for n in graph.nodes) else "geo"


def native_layout(graph, root):
    """Deterministic task-local paths; no implicit networks or external roots."""
    errors = _binding_errors(graph)
    if errors:
        raise GraphCompileError(errors)
    return {n.address: {"path": root + "/" + "/".join(tuple(n.subnet_path) + (n.node_id,)),
                        "parent": root + ("/" + "/".join(n.subnet_path) if n.subnet_path else ""),
                        "type": native_binding(n.node_type).native_type,
                        "category": native_binding(n.node_type).category}
            for n in graph.nodes}


def connection_binding(graph, connection):
    by_address = {n.address: n for n in graph.nodes}
    source, target = by_address[connection.source_node], by_address[connection.target_node]
    sb, tb = native_binding(source.node_type), native_binding(target.node_type)
    field = dict(tb.references).get(connection.target_port)
    return {"kind": "reference" if field else "wire", "field": field,
            "input_index": None if field else dict(tb.inputs)[connection.target_port] + (connection.target_index or 0),
            "output_index": dict(sb.outputs)[connection.source_port],
            "input_name":dict(tb.input_names).get(connection.target_port), "output_name":dict(sb.output_names).get(connection.source_port)}


def resolve_connection_binding(binding,source_info,target_info):
    result=dict(binding)
    for side,info in (('input',target_info),('output',source_info)):
        name=result.get(side+'_name')
        if name is None:continue
        names=info.get(side+'_names')
        if not isinstance(names,list) or any(not isinstance(n,str) for n in names) or names.count(name)!=1:
            raise ValueError('actual native named port interface is unavailable')
        index=names.index(name)
        if index>=64:raise ValueError('actual native port exceeds the bounded interface')
        result[side+'_index']=index
    return result


def execution_diagnostics(graph):
    return [{"code": "NATIVE_BINDING_BLOCKED", "address": n.address,
             "message": native_binding(n.node_type).execution_blocker}
            for n in graph.nodes if native_binding(n.node_type).execution_blocker]


def catalog_specs():
    return {identifier: {p.name: {"minimum": p.minimum, "maximum": p.maximum,
                               "enum_values": list(p.enum_values) if p.enum_values else None}
                        for p in node.parameters} for identifier, node in _SPECS.items()}


def descriptor():
    instance = compiler()
    value = {"catalog_version": VERSION, "maturity": "experimental",
             "native_execution": False, "houdini_versions": list(HOUDINI_VERSIONS),
             "nodes": [n.to_dict() for n in instance.node_catalog.values()],
             "contexts": [c.to_dict() for c in instance.contexts.values()],
             "native_types": dict(NATIVE_TYPES), "native_bindings": [b.to_dict() for b in _BINDINGS.values()],
             "max_nodes": instance.max_nodes, "max_connections": instance.max_connections,
             "domains": list(DOMAIN_IDS), "combinations": list(COMPOSITION_IDS),
             "registered_domain_ids":registered_domain_ids(),
             "registered_domain_branches":{"vellum_softbody_grains_v1":["softbody","grains"]}}
    return {**value, "catalog_hash": canonical_sha256(value)}
