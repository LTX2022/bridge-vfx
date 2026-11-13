"""G03 pure plans and collectors for an authenticated, owned SOP transaction.

The host supplies native observations and authenticates basis provenance. No
geometry is cooked or mutated here. Parameter evidence never proves downstream
consumption. Plan seals are fresh process-local guards, not durable receipts.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import PurePosixPath
import secrets
from typing import Mapping

VERSIONS = ('21.0.631', '22.0.429')
ROLE = 'geometry_deform'
BASIS_SCHEMA = 'bridge.geometry-deform-basis/1'
REGISTRATION_SCHEMA = 'bridge.geometry-deform-initialization/1'
GENERATOR = 'houdini_bridge.native_geometry_controls_program.source_program/1'
GATES = {
    'group': ('string', ''), 'class': ('ordinal', 'point'),
    'autobind': ('toggle', 1), 'bindings': ('multiparm', 0),
    'groupautobind': ('toggle', 0), 'groupbindings': ('multiparm', 0),
    'exportlist': ('string', 'P'), 'vex_outputmask': ('string', 'P'),
    'vex_updatenmls': ('toggle', 0), 'vex_inplace': ('toggle', 0),
    'vex_matchattrib': ('string', 'id'), 'vex_precision': ('string', '64'),
}
MISSING_EVIDENCE = (
    'same_build_vex_compile_and_actual_deformed_P',
    'same_build_zero_program_P_export_masks_and_no_N_update_behavior',
    'actual_preserved_topology_N_and_unrelated_attributes',
    'downstream_transform_and_copytopoints_consumption',
    'preserved_instance_point_ID_P_pscale_count_and_seed',
    'save_reopen_and_cross_frame_rest_basis_stability',
)
_SEAL_KEY = secrets.token_bytes(32)


class GeometryControlsError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _fail(code, detail):
    raise GeometryControlsError(code, detail)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise GeometryControlsError('GEOMETRY_INVALID_FACT', str(error)) from error


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _number(value, label, minimum=-1e12, maximum=1e12):
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        _fail('GEOMETRY_INVALID_NUMBER', label)
    if not math.isfinite(value):
        _fail('GEOMETRY_INVALID_NUMBER', label)
    return float(value)


def _path(value):
    return (isinstance(value, str) and value.startswith('/') and value != '/'
            and str(PurePosixPath(value)) == value
            and all(part not in ('.', '..') for part in value.split('/')))


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def _attribute(source, name, kind, size):
    attributes = source.get('point_attributes')
    if not isinstance(attributes, Mapping):
        _fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', 'actual point attribute mapping required')
    attribute = attributes.get(name, {})
    if not isinstance(attribute, Mapping):
        _fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', name)
    precision = ('int32',) if kind == 'integer' else ('float32', 'float64')
    values = attribute.get('values')
    if (attribute.get('owner') != 'point' or attribute.get('type') != kind
            or type(attribute.get('size')) is not int or attribute['size'] != size
            or attribute.get('precision') not in precision or attribute.get('is_array') is not False
            or not isinstance(values, list) or len(values) != source['points']):
        _fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', name + '/class, storage, tuple or values')
    if kind == 'integer':
        if any(type(value) is not int or not -2147483648 <= value <= 2147483647 for value in values):
            _fail('GEOMETRY_STABLE_IDS_REQUIRED', 'actual int32 point IDs required')
        if len(set(values)) != len(values):
            _fail('GEOMETRY_STABLE_IDS_REQUIRED', 'actual point IDs must be unique')
    else:
        for vector in values:
            if not isinstance(vector, list) or len(vector) != size:
                _fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', name + '/tuple values')
            for component in vector:
                _number(component, name)
            if name == 'N' and not math.isclose(math.fsum(component ** 2 for component in vector),
                                               1., rel_tol=0, abs_tol=1e-6):
                _fail('GEOMETRY_REST_NORMAL_REQUIRED', 'actual unit point N required; no implicit normalization')
    return values


def source_geometry_sha256(source):
    if (not isinstance(source, Mapping) or source.get('origin') != 'runtime_hom'
            or not _path(source.get('node_path')) or source.get('space') != 'sop_local_rest'
            or source.get('unit') != 'SU' or type(source.get('output')) is not int or source['output'] != 0
            or type(source.get('points')) is not int or not 1 <= source['points'] <= 100000):
        _fail('GEOMETRY_REST_SOURCE_REQUIRED', 'bounded observed rest SOP output 0 required')
    _number(source.get('frame'), 'source frame')
    for name, kind, size in (('P', 'float', 3), ('N', 'float', 3), ('id', 'integer', 1)):
        _attribute(source, name, kind, size)
    topology = source.get('polygons')
    if not isinstance(topology, list) or not 1 <= len(topology) <= 100000:
        _fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'actual polygon connectivity required')
    vertex_count = 0
    for polygon in topology:
        if not isinstance(polygon, list) or len(polygon) < 3:
            _fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'explicit unpacked polygon source required')
        vertex_count += len(polygon)
        if vertex_count > 1000000 or any(type(index) is not int or not 0 <= index < source['points'] for index in polygon):
            _fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'bounded valid point connectivity required')
    if source.get('primitive_types') != ['Polygon'] * len(topology):
        _fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'packed, volume and mixed carriers unsupported')
    return _hash(dict(source))


def basis_content_sha256(basis):
    return _hash({key: value for key, value in basis.items() if key != 'content_sha256'})


def freeze_basis(version, source, *, local_x_axis, task_id, task_root, input_version, basis_input_sha256):
    """Freeze independently observed geometry and explicitly authenticated axes.

    The digest records identity only. The host verifies ownership, input hashes
    and rest-space provenance before calling; arbitrary client JSON is untrusted.
    """
    if type(version) is not str or version not in (*VERSIONS, *PREPARATION_VERSIONS):
        _fail('UNSUPPORTED_NATIVE_VERSION', str(version))
    if (not isinstance(task_id, str) or not task_id or not _path(task_root)
            or not isinstance(input_version, str) or not input_version or not _digest(basis_input_sha256)):
        _fail('GEOMETRY_BASIS_REQUIRED', 'authenticated task, input version and basis SHA required')
    source_hash = source_geometry_sha256(source)
    if not source['node_path'].startswith(task_root + '/'):
        _fail('GEOMETRY_OWNED_SOURCE_REQUIRED', 'source outside task root')
    if (not isinstance(local_x_axis, (list, tuple)) or len(local_x_axis) != 3
            or any(type(component) not in (int, float) for component in local_x_axis)
            or list(local_x_axis) != [1, 0, 0]):
        _fail('GEOMETRY_LOCAL_X_AXIS_REQUIRED', 'explicit source SOP local +X basis required')
    positions = source['point_attributes']['P']['values']
    bbox_min_x = min(position[0] for position in positions)
    span_x = max(position[0] for position in positions) - bbox_min_x
    if not math.isfinite(span_x) or span_x <= 0:
        _fail('GEOMETRY_POSITIVE_X_SPAN_REQUIRED', 'no guessed wavelength for degenerate source')
    basis = dict(schema=BASIS_SCHEMA, origin='authenticated_host_basis',
                 native_version=version, task_id=task_id, task_root=task_root,
                 input_version=input_version, basis_input_sha256=basis_input_sha256,
                 source_node_path=source['node_path'], source_geometry_sha256=source_hash,
                 local_x_axis=[1., 0., 0.], bbox_min_x=float(bbox_min_x), span_x=float(span_x),
                 space='sop_local_rest', unit='SU', id_attribute='id', phase=0.)
    basis['content_sha256'] = basis_content_sha256(basis)
    return basis


def validate_context(version, context):
    if not isinstance(context, Mapping) or not isinstance(context.get('basis'), Mapping):
        _fail('GEOMETRY_BASIS_REQUIRED', 'frozen basis and independent source observations required')
    basis = context['basis']
    rebuilt = freeze_basis(version, context.get('source'), local_x_axis=basis.get('local_x_axis'),
        task_id=basis.get('task_id'), task_root=basis.get('task_root'), input_version=basis.get('input_version'),
        basis_input_sha256=basis.get('basis_input_sha256'))
    if dict(basis) != rebuilt:
        _fail('GEOMETRY_BASIS_CHANGED', 'source, frame, coordinate basis or digest differs')
    nodes = context.get('nodes', {})
    if not isinstance(nodes, Mapping):
        _fail('GEOMETRY_OWNED_GRAPH_REQUIRED', 'observed nodes required')
    for role, allowed in (('instance_source', ('sphere', 'grid')),
                          (ROLE, ('attribwrangle',)), ('instance_transform', ('xform',))):
        node = nodes.get(role, {})
        if (not isinstance(node, Mapping) or node.get('origin') != 'runtime_hom'
                or node.get('task_owned') is not True or node.get('task_id') != basis['task_id']
                or node.get('task_root') != basis['task_root'] or node.get('input_version') != basis['input_version']
                or node.get('native_version') != version or not _path(node.get('path'))
                or not node['path'].startswith(basis['task_root'] + '/')
                or node.get('type') not in allowed or node.get('category') != 'sop'
                or node.get('space') != 'sop_local_rest'
                or node.get('editable') is not True or node.get('bypassed') is not False):
            _fail('GEOMETRY_OWNED_GRAPH_REQUIRED', role)
    paths = [nodes[role]['path'] for role in ('instance_source', ROLE, 'instance_transform')]
    if (len(set(paths)) != 3 or len({str(PurePosixPath(path).parent) for path in paths}) != 1
            or paths[0] != basis['source_node_path']):
        _fail('GEOMETRY_SOURCE_SPACE_CHANGED', 'distinct nodes in the same source SOP space required')
    if nodes['instance_source'].get('inputs') != []:
        _fail('GEOMETRY_REST_SOURCE_REQUIRED', 'independent procedural source with no feedback inputs required')
    for downstream, upstream in ((ROLE, 'instance_source'), ('instance_transform', ROLE)):
        wires = nodes[downstream].get('inputs')
        expected = [{'input_index': 0, 'output_index': 0, 'node_path': nodes[upstream]['path']}]
        if (not isinstance(wires, list) or wires != expected
                or type(wires[0].get('input_index')) is not int or type(wires[0].get('output_index')) is not int):
            _fail('GEOMETRY_SOURCE_CONNECTION_REQUIRED', downstream + '/actual source before scale/rotation')
    return rebuilt


def source_program(version, value, context):
    basis = validate_context(version, context)
    value = _number(value, 'deformation', 0, 100)
    if value == 0:
        program = 'float deform_amplitude = 0;\n'
    else:
        program = ('float deform_amplitude = ' + format(value, '.17g') + ';\n'
                   + 'float deform_phase = ((@P.x - (' + format(basis['bbox_min_x'], '.17g') + ')) / ('
                   + format(basis['span_x'], '.17g') + ')) * 6.2831853071795862;\n'
                   + '@P += deform_amplitude * sin(deform_phase) * v@N;\n')
    return dict(generator=GENERATOR, domain_pack='procedural_geometry_v1', control='deformation',
                native_version=version, role=ROLE, parm='snippet', basis_sha256=basis['content_sha256'],
                program=program, sha256=hashlib.sha256(program.encode('utf-8')).hexdigest(),
                status='BLOCKED', evidence_scope='program_candidate', missing_evidence=list(MISSING_EVIDENCE))


def initialization_plan():
    return [dict(role=ROLE, parm=name, value=value, native_type=kind, phase='deform_scope',
                 require_writable=True, require_readback=True) for name, (kind, value) in GATES.items()]


def collect_parameters(node, observe_parameter):
    """Delegate to the existing host's actual template/channel/HOM collector."""
    return {(ROLE, name): observe_parameter(node, name) for name in (*GATES, 'snippet')}


