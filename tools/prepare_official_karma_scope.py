#!/usr/bin/env python3
"""Prepare a review candidate for the official case; never grant or start native work."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import secrets
import sys
import uuid
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/package/'src'))
from dcc_task_runtime.native_scope import NativeScope,OFFICIAL_SCOPE_SCHEMA,OFFICIAL_RESOURCE_PROFILE,OFFICIAL_BUDGET
from dcc_task_runtime.render_profiles import OFFICIAL
from houdini_bridge.official_karma_observation import file_record,load_record,write_new,checked_bytes
from houdini_bridge.official_karma_preparation import case_spec
import prepare_controlled_engineering as preparation


def prepare(output_root,host_scope,source_preparation,static_review,*,first_stage_diagnostic=False,writer_identity_diagnostic=False,writer_identity_survey=False,writer_startup_diagnostic=False,writer_window_diagnostic=False,stack_qualification=None):
    if sum(map(bool,(first_stage_diagnostic,writer_identity_diagnostic,writer_identity_survey,writer_startup_diagnostic,writer_window_diagnostic)))>1:raise ValueError("OFFICIAL_DIAGNOSTIC_MODE_CONFLICT")
    root=Path(output_root)
    if (not root.is_absolute() or root!=root.resolve() or root.exists() or not root.parent.is_dir()
            or any(p.is_symlink() for p in (root,*root.parents))):
        raise ValueError('OFFICIAL_PREPARATION_FRESH_ROOT_REQUIRED')
    template=load_record(file_record(host_scope))
    if sys.version_info[:2]!=(3,11):
        raise ValueError('OFFICIAL_PREPARATION_PYTHON311_REQUIRED')
    value={key:copy.deepcopy(template[key]) for key in
        ('versions','hosts','project_color','native_color_tokens','alpha_fixture')}
    if (value['versions']!={'houdini':'21.0.631','nuke':'17.0v1'}
            or value['project_color']['colorspace']!='ACEScg'):
        raise ValueError('OFFICIAL_PREPARATION_FIXED_VERSION_COLOR_REQUIRED')
    value['hosts']['supervisor_python']=file_record(Path(sys.executable).resolve())
    value['process_image_policy']={'policy':'sample_header_v1','tools':{
        name:file_record(path) for name,path in (('sample','/usr/bin/sample'),('vmmap','/usr/bin/vmmap'))}}
    for record in value['hosts'].values(): checked_bytes(record)
    key=secrets.token_bytes(32)
    case=case_spec(root,value['hosts'],file_record(source_preparation),file_record(static_review),ROOT,
        {k:value['native_color_tokens']['houdini_static_config'][k] for k in ('path','bytes','sha256')})
    value.update(schema=OFFICIAL_SCOPE_SCHEMA,resource_profile=OFFICIAL_RESOURCE_PROFILE,scene_profile=OFFICIAL,
        scope_id='official-karma-candidate-'+uuid.uuid4().hex,output_root=str(root),
        execution_authorized=False,status='PREPARED_NOT_AUTHORIZED',host_started=False,
        evidence_source='real_host',budget=dict(OFFICIAL_BUDGET),official_case=case,
        accounting={'key_path':str(root/'.native-control/key'),'key_sha256':hashlib.sha256(key).hexdigest()},
        operations=[{'id':role} for role in ('official-open-save','official-cold-export','official-husk',
            'alpha-h21','alpha-nuke','formal-h21','consume-nuke')],
        exclusions=['models','simulation','cache','automatic retry','successor after native start'])
    if first_stage_diagnostic or writer_identity_diagnostic or writer_identity_survey or writer_startup_diagnostic or writer_window_diagnostic:
        from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODE,OFFICIAL_DIAGNOSTIC_BUDGET
        from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_DIAGNOSTIC_MODE
        if writer_identity_diagnostic or writer_identity_survey or writer_startup_diagnostic or writer_window_diagnostic:value['writer_trace_tools']={name:file_record(path) for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample'))}
        value.update(execution_mode=OFFICIAL_IDENTITY_DIAGNOSTIC_MODE if writer_identity_diagnostic else OFFICIAL_DIAGNOSTIC_MODE,budget=dict(OFFICIAL_DIAGNOSTIC_BUDGET),
            operations=[{'id':'official-open-save'}])
        if writer_identity_survey:
            from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_SURVEY_BUDGET,OFFICIAL_IDENTITY_ROLES
            value.update(execution_mode=OFFICIAL_IDENTITY_SURVEY_MODE,budget=dict(OFFICIAL_IDENTITY_SURVEY_BUDGET),operations=[{'id':role} for role in OFFICIAL_IDENTITY_ROLES])
        if writer_window_diagnostic:
            from dcc_task_runtime.native_scope import OFFICIAL_WINDOW_DIAGNOSTIC_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET
            from houdini_bridge.official_karma_observation import validate_stack_qualification
            qrecord=file_record(stack_qualification)
            validate_stack_qualification(qrecord,value['writer_trace_tools'])
            value.update(execution_mode=OFFICIAL_WINDOW_DIAGNOSTIC_MODE,budget=dict(OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET),stack_qualification=qrecord)
            value['writer_trace_tools']['vmmap']=file_record('/usr/bin/vmmap')
        if writer_startup_diagnostic:
            from dcc_task_runtime.native_scope import OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET
            value.update(execution_mode=OFFICIAL_STARTUP_DIAGNOSTIC_MODE,budget=dict(OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET))
    root.mkdir(mode=0o700)
    record=write_new(root/'scope.json',value)
    binding={k:record[k] for k in ('path','sha256')}
    native=NativeScope.initialize(binding,key=key)
    result=preparation.prepare(native.path)
    return {'state':'PREPARED_NOT_AUTHORIZED','scope':binding,'bindings':result['bindings'],
        'driver_preflight':result['driver_preflight'],'native_execution_status':'NOT_RUN','native_start_count':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output-root','host-scope','source-preparation','static-review'):
        parser.add_argument('--'+name,required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--first-stage-diagnostic',action='store_true')
    modes.add_argument('--writer-identity-diagnostic',action='store_true')
    modes.add_argument('--writer-identity-survey',action='store_true')
    modes.add_argument('--writer-startup-diagnostic',action='store_true')
    modes.add_argument('--writer-window-diagnostic',action='store_true')
    parser.add_argument('--stack-qualification')
    args=parser.parse_args()
    print(json.dumps(prepare(args.output_root,args.host_scope,args.source_preparation,args.static_review,first_stage_diagnostic=args.first_stage_diagnostic,writer_identity_diagnostic=args.writer_identity_diagnostic,writer_identity_survey=args.writer_identity_survey,writer_startup_diagnostic=args.writer_startup_diagnostic,writer_window_diagnostic=args.writer_window_diagnostic,stack_qualification=args.stack_qualification),ensure_ascii=False))


if __name__=='__main__':main()
