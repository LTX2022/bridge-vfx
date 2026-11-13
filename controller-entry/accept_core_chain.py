# -*- coding: utf-8 -*-
"""Controller verification entry for the core execution chain (默认不执行).

Run by the controller / independent reviewer against a real H21.0.631 host:

    python3 accept_core_chain.py --work-root <new dir> --addon-root <add-on root> \
        [--houdini-bin path] [--budget 110] [--ready-timeout 120]

Exit code 0 only when every gate passed; any failure, timeout, unconfirmed
cancel or missing evidence exits non-zero with the partial results preserved
on disk (accept-results.json). Hosts are always reclaimed in a finally block;
an unreclaimable host is reported as UNRECLAIMED with its pid.

The client package bundled next to this script (client/) is the only import
source: --client-root can point elsewhere, but the effective import paths and
sha256 of every key module are recorded in the results.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent

PACK = "vellum_softbody_grains_v1"
ARGS = None
CLIENT_ROOT = None
HoudiniClient = None
BridgeError = None
th = None
RESULTS: dict = {"gates": {}, "module_sources": {}, "errors": []}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", required=True)
    ap.add_argument("--addon-root", required=True)
    ap.add_argument("--houdini-bin", default=None)
    ap.add_argument("--budget", type=float, default=120.0,
                    help="per-operation budget in seconds (acceptance constant: 120)")
    ap.add_argument("--ready-timeout", type=float, default=120.0)
    ap.add_argument("--watchdog-timeout", type=float, default=135.0,
                    help="external watchdog ceiling per heavy job in seconds (acceptance constant: 135); "
                         "the CONTROLLER must enforce this outside the host process")
    ap.add_argument("--frames", default="2,4,6,8,10,12",
                    help="comma-separated frame list; acceptance allows at most 12 specified frames")
    ap.add_argument("--client-root", default=str(HERE / "client"))
    return ap.parse_args(argv)


def configure_normal_runtime(args: argparse.Namespace) -> bool:
    """Load the normal acceptance client only after normal CLI parsing.

    The watchdog child deliberately does not enter this path: it has no
    requirement for work-root, add-on-root, Houdini, or a controller client.
    """
    global ARGS, CLIENT_ROOT, HoudiniClient, BridgeError, th, RESULTS
    ARGS = args
    CLIENT_ROOT = Path(args.client_root).expanduser().resolve()
    if not (CLIENT_ROOT / "houdini_bridge" / "client.py").is_file():
        print(json.dumps({"error": "CLIENT_ROOT_INVALID", "client_root": str(CLIENT_ROOT)}))
        return False
    if str(CLIENT_ROOT) not in sys.path:
        sys.path.insert(0, str(CLIENT_ROOT))
    from houdini_bridge.client import HoudiniClient as _HoudiniClient, BridgeError as _BridgeError
    from houdini_bridge import task_host as _task_host
    HoudiniClient, BridgeError, th = _HoudiniClient, _BridgeError, _task_host
    RESULTS = {"gates": {}, "module_sources": {}, "errors": []}
    return True


def module_source_record() -> dict:
    record = {}
    for name, module in sorted(sys.modules.items()):
        if name in ("houdini_bridge", "houdini_bridge.client", "houdini_bridge.task_host",
                    "houdini_bridge.registry", "dcc_task_runtime.execution_lock"):
            path = getattr(module, "__file__", None)
            if path and Path(path).is_file():
                record[name] = {"path": str(Path(path).resolve()),
                                "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    return record


def manifest_state_path(task_id: str) -> Path:
    """Deterministic task manifest path, mirroring the add-on exactly.

    Kept in lockstep with ``houdini_bridge_addon._fx_state_path`` (digest of
    the FULL task id, under ``<state root>/fx_tasks``) by
    ``tests/unit/test_acceptance_entry_contract.py``.
    """
    override = os.environ.get("HOUDINI_BRIDGE_STATE_DIR")
    if override:
        state_dir = Path(override).expanduser() / "instances"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        state_dir = root / "HoudiniBridge" / "instances"
    elif sys.platform == "darwin":
        state_dir = Path.home() / "Library" / "Application Support" / "HoudiniBridge" / "instances"
    else:
        state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "houdini-bridge" / "instances"
    digest = hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:16]
    return state_dir.parent / "fx_tasks" / ("fx_%s.json" % digest)


def client_for(workdir: Path):
    receipt = json.loads((workdir / th.WORKDIR_READY).read_text())
    return HoudiniClient(int(receipt["port"]), timeout_seconds=90), receipt


def wait_terminal(c: HoudiniClient, task: str, request_id: str, timeout: float):
    t0 = time.time()
    rec = {"state": "UNKNOWN"}
    while time.time() - t0 < timeout:
        rec = c.call("operation.status", {"task_id": task, "operation_id": request_id})["operation"]
        if rec.get("state") not in ("QUEUED", "RUNNING", "CANCEL_PENDING"):
            return rec, False
        time.sleep(0.3)
    return rec, True  # timed out with the record still active


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        return _watchdog_runtime()[0].pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _process_identity(pid) -> str | None:
    """Return an OS process-start token, or None when it cannot be proven."""
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == 'nt':
        observed = _watchdog_runtime()[0].process_identity(pid_int)
        birth = observed.get('birth')
        return 'windows-birth:' + birth if isinstance(birth, str) and birth else None
    proc_stat = Path("/proc") / str(pid_int) / "stat"
    try:
        fields = proc_stat.read_text(encoding="utf-8").split()
        if len(fields) > 21:
            return "proc-start:" + str(fields[21])
    except (OSError, ValueError):
        pass
    try:
        output = subprocess.check_output(
            ["ps", "-p", str(pid_int), "-o", "lstart="],
            text=True, stderr=subprocess.DEVNULL, timeout=2)
        value = output.strip()
        if value:
            return "ps-start:" + value
    except (OSError, subprocess.SubprocessError):
        pass
    # macOS sandboxed controller processes may not be allowed to query ``ps``.
    # A process-group/session tuple is still an additional ownership token;
    # it is never used as a replacement for the task nonce and host generation.
    try:
        return "session:%s:%s" % (os.getpgid(pid_int), os.getsid(pid_int))
    except (OSError, AttributeError, ProcessLookupError, PermissionError):
        pass
    return None


def _watchdog_runtime():
    root = Path(CLIENT_ROOT or HERE / 'client').resolve() / 'dcc_task_runtime'
    name = '_bridge_watchdog_runtime_' + hashlib.sha256(str(root).encode()).hexdigest()
    package = types.ModuleType(name)
    package.__package__ = name
    package.__path__ = [str(root)]
    sys.modules.setdefault(name, package)
    return (importlib.import_module(name + '.platform_support'),
            importlib.import_module(name + '.owned_process'))


def _windows_supervisor(workdir, contract):
    raw = contract.get('owned_supervisor_dir')
    identity = contract.get('owned_supervisor_identity')
    if not isinstance(raw, str) or not isinstance(identity, dict):
        raise ValueError('OWNED_SUPERVISOR_REQUIRED')
    directory = Path(raw)
    if not directory.is_absolute() or directory.is_symlink() or not directory.resolve().is_relative_to(workdir):
        raise ValueError('OWNED_SUPERVISOR_OUTSIDE_WORKDIR')
    handle = _watchdog_runtime()[1].OwnedProcessHandle(directory, identity)
    if handle.pid != int(contract['pid']):
        raise ValueError('OWNED_SUPERVISOR_PID_MISMATCH')
    if 'windows-birth:' + handle.started['process_birth'] != contract['process_identity']:
        raise ValueError('OWNED_SUPERVISOR_BIRTH_MISMATCH')
    for key in ('task_id', 'launch_nonce', 'process_generation'):
        if key in identity and str(identity[key]) != str(contract[key]):
            raise ValueError('OWNED_SUPERVISOR_IDENTITY_MISMATCH')
    return handle


def _read_json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _watchdog_child(work_dir: str, timeout: float, grace: float = 10.0, *,
                    expected: dict | None = None, events_file: str | None = None,
                    complete_file: str | None = None, operation_file: str | None = None,
                    shutdown_file: str | None = None, operation_id: str | None = None,
                    messages_dir: str | None = None, acks_dir: str | None = None) -> int:
    """Run the real independent watchdog protocol.

    The child can only act after a controller-written identity contract
    matches the current host receipt *and* the OS start token for that pid.
    With the message/ack directories the timeout is armed per heavy operation
    only after the child has durably acknowledged a sequenced start message.
    The parent must likewise receive a durable completion acknowledgement
    before it can issue another side effect.  ``operation_file`` and
    ``complete_file`` remain accepted for old direct probes, but the shipped
    parent uses the append-only message protocol.
    """
    workdir = Path(work_dir).expanduser().resolve()
    ready = workdir / "host.ready"
    stop_file = workdir / "host.stop"
    events = Path(events_file).expanduser().resolve() if events_file else workdir / "watchdog-events.json"
    complete = Path(complete_file).expanduser().resolve() if complete_file else None
    operation_path = Path(operation_file).expanduser().resolve() if operation_file else None
    shutdown_path = Path(shutdown_file).expanduser().resolve() if shutdown_file else None
    messages = Path(messages_dir).expanduser().resolve() if messages_dir else None
    acknowledgements = Path(acks_dir).expanduser().resolve() if acks_dir else None
    record = {"work_dir": str(workdir), "timeout": float(timeout), "grace": float(grace),
              "operation_id": operation_id, "events": []}
    supervised = None

    def host_stopped():
        if os.name == 'nt':
            return supervised is not None and supervised.poll() is not None
        return not _pid_alive(expected_pid)

    def persist() -> None:
        _write_json_atomic(events, record)

    def finish(code: int, action: str, **details) -> int:
        event = {"at": time.time(), "action": action}
        event.update(details)
        record["events"].append(event)
        record["exit"] = int(code)
        persist()
        return int(code)

    try:
        if float(timeout) <= 0 or float(grace) < 0:
            return finish(2, "invalid_watchdog_budget")
        if (messages is None) != (acknowledgements is None):
            return finish(2, "message_protocol_invalid", reason="messages_dir and acks_dir must be supplied together")
        contract = dict(expected or {})
        if not contract:
            contract_path = workdir / "watchdog-contract.json"
            loaded = _read_json_file(contract_path)
            if isinstance(loaded, dict):
                contract = loaded
        required = ("task_id", "pid", "launch_nonce", "process_generation", "process_identity")
        missing = [key for key in required if not str(contract.get(key) or "")]
        if missing:
            return finish(2, "identity_contract_missing", missing=missing)
        expected_pid = int(contract.get("pid") or 0)
        if expected_pid <= 0:
            return finish(2, "identity_contract_invalid", field="pid")
        deadline = time.monotonic() + float(timeout)
        receipt = None
        while time.monotonic() < deadline:
            receipt = _read_json_file(ready)
            if isinstance(receipt, dict):
                mismatches = {
                    key: {"expected": contract.get(key), "actual": receipt.get(key)}
                    for key in ("task_id", "pid", "launch_nonce", "process_generation")
                    if str(receipt.get(key)) != str(contract.get(key))
                }
                if mismatches:
                    return finish(4, "identity_mismatch", mismatches=mismatches)
                if int(receipt.get("pid") or 0) != expected_pid:
                    return finish(4, "identity_mismatch", field="pid")
                if os.name == 'nt':
                    try:
                        supervised = _windows_supervisor(workdir, contract)
                    except (OSError, ValueError, KeyError) as exc:
                        field = 'process_identity' if str(exc) == 'OWNED_SUPERVISOR_BIRTH_MISMATCH' else 'owned_supervisor'
                        return finish(4, 'identity_mismatch', field=field, stop_confirmed=False,
                                      error=str(exc))
                    if host_stopped():
                        return finish(0, 'host_exited_before_deadline', confirmed_identity=True)
                if _pid_alive(expected_pid):
                    current_identity = _process_identity(expected_pid)
                    if current_identity != str(contract.get("process_identity")):
                        return finish(4, "identity_mismatch", field="process_identity",
                                      expected=contract.get("process_identity"), actual=current_identity)
                    record["watched_pid"] = expected_pid
                    record["identity"] = {key: contract.get(key) for key in required}
                    record["events"].append({"at": time.time(), "action": "watching",
                                              "pid": expected_pid, "task_id": contract.get("task_id"),
                                              "process_generation": contract.get("process_generation")})
                    persist()
                    break
                # A matching receipt whose owned process already ended is a
                # clean observation; no PID is ever signalled in this branch.
                if os.name == 'nt':
                    return finish(4, 'stop_unconfirmed', stop_confirmed=False)
                return finish(0, "host_exited_before_deadline", confirmed_identity=True)
            time.sleep(0.05)
        else:
            return finish(2, "no_ready_receipt")

        message_mode = messages is not None
        if message_mode:
            messages.mkdir(parents=True, exist_ok=True)
            acknowledgements.mkdir(parents=True, exist_ok=True)
            record["protocol"] = {"version": "watchdog-v2",
                                   "messages_dir": str(messages),
                                   "acks_dir": str(acknowledgements)}

        direct_mode = not message_mode and operation_path is None
        legacy_operation_mode = not message_mode and operation_path is not None
        active_operation = None
        active_deadline = None
        active_start_sequence = None
        completed_operations = set()
        next_sequence = 1

        def _acknowledge(message: dict) -> None:
            ack = {
                "protocol_version": "watchdog-v2",
                "seq": int(message["seq"]),
                "kind": str(message["kind"]),
                "operation_id": str(message["operation_id"]),
                "status": "accepted",
                "task_id": str(contract["task_id"]),
                "pid": int(contract["pid"]),
                "launch_nonce": str(contract["launch_nonce"]),
                "process_generation": str(contract["process_generation"]),
                "process_identity": str(contract["process_identity"]),
                "at": time.time(),
            }
            _write_json_atomic(acknowledgements / ("%020d.json" % int(message["seq"])), ack)

        def _process_messages():
            nonlocal active_operation, active_deadline, active_start_sequence, next_sequence
            if not message_mode:
                return None
            expected_path = messages / ("%020d.json" % next_sequence)
            if not expected_path.is_file():
                for candidate in messages.glob("*.json"):
                    try:
                        candidate_seq = int(candidate.stem)
                    except ValueError:
                        continue
                    if candidate_seq > next_sequence:
                        return finish(4, "protocol_sequence_gap", expected_seq=next_sequence,
                                      actual_seq=candidate_seq)
                return None
            message = _read_json_file(expected_path)
            if not isinstance(message, dict):
                return finish(4, "protocol_message_invalid", seq=next_sequence)
            try:
                message_seq = int(message.get("seq"))
            except (TypeError, ValueError):
                return finish(4, "protocol_message_invalid", seq=next_sequence, field="seq")
            if message_seq != next_sequence:
                return finish(4, "protocol_sequence_mismatch", expected_seq=next_sequence,
                              actual_seq=message_seq)
            for key in ("task_id", "pid", "launch_nonce", "process_generation", "process_identity"):
                if str(message.get(key)) != str(contract.get(key)):
                    return finish(4, "protocol_identity_mismatch", seq=message_seq, field=key)
            kind = str(message.get("kind") or "")
            operation = str(message.get("operation_id") or "")
            if kind not in {"start", "complete"} or not operation:
                return finish(4, "protocol_message_invalid", seq=message_seq,
                              kind=kind, operation_id=operation)
            if kind == "start":
                if active_operation is not None:
                    return finish(4, "protocol_start_before_complete", seq=message_seq,
                                  active_operation=active_operation, operation_id=operation)
                if operation in completed_operations:
                    return finish(4, "protocol_duplicate_operation", seq=message_seq,
                                  operation_id=operation)
                active_operation = operation
                active_start_sequence = message_seq
                active_deadline = time.monotonic() + float(timeout)
                record["operation_id"] = operation
                record["events"].append({"at": time.time(), "action": "operation_started",
                                          "seq": message_seq, "operation_id": operation,
                                          "task_id": contract["task_id"],
                                          "process_generation": contract["process_generation"]})
                persist()
                _acknowledge(message)
            else:
                if active_operation != operation:
                    return finish(4, "protocol_complete_mismatch", seq=message_seq,
                                  active_operation=active_operation, operation_id=operation)
                completed_operations.add(operation)
                record["events"].append({"at": time.time(), "action": "operation_completed",
                                          "seq": message_seq, "start_seq": active_start_sequence,
                                          "operation_id": operation,
                                          "task_id": contract["task_id"],
                                          "process_generation": contract["process_generation"]})
                persist()
                _acknowledge(message)
                active_operation = None
                active_start_sequence = None
                active_deadline = None
            next_sequence += 1
            record["next_sequence"] = next_sequence
            persist()
            return None

        if direct_mode:
            # Direct CLI mode is intentionally a one-operation watchdog.  The
            # controller mode supplies the sequenced message protocol and arms
            # each operation explicitly, so host startup itself never consumes
            # the operation budget.
            active_operation = str(operation_id or "watchdog-direct")
            active_deadline = time.monotonic() + float(timeout)
            record["events"].append({"at": time.time(), "action": "operation_started",
                                      "operation_id": active_operation})
            persist()
        while True:
            protocol_result = _process_messages()
            if protocol_result is not None:
                return protocol_result
            if shutdown_path is not None and shutdown_path.is_file():
                if active_operation is not None:
                    return finish(4, "shutdown_with_active_operation", operation_id=active_operation)
                return finish(0, "watchdog_shutdown")
            if legacy_operation_mode:
                current = _read_json_file(operation_path)
                current_id = str(current.get("operation_id") or "") if isinstance(current, dict) else ""
                if current_id and current_id not in completed_operations and current_id != active_operation:
                    active_operation = current_id
                    active_deadline = time.monotonic() + float(timeout)
                    record["operation_id"] = current_id
                    record["events"].append({"at": time.time(), "action": "operation_started",
                                              "operation_id": current_id})
                    persist()
            if complete is not None and active_operation:
                done = _read_json_file(complete)
                done_id = str(done.get("operation_id") or "") if isinstance(done, dict) else ""
                if done_id == active_operation:
                    completed_operations.add(active_operation)
                    record["events"].append({"at": time.time(), "action": "operation_completed",
                                              "operation_id": active_operation})
                    persist()
                    active_operation = None
                    active_deadline = None
            if host_stopped():
                if active_operation and not direct_mode:
                    return finish(4, "host_exited_during_operation", operation_id=active_operation)
                return finish(0, "host_exited_before_deadline", confirmed_identity=True)
            current_identity = _process_identity(expected_pid)
            if current_identity is None:
                if os.name == 'nt':
                    return finish(4, 'stop_unconfirmed', stop_confirmed=False, operation_id=active_operation)
                # On macOS a just-exited sibling may remain observable by
                # kill(pid, 0) for a short zombie window while its start-token
                # query is already gone.  Treat that as an observed exit; an
                # active operation remains UNKNOWN and therefore fails.
                if direct_mode:
                    return finish(0, "host_exited_before_deadline", confirmed_identity=True)
                if active_operation:
                    return finish(4, "host_exited_during_operation", operation_id=active_operation)
                return finish(0, "host_exited_before_deadline", confirmed_identity=True)
            if current_identity != str(contract.get("process_identity")):
                return finish(4, "identity_lost", expected=contract.get("process_identity"), actual=current_identity)
            if active_operation is None:
                time.sleep(0.05)
                continue
            if active_deadline is not None and time.monotonic() >= active_deadline:
                record["events"].append({"at": time.time(), "action": "timeout_stop_file",
                                          "operation_id": active_operation})
                persist()
                try:
                    stop_file.write_text("stop", encoding="utf-8")
                    record["events"].append({"at": time.time(), "action": "stop_file_written",
                                              "operation_id": active_operation})
                    persist()
                except OSError as exc:
                    return finish(4, "stop_file_failed", error=str(exc), operation_id=active_operation)
                stop_deadline = time.monotonic() + float(grace)
                while time.monotonic() < stop_deadline:
                    if host_stopped():
                        return finish(3, "stopped_after_stop_file", stop_confirmed=True,
                                      operation_id=active_operation)
                    current_identity = _process_identity(expected_pid)
                    if current_identity is not None and current_identity != str(contract.get("process_identity")):
                        return finish(4, "identity_lost", stop_confirmed=False,
                                      expected=contract.get("process_identity"),
                                      actual=current_identity, operation_id=active_operation)
                    time.sleep(0.05)
                if host_stopped():
                    return finish(3, "stopped_after_stop_file", stop_confirmed=True,
                                  operation_id=active_operation)
                current_identity = _process_identity(expected_pid)
                if current_identity != str(contract.get("process_identity")):
                    return finish(4, "identity_lost", stop_confirmed=False,
                                  expected=contract.get("process_identity"),
                                  actual=current_identity, operation_id=active_operation)
                record["events"].append({"at": time.time(), "action": "escalate_terminate_owned_job" if os.name == 'nt' else "escalate_terminate_owned_pid",
                                          "operation_id": active_operation})
                persist()
                try:
                    if os.name == 'nt':
                        supervised.terminate()
                    else:
                        os.kill(expected_pid, 15)
                except OSError as exc:
                    return finish(4, "terminate_failed", error=str(exc), operation_id=active_operation)
                terminate_deadline = time.monotonic() + max(1.0, min(10.0, float(grace) or 1.0))
                while time.monotonic() < terminate_deadline:
                    if host_stopped():
                        return finish(3, "stop_confirmed_after_supervisor" if os.name == 'nt' else "stop_confirmed_after_sigterm", stop_confirmed=True,
                                      operation_id=active_operation)
                    current_identity = _process_identity(expected_pid)
                    if current_identity is not None and current_identity != str(contract.get("process_identity")):
                        return finish(4, "identity_lost", stop_confirmed=False,
                                      expected=contract.get("process_identity"),
                                      actual=current_identity, operation_id=active_operation)
                    time.sleep(0.05)
                return finish(4, "stop_unconfirmed", stop_confirmed=False,
                              operation_id=active_operation)
            time.sleep(0.05)
    except BaseException as exc:  # watchdog failure is a recorded acceptance failure
        try:
            record["events"].append({"at": time.time(), "action": "watchdog_exception",
                                      "error": repr(exc)[:400]})
            record["exit"] = 70
            persist()
        except BaseException as persist_exc:
            sys.stderr.write(json.dumps({
                "error": "watchdog_exception_evidence_unavailable",
                "exception": repr(exc)[:400],
                "evidence_error": repr(persist_exc)[:400],
            }, ensure_ascii=False) + "\n")
            sys.stderr.flush()
        return 70


def _parse_watchdog_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="accept_core_chain.py --watchdog-child")
    parser.add_argument("--watchdog-child", action="store_true")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--grace", type=float, default=10.0)
    parser.add_argument("--identity-file", default=None)
    parser.add_argument("--events-file", default=None)
    parser.add_argument("--complete-file", default=None)
    parser.add_argument("--operation-file", default=None)
    parser.add_argument("--shutdown-file", default=None)
    parser.add_argument("--operation-id", default=None)
    parser.add_argument("--messages-dir", default=None)
    parser.add_argument("--acks-dir", default=None)
    parser.add_argument("--expected-task-id", default=None)
    parser.add_argument("--expected-pid", type=int, default=None)
    parser.add_argument("--expected-launch-nonce", default=None)
    parser.add_argument("--expected-process-generation", default=None)
    parser.add_argument("--expected-process-identity", default=None)
    return parser.parse_args(argv)


def _run_watchdog_cli(argv=None) -> int:
    args = _parse_watchdog_args(argv)
    expected = _read_json_file(Path(args.identity_file)) if args.identity_file else None
    if not isinstance(expected, dict):
        expected = {}
    explicit = {
        "task_id": args.expected_task_id,
        "pid": args.expected_pid,
        "launch_nonce": args.expected_launch_nonce,
        "process_generation": args.expected_process_generation,
        "process_identity": args.expected_process_identity,
    }
    expected.update({key: value for key, value in explicit.items() if value is not None})
    return _watchdog_child(args.work_dir, args.timeout, args.grace, expected=expected,
                           events_file=args.events_file, complete_file=args.complete_file,
                           operation_file=args.operation_file, shutdown_file=args.shutdown_file,
                           operation_id=args.operation_id, messages_dir=args.messages_dir,
                           acks_dir=args.acks_dir)


def _watchdog_contract(work_dir: Path, receipt: dict) -> dict | None:
    """Build an identity contract only for a host owned by this controller."""
    if th is None:
        return None
    try:
        pid = int(receipt.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    process = getattr(th, "_ACTIVE_CHILDREN", {}).get(pid)
    if process is None or process.poll() is not None:
        return None
    process_identity = _process_identity(pid)
    if not process_identity:
        return None
    required = {"task_id", "pid", "launch_nonce", "process_generation"}
    if any(not str(receipt.get(key) or "") for key in required):
        return None
    contract = {key: receipt.get(key) for key in required} | {"process_identity": process_identity}
    if os.name == 'nt':
        directory = getattr(process, 'directory', None)
        identity = getattr(process, 'identity', None)
        if directory is None or not isinstance(identity, dict):
            return None
        contract.update(owned_supervisor_dir=str(directory), owned_supervisor_identity=dict(identity))
        try:
            _windows_supervisor(work_dir, contract)
        except (OSError, ValueError, KeyError):
            return None
    return contract


def start_watchdog(work_dir: Path, timeout: float, receipt: dict | None = None,
                   operation_mode: bool = True):
    """Spawn the real watchdog child and retain all stdout/stderr evidence."""
    work_dir = Path(work_dir).expanduser().resolve()
    receipt = receipt or _read_json_file(work_dir / "host.ready")
    contract = _watchdog_contract(work_dir, receipt or {})
    if contract is None:
        raise RuntimeError("watchdog cannot prove controller-owned host identity")
    suffix = "" if operation_mode else "-direct"
    contract_path = work_dir / ("watchdog-contract%s.json" % suffix)
    events_path = work_dir / ("watchdog-events%s.json" % suffix)
    complete_path = work_dir / ("watchdog-complete%s.json" % suffix)
    operation_path = work_dir / ("watchdog-operation%s.json" % suffix)
    shutdown_path = work_dir / ("watchdog-shutdown%s" % suffix)
    messages_path = work_dir / ("watchdog-messages%s" % suffix)
    acknowledgements_path = work_dir / ("watchdog-acks%s" % suffix)
    stdout_path = work_dir / ("watchdog%s.stdout.log" % suffix)
    stderr_path = work_dir / ("watchdog%s.stderr.log" % suffix)
    for path in (contract_path, events_path, complete_path, operation_path, shutdown_path):
        path.unlink(missing_ok=True)
    for directory in (messages_path, acknowledgements_path):
        directory.mkdir(parents=True, exist_ok=True)
        for child in directory.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
    _write_json_atomic(contract_path, contract)
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            [getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', str(Path(__file__).resolve()), "--watchdog-child",
             "--work-dir", str(work_dir), "--timeout", str(float(timeout)),
             "--grace", str(max(0.0, min(float(timeout), 10.0))),
             "--identity-file", str(contract_path), "--events-file", str(events_path),
             *( ["--shutdown-file", str(shutdown_path), "--messages-dir", str(messages_path),
                  "--acks-dir", str(acknowledgements_path)] if operation_mode else [] )],
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    proc._bridge_watchdog = {"contract": contract, "contract_path": contract_path,
                             "events": events_path, "complete": complete_path,
                             "operation": operation_path, "shutdown": shutdown_path,
                             "messages": messages_path, "acks": acknowledgements_path,
                             "next_sequence": 1, "active_operation": None,
                             "ack_timeout": max(5.0, min(60.0, float(timeout))),
                             "stdout": stdout_path, "stderr": stderr_path}
    return proc


def wait_watchdog_ready(proc, timeout: float = 10.0) -> bool:
    meta = getattr(proc, "_bridge_watchdog", {})
    events = meta.get("events")
    expected = meta.get("contract") or {}
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if events and events.is_file():
            record = _read_json_file(events)
            if isinstance(record, dict):
                for event in record.get("events") or []:
                    if event.get("action") == "watching":
                        identity = record.get("identity") or {}
                        required = ("task_id", "pid", "launch_nonce", "process_generation",
                                    "process_identity")
                        if all(str(identity.get(key)) == str(expected.get(key)) for key in required):
                            return True
                        return False
        if proc.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _await_watchdog_ack(proc, message: dict) -> dict:
    meta = getattr(proc, "_bridge_watchdog", {})
    acknowledgements = meta.get("acks")
    if acknowledgements is None:
        raise RuntimeError("watchdog has no sequenced acknowledgement channel")
    ack_path = Path(acknowledgements) / ("%020d.json" % int(message["seq"]))
    deadline = time.monotonic() + float(meta.get("ack_timeout") or 10.0)
    while time.monotonic() < deadline:
        ack = _read_json_file(ack_path)
        if isinstance(ack, dict):
            for key in ("seq", "kind", "operation_id", "task_id", "pid",
                        "launch_nonce", "process_generation", "process_identity"):
                if str(ack.get(key)) != str(message.get(key)):
                    raise RuntimeError("watchdog acknowledgement identity mismatch for {}".format(message["operation_id"]))
            if ack.get("status") != "accepted":
                raise RuntimeError("watchdog rejected {} for {}".format(message["kind"], message["operation_id"]))
            return ack
        if proc.poll() is not None:
            raise RuntimeError("watchdog exited before {} acknowledgement (rc={})".format(message["kind"], proc.returncode))
        time.sleep(0.01)
    raise RuntimeError("watchdog did not acknowledge {} for {}".format(message["kind"], message["operation_id"]))


def _send_watchdog_message(proc, kind: str, operation_id: str) -> dict:
    meta = getattr(proc, "_bridge_watchdog", {})
    if proc.poll() is not None:
        raise RuntimeError("watchdog exited before operation message (rc={})".format(proc.returncode))
    operation_id = str(operation_id)
    if kind == "start":
        if meta.get("active_operation") is not None:
            raise RuntimeError("previous watchdog operation was not acknowledged complete")
        if operation_id in list(meta.get("expected_operations") or []):
            raise RuntimeError("watchdog operation id was reused: {}".format(operation_id))
    elif kind == "complete":
        if str(meta.get("active_operation") or "") != operation_id:
            raise RuntimeError("watchdog completion does not match the acknowledged active operation")
    else:
        raise RuntimeError("unknown watchdog message kind: {}".format(kind))
    seq = int(meta.get("next_sequence") or 1)
    contract = meta.get("contract") or {}
    message = {"protocol_version": "watchdog-v2", "seq": seq, "kind": kind,
               "operation_id": operation_id, "at": time.time()}
    message.update({key: contract.get(key) for key in
                    ("task_id", "pid", "launch_nonce", "process_generation", "process_identity")})
    _write_json_atomic(Path(meta["messages"]) / ("%020d.json" % seq), message)
    _await_watchdog_ack(proc, message)
    meta["next_sequence"] = seq + 1
    if kind == "start":
        meta.setdefault("expected_operations", []).append(operation_id)
        meta["active_operation"] = operation_id
    else:
        meta["active_operation"] = None
    return message


def arm_watchdog(proc, operation_id: str) -> None:
    _send_watchdog_message(proc, "start", operation_id)


def complete_watchdog(proc, operation_id: str) -> None:
    _send_watchdog_message(proc, "complete", operation_id)


def shutdown_watchdog(proc) -> None:
    meta = getattr(proc, "_bridge_watchdog", {})
    if meta.get("active_operation") is not None:
        raise RuntimeError("cannot shut down watchdog before operation completion acknowledgement")
    if meta.get("shutdown"):
        Path(meta["shutdown"]).write_text("shutdown", encoding="utf-8")


def read_watchdog_events(work_dir: Path, events_file: Path | None = None) -> dict:
    events = Path(events_file) if events_file is not None else Path(work_dir) / "watchdog-events.json"
    payload = _read_json_file(events)
    if not isinstance(payload, dict):
        return {"present": False, "events_file": str(events)}
    if events.name == "watchdog-events.json":
        stderr = events.with_name("watchdog.stderr.log")
    else:
        stderr = events.with_name(events.name.replace("-events", ".stderr").replace(".json", ".log"))
    return {"present": True, **payload,
            "events_file": str(events),
            "stderr": stderr.read_text(encoding="utf-8", errors="replace") if stderr.is_file() else ""}


def watchdog_process_evidence(proc) -> dict:
    meta = getattr(proc, "_bridge_watchdog", {})
    evidence = read_watchdog_events(Path(meta.get("events").parent) if meta.get("events") else Path("."),
                                    meta.get("events"))
    evidence.update({
        "returncode": proc.poll(),
        "expected_identity": dict(meta.get("contract") or {}),
        "stdout_file": str(meta.get("stdout")) if meta.get("stdout") else None,
        "stderr_file": str(meta.get("stderr")) if meta.get("stderr") else None,
        "stdout": meta["stdout"].read_text(encoding="utf-8", errors="replace") if meta.get("stdout") and meta["stdout"].is_file() else "",
        "stderr": meta["stderr"].read_text(encoding="utf-8", errors="replace") if meta.get("stderr") and meta["stderr"].is_file() else evidence.get("stderr", ""),
        "expected_operations": list(meta.get("expected_operations") or []),
        "protocol": {"version": "watchdog-v2",
                      "messages_dir": str(meta.get("messages")) if meta.get("messages") else None,
                      "acks_dir": str(meta.get("acks")) if meta.get("acks") else None,
                      "next_sequence": int(meta.get("next_sequence") or 1)},
    })
    return evidence


def validate_watchdog_evidence(evidence: dict, expected_operations=()) -> list[str]:
    """Turn child-watchdog evidence into a mandatory parent gate.

    A zero child exit is not sufficient by itself: the parent must have a
    persisted ready/watch event, matching identity, every armed operation's
    start and completion, and a confirmed stop/shutdown outcome.
    """
    errors = []
    if evidence.get("returncode") != 0:
        errors.append("watchdog returncode=%r" % (evidence.get("returncode"),))
    if evidence.get("stderr"):
        errors.append("watchdog emitted stderr")
    if evidence.get("present") is not True:
        errors.append("watchdog events/ready evidence missing")
    events = evidence.get("events") or []
    typed_events = [item for item in events if isinstance(item, dict)]
    actions = [str(item.get("action")) for item in typed_events]
    watching = next((item for item in typed_events if item.get("action") == "watching"), None)
    identity = evidence.get("identity") or {}
    expected_identity = evidence.get("expected_identity") or {}
    for key in ("task_id", "pid", "launch_nonce", "process_generation", "process_identity"):
        if not str(identity.get(key) or ""):
            errors.append("watchdog identity missing %s" % key)
        elif expected_identity and str(identity.get(key)) != str(expected_identity.get(key)):
            errors.append("watchdog identity mismatch %s" % key)
    if watching is None:
        errors.append("watchdog missing ready/watch event")
    elif any(str(watching.get(key)) != str(identity.get(key))
             for key in ("task_id", "pid", "process_generation")):
        errors.append("watchdog ready/watch event identity mismatch")
    if not any(action in ("watchdog_shutdown", "host_exited_before_deadline", "stopped_after_stop_file",
                          "stop_confirmed_after_sigterm", "stop_confirmed_after_supervisor") for action in actions):
        errors.append("watchdog stop/shutdown is unconfirmed")
    operations = list(expected_operations or evidence.get("expected_operations") or [])
    if len(set(str(item) for item in operations)) != len(operations):
        errors.append("watchdog expected operation list contains duplicates")
    operation_events = {}
    for item in typed_events:
        if item.get("action") in ("operation_start", "operation_armed", "operation_started", "operation_complete", "operation_completed"):
            operation_events.setdefault(str(item.get("operation_id")), []).append(item)
    for operation in operations:
        op_events = operation_events.get(str(operation), [])
        starts = [item for item in op_events if item.get("action") in ("operation_start", "operation_armed", "operation_started")]
        completions = [item for item in op_events if item.get("action") in ("operation_complete", "operation_completed")]
        if len(starts) != 1:
            errors.append("watchdog missing start for %s" % operation)
        if len(completions) != 1:
            errors.append("watchdog missing completion for %s" % operation)
        if len(starts) == 1 and len(completions) == 1:
            try:
                start_seq = int(starts[0]["seq"])
                complete_seq = int(completions[0]["seq"])
                if start_seq >= complete_seq:
                    errors.append("watchdog sequence order invalid for %s" % operation)
                if completions[0].get("start_seq") not in (None, start_seq):
                    errors.append("watchdog completion does not bind start for %s" % operation)
            except (KeyError, TypeError, ValueError):
                errors.append("watchdog sequence missing for %s" % operation)
            for event in starts + completions:
                for key in ("task_id", "process_generation"):
                    if str(event.get(key)) != str(identity.get(key)):
                        errors.append("watchdog %s identity mismatch for %s" % (key, operation))
    return errors


class _GateStop(Exception):
    """Normal gate-flow exit: carries the gate code to the unified decision."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = int(code)


