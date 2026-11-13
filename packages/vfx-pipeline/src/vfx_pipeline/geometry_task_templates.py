"""操作者绑定有限任务目标、参考与评估；模型的goal文字不能更换合同。"""
from __future__ import annotations
import copy
import json
import math
import sys
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import checked_bytes
from .table_evaluation import validate_criteria


def collector_policy(parent_scope, template):
    """旧明确选择保持原值；新macOS桌体范围明确冻结现有sample头信息路线。"""
    from dcc_task_runtime.process_image import validate_collector_policy, SAMPLE_COLLECTOR_POLICY
    from houdini_bridge.official_karma_observation import file_record
    current=parent_scope.get('process_image_policy')
    if current is not None:
        validate_collector_policy(current)
        return copy.deepcopy(current)
    if template is None or sys.platform!='darwin':return None
    value={'policy':SAMPLE_COLLECTOR_POLICY,
           'tools':{name:file_record(Path('/usr/bin')/name) for name in ('sample','vmmap')}}
    validate_collector_policy(value)
    return value


def load(record):
    if record is None:return None
    from .task_creation import _plain, _fail
    def object_bytes(raw):
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:_fail('DUPLICATE_KEY')
                value[key]=item
            return value
        def nonfinite(value):_fail('TEMPLATE_NONFINITE_JSON')
        value=json.loads(raw,object_pairs_hook=unique,parse_constant=nonfinite)
        if type(value) is not dict:_fail('TEMPLATE_OBJECT_REQUIRED')
        return value
    def read(item):
        if type(item) is not dict or set(item)!={'path','bytes','sha256'}:
            _fail('TEMPLATE_FILE_RECORD_REQUIRED')
        _plain(item['path'])
        return checked_bytes(item)
    raw=read(record)
    if len(raw)>65536:_fail('TEMPLATE_TOO_LARGE')
    value=object_bytes(raw)
    if (set(value)!={'schema','profile','public_brief','feedback','criteria','media','viewing_exposure_stops'}
            or value.get('schema')!='bridge.geometry-task-template/1' or value.get('profile')!='table_geometry_v1'
            or any(type(value.get(k)) is not str or not 20<=len(value[k])<=8000 for k in ('public_brief','feedback'))
            or type(value.get('media')) is not dict or set(value['media'])!={'reference_front','reference_perspective'}
            or type(value.get('viewing_exposure_stops')) not in (int,float)
            or not math.isfinite(value['viewing_exposure_stops']) or not -8<=value['viewing_exposure_stops']<=8):
        _fail('TEMPLATE_CONTRACT_INVALID')
    criteria=read(value['criteria'])
    if len(criteria)>65536:_fail('TEMPLATE_CRITERIA_TOO_LARGE')
    validate_criteria(object_bytes(criteria))
    images=[]
    for item in value['media'].values():
        image=read(item);images.append((item,image))
        if len(image)>2*1024*1024 or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            _fail('TEMPLATE_REFERENCE_PNG_REQUIRED')
    if read(record)!=raw or read(value['criteria'])!=criteria or any(read(r)!=b for r,b in images):
        _fail('TEMPLATE_SOURCE_CHANGED')
    return copy.deepcopy(value)


def bind(preparation, template, template_record, root, instruction):
    from .task_creation import _write
    value=copy.deepcopy(preparation)
    value['task_template']=copy.deepcopy(template_record)
    value['goal_contract']={'kind':template['profile'],'goal_text_changes_criteria':False,
                            'criteria_file_sha256':value['criteria']['sha256'],
                            'feedback_reference':'original_accepted_revision_1','human_visual_acceptance':'separate'}
    value['model_route']={'route':'CodexDelegatedMCPRoute','selected_model':'unknown',
                          'reasoning_effort':'unknown','provider_identity':'unknown'}
    display=value['display']
    display['exposure_source']=_write(Path(root)/'viewing-selection.json',
        {'schema':'bridge.manual-viewing-selection/1','exposure_stops':template['viewing_exposure_stops'],
         'instruction':instruction,'scope':'display_only','scene_or_exr_changes':False})
    display['exposure_stops']=template['viewing_exposure_stops']
    display['sha256']=canonical_sha256({k:v for k,v in display.items() if k!='sha256'})
    return value