def _registered_context(context, basis):
    """Check a host-collected initialization record, never authenticate JSON.

    The host creates this immutable record only after its authorized new-node
    initialization and actual zero-program/gate readback, and authenticates the
    record's ownership against its server-side task registry before calling.
    """
    expected = dict(schema=REGISTRATION_SCHEMA, origin='runtime_hom', initialized=True, registered=True,
        generator=GENERATOR, task_id=basis['task_id'], task_root=basis['task_root'],
        input_version=basis['input_version'], native_version=basis['native_version'],
        node_path=context['nodes'][ROLE]['path'], basis_sha256=basis['content_sha256'],
        initial_program_sha256=hashlib.sha256(b'float deform_amplitude = 0;\n').hexdigest(),
        gates_sha256=_hash(GATES))
    registration = context.get('initialization')
    if not isinstance(registration, Mapping) or _json(registration) != _json(expected):
        _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED', 'authenticated host record and canonical basis required')


def collect_source_geometry(geometry, observe_geometry):
    """Validate a host collector snapshot of already obtained native geometry.

    No node.geometry()/geometryAtFrame() call is made. The host decides whether
    acquiring geometry is authorized, and collects actual P/N/id and topology.
    """
    if geometry is None:
        _fail('GEOMETRY_REST_SOURCE_REQUIRED', 'already obtained geometry required')
    observed = observe_geometry(geometry)
    source_geometry_sha256(observed)
    return copy.deepcopy(observed)


