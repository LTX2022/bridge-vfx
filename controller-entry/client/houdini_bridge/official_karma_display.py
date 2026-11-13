"""Fixed reference-only exposure and shared H21 OCIO display previews."""
from __future__ import annotations
import importlib
import math
from pathlib import Path
import struct
import sys
import zlib

from dcc_task_runtime.exr_codec import read_exr
from .official_karma_observation import checked_bytes,file_record,load_record,write_new,read_sealed

SCHEMA='bridge.official-karma-display/1'
DISPLAY='sRGB - Display'
VIEW='ACES 1.0 - SDR Video'


def policy(host,config):
    install=next(p for p in Path(host).parents if p.name=='Houdini21.0.631')
    package=install/'Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages/PyOpenColorIO'
    library=install/'Frameworks/Houdini.framework/Versions/21.0/Libraries/libOpenColorIO_sidefx.2.4.1.dylib'
    return {'display':DISPLAY,'view':VIEW,'source':'ACEScg','ocio_config':config,
        'ocio_version':'2.4.1','module_files':[file_record(package/'__init__.py'),file_record(package/'PyOpenColorIO.so'),
                                            file_record(library.resolve(strict=True))],
        'exposure_rule':'positive-covered-luminance-median-to-0.18-quarter-stop-clamp-8/1'}


def _processor(value):
    for record in (value['ocio_config'],*value['module_files']):checked_bytes(record)
    package=Path(value['module_files'][0]['path']).parent
    sys.path.insert(0,str(package.parent))
    try: ocio=importlib.import_module('PyOpenColorIO')
    finally:sys.path.pop(0)
    if (Path(ocio.__file__).resolve()!=package/'__init__.py' or ocio.__version__!=value['ocio_version']
            or value['display']!=DISPLAY or value['view']!=VIEW or value['source']!='ACEScg'
            or value['exposure_rule']!='positive-covered-luminance-median-to-0.18-quarter-stop-clamp-8/1'):
        raise ValueError('OFFICIAL_DISPLAY_FROZEN_PROCESSOR_REQUIRED')
    config=ocio.Config.CreateFromFile(value['ocio_config']['path'])
    transform=ocio.DisplayViewTransform(src='ACEScg',display=DISPLAY,view=VIEW)
    processor=config.getProcessor(transform)
    return processor.getDefaultCPUProcessor(),processor.getCacheID()


def _exposure(image):
    values=[]
    for row in image['rows']:
        colors=row['channels']
        for i,alpha in enumerate(colors['A']):
            if alpha>0:
                luminance=sum(colors[c][i]*w for c,w in zip('RGB',(.2722287168,.6740817658,.0536895174)))/alpha
                if math.isfinite(luminance) and luminance>1e-6:values.append(luminance)
    if not values:raise ValueError('OFFICIAL_DISPLAY_UNLIT_REFERENCE')
    values.sort();median=values[(len(values)-1)//2]
    return max(-8.,min(8.,round(4*math.log2(.18/median))/4))


def _record(scope,seal):
    case=scope.scope['official_case'];value=case['display_policy']
    observed=read_sealed(seal,expected_scope=scope.binding)
    reference=file_record(case['paths']['official_image'])
    if observed['output']!=reference['path']:raise ValueError('OFFICIAL_DISPLAY_REFERENCE_MISMATCH')
    _processor(value)
    image=read_exr(reference['path'])
    exposure=_exposure(image)
    return {'schema':SCHEMA,'scope_binding':scope.binding,'sealed_observation':seal,
        'reference':reference,'policy':value,'exposure_stops':exposure}


def freeze_display(scope,seal):
    record=_record(scope,seal)
    path=scope.root/'project/control/official-display.json'
    write_new(path,record)
    return file_record(path)


def resolve_display(scope,seal):
    path=scope.root/'project/control/official-display.json'
    record=file_record(path);value=load_record(record)
    if value!=_record(scope,seal):raise ValueError('OFFICIAL_DISPLAY_REFERENCE_OR_EXPOSURE_CHANGED')
    return value


def check_output_capacity(scope, byte_count):
    """Check the actual scope immediately before adding controller output bytes."""
    if type(byte_count) is not int or byte_count < 0:
        raise ValueError('OFFICIAL_DISPLAY_BYTE_COUNT_INVALID')
    usage=scope.check()
    if usage['disk_bytes']+byte_count>scope.scope['budget']['max_disk_bytes']:
        raise ValueError('NATIVE_SCOPE_DISK_EXHAUSTED')


def _png(path,width,height,rows,*,scope=None):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+bytes(row) for row in rows)
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    if scope is not None:check_output_capacity(scope,len(data))
    with Path(path).open('xb') as stream:stream.write(data)
    return file_record(path)


