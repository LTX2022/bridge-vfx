"""Trusted controller launch/reconnect/stop for a task-owned Nuke TCP host."""
from __future__ import annotations
import copy
import errno
import hashlib
import hmac
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import secrets
import sys
import subprocess
import time
import uuid
from dcc_task_runtime import owned_process
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory
from .client import NukeClient


def _file(value):
    path=Path(value).expanduser()
    if path.is_symlink() or not path.is_file(): raise ValueError('regular file required: '+str(path))
    return path.resolve()


def _write(path,payload):
    atomic_write(path,json.dumps(payload,sort_keys=True).encode('utf-8'),owned_root=path.parent)


def _input_source_payload(record, scope):
    """读取由当前控制端启动文件固定的旧产物来源，不接受模型请求中的路径。"""
    from houdini_bridge.official_karma_observation import checked_bytes
    path = Path(str((record or {}).get('path') or ''))
    if (not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents))
            or not path.resolve().is_relative_to(scope.root) or (record or {}).get('bytes', 0) > 4 * 1024 * 1024):
        raise ValueError('CONTROLLED_INPUT_RESUME_RECORD_INVALID')
    return json.loads(checked_bytes(record))


def _input_source_registry_class(source, *, scope=None, task_id=None):
    """按认证来源隔离加载登记实现，旧生产快照与后续登记实现分别绑定。"""
    if source.get('schema') == 'bridge.geometry-nuke-source/2':
        from vfx_pipeline.geometry_registration_resume import registration_registry_class
        return registration_registry_class(source['registration_implementation'], scope, task_id, source=source)
    import types
    from dcc_task_runtime.canonical import canonical_sha256
    from houdini_bridge.official_karma_observation import checked_bytes, file_record
    control = Path(source['producer_control'])
    index = json.loads(checked_bytes(source['producer_snapshot_manifest']))
    frozen = {item['path']: item['sha256'] for item in index['files']}
    names = ('canonical', 'models', 'errors', 'contracts', 'windows_process', 'platform_support',
             'pipeline_store', 'project_color', 'exr_codec', 'artifact_registry')
    paths, sources = {}, {}
    for name in names:
        relative = 'packages/dcc-task-runtime/src/dcc_task_runtime/' + name + '.py'
        path = control / 'snapshot' / relative
        record = file_record(path)
        if frozen.get(relative) != record['sha256']:
            raise ValueError('CONTROLLED_INPUT_REGISTRY_SOURCE_CHANGED')
        paths[name], sources[name] = path, checked_bytes(record)
    alias = '_bridge_nuke_input_registry_' + canonical_sha256(source['producer_snapshot_manifest'])
    if alias not in sys.modules:
        package = types.ModuleType(alias)
        package.__package__, package.__path__ = alias, []
        sys.modules[alias] = package
        try:
            for name in names:
                module = types.ModuleType(alias + '.' + name)
                module.__package__, module.__file__ = alias, str(paths[name])
                sys.modules[module.__name__] = module
                setattr(package, name, module)
                exec(compile(sources[name], str(paths[name]), 'exec'), module.__dict__)
        except BaseException:
            for name in tuple(sys.modules):
                if name == alias or name.startswith(alias + '.'):
                    sys.modules.pop(name, None)
            raise
    return sys.modules[alias + '.artifact_registry'].ArtifactRegistry


def _geometry_source_header(source, scope, task_id):
    """认证独立几何来源的固定身份；具体owner、生产事实和登记回执仍走公共精确核验。"""
    from dcc_task_runtime.native_scope import GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE, GEOMETRY_SCENE_PROFILE
    from dcc_task_runtime.geometry_feedback_scope import SCHEMA as FEEDBACK_SCHEMA, RESOURCE_PROFILE as FEEDBACK_PROFILE
    from houdini_bridge.official_karma_observation import checked_bytes
    fields = {'schema', 'task_id', 'artifact_id', 'artifact_version', 'producer_scope',
              'producer_control', 'producer_ledger', 'producer_manifest', 'producer_snapshot_manifest',
              'producer_deployment', 'producer_owners', 'registry_operation_receipt', 'producer_fact_sha256'}
    registration_tail = type(source) is dict and source.get('schema') == 'bridge.geometry-nuke-source/2'
    if registration_tail:
        fields = fields | {'registration_implementation'}
    if (type(source) is not dict or set(source) != fields
            or source.get('schema') not in ('bridge.geometry-nuke-source/1', 'bridge.geometry-nuke-source/2')
            or source.get('task_id') != task_id or scope.scope.get('task_id') != task_id
            or (scope.scope.get('schema'), scope.resource_profile) not in
               ((GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE), (FEEDBACK_SCHEMA, FEEDBACK_PROFILE))
            or scope.scope.get('scene_profile') != GEOMETRY_SCENE_PROFILE
            or type(source.get('artifact_id')) is not str or not source['artifact_id']
            or type(source.get('artifact_version')) is not int or source['artifact_version'] < 1
            or type(source.get('producer_fact_sha256')) is not str
            or len(source['producer_fact_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in source['producer_fact_sha256'])):
        raise ValueError('GEOMETRY_INPUT_SOURCE_BINDING_REQUIRED')
    record = source['producer_scope']
    if (type(record) is not dict or set(record) != {'path', 'bytes', 'sha256'}
            or {k: record[k] for k in ('path', 'sha256')} != scope.binding):
        raise ValueError('GEOMETRY_INPUT_SCOPE_MISMATCH')
    checked_bytes(record)
    control, ledger = Path(str(source['producer_control'])), Path(str(source['producer_ledger']))
    for path in (control, ledger):
        if (not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents))
                or path != path.resolve() or not path.is_relative_to(scope.root)):
            raise ValueError('GEOMETRY_INPUT_PATH_INVALID')
    parts = control.relative_to(scope.root).parts
    if (len(parts) != 4 or parts[0] != 'jobs' or not parts[1]
            or parts[2:] != ('project', 'control')
            or ledger != scope.root / 'artifact_ledger'
            or type(source['registry_operation_receipt']) is not dict
            or source['registry_operation_receipt'].get('registry_path') != str(ledger / 'artifacts.sqlite3')):
        raise ValueError('GEOMETRY_INPUT_LEDGER_OR_CONTROL_MISMATCH')
    return control, ledger


def _geometry_binding(source, scope, task_id):
    """完整认证并只在本次调用内返回登记实现。"""
    control, ledger = _geometry_source_header(source, scope, task_id)
    registry_class = None
    if source['schema'] == 'bridge.geometry-nuke-source/2':
        registry_class = _input_source_registry_class(source, scope=scope, task_id=task_id)
    return control, ledger, registry_class


def _geometry_source_binding(source, scope, task_id):
    """保留生产门的完整认证和二元返回协议。"""
    control, ledger, _ = _geometry_binding(source, scope, task_id)
    return control, ledger



def _rectlight_shape_source_binding(source, scope, task_id):
    """独立软箱产物只接受同范围、原场景task与新前端身份的生产来源。"""
    from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE,validate_scope
    from houdini_bridge.official_karma_observation import checked_bytes
    fields={'schema','task_id','artifact_id','artifact_version','producer_scope','producer_control','producer_ledger',
      'producer_manifest','producer_snapshot_manifest','producer_deployment','producer_owners','registry_operation_receipt',
      'producer_fact_sha256','case_id','case_variant','shape_authority','creative_task_id'}
    if (type(source) is not dict or set(source)!=fields or source.get('schema')!='bridge.rectlight-shape-nuke-source/1'
            or scope.resource_profile!=RESOURCE_PROFILE or task_id!=scope.scope.get('task_id')
            or source.get('task_id')!=task_id or source.get('creative_task_id')!=scope.scope.get('creative_task_id')
            or source.get('shape_authority')!=scope.scope.get('shape_authority')
            or source.get('artifact_id')!='rectlight_shape_main' or type(source.get('artifact_version')) is not int
            or source['artifact_version'] not in (1,2) or source.get('case_id')!='karma_lights_rectlight_v1'
            or type(source.get('producer_fact_sha256')) is not str or len(source['producer_fact_sha256'])!=64
            or any(ch not in '0123456789abcdef' for ch in source['producer_fact_sha256'])):
        raise ValueError('RECT_SHAPE_INPUT_SOURCE_REQUIRED')
    authority=validate_scope(scope.scope,scope.path)
    if source['case_variant']!=authority['sources']['case_variant']:
        raise ValueError('RECT_SHAPE_INPUT_CASE_MISMATCH')
    record=source['producer_scope']
    if (type(record) is not dict or set(record)!={'path','bytes','sha256'}
            or {k:record[k] for k in ('path','sha256')}!=scope.binding):raise ValueError('RECT_SHAPE_INPUT_SCOPE_MISMATCH')
    checked_bytes(record)
    control=Path(str(source['producer_control']));ledger=Path(str(source['producer_ledger']))
    for path in (control,ledger):
        if (not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents))
                or not path.is_relative_to(scope.root)):raise ValueError('RECT_SHAPE_INPUT_PATH_INVALID')
    parts=control.relative_to(scope.root).parts
    if (len(parts)!=4 or parts[0]!='jobs' or not parts[1] or parts[2:]!=('project','control')
            or ledger!=Path(authority['ledger_root']) or ledger!=scope.root/'artifact_ledger'
            or type(source['registry_operation_receipt']) is not dict
            or source['registry_operation_receipt'].get('registry_path')!=str(ledger/'artifacts.sqlite3')):
        raise ValueError('RECT_SHAPE_INPUT_LEDGER_OR_CONTROL_MISMATCH')
    return control,ledger

def input_artifact_registry(source, *, scope, task_id, require_continuation=True, fallback=None, observe_completed=False):
    """公开入口保留完整来源核验及原生产绑定行为。"""
    return _input_artifact_registry(source, scope=scope, task_id=task_id,
        require_continuation=require_continuation, fallback=fallback, observe_completed=observe_completed)


