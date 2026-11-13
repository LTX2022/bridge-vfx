from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from houdini_bridge import native_flip_rbd_domains as plans
from houdini_bridge.domain_packs import get_domain_pack

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / 'tests/fixtures/native/flip-rbd-source-refs.json'


def fact(value, kind='float', size=1, **extra):
    return dict(origin='runtime_hom', type=kind, size=size, value=value,
                driven=False, locked=False, disabled=False, hidden=False, **extra)


def flip_observations():
    return {('fluid_source', 'particlesep'): fact(.1), ('container', 'particlesep'): fact(.1),
            ('surface', 'particlesep'): fact(.1), ('fluid_source', 'createparticles'): fact(1, 'toggle'),
            ('solver', 'overrideres'): fact(0, 'toggle'), ('solver', 'minimumsubsteps'): fact(1, 'integer'),
            ('solver', 'substeps'): fact(2, 'integer'), ('surface', 'voxelsize'): fact(.75),
            ('surface', 'surfacedistance'): fact(1.),
            ('surface', 'surfmethod'): fact(0, 'ordinal', menu_tokens=['particlefluid', 'particles'], menu_uses_token_value=False),
            ('container', 'viscosity'): fact(1, 'toggle'), ('container', 'dovaryingviscosity'): fact(0, 'toggle'),
            ('container', 'default_viscosity'): fact(0.), ('container', 'dosurfacetension'): fact(1, 'toggle'),
            ('container', 'surfacetension'): fact(10.)}


