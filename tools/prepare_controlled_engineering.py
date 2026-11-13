#!/usr/bin/env python3
"""Prepare frozen engineering inputs and bindings; never start a DCC or grant execution."""
from __future__ import annotations
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.owned_process import _canonical
from houdini_bridge.controlled_output import validate_controlled_policy
from run_alpha_calibration import checked, file_record, plain
from vfx_pipeline.production_hosts import validate_deployments

POLICY = {'policy': 'controlled_output_v1', 'scene_variant': 'sphere_ground_v2',
          'resolution': [128, 128], 'frames': [1], 'channels': ['R', 'G', 'B', 'A']}
MAIN_PLAN = {'schema': 'bridge.controlled-engineering.plan/1', 'domain_pack': 'material_lookdev_v1',
             'scene_profile': 'sphere_ground_v2', 'resolution': [128, 128], 'frames': [1],
             'request_prefix': 'engineering_h21'}


def _write(path, value):
    with path.open('xb') as stream:
        stream.write(_canonical(value))
    return file_record(path)


def _environment(scope):
    root = Path(scope['output_root'])
    runtime = root / 'runtime'
    paths = {name: runtime / name for name in ('tmp', 'cache', 'config', 'logs', 'houdini-prefs')}
    for path in (*paths.values(), paths['tmp'] / 'houdini', paths['tmp'] / 'nuke'):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    from dcc_task_runtime.render_profiles import OFFICIAL
    preference_path=paths['houdini-prefs']
    if scope.get('scene_profile')==OFFICIAL:
        preference_path=runtime/'houdini-prefs-__HVER__'
        (runtime/'houdini-prefs-21.0').mkdir(exist_ok=True,mode=0o700)
    environment = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
    environment.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='en_US.UTF-8', TZ='UTC',
        OCIO=scope['native_color_tokens']['houdini_static_config']['path'],
        TMPDIR=str(paths['tmp']), TMP=str(paths['tmp']), TEMP=str(paths['tmp']),
        XDG_CACHE_HOME=str(paths['cache']), XDG_CONFIG_HOME=str(paths['config']),
        HOUDINI_USER_PREF_DIR=str(preference_path), HOUDINI_TEMP_DIR=str(paths['tmp'] / 'houdini'),
        NUKE_TEMP_DIR=str(paths['tmp'] / 'nuke'), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    return environment


def _python(scope, command, environment, *, timeout_seconds=90):
    """Only the frozen plain Python executable may run pure preparation tools."""
    python = checked(scope['hosts']['supervisor_python'])
    if 'python' not in python.name.lower():
        raise ValueError('ENGINEERING_PREPARATION_PLAIN_PYTHON_REQUIRED')
    result = subprocess.run([str(python), '-I', '-B', *map(str, command)], stdin=subprocess.DEVNULL,
        capture_output=True, env=environment, timeout=timeout_seconds, check=False)
    if len(result.stdout) > 2 * 1024 * 1024 or len(result.stderr) > 128 * 1024:
        raise ValueError('ENGINEERING_PREPARATION_PYTHON_OUTPUT_LIMIT')
    if result.returncode != 0:
        detail = result.stderr.decode('utf-8', errors='replace')[-1500:]
        try:
            failure = json.loads(result.stdout)
            if isinstance(failure, dict) and failure.get('blockers'):
                detail = ';'.join(map(str, failure['blockers']))
        except (ValueError, TypeError):
            pass
        raise ValueError('ENGINEERING_PREPARATION_PYTHON_FAILED:' + detail)
    return json.loads(result.stdout)


