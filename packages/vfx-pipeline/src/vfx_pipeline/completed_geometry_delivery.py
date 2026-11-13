"""将已完成的真实几何交付登记为只读工程，复用正常接收回执而不重派旧作业。"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import uuid
from pathlib import Path

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.owned_process import execution_returncode, read_receipt
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory
from houdini_bridge.official_karma_observation import checked_bytes, file_record
from .geometry_session import GeometrySession

KIND = 'geometry_delivery'
PREPARATION = 'bridge.geometry-delivery-preparation/1'
RESULT = 'bridge.geometry-delivery-revision/1'
_DOMAIN = b'bridge.geometry-delivery-registration/1\0'


def _require(condition, code):
    if not condition:
        raise ValueError('GEOMETRY_DELIVERY_' + code)


def _path(value, root=None):
    """来源和交付只接受真实绝对路径，拒绝链接及越界。"""
    p = Path(value)
    _require(p.is_absolute() and p == p.resolve() and not any(x.is_symlink() for x in (p, *p.parents)), 'PATH_INVALID')
    _require(root is None or p.is_relative_to(root), 'PATH_OUTSIDE_SOURCE')
    return p


def _object(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            _require(k not in result, 'DUPLICATE_KEY')
            result[k] = v
        return result
    value = json.loads(_path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)
    _require(type(value) is dict, 'OBJECT_REQUIRED')
    return value


def _record(record, root=None):
    _path(record['path'], root)
    return checked_bytes(record)


def _write(path, value):
    """登记内容以私有原子写入落盘；不覆盖既有原生生产记录。"""
    ensure_private_directory(path.parent)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    atomic_write(path, data, owned_root=path.parent)


def _signed(native, value, domain):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hmac.new(native._key(), domain + raw, hashlib.sha256).hexdigest()


def _envelope(path, native, domain):
    value = _object(path)
    _require(set(value) == {'payload', 'signature'} and type(value['signature']) is str
             and hmac.compare_digest(value['signature'], _signed(native, value['payload'], domain)), 'SIGNATURE_INVALID')
    return value['payload']


def _stops(native, snapshot):
    """认证同一范围的全部启动和停止；不启动、准入或重开任何宿主。"""
    _require(snapshot == native.completed_snapshot() and snapshot['closed_reason'] is None, 'ACCOUNTING_CHANGED')
    for ticket in snapshot['tickets']:
        directory = _path(ticket['directory'], native.root)
        start = read_receipt(directory, 'started', identity=ticket['identity'])
        stop = read_receipt(directory, 'stopped', identity=ticket['identity'])
        _require(ticket['stopped_at'] is not None and start and stop and execution_returncode(stop) == 0
                 and start['pid'] == stop['pid'] and stop['started_sha256'] == canonical_sha256(start), 'STOP_REQUIRED')


def verify_source(record):
    """验证固定已完成交付类型的原始生产事实，不能用说明文件或自述替代。"""
    _record(record)
    path = _path(record['path'])
    _require(path.name == 'result.json' and path.parent.name == 'cold-consumption', 'SOURCE_TYPE_REQUIRED')
    root = path.parent.parent
    scope_record = file_record(_path(root / 'scope.json'))
    native = NativeScope({k: scope_record[k] for k in ('path', 'sha256')})
    _require(native.scope['schema'] == 'bridge.engineering-closure-scope/1', 'SOURCE_SCOPE_REQUIRED')
    cold = _envelope(path, native, b'bridge.independent-cold-consumption/1\0')
    permit = _envelope(path.parent / 'permit.json', native, b'bridge.independent-cold-consumption/1\0')
    stage = _envelope(root / 'permit.json', native, b'bridge.saved-graph-stage/1\0')
    _require(cold['state'] == 'INDEPENDENT_COLD_CONSUMPTION_PASS' and permit['scope'] == stage['scope'] == native.binding,
             'COMPLETED_SOURCE_REQUIRED')
    for source in stage['sources'].values():
        _record(source)
    for name, source in permit['sources'].items():
        if name != 'state_before':
            _record(source)
    # 启动前state是同一认证journal中的历史前缀，不能要求它等于启动后动态state文件。
    before = permit['sources']['state_before']
    _require(before['path'] == str(native.state_path), 'ACCOUNTING_PREFIX_INVALID')
    matches = [line for line in native.journal_path.read_bytes().splitlines()
               if len(line) == before['bytes'] and hashlib.sha256(line).hexdigest() == before['sha256']]
    _require(len(matches) == 1, 'ACCOUNTING_PREFIX_INVALID')
    prefix = native._verify_envelope(json.loads(matches[0]))['state']
    _require(prefix['tickets'] == cold['native']['tickets'][:-1]
             and permit['native_before']['tickets'] == prefix['tickets'], 'ACCOUNTING_PREFIX_CHANGED')
    _stops(native, cold['native'])
    task = native.scope['task_id']
    files = cold['files']
    _require(set(files) == {'hip', 'main', 'nk', 'nuke'}, 'FILES_REQUIRED')
    for source in files.values():
        _record(source, root)
    journal = _object(root / 'journal.json')['stages']
    required = ('adopt_checkpoint', 'save', 'cold_reopen', 'cold_geometry_evaluation', 'render_completed', 'verify', 'register', 'consume')
    _require(all(journal.get(k, {}).get('state') == 'DONE' for k in required), 'STAGES_REQUIRED')
    original = json.loads(_record(stage['sources']['old_preparation']))
    original_record = stage['sources']['old_preparation']
    _require(original['task_id'] == task, 'TASK_CHANGED')
    # 从已认证健康许可取原job字节，原计划与原编译图必须精确相等。
    health_record = stage['sources']['health_result']
    health_root = _path(health_record['path']).parent
    health = _object(health_root / 'permit.json')
    key_path = _path(health_root / '.phase-key')
    _require(key_path.stat().st_mode & 0o077 == 0, 'PRIVATE_SOURCE_KEY_REQUIRED')
    digest = hmac.new(key_path.read_bytes(), b'bridge.health-diagnostic/1\0' + json.dumps(
        health['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode(), hashlib.sha256).hexdigest()
    _require(hmac.compare_digest(health['signature'], digest), 'ORIGINAL_JOB_SIGNATURE_INVALID')
    origin_job_record = health['payload']['sources']['job']
    origin_job = json.loads(_record(origin_job_record))
    _require(origin_job['task_id'] == task and origin_job['preparation'] == original_record, 'ORIGINAL_PLAN_CHANGED')
    plan = origin_job['plan']; unsigned = copy.deepcopy(plan); claimed = unsigned.pop('plan_sha256')
    _require(canonical_sha256(unsigned) == claimed, 'ORIGINAL_PLAN_CHANGED')
    from . import geometry_graph
    graph_source = json.loads(_record(stage['sources']['source']))
    from .official_graph_resume import inspect_resume_source
    observed_source = inspect_resume_source(graph_source['preparation']['path'], graph_source['operation_id'])
    _require(all(observed_source[k] == graph_source[k] for k in observed_source), 'GRAPH_SOURCE_CHANGED')
    expected = geometry_graph._catalog().compiler().compile(geometry_graph.compose_proposal(geometry_graph.selector(plan['model_graph']))).to_dict()
    _require(expected == graph_source['compiled_graph'], 'MODEL_GRAPH_CHANGED')
    saved = journal['save']['result']; reopened = journal['cold_reopen']['result']
    from houdini_bridge.operation_receipts import validate_operation_receipt, operation_receipt_sha256
    from houdini_bridge.operation_receipt_store import load_record
    from .production_hosts import _scene_transition_operation_store_path, _scene_transition_formal_record
    control = root / 'project/control'; runner = _scene_transition_operation_store_path(control, task)
    receipt = saved['operation_receipt']; validate_operation_receipt(receipt)
    _require(receipt['command'] == 'scene.save_hip' and receipt['task_id'] == task
             and load_record(runner, task, receipt['operation_id']) == receipt
             and saved['path'] == files['hip']['path'] and saved['sha256'] == files['hip']['sha256'], 'TYPED_SAVE_REQUIRED')
    transition = reopened['scene_transition']
    _require(all(reopened.get(k) is True for k in ('nodes_verified', 'parameters_verified', 'connections_verified'))
             and reopened['load_warnings'] == [] and reopened['sha256'] == saved['sha256']
             and transition['state'] == 'COMPLETED' and transition['load_count'] == 1
             and transition['operation_receipt_sha256'] == operation_receipt_sha256(transition)
             and _scene_transition_formal_record(control, transition) == transition
             and transition['after_identity']['launch_nonce'] != receipt['host_identity']['launch_nonce'], 'NATIVE_COLD_REOPEN_REQUIRED')
    from .geometry_native_evidence import _receipt, _host
    geometry = journal['cold_geometry_evaluation']['result']; observation = geometry['observation']
    _receipt(observation, saved, native, 'saved_graph_stage_geometry_cold', control)
    _host(native, cold['native'], observation['operation_receipt']['host_identity'], control, completed=True)
    from .geometry_evaluation import evaluate_initial
    evaluation = evaluate_initial(observation['geometry_observation'], json.loads(_record(original['criteria'])))
    _require(evaluation == geometry['evaluation'] and evaluation['state'] == 'PASS', 'GEOMETRY_REQUIRED')
    # 使用原受控producer读回建立登记来源，沿用原artifact ID，不创建假的Nuke producer。
    from .workbuddy_assembly import production_host_client
    from nuke_bridge.task_host import _input_source_registry_class
    hosts = _object(control / 'production-hosts.json')
    boundary = production_host_client(hosts['hosts']['houdini'], control / 'host-state'); boundary.observe_task(task)
    # 旧登记仍按已签快照中的原实现核验，不把新版实现路径追加到旧receipt来源。
    registry_class = _input_source_registry_class({'producer_control': str(control), 'producer_snapshot_manifest': stage['snapshot']})
    registry = registry_class(control / 'artifact_ledger')
    registry.set_operation_source(lambda op: boundary.call('output.verify.status', {'verification_id': op})['execution_fact'])
    main = journal['register']['result']
    verified_main = registry.verify_operation_receipt(main['registry_operation_receipt'])
    _require(verified_main['artifact_id'] == main['artifact_id'] == 'saved_graph_main'
             and main['task_id'] == task and registry.verify('saved_graph_main')['usable'], 'REGISTERED_MAIN_REQUIRED')
    worker = cold['worker']; _record(cold['worker_file'], root)
    _require(json.loads(_record(cold['worker_file'], root)) == worker, 'WORKER_RESULT_CHANGED')
    ticket = cold['native']['tickets'][-1]
    _require(ticket['role'] == 'nuke-render' and ticket['identity'] == permit['identity'], 'COLD_WORKER_REQUIRED')
    stopped = read_receipt(ticket['directory'], 'stopped', identity=ticket['identity'])
    intent = _object(Path(ticket['directory']) / 'intent.json')
    contract = json.loads(_record(permit['sources']['contract'], root))
    _require(stopped == cold['stopped'] and intent['command'] == permit['command']
             and ticket['identity']['snapshot_sha256'] == files['nk']['sha256']
             and ticket['identity']['input_contract_sha256'] == permit['sources']['contract']['sha256']
             and contract['owner_task_id'] == task and contract['registry_inputs']['saved_graph_main']['version'] == main['version'], 'COLD_BINDING_CHANGED')
    readback = worker['input_readback']
    _require(worker['script_opened'] is True and worker['node_resolved'] is True and worker['software_api'] is False
             and worker['execute_calls'] == worker['frames'] == [1] and worker['snapshot'] == files['nk']['path']
             and worker['snapshot_sha256'] == files['nk']['sha256'] and worker['outputs'] == [files['nuke']['path']]
             and readback['before_verified'] is True and readback['after_verified'] is True and readback['owner_task_id'] == task
             and readback['contract_sha256'] == permit['sources']['contract']['sha256']
             and readback['frozen_inputs_sha256'] == contract['input_binding']['frozen_inputs_sha256'], 'NATIVE_CONSUMPTION_REQUIRED')
    frames = [frame for entry in contract['input_binding']['frozen_inputs_manifest'] for frame in entry['frames']]
    _require(len(frames) == 1 and frames[0]['uri'] == files['main']['path'] and frames[0]['sha256'] == files['main']['sha256']
             and all(x['sha256'] == files['main']['sha256'] and x['readonly_copy'] is True for x in readback['consumed'])
             and len(readback['consumed']) == 1, 'CONSUMED_INPUT_CHANGED')
    comparison = cold['comparison']
    _require(comparison['state'] == 'PASS' and comparison['require_identical'] is True
             and comparison['samples_compared'] == 504000 and comparison['different_samples'] == 0
             and comparison['reference'] == files['main'] and comparison['candidate'] == files['nuke'], 'COMPARISON_REQUIRED')
    return {'task_id': task, 'scope': native.binding, 'native_snapshot': cold['native'], 'files': files,
            'original_preparation': original_record, 'original_job': origin_job_record, 'plan': plan,
            'main_registry': main['registry_operation_receipt'], 'source': record,
            'source_permit': file_record(path.parent / 'permit.json'), 'stage_permit': file_record(root / 'permit.json'),
            'nk_origin': cold['nk_origin'], 'visual_acceptance': 'PENDING'}


class CompletedGeometryDelivery(GeometrySession):
    """只有正常接收和只读查询能力，不授予新创作或旧范围执行权限。"""
    def __init__(self, preparation, *, connection_id=None):
        self.preparation = copy.deepcopy(preparation)
        outer = json.loads(_record(self.preparation)); payload = outer['payload']
        native = NativeScope(payload['scope'])
        _require(set(outer) == {'payload', 'signature'} and hmac.compare_digest(
            outer['signature'], _signed(native, payload, _DOMAIN)), 'REGISTRATION_SIGNATURE_INVALID')
        details = verify_source(payload['source'])
        _require(payload['schema'] == PREPARATION and payload['task_id'] == details['task_id']
                 and payload['scope'] == details['scope'] and payload['original_preparation'] == details['original_preparation']
                 and payload['original_job'] == details['original_job'], 'REGISTRATION_CHANGED')
        _record(payload['original_state'])
        self.prep = payload; self.root = _path(self.preparation['path']).parent
        self.worker_record = None; self.state_path = self.root / 'geometry-state.json'; self.log = self.root / 'geometry-events.jsonl'
        self.connection_id = connection_id or uuid.uuid4().hex

    def _result_binding(self, entry, job, result, record, **kwargs):
        """导入类型显式绑定S3真实范围，不冒充旧geometry执行结果。"""
        validation = validate_result(self.preparation, job, result)
        _require(entry['operation_id'] == job['operation_id'] and entry['job_file'] == file_record(Path(entry['directory']) / 'job.json')
                 and record == file_record(Path(entry['directory']) / 'result.json'), 'ACCEPTED_BINDING_CHANGED')
        return {'schema': 'bridge.geometry-imported-accepted-result/1', 'delivery_kind': KIND,
                'preparation': self.preparation, 'scope': self.prep['scope'], 'task_id': self.prep['task_id'],
                'operation_id': job['operation_id'], 'revision': job['revision'], 'job': entry['job_file'],
                'result': record, 'files': result['files'], 'source': result['completed_delivery_source'],
                'source_validation': validation, 'original_preparation': self.prep['original_preparation']}

    def catalog(self):
        """公开只读交付能力；不提供可执行模型基线。"""
        state = self._read()
        return {'task_id': self.prep['task_id'], 'revision': state['revision'], 'delivery_kind': KIND,
                'read_only': True, 'current_model_graph': None, 'consumable_for_new_execution': False,
                'capabilities': ['tasks', 'continue_task'], 'native_dispatch_attempted': False}

    def _read_only(self, *args, **kwargs):
        """明确拒绝创作和取消，不能靠缺少素材偶然阻断继承的执行入口。"""
        raise ValueError('GEOMETRY_DELIVERY_READ_ONLY')

    media = _read_only
    observe = _read_only
    propose = _read_only
    execute = _read_only
    cancel = _read_only

    def tasks(self):
        state = self._read(); original = json.loads(_record(self.prep['original_state']))
        failures = [{'operation_id': op, 'state': row['state'], 'revision': row['revision'],
                     'task_id': self.prep['task_id'], 'historical': True} for op, row in original['jobs'].items()]
        return failures + super().tasks()

    def query(self, operation_id, **kwargs):
        original = json.loads(_record(self.prep['original_state']))
        if operation_id in original['jobs']:
            row = original['jobs'][operation_id]
            _require(row['state'] == 'FAILED', 'ORIGINAL_FAILURE_CHANGED')
            return {'operation_id': operation_id, 'task_id': self.prep['task_id'], 'state': 'FAILED',
                    'action': 'BLOCKED', 'historical': True, 'native_dispatch_attempted': False}
        _require(type(operation_id) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', operation_id), 'OPERATION_ID_REQUIRED')
        state = self._read(); entry = state['jobs'].get(operation_id)
        _require(entry is not None, 'TASK_NOT_IN_PROJECT')
        directory = _path(entry['directory'], self.root)
        _require(directory == self.root / 'jobs' / operation_id and entry['operation_id'] == operation_id
                 and entry['job_file']['path'] == str(directory / 'job.json'), 'TASK_BINDING_CHANGED')
        job = json.loads(_record(entry['job_file'], self.root))
        if operation_id in state['completed']:
            return self._observe_accepted(state, entry, job)
        record = file_record(directory / 'result.json'); result = json.loads(_record(record, self.root))
        validation = validate_result(self.preparation, job, result)
        with execution_lock(self.root, 'geometry-session'):
            state = self._read(); entry = state['jobs'][operation_id]
            if operation_id in state['completed']:
                return self._observe_accepted(state, entry, job)
            _require(job['revision'] == state['revision'] + 1 and file_record(directory / 'result.json') == record,
                     'COMPLETION_ORDER_CHANGED')
            acceptance = self._seal_acceptance(entry, job, result, record, validation)
            entry.update(state='COMPLETE', result=record, acceptance=acceptance)
            state['completed'].append(operation_id); state['revision'] = job['revision']
            state['current_model_graph'] = None  # 只读文件来源不授予标准模型基线能力。
            self._write(state)
            self._event('job_complete', {'operation_id': operation_id, 'revision': job['revision'],
                        'result': record, 'acceptance': acceptance, 'delivery_kind': KIND})
        return self._observe_accepted(state, entry, job)


def validate_result(preparation, job, result):
    """首次接收和历史观察均复核本类型来源，普通geometry不接受此通道。"""
    outer = json.loads(_record(preparation)); p = outer['payload']; native = NativeScope(p['scope'])
    _require(hmac.compare_digest(outer['signature'], _signed(native, p, _DOMAIN)) and p['schema'] == PREPARATION, 'REGISTRATION_SIGNATURE_INVALID')
    details = verify_source(p['source'])
    directory = _path(Path(preparation['path']).parent / 'jobs' / job['operation_id'])
    _require(job['schema'] == 'bridge.geometry-job/1' and job['preparation'] == preparation
             and job['task_id'] == p['task_id'] == details['task_id'] and job['revision'] == 1
             and job['directory'] == str(directory) and job.get('completed_delivery_source') == p['source']
             and job['plan'] == details['plan'] and result['schema'] == RESULT and result['state'] == 'COMPLETE'
             and all(result.get(k) == job[k] for k in ('preparation', 'task_id', 'operation_id', 'revision', 'plan', 'completed_delivery_source'))
             and result['files'] == details['files'] and result['source_scope'] == details['scope']
             and result['native_snapshot'] == details['native_snapshot'] and result['main_registry'] == details['main_registry']
             and result['derived_files'] == {k: details['files'][k] for k in ('nk', 'nuke')}
             and result['nk_origin'] == details['nk_origin'] and result['visual_acceptance'] == 'PENDING', 'RESULT_BINDING_CHANGED')
    return {'state': 'VERIFIED', 'delivery_kind': KIND, 'source': p['source'], 'source_scope': details['scope'],
            'native_snapshot': details['native_snapshot'], 'main_registry': details['main_registry'], 'derived_files': result['derived_files']}


def register_delivery(registry, project_id, label, source):
    """操作者CLI只登记验证后的固定来源；模型MCP不开放任意路径参数。"""
    from .project_entry import read_projects, _identifier
    _identifier(project_id); _require(type(label) is str and 1 <= len(label) <= 120, 'LABEL_REQUIRED')
    registry = _path(registry); source = file_record(_path(source)); details = verify_source(source)
    native = NativeScope(details['scope']); root = registry.parent / 'accepted-deliveries' / project_id
    original_root = Path(details['original_preparation']['path']).parent
    original_state = file_record(original_root / 'geometry-state.json'); old = json.loads(_record(original_state))
    _require(old['task_id'] == details['task_id'] and old['revision'] == 0 and not old['completed']
             and old['jobs'] and all(x['state'] == 'FAILED' for x in old['jobs'].values()), 'ORIGINAL_FAILURES_REQUIRED')
    payload = {'schema': PREPARATION, 'task_id': details['task_id'], 'scope': details['scope'], 'source': source,
               'original_preparation': details['original_preparation'], 'original_job': details['original_job'],
               'original_state': original_state, 'media': {}, 'capability': 'accepted_result_observation_only'}
    preparation_path = root / 'delivery-preparation.json'; envelope = {'payload': payload, 'signature': _signed(native, payload, _DOMAIN)}
    operation = 'delivery_' + canonical_sha256({'source': source, 'project_id': project_id})[:24]
    with execution_lock(registry.parent, 'bridge-projects'):
        projects = read_projects(registry)
        previous = projects['projects'].get(project_id)
        # 与既有登记共用同一锁；项目冲突须在创建任何新目录前拒绝。
        _require(previous is None or (previous['kind'] == KIND and previous['label'] == label
                 and previous['preparation']['path'] == str(preparation_path)), 'REGISTRATION_CONFLICT')
        if preparation_path.exists():
            _require(_object(preparation_path) == envelope, 'REGISTRATION_CONFLICT')
        else:
            ensure_private_directory(root); _write(preparation_path, envelope)
        preparation = file_record(preparation_path); item = {'label': label, 'kind': KIND, 'preparation': preparation}
        _require(project_id not in projects['projects'] or projects['projects'][project_id] == item, 'REGISTRATION_CONFLICT')
        session = CompletedGeometryDelivery(preparation)
        directory = root / 'jobs' / operation
        with execution_lock(root, 'geometry-session'):
            state = session._read()
            if operation not in state['jobs']:
                _require(state['revision'] == 0 and not state['jobs'], 'REGISTRATION_CONFLICT')
                ensure_private_directory(directory)
                job = {'schema': 'bridge.geometry-job/1', 'preparation': preparation, 'task_id': details['task_id'],
                       'operation_id': operation, 'revision': 1, 'directory': str(directory), 'plan': details['plan'],
                       'completed_delivery_source': source}
                result = {k: copy.deepcopy(job[k]) for k in ('preparation', 'task_id', 'operation_id', 'revision', 'plan', 'completed_delivery_source')}
                result.update(schema=RESULT, state='COMPLETE', files=details['files'], source_scope=details['scope'],
                              native_snapshot=details['native_snapshot'], main_registry=details['main_registry'],
                              derived_files={k: details['files'][k] for k in ('nk', 'nuke')}, nk_origin=details['nk_origin'], visual_acceptance='PENDING')
                validate_result(preparation, job, result)
                _write(directory / 'job.json', job); _write(directory / 'result.json', result)
                state['jobs'][operation] = {'operation_id': operation, 'directory': str(directory), 'revision': 1,
                    'plan_id': details['plan']['plan_id'], 'state': 'RESULT_READY', 'job_file': file_record(directory / 'job.json')}
                session._write(state)
        projects['projects'][project_id] = item; _write(registry, projects)
    current = session._read()
    return {'project_id': project_id, 'operation_id': operation, 'task_id': details['task_id'],
            'state': current['jobs'][operation]['state'], 'revision': current['revision'], 'native_dispatch_attempted': False}
