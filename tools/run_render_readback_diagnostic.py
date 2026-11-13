#!/usr/bin/env python3
"""One reviewed read-only H21 composed-render-settings readback diagnostic.

Opens an already registered, byte-verified task HIP in a supervised hython,
composes the LOP stage at frame 1 and dumps the composed RenderSettings
configuration verbatim.  It never renders, never saves the HIP and never
writes inside the task tree.  Preparation and preflight never dispatch native
processes; activation is an explicit trusted-controller action bound to an
independent review and the user's recorded conditional instruction.
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / 'tools'))
PACKAGES = ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')
for _package in PACKAGES:
    sys.path.insert(0, str(ROOT / 'packages' / _package / 'src'))
import run_hip_diagnostic as hip_tool
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.graph_scheduler import GraphScheduler
from dcc_task_runtime import owned_process
from houdini_bridge.operation_receipts import validate_scene_contract_header

# The diagnostic is bounded harder than the outer scope budget: one hython
# start, 120 seconds, no rendering.  The scope schema keeps the standard
# outer budget; this tool refuses any second start or any overtime itself.
LIMITS = {'starts': 1, 'total_seconds': 120, 'per_start_seconds': 120,
          'max_bytes': 536870912, 'jobs': 1, 'retries': 0, 'stop_reserve_seconds': 10}
TASK_ID = 'render-readback-h21-20261026'
TOOLS = ('render_readback_host.py', 'run_render_readback_diagnostic.py',
         'run_controlled_engineering.py', 'run_hip_diagnostic.py')
AUTHORITY = 'current_user_conditional_instruction'
INSTRUCTION = '你全都可以做，做过的记得写下到文档一起提交'


def source_paths(repo):
    paths = []
    for package in PACKAGES:
        paths.extend((repo / 'packages' / package / 'src').rglob('*.py'))
    paths.extend(p for p in (repo / 'plugins/houdini').rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
    paths.append(repo / 'plugins/nuke/nuke_bridge_addon.py')
    paths += [repo / 'tools' / name for name in TOOLS]
    for path in paths:
        hip_tool.plain(path)
    return sorted(set(paths))


def source_manifest(repo):
    return {str(p.relative_to(repo)): hip_tool.record(p)['sha256'] for p in source_paths(repo)}


def save_entry(store_path, hip_record, contract_digest):
    store = hip_tool.load(store_path)
    matches = [item for item in store.get('saves', [])
               if item.get('path') == hip_record['path'] and item.get('sha256') == hip_record['sha256']
               and item.get('scene_contract_sha256') == contract_digest]
    if len(matches) != 1:
        raise ValueError('RENDER_READBACK_SAVE_ENTRY_INVALID')
    return matches[0]


def _initialize(root, config, plan, sources, source_repo, *, authorized=False, activation=None):
    root = hip_tool.plain(root)
    if root.exists() or not root.parent.is_dir():
        raise ValueError('RENDER_READBACK_FRESH_ROOT_REQUIRED')
    root.mkdir(mode=0o700)
    frozen = root / 'control/snapshot'
    for relative, digest in sources.items():
        source = source_repo / relative
        if hip_tool.record(source)['sha256'] != digest:
            raise ValueError('RENDER_READBACK_SOURCE_DRIFT')
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    copied_plan = root / 'plan.md'
    shutil.copyfile(hip_tool.checked(plan), copied_plan)
    config_record = hip_tool.write(root / 'configuration.json', config)
    freeze = {'schema': 'bridge.render-readback.freeze/1', 'sources': sources,
              'plan': hip_tool.record(copied_plan), 'configuration': config_record,
              'limits': dict(LIMITS), 'evidence_source': config['evidence_source']}
    freeze_record = hip_tool.write(root / 'freeze.json', freeze)
    key = secrets.token_bytes(32)
    scope = {'schema': 'bridge.engineering-closure-scope/1', 'scope_id': 'render-readback-' + uuid.uuid4().hex,
             'output_root': str(root), 'execution_authorized': authorized,
             'status': 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION' if authorized else 'PREPARED_NOT_AUTHORIZED',
             'budget': {'per_operation_seconds': 120, 'total_seconds': 600, 'max_dcc_starts': 8,
                        'max_disk_bytes': 536870912, 'max_heavy_operations': 1, 'automatic_retries': 0},
             'hosts': config['hosts'], 'versions': {'houdini': '21.0.631'},
             'project_color': {'working_space': 'ACEScg', 'source': 'user_confirmed'},
             'evidence_source': config['evidence_source'],
             'accounting': {'key_path': str(root / '.native-control/key'),
                            'key_sha256': hashlib.sha256(key).hexdigest()}}
    if activation:
        scope['activation_review'] = activation['review']
    scope_record = hip_tool.write(root / 'scope.json', scope)
    native = NativeScope.initialize(hip_tool.binding(scope_record['path']), key=key)
    if activation:
        hip_tool.write(root / 'activation.json', native._envelope({**activation,
            'scope': native.binding, 'freeze': freeze_record,
            'schema': 'bridge.render-readback.activation/1'}))
    return {'scope': native.binding, 'freeze': freeze_record, 'state': scope['status'],
            'native_execution_status': 'NOT_RUN', 'dcc_starts': native.snapshot()['dcc_starts']}


def prepare(root, *, plan, hip, contract_store, contract_sha256, hython, supervisor_python,
            ocio_config, evidence_source='real_host'):
    if evidence_source not in ('real_host', 'software_test'):
        raise ValueError('RENDER_READBACK_EVIDENCE_SOURCE_INVALID')
    hosts = {'hython': hip_tool.record(hython), 'supervisor_python': hip_tool.record(supervisor_python)}
    if evidence_source == 'real_host' and ('Houdini21.0.631' not in hosts['hython']['path']
                                           or Path(hosts['hython']['path']).name != 'hython'):
        raise ValueError('RENDER_READBACK_H21_EXECUTABLE_REQUIRED')
    if 'python' not in Path(hosts['supervisor_python']['path']).name.lower():
        raise ValueError('RENDER_READBACK_PLAIN_SUPERVISOR_REQUIRED')
    hip_record = hip_tool.record(hip)
    store_record = hip_tool.record(contract_store)
    entry = save_entry(store_record['path'], hip_record, contract_sha256)
    contract = entry.get('scene_contract')
    if not isinstance(contract, dict) or not isinstance(contract.get('nodes'), list):
        raise ValueError('RENDER_READBACK_CONTRACT_INVALID')
    try:
        validate_scene_contract_header(contract, task_id=str(contract.get('task_id') or ''))
    except ValueError as error:
        raise ValueError('RENDER_READBACK_CONTRACT_INVALID') from error
    roles = {node.get('role'): node.get('path') for node in contract['nodes']}
    render_path, settings_path = roles.get('render'), roles.get('settings')
    if not render_path or not settings_path:
        raise ValueError('RENDER_READBACK_ROLES_MISSING')
    inputs = {'hip': hip_record, 'contract_store': store_record,
              'contract_sha256': contract_sha256,
              'render_role': render_path, 'settings_role': settings_path,
              'execution_root': contract['execution_root'],
              'source_scope_sha256': entry.get('scope_sha256')}
    config = {'task_id': TASK_ID, 'hosts': hosts, 'inputs': inputs,
              'ocio_config': hip_tool.record(ocio_config), 'evidence_source': evidence_source}
    return _initialize(root, config, hip_tool.record(plan), source_manifest(ROOT), ROOT)


def frozen_data(scope_path, *, require_frozen=False):
    native = NativeScope(hip_tool.binding(scope_path))
    root = native.root
    freeze_record = hip_tool.record(root / 'freeze.json')
    freeze = hip_tool.load(freeze_record['path'])
    config = hip_tool.load(hip_tool.checked(freeze['configuration']))
    frozen = root / 'control/snapshot'
    if (freeze.get('schema') != 'bridge.render-readback.freeze/1' or freeze.get('limits') != LIMITS
            or native.scope['budget']['max_dcc_starts'] != 8
            or config['hosts'] != native.scope['hosts']
            or config['evidence_source'] != freeze['evidence_source']
            or native.scope.get('evidence_source') != freeze['evidence_source']
            or source_manifest(frozen) != freeze['sources']
            or not config['inputs']['render_role'].startswith(config['inputs']['execution_root'] + '/')
            or not config['inputs']['settings_role'].startswith(config['inputs']['execution_root'] + '/')):
        raise ValueError('RENDER_READBACK_FREEZE_DRIFT')
    hip_tool.checked(freeze['plan'])
    for item in [*config['hosts'].values(), config['ocio_config'], config['inputs']['hip'],
                 config['inputs']['contract_store']]:
        hip_tool.checked(item)
    native.validate_host('houdini', '21.0.631', config['hosts']['hython']['path'],
                         config['hosts']['supervisor_python']['path'], allow_missing_writer=True)
    if require_frozen and ROOT != frozen:
        raise ValueError('RENDER_READBACK_FROZEN_ENTRY_REQUIRED')
    return {'native': native, 'root': root, 'freeze': freeze, 'freeze_record': freeze_record,
            'config': config, 'frozen': frozen, 'control': root / 'control', 'limits': LIMITS}


def activate(candidate_scope, *, review_path, authorization_path, output_root):
    """Explicit local controller action; never invoked by prepare or preflight."""
    data = frozen_data(candidate_scope)
    native = data['native']
    state = native.snapshot()
    if native.scope['execution_authorized'] or state['dcc_starts'] or state['closed_reason']:
        raise ValueError('RENDER_READBACK_UNUSED_CANDIDATE_REQUIRED')
    review_record, auth_record = hip_tool.record(review_path), hip_tool.record(authorization_path)
    review, authorization = hip_tool.load(review_path), hip_tool.load(authorization_path)
    target = hip_tool.plain(output_root)
    expected = {'candidate_scope': native.binding, 'candidate_freeze': data['freeze_record'],
                'source_sha256': hashlib.sha256(
                    hip_tool.canonical(data['freeze']['sources'])).hexdigest(),
                'target_root': str(target)}
    if (review.get('schema') != 'bridge.render-readback.review/1' or review.get('decision') != 'APPROVED'
            or any(review.get(k) != v for k, v in expected.items())
            or not isinstance(review.get('reviewer'), str) or not review.get('reviewer')):
        raise ValueError('RENDER_READBACK_INDEPENDENT_REVIEW_REQUIRED')
    if (authorization.get('schema') != 'bridge.render-readback.conditional-authorization/1'
            or authorization.get('authority') != AUTHORITY
            or authorization.get('instruction') != INSTRUCTION or authorization.get('review') != review_record
            or any(authorization.get(k) != v for k, v in expected.items())):
        raise ValueError('RENDER_READBACK_TRUSTED_CONDITIONAL_AUTHORIZATION_REQUIRED')
    return _initialize(target, data['config'], data['freeze']['plan'], data['freeze']['sources'],
                       data['frozen'], authorized=True, activation={'review': review_record,
                           'authorization': auth_record, 'candidate_scope': native.binding,
                           'candidate_freeze': data['freeze_record'],
                           'trusted_action': 'conditional_controller_activation'})


def _activation(data):
    native = data['native']
    value = native._verify_envelope(hip_tool.load(data['root'] / 'activation.json'))
    if (native.scope['execution_authorized'] is not True
            or native.scope['status'] != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or value.get('scope') != native.binding or value.get('freeze') != data['freeze_record']
            or value.get('trusted_action') != 'conditional_controller_activation'
            or value.get('review') != native.scope.get('activation_review')):
        raise ValueError('RENDER_READBACK_ACTIVATION_BINDING_INVALID')
    hip_tool.checked(value['review'])
    hip_tool.checked(value['authorization'])
    return value


def admission(native):
    state = native.snapshot()
    if (state['closed_reason'] or state['dcc_starts'] != 0 or state['tickets']
            or state['disk_bytes'] >= LIMITS['max_bytes'] or state['total_seconds'] >= LIMITS['total_seconds']):
        raise ValueError('RENDER_READBACK_ADMISSION_REFUSED')
    seconds = min(native.role_seconds('houdini-host'),
                  LIMITS['total_seconds'] - state['total_seconds']) - LIMITS['stop_reserve_seconds']
    if seconds <= LIMITS['stop_reserve_seconds']:
        raise ValueError('RENDER_READBACK_STOP_RESERVE_EXHAUSTED')
    return {'roots': [str(native.root)], 'max_bytes': LIMITS['max_bytes'],
            'max_seconds': seconds, 'native_scope': native.binding}


def preflight(scope_path):
    data = frozen_data(scope_path)
    state = data['native'].snapshot()
    blockers = []
    if state['dcc_starts'] or state['closed_reason'] or (data['root'] / 'stages.json').exists():
        blockers.append('RENDER_READBACK_SCOPE_ALREADY_USED')
    if state['disk_bytes'] >= data['limits']['max_bytes']:
        blockers.append('RENDER_READBACK_DISK_BUDGET')
    active = hip_tool.active_native_processes()
    if active:
        blockers.append('RENDER_READBACK_EXISTING_NATIVE_PROCESS')
    if data['native'].scope['execution_authorized']:
        _activation(data)
    return {'schema': 'bridge.render-readback.preflight/1',
            'state': 'BLOCKED' if blockers else 'PREPARED', 'blockers': blockers,
            'scope': data['native'].binding, 'freeze': data['freeze_record'],
            'source_sha256': hashlib.sha256(hip_tool.canonical(data['freeze']['sources'])).hexdigest(),
            'evidence_source': data['config']['evidence_source'], 'dcc_starts': state['dcc_starts'],
            'active_native_processes': active, 'native_execution_status': 'NOT_RUN'}


def validate_dump(dump, config):
    """The dump must carry the composed resolution fact verbatim; no inference."""
    if (not isinstance(dump, dict) or dump.get('schema') != 'bridge.render-readback.dump/1'
            or dump.get('houdini_version') != '21.0.631'
            or dump.get('frame') != 1
            or dump.get('hip_path') != config['inputs']['hip']['path']):
        raise ValueError('RENDER_READBACK_DUMP_HEADER_INVALID')
    prim = dump.get('render_settings_prim') or {}
    if prim.get('typeName') != 'RenderSettings':
        raise ValueError('RENDER_READBACK_DUMP_PRIM_INVALID')
    resolution = (prim.get('attributes') or {}).get('resolution')
    if not isinstance(resolution, dict) or 'value' not in resolution or 'authored' not in resolution:
        raise ValueError('RENDER_READBACK_DUMP_RESOLUTION_MISSING')
    render = dump.get('render_node') or {}
    if render.get('path') != config['inputs']['render_role'] or not render.get('parameters'):
        raise ValueError('RENDER_READBACK_DUMP_RENDER_NODE_INVALID')
    return True


def _host_environment(data, directory, supervisor_identity):
    environment = hip_tool._host_environment(
        {'root': data['root'], 'control': data['control'], 'config': data['config']}, directory,
        supervisor_identity)
    inputs = data['config']['inputs']
    environment.update(RENDER_READBACK_HIP=inputs['hip']['path'],
                       RENDER_READBACK_DUMP=str(directory / 'readback-dump.json'),
                       RENDER_READBACK_RENDER_NODE=inputs['render_role'],
                       RENDER_READBACK_SETTINGS_NODE=inputs['settings_role'])
    return environment


def run_readback(data, budget):
    control, config = data['control'], data['config']
    directory = control / 'readback-host'
    directory.mkdir()
    nonce = uuid.uuid4().hex
    identity = {'task_id': config['task_id'], 'launch_nonce': nonce}
    dump_path = directory / 'readback-dump.json'
    scheduler = GraphScheduler(control / 'scheduler')
    owner, operation = str(directory), config['task_id'] + '-readback'
    deadline = time.monotonic() + data['limits']['total_seconds']
    call_deadline = deadline - data['limits']['stop_reserve_seconds']
    handle = None
    stop = directory / 'stop'
    permit = scheduler.reserve(owner, operation)
    token = permit['token']
    try:
        scheduler.arm(owner, operation, token)
        handle = owned_process.launch([config['hosts']['hython']['path'],
                                       str(data['frozen'] / 'tools/render_readback_host.py')],
            directory=directory / 'owned-supervisor', identity=identity,
            supervisor_executable=config['hosts']['supervisor_python']['path'],
            env=_host_environment(data, directory, identity),
            budget_seconds=data['limits']['per_start_seconds'],
            resource_budget=budget, scope_role='houdini-host', scope_heavy=False)
        tickets = data['native'].snapshot()['tickets']
        selected = [t for t in tickets if t['role'] == 'houdini-host'
                    and t['directory'] == str(directory / 'owned-supervisor') and t['identity'] == identity]
        if len(selected) != 1:
            raise ValueError('RENDER_READBACK_TICKET_UNPROVEN')
        remaining = data['native'].remaining_seconds(selected[0])
        call_deadline = min(call_deadline, time.monotonic() + remaining)
        birth = hip_tool.process_identity(handle.pid)
        birth.pop('state', None)
        if not birth.get('birth'):
            raise ValueError('RENDER_READBACK_BIRTH_MISSING')
        scheduler.bind_process(owner, operation, token, birth)
        while not dump_path.exists():
            if handle.poll() is not None or time.monotonic() >= call_deadline:
                raise ValueError('RENDER_READBACK_DUMP_UNPROVEN')
            time.sleep(.05)
        dump = hip_tool.load(dump_path)
        validate_dump(dump, config)
        stop.write_text('stop\n')
        handle.wait(timeout=max(.01, deadline - time.monotonic()))
        pair = hip_tool.receipt_pair({'directory': str(handle.directory), 'identity': identity})
        scheduler.release(owner, operation, token, stopped=True)
        hip_after = hip_tool.record(config['inputs']['hip']['path'])
        if hip_after != config['inputs']['hip']:
            raise ValueError('RENDER_READBACK_HIP_MODIFIED')
        return {'dump': hip_tool.record(dump_path), 'dump_payload_sha256':
                hashlib.sha256(hip_tool.canonical(dump)).hexdigest(),
                'birth_identity': birth, 'signed_process': pair,
                'hip_after': hip_after, 'readback': 'READ_ONLY'}
    finally:
        if handle is not None:
            if not stop.exists():
                stop.write_text('stop\n')
            try:
                handle.wait(timeout=max(.01, deadline - time.monotonic()))
                hip_tool.receipt_pair({'directory': str(handle.directory), 'identity': identity})
                scheduler.release(owner, operation, token, stopped=True)
            except (ValueError, OSError, subprocess.TimeoutExpired):
                handle.terminate()
                try:
                    handle.wait(timeout=max(.01, deadline - time.monotonic()))
                    hip_tool.receipt_pair({'directory': str(handle.directory), 'identity': identity})
                    scheduler.release(owner, operation, token, stopped=True)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    hip_tool.write(directory / 'stop-unknown.json',
                                   {'state': 'STOP_UNKNOWN', 'scheduler_slot_retained': True,
                                    'operation_id': operation,
                                    'native_execution_status': 'ATTEMPTED_FAILED_CLOSED'})
        elif scheduler.fence_unstarted(owner, operation, token):
            scheduler.release(owner, operation, token, unstarted=True)


def _execute(scope_path):
    data = frozen_data(scope_path, require_frozen=True)
    _activation(data)
    if data['config']['evidence_source'] != 'real_host':
        raise ValueError('RENDER_READBACK_EXECUTION_SOURCE_MISMATCH')
    if Path(sys.executable).resolve() != Path(data['config']['hosts']['supervisor_python']['path']):
        raise ValueError('RENDER_READBACK_FIXED_CONTROLLER_PYTHON_REQUIRED')
    native = data['native']
    journal_path = data['root'] / 'stages.json'
    with execution_lock(journal_path, data['config']['task_id']):
        journal = hip_tool.stage_journal(journal_path, native.binding['sha256'],
                                         data['freeze_record']['sha256'])
        if journal.existing:
            raise ValueError('RENDER_READBACK_EXECUTION_ALREADY_ATTEMPTED')
        try:
            if preflight(scope_path)['state'] != 'PREPARED':
                raise ValueError('RENDER_READBACK_PREFLIGHT_BLOCKED')
            budget = admission(native)
            journal.intent('readback', {'request_id': config_task(data), 'budget': budget})
            with hip_tool.controlled_environment(data):
                readback = run_readback(data, budget)
            journal.done('readback', readback)
            state = native.check()
            tickets = native.snapshot()['tickets']
            if (state['dcc_starts'] != LIMITS['starts'] or state['total_seconds'] > LIMITS['total_seconds']
                    or any(t['stopped_at'] is None for t in tickets)):
                raise ValueError('RENDER_READBACK_FINAL_BUDGET_INVALID')
            result = {'schema': 'bridge.render-readback.result/1', 'state': 'RENDER_READBACK_PASSED',
                      'evidence_source': 'real_host', 'scope': native.binding,
                      'freeze': data['freeze_record'], 'readback': readback, 'budget': state,
                      'render': 'NOT_RUN', 'alpha': 'NOT_RUN', 'nuke': 'NOT_RUN', 'visual': 'NOT_RUN'}
        except BaseException as error:
            native.fail('RENDER_READBACK_FAILED_CLOSED')
            journal.value['terminal'] = {'state': 'FAILED_CLOSED', 'error': type(error).__name__,
                                         'message': str(error)}
            journal.save()
            raise
        native.fail('RENDER_READBACK_DIAGNOSTIC_TERMINAL_CLOSED')
        journal.value['terminal'] = {'state': 'RENDER_READBACK_PASSED'}
        journal.save()
        result['closed_budget'] = native.snapshot()
        hip_tool.write(data['root'] / 'result.json', result)
        return result


def config_task(data):
    return data['config']['task_id'] + '-readback'


def execute(scope_path):
    return _execute(scope_path)


def verify_receipts(scope_path):
    data = frozen_data(scope_path, require_frozen=True)
    _activation(data)
    state = data['native'].snapshot()
    outcomes = []
    for ticket in state['tickets']:
        start = owned_process.read_receipt(ticket['directory'], 'started', identity=ticket['identity'])
        stop = owned_process.read_receipt(ticket['directory'], 'stopped', identity=ticket['identity'])
        if not start or not stop:
            raise ValueError('RENDER_READBACK_SIGNED_STOP_UNPROVEN')
        outcomes.append({'role': ticket['role'], 'pid': start['pid'],
                         'execution_returncode': owned_process.execution_returncode(stop),
                         'observed_by': stop['observed_by']})
    return {'schema': 'bridge.render-readback.local-receipt-verification/1',
            'verified_signed_pairs': len(outcomes), 'outcomes': outcomes,
            'dcc_starts': state['dcc_starts'], 'closed_reason': state['closed_reason'],
            'method': 'frozen_source_HMAC_original_local_keys', 'keys_exported': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for name in ('output-root', 'plan', 'hip', 'contract-store', 'contract-sha256',
                 'hython', 'supervisor-python', 'ocio-config'):
        prep.add_argument('--' + name, required=True)
    activation = sub.add_parser('activate')
    for name in ('scope', 'review', 'authorization', 'output-root'):
        activation.add_argument('--' + name, required=True)
    for name in ('preflight', 'execute', 'verify-receipts'):
        sub.add_parser(name).add_argument('--scope', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.output_root, plan=args.plan, hip=args.hip,
                             contract_store=args.contract_store, contract_sha256=args.contract_sha256,
                             hython=args.hython, supervisor_python=args.supervisor_python,
                             ocio_config=args.ocio_config)
        elif args.command == 'activate':
            result = activate(args.scope, review_path=args.review,
                              authorization_path=args.authorization, output_root=args.output_root)
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
