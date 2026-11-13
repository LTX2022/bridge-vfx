"""Trusted deployment lifecycle for the formal WorkBuddy host boundaries.

Only the controller calls this module. Model tools receive bound transports,
never executable paths, lifecycle configuration or supervisor capabilities.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
from dcc_task_runtime.owned_process import OwnedProcessHandle
from dcc_task_runtime.project_color import validate_project_color
from dcc_task_runtime.canonical import canonical_json, canonical_sha256
from dcc_task_runtime.platform_support import (lock_file, unlock_file, atomic_write,
    atomic_replace, remove_owned_path, ensure_private_directory, open_private_file)


def _atomic(path,value):
    ensure_private_directory(path.parent)
    atomic_write(path,json.dumps(value,sort_keys=True).encode('utf-8'),owned_root=path.parent)


@contextlib.contextmanager
def _deployment_lock(control):
    ensure_private_directory(control)
    fd=open_private_file(control/'production-hosts.lock',os.O_CREAT|os.O_RDWR)
    acquired=False
    try:
        lock_file(fd,blocking=True)
        acquired=True
        yield
    finally:
        try:
            if acquired:unlock_file(fd)
        finally:
            os.close(fd)


def _rect_shape_monitor_budget(scope, budget):
    """仅返回本授权两个精确磁盘监控目录；不授予任何新文件读写路径。"""
    from dcc_task_runtime.rectlight_shape_scope import object_record,RESOURCE_PROFILE
    if scope.resource_profile!=RESOURCE_PROFILE:raise ValueError('RECT_SHAPE_PROFILE_REQUIRED')
    authority=object_record(scope.scope['shape_authority'])
    expected=[scope.root.parent,Path(authority['plan']['path']).parent]
    if (type(budget) is not dict or budget.get('roots')!=[str(p) for p in expected]
            or budget.get('max_bytes')!=1073741824 or budget.get('native_scope')!=scope.binding):
        raise ValueError('RECT_SHAPE_EXACT_MONITOR_BUDGET_REQUIRED')
    for path in expected:
        if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('RECT_SHAPE_EXACT_MONITOR_BUDGET_REQUIRED')
    if expected[0]==expected[1] or expected[0].is_relative_to(expected[1]) or expected[1].is_relative_to(expected[0]):
        raise ValueError('RECT_SHAPE_DISTINCT_MONITOR_ROOTS_REQUIRED')
    seconds=budget.get('max_seconds',120)
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=120:
        raise ValueError('RECT_SHAPE_MONITOR_TIME_REQUIRED')
    return {'roots':[str(p) for p in expected],'max_bytes':1073741824,'max_seconds':seconds,'native_scope':dict(scope.binding)}


def native_scope_budget(binding, budget, *owned_paths):
    """Validate a trusted frozen scope without admitting or starting a process."""
    from dcc_task_runtime.native_scope import NativeScope, GEOMETRY_RESOURCE_PROFILE
    scope = NativeScope(binding)
    for raw in owned_paths:
        path = Path(raw).expanduser()
        if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(scope.root):
            raise ValueError('PRODUCTION_PATH_OUTSIDE_NATIVE_SCOPE')
    # owned_paths始终经过上方原任务根严格检查；新分支只验证精确监控配置。
    from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
    if scope.resource_profile==RECT_SHAPE_PROFILE:
        return _rect_shape_monitor_budget(scope,budget)
    # 只有完整认证的新几何合同可用1GiB；旧范围仍只接受原512/固定640MiB。
    storage_revision=scope.scope.get('case_storage_revision') is not None
    geometry=scope.resource_profile == GEOMETRY_RESOURCE_PROFILE
    disk_limit=scope.scope['budget']['max_disk_bytes'] if storage_revision or geometry else 512 * 1024 * 1024
    if (not isinstance(budget, dict) or type(budget.get('max_bytes')) is not int
            or not 0 < budget['max_bytes'] <= disk_limit
            or storage_revision and (disk_limit!=671088640 or budget['max_bytes']!=disk_limit)
            or geometry and (disk_limit!=1073741824 or budget['max_bytes']!=disk_limit)
            or budget.get('native_scope', scope.binding) != scope.binding):
        raise ValueError('PRODUCTION_NATIVE_SCOPE_BUDGET_INVALID')
    for raw in budget.get('roots', []):
        path = Path(raw)
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(scope.root):
            raise ValueError('PRODUCTION_PATH_OUTSIDE_NATIVE_SCOPE')
    from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as GEOMETRY_FEEDBACK_PROFILE
    seconds = scope.role_seconds('houdini-host' if scope.resource_profile == GEOMETRY_FEEDBACK_PROFILE else 'graph-worker')
    if scope.resource_profile is not None:
        configured = budget.get('max_seconds', seconds)
        if (type(configured) not in (int, float) or not math.isfinite(configured)
                or not 0 < configured <= seconds):
            raise ValueError('PRODUCTION_NATIVE_SCOPE_BUDGET_INVALID')
        seconds = configured
    return {'roots': [str(scope.root)], 'max_bytes': budget['max_bytes'],
            'max_seconds': seconds, 'native_scope': dict(scope.binding)}


def native_scope_host_binding(binding, kind, version, executable, supervisor, *, project_color, writer=None, allow_missing_writer=False):
    """Keep the approved project and native binaries fixed across deployment/rebind."""
    from dcc_task_runtime.native_scope import NativeScope
    if not project_color:
        raise ValueError('PRODUCTION_NATIVE_SCOPE_PROJECT_COLOR_MISMATCH')
    NativeScope(binding).validate_host(kind, version, Path(executable).resolve(), Path(supervisor).resolve(),
        project_color=project_color, writer=writer, allow_missing_writer=allow_missing_writer)


def _validate(raw,kind,controller_root,repo_root,allow_software):
    if not isinstance(raw,dict) or raw.get('lifecycle')!='task_owned':raise ValueError('PRODUCTION_TASK_OWNED_CONFIG_REQUIRED:'+kind)
    if raw.get('application')!=kind:raise ValueError('PRODUCTION_APPLICATION_MISMATCH')
    if raw.get('version') not in ({'21.0.631','22.0.429','22.0.459'} if kind=='houdini' else {'17.0v1'}):raise ValueError('PRODUCTION_VERSION_REQUIRED')
    for key in ('executable','supervisor_executable'):
        path=Path(str(raw.get(key) or '')).expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path,os.X_OK):raise ValueError('PRODUCTION_EXECUTABLE_UNVERIFIED:'+key)
    task_root=Path(str(raw.get('task_root') or '')).expanduser()
    if not task_root.is_absolute() or task_root.is_symlink():raise ValueError('PRODUCTION_TASK_ROOT_INVALID')
    task_root=task_root.resolve()
    if not controller_root.is_relative_to(task_root):raise ValueError('PRODUCTION_CONTROLLER_OUTSIDE_BUDGET_ROOT')
    budget=raw.get('resource_budget',{})
    if type(budget.get('max_bytes')) is not int or budget['max_bytes']<=0:raise ValueError('PRODUCTION_DISK_BUDGET_REQUIRED')
    roots=budget.get('roots')
    if not isinstance(roots,list) or not roots:raise ValueError('PRODUCTION_RESOURCE_ROOT_REQUIRED')
    scope_binding = raw.get('native_scope')
    if scope_binding is None and 'native_scope' in budget:
        raise ValueError('PRODUCTION_NATIVE_SCOPE_BINDING_REQUIRED')
    scoped_budget = native_scope_budget(scope_binding, budget, task_root, controller_root) if scope_binding is not None else None
    paths=[]
    for name in ([] if scoped_budget is not None else roots):
        p=Path(name)
        if not p.is_absolute() or p.is_symlink() or not p.resolve().is_relative_to(task_root):raise ValueError('PRODUCTION_RESOURCE_ROOT_INVALID')
        paths.append(p.resolve())
    if scoped_budget is None and not any(task_root==p for p in paths):raise ValueError('PRODUCTION_BUDGET_MUST_COVER_TASK_ROOT')
    seconds=raw.get('session_seconds')
    session_limit=120
    if scoped_budget is not None and kind == 'houdini':
        from dcc_task_runtime.native_scope import NativeScope, GEOMETRY_RESOURCE_PROFILE
        from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as GEOMETRY_FEEDBACK_PROFILE
        # 生命周期可覆盖建图/冷开后的受限操作；单次渲染/非建图操作门仍由原命令保持。
        if NativeScope(scope_binding).resource_profile in (GEOMETRY_RESOURCE_PROFILE, GEOMETRY_FEEDBACK_PROFILE):
            session_limit=240
    if type(seconds) not in (float,int) or not math.isfinite(seconds) or not 0<seconds<=session_limit:raise ValueError('PRODUCTION_SESSION_BUDGET_REQUIRED')
    software=raw.get('evidence_source')=='software_test'
    if raw.get('evidence_source') not in ('software_test','real_host'):raise ValueError('PRODUCTION_EVIDENCE_SOURCE_REQUIRED')
    if software and allow_software is not True:raise ValueError('SOFTWARE_PROCESS_BOUNDARY_NOT_AUTHORIZED')
    if not software and 'software_api_dir' in raw:raise ValueError('SOFTWARE_API_IN_PRODUCTION')
    if not software and 'software_launch_script' in raw:raise ValueError('SOFTWARE_LAUNCH_IN_PRODUCTION')
    color_config={}
    if 'project_color' in raw:
        color_config['project_color']=validate_project_color(raw['project_color'])
    writer_config={}
    if 'writer_executable' in raw:
        writer=raw['writer_executable']
        if (kind!='houdini' or not isinstance(writer,dict) or set(writer) not in
                ({'path','version','sha256'}, {'schema','platform','version','image'})):
            raise ValueError('PRODUCTION_WRITER_EXECUTABLE_INVALID')
        if writer['version']!=raw['version']:
            raise ValueError('PRODUCTION_WRITER_VERSION_MISMATCH')
        from dcc_task_runtime.process_image import freeze_executable
        if 'image' in writer:
            # Repeated deployment validation authenticates the current file
            # against the complete identity frozen by the first validation.
            from dcc_task_runtime.owned_process import _freeze_writer_executable
            writer_config['writer_executable']=_freeze_writer_executable(writer)
        else:
            writer_config['writer_executable']=freeze_executable(
                writer['path'],writer['version'],writer['sha256'])
    acceptance_config={}
    if 'output_acceptance' in raw:
        if kind!='houdini':raise ValueError('CONTROLLED_OUTPUT_APPLICATION_INVALID')
        from houdini_bridge.controlled_output import validate_controlled_policy
        acceptance_config['output_acceptance']=validate_controlled_policy(raw['output_acceptance'])
    if 'alpha_calibration' in raw:
        if kind!='houdini' or 'output_acceptance' not in raw or not isinstance(raw['alpha_calibration'],dict):
            raise ValueError('CONTROLLED_OUTPUT_CALIBRATION_BINDING_INVALID')
        acceptance_config['alpha_calibration']=json.loads(json.dumps(raw['alpha_calibration'],allow_nan=False))
    if scoped_budget is not None and kind == 'houdini' and 'output_acceptance' not in acceptance_config:
        raise ValueError('PRODUCTION_NATIVE_SCOPE_CONTROLLED_OUTPUT_REQUIRED')
    launch_config={}
    if 'software_launch_script' in raw:
        if kind!='houdini':raise ValueError('PRODUCTION_SOFTWARE_LAUNCH_UNSUPPORTED:'+kind)
        script=Path(str(raw['software_launch_script'] or ''))
        if not script.is_absolute() or script.is_symlink() or not script.is_file():
            raise ValueError('PRODUCTION_SOFTWARE_LAUNCH_SCRIPT_INVALID')
        digest=hashlib.sha256(script.read_bytes()).hexdigest()
        if ('software_launch_script_sha256' in raw
                and raw['software_launch_script_sha256']!=digest):
            raise ValueError('PRODUCTION_SOFTWARE_LAUNCH_SCRIPT_CHANGED')
        launch_config={'software_launch_script':str(script.resolve()),'software_launch_script_sha256':digest}
    if scoped_budget is not None:
        native_scope_host_binding(scope_binding, kind, raw['version'], raw['executable'], raw['supervisor_executable'],
            project_color=color_config.get('project_color'), writer=writer_config.get('writer_executable'),
            allow_missing_writer=software and allow_software is True)
    if 'feedback_ledger_root' in raw:
        native = __import__('dcc_task_runtime.native_scope',fromlist=['NativeScope']).NativeScope(scope_binding)
        phase = native.scope.get('feedback_phase') or {}
        reader = __import__('dcc_task_runtime.native_scope',fromlist=['_reuse_record_bytes'])._reuse_record_bytes
        from dcc_task_runtime.native_scope import GEOMETRY_RESOURCE_PROFILE
        from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
        from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as GEOMETRY_FEEDBACK_PROFILE
        if native.resource_profile in (GEOMETRY_RESOURCE_PROFILE, GEOMETRY_FEEDBACK_PROFILE, RECT_SHAPE_PROFILE):
            # 已认证独立任务只共用本根固定账本，不借旧feedback/creative phase。
            delivery = {'artifact_ledger': str(native.root / 'artifact_ledger')}
        elif native.scope.get('creative_phase') is not None:
            anchor = json.loads(reader(native.scope['creative_phase']['input_source']))
            delivery = {'artifact_ledger': native.scope['creative_phase'].get('ledger_root',anchor['producer_ledger'])}
        else:
            delivery = json.loads(reader(phase.get('source_delivery')))
        ledger = Path(raw['feedback_ledger_root'])
        if (str(ledger) != delivery.get('artifact_ledger') or not ledger.is_absolute()
                or not (ledger/'artifacts.sqlite3').is_file()
                or any(p.is_symlink() for p in (ledger/'artifacts.sqlite3',ledger,*ledger.parents))
                or not ledger.resolve().is_relative_to(task_root)):
            raise ValueError('PRODUCTION_FEEDBACK_LEDGER_REQUIRED')
    plugin=repo_root/'plugins'/kind/('_impl/houdini_bridge_addon.py' if kind=='houdini' else 'nuke_bridge_addon.py')
    if not plugin.is_file():raise ValueError('BUNDLED_PLUGIN_MISSING')
    return {**raw,**launch_config,**writer_config,**color_config,**acceptance_config,'task_root':str(task_root),'controller_root':str(controller_root.resolve()),
            'plugin_build':hashlib.sha256(plugin.read_bytes()).hexdigest(),
            'resource_budget':scoped_budget if scoped_budget is not None else {'roots':[str(p) for p in paths],'max_bytes':budget['max_bytes']}}


def validate_deployments(host_config,nuke_config,*,controller_root,repo_root,allow_software_processes=False,application='pipeline'):
    control=Path(controller_root).resolve();repo=Path(repo_root).resolve()
    if application not in ('pipeline','nuke'):raise ValueError('PRODUCTION_APPLICATION_MISMATCH')
    deployments=[('nuke',nuke_config)] if application=='nuke' else [('houdini',host_config),('nuke',nuke_config)]
    configs=[_validate(raw,kind,control,repo,allow_software_processes) for kind,raw in deployments]
    scopes = [config.get('native_scope') for config in configs]
    if any(binding is not None for binding in scopes) and any(binding != scopes[0] for binding in scopes):
        raise ValueError('PRODUCTION_NATIVE_SCOPE_DEPLOYMENT_MISMATCH')
    selections=[config['project_color'] for config in configs if 'project_color' in config]
    if len(selections)>1 and any(value!=selections[0] for value in selections[1:]):
        raise ValueError('PROJECT_COLOR_SELECTION_INVALID:deployment_mismatch')
    return configs


def _shared_env(config,control,scheduler):
    import dcc_task_runtime,houdini_bridge,nuke_bridge,vfx_pipeline
    roots=[str(Path(p.__file__).resolve().parent.parent) for p in (dcc_task_runtime,houdini_bridge,nuke_bridge,vfx_pipeline)]
    if config.get('evidence_source')=='software_test' and config.get('software_api_dir'):
        roots.insert(0,str(Path(config['software_api_dir']).resolve()))
    return {'PYTHONPATH':os.pathsep.join(dict.fromkeys(roots)),'PYTHONNOUSERSITE':'1',
        'HOUDINI_BRIDGE_STATE_DIR':str(control/'houdini-instances'),
        'HOUDINI_BRIDGE_TASK_STATE_DIR':str(control/'houdini-instances'),
        'BRIDGE_SKILLS_STATE_ROOT':str(control/'host-runtime-state'),
        'BRIDGE_ARTIFACT_LEDGER_ROOT':str(control/'artifact_ledger'),
        'BRIDGE_SKILLS_SCHEDULER_ROOT':str(scheduler)}


class _HoudiniDeploymentIdentityMismatch(ValueError):
    def __init__(self, observed):
        super().__init__('PRODUCTION_HOST_DEPLOYMENT_IDENTITY_MISMATCH')
        self.observed = observed


class _HoudiniHostStopped(ValueError):
    def __init__(self, observed, identity):
        super().__init__('PRODUCTION_HOST_STOPPED')
        self.observed = observed
        self.ready_identity = dict(identity)


def _h_config(config,work,control,*,task_id,binding_override=None):
    from houdini_bridge.client import HoudiniClient
    if not work.resolve().is_relative_to(Path(config['task_root']).resolve()):
        raise ValueError('PRODUCTION_HOST_WORKDIR_UNTRUSTED_RECONCILE_REQUIRED')
    ready_path=work/'host.ready'
    ready=json.loads(ready_path.read_text(encoding='utf-8'))
    binding=binding_override if binding_override is not None else json.loads((work/'supervisor-binding.json').read_text(encoding='utf-8'))
    supervisor_identity=binding.get('identity')
    if (not isinstance(supervisor_identity,dict) or supervisor_identity.get('task_id')!=task_id
            or not isinstance(supervisor_identity.get('launch_nonce'),str)
            or not supervisor_identity['launch_nonce']
            or Path(binding['directory']).is_symlink()
            or Path(binding['directory']).resolve()!=work.resolve()/('supervisor-'+supervisor_identity['launch_nonce'])):
        raise ValueError('PRODUCTION_SUPERVISOR_BINDING_UNTRUSTED_RECONCILE_REQUIRED')
    observed=OwnedProcessHandle(binding['directory'],supervisor_identity)
    identity=ready.get('task_host_identity')
    if not isinstance(identity,dict) or identity.get('pid')!=observed.pid or identity.get('launch_nonce')!=supervisor_identity['launch_nonce']:raise ValueError('PRODUCTION_READY_IDENTITY_INVALID')
    trusted={'task_id':task_id,'version':config['version'],'plugin_build':config['plugin_build']}
    if 'writer_executable' in config:
        writer=config['writer_executable']
        digest=canonical_sha256(writer)
        trusted['writer_executable_sha256']=digest
        started=observed.started
        writer_binding=started.get('writer_process_binding')
        try:
            from dcc_task_runtime.process_image import freeze_executable
            frozen=freeze_executable(writer['image']['path'],writer['version'],writer['image']['sha256'])
            anchor=writer_binding.get('host_anchor') if isinstance(writer_binding,dict) else None
            valid=(canonical_json(frozen)==canonical_json(writer)
                and supervisor_identity.get('writer_executable_sha256')==digest
                and started.get('identity',{}).get('writer_executable_sha256')==digest
                and 'writer_process_binding_error' not in started
                and isinstance(writer_binding,dict)
                and canonical_json(writer_binding.get('expected_executable'))==canonical_json(writer)
                and isinstance(anchor,dict) and type(anchor.get('pid')) is int
                and anchor['pid']==observed.pid)
        except (ImportError,OSError,ValueError,KeyError,TypeError):
            valid=False
        if not valid:
            raise _HoudiniDeploymentIdentityMismatch(observed)
    if any(identity.get(key)!=value for key,value in trusted.items()):
        raise _HoudiniDeploymentIdentityMismatch(observed)
    if observed.poll() is not None:raise _HoudiniHostStopped(observed,identity)
    state=control/'houdini-instances/instances'
    record=json.loads((state/(str(observed.pid)+'.json')).read_text(encoding='utf-8'))
    name=record.get('token_file')
    if not isinstance(name,str) or Path(name).name!=name:raise ValueError('PRODUCTION_AUTH_TOKEN_MISSING')
    token=(state/name).read_text(encoding='utf-8')
    client = HoudiniClient(ready['port'], token=token)
    actual=client.health().get('task_host_identity')
    if not isinstance(actual,dict):raise ValueError('PRODUCTION_HEALTH_IDENTITY_MISMATCH')
    if any(actual.get(key)!=value for key,value in trusted.items()):
        raise _HoudiniDeploymentIdentityMismatch(observed)
    # A scene open/rebind is the only permitted in-place identity change while
    # the trusted host process survives a controller restart.  Every process
    # and deployment identity field must still match the ready receipt; only a
    # monotonic scene epoch may advance, and the new receipt is persisted before
    # the controller records the bound host.
    identity_without_epoch={key:value for key,value in identity.items() if key!='scene_epoch'}
    actual_without_epoch={key:value for key,value in actual.items() if key!='scene_epoch'}
    if actual_without_epoch!=identity_without_epoch:
        raise ValueError('PRODUCTION_HEALTH_IDENTITY_MISMATCH')
    if (type(identity.get('scene_epoch')) is not int
            or type(actual.get('scene_epoch')) is not int
            or actual['scene_epoch']<identity['scene_epoch']):
        raise ValueError('PRODUCTION_SCENE_EPOCH_INVALID')
    if actual['scene_epoch']!=identity['scene_epoch']:
        _reconcile_scene_transition_records(
            control, client, task_id=task_id,
            expected_identity=identity, actual_identity=actual,
            task_root=Path(config['task_root']).resolve(),
        )
        if not _scene_epoch_transition_is_authorized(
                control, task_id=task_id,
                from_epoch=identity['scene_epoch'], to_epoch=actual['scene_epoch'],
                task_root=Path(config['task_root']).resolve(),
                expected_identity=identity, actual_identity=actual):
            raise ValueError('PRODUCTION_SCENE_EPOCH_UNAUTHORIZED')
        ready={**ready,'task_host_identity':actual}
        _atomic(ready_path,ready)
        identity=actual
    return {**config,'transport':'http','host':'127.0.0.1','port':ready['port'],'token':token,
            'expected_identity':identity,'work_dir':str(work),'ledger_root':str(control/'artifact_ledger')}



HOST_STOP_RESERVE_SECONDS = 6.0


def host_phase_budget(config, requested_seconds=120.0):
    """Cap a child job to its authenticated host deadline, including stop grace."""
    from dcc_task_runtime.owned_process import read_receipt
    if (type(requested_seconds) not in (int, float) or not math.isfinite(requested_seconds)
            or requested_seconds <= 0):
        raise ValueError('PRODUCTION_PHASE_BUDGET_INVALID')
    try:
        kind = config['application']
        expected = config['expected_identity']
        work = Path(config['work_dir'])
        task_root = Path(config['task_root'])
        if (kind not in {'houdini', 'nuke'} or not work.is_absolute()
                or not work.resolve().is_relative_to(task_root.resolve())
                or any(path.is_symlink() for path in (work, *work.parents))
                or not isinstance(expected, dict)
                or not isinstance(expected.get('launch_nonce'), str)
                or not expected['launch_nonce'] or type(expected.get('pid')) is not int
                or expected.get('plugin_build') != config['plugin_build']
                or expected.get('version') != config['version']):
            raise ValueError('invalid host binding')
        if kind == 'houdini':
            pointer = work / 'supervisor-binding.json'
            if pointer.is_symlink():
                raise ValueError('linked binding')
            binding = json.loads(pointer.read_text(encoding='utf-8'))
            directory = Path(binding['directory'])
            identity = binding['identity']
            if directory != work / ('supervisor-' + expected['launch_nonce']):
                raise ValueError('invalid supervisor path')
        else:
            directory = Path(config['supervisor_dir'])
            identity = config['supervisor_identity']
            if directory != work / 'supervisor' or work.name != 'nuke-host-' + expected['launch_nonce']:
                raise ValueError('invalid supervisor path')
        if (directory.is_symlink() or not isinstance(identity, dict)
                or identity.get('task_id') != expected.get('task_id')
                or identity.get('launch_nonce') != expected['launch_nonce']
                or any(expected.get(key) != value for key, value in identity.items())):
            raise ValueError('invalid supervisor identity')
        started = read_receipt(directory, 'started', identity=identity)
        if not isinstance(started, dict) or started.get('pid') != expected['pid']:
            raise ValueError('unconfirmed supervisor start')
        # The command bytes are anchored by the signed receipt; intent alone
        # never supplies a trusted budget or executable identity.
        intent = json.loads((directory / 'intent.json').read_text(encoding='utf-8'))
        command = intent['command']
        if (not isinstance(command, list) or not command
                or Path(command[0]).resolve() != Path(config['executable']).resolve()
                or canonical_sha256(command) != started.get('argv_sha256')):
            raise ValueError('host executable mismatch')
        seconds, observed = started.get('budget_seconds'), started.get('observed_at')
        host_limit = 120
        if kind == 'houdini' and config.get('native_scope') is not None:
            from dcc_task_runtime.native_scope import NativeScope, GEOMETRY_RESOURCE_PROFILE
            from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as GEOMETRY_FEEDBACK_PROFILE
            native = NativeScope(config['native_scope'])
            if native.resource_profile in (GEOMETRY_RESOURCE_PROFILE, GEOMETRY_FEEDBACK_PROFILE):
                # 会话期限沿认证几何角色上限；单次子任务仍受下方120秒与停止预留限制。
                if ((config.get('resource_budget') or {}).get('native_scope') != native.binding
                        or (started.get('resource_budget') or {}).get('native_scope') != native.binding
                        or not directory.resolve().is_relative_to(native.root)):
                    raise ValueError('host scope binding mismatch')
                host_limit = native.role_seconds('houdini-host')
        if (type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= host_limit
                or type(observed) not in (int, float) or not math.isfinite(observed)):
            raise ValueError('signed host deadline missing')
        if read_receipt(directory, 'stopped', identity=identity) is not None:
            raise ValueError('host already stopped')
        now = time.time()
        if not math.isfinite(now) or now < observed:
            raise ValueError('invalid host clock')
        remaining = observed + seconds - now - HOST_STOP_RESERVE_SECONDS
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError('PRODUCTION_HOST_DEADLINE_UNVERIFIED') from exc
    if remaining <= 0:
        raise ValueError('PRODUCTION_HOST_PHASE_BUDGET_EXHAUSTED')
    return min(float(requested_seconds), 120.0, remaining)


def _scene_transition_path(control):
    return Path(control).resolve() / 'scene-transitions.json'


def _scene_transition_records(control):
    path = _scene_transition_path(control)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('PRODUCTION_SCENE_TRANSITION_STORE_INVALID') from exc
    if not isinstance(payload, dict) or payload.get('schema') != 'bridge.production.scene-transitions/1.0':
        raise ValueError('PRODUCTION_SCENE_TRANSITION_STORE_INVALID')
    records = payload.get('records')
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError('PRODUCTION_SCENE_TRANSITION_STORE_INVALID')
    return records


def _scene_transition_operation_store_path(control, task_id):
    key = hashlib.sha256(str(task_id).encode('utf-8')).hexdigest()[:16]
    # Task hosts receive HOUDINI_BRIDGE_STATE_DIR=<control>/houdini-instances;
    # the add-on's _state_dir() therefore persists its normal fx_operations
    # store below that installation state root, not beside production-hosts.
    return (Path(control).resolve() / 'houdini-instances' / 'fx_operations'
            / ('ops_' + key + '.json'))


def _scene_transition_operation_digest(record):
    body = {key: value for key, value in record.items()
            if key != 'operation_receipt_sha256'}
    return hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        .encode('utf-8')).hexdigest()


def _scene_transition_formal_record(control, record):
    operation_id = str(record.get('operation_id') or '')
    task_id = str(record.get('task_id') or '')
    if not operation_id or not task_id:
        return None
    path = _scene_transition_operation_store_path(control, task_id)
    try:
        from houdini_bridge.render_observation_budget import read_store_payload, validate_store
        from houdini_bridge.operation_store import resolve_record
        store = json.loads(read_store_payload(path))
        validate_store(store)
        formal = resolve_record(path, store, operation_id, family='scene_transitions')
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(formal, dict) or formal.get('task_id') != task_id:
        return None
    return formal


def _reconcile_scene_transition_records(control, client, *, task_id, expected_identity,
                                        actual_identity, task_root):
    """Reconcile a host-owned INTENT before accepting its live epoch edge.

    The controller-side scene-transitions file is only an attachment. The
    host's scene transition entry in the normal per-task operation store is
    the authority and is updated by the host under its durable operation lock.
    """
    path = _scene_transition_path(control)
    records = _scene_transition_records(control)
    changed = False
    for index, record in enumerate(records):
        if (record.get('status') != 'INTENT' or record.get('task_id') != task_id
                or not record.get('operation_id')
                or record.get('before_scene_epoch') != expected_identity.get('scene_epoch')):
            continue
        try:
            response = client.call('scene.reconcile_transition', {
                'task_id': task_id,
                'operation_id': str(record['operation_id']),
            })
        except Exception:
            continue
        formal = response.get('scene_transition') if isinstance(response, dict) else None
        if (not isinstance(formal, dict) or formal.get('state') != 'COMPLETED'
                or formal.get('task_id') != task_id
                or formal.get('operation_id') != record.get('operation_id')
                or formal.get('request_id') != record.get('request_id')
                or formal.get('request_sha256') != record.get('request_sha256')
                or formal.get('before_scene_epoch') != record.get('before_scene_epoch')
                or formal.get('after_scene_epoch') != actual_identity.get('scene_epoch')
                or formal.get('before_identity') != record.get('before_identity')
                or formal.get('after_identity') != actual_identity
                or formal.get('operation_receipt_sha256') != _scene_transition_operation_digest(formal)):
            continue
        snapshot = _scene_transition_snapshot_from_formal(
            control, record, formal, task_root=task_root)
        if snapshot is None:
            continue
        updated = dict(record)
        updated.update({
            'status': 'COMPLETED',
            'recovered_from_intent': True,
            'completed_at': 'controller-reconnect',
            'after_scene_epoch': formal.get('after_scene_epoch'),
            'after_identity': formal.get('after_identity'),
            'result': snapshot,
            'operation_store_cas': formal.get('store_cas'),
            'operation_receipt_sha256': formal.get('operation_receipt_sha256'),
            'formal_operation': formal,
        })
        records[index] = updated
        changed = True
    if changed:
        _atomic(path, {
            'schema': 'bridge.production.scene-transitions/1.0',
            'task_id': task_id, 'records': records,
        })
    return changed


def _scene_transition_snapshot(control, record, *, task_root, require_source=False):
    task_root = Path(task_root).expanduser().resolve()
    request = record.get('request') if isinstance(record.get('request'), dict) else {}
    raw_path = str(request.get('path') or '')
    digest = str(request.get('sha256') or '').lower()
    if not raw_path or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
        return None
    raw_source = Path(raw_path).expanduser()
    if raw_source.is_symlink():
        return None
    source = raw_source.resolve()
    if not source.is_relative_to(task_root):
        if not _rect_shape_readonly_source(control,record,source,digest,task_root):
            return None
    if require_source and not source.is_file():
        return None
    snapshot_root = Path(control).resolve() / 'scene-transition-snapshots' / str(task_id_for_snapshot(record))
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_root / (digest + '.hip')
    if snapshot.is_symlink():
        return None
    if not snapshot.is_file():
        if not require_source:
            return None
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            return None
        temporary = snapshot.with_name('.' + snapshot.name + '.tmp')
        temporary.write_bytes(source.read_bytes())
        os.chmod(temporary, 0o400)
        atomic_replace(temporary,snapshot,owned_root=Path(control).resolve())
    try:
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            return None
        if require_source and hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            return None
    except OSError:
        return None
    return {'path': str(source), 'sha256': digest, 'snapshot_path': str(snapshot),
            'snapshot_sha256': digest}


def _rect_shape_readonly_source(control, record, source, digest, task_root):
    """只为当前shape模型job读取授权FR中唯一源HIP，不放开外部目录。"""
    try:
        from dcc_task_runtime.native_scope import NativeScope
        from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE,object_record,read_record
        control=Path(control).resolve()
        config=json.loads((control/'run.json').read_text()).get('production_host') or {}
        native=NativeScope(config['native_scope'])
        from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as FEEDBACK_PROFILE
        if native.resource_profile==FEEDBACK_PROFILE:
            if native.root!=Path(task_root).resolve() or control.name!='control' or control.parent.name!='project' or control.parents[2]!=native.root/'jobs':
                return False
            from .geometry_feedback import verify_job
            job=json.loads((control.parents[1]/'job.json').read_text())
            if control!=Path(job.get('directory',''))/'project/control':
                return False
            details=verify_job(job,native)
            checkpoint=details.get('checkpoint')
            expected=checkpoint['hip'] if checkpoint is not None else details['parent']['files']['hip']
            request=record.get('request') or {}
            if (str(source)!=expected['path'] or digest!=expected['sha256']
                    or request.get('task_id',record.get('task_id'))!=native.scope['task_id']):
                return False
            from houdini_bridge.official_karma_observation import checked_bytes
            checked_bytes(expected)
            return True
        if native.resource_profile!=RESOURCE_PROFILE or native.root!=Path(task_root).resolve():return False
        if control.name!='control' or control.parent.name!='project' or control.parent.parent.parent!=native.root/'jobs':return False
        authority=object_record(native.scope['shape_authority']);expected=authority['sources']['saved_hip']
        job=json.loads((control.parent.parent/'job.json').read_text());prep=object_record(job['preparation'])
        if (job.get('schema')!='bridge.rectlight-shape-job/1' or job.get('operation_id')!=control.parent.parent.name
                or prep.get('scope')!=native.binding or prep.get('creative_task_id')!=authority['creative_task_id']):return False
        request=record.get('request') or {}
        if 'task_id' in request and 'task_id' in record and request['task_id']!=record['task_id']:return False
        if (str(source)!=expected['path'] or digest!=expected['sha256']
                or request.get('task_id',record.get('task_id'))!=authority['source_scene_task_id']):return False
        read_record(expected)
        return True
    except (OSError,ValueError,KeyError,TypeError):return False


def _scene_transition_snapshot_from_formal(control, record, formal, *, task_root):
    """Copy a verified host-owned transition snapshot into controller state."""
    task_root = Path(task_root).expanduser().resolve()
    request = record.get('request') if isinstance(record.get('request'), dict) else {}
    raw_path = str(request.get('path') or '')
    raw_source = Path(raw_path).expanduser()
    digest = str(request.get('sha256') or '').lower()
    if (not raw_path or raw_source.is_symlink() or len(digest) != 64
            or any(char not in '0123456789abcdef' for char in digest)):
        return None
    source = raw_source.resolve()
    if not source.is_relative_to(task_root):
        if not _rect_shape_readonly_source(control,record,source,digest,task_root):
            return None
    formal_result = formal.get('result')
    if (not isinstance(formal_result, dict)
            or formal_result.get('path') != str(source)
            or str(formal_result.get('sha256') or '').lower() != digest
            or str(formal_result.get('snapshot_sha256') or '').lower() != digest):
        return None
    raw_host_snapshot = Path(str(formal_result.get('snapshot_path') or '')).expanduser()
    if raw_host_snapshot.is_symlink() or not raw_host_snapshot.is_file():
        return None
    host_snapshot = raw_host_snapshot.resolve()
    host_snapshot_root = (Path(control).resolve() / 'houdini-instances'
                          / 'scene-transition-snapshots'
                          / str(task_id_for_snapshot(record))).resolve()
    if not host_snapshot.is_relative_to(host_snapshot_root):
        return None
    try:
        payload = host_snapshot.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(payload).hexdigest() != digest:
        return None
    controller_root = (Path(control).resolve() / 'scene-transition-snapshots'
                       / str(task_id_for_snapshot(record)))
    controller_root.mkdir(parents=True, exist_ok=True)
    snapshot = controller_root / (digest + '.hip')
    if snapshot.is_symlink():
        return None
    if snapshot.is_file():
        try:
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
                return None
        except OSError:
            return None
    else:
        temporary = snapshot.with_name('.' + snapshot.name + '.tmp')
        try:
            temporary.write_bytes(payload)
            os.chmod(temporary, 0o400)
            atomic_replace(temporary,snapshot,owned_root=controller_root)
        except OSError:
            try:
                remove_owned_path(temporary,owned_root=controller_root)
            except OSError:
                pass
            return None
    return {'path': str(source), 'sha256': digest, 'snapshot_path': str(snapshot),
            'snapshot_sha256': digest}


def task_id_for_snapshot(record):
    return ''.join(char if char.isalnum() or char in '._-' else '_' for char in str(record.get('task_id') or ''))[:120] or 'unbound'


def _scene_transition_record_is_valid(record, *, control, task_id, task_root, expected_identity, actual_identity):
    if (record.get('schema') != 'bridge.production.scene-transition/1.0'
            or record.get('status') != 'COMPLETED'
            or record.get('kind') != 'houdini'
            or record.get('task_id') != task_id
            or record.get('command') not in {'scene.open_hip', 'scene.reopen_task_hip', 'scene.reopen_owned_hip'}):
        return False
    before = record.get('before_identity')
    after = record.get('after_identity')
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if before.get('task_id') != task_id or after.get('task_id') != task_id:
        return False
    if before.get('scene_epoch') != record.get('before_scene_epoch') or after.get('scene_epoch') != record.get('after_scene_epoch'):
        return False
    if type(record.get('before_scene_epoch')) is not int or type(record.get('after_scene_epoch')) is not int:
        return False
    if record['after_scene_epoch'] <= record['before_scene_epoch']:
        return False
    identity_keys = ('task_id', 'session_id', 'launch_nonce', 'pid', 'process_generation', 'plugin_build', 'version')
    if any(before.get(key) != after.get(key) for key in identity_keys):
        return False
    if any(before.get(key) != expected_identity.get(key) for key in identity_keys):
        return False
    if any(after.get(key) != actual_identity.get(key) for key in identity_keys):
        return False
    result = record.get('result')
    if not isinstance(result, dict):
        return False
    snapshot = _scene_transition_snapshot(control, record, task_root=task_root, require_source=False)
    valid = (isinstance(snapshot, dict)
            and result.get('path') == snapshot['path']
            and str(result.get('sha256') or '').lower() == snapshot['sha256']
            and result.get('snapshot_path') == snapshot['snapshot_path']
            and result.get('snapshot_sha256') == snapshot['snapshot_sha256'])
    operation_id = str(record.get('operation_id') or '')
    if not valid or not operation_id:
        return valid
    formal = _scene_transition_formal_record(control, record)
    if (not isinstance(formal, dict) or formal.get('state') != 'COMPLETED'
            or formal.get('operation_id') != operation_id
            or formal.get('request_id') != record.get('request_id')
            or formal.get('request_sha256') != record.get('request_sha256')
            or formal.get('before_scene_epoch') != record.get('before_scene_epoch')
            or formal.get('after_scene_epoch') != record.get('after_scene_epoch')
            or record.get('operation_store_cas') != formal.get('store_cas')
            or record.get('operation_receipt_sha256') != formal.get('operation_receipt_sha256')
            or formal.get('operation_receipt_sha256') != _scene_transition_operation_digest(formal)):
        return False
    formal_result = formal.get('result')
    # The controller and host each keep an immutable copy under their own
    # private state root.  Their snapshot paths therefore differ, while the
    # loaded HIP content identity must be identical.
    if (not isinstance(formal_result, dict)
            or formal_result.get('path') != result.get('path')
            or formal_result.get('sha256') != result.get('sha256')
            or formal_result.get('snapshot_sha256') != result.get('snapshot_sha256')):
        return False
    return (formal.get('before_identity') == record.get('before_identity')
            and formal.get('after_identity') == record.get('after_identity'))


def _scene_epoch_transition_is_authorized(control, *, task_id, from_epoch, to_epoch,
                                          task_root, expected_identity, actual_identity):
    """Authorize a live epoch advance only through a completed controller load.

    A Houdini process can advance its scene epoch for an external load/clear
    without touching controller state.  Such a change is not a reconnect
    signal.  The only accepted edge is a durable completed scene operation
    whose exact task, process identity, HIP path and content hash match.
    """
    records = _scene_transition_records(control)
    current = int(from_epoch)
    visited = set()
    while current < int(to_epoch):
        candidates = []
        for index, record in enumerate(records):
            if index in visited or record.get('before_scene_epoch') != current:
                continue
            if not _scene_transition_record_is_valid(
                    record, control=control, task_id=task_id, task_root=task_root,
                    expected_identity=expected_identity, actual_identity=actual_identity):
                if (record.get('status') == 'INTENT'
                        and record.get('task_id') == task_id
                        and record.get('before_scene_epoch') == current
                        and int(to_epoch) == current + 1):
                    recovered = _recover_interrupted_scene_transition(
                        control, record, task_root=task_root,
                        actual_identity=actual_identity,
                    )
                    if recovered:
                        records = _scene_transition_records(control)
                        candidates.append((current + 1, index))
                continue
            after = record.get('after_scene_epoch')
            if type(after) is int and current < after <= int(to_epoch):
                candidates.append((after, index))
        if len(candidates) != 1:
            return False
        current, index = sorted(candidates)[0]
        visited.add(index)
    return current == int(to_epoch)


def _recover_interrupted_scene_transition(control, record, *, task_root, actual_identity):
    """Close an intent left by a controller crash only from the same HIP fact.

    The source must still have the exact requested digest.  The durable snapshot
    is then the fact used by future controller restarts, so later saves to the
    mutable source path cannot invalidate a completed load receipt.
    """
    # Production records are completed by the host against the same durable
    # operation store. A controller-only rewrite would create a second
    # authorization source, so only legacy/unit records without an operation
    # identity use this local fallback.
    if record.get('operation_id'):
        return False
    snapshot = _scene_transition_snapshot(control, record, task_root=task_root, require_source=True)
    if snapshot is None:
        return False
    before = record.get('before_scene_epoch')
    if type(before) is not int:
        return False
    recovered = dict(record)
    recovered.update({
        'status': 'COMPLETED',
        'recovered_from_intent': True,
        'completed_at': 'controller-reconnect',
        'after_scene_epoch': before + 1,
        'after_identity': dict(actual_identity),
        'result': snapshot,
    })
    records = _scene_transition_records(control)
    try:
        index = next(index for index, item in enumerate(records) if item is record)
    except StopIteration:
        # Records are reloaded from JSON, so identity is not shared; match the
        # unique intent by task, command, epoch and requested content instead.
        index = next((index for index, item in enumerate(records)
                      if item.get('status') == 'INTENT'
                      and item.get('task_id') == record.get('task_id')
                      and item.get('before_scene_epoch') == before
                      and item.get('request') == record.get('request')), -1)
    if index < 0:
        return False
    records[index] = recovered
    _atomic(_scene_transition_path(control), {
        'schema': 'bridge.production.scene-transitions/1.0',
        'task_id': str(record.get('task_id') or ''), 'records': records,
    })
    return True


def _stopped_prior(prior,kind,config,task_id):
    """A signed wait receipt for this exact old host is required to restart."""
    identity=prior.get('expected_identity')
    if (not isinstance(identity,dict) or identity.get('task_id')!=task_id
            or identity.get('plugin_build')!=config['plugin_build']
            or not isinstance(identity.get('pid'),int)
            or not isinstance(identity.get('launch_nonce'),str)):
        raise ValueError('PRODUCTION_OLD_HOST_IDENTITY_INVALID')
    work=Path(prior['work_dir']).resolve()
    if not work.is_relative_to(Path(config['task_root']).resolve()):
        raise ValueError('PRODUCTION_OLD_HOST_OUTSIDE_TASK')
    if kind=='nuke':
        expected=prior.get('supervisor_identity')
        supervisor=Path(prior.get('supervisor_dir','')).resolve()
        if (not isinstance(expected,dict) or expected.get('launch_nonce')!=identity['launch_nonce']
                or expected.get('process_generation')!=identity.get('process_generation')
                or supervisor!=work/'supervisor'):
            raise ValueError('PRODUCTION_OLD_HOST_IDENTITY_INVALID')
    else:
        expected={'task_id':task_id,'launch_nonce':identity['launch_nonce']}
        if 'writer_executable' in config:
            expected['writer_executable_sha256']=canonical_sha256(config['writer_executable'])
        supervisor=work/('supervisor-'+identity['launch_nonce'])
    observed=OwnedProcessHandle(supervisor,expected)
    if observed.pid!=identity['pid'] or observed.poll() is None or observed.receipt() is None:
        raise ValueError('PRODUCTION_OLD_HOST_STOP_UNKNOWN')
    return work


def _launch_h(config,work,task_id,control,scheduler,repo):
    from houdini_bridge import task_host as houdini_host
    ensure_private_directory(work)
    args=argparse.Namespace(task_id=task_id,work_dir=str(work),addon_root=str(repo/'plugins/houdini'),
        houdini_bin=config['executable'],version=config['version'],max_seconds=config['session_seconds'],
        ready_timeout=(config['session_seconds'] if (config.get('resource_budget') or {}).get('native_scope') is not None else 10),poll_seconds=.01,warmup=False,
        supervisor_executable=config['supervisor_executable'],resource_budget=config['resource_budget'],environment=_shared_env(config,control,scheduler),
        evidence_source=config['evidence_source'],allow_software_processes=config['evidence_source']=='software_test',
        project_color=config.get('project_color'))
    if 'writer_executable' in config:
        args.writer_executable=config['writer_executable']
    if 'software_launch_script' in config:
        args.software_launch_script=config['software_launch_script']
        args.software_launch_script_sha256=config['software_launch_script_sha256']
    with contextlib.redirect_stdout(io.StringIO()) as output:code=houdini_host.start(args)
    if code:raise RuntimeError('PRODUCTION_HOUDINI_START_FAILED:'+output.getvalue())


def _reclaim_mismatched_houdini(work, task_id, observed, *, persist_stopped, expected_stopped_identity=None):
    """Reclaim only this signed supervisor child, retaining its stop evidence."""
    from houdini_bridge import task_host as houdini_host
    if (observed.identity.get('task_id') != task_id
            or observed.directory.resolve() != work.resolve()/('supervisor-'+observed.identity['launch_nonce'])):
        raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
    try:
        with houdini_host._owner_lock(work):
            ready_path=work/'host.ready'
            ready=json.loads(ready_path.read_text(encoding='utf-8'))
            identity=ready.get('task_host_identity',{})
            if (identity.get('pid')!=observed.pid
                    or identity.get('launch_nonce')!=observed.identity['launch_nonce']):
                raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
            if expected_stopped_identity is not None:
                binding=json.loads((work/'supervisor-binding.json').read_text(encoding='utf-8'))
                if (identity!=expected_stopped_identity
                        or binding.get('identity')!=observed.identity
                        or Path(binding['directory']).is_symlink()
                        or Path(binding['directory']).resolve()!=observed.directory.resolve()):
                    raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
                observed=OwnedProcessHandle(binding['directory'],binding['identity'])
                if (observed.pid!=identity['pid'] or observed.poll() is None
                        or observed.receipt() is None):
                    raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
            # The in-process launcher owns the original handle and its parent
            # wait; a restarted controller uses the same signed supervisor facts.
            child=houdini_host._ACTIVE_CHILDREN.get(observed.pid)
            if (child is None or child.identity!=observed.identity
                    or child.directory.resolve()!=observed.directory.resolve()):
                child=observed
            if child.poll() is None:
                if expected_stopped_identity is not None:
                    raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
                houdini_host._reclaim_child(work/'host.stop',child)
            if child.poll() is None or child.receipt() is None:
                raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
            current=json.loads(ready_path.read_text(encoding='utf-8'))
            current_identity=current.get('task_host_identity',{})
            if (current_identity.get('pid')!=observed.pid
                    or current_identity.get('launch_nonce')!=observed.identity['launch_nonce']):
                raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED')
            # Keep readiness recoverable until the deployment record no longer
            # names this rejected host; the original signed stop remains intact.
            persist_stopped()
            remove_owned_path(ready_path,owned_root=work)
            if houdini_host._ACTIVE_CHILDREN.get(observed.pid) is child:
                houdini_host._ACTIVE_CHILDREN.pop(observed.pid,None)
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('PRODUCTION_HOST_IDENTITY_RECONCILE_REQUIRED') from exc


def _nuke_restart_candidate(config,task_id,old_work,generation):
    candidates=[]
    for path in Path(config['task_root']).glob('nuke-host-*'):
        if path.is_symlink() or not path.resolve().is_relative_to(Path(config['task_root']).resolve()):
            raise ValueError('PRODUCTION_RESTART_WORKDIR_INVALID')
        intent=path/'launch.json'
        if path.resolve()==old_work or not intent.is_file():continue
        raw=json.loads(intent.read_text(encoding='utf-8'))
        identity=raw.get('identity',{})
        if (identity.get('task_id')==task_id and identity.get('process_generation')==generation
                and identity.get('plugin_build')==config['plugin_build']):
            candidates.append(path)
    if len(candidates)>1:raise ValueError('PRODUCTION_MULTIPLE_HOSTS_RECONCILE_REQUIRED')
    return candidates[0] if candidates else None


def ensure_hosts(host_config,nuke_config,*,task_id,controller_root,repo_root,scheduler_root,allow_software_processes=False,application='pipeline',host_kinds=None):
    if host_kinds is not None and (not isinstance(host_kinds, (set, frozenset)) or not host_kinds or not host_kinds <= ({'nuke'} if application == 'nuke' else {'houdini', 'nuke'})):
        raise ValueError('PRODUCTION_HOST_SELECTION_INVALID')
    control=Path(controller_root).resolve()
    for raw in ((nuke_config,) if application == 'nuke' else (host_config, nuke_config)):
        if isinstance(raw, dict) and raw.get('native_scope') is not None:
            native_scope_budget(raw['native_scope'], raw.get('resource_budget'), raw.get('task_root'), control, scheduler_root)
    with _deployment_lock(control):
        return _ensure_hosts_locked(host_config,nuke_config,task_id=task_id,controller_root=control,
            repo_root=repo_root,scheduler_root=scheduler_root,allow_software_processes=allow_software_processes,application=application,host_kinds=host_kinds)


def _ensure_hosts_locked(host_config,nuke_config,*,task_id,controller_root,repo_root,scheduler_root,allow_software_processes,application='pipeline',host_kinds=None):
    from nuke_bridge import task_host as nuke_host
    from houdini_bridge import task_host as houdini_host
    control=Path(controller_root).resolve();repo=Path(repo_root).resolve();scheduler=Path(scheduler_root).resolve()
    configs=validate_deployments(host_config,nuke_config,controller_root=control,repo_root=repo,
                                allow_software_processes=allow_software_processes,application=application)
    for config in configs:
        if config.get('native_scope') is not None:
            native_scope_budget(config['native_scope'], config['resource_budget'], control, scheduler, config['task_root'])
    state_file=control/'production-hosts.json'
    fingerprint=hashlib.sha256(json.dumps(configs,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')).hexdigest()
    saved=json.loads(state_file.read_text(encoding='utf-8')) if state_file.is_file() else {'task_id':task_id,'config_sha256':fingerprint,'hosts':{}}
    if saved.get('task_id')!=task_id or saved.get('config_sha256')!=fingerprint:raise ValueError('PRODUCTION_DEPLOYMENT_CHANGED')
    restarts=saved.setdefault('restarts',{})
    result={}
    for config in configs:
        if host_kinds is not None and config['application'] not in host_kinds:
            continue
        kind=config['application'];prior=saved['hosts'].get(kind);work=control/(kind+'-task-host')
        if kind=='houdini':
            try:
                if prior:
                    work=Path(prior['work_dir']).resolve()
                    if restarts.get(kind):
                        old=_stopped_prior(prior,kind,config,task_id)
                        if restarts[kind].get('old_nonce')!=prior['expected_identity']['launch_nonce']:
                            raise ValueError('PRODUCTION_RESTART_INTENT_MISMATCH')
                        # A crash after launching must reconnect the new child,
                        # never launch a second child into the same work directory.
                        known=restarts[kind].get('known_supervisors')
                        if not isinstance(known,list) or any(not isinstance(name,str) for name in known):
                            raise ValueError('PRODUCTION_RESTART_INTENT_MISMATCH')
                        candidates=[p for p in work.glob('supervisor-*') if p.is_dir() and p.name not in known]
                        if candidates:
                            if len(candidates)!=1:raise ValueError('PRODUCTION_MULTIPLE_HOSTS_RECONCILE_REQUIRED')
                            binding=json.loads((work/'supervisor-binding.json').read_text(encoding='utf-8'))
                            candidate=candidates[0].resolve()
                            if Path(binding['directory']).resolve()!=candidate:
                                nonce=candidate.name.removeprefix('supervisor-')
                                recovered={'directory':str(candidate),'identity':{'task_id':task_id,'launch_nonce':nonce}}
                                if 'writer_executable' in config:
                                    recovered['identity']['writer_executable_sha256']=canonical_sha256(config['writer_executable'])
                                try:
                                    bound=_h_config(config,work,control,task_id=task_id,binding_override=recovered)
                                except _HoudiniDeploymentIdentityMismatch:
                                    raise
                                except (OSError,ValueError,KeyError):
                                    raise ValueError('PRODUCTION_RESTART_PENDING') from None
                                identity=bound['expected_identity']
                                if identity.get('task_id')!=task_id or identity.get('plugin_build')!=config['plugin_build']:
                                    raise ValueError('PRODUCTION_RESTART_IDENTITY_INVALID')
                                _atomic(work/'supervisor-binding.json',recovered)
                                binding=recovered
                            observed=OwnedProcessHandle(binding['directory'],binding['identity'])
                            if observed.poll() is not None:raise ValueError('PRODUCTION_RESTART_STOPPED_RECONCILE_REQUIRED')
                            bound=_h_config(config,work,control,task_id=task_id)
                        else:
                            _launch_h(config,work,task_id,control,scheduler,repo)
                            bound=_h_config(config,work,control,task_id=task_id)
                    else:
                        binding=json.loads((work/'supervisor-binding.json').read_text(encoding='utf-8'))
                        if binding['identity'].get('launch_nonce')!=prior['expected_identity']['launch_nonce']:
                            raise ValueError('PRODUCTION_UNRECORDED_HOST')
                        try:bound=_h_config(config,work,control,task_id=task_id)
                        except ValueError as exc:
                            if str(exc)!='PRODUCTION_HOST_STOPPED':raise
                            _stopped_prior(prior,kind,config,task_id)
                            restarts[kind]={'old_nonce':prior['expected_identity']['launch_nonce'],
                                            'known_supervisors':sorted(p.name for p in work.glob('supervisor-*') if p.is_dir())}
                            _atomic(state_file,saved)
                            _launch_h(config,work,task_id,control,scheduler,repo)
                            bound=_h_config(config,work,control,task_id=task_id)
                else:
                    if not (work/'host.ready').is_file():
                        _launch_h(config,work,task_id,control,scheduler,repo)
                    try:
                        bound=_h_config(config,work,control,task_id=task_id)
                    except _HoudiniHostStopped as stopped:
                        _reclaim_mismatched_houdini(work,task_id,stopped.observed,
                            persist_stopped=lambda:_atomic(state_file,saved),
                            expected_stopped_identity=stopped.ready_identity)
                        _launch_h(config,work,task_id,control,scheduler,repo)
                        bound=_h_config(config,work,control,task_id=task_id)
            except _HoudiniDeploymentIdentityMismatch as exc:
                def persist_rejected_stop():
                    prior_identity=(prior or {}).get('expected_identity',{})
                    if (prior_identity.get('pid')==exc.observed.pid
                            and prior_identity.get('launch_nonce')==exc.observed.identity['launch_nonce']):
                        saved['hosts'].pop(kind,None)
                        restarts.pop(kind,None)
                    elif restarts.get(kind):
                        restarts[kind]['known_supervisors']=sorted(p.name for p in work.glob('supervisor-*') if p.is_dir())
                    _atomic(state_file,saved)
                _reclaim_mismatched_houdini(work,task_id,exc.observed,persist_stopped=persist_rejected_stop)
                raise ValueError('PRODUCTION_HOST_DEPLOYMENT_IDENTITY_MISMATCH_STOP_CONFIRMED') from exc
        else:
            if prior:
                if restarts.get(kind):
                    old=_stopped_prior(prior,kind,config,task_id)
                    generation=restarts[kind].get('generation')
                    if (restarts[kind].get('old_nonce')!=prior['expected_identity']['launch_nonce']
                            or type(generation) is not int or generation!=prior['expected_identity']['process_generation']+1):
                        raise ValueError('PRODUCTION_RESTART_INTENT_MISMATCH')
                    candidate=_nuke_restart_candidate(config,task_id,old,generation)
                    if candidate:
                        receipt=nuke_host.reconnect(candidate)
                    else:
                        receipt=nuke_host.start(task_id=task_id,task_root=config['task_root'],nuke_executable=config['executable'],
                            addon_path=repo/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=config['supervisor_executable'],
                            version=config['version'],process_generation=generation,budget_seconds=config['session_seconds'],
                            snapshot=config.get('snapshot'),resource_budget=config['resource_budget'],project_color=config.get('project_color'),ledger_root=control/'artifact_ledger',
                            scheduler_root=scheduler,controller_root=control,software_api=config['evidence_source']=='software_test',software_api_dir=config.get('software_api_dir'),
                            input_artifact_source=config.get('input_artifact_source'))
                else:
                    try:receipt=nuke_host.reconnect(prior['work_dir'])
                    except RuntimeError as exc:
                        if str(exc)!='owned host is stopped':raise
                        _stopped_prior(prior,kind,config,task_id)
                        generation=prior['expected_identity']['process_generation']+1
                        restarts[kind]={'old_nonce':prior['expected_identity']['launch_nonce'],'generation':generation}
                        _atomic(state_file,saved)
                        receipt=nuke_host.start(task_id=task_id,task_root=config['task_root'],nuke_executable=config['executable'],
                            addon_path=repo/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=config['supervisor_executable'],
                            version=config['version'],process_generation=generation,budget_seconds=config['session_seconds'],
                            snapshot=config.get('snapshot'),resource_budget=config['resource_budget'],project_color=config.get('project_color'),ledger_root=control/'artifact_ledger',
                            scheduler_root=scheduler,controller_root=control,software_api=config['evidence_source']=='software_test',software_api_dir=config.get('software_api_dir'),
                            input_artifact_source=config.get('input_artifact_source'))
            else:
                # Reclaim a controller crash after native readiness, before
                # the combined deployment record was committed.
                candidates=[]
                for path in Path(config['task_root']).glob('nuke-host-*'):
                    intent=path/'launch.json'
                    if intent.is_file():
                        launch = json.loads(intent.read_text(encoding='utf-8'))
                        if launch.get('identity', {}).get('task_id') != task_id:
                            continue
                        # 显式产物续接只重连当前控制端、当前范围的进程，不能复用旧控制端宿主。
                        if (config.get('input_artifact_source') is not None or config.get('feedback_ledger_root') is not None) and (
                                launch.get('controller_root') != str(control)
                                or (launch.get('resource_budget') or {}).get('native_scope') != config.get('native_scope')):
                            continue
                        candidates.append(path)
                if len(candidates)>1:raise ValueError('PRODUCTION_MULTIPLE_HOSTS_RECONCILE_REQUIRED')
                if candidates:receipt=nuke_host.reconnect(candidates[0])
                else:
                    receipt=nuke_host.start(task_id=task_id,task_root=config['task_root'],nuke_executable=config['executable'],
                        addon_path=repo/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=config['supervisor_executable'],
                        version=config['version'],budget_seconds=config['session_seconds'],snapshot=config.get('snapshot'),
                        resource_budget=config['resource_budget'],project_color=config.get('project_color'),ledger_root=Path(config.get('feedback_ledger_root',control/'artifact_ledger')),scheduler_root=scheduler,controller_root=control,
                        software_api=config['evidence_source']=='software_test',software_api_dir=config.get('software_api_dir'),
                            input_artifact_source=config.get('input_artifact_source'))
            ledger_root = _nuke_input_ledger(config,receipt,control)
            bound={**config,**receipt,'evidence_source':config['evidence_source'],'transport':'tcp','host':'127.0.0.1','ledger_root':ledger_root,
                   'render_records_root':str(Path(config['task_root'])/'state'/'nuke_renders')}
        saved['hosts'][kind]=bound;restarts.pop(kind,None);_atomic(state_file,saved);result[kind]=bound
    return result.get('houdini'),result.get('nuke')


def _nuke_input_ledger(config,receipt,control):
    """独立核对生产控制端与实际共享账本，不能假定二者目录同址。"""
    ledger_root=str(config.get('feedback_ledger_root',control/'artifact_ledger'))
    if config.get('input_artifact_source') is None:
        return ledger_root
    from dcc_task_runtime.native_scope import NativeScope
    from nuke_bridge.task_host import _input_source_payload
    native=NativeScope(config['native_scope'])
    source=_input_source_payload(config['input_artifact_source'],native)
    producer_control=Path(str(receipt.get('producer_controller') or ''))
    actual_ledger=Path(str(receipt.get('ledger_root') or ''))
    expected=producer_control/'artifact_ledger'
    if source.get('schema') in ('bridge.geometry-nuke-source/1', 'bridge.geometry-nuke-source/2'):
        from nuke_bridge.task_host import _geometry_source_binding
        # Nuke保存宿主可有独立control；输入生产端及两轮共享账本仍精确绑定原来源。
        source_control, expected = _geometry_source_binding(source,native,native.scope['task_id'])
        if (receipt.get('producer_controller') != source['producer_control']
                or producer_control != source_control
                or receipt.get('ledger_root') != str(expected)
                or config.get('feedback_ledger_root') != str(expected)
                or config.get('task_root') != str(native.root)):
            raise ValueError('PRODUCTION_INPUT_LEDGER_BINDING_MISMATCH')
    if source.get('schema')=='bridge.disklight-feedback-nuke-source/1':
        from houdini_bridge.official_karma_observation import checked_bytes
        phase=native.scope.get('feedback_phase') or {}
        if native.scope.get('recovery_phase') is not None:
            recovery=native.scope['recovery_phase']
            if json.loads(checked_bytes(recovery['input_source'])) != source:
                raise ValueError('PRODUCTION_RECOVERY_INPUT_SOURCE_MISMATCH')
            binding=source['producer_scope']
            phase=NativeScope({k:binding[k] for k in ('path','sha256')}).scope.get('feedback_phase') or {}
        if (source.get('task_id')!=phase.get('task_id')
                or source.get('feedback_delivery')!=phase.get('source_delivery')
                or source.get('producer_control')!=str(producer_control)):
            raise ValueError('PRODUCTION_INPUT_LEDGER_BINDING_MISMATCH')
        delivery=json.loads(checked_bytes(source['feedback_delivery']))
        expected=Path(delivery['artifact_ledger'])
        if source.get('producer_ledger')!=str(expected):
            raise ValueError('PRODUCTION_INPUT_LEDGER_BINDING_MISMATCH')
    if (not producer_control.is_absolute() or not actual_ledger.is_absolute()
            or actual_ledger!=expected or not actual_ledger.is_dir()
            or not (actual_ledger/'artifacts.sqlite3').is_file()
            or (actual_ledger/'artifacts.sqlite3').is_symlink()
            or any(item.is_symlink() for item in (actual_ledger,*actual_ledger.parents))
            or not actual_ledger.resolve().is_relative_to(Path(config['task_root']).resolve())):
        raise ValueError('PRODUCTION_INPUT_LEDGER_BINDING_MISMATCH')
    return str(actual_ledger)


def stop_hosts(controller_root):
    from nuke_bridge import task_host as nuke_host
    from houdini_bridge import task_host as houdini_host
    control=Path(controller_root).resolve()
    with _deployment_lock(control):
        path=control/'production-hosts.json';saved=json.loads(path.read_text(encoding='utf-8'));results={}
        if saved.get('restarts'):
            raise ValueError('PRODUCTION_RESTART_PENDING_RECONCILE_REQUIRED')
        for kind,config in saved['hosts'].items():
            if kind=='nuke':results[kind]=nuke_host.stop(config['work_dir'])
            else:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code=houdini_host.stop(argparse.Namespace(work_dir=config['work_dir'],timeout=3,exit_grace=3))
                results[kind]={'returncode':code,'receipt':json.loads(output.getvalue())}
        return results
