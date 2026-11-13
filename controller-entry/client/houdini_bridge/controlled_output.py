"""Detached output verification from an authenticated, frozen render original."""
from __future__ import annotations

import copy
import hashlib
import math
import os
import stat
from pathlib import Path
import tempfile

from . import client
from dcc_task_runtime.owned_process import _canonical, read_receipt, execution_returncode
from dcc_task_runtime.exr_codec import read_exr, _parse_header
from dcc_task_runtime.project_color import validate_project_color

_POLICY = {'policy': 'controlled_output_v1', 'scene_variant': 'sphere_ground_v2',
           'resolution': [128, 128], 'frames': [1], 'channels': ['R', 'G', 'B', 'A']}
NATIVE_INTERNAL_UNKNOWNS = [
    'effective_writer_color_processor', 'effective_writer_lut', 'effective_writer_file_rule',
    'executed_aov_identity', 'executed_ordered_image_filters',
    'actual_writer_instance', 'writer_flush_close_results',
]


def validate_controlled_policy(value):
    from dcc_task_runtime.render_profiles import OFFICIAL, GEOMETRY, output_policy
    allowed = (_POLICY, output_policy(OFFICIAL), output_policy(GEOMETRY))
    if not isinstance(value, dict) or not any(_canonical(value) == _canonical(item) for item in allowed):
        raise ValueError('CONTROLLED_OUTPUT_POLICY_INVALID')
    return copy.deepcopy(value)


def controlled_route_sha256(readback, *, require_color_route=False):
    """Bind the explicitly observed output route, excluding scene-specific paths."""
    keys = ('resolution', 'denoiser', 'motion_blur', 'image_filters', 'products', 'renderer', 'colorspace', 'aov_semantics')
    if not isinstance(readback, dict) or any(key not in readback for key in keys):
        raise ValueError('CONTROLLED_OUTPUT_CONFIG_READBACK_REQUIRED')
    if 'output_color_route' in readback:
        if readback['output_color_route'] != {'source': 'scene_linear', 'output': 'ACEScg'}:
            raise ValueError('CONTROLLED_OUTPUT_COLOR_ROUTE_INVALID')
        keys += ('output_color_route',)
    elif require_color_route:
        raise ValueError('CONTROLLED_OUTPUT_COLOR_ROUTE_REQUIRED')
    return hashlib.sha256(_canonical({key: readback[key] for key in keys})).hexdigest()


def _configuration(producer, policy):
    config = producer['render_config'].get('1', {})
    readback = config.get('controlled_output_readback')
    if not isinstance(readback, dict):
        raise ValueError('CONTROLLED_OUTPUT_CONFIG_READBACK_REQUIRED')
    if (readback.get('scene_variant') != policy['scene_variant']
            or readback.get('resolution') != policy['resolution']
            or any(type(value) is not int for value in readback.get('resolution', []))
            or readback.get('aov_semantics') != 'karma_beauty_lpe_v1'
            or readback.get('renderer') != 'BRAY_HdKarma'
            or readback.get('colorspace') != producer.get('project_color', {}).get('colorspace')
            or not isinstance(readback.get('colorspace'), str) or not readback['colorspace']
            or readback.get('denoiser') != 'off'
            or type(readback.get('motion_blur')) is not bool or readback['motion_blur']
            or readback.get('image_filters') != []
            or readback.get('products') != [{'kind': 'beauty', 'channels': policy['channels'], 'multipart': False}]
            or type(readback['products'][0].get('multipart')) is not bool
            or not isinstance(readback.get('houdini_version'), str) or not readback['houdini_version']
            or not isinstance(readback.get('plugin_build'), str) or not readback['plugin_build']
            or config.get('exr_format', {}).get('storage') != 'scanline'
            or type(config.get('exr_format', {}).get('multipart')) is not int
            or config['exr_format']['multipart'] != 0):
        raise ValueError('CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY')
    return readback


