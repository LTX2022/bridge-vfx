#!/usr/bin/env python3
"""Preflight a frozen alpha calibration; execution requires both approved hashes.

ScopeBudget is a read-only view of the shared NativeScope. Actual launches use
 owned_process admission and supervisor completion; no second accounting ledger
 or manual admission/finish is maintained by this tool.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import shlex
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from dcc_task_runtime import alpha_calibration, owned_process, process_image
from dcc_task_runtime.project_color import validate_project_color
from houdini_bridge.controlled_output import controlled_route_sha256, validate_controlled_policy

FORMAL_ROUTE_MINIMUM_DCC_STARTS = 8
ROLE_HOSTS = {'alpha-husk': 'husk', 'alpha-nuke': 'nuke', 'houdini-host': 'hython',
              'nuke-host': 'nuke', 'graph-worker': 'hython', 'main-husk': 'husk', 'nuke-render': 'nuke'}
ROLE_QUOTAS = {'alpha-husk': 1, 'alpha-nuke': 1, 'houdini-host': 2, 'nuke-host': 1,
               'graph-worker': 1, 'main-husk': 1, 'nuke-render': 1}

LIMITS = {'per_operation_seconds': 120, 'total_seconds': 600, 'max_dcc_starts': 8,
          'max_disk_bytes': 512 * 1024 * 1024, 'max_heavy_operations': 1, 'automatic_retries': 0}


def _profile(scope):
    from dcc_task_runtime.native_scope import OFFICIAL_SCOPE_SCHEMA
    from dcc_task_runtime.render_profiles import LEGACY, OFFICIAL
    if scope.get('schema') == OFFICIAL_SCOPE_SCHEMA:
        if scope.get('scene_profile') != OFFICIAL:
            raise ValueError('ALPHA_RUNNER_PROFILE_MISMATCH')
        return OFFICIAL
    if scope.get('scene_profile', LEGACY) != LEGACY:
        raise ValueError('ALPHA_RUNNER_PROFILE_MISMATCH')
    return LEGACY


def _limits(scope):
    from dcc_task_runtime.native_scope import OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET
    if scope.get('execution_mode') in (OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE):
        _profile(scope)
        return dict(OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET)
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_SURVEY_BUDGET
    if scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE:
        _profile(scope)
        return dict(OFFICIAL_IDENTITY_SURVEY_BUDGET)
    from dcc_task_runtime.native_scope import OFFICIAL_BUDGET,OFFICIAL_DIAGNOSTIC_MODES,OFFICIAL_DIAGNOSTIC_BUDGET
    if scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES:
        _profile(scope)
        return dict(OFFICIAL_DIAGNOSTIC_BUDGET)
    from dcc_task_runtime.render_profiles import OFFICIAL
    return dict(OFFICIAL_BUDGET if _profile(scope) == OFFICIAL else LIMITS)


def _roles(scope):
    from dcc_task_runtime.render_profiles import OFFICIAL
    roles, hosts = dict(ROLE_QUOTAS), dict(ROLE_HOSTS)
    if _profile(scope) == OFFICIAL:
        roles.update({'official-open-save': 1, 'official-cold-export': 1, 'official-husk': 1})
        hosts.update({'official-open-save': 'hython', 'official-cold-export': 'hython', 'official-husk': 'husk'})
    return roles, hosts


def plain(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ALPHA_RUNNER_PLAIN_ABSOLUTE_PATH_REQUIRED')
    return path


def file_record(path, limit=512 * 1024 * 1024):
    path = plain(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('ALPHA_RUNNER_FILE_SIZE_INVALID')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(block)
            if size > limit: raise ValueError('ALPHA_RUNNER_FILE_SIZE_INVALID')
            digest.update(block)
        after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if size != before.st_size or any(getattr(before, key) != getattr(after, key) or
                                   getattr(before, key) != getattr(path.stat(), key) for key in keys):
        raise ValueError('ALPHA_RUNNER_FILE_CHANGED')
    return {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()}


def checked(record, limit=512 * 1024 * 1024):
    if not isinstance(record, dict) or file_record(record['path'], limit) != record:
        raise ValueError('ALPHA_RUNNER_FROZEN_FILE_CHANGED')
    return Path(record['path'])


def load(path):
    return json.loads(plain(path).read_text(encoding='utf-8'))


def _software_boundaries(scope, bindings, *, required=False):
    boundary = scope.get('software_native_boundaries')
    if boundary is None:
        if required: raise ValueError('ALPHA_RUNNER_SOFTWARE_BOUNDARY_REQUIRED')
        return None
    if (scope.get('evidence_source') != 'software_test' or bindings.get('evidence_source') != 'software_test'
            or not isinstance(boundary, dict)
            or set(boundary) != {'houdini_launch_script', 'nuke_api', 'alpha_husk_script'}):
        raise ValueError('ALPHA_RUNNER_SOFTWARE_BOUNDARY_FORBIDDEN')
    return {key: checked(value, 2 * 1024 * 1024) for key, value in boundary.items()}


class ScopeBudget:
    """Read-only tool view of the same NativeScope used by every native launch."""
    def __init__(self, scope_path, bindings_path=None):
        from dcc_task_runtime.native_scope import NativeScope
        self.scope_path = plain(scope_path)
        self.scope_sha256 = file_record(self.scope_path, 2 * 1024 * 1024)['sha256']
        self.binding = {'path': str(self.scope_path), 'sha256': self.scope_sha256}
        self.native = NativeScope(self.binding)
        self.scope, self.root = self.native.scope, self.native.root
        self.path = self.native.state_path
        from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
        if self.native.resource_profile == RECT_SHAPE_PROFILE:
            # 仅作已认证新任务的预算只读视图；不开放alpha角色或改变旧profile门。
            from dcc_task_runtime.rectlight_shape_scope import object_record
            authority = object_record(self.scope['shape_authority'])
            self.limits = dict(self.scope['budget'])
            roots = [str(self.root.parent), str(Path(authority['plan']['path']).parent)]
        else:
            self.limits = _limits(self.scope)
            roots = [str(self.root)]
        self.resource_budget = {'roots': roots, 'max_bytes': self.limits['max_disk_bytes'],
                                'native_scope': self.binding}

    def snapshot(self):
        return self.native.snapshot()

    def remaining(self, state=None):
        state = state or self.snapshot()
        return max(0., self.limits['total_seconds'] - state['total_seconds'])

    def available(self, starts=1):
        state = self.snapshot()
        if state['closed_reason']: raise ValueError(state['closed_reason'])
        if any(ticket['heavy'] and ticket.get('stopped_at') is None for ticket in state['tickets']):
            raise ValueError('NATIVE_SCOPE_HEAVY_BUSY')
        if state['dcc_starts'] + starts > self.limits['max_dcc_starts']:
            raise ValueError('NATIVE_SCOPE_STARTS_EXHAUSTED')
        if self.remaining(state) <= 0: raise ValueError('NATIVE_SCOPE_TIME_EXHAUSTED')
        if owned_process._disk_usage(self.resource_budget) >= self.limits['max_disk_bytes']:
            raise ValueError('NATIVE_SCOPE_DISK_EXHAUSTED')
        return state

    def fail(self, reason):
        return self.native.fail(str(reason)[:512])


def required_source_paths():
    relative = (
        'tools/run_alpha_calibration.py', 'tools/prepare_native_alpha_scene.py', 'tools/activate_controlled_engineering.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/render_profiles.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py',
        'packages/dcc-task-runtime/src/dcc_task_runtime/native_scope.py',
        'packages/houdini-bridge/src/houdini_bridge/controlled_output.py',
        'packages/vfx-pipeline/src/vfx_pipeline/production_hosts.py',
        'packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py',
        'packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py',
        'packages/houdini-bridge/src/houdini_bridge/task_host.py',
        'packages/nuke-bridge/src/nuke_bridge/task_host.py',
        'packages/nuke-bridge/src/nuke_bridge/task_host_worker.py',
        'plugins/houdini/_impl/houdini_bridge_addon.py', 'plugins/nuke/nuke_bridge_addon.py')
    return [ROOT / path for path in relative]


def validate_inventory(inventory, scope):
    from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODES,OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_ROLES
    if scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE:
        expected=[{'start_id':role,'operation_id':role,'host':'hython','parent_start_id':None,'role':role,'heavy':True} for role in OFFICIAL_IDENTITY_ROLES]
        if inventory!=expected or scope.get('operations')!=[{'id':role} for role in OFFICIAL_IDENTITY_ROLES]:raise ValueError('OFFICIAL_IDENTITY_SURVEY_INVENTORY_INVALID')
        return inventory
    if scope.get('execution_mode') in OFFICIAL_DIAGNOSTIC_MODES:
        expected=[{'start_id':'official-open-save','operation_id':'official-open-save','host':'hython',
            'parent_start_id':None,'role':'official-open-save','heavy':True}]
        if inventory!=expected or scope.get('operations')!=[{'id':'official-open-save'}]:
            raise ValueError('OFFICIAL_DIAGNOSTIC_INVENTORY_INVALID')
        return inventory
    roles, hosts = _roles(scope)
    keys = {'start_id', 'operation_id', 'host', 'parent_start_id', 'role', 'heavy'}
    if (not isinstance(inventory, list) or len(inventory) != _limits(scope)['max_dcc_starts']
            or any(not isinstance(item, dict) or set(item) != keys for item in inventory)):
        raise ValueError('ALPHA_RUNNER_NATIVE_START_COUNT_REQUIRED')
    seen, operations = {}, {operation['id'] for operation in scope['operations']}
    for item in inventory:
        role = item['role']
        if (not isinstance(item['start_id'], str) or not item['start_id'] or item['start_id'] in seen
                or role not in roles or item['host'] != hosts[role]
                or type(item['heavy']) is not bool or item['heavy'] != (role not in ('houdini-host', 'nuke-host'))
                or item['operation_id'] not in operations):
            raise ValueError('ALPHA_RUNNER_NATIVE_START_INVENTORY_INVALID')
        seen[item['start_id']] = item
    if Counter(item['role'] for item in inventory) != Counter(roles):
        raise ValueError('ALPHA_RUNNER_NATIVE_ROLE_QUOTA_MISMATCH')
    if {item['start_id'] for item in inventory if item['role'] == 'houdini-host'} != {'houdini-initial', 'houdini-reopen'}:
        raise ValueError('ALPHA_RUNNER_HOUDINI_HOST_IDENTITIES_REQUIRED')
    for item in inventory:
        if item['role'] == 'main-husk':
            if item['parent_start_id'] != 'houdini-reopen':
                raise ValueError('ALPHA_RUNNER_MAIN_HUSK_REOPEN_PARENT_REQUIRED')
        elif item['parent_start_id'] is not None:
            raise ValueError('ALPHA_RUNNER_UNEXPECTED_NATIVE_PARENT')
    if {item['operation_id'] for item in inventory} != operations:
        raise ValueError('ALPHA_RUNNER_COMPLETE_NATIVE_START_INVENTORY_REQUIRED')
    return inventory


def preflight(scope_path, bindings_path=None, *, allow_completed=False):
    blockers, data = [], {}
    try:
        budget = ScopeBudget(scope_path)
        scope = budget.scope
        if scope.get('execution_mode') is not None:
            raise ValueError('ALPHA_RUNNER_DIAGNOSTIC_ONLY_NOT_AUTHORIZED')
        color = validate_project_color(scope.get('project_color'))
        if color['colorspace'] != 'ACEScg' or scope.get('versions') != {'houdini': '21.0.631', 'nuke': '17.0v1'}:
            raise ValueError('ALPHA_RUNNER_FROZEN_VERSION_COLOR_REQUIRED')
        budget.available(starts=0 if allow_completed else 2)
        data.update(scope=scope, scope_sha256=budget.scope_sha256)
        if bindings_path is None: raise ValueError('ALPHA_RUNNER_RUNTIME_BINDINGS_REQUIRED')
        bindings = load(bindings_path)
        if (bindings.get('schema') != 'bridge.engineering-closure.runtime-bindings/1'
                or bindings.get('scope_sha256') != budget.scope_sha256):
            raise ValueError('ALPHA_RUNNER_RUNTIME_BINDINGS_INVALID')
        data.update(bindings=bindings, bindings_sha256=file_record(bindings_path, 2 * 1024 * 1024)['sha256'])
        validate_inventory(bindings.get('native_start_inventory'), scope)
        sources = bindings.get('source_freeze')
        required = required_source_paths()
        if not isinstance(sources, dict) or any(str(path) not in sources for path in required):
            raise ValueError('ALPHA_RUNNER_FINAL_SOURCE_FREEZE_REQUIRED')
        for path, digest in sources.items():
            if file_record(path)['sha256'] != digest: raise ValueError('ALPHA_RUNNER_FROZEN_SOURCE_CHANGED')
        if bindings.get('plugin_build') != sources[str(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')]:
            raise ValueError('ALPHA_RUNNER_PLUGIN_BUILD_MISMATCH')
        data['source_admission_status'] = 'SOURCE_BOUND'
        preparation = load(checked(bindings['alpha_preparation'], 2 * 1024 * 1024))
        if (preparation.get('schema') != 'bridge.alpha-chart.preparation/1.0'
                or preparation.get('houdini_version') != '21.0.631'
                or preparation.get('native_execution_status') != 'NOT_RUN'):
            raise ValueError('ALPHA_RUNNER_ALPHA_PREPARATION_INVALID')
        checked(preparation['generator'], 2 * 1024 * 1024)
        for record in preparation['primary_sources'].values(): checked(record, 8 * 1024 * 1024)
        scene = checked(preparation['scene'], 2 * 1024 * 1024)
        chart = plain(preparation['chart_path'])
        observer_root = plain(bindings['nuke_output_root'])
        if (not all(path.is_relative_to(budget.root) for path in (scene, chart, observer_root))
                or (not allow_completed and (chart.exists() or observer_root.exists()))):
            raise ValueError('ALPHA_RUNNER_FRESH_SCOPED_OUTPUT_REQUIRED')
        route = preparation['route']
        if (controlled_route_sha256(route) != preparation['route_sha256']
                or preparation['route_sha256'] != bindings.get('route_sha256')
                or route.get('colorspace') != color['colorspace'] or route.get('renderer') != 'BRAY_HdKarma'
                or route.get('aov_semantics') != 'karma_beauty_lpe_v1'):
            raise ValueError('ALPHA_RUNNER_ROUTE_MISMATCH')
        from dcc_task_runtime.render_profiles import LEGACY, definition, output_policy
        profile = _profile(scope)
        fixture = definition(profile)
        if (preparation.get('scene_profile', LEGACY) != profile
                or (profile != LEGACY and preparation.get('resolution') != fixture['resolution'])
                or (profile != LEGACY and preparation.get('sample_pixels') != fixture['sample_pixels'])
                or route.get('resolution') != fixture['resolution']
                or bindings.get('output_acceptance') != output_policy(profile)):
            raise ValueError('ALPHA_RUNNER_PROFILE_MISMATCH')
        validate_controlled_policy(bindings.get('output_acceptance'))
        ready_adapter = ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'
        if (preparation.get('runtime_ready_adapter') != file_record(ready_adapter)
                or str(ready_adapter) not in sources
                or sources[str(ready_adapter)] != file_record(ready_adapter)['sha256']):
            raise ValueError('ALPHA_RUNNER_RUNTIME_READY_ADAPTER_MISMATCH')
        expected_command = [scope['hosts']['husk']['path'], '--prerender-script', shlex.quote(str(ready_adapter)),
            '--renderer', 'BRAY_HdKarma', '--settings', '/Render/Settings',
            '--frame', '1', '--frame-count', '1', '--output', str(chart), str(scene)]
        software_boundary = _software_boundaries(scope, bindings)
        if software_boundary is not None: expected_command.insert(1, str(software_boundary['alpha_husk_script']))
        if preparation.get('command') != expected_command or preparation['husk'] != scope['hosts']['husk']:
            raise ValueError('ALPHA_RUNNER_COMMAND_MISMATCH')
        for host in ('hython', 'husk', 'nuke', 'supervisor_python'): checked(scope['hosts'][host])
        if not isinstance(bindings.get('main_writer_plan'), dict):
            raise ValueError('ALPHA_RUNNER_MAIN_WRITER_PLAN_REQUIRED')
        writer = load(checked(bindings['main_writer_plan'], 2 * 1024 * 1024))
        if (writer.get('schema') != 'bridge.controlled-output.main-writer-plan/1.0' or writer.get('state') != 'PREPARED'
                or writer.get('output_acceptance') != bindings['output_acceptance']
                or writer.get('project_color') != color or writer.get('route_sha256') != bindings['route_sha256']
                or writer.get('plugin_build') != bindings['plugin_build'] or not writer.get('command')):
            raise ValueError('ALPHA_RUNNER_MAIN_WRITER_PLAN_REQUIRED')
        command = writer['command']
        driver_index = 1
        options = set()
        while isinstance(command, list) and len(command) > driver_index and command[driver_index] in ('-I', '-B'):
            if command[driver_index] in options:
                raise ValueError('ALPHA_RUNNER_MAIN_WRITER_PLAN_REQUIRED')
            options.add(command[driver_index]);driver_index += 1
        if (not isinstance(command, list) or len(command) <= driver_index or any(type(arg) is not str or not arg for arg in command)
                or command[0] != scope['hosts']['supervisor_python']['path']
                or command[driver_index] not in sources or file_record(command[driver_index])['sha256'] != sources[command[driver_index]]):
            raise ValueError('ALPHA_RUNNER_MAIN_WRITER_PLAN_REQUIRED')
        deployment_records = bindings.get('deployments')
        if not isinstance(deployment_records, dict) or set(deployment_records) != {'houdini', 'nuke'}:
            raise ValueError('ALPHA_RUNNER_DEPLOYMENTS_REQUIRED')
        deployments = {kind: load(checked(record, 2 * 1024 * 1024)) for kind, record in deployment_records.items()}
        evidence = bindings.get('evidence_source')
        if evidence not in ('software_test', 'real_host') or any(value.get('evidence_source') != evidence for value in deployments.values()):
            raise ValueError('ALPHA_RUNNER_DEPLOYMENT_EVIDENCE_SOURCE_MISMATCH')
        controller = plain(bindings['controller_root'])
        if not controller.is_relative_to(budget.root):
            raise ValueError('ALPHA_RUNNER_CONTROLLER_OUTSIDE_SCOPE')
        if any(value.get('native_scope') != budget.binding for value in deployments.values()):
            raise ValueError('ALPHA_RUNNER_DEPLOYMENT_NATIVE_SCOPE_REQUIRED')
        from vfx_pipeline.production_hosts import validate_deployments
        validate_deployments(deployments['houdini'], deployments['nuke'], controller_root=controller,
            repo_root=ROOT, allow_software_processes=evidence == 'software_test')
        data['deployments'] = deployments
        environment = bindings.get('environment')
        if not isinstance(environment, dict) or not environment or any(type(k) is not str or type(v) is not str for k, v in environment.items()):
            raise ValueError('ALPHA_RUNNER_FROZEN_ENVIRONMENT_REQUIRED')
        ocio = scope['native_color_tokens']['houdini_static_config']
        checked({k: ocio[k] for k in ('path', 'bytes', 'sha256')})
        if environment.get('OCIO') != ocio['path']:
            raise ValueError('ALPHA_RUNNER_FROZEN_OCIO_ENVIRONMENT_REQUIRED')
        data.update(preparation=preparation, observer_root=str(observer_root))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        blockers.append(str(error))
    return {'schema': 'bridge.alpha-runner.preflight/1', 'state': 'BLOCKED' if blockers else 'PREPARED',
        'native_execution_status': 'NOT_RUN', 'blockers': blockers,
        'scope_sha256': data.get('scope_sha256'), 'bindings_sha256': data.get('bindings_sha256'),
        'formal_route_minimum_dcc_starts': _limits(data['scope'])['max_dcc_starts'] if 'scope' in data else FORMAL_ROUTE_MINIMUM_DCC_STARTS,
        'shared_scope_admission_status': data.get('source_admission_status', 'UNVERIFIED')}, data


def _decoded(record, scene_profile="sphere_ground_v2"):
    from houdini_bridge.controlled_output import _decode_snapshot
    path = checked(record)
    snapshot = dict(record, modified_ns=path.stat().st_mtime_ns)
    from dcc_task_runtime.render_profiles import definition
    resolution = definition(scene_profile)['resolution']
    image = _decode_snapshot(snapshot, resolution=resolution, channels=list('RGBA'))
    window = [0, 0, resolution[0] - 1, resolution[1] - 1]
    if (image['channel_layout']['data_window'] != window
            or image['channel_layout']['display_window'] != window):
        raise ValueError('ALPHA_RUNNER_IMAGE_INVALID')
    checked(record)
    return image


def _seal(directory, identity, payload):
    event = payload['event']
    if owned_process.read_receipt(directory, event, identity=identity) is not None:
        raise ValueError('ALPHA_RUNNER_ORIGINAL_EVENT_ALREADY_EXISTS')
    owned_process._signed_write(Path(directory), payload)
    if owned_process.read_receipt(directory, event, identity=identity) != payload:
        raise ValueError('ALPHA_RUNNER_ORIGINAL_EVENT_MISMATCH')
    return payload


class AlphaRunnerBusy(ValueError):
    """Another entry is advancing this same calibration; do not close its scope."""


def _activation_module():
    spec = importlib.util.spec_from_file_location('alpha_trusted_activation', ROOT / 'tools/activate_controlled_engineering.py')
    activation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(activation)
    return activation


def _activation_gate(scope_path, bindings_path, scope_sha256):
    from dcc_task_runtime.native_scope import NativeScope
    native = NativeScope({'path': str(plain(scope_path)), 'sha256': scope_sha256})
    receipt = _activation_module().validate_activation(native, bindings_path)
    if receipt.get('authorization') not in ('explicit_local_terminal_controller','explicit_agent_controller'):
        raise ValueError('ALPHA_RUNNER_EXPLICIT_LOCAL_ACTIVATION_REQUIRED')


def _completed_original(scope_path, bindings_path):
    scope = load(scope_path)
    path = plain(scope['output_root']) / 'alpha-calibration-result.json'
    if not path.exists(): return None
    result, bindings = load(path), load(bindings_path)
    if (result.get('schema') != 'bridge.alpha-runner.result/1'
            or result.get('scope_sha256') != file_record(scope_path)['sha256']
            or result.get('bindings_sha256') != file_record(bindings_path)['sha256']):
        raise ValueError('ALPHA_RUNNER_ORIGINAL_RESULT_BINDING_MISMATCH')
    calibration = alpha_calibration.validate_alpha_calibration(result['alpha_calibration'],
        expected_version='21.0.631', expected_plugin_build=bindings['plugin_build'],
        expected_route_sha256=bindings['route_sha256'], evidence_source=bindings.get('evidence_source'))
    if result.get('calibration') != calibration:
        raise ValueError('ALPHA_RUNNER_ORIGINAL_RESULT_CHANGED')
    return result


def _execution_preflight(scope_path, bindings_path):
    completed = _completed_original(scope_path, bindings_path)
    report, data = preflight(scope_path, bindings_path, allow_completed=completed is not None)
    return report, data, completed


def _execution_gate(scope_path, bindings_path, report, data, approved_scope_sha256, approved_bindings_sha256):
    if report['blockers']:
        if all(value == 'NATIVE_SCOPE_HEAVY_BUSY' for value in report['blockers']):
            raise AlphaRunnerBusy('ALPHA_RUNNER_BUSY')
        raise ValueError(';'.join(report['blockers']))
    if (approved_scope_sha256 != report['scope_sha256'] or approved_bindings_sha256 != report['bindings_sha256']):
        raise ValueError('ALPHA_RUNNER_EXPLICIT_FROZEN_APPROVAL_REQUIRED')
    if (data['scope'].get('execution_authorized') is not True
            or data['scope'].get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('ALPHA_RUNNER_LIVE_AUTHORIZATION_REQUIRED')
    if data['scope'].get('evidence_source') != 'real_host' or data['bindings'].get('evidence_source') != 'real_host':
        raise ValueError('ALPHA_RUNNER_NATIVE_EXECUTION_REQUIRES_REAL_HOST_BINDINGS')
    _activation_gate(scope_path, bindings_path, report['scope_sha256'])


def execute(scope_path, bindings_path, *, approved_scope_sha256, approved_bindings_sha256):
    report, data, _ = _execution_preflight(scope_path, bindings_path)
    _execution_gate(scope_path, bindings_path, report, data, approved_scope_sha256, approved_bindings_sha256)
    from contextlib import ExitStack
    from dcc_task_runtime.execution_lock import execution_lock
    from dcc_task_runtime.errors import RuntimeV2Error
    from dcc_task_runtime.models import ErrorCode
    with ExitStack() as stack:
        try:
            stack.enter_context(execution_lock(plain(data['scope']['output_root']) / 'engineering-driver-state.json',
                'controlled-engineering'))
        except RuntimeV2Error as error:
            if error.code == ErrorCode.INVALID_TRANSITION:
                raise AlphaRunnerBusy('ALPHA_RUNNER_BUSY') from error
            raise
        current, data, completed = _execution_preflight(scope_path, bindings_path)
        if (current.get('scope_sha256') != report['scope_sha256']
                or current.get('bindings_sha256') != report['bindings_sha256']):
            raise ValueError('ALPHA_RUNNER_FROZEN_INPUTS_CHANGED')
        _execution_gate(scope_path, bindings_path, current, data, approved_scope_sha256, approved_bindings_sha256)
        if completed is not None:return completed
        budget = ScopeBudget(scope_path, bindings_path)
        if budget.scope_sha256 != current['scope_sha256']:
            raise ValueError('ALPHA_RUNNER_FROZEN_SCOPE_CHANGED')
        try:
            return _execute_approved(data, current, budget)
        except BaseException as error:
            budget.fail(type(error).__name__ + ':' + str(error))
            raise


def _execute_approved(data, report, budget):
    scope, bindings, prep = data['scope'], data['bindings'], data['preparation']
    evidence_source = scope.get('evidence_source')
    if evidence_source not in ('real_host', 'software_test') or bindings.get('evidence_source') != evidence_source:
        raise ValueError('ALPHA_RUNNER_EVIDENCE_SOURCE_MISMATCH')
    software_boundary = _software_boundaries(scope, bindings, required=evidence_source == 'software_test')
    nuke_command = [scope['hosts']['nuke']['path']] + ([] if software_boundary is not None else ['-t']) + [
        str(Path(alpha_calibration.__file__).resolve()), '--observe-native', '--chart', prep['chart_path'],
        '--output-root', data['observer_root'], '--project-colorspace', 'ACEScg']
    from dcc_task_runtime.render_profiles import LEGACY
    profile = _profile(scope)
    if profile != LEGACY:
        nuke_command.extend(['--scene-profile', profile])
    environment = dict(bindings['environment'])
    if software_boundary is not None:
        environment.update(PYTHONPATH=os.pathsep.join([str(software_boundary['nuke_api'].parent)] +
            [str(ROOT / 'packages' / package / 'src') for package in
             ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')]),
            PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    native_operations = {}
    outputs = {}
    for role, command, host, version in (
            ('houdini', prep['command'], 'husk', '21.0.631'),
            ('nuke', nuke_command, 'nuke', '17.0v1')):
        operation_id = 'alpha-h21' if role == 'houdini' else 'alpha-nuke'
        directory = budget.root / ('supervisor-' + operation_id)
        identity = {'task_id': scope['scope_id'], 'operation_id': operation_id, 'launch_nonce': uuid4().hex}
        for path, digest in bindings['source_freeze'].items():
            if file_record(path)['sha256'] != digest: raise ValueError('ALPHA_RUNNER_FROZEN_SOURCE_CHANGED')
        if role == 'nuke':
            checked(outputs['houdini']['chart'])
            checked(outputs['houdini']['scene'])
        expected = process_image.freeze_executable(scope['hosts'][host]['path'], version, scope['hosts'][host]['sha256'])
        state = budget.native.check()
        remaining = budget.remaining(state)
        handle = owned_process.launch(command, directory=directory, identity=identity,
            supervisor_executable=scope['hosts']['supervisor_python']['path'], env=environment,
            budget_seconds=min(120., remaining), resource_budget=budget.resource_budget, writer_executable=expected,
            scope_role='alpha-husk' if role == 'houdini' else 'alpha-nuke', scope_heavy=True)
        try:
            handle.wait(timeout=min(125., budget.remaining()))
        except BaseException:
            handle.terminate()
            handle.wait(timeout=5)
            raise
        for path, digest in bindings['source_freeze'].items():
            if file_record(path)['sha256'] != digest: raise ValueError('ALPHA_RUNNER_FROZEN_SOURCE_CHANGED')
        started = owned_process.read_receipt(directory, 'started', identity=identity)
        stopped = owned_process.read_receipt(directory, 'stopped', identity=identity)
        if not stopped or owned_process.execution_returncode(stopped) != 0:
            if stopped and type(started) is dict and started.get('writer_process_binding_error') is not None:
                alpha_calibration.validate_native_process_binding(started, stopped,
                    expected_executable=expected, identity=identity, command=command)
            raise ValueError('ALPHA_RUNNER_NATIVE_EXECUTION_FAILED')
        budget.native.check()
        alpha_calibration.validate_native_process_binding(started, stopped,
            expected_executable=expected, identity=identity, command=command)
        output = {'schema': owned_process.SCHEMA, 'event': 'alpha-output', 'identity': identity,
            'started_sha256': alpha_calibration._sha(started), 'stopped_sha256': alpha_calibration._sha(stopped),
            'command': command, 'route_sha256': bindings['route_sha256'], 'plugin_build': bindings['plugin_build'],
            'evidence_source': evidence_source, 'observed_by': 'trusted_controller_after_owned_tree_stop',
            'source': file_record(ROOT / 'tools/prepare_native_alpha_scene.py' if role == 'houdini' else Path(alpha_calibration.__file__).resolve()),
            'chart': file_record(prep['chart_path']),
            'executable': file_record(expected['image']['path'])}
        _decoded(output['chart'], profile)
        if role == 'houdini':
            output['scene'] = prep['scene']; checked(prep['scene'])
        else:
            root = Path(data['observer_root'])
            sources = {name: file_record(root / (name + '.json'), 1024 * 1024) for name in ('houdini_raw', 'nuke_composite')}
            raw, composite = (load(record['path']) for record in sources.values())
            alpha_calibration._numeric_observation(raw, composite)
            output.update(sources=sources, images=composite['images'])
            for image in output['images']: _decoded(image, profile)
        _seal(directory, identity, output)
        native_operations[role] = {'directory': str(directory), 'identity': identity, 'output_sha256': alpha_calibration._sha(output)}
        outputs[role] = output
    nuke = native_operations['nuke']
    directory, identity = Path(nuke['directory']), nuke['identity']
    terminal = {'schema': owned_process.SCHEMA, 'event': 'alpha-calibration', 'identity': identity,
        'calibration_schema': 'bridge.alpha-calibration/1.0', 'version': '21.0.631',
        'plugin_build': bindings['plugin_build'], 'route_sha256': bindings['route_sha256'], 'evidence_source': evidence_source,
        'started_sha256': outputs['nuke']['started_sha256'], 'stopped_sha256': outputs['nuke']['stopped_sha256'],
        'verifier_sha256': file_record(Path(alpha_calibration.__file__).resolve())['sha256'],
        'native_operations': native_operations, 'sources': outputs['nuke']['sources'],
        'derived_by': 'trusted_controller_from_original_native_operations'}
    _seal(directory, identity, terminal)
    binding = {'directory': str(directory), 'identity': identity, 'terminal_sha256': alpha_calibration._sha(terminal)}
    calibration = alpha_calibration.validate_alpha_calibration(binding, expected_version='21.0.631',
        expected_plugin_build=bindings['plugin_build'], expected_route_sha256=bindings['route_sha256'], evidence_source=evidence_source)
    result = {'schema': 'bridge.alpha-runner.result/1', 'alpha_calibration': binding,
        'calibration': calibration, 'scope_sha256': report['scope_sha256'], 'bindings_sha256': report['bindings_sha256'],
        'evidence_source': evidence_source}
    result_path = budget.root / 'alpha-calibration-result.json'
    with result_path.open('xb') as stream: stream.write(owned_process._canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--bindings')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-scope-sha256')
    parser.add_argument('--approved-bindings-sha256')
    args = parser.parse_args()
    if args.execute:
        result = execute(args.scope, args.bindings, approved_scope_sha256=args.approved_scope_sha256,
                         approved_bindings_sha256=args.approved_bindings_sha256)
    else:
        result, _ = preflight(args.scope, args.bindings)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('state') != 'BLOCKED' else 2


if __name__ == '__main__': raise SystemExit(main())
