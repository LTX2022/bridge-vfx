from pathlib import Path
from types import SimpleNamespace
import importlib.util
import copy
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import call, patch
from vfx_pipeline.workbuddy_assembly import software_host_client
from vfx_pipeline.domain_readiness import DomainReadinessRunner
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_schema_test_boundary',ROOT/'tools/native_schema_test_boundary.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)

def _feedback_takeover_cas(pipe, root, addon_path):
    """Use the production CAS, observing its actual platform lock acquisition."""
    import errno
    from dcc_task_runtime import platform_support
    spec=importlib.util.spec_from_file_location('feedback_new_host',addon_path)
    addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
    identity=addon._host_identity();lease=addon._root_lease_read(root)
    lease.update(owner_generation=identity['process_generation'],
        owner_session_id=identity['session_id'],scene_epoch=identity['scene_epoch'])
    original=platform_support.lock_file
    observed=[False]
    def attempt(fd, blocking=True):
        if blocking and not observed[0]:
            observed[0]=True
            try:
                original(fd,blocking=False)
            except OSError as exc:
                if exc.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):
                    raise
                pipe.send({'kind':'cas_lock_attempt','blocked':True})
                return original(fd,blocking=blocking)
            pipe.send({'kind':'cas_lock_attempt','blocked':False})
            return
        return original(fd,blocking=blocking)
    try:
        with patch.object(platform_support,'lock_file',attempt):
            updated=addon._root_lease_write(root,lease,expect_version=int(lease['version']))
        pipe.send({'kind':'takeover_committed','identity':identity,'lease':updated})
    except Exception as exc:
        pipe.send({'kind':'error','detail':repr(exc)})
    finally:
        pipe.close()

