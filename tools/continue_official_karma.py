#!/usr/bin/env python3
"""复用官方 DiskLight 封存输入，通过常规 GraphRun 完成任务与产物登记。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from dcc_task_runtime.native_scope import (NativeScope, OFFICIAL_INCREMENTAL_MODE,
    OFFICIAL_INCREMENTAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_BUDGET,
    OFFICIAL_INCREMENTAL_ROLE_SECONDS)
from dcc_task_runtime.render_profiles import OFFICIAL, output_policy
from houdini_bridge.official_karma_observation import file_record, load_record, checked_bytes, write_new

PREFIX = 'disklight_incremental'
ARTIFACT_ID = PREFIX + '_main'


def _load(path):
    """读取本任务已有 JSON；文件身份由调用处的记录约束。"""
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _binding(record):
    """作用域只携带路径与摘要，保留既有 NativeScope 合同。"""
    return {name: record[name] for name in ('path', 'sha256')}


def _source(source_root):
    """重新认证封存观测、原 alpha 和其精确插件版本，绝不重签历史事实。"""
    from houdini_bridge.official_karma_scene import load_observation
    root = Path(source_root)
    if not root.is_absolute() or root != root.resolve():
        raise ValueError('INCREMENTAL_SOURCE_PATH_INVALID')
    scope_record = file_record(root / 'scope.json')
    scope = NativeScope(_binding(scope_record))
    bindings_record = file_record(root / 'runtime-bindings.json')
    bindings = load_record(bindings_record)
    alpha_record = file_record(root / 'alpha-calibration-result.json')
    alpha = load_record(alpha_record)
    if (scope.root != root or scope.scope.get('scene_profile') != OFFICIAL
            or bindings.get('scope_sha256') != scope_record['sha256']
            or bindings.get('evidence_source') != 'real_host'
            or alpha.get('schema') != 'bridge.alpha-runner.result/1'
            or alpha.get('scope_sha256') != scope_record['sha256']
            or alpha.get('bindings_sha256') != bindings_record['sha256']):
        raise ValueError('INCREMENTAL_SOURCE_BINDING_MISMATCH')
    from houdini_bridge.alpha_reuse import validate_source_calibration
    calibration_reader = file_record(root / 'project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py')
    calibrated = validate_source_calibration(alpha['alpha_calibration'], calibration_reader,
        expected_version='21.0.631', expected_plugin_build=bindings['plugin_build'],
        expected_route_sha256=bindings['route_sha256'], evidence_source='real_host')
    if calibrated != alpha.get('calibration'):
        raise ValueError('INCREMENTAL_ALPHA_ORIGINAL_CHANGED')
    configuration_record = file_record(root / 'frozen-inputs/official-scene.json')
    configuration = load_record(configuration_record)
    load_observation(configuration, '21.0.631')
    addon = file_record(root / 'project/control/snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    if (addon['sha256'] != calibrated['plugin_build']
            or bindings['source_freeze'].get(addon['path']) != addon['sha256']):
        raise ValueError('INCREMENTAL_CALIBRATED_ADDON_REQUIRED')
    reference = file_record(scope.scope['official_case']['paths']['official_image'])
    return {'root': root, 'native': scope, 'bindings': bindings, 'alpha': alpha,
        'configuration': configuration, 'addon': addon,
        'records': {'scope': scope_record, 'bindings': bindings_record,
                    'alpha': alpha_record, 'configuration': configuration_record,
                    'addon': addon, 'reference': reference, 'calibration_reader': calibration_reader}}


def _runtime_environment(scope, *, startup_diagnostics=False):
    """在既有白名单上保留四项非敏感原生兼容设置；诊断开关只由本次显式参数启用。"""
    from prepare_controlled_engineering import _environment
    environment = _environment(scope)
    for name in ('LC_ALL', 'LC_CTYPE', 'MallocNanoZone', '__CF_USER_TEXT_ENCODING'):
        if name in os.environ:
            environment[name] = os.environ[name]
    if startup_diagnostics:
        environment['BRIDGE_GRAPH_STARTUP_DIAGNOSTICS'] = '1'
    return environment


def prepare(source_root, output_root, instruction, *, parameter_templates=None, startup_diagnostics=False):
    """创建独立授权任务；仅复用原件，不运行官方前缀、校准或任何宿主。"""
    from prepare_workbuddy_graph import prepare_graph
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError('INCREMENTAL_CURRENT_USER_INSTRUCTION_REQUIRED')
    # 官方案例需要完整原生模板；缺件在读来源或创建范围之前明确拒绝。
    if parameter_templates is None:
        raise ValueError('INCREMENTAL_PARAMETER_TEMPLATE_RECORD_REQUIRED')
    source = _source(source_root)
    template_record = None
    if parameter_templates is not None:
        from houdini_bridge.official_karma_templates import validate_parameter_templates
        template_record = file_record(Path(parameter_templates))
        # 先在创建新范围前核对模板旁车与原观测/工作 HIP，避免无效输入留下半成品。
        template_configuration = copy.deepcopy(source['configuration'])
        template_configuration['parameter_templates'] = template_record
        validate_parameter_templates(template_configuration)
    root = Path(output_root)
    if (not root.is_absolute() or root != root.resolve() or root.exists()
            or not root.parent.is_dir() or any(p.is_symlink() for p in (root, *root.parents))):
        raise ValueError('INCREMENTAL_FRESH_OUTPUT_REQUIRED')
    root.mkdir(mode=0o700)
    key = secrets.token_bytes(32)
    scope = copy.deepcopy(source['native'].scope)
    for field in ('activation_review', 'prepared_from', 'execution_mode', 'writer_trace_tools',
                  'stack_qualification'):
        scope.pop(field, None)
    scope.update(scope_id='disklight-incremental-' + uuid.uuid4().hex,
        output_root=str(root), execution_mode=OFFICIAL_INCREMENTAL_MODE, execution_authorized=True,
        resource_profile=OFFICIAL_INCREMENTAL_RESOURCE_PROFILE,
        budget=copy.deepcopy(OFFICIAL_INCREMENTAL_BUDGET),
        role_seconds=copy.deepcopy(OFFICIAL_INCREMENTAL_ROLE_SECONDS),
        status='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION', host_started=False,
        accounting={'key_path': str(root / '.native-control/key'),
                    'key_sha256': hashlib.sha256(key).hexdigest()},
        operations=[{'id': 'formal-h21'}, {'id': 'consume-nuke'}],
        authorization={'authority': 'current_user_instruction', 'instruction': instruction},
        reused_inputs=source['records'])
    scope_record = write_new(root / 'scope.json', scope)
    native = NativeScope.initialize(_binding(scope_record), key=key)
    environment = _runtime_environment(scope, startup_diagnostics=startup_diagnostics)
    frozen = root / 'frozen-inputs'
    frozen.mkdir(mode=0o700)
    configuration = copy.deepcopy(source['configuration'])
    configuration['observation_scope'] = source['native'].binding
    configuration['native_scope'] = native.binding
    configuration['scene']['output_image'] = str(root / 'project/saves/main.0001.exr')
    if template_record is not None:
        configuration['parameter_templates'] = template_record
        validate_parameter_templates(configuration)
    configuration_record = write_new(frozen / 'official-scene.json', configuration)
    from houdini_bridge.alpha_reuse import make_reuse_binding
    active_addon = file_record(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
    alpha_binding = make_reuse_binding(source['alpha']['alpha_calibration'], source['addon'], active_addon)
    # 生成器即将复制同一字节；运行时证明绑定实际部署快照，不能只信任源码目录。
    alpha_binding['plugin_reuse']['active_plugin']['path'] = str(
        root / 'project/control/snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    host_configs = {}
    for kind, executable in (('houdini', 'hython'), ('nuke', 'nuke')):
        host_configs[kind] = {
            'lifecycle': 'task_owned', 'application': kind, 'version': scope['versions'][kind],
            'executable': scope['hosts'][executable]['path'],
            'supervisor_executable': scope['hosts']['supervisor_python']['path'],
            'task_root': str(root), 'session_seconds': 120, 'evidence_source': 'real_host',
            'project_color': scope['project_color'], 'native_scope': native.binding,
            'resource_budget': {'roots': [str(root)], 'max_bytes': scope['budget']['max_disk_bytes'],
                                'native_scope': native.binding}}
    host_configs['houdini'].update(output_acceptance=output_policy(OFFICIAL),
        alpha_calibration=alpha_binding,
        writer_executable={'path': scope['hosts']['husk']['path'], 'version': '21.0.631',
                           'sha256': scope['hosts']['husk']['sha256']})
    construction = [{'index': 0, 'asset_id': 'sealed-official-karma-disklight',
        'semantic_role': 'render_scene_configuration', 'source_uri': configuration_record['path'],
        'bytes': configuration_record['bytes'], 'sha256': configuration_record['sha256']}]
    project = root / 'project'
    prepare_graph(project, app=None, scheduler_root=root / 'scheduler',
        execution_profile=True, render_profile=True,
        production_host_config=host_configs['houdini'], production_nuke_config=host_configs['nuke'],
        construction_input_manifest=construction)
    control = project / 'control'
    preparation = {
        'schema': 'bridge.official-karma-incremental/1', 'state': 'PREPARED',
        'scope': native.binding, 'source': source['records'],
        'configuration': configuration_record, 'project': str(project),
        'manifest': file_record(control / 'run.json'),
        'snapshot_manifest': file_record(control / 'snapshot-manifest.json'),
        'environment': environment, 'alpha_calibration': alpha_binding,
        'active_plugin': file_record(control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py'),
        'calibration': source['alpha']['calibration'], 'native_starts': 0,
        'planned_steps': ['graph_build', 'save', 'reopen', 'main_render', 'verify', 'register',
                          'nuke_consume', 'nuke_save', 'nuke_render'],
        'reused_steps': ['official_reference', 'sealed_observation', 'alpha_calibration']}
    if template_record is not None:
        preparation['parameter_templates'] = template_record
    record = write_new(root / 'incremental-preparation.json', preparation)
    return {'state': 'PREPARED', 'preparation': record,
        'run_command': [scope['hosts']['supervisor_python']['path'], '-I', '-B',
            str(control / 'snapshot/tools/continue_official_karma.py'),
            'run', '--preparation', record['path']], 'native_starts': 0}


def prepare_resume(preparation_path, namespace, instruction, *, nuke_only=False):
    """认证已完成 GraphRun，在同任务预算内只准备剩余下游。"""
    import re
    from prepare_workbuddy_graph import prepare_graph
    from vfx_pipeline.official_graph_resume import inspect_resume_source, inspect_nuke_resume_source
    from houdini_bridge.alpha_reuse import make_reuse_binding
    if (type(instruction) is not str or not instruction.strip()
            or type(namespace) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', namespace)):
        raise ValueError('INCREMENTAL_CONTINUATION_INSTRUCTION_OR_NAMESPACE_INVALID')
    nuke_source = inspect_nuke_resume_source(Path(preparation_path)) if nuke_only else None
    origin = nuke_source['source_graph'] if nuke_only else inspect_resume_source(Path(preparation_path))
    prior = load_record(file_record(preparation_path) if nuke_only else origin['preparation'])
    predecessor = NativeScope(prior['scope'])
    previous = predecessor.snapshot()
    if any(ticket.get('stopped_at') is None for ticket in previous['tickets']):
        raise ValueError('INCREMENTAL_CONTINUATION_PRIOR_STOP_REQUIRED')
    source = _source(Path(prior['source']['scope']['path']).parent)
    if source['records'] != prior['source']:
        raise ValueError('INCREMENTAL_CONTINUATION_SOURCE_CHANGED')
    root = predecessor.root / 'continuations' / namespace
    if root.exists() or any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError('INCREMENTAL_FRESH_CONTINUATION_REQUIRED')
    root.mkdir(mode=0o700, parents=True)
    key = secrets.token_bytes(32)
    scope = copy.deepcopy(predecessor.scope)
    scope.update(scope_id='disklight-continuation-' + uuid.uuid4().hex,
        authorization={'authority': 'current_user_instruction', 'instruction': instruction},
        accounting={'namespace': namespace,
            'key_path': str(predecessor.root / '.native-control' / namespace / 'key'),
            'key_sha256': hashlib.sha256(key).hexdigest()},
        continuation_of=file_record(predecessor.path), host_started=False,
        replacement_host_allowance=1,
        budget=dict(scope['budget'], max_dcc_starts=7))
    if nuke_only:
        scope.update(replacement_nuke_host_allowance=1, budget=dict(scope['budget'], max_dcc_starts=8))
    scope_record = write_new(root / 'scope.json', scope)
    native = NativeScope.initialize(_binding(scope_record), key=key)
    # 已失败启动计入总账；替换额度只增加一票，仍在原 600 秒总额内。
    if native.snapshot()['dcc_starts'] != previous['dcc_starts']:
        raise ValueError('INCREMENTAL_CONTINUATION_ACCOUNTING_NOT_INHERITED')
    project, control = Path(prior['project']), root / 'project/control'
    active = file_record(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
    alpha = make_reuse_binding(source['alpha']['alpha_calibration'], source['addon'], active)
    alpha['plugin_reuse']['active_plugin']['path'] = str(
        control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    hosts = {}
    for kind, executable in (('houdini', 'hython'), ('nuke', 'nuke')):
        hosts[kind] = {'lifecycle': 'task_owned', 'application': kind,
            'version': scope['versions'][kind], 'executable': scope['hosts'][executable]['path'],
            'supervisor_executable': scope['hosts']['supervisor_python']['path'],
            'task_root': str(native.root), 'session_seconds': 120, 'evidence_source': 'real_host',
            'project_color': scope['project_color'], 'native_scope': native.binding,
            'resource_budget': {'roots': [str(native.root)], 'max_bytes': scope['budget']['max_disk_bytes'],
                                'native_scope': native.binding}}
    hosts['houdini'].update(output_acceptance=output_policy(OFFICIAL), alpha_calibration=alpha,
        writer_executable={'path': scope['hosts']['husk']['path'], 'version': '21.0.631',
                           'sha256': scope['hosts']['husk']['sha256']})
    if nuke_only:
        (root / 'frozen-inputs').mkdir(mode=0o700)
        hosts['nuke']['input_artifact_source'] = write_new(
            root / 'frozen-inputs/input-artifact-source.json', nuke_source)
    configuration = prior['configuration']
    checked_bytes(configuration)
    construction = [{'index': 0, 'asset_id': 'sealed-official-karma-disklight',
        'semantic_role': 'render_scene_configuration', 'source_uri': configuration['path'],
        'bytes': configuration['bytes'], 'sha256': configuration['sha256']}]
    prepare_graph(root / 'project', app=None, scheduler_root=root / 'scheduler',
        execution_profile=True, render_profile=True, production_host_config=hosts['houdini'],
        production_nuke_config=hosts['nuke'], construction_input_manifest=construction)
    preparation = {'schema': 'bridge.official-karma-incremental/1', 'state': 'PREPARED',
        'scope': native.binding, 'source': source['records'], 'configuration': configuration,
        'project': str(project), 'control': str(control), 'resume_graph': origin,
        'manifest': file_record(control / 'run.json'),
        'snapshot_manifest': file_record(control / 'snapshot-manifest.json'),
        'environment': _runtime_environment(scope, startup_diagnostics=False),
        'alpha_calibration': alpha, 'calibration': source['alpha']['calibration'],
        'active_plugin': file_record(control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py'),
        'parameter_templates': prior['parameter_templates'], 'native_starts': 0,
        'inherited_native_starts': previous['dcc_starts'],
        'planned_steps': ['handoff', 'save', 'initial_host_stop', 'reopen_cold', 'main_render', 'verify',
                          'register', 'nuke_consume', 'nuke_save', 'nuke_render'],
        'reused_steps': ['accepted_graph_run', 'official_reference', 'sealed_observation', 'alpha_calibration']}
    if nuke_only:
        preparation['resume_nuke'] = nuke_source
        preparation['planned_steps'] = ['nuke_consume', 'nuke_save', 'nuke_render', 'compare']
        preparation['reused_steps'] += ['saved_hip', 'cold_reopen', 'main_render', 'verified_registered_artifact']
    record = write_new(root / 'incremental-preparation.json', preparation)
    return {'state': 'PREPARED', 'preparation': record, 'native_starts': 0,
        'inherited_native_starts': previous['dcc_starts'],
        'run_command': [scope['hosts']['supervisor_python']['path'], '-I', '-B',
            str(control / 'snapshot/tools/continue_official_karma.py'), 'run', '--preparation', record['path']]}


class Journal:
    """副作用前持久记录 INTENT；未知步骤必须查询，不能换请求自动重做。"""
    def __init__(self, root, preparation):
        self.path = root / 'incremental-state.json'
        self.preparation = file_record(preparation)
        if self.path.exists():
            self.value = _load(self.path)
            if self.value.get('preparation') != self.preparation:
                raise ValueError('INCREMENTAL_PREPARATION_CHANGED')
        else:
            self.value = {'schema': 'bridge.official-karma-incremental-state/1',
                          'preparation': self.preparation, 'stages': {}}

    def save(self):
        from dcc_task_runtime.platform_support import atomic_write
        data = json.dumps(self.value, ensure_ascii=False, sort_keys=True,
                          allow_nan=False, indent=2).encode('utf-8')
        atomic_write(self.path, data, owned_root=self.path.parent)

    def action(self, name, callback):
        prior = self.value['stages'].get(name)
        if prior:
            raise ValueError('INCREMENTAL_QUERY_REQUIRED:' + name)
        self.value['stages'][name] = {'state': 'INTENT'}
        self.save()
        result = callback()
        self.value['stages'][name] = {'state': 'DONE', 'result': result}
        self.save()
        return result


def _poll(facade, method, operation_id, state_path, budget, *, role=None):
    """仅查询原操作；建图读取该角色预算，下游仍使用 120 秒上限。"""
    seconds = budget.native.role_seconds(role) if role is not None else 120
    deadline = time.monotonic() + min(seconds, budget.remaining())
    while time.monotonic() < deadline:
        budget.native.check()
        result = getattr(facade, method)(operation_id)
        state = result
        for name in state_path:
            state = state[name]
        if state in ('SUCCEEDED', 'COMPLETED'):
            return result
        if state not in ('PREPARED', 'STARTING', 'RUNNING', 'READY', 'QUEUED', 'ACTIVE',
                         'SUBMITTED', 'RENDERING'):
            raise ValueError('INCREMENTAL_OPERATION_FAILED:' + str(state))
        time.sleep(.1)
    raise TimeoutError('INCREMENTAL_OPERATION_TIMEOUT')


def _registered_task_domain(facade):
    """从真实任务账本读回领域，防止照明任务被登记为默认烟雾任务。"""
    task = facade.trusted_execution.store.get_task(facade.pipeline_task_id)
    expected = [{'identifier': 'lighting_camera_render_v1', 'version': '1.0.0'}]
    if task.get('spec', {}).get('domains') != expected:
        raise ValueError('INCREMENTAL_REGISTERED_TASK_DOMAIN_MISMATCH')
    return {'task_id': task['task_id'], 'domains': expected, 'spec_hash': task['spec_hash']}


def _run_resumed(prep, source, budget, journal, data):
    """复用已接收工程，只执行交接及保存、冷开、渲染、登记和 Nuke 下游。"""
    from vfx_pipeline.official_graph_resume import inspect_resume_source, resume_graph_facade
    from run_controlled_engineering import _stop_host
    from houdini_bridge.official_karma import compare_files
    origin = inspect_resume_source(Path(prep['resume_graph']['preparation']['path']),
                                   prep['resume_graph']['operation_id'])
    if origin != prep['resume_graph']:
        raise ValueError('INCREMENTAL_CONTINUATION_GRAPH_CHANGED')
    journal.action('accepted_graph_revalidated', lambda: {
        'task_id': origin['task_id'], 'graph_id': origin['graph_id'],
        'operation_id': origin['operation_id'], 'reconstructed_this_run': False})
    root, project, control = data['root'], data['project'], data['control']
    with resume_graph_facade(control / 'run.json', origin, repo_root=ROOT,
                             scheduler_root=root / 'scheduler') as first:
        journal.action('task_domain', lambda: _registered_task_domain(first))
        handed = journal.action('handoff', lambda: first._mark_graph_trial_complete(origin['receipt']))
        if ((handed.get('host_binding') or {}).get('graph_binding', {}).get('graph_ready') is not True):
            raise ValueError('INCREMENTAL_CONTINUATION_HANDOFF_REQUIRED')
        saved = journal.action('save', first.task_save)
        roles = {node['role']: node['path'] for node in saved['scene_contract']['nodes']}
        journal.action('initial_host_stop', lambda: _stop_host(data, 'houdini'))
    with resume_graph_facade(control / 'run.json', origin, repo_root=ROOT,
                             scheduler_root=root / 'scheduler') as second:
        journal.action('reopen', lambda: second.task_reopen(saved['saved_scene_id']))
        rendered = journal.action('render', lambda: second.houdini_render_bounded(
            PREFIX + '_render', saved['saved_scene_id'], roles['render'],
            str(project / 'saves/main.%04d.exr'), [1], min(120, budget.remaining())))
        journal.action('render_completed', lambda: _poll(second, 'operation_query',
            rendered['operation_id'], ('operation', 'state'), budget))
        journal.action('render_host_stop', lambda: _stop_host(data, 'houdini'))
        verified = journal.action('verify', lambda: second.verify_render_output(
            PREFIX + '_verify', rendered['operation_id']))
        image = verified['execution_fact']['metadata']['1']
        artifact = journal.action('register', lambda: second.register_render_artifact(
            ARTIFACT_ID, 'preview_temp', str(project / 'saves/main.%04d.exr'), [1],
            image['colorspace'], image['premultiplied'], PREFIX + '_verify'))
        consumed = journal.action('consume', lambda: second.consume_artifact(ARTIFACT_ID))
        if not consumed.get('usable_as_render_input'):
            raise ValueError('INCREMENTAL_CONTINUATION_ARTIFACT_UNUSABLE')
        def prepare_nuke():
            client = second.nuke_client
            output = str(project / 'saves/nuke.%04d.exr')
            client.call('set_knob', {'node': 'Write1', 'knob': 'file_type', 'value': 'exr'})
            binding = client.render_binding(second.pipeline_task_id, output, [1],
                consumed['colorspace'], consumed['premultiplied'], artifact_binding=consumed)
            client.call('set_knob', {'node': 'Write1', 'knob': 'channels', 'value': 'rgba'})
            client.call('set_knob', {'node': 'Write1', 'knob': 'metadata', 'value': 'all metadata'})
            script = project / 'saves/composite.nk'
            result = client.call('save_script', {'path': str(script), 'overwrite': False})
            if result.get('path') != str(script):
                raise ValueError('INCREMENTAL_CONTINUATION_NUKE_SAVE_MISMATCH')
            return {'script': file_record(script), 'input_artifact_id': ARTIFACT_ID,
                    'output_binding': binding}
        journal.action('nuke_prepare', prepare_nuke)
        nuke = journal.action('nuke_render', lambda: second.nuke_render_bounded(
            PREFIX + '_nuke', str(project / 'saves/nuke.%04d.exr'), [1], artifact_id=ARTIFACT_ID))
        journal.action('nuke_completed', lambda: _poll(second, 'operation_query',
            nuke['operation_id'], ('operation', 'state'), budget))
        journal.action('nuke_stop', lambda: _stop_host(data, 'nuke'))
        if not second.artifact_registry.verify(ARTIFACT_ID).get('usable'):
            raise ValueError('INCREMENTAL_CONTINUATION_FINAL_ARTIFACT_UNUSABLE')
        comparisons = journal.action('compare', lambda: {
            'official_to_bridge': compare_files(source['records']['reference']['path'],
                str(project / 'saves/main.0001.exr')),
            'bridge_to_nuke': compare_files(str(project / 'saves/main.0001.exr'),
                str(project / 'saves/nuke.0001.exr'), require_identical=True)})
        if any(item['state'] != 'PASS' for item in comparisons.values()):
            raise ValueError('INCREMENTAL_CONTINUATION_COMPARISON_FAILED')
        snapshot = budget.native.snapshot()
        if any(ticket.get('stopped_at') is None for ticket in snapshot['tickets']):
            raise ValueError('INCREMENTAL_CONTINUATION_ALL_STOPS_REQUIRED')
        result = {'schema': 'bridge.official-karma-incremental-result/1',
            'state': 'TASK_AND_ARTIFACT_REGISTERED', 'task_id': second.pipeline_task_id,
            'task_domain': _registered_task_domain(second), 'graph_id': origin['graph_id'],
            'graph_run_reused': {'operation_id': origin['operation_id'],
                'preparation': origin['preparation'], 'reconstructed_this_run': False},
            'saved_scene_id': saved['saved_scene_id'], 'hip': file_record(saved['path']),
            'nuke_script': file_record(project / 'saves/composite.nk'),
            'artifact_id': artifact['artifact_id'], 'artifact_version': artifact['version'],
            'render_operation_id': rendered['operation_id'],
            'verification_operation_id': PREFIX + '_verify',
            'nuke_render_operation_id': nuke['operation_id'],
            'artifact_registry_accepted': True, 'graph_run_accepted': True,
            'old_failed_graph_run_unchanged': True, 'human_visual_review': 'PENDING_USER',
            'inherited_native_starts': prep['inherited_native_starts'],
            'this_run_native_starts': snapshot['dcc_starts'] - prep['inherited_native_starts'],
            'reused_inputs': prep['source'], 'comparisons': comparisons, 'native_scope': snapshot}
        journal.action('complete', lambda: result)
        write_new(root / 'incremental-result.json', result)
        return result


def _run_nuke_resumed(prep, source, budget, journal, data):
    """只消费已登记产物并完成 Nuke 写出；已保存、冷开和渲染的上游保持原样。"""
    from vfx_pipeline.official_graph_resume import inspect_nuke_resume_source, resume_nuke_facade
    from run_controlled_engineering import _stop_host
    from houdini_bridge.official_karma import compare_files
    origin = inspect_nuke_resume_source(Path(prep['resume_nuke']['preparation']['path']))
    if origin != prep['resume_nuke']:
        raise ValueError('INCREMENTAL_NUKE_SOURCE_CHANGED')
    journal.action('registered_artifact_revalidated', lambda: {
        'task_id': origin['task_id'], 'artifact_id': origin['artifact_id'],
        'artifact_version': origin['artifact_version'], 'upstream_executed_this_run': False})
    root, project, control = data['root'], data['project'], data['control']
    with resume_nuke_facade(control / 'run.json', origin, repo_root=ROOT,
                            scheduler_root=root / 'scheduler') as facade:
        journal.action('task_domain', lambda: _registered_task_domain(facade))
        consumed = journal.action('consume', lambda: facade.consume_artifact(origin['artifact_id']))
        if not consumed.get('usable_as_render_input'):
            raise ValueError('INCREMENTAL_NUKE_SOURCE_UNUSABLE')
        def prepare_nuke():
            client = facade.nuke_client
            # 格式专属 knob 在原生 Write 选定 EXR 后才存在，颜色绑定随后严格读回。
            client.call('set_knob', {'node': 'Write1', 'knob': 'file_type', 'value': 'exr'})
            binding = client.render_binding(facade.pipeline_task_id, str(project / 'saves/nuke.%04d.exr'),
                [1], consumed['colorspace'], consumed['premultiplied'], artifact_binding=consumed)
            client.call('set_knob', {'node': 'Write1', 'knob': 'channels', 'value': 'rgba'})
            client.call('set_knob', {'node': 'Write1', 'knob': 'metadata', 'value': 'all metadata'})
            script = project / 'saves/composite.nk'
            result = client.call('save_script', {'path': str(script), 'overwrite': False})
            if result.get('path') != str(script):
                raise ValueError('INCREMENTAL_NUKE_FINAL_SCRIPT_SAVE_MISMATCH')
            return {'script': file_record(script), 'input_artifact_id': origin['artifact_id'],
                    'output_binding': binding}
        journal.action('nuke_prepare', prepare_nuke)
        rendered = journal.action('nuke_render', lambda: facade.nuke_render_bounded(
            PREFIX + '_nuke', str(project / 'saves/nuke.%04d.exr'), [1], artifact_id=origin['artifact_id']))
        journal.action('nuke_completed', lambda: _poll(facade, 'operation_query',
            rendered['operation_id'], ('operation', 'state'), budget))
        journal.action('nuke_stop', lambda: _stop_host(data, 'nuke'))
        if not facade.artifact_registry.verify(origin['artifact_id']).get('usable'):
            raise ValueError('INCREMENTAL_NUKE_INPUT_INVALIDATED')
        comparisons = journal.action('compare', lambda: {
            'official_to_bridge': compare_files(source['records']['reference']['path'],
                str(project / 'saves/main.0001.exr')),
            'bridge_to_nuke': compare_files(str(project / 'saves/main.0001.exr'),
                str(project / 'saves/nuke.0001.exr'), require_identical=True)})
        if any(value['state'] != 'PASS' for value in comparisons.values()):
            raise ValueError('INCREMENTAL_NUKE_COMPARISON_FAILED')
        snapshot = budget.native.snapshot()
        if any(ticket.get('stopped_at') is None for ticket in snapshot['tickets']):
            raise ValueError('INCREMENTAL_NUKE_ALL_STOPS_REQUIRED')
        checked_bytes(origin['hip'])
        result = {'schema': 'bridge.official-karma-incremental-result/1',
            'state': 'TASK_AND_ARTIFACT_REGISTERED', 'task_id': facade.pipeline_task_id,
            'task_domain': _registered_task_domain(facade),
            'graph_id': origin['source_graph']['graph_id'],
            'graph_run_reused': {'operation_id': origin['source_graph']['operation_id'],
                'preparation': origin['source_graph']['preparation'], 'reconstructed_this_run': False},
            'saved_scene_id': origin['saved_scene_id'], 'hip': origin['hip'],
            'nuke_script': file_record(project / 'saves/composite.nk'),
            'main_exr': file_record(project / 'saves/main.0001.exr'),
            'nuke_exr': file_record(project / 'saves/nuke.0001.exr'),
            'artifact_id': origin['artifact_id'], 'artifact_version': origin['artifact_version'],
            'artifact_registry_accepted': True, 'graph_run_accepted': True,
            'old_failed_graph_run_unchanged': True, 'human_visual_review': 'PENDING_USER',
            'upstream_executed_this_run': False,
            'reused_registered_artifact': prep['resume_nuke']['preparation'],
            'inherited_native_starts': prep['inherited_native_starts'],
            'this_run_native_starts': snapshot['dcc_starts'] - prep['inherited_native_starts'],
            'reused_inputs': prep['source'], 'comparisons': comparisons,
            'nuke_render_operation_id': rendered['operation_id'], 'native_scope': snapshot}
        journal.action('complete', lambda: result)
        write_new(root / 'incremental-result.json', result)
        return result


def run(preparation_path):
    """执行改动建图与必要下游，旧正式 GraphRun 和历史校准保持原样。"""
    from run_alpha_calibration import ScopeBudget
    from run_controlled_engineering import _stop_host, metadata_observations
    from vfx_pipeline.workbuddy_assembly import prepared_graph_facade
    path = Path(preparation_path)
    prep = load_record(file_record(path))
    root = path.parent
    project = Path(prep['project'])
    control = Path(prep.get('control', str(project / 'control')))
    if (prep.get('schema') != 'bridge.official-karma-incremental/1'
            or path != root / 'incremental-preparation.json' or ROOT != control / 'snapshot'):
        raise ValueError('INCREMENTAL_USE_PREPARED_SNAPSHOT_ENTRY')
    for name in ('manifest', 'snapshot_manifest', 'configuration'):
        checked_bytes(prep[name])
    for record in prep['source'].values():
        checked_bytes(record)
    if 'parameter_templates' in prep:
        from houdini_bridge.official_karma_templates import validate_parameter_templates
        checked_bytes(prep['parameter_templates'])
        configuration = load_record(prep['configuration'])
        if configuration.get('parameter_templates') != prep['parameter_templates']:
            raise ValueError('INCREMENTAL_TEMPLATE_BINDING_MISMATCH')
        validate_parameter_templates(configuration)
    source = _source(Path(prep['source']['scope']['path']).parent)
    if source['records'] != prep['source']:
        raise ValueError('INCREMENTAL_SOURCE_CHANGED')
    budget = ScopeBudget(root / 'scope.json')
    if budget.binding != prep['scope']:
        raise ValueError('INCREMENTAL_SCOPE_CHANGED')
    # NativeScope 已严格认证显式预算；工具侧启动预检复用同一份权威限额。
    budget.limits = copy.deepcopy(budget.native.scope['budget'])
    from houdini_bridge.alpha_reuse import validate_output_calibration
    if file_record(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py') != prep['active_plugin']:
        raise ValueError('INCREMENTAL_ACTIVE_ADDON_CHANGED')
    reused = validate_output_calibration(prep['alpha_calibration'], expected_version='21.0.631',
        expected_plugin_build=prep['active_plugin']['sha256'],
        expected_route_sha256=prep['calibration']['route_sha256'], evidence_source='real_host')
    if any(reused.get(name) != value for name, value in prep['calibration'].items()):
        raise ValueError('INCREMENTAL_REUSED_ALPHA_CHANGED')
    journal = Journal(root, path)
    if journal.value['stages']:
        return {'state': 'QUERY_REQUIRED', 'reason': 'INCREMENTAL_EXISTING_STAGES_NO_REPLAY',
                'journal': str(journal.path),
                'stages': {name: value['state'] for name, value in journal.value['stages'].items()}}
    budget.available(starts=2 if 'resume_nuke' in prep else 5 if 'resume_graph' in prep else 6)
    # 原生进程的 intent 会保存环境；只继承准备器白名单，避免带入父进程敏感变量。
    os.environ.clear()
    os.environ.update(prep['environment'])
    data = {'root': root, 'project': project, 'control': control,
        'manifest': _load(control / 'run.json'), 'scope': budget.scope,
        'scope_path': root / 'scope.json', 'scope_sha256': budget.binding['sha256']}
    cleanup = {}
    try:
        if 'resume_nuke' in prep:
            return _run_nuke_resumed(prep, source, budget, journal, data)
        if 'resume_graph' in prep:
            return _run_resumed(prep, source, budget, journal, data)
        with prepared_graph_facade(control / 'run.json', repo_root=ROOT,
                scheduler_root=root / 'scheduler', backend='production') as first:
            journal.action('task_domain', lambda: _registered_task_domain(first))
            for observation in metadata_observations(data, first.catalog()):
                first.submit_observation(**observation)
            proposed = journal.action('propose', lambda: first.graph_propose(
                {'schema': 'bridge.registered-domain-construction/1',
                 'domain_pack': 'lighting_camera_render_v1',
                 'houdini_version': '21.0.631', 'scene_profile': OFFICIAL},
                PREFIX + '_propose'))
            built = journal.action('build', lambda: first.graph_trial(proposed['graph_id'], PREFIX + '_build'))
            operation_id = built['operation_id']
            journal.action('build_completed', lambda: _poll(first, 'graph_status', operation_id,
                ('state',), budget, role='graph-worker'))
            handed = journal.action('handoff', lambda: first.graph_trial(proposed['graph_id'], PREFIX + '_build'))
            if ((handed.get('host_binding') or {}).get('graph_binding', {}).get('graph_ready') is not True):
                raise ValueError('INCREMENTAL_GRAPH_HANDOFF_REQUIRED')
            saved = journal.action('save', first.task_save)
            roles = {node['role']: node['path'] for node in saved['scene_contract']['nodes']}
            journal.action('initial_host_stop', lambda: _stop_host(data, 'houdini'))
        with prepared_graph_facade(control / 'run.json', repo_root=ROOT,
                scheduler_root=root / 'scheduler', backend='production') as second:
            journal.action('reopen', lambda: second.task_reopen(saved['saved_scene_id']))
            rendered = journal.action('render', lambda: second.houdini_render_bounded(
                PREFIX + '_render', saved['saved_scene_id'], roles['render'],
                str(project / 'saves/main.%04d.exr'), [1], min(120, budget.remaining())))
            journal.action('render_completed', lambda: _poll(second, 'operation_query',
                rendered['operation_id'], ('operation', 'state'), budget))
            journal.action('render_host_stop', lambda: _stop_host(data, 'houdini'))
            verified = journal.action('verify', lambda: second.verify_render_output(
                PREFIX + '_verify', rendered['operation_id']))
            image = verified['execution_fact']['metadata']['1']
            artifact = journal.action('register', lambda: second.register_render_artifact(
                ARTIFACT_ID, 'preview_temp', str(project / 'saves/main.%04d.exr'),
                [1], image['colorspace'], image['premultiplied'], PREFIX + '_verify'))
            consumed = journal.action('consume', lambda: second.consume_artifact(ARTIFACT_ID))
            if not consumed.get('usable_as_render_input'):
                raise ValueError('INCREMENTAL_REGISTERED_INPUT_UNUSABLE')

            def prepare_nuke():
                client = second.nuke_client
                output = str(project / 'saves/nuke.%04d.exr')
                client.call('set_knob', {'node': 'Write1', 'knob': 'file_type', 'value': 'exr'})
                binding = client.render_binding(second.pipeline_task_id, output, [1],
                    consumed['colorspace'], consumed['premultiplied'], artifact_binding=consumed)
                client.call('set_knob', {'node': 'Write1', 'knob': 'channels', 'value': 'rgba'})
                client.call('set_knob', {'node': 'Write1', 'knob': 'metadata', 'value': 'all metadata'})
                script = project / 'saves/composite.nk'
                result = client.call('save_script', {'path': str(script), 'overwrite': False})
                if result.get('path') != str(script):
                    raise ValueError('INCREMENTAL_NUKE_SAVE_MISMATCH')
                return {'script': file_record(script), 'input_artifact_id': ARTIFACT_ID,
                        'output_binding': binding}
            journal.action('nuke_prepare', prepare_nuke)
            nuke = journal.action('nuke_render', lambda: second.nuke_render_bounded(
                PREFIX + '_nuke', str(project / 'saves/nuke.%04d.exr'), [1], artifact_id=ARTIFACT_ID))
            journal.action('nuke_completed', lambda: _poll(second, 'operation_query',
                nuke['operation_id'], ('operation', 'state'), budget))
            journal.action('nuke_stop', lambda: _stop_host(data, 'nuke'))
            usable = second.artifact_registry.verify(ARTIFACT_ID)
            if not usable.get('usable'):
                raise ValueError('INCREMENTAL_FINAL_ARTIFACT_UNUSABLE')
            from houdini_bridge.official_karma import compare_files
            comparisons = journal.action('compare', lambda: {
                'official_to_bridge': compare_files(source['records']['reference']['path'],
                    str(project / 'saves/main.0001.exr')),
                'bridge_to_nuke': compare_files(str(project / 'saves/main.0001.exr'),
                    str(project / 'saves/nuke.0001.exr'), require_identical=True)})
            if any(item['state'] != 'PASS' for item in comparisons.values()):
                raise ValueError('INCREMENTAL_IMAGE_COMPARISON_FAILED')
            snapshot = budget.native.snapshot()
            if any(ticket.get('stopped_at') is None for ticket in snapshot['tickets']):
                raise ValueError('INCREMENTAL_ALL_STOPS_REQUIRED')
            task_domain = _registered_task_domain(second)
            result = {'schema': 'bridge.official-karma-incremental-result/1',
                'state': 'TASK_AND_ARTIFACT_REGISTERED', 'task_id': second.pipeline_task_id,
                'task_domain': task_domain,
                'graph_id': proposed['graph_id'], 'saved_scene_id': saved['saved_scene_id'],
                'hip': file_record(saved['path']), 'nuke_script': file_record(project / 'saves/composite.nk'),
                'artifact_id': artifact['artifact_id'], 'artifact_version': artifact['version'],
                'render_operation_id': rendered['operation_id'], 'verification_operation_id': PREFIX + '_verify',
                'artifact_registry_accepted': True, 'graph_run_accepted': True,
                'old_failed_graph_run_unchanged': True, 'human_visual_review': 'PENDING_USER',
                'reused_inputs': prep['source'], 'comparisons': comparisons,
                'nuke_render_operation_id': nuke['operation_id'],
                'native_scope': snapshot}
            journal.action('complete', lambda: result)
            write_new(root / 'incremental-result.json', result)
            return result
    except BaseException as error:
        if (control / 'production-hosts.json').is_file():
            for kind in _load(control / 'production-hosts.json').get('hosts', {}):
                try:
                    cleanup[kind] = _stop_host(data, kind)
                except Exception as stop_error:
                    cleanup[kind] = {'state': 'STOP_UNKNOWN', 'reason': str(stop_error)}
        journal.value['failure'] = {'error': str(error), 'cleanup': cleanup}
        journal.save()
        try:
            budget.fail('INCREMENTAL_EXECUTION_FAILED')
        except Exception:
            pass
        raise


def main():
    """显式区分零启动准备与已授权任务执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preparation = sub.add_parser('prepare')
    preparation.add_argument('--source', type=Path, required=True)
    preparation.add_argument('--output', type=Path, required=True)
    preparation.add_argument('--instruction', required=True)
    preparation.add_argument('--parameter-templates', type=Path, required=True)
    preparation.add_argument('--startup-diagnostics', action='store_true')
    continuation = sub.add_parser('prepare-resume')
    continuation.add_argument('--from-preparation', type=Path, required=True)
    continuation.add_argument('--namespace', required=True)
    continuation.add_argument('--instruction', required=True)
    nuke_continuation = sub.add_parser('prepare-nuke-resume')
    nuke_continuation.add_argument('--from-preparation', type=Path, required=True)
    nuke_continuation.add_argument('--namespace', required=True)
    nuke_continuation.add_argument('--instruction', required=True)
    execution = sub.add_parser('run')
    execution.add_argument('--preparation', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.source, args.output, args.instruction,
            parameter_templates=args.parameter_templates, startup_diagnostics=args.startup_diagnostics)
    elif args.command in ('prepare-resume', 'prepare-nuke-resume'):
        result = prepare_resume(args.from_preparation, args.namespace, args.instruction,
                                nuke_only=args.command == 'prepare-nuke-resume')
    else:
        result = run(args.preparation)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
