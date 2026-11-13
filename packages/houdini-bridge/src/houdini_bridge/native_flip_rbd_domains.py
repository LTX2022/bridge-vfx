"""Pure FLIP/RBD contracts for the host's existing atomic transaction path.

No native calls, scene writes or operation state are performed here. Runtime
observations are required for compiled parameter state and multiparm bindings.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Mapping

from .product_control_definitions import annotate_control_contract

SCHEMA = 'bridge.native-flip-rbd-domains/1'
FLIP = 'water_flip_v1'
RBD = 'rbd_destruction_v1'
UNIT_GLUE_SNIPPET = 'if (s@constraint_name == "Glue") f@strength = 1.0;'
DOMAIN_IDS = (FLIP, RBD)
VERSIONS = ('21.0.631', '22.0.429')
RBD_VELOCITY_ROUTE = 'bridge.rbd-velocity-program/1'


class NativeFlipRbdDomainError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _domain(pack, version):
    if version not in (*VERSIONS, *PREPARATION_VERSIONS):
        raise NativeFlipRbdDomainError('UNSUPPORTED_NATIVE_VERSION', str(version))
    if pack not in DOMAIN_IDS:
        raise NativeFlipRbdDomainError('UNKNOWN_NATIVE_DOMAIN', str(pack))


def _number(value, lo, hi, name, integer=False):
    if type(value) not in (float, int) or not lo <= value <= hi or not math.isfinite(value) or (integer and type(value) is not int):
        raise NativeFlipRbdDomainError('INVALID_NATIVE_CONTROL_VALUE', name)
    return int(value) if integer else float(value)


def _control(role, parm, lo, hi, *, kind='float', gates=(), phase='generation_simulation', unit='native scalar', **extra):
    return dict(role=role, aliases=[parm] if parm else [], minimum=lo, maximum=hi,
                value_type='int' if kind == 'integer' else 'float', native_type=kind, size=1,
                application='houdini', required_gates=list(gates), invalidates_from=phase,
                unit=unit, native_status='mapped', **extra)


def _blocked(role, lo, hi, blocker, *, kind='float', phase='generation_simulation'):
    c = _control(role, None, lo, hi, kind=kind, phase=phase, unit='NOT_CAPTURED')
    c.update(native_status='blocked', blocker=blocker)
    return c


@versioned_controls
def control_contract(pack, version):
    _domain(pack, version)
    if pack == FLIP:
        voxel = _control('surface', 'voxelsize', .1, 10, phase='shaping_meshing',
                         unit='dimensionless voxel scale times particle separation')
        detail = copy.deepcopy(voxel); detail.update(minimum=.01, maximum=100)
        return annotate_control_contract(pack, {
            'particle_separation': _control('container', 'particlesep', .001, 10,
                gates=[('fluid_source', 'createparticles', 1), ('solver', 'overrideres', 0)],
                unit='scene units; container vendor unit m1',
                targets=[('fluid_source', 'particlesep'), ('container', 'particlesep'), ('surface', 'particlesep')]),
            'substeps': _control('solver', 'minimumsubsteps', 1, 20, kind='integer', unit='minimum substeps per frame',
                maximum_substeps_parm='substeps', context_parms=[('solver', 'substeps')],
                maximum_policy='preserve actual maximum or raise it to the requested minimum'),
            'viscosity': _control('container', 'default_viscosity', 0, 100000,
                gates=[('container', 'viscosity', 1), ('container', 'dovaryingviscosity', 0)],
                unit='native viscosity; vendor token kg1m-1, physical conversion NOT_CAPTURED'),
            'surface_tension': _control('container', 'surfacetension', 0, 10000,
                gates=[('container', 'dosurfacetension', 1)], unit='native surface tension; vendor token kg1m-3s-2'),
            'surface_resolution': voxel, 'meshing_detail': detail,
            'droplet_scale': _control('surface', 'surfacedistance', 0, 100,
                gates=[('surface', 'surfmethod', 'particlefluid')], phase='shaping_meshing',
                unit='native dimensionless droplet scale'),
            'collision_separation': _blocked('collisions', 0, 100, 'FLIP_SIMULATION_COLLISION_SEPARATION_CONTRACT_NOT_CAPTURED'),
            'collision_passes': _blocked('solver', 1, 1000, 'FLIP_COLLISION_PASSES_NATIVE_FIELD_NOT_CAPTURED', kind='integer'),
        })
    velocity = _blocked('rbd_velocity', 0, 1000, 'RBD_VELOCITY_VARIANCE_ATTRIBUTE_CONTRACT_REQUIRED')
    velocity.update(aliases=['snippet'], native_type='string', unit='SU/s per-axis initial velocity amplitude',
        native_program=RBD_VELOCITY_ROUTE, conditional_native_route=RBD_VELOCITY_ROUTE,
        runtime_scope='initial_active_packed_pieces_only',
        context_parms=[('rbd_velocity', '@basis'), ('rbd_velocity', '@program'),
                       ('configure', '@packed_geometry/0'), ('rbd_velocity', '@packed_geometry/0'),
                       ('solver', '@input_geometry/0')])
    return annotate_control_contract(pack, {
        'fracture_scale': _blocked('fracture', .001, 1000, 'PHYSICAL_FRAGMENT_SCALE_CONTRACT_REQUIRED'),
        'constraint_strength': _control('solver', 'glue_strength', 0, 1e12,
            gates=[('solver', 'glue_defaultparmop', 'always'), ('solver', 'glue_dataname', 'Glue')],
            unit='uniform effective native Glue strength; scalar physical unit NOT_CAPTURED',
            semantic_contract='uniform_native_glue_strength_with_unit_primitive_multiplier/1',
            context_parms=[('solver', '@input_geometry/1')]),
        'impact_threshold': _control('solver', 'constraint_impactthreshold#', 0, 1e12,
            gates=[('solver', 'enable_constraintbreaks', 1), ('solver', 'constraint_reloadfromsops', 0)],
            unit='native impact threshold; physical unit conversion NOT_CAPTURED', multiparm='breaks',
            multiparm_templates=list(_IMPACT_TEMPLATES),
            context_parms=[('solver', '@multiparm/breaks'), ('configure', '@geometry/1')]),
        'substeps': _control('solver', 'substeps', 1, 100, kind='integer', unit='Bullet substeps per frame'),
        'drag': _control('solver', 'drag_airresist', 0, 100,
            gates=[('solver', 'adddrag', 1), ('solver', 'drag_usegroup', 0), ('solver', 'drag_uselocaldrag', 0),
                   ('solver', 'drag_windvelocity', [0., 0., 0.])], unit='native air resistance; vendor token kg1s-1'),
        'fracture_variance': _blocked('fracture', 0, 100, 'FRACTURE_VARIANCE_DISTRIBUTION_CONTRACT_REQUIRED'),
        'impact_spread': _blocked('solver', 0, 1000, 'IMPACT_SPREAD_SEMANTIC_CONVERSION_REQUIRED'),
        'piece_scale': _blocked('fracture', .001, 1000, 'ACTUAL_PIECE_SCALE_GEOMETRY_CONTRACT_REQUIRED'),
        'velocity_variance': velocity,
        'activation_frame': _control('configure', 'active#', -100000, 100000, kind='integer', unit='integer scene frame; inactive before requested frame and active from it', semantic_contract='bridge.rbd-active-step/1', value_kind='trusted_constant_activation_channel', multiparm='attributes', multiparm_templates=list(_ACTIVE_TEMPLATES), context_parms=[('configure', '@multiparm/attributes'), ('configure', '@activation_channel'), ('solver', 'overwriteattributes')], gates=[('solver', 'overwritefromsop', 1), ('solver', 'minactivationimpulseoverride', 0)]),
        'impulse_scale': _blocked('solver', 0, 10000, 'RBD_IMPULSE_SCALE_SEMANTIC_CONVERSION_REQUIRED'),
    })


def conditional_runtime_route(pack, control, value, version):
    """Defer R05 preflight to its existing authenticated host transaction.

    This identifies a fixed route only. It neither declares native availability
    nor replaces the actual basis, active-state, consumer and authority guards.
    Mapped controls return None; all other blocked controls retain their blocker.
    """
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeFlipRbdDomainError('UNKNOWN_NATIVE_CONTROL', str(control))
    contract = contracts[control]
    _number(value, contract['minimum'], contract['maximum'], control, contract['value_type'] == 'int')
    if contract.get('blocker') == 'H22_459_NATIVE_TEMPLATE_REQUIRED':
        raise NativeFlipRbdDomainError(contract['blocker'], control)
    if pack == RBD and control == 'velocity_variance':
        return RBD_VELOCITY_ROUTE
    if contract['native_status'] != 'mapped':
        raise NativeFlipRbdDomainError(contract['blocker'], control)
    return None


def _write(role, parm, value, kind='float', *, phase='values', size=1, **extra):
    return dict(role=role, parm=parm, value=value, native_type=kind, size=size, phase=phase,
                require_writable=True, require_readback=True, required_gates=[],
                frozen_readback_guards=[], invalidates_from='generation_simulation', **extra)


def _near(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_near(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _runtime(observations, role, parm, kind=None, size=1):
    fact = observations.get((role, parm), {})
    if fact.get('origin') != 'runtime_hom' or (kind is not None and fact.get('type') != kind) or fact.get('size') != size or fact.get('driven') is not False or 'value' not in fact:
        raise NativeFlipRbdDomainError('ACTUAL_NATIVE_CONTEXT_REQUIRED', role + '/' + parm)
    if not _typed_value(fact['value'], fact.get('type'), size):
        raise NativeFlipRbdDomainError('ACTUAL_NATIVE_CONTEXT_REQUIRED', role + '/' + parm)
    return fact


def _typed_value(value, kind, size):
    if type(size) is not int or size < 1: return False
    if size != 1:
        return isinstance(value, (tuple, list)) and len(value) == size and all(_typed_value(v, kind, 1) for v in value)
    if kind == 'float': return type(value) in (int, float) and -1e308 <= value <= 1e308 and math.isfinite(value)
    if kind in ('integer', 'multiparm'): return type(value) is int and -(2 ** 31) <= value < 2 ** 31
    if kind == 'toggle': return type(value) is int and value in (0, 1)
    if kind == 'string': return isinstance(value, str)
    if kind == 'ordinal': return isinstance(value, str) or type(value) is int
    return False


def _guard(role, parm, fact):
    guard = dict(role=role, parm=parm, value=copy.deepcopy(fact['value']), native_type=fact['type'],
                 size=fact['size'], require_undriven=True)
    if fact['type'] == 'ordinal':
        if fact.get('menu_uses_token_value') not in (True, False) or not isinstance(fact.get('menu_tokens'), (list, tuple)):
            raise NativeFlipRbdDomainError('ACTUAL_NATIVE_MENU_REQUIRED', role + '/' + parm)
        guard.update(menu_tokens=copy.deepcopy(fact['menu_tokens']), menu_uses_token_value=fact['menu_uses_token_value'])
    return guard


def _gate_spec(role, parm):
    fixed = {('fluid_source', 'createparticles'): ('toggle', 1), ('solver', 'overrideres'): ('toggle', 1),
             ('container', 'viscosity'): ('toggle', 1), ('container', 'dovaryingviscosity'): ('toggle', 1),
             ('container', 'dosurfacetension'): ('toggle', 1), ('surface', 'surfmethod'): ('ordinal', 1),
             ('solver', 'enable_constraintbreaks'): ('toggle', 1), ('solver', 'constraint_reloadfromsops'): ('toggle', 1),
             ('solver', 'glue_defaultparmop'): ('ordinal', 1), ('solver', 'glue_dataname'): ('string', 1),
             ('solver', 'adddrag'): ('toggle', 1), ('solver', 'drag_usegroup'): ('toggle', 1),
             ('solver', 'drag_uselocaldrag'): ('toggle', 1), ('solver', 'overwritefromsop'): ('toggle', 1), ('solver', 'minactivationimpulseoverride'): ('toggle', 1), ('solver', 'drag_windvelocity'): ('float', 3)}
    if (role, parm) in fixed: return fixed[(role, parm)]
    if role == 'configure':
        for template, kind in [('group#', 'string'), ('addactive#', 'toggle'), ('useactivebounds#', 'toggle')]:
            if re.fullmatch(re.escape(template).replace(r'\#', r'\d+'), parm): return kind, 1
    if role == 'solver':
        for template, kind in [('constraint_useimpact#', 'toggle'), ('constraint_scaleimpact#', 'integer'),
                               ('constraint_mode#', 'integer'), ('constraint_group#', 'string')]:
            if re.fullmatch(re.escape(template).replace(r'\#', r'\d+'), parm): return kind, 1
    raise NativeFlipRbdDomainError('NATIVE_GATE_INTERFACE_NOT_CAPTURED', role + '/' + parm)


_ACTIVE_TEMPLATES = ('group#', 'addactive#', 'active#', 'useactivebounds#')
_ACTIVE_SCHEMA = 'bridge.rbd-active-channel-observation/1'


_IMPACT_TEMPLATES = ('constraint_names#', 'constraint_group#', 'constraint_mode#',
                     'constraint_useimpact#', 'constraint_scaleimpact#', 'constraint_impactthreshold#')


def _unit_glue_geometry(observations):
    """Read actual per-primitive multipliers at the solver's constraint input."""
    fact = observations.get(('solver', '@input_geometry/1'), {})
    count = fact.get('primitives'); attributes = fact.get('primitive_attributes', {})
    values = fact.get('primitive_attribute_values', {})
    names = values.get('constraint_name'); strengths = values.get('strength')
    name_attribute = attributes.get('constraint_name', {}); strength_attribute = attributes.get('strength', {})
    if fact.get('origin') != 'runtime_hom' or type(count) is not int or count < 1 or name_attribute.get('type') != 'string' or name_attribute.get('size') != 1 or strength_attribute.get('type') != 'float' or strength_attribute.get('size') != 1:
        raise NativeFlipRbdDomainError('ACTUAL_UNIT_GLUE_PRIMITIVE_STRENGTHS_REQUIRED', 'solver/input1')
    if not isinstance(names, (tuple, list)) or not isinstance(strengths, (tuple, list)) or len(names) != count or len(strengths) != count or any(not isinstance(name, str) or not _typed_value(strength, 'float', 1) for name, strength in zip(names, strengths)):
        raise NativeFlipRbdDomainError('ACTUAL_UNIT_GLUE_PRIMITIVE_STRENGTHS_REQUIRED', 'solver/input1')
    glue = [i for i, name in enumerate(names) if name == 'Glue']
    if not glue or any(not _near(strengths[i], 1.) for i in glue):
        raise NativeFlipRbdDomainError('ACTUAL_UNIT_GLUE_PRIMITIVE_STRENGTHS_REQUIRED', 'solver/input1')
    return dict(role='solver', parm='@input_geometry/1', value=copy.deepcopy(fact))