def _decode_snapshot(snapshot, *, resolution=None, channels=None):
    """Fully decode the exact hashed copy, with path identity checked on both sides."""
    if type(snapshot.get('bytes')) is not int or not 0 < snapshot['bytes'] <= 32 * 1024 * 1024:
        raise ValueError('CONTROLLED_OUTPUT_BYTE_BUDGET_EXCEEDED')
    path = Path(snapshot['path'])
    client._render_file_observation(path, snapshot)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != snapshot['bytes']:
            raise ValueError('CONTROLLED_OUTPUT_BYTES_CHANGED')
        payload = stream.read(snapshot['bytes'] + 1)
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError('CONTROLLED_OUTPUT_BYTES_CHANGED')
    if len(payload) != snapshot['bytes'] or hashlib.sha256(payload).hexdigest() != snapshot['sha256']:
        raise ValueError('CONTROLLED_OUTPUT_BYTES_CHANGED')
    header, _ = _parse_header(payload)
    if resolution is not None and [header['max_x'] - header['min_x'] + 1,
                                   header['max_y'] - header['min_y'] + 1] != resolution:
        raise ValueError('CONTROLLED_OUTPUT_EXR_OUTSIDE_POLICY')
    if channels is not None and sorted(channel['name'] for channel in header['channels']) != sorted(channels):
        raise ValueError('CONTROLLED_OUTPUT_EXR_OUTSIDE_POLICY')
    with tempfile.TemporaryDirectory(prefix='controlled-output-') as directory:
        frozen = Path(directory) / 'frame.exr'
        frozen.write_bytes(payload)
        decoded = read_exr(frozen, with_pixels=True)
    client._render_file_observation(path, snapshot)
    values = [sample for row in decoded['rows'] for samples in row['channels'].values() for sample in samples]
    if len(values) != decoded['sample_count'] or any(not math.isfinite(sample) for sample in values):
        raise ValueError('CONTROLLED_OUTPUT_NONFINITE_PIXELS')
    if any(not 0 <= sample <= 1 for row in decoded['rows'] for sample in row['channels'].get('A', [])):
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RANGE_INVALID')
    decoded.pop('rows')
    return decoded


def _validate_exr_color(image, expected, *, evidence_source="real_host"):
    """Keep the native header distinct from the human project selection."""
    metadata = image.get('color_metadata', {})
    if not metadata and evidence_source == 'real_host':
        raise ValueError('CONTROLLED_OUTPUT_COLORSPACE_UNVERIFIED')
    token = metadata.get('oiio:ColorSpace')
    # Houdini 21.0.631 bundled OCIO config declares these ACEScg aliases.
    aliases = {'ACEScg', 'ACES - ACEScg', 'lin_ap1'} if expected == 'ACEScg' else {expected}
    if token is not None and token not in aliases:
        raise ValueError('CONTROLLED_OUTPUT_COLORSPACE_CONFLICT')
    chromaticities = metadata.get('chromaticities')
    if expected == 'ACEScg' and chromaticities is not None:
        ap1_d60 = (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767)
        if len(chromaticities) != 8 or any(not math.isfinite(v) or abs(v - e) > 0.00001
                for v, e in zip(chromaticities, ap1_d60)):
            raise ValueError('CONTROLLED_OUTPUT_CHROMATICITIES_CONFLICT')


