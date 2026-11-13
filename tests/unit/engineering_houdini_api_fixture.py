"""Finite native-API substitutes for the engineering software integration case.

These Python programs make synthetic pixels and persist the existing fake HOM
scene. All task dispatch, supervision, scope tickets, receipts and registration
remain in the production modules. They never import a native DCC package.
"""
from pathlib import Path
from engineering_process_fixture import SUPERVISOR_START_SYNC
from engineering_image_tool_fixture import bootstrap
from software_host_bootstrap import BOOTSTRAP_SETUP, BOOTSTRAP_RUN

_PIXELS = r'''
from dcc_task_runtime.exr_codec import write_exr, read_exr, _parse_header
import struct,zlib
def write_pixels(path, *, chart=False, compression='none', pixel_type=2, chart_samples=None):
    if compression not in ('none','zips'):
        raise ValueError('unsupported explicit software EXR compression: '+str(compression))
    if chart and (chart_samples is None or len(chart_samples)!=3):
        raise ValueError('software alpha pixels require actual USD material samples')
    channels = sorted('RGBA')
    image = {'width':128, 'height':128, 'channels':channels, 'compression':0, 'pixel_count':128*128, 'sample_count':128*128*4, 'structural_validated':True,
        'channel_layout': {'channels':[{'name':n,'pixel_type':pixel_type,'p_linear':0,'x_sampling':1,'y_sampling':1} for n in channels],
            'data_window':[0,0,127,127], 'display_window':[0,0,127,127]}}
    rows=[]
    for y in range(128):
        values={n:[] for n in channels}
        for x in range(128):
            rgb,a=chart_samples[0 if x<42 else 1 if x<85 else 2] if chart else ((.125+x/512.,.25+y/512.,.5),1.)
            for name,value in zip('RGBA',(*[v*a for v in rgb],a)):values[name].append(value)
        rows.append({'y':y,'channels':values})
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    write_exr(path,image,rows)
    if compression=='zips':
        # Encode genuine ZIPS blocks from the typed NONE writer's scanlines.
        original=read_exr(path);raw=Path(path).read_bytes();_,cursor=_parse_header(raw)
        attribute=b'compression\0compression\0'+struct.pack('<I',1)+b'\0'
        header=raw[:cursor]
        if header.count(attribute)!=1:raise ValueError('software EXR compression header differs')
        header=header.replace(attribute,attribute[:-1]+b'\x02')
        chunks=[]
        for index in range(original['height']):
            offset=struct.unpack_from('<Q',raw,cursor+index*8)[0]
            y,size=struct.unpack_from('<iI',raw,offset);samples=raw[offset+8:offset+8+size]
            reordered=bytearray(samples[::2]+samples[1::2])
            for i in range(len(reordered)-1,0,-1):
                reordered[i]=(reordered[i]-reordered[i-1]+128)&255
            packed=zlib.compress(reordered)
            payload=packed if len(packed)<len(samples) else samples
            chunks.append(struct.pack('<iI',y,len(payload))+payload)
        offset=cursor+len(chunks)*8;offsets=[]
        for chunk in chunks:offsets.append(struct.pack('<Q',offset));offset+=len(chunk)
        Path(path).write_bytes(header+b''.join(offsets)+b''.join(chunks))
        decoded=read_exr(path)
        if decoded['compression']!=2 or decoded['rows']!=original['rows']:
            raise ValueError('software ZIPS typed pixels differ')
'''

_ALPHA_USD = r'''
import json,math,re
def write_alpha_chart(scene_path,output_path):
    # Finite support for the dedicated chart, not a general USD renderer.
    text=Path(scene_path).read_text(encoding='utf-8')
    variables=re.findall(r'\bdef RenderVar\s+"C"\s*\{([^{}]*)\}',text)
    if len(variables)!=1 or len(re.findall(r'\bdef RenderVar\b',text))!=1:
        raise ValueError('SOFTWARE_ALPHA_SINGLE_RENDER_VAR_REQUIRED')
    def field(name):
        values=re.findall(r'(?m)^\s*(?:uniform|custom)\s+(?:token|string)\s+'+re.escape(name)+r'\s*=\s*("(?:[^"\\]|\\.)*")\s*$',variables[0])
        if len(values)!=1:raise ValueError('SOFTWARE_ALPHA_USD_FIELD_REQUIRED:'+name)
        return json.loads(values[0])
    if field('driver:parameters:aov:husk:format')!='color4h':
        raise ValueError('SOFTWARE_ALPHA_FORMAT_REQUIRES_COLOR4H')
    if any(field(name)!=value for name,value in [('dataType','color4f'),('sourceName','C.*[LO]'),
            ('sourceType','lpe'),('driver:parameters:aov:husk:name','C')]):
        raise ValueError('SOFTWARE_ALPHA_BEAUTY_VAR_REQUIRED')
    if (len(re.findall(r'\bdef RenderProduct\b',text))!=1
            or re.findall(r'rel orderedVars\s*=\s*<([^>]+)>',text)!=['/Render/Vars/C']
            or re.findall(r'uniform int2 resolution\s*=\s*\(([^)]+)\)',text)!=['128, 128']):
        raise ValueError('SOFTWARE_ALPHA_PRODUCT_REQUIRED')
    products=re.findall(r'uniform token productName\s*=\s*("(?:[^"\\]|\\.)*")',text)
    if len(products)!=1 or Path(json.loads(products[0]))!=Path(output_path):
        raise ValueError('SOFTWARE_ALPHA_OUTPUT_PATH_MISMATCH')
    colors=re.findall(r'color3f inputs:emission_color\s*=\s*\(([^)]+)\)',text)
    opacities=re.findall(r'color3f inputs:opacity\s*=\s*\(([^)]+)\)',text)
    if len(colors)!=3 or len(opacities)!=3 or any(re.findall(r'float inputs:'+name+r'\s*=\s*([^\s]+)',text)!=[value]*3
            for name,value in [('base','0'),('specular','0'),('emission','1')]):
        raise ValueError('SOFTWARE_ALPHA_EMISSION_MATERIAL_REQUIRED')
    def triple(raw):
        values=tuple(float(v.strip()) for v in raw.split(','))
        if len(values)!=3 or not all(math.isfinite(v) for v in values):
            raise ValueError('SOFTWARE_ALPHA_MATERIAL_SAMPLE_INVALID')
        return values
    samples=[]
    for color,opacity in zip(colors,opacities):
        alpha=triple(opacity)
        if len(set(alpha))!=1 or not 0<=alpha[0]<=1:
            raise ValueError('SOFTWARE_ALPHA_OPACITY_INVALID')
        samples.append((triple(color),alpha[0]))
    write_pixels(output_path,chart=True,pixel_type=1,chart_samples=samples)
'''

