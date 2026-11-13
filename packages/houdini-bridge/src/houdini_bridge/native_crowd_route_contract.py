"""Pure Crowd route plans consumed by the existing trusted host transaction.

Runtime facts come from the host adapter. No HOM calls, geometry, ownership
leases or operation receipts are manufactured by this module.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

VERSIONS = ('21.0.631', '22.0.429')
FIXED_CURVE_POINTS = ((0., 0., 0.), (4., 0., 0.), (8., 0., 3.))
_ROUTE_DIALOG = {'21.0.631': '2a91f80800471551352e27550bcad8a0ad6151ca29c3242379ad3cce221f971a', '22.0.429': '7919bf5833be4dbda326f4e47773cb35dd131712473919a368b2beef432e015f', '22.0.459': '7919bf5833be4dbda326f4e47773cb35dd131712473919a368b2beef432e015f'}
_GEOMETRY_DOC = {'21.0.631': '4614f2ed20495d12c37a833c6e01ededcec19b5e9c23961a0cacd59c2f8d5605', '22.0.429': 'b14324302f4481e0e4dad87e2920e0e10ea01d87182db8b0352a5b5a2cc01bae', '22.0.459': 'b14324302f4481e0e4dad87e2920e0e10ea01d87182db8b0352a5b5a2cc01bae'}

_RECIPE_SHA256 = {'21.0.631': '1aa562c05ccc2b7e1c7abb74a4ff275a19f8eb7e286291ae5d6e64d0d8c01d85', '22.0.429': '1c4e4af57e9f3fb88fe2673aa5b099ab318c264c0de3c1f716c43a44a96326a8', '22.0.459': '1c4e4af57e9f3fb88fe2673aa5b099ab318c264c0de3c1f716c43a44a96326a8'}
_PARM_DOC = {'21.0.631': 'bfc24e62c4095fe841f64152c0914262915689a2f578aa2fbd0de35bfbbb2b24', '22.0.429': '01e930c2f95921c43b962a7a4ace809b978fbe49d987d4bfe12029bfef985704', '22.0.459': '01e930c2f95921c43b962a7a4ace809b978fbe49d987d4bfe12029bfef985704'}


class CrowdRouteContractError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _require(condition, code, detail):
    if not condition:
        raise CrowdRouteContractError(code, detail)


def _version(version):
    _require(version in (*VERSIONS, *PREPARATION_VERSIONS), 'UNSUPPORTED_NATIVE_VERSION', str(version))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _number(value, lo, hi):
    _require(type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi,
             'INVALID_ROUTE_WEIGHT', 'route_weight must be a finite native relative weight in [0,100]')
    return float(value)


@dataclass(frozen=True)
class HostIdentity:
    task_id: str
    resource_id: str
    content_version: str
    session_id: str
    process_generation: str
    scene_epoch: int


@dataclass(frozen=True)
class NodeFact:
    role: str
    path: str
    parent_path: str
    category: str
    native_type: str
    instance_id: str
    identity: HostIdentity
    input_count: int
    output_count: int
    writable: bool
    version: str
    origin: str = 'runtime_hom'


@dataclass(frozen=True)
class MenuFact:
    items: tuple[tuple[str, str], ...]
    storage: str
    origin: str = 'runtime_hom'


@dataclass(frozen=True)
class ParmFact:
    role: str
    name: str
    native_type: str
    ui_type: str
    size: int
    value: object
    writable: bool
    driven: bool
    compiled_native_type: str
    compiled_writable: bool
    node_path: str
    identity: HostIdentity
    menu: MenuFact | None = None
    origin: str = 'runtime_hom'


@dataclass(frozen=True)
class CurveFact:
    node_path: str
    output_port: int
    points: tuple[tuple[float, float, float], ...]
    vertices: tuple[int, ...]
    closed: bool
    primitive_type: str
    geometry_sha256: str
    identity: HostIdentity
    primitive_count: int
    origin: str = 'runtime_hom'


@dataclass(frozen=True)
class WireBinding:
    source_role: str
    output_port: int
    target_role: str
    input_port: int


@dataclass(frozen=True)
class RouteContext:
    version: str
    identity: HostIdentity
    task_root: str
    sop_root: str
    dop_root: str
    nodes: tuple[NodeFact, ...]
    parameters: tuple[ParmFact, ...]
    curve: CurveFact
    connections: tuple[WireBinding, ...]
    parents: tuple[NodeFact, ...]
    origin: str = 'trusted_host_runtime'


@dataclass(frozen=True)
class ParmWrite:
    role: str
    parm: str
    value: object
    native_type: str
    require_writable: bool = True
    require_readback: bool = True


@dataclass(frozen=True)
class RoutePlan:
    phase: str
    writes: tuple[ParmWrite, ...]
    connections: tuple[WireBinding, ...]
    frozen_guard_sha256: str
    version: str
    invalidates_from: str = 'generation_simulation'
    schema: str = 'bridge.native-crowd-route-plan/1'


def curve_geometry_sha256(points, vertices, closed=False, primitive_type='Polygon'):
    """Digest the adapter's observed output geometry, not a path or a data ID."""
    _require(type(closed) is bool and closed is False and primitive_type == 'Polygon',
             'ACTUAL_ROUTE_CURVE_REQUIRED', 'an open polygon curve is required')
    _require(isinstance(points, tuple) and len(points) >= 2 and all(
        isinstance(p, tuple) and len(p) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in p)
        for p in points), 'ACTUAL_ROUTE_CURVE_REQUIRED', 'finite actual points are required')
    _require(isinstance(vertices, tuple) and len(vertices) >= 2
        and all(type(i) is int and 0 <= i < len(points) for i in vertices)
        and len(set(vertices)) == len(vertices),
        'ACTUAL_ROUTE_CURVE_REQUIRED', 'ordered actual curve vertices are required')
    length = sum(math.dist(points[a], points[b]) for a, b in zip(vertices, vertices[1:]))
    _require(length > 1e-9 and all(math.dist(points[a], points[b]) > 1e-9
        for a, b in zip(vertices, vertices[1:])), 'ACTUAL_ROUTE_CURVE_REQUIRED', 'curve must be nondegenerate')
    return _digest({'points': [[float(v) for v in p] for p in points],
                    'vertices': vertices, 'closed': closed, 'primitive_type': primitive_type})


