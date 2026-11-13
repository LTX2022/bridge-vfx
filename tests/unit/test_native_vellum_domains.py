from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest

from houdini_bridge import native_vellum_domains as plans
from houdini_bridge.domain_packs import get_domain_pack

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / 'tests/fixtures/native/vellum-operator-facts.json'
DOMAINS = [(plans.CLOTH, 'cloth'), (plans.SOFT_GRAINS, 'softbody'), (plans.SOFT_GRAINS, 'grains')]


def observation(value, kind='float', **extra):
    return {'origin': 'runtime_hom', 'type': kind, 'size': 1, 'value': value,
            'locked': False, 'disabled': False, 'hidden': False, 'driven': False, **extra}


def exponent(value):
    return observation(value, 'ordinal', menu_uses_token_value=True,
                       menu_tokens=[str(x) for x in range(10, -11, -1)])


class NativeVellumDomainTests(unittest.TestCase):
    def test_same_version_metadata_types_menus_and_all_required_fields(self):
        fact_bytes = FACTS_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(fact_bytes).hexdigest(), '5e8063ca5dc84d644bf3b487a661f50afc4b5a898ef09dd4cb1298306b33f3b2')
        facts = json.loads(fact_bytes)
        supplement=json.loads((ROOT/'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
        role_ops = {'constraints': 'Sop/vellumconstraints', 'cluster_constraints': 'Sop/vellumconstraints',
                    'grain_source': 'Sop/vellumconstraints_grain', 'tet_mesh': 'Sop/tetconform',
                    'cluster_points': 'Sop/clusterpoints', 'solver': 'Sop/vellumsolver'}
        for version in plans.VERSIONS:
            for pack, branch in DOMAINS:
                with self.subTest(version=version, branch=branch):
                    for node in plans.node_requirements(pack, version, branch):
                        if node['role'] not in role_ops:
                            continue
                        fields = facts[version][role_ops[node['role']]]['parameters']
                        for aliases in node['required_parms']:
                            self.assertTrue(any(name in fields for name in aliases), aliases)
                    allocated = False
                    for w in plans.trusted_initialization_plan(pack, version, branch):
                        if w['role']=='source':
                            self.assertIn(w['parm'],('rows','cols'))
                            grid_basis=json.loads((ROOT/'docs/native-basis/grid-rows-columns-static.json').read_text(encoding='utf-8'))
                            source=next(row for row in grid_basis['versions'] if row['version']==version)
                            self.assertIn('#id: '+w['parm'],source['help']['text'])
                            continue
                        fields = (supplement['versions'][version]['operators']['Sop/attribwrangle']['parameters']
                            if w['role']=='cloth_wrinkle' else facts[version][role_ops[w['role']]]['parameters'])
                        template = w['parm'] if w['parm'] in fields else re.sub(r'\d+$', '#', w['parm'])
                        native = fields[template]
                        self.assertEqual(w['native_type'], native['type'])
                        if w['native_type'] == 'ordinal':
                            self.assertIn(str(w['value']), native['menu_tokens'][1::2] if w.get('value_kind')=='menu_label' else native['menu_tokens'][::2])
                            if w.get('menu_uses_token_value'):
                                self.assertIs(native['menu_uses_token_value'], True)
                        if w['parm'] == 'num_controls':
                            allocated = True
                        if '#' in template:
                            self.assertTrue(allocated)
            self.assertEqual(facts[version]['Sop/vellumsolver']['parameters']['friction']['type'], 'toggle')
            self.assertEqual(facts[version]['Sop/vellumconstraints_grain']['parameters']['friction']['type'], 'float')
            self.assertIn('method != grid', facts[version]['Sop/vellumconstraints_grain']['parameters']['packingdensity']['hide_when'])

    def test_original_vendor_archives_and_sections_match_frozen_hashes(self):
        facts = json.loads(FACTS_PATH.read_text(encoding='utf-8'))
        spec = importlib.util.spec_from_file_location('vellum_static_capture', ROOT / 'tools/capture_native_schema.py')
        capture = importlib.util.module_from_spec(spec); spec.loader.exec_module(capture)
        archives = {}; missing = set()
        for version in plans.VERSIONS:
            for operator, record in facts[version].items():
                path = Path(record['path'])
                if not path.exists():
                    missing.add(str(path)); continue
                if path not in archives:
                    raw = path.read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), record['archive_sha256'], (version, operator, str(path)))
                    archives[path] = (hashlib.sha256(raw).hexdigest(), capture.index_sections(raw))
                archive_hash, sections = archives[path]
                self.assertEqual(archive_hash, record['archive_sha256'], (version, operator, str(path)))
                operator_name, section = record['member'].rsplit('/', 1)
                member = capture.index_sections(sections[operator_name])[section]
                self.assertEqual(hashlib.sha256(member).hexdigest(), record['section_sha256'], (version, operator))
        if missing:
            self.skipTest('NOT_RUN: original vendor archives unavailable: ' + '; '.join(sorted(missing)))

    def test_explicit_branch_overlays_preserve_all_controls_and_real_multiple_inputs(self):
        for version in plans.VERSIONS:
            for pack_id, branch in DOMAINS:
                original = get_domain_pack(pack_id).to_dict(); before = copy.deepcopy(original)
                overlay = plans.overlay_core_pack_dict(original, version, branch)
                self.assertEqual(original, before)
                self.assertEqual({c['id'] for c in original['controls']}, {c['id'] for c in overlay['controls']})
                nodes = {n['role']: n for n in overlay['nodes']}
                edges = {(e['source_role'], e['source_output'], e['destination_role'], e['destination_input']) for e in overlay['connections']}
                terminal = 'constraints' if branch == 'cloth' else 'cluster_constraints'
                self.assertIn((terminal, 0, 'solver', 0), edges)
                self.assertIn((terminal, 1, 'solver', 1), edges)
                self.assertIn(('collision_source', 0, 'collision_transform', 0), edges)
                self.assertIn(('collision_transform', 0, 'solver', 2), edges)
                self.assertNotIn(('source', 0, 'solver', 0), edges)
                if branch != 'cloth':
                    self.assertIn(('constraints', 1, 'cluster_constraints', 1), edges)
                    self.assertIn(('constraints', 0, 'cluster_points', 0), edges)
                    self.assertIn(('cluster_points', 0, 'cluster_constraints', 0), edges)
                if branch == 'softbody':
                    self.assertIn(('source', 0, 'tet_mesh', 0), edges)
                    self.assertIn(('tet_mesh', 0, 'constraints', 0), edges)
                    self.assertNotIn('grain_source', nodes)
                if branch == 'grains':
                    self.assertIn(('grain_source', 1, 'constraints', 1), edges)
                    self.assertIn(('source', 0, 'grain_source', 0), edges)
                    self.assertNotIn('tet_mesh', nodes)
                bad = copy.deepcopy(original); bad['controls'].pop()
                with self.assertRaisesRegex(plans.NativeVellumDomainError, 'PUBLIC_CONTROL_CONTRACT_CHANGED'):
                    plans.overlay_core_pack_dict(bad, version, branch)
        with self.assertRaisesRegex(plans.NativeVellumDomainError, 'EXPLICIT_VELLUM_BRANCH_REQUIRED'):
            plans.node_requirements(plans.SOFT_GRAINS, '21.0.631', None)

    def test_fresh_initialization_modes_cluster_membership_and_normal_source_geometry(self):
        version = '21.0.631'
        for pack, branch in DOMAINS:
            writes = plans.trusted_initialization_plan(pack, version, branch, cluster_count=3, cluster_seed=17)
            values = {(w['role'], w['parm']): w['value'] for w in writes}
            req = {(r['role'], r['output']): r for r in plans.geometry_requirements(pack, version, branch)}
            self.assertIn(('collision_transform', 0), req)
            self.assertEqual(req[('constraints', 1)]['minimum_primitives'], 1)
            if branch == 'softbody':
                self.assertEqual(values[('constraints', 'constrainttype')], 'tetstretch')
                self.assertEqual(values[('constraints', 'preservevol')], 1)
                self.assertEqual(values[('constraints', 'linear')], 'normarap')
                self.assertEqual(req[('tet_mesh', 0)]['kind'], 'tetrahedral_solid')
            elif branch == 'grains':
                self.assertEqual(values[('grain_source', 'createpoints')], 1)
                self.assertEqual(values[('grain_source', 'method')], 'grid')
                self.assertEqual(values[('grain_source', 'type')], 'grain')
                # Points have no edge graph: use actual neighbour glue bonds.
                self.assertEqual(values[('constraints', 'constrainttype')], 'glue')
                self.assertEqual(values[('constraints', 'glue_radius')], 2 * values[('grain_source', 'grainsize')])
                self.assertEqual(values[('constraints', 'glue_detach_chance')], 0)
                self.assertEqual(req[('grain_source', 0)]['pscale_relation'], 'diameter/2')
            else:
                self.assertEqual(values[('constraints', 'constrainttype')], 'cloth')
                self.assertEqual(values[('constraints', 'dothickness')], 'on')
                gate = next(i for i,w in enumerate(writes) if w['parm'] == 'dothickness')
                write = next(i for i,w in enumerate(writes) if w['parm'] == 'thickness')
                self.assertLess(gate, write)
            if branch != 'cloth':
                self.assertEqual(values[('cluster_constraints', 'constrainttype')], 'shapematch')
                self.assertEqual(values[('cluster_constraints', 'pieceattrib')], 'cluster')
                self.assertEqual(values[('cluster_points', 'attrib_name')], 'cluster')
                self.assertEqual(values[('cluster_points', 'cluster_output')], 'clusterpoints')
                self.assertEqual(values[('cluster_points', 'num_clusters')], 3)
                self.assertEqual(values[('cluster_points', 'random_seed')], 17)
                self.assertIs(req[('cluster_constraints', 1)]['must_preserve_incoming_constraints'], True)
                self.assertEqual(req[('cluster_points', 0)]['required_point_attributes'], {'cluster': 'integer'})

    def test_stiffness_exponent_conversion_freezes_existing_multiplier(self):
        for pack, branch in DOMAINS:
            name = 'stretch_stiffness' if branch == 'cloth' else 'stiffness'
            exp = {('constraints', 'stretchstiffnessexp'): exponent(3)}
            writes = plans.control_write_plan(pack, name, 2000., '21.0.631', branch, observations=exp)
            self.assertEqual([(w['parm'], w['value']) for w in writes], [('stretchstiffness', 2.)])
            self.assertEqual(plans.control_readback(pack, name, {('constraints', 'stretchstiffness'):2.}, '21.0.631', branch, observations=exp), 2000.)
            self.assertEqual(plans.immutable_readback_guards(writes)[0]['value'], 3)
            changed = {('constraints', 'stretchstiffnessexp'): exponent(4)}
            with self.assertRaisesRegex(plans.NativeVellumDomainError, 'CONTEXT_CHANGED'):
                plans.validate_readback_guards(writes, changed)
            for bad in ({}, {('constraints', 'stretchstiffnessexp'): observation(3, 'ordinal')},
                        {('constraints', 'stretchstiffnessexp'): exponent(21)},
                        {('constraints', 'stretchstiffnessexp'): {**exponent(3),'driven':True}}):
                with self.assertRaisesRegex(plans.NativeVellumDomainError, 'ACTUAL_STIFFNESS_EXPONENT_REQUIRED'):
                    plans.control_write_plan(pack, name, 2000., '21.0.631', branch, observations=bad)
        exp = {('cluster_constraints', 'stretchstiffnessexp'): exponent(-1)}
        writes = plans.control_write_plan(plans.SOFT_GRAINS, 'cluster_stiffness', 2., '22.0.429', 'grains', observations=exp)
        self.assertEqual((writes[0]['role'],writes[0]['value']),('cluster_constraints',20.))
        both = {('constraints','stretchstiffnessexp'):exponent(0)}
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'CONFLICTING_NATIVE_CONTROLS'):
            plans.candidate_write_plan(plans.SOFT_GRAINS, {'stiffness':2,'constraint_stiffness':3}, '21.0.631', 'softbody', observations=both)

    def test_joint_grain_size_and_branch_accurate_friction_and_fail_closed_gates(self):
        pack = plans.SOFT_GRAINS; version = '21.0.631'
        old = {('grain_source','grainsize'):observation(.1),('constraints','glue_radius'):observation(.2)}
        writes = plans.control_write_plan(pack, 'grain_size', .3, version, 'grains', observations=old)
        self.assertEqual([(w['role'], w['parm'], w['value']) for w in writes], [('grain_source','grainsize',.3),('constraints','glue_radius',.6)])
        changed_joint = {('grain_source','grainsize'):observation(.3),('constraints','glue_radius'):observation(.6)}
        plans.validate_readback_guards(writes,changed_joint,after_mutation=True)
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'CONTEXT_CHANGED'):
            plans.validate_readback_guards(writes,changed_joint)
        self.assertEqual(plans.control_readback(pack,'grain_size',{('grain_source','grainsize'):.3,('constraints','glue_radius'):.6},version,'grains'),.3)
        observed = copy.deepcopy(old)
        for w in writes:
            for role,parm,value in w['required_gates']:
                observed[(role,parm)] = observation(value, 'ordinal' if isinstance(value,str) else 'toggle')
        plans.validate_control_write_plan(writes, observed)
        for role, parm, value in [('grain_source','createpoints',0),('grain_source','method','pack'),('constraints','constrainttype','distance')]:
            bad = copy.deepcopy(observed); bad[(role,parm)]['value']=value
            with self.assertRaisesRegex(plans.NativeVellumDomainError,'GATE_BLOCKED'):
                plans.validate_control_write_plan(writes,bad)
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'GRAIN_BOND_SEARCH_CONTRACT_REQUIRED'):
            plans.control_write_plan(pack,'grain_size',.3,version,'grains',observations={**old,('constraints','glue_radius'):observation(.9)})
        context = {('solver','static_threshold'):observation(.5),('solver','dynamic_scale'):observation(.1)}
        fric = plans.control_write_plan(pack,'friction',.7,version,'grains',observations=context)[0]
        self.assertEqual((fric['role'],fric['parm'],fric['native_type']),('grain_source','friction','float'))
        self.assertIn(('grain_source','dofriction',1),fric['required_gates'])
        changed_context={**context,('solver','static_threshold'):observation(.8)}
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'CONTEXT_CHANGED'):
            plans.validate_readback_guards([fric],changed_context,after_mutation=True)
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'ACTUAL_FRICTION_CONTEXT_REQUIRED'):
            plans.control_write_plan(pack,'friction',.7,version,'grains',observations={})
        soft = plans.control_write_plan(pack,'friction',.7,version,'softbody')[0]
        self.assertEqual((soft['role'],soft['parm'],soft['native_type']),('solver','static_threshold','float'))
        for control,branch,reason in [('grain_size','softbody','GRAINS_BRANCH'),('packing','softbody','GRAINS_BRANCH')]:
            with self.assertRaisesRegex(plans.NativeVellumDomainError,reason):
                plans.control_write_plan(pack,control,1,version,branch)
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'ZERO_PACKING_DENSITY'):
            plans.control_write_plan(pack,'packing',0,version,'grains')
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'ACTUAL_CLOTH_GEOMETRY'):
            plans.control_write_plan(plans.CLOTH,'wrinkle_scale',1,version,'cloth')

    def test_actual_interface_and_no_driven_hidden_disabled_artist_channels(self):
        writes = plans.control_write_plan(plans.SOFT_GRAINS,'collision_passes',20,'21.0.631','grains')
        actual = {('solver','collisionsiter'):observation(10,'integer'),('solver','enablecollisions'):observation(1,'toggle')}
        plans.validate_control_write_plan(writes,actual)
        for field in ('locked','disabled','hidden','driven','type','origin'):
            changed=copy.deepcopy(actual); changed[('solver','collisionsiter')][field]=True if field not in ('type','origin') else 'unknown'
            with self.assertRaises(plans.NativeVellumDomainError):
                plans.validate_control_write_plan(writes,changed)
        with self.assertRaisesRegex(plans.NativeVellumDomainError,'INTERFACE_REQUIRED'):
            plans.validate_control_write_plan(writes,{})


if __name__ == '__main__':
    unittest.main()
