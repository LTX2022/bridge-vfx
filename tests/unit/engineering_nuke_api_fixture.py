"""Finite Nuke API adapter for the owned-process engineering integration test."""
from pathlib import Path
from engineering_process_fixture import SUPERVISOR_START_SYNC
from engineering_image_tool_fixture import bootstrap
from test_nuke_task_host import FAKE

_EXTENSION = r'''
from types import SimpleNamespace
import os
from dcc_task_runtime.exr_codec import read_exr, write_exr
_current_frame=1
_cache={}
class Format:
    def name(self):return 'bridge_alpha_calibration'
    def width(self):return 128
    def height(self):return 128
_original_value=Knob.value
def knob_value(self):
    return Format() if self._value=='bridge_alpha_calibration' else self._value
Knob.value=knob_value
Knob.isAnimated=lambda self:False
Knob.hasExpression=lambda self:False
_original_init=Node.__init__
def node_init(self,kind,name=None):
    if name is None:
        index=1
        while kind+str(index) in _nodes:index+=1
        name=kind+str(index)
    _original_init(self,kind,name)
    self._knobs.update({key:Knob(value) for key,value in {
        'raw':False,'premultiplied':True,'file_type':'exr','channels':'rgba',
        'format':'','color':[0.,0.,0.,1.],'operation':'over'}.items()})
Node.__init__=node_init
Node.width=lambda self:128
Node.height=lambda self:128
def frame(value=None):
    global _current_frame
    if value is not None:_current_frame=int(value)
    return _current_frame
def addFormat(value):return Format()
def _path(pattern):
    try:return pattern%_current_frame
    except TypeError:return pattern

def _pixels(node,x,y):
    kind=node.Class()
    if kind=='Read':
        path=Path(_path(node['file'].value()))
        stamp=(str(path),path.stat().st_mtime_ns,path.stat().st_size)
        if stamp not in _cache:_cache[stamp]=read_exr(path)
        image=_cache[stamp]
        row=image['rows'][int(y)]['channels']
        return [row[name][int(x)] for name in 'RGBA']
    if kind=='Constant':return list(node['color'].value())
    if kind=='Premult':
        pixel=_pixels(node.input(0),x,y)
        return [value*pixel[3] for value in pixel[:3]]+[pixel[3]]
    if kind=='Merge2':
        bg,fg=(_pixels(node.input(index),x,y) for index in (0,1))
        return [fg[index]+bg[index]*(1-fg[3]) for index in range(4)]
    return _pixels(node.input(0),x,y)
def sample(self,channel,x,y):
    return _pixels(self,int(x),int(y))[{'rgba.red':0,'rgba.green':1,'rgba.blue':2,'rgba.alpha':3}[channel]]
Node.sample=sample
nodes=SimpleNamespace(**{kind:(lambda kind=kind:Node(kind)) for kind in ('Read','Write','Constant','Merge2','Premult')})
def scriptSave():scriptSaveAs(_root_path,overwrite=True)
def execute(node,first,last):
    global _current_frame
    _assert()
    software_wait_for_supervisor_start('alpha-nuke')
    if node.Class()!='Write':raise ValueError('finite software API requires Write')
    for number in range(first,last+1):
        _current_frame=number
        output=Path(_path(node['file'].value()));output.parent.mkdir(parents=True,exist_ok=True)
        channels=sorted('RGBA')
        image={'width':128,'height':128,'channels':channels,'compression':0,'pixel_count':128*128,
            'sample_count':128*128*4,'structural_validated':True,
            'channel_layout':{'channels':[{'name':name,'pixel_type':2,'p_linear':0,'x_sampling':1,'y_sampling':1} for name in channels],
                'data_window':[0,0,127,127],'display_window':[0,0,127,127]}}
        rows=[]
        for y in range(128):
            values={name:[] for name in channels}
            for x in range(128):
                for name,value in zip('RGBA',_pixels(node.input(0),x,y)):values[name].append(value)
            rows.append({'y':y,'channels':values})
        write_exr(output,image,rows)
        log=Path(os.environ.get('BRIDGE_NUKE_RESULT_FILE',str(output)+'.api-log')).with_suffix('.native-api.jsonl')
        with log.open('a') as stream:stream.write(json.dumps({'pid':os.getpid(),'frame':number,'script':_root_path,'input':node.input(0)['file'].value() if node.input(0).Class()=='Read' else node.input(0).Class(),'output':str(output)})+'\n')
'''


def write_api(directory, *, image_adapter=None, image_audit=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'nuke.py'
    injection=bootstrap(image_adapter,image_audit) if image_adapter is not None else ''
    path.write_text(injection+FAKE+SUPERVISOR_START_SYNC+_EXTENSION)
    return path