def _input_artifact_registry(source, *, scope, task_id, require_continuation=True, fallback=None,
                             observe_completed=False, _read_only_binding=False, _historical_observation=None):
    """重验原生产与登记；自有冷消费仅观察生产绑定，不改其诊断索引。"""
    from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_INCREMENTAL_MODE
    from dcc_task_runtime.canonical import canonical_sha256
    from houdini_bridge.official_karma_observation import checked_bytes
    feedback = isinstance(source,dict) and source.get('schema')=='bridge.disklight-feedback-nuke-source/1'
    creative = isinstance(source,dict) and source.get('schema')=='bridge.creative-nuke-source/1'
    geometry = isinstance(source,dict) and source.get('schema') in ('bridge.geometry-nuke-source/1', 'bridge.geometry-nuke-source/2')
    shape = isinstance(source,dict) and source.get('schema')=='bridge.rectlight-shape-nuke-source/1'
    if (not isinstance(source, dict) or source.get('schema') not in ('bridge.official-nuke-resume-source/1','bridge.disklight-feedback-nuke-source/1','bridge.creative-nuke-source/1','bridge.geometry-nuke-source/1','bridge.geometry-nuke-source/2','bridge.rectlight-shape-nuke-source/1')
            or source.get('task_id') != task_id):
        raise ValueError('CONTROLLED_INPUT_RESUME_TASK_MISMATCH')
    registry_class = None
    if shape:_rectlight_shape_source_binding(source,scope,task_id)
    if geometry:
        if source['schema'] == 'bridge.geometry-nuke-source/2':
            if type(source) is not dict:
                raise ValueError('GEOMETRY_INPUT_SOURCE_BINDING_REQUIRED')
            # 冻结本次来源，避免调用方并发改动已认证字典后再使用其字段。
            source = copy.deepcopy(source)
            _, _, registry_class = _geometry_binding(source, scope, task_id)
        else:
            _geometry_source_binding(source, scope, task_id)
    record = source['producer_scope']
    checked_bytes(record)
    producer = NativeScope({key: record[key] for key in ('path', 'sha256')})
    ancestry_ok=scope.scope.get('continuation_of')==record
    if shape:
        ancestry_ok = scope.binding == producer.binding and producer.scope.get('shape_authority')==scope.scope['shape_authority']
    if geometry:
        ancestry_ok = scope.binding == producer.binding and producer.scope.get('task_id') == task_id
    if creative:
        phase = scope.scope.get('creative_phase') or {}
        if phase != producer.scope.get('creative_phase') or phase.get('task_id') != task_id:
            raise ValueError('CONTROLLED_INPUT_CREATIVE_PHASE_MISMATCH')
        ancestry_ok = scope.binding == producer.binding
        current = scope
        for _ in range(16):
            if ancestry_ok:
                break
            parent = current.scope.get('continuation_of')
            if parent == record:
                ancestry_ok = True
                break
            if not isinstance(parent, dict) or current.scope.get('creative_phase') != phase:
                break
            current = NativeScope({k: parent[k] for k in ('path', 'sha256')})
    if feedback and not ancestry_ok and scope.scope.get('recovery_phase') is not None:
        # 恢复阶段只使用被新范围固定的同一v2来源，旧生产范围仍逐项重验。
        phase = scope.scope['recovery_phase']
        ancestry_ok = (phase.get('task_id') == task_id
                       and json.loads(checked_bytes(phase['input_source'])) == source)
    if feedback and not ancestry_ok:
        current=scope
        for _ in range(8):
            if current.scope.get('feedback_phase')!=producer.scope.get('feedback_phase'):break
            parent=current.scope.get('continuation_of')
            if parent==record:ancestry_ok=True;break
            if not isinstance(parent,dict):break
            current=NativeScope({key:parent[key] for key in ('path','sha256')})
    if (producer.root != scope.root or not (geometry or shape) and scope.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE
            or require_continuation and not ancestry_ok):
        raise ValueError('CONTROLLED_INPUT_RESUME_SCOPE_MISMATCH')
    def owned(value):
        path = Path(str(value or ''))
        if (not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents))
                or not path.resolve().is_relative_to(scope.root)):
            raise ValueError('CONTROLLED_INPUT_PATH_OUTSIDE_SCOPE')
        return path.resolve()
    control, ledger = owned(source['producer_control']), owned(source['producer_ledger'])
    expected_ledger = control / 'artifact_ledger'
    if geometry or shape:
        expected_ledger = scope.root / 'artifact_ledger'
    if feedback:
        phase=producer.scope.get('feedback_phase') or {}
        if phase.get('task_id')!=task_id or source.get('feedback_delivery')!=phase.get('source_delivery'):
            raise ValueError('CONTROLLED_INPUT_FEEDBACK_TASK_MISMATCH')
        delivery=json.loads(checked_bytes(source['feedback_delivery']))
        expected_ledger=owned(delivery['artifact_ledger'])
        if owned(source['registry_operation_receipt']['registry_path']) != expected_ledger/'artifacts.sqlite3':
            raise ValueError('CONTROLLED_INPUT_FEEDBACK_LEDGER_MISMATCH')
    if creative:
        anchor = json.loads(checked_bytes(producer.scope['creative_phase']['input_source']))
        expected_ledger = owned(producer.scope['creative_phase'].get('ledger_root',anchor['producer_ledger']))
        if source.get('creative_phase') != producer.scope['creative_phase'] or owned(source['registry_operation_receipt']['registry_path']) != expected_ledger / 'artifacts.sqlite3':
            raise ValueError('CONTROLLED_INPUT_CREATIVE_LEDGER_MISMATCH')
    if ledger != expected_ledger or not (ledger / 'artifacts.sqlite3').is_file():
        raise ValueError('CONTROLLED_INPUT_RESUME_LEDGER_MISMATCH')
    for name, expected in (('producer_manifest', control / 'run.json'),
                           ('producer_snapshot_manifest', control / 'snapshot-manifest.json'),
                           ('producer_deployment', control / 'production-hosts.json'),
                           ('producer_owners', control / 'host-state/houdini-operation-owners.json')):
        item = source[name]
        if owned(item['path']) != expected:
            raise ValueError('CONTROLLED_INPUT_RESUME_RECORD_MISMATCH')
        checked_bytes(item)
    from vfx_pipeline.official_graph_resume import _snapshot
    if _snapshot(control) != source['producer_snapshot_manifest']:
        raise ValueError('CONTROLLED_INPUT_RESUME_SNAPSHOT_MISMATCH')
    saved = json.loads(checked_bytes(source['producer_deployment']))
    host = saved.get('hosts', {}).get('houdini')
    # 几何共享账本须由部署显式绑定，宿主本地索引只接纳原control目录。
    if (saved.get('task_id') != task_id or not isinstance(host, dict)
            or host.get('native_scope') != producer.binding
            or (host.get('resource_budget') or {}).get('native_scope') != producer.binding
            or owned(host.get('task_root')) != producer.root
            or owned(host.get('controller_root')) != control
            or ((geometry or shape) and host.get('feedback_ledger_root') != str(ledger))
            or (owned(host.get('ledger_root')) != ledger and not ((feedback or creative or geometry or shape) and owned(host.get('ledger_root'))==control/'artifact_ledger'))
            or host.get('expected_identity', {}).get('task_id') != task_id
            or host.get('evidence_source') != 'real_host'):
        raise ValueError('CONTROLLED_INPUT_DEPLOYMENT_BINDING_MISMATCH')
    from vfx_pipeline.workbuddy_assembly import production_host_client
    boundary = production_host_client(host, control / 'host-state')
    if _read_only_binding:
        boundary.observe_task(task_id)
    else:
        boundary.bind_task(task_id)
    if registry_class is None:
        registry_class = _input_source_registry_class(source, scope=scope, task_id=task_id)
    registry = registry_class(ledger)
    def operation_source(operation_id):
        owner = boundary._load_operation_owners().get(operation_id)
        if owner is None:
            return fallback(operation_id) if fallback is not None else None
        if (not isinstance(owner, dict) or owner.get('operation_kind') != 'output-verification'
                or owner.get('task_id') != task_id or owner.get('evidence_source') != 'real_host'):
            raise ValueError('CONTROLLED_INPUT_OPERATION_OWNER_MISMATCH')
        parent = boundary._load_operation_owners().get(owner.get('parent_operation_id'))
        if not isinstance(parent, dict) or parent.get('task_id') != task_id:
            raise ValueError('CONTROLLED_INPUT_OPERATION_OWNER_MISMATCH')
        producer_binding = parent.get('producer_binding') or {}
        if any(host['expected_identity'].get(key) != value
               for key, value in producer_binding.get('host_identity', {}).items() if key != 'scene_epoch'):
            raise ValueError('CONTROLLED_INPUT_PRODUCER_HOST_MISMATCH')
        owned(parent.get('operation_store_path'))
        owned((parent.get('supervisor_binding') or {}).get('directory'))
        owned(producer_binding.get('output_pattern'))
        from houdini_bridge.controlled_output import verify_controlled_output
        fact = verify_controlled_output(parent, task_id=task_id,
            operation_id=owner['parent_operation_id'], verification_id=operation_id,
            policy=owner['policy'], alpha_calibration=owner['alpha_calibration'],
            evidence_source='real_host', historical_scope=owner.get('historical_scope') or (source['producer_scope'] if observe_completed else (None if (creative or geometry or shape) and scope.binding == producer.binding else source['producer_scope'])),
            render_terminal_recovery=owner.get('render_terminal_recovery'),
            _historical_completion=(_historical_observation.get('completed_result')
                if _historical_observation is not None and _read_only_binding and observe_completed and creative else None))
        # 只接受与原登记时验证事实完全相同的历史读回，不重签或生成新生产事实。
        original_fact = control / 'host-state' / ('verified-output-' + operation_id + '.json')
        if (not original_fact.is_file() or original_fact.is_symlink()
                or json.loads(original_fact.read_bytes()) != fact
                or canonical_sha256(fact) != source['producer_fact_sha256']
                or fact.get('task_id') != task_id or fact.get('evidence_source') != 'real_host'):
            raise ValueError('CONTROLLED_INPUT_SOURCE_MISMATCH')
        return fact
    registry.set_operation_source(operation_source)
    if _historical_observation is not None:
        if not creative or not observe_completed or not _read_only_binding:
            raise ValueError('HISTORICAL_CREATIVE_OBSERVATION_REQUIRED')
        from dcc_task_runtime.historical_artifacts import verify_historical_operation_receipt
        receipt = verify_historical_operation_receipt(registry, source['registry_operation_receipt'],
            superseding=_historical_observation)['receipt']
    else:
        receipt = registry.verify_operation_receipt(source['registry_operation_receipt'])
    if (receipt.get('artifact_id') != source['artifact_id'] or receipt.get('version') != source['artifact_version']
            or receipt.get('task_id') != task_id or receipt.get('producer_fact_sha256') != source['producer_fact_sha256']):
        raise ValueError('CONTROLLED_INPUT_RESUME_ARTIFACT_MISMATCH')
    if _historical_observation is None and not registry.verify(source['artifact_id']).get('usable'):
        raise ValueError('CONTROLLED_INPUT_RESUME_ARTIFACT_UNUSABLE')
    return registry