def native_inventory(scope=None):
    prefix=[]
    from dcc_task_runtime.render_profiles import OFFICIAL
    if (scope or {}).get('scene_profile')==OFFICIAL:
        prefix=[{'start_id':role,'operation_id':role,'host':host,'parent_start_id':None,'role':role,'heavy':True}
            for role,host in (('official-open-save','hython'),('official-cold-export','hython'),('official-husk','husk'))]
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_ROLES
    if (scope or {}).get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE:
        return [{'start_id':role,'operation_id':role,'host':'hython','parent_start_id':None,'role':role,'heavy':True} for role in OFFICIAL_IDENTITY_ROLES]
    if (scope or {}).get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES:return prefix[:1]
    return prefix+[{'start_id': start, 'operation_id': operation, 'host': host, 'parent_start_id': parent,
             'role': role, 'heavy': role not in ('houdini-host', 'nuke-host')}
        for start, operation, host, parent, role in (
            ('alpha-h21', 'alpha-h21', 'husk', None, 'alpha-husk'),
            ('alpha-nuke', 'alpha-nuke', 'nuke', None, 'alpha-nuke'),
            ('houdini-initial', 'formal-h21', 'hython', None, 'houdini-host'),
            ('nuke-control', 'formal-h21', 'nuke', None, 'nuke-host'),
            ('formal-graph', 'formal-h21', 'hython', None, 'graph-worker'),
            ('houdini-reopen', 'formal-h21', 'hython', None, 'houdini-host'),
            ('main-render', 'formal-h21', 'husk', 'houdini-reopen', 'main-husk'),
            ('nuke-render', 'consume-nuke', 'nuke', None, 'nuke-render'))]


def _deployments(scope, binding, evidence_source):
    root = Path(scope['output_root'])
    result = {}
    for kind, host in (('houdini', 'hython'), ('nuke', 'nuke')):
        result[kind] = {'lifecycle': 'task_owned', 'application': kind,
            'version': scope['versions'][kind], 'executable': scope['hosts'][host]['path'],
            'supervisor_executable': scope['hosts']['supervisor_python']['path'],
            'task_root': str(root), 'session_seconds': 120, 'evidence_source': evidence_source,
            'project_color': scope['project_color'], 'native_scope': binding,
            'resource_budget': {'roots': [str(root)], 'max_bytes': scope['budget']['max_disk_bytes'],
                                'native_scope': binding}}
    boundaries = scope.get('software_native_boundaries')
    if 'software_native_boundaries' in scope:
        if evidence_source != 'software_test' or not isinstance(boundaries, dict) or set(boundaries) != {'houdini_launch_script', 'nuke_api', 'alpha_husk_script'}:
            raise ValueError('ENGINEERING_PREPARATION_SOFTWARE_BOUNDARIES_INVALID')
        launch = checked(boundaries['houdini_launch_script'])
        api = checked(boundaries['nuke_api'])
        checked(boundaries['alpha_husk_script'])
        if api.name != 'nuke.py':
            raise ValueError('ENGINEERING_PREPARATION_SOFTWARE_NUKE_API_REQUIRED')
        result['houdini'].update(software_launch_script=str(launch),
            software_launch_script_sha256=boundaries['houdini_launch_script']['sha256'])
        result['nuke']['software_api_dir'] = str(api.parent)
    from dcc_task_runtime.render_profiles import output_policy,LEGACY
    result['houdini'].update(output_acceptance=validate_controlled_policy(output_policy(scope.get('scene_profile',LEGACY))),
        writer_executable={'path': scope['hosts']['husk']['path'], 'version': scope['versions']['houdini'],
                           'sha256': scope['hosts']['husk']['sha256']})
    return result



def _alpha_preflight(scope,snapshot,scope_path,bindings_path,environment):
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    if scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES:
        return {'state':'NOT_APPLICABLE_DIAGNOSTIC_ONLY','native_execution_status':'NOT_RUN'}
    result=_python(scope,[snapshot/'tools/run_alpha_calibration.py','--scope',scope_path,
        '--bindings',bindings_path,'--preflight'],environment)
    if result.get('state')!='PREPARED' or result.get('native_execution_status')!='NOT_RUN':
        raise ValueError('ENGINEERING_PREPARATION_PREFLIGHT_NOT_PREPARED')
    return result


def _verify_prepared(scope, receipt_path):
    receipt = json.loads(plain(receipt_path).read_text(encoding='utf-8'))
    if receipt.get('schema') != 'bridge.controlled-engineering.preparation/1':
        raise ValueError('ENGINEERING_PREPARATION_RECEIPT_INVALID')
    if receipt.get('scope_sha256') != scope.binding['sha256']:
        raise ValueError('ENGINEERING_PREPARATION_SCOPE_CHANGED')
    for record in receipt['immutable_files']:
        checked(record)
    snapshot = Path(receipt['snapshot_root'])
    bindings = Path(receipt['bindings']['path'])
    environment = json.loads(bindings.read_text(encoding='utf-8'))['environment']
    preflight=_alpha_preflight(scope.scope,snapshot,scope.path,bindings,environment)
    driver_preflight = _python(scope.scope, [snapshot / 'tools/run_controlled_engineering.py',
        '--scope', scope.path, '--bindings', bindings], environment)
    if driver_preflight.get('state') != 'PREPARED':
        raise ValueError('ENGINEERING_PREPARATION_DRIVER_NOT_PREPARED')
    return {**receipt, 'preflight': preflight, 'driver_preflight': driver_preflight, 'native_execution_status': 'NOT_RUN'}