def _path(path):
    return isinstance(path, str) and path.startswith('/obj/') and str(PurePosixPath(path)) == path and '..' not in path.split('/')


def _menu_value(fact, token, label):
    menu = fact.menu
    _require(isinstance(menu, MenuFact) and menu.origin == 'runtime_hom'
        and menu.storage in ('index', 'token') and isinstance(menu.items, tuple)
        and all(isinstance(item, tuple) and len(item) == 2 and all(isinstance(v, str) for v in item) for item in menu.items)
        and len(menu.items) == len(set(t for t, _ in menu.items))
        and (token, label) in menu.items, 'ACTUAL_MENU_BINDING_REQUIRED', fact.name)
    index = next(i for i, item in enumerate(menu.items) if item == (token, label))
    _require(index == 0, 'ACTUAL_MENU_BINDING_REQUIRED', fact.name + ' captured native item must be index 0')
    _require(fact.native_type == ('int' if menu.storage == 'index' else 'string'),
             'ACTUAL_MENU_STORAGE_REQUIRED', fact.name)
    return index if menu.storage == 'index' else token


def _parts(context):
    nodes = {n.role: n for n in context.nodes}
    parms = {(p.role, p.name): p for p in context.parameters}
    _require(len(nodes) == len(context.nodes) and len(parms) == len(context.parameters),
             'AMBIGUOUS_NATIVE_CONTEXT', 'duplicate role or parameter')
    return nodes, parms


def _expected_wires():
    return (WireBinding('state_stream', 0, 'route', 0), WireBinding('route', 0, 'solver', 2))