def _multiparm_binding(observations, role, parent, templates):
    fact = observations.get((role, '@multiparm/' + parent), {})
    if not isinstance(fact, Mapping):
        raise NativeFlipRbdDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + parent)
    names = fact.get('bindings', {})
    if fact.get('origin') != 'runtime_hom' or fact.get('parent') != parent or type(fact.get('instance_count')) is not int or fact['instance_count'] != 1 or not isinstance(names, Mapping) or set(names) != set(templates):
        raise NativeFlipRbdDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + parent)
    indices = set()
    for template, name in names.items():
        m = re.fullmatch(re.escape(template).replace(r'\#', r'(\d+)'), name) if isinstance(name, str) else None
        if m is None:
            raise NativeFlipRbdDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', template)
        indices.add(m.group(1))
    if len(indices) != 1:
        raise NativeFlipRbdDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + parent)
    return names, dict(role=role, parm='@multiparm/' + parent, value=copy.deepcopy(fact))


def _impact_binding(observations):
    return _multiparm_binding(observations, 'solver', 'breaks', _IMPACT_TEMPLATES)


def _activation_fact(observations, version, parm):
    """Consume host-authenticated HOM channels; registrations alone are insufficient."""
    channel = observations.get(('configure', '@activation_channel'), {})
    if not isinstance(channel, Mapping):
        raise NativeFlipRbdDomainError('ACTUAL_OWNED_ACTIVE_CHANNEL_REQUIRED', parm)
    binding = channel.get('binding', {}); identity = channel.get('identity', {})
    if not isinstance(binding, Mapping) or not isinstance(identity, Mapping):
        raise NativeFlipRbdDomainError('ACTUAL_OWNED_ACTIVE_CHANNEL_REQUIRED', parm)
    root, path = binding.get('task_root'), binding.get('node_path')
    if (channel.get('origin') != 'runtime_hom' or channel.get('schema') != _ACTIVE_SCHEMA or
            channel.get('native_version') != version or channel.get('task_owned') is not True or
            not isinstance(root, str) or not root.startswith('/obj/') or '..' in root.split('/') or
            not isinstance(path, str) or not path.startswith(root + '/') or '..' in path.split('/') or
            str(PurePosixPath(root)) != root or str(PurePosixPath(path)) != path or
            binding.get('node_type') != 'rbdconfigure' or binding.get('category') != 'sop' or
            binding.get('parm') != parm or binding.get('template') != 'active#' or
            binding.get('type') != 'integer' or type(binding.get('size')) is not int or binding['size'] != 1 or
            not isinstance(binding.get('task_id'), str) or not binding['task_id'] or
            identity.get('task_id') != binding['task_id'] or
            type(identity.get('pid')) is not int or identity['pid'] <= 0 or
            not isinstance(identity.get('launch_nonce'), str) or not identity['launch_nonce'] or
            identity.get('version') != version or not isinstance(identity.get('session_id'), str) or not identity['session_id'] or
            not isinstance(identity.get('process_generation'), str) or not identity['process_generation'] or
            not re.fullmatch(r'[0-9a-f]{64}', str(identity.get('plugin_build',''))) or
            type(identity.get('scene_epoch')) is not int or identity['scene_epoch'] < 0 or
            not _typed_value(channel.get('current_frame'), 'float', 1) or
            channel.get('reference_path') is not None):
        raise NativeFlipRbdDomainError('ACTUAL_OWNED_ACTIVE_CHANNEL_REQUIRED', parm)
    fact = observations.get(('configure', parm), {})
    if (not isinstance(fact, Mapping) or fact.get('origin') != 'runtime_hom' or fact.get('type') != 'integer' or fact.get('size') != 1 or
            type(fact.get('value')) is not int or fact['value'] not in (0, 1)):
        raise NativeFlipRbdDomainError('ACTUAL_OWNED_ACTIVE_CHANNEL_REQUIRED', parm)
    keys = channel.get('keyframes'); ids = channel.get('keyframe_identities')
    if channel.get('mode') == 'undriven':
        if fact.get('driven') is not False or keys != [] or ids != [] or channel.get('registration') is not None or channel.get('expression') is not None:
            raise NativeFlipRbdDomainError('UNTRUSTED_ACTIVE_CHANNEL', parm)
        return fact, channel, None
    registration = channel.get('registration', {})
    if (not isinstance(registration, Mapping) or channel.get('mode') != 'bridge_constant_step' or fact.get('driven') is not True or
            registration.get('schema') != 'bridge.rbd-active-step/1' or registration.get('native_version') != version or
            registration.get('binding') != binding or channel.get('expression') not in (None, '', 'constant()')):
        raise NativeFlipRbdDomainError('UNTRUSTED_ACTIVE_CHANNEL', parm)
    frame = _number(registration.get('activation_frame'), -100000, 100000, 'activation_frame', True)
    expected = [dict(frame=frame-1, value=0, expression='constant()', language='Hscript'),
                dict(frame=frame, value=1, expression='constant()', language='Hscript')]
    if (not isinstance(keys,list) or len(keys) != 2 or any(not isinstance(k,dict) or type(k.get('frame')) is not int or type(k.get('value')) is not int for k in keys) or
            keys != expected or not isinstance(ids, list) or len(ids) != 2 or
            any(not isinstance(v, str) or not v for v in ids) or ids[0] == ids[1] or
            registration.get('keyframe_identities') != ids or
            channel.get('pre_extrapolation') != 'constant' or channel.get('post_extrapolation') != 'constant'):
        raise NativeFlipRbdDomainError('ACTIVE_CHANNEL_READBACK_MISMATCH', parm)
    # Bind the complete native asCode identities without parsing or dropping fields.
    payload = {k: registration[k] for k in ('schema', 'native_version', 'binding', 'activation_frame', 'keyframe_identities')}
    digest = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if registration.get('content_sha256') != digest:
        raise NativeFlipRbdDomainError('ACTIVE_CHANNEL_READBACK_MISMATCH', 'content binding')
    samples = [dict(frame=f, value=int(f >= frame)) for f in (frame-2, frame-1, frame, frame+1)]
    actual_samples = channel.get('samples')
    if (not isinstance(actual_samples,list) or len(actual_samples) != 4 or any(not isinstance(k,dict) or type(k.get('frame')) is not int or type(k.get('value')) is not int for k in actual_samples) or actual_samples != samples) or fact['value'] != int(channel['current_frame'] >= frame):
        raise NativeFlipRbdDomainError('ACTIVE_CHANNEL_READBACK_MISMATCH', 'actual evalAtFrame samples')
    return fact, channel, frame


