"""Synthetic typed adapter facts test pure plans; native execution is NOT_RUN."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/houdini-bridge/src'))
from houdini_bridge import native_crowd_route_contract as route


def fixture(version, storage='index', layout='Obj'):
    identity = route.HostIdentity('synthetic-task', 'synthetic-resource', 'v1', 'synthetic-session', 'generation-1', 1)
    root = '/obj/synthetic_task'; sop = root + '/sop'; dop = (sop if layout=='Sop' else root) + '/dop'
    nodes = tuple(route.NodeFact(role, parent + '/' + role, parent, category, native_type,
        'synthetic-instance-' + role, identity, inputs, 1, True, version)
        for role, parent, category, native_type, inputs in (
            ('route_curve', sop, 'Sop', 'stash', 0), ('route', dop, 'Dop', 'popsteerpath', 4),
            ('state_stream', dop, 'Dop', 'merge', 4), ('solver', dop, 'Dop', 'crowdsolver::3.0', 4)))
    paths = {n.role: n.path for n in nodes}
    digest = route.curve_geometry_sha256(route.FIXED_CURVE_POINTS, (0, 1, 2))
    curve = route.CurveFact(paths['route_curve'], 0, route.FIXED_CURVE_POINTS, (0, 1, 2), False,
                            'Polygon', digest, identity, 1)
    menu_kind = 'int' if storage == 'index' else 'string'
    menus = {'output': (('0', 'Crowds steerforce'), ('1', 'POP force')),
             'pathsource': (('sop', 'SOP'), ('dopdata', 'DOP Data'), ('first', 'First Context Geometry')),
             'method': (('0', 'Curve Lookup'), ('1', 'Curve Point Walk'))}
    parms = []
    for name, kind, ui, value in (
        ('weight', 'float', 'float', .5), ('activate', 'float', 'float', 0.),
        ('uselocalforce', 'int', 'toggle', 1), ('soppath', 'string', 'oppath', ''),
        ('output', menu_kind, 'ordinal', 1 if storage == 'index' else '1'),
        ('pathsource', menu_kind, 'ordinal', 0 if storage == 'index' else 'sop'),
        ('method', menu_kind, 'ordinal', 0 if storage == 'index' else '0')):
        menu = route.MenuFact(menus[name], storage) if name in menus else None
        parms.append(route.ParmFact('route', name, kind, ui, 1, value, True, False, kind, True,
                                    paths['route'], identity, menu))
    parms.append(route.ParmFact('route_curve', 'stash', 'data', 'data', 1, digest, True, False,
                                'data', True, paths['route_curve'], identity))
    parents = tuple(route.NodeFact(role, path, parent, layout if role=='dop_root' else 'Obj', native_type,
        'synthetic-parent-' + role, identity, 0, 0, True, version)
        for role, path, parent, native_type in (('task_root', root, '/obj', 'subnet'),
            ('sop_root', sop, root, 'geo'), ('dop_root', dop, sop if layout=='Sop' else root, 'dopnet')))
    return route.RouteContext(version, identity, root, sop, dop, nodes, tuple(parms), curve,
                              (route.WireBinding('state_stream', 0, 'solver', 2),), parents)


def change_parm(context, name, **changes):
    return replace(context, parameters=tuple(replace(p, **changes) if p.role == 'route' and p.name == name
                                             else p for p in context.parameters))


def apply_pure_plan(context, plan):
    values = {(w.role, w.parm): w.value for w in plan.writes}
    return replace(context, connections=plan.connections,
        parameters=tuple(replace(p, value=values[p.role, p.name]) if (p.role, p.name) in values else p
                         for p in context.parameters))


class NativeCrowdRouteContractTests(unittest.TestCase):
    def test_two_versions_initialize_native_route_and_edit_relative_weight(self):
        for version in route.VERSIONS:
            for storage in ('index', 'token'):
                with self.subTest(version=version, storage=storage):
                    context = fixture(version, storage)
                    plan = route.init_write_plan(context, route_weight=35)
                    installed = apply_pure_plan(context, plan)
                    self.assertEqual(route.validate_readback(plan, installed)['route_weight'], 35.)
                    self.assertEqual(route.wire_plan(context), (
                        route.WireBinding('state_stream', 0, 'route', 0), route.WireBinding('route', 0, 'solver', 2)))
                    self.assertEqual(route.node_plan(version)[1]['types'], ['popsteerpath'])
                    self.assertEqual({w.parm: w.value for w in plan.writes}['soppath'], context.curve.node_path)
                    # An active force does not require activation to equal one.
                    installed = change_parm(installed, 'activate', value=.5)
                    for weight in (0, 72.5, 100):
                        candidate = route.candidate_write_plan(installed, weight)
                        self.assertEqual(len(candidate.writes), 1)
                        self.assertEqual(candidate.writes[0].parm, 'weight')
                        self.assertEqual(candidate.writes[0].value, float(weight))
                        self.assertEqual(route.validate_readback(candidate, apply_pure_plan(installed, candidate))['route_weight'], weight)

    def test_actual_sop_dopnet_parent_layout_preserves_guards(self):
        for version in route.VERSIONS:
            context=fixture(version,layout='Sop')
            plan=route.init_write_plan(context,route_weight=25.)
            self.assertEqual(route.validate_readback(plan,apply_pure_plan(context,plan))['route_weight'],25.)
            for mutation in ({'parent_path':context.task_root},{'category':'Obj'},{'path':context.dop_root+'/nested'},
                {'parent_path':'/obj/foreign'},{'identity':replace(context.identity,task_id='foreign')},
                {'version':'unsupported'},{'writable':False}):
                bad=replace(context,parents=tuple(replace(p,**mutation) if p.role=='dop_root' else p for p in context.parents))
                with self.subTest(version=version,mutation=mutation),self.assertRaises(route.CrowdRouteContractError):route.validate_context(bad)

    def test_geometry_context_role_ports_and_compiled_gate_fail_distinctly(self):
        context = fixture(route.VERSIONS[0])
        failures = [
            ('degenerate', replace(context, curve=replace(context.curve, points=((0., 0., 0.),) * 3)), 'ACTUAL_ROUTE_CURVE_REQUIRED'),
            ('wrong_digest', replace(context, curve=replace(context.curve, geometry_sha256='0' * 64)), 'ACTUAL_ROUTE_GEOMETRY_DIGEST_REQUIRED'),
            ('metadata_only', replace(context, curve=replace(context.curve, origin='metadata')), 'ACTUAL_ROUTE_GEOMETRY_PORT_REQUIRED'),
            ('wrong_geometry_port', replace(context, curve=replace(context.curve, output_port=1)), 'ACTUAL_ROUTE_GEOMETRY_PORT_REQUIRED'),
            ('wrong_parent', replace(context, parents=tuple(replace(n, native_type='geo') if n.role == 'dop_root' else n for n in context.parents)), 'ACTUAL_CONTEXT_PARENT_REQUIRED'),
            ('wrong_context', replace(context, nodes=tuple(replace(n, category='Sop') if n.role == 'route' else n for n in context.nodes)), 'ACTUAL_TASK_OWNED_NODE_REQUIRED'),
            ('wrong_owner', replace(context, curve=replace(context.curve, identity=replace(context.identity, task_id='another-task'))), 'ACTUAL_ROUTE_GEOMETRY_PORT_REQUIRED'),
            ('insufficient_ports', replace(context, nodes=tuple(replace(n, input_count=2) if n.role == 'solver' else n for n in context.nodes)), 'ACTUAL_NATIVE_PORTS_REQUIRED'),
            ('wrong_state_port', replace(context, connections=(route.WireBinding('state_stream', 0, 'solver', 1),)), 'ACTUAL_STATE_STREAM_BINDING_REQUIRED'),
            ('compiled_readonly', change_parm(context, 'weight', compiled_writable=False), 'COMPILED_WRITABLE_GATE_REQUIRED'),
            ('driven', change_parm(context, 'weight', driven=True), 'COMPILED_WRITABLE_GATE_REQUIRED'),
            ('borrowed_parm', change_parm(context, 'weight', node_path='/obj/user_node'), 'COMPILED_WRITABLE_GATE_REQUIRED'),
            ('wrong_menu', change_parm(context, 'pathsource', menu=route.MenuFact((('dopdata', 'DOP Data'),), 'index')), 'ACTUAL_MENU_BINDING_REQUIRED'),
        ]
        for label, invalid, code in failures:
            with self.subTest(risk=label), self.assertRaises(route.CrowdRouteContractError) as caught:
                route.init_write_plan(invalid, route_weight=35)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(route.CrowdRouteContractError): route.init_write_plan(replace(context, version='20.5.1'), route_weight=35)
        for invalid in (-1, 101, True, float('nan')):
            with self.subTest(weight=invalid), self.assertRaises(route.CrowdRouteContractError): route.init_write_plan(context, route_weight=invalid)

    def test_candidate_requires_consumed_route_and_freezes_readback(self):
        context = fixture(route.VERSIONS[1]); init = route.init_write_plan(context, route_weight=20)
        installed = apply_pure_plan(context, init); candidate = route.candidate_write_plan(installed, 80)
        good = apply_pure_plan(installed, candidate)
        for name, value in (('activate', 0.), ('output', 1), ('uselocalforce', 1),
                            ('pathsource', 1), ('soppath', '/obj/unowned/curve')):
            with self.subTest(gate=name), self.assertRaises(route.CrowdRouteContractError):
                route.candidate_write_plan(change_parm(installed, name, value=value), 30)
        with self.assertRaisesRegex(route.CrowdRouteContractError, 'ROUTE_NATIVE_READBACK_MISMATCH'):
            route.validate_readback(candidate, change_parm(good, 'weight', value=79.))
        with self.assertRaisesRegex(route.CrowdRouteContractError, 'FROZEN_ROUTE_CONTEXT_CHANGED'):
            route.validate_readback(candidate, change_parm(good, 'activate', value=.5))
        changed_points = ((0., 0., 0.), (4., 0., 0.), (8., 0., 4.))
        digest = route.curve_geometry_sha256(changed_points, (0, 1, 2))
        changed = replace(good, curve=replace(good.curve, points=changed_points, geometry_sha256=digest),
            parameters=tuple(replace(p, value=digest) if p.role == 'route_curve' else p for p in good.parameters))
        with self.assertRaisesRegex(route.CrowdRouteContractError, 'FROZEN_ROUTE_CONTEXT_CHANGED'):
            route.validate_readback(candidate, changed)
        identity = replace(good.identity, content_version='v2')
        changed = replace(good, identity=identity, nodes=tuple(replace(n, identity=identity) for n in good.nodes),
            parameters=tuple(replace(p, identity=identity) for p in good.parameters), curve=replace(good.curve, identity=identity),
            parents=tuple(replace(p, identity=identity) for p in good.parents))
        with self.assertRaisesRegex(route.CrowdRouteContractError, 'FROZEN_ROUTE_CONTEXT_CHANGED'):
            route.validate_readback(candidate, changed)

    def test_fixed_geometry_plan_is_native_construction_without_execution_claims(self):
        for version in route.VERSIONS:
            plan = route.fixed_curve_geometry_plan(version)
            self.assertEqual(plan['operations'][0]['call'], 'hou.Geometry')
            self.assertEqual(plan['operations'][1]['kwargs'], {'is_closed': False})
            self.assertEqual(plan['operations'][-1]['value_kind'], 'actual_hou_Geometry')
            self.assertTrue(plan['required_readback']['nondegenerate_open_polygon'])
            self.assertEqual(plan['basis']['native_execution'], 'NOT_RUN')
            self.assertFalse(hasattr(route, 'animation_blend'))
