"""Local graph-job evidence, not host/model certification or a security boundary.

Only the controller/worker imports this module. No evidence path or ownership
claim is accepted from an MCP caller. Full Access remains user-selected.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from dcc_task_runtime.canonical import canonical_json, canonical_sha256
from dcc_task_runtime.owned_process import execution_returncode

PROTOCOL = "bridge.graph_job_evidence/2.0"
MAX_JSON_BYTES = 2 * 1024 * 1024


def owned_file(root: Path, path: Path, *, required: bool = True) -> Path:
    """Reject symlinks below a trusted root while tolerating ancestor aliases."""
    root = root.resolve()
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        # macOS may expose a trusted ancestor through an OS alias such as
        # /var -> /private/var.  Resolve only candidate prefixes until the
        # already-resolved trusted root is found; never resolve untrusted
        # components below that boundary because doing so would hide links.
        relative = None
        for prefix in reversed(candidate.parents):
            try:
                if prefix.resolve() == root:
                    relative = candidate.relative_to(prefix)
                    break
            except (OSError, RuntimeError):
                # A looping/unreadable prefix is not evidence of ownership.
                continue
        if relative is None:
            raise ValueError("evidence path is outside the task root")
    current = root
    for part in relative.parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise ValueError("evidence path traverses a symlink or reparse point")
    candidate = root / relative
    if required and not candidate.is_file():
        raise ValueError("evidence file is missing")
    return candidate


def read_json(path: Path, *, root: Path) -> Any:
    path = owned_file(root, path)
    with path.open("rb") as handle:
        data = handle.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("evidence exceeds its size bound")
    return json.loads(data)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any], *, root: Path) -> None:
    path = owned_file(root, path, required=False)
    from dcc_task_runtime.platform_support import ensure_private_directory, open_private_file, atomic_replace, remove_owned_path
    ensure_private_directory(path.parent)
    path = owned_file(root, path, required=False)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("evidence exceeds its size bound")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    descriptor = open_private_file(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(temporary, path, owned_root=root)
        # Windows cannot open a directory this way. A failure after replace
        # elsewhere is propagated: its durability must not be assumed.
        if os.name != "nt":
            parent_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            remove_owned_path(temporary, owned_root=root)
        except FileNotFoundError:
            pass


def runtime_fingerprint(repo_root: Path) -> str:
    """Bind recovery to the Python runtime inputs and the Houdini plug-in.

    所有包内 Python 源码均参与摘要，包括官方分阶段构造及完成验证辅助模块。
    This detects changed on-disk inputs; it is not a loaded-code attestation
    and is not a replacement for task C's reproducible release snapshot.
    """
    paths = []
    for name in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
        directory = repo_root / "packages" / name / "src"
        if not directory.is_dir():
            raise ValueError("runtime package is missing")
        paths.extend(directory.rglob("*.py"))
    paths.append(repo_root / "plugins/houdini/_impl/houdini_bridge_addon.py")
    values = {path.relative_to(repo_root).as_posix(): file_sha256(owned_file(repo_root, path))
              for path in sorted(paths, key=lambda path: path.relative_to(repo_root).as_posix())}
    return canonical_sha256(values)


def process_identity(pid: int) -> dict[str, Any]:
    """Capture PID birth identity where available, never a reusable kill target.

    On other platforms PID absence is still a valid stopped observation;
    existence alone cannot certify identity and is reported as unknown.
    """
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid process id")
    if os.name == "nt":
        from dcc_task_runtime.platform_support import process_identity as native_identity
        return native_identity(pid)
    value: dict[str, Any] = {"pid": pid, "platform": sys.platform, "birth": None}
    if os.name == "posix":
        try:
            value.update(pgid=os.getpgid(pid), sid=os.getsid(pid))
        except OSError:
            pass
    if sys.platform.startswith("linux"):
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
            fields = text[text.rfind(")") + 2:].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            value.update(birth=boot + ":" + fields[19], state=fields[0])
        except (OSError, IndexError, ValueError):
            pass
    elif sys.platform == 'darwin':
        from dcc_task_runtime.platform_support import process_identity as native_identity
        observed = native_identity(pid)
        if (observed.get('pid') == pid and observed.get('platform') == 'posix'
                and isinstance(observed.get('birth'), str) and observed['birth']
                and observed.get('state') in {'alive', 'stopped'}):
            value.update(birth=observed['birth'], state=observed['state'])
    return value


def process_status(identity: Mapping[str, Any]) -> str:
    """Return stopped/alive/unknown; never signal a persisted PID."""
    if os.name == "nt":
        from dcc_task_runtime.platform_support import process_status as native_status
        return native_status(identity)
    pid = identity.get("pid")
    if type(pid) is not int or pid <= 0 or identity.get("platform") != sys.platform:
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "stopped"
    except (PermissionError, OSError):
        return "unknown"
    current = process_identity(pid)
    if identity.get("birth") and current.get("birth"):
        if current["birth"] != identity["birth"] or current.get("state") in {"Z", "X", "stopped"}:
            return "stopped"
        return "alive"
    return "unknown"


def owned_group_status(identity: Mapping[str, Any]) -> str:
    """Observe the original task-owned session/group without signalling it.

    Detached/new-session descendants are not contained by this cooperative
    protocol. Such host behavior still requires local lifecycle validation.
    """
    pid, group, session = identity.get("pid"), identity.get("pgid"), identity.get("sid")
    if type(pid) is not int or group != pid or session != pid:
        return "unknown"
    if sys.platform.startswith("linux"):
        try:
            entries = list(Path("/proc").iterdir())
        except OSError:
            return "unknown"
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                text = (entry / "stat").read_text()
                fields = text[text.rfind(")") + 2:].split()
                if int(fields[2]) == group and int(fields[3]) == session and fields[0] not in {"Z", "X"}:
                    return "alive"
            except FileNotFoundError:
                continue  # Process exited during this read-only observation.
            except (PermissionError, OSError, IndexError, ValueError):
                return "unknown"
        return "stopped"
    if os.name == "posix":
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return "stopped"
        except OSError:
            return "unknown"
    return "unknown"


def graph_recovery_snapshot(service, operation_id: str) -> dict[str, Any]:
    """Capture immutable committed inputs for a local recovery comparison."""
    row = dict(service._row(operation_id))
    paths = service._worker_paths(operation_id)
    from vfx_pipeline.graph_job_worker import DurableJournal
    with DurableJournal(paths['journal'])._connect() as database:
        entries = database.execute('SELECT operation_id,payload FROM entries ORDER BY operation_id').fetchall()
    if not entries or any(json.loads(payload).get('status') != 'COMPLETE' for _, payload in entries):
        raise ValueError('FORMAL_RECOVERY_COMMIT_INCOMPLETE')
    result = read_json(paths['result'], root=service.root)
    artifact = result.get('artifact') or {}
    hip = owned_file(service.root, Path(str(artifact.get('hip_path') or '')))
    return {'operation_id': operation_id, 'task_id': service._task_id_for_row(row),
            'attempt_token': row['process_token'], 'attempt_generation': row['attempt_generation'],
            'journal_sha256': canonical_sha256(entries),
            'files': {name: file_sha256(owned_file(service.root, paths[name]))
                      for name in ('inputs', 'proposal', 'graph', 'result', 'completion')},
            'hip_path': str(hip), 'hip_sha256': file_sha256(hip)}


def capture_prepared_graph_interruption(service, operation_id: str) -> dict[str, Any]:
    """Observe the actual case worker alive in its committed pre-exit window."""
    row = service._row(operation_id)
    handle = service._supervised_handle(row)
    paths = service._worker_paths(operation_id)
    active = read_json(paths['directory'] / 'formal-worker-active.json', root=service.root)
    identity = json.loads(row['process_identity_json'])
    if (service.status(operation_id)['state'] != 'RUNNING' or handle is None or handle.poll() is not None
            or process_status(identity) != 'alive' or active.get('window') != 'committed_graph_before_worker_exit'
            or active.get('process_identity', {}).get('pid') != handle.pid
            or active.get('process_identity', {}).get('birth') != identity.get('birth')
            or any(active.get(key) != expected for key, expected in (
                ('task_id', service._task_id_for_row(row)), ('operation_id', operation_id),
                ('attempt_token', row['process_token']), ('attempt_generation', row['attempt_generation'])))):
        raise ValueError('FORMAL_RECOVERY_ACTIVE_WORKER_UNPROVEN')
    controller = process_identity(os.getpid())
    controller.pop('state', None)
    return {'controller_identity': controller, 'worker_identity': identity,
            'state_before_interruption': 'RUNNING', 'observed_at': time.time(),
            'active_event_sha256': file_sha256(paths['directory'] / 'formal-worker-active.json'),
            'started_receipt_sha256': canonical_sha256(handle.started)}


def reconcile_prepared_graph_job(facade, *, graph_id: str, request_id: str,
                                 operation_id: str, committed: Mapping[str, Any],
                                 interruption: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the same prepared job using the existing supervisor and validators.

    An unknown stop remains an occupied slot. This interface never dispatches a
    new job or changes the owner-stopped contract, and does not certify a domain.
    """
    service = facade.jobs_service
    lower_request = facade.jobs._lower_trial_request(request_id)
    if facade.backend_kind != 'production' or service.lookup_trial(lower_request) != operation_id:
        raise ValueError('FORMAL_RECOVERY_OPERATION_MISMATCH')
    if committed.get('task_id') != facade.pipeline_task_id or committed.get('operation_id') != operation_id:
        raise ValueError('FORMAL_RECOVERY_OWNER_MISMATCH')
    controller = process_identity(os.getpid())
    controller.pop('state', None)
    previous_controller = interruption.get('controller_identity') or {}
    row = service._row(operation_id)
    handle = service._supervised_handle(row)
    paths = service._worker_paths(operation_id)
    active = read_json(paths['directory'] / 'formal-worker-active.json', root=service.root)
    worker_identity = interruption.get('worker_identity') or {}
    observed_at = interruption.get('observed_at')
    if (not controller.get('birth') or not previous_controller.get('birth')
            or controller == previous_controller or process_status(previous_controller) != 'stopped'
            or interruption.get('state_before_interruption') != 'RUNNING'
            or worker_identity != json.loads(row['process_identity_json'])
            or handle is None or active.get('process_identity', {}).get('pid') != handle.pid
            or active.get('process_identity', {}).get('birth') != worker_identity.get('birth')
            or active.get('window') != 'committed_graph_before_worker_exit'
            or active.get('task_id') != facade.pipeline_task_id or active.get('operation_id') != operation_id
            or active.get('attempt_token') != row['process_token']
            or active.get('attempt_generation') != row['attempt_generation']
            or file_sha256(paths['directory'] / 'formal-worker-active.json') != interruption.get('active_event_sha256')
            or canonical_sha256(handle.started) != interruption.get('started_receipt_sha256')
            or type(observed_at) not in (int, float) or not 0 < observed_at <= time.time()
            or observed_at < handle.started['observed_at']):
        raise ValueError('FORMAL_RECOVERY_INTERRUPTION_IDENTITY_UNPROVEN')
    if graph_recovery_snapshot(service, operation_id) != dict(committed):
        raise ValueError('FORMAL_RECOVERY_COMMIT_CHANGED')
    status = service.reconcile(operation_id)
    if not status.get('stop_confirmed'):
        slot = service.scheduler.snapshot()
        if not slot or not slot.get('active') or slot.get('operation_id') != operation_id:
            raise ValueError('FORMAL_RECOVERY_UNKNOWN_STOP_SLOT_LOST')
        return {'tested': False, 'blocker': 'FORMAL_RECOVERY_STOP_UNCONFIRMED',
                'operation_id': operation_id, 'task_id': facade.pipeline_task_id, 'slot_retained': True,
                'operation': status}
    if status.get('state') != 'SUCCEEDED':
        raise ValueError('FORMAL_RECOVERY_COMPLETION_UNVERIFIED')
    row = service._row(operation_id)
    handle = service._supervised_handle(row)
    stop = handle.receipt() if handle is not None else None
    if (not stop or stop.get('event') != 'stopped' or stop.get('observed_by') != 'owned_child_wait'
            or stop.get('pid') != row['pid']
            or type(stop.get('exit_code')) is not int or execution_returncode(stop) == 0
            or stop.get('observed_at', 0) <= observed_at
            or (os.name == 'nt' and (stop.get('child_wait_observed') is not True
                                    or stop.get('job_active_processes') != 0))):
        raise ValueError('FORMAL_RECOVERY_SUPERVISOR_STOP_MISSING')
    trial = facade.graph_trial(graph_id, request_id)
    if trial.get('operation_id') != operation_id or trial.get('state') != 'SUCCEEDED':
        raise ValueError('FORMAL_RECOVERY_REQUEST_REPLAY_CHANGED')
    if graph_recovery_snapshot(service, operation_id) != dict(committed):
        raise ValueError('FORMAL_RECOVERY_COMMITTED_WORK_REPLAYED')
    return {'tested': True, 'scope': 'prepared_graph_commit_recovery',
            'domain_lifecycle_verified': False, 'operation_id': operation_id,
            'task_id': facade.pipeline_task_id, 'committed': dict(committed),
            'interruption': dict(interruption), 'recovered_controller_identity': controller,
            'stop_receipt': stop, 'trial': trial, 'slot_released': not service.scheduler.snapshot().get('active', False)}