def validate_context(context, *, installed=False):
    _require(isinstance(context, RouteContext), 'TYPED_ROUTE_CONTEXT_REQUIRED', 'RouteContext')
    _version(context.version)
    identity = context.identity
    _require(isinstance(identity, HostIdentity) and all(isinstance(v, str) and v for v in (
        identity.task_id, identity.resource_id, identity.content_version, identity.session_id, identity.process_generation))
        and type(identity.scene_epoch) is int and identity.scene_epoch >= 0
        and context.origin == 'trusted_host_runtime', 'ACTUAL_HOST_IDENTITY_REQUIRED', 'task/resource/version/session/scene')
    _require(all(_path(p) for p in (context.task_root, context.sop_root, context.dop_root))
        and context.sop_root.startswith(context.task_root + '/')
        and context.dop_root.startswith(context.task_root + '/') and context.sop_root != context.dop_root,
        'TASK_OWNED_CONTEXT_REQUIRED', 'separate task-owned SOP and DOP roots')
    _require(isinstance(context.nodes, tuple) and isinstance(context.parameters, tuple)
        and all(isinstance(n, NodeFact) for n in context.nodes)
        and all(isinstance(p, ParmFact) for p in context.parameters)
        and isinstance(context.curve, CurveFact), 'TYPED_ROUTE_CONTEXT_REQUIRED', 'native facts')
    parent_types = {'task_root': (context.task_root, '/obj', 'subnet'),
                    'sop_root': (context.sop_root, context.task_root, 'geo'),
                    'dop_root': (context.dop_root, context.task_root, 'dopnet')}
    _require(isinstance(context.parents, tuple) and all(isinstance(p, NodeFact) for p in context.parents)
        and len(context.parents) == 3 and {p.role for p in context.parents} == set(parent_types),
        'ACTUAL_CONTEXT_PARENT_REQUIRED', 'task subnet with separate geo/dopnet children')
    dop_parent = next(p for p in context.parents if p.role=='dop_root')
    dop_category = 'Sop' if dop_parent.category=='Sop' else 'Obj'
    parent_types['dop_root'] = (context.dop_root,context.sop_root if dop_category=='Sop' else context.task_root,'dopnet')
    for p in context.parents:
        expected_category = dop_category if p.role=='dop_root' else 'Obj'
        _require((p.path, p.parent_path, p.native_type) == parent_types[p.role]
            and str(PurePosixPath(p.path).parent)==p.parent_path
            and p.category == expected_category and p.identity == identity and p.version == context.version
            and p.origin == 'runtime_hom' and p.writable is True and p.instance_id,
            'ACTUAL_CONTEXT_PARENT_REQUIRED', p.role)
    nodes, parms = _parts(context)
    types = {'route': ('Dop', 'popsteerpath', context.dop_root),
             'solver': ('Dop', 'crowdsolver::3.0', context.dop_root),
             'state_stream': ('Dop', 'merge', context.dop_root),
             'route_curve': ('Sop', 'stash', context.sop_root)}
    _require(set(nodes) == set(types), 'ACTUAL_ROUTE_ROLES_REQUIRED', 'route/solver/state_stream/route_curve')
    _require(len({n.path for n in nodes.values()}) == len(nodes)
        and len({n.instance_id for n in nodes.values()}) == len(nodes), 'AMBIGUOUS_NATIVE_CONTEXT', 'role paths')
    for role, expected in types.items():
        n = nodes[role]
        _require((n.category, n.native_type, n.parent_path) == expected and _path(n.path)
            and str(PurePosixPath(n.path).parent) == n.parent_path and n.identity == identity
            and isinstance(n.instance_id, str) and n.instance_id and n.origin == 'runtime_hom'
            and n.writable is True and n.version == context.version, 'ACTUAL_TASK_OWNED_NODE_REQUIRED', role)
        _require(type(n.input_count) is int and n.input_count >= 0 and type(n.output_count) is int
            and n.output_count >= 1, 'ACTUAL_NATIVE_PORTS_REQUIRED', role)
    _require(nodes['route'].input_count >= 1 and nodes['solver'].input_count >= 3,
             'ACTUAL_NATIVE_PORTS_REQUIRED', 'route input0 and solver input2')
    required = {'weight': ('float', 'float'), 'activate': ('float', 'float'),
                'uselocalforce': ('int', 'toggle'), 'soppath': ('string', 'oppath')}
    for name, (kind, ui) in required.items():
        _require(('route', name) in parms, 'ACTUAL_NATIVE_PARAMETER_REQUIRED', name)
        _require((parms['route', name].native_type, parms['route', name].ui_type) == (kind, ui),
                 'ACTUAL_NATIVE_PARAMETER_REQUIRED', name)
    for name, token, label in (('output', '0', 'Crowds steerforce'), ('pathsource', 'sop', 'SOP'), ('method', '0', 'Curve Lookup')):
        _require(('route', name) in parms and parms['route', name].ui_type == 'ordinal',
                 'ACTUAL_NATIVE_PARAMETER_REQUIRED', name)
        _menu_value(parms['route', name], token, label)
    for p in parms.values():
        _require(p.role in nodes and p.origin == 'runtime_hom' and type(p.size) is int and p.size == 1
            and p.driven is False and p.writable is True and p.compiled_writable is True
            and p.compiled_native_type == p.native_type and p.node_path == nodes[p.role].path
            and p.identity == identity, 'COMPILED_WRITABLE_GATE_REQUIRED', p.role + '/' + p.name)
    _require(('route_curve', 'stash') in parms and parms['route_curve', 'stash'].native_type == 'data',
             'COMPILED_WRITABLE_GATE_REQUIRED', 'route_curve/stash geometry data')
    c = context.curve
    _require(c.origin == 'runtime_hom' and c.identity == identity and c.node_path == nodes['route_curve'].path
        and type(c.output_port) is int and c.output_port == 0
        and type(c.primitive_count) is int and c.primitive_count == 1,
        'ACTUAL_ROUTE_GEOMETRY_PORT_REQUIRED', 'actual owned curve output0')
    actual = curve_geometry_sha256(c.points, c.vertices, c.closed, c.primitive_type)
    _require(isinstance(c.geometry_sha256, str) and re.fullmatch('[0-9a-f]{64}', c.geometry_sha256)
        and actual == c.geometry_sha256 and parms['route_curve', 'stash'].value == c.geometry_sha256,
        'ACTUAL_ROUTE_GEOMETRY_DIGEST_REQUIRED', 'actual geometry and stored data must agree')
    baseline = (WireBinding('state_stream', 0, 'solver', 2),)
    _require(context.connections == (_expected_wires() if installed else baseline),
             'ACTUAL_STATE_STREAM_BINDING_REQUIRED', 'state stream feeds solver input2')
    if installed:
        activation = parms['route', 'activate'].value
        _require(type(activation) in (int, float) and math.isfinite(activation) and activation != 0,
                 'ROUTE_CONSUMER_GATE_REQUIRED', 'activate must be nonzero')
        for name, expected in _init_values(context).items():
            if name == 'activate':
                continue
            value = parms['route', name].value
            _require(type(value) is type(expected) and value == expected,
                     'ROUTE_CONSUMER_GATE_REQUIRED', name)
        _number(parms['route', 'weight'].value, 0, 100)
    return context


