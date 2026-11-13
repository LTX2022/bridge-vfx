"""Software-only contract fixtures; no native scene or acceptance receipt is built."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path, PurePosixPath
import unittest

from houdini_bridge import native_particle_ocean_geometry_domains as plans
from houdini_bridge import native_geometry_controls_program as deform_program
from houdini_bridge.domain_packs import get_domain_pack
from test_native_geometry_controls_program import BottomHost

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = {
    plans.PARTICLES: {'birth_rate', 'life', 'speed', 'drag', 'size', 'emission_variance', 'life_variance', 'velocity_variance', 'force_noise', 'size_variance', 'force_strength', 'collision_radius', 'trail_length', 'motion_blur_scale', 'cluster_strength'},
    plans.SWARM: {'cohesion', 'separation', 'alignment', 'neighbor_radius', 'goal_attraction', 'target_noise', 'noise_strength'},
    plans.OCEAN: {'wave_scale', 'wind_speed', 'wind_direction', 'chop', 'foam', 'spectrum_amplitude', 'directional_spread', 'crest_threshold', 'foam_amount'},
    plans.GEOMETRY: {'scatter_density', 'seed', 'scale', 'variation', 'scatter_variance', 'scale_variance', 'rotation_variance', 'deformation', 'density', 'rotation'},
}
VALUES = {
    plans.PARTICLES: dict(birth_rate=40., life=4., speed=3., drag=.3, size=.07, life_variance=.25, velocity_variance=.7, force_noise=.9, force_strength=-2., cluster_strength=3.),
    plans.SWARM: dict(cohesion=3., separation=2., alignment=4., neighbor_radius=7., goal_attraction=6.),
    plans.OCEAN: dict(wave_scale=2., wind_speed=8., wind_direction=-33., chop=.6, spectrum_amplitude=2., crest_threshold=.4, foam_amount=3.),
    plans.GEOMETRY: dict(scatter_density=30, seed=17, scale=1.4, variation=.8, scale_variance=.8, rotation=72.),
}


def fact(value, kind='float', size=1, **extra):
    return dict(origin='runtime_hom', type=kind, size=size, value=copy.deepcopy(value),
        driven=False, locked=False, disabled=False, hidden=False, **extra)


def software_observations(pack, version, *, density_mode=False):
    """Explicit API observations for a parser/plan fixture, never real HOM evidence."""
    observations = {}; nodes = plans.node_requirements(pack, version)
    for n in nodes:
        path = '/obj/software_fixture/Sop/' + n['role']
        if n['category'] == 'dop': path = '/obj/software_fixture/Sop/simulation/' + n['role']
        observations[n['role'], '@node'] = dict(origin='runtime_hom', task_owned=True,
            task_root='/obj/software_fixture', path=path, type=n['types'][0], category=n['category'],
            context_parent_path=str(PurePosixPath(path).parent))
    for e in plans.connection_requirements(pack, version):
        source = observations[e['source_role'], '@node']
        observations[e['destination_role'], '@input/' + str(e['destination_input'])] = dict(
            origin='runtime_hom', task_owned=True, source_path=source['path'], source_type=source['type'],
            source_output=e['source_output'], destination_input=e['destination_input'])
    for name, c in plans.control_contract(pack, version).items():
        if c['native_status'] != 'mapped': continue
        value = 1 if c['native_type'] == 'integer' else 1.
        if c['size'] != 1: value = [0., 1., 0.] if name in ('speed', 'velocity_variance') else [11., -7., 13.]
        observations[c['role'], c['aliases'][0]] = fact(value, c['native_type'], c['size'])
        for role, parm, expected in c['required_gates']:
            kind, size = plans._gate_spec(role, parm)
            extra = dict(menu_tokens=[expected], menu_uses_token_value=False) if kind == 'ordinal' else {}
            observations[role, parm] = fact(expected, kind, size, **extra)
    if pack == plans.PARTICLES:
        observations['emission', '@trusted_axis'] = dict(origin='trusted_host_runtime', value=[.6, .8, 0.])
    if pack == plans.SWARM: observations['seek', 'goal'] = fact([2., 3., -4.], size=3)
    if pack == plans.OCEAN:
        observations['source', '@geometry/0'] = dict(origin='runtime_hom', points=4, primitives=1,
            bbox_min=[-2., 0., -3.], bbox_max=[4., 0., 5.])
        observations['foam_emit', 'size'] = fact([6., 8.], size=2)
        observations['foam_emit', 't'] = fact([1., 1.], size=2)
    if pack == plans.GEOMETRY:
        observations['scatter', 'forcetotal'] = fact(0 if density_mode else 1, 'toggle')
        observations['scatter', '@input_geometry/0'] = dict(origin='runtime_hom', points=4, primitives=1, primitive_types=['Polygon'])
    return observations


class NativeParticleOceanGeometryTests(unittest.TestCase):
    def test_all_public_controls_overlay_and_static_fields_for_both_versions(self):
        captures = json.loads((ROOT / 'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
        foam_paths = (ROOT.parent / 'integration/oceanfoam-static-audit.json',
                      ROOT / 'outputs/recovered-static/oceanfoam-static-audit.json')
        foam_path = next((path for path in foam_paths if path.is_file()), None)
        role_ops = {'ocean_masks':'Sop/attribwrangle','emission': 'Dop/popsource::2.0', 'drag': 'Dop/popdrag', 'force': 'Dop/popforce', 'cluster': 'Dop/popflock', 'flock': 'Dop/popflock', 'seek': 'Dop/popsteerseek', 'particle_size': 'Sop/attribadjustfloat', 'spectrum': 'Sop/oceanspectrum', 'point_variation': 'Sop/attribadjustfloat', 'scatter': 'Sop/scatter::2.0', 'instance_transform': 'Sop/xform'}
        role_ops['noise_force'] = 'Dop/popforce'
        role_ops['geometry_deform'] = 'Sop/attribwrangle'
        for version in plans.VERSIONS:
            operators = captures['versions'][version]['operators']
            operators = dict(operators)
            wrangle=json.loads((ROOT/'docs/native-basis/w2-wrangle-convolve-static.json').read_text(encoding='utf-8'))
            operators['Sop/attribwrangle']=wrangle['versions'][version]['operators']['Sop/attribwrangle']
            for pack in plans.DOMAIN_IDS:
                with self.subTest(version=version, pack=pack):
                    if pack == plans.OCEAN:
                        if foam_path is None:
                            self.skipTest('NOT_RUN: oceanfoam static audit unavailable: ' + '; '.join(map(str, foam_paths)))
                        foam = json.loads(foam_path.read_text(encoding='utf-8'))
                        operators['Sop/oceanfoam'] = next(o for o in foam['operators'] if o['version'] == version)
                    public = get_domain_pack(pack).to_dict(); original = copy.deepcopy(public)
                    for node in plans.node_requirements(pack,version):
                        if node['category']=='dop' and node['role'] in role_ops:
                            actual_fields=operators[role_ops[node['role']]]['parameters']
                            for aliases in node['required_parms']:
                                self.assertTrue(any(name in actual_fields for name in aliases),(version,node['role'],aliases))
                    contracts = plans.control_contract(pack, version)
                    self.assertEqual(PUBLIC[pack], set(contracts))
                    self.assertEqual(PUBLIC[pack], {c['id'] for c in public['controls']})
                    overlay = plans.overlay_core_pack_dict(public, version)
                    self.assertEqual(PUBLIC[pack], {c['id'] for c in overlay['controls']})
                    self.assertEqual(public, original)
                    self.assertFalse(overlay['native_execution'])
                    self.assertEqual(public['evidence'], overlay['evidence'])
                    host = plans.overlay_host_pack(pack, dict(controls={n: {} for n in PUBLIC[pack]}, nodes=[dict(role='render_camera')]), version)
                    self.assertIn(dict(role='render_camera'), host['nodes'])
                    for name, c in contracts.items():
                        if c['native_status'] != 'mapped':
                            self.assertEqual(c['aliases'], []); self.assertTrue(c['blocker']); continue
                        op = 'Sop/oceanfoam' if c['role'] == 'foam_emit' else role_ops[c['role']]
                        metadata = operators[op]['parameters'][c['aliases'][0]]
                        kind = 'float' if metadata['type'] in ('direction', 'vector', 'vector2') else metadata['type']
                        self.assertEqual((kind, metadata['size']), (c['native_type'], c['size']))
                    obs = software_observations(pack, version)
                    for w in plans.trusted_initialization_plan(pack, version, fresh=True, observations=obs):
                        self.assertTrue(w['fresh_only']); self.assertTrue(w['require_task_owned'])
                        self.assertTrue(plans._typed_value(w['value'], w['native_type'], w['size']))
                        if pack == plans.PARTICLES and (w['role'], w['parm']) in {('force', 'force'), ('force', 'amp'), ('cluster', 'centralforce')}:
                            self.assertEqual(w['value'], [0., 0., 0.] if w['parm'] == 'force' else 0.)
                        if w['role'] == 'scatter': continue  # Same-build SDK fields are verified separately.
                        op = 'Dop/popsolver::2.0' if w['role'] == 'solver' else 'Sop/oceanevaluate::2.0' if w['role'] == 'evaluate' else 'Sop/oceanfoam' if w['role'] == 'foam_emit' else role_ops[w['role']]
                        metadata = operators[op]['parameters'][w['parm']]
                        kind = 'float' if metadata['type'] in ('direction', 'vector', 'vector2') else metadata['type']
                        self.assertEqual((kind, metadata['size']), (w['native_type'], w['size']))
                        if kind == 'ordinal': self.assertIn(w['value'], metadata['menu_tokens'][::2])

    def test_table_driven_candidate_roundtrip_preserves_unrelated_values(self):
        for version in plans.VERSIONS:
            for pack in plans.DOMAIN_IDS:
                with self.subTest(version=version, pack=pack):
                    obs = software_observations(pack, version); before = copy.deepcopy(obs)
                    obs['unrelated', 'value'] = fact(819.)
                    writes = plans.candidate_write_plan(pack, VALUES[pack], version, observations=obs)
                    self.assertEqual({k: v for k, v in obs.items() if k != ('unrelated', 'value')}, before)
                    keys = [(w['role'], w['parm']) for w in writes]
                    self.assertEqual(len(keys), len(set(keys)))
                    applied = copy.deepcopy(obs)
                    for w in writes: applied[w['role'], w['parm']]['value'] = copy.deepcopy(w['value'])
                    plans.validate_applied_readback(writes, applied)
                    self.assertEqual(applied['unrelated', 'value']['value'], 819.)
                    values = {key: f['value'] for key, f in applied.items() if 'value' in f}
                    for name, value in VALUES[pack].items():
                        self.assertAlmostEqual(plans.control_readback(pack, name, values, version, observations=applied), value)
                    if pack == plans.PARTICLES:
                        for actual, expected in zip(applied['emission', 'vel']['value'], [1.8, 2.4, 0.]): self.assertAlmostEqual(actual, expected)
                        for actual, expected in zip(applied['emission', 'var']['value'], [.42, .56, 0.]): self.assertAlmostEqual(actual, expected)
                    if pack == plans.GEOMETRY: self.assertEqual(applied['instance_transform', 'r']['value'], [11., -7., 72.])

    def test_unknown_controls_inputs_and_blocked_controls_fail_closed(self):
        for version in plans.VERSIONS:
            for pack in plans.DOMAIN_IDS:
                for name, c in plans.control_contract(pack, version).items():
                    if c['native_status'] != 'blocked': continue
                    if pack == plans.OCEAN and name == 'directional_spread':
                        self.assertEqual(c['invalidates_from'], 'source_layout_control')
                        self.assertEqual(c['invalidates_from'],
                                         plans.control_contract(pack, version)['wind_direction']['invalidates_from'])
                    value = False if c['value_type'] == 'bool' else c['minimum']
                    with self.subTest(pack=pack, name=name), self.assertRaisesRegex(ValueError, c['blocker']):
                        plans.candidate_write_plan(pack, {name: value}, version, observations={})
                    with self.assertRaisesRegex(ValueError, c['blocker']):
                        plans.control_readback(pack, name, {}, version)
        for value in (True, float('nan'), float('inf'), -1., '4', 10 ** 1000):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_CONTROL_VALUE'):
                plans.candidate_write_plan(plans.PARTICLES, dict(birth_rate=value), plans.VERSIONS[0])
        for pack, version, controls, code in [('bad', plans.VERSIONS[0], {}, 'UNKNOWN_NATIVE_DOMAIN'), (plans.PARTICLES, '21.0.632', {}, 'UNSUPPORTED_NATIVE_VERSION'), (plans.PARTICLES, plans.VERSIONS[0], [], 'INVALID_NATIVE_CONTROLS'), (plans.PARTICLES, plans.VERSIONS[0], {'bad': 1}, 'UNKNOWN_NATIVE_CONTROL')]:
            with self.assertRaisesRegex(ValueError, code): plans.candidate_write_plan(pack, controls, version)

    def test_actual_types_drivers_gates_and_frozen_context_are_required(self):
        version = plans.VERSIONS[0]
        for field, replacement in [('origin', 'caller_json'), ('type', 'integer'), ('size', 3), ('driven', True), ('locked', True), ('hidden', True), ('disabled', True), ('value', True)]:
            obs = software_observations(plans.PARTICLES, version); obs['emission', 'constantrate'][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError): plans.candidate_write_plan(plans.PARTICLES, dict(birth_rate=12.), version, observations=obs)
        obs = software_observations(plans.PARTICLES, version)
        writes = plans.candidate_write_plan(plans.PARTICLES, dict(speed=3.), version, observations=obs)
        for key, field, replacement in [(('emission', '@trusted_axis'), 'value', [1., 0., 0.]), (('emission', 'initvel'), 'menu_uses_token_value', True), (('emission', '@node'), 'task_root', '/obj/other')]:
            bad = copy.deepcopy(obs); bad[key][field] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError): plans.validate_control_write_plan(writes, bad)
        bad = copy.deepcopy(writes); bad[0]['value'] = [float('nan'), 0., 0.]
        with self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_WRITE_VALUE'): plans.validate_control_write_plan(bad, obs)
        applied = copy.deepcopy(obs); applied['emission', 'vel']['value'] = [1.8, 2.4, 1.]
        with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'): plans.validate_applied_readback(writes, applied)
        with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'): plans.control_readback(plans.PARTICLES, 'speed', {('emission', 'vel'): [1.8, 2.4, 1.]}, version, observations=applied)
        gate = copy.deepcopy(obs); gate['emission', 'initvel']['value'] = 'use'
        with self.assertRaisesRegex(ValueError, 'GATE_BLOCKED'): plans.candidate_write_plan(plans.PARTICLES, dict(speed=3.), version, observations=gate)
        for control, target in [('force_noise', ('force', 'amp')), ('force_strength', ('force', 'force')), ('cluster_strength', ('cluster', 'centralforce'))]:
            for field, value in [('driven', True), ('locked', True), ('disabled', True)]:
                bad = copy.deepcopy(obs); bad[target][field] = value; before = copy.deepcopy(bad)
                with self.subTest(control=control, field=field), self.assertRaises(ValueError):
                    plans.candidate_write_plan(plans.PARTICLES, {control: 2.}, version, observations=bad)
                self.assertEqual(bad, before)
        bad = copy.deepcopy(obs); bad['cluster', 'interactionforce']['value'] = 1.
        with self.assertRaisesRegex(ValueError, 'GATE_BLOCKED'):
            plans.candidate_write_plan(plans.PARTICLES, dict(cluster_strength=2.), version, observations=bad)
        bad = copy.deepcopy(obs); bad['solver', 'externalforce']['value'] = 0
        with self.assertRaisesRegex(ValueError, 'GATE_BLOCKED'):
            plans.candidate_write_plan(plans.PARTICLES, dict(force_strength=2.), version, observations=bad)
        force = plans.candidate_write_plan(plans.PARTICLES, dict(force_strength=-2.), version, observations=obs)
        applied = copy.deepcopy(obs); applied['force', 'force']['value'] = [-1.2, -1.6, .1]
        with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'):
            plans.validate_applied_readback(force, applied)
        missing = copy.deepcopy(obs); missing['emission', '@trusted_axis']['origin'] = 'runtime_hom'
        with self.assertRaisesRegex(ValueError, 'TRUSTED_UNIT_AXIS'): plans.candidate_write_plan(plans.PARTICLES, dict(speed=3.), version, observations=missing)

    def test_lease_identity_type_context_and_actual_ports_reject_drift(self):
        version = plans.VERSIONS[0]
        changes = [(('emission', '@node'), 'task_owned', False), (('emission', '@node'), 'type', 'popforce'), (('emission', '@node'), 'category', 'sop'), (('emission', '@node'), 'context_parent_path', '/obj/software_fixture/Sop'), (('source', '@node'), 'path', '/obj/software_fixture/../other'), (('solver', '@input/2'), 'source_path', '/obj/other/drag'), (('solver', '@input/2'), 'source_type', 'popforce'), (('solver', '@input/2'), 'source_output', 1), (('solver', '@input/2'), 'destination_input', True), (('solver', '@input/2'), 'task_owned', False)]
        for key, field, replacement in changes:
            obs = software_observations(plans.PARTICLES, version)
            plans.validate_topology_readback(plans.PARTICLES, version, obs)
            obs[key][field] = replacement
            with self.subTest(key=key, field=field), self.assertRaises(ValueError): plans.validate_topology_readback(plans.PARTICLES, version, obs)

    def test_scatter_count_density_modes_and_alias_conflicts(self):
        for version in plans.VERSIONS:
            obs = software_observations(plans.GEOMETRY, version, density_mode=True)
            writes = plans.candidate_write_plan(plans.GEOMETRY, dict(density=2.5), version, observations=obs)
            self.assertEqual([(w['parm'], w['value']) for w in writes], [('densityscale', 2.5)])
            obs['scatter', 'densityscale']['value'] = 2.5
            self.assertEqual(plans.control_readback(plans.GEOMETRY, 'density', {('scatter', 'densityscale'): 2.5}, version, observations=obs), 2.5)
            for mutate in ('mode', 'geometry', 'mask'):
                bad = copy.deepcopy(obs)
                if mutate == 'mode': bad['scatter', 'forcetotal']['value'] = 1
                elif mutate == 'geometry': bad['scatter', '@input_geometry/0']['primitive_types'] = ['Volume']
                else: bad['scatter', 'usedensityattrib']['value'] = 1
                with self.subTest(mutate=mutate), self.assertRaises(ValueError): plans.candidate_write_plan(plans.GEOMETRY, dict(density=2.), version, observations=bad)
            with self.assertRaisesRegex(ValueError, 'INCOMPATIBLE_SCATTER'): plans.candidate_write_plan(plans.GEOMETRY, dict(density=2., scatter_density=10), version, observations=obs)
            count = software_observations(plans.GEOMETRY, version)
            with self.assertRaisesRegex(ValueError, 'CONFLICTING_NATIVE_CONTROLS'): plans.candidate_write_plan(plans.GEOMETRY, dict(variation=.5, scale_variance=.8), version, observations=count)
            ocean = software_observations(plans.OCEAN, version)
            with self.assertRaisesRegex(ValueError, 'CONFLICTING_NATIVE_CONTROLS'): plans.candidate_write_plan(plans.OCEAN, dict(wave_scale=1., spectrum_amplitude=2.), version, observations=ocean)
            with self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_CONTROL_VALUE'): plans.candidate_write_plan(plans.GEOMETRY, dict(scatter_density=1.5), version, observations=count)

    def test_initialization_phases_use_actual_goal_bounds_and_no_factory_defaults(self):
        for version in plans.VERSIONS:
            for pack in plans.DOMAIN_IDS:
                with self.assertRaisesRegex(ValueError, 'FRESH_TASK_OWNED'): plans.trusted_initialization_plan(pack, version)
                self.assertEqual(plans.trusted_initialization_plan(pack, version, fresh=True, phase='allocate'), [])
                gates = plans.trusted_initialization_plan(pack, version, fresh=True, phase='gates')
                self.assertTrue(gates); self.assertTrue(all(w['phase'] == 'gates' for w in gates))
                with self.assertRaisesRegex(ValueError, 'UNKNOWN_INITIALIZATION_PHASE'): plans.trusted_initialization_plan(pack, version, fresh=True, phase='bad')
            with self.assertRaisesRegex(ValueError, 'ACTUAL_NATIVE_CONTEXT_REQUIRED'): plans.trusted_initialization_plan(plans.SWARM, version, fresh=True, phase='values')
            swarm = software_observations(plans.SWARM, version); swarm['seek', 'goal']['value'] = [12., -6., 14.]
            goal = next(w for w in plans.trusted_initialization_plan(plans.SWARM, version, fresh=True, phase='values', observations=swarm) if w['parm'] == 'goal')
            self.assertEqual(goal['value'], [12., 3., 14.])
            with self.assertRaisesRegex(ValueError, 'ACTUAL_OCEAN_SOURCE_XZ_BOUNDS'): plans.trusted_initialization_plan(plans.OCEAN, version, fresh=True, phase='values')
            ocean = software_observations(plans.OCEAN, version)
            values = plans.trusted_initialization_plan(plans.OCEAN, version, fresh=True, phase='values', observations=ocean)
            self.assertEqual([(w['parm'], w['value']) for w in values], [('size', [6., 8.]), ('t', [1., 1.])])
            ocean['foam_emit', 'size']['value'] = [9., 8.]
            with self.assertRaisesRegex(ValueError, 'ACTUAL_OCEAN_FOAM_REGION'): plans.candidate_write_plan(plans.OCEAN, dict(foam_amount=3.), version, observations=ocean)
            ocean['source', '@geometry/0'].update(bbox_min=[-1e308, 0., -3.], bbox_max=[1e308, 0., 5.])
            with self.assertRaisesRegex(ValueError, 'ACTUAL_OCEAN_SOURCE_XZ_BOUNDS'): plans.trusted_initialization_plan(plans.OCEAN, version, fresh=True, phase='values', observations=ocean)
            for mode, expected in [('count', 1), ('density', 0)]:
                init = plans.trusted_initialization_plan(plans.GEOMETRY, version, fresh=True, scatter_mode=mode)
                self.assertEqual(next(w['value'] for w in init if w['parm'] == 'forcetotal'), expected)

    def test_actual_geometry_schema_and_public_contract_drift(self):
        version = plans.VERSIONS[0]
        for pack in plans.DOMAIN_IDS:
            obs = software_observations(pack, version)
            for req in plans.geometry_requirements(pack, version):
                obs[req['role'], '@geometry/' + str(req['output'])] = dict(origin='runtime_hom',
                    points=max(1, req.get('minimum_points', 0)), primitives=max(1, req.get('minimum_primitives', 0)),
                    point_attributes={name: dict(type=kind, size=size) for name, (kind, size) in req.get('point_attributes', {}).items()})
            plans.validate_geometry_readback(pack, version, obs)
            for req in plans.geometry_requirements(pack, version):
                if req.get('minimum_points', 0) == 0:
                    obs[req['role'], '@geometry/' + str(req['output'])].update(points=0, primitives=0, point_attributes={})
            plans.validate_geometry_readback(pack, version, obs)
            key = (plans.geometry_requirements(pack, version)[0]['role'], '@geometry/0')
            obs[key]['origin'] = 'fixture_json'
            with self.assertRaisesRegex(ValueError, 'ACTUAL_NATIVE_GEOMETRY'): plans.validate_geometry_readback(pack, version, obs)
            with self.assertRaisesRegex(ValueError, 'PUBLIC_CONTROL_CONTRACT_CHANGED'): plans.overlay_host_pack(pack, dict(controls={}), version)


class NativeGeometryDeformRoutingTests(unittest.TestCase):
    def observations(self, host):
        observed = software_observations(plans.GEOMETRY, host.version)
        for node in plans.node_requirements(plans.GEOMETRY, host.version):
            role = node['role']
            current = observed[role, '@node']
            current.update(task_root=host.root, path=host.root + '/' + role,
                           context_parent_path=host.root)
        for edge in plans.connection_requirements(plans.GEOMETRY, host.version):
            observed[edge['destination_role'], '@input/' + str(edge['destination_input'])]['source_path'] = (
                observed[edge['source_role'], '@node']['path'])
        observed[deform_program.ROLE, '@geometry_context'] = host.context()
        observed[deform_program.ROLE, '@geometry_parameters'] = host.observe()
        return observed

    def test_routed_candidate_roundtrip_and_zero_preserve_other_controls(self):
        for version in plans.VERSIONS:
            host = BottomHost(version)
            for amplitude in (1.25, 100., 0.):
                with self.subTest(version=version, amplitude=amplitude):
                    observed = self.observations(host)
                    before = copy.deepcopy(observed)
                    controls = dict(deformation=amplitude, seed=31, scale=2., rotation=27.)
                    writes = plans.candidate_write_plan(plans.GEOMETRY, controls, version, observations=observed)
                    self.assertEqual(observed, before)
                    deform = next(write for write in writes if write['public_control'] == 'deformation')
                    plan = deform['geometry_deform_plan']
                    self.assertIsInstance(plan, deform_program.GeometryDeformPlan)
                    with self.assertRaises(FrozenInstanceError):
                        plan.value = 99
                    self.assertEqual(deform['value_kind'], 'trusted_geometry_deform_program')
                    self.assertEqual((deform['role'], deform['parm'], deform['invalidates_from']),
                                     (deform_program.ROLE, 'snippet', 'shaping_meshing'))
                    original = deform_program.validate_plan(plan, host.context(), host.observe())[0]
                    self.assertTrue(all(deform[key] == value for key, value in original.items()))
                    self.assertEqual(plans.semantic_write_map(writes, controls)[deform_program.ROLE, 'snippet'],
                                     ['deformation'])
                    host.apply(plan)
                    after = self.observations(host)
                    for write in writes:
                        if write is not deform:
                            after[write['role'], write['parm']]['value'] = write['value']
                    plans.validate_applied_readback(writes, after)
                    misleading_values = {(deform_program.ROLE, 'snippet'): 'float deform_amplitude = 77;\n'}
                    self.assertEqual(plans.control_readback(plans.GEOMETRY, 'deformation', misleading_values,
                        version, observations=after), amplitude)
                    result = deform_program.control_readback(version, host.context(), host.observe())
                    self.assertEqual((result['status'], result['evidence_scope']), ('BLOCKED', 'parameters_only'))
                    if amplitude == 0:
                        self.assertEqual(deform['value'], 'float deform_amplitude = 0;\n')
                    self.assertEqual({key: value for key, value in host.observe().items() if key[1] != 'snippet'},
                        {key: value for key, value in before[deform_program.ROLE, '@geometry_parameters'].items()
                         if key[1] != 'snippet'})

    def test_missing_actual_context_parameters_or_registered_initialization_refused(self):
        for version in plans.VERSIONS:
            host = BottomHost(version)
            for missing in ('context', 'parameters', 'initialization'):
                observed = self.observations(host)
                if missing == 'initialization':
                    observed[deform_program.ROLE, '@geometry_context']['initialization'] = None
                else:
                    observed.pop((deform_program.ROLE, '@geometry_' + missing))
                with self.subTest(version=version, missing=missing):
                    with self.assertRaises(ValueError):
                        plans.control_write_plan(plans.GEOMETRY, 'deformation', 1, version, observations=observed)
                    with self.assertRaises(ValueError):
                        plans.control_readback(plans.GEOMETRY, 'deformation', {}, version, observations=observed)

    def test_seal_and_routed_fields_cannot_be_changed(self):
        for version in plans.VERSIONS:
            observed = self.observations(BottomHost(version))
            writes = plans.control_write_plan(plans.GEOMETRY, 'deformation', 2, version, observations=observed)
            for field, value in (('value', 'float deform_amplitude = 99;\n'), ('public_control', 'scale'),
                                 ('native_version', plans.VERSIONS[1]), ('domain_id', plans.PARTICLES),
                                 ('role', 'instance_transform'), ('required_gates', []),
                                 ('frozen_readback_guards', []), ('value_kind', 'untrusted')):
                bad = copy.deepcopy(writes)
                if bad[0][field] == value:
                    value = 'unsupported'
                bad[0][field] = value
                with self.subTest(version=version, field=field), self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                    plans.validate_control_write_plan(bad, observed)
            bad = copy.deepcopy(writes)
            bad[0]['geometry_deform_plan'] = replace(bad[0]['geometry_deform_plan'], value=99.)
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                plans.validate_control_write_plan(bad, observed)
            bad[0].pop('geometry_deform_plan')
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                plans.validate_control_write_plan(bad, observed)

    def test_phase_checks_actual_snippet_and_full_parameter_snapshot(self):
        for version in plans.VERSIONS:
            host = BottomHost(version)
            before = self.observations(host)
            writes = plans.control_write_plan(plans.GEOMETRY, 'deformation', 3, version, observations=before)
            with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'):
                plans.validate_control_write_plan(writes, before, after_mutation=True)
            host.apply(writes[0]['geometry_deform_plan'])
            after = self.observations(host)
            plans.validate_control_write_plan(writes, after, after_mutation=True)
            with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'):
                plans.validate_control_write_plan(writes, after)
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                plans.validate_control_write_plan(writes, after, after_mutation='yes')
            for name, field, value in (('snippet', 'value', writes[0]['value'] + '@P *= 2;\n'),
                                       ('group', 'value', '*'), ('snippet', 'locked', True),
                                       ('class', 'menu_uses_token_value', True),
                                       ('snippet', 'channel_identity', 'different')):
                bad = copy.deepcopy(after)
                bad[deform_program.ROLE, '@geometry_parameters'][deform_program.ROLE, name][field] = value
                with self.subTest(version=version, name=name, field=field), self.assertRaises(ValueError):
                    plans.validate_control_write_plan(writes, bad, after_mutation=True)
            foreign = copy.deepcopy(after)
            foreign[deform_program.ROLE, '@geometry_parameters'][deform_program.ROLE, 'snippet']['value'] += '@P *= 2;\n'
            with self.assertRaisesRegex(ValueError, 'PROGRAM_READBACK_MISMATCH'):
                plans.control_readback(plans.GEOMETRY, 'deformation', {}, version, observations=foreign)

    def test_frozen_context_and_whole_domain_topology_drift_refused(self):
        for version in plans.VERSIONS:
            observed = self.observations(BottomHost(version))
            writes = plans.control_write_plan(plans.GEOMETRY, 'deformation', 1, version, observations=observed)
            guards = plans.immutable_readback_guards(writes)
            self.assertIn((deform_program.ROLE, '@geometry_context'),
                          {(guard['role'], guard['parm']) for guard in guards})
            for mutation in ('source', 'initialization', 'host_identity', 'context_wire', 'copy_wire', 'node_identity'):
                bad = copy.deepcopy(observed)
                context = bad[deform_program.ROLE, '@geometry_context']
                if mutation == 'source': context['source']['point_attributes']['P']['values'][0][0] = -3.
                elif mutation == 'initialization': context['initialization']['registered'] = False
                elif mutation == 'host_identity': context['host_identity'] = dict(pid=999, launch_nonce='other')
                elif mutation == 'context_wire': context['nodes']['instance_transform']['inputs'][0]['output_index'] = 1
                elif mutation == 'copy_wire': bad['instance', '@input/0']['source_path'] = '/obj/foreign/source'
                else: bad['scatter', '@node']['session_id'] = 999
                with self.subTest(version=version, mutation=mutation), self.assertRaises(ValueError):
                    plans.validate_control_write_plan(writes, bad)

    def test_geometry_role_fields_static_basis_and_order(self):
        capture = json.loads((ROOT / 'docs/native-basis/w2-wrangle-convolve-static.json').read_text(encoding='utf-8'))
        for version in plans.VERSIONS:
            node = next(node for node in plans.node_requirements(plans.GEOMETRY, version)
                        if node['role'] == deform_program.ROLE)
            self.assertEqual((node['category'], node['types']), ('sop', ['attribwrangle']))
            fields = {aliases[0] for aliases in node['required_parms']}
            self.assertEqual(fields, {'class', 'group', 'snippet', 'vex_precision'})
            self.assertTrue(fields <= set(capture['versions'][version]['operators']['Sop/attribwrangle']['parameters']))
            edges = {(edge['source_role'], edge['destination_role'])
                     for edge in plans.connection_requirements(plans.GEOMETRY, version)}
            self.assertIn(('instance_source', deform_program.ROLE), edges)
            self.assertIn((deform_program.ROLE, 'instance_transform'), edges)
            self.assertNotIn(('instance_source', 'instance_transform'), edges)
            for pack in (plans.PARTICLES, plans.SWARM, plans.OCEAN):
                self.assertNotIn(deform_program.ROLE, {node['role'] for node in plans.node_requirements(pack, version)})
            initialization = plans.trusted_initialization_plan(plans.GEOMETRY, version, fresh=True)
            self.assertNotIn(deform_program.ROLE, {write['role'] for write in initialization})


if __name__ == '__main__':
    unittest.main()