def activation_observations(frame=None, *, current_frame=1, version='21.0.631'):
    """Pure consumer fixture; channel/native production writes are not simulated."""
    names = {p:p.replace('#','4') for p in plans._ACTIVE_TEMPLATES}
    binding = dict(task_id='fixture-task',task_root='/obj/fixture',node_path='/obj/fixture/configure',
        node_type='rbdconfigure',category='sop',parm=names['active#'],template='active#',type='integer',size=1)
    channel = dict(origin='runtime_hom',schema=plans._ACTIVE_SCHEMA,native_version=version,
        task_owned=True,binding=binding,identity=dict(task_id='fixture-task',pid=123,launch_nonce='fixture-nonce',session_id='fixture-session',process_generation='fixture-generation',plugin_build='9'*64,scene_epoch=0,version=version),
        current_frame=current_frame,mode='undriven',reference_path=None,expression=None,
        keyframes=[],keyframe_identities=[],registration=None,samples=[])
    obs = {('configure','@multiparm/attributes'):dict(origin='runtime_hom',parent='attributes',instance_count=1,bindings=names),
        ('configure','@activation_channel'):channel,('configure',names['active#']):fact(1,'integer'),
        ('configure',names['group#']):fact('','string'),('configure',names['addactive#']):fact(1,'toggle'),
        ('configure',names['useactivebounds#']):fact(0,'toggle'),('solver','overwritefromsop'):fact(1,'toggle'),
        ('solver','minactivationimpulseoverride'):fact(0,'toggle'),
        ('solver','overwriteattributes'):fact('active animated deforming __pin __guide_*','string')}
    if frame is not None:
        # Opaque complete serialized native key identities are passed through,
        # not parsed or replaced by a shortened identity in the production plan.
        ids = ['explicit-software-keyframe-identity:'+str(f) for f in (frame-1,frame)]
        registration = dict(schema='bridge.rbd-active-step/1',native_version=channel['native_version'],
            binding=copy.deepcopy(binding),activation_frame=frame,keyframe_identities=ids)
        registration['content_sha256'] = hashlib.sha256(json.dumps(registration,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        channel.update(mode='bridge_constant_step',registration=registration,keyframe_identities=ids,
            keyframes=[dict(frame=frame-1,value=0,expression='constant()',language='Hscript'),
                       dict(frame=frame,value=1,expression='constant()',language='Hscript')],
            samples=[dict(frame=f,value=int(f>=frame)) for f in (frame-2,frame-1,frame,frame+1)],
            pre_extrapolation='constant',post_extrapolation='constant')
        obs['configure',names['active#']] = fact(int(current_frame>=frame),'integer');obs['configure',names['active#']]['driven']=True
    return obs


def impact_observations():
    names = {p: p.replace('#', '7') for p in plans._IMPACT_TEMPLATES}
    obs = {('solver', '@multiparm/breaks'): dict(origin='runtime_hom', parent='breaks', instance_count=1, bindings=names),
           ('solver', 'enable_constraintbreaks'): fact(1, 'toggle'),
           ('solver', 'constraint_reloadfromsops'): fact(0, 'toggle'),
           ('configure', '@geometry/1'): dict(origin='runtime_hom', points=2, primitives=1, constraint_names=['Glue'])}
    for p, v, k in [('constraint_names#', 'Glue', 'string'), ('constraint_group#', '', 'string'),
                    ('constraint_mode#', 0, 'integer'), ('constraint_useimpact#', 1, 'toggle'),
                    ('constraint_scaleimpact#', 0, 'integer'), ('constraint_impactthreshold#', 0., 'float')]:
        obs[('solver', names[p])] = fact(v, k)
    obs.update(activation_observations())
    return obs


class NativeFlipRbdDomainTests(unittest.TestCase):
    def test_captured_fields_and_public_controls_are_preserved_for_both_versions(self):
        source_bytes = FACTS_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), '81d95c43af9bb7ad31f1f7b38b0af958db351c291c589c61a635a2822710e064')
        sources = json.loads(source_bytes)
        captured = json.loads((ROOT/'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
        role_ops = dict(fluid_source='Sop/flipsource', container='Sop/flipcontainer', collisions='Sop/flipcollide',
                        surface='Sop/particlefluidsurface::2.0', solver='Sop/flipsolver')
        for version in plans.VERSIONS:
            ops = sources['versions'][version]['operators']
            for pack in plans.DOMAIN_IDS:
                with self.subTest(version=version, pack=pack):
                    contracts = plans.control_contract(pack, version)
                    public = get_domain_pack(pack).to_dict()
                    overlay = plans.overlay_core_pack_dict(public, version)
                    self.assertEqual({c['id'] for c in public['controls']}, set(contracts))
                    self.assertEqual({c['id'] for c in overlay['controls']}, set(contracts))
                    self.assertEqual(public['controls'], get_domain_pack(pack).to_dict()['controls'])
                    for c in contracts.values():
                        if c['native_status'] != 'mapped': continue
                        if c['role'] == 'configure':
                            field = captured['versions'][version]['operators']['Sop/rbdconfigure']['parameters'][c['aliases'][0]]
                        else:
                            op = 'Sop/rbdbulletsolver' if pack == plans.RBD else role_ops[c['role']]
                            record = ops[op]['parameters'][c['aliases'][0]]; self.assertTrue(record['line_numbers']);field=record['metadata']
                        self.assertEqual(field['type'], c['native_type'])
                        self.assertEqual(field['size'], c['size'])
                    initialization = plans.trusted_initialization_plan(pack, version, fresh=True,
                        observations=impact_observations() if pack == plans.RBD else None)
                    for w in initialization:
                        if w['role'] == 'configure':
                            params=captured['versions'][version]['operators']['Sop/rbdconfigure']['parameters']
                            template=w['parm'] if w['parm'] in params else w['parm'].rstrip('0123456789')+'#'
                            field=params[template]
                        else:
                            op = 'Sop/rbdbulletsolver' if pack == plans.RBD else role_ops[w['role']]
                            template = w['parm'] if w['parm'] in ops[op]['parameters'] else w['parm'].rstrip('0123456789') + '#'
                            field = ops[op]['parameters'][template]['metadata']
                        kind = 'multiparm' if field['type'] == 'multiswitcher' else field['type']
                        self.assertEqual((w['native_type'], w['size']), (kind, field['size']))
                        if w['native_type'] == 'ordinal': self.assertIn(w['value'], field['menu_tokens'][::2])
            edges = plans.connection_requirements(plans.FLIP, version)
            self.assertIn(dict(source_role='collisions', source_output=2, destination_role='surface', destination_input=1), edges)
            wires=plans.connection_requirements(plans.RBD,version)
            constraint_input=next(w for w in wires if w['destination_role']=='solver' and w['destination_input']==1)
            self.assertEqual(constraint_input['source_role'],'constraint_strength')
            self.assertTrue(any(w['source_role']=='configure' and w['source_output']==1 and
                w['destination_role']=='constraint_strength' and w['destination_input']==0 for w in wires))

    def test_original_vendor_archives_and_sections_match_frozen_hashes(self):
        sources = json.loads(FACTS_PATH.read_text(encoding='utf-8'))
        spec = importlib.util.spec_from_file_location('flip_rbd_static_capture', ROOT / 'tools/capture_native_schema.py')
        capture = importlib.util.module_from_spec(spec); spec.loader.exec_module(capture)
        archives = {}; missing = set()
        for version in plans.VERSIONS:
            for operator, record in sources['versions'][version]['operators'].items():
                source = record['source']; path = Path(source['path'])
                if not path.exists():
                    missing.add(str(path)); continue
                if path not in archives:
                    raw = path.read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), source['file_sha256'], (version, operator, str(path)))
                    archives[path] = (hashlib.sha256(raw).hexdigest(), capture.index_sections(raw))
                archive_hash, sections = archives[path]
                self.assertEqual(archive_hash, source['file_sha256'], (version, operator, str(path)))
                operator_name, section = source['member'].rsplit('/', 1)
                member = capture.index_sections(sections[operator_name])[section]
                self.assertEqual(hashlib.sha256(member).hexdigest(), source['section_sha256'], (version, operator))
        if missing:
            self.skipTest('NOT_RUN: original vendor archives unavailable: ' + '; '.join(sorted(missing)))

    def test_joint_spacing_alias_merge_substeps_and_applied_readback(self):
        for version in plans.VERSIONS:
            obs = flip_observations()
            values = dict(particle_separation=.2, surface_resolution=.5, meshing_detail=.5, substeps=4,
                          droplet_scale=1.5, viscosity=8., surface_tension=12.)
            writes = plans.candidate_write_plan(plans.FLIP, values, version, observations=obs)
            keys = [(w['role'], w['parm']) for w in writes]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual([w['value'] for w in writes if w['parm'] == 'particlesep'], [.2] * 3)
            self.assertEqual(next(w['value'] for w in writes if w['parm'] == 'substeps'), 4)
            applied = copy.deepcopy(obs)
            for w in writes: applied[(w['role'], w['parm'])]['value'] = copy.deepcopy(w['value'])
            plans.validate_applied_readback(writes, applied)
            native_values = {key: f['value'] for key, f in applied.items()}
            for name, value in values.items():
                self.assertEqual(plans.control_readback(plans.FLIP, name, native_values, version, observations=applied), value)
            native_values[('surface', 'particlesep')] = .3
            with self.assertRaisesRegex(ValueError, 'READBACK_MISMATCH'):
                plans.control_readback(plans.FLIP, 'particle_separation', native_values, version, observations=applied)
            with self.assertRaisesRegex(ValueError, 'CONFLICTING_NATIVE_CONTROLS'):
                plans.candidate_write_plan(plans.FLIP, dict(surface_resolution=.5, meshing_detail=.7), version, observations=obs)

    def test_impact_uses_observed_instance_and_impact_not_force(self):
        for version in plans.VERSIONS:
            obs = impact_observations()
            writes = plans.candidate_write_plan(plans.RBD, dict(impact_threshold=3.), version, observations=obs)
            self.assertEqual([(w['parm'], w['value']) for w in writes], [('constraint_impactthreshold7', 3.)])
            applied = copy.deepcopy(obs); applied[('solver', 'constraint_impactthreshold7')]['value'] = 3.
            plans.validate_applied_readback(writes, applied)
            observed = {key: f['value'] for key, f in applied.items() if 'value' in f}
            self.assertEqual(plans.control_readback(plans.RBD, 'impact_threshold', observed, version, observations=applied), 3.)
            for mutate in ('binding', 'names', 'scaling'):
                bad = copy.deepcopy(obs)
                if mutate == 'binding': bad[('solver', '@multiparm/breaks')]['bindings']['constraint_mode#'] = 'constraint_mode8'
                elif mutate == 'names': bad[('solver', 'constraint_names7')]['value'] = 'Unknown'
                else: bad[('solver', 'constraint_scaleimpact7')]['value'] = 1
                with self.subTest(version=version, mutate=mutate), self.assertRaises(ValueError):
                    plans.candidate_write_plan(plans.RBD, dict(impact_threshold=3.), version, observations=bad)
            drag = {('solver', 'drag_airresist'): fact(.00075), ('solver', 'adddrag'): fact(1, 'toggle'),
                    ('solver', 'drag_usegroup'): fact(0, 'toggle'), ('solver', 'drag_uselocaldrag'): fact(0, 'toggle'),
                    ('solver', 'drag_windvelocity'): fact([0., 0., 0.], size=3)}
            self.assertEqual(plans.candidate_write_plan(plans.RBD, dict(drag=.5), version, observations=drag)[0]['parm'], 'drag_airresist')
            glue = {('solver', 'glue_strength'): fact(1.), ('solver', 'glue_dataname'): fact('Glue', 'string'),
                    ('solver', 'glue_defaultparmop'): fact('always', 'ordinal', menu_tokens=['initial', 'always', 'never'], menu_uses_token_value=False),
                    ('solver', '@input_geometry/1'): dict(origin='runtime_hom', primitives=2,
                        primitive_attributes={'constraint_name': dict(type='string', size=1), 'strength': dict(type='float', size=1)},
                        primitive_attribute_values={'constraint_name': ['Glue', 'Soft'], 'strength': [1., 5.]})}
            strength_plan = plans.candidate_write_plan(plans.RBD, dict(constraint_strength=9.), version, observations=glue)
            self.assertEqual(strength_plan[0]['parm'], 'glue_strength')
            self.assertEqual(strength_plan[0]['value'], 9.)
            applied = copy.deepcopy(glue); applied[('solver', 'glue_strength')]['value'] = 9.
            plans.validate_applied_readback(strength_plan, applied)
            self.assertEqual(plans.control_readback(plans.RBD, 'constraint_strength', {('solver', 'glue_strength'): 9.}, version, observations=applied), 9.)
            glue[('solver', '@input_geometry/1')]['primitive_attribute_values']['strength'][0] = 2.
            with self.assertRaisesRegex(ValueError, 'ACTUAL_UNIT_GLUE_PRIMITIVE_STRENGTHS_REQUIRED'):
                plans.candidate_write_plan(plans.RBD, dict(constraint_strength=9.), version, observations=glue)
            with self.assertRaisesRegex(ValueError, 'CONTEXT_CHANGED'):
                plans.validate_control_write_plan(strength_plan, glue)

        for version in plans.VERSIONS:
            for frame in (-100000,-3,0,17,100000):
                obs=activation_observations(version=version)
                before=copy.deepcopy(obs);writes=plans.candidate_write_plan(plans.RBD,dict(activation_frame=frame),version,observations=obs)
                self.assertEqual(obs,before)
                self.assertEqual(writes[0]['parm'],'active4');self.assertEqual(writes[0]['schedule'],[dict(frame=frame-1,value=0),dict(frame=frame,value=1)])
                applied=activation_observations(frame,version=version);ch=applied['configure','@activation_channel'];ch['native_version']=version;ch['registration']['native_version']=version
                payload={k:v for k,v in ch['registration'].items() if k!='content_sha256'}
                ch['registration']['content_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                plans.validate_applied_readback(writes,applied)
                self.assertEqual(plans.control_readback(plans.RBD,'activation_frame',{},version,observations=applied),frame)
                # Feedback may only replace the host-authenticated prior step.
                self.assertEqual(plans.candidate_write_plan(plans.RBD,dict(activation_frame=frame+1 if frame<100000 else frame-1),version,observations=applied)[0]['parm'],'active4')
                if frame != -3 or version != plans.VERSIONS[0]: continue
                for field,value in [('native_version','wrong'),('task_owned',False),('reference_path','/obj/external/v')]:
                    bad=copy.deepcopy(applied);bad['configure','@activation_channel'][field]=value
                    with self.subTest(frame=frame,field=field),self.assertRaises(ValueError):plans.validate_applied_readback(writes,bad)
                for mutate in ('identities','sample','extrapolation','binding','foreigndriver','overwrite','identity','override'):
                    bad=copy.deepcopy(applied);channel=bad['configure','@activation_channel']
                    if mutate=='identities':channel['keyframe_identities'][0]+='changed-native-field'
                    elif mutate=='sample':channel['samples'][2]['value']=0
                    elif mutate=='extrapolation':channel['pre_extrapolation']='cycle'
                    elif mutate=='binding':channel['binding']['task_id']='foreign-task'
                    elif mutate=='foreigndriver':channel['registration']=None
                    elif mutate=='overwrite':bad['solver','overwriteattributes']['value']='animated deforming'
                    elif mutate=='identity':channel['identity']['launch_nonce']='different-instance'
                    else:bad['solver','minactivationimpulseoverride']['value']=1
                    with self.subTest(frame=frame,mutate=mutate),self.assertRaises(ValueError):plans.validate_applied_readback(writes,bad)
                poison=copy.deepcopy(writes);poison[0]['schedule'][0]['value']=1
                with self.assertRaisesRegex(ValueError,'UNTRUSTED_ACTIVE_CHANNEL_WRITE'):plans.validate_control_write_plan(poison,obs)
                poison=copy.deepcopy(writes);poison[0].pop('value_kind')
                with self.assertRaisesRegex(ValueError,'UNTRUSTED_ACTIVE_CHANNEL_WRITE'):plans.validate_control_write_plan(poison,obs)

    def test_bad_inputs_unknown_facts_and_frozen_guards_reject(self):
        cases = [(True, 'INVALID_NATIVE_CONTROL_VALUE'), (float('nan'), 'INVALID_NATIVE_CONTROL_VALUE'),
                 (-1., 'INVALID_NATIVE_CONTROL_VALUE')]
        for value, code in cases:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, code):
                plans.candidate_write_plan(plans.FLIP, dict(particle_separation=value), '21.0.631', observations=flip_observations())
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_NATIVE_VERSION'):
            plans.candidate_write_plan(plans.FLIP, {}, '21.0.632')
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_NATIVE_DOMAIN'):
            plans.candidate_write_plan('unknown', {}, '21.0.631')
        for flag in ('origin', 'type', 'size', 'driven', 'locked', 'hidden', 'disabled'):
            obs = flip_observations(); obs[('surface', 'particlesep')].pop(flag)
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                plans.candidate_write_plan(plans.FLIP, dict(particle_separation=.2), '21.0.631', observations=obs)
        obs = flip_observations(); obs[('fluid_source', 'createparticles')]['type'] = 'float'
        with self.assertRaisesRegex(ValueError, 'ACTUAL_NATIVE_CONTEXT_REQUIRED'):
            plans.candidate_write_plan(plans.FLIP, dict(particle_separation=.2), '21.0.631', observations=obs)
        obs = flip_observations(); obs[('solver', 'substeps')]['value'] = 8
        writes = plans.candidate_write_plan(plans.FLIP, dict(substeps=4), '21.0.631', observations=obs)
        self.assertEqual(len(writes), 1)
        poisoned = copy.deepcopy(writes); poisoned[0]['value'] = '4'
        with self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_WRITE_VALUE'):
            plans.validate_control_write_plan(poisoned, obs)
        changed = copy.deepcopy(obs); changed[('solver', 'substeps')]['value'] = 9
        with self.assertRaisesRegex(ValueError, 'CONTEXT_CHANGED'):
            plans.validate_control_write_plan(writes, changed)
        changed = copy.deepcopy(obs); changed[('solver', 'minimumsubsteps')]['value'] = 4
        plans.validate_applied_readback(writes, changed)
        obs = impact_observations(); writes = plans.candidate_write_plan(plans.RBD, dict(impact_threshold=3.), '21.0.631', observations=obs)
        obs[('solver', '@multiparm/breaks')]['bindings']['constraint_names#'] = 'constraint_names8'
        with self.assertRaisesRegex(ValueError, 'CONTEXT_CHANGED'):
            plans.validate_control_write_plan(writes, obs)

    def test_specific_physical_blockers_and_fresh_initialization(self):
        for pack, control, blocker in [(plans.RBD, 'fracture_scale', 'PHYSICAL_FRAGMENT_SCALE_CONTRACT_REQUIRED'),
                                       (plans.RBD, 'piece_scale', 'ACTUAL_PIECE_SCALE_GEOMETRY_CONTRACT_REQUIRED'),
                                       (plans.RBD, 'activation_frame', 'ACTUAL_MULTIPARM_BINDING_REQUIRED'),
                                       (plans.FLIP, 'collision_passes', 'FLIP_COLLISION_PASSES_NATIVE_FIELD_NOT_CAPTURED')]:
            with self.subTest(control=control), self.assertRaisesRegex(ValueError, blocker):
                plans.candidate_write_plan(pack, {control: 1}, '21.0.631')
        for pack in plans.DOMAIN_IDS:
            with self.assertRaisesRegex(ValueError, 'FRESH_TASK_OWNED_NODE_REQUIRED'):
                plans.trusted_initialization_plan(pack, '21.0.631')
            init = plans.trusted_initialization_plan(pack, '21.0.631', fresh=True,
                observations=impact_observations() if pack == plans.RBD else None)
            self.assertTrue(all(w['fresh_only'] for w in init))
            allocation = plans.trusted_initialization_plan(pack, '21.0.631', fresh=True, phase='allocate')
            self.assertEqual([(w['parm'], w['value']) for w in allocation], [('breaks', 1)] if pack == plans.RBD else [])
        activation_init=plans.trusted_initialization_plan(plans.RBD,'21.0.631',fresh=True,initialize_activation=True,observations=impact_observations())
        self.assertIn(('attributes',1),[(w['parm'],w['value']) for w in activation_init])
        self.assertIn(('addactive4',1),[(w['parm'],w['value']) for w in activation_init])
        self.assertNotIn('active4',[w['parm'] for w in activation_init])  # Channel is authored by the trusted candidate adapter.
        with self.assertRaisesRegex(ValueError, 'ACTUAL_MULTIPARM_BINDING_REQUIRED'):
            plans.trusted_initialization_plan(plans.RBD, '21.0.631', fresh=True, phase='gates')

    def test_geometry_and_consumer_connections_require_actual_observations(self):
        for pack in plans.DOMAIN_IDS:
            obs = {}
            for requirement in plans.geometry_requirements(pack, '21.0.631'):
                item = dict(origin='runtime_hom', points=max(4, requirement.get('minimum_points', 0)), primitives=max(2, requirement.get('minimum_primitives', 0)))
                if 'primitive_types' in requirement: item['primitive_types'] = requirement['primitive_types']
                for owner in ('point', 'primitive'):
                    item[owner + '_attributes'] = {name: dict(type=kind, size=size) for name, (kind, size) in requirement.get(owner + '_attributes', {}).items()}
                obs[(requirement['role'], '@geometry/' + str(requirement['output']))] = item
            for edge in plans.connection_requirements(pack, '21.0.631'):
                obs[(edge['destination_role'], '@input/' + str(edge['destination_input']))] = dict(origin='runtime_hom', source_role=edge['source_role'], source_output=edge['source_output'])
            plans.validate_geometry_readback(pack, '21.0.631', obs)
            obs[('solver', '@input/2')]['source_output'] = 0
            with self.assertRaisesRegex(ValueError, 'CONNECTION_REQUIRED'):
                plans.validate_geometry_readback(pack, '21.0.631', obs)
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_REQUIRED'):
                plans.validate_geometry_readback(pack, '21.0.631', {})


if __name__ == '__main__':
    unittest.main()