def _activation_write_plan(value, version, observations):
    names, binding_guard = _multiparm_binding(observations, 'configure', 'attributes', _ACTIVE_TEMPLATES)
    parm = names['active#']; fact, channel, _ = _activation_fact(observations, version, parm)
    overwrite = _runtime(observations, 'solver', 'overwriteattributes', 'string')
    if 'active' not in overwrite['value'].split():
        raise NativeFlipRbdDomainError('ACTIVE_SOP_OVERWRITE_REQUIRED', 'solver/overwriteattributes')
    gates = [('solver', 'overwritefromsop', 1), ('solver', 'minactivationimpulseoverride', 0), ('configure', names['group#'], ''),
             ('configure', names['addactive#'], 1), ('configure', names['useactivebounds#'], 0)]
    target_guard = _guard('configure', parm, fact)
    target_guard.update(require_undriven=False, require_owned_active_channel=True, native_version=version)
    channel_guard = dict(role='configure', parm='@activation_channel', value=copy.deepcopy(channel),
        mutable_target=['configure', parm], immutable_fields=['origin','schema','native_version','task_owned','binding','identity','current_frame'])
    guards = [binding_guard, channel_guard, target_guard, _guard('solver', 'overwriteattributes', overwrite)]
    for role, field, _ in gates:
        kind, size = _gate_spec(role, field); guards.append(_guard(role, field, _runtime(observations, role, field, kind, size)))
    write = _write('configure', parm, value, 'integer', value_kind='trusted_constant_activation_channel',
        trusted_channel_id='bridge.rbd-active-step/1', native_version=version,
        schedule=[dict(frame=value-1,value=0),dict(frame=value,value=1)], interpolation='constant',
        require_full_native_keyframe_identity=True, require_eval_at_frame=True)
    write.update(required_gates=gates, frozen_readback_guards=guards)
    validate_control_write_plan([write], observations)
    return [write]


