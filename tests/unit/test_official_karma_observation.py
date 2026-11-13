"""Bottom HOM/USD fixtures only; these tests do not attest native execution."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from houdini_bridge import official_karma_native as native
from houdini_bridge import official_karma_observation as evidence
from houdini_bridge import official_karma_worker as worker
from houdini_bridge.official_karma import SELECTED_TYPES
from dcc_task_runtime.render_profiles import OFFICIAL,SOURCE_HIP_SHA256

ROOT=Path(__file__).resolve().parents[2]


class Template:
    def __init__(self,name,label='',size=1,default_value=('',),menu_items=(),menu_labels=(),kind='String'):
        self._name=name; self.size=size; self.kind=kind; self._tags={}; self.default=default_value
    def name(self): return self._name
    def type(self): return SimpleNamespace(name=lambda:self.kind)
    def numComponents(self): return self.size
    def tags(self): return dict(self._tags)
    def setTags(self,v): self._tags=dict(v)
    def asCode(self): return json.dumps([self._name,self.kind,self.size,self._tags],sort_keys=True)


class Group:
    def __init__(self): self.items={}
    def find(self,name): return self.items.get(name)
    def append(self,v): self.items[v.name()]=v


class Parm:
    def __init__(self,name,template,value=None):
        self._name=name; self.template=template; self.value=template.default[0] if value is None else value
        self.keys=[]; self.locked=False
    def isLocked(self): return self.locked
    def isDisabled(self): return False
    def name(self): return self._name
    def parmTemplate(self): return self.template
    def keyframes(self): return tuple(self.keys)
    def deleteAllKeyframes(self): self.keys=[]
    def set(self,value,**kwargs): self.value=value
    def eval(self): return self.value
    def unexpandedString(self): return str(self.value)
    def isMultiParmParent(self): return False


class OrdinalMenu(Parm):
    """HOM ordinal menu: native eval is int, token readback is separate."""
    def __init__(self,name='createprims',items=('on','off')):
        super().__init__(name,Template(name,default_value=(0,),kind='Menu'),0)
        self.items=items
    def menuItems(self): return self.items
    def evalAsString(self): return self.items[self.value]
    def set(self,value,**kwargs): self.value=self.items.index(value) if type(value) is str else value


class Node:
    def __init__(self): self.group=Group(); self.parms={}; self.kind='editproperties'
    def type(self): return SimpleNamespace(name=lambda:self.kind)
    def parmTemplateGroup(self): return self.group
    def setParmTemplateGroup(self,group):
        self.group=group
        for name,t in group.items.items(): self.parms.setdefault(name,Parm(name,t))
    def parm(self,name): return self.parms.get(name)


def hou_api():
    def toggle(name,label='',default_value=True):
        return Template(name,label,default_value=(int(default_value),),kind='Toggle')
    return SimpleNamespace(text=SimpleNamespace(encodeParm=lambda s:s.replace(':','_')),
                           StringParmTemplate=Template,ToggleParmTemplate=toggle)


class OutputAuthorTests(unittest.TestCase):
    def test_fixed_attributes_use_typed_templates_and_reentry_is_idempotent(self):
        node=Node(); hou=hou_api()
        result=native.configure_output(hou,node)
        self.assertEqual(set(result),set(native.OUTPUT_ATTRIBUTES))
        self.assertEqual(len(node.parms),10)
        for prop,(_,typ,value) in native.OUTPUT_ATTRIBUTES.items():
            parm=node.parm(hou.text.encodeParm(prop))
            self.assertEqual(parm.eval(),value)
            self.assertEqual(parm.parmTemplate().tags(),{'usdvaluetype':typ})
        self.assertEqual(native.configure_output(hou,node),result)
        self.assertEqual(len(node.parms),10)

    def test_beauty_adapter_has_exact_typed_output_only_fields_and_rejects_drift(self):
        node=Node();hou=hou_api()
        for name,value in (('primpattern',''),('createprims','on')):
            node.group.append(Template(name,default_value=(value,)))
        node.setParmTemplateGroup(node.group)
        node.parms['createprims']=OrdinalMenu()
        node.path=lambda:native.BEAUTY_ADAPTER
        node.errors=lambda:();node.warnings=lambda:()
        source='/stage/lights/update_output_image_path'
        node.inputConnections=lambda:(SimpleNamespace(inputIndex=lambda:0,outputIndex=lambda:0,
            inputNode=lambda:SimpleNamespace(path=lambda:source)),)
        native.configure_beauty(hou,node)
        actual=native.beauty_author_readback(hou,node,source)
        self.assertEqual(actual['primpattern'],'/Render/Products/Vars/Beauty')
        self.assertEqual(actual['attributes']['driver:parameters:aov:husk:format'],
            {'type':'token','value':'color4h','control':'set'})
        self.assertEqual(len(node.parms),6)
        node.parm('primpattern').set(native.PRODUCT)
        with self.assertRaisesRegex(ValueError,'FIELD_DRIFT'):
            native.beauty_author_readback(hou,node,source)

    def test_ordinal_menu_reproduces_failure_and_writes_the_declared_token_without_assuming_zero(self):
        node=Node();node.parms['createprims']=OrdinalMenu()
        parm=node.parm('createprims')
        with self.assertRaisesRegex(ValueError,'FIELD_READBACK:createprims'):
            native.scalar_write(node,'createprims','off')
        self.assertEqual(parm.eval(),1)
        parm.keys=['animated'];parm.value=0
        fact=native.menu_token_write(node,'createprims','off')
        self.assertEqual(fact,{'field':'createprims','token':'off','index':1,'dynamic':False})
        self.assertEqual(parm.keyframes(),())
        self.assertEqual(parm.evalAsString(),'off')
        parm.value=0
        with self.assertRaisesRegex(ValueError,'MENU_READBACK'):
            native.menu_token_readback(node,'createprims','off')
        with self.assertRaisesRegex(ValueError,'TOKEN_REQUIRED'):
            native.menu_token_write(node,'createprims','missing')
        parm.locked=True
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            native.menu_token_write(node,'createprims','off')

    def test_wrong_node_conflicting_template_and_locked_write_are_rejected(self):
        hou=hou_api(); node=Node(); node.kind='karmarenderproperties'
        with self.assertRaisesRegex(ValueError,'AUTHOR_TYPE'): native.configure_output(hou,node)
        node=Node(); name=hou.text.encodeParm(next(iter(native.OUTPUT_ATTRIBUTES)))
        node.group.append(Template(name,kind='Float'))
        with self.assertRaisesRegex(ValueError,'TEMPLATE_CONFLICT'): native.configure_output(hou,node)
        node=Node(); native.configure_output(hou,node); node.parm(name).locked=True
        with self.assertRaisesRegex(ValueError,'FIELD_UNAVAILABLE'): native.configure_output(hou,node)

    def test_declared_edit_removes_animation_and_checks_concrete_readback(self):
        node=Node(); node.group.append(Template('input',default_value=(0,),kind='Int'))
        node.setParmTemplateGroup(node.group); node.parm('input').keys=['$F-1']
        self.assertEqual(native.scalar_write(node,'input',1),{'field':'input','value':1,'dynamic':False})
        self.assertEqual(node.parm('input').keyframes(),())
        with self.assertRaisesRegex(ValueError,'FIELD_UNAVAILABLE'): native.scalar_write(node,'missing',1)


class Ramp:
    """Exact return shape of H21 ParmTuple.eval for a ramp, not an iterable."""
    def basis(self): return (SimpleNamespace(__str__=lambda:'Linear'),)
    def keys(self): return (0.,1.)
    def values(self): return (.25,.75)


class NativeShapeTests(unittest.TestCase):
    def test_hom_ramp_return_is_encoded_as_one_typed_component(self):
        class Basis:
            def __str__(self): return 'hou.rampBasis.Linear'
        ramp=Ramp();ramp.basis=lambda:(Basis(),Basis())
        template=Template('ramp',kind='Ramp')
        scalar=Parm('ramp',template,ramp)
        scalar.isMultiParmParent=lambda:True
        class Tuple:
            calls=0
            def __iter__(self): return iter((scalar,))
            def __getitem__(self,index): return (scalar,)[index]
            def parmTemplate(self): return template
            def name(self): return 'ramp'
            def eval(self): raise AssertionError('unexpected untyped evaluation')
            def evalAsRamps(self):
                self.calls+=1
                return (ramp,)
        parm=Tuple()
        expected=[{'ramp_basis':['Linear','Linear'],'keys':[0.,1.],'values':[.25,.75]}]
        with patch.dict(sys.modules,{'hou':SimpleNamespace(Ramp=Ramp)}):
            self.assertEqual(native.parameter_value(parm,'Ramp'),expected)
            captured=native.capture_parameters(SimpleNamespace(parmTuples=lambda:(parm,)))
            self.assertEqual(captured['ramp']['value'],expected)
            from houdini_bridge.official_karma_scene_host import _native_write
            hou=SimpleNamespace(rampBasis=SimpleNamespace(Linear='Linear'),
                Ramp=lambda basis,keys,values: ramp)
            _native_write(hou,parm,expected,'Ramp')
        self.assertEqual(parm.calls,3)
        self.assertIs(scalar.value,ramp)

    def test_ramp_invalid_shapes_fail_without_reevaluation(self):
        for result in (None, [], (), (object(),), (Ramp(), Ramp())):
            calls=[]
            parm=SimpleNamespace(evalAsRamps=lambda: (calls.append(1),result)[1])
            with self.subTest(result=result), patch.dict(sys.modules,{'hou':SimpleNamespace(Ramp=Ramp)}):
                with self.assertRaisesRegex(ValueError,'OFFICIAL_NATIVE_RAMP_SHAPE_INVALID'):
                    native.parameter_value(parm,'Ramp')
                self.assertEqual(calls,[1])

    def test_ramp_failure_context_and_non_ramp(self):
        template=Template('ramp',kind='Ramp')
        scalar=Parm('ramp',template)
        class Tuple:
            def __iter__(self): return iter((scalar,))
            def parmTemplate(self): return template
            def name(self): return 'ramp'
            def evalAsRamps(self): raise RuntimeError('failure')
        node=SimpleNamespace(path=lambda:'/stage/test',parmTuples=lambda:(Tuple(),))
        with patch.dict(sys.modules,{'hou':SimpleNamespace(Ramp=Ramp)}):
            with self.assertRaises(RuntimeError) as caught:
                native.capture_parameters(node)
        context=native.validate_ramp_failure_context(caught.exception.official_ramp_context)
        self.assertEqual(context['node'],'/stage/test')
        self.assertEqual(context['parameter'],'ramp')
        self.assertEqual(native.parameter_value(SimpleNamespace(eval=lambda:(1,2)),'Int'),[1,2])
        with self.assertRaisesRegex(ValueError,'CONTEXT_INVALID'):
            native.validate_ramp_failure_context({})

    def test_ramp_boundaries_and_rgb_capture(self):
        class Basis:
            def __str__(self): return 'hou.rampBasis.Linear'
        class Tuple:
            def __init__(self,ramp):
                self.ramp=ramp; self.calls=0
                self.template=Template('ramp',kind='Ramp')
                self.scalar=Parm('ramp',self.template,ramp)
            def __iter__(self): return iter((self.scalar,))
            def __getitem__(self,index): return (self.scalar,)[index]
            def parmTemplate(self): return self.template
            def name(self): return 'ramp'
            def evalAsRamps(self): self.calls+=1; return (self.ramp,)
        for count in (1,2,64,65):
            ramp=Ramp(); ramp.basis=lambda:(Basis(),)*count
            ramp.keys=lambda:tuple(float(i) for i in range(count))
            ramp.values=lambda:tuple((.1,.2,.3) for _ in range(count))
            parm=Tuple(ramp)
            node=SimpleNamespace(path=lambda:'/stage/test',parmTuples=lambda:(parm,))
            with self.subTest(count=count), patch.dict(sys.modules,{'hou':SimpleNamespace(Ramp=Ramp)}):
                if 2<=count<=64:
                    value=native.capture_parameters(node)['ramp']['value']
                    self.assertEqual(value[0]['values'][0],[.1,.2,.3])
                    from houdini_bridge.official_karma_scene_host import _native_write
                    constructed=[]
                    def make_ramp(basis,keys,values):
                        constructed.append((basis,keys,values))
                        return ramp
                    _native_write(SimpleNamespace(rampBasis=SimpleNamespace(Linear='Linear'),
                        Ramp=make_ramp),parm,value,'Ramp')
                    self.assertEqual(constructed[0][2],tuple((.1,.2,.3) for _ in range(count)))
                    self.assertEqual(parm.calls,2)
                else:
                    with self.assertRaisesRegex(ValueError,'RAMP_INVALID') as caught:
                        native.capture_parameters(node)
                    self.assertEqual(caught.exception.official_ramp_context['parameter'],'ramp')
                    self.assertEqual(parm.calls,1)

    def test_ramp_invalid_data_preserves_context(self):
        class Basis:
            def __init__(self,name): self.name=name
            def __str__(self): return 'hou.rampBasis.'+self.name
        class Tuple:
            def __init__(self,ramp):
                self.ramp=ramp; self.calls=0
                self.template=Template('ramp',kind='Ramp')
                self.scalar=Parm('ramp',self.template,ramp)
            def __iter__(self): return iter((self.scalar,))
            def parmTemplate(self): return self.template
            def name(self): return 'ramp'
            def evalAsRamps(self): self.calls+=1; return (self.ramp,)
        cases=[((),(),()), ((0.,1.),('Linear','Linear'),(float('nan'),1.)),
               ((1.,0.),('Linear','Linear'),(0.,1.)), ((0.,1.),('Bad','Linear'),(0.,1.))]
        for keys,bases,values in cases:
            ramp=Ramp(); ramp.keys=lambda:keys
            ramp.basis=lambda:tuple(Basis(x) for x in bases); ramp.values=lambda:values
            parm=Tuple(ramp)
            with self.subTest(keys=keys,bases=bases), patch.dict(sys.modules,{'hou':SimpleNamespace(Ramp=Ramp)}):
                with self.assertRaises(ValueError) as caught:
                    native.capture_parameters(SimpleNamespace(path=lambda:'/stage/test',parmTuples=lambda:(parm,)))
                self.assertEqual(native.validate_ramp_failure_context(caught.exception.official_ramp_context)['parameter'],'ramp')
                self.assertEqual(parm.calls,1)

    def test_all_proof_modules_are_mandatory_frozen_dependencies(self):
        paths=evidence.required_source_paths()
        expected=[ROOT/'packages/dcc-task-runtime/src/dcc_task_runtime'/name
                  for name in ('alpha_calibration.py','exr_codec.py','process_image.py')]
        expected += [ROOT/'packages/houdini-bridge/src/houdini_bridge'/name
                     for name in ('controlled_output.py','official_karma_scene_host.py','operation_receipts.py')]
        self.assertTrue(set(expected)<=set(paths))
        # Supplying every other source cannot excuse one missing proof module.
        for path in expected:
            case={'observer':evidence.file_record(Path(worker.__file__)),
                  'source_freeze':{str(p):'a'*64 for p in paths if p!=path}}
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'FREEZE_INCOMPLETE'):
                evidence.require_frozen_sources(case)


class ObservationContractTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/private/tmp'); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve(); self.scope={'path':str(self.root/'scope.json'),'sha256':'a'*64}
        nodes={'/'+p:{'native_type':t,'inputs':[],'display':False,'render':False} for p,t in SELECTED_TYPES.items()}
        nodes['/stage/lights/OUT_karma_lights']['inputs']=[{'input':0,'source':'update_output_image_path','output':0}]
        self.contract=evidence.write_new(self.root/'source.json',{'profile':OFFICIAL,'source_sha256':SOURCE_HIP_SHA256,'nodes':nodes})
        self.value=self.observation(nodes)

    @staticmethod
    def parm(kind,values):
        n=len(values)
        return {'kind':kind,'multiparm':False,'components':n,'value':values,'template_sha256':'b'*64,
                'locked':[False]*n,'disabled':[None]*n,'raw_channels':[None]*n,'keyframe_counts':[0]*n}

    def observation(self,nodes):
        rows={p:{'type':v['native_type'],'parameters':{},'inputs':[],'flags':
              {'display':False,'render':False} if '/sopnet/create/' in p else None} for p,v in nodes.items()}
        rows['/stage/lights/OUT_karma_lights']['inputs']=[{'input':0,'source':native.BEAUTY_ADAPTER,'output':0}]
        requirements={'/stage/lights/switch3':{'input':('Int',[1])},
            '/stage/lights/karmarendersettings':{'engine':('String',['cpu']),'resolution':('Int',[420,300]),
                'denoiser':('String',['off']),'enablemblur':('Toggle',[0])},
            '/stage/lights/disklight':{'lighttype':('Menu',[2])}}
        for path,parms in requirements.items():
            rows[path]['parameters']={name:self.parm(kind,values) for name,(kind,values) in parms.items()}
        def prim(typ):
            return {'type':typ,'attributes':{},'relationships':{},'world_matrix':None,'material_binding':None,
                    'active':True,'instanceable':False,'kind':None}
        stage={'metadata':{},'prims':{'/Mesh':prim('Mesh'),'/Camera':prim('Camera'),'/Disk':prim('DiskLight')}}
        return {'schema':native.OBSERVATION_SCHEMA,'profile':OFFICIAL,'version':'21.0.631','frame':1,
            'scope_sha256':self.scope['sha256'],'source_sha256':SOURCE_HIP_SHA256,
            'source_contract_sha256':self.contract['sha256'],'nodes':rows,
            'capture_policy':{'schema':'bridge.official-karma-parameter-capture/1','ui_disabled':'NOT_EVALUATED',
                'omissions':[{'node':native.UI_PROBE_NODE,'parameter':native.UI_PROBE_PARM,'kind':'Toggle','components':1,
                    'template_sha256':'e'*64,'hidden':True,'expression_language':'Python','source_expression':native.UI_PROBE_EXPRESSION,'reason':native.UI_PROBE_REASON,
                    'input_count':0,'value_status':'NOT_EVALUATED'}]},
            'sopcreate_import':{name:{'type':kind,'parameters':{}} for name,kind in
                (('sopimport','sopimport'),('xform','xform'),('loftpayloadinfo1','loftpayloadinfo'))},
            'output_adapter':{'path':native.BEAUTY_ADAPTER,'type':'editproperties','input':'/stage/lights/update_output_image_path',
                'primpattern':native.BEAUTY,'createprims':'off','attributes':{p:{'type':t,'value':v,'control':'set'}
                    for p,(_k,t,v) in native.BEAUTY_ATTRIBUTES.items()}},
            'output_topology':native.output_topology(),
            'stage':stage,'output':str(self.root/'official.exr'),'resources':[]}

    def validate(self,value):
        return evidence.validate_observation(value,scope_binding=self.scope,source_contract=self.contract)

    def test_complete_typed_fixture_is_detached_and_not_native_authority(self):
        result=self.validate(self.value)
        self.assertEqual(len(result['nodes']),31)
        result['nodes'].clear(); self.assertEqual(len(self.value['nodes']),31)
        with self.assertRaises(ValueError):
            evidence.read_sealed({'associated':True,'state':'PASS'},expected_scope=self.scope)

    def test_native_disk_menu_contract_is_exact_and_reconstruction_checks_template(self):
        path='/stage/lights/disklight'
        self.assertEqual(self.validate(self.value)['nodes'][path]['parameters']['lighttype']['value'],[2])
        for kind,values in (('Menu',[0]),('Menu',[1]),('Menu',[3]),('String',['UsdLuxDiskLight']),('Menu',[2.0])):
            value=copy.deepcopy(self.value)
            value['nodes'][path]['parameters']['lighttype']=self.parm(kind,values)
            with self.subTest(kind=kind,values=values),self.assertRaises(ValueError):
                self.validate(value)
        from houdini_bridge.official_karma_scene_host import _target
        template=Template('lighttype',kind='Menu')
        scalar=Parm('lighttype',template,2)
        class Tuple:
            def __iter__(self): return iter((scalar,))
            def parmTemplate(self): return template
        parm=Tuple(); node=SimpleNamespace(path=lambda:'/obj/light',parmTuple=lambda name:parm)
        field=self.parm('Menu',[2]);field['template_sha256']=hashlib.sha256(template.asCode().encode()).hexdigest()
        self.assertIs(_target(None,node,'lighttype',field),parm)
        template.kind='Int'
        with self.assertRaisesRegex(ValueError,'TEMPLATE_MISMATCH'):
            _target(None,node,'lighttype',field)
        template.kind='Menu';template._tags['drift']='changed'
        with self.assertRaisesRegex(ValueError,'TEMPLATE_MISMATCH'):
            _target(None,node,'lighttype',field)

    def test_export_topology_contract_rejects_old_or_extra_wires(self):
        self.assertEqual(self.validate(self.value)['output_topology'],native.output_topology())
        rop='/stage/lights/OUT_karma_lights'
        for inputs in ([],[{'input':0,'source':'/stage/lights/update_output_image_path','output':0}],
                       [{'input':0,'source':native.BEAUTY_ADAPTER,'output':1}],
                       [{'input':0,'source':native.BEAUTY_ADAPTER,'output':0},{'input':1,'source':native.BEAUTY_ADAPTER,'output':0}]):
            value=copy.deepcopy(self.value);value['nodes'][rop]['inputs']=inputs
            with self.subTest(inputs=inputs),self.assertRaisesRegex(ValueError,'CONNECTION_MISMATCH'):
                self.validate(value)
        value=copy.deepcopy(self.value);value['output_topology']['source']='/foreign'
        with self.assertRaisesRegex(ValueError,'OUTPUT_TOPOLOGY_MISMATCH'):
            self.validate(value)
        value=copy.deepcopy(self.value);value['schema']='bridge.official-karma-observation/2'
        with self.assertRaisesRegex(ValueError,'BINDING_MISMATCH'):
            self.validate(value)
        with self.assertRaisesRegex(ValueError,'SOURCE_EXPORT_CONNECTION_MISMATCH'):
            native.observation_inputs(rop,{'inputs':[]})

    def test_missing_wrong_scope_scene_downgrade_and_unexplained_material_refused(self):
        for failure in ('missing-node','wrong-scope','missing-importer','bad-wire','empty-critical','wrong-size',
                        'float-as-int','nan','not-disk','material','resource','wrong-source','bad-adapter','broad-omission','fake-ui-state'):
            value=copy.deepcopy(self.value)
            if failure=='missing-node': value['nodes'].pop('/stage/lights/disklight')
            elif failure=='wrong-scope': value['scope_sha256']='c'*64
            elif failure=='missing-importer': value['sopcreate_import'].pop('xform')
            elif failure=='bad-wire': value['nodes']['/stage/lights/disklight']['inputs']=[{'input':0,'source':'/foreign','output':0}]
            elif failure=='empty-critical': value['nodes']['/stage/lights/karmarendersettings']['parameters'].clear()
            elif failure=='wrong-size': value['nodes']['/stage/lights/karmarendersettings']['parameters']['resolution']['value']=[128,128]
            elif failure=='float-as-int': value['nodes']['/stage/lights/switch3']['parameters']['input']['value']=[1.]
            elif failure=='nan': value['stage']['prims']['/Mesh']['attributes']['points']={'value':[float('nan')]}
            elif failure=='not-disk': value['stage']['prims']['/Disk']['type']='SphereLight'
            elif failure=='material': value['stage']['prims']['/Mesh']['relationships']['material:binding']=['/Material']
            elif failure=='resource': value['resources']=[{'path':str(self.root/'missing'),'bytes':1,'sha256':'d'*64}]
            elif failure=='broad-omission':value['capture_policy']['omissions'].append(copy.deepcopy(value['capture_policy']['omissions'][0]))
            elif failure=='fake-ui-state':value['nodes']['/stage/lights/switch3']['parameters']['input']['disabled']=[False]
            elif failure=='bad-adapter':value['output_adapter']['primpattern']='/Render/Products/Vars/beauty'
            else: value['source_contract_sha256']='f'*64
            with self.subTest(failure=failure),self.assertRaises((ValueError,OSError)):
                self.validate(value)

    def test_duplicate_json_changed_files_hardlinks_and_symlinks_are_refused(self):
        path=self.root/'data.json'; path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError,'DUPLICATE'): evidence.load_record(evidence.file_record(path))
        record=evidence.file_record(path); path.write_text('{}')
        with self.assertRaises(ValueError): evidence.checked_bytes(record)
        link=self.root/'link';link.symlink_to(path)
        with self.assertRaises(ValueError): evidence.file_record(link)
        hard=self.root/'hard'; hard.hardlink_to(path)
        with self.assertRaises(ValueError): evidence.file_record(path)

    def test_semantics_check_primvars_indices_and_int_topology_before_pass(self):
        def doc(output):
            return {'prims':{native.PRODUCT:{'attributes':{'productName':{'value':output}}},
                 '/Mesh':{'attributes':{'primvars:displayColor':{'type':'color3f[]','authored':True,
                   'value':[[.75,.75,.75]],'interpolation':'constant'},
                   'primvars:displayColor:indices':{'value':[0,0,0]},'faceVertexCounts':{'value':[4]}}}}}
        a,b=doc('a.exr'),doc('b.exr')
        options={'reference_output':'a.exr','actual_output':'b.exr'}
        self.assertEqual(native.semantic_compare(a,b,**options)['state'],'PASS')
        b['prims']['/Mesh']['attributes']['primvars:displayColor']['value'][0][0]+=.0000001
        self.assertEqual(native.semantic_compare(a,b,**options)['state'],'PASS')
        b['prims']['/Mesh']['attributes']['primvars:displayColor:indices']['value'][0]=1
        self.assertEqual(native.semantic_compare(a,b,**options)['state'],'FAIL')
        b=doc('b.exr');b['prims']['/Mesh']['attributes']['faceVertexCounts']['value']=[4.]
        self.assertEqual(native.semantic_compare(a,b,**options)['state'],'FAIL')
        with self.assertRaisesRegex(ValueError,'OUTPUT_IDENTITY'):
            native.semantic_compare(a,doc('wrong.exr'),**options)

    def test_export_up_axis_equivalence_is_explicit_directional_and_bounded(self):
        def doc(authored,value='Y'):
            return {'metadata':{'upAxis':{'authored':authored,'value':value},
                                'metersPerUnit':{'authored':True,'value':1.0}},
                    'prims':{native.PRODUCT:{'attributes':{'productName':{'value':'a.exr'}}}}}
        reference,actual=doc(False),doc(True)
        kwargs={'reference_output':'a.exr','actual_output':'a.exr'}
        self.assertEqual(native.semantic_compare(reference,actual,**kwargs)['state'],'FAIL')
        result=native.semantic_compare(reference,actual,export_up_axis_policy='h21_export_fallback_y_v1',**kwargs)
        self.assertEqual(result['state'],'PASS')
        self.assertEqual(len(result['representation_equivalences']),1)
        self.assertEqual(reference,doc(False));self.assertEqual(actual,doc(True))
        self.assertNotEqual(result['reference_sha256'],result['actual_sha256'])
        cases=[(doc(False),doc(True,'Z')),(doc(False,'Z'),doc(True,'Z')),
               (doc(True),doc(False)),(doc(0),doc(True)),(doc(False),doc(1))]
        missing=doc(True);del missing['metadata']['upAxis']['value']
        extra=doc(True);extra['metadata']['upAxis']['extra']=True
        cases.extend([(doc(False),missing),(doc(False),extra)])
        for before,bad in cases:
            with self.subTest(reference=before,actual=bad):
                compared=native.semantic_compare(before,bad,export_up_axis_policy='h21_export_fallback_y_v1',**kwargs)
                self.assertEqual(compared['state'],'FAIL')
                self.assertEqual(compared['representation_equivalences'],[])
        actual=doc(True);actual['metadata']['metersPerUnit']['authored']=False
        self.assertEqual(native.semantic_compare(reference,actual,export_up_axis_policy='h21_export_fallback_y_v1',**kwargs)['state'],'FAIL')
        with self.assertRaisesRegex(ValueError,'POLICY_INVALID'):
            native.semantic_compare(reference,actual,export_up_axis_policy='ignore_metadata',**kwargs)

    def test_worker_standalone_help_is_safe_and_execution_without_owner_refused(self):
        result=subprocess.run([sys.executable,'-I','-B',str(Path(worker.__file__)),'--help'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('official-cold-export',result.stdout)
        with self.assertRaisesRegex(ValueError,'SUPERVISOR_REQUIRED'):
            worker.current_authority(self.root/'scope.json','official-open-save')


class UIProbeTests(unittest.TestCase):
    def probe(self,serialized=False):
        template=Template(native.UI_PROBE_PARM,kind='Toggle')
        template.defaultExpression=lambda:native.UI_PROBE_EXPRESSION
        template.defaultExpressionLanguage=lambda:SimpleNamespace(name=lambda:'Python')
        template.isHidden=lambda:True
        component=Parm(native.UI_PROBE_PARM,template,0)
        component.keys=['saved default driver'] if serialized else []
        component.expression=lambda:native.UI_PROBE_EXPRESSION
        component.rawValue=lambda:native.UI_PROBE_EXPRESSION
        component.expressionLanguage=lambda:SimpleNamespace(name=lambda:'Python')
        class Tuple:
            def name(self):return native.UI_PROBE_PARM
            def __iter__(self):return iter((component,))
            def parmTemplate(self):return template
            def eval(self):raise IndexError('tuple index out of range: hidden UI driver')
        field=Tuple()
        scalar=Parm('copycontents',Template('copycontents',kind='Menu'),2)
        def ui_query():raise AssertionError('must not evaluate UI disable conditions')
        scalar.isDisabled=ui_query
        class Other:
            def name(self):return 'copycontents'
            def __iter__(self):return iter((scalar,))
            def parmTemplate(self):return scalar.template
            def eval(self):return (scalar.value,)
        node=SimpleNamespace(path=lambda:native.UI_PROBE_NODE,type=lambda:SimpleNamespace(name=lambda:'sopcreate'),
            inputConnections=lambda:(),parmTuple=lambda name:field,parmTuples=lambda:(field,Other()))
        return node,component,template

    def test_unused_probe_and_ui_disable_query_are_not_evaluated(self):
        node,_,_=self.probe()
        with self.assertRaises(IndexError):native.capture_parameters(node)
        result=native.capture_parameters(node,omitted_fields=(native.UI_PROBE_PARM,))
        self.assertNotIn(native.UI_PROBE_PARM,result)
        self.assertEqual(result['copycontents']['value'],[2])
        self.assertEqual(result['copycontents']['disabled'],[None])
        fact=native.ui_probe_omission(node)
        self.assertEqual(fact['value_status'],'NOT_EVALUATED')
        with self.assertRaises(ValueError):native.capture_parameters(node,omitted_fields=('different_hidden_field',))

    def test_default_and_serialized_default_match_but_other_drivers_are_refused(self):
        warm,_,_=self.probe();cold,component,template=self.probe(serialized=True)
        self.assertEqual(native.ui_probe_omission(warm),native.ui_probe_omission(cold))
        component.expression=lambda:'0'
        with self.assertRaisesRegex(ValueError,'DRIVER_MISMATCH'):native.ui_probe_omission(cold)
        node,component,_=self.probe();component.rawValue=lambda:'0'
        with self.assertRaisesRegex(ValueError,'DRIVER_MISMATCH'):native.ui_probe_omission(node)
        component.rawValue=lambda:'1'
        with self.assertRaisesRegex(ValueError,'DRIVER_MISMATCH'):native.ui_probe_omission(node)
        node,_,_=self.probe();node.inputConnections=lambda:('connected',)
        with self.assertRaisesRegex(ValueError,'CONTEXT_MISMATCH'):native.ui_probe_omission(node)
        node,_,template=self.probe();template.isHidden=lambda:False
        with self.assertRaisesRegex(ValueError,'TEMPLATE_MISMATCH'):native.ui_probe_omission(node)


class CachedDiagnosticTests(unittest.TestCase):
    def test_ramp_failure_context_reaches_signed_diagnostic_and_original_exception(self):
        from dcc_task_runtime import owned_process
        original=RuntimeError('ramp evaluation failed')
        template=Template('density',kind='Ramp')
        scalar=Parm('density',template)
        class Tuple:
            def __iter__(self): return iter((scalar,))
            def parmTemplate(self): return template
            def name(self): return 'density'
            def evalAsRamps(self): raise original
        node=SimpleNamespace(path=lambda:'/stage/test',parmTuples=lambda:(Tuple(),))
        hou=SimpleNamespace(Ramp=Ramp,node=lambda path:None)
        scope=SimpleNamespace(scope={},binding={'path':'/fixture/scope.json','sha256':'a'*64})
        case={'paths':{'official_hip':'/fixture/missing.hip'},
              'observer':{'fixture':'observer'},'source_contract':{'fixture':'contract'}}
        identity={'fixture':'offline'}
        start={'fixture':'started'}
        context={'schema':'bridge.official-karma-ramp-failure/1','node':'/stage/test',
                 'parameter':'density','kind':'Ramp','api':'evalAsRamps',
                 'stage':'evaluation_or_serialization'}
        diagnostic_record={'path':'/fixture/native-diagnostic-details.json','sha256':'b'*64,'bytes':123}
        with patch.dict(sys.modules,{'hou':hou}), \
             patch.object(worker,'current_authority',return_value=(scope,case,Path('/fixture'),identity,start)), \
             patch.object(worker,'_run_owned',side_effect=lambda *args: native.capture_parameters(node)), \
             patch.object(worker,'write_new',return_value=diagnostic_record) as write, \
             patch.object(owned_process,'read_receipt',return_value=None) as read, \
             patch.object(owned_process,'_signed_write') as signed, \
             patch.object(Path,'exists',return_value=False), \
             patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(RuntimeError) as caught:
                worker.run('/fixture/scope.json','official-open-save')
        self.assertIs(caught.exception,original)
        self.assertEqual(original.official_ramp_context,context)
        detail=write.call_args.args[1]
        self.assertEqual(detail['ramp_failure'],context)
        self.assertEqual(detail['exception']['type'],'RuntimeError')
        self.assertEqual(detail['exception']['message'],'ramp evaluation failed')
        self.assertIn('RuntimeError: ramp evaluation failed',detail['exception']['traceback'])
        self.assertEqual(detail['identity'],identity)
        self.assertEqual(detail['scope_binding'],scope.binding)
        self.assertEqual(detail['started_sha256'],worker.canonical_sha256(start))
        read.assert_called_once_with(Path('/fixture'),'official-diagnostic',identity=identity)
        signed.assert_called_once()
        directory,payload=signed.call_args.args
        self.assertEqual(directory,Path('/fixture'))
        self.assertEqual(payload,{'schema':owned_process.SCHEMA,'event':'official-diagnostic',
            'identity':identity,'scope_binding':scope.binding,'started_sha256':worker.canonical_sha256(start),
            'captured_pid':detail['pid'],'role':'official-open-save','observer':case['observer'],
            'source_contract':case['source_contract'],'diagnostic':diagnostic_record,
            'diagnostics_incomplete':detail['diagnostics_incomplete'],'evidence_source':'real_host',
            'acceptance':'FAILED_NOT_ACCEPTED'})

    def test_invalid_ramp_context_fails_closed_and_preserves_original_exception(self):
        from dcc_task_runtime import owned_process
        context={'schema':'bridge.official-karma-ramp-failure/1','node':'/stage/test',
                 'parameter':'density','kind':'Ramp','api':'evalAsRamps',
                 'stage':'evaluation_or_serialization'}
        invalid=[{},dict(context,api='eval'),dict(context,node=123),dict(context,extra=True),
                 dict(context,parameter='x'*257),dict(context,node='bad\0node')]
        scope=SimpleNamespace(scope={},binding={'path':'/fixture/scope.json','sha256':'a'*64})
        case={'paths':{'official_hip':'/fixture/missing.hip'},
              'observer':{'fixture':'observer'},'source_contract':{'fixture':'contract'}}
        for value in invalid:
            original=RuntimeError('original failure')
            original.official_ramp_context=value
            with self.subTest(context=value), patch.dict(sys.modules,{'hou':SimpleNamespace(node=lambda path:None)}), \
                 patch.object(worker,'current_authority',return_value=(scope,case,Path('/fixture'),{},{})), \
                 patch.object(worker,'_run_owned',side_effect=original), \
                 patch.object(worker,'write_new') as write, \
                 patch.object(owned_process,'read_receipt') as read, \
                 patch.object(owned_process,'_signed_write') as signed, \
                 patch('sys.stderr',new_callable=io.StringIO) as stderr:
                with self.assertRaises(RuntimeError) as caught:
                    worker.run('/fixture/scope.json','official-open-save')
                self.assertIs(caught.exception,original)
                write.assert_not_called()
                read.assert_not_called()
                signed.assert_not_called()
                self.assertIn('OFFICIAL_DIAGNOSTICS_INCOMPLETE:ValueError:',stderr.getvalue())

    def test_cached_messages_are_preserved_without_cooking_or_evaluating(self):
        class Camera:
            def type(self):return SimpleNamespace(name=lambda:'camera')
            def errors(self):return ('upstream native error',)
            def warnings(self):return ('camera warning text',)
            def messages(self):raise RuntimeError('messages API failed')
            def stage(self,*a,**k):raise AssertionError('must not cook')
            def parm(self,*a):raise AssertionError('must not evaluate')
        api=SimpleNamespace(node=lambda p:Camera() if p=='/stage/lights/camera1' else None)
        result=native.cached_node_diagnostics(api)
        row=next(v for v in result['nodes'] if v['path']=='/stage/lights/camera1')
        self.assertEqual(row['queries']['errors']['values'],['upstream native error'])
        self.assertEqual(row['queries']['warnings']['values'],['camera warning text'])
        self.assertEqual(row['queries']['messages']['state'],'CAPTURE_FAILED')
        self.assertTrue(result['diagnostics_incomplete'])
        self.assertEqual(len(result['nodes']),32)

    def test_failure_receipt_is_separate_from_acceptance_and_binds_saved_hip(self):
        from unittest import mock
        from dcc_task_runtime import owned_process
        import os
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve()
            (root/'receipt.key').write_bytes(b'explicit diagnostic receipt fixture')
            hip=root/'saved.hip';hip.write_bytes(b'explicit saved-file fixture, not real HIP')
            contract=root/'source.json';contract.write_text('{}')
            identity={'fixture':'offline diagnostic only'}
            scope=SimpleNamespace(binding={'path':str(root/'scope.json'),'sha256':'a'*64})
            case={'paths':{'official_hip':str(hip)},'observer':evidence.file_record(Path(worker.__file__)),
                  'source_contract':evidence.file_record(contract)}
            start={'schema':owned_process.SCHEMA,'event':'started','identity':identity,'pid':os.getpid()}
            with mock.patch.dict(sys.modules,{'hou':SimpleNamespace(node=lambda p:None)}):
                worker._record_diagnostic(scope,case,root,identity,start,'official-open-save',ValueError('original failure'))
            payload=owned_process.read_receipt(root,'official-diagnostic',identity=identity)
            self.assertEqual(payload['acceptance'],'FAILED_NOT_ACCEPTED')
            self.assertEqual(payload['started_sha256'],worker.canonical_sha256(start))
            value=evidence.load_record(payload['diagnostic'])
            self.assertEqual(value['exception']['message'],'original failure')
            self.assertEqual(value['saved_hip'],evidence.file_record(hip))
            self.assertIsNone(owned_process.read_receipt(root,'official-observation',identity=identity))


if __name__=='__main__': unittest.main()
