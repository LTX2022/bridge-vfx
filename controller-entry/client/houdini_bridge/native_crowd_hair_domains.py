"""Pure trusted-host Crowd/Hair plans; native execution remains a host guard.

These plans contain no caller code, HOM construction, cooking or operation state.
Multiparm names, clip timing, stiffness exponents and geometry must be observed
from the task-owned native nodes before the existing transaction applies them.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import importlib
import inspect
import math
import re
from typing import Mapping

VERSIONS = ('21.0.631', '22.0.429')
CROWD = 'crowd_agents_v1'
HAIR = 'hair_fur_v1'
SCHEMA = 'bridge.native-crowd-hair-domains/1'
FIXTURE_CLIP = 'w5_loop'
HOM_HELPER_MODULE = 'houdini_bridge.crowd_helpers'
HOM_HOOKS = ('build_synthetic_agent_geometry', 'snapshot_agent_geometry',
             'validate_synthetic_snapshot', 'compare_agent_snapshots')


class NativeCrowdHairDomainError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _domain(pack, version):
    if version not in (*VERSIONS, *PREPARATION_VERSIONS):
        raise NativeCrowdHairDomainError('UNSUPPORTED_NATIVE_VERSION', str(version))
    if pack not in (CROWD, HAIR):
        raise NativeCrowdHairDomainError('UNKNOWN_NATIVE_DOMAIN', str(pack))


def _number(value, lo, hi, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not lo <= value <= hi:
        raise NativeCrowdHairDomainError('INVALID_NATIVE_CONTROL_VALUE', label)
    return float(value)


def _contract(role, parm, lo, hi, *, kind='float', size=1, gates=(), unit='native scalar', phase='generation_simulation', **extra):
    return dict(role=role, aliases=[parm] if parm else [], minimum=lo, maximum=hi,
                value_type='float', native_type=kind, size=size, application='houdini',
                invalidates_from=phase, required_gates=list(gates), unit=unit,
                native_status='mapped', **extra)


@versioned_controls
def control_contract(pack, version):
    _domain(pack, version)
    if pack == HAIR:
        density = _contract('guide_seed', 'density', 0, 10000000, gates=[('guide_seed', 'mode', 'surface'), ('guide_seed', 'forcecount', 0), ('guide_seed', 'densityoverride', 'none'), ('guides', 'tool', 'plant'), ('guides', 'plantmode', 'scatter'), ('hair', 'mode', 'surface'), ('hair', 'forcecount', 0), ('hair', 'densityoverride', 'none')], unit='native surface scatter density; physical area unit not captured', semantic_contract='joint_native_guide_and_hair_scatter_density/1', targets=[('guide_seed', 'density'), ('guides', 'density'), ('hair', 'density')])
        return {
            'guide_length': _contract('guide_length', 'setlength_length#', 0, 1000, gates=[('guide_seed', 'useguides', 0), ('guide_seed', 'unguidedlengthoverride', 'none')], unit='native curve length in scene units', semantic_contract='seed_and_actual_multiparm_guide_length/1',context_parms=[('guide_length','@multiparm/operations'),('guide_seed','unguidedlength')]),
            'guide_density': density,
            'bend_stiffness': _contract('constraints', 'bendstiffness', 0, 1e12, gates=[('constraints', 'constrainttype', 'hair'), ('constraints', 'bendstiffnessscalemode', 'none')], unit='effective native bend stiffness', multiplier_parm='bendstiffnessexp', semantic_contract='native_constraint_stiffness_times_ten_to_exponent/1'),
            'damping': _contract('solver', 'veldamping', 0, 100, unit='native direct velocity damping'),
            'clump': _contract('hair_clump', 'clumpsize', 0, 10, gates=[('hair_clump', 'clumpsizeoverride', 'none')], unit='native clump size in scene units', phase='shaping_control'),
            'collision_radius': _contract('constraints', 'thickness', 0, 100, gates=[('constraints', 'constrainttype', 'hair'), ('constraints', 'dothickness', 'on'), ('solver', 'enablecollisions', 1)], unit='native point pscale collision radius in scene units; requires actual pscale/radius convention', semantic_contract='native_pscale_radius/1', requires_context='collision_radius_convention',context_parms=[('constraints','@collision_radius_convention'),('constraints','@geometry/0')]),
            'clump_strength': _contract('hair_clump', 'tightness', 0, 100, gates=[('hair_clump', 'tightnessoverride', 'none')], unit='percentage of native clump tightness in the hard [0,1] interval', phase='shaping_control', semantic_contract='native_clump_tightness_percent/1', forward='native=value/100', inverse='value=native*100'),
            'wind_strength': _contract('solver', 'windspeed', -10000, 10000, gates=[('solver', 'dowind', 1)], unit='signed native wind gain along an observed trusted unit axis', targets=[('solver', 'wind'), ('solver', 'windspeed')], semantic_contract='signed_native_wind_axis_gain/1',context_parms=[('solver','@trusted_axis')]),
            'hair_width': _contract('hair', 'thickness', .00001, 100, gates=[('hair', 'outputthicknessattrib', 1), ('hair', 'thicknessoverride', 'none'), ('hair', 'thicknessattrib', 'width'), ('guides', 'widthoverride', 0)], unit='native hair thickness at the thickest point in scene units', phase='shaping_control', targets=[('guides', 'width'), ('hair', 'thickness')]),
        }
    state = [('state', 'rbdragdoll', 'ignore'), ('state', 'uselocal', 0)]
    wander = [('wander', 'output', '0'), ('wander', 'uselocalforce', 0), ('wander', 'uselocalnoise', 0)]
    avoidance = _contract('solver', 'forcescale', 0, 10, gates=[('solver', 'avoidance', 1)], unit='native avoidance force scale')
    variation = _contract('wander', 'amp', 0, 10, gates=wander, unit='native wander noise amplitude; not a measured trajectory variance')
    timing = _contract('state', 'globalclipoffset', -10000, 10000, gates=state + [('state', 'setinitialcliptime', 1), ('state', 'randomizecliptime', 0)], unit='seconds relative to the actual clip start time', semantic_contract='actual_clip_start_plus_offset_seconds/1',context_parms=[('agent_definition','@actual_clip')])
    blend = _contract('transition','duration',0,10,unit='seconds',semantic_contract='native_transition_duration_seconds/1',context_parms=[('transition','@crowd_transition')])
    route = _contract('route', 'weight', 0, 100, unit='native relative steering force factor',
        semantic_contract='native_relative_steering_force_weight/1',context_parms=[('route','@crowd_route')])
    return {
        'speed': _contract('source', 'initialvel', 0, 100, size=3, gates=[('solver', 'updateparticles', 1)], unit='initial velocity magnitude in native scene units per second along an observed trusted unit axis', targets=[('source', 'initialvel'), ('source', 'randominitvel')], semantic_contract='joint_initial_velocity_vector/1',context_parms=[('source','@trusted_axis')]),
        'avoidance': avoidance,
        'behavior_variation': variation,
        'animation_blend': blend,
        'speed_variance': _contract('source', 'randominitveloffset', 0, 100, size=3, gates=[('source', 'randomizeinitvel', 1), ('solver', 'updateparticles', 1)], unit='native per-direction initial velocity randomness along the trusted movement axis; not statistical variance',context_parms=[('source','@trusted_axis')]),
        'path_variance': dict(copy.deepcopy(variation), maximum=100),
        'clip_offset': timing,
        'avoidance_strength': dict(copy.deepcopy(avoidance), maximum=100),
        'behavior_mix': _contract('wander', 'weight', 0, 100, gates=wander, unit='native steering force priority weight'),
        'route_weight': route,
        'animation_variation': _contract('state', 'clipspeedvariance', 0, 100, gates=state + [('state', 'randomizeclipspeed', 1)], unit='percentage variation around the actual clip speed multiplier'),
        'timing_offset': copy.deepcopy(timing),
    }


def _write(role, parm, value, kind='float', size=1, phase='values', **extra):
    # log/direction describe the captured UI, while HOM exposes Float templates.
    native_kind = 'float' if kind in {'log','direction'} else kind
    return dict(role=role, parm=parm, value=value, native_type=native_kind, native_ui_type=kind, size=size, phase=phase,
                require_writable=True, require_readback=True, **extra)


def _runtime(observations, role, parm, kind, size=1):
    fact = observations.get((role, parm), {})
    if fact.get('origin') != 'runtime_hom' or fact.get('type') != kind or fact.get('size') != size or fact.get('driven') is not False:
        raise NativeCrowdHairDomainError('ACTUAL_NATIVE_CONTEXT_REQUIRED', role + '/' + parm)
    return fact


def _binding(observations, role, parent, templates):
    fact = observations.get((role, '@multiparm/' + parent), {})
    names = fact.get('bindings', {})
    if fact.get('origin') != 'runtime_hom' or fact.get('parent') != parent or fact.get('instance_count') != 1 or set(names) != set(templates):
        raise NativeCrowdHairDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + parent)
    indices = set()
    for template, name in names.items():
        m = re.fullmatch(re.escape(template).replace(r'\#', r'(\d+)'), name) if isinstance(name, str) else None
        if not m or not observations.get((role, name), {}).get('origin') == 'runtime_hom':
            raise NativeCrowdHairDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + template)
        indices.add(m.group(1))
    if len(indices) != 1:
        raise NativeCrowdHairDomainError('ACTUAL_MULTIPARM_BINDING_REQUIRED', role + '/' + parent)
    return names, {'role': role, 'parm': '@multiparm/' + parent, 'value': copy.deepcopy(fact)}


_LENGTH_TEMPLATES = ('op#', 'active#', 'setlength_mode#', 'setlength_method#', 'setlength_randomize#', 'setlength_length#', 'setlength_lengthoverride#', 'setlength_blend#')
_IMPORT_TEMPLATES = ('visible#', 'objname#', 'fieldname#')


def _axis(observations, role):
    fact = observations.get((role, '@trusted_axis'), {})
    vector = fact.get('value')
    if fact.get('origin') != 'trusted_host_runtime' or not isinstance(vector, (list, tuple)) or len(vector) != 3:
        raise NativeCrowdHairDomainError('ACTUAL_TRUSTED_UNIT_AXIS_REQUIRED', role)
    vector = [_number(v, -1, 1, role + ' axis') for v in vector]
    if not math.isclose(sum(v*v for v in vector), 1., abs_tol=1e-9):
        raise NativeCrowdHairDomainError('ACTUAL_TRUSTED_UNIT_AXIS_REQUIRED', role)
    return vector, {'role': role, 'parm': '@trusted_axis', 'value': copy.deepcopy(fact)}


def _clip_timing(observations):
    fact = observations.get(('agent_definition', '@actual_clip'), {})
    if fact.get('origin') != 'runtime_hom' or fact.get('clip_name') != FIXTURE_CLIP or fact.get('sample_count') != 3 or fact.get('native_type') != 'PackedAgent' or fact.get('api_helper') != HOM_HELPER_MODULE:
        raise NativeCrowdHairDomainError('ACTUAL_PACKED_AGENT_CLIP_TIMING_REQUIRED', FIXTURE_CLIP)
    start = _number(fact.get('start_time'), -1e30, 1e30, 'actual clip start')
    _number(fact.get('sample_rate'), 1e-30, 1e30, 'actual clip sample rate')
    _number(fact.get('length_seconds'), 1e-30, 1e30, 'actual clip length')
    if not re.fullmatch('[0-9a-f]{64}', str(fact.get('content_sha256', ''))):
        raise NativeCrowdHairDomainError('ACTUAL_PACKED_AGENT_CLIP_TIMING_REQUIRED', 'content hash')
    return start, {'role': 'agent_definition', 'parm': '@actual_clip', 'value': copy.deepcopy(fact)}


def _radius_geometry(observations, radius):
    radius = _number(radius,0,100,'actual collision radius')
    geometry = observations.get(('constraints','@geometry/0'),{})
    attribute = geometry.get('point_attributes',{}).get('pscale')
    values = geometry.get('point_attribute_values',{}).get('pscale')
    count = geometry.get('points')
    if (geometry.get('origin') != 'runtime_hom' or type(count) is not int or count < 0 or
            attribute != {'type':'float','size':1} or not isinstance(values,list) or len(values) != count or
            any(type(v) not in (int,float) or not math.isfinite(v) or not _near(v,radius) for v in values)):
        raise NativeCrowdHairDomainError('ACTUAL_POINT_COLLISION_RADIUS_REQUIRED','constraints/pscale')
    return radius


def control_write_plan(pack, control, value, version, *, observations=None):
    contracts = control_contract(pack, version)
    if control not in contracts:
        raise NativeCrowdHairDomainError('UNKNOWN_NATIVE_CONTROL', control)
    c = contracts[control]; value = _number(value, c['minimum'], c['maximum'], control)
    if c['native_status'] != 'mapped':
        raise NativeCrowdHairDomainError(c['blocker'], control)
    observations = observations or {}; guards = []; gates = copy.deepcopy(c['required_gates'])
    if pack == HAIR and control == 'guide_length':
        names, guard = _binding(observations, 'guide_length', 'operations', _LENGTH_TEMPLATES); guards.append(guard)
        gates += [('guide_length', names[t], v) for t, v in [('op#', 'setlength'), ('active#', 1), ('setlength_mode#', 'set'), ('setlength_method#', 'scale'), ('setlength_randomize#', 0), ('setlength_lengthoverride#', 'none'), ('setlength_blend#', 1.)]]
        writes = [_write('guide_seed', 'unguidedlength', value), _write('guide_length', names['setlength_length#'], value)]
    elif pack == HAIR and control == 'bend_stiffness':
        fact = _runtime(observations, 'constraints', 'bendstiffnessexp', 'ordinal')
        exp = fact.get('value')
        if type(exp) is not int or not -10 <= exp <= 10 or fact.get('menu_uses_token_value') is not True or str(exp) not in fact.get('menu_tokens', []):
            raise NativeCrowdHairDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED', control)
        guards.append({'role': 'constraints', 'parm': 'bendstiffnessexp', 'value': exp, 'native_type': 'ordinal', 'menu_uses_token_value': True})
        writes = [_write('constraints', 'bendstiffness', value/(10.**exp))]
    elif pack == HAIR and control in ('guide_density', 'hair_width'):
        writes = [_write(role, parm, value, 'log' if role == 'guides' else 'float') for role, parm in c['targets']]
    elif pack == HAIR and control == 'clump_strength':
        writes = [_write('hair_clump', 'tightness', value/100.)]
    elif pack == HAIR and control == 'collision_radius':
        fact = observations.get(('constraints', '@collision_radius_convention'), {})
        if fact.get('origin') != 'runtime_hom' or fact.get('contract') != 'pscale_is_collision_radius' or fact.get('verified_from') != 'actual_point_pscale_and_documented_native_radius' or fact.get('documentation_sha256') != '64f9bf4f360eb3d9f202c2174b8dd1962c70ef31debfda6108528966235a0a25':
            raise NativeCrowdHairDomainError('ACTUAL_COLLISION_RADIUS_CONVENTION_REQUIRED', control)
        guards.append({'role': 'constraints', 'parm': '@collision_radius_convention', 'value': copy.deepcopy(fact)})
        _radius_geometry(observations, observations.get(('constraints','thickness'),{}).get('value'))
        writes = [_write('constraints', 'thickness', value)]
    elif pack == HAIR and control == 'wind_strength':
        axis, guard = _axis(observations, 'solver'); guards.append(guard)
        writes = [_write('solver', 'wind', [v * (-1 if value < 0 else 1) for v in axis], 'direction', 3), _write('solver', 'windspeed', abs(value))]
    elif pack == CROWD and control == 'animation_blend':
        from .native_crowd_transition_contract import candidate_write_plan as transition_candidate
        fact=observations.get(('transition','@crowd_transition'),{})
        if fact.get('origin')!='runtime_hom' or 'context' not in fact:
            raise NativeCrowdHairDomainError('ACTUAL_TRANSITION_CONTEXT_REQUIRED',control)
        plan=transition_candidate(fact['context'],value)
        guards.append({'role':'transition','parm':'@crowd_transition','value':plan.frozen_guard_sha256})
        writes=[_write(w.role,w.parm,w.value) for w in plan.writes]
    elif pack == CROWD and control == 'route_weight':
        from .native_crowd_route_contract import candidate_write_plan as route_candidate
        fact = observations.get(('route','@crowd_route'),{})
        if fact.get('origin') != 'runtime_hom' or 'context' not in fact:
            raise NativeCrowdHairDomainError('ACTUAL_ROUTE_BEHAVIOR_AND_GEOMETRY_REQUIRED',control)
        plan = route_candidate(fact['context'],value)
        guards.append({'role':'route','parm':'@crowd_route','value':plan.frozen_guard_sha256})
        writes = [_write(w.role,w.parm,w.value) for w in plan.writes]
    elif pack == CROWD and control in ('speed', 'speed_variance'):
        axis, guard = _axis(observations, 'source'); guards.append(guard)
        writes = [_write('source', parm, [value * (abs(v) if control == 'speed_variance' else v) for v in axis], size=3) for parm in (['randominitveloffset'] if control == 'speed_variance' else ['initialvel', 'randominitvel'])]
    elif pack == CROWD and control in ('clip_offset', 'timing_offset'):
        start, guard = _clip_timing(observations); guards.append(guard)
        writes = [_write('state', 'globalclipoffset', start + value)]
    else:
        writes = [_write(c['role'], c['aliases'][0], value, c['native_type'], c['size'])]
    for w in writes:
        w.update(required_gates=copy.deepcopy(gates), frozen_readback_guards=copy.deepcopy(guards), invalidates_from=c['invalidates_from'], semantic_contract=c.get('semantic_contract'), public_control=control)
    return writes


def candidate_write_plan(pack, controls, version, *, observations=None):
    writes = []; seen = {}
    for name, value in controls.items():
        for w in control_write_plan(pack, name, value, version, observations=observations):
            key = (w['role'], w['parm'])
            if key in seen and seen[key]['value'] != w['value']:
                raise NativeCrowdHairDomainError('CONFLICTING_NATIVE_CONTROLS', '/'.join(key))
            if key not in seen:
                writes.append(w); seen[key] = w
            else:
                seen[key]['required_gates'] += [g for g in w['required_gates'] if g not in seen[key]['required_gates']]
                seen[key]['frozen_readback_guards'] += [g for g in w['frozen_readback_guards'] if g not in seen[key]['frozen_readback_guards']]
    return writes


def _node(role, typ, category='sop', parms=(), parent=None):
    return dict(role=role, category=category, types=[typ], required_parms=[[p] for p in parms], input_role=None, context_parent_role=parent)


def node_requirements(pack, version):
    _domain(pack, version)
    if pack == HAIR:
        nodes = [_node('source', 'sphere'), _node('guide_seed', 'hairgen::2.0', parms=('mode','forcecount','densityoverride','useguides','useinitdirattrib','unguidedlength','unguidedlengthoverride','unguidedsegments')),
                 _node('guides', 'guidegroom::2.0', parms=('tool','plantmode','density','width','widthoverride')),
                 _node('guide_length', 'guideprocess', parms=('operations',) + _LENGTH_TEMPLATES),
                 _node('hair_clump', 'hairclump::2.0', parms=('clumpsize','clumpsizeoverride','tightness','tightnessoverride')),
                 _node('constraints', 'vellumconstraints', parms=('constrainttype','computeorient','bendstiffnessexp','bendstiffnessscalemode','dothickness','pingroup','pintype','pinrotation','matchanimation')),
                 _node('collision_source', 'box', parms=('size',)), _node('collision_transform', 'xform', parms=('t','s')),
                 _node('solver', 'vellumsolver', parms=('enablecollisions','doselfcollisions','dowind')),
                 _node('hair', 'hairgen::2.0', parms=('mode','forcecount','densityoverride','useguides','outputthicknessattrib','thicknessattrib','thicknessoverride')),
                 _node('output', 'null')]
    else:
        nodes = [_node('route_curve','stash',parms=('stash',)), _node('agent_definition', 'stash'), _node('positions', 'grid'), _node('source', 'crowdsource::3.0', parms=('randomizeagent','randomizedefaultstate','randomizelayer','state','randomizeinitvel','initialvel','randominitvel','randominitveloffset')),
                 _node('dop_network', 'dopnet'), _node('import_geometry', 'dopimportfield', parms=('doppath','dopnode','fields','compression') + _IMPORT_TEMPLATES), _node('output', 'null')]
        from .native_crowd_transition_contract import node_plan
        nodes.extend(_node(n["role"],n["types"][0],n["category"].lower(),tuple(x[0] for x in n["required_parms"]),n["context_parent_role"]) for n in node_plan(version))
        nodes.append(_node('target_state','crowdstate::3.0','dop',('statename','clipname','clipassignment','rbdragdoll','uselocal'),'dop_network'))
        for role, typ, parms in [('route','popsteerpath',('output','activate','uselocalforce','pathsource','soppath','method','weight')), ('crowd_object','crowdobject',()), ('population','popsource::2.0',('emittype','showguide','usecontextgeo','soppath','impulseactiveate','jitterbirthtime')), ('state','crowdstate::3.0',('statename','rbdragdoll','clipassignment','clipname','cliptype','setinitialclipname','setinitialcliptime','randomizecliptime','randomclipoffset','retimetoparticle','clipspeedmultiplier','randomizeclipspeed','enablelooping','uselocal')), ('wander','popsteerwander',('output','type','state','uselocalforce','uselocalnoise')), ('solver','crowdsolver::3.0',('updateparticles','avoidance')), ('states','merge',()), ('transitions','merge',()), ('active_collisions','merge',()), ('static_collisions','merge',()), ('static_solver','staticsolver',()), ('multisolver','multisolver',()), ('bullet','bulletrbdsolver',('constraintsolvertype','randomize_order')), ('merge_solvers','merge',()), ('gravity','gravity',()), ('dop_output','output',())]:
            nodes.append(_node(role,typ,'dop',parms,'dop_network'))
    roles = {n['role']: n for n in nodes}
    for c in control_contract(pack,version).values():
        if c['native_status'] != 'mapped':
            continue
        entries = [(c['role'], p) for p in c['aliases']] + list(c.get('targets', ())) + [(r,p) for r,p,_ in c['required_gates']]
        for role, parm in entries:
            if [parm] not in roles[role]['required_parms']:
                roles[role]['required_parms'].append([parm])
    return nodes


def connection_requirements(pack, version):
    _domain(pack, version)
    if pack == HAIR:
        edges = [('source',0,'guide_seed',0),('guide_seed',0,'guides',0),('source',0,'guides',1),('guides',0,'guide_length',0),('source',0,'guide_length',1),('guide_length',0,'hair_clump',0),('source',0,'hair_clump',1),('hair_clump',0,'constraints',0),('constraints',0,'solver',0),('constraints',1,'solver',1),('collision_source',0,'collision_transform',0),('collision_transform',0,'solver',2),('source',0,'hair',0),('solver',0,'hair',1),('hair',0,'output',0)]
    else:
        edges = [('agent_definition',0,'source',0),('positions',0,'source',1),('population',0,'solver',1),('target_state',0,'states',1),('trigger',0,'transition',0),('transition',0,'transitions',0),('state',0,'wander',0),('wander',0,'states',0),('states',0,'route',0),('route',0,'solver',2),('transitions',0,'solver',3),('crowd_object',0,'active_collisions',0),('active_collisions',0,'multisolver',0),('solver',0,'multisolver',1),('bullet',0,'multisolver',2),('static_collisions',0,'static_solver',0),('static_solver',0,'merge_solvers',0),('multisolver',0,'merge_solvers',1),('merge_solvers',0,'gravity',0),('gravity',0,'dop_output',0),('import_geometry',0,'output',0)]
    return [dict(source_role=s,source_output=so,destination_role=d,destination_input=di) for s,so,d,di in edges]


def multiparm_allocation_plan(pack, version, *, fresh=False):
    _domain(pack,version)
    if fresh is not True:
        raise NativeCrowdHairDomainError('FRESH_TASK_OWNED_NODES_REQUIRED', pack)
    return ([_write('guide_length','operations',1,'multiparm',phase='allocate')] if pack == HAIR else
            [_write('import_geometry','fields',1,'multiparm',phase='allocate'),
             _write('import_geometry','compression',0,'multiparm',phase='allocate')])


def trusted_initialization_plan(pack, version, *, fresh=False, observations=None, root_fact=None, stage='all'):
    _domain(pack,version)
    if fresh is not True:
        raise NativeCrowdHairDomainError('FRESH_TASK_OWNED_NODES_REQUIRED', pack)
    if stage not in ('all','source','simulation') or (pack == CROWD and stage != 'all'):
        raise NativeCrowdHairDomainError('INVALID_INITIALIZATION_STAGE',stage)
    observations = observations or {}; writes = []
    def add(role,parm,value,kind='toggle',**extra):
        writes.append(_write(role,parm,value,kind,phase='gates',**extra))
    if pack == HAIR:
        names, binding = _binding(observations,'guide_length','operations',_LENGTH_TEMPLATES)
        for role in ('guide_seed','hair'):
            add(role,'mode','surface','ordinal'); add(role,'forcecount',0); add(role,'densityoverride','none','ordinal')
        add('guide_seed','useguides',0); add('guide_seed','useinitdirattrib',0); add('guide_seed','unguidedlengthoverride','none','ordinal'); add('guide_seed','unguidedsegments',8,'integer')
        add('guide_seed','unguidedlength',.1,'float'); add('hair','useguides',1)
        add('guides','tool','plant','ordinal',require_actual_menu_token=True); add('guides','plantmode','scatter','ordinal'); add('guides','widthoverride',0)
        for role in ('guide_seed','guides','hair'):
            add(role,'density',1000.,'log' if role == 'guides' else 'float')
        add('guides','width',.001,'log'); add('hair','thickness',.001,'float')
        for template,value,kind in [('op#','setlength','ordinal'),('active#',1,'toggle'),('setlength_mode#','set','ordinal'),('setlength_method#','scale','ordinal'),('setlength_randomize#',0,'toggle'),('setlength_lengthoverride#','none','ordinal'),('setlength_blend#',1.,'float'),('setlength_length#',.1,'float')]:
            add('guide_length',names[template],value,kind,frozen_readback_guards=[binding])
        for parm in ('clumpsizeoverride','tightnessoverride'):
            add('hair_clump',parm,'none','ordinal')
        add('constraints','constrainttype','hair','ordinal'); add('constraints','computeorient',1)
        add('constraints','bendstiffnessscalemode','none','ordinal'); add('constraints','bendstiffnessexp',0,'ordinal',menu_uses_token_value=True)
        add('constraints','dothickness','on','ordinal'); add('constraints','pintype','hard','ordinal'); add('constraints','pinrotation','same','ordinal'); add('constraints','matchanimation',0)
        if stage != 'source':
            root = root_binding_plan(root_fact or {}); add('constraints','pingroup',root['point_group'],'string',geometry_guard=root)
        for parm in ('enablecollisions','doselfcollisions','dowind'):
            add('solver',parm,1)
        add('hair','outputthicknessattrib',1); add('hair','thicknessattrib','width','string'); add('hair','thicknessoverride','none','ordinal')
    else:
        start, clip_guard = _clip_timing(observations)
        names, binding = _binding(observations,'import_geometry','fields',_IMPORT_TEMPLATES)
        identity = observations.get(('crowd_object','@node_identity'),{})
        if identity.get('origin') != 'runtime_hom' or identity.get('task_owned') is not True or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',str(identity.get('name',''))):
            raise NativeCrowdHairDomainError('ACTUAL_TASK_OWNED_CROWD_OBJECT_REQUIRED','object name')
        for parm in ('randomizeagent','randomizedefaultstate','randomizelayer'):
            add('source',parm,0)
        add('source','state',FIXTURE_CLIP,'string'); add('source','randomizeinitvel',1); add('source','randominitveloffset',[0.,0.,0.],'float',size=3)
        for parm,val in [('rbdragdoll','ignore'),('clipassignment','single'),('cliptype','0')]:
            add('state',parm,val,'ordinal')
        add('state','statename',FIXTURE_CLIP,'string'); add('state','clipname',FIXTURE_CLIP,'string')
        for parm,val in [('setinitialclipname',1),('setinitialcliptime',1),('randomizecliptime',1),('retimetoparticle',0),('randomizeclipspeed',1),('enablelooping',1),('uselocal',0)]:
            add('state',parm,val)
        add('state','randomclipoffset',0.,'float'); add('state','randomizecliptime',0)
        add('state','globalclipoffset',start,'float',frozen_readback_guards=[clip_guard]); add('state','clipspeedmultiplier',1.,'float'); add('state','clipspeedvariance',0.,'float')
        add('solver','updateparticles',1); add('solver','avoidance',1)
        for parm,val in [('output','0'),('type','1')]:
            add('wander',parm,val,'ordinal')
        add('wander','state',FIXTURE_CLIP,'string'); add('wander','uselocalforce',0); add('wander','uselocalnoise',0)
        add('population','usecontextgeo','none','ordinal'); add('population','emittype','allgeo','ordinal'); add('population','showguide',0); add('population','jitterbirthtime','none','ordinal')
        add('population','impulseactiveate','$SF==1','float',value_kind='fixed_vendor_hscript',trusted_expression_id='vendor_crowd_initial_frame_population/1')
        for template,value,kind in [('visible#','nochange','ordinal'),('objname#',identity['name'],'string'),('fieldname#','Geometry','string')]:
            add('import_geometry',names[template],value,kind,frozen_readback_guards=[binding])
        bullet_menu = observations.get(('bullet','constraintsolvertype'),{})
        if bullet_menu.get('origin') != 'runtime_hom' or bullet_menu.get('type') not in ('ordinal','string') or bullet_menu.get('size') != 1 or 'gaussseidelisland' not in bullet_menu.get('menu_tokens',[]):
            raise NativeCrowdHairDomainError('ACTUAL_VENDOR_BULLET_INTERFACE_REQUIRED','constraintsolvertype')
        _runtime(observations,'bullet','randomize_order','toggle')
        add('bullet','constraintsolvertype','gaussseidelisland',bullet_menu['type']); add('bullet','randomize_order',1)
    if pack == HAIR and stage != 'all':
        source_roles={'guide_seed','guides','guide_length','hair_clump'}
        writes=[w for w in writes if (w['role'] in source_roles) == (stage == 'source')]
    return writes


def role_reference_plan(pack, version):
    _domain(pack,version)
    return [] if pack == HAIR else [dict(role='population',parm='soppath',native_type='oppath',target_role='source',target_scope='task_owned_sop'), dict(role='import_geometry',parm='doppath',native_type='oppath',target_role='dop_network',target_scope='task_owned_dop'), dict(role='import_geometry',parm='dopnode',native_type='oppath',target_role='crowd_object',target_scope='task_owned_dop')]


def root_binding_plan(fact):
    if fact.get('origin') != 'runtime_hom' or fact.get('role') != 'hair_clump' or fact.get('output') != 0 or not re.fullmatch('[0-9a-f]{64}', str(fact.get('geometry_sha256',''))):
        raise NativeCrowdHairDomainError('ACTUAL_NONEMPTY_GUIDE_CURVES_REQUIRED', 'hair_clump')
    curves = fact.get('curves',[]); count = fact.get('point_count'); roots = []
    if type(count) is not int or count < 2 or not curves:
        raise NativeCrowdHairDomainError('ACTUAL_NONEMPTY_GUIDE_CURVES_REQUIRED', 'point/curve count')
    for curve in curves:
        points = curve.get('point_numbers',[])
        if curve.get('kind') != 'open_curve' or curve.get('closed') is not False or len(points) < 2 or len(set(points)) != len(points) or any(type(p) is not int or not 0 <= p < count for p in points):
            raise NativeCrowdHairDomainError('ACTUAL_NONEMPTY_GUIDE_CURVES_REQUIRED', 'actual ordered vertices')
        roots.append(points[0])
    return dict(role='hair_clump',output=0,geometry_sha256=fact['geometry_sha256'],point_group=' '.join(str(p) for p in sorted(set(roots))),root_point_numbers=sorted(set(roots)),curve_count=len(curves),pin_contract='each_actual_open_curve_first_vertex/1',require_saved_reopen_match=True)


def crowd_hom_hooks():
    try:
        module = importlib.import_module(HOM_HELPER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != HOM_HELPER_MODULE:
            raise
        raise NativeCrowdHairDomainError('CROWD_HOM_HELPER_NOT_INTEGRATED', HOM_HELPER_MODULE) from exc
    hooks = {name:getattr(module,name,None) for name in HOM_HOOKS}
    if any(not callable(hook) for hook in hooks.values()):
        raise NativeCrowdHairDomainError('CROWD_HOM_HELPER_INTERFACE_REQUIRED', HOM_HELPER_MODULE)
    try:
        inspect.signature(hooks['build_synthetic_agent_geometry']).bind(None)
        inspect.signature(hooks['snapshot_agent_geometry']).bind(None,None)
        inspect.signature(hooks['validate_synthetic_snapshot']).bind(None)
        inspect.signature(hooks['compare_agent_snapshots']).bind(None,None,tolerance=1e-8)
    except (TypeError,ValueError) as exc:
        raise NativeCrowdHairDomainError('CROWD_HOM_HELPER_INTERFACE_REQUIRED', HOM_HELPER_MODULE) from exc
    return hooks


def agent_recipe_plan(version):
    _domain(CROWD,version)
    return dict(helper_module=HOM_HELPER_MODULE, hooks=list(HOM_HOOKS), constructors=[dict(api='hou.AgentRig',args=['w5_root_body',['root','body'],[[1],[]]]),dict(api='hou.AgentShapeBinding',args=[1,'w5_body',False],kwargs={'bounds_scale':1.0}),dict(api='hou.AgentClip',args=[FIXTURE_CLIP,'actual_rig',3],kwargs={})],
                clip_samples='actual two-transform A/B/A local transforms', timing='read sampleRate/startTime/length/sampleCount/localTransforms from constructed native clip', subtype='geometry.createPacked("PackedAgent") must be isinstance(hou.Agent)', source_materialization='host must persist detached native geometry into task-owned SOP source; actual PackedAgent readback required', save_reopen='snapshot_agent_geometry then compare_agent_snapshots; no default frame rate or start time')


def validate_root_binding(guard, actual_fact):
    if root_binding_plan(actual_fact) != guard:
        raise NativeCrowdHairDomainError('GUIDE_ROOT_GEOMETRY_CHANGED','hair_clump')


def _near(actual, expected):
    if type(actual) in (float,int) and type(expected) in (float,int):
        return math.isfinite(actual) and math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-12)
    if isinstance(actual,(list,tuple)) and isinstance(expected,(list,tuple)):
        return len(actual)==len(expected) and all(_near(a,b) for a,b in zip(actual,expected))
    return actual==expected


def _gate_matches(actual, expected):
    current = actual.get('value')
    if _near(current, expected):
        return True
    tokens = actual.get('menu_tokens',[])
    return actual.get('type') == 'ordinal' and actual.get('menu_uses_token_value') is False and type(current) is int and 0 <= current < len(tokens) and tokens[current] == expected


def validate_readback_guards(writes, observations):
    for write in writes:
        for guard in write.get('frozen_readback_guards',()):
            actual = observations.get((guard['role'],guard['parm']),{})
            value = actual.get('frozen_guard_sha256') if guard['parm'] in ('@crowd_route','@crowd_transition') else actual if guard['parm'].startswith('@') else actual.get('value')
            if value != guard['value']:
                raise NativeCrowdHairDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', guard['role']+'/'+guard['parm'])
            if guard.get('menu_uses_token_value') and (actual.get('origin') != 'runtime_hom' or actual.get('menu_uses_token_value') is not True or actual.get('driven') is not False):
                raise NativeCrowdHairDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED', guard['parm'])


def validate_control_write_plan(writes, observations):
    for w in writes:
        fact = _runtime(observations,w['role'],w['parm'],w['native_type'],w.get('size',1))
        if any(fact.get(flag) is not False for flag in ('locked','disabled','hidden')):
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_GATE_BLOCKED',w['role']+'/'+w['parm'])
        for role,parm,value in w.get('required_gates',()):
            gate = observations.get((role,parm),{})
            if gate.get('origin') != 'runtime_hom' or gate.get('driven') is not False or not _gate_matches(gate,value):
                raise NativeCrowdHairDomainError('NATIVE_CONTROL_GATE_BLOCKED',role+'/'+parm)
        if w['native_type'] == 'ordinal':
            if w.get('menu_uses_token_value'):
                if fact.get('menu_uses_token_value') is not True or str(w['value']) not in fact.get('menu_tokens',[]):
                    raise NativeCrowdHairDomainError('NATIVE_MENU_TOKEN_REQUIRED',w['parm'])
            elif w['value'] not in fact.get('menu_tokens',[]):
                raise NativeCrowdHairDomainError('NATIVE_MENU_TOKEN_REQUIRED',w['parm'])
    validate_readback_guards(writes,observations)


def validate_applied_readback(writes, observations):
    validate_control_write_plan(writes,observations)
    for w in writes:
        if not _gate_matches(observations[(w['role'],w['parm'])],w['value']):
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_MISMATCH',w['role']+'/'+w['parm'])


def immutable_readback_guards(writes):
    guards={}
    for write in writes:
        for guard in write.get('frozen_readback_guards',()):
            key=(guard['role'],guard['parm'])
            if key in guards and guards[key] != guard:
                raise NativeCrowdHairDomainError('CONFLICTING_NATIVE_CONTEXT', '/'.join(key))
            guards[key]=copy.deepcopy(guard)
    return list(guards.values())


def native_control_value(pack, control, values, version, *, observations=None):
    """Normalize a saved/reopened native readback using its frozen context."""
    contracts = control_contract(pack,version)
    if control not in contracts:
        raise NativeCrowdHairDomainError('UNKNOWN_NATIVE_CONTROL',control)
    c=contracts[control]; observations=observations or {}
    if c['native_status']!='mapped':
        raise NativeCrowdHairDomainError(c['blocker'],control)
    def read(role,parm):
        try:
            return values[(role,parm)]
        except KeyError as exc:
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_REQUIRED',role+'/'+parm) from exc
    def joint(entries):
        result=read(*entries[0])
        if any(not _near(read(*entry),result) for entry in entries[1:]):
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_MISMATCH',control)
        return result
    if pack==HAIR and control=='guide_length':
        names,_=_binding(observations,'guide_length','operations',_LENGTH_TEMPLATES)
        value=joint([('guide_seed','unguidedlength'),('guide_length',names['setlength_length#'])])
    elif pack==HAIR and control=='bend_stiffness':
        fact=_runtime(observations,'constraints','bendstiffnessexp','ordinal');exp=fact.get('value')
        if type(exp) is not int or not -10<=exp<=10 or fact.get('menu_uses_token_value') is not True or str(exp) not in fact.get('menu_tokens',[]):
            raise NativeCrowdHairDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED',control)
        value=_number(read('constraints','bendstiffness'),0,1e30,control)*(10.**exp)
    elif pack==HAIR and control in ('guide_density','hair_width'):
        value=joint(c['targets'])
    elif pack==HAIR and control=='collision_radius':
        value=_radius_geometry(observations,read('constraints','thickness'))
    elif pack==HAIR and control=='clump_strength':
        value=_number(read('hair_clump','tightness'),0,1,control)*100.
    elif pack==HAIR and control=='wind_strength':
        axis,_=_axis(observations,'solver');direction=read('solver','wind');gain=_number(read('solver','windspeed'),0,10000,control)
        if _near(direction,axis):value=gain
        elif _near(direction,[-v for v in axis]):value=-gain
        else:raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_MISMATCH',control)
    elif pack==CROWD and control in ('speed','speed_variance'):
        axis,_=_axis(observations,'source')
        if control=='speed_variance':axis=[abs(v) for v in axis]
        vector=joint(c['targets']) if control=='speed' else read('source','randominitveloffset')
        if not isinstance(vector,(list,tuple)) or len(vector)!=3:
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_MISMATCH',control)
        vector=[_number(v,-1e30,1e30,control) for v in vector];value=sum(a*v for a,v in zip(axis,vector))
        if not _near(vector,[value*a for a in axis]):
            raise NativeCrowdHairDomainError('NATIVE_CONTROL_READBACK_MISMATCH',control)
    elif pack==CROWD and control in ('clip_offset','timing_offset'):
        start,_=_clip_timing(observations);value=_number(read('state','globalclipoffset'),-1e30,1e30,control)-start
    else:
        value=read(c['role'],c['aliases'][0])
    value=_number(value,c['minimum'],c['maximum'],control)
    control_write_plan(pack,control,value,version,observations=observations)
    return value


def overlay_host_pack(pack_id, pack: Mapping, version):
    contracts = control_contract(pack_id,version); result = copy.deepcopy(dict(pack))
    if not isinstance(result.get('controls'),dict) or set(result['controls']) != set(contracts):
        raise NativeCrowdHairDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED',pack_id)
    roles = {n['role'] for n in node_requirements(pack_id,version)}
    described = {n['role']:n for n in result.get('nodes',())}
    complete = roles.issubset(described) and all(described[n['role']].get('types') == n['types'] for n in node_requirements(pack_id,version))
    extras = [n for n in result.get('nodes',()) if n.get('role') not in (roles if complete else {'source','guides','solver','output'})]
    if any(n.get('role') in roles for n in extras):
        raise NativeCrowdHairDomainError('NATIVE_TOPOLOGY_ALREADY_DECLARED',pack_id)
    for name,c in result['controls'].items():
        c.update(copy.deepcopy(contracts[name]))
    result.update(nodes=node_requirements(pack_id,version)+extras,connections=connection_requirements(pack_id,version),native_plan_schema=SCHEMA,native_version=version,native_execution=False)
    return result


def overlay_core_pack_dict(pack: Mapping, version):
    result = copy.deepcopy(dict(pack)); contracts = control_contract(result['id'],version)
    if not isinstance(result.get('controls'),list) or len(result['controls']) != len(contracts) or {c.get('id') for c in result['controls']} != set(contracts):
        raise NativeCrowdHairDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED',result['id'])
    nodes=[]
    for node in result['nodes']:
        node=copy.deepcopy(node);node['types']=node.pop('type_candidates',[]);node['required_parms']=node.pop('required_parameter_aliases',[]);nodes.append(node)
    host = overlay_host_pack(result['id'],dict(nodes=nodes,controls={c['id']:{} for c in result['controls']}),version)
    result['nodes'] = []
    for n in host['nodes']:
        n = copy.deepcopy(n);n['type_candidates']=n.pop('types',[]);n['required_parameter_aliases']=n.pop('required_parms',[]);result['nodes'].append(n)
    for c in result['controls']:
        native=copy.deepcopy(contracts[c['id']]);c['node_role']=native.pop('role');c['parameter_aliases']=native.pop('aliases');c.update(native)
    result.update(connections=host['connections'],native_plan_schema=SCHEMA,native_version=version,native_execution=False)
    return result


def geometry_requirements(pack, version):
    _domain(pack,version)
    if pack == HAIR:
        return [dict(role='source',output=0,kind='polygon_skin_surface',minimum_primitives=1),dict(role='guide_seed',output=0,kind='nonempty_open_curves',minimum_primitives=1),dict(role='hair_clump',output=0,kind='nonempty_open_curves',root_first_vertex_readback=True),dict(role='constraints',output=1,kind='native_hair_and_root_pin_constraints',actual_pscale_and_effective_bend_stiffness_readback=True),dict(role='collision_transform',output=0,kind='collision_polygon_surface',minimum_primitives=1),dict(role='hair',output=0,kind='nonempty_open_curves',required_point_attributes={'width':'float'},must_preserve_root_skin_binding=True)]
    return [dict(role='agent_definition',output=0,kind='native_PackedAgent',helper=HOM_HELPER_MODULE,actual_clip_timing_and_samples=True),dict(role='source',output=0,kind='native_PackedAgent_population',required_point_attributes={'v':'float3','state':'string'}),dict(role='import_geometry',output=0,kind='native_PackedAgent_population',actual_definition_pose_clip_and_output_port_readback=True)]
