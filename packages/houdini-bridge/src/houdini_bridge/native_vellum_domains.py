"""Pure Vellum plans for the existing trusted host construction/transaction path.

No HOM calls, cooking, node creation or operation state lives here. The fixed
cloth source program is derived only from guarded actual host observations. Actual menus, ownership, topology, geometry and readback remain host gates.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import math
import re
from typing import Any, Mapping

VERSIONS = ('21.0.631', '22.0.429')
CLOTH = 'vellum_cloth_v1'
SOFT_GRAINS = 'vellum_softbody_grains_v1'
SCHEMA = 'bridge.native-vellum-domains/1'
STIFFNESS_CONTRACT = 'native_constraint_stiffness_times_ten_to_exponent/1'
GRAIN_BOND_CONTRACT = 'grain_neighbour_glue_radius_twice_diameter/1'


class NativeVellumDomainError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _domain(pack, version, branch):
    if version not in (*VERSIONS, *PREPARATION_VERSIONS):
        raise NativeVellumDomainError('UNSUPPORTED_NATIVE_VERSION', str(version))
    if pack == CLOTH and branch == 'cloth':
        return
    if pack == SOFT_GRAINS and branch in ('softbody', 'grains'):
        return
    raise NativeVellumDomainError('EXPLICIT_VELLUM_BRANCH_REQUIRED', str(pack) + '/' + str(branch))


def _numeric(value, lo, hi, label, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi or (integer and type(value) is not int):
        raise NativeVellumDomainError('INVALID_NATIVE_CONTROL_VALUE', label)
    return int(value) if integer else float(value)


def _control(role, parm, lo, hi, kind='float', gates=(), unit='native scalar'):
    return {'role': role, 'aliases': [parm] if parm else [], 'minimum': lo, 'maximum': hi,
            'value_type': kind, 'application': 'houdini', 'invalidates_from': 'generation_simulation',
            'required_gates': list(gates), 'unit': unit, 'native_status': 'mapped'}


@versioned_controls
def control_contract(pack: str, version: str, branch: str) -> dict:
    _domain(pack, version, branch)
    solver = {
        'damping': _control('solver', 'veldamping', 0, 100, unit='native direct velocity damping'),
        'substeps': _control('solver', 'substeps', 1, 100, 'int', unit='substeps per frame'),
        'constraint_iterations': _control('solver', 'niter', 1, 10000, 'int', unit='constraint iterations per substep'),
    }
    mode = 'cloth' if branch == 'cloth' else 'tetstretch' if branch == 'softbody' else 'glue'
    stiffness_gates = [('constraints', 'constrainttype', mode), ('constraints', 'stretchstiffnessscalemode', 'none')]
    if branch == 'softbody':
        stiffness_gates.extend([('constraints', 'preservevol', 1), ('constraints', 'linear', 'normarap')])
    stiffness = _control('constraints', 'stretchstiffness', 0, 1e12, gates=stiffness_gates,
                         unit='effective native constraint stiffness; not a material Young modulus')
    stiffness.update(semantic_contract=STIFFNESS_CONTRACT, native_multiplier_parm='stretchstiffnessexp',
                     forward='native=effective/(10**actual_exponent)', inverse='effective=native*(10**actual_exponent)',
                     existing_exponent_policy='read and freeze actual token-value exponent; never normalize existing nodes')
    if branch == 'cloth':
        bend = copy.deepcopy(stiffness); bend['aliases'] = ['bendstiffness']; bend['native_multiplier_parm'] = 'bendstiffnessexp'
        bend['required_gates'] = [('constraints', 'constrainttype', 'cloth'), ('constraints', 'bendtype', 'angle'), ('constraints', 'bendstiffnessscalemode', 'none')]
        thickness = _control('constraints', 'thickness', 0, 100, gates=[('constraints', 'constrainttype', 'cloth'), ('constraints', 'dothickness', 'on')], unit='native collision thickness in scene units')
        thickness['invalidates_from']='source_layout_control'
        wrinkle = _control('cloth_wrinkle', 'snippet', 0, 100, unit='scene-unit wavelength; 0 restores upstream flat surface')
        wrinkle.update(semantic_contract='fixed_cloth_normal_wave_from_actual_source_and_half_native_thickness/1',invalidates_from='source_layout_control',context_parms=[('cloth_wrinkle','class'),('cloth_wrinkle','group'),('cloth_wrinkle','vex_precision'),('source','@cloth_source'),('constraints','@cloth_thickness'),('cloth_wrinkle','@cloth_stage'),('cloth_wrinkle','@cloth_geometry')])
        return {'stretch_stiffness': stiffness, 'bend_stiffness': bend, **solver,
                'thickness': thickness, 'collision_thickness': copy.deepcopy(thickness), 'wrinkle_scale': wrinkle}
    cluster = copy.deepcopy(stiffness); cluster.update(role='cluster_constraints')
    cluster['required_gates'] = [('cluster_constraints', 'constrainttype', 'shapematch'), ('cluster_constraints', 'piecemode', 'attribute'),
                                 ('cluster_constraints', 'pieceattrib', 'cluster'), ('cluster_constraints', 'stretchstiffnessscalemode', 'none'),
                                 ('cluster_points', 'buildclusters', 1), ('cluster_points', 'attrib_name', 'cluster'), ('cluster_points', 'cluster_output', 'clusterpoints')]
    friction = _control('grain_source' if branch == 'grains' else 'solver', 'friction' if branch == 'grains' else 'static_threshold', 0, 10,
        gates=[('solver', 'enablecollisions', 1), ('solver', 'friction', 1)],
        unit='native per-point friction multiplier; solver static threshold is readback context' if branch == 'grains' else 'native static friction threshold, approximately tangent of sliding slope angle')
    if branch == 'grains':
        friction['required_gates'].append(('grain_source', 'dofriction', 1))
        friction['context_parms'] = [('solver', 'static_threshold'), ('solver', 'dynamic_scale')]
    grainsize = _control('grain_source', 'grainsize', .0001, 1000,
        gates=[('grain_source', 'createpoints', 1), ('grain_source', 'type', 'grain'), ('grain_source', 'method', 'grid'), ('constraints', 'constrainttype', 'glue')],
        unit='particle diameter in scene units; native point pscale=diameter/2')
    grainsize.update(semantic_contract=GRAIN_BOND_CONTRACT, targets=[('grain_source', 'grainsize'), ('constraints', 'glue_radius')],
                     forward='grainsize=diameter; glue search radius=2*diameter', inverse='diameter=grainsize; require radius=2*diameter', invalidates_from='source_layout_control')
    packing = _control('grain_source', 'packingdensity', 0, 100,
        gates=[('grain_source', 'createpoints', 1), ('grain_source', 'method', 'grid'), ('grain_source', 'type', 'grain')],
        unit='native Regular Grid packing density multiplier; not measured final packing fraction')
    packing['invalidates_from'] = 'source_layout_control'
    if branch == 'softbody':
        for c in (grainsize, packing):
            c.update(native_status='branch_required', blocker='GRAIN_SOURCE_CONTROL_REQUIRES_GRAINS_BRANCH')
    return {'stiffness': stiffness, 'constraint_stiffness': copy.deepcopy(stiffness), 'cluster_stiffness': cluster,
            'friction': friction, **solver, 'collision_passes': _control('solver', 'collisionsiter', 1, 1000, 'int',
              gates=[('solver', 'enablecollisions', 1)], unit='collision passes per solver substep'),
            'grain_size': grainsize, 'packing': packing}


def _write(role, parm, value, native_type='float', phase='values', **extra):
    return {'role': role, 'parm': parm, 'value': value, 'native_type': native_type, 'phase': phase,
            'require_writable': True, 'require_readback': True, **extra}


def _exponent(observations, role, parm):
    fact = observations.get((role, parm), {})
    value = fact.get('value')
    if fact.get('origin') != 'runtime_hom' or fact.get('type') != 'ordinal' or fact.get('size') != 1 or fact.get('menu_uses_token_value') is not True or fact.get('driven') is not False:
        raise NativeVellumDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED', role + '/' + parm)
    if type(value) is not int or not -10 <= value <= 10 or str(value) not in fact.get('menu_tokens', []):
        raise NativeVellumDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED', role + '/' + parm)
    return value


def _wrinkle_context(observations):
    return {'source':observations.get(('source','@cloth_source'),{}),
            'thickness':observations.get(('constraints','@cloth_thickness'),{}),
            'shape_stage':observations.get(('cloth_wrinkle','@cloth_stage'),{})}


def _wrinkle_writes(pack,value,version,observations):
    from . import native_cloth_wrinkle_program as program
    try:
        raw = program.control_write_plan(pack,value,version,**_wrinkle_context(observations))
    except ValueError as exc:
        raise NativeVellumDomainError(getattr(exc,'code','UNTRUSTED_CLOTH_SOURCE_PROGRAM'),str(exc)) from exc
    result=[]
    for original in raw:
        w=copy.deepcopy(original); w['cloth_write']=copy.deepcopy(original);w['frozen_readback_guards']=[]
        if w.get('value_kind') == 'menu_label':
            fact=observations.get((w['role'],w['parm']),{})
            labels,tokens=fact.get('menu_labels',[]),fact.get('menu_tokens',[])
            if w['value'] not in labels or labels.index(w['value']) >= len(tokens):
                raise NativeVellumDomainError('NATIVE_CONTROL_INTERFACE_REQUIRED','cloth_wrinkle/class Points')
            w['value']=tokens[labels.index(w['value'])]
        result.append(w)
    return result


def control_write_plan(pack, control, value, version, branch, *, observations=None):
    contracts = control_contract(pack, version, branch)
    if control not in contracts:
        raise NativeVellumDomainError('UNKNOWN_NATIVE_CONTROL', control)
    c = contracts[control]; value = _numeric(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')
    if c['native_status'] != 'mapped':
        raise NativeVellumDomainError(c['blocker'], control)
    observations = observations or {}; guards = []
    if control == 'wrinkle_scale':
        return _wrinkle_writes(pack,value,version,observations)
    if 'native_multiplier_parm' in c:
        exponent = _exponent(observations, c['role'], c['native_multiplier_parm'])
        value /= 10. ** exponent
        guards.append({'role': c['role'], 'parm': c['native_multiplier_parm'], 'value': exponent,
                       'native_type': 'ordinal', 'menu_uses_token_value': True})
    if control == 'grain_size':
        old = observations.get(('grain_source', 'grainsize'), {})
        radius = observations.get(('constraints', 'glue_radius'), {})
        if old.get('origin') != 'runtime_hom' or radius.get('origin') != 'runtime_hom' or not _near(radius.get('value'), 2 * _numeric(old.get('value'), .0001, 1000, 'old grainsize')):
            raise NativeVellumDomainError('GRAIN_BOND_SEARCH_CONTRACT_REQUIRED', control)
        writes = [_write('grain_source', 'grainsize', value), _write('constraints', 'glue_radius', 2 * value)]
        guards.extend([{'role': role, 'parm': parm, 'value': fact['value']} for role, parm, fact in (('grain_source', 'grainsize', old), ('constraints', 'glue_radius', radius))])
    else:
        if control == 'packing' and value == 0:
            raise NativeVellumDomainError('ZERO_PACKING_DENSITY_NOT_SOURCEABLE', control)
        writes = [_write(c['role'], c['aliases'][0], value, 'integer' if c['value_type'] == 'int' else 'float')]
    for role, parm in c.get('context_parms', ()):
        fact = observations.get((role, parm), {})
        if fact.get('origin') != 'runtime_hom' or fact.get('type') != 'float' or fact.get('size') != 1 or fact.get('driven') is not False:
            raise NativeVellumDomainError('ACTUAL_FRICTION_CONTEXT_REQUIRED', role + '/' + parm)
        context = _numeric(fact.get('value'), 0, 1e10, parm)
        guards.append({'role': role, 'parm': parm, 'value': context, 'native_type': 'float', 'require_undriven': True})
    for w in writes:
        w.update(required_gates=copy.deepcopy(c['required_gates']), frozen_readback_guards=copy.deepcopy(guards), invalidates_from=c['invalidates_from'])
    return writes


def candidate_write_plan(pack, controls, version, branch, *, observations=None):
    if 'wrinkle_scale' in controls and any(name in controls for name in ('thickness','collision_thickness')):
        raise NativeVellumDomainError('CLOTH_THICKNESS_TRANSACTION_REQUIRED','apply thickness, observe it, then apply wrinkle_scale')
    writes = []; seen = {}
    for name, value in controls.items():
        for w in control_write_plan(pack, name, value, version, branch, observations=observations):
            key = (w['role'], w['parm'])
            if key in seen and seen[key] != w['value']:
                raise NativeVellumDomainError('CONFLICTING_NATIVE_CONTROLS', '/'.join(key))
            if key not in seen:
                writes.append(w); seen[key] = w['value']
    return writes


def _node(role, typ, input_role=None, parms=()):
    return {'role': role, 'category': 'sop', 'types': [typ], 'input_role': input_role, 'required_parms': [[p] for p in parms]}


def node_requirements(pack, version, branch):
    _domain(pack, version, branch)
    nodes = [_node('source', 'grid' if branch == 'cloth' else 'sphere'),
             _node('collision_source', 'box', parms=('size',)), _node('collision_transform', 'xform', 'collision_source', ('t', 's'))]
    if branch == 'softbody':
        nodes.append(_node('tet_mesh', 'tetconform', 'source', ('usemaxtetscale', 'maxtetscale')))
    if branch == 'grains':
        nodes.append(_node('grain_source', 'vellumconstraints_grain', 'source', ('createpoints', 'method', 'type', 'grainsize', 'packingdensity', 'dofriction', 'friction')))
    if branch == 'cloth':
        nodes.append(_node('cloth_wrinkle','attribwrangle','source',('class','group','snippet','vex_precision')))
    nodes.append(_node('constraints', 'vellumconstraints', 'cloth_wrinkle' if branch == 'cloth' else 'tet_mesh' if branch == 'softbody' else 'grain_source', ('constrainttype', 'stretchstiffness', 'stretchstiffnessexp', 'stretchstiffnessscalemode')))
    if branch != 'cloth':
        nodes.extend([_node('cluster_points', 'clusterpoints', 'constraints', ('buildclusters', 'num_clusters', 'random_seed', 'attrib_name', 'cluster_output', 'num_controls', 'control_attrib#', 'control_weight#')),
                      _node('cluster_constraints', 'vellumconstraints', 'cluster_points', ('constrainttype', 'piecemode', 'pieceattrib', 'stretchstiffness', 'stretchstiffnessexp', 'stretchstiffnessscalemode'))])
    nodes.extend([_node('solver', 'vellumsolver', 'constraints' if branch == 'cloth' else 'cluster_constraints', ('substeps', 'niter', 'collisionsiter', 'veldamping', 'enablecollisions', 'friction', 'static_threshold', 'dynamic_scale')),
                  _node('output', 'null', 'solver')])
    by_role = {n['role']: n for n in nodes}
    for c in control_contract(pack, version, branch).values():
        if c['native_status'] != 'mapped':
            continue
        for role, parm in [(c['role'], p) for p in c['aliases']] + [(r, p) for r, p, _ in c['required_gates']]:
            if [parm] not in by_role[role]['required_parms']:
                by_role[role]['required_parms'].append([parm])
    if branch == 'grains':
        by_role['constraints']['required_parms'] += [[p] for p in ('glue_radius', 'glue_minradius', 'glue_numpt', 'glue_searchpref', 'glue_constraintsperpt', 'glue_detach_chance', 'glue_point_chance', 'glue_usecluster', 'piecemode')]
    return nodes


def connection_requirements(pack, version, branch):
    nodes = node_requirements(pack, version, branch)
    edges = [{'source_role': n['input_role'], 'source_output': 0, 'destination_role': n['role'], 'destination_input': 0} for n in nodes if n['input_role']]
    terminal = 'constraints' if branch == 'cloth' else 'cluster_constraints'
    edges.append({'source_role': terminal, 'source_output': 1, 'destination_role': 'solver', 'destination_input': 1})
    edges.append({'source_role': 'collision_transform', 'source_output': 0, 'destination_role': 'solver', 'destination_input': 2})
    if branch != 'cloth':
        edges.append({'source_role': 'constraints', 'source_output': 1, 'destination_role': 'cluster_constraints', 'destination_input': 1})
    if branch == 'grains':
        edges.append({'source_role': 'grain_source', 'source_output': 1, 'destination_role': 'constraints', 'destination_input': 1})
    return edges


def trusted_initialization_plan(pack, version, branch, *, grain_size=.1, packing=1., cluster_count=4, cluster_seed=0):
    _domain(pack, version, branch)
    grain_size = _numeric(grain_size, .0001, 1000, 'grain_size')
    packing = _numeric(packing, 0, 100, 'packing')
    if branch == 'grains' and packing == 0:
        raise NativeVellumDomainError('ZERO_PACKING_DENSITY_NOT_SOURCEABLE', 'packing')
    cluster_count = _numeric(cluster_count, 1, 100000, 'cluster_count', True)
    cluster_seed = _numeric(cluster_seed, 0, 2147483647, 'cluster_seed', True)
    mode = 'cloth' if branch == 'cloth' else 'tetstretch' if branch == 'softbody' else 'glue'
    writes = [_write('constraints', 'constrainttype', mode, 'ordinal', 'gates', value_kind='menu_token'),
              _write('constraints', 'stretchstiffnessexp', 0, 'ordinal', 'gates', value_kind='numeric_menu_token', menu_uses_token_value=True),
              _write('constraints', 'stretchstiffnessscalemode', 'none', 'ordinal', 'gates', value_kind='menu_token'),
              _write('solver', 'enablecollisions', 1, 'toggle', 'gates'), _write('solver', 'doselfcollisions', 1, 'toggle', 'gates'),
              _write('solver', 'friction', 1, 'toggle', 'gates'), _write('solver', 'selffriction', 1, 'toggle', 'gates')]
    if branch == 'cloth':
        writes.extend([_write('source','rows',17,'integer'),_write('source','cols',17,'integer'),
            _write('cloth_wrinkle','vex_precision','64','string'),_write('cloth_wrinkle','class','Points','ordinal',value_kind='menu_label'),
            _write('cloth_wrinkle','group','','string'),
            _write('cloth_wrinkle','snippet','vector bridge_source = point(0, "P", @ptnum);\n@P = bridge_source;\n','string')])
        writes.extend([_write('constraints', 'stretchtype', 'distance', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'bendtype', 'angle', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'bendstiffnessexp', 0, 'ordinal', 'gates', value_kind='numeric_menu_token', menu_uses_token_value=True),
                       _write('constraints', 'bendstiffnessscalemode', 'none', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'dothickness', 'on', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'thickness', .01)])
    elif branch == 'softbody':
        writes.extend([_write('tet_mesh', 'usemaxtetscale', 1, 'toggle', 'gates'),
                       _write('tet_mesh', 'maxtetscale', .1),
                       _write('constraints', 'linear', 'normarap', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'preservevol', 1, 'toggle', 'gates')])
    else:
        writes.extend([_write('grain_source', 'createpoints', 1, 'toggle', 'gates'),
                       _write('grain_source', 'method', 'grid', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('grain_source', 'type', 'grain', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('grain_source', 'dofriction', 1, 'toggle', 'gates'), _write('grain_source', 'friction', 1.),
                       _write('grain_source', 'grainsize', grain_size), _write('grain_source', 'packingdensity', packing),
                       _write('constraints', 'piecemode', 'connectivity', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'glue_usecluster', 0, 'toggle', 'gates'), _write('constraints', 'glue_radius', 2 * grain_size),
                       _write('constraints', 'glue_minradius', 0.), _write('constraints', 'glue_numpt', 12, 'integer'),
                       _write('constraints', 'glue_searchpref', 'nearest', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('constraints', 'glue_constraintsperpt', 6, 'integer'),
                       _write('constraints', 'glue_detach_chance', 0.), _write('constraints', 'glue_point_chance', 0.)])
    if branch != 'cloth':
        writes.extend([_write('cluster_points', 'num_controls', 1, 'multiparm', 'allocate'),
                       _write('cluster_points', 'buildclusters', 1, 'toggle', 'gates'),
                       _write('cluster_points', 'cluster_output', 'clusterpoints', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('cluster_points', 'attrib_name', 'cluster', 'string'),
                       _write('cluster_points', 'control_attrib1', 'P', 'string'), _write('cluster_points', 'control_weight1', 1.),
                       _write('cluster_points', 'num_clusters', cluster_count, 'integer'), _write('cluster_points', 'random_seed', cluster_seed, 'integer'),
                       _write('cluster_constraints', 'constrainttype', 'shapematch', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('cluster_constraints', 'piecemode', 'attribute', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('cluster_constraints', 'pieceattrib', 'cluster', 'string'),
                       _write('cluster_constraints', 'stretchstiffnessexp', 0, 'ordinal', 'gates', value_kind='numeric_menu_token', menu_uses_token_value=True),
                       _write('cluster_constraints', 'stretchstiffnessscalemode', 'none', 'ordinal', 'gates', value_kind='menu_token'),
                       _write('cluster_constraints', 'stretchstiffness', 1.)])
    return writes


def _near(a, b):
    return not isinstance(a, bool) and isinstance(a, (int, float)) and math.isfinite(a) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def control_readback(pack, control, values, version, branch, *, observations=None):
    c = control_contract(pack, version, branch).get(control)
    if c is None:
        raise NativeVellumDomainError('UNKNOWN_NATIVE_CONTROL', control)
    if c['native_status'] != 'mapped':
        raise NativeVellumDomainError(c['blocker'], control)
    value = values[(c['role'], c['aliases'][0])]
    if control == 'wrinkle_scale':
        from . import native_cloth_wrinkle_program as program
        if value == 'vector bridge_source = point(0, "P", @ptnum);\n@P = bridge_source;\n':
            wavelength=0.
        else:
            match=re.search(r'bridge_distance / ([0-9.eE+\-]+)\)\);\n$',value)
            if not match:raise NativeVellumDomainError('UNTRUSTED_CLOTH_SOURCE_PROGRAM','saved snippet is not the fixed wavelength formula')
            wavelength=_numeric(float(match.group(1)),0,100,control)
        raw=program.control_write_plan(pack,wavelength,version,**_wrinkle_context(observations or {}))
        program.validate_applied_readback(raw,observations or {},**_wrinkle_context(observations or {}),
            shaped_geometry=(observations or {}).get(('cloth_wrinkle','@cloth_geometry'),{}))
        return wavelength
    if 'native_multiplier_parm' in c:
        value = _numeric(value, 0, 1e30, control) * (10. ** _exponent(observations or {}, c['role'], c['native_multiplier_parm']))
    if control == 'grain_size' and not _near(values[('constraints', 'glue_radius')], 2 * value):
        raise NativeVellumDomainError('NATIVE_CONTROL_READBACK_MISMATCH', GRAIN_BOND_CONTRACT)
    return _numeric(value, c['minimum'], c['maximum'], control, c['value_type'] == 'int')


def _gate_matches(actual, expected):
    if actual.get('value') == expected:
        return True
    tokens = actual.get('menu_tokens', []); current = actual.get('value')
    index = tokens.index(current) if current in tokens else current if type(current) is int and not actual.get('menu_uses_token_value') else -1
    return 0 <= index < len(tokens) and tokens[index] == expected


def validate_control_write_plan(writes, observations):
    cloth=[w['cloth_write'] for w in writes if 'cloth_write' in w]
    if cloth:
        from . import native_cloth_wrinkle_program as program
        program.validate_control_write_plan(cloth,observations,**_wrinkle_context(observations))
    for write in writes:
        key = (write['role'], write['parm']); actual = observations.get(key, {})
        if actual.get('origin') != 'runtime_hom' or actual.get('type') != write['native_type'] or actual.get('size') != 1:
            raise NativeVellumDomainError('NATIVE_CONTROL_INTERFACE_REQUIRED', '/'.join(key))
        if any(actual.get(flag) is not False for flag in ('locked', 'disabled', 'hidden', 'driven')):
            raise NativeVellumDomainError('NATIVE_CONTROL_GATE_BLOCKED', '/'.join(key))
        for role, parm, value in write.get('required_gates', ()):
            gate = observations.get((role, parm), {})
            if gate.get('origin') != 'runtime_hom' or not _gate_matches(gate, value):
                raise NativeVellumDomainError('NATIVE_CONTROL_GATE_BLOCKED', role + '/' + parm)
        validate_readback_guards([write], observations)


def validate_readback_guards(writes, observations, *, after_mutation=False):
    """Run before mutation and after writes for immutable exponent/context guards.

    Guards also include the old grain-size joint values for preflight; after the
    write phase, only fields outside the write set remain immutable.
    """
    for w in writes:
        if w.get('trusted_program'):
            from . import native_cloth_wrinkle_program as program
            program.validate_source_program(w['trusted_program'],**_wrinkle_context(observations))
    written_keys = {(w['role'], w['parm']) for w in writes}
    for write in writes:
        for guard in write.get('frozen_readback_guards', ()):
            key = (guard['role'], guard['parm'])
            if after_mutation and key in written_keys:
                continue
            actual = observations.get(key, {})
            if actual.get('origin') != 'runtime_hom' or actual.get('value') != guard['value']:
                raise NativeVellumDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))
            if guard.get('require_undriven') and (actual.get('type') != guard.get('native_type') or actual.get('driven') is not False):
                raise NativeVellumDomainError('NATIVE_CONTROL_CONTEXT_CHANGED', '/'.join(key))
            if guard.get('menu_uses_token_value') and (actual.get('menu_uses_token_value') is not True or actual.get('type') != 'ordinal' or actual.get('driven') is not False):
                raise NativeVellumDomainError('ACTUAL_STIFFNESS_EXPONENT_REQUIRED', '/'.join(key))


def immutable_readback_guards(writes):
    keys = {(w['role'], w['parm']) for w in writes}; guards = {}
    for w in writes:
        for guard in w.get('frozen_readback_guards', ()):
            key = (guard['role'], guard['parm'])
            if key not in keys:
                guards[key] = copy.deepcopy(guard)
    return list(guards.values())


def overlay_host_pack(pack_id, pack: Mapping, version, branch):
    contracts = control_contract(pack_id, version, branch); result = copy.deepcopy(dict(pack))
    if not isinstance(result.get('controls'), dict) or set(result['controls']) != set(contracts):
        raise NativeVellumDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', pack_id)
    for name, control in result['controls'].items():
        control.update(copy.deepcopy(contracts[name]))
    core_roles = {n['role'] for n in node_requirements(pack_id, version, branch)}
    extras = [n for n in result.get('nodes', ()) if n.get('role') not in core_roles | {'source', 'constraints', 'solver', 'output', 'collision_source', 'collision_transform'}]
    if any(n.get('role') in core_roles for n in extras):
        raise NativeVellumDomainError('VELLUM_BRANCH_ALREADY_DECLARED', branch)
    result.update(nodes=node_requirements(pack_id, version, branch) + extras, connections=connection_requirements(pack_id, version, branch), native_version=version, native_branch=branch, native_plan_schema=SCHEMA)
    return result


def overlay_core_pack_dict(pack: Mapping, version, branch):
    result = copy.deepcopy(dict(pack)); contracts = control_contract(result['id'], version, branch)
    if not isinstance(result.get('controls'), list) or len(result['controls']) != len(contracts) or {c.get('id') for c in result['controls']} != set(contracts):
        raise NativeVellumDomainError('PUBLIC_CONTROL_CONTRACT_CHANGED', result['id'])
    nodes = []
    for node in result.get('nodes', ()):
        node = copy.deepcopy(node); node['types'] = node.pop('type_candidates', []); node['required_parms'] = node.pop('required_parameter_aliases', [])
        nodes.append(node)
    host = overlay_host_pack(result['id'], {'nodes': nodes, 'controls': {c['id']: {} for c in result['controls']}}, version, branch)
    result['nodes'] = []
    for n in host['nodes']:
        n = copy.deepcopy(n); n['type_candidates'] = n.pop('types'); n['required_parameter_aliases'] = n.pop('required_parms')
        result['nodes'].append(n)
    for c in result['controls']:
        item = copy.deepcopy(contracts[c['id']]); c['node_role'] = item.pop('role'); c['parameter_aliases'] = item.pop('aliases'); c.update(item)
    result.update(connections=host['connections'], native_version=version, native_branch=branch, native_plan_schema=SCHEMA)
    return result


def geometry_requirements(pack, version, branch):
    _domain(pack, version, branch)
    required = [{'role': 'source', 'output': 0, 'kind': 'polygon_surface' if branch == 'cloth' else 'closed_connected_polygon_surface', 'minimum_points': 3},
                {'role': 'collision_transform', 'output': 0, 'kind': 'collision_polygon_surface', 'minimum_points': 3},
                {'role': 'constraints', 'output': 1, 'kind': 'native_constraints', 'minimum_primitives': 1, 'stiffness_attribute_readback_required': True}]
    if branch == 'softbody':
        required.append({'role': 'tet_mesh', 'output': 0, 'kind': 'tetrahedral_solid', 'minimum_primitives': 1})
    if branch == 'grains':
        required.append({'role': 'grain_source', 'output': 0, 'kind': 'grain_points', 'minimum_points': 2,
                         'required_point_attributes': {'isgrain': 'integer', 'pscale': 'float', 'friction': 'float'}, 'pscale_relation': 'diameter/2'})
    if branch != 'cloth':
        required.extend([{'role': 'cluster_points', 'output': 0, 'kind': 'clustered_input_points', 'required_point_attributes': {'cluster': 'integer'},
                          'must_preserve_input_geometry': True, 'piece_membership_readback_required': True},
                         {'role': 'cluster_constraints', 'output': 1, 'kind': 'native_constraints', 'minimum_primitives': 1,
                          'must_preserve_incoming_constraints': True, 'shape_match_stiffness_readback_required': True}])
    return required
