"""A01 plans and parameter collectors for the host's owned Pyro transaction.

The host supplies independently collected source geometry, node ownership and
input/output connections. This module never cooks a solver or claims field,
simulation, persistence or render success. The seal is local to this process.
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

from .native_pyro_domains import NativePyroDomainError, SUPPORTED_VERSIONS

ROLE = 'flame_height'
SCHEMA = 'bridge.trusted-pyro-height-program/1'
BASIS_SCHEMA = 'bridge.pyro-height-basis/1'
GENERATOR = 'houdini_bridge.native_pyro_height_program.source_program/1'
GATES = {
    'group': ('string', '@name=flame'), 'bindeach': ('toggle', 0),
    'exportlist': ('string', 'flame'), 'autobind': ('toggle', 1),
    'vex_outputmask': ('string', 'flame'),
    'vex_geometrygenerator': ('toggle', 0), 'vex_precision': ('string', '64'),
}
_SEAL_KEY = secrets.token_bytes(32)


def _fail(code, detail):
    raise NativePyroDomainError(code, detail)


def _hash(value):
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, OverflowError) as error:
        raise NativePyroDomainError('PYRO_HEIGHT_INVALID_CONTEXT', str(error)) from error


def _number(value, label, lo=-1e12, hi=1e12):
    if (type(value) not in (int, float) or not lo <= value <= hi
            or not math.isfinite(value)):
        _fail('PYRO_HEIGHT_INVALID_CONTEXT', label)
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail('PYRO_HEIGHT_INVALID_CONTEXT', label)
    return [_number(component, label) for component in value]


def _path(value):
    return (isinstance(value, str) and value.startswith('/') and value != '/'
            and str(PurePosixPath(value)) == value
            and all(part not in ('.', '..') for part in value.split('/')))


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def source_geometry_sha256(source):
    if not isinstance(source, Mapping):
        _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'actual source vertices required')
    if (source.get('origin') != 'runtime_hom' or source.get('space') != 'sop_local'
            or not _path(source.get('node_path')) or type(source.get('output')) is not int
            or source['output'] != 0 or not isinstance(source.get('point_positions'), (list, tuple))
            or not 1 <= len(source['point_positions']) <= 100000):
        _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'bounded actual SOP output 0 source positions required')
    _number(source.get('frame'), 'source frame')
    for position in source['point_positions']:
        _vector(position, 'source vertex')
    return _hash(dict(source))


def basis_content_sha256(basis):
    return _hash({key: value for key, value in basis.items() if key != 'content_sha256'})


def freeze_basis(version, h_base, axis, source, *, task_id, task_root, input_version,
                 basis_input_sha256, source_program_sha256):
    """Freeze explicit positive H_base and the authenticated source up axis.

    The host authenticates the two input hashes and task/version binding before
    calling. A digest is content identity, not authentication or a receipt.
    """
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        _fail('UNSUPPORTED_NATIVE_VERSION', str(version))
    h_base = _number(h_base, 'positive H_base', 0)
    if h_base <= 0 or not _path(task_root) or not isinstance(task_id, str) or not task_id:
        _fail('PYRO_HEIGHT_BASIS_REQUIRED', 'explicit positive owned height basis required')
    if (not isinstance(input_version, str) or not input_version
            or not _digest(basis_input_sha256) or not _digest(source_program_sha256)):
        _fail('PYRO_HEIGHT_BASIS_REQUIRED', 'authenticated input/version and source program hashes required')
    source_hash = source_geometry_sha256(source)
    if not source['node_path'].startswith(task_root + '/'):
        _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'source is outside owned root')
    axis = _vector(axis, 'trusted up axis')
    if not math.isclose(math.fsum(component * component for component in axis), 1., rel_tol=0, abs_tol=1e-12):
        _fail('PYRO_HEIGHT_BASIS_REQUIRED', 'up axis must match normalized trusted source program')
    top = max(math.fsum(component * direction for component, direction in zip(position, axis))
              for position in source['point_positions'])
    basis = {'schema': BASIS_SCHEMA, 'native_version': version, 'task_id': task_id,
             'task_root': task_root, 'input_version': input_version, 'h_base': h_base,
             'axis': axis, 'source_top': top, 'space': 'sop_local',
             'source_node_path': source['node_path'], 'source_geometry_sha256': source_hash,
             'basis_input_sha256': basis_input_sha256, 'source_program_sha256': source_program_sha256}
    basis['content_sha256'] = basis_content_sha256(basis)
    return basis


def _basis(version, context):
    if not isinstance(context, Mapping) or not isinstance(context.get('basis'), Mapping):
        _fail('PYRO_HEIGHT_BASIS_REQUIRED', 'frozen basis and independent runtime source required')
    basis = context['basis']
    rebuilt = freeze_basis(version, basis.get('h_base'), basis.get('axis'), context.get('source'),
                           task_id=basis.get('task_id'), task_root=basis.get('task_root'),
                           input_version=basis.get('input_version'), basis_input_sha256=basis.get('basis_input_sha256'),
                           source_program_sha256=basis.get('source_program_sha256'))
    if dict(basis) != rebuilt:
        _fail('PYRO_HEIGHT_BASIS_CHANGED', 'source, version, coordinate or frozen basis differs')
    return rebuilt


def _node(context, role, basis, types):
    fact = context.get('nodes', {}).get(role, {})
    if (not isinstance(fact, Mapping) or fact.get('origin') != 'runtime_hom'
            or fact.get('task_owned') is not True or fact.get('task_id') != basis['task_id']
            or fact.get('input_version') != basis['input_version']
            or fact.get('native_version') != basis['native_version']
            or fact.get('task_root') != basis['task_root'] or not _path(fact.get('path'))
            or not fact['path'].startswith(basis['task_root'] + '/')
            or fact.get('category') != 'sop' or fact.get('type') not in types
            or fact.get('editable') is not True or fact.get('bypassed') is not False
            or fact.get('space') != 'sop_local'):
        _fail('PYRO_HEIGHT_OWNED_GRAPH_REQUIRED', role)
    return fact


def validate_context(version, context):
    basis = _basis(version, context)
    source = _node(context, 'source', basis, ('sphere',))
    solver = _node(context, 'solver', basis, ('pyrosolver',))
    mask = _node(context, ROLE, basis, ('volumewrangle',))
    output = _node(context, 'output', basis, ('null',))
    if source['path'] != basis['source_node_path']:
        _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'source identity differs')
    if len({str(PurePosixPath(fact['path']).parent) for fact in (source, solver, mask, output)}) != 1:
        _fail('PYRO_HEIGHT_SPACE_MISMATCH', 'all four nodes must share one SOP coordinate space')
    for downstream, upstream in ((mask, solver), (output, mask)):
        wires = downstream.get('inputs')
        if (not isinstance(wires, list) or len(wires) != 1
                or type(wires[0].get('input_index')) is not int or type(wires[0].get('output_index')) is not int):
            _fail('PYRO_HEIGHT_CONNECTION_REQUIRED', downstream['path'])
        if downstream.get('inputs') != [{'input_index': 0, 'output_index': 0, 'node_path': upstream['path']}]:
            _fail('PYRO_HEIGHT_CONNECTION_REQUIRED', downstream['path'])
    production = context.get('production', {})
    if (not isinstance(production, Mapping) or production.get('origin') != 'runtime_hom'
            or production.get('node_path') != solver['path']):
        _fail('PYRO_HEIGHT_PRODUCTION_REQUIRED', 'actual same-solver field exports required')
    for name, expected in (('addflamefield', 1), ('conv_vdb', 0)):
        actual = production.get(name, {})
        if (actual.get('origin') != 'runtime_hom' or actual.get('type') != 'toggle'
                or type(actual.get('size')) is not int or actual['size'] != 1
                or type(actual.get('value')) is not int or actual['value'] != expected
                or actual.get('driven') is not False):
            _fail('PYRO_HEIGHT_PRODUCTION_REQUIRED', name)
    exported = production.get('exports')
    if not isinstance(exported, list) or not 1 <= len(exported) <= 64:
        _fail('PYRO_HEIGHT_PRODUCTION_REQUIRED', 'bounded actual exported fields required')
    enabled = []
    for row in exported:
        enable, name = row.get('enable', {}), row.get('name', {})
        if (enable.get('origin') != 'runtime_hom' or enable.get('type') != 'toggle'
                or type(enable.get('value')) is not int or enable['value'] not in (0, 1)
                or enable.get('driven') is not False or name.get('origin') != 'runtime_hom'
                or name.get('type') != 'string' or not isinstance(name.get('value'), str)
                or name.get('driven') is not False):
            _fail('PYRO_HEIGHT_PRODUCTION_REQUIRED', 'actual export row interface differs')
        if enable['value']:
            enabled.append(name['value'])
    if len(enabled) != len(set(enabled)) or not {'density', 'temperature', 'vel', 'flame'}.issubset(enabled):
        _fail('PYRO_HEIGHT_PRODUCTION_REQUIRED', 'required unique Pyro field exports missing')
    actual_source_program = context.get('source_program', {})
    if (not isinstance(actual_source_program, Mapping)
            or actual_source_program.get('generator') != 'houdini_bridge.native_pyro_domains.source_program/1'
            or actual_source_program.get('native_version') != version
            or actual_source_program.get('domain_pack') != 'pyro_fire_v1'
            or actual_source_program.get('source', {}).get('direction') != basis['axis']
            or not isinstance(actual_source_program.get('program'), str)
            or hashlib.sha256(actual_source_program['program'].encode()).hexdigest() != basis['source_program_sha256']
            or actual_source_program.get('sha256') != basis['source_program_sha256']):
        _fail('PYRO_HEIGHT_SOURCE_PROGRAM_REQUIRED', 'actual registered source program and trusted axis required')
    from .native_pyro_domains import source_program
    regenerated = source_program('pyro_fire_v1', version, context.get('source_input'))
    if _hash(regenerated) != _hash(actual_source_program):
        _fail('PYRO_HEIGHT_SOURCE_PROGRAM_REQUIRED', 'source registration differs from fixed generator')
    actual_snippet = context.get('source_program_observation', {})
    if (not isinstance(actual_snippet, Mapping) or actual_snippet.get('origin') != 'runtime_hom'
            or actual_snippet.get('type') != 'string' or type(actual_snippet.get('size')) is not int
            or actual_snippet['size'] != 1 or actual_snippet.get('value') != regenerated['program']
            or actual_snippet.get('driven') is not False):
        _fail('PYRO_HEIGHT_SOURCE_PROGRAM_REQUIRED', 'source_control snippet must be independently read back')
    return basis


def source_program(version, value, context):
    basis = validate_context(version, context)
    value = _number(value, 'flame_height', -100, 1000)
    upper = basis['h_base'] + value
    if not math.isfinite(upper) or (value != 0 and upper == basis['h_base']):
        _fail('PYRO_HEIGHT_NOT_REPRESENTABLE', 'signed offset collapsed or overflowed')
    number = lambda scalar: format(scalar, '.17g')
    program = ('vector height_axis = set(' + ', '.join(number(component) for component in basis['axis']) + ');\n'
               + 'float height_upper = ' + number(basis['h_base']) + ' + (' + number(value) + ');\n'
               + 'float height_from_source = dot(@P, height_axis) - (' + number(basis['source_top']) + ');\n'
               + 'if (height_upper <= 0 || height_from_source > height_upper) f@flame = 0;\n')
    return {'schema': SCHEMA, 'generator': GENERATOR, 'domain_pack': 'pyro_fire_v1',
            'native_version': version, 'role': ROLE, 'parm': 'snippet',
            'control': 'flame_height', 'value': value, 'basis': basis,
            'program': program, 'sha256': hashlib.sha256(program.encode()).hexdigest(),
            'evidence_scope': 'parameters_only',
            'missing_evidence': ['actual_flame_voxels', 'preserved_density_temperature_velocity',
                                 'downstream_volume_consumption', 'save_reopen', 'dynamic_simulation_effects']}


def initialization_plan():
    return [{'role': ROLE, 'parm': name, 'value': value, 'native_type': kind,
             'phase': 'height_scope', 'require_writable': True, 'require_readback': True}
            for name, (kind, value) in GATES.items()]


def control_write_plan(version, value, context):
    registration = source_program(version, value, context)
    return [{'role': ROLE, 'parm': 'snippet', 'value': registration['program'], 'native_type': 'string',
             'phase': 'height_program', 'require_writable': True, 'require_readback': True,
             'required_gates': [(ROLE, name, value) for name, (_, value) in GATES.items()],
             'trusted_program': registration, 'invalidates_from': 'generation_simulation'}]


def collect_parameters(node, observe_parameter):
    """Use the existing host's HOM parameter collector without reading geometry.

    No request values are inputs. The callback must collect native template,
    current eval, expressions/keys, editability and menu representation facts.
    """
    return {(ROLE, name): observe_parameter(node, name) for name in (*GATES, 'snippet')}


def collect_source_geometry(geometry, *, node_path, frame):
    """Collect an already obtained source surface; never request a solver cook."""
    if geometry is None:
        _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'actual source geometry required')
    positions = []
    for primitive in geometry.prims():
        if primitive.type().name() != 'Polygon':
            _fail('PYRO_HEIGHT_SOURCE_REQUIRED', 'explicit polygon source vertices required')
        for vertex in primitive.vertices():
            if len(positions) >= 100000:
                _fail('PYRO_HEIGHT_SOURCE_BUDGET_EXCEEDED', 'source vertices exceed 100000')
            positions.append(list(vertex.point().position()))
    fact = {'origin': 'runtime_hom', 'node_path': node_path, 'output': 0,
            'space': 'sop_local', 'frame': frame, 'point_positions': positions}
    source_geometry_sha256(fact)
    return fact


def collect_volume_fields(geometry, *, node_path, frame, max_voxels=131072):
    """Collect bounded dense-volume voxels only from an already obtained geometry.

    The host alone decides whether native cooking is authorized. Missing,
    VDB, SDF and unsupported carriers remain explicit refusals.
    """
    if (geometry is None or not _path(node_path) or type(max_voxels) is not int
            or not 1 <= max_voxels <= 131072):
        _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'actual bounded dense-volume geometry required')
    _number(frame, 'volume frame')
    fields = {}
    total = 0
    for primitive in geometry.prims():
        channels, sdf = primitive.channelCount(), primitive.isSDF()
        if primitive.type().name() != 'Volume' or type(channels) is not int or channels != 1 or sdf is not False:
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'only scalar dense nonsigned-distance fields supported')
        name = primitive.attribValue('name')
        if not isinstance(name, str) or not name or name in fields:
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'actual unique volume names required')
        resolution = list(primitive.resolution())
        if len(resolution) != 3 or any(type(size) is not int or size <= 0 for size in resolution):
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'actual positive native resolution required')
        count = math.prod(resolution)
        total += count
        if total > max_voxels:
            _fail('PYRO_HEIGHT_VOLUME_BUDGET_EXCEEDED', 'refuse before reading voxel arrays')
        voxels = []
        positions = []
        for depth in range(resolution[2]):
            for row in range(resolution[1]):
                for column in range(resolution[0]):
                    index = (column, row, depth)
                    voxels.append(_number(primitive.voxel(index), name))
                    positions.append(_vector(list(primitive.indexToPos(index)), 'voxel center'))
        fields[name] = {'resolution': resolution, 'positions': positions, 'values': voxels}
    if not {'flame', 'density', 'temperature', 'vel.x', 'vel.y', 'vel.z'}.issubset(fields):
        _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'flame/density/temperature/vel scalar components required')
    return {'origin': 'runtime_hom', 'node_path': node_path, 'output': 0,
            'space': 'sop_local', 'frame': frame, 'fields': fields}


def validate_volume_readback(version, context, parameters, before, after):
    """Compare independent native observations; CPU expectation is not a cook."""
    observed = control_readback(version, context, parameters)
    basis = validate_context(version, context)
    expected_paths = (context['nodes']['solver']['path'], context['nodes'][ROLE]['path'])
    for snapshot, expected_path in zip((before, after), expected_paths):
        if (not isinstance(snapshot, Mapping) or snapshot.get('origin') != 'runtime_hom'
                or snapshot.get('node_path') != expected_path or snapshot.get('space') != 'sop_local'
                or type(snapshot.get('output')) is not int or snapshot['output'] != 0
                or not isinstance(snapshot.get('fields'), Mapping)):
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'independent same-space producer/mask output observations required')
        _number(snapshot.get('frame'), 'volume frame')
    if before['frame'] != after['frame'] or before['fields'].keys() != after['fields'].keys():
        _fail('PYRO_HEIGHT_VOLUME_READBACK_MISMATCH', 'frame or field set differs')
    required = {'flame', 'density', 'temperature', 'vel.x', 'vel.y', 'vel.z'}
    if not required.issubset(before['fields']):
        _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'required production fields missing')
    total = 0
    for name, field in before['fields'].items():
        target = after['fields'][name]
        if (not isinstance(field, Mapping) or not isinstance(target, Mapping)
                or set(field) != {'resolution', 'positions', 'values'} or set(target) != set(field)):
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', name)
        resolution = field['resolution']
        if (not isinstance(resolution, (list, tuple)) or len(resolution) != 3
                or any(type(size) is not int or size <= 0 for size in resolution)):
            _fail('PYRO_HEIGHT_VOLUME_REQUIRED', 'native resolution required')
        total += math.prod(resolution)
        if total > 131072:
            _fail('PYRO_HEIGHT_VOLUME_BUDGET_EXCEEDED', 'bounded readback required')
        if (target['resolution'] != resolution or target['positions'] != field['positions']
                or not isinstance(field['positions'], (list, tuple))
                or not isinstance(field['values'], (list, tuple))
                or not isinstance(target['values'], (list, tuple))
                or len(field['positions']) != math.prod(resolution)
                or len(field['values']) != len(field['positions'])
                or len(target['values']) != len(field['values'])):
            _fail('PYRO_HEIGHT_VOLUME_READBACK_MISMATCH', name + '/topology')
        upper = basis['h_base'] + observed['value']
        for position, original, actual in zip(field['positions'], field['values'], target['values']):
            position = _vector(position, 'voxel center')
            original = _number(original, name)
            actual = _number(actual, name)
            height = math.fsum(component * axis for component, axis in zip(position, basis['axis'])) - basis['source_top']
            expected = 0. if name == 'flame' and (upper <= 0 or height > upper) else original
            if actual != expected:
                _fail('PYRO_HEIGHT_VOLUME_READBACK_MISMATCH', name + '/actual voxel differs')
    return {**observed, 'evidence_scope': 'observed_dense_volume_comparison',
            'missing_evidence': ['downstream_volume_consumption', 'save_reopen', 'dynamic_simulation_effects']}


@dataclass(frozen=True)
class HeightPlan:
    version: str
    value: float
    frozen_context_json: str
    frozen_parameters_json: str
    writes_json: str
    seal: str


def _seal(version, value, context_json, parameters_json, writes_json):
    body = json.dumps([version, value, context_json, parameters_json, writes_json], allow_nan=False)
    return hmac.new(_SEAL_KEY, body.encode(), hashlib.sha256).hexdigest()


def _parameters(parameters):
    if not isinstance(parameters, Mapping):
        _fail('PYRO_HEIGHT_RUNTIME_REQUIRED', 'actual HOM parameter observations required')
    result = {}
    for name in (*GATES, 'snippet'):
        fact = parameters.get((ROLE, name), {})
        kind = GATES[name][0] if name in GATES else 'string'
        if (not isinstance(fact, Mapping) or fact.get('origin') != 'runtime_hom'
                or fact.get('type') != kind or type(fact.get('size')) is not int or fact['size'] != 1
                or any(fact.get(flag) is not False for flag in ('locked', 'disabled', 'hidden', 'driven'))
                or (kind == 'string' and not isinstance(fact.get('value'), str))
                or (kind == 'toggle' and (type(fact.get('value')) is not int or fact['value'] not in (0, 1)))):
            _fail('PYRO_HEIGHT_RUNTIME_REQUIRED', name)
        if name in GATES and fact['value'] != GATES[name][1]:
            _fail('PYRO_HEIGHT_SCOPE_CHANGED', name)
        result[name] = copy.deepcopy(dict(fact))
    return result


def plan_control(version, value, context, parameters):
    writes = control_write_plan(version, value, context)
    observed = _parameters(parameters)
    context_json = json.dumps(context, sort_keys=True, allow_nan=False)
    parameters_json = json.dumps(observed, sort_keys=True, allow_nan=False)
    writes_json = json.dumps(writes, sort_keys=True, allow_nan=False)
    value = writes[0]['trusted_program']['value']
    return HeightPlan(version, value, context_json, parameters_json, writes_json,
                      _seal(version, value, context_json, parameters_json, writes_json))


def validate_plan(plan, context, parameters, *, after_mutation=False):
    if not isinstance(plan, HeightPlan) or type(after_mutation) is not bool:
        _fail('PYRO_HEIGHT_INVALID_PLAN', 'local typed plan and boolean phase required')
    expected_seal = _seal(plan.version, plan.value, plan.frozen_context_json,
                          plan.frozen_parameters_json, plan.writes_json)
    if not isinstance(plan.seal, str) or not hmac.compare_digest(plan.seal, expected_seal):
        _fail('PYRO_HEIGHT_INVALID_PLAN', 'local plan seal differs')
    validate_context(plan.version, context)
    if json.dumps(context, sort_keys=True, allow_nan=False) != plan.frozen_context_json:
        _fail('PYRO_HEIGHT_BASIS_CHANGED', 'independent runtime context drifted')
    observed = _parameters(parameters)
    frozen = json.loads(plan.frozen_parameters_json)
    writes = json.loads(plan.writes_json)
    expected = control_write_plan(plan.version, plan.value, json.loads(plan.frozen_context_json))
    if _hash(writes) != _hash(expected):
        _fail('PYRO_HEIGHT_INVALID_PLAN', 'writes differ from fixed generator')
    if after_mutation:
        frozen['snippet']['value'] = writes[0]['value']
    if _hash(observed) != _hash(frozen):
        _fail('PYRO_HEIGHT_READBACK_MISMATCH', 'actual parameter state differs')
    return copy.deepcopy(writes)


def control_readback(version, context, parameters):
    """Decode the independently observed program; never echo the requested value."""
    basis = validate_context(version, context)
    observed = _parameters(parameters)
    lines = observed['snippet']['value'].splitlines()
    if len(lines) != 4:
        _fail('PYRO_HEIGHT_READBACK_MISMATCH', 'actual program differs')
    prefix = 'float height_upper = ' + format(basis['h_base'], '.17g') + ' + ('
    if not lines[1].startswith(prefix) or not lines[1].endswith(');'):
        _fail('PYRO_HEIGHT_READBACK_MISMATCH', 'observed basis differs')
    try:
        value = float(lines[1][len(prefix):-2])
    except ValueError as error:
        raise NativePyroDomainError('PYRO_HEIGHT_READBACK_MISMATCH', 'invalid offset literal') from error
    registration = source_program(version, value, context)
    if observed['snippet']['value'] != registration['program']:
        _fail('PYRO_HEIGHT_READBACK_MISMATCH', 'observed program differs from fixed generator')
    return {'value': value, 'basis_sha256': basis['content_sha256'],
            'program_sha256': registration['sha256'], 'evidence_scope': 'parameters_only',
            'missing_evidence': registration['missing_evidence']}


def rollback_plan(plan, context, parameters):
    """Return original observed channel values only after a guarded final read.

    The host snapshots connections, registration and native channels and applies
    this restoration under its existing ownership/lease transaction fence.
    """
    validate_plan(plan, context, parameters, after_mutation=True)
    original = json.loads(plan.frozen_parameters_json)
    return [{'role': ROLE, 'parm': 'snippet', 'value': original['snippet']['value'],
             'native_type': 'string', 'phase': 'rollback', 'require_readback': True}]