def control_write_plan(pack, control, value, version, *, observations=None):
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeFlipRbdDomainError('UNKNOWN_NATIVE_CONTROL', str(control))
    c = contracts[control]
    value = _number(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')
    if c.get('blocker') == 'H22_459_NATIVE_TEMPLATE_REQUIRED':
        raise NativeFlipRbdDomainError(c['blocker'], control)
    if pack == RBD and control == 'velocity_variance' and observations and ('rbd_velocity', '@basis') in observations:
        from .native_rbd_controls_program import velocity_write_plan
        return velocity_write_plan(value, version, observations)
    if c['native_status'] != 'mapped':
        raise NativeFlipRbdDomainError(c['blocker'], control)
    observations = observations or {}
    if pack == RBD and control == 'activation_frame':
        return _activation_write_plan(value, version, observations)
    gates = copy.deepcopy(c['required_gates']); guards = []
    targets = c.get('targets', [(c['role'], c['aliases'][0])])
    if pack == RBD and control == 'constraint_strength':
        guards.append(_unit_glue_geometry(observations))
    if pack == RBD and control == 'impact_threshold':
        names, binding_guard = _impact_binding(observations); guards.append(binding_guard)
        targets = [('solver', names['constraint_impactthreshold#'])]
        for template, expected, kind in [('constraint_useimpact#', 1, 'toggle'), ('constraint_scaleimpact#', 0, 'integer'), ('constraint_mode#', 0, 'integer'), ('constraint_group#', '', 'string')]:
            parm = names[template]; fact = _runtime(observations, 'solver', parm, kind)
            if not _near(fact['value'], expected):
                raise NativeFlipRbdDomainError('IMPACT_THRESHOLD_CONTEXT_REQUIRED', parm)
            gates.append(('solver', parm, expected))
        name_parm = names['constraint_names#']; name_fact = _runtime(observations, 'solver', name_parm, 'string')
        geo = observations.get(('configure', '@geometry/1'), {})
        selected = name_fact['value'].split() if isinstance(name_fact['value'], str) else []
        if not selected or any('*' in name or '?' in name for name in selected) or geo.get('origin') != 'runtime_hom' or not set(selected) <= set(geo.get('constraint_names', ())):
            raise NativeFlipRbdDomainError('ACTUAL_IMPACT_CONSTRAINT_TARGETS_REQUIRED', name_parm)
        guards.extend([_guard('solver', name_parm, name_fact), dict(role='configure', parm='@geometry/1', value=copy.deepcopy(geo))])
    writes = [_write(role, parm, value, c['native_type']) for role, parm in targets]
    if pack == FLIP and control == 'substeps':
        maximum = _runtime(observations, 'solver', 'substeps', 'integer')
        current = _number(maximum['value'], 1, 2147483647, 'actual maximum substeps', True)
        if current < value:
            writes.insert(0, _write('solver', 'substeps', value, 'integer'))
        else:
            guards.append(_guard('solver', 'substeps', maximum))
    for write in writes:
        old = _runtime(observations, write['role'], write['parm'], write['native_type'], write['size'])
        guards.append(_guard(write['role'], write['parm'], old))
    for role, parm, _ in gates:
        kind, size = _gate_spec(role, parm)
        guards.append(_guard(role, parm, _runtime(observations, role, parm, kind, size)))
    for w in writes:
        w.update(required_gates=copy.deepcopy(gates), frozen_readback_guards=copy.deepcopy(guards), invalidates_from=c['invalidates_from'])
    validate_control_write_plan(writes, observations)
    return writes


def candidate_write_plan(pack, controls, version, *, observations=None):
    _domain(pack, version)
    if not isinstance(controls, Mapping):
        raise NativeFlipRbdDomainError('INVALID_NATIVE_CONTROLS', 'mapping required')
    if pack == RBD and {'activation_frame', 'velocity_variance'} <= set(controls):
        raise NativeFlipRbdDomainError('RBD_INITIAL_VELOCITY_ACTIVATION_COMBINATION_UNSUPPORTED',
            'initial velocity carrier cannot change its activation basis in the same transaction')
    writes = []; by_key = {}
    for name, value in controls.items():
        for w in control_write_plan(pack, name, value, version, observations=observations):
            key = (w['role'], w['parm'])
            if key in by_key:
                prior = by_key[key]
                if not _near(prior['value'], w['value']):
                    raise NativeFlipRbdDomainError('CONFLICTING_NATIVE_CONTROLS', '/'.join(key))
                for field in ('required_gates', 'frozen_readback_guards'):
                    for item in w[field]:
                        if item not in prior[field]: prior[field].append(copy.deepcopy(item))
            else:
                writes.append(w); by_key[key] = w
    immutable_readback_guards(writes)
    return writes


def _gate_matches(actual, expected):
    if actual.get('type') == 'ordinal' and (expected not in actual.get('menu_tokens', ()) or actual.get('menu_uses_token_value') not in (True, False)):
        return False
    if _near(actual.get('value'), expected): return True
    tokens = actual.get('menu_tokens', []); value = actual.get('value')
    return actual.get('type') == 'ordinal' and actual.get('menu_uses_token_value') is False and type(value) is int and 0 <= value < len(tokens) and tokens[value] == expected


def validate_readback_guards(writes, observations, *, after_mutation=False):
    written = {(w['role'], w['parm']) for w in writes}
    for write in writes:
        for guard in write.get('frozen_readback_guards', ()):
            key = (guard['role'], guard['parm'])
            if after_mutation and key in written: continue
            actual = observations.get(key, {})
            if after_mutation and tuple(guard.get('mutable_target', ())) in written:
                if any(actual.get(k) != guard['value'].get(k) for k in guard['immutable_fields']):
                    raise NativeFlipRbdDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))
                continue
            if guard['parm'].startswith('@'):
                if actual.get('origin') != 'runtime_hom' or actual != guard['value']:
                    raise NativeFlipRbdDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))
            else:
                fact = (_activation_fact(observations, guard['native_version'], guard['parm'])[0]
                    if guard.get('require_owned_active_channel') else
                    _runtime(observations, *key, guard.get('native_type'), guard.get('size', 1)))
                if not _near(fact['value'], guard['value']) or any(fact.get(k) != guard[k] for k in ('menu_tokens', 'menu_uses_token_value') if k in guard):
                    raise NativeFlipRbdDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))


