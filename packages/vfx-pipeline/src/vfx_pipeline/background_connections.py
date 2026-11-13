"""管理独立的空后台连接；公开接口只接收不透明标识，不接受执行或工程路径。"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from dcc_task_runtime.platform_support import (atomic_write, ensure_private_directory,
    lock_file, open_private_file, process_identity, unlock_file)
from dcc_task_runtime.owned_process import OwnedProcessHandle

SCHEMA = 'bridge.background-connection/1'
PUBLIC_ERROR_CODES = frozenset({'CONNECTION_EXPIRED', 'CONNECTION_START_FAILED',
    'CONNECTION_CLEANUP_UNCONFIRMED', 'CONNECTION_HEALTH_UNVERIFIED', 'CONNECTION_START_INTERRUPTED',
    'CONNECTION_PYTHON_311_REQUIRED', 'CONNECTION_EXECUTABLE_UNAVAILABLE', 'CONNECTION_STATE_INVALID',
    'CONNECTION_ID_INVALID', 'CONNECTION_NOT_FOUND', 'CONNECTION_REQUEST_ID_INVALID',
    'CONNECTION_IDENTITY_MISMATCH'})
SESSION_SECONDS = 120
READY_SECONDS = 60
HYTHON = '/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/bin/hython'
NUKE = '/Applications/Nuke17.0v1/Nuke17.0v1.app/Contents/MacOS/Nuke17.0'
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
CONNECTION_ID = re.compile(r'^connection-[0-9a-f]{32}$')


def _plain(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('CONNECTION_STATE_INVALID')
    return path


def _read(path):
    path = _plain(path)
    if path.stat().st_nlink != 1:
        raise ValueError('CONNECTION_STATE_INVALID')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('CONNECTION_STATE_INVALID')
    return value


def _write(path, value):
    path = _plain(path)
    ensure_private_directory(path.parent)
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False).encode('utf-8'), owned_root=path.parent)


@contextlib.contextmanager
def _lock(root):
    ensure_private_directory(root)
    descriptor = open_private_file(root / 'connections.lock', os.O_CREAT | os.O_RDWR)
    try:
        lock_file(descriptor, blocking=True)
        yield
    finally:
        unlock_file(descriptor)
        os.close(descriptor)


def _task(directory):
    return directory / 'task'


def _control(directory):
    return _task(directory) / 'controller'


def _attempted(directory):
    """固定自有目录的 supervisor intent 表示已进入原生启动边界。"""
    task = _task(directory)
    return any(task.glob('controller/houdini-task-host/supervisor-*/intent.json')) or any(
        task.glob('nuke-host-*/supervisor/intent.json'))


def _public(record):
    result = {key: record[key] for key in ('connection_id', 'state', 'hosts',
        'expires_at', 'native_dispatch_attempted')}
    if record.get('error_code'):
        result['error_code'] = record['error_code']
    return result


def _host_binding(directory, kind, config):
    """只接纳本连接派生路径，核验签名启动事实与 nonce；绝不发现用户 GUI。"""
    task = _task(directory)
    expected = config['expected_identity']
    if (config.get('application') != kind or config.get('task_root') != str(task)
            or expected.get('task_id') != directory.name
            or not re.fullmatch('[0-9a-f]{32}', str(expected.get('launch_nonce', '')))
            or not isinstance(config.get('token'), str) or not config['token']):
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    nonce = expected['launch_nonce']
    work = _control(directory) / 'houdini-task-host' if kind == 'houdini' else task / ('nuke-host-' + nonce)
    if config.get('work_dir') != str(work):
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    if kind == 'houdini':
        binding = _read(work / 'supervisor-binding.json')
        supervisor = work / ('supervisor-' + nonce)
        identity = {'task_id': directory.name, 'launch_nonce': nonce}
        if binding != {'directory': str(supervisor), 'identity': identity}:
            raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    else:
        supervisor = work / 'supervisor'
        identity = config['supervisor_identity']
        if (config.get('supervisor_dir') != str(supervisor)
                or identity.get('task_id') != directory.name or identity.get('launch_nonce') != nonce
                or any(expected.get(key) != value for key, value in identity.items())):
            raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    _plain(supervisor)
    observed = OwnedProcessHandle(supervisor, identity)
    started = observed.started
    seconds = started.get('budget_seconds')
    at = started.get('observed_at')
    if (observed.pid != expected.get('pid') or type(seconds) not in (int, float)
            or seconds != SESSION_SECONDS or type(at) not in (int, float) or not math.isfinite(at)
            or expected.get('version') != ('21.0.631' if kind == 'houdini' else '17.0v1')
            or not expected.get('session_id')):
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    return observed, float(at + seconds)


def _deployments(directory):
    saved = _read(_control(directory) / 'production-hosts.json')
    if saved.get('task_id') != directory.name or not isinstance(saved.get('hosts'), dict) or not set(saved['hosts']) <= {'houdini', 'nuke'}:
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    for kind, config in saved['hosts'].items():
        _host_binding(directory, kind, config)
    return saved['hosts']


def _health(kind, config):
    """只用当前私有 token 认证；禁用客户端的用户实例 token 自动发现。"""
    if kind == 'houdini':
        from houdini_bridge.client import HoudiniClient
        client = HoudiniClient(config['port'], token='', timeout_seconds=3)
    else:
        from nuke_bridge.client import NukeClient
        client = NukeClient(config['port'], token='', timeout_seconds=3)
    client.token = config['token']
    client._token_candidates = (config['token'],)
    return client.health().get('task_host_identity')


def _observe(directory, record, *, initial=False):
    hosts = _deployments(directory)
    if set(hosts) != {'houdini', 'nuke'}:
        raise ValueError('CONNECTION_HOSTS_INCOMPLETE')
    anchors = record.setdefault('anchors', {})
    public = {}
    for kind, config in hosts.items():
        observed, expires = _host_binding(directory, kind, config)
        expected = config['expected_identity']
        birth = process_identity(observed.pid)
        if initial:
            anchors[kind] = {'identity': expected, 'birth': birth}
        anchor = anchors.get(kind, {})
        if (anchor.get('identity') != expected or anchor.get('birth') != birth
                or birth.get('state') != 'alive' or not birth.get('birth')
                or observed.poll() is not None or _health(kind, config) != expected):
            raise ValueError('CONNECTION_HEALTH_UNVERIFIED')
        public[kind] = {'pid': observed.pid, 'session_id': expected['session_id'],
            'version': expected['version'], 'expires_at': expires}
    record.update(hosts=public, expires_at=min(h['expires_at'] for h in public.values()),
        native_dispatch_attempted=True)
    if time.time() >= record['expires_at']:
        record.update(state='EXPIRED', error_code='CONNECTION_EXPIRED')
    else:
        record.update(state='CONNECTED')
        record.pop('error_code', None)
    return record


def _stop_owned_supervisor(supervisor, identity):
    """按固定意图收口；未发布 started 的监督器也先收到自有取消请求。"""
    from dcc_task_runtime.canonical import canonical_sha256
    from dcc_task_runtime.owned_process import read_receipt
    supervisor = _plain(supervisor)
    intent = _read(supervisor / 'intent.json')
    command = intent.get('command')
    if (intent.get('identity') != identity or not isinstance(command, list) or not command
            or not _plain(supervisor / 'receipt.key').is_file()):
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    # cancel 只写此目录，不按 PID 发信号；监督器持有并等待它自己的子进程。
    _write(supervisor / 'cancel.json', {'identity': identity})
    deadline = time.monotonic() + 6
    while read_receipt(supervisor, 'started', identity=identity) is None:
        if time.monotonic() >= deadline:
            raise ValueError('CONNECTION_CLEANUP_UNCONFIRMED')
        time.sleep(.01)
    observed = OwnedProcessHandle(supervisor, identity)
    if observed.started.get('argv_sha256') != canonical_sha256(command):
        raise ValueError('CONNECTION_IDENTITY_MISMATCH')
    if observed.poll() is None:
        observed.wait(timeout=max(0, deadline - time.monotonic()))
    if observed.poll() is None or observed.receipt() is None:
        raise ValueError('CONNECTION_CLEANUP_UNCONFIRMED')


def _cleanup(directory):
    """终止本连接拥有的宿主；部署文件和 ready 未发布时仍核验自有监督事实。"""
    from vfx_pipeline.production_hosts import stop_hosts
    success = True
    deployed = set()
    path = _control(directory) / 'production-hosts.json'
    if path.is_file():
        try:
            deployed = set(_deployments(directory))
        except Exception:
            success = False
        else:
            try:
                stop_hosts(_control(directory))
            except Exception:
                # ready 缺失等旧停止入口不能确认的窗口，由下方签名监督事实收口。
                pass
    work = _control(directory) / 'houdini-task-host'
    pointer = work / 'supervisor-binding.json'
    if pointer.is_file():
        try:
            binding = _read(pointer)
            identity = binding['identity']
            nonce = identity['launch_nonce']
            if (identity != {'task_id': directory.name, 'launch_nonce': nonce}
                    or not re.fullmatch('[0-9a-f]{32}', nonce)
                    or binding['directory'] != str(work / ('supervisor-' + nonce))):
                raise ValueError('CONNECTION_IDENTITY_MISMATCH')
        except Exception:
            success = False
    houdini_seen = False
    for supervisor in work.glob('supervisor-*'):
        if supervisor == pointer:
            continue
        try:
            if not re.fullmatch('supervisor-[0-9a-f]{32}', supervisor.name):
                raise ValueError('CONNECTION_IDENTITY_MISMATCH')
            identity = {'task_id': directory.name,
                'launch_nonce': supervisor.name.removeprefix('supervisor-')}
            _stop_owned_supervisor(supervisor, identity)
            houdini_seen = True
        except Exception:
            success = False
    if (pointer.is_file() or 'houdini' in deployed) and not houdini_seen:
        success = False
    nuke_seen = False
    for work in _task(directory).glob('nuke-host-*'):
        try:
            if not re.fullmatch('nuke-host-[0-9a-f]{32}', work.name):
                raise ValueError('CONNECTION_IDENTITY_MISMATCH')
            launch = _read(work / 'launch.json')
            identity = launch['identity']
            if identity.get('task_id') != directory.name or work.name != 'nuke-host-' + identity.get('launch_nonce', ''):
                raise ValueError('CONNECTION_IDENTITY_MISMATCH')
            _stop_owned_supervisor(work / 'supervisor', identity)
            nuke_seen = True
        except Exception:
            success = False
    if 'nuke' in deployed and not nuke_seen:
        success = False
    return bool(success)


class BackgroundConnections:
    """跨 MCP 持久的连接管理器；构造和状态读取都不会启动宿主或延长会话。"""
    def __init__(self, runtime_root, state_root):
        self.runtime_root = _plain(runtime_root)
        self.state_root = _plain(state_root)

    def _directory(self, connection_id):
        if not isinstance(connection_id, str) or not CONNECTION_ID.fullmatch(connection_id):
            raise ValueError('CONNECTION_ID_INVALID')
        return _plain(self.state_root / connection_id)

    def _load(self, connection_id):
        directory = self._directory(connection_id)
        path = directory / 'connection.json'
        if not path.is_file():
            raise ValueError('CONNECTION_NOT_FOUND')
        record = _read(path)
        if record.get('schema') != SCHEMA or record.get('connection_id') != connection_id:
            raise ValueError('CONNECTION_STATE_INVALID')
        return directory, record

    def _environment(self, directory):
        # 保留真实 HOME 和许可证变量；不继承旧工程、模型或用户 Python 注入路径。
        names = {'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE',
            'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE',
            'SESI_LMHOST', 'SESI_LMINFO', 'HOUDINI_LICENSE_SERVER',
            'FOUNDRY_LICENSE_FILE', 'foundry_LICENSE', 'RLM_LICENSE', 'LM_LICENSE_FILE'}
        env = {key: value for key, value in os.environ.items() if key in names}
        private = directory / 'environment'
        for name in ('preferences', 'packages', 'nuke', 'tmp'):
            ensure_private_directory(private / name)
        roots = [self.runtime_root / 'packages' / name / 'src' for name in
            ('vfx-pipeline', 'dcc-task-runtime', 'houdini-bridge', 'nuke-bridge')]
        env.update(PYTHONPATH=os.pathsep.join(map(str, roots)), PYTHONNOUSERSITE='1',
            PYTHONDONTWRITEBYTECODE='1', HOUDINI_USER_PREF_DIR=str(private / 'preferences' / '__HVER__'),
            HOUDINI_PACKAGE_DIR=str(private / 'packages'), HOUDINI_NO_ENV_FILE='1',
            NUKE_PATH=str(private / 'nuke'), TMPDIR=str(private / 'tmp'))
        return env

    def connect(self, request_id):
        """请求先持久化再启动，每个请求最多提交一次 H 和一次 N 原生启动。"""
        if not isinstance(request_id, str) or not ID.fullmatch(request_id):
            raise ValueError('CONNECTION_REQUEST_ID_INVALID')
        with _lock(self.state_root):
            request = self.state_root / ('request-' + hashlib.sha256(request_id.encode()).hexdigest() + '.json')
            if request.is_file():
                return self._status(_read(request)['connection_id'])
            connection_id = 'connection-' + uuid.uuid4().hex
            directory = self._directory(connection_id)
            ensure_private_directory(directory)
            record = {'schema': SCHEMA, 'connection_id': connection_id, 'state': 'CONNECTING',
                'hosts': {}, 'expires_at': None, 'native_dispatch_attempted': False}
            _write(request, {'connection_id': connection_id})
            _write(directory / 'connection.json', record)
            try:
                if sys.version_info[:2] != (3, 11):
                    raise ValueError('CONNECTION_PYTHON_311_REQUIRED')
                for executable in (Path(HYTHON), Path(NUKE), Path(sys.executable).resolve()):
                    if not executable.is_file() or executable.is_symlink() or not os.access(executable, os.X_OK):
                        raise ValueError('CONNECTION_EXECUTABLE_UNAVAILABLE')
                environment = self._environment(directory)
                process = subprocess.Popen([sys.executable, '-m', __name__, '--launch',
                    str(self.runtime_root), str(self.state_root), connection_id], env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                record['launcher'] = process_identity(process.pid)
                _write(directory / 'connection.json', record)
                process.wait(timeout=145)
                return self._status(connection_id)
            except Exception as exc:
                # 原始异常可能含凭据或本机路径，公开结果只保留固定错误码。
                if 'process' in locals() and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                cleanup = _cleanup(directory)
                record = _read(directory / 'connection.json')
                code = str(exc) if str(exc) in {'CONNECTION_PYTHON_311_REQUIRED', 'CONNECTION_EXECUTABLE_UNAVAILABLE'} else 'CONNECTION_START_FAILED'
                record.update(state='FAILED', error_code=code if cleanup else 'CONNECTION_CLEANUP_UNCONFIRMED',
                    native_dispatch_attempted=_attempted(directory))
                _write(directory / 'connection.json', record)
                return _public(record)

    def _status(self, connection_id):
        directory, record = self._load(connection_id)
        if record['state'] in {'FAILED', 'DISCONNECTED', 'EXPIRED'}:
            return _public(record)
        if record.get('expires_at') is not None and time.time() >= record['expires_at']:
            record.update(state='EXPIRED', error_code='CONNECTION_EXPIRED')
        elif record['state'] == 'CONNECTING':
            launcher = record.get('launcher')
            if launcher is not None and process_identity(launcher['pid']) == launcher:
                return _public(record)
            record.update(state='FAILED', error_code='CONNECTION_START_INTERRUPTED',
                native_dispatch_attempted=_attempted(directory))
        else:
            try:
                _observe(directory, record)
            except Exception:
                record.update(state='FAILED', error_code='CONNECTION_HEALTH_UNVERIFIED')
        _write(directory / 'connection.json', record)
        return _public(record)

    def status(self, connection_id):
        """实时认证两个原生宿主；只报告原连接，不重启、不续租。"""
        with _lock(self.state_root):
            return self._status(connection_id)

    def disconnect(self, connection_id):
        """仅停止此管理器私有目录持有的原生进程，不操作用户 GUI。"""
        with _lock(self.state_root):
            directory, record = self._load(connection_id)
            if record['state'] != 'DISCONNECTED':
                cleanup = _cleanup(directory)
                record.update(state='DISCONNECTED' if cleanup else 'FAILED',
                    native_dispatch_attempted=_attempted(directory))
                if cleanup:
                    record.pop('error_code', None)
                else:
                    record['error_code'] = 'CONNECTION_CLEANUP_UNCONFIRMED'
                _write(directory / 'connection.json', record)
            return _public(record)


def _intent(path):
    """独占创建每个宿主的启动意图，中断后也不可再次提交。"""
    descriptor = open_private_file(_plain(path))
    try:
        os.write(descriptor, b'{"state":"INTENT"}')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _launch(runtime_root, state_root, connection_id):
    """固定私有子进程入口：顺序启动一次，无自动重试，也不加载既有工程。"""
    from vfx_pipeline.production_hosts import validate_deployments, _h_config
    from houdini_bridge import task_host as houdini_host
    from nuke_bridge import task_host as nuke_host
    manager = BackgroundConnections(runtime_root, state_root)
    directory, record = manager._load(connection_id)
    # 父控制端先绑定辅助进程出生身份，避免极快启动覆盖父端持久化。
    deadline = time.monotonic() + 3
    while 'launcher' not in record and time.monotonic() < deadline:
        time.sleep(.01)
        directory, record = manager._load(connection_id)
    if record.get('state') != 'CONNECTING' or record.get('launcher') != process_identity(os.getpid()):
        return 1
    path = directory / 'connection.json'
    task = _task(directory)
    control = _control(directory)
    scheduler = task / 'scheduler'
    for owned in (task, control, scheduler):
        ensure_private_directory(owned)
    saved = {'task_id': connection_id, 'hosts': {}}
    try:
        common = {'lifecycle': 'task_owned', 'task_root': str(task),
            'supervisor_executable': str(Path(sys.executable).resolve()),
            'resource_budget': {'roots': [str(task)], 'max_bytes': 64 * 1024 * 1024},
            'session_seconds': SESSION_SECONDS, 'evidence_source': 'real_host'}
        h, n = validate_deployments(dict(common, application='houdini', version='21.0.631', executable=HYTHON),
            dict(common, application='nuke', version='17.0v1', executable=NUKE),
            controller_root=control, repo_root=manager.runtime_root)
        environment = {'HOUDINI_BRIDGE_STATE_DIR': str(control / 'houdini-instances'),
            'HOUDINI_BRIDGE_TASK_STATE_DIR': str(control / 'houdini-instances'),
            'BRIDGE_SKILLS_STATE_ROOT': str(task / 'state'),
            'BRIDGE_ARTIFACT_LEDGER_ROOT': str(control / 'artifact_ledger'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT': str(scheduler)}
        work = control / 'houdini-task-host'
        # 每个 host 的 INTENT 先落盘；中断后绝不重放启动。
        _intent(directory / 'houdini-intent.json')
        with contextlib.redirect_stdout(io.StringIO()):
            code = houdini_host.start(argparse.Namespace(task_id=connection_id, work_dir=str(work),
                addon_root=str(manager.runtime_root / 'plugins/houdini'), houdini_bin=HYTHON,
                version=h['version'], max_seconds=SESSION_SECONDS, ready_timeout=READY_SECONDS,
                poll_seconds=.01, warmup=False, supervisor_executable=h['supervisor_executable'],
                resource_budget=h['resource_budget'], environment=environment, evidence_source='real_host',
                allow_software_processes=False))
        if code:
            raise ValueError('CONNECTION_START_FAILED')
        saved['hosts']['houdini'] = _h_config(h, work, control, task_id=connection_id)
        _write(control / 'production-hosts.json', saved)
        _intent(directory / 'nuke-intent.json')
        receipt = nuke_host.start(task_id=connection_id, task_root=task, nuke_executable=NUKE,
            addon_path=manager.runtime_root / 'plugins/nuke/nuke_bridge_addon.py',
            supervisor_executable=n['supervisor_executable'], version=n['version'],
            budget_seconds=SESSION_SECONDS, ready_timeout_seconds=READY_SECONDS,
            resource_budget=n['resource_budget'], ledger_root=control / 'artifact_ledger',
            scheduler_root=scheduler, controller_root=control)
        saved['hosts']['nuke'] = dict(n, **receipt)
        _write(control / 'production-hosts.json', saved)
        _observe(directory, record, initial=True)
        _write(path, record)
    except BaseException:
        cleanup = _cleanup(directory)
        record.update(state='FAILED', error_code='CONNECTION_START_FAILED' if cleanup else 'CONNECTION_CLEANUP_UNCONFIRMED',
            native_dispatch_attempted=_attempted(directory))
        _write(path, record)
        return 1
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--launch', nargs=3, required=True)
    args = parser.parse_args()
    raise SystemExit(_launch(*args.launch))