def _prepare(scope_path, *, authorized=False):
    scope_path = plain(scope_path)
    binding = {'path': str(scope_path), 'sha256': file_record(scope_path)['sha256']}
    native = NativeScope(binding)
    scope = native.scope
    for record in scope.get('process_image_policy',{}).get('tools',{}).values(): checked(record)
    before = native.snapshot()
    expected_status = 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION' if authorized else 'PREPARED_NOT_AUTHORIZED'
    if scope.get('execution_authorized') is not authorized or scope.get('status') != expected_status:
        raise ValueError('ENGINEERING_PREPARATION_UNAUTHORIZED_SCOPE_REQUIRED')
    if authorized and not isinstance(scope.get('activation_review'), dict):
        raise ValueError('ENGINEERING_PREPARATION_ACTIVATION_REVIEW_REQUIRED')
    if before['dcc_starts'] != 0:
        raise ValueError('ENGINEERING_PREPARATION_SCOPE_ALREADY_USED')
    root = native.root
    receipt_path = root / 'engineering-preparation.json'
    if receipt_path.exists():
        return _verify_prepared(native, receipt_path)
    project = root / 'project'
    if any(path.exists() for path in (project, root / 'frozen-inputs', root / 'alpha-chart',
                                     root / 'runtime-bindings.json', root / 'main-writer-plan.json')):
        raise ValueError('ENGINEERING_PREPARATION_PARTIAL_OUTPUT_REQUIRES_REVIEW')
    for name in ('run_controlled_engineering.py', 'prepare_controlled_engineering.py',
                 'run_alpha_calibration.py', 'prepare_native_alpha_scene.py', 'verify_controlled_output.py'):
        if not (ROOT / 'tools' / name).is_file():
            raise ValueError('ENGINEERING_PREPARATION_DRIVER_SOURCE_REQUIRED:' + name)
    for record in scope['hosts'].values(): checked(record)
    color = scope.get('project_color')
    if not color or color['colorspace'] != 'ACEScg' or scope['versions'] != {'houdini': '21.0.631', 'nuke': '17.0v1'}:
        raise ValueError('ENGINEERING_PREPARATION_FROZEN_H21_ACESCG_REQUIRED')
    evidence = scope.get('evidence_source', 'real_host')
    if evidence not in ('real_host', 'software_test'):
        raise ValueError('ENGINEERING_PREPARATION_EVIDENCE_SOURCE_INVALID')
    environment = _environment(scope)
    frozen = root / 'frozen-inputs'
    frozen.mkdir(mode=0o700)
    from dcc_task_runtime.render_profiles import OFFICIAL,LEGACY,output_policy
    official=scope.get('scene_profile',LEGACY)==OFFICIAL
    policy=output_policy(scope.get('scene_profile',LEGACY))
    construction=None;scene_records=[]
    if official:
        case=scope['official_case']
        from houdini_bridge.official_karma_inputs import derivation_rule
        if case.get('derivation')!=derivation_rule(root):
            raise ValueError('OFFICIAL_PREPARATION_DERIVATION_RULE_REQUIRED')
        from houdini_bridge.official_karma_observation import checked_bytes
        for record in (case['source_contract'],case['static_review'],*case['original_files']):
            checked_bytes(record)
        if len(case['source_files'])!=len(case['original_files']):
            raise ValueError('OFFICIAL_PREPARATION_SOURCE_COPY_REQUIRED')
        for source,destination in zip(case['original_files'],case['source_files']):
            target_file=Path(destination['path'])
            if (not target_file.is_relative_to(root/'official-inputs')
                    or {k:source[k] for k in ('bytes','sha256')}!={k:destination[k] for k in ('bytes','sha256')}):
                raise ValueError('OFFICIAL_PREPARATION_SOURCE_COPY_MISMATCH')
            target_file.parent.mkdir(parents=True,exist_ok=True)
            with target_file.open('xb') as stream:stream.write(checked_bytes(source))
            checked_bytes(destination)
        checked_bytes(case['source_hip'])
        original=Path(case['source_hip']['path']).parent
        target=Path(case['paths']['official_hip']).parent
        target.mkdir(parents=True,exist_ok=False)
        # Preserve $HIP-relative resources without copying the original HIP as a result.
        for record in case['source_files']:
            source=Path(record['path'])
            if source==Path(case['source_hip']['path']): continue
            relative=source.relative_to(original)
            destination=target/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as stream: stream.write(checked_bytes(record))
            scene_records.append(file_record(destination))
    else:
        baseline=ROOT/'docs/official-baselines/karma/frozen-scene-v2.json'
        copied_scene=frozen/'frozen-scene-v2.json'
        with copied_scene.open('xb') as stream: stream.write(checked(file_record(baseline)).read_bytes())
        scene_record=file_record(copied_scene);scene_records=[scene_record]
        construction=[{'index':0,'asset_id':'frozen-sphere-ground-v2',
            'semantic_role':'render_scene_configuration','source_uri':str(copied_scene),
            'bytes':scene_record['bytes'],'sha256':scene_record['sha256']}]
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES
    diagnostic=scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES
    deployments = {} if diagnostic else _deployments(scope, binding, evidence)
    control = project / 'control'
    if not diagnostic:
        validate_deployments(deployments['houdini'], deployments['nuke'], controller_root=control,
            repo_root=ROOT, allow_software_processes=evidence == 'software_test')
    from prepare_workbuddy_graph import prepare_graph
    prepare_graph(project, app=None, scheduler_root=root / 'scheduler', execution_profile=not diagnostic,
        render_profile=not diagnostic, production_host_config=deployments.get('houdini'), production_nuke_config=deployments.get('nuke'),
        construction_input_manifest=construction,official_case_derivation=case['derivation'] if official else None)
    snapshot = control / 'snapshot'
    if official:
        for source,digest in case['source_freeze'].items():
            if file_record(source)['sha256']!=digest:
                raise ValueError('OFFICIAL_PREPARATION_FROZEN_SOURCE_CHANGED')
    for name in ('run_controlled_engineering.py', 'prepare_controlled_engineering.py', 'run_alpha_calibration.py'):
        if not (snapshot / 'tools' / name).is_file():
            raise ValueError('ENGINEERING_PREPARATION_SNAPSHOT_DRIVER_REQUIRED:' + name)
    hroot = next((parent for parent in Path(scope['hosts']['husk']['path']).parents
                  if parent.name == 'Houdini21.0.631'), None)
    if hroot is None: raise ValueError('ENGINEERING_PREPARATION_HOUDINI_ROOT_REQUIRED')
    _python(scope, [snapshot / 'tools/prepare_native_alpha_scene.py', '--output-root', root / 'alpha-chart',
                   '--houdini-root', hroot, '--colorspace', 'ACEScg',
                   '--scene-profile',scope.get('scene_profile',LEGACY)], environment)
    alpha_path = root / 'alpha-chart/preparation.json'
    alpha = json.loads(alpha_path.read_text(encoding='utf-8'))
    if scope.get('software_native_boundaries') is not None:
        alpha['command'].insert(1, str(checked(scope['software_native_boundaries']['alpha_husk_script'])))
        alpha_path.write_bytes(_canonical(alpha))
    display_record=None
    if official:
        script=('import sys,json; '
            +'sys.path[:0]='+repr([str(snapshot/'packages'/name/'src') for name in ('dcc-task-runtime','houdini-bridge')])+'; '
            +'from houdini_bridge.official_karma_display import _processor; '
            +'from houdini_bridge.official_karma import canonical_sha256; '
            +'value=json.loads(sys.argv[1]); p,cache=_processor(value); '
            +"print(json.dumps({'state':'VERIFIED_SOFTWARE_OCIO_PROCESSOR','ocio_version':value['ocio_version'],"
            +"'processor_cache_id':cache,'policy_sha256':canonical_sha256(value),'native_execution_status':'NOT_RUN'}))")
        display_report=_python(scope,['-c',script,json.dumps(case['display_policy'])],environment)
        display_record=_write(root/'official-display-preflight.json',display_report)
    plan = json.loads(json.dumps(MAIN_PLAN))
    if official: plan.update(domain_pack='lighting_camera_render_v1',scene_profile=OFFICIAL,resolution=[420,300])
    driver_plan = _write(root / 'driver-plan.json', plan)
    bindings_path = root / 'runtime-bindings.json'
    plugin_build = file_record(snapshot / 'plugins/houdini/_impl/houdini_bridge_addon.py')['sha256']
    command = [scope['hosts']['supervisor_python']['path'], '-I', '-B', str(snapshot / 'tools/run_controlled_engineering.py'),
               '--scope', str(scope_path), '--bindings', str(bindings_path)]
    writer_plan = _write(root / 'main-writer-plan.json', {
        'schema': 'bridge.controlled-output.main-writer-plan/1.0', 'state': 'PREPARED', 'command': command,
        'output_acceptance': policy, 'project_color': color, 'route_sha256': alpha['route_sha256'],
        'plugin_build': plugin_build})
    deployment_records = {kind: _write(root / (kind + '-deployment.json'), value) for kind, value in deployments.items()}
    project_files = {name: file_record(path) for name, path in (
        ('manifest', control / 'run.json'), ('snapshot_manifest', control / 'snapshot-manifest.json'),
        ('server', control / 'server.py'))}
    immutable = [file_record(path) for path in sorted(project.rglob('*')) if path.is_file()]
    if official: immutable.extend([*case['source_files'],display_record])
    immutable.extend([*scene_records, driver_plan, writer_plan, *deployment_records.values()])
    immutable.extend(file_record(path) for path in sorted((root / 'alpha-chart').rglob('*')) if path.is_file())
    source_files = {record['path']: record['sha256'] for record in immutable}
    bindings_value = {'schema': 'bridge.engineering-closure.runtime-bindings/1', 'scope_sha256': binding['sha256'],
        'source_freeze': source_files, 'alpha_preparation': file_record(alpha_path),
        'nuke_output_root': str(root / 'alpha-nuke'), 'plugin_build': plugin_build,
        'route_sha256': alpha['route_sha256'], 'output_acceptance': policy, 'main_writer_plan': writer_plan,
        'main_plan': plan, 'driver_plan': driver_plan, 'project_files': project_files,
        'environment': environment, 'deployments': deployment_records, 'controller_root': str(control),
        'project_root': str(project), 'native_start_inventory': native_inventory(scope), 'evidence_source': evidence,
        'outputs': {'houdini_pattern': str(project / 'saves/main.%04d.exr'),
                    'nuke_pattern': str(project / 'saves/nuke.%04d.exr'),
                    'nuke_script': str(project / 'saves/composite.nk')}}
    bindings_record = _write(bindings_path, bindings_value)
    preflight=_alpha_preflight(scope,snapshot,scope_path,bindings_path,environment)
    driver_preflight = _python(scope, [snapshot / 'tools/run_controlled_engineering.py',
        '--scope', scope_path, '--bindings', bindings_path], environment)
    if driver_preflight.get('state') != 'PREPARED':
        raise ValueError('ENGINEERING_PREPARATION_DRIVER_NOT_PREPARED')
    if native.snapshot()['dcc_starts'] != before['dcc_starts']:
        raise ValueError('ENGINEERING_PREPARATION_UNEXPECTED_NATIVE_START')
    receipt = {'schema': 'bridge.controlled-engineering.preparation/1', 'scope_sha256': binding['sha256'],
        'project_root': str(project), 'snapshot_root': str(snapshot), 'bindings': bindings_record,
        'immutable_files': [*immutable, bindings_record], 'preflight': preflight,
        'driver_preflight': driver_preflight, 'native_execution_status': 'NOT_RUN'}
    _write(receipt_path, receipt)
    return receipt


def prepare(scope_path):
    return _prepare(scope_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True)
    args = parser.parse_args()
    result = prepare(args.scope)
    print(json.dumps({'schema': result['schema'], 'project_root': result['project_root'],
        'bindings': result['bindings'], 'preflight': result['preflight'],
        'driver_preflight': result['driver_preflight'], 'native_execution_status': 'NOT_RUN'}, indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
