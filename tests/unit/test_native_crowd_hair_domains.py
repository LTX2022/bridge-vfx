from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_crowd_hair_domains as plans
from houdini_bridge.domain_packs import get_domain_pack

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / 'tests/fixtures/native/crowd-hair-operator-facts.json'
FACTS = json.loads(FACTS_PATH.read_text(encoding='utf-8'))
ROLE_OPS = {'guide_seed':'Sop/hairgen::2.0','hair':'Sop/hairgen::2.0','guides':'Sop/guidegroom::2.0','guide_length':'Sop/guideprocess','hair_clump':'Sop/hairclump::2.0','constraints':'Sop/vellumconstraints','solver_hair':'Sop/vellumsolver','source_crowd':'Sop/crowdsource::3.0','state':'Dop/crowdstate::3.0','solver_crowd':'Dop/crowdsolver::3.0','population':'Dop/popsource::2.0','import_geometry':'Sop/dopimportfield','wander':'Dop/popsteerwander'}


def observation(value, kind='float', size=1, **extra):
    return dict(origin='runtime_hom',type=kind,size=size,value=value,locked=False,disabled=False,hidden=False,driven=False,**extra)


def binding(role,parent,templates,index=7):
    names = {t:t.replace('#',str(index)) for t in templates}
    obs = {(role,'@multiparm/'+parent):dict(origin='runtime_hom',parent=parent,instance_count=1,bindings=names)}
    for name in names.values():
        obs[(role,name)] = observation(0.)
    return obs


def contexts(pack):
    if pack == plans.HAIR:
        obs = binding('guide_length','operations',plans._LENGTH_TEMPLATES)
        obs[('constraints','bendstiffnessexp')] = observation(3,'ordinal',menu_uses_token_value=True,menu_tokens=[str(x) for x in range(-10,11)])
        obs[('solver','@trusted_axis')] = dict(origin='trusted_host_runtime',value=[0.,0.,1.])
        obs[('constraints','@collision_radius_convention')] = dict(origin='runtime_hom',contract='pscale_is_collision_radius',verified_from='actual_point_pscale_and_documented_native_radius',documentation_sha256='64f9bf4f360eb3d9f202c2174b8dd1962c70ef31debfda6108528966235a0a25')
        obs[('constraints','thickness')]=observation(.01)
        obs[('constraints','@geometry/0')]=dict(origin='runtime_hom',points=4,point_attributes={'pscale':{'type':'float','size':1}},point_attribute_values={'pscale':[.01]*4})
    else:
        obs = binding('import_geometry','fields',plans._IMPORT_TEMPLATES,4)
        obs[('source','@trusted_axis')] = dict(origin='trusted_host_runtime',value=[0.,0.,-1.])
        obs[('agent_definition','@actual_clip')] = dict(origin='runtime_hom',api_helper=plans.HOM_HELPER_MODULE,native_type='PackedAgent',clip_name='w5_loop',sample_count=3,sample_rate=30.7,start_time=12.5,length_seconds=.065,content_sha256='a'*64)
        obs[('bullet','constraintsolvertype')] = observation('gaussseidelisland','ordinal',menu_tokens=['gaussseidelisland'],menu_uses_token_value=False)
        obs[('bullet','randomize_order')] = observation(1,'toggle')
        obs[('crowd_object','@node_identity')] = dict(origin='runtime_hom',task_owned=True,name='owned_crowd_object_2')
    return obs


def root_fact():
    return dict(origin='runtime_hom',role='hair_clump',output=0,geometry_sha256='b'*64,point_count=6,curves=[dict(kind='open_curve',closed=False,point_numbers=[4,5,3]),dict(kind='open_curve',closed=False,point_numbers=[1,2,0])])