def _init_values(context):
    nodes, parms = _parts(context)
    return {'output': _menu_value(parms['route', 'output'], '0', 'Crowds steerforce'),
            'pathsource': _menu_value(parms['route', 'pathsource'], 'sop', 'SOP'),
            'method': _menu_value(parms['route', 'method'], '0', 'Curve Lookup'),
            'activate': 1., 'uselocalforce': 0, 'soppath': nodes['route_curve'].path}


def native_basis(version):
    _version(version)
    return {'operator': 'Dop/popsteerpath', 'dialog_sha256': _ROUTE_DIALOG[version],
            'geometry_doc_member': 'hou/Geometry.txt', 'geometry_doc_sha256': _GEOMETRY_DOC[version],
            'point_doc_sha256': 'fe89d913869c98ad17458239c2fa65c25280285ebd1d18bf8c0cf96d5c34f6c9',
            'face_doc_sha256': '5d871b3436304c44505081196c7dff4134851fabf2b8afa6c7077796df5b02f9',
            'semantic_contract': 'native_relative_steering_force_weight/1',
            'parm_set_doc_sha256': _PARM_DOC[version], 'vendor_recipe_sha256': _RECIPE_SHA256[version],
            'solver_states_input': 2, 'native_execution': 'NOT_RUN'}


def node_plan(version):
    native_basis(version)
    return ({'role': 'route_curve', 'category': 'Sop', 'types': ['stash'], 'context_parent_role': 'sop_network',
             'required_parms': [['stash']]},
            {'role': 'route', 'category': 'Dop', 'types': ['popsteerpath'], 'context_parent_role': 'dop_network',
             'required_parms': [[n] for n in ('output', 'activate', 'uselocalforce', 'pathsource', 'soppath', 'method', 'weight')]})


