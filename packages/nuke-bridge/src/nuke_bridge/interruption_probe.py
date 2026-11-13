"""经控制范围明确启用的原生帧入口中断观测，普通渲染保持关闭。"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def probe_configuration(snapshot, snapshot_sha, contract):
    """只接受固定宿主配置、恢复范围及该范围唯一请求的交叉身份。"""
    config_path = os.environ.get('BRIDGE_NUKE_HOST_CONFIG')
    if config_path is None:
        return None
    path = Path(config_path)
    if not path.is_absolute() or path.is_symlink() or path.name != 'launch.json':
        raise ValueError('RECOVERY_PROBE_HOST_CONFIG_INVALID')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != os.environ.get('BRIDGE_NUKE_HOST_CONFIG_SHA256'):
        raise ValueError('RECOVERY_PROBE_HOST_CONFIG_CHANGED')
    config = json.loads(content)
    from dcc_task_runtime.native_scope import NativeScope
    scope = NativeScope(config['resource_budget']['native_scope'])
    phase = scope.scope.get('recovery_phase')
    if phase is None:
        return None
    from houdini_bridge.official_karma_observation import checked_bytes
    if (config.get('software_api') is not False or config.get('identity', {}).get('task_id') != phase['task_id']
            or not path.resolve().is_relative_to(scope.root)
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError('RECOVERY_PROBE_NATIVE_TASK_REQUIRED')
    operation = os.environ.get('BRIDGE_NUKE_TASK_ID', '')
    result = Path(os.environ.get('BRIDGE_NUKE_RESULT_FILE', ''))
    if (not operation or result != scope.root / 'state/nuke_renders' / (operation + '.worker-result.json')
            or snapshot != result.parent / (operation + '.nk')):
        raise ValueError('RECOVERY_PROBE_OPERATION_PATH_INVALID')
    record = json.loads((result.parent / (operation + '.json')).read_text())
    if record.get('request_id') != phase['interrupt_request_id']:
        return None
    source = json.loads(checked_bytes(phase['input_source']))
    binding = (contract or {}).get('input_binding', {})
    if (record.get('state') not in ('RUNNING', 'QUEUED') or record.get('owner_task_id') != phase['task_id']
            or contract is None or contract.get('owner_task_id') != phase['task_id']
            or (contract.get('registry_inputs', {}).get(source['artifact_id']) or {}).get('version') != source['artifact_version']
            or snapshot_sha != hashlib.sha256(snapshot.read_bytes()).hexdigest()):
        raise ValueError('RECOVERY_PROBE_INPUT_BINDING_INVALID')
    return {'schema': 'bridge.native-frame-interruption/1', 'task_id': phase['task_id'],
            'operation_id': operation, 'request_id': phase['interrupt_request_id'],
            'scope': scope.binding, 'pid': os.getpid(), 'snapshot_sha256': snapshot_sha,
            'input_contract_sha256': os.environ['BRIDGE_NUKE_INPUT_CONTRACT_SHA256'],
            'marker': str(result.parent / (operation + '.interruption.json'))}


@contextmanager
def frame_entry_probe(nuke, node, frames, snapshot, snapshot_sha, contract):
    """在真正的Nuke beforeFrameRender内暂停自身；终止仍由原监督器负责。"""
    config = probe_configuration(snapshot, snapshot_sha, contract)
    if config is None:
        yield
        return
    if frames != [1] or node.Class() != 'Write':
        raise ValueError('RECOVERY_PROBE_FRAME_NODE_INVALID')
    marker = Path(config.pop('marker'))
    def before_frame():
        if int(nuke.frame()) != 1 or nuke.thisNode().fullName() != node.fullName():
            raise ValueError('RECOVERY_PROBE_NATIVE_CALLBACK_MISMATCH')
        payload = dict(config, frame=1, node=node.fullName(), native_callback='beforeFrameRender',
                       observed_at=time.time(), nuke_version=str(nuke.NUKE_VERSION_STRING))
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.kill(os.getpid(), signal.SIGSTOP)
        # 该故障注入必须由监督取消结束，恢复执行不能把暂停后的继续当作成功。
        raise RuntimeError('RECOVERY_PROBE_MUST_BE_CANCELLED')
    nuke.addBeforeFrameRender(before_frame, nodeClass='Write')
    try:
        yield
    finally:
        nuke.removeBeforeFrameRender(before_frame, nodeClass='Write')