def _verify_historical_scope(scope_binding, historical_scope, supervisor, started, stopped):
    """只读取已结束生产的原范围，不能把下游失败转成预算豁免或重新启动授权。"""
    from dcc_task_runtime.native_scope import NativeScope
    from .official_karma_observation import checked_bytes
    if (not isinstance(historical_scope, dict) or set(historical_scope) != {'path', 'bytes', 'sha256'}
            or {key: historical_scope[key] for key in ('path', 'sha256')} != scope_binding):
        raise ValueError('CONTROLLED_OUTPUT_HISTORICAL_SCOPE_MISMATCH')
    checked_bytes(historical_scope)
    scope = NativeScope(scope_binding)
    # 完成观察认证原签名记账与停止事实，不套用目录后来增长后的实时磁盘占用。
    state = scope.completed_snapshot()
    tickets = state['tickets']
    allowed = state.get('closed_reason') in (None, 'INCREMENTAL_EXECUTION_FAILED')
    if state.get('closed_reason')=='NATIVE_SCOPE_EXECUTION_FAILED' and scope.scope.get('feedback_phase'):
        # 只复用成功生产后的事实；同反馈阶段仅 Nuke 控制宿主可失败。
        phase = scope.scope['feedback_phase']
        base = NativeScope({key:phase['prior_scope'][key] for key in ('path','sha256')}).completed_snapshot()
        added = tickets[len(base['tickets']):]
        failed = [t for t in added if scope._stop(t) is None or execution_returncode(scope._stop(t))!=0]
        allowed = (len(failed)==1 and failed[0]['role']=='nuke-host'
                   and not any(t['role']=='nuke-render' for t in added))
    if not allowed and state.get('closed_reason') == 'NATIVE_SCOPE_EXECUTION_FAILED':
        from dcc_task_runtime.native_scope import GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE
        if (scope.scope.get('schema') == GEOMETRY_SCOPE_SCHEMA
                and scope.resource_profile == GEOMETRY_RESOURCE_PROFILE):
            grant_path = scope.root / 'geometry-nuke-recovery-authorization.json'
            if grant_path.exists() or grant_path.is_symlink():
                from dcc_task_runtime.geometry_nuke_recovery import validate
                from .official_karma_observation import file_record
                from dcc_task_runtime.native_scope import _accounting_lock
                with _accounting_lock(scope.state_path):
                    _, _, closed = validate(scope, file_record(grant_path))
                    # 逐字段绑定原始签名状态，不能用同十票但额外marker的后续关闭状态。
                    original_matches = _canonical(scope._read()) == _canonical(closed)
                    # 许可仅供历史只读核验；不激活、不改变实时预算或执行门。
                    allowed = (original_matches
                               and closed.get('scope_sha256') == state.get('scope_sha256')
                               and closed.get('closed_reason') == state.get('closed_reason')
                               and _canonical(closed['tickets']) == _canonical(tickets))
    if not allowed and state.get('closed_reason') == 'NATIVE_SCOPE_EXECUTION_FAILED':
        from dcc_task_runtime.native_scope import GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE
        if (scope.scope.get('schema') == GEOMETRY_SCOPE_SCHEMA and scope.resource_profile == GEOMETRY_RESOURCE_PROFILE):
            from dcc_task_runtime.geometry_nuke_save_recovery import historical_closed_state
            # 仅新用户17/NH3许可精确绑定的原closed15可观察；fresh执行门仍关闭。
            closed = historical_closed_state(scope)
            allowed = closed is not None and _canonical(closed['tickets']) == _canonical(tickets)
    if not allowed and state.get('closed_reason') == 'NATIVE_SCOPE_EXECUTION_FAILED':
        from dcc_task_runtime.native_scope import GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE
        if scope.scope.get('schema') == GEOMETRY_SCOPE_SCHEMA and scope.resource_profile == GEOMETRY_RESOURCE_PROFILE:
            from dcc_task_runtime.geometry_seed_cold_recovery import historical_closed_state
            # 只观察同17上限NR-only许可精确固定的closed16，不开放fresh执行。
            closed=historical_closed_state(scope)
            allowed=closed is not None and _canonical(closed['tickets']) == _canonical(tickets)
    if (not allowed or any(ticket.get('stopped_at') is None for ticket in tickets)):
        raise ValueError('CONTROLLED_OUTPUT_HISTORICAL_SCOPE_NOT_STOPPED')
    import time
    now = time.time()
    if any(ticket['admitted_at'] > now or ticket['stopped_at'] > now + 1 for ticket in tickets):
        raise ValueError('CONTROLLED_OUTPUT_HISTORICAL_SCOPE_CLOCK_INVALID')
    charges = [max(ticket['charged_seconds'], ticket['stopped_at'] - ticket['admitted_at'])
               for ticket in tickets]
    if (sum(charges) > scope.scope['budget']['total_seconds']
            or any(charge > scope.role_seconds(ticket['role'])
                   for ticket, charge in zip(tickets, charges))):
        raise ValueError('CONTROLLED_OUTPUT_HISTORICAL_SCOPE_BUDGET_EXCEEDED')
    matches = [ticket for ticket in tickets
               if ticket['role'] == 'houdini-host' and ticket.get('parent') is None
               and ticket['directory'] == supervisor['directory']
               and ticket['identity'] == supervisor['identity']]
    if (len(matches) != 1 or matches[0]['stopped_at'] != stopped.get('observed_at')
            or matches[0].get('stopped_sha256') != hashlib.sha256(_canonical(stopped)).hexdigest()
            or started.get('identity') != supervisor['identity']
            or execution_returncode(stopped) != 0):
        raise ValueError('CONTROLLED_OUTPUT_HISTORICAL_PRODUCER_TICKET_REQUIRED')
    return scope