class NativeDomainGraphTests(unittest.TestCase):
    def test_feedback_validation_transaction_fences_cross_process_takeover(self):
        spec=importlib.util.spec_from_file_location('feedback_software_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version,domain in ((v,d) for v in ('21.0.631','22.0.429') for d in ('water_ocean_v1','hair_fur_v1')):
            with self.subTest(version=version,domain=domain),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                        instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    hou=sys.modules['hou'];api.install_stage_api(hou)
                    task='feedback-fence'
                    params={'task_id':task,'constraints':{'fx':{'domain_pack':domain,'run_mode':'diagnose','frames':[1,2]}},
                        'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    roles=client.call('agent.fx.build_preview',params)['scene_manifest']['nodes']
                    root,manifest=addon._fx_manifest(task);old=addon._host_identity()
                    lease_before=addon._root_lease_read(root.path())
                    entered,resume=threading.Event(),threading.Event()
                    original_prepared=addon._fx_planned_domain_prepared
                    native_parm=hou.node(roles['spectrum' if domain=='water_ocean_v1' else 'guide_seed']).parm('ampscale' if domain=='water_ocean_v1' else 'unguidedlength')
                    original_set=type(native_parm).set
                    writes=[];paused=[False];outcome={}
                    def validated(*args,**kwargs):
                        result=original_prepared(*args,**kwargs)
                        if not paused[0]:
                            paused[0]=True;entered.set()
                            if not resume.wait(15):raise AssertionError('validation barrier not resumed')
                        return result
                    def record_write(parm,value,**kwargs):
                        lease=addon._root_lease_read(root.path())
                        writes.append({'parameter':parm.path(),'owner':lease['owner_generation']})
                        return original_set(parm,value,**kwargs)
                    def feedback():
                        try:outcome['result']=client.call('agent.fx.apply_candidate',params)
                        except Exception as exc:outcome['error']=repr(exc)
                    params['constraints']['fx']['changes']=({'wave_scale':2.,'foam_amount':3.,'foam':True} if domain=='water_ocean_v1' else {'guide_length':.4,'collision_radius':.02,'wind_strength':3.})
                    ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
                    process=ctx.Process(target=_feedback_takeover_cas,args=(child,root.path(),str(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py')))
                    thread=threading.Thread(target=feedback,daemon=True)
                    with patch.object(addon,'_fx_planned_domain_prepared',validated),patch.object(type(native_parm),'set',record_write):
                        try:
                            thread.start();self.assertTrue(entered.wait(15),outcome)
                            process.start();child.close()
                            self.assertTrue(parent.poll(15),'takeover did not reach actual lease CAS lock')
                            attempted=parent.recv()
                            transferred=None
                            if attempted.get('blocked') is False:
                                self.assertTrue(parent.poll(15),'unfenced takeover did not finish')
                                transferred=parent.recv()
                            resume.set();thread.join(15);self.assertFalse(thread.is_alive())
                            if transferred is None:
                                self.assertTrue(parent.poll(15),'takeover did not complete after feedback finished')
                                transferred=parent.recv()
                            process.join(15);self.assertFalse(process.is_alive())
                        finally:
                            resume.set();thread.join(15)
                            if process.pid and process.is_alive():process.terminate();process.join(5)
                            parent.close();child.close()
                    evidence=os.environ.get('BRIDGE_LEASE_FENCE_EVIDENCE_DIR')
                    if evidence:
                        target=Path(evidence)/version/domain;target.mkdir(parents=True,exist_ok=True)
                        (target/'transaction-before-assertions.json').write_text(json.dumps({'attempt':attempted,'takeover':transferred,'old_identity':old,'lease_before':lease_before,'writes':writes,'feedback':outcome},indent=2)+'\n')
                    self.assertEqual(attempted,{'kind':'cas_lock_attempt','blocked':True})
                    self.assertEqual(transferred['kind'],'takeover_committed',transferred)
                    self.assertEqual(process.exitcode,0)
                    self.assertIn('result',outcome,outcome)
                    self.assertTrue(writes)
                    self.assertEqual({w['owner'] for w in writes},{old['process_generation']})
                    self.assertNotEqual(transferred['identity']['process_generation'],old['process_generation'])
                    current=addon._root_lease_read(root.path())
                    self.assertEqual(current['owner_generation'],transferred['identity']['process_generation'])
                    self.assertEqual(current['version'],lease_before['version']+1)
                    state_path=addon._fx_state_path(task)
                    frozen_bytes=state_path.read_bytes();frozen_data=root.userData('bridge_fx_manifest_v1')
                    frozen_parameters={p:tuple((parm.name(),addon._fx_scene_parameter_readback(parm)) for parm in hou.node(p).parms()) for p in roles.values()}
                    with self.assertRaises(addon.BridgeCommandError) as stale:
                        client.call('agent.fx.apply_candidate',params)
                    self.assertEqual(stale.exception.code,'GENERATION_TAKEOVER')
                    self.assertEqual(state_path.read_bytes(),frozen_bytes)
                    self.assertEqual(root.userData('bridge_fx_manifest_v1'),frozen_data)
                    self.assertEqual({p:tuple((parm.name(),addon._fx_scene_parameter_readback(parm)) for parm in hou.node(p).parms()) for p in roles.values()},frozen_parameters)
                    evidence=os.environ.get('BRIDGE_LEASE_FENCE_EVIDENCE_DIR')
                    if evidence:
                        target=Path(evidence)/version/domain;target.mkdir(parents=True,exist_ok=True)
                        (target/'transaction-takeover.json').write_text(json.dumps({'attempt':attempted,'takeover':transferred,'old_identity':old,'writes':writes,'feedback':outcome,'stale_request_rejected':True,'parameter_and_manifest_bytes_unchanged_after_takeover':True},indent=2)+'\n')

    def test_crowd_route_actual_curve_native_context_feedback_and_rollback(self):
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        api=load('crowd_route_api',ROOT/'tools/software_render_api_boundary.py')
        agent=load('crowd_route_geometry_api',ROOT/'tools/software_agent_api_boundary.py')
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                        instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    hou=sys.modules['hou'];hou._software_agent_api_state={'origin':'test_injected_native_api','clip_sample_rate':30.7,'clip_start_time':12.5}
                    agent.install_agent_api(hou);api.install_stage_api(hou)
                    params={'task_id':'crowd-route','constraints':{'fx':{'domain_pack':'crowd_agents_v1','run_mode':'diagnose','frames':[1,2]}},
                        'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    roles=client.call('agent.fx.build_preview',params)['scene_manifest']['nodes']
                    route=hou.node(roles['route']);solver=hou.node(roles['solver'])
                    self.assertIs(route.input(0),hou.node(roles['states']))
                    self.assertIs(solver.input(2),route)
                    def apply(value):
                        params['constraints']['fx']['changes']={'route_weight':value}
                        return client.call('agent.fx.apply_candidate',params)
                    result=apply(75.)
                    context=result['native_geometry_readback']['route_context']
                    self.assertEqual(tuple(map(tuple,context['curve']['points'])),((0.,0.,0.),(4.,0.,0.),(8.,0.,3.)))
                    self.assertEqual(tuple(context['curve']['vertices']),(0,1,2))
                    self.assertEqual(context['curve']['primitive_count'],1)
                    self.assertEqual(route.parm('weight').eval(),75.)
                    for boundary in (0.,100.):self.assertEqual(apply(boundary)['native_geometry_readback']['route_readback']['route_weight'],boundary)
                    transition=hou.node(roles['transition']);trigger=hou.node(roles['trigger'])
                    self.assertIs(transition.input(0),trigger)
                    self.assertIs(hou.node(roles['transitions']).input(0),transition)
                    self.assertIs(solver.input(3),hou.node(roles['transitions']))
                    self.assertIs(hou.node(roles['states']).input(1),hou.node(roles['target_state']))
                    def blend(value):
                        params['constraints']['fx']['changes']={'animation_blend':value}
                        return client.call('agent.fx.apply_candidate',params)
                    for duration in (0.,1.25,10.):
                        changed=blend(duration)
                        self.assertEqual(changed['native_geometry_readback']['transition_readback']['animation_blend'],duration)
                        native_context=changed['native_geometry_readback']['transition_context']
                        snapshot=json.loads(native_context['geometry']['snapshot_json'])
                        clips=snapshot['content']['agents'][0]['clips']
                        self.assertEqual([c['name'] for c in clips],['w5_loop','w5_transition'])
                        self.assertNotEqual(clips[0]['local_samples'],clips[1]['local_samples'])
                        ramp=transition.parm('blend').evalAsRamp()
                        self.assertEqual(tuple(ramp.keys()),(0.,1.));self.assertEqual(tuple(ramp.values()),(0.,1.))
                    curve_node=hou.node(roles['route_curve'])
                    actual_snapshot=addon._fx_crowd_curve_stash_snapshot(curve_node,'crowd-route')
                    self.assertEqual(actual_snapshot['geometry_sha256'],context['curve']['geometry_sha256'])
                    with self.assertRaises(addon.BridgeCommandError):addon._fx_crowd_curve_stash_snapshot(curve_node,'foreign-task')
                    stored_curve=curve_node.parm('stash').evalAsGeometry()
                    bad_curve=hou.Geometry();polygon=bad_curve.createPolygon(is_closed=False)
                    for position in ((0.,0.,0.),(2.,0.,0.),(3.,0.,1.)):
                        point=bad_curve.createPoint();point.setPosition(position);polygon.addVertex(point)
                    curve_node.parm('stash').set(bad_curve)
                    with self.assertRaises(addon.BridgeCommandError):addon._fx_crowd_curve_stash_snapshot(curve_node,'crowd-route')
                    with self.assertRaises(addon.BridgeCommandError):apply(20.)
                    curve_node.parm('stash').set(stored_curve)
                    root,manifest=addon._fx_manifest('crowd-route')
                    def state():return (route.parm('weight').eval(),transition.parm('duration').eval(),root.userData('bridge_fx_manifest_v1'),addon._fx_state_path('crowd-route').read_bytes())
                    frozen=state();original=addon._fx_write_state
                    def fail(task,value):original(task,value);raise OSError('injected route manifest failure')
                    with patch.object(addon,'_fx_write_state',fail),self.assertRaisesRegex(addon.BridgeCommandError,'route manifest failure'):apply(33.)
                    self.assertEqual(state(),frozen)
                    with patch.object(addon,'_fx_write_state',fail),self.assertRaisesRegex(addon.BridgeCommandError,'route manifest failure'):blend(2.)
                    self.assertEqual(state(),frozen)
                    hou.node(roles['states']).setInput(1,None)
                    foreign_transition=state()
                    with self.assertRaises(addon.BridgeCommandError):blend(2.)
                    self.assertEqual(state(),foreign_transition);hou.node(roles['states']).setInput(1,hou.node(roles['target_state']))
                    transition.parm('blend').set(hou.Ramp((hou.rampBasis.Linear,hou.rampBasis.Linear),(0.,1.),(.1,1.)))
                    with self.assertRaises(addon.BridgeCommandError):blend(2.)
                    self.assertEqual(state(),frozen)
                    transition.parm('blend').set(hou.Ramp((hou.rampBasis.Linear,hou.rampBasis.Linear),(0.,1.),(0.,1.)))
                    route.parm('soppath').set(roles['positions']);foreign=state()
                    with self.assertRaises(addon.BridgeCommandError):apply(20.)
                    self.assertEqual(state(),foreign)
                    route.parm('soppath').set(roles['route_curve'])
                    solver.setInput(2,hou.node(roles['states']))
                    with self.assertRaises(addon.BridgeCommandError):apply(20.)
                    self.assertEqual(state(),frozen)
                    solver.setInput(2,route)
                    evidence=os.environ.get('BRIDGE_CROWD_ROUTE_EVIDENCE_DIR')
                    if evidence:
                        target=Path(evidence)/version;target.mkdir(parents=True,exist_ok=True)
                        (target/'native-route.json').write_text(json.dumps({'context':context,'transition_context':native_context,'feedback':result,'transition_feedback':changed,
                            'manifest_failure_restored':True,'foreign_path_and_bypass_rejected':True,'native_execution':False},indent=2)+'\n')

    def test_ocean_actual_three_inputs_program_feedback_frames_and_fail_closed(self):
        spec=importlib.util.spec_from_file_location('ocean_software_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                        instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    hou=sys.modules['hou'];api.install_stage_api(hou)
                    params={'task_id':'ocean-transaction','constraints':{'fx':{'domain_pack':'water_ocean_v1','run_mode':'diagnose','frames':[1,2]}},
                        'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    roles=client.call('agent.fx.build_preview',params)['scene_manifest']['nodes']
                    stage=hou.node(roles['ocean_masks']);spectrum=hou.node(roles['spectrum']);emit=hou.node(roles['foam_emit'])
                    self.assertEqual([stage.input(i).path() for i in range(3)],[roles['evaluate'],roles['spectrum'],roles['source']])
                    def apply(changes):
                        params['constraints']['fx']['changes']=changes
                        result=client.call('agent.fx.apply_candidate',params)
                        self.assertEqual({diff['semantic_control'] for diff in result['parameter_diff']},set(changes))
                        return result
                    first=apply({'wave_scale':2.,'foam':True,'foam_amount':3.,'crest_threshold':.1})
                    self.assertIn('source_layout_control',first['invalidates_from'])
                    measured=first['native_geometry_readback'];attrs=measured['masked_geometry']['point_attributes']
                    self.assertEqual(measured['masked_geometry']['role'],'ocean_masks')
                    self.assertEqual(measured['masked_geometry']['polygons'],measured['context']['surface']['polygons'])
                    volumes=measured['context']['spectrum']['volumes']
                    self.assertEqual([v['name'] for v in volumes],['amplitude','phase','frequency'])
                    self.assertEqual(measured['registration']['observed_layers'],1)
                    self.assertTrue(all(v['storage']['voxel_count']==16 and v['storage']['precision']=='float32' for v in volumes))
                    self.assertGreater(max(attrs['foam_mask']['values']),0.)
                    self.assertEqual(measured['masked_geometry']['point_positions'],measured['context']['surface']['point_positions'])
                    self.assertEqual(apply({'foam':True})['native_geometry_readback']['masked_geometry'],measured['masked_geometry'])
                    changed=apply({'foam_amount':4.});self.assertTrue(any(d.get('dependent_semantic_control')=='foam' for d in changed['parameter_diff']))
                    self.assertEqual(changed['native_geometry_readback']['registration']['foam_amount_native_density'],4.)
                    self.assertNotEqual(changed['cache_subject_hash'],first['cache_subject_hash'])
                    _,updated=addon._fx_manifest('ocean-transaction')
                    self.assertNotIn('cache',updated)
                    self.assertEqual(changed['cache_approval_subject']['revision'],updated['revision'])
                    self.assertEqual(changed['cache_approval_subject']['candidate_patch'],updated['candidate_patch'])
                    self.assertEqual(apply({'foam':False})['native_geometry_readback']['masked_geometry']['point_attributes']['foam_mask']['values'],[0.]*len(attrs['foam_mask']['values']))
                    apply({'foam':True})
                    frames=client.call('agent.fx.collect_evidence',params)['evidence']['native_geometry_readback']
                    self.assertEqual(set(frames),{'1','2'})
                    self.assertNotEqual(frames['1']['context']['spectrum']['sample_time'],frames['2']['context']['spectrum']['sample_time'])
                    self.assertNotEqual(frames['1']['masked_geometry']['point_attributes']['bridge_ocean_cusp']['values'],frames['2']['masked_geometry']['point_attributes']['bridge_ocean_cusp']['values'])
                    self.assertEqual(frames['1']['registration']['sha256'],frames['2']['registration']['sha256'])
                    _,manifest=addon._fx_manifest('ocean-transaction');before=copy.deepcopy(manifest)
                    snapshot=(spectrum.parm('ampscale').eval(),emit.parm('density').eval(),stage.parm('snippet').eval())
                    original=type(stage.parm('snippet')).set;tripped=[False]
                    def fail_once(parm,value,**kwargs):
                        if parm.path()==stage.parm('snippet').path() and not tripped[0]:
                            tripped[0]=True;raise RuntimeError('injected ocean program write failure')
                        return original(parm,value,**kwargs)
                    with patch.object(type(stage.parm('snippet')),'set',fail_once),self.assertRaises(Exception):apply({'wave_scale':3.,'foam_amount':5.})
                    self.assertTrue(tripped[0]);self.assertEqual(snapshot,(spectrum.parm('ampscale').eval(),emit.parm('density').eval(),stage.parm('snippet').eval()))
                    self.assertEqual(addon._fx_manifest('ocean-transaction')[1],before)
                    spectrum.setUserData('test_native_spectrum_zero_layers','1')
                    with self.assertRaisesRegex(Exception,'LAYERS|layers'):apply({'foam':True})
                    spectrum.setUserData('test_native_spectrum_zero_layers','')
                    stage.setInput(2,hou.node(roles['evaluate']))
                    with self.assertRaisesRegex(Exception,'connection|input'):apply({'foam':True})
                    stage.setInput(2,hou.node(roles['source']))
                    original_geometry=type(stage).geometry
                    def observed_failure(kind):
                        def broken(node,output_index=0):
                            g=original_geometry(node,output_index=output_index)
                            if node==spectrum:
                                if kind=='voxels':
                                    prims=list(g.prims());first=prims[0]
                                    prims[0]=SimpleNamespace(**{**vars(first),'allVoxels':lambda:tuple([float('nan')]*16)})
                                    return SimpleNamespace(**{**vars(g),'prims':lambda:tuple(prims)})
                                if kind=='budget':
                                    prims=list(g.prims());prims[0]=SimpleNamespace(**{**vars(prims[0]),'resolution':lambda:(4194305,1,1),'allVoxels':lambda:(_ for _ in ()).throw(AssertionError('must reject before voxel expansion'))})
                                    return SimpleNamespace(**{**vars(g),'prims':lambda:tuple(prims)})
                            if node==stage and kind=='attribute':
                                find=g.findPointAttrib
                                return SimpleNamespace(**{**vars(g),'findPointAttrib':lambda name:None if name=='bridge_ocean_cusp' else find(name)})
                            if node==stage and kind=='positions':
                                points=list(g.points());points[0]=SimpleNamespace(**{**vars(points[0]),'position':lambda:(0.,999.,0.)})
                                return SimpleNamespace(**{**vars(g),'points':lambda:tuple(points)})
                            return g
                        return broken
                    for kind,pattern in [('voxels','finite'),('budget','budget'),('attribute','attribute'),('positions','retain')]:
                        with self.subTest(native_fault=kind),patch.object(type(stage),'geometry',observed_failure(kind)),self.assertRaisesRegex(Exception,pattern):apply({'foam':True})
                    original_input=type(stage).inputGeometry
                    def wrong_input(node,index):
                        return original_input(node,0) if node==stage and index==2 else original_input(node,index)
                    with patch.object(type(stage),'inputGeometry',wrong_input),self.assertRaisesRegex(Exception,'hash|input'):apply({'foam':True})
                    with patch.object(hou,'applicationVersionString',lambda:'21.0.632'),self.assertRaisesRegex(Exception,'VERSION|version'):apply({'foam':True})
                    stage.setUserData('artist_note','retained')
                    original_parent=type(stage).parent
                    with patch.object(type(stage),'parent',lambda node:hou.node('/obj') if node==stage else original_parent(node)),self.assertRaises(Exception):apply({'foam':True})
                    self.assertEqual(stage.userData('artist_note'),'retained')

    def test_cloth_native_thickness_wave_transaction_flat_restore_and_rollback(self):
        spec=importlib.util.spec_from_file_location('cloth_software_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                        instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    hou=sys.modules['hou'];api.install_stage_api(hou)
                    params={'task_id':'cloth-transaction','constraints':{'fx':{'domain_pack':'vellum_cloth_v1','run_mode':'diagnose','frames':[1,2]}},
                        'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    built=client.call('agent.fx.build_preview',params)
                    roles=built['scene_manifest']['nodes'];stage=hou.node(roles['cloth_wrinkle']);constraints=hou.node(roles['constraints'])
                    source=hou.node(roles['source']);source.setUserData('artist_note','retained')
                    feedback=[]
                    def apply(changes):
                        params['constraints']['fx']['changes']=changes
                        result=client.call('agent.fx.apply_candidate',params);feedback.append(result)
                        self.assertEqual({diff['semantic_control'] for diff in result['parameter_diff']},set(changes))
                        return result['native_geometry_readback']
                    first=apply({'thickness':.06,'wrinkle_scale':.5})
                    self.assertEqual(first['registration']['amplitude'],.03)
                    positions=first['shaped_geometry']['point_positions']
                    self.assertEqual(apply({'wrinkle_scale':.5})['shaped_geometry']['point_positions'],positions)
                    changed=apply({'thickness':.08})
                    self.assertEqual(feedback[-1]['invalidates_from'],['source_layout_control'])
                    self.assertTrue(any(diff.get('dependent_semantic_control')=='wrinkle_scale' for diff in feedback[-1]['parameter_diff']))
                    self.assertNotEqual(feedback[-1]['cache_subject_hash'],feedback[-2]['cache_subject_hash'])
                    _,updated=addon._fx_manifest('cloth-transaction')
                    self.assertNotIn('cache',updated)
                    self.assertEqual(feedback[-1]['cache_approval_subject']['revision'],updated['revision'])
                    self.assertEqual(feedback[-1]['cache_approval_subject']['candidate_patch'],updated['candidate_patch'])
                    self.assertEqual(changed['registration']['wrinkle_scale'],.5)
                    self.assertEqual(changed['registration']['amplitude'],.04)
                    self.assertTrue(changed['comparison']['pointwise_formula_matches'])
                    flat=apply({'wrinkle_scale':0.})
                    self.assertEqual(flat['shaped_geometry']['point_positions'],flat['context']['source']['point_positions'])
                    self.assertEqual(apply({'collision_thickness':.1,'wrinkle_scale':.5})['registration']['amplitude'],.05)
                    _,manifest=addon._fx_manifest('cloth-transaction');before=copy.deepcopy(manifest)
                    snippet=stage.parm('snippet');old_snippet=snippet.eval();original=type(snippet).set;tripped=[False]
                    def fail_once(parm,value,**kwargs):
                        if parm.path()==snippet.path() and not tripped[0]:
                            tripped[0]=True
                            raise RuntimeError('injected second-phase native write failure')
                        return original(parm,value,**kwargs)
                    with patch.object(type(snippet),'set',fail_once),self.assertRaises(Exception):
                        apply({'thickness':.12,'wrinkle_scale':.25})
                    self.assertTrue(tripped[0]);self.assertEqual(constraints.parm('thickness').eval(),.1)
                    self.assertEqual(snippet.eval(),old_snippet)
                    self.assertEqual(addon._fx_manifest('cloth-transaction')[1],before)
                    self.assertEqual(source.userData('artist_note'),'retained')
                    constraints.setInput(0,source)
                    with self.assertRaisesRegex(Exception,'shape stage'):
                        apply({'wrinkle_scale':.5})

    def test_rbd_stage_boundary_preserves_host_time_and_channel_evaluation(self):
        spec=importlib.util.spec_from_file_location('rbd_channel_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                interfaces,states,ports=api.interface_profiles(ROOT,version)
                native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                hou=sys.modules['hou']
                host_time=(hou.frame,hou.setFrame,hou.time)
                eval_at_frame=hou._native_schema_parm_class.evalAtFrame
                api.install_stage_api(hou)
                for current,original in zip((hou.frame,hou.setFrame,hou.time),host_time):
                    self.assertIs(current,original)
                self.assertIs(hou._native_schema_parm_class.evalAtFrame,eval_at_frame)
                hou.setFrame(17.25)
                self.assertEqual(hou.frame(),17.25)
                self.assertEqual(hou.time(),(17.25-1)/hou.fps())
                original_time=hou.time()
                parent=hou.node('/obj').createNode('geo','rbd-channel')
                source=parent.createNode('box','source')
                fracture=parent.createNode('rbdmaterialfracture','fracture')
                fracture.setInput(0,source)
                configure=parent.createNode('rbdconfigure','configure')
                configure.setInput(0,fracture)
                configure.parm('attributes').set(1)
                configure.parm('group1').set('')
                configure.parm('addactive1').set(1)
                configure.parm('useactivebounds1').set(0)
                active=configure.parm('active1')
                for frame in (-100000,-5,0,3,100000):
                    with self.subTest(frame=frame):
                        active.deleteAllKeyframes()
                        keys=[]
                        for key_frame,value in ((frame-1,0),(frame,1)):
                            key=hou.Keyframe(value)
                            key.setFrame(key_frame)
                            key.setExpression('constant()',hou.exprLanguage.Hscript)
                            keys.append(key)
                        active.setKeyframes(keys)
                        for sample,expected in ((frame-2,0),(frame-1,0),(frame,1),(frame+1,1)):
                            self.assertEqual(active.evalAtFrame(sample),expected)
                            self.assertEqual(hou.frame(),17.25)
                            self.assertEqual(hou.time(),original_time)
                            try:
                                hou.setFrame(sample)
                                self.assertEqual([primitive.attribValue('active') for primitive in configure.geometry().prims()],
                                    [expected,expected])
                            finally:
                                hou.setFrame(17.25)
                        for before,sample in ((True,frame-2),(False,frame+1)):
                            active.setKeyframeExtrapolation(before,hou.parmExtrapolate.Linear)
                            with self.assertRaisesRegex(ValueError,'extrapolation'):
                                active.evalAtFrame(sample)
                            self.assertEqual(hou.frame(),17.25)
                            self.assertEqual(hou.time(),original_time)
                            active.setKeyframeExtrapolation(before,hou.parmExtrapolate.Constant)
                        keys[0].setExpression('constant()',hou.exprLanguage.Python)
                        active.setKeyframes(keys)
                        with self.assertRaisesRegex(ValueError,'interpolate'):
                            active.evalAtFrame(frame-2)
                        self.assertEqual(hou.frame(),17.25)
                        self.assertEqual(hou.time(),original_time)
                original_frame=hou.frame()
                for invalid_frame in (float('nan'),float('inf'),float('-inf')):
                    with self.subTest(invalid_frame=invalid_frame),self.assertRaisesRegex(ValueError,'finite'):
                        active.evalAtFrame(invalid_frame)
                    self.assertEqual(hou.frame(),original_frame)
                    self.assertEqual(hou.time(),original_time)
                for error in (None,RuntimeError('injected native evaluation failure')):
                    with self.subTest(error=error),patch.object(hou,'setFrame',wraps=hou.setFrame) as set_frame:
                        with patch.object(type(active),'eval',return_value=42,side_effect=error):
                            if error is None:
                                self.assertEqual(active.evalAtFrame(-5),42)
                            else:
                                with self.assertRaisesRegex(RuntimeError,'injected native evaluation failure'):
                                    active.evalAtFrame(-5)
                        self.assertEqual(set_frame.call_args_list,[call(-5),call(original_frame)])
                        self.assertEqual(hou.frame(),original_frame)
                with patch.dict(sys.modules):
                    software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'second-host')
                    other_hou=sys.modules['hou']
                    self.assertIsNot(other_hou,hou)
                    self.assertEqual(other_hou.frame(),1.0)
                    other_hou.setFrame(-9)
                    self.assertEqual(other_hou.frame(),-9)
                    self.assertEqual(other_hou.time(),(-9-1)/other_hou.fps())
                    self.assertEqual(hou.frame(),original_frame)
                    self.assertEqual(hou.time(),original_time)

    def test_rbd_actual_owned_activation_channel_geometry_and_rollback(self):
        spec=importlib.util.spec_from_file_location('rbd_activation_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
                with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    hou=sys.modules['hou'];api.install_stage_api(hou)
                    # Unit-level trusted setup only; formal process evidence is separate.
                    addon._TASK_HOST_IDENTITY=dict(addon._host_identity(),task_id='rbd-active',pid=os.getpid(),launch_nonce='rbd-unit-'+Path(tmp).name,plugin_build=addon._FX_LOADED_ADDON_SHA256,version=version)
                    params={'task_id':'rbd-active','constraints':{'fx':{'domain_pack':'rbd_destruction_v1','run_mode':'diagnose','frames':[1,2]}},'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    roles=client.call('agent.fx.build_preview',params)['scene_manifest']['nodes']
                    solver=hou.node(roles['solver']);configure=hou.node(roles['configure']);startframe=solver.parm('startframe').eval()
                    tokens=solver.parm('overwriteattributes').eval();snapshots=[]
                    hou.setFrame(17.25)
                    self.assertEqual(hou.frame(),17.25)
                    self.assertEqual(hou.time(),(17.25-1)/hou.fps())
                    original_time=hou.time()
                    def apply(frame):
                        params['constraints']['fx']['changes']={'activation_frame':frame}
                        result=client.call('agent.fx.apply_candidate',params)
                        self.assertEqual(result['native_geometry_readback']['activation_channel']['registration']['activation_frame'],frame)
                        self.assertEqual(hou.frame(),17.25)
                        self.assertEqual(hou.time(),original_time)
                        snapshots.append(result);return result
                    for frame in (-5,0,3,-100000,100000):
                        result=apply(frame)
                        channel=result['native_geometry_readback']['activation_channel']
                        self.assertEqual(channel['samples'],[{'frame':f,'value':int(f>=frame)} for f in (frame-2,frame-1,frame,frame+1)])
                        self.assertEqual(len(channel['keyframe_identities']),2)
                        self.assertEqual(channel['keyframes'],[
                            {'frame':frame-1,'value':0,'expression':'constant()','language':'Hscript'},
                            {'frame':frame,'value':1,'expression':'constant()','language':'Hscript'}])
                        self.assertEqual(channel['pre_extrapolation'],'constant');self.assertEqual(channel['post_extrapolation'],'constant')
                        self.assertEqual(channel['current_frame'],17.25)
                        self.assertEqual([v['active_values'] for v in result['native_geometry_readback']['configure_output_samples']],[[0,0],[0,0],[1,1],[1,1]])
                    self.assertEqual(solver.parm('startframe').eval(),startframe);self.assertEqual(solver.parm('overwriteattributes').eval(),tokens)
                    root,manifest=addon._fx_manifest('rbd-active');active=configure.parm('active1')
                    def state():
                        return copy.deepcopy({
                            'channel':addon._fx_scene_parameter_readback(active),
                            'nodes':{role:{'data':hou.node(path).userDataDict(),
                                'parameters':{name:(parm.value,parm._native_state) for name,parm in hou.node(path).parms_dict.items()}}
                                for role,path in roles.items()},
                            'root_data':root.userDataDict(),
                            'manifest':addon._fx_state_path('rbd-active').read_bytes(),
                            'frame':hou.frame(),'time':hou.time()})
                    for frame in (-100001,100001,.5,True):
                        frozen=state()
                        with self.subTest(invalid_frame=frame),self.assertRaises(addon.BridgeCommandError):
                            apply(frame)
                        self.assertEqual(state(),frozen)
                    with patch.object(type(active),'eval',side_effect=RuntimeError('injected native evaluation failure')):
                        with self.assertRaisesRegex(RuntimeError,'injected native evaluation failure'):
                            active.evalAtFrame(-5)
                    self.assertEqual(hou.frame(),17.25)
                    self.assertEqual(hou.time(),original_time)
                    frozen=state()
                    original_geometry=type(configure).geometry
                    geometry_failed=[False]
                    def fail_geometry(node,*args,**kwargs):
                        if node is configure and hou.frame()!=17.25:
                            geometry_failed[0]=True
                            raise RuntimeError('injected sampled configure geometry failure')
                        return original_geometry(node,*args,**kwargs)
                    with patch.object(type(configure),'geometry',fail_geometry),self.assertRaises(addon.BridgeCommandError):
                        apply(-7)
                    self.assertTrue(geometry_failed[0])
                    self.assertEqual(state(),frozen)
                    original_set_keys=type(active).setKeyframes
                    key_write_failed=[False]
                    def fail_keys(parm,keys):
                        if parm is active and not key_write_failed[0]:
                            key_write_failed[0]=True
                            original_set_keys(parm,list(keys)[:1])
                            raise RuntimeError('injected partial native keyframe write failure')
                        return original_set_keys(parm,keys)
                    with patch.object(type(active),'setKeyframes',fail_keys),self.assertRaises(addon.BridgeCommandError):
                        apply(-7)
                    self.assertTrue(key_write_failed[0])
                    self.assertEqual(state(),frozen)
                    frozen=state();original=addon._fx_write_state
                    def fail(task,value):original(task,value);raise OSError('injected activation persistence failure')
                    with patch.object(addon,'_fx_write_state',fail),self.assertRaises(addon.BridgeCommandError):apply(-7)
                    self.assertEqual(state(),frozen)
                    for foreign_kind in ('expression','reference','extra_key','key_language','pre_extrapolation','post_extrapolation'):
                        original_state=active._native_state
                        pristine=state()
                        with self.subTest(foreign=foreign_kind),patch.object(active,'_native_state',copy.deepcopy(original_state)):
                            if foreign_kind=='expression':
                                active.setExpression('1',hou.exprLanguage.Hscript)
                            elif foreign_kind=='reference':
                                native.set_parm_state(active,reference=solver.parm('startframe'))
                            elif foreign_kind=='extra_key':
                                extra=hou.Keyframe(1.)
                                extra.setFrame(20.)
                                extra.setExpression('constant()',hou.exprLanguage.Hscript)
                                active.setKeyframes([*active.keyframes(),extra])
                            elif foreign_kind=='key_language':
                                keys=list(active.keyframes())
                                keys[0].setExpression('constant()',hou.exprLanguage.Python)
                                active.setKeyframes(keys)
                            else:
                                active.setKeyframeExtrapolation(foreign_kind=='pre_extrapolation',hou.parmExtrapolate.Linear)
                            foreign=state()
                            with self.assertRaises(addon.BridgeCommandError) as rejected:apply(0)
                            if foreign_kind=='post_extrapolation':
                                self.assertEqual(rejected.exception.code,'ACTUAL_OWNED_ACTIVE_CHANNEL_REQUIRED')
                            self.assertEqual(state(),foreign)
                        self.assertIs(active._native_state,original_state)
                        self.assertEqual(state(),pristine)
                    self.assertEqual(apply(0)['native_geometry_readback']['activation_channel']['post_extrapolation'],'constant')
                    output=os.environ.get('BRIDGE_RBD_ACTIVATION_EVIDENCE_DIR')
                    if output:
                        target=Path(output)/version;target.mkdir(parents=True,exist_ok=True)
                        (target/'native-activation-channel.json').write_text(json.dumps({'feedback':snapshots,'persistence_rollback_exact':True,'external_extra_key_rejected':True,'startframe':startframe,'overwriteattributes':tokens,'unit_trusted_identity_setup':True,'native_execution':False},indent=2)+'\n',encoding='utf-8')

    def test_documented_ports_parameters_feedback_and_saved_structure_on_both_versions(self):
        spec=importlib.util.spec_from_file_location('domain_software_api',ROOT/'tools/software_render_api_boundary.py')
        api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
        for version in ('21.0.631','22.0.429'):
            for domain in ('water_ocean_v1','procedural_geometry_v1','vellum_cloth_v1','water_flip_v1','particles_v1','swarm_flocking_v1'):
                with self.subTest(version=version,domain=domain),tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ,{'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini','BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}),patch.dict(sys.modules):
                        client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                        interfaces,states,ports=api.interface_profiles(ROOT,version)
                        native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                            instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                        api.install_stage_api(sys.modules['hou'])
                        runner=DomainReadinessRunner(host_client=client,task_id='native-interface',output_root=Path(tmp)/'outputs')
                        result=runner.run_case(domain,'causal_candidate').to_dict()
                        receipts=result['stage_receipts'];commands=[r['command'] for r in receipts]
                        self.assertIn('scene.reopen_task_hip',commands,result)
                        self.assertIn('agent.fx.apply_candidate',commands)
                        build=receipts[0]['result'];assessment=build['scene_manifest']['execution_assessment']
                        self.assertTrue(assessment['domain_graph_constructed'])
                        self.assertEqual(build['execution_state'],'EDITABLE_DOMAIN_GRAPH')
                        self.assertFalse(assessment['native_graph_contract']['native_geometry_validated'])
                        connections=build['scene_manifest']['connections']['verified']
                        self.assertTrue(all(c['verified'] for c in connections))
                        patch_result=next(r['result'] for r in receipts if r['command']=='agent.fx.apply_candidate')
                        self.assertTrue(patch_result['parameter_diff'])
                        self.assertEqual(result['diagnostic_status'],'PASS',result.get('blocker'))
                        self.assertEqual(result['status'],'BLOCKED',result.get('blocker'))
                        self.assertIn('FORMAL_CASE_FACADE_REQUIRED',result.get('blocker',''))
                        self.assertEqual(result['preview_operation']['frames_done'],[1,2])
                        self.assertEqual(result['preview_operation']['lifecycle_fact']['kind'],'STOP_CONFIRMED')
                        self.assertFalse(result['real_dcc_verified'])
    def test_capture_fixture_rejects_invented_parameter_instead_of_lazily_accepting_it(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
            client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp))
            native.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json')
            root=sys.modules['hou'].node('/obj').createNode('geo','source')
            node=root.createNode('oceanspectrum','spectrum')
            self.assertIsNotNone(node.parm('ampscale'))
            self.assertIsNone(node.parm('wavescale'))
            self.assertIsNone(node.parm('invented_parameter'))
