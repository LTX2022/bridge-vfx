"""Pure native plans for the existing trusted atomic domain adapter.

No HOM calls, scene construction, cooking or operation state live here. Node
ownership and actual connections are collected by the host from its lease and
manifest, never inferred from a template or accepted from caller JSON.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import math
from pathlib import PurePosixPath
from typing import Mapping

from .product_control_definitions import annotate_control_contract

SCHEMA = 'bridge.native-particle-ocean-geometry-domains/1'
PARTICLES = 'particles_v1'
SWARM = 'swarm_flocking_v1'
OCEAN = 'water_ocean_v1'
GEOMETRY = 'procedural_geometry_v1'
DOMAIN_IDS = (PARTICLES, SWARM, OCEAN, GEOMETRY)
VERSIONS = ('21.0.631', '22.0.429')


class NativeParticleOceanGeometryDomainError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _domain(pack, version):
    if version not in (*VERSIONS, *PREPARATION_VERSIONS):
        raise NativeParticleOceanGeometryDomainError('UNSUPPORTED_NATIVE_VERSION', str(version))
    if pack not in DOMAIN_IDS:
        raise NativeParticleOceanGeometryDomainError('UNKNOWN_NATIVE_DOMAIN', str(pack))


def _number(value, lo, hi, name, integer=False):
    if type(value) not in (int, float) or not lo <= value <= hi or not math.isfinite(value) or (integer and type(value) is not int):
        raise NativeParticleOceanGeometryDomainError('INVALID_NATIVE_CONTROL_VALUE', str(name))
    return int(value) if integer else float(value)


def _typed_value(value, kind, size):
    if type(size) is not int or size < 1:
        return False
    if size != 1:
        return isinstance(value, (list, tuple)) and len(value) == size and all(_typed_value(v, kind, 1) for v in value)
    if kind == 'float': return type(value) in (int, float) and -1e308 <= value <= 1e308 and math.isfinite(value)
    if kind == 'integer': return type(value) is int and -(2 ** 31) <= value < 2 ** 31
    if kind == 'toggle': return type(value) is int and value in (0, 1)
    if kind == 'string': return isinstance(value, str)
    if kind == 'ordinal': return isinstance(value, str) or type(value) is int
    return False


def _near(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return _typed_value(a, 'float', 1) and _typed_value(b, 'float', 1) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_near(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


_EMISSION_GATES = [('emission', 'emittype', 'surface'), ('emission', 'usecontextgeo', 'first')]
_BIRTH_GATES = _EMISSION_GATES + [('emission', 'constantactivate', 1.), ('emission', 'impulseactiveate', 0.),
    ('emission', 'scalebyarea', 0), ('emission', 'emitattrib', ''), ('emission', 'usesimpointlimit', 0),
    ('emission', 'useframepointlimit', 0), ('emission', 'removeoverlap', 'none')]
_VELOCITY_GATES = _EMISSION_GATES + [('emission', 'initvel', 'set'), ('solver', 'integratevel', 1), ('solver', 'integratepos', 1)]
_LIFE_GATES = [('solver', 'doage', 1), ('solver', 'doreapparticles', 1)]
_DRAG_GATES = [('drag', 'activate', 1.), ('drag', 'usegroup', 0), ('drag', 'uselocaldrag', 0),
    ('drag', 'ignoremass', 1), ('drag', 'windvelocity', [0., 0., 0.])]
_FORCE_GATES = [('force', 'activate', 1.), ('force', 'usegroup', 0), ('force', 'uselocalforce', 0),
    ('force', 'uselocalnoise', 0), ('force', 'ignoremass', 1), ('solver', 'externalforce', 1), ('solver', 'integratevel', 1), ('solver', 'integratepos', 1)]
_SWARM_NOISE_GATES = [('noise_force' if r == 'force' else r, p, v) for r,p,v in _FORCE_GATES] + [('noise_force','force',[0.,0.,0.])]
_CLUSTER_GATES = [('cluster', 'activate', 1), ('cluster', 'usegroup', 0), ('cluster', 'ignoremass', 1),
    ('cluster', 'numcenters', 1), ('cluster', 'interactionforce', 0.), ('cluster', 'velmatchforce', 0.),
    ('solver', 'externalforce', 1), ('solver', 'integratevel', 1), ('solver', 'integratepos', 1)]
_FLOCK_GATES = [('flock', 'activate', 1), ('flock', 'usegroup', 0), ('flock', 'ignoremass', 1)]
_SEEK_GATES = [('seek', 'activate', 1.), ('seek', 'usegroup', 0), ('seek', 'output', '1'),
    ('seek', 'attracttype', 'position'), ('seek', 'uselocalgoal', 0), ('seek', 'uselocalforce', 0), ('seek', 'ignoremass', 1)]


def _attribute_gates(role, pattern):
    gates = [(role, 'attrib', 'pscale'), (role, 'class', 'point'), (role, 'adjustvalue', 1),
        (role, 'operation', 'set'), (role, 'valuetype', pattern), (role, 'unitsettings', 'none'),
        (role, 'doblend', 0), (role, 'enable_postprocess', 0), (role, 'group', '')]
    if pattern == 'rand':
        gates += [(role, 'rangemethod', 'minplusrange'), (role, 'minvalue', 1.),
            (role, 'distribinrange', 'uniform'), (role, 'enablestepping', 0)]
    return gates


def _gate_spec(role, parm):
    if role == 'emission':
        if parm in ('emittype', 'usecontextgeo', 'initvel', 'removeoverlap'): return 'ordinal', 1
        if parm in ('constantactivate', 'impulseactiveate'): return 'float', 1
        if parm == 'emitattrib': return 'string', 1
        if parm in ('scalebyarea', 'usesimpointlimit', 'useframepointlimit', 'doid'): return 'toggle', 1
    if role == 'solver' and parm in ('integratevel', 'integratepos', 'externalforce', 'doage', 'doreapparticles'): return 'toggle', 1
    if role in ('drag', 'flock', 'seek', 'force', 'noise_force', 'cluster'):
        if parm == 'activate': return ('integer' if role in ('flock', 'cluster') else 'float'), 1
        if parm in ('usegroup', 'uselocaldrag', 'uselocalgoal', 'uselocalforce', 'uselocalnoise', 'ignoremass'): return 'toggle', 1
        if parm == 'numcenters' and role == 'cluster': return 'integer', 1
        if parm in ('interactionforce', 'velmatchforce') and role == 'cluster': return 'float', 1
        if parm == 'windvelocity' and role == 'drag': return 'float', 3
        if parm == 'force' and role == 'noise_force': return 'float', 3
        if parm in ('output', 'attracttype') and role == 'seek': return 'ordinal', 1
    if role in ('particle_size', 'point_variation'):
        if parm in ('attrib', 'group'): return 'string', 1
        if parm in ('class', 'operation', 'valuetype', 'unitsettings', 'rangemethod', 'distribinrange'): return 'ordinal', 1
        if parm in ('adjustvalue', 'doblend', 'enable_postprocess', 'enablestepping'): return 'toggle', 1
        if parm == 'minvalue': return 'float', 1
    if role == 'evaluate' and parm == 'deformgeo': return 'toggle', 1
    if role == 'scatter':
        if parm == 'generateby': return 'ordinal', 1
        if parm in ('forcetotal', 'indepvoxel', 'usedensityattrib', 'useareaattrib'): return 'toggle', 1
        if parm == 'group': return 'string', 1
    if role == 'foam_emit':
        if parm in ('mode', 'region'): return 'ordinal', 1
        if parm in ('domincusp', 'dominvel', 'dominheight', 'dodisplace'): return 'toggle', 1
    raise NativeParticleOceanGeometryDomainError('NATIVE_GATE_INTERFACE_NOT_CAPTURED', role + '/' + parm)


def _control(role, parm, lo, hi, *, kind='float', size=1, gates=(), phase='generation_simulation', unit, **extra):
    result = dict(role=role, aliases=[parm] if parm else [], minimum=lo, maximum=hi,
        value_type='int' if kind == 'integer' else 'float', native_type=kind, size=size,
        application='houdini', required_gates=copy.deepcopy(list(gates)), invalidates_from=phase,
        unit=unit, native_status='mapped')
    result.update(extra)
    return result


def _blocked(role, lo, hi, blocker, *, kind='float', phase='generation_simulation'):
    return _control(role, None, lo, hi, kind=kind, phase=phase, unit='NOT_CAPTURED',
        **dict(native_status='blocked', blocker=blocker))


@versioned_controls
def control_contract(pack, version):
    _domain(pack, version)
    if pack == PARTICLES:
        controls = {
            'birth_rate': _control('emission', 'constantrate', 0, 10000000, gates=_BIRTH_GATES, unit='expected particles per second; unscaled surface source rate'),
            'life': _control('emission', 'life', .01, 1000, gates=_LIFE_GATES, unit='seconds'),
            'speed': _control('emission', 'vel', 0, 1000, size=3, gates=_VELOCITY_GATES, unit='native scene units per second along the observed trusted unit axis', semantic_contract='native_initial_velocity_axis_gain/1', context_parms=[('emission', '@trusted_axis')]),
            'drag': _control('drag', 'airresist', 0, 100, gates=_DRAG_GATES, unit='native air resistance with Ignore Mass; vendor token kg1s-1, physical conversion NOT_CAPTURED'),
            'size': _control('particle_size', 'singlevalue', .0001, 100, gates=_attribute_gates('particle_size', 'const'), unit='native point pscale multiplier for instancing; physical collision radius NOT_CAPTURED'),
            'emission_variance': _control('emission', 'constantrate', 0, 100,
                gates=_BIRTH_GATES, unit='percent bounded scene-second emission-rate modulation',
                semantic_contract='owned_particle_emission_expression/1',
                evidence_scope='parameter_expression_requires_native_substep_integration',
                context_parms=[('emission', '@emission_context')]),
            'life_variance': _control('emission', 'lifevar', 0, 1000, gates=_LIFE_GATES, unit='plus or minus seconds around Life Expectancy; not statistical variance'),
            'velocity_variance': _control('emission', 'var', 0, 1000, size=3, gates=_VELOCITY_GATES, unit='native per-axis plus or minus initial velocity range along the absolute trusted axis; not statistical variance', semantic_contract='native_initial_velocity_axis_range/1', context_parms=[('emission', '@trusted_axis')]),
            'force_noise': _control('force', 'amp', 0, 1000, gates=_FORCE_GATES, unit='native POP noise force amplitude with Ignore Mass; vendor force token kg1m1s-2, physical conversion NOT_CAPTURED'),
            'size_variance': _control('particle_size', 'rangevalue', 0, 100,
                gates=[], phase='shaping_meshing',
                unit='percent bounded instance pscale amplitude about an independently frozen size',
                semantic_contract='owned_particle_size_variance/1',
                evidence_scope='parameter_plan_requires_actual_pscale_and_copy_consumption',
                context_parms=[('particle_size', '@size_basis'), ('particle_size', '@size_context')]),
            'force_strength': _control('force', 'force', -10000, 10000, size=3, gates=_FORCE_GATES, unit='native signed POP force gain along the observed trusted unit axis with Ignore Mass', semantic_contract='native_force_axis_gain/1', context_parms=[('emission', '@trusted_axis')]),
            'collision_radius': _blocked('solver', 0, 1000, 'PARTICLE_COLLISION_RADIUS_NATIVE_CONVENTION_REQUIRED'),
            'trail_length': _blocked('output', 0, 10000, 'PARTICLE_TRAIL_GEOMETRY_GRAPH_REQUIRED', phase='shaping_meshing'),
            'motion_blur_scale': _blocked('output', 0, 100, 'PARTICLE_RENDER_MOTION_BLUR_BINDING_REQUIRED', phase='render'),
            'cluster_strength': _control('cluster', 'centralforce', 0, 100, gates=_CLUSTER_GATES, unit='native central attraction toward one particle group center; avoidance and velocity matching disabled'),
        }
    elif pack == SWARM:
        controls = {
            'cohesion': _control('flock', 'centralforce', 0, 100, gates=_FLOCK_GATES, unit='native central attraction force scalar; physical unit NOT_CAPTURED'),
            'separation': _control('flock', 'interactionforce', 0, 100, gates=_FLOCK_GATES, unit='native avoidance force scalar; physical unit NOT_CAPTURED'),
            'alignment': _control('flock', 'velmatchforce', 0, 100, gates=_FLOCK_GATES, unit='native velocity matching force scalar; physical unit NOT_CAPTURED'),
            'neighbor_radius': _control('flock', 'centermaxdist', .001, 10000, gates=_FLOCK_GATES, unit='native central maximum distance; vendor scene length token m1'),
            'goal_attraction': _control('seek', 'forcescale', 0, 100, gates=_SEEK_GATES, unit='native goal force scale; vendor token kg1m1s-2, physical conversion NOT_CAPTURED', context_parms=[('seek', 'goal')]),
            'target_noise': _control('seek', 'goal', 0, 100, size=3, gates=_SEEK_GATES, unit='shared goal perturbation radius in scene units', semantic_contract='owned_swarm_goal_channels/1', context_parms=[('seek','@swarm_basis'),('seek','@swarm_channels')]),
            'noise_strength': _control('noise_force', 'amp', 0, 1000, gates=_SWARM_NOISE_GATES, unit='native POP noise amplitude with Ignore Mass; SI conversion not captured', context_parms=[('seek','@swarm_basis')]),
        }
    elif pack == OCEAN:
        gain = _control('spectrum', 'ampscale', 0, 100, gates=[('evaluate', 'deformgeo', 1)], phase='source_layout_control', unit='native uniform wave amplitude gain; vendor length token m1, physical conversion NOT_CAPTURED')
        controls = {
            'wave_scale': gain,
            'wind_speed': _control('spectrum', 'windspeed', 0, 200, gates=[('evaluate', 'deformgeo', 1)], phase='source_layout_control', unit='native wind speed; vendor token m1s-1'),
            'wind_direction': _control('spectrum', 'winddir', -360, 360, gates=[('evaluate', 'deformgeo', 1)], phase='source_layout_control', unit='degrees; zero is along the X axis'),
            'chop': _control('spectrum', 'chopscale', 0, 10, gates=[('evaluate', 'deformgeo', 1)], phase='source_layout_control', unit='native chop scalar'),
            'foam': _control('ocean_masks', 'snippet', 0, 1, kind='string', phase='shaping_meshing', unit='owned native-cusp rest-cell coverage enable', semantic_contract='owned_ocean_native_cusp_rest_cell_coverage/1', context_parms=[('ocean_masks','class'),('ocean_masks','group'),('ocean_masks','vex_precision'),('source','@ocean_source'),('evaluate','@ocean_surface'),('spectrum','@ocean_spectrum'),('foam_emit','@ocean_emit'),('ocean_masks','@ocean_stage'),('ocean_masks','@ocean_geometry')]),
            'spectrum_amplitude': copy.deepcopy(gain),
            'directional_spread': _blocked('spectrum', 0, 360, 'OCEAN_ANGULAR_SPREAD_TO_NATIVE_BIAS_CONVERSION_REQUIRED', phase='source_layout_control'),
            'crest_threshold': _control('foam_emit', 'mincusp', 0, 100, gates=[('foam_emit', 'mode', 'emit'), ('foam_emit', 'region', 'grid'), ('foam_emit', 'domincusp', 1)], phase='shaping_meshing', unit='native minimum cusp level for foam particle emission; owned rest-cell foam_mask coverage', context_parms=[('foam_emit', 'size'), ('foam_emit', 't'), ('source', '@geometry/0')]),
            'foam_amount': _control('foam_emit', 'density', 0, 100, gates=[('foam_emit', 'mode', 'emit'), ('foam_emit', 'region', 'grid')], phase='shaping_meshing', unit='foam particles per native scene area before emission criteria; owned rest-cell foam_mask coverage', context_parms=[('foam_emit', 'size'), ('foam_emit', 't'), ('source', '@geometry/0')]),
        }
        controls['foam']['value_type'] = 'bool'
    else:
        variation = _control('point_variation', 'rangevalue', 0, 100, gates=_attribute_gates('point_variation', 'rand'), phase='shaping_meshing', unit='length of uniform native point pscale range [1,1+value]; not statistical variance')
        controls = {
            'scatter_density': _control('scatter', 'npts', 0, 10000000, kind='integer', gates=[('scatter', 'generateby', 'bydensity'), ('scatter', 'forcetotal', 1), ('scatter', 'indepvoxel', 0)], phase='source_layout_control', unit='exact native forced total point count; requires actual count mode'),
            'seed': _control('scatter', 'seed', 0, 2147483647, kind='integer', phase='source_layout_control', unit='native global random seed'),
            'scale': _control('instance_transform', 'scale', .0001, 10000, phase='shaping_meshing', unit='native uniform scaling multiplier'),
            'variation': variation,
            'scatter_variance': _blocked('scatter', 0, 1000, 'SCATTER_STATISTICAL_VARIANCE_CONVERSION_REQUIRED', phase='source_layout_control'),
            'scale_variance': copy.deepcopy(variation),
            'rotation_variance': _blocked('instance', 0, 360, 'INSTANCE_RANDOM_ROTATION_ATTRIBUTE_GRAPH_REQUIRED', phase='shaping_meshing'),
            'deformation': _control('geometry_deform', 'snippet', 0, 100, kind='string', phase='shaping_meshing',
                unit='SU; frozen rest-space instance-source sinusoidal normal displacement before scale/rotation',
                semantic_contract='trusted_geometry_deform_program/1',
                evidence_scope='parameters_only_requires_actual_deformation_and_downstream_consumption',
                context_parms=[('geometry_deform', '@geometry_context'), ('geometry_deform', '@geometry_parameters')]),
            'density': _control('scatter', 'densityscale', 0, 10000000, gates=[('scatter', 'generateby', 'bydensity'), ('scatter', 'forcetotal', 0), ('scatter', 'indepvoxel', 0), ('scatter', 'usedensityattrib', 0), ('scatter', 'useareaattrib', 0), ('scatter', 'group', '')], phase='source_layout_control', unit='expected points per native scene area on the observed polygon surface without density or area attribute weights', context_parms=[('scatter', '@input_geometry/0')]),
            'rotation': _control('instance_transform', 'r', -360, 360, size=3, phase='shaping_meshing', unit='native Z rotation in degrees; preserve actual X and Y', semantic_contract='native_rotation_z_preserve_xy/1'),
        }
    context = [(n['role'], '@node') for n in node_requirements(pack, version)]
    context += [(e['destination_role'], '@input/' + str(e['destination_input'])) for e in connection_requirements(pack, version)]
    for c in controls.values():
        if c['native_status'] == 'mapped':
            c['context_parms'] = c.get('context_parms', []) + context
    return annotate_control_contract(pack, controls)


def _node(role, typ, *, category='sop', parms=(), parent=None):
    return dict(role=role, category=category, types=[typ], required_parms=[[p] for p in parms],
        input_role=None, context_parent_role=parent)


def node_requirements(pack, version):
    _domain(pack, version)
    if pack in (PARTICLES, SWARM):
        nodes = [_node('source', 'sphere'), _node('simulation', 'dopnet'),
            _node('particle_object', 'popobject', category='dop', parent='simulation'),
            _node('emission', 'popsource::2.0', category='dop', parent='simulation', parms=('emittype', 'usecontextgeo', 'initvel', 'constantrate', 'life', 'lifevar', 'vel', 'var', 'doid', 'constantactivate', 'impulseactiveate', 'scalebyarea', 'emitattrib', 'usesimpointlimit', 'useframepointlimit', 'removeoverlap'))]
        if pack == PARTICLES:
            nodes += [_node('drag', 'popdrag', category='dop', parent='simulation', parms=('airresist', 'activate', 'usegroup', 'uselocaldrag', 'ignoremass', 'windvelocity')),
                _node('force', 'popforce', category='dop', parent='simulation', parms=('force', 'amp', 'activate', 'usegroup', 'uselocalforce', 'uselocalnoise', 'ignoremass')),
                _node('cluster', 'popflock', category='dop', parent='simulation', parms=('centralforce', 'activate', 'usegroup', 'ignoremass', 'numcenters', 'interactionforce', 'velmatchforce'))]
        else:
            nodes += [_node('flock', 'popflock', category='dop', parent='simulation', parms=('centralforce', 'interactionforce', 'velmatchforce', 'centermaxdist', 'activate', 'usegroup', 'ignoremass')),
                _node('seek', 'popsteerseek', category='dop', parent='simulation', parms=('forcescale', 'goal', 'activate', 'usegroup', 'output', 'attracttype', 'uselocalgoal', 'uselocalforce', 'ignoremass', 'bindgeo'))]
        if pack == SWARM:
            nodes += [_node('noise_force','popforce',category='dop',parent='simulation',parms=('amp','force','activate','usegroup','uselocalforce','uselocalnoise','ignoremass','swirlsize','swirlscale','pulselength','rough','atten','turb','offset','bindgeo'))]
        nodes += [_node('solver', 'popsolver::2.0', category='dop', parent='simulation', parms=('integratevel', 'integratepos', 'doage', 'doreapparticles') + ('externalforce',)),
            _node('simulation_output', 'output', category='dop', parent='simulation'),
            _node('particle_size', 'attribadjustfloat', parms=('singlevalue',) + tuple(p for _, p, _ in _attribute_gates('particle_size', 'const'))),
            _node('instance_source', 'sphere'), _node('instances', 'copytopoints::2.0'), _node('output', 'null')]
        return nodes
    if pack == OCEAN:
        return [_node('source', 'grid'), _node('spectrum', 'oceanspectrum', parms=('ampscale', 'windspeed', 'winddir', 'chopscale')),
            _node('evaluate', 'oceanevaluate::2.0', parms=('deformgeo',)),
            _node('foam_emit', 'oceanfoam', parms=('mode', 'region', 'size', 't', 'density', 'domincusp', 'mincusp', 'dominvel', 'dominheight', 'dodisplace')),
            _node('ocean_masks','attribwrangle',parms=('class','group','snippet','vex_precision')),
            _node('output', 'null')]
    return [_node('source', 'grid'), _node('instance_source', 'sphere'),
        _node('geometry_deform', 'attribwrangle', parms=('class', 'group', 'snippet', 'vex_precision')),
        _node('instance_transform', 'xform', parms=('scale', 'r')),
        _node('scatter', 'scatter::2.0', parms=('seed', 'npts', 'densityscale', 'generateby', 'forcetotal', 'indepvoxel', 'usedensityattrib', 'useareaattrib', 'group')),
        _node('point_variation', 'attribadjustfloat', parms=('rangevalue',) + tuple(p for _, p, _ in _attribute_gates('point_variation', 'rand'))),
        _node('instance', 'copytopoints::2.0'), _node('output', 'null')]


def connection_requirements(pack, version):
    _domain(pack, version)
    if pack in (PARTICLES, SWARM):
        force = 'cluster' if pack == PARTICLES else 'seek'
        edges = [('source', 0, 'simulation', 0), ('particle_object', 0, 'solver', 0)]
        edges += [('emission', 0, 'drag', 0), ('drag', 0, 'force', 0), ('force', 0, 'cluster', 0)] if pack == PARTICLES else [('emission', 0, 'flock', 0), ('flock', 0, 'seek', 0)]
        if pack == SWARM: edges += [('noise_force',0,'solver',1)]
        edges += [(force, 0, 'solver', 2), ('solver', 0, 'simulation_output', 0), ('simulation', 0, 'particle_size', 0),
            ('instance_source', 0, 'instances', 0), ('particle_size', 0, 'instances', 1), ('instances', 0, 'output', 0)]
    elif pack == OCEAN:
        edges = [('source', 0, 'evaluate', 0), ('spectrum', 0, 'evaluate', 1), ('spectrum', 0, 'foam_emit', 0), ('evaluate', 0, 'ocean_masks', 0), ('spectrum', 0, 'ocean_masks', 1), ('source', 0, 'ocean_masks', 2), ('ocean_masks', 0, 'output', 0)]
    else:
        edges = [('source', 0, 'scatter', 0), ('instance_source', 0, 'geometry_deform', 0),
            ('geometry_deform', 0, 'instance_transform', 0),
            ('instance_transform', 0, 'instance', 0), ('scatter', 0, 'point_variation', 0), ('point_variation', 0, 'instance', 1), ('instance', 0, 'output', 0)]
    return [dict(source_role=a, source_output=b, destination_role=c, destination_input=d) for a, b, c, d in edges]


def _path(path):
    return isinstance(path, str) and path.startswith('/') and str(PurePosixPath(path)) == path and '..' not in PurePosixPath(path).parts


def validate_topology_readback(pack, version, observations):
    """Require actual role paths authenticated by both the host lease and manifest."""
    _domain(pack, version)
    roots = set(); paths = set(); nodes = {}
    for n in node_requirements(pack, version):
        role = n['role']; fact = observations.get((role, '@node'), {})
        path = fact.get('path'); root = fact.get('task_root'); parent = fact.get('context_parent_path')
        if fact.get('origin') != 'runtime_hom' or fact.get('task_owned') is not True or not _path(path) or not _path(root) or root == '/' or not path.startswith(root + '/') or parent != str(PurePosixPath(path).parent) or fact.get('type') not in n['types'] or fact.get('category') != n['category'] or path in paths:
            raise NativeParticleOceanGeometryDomainError('ACTUAL_TASK_OWNED_NATIVE_NODE_REQUIRED', role)
        roots.add(root); paths.add(path); nodes[role] = fact
    if len(roots) != 1:
        raise NativeParticleOceanGeometryDomainError('ACTUAL_TASK_OWNED_NATIVE_NODE_REQUIRED', 'task root differs')
    for n in node_requirements(pack, version):
        parent = n.get('context_parent_role')
        if parent and nodes[n['role']]['context_parent_path'] != nodes[parent]['path']:
            raise NativeParticleOceanGeometryDomainError('ACTUAL_NATIVE_NODE_CONTEXT_REQUIRED', n['role'])
    for edge in connection_requirements(pack, version):
        fact = observations.get((edge['destination_role'], '@input/' + str(edge['destination_input'])), {})
        source = nodes[edge['source_role']]
        if fact.get('origin') != 'runtime_hom' or fact.get('task_owned') is not True or fact.get('source_path') != source['path'] or fact.get('source_type') != source['type'] or type(fact.get('source_output')) is not int or fact['source_output'] != edge['source_output'] or type(fact.get('destination_input')) is not int or fact['destination_input'] != edge['destination_input']:
            raise NativeParticleOceanGeometryDomainError('ACTUAL_NATIVE_CONNECTION_REQUIRED', edge['destination_role'])


def _runtime(observations, role, parm, kind, size=1):
    fact = observations.get((role, parm), {})
    if fact.get('origin') != 'runtime_hom' or fact.get('type') != kind or type(fact.get('size')) is not int or fact['size'] != size or fact.get('driven') is not False or not _typed_value(fact.get('value'), kind, size):
        raise NativeParticleOceanGeometryDomainError('ACTUAL_NATIVE_CONTEXT_REQUIRED', role + '/' + parm)
    if kind == 'ordinal':
        tokens = fact.get('menu_tokens')
        if type(fact.get('menu_uses_token_value')) is not bool or not isinstance(tokens, (list, tuple)) or not tokens or any(not isinstance(t, str) for t in tokens) or len(tokens) != len(set(tokens)):
            raise NativeParticleOceanGeometryDomainError('ACTUAL_NATIVE_MENU_REQUIRED', role + '/' + parm)
    return fact


def _guard(role, parm, fact):
    if parm.startswith('@'):
        return dict(role=role, parm=parm, value=copy.deepcopy(fact))
    guard = dict(role=role, parm=parm, value=copy.deepcopy(fact['value']), native_type=fact['type'], size=fact['size'], require_undriven=True)
    if fact['type'] == 'ordinal':
        guard.update(menu_tokens=copy.deepcopy(fact['menu_tokens']), menu_uses_token_value=fact['menu_uses_token_value'])
    return guard


def _axis(observations):
    fact = observations.get(('emission', '@trusted_axis'), {})
    vector = fact.get('value')
    if fact.get('origin') != 'trusted_host_runtime' or not _typed_value(vector, 'float', 3) or not math.isclose(sum(v * v for v in vector), 1., rel_tol=1e-9, abs_tol=1e-12):
        raise NativeParticleOceanGeometryDomainError('ACTUAL_TRUSTED_UNIT_AXIS_REQUIRED', 'emission')
    return list(vector), _guard('emission', '@trusted_axis', fact)


def _write(role, parm, value, kind='float', *, size=1, phase='values', **extra):
    result = dict(role=role, parm=parm, value=copy.deepcopy(value), native_type=kind, size=size, phase=phase,
        require_task_owned=True, require_writable=True, require_readback=True, required_gates=[],
        frozen_readback_guards=[], invalidates_from='generation_simulation')
    result.update(extra)
    return result


def _foam_region(observations):
    region = observations.get(('source', '@geometry/0'), {})
    lo = region.get('bbox_min'); hi = region.get('bbox_max')
    if region.get('origin') != 'runtime_hom' or not _typed_value(lo, 'float', 3) or not _typed_value(hi, 'float', 3) or any(a > b for a, b in zip(lo, hi)) or hi[0] <= lo[0] or hi[2] <= lo[2]:
        raise NativeParticleOceanGeometryDomainError('ACTUAL_OCEAN_SOURCE_XZ_BOUNDS_REQUIRED', 'source')
    size = [hi[0] - lo[0], hi[2] - lo[2]]
    center = [hi[0] / 2. + lo[0] / 2., hi[2] / 2. + lo[2] / 2.]
    if not _typed_value(size, 'float', 2) or not _typed_value(center, 'float', 2):
        raise NativeParticleOceanGeometryDomainError('ACTUAL_OCEAN_SOURCE_XZ_BOUNDS_REQUIRED', 'finite region')
    return size, center, _guard('source', '@geometry/0', region)


def _ocean_context(observations, foam):
    return dict(source=observations.get(('source','@ocean_source'),{}),
        surface=observations.get(('evaluate','@ocean_surface'),{}),
        spectrum=observations.get(('spectrum','@ocean_spectrum'),{}),
        native_emit=observations.get(('foam_emit','@ocean_emit'),{}),
        mask_stage=observations.get(('ocean_masks','@ocean_stage'),{}),foam=foam)


def _ocean_writes(pack,version,observations,foam):
    from . import native_ocean_mask_program as program
    raw=program.control_write_plan(pack,version,**_ocean_context(observations,foam))
    result=[]
    for original in raw:
        w=copy.deepcopy(original);w['ocean_write']=copy.deepcopy(original);w['frozen_readback_guards']=[]
        w.update(domain_id=pack,native_version=version)
        if w.get('value_kind')=='menu_label':
            fact=observations.get((w['role'],w['parm']),{})
            labels,tokens=fact.get('menu_labels',[]),fact.get('menu_tokens',[])
            if w['value'] not in labels or labels.index(w['value'])>=len(tokens):
                raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_INTERFACE_REQUIRED','ocean_masks/class Points')
            w['value']=tokens[labels.index(w['value'])]
        result.append(w)
    return result


def _geometry_deform_write(plan, native_write, observations):
    contract = control_contract(GEOMETRY, plan.version)['deformation']
    guards = [_guard(role, parm, observations[role, parm])
        for role, parm in contract['context_parms'] if parm != '@geometry_parameters']
    write = copy.deepcopy(native_write)
    write.update(public_control='deformation', domain_id=GEOMETRY, native_version=plan.version,
        value_kind='trusted_geometry_deform_program', geometry_deform_plan=plan,
        size=1, require_task_owned=True, frozen_readback_guards=guards)
    return write


def control_write_plan(pack, control, value, version, *, observations=None):
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeParticleOceanGeometryDomainError('UNKNOWN_NATIVE_CONTROL', str(control))
    c = contracts[control]
    if c['value_type'] == 'bool':
        if type(value) is not bool:
            raise NativeParticleOceanGeometryDomainError('INVALID_NATIVE_CONTROL_VALUE', str(control))
        # Keep the trusted public toggle a strict bool; it derives fixed VEX.
    else:
        value = _number(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')
    if c['native_status'] != 'mapped':
        raise NativeParticleOceanGeometryDomainError(c['blocker'], str(control))
    observations = observations or {}
    if pack == PARTICLES and (control == 'emission_variance'
            or control == 'birth_rate' and ('emission', '@emission_context') in observations):
        from . import native_particle_emission_host as emission
        context = observations.get(emission.CONTEXT, {})
        percentage = value if control == 'emission_variance' else context.get('percentage')
        write = emission.routed_write(percentage, observations,
            birth_rate_override=value if control == 'birth_rate' else None)
        validate_control_write_plan([write], observations)
        return [write]
    if pack == GEOMETRY and control == 'deformation':
        from . import native_geometry_controls_program as program
        context = observations.get((program.ROLE, '@geometry_context'))
        parameters = observations.get((program.ROLE, '@geometry_parameters'))
        plan = program.plan_control(version, value, context, parameters)
        native_write = program.validate_plan(plan, context, parameters)[0]
        validate_topology_readback(pack, version, observations)
        write = _geometry_deform_write(plan, native_write, observations)
        validate_control_write_plan([write], observations)
        return [write]
    if pack == PARTICLES and control == 'size_variance':
        from . import native_particle_size_program as program
        size = _runtime(observations, 'particle_size', 'singlevalue', 'float')['value']
        return program.routed_writes(program.plan_size_variance(value, version,
            observations=observations, staged=True, size_override=size))
    if (pack == PARTICLES and control == 'size' and ('particle_size', '@size_basis') in observations
            and _gate_matches(observations.get(('particle_size', 'valuetype'), {}), 'rand')):
        from . import native_particle_size_program as program
        percentage, _, _ = program.observed_percentage(version, observations)
        return program.routed_writes(program.plan_size_variance(percentage, version,
            observations=observations, size_override=value, staged=True))
    validate_topology_readback(pack, version, observations)
    if pack==SWARM and control in ('target_noise','noise_strength'):
        from . import native_swarm_controls as swarm
        frozen=swarm.basis(observations,version)
        if control=='target_noise':
            swarm.channel_value(observations,version)
            channels=observations['seek','@swarm_channels']
            write=_write('seek','goal',swarm.interpolate(swarm.schedule(frozen,value),channels['time']),size=3,
                value_kind='trusted_swarm_goal_channels',public_value=value,swarm_basis=copy.deepcopy(frozen),swarm_before=copy.deepcopy(channels),
                required_gates=copy.deepcopy(_SEEK_GATES),domain_id=pack,native_version=version,public_control=control)
            write['frozen_readback_guards']=[_guard(r,p,observations[r,p]) for r,p in c['context_parms'] if p!='@swarm_channels']
            validate_control_write_plan([write],observations)
            return [write]
    if pack==OCEAN and control=='foam':
        return _ocean_writes(pack,version,observations,value)
    if pack == GEOMETRY and control == 'density':
        basis = observations.get(('scatter', '@input_geometry/0'), {})
        if basis.get('origin') != 'runtime_hom' or type(basis.get('primitives')) is not int or basis['primitives'] < 1 or not isinstance(basis.get('primitive_types'), (list, tuple)) or not basis['primitive_types'] or set(basis['primitive_types']) != {'Polygon'}:
            raise NativeParticleOceanGeometryDomainError('ACTUAL_SCATTER_SURFACE_AREA_BASIS_REQUIRED', control)
    if pack == OCEAN and control in ('crest_threshold', 'foam_amount'):
        size, center, _ = _foam_region(observations)
        for parm, expected in [('size', size), ('t', center)]:
            if not _near(_runtime(observations, 'foam_emit', parm, 'float', 2)['value'], expected):
                raise NativeParticleOceanGeometryDomainError('ACTUAL_OCEAN_FOAM_REGION_REQUIRED', parm)
    guards = []
    for role, parm in c['context_parms']:
        if pack==SWARM and (role,parm)==('seek','goal') and ('seek','@swarm_channels') in observations:
            from . import native_swarm_controls as swarm
            swarm.channel_value(observations,version)
            guards += [_guard('seek',p,observations['seek',p]) for p in ('@swarm_basis','@swarm_channels')]
            continue
        if parm.startswith('@') and parm != '@trusted_axis':
            guards.append(_guard(role, parm, observations[(role, parm)]))
        elif not parm.startswith('@'):
            guards.append(_guard(role, parm, _runtime(observations, role, parm, 'float', 2 if role == 'foam_emit' else 3)))
    if pack == PARTICLES and control in ('speed', 'velocity_variance', 'force_strength'):
        axis, guard = _axis(observations); guards.append(guard)
        value = [value * (abs(v) if control == 'velocity_variance' else v) for v in axis]
    elif pack == GEOMETRY and control == 'rotation':
        current = _runtime(observations, 'instance_transform', 'r', 'float', 3)
        value = [current['value'][0], current['value'][1], value]
    write = _write(c['role'], c['aliases'][0], value, c['native_type'], size=c['size'])
    target = _runtime(observations, write['role'], write['parm'], write['native_type'], write['size'])
    guards.append(_guard(write['role'], write['parm'], target))
    for role, parm, _ in c['required_gates']:
        kind, size = _gate_spec(role, parm)
        guards.append(_guard(role, parm, _runtime(observations, role, parm, kind, size)))
    write.update(required_gates=copy.deepcopy(c['required_gates']), frozen_readback_guards=guards,
        invalidates_from=c['invalidates_from'], public_control=control, domain_id=pack, native_version=version)
    validate_control_write_plan([write], observations)
    return [write]


def candidate_write_plan(pack, controls, version, *, observations=None):
    _domain(pack, version)
    if not isinstance(controls, Mapping):
        raise NativeParticleOceanGeometryDomainError('INVALID_NATIVE_CONTROLS', 'mapping required')
    if pack == GEOMETRY and {'scatter_density', 'density'} <= set(controls):
        raise NativeParticleOceanGeometryDomainError('INCOMPATIBLE_SCATTER_GENERATION_CONTROLS', 'count and density require different actual modes')
    writes = []; seen = {}
    emission_controls = set()
    if pack == PARTICLES and 'emission_variance' in controls:
        from . import native_particle_emission_host as emission
        write = emission.routed_write(controls['emission_variance'], observations or {},
                                     birth_rate_override=controls.get('birth_rate'))
        validate_control_write_plan([write], observations or {})
        writes.append(write)
        seen[write['role'], write['parm']] = write
        emission_controls = {'emission_variance', 'birth_rate'}
    if pack == PARTICLES and 'size_variance' in controls:
        from . import native_particle_size_program as program
        observed_size = _runtime(observations or {}, 'particle_size', 'singlevalue', 'float')['value']
        plan = program.plan_size_variance(controls['size_variance'], version,
            observations=observations or {}, size_override=controls.get('size', observed_size), staged=True)
        writes.extend(program.routed_writes(plan))
        seen = {(write['role'], write['parm']): write for write in writes}
    for control, value in controls.items():
        if control in emission_controls:
            continue
        if pack == PARTICLES and 'size_variance' in controls and control in ('size', 'size_variance'):
            continue
        for w in control_write_plan(pack, control, value, version, observations=observations):
            key = (w['role'], w['parm'])
            if key in seen:
                prior = seen[key]
                if not _near(prior['value'], w['value']):
                    raise NativeParticleOceanGeometryDomainError('CONFLICTING_NATIVE_CONTROLS', '/'.join(key))
                for field in ('required_gates', 'frozen_readback_guards'):
                    for item in w[field]:
                        if item not in prior[field]: prior[field].append(copy.deepcopy(item))
            else:
                writes.append(w); seen[key] = w
    immutable_readback_guards(writes)
    return writes


def semantic_write_map(writes, controls):
    result = {}
    for write in writes:
        names = [write['public_control']] if write.get('public_control') in controls else []
        if write.get('value_kind') == 'trusted_particle_size_program':
            from . import native_particle_size_program as program
            plan = program.plan_from_routed_writes([write])
            if 'size' in controls and plan.size_override is not None:
                names.insert(0, 'size')
        if write.get('value_kind') == 'trusted_particle_emission_expression' and 'birth_rate' in controls:
            names.insert(0, 'birth_rate')
        if not names:
            raise NativeParticleOceanGeometryDomainError('NATIVE_SEMANTIC_WRITE_MAPPING_REQUIRED', write['parm'])
        result[write['role'], write['parm']] = names
    return result


def _gate_matches(fact, expected):
    if fact.get('type') != 'ordinal': return _near(fact.get('value'), expected)
    tokens = fact.get('menu_tokens', ()); value = fact.get('value')
    if expected not in tokens: return False
    if isinstance(value, str): return value == expected
    if fact.get('menu_uses_token_value') is False:
        return type(value) is int and 0 <= value < len(tokens) and tokens[value] == expected
    return type(value) is int and str(value) == expected


def _menu_guard_matches(fact, guard):
    if 'menu_tokens' in guard:
        tokens = guard['menu_tokens']
        if not isinstance(tokens, (list, tuple)) or tuple(fact.get('menu_tokens', ())) != tuple(tokens):
            return False
    if 'menu_uses_token_value' in guard:
        expected = guard['menu_uses_token_value']
        if type(expected) is not bool or fact.get('menu_uses_token_value') is not expected:
            return False
    return True


def validate_readback_guards(writes, observations, *, after_mutation=False):
    written = {(w['role'], w['parm']) for w in writes}
    for w in writes:
        for guard in w.get('frozen_readback_guards', ()):
            key = (guard['role'], guard['parm'])
            if after_mutation and key in written: continue
            if after_mutation and key==('seek','@swarm_channels') and ('seek','goal') in written: continue
            if guard['parm'].startswith('@'):
                if observations.get(key) != guard['value']:
                    raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))
            else:
                fact = _runtime(observations, *key, guard['native_type'], guard['size'])
                if not _near(fact['value'], guard['value']) or not _menu_guard_matches(fact, guard):
                    raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))


def validate_control_write_plan(writes, observations, *, after_mutation=False):
    particle = [write for write in writes if write.get('public_control') == 'size_variance'
                or 'particle_size_plan' in write]
    if particle:
        from . import native_particle_size_program as program
        program.validate_control_write_plan(program.plan_from_routed_writes(particle), observations,
                                            after_mutation=after_mutation)
    ocean=[w['ocean_write'] for w in writes if 'ocean_write' in w]
    if ocean:
        from . import native_ocean_mask_program as program
        foam=ocean[-1]['trusted_program']['foam']
        program.validate_control_write_plan(ocean,observations,**_ocean_context(observations,foam))
    for w in writes:
        if w in particle:
            continue
        if w.get('value_kind') == 'trusted_particle_emission_expression':
            from . import native_particle_emission_host as emission
            emission.validate_write(w, observations, after_mutation=after_mutation)
            validate_topology_readback(PARTICLES, w['native_version'], observations)
            continue
        if ('geometry_deform_plan' in w or w.get('value_kind') == 'trusted_geometry_deform_program'
                or (w.get('domain_id') == GEOMETRY and w.get('public_control') == 'deformation')):
            from . import native_geometry_controls_program as program
            plan = w.get('geometry_deform_plan')
            native_write = program.validate_plan(plan,
                observations.get((program.ROLE, '@geometry_context')),
                observations.get((program.ROLE, '@geometry_parameters')),
                after_mutation=after_mutation)[0]
            validate_topology_readback(GEOMETRY, plan.version, observations)
            if w != _geometry_deform_write(plan, native_write, observations):
                raise NativeParticleOceanGeometryDomainError('GEOMETRY_PLAN_CHANGED', 'routed write differs from sealed plan or frozen context')
            continue
        validate_topology_readback(w['domain_id'], w['native_version'], observations)
        if not _typed_value(w['value'], w['native_type'], w.get('size', 1)):
            raise NativeParticleOceanGeometryDomainError('INVALID_NATIVE_WRITE_VALUE', w['role'] + '/' + w['parm'])
        if w.get('value_kind')=='trusted_swarm_goal_channels':
            from . import native_swarm_controls as swarm
            swarm.validate(w,observations,after=after_mutation)
            fact=observations[w['role'],w['parm']]
        else:
            fact = _runtime(observations, w['role'], w['parm'], w['native_type'], w.get('size', 1))
        if any(fact.get(flag) is not False for flag in ('locked', 'disabled', 'hidden')):
            raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_GATE_BLOCKED', w['role'] + '/' + w['parm'])
        for role, parm, expected in w.get('required_gates', ()):
            kind, size = _gate_spec(role, parm)
            gate = _runtime(observations, role, parm, kind, size)
            if not _gate_matches(gate, expected):
                raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_GATE_BLOCKED', role + '/' + parm)
    validate_readback_guards(writes, observations, after_mutation=after_mutation)


def validate_applied_readback(writes, observations):
    validate_control_write_plan(writes, observations, after_mutation=True)
    particle = [write for write in writes if write.get('public_control') == 'size_variance'
                or 'particle_size_plan' in write]
    if particle:
        from . import native_particle_size_program as program
        program.validate_geometry_consumption(program.plan_from_routed_writes(particle), observations)
    for w in writes:
        if w in particle:
            continue
        if w.get('value_kind') == 'trusted_geometry_deform_program': continue
        if w.get('value_kind') == 'trusted_particle_emission_expression': continue
        if w.get('value_kind')=='trusted_swarm_goal_channels': continue
        if not _gate_matches(observations[(w['role'], w['parm'])], w['value']):
            raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_READBACK_MISMATCH', w['role'] + '/' + w['parm'])


def immutable_readback_guards(writes):
    written = {(w['role'], w['parm']) for w in writes}; guards = {}
    for w in writes:
        for g in w.get('frozen_readback_guards', ()):
            key = (g['role'], g['parm'])
            if key in written: continue
            if key in guards and guards[key] != g:
                raise NativeParticleOceanGeometryDomainError('CONFLICTING_NATIVE_CONTEXT', '/'.join(key))
            guards[key] = copy.deepcopy(g)
    return list(guards.values())


def control_readback(pack, control, values, version, *, observations=None):
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeParticleOceanGeometryDomainError('UNKNOWN_NATIVE_CONTROL', str(control))
    c = contracts[control]
    if c['native_status'] != 'mapped':
        raise NativeParticleOceanGeometryDomainError(c['blocker'], str(control))
    if pack == PARTICLES and (control == 'emission_variance'
            or control == 'birth_rate' and ('emission', '@emission_context') in (observations or {})):
        from . import native_particle_emission_host as emission
        current = (observations or {}).get(emission.CONTEXT)
        if not isinstance(current, dict):
            raise NativeParticleOceanGeometryDomainError('PARTICLE_EMISSION_AUTHORITY_REQUIRED', 'current native emission registration required')
        write = emission.routed_write(current['percentage'], observations,
                                     birth_rate_override=current['birth_rate'])
        validate_control_write_plan([write], observations, after_mutation=True)
        return current['percentage'] if control == 'emission_variance' else current['birth_rate']
    if pack == GEOMETRY and control == 'deformation':
        from . import native_geometry_controls_program as program
        observations = observations or {}
        result = program.control_readback(version,
            observations.get((program.ROLE, '@geometry_context')),
            observations.get((program.ROLE, '@geometry_parameters')))
        validate_topology_readback(pack, version, observations)
        return result['value']
    if pack == PARTICLES and control == 'size_variance':
        from . import native_particle_size_program as program
        return program.collect_control_readback(version, observations or {}).observed_percentage
    if pack == PARTICLES and control == 'size' and ('particle_size', '@size_basis') in (observations or {}):
        from . import native_particle_size_program as program
        return program.observed_percentage(version, observations)[1]
    if pack==SWARM and control in ('target_noise','noise_strength'):
        from . import native_swarm_controls as swarm
        swarm.basis(observations or {},version)
        if control=='target_noise':
            value=swarm.channel_value(observations or {},version)
            writes=control_write_plan(pack,control,value,version,observations=observations)
            validate_applied_readback(writes,observations)
            return value
    if pack==OCEAN and control=='foam':
        from . import native_ocean_mask_program as program
        snippet=values.get(('ocean_masks','snippet'))
        if not isinstance(snippet,str):
            raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_READBACK_REQUIRED','actual ocean program')
        foam=not snippet.endswith('f@foam_mask = 0.0;\n')
        context=_ocean_context(observations or {},foam)
        writes=program.control_write_plan(pack,version,**context)
        program.validate_applied_readback(writes,observations or {},masked_geometry=(observations or {}).get(('ocean_masks','@ocean_geometry'),{}),**context)
        return foam
    try: native = values[c['role'], c['aliases'][0]]
    except KeyError as exc:
        raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_READBACK_REQUIRED', str(control)) from exc
    if not _typed_value(native, c['native_type'], c['size']):
        raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_READBACK_MISMATCH', str(control))
    if pack == PARTICLES and control in ('speed', 'velocity_variance', 'force_strength'):
        axis, _ = _axis(observations or {})
        if control == 'velocity_variance': axis = [abs(v) for v in axis]
        value = sum(v * a for v, a in zip(native, axis))
        if not _near(native, [value * a for a in axis]):
            raise NativeParticleOceanGeometryDomainError('NATIVE_CONTROL_READBACK_MISMATCH', str(control))
    elif pack == GEOMETRY and control == 'rotation': value = native[2]
    else: value = native
    value = _number(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')
    writes = control_write_plan(pack, control, value, version, observations=observations)
    validate_applied_readback(writes, observations or {})
    return value


native_control_value = control_readback


def trusted_initialization_plan(pack, version, *, fresh=False, phase='all', observations=None, scatter_mode='count', preserve_goal=False):
    _domain(pack, version)
    if fresh is not True:
        raise NativeParticleOceanGeometryDomainError('FRESH_TASK_OWNED_NODE_REQUIRED', str(pack))
    if phase not in ('all', 'allocate', 'gates', 'values'):
        raise NativeParticleOceanGeometryDomainError('UNKNOWN_INITIALIZATION_PHASE', str(phase))
    gates = []; values = []
    if pack in (PARTICLES, SWARM):
        gates = _BIRTH_GATES + _VELOCITY_GATES + _LIFE_GATES + [('emission', 'doid', 1)] + _attribute_gates('particle_size', 'const')
        gates += _DRAG_GATES + _FORCE_GATES + _CLUSTER_GATES if pack == PARTICLES else _FLOCK_GATES + _SEEK_GATES + _SWARM_NOISE_GATES
        values = [_write('particle_size', 'singlevalue', .05)]
        if pack == PARTICLES:
            values += [_write('force', 'force', [0., 0., 0.], size=3), _write('force', 'amp', 0.), _write('cluster', 'centralforce', 0.)]
        if pack == SWARM and not preserve_goal:
            values += [_write('noise_force','amp',0.)]
        if pack == SWARM and not preserve_goal and phase in ('all', 'values'):
            goal = _runtime(observations or {}, 'seek', 'goal', 'float', 3)
            values += [_write('emission', 'constantrate', 100.), _write('emission', 'life', 5.),
                _write('seek', 'goal', [goal['value'][0], 3., goal['value'][2]], size=3,
                    frozen_readback_guards=[_guard('seek', 'goal', goal)])]
    elif pack == OCEAN:
        gates = [('evaluate', 'deformgeo', 1), ('foam_emit', 'mode', 'emit'), ('foam_emit', 'region', 'grid'),
            ('foam_emit', 'domincusp', 1), ('foam_emit', 'dominvel', 0), ('foam_emit', 'dominheight', 0), ('foam_emit', 'dodisplace', 0)]
        if phase in ('all', 'values'):
            size, center, guard = _foam_region(observations or {})
            values = [_write('foam_emit', 'size', size, size=2, frozen_readback_guards=[guard]),
                _write('foam_emit', 't', center, size=2, frozen_readback_guards=[guard])]
    else:
        if scatter_mode not in ('count', 'density'):
            raise NativeParticleOceanGeometryDomainError('UNKNOWN_SCATTER_GENERATION_MODE', str(scatter_mode))
        gates = [('scatter', 'generateby', 'bydensity'), ('scatter', 'indepvoxel', 0),
            ('scatter', 'forcetotal', 1 if scatter_mode == 'count' else 0), ('scatter', 'usedensityattrib', 0),
            ('scatter', 'useareaattrib', 0), ('scatter', 'group', '')] + _attribute_gates('point_variation', 'rand')
    items = []; seen = set()
    for role, parm, value in gates:
        if (role, parm) in seen: continue
        kind, size = _gate_spec(role, parm)
        items.append(_write(role, parm, value, kind, size=size, phase='gates')); seen.add((role, parm))
    items += values
    for w in items:
        w.update(fresh_only=True, domain_id=pack, native_version=version)
    return copy.deepcopy([w for w in items if phase == 'all' or w['phase'] == phase])


def geometry_requirements(pack, version):
    _domain(pack, version)
    if pack in (PARTICLES, SWARM):
        return [dict(role='simulation', output=0, minimum_points=0, attributes_when_nonempty=True, point_attributes={'v': ('float', 3), 'id': ('integer', 1), 'age': ('float', 1)}),
            dict(role='particle_size', output=0, minimum_points=0, attributes_when_nonempty=True, point_attributes={'pscale': ('float', 1)}),
            dict(role='output', output=0, minimum_points=0)]
    if pack == OCEAN:
        return [dict(role='evaluate', output=0, minimum_points=1, minimum_primitives=1),
            dict(role='foam_emit', output=0, minimum_points=0, attributes_when_nonempty=True, point_attributes={'pscale': ('float', 1)}),
            dict(role='output', output=0, minimum_points=1, minimum_primitives=1)]
    return [dict(role='point_variation', output=0, minimum_points=0, attributes_when_nonempty=True, point_attributes={'pscale': ('float', 1)}), dict(role='output', output=0, minimum_points=0)]


def validate_geometry_readback(pack, version, observations):
    validate_topology_readback(pack, version, observations)
    for requirement in geometry_requirements(pack, version):
        key = (requirement['role'], '@geometry/' + str(requirement['output'])); fact = observations.get(key, {})
        if fact.get('origin') != 'runtime_hom':
            raise NativeParticleOceanGeometryDomainError('ACTUAL_NATIVE_GEOMETRY_REQUIRED', '/'.join(key))
        for kind in ('points', 'primitives'):
            count = fact.get(kind)
            if type(count) is not int or count < requirement.get('minimum_' + kind, 0):
                raise NativeParticleOceanGeometryDomainError('NATIVE_GEOMETRY_READBACK_MISMATCH', '/'.join(key) + '/' + kind)
        for name, (kind, size) in requirement.get('point_attributes', {}).items():
            if requirement.get('attributes_when_nonempty') and fact['points'] == 0: continue
            attribute = fact.get('point_attributes', {}).get(name, {})
            if attribute.get('type') != kind or type(attribute.get('size')) is not int or attribute['size'] != size:
                raise NativeParticleOceanGeometryDomainError('NATIVE_GEOMETRY_READBACK_MISMATCH', '/'.join(key) + '/' + name)


def overlay_host_pack(pack_id, pack: Mapping, version):
    result = copy.deepcopy(dict(pack)); contracts = control_contract(pack_id, version)
    if not isinstance(result.get('controls'), dict) or set(result['controls']) != set(contracts):
        raise NativeParticleOceanGeometryDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', str(pack_id))
    for name, c in result['controls'].items(): c.update(copy.deepcopy(contracts[name]))
    roles = {n['role'] for n in node_requirements(pack_id, version)}
    extras = [n for n in result.get('nodes', ()) if n.get('role') not in roles]
    result.update(nodes=node_requirements(pack_id, version) + extras, connections=connection_requirements(pack_id, version),
        native_domain_id=pack_id, native_plan_schema=SCHEMA, native_version=version, native_execution=False)
    return result


def overlay_core_pack_dict(pack: Mapping, version):
    result = copy.deepcopy(dict(pack)); contracts = control_contract(result['id'], version)
    if not isinstance(result.get('controls'), list) or len(result['controls']) != len(contracts) or {c.get('id') for c in result['controls']} != set(contracts):
        raise NativeParticleOceanGeometryDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', result['id'])
    nodes = [dict(n, types=n.get('type_candidates', []), required_parms=n.get('required_parameter_aliases', [])) for n in result.get('nodes', ())]
    host = overlay_host_pack(result['id'], dict(nodes=nodes, controls={c['id']: {} for c in result['controls']}), version)
    result['nodes'] = []
    for n in host['nodes']:
        item = copy.deepcopy(n); item['type_candidates'] = item.pop('types'); item['required_parameter_aliases'] = item.pop('required_parms'); result['nodes'].append(item)
    for c in result['controls']:
        item = copy.deepcopy(contracts[c['id']]); c['node_role'] = item.pop('role'); c['parameter_aliases'] = item.pop('aliases'); c.update(item)
    result.update(connections=host['connections'], native_domain_id=result['id'], native_plan_schema=SCHEMA, native_version=version, native_execution=False)
    return result