def verify_controlled_output(binding, *, task_id, operation_id, verification_id, policy, alpha_calibration,
                             evidence_source='real_host', historical_scope=None, render_terminal_recovery=None):
    """Reauthenticate source facts; never upgrade or reseal their render receipt."""
    policy = validate_controlled_policy(policy)
    if (not isinstance(verification_id, str) or not verification_id.strip()
            or verification_id == operation_id):
        raise ValueError('CONTROLLED_OUTPUT_VERIFICATION_ID_INVALID')
    source = client.read_render_operation(binding, task_id=task_id, operation_id=operation_id)
    record, original = source['operation'], source['execution_fact']
    producer = client.render_producer_binding(record)
    if producer.get('output_acceptance') != policy:
        raise ValueError('CONTROLLED_OUTPUT_FROZEN_POLICY_REQUIRED')
    if producer != binding.get('producer_binding'):
        raise ValueError('CONTROLLED_OUTPUT_PRODUCER_MISMATCH')
    if (not isinstance(original, dict) or original.get('state') != 'COMPLETED'
            or original.get('operation_receipt_sha256') != client.render_receipt_digest(original)
            or original.get('frame_set') != policy['frames'] or original.get('frames_done') != policy['frames']
            or record.get('frames') != policy['frames']):
        raise ValueError('CONTROLLED_OUTPUT_COMPLETED_ORIGINAL_REQUIRED')
    client._verify_render_terminal(binding, original)
    supervisor = producer['supervisor_binding']
    started = read_receipt(supervisor['directory'], 'started', identity=supervisor['identity'])
    stopped = read_receipt(supervisor['directory'], 'stopped', identity=supervisor['identity'])
    recovery = None
    validated_scope = None
    if render_terminal_recovery is not None:
        from vfx_pipeline.rectlight_render_terminal_recovery import validate_render_terminal_recovery
        recovery = validate_render_terminal_recovery(render_terminal_recovery,binding=binding,verification_id=verification_id)
        if (evidence_source!='real_host' or recovery['started']!=started or recovery['stopped']!=stopped
                or recovery['policy']!=policy or recovery['alpha_calibration']!=alpha_calibration
                or historical_scope is not None and historical_scope!=recovery['source_scope']):
            raise ValueError('CONTROLLED_OUTPUT_TERMINAL_RECOVERY_BINDING_MISMATCH')
    else:
        if (not started or not stopped or started.get('pid') != producer['host_identity'].get('pid')
                or stopped.get('pid') != started.get('pid') or execution_returncode(stopped) != 0):
            raise ValueError('CONTROLLED_OUTPUT_SUCCESSFUL_TREE_STOP_REQUIRED')
        scope_binding = (started.get('resource_budget') or {}).get('native_scope')
        if historical_scope is not None:
            validated_scope = _verify_historical_scope(scope_binding, historical_scope, supervisor, started, stopped)
        elif scope_binding is not None:
            from dcc_task_runtime.native_scope import NativeScope
            validated_scope = NativeScope(scope_binding)
            validated_scope.check()
    readback = _configuration(producer, policy)
    color = validate_project_color(producer.get('project_color'))
    from .alpha_reuse import validate_output_calibration
    if evidence_source not in ('real_host', 'software_test'):
        raise ValueError('CONTROLLED_OUTPUT_EVIDENCE_SOURCE_INVALID')
    # 保留原校准身份；仅通过明确来源与非渲染变更核验后允许跨构建复用。
    # 只向本轮已认证新profile透传绑定；旧范围仍按原历史alpha默认路线。
    alpha_task = {}
    if validated_scope is not None:
        from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
        if validated_scope.resource_profile == RECT_SHAPE_PROFILE:
            alpha_task['shape_scope_binding'] = validated_scope.binding
    calibration = validate_output_calibration(alpha_calibration,
        expected_version=readback['houdini_version'], expected_plugin_build=readback['plugin_build'],
        expected_route_sha256=controlled_route_sha256(readback, require_color_route=evidence_source == 'real_host'), evidence_source=evidence_source, **alpha_task)
    if type(calibration.get('associated')) is not bool:
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_CALIBRATION_REQUIRED')
    snapshots = copy.deepcopy(original['frame_snapshots'])
    if set(snapshots) != {'1'}:
        raise ValueError('CONTROLLED_OUTPUT_FRAME_SNAPSHOT_REQUIRED')
    image = _decode_snapshot(snapshots['1'], resolution=policy['resolution'], channels=policy['channels'])
    expected_window = [0, 0, policy['resolution'][0] - 1, policy['resolution'][1] - 1]
    if ([image['width'], image['height']] != policy['resolution']
            or image['channel_layout']['data_window'] != expected_window
            or image['channel_layout']['display_window'] != expected_window
            or sorted(image['channels']) != sorted(policy['channels'])
            or len(image['channels']) != 4):
        raise ValueError('CONTROLLED_OUTPUT_EXR_OUTSIDE_POLICY')
    _validate_exr_color(image, color['colorspace'], evidence_source=evidence_source)
    image.update(copy.deepcopy(snapshots['1']), colorspace=color['colorspace'],
                 premultiplied=calibration['associated'], project_color=color,
                 color_metadata_source='human_project_selection', verification_basis='controlled_output_v1')
    fact = {key: copy.deepcopy(original[key]) for key in (
        'frame_set', 'frames_done', 'output_pattern', 'started_at_epoch', 'scene_fingerprint',
        'dependencies', 'host_identity')}
    fact.update(schema='bridge.houdini.controlled-output/1.0', command='output.verify', kind='output_verification',
        operation_id=verification_id, parent_operation_id=operation_id, task_id=task_id,
        state='COMPLETED', stop_confirmed=True, completion_metadata_status='AVAILABLE',
        verification_basis='controlled_output_v1', native_internal_status='NOT_OBSERVED',
        native_internal_unknowns=list(NATIVE_INTERNAL_UNKNOWNS), policy=policy,
        source_receipt_sha256=original['operation_receipt_sha256'],
        stopped_receipt_sha256=hashlib.sha256(_canonical(stopped)).hexdigest(),
        started_receipt_sha256=hashlib.sha256(_canonical(started)).hexdigest(),
        project_color=color, frame_snapshots=snapshots, metadata={'1': image},
        alpha_calibration=calibration, evidence_source=evidence_source)
    if recovery is not None:
        # 同步render完成与所有者稍后的失败分别保留，不推定husk退出码。
        fact['render_terminal_recovery']=copy.deepcopy(render_terminal_recovery)
        fact['render_terminal_recovery_basis']=copy.deepcopy(recovery['basis'])
        fact['native_internal_unknowns'].append('writer_process_exit_code')
    fact['operation_receipt_sha256'] = client.render_receipt_digest(fact)
    return copy.deepcopy(fact)
