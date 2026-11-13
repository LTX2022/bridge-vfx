#!/usr/bin/env python3
"""One reviewed H21 HIP construction and cold-reopen diagnostic.

Preparation and preflight never dispatch native processes. Activation is an
explicit trusted-controller action using the user's conditional authorization
and an independent, freeze-bound review; hashes alone grant no permission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')
for _package in PACKAGES:
    sys.path.insert(0, str(ROOT / 'packages' / _package / 'src'))
from dcc_task_runtime.native_scope import (
    NativeScope, HIP_RESOURCE_PROFILE, HIP_SCOPE_SCHEMA, HIP_BUDGET, HIP_ROLE_SECONDS,
)
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.graph_scheduler import GraphScheduler
from dcc_task_runtime import owned_process
from vfx_pipeline.graph_job_evidence import process_identity
from vfx_pipeline.graph_jobs import GraphJobService
from houdini_bridge.client import HoudiniClient
from houdini_bridge.operation_receipts import validate_scene_contract_header
from houdini_bridge.task_host import RUNNER_TEMPLATE

OUTER_BUDGET = {'per_operation_seconds': 120, 'total_seconds': 600, 'max_dcc_starts': 8,
    'max_disk_bytes': 536870912, 'max_heavy_operations': 1, 'automatic_retries': 0}
LIMITS = {'starts': 2, 'total_seconds': 240, 'per_start_seconds': 120,
    'max_bytes': 536870912, 'jobs': 1, 'retries': 0, 'stop_reserve_seconds': 10}
PROPOSAL = {'schema': 'bridge.registered-domain-construction/1',
    'domain_pack': 'material_lookdev_v1', 'houdini_version': '21.0.631',
    'scene_profile': 'sphere_ground_v2'}
TOOLS = ('nuke_owned_render_worker.py', 'software_graph_worker.py', 'verify_controlled_output.py',
    'prepare_native_alpha_scene.py', 'run_alpha_calibration.py', 'run_controlled_engineering.py',
    'prepare_controlled_engineering.py', 'prepare_nuke_project.py', 'activate_controlled_engineering.py',
    'prepare_workbuddy_graph.py', 'prepare_workbuddy.py', 'run_hip_diagnostic.py')
SCENE = Path('docs/official-baselines/karma/frozen-scene-v2.json')
AUTH_TEXT = '列出完整计划，开子agent检查计划缺陷，它说没问题就去执行'


def limits_for(resource_profile=None):
    if resource_profile is None:
        return dict(LIMITS)
    if resource_profile != HIP_RESOURCE_PROFILE:
        raise ValueError('HIP_RESOURCE_PROFILE_INVALID')
    return {'starts': HIP_BUDGET['max_dcc_starts'], 'total_seconds': HIP_BUDGET['total_seconds'],
        'per_start_seconds': HIP_BUDGET['per_operation_seconds'],
        'max_bytes': HIP_BUDGET['max_disk_bytes'], 'jobs': HIP_BUDGET['max_heavy_operations'],
        'retries': HIP_BUDGET['automatic_retries'], 'stop_reserve_seconds': 10,
        'role_seconds': dict(HIP_ROLE_SECONDS)}


def native_limits(native):
    return limits_for(native.resource_profile)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def plain(raw):
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts or path != path.resolve():
        raise ValueError('HIP_PATH_INVALID')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('HIP_SYMLINK_REFUSED')
    return path


def record(path):
    path = plain(path)
    if not path.is_file():
        raise ValueError('HIP_FILE_MISSING')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def checked(value):
    if record(value['path']) != value:
        raise ValueError('HIP_FILE_CHANGED')
    return plain(value['path'])


def load(path):
    path = plain(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('HIP_JSON_LIMIT')
    return json.loads(path.read_bytes())


def write(path, value):
    with plain(path).open('xb') as stream:
        stream.write(canonical(value))
    return record(path)


def binding(path):
    return {k: v for k, v in record(path).items() if k != 'bytes'}


def stage_journal(path, scope_sha, freeze_sha):
    spec = importlib.util.spec_from_file_location('hip_stage_journal', ROOT / 'tools/run_controlled_engineering.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.StageJournal(path, scope_sha, freeze_sha)


def source_paths(repo):
    paths = []
    for package in PACKAGES:
        paths.extend((repo / 'packages' / package / 'src').rglob('*.py'))
    paths.extend(p for p in (repo / 'plugins/houdini').rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
    paths += [repo / 'plugins/nuke/nuke_bridge_addon.py', repo / SCENE]
    paths += [repo / 'tools' / name for name in TOOLS]
    for path in paths:
        plain(path)
    return sorted(set(paths))


def source_manifest(repo):
    return {str(p.relative_to(repo)): record(p)['sha256'] for p in source_paths(repo)}


def _initialize(root, config, plan, sources, source_repo, *, authorized=False, activation=None):
    profile = config.get('resource_profile')
    limits = limits_for(profile)
    root = plain(root)
    if root.exists() or not root.parent.is_dir():
        raise ValueError('HIP_FRESH_ROOT_REQUIRED')
    root.mkdir(mode=0o700)
    frozen = root / 'control/snapshot'
    for relative, digest in sources.items():
        source = source_repo / relative
        if record(source)['sha256'] != digest:
            raise ValueError('HIP_SOURCE_DRIFT')
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    copied_plan = root / 'plan.md'
    shutil.copyfile(checked(plan), copied_plan)
    config_record = write(root / 'configuration.json', config)
    freeze = {'schema': 'bridge.hip-diagnostic.freeze/1', 'sources': sources,
        'plan': record(copied_plan), 'configuration': config_record, 'limits': limits,
        'proposal': PROPOSAL, 'evidence_source': config['evidence_source']}
    freeze_record = write(root / 'freeze.json', freeze)
    key = secrets.token_bytes(32)
    scope = {'schema': HIP_SCOPE_SCHEMA if profile else 'bridge.engineering-closure-scope/1',
        'scope_id': 'hip-' + uuid.uuid4().hex,
        'output_root': str(root), 'execution_authorized': authorized,
        'status': 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION' if authorized else 'PREPARED_NOT_AUTHORIZED',
        'budget': dict(HIP_BUDGET) if profile else dict(OUTER_BUDGET),
        'hosts': config['hosts'], 'versions': {'houdini': '21.0.631'},
        'project_color': {'working_space': 'ACEScg', 'source': 'user_confirmed'},
        'evidence_source': config['evidence_source'],
        'accounting': {'key_path': str(root / '.native-control/key'),
                       'key_sha256': hashlib.sha256(key).hexdigest()}}
    if profile:
        scope.update(resource_profile=profile, role_seconds=dict(HIP_ROLE_SECONDS))
    if activation:
        scope['activation_review'] = activation['review']
    scope_record = write(root / 'scope.json', scope)
    native = NativeScope.initialize(binding(scope_record['path']), key=key)
    if activation:
        write(root / 'activation.json', native._envelope({**activation,
            'scope': native.binding, 'freeze': freeze_record,
            'schema': 'bridge.hip-diagnostic.activation/1'}))
    return {'scope': native.binding, 'freeze': freeze_record, 'state': scope['status'],
            'native_execution_status': 'NOT_RUN', 'dcc_starts': native.snapshot()['dcc_starts']}


def prepare(root, *, plan, hython, supervisor_python, ocio_config, evidence_source='real_host',
            resource_profile=None):
    limits_for(resource_profile)
    if evidence_source not in ('real_host', 'software_test'):
        raise ValueError('HIP_EVIDENCE_SOURCE_INVALID')
    hosts = {'hython': record(hython), 'supervisor_python': record(supervisor_python)}
    if evidence_source == 'real_host' and ('Houdini21.0.631' not in hosts['hython']['path']
            or Path(hosts['hython']['path']).name != 'hython'):
        raise ValueError('HIP_H21_EXECUTABLE_REQUIRED')
    if 'python' not in Path(hosts['supervisor_python']['path']).name.lower():
        raise ValueError('HIP_PLAIN_SUPERVISOR_REQUIRED')
    config = {'task_id': 'hip-only-h21-20261024', 'hosts': hosts,
        'ocio_config': record(ocio_config), 'evidence_source': evidence_source}
    if resource_profile:
        config.update(resource_profile=resource_profile, task_id='hip360-h21-20261024')
    return _initialize(root, config, record(plan), source_manifest(ROOT), ROOT)


def frozen_data(scope_path, *, require_frozen=False):
    native = NativeScope(binding(scope_path))
    root = native.root
    freeze_record = record(root / 'freeze.json')
    freeze = load(freeze_record['path'])
    config = load(checked(freeze['configuration']))
    profile = config.get('resource_profile')
    limits = limits_for(profile)
    frozen = root / 'control/snapshot'
    if (freeze.get('schema') != 'bridge.hip-diagnostic.freeze/1' or freeze.get('limits') != limits
            or freeze.get('proposal') != PROPOSAL
            or native.scope['budget'] != (HIP_BUDGET if profile else OUTER_BUDGET)
            or native.resource_profile != profile
            or config['hosts'] != native.scope['hosts']
            or config['evidence_source'] != freeze['evidence_source']
            or native.scope.get('evidence_source') != freeze['evidence_source']
            or source_manifest(frozen) != freeze['sources']):
        raise ValueError('HIP_FREEZE_DRIFT')
    checked(freeze['plan'])
    for item in [*config['hosts'].values(), config['ocio_config']]:
        checked(item)
    native.validate_host('houdini', '21.0.631', config['hosts']['hython']['path'],
        config['hosts']['supervisor_python']['path'], allow_missing_writer=True)
    if require_frozen and ROOT != frozen:
        raise ValueError('HIP_FROZEN_ENTRY_REQUIRED')
    return {'native': native, 'root': root, 'freeze': freeze, 'freeze_record': freeze_record,
        'config': config, 'frozen': frozen, 'control': root / 'control', 'limits': limits}


def activate(candidate_scope, *, review_path, authorization_path, output_root):
    """Explicit local controller action; never invoked by prepare or preflight."""
    data = frozen_data(candidate_scope)
    native = data['native']
    state = native.snapshot()
    if native.scope['execution_authorized'] or state['dcc_starts'] or state['closed_reason']:
        raise ValueError('HIP_UNUSED_CANDIDATE_REQUIRED')
    review_record, auth_record = record(review_path), record(authorization_path)
    review, authorization = load(review_path), load(authorization_path)
    target = plain(output_root)
    expected = {'candidate_scope': native.binding, 'candidate_freeze': data['freeze_record'],
        'source_sha256': hashlib.sha256(canonical(data['freeze']['sources'])).hexdigest(),
        'target_root': str(target)}
    if (review.get('schema') != 'bridge.hip-diagnostic.review/1' or review.get('decision') != 'APPROVED'
            or review.get('reviewer') != '/root/hip_only_plan_review'
            or any(review.get(k) != v for k, v in expected.items())):
        raise ValueError('HIP_INDEPENDENT_REVIEW_REQUIRED')
    profile = data['config'].get('resource_profile')
    if profile and any(value.get('resource_profile') != profile
            or value.get('resource_contract') != data['limits'] for value in (review, authorization)):
        raise ValueError('HIP_RESOURCE_CONTRACT_CONFIRMATION_REQUIRED')
    authority = ('current_user_resource_contract_confirmation' if profile
                 else 'current_user_conditional_instruction')
    instruction = '同意新预算，审核后执行' if profile else AUTH_TEXT
    if (authorization.get('schema') != 'bridge.hip-diagnostic.conditional-authorization/1'
            or authorization.get('authority') != authority
            or authorization.get('instruction') != instruction or authorization.get('review') != review_record
            or any(authorization.get(k) != v for k, v in expected.items())):
        raise ValueError('HIP_TRUSTED_CONDITIONAL_AUTHORIZATION_REQUIRED')
    return _initialize(target, data['config'], data['freeze']['plan'], data['freeze']['sources'],
        data['frozen'], authorized=True, activation={'review': review_record,
            'authorization': auth_record, 'candidate_scope': native.binding,
            'candidate_freeze': data['freeze_record'], 'trusted_action': 'conditional_controller_activation'})


def _activation(data):
    native = data['native']
    value = native._verify_envelope(load(data['root'] / 'activation.json'))
    if (native.scope['execution_authorized'] is not True
            or native.scope['status'] != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or value.get('scope') != native.binding or value.get('freeze') != data['freeze_record']
            or value.get('trusted_action') != 'conditional_controller_activation'
            or value.get('review') != native.scope.get('activation_review')):
        raise ValueError('HIP_ACTIVATION_BINDING_INVALID')
    checked(value['review']); checked(value['authorization'])
    return value


def active_native_processes():
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,comm='], capture_output=True, text=True,
                            timeout=5, check=True)
    active = []
    for line in result.stdout.splitlines():
        pid, _, command = line.strip().partition(' ')
        name = Path(command.strip()).name.lower()
        if (name in {'hython', 'husk', 'houdini', 'houdinifx'}
                or re.fullmatch(r'nuke(?:\d+(?:\.\d+)*(?:v\d+)?)?', name)):
            active.append({'pid': int(pid), 'executable': command.strip()})
    return active


def admission(native, stage):
    limits = native_limits(native)
    state = native.snapshot()
    if (state['closed_reason'] or state['dcc_starts'] != stage
            or any(t['stopped_at'] is None for t in state['tickets'])
            or any(t['charged_seconds'] > native.role_seconds(t['role']) for t in state['tickets'])
            or [t['role'] for t in state['tickets']] != ['graph-worker', 'houdini-host'][:stage]
            or state['disk_bytes'] >= limits['max_bytes']
            or state['total_seconds'] >= limits['total_seconds'] or stage >= limits['starts']):
        raise ValueError('HIP_ADMISSION_REFUSED')
    role = ('graph-worker', 'houdini-host')[stage]
    seconds = min(native.role_seconds(role), limits['total_seconds'] - state['total_seconds'])
    seconds -= limits['stop_reserve_seconds']
    if seconds <= limits['stop_reserve_seconds']:
        raise ValueError('HIP_STOP_RESERVE_EXHAUSTED')
    return {'roots': [str(native.root)], 'max_bytes': limits['max_bytes'],
            'max_seconds': seconds, 'native_scope': native.binding}


def preflight(scope_path):
    data = frozen_data(scope_path)
    state = data['native'].snapshot()
    blockers = []
    if state['dcc_starts'] or state['closed_reason'] or (data['root'] / 'stages.json').exists():
        blockers.append('HIP_SCOPE_ALREADY_USED')
    if state['disk_bytes'] >= data['limits']['max_bytes']:
        blockers.append('HIP_DISK_BUDGET')
    active = active_native_processes()
    if active:
        blockers.append('HIP_EXISTING_NATIVE_PROCESS')
    if data['native'].scope['execution_authorized']:
        _activation(data)
    return {'schema': 'bridge.hip-diagnostic.preflight/1',
        'state': 'BLOCKED' if blockers else 'PREPARED', 'blockers': blockers,
        'scope': data['native'].binding, 'freeze': data['freeze_record'],
        'source_sha256': hashlib.sha256(canonical(data['freeze']['sources'])).hexdigest(),
        'evidence_source': data['config']['evidence_source'], 'dcc_starts': state['dcc_starts'],
        'active_native_processes': active, 'native_execution_status': 'NOT_RUN'}


def receipt_pair(ticket):
    directory = plain(ticket['directory'])
    start = owned_process.read_receipt(directory, 'started', identity=ticket['identity'])
    stop = owned_process.read_receipt(directory, 'stopped', identity=ticket['identity'])
    if (not start or not stop or owned_process.execution_returncode(stop) != 0
            or stop.get('observed_by') != 'owned_child_wait'):
        raise ValueError('HIP_SIGNED_STOP_UNPROVEN')
    return {'started': start, 'stopped': stop}


def _saved_contract(data, hip, digest, contract_digest):
    matches = []
    for path in (data['control'] / 'houdini-instances/fx_operations').glob('*.saves.json'):
        for item in load(path).get('saves', []):
            if ((item.get('scene_contract') or {}).get('task_id') == data['config']['task_id']
                    and item.get('path') == str(hip) and item.get('sha256') == digest):
                matches.append(item)
    if not matches:
        raise ValueError('HIP_REAL_SAVE_CONTRACT_MISSING')
    saved = matches[-1]
    contract = saved.get('scene_contract')
    if isinstance(contract, dict) and isinstance(contract.get('nodes'), list):
        for node in contract['nodes']:
            if (not isinstance(node, dict)
                    or not {'path', 'type', 'parameters', 'parameter_channels', 'inputs'} <= node.keys()
                    or not isinstance(node['parameter_channels'], dict)):
                raise ValueError('HIP_CHANNEL_READBACK_MISSING')
    try:
        validate_scene_contract_header(contract, task_id=data['config']['task_id'])
    except ValueError as error:
        raise ValueError('HIP_FULL_CONTRACT_REQUIRED') from error
    if (hashlib.sha256(canonical(contract)).hexdigest() != contract_digest
            or saved.get('scene_contract_sha256') != contract_digest):
        raise ValueError('HIP_FULL_CONTRACT_REQUIRED')
    frozen = contract.get('frozen_scene_parameters') or {}
    if (frozen.get('profile') != 'sphere_ground_v2' or not frozen.get('fields')
            or set(frozen.get('geometry', {})) != {'Sphere', 'Ground'}):
        raise ValueError('HIP_FROZEN_READBACK_MISSING')
    for geometry in frozen['geometry'].values():
        if not geometry.get('resolved_prims') or any(not p.get('material_prim_path') for p in geometry['resolved_prims']):
            raise ValueError('HIP_USDSHADE_READBACK_MISSING')
    return saved


def graph_deadlines(service, operation, outer_deadline, reserve):
    persisted = service.operation_deadline(operation)
    hard = min(outer_deadline, time.monotonic() + max(0, persisted - service.clock()))
    return persisted, hard, hard - reserve


def run_graph(data, budget):
    control, config = data['control'], data['config']
    limits = data.get('limits') or native_limits(data['native'])
    reserve = limits['stop_reserve_seconds']
    scene = record(data['frozen'] / SCENE)
    manifest = [{'index': 0, 'asset_id': 'frozen-sphere-ground-v2',
        'semantic_role': 'render_scene_configuration', 'source_uri': scene['path'],
        'bytes': scene['bytes'], 'sha256': scene['sha256']}]
    service = GraphJobService(control / 'jobs', data['frozen'], config['hosts']['hython']['path'],
        scheduler_root=control / 'scheduler', task_id=config['task_id'],
        frozen_input_manifest=manifest, resource_budget=budget)
    operation = None
    hard_deadline = time.monotonic() + min(data['native'].role_seconds('graph-worker'),
                                         budget['max_seconds'] + reserve)
    try:
        graph = service.propose(PROPOSAL, config['task_id'] + '-propose')
        operation = service.trial(graph, config['task_id'] + '-trial')
        persisted_deadline, hard_deadline, deadline = graph_deadlines(
            service, operation, hard_deadline, reserve)
        while True:
            status = service.status(operation)
            if status['state'] not in {'PREPARED', 'STARTING', 'RUNNING'}:
                break
            if time.monotonic() >= deadline:
                service.cancel(operation)
                raise ValueError('HIP_GRAPH_DEADLINE')
            time.sleep(.05)
        result = status.get('result') or {}
        expected_scopes = ({'host_construction_only'} if config['evidence_source'] == 'real_host'
                           else {'host_construction_only', 'software_test', 'software_fake_host'})
        if (status['state'] != 'SUCCEEDED' or status.get('stop_confirmed') is not True
                or result.get('construction_executed') is not True
                or result.get('validation_scope') not in expected_scopes):
            raise ValueError('HIP_GRAPH_NOT_SUCCEEDED')
        paths = service._worker_paths(operation)
        raw = load(paths['result'])
        if raw.get('validation_scope') not in expected_scopes:
            raise ValueError('HIP_SOFTWARE_BOUNDARY_REFUSED')
        verify = raw.get('verification') or {}
        if any(verify.get(k) is not True for k in ('nodes_verified', 'parameters_verified', 'connections_verified')):
            raise ValueError('HIP_GRAPH_READBACK_MISSING')
        hip = plain(verify['hip_path'])
        if not hip.is_relative_to(control / 'jobs') or record(hip)['sha256'] != verify['hip_sha256']:
            raise ValueError('HIP_ARTIFACT_INVALID')
        saved = _saved_contract(data, hip, verify['hip_sha256'], verify['registered_scene_contract_sha256'])
        evidence = raw.get('native_operation_evidence') or {}
        evidence_path = Path(evidence.get('path', ''))
        if not evidence_path.is_absolute():
            evidence_path = service.root / evidence_path
        evidence_record = record(evidence_path)
        payload = load(evidence_path)
        receipts = payload.get('receipts', [])
        if evidence_record['sha256'] != evidence.get('sha256') or not receipts:
            raise ValueError('HIP_NATIVE_HOM_UNPROVEN')
        expected_boundary = 'native_hom' if config['evidence_source'] == 'real_host' else 'software_hou_api'
        for receipt in receipts:
            receipt_path = plain(receipt['path'])
            if not receipt_path.is_relative_to(control / 'graph-houdini-instances'):
                raise ValueError('HIP_NATIVE_RECEIPT_PATH_INVALID')
            checked({k: receipt[k] for k in ('path', 'bytes', 'sha256')})
            original = load(receipt_path)
            if receipt.get('storage_format') == 'legacy_task_store':
                original = original.get('producer_operations', {}).get(receipt['operation_id'])
            if not original or original.get('execution_boundary') != expected_boundary:
                raise ValueError('HIP_NATIVE_HOM_UNPROVEN')
        row = dict(service._row(operation))
        birth = json.loads(row['process_identity_json'])
        state = data['native'].snapshot()
        if state['dcc_starts'] != 1 or not birth.get('birth'):
            raise ValueError('HIP_WORKER_BIRTH_MISSING')
        pair = receipt_pair(state['tickets'][0])
        if pair['started']['pid'] != birth['pid']:
            raise ValueError('HIP_WORKER_PID_MISMATCH')
        return {'operation': status, 'worker_result': raw, 'save': saved,
            'hip': record(hip), 'birth_identity': birth, 'native_evidence': evidence_record,
            'signed_process': pair, 'operation_deadline_at': persisted_deadline,
            'stop_reserve_seconds': reserve}
    finally:
        service.close()
        # The service's default close joins monitors briefly. This diagnostic
        # also consumes its reserved stop interval, without extending the
        # service's own deadline or releasing an unknown worker.
        if operation is not None:
            handle = service._supervised_handle(service._row(operation))
            while handle is not None and time.monotonic() < hard_deadline:
                tickets = data['native'].snapshot()['tickets']
                if not tickets or all(t['stopped_at'] is not None for t in tickets):
                    break
                time.sleep(.05)
            state = data['native'].snapshot()
            if any(t['stopped_at'] is None for t in state['tickets']):
                write(control / 'graph-stop-unknown.json', {'state': 'STOP_UNKNOWN',
                    'operation_id': operation, 'scheduler_slot_retained': True})


def _host_environment(data, directory, supervisor_identity):
    root, control = data['root'], data['control']
    environment = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
    temporary = directory / 'tmp'
    temporary.mkdir(parents=True)
    preferences = directory / 'prefs'
    preferences.mkdir()
    environment.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='en_US.UTF-8', TZ='UTC',
        PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
        TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary),
        XDG_CACHE_HOME=str(temporary / 'cache'), XDG_CONFIG_HOME=str(temporary / 'config'),
        HOUDINI_TEMP_DIR=str(temporary), HOUDINI_USER_PREF_DIR=str(preferences / '__HVER__'),
        OCIO=data['config']['ocio_config']['path'],
        HOUDINI_BRIDGE_STATE_DIR=str(control / 'houdini-instances'),
        HOUDINI_BRIDGE_TASK_STATE_DIR=str(control / 'houdini-instances'),
        BRIDGE_SKILLS_SCHEDULER_ROOT=str(control / 'scheduler'),
        BRIDGE_SKILLS_STATE_ROOT=str(control / 'host-runtime-state'),
        BRIDGE_ARTIFACT_LEDGER_ROOT=str(control / 'artifact_ledger'),
        BRIDGE_OWNED_SUPERVISOR_DIR=str(directory / 'owned-supervisor'),
        BRIDGE_OWNED_SUPERVISOR_IDENTITY=canonical(supervisor_identity).decode())
    return environment


def validate_cold(result, before, graph, operation_id, snapshot_before):
    saved, hip = graph['save'], graph['hip']
    transition = result.get('scene_transition') or {}
    after = transition.get('after_identity') or {}
    fixed = ('task_id', 'session_id', 'launch_nonce', 'pid', 'process_generation', 'plugin_build')
    if (result.get('path') != hip['path'] or result.get('sha256') != hip['sha256']
            or result.get('scene_contract_sha256') != saved['scene_contract_sha256']
            or result.get('load_warnings') != [] or result.get('structure_verified', 0) <= 0
            or any(result.get(k) is not True for k in ('nodes_verified', 'parameters_verified', 'connections_verified'))
            or result.get('node_count') != len(saved['scene_contract']['nodes'])
            or result.get('frozen_scene_parameters') != saved['scene_contract']['frozen_scene_parameters']
            or transition.get('state') != 'COMPLETED' or transition.get('operation_id') != operation_id
            or transition.get('before_identity') != before
            or any(after.get(k) != before.get(k) for k in fixed)
            or type(after.get('scene_epoch')) is not int or after['scene_epoch'] <= before['scene_epoch']
            or transition.get('result', {}).get('snapshot_path') != snapshot_before['path']
            or transition.get('result', {}).get('snapshot_sha256') != snapshot_before['sha256']):
        raise ValueError('HIP_COLD_READBACK_UNPROVEN')
    checked(hip); checked(snapshot_before)


def cold_runner(data, directory, nonce, budget):
    limits = data.get('limits') or limits_for(data['config'].get('resource_profile'))
    bootstrap = 'import sys\n' + ''.join('sys.path.insert(0, ' + repr(str(data['frozen'] / 'packages' / package / 'src')) + ')\n'
                                         for package in PACKAGES)
    return bootstrap + RUNNER_TEMPLATE.format(addon_libs=str(data['frozen'] / 'plugins/houdini/python3.11libs'),
        task_id=data['config']['task_id'], ready_file=str(directory / 'ready.json'), stop_file=str(directory / 'stop'), poll_seconds=.05,
        max_seconds=(budget['max_seconds'] if data['config'].get('resource_profile')
                     else budget['max_seconds'] - limits['stop_reserve_seconds']), warmup=False,
        launch_nonce=nonce, writer_executable=None)


def run_cold(data, budget, graph):
    control, config = data['control'], data['config']
    limits = data.get('limits') or native_limits(data['native'])
    reserve = limits['stop_reserve_seconds']
    extended = bool(config.get('resource_profile'))
    directory = control / 'cold-host'
    directory.mkdir()
    nonce = uuid.uuid4().hex
    identity = {'task_id': config['task_id'], 'launch_nonce': nonce}
    ready, stop = directory / 'ready.json', directory / 'stop'
    runner = directory / 'runner.py'
    runner.write_text(cold_runner(data, directory, nonce, budget))
    scheduler = GraphScheduler(control / 'scheduler')
    owner, operation = str(directory), config['task_id'] + '-cold-reopen'
    snapshot_path = (control / 'houdini-instances/scene-transition-snapshots' / config['task_id'] /
                     (graph['hip']['sha256'] + '.hip'))
    snapshot = record(snapshot_path)
    if snapshot['sha256'] != graph['hip']['sha256']:
        raise ValueError('HIP_SNAPSHOT_INVALID')
    permit = scheduler.reserve(owner, operation)
    token = permit['token']
    handle = None
    dispatched = False
    deadline = time.monotonic() + budget['max_seconds'] + (reserve if extended else 0)
    try:
        scheduler.arm(owner, operation, token)
        dispatched = True
        handle = owned_process.launch([config['hosts']['hython']['path'], str(runner)],
            directory=directory / 'owned-supervisor', identity=identity,
            supervisor_executable=config['hosts']['supervisor_python']['path'],
            env=_host_environment(data, directory, identity),
            budget_seconds=budget['max_seconds'] + (reserve if extended else 0),
            resource_budget=budget, scope_role='houdini-host', scope_heavy=False)
        if extended:
            tickets = data['native'].snapshot()['tickets']
            selected = [t for t in tickets if t['role'] == 'houdini-host'
                        and t['directory'] == str(directory / 'owned-supervisor') and t['identity'] == identity]
            if len(selected) != 1:
                raise ValueError('HIP_HOST_TICKET_UNPROVEN')
            remaining = data['native'].remaining_seconds(selected[0])
            deadline = min(deadline, time.monotonic() + remaining)
        birth = process_identity(handle.pid)
        birth.pop('state', None)
        if (not birth.get('birth') or birth['pid'] == graph['birth_identity']['pid']
                or birth['birth'] == graph['birth_identity']['birth']):
            raise ValueError('HIP_NEW_PROCESS_UNPROVEN')
        scheduler.bind_process(owner, operation, token, birth)
        call_deadline = deadline - reserve
        receipt = None
        while receipt is None:
            if handle.poll() is not None or time.monotonic() >= call_deadline:
                raise ValueError('HIP_HOST_READY_UNPROVEN')
            if ready.exists():
                try:
                    receipt = load(ready)
                except json.JSONDecodeError:
                    pass  # task_host writes this small receipt non-atomically.
            if receipt is not None:
                break
            time.sleep(.05)
        trusted = receipt.get('task_host_identity') or {}
        plugin = data['freeze']['sources']['plugins/houdini/_impl/houdini_bridge_addon.py']
        if (receipt.get('pid') != handle.pid or receipt.get('launch_nonce') != nonce
                or receipt.get('task_id') != config['task_id'] or receipt.get('gui') is not False
                or receipt.get('houdini_version') != '21.0.631' or receipt.get('addon_sha256') != plugin
                or receipt.get('warmup') != 'skipped'
                or any(trusted.get(k) != v for k, v in {'task_id': config['task_id'], 'pid': handle.pid,
                    'launch_nonce': nonce, 'plugin_build': plugin, 'version': '21.0.631'}.items())):
            raise ValueError('HIP_READY_BINDING_INVALID')
        instance_dir = control / 'houdini-instances/instances'
        instance = load(instance_dir / (str(handle.pid) + '.json'))
        name = instance.get('token_file')
        if (not isinstance(name, str) or Path(name).name != name or not name.endswith('.token')
                or any(instance.get(k) != v for k, v in {'pid': handle.pid,
                    'session_id': trusted['session_id'], 'port': receipt['port'],
                    'loaded_addon_sha256': plugin, 'houdini_version': '21.0.631'}.items())):
            raise ValueError('HIP_TOKEN_BINDING_INVALID')
        token_path = plain(instance_dir / name)
        auth_token = token_path.read_text(encoding='ascii')
        client = HoudiniClient(receipt['port'], timeout_seconds=max(.01, call_deadline-time.monotonic()), token=auth_token)
        # Do not allow fallback discovery of another instance's credentials.
        client._token_candidates = (auth_token,)
        with scheduler.operation(owner, operation, token):
            before = client.health().get('task_host_identity')
        if before != trusted:
            raise ValueError('HIP_HEALTH_BINDING_INVALID')
        client.timeout_seconds = max(.01, call_deadline-time.monotonic())
        with scheduler.operation(owner, operation, token):
            result = client.call('scene.reopen_task_hip', {'task_id': config['task_id'],
                'path': graph['hip']['path'], 'sha256': graph['hip']['sha256'],
                'scene_contract_sha256': graph['save']['scene_contract_sha256'],
                'operation_id': operation, 'request_id': operation, 'scene_before_identity': before})
        validate_cold(result, before, graph, operation, snapshot)
        stop.write_text('stop\n')
        handle.wait(timeout=max(.01, deadline-time.monotonic()))
        pair = receipt_pair({'directory': str(handle.directory), 'identity': identity})
        scheduler.release(owner, operation, token, stopped=True)
        return {'ready': receipt, 'birth_identity': birth, 'reopen': result,
                'snapshot': snapshot, 'signed_process': pair}
    finally:
        if handle is not None:
            if not stop.exists():
                stop.write_text('stop\n')
            try:
                handle.wait(timeout=max(.01, deadline-time.monotonic()))
                receipt_pair({'directory': str(handle.directory), 'identity': identity})
                scheduler.release(owner, operation, token, stopped=True)
            except (ValueError, OSError, subprocess.TimeoutExpired):
                handle.terminate()
                try:
                    handle.wait(timeout=max(.01, deadline-time.monotonic()))
                    receipt_pair({'directory': str(handle.directory), 'identity': identity})
                    scheduler.release(owner, operation, token, stopped=True)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    # The durable reservation remains occupied on unknown
                    # stop; the outer journal closes this diagnostic.
                    write(directory / 'stop-unknown.json', {'state': 'STOP_UNKNOWN',
                        'scheduler_slot_retained': True, 'operation_id': operation,
                        'native_execution_status': 'ATTEMPTED_FAILED_CLOSED'})
        elif not dispatched and scheduler.fence_unstarted(owner, operation, token):
            scheduler.release(owner, operation, token, unstarted=True)


@contextmanager
def controlled_environment(data):
    directory = data['root'] / 'runtime'
    directory.mkdir()
    identity = {'task_id': data['config']['task_id'], 'launch_nonce': 'environment-only'}
    environment = _host_environment(data, directory, identity)
    environment['BRIDGE_GRAPH_STARTUP_DIAGNOSTICS'] = '1'
    environment.pop('BRIDGE_OWNED_SUPERVISOR_DIR')
    environment.pop('BRIDGE_OWNED_SUPERVISOR_IDENTITY')
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _execute(scope_path, *, software_test=False):
    data = frozen_data(scope_path, require_frozen=True)
    _activation(data)
    source = 'software_test' if software_test else 'real_host'
    if data['config']['evidence_source'] != source:
        raise ValueError('HIP_EXECUTION_SOURCE_MISMATCH')
    if Path(sys.executable).resolve() != Path(data['config']['hosts']['supervisor_python']['path']):
        raise ValueError('HIP_FIXED_CONTROLLER_PYTHON_REQUIRED')
    native = data['native']
    journal_path = data['root'] / 'stages.json'
    with execution_lock(journal_path, data['config']['task_id']):
        journal = stage_journal(journal_path, native.binding['sha256'], data['freeze_record']['sha256'])
        if journal.existing:
            raise ValueError('HIP_EXECUTION_ALREADY_ATTEMPTED')
        try:
            if preflight(scope_path)['state'] != 'PREPARED':
                raise ValueError('HIP_PREFLIGHT_BLOCKED')
            budget = admission(native, 0)
            journal.intent('graph', {'request_id': data['config']['task_id'] + '-trial', 'budget': budget})
            with controlled_environment(data):
                graph = run_graph(data, budget)
            journal.done('graph', graph)
            refreshed = frozen_data(scope_path, require_frozen=True)
            _activation(refreshed)
            if refreshed['freeze_record'] != data['freeze_record']:
                raise ValueError('HIP_FREEZE_DRIFT')
            budget = admission(native, 1)
            journal.intent('cold', {'request_id': data['config']['task_id'] + '-cold-reopen', 'budget': budget})
            cold = run_cold(data, budget, graph)
            journal.done('cold', cold)
            state = native.check()
            tickets = native.snapshot()['tickets']
            limits = data['limits']
            if (state['dcc_starts'] != limits['starts'] or state['total_seconds'] > limits['total_seconds']
                    or any(t['stopped_at'] is None or t['charged_seconds'] > native.role_seconds(t['role'])
                           for t in tickets)):
                raise ValueError('HIP_FINAL_BUDGET_INVALID')
            final_state = 'SOFTWARE_TEST_PASSED' if software_test else 'HIP_NATIVE_PASSED'
            result = {'schema': 'bridge.hip-diagnostic.result/1', 'state': final_state,
                'evidence_source': source, 'scope': native.binding, 'freeze': data['freeze_record'],
                'graph': graph, 'cold': cold, 'budget': state,
                'os_image': 'NOT_OBSERVED', 'production_identity': 'NOT_RUN',
                'render': 'NOT_RUN', 'alpha': 'NOT_RUN', 'nuke': 'NOT_RUN', 'visual': 'NOT_RUN'}
        except BaseException as error:
            native.fail('HIP_DIAGNOSTIC_FAILED_CLOSED')
            journal.value['terminal'] = {'state': 'FAILED_CLOSED', 'error': type(error).__name__, 'message': str(error)}
            journal.save()
            raise
        native.fail('HIP_DIAGNOSTIC_TERMINAL_CLOSED')
        journal.value['terminal'] = {'state': final_state}
        journal.save()
        result['closed_budget'] = native.snapshot()
        write(data['root'] / 'result.json', result)
        return result


def execute(scope_path):
    return _execute(scope_path)


def execute_software_test(scope_path):
    """Explicit software harness; only bottom native/transport/process APIs may be stubbed."""
    return _execute(scope_path, software_test=True)


def verify_receipts(scope_path):
    """Offline local verification needs original HMAC keys; never export them."""
    data = frozen_data(scope_path, require_frozen=True)
    _activation(data)
    state = data['native'].snapshot()
    outcomes = []
    for ticket in state['tickets']:
        start = owned_process.read_receipt(ticket['directory'], 'started', identity=ticket['identity'])
        stop = owned_process.read_receipt(ticket['directory'], 'stopped', identity=ticket['identity'])
        if not start or not stop:
            raise ValueError('HIP_SIGNED_STOP_UNPROVEN')
        outcomes.append({'role': ticket['role'], 'pid': start['pid'],
            'execution_returncode': owned_process.execution_returncode(stop),
            'observed_by': stop['observed_by']})
    return {'schema': 'bridge.hip-diagnostic.local-receipt-verification/1',
        'verified_signed_pairs': len(outcomes), 'outcomes': outcomes, 'dcc_starts': state['dcc_starts'],
        'closed_reason': state['closed_reason'], 'native_execution_status': 'NOT_RUN',
        'method': 'frozen_source_HMAC_original_local_keys', 'keys_exported': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for name in ('output-root', 'plan', 'hython', 'supervisor-python', 'ocio-config'):
        prep.add_argument('--' + name, required=True)
    prep.add_argument('--resource-profile', choices=(HIP_RESOURCE_PROFILE,), default=None)
    activation = sub.add_parser('activate')
    for name in ('scope', 'review', 'authorization', 'output-root'):
        activation.add_argument('--' + name, required=True)
    for name in ('preflight', 'execute', 'verify-receipts'):
        sub.add_parser(name).add_argument('--scope', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.output_root, plan=args.plan, hython=args.hython,
                supervisor_python=args.supervisor_python, ocio_config=args.ocio_config,
                resource_profile=args.resource_profile)
        elif args.command == 'activate':
            result = activate(args.scope, review_path=args.review, authorization_path=args.authorization,
                              output_root=args.output_root)
        elif args.command == 'preflight':
            result = preflight(args.scope)
        elif args.command == 'verify-receipts':
            result = verify_receipts(args.scope)
        else:
            result = execute(args.scope)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get('state') != 'BLOCKED' else 2
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'state': 'BLOCKED', 'blocker': str(error), 'native_execution_status':
            'ATTEMPTED_FAILED_CLOSED' if args.command == 'execute' else 'NOT_RUN'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
