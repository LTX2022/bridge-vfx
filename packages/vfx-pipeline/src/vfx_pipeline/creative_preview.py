"""参考、当前图与创作预览共用固定OCIO显示，不逐图归一化。"""
from __future__ import annotations
import ctypes
from pathlib import Path
from houdini_bridge.official_karma_observation import checked_bytes,file_record
from houdini_bridge.official_karma_display import _processor,_png
from dcc_task_runtime.exr_codec import read_exr


def write_preview(source, target, display):
    """仅从认证EXR派生可比较PNG，所有图使用同一显示配置与曝光。"""
    checked_bytes(source)
    policy=display['policy']
    for record in policy['module_files']:
        checked_bytes(record)
    ctypes.CDLL(policy['module_files'][-1]['path'],mode=ctypes.RTLD_GLOBAL)
    processor,cache=_processor(policy)
    if cache!=display['processor_cache_id']:
        raise ValueError('CREATIVE_DISPLAY_PROCESSOR_CHANGED')
    image=read_exr(source['path']);gain=2**display['exposure_stops']
    if (image['width'],image['height'])!=(420,300) or set(image['channels'])!=set('RGBA'):
        raise ValueError('CREATIVE_PREVIEW_IMAGE_CONTRACT')
    rows_by_y={row['y']:row['channels'] for row in image['rows']};rows=[]
    # EXR行坐标从上到下递增；PNG保持同一顺序。
    for y in range(300):
        row=[];colors=rows_by_y[y]
        for x in range(420):
            alpha=max(0.,min(1.,colors['A'][x]))
            rgb=[colors[c][x]*gain/alpha if alpha>0 else 0. for c in 'RGB']
            values=processor.applyRGB(rgb)
            row.extend(round(max(0.,min(1.,v))*alpha*255) for v in values)
            row.append(255)
        rows.append(row)
    record=_png(Path(target),420,300,rows)
    return {'source':source,'preview':record,'display_sha256':display['sha256'],
            'processor_cache_id':cache,'alpha_display':'composite_over_black_opaque'}
