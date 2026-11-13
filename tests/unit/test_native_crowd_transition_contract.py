"""Synthetic facts validate pure planning; no HOM or native operation is run."""
from dataclasses import replace
import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/houdini-bridge/src'))
from houdini_bridge import native_crowd_transition_contract as transition
from houdini_bridge.native_crowd_route_contract import HostIdentity, NodeFact, ParmFact, MenuFact, WireBinding


def payload(raw):
    return {'encoding': 'base64', 'data': base64.b64encode(raw).decode(),
            'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def snapshot(version):
    matrix = [float(i % 5 == 0) for i in range(16)]
    clips = []
    for name, offset, rate, start in (('walk_clip', 1., 17.25, 1.2), ('run_clip', 3., 53.5, -.4)):
        moved = list(matrix); moved[12] = offset
        clips.append({'name': name, 'external_reference': False, 'sample_count': 2,
            'sample_rate': rate, 'start_time': start, 'length_seconds': 1. / rate,
            'local_samples': [[matrix], [moved]], 'world_samples': [[matrix], [moved]], 'channels': []})
    content = {'point_count': 1, 'attributes': {}, 'agents': [{'native_type': 'PackedAgent',
        'rig': {'transform_names': ['body'], 'external_reference': False, 'parents': [-1],
                'rest_local': [matrix], 'rest_world': [matrix]},
        'shape_library': {'external_reference': False, 'shapes': [{'name': 'synthetic-body', 'geometry': {
            'points': [{'number': i, 'position': position} for i, position in enumerate([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])],
            'polygons': [{'closed': True, 'point_indices': [0, 1, 2]}]}}]},
        'layers': [{'name': 'synthetic-layer', 'external_reference': False, 'bindings': [
            {'transform': 0, 'shape': 'synthetic-body', 'attached': True, 'deforming': False, 'bounds_scale': [1., 1., 1.]}]}],
        'current_layers': ['synthetic-layer'], 'clips': clips, 'current_clips': ['walk_clip'],
        'clip_times': [1.2], 'clip_weights': [1.0]}]}
    return {'schema': 'bridge.w5.synthetic_agent_snapshot/1.0', 'houdini_version': version,
        'content': content, 'content_sha256': transition._digest(content),
        'native_payloads': {'geometry_bgeo': payload(b'synthetic-native-byte-fixture'),
            'agents': [{'rig_json': '{"synthetic_rig":true}', 'shape_library_bgeo': payload(b'synthetic-library'),
                'shapes': [{'name': 'synthetic-body', 'bgeo': payload(b'synthetic-shape')}],
                'layers': [{'name': 'synthetic-layer', 'json': '{"synthetic_layer":true}'}],
                'clips': [{'name': c['name'], 'local_clip_binary': payload(c['name'].encode())} for c in clips]}]}}


def fixture(version, storage='index', route=False, layout='Obj'):
    identity = HostIdentity('synthetic-task', 'synthetic-resource', 'v1', 'synthetic-session', 'generation-1', 1)
    root = '/obj/synthetic_transition'; sop = root + '/sop'; dop = (sop if layout=='Sop' else root) + '/dop'
    parents = tuple(NodeFact(role, path, parent, layout if role=='dop_root' else 'Obj', kind, 'synthetic-parent-' + role, identity, 0, 0, True, version)
        for role, path, parent, kind in (('task_root', root, '/obj', 'subnet'), ('sop_root', sop, root, 'geo'), ('dop_root', dop, sop if layout=='Sop' else root, 'dopnet')))
    kinds = {'agent_definition': ('Sop', 'stash', 0), 'source': ('Sop', 'crowdsource::3.0', 2),
             'population': ('Dop', 'popsource::2.0', 1), 'source_state': ('Dop', 'crowdstate::3.0', 1),
             'target_state': ('Dop', 'crowdstate::3.0', 1), 'trigger': ('Dop', 'crowdtrigger::2.0', 1),
             'transition': ('Dop', 'crowdtransition::3.0', 4), 'states': ('Dop', 'merge', 8),
             'transitions': ('Dop', 'merge', 8), 'solver': ('Dop', 'crowdsolver::3.0', 4)}
    if route: kinds.update(route=('Dop', 'popsteerpath', 4), wander=('Dop', 'popsteerwander', 4))
    nodes = tuple(NodeFact(role, (sop if category == 'Sop' else dop) + '/' + role,
        sop if category == 'Sop' else dop, category, kind, 'synthetic-instance-' + role, identity, inputs, 1, True, version)
        for role, (category, kind, inputs) in kinds.items())
    paths = {n.role: n.path for n in nodes}; parms = []
    def add(role, name, kind, ui, value, menu=None):
        parms.append(ParmFact(role, name, kind, ui, 1, value, True, False, kind, True, paths[role], identity, menu))
    def menu(role, name, items, token):
        binding = MenuFact(tuple(items), storage)
        value = next(i for i, item in enumerate(items) if item[0] == token) if storage == 'index' else token
        add(role, name, 'int' if storage == 'index' else 'string', 'ordinal', value, binding)
    for role, name, clip in (('source_state', 'walk', 'walk_clip'), ('target_state', 'run', 'run_clip')):
        add(role, 'statename', 'string', 'string', name); add(role, 'clipname', 'string', 'string', clip)
        add(role, 'uselocal', 'int', 'toggle', 0)
        menu(role, 'clipassignment', [('none', 'None'), ('single', 'Single Clip'), ('random', 'Random Distribution')], 'single')
        menu(role, 'rbdragdoll', [('active', 'Active'), ('static', 'Animated Static'), ('ignore', 'Ignore')], 'ignore')
    add('source', 'state', 'string', 'string', 'walk'); add('population', 'soppath', 'string', 'oppath', paths['source'])
    for name in ('useclipgraph', 'randomstart', 'uselocal', 'useoutclip'): add('transition', name, 'int', 'toggle', 1)
    for name, value in (('instate', 'walk'), ('outstate', 'run')): add('transition', name, 'string', 'string', value)
    add('transition', 'duration', 'float', 'float', 1.)
    add('transition', 'blend', 'ramp_float', 'ramp_flt', transition.RampFact(('Linear', 'Linear'), (0., 1.), (.2, .8), False, 'runtime_hom'))
    trigger_items = tuple((str(i), 'Current State Duration' if i == 10 else 'synthetic-menu-' + str(i)) for i in range(17))
    menu('trigger', 'type', trigger_items, '10')
    menu('trigger', 'statedurationcondition', [('0', 'Less Than'), ('1', 'Equal'), ('2', 'Greater Than')], '2')
    add('trigger', 'fuzzyoutput', 'int', 'toggle', 0); add('trigger', 'stateduration', 'float', 'float', .123)
    add('trigger', 'triggername', 'string', 'string', 'synthetic-stateduration')
    wires = [WireBinding('agent_definition', 0, 'source', 0), WireBinding('population', 0, 'solver', 1),
        WireBinding('target_state', 0, 'states', 1), WireBinding('transitions', 0, 'solver', 3)]
    if route:
        wires += [WireBinding('source_state', 0, 'wander', 0), WireBinding('wander', 0, 'states', 0),
                  WireBinding('states', 0, 'route', 0), WireBinding('route', 0, 'solver', 2)]
    else: wires += [WireBinding('source_state', 0, 'states', 0), WireBinding('states', 0, 'solver', 2)]
    geometry = transition.AgentGeometryFact(paths['agent_definition'], 0, identity, json.dumps(snapshot(version)), 'runtime_hom')
    return transition.TransitionContext(version, identity, root, sop, dop, parents, nodes, tuple(parms), geometry, tuple(wires), 0)


def change_parm(context, role, name, **changes):
    return replace(context, parameters=tuple(replace(p, **changes) if (p.role, p.name) == (role, name) else p for p in context.parameters))


def apply_pure_plan(context, plan):
    values = {(w.role, w.parm): w.value for w in plan.writes}
    def actual(p):
        if (p.role, p.name) not in values: return p
        value = values[p.role, p.name]
        if isinstance(value, transition.RampSpec): value = transition.RampFact(value.basis, value.keys, value.values, False, 'runtime_hom')
        return replace(p, value=value)
    return replace(context, connections=plan.connections, parameters=tuple(actual(p) for p in context.parameters))


class NativeCrowdTransitionContractTests(unittest.TestCase):
    def test_two_versions_duration_zero_and_positive_fixed_ramp_and_preserved_routes(self):
        for version in transition.VERSIONS:
            for storage in ('index', 'token'):
                with self.subTest(version=version, storage=storage):
                    ctx = fixture(version, storage, route=True)
                    init = transition.init_write_plan(ctx, animation_blend=0)
                    installed = apply_pure_plan(ctx, init)
                    self.assertEqual(transition.validate_readback(init, installed)['animation_blend'], 0.)
                    self.assertTrue(set(ctx.connections) <= set(init.connections))
                    self.assertIn(WireBinding('route', 0, 'solver', 2), init.connections)
                    self.assertIn(WireBinding('transition', 0, 'transitions', 0), init.connections)
                    for seconds in (0, .25, 10):
                        candidate = transition.candidate_write_plan(installed, seconds)
                        self.assertEqual([(w.parm, w.value) for w in candidate.writes], [('duration', float(seconds))])
                        readback = transition.validate_readback(candidate, apply_pure_plan(installed, candidate))
                        self.assertEqual(readback['unit'], 'seconds'); self.assertEqual(readback['native_execution'], 'NOT_RUN')
                    constructor = transition.ramp_constructor_plan(version)
                    self.assertEqual(constructor['call'], 'hou.Ramp')
                    self.assertEqual(constructor['args'][1:], ((0., 1.), (0., 1.)))
                    self.assertIn('finish_before_progress_division', transition.native_basis(version)['zero_seconds'])

    def test_actual_sop_dopnet_parent_layout_preserves_guards(self):
        for version in transition.VERSIONS:
            context=fixture(version,route=True,layout='Sop')
            plan=transition.init_write_plan(context,animation_blend=0.)
            self.assertEqual(transition.validate_readback(plan,apply_pure_plan(context,plan))['animation_blend'],0.)
            for mutation in ({'parent_path':context.task_root},{'category':'Obj'},{'path':context.dop_root+'/nested'},
                {'parent_path':'/obj/foreign'},{'identity':replace(context.identity,task_id='foreign')},
                {'version':'unsupported'},{'writable':False}):
                bad=replace(context,parents=tuple(replace(p,**mutation) if p.role=='dop_root' else p for p in context.parents))
                with self.subTest(version=version,mutation=mutation),self.assertRaises(transition.CrowdTransitionContractError):transition.validate_context(bad)

    def test_missing_clips_geometry_ownership_ports_and_compiled_facts_reject(self):
        ctx = fixture(transition.VERSIONS[0]); snap = json.loads(ctx.geometry.snapshot_json)
        missing = json.loads(ctx.geometry.snapshot_json); missing['content']['agents'][0]['clips'].pop()
        missing['content_sha256'] = transition._digest(missing['content'])
        shell = json.loads(ctx.geometry.snapshot_json)
        shell['content']['agents'][0]['shape_library']['shapes'][0].pop('geometry')
        shell['content_sha256'] = transition._digest(shell['content'])
        route_ctx = fixture(transition.VERSIONS[0], route=True)
        retained = tuple(w for w in route_ctx.connections if w.source_role not in
            ('source_state', 'target_state', 'wander', 'states'))
        dead_states = replace(route_ctx, connections=retained + (
            WireBinding('source_state', 0, 'wander', 0), WireBinding('target_state', 0, 'wander', 1),
            WireBinding('wander', 0, 'route', 0)))
        wrong_route_ports = replace(route_ctx, connections=retained + (
            WireBinding('source_state', 0, 'route', 1), WireBinding('target_state', 0, 'route', 2)))
        failures = [
            ('dead_states_merge', dead_states),
            ('states_to_route_geometry_ports', wrong_route_ports),
            ('missing_transition_input0', replace(ctx, nodes=tuple(replace(n, input_count=0)
                if n.role == 'transition' else n for n in ctx.nodes))),
            ('geometry_name_shell', replace(ctx, geometry=replace(ctx.geometry, snapshot_json=json.dumps(shell)))),
            ('duplicate_states', change_parm(ctx, 'target_state', 'statename', value='walk')),
            ('missing_clip', replace(ctx, geometry=replace(ctx.geometry, snapshot_json=json.dumps(missing)))),
            ('metadata_geometry', replace(ctx, geometry=replace(ctx.geometry, origin='metadata'))),
            ('foreign_owner', replace(ctx, geometry=replace(ctx.geometry, identity=replace(ctx.identity, task_id='other')))),
            ('wrong_geometry_port', replace(ctx, geometry=replace(ctx.geometry, output_port=1))),
            ('compiled_readonly', change_parm(ctx, 'transition', 'duration', compiled_writable=False)),
            ('driven_ramp', change_parm(ctx, 'transition', 'blend', driven=True)),
            ('wrong_states_input', replace(ctx, connections=tuple(replace(w, input_port=0) if w.target_role == 'solver' and w.input_port == 2 else w for w in ctx.connections))),
            ('occupied_transition_input', replace(ctx, connections=ctx.connections + (WireBinding('trigger', 0, 'transitions', 0),))),
            ('wrong_source_state', change_parm(ctx, 'source', 'state', value='run')),
            ('trigger_fuzzy', change_parm(ctx, 'trigger', 'fuzzyoutput', value=1)),
        ]
        for risk, invalid in failures:
            with self.subTest(risk=risk), self.assertRaises(transition.CrowdTransitionContractError):
                transition.init_write_plan(invalid, animation_blend=2)
        for seconds in (-1, 11, True, float('inf')):
            with self.subTest(seconds=seconds), self.assertRaises(transition.CrowdTransitionContractError):
                transition.init_write_plan(ctx, animation_blend=seconds)

    def test_native_ramp_gate_clip_timing_geometry_and_duration_readback_frozen(self):
        ctx = fixture(transition.VERSIONS[1]); installed = apply_pure_plan(ctx, transition.init_write_plan(ctx, animation_blend=2))
        plan = transition.candidate_write_plan(installed, 5); good = apply_pure_plan(installed, plan)
        for parm in ('useclipgraph', 'randomstart', 'uselocal', 'useoutclip'):
            with self.subTest(gate=parm), self.assertRaises(transition.CrowdTransitionContractError):
                transition.candidate_write_plan(change_parm(installed, 'transition', parm, value=1), 4)
        with self.assertRaisesRegex(transition.CrowdTransitionContractError, 'FIXED_LINEAR_TRANSITION_RAMP_REQUIRED'):
            transition.validate_readback(plan, change_parm(good, 'transition', 'blend',
                value=transition.RampFact(('Bezier', 'Bezier'), (0., 1.), (0., 1.), False, 'runtime_hom')))
        with self.assertRaisesRegex(transition.CrowdTransitionContractError, 'TRANSITION_NATIVE_READBACK_MISMATCH'):
            transition.validate_readback(plan, change_parm(good, 'transition', 'duration', value=4.))
        changed = json.loads(good.geometry.snapshot_json)
        changed['content']['agents'][0]['clips'][1]['sample_rate'] = 37.125
        changed['content_sha256'] = transition._digest(changed['content'])
        with self.assertRaisesRegex(transition.CrowdTransitionContractError, 'FROZEN_TRANSITION_CONTEXT_CHANGED'):
            transition.validate_readback(plan, replace(good, geometry=replace(good.geometry, snapshot_json=json.dumps(changed))))
        changed = json.loads(good.geometry.snapshot_json)
        changed['content']['agents'][0]['shape_library']['shapes'][0]['geometry']['points'][1]['position'][0] = 2.
        changed['content_sha256'] = transition._digest(changed['content'])
        with self.assertRaisesRegex(transition.CrowdTransitionContractError, 'FROZEN_TRANSITION_CONTEXT_CHANGED'):
            transition.validate_readback(plan, replace(good, geometry=replace(good.geometry, snapshot_json=json.dumps(changed))))

        for component in ('geometry_bgeo', 'clip', 'shape', 'rig', 'layer'):
            changed = json.loads(good.geometry.snapshot_json)
            native = changed['native_payloads']; agent = native['agents'][0]
            if component == 'geometry_bgeo': native['geometry_bgeo'] = payload(b'changed-native-geometry')
            elif component == 'clip': agent['clips'][1]['local_clip_binary'] = payload(b'changed-native-clip')
            elif component == 'shape': agent['shapes'][0]['bgeo'] = payload(b'changed-native-shape')
            elif component == 'rig': agent['rig_json'] = '{"changed_native_rig":true}'
            else: agent['layers'][0]['json'] = '{"changed_native_layer":true}'
            self.assertEqual(changed['content'], json.loads(good.geometry.snapshot_json)['content'])
            with self.subTest(payload=component), self.assertRaisesRegex(
                    transition.CrowdTransitionContractError, 'FROZEN_TRANSITION_CONTEXT_CHANGED'):
                transition.validate_readback(plan, replace(good, geometry=replace(
                    good.geometry, snapshot_json=json.dumps(changed))))