def creative_cold_context():
    """冷worker使用明确的创作上下文，不虚构Nuke控制宿主身份。"""
    value = os.environ.get('BRIDGE_CREATIVE_COLD_CONTEXT')
    digest = os.environ.get('BRIDGE_CREATIVE_COLD_CONTEXT_SHA256')
    if value is None and digest is None:
        return None
    from houdini_bridge.official_karma_observation import checked_bytes
    from dcc_task_runtime.native_scope import NativeScope
    path = Path(str(value or ''))
    if not path.is_absolute() or path.is_symlink() or path.name != 'cold-context.json':
        raise ValueError('CREATIVE_COLD_CONTEXT_PATH_INVALID')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('CREATIVE_COLD_CONTEXT_CHANGED')
    context = json.loads(content)
    if context.get('schema') == 'bridge.rectlight-shape-cold-context/1':
        if set(context)!={'schema','native_scope','task_id','input_artifact_source'} or len(content)>64*1024:
            raise ValueError('RECT_SHAPE_COLD_CONTEXT_INVALID')
        scope=NativeScope(context['native_scope'])
        source=_input_source_payload(context['input_artifact_source'],scope)
        control,_=_rectlight_shape_source_binding(source,scope,context['task_id'])
        if (path!=control/'cold-context.json' or any(p.is_symlink() for p in (path,*path.parents))
                or context['input_artifact_source'].get('path')!=str(control/'creative-input-source.json')):
            raise ValueError('RECT_SHAPE_COLD_CONTEXT_BINDING_MISMATCH')
        return context,scope,source
    if context.get('schema') == 'bridge.geometry-cold-context/1':
        if set(context) != {'schema', 'native_scope', 'task_id', 'input_artifact_source'}:
            raise ValueError('GEOMETRY_COLD_CONTEXT_INVALID')
        scope = NativeScope(context['native_scope'])
        source = _input_source_payload(context['input_artifact_source'], scope)
        control, _ = _geometry_source_binding(source, scope, context['task_id'])
        if (len(content) > 64 * 1024 or path != control / 'cold-context.json'
                or any(p.is_symlink() for p in (path, *path.parents))):
            raise ValueError('GEOMETRY_COLD_CONTEXT_BINDING_MISMATCH')
        return context, scope, source
    if context.get('schema') != 'bridge.creative-cold-context/1':
        raise ValueError('CREATIVE_COLD_CONTEXT_INVALID')
    scope = NativeScope(context['native_scope'])
    phase = scope.scope.get('creative_phase') or {}
    source = json.loads(checked_bytes(context['input_artifact_source']))
    namespace = scope.scope['accounting']['namespace']
    allowed = scope.root / 'continuations' / namespace / 'jobs'
    if phase.get('schema') == 'bridge.official-case-creative-phase/1':
        # 案例工程位于已认证合同旁；后续核算范围改名不改变该工程和作业归属。
        contract_record = phase['case_contract']
        contract_path = Path(contract_record['path'])
        if (not contract_path.is_absolute() or any(p.is_symlink() for p in (contract_path, *contract_path.parents))
                or contract_path.parent.parent != scope.root / 'continuations'):
            raise ValueError('CREATIVE_COLD_CASE_CONTRACT_PATH_INVALID')
        contract = json.loads(checked_bytes(contract_record))
        if (contract.get('schema') != 'bridge.official-rectlight-source/1'
                or contract.get('case_id') != 'karma_lights_rectlight_v1'
                or source.get('case_id') != contract['case_id']
                or Path(phase.get('ledger_root', '')) != contract_path.parent / 'artifact_ledger'):
            raise ValueError('CREATIVE_COLD_CASE_CONTRACT_MISMATCH')
        allowed = contract_path.parent / 'jobs'
    producer_binding={k:source['producer_scope'][k] for k in ('path','sha256')}
    producer_matches=producer_binding==scope.binding
    controller_matches=Path(source.get('producer_control',''))==path.parent
    retry_recovery=context.get('nuke_retry_recovery')
    if source.get('render_terminal_recovery') is not None:
        # 仅这份已签名完成的Rect产物可由准确直接后继07冷消费，生产身份仍为06。
        from vfx_pipeline.rectlight_render_terminal_recovery import validate_render_terminal_recovery,VERIFY
        proof=source['render_terminal_recovery']
        recovered=validate_render_terminal_recovery(proof,scope,nuke_retry_recovery=retry_recovery)
        control=Path(recovered['control'])
        if retry_recovery is not None:
            retry_contract=recovered.get('_consumer_retry_contract') or {}
            if (path!=Path(retry_contract.get('retry_context','')) or context['input_artifact_source']!=retry_contract.get('source_input')
                    or Path(source.get('producer_control',''))!=control):
                raise ValueError('CREATIVE_COLD_EXACT_NUKE_RETRY_CONTEXT_REQUIRED')
            controller_matches=True
        if (context.get('render_terminal_recovery')!=proof or producer_binding!={k:recovered['source_scope'][k] for k in ('path','sha256')}
                or source.get('artifact_id')!='rectlight_creative_main' or source.get('artifact_version')!=2
                or Path(source.get('producer_control',''))!=control):
            raise ValueError('CREATIVE_COLD_TERMINAL_RECOVERY_MISMATCH')
        from houdini_bridge.controlled_output import verify_controlled_output
        from dcc_task_runtime.canonical import canonical_sha256
        fact=verify_controlled_output(recovered['binding'],task_id=phase['task_id'],operation_id=recovered['binding']['producer_binding']['request_id'],verification_id=VERIFY,
            policy=recovered['policy'],alpha_calibration=recovered['alpha_calibration'],historical_scope=recovered['source_scope'],render_terminal_recovery=proof)
        if canonical_sha256(fact)!=source.get('producer_fact_sha256'):
            raise ValueError('CREATIVE_COLD_TERMINAL_RECOVERY_FACT_MISMATCH')
        producer_matches=True
    if (not path.is_relative_to(allowed) or any(p.is_symlink() for p in (path, *path.parents))
            or source.get('schema') != 'bridge.creative-nuke-source/1'
            or source.get('creative_phase') != phase or context.get('task_id') != phase.get('task_id')
            or source.get('task_id') != context.get('task_id')
            or not controller_matches
            or not producer_matches):
        raise ValueError('CREATIVE_COLD_CONTEXT_BINDING_MISMATCH')
    return context, scope, source


