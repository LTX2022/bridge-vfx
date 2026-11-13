"""几何任务的原生观测接纳证明：真实查询时签署，交付时只读复核。"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from pathlib import Path
import re

from dcc_task_runtime.native_scope import NativeScope, GEOMETRY_RESOURCE_PROFILE
from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as GEOMETRY_FEEDBACK_PROFILE
from dcc_task_runtime import owned_process
from dcc_task_runtime.platform_support import _owned_path, process_identity
from houdini_bridge.operation_receipts import canonical_sha256, validate_operation_receipt
from houdini_bridge.operation_receipt_store import load_record, record_path
from .production_hosts import _scene_transition_operation_store_path

_SCHEMA = 'bridge.geometry-native-observation-acceptance/1'
_DOMAIN = b'bridge.geometry-native-observation-acceptance/1\x00'
_IDENTITY = ('task_id', 'pid', 'session_id', 'launch_nonce', 'process_generation', 'plugin_build', 'scene_epoch')
_WRAPPERS = {'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent', 'native_evidence'}


def _fail():
    raise ValueError('GEOMETRY_NATIVE_EVIDENCE_INVALID')


def _native(binding, operation_id, phase):
    """严格限定新增几何合同，不能为旧任务签发接纳证明。"""
    native = NativeScope(binding)
    if (native.resource_profile not in (GEOMETRY_RESOURCE_PROFILE, GEOMETRY_FEEDBACK_PROFILE)
            or native.scope.get('scene_profile') != 'bounded_geometry_rig_v1'
            or phase not in {'warm', 'cold'}
            or not isinstance(operation_id, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', operation_id)):
        _fail()
    return native


def _file(path, root):
    """文件记录必须留在本范围，且路径不能经过符号链接。"""
    path = _owned_path(Path(path), Path(root))
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _checked(record, root):
    if not isinstance(record, dict) or set(record) != {'path', 'bytes', 'sha256'}:
        _fail()
    if _file(record['path'], root) != record:
        _fail()


def _signature(native, payload):
    # 不与原生记账envelope共用消息域；此证明声明可信控制器完成了真实查询。
    key = hmac.new(native._key(), _DOMAIN, hashlib.sha256).digest()
    return hmac.new(key, native._canonical(payload), hashlib.sha256).hexdigest()


def _request(saved, task_id, operation_id):
    roles = [node['path'] for node in saved['scene_contract']['nodes'] if node.get('role') == 'source']
    if len(roles) != 1:
        _fail()
    return {'path': roles[0], 'task_id': task_id, 'geometry_observation': True,
            'operation_id': operation_id, 'request_id': operation_id,
            'root_path': saved['scene_contract']['execution_root'], 'frozen_input_manifest': []}


def _saved_hip(saved, native, control, phase):
    path = Path(saved['path'])
    if path.is_relative_to(native.root) or phase != 'cold' or native.resource_profile != GEOMETRY_FEEDBACK_PROFILE:
        return _file(path, native.root)
    from .geometry_feedback import verify_job
    from .geometry_session import _object
    job = _object(control.parents[1] / 'job.json')
    if control != Path(job['directory']) / 'project/control':
        _fail()
    checkpoint = verify_job(job, native).get('checkpoint')
    if checkpoint is None or saved != checkpoint['saved']:
        _fail()
    return checkpoint['hip']


def _receipt(value, saved, native, operation_id, control, phase):
    """重读原生私有producer_record，核对请求、完整结果及未改变的保存场景。"""
    receipt = value.get('operation_receipt')
    validate_operation_receipt(receipt)
    task = native.scope['task_id']
    if (receipt['command'] != 'node.info' or receipt['task_id'] != task
            or receipt['operation_id'] != operation_id or receipt['request_id'] != operation_id
            or receipt['request'] != _request(saved, task, operation_id)
            or value.get('operation_store_format') != 'producer_record'
            or receipt['result'] != {k: v for k, v in value.items() if k not in _WRAPPERS}
            or not isinstance(receipt['result'].get('geometry_observation'), dict)
            or receipt['before_scene'] != receipt['after_scene']):
        _fail()
    scene = receipt['after_scene']
    if (scene['scene_contract'] != saved['scene_contract']
            or scene['scene_contract_sha256'] != canonical_sha256(saved['scene_contract'])
            or scene.get('hip_path') != saved['path'] or scene.get('hip_sha256') != saved['sha256']
            or _saved_hip(saved, native, control, phase)['sha256'] != saved['sha256']):
        _fail()
    runner = _scene_transition_operation_store_path(control, task)
    path = record_path(runner, task, operation_id)
    if value.get('operation_store_path') != str(path) or load_record(runner, task, operation_id) != receipt:
        _fail()
    return receipt, _file(path, native.root)


def _host(native, state, identity, control, *, completed):
    """原生出生/停止回执必须来自同一个已签名记账票据。"""
    matches = [t for t in state['tickets'] if t['role'] == 'houdini-host'
               and t['identity'].get('task_id') == identity['task_id']
               and t['identity'].get('launch_nonce') == identity['launch_nonce']]
    if len(matches) != 1:
        _fail()
    ticket = matches[0]
    directory = _owned_path(Path(ticket['directory']), native.root)
    if directory != control / 'houdini-task-host' / ('supervisor-' + identity['launch_nonce']):
        _fail()
    start = owned_process.read_receipt(directory, 'started', identity=ticket['identity'])
    if (not isinstance(start, dict) or start.get('pid') != identity['pid']
            or start.get('execution_protocol') != 1
            or (start.get('resource_budget') or {}).get('native_scope') != native.binding
            or any(identity.get(k) != v for k, v in ticket['identity'].items())):
        _fail()
    intent_record = _file(directory / 'intent.json', native.root)
    intent = json.loads(Path(intent_record['path']).read_bytes())
    command = intent.get('command')
    if (not isinstance(command, list) or not command
            or command[0] != native.scope['hosts']['hython']['path']
            or canonical_sha256(command) != start.get('argv_sha256')):
        _fail()
    stopped = native._stop(ticket)
    if completed:
        if (ticket['stopped_at'] is None or not stopped
                or owned_process.execution_returncode(stopped) != 0):
            _fail()
    elif ticket['stopped_at'] is not None or stopped is not None:
        _fail()
    return {'ticket_id': ticket['id'], 'directory': str(directory), 'identity': ticket['identity'],
            'started': _file(directory / 'started.json', native.root), 'intent': intent_record}


def _control(native, raw):
    control = _owned_path(Path(raw), native.root)
    relative = control.relative_to(native.root)
    if len(relative.parts) != 4 or relative.parts[0] != 'jobs' or relative.parts[2:] != ('project', 'control'):
        _fail()
    return control


def capture(facade, saved, scope_binding, operation_id, phase, *, transition=None):
    """在真实生产边界执行一次只读几何查询，并签署已认证结果与来源。"""
    native = _native(scope_binding, operation_id, phase)
    client = facade.host_client
    config = client.production_config
    control = _control(native, Path(client.scene_transition_path).parent)
    if (getattr(client, 'backend_kind', None) != 'production'
            or config.get('evidence_source') != 'real_host'
            or config.get('native_scope') != scope_binding
            or config.get('task_root') != str(native.root)
            or config.get('version') != '21.0.631'
            or client.bound_task_id != native.scope['task_id']):
        _fail()
    native.validate_host('houdini', config['version'], config['executable'], config['supervisor_executable'],
                         project_color=config['project_color'], writer=config['writer_executable'])
    before = client._verify_identity()['task_host_identity']
    if before.get('plugin_build') != config.get('plugin_build'):
        _fail()
    if ((phase == 'cold' and (not isinstance(transition, dict)
            or (transition.get('scene_transition') or {}).get('after_identity') != before))
            or (phase == 'warm' and transition is not None)):
        _fail()
    birth = process_identity(before['pid'])
    if birth.get('state') != 'alive' or not birth.get('birth'):
        _fail()
    state = native.snapshot()
    host = _host(native, state, before, control, completed=False)
    value = client.call('node.info', _request(saved, native.scope['task_id'], operation_id))
    after = client._verify_identity()['task_host_identity']
    if (any(before.get(k) != after.get(k) for k in _IDENTITY)
            or process_identity(before['pid']) != birth):
        _fail()
    receipt, stored = _receipt(value, saved, native, operation_id, control, phase)
    if any(receipt['host_identity'].get(k) != before.get(k) for k in _IDENTITY):
        _fail()
    if phase == 'warm' and any(before.get(k) != saved['operation_receipt']['host_identity'].get(k) for k in _IDENTITY):
        _fail()
    # 原装配器检查完整冻结snapshot及addon构建摘要；不是信任请求中自报的来源。
    sources = facade._registry_receipt_sources(receipt)
    if not sources:
        _fail()
    files = [_file(path, native.root) for path in sorted(sources)]
    if any(record['sha256'] != sources[record['path']] for record in files):
        _fail()
    payload = {'schema': _SCHEMA, 'native_scope': scope_binding, 'task_id': native.scope['task_id'],
               'operation_id': operation_id, 'phase': phase, 'control': str(control),
               'saved_scene_id': saved['saved_scene_id'], 'saved_sha256': saved['sha256'],
               'saved_contract_sha256': canonical_sha256(saved['scene_contract']), 'transition': transition,
               'value_sha256': canonical_sha256(value), 'host_identity': before,
               'process_birth': birth, 'host': host, 'producer_record': stored, 'sources': files}
    return {**value, 'native_evidence': {'payload': payload, 'signature': _signature(native, payload)}}


def _verify(value, saved, scope_binding, operation_id, phase, *, transition=None, historical_state=None):
    """宿主已停止时只读复核；不启动宿主，不向输出来历不明的JSON补签。"""
    native = _native(scope_binding, operation_id, phase)
    proof = value.get('native_evidence') if isinstance(value, dict) else None
    if not isinstance(proof, dict) or set(proof) != {'payload', 'signature'}:
        _fail()
    payload = proof['payload']
    if (not isinstance(payload, dict)
            or not hmac.compare_digest(str(proof['signature']), _signature(native, payload))
            or payload.get('schema') != _SCHEMA or payload.get('native_scope') != scope_binding
            or payload.get('task_id') != native.scope['task_id']
            or payload.get('operation_id') != operation_id or payload.get('phase') != phase
            or payload.get('saved_scene_id') != saved['saved_scene_id']
            or payload.get('saved_sha256') != saved['sha256']
            or payload.get('saved_contract_sha256') != canonical_sha256(saved['scene_contract'])
            or payload.get('transition') != transition
            or (phase == 'cold' and (not isinstance(transition, dict)
                or (transition.get('scene_transition') or {}).get('after_identity') != payload.get('host_identity')))
            or (phase == 'warm' and transition is not None)
            or payload.get('value_sha256') != canonical_sha256({k: v for k, v in value.items() if k != 'native_evidence'})):
        _fail()
    control = _control(native, payload['control'])
    receipt, stored = _receipt(value, saved, native, operation_id, control, phase)
    identity = payload['host_identity']
    if (receipt['host_identity'] != identity or payload['producer_record'] != stored
            or payload['process_birth'].get('pid') != identity['pid']
            or payload['process_birth'].get('state') != 'alive' or not payload['process_birth'].get('birth')):
        _fail()
    if phase == 'warm' and any(identity.get(k) != saved['operation_receipt']['host_identity'].get(k) for k in _IDENTITY):
        _fail()
    state = native.completed_snapshot() if historical_state is None else historical_state
    host = _host(native, state, identity, control, completed=True)
    if host != payload['host']:
        _fail()
    for record in [host['started'], host['intent'], *payload['sources']]:
        _checked(record, native.root)
    if not payload['sources']:
        _fail()
    return value


def verify(value, saved, scope_binding, operation_id, phase, *, transition=None):
    """默认接纳仍要求当前全部停止；历史入口不能放宽新产物的停止门。"""
    return _verify(value, saved, scope_binding, operation_id, phase, transition=transition)


def _historical_state(native, accounting_prefix, accounting_envelope):
    """只读取原R2已停止十四票前缀，当前后继票据不能混入原几何证据。"""
    from dcc_task_runtime.native_scope import _accounting_lock
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    with _accounting_lock(native.state_path):
        current = native._read()
        payload = _prefix(native, accounting_prefix, accounting_envelope)
        state = payload.get('state')
        if (not isinstance(state, dict) or state.get('schema') != 'bridge.native-scope-state/1'
                or state.get('scope_sha256') != native.binding['sha256']
                or state.get('task_id', native.scope['task_id']) != native.scope['task_id']
                or state.get('closed_reason') is not None):
            _fail()
        tickets = state.get('tickets')
        if (not isinstance(tickets, list) or len(tickets) != 14
                or tickets != current['tickets'][:14]
                or sorted(ticket.get('role', '') for ticket in tickets) != sorted(
                    ['graph-worker'] * 2 + ['houdini-host'] * 7 + ['main-husk'] * 2
                    + ['nuke-host'] + ['nuke-render'] * 2)):
            _fail()
        now = time.time()
        charges = []
        for ticket in tickets:
            stopped = native._stop(ticket)
            end = ticket.get('stopped_at')
            if (type(end) not in (int, float) or not math.isfinite(end)
                    or end < ticket['admitted_at'] or ticket['admitted_at'] > now or end > now + 1
                    or not stopped or stopped.get('observed_at') != end
                    or hashlib.sha256(native._canonical(stopped)).hexdigest() != ticket.get('stopped_sha256')):
                _fail()
            charge = max(ticket['charged_seconds'], end - ticket['admitted_at'])
            if not math.isfinite(charge) or charge > native.role_seconds(ticket['role']):
                _fail()
            charges.append(charge)
        if sum(charges) > native._budget['total_seconds']:
            _fail()
        # 与默认completed_snapshot保持相同阶段限制；这里只计算原前缀，绝不刷新账本。
        phases = []
        if native.scope.get('feedback_phase') is not None and native._continuation_previous is not None:
            phases.append((native._feedback_base_state, native._feedback_start_limit, 600))
        if native.scope.get('recovery_phase') is not None:
            phases.append((native._recovery_base_state, 6, 600))
        if native.scope.get('creative_phase') is not None:
            phases.append((native._creative_base_state, native.effective_creative_starts(),
                           native.scope['creative_phase']['seconds']))
        for base, starts, seconds in phases:
            inherited = base['tickets']
            if (tickets[:len(inherited)] != inherited or len(tickets) - len(inherited) > starts
                    or sum(charges[len(inherited):]) > seconds):
                _fail()
        return state


def verify_historical(value, saved, scope_binding, operation_id, phase, *, transition=None,
                      accounting_prefix, accounting_envelope):
    """重验同任务原十四票的HOM原件；原签名前缀是必要来源，不接受裸停止快照。"""
    native = _native(scope_binding, operation_id, phase)
    state = _historical_state(native, accounting_prefix, accounting_envelope)
    return _verify(value, saved, scope_binding, operation_id, phase,
                   transition=transition, historical_state=state)
