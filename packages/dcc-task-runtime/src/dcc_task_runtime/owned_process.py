"""Durable observations from a supervisor that owns and waits for one child.

This module is also the fixed supervisor executable. A restarted controller
reads its exact receipt; PID disappearance or a worker's own result is never
used as a substitute for wait() returning on the owned process.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import queue
import secrets
import signal
import stat
import subprocess
import sys
import time
import threading

if __package__:
    from .platform_support import atomic_write, ensure_private_directory, open_private_file, process_identity
    if os.name == 'nt':
        from .windows_process import WindowsJobProcess
    else:
        WindowsJobProcess = None
else:
    import importlib
    import types
    _support_root = Path(__file__).resolve().parent
    _support_name = '_bridge_owned_support_' + hashlib.sha256(str(_support_root).encode()).hexdigest()
    _support_package = types.ModuleType(_support_name)
    _support_package.__package__ = _support_name
    _support_package.__path__ = [str(_support_root)]
    sys.modules.setdefault(_support_name, _support_package)
    _support = importlib.import_module(_support_name + '.platform_support')
    atomic_write = _support.atomic_write
    ensure_private_directory = _support.ensure_private_directory
    open_private_file = _support.open_private_file
    process_identity = _support.process_identity
    WindowsJobProcess = (importlib.import_module(_support_name + '.windows_process').WindowsJobProcess
                         if os.name == 'nt' else None)

SCHEMA = 'bridge.owned_process/1'
MAX_LOG_BYTES = 1024 * 1024
WRITER_COLLECTION_SECONDS = 22  # Runtime freeze (5s) + observe (16s), with scheduling margin.
_WRITER_STARTUP_STOP_RESERVE_SECONDS = 10
_READY_ENV = ('BRIDGE_OWNED_SUPERVISOR_DIR', 'BRIDGE_OWNED_SUPERVISOR_IDENTITY',
              'BRIDGE_OWNED_RUNTIME_NONCE', 'BRIDGE_OWNED_WRITER_COLLECTION_END', 'BRIDGE_OWNED_SESSION_END')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def execution_returncode(receipt):
    """Separate execution success from a signed observation that the tree stopped.

    Legacy receipts preserve stop facts and a nonzero leader status, but their
    leader zero alone cannot establish success of any unobserved descendants.
    """
    code = receipt.get('exit_code')
    if type(code) is not int:
        raise ValueError('SUPERVISOR_EXECUTION_NOT_BOUND')
    if 'execution_protocol' not in receipt:
        return code if code != 0 else 2
    unobserved = receipt.get('descendant_result_unobserved')
    reason = receipt.get('stop_reason')
    supervisor_code = 2 if unobserved or (reason is not None and code == 0) else 0
    result = ('failed' if reason is not None or code != 0 else
              'unknown' if unobserved else 'succeeded')
    if (type(receipt.get('execution_protocol')) is not int or receipt['execution_protocol'] != 1
            or type(unobserved) is not bool
            or (reason is not None and not isinstance(reason, str))
            or type(receipt.get('supervisor_exit_code')) is not int
            or receipt['supervisor_exit_code'] != supervisor_code
            or receipt.get('execution_result') != result):
        raise ValueError('SUPERVISOR_EXECUTION_NOT_BOUND')
    return supervisor_code if supervisor_code else code


def _atomic(path, value):
    path = Path(path)
    atomic_write(path, _canonical(value), owned_root=path.parent)


def _read(path):
    path = Path(path)
    if path.is_symlink(): raise ValueError('SUPERVISOR_SYMLINK')
    return json.loads(path.read_text(encoding='utf-8'))


def _signed_write(directory, payload):
    key = (directory / 'receipt.key').read_bytes()
    _atomic(directory / (payload['event'] + '.json'), {
        'payload': payload, 'signature': hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()})


def read_receipt(directory, event, *, identity):
    directory = Path(directory)
    path = directory / (event + '.json')
    if not path.exists(): return None
    envelope = _read(path); payload = envelope['payload']
    key_path = directory / 'receipt.key'
    if key_path.is_symlink(): raise ValueError('SUPERVISOR_SYMLINK')
    expected = hmac.new(key_path.read_bytes(), _canonical(payload), hashlib.sha256).hexdigest()
    if (not hmac.compare_digest(expected, str(envelope.get('signature', '')))
            or payload.get('schema') != SCHEMA or payload.get('event') != event
            or payload.get('identity') != identity):
        raise ValueError('SUPERVISOR_RECEIPT_MISMATCH')
    if event == 'started' and (os.name == 'nt' or payload.get('platform') == 'windows'):
        birth = payload.get('process_birth')
        job = payload.get('job')
        if (payload.get('platform') != 'windows' or type(payload.get('pid')) is not int
                or payload['pid'] <= 0 or not isinstance(birth, str) or not birth.isdigit()
                or int(birth) <= 0 or not isinstance(job, dict)
                or not isinstance(job.get('name'), str) or not job['name'].startswith('BridgeOwnedJob-')
                or job.get('assigned_at_creation') is not True or job.get('kill_on_close') is not True
                or job.get('process_is_in_job') is not True):
            raise ValueError('SUPERVISOR_WINDOWS_START_NOT_BOUND')
    if event == 'stopped':
        start = read_receipt(directory, 'started', identity=identity)
        if (not start or payload.get('started_sha256') != hashlib.sha256(_canonical(start)).hexdigest()
                or payload.get('pid') != start.get('pid') or payload.get('observed_by') != 'owned_child_wait'
                or type(payload.get('exit_code')) is not int):
            raise ValueError('SUPERVISOR_STOP_NOT_BOUND')
        if 'execution_protocol' in start or 'execution_protocol' in payload:
            if (type(start.get('execution_protocol')) is not int or start['execution_protocol'] != 1
                    or type(payload.get('execution_protocol')) is not int
                    or payload['execution_protocol'] != start['execution_protocol']):
                raise ValueError('SUPERVISOR_EXECUTION_NOT_BOUND')
            execution_returncode(payload)
        if start.get('platform') == 'windows':
            if (payload.get('platform') != 'windows'
                    or payload.get('process_birth') != start['process_birth']
                    or payload.get('job') != start['job'] or payload.get('child_wait_observed') is not True
                    or type(payload.get('job_active_processes')) is not int
                    or payload['job_active_processes'] != 0):
                raise ValueError('SUPERVISOR_WINDOWS_STOP_NOT_BOUND')
    return payload


def _incremental_houdini_startup(directory, spec, native_scope):
    """认证的官方增量或几何 Houdini 宿主共享原会话的启动就绪窗口。"""
    if native_scope is None:
        return False
    import importlib
    module = importlib.import_module((__package__ or _support_name) + '.native_scope')
    official = (native_scope.resource_profile == module.OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                and native_scope.scope.get('execution_mode') == module.OFFICIAL_INCREMENTAL_MODE)
    geometry = native_scope.resource_profile == module.GEOMETRY_RESOURCE_PROFILE
    if (not (official or geometry)
            or (spec.get('native_scope_ticket') or {}).get('role') != 'houdini-host'):
        return False
    if (spec.get('resource_budget') or {}).get('native_scope') != native_scope.binding:
        raise ValueError('NATIVE_SCOPE_IDENTITY_CONFLICT')
    # 验证同一签名账本、原始目录和身份；角色上限仍取原范围的120或240秒。
    _scope_remaining(directory, spec, native_scope)
    return True


def _writer_runtime_spec(directory, spec, *, remaining_seconds=None,startup_diagnostic=False,
                         native_scope=None):
    now = time.monotonic()
    seconds = spec['budget_seconds'] if remaining_seconds is None else remaining_seconds
    session_end = now + seconds
    collection_end = min(session_end, now + WRITER_COLLECTION_SECONDS)
    if _incremental_houdini_startup(directory, spec, native_scope):
        observe_seconds = _process_images().OBSERVE_TIMEOUT_SECONDS
        # 完整启动和实际映像观察共享已有会话；为观察及停止保留确定窗口。
        if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                or not observe_seconds + _WRITER_STARTUP_STOP_RESERVE_SECONDS < seconds
                    <= native_scope.role_seconds('houdini-host')):
            raise ValueError('SUPERVISOR_WRITER_STARTUP_BUDGET_INSUFFICIENT')
        collection_end = session_end - _WRITER_STARTUP_STOP_RESERVE_SECONDS
    runtime = {'nonce': secrets.token_hex(16), 'session_end': session_end,
               'collection_end': collection_end}
    environment = dict(spec.get('env', {}))
    if startup_diagnostic:
        folder=Path(directory)/'startup-trace';folder.mkdir(mode=0o700,exist_ok=False)
        environment['BRIDGE_OWNED_STARTUP_TRACE_DIR']=str(folder)
    environment.update(zip(_READY_ENV, (str(directory), _canonical(spec['identity']).decode('utf-8'),
        runtime['nonce'], str(runtime['collection_end']), str(runtime['session_end']))))
    return {**spec, 'env': environment, 'writer_runtime': runtime}


def _ready_payload(payload, *, identity, pid, command_hash, runtime):
    if (type(payload) is not dict or set(payload) != {'schema', 'event', 'identity', 'pid',
            'argv_sha256', 'runtime_nonce', 'observed_at'}
            or payload.get('schema') != SCHEMA or payload.get('event') != 'runtime-ready'
            or payload.get('identity') != identity or type(payload.get('pid')) is not int
            or payload['pid'] != pid or payload.get('argv_sha256') != command_hash
            or payload.get('runtime_nonce') != runtime['nonce']
            or type(payload.get('observed_at')) not in (int, float)
            or not math.isfinite(payload['observed_at'])):
        raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_MISMATCH')


def _wait_writer_runtime_ready(directory, spec, pid, cancelled, deadline):
    command_hash = hashlib.sha256(_canonical(spec['command'])).hexdigest()
    while True:
        if any(path.is_symlink() for path in (directory / 'runtime-ready.json', directory, *directory.parents)):
            raise ValueError('SUPERVISOR_WRITER_RUNTIME_DIRECTORY_INVALID')
        if cancelled.is_set():
            raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_CANCELLED')
        if time.monotonic() >= deadline:
            raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT')
        payload = read_receipt(directory, 'runtime-ready', identity=spec['identity'])
        if payload is not None:
            _ready_payload(payload, identity=spec['identity'], pid=pid,
                           command_hash=command_hash, runtime=spec['writer_runtime'])
            if cancelled.is_set():
                raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_CANCELLED')
            return
        time.sleep(.01)


def runtime_ready_and_wait():
    """Publish this fixed runtime code point, then hold for the owned image proof."""
    directory = Path(os.environ.get(_READY_ENV[0], ''))
    if (not directory.is_absolute() or any(path.is_symlink() for path in (directory, *directory.parents))):
        raise ValueError('SUPERVISOR_WRITER_RUNTIME_DIRECTORY_INVALID')
    spec = _read(directory / 'intent.json')
    runtime = spec.get('writer_runtime')
    if (not isinstance(runtime, dict) or set(runtime) != {'nonce', 'session_end', 'collection_end'}
            or 'writer_executable' not in spec
            or type(runtime['nonce']) is not str or len(runtime['nonce']) != 32
            or any(type(runtime[key]) not in (int, float) or not math.isfinite(runtime[key])
                   for key in ('session_end', 'collection_end'))
            or not 0 < runtime['collection_end'] <= runtime['session_end']
            or not isinstance(spec.get('command'), list) or not spec['command']
            or any(type(arg) is not str or not arg for arg in spec['command'])):
        raise ValueError('SUPERVISOR_WRITER_RUNTIME_INTENT_INVALID')
    expected_env = (str(directory), _canonical(spec['identity']).decode('utf-8'), runtime['nonce'],
                    str(runtime['collection_end']), str(runtime['session_end']))
    if any(os.environ.get(key) != value or spec['env'].get(key) != value
           for key, value in zip(_READY_ENV, expected_env)):
        raise ValueError('SUPERVISOR_WRITER_RUNTIME_ENVIRONMENT_MISMATCH')
    identity = spec['identity']; pid = os.getpid()
    command_hash = hashlib.sha256(_canonical(spec['command'])).hexdigest()
    if time.monotonic() >= runtime['collection_end']:
        raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT')
    ready = read_receipt(directory, 'runtime-ready', identity=identity)
    if ready is None:
        _signed_write(directory, {'schema': SCHEMA, 'event': 'runtime-ready', 'identity': identity,
            'pid': pid, 'argv_sha256': command_hash, 'runtime_nonce': runtime['nonce'], 'observed_at': time.time()})
    else:
        _ready_payload(ready, identity=identity, pid=pid, command_hash=command_hash, runtime=runtime)
    while time.monotonic() < runtime['collection_end']:
        cancel = directory / 'cancel.json'
        if cancel.exists() and _read(cancel).get('identity') == identity:
            raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_CANCELLED')
        if read_receipt(directory, 'stopped', identity=identity) is not None:
            raise ValueError('SUPERVISOR_WRITER_RUNTIME_ALREADY_STOPPED')
        started = read_receipt(directory, 'started', identity=identity)
        if started is not None:
            if (type(started.get('pid')) is not int or started['pid'] != pid
                    or started.get('argv_sha256') != command_hash):
                raise ValueError('SUPERVISOR_WRITER_RUNTIME_START_MISMATCH')
            if started.get('writer_process_binding_error') is not None:
                raise ValueError('SUPERVISOR_WRITER_RUNTIME_BINDING_FAILED:' + str(started['writer_process_binding_error']))
            binding = started.get('writer_process_binding')
            if (type(binding) is not dict or set(binding) != {'expected_executable', 'host_anchor'}
                    or binding['expected_executable'] != spec['writer_executable']
                    or type(binding['host_anchor']) is not dict
                    or type(binding['host_anchor'].get('pid')) is not int or binding['host_anchor']['pid'] != pid):
                raise ValueError('SUPERVISOR_WRITER_RUNTIME_BINDING_INVALID')
            return
        time.sleep(.01)
    raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT')


class OwnedProcessHandle:
    def __init__(self, directory, identity, *, supervisor=None):
        self.directory = Path(directory); self.identity = dict(identity)
        self._supervisor = supervisor
        self.started = read_receipt(self.directory, 'started', identity=self.identity)
        if self.started is None: raise ValueError('SUPERVISOR_START_UNCONFIRMED')
        self.pid = self.started['pid']; self.returncode = None

    def poll(self):
        receipt = read_receipt(self.directory, 'stopped', identity=self.identity)
        if receipt is not None: self.returncode = execution_returncode(receipt)
        return self.returncode

    def terminate(self):
        _atomic(self.directory / 'cancel.json', {'identity': self.identity})

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('owned supervisor', timeout)
            time.sleep(.01)
        if self._supervisor is not None:
            remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
            self._supervisor.wait(timeout=remaining)
        return self.returncode

    def receipt(self):
        return read_receipt(self.directory, 'stopped', identity=self.identity)


class SupervisorNotStarted(ValueError):
    """A preflight rejection before either supervisor or child was spawned."""


def _disk_usage(resource_budget):
    if resource_budget is None:
        return None
    if (not isinstance(resource_budget, dict)
            or type(resource_budget.get('max_bytes')) is not int
            or resource_budget['max_bytes'] <= 0
            or not isinstance(resource_budget.get('roots'), list)
            or not resource_budget['roots']):
        raise ValueError('SUPERVISOR_DISK_BUDGET_INVALID')
    total = 0; seen = set()
    for raw in resource_budget['roots']:
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError('SUPERVISOR_DISK_ROOT_INVALID')
        root = Path(raw)
        if any(item.is_symlink() for item in (root, *root.parents)):
            raise ValueError('SUPERVISOR_DISK_ROOT_SYMLINK')
        if not root.exists():
            continue
        pending = [root]
        while pending:
            path = pending.pop()
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError('SUPERVISOR_DISK_OUTPUT_SYMLINK')
            if stat.S_ISDIR(info.st_mode):
                try:
                    pending.extend(path.iterdir())
                except FileNotFoundError:
                    # A concurrently removed directory has no remaining bytes.
                    # A replacement or inaccessible path remains unobservable.
                    try:
                        path.lstat()
                    except FileNotFoundError:
                        continue
                    raise
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def _signal_group(process, signum):
    if os.name == 'nt':
        process.terminate()
        return
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def _private_log(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    fd = open_private_file(path, flags)
    return os.fdopen(fd, 'ab', buffering=0)


def _process_images():
    # The supervisor also runs this file directly, under its private support
    # package. Import the same sibling implementation without PYTHONPATH lookup.
    import importlib
    return importlib.import_module((__package__ or _support_name) + '.process_image')


def _freeze_writer_executable(writer):
    if not isinstance(writer, dict):
        raise ValueError('SUPERVISOR_WRITER_EXECUTABLE_INVALID')
    frozen = _process_images().freeze_executable(writer['image']['path'], writer['version'], writer['image']['sha256'])
    if _canonical(frozen) != _canonical(writer):
        raise ValueError('SUPERVISOR_WRITER_EXECUTABLE_CHANGED')
    return frozen


def _start_writer_collection(writer, pid, *, directory=None, spec=None, native_scope=None):
    """Collect only data; the owning supervision thread alone signs receipts.

    Runtime freeze/observe have their own 5s/16s bounds. Readiness shares the
    absolute collection deadline without consuming the OS observation window.
    The caller also stops
    accepting results at its collection/session deadline; cancellation prevents
    a late refreeze from starting another OS observation.
    """
    results = queue.Queue(maxsize=1)
    cancelled = threading.Event()

    def phase(name,detail=None):
        if native_scope is None or native_scope.scope.get('execution_mode') not in ('official_writer_startup_diagnostic_v1','official_writer_window_diagnostic_v1'):return
        try:
            import importlib
            module=importlib.import_module((__package__ or _support_name)+'.startup_trace')
            module.stage(Path(directory)/'startup-trace','collector_'+name,pid=os.getpid(),extra=detail)
        except BaseException:
            try:sys.stderr.write('STARTUP_COLLECTOR_CHECKPOINT_FAILED\n')
            except BaseException:pass

    def collect():
        images = None;trace=None;trace_record=None
        phase('entry')
        try:
            images = _process_images()
            import importlib
            policy_images = importlib.import_module((__package__ or _support_name) + '.process_image')
            policy = (native_scope.collector_policy() if native_scope is not None
                      else policy_images.scope_collector_policy({}))
            policy_images.check_collector_tools(policy, min(spec['writer_runtime']['collection_end'],
                spec['writer_runtime']['session_end']))
            phase('freeze_start')
            frozen = _freeze_writer_executable(writer)
            phase('freeze_done')
            if cancelled.is_set():
                return
            runtime = spec['writer_runtime']
            collection_end = min(runtime['collection_end'], runtime['session_end'])
            phase('ps_start')
            parent, birth = images._ps(pid, min(collection_end,
                time.monotonic() + images.OBSERVE_TIMEOUT_SECONDS))
            phase('ps_done')
            phase('ready_wait_start')
            ready_end = collection_end
            if _incremental_houdini_startup(directory, spec, native_scope):
                # 未就绪时按确定截止失败，不能挤占后续最多 16 秒的原生观察。
                ready_end -= images.OBSERVE_TIMEOUT_SECONDS
            _wait_writer_runtime_ready(directory, spec, pid, cancelled, ready_end)
            phase('ready_observed')
            if cancelled.is_set():
                return
            observe_end = min(collection_end, time.monotonic() + images.OBSERVE_TIMEOUT_SECONDS)
            phase('observe_start')
            def observe():
                with policy_images.collector_policy_scope(policy):
                    return images._observe(pid, observe_end)
            if native_scope is not None and native_scope.scope.get('execution_mode') in ('official_writer_identity_diagnostic_v1','official_writer_identity_survey_v1'):
                import importlib
                module=importlib.import_module((__package__ or _support_name)+'.writer_tool_trace')
                trace=module.ToolTrace(directory/'writer-tool-trace',writer_pid=pid,
                    identity=spec['identity'],scope_binding=native_scope.binding,collection_end=collection_end,
                    tools=native_scope.scope['writer_trace_tools'],collector_policy=policy)
                with images.diagnostic_tool_observer(trace):anchor=observe()
            elif native_scope is not None and native_scope.scope.get('execution_mode')=='official_writer_window_diagnostic_v1':
                import importlib
                module=importlib.import_module((__package__ or _support_name)+'.window_trace')
                trace=module.SignedToolEvents(directory,identity=spec['identity'],scope_binding=native_scope.binding,writer_pid=pid,spec=spec,collector_policy=policy)
                with images.diagnostic_tool_observer(trace):anchor=observe()
            else:anchor = observe()
            phase('observe_done')
            if cancelled.is_set():
                return
            if time.monotonic() >= collection_end:
                raise ValueError('SUPERVISOR_WRITER_COLLECTION_TIMEOUT')
            if (not isinstance(anchor, dict) or anchor.get('parent_pid') != parent
                    or int(images._birth(anchor.get('birth')).timestamp()) != birth):
                raise ValueError('SUPERVISOR_WRITER_HOST_ANCHOR_CHANGED')
            if (not isinstance(anchor, dict) or type(anchor.get('pid')) is not int
                    or anchor['pid'] != pid):
                raise ValueError('SUPERVISOR_WRITER_HOST_ANCHOR_INVALID')
            binding = {'expected_executable': frozen, 'host_anchor': anchor}
            result = ('writer_process_binding', json.loads(_canonical(binding)))
        except Exception as exc:
            phase('error',type(exc).__name__+':'+str(exc))
            result = ('writer_process_binding_error', type(exc).__name__ + ':' + str(exc))
            diagnostic = getattr(exc, 'diagnostic', None)
            if images is not None and isinstance(exc, images.ProcessImageError) and type(diagnostic) is dict:
                # The bounded tool diagnostic is signed for debugging only;
                # it never supplies or repairs an executable/host binding.
                encoded = _canonical(diagnostic)
                if len(encoded) <= 16 * 1024:
                    result += (json.loads(encoded),)
        finally:
            if trace is not None:
                try:trace_record=trace.close()
                except Exception as error:
                    trace_record={'record':None,'cleanup_complete':False,'error':type(error).__name__+':'+str(error)[:512]}
        if trace_record is not None:
            if not trace_record['cleanup_complete'] and result[0]=='writer_process_binding':
                result=('writer_process_binding_error','SUPERVISOR_WRITER_TRACE_INCOMPLETE')
            if len(result)==2:result+=(None,)
            result+=(trace_record,)
        if not cancelled.is_set():
            results.put_nowait(result)

    try:
        threading.Thread(target=collect, daemon=True, name='writer-process-binding').start()
    except Exception as exc:
        results.put_nowait(('writer_process_binding_error', type(exc).__name__ + ':' + str(exc)))
    return results, cancelled


def _native_scope(binding):
    if __package__:
        from .native_scope import NativeScope
    else:
        NativeScope = importlib.import_module(_support_name + '.native_scope').NativeScope
    return NativeScope(binding)


def _scope_remaining(directory, spec, scope):
    """Bind a HIP session's deadline to its durable admission, including startup."""
    ticket = spec.get('native_scope_ticket')
    if (not isinstance(ticket, dict) or ticket.get('identity') != spec['identity']
            or ticket.get('directory') != str(Path(directory).resolve())):
        raise ValueError('NATIVE_SCOPE_IDENTITY_CONFLICT')
    cap = scope.role_seconds(ticket.get('role'))
    seconds = spec['budget_seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= cap:
        raise ValueError('SUPERVISOR_BUDGET_INVALID')
    return max(0, min(scope.remaining_seconds(ticket),
                      ticket['admitted_at'] + seconds - time.time()))


def launch(command, *, directory, identity, supervisor_executable, env=None, budget_seconds=120,
           resource_budget=None, writer_executable=None, scope_role=None, scope_heavy=True,on_supervisor_spawned=None):
    if (type(budget_seconds) not in (int, float) or not math.isfinite(budget_seconds)
            or budget_seconds <= 0):
        raise ValueError('SUPERVISOR_BUDGET_INVALID')
    scope_binding = (resource_budget or {}).get('native_scope')
    scope = None
    if scope_binding is not None:
        try:
            if not scope_role:
                raise ValueError('NATIVE_SCOPE_LAUNCH_ROLE_REQUIRED')
            scope = _native_scope(scope_binding)
            cap = scope.role_seconds(scope_role)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SupervisorNotStarted(str(exc)) from exc
    else:
        cap = 120
    if on_supervisor_spawned is not None and (not callable(on_supervisor_spawned) or scope is None
            or scope.scope.get('execution_mode') not in ('official_writer_startup_diagnostic_v1','official_writer_window_diagnostic_v1') or writer_executable is None):
        raise SupervisorNotStarted('SUPERVISOR_DIAGNOSTIC_CALLBACK_FORBIDDEN')
    if budget_seconds > cap:
        raise ValueError('SUPERVISOR_BUDGET_INVALID')
    if not identity or not all(isinstance(v, (str, int)) for v in identity.values()):
        raise ValueError('SUPERVISOR_IDENTITY_INVALID')
    try:
        if writer_executable is not None:
            writer_executable = _freeze_writer_executable(writer_executable)
        used = _disk_usage(resource_budget)
        if used is not None and used > resource_budget['max_bytes']:
            raise ValueError('SUPERVISOR_DISK_BUDGET_EXCEEDED')
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        raise SupervisorNotStarted(str(exc)) from exc
    directory = Path(directory)
    environment = dict(env if env is not None else os.environ)
    scope_ticket = None
    if scope_binding is not None:
        try:
            if not scope_role:
                raise ValueError('NATIVE_SCOPE_LAUNCH_ROLE_REQUIRED')
            scope_ticket = scope.admit(scope_role, directory, identity, heavy=scope_heavy)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SupervisorNotStarted(str(exc)) from exc
        if scope_ticket.get('reused'):
            raise SupervisorNotStarted('NATIVE_SCOPE_AUTOMATIC_RETRY_FORBIDDEN')
        environment['BRIDGE_NATIVE_SCOPE_BINDING'] = _canonical(scope_binding).decode('utf-8')
        environment['BRIDGE_NATIVE_SCOPE_TICKET'] = scope_ticket['id']
    elif environment.get('BRIDGE_NATIVE_SCOPE_BINDING'):
        raise SupervisorNotStarted('NATIVE_SCOPE_PROPAGATION_REQUIRED')
    directory = ensure_private_directory(directory, exist_ok=False)
    key_path = directory / 'receipt.key'
    fd = open_private_file(key_path)
    with os.fdopen(fd, 'wb') as stream: stream.write(secrets.token_bytes(32))
    spec = {'command': list(command), 'identity': dict(identity), 'env': environment,
            'budget_seconds': budget_seconds, 'resource_budget': resource_budget}
    if scope_ticket is not None:
        spec['native_scope_ticket'] = scope_ticket
        if scope.resource_profile is not None and _scope_remaining(directory, spec, scope) <= 0:
            raise SupervisorNotStarted('NATIVE_SCOPE_TIME_EXHAUSTED')
    if writer_executable is not None:
        spec['writer_executable'] = writer_executable
    _atomic(directory / 'intent.json', spec)
    started_wait_end = None
    if writer_executable is not None and _incremental_houdini_startup(directory, spec, scope):
        # 监督器启动前锚定账本剩余时间，父进程不能因旧 25 秒等待先行报未知。
        started_wait_end = time.monotonic() + _scope_remaining(directory, spec, scope)
    with _private_log(directory / 'supervisor.stdout.log') as output, \
            _private_log(directory / 'supervisor.stderr.log') as errors:
        process = subprocess.Popen([str(supervisor_executable), '-B', str(Path(__file__).resolve()),
                                    '--supervise', str(directory)], stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=errors, start_new_session=os.name != 'nt',
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    deadline = (started_wait_end if started_wait_end is not None else
                time.monotonic() + (25 if writer_executable is not None else 10))
    observer_error=None
    if on_supervisor_spawned is not None:
        try:on_supervisor_spawned(process)
        except BaseException as error:
            observer_error=error
            try:_atomic(directory/'cancel.json',{'identity':identity})
            except Exception:pass
    threading.Thread(target=process.wait, daemon=True).start()
    # The caller must retain its reservation on an ambiguous launch exception.
    while time.monotonic() < deadline:
        if read_receipt(directory, 'started', identity=identity):
            if observer_error is not None:raise RuntimeError('SUPERVISOR_DIAGNOSTIC_OBSERVER_FAILED') from observer_error
            return OwnedProcessHandle(directory, identity, supervisor=process)
        if process.poll() is not None:
            raise RuntimeError('SUPERVISOR_START_FAILED_OR_UNKNOWN')
        time.sleep(.01)
    raise RuntimeError('SUPERVISOR_START_UNKNOWN')


def supervise(directory):
    directory = Path(directory); spec = _read(directory / 'intent.json')
    budget = spec.get('resource_budget') or {}
    scope = _native_scope(budget['native_scope']) if 'native_scope' in budget else None
    if scope is not None:
        scope.check()
        if scope.scope.get('schema') == 'bridge.softbody-shot-scope/1':
            package = scope.__class__.__module__.rsplit('.', 1)[0]
            importlib.import_module(package + '.softbody_shot_scope').check_step(scope, directory, spec)
    remaining = (_scope_remaining(directory, spec, scope)
                 if scope is not None and scope.resource_profile is not None else None)
    if remaining is not None and remaining <= 0:
        raise ValueError('NATIVE_SCOPE_TIME_EXHAUSTED')
    if 'writer_executable' in spec:
        spec = _writer_runtime_spec(directory, spec, remaining_seconds=remaining,
            startup_diagnostic=scope is not None and scope.scope.get('execution_mode') in ('official_writer_startup_diagnostic_v1','official_writer_window_diagnostic_v1'),
            native_scope=scope)
        if scope is not None and scope.scope.get('execution_mode')=='official_writer_window_diagnostic_v1':spec['env']['BRIDGE_OWNED_WINDOW_MODE']='1'
        _atomic(directory / 'intent.json', spec)
    with _private_log(directory / 'child.stdout.log') as output, \
            _private_log(directory / 'child.stderr.log') as errors:
        if os.name == 'nt':
            process = WindowsJobProcess(spec['command'], env=spec['env'], stdout=output, stderr=errors)
        else:
            process = subprocess.Popen(spec['command'], env=spec['env'], stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=errors, start_new_session=True)
        popen_monotonic=time.monotonic()
    try:
        return _supervise_owned(directory, spec, process, native_scope=scope,popen_monotonic=popen_monotonic)
    finally:
        if os.name == 'nt':
            process.close()


def _supervise_owned(directory, spec, process, *, native_scope=None,popen_monotonic=None):
    identity = spec['identity']
    scoped_remaining = None
    scope_deadline = None
    scope_initial_error = None
    if (native_scope is not None and (spec.get('resource_budget') or {}).get('native_scope') is not None
            and native_scope.resource_profile is not None):
        try:
            observed_at = time.monotonic()
            scoped_remaining = _scope_remaining(directory, spec, native_scope)
            scope_deadline = observed_at + scoped_remaining
        except (OSError, ValueError, KeyError, TypeError) as error:
            # The child already exists: keep ownership and stop it in the loop.
            scoped_remaining, scope_initial_error = 0.0, error
            scope_deadline = time.monotonic()
    if 'writer_executable' in spec and 'writer_runtime' not in spec:
        # Direct software state-machine tests enter after constructing their child.
        spec = _writer_runtime_spec(directory, spec, native_scope=native_scope)
    # Include writer collection in the child's existing session budget.
    deadline = spec['writer_runtime']['session_end'] if 'writer_executable' in spec else None
    if deadline is not None and scope_deadline is not None:
        deadline = min(deadline, scope_deadline)
    start = {'schema': SCHEMA, 'event': 'started', 'identity': identity, 'pid': process.pid,
             'execution_protocol': 1, 'budget_seconds': spec['budget_seconds'],
             'argv_sha256': hashlib.sha256(_canonical(spec['command'])).hexdigest(),
             'resource_budget': spec.get('resource_budget'), 'observed_at': time.time(),
             'platform': 'windows' if os.name == 'nt' else 'posix',
             'supervisor_identity': process_identity(os.getpid())}
    if os.name == 'nt':
        start.update(process_birth=process.birth, job=process.job_facts)
    startup_event_error=None
    if native_scope is not None and native_scope.scope.get('execution_mode') in ('official_writer_startup_diagnostic_v1','official_writer_window_diagnostic_v1'):
        try:
            _signed_write(directory,{'schema':SCHEMA,'event':'diagnostic-child','identity':identity,
                'purpose':'STARTUP_DIAGNOSTIC_ONLY_NO_IMAGE_PROOF','scope_binding':native_scope.binding,
                'pid':process.pid,'supervisor_pid':os.getpid(),'supervisor_identity':start['supervisor_identity'],
                'ticket_id':spec['native_scope_ticket']['id'],'runtime_nonce':spec['writer_runtime']['nonce'],
                'argv_sha256':start['argv_sha256'],'popen_return_monotonic':time.monotonic() if popen_monotonic is None else popen_monotonic,
                'popen_time_origin':'direct_test_entry' if popen_monotonic is None else 'owned_popen_return',
                'collection_end_monotonic':spec['writer_runtime']['collection_end'],'observed_at':time.time()})
        except Exception as error:startup_event_error=type(error).__name__+':'+str(error)[:256]
    collection = None
    collection_deadline = None
    start_written = False
    if 'writer_executable' in spec:
        collection_deadline = spec['writer_runtime']['collection_end']
        collection = _start_writer_collection(spec['writer_executable'], process.pid, directory=directory, spec=spec, native_scope=native_scope)
    else:
        _signed_write(directory, start)
        start_written = True
        deadline = time.monotonic() + spec['budget_seconds'] if scope_deadline is None else scope_deadline
    # HIP work and controller work share this admission-derived boundary.
    # Keep the final ten seconds inside the unchanged hard scope deadline.
    work_deadline = deadline - 10 if scope_deadline is not None else deadline

    def finish_start(error=None):
        nonlocal start_written, stop_reason
        if start_written:
            return True
        if 'writer_process_binding' in start or 'writer_process_binding_error' in start:
            pass  # Preserve the first collection outcome if receipt I/O failed.
        elif error is None:
            try:
                result = collection[0].get_nowait()
                key, value = result[:2]
                if len(result) >= 3 and result[2] is not None:
                    start['writer_process_binding_diagnostic'] = result[2]
                if len(result) == 4:
                    start['writer_tool_trace'] = result[3]
                start[key] = value
            except queue.Empty:
                return False
        else:
            start['writer_process_binding_error'] = error
        collection[1].set()
        if 'writer_process_binding_error' in start:
            stop_reason = stop_reason or 'SUPERVISOR_WRITER_COLLECTION_FAILED'
        try:
            _signed_write(directory, start)
        except (OSError, ValueError):
            # A later diagnostic write must never publish a releasable start
            # after this attempt has already entered failure/termination.
            start.setdefault('writer_process_binding_error', 'SUPERVISOR_WRITER_START_WRITE_FAILED')
            raise
        start_written = True
        return True

    stop_at = None
    next_kill_at = None
    denied_signals = set()
    observation_failure_attempted = False

    def observation_failed(phase, error, reason):
        nonlocal observation_failure_attempted
        if observation_failure_attempted:
            return
        observation_failure_attempted = True
        try:
            finish_start('SUPERVISOR_WRITER_OBSERVATION_FAILED')
            filename = getattr(error, 'filename', None)
            payload = {'schema': SCHEMA, 'event': 'observation-failed',
                'identity': identity, 'pid': process.pid, 'phase': phase, 'stop_reason': reason,
                'exception_type': type(error).__name__, 'errno': getattr(error, 'errno', None),
                'message': str(error)[:512], 'filename': None if filename is None else str(filename)[:512],
                'observed_at': time.time(),
                'started_sha256': hashlib.sha256(_canonical(start)).hexdigest()}
            _signed_write(directory, payload)
        except (OSError, ValueError):
            try:
                sys.stderr.write('SUPERVISOR_OBSERVATION_DIAGNOSTIC_WRITE_FAILED\n')
                sys.stderr.flush()
            except (OSError, ValueError):
                pass

    def signal_denied(signum, error):
        # A refused signal proves neither cancellation nor group absence.
        # Preserve the first signed refusal per signal without log/write churn.
        if signum in denied_signals:
            return
        finish_start('SUPERVISOR_WRITER_SIGNAL_DENIED')
        _signed_write(directory, {'schema': SCHEMA, 'event': 'signal-denied-' + str(int(signum)),
            'identity': identity, 'pid': process.pid, 'signal': int(signum),
            'errno': error.errno, 'stop_reason': stop_reason,
            'observed_by': 'owned_group_signal', 'observed_at': time.time(),
            'started_sha256': hashlib.sha256(_canonical(start)).hexdigest()})
        denied_signals.add(signum)

    def request_signal(signum):
        try:
            _signal_group(process, signum)
        except PermissionError as error:
            signal_denied(signum, error)
    stop_reason = ('NATIVE_SCOPE_BUDGET_EXCEEDED_OR_UNOBSERVABLE'
                   if scope_initial_error is not None else None)
    if startup_event_error is not None:stop_reason=stop_reason or 'SUPERVISOR_DIAGNOSTIC_CHILD_WRITE_FAILED'
    observed_bytes = None; next_disk_check = 0; next_scope_check = 0
    operation = None; operation_deadline = None; descendant_result_unobserved = False
    log_roots = [str((directory / name).resolve()) for name in (
        'child.stdout.log', 'child.stderr.log', 'supervisor.stdout.log', 'supervisor.stderr.log')]
    log_budget = {'roots': log_roots, 'max_bytes': MAX_LOG_BYTES}
    budget = spec.get('resource_budget')
    scope = native_scope
    operation_cap = (scope.role_seconds(spec['native_scope_ticket']['role'])
                     if scoped_remaining is not None and scope_initial_error is None else 120)
    if budget is not None:
        # Diagnostics are task output even when their private directory is
        # outside the caller's output roots. Inode accounting avoids doubles.
        budget = {**budget, 'roots': list(budget['roots']) + log_roots}
    while True:
        tree_stopped = False
        code = process.poll()
        if os.name == 'nt':
            active = process.active_processes()
            if active is None:
                finish_start('SUPERVISOR_WRITER_CHILD_STATE_UNKNOWN')
                return 2
            if code is not None and active == 0:
                if start_written:
                    break
                tree_stopped = True
            elif code is not None:
                descendant_result_unobserved = True
        elif code is not None:
            # The owned parent can exit before its same-group children finish.
            # Keep the existing cancellation and budget supervision active until
            # the whole group is observed absent; a live group is not stopped.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                if start_written:
                    break
                tree_stopped = True
            except PermissionError as error:
                signal_denied(0, error)
                stop_reason = stop_reason or 'SUPERVISOR_GROUP_STATE_UNKNOWN'
            if not tree_stopped:
                descendant_result_unobserved = True
        cancel_path = directory / 'cancel.json'
        cancelled = cancel_path.exists() and _read(cancel_path).get('identity') == identity
        now = time.monotonic()
        operation_path = directory / 'operation-budget.json'
        if operation_path.exists():
            try:
                offered = read_receipt(directory, "operation-budget", identity=identity)
                if operation is not None:
                    finished = read_receipt(directory, 'operation-finished-' + operation['token'], identity=identity)
                    if (finished is not None and finished.get('operation_id') == operation['operation_id']
                            and finished.get('token') == operation['token']
                            and finished.get('host_identity') == operation['host_identity']
                            and finished.get('pid') == process.pid and finished.get('finished') is True):
                        operation = None; operation_deadline = None
                valid = (offered.get('identity') == identity and offered.get('pid') == process.pid
                         and offered.get('host_identity', {}).get('pid') == process.pid
                         and offered.get('host_identity', {}).get('task_id') == identity.get('task_id')
                         and offered.get('host_identity', {}).get('launch_nonce') == identity.get('launch_nonce')
                         and isinstance(offered.get('operation_id'), str) and bool(offered['operation_id'])
                         and isinstance(offered.get('token'), str) and bool(offered['token'])
                         and type(offered.get('budget_seconds')) in (int, float)
                         and 0 < offered['budget_seconds'] <= operation_cap
                         and type(offered.get('started_at_epoch')) in (int, float))
                if valid:
                    if operation is None and offered.get('finished') is not True:
                        operation = offered
                        remaining = max(0, min(offered['budget_seconds'],
                            offered['started_at_epoch'] + offered['budget_seconds'] - time.time()))
                        operation_deadline = now + remaining
                        _signed_write(directory, {
                            'schema': SCHEMA, 'event': 'operation-budget-observed',
                            'identity': identity, 'pid': process.pid,
                            'operation_id': offered['operation_id'], 'token': offered['token'],
                            'host_identity': offered['host_identity'],
                            'budget_seconds': offered['budget_seconds'],
                            'started_at_epoch': offered['started_at_epoch'],
                            'observed_at': time.time(),
                        })
                    elif (operation is not None and offered.get('token') == operation['token']
                          and offered.get('operation_id') == operation['operation_id']
                          and offered.get('host_identity') == operation['host_identity']):
                        if offered.get('finished') is True:
                            operation = None; operation_deadline = None
                        # The first observed deadline is immutable; rewriting
                        # budget/start or deleting the file cannot extend it.
            except (OSError, ValueError, KeyError, TypeError):
                stop_reason = stop_reason or 'OPERATION_BUDGET_UNOBSERVABLE'
        operation_cancel = directory / 'operation-cancel.json'
        if operation is not None and operation_cancel.exists():
            try:
                request = _read(operation_cancel)
                if (request.get('identity') == identity and request.get('pid') == process.pid
                        and request.get('operation_id') == operation['operation_id']
                        and request.get('token') == operation['token']
                        and request.get('host_identity') == operation['host_identity']):
                    stop_reason = stop_reason or 'OPERATION_CANCEL_REQUESTED'
            except (OSError, ValueError):
                pass
        if operation_deadline is not None and now >= operation_deadline:
            stop_reason = stop_reason or 'OPERATION_TIME_BUDGET_EXCEEDED'
        if scope is not None and now >= next_scope_check and stop_at is None:
            try:
                scope.check()
            except (OSError, ValueError, KeyError, TypeError) as error:
                stop_reason = stop_reason or 'NATIVE_SCOPE_BUDGET_EXCEEDED_OR_UNOBSERVABLE'
                observation_failed('native_scope.check', error, stop_reason)
            next_scope_check = now + .5
        if now >= next_disk_check and stop_at is None:
            try:
                if _disk_usage(log_budget) > MAX_LOG_BYTES:
                    stop_reason = 'LOG_BUDGET_EXCEEDED'
                if budget is not None:
                    observed_bytes = _disk_usage(budget)
                    if observed_bytes > budget['max_bytes']:
                        stop_reason = 'DISK_BUDGET_EXCEEDED'
            except (OSError, ValueError) as error:
                stop_reason = 'DISK_BUDGET_UNOBSERVABLE'
                observation_failed('disk_usage', error, stop_reason)
            next_disk_check = now + .05
        if cancelled:
            stop_reason = stop_reason or 'CANCEL_REQUESTED'
        if now >= work_deadline:
            stop_reason = stop_reason or 'TIME_BUDGET_EXCEEDED'
        if not start_written:
            try:
                if stop_reason is not None:
                    finish_start('SUPERVISOR_WRITER_COLLECTION_ABORTED:' + stop_reason)
                elif now >= collection_deadline:
                    finish_start('SUPERVISOR_WRITER_COLLECTION_TIMEOUT')
                else:
                    finish_start()
                if tree_stopped and not start_written:
                    finish_start('SUPERVISOR_WRITER_CHILD_EXITED_DURING_COLLECTION')
            except (OSError, ValueError) as error:
                stop_reason = stop_reason or 'SUPERVISOR_WRITER_START_WRITE_FAILED'
                observation_failed('writer_collection.started', error, stop_reason)
        if stop_reason is not None and stop_at is None:
            request_signal(signal.SIGTERM)
            stop_at = now
            next_kill_at = now + 2
        if tree_stopped:
            break
        if next_kill_at is not None and now >= next_kill_at:
            if os.name == 'nt':
                process.kill()
            else:
                request_signal(signal.SIGKILL)
            next_kill_at = now + 2
        time.sleep(.01)
    code = process.wait()
    if not start_written:
        return 2
    facts = {}
    if os.name == 'nt':
        if process.active_processes() != 0:
            return 2
        facts = {'platform': 'windows', 'process_birth': process.birth, 'job': process.job_facts,
                 'child_wait_observed': True, 'job_active_processes': 0}
    else:
        try:
            os.killpg(process.pid, 0)
            return 2
        except ProcessLookupError:
            pass
        except PermissionError:
            return 2
    supervisor_code = 2 if descendant_result_unobserved or (stop_reason is not None and code == 0) else 0
    execution_result = ('failed' if stop_reason is not None or code != 0 else
                        'unknown' if descendant_result_unobserved else 'succeeded')
    _signed_write(directory, {**facts, 'schema': SCHEMA, 'event': 'stopped', 'identity': identity,
                  'pid': process.pid, 'exit_code': code, 'observed_by': 'owned_child_wait',
                  'execution_protocol': 1, 'supervisor_exit_code': supervisor_code,
                  'execution_result': execution_result,
                  'descendant_result_unobserved': descendant_result_unobserved,
                  'stop_reason': stop_reason, 'observed_bytes': observed_bytes, 'operation': operation,
                  'observed_at': time.time(), 'started_sha256': hashlib.sha256(_canonical(start)).hexdigest()})
    if scope is not None:
        scope.finish(spec['native_scope_ticket'])
    return supervisor_code

if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--supervise': raise SystemExit(2)
    raise SystemExit(supervise(sys.argv[2]))