def applied_observations(pack,writes,obs):
    result=copy.deepcopy(obs)
    for w in writes:
        extra={}
        if w['native_type']=='ordinal':
            extra=dict(menu_tokens=[str(x) for x in range(-10,11)] if w.get('menu_uses_token_value') else [w['value']],menu_uses_token_value=bool(w.get('menu_uses_token_value')))
        result[(w['role'],w['parm'])]=observation(w['value'],w['native_type'],w.get('size',1),**extra)
        for role,parm,value in w.get('required_gates',()):
            if (role,parm) not in result or not plans._gate_matches(result[(role,parm)],value):
                result[(role,parm)]=observation(value,'ordinal' if isinstance(value,str) else 'toggle',menu_tokens=[value] if isinstance(value,str) else [],menu_uses_token_value=False)
    if ('constraints','thickness') in result and ('constraints','@geometry/0') in result:
        result[('constraints','@geometry/0')]['point_attribute_values']['pscale']=[result[('constraints','thickness')]['value']]*4
    return result


class NativeCrowdHairDomainTests(unittest.TestCase):
    def test_owned_stash_scene_contract_reads_actual_agent_data_and_rejects_changed_pose(self):
        import os, sys, tempfile
        from vfx_pipeline.workbuddy_assembly import software_host_client
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        native=load('stash_native_schema',ROOT/'tools/native_schema_test_boundary.py')
        api=load('stash_stage_api',ROOT/'tools/software_render_api_boundary.py')
        agent_api=load('stash_agent_api',ROOT/'tools/software_agent_api_boundary.py')
        for version in plans.VERSIONS:
            with self.subTest(version=version),tempfile.TemporaryDirectory() as temp,patch.dict(sys.modules),patch.dict(os.environ,{
                    'BRIDGE_SKILLS_STATE_ROOT':temp+'/state','HOUDINI_BRIDGE_STATE_DIR':temp+'/h',
                    'BRIDGE_SKILLS_SCHEDULER_ROOT':temp+'/scheduler'}),patch('subprocess.Popen',
                    side_effect=OSError('test_injected_process_boundary: external process NOT_RUN')):
                client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(temp)/'host')
                interfaces,states,ports=api.interface_profiles(ROOT,version)
                native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                hou=sys.modules['hou'];hou._software_agent_api_state={'origin':'test_injected_native_api',
                    'clip_sample_rate':30.7,'clip_start_time':12.5}
                agent_api.install_agent_api(hou);api.install_stage_api(hou)
                params={'task_id':'stash-contract','constraints':{'fx':{'domain_pack':plans.CROWD,
                    'run_mode':'diagnose','frames':[1,2]}},'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                result=client.call('agent.fx.build_preview',params)
                roles=result['scene_manifest']['nodes']
                stash=hou.node(roles['agent_definition']);value,channel=addon._fx_scene_parameter_readback(stash.parm('stash'))
                self.assertTrue(channel['evaluated_available']);self.assertIn('agents',value['content'])
                self.assertEqual(value['content']['agents'][0]['clips'][0]['sample_rate'],30.7)
                contract=addon._fx_capture_scene_contract('stash-contract')
                record=next(n for n in contract['nodes'] if n['path']==stash.path())
                self.assertEqual(record['parameters']['stash'],value)
                geometry=stash.parm('stash').evalAsGeometry()
                agent=geometry.prims()[0];agent.setLocalTransform(hou.hmath.buildTranslate(1.,0.,0.),0)
                stash.parm('stash').set(geometry)
                with self.assertRaisesRegex(Exception,'differs|changed'):
                    addon._fx_scene_parameter_readback(stash.parm('stash'))

    def test_original_vendor_archives_sections_and_parsed_fields_match_frozen_facts(self):
        spec=importlib.util.spec_from_file_location('native_static_capture',ROOT/'tools/capture_native_schema.py');capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
        archives={};missing=set()
        for version in plans.VERSIONS:
            for op in FACTS[version].values():
                source=op['source']; path=source['vendor_source']; sha=source['source_sha256']
                if not Path(path).exists():
                    missing.add(path);continue
                if path not in archives:
                    raw=Path(path).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),sha,(version,path))
                    archives[path]=(hashlib.sha256(raw).hexdigest(),capture.index_sections(raw))
                archive_hash,sections=archives[path];self.assertEqual(archive_hash,sha,(version,path))
                opname,section=source['member'].rsplit('/',1);member=capture.index_sections(sections[opname])[section];self.assertEqual(hashlib.sha256(member).hexdigest(),source['member_sha256'])
                parsed=capture.dialog_parameters(member);expected=copy.deepcopy(op['parameters'])
                for fields in (parsed,expected):
                    for field in fields.values():field['flags']=sorted(field['flags'])
                self.assertEqual(parsed,expected)
        if missing:
            self.skipTest('NOT_RUN: original vendor archives unavailable: '+'; '.join(sorted(missing)))

    def test_same_version_metadata_all_target_fields_types_menus_and_frozen_contract(self):
        contract=ROOT/'docs/native-basis/crowd-hair-native-followup.json'
        contract_bytes=contract.read_bytes()
        self.assertEqual(hashlib.sha256(contract_bytes).hexdigest(),'f136769086faecc3184a8733c10d034ed67700b25e6ee543d5b565c643fefeb2')
        self.assertEqual(hashlib.sha256(FACTS_PATH.read_bytes()).hexdigest(),'16d1c1c14527e66ad2e4c6aee23c15e8e89d978e5a0639f686dc8911e1252ee6')
        followup=json.loads(contract_bytes)
        for version in plans.VERSIONS:
            for pack in (plans.HAIR,plans.CROWD):
                for node in plans.node_requirements(pack,version):
                    role=node['role']; key=role+'_'+('hair' if pack==plans.HAIR else 'crowd') if role in ('source','solver') else role
                    if key not in ROLE_OPS:
                        continue
                    fields=FACTS[version][ROLE_OPS[key]]['parameters']
                    for aliases in node['required_parms']:
                        self.assertTrue(any(p in fields for p in aliases),(version,role,aliases))
                obs=contexts(pack)
                writes=plans.trusted_initialization_plan(pack,version,fresh=True,observations=obs,root_fact=root_fact())
                for w in writes:
                    key=w['role']+'_'+('hair' if pack==plans.HAIR else 'crowd') if w['role'] in ('source','solver') else w['role']
                    if key not in ROLE_OPS:
                        self.assertEqual(w['role'],'bullet');continue
                    fields=FACTS[version][ROLE_OPS[key]]['parameters']
                    parm=w['parm']; template=next((t for t in fields if '#' in t and parm in [t.replace('#',str(i)) for i in (4,7)]),parm)
                    f=fields[template]; self.assertEqual((w.get('native_ui_type',w['native_type']),w['size']),(f['type'],f['size']),(w['role'],parm))
                    if w['native_type']=='ordinal' and not w.get('require_actual_menu_token'):
                        self.assertIn(str(w['value']),f['menu_tokens'][::2])
        self.assertIn('Generate unguided hair of this length.','\n'.join(item['text'] for item in followup['versions']['21.0.631']['node_help']['sop/hairgen.txt']))
        thickness_bytes=(ROOT/'docs/native-basis/vellum-thickness-radius-static.json').read_bytes()
        self.assertEqual(hashlib.sha256(thickness_bytes).hexdigest(),'64f9bf4f360eb3d9f202c2174b8dd1962c70ef31debfda6108528966235a0a25')
        thickness=json.loads(thickness_bytes)
        source=next(item for item in thickness['versions']['22.0.429']['source_refs'] if item['member']=='sop/vellumconstraints.txt')
        self.assertIn('stored in `pscale`','\n'.join(item['text'] for item in source['lines']))

    def test_public_controls_preserved_and_full_native_topologies_have_exact_ports(self):
        for version in plans.VERSIONS:
            for pack in (plans.HAIR,plans.CROWD):
                original=get_domain_pack(pack).to_dict(); before=copy.deepcopy(original)
                overlay=plans.overlay_core_pack_dict(original,version)
                self.assertEqual(original,before)
                self.assertEqual({c['id'] for c in original['controls']},{c['id'] for c in overlay['controls']})
                edges={(e['source_role'],e['source_output'],e['destination_role'],e['destination_input']) for e in overlay['connections']}
                nodes={n['role']:n for n in overlay['nodes']}
                if pack==plans.HAIR:
                    for edge in [('guide_seed',0,'guides',0),('source',0,'guides',1),('source',0,'hair',0),('solver',0,'hair',1),('constraints',0,'solver',0),('constraints',1,'solver',1),('collision_transform',0,'solver',2),('guide_length',0,'hair_clump',0)]:self.assertIn(edge,edges)
                    self.assertNotIn(('source',0,'guides',0),edges)
                    self.assertEqual(nodes['hair_clump']['type_candidates'],['hairclump::2.0'])
                else:
                    for edge in [('population',0,'solver',1),('states',0,'route',0),('route',0,'solver',2),('transitions',0,'solver',3),('crowd_object',0,'active_collisions',0),('active_collisions',0,'multisolver',0),('solver',0,'multisolver',1),('bullet',0,'multisolver',2),('merge_solvers',0,'gravity',0),('gravity',0,'dop_output',0),('agent_definition',0,'source',0),('positions',0,'source',1),('import_geometry',0,'output',0)]:self.assertIn(edge,edges)
                    self.assertEqual(nodes['solver']['category'],'dop')
                    self.assertEqual(nodes['solver']['context_parent_role'],'dop_network')
                    self.assertNotIn(('source',0,'solver',0),edges)
                bad=copy.deepcopy(original);bad['controls'].pop()
                with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'PUBLIC_CONTROL_CONTRACT_CHANGED'):plans.overlay_core_pack_dict(bad,version)
                self.assertFalse(overlay['native_execution'])

    def test_actual_multiparm_instance_and_curve_first_vertices_are_required(self):
        obs=contexts(plans.HAIR)
        writes=plans.control_write_plan(plans.HAIR,'guide_length',.4,'21.0.631',observations=obs)
        self.assertEqual(writes[1]['parm'],'setlength_length7')
        self.assertNotIn('setlength_length1',[w['parm'] for w in writes])
        actual=applied_observations(plans.HAIR,writes,obs);plans.validate_applied_readback(writes,actual)
        actual[('guide_length','active7')]['value']=0
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'NATIVE_CONTROL_GATE_BLOCKED'):plans.validate_control_write_plan(writes,actual)
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'ACTUAL_MULTIPARM_BINDING_REQUIRED'):plans.control_write_plan(plans.HAIR,'guide_length',.4,'21.0.631')
        guard=plans.root_binding_plan(root_fact());self.assertEqual(guard['point_group'],'1 4')
        plans.validate_root_binding(guard,root_fact())
        changed=root_fact();changed['geometry_sha256']='c'*64
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'GUIDE_ROOT_GEOMETRY_CHANGED'):plans.validate_root_binding(guard,changed)
        for bad in [dict(root_fact(),curves=[]),dict(root_fact(),curves=[dict(kind='polygon',closed=True,point_numbers=[0,1,2])]),dict(root_fact(),curves=[dict(kind='open_curve',closed=False,point_numbers=[0,'roots'])])]:
            with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'ACTUAL_NONEMPTY_GUIDE_CURVES_REQUIRED'):plans.root_binding_plan(bad)
        source_init=plans.trusted_initialization_plan(plans.HAIR,'21.0.631',fresh=True,observations=obs,stage='source')
        self.assertTrue(all(w['role'] in {'guide_seed','guides','guide_length','hair_clump'} for w in source_init))
        simulation_init=plans.trusted_initialization_plan(plans.HAIR,'21.0.631',fresh=True,observations=obs,stage='simulation',root_fact=root_fact())
        self.assertTrue(all(w['role'] in {'constraints','solver','hair'} for w in simulation_init))
        init=plans.trusted_initialization_plan(plans.HAIR,'21.0.631',fresh=True,observations=obs,root_fact=root_fact())
        self.assertEqual(next(w['value'] for w in init if w['parm']=='pingroup'),'1 4')
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'FRESH_TASK_OWNED_NODES_REQUIRED'):plans.trusted_initialization_plan(plans.HAIR,'21.0.631',observations=obs,root_fact=root_fact())

    def test_all_hair_controls_joint_writes_conversion_and_actual_guards(self):
        controls=dict(guide_length=.4,guide_density=20,bend_stiffness=1000,damping=2,clump=.2,collision_radius=.02,clump_strength=.7,wind_strength=-3,hair_width=.01)
        obs=contexts(plans.HAIR);writes=plans.candidate_write_plan(plans.HAIR,controls,'22.0.429',observations=obs)
        values={(w['role'],w['parm']):w['value'] for w in writes}
        self.assertEqual(values[('constraints','bendstiffness')],1.)
        self.assertAlmostEqual(values[('hair_clump','tightness')],.007)
        self.assertEqual(plans.control_write_plan(plans.HAIR,'clump_strength',100,'21.0.631')[0]['value'],1.)
        self.assertEqual(values[('solver','wind')],[0.,0.,-1.]);self.assertEqual(values[('solver','windspeed')],3)
        self.assertEqual([values[(r,'density')] for r in ('guide_seed','guides','hair')],[20,20,20])
        self.assertEqual(values[('guides','width')],values[('hair','thickness')])
        self.assertIn(('constraints','bendstiffnessexp'),{(g['role'],g['parm']) for g in plans.immutable_readback_guards(writes)})
        actual=applied_observations(plans.HAIR,writes,obs);plans.validate_applied_readback(writes,actual)
        for name,value in controls.items():self.assertAlmostEqual(plans.native_control_value(plans.HAIR,name,values,'22.0.429',observations=actual),value)
        changed=copy.deepcopy(actual);changed[('constraints','bendstiffnessexp')]['value']=4
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'NATIVE_CONTROL_CONTEXT_CHANGED'):plans.validate_applied_readback(writes,changed)
        changed=copy.deepcopy(actual);changed[('guides','density')]['hidden']=True
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'NATIVE_CONTROL_GATE_BLOCKED'):plans.validate_control_write_plan(writes,changed)
        changed=copy.deepcopy(actual);changed[('hair','thickness')]['value']=.02
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'NATIVE_CONTROL_READBACK_MISMATCH'):plans.validate_applied_readback(writes,changed)
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'ACTUAL_COLLISION_RADIUS_CONVENTION_REQUIRED'):plans.control_write_plan(plans.HAIR,'collision_radius',.01,'21.0.631')
        changed=copy.deepcopy(actual);changed[('constraints','@geometry/0')]['point_attribute_values']['pscale'][0]=.1
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'ACTUAL_POINT_COLLISION_RADIUS_REQUIRED'):
            plans.native_control_value(plans.HAIR,'collision_radius',values,'22.0.429',observations=changed)
        for control in ('guide_density','guide_length'):
            self.assertTrue(all(w['value']==0 for w in plans.control_write_plan(plans.HAIR,control,0,'21.0.631',observations=obs)))
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'INVALID_NATIVE_CONTROL_VALUE'):plans.control_write_plan(plans.HAIR,'clump',float('nan'),'21.0.631')

    def test_crowd_source_velocity_actual_clip_timing_and_unproven_controls_block(self):
        obs=contexts(plans.CROWD)
        controls=dict(speed=2,speed_variance=.5,avoidance=2,avoidance_strength=2,behavior_variation=3,path_variance=3,behavior_mix=.8,animation_variation=20,clip_offset=-2,timing_offset=-2)
        writes=plans.candidate_write_plan(plans.CROWD,controls,'21.0.631',observations=obs)
        values={(w['role'],w['parm']):w['value'] for w in writes}
        self.assertEqual(values[('source','initialvel')],[0.,0.,-2.]);self.assertEqual(values[('source','randominitvel')],[0.,0.,-2.])
        self.assertEqual(values[('source','randominitveloffset')],[0.,0.,.5])
        self.assertEqual(values[('state','globalclipoffset')],10.5)
        self.assertFalse({'gaitspeed','speedvariance','agentspeed'}.intersection(w['parm'] for w in writes))
        actual=applied_observations(plans.CROWD,writes,obs);plans.validate_applied_readback(writes,actual)
        for name,value in controls.items():self.assertAlmostEqual(plans.native_control_value(plans.CROWD,name,values,'21.0.631',observations=actual),value)
        init=plans.trusted_initialization_plan(plans.CROWD,'21.0.631',fresh=True,observations=obs)
        self.assertEqual(next(w['value'] for w in init if w['parm']=='objname4'),'owned_crowd_object_2')
        self.assertEqual(next(w['value'] for w in init if w['parm']=='globalclipoffset'),12.5)
        self.assertEqual(next(w['value'] for w in init if w['parm']=='retimetoparticle'),0)
        self.assertEqual(next(w['value'] for w in init if w['parm']=='impulseactiveate'),'$SF==1')
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'CONFLICTING_NATIVE_CONTROLS'):plans.candidate_write_plan(plans.CROWD,dict(avoidance=2,avoidance_strength=3),'21.0.631')
        for control,code in [('animation_blend','ACTUAL_TRANSITION_CONTEXT_REQUIRED'),('route_weight','ACTUAL_ROUTE_BEHAVIOR_AND_GEOMETRY_REQUIRED')]:
            with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,code):plans.control_write_plan(plans.CROWD,control,1,'21.0.631')
        changed=copy.deepcopy(actual);changed[('agent_definition','@actual_clip')]['sample_rate']=24.
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'NATIVE_CONTROL_CONTEXT_CHANGED'):plans.validate_applied_readback(writes,changed)
        bad=copy.deepcopy(obs);bad[('agent_definition','@actual_clip')]['sample_rate']=0
        with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'INVALID_NATIVE_CONTROL_VALUE'):plans.control_write_plan(plans.CROWD,'clip_offset',1,'21.0.631',observations=bad)

    def test_lazy_exact_hom_hooks_and_saved_native_guards_are_not_runtime_acceptance(self):
        funcs={name:lambda *args,**kwargs:None for name in plans.HOM_HOOKS}
        with patch.object(plans.importlib,'import_module',return_value=SimpleNamespace(**funcs)) as load:
            self.assertEqual(plans.crowd_hom_hooks(),funcs);load.assert_called_once_with('houdini_bridge.crowd_helpers')
        with patch.object(plans.importlib,'import_module',side_effect=ModuleNotFoundError(name='houdini_bridge.crowd_helpers')):
            with self.assertRaisesRegex(plans.NativeCrowdHairDomainError,'CROWD_HOM_HELPER_NOT_INTEGRATED'):plans.crowd_hom_hooks()
        recipe=plans.agent_recipe_plan('22.0.429');clip=next(c for c in recipe['constructors'] if c['api']=='hou.AgentClip')
        self.assertEqual(clip['args'],['w5_loop','actual_rig',3]);self.assertEqual(clip['kwargs'],{})
        self.assertIn('sampleRate/startTime/length/sampleCount/localTransforms',recipe['timing'])
        self.assertIn('compare_agent_snapshots',recipe['save_reopen'])
        guards=plans.geometry_requirements(plans.CROWD,'21.0.631')
        self.assertTrue(next(g for g in guards if g['role']=='import_geometry')['actual_definition_pose_clip_and_output_port_readback'])
        self.assertTrue(next(g for g in plans.geometry_requirements(plans.HAIR,'21.0.631') if g['role']=='hair')['must_preserve_root_skin_binding'])
        references=plans.role_reference_plan(plans.CROWD,'21.0.631')
        self.assertEqual({r['parm']:r['native_type'] for r in references},{'soppath':'oppath','doppath':'oppath','dopnode':'oppath'})


if __name__=='__main__':unittest.main()
