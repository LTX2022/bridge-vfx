#!/usr/bin/env python3
"""Write an explicit controller deployment; never launch a DCC or model."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task-root',type=Path,required=True)
    parser.add_argument('--houdini-executable',type=Path,required=True)
    parser.add_argument('--nuke-executable',type=Path,required=True)
    parser.add_argument('--python-executable',type=Path,required=True)
    parser.add_argument('--houdini-version',choices=('21.0.631','22.0.429','22.0.459'),required=True)
    parser.add_argument('--husk-executable',type=Path)
    parser.add_argument('--husk-sha256')
    parser.add_argument('--max-bytes',type=int,required=True)
    parser.add_argument('--session-seconds',type=float,required=True)
    parser.add_argument('--project-id')
    parser.add_argument('--project-colorspace')
    parser.add_argument('--project-color-revision',type=int,default=1)
    parser.add_argument('--controlled-output',action='store_true')
    parser.add_argument('--alpha-calibration',type=Path)
    parser.add_argument('--native-scope',type=Path)
    args=parser.parse_args()
    if (args.project_id is None)!=(args.project_colorspace is None):
        parser.error('--project-id and --project-colorspace must be supplied together')
    project_color=None
    if args.project_id is not None:
        from dcc_task_runtime.project_color import validate_project_color
        try:
            project_color=validate_project_color({
                'schema':'bridge.project-color/1.0','project_id':args.project_id,
                'revision':args.project_color_revision,'colorspace':args.project_colorspace,
                'source':'human_project_selection'})
        except ValueError as exc:
            parser.error(str(exc))
    acceptance=None
    if args.controlled_output:
        if project_color is None:parser.error('--controlled-output requires explicit project color selection')
        from houdini_bridge.controlled_output import validate_controlled_policy
        acceptance=validate_controlled_policy({'policy':'controlled_output_v1','scene_variant':'sphere_ground_v2',
            'resolution':[128,128],'frames':[1],'channels':['R','G','B','A']})
    if args.alpha_calibration is not None and acceptance is None:
        parser.error('--alpha-calibration requires --controlled-output')
    if args.output.exists():parser.error('output already exists')
    if (args.husk_executable is None)!=(args.husk_sha256 is None):
        parser.error('--husk-executable and --husk-sha256 must be supplied together')
    writer=None
    if args.husk_executable is not None:
        from dcc_task_runtime.process_image import freeze_executable
        try:
            frozen=freeze_executable(str(args.husk_executable),args.houdini_version,args.husk_sha256)
        except (OSError,ValueError,TypeError) as exc:
            parser.error(str(exc))
        # Persist only deployment inputs; validation collects the complete
        # frozen identity afresh rather than trusting caller-supplied facts.
        writer={'path':frozen['image']['path'],'version':frozen['version'],
                'sha256':frozen['image']['sha256']}
    if args.max_bytes<=0 or not math.isfinite(args.session_seconds) or not 0<args.session_seconds<=120:parser.error('positive disk bytes and 0..120 second session required')
    for p in (args.houdini_executable,args.nuke_executable,args.python_executable):
        if not p.resolve().is_file() or not os.access(p,os.X_OK):parser.error('executable missing')
    task=args.task_root.expanduser().resolve()
    scoped_budget = None
    native_scope = None
    if args.native_scope is not None:
        from vfx_pipeline.production_hosts import native_scope_budget, native_scope_host_binding
        path = args.native_scope.expanduser().resolve(strict=True)
        native_scope = {'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        if acceptance is None:
            parser.error('--native-scope requires --controlled-output')
        from dcc_task_runtime.native_scope import NativeScope
        scope = NativeScope(native_scope)
        if project_color != scope.scope.get('project_color'):
            parser.error('native scope project color selection differs')
        if args.houdini_version != scope.scope.get('versions', {}).get('houdini'):
            parser.error('native scope Houdini version differs')
        try:
            native_scope_host_binding(native_scope, 'houdini', args.houdini_version,
                args.houdini_executable, args.python_executable, project_color=project_color, writer=writer)
            native_scope_host_binding(native_scope, 'nuke', '17.0v1',
                args.nuke_executable, args.python_executable, project_color=project_color)
            scoped_budget = native_scope_budget(native_scope,
                {'roots':[str(task)], 'max_bytes':args.max_bytes}, task, args.output.resolve().parent)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    result={}
    for app,exe,version in [('houdini',args.houdini_executable,args.houdini_version),('nuke',args.nuke_executable,'17.0v1')]:
        result[app]={'lifecycle':'task_owned','application':app,'version':version,
            'executable':str(exe.resolve()),'supervisor_executable':str(args.python_executable.resolve()),
            'task_root':str(task),'session_seconds':args.session_seconds,'evidence_source':'real_host',
            'resource_budget':scoped_budget if scoped_budget is not None else {'roots':[str(task)],'max_bytes':args.max_bytes}}
    if project_color is not None:
        for config in result.values():config['project_color']=dict(project_color)
    if native_scope is not None:
        for config in result.values():config['native_scope']=dict(native_scope)
    if acceptance is not None:result['houdini']['output_acceptance']=acceptance
    if args.alpha_calibration is not None:
        calibration=json.loads(args.alpha_calibration.read_text(encoding='utf-8'))
        if not isinstance(calibration,dict):parser.error('alpha calibration must be an authority binding object')
        result['houdini']['alpha_calibration']=calibration
    if writer is not None:result['houdini']['writer_executable']=writer
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    args.output.chmod(0o600)
    print(json.dumps({'configuration':str(args.output),'host_started':False}))
    return 0
if __name__=='__main__':raise SystemExit(main())
