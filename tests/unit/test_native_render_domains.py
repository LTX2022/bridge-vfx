from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/houdini-bridge/src"))
from houdini_bridge import native_render_domains as native
from houdini_bridge.domain_packs import DOMAIN_PACKS

spec = importlib.util.spec_from_file_location("render_domain_boundary", ROOT / "tools/native_schema_test_boundary.py")
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


class NativeRenderDomainTests(unittest.TestCase):
    def assert_code(self, code, callable, *args, **kwargs):
        with self.assertRaises(native.NativeRenderDomainError) as error:
            callable(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_all_existing_public_controls_remain_and_exact_material_fields_exist(self):
        packs = {pack.identifier: pack for pack in DOMAIN_PACKS}
        for version in native.SUPPORTED_VERSIONS:
            catalog = boundary.capture_catalog(ROOT / "docs/native-basis/hda-interface-capture.json", version)
            for pack_id in (native.MATERIAL, native.LIGHTING):
                controls = native.control_contract(pack_id, version)
                self.assertEqual(set(controls), {c.identifier for c in packs[pack_id].controls})
                self.assertEqual(len(controls), 11 if pack_id == native.MATERIAL else 12)
                nodes = {r['role']:r for r in native.node_requirements(pack_id,version)}
                for control in controls.values():
                    node = nodes[control['role']]
                    category = {'vop':'Vop','lop':'Lop'}[node['category']]
                    record = catalog[(category,node['types'][0])]
                    self.assertIn(control['aliases'][0], record['parameters'])
            self.assertEqual(native.control_contract(native.MATERIAL,version)['ior']['aliases'],['specular_IOR'])
            self.assertEqual(native.control_contract(native.MATERIAL,version)['normal_strength']['role'],'normal_map')
            self.assertEqual(native.control_contract(native.MATERIAL,version)['displacement_scale']['role'],'displacement')

    def test_public_native_build_feedback_and_actual_usd_save_reopen(self):
        import os
        import tempfile
        from unittest.mock import patch
        from vfx_pipeline.workbuddy_assembly import software_host_client
        api_spec = importlib.util.spec_from_file_location("software_render_api_boundary", ROOT / "tools/software_render_api_boundary.py")
        api = importlib.util.module_from_spec(api_spec); api_spec.loader.exec_module(api)
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.MATERIAL, native.LIGHTING):
                with self.subTest(version=version,domain=domain), tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules), patch.dict(os.environ, {
                    'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state','HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini',
                    'BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                    client,addon=software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',Path(tmp)/'host')
                    interfaces,states,ports=api.interface_profiles(ROOT,version)
                    boundary.constrain_hou(ROOT/'docs/native-basis/hda-interface-capture.json',version,
                        instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
                    api.install_stage_api(sys.modules['hou'])
                    params={'task_id':'public-render-entry','constraints':{'fx':{'domain_pack':domain,'run_mode':'diagnose','frames':[1,2]}},
                        'render':{'frame_range':{'start':1,'end':2,'step':1}}}
                    built=client.call('agent.fx.build_preview',params);scene=built['scene_manifest']
                    self.assertEqual(built['execution_state'],'EDITABLE_DOMAIN_GRAPH')
                    self.assertEqual(sys.modules['hou'].node(scene['execution_root']).type().name(),'subnet')
                    changes={'roughness':.3,'normal_strength':.7} if domain==native.MATERIAL else {'focal_length':45.,'shutter':.4,'filter_width':2.5}
                    changed=copy.deepcopy(params);changed['constraints']['fx']['changes']=changes
                    feedback=client.call('agent.fx.apply_candidate',changed)
                    self.assertEqual({d['semantic_control'] for d in feedback['parameter_diff']},set(changes))
                    self.assertTrue(all(d['readback_verified'] for d in feedback['parameter_diff']))
                    observed=addon._fx_static_domain_readback(domain,scene['nodes'],addon._fx_pack(params)[1])
                    self.assertTrue(observed['usd_binding_readback']['imported_prim_paths'])
                    hou = sys.modules['hou']
                    original_frame = hou.frame()
                    try:
                        hou.setFrame(1.25)
                        fractional = addon._fx_static_domain_readback(domain, scene['nodes'], addon._fx_pack(params)[1])
                        self.assertEqual(fractional['usd_binding_readback']['render_config'],
                            addon._fx_render_configuration(hou.node(scene['nodes']['render']), [1.25]))
                        self.assertEqual(hou.frame(), 1.25)
                    finally:
                        hou.setFrame(original_frame)
                    output_config=addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),[1,2])
                    from dcc_task_runtime.artifact_registry import frame_path
                    pattern=str(Path(tmp)/'中文 output'/'override.%03d.exr')
                    preflight=addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),
                                                           [1,2],output_pattern=pattern)
                    for frame in (1,2):
                        ocio=preflight[str(frame)]['ocio_configuration_fact']
                        self.assertEqual(ocio['schema'],'bridge.houdini.ocio-preflight/1.0')
                        self.assertEqual(ocio['source'],'parent_houdini_preflight')
                        self.assertEqual(ocio['final_output_path'],str(frame_path(pattern,frame)))
                        self.assertNotIn('colorspace',ocio)
                        self.assertNotIn('premultiplied',ocio)
                        self.assertNotIn('completion_metadata_status',ocio)
                        original={key:value for key,value in preflight[str(frame)].items()
                                  if key!='ocio_configuration_fact'}
                        self.assertEqual(original,output_config[str(frame)])
                    selection={'schema':'bridge.project-color/1.0','project_id':'fixture','revision':1,
                               'colorspace':'project-linear','source':'human_project_selection'}
                    with patch('houdini_bridge.render_ocio_facts.collect_ocio_configuration',
                               side_effect=AssertionError('project selection must not require internal color trace')):
                        selected=addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),
                                                               [1,2],output_pattern=pattern,project_color=selection)
                    for frame in (1,2):
                        self.assertEqual(selected[str(frame)]['project_color'],selection)
                        self.assertNotIn('ocio_configuration_fact',selected[str(frame)])
                        self.assertEqual({key:value for key,value in selected[str(frame)].items()
                                          if key!='project_color'},output_config[str(frame)])
                    terminal=sys.modules['hou'].node(scene['nodes']['settings_binding'])
                    explicit_stage=terminal.stage(frame=1,apply_viewport_overrides=False,ignore_errors=False)
                    product_path=output_config['1']['products'][0]
                    var_path=output_config['1']['aovs'][0]
                    attribute_snapshots=[]
                    for path,prefix,source,destination in (
                            (product_path,'driver:parameters:husk:','product-source','product-destination'),
                            (var_path,'driver:parameters:aov:husk:','var-source','var-destination')):
                        attributes=explicit_stage.GetPrimAtPath(path).attributes
                        for field in ('source_colorspace','output_colorspace'):
                            name=prefix+field
                            attribute_snapshots.append((attributes,name,name in attributes,attributes.get(name)))
                        attributes[prefix+'source_colorspace']=api.Attribute('string',source,prefix+'source_colorspace')
                        attributes[prefix+'output_colorspace']=api.Attribute('string',destination,prefix+'output_colorspace')
                    try:
                        with patch.object(type(terminal),'stage',lambda *args,**kwargs:explicit_stage):
                            explicit=addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),
                                                                   [1],output_pattern=pattern)
                    finally:
                        for attributes,name,present,value in attribute_snapshots:
                            if present:attributes[name]=value
                            else:attributes.pop(name,None)
                    self.assertEqual(explicit['1']['ocio_configuration_fact']['transform_requests'],[
                        {'label':product_path,'source':'product-source','destination':'product-destination'},
                        {'label':var_path,'source':'var-source','destination':'var-destination'}])
                    product=explicit_stage.GetPrimAtPath(product_path)
                    original_vars=product.relations['orderedVars']
                    extra_vars=['/PreflightVar'+str(index) for index in range(17)]
                    try:
                        product.relations['orderedVars']=extra_vars
                        for path in extra_vars:
                            variable=api.Prim(path,'RenderVar')
                            for field,value in (('source_colorspace','var-source'),('output_colorspace','var-destination')):
                                name='driver:parameters:aov:husk:'+field
                                variable.attributes[name]=api.Attribute('string',value,name)
                            explicit_stage.prims[path]=variable
                        with patch.object(type(terminal),'stage',lambda *args,**kwargs:explicit_stage):
                            bounded=addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),
                                                                  [1],output_pattern=pattern)['1']
                        ocio=bounded['ocio_configuration_fact']
                        self.assertEqual(len(bounded['aovs']),17)
                        self.assertEqual(len(ocio['transform_requests']),16)
                        self.assertEqual(ocio['api_facts']['raw_usd.transform_requests.omitted']['value'],1)
                        self.assertIn('PROCESSOR_REQUEST_BUDGET_EXCEEDED',
                                      {gap['code'] for gap in ocio['missing_facts']})
                        from houdini_bridge.render_ocio_facts import validate_ocio_configuration
                        validate_ocio_configuration(ocio)
                    finally:
                        product.relations['orderedVars']=original_vars
                        for path in extra_vars:explicit_stage.prims.pop(path,None)
                    if domain==native.MATERIAL:
                        hou=sys.modules['hou'];roles=scene['nodes']
                        self.assertEqual(observed['usd_binding_readback']['render_config'],
                                         addon._fx_render_configuration(hou.node(roles['render']),[int(hou.frame())]))
                        camera=hou.node(roles['camera'])
                        self.assertIs(camera.input(0),hou.node(roles['material_binding']))
                        self.assertEqual(observed['output_role'],'settings_binding')
                        self.assertEqual(observed['output_kind'],'usd_render_stage')
                        final_stage=hou.node(roles['settings_binding']).stage()
                        geometry=observed['usd_binding_readback']['geometry_prefix']
                        material=observed['usd_binding_readback']['material_prim_path']
                        self.assertEqual([str(p) for p in final_stage.GetPrimAtPath(geometry).GetRelationship('material:binding').GetTargets()],[material])
                        camera.setInput(0,hou.node(roles['geometry_import']))
                        try:
                            with self.assertRaises(addon.BridgeCommandError):
                                addon._fx_static_domain_readback(domain,roles,addon._fx_pack(params)[1])
                        finally:
                            camera.setInput(0,hou.node(roles['material_binding']))
                        driver=hou.node(roles['render']);output=driver.parm('loppath');original=output.eval()
                        output.set(roles['material_binding'])
                        try:
                            with self.assertRaises(addon.BridgeCommandError):
                                addon._fx_static_domain_readback(domain,roles,addon._fx_pack(params)[1])
                        finally:
                            output.set(original)
                        unrelated = hou.node(roles['material_binding'])
                        unrelated_stage = copy.deepcopy(final_stage)
                        unrelated_stage.prims[geometry].relations.pop('material:binding', None)
                        original_stage = type(unrelated).stage
                        def stage_for_node(node, *arguments, **keywords):
                            if node is unrelated:
                                return unrelated_stage
                            return original_stage(node, *arguments, **keywords)
                        output.set(unrelated.path())
                        try:
                            with patch.object(type(unrelated), 'stage', stage_for_node):
                                addon._fx_render_configuration(driver, [int(hou.frame())])
                                with self.assertRaisesRegex(addon.BridgeCommandError, 'verified final USD stage'):
                                    addon._fx_static_domain_readback(domain, roles, addon._fx_pack(params)[1])
                        finally:
                            output.set(original)
                        self.assertEqual(sum(hou.node(path).type().name()=='sopimport' for path in roles.values()),1)
                    if version.startswith('22'):
                        settings=sys.modules['hou'].node(scene['nodes']['settings'])
                        width=settings.parm('pixelfiltersize')
                        original_width=width.eval()
                        self.assertTrue(width.parmTemplate().isHidden())
                        self.assertFalse(width.isHidden())
                        self.assertFalse(width.isVisible())
                        stage=sys.modules['hou'].node(scene['nodes']['settings_binding']).stage()
                        authored=stage.GetPrimAtPath(settings.parm('primpath').eval()).GetAttribute('karma:global:pixelfiltersize')
                        if authored is not None:
                            self.assertEqual(authored.Get(),original_width)
                        else:
                            self.assertEqual(original_width,2.)
                        terminal=sys.modules['hou'].node(scene['nodes']['settings_binding'])
                        cases=[(2.,None,True),(2.,api.Attribute('float',2.),True),
                            (2.,api.Attribute('float',3.),False),(2.5,api.Attribute('float',2.5),True),
                            (2.5,None,False),(2.,api.Attribute('string','2'),False),
                            (2.,api.Attribute('float',None),False)]
                        for requested,attribute,accepted in cases:
                            with self.subTest(width=requested,authored=None if attribute is None else (attribute.kind,attribute.value)):
                                width.set(requested)
                                injected_stage=terminal.stage()
                                attrs=injected_stage.GetPrimAtPath(settings.parm('primpath').eval()).attributes
                                if attribute is None:attrs.pop('karma:global:pixelfiltersize',None)
                                else:attrs['karma:global:pixelfiltersize']=attribute
                                with patch.object(type(terminal),'stage',lambda *a,**k:injected_stage):
                                    if accepted:
                                        addon._fx_static_domain_readback(domain,scene['nodes'],addon._fx_pack(params)[1])
                                    else:
                                        with self.assertRaises(addon.BridgeCommandError) as error:
                                            addon._fx_static_domain_readback(domain,scene['nodes'],addon._fx_pack(params)[1])
                                        self.assertEqual(error.exception.code,'GRAPH_CONTRACT_UNVERIFIED')
                        width.set(original_width)
                    before={role:client.call('node.info',{'task_id':params['task_id'],'path':path,'root_path':scene['execution_root']}) for role,path in scene['nodes'].items()}
                    saved=client.call('scene.save_hip',{'task_id':params['task_id'],'path':tmp+'/scene.hip','root_path':scene['execution_root']})
                    client.call('scene.reopen_task_hip',{'task_id':params['task_id'],'path':saved['path'],'sha256':saved['sha256']})
                    after={role:client.call('node.info',{'task_id':params['task_id'],'path':path,'root_path':scene['execution_root']}) for role,path in scene['nodes'].items()}
                    self.assertEqual(before,after)
                    reopened=addon._fx_static_domain_readback(domain,scene['nodes'],addon._fx_pack(params)[1])
                    self.assertEqual(observed,reopened)
                    self.assertEqual(output_config,addon._fx_render_configuration(sys.modules['hou'].node(scene['nodes']['render']),[1,2]))
                    target=sys.modules['hou'].node(scene['nodes']['material' if domain==native.MATERIAL else 'camera'])
                    parm=target.parm('specular_roughness' if domain==native.MATERIAL else 'focalLength')
                    boundary.set_parm_state(parm,locked=True)
                    with self.assertRaises(addon.BridgeCommandError):client.call('agent.fx.apply_candidate',changed)
                    self.assertEqual(parm.eval(),.3 if domain==native.MATERIAL else 45.)

    def test_named_shader_ports_are_evidenced_but_not_assumed_hom_indices(self):
        facts=json.loads((ROOT/'docs/native-basis/hda-interface-capture.json').read_text(encoding='utf-8'))
        for version in native.SUPPORTED_VERSIONS:
            nodes={n['role']:n['types'][0] for n in native.node_requirements(native.MATERIAL,version)}
            for wire in native.connection_requirements(native.MATERIAL,version):
                if 'source_output_name' not in wire:continue
                source=facts['versions'][version]['operators']['Vop/'+nodes[wire['source_role']]]
                dest=facts['versions'][version]['operators']['Vop/'+nodes[wire['destination_role']]]
                self.assertIn(wire['source_output_name'],[p['name'] for p in source['outputs']])
                self.assertIn(wire['destination_input_name'],[p['name'] for p in dest['inputs']])
            self.assert_code('NATIVE_PORT_INTERFACE_REQUIRED',native.resolve_named_connections,native.MATERIAL,version,{})
            interfaces={role:{'origin':'runtime_hom','output_names':['out'],'input_names':[]} for role in ('normal_map','material','displacement','material_output')}
            interfaces['material']['input_names']=['base_color','normal']
            interfaces['material_output']['input_names']=['displacementshader','surfaceshader']
            resolved=native.resolve_named_connections(native.MATERIAL,version,interfaces)
            shader=[r for r in resolved if 'source_output_name' in r]
            self.assertEqual([r['destination_input'] for r in shader],[1,1,0])
            interfaces['material_output']['origin']='static_dialogscript'
            self.assert_code('NATIVE_PORT_INTERFACE_REQUIRED',native.resolve_named_connections,native.MATERIAL,version,interfaces)

    def test_shutter_requires_explicit_unit_contract_and_checks_inverse(self):
        for version in native.SUPPORTED_VERSIONS:
            self.assert_code('SHUTTER_UNIT_CONTRACT_REQUIRED',native.control_write_plan,native.LIGHTING,'shutter',.5,version)
            plan=native.control_write_plan(native.LIGHTING,'shutter',.5,version,shutter_contract=native.SHUTTER_CONTRACT)
            self.assertEqual([(p['parm'],p['value']) for p in plan],[('xn__shutteropen_0ta',-.25),('xn__shutterclose_nva',.25)])
            self.assert_code('SHUTTER_ZERO_DURATION_UNSUPPORTED',native.control_write_plan,native.LIGHTING,'shutter',0,version,shutter_contract=native.SHUTTER_CONTRACT)
            values={(p['role'],p['parm']):p['value'] for p in plan}
            self.assertEqual(native.control_readback(native.LIGHTING,'shutter',values,version,shutter_contract=native.SHUTTER_CONTRACT),.5)
            values[('camera','xn__shutterclose_nva')]=.1
            self.assert_code('NATIVE_CONTROL_READBACK_MISMATCH',native.control_readback,native.LIGHTING,'shutter',values,version,shutter_contract=native.SHUTTER_CONTRACT)

    def test_denoiser_endpoints_do_not_misrepresent_continuous_mix(self):
        for version in native.SUPPORTED_VERSIONS:
            for control in ('denoise','denoise_mix'):
                self.assertEqual(native.control_write_plan(native.LIGHTING,control,0,version)[0]['value'],'off')
                self.assertEqual(native.control_write_plan(native.LIGHTING,control,1,version)[0]['value'],'oidn')
            self.assert_code('EXTERNAL_DENOISE_BLEND_REQUIRED',native.control_write_plan,native.LIGHTING,'denoise_mix',.4,version)
            self.assertEqual(native.control_contract(native.LIGHTING,version)['denoise_mix']['external_application'],'external_nuke')
            self.assert_code('CONFLICTING_NATIVE_CONTROLS',native.candidate_write_plan,native.LIGHTING,{'denoise':0,'denoise_mix':1},version)

    def test_alias_conflicts_and_invalid_values_are_rejected_before_resolving(self):
        version=native.SUPPORTED_VERSIONS[0]
        self.assert_code('CONFLICTING_NATIVE_CONTROLS',native.candidate_write_plan,native.LIGHTING,{'pixel_samples':9,'sample_quality':16},version)
        self.assertEqual(len(native.candidate_write_plan(native.LIGHTING,{'pixel_samples':9,'sample_quality':9},version)),1)
        for control,value in [('sample_quality',2.3),('motion_blur',.3),('focal_length',float('nan')),('filter_width',0)]:
            self.assert_code('INVALID_NATIVE_CONTROL_VALUE',native.control_write_plan,native.LIGHTING,control,value,version)
        self.assert_code('INVALID_NATIVE_CONTROL_VALUE',native.control_write_plan,native.MATERIAL,'base_color',[1,2,3],version)
        self.assert_code('INVALID_NATIVE_CONTROL_VALUE',native.control_write_plan,native.MATERIAL,'roughness',True,version)

    def test_domelight_radius_and_artist_control_gates_block_preflight(self):
        version=native.SUPPORTED_VERSIONS[0]
        self.assert_code('UNSUPPORTED_NATIVE_CONTROL',native.control_write_plan,native.LIGHTING,'light_size',1,version,light_type='domelight')
        writes=native.control_write_plan(native.LIGHTING,'depth_of_field',4,version)
        observation={('camera','fStop'):{'origin':'runtime_hom','type':'float','size':1,'locked':False,'disabled':False,'hidden':False},('camera','fStop_control'):{'origin':'runtime_hom','value':'set'}}
        native.validate_control_write_plan(writes,observation)
        for value in ('none','block','animationblock'):
            observation[('camera','fStop_control')]['value']=value
            self.assert_code('NATIVE_CONTROL_GATE_BLOCKED',native.validate_control_write_plan,writes,observation)
        observation[('camera','fStop_control')]['value']='set'
        for name in ('locked','disabled','hidden'):
            observation[('camera','fStop')][name]=None
            self.assert_code('NATIVE_CONTROL_GATE_BLOCKED',native.validate_control_write_plan,writes,observation)
            observation[('camera','fStop')][name]=False
        observation[('camera','fStop')]['type']='string'
        self.assert_code('NATIVE_CONTROL_INTERFACE_REQUIRED',native.validate_control_write_plan,writes,observation)

    def test_karma_versions_have_explicit_filter_and_sampling_gate_contracts(self):
        for version in native.SUPPORTED_VERSIONS:
            plan=native.control_write_plan(native.LIGHTING,'filter_width',2.5,version)
            self.assertEqual(plan[0]['parm'],'pixelfiltersize')
            self.assertEqual(plan[0]['required_gates'],[('settings','pixelfilterscale',1.0)] if version.startswith('22') else [])
            sample=native.control_write_plan(native.LIGHTING,'pixel_samples',16,version)
            self.assertEqual(sample[0]['required_gates'],[('settings','engine','cpu'),('settings','convergence_mode','Variance')])
            self.assertEqual(native.control_write_plan(native.LIGHTING,'motion_blur',True,version)[0]['parm'],'enablemblur')

    def test_real_driver_and_explicit_usd_links_in_initialization(self):
        bindings={'source_node_path':'/obj/task/geo/output','geometry_prim_path':'/World/task/Geometry',
                  'final_lop_node_path':'/obj/task/stage/settings_binding','output_image':'/tmp/task/beauty.$F4.exr'}
        bindings.update({n+'_prim_path':'/World/task/'+n for n in ('camera','light','settings','product','var')})
        bindings['product_prim_path']='/World/task/Products/renderproduct'
        bindings.update(material_output_node_path='/obj/task/materials/material_output',material_prim_path='/World/task/Materials/lookdev')
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.MATERIAL,native.LIGHTING):
                requirements=native.node_requirements(domain,version)
                render=next(n for n in requirements if n['role']=='render')
                self.assertEqual((render['category'],render['types'],render['input_role']),('rop',['usdrender'],None))
                self.assert_code('USD_RENDERER_INTERFACE_REQUIRED',native.trusted_initialization_plan,domain,version,bindings)
                snapshot=copy.deepcopy(bindings)
                plan=native.trusted_initialization_plan(domain,version,bindings,renderer_field='renderer')
                for output in ('C:/中文 task/beauty.$F4.exr', 'C:\\中文 task\\beauty.$F4.exr',
                               '//server/share/task/beauty.$F4.exr'):
                    with self.subTest(output=output):
                        portable=native.trusted_initialization_plan(domain,version,
                            dict(bindings,output_image=output),renderer_field='renderer')
                        self.assertEqual(next(write['value'] for write in portable
                                              if write['role']=='settings' and write['parm']=='picture'),output)
                        directory_writes = [write for write in portable if write['role'] == 'render'
                                            and write['parm'] in {'enableoutputprocessor_savetodirectory', 'savetodirectory_directory', 'husk_tiletempdir'}]
                        if version == '21.0.631':
                            from pathlib import PurePosixPath, PureWindowsPath
                            parent = (PurePosixPath(output) if PurePosixPath(output).is_absolute() else PureWindowsPath(output)).parent
                            self.assertEqual([(write['parm'], write['value'], write['native_type']) for write in directory_writes],
                                             [('enableoutputprocessor_savetodirectory', 1, 'toggle'),
                                              ('savetodirectory_directory', str(parent), 'string'),
                                              ('husk_tiletempdir', str(parent), 'string')])
                            self.assertFalse(any(write['parm'] in {'husk_tile', 'husk_autotile'} for write in portable))
                            self.assertIs(type(directory_writes[0]['value']), int)
                        else:
                            self.assertEqual(directory_writes, [])
                for output in ('relative/beauty.exr', 'C:beauty.exr', 'C:/bad\x00.exr'):
                    with self.subTest(output=output):
                        self.assert_code('EXPLICIT_NATIVE_BINDING_REQUIRED',native.trusted_initialization_plan,
                            domain,version,dict(bindings,output_image=output),renderer_field='renderer')
                self.assertEqual(bindings,snapshot)
                writes={(p['role'],p['parm']):p['value'] for p in plan}
                self.assertEqual(writes[('render','loppath')],bindings['final_lop_node_path'])
                self.assertEqual(writes[('render','renderer')],'BRAY_HdKarma')
                self.assertEqual(writes[('render_product','orderedVars')],bindings['var_prim_path'])
                self.assertEqual(writes[('settings_binding','products')],bindings['product_prim_path'])
                self.assertEqual(writes[('settings_binding','createprims')],'forceedit')
                self.assertEqual(writes[('light','lighttype')],'UsdLuxSphereLight')
                self.assertEqual(writes[('render_product','camera_control')],'set')
                self.assertEqual(writes[('render_product','primpattern')],bindings['product_prim_path'])
                self.assertEqual(writes[('render_product','createprims')],'forceedit')
                self.assertNotIn(('render_product','primpath'),writes)
                self.assertNotIn(('render','execute'),writes)
                self.assertFalse(any('exr' in p['parm'].lower() for p in plan))

    def test_material_binding_is_explicit_and_multiparm_phase_is_preserved(self):
        bindings={'source_node_path':'/obj/task/geo/output','geometry_prim_path':'/World/task/Geometry',
                  'material_output_node_path':'/obj/task/materials/material_output','material_prim_path':'/World/task/Materials/lookdev',
                  'final_lop_node_path':'/obj/task/stage/settings_binding','output_image':'/tmp/task/beauty.$F4.exr'}
        bindings.update({n+'_prim_path':'/World/task/'+n for n in ('camera','light','settings','product','var')})
        bindings['product_prim_path']='/World/task/Products/renderproduct'
        plan=native.trusted_initialization_plan(native.MATERIAL,'21.0.631',bindings,renderer_field='renderer')
        writes={(p['role'],p['parm']):p for p in plan}
        self.assertEqual(writes[('material_library','matflag1')]['value'],1)
        self.assertEqual(writes[('material_library','matnode1')]['value'],bindings['material_output_node_path'])
        self.assertEqual(writes[('material_binding','matspecpath1')]['value'],bindings['material_prim_path'])
        self.assertEqual(writes[('material_binding','primpattern1')]['value'],bindings['geometry_prim_path'])
        self.assertEqual(writes[('material_binding','nummaterials')]['phase'],'multiparm_count')
        self.assertEqual(writes[('render','loppath')]['value'],bindings['final_lop_node_path'])
        self.assertEqual(sum(w['role']=='geometry_import' and w['parm']=='soppath' for w in plan),1)
        for version in native.SUPPORTED_VERSIONS:
            nodes=native.node_requirements(native.MATERIAL,version)
            self.assertEqual(len({n['role'] for n in nodes}),len(nodes))
            self.assertEqual(sum(n['types']==['sopimport'] for n in nodes),1)
            by_role={n['role']:n for n in nodes}
            chain=('geometry_import','material_library','material_binding','camera','light','settings','render_var','render_product','settings_binding')
            self.assertEqual([by_role[n]['input_role'] for n in chain[1:]],list(chain[:-1]))
            self.assertEqual(by_role['render']['parent_role'],'render_network')
            for field in ('material_output_node_path','material_prim_path','final_lop_node_path','output_image','camera_prim_path','product_prim_path'):
                bad=dict(bindings);bad.pop(field)
                self.assert_code('EXPLICIT_NATIVE_BINDING_REQUIRED',native.trusted_initialization_plan,native.MATERIAL,version,bad,renderer_field='renderer')
        self.assertEqual(native.trusted_node_flag_plan(native.MATERIAL,'21.0.631')[0]['setter'],'setMaterialFlag')
        self.assert_code('EXPLICIT_NATIVE_BINDING_REQUIRED',native.trusted_initialization_plan,native.MATERIAL,'21.0.631',{})

    def test_renderer_observation_reads_only_exact_native_instance_menu(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for category in ("Driver/usdrender", "Lop/usdrender_rop", "Lop/other"):
            for name in ("renderer", "other"):
                calls = []
                template = SimpleNamespace(type=lambda: "parmTemplateType.String", numComponents=lambda: 1,
                                           menuItems=lambda: ())
                component = SimpleNamespace(isHidden=lambda: False, isDisabled=lambda: False, isLocked=lambda: False,
                                            menuItems=lambda: calls.append("instance") or ("BRAY_HdKarma",))
                parm = SimpleNamespace(parmTemplate=lambda: template, _components=lambda: [component],
                                       isLocked=lambda: False, isDisabled=lambda: False,
                                       eval=lambda: "BRAY_HdKarma", evalAsString=lambda: "BRAY_HdKarma",
                                       path=lambda: "/out/render/" + name)
                node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: category))
                with self.subTest(category=category, name=name), patch.object(addon, "_resolve_parm_target", return_value=parm):
                    observed = addon._fx_native_field_observation(node, name)
                    selected = category != "Lop/other" and name == "renderer"
                    self.assertEqual(calls, ["instance"] if selected else [])
                    self.assertEqual(observed["menu_tokens"], ("BRAY_HdKarma",) if selected else ())
                    self.assertEqual((observed["type"], observed["size"]), ("string", 1))
                    if selected:
                        self.assertEqual(native.renderer_parameter("21.0.631", {"renderer": observed}), "renderer")
                        for bad in (("different",), (123,), None):
                            component.menuItems = lambda: bad
                            if bad == ("different",):
                                actual = addon._fx_native_field_observation(node, name)
                                self.assert_code("USD_RENDERER_INTERFACE_REQUIRED", native.renderer_parameter,
                                                 "21.0.631", {"renderer": actual})
                            else:
                                with self.assertRaises(addon.BridgeCommandError):
                                    addon._fx_native_field_observation(node, name)
                        def unavailable(): raise RuntimeError("menu unavailable")
                        component.menuItems = unavailable
                        with self.assertRaises(addon.BridgeCommandError):
                            addon._fx_native_field_observation(node, name)
                        self.assertEqual(calls, ["instance"])

    def test_native_observation_respects_template_menu_capabilities(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()

        class NonMenuTemplate:
            def __init__(self, kind, size): self.kind, self.size = kind, size
            def type(self): return "parmTemplateType." + self.kind
            def numComponents(self): return self.size

        class FloatTemplate(NonMenuTemplate):
            def namingScheme(self): return "parmNamingScheme.XYZW"

        class MenuTemplate(NonMenuTemplate):
            def menuItems(self): return ("a", "b")

        for kind, expected in (("Toggle", "toggle"), ("Float", "float"), ("Folder", "integer"),
                               ("Data", "data"), ("String", "string"), ("Int", "integer"), ("Menu", "integer")):
            menu = kind in {"String", "Int", "Menu"}
            template = (MenuTemplate if menu else FloatTemplate if kind == "Float" else NonMenuTemplate)(kind, 3 if kind == "Float" else 1)
            component = SimpleNamespace(isHidden=lambda: False, isDisabled=lambda: False, isLocked=lambda: False)
            parm = SimpleNamespace(parmTemplate=lambda: template, _components=lambda: [component],
                                   isLocked=lambda: False, isDisabled=lambda: False,
                                   eval=lambda: 1, evalAsString=lambda: "a", path=lambda: "/stage/import/value")
            with self.subTest(kind=kind), patch.object(addon, "_resolve_parm_target", return_value=parm):
                actual = addon._fx_native_field_observation(SimpleNamespace(), "value")
                self.assertEqual(actual["type"], expected)
                self.assertEqual(actual["size"], template.size)
                self.assertEqual(actual["menu_tokens"], ("a", "b") if menu else ())
                self.assertEqual(actual["value"], "a" if kind in {"String", "Menu"} else 1)
                self.assertFalse(actual["hidden"] or actual["locked"] or actual["disabled"])
                if menu:
                    template = NonMenuTemplate(kind, 1)
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._fx_native_field_observation(SimpleNamespace(), "value")
                    template = MenuTemplate(kind, 1)
                    def unavailable(): raise RuntimeError("menu unavailable")
                    template.menuItems = unavailable
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._fx_native_field_observation(SimpleNamespace(), "value")
                template = NonMenuTemplate("Unknown", 1)
                with self.assertRaises(addon.BridgeCommandError):
                    addon._fx_native_field_observation(SimpleNamespace(), "value")

    def test_planned_nonmenu_observation_does_not_require_menu_labels(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for kind in ("Toggle", "Float", "Folder", "Data", "String", "Int", "Menu"):
            template = SimpleNamespace(type=lambda: "parmTemplateType." + kind, numComponents=lambda: 1)
            if kind in {"String", "Int", "Menu"}: template.menuItems = lambda: ()
            component = SimpleNamespace(isHidden=lambda: False, isDisabled=lambda: False, isLocked=lambda: False,
                                        keyframes=lambda: ())
            parm = SimpleNamespace(parmTemplate=lambda: template, _components=lambda: [component],
                                   isLocked=lambda: False, isDisabled=lambda: False, eval=lambda: 1,
                                   path=lambda: "/stage/import/value")
            with self.subTest(kind=kind), patch.object(addon, "_resolve_parm_target", return_value=parm):
                if kind in {"String", "Int", "Menu"}:
                    with self.assertRaises(AttributeError):
                        addon._fx_planned_observation(SimpleNamespace(), "value", observe_value=False)
                    template.menuLabels = lambda: ("A", "B")
                    actual = addon._fx_planned_observation(SimpleNamespace(), "value", observe_value=False)
                    self.assertEqual(actual["menu_labels"], ("A", "B"))
                else:
                    actual = addon._fx_planned_observation(SimpleNamespace(), "value", observe_value=False)
                    self.assertEqual(actual["menu_labels"], ())
                    self.assertFalse(actual["driven"])
                    self.assertIsNone(actual["value"])

    def test_trusted_output_pattern_readback_is_raw_and_evaluated_at_frozen_frame(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        pattern = "/output/beauty.$F4.exr"
        for role, name, node_type in (("settings", "picture", "Lop/karmarendersettings"),
                                      ("render_product", "productName", "Lop/renderproduct"),
                                      ("render", "outputimage", "Driver/usdrender")):
            state = {"raw": "/output/before.exr", "frame": 1, "bad_eval": False}
            node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: node_type))
            template = SimpleNamespace(type=lambda: "parmTemplateType.String", numComponents=lambda: 1)
            component = SimpleNamespace(node=lambda: node, unexpandedString=lambda: state["raw"])
            def evaluated():
                return "wrong" if state["bad_eval"] else state["raw"].replace("$F4", "0001")
            def set_value(value, *, follow_references=True):
                self.assertFalse(follow_references)
                state["raw"] = value
            parm = SimpleNamespace(kind="parm", component_count=1, _components=lambda: [component],
                                   parmTemplate=lambda: template, name=lambda: name, path=lambda: "/stage/node/" + name,
                                   isDisabled=lambda: False, isLocked=lambda: False, set=set_value, eval=evaluated)
            write = {"role": role, "parm": name, "native_type": "string", "value": pattern}
            with self.subTest(role=role), patch.dict(sys.modules, {"hou": SimpleNamespace(
                    frame=lambda: state["frame"], expandString=lambda value: value.replace("$F4", "0001"))}), \
                    patch.object(addon, "_snapshot_parm_state", return_value={"evaluated": "/output/before.exr"}), \
                    patch.object(addon, "_parm_snapshot_is_driven", return_value=False), \
                    patch.object(addon, "_restore_parm_snapshot", side_effect=lambda *a: state.update(raw="/output/before.exr")) as restore:
                frames = addon._fx_output_pattern_frames(write, node, {"scene": {"frames": [1, 2]}})
                result = addon._set_parm_verified(parm, pattern, output_pattern_frames=frames)
                self.assertEqual(result["after"], "/output/beauty.0001.exr")
                self.assertEqual(result["output_pattern_readback"], {"raw": pattern, "evaluated": result["after"], "frame": 1})
                self.assertEqual(addon._fx_output_pattern_readback(parm, pattern, frames), result["output_pattern_readback"])
                for invalid in ("/output/$HIP/beauty.$F4.exr", "/output/`expr`.$F4.exr", "/output/$F4.$F4.exr", "relative.$F4.exr"):
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._set_parm_verified(parm, invalid, output_pattern_frames=frames)
                    self.assertEqual(state["raw"], "/output/before.exr")
                state["bad_eval"] = True
                with self.assertRaises(addon.BridgeCommandError):
                    addon._set_parm_verified(parm, pattern, output_pattern_frames=frames)
                self.assertEqual(state["raw"], "/output/before.exr")
                state["bad_eval"] = False
                state["raw"] = "/output/beauty.0001.exr"
                with self.assertRaises(ValueError): addon._fx_output_pattern_readback(parm, pattern, frames)
                state["raw"], state["frame"] = pattern, 3
                with self.assertRaises(ValueError): addon._fx_output_pattern_readback(parm, pattern, frames)
                state["frame"] = 1
                with patch.object(sys.modules["hou"], "frame", side_effect=[1, 2]):
                    with self.assertRaises(ValueError): addon._fx_output_pattern_readback(parm, pattern, frames)
                with patch.object(parm, "isLocked", return_value=True):
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._set_parm_verified(parm, pattern, output_pattern_frames=frames)
                with patch.object(template, "numComponents", return_value=True):
                    with self.assertRaises(ValueError): addon._fx_output_pattern_readback(parm, pattern, frames)
                with self.assertRaises(addon.BridgeCommandError): addon._set_parm_verified(parm, pattern)
                self.assertGreater(restore.call_count, 0)
                with patch.object(addon, "_parm_snapshot_is_driven", return_value=True):
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._set_parm_verified(parm, pattern, output_pattern_frames=frames)
                self.assertIsNone(addon._fx_output_pattern_frames(dict(write, role="untrusted"), node, {"scene": {"frames": [1]}}))

    def test_resolution_mode_reads_only_exact_instance_menu_and_keeps_rejection(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for category, name in (("Lop/karmarendersettings", "res_mode"), ("Lop/other", "res_mode"),
                               ("Lop/karmarendersettings", "other")):
            calls = []
            template = SimpleNamespace(type=lambda: "parmTemplateType.String", numComponents=lambda: 1, menuItems=lambda: ())
            component = SimpleNamespace(isHidden=lambda: False, isDisabled=lambda: False, isLocked=lambda: False,
                                        menuItems=lambda: calls.append(True) or ("manual", "autowidth"))
            parm = SimpleNamespace(parmTemplate=lambda: template, _components=lambda: [component],
                                   isLocked=lambda: False, isDisabled=lambda: False, eval=lambda: "manual",
                                   evalAsString=lambda: "manual", path=lambda: "/obj/owned/settings/" + name)
            node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: category), destroy=lambda: None)
            with self.subTest(category=category, name=name), patch.object(addon, "_resolve_parm_target", return_value=parm):
                actual = addon._fx_native_field_observation(node, name)
                selected = category == "Lop/karmarendersettings" and name == "res_mode"
                self.assertEqual(calls, [True] if selected else [])
                self.assertEqual(actual["menu_tokens"], ("manual", "autowidth") if selected else ())
                if not selected: continue
                component.menuItems = lambda: ("autowidth",)
                with patch.dict(sys.modules, {"hou": SimpleNamespace(applicationVersionString=lambda: "21.0.631", node=lambda path: node)}), \
                        patch.object(addon, "_fx_task_paths", return_value=("/obj/owned", "/obj/owned/stage")), \
                        patch.object(addon, "_fx_execution_root", return_value="/obj/owned"), \
                        patch.object(addon, "_task_output_dir", return_value=Path("/output")), \
                        patch.object(native, "trusted_initialization_plan", return_value=[
                            {"role": "settings", "parm": "res_mode", "value": "manual", "native_type": "menu"}]), \
                        patch.object(native, "trusted_node_flag_plan", return_value=[]), \
                        patch.object(addon, "_set_parm_verified") as setter:
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        addon._fx_initialize_render_domain({"task_id": "abc123"}, "material_lookdev_v1",
                            {"source": "/obj/owned/source", "settings": "/obj/owned/settings"}, {}, {"settings"})
                    self.assertIn("native initialization menu token differs", str(caught.exception))
                    self.assertIn("res_mode", str(caught.exception))
                    setter.assert_not_called()
                def unavailable(): raise RuntimeError("menu unavailable")
                component.menuItems = unavailable
                with self.assertRaises(addon.BridgeCommandError): addon._fx_native_field_observation(node, name)

    def test_manual_resolution_callback_requires_exact_identity_and_editable_undriven_result(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for case in ("success", "callback", "language", "exception", "locked", "driven", "mode", "components"):
            calls = []
            actual = {"type": "integer", "size": 2, "hidden": False, "disabled": False, "locked": True}
            mode = {"value": "manual", "hidden": False, "disabled": False, "locked": False}
            def callback():
                calls.append("callback")
                if case == "exception": raise RuntimeError("native callback failed")
                actual["locked"] = case == "locked"
                if case == "mode": mode["value"] = "autoheight"
            template = SimpleNamespace(scriptCallback=lambda: "other()" if case == "callback" else
                                       "__import__('loputils').updateResolutionParameters(hou.pwd(),True)",
                                       scriptCallbackLanguage=lambda: "Hscript" if case == "language" else "scriptLanguage.Python")
            component = SimpleNamespace(pressButton=callback)
            mode_parm = SimpleNamespace(name=lambda: "res_mode", parmTemplate=lambda: template, _components=lambda: [component])
            resolution = SimpleNamespace(_components=lambda: [object()] if case == "components" else [object(), object()])
            node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: "Lop/karmarendersettings"),
                                   updateParmStates=lambda: calls.append("update"))
            with self.subTest(case=case), patch.object(addon, "_fx_native_field_observation", side_effect=lambda node, name: mode if name == "res_mode" else actual), \
                    patch.object(addon, "_resolve_parm_target", return_value=resolution), \
                    patch.object(addon, "_snapshot_parm_state", side_effect=lambda parm: {"driven": case == "driven" and parm is resolution}), \
                    patch.object(addon, "_parm_snapshot_is_driven", side_effect=lambda snapshot: snapshot["driven"]):
                if case == "success":
                    result = addon._fx_initialize_manual_resolution(node, mode_parm)
                    self.assertTrue(result["callback_executed"] and result["resolution_editable_undriven"])
                    self.assertEqual(calls, ["callback", "update"])
                else:
                    with self.assertRaises((addon.BridgeCommandError, RuntimeError)):
                        addon._fx_initialize_manual_resolution(node, mode_parm)
                    if case in {"callback", "language"}: self.assertEqual(calls, [])

    def test_manual_resolution_callback_is_only_invoked_for_fresh_settings(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: "Lop/karmarendersettings"), destroy=lambda: None)
        actual = {"type": "string", "size": 1, "hidden": False, "disabled": False, "locked": False, "menu_tokens": ("manual",)}
        parm = SimpleNamespace(path=lambda: "/obj/owned/settings/res_mode")
        for fresh in (False, True):
            with self.subTest(fresh=fresh), patch.dict(sys.modules, {"hou": SimpleNamespace(applicationVersionString=lambda: "21.0.631", node=lambda path: node)}), \
                    patch.object(addon, "_fx_task_paths", return_value=("/obj/owned", "/obj/owned/stage")), \
                    patch.object(addon, "_fx_execution_root", return_value="/obj/owned"), \
                    patch.object(addon, "_task_output_dir", return_value=Path("/output")), \
                    patch.object(native, "trusted_initialization_plan", return_value=[{"role": "settings", "parm": "res_mode", "value": "manual", "native_type": "menu"}]), \
                    patch.object(native, "trusted_node_flag_plan", return_value=[]), \
                    patch.object(addon, "_fx_native_field_observation", return_value=actual), \
                    patch.object(addon, "_resolve_parm_target", return_value=parm), \
                    patch.object(addon, "_snapshot_parm_state", return_value={}), \
                    patch.object(addon, "_parm_snapshot_is_driven", return_value=False), \
                    patch.object(addon, "_read_parm_for_request", return_value="manual"), \
                    patch.object(addon, "_set_parm_verified", return_value={}), \
                    patch.object(addon, "_fx_initialize_manual_resolution", return_value={"callback_executed": True}) as callback:
                addon._fx_initialize_render_domain({"task_id": "abc123"}, "material_lookdev_v1",
                    {"source": "/obj/owned/source", "settings": "/obj/owned/settings"}, {"controls": {}}, {"settings"} if fresh else set())
                self.assertEqual(callback.call_count, int(fresh))

    def test_absent_manifest_userdata_restoration_is_idempotent_but_other_errors_fail(self):
        from types import SimpleNamespace
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for case in ("absent", "present", "delete_error", "read_error", "silent_delete"):
            data = {} if case == "absent" else {"bridge_fx_manifest_v1": "new", "bridge_fx_pack": "new"}
            calls = []
            def read(key):
                if case == "read_error": raise RuntimeError("read failed")
                return data.get(key)
            def delete(key):
                calls.append(key)
                if case == "delete_error": raise RuntimeError("delete failed")
                if case == "silent_delete": return
                if key not in data: raise RuntimeError("No data exists")
                del data[key]
            root = SimpleNamespace(userData=read, destroyUserData=delete)
            snapshot = {"available": True, "embedded_manifest": None, "embedded_pack": None}
            with self.subTest(case=case):
                if case in {"absent", "present"}:
                    addon._fx_restore_manifest_persistence(root, snapshot)
                    addon._fx_restore_manifest_persistence(root, snapshot)
                    self.assertEqual(data, {})
                    self.assertEqual(len(calls), 0 if case == "absent" else 2)
                else:
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        addon._fx_restore_manifest_persistence(root, snapshot)
                    self.assertEqual(caught.exception.code, "CANDIDATE_MANIFEST_ROLLBACK_FAILED")

    def test_exr_attribute_diagnostics_distinguish_missing_type_and_native_failure(self):
        from types import SimpleNamespace
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for case in ("valid", "missing", "wrong_type", "get_error", "long_value"):
            calls = []
            def get(frame):
                calls.append(frame)
                if case == "get_error": raise RuntimeError("native read failed")
                return False if case == "wrong_type" else "x" * 200 if case == "long_value" else 0
            attribute = None if case == "missing" else SimpleNamespace(
                GetTypeName=lambda: "token" if case == "wrong_type" else "string" if case == "long_value" else "int", Get=get)
            product = SimpleNamespace(GetAttribute=lambda name: attribute)
            with self.subTest(case=case):
                if case == "valid":
                    self.assertEqual(addon._fx_exr_attribute_value(product, "multipart", "int", 2), 0)
                else:
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        addon._fx_exr_attribute_value(product, "multipart", "int", 2)
                    self.assertEqual(caught.exception.code, "RENDER_CONFIG_INVALID")
                    self.assertIsNotNone(caught.exception.__cause__)
                    message = str(caught.exception)
                    self.assertIn("multipart", message)
                    if case == "missing":
                        self.assertIn("'exists': False", message)
                        self.assertEqual(calls, [])
                    elif case == "wrong_type":
                        self.assertIn("'usd_type': 'token'", message)
                        self.assertIn("'value_type': 'bool'", message)
                        self.assertIn("'value': 'False'", message)
                    elif case == "long_value": self.assertNotIn("x" * 161, message)

    def test_multipart_schema_bool_and_legacy_int_require_exact_false_or_zero(self):
        from types import SimpleNamespace
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        for kind, value, accepted in (("bool", False, True), ("int", 0, True), ("bool", True, False),
                                       ("bool", 0, False), ("int", False, False), ("int", 0.0, False),
                                       ("int", 1, False), ("string", "0", False), ("bool", None, False)):
            attribute = SimpleNamespace(GetTypeName=lambda: kind, Get=lambda frame: value)
            product = SimpleNamespace(GetAttribute=lambda name: attribute)
            with self.subTest(kind=kind, value=value):
                if accepted:
                    observed = addon._fx_exr_attribute_value(product, "multipart", "int", 1)
                    self.assertIs(type(observed), int)
                    self.assertEqual(observed, 0)
                else:
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        addon._fx_exr_attribute_value(product, "multipart", "int", 1)
                    self.assertEqual(caught.exception.code, "RENDER_CONFIG_INVALID")
                    self.assertIn("usd_type", str(caught.exception))
                    self.assertIn("value_type", str(caught.exception))

    def test_stable_output_directory_cannot_bypass_native_gates(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: "Driver/usdrender"), destroy=lambda: None)
        parm = SimpleNamespace(path=lambda: "/obj/owned/render/savetodirectory_directory")
        write = {"role": "render", "parm": "savetodirectory_directory", "value": "/output/task", "native_type": "string"}
        for field, gate in ((field, gate) for field in ("savetodirectory_directory", "husk_tiletempdir")
                            for gate in ("hidden", "disabled", "locked")):
            write["parm"] = field
            actual = {"type": "string", "size": 1, "hidden": False, "disabled": False, "locked": False,
                      "menu_tokens": ("BRAY_HdKarma",)}
            actual[gate] = True
            with self.subTest(gate=gate), patch.dict(sys.modules, {"hou": SimpleNamespace(applicationVersionString=lambda: "21.0.631", node=lambda path: node)}), \
                    patch.object(addon, "_fx_task_paths", return_value=("/obj/owned", "/obj/owned/stage")), \
                    patch.object(addon, "_fx_execution_root", return_value="/obj/owned"), \
                    patch.object(addon, "_task_output_dir", return_value=Path("/output/task")), \
                    patch.object(native, "renderer_parameter", return_value="renderer"), \
                    patch.object(native, "trusted_initialization_plan", return_value=[write]), \
                    patch.object(native, "trusted_node_flag_plan", return_value=[]), \
                    patch.object(addon, "_fx_native_field_observation", return_value=actual), \
                    patch.object(addon, "_resolve_parm_target", return_value=parm), \
                    patch.object(addon, "_set_parm_verified") as setter:
                with self.assertRaises(addon.BridgeCommandError) as caught:
                    addon._fx_initialize_render_domain({"task_id": "abc123"}, "material_lookdev_v1",
                        {"source": "/obj/owned/source", "render": "/obj/owned/render"}, {}, {"render"})
                self.assertEqual(caught.exception.code, "NATIVE_CONTROL_GATE_BLOCKED")
                self.assertIn(repr(gate) + ": True", str(caught.exception))
                setter.assert_not_called()

    def test_initializer_menu_rejection_reports_bounded_actual_context(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_houdini_parm_probe import _load_addon
        addon = _load_addon()
        node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: "Sop/grid"), destroy=lambda: None)
        actual = {"type": "string", "size": 1, "hidden": False, "disabled": False, "locked": False,
                  "menu_tokens": tuple("actual-token-" + str(i) + "x" * 100 for i in range(30))}
        write = {"role": "ground", "parm": "orient", "value": "requested-token", "native_type": "menu"}
        with patch.dict(sys.modules, {"hou": SimpleNamespace(applicationVersionString=lambda: "21.0.631", node=lambda path: node)}), \
                patch.object(addon, "_fx_task_paths", return_value=("/obj/owned", "/obj/owned/stage")), \
                patch.object(addon, "_fx_execution_root", return_value="/obj/owned"), \
                patch.object(addon, "_task_output_dir", return_value=Path("/output")), \
                patch.object(native, "trusted_initialization_plan", return_value=[write]), \
                patch.object(native, "trusted_node_flag_plan", return_value=[]), \
                patch.object(addon, "_fx_native_field_observation", return_value=actual), \
                patch.object(addon, "_resolve_parm_target", return_value=SimpleNamespace()), \
                patch.object(addon, "_set_parm_verified") as setter:
            with self.assertRaises(addon.BridgeCommandError) as caught:
                addon._fx_initialize_render_domain({"task_id": "abc123"}, "material_lookdev_v1",
                                                  {"source": "/obj/owned/source", "ground": "/obj/owned/ground"}, {}, {"ground"})
            self.assertEqual(caught.exception.code, "NATIVE_CONTROL_INTERFACE_REQUIRED")
            message = str(caught.exception)
            for value in ("ground", "orient", "Sop/grid", "requested-token", "actual_type", "string", "size", "actual-token-23"):
                self.assertIn(value, message)
            self.assertNotIn("actual-token-24", message)
            self.assertNotIn("x" * 81, message)
            setter.assert_not_called()

    def test_renderer_machine_id_is_exact_and_requires_actual_typed_menu(self):
        observation={'origin':'runtime_hom','type':'string','size':1,'menu_tokens':['BRAY_HdKarma']}
        for version in native.SUPPORTED_VERSIONS:
            self.assertEqual(native.renderer_parameter(version,{'renderer':observation}),'renderer')
            self.assert_code('USD_RENDERER_INTERFACE_REQUIRED',native.renderer_parameter,version,{'renderdelegate':observation})
            self.assert_code('USD_RENDERER_INTERFACE_REQUIRED',native.renderer_parameter,version,{'renderer':dict(observation,type='integer')})
            self.assert_code('USD_RENDERER_INTERFACE_REQUIRED',native.renderer_parameter,version,{'renderer':dict(observation,size=2)})
            self.assert_code('USD_RENDERER_INTERFACE_REQUIRED',native.renderer_parameter,version,{'renderer':dict(observation,origin='static_ui')})

    def test_overlay_preserves_existing_contract_without_mutating_source(self):
        controls=native.control_contract(native.MATERIAL,'21.0.631')
        pack={'controls':{n:{'invalidates_from':'material'} for n in controls},'evidence':['normal_aov'],'simulation_cache':False}
        snapshot=copy.deepcopy(pack)
        result=native.overlay_host_pack(native.MATERIAL,pack,'21.0.631')
        self.assertEqual(pack,snapshot)
        self.assertEqual(result['evidence'],snapshot['evidence'])
        self.assertTrue(all(c['invalidates_from']=='material' for c in result['controls'].values()))
        del pack['controls']['normal_strength']
        self.assert_code('PUBLIC_CONTROL_CONTRACT_CHANGED',native.overlay_host_pack,native.MATERIAL,pack,'21.0.631')

    def test_core_descriptor_overlay_keeps_metrics_evidence_and_public_controls(self):
        for pack in DOMAIN_PACKS:
            if pack.identifier not in (native.MATERIAL,native.LIGHTING):continue
            original=pack.to_dict(); snapshot=copy.deepcopy(original)
            result=native.overlay_core_pack_dict(original,'21.0.631')
            self.assertEqual(original,snapshot)
            self.assertEqual(result['metrics'],original['metrics'])
            self.assertEqual(result['evidence'],original['evidence'])
            self.assertEqual([c['id'] for c in result['controls']],[c['id'] for c in original['controls']])
            self.assertEqual(result['maturity'],original['maturity'])
            self.assertEqual(result['validated_houdini_versions'],original['validated_houdini_versions'])
            self.assertTrue(all('type_candidates' in n for n in result['nodes']))

    def test_unknown_version_and_unproven_core_are_explicit_blockers(self):
        self.assert_code('UNSUPPORTED_NATIVE_VERSION',native.control_contract,native.LIGHTING,'20.5.0')
        blockers=native.static_blockers(native.MATERIAL,'21.0.631')
        self.assertIn('assignmaterial',{b.get('operator','/').split('/')[-1] for b in blockers})
        self.assertTrue(any(b['code']=='NATIVE_RENDER_EXECUTION_NOT_RUN' for b in blockers))
        self.assertTrue(any(b['code']=='EXTERNAL_DENOISE_BLEND_REQUIRED' for b in native.static_blockers(native.LIGHTING,'22.0.429')))
