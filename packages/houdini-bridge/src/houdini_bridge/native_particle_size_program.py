"""Approved P02 parameter plans for an existing authenticated host transaction.

Observations must come from the host collector. This module never writes HOM,
samples native randomness, changes an operation state, or proves instancing.
Plans are sealed only for the issuing Python process, not for persistence.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import secrets
from typing import Mapping

from . import native_particle_ocean_geometry_domains as core


ROLE = 'particle_size'
BASIS_SCHEMA = 'bridge.particle-size-basis/1'
PLAN_SCHEMA = 'bridge.particle-size-plan/1'
_PLAN_SEAL_KEY = secrets.token_bytes(32)
COMMON_GATES = {
    'attrib': ('string', 'pscale'), 'class': ('ordinal', 'point'),
    'adjustvalue': ('toggle', 1), 'operation': ('ordinal', 'set'),
    'unitsettings': ('ordinal', 'none'), 'doblend': ('toggle', 0),
    'enable_postprocess': ('toggle', 0), 'group': ('string', ''),
}
BASIS_FIELDS = {
    'schema', 'origin', 'task_owned', 'task_id', 'task_root', 'node_path',
    'native_version', 'size', 'task_seed', 'id_attribute', 'content_sha256',
}


class ParticleSizeError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


@dataclass(frozen=True)
class ParticleSizePlan:
    schema: str
    native_version: str
    percentage: float
    basis_sha256: str
    native_seed: int
    writes: tuple[dict, ...]
    content_sha256: str
    frozen_readback_json: str
    host_seal: str = ''
    size_override: float | None = None
    staged: bool = False
    frozen_parameter_states_json: str = ''


@dataclass(frozen=True)
class ParticleSizeParameterReadback:
    native_version: str
    observed_percentage: float
    basis_sha256: str
    parameters: dict
    evidence_scope: str = 'parameters_only'
    missing_evidence: tuple[str, ...] = (
        'actual_random_pscale_by_stable_id', 'copytopoints_pscale_consumption',
        'cross_frame_and_reopen_stability',
    )


@dataclass(frozen=True)
class ParticleSizeGeometryReadback:
    native_version: str
    observed_percentage: float
    basis_sha256: str
    pscale_by_id: dict
    copied_ids: tuple[int, ...]
    evidence_scope: str = 'actual_pscale_and_unpacked_copy_geometry'
    missing_evidence: tuple[str, ...] = (
        'cross_frame_and_reopen_stability', 'native_random_distribution_verification',
        'full_copy_transform_and_connectivity',
    )


def _fail(code, detail):
    raise ParticleSizeError(code, detail)


def _digest(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise ParticleSizeError('PARTICLE_SIZE_INVALID_BINDING', str(error)) from error
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _plan_seal(content_sha256):
    return hmac.new(_PLAN_SEAL_KEY, content_sha256.encode('ascii'), hashlib.sha256).hexdigest()


def basis_content_sha256(basis: Mapping) -> str:
    return _digest({key: value for key, value in basis.items() if key != 'content_sha256'})


def _parameter(observations, name, kind, *, staged=False):
    fact = core._runtime(observations, ROLE, name, kind)
    if (fact.get('locked') is not False
            or any(type(fact.get(flag)) is not bool for flag in ('disabled', 'hidden'))
            or (not staged and any(fact[flag] for flag in ('disabled', 'hidden')))
            or (staged and name in set(COMMON_GATES) | {'valuetype'}
                and any(fact[flag] for flag in ('disabled', 'hidden')))):
        _fail('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name)
    if kind == 'ordinal' and (type(fact.get('menu_uses_token_value')) is not bool
            or not any(core._gate_matches(fact, token) for token in fact['menu_tokens'])):
        _fail('PARTICLE_SIZE_NATIVE_TOKEN_REQUIRED', name + '/current representation')
    return fact


def _context(version, observations):
    if type(version) is not str or version not in (*core.VERSIONS, *PREPARATION_VERSIONS):
        _fail('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', 'supported native version string required')
    if not isinstance(observations, Mapping):
        _fail('PARTICLE_SIZE_HOST_OBSERVATIONS_REQUIRED', 'mapping required')
    core.validate_geometry_readback(core.PARTICLES, version, observations)
    fact = observations.get((ROLE, '@size_basis'), {})
    node = observations[ROLE, '@node']
    if (not isinstance(fact, Mapping) or set(fact) != BASIS_FIELDS
            or fact.get('schema') != BASIS_SCHEMA or fact.get('origin') != 'runtime_hom'
            or fact.get('task_owned') is not True or fact.get('native_version') != version
            or node.get('native_version') != version
            or not isinstance(fact.get('task_id'), str) or not fact['task_id']
            or node.get('task_id') != fact['task_id']
            or fact.get('node_path') != node['path'] or fact.get('task_root') != node['task_root']
            or fact.get('id_attribute') != 'id'):
        _fail('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', 'owned same-build size and seed basis required')
    if basis_content_sha256(fact) != fact['content_sha256']:
        _fail('PARTICLE_SIZE_BASIS_CHANGED', 'frozen basis digest differs')
    for requirement in core.node_requirements(core.PARTICLES, version):
        observed_node = observations[requirement['role'], '@node']
        if (observed_node.get('task_id') != fact['task_id']
                or observed_node.get('native_version') != version):
            _fail('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', requirement['role'] + '/task or version differs')
    core._number(fact['size'], .0001, 100, 'size')
    core._number(fact['task_seed'], 0, 2147483647, 'task_seed', integer=True)
    geometry = observations['simulation', '@geometry/0']
    attribute = geometry.get('point_attributes', {}).get('id', {})
    identities = attribute.get('values')
    if (attribute.get('owner') != 'point' or attribute.get('type') != 'integer'
            or type(attribute.get('size')) is not int or attribute['size'] != 1
            or attribute.get('precision') != 'int32'
            or attribute.get('is_array') is not False or not isinstance(identities, list)
            or len(identities) != geometry['points']
            or any(not core._typed_value(identity, 'integer', 1) for identity in identities)
            or len(set(identities)) != len(identities)):
        _fail('PARTICLE_SIZE_STABLE_IDS_REQUIRED', 'actual unique point id integer/1 values required')
    for name, (kind, expected) in COMMON_GATES.items():
        observed = _parameter(observations, name, kind)
        if not core._gate_matches(observed, expected):
            _fail('PARTICLE_SIZE_SCOPE_CHANGED', name)
    mode = _parameter(observations, 'valuetype', 'ordinal')
    if not any(core._gate_matches(mode, token) for token in ('const', 'rand')):
        _fail('PARTICLE_SIZE_SCOPE_CHANGED', 'only owned constant/random size modes are supported')
    return fact


def _targets(percentage, basis, size_override=None):
    if size_override is not None:
        basis = dict(basis, size=core._number(size_override, .0001, 100, 'size'))
    percentage = core._number(percentage, 0, 100, 'size_variance')
    seed = int.from_bytes(hashlib.sha256(
        ('bridge.P02/1:' + str(basis['task_seed'])).encode('ascii')).digest()[:4], 'big') & 2147483647
    if percentage == 0:
        return percentage, seed, [('valuetype', 'ordinal', 'const', 'gates'),
                                  ('singlevalue', 'float', float(basis['size']), 'values')]
    factor = 1 + percentage / 100
    minimum = basis['size'] / factor
    extent = basis['size'] * (factor - 1 / factor)
    if factor <= 1 or extent <= 0 or minimum + extent <= minimum:
        _fail('PARTICLE_SIZE_RANGE_NOT_REPRESENTABLE', 'positive variation collapsed in numeric representation')
    targets = [
        ('valuetype', 'ordinal', 'rand', 'gates'),
        ('rangemethod', 'ordinal', 'minplusrange', 'gates'),
        ('distribinrange', 'ordinal', 'uniform', 'gates'),
        ('randmethod', 'ordinal', 'custom', 'gates'),
        ('randattrib', 'string', 'id', 'gates'),
        ('randomseed', 'integer', seed, 'values'),
        ('enablestepping', 'toggle', 0, 'gates'),
        ('minvalue', 'float', minimum, 'values'),
        ('rangevalue', 'float', extent, 'values'),
    ]
    if size_override is not None:
        targets.append(('singlevalue', 'float', basis['size'], 'values'))
    return percentage, seed, targets


def _plan_body(plan):
    return {key: copy.deepcopy(getattr(plan, key)) for key in (
        'schema', 'native_version', 'percentage', 'basis_sha256', 'native_seed', 'writes',
        'frozen_readback_json', 'size_override', 'staged', 'frozen_parameter_states_json')}


def _topology_keys(observations):
    result = set()
    for key in observations:
        if not isinstance(key, tuple) or len(key) != 2 or not all(isinstance(part, str) for part in key):
            _fail('PARTICLE_SIZE_HOST_OBSERVATIONS_REQUIRED', 'role/field tuple keys required')
        role, name = key
        if name == '@node' or name.startswith('@input/'):
            result.add((role, name))
    return result


def _native_write(name, kind, value, phase, version, guards):
    return core._write(
        ROLE, name, value, kind, phase=phase, domain_id=core.PARTICLES,
        native_version=version, public_control='size_variance',
        invalidates_from='shaping_meshing',
        required_gates=[(ROLE, gate, expected) for gate, (_, expected) in COMMON_GATES.items()],
        frozen_readback_guards=copy.deepcopy(guards),
    )


def plan_size_variance(percentage, version, *, observations, size_override=None, staged=False) -> ParticleSizePlan:
    basis = _context(version, observations)
    percentage, seed, targets = _targets(percentage, basis, size_override)
    guards = []
    for role, name in sorted(_topology_keys(observations)):
        guards.append(core._guard(role, name, observations[role, name]))
    guards += [core._guard(ROLE, '@size_basis', basis),
               core._guard('simulation', '@geometry/0', observations['simulation', '@geometry/0'])]
    if ('instance_source', '@geometry/0') in observations:
        guards.append(core._guard('instance_source', '@geometry/0', observations['instance_source', '@geometry/0']))
    for name, (kind, expected) in COMMON_GATES.items():
        guards.append(core._guard(ROLE, name, _parameter(observations, name, kind)))
    for name, kind, value, phase in targets:
        observed = _parameter(observations, name, kind, staged=staged)
        if kind == 'ordinal' and value not in observed['menu_tokens']:
            _fail('PARTICLE_SIZE_NATIVE_TOKEN_REQUIRED', name + '/' + value)
        guards.append(core._guard(ROLE, name, observed))
    writes = tuple(_native_write(name, kind, value, phase, version, guards)
                   for name, kind, value, phase in targets)
    frozen_readback_json = json.dumps(guards, sort_keys=True, separators=(',', ':'), allow_nan=False)
    states = {name: copy.deepcopy(observations[ROLE, name])
              for name in {name for name, _, _, _ in targets} | {'singlevalue', 'valuetype'}}
    plan = ParticleSizePlan(PLAN_SCHEMA, version, percentage, basis['content_sha256'], seed,
                            writes, '', frozen_readback_json, size_override=size_override,
                            staged=staged, frozen_parameter_states_json=json.dumps(
                                states, sort_keys=True, separators=(',', ':'), allow_nan=False))
    content_sha256 = _digest(_plan_body(plan))
    plan = ParticleSizePlan(**_plan_body(plan), content_sha256=content_sha256,
                            host_seal=_plan_seal(content_sha256))
    validate_control_write_plan(plan, observations)
    return plan


def validate_control_write_plan(plan: ParticleSizePlan, observations, *, after_mutation=False):
    if (not isinstance(plan, ParticleSizePlan) or plan.schema != PLAN_SCHEMA
            or type(after_mutation) is not bool
            or type(plan.native_version) is not str or plan.native_version not in (*core.VERSIONS, *PREPARATION_VERSIONS)
            or not core._typed_value(plan.native_seed, 'integer', 1)
            or type(plan.frozen_readback_json) is not str
            or type(plan.host_seal) is not str
            or type(plan.staged) is not bool or type(plan.frozen_parameter_states_json) is not str
            or not isinstance(plan.writes, tuple) or not all(isinstance(write, dict) for write in plan.writes)
            or _digest(_plan_body(plan)) != plan.content_sha256
            or not hmac.compare_digest(plan.host_seal.encode('utf-8'),
                                       _plan_seal(plan.content_sha256).encode('ascii'))):
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'plan type/schema/digest differs')
    basis = _context(plan.native_version, observations)
    if not after_mutation and plan.staged:
        states = json.loads(plan.frozen_parameter_states_json)
        if any(_digest(observations.get((ROLE, name))) != _digest(fact) for name, fact in states.items()):
            _fail('NATIVE_CONTROL_CONTEXT_CHANGED', 'staged parameter states changed before application')
    _, seed, targets = _targets(plan.percentage, basis, plan.size_override)
    if basis['content_sha256'] != plan.basis_sha256 or seed != plan.native_seed:
        _fail('PARTICLE_SIZE_BASIS_CHANGED', 'plan no longer binds the size/seed basis')
    if len(plan.writes) != len(targets):
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'native target set differs')
    guard_keys = _topology_keys(observations) | {
        (ROLE, '@size_basis'), ('simulation', '@geometry/0'),
    } | {(ROLE, name) for name in COMMON_GATES} | {(ROLE, name) for name, _, _, _ in targets}
    if ('instance_source', '@geometry/0') in observations:
        guard_keys.add(('instance_source', '@geometry/0'))
    guards = plan.writes[0].get('frozen_readback_guards')
    if (not isinstance(guards, list) or any(not isinstance(guard, dict) for guard in guards)
            or len(guards) != len(guard_keys)
            or {(guard.get('role'), guard.get('parm')) for guard in guards} != guard_keys):
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'mandatory identity/geometry/parameter guards differ')
    if json.dumps(guards, sort_keys=True, separators=(',', ':'), allow_nan=False) != plan.frozen_readback_json:
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'original frozen readback guards differ')
    for write, (name, kind, value, phase) in zip(plan.writes, targets):
        if (write != _native_write(name, kind, value, phase, plan.native_version, guards)
                or not core._typed_value(write.get('value'), kind, 1)):
            _fail('PARTICLE_SIZE_PLAN_CHANGED', name)
        observed = _parameter(observations, name, kind, staged=plan.staged)
        if kind == 'ordinal' and value not in observed['menu_tokens']:
            _fail('PARTICLE_SIZE_NATIVE_TOKEN_REQUIRED', name + '/' + value)
        if after_mutation and not core._gate_matches(observed, value):
            _fail('PARTICLE_SIZE_PARAMETER_READBACK_MISMATCH', name)
        if (after_mutation and plan.staged and not (name == 'singlevalue' and plan.percentage > 0)
                and any(observed[flag] for flag in ('disabled', 'hidden'))):
            _fail('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name + '/final active gate')
    parameter_kinds = {name: kind for name, (kind, _) in COMMON_GATES.items()}
    parameter_kinds.update({name: kind for name, kind, _, _ in targets})
    for guard in guards:
        if guard['parm'].startswith('@'):
            if set(guard) != {'role', 'parm', 'value'}:
                _fail('PARTICLE_SIZE_PLAN_CHANGED', 'identity/geometry guard structure differs')
            continue
        kind = parameter_kinds[guard['parm']]
        expected_keys = {'role', 'parm', 'value', 'native_type', 'size', 'require_undriven'}
        if kind == 'ordinal':
            expected_keys |= {'menu_tokens', 'menu_uses_token_value'}
        if (set(guard) != expected_keys or guard.get('native_type') != kind
                or type(guard.get('size')) is not int or guard['size'] != 1
                or not core._typed_value(guard.get('value'), kind, 1)
                or guard.get('require_undriven') is not True):
            _fail('PARTICLE_SIZE_PLAN_CHANGED', 'typed parameter guard differs')
        observed = _parameter(observations, guard['parm'], kind, staged=plan.staged)
        if kind == 'ordinal' and not core._menu_guard_matches(observed, guard):
            _fail('PARTICLE_SIZE_NATIVE_MENU_CHANGED', guard['parm'])
    core.validate_readback_guards(plan.writes, observations, after_mutation=after_mutation)


def validate_applied_readback(plan: ParticleSizePlan, observations) -> ParticleSizeParameterReadback:
    validate_control_write_plan(plan, observations, after_mutation=True)
    basis = observations[ROLE, '@size_basis']
    parameters = {write['parm']: copy.deepcopy(observations[ROLE, write['parm']]['value'])
                  for write in plan.writes}
    if core._gate_matches(observations[ROLE, 'valuetype'], 'const'):
        percentage = 0.
    else:
        size = basis['size'] if plan.size_override is None else plan.size_override
        percentage = ((parameters['minvalue'] + parameters['rangevalue']) / size - 1) * 100
    if not core._near(percentage, plan.percentage):
        _fail('PARTICLE_SIZE_PARAMETER_READBACK_MISMATCH', 'observed range does not recover percentage')
    return ParticleSizeParameterReadback(plan.native_version, percentage,
                                         plan.basis_sha256, parameters)


def routed_writes(plan):
    descriptor = _plan_body(plan)
    descriptor.update(content_sha256=plan.content_sha256, host_seal=plan.host_seal)
    guards = [guard for guard in json.loads(plan.frozen_readback_json)
              if guard['parm'].startswith('@')]
    return [core._write(ROLE, 'singlevalue', plan.percentage, 'float',
        value_kind='trusted_particle_size_program', particle_size_plan=descriptor,
        domain_id=core.PARTICLES, native_version=plan.native_version,
        public_control='size_variance', invalidates_from='shaping_meshing',
        frozen_readback_guards=guards)]


def plan_from_routed_writes(writes):
    if len(writes) != 1 or not isinstance(writes[0], dict):
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'complete routed native write set required')
    descriptor = writes[0].get('particle_size_plan')
    if not isinstance(descriptor, dict):
        _fail('PARTICLE_SIZE_PLAN_CHANGED', 'routed plan descriptor differs or is absent')
    try:
        fields = copy.deepcopy(descriptor)
        fields['writes'] = tuple(fields['writes'])
        plan = ParticleSizePlan(**fields)
        if writes != routed_writes(plan):
            _fail('PARTICLE_SIZE_PLAN_CHANGED', 'outer staged dispatch fields changed')
        return plan
    except TypeError as error:
        raise ParticleSizeError('PARTICLE_SIZE_PLAN_CHANGED', str(error)) from error


def _geometry(observations, role):
    fact = observations.get((role, '@geometry/0'))
    if (not isinstance(fact, Mapping) or fact.get('origin') != 'runtime_hom'
            or any(type(fact.get(name)) is not int or not 0 <= fact[name] <= 8192
                   for name in ('points', 'primitives'))):
        _fail('PARTICLE_SIZE_ACTUAL_GEOMETRY_REQUIRED', role)
    positions = fact.get('positions')
    if (not isinstance(positions, list) or len(positions) != fact['points']
            or any(not core._typed_value(position, 'float', 3) for position in positions)):
        _fail('PARTICLE_SIZE_ACTUAL_GEOMETRY_REQUIRED', role + '/positions')
    return fact


def _attribute(geometry, name, kind, size=1):
    attributes = geometry.get('point_attributes')
    attribute = attributes.get(name) if isinstance(attributes, Mapping) else None
    if (not isinstance(attribute, Mapping) or attribute.get('owner') != 'point'
            or attribute.get('type') != kind or type(attribute.get('size')) is not int
            or attribute['size'] != size or attribute.get('is_array') is not False
            or attribute.get('precision') not in (('int32',) if kind == 'integer'
                                                else ('float32', 'float64'))
            or not isinstance(attribute.get('values'), list)
            or len(attribute['values']) != geometry['points']
            or any(not core._typed_value(value, kind, size) for value in attribute['values'])):
        _fail('PARTICLE_SIZE_ATTRIBUTE_VALUES_REQUIRED', name)
    return attribute['values']


def _point_map(geometry):
    identities = _attribute(geometry, 'id', 'integer')
    if len(set(identities)) != len(identities):
        _fail('PARTICLE_SIZE_STABLE_IDS_REQUIRED', 'unique particle IDs required')
    return {identity: index for index, identity in enumerate(identities)}


def _primitive_signature(geometry, identities=None):
    records = geometry.get('primitive_records')
    if not isinstance(records, list) or len(records) != geometry['primitives']:
        _fail('PARTICLE_SIZE_COPY_CONSUMPTION_REQUIRED', 'actual primitive vertices required')
    result = {}
    for record in records:
        if (not isinstance(record, Mapping) or record.get('type') != 'Polygon'
                or type(record.get('closed')) is not bool
                or not isinstance(record.get('vertices'), list) or not record['vertices']
                or any(type(index) is not int or not 0 <= index < geometry['points']
                       for index in record['vertices'])):
            _fail('PARTICLE_SIZE_COPY_CONSUMPTION_REQUIRED', 'only observed unpacked polygon copies supported')
        identity = None if identities is None else identities[record['vertices'][0]]
        if identities is not None and any(identities[index] != identity for index in record['vertices']):
            _fail('PARTICLE_SIZE_COPY_CONSUMPTION_MISMATCH', 'primitive crosses target IDs')
        result.setdefault(identity, []).append((record['closed'], len(record['vertices'])))
    return {identity: sorted(signature) for identity, signature in result.items()}


def _distances(positions):
    result = sorted(math.dist(first, second) for index, first in enumerate(positions)
                    for second in positions[index + 1:])
    if not result or not all(math.isfinite(value) for value in result) or result[-1] <= 0:
        _fail('PARTICLE_SIZE_COPY_CONSUMPTION_REQUIRED', 'nondegenerate finite copy source required')
    return result


def _geometry_consumption(version, observations, percentage, size, basis_sha256):
    simulation = _geometry(observations, 'simulation')
    particles = _geometry(observations, ROLE)
    source = _geometry(observations, 'instance_source')
    copies = _geometry(observations, 'instances')
    output = _geometry(observations, 'output')
    original = _point_map(simulation)
    adjusted = _point_map(particles)
    if not original:
        _fail('PARTICLE_SIZE_NONEMPTY_CONSUMPTION_REQUIRED', 'empty geometry is not a copy-consumption proof')
    if set(original) != set(adjusted) or simulation['primitives'] != particles['primitives']:
        _fail('PARTICLE_SIZE_UNRELATED_GEOMETRY_CHANGED', 'particle identities/topology differ')
    attributes = simulation['point_attributes']
    if set(particles['point_attributes']) - {'pscale'} != set(attributes) - {'pscale'}:
        _fail('PARTICLE_SIZE_UNRELATED_GEOMETRY_CHANGED', 'non-pscale attribute set differs')
    for name, attribute in attributes.items():
        if name == 'pscale':
            continue
        actual = particles['point_attributes'].get(name)
        if name in ('id', 'v', 'age'):
            _attribute(simulation, name, 'integer' if name == 'id' else 'float', 3 if name == 'v' else 1)
            _attribute(particles, name, 'integer' if name == 'id' else 'float', 3 if name == 'v' else 1)
        if (not isinstance(actual, Mapping)
                or {key: value for key, value in attribute.items() if key != 'values'}
                != {key: value for key, value in actual.items() if key != 'values'}
                or not isinstance(attribute.get('values'), list)
                or len(attribute['values']) != simulation['points']
                or not isinstance(actual.get('values'), list)
                or len(actual['values']) != particles['points']
                or any(attribute['values'][original[identity]] != actual['values'][adjusted[identity]]
                       for identity in original)):
            _fail('PARTICLE_SIZE_UNRELATED_GEOMETRY_CHANGED', name)
    if any(simulation['positions'][original[identity]] != particles['positions'][adjusted[identity]]
           for identity in original):
        _fail('PARTICLE_SIZE_UNRELATED_GEOMETRY_CHANGED', 'particle positions differ')
    scales = _attribute(particles, 'pscale', 'float')
    factor = 1 + percentage / 100
    lower, upper = size / factor, size * factor
    pscale_by_id = {identity: scales[index] for identity, index in adjusted.items()}
    if any(value <= 0 or (value < lower and not math.isclose(value, lower, rel_tol=2e-6))
           or (value > upper and not math.isclose(value, upper, rel_tol=2e-6))
           for value in scales):
        _fail('PARTICLE_SIZE_PSCALE_READBACK_MISMATCH', 'actual pscale falls outside observed native range')
    if output != copies:
        _fail('PARTICLE_SIZE_COPY_CONSUMPTION_MISMATCH', 'null output differs from actual copy geometry')
    identities = _attribute(copies, 'id', 'integer')
    groups = {}
    for index, identity in enumerate(identities):
        groups.setdefault(identity, []).append(index)
    if set(groups) != set(adjusted):
        _fail('PARTICLE_SIZE_COPY_CONSUMPTION_MISMATCH', 'actual copied target IDs differ')
    if not 2 <= source['points'] <= 128 or source['primitives'] < 1:
        _fail('PARTICLE_SIZE_COPY_CONSUMPTION_REQUIRED', 'bounded nonempty polygon source required')
    if len(groups) * source['points'] * (source['points'] - 1) // 2 > 524288:
        _fail('PARTICLE_SIZE_COPY_OBSERVATION_BUDGET_EXCEEDED', 'pairwise copy geometry comparison budget')
    source_signature = _primitive_signature(source).get(None)
    copied_signatures = _primitive_signature(copies, identities)
    source_distances = _distances(source['positions'])
    for identity, indices in groups.items():
        if len(indices) != source['points'] or copied_signatures.get(identity) != source_signature:
            _fail('PARTICLE_SIZE_COPY_CONSUMPTION_MISMATCH', 'source point/primitive counts differ per ID')
        distances = _distances([copies['positions'][index] for index in indices])
        if any(not math.isclose(actual, expected * pscale_by_id[identity], rel_tol=2e-5, abs_tol=1e-7)
               for actual, expected in zip(distances, source_distances)):
            _fail('PARTICLE_SIZE_COPY_CONSUMPTION_MISMATCH', 'actual copied geometry scale differs from pscale')
    return ParticleSizeGeometryReadback(version, percentage, basis_sha256,
                                       pscale_by_id, tuple(sorted(groups)))


def validate_geometry_consumption(plan, observations):
    parameters = validate_applied_readback(plan, observations)
    basis = observations[ROLE, '@size_basis']
    size = basis['size'] if plan.size_override is None else plan.size_override
    return _geometry_consumption(plan.native_version, observations, parameters.observed_percentage,
                                 size, plan.basis_sha256)


def observed_percentage(version, observations):
    basis = _context(version, observations)
    size = core._runtime(observations, ROLE, 'singlevalue', 'float')['value']
    core._number(size, .0001, 100, 'size')
    mode = _parameter(observations, 'valuetype', 'ordinal')
    if core._gate_matches(mode, 'const'):
        percentage = 0.
    else:
        minimum = _parameter(observations, 'minvalue', 'float', staged=True)['value']
        extent = _parameter(observations, 'rangevalue', 'float', staged=True)['value']
        percentage = core._number(((minimum + extent) / size - 1) * 100,
                                  0, 100, 'size_variance')
    return percentage, size, basis


def collect_control_readback(version, observations):
    percentage, size, basis = observed_percentage(version, observations)
    plan = plan_size_variance(percentage, version, observations=observations, staged=True,
                             size_override=size if not core._near(size, basis['size']) else None)
    return validate_geometry_consumption(plan, observations)