def fixed_curve_geometry_plan(version):
    """Desired native geometry operations; the adapter must read actual output."""
    operations = [{'call': 'hou.Geometry', 'args': (), 'result': 'geometry'},
                  {'call': 'Geometry.createPolygon', 'receiver': 'geometry',
                   'kwargs': {'is_closed': False}, 'result': 'curve'}]
    for index, position in enumerate(FIXED_CURVE_POINTS):
        point = 'point_' + str(index)
        operations.extend(({'call': 'Geometry.createPoint', 'receiver': 'geometry', 'args': (), 'result': point},
                           {'call': 'Point.setPosition', 'receiver': point, 'args': (position,)},
                           {'call': 'Face.addVertex', 'receiver': 'curve', 'args': ({'object_ref': point},)}))
    operations.append({'call': 'Parm.set', 'role': 'route_curve', 'parm': 'stash',
                       'args': ({'object_ref': 'geometry'},), 'value_kind': 'actual_hou_Geometry'})
    return {'basis': native_basis(version), 'target_role': 'route_curve', 'target_parm': 'stash',
            'require_compiled_writable_data_parameter': True, 'operations': tuple(operations),
            'required_readback': {'role': 'route_curve', 'output_port': 0, 'origin': 'runtime_hom',
                                  'nondegenerate_open_polygon': True, 'content_digest': 'actual_points_and_ordered_vertices'}}


def wire_plan(context):
    validate_context(context)
    return _expected_wires()


def _guard(context, written_names):
    doc = asdict(context)
    doc.pop('connections')
    doc['nodes'] = sorted(doc['nodes'], key=lambda n: n['role'])
    doc['parents'] = sorted(doc['parents'], key=lambda n: n['role'])
    doc['parameters'] = sorted(doc['parameters'], key=lambda p: (p['role'], p['name']))
    for p in doc['parameters']:
        if p['role'] == 'route' and p['name'] in written_names:
            p['value'] = None
    return _digest(doc)


def init_write_plan(context, *, route_weight):
    validate_context(context)
    values = dict(_init_values(context), weight=_number(route_weight, 0, 100))
    _, parms = _parts(context)
    writes = tuple(ParmWrite('route', n, v, parms['route', n].native_type) for n, v in values.items())
    return RoutePlan('initialize', writes, wire_plan(context), _guard(context, values), context.version)


def candidate_write_plan(context, route_weight):
    validate_context(context, installed=True)
    value = _number(route_weight, 0, 100)
    return RoutePlan('candidate', (ParmWrite('route', 'weight', value, 'float'),),
                     _expected_wires(), _guard(context, {'weight'}), context.version)


def readback_plan(plan):
    _require(isinstance(plan, RoutePlan), 'TYPED_ROUTE_PLAN_REQUIRED', 'RoutePlan')
    return {'version': plan.version, 'parameters': tuple((w.role, w.parm) for w in plan.writes),
            'required_consumer_gates': ('output', 'activate', 'uselocalforce', 'pathsource', 'soppath', 'method'),
            'geometry_output': ('route_curve', 0), 'connections': tuple(asdict(w) for w in plan.connections),
            'frozen_guard_sha256': plan.frozen_guard_sha256, 'operation_receipt': 'existing_host_transaction_only'}


def validate_readback(plan, observed):
    readback_plan(plan)
    validate_context(observed, installed=True)
    _require(observed.version == plan.version and observed.connections == plan.connections
        and _guard(observed, {w.parm for w in plan.writes}) == plan.frozen_guard_sha256,
        'FROZEN_ROUTE_CONTEXT_CHANGED', 'identity/role/geometry/menu/compiled gate/context')
    _, parms = _parts(observed)
    for w in plan.writes:
        value = parms[w.role, w.parm].value
        _require(type(value) is type(w.value) and value == w.value,
                 'ROUTE_NATIVE_READBACK_MISMATCH', w.role + '/' + w.parm)
    return {'route_weight': float(parms['route', 'weight'].value),
            'semantic_contract': 'native_relative_steering_force_weight/1', 'phase': 'PURE_PLAN_VALIDATED'}