def controlled_artifact_registry(*, fallback=None, registry_root=None, task_id=None, _read_only_binding=False):
    """Reopen the controller's detached H verification source in host/worker.

    The environment is fixed by the owned supervisor, not a render request.
    Its digest detects launch-file drift; authenticated scope accounting and
    the matching deployment/owner stores establish the actual source binding.
    Legacy Nuke-only hosts keep their original operation source.
    纯验证只观察既有生产绑定；宿主初始化默认保留持久化绑定。
    """
    creative_context = creative_cold_context()
    if creative_context is not None:
        context, scope, source = creative_context
        if (task_id is not None and task_id != context['task_id']
                or registry_root is not None and Path(registry_root) != Path(source['producer_ledger'])):
            raise ValueError('CREATIVE_COLD_REGISTRY_BINDING_MISMATCH')
        return _input_artifact_registry(source, scope=scope, task_id=context['task_id'], fallback=fallback, _read_only_binding=_read_only_binding)
    path = os.environ.get('BRIDGE_NUKE_HOST_CONFIG')
    digest = os.environ.get('BRIDGE_NUKE_HOST_CONFIG_SHA256')
    if path is None and digest is None:
        return None
    source = Path(str(path or ''))
    if (not source.is_absolute() or source.is_symlink() or not source.is_file()
            or source.name != 'launch.json' or source.stat().st_size > 1024*1024):
        raise ValueError('CONTROLLED_INPUT_HOST_CONFIG_CHANGED')
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('CONTROLLED_INPUT_HOST_CONFIG_CHANGED')
    config = json.loads(content)
    from dcc_task_runtime.native_scope import NativeScope
    scope = NativeScope((config.get('resource_budget') or {}).get('native_scope'))
    def owned(value):
        candidate = Path(str(value or ''))
        if (not candidate.is_absolute() or any(p.is_symlink() for p in (candidate, *candidate.parents))
                or not candidate.resolve().is_relative_to(scope.root)):
            raise ValueError('CONTROLLED_INPUT_PATH_OUTSIDE_SCOPE')
        return candidate.resolve()
    root = owned(config['task_root'])
    owned(source)
    control, ledger = owned(config['controller_root']), owned(config['ledger_root'])
    identity = config['identity']
    resume_source = (_input_source_payload(config['input_artifact_source'], scope)
                     if 'input_artifact_source' in config else None)
    expected_ledger = (owned(resume_source['producer_ledger']) if resume_source is not None
                       else control / 'artifact_ledger')
    owner_task = identity['task_id']
    feedback_shared = resume_source is None and bool(scope.scope.get('feedback_phase'))
    if feedback_shared:
        from houdini_bridge.official_karma_observation import checked_bytes
        phase=scope.scope['feedback_phase'];delivery=json.loads(checked_bytes(phase['source_delivery']))
        if phase.get('task_id')!=owner_task or delivery.get('task_id')!=owner_task:
            raise ValueError('CONTROLLED_INPUT_FEEDBACK_TASK_MISMATCH')
        expected_ledger=owned(delivery['artifact_ledger'])
    expected_source = scope.scope.get('evidence_source', 'real_host')
    if (source != root / ('nuke-host-'+identity['launch_nonce']) / 'launch.json'
            or ledger != expected_ledger
            or registry_root is not None and Path(registry_root).resolve() != ledger
            or task_id is not None and task_id != owner_task
            or expected_source not in {'software_test','real_host'}
            or config.get('software_api') is not (expected_source == 'software_test')
            or config.get('evidence_source') != ('software_test' if expected_source == 'software_test' else 'native_host')
            or scope.scope.get('execution_authorized') is not True
            or scope.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('CONTROLLED_INPUT_HOST_BINDING_MISMATCH')
    scope.validate_host('nuke', config['version'], config['nuke_executable'], config['supervisor_executable'],
                        project_color=scope.scope.get('project_color'))
    if resume_source is not None:
        return _input_artifact_registry(resume_source, scope=scope, task_id=owner_task, fallback=fallback, _read_only_binding=_read_only_binding)
    deployment = owned(control/'production-hosts.json')
    if not deployment.exists():
        return None
    saved = json.loads(deployment.read_bytes())
    if saved.get('task_id') != owner_task:
        raise ValueError('CONTROLLED_INPUT_DEPLOYMENT_TASK_MISMATCH')
    host = saved.get('hosts', {}).get('houdini')
    if host is None:
        return None
    if (host.get('native_scope') != scope.binding
            or (host.get('resource_budget') or {}).get('native_scope') != scope.binding
            or owned(host.get('task_root')) != root
            or owned(host.get('controller_root')) != control
            or (owned(host.get('ledger_root')) != ledger and not (feedback_shared and owned(host.get('ledger_root'))==control/'artifact_ledger'))
            or host.get('evidence_source') != expected_source
            or host.get('expected_identity', {}).get('task_id') != owner_task):
        raise ValueError('CONTROLLED_INPUT_DEPLOYMENT_BINDING_MISMATCH')
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    from vfx_pipeline.workbuddy_assembly import production_host_client
    boundary = production_host_client(host, control/'host-state')
    if _read_only_binding:
        boundary.observe_task(owner_task)
    else:
        boundary.bind_task(owner_task)
    registry = ArtifactRegistry(ledger)
    def operation_source(operation_id):
        owner = boundary._load_operation_owners().get(operation_id)
        if owner is None:
            return fallback(operation_id) if fallback is not None else None
        if (not isinstance(owner, dict) or owner.get('operation_kind') != 'output-verification'
                or owner.get('task_id') != owner_task or owner.get('evidence_source') != expected_source):
            raise ValueError('CONTROLLED_INPUT_OPERATION_OWNER_MISMATCH')
        parent = boundary._load_operation_owners().get(owner.get('parent_operation_id'))
        if not isinstance(parent, dict) or parent.get('task_id') != owner_task:
            raise ValueError('CONTROLLED_INPUT_OPERATION_OWNER_MISMATCH')
        producer = parent.get('producer_binding') or {}
        if any(host['expected_identity'].get(key) != value for key,value in producer.get('host_identity', {}).items()
               if key != 'scene_epoch'):
            raise ValueError('CONTROLLED_INPUT_PRODUCER_HOST_MISMATCH')
        owned(parent.get('operation_store_path'))
        owned((parent.get('supervisor_binding') or {}).get('directory'))
        owned(producer.get('output_pattern'))
        fact = boundary.call('output.verify.status', {'verification_id': operation_id})['execution_fact']
        if fact.get('task_id') != owner_task or fact.get('evidence_source') != expected_source:
            raise ValueError('CONTROLLED_INPUT_SOURCE_MISMATCH')
        return fact
    registry.set_operation_source(operation_source)
    return registry


def start(*, task_id, task_root, nuke_executable, addon_path, supervisor_executable,
          version='17.0v1', process_generation=1, snapshot=None, budget_seconds=120,
          software_api=False, software_api_dir=None, resource_budget=None, ledger_root=None, scheduler_root=None, project_color=None,
          controller_root=None, input_artifact_source=None, ready_timeout_seconds=None):
    """Only the trusted controller may call this with executable/config paths.

    Software mode is explicit and changes only the launch/native API boundary.
    Production always invokes Nuke -t and never falls back to Python or fake.
    """
    # 独立空后台连接可显式放宽就绪等待；旧调用仍保持原十秒窗口。
    if ready_timeout_seconds is not None and (type(ready_timeout_seconds) not in (int, float)
            or not math.isfinite(ready_timeout_seconds) or not 0 < ready_timeout_seconds <= budget_seconds):
        raise ValueError('TASK_HOST_READY_TIMEOUT_INVALID')
    if not task_id or version!='17.0v1' or type(process_generation) is not int or process_generation<1:
        raise ValueError('invalid task/version/generation')
    executable=_file(nuke_executable);addon=_file(addon_path);supervisor=_file(supervisor_executable)
    if not os.access(executable,os.X_OK) or not os.access(supervisor,os.X_OK): raise ValueError('executable permission required')
    if software_api_dir is not None and software_api is not True: raise ValueError('software API injection is test-only')
    root=Path(task_root).expanduser().resolve()
    if (resource_budget or {}).get('native_scope') is not None:
        from dcc_task_runtime.native_scope import NativeScope
        scope = NativeScope(resource_budget['native_scope'])
        scope.validate_host('nuke', version, executable, supervisor, project_color=project_color)
        if ledger_root is None or scheduler_root is None:
            raise ValueError('NATIVE_SCOPE_HOST_PATH_REQUIRED')
        if any(not Path(path).resolve().is_relative_to(scope.root) for path in (root, ledger_root, scheduler_root,
                *([controller_root] if controller_root is not None else []))):
            raise ValueError('NATIVE_SCOPE_HOST_PATH_OUTSIDE_ROOT')
    if input_artifact_source is not None:
        if (resource_budget or {}).get('native_scope') is None or controller_root is None:
            raise ValueError('CONTROLLED_INPUT_RESUME_SCOPE_REQUIRED')
        source = _input_source_payload(input_artifact_source, scope)
        # 启动前先重验旧登记；独立 Nuke 控制进程及渲染 worker 仍会各自重验。
        input_artifact_registry(source, scope=scope, task_id=str(task_id))
        ledger_root = source['producer_ledger']
    root.mkdir(parents=True,exist_ok=True)
    snapshot_path=None
    if snapshot is not None:
        snapshot_path=_file(snapshot)
        if not snapshot_path.is_relative_to(root) or snapshot_path.suffix.lower()!='.nk': raise ValueError('snapshot outside task root')
    nonce=uuid.uuid4().hex;work=ensure_private_directory(root/('nuke-host-'+nonce))
    identity={'task_id':str(task_id),'session_id':uuid.uuid4().hex,'launch_nonce':nonce,
              'process_generation':process_generation,'plugin_build':hashlib.sha256(addon.read_bytes()).hexdigest()}
    package=Path(__file__).resolve().parent
    config={'identity':identity,'task_root':str(root),'version':version,'nuke_executable':str(executable),'supervisor_executable':str(supervisor),
            'addon_path':str(addon),'render_worker':str(package/'owned_render_worker.py'),
            'software_api':software_api is True,'resource_budget':resource_budget,'snapshot':str(snapshot_path) if snapshot_path else None,
            'ready':str(work/'ready.json'),'stop_request':str(work/'stop-request.json'),'token':secrets.token_urlsafe(32),
            'evidence_source':'software_test' if software_api is True else 'native_host'}
    controlled = controller_root is not None and (resource_budget or {}).get('native_scope') is not None
    if controlled:
        config.update(controller_root=str(Path(controller_root).resolve()), ledger_root=str(Path(ledger_root).resolve()))
    if input_artifact_source is not None:
        config['input_artifact_source'] = dict(input_artifact_source)
    _write(work/'launch.json',config)
    import dcc_task_runtime
    paths=[str(package.parent),str(Path(dcc_task_runtime.__file__).resolve().parent.parent)]
    if controlled:
        snapshot=package.parents[2]
        paths.extend(str(snapshot/name/'src') for name in ('houdini-bridge','vfx-pipeline'))
    if software_api is True:
        if not software_api_dir or not (Path(software_api_dir)/'nuke.py').is_file(): raise ValueError('explicit software API directory required')
        paths.insert(0,str(Path(software_api_dir).resolve()))
    env=dict(os.environ,PYTHONPATH=os.pathsep.join(dict.fromkeys(paths)),PYTHONNOUSERSITE='1',
             NUKE_BRIDGE_INSTANCES_DIR=str(work/'instances'),BRIDGE_SKILLS_STATE_ROOT=str(root/'state'))
    if (resource_budget or {}).get('native_scope') is not None:
        env.update(TMPDIR=str(ensure_private_directory(work/'tmp')), PYTHONDONTWRITEBYTECODE='1')
    if ledger_root is not None: env['BRIDGE_ARTIFACT_LEDGER_ROOT']=str(Path(ledger_root).resolve())
    if scheduler_root is not None: env['BRIDGE_SKILLS_SCHEDULER_ROOT']=str(Path(scheduler_root).resolve())
    for name in ('BRIDGE_NUKE_HOST_CONFIG','BRIDGE_NUKE_HOST_CONFIG_SHA256'):
        env.pop(name,None)
    # The embedded interpreter must resolve its own stdlib; a controller-side
    # PYTHONEXECUTABLE (e.g. pinning a stub's self-report) corrupts Nuke's
    # module search and breaks builtin extensions like binascii.
    for name in ('PYTHONEXECUTABLE','PYTHONHOME'):
        env.pop(name,None)
    if controlled:
        env['BRIDGE_NUKE_HOST_CONFIG']=str(work/'launch.json')
        env['BRIDGE_NUKE_HOST_CONFIG_SHA256']=hashlib.sha256((work/'launch.json').read_bytes()).hexdigest()
    command=[str(executable)]+([] if software_api else ['-t'])+[str(package/'task_host_worker.py'),str(work/'launch.json')]
    scope_options = ({"scope_role":"nuke-host", "scope_heavy":False}
                     if (resource_budget or {}).get("native_scope") is not None else {})
    handle=owned_process.launch(command,directory=work/'supervisor',identity=identity,
        supervisor_executable=str(supervisor),env=env,budget_seconds=budget_seconds,resource_budget=resource_budget,**scope_options)
    deadline=time.monotonic()+(ready_timeout_seconds if ready_timeout_seconds is not None else
        budget_seconds if (resource_budget or {}).get('native_scope') is not None else min(10,budget_seconds))
    ready_error=None
    try:
        while time.monotonic()<deadline:
            if handle.poll() is not None:
                error=(work/'worker-error.log').read_text() if (work/'worker-error.log').exists() else 'no worker error receipt'
                raise RuntimeError('task host exited before ready: '+error)
            if (work/'ready.json').is_file():
                try:
                    ready=json.loads((work/'ready.json').read_text(encoding='utf-8'))
                except OSError as exc:
                    if os.name!='nt' or not (getattr(exc,'winerror',None) in (5,32,33)
                            or isinstance(exc,PermissionError) and exc.errno==errno.EACCES):
                        raise
                    ready_error=exc
                    time.sleep(.01)
                    continue
                expected=dict(identity,pid=handle.pid,scene_epoch=1,version=version)
                if ready.get('task_host_identity')!=expected: raise ValueError('ready identity mismatch')
                client=NukeClient(ready['port'],token=config['token'])
                health=client.health()
                if health.get('task_host_identity')!=expected: raise ValueError('handshake identity mismatch')
                receipt={'work_dir':str(work),'port':ready['port'],'token':config['token'],
                         'expected_identity':expected,'evidence_source':config['evidence_source'],
                         'supervisor_identity':identity,'supervisor_dir':str(work/'supervisor')}
                if input_artifact_source is not None:
                    # 返回启动文件实际采用的输入账本，不能由当前控制端目录覆盖。
                    receipt.update(ledger_root=config['ledger_root'], producer_controller=source['producer_control'])
                _write(work/'host.json',receipt)
                return receipt
            time.sleep(.01)
        if ready_error is not None:
            raise RuntimeError('task host ready unreadable') from ready_error
        raise RuntimeError('task host ready timeout')
    except BaseException:
        handle.terminate()
        try: handle.wait(timeout=4)
        except Exception: pass
        raise


def reconnect(work_dir):
    work=Path(work_dir).resolve()
    if (work/'host.json').is_file():
        receipt=json.loads((work/'host.json').read_text())
    else:
        # Recover the launch->ready->controller-receipt interruption window
        # from the durable launch intent and supervisor-observed child PID.
        config=json.loads((work/'launch.json').read_text())
        ready=json.loads((work/'ready.json').read_text())
        observed=owned_process.OwnedProcessHandle(work/'supervisor',config['identity'])
        expected=dict(config['identity'],pid=observed.pid,scene_epoch=1,version=config['version'])
        if ready.get('task_host_identity')!=expected: raise ValueError('recovery ready identity mismatch')
        receipt={'work_dir':str(work),'port':ready['port'],'token':config['token'],
                 'expected_identity':expected,'evidence_source':config['evidence_source'],
                 'supervisor_identity':config['identity'],'supervisor_dir':str(work/'supervisor')}
    handle=owned_process.OwnedProcessHandle(work/'supervisor',receipt['supervisor_identity'])
    if handle.poll() is not None: raise RuntimeError('owned host is stopped')
    health=NukeClient(receipt['port'],token=receipt['token']).health()
    if health.get('task_host_identity')!=receipt['expected_identity']: raise ValueError('host identity/scene epoch changed')
    launch_path = work / 'launch.json'
    if launch_path.is_file():
        content = launch_path.read_bytes()
        config = json.loads(content)
        if config.get('input_artifact_source') is not None:
            # 重连从原启动配置及其固定摘要恢复同一输入来源，不沿用可能陈旧的部署派生值。
            environment = json.loads((work / 'supervisor/intent.json').read_bytes()).get('env') or {}
            if (launch_path.is_symlink() or environment.get('BRIDGE_NUKE_HOST_CONFIG') != str(launch_path)
                    or environment.get('BRIDGE_NUKE_HOST_CONFIG_SHA256') != hashlib.sha256(content).hexdigest()
                    or config.get('identity') != receipt['supervisor_identity']):
                raise ValueError('CONTROLLED_INPUT_HOST_CONFIG_CHANGED')
            from dcc_task_runtime.native_scope import NativeScope
            scope = NativeScope((config.get('resource_budget') or {}).get('native_scope'))
            source = _input_source_payload(config['input_artifact_source'], scope)
            if config.get('ledger_root') != source['producer_ledger']:
                raise ValueError('CONTROLLED_INPUT_RESUME_LEDGER_MISMATCH')
            receipt.update(ledger_root=config['ledger_root'], producer_controller=source['producer_control'])
    elif receipt.get('producer_controller') is not None:
        raise ValueError('CONTROLLED_INPUT_HOST_CONFIG_CHANGED')
    _write(work/'host.json',receipt)
    return receipt


def stop(work_dir, *, timeout=5):
    work=Path(work_dir).resolve();config=json.loads((work/'launch.json').read_text())
    handle=owned_process.OwnedProcessHandle(work/'supervisor',config['identity'])
    forced = False
    if handle.poll() is None:
        request = config.get('stop_request')
        if request is not None:
            if Path(request) != work/'stop-request.json':
                raise ValueError('TASK_HOST_STOP_PATH_INVALID')
            _write(Path(request), {'schema':'bridge.nuke.task-host-stop/1', 'identity':config['identity']})
            try: handle.wait(timeout=timeout)
            except (TimeoutError, subprocess.TimeoutExpired):
                forced = True
                handle.terminate()
        else:
            forced = True
            handle.terminate()
    try: handle.wait(timeout=timeout)
    except Exception:
        return {'stopped':False,'status':'STOP_UNKNOWN','work_dir':str(work)}
    if (config.get('resource_budget') or {}).get('native_scope') is not None:
        from dcc_task_runtime.native_scope import NativeScope
        NativeScope(config['resource_budget']['native_scope']).check()
    return {'stopped':True,'status':'STOP_FORCED' if forced else 'STOP_CONFIRMED',
            'receipt':handle.receipt(),'work_dir':str(work)}


_COLD_INPUT_SEAL = object()


def _cold_bytes(record):
    """只读记录也允许真实空日志，保持普通原件的严格身份检查。"""
    from houdini_bridge.official_karma_observation import checked_bytes
    if record.get('bytes') != 0:return checked_bytes(record)
    import stat
    if (type(record) is not dict or set(record)!={'path','bytes','sha256'} or type(record['bytes']) is not int
            or record['sha256']!=hashlib.sha256(b'').hexdigest()):raise ValueError('COLD_INPUT_RECORD_INVALID')
    path=Path(record['path'])
    if not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('COLD_INPUT_RECORD_INVALID')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        before=os.fstat(fd);after=path.stat()
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=0 or os.read(fd,1)
                or any(getattr(before,k)!=getattr(after,k) or getattr(before,k)!=getattr(os.fstat(fd),k) for k in fields)):
            raise ValueError('COLD_INPUT_RECORD_CHANGED')
        return b''
    finally:os.close(fd)


