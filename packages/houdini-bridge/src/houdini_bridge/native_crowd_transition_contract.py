"""Pure animation_blend duration plans for the existing trusted Crowd owner.

Public duration is 0-10 seconds. Actual states, clips, geometry, native ramps
and compiled gates must come from the host. No HOM, lease or receipt is created.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS
from dataclasses import asdict, dataclass
import base64
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from .native_crowd_route_contract import HostIdentity, NodeFact, ParmFact, ParmWrite, WireBinding, MenuFact, VERSIONS

_ZERO_CONSUMER_SHA256 = 'c6d04257dcf8d2713992b82eede36adb44732686ed0187ced74741fd16e2b9ab'
_RAMP_DOC_SHA256 = '600a5069a5288905aaaa490f8e8834346a438788cd515f24db3cfed6fdaa45f3'
_ZERO_CONSUMER_BY_VERSION = {'21.0.631': _ZERO_CONSUMER_SHA256, '22.0.429': _ZERO_CONSUMER_SHA256, '22.0.459': 'c6d04257dcf8d2713992b82eede36adb44732686ed0187ced74741fd16e2b9ab'}
_RAMP_DOC_BY_VERSION = {'21.0.631': _RAMP_DOC_SHA256, '22.0.429': _RAMP_DOC_SHA256, '22.0.459': '600a5069a5288905aaaa490f8e8834346a438788cd515f24db3cfed6fdaa45f3'}


class CrowdTransitionContractError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _require(condition, code, detail):
    if not condition:
        raise CrowdTransitionContractError(code, detail)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _duration(value):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10,
             'INVALID_ANIMATION_BLEND_DURATION', 'animation_blend is duration in seconds, inclusive [0,10]')
    return float(value)


@dataclass(frozen=True)
class RampSpec:
    basis: tuple[str, ...] = ('Linear', 'Linear')
    keys: tuple[float, ...] = (0., 1.)
    values: tuple[float, ...] = (0., 1.)


@dataclass(frozen=True)
class RampFact:
    basis: tuple[str, ...]
    keys: tuple[float, ...]
    values: tuple[float, ...]
    is_color: bool
    origin: str


@dataclass(frozen=True)
class AgentGeometryFact:
    node_path: str
    output_port: int
    identity: HostIdentity
    snapshot_json: str
    origin: str


@dataclass(frozen=True)
class TransitionContext:
    version: str
    identity: HostIdentity
    task_root: str
    sop_root: str
    dop_root: str
    parents: tuple[NodeFact, ...]
    nodes: tuple[NodeFact, ...]
    parameters: tuple[ParmFact, ...]
    geometry: AgentGeometryFact
    connections: tuple[WireBinding, ...]
    transition_merge_input: int
    origin: str = 'trusted_host_runtime'


@dataclass(frozen=True)
class TransitionPlan:
    phase: str
    writes: tuple[ParmWrite, ...]
    connections: tuple[WireBinding, ...]
    frozen_guard_sha256: str
    version: str
    public_control: str = 'animation_blend'
    unit: str = 'seconds'
    invalidates_from: str = 'generation_simulation'
    schema: str = 'bridge.native-crowd-transition-plan/1'


def native_basis(version):
    _require(version in (*VERSIONS, *PREPARATION_VERSIONS), 'UNSUPPORTED_NATIVE_VERSION', str(version))
    return {'operator': 'Dop/crowdtransition::3.0', 'native_duration_parm': 'duration',
            'public_range_seconds': (0, 10), 'perform_transition_sha256': _ZERO_CONSUMER_BY_VERSION[version],
            'ramp_doc_sha256': _RAMP_DOC_BY_VERSION[version], 'solver_states_input': 2, 'solver_transitions_input': 3,
            'zero_seconds': 'native_finish_before_progress_division_without_clipgraph_or_random_delay',
            'native_execution': 'NOT_RUN'}


def node_plan(version):
    native_basis(version)
    return ({'role': 'transition', 'category': 'Dop', 'types': ['crowdtransition::3.0'],
             'context_parent_role': 'dop_network', 'required_parms': [[n] for n in
              ('instate', 'outstate', 'duration', 'blend', 'useclipgraph', 'randomstart', 'uselocal', 'useoutclip')]},
            {'role': 'trigger', 'category': 'Dop', 'types': ['crowdtrigger::2.0'],
             'context_parent_role': 'dop_network', 'required_parms': [[n] for n in
              ('type', 'fuzzyoutput', 'statedurationcondition', 'stateduration', 'triggername')]})


def ramp_constructor_plan(version):
    return {'basis': native_basis(version), 'call': 'hou.Ramp',
            'args': ({'native_enum_refs': ('hou.rampBasis.Linear', 'hou.rampBasis.Linear')}, (0., 1.), (0., 1.)),
            'target': ('transition', 'blend'), 'setter': 'Parm.set',
            'readback': ('Parm.evalAsRamp', 'Ramp.basis', 'Ramp.keys', 'Ramp.values'),
            'require_actual_float_ramp': True}


def _parts(context):
    nodes = {n.role: n for n in context.nodes}
    parms = {(p.role, p.name): p for p in context.parameters}
    _require(len(nodes) == len(context.nodes) and len(parms) == len(context.parameters),
             'AMBIGUOUS_TRANSITION_CONTEXT', 'role or parameter')
    return nodes, parms


def _menu_value(fact, token, label):
    menu = fact.menu
    _require(isinstance(menu, MenuFact) and menu.origin == 'runtime_hom' and menu.storage in ('index', 'token')
        and isinstance(menu.items, tuple) and all(isinstance(item, tuple) and len(item) == 2 and all(isinstance(v, str) for v in item) for item in menu.items)
        and len({item[0] for item in menu.items}) == len(menu.items) and (token, label) in menu.items,
        'ACTUAL_TRANSITION_MENU_REQUIRED', fact.role + '/' + fact.name)
    _require(fact.native_type == ('int' if menu.storage == 'index' else 'string') and fact.ui_type == 'ordinal',
             'ACTUAL_TRANSITION_MENU_REQUIRED', fact.name + ' storage/type')
    index = next(i for i, item in enumerate(menu.items) if item == (token, label))
    expected = {'single': 1, 'ignore': 2, '10': 10, '2': 2}[token]
    _require(index == expected, 'ACTUAL_TRANSITION_MENU_REQUIRED', fact.name + ' captured menu index')
    return index if menu.storage == 'index' else token


def _ramp(value, *, linear=False):
    _require(isinstance(value, RampFact) and value.origin == 'runtime_hom' and value.is_color is False
        and isinstance(value.basis, tuple) and isinstance(value.keys, tuple) and isinstance(value.values, tuple)
        and len(value.basis) == len(value.keys) == len(value.values) and len(value.keys) >= 2
        and all(isinstance(b, str) and b for b in value.basis)
        and all(type(v) in (int, float) and math.isfinite(v) for v in (*value.keys, *value.values))
        and all(0 <= k <= 1 for k in value.keys) and list(value.keys) == sorted(set(value.keys)),
        'ACTUAL_NATIVE_FLOAT_RAMP_REQUIRED', 'evalAsRamp basis/keys/values')
    if linear:
        _require((value.basis, value.keys, value.values) == (RampSpec().basis, RampSpec().keys, RampSpec().values),
                 'FIXED_LINEAR_TRANSITION_RAMP_REQUIRED', 'native linear progress 0 to 1')


def _payload(payload):
    _require(isinstance(payload, dict) and payload.get('encoding') == 'base64'
        and isinstance(payload.get('data'), str), 'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', 'serialized native data')
    try:
        raw = base64.b64decode(payload['data'], validate=True)
    except (ValueError, TypeError) as exc:
        raise CrowdTransitionContractError('ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', str(exc)) from exc
    _require(raw and type(payload.get('byte_count')) is int and len(raw) == payload['byte_count']
        and hashlib.sha256(raw).hexdigest() == payload.get('sha256'),
        'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', 'native bytes/hash')




def _native_payload_guard(native):
    def binary(value):
        _payload(value)
        return {'bytes': value['byte_count'], 'sha256': value['sha256']}
    def text(value):
        _require(isinstance(value, str) and value, 'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', 'native rig/layer text')
        raw = value.encode('utf-8')
        return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return {'geometry_bgeo': binary(native['geometry_bgeo']), 'agents': [
        {'rig_json': text(agent['rig_json']), 'shape_library_bgeo': binary(agent['shape_library_bgeo']),
         'shapes': sorted([{'name': item['name'], 'bgeo': binary(item['bgeo'])}
                           for item in agent['shapes']], key=lambda item: item['name']),
         'layers': sorted([{'name': item['name'], 'json': text(item['json'])}
                           for item in agent['layers']], key=lambda item: item['name']),
         'clips': sorted([{'name': item['name'], 'local_clip_binary': binary(item['local_clip_binary'])}
                          for item in agent['clips']], key=lambda item: item['name'])}
        for agent in native['agents']]}


def _native_definition(agent, payload):
    rig, library, layers = agent['rig'], agent['shape_library'], agent['layers']
    transforms = rig['transform_names']; count = len(transforms)
    finite_vector = lambda v, size: isinstance(v, list) and len(v) == size and all(
        type(x) in (int, float) and math.isfinite(x) for x in v)
    _require(agent['native_type'] == 'PackedAgent' and count > 0 and len(set(transforms)) == count
        and all(isinstance(n, str) and n for n in transforms) and rig['external_reference'] is False
        and len(rig['parents']) == count and all(type(i) is int and -1 <= i < count for i in rig['parents'])
        and len(rig['rest_local']) == len(rig['rest_world']) == count
        and all(finite_vector(m, 16) for m in rig['rest_local'] + rig['rest_world']),
        'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'embedded rig transforms/rest pose')
    shapes = library['shapes']; shape_names = [s['name'] for s in shapes]
    _require(library['external_reference'] is False and shapes and len(set(shape_names)) == len(shapes)
        and all(isinstance(n, str) and n for n in shape_names),
        'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'embedded actual shapes')
    for shape in shapes:
        geometry = shape['geometry']; points = geometry['points']; polygons = geometry['polygons']
        indices = [p['number'] for p in points]
        _require(points and polygons and all(type(i) is int and i >= 0 for i in indices)
            and len(set(indices)) == len(indices) and all(finite_vector(p['position'], 3) for p in points)
            and len({tuple(p['position']) for p in points}) >= 3,
            'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'actual shape points and topology')
        for polygon in polygons:
            vertices = polygon['point_indices']
            _require(type(polygon['closed']) is bool and isinstance(vertices, list) and len(vertices) >= 3
                and len(set(vertices)) >= 3 and all(type(i) is int and i in indices for i in vertices),
                'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'actual polygon point bindings')
    layer_names = [layer['name'] for layer in layers]
    _require(layers and len(set(layer_names)) == len(layers) and all(isinstance(n, str) and n for n in layer_names)
        and agent['current_layers'] and set(agent['current_layers']) <= set(layer_names),
        'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'actual active shape layers')
    for layer in layers:
        _require(layer['external_reference'] is False and layer['bindings'],
                 'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'embedded layer bindings')
        for binding in layer['bindings']:
            _require(type(binding['transform']) is int and 0 <= binding['transform'] < count
                and binding['shape'] in shape_names and type(binding['attached']) is bool
                and type(binding['deforming']) is bool and finite_vector(binding['bounds_scale'], 3),
                'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'actual rig/shape binding')
    _require(isinstance(payload['rig_json'], str) and payload['rig_json']
        and [s['name'] for s in payload['shapes']] == shape_names
        and [l['name'] for l in payload['layers']] == layer_names
        and all(isinstance(l['json'], str) and l['json'] for l in payload['layers']),
        'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', 'rig/shape/layer native content')
    _payload(payload['shape_library_bgeo'])
    for shape in payload['shapes']: _payload(shape['bgeo'])


def _geometry(context, nodes, parms):
    fact = context.geometry
    _require(isinstance(fact, AgentGeometryFact) and fact.origin == 'runtime_hom'
        and fact.identity == context.identity and fact.node_path == nodes['agent_definition'].path
        and type(fact.output_port) is int and fact.output_port == 0,
        'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'native agent definition output0')
    try:
        snap = json.loads(fact.snapshot_json); content = snap['content']
        _require(snap['schema'] == 'bridge.w5.synthetic_agent_snapshot/1.0' and snap['houdini_version'] == context.version
            and _digest(content) == snap['content_sha256'], 'ACTUAL_AGENT_GEOMETRY_DIGEST_REQUIRED', 'existing native snapshot content')
        _native_payload_guard(snap['native_payloads'])
        _require(type(content['point_count']) is int and content['point_count'] > 0 and content['agents'],
                 'ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', 'actual PackedAgent geometry')
        names = [parms[role, 'statename'].value for role in ('source_state', 'target_state')]
        selected = [parms[role, 'clipname'].value for role in ('source_state', 'target_state')]
        _require(len(set(names)) == 2 and len(set(selected)) == 2 and all(isinstance(v, str) and v
            and not re.search(r'[\s*?\[\]^]', v) for v in names + selected),
            'TWO_DISTINCT_ACTUAL_STATES_AND_CLIPS_REQUIRED', 'exact actual state and clip names')
        _require(parms['source', 'state'].value == names[0], 'ACTUAL_SOURCE_STATE_REQUIRED', 'source starts in source state')
        _require(len(snap['native_payloads']['agents']) == len(content['agents']),
                 'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', 'native agent payload count')
        for agent, payload in zip(content['agents'], snap['native_payloads']['agents']):
            _native_definition(agent, payload)
            clips = {c['name']: c for c in agent['clips']}
            _require(len(clips) == len(agent['clips']) and all(name in clips for name in selected),
                     'TWO_DISTINCT_ACTUAL_STATES_AND_CLIPS_REQUIRED', 'available definition clips')
            sample_hashes = []
            for name in selected:
                c = clips[name]
                _require(c['external_reference'] is False and type(c['sample_count']) is int and c['sample_count'] >= 2
                    and all(type(c[k]) in (int, float) and math.isfinite(c[k]) for k in ('sample_rate', 'start_time', 'length_seconds'))
                    and c['sample_rate'] > 0 and c['length_seconds'] > 0
                    and len(c['local_samples']) == c['sample_count'] and len(c['world_samples']) == c['sample_count']
                    and all(len(sample) == len(agent['rig']['transform_names']) and all(len(matrix) == 16
                        and all(type(v) in (int, float) and math.isfinite(v) for v in matrix) for matrix in sample)
                        for sample in (*c['local_samples'], *c['world_samples'])),
                    'ACTUAL_CLIP_SAMPLES_AND_TIMING_REQUIRED', name)
                sample_hashes.append(_digest(c['local_samples']))
                matching = [p for p in payload['clips'] if p['name'] == name]
                _require(len(matching) == 1, 'ACTUAL_AGENT_NATIVE_PAYLOAD_REQUIRED', name)
                _payload(matching[0]['local_clip_binary'])
            _require(sample_hashes[0] != sample_hashes[1], 'DISTINCT_NATIVE_ANIMATION_DATA_REQUIRED', 'two actual animations')
            _require(agent['current_clips'] == [selected[0]] and agent['clip_times'] == [clips[selected[0]]['start_time']]
                and agent['clip_weights'] == [1.0], 'ACTUAL_SOURCE_CLIP_TIMING_REQUIRED', 'actual startTime, no inferred fps')
        return content
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CrowdTransitionContractError): raise
        raise CrowdTransitionContractError('ACTUAL_OWNED_AGENT_GEOMETRY_REQUIRED', str(exc)) from exc


def _wire_capacity(wire, nodes):
    _require(wire.source_role in nodes and wire.target_role in nodes and type(wire.output_port) is int
        and type(wire.input_port) is int and 0 <= wire.output_port < nodes[wire.source_role].output_count
        and 0 <= wire.input_port < nodes[wire.target_role].input_count,
        'ACTUAL_TRANSITION_CONNECTIONS_REQUIRED', 'actual source/output and target/input capacity')
    _require(wire.target_role not in ('wander', 'route') or wire.input_port == 0,
             'ACTUAL_STATE_AND_TRANSITION_STREAM_REQUIRED', 'steering state stream uses native input0')


def _reachable(context, source_role, target_port):
    adjacency = {}
    for w in context.connections:
        if w.output_port != 0: continue
        if w.target_role == 'solver':
            if w.input_port != target_port: continue
        elif w.target_role not in ('states', 'wander', 'route'): continue
        elif w.target_role in ('wander', 'route') and w.input_port != 0: continue
        adjacency.setdefault(w.source_role, []).append(w.target_role)
    pending = [(source_role, False)]; seen = set()
    while pending:
        role, through_states = pending.pop()
        through_states = through_states or role == 'states'
        if role == 'solver':
            if through_states: return True
            continue
        state = (role, through_states)
        if state in seen: continue
        seen.add(state)
        pending.extend((target, through_states) for target in adjacency.get(role, ()))
    return False


def validate_context(context, *, installed=False):
    _require(isinstance(context, TransitionContext), 'TYPED_TRANSITION_CONTEXT_REQUIRED', 'TransitionContext')
    native_basis(context.version); identity = context.identity
    _require(isinstance(identity, HostIdentity) and context.origin == 'trusted_host_runtime'
        and all(isinstance(v, str) and v for v in (identity.task_id, identity.resource_id, identity.content_version,
        identity.session_id, identity.process_generation)) and type(identity.scene_epoch) is int and identity.scene_epoch >= 0,
        'ACTUAL_TRANSITION_IDENTITY_REQUIRED', 'host identity')
    _require(isinstance(context.nodes, tuple) and isinstance(context.parameters, tuple)
        and all(isinstance(n, NodeFact) for n in context.nodes) and all(isinstance(p, ParmFact) for p in context.parameters),
        'TYPED_TRANSITION_CONTEXT_REQUIRED', 'nodes and parameter facts')
    _require(all(isinstance(p, str) and p.startswith('/obj/') and str(PurePosixPath(p)) == p
        and '..' not in p.split('/') for p in (context.task_root, context.sop_root, context.dop_root)),
        'ACTUAL_TRANSITION_PARENT_REQUIRED', 'canonical actual task paths')
    parents = {'task_root': (context.task_root, '/obj', 'subnet'),
               'sop_root': (context.sop_root, context.task_root, 'geo'), 'dop_root': (context.dop_root, context.task_root, 'dopnet')}
    _require(isinstance(context.parents, tuple) and len(context.parents) == 3
        and all(isinstance(p, NodeFact) for p in context.parents) and {p.role for p in context.parents} == set(parents),
        'ACTUAL_TRANSITION_PARENT_REQUIRED', 'subnet/geo/dopnet')
    dop_parent = next(p for p in context.parents if p.role=='dop_root')
    dop_category = 'Sop' if dop_parent.category=='Sop' else 'Obj'
    parents['dop_root'] = (context.dop_root,context.sop_root if dop_category=='Sop' else context.task_root,'dopnet')
    for p in context.parents:
        expected_category = dop_category if p.role=='dop_root' else 'Obj'
        _require((p.path, p.parent_path, p.native_type) == parents[p.role] and p.category == expected_category
            and p.path.startswith(p.parent_path + '/') and '/' not in p.path[len(p.parent_path)+1:]
            and p.identity == identity and p.version == context.version and p.origin == 'runtime_hom'
            and p.writable is True, 'ACTUAL_TRANSITION_PARENT_REQUIRED', p.role)
    nodes, parms = _parts(context)
    required = {'agent_definition': ('Sop', 'stash'), 'source': ('Sop', 'crowdsource::3.0'),
                'population': ('Dop', 'popsource::2.0'), 'source_state': ('Dop', 'crowdstate::3.0'),
                'target_state': ('Dop', 'crowdstate::3.0'), 'trigger': ('Dop', 'crowdtrigger::2.0'),
                'transition': ('Dop', 'crowdtransition::3.0'), 'states': ('Dop', 'merge'),
                'transitions': ('Dop', 'merge'), 'solver': ('Dop', 'crowdsolver::3.0')}
    optional = {'wander': ('Dop', 'popsteerwander'), 'route': ('Dop', 'popsteerpath')}
    _require(set(required) <= set(nodes) <= set(required) | set(optional), 'ACTUAL_TRANSITION_ROLES_REQUIRED', 'actual owned roles')
    _require(len({n.path for n in nodes.values()}) == len(nodes) and len({n.instance_id for n in nodes.values()}) == len(nodes),
             'AMBIGUOUS_TRANSITION_CONTEXT', 'node identities')
    for role, n in nodes.items():
        parent = context.sop_root if n.category == 'Sop' else context.dop_root
        _require((n.category, n.native_type) == (required | optional)[role] and n.parent_path == parent
            and n.path.startswith(parent + '/') and '/' not in n.path[len(parent)+1:] and n.instance_id
            and n.identity == identity and n.version == context.version and n.origin == 'runtime_hom' and n.writable is True,
            'ACTUAL_TRANSITION_NODE_REQUIRED', role)
        _require(type(n.input_count) is int and n.input_count >= 0 and type(n.output_count) is int and n.output_count > 0,
                 'ACTUAL_TRANSITION_PORTS_REQUIRED', role)
    for p in parms.values():
        _require(p.role in nodes and p.node_path == nodes[p.role].path and p.identity == identity
            and p.origin == 'runtime_hom' and type(p.size) is int and p.size == 1 and p.driven is False
            and p.writable is True and p.compiled_writable is True and p.compiled_native_type == p.native_type,
            'TRANSITION_COMPILED_WRITABLE_GATE_REQUIRED', p.role + '/' + p.name)
        _require((p.native_type == 'float' and type(p.value) in (int, float) and math.isfinite(p.value))
            or (p.native_type == 'int' and type(p.value) is int)
            or (p.native_type == 'string' and isinstance(p.value, str))
            or (p.native_type == 'ramp_float' and isinstance(p.value, RampFact)),
            'ACTUAL_TRANSITION_PARAMETER_REQUIRED', p.role + '/' + p.name + ' value type')
    fields = {'transition': {'duration': ('float', 'float'), 'blend': ('ramp_float', 'ramp_flt'),
                'instate': ('string', 'string'), 'outstate': ('string', 'string'),
                **{n: ('int', 'toggle') for n in ('useclipgraph', 'randomstart', 'uselocal', 'useoutclip')}},
              'source': {'state': ('string', 'string')}, 'population': {'soppath': ('string', 'oppath')},
              'trigger': {'fuzzyoutput': ('int', 'toggle'), 'stateduration': ('float', 'float'), 'triggername': ('string', 'string')}}
    for role in ('source_state', 'target_state'):
        fields[role] = {'statename': ('string', 'string'), 'clipname': ('string', 'string'), 'uselocal': ('int', 'toggle')}
    for role, names in fields.items():
        for name, kind in names.items():
            _require((role, name) in parms and (parms[role, name].native_type, parms[role, name].ui_type) == kind,
                     'ACTUAL_TRANSITION_PARAMETER_REQUIRED', role + '/' + name)
    for role in ('source_state', 'target_state'):
        for name, token, label in (('clipassignment', 'single', 'Single Clip'), ('rbdragdoll', 'ignore', 'Ignore')):
            _require((role, name) in parms and parms[role, name].value == _menu_value(parms[role, name], token, label),
                     'ACTUAL_SINGLE_CLIP_STATE_REQUIRED', role + '/' + name)
        _require(parms[role, 'uselocal'].value == 0, 'ACTUAL_SINGLE_CLIP_STATE_REQUIRED', role + '/uselocal')
    for name, token, label in (('type', '10', 'Current State Duration'), ('statedurationcondition', '2', 'Greater Than')):
        _require(('trigger', name) in parms and parms['trigger', name].value == _menu_value(parms['trigger', name], token, label),
                 'ACTUAL_TRANSITION_TRIGGER_REQUIRED', name)
    threshold = parms['trigger', 'stateduration'].value
    _require(type(threshold) in (int, float) and math.isfinite(threshold) and threshold >= 0
        and parms['trigger', 'fuzzyoutput'].value == 0 and parms['trigger', 'triggername'].value,
        'ACTUAL_TRANSITION_TRIGGER_REQUIRED', 'actual trigger threshold/configuration')
    _require(parms['population', 'soppath'].value == nodes['source'].path,
             'ACTUAL_SOURCE_POPULATION_REQUIRED', 'actual source SOP path')
    _ramp(parms['transition', 'blend'].value, linear=installed)
    _geometry(context, nodes, parms)
    _require(isinstance(context.connections, tuple) and all(isinstance(w, WireBinding) for w in context.connections),
             'ACTUAL_TRANSITION_CONNECTIONS_REQUIRED', 'native wires')
    targets = set()
    for w in context.connections:
        _wire_capacity(w, nodes)
        _require((w.target_role, w.input_port) not in targets,
            'ACTUAL_TRANSITION_CONNECTIONS_REQUIRED', 'valid unique actual ports')
        targets.add((w.target_role, w.input_port))
    _require(WireBinding('agent_definition', 0, 'source', 0) in context.connections
        and WireBinding('population', 0, 'solver', 1) in context.connections
        and WireBinding('transitions', 0, 'solver', 3) in context.connections
        and all(_reachable(context, r, 2) for r in ('source_state', 'target_state')),
        'ACTUAL_STATE_AND_TRANSITION_STREAM_REQUIRED', 'both states through owned states merge to solver2, transition stream to solver3')
    _require(type(context.transition_merge_input) is int and 0 <= context.transition_merge_input < nodes['transitions'].input_count,
             'ACTUAL_TRANSITION_MERGE_PORT_REQUIRED', 'actual merge input')
    added = _transition_wires(context)
    for w in added: _wire_capacity(w, nodes)
    _require(all(w in context.connections for w in added) if installed else all(
        (w.target_role, w.input_port) not in targets for w in added),
        'ACTUAL_TRANSITION_MERGE_PORT_REQUIRED', 'actual free or installed transition ports')
    if installed:
        for name, value in _init_values(context).items():
            if name == 'blend': continue
            _require(type(parms['transition', name].value) is type(value) and parms['transition', name].value == value,
                     'TRANSITION_CONSUMER_GATE_REQUIRED', name)
        _duration(parms['transition', 'duration'].value)
    return context


def _transition_wires(context):
    return (WireBinding('trigger', 0, 'transition', 0),
            WireBinding('transition', 0, 'transitions', context.transition_merge_input))


def wire_plan(context):
    validate_context(context)
    return context.connections + _transition_wires(context)


def _init_values(context):
    _, parms = _parts(context)
    return {'instate': parms['source_state', 'statename'].value, 'outstate': parms['target_state', 'statename'].value,
            'useclipgraph': 0, 'randomstart': 0, 'uselocal': 0, 'useoutclip': 0, 'blend': RampSpec()}


def _guard(context, written):
    doc = asdict(context); doc.pop('connections')
    doc['nodes'] = sorted(doc['nodes'], key=lambda n: n['role'])
    doc['parents'] = sorted(doc['parents'], key=lambda n: n['role'])
    doc['parameters'] = sorted(doc['parameters'], key=lambda p: (p['role'], p['name']))
    for p in doc['parameters']:
        if p['role'] == 'transition' and p['name'] in written: p['value'] = None
    snap = json.loads(context.geometry.snapshot_json)
    doc['geometry']['snapshot_json'] = _canonical({'content': snap['content'],
        'native_payloads': _native_payload_guard(snap['native_payloads'])}).decode()
    return _digest(doc)


def init_write_plan(context, *, animation_blend):
    validate_context(context)
    values = dict(_init_values(context), duration=_duration(animation_blend)); _, parms = _parts(context)
    return TransitionPlan('initialize', tuple(ParmWrite('transition', name, value, parms['transition', name].native_type)
        for name, value in values.items()), wire_plan(context), _guard(context, values), context.version)


def candidate_write_plan(context, animation_blend):
    validate_context(context, installed=True)
    return TransitionPlan('candidate', (ParmWrite('transition', 'duration', _duration(animation_blend), 'float'),),
        context.connections, _guard(context, {'duration'}), context.version)


def readback_plan(plan):
    _require(isinstance(plan, TransitionPlan), 'TYPED_TRANSITION_PLAN_REQUIRED', 'TransitionPlan')
    return {'version': plan.version, 'parameters': tuple((w.role, w.parm) for w in plan.writes),
            'ramp': ('transition', 'blend', 'actual_evalAsRamp'), 'native_agent_geometry': ('agent_definition', 0),
            'connections': tuple(asdict(w) for w in plan.connections), 'frozen_guard_sha256': plan.frozen_guard_sha256,
            'native_operation_receipt': 'existing_owner_only'}


def validate_readback(plan, context):
    readback_plan(plan); validate_context(context, installed=True)
    _require(context.version == plan.version and set(context.connections) == set(plan.connections)
        and _guard(context, {w.parm for w in plan.writes}) == plan.frozen_guard_sha256,
        'FROZEN_TRANSITION_CONTEXT_CHANGED', 'identity/geometry/clips/ramp/gates/ports')
    _, parms = _parts(context)
    for w in plan.writes:
        value = parms[w.role, w.parm].value
        if isinstance(w.value, RampSpec):
            _ramp(value, linear=True)
        else:
            _require(type(value) is type(w.value) and value == w.value,
                     'TRANSITION_NATIVE_READBACK_MISMATCH', w.parm)
    return {'animation_blend': float(parms['transition', 'duration'].value), 'unit': 'seconds',
            'phase': 'PURE_PLAN_VALIDATED', 'native_execution': 'NOT_RUN'}