def validate_control_write_plan(writes, observations, *, after_mutation=False):
    if any(w.get('role') == 'rbd_velocity' for w in writes):
        from .native_rbd_controls_program import validate_velocity_plan
        validate_velocity_plan(writes, observations)
    for w in writes:
        if not _typed_value(w['value'], w['native_type'], w.get('size', 1)):
            raise NativeFlipRbdDomainError('INVALID_NATIVE_WRITE_VALUE', w['role'] + '/' + w['parm'])
        if w['role'] == 'configure' and re.fullmatch(r'active\d+', w['parm']) and w.get('value_kind') != 'trusted_constant_activation_channel':
            raise NativeFlipRbdDomainError('UNTRUSTED_ACTIVE_CHANNEL_WRITE', w['parm'])
        channel_write = w.get('value_kind') == 'trusted_constant_activation_channel'
        if channel_write:
            frame = _number(w['value'], -100000, 100000, 'activation_frame', True)
            if (w['role'] != 'configure' or w['native_type'] != 'integer' or w.get('size', 1) != 1 or
                    w.get('trusted_channel_id') != 'bridge.rbd-active-step/1' or w.get('native_version') not in (*VERSIONS, *PREPARATION_VERSIONS) or
                    w.get('schedule') != [dict(frame=frame-1,value=0),dict(frame=frame,value=1)] or w.get('interpolation') != 'constant' or
                    w.get('require_full_native_keyframe_identity') is not True or w.get('require_eval_at_frame') is not True):
                raise NativeFlipRbdDomainError('UNTRUSTED_ACTIVE_CHANNEL_WRITE', w['parm'])
            names, _ = _multiparm_binding(observations, 'configure', 'attributes', _ACTIVE_TEMPLATES)
            if names['active#'] != w['parm']:
                raise NativeFlipRbdDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', w['parm'])
            fact = _activation_fact(observations,w['native_version'],w['parm'])[0]
        else:
            fact = _runtime(observations, w['role'], w['parm'], w['native_type'], w.get('size', 1))
        if any(fact.get(flag) is not False for flag in ('locked', 'disabled', 'hidden')):
            raise NativeFlipRbdDomainError('NATIVE_CONTROL_GATE_BLOCKED', w['role'] + '/' + w['parm'])
        for role, parm, expected in w.get('required_gates', ()):
            kind, size = _gate_spec(role, parm)
            gate = _runtime(observations, role, parm, kind, size)
            if not _gate_matches(gate, expected):
                raise NativeFlipRbdDomainError('NATIVE_CONTROL_GATE_BLOCKED', role + '/' + parm)
        if w['native_type'] == 'ordinal' and w['value'] not in fact.get('menu_tokens', ()):
            raise NativeFlipRbdDomainError('NATIVE_MENU_TOKEN_REQUIRED', w['parm'])
    validate_readback_guards(writes, observations, after_mutation=after_mutation)