def _parameters(parameters):
    if not isinstance(parameters, Mapping):
        _fail('GEOMETRY_PARAMETERS_REQUIRED', 'actual host parameter observations required')
    result = {}
    for name, kind in [(name, gate[0]) for name, gate in GATES.items()] + [('snippet', 'string')]:
        fact = parameters.get((ROLE, name), {})
        if (not isinstance(fact, Mapping) or fact.get('origin') != 'runtime_hom' or fact.get('type') != kind
                or type(fact.get('size')) is not int or fact['size'] != 1
                or any(fact.get(flag) is not False for flag in ('driven', 'locked', 'disabled', 'hidden'))):
            _fail('GEOMETRY_PARAMETER_UNAVAILABLE', name)
        actual = fact.get('value')
        if kind == 'ordinal':
            tokens = fact.get('menu_tokens')
            if (not isinstance(tokens, (list, tuple))
                    or tuple(tokens) != ('detail', 'primitive', 'point', 'vertex', 'number')
                    or type(fact.get('menu_uses_token_value')) is not bool):
                _fail('GEOMETRY_NATIVE_MENU_CHANGED', name)
            valid = ((type(actual) is str and actual == 'point')
                     or (fact['menu_uses_token_value'] is False
                         and type(actual) is int and actual == tokens.index('point')))
        elif kind in ('toggle', 'multiparm'):
            valid = type(actual) is int and actual == GATES[name][1]
        else:
            valid = type(actual) is str and (name == 'snippet' or actual == GATES[name][1])
        if not valid:
            _fail('GEOMETRY_SCOPE_CHANGED', name)
        result[name] = copy.deepcopy(dict(fact))
    return result


