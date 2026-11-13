"""Explicit bottom HOM/USD API states for normal render-domain software checks.

Source-bound machine names are separate from injected instance types and gates.
No task graph, result, artifact, image, ledger or producer receipt is pre-created.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import sys
import struct
from types import SimpleNamespace

ORIGIN = 'test_injected_native_api'


def interface_profiles(root: Path, version: str):
    root=Path(root)
    if version == '22.0.459':
        # Exact gallery compiled-template metadata is unknown. This is only
        # a synthetic minimum String Parm API, with a separately documented
        # H22 factory locator (ref.zip member SHA256 below).
        source = Path(__file__).resolve()
        gallery = '$HIP/galleries/$HIPNAME.$OS/rendergallery.db'
        interface = {'origin': ORIGIN, 'version': version, 'mode': 'missing_compiled_templates',
            'compiled_template_status': 'NOT_CAPTURED', 'fixture_api_scope': 'synthetic_minimum_string_parm',
            'factory_default_member_sha256': 'cf655dc0def5408937f87754b00371c5e1106f6d0df17189c9a4dbe4308116d9',
            'machine_field_evidence_path': str(source),
            'machine_field_evidence_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'parameters': {'rendergallerysource': {'name': 'rendergallerysource', 'type': 'string', 'size': 1,
                'ancestors': [], 'children': [], 'menu_tokens': [], 'naming_tokens': 'XYZW', 'flags': [],
                'native_api_compiled_hidden': False, 'declared_factory_defaults': [gallery]}}}
        # Actual H22 DialogScript member hashes: Karma cc263cb8...68783fe;
        # Pyro 950bb643...d4c702d. These are same-build factory values, while
        # instance values remain explicit software inputs.
        states = {'Obj/lopnet': {'rendergallerysource': {'value': gallery}},
            'Lop/karmarendersettings': {'dcmfilename': {'value': '$HIP/render/$HIPNAME.$OS.dcm.$F4.exr'},
                'productName': {'value': '$HIP/render/$HIPNAME.$OS.$F4.checkpoint'}},
            'Sop/pyrosolver': {'checkpoint_basedir': {'value': '$HIP/geo'},
                'checkpoint_basename': {'value': '$HIPNAME.$OS'}, 'savecheckpoints': {'value': 0}}}
        for fields in states.values():
            for state in fields.values():
                state.update(origin=ORIGIN, locked=False, hidden=False)
        states['Obj/lopnet']['rendergallerysource']['disabled'] = False
        states['Manager/lopnet'] = copy.deepcopy(states['Obj/lopnet'])
        return {'Obj/lopnet': interface, 'Manager/lopnet': copy.deepcopy(interface)}, states, {}
    evidence={name:root/'docs/native-basis'/name for name in (
        'w1-sopimport-usdrender-static.json','lop-render-hda-followup.json','usdrender-renderer-machine-field-audit.json')}
    def field(name,kind,size=1,ancestors=(),menu=(),children=()):
        return {'name':name,'type':kind,'size':size,'ancestors':list(ancestors),'children':list(children),
                'menu_tokens':list(menu),'naming_tokens':'XYZW','flags':[],'native_api_compiled_hidden':False}
    def count(name,children):return field(name,'multiparm',children=children)
    rows={
      'Lop/sopimport':{'soppath':field('soppath','oppath'),'enable_pathprefix':field('enable_pathprefix','toggle'),
                       'pathprefix':field('pathprefix','string')},
      'Lop/materiallibrary':{'materials':count('materials',['matnode#','matpath#','matflag#','assign#']),
        **{n:field(n,k,ancestors=('materials',)) for n,k in (('matnode#','oppath'),('matpath#','string'),('matflag#','toggle'),('assign#','toggle'))}},
      'Lop/assignmaterial':{'nummaterials':count('nummaterials',['primpattern#','matspecpath#']),
        **{n:field(n,'string',ancestors=('nummaterials',)) for n in ('primpattern#','matspecpath#')}},
      'Driver/usdrender':{**{n:field(n,'string') for n in ('loppath','rendersettings','override_camera','outputimage')},
         'husk_tpostframe':field('husk_tpostframe','toggle'), 'husk_postframe':field('husk_postframe','string'),
         'soho_foreground':field('soho_foreground','toggle'),
         'enableoutputprocessor_savetodirectory':field('enableoutputprocessor_savetodirectory','toggle'),
         'savetodirectory_directory':field('savetodirectory_directory','string'),
         'husk_tiletempdir':field('husk_tiletempdir','string'),
         'renderer':field('renderer','string',menu=('BRAY_HdKarma','Karma CPU')),'execute':field('execute','button')},
    }
    rows['Sop/volumeconvolve3'] = {'group':field('group','string'),'normalize':field('normalize','toggle'),
        **{name: {**field(name,'float',9), 'naming_tokens':'Base1'} for name in ('convolvezm','convolvezz','convolvezp')}}
    evidence['w2-wrangle-convolve-static.json'] = root/'docs/native-basis/w2-wrangle-convolve-static.json'
    evidence['crowd-hair-native-followup.json'] = root/'docs/native-basis/crowd-hair-native-followup.json'
    evidence['stash-geometry-static.json'] = root/'docs/native-basis/stash-geometry-static.json'
    evidence['scatter2-sdk-help-static.json'] = root/'docs/native-basis/scatter2-sdk-help-static.json'
    evidence['grid-rows-columns-static.json'] = root/'docs/native-basis/grid-rows-columns-static.json'
    rows['Sop/grid'] = {name:field(name,'integer') for name in ('rows','cols')}
    rows['Sop/scatter::2.0'] = {'generateby':field('generateby','ordinal',menu=('bydensity','By Density')),
        **{name:field(name,'toggle') for name in ('forcetotal','indepvoxel','usedensityattrib','useareaattrib')},
        'group':field('group','string')}
    rows['Sop/stash'] = {'stash':field('stash','data')}
    rows.update({op:{} for op in ('Dop/merge','Dop/staticsolver','Dop/multisolver','Dop/gravity')})
    rows['Dop/bulletrbdsolver'] = {'constraintsolvertype':field('constraintsolvertype','ordinal',menu=('gaussseidelisland','Gauss Seidel Island')),
        'randomize_order':field('randomize_order','toggle')}
    source_for={'Lop/sopimport':'w1-sopimport-usdrender-static.json',
      'Lop/materiallibrary':'lop-render-hda-followup.json','Lop/assignmaterial':'lop-render-hda-followup.json',
      'Driver/usdrender':'w1-sopimport-usdrender-static.json','Sop/volumeconvolve3':'w2-wrangle-convolve-static.json'}
    source_for.update({op:'stash-geometry-static.json' if op=='Sop/stash' else 'crowd-hair-native-followup.json'
        for op in ('Sop/stash','Dop/merge','Dop/staticsolver','Dop/multisolver','Dop/gravity','Dop/bulletrbdsolver')})
    source_for['Sop/scatter::2.0'] = 'scatter2-sdk-help-static.json'
    source_for['Sop/grid'] = 'grid-rows-columns-static.json'
    interfaces={op:{'origin':ORIGIN,'version':version,'parameters':params,
      'machine_field_evidence_path':str(evidence[source_for[op]]),
      'machine_field_evidence_sha256':hashlib.sha256(evidence[source_for[op]].read_bytes()).hexdigest()} for op,params in rows.items()}
    # H21 ref.zip panes/rendergallery.txt:451-459 gives this factory locator;
    # member SHA256 b9ce8bd7ad83935e28ee4ba8020e2f2a2d56464489bee8b9746c9e0a9ef2a6a8.
    project_source = Path(__file__).resolve()
    interfaces['Obj/lopnet'] = {'origin': ORIGIN, 'version': version, 'mode': 'missing_compiled_templates',
        'compiled_template_status': 'NOT_CAPTURED', 'fixture_api_scope': 'synthetic_minimum_string_parm',
        'factory_default_member_sha256': 'b9ce8bd7ad83935e28ee4ba8020e2f2a2d56464489bee8b9746c9e0a9ef2a6a8',
        'parameters': {'rendergallerysource': {**field('rendergallerysource', 'string'),
            'declared_factory_defaults': ['$HIP/galleries/$HIPNAME.$OS/rendergallery.db']}},
        'machine_field_evidence_path': str(project_source),
        'machine_field_evidence_sha256': hashlib.sha256(project_source.read_bytes()).hexdigest()}
    interfaces['Manager/lopnet'] = copy.deepcopy(interfaces['Obj/lopnet'])
    interfaces['Sop/scatter::2.0']['mode'] = 'missing_compiled_templates'
    interfaces['Sop/grid']['mode'] = 'missing_compiled_templates'
    crowd_evidence = root/'docs/native-basis/crowd-route-transition-interface-20261003.json'
    crowd_capture = json.loads(crowd_evidence.read_text(encoding='utf-8'))['versions'][version]['operators']
    for op, record in crowd_capture.items():
        interfaces[op] = {'origin':ORIGIN,'version':version,'mode':'captured_dialog','parameters':record['parameters'],
            'machine_field_evidence_path':str(crowd_evidence),
            'machine_field_evidence_sha256':hashlib.sha256(crowd_evidence.read_bytes()).hexdigest()}
    states={
      'Lop/sopimport':{'soppath':{'value':''},'enable_pathprefix':{'value':0},'pathprefix':{'value':'/unconfigured'}},
      'Lop/materiallibrary':{'materials':{'value':0},'matnode1':{'value':''},'matpath1':{'value':''},'matflag1':{'value':0},'assign1':{'value':0}},
      'Lop/assignmaterial':{'nummaterials':{'value':0},'primpattern1':{'value':''},'matspecpath1':{'value':''}},
      'Driver/usdrender':{n:{'value':'BRAY_HdKarma' if n=='renderer' else ''} for n in ('renderer','loppath','rendersettings','override_camera','outputimage')},
      'Lop/karmarendersettings':{n:{'value':0} for n in (('extrarendervars','ocio','custom_metadata','cop_imagefilters') if version.startswith('22') else ('extrarendervars','ocio','custom_metadata'))},
      'Lop/renderproduct':{'primpattern':{'value':'/unconfigured'}},
      'Lop/rendersettings':{'primpattern':{'value':'/unconfigured'}},
      'Sop/sphere':{**{n:{'value':1.0} for n in ('radx','rady','radz','scale')},**{n:{'value':0.0} for n in ('tx','ty','tz','rx','ry','rz')}},
    }
    states['Lop/karmarendersettings'].update({
        'dcmfilename': {'value': '$HIP/render/$HIPNAME.$OS.dcm.$F4.exr'},
        'productName': {'value': '$HIP/render/$HIPNAME.$OS.$F4.checkpoint'},
    })
    states['Obj/lopnet'] = {'rendergallerysource': {
        'value': '$HIP/galleries/$HIPNAME.$OS/rendergallery.db'}}
    states['Manager/lopnet'] = copy.deepcopy(states['Obj/lopnet'])
    # OPlibSop.hda Sop/pyrosolver/DialogScript:4503-4532, member SHA256
    # c01a9fb6e18a72863555dd6e0b03754acdc696f3196c5c077e1140d8f05ae755.
    # The captured supplement supplies their native template/default metadata.
    states['Sop/pyrosolver'] = {
        'checkpoint_basedir': {'value': '$HIP/geo'},
        'checkpoint_basename': {'value': '$HIPNAME.$OS'},
        'savecheckpoints': {'value': 0},
    }
    states['Driver/usdrender'].update(husk_tpostframe={'value':0},husk_postframe={'value':''},soho_foreground={'value':1},
        enableoutputprocessor_savetodirectory={'value':0},savetodirectory_directory={'value':''},husk_tiletempdir={'value':''})
    states['Sop/volumeconvolve3'] = {'group':{'value':''},'normalize':{'value':1},
        **{name+str(i):{'value':0.0} for name in ('convolvezm','convolvezz','convolvezp') for i in range(1,10)}}
    states['Sop/grid'] = {**{name:{'value':2.0} for name in ('sizex','sizey')},
        **{prefix+axis:{'value':0.0} for prefix in ('t','r') for axis in 'xyz'}}
    states['Sop/box'] = {**{name:{'value':2.0} for name in ('sizex','sizey','sizez')}, 'scale':{'value':1.0}}
    states['Sop/xform'] = {'scale':{'value':1.0},
        **{prefix+axis:{'value':0.0 if prefix in ('t','r') else 1.0} for prefix in ('t','r','s') for axis in 'xyz'}}
    states['Sop/guidegroom::2.0'] = {'tool':{'value':'adjustlength',
        'menu_tokens':['adjustlength','plant','relax','cull'],
        'menu_labels':['Adjust Length','Plant','Relax','Cull']}}
    states['Sop/grid'].update(rows={'value':2},cols={'value':2})
    states['Sop/attribwrangle'] = {'class':{'value':'point'},'group':{'value':''},'snippet':{'value':''},'vex_precision':{'value':'64'}}
    states['Sop/stash'] = {'stash':{}}
    states['Dop/bulletrbdsolver'] = {'constraintsolvertype':{'value':'gaussseidelisland'},'randomize_order':{'value':1}}
    states['Sop/scatter::2.0'] = {'npts':{'value':10},'seed':{'value':0},'densityscale':{'value':1.0},'relaxiterations':{'value':0},
        'generateby':{'value':'bydensity'},'forcetotal':{'value':1},'indepvoxel':{'value':0},
        'usedensityattrib':{'value':0},'useareaattrib':{'value':0},'group':{'value':''}}
    for op, fields in states.items():
        for value in fields.values():value.update(origin=ORIGIN,disabled=False,locked=False,hidden=False)
    for name in ('checkpoint_basedir', 'checkpoint_basename'):
        states['Sop/pyrosolver'][name].pop('disabled')
    # Row state is applied when a multiparm instance actually becomes addressable.
    ports={op:{'origin':ORIGIN,'input_names':[],'output_names':[]} for op in (
      'Obj/geo','Obj/matnet','Obj/lopnet','Obj/ropnet','Sop/sphere','Lop/sopimport','Lop/materiallibrary','Lop/assignmaterial',
      'Lop/camera','Lop/light','Lop/karmarendersettings','Lop/rendervar','Lop/renderproduct','Lop/rendersettings','Driver/usdrender')}
    ports.update({
      'Vop/mtlxnormalmap':{'origin':ORIGIN,'input_names':['in','scale'],'output_names':['out']},
      'Vop/mtlxdisplacement':{'origin':ORIGIN,'input_names':['scale','displacement'],'output_names':['out']},
      'Vop/mtlxstandard_surface':{'origin':ORIGIN,'input_names':['base_color','normal'],'output_names':['out']},
      'Vop/mtlxsurfacematerial':{'origin':ORIGIN,'input_names':['displacementshader','surfaceshader'],'output_names':['out']},
    })
    # Explicit finite software NodeType capacity API returns. These are test
    # instance facts; the static archives do not capture complete native arity.
    for op, inputs in {'Obj/subnet':0,'Obj/geo':0,'Obj/dopnet':0,'Sop/dopnet':0,'Sop/stash':0,
        'Dop/popsteerpath':4,'Dop/crowdsolver::3.0':4,'Dop/merge':8,
        'Sop/crowdsource::3.0':2,'Dop/popsource::2.0':4,'Dop/crowdstate::3.0':4,
        'Dop/popsteerwander':4,'Dop/crowdtrigger::2.0':4,'Dop/crowdtransition::3.0':4}.items():
        ports.setdefault(op,{'origin':ORIGIN,'input_names':[],'output_names':[]}).update(input_count=inputs,output_count=1)
    return interfaces,states,ports


def static_scene_interface_profiles(root: Path, version: str):
    """Explicit bottom API shapes for static-scene software tests only.

    Compiled instance types/defaults and dynamic menus are test inputs, not
    native-interface capture. In particular this must never close H22.0.459's
    missing compiled-template basis or be selected by production assembly.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location('static_scene_boundary',Path(root)/'tools/native_schema_test_boundary.py')
    boundary = importlib.util.module_from_spec(spec);spec.loader.exec_module(boundary)
    capture_catalog = boundary.capture_catalog
    if version not in ('21.0.631','22.0.459'):
        raise ValueError('unsupported static scene fixture')
    interfaces,states,ports = interface_profiles(root,'21.0.631')
    if version != '21.0.631':
        # These instance defaults were observed for H21 only. Existing H22
        # catalog/template evidence remains available independently.
        interfaces.pop('Obj/lopnet', None)
        interfaces.pop('Manager/lopnet', None)
        states.pop('Obj/lopnet', None)
        states.pop('Manager/lopnet', None)
        states.pop('Sop/pyrosolver', None)
        version_interfaces, version_states, _ = interface_profiles(root, version)
        interfaces.update(version_interfaces)
        for operator, fields in version_states.items():
            states.setdefault(operator, {}).update(fields)
    catalog = capture_catalog(Path(root)/'docs/native-basis/hda-interface-capture.json',version)
    interfaces = {op:item for op,item in interfaces.items() if item.get('mode') != 'captured_dialog'
                  and (tuple(op.split('/',1)) not in catalog or catalog[tuple(op.split('/',1))]['status']=='CAPTURED_CORE')}
    source = Path(__file__).resolve()
    proof = {'origin':ORIGIN,'version':version,'mode':'missing_compiled_templates',
             'machine_field_evidence_path':str(source),'machine_field_evidence_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    def field(name,kind,size=1,menu=()):
        return dict(name=name,type=kind,size=size,ancestors=[],children=[],menu_tokens=list(menu),naming_tokens='XYZW',flags=[],native_api_compiled_hidden=False)
    for op,fields in {
        'Sop/grid':{'orient':field('orient','ordinal',menu=('xy','XY Plane','yz','YZ Plane','zx','ZX Plane'))},
        'Lop/configurelayer':{'setupaxis':field('setupaxis','toggle'),'upaxis':field('upaxis','ordinal',menu=('y','Y Axis','z','Z Axis')),
                              'setmetersperunit':field('setmetersperunit','toggle'),'metersperunit':field('metersperunit','float')},
    }.items():
        interfaces.setdefault(op,{**proof,'parameters':{}})['parameters'].update(fields)
    for op in ('Obj/subnet','Obj/geo','Obj/lopnet','Obj/matnet','Obj/ropnet','Lop/merge','Sop/merge','Sop/sphere'):
        if tuple(op.split('/',1)) not in catalog:
            interfaces.setdefault(op, {**proof,'parameters':{}})
    if ('Sop','sphere') not in catalog:
        interfaces['Sop/sphere']['parameters'] = {**{name:field(name,'float',3) for name in ('rad','t','r')},'scale':field('scale','float')}
    if ('Sop','grid') not in catalog:
        interfaces['Sop/grid']['parameters'].update({name:field(name,'float',size) for name,size in [('t',3),('r',3),('size',2)]})
    for item in interfaces.values():
        item.update(version=version)
    present = set(catalog) | {tuple(op.split('/',1)) for op in interfaces}
    states = {op:value for op,value in states.items() if tuple(op.split('/',1)) in present}
    states['Lop/configurelayer'] = {name:{'value':value,'origin':ORIGIN,'hidden':False,'disabled':False,'locked':False}
                                  for name,value in [('setupaxis',0),('upaxis','z'),('setmetersperunit',0),('metersperunit',.01)]}
    states['Sop/grid']['orient'] = {'value':'xy','origin':ORIGIN,'hidden':False,'disabled':False,'locked':False}
    states['Lop/karmarendersettings']['res_mode'] = {'value':'autoheight','menu_tokens':['manual'],'menu_labels':['Manual'],'origin':ORIGIN,'hidden':False,'disabled':False,'locked':False}
    states['Lop/rendersettings'] = {'primpattern': {'value':'/unconfigured','origin':ORIGIN,'hidden':False,'disabled':False,'locked':False},
                                    'res_mode': {'value':'autoheight','menu_tokens':['manual'],'menu_labels':['Manual'],
                                                 'origin':ORIGIN,'hidden':False,'disabled':False,'locked':False},
                                    'resolutionx': {'value':2048,'origin':ORIGIN,'hidden':False,'disabled':False,'locked':True},
                                    'resolutiony': {'value':1080,'origin':ORIGIN,'hidden':False,'disabled':False,'locked':True}}
    for role in ('Lop/camera','Lop/light'):
        states.setdefault(role,{})['lookatenable'] = {'value':0,'origin':ORIGIN,'hidden':False,'disabled':False,'locked':False}
    ports = {op:value for op,value in ports.items() if tuple(op.split('/',1)) in present}
    for op,count in [('Lop/merge',8),('Sop/merge',8),('Sop/grid',0),('Lop/configurelayer',1)]:
        ports[op] = dict(origin=ORIGIN,input_count=count,output_count=1,input_names=[],output_names=[])
    return interfaces,states,ports


class Attribute:
    def __init__(self,kind,value,name=''):self.kind,self.value,self.name=kind,value,name
    def GetName(self):return self.name
    def GetTypeName(self):return self.kind
    def HasAuthoredValueOpinion(self):return True
    def Get(self,frame=None):return self.value


class Relationship:
    def __init__(self,targets,present):self.targets,self.present=targets,present
    def __bool__(self):return self.present
    def GetTargets(self):return list(self.targets)
    def GetForwardedTargets(self):return list(self.targets)


class Prim:
    def __init__(self,path,kind,stage=None):self.path,self.kind,self.relations,self.attributes,self.stage=path,kind,{},{},stage
    def GetPath(self):return self.path
    def GetTypeName(self):return self.kind
    def GetStage(self):return self.stage
    def IsActive(self):return True
    def GetRelationship(self,name):return Relationship(self.relations.get(name,[]),name in self.relations)
    def GetAttribute(self,name):return self.attributes.get(name)
    def GetAttributes(self):return [Attribute(value.kind,value.value,name) for name,value in self.attributes.items()]


class Stage:
    def __init__(self,node,frame):
        self.prims={}; self.metadata={}; self.source=node.path(); self.frame=float(frame)
        self._author(node,set())
    def _author(self,node,seen):
        if node.path() in seen:raise ValueError('native stage cycle')
        seen=seen|{node.path()}
        for upstream in node.inputs():
            if upstream is not None:self._author(upstream,seen)
        typ=node.type().name()
        def value(name):
            parm=node.parm(name)
            if parm is None:raise ValueError('actual native field missing: '+name)
            return parm.evalAsString() if parm.parmTemplate().menuItems() else parm.eval()
        def create(path,kind):
            parent=path.rsplit('/',1)[0]
            if parent and parent not in self.prims:create(parent,'')
            if path not in self.prims:self.prims[path]=Prim(path,kind,self)
            if self.prims[path].kind != kind:raise ValueError('USD type conflict')
            return self.prims[path]
        if typ=='sopimport':
            source=sys.modules['hou'].node(value('soppath'))
            if source is None or not source.geometry().prims():raise ValueError('SOP import has no source geometry')
            if value('enable_pathprefix') != 1:raise ValueError('explicit import prefix required')
            prefix=value('pathprefix'); create(prefix,'Scope')
            kinds={prim.type().name() for prim in source.geometry().prims()}
            open_curves = any(callable(getattr(prim,'isClosed',None)) and not prim.isClosed() for prim in source.geometry().prims())
            kind = 'Volume' if 'Volume' in kinds else 'BasisCurves' if open_curves else 'Mesh'
            create(prefix+{'Volume':'/volume_0','BasisCurves':'/curves_0','Mesh':'/mesh_0'}[kind],kind)
        elif typ=='configurelayer':
            if value('setupaxis'):self.metadata['upAxis']={'y':'Y','z':'Z'}[value('upaxis')]
            if value('setmetersperunit'):self.metadata['metersPerUnit']=value('metersperunit')
        elif typ=='materiallibrary':
            hou=sys.modules['hou']
            for row in range(1,value('materials')+1):
                terminal=hou.node(value('matnode'+str(row)))
                if terminal is None or not terminal.isMaterialFlagSet():raise ValueError('material terminal is absent')
                wires={wire.inputIndex():wire.inputNode() for wire in terminal.inputConnections()}
                names=terminal.inputNames()
                if not all(name in names and names.index(name) in wires for name in ('surfaceshader','displacementshader')):raise ValueError('material shader wiring is incomplete')
                create(value('matpath'+str(row)),'Material')
        elif typ=='assignmaterial':
            for row in range(1,value('nummaterials')+1):
                geometry=value('primpattern'+str(row));material=value('matspecpath'+str(row))
                if geometry not in self.prims or material not in self.prims:raise ValueError('material binding has no actual target')
                self.prims[geometry].relations['material:binding']=[material]
        elif typ in {'camera','light','rendervar'}:
            if value('createprims')!='on':raise ValueError('test authoring supports explicit creation')
            kind={'camera':'Camera','light':'SphereLight','rendervar':'RenderVar'}[typ]
            if typ=='light':
                kinds={'UsdLuxSphereLight':'SphereLight','UsdLuxDiskLight':'DiskLight'}
                if value('lighttype') not in kinds:raise ValueError('light type differs')
                kind=kinds[value('lighttype')]
            prim=create(value('primpath'),kind)
            if typ=='rendervar':
                for name,attribute_type in (('sourceName','string'),('sourceType','token'),('dataType','token')):
                    if node.parm(name) is not None and value(name+'_control')=='set':
                        prim.attributes[name]=Attribute(attribute_type,value(name),name)
        elif typ=='karmarendersettings':
            settings=create(value('primpath'),'RenderSettings')
            if node.parm('res_mode') is not None and value('res_mode') == 'manual':
                resolution=node.parmTuple('resolution')
                if resolution is None:raise ValueError('manual native resolution tuple is missing')
                settings.attributes['resolution']=Attribute('int2',list(resolution.eval()),'resolution')
            # Finite Karma HDA response: the installed karmautils.py authors
            # the enabled stock beauty AOV under this actual parameter path.
            beauty=node.parm('beauty')
            if beauty is not None and value('beauty') == 1:
                prim=create(value('rendervarsparentprimpath')+'/beauty','RenderVar')
                for name,kind,item in (('dataType','token','color4f'),('sourceType','string','lpe'),
                        ('sourceName','string','C.*[LO]'),('driver:parameters:aov:husk:name','string','C')):
                    prim.attributes[name]=Attribute(kind,item,name)
            width=value('pixelfiltersize')
            if not sys.modules['hou'].applicationVersionString().startswith('22') or width!=2:
                settings.attributes['karma:global:pixelfiltersize']=Attribute('float',width,'karma:global:pixelfiltersize')
            if sys.modules['hou'].applicationVersionString().startswith('22'):
                settings.attributes['karma:global:pixelfilterscale']=Attribute('float',value('pixelfilterscale'),'karma:global:pixelfilterscale')
            product=create(value('renderproductsparentprimpath')+'/renderproduct','RenderProduct')
            product.relations['orderedVars']=[]
            product.attributes['productName']=Attribute('token',value('picture'),'productName')
            settings.relations.update(products=[product.path],camera=[value('camera')])
            for row in range(1,value('custom_metadata')+1):
                kind=value('metadata_type_'+str(row));key=value('metadata_key_'+str(row))
                product.attributes['driver:parameters:husk:'+key]=Attribute(kind,value('metadata_'+kind+'_'+str(row)),'driver:parameters:husk:'+key)
            product.attributes['driver:parameters:husk:OpenEXR:compression']=Attribute('string',value('image_exr_compression'),'driver:parameters:husk:OpenEXR:compression')
        elif typ in {'renderproduct','rendersettings'}:
            kind='RenderProduct' if typ=='renderproduct' else 'RenderSettings'
            action=value('createprims')
            if action=='on':prim=create(value('primpath'),kind)
            elif action=='forceedit':
                prim=self.prims.get(value('primpattern'))
                if prim is None or prim.kind!=kind:raise ValueError('Force Edit requires an actual existing typed prim')
            else:raise ValueError('unsupported injected authoring mode')
            for name in ('orderedVars','camera','products'):
                if node.parm(name) is not None and value(name+'_control')=='set':prim.relations[name]=[value(name)]
            for name in ('productName','productType'):
                if node.parm(name) is not None and value(name+'_control')=='set':prim.attributes[name]=Attribute('token',value(name),name)
            if typ=='rendersettings' and node.parm('renderingColorSpace') is not None and value('renderingColorSpace_control')=='set':
                prim.attributes['renderingColorSpace']=Attribute('token',value('renderingColorSpace'),'renderingColorSpace')
    def HasAuthoredMetadata(self,name):return name in self.metadata
    def GetMetadata(self,name):return self.metadata.get(name)
    def GetPrimAtPath(self,path):return self.prims.get(str(path))
    def Traverse(self):return tuple(self.prims.values())
    def ExportToString(self):return json.dumps({'source':self.source,'frame':self.frame,'metadata':self.metadata,'prims':[(p.path,p.kind,p.relations,{k:(v.kind,v.value) for k,v in p.attributes.items()}) for p in self.prims.values()]},sort_keys=True)


def install_stage_api(hou):
    if not hasattr(hou,'parmTemplateType'):
        hou.parmTemplateType=SimpleNamespace(Toggle='parmTemplateType.Toggle',String='parmTemplateType.String')
    Node=type(hou.node('/obj'))
    Node.destroyUserData=lambda node,name:node._data.pop(name,None)
    Node.userDataDict=lambda node:dict(node._data)
    original_geometry=Node.geometry
    Node.input=lambda node,index:node.inputs()[index] if type(index) is int and 0<=index<len(node.inputs()) else None
    Node.inputGeometry=lambda node,index:next((wire.inputNode().geometry(output_index=wire.outputIndex())
        for wire in node.inputConnections() if wire.inputIndex()==index),None)
    def curve_geometry(curves,width=None,pscale=None):
        points = []
        prims = []
        for positions in curves:
            vertices = []
            for position in positions:
                number = len(points)
                point = SimpleNamespace(number=lambda n=number:n,position=lambda v=position:v,
                    attribValue=lambda a,w=width,r=pscale:{'width':w,'pscale':r}.get(a if isinstance(a,str) else a.name()))
                points.append(point);vertices.append(SimpleNamespace(point=lambda p=point:p))
            prims.append(SimpleNamespace(type=lambda:SimpleNamespace(name=lambda:'Polygon'),
                isClosed=lambda:False,vertices=lambda v=tuple(vertices):v))
        def extent():
            if not points:return (0.,0.,0.)
            return tuple(max(p.position()[i] for p in points)-min(p.position()[i] for p in points) for i in range(3))
        attrs = tuple(SimpleNamespace(name=lambda name=name:name,size=lambda:1,dataType=lambda:'attribData.Float') for name,value in [('width',width),('pscale',pscale)] if value is not None)
        return SimpleNamespace(points=lambda:tuple(points),prims=lambda:tuple(prims),pointAttribs=lambda:attrs,primAttribs=lambda:(),
            boundingBox=lambda:SimpleNamespace(sizevec=extent))
    def attribute_geometry(positions,primitive_types,values):
        points = tuple(SimpleNamespace(number=lambda i=i:i,position=lambda p=p:tuple(p)) for i,p in enumerate(positions))
        def datatype(name):
            value=values[name][0]
            return 'attribData.String' if isinstance(value,str) else 'attribData.Int' if type(value) is int else 'attribData.Float'
        attributes=tuple(SimpleNamespace(name=lambda name=name:name,size=lambda:1,
            dataType=lambda name=name:datatype(name)) for name in values)
        prims=tuple(SimpleNamespace(number=lambda i=i:i,type=lambda kind=kind:SimpleNamespace(name=lambda:kind),
            attribValue=lambda name,i=i:values[name][i]) for i,kind in enumerate(primitive_types))
        def extent():
            return tuple(max(p[axis] for p in positions)-min(p[axis] for p in positions) for axis in range(3))
        return SimpleNamespace(points=lambda:points,prims=lambda:prims,pointAttribs=lambda:(),primAttribs=lambda:attributes,
            boundingBox=lambda:SimpleNamespace(sizevec=extent))
    def polygon_geometry(positions,polygons,precision='Float64',point_values=None):
        point_values=point_values or {}
        points=tuple(SimpleNamespace(number=lambda i=i:i,position=lambda p=p:tuple(p),
            attribValue=lambda name,i=i:point_values[name][i]) for i,p in enumerate(positions))
        prims=tuple(SimpleNamespace(type=lambda:SimpleNamespace(name=lambda:'Polygon'),
            vertices=lambda face=face:tuple(SimpleNamespace(point=lambda i=i:points[i]) for i in face)) for face in polygons)
        attribute=SimpleNamespace(name=lambda:'P',size=lambda:3,dataType=lambda:'attribData.Float',numericDataType=lambda:'numericData.'+precision)
        def extent():return tuple(max(p[i] for p in positions)-min(p[i] for p in positions) for i in range(3))
        return SimpleNamespace(points=lambda:points,prims=lambda:prims,pointAttribs=lambda:(),primAttribs=lambda:(),
            findPointAttrib=lambda name:attribute if name=='P' else (SimpleNamespace(name=lambda:name,size=lambda:1,
                dataType=lambda:'attribData.Int' if name=='bridge_ocean_layers' else 'attribData.Float',
                numericDataType=lambda:'numericData.Int32' if name=='bridge_ocean_layers' else 'numericData.Float32') if name in point_values else None),boundingBox=lambda:SimpleNamespace(sizevec=extent))

    def spectral_geometry(node):
        # Explicit nonphysical native Volume response. These scalar buffers
        # and the sampler below implement only the injected native API boundary.
        # They do not build nodes, programs, task roots or business receipts.
        f32=lambda v:struct.unpack('!f',struct.pack('!f',v))[0]
        names=('amplitude','phase','frequency') if node.userData('test_native_spectrum_zero_layers')!='1' else ()
        parms=lambda n:float(node.parm(n).eval())
        values={'amplitude':[f32(parms('ampscale')*(1.+i/32.)) for i in range(16)],
            'phase':[f32(.25+i/64.) for i in range(16)],'frequency':[f32(.5+i/128.) for i in range(16)]}
        attrs=('name','chop','timeoffset','timescale')
        prims=[];points=[]
        for index,name in enumerate(names):
            point=SimpleNamespace(number=lambda i=index:i,position=lambda:(0.,0.,0.));points.append(point)
            actual={'name':name,'chop':parms('chopscale'),'timeoffset':parms('timeoffset'),'timescale':parms('timescale')}
            prims.append(SimpleNamespace(number=lambda i=index:i,type=lambda:SimpleNamespace(name=lambda:'Volume'),
                resolution=lambda:(4,1,4),storageType=lambda:'volumeStorageType.Float',channelCount=lambda:1,
                allVoxels=lambda n=name:tuple(values[n]),transform=lambda:SimpleNamespace(asTuple=lambda:(1.,0.,0.,0.,1.,0.,0.,0.,1.)),
                vertex=lambda i,p=point:SimpleNamespace(point=lambda:p),intrinsicNames=lambda:('volumebordertype',),
                intrinsicValue=lambda n:'repeat' if n=='volumebordertype' else None,
                attribValue=lambda n,a=actual:a[n]))
        attributes=tuple(SimpleNamespace(name=lambda n=n:n,size=lambda:1,dataType=lambda n=n:'attribData.String' if n=='name' else 'attribData.Float') for n in attrs)
        return SimpleNamespace(points=lambda:tuple(points),prims=lambda:tuple(prims),pointAttribs=lambda:(),primAttribs=lambda:attributes)

    def geometry(node,output_index=0):
        typ = node.type().name()
        if typ=='merge' and node.type().category().name()=='Sop':
            buffers=[upstream.geometry() for upstream in node.inputs() if upstream is not None]
            points=tuple(point for buffer in buffers for point in buffer.points())
            prims=tuple(prim for buffer in buffers for prim in buffer.prims())
            def extent():
                return tuple(max(p.position()[i] for p in points)-min(p.position()[i] for p in points) for i in range(3)) if points else (0.,0.,0.)
            return SimpleNamespace(points=lambda:points,prims=lambda:prims,pointAttribs=lambda:(),boundingBox=lambda:SimpleNamespace(sizevec=extent))
        if typ=='oceanspectrum':return spectral_geometry(node)
        if typ=='oceanevaluate::2.0':
            source=node.inputGeometry(0);spectral=node.inputGeometry(1)
            if source is None or spectral is None:raise ValueError('evaluate actual two inputs absent')
            positions=[tuple(p.position()) for p in source.points()]
            polygons=[[v.point().number() for v in prim.vertices()] for prim in source.prims()]
            amplitude=[p for p in spectral.prims() if p.attribValue('name')=='amplitude']
            gain=amplitude[0].allVoxels()[0] if amplitude else 0.
            time=hou.time()
            if node.parm('deformgeo').eval():
                positions=[(x,y+.05*gain*math.sin(x+time)*math.cos(z+2*time)+.02*gain*x*z,z) for x,y,z in positions]
            return polygon_geometry(positions,polygons)
        if typ=='attribwrangle' and node.parm('snippet').eval().startswith('#include <ocean.h>\n'):
            if node.parm('class').evalAsString()!='point' or node.parm('group').eval()!='':raise ValueError('unsupported ocean VEX scope')
            evaluated,spectral,rest=(node.inputGeometry(i) for i in range(3))
            if any(g is None for g in (evaluated,spectral,rest)):raise ValueError('ocean VEX requires actual three inputs')
            positions=[tuple(p.position()) for p in evaluated.points()]
            source_positions=[tuple(p.position()) for p in rest.points()]
            polygons=[[v.point().number() for v in prim.vertices()] for prim in rest.prims()]
            spectra={name:[p for p in spectral.prims() if p.attribValue('name')==name] for name in ('amplitude','phase','frequency')}
            if not spectra['amplitude']:raise ValueError('native sampled zero layers')
            # A finite bottom native oceanSampleLayers response depends on its
            # independently read input buffers, rest positions and actual time.
            amp,phase,freq=(spectra[n][0].allVoxels()[0] for n in ('amplitude','phase','frequency'))
            time=(hou.time()+spectra['amplitude'][0].attribValue('timeoffset'))*spectra['amplitude'][0].attribValue('timescale')
            cusps=[.25+abs(math.sin(x+z+time*freq+phase))*amp for x,y,z in source_positions]
            areas=[0.]*len(positions)
            for face in polygons:
                anchor=source_positions[face[0]];cross=[0.,0.,0.]
                for i,index in enumerate(face):
                    a=[source_positions[index][j]-anchor[j] for j in range(3)]
                    b=[source_positions[face[(i+1)%len(face)]][j]-anchor[j] for j in range(3)]
                    cross[0]+=a[1]*b[2]-a[2]*b[1];cross[1]+=a[2]*b[0]-a[0]*b[2];cross[2]+=a[0]*b[1]-a[1]*b[0]
                area=.5*math.sqrt(sum(v*v for v in cross))/len(face)
                for index in face:areas[index]+=area
            snippet=node.parm('snippet').eval();lines=snippet.splitlines()
            if 'oceanSampleLayers(@OpInput2, "", @Time, bridge_rest, 0.0, 0, 0.0, 0,' not in lines or 'i@bridge_ocean_layers = nprimsByName(@OpInput2, "amplitude");' not in lines:
                raise ValueError('unsupported actual fixed ocean VEX sampler')
            match=re.fullmatch(r'f@foam_mask = 1\.0 - exp\(-([^ ]+) \* bridge_dual_area \* max\(bridge_cusp - ([^,]+), 0\.0\)\);',lines[-1])
            if match:
                density,threshold=(float(v) for v in match.groups())
                foam=[1.-math.exp(-density*a*max(c-threshold,0.)) for a,c in zip(areas,cusps)]
            elif lines[-1]=='f@foam_mask = 0.0;':foam=[0.]*len(positions)
            else:raise ValueError('unsupported finite ocean VEX coverage')
            f32=lambda v:struct.unpack('!f',struct.pack('!f',v))[0]
            attrs={'bridge_ocean_layers':[len(spectra['amplitude'])]*len(positions),'bridge_ocean_cusp':list(map(f32,cusps)),
                'bridge_ocean_dual_area':list(map(f32,areas)),'cusp_mask':[f32(min(1.,max(0.,c))) for c in cusps],'foam_mask':list(map(f32,foam))}
            return polygon_geometry(positions,polygons,point_values=attrs)
        if typ=='attribwrangle' and node.parm('snippet').eval().startswith('vector bridge_source = point(0, "P", @ptnum);\n'):
            source=node.inputGeometry(0)
            if source is None:raise ValueError('cloth wrangle has no actual input')
            positions=[tuple(p.position()) for p in source.points()]
            polygons=[[v.point().number() for v in prim.vertices()] for prim in source.prims()]
            snippet=node.parm('snippet').eval()
            if snippet == 'vector bridge_source = point(0, "P", @ptnum);\n@P = bridge_source;\n' or snippet=='':
                return polygon_geometry(positions,polygons)
            if node.parm('class').evalAsString()!='point' or node.parm('group').eval()!='':
                raise ValueError('unsupported cloth VEX scope')
            lines=snippet.splitlines()
            if len(lines)!=6 or lines[0]!='vector bridge_source = point(0, "P", @ptnum);' or lines[4]!='float bridge_distance = dot(bridge_source - bridge_anchor, bridge_tangent);':
                raise ValueError('unsupported finite cloth VEX grammar')
            vectors={}
            for line in lines[1:4]:
                match=re.fullmatch(r'vector bridge_(anchor|normal|tangent) = set\(([^;]+)\);',line)
                if not match:raise ValueError('unsupported finite cloth VEX vector')
                values=[float(value.strip()) for value in match.group(2).split(',')]
                if len(values)!=3 or not all(math.isfinite(value) for value in values):raise ValueError('invalid VEX vector')
                vectors[match.group(1)]=values
            match=re.fullmatch(r'@P = bridge_source \+ bridge_normal \* \(([-+0-9.eE]+) \* sin\(6\.283185307179586 \* bridge_distance / ([-+0-9.eE]+)\)\);',lines[5])
            if not match or set(vectors)!= {'anchor','normal','tangent'}:raise ValueError('unsupported finite cloth VEX position')
            amplitude,wavelength=map(float,match.groups())
            if not math.isfinite(amplitude) or not math.isfinite(wavelength) or wavelength<=0:raise ValueError('invalid VEX scalars')
            shaped=[]
            for point in positions:
                distance=sum((point[i]-vectors['anchor'][i])*vectors['tangent'][i] for i in range(3))
                offset=amplitude*math.sin(6.283185307179586*distance/wavelength)
                shaped.append(tuple(point[i]+vectors['normal'][i]*offset for i in range(3)))
            return polygon_geometry(shaped,polygons)
        if typ in {'attribadjustfloat','copytopoints::2.0','dopnet','xform'}:
            source = node.input(0)
            if source is None:raise ValueError('native API fixture has no connected source geometry')
            # Non-simulating finite API response preserves the actual source.
            # Ocean displacement, POP history and scatter populations are not
            # claimed as physical results by this structural software fixture.
            return source.geometry()
        if typ == 'scatter::2.0':
            source=node.input(0)
            if source is None:raise ValueError('scatter has no actual surface')
            return source.geometry()
        if typ == 'rbdmaterialfracture':
            source=node.inputGeometry(0)
            if source is None:raise ValueError('fracture has no actual source')
            positions=[tuple(p.position()) for p in source.points()]
            low=[min(p[i] for p in positions) for i in range(3)]
            high=[max(p[i] for p in positions) for i in range(3)]
            centers=[[(low[0]*3+high[0])/4,(low[1]+high[1])/2,(low[2]+high[2])/2],
                     [(low[0]+high[0]*3)/4,(low[1]+high[1])/2,(low[2]+high[2])/2]]
            # Bounded native API output fixture, without a physical fracture
            # solver or any claimed size/distribution mapping.
            if output_index==1:
                return attribute_geometry(centers,['Polygon'],{'constraint_name':['Glue'],
                    'constraint_type':['all'],'strength':[2.5]})
            if output_index==0:
                return attribute_geometry(centers,['PackedGeometry','PackedGeometry'],{'name':['piece0','piece1']})
            return source
        if typ == 'rbdconfigure':
            source=node.inputGeometry(output_index)
            if output_index!=0:return source
            if node.parm('attributes').eval()!=1:raise ValueError('unsupported native configure row count')
            if not node.parm('addactive1').eval():return source
            if node.parm('group1').eval()!='' or node.parm('useactivebounds1').eval():raise ValueError('unsupported native active group/bounds')
            values={a.name():[p.attribValue(a.name()) for p in source.prims()] for a in source.primAttribs()}
            values['active']=[node.parm('active1').eval() for p in source.prims()]
            return attribute_geometry([tuple(p.position()) for p in source.points()],[p.type().name() for p in source.prims()],values)
        if typ == 'rbdbulletsolver':
            return node.inputGeometry(0)
        if typ == 'attribwrangle' and node.parm('snippet').eval() == '':
            source=node.inputGeometry(0)
            if source is None:raise ValueError('empty native wrangle has no actual input')
            return source
        if typ == 'attribwrangle' and node.parm('snippet').eval() == 'if (s@constraint_name == "Glue") f@strength = 1.0;':
            if node.parm('class').evalAsString() != 'primitive' or node.parm('group').eval() != '':
                raise ValueError('unsupported primitive normalization scope')
            source=node.inputGeometry(0)
            values={a.name():[p.attribValue(a.name()) for p in source.prims()] for a in source.primAttribs()}
            if set(('constraint_name','strength')) - set(values):raise ValueError('actual constraint attributes missing')
            values['strength']=[1. if name=='Glue' else old for name,old in zip(values['constraint_name'],values['strength'])]
            return attribute_geometry([tuple(p.position()) for p in source.points()],
                [p.type().name() for p in source.prims()],values)
        if typ == 'stash':
            return node.parm('stash').evalAsGeometry()
        if typ == 'crowdsource::3.0':
            source = node.input(0)
            if source is None:raise ValueError('crowd source has no actual agent input')
            # A non-simulating API fixture preserves actual detached agents.
            # Population distribution and DOP animation are not represented.
            return source.geometry()
        if typ == 'dopimportfield':
            network = hou.node(node.parm('doppath').eval())
            imported = hou.node(node.parm('dopnode').eval())
            if network is None or imported is None or imported.parent().path() != network.path():
                raise ValueError('actual imported DOP object identity differs')
            sources = [child for child in network.children() if child.type().name() == 'popsource::2.0']
            if len(sources) != 1:raise ValueError('ambiguous actual population source')
            source = hou.node(sources[0].parm('soppath').eval())
            if source is None:raise ValueError('actual population SOP path is missing')
            return source.geometry()
        if typ == 'vellumconstraints' and node.parm('constrainttype').evalAsString() == 'hair':
            source=node.inputGeometry(0)
            if source is None:raise ValueError('hair constraints have no actual curves')
            curves=[[tuple(v.point().position()) for v in prim.vertices()] for prim in source.prims()]
            if node.parm('dothickness').evalAsString() != 'on':raise ValueError('uniform native hair thickness is not enabled')
            return curve_geometry(curves,pscale=float(node.parm('thickness').eval()))
        if typ == 'hairgen::2.0':
            if node.parm('useguides').eval() == 1:
                guides = node.input(1)
                if guides is None:return curve_geometry([])
                source = guides.geometry()
                curves = [[tuple(v.point().position()) for v in p.vertices()] for p in source.prims()]
                return curve_geometry(curves,float(node.parm('thickness').eval()))
            skin = node.input(0)
            if skin is None:return curve_geometry([])
            length = float(node.parm('unguidedlength').eval())
            # Explicit bottom API curve fixture; no density population or hair
            # simulation is modeled. Actual parameter edits remain production.
            roots = [tuple(p.position()) for p in skin.geometry().points()[:2]]
            return curve_geometry([[p,(p[0],p[1]+length,p[2])] for p in roots])
        if typ in {'guidegroom::2.0','hairclump::2.0'}:
            upstream = node.input(0)
            return upstream.geometry() if upstream is not None else curve_geometry([])
        if typ == 'guideprocess':
            upstream = node.input(0)
            if upstream is None:return curve_geometry([])
            result = [[tuple(v.point().position()) for v in p.vertices()] for p in upstream.geometry().prims()]
            for row in range(1,node.parm('operations').eval()+1):
                if node.parm('active'+str(row)).eval() and node.parm('op'+str(row)).evalAsString() == 'setlength':
                    length = float(node.parm('setlength_length'+str(row)).eval())
                    result = [[curve[0],(curve[0][0],curve[0][1]+length,curve[0][2])] for curve in result]
            return curve_geometry(result)
        if typ in {'null','vellumsolver','vellumconstraints','vellumconstraints_grain','clusterpoints','tetconform','pyrosource','attribwrangle','pyrosolver','volumeconvolve3','volumewrangle','flipsource','flipcontainer','flipcollide','flipsolver','particlefluidsurface::2.0'}:
            inputs = node.inputs()
            if not inputs or inputs[0] is None:
                return original_geometry(node)
            # Explicit non-simulating native API replacement. The fixture keeps
            # source geometry and never models a solver's physical result.
            return inputs[0].geometry()
        if typ == 'volumerasterizeattributes':
            upstream = node.input(0)
            if upstream is None or not upstream.geometry().points():
                return original_geometry(node)
            source = upstream.geometry(); names = node.parm('attributes').eval().split()
            if not names:
                return original_geometry(node)
            prims = tuple(SimpleNamespace(type=lambda:SimpleNamespace(name=lambda:'Volume'),
                attribValue=lambda name,field=field:field if name == 'name' else None) for field in names)
            return SimpleNamespace(points=lambda:source.points(),prims=lambda:prims,pointAttribs=lambda:(),
                boundingBox=lambda:source.boundingBox())
        if typ in {'grid','box'}:
            size = node.parmTuple('size').eval()
            if typ == 'grid':
                rows,cols=node.parm('rows').eval(),node.parm('cols').eval()
                if type(rows)is not int or type(cols)is not int or not 2<=rows<=64 or not 2<=cols<=64:
                    raise ValueError('bounded actual grid resolution is required')
                positions=[(-size[0]/2+size[0]*c/(cols-1),0.,-size[1]/2+size[1]*r/(rows-1)) for r in range(rows) for c in range(cols)]
                polygons=[[r*cols+c,r*cols+c+1,(r+1)*cols+c+1,(r+1)*cols+c] for r in range(rows-1) for c in range(cols-1)]
                return polygon_geometry(positions,polygons)
            else:
                extent = tuple(float(s)*float(node.parm('scale').eval()) for s in size)
                positions = tuple((x*extent[0]/2,y*extent[1]/2,z*extent[2]/2)
                    for x in (-1,1) for y in (-1,1) for z in (-1,1))
                primitive_count = 6
            vertices = tuple(SimpleNamespace(position=lambda v=v:v) for v in positions)
            return SimpleNamespace(points=lambda:vertices,prims=lambda:tuple(SimpleNamespace(type=lambda:SimpleNamespace(name=lambda:'Polygon')) for _ in range(primitive_count)),
                pointAttribs=lambda:(),primAttribs=lambda:(),boundingBox=lambda:SimpleNamespace(sizevec=lambda:extent))
        if typ!='sphere':return original_geometry(node)
        radii=tuple(float(node.parm('rad'+axis).eval())*float(node.parm('scale').eval()) for axis in 'xyz')
        if min(radii)<=0:raise ValueError('injected sphere geometry has nonpositive radius')
        vertices=tuple(SimpleNamespace(position=lambda v=v:v) for v in ((radii[0],0,0),(0,radii[1],0),(0,0,radii[2]),(-radii[0],0,0)))
        return SimpleNamespace(points=lambda:vertices,prims=lambda:(SimpleNamespace(type=lambda:SimpleNamespace(name=lambda:'Polygon')),),
            pointAttribs=lambda:(),boundingBox=lambda:SimpleNamespace(sizevec=lambda:tuple(2*r for r in radii)))
    Node.geometry=geometry
    Node.stage=lambda self,frame=None,**kwargs:Stage(self,hou.frame() if frame is None else frame)
    class Kind(type):
        def __instancecheck__(cls,node):
            if cls.__name__ == 'LopNetwork':
                return node is not None and node == hou.node('/stage')
            return node is not None and node.type().category().name()==('Driver' if cls.__name__=='RopNode' else 'Lop')
    hou.RopNode=Kind('RopNode',(),{})
    hou.LopNode=Kind('LopNode',(),{})
    hou.LopNetwork=Kind('LopNetwork',(),{})
    hou.applicationVersion=lambda:tuple(int(x) for x in hou.applicationVersionString().split('.'))


def install_material_binding_api():
    """Explicit bottom UsdShade API for simple direct/inherited binding tests.

    The fixture only resolves relationships on its already-authored Stage. It
    builds no task graph, expected prim, material assignment or success receipt.
    Collection bindings are deliberately outside this finite software API.
    """
    from types import ModuleType
    pxr = ModuleType('pxr')
    if 'pxr' in sys.modules:pxr.__dict__.update(vars(sys.modules['pxr']))
    shade = ModuleType('pxr.UsdShade')
    class Material:
        def __init__(self,prim):self.prim=prim
        def __bool__(self):return self.prim is not None and self.prim.GetTypeName()=='Material'
        def GetPrim(self):return self.prim
        def GetPath(self):return self.prim.GetPath() if self.prim is not None else ''
    class MaterialBindingAPI:
        def __init__(self,prim):self.prim=prim
        def ComputeBoundMaterial(self):
            stage=self.prim.GetStage();path=str(self.prim.GetPath())
            while path:
                current=stage.GetPrimAtPath(path)
                if current is not None:
                    if any(name.startswith('material:binding:collection') for name in current.relations):
                        raise ValueError('collection resolution is outside the explicit software fixture')
                    relation=current.GetRelationship('material:binding');targets=relation.GetTargets()
                    if targets:
                        if len(targets)!=1:raise ValueError('direct binding must have one target')
                        return Material(stage.GetPrimAtPath(targets[0])),relation
                path=path.rsplit('/',1)[0]
            return Material(None),Relationship([])
    shade.MaterialBindingAPI=MaterialBindingAPI;pxr.UsdShade=shade
    sys.modules['pxr']=pxr;sys.modules['pxr.UsdShade']=shade


def execute_postframe_hook(node, hou, frame):
    """Bottom native hook API only; execute the actual generated observer source."""
    import runpy
    enabled=node.parm('husk_tpostframe'); script=node.parm('husk_postframe')
    if enabled is None or script is None:
        raise ValueError('explicit native post-frame templates are missing')
    if enabled.evalAtFrame(frame) == 0:
        return
    path=Path(script.unexpandedString())
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError('explicit native post-frame script is unavailable')
    lop=hou.node(node.parm('loppath').eval())
    if lop is None:
        raise ValueError('explicit writer source LOP is absent')
    previous=hou.frame()
    try:
        hou.setFrame(frame)
        runpy.run_path(str(path),init_globals={
            'stage':lop.stage(frame=frame,apply_viewport_overrides=False,ignore_errors=False),
            'settings':{}, 'husk_command':['explicit-software-native-husk-hook-api']},
            run_name='__software_native_husk_postframe__')
    finally:
        hou.setFrame(previous)


def install_graph_native_layout_api(hou):
    """Finite H21 graph API inputs: Object category and locked Karma contents.

    The definition, static flags, empty channels and wires below are explicit
    synthetic HOM inputs. They model no native Karma implementation or cook.
    The same finite graph is available to both legacy and 2.1 capture policies.
    """
    node_class = type(hou.node('/obj'))
    original_type, original_children = node_class.type, node_class.children
    original_editable = node_class.isEditable
    original_lookup = hou.node
    definition = {
        'additional_vars':('Lop','null'), 'configurelayer1':('Lop','configurelayer'),
        'configurelayer2':('Lop','configurelayer'), 'input':('Lop','null'),
        'merge1':('Lop','merge'), 'null1':('Lop','null'), 'output0':('Lop','output'),
        'prune1':('Lop','prune'), 'pythonscript1':('Lop','pythonscript'),
        'rendersettings':('Lop','rendersettings'), 'select_secondary_rendervars':('Lop','switch'),
        'sopnet':('Lop','sopnet'), 'sopnet/attribwrangle1':('Sop','attribwrangle'),
        'sopnet/line1':('Sop','line'), 'sopnet/resample1':('Sop','resample'),
        'sopnet/tonemap_curve':('Sop','attribwrangle'),
        'sopnet/tonemap_curve/attribvop1':('Sop','attribwranglecore'), 'warning':('Lop','error'),
    }
    generated = {}
    lock_key = '_software_karma_definition_unlocked'
    state_key = '_software_karma_definition_channels'

    class SyntheticSection:
        def __init__(self, contents): self.contents = contents
        def binaryContents(self): return self.contents

    class SyntheticDefinition:
        def __init__(self):
            contents = json.dumps({'schema':'bridge.software-hda-definition/1',
                'nodes':[{'relative_path':path,'category':category,'type':kind}
                         for path,(category,kind) in sorted(definition.items())]},
                sort_keys=True,separators=(',',':')).encode('utf-8')
            self._sections = {'Contents':SyntheticSection(contents),
                'PythonModule':SyntheticSection(b'# Synthetic HOM graph only; no Karma implementation.\n')}
            self._options = {'PythonModule/IsPython':True}
        def nodeTypeName(self): return 'karmarendersettings'
        def nodeTypeCategory(self): return SimpleNamespace(name=lambda:'Lop')
        def version(self): return 'software-fixture/1'
        def sections(self): return dict(self._sections)
        def extraFileOptions(self): return dict(self._options)
        def extraInfo(self): return 'bridge.software-hda-definition/1'
        def libraryFilePath(self): return 'synthetic:software_render_api_boundary'

    synthetic_definition = SyntheticDefinition()

    def category_type(node):
        result = original_type(node)
        category = 'Object' if result.category().name() == 'Obj' else result.category().name()
        return SimpleNamespace(**{**vars(result), 'category':lambda:SimpleNamespace(name=lambda:category),
            'nameWithCategory':lambda:category+'/'+result.name(),
            'definition':lambda:synthetic_definition if asset(node) else None})

    def asset(node):
        return original_type(node).nameWithCategory() == 'Lop/karmarendersettings'

    class DefinitionNode:
        def __init__(self, owner, relative):
            self.owner, self.relative = owner, relative
            self.parms_dict = {}
        def path(self): return self.owner + '/' + self.relative
        def name(self): return self.relative.rsplit('/',1)[-1]
        def type(self):
            category, name = definition[self.relative]
            return SimpleNamespace(name=lambda:name,nameWithCategory=lambda:category+'/'+name,
                                   category=lambda:SimpleNamespace(name=lambda:category), definition=lambda:None)
        def parent(self): return lookup(self.path().rsplit('/',1)[0])
        def parms(self): return ()
        def inputs(self): return ()
        def inputConnections(self): return ()
        def isEditable(self): return original_lookup(self.owner).isEditable()
        def isEditableInsideLockedHDA(self): return self.isEditable()
        def isLockedHDA(self): return False
        def matchesCurrentDefinition(self): return True
        def isDelayedDefinition(self): return False
        def isHardLocked(self): return False
        def isBypassed(self): return False
        def isDisplayFlagSet(self): return False
        def isRenderFlagSet(self): return False
        def isTemplateFlagSet(self): return False
        def userDataDict(self):
            owner = original_lookup(self.owner)
            return dict(json.loads(owner.userData(state_key) or '{}').get(self.relative,{}))
        def children(self):
            prefix=self.relative+'/'
            return tuple(item for item in contents(original_lookup(self.owner))
                         if item.relative.startswith(prefix) and '/' not in item.relative[len(prefix):])
        def allSubChildren(self, **kwargs): return descendants(self, **kwargs)
        def userData(self,key):
            owner=original_lookup(self.owner)
            return json.loads(owner.userData(state_key) or '{}').get(self.relative,{}).get(key)
        def setUserData(self,key,value):
            owner=original_lookup(self.owner)
            data=json.loads(owner.userData(state_key) or '{}')
            data.setdefault(self.relative,{})[key]=value
            owner.setUserData(state_key,json.dumps(data,sort_keys=True))
        def destroyUserData(self,key):
            owner=original_lookup(self.owner)
            data=json.loads(owner.userData(state_key) or '{}')
            values=data.get(self.relative,{})
            values.pop(key,None)
            if values:data[self.relative]=values
            else:data.pop(self.relative,None)
            if data:owner.setUserData(state_key,json.dumps(data,sort_keys=True))
            else:owner.destroyUserData(state_key)

    def contents(owner):
        if owner is None:return ()
        return tuple(generated.setdefault(owner.path()+'/'+relative, DefinitionNode(owner.path(),relative))
                     for relative in definition)

    def children(node):
        result=tuple(original_children(node))
        if asset(node):
            result+=tuple(child for child in contents(node) if '/' not in child.relative)
        return result

    def editable(node):
        return node.userData(lock_key)=='1' if asset(node) else original_editable(node)

    def descendants(node, top_down=True, recurse_in_locked_nodes=True, sync_delayed_definition=False):
        if any(type(value) is not bool for value in (top_down,recurse_in_locked_nodes,sync_delayed_definition)):
            raise ValueError('explicit software HOM traversal flags required')
        result=[]
        for child in node.children():
            if top_down:result.append(child)
            if recurse_in_locked_nodes or child.isEditable():
                result.extend(descendants(child,top_down,recurse_in_locked_nodes,sync_delayed_definition))
            if not top_down:result.append(child)
        return tuple(result)

    def lookup(path):
        actual=original_lookup(path)
        if actual is not None:return actual
        candidate=generated.get(str(path))
        return candidate if candidate is not None and original_lookup(candidate.owner) is not None else None

    node_class.type, node_class.children = category_type, children
    node_class.isEditable, node_class.allSubChildren = editable, descendants
    node_class.isLockedHDA = lambda node: asset(node) and not editable(node)
    node_class.matchesCurrentDefinition = lambda node: not asset(node) or not editable(node)
    node_class.allowEditingOfContents = lambda node: node.setUserData(lock_key,'1')
    node_class.matchCurrentDefinition = lambda node: node.setUserData(lock_key,'0')
    original_child_category = node_class.childTypeCategory
    node_class.childTypeCategory = lambda node: SimpleNamespace(name=lambda:
        'Object' if original_child_category(node).name()=='Obj' else original_child_category(node).name())
    original_node_type = hou.nodeType
    hou.objNodeTypeCategory = lambda: SimpleNamespace(name=lambda:'Object')
    hou.nodeType = lambda category,name: original_node_type(
        SimpleNamespace(name=lambda:'Obj') if category.name()=='Object' else category,name)
    hou.node = lookup
    return {'origin':ORIGIN,'native_geometry_executed':False,'locked_definition_nodes':len(definition),
            'native_category':'Object','internal_parameter_observation':'EXPLICIT_SYNTHETIC_EMPTY_CHANNELS',
            'definition_origin':'bridge.software-hda-definition/1'}