def _cold_record(path):
    path=Path(path);raw=path.read_bytes()
    record={'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    _cold_bytes(record);return record


@contextmanager
def _capture_cold_reads(scope):
    """仅本线程一次完整验证期间记录成功读取，绝不追认后来按路径读到的新内容。"""
    from houdini_bridge.official_karma_observation import checked_bytes
    from dcc_task_runtime.geometry_recovery import _bytes
    from vfx_pipeline.geometry_render_resume import _read
    if sys.getprofile() is not None:raise ValueError('COLD_INPUT_PROFILE_ALREADY_ACTIVE')
    readers={checked_bytes.__code__,_bytes.__code__,_read.__code__}
    paths={Path.read_bytes.__code__,Path.read_text.__code__};pending={};observed={};capture_failed=[]
    dynamic={scope.state_path,scope.journal_path,scope.anchor_path,scope.root/'geometry-state.json',scope.root/'artifact_ledger/artifacts.sqlite3'}
    def add(record):
        path=Path(record['path'])
        if path in dynamic:return
        previous=observed.get(str(path))
        if previous is not None and previous!=record:raise ValueError('COLD_INPUT_ACTUAL_READ_CONFLICT')
        observed[str(path)]=copy.deepcopy(record)
    def stamp(path):
        info=path.stat();return tuple(getattr(info,key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink'))
    def record_event(frame,event,result):
        code=frame.f_code
        if code not in readers and code not in paths:return
        if event=='call' and code in paths:
            path=frame.f_locals.get('self')
            if isinstance(path,Path) and path.is_absolute():
                try:identity=stamp(path)
                except OSError:identity=None  # 可选缺失仍由原reader/fallback处理。
                pending[id(frame)]=(path,identity)
            return
        if event!='return':return
        if code in readers:
            record=frame.f_locals.get('record')
            if (isinstance(result,bytes) and isinstance(record,dict) and set(record)=={'path','bytes','sha256'}
                    and len(result)==record['bytes'] and hashlib.sha256(result).hexdigest()==record['sha256']):add(record)
            return
        prior=pending.pop(id(frame),None)
        if prior is None or not isinstance(result,(bytes,str)):return
        path,identity=prior
        if identity is None or stamp(path)!=identity:raise ValueError('COLD_INPUT_ACTUAL_READ_CHANGED')
        if code is Path.read_bytes.__code__:
            raw=result
        else:
            # read_text的成功返回只在同一文件身份及严格解码/换行等价时转换成字节记录。
            import locale
            encoding=frame.f_locals.get('encoding') or locale.getpreferredencoding(False)
            if encoding=='locale':encoding=locale.getpreferredencoding(False)
            errors=frame.f_locals.get('errors') or 'strict'
            raw=path.read_bytes()
            if errors!='strict' or raw.decode(encoding,errors).replace('\r\n','\n').replace('\r','\n')!=result or stamp(path)!=identity:
                raise ValueError('COLD_INPUT_TEXT_READ_AMBIGUOUS')
        record={'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        add(record)
    capturing=[True]
    def profile(frame,event,result):
        # 大量非读取事件只做本地过滤，仍覆盖每个已知reader的成功返回及hook篡改。
        if event=='c_call':
            if capturing[0] and result is sys.setprofile:capture_failed.append('profile_replaced')
            return
        if capture_failed:return
        if event=='call':
            if frame.f_code not in paths:return
        elif event=='return':
            if frame.f_code not in readers and frame.f_code not in paths:return
        else:return
        try:record_event(frame,event,result)
        except BaseException as error:
            # Python会在回调异常时自动卸载hook；锁存并在外层拒绝，不能让validator吞错后接纳半份读集。
            capture_failed.append(type(error).__name__)
    sys.setprofile(profile)
    try:
        yield observed
        capturing[0]=False
        if capture_failed or pending or sys.getprofile() is not profile:
            raise ValueError('COLD_INPUT_CAPTURE_INCOMPLETE')
    finally:
        sys.setprofile(None);pending.clear()



def _cold_read_set(source, scope, context_record, extra, observed=None, *, _record_limit=4096):
    """只固定实际成功读集和直接受签闭包；不递归解释历史日志里的路径型声明。"""
    if type(_record_limit) is not int or _record_limit not in (4096,8192):raise ValueError('COLD_INPUT_RECORD_LIMIT_INVALID')
    authority=source['registration_implementation']['authorization'];payload=json.loads(_cold_bytes(authority))['payload']
    formal=Path(source['registration_implementation']['package_root']);records={}
    dynamic={scope.state_path,scope.journal_path,scope.anchor_path,scope.root/'geometry-state.json',scope.root/'artifact_ledger/artifacts.sqlite3'}
    def collect(value):
        if isinstance(value,dict):
            if set(value)=={'path','bytes','sha256'}:
                if Path(value['path']) in dynamic:return
                old=records.get(value['path'])
                if old is not None and old!=value:raise ValueError('COLD_INPUT_READ_SET_CONFLICT')
                if old is None:
                    if len(records)>=_record_limit:raise ValueError('COLD_INPUT_READ_SET_LIMIT')
                    _cold_bytes(value);records[value['path']]=copy.deepcopy(value)
            else:
                for child in value.values():collect(child)
        elif isinstance(value,(list,tuple)):
            for child in value:collect(child)
    collect([source,context_record,authority,payload['source'],payload['request'],payload['source_closure'],extra,list((observed or {}).values())])
    roots={formal}|{Path(r['path']).parent for r in records.values() if Path(r['path']).name=='runtime-manifest.json'}
    indexes=[(root,_cold_record(root/'runtime-manifest.json')) for root in sorted(roots)]
    indexes.append((Path(source['producer_control'])/'snapshot',source['producer_snapshot_manifest']))
    for root,index_record in indexes:
        collect(index_record)
        for item in json.loads(_cold_bytes(index_record))['files']:
            path=root/item['path']
            if path!=path.resolve() or not path.is_relative_to(root):raise ValueError('COLD_INPUT_INDEX_PATH_INVALID')
            record=_cold_record(path)
            if record['sha256']!=item['sha256'] or item.get('bytes',record['bytes'])!=record['bytes']:
                raise ValueError('COLD_INPUT_INDEX_CHANGED')
            collect(record)
    original=json.loads(_cold_bytes(payload['source']))
    return [records[key] for key in sorted(records)],[original['journal_prefix']]


def _cold_binding_identity(binding):
    result=copy.deepcopy(binding)
    ticket=result.get('current_ticket')
    if isinstance(ticket,dict):
        result['current_ticket']={key:ticket.get(key) for key in ('id','role','directory','identity','heavy','parent','admitted_at')}
    return result


def _owned_nr_binding(scope,snapshot_record,contract_record,env):
    """当前worker只认自己的签名进程，实时收费字段不作为固定身份。"""
    from dcc_task_runtime import owned_process
    from vfx_pipeline.geometry_seed_cold_resume import verify_cold_worker_binding
    native=scope;operation=env['BRIDGE_NUKE_TASK_ID'];state=native._read()
    expected=native.root/'state/nuke_renders'/(str(operation)+'.supervisor')
    tickets=[t for t in state['tickets'] if t['role']=='nuke-render' and t['directory']==str(expected)]
    if len(tickets)!=1 or tickets[0]['stopped_at'] is not None or state.get('closed_reason') is not None:
        raise ValueError('COLD_INPUT_CURRENT_NR_REQUIRED')
    ticket=tickets[0];started=owned_process.read_receipt(expected,'started',identity=ticket['identity'])
    intent=json.loads((expected/'intent.json').read_text())
    identity=ticket['identity']
    if (not started or started.get('pid')!=os.getpid() or identity.get('task_id')!=operation
            or identity.get('operation_id')!=operation or identity.get('snapshot_sha256')!=snapshot_record['sha256']
            or identity.get('input_contract_sha256')!=contract_record['sha256']
            or intent.get('identity')!=identity or hashlib.sha256(owned_process._canonical(intent['command'])).hexdigest()!=started.get('argv_sha256')
            or any(intent.get('env',{}).get(key)!=value for key,value in env.items())):
        raise ValueError('COLD_INPUT_OWNED_NR_IDENTITY_CHANGED')
    bound=verify_cold_worker_binding(native,operation_id=operation,snapshot_record=snapshot_record,
        input_contract_record=contract_record,result_path=env['BRIDGE_NUKE_RESULT_FILE'])
    if bound.get('observation_only') is True:raise ValueError('COLD_INPUT_EXECUTION_CONTEXT_REQUIRED')
    return _cold_binding_identity(bound)


class _OwnedColdInputs:
    """仅固定worker本次调用持有；只读预检永远不能取得原生执行资格。"""
    __slots__ = ('_seal','_active','_observation','_scope','_source','_registry','_records',
                 '_context_record','_env','_snapshot','_contract_record','_binding','_nuke','_node','_write','_prefix_records')
    def __init__(self, seal, scope, source, registry, context_record, snapshot, contract_record,
                 binding, observation, observed=None):
        if seal is not _COLD_INPUT_SEAL:raise ValueError('COLD_INPUT_CONTEXT_REQUIRED')
        self._seal,self._active,self._observation = seal,True,observation
        self._scope,self._source,self._registry = scope,copy.deepcopy(source),registry
        self._context_record,self._snapshot,self._contract_record = context_record,snapshot,contract_record
        self._binding = _cold_binding_identity(binding)
        self._env = {key:os.environ.get(key) for key in ('BRIDGE_CREATIVE_COLD_CONTEXT','BRIDGE_CREATIVE_COLD_CONTEXT_SHA256',
            'BRIDGE_NUKE_TASK_ID','BRIDGE_NUKE_RESULT_FILE','BRIDGE_NUKE_INPUT_CONTRACT','BRIDGE_NUKE_INPUT_CONTRACT_SHA256')}
        self._nuke,self._node,self._write = None,None,None
        self._records,self._prefix_records = _cold_read_set(source,scope,context_record,[snapshot,contract_record,binding.get('readset',[])],observed)
    def _valid(self):
        if self._seal is not _COLD_INPUT_SEAL or not self._active:
            raise ValueError('COLD_INPUT_CONTEXT_REQUIRED')
        if any(os.environ.get(key)!=value for key,value in self._env.items()):
            raise ValueError('COLD_INPUT_CONTEXT_ENV_CHANGED')
    @property
    def scope(self):
        self._valid();return self._scope
    def close(self):
        self._active=False;self._registry=None;self._nuke=None;self._node=None
    def _worker_binding(self):
        return _owned_nr_binding(self._scope,self._snapshot,self._contract_record,self._env)
    def bind_native(self,nuke,node):
        """Root和Write仍由已打开快照实际读回，前后每个输入栅栏复验。"""
        self._valid()
        from .operation_receipts import native_write_readback
        self._nuke,self._node,self._write=nuke,node,native_write_readback(node)
        expected=str(Path(self._source['producer_control']).parent/'saves/nuke.%04d.exr')
        if str(node['file'].value())!=expected:raise ValueError('COLD_INPUT_WRITE_PATTERN_CHANGED')
        self._native_fence()
    def _native_fence(self):
        if self._nuke is None:return
        from .task_host_worker import _root_ocio
        from .operation_receipts import native_write_readback
        _root_ocio(self._nuke,self._scope.scope['native_color_tokens']['houdini_static_config'],
            self._scope.scope['project_color']['colorspace'],configure=False)
        if native_write_readback(self._node)!=self._write:raise ValueError('COLD_INPUT_WRITE_CHANGED')
    def validate_contract(self,contract):
        self._valid()
        from houdini_bridge.official_karma_observation import checked_bytes
        from vfx_pipeline import geometry_registration_resume as registration
        from dcc_task_runtime.geometry_budget_addendum import _prefix
        from .operation_receipts import _validate_registered_input_contract_with_registry
        for record in self._records:_cold_bytes(record)
        for record in self._prefix_records:
            path=Path(record['path'])
            if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
                raise ValueError('COLD_INPUT_PREFIX_CHANGED')
            with path.open('rb') as stream:raw=stream.read(record['bytes'])
            if len(raw)!=record['bytes'] or hashlib.sha256(raw).hexdigest()!=record['sha256']:
                raise ValueError('COLD_INPUT_PREFIX_CHANGED')
        authority=self._source['registration_implementation']['authorization']
        signed=json.loads(checked_bytes(authority));payload=signed['payload']
        if not hmac.compare_digest(str(signed['signature']),registration._sign(self._scope,payload)):
            raise ValueError('COLD_INPUT_AUTHORITY_CHANGED')
        original=json.loads(checked_bytes(payload['source']))
        state=self._scope._read();prefix=_prefix(self._scope,original['journal_prefix'],original['accounting_envelope'])['state']
        if state['tickets'][:14]!=prefix['tickets']:raise ValueError('COLD_INPUT_ORIGINAL_PREFIX_CHANGED')
        session=json.loads((self._scope.root/'geometry-state.json').read_text())
        completed=session.get('completed',[])
        if len(completed) not in (1,2):raise ValueError('COLD_INPUT_ACCEPTED_SOURCE_CHANGED')
        accepted=session.get('jobs',{}).get(completed[0],{})
        if (accepted.get('state')!='COMPLETE' or accepted.get('result')!=original['base_result']
                or accepted.get('acceptance')!=original['base_acceptance']):
            raise ValueError('COLD_INPUT_ACCEPTED_SOURCE_CHANGED')
        if self._observation:
            from vfx_pipeline.geometry_seed_cold_resume import verify_cold_observation_binding
            bound=_cold_binding_identity(verify_cold_observation_binding(self._scope,operation_id=self._env['BRIDGE_NUKE_TASK_ID'],
                snapshot_record=self._snapshot,input_contract_record=self._contract_record,result_path=self._env['BRIDGE_NUKE_RESULT_FILE']))
            if bound!=self._binding:raise ValueError('COLD_INPUT_OBSERVATION_BINDING_CHANGED')
        else:
            bound=self._worker_binding()
            if bound!=self._binding:raise ValueError('COLD_INPUT_WORKER_BINDING_CHANGED')
            self._scope.check()
        if (contract!=json.loads(checked_bytes(self._contract_record))
                or contract.get('owner_task_id')!=self._scope.scope['task_id']
                or contract.get('registry_root')!=str(self._scope.root/'artifact_ledger')):
            raise ValueError('COLD_INPUT_CONTRACT_CHANGED')
        self._native_fence()
        return _validate_registered_input_contract_with_registry(contract,self._registry)
    def authorize_execute(self):
        self._valid()
        if self._observation:raise ValueError('COLD_INPUT_OBSERVATION_CANNOT_EXECUTE')
        if self._worker_binding()!=self._binding:raise ValueError('COLD_INPUT_WORKER_BINDING_CHANGED')
        self._scope.check()


@contextmanager
def _owned_cold_inputs(snapshot, *, observation=False):
    """只优化明确NR-only source2；其它worker和所有公开验证入口保持原全验。"""
    from houdini_bridge.official_karma_observation import file_record,checked_bytes
    from dcc_task_runtime.native_scope import NativeScope
    path=Path(str(os.environ.get('BRIDGE_CREATIVE_COLD_CONTEXT') or ''))
    if not path.is_absolute() or not path.is_file():
        yield None;return
    record=file_record(path);context=json.loads(checked_bytes(record))
    if context.get('schema')!='bridge.geometry-cold-context/1':
        yield None;return
    if record['sha256']!=os.environ.get('BRIDGE_CREATIVE_COLD_CONTEXT_SHA256'):
        raise ValueError('CREATIVE_COLD_CONTEXT_CHANGED')
    scope=NativeScope(context['native_scope']);source=_input_source_payload(context['input_artifact_source'],scope)
    if source.get('schema')!='bridge.geometry-nuke-source/2':
        yield None;return
    if _cold_proof_required(scope):
        with _proved_cold_inputs(snapshot,observation=observation) as cap:yield cap
        return
    state=scope._read()
    if not observation and 'geometry_seed_cold_recovery' not in state:
        yield None;return
    control,_=_geometry_source_header(source,scope,context['task_id'])
    if (set(context)!={'schema','native_scope','task_id','input_artifact_source'}
            or path!=control/'cold-context.json' or record['bytes']>64*1024):
        raise ValueError('GEOMETRY_COLD_CONTEXT_BINDING_MISMATCH')
    operation=os.environ.get('BRIDGE_NUKE_TASK_ID');result=Path(str(os.environ.get('BRIDGE_NUKE_RESULT_FILE') or ''))
    contract_path=Path(str(os.environ.get('BRIDGE_NUKE_INPUT_CONTRACT') or ''))
    contract_record=file_record(contract_path)
    if (not result.is_absolute() or contract_path.parent!=result.parent or contract_path.name!=str(operation)+'.inputs.json'
            or contract_record['sha256']!=os.environ.get('BRIDGE_NUKE_INPUT_CONTRACT_SHA256')):
        raise ValueError('COLD_INPUT_CONTRACT_ENV_CHANGED')
    snapshot_record=file_record(Path(snapshot));binding={}
    if observation:
        from vfx_pipeline.geometry_seed_cold_resume import verify_cold_observation_binding
        binding=verify_cold_observation_binding(scope,operation_id=operation,snapshot_record=snapshot_record,
            input_contract_record=contract_record,result_path=str(result))
    else:
        env={key:os.environ.get(key) for key in ('BRIDGE_CREATIVE_COLD_CONTEXT','BRIDGE_CREATIVE_COLD_CONTEXT_SHA256',
            'BRIDGE_NUKE_TASK_ID','BRIDGE_NUKE_RESULT_FILE','BRIDGE_NUKE_INPUT_CONTRACT','BRIDGE_NUKE_INPUT_CONTRACT_SHA256')}
        binding=_owned_nr_binding(scope,snapshot_record,contract_record,env)
    with _capture_cold_reads(scope) as observed:
        registry=_input_artifact_registry(source,scope=scope,task_id=context['task_id'],
            observe_completed=observation,_read_only_binding=True)
    capability=_OwnedColdInputs(_COLD_INPUT_SEAL,scope,source,registry,record,snapshot_record,contract_record,binding,observation,observed)
    try:yield capability
    finally:capability.close()


# 046的完整来源认证留在原生准入之前；证明只在当前调用和既有nonce内封口。
_COLD_PROOF_PATH_ENV='BRIDGE_NUKE_CONTROLLER_PROOF'
_COLD_PROOF_SHA_ENV='BRIDGE_NUKE_CONTROLLER_PROOF_SHA256'
_COLD_NATIVE_ENV={'BRIDGE_NATIVE_SCOPE_BINDING','BRIDGE_NATIVE_SCOPE_TICKET'}
_COLD_PROOF_ENV={_COLD_PROOF_PATH_ENV,_COLD_PROOF_SHA_ENV}
_COLD_CONTROLLER_SEAL=object()
_COLD_PROOF_SCHEMA='bridge.geometry-cold-input-proof/1'


def _cold_proof_sign(scope,payload):
    """执行与观察使用不同子密钥，观察证明不能被真实worker消费。"""
    domain=('bridge.geometry-cold-input-proof.'+payload['mode']+'/1\x00').encode()
    key=hmac.new(scope._key(),domain,hashlib.sha256).digest()
    return hmac.new(key,scope._canonical(payload),hashlib.sha256).hexdigest()


def _cold_env_projection(env):
    """仅记录环境键集合与摘要；Native两键随后由真实票据单独核验。"""
    base={key:value for key,value in env.items() if key not in _COLD_PROOF_ENV|_COLD_NATIVE_ENV}
    return {'keys':sorted(base),'sha256':hashlib.sha256(owned_process._canonical(base)).hexdigest()}


def _cold_slot_binding(slot):
    if not isinstance(slot,dict) or set(slot)!={'owner_root','operation_id','token','generation'}:
        raise ValueError('COLD_PROOF_SLOT_REQUIRED')
    return {key:slot[key] for key in ('owner_root','operation_id','generation')}|{'token_sha256':hashlib.sha256(str(slot['token']).encode()).hexdigest()}


def _cold_proof_write(path,scope,payload):
    path=Path(path)
    if not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('COLD_PROOF_PATH_INVALID')
    raw=scope._canonical({'payload':payload,'signature':_cold_proof_sign(scope,payload)})
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return _cold_record(path)


class _ControllerColdInputs:
    """仅当前控制器栈持有完整工厂结果；nonce产生后签字，不再运行第二次工厂。"""
    def __init__(self,seal,source_record,scope,task_id,source,context,registry,observed,observation):
        if seal is not _COLD_CONTROLLER_SEAL:raise ValueError('COLD_CONTROLLER_CAP_REQUIRED')
        self._active=True;self._seal=seal;self._scope=scope;self._task_id=task_id
        self._source_record=copy.deepcopy(source_record);self._source=copy.deepcopy(source);self._context=context
        self._registry=registry;self._observed=observed;self._observation=observation;self._contract=None;self._authoritative_records=[];self._capture=None
    def _valid(self):
        if self._seal is not _COLD_CONTROLLER_SEAL or not self._active:raise ValueError('COLD_CONTROLLER_CAP_REQUIRED')
    @property
    def registry(self):self._valid();return self._registry
    def _finish_capture(self):
        capture,self._capture=self._capture,None
        if capture is not None:capture.__exit__(None,None,None)
    def close(self):
        try:self._finish_capture()
        finally:self._active=False;self._registry=None
    def freeze_contract(self,contract):
        self._valid()
        from .operation_receipts import _validate_registered_input_contract_with_registry
        _validate_registered_input_contract_with_registry(contract,self._registry)
        if self._contract is not None and self._contract!=contract:raise ValueError('COLD_CONTROLLER_CONTRACT_CHANGED')
        self._contract=copy.deepcopy(contract)
        return copy.deepcopy(contract)
    def _seal_proof(self,*,snapshot_record,contract_record,identity,command,env,slot,result_path,directory=None):
        self._valid()
        from vfx_pipeline.geometry_seed_cold_resume import verify_cold_pre_admission_binding
        from dcc_task_runtime.canonical import canonical_sha256
        scope=self._scope;operation=env.get('BRIDGE_NUKE_TASK_ID');contract=json.loads(_cold_bytes(contract_record))
        if self._contract is None or contract!=self._contract:raise ValueError('COLD_CONTROLLER_CONTRACT_REQUIRED')
        self.freeze_contract(contract)
        binding=verify_cold_pre_admission_binding(scope,operation_id=operation,snapshot_record=snapshot_record,
            input_contract_record=contract_record,result_path=str(result_path),observation=self._observation)
        if binding['input_source']!=self._source_record:raise ValueError('COLD_CONTROLLER_SOURCE_CHANGED')
        runtime=_cold_execution_code(scope,binding,snapshot_record,command,observation=self._observation)
        fact_path=Path(self._source['producer_control'])/'host-state'/('verified-output-'+self._source['registry_operation_receipt']['operation_id']+'.json')
        fact_record=_cold_record(fact_path);fact=json.loads(_cold_bytes(fact_record))
        if canonical_sha256(fact)!=self._source['producer_fact_sha256'] or fact.get('task_id')!=self._task_id:
            raise ValueError('COLD_CONTROLLER_FACT_CHANGED')
        # 合同typed冻结和最后的来源身份检查均在同一次捕获中；随后才封口。
        self._finish_capture()
        # 仅此处已经认证的047绑定扩内部原件计数；不改任何Native次数、时间或磁盘额度。
        record_limit=8192 if binding['authority']['path']==str(scope.root/'geometry-prelaunch-tail-authorization.json') else 4096
        records,prefixes=_cold_read_set(self._source,scope,self._context,
            [self._source_record,snapshot_record,contract_record,binding['readset'],self._authoritative_records,runtime],self._observed,_record_limit=record_limit)
        records={r['path']:r for r in records}
        if str(fact_path) in records and records[str(fact_path)]!=fact_record:raise ValueError('COLD_CONTROLLER_FACT_BYTES_CHANGED')
        records[str(fact_path)]=fact_record
        state=scope._read();raw=scope.journal_path.read_bytes()
        if len(state['tickets'])!=16 or any(t['stopped_at'] is None for t in state['tickets']):raise ValueError('COLD_PROOF_PRE_ADMISSION_REQUIRED')
        if not self._observation and state.get('closed_reason') is not None:raise ValueError('COLD_PROOF_SCOPE_CLOSED')
        session=json.loads((scope.root/'geometry-state.json').read_text());base=session['completed'][0];accepted=session['jobs'][base]
        mode='observation' if self._observation else 'execution'
        if self._observation:
            if identity is not None or slot is not None or command:raise ValueError('COLD_OBSERVATION_REAL_OWNER_FORBIDDEN')
            target=Path(directory)/('observation-'+uuid.uuid4().hex+'.proof.json')
            if target.is_relative_to(scope.root):raise ValueError('COLD_OBSERVATION_PROOF_OUTSIDE_SCOPE_REQUIRED')
        else:
            if (not isinstance(identity,dict) or not identity.get('launch_nonce') or identity.get('task_id')!=operation
                    or identity.get('operation_id')!=operation or identity.get('snapshot_sha256')!=snapshot_record['sha256']
                    or identity.get('input_contract_sha256')!=contract_record['sha256']):raise ValueError('COLD_PROOF_NONCE_BINDING_REQUIRED')
            target=scope.root/'state/nuke_renders'/(operation+'.'+identity['launch_nonce']+'.input-proof.json')
        projection=_cold_session_projection(scope,binding,runtime['request'],observation=self._observation)
        payload={'schema':_COLD_PROOF_SCHEMA,'mode':mode,'session_projection':projection,'execution_code':runtime,'native_scope':scope.binding,'owner_task_id':self._task_id,
            'operation_id':operation,'binding':binding,'source':self._source_record,'context':self._context,
            'snapshot':snapshot_record,'contract':contract_record,'result_path':str(result_path),'identity':copy.deepcopy(identity),
            'command_sha256':hashlib.sha256(owned_process._canonical(command)).hexdigest(),'environment':_cold_env_projection(env),
            'slot':None if slot is None else _cold_slot_binding(slot),'fixed_records':[records[key] for key in sorted(records)],
            'original_prefixes':prefixes,'accounting_envelope':json.loads(scope.state_path.read_bytes()),
            'accounting_prefix':{'path':str(scope.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
            'producer_fact':fact_record,'producer_fact_sha256':self._source['producer_fact_sha256'],
            'accepted_base':{'operation_id':base,'result':accepted['result'],'acceptance':accepted['acceptance']},
            'registry_implementation':copy.deepcopy(self._source['registration_implementation'])}
        return _cold_proof_write(target,scope,payload)
    def sign_execution_proof(self,**kwargs):
        if self._observation:raise ValueError('COLD_OBSERVATION_CANNOT_SIGN_EXECUTION')
        return self._seal_proof(**kwargs)
    def sign_observation_proof(self,**kwargs):
        if not self._observation:raise ValueError('COLD_EXECUTION_CANNOT_SIGN_OBSERVATION')
        return self._seal_proof(identity=None,command=[],slot=None,**kwargs)


@contextmanager
def _controller_cold_inputs(source_record,*,scope,task_id,fallback=None,observation=False):
    """完整来源认证、typed来源和读取证明只在原生准入前执行一次。"""
    source=_input_source_payload(source_record,scope);control,_=_geometry_source_header(source,scope,task_id)
    context=_cold_record(control/'cold-context.json')
    if json.loads(_cold_bytes(context))!={'schema':'bridge.geometry-cold-context/1','native_scope':scope.binding,
            'task_id':task_id,'input_artifact_source':source_record}:raise ValueError('COLD_CONTROLLER_CONTEXT_CHANGED')
    # 固定闭包由已验schema展开；动态alias alpha等不依赖函数同名猜测。
    from vfx_pipeline.geometry_cold_preflight_runtime import authoritative_input_records
    authoritative=authoritative_input_records(scope,source)
    capture=_capture_controller_records(scope);observed=capture.__enter__();cap=None
    try:
        registry=_input_artifact_registry(source,scope=scope,task_id=task_id,fallback=fallback,
            observe_completed=observation,_read_only_binding=True)
        cap=_ControllerColdInputs(_COLD_CONTROLLER_SEAL,source_record,scope,task_id,source,context,registry,observed,observation)
        cap._authoritative_records=copy.deepcopy(authoritative);cap._capture=capture
        yield cap
    finally:
        if cap is not None:cap.close()
        else:capture.__exit__(*sys.exc_info())


def _proof_registry(implementation,root,fact_record,fact_sha,task_id):
    """只加载controller已认证并受签固定的039原实现；不重入来源/HOM工厂。"""
    import types
    from dcc_task_runtime.canonical import canonical_sha256
    names=('canonical','models','errors','contracts','windows_process','platform_support','pipeline_store','project_color','exr_codec','artifact_registry')
    if set(implementation)!={'schema','authorization','package_root','files'} or set(implementation['files'])!=set(names):
        raise ValueError('COLD_PROOF_REGISTRY_IMPLEMENTATION_INVALID')
    alias='_bridge_cold_attested_registry_'+canonical_sha256(implementation)
    if alias not in sys.modules:
        package=types.ModuleType(alias);package.__package__=alias;package.__path__=[];sys.modules[alias]=package
        try:
            for name in names:
                r=implementation['files'][name];module=types.ModuleType(alias+'.'+name);module.__package__=alias;module.__file__=r['path']
                sys.modules[module.__name__]=module;setattr(package,name,module);exec(compile(_cold_bytes(r),r['path'],'exec'),module.__dict__)
        except BaseException:
            for key in tuple(sys.modules):
                if key==alias or key.startswith(alias+'.'):sys.modules.pop(key,None)
            raise
    registry=sys.modules[alias+'.artifact_registry'].ArtifactRegistry(root)
    def fact_source(operation):
        fact=json.loads(_cold_bytes(fact_record))
        if canonical_sha256(fact)!=fact_sha or fact.get('task_id')!=task_id:raise ValueError('COLD_PROOF_PRODUCER_FACT_CHANGED')
        return fact if fact.get('operation_id')==operation else None
    registry.set_operation_source(fact_source);return registry


def _cold_proof_payload(record,scope,*,observation):
    value=json.loads(_cold_bytes(record));payload=value.get('payload');mode='observation' if observation else 'execution'
    if (set(value)!={'payload','signature'} or not isinstance(payload,dict) or payload.get('schema')!=_COLD_PROOF_SCHEMA
            or payload.get('mode')!=mode or payload.get('native_scope')!=scope.binding
            or payload.get('owner_task_id')!=scope.scope['task_id']
            or not hmac.compare_digest(str(value['signature']),_cold_proof_sign(scope,payload))):
        raise ValueError('COLD_INPUT_PROOF_INVALID')
    path=Path(record['path'])
    if path.stat().st_mode&0o077:raise ValueError('COLD_INPUT_PROOF_PRIVATE_REQUIRED')
    if observation:
        if path.is_relative_to(scope.root) or payload['identity'] is not None or payload['slot'] is not None:
            raise ValueError('COLD_INPUT_OBSERVATION_PROOF_REQUIRED')
    else:
        identity=payload['identity'];expected=scope.root/'state/nuke_renders'/(payload['operation_id']+'.'+identity['launch_nonce']+'.input-proof.json')
        if path!=expected:raise ValueError('COLD_INPUT_EXECUTION_PROOF_PATH_REQUIRED')
    return payload


class _ProofColdInputs(_OwnedColdInputs):
    """worker仅核nonce证明、原件及typed门，永不回退全来源工厂。"""
    __slots__=('_proof_record','_proof_payload')
    def __init__(self,scope,record,payload,snapshot):
        source=json.loads(_cold_bytes(payload['source']));registry=_proof_registry(payload['registry_implementation'],scope.root/'artifact_ledger',payload['producer_fact'],payload['producer_fact_sha256'],payload['owner_task_id'])
        self._seal=_COLD_INPUT_SEAL;self._active=True;self._observation=payload['mode']=='observation';self._scope=scope
        self._source=source;self._registry=registry;self._records=copy.deepcopy(payload['fixed_records']);self._prefix_records=copy.deepcopy(payload['original_prefixes'])
        self._context_record=payload['context'];self._snapshot=snapshot;self._contract_record=payload['contract'];self._binding=payload['binding']
        self._env={key:os.environ.get(key) for key in ('BRIDGE_CREATIVE_COLD_CONTEXT','BRIDGE_CREATIVE_COLD_CONTEXT_SHA256','BRIDGE_NUKE_TASK_ID','BRIDGE_NUKE_RESULT_FILE','BRIDGE_NUKE_INPUT_CONTRACT','BRIDGE_NUKE_INPUT_CONTRACT_SHA256',_COLD_PROOF_PATH_ENV,_COLD_PROOF_SHA_ENV)}
        self._nuke=self._node=self._write=None;self._proof_record=record;self._proof_payload=payload;_cold_runtime_origin(payload);self._proof_fence()
    def _proof_fence(self):
        self._valid();payload=_cold_proof_payload(self._proof_record,self._scope,observation=self._observation)
        if payload!=self._proof_payload:raise ValueError('COLD_INPUT_PROOF_CHANGED')
        for record in self._records:_cold_bytes(record)
        from dcc_task_runtime.geometry_budget_addendum import _prefix
        prior=_prefix(self._scope,payload['accounting_prefix'],payload['accounting_envelope'])['state'];state=self._scope._read()
        if len(prior['tickets'])!=16 or state['tickets'][:16]!=prior['tickets']:raise ValueError('COLD_PROOF_NATIVE_PREFIX_CHANGED')
        session=json.loads((self._scope.root/'geometry-state.json').read_text());base=payload['accepted_base'];entry=session['jobs'][base['operation_id']]
        if (session['completed'][0]!=base['operation_id'] or entry.get('state')!='COMPLETE'
                or entry.get('result')!=base['result'] or entry.get('acceptance')!=base['acceptance']):raise ValueError('COLD_PROOF_ACCEPTED_BASE_CHANGED')
        _cold_session_fence(self._scope,payload['session_projection'],observation=self._observation)
        if self._observation:
            if len(state['tickets'])!=16 or state!=prior or any(t['stopped_at'] is None for t in state['tickets']):raise ValueError('COLD_PROOF_OBSERVATION_SCOPE_CHANGED')
            return
        p=payload;identity=p['identity'];expected=self._scope.root/'state/nuke_renders'/(p['operation_id']+'.supervisor')
        matches=[t for t in state['tickets'] if t['role']=='nuke-render' and t['directory']==str(expected)]
        if len(state['tickets'])!=17 or len(matches)!=1 or matches[0]['stopped_at'] is not None:raise ValueError('COLD_PROOF_CURRENT_NR_REQUIRED')
        ticket=matches[0];started=owned_process.read_receipt(expected,'started',identity=ticket['identity']);intent=json.loads((expected/'intent.json').read_text())
        wanted=dict(identity,cold_proof_sha256=self._proof_record['sha256'])
        if (ticket['identity']!=wanted or not started or started.get('pid')!=os.getpid() or intent.get('identity')!=wanted
                or hashlib.sha256(owned_process._canonical(intent['command'])).hexdigest()!=p['command_sha256']
                or started.get('argv_sha256')!=p['command_sha256']):raise ValueError('COLD_PROOF_OWNED_NR_IDENTITY_CHANGED')
        env=intent['env'];base=p['environment']
        if (set(env)!=set(base['keys'])|_COLD_PROOF_ENV|_COLD_NATIVE_ENV
                or env.get(_COLD_PROOF_PATH_ENV)!=self._proof_record['path'] or env.get(_COLD_PROOF_SHA_ENV)!=self._proof_record['sha256']
                or _cold_env_projection(env)!=base or env.get('BRIDGE_NATIVE_SCOPE_BINDING')!=owned_process._canonical(self._scope.binding).decode()
                or env.get('BRIDGE_NATIVE_SCOPE_TICKET')!=ticket['id']
                or os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')!=env.get('BRIDGE_NATIVE_SCOPE_BINDING')
                or os.environ.get('BRIDGE_NATIVE_SCOPE_TICKET')!=ticket['id']
                or any(env.get(key)!=value for key,value in self._env.items())):raise ValueError('COLD_PROOF_LAUNCH_ENV_CHANGED')
        _cold_live_slot_fence(self._scope,p,ticket,started)
        task=json.loads((self._scope.root/'state/nuke_renders'/(p['operation_id']+'.json')).read_text())
        if (task.get('owner_task_id')!=p['owner_task_id'] or task.get('script_snapshot')!=p['snapshot']['path']
                or task.get('scene_fingerprint')!=p['snapshot']['sha256'] or _cold_slot_binding(task.get('slot'))!=p['slot']
                or task.get('input_contract')!=json.loads(_cold_bytes(p['contract']))):raise ValueError('COLD_PROOF_RENDER_TASK_CHANGED')
        self._scope.check()
    def validate_contract(self,contract):
        from .operation_receipts import _validate_registered_input_contract_with_registry
        self._proof_fence()
        if contract!=json.loads(_cold_bytes(self._contract_record)):raise ValueError('COLD_PROOF_CONTRACT_CHANGED')
        self._native_fence();return _validate_registered_input_contract_with_registry(contract,self._registry)
    def authorize_execute(self):
        if self._observation:raise ValueError('COLD_INPUT_OBSERVATION_CANNOT_EXECUTE')
        self._proof_fence();self._native_fence()


@contextmanager
def _proved_cold_inputs(snapshot,*,observation=False,proof_record=None):
    from dcc_task_runtime.native_scope import NativeScope
    context_path=Path(str(os.environ.get('BRIDGE_CREATIVE_COLD_CONTEXT') or ''))
    context_record=_cold_record(context_path);context=json.loads(_cold_bytes(context_record));scope=NativeScope(context['native_scope'])
    record=proof_record
    if record is None:
        path=Path(str(os.environ.get(_COLD_PROOF_PATH_ENV) or ''))
        if not path.is_absolute() or not path.is_file():raise ValueError('COLD_INPUT_EXECUTION_PROOF_REQUIRED')
        record=_cold_record(path)
        if record['sha256']!=os.environ.get(_COLD_PROOF_SHA_ENV):raise ValueError('COLD_INPUT_PROOF_CHANGED')
    payload=_cold_proof_payload(record,scope,observation=observation);snapshot_record=_cold_record(Path(snapshot))
    if (payload['snapshot']!=snapshot_record or payload['context']!=context_record
            or payload['operation_id']!=os.environ.get('BRIDGE_NUKE_TASK_ID') or payload['result_path']!=os.environ.get('BRIDGE_NUKE_RESULT_FILE')
            or payload['contract']['path']!=os.environ.get('BRIDGE_NUKE_INPUT_CONTRACT')
            or payload['contract']['sha256']!=os.environ.get('BRIDGE_NUKE_INPUT_CONTRACT_SHA256')):raise ValueError('COLD_INPUT_PROOF_BOUNDARY_CHANGED')
    cap=_ProofColdInputs(scope,record,payload,snapshot_record)
    try:yield cap
    finally:cap.close()



def _cold_live_slot_fence(scope,payload,ticket,started):
    """047执行在已验当前NR身份后只读重验实时slot，不重进来源工厂。"""
    if (payload['mode']!='execution' or Path(payload['binding']['authority']['path']).name!='geometry-prelaunch-tail-authorization.json'):return
    import sqlite3
    from contextlib import closing
    path=scope.root/'scheduler/graph_scheduler.sqlite3'
    if path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('COLD_PROOF_LIVE_SLOT_PATH_CHANGED')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        row=db.execute('SELECT * FROM heavy_slot WHERE slot=1').fetchone()
    slot=payload['slot']
    if (row is None or row['active']!=1 or row['phase']!='DISPATCHING' or row['cancel_requested']!=0
            or row['operation_id']!=payload['operation_id'] or row['owner_root']!=slot['owner_root']
            or row['generation']!=slot['generation']
            or not hmac.compare_digest(hashlib.sha256(row['token'].encode()).hexdigest(),slot['token_sha256'])):
        raise ValueError('COLD_PROOF_LIVE_SLOT_CHANGED')
    # 控制器可能尚未bind_process；当前NR17的签名started/PID/nonce门已先通过。
    if row['process_json'] is not None:
        process=json.loads(row['process_json']);expected=scope.root/'state/nuke_renders'/(payload['operation_id']+'.supervisor')
        if (process.get('pid')!=started['pid'] or process.get('supervisor_identity')!=ticket['identity']
                or process.get('supervisor_directory')!=str(expected)):
            raise ValueError('COLD_PROOF_LIVE_PROCESS_CHANGED')


def _cold_proof_required(scope):
    """按原任务声明识别046，而非把新插件版本扩成所有旧source2的强制门。"""
    name='geometry-cold-preflight-runtime-authorization.json'
    operation=str(os.environ.get('BRIDGE_NUKE_TASK_ID') or '')
    # 真实签名票据已有proof hash时，改写普通job/env也不能解除此门。
    if any(ticket.get('identity',{}).get('task_id')==operation and ticket.get('identity',{}).get('cold_proof_sha256')
            for ticket in scope._read()['tickets']):return True
    task_path=scope.root/'state/nuke_renders'/(operation+'.json')
    if task_path.is_file():
        task=json.loads(task_path.read_text());request=str(task.get('request_id') or '')
        if request.endswith('_nuke'):
            mainop=request[:-5];job_path=scope.root/'jobs'/mainop/'job.json'
            if job_path.is_file():
                job=json.loads(job_path.read_text());authority=job.get('runtime_continuation') or {}
                # 声明了046的任务即使授权被删除也不能回落慢工厂。
                return Path(str(authority.get('path') or '')).name==name
    return (scope.root/name).exists()


@contextmanager
def _capture_controller_records(scope):
    """只捕获可信读函数实际验过的输入；构造输出记录不声明输入依赖。"""
    from houdini_bridge.official_karma_observation import checked_bytes,file_record
    from dcc_task_runtime.geometry_recovery import _bytes
    from vfx_pipeline.geometry_render_resume import _read
    from vfx_pipeline.geometry_native_evidence import _file as native_file
    if sys.getprofile() is not None:raise ValueError('COLD_INPUT_PROFILE_ALREADY_ACTIVE')
    bytes_readers={checked_bytes.__code__,_bytes.__code__,_read.__code__}
    # file_record也用于当前journal的INTENT/DONE写出；永久输入由受签schema和索引补齐。
    record_readers={native_file.__code__}
    dynamic={scope.state_path,scope.journal_path,scope.anchor_path,scope.root/'geometry-state.json',scope.root/'artifact_ledger/artifacts.sqlite3'}
    observed={};failed=[];capturing=[True]
    def add(record):
        if type(record) is not dict or set(record)!={'path','bytes','sha256'}:raise ValueError('COLD_AUTHORITY_RECORD_INVALID')
        if Path(record['path']) in dynamic:return
        prior=observed.get(record['path'])
        if prior is not None and prior!=record:raise ValueError('COLD_AUTHORITY_RECORD_CHANGED')
        observed[record['path']]=copy.deepcopy(record)
    def profile(frame,event,result):
        if event=='c_call':
            if capturing[0] and result is sys.setprofile:failed.append('profile_replaced')
            return
        if failed or event!='return':return
        code=frame.f_code
        if code not in bytes_readers and code not in record_readers:return
        # 构造器按自身刚算出的digest自检，不是对外部预期FileRecord的输入验证。
        if code is checked_bytes.__code__ and frame.f_back is not None and frame.f_back.f_code is file_record.__code__:return
        try:
            if code in record_readers:
                if isinstance(result,dict):add(result)
            else:
                record=frame.f_locals.get('record')
                if isinstance(result,bytes) and isinstance(record,dict):
                    if len(result)!=record['bytes'] or hashlib.sha256(result).hexdigest()!=record['sha256']:
                        raise ValueError('COLD_AUTHORITY_RETURN_MISMATCH')
                    add(record)
        except BaseException as error:failed.append(type(error).__name__)
    sys.setprofile(profile)
    try:
        yield observed
        capturing[0]=False
        if failed or sys.getprofile() is not profile:raise ValueError('COLD_INPUT_CAPTURE_INCOMPLETE')
    finally:sys.setprofile(None)


def _cold_execution_code(scope,binding,snapshot,command,*,observation):
    """准入前把nonce证明绑定真实046入口原字节和固定argv，拒绝错包慢worker。"""
    from vfx_pipeline.geometry_seed_cold_resume import validate
    preparation=_cold_record(scope.root/'geometry-preparation.json');payload,_=validate(preparation,binding['authority'],scope)
    active=Path(payload['active_worker']['path']).parents[2];formal=Path(payload['consumer_runtime']['package_root'])
    manifest=json.loads(_cold_bytes(_cold_record(formal/'runtime-manifest.json')));entries={item['path']:item for item in manifest['files']}
    selected={}
    for key,relative in (('worker_script','runtime/tools/nuke_owned_render_worker.py'),('worker_module','runtime/packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py'),('proof_module','runtime/packages/nuke-bridge/src/nuke_bridge/task_host.py'),('addon','runtime/plugins/nuke/nuke_bridge_addon.py')):
        item=entries.get(relative);record=_cold_record(active/relative)
        if not item or record['sha256']!=item['sha256'] or item.get('bytes',record['bytes'])!=record['bytes']:
            raise ValueError('COLD_PROOF_RUNTIME_BYTES_CHANGED')
        selected[key]=record
    selected['request']=copy.deepcopy(payload['request'])
    selected['nuke_executable']=copy.deepcopy(scope.scope['hosts']['nuke']);_cold_bytes(selected['nuke_executable'])
    expected=[selected['nuke_executable']['path'],'-t',selected['worker_script']['path'],snapshot['path'],'Write1','1','1',binding['approved_pattern'],'[1]']
    if not observation and command!=expected:raise ValueError('COLD_PROOF_FIXED_ARGV_REQUIRED')
    return selected


def _cold_runtime_origin(payload):
    """文件相同仍不等于当前进程已加载它：同时核对实际模块来源与原字节。"""
    from . import owned_render_worker
    if (_cold_record(Path(__file__))!=payload['execution_code']['proof_module']
            or _cold_record(Path(owned_render_worker.__file__))!=payload['execution_code']['worker_module']):
        raise ValueError('COLD_PROOF_LOADED_RUNTIME_MISMATCH')


def _cold_session_projection(scope,binding,request_record,*,observation):
    """只绑定本op的计划/请求/执行映射，不冻结持续更新的整个Session文件。"""
    request=json.loads(_cold_bytes(request_record));op=request['new_operation_id'];plan=request['new_plan'];pid=plan['plan_id'];rid=request['request_id']
    if binding['operation_id']!=op:raise ValueError('COLD_PROOF_SESSION_OPERATION_CHANGED')
    projection={'operation_id':op,'plan_id':pid,'request_id':rid,'plan':plan,'request_sha256':hashlib.sha256(owned_process._canonical({'plan_id':pid})).hexdigest(),'job_identity':None}
    # 旧只读预检没有job；已认证续接binding带原job时，观察也保留同一动态身份门。
    if binding.get('main_job_record') is not None:
        job=json.loads(_cold_bytes(binding['main_job_record']))
        projection['job_identity']={'operation_id':op,'revision':job['revision'],'plan_id':pid,'directory':job['directory'],'job_file':binding['main_job_record']}
    _cold_session_fence(scope,projection,observation=observation);return projection


def _cold_session_fence(scope,projection,*,observation):
    session=json.loads((scope.root/'geometry-state.json').read_text());op=projection['operation_id'];pid=projection['plan_id'];rid=projection['request_id']
    if session.get('task_id')!=scope.scope['task_id']:raise ValueError('COLD_PROOF_SESSION_TASK_CHANGED')
    if observation and projection['job_identity'] is None:
        if op in session.get('jobs',{}) or (scope.root/'jobs'/op).exists():raise ValueError('COLD_PROOF_OBSERVATION_JOB_APPEARED')
        return
    current=session.get('jobs',{}).get(op) or {};expected=projection['job_identity']
    if (any(current.get(key)!=value for key,value in expected.items()) or current.get('state') not in ('QUEUED','RUNNING')
            or session.get('plans',{}).get(pid)!=projection['plan']
            or session.get('execution_requests',{}).get(rid)!={'request_sha256':projection['request_sha256'],'operation_id':op}
            or session.get('plan_operations',{}).get(pid)!=op):raise ValueError('COLD_PROOF_SESSION_OPERATION_CHANGED')