def validate_applied_readback(writes, observations):
    validate_control_write_plan(writes, observations, after_mutation=True)
    for w in writes:
        if w.get('value_kind') == 'trusted_constant_activation_channel':
            _, _, frame = _activation_fact(observations,w['native_version'],w['parm'])
            if frame != w['value']:
                raise NativeFlipRbdDomainError('ACTIVE_CHANNEL_READBACK_MISMATCH', w['parm'])
            continue
        if not _gate_matches(observations[(w['role'], w['parm'])], w['value']):
            raise NativeFlipRbdDomainError('NATIVE_CONTROL_READBACK_MISMATCH', w['role'] + '/' + w['parm'])
    if any(w.get('role') == 'rbd_velocity' for w in writes):
        from .native_rbd_controls_program import validate_velocity_readback
        validate_velocity_readback(writes, observations)


def immutable_readback_guards(writes):
    written = {(w['role'], w['parm']) for w in writes}; result = {}
    for w in writes:
        for guard in w.get('frozen_readback_guards', ()):
            key = (guard['role'], guard['parm'])
            if key in written: continue
            if key in result and result[key] != guard:
                raise NativeFlipRbdDomainError('CONFLICTING_NATIVE_CONTEXT', '/'.join(key))
            result[key] = copy.deepcopy(guard)
    return list(result.values())