def control_readback(version, context, parameters):
    basis = validate_context(version, context)
    _registered_context(context, basis)
    actual = _parameters(parameters)['snippet']['value']
    prefix = 'float deform_amplitude = '
    first_line = actual.splitlines()[0] if actual else ''
    if not first_line.startswith(prefix) or not first_line.endswith(';'):
        _fail('GEOMETRY_PROGRAM_READBACK_MISMATCH', 'actual owned snippet required')
    try:
        value = float(first_line[len(prefix):-1])
    except ValueError as error:
        raise GeometryControlsError('GEOMETRY_PROGRAM_READBACK_MISMATCH', 'invalid amplitude literal') from error
    registration = source_program(version, value, context)
    if actual != registration['program']:
        _fail('GEOMETRY_PROGRAM_READBACK_MISMATCH', 'actual program differs from fixed generator')
    return dict(value=value, basis_sha256=basis['content_sha256'], program_sha256=registration['sha256'],
                status='BLOCKED', evidence_scope='parameters_only', missing_evidence=list(MISSING_EVIDENCE))


@dataclass(frozen=True)
class GeometryDeformPlan:
    version: str
    value: float
    frozen_context_json: str
    frozen_parameters_json: str
    writes_json: str
    seal: str


def _seal(version, value, context_json, parameters_json, writes_json):
    return hmac.new(_SEAL_KEY, _json([version, value, context_json, parameters_json, writes_json]).encode(),
                    hashlib.sha256).hexdigest()


def _writes(version, value, context):
    registration = source_program(version, value, context)
    return [dict(role=ROLE, parm='snippet', value=registration['program'], native_type='string',
                 phase='deform_program', require_writable=True, require_readback=True,
                 required_gates=[(ROLE, name, target) for name, (_, target) in GATES.items()],
                 trusted_program=registration, invalidates_from='shaping_meshing')]


def plan_control(version, value, context, parameters):
    """Produce one guarded snippet write; never register a producer result."""
    basis = validate_context(version, context)
    _registered_context(context, basis)
    writes = _writes(version, value, context)
    observed = _parameters(parameters)
    control_readback(version, context, parameters)
    context_json, parameters_json, writes_json = _json(context), _json(observed), _json(writes)
    value = _number(value, 'deformation', 0, 100)
    return GeometryDeformPlan(version, value, context_json, parameters_json, writes_json,
        _seal(version, value, context_json, parameters_json, writes_json))


def validate_plan(plan, context, parameters, *, after_mutation=False):
    if not isinstance(plan, GeometryDeformPlan) or type(after_mutation) is not bool:
        _fail('GEOMETRY_PLAN_CHANGED', 'process-local plan and boolean phase required')
    expected_seal = _seal(plan.version, plan.value, plan.frozen_context_json,
                          plan.frozen_parameters_json, plan.writes_json)
    if not isinstance(plan.seal, str) or not hmac.compare_digest(plan.seal, expected_seal):
        _fail('GEOMETRY_PLAN_CHANGED', 'plan seal differs')
    basis = validate_context(plan.version, context)
    _registered_context(context, basis)
    if _json(context) != plan.frozen_context_json:
        _fail('GEOMETRY_CONTEXT_CHANGED', 'frozen owned graph/source/basis differs')
    writes = _writes(plan.version, plan.value, context)
    if _json(writes) != plan.writes_json:
        _fail('GEOMETRY_PLAN_CHANGED', 'fixed generator differs')
    expected = json.loads(plan.frozen_parameters_json)
    if after_mutation:
        expected['snippet']['value'] = writes[0]['value']
    if _json(_parameters(parameters)) != _json(expected):
        _fail('GEOMETRY_PARAMETER_READBACK_MISMATCH', 'actual channel or template snapshot differs')
    return writes


def rollback_plan(plan, context, parameters):
    validate_plan(plan, context, parameters, after_mutation=True)
    original = json.loads(plan.frozen_parameters_json)['snippet']['value']
    return [dict(role=ROLE, parm='snippet', value=original, native_type='string',
                 phase='rollback', require_readback=True)]