def main() -> int:
    root = Path(ARGS.work_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    frames = [int(x) for x in ARGS.frames.split(",")]
    if not frames or len(frames) > 12:
        print(json.dumps({"error": "FRAME_BUDGET_EXCEEDED",
                          "detail": "acceptance allows at most 12 specified frames per heavy job",
                          "frames": frames}))
        return 2
    task = "coreacc-" + uuid.uuid4().hex[:8]
    task_reopen = task + "-r"
    RESULTS["task_id"] = task
    RESULTS["frames"] = frames
    RESULTS["module_sources"] = module_source_record()
    gate_code = 0
    reclaim_failed = False
    hosts_started: list[Path] = []
    watchdogs = []
    try:
        # gate 1: formal host start
        hostA = root / "hostA"
        rc = th.start(argparse.Namespace(task_id=task, work_dir=str(hostA), addon_root=ARGS.addon_root,
                                         houdini_bin=ARGS.houdini_bin, max_seconds=None,
                                         ready_timeout=ARGS.ready_timeout, poll_seconds=0.05, warmup=False))
        hosts_started.append(hostA)
        if rc != 0:
            RESULTS["errors"].append("host A start rc=%s" % rc)
            raise _GateStop(3)
        c, receiptA = client_for(hostA)
        watchdogA = start_watchdog(hostA, ARGS.watchdog_timeout, receiptA)
        watchdogs.append(watchdogA)
        if not wait_watchdog_ready(watchdogA, timeout=min(10.0, ARGS.ready_timeout)):
            RESULTS["errors"].append("watchdog A did not confirm ready; child evidence was preserved")
            watchdogA.kill()
            raise _GateStop(14)
        RESULTS["gates"]["host_start"] = {"generation": receiptA.get("process_generation"),
                                          "nonce": receiptA.get("launch_nonce"),
                                          "warmup": receiptA.get("warmup")}
        if receiptA.get("warmup") not in (None, "skipped"):
            RESULTS["errors"].append("warmup ran without explicit opt-in")
            gate_code = 3

        # gate 2: one-shot build with dual-input contract
        arm_watchdog(watchdogA, "build_preview")
        c.call("agent.fx.build_preview", {"task_id": task, "step_params": {"domain_pack": PACK}})
        complete_watchdog(watchdogA, "build_preview")
        manifest_path = manifest_state_path(task)
        manifest = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
        else:
            RESULTS["errors"].append("manifest not found via receipt path: %s" % manifest_path)
        wires = (manifest.get("connections") or {}).get("verified") or []
        RESULTS["gates"]["build"] = {
            "build_state": manifest.get("build_state"),
            "source_menu": manifest.get("source_menu_choices"),
            "wires": [{"w": "{}.o{}->{}.i{}".format(e["source_role"], e["source_output"], e["destination_role"], e["destination_input"]),
                       "verified": e["verified"]} for e in wires],
        }
        if manifest.get("build_state") not in ("BUILT_VERIFIED", "BUILT_VERIFIED_STATIC"):
            RESULTS["errors"].append("build_state=%s" % manifest.get("build_state"))
            gate_code = 4
        if not any(e["destination_role"] == "solver" and e["destination_input"] == 1 and e["verified"] for e in wires):
            RESULTS["errors"].append("constraint stream (solver.input1) not verified")
            gate_code = 4

        # gate 3: persistent segment run
        arm_watchdog(watchdogA, "segment-primary")
        op = c.call("agent.fx.simulate_segment", {"task_id": task,
                                                  "step_params": {"domain_pack": PACK, "frames": frames},
                                                  "budget_seconds": ARGS.budget})
        request_id = op["request_id"]
        rec, timed_out = wait_terminal(c, task, request_id, timeout=max(ARGS.budget + 60, 180))
        complete_watchdog(watchdogA, "segment-primary")
        RESULTS["gates"]["segment"] = {"state": rec.get("state"), "frames_done": rec.get("frames_done"),
                                       "evidence": rec.get("evidence", []), "wait_timed_out": timed_out}
        if rec.get("state") != "COMPLETED" or timed_out:
            RESULTS["errors"].append("segment state=%s timed_out=%s" % (rec.get("state"), timed_out))
            gate_code = 5
        if sorted(rec.get("frames_done") or []) != sorted(frames):
            RESULTS["errors"].append("frames_done mismatch")
            gate_code = 5

        # gate 4: idempotent resubmit (no rerun)
        again = c.call("agent.fx.simulate_segment", {"task_id": task,
                                                     "step_params": {"domain_pack": PACK, "frames": frames},
                                                     "budget_seconds": ARGS.budget})
        RESULTS["gates"]["resubmit"] = {"same_id": again["request_id"] == request_id,
                                        "state": again["record"].get("state")}
        if again["request_id"] != request_id:
            RESULTS["errors"].append("resubmit produced a different request id")
            gate_code = 6

        # gate 5: budget exhaustion keeps partial results.  The SAME ≤12-frame
        # cap applies to every submission; exhaustion comes from a short
        # budget against a real host's per-frame cook cost.
        arm_watchdog(watchdogA, "segment-budget")
        op2 = c.call("agent.fx.simulate_segment", {"task_id": task,
                                                   "step_params": {"domain_pack": PACK, "frames": frames},
                                                   "budget_seconds": 3})
        rec2, _ = wait_terminal(c, task, op2["request_id"], timeout=90)
        complete_watchdog(watchdogA, "segment-budget")
        RESULTS["gates"]["budget"] = {"state": rec2.get("state"), "frames_done_count": len(rec2.get("frames_done") or [])}
        if rec2.get("state") != "BUDGET_REACHED" or not rec2.get("frames_done"):
            RESULTS["errors"].append("budget gate state=%s" % rec2.get("state"))
            gate_code = 7

        # gate 6: cancel passes only on confirmed stop
        arm_watchdog(watchdogA, "segment-cancel")
        op3 = c.call("agent.fx.simulate_segment", {"task_id": task,
                                                   "step_params": {"domain_pack": PACK, "frames": frames},
                                                   "budget_seconds": ARGS.budget})
        c.call("operation.cancel", {"task_id": task, "operation_id": op3["request_id"]})
        rec3, _ = wait_terminal(c, task, op3["request_id"], timeout=60)
        complete_watchdog(watchdogA, "segment-cancel")
        RESULTS["gates"]["cancel"] = {"state": rec3.get("state")}
        if rec3.get("state") != "CANCELLED":  # CANCEL_PENDING alone is NOT a stop
            RESULTS["errors"].append("cancel state=%s (must be CANCELLED)" % rec3.get("state"))
            gate_code = 8

        # gate 7: save with receipt
        save = c.call("scene.save_hip", {"path": str(root / "coreacc.hip"), "task_id": task})
        RESULTS["gates"]["save"] = {k: save.get(k) for k in ("path", "sha256", "structure")}
        if not save.get("sha256") or not save.get("structure"):
            RESULTS["errors"].append("save receipt incomplete")
            gate_code = 9

        # gate 8: formal reopen in a NEW host + generation takeover
        shutdown_watchdog(watchdogA)
        try:
            watchdogA.wait(timeout=30)
        except subprocess.TimeoutExpired:
            watchdogA.kill()
            RESULTS["errors"].append("watchdog A did not observe host exit")
        RESULTS["gates"]["watchdog_A"] = watchdog_process_evidence(watchdogA)
        rc_stop = th.stop(argparse.Namespace(work_dir=str(hostA), timeout=45))
        if rc_stop not in (0,):
            RESULTS["errors"].append("host A stop rc=%s (exit/slot not confirmed)" % rc_stop)
            gate_code = 10
        # capture stop output by rerunning stop semantics through the launcher is side-effect free here
        hostB = root / "hostB"
        rcB = th.start(argparse.Namespace(task_id=task_reopen, work_dir=str(hostB), addon_root=ARGS.addon_root,
                                          houdini_bin=ARGS.houdini_bin, max_seconds=None,
                                          ready_timeout=ARGS.ready_timeout, poll_seconds=0.05, warmup=False))
        hosts_started.append(hostB)
        if rcB != 0:
            RESULTS["errors"].append("host B start rc=%s" % rcB)
            raise _GateStop(10)
        c2, receiptB = client_for(hostB)
        watchdogB = start_watchdog(hostB, ARGS.watchdog_timeout, receiptB)
        watchdogs.append(watchdogB)
        if not wait_watchdog_ready(watchdogB, timeout=min(10.0, ARGS.ready_timeout)):
            RESULTS["errors"].append("watchdog B did not confirm ready; child evidence was preserved")
            watchdogB.kill()
            raise _GateStop(14)
        try:
            reopen = c2.call("scene.reopen_task_hip", {"task_id": task, "path": save["path"],
                                                       "sha256": save["sha256"]})
            RESULTS["gates"]["reopen"] = {"structure_verified": reopen.get("structure_verified"),
                                          "load_warnings": reopen.get("load_warnings"),
                                          "new_generation": reopen.get("active_generation"),
                                          "old_generation": receiptA.get("process_generation")}
            if not reopen.get("structure_verified"):
                RESULTS["errors"].append("reopen structure unverified")
                gate_code = 11
            if reopen.get("active_generation") == receiptA.get("process_generation"):
                RESULTS["errors"].append("generation did not change on takeover")
                gate_code = 11
        except BridgeError as exc:
            RESULTS["errors"].append("reopen failed: %s" % exc)
            RESULTS["gates"]["reopen"] = {"error": str(exc)[:200]}
            gate_code = 11
        raise _GateStop(gate_code)
    except _GateStop as stop:
        gate_code = stop.code
    except Exception as exc:
        RESULTS["errors"].append("acceptance exception: %s: %s" % (type(exc).__name__, str(exc)[:400]))
        gate_code = gate_code or 15
    finally:
        # reclaim every host we started; record any that would not stop.
        # Cleanup MUST NOT decide the exit code here: the return value of a
        # try block is already fixed when finally runs, so cleanup failures
        # are recorded as a flag and the code is decided AFTER finally.
        for hostdir in hosts_started:
            try:
                if not th.active_owner_present(hostdir):
                    continue
                rc = th.stop(argparse.Namespace(work_dir=str(hostdir), timeout=45))
                if rc != 0:
                    ready = hostdir / th.WORKDIR_READY
                    pid = json.loads(ready.read_text()).get("pid") if ready.is_file() else None
                    RESULTS["errors"].append("UNRECLAIMED host pid=%s dir=%s" % (pid, hostdir))
                    reclaim_failed = True
            except Exception as exc:
                RESULTS["errors"].append("reclaim error on %s: %s" % (hostdir, exc))
                reclaim_failed = True
        for watchdog in watchdogs:
            try:
                if watchdog.poll() is None:
                    shutdown_watchdog(watchdog)
                    watchdog.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watchdog.kill()
                watchdog.wait(timeout=5)
                RESULTS["errors"].append("watchdog process did not exit cleanly")
            except Exception as exc:
                RESULTS["errors"].append("watchdog reclaim error: %s" % exc)

    # unified exit-code decision, made only after cleanup completed
    exit_code = gate_code
    if not exit_code and reclaim_failed:
        exit_code = 12
    if RESULTS["errors"] and not exit_code:
        exit_code = 13
    try:
        if "watchdogB" in locals():
            RESULTS["gates"]["watchdog_B"] = watchdog_process_evidence(watchdogB)
        else:
            RESULTS["gates"]["watchdog_B"] = read_watchdog_events(root / "hostB")
    except NameError:
        pass
    for gate_name in ("watchdog_A", "watchdog_B"):
        evidence = RESULTS["gates"].get(gate_name) or {}
        watchdog_errors = validate_watchdog_evidence(evidence)
        if watchdog_errors:
            RESULTS["errors"].extend([gate_name + ": " + item for item in watchdog_errors])
            if not exit_code:
                exit_code = 16
    RESULTS["exit_code"] = exit_code
    RESULTS["reclaim_failed"] = reclaim_failed
    (root / "accept-results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    print(json.dumps({"exit_code": exit_code, "gates": RESULTS.get("gates"), "errors": RESULTS.get("errors")},
                     ensure_ascii=False, indent=1))
    return exit_code


def run_cli(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--watchdog-child" in argv:
        return _run_watchdog_cli(argv)
    args = parse_args(argv)
    if not configure_normal_runtime(args):
        return 2
    return main()


if __name__ == "__main__":
    sys.exit(run_cli())
