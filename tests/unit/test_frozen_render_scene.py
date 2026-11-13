"""Frozen semantic parameters through the shipped generator/TCP/worker/save path.

Only bottom HOM/USD and native process launch are explicit Python substitutes.
These tests do not attest installed compiled templates, cooking or rendered pixels.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def file_manifest(path):
    raw=path.read_bytes()
    return [dict(index=0,asset_id='karma-static-scene',semantic_role='render_scene_configuration',
                 source_uri=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))]


class FrozenRenderSceneTests(unittest.TestCase):
    def test_profile_and_frozen_input_guards(self):
        from vfx_pipeline import graph_catalog
        # The original registered graph stays a distinct capability.
        base={'schema':'bridge.registered-domain-construction/1','domain_pack':'material_lookdev_v1','houdini_version':'21.0.631'}
        old=graph_catalog.compile_proposal(base)
        proposal={**base,'scene_profile':'sphere_ground_v2'}
        graph=graph_catalog.compile_proposal(proposal)
        self.assertNotEqual(old.graph_hash,graph.graph_hash)
        self.assertEqual(graph_catalog.registered_domain_identity(graph),proposal)
        self.assertTrue({'ground','ground_import','geometry_stage_merge','stage_metadata'} <= {n.node_id for n in graph.nodes})
        from vfx_pipeline.graph_construction_inputs import render_scene_configuration
        from houdini_bridge.native_render_scene import validate_configuration,parameter_plan
        source=ROOT/'docs/official-baselines/karma/frozen-scene-v2.json'
        config=render_scene_configuration(file_manifest(source))
        from dcc_task_runtime.canonical import canonical_sha256
        from vfx_pipeline.graph_job_worker import GraphJobWorker
        frozen=file_manifest(source)
        legacy=file_manifest(source.parent/'frozen-scene.json')
        for selector,inputs,accepted in [(proposal,frozen,True),(base,frozen,False),(proposal,[],False),
                ({**proposal,'scene_profile':'sphere_ground_v1'},frozen,False),(proposal,legacy,False),
                ({**proposal,'scene_profile':'sphere_ground_v1'},legacy,True),
                ({**proposal,'houdini_version':'22.0.429'},frozen,False)]:
            with self.subTest(selector=selector,inputs=bool(inputs)):
                worker=GraphJobWorker.__new__(GraphJobWorker)
                worker.domain_schedule={'identity':selector}
                worker.job={'frozen_input_manifest':inputs,'frozen_inputs_sha256':canonical_sha256(inputs)}
                if accepted:
                    worker._construction_inputs(worker.job)
                    self.assertEqual(worker.frozen_input_manifest,inputs)
                else:
                    with self.assertRaises(ValueError):worker._construction_inputs(worker.job)
        original=json.loads((source.parent/'rebuild-contract.json').read_text())
        self.assertEqual(config['scene'],original['proposed_scene'])
        self.assertEqual(config['source_contract_sha256'],hashlib.sha256((source.parent/'rebuild-contract.json').read_bytes()).hexdigest())
        for version in ('21.0.631','22.0.459'):
            compiled=graph_catalog.compile_proposal({**proposal,'houdini_version':version})
            self.assertEqual(graph_catalog.registered_domain_identity(compiled)['scene_profile'],'sphere_ground_v2')
            writes={(w['role'],w['parm']):w['value'] for w in parameter_plan(config,version)}
            self.assertEqual(writes['source','rad'],(.5,.5,.5))
            self.assertEqual(writes['camera','lookatposition'],(0,.5,0))
            self.assertEqual(writes['settings','resolution'],(128,128))
        for kind in ('bool_radius','extra_path','bad_resolution','wrong_version','nan','zero_look_at'):
            bad=copy.deepcopy(config)
            if kind=='bool_radius':bad['scene']['sphere']['radius']=True
            elif kind=='extra_path':bad['executable']='/tmp/tool'
            elif kind=='bad_resolution':bad['scene']['resolution']=[129,128]
            elif kind=='wrong_version':bad['supported_versions']=['22.0.429']
            elif kind=='nan':bad['scene']['light']['radius']=float('nan')
            else:bad['scene']['camera']['look_at']=bad['scene']['camera']['position']
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_configuration(bad)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scene.json';path.write_bytes(source.read_bytes())
            frozen=file_manifest(path)
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'changed'):render_scene_configuration(frozen)
            path.write_text('{"schema":"x","schema":"y"}')
            with self.assertRaisesRegex(ValueError,'duplicate'):render_scene_configuration(file_manifest(path))
            path.write_bytes(b'\xff')
            with self.assertRaisesRegex(ValueError,'verification'):render_scene_configuration(file_manifest(path))

    def test_plan_normalizes_only_declared_floats_without_changing_frozen_input(self):
        from houdini_bridge.native_render_scene import parameter_plan
        for filename in ("frozen-scene.json", "frozen-scene-v2.json"):
            config = json.loads((ROOT / "docs/official-baselines/karma" / filename).read_text())
            config["scene"]["camera"]["position"] = [3, 2, 4]
            config["scene"]["camera"]["focal_length_mm"] = 50
            config["scene"]["material"]["semantic_base_color"] = [0, 1, 0]
            before = copy.deepcopy(config)
            encoded = json.dumps(config, sort_keys=True)
            for version in ("21.0.631", "22.0.459"):
                plan = parameter_plan(config, version)
                for write in plan:
                    value, kind = write["value"], write["native_type"]
                    with self.subTest(profile=filename, version=version, parameter=write["parm"]):
                        if kind == "float": self.assertIs(type(value), float)
                        elif kind in {"vector3", "color3"}:
                            self.assertIs(type(value), tuple)
                            self.assertTrue(all(type(item) is float for item in value))
                        elif kind == "intvector2": self.assertTrue(all(type(item) is int for item in value))
                        elif kind in {"integer", "toggle"}: self.assertIs(type(value), int)
                        elif kind in {"menu", "string"}: self.assertIs(type(value), str)
                camera = next(write["value"] for write in plan if (write["role"], write["parm"]) == ("camera", "t"))
                self.assertEqual(camera, (3.0, 2.0, 4.0))
                self.assertEqual(config, before)
                self.assertEqual(json.dumps(config, sort_keys=True), encoded)
            for invalid in (True, float("nan"), float("inf"), float("-inf")):
                for field in ("scalar", "vector"):
                    bad = copy.deepcopy(config)
                    if field == "scalar": bad["scene"]["camera"]["focal_length_mm"] = invalid
                    else: bad["scene"]["camera"]["position"][0] = invalid
                    with self.subTest(invalid=invalid, field=field), self.assertRaises(ValueError):
                        parameter_plan(bad, "21.0.631")
            for invalid in (128.0, True):
                bad = copy.deepcopy(config)
                bad["scene"]["resolution"][0] = invalid
                with self.subTest(resolution=invalid), self.assertRaises(ValueError):
                    parameter_plan(bad, "21.0.631")

    def test_generated_entry_build_feedback_and_new_host_readback(self):
        import test_production_task_hosts as fixture
        from prepare_workbuddy_graph import prepare_graph
        from vfx_pipeline.production_hosts import stop_hosts
        from vfx_pipeline.workbuddy_assembly import production_host_client
        helper=fixture.ProductionTaskHostsTests()
        retained=os.environ.get('BRIDGE_FROZEN_SCENE_EVIDENCE_DIR')
        for version,profile in [('21.0.631','sphere_ground_v2'),('22.0.459','sphere_ground_v2'),('21.0.631','sphere_ground_v1')]:
            with self.subTest(version=version,profile=profile),tempfile.TemporaryDirectory(prefix='frozen-scene-') as temp:
                base=Path(temp).resolve();project=base/'project';api=base/'api';api.mkdir()
                (api/'nuke.py').write_text(fixture.FAKE)
                native=fixture.STRICT_RENDER_NATIVE.replace('api.interface_profiles(native_root,version)','api.static_scene_interface_profiles(native_root,version)')
                native=native.replace('api.install_stage_api(hou)', 'api.install_stage_api(hou);api.install_material_binding_api()')
                native += """