def write_previews(scope,seal,bridge,nuke):
    value=resolve_display(scope,seal)
    processor,cache_id=_processor(value['policy']);gain=2**value['exposure_stops']
    paths={'official':value['reference']['path'],'bridge':str(bridge),'nuke':str(nuke)}
    images={key:read_exr(path) for key,path in paths.items()}
    if any((im['width'],im['height'])!=(420,300) or set(im['channels'])!=set('RGBA') for im in images.values()):
        raise ValueError('OFFICIAL_DISPLAY_IMAGE_FORMAT_MISMATCH')
    by_y={key:{row['y']:row['channels'] for row in image['rows']} for key,image in images.items()}
    previews={}
    target=scope.root/'previews';target.mkdir(exist_ok=False)
    for name in ('official','bridge','nuke','difference'):
        rows=[]
        for y in reversed(range(300)):
            row=[]
            for x in range(420):
                if name=='difference':
                    rgb=[abs(by_y['bridge'][y][c][x]-by_y['official'][y][c][x])*gain for c in 'RGB'];alpha=1.
                else:
                    colors=by_y[name][y];alpha=colors['A'][x]
                    rgb=[colors[c][x]*gain/alpha if alpha>0 else colors[c][x]*gain for c in 'RGB']
                converted=processor.applyRGB(rgb)
                row.extend(round(max(0.,min(1.,v))*255) for v in (*converted,alpha))
            rows.append(row)
        previews[name]=_png(target/(name+'.png'),420,300,rows,scope=scope)
    return {'schema':'bridge.official-karma-previews/1','display':file_record(scope.root/'project/control/official-display.json'),
        'processor_cache_id':cache_id,'sources':{name:file_record(path) for name,path in paths.items()},'previews':previews}


MAX_PREVIEW_BYTES=420*300*4+300+2048


def _validate_png(raw):
    """Accept the complete fixed RGBA PNG emitted by this preview writer."""
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
    chunks=[];cursor=8
    while cursor<len(raw):
        if cursor+12>len(raw):raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
        size=struct.unpack('>I',raw[cursor:cursor+4])[0];kind=raw[cursor+4:cursor+8]
        end=cursor+8+size
        if end+4>len(raw):raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
        data=raw[cursor+8:end];crc=struct.unpack('>I',raw[end:end+4])[0]
        if zlib.crc32(kind+data)&0xffffffff!=crc:raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
        chunks.append((kind,data));cursor=end+4
        if len(chunks)>3:raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
    if ([k for k,_ in chunks]!=[b'IHDR',b'IDAT',b'IEND'] or chunks[2][1]
            or chunks[0][1]!=struct.pack('>IIBBBBB',420,300,8,6,0,0,0)):
        raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')
    size=(420*4+1)*300
    try:
        inflater=zlib.decompressobj();pixels=inflater.decompress(chunks[1][1],size+1)
    except zlib.error as error:raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID') from error
    if (len(pixels)!=size or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail
            or any(pixels[y*(420*4+1)]!=0 for y in range(300))):
        raise ValueError('OFFICIAL_PREVIEW_PNG_INVALID')


def validate_previews(scope,seal,sources):
    """Reauthenticate an existing index and its actual source and preview bytes."""
    if type(sources) is not dict or set(sources)!={'official','bridge','nuke'}:
        raise ValueError('OFFICIAL_PREVIEW_SOURCES_INVALID')
    record=file_record(scope.root/'official-previews.json')
    value=load_record(record)
    if (type(value) is not dict or set(value)!={'schema','display','processor_cache_id','sources','previews'}
            or value['schema']!='bridge.official-karma-previews/1' or value['sources']!=sources
            or value['display']!=file_record(scope.root/'project/control/official-display.json')
            or type(value['previews']) is not dict or set(value['previews'])!={'official','bridge','nuke','difference'}):
        raise ValueError('OFFICIAL_PREVIEW_INDEX_INVALID')
    display=resolve_display(scope,seal)
    _,cache_id=_processor(display['policy'])
    if (value['processor_cache_id']!=cache_id or display['reference']!=sources['official']
            or sources['official']['path']!=scope.scope['official_case']['paths']['official_image']
            or sources['bridge']['path']!=str(scope.root/'project/saves/main.0001.exr')
            or sources['nuke']['path']!=str(scope.root/'project/saves/nuke.0001.exr')):
        raise ValueError('OFFICIAL_PREVIEW_SOURCE_OR_DISPLAY_CHANGED')
    for source in sources.values():checked_bytes(source)
    for name,item in value['previews'].items():
        path=scope.root/'previews'/(name+'.png')
        if item!=file_record(path,MAX_PREVIEW_BYTES):raise ValueError('OFFICIAL_PREVIEW_FILE_CHANGED')
        _validate_png(checked_bytes(item,MAX_PREVIEW_BYTES))
    checked_bytes(record)
    return record
