#!/usr/bin/env python3
"""同一DiskLight任务的真实Nuke帧入口中断与独立控制端恢复。"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import uuid
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from houdini_bridge.official_karma_observation import file_record, checked_bytes, write_new
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.canonical import canonical_sha256
from continue_official_karma import _runtime_environment, Journal


def load(path):
    """读取本轮已定位的控制文件。"""
    return json.loads(Path(path).read_text(encoding='utf-8'))


def binding(record):
    """原生范围绑定不携带文件大小字段。"""
    return {key: record[key] for key in ('path', 'sha256')}


def stopped_scope(native):
    """在创建唯一后继前将真实停止记账；不清除旧失败原因。"""
    try:
        native.check()
    except ValueError:
        pass
    state = native.snapshot()
    if any(t.get('stopped_at') is None for t in state['tickets']):
        raise ValueError('RECOVERY_PREDECESSOR_STOP_UNCONFIRMED')
    return state


def prepare(source_preparation, delivery_path, namespace, instruction, previous_result=None, previous_scope=None, cold=False):
    """零原生启动准备，后继范围沿同一恢复阶段继承固定额度。"""
    from prepare_workbuddy_graph import prepare_graph
    from nuke_bridge.task_host import input_artifact_registry
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', namespace) or not instruction.strip():
        raise ValueError('RECOVERY_NAMESPACE_AUTHORIZATION_REQUIRED')
    prep_record = file_record(Path(source_preparation).resolve())
    original = json.loads(checked_bytes(prep_record))
    base = NativeScope(original['scope'])
    base_state = stopped_scope(base)
    delivery_record = file_record(Path(delivery_path).resolve())
    delivery = json.loads(checked_bytes(delivery_record))
    source = json.loads(checked_bytes(original['source']))
    registry = input_artifact_registry(source, scope=base, task_id=source['task_id'])
    if (delivery.get('state') != 'FEEDBACK_AND_DOWNSTREAM_COMPLETE'
            or delivery.get('task_id') != source['task_id'] or delivery.get('artifact_version') != 2
            or registry.lookup(source['artifact_id'])['version'] != 2):
        raise ValueError('RECOVERY_COMPLETED_V2_REQUIRED')
    for item in delivery['files'].values():
        checked_bytes(item)
    old_result = None
    previous = base
    if previous_result is not None:
        result_record = file_record(Path(previous_result).resolve())
        old_result = json.loads(checked_bytes(result_record))
        if old_result.get('state') != 'INTERRUPTED_STOPPED':
            raise ValueError('RECOVERY_INTERRUPTED_RESULT_REQUIRED')
        previous = NativeScope(old_result['scope'])
    failed = None
    if previous_scope is not None:
        if old_result is None:
            raise ValueError('RECOVERY_RETRY_ORIGINAL_INTERRUPTION_REQUIRED')
        candidate_record = file_record(Path(previous_scope).resolve())
        candidate = NativeScope(binding(candidate_record))
        if candidate.scope.get('recovery_phase') != previous.scope.get('recovery_phase'):
            raise ValueError('RECOVERY_RETRY_PHASE_CHANGED')
        if cold:
            # 第五票只有宿主启动，原renderer失败事实来自它的直接前驱。
            parent = candidate.scope.get('continuation_of')
            failed = inspect_failed_attempt(NativeScope(binding(parent)))
            if len(stopped_scope(candidate)['tickets']) != len(stopped_scope(NativeScope(binding(parent)))['tickets']) + 1:
                raise ValueError('RECOVERY_COLD_SINGLE_HOST_SOURCE_REQUIRED')
        else:
            failed = inspect_failed_attempt(candidate)
        previous = candidate
    previous_state = stopped_scope(previous)
    root = base.root / 'continuations' / namespace
    if root.exists():
        raise ValueError('RECOVERY_FRESH_NAMESPACE_REQUIRED')
    phase = previous.scope.get('recovery_phase') or {
        'schema': 'bridge.disklight-recovery-phase/1', 'task_id': source['task_id'],
        'prior_scope': file_record(base.path), 'source_preparation': prep_record,
        'source_delivery': delivery_record, 'input_source': original['source'],
        'starts': 6, 'seconds': 600, 'interrupt_request_id': 'disklight_interrupt_' + uuid.uuid4().hex[:12]}
    if phase['source_preparation'] != prep_record or phase['source_delivery'] != delivery_record:
        raise ValueError('RECOVERY_PHASE_BASE_CHANGED')
    key = secrets.token_bytes(32)
    scope = copy.deepcopy(previous.scope)
    for name in ('feedback_phase', 'feedback_nuke_replacement', 'feedback_extra_start_approval'):
        scope.pop(name, None)
    scope.update(scope_id='disklight-recovery-' + uuid.uuid4().hex, host_started=False,
                 recovery_phase=phase, continuation_of=file_record(previous.path),
                 authorization={'authority': 'current_user_instruction', 'instruction': instruction},
                 accounting={'namespace': namespace, 'key_path': str(base.root / '.native-control' / namespace / 'key'),
                             'key_sha256': hashlib.sha256(key).hexdigest()},
                 budget=dict(base.scope['budget'], max_dcc_starts=base.scope['budget']['max_dcc_starts'] + 6,
                             total_seconds=base.scope['budget']['total_seconds'] + 600))
    root.mkdir(parents=True, mode=0o700)
    native = NativeScope.initialize(binding(write_new(root / 'scope.json', scope)), key=key)
    project, control = root / 'project', root / 'project/control'
    (project / 'saves').mkdir(parents=True)
    old_manifest = load(Path(original['control']) / 'run.json')
    hosts = {}
    for kind, name in (('houdini', 'production_host'), ('nuke', 'production_nuke')):
        config = copy.deepcopy(old_manifest[name])
        for item in ('plugin_build', 'controller_root', 'expected_identity', 'port', 'transport', 'host', 'work_dir', 'feedback_ledger_root'):
            config.pop(item, None)
        config.update(native_scope=native.binding,
                      resource_budget={'roots': [str(native.root)], 'max_bytes': scope['budget']['max_disk_bytes'], 'native_scope': native.binding})
        if kind == 'nuke':
            config['input_artifact_source'] = phase['input_source']
        else:
            config['alpha_calibration']['plugin_reuse']['active_plugin']['path'] = str(control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
        hosts[kind] = config
    feedback = load(original['feedback_preparation']['path'])
    config = feedback['configuration']
    construction = [{'index': 0, 'asset_id': 'sealed-official-karma-disklight', 'semantic_role': 'render_scene_configuration',
                     'source_uri': config['path'], 'bytes': config['bytes'], 'sha256': config['sha256']}]
    # 两个宿主必须共用同一调度库，才能核实/释放首段的真实资源槽。
    scheduler = root / 'scheduler' if old_result is None else Path(old_result['scheduler_root'])
    prepare_graph(project, app=None, scheduler_root=scheduler, execution_profile=True, render_profile=True,
                  production_host_config=hosts['houdini'], production_nuke_config=hosts['nuke'], construction_input_manifest=construction)
    result = dict(schema='bridge.disklight-recovery-preparation/1', scope=native.binding, source=phase['input_source'],
                  source_preparation=prep_record, delivery=delivery_record, project=str(project), control=str(control),
                  scheduler_root=str(scheduler), manifest=file_record(control / 'run.json'),
                  snapshot_manifest=file_record(control / 'snapshot-manifest.json'), source_graph=source['source_graph'],
                  environment=_runtime_environment(scope), initial_starts=base_state['dcc_starts'],
                  initial_seconds=base_state['total_seconds'], previous_result=None if old_result is None else result_record,
                  protected_files=delivery['files'])
    if old_result is not None:
        result['operation_owner_continuation'] = continue_operation_owner(old_result, result_record, control, source['task_id'], additional=failed)
        if failed is not None:
            result['failed_attempt'] = write_new(root / 'failed-attempt-source.json', failed)
    if cold:
        if failed is None:
            raise ValueError('RECOVERY_COLD_FAILED_SOURCE_REQUIRED')
        failed_prep = json.loads(checked_bytes(failed['preparation']))
        stages = json.loads(checked_bytes(failed['journal']))['stages']
        old_script = stages['prepare_nuke']['result']['script']
        raw = checked_bytes(old_script).decode('utf-8')
        old_pattern = stages['prepare_nuke']['result']['pattern']
        pattern = str(project / 'saves/recovered.%04d.exr')
        script = project / 'saves/recovered.nk'
        if raw.count(old_pattern) != 2 or raw.count(old_script['path']) != 1:
            raise ValueError('RECOVERY_COLD_EXACT_NK_PATH_REWRITE_REQUIRED')
        raw = raw.replace(old_pattern, pattern).replace(old_script['path'], str(script))
        script.write_text(raw, encoding='utf-8')
        failed_record = load(original_record(previous, failed['operation_id']))
        if file_record(Path(failed_record['script_snapshot']))['sha256'] != old_script['sha256']:
            raise ValueError('RECOVERY_COLD_NATIVE_SNAPSHOT_CHANGED')
        host = load(Path(failed_prep['control']) / 'production-hosts.json')['hosts']['nuke']
        launch = file_record(Path(host['work_dir']) / 'launch.json')
        result['environment']['PYTHONPATH'] = os.pathsep.join(str(control / 'snapshot/packages' / package / 'src')
            for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'))
        result['environment']['PYTHONNOUSERSITE'] = '1'
        result['cold_source'] = write_new(root / 'cold-source.json', {
            'schema': 'bridge.disklight-cold-source/1', 'native_script': old_script,
            'script': file_record(script), 'pattern': pattern, 'host_launch': launch,
            'failed_operation_record': file_record(original_record(previous, failed['operation_id'])),
            'failed_attempt': result['failed_attempt'], 'rewrite': {'old_pattern': old_pattern, 'new_pattern': pattern}})
    record = write_new(root / 'recovery-preparation.json', result)
    return {'preparation': record, 'phase_starts_spent': previous_state['dcc_starts'] - base_state['dcc_starts'],
            'run_command': [scope['hosts']['supervisor_python']['path'], '-I', '-B', str(control / 'snapshot/tools/recover_disklight_nuke.py'),
                            'cold' if cold else 'resume' if old_result is not None else 'interrupt', '--preparation', record['path']]}


def read_mapping(control, operation):
    """只读认证控制端已持久保存的operation映射。"""
    with sqlite3.connect('file:' + str(Path(control) / 'diagnostic.sqlite3') + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT kind,owner,request_id FROM operation_registry WHERE operation_id=?', (operation,)).fetchone()
    if row is None or row[0] != 'nuke-render' or row[1] != 'nuke':
        raise ValueError('RECOVERY_STORED_MAPPING_REQUIRED')
    return {'kind': row[0], 'owner': row[1], 'request_id': row[2]}


def inspect_failed_attempt(native):
    """只有实际失败且全部可信停止的恢复段才能使用剩余固定票据。"""
    from dcc_task_runtime.owned_process import read_receipt, execution_returncode
    state = stopped_scope(native)
    if state['closed_reason'] is None:
        raise ValueError('RECOVERY_RETRY_FAILED_SCOPE_REQUIRED')
    directory = native.path.parent
    prep_record = file_record(directory / 'recovery-preparation.json')
    prep = json.loads(checked_bytes(prep_record))
    journal_record = file_record(directory / 'incremental-state.json')
    stages = json.loads(checked_bytes(journal_record))['stages']
    if prep['scope'] != native.binding or any(stages.get(k, {}).get('state') != 'DONE'
            for k in ('old_operation_query', 'old_query_replay', 'old_slot_released', 'prepare_nuke', 'render')):
        raise ValueError('RECOVERY_RETRY_SOURCE_INCOMPLETE')
    operation = stages['render']['result']['operation_id']
    record = load(original_record(native, operation))
    process = record['process']
    tickets = [t for t in state['tickets'] if t['directory'] == process['supervisor_directory']
               and t['identity'] == process['supervisor_identity'] and t['role'] == 'nuke-render']
    stopped = read_receipt(process['supervisor_directory'], 'stopped', identity=process['supervisor_identity'])
    if (len(tickets) != 1 or stopped is None or execution_returncode(stopped) == 0
            or record.get('owner_task_id') != native.scope['recovery_phase']['task_id']):
        raise ValueError('RECOVERY_RETRY_SIGNED_FAILURE_REQUIRED')
    return {'schema': 'bridge.disklight-failed-recovery-attempt/1', 'scope': file_record(native.path),
            'task_id': record['owner_task_id'], 'preparation': prep_record, 'journal': journal_record,
            'operation_id': operation, 'mapping': read_mapping(prep['control'], operation),
            'boundary_owners': file_record(Path(prep['control']) / 'nuke-state/nuke-operation-owners.json'),
            'stopped_sha256': canonical_sha256(stopped), 'original_interruption': prep['previous_result'],
            'original_terminal': stages['old_operation_query']['result'], 'supervisor': process}


def continue_operation_owner(old_result, result_record, control, task_id, additional=None):
    """认证旧边界原件，只续接指定operation到相同根任务。"""
    authenticated = json.loads(checked_bytes(result_record))
    if authenticated != old_result or authenticated.get('task_id') != task_id:
        raise ValueError('RECOVERY_OLD_RESULT_OWNER_MISMATCH')
    owners = json.loads(checked_bytes(old_result['boundary_owners']))
    operation = old_result['operation_id']
    if owners.get(operation) != task_id:
        raise ValueError('RECOVERY_OLD_BOUNDARY_OWNER_MISMATCH')
    directory = Path(control) / 'nuke-state'
    directory.mkdir(parents=True, exist_ok=True)
    target_owners = {operation: task_id}
    if additional is not None:
        failed_owners = json.loads(checked_bytes(additional['boundary_owners']))
        if additional['task_id'] != task_id or failed_owners.get(additional['operation_id']) != task_id:
            raise ValueError('RECOVERY_FAILED_BOUNDARY_OWNER_MISMATCH')
        target_owners[additional['operation_id']] = task_id
    owner_record = write_new(directory / 'nuke-operation-owners.json', target_owners)
    return write_new(Path(control).parent.parent / 'operation-owner-continuation.json', {
        'schema': 'bridge.nuke-owner-continuation/1', 'source_result': result_record,
        'source_owners': old_result['boundary_owners'], 'destination': owner_record,
        'operation_id': operation, 'task_id': task_id})


@contextmanager
def facade_for(prep):
    """正式GraphRun同任务接线；Houdini边界明确禁用。"""
    from vfx_pipeline.service import ModelSafePipeline, TrustedExecutionControl
    from vfx_pipeline.production_hosts import validate_deployments, ensure_hosts
    from vfx_pipeline.workbuddy_assembly import build_graph_facade, _DeferredTaskBoundary, production_nuke_client
    from vfx_pipeline.official_graph_resume import _snapshot, _VerifiedCompiledGraph, _NoHoudiniContinuation
    from nuke_bridge.task_host import input_artifact_registry
    control = Path(prep['control'])
    if ROOT != control / 'snapshot' or _snapshot(control) != prep['snapshot_manifest']:
        raise ValueError('RECOVERY_PREPARED_SOURCE_REQUIRED')
    manifest = load(control / 'run.json')
    source = json.loads(checked_bytes(prep['source']))
    native = NativeScope(prep['scope'])
    configs = validate_deployments(manifest['production_host'], manifest['production_nuke'], controller_root=control, repo_root=ROOT, application='pipeline')
    hosts = {x['application']: x for x in configs}
    registry = input_artifact_registry(source, scope=native, task_id=source['task_id'])
    pipeline = ModelSafePipeline(Path(source['source_graph']['control']) / 'pipeline.sqlite3')
    def factory():
        _, bound = ensure_hosts(hosts['houdini'], hosts['nuke'], task_id=source['task_id'], controller_root=control,
                                repo_root=ROOT, scheduler_root=Path(prep['scheduler_root']), application='pipeline', host_kinds={'nuke'})
        return production_nuke_client(bound, control / 'nuke-state')
    def detached():
        deployment = control / 'production-hosts.json'
        config = load(deployment).get('hosts', {}).get('nuke') if deployment.exists() else None
        return production_nuke_client(config, control / 'nuke-state') if config else None
    nuke = _DeferredTaskBoundary('nuke', factory, detached)
    f = build_graph_facade(control / 'run.json', trusted_execution=TrustedExecutionControl(pipeline),
        jobs=_VerifiedCompiledGraph(source['source_graph']), task_id=source['task_id'], session_id=manifest['session_id'],
        backend='production', repo_root=ROOT, host_client=_NoHoudiniContinuation(), nuke_client=nuke, registry=registry,
        host_config=hosts['houdini'], nuke_config=hosts['nuke'], save_root=Path(prep['project']) / 'saves')
    f.controller_source = {'manifest_path': str(control / 'run.json'), 'manifest_sha256': prep['manifest']['sha256'],
                          'snapshot_manifest_sha256': prep['snapshot_manifest']['sha256'], 'repo_root': str(ROOT),
                          'backend': 'production', 'software_processes': False}
    yield f


def stop_host(prep):
    """只停止本次部署的宿主；非零停止原样记录，不将预期失败改成成功。"""
    from nuke_bridge.task_host import stop
    p = Path(prep['control']) / 'production-hosts.json'
    if not p.exists():
        return {'started': False}
    host = load(p)['hosts']['nuke']
    if host['native_scope'] != prep['scope']:
        raise ValueError('RECOVERY_HOST_SCOPE_MISMATCH')
    try:
        result = stop(host['work_dir'])
    except ValueError:
        # 普通stop在可信停止后仍拒绝已关闭范围；此处分别记录停止事实和失败原因。
        # 不放宽普通stop，也不把没有签名回执的异常视为已停止。
        from dcc_task_runtime.owned_process import OwnedProcessHandle
        work = Path(host['work_dir'])
        config = load(work / 'launch.json')
        if config['resource_budget']['native_scope'] != prep['scope'] or any(host['expected_identity'].get(k) != v for k, v in config['identity'].items()):
            raise ValueError('RECOVERY_HOST_STOP_IDENTITY_MISMATCH')
        handle = OwnedProcessHandle(work / 'supervisor', config['identity'])
        receipt = handle.receipt()
        state = NativeScope(prep['scope']).snapshot()
        if handle.poll() is None or receipt is None or state['closed_reason'] is None:
            raise
        result = {'stopped': True, 'status': 'STOP_CONFIRMED_CLOSED_SCOPE',
                  'receipt': receipt, 'scope_closed_reason': state['closed_reason']}
    if not result.get('stopped'):
        raise ValueError('RECOVERY_HOST_STOP_UNKNOWN')
    return result


def configure(f, prep, name):
    """使用真实登记v2生成新输出NK，保持原图颜色、通道与精确帧。"""
    source = json.loads(checked_bytes(prep['source']))
    consumed = f.consume_artifact(source['artifact_id'])
    if consumed['registry_operation_receipt']['version'] != 2:
        raise ValueError('RECOVERY_INPUT_VERSION_CHANGED')
    client = f.nuke_client
    pattern = str(Path(prep['project']) / 'saves' / (name + '.%04d.exr'))
    client.call('set_knob', {'node': 'Write1', 'knob': 'file_type', 'value': 'exr'})
    client.render_binding(source['task_id'], pattern, [1], consumed['colorspace'], consumed['premultiplied'], artifact_binding=consumed)
    for key, value in (('channels', 'rgba'), ('metadata', 'all metadata')):
        client.call('set_knob', {'node': 'Write1', 'knob': key, 'value': value})
    script = Path(prep['project']) / 'saves' / (name + '.nk')
    client.call('save_script', {'path': str(script), 'overwrite': False})
    return {'script': file_record(script), 'pattern': pattern, 'input': consumed}


def preflight(path):
    """执行前只读重验，拒绝旧文件漂移及未认证输入。"""
    prep = load(path)
    for name in ('manifest', 'snapshot_manifest', 'source', 'source_preparation', 'delivery'):
        checked_bytes(prep[name])
    for record in prep['protected_files'].values():
        checked_bytes(record)
    return prep


def original_record(native, operation):
    """原生记录只能来自任务统一状态目录。"""
    return native.root / 'state/nuke_renders' / (operation + '.json')


def operation_mapping(f, operation):
    """取已落库映射，保存的是旧operation本身而不是新执行事实。"""
    row = f._lookup_operation(operation)
    if row is None or row['kind'] != 'nuke-render' or row['owner'] != 'nuke':
        raise ValueError('RECOVERY_OPERATION_MAPPING_REQUIRED')
    return row


def assert_released_slot(scheduler_root, operation):
    """释放后保留的SQLite行必须属于该操作且明确处于非占用终态。"""
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    row = GraphScheduler(Path(scheduler_root)).snapshot()
    if (row is None or row.get('active') != 0 or row.get('phase') != 'RELEASED'
            or row.get('operation_id') != operation):
        raise ValueError('RECOVERY_RESOURCE_SLOT_NOT_RELEASED')
    return row


def interrupt(path):
    """第一控制进程：启动真实渲染，命中原生帧入口后正常取消。"""
    from dcc_task_runtime.owned_process import OwnedProcessHandle, read_receipt
    prep = preflight(path)
    root = Path(path).parent
    native = NativeScope(prep['scope'])
    native.check()
    journal = Journal(root, path)
    if journal.value['stages']:
        raise ValueError('RECOVERY_EXISTING_INTENT_QUERY_REQUIRED')
    os.environ.clear()
    os.environ.update(prep['environment'])
    result = None
    try:
        with facade_for(prep) as f:
            prepared = journal.action('prepare_nuke', lambda: configure(f, prep, 'interrupted'))
            request = native.scope['recovery_phase']['interrupt_request_id']
            source = json.loads(checked_bytes(prep['source']))
            launched = journal.action('render', lambda: f.nuke_render_bounded(request, prepared['pattern'], [1], artifact_id=source['artifact_id']))
            operation = launched['operation_id']
            record_path = original_record(native, operation)
            marker = record_path.with_suffix('.interruption.json')
            deadline = time.monotonic() + min(100, native.remaining_seconds())
            while not marker.exists() and time.monotonic() < deadline:
                state = f.operation_query(operation)['operation']
                if state['state'] not in ('RUNNING', 'QUEUED'):
                    raise ValueError('RECOVERY_FRAME_ENTRY_NOT_REACHED:' + state['state'])
                time.sleep(.1)
            observation = load(marker)
            record = load(record_path)
            process = record['process']
            started = read_receipt(process['supervisor_directory'], 'started', identity=process['supervisor_identity'])
            writer = (started or {}).get('writer_process') or {}
            # writer_process结构由签名监督器定义；实际PID同时与启动的直属writer核对。
            writer_pid = writer.get('pid') or (started or {}).get('pid')
            if (observation['operation_id'] != operation or observation['scope'] != prep['scope']
                    or observation['request_id'] != request or observation['frame'] != 1
                    or observation['pid'] != writer_pid or observation['snapshot_sha256'] != process['supervisor_identity']['snapshot_sha256']):
                raise ValueError('RECOVERY_NATIVE_OBSERVATION_IDENTITY_MISMATCH')
            journal.action('native_frame_entry', lambda: {'observation': file_record(marker), 'started_sha256': canonical_sha256(started)})
            mapping = operation_mapping(f, operation)
            journal.action('cancel', lambda: f.operation_cancel(operation))
            handle = OwnedProcessHandle(process['supervisor_directory'], process['supervisor_identity'])
            end = time.monotonic() + 15
            while handle.poll() is None and time.monotonic() < end:
                time.sleep(.05)
            stopped = read_receipt(process['supervisor_directory'], 'stopped', identity=process['supervisor_identity'])
            if stopped is None or stopped.get('stop_reason') != 'CANCEL_REQUESTED':
                raise ValueError('RECOVERY_SIGNED_CANCEL_STOP_REQUIRED')
            try:
                terminal = f.operation_query(operation)
            except Exception as exc:
                terminal = {'reconciliation_required': True, 'error': type(exc).__name__}
            if f.artifact_registry.lookup('nuke-render-' + operation) is not None:
                raise ValueError('RECOVERY_INTERRUPTED_ARTIFACT_REGISTERED')
            result = {'schema': 'bridge.disklight-interruption-result/1', 'state': 'INTERRUPTED_STOPPED',
                'scope': prep['scope'], 'preparation': file_record(Path(path)), 'controller_pid': os.getpid(),
                'task_id': source['task_id'], 'operation_id': operation, 'mapping': mapping,
                'mapping_sha256': canonical_sha256(mapping), 'observation': file_record(marker),
                'supervisor': process, 'stopped_sha256': canonical_sha256(stopped), 'terminal': terminal,
                'scheduler_root': prep['scheduler_root'], 'prepared': prepared,
                'boundary_owners': file_record(Path(prep['control']) / 'nuke-state/nuke-operation-owners.json')}
    finally:
        cleanup = stop_host(prep)
        write_new(root / 'host-stop.json', cleanup)
    if result is not None:
        result['native_scope'] = stopped_scope(native)
        result['old_record'] = file_record(original_record(native, result['operation_id']))
        record = write_new(root / 'interruption-result.json', result)
        print(json.dumps({'state': result['state'], 'result': record['path']}, ensure_ascii=False), flush=True)


def resume(path):
    """第二独立控制进程：认证旧映射与可信停止，只续尚未完成的Nuke渲染。"""
    from houdini_bridge.official_karma import compare_files
    prep = preflight(path)
    previous = json.loads(checked_bytes(prep['previous_result']))
    if previous['controller_pid'] == os.getpid():
        raise ValueError('RECOVERY_INDEPENDENT_CONTROLLER_REQUIRED')
    old_prep = json.loads(checked_bytes(previous['preparation']))
    old_record = json.loads(checked_bytes(previous['old_record']))
    old_operation = previous['operation_id']
    expected = read_mapping(old_prep['control'], old_operation)
    if expected != previous['mapping'] or canonical_sha256(expected) != previous['mapping_sha256']:
        raise ValueError('RECOVERY_OLD_MAPPING_CHANGED')
    native = NativeScope(prep['scope'])
    native.check()
    root = Path(path).parent
    journal = Journal(root, path)
    if journal.value['stages']:
        raise ValueError('RECOVERY_EXISTING_INTENT_QUERY_REQUIRED')
    os.environ.clear()
    os.environ.update(prep['environment'])
    result = None
    try:
        with facade_for(prep) as f:
            # 只续接已认证映射；仍由原生插件读取旧记录和签名监督器事实。
            f._register_operation(old_operation, expected['kind'], expected['owner'], expected['request_id'])
            failed = json.loads(checked_bytes(prep['failed_attempt'])) if 'failed_attempt' in prep else None
            if failed is None:
                terminal = journal.action('old_operation_query', lambda: f.operation_query(old_operation))
            else:
                # 成功的原中断查询沿认证前缀复用，失败的后继必须由正常接口新查询。
                checked_bytes(failed['preparation'])
                checked_bytes(failed['journal'])
                terminal = failed['original_terminal']
                failed_prep = json.loads(checked_bytes(failed['preparation']))
                mapping = read_mapping(failed_prep['control'], failed['operation_id'])
                if mapping != failed['mapping']:
                    raise ValueError('RECOVERY_FAILED_MAPPING_CHANGED')
                f._register_operation(failed['operation_id'], mapping['kind'], mapping['owner'], mapping['request_id'])
                failed_terminal = journal.action('failed_operation_query', lambda: f.operation_query(failed['operation_id']))
                observed = failed_terminal['operation']
                if observed['state'] != 'FAILED' or observed.get('stop_confirmed') is not True or observed.get('slot_released') is not True:
                    raise ValueError('RECOVERY_FAILED_ATTEMPT_NOT_STOPPED_RELEASED')
                journal.action('failed_slot_released', lambda: assert_released_slot(prep['scheduler_root'], failed['operation_id']))
                if f.artifact_registry.lookup('nuke-render-' + failed['operation_id']) is not None:
                    raise ValueError('RECOVERY_FAILED_OUTPUT_REGISTERED')
            old = terminal['operation']
            if (old['state'] != 'CANCELLED' or old.get('stop_confirmed') is not True or old.get('slot_released') is not True):
                raise ValueError('RECOVERY_OLD_OPERATION_NOT_CANCELLED_STOPPED_RELEASED')
            if f.artifact_registry.lookup('nuke-render-' + old_operation) is not None:
                raise ValueError('RECOVERY_INTERRUPTED_ARTIFACT_REGISTERED')
            if failed is None:
                journal.action('old_query_replay', lambda: f.operation_query(old_operation))
                journal.action('old_slot_released', lambda: assert_released_slot(prep['scheduler_root'], old_operation))
            prepared = journal.action('prepare_nuke', lambda: configure(f, prep, 'recovered'))
            source = json.loads(checked_bytes(prep['source']))
            request = 'disklight_recover_' + hashlib.sha256(prep['scope']['sha256'].encode()).hexdigest()[:12]
            launched = journal.action('render', lambda: f.nuke_render_bounded(request, prepared['pattern'], [1], artifact_id=source['artifact_id']))
            operation = launched['operation_id']
            end = time.monotonic() + min(115, native.remaining_seconds())
            while time.monotonic() < end:
                state = f.operation_query(operation)['operation']
                if state['state'] == 'COMPLETED':
                    break
                if state['state'] not in ('RUNNING', 'QUEUED'):
                    raise ValueError('RECOVERY_RENDER_FAILED:' + state['state'])
                time.sleep(.1)
            else:
                raise TimeoutError('RECOVERY_RENDER_TIMEOUT')
            journal.action('render_completed', lambda: state)
            before = native.snapshot()['dcc_starts']
            replay = f.nuke_render_bounded(request, prepared['pattern'], [1], artifact_id=source['artifact_id'])
            if replay['operation_id'] != operation or native.snapshot()['dcc_starts'] != before:
                raise ValueError('RECOVERY_REPLAY_DUPLICATED_EXECUTION')
            artifact = f.artifact_registry.lookup('nuke-render-' + operation)
            if artifact is None or artifact['version'] != 1 or not f.artifact_registry.verify(artifact['artifact_id']).get('usable'):
                raise ValueError('RECOVERY_DERIVATIVE_REGISTRATION_REQUIRED')
            comparison = compare_files(load(prep['delivery']['path'])['files']['main_exr']['path'], prepared['pattern'] % 1, require_identical=True)
            if comparison['state'] != 'PASS':
                raise ValueError('RECOVERY_RGBA_MISMATCH')
            if f.artifact_registry.lookup(source['artifact_id'])['version'] != 2:
                raise ValueError('RECOVERY_MAIN_VERSION_CHANGED')
            snapshot = native.root / 'state/nuke_renders' / (operation + '.nk')
            if file_record(snapshot)['sha256'] != prepared['script']['sha256']:
                raise ValueError('RECOVERY_NK_SNAPSHOT_MISMATCH')
            if state.get('stop_confirmed') is not True or state.get('slot_released') is not True:
                raise ValueError('RECOVERY_FINAL_OPERATION_STOP_REQUIRED')
            journal.action('final_slot_released', lambda: assert_released_slot(prep['scheduler_root'], operation))
            result = {'schema': 'bridge.disklight-recovery-result/1', 'state': 'FRAME_ENTRY_RECOVERY_COMPLETE',
                'task_id': source['task_id'], 'scope': prep['scope'], 'preparation': file_record(Path(path)),
                'controller_pid': os.getpid(), 'previous_controller_pid': previous['controller_pid'],
                'interruption': prep['previous_result'], 'failed_attempt': prep.get('failed_attempt'), 'old_operation': old_operation,
                'old_terminal': terminal, 'new_operation': operation, 'artifact': artifact,
                'comparison': comparison, 'replay_operation': replay, 'upstream_reexecuted': False,
                'files': {'nk': prepared['script'], 'exr': file_record(Path(prepared['pattern'] % 1))}}
    finally:
        write_new(root / 'host-stop.json', stop_host(prep))
    if result is not None:
        for record in prep['protected_files'].values():
            checked_bytes(record)
        state = stopped_scope(native)
        if state['closed_reason'] is not None:
            raise ValueError('RECOVERY_FINAL_SCOPE_NOT_SUCCESSFUL')
        result.update(native_scope=state, phase_starts=state['dcc_starts'] - prep['initial_starts'],
                      phase_seconds=state['total_seconds'] - prep['initial_seconds'])
        record = write_new(root / 'recovery-result.json', result)
        print(json.dumps({'state': result['state'], 'result': record['path'], 'phase_starts': result['phase_starts'],
                          'phase_seconds': result['phase_seconds']}, ensure_ascii=False), flush=True)


def cold_request_digest(task):
    """与正式receipt使用完全相同的请求字段，不能用来源清单摘要替代。"""
    request = {'command': task['entry'], 'task_key': task['task_key'], 'node': task['node'],
        'frames': task['frame_set'], 'pattern': task['pattern'], 'input_binding': task['input_binding'],
        'background': task['background'], 'scene': task['scene_fingerprint']}
    for key in ('project_color', 'output_verification'):
        if task.get(key) is not None:
            request[key] = task[key]
    if task.get('input_contract') is not None:
        request['input_contract_sha256'] = canonical_sha256(task['input_contract'])
    return canonical_sha256(request)


def finalize_preparation(path):
    """未执行的准备采用新控制快照和新文件承接，原准备文件保持不可变。"""
    from prepare_workbuddy_graph import prepare_graph
    prep = preflight(path)
    native = NativeScope(prep['scope'])
    state = native.snapshot()
    if state['dcc_starts'] - prep['initial_starts'] != 5 or any(t['stopped_at'] is None for t in state['tickets']):
        raise ValueError('RECOVERY_COLD_FINAL_PREPARATION_NOT_UNUSED')
    root = Path(path).parent
    generation = 1
    while (root / ('final-controller' if generation == 1 else 'final-controller-' + str(generation))).exists():
        generation += 1
    project = root / ('final-controller' if generation == 1 else 'final-controller-' + str(generation))
    control = project / 'control'
    if project.exists():
        raise ValueError('RECOVERY_FINAL_CONTROL_FRESH_REQUIRED')
    manifest = load(prep['manifest']['path'])
    hosts = {}
    for kind, field in (('houdini', 'production_host'), ('nuke', 'production_nuke')):
        config = copy.deepcopy(manifest[field])
        for key in ('plugin_build', 'controller_root', 'expected_identity', 'port', 'transport', 'host', 'work_dir'):
            config.pop(key, None)
        if kind == 'houdini':
            config['alpha_calibration']['plugin_reuse']['active_plugin']['path'] = str(control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
        hosts[kind] = config
    original = load(prep['source_preparation']['path'])
    config = load(original['feedback_preparation']['path'])['configuration']
    construction = [{'index': 0, 'asset_id': 'sealed-official-karma-disklight', 'semantic_role': 'render_scene_configuration',
        'source_uri': config['path'], 'bytes': config['bytes'], 'sha256': config['sha256']}]
    prepare_graph(project, app=None, scheduler_root=Path(prep['scheduler_root']), execution_profile=True, render_profile=True,
        production_host_config=hosts['houdini'], production_nuke_config=hosts['nuke'], construction_input_manifest=construction)
    final = dict(prep, execution_root=str(root / ('cold-execution-' + str(generation))), previous_preparation=file_record(Path(path)), control=str(control),
        manifest=file_record(control / 'run.json'), snapshot_manifest=file_record(control / 'snapshot-manifest.json'))
    final['environment'] = dict(prep['environment'], PYTHONPATH=os.pathsep.join(str(control / 'snapshot/packages' / package / 'src')
        for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')), PYTHONNOUSERSITE='1')
    record = write_new(root / ('recovery-preparation-final.json' if generation == 1 else 'recovery-preparation-final-' + str(generation) + '.json'), final)
    return {'preparation': record, 'native_starts': 0, 'run_command': [native.scope['hosts']['supervisor_python']['path'], '-I', '-B',
        str(control / 'snapshot/tools/recover_disklight_nuke.py'), 'cold', '--preparation', record['path']]}


def cleanup_cold_attempt(native, operation, task, handle, scheduler, permit, unstarted=False):
    """启动/晚到绑定/登记所有异常共用停止路径；停止不明保持资源槽。"""
    from dcc_task_runtime import owned_process
    if handle is not None:
        if handle.poll() is None:
            handle.terminate()
            handle.wait(timeout=8)
        return
    if unstarted or task is None or not task.get('supervisor_intent'):
        fenced = scheduler.fence_unstarted(permit['owner_root'], operation, permit['token'])
        if not fenced and unstarted is True and (native.root / 'geometry-prelaunch-tail-authorization.json').is_file():
            from vfx_pipeline.geometry_prelaunch_tail import validate_unstarted_attempt
            # DISPATCHING只能凭047原件与当前未准入事实在同一SQLite锁内封口，未知仍持槽。
            scheduler._fence_verified_prelaunch_dispatch(permit['owner_root'], operation, permit['token'], permit['generation'],
                lambda row: validate_unstarted_attempt(native, operation, task, permit, row))
        scheduler.release(permit['owner_root'], operation, permit['token'], unstarted=True)
        return
    intent = task['supervisor_intent']
    expected = native.root / 'state/nuke_renders' / (operation + '.supervisor')
    if Path(intent['directory']) != expected or intent['identity'].get('operation_id') != operation:
        raise ValueError('RECOVERY_COLD_CLEANUP_IDENTITY_MISMATCH')
    owned_process._atomic(expected / 'cancel.json', {'identity': intent['identity']})
    end = time.monotonic() + 8
    while time.monotonic() < end:
        stopped = owned_process.read_receipt(expected, 'stopped', identity=intent['identity'])
        if stopped is not None:
            return
        time.sleep(.05)
    raise RuntimeError('RECOVERY_COLD_STOP_UNCONFIRMED_SLOT_HELD')


def cold_run(path):
    """复用原生NK和认证输入，最后一票独立冷渲染；实际回执完成后才形成事实。"""
    import importlib.util
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    from dcc_task_runtime import owned_process
    from nuke_bridge.task_host import input_artifact_registry
    from houdini_bridge.official_karma import compare_files
    prep = preflight(path)
    from vfx_pipeline.official_graph_resume import _snapshot
    if ROOT != Path(prep['control']) / 'snapshot' or _snapshot(Path(prep['control'])) != prep['snapshot_manifest']:
        raise ValueError('RECOVERY_COLD_PREPARED_SOURCE_REQUIRED')
    cold = json.loads(checked_bytes(prep['cold_source']))
    failed = json.loads(checked_bytes(cold['failed_attempt']))
    checked_bytes(cold['script'])
    checked_bytes(cold['native_script'])
    old_record = json.loads(checked_bytes(cold['failed_operation_record']))
    old_launch = json.loads(checked_bytes(cold['host_launch']))
    native = NativeScope(prep['scope'])
    native.check()
    if native.snapshot()['dcc_starts'] - prep['initial_starts'] != 5:
        raise ValueError('RECOVERY_COLD_FINAL_TICKET_REQUIRED')
    os.environ.clear()
    os.environ.update(prep['environment'])
    # 此真实旧宿主配置只提供已认证颜色/输入上下文，不重连或启动旧宿主。
    for key in ('PYTHONEXECUTABLE', 'PYTHONHOME'):
        os.environ.pop(key, None)
    os.environ['BRIDGE_NUKE_HOST_CONFIG'] = cold['host_launch']['path']
    os.environ['BRIDGE_NUKE_HOST_CONFIG_SHA256'] = cold['host_launch']['sha256']
    spec = importlib.util.spec_from_file_location('cold_nuke_receipts', ROOT / 'plugins/nuke/nuke_bridge_addon.py')
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon._RENDER_RECORDS_DIR = native.root / 'state/nuke_renders'
    addon._NUKE_SCHEDULER = GraphScheduler(Path(prep['scheduler_root']))
    source = json.loads(checked_bytes(prep['source']))
    os.environ['BRIDGE_ARTIFACT_LEDGER_ROOT'] = source['producer_ledger']
    registry = input_artifact_registry(source, scope=native, task_id=source['task_id'], fallback=addon._nuke_operation_fact)
    addon._NUKE_ARTIFACT_REGISTRY = registry
    journal_root = Path(prep.get('execution_root', Path(path).parent))
    journal_root.mkdir(parents=True, exist_ok=True)
    journal = Journal(journal_root, path)
    if journal.value['stages']:
        raise ValueError('RECOVERY_COLD_EXISTING_INTENT_QUERY_REQUIRED')
    terminal = journal.action('failed_operation_query', lambda: addon.nuke_render_status(failed['operation_id']))
    if terminal['state'] != 'FAILED' or terminal.get('stop_confirmed') is not True or not terminal.get('slot_released'):
        raise ValueError('RECOVERY_COLD_FAILED_STOP_RELEASE_REQUIRED')
    assert_released_slot(prep['scheduler_root'], failed['operation_id'])
    if registry.lookup('nuke-render-' + failed['operation_id']) is not None:
        raise ValueError('RECOVERY_COLD_FAILED_OUTPUT_REGISTERED')
    # 不从旧记录继承任何完成、进度、停止或原生输出读回事实，只复用认证输入合同。
    request = 'disklight_cold_' + prep['scope']['sha256'][:12]
    operation = 'nrend-' + hashlib.sha256(request.encode()).hexdigest()[:16]
    pattern = cold['pattern']
    script = Path(cold['script']['path'])
    output = Path(pattern % 1)
    if output.exists() or original_record(native, operation).exists():
        raise ValueError('RECOVERY_COLD_FRESH_OPERATION_REQUIRED')
    task_id = source['task_id']
    from nuke_bridge.operation_receipts import validate_registered_input_contract
    validate_registered_input_contract(old_record['input_contract'])
    if old_record['owner_task_id'] != task_id or old_record['frame_set'] != [1]:
        raise ValueError('RECOVERY_COLD_SOURCE_OWNER_FRAMES_INVALID')
    owner_root = 'nuke:' + str(script)
    route = addon.configure_nuke_background_route(nuke_executable=native.scope['hosts']['nuke']['path'],
        worker_script=str(ROOT / 'tools/nuke_owned_render_worker.py'), supervisor_executable=native.scope['hosts']['supervisor_python']['path'],
        software_api=False, resource_budget={'roots': [str(native.root)], 'max_bytes': native.scope['budget']['max_disk_bytes'], 'native_scope': native.binding})
    handle = None
    task = None
    permit = None
    definitely_unstarted = False
    try:
        permit = addon._NUKE_SCHEDULER.reserve(owner_root, operation)
        snapshot = addon._snapshot_nuke_script(operation, str(script))
        scene = cold['script']['sha256']
        task = {'task_id': operation, 'owner_task_id': task_id, 'request_id': request,
            'request_sha256': None,
            'entry': 'render_write', 'task_key': 'render_write', 'node': 'Write1', 'background': True,
            'frame_range': [1, 1], 'frame_set': [1], 'stride': 1, 'active_frames': [1],
            'pattern': pattern, 'scene_fingerprint': scene, 'script_snapshot': snapshot,
            'input_contract': old_record['input_contract'], 'input_binding': old_record['input_binding'],
            'output_verification': old_record['output_verification'], 'project_color': old_record['project_color'],
            'dependencies': [scene] + list(old_record['input_binding'].get('dependencies', [])),
            'delivery_confirmations': {'colorspace_confirmed': True, 'premultiplied_confirmed': True, 'dependencies_confirmed': True},
            'started_at_epoch': time.time(), 'cancel_requested': False, 'cancel_requested_at': None,
            'stop_confirmed_at': None, 'state': 'RUNNING', 'background_backend': 'owned', 'budget_seconds': 120,
            'colorspace': old_record['colorspace'], 'premultiplied': old_record['premultiplied'],
            'cold_preparation': file_record(Path(path)), 'scene_identity_basis': 'authenticated_nk_bytes_sha256',
            'slot': {'owner_root': owner_root, 'operation_id': operation, 'token': permit['token'], 'generation': permit['generation']}}
        task['request_sha256'] = cold_request_digest(task)
        addon._RENDERS[operation] = task
        addon._persist_render_record(task)
        addon._NUKE_SCHEDULER.arm(owner_root, operation, permit['token'])
        journal.action('launch_intent', lambda: {'operation_id': operation, 'record': file_record(original_record(native, operation)), 'script': cold['script']})
        try:
            identity = addon._launch_owned_render_subprocess(operation, snapshot, 'Write1', 1, 1, pattern=pattern, route=route, frame_set=[1], budget_seconds=120)
            task['process'] = {k: v for k, v in identity.items() if k != 'handle'}
            handle = identity['handle']
        except Exception as error:
            if getattr(error, 'started', None) is False:
                definitely_unstarted = True
                raise
            # 启动未知只能查同一持久意图，绝不重发。签名started若迟到仍属这一次启动。
            end = time.monotonic() + min(40, native.remaining_seconds())
            intent = task.get('supervisor_intent')
            if not intent:
                raise
            while time.monotonic() < end:
                try:
                    handle = owned_process.OwnedProcessHandle(intent['directory'], intent['identity'])
                    break
                except (OSError, ValueError):
                    time.sleep(.05)
            else:
                raise RuntimeError('RECOVERY_COLD_START_UNCONFIRMED')
            task['process'] = {'pid': handle.pid, 'kind': 'owned_render_subprocess',
                'supervisor_directory': intent['directory'], 'supervisor_identity': intent['identity'],
                **{key: intent[key] for key in ('argv', 'argv0', 'worker_result', 'worker_script')}}
        task.update(backend='owned_subprocess', dispatch_state='launched')
        addon._RENDER_HANDLES[operation] = handle
        addon._NUKE_SCHEDULER.bind_process(owner_root, operation, permit['token'], task['process'])
        addon._persist_render_record(task)
        end = time.monotonic() + min(120, native.remaining_seconds())
        try:
            while handle.poll() is None and time.monotonic() < end:
                time.sleep(.1)
            receipt = handle.receipt()
            if receipt is None or owned_process.execution_returncode(receipt) != 0 or receipt.get('stop_reason') is not None:
                raise ValueError('RECOVERY_COLD_SUCCESSFUL_STOP_REQUIRED')
            # 输出设置只来自这次真实worker读回，旧记录不提供新执行事实。
            worker = addon._verify_owned_worker_receipt(task)
            actual = worker['write_readback']['settings']
            if actual != {'file': pattern, 'colorspace': 'ACEScg', 'premultiplied': True, 'raw': False}:
                raise ValueError('RECOVERY_COLD_ACTUAL_WRITE_SETTINGS_MISMATCH')
            task['native_output_settings'] = {'origin': 'nuke_write_readback', 'class': 'Write', 'node': 'Write1',
                'pattern': actual['file'], 'scene_fingerprint': scene, 'colorspace': actual['colorspace'],
                'premultiplied': actual['premultiplied'], 'raw': actual['raw'], 'operation_id': operation, 'request_id': request}
            task['cold_worker_readback_sha256'] = canonical_sha256(worker)
            addon._persist_render_record(task)
            completed = journal.action('completion', lambda: addon.nuke_render_status(operation))
            if completed['state'] != 'COMPLETED' or completed.get('ledger_state') != 'REGISTERED' or not completed.get('slot_released'):
                raise ValueError('RECOVERY_COLD_COMPLETION_REGISTRATION_REQUIRED')
            count = native.snapshot()['dcc_starts']
            replay = addon.nuke_render_status(operation)
            if replay['state'] != 'COMPLETED' or native.snapshot()['dcc_starts'] != count:
                raise ValueError('RECOVERY_COLD_QUERY_REPLAY_CHANGED_EXECUTION')
            artifact = registry.lookup('nuke-render-' + operation)
            if artifact is None or artifact['version'] != 1 or not registry.verify(artifact['artifact_id']).get('usable'):
                raise ValueError('RECOVERY_COLD_TYPED_ARTIFACT_REQUIRED')
            comparison = compare_files(load(prep['delivery']['path'])['files']['main_exr']['path'], str(output), require_identical=True)
            if comparison['state'] != 'PASS' or registry.lookup(source['artifact_id'])['version'] != 2:
                raise ValueError('RECOVERY_COLD_OUTPUT_OR_MAIN_VERSION_MISMATCH')
            assert_released_slot(prep['scheduler_root'], operation)
            previous = json.loads(checked_bytes(prep['previous_result']))
            state = stopped_scope(native)
            if state['closed_reason'] is not None:
                raise ValueError('RECOVERY_COLD_SCOPE_FAILURE')
            for item in prep['protected_files'].values():
                checked_bytes(item)
            result = {'schema': 'bridge.disklight-recovery-result/1', 'state': 'FRAME_ENTRY_RECOVERY_COMPLETE',
                'task_id': task_id, 'scope': native.binding, 'preparation': file_record(Path(path)),
                'controller_pid': os.getpid(), 'previous_controller_pid': previous['controller_pid'],
                'interruption': prep['previous_result'], 'failed_attempt': prep['failed_attempt'],
                'old_operation': previous['operation_id'], 'old_terminal': failed['original_terminal'],
                'new_operation': operation, 'artifact': artifact, 'comparison': comparison,
                'replay_operation': {'operation_id': operation, 'kind': 'read_only_status', 'state': replay['state']},
                'upstream_reexecuted': False, 'cold_native_script_source': cold['native_script'],
                'files': {'nk': cold['script'], 'exr': file_record(output)}, 'native_scope': state,
                'phase_starts': state['dcc_starts'] - prep['initial_starts'], 'phase_seconds': state['total_seconds'] - prep['initial_seconds']}
            record = write_new(Path(path).parent / 'recovery-result.json', result)
            print(json.dumps({'state': result['state'], 'result': record['path'], 'phase_starts': result['phase_starts'], 'phase_seconds': result['phase_seconds']}, ensure_ascii=False), flush=True)
        finally:
            if handle.poll() is None:
                handle.terminate()
                handle.wait(timeout=5)
    finally:
        if permit is not None:
            cleanup_cold_attempt(native, operation, task, handle, addon._NUKE_SCHEDULER,
                dict(permit, owner_root=owner_root), definitely_unstarted)


def main():
    """准备不启动DCC；真实执行只能从当前准备快照运行。"""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for key in ('source-preparation', 'delivery', 'namespace', 'instruction'):
        p.add_argument('--' + key, required=True)
    p.add_argument('--previous-result')
    p.add_argument('--previous-scope')
    p.add_argument('--cold', action='store_true')
    for name in ('interrupt', 'resume', 'cold', 'finalize-preparation'):
        p = sub.add_parser(name)
        p.add_argument('--preparation', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.source_preparation, args.delivery, args.namespace, args.instruction, args.previous_result, args.previous_scope, args.cold)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'finalize-preparation':
        print(json.dumps(finalize_preparation(Path(args.preparation)), ensure_ascii=False, indent=2))
    else:
        {'interrupt': interrupt, 'resume': resume, 'cold': cold_run}[args.command](Path(args.preparation))
if __name__ == '__main__':
    main()