original_stage=api.Stage
class FaultableStage(original_stage):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        fault=Path(os.environ['BRIDGE_TEST_USD_BINDING_FAULT'])
        if fault.is_file():
            request=json.loads(fault.read_text())
            if request['action']=='drop':
                self.prims={path:prim for path,prim in self.prims.items() if path!=request['prim_path'] and not path.startswith(request['prim_path']+'/')}
            elif request['action']=='binding':
                prim=self.GetPrimAtPath(request['prim_path'])
                if prim is None:raise ValueError('fault injection target does not exist')
                prim.relations['material:binding']=request['targets']
            else:raise ValueError('unsupported bottom USD fault')
api.Stage=FaultableStage
"""
                script=base/'python-hom.py'
                script.write_text(fixture.HYTHON.replace("sys.modules['houdini_bridge_addon']=addon", "sys.modules['houdini_bridge_addon']=addon\n"+native))
                config=base/'scene.json';config.write_bytes((ROOT/'docs/official-baselines/karma'/('frozen-scene-v2.json' if profile=='sphere_ground_v2' else 'frozen-scene.json')).read_bytes())
                h=helper.config(project,'houdini',script,api);h.update(version=version,session_seconds=120)
                n=helper.config(project,'nuke',fixture.SOFTWARE_PYTHON,api);n['session_seconds']=120
                environment={'BRIDGE_TEST_NATIVE_ROOT':str(ROOT),'BRIDGE_TEST_NATIVE_VERSION':version,
                    'HOUDINI_BRIDGE_STATE_DIR':str(project/'bridge-state'),'BRIDGE_SKILLS_STATE_ROOT':str(project/'runtime-state'),
                    'BRIDGE_TEST_USD_BINDING_FAULT':str(base/'usd-fault.json')}
                process=None
                with patch.dict(os.environ,environment):
                    try:
                        prepare_graph(project,app=None,scheduler_root=project/'scheduler',execution_profile=True,
                            production_host_config=h,production_nuke_config=n,construction_input_manifest=file_manifest(config))
                        process=helper.boot(project)
                        for index,asset in enumerate(helper.tool(process,'catalog',{})['assets']):
                            helper.tool(process,'submit_observation',{'asset_id':asset['asset_id'],'request_id':'obs-'+str(index),
                                'observation':{'description':'synthetic neutral sphere reference','dominant_colors':['grey']}})
                        proposal={'schema':'bridge.registered-domain-construction/1','domain_pack':'material_lookdev_v1',
                                  'houdini_version':version,'scene_profile':profile}
                        mismatched={**proposal,'scene_profile':'sphere_ground_v1' if profile=='sphere_ground_v2' else 'sphere_ground_v2'}
                        mismatch=helper.tool(process,'graph_propose',{'proposal':mismatched,'request_id':'propose-mismatch'})
                        self.assertTrue(mismatch.get('isError'),mismatch)
                        graph=helper.tool(process,'graph_propose',{'proposal':proposal,'request_id':'propose'})
                        self.assertIn('graph_id',graph,graph)
                        trial=helper.completed_graph_trial(process,project,{'graph_id':graph['graph_id'],'request_id':'build'})
                        errors=[str(p.relative_to(project))+': '+p.read_text(errors='replace')[-6000:] for name in ('error.txt','result.json') for p in project.rglob(name)]
                        if trial.get('state')!='SUCCEEDED':
                            import sqlite3
                            for journal in project.rglob('journal.sqlite3'):
                                with sqlite3.connect(journal) as db:
                                    errors.extend(row[0] for row in db.execute('SELECT payload FROM entries') if json.loads(row[0]).get('status')!='COMPLETE')
                        self.assertEqual(trial.get('state'),'SUCCEEDED',str(trial)+'\n'+'\n'.join(errors))
                        self.assertRegex(trial['result']['verification']['registered_scene_contract_sha256'],r'^[0-9a-f]{64}$')
                        initial_save=helper.tool(process,'task_save',{})
                        self.assertIn('scene_contract',initial_save,initial_save)
                        initial=initial_save['scene_contract']['frozen_scene_parameters']
                        self.assertEqual(initial['fields']['source.rad'],[.5,.5,.5])
                        self.assertEqual(initial['fields']['source.t'],[0,.5,0])
                        self.assertEqual(initial['fields']['camera.t'],[3,2,4])
                        self.assertEqual(initial['fields']['light.lighttype'],'UsdLuxDiskLight')
                        self.assertEqual(initial['fields']['settings.resolution'],[128,128])
                        self.assertEqual(initial['fields']['material.base_color'],[.18,.18,.18])
                        self.assertEqual(initial['stage_metadata'],{'upAxis':'Y','metersPerUnit':1.0})
                        self.assertFalse(initial['native_geometry_validated']);self.assertFalse(initial['render_executed'])
                        if profile=='sphere_ground_v2':
                            self.assertEqual(set(initial['geometry']),{'Sphere','Ground'})
                            sphere,ground=(initial['geometry'][name] for name in ('Sphere','Ground'))
                            self.assertNotEqual(sphere['source_node_path'],ground['source_node_path'])
                            self.assertNotEqual(sphere['import_node_path'],ground['import_node_path'])
                            prim_sets=[]
                            for name,geometry in initial['geometry'].items():
                                self.assertTrue(geometry['prim_prefix'].endswith('/Geometry/'+name))
                                self.assertTrue(geometry['resolved_prims'])
                                prim_sets.append({item['prim_path'] for item in geometry['resolved_prims']})
                                for item in geometry['resolved_prims']:
                                    self.assertTrue(item['prim_path'].startswith(geometry['prim_prefix']+'/'))
                                    self.assertTrue(item['material_prim_path'].endswith('/Materials/lookdev'))
                            self.assertFalse(prim_sets[0]&prim_sets[1])
                        else:
                            self.assertNotIn('geometry',initial)
                            # 36 frozen fields + settings_binding res_mode/resolution (the rendersettings
                            # LOP's factory 2048x1080/autoheight otherwise overrides the karma settings
                            # prim during composition; see ITERATION26/27).
                            self.assertEqual(len(initial['fields']),40)
                        state=json.loads((project/'control/production-hosts.json').read_text());task=state['task_id']
                        changed=helper.tool(process,'feedback_edit',{'graph_id':graph['graph_id'],'node_id':'material',
                            'parms':{'base_color':[.5,.18,.18]},'task_id':task})
                        self.assertFalse(changed.get('isError'),changed)
                        saved=helper.tool(process,'task_save',{});self.assertIn('saved_scene_id',saved,saved)
                        helper.close(process);process=None
                        stops=stop_hosts(project/'control');self.assertTrue(stops['houdini']['receipt']['confirmed_exit'])
                        old=state['hosts']['houdini']['expected_identity']
                        process=helper.boot(project)
                        reopened=helper.tool(process,'task_reopen',{'saved_scene_id':saved['saved_scene_id']})
                        self.assertTrue(reopened.get('parameters_verified'),reopened)
                        observed=reopened['frozen_scene_parameters']
                        self.assertEqual(observed['configuration_sha256'],initial['configuration_sha256'])
                        self.assertEqual(observed['fields']['material.base_color'],[.5,.18,.18])
                        for field,value in initial['fields'].items():
                            if field!='material.base_color':self.assertEqual(observed['fields'][field],value,field)
                        self.assertEqual(observed.get('geometry'),initial.get('geometry'))
                        state=json.loads((project/'control/production-hosts.json').read_text())
                        self.assertNotEqual(state['hosts']['houdini']['expected_identity']['launch_nonce'],old['launch_nonce'])
                        # A direct field drift must be caught before a new saved receipt is accepted.
                        host=production_host_client(state['hosts']['houdini'],project/'readback-client');host.bind_task(task)
                        roles={a.rsplit('/',1)[-1]:p for a,p in trial['result']['topology']['nodes'].items()}
                        fault_path=base/'usd-fault.json';fault_refusals=[]
                        wrong_source=None
                        if profile=='sphere_ground_v2':
                            for corruption in [{'action':'drop','prim_path':ground['prim_prefix']},
                                    {'action':'binding','prim_path':ground['resolved_prims'][0]['prim_path'],
                                     'targets':[ground['prim_prefix']+'/MissingMaterial']}]:
                                fault_path.write_text(json.dumps(corruption))
                                denied=helper.tool(process,'task_save',{})
                                self.assertTrue(denied.get('isError'),denied)
                                self.assertIn('GRAPH_CONTRACT_UNVERIFIED',denied['text'])
                                fault_refusals.append({'fault':corruption,'refusal':denied})
                                fault_path.unlink()
                            host.call('node.set_parms',{'path':roles['ground_import'],'parms':{'soppath':roles['source']}})
                            wrong_source=helper.tool(process,'task_save',{})
                            self.assertTrue(wrong_source.get('isError'),wrong_source)
                            self.assertIn('PARAMETER_READBACK_MISMATCH',wrong_source['text'])
                            host.call('node.set_parms',{'path':roles['ground_import'],'parms':{'soppath':roles['ground']}})
                        host.call('node.set_parms',{'path':roles['camera'],'parms':{'focalLength':35.}})
                        refused=helper.tool(process,'task_save',{})
                        self.assertTrue(refused.get('isError'),refused)
                        if retained:
                            out=Path(retained);out.mkdir(parents=True,exist_ok=True)
                            (out/(version+'-'+profile+'.json')).write_text(json.dumps({'evidence_source':'explicit_software_hom_usd',
                                'compiled_native_basis_complete':False,'real_host_started':False,
                                'trial':{key:trial[key] for key in ('graph_id','operation_id','state')},
                                'trial_verification':trial['result']['verification'],
                                'initial_readback':initial,'saved_readback':saved['scene_contract']['frozen_scene_parameters'],
                                'saved_scene_contract_sha256':saved['scene_contract_sha256'],
                                'reopened_readback':observed,'old_identity':old,
                                'new_identity':state['hosts']['houdini']['expected_identity'],
                                'old_process_stop_confirmed':stops['houdini']['receipt']['confirmed_exit'],
                                'usd_fault_refusals':fault_refusals,'wrong_source_refusal':wrong_source,'drift_refusal':refused},ensure_ascii=False,indent=2)+'\n')
                    finally:
                        if process is not None:helper.close(process)
                        if (project/'control/production-hosts.json').is_file():stop_hosts(project/'control')