def control_readback(pack, control, values, version, *, observations=None):
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeFlipRbdDomainError('UNKNOWN_NATIVE_CONTROL', str(control))
    c = contracts[control]
    if c.get('blocker') == 'H22_459_NATIVE_TEMPLATE_REQUIRED':
        raise NativeFlipRbdDomainError(c['blocker'], control)
    if pack == RBD and control == 'velocity_variance' and observations and ('rbd_velocity', '@basis') in observations:
        from .native_rbd_controls_program import velocity_control_readback
        return velocity_control_readback(version, observations)
    if c['native_status'] != 'mapped': raise NativeFlipRbdDomainError(c['blocker'], control)
    observations = observations or {}
    if pack == RBD and control == 'activation_frame':
        names, _ = _multiparm_binding(observations,'configure','attributes',_ACTIVE_TEMPLATES)
        _, _, value = _activation_fact(observations,version,names['active#'])
        if value is None:
            raise NativeFlipRbdDomainError('ACTIVE_CHANNEL_READBACK_MISMATCH','missing owned step')
        plan = _activation_write_plan(value,version,observations)
        validate_applied_readback(plan,observations)
        return value
    targets = c.get('targets', [(c['role'], c['aliases'][0])])
    if pack == RBD and control == 'impact_threshold':
        names, _ = _impact_binding(observations); targets = [('solver', names['constraint_impactthreshold#'])]
    try:
        value = values[targets[0]]
        if any(not _near(values[key], value) for key in targets[1:]):
            raise NativeFlipRbdDomainError('NATIVE_CONTROL_READBACK_MISMATCH', control)
    except KeyError as exc:
        raise NativeFlipRbdDomainError('NATIVE_CONTROL_READBACK_REQUIRED', str(exc)) from exc
    value = _number(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')
    # A minimum above the observed maximum cannot pass saved/reopened readback.
    if pack == FLIP and control == 'substeps':
        try: maximum = values[('solver', 'substeps')]
        except KeyError as exc: raise NativeFlipRbdDomainError('NATIVE_CONTROL_READBACK_REQUIRED', 'solver/substeps') from exc
        if _number(maximum, 1, 2147483647, 'actual maximum substeps', True) < value:
            raise NativeFlipRbdDomainError('NATIVE_CONTROL_READBACK_MISMATCH', control)
    plan = control_write_plan(pack, control, value, version, observations=observations)
    validate_applied_readback(plan, observations)
    return value


def _node(role, typ, parms=(), input_role=None):
    return dict(role=role, category='sop', types=[typ], input_role=input_role, required_parms=[[p] for p in parms])


def node_requirements(pack, version):
    _domain(pack, version)
    if pack == RBD:
        return [_node('source', 'box'), _node('fracture', 'rbdmaterialfracture', input_role='source'),
                _node('configure', 'rbdconfigure', ('attributes', *_ACTIVE_TEMPLATES)),
                _node('rbd_velocity', 'attribwrangle', ('class', 'group', 'snippet', 'vex_precision', 'exportlist', 'bindings')),
                _node('constraint_strength', 'attribwrangle', ('class','group','snippet')),
                _node('solver', 'rbdbulletsolver', ('substeps', 'overwritefromsop', 'overwriteattributes', 'minactivationimpulseoverride', 'glue_strength', 'glue_defaultparmop', 'glue_dataname', 'adddrag', 'drag_airresist', 'drag_usegroup', 'drag_uselocaldrag', 'drag_windvelocity', 'enable_constraintbreaks', 'constraint_reloadfromsops', 'breaks', *_IMPACT_TEMPLATES)),
                _node('output', 'null', input_role='solver')]
    return [_node('source', 'sphere'), _node('fluid_source', 'flipsource', ('createparticles', 'particlesep'), 'source'),
            _node('container', 'flipcontainer', ('particlesep', 'viscosity', 'dovaryingviscosity', 'default_viscosity', 'dosurfacetension', 'surfacetension')),
            _node('collision_source', 'box'), _node('collision_transform', 'xform', ('t', 's'), 'collision_source'),
            _node('collisions', 'flipcollide', ('activate', 'dovolume', 'dosurface')),
            _node('solver', 'flipsolver', ('overrideres', 'minimumsubsteps', 'substeps', 'collision')),
            _node('surface', 'particlefluidsurface::2.0', ('particlesep', 'voxelsize', 'surfmethod', 'surfacedistance', 'conversion', 'docollisions'), 'solver'),
            _node('output', 'null', input_role='surface')]


def connection_requirements(pack, version):
    _domain(pack, version)
    if pack == RBD:
        edges = [('source', 0, 'fracture', 0)]
        edges.extend(('fracture',i,'configure',i) for i in range(3))
        edges.extend([('configure', 0, 'rbd_velocity', 0), ('rbd_velocity', 0, 'solver', 0),
                      ('configure', 2, 'solver', 2)])
        edges.extend([('configure',1,'constraint_strength',0),('constraint_strength',0,'solver',1)])
        edges.append(('solver', 0, 'output', 0))
    else:
        edges = [('source', 0, 'fluid_source', 0), ('fluid_source', 0, 'container', 0),
                 ('collision_source', 0, 'collision_transform', 0), ('collision_transform', 0, 'collisions', 3)]
        for source, dest in [('container', 'collisions'), ('collisions', 'solver')]:
            edges.extend((source, i, dest, i) for i in range(3))
        edges.extend([('solver', 0, 'surface', 0), ('collisions', 2, 'surface', 1), ('surface', 0, 'output', 0)])
    return [dict(source_role=a, source_output=b, destination_role=c, destination_input=d) for a, b, c, d in edges]


def trusted_initialization_plan(pack, version, *, fresh=False, phase='all', observations=None, initialize_activation=False):
    _domain(pack, version)
    if fresh is not True: raise NativeFlipRbdDomainError('FRESH_TASK_OWNED_NODE_REQUIRED', pack)
    if phase not in ('all', 'allocate', 'gates', 'values'):
        raise NativeFlipRbdDomainError('UNKNOWN_INITIALIZATION_PHASE', str(phase))
    if pack == RBD:
        allocate = [_write('solver', 'breaks', 1, 'multiparm', phase='allocate')]
        if initialize_activation is True:
            allocate.append(_write('configure', 'attributes', 1, 'multiparm', phase='allocate'))
        if phase == 'allocate':
            for w in allocate: w['fresh_only'] = True
            return allocate
        if phase == 'values': return []
        observations = observations or {}
        names, binding_guard = _impact_binding(observations)
        geometry = observations.get(('configure', '@geometry/1'), {})
        selected = geometry.get('constraint_names')
        if geometry.get('origin') != 'runtime_hom' or not isinstance(selected, (list, tuple)) or not selected or any(not isinstance(name, str) or not name or any(c.isspace() or c in '*?' for c in name) for name in selected):
            raise NativeFlipRbdDomainError('ACTUAL_IMPACT_CONSTRAINT_TARGETS_REQUIRED', 'configure/constraints')
        items = [*allocate, _write('solver', 'adddrag', 1, 'toggle', phase='gates'),
                 _write('solver', 'drag_usegroup', 0, 'toggle', phase='gates'),
                 _write('solver', 'drag_uselocaldrag', 0, 'toggle', phase='gates'),
                 _write('solver', 'drag_windvelocity', [0., 0., 0.], 'float', size=3, phase='gates'),
                 _write('solver', 'glue_dataname', 'Glue', 'string', phase='gates'),
                 _write('solver', 'glue_defaultparmop', 'always', 'ordinal', phase='gates'),
                 _write('solver', 'enable_constraintbreaks', 1, 'toggle', phase='gates'),
                 _write('solver', 'constraint_reloadfromsops', 0, 'toggle', phase='gates'),
                 _write('solver', names['constraint_names#'], ' '.join(sorted(set(selected))), 'string', phase='gates'),
                 _write('solver', names['constraint_group#'], '', 'string', phase='gates'),
                 _write('solver', names['constraint_mode#'], 0, 'integer', phase='gates'),
                 _write('solver', names['constraint_useimpact#'], 1, 'toggle', phase='gates'),
                 _write('solver', names['constraint_scaleimpact#'], 0, 'integer', phase='gates')]
        for w in items[len(allocate):]:
            w['frozen_readback_guards'] = [copy.deepcopy(binding_guard), dict(role='configure', parm='@geometry/1', value=copy.deepcopy(geometry))]
        if initialize_activation is True:
            active_names, active_guard = _multiparm_binding(observations,'configure','attributes',_ACTIVE_TEMPLATES)
            activation_gates = [_write('configure',active_names['group#'],'','string',phase='gates'),
                _write('configure',active_names['addactive#'],1,'toggle',phase='gates'),
                _write('configure',active_names['useactivebounds#'],0,'toggle',phase='gates'),
                _write('solver','overwritefromsop',1,'toggle',phase='gates'),
                _write('solver','minactivationimpulseoverride',0,'toggle',phase='gates')]
            for w in activation_gates: w['frozen_readback_guards'] = [copy.deepcopy(active_guard)]
            items += activation_gates
        # Allocate first, then observe compiled instance names and constraint data.
    else:
        items = [_write('fluid_source', 'createparticles', 1, 'toggle', phase='gates'),
                 _write('solver', 'overrideres', 0, 'toggle', phase='gates'),
                 _write('container', 'viscosity', 1, 'toggle', phase='gates'),
                 _write('container', 'dovaryingviscosity', 0, 'toggle', phase='gates'),
                 _write('container', 'dosurfacetension', 1, 'toggle', phase='gates'),
                 _write('collisions', 'dovolume', 1, 'toggle', phase='gates'),
                 _write('collisions', 'dosurface', 1, 'toggle', phase='gates'),
                 _write('solver', 'collision', 'particle', 'ordinal', phase='gates'),
                 _write('surface', 'surfmethod', 'particlefluid', 'ordinal', phase='gates'),
                 _write('surface', 'conversion', 'poly', 'ordinal', phase='gates'),
                 _write('surface', 'docollisions', 1, 'toggle', phase='gates'),
                 *[_write(role, 'particlesep', .1) for role in ('fluid_source', 'container', 'surface')]]
    for w in items: w['fresh_only'] = True
    return copy.deepcopy([w for w in items if phase == 'all' or w['phase'] == phase])


def geometry_requirements(pack, version):
    _domain(pack, version)
    if pack == FLIP:
        return [dict(role='source', output=0, minimum_points=3, minimum_primitives=1),
                dict(role='fluid_source', output=0, minimum_points=1, point_attributes={'v': ('float', 3)}),
                dict(role='collision_transform', output=0, minimum_points=3, minimum_primitives=1),
                dict(role='collisions', output=2, minimum_primitives=1),
                dict(role='solver', output=0, minimum_points=1, point_attributes={'v': ('float', 3)}),
                dict(role='surface', output=0, minimum_points=3, minimum_primitives=1, primitive_types=['Polygon'])]
    return [dict(role='source', output=0, minimum_points=4, minimum_primitives=1),
            dict(role='fracture', output=0, minimum_primitives=2, primitive_attributes={'name': ('string', 1)}),
            dict(role='configure', output=1, minimum_primitives=1, primitive_attributes={'constraint_name': ('string', 1), 'constraint_type': ('string', 1)}),
            dict(role='solver', output=0, minimum_primitives=2)]


def validate_geometry_readback(pack, version, observations):
    """Validate host-collected HOM output summaries and the actual input edges."""
    for requirement in geometry_requirements(pack, version):
        key = (requirement['role'], '@geometry/' + str(requirement['output'])); fact = observations.get(key, {})
        if fact.get('origin') != 'runtime_hom':
            raise NativeFlipRbdDomainError('ACTUAL_NATIVE_GEOMETRY_REQUIRED', '/'.join(key))
        for kind in ('points', 'primitives'):
            count = fact.get(kind); minimum = requirement.get('minimum_' + kind, 0)
            if type(count) is not int or count < minimum:
                raise NativeFlipRbdDomainError('NATIVE_GEOMETRY_READBACK_MISMATCH', '/'.join(key) + '/' + kind)
        for owner in ('point', 'primitive'):
            for name, (kind, size) in requirement.get(owner + '_attributes', {}).items():
                attribute = fact.get(owner + '_attributes', {}).get(name, {})
                if attribute.get('type') != kind or attribute.get('size') != size:
                    raise NativeFlipRbdDomainError('NATIVE_GEOMETRY_READBACK_MISMATCH', '/'.join(key) + '/' + name)
        if 'primitive_types' in requirement:
            types = fact.get('primitive_types')
            if not isinstance(types, (list, tuple)) or not types or not set(types) <= set(requirement['primitive_types']):
                raise NativeFlipRbdDomainError('NATIVE_GEOMETRY_READBACK_MISMATCH', '/'.join(key) + '/primitive_types')
    for edge in connection_requirements(pack, version):
        key = (edge['destination_role'], '@input/' + str(edge['destination_input']))
        fact = observations.get(key, {})
        if fact.get('origin') != 'runtime_hom' or fact.get('source_role') != edge['source_role'] or fact.get('source_output') != edge['source_output']:
            raise NativeFlipRbdDomainError('ACTUAL_NATIVE_CONNECTION_REQUIRED', '/'.join(key))


def overlay_host_pack(pack_id, pack: Mapping, version):
    contracts = control_contract(pack_id, version); result = copy.deepcopy(dict(pack))
    if not isinstance(result.get('controls'), dict) or set(result['controls']) != set(contracts):
        raise NativeFlipRbdDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', pack_id)
    for name, c in result['controls'].items(): c.update(copy.deepcopy(contracts[name]))
    roles = {n['role'] for n in node_requirements(pack_id, version)}
    extras = [n for n in result.get('nodes', ()) if n.get('role') not in roles]
    result.update(nodes=node_requirements(pack_id, version) + extras, connections=connection_requirements(pack_id, version),
                  native_plan_schema=SCHEMA, native_version=version, native_execution=False)
    return result


def overlay_core_pack_dict(pack: Mapping, version):
    result = copy.deepcopy(dict(pack)); contracts = control_contract(result['id'], version)
    if not isinstance(result.get('controls'), list) or len(result['controls']) != len(contracts) or {c.get('id') for c in result['controls']} != set(contracts):
        raise NativeFlipRbdDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', result['id'])
    nodes = [dict(n, types=n.get('type_candidates', []), required_parms=n.get('required_parameter_aliases', [])) for n in result.get('nodes', ())]
    host = overlay_host_pack(result['id'], dict(nodes=nodes, controls={c['id']: {} for c in result['controls']}), version)
    result['nodes'] = []
    for n in host['nodes']:
        item = copy.deepcopy(n); item['type_candidates'] = item.pop('types'); item['required_parameter_aliases'] = item.pop('required_parms'); result['nodes'].append(item)
    for c in result['controls']:
        item = copy.deepcopy(contracts[c['id']]); c['node_role'] = item.pop('role'); c['parameter_aliases'] = item.pop('aliases'); c.update(item)
    result.update(connections=host['connections'], native_plan_schema=SCHEMA, native_version=version, native_execution=False)
    return result