_SETUP = r'''
import importlib.util, subprocess
native_root=Path(__SOURCE_ROOT__)
def injected_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
native=injected_module('engineering_native_schema',native_root/'tools/native_schema_test_boundary.py')
api=injected_module('engineering_stage_api',native_root/'tools/software_render_api_boundary.py')
interfaces,states,ports=api.static_scene_interface_profiles(native_root,'21.0.631')
native.constrain_hou(native_root/'docs/native-basis/hda-interface-capture.json','21.0.631',
    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports,
    native_api_type_preferences={'Lop/light':'light::2.0','Lop/rendervar':'rendervar::2.0',
                                 'Vop/mtlxnormalmap':'mtlxnormalmap::2.0'})
hou=sys.modules['hou']
api.install_stage_api(hou)
api.install_material_binding_api()
api.install_graph_native_layout_api(hou)
hou.hipFile.hasUnsavedChanges=lambda:True
Node=type(hou.node('/obj'))
'''

_RENDER = r'''
def render(self,frame_range=(),res=(),output_file=None,output_format=None,to_flipbook=False,ignore_inputs=False,**kwargs):
    assert frame_range==(1,1,1) and output_format=='exr' and ignore_inputs and not to_flipbook
    hook=self.parm('husk_postframe').unexpandedString()
    # The child is a real owned descendant. The generated post-frame collector
    # observes that child's actual Python image and ancestry itself.
    subprocess.run([__HUSK_EXE__,__HUSK_SCRIPT__,str(runner),'--bridge-main',hou.hipFile.path(),
        self.path(),str(frame_range[0]),str(output_file),hook],check=True,timeout=90)
Node.render=render
'''


def write_boundaries(directory, source_root, *, husk_executable, image_adapter=None, image_audit=None):
    """Return two source files for explicitly configured software-only hosts."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    root=Path(source_root).resolve()
    husk=directory/'engineering-husk-api.py'
    setup=_SETUP.replace('__SOURCE_ROOT__',repr(str(root)))
    injection=bootstrap(image_adapter,image_audit) if image_adapter is not None else ''
    # Main render reopens the saved fake HIP. Alpha reads the actual fixed USD
    # chart and format; both execute the ordinary EXR codec.
    child='import sys,os\nfrom pathlib import Path\nsys.dont_write_bytecode=True\n'
    child+=f"sys.path.insert(0,{str(root/'packages/dcc-task-runtime/src')!r})\n"
    child+=injection+SUPERVISOR_START_SYNC
    child+="if '--bridge-main' not in sys.argv:\n"
    child+='\n'.join('    '+line for line in _PIXELS.splitlines())+'\n'
    child+='\n'.join('    '+line for line in _ALPHA_USD.splitlines())+'\n'
    child+="    if '--prerender-script' in sys.argv:\n        import shlex\n        hook=Path(shlex.split(sys.argv[sys.argv.index('--prerender-script')+1])[0])\n        exec(compile(hook.read_bytes(),str(hook),'exec'),{'__name__':'software_husk_prerender'})\n    write_alpha_chart(sys.argv[-1],sys.argv[sys.argv.index('--output')+1])\n    software_wait_for_supervisor_start('alpha-husk')\n    raise SystemExit(0)\n"
    child+=BOOTSTRAP_SETUP+setup+_PIXELS
    child+=r'''
hip,node_path,frame,output,hook=sys.argv[3:]
hou.hipFile.load(hip,suppress_save_prompt=True)
node=hou.node(node_path)
if node is None:raise ValueError('software saved render node missing')
node.parm('husk_tpostframe').set(1);node.parm('husk_postframe').set(hook)
stage=hou.node(node.parm('loppath').evalAsString()).stage()
settings=stage.GetPrimAtPath(node.parm('rendersettings').evalAsString())
products=settings.GetRelationship('products').GetTargets()
if len(products)!=1:raise ValueError('software output requires one actual render product')
compression=stage.GetPrimAtPath(str(products[0])).GetAttribute('driver:parameters:husk:OpenEXR:compression').Get()
write_pixels(output,compression=compression)
api.execute_postframe_hook(node,hou,int(frame))
'''
    husk.write_text(child,encoding='utf-8')
    render=_RENDER.replace('__HUSK_EXE__',repr(str(husk_executable))).replace('__HUSK_SCRIPT__',repr(str(husk)))
    h=directory/'engineering-hython-api.py'
    h.write_text(injection+BOOTSTRAP_SETUP+setup+render+BOOTSTRAP_RUN,encoding='utf-8')
    return {'houdini_launch_script':h,'alpha_husk_script':husk}
