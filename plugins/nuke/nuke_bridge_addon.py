"""Loopback TCP bridge loaded inside Nuke.

Connection workers schedule every Nuke API call on Nuke's main thread. The
addon contains no external dependencies and publishes a per-process manifest.
"""

from __future__ import annotations

import ast
import atexit
import builtins
import errno
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socketserver
import socket
import stat
import subprocess
import sys
import time as _time
import threading
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from uuid import uuid4


_SERVER = None
_TASK_HOST_EXECUTOR = None
_TASK_HOST_IDENTITY = None
_TASK_HOST_ROOT = None
_RENDERS: dict[str, dict[str, Any]] = {}
_DELIVERIES: dict[str, dict[str, Any]] = {}
_COMPOSITES: dict[str, dict[str, Any]] = {}
_NUKE_SCHEDULER: Any = None


def _fx_graph_scheduler():
    """Installation-wide heavy-slot authority shared with Houdini.

    Nuke renders and Houdini frame operations reserve the SAME GraphScheduler
    database (one per installation), so a single heavy job is enforced across
    hosts.  Raises ValueError (SchedulerBusy) while another job is active.
    """
    global _NUKE_SCHEDULER
    if _NUKE_SCHEDULER is None:
        repository_root = Path(__file__).resolve().parents[2]
        for src in ("packages/dcc-task-runtime/src", "packages/vfx-pipeline/src"):
            package_root = repository_root / src
            if package_root.is_dir() and str(package_root) not in sys.path:
                sys.path.insert(0, str(package_root))
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from dcc_task_runtime.state_paths import installation_scheduler_root
        _NUKE_SCHEDULER = GraphScheduler(installation_scheduler_root())
    return _NUKE_SCHEDULER


_RENDER_HANDLES: dict[str, Any] = {}  # in-memory Popen-like handles (process evidence)
_RENDER_RECORDS_DIR: "Path | None" = None
_RENDER_RECORD_ACTIVE_STATES = {"QUEUED", "RUNNING", "CANCEL_PENDING"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_records_dir() -> Path:
    global _RENDER_RECORDS_DIR
    if _RENDER_RECORDS_DIR is None:
        from dcc_task_runtime.state_paths import installation_state_root
        _RENDER_RECORDS_DIR = installation_state_root() / "nuke_renders"
    _RENDER_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    return _RENDER_RECORDS_DIR


def _persist_render_record(task: dict[str, Any]) -> None:
    path = _render_records_dir() / "{}.json".format(task["task_id"])
    tmp = path.with_suffix(".tmp-" + uuid4().hex[:8])
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _load_render_record(task_id: str) -> "dict[str, Any] | None":
    """Recover a render record after a host process restart."""
    path = _render_records_dir() / "{}.json".format(str(task_id))
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    _RENDERS.setdefault(str(task_id), record)
    return record


def _render_history(record: dict[str, Any], to_state: str, note: "str | None" = None) -> None:
    record.setdefault("history", []).append({
        "at": datetime.now(timezone.utc).isoformat(),
        "from": record.get("state"), "to": to_state, "note": note})
    record["state"] = to_state


_NUKE_ARTIFACT_REGISTRY: Any = None


def _immutable_execution_snapshots(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the completion snapshots captured before ledger registration."""
    fact = task.get("execution_fact") if isinstance(task.get("execution_fact"), dict) else {}
    snapshots = fact.get("frame_snapshots") if isinstance(fact.get("frame_snapshots"), dict) else None
    if snapshots is None:
        snapshots = task.get("frame_snapshots") if isinstance(task.get("frame_snapshots"), dict) else {}
    return {str(key): dict(value) for key, value in snapshots.items()
            if isinstance(value, dict)}


def _operation_receipt_sha256(task: dict[str, Any]) -> str:
    """Use one UTF-8 canonical receipt encoder for fact and registration."""
    execution_fact = task.get("execution_fact") if isinstance(task.get("execution_fact"), dict) else {}
    return _canonical_payload_sha256({
        "task_id": task.get("task_id"),
        "pattern": task.get("pattern"),
        "frame_set": list(task.get("frame_set") or []),
        "scene_fingerprint": task.get("scene_fingerprint"),
        "frame_snapshots": _immutable_execution_snapshots(task),
        # A ledger outage must not erase the durable execution outcome.  The
        # public record may be NEEDS_RECONCILE while this fact remains
        # COMPLETED and awaits only registration.
        "state": execution_fact.get("state") or task.get("state"),
        "execution_kind": execution_fact.get("kind"),
    })


def _nuke_operation_fact(operation_id: str):
    """Return only controller-recorded facts; unknown operations fail closed."""
    task = _RENDERS.get(str(operation_id)) or _load_render_record(str(operation_id))
    if not task:
        return None
    first, last = (task.get("frame_range") or [0, -1])[:2]
    frames = list(task.get("frame_set") or
                  range(int(first), int(last) + 1, max(1, int(task.get("stride") or 1))))
    execution_fact = task.get("execution_fact") if isinstance(task.get("execution_fact"), dict) else {}
    legacy_fact = {
        "task_id": str(task.get("owner_task_id") or ("nuke:" + str(task.get("entry") or "render"))),
        "scene_fingerprint": str(task.get("scene_fingerprint") or ""),
        "frame_set": frames, "output_pattern": str(task.get("pattern") or ""),
        "state": str(execution_fact.get("state") or task.get("state") or ""),
        "started_at_epoch": float(task.get("started_at_epoch") or 0.0),
        "frame_snapshots": _immutable_execution_snapshots(task),
        "active_frames": list(task.get("active_frames") or []),
        "visual_objective": task.get("visual_objective"),
        "metadata": {
            "colorspace": str(task.get("colorspace") or ""),
            "premultiplied": task.get("premultiplied"),
        },
        "dependencies": list(task.get("dependencies") or []),
        "operation_receipt_sha256": _operation_receipt_sha256(task),
        "execution_fact": json.loads(json.dumps(execution_fact)),
    }

    from nuke_bridge.operation_receipts import finalize_render_operation, completed_operation_projection
    legacy_fact.update(operation_id=None, execution_kind=None, stop_confirmed=False,
                       completion_metadata_status="UNAVAILABLE_UNVERIFIED_COMPLETION")
    legacy_fact["formal_receipt"] = finalize_render_operation(task, legacy_fact)
    projection = completed_operation_projection(legacy_fact["formal_receipt"], legacy_fact)
    if projection and projection["execution_kind"] == "owned_subprocess":
        try:
            if _render_supervisor_stop_reason(task, 0) is not None: projection = None
        except (ValueError, OSError, KeyError, TypeError): projection = None
    if projection:
        if projection.get('completion_metadata_status') == 'AVAILABLE':
            try:
                current_matches = _snapshot_frames(str(task['pattern']), frames) == _immutable_execution_snapshots(task)
            except (ValueError, OSError, KeyError, TypeError):
                current_matches = False
            if not current_matches:
                projection.pop('metadata', None)
                projection['completion_metadata_status'] = 'INVALID_CURRENT_OUTPUT'
        legacy_fact.update(projection)
    elif legacy_fact["formal_receipt"] is not None:
        legacy_fact["formal_receipt"] = None
        legacy_fact["completion_metadata_status"] = "UNAVAILABLE_UNVERIFIED_STOP"
    return legacy_fact


def _nuke_artifact_registry():
    """Installation-wide artifact ledger (R07 production wiring)."""
    global _NUKE_ARTIFACT_REGISTRY
    if _NUKE_ARTIFACT_REGISTRY is None:
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        # The records directory is the state-root anchor.  Keeping the ledger
        # beside it also makes an explicitly isolated controller state root
        # authoritative in tests and in a bundled worker process.
        registry = ArtifactRegistry(Path(os.environ["BRIDGE_ARTIFACT_LEDGER_ROOT"]) if os.environ.get("BRIDGE_ARTIFACT_LEDGER_ROOT") else _render_records_dir().parent / "artifact_ledger")
        registry.set_operation_source(_nuke_operation_fact)
        _NUKE_ARTIFACT_REGISTRY = registry
    return _NUKE_ARTIFACT_REGISTRY


def _register_render_artifact(task: dict[str, Any]) -> "dict | None":
    """Ledger entry for a completed render, tied to its operation receipt."""
    try:
        if task.get('input_contract') is not None:
            from nuke_bridge.operation_receipts import validate_registered_input_contract
            validate_registered_input_contract(task['input_contract'])
        execution = task.get("execution_fact") or {}
        if task.get('output_verification') is not None and (
                execution.get('completion_metadata_status') != 'AVAILABLE'
                or execution.get('output_verification') != task['output_verification']):
            raise ValueError('OUTPUT_VERIFICATION_COMPLETION_REQUIRED')
        if str(execution.get("completion_metadata_status") or "").startswith("INVALID"):
            raise ValueError("COMPLETION_METADATA_INVALID: " + str(execution.get("completion_metadata_error") or "binding"))
        if execution.get("completion_metadata_status") == "AVAILABLE":
            if _snapshot_frames(str(task["pattern"]), list(task["frame_set"])) != _immutable_execution_snapshots(task):
                raise ValueError("COMPLETION_OUTPUT_DRIFT: output changed before ledger registration")
            producer = _nuke_operation_fact(str(task["task_id"]))
            if not producer or producer.get("stop_confirmed") is not True or producer.get("completion_metadata_status") not in {"AVAILABLE", "UNAVAILABLE_LEGACY_WORKER_READBACK"}:
                raise ValueError("COMPLETION_METADATA_UNVERIFIED: actual formal completion/stop binding required")

        receipt = _operation_receipt_sha256(task)
        return _nuke_artifact_registry().register(
            artifact_id="nuke-render-" + str(task["task_id"]),
            task_id=str(task.get("owner_task_id") or ("nuke:" + str(task.get("entry") or "render"))),
            artifact_class=str(task.get("artifact_class") or "preview_temp"),
            pattern=str(task.get("pattern") or ""),
            frame_set=list(task.get("frame_set") or range(
                int(task["frame_range"][0]), int(task["frame_range"][1]) + 1,
                max(1, int(task.get("stride") or 1)))),
            colorspace=str(task.get("colorspace") or ""),
            premultiplied=task.get("premultiplied"),
            dependencies=list(task.get("dependencies") or [str(task.get("scene_fingerprint") or task.get("task_id"))]),
            operation_id=str(task["task_id"]),
            operation_receipt_sha256=receipt,
            payload={
                "completion_snapshot": _immutable_execution_snapshots(task),
                "active_frames": list(task.get("active_frames") or []),
                "visual_objective": task.get("visual_objective"),
                "delivery_confirmations": dict(task.get("delivery_confirmations") or {
                    "colorspace_confirmed": bool(str(task.get("colorspace") or "")),
                    "premultiplied_confirmed": type(task.get("premultiplied")) is bool,
                    "dependencies_confirmed": bool(task.get("dependencies")),
                }),
            },
        )
    except Exception:
        # Ledger failure is an evidence failure.  The caller must retain the
        # operation for reconciliation; never report a completed render with
        # a silently missing artifact fact.
        raise


def _verify_owned_worker_receipt(task: dict[str, Any]) -> dict[str, Any]:
    """Verify the fixed worker's task/snapshot/node/frame execution receipt."""
    process = task.get("process") or {}
    receipt_path = Path(str(process.get("worker_result") or "")).expanduser()
    if not str(receipt_path) or receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("WORKER_EVIDENCE_MISSING: owned worker receipt is unavailable")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("WORKER_EVIDENCE_INVALID: owned worker receipt is not valid JSON") from exc
    expected_frames = list(task.get("frame_set") or [])
    expected_snapshot = Path(str(task.get("script_snapshot") or "")).expanduser()
    expected_snapshot_sha = _artifact(expected_snapshot).get("sha256") if expected_snapshot.is_file() else ""
    expected_outputs = [str(_frame_path(str(task.get("pattern") or ""), int(frame)).resolve())
                       for frame in expected_frames]
    actual_outputs = [str(Path(str(item)).expanduser().resolve()) for item in receipt.get("outputs") or []]
    if (str(receipt.get("task_id") or "") != str(task.get("task_id") or "")
            or str(receipt.get("snapshot") or "") != str(expected_snapshot)
            or str(receipt.get("snapshot_sha256") or "") != str(expected_snapshot_sha)
            or str(receipt.get("node") or "") != str(task.get("node") or "")
            or list(receipt.get("frames") or []) != expected_frames
            or list(receipt.get("execute_calls") or []) != expected_frames
            or receipt.get("script_opened") is not True
            or receipt.get("node_resolved") is not True
            or actual_outputs != expected_outputs):
        raise ValueError("WORKER_EVIDENCE_MISMATCH: receipt does not match task launch identity")
    if any(not Path(path).is_file() or Path(path).is_symlink() for path in actual_outputs):
        raise ValueError("WORKER_EVIDENCE_MISSING: worker receipt names missing output files")
    if task.get('input_contract') is not None:
        from nuke_bridge.operation_receipts import validate_registered_input_contract, worker_input_readback_valid
        validate_registered_input_contract(task['input_contract'])
        expected_input_sha = (process.get('supervisor_identity') or {}).get('input_contract_sha256')
        if (not worker_input_readback_valid(receipt, task['input_binding'])
                or receipt['input_readback']['contract_sha256'] != expected_input_sha
                or expected_input_sha != _canonical_payload_sha256(task['input_contract'])):
            raise ValueError('INPUT_SOURCE_HASH_MISMATCH: actual worker input consumption is unverified')
    if task.get('composite_contract') is not None:
        from nuke_bridge.operation_receipts import worker_composite_readback_valid
        expected_sha = (process.get('supervisor_identity') or {}).get('composite_contract_sha256')
        if (task['composite_contract'].get('task_id') != task.get('owner_task_id')
                or (process.get('supervisor_identity') or {}).get('owner_task_id') != task.get('owner_task_id')
                or not worker_composite_readback_valid(receipt,task['composite_contract'],expected_sha)):
            raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: actual worker graph consumption is unverified')

    return receipt



def _native_write_output_settings(write, pattern, scene_fingerprint):
    """Known Nuke 17 Write knobs; no params or pixel-based color inference."""
    from nuke_bridge.operation_receipts import native_write_readback
    try:
        readback = native_write_readback(write)
        values = readback['settings']
        if (values['file'] != str(pattern) or not values['colorspace'].strip()
                or 'default' in values['colorspace'].lower() or values['raw'] is not False): return None
        return {'origin':'nuke_write_readback', 'class':'Write', 'node':readback['node'],
            'pattern':str(pattern), 'scene_fingerprint':str(scene_fingerprint),
            'colorspace':values['colorspace'], 'premultiplied':values['premultiplied'], 'raw':False}
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _capture_render_completion_metadata(task):
    """Capture once at trusted completion, never during ledger recovery."""
    from nuke_bridge.operation_receipts import capture_completion_metadata
    fact = task["execution_fact"]
    if task.get("input_contract") is not None:
        fact["input_contract_sha256"] = _canonical_payload_sha256(task["input_contract"])
    if task.get("output_verification") is not None:
        fact["output_verification"] = json.loads(json.dumps(task["output_verification"]))
    settings = task.get("native_output_settings")
    if not isinstance(settings,dict):
        fact["completion_metadata_status"] = "UNAVAILABLE_NATIVE_WRITE_SETTINGS"; return
    fact["native_output_settings"] = json.loads(json.dumps(settings))
    if task.get("project_color") is not None:
        fact["project_color"] = json.loads(json.dumps(task["project_color"]))
    producer = _nuke_operation_fact(str(task["task_id"]))
    if not producer or producer.get("stop_confirmed") is not True:
        fact["completion_metadata_status"] = "UNAVAILABLE_UNVERIFIED_COMPLETION"; return
    try:
        if fact["kind"] == "synchronous_nuke_execute":
            import nuke
            actual = _native_write_output_settings(nuke.toNode(task["node"]), task["pattern"],
                                                  _nuke_scene_version_fingerprint(nuke))
            expected = {k:v for k,v in settings.items() if k not in {"operation_id","request_id"}}
            if actual != expected: raise ValueError("native Write/scene changed during execution")
        else:
            from nuke_bridge.operation_receipts import worker_write_readback_valid
            worker = fact.get('worker_receipt') or {}
            if 'write_readback' not in worker:
                fact['completion_metadata_status'] = 'UNAVAILABLE_LEGACY_WORKER_READBACK'; return
            if not worker_write_readback_valid(worker, operation_id=task['task_id'], node=task['node'],
                    frames=task['frame_set'], snapshot_sha256=worker.get('snapshot_sha256')):
                raise ValueError('actual worker Write readback binding invalid')
            actual = worker['write_readback']['settings']
            if actual != {'file':settings['pattern'], 'colorspace':settings['colorspace'],
                    'premultiplied':settings['premultiplied'], 'raw':settings['raw']}:
                raise ValueError('snapshot Write readback differs from live launch settings')
            if actual['raw'] is not False:
                fact['completion_metadata_status'] = 'UNAVAILABLE_RAW_COLOR_SEMANTICS'; return
            settings = {**settings, 'colorspace':actual['colorspace'],
                'premultiplied':actual['premultiplied'], 'raw':actual['raw'],
                'snapshot_sha256':worker['snapshot_sha256']}
            fact['native_output_settings'] = json.loads(json.dumps(settings))
        fact["completion_metadata"] = capture_completion_metadata({**task, 'native_output_settings':settings}, fact["frame_snapshots"])
        fact["completion_metadata_status"] = "AVAILABLE"
        # Keep the legacy registration fields aligned with observed Write semantics.
        task["colorspace"] = settings["colorspace"]
        task["premultiplied"] = settings["premultiplied"]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        fact["completion_metadata_status"] = "INVALID_CAPTURE"
        fact["completion_metadata_error"] = str(exc)[:200]


def _record_synchronous_execution_fact(task: dict[str, Any], verification: dict[str, Any]) -> None:
    """Persist execution/stop success before attempting ledger registration.

    The ledger is a consumer of this fact, not the source of truth for whether
    Nuke executed and stopped.  Keeping the fact in the task record lets a
    later controller retry registration without calling ``nuke.execute`` a
    second time.
    """
    frames = list(task.get("frame_set") or [])
    snapshots = _snapshot_frames(str(task.get("pattern") or ""), frames)
    task["frame_snapshots"] = snapshots
    completed_at = _now_iso()
    task["execution_fact"] = {
        "schema": "bridge.nuke.execution_fact/1.0",
        "kind": "synchronous_nuke_execute",
        "state": "COMPLETED",
        "task_id": str(task.get("task_id") or ""),
        "request_id": str(task.get("request_id") or ""),
        "frame_set": frames,
        "pattern": str(task.get("pattern") or ""),
        "exit_code": 0,
        "process_identity": "nuke-main:{}:{}".format(os.getpid(), threading.get_ident()),
        "stop_confirmed": True,
        "completed_at": completed_at,
        "frame_snapshots": dict(snapshots),
        "verification": dict(verification),
    }
    task["execution_state"] = "COMPLETED"
    task["stop_confirmed_at"] = task.get("stop_confirmed_at") or completed_at
    _capture_render_completion_metadata(task)


def _record_owned_execution_fact(task: dict[str, Any], verification: dict[str, Any],
                                 worker_receipt: dict[str, Any], exit_code: int) -> None:
    """Persist a verified owned-worker exit before ledger registration."""
    frames = list(task.get("frame_set") or [])
    completed_at = _now_iso()
    snapshots = _snapshot_frames(str(task.get("pattern") or ""), frames)
    task["frame_snapshots"] = snapshots
    task["execution_fact"] = {
        "schema": "bridge.nuke.execution_fact/1.0",
        "kind": "owned_subprocess",
        "state": "COMPLETED",
        "task_id": str(task.get("task_id") or ""),
        "request_id": str(task.get("request_id") or ""),
        "frame_set": frames,
        "pattern": str(task.get("pattern") or ""),
        "exit_code": int(exit_code),
        "process_identity": dict(task.get("process") or {}),
        "stop_confirmed": True,
        "worker_receipt": dict(worker_receipt),
        "completed_at": completed_at,
        "frame_snapshots": dict(snapshots),
    }
    task["execution_state"] = "COMPLETED"
    task["stop_confirmed_at"] = task.get("stop_confirmed_at") or completed_at
    _capture_render_completion_metadata(task)


def _has_durable_execution_success(task: dict[str, Any]) -> bool:
    fact = task.get("execution_fact")
    return bool(
        isinstance(fact, dict)
        and fact.get("kind") in {"synchronous_nuke_execute", "owned_subprocess"}
        and fact.get("state") == "COMPLETED"
        and fact.get("stop_confirmed") is True
        and type(fact.get("exit_code")) is int
        and fact.get("exit_code") == 0
        and list(fact.get("frame_set") or []) == list(task.get("frame_set") or [])
        and str(fact.get("pattern") or "") == str(task.get("pattern") or "")
        and isinstance(fact.get("frame_snapshots"), dict)
        and all(isinstance(fact["frame_snapshots"].get(str(frame)), dict)
                and fact["frame_snapshots"].get(str(frame))
                for frame in list(task.get("frame_set") or []))
    )


def _verify_execution_fact_outputs(task: dict[str, Any], verification: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reject output replacement after execution, even when files are fresh."""
    fact = task.get("execution_fact") if isinstance(task.get("execution_fact"), dict) else {}
    expected = fact.get("frame_snapshots") if isinstance(fact.get("frame_snapshots"), dict) else {}
    frames = list(task.get("frame_set") or [])
    current = _snapshot_frames(str(task.get("pattern") or ""), frames)
    if (not verification.get("ok") or not verification.get("fresh")
            or any(current.get(str(frame)) != expected.get(str(frame)) for frame in frames)):
        raise ValueError("RECOVER_OUTPUT_DRIFT: outputs differ from the original execution snapshots")
    return {str(frame): dict(expected[str(frame)]) for frame in frames}


def _register_durable_execution(task: dict[str, Any], *, note: str) -> dict[str, Any]:
    """Verify and register a durable execution fact without re-executing it."""
    if not _has_durable_execution_success(task):
        raise ValueError("RECOVER_EXECUTION_FACT_UNAVAILABLE: no durable synchronous completion fact")
    fact = task.get("execution_fact") or {}
    if fact.get("kind") == "owned_subprocess":
        try:
            task["worker_receipt"] = _verify_owned_worker_receipt(task)
        except ValueError as exc:
            raise ValueError("RECOVER_WORKER_EVIDENCE_UNVERIFIED: {}".format(exc)) from exc
    expected_frames = list(task.get("frame_set") or [])
    verification = _verify(
        str(task.get("pattern") or ""),
        int((task.get("frame_range") or [0, 0])[0]),
        int((task.get("frame_range") or [0, 0])[1]),
        not_before=float(task.get("started_at_epoch") or 0.0),
        frames=expected_frames or None,
    )
    if not (verification.get("ok") and verification.get("fresh")):
        raise ValueError("RECOVER_INVALID: outputs are not proven complete and fresh")
    task["frame_snapshots"] = _verify_execution_fact_outputs(task, verification)
    task["artifact"] = _register_render_artifact(task)
    task["ledger_state"] = "REGISTERED"
    task["ledger_error"] = None
    if task.get("state") != "COMPLETED":
        _render_history(task, "COMPLETED", note=note)
    task["stop_confirmed_at"] = task.get("stop_confirmed_at") or _now_iso()
    _fx_release_render_slot(task)
    task["slot_released"] = True
    task["execution_fact"]["ledger_state"] = "REGISTERED"
    task["execution_fact"]["registered_at"] = _now_iso()
    _persist_render_record(task)
    return task


def _mark_verified_stop_pending_ledger(task: dict[str, Any], *, note: str,
                                       error: Any = None) -> None:
    """Release a slot once the owned execution has a durable stop fact.

    Artifact-ledger registration is a separate durable consumer.  A ledger
    outage must leave the result in ``NEEDS_RECONCILE`` without keeping a
    heavy slot occupied after the host has already proved that its process
    stopped.  The output and execution snapshots remain attached to the
    record so a later controller retry can register the same result without
    executing Nuke again.
    """
    task["state"] = "NEEDS_RECONCILE"
    task["execution_state"] = "COMPLETED"
    task["ledger_state"] = "PENDING"
    if error is not None:
        task["ledger_error"] = str(error)[:200]
    task["stop_confirmed_at"] = task.get("stop_confirmed_at") or _now_iso()
    _fx_release_render_slot(task)
    task["slot_released"] = True
    fact = task.get("execution_fact")
    if isinstance(fact, dict):
        fact["ledger_state"] = "PENDING"
        fact["stop_confirmed"] = True
    _render_history(task, "NEEDS_RECONCILE", note=note)


def _fx_pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        from dcc_task_runtime.platform_support import pid_alive
        return pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _verify_control_authorization(action: str, payload: dict[str, Any], authorization: Any) -> str:
    """Nuke-side control authorization: same HMAC secret convention (C2)."""
    import hmac as _hmac
    if not isinstance(authorization, dict):
        raise ValueError("control authorization object required")
    if not str(authorization.get("verified_by") or "").strip():
        raise ValueError("verified_by must name the control operator and the verified evidence")
    signature = str(authorization.get("signature") or "")
    if not signature:
        raise ValueError("APPROVAL_INVALID: control authorization requires a verifiable signature")
    secret = _fx_approval_secret_value()
    body = json.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = _hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(signature, expected):
        raise ValueError("APPROVAL_INVALID: control authorization signature is invalid")
    return str(authorization["verified_by"])


def _fx_approval_secret_value() -> str:
    direct = os.environ.get("HOUDINI_BRIDGE_APPROVAL_SECRET")
    if direct:
        if len(direct) < 32:
            raise ValueError("APPROVAL_INVALID: approval secret is too short")
        return direct
    configured = os.environ.get("BRIDGE_SKILLS_APPROVAL_SECRET_FILE")
    path = Path(configured).expanduser() if configured else Path.home() / ".bridge-skills" / "approval.key"
    if path.is_symlink() or not path.is_file():
        raise ValueError("APPROVAL_INVALID: approval secret must be a regular file")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError("APPROVAL_INVALID: approval secret is too short")
    return value


def nuke_render_recover(task_key: "str | None" = None) -> dict[str, Any]:
    """Read-only Nuke-side recovery scan (C2): crash-window orphans.

    Kinds: ``intent_not_reserved`` (phase intent without slot), ``launch_not_saved``
    (record RUNNING whose launch phase never committed), ``terminal_not_released``
    (record terminal but slot still active) and ``unknown_active``.  Queries never
    release anything.
    """
    scheduler = _fx_graph_scheduler()
    snapshot = scheduler.snapshot()
    orphans: list[dict[str, Any]] = []
    records_dir = _render_records_dir()
    for phase_file in sorted(records_dir.glob("*.phase.json")):
        try:
            marker = json.loads(phase_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            marker = {}
        task_id = str(marker.get("task_id") or "")
        record = _load_render_record(task_id) if task_id else None
        if record is None:
            active = bool(snapshot and snapshot.get("active")
                          and snapshot.get("operation_id") == task_id)
            proven_unstarted = (active and marker.get("phase") in {"intent", "reserved"}
                                and snapshot.get("phase") in {"RESERVED", "FENCED_UNSTARTED"}
                                and not snapshot.get("process_json"))
            orphans.append({"kind": "reserved_without_record" if proven_unstarted else "intent_not_reserved",
                            "task_id": task_id, "phase": marker.get("phase"),
                            "evidence": "intent phase without a committed record"})
            continue
        if marker.get("phase") in {"launching", "launched"} and not record.get("process"):
            orphans.append({"kind": "launch_not_saved", "task_id": task_id,
                            "evidence": "dispatch intent exists but process binding did not commit; unknown stays held"})
        if marker.get("phase") in ("reserved", "intent") and record.get("state") in ("RUNNING", "NEEDS_RECONCILE"):
            slot_gen = int((record.get("slot") or {}).get("generation") or 0)
            active_gen = int((snapshot or {}).get("generation") or 0)
            if slot_gen and active_gen and slot_gen != active_gen:
                orphans.append({"kind": "launch_not_saved", "task_id": task_id,
                                "record_generation": slot_gen, "active_generation": active_gen,
                                "evidence": "record RUNNING with a stale slot binding"})
    if snapshot and snapshot.get("active"):
        op_id = str(snapshot.get("operation_id") or "")
        record = _load_render_record(op_id)
        if record is not None and record.get("state") in ("COMPLETED", "FAILED", "CANCELLED"):
            orphans.append({"kind": "terminal_not_released", "task_id": op_id,
                            "evidence": "record terminal and marked released but the slot is still active"})
        elif record is None:
            orphans.append({"kind": "unknown_active", "task_id": op_id,
                            "evidence": "active reservation without a committed record; stays blocked"})
    return {"orphans": orphans, "slot_active": bool(snapshot and snapshot.get("active"))}


def nuke_render_resolve(action: str, task_id: str, authorization: Any, note: str = "") -> dict[str, Any]:
    """Signed control actions over Nuke render recovery (C2).

    ``release_terminal``: record terminal + slot still active -> free it.
    ``adopt_launched``: record launched with a persisted pid -> bind the live
    process evidence to the record (no new side effect).  Unknown stays held.
    """
    verified_by = _verify_control_authorization(action, {"task_id": str(task_id)}, authorization)
    scheduler = _fx_graph_scheduler()
    snapshot = scheduler.snapshot()
    record = _load_render_record(str(task_id))
    if action == "release_unstarted":
        if (not snapshot or not snapshot.get("active")
                or str(snapshot.get("operation_id") or "") != str(task_id)):
            raise ValueError("RECOVER_TARGET_GONE: no matching active reservation")
        marker_path = _render_records_dir() / (str(task_id) + ".phase.json")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            marker = {}
        record_path = _render_records_dir() / (str(task_id) + ".json")
        if (marker.get("task_id") != task_id or marker.get("phase") not in {"intent", "reserved"}
                or marker.get("owner_root") != snapshot.get("owner_root")
                or (marker.get("phase") == "reserved" and
                    (marker.get("slot_generation") != snapshot.get("generation")
                     or marker.get("slot_token") != snapshot.get("token")))
                or (record is None and record_path.exists())
                or (record is not None and record.get("dispatch_state"))
                or snapshot.get("process_json")):
            raise ValueError("RECOVER_UNSTARTED_UNPROVEN: dispatch or corrupt evidence remains unknown")
        owner, token = str(snapshot["owner_root"]), str(snapshot["token"])
        # The scheduler CAS is the non-dispatch fact, not the caller's HMAC.
        # A launcher that resumes after this fence cannot arm its old permit.
        if not scheduler.fence_unstarted(owner, str(task_id), token):
            raise ValueError("RECOVER_UNSTARTED_UNPROVEN: launch permit already armed")
        released = scheduler.release(owner, str(task_id), token, unstarted=True)
        if record is not None:
            record["dispatch_state"] = "NOT_STARTED"
            record["slot_released"] = bool(released)
            record["stop_confirmed_at"] = _now_iso()
            _render_history(record, "FAILED", note="control fenced an unstarted render permit")
            _persist_render_record(record)
        marker_path.unlink(missing_ok=True)
        return {"released": bool(released), "task_id": str(task_id), "verified_by": verified_by}
    if action == "release_terminal":
        if not snapshot or str(snapshot.get("operation_id") or "") != str(task_id):
            raise ValueError("RECOVER_TARGET_GONE: no active reservation for {}".format(task_id))
        if record is None or record.get("state") not in ("COMPLETED", "FAILED", "CANCELLED"):
            raise ValueError("RECOVER_INVALID: {} is not a proven terminal record".format(task_id))
        slot = record.get("slot") or {}
        if (slot.get("token") != snapshot.get("token")
                or slot.get("generation") != snapshot.get("generation")
                or slot.get("owner_root") != snapshot.get("owner_root")):
            raise ValueError("RECOVER_SLOT_MISMATCH: terminal record belongs to another attempt")
        handle = _restore_supervised_handle(record)
        if not _has_durable_execution_success(record) and (handle is None or handle.poll() is None):
            raise ValueError("RECOVER_STOP_UNCONFIRMED: terminal label is not an observed stop")
        scheduler.release(str(snapshot.get("owner_root")), str(snapshot.get("operation_id")),
                          str(snapshot.get("token")), stopped=True)
        record["slot_released"] = True
        record["stop_confirmed_at"] = record.get("stop_confirmed_at") or _now_iso()
        _persist_render_record(record)
        return {"released": True, "task_id": str(task_id), "verified_by": verified_by, "note": str(note or "")}
    if action == "complete_recovered":
        slot = (record or {}).get("slot") or {}
        if (snapshot and snapshot.get("active") and snapshot.get("operation_id") == task_id
                and (snapshot.get("token") != slot.get("token")
                     or snapshot.get("generation") != slot.get("generation")
                     or snapshot.get("owner_root") != slot.get("owner_root"))):
            raise ValueError("RECOVER_SLOT_MISMATCH: completion belongs to another attempt")
        if (record is not None and record.get("state") == "COMPLETED"
                and record.get("slot_released") and record.get("artifact")):
            # Recovery is idempotent after a retry successfully filled the
            # ledger.  This is an observation of the same execution, never a
            # second host call or render.
            return {"completed": True, "reused": True, "task_id": str(task_id),
                    "verified_by": verified_by}
        # Completion recovery is only legal with a still-owned in-memory
        # process handle whose exit code is observed by this controller.  A
        # dead PID after restart is not a stop receipt, and live output is
        # never allowed to outrun a live child.
        if record is None or record.get("state") != "NEEDS_RECONCILE":
            raise ValueError("RECOVER_INVALID: {} is not NEEDS_RECONCILE".format(task_id))
        if _has_durable_execution_success(record):
            # A verified stop may already have released the heavy slot while
            # the ledger was unavailable.  Re-registration is still allowed
            # for that exact durable fact and never calls the host again.
            if (record.get("slot_released")
                    and (not snapshot or str(snapshot.get("operation_id") or "") != str(task_id))):
                try:
                    _register_durable_execution(
                        record,
                        note="re-registered durable execution after ledger recovery",
                    )
                except Exception as exc:
                    record["ledger_error"] = str(exc)[:200]
                    record["ledger_state"] = "PENDING"
                    _persist_render_record(record)
                    raise ValueError("RECOVER_LEDGER_REQUIRED: completed output has no ledger receipt") from exc
                return {"completed": True, "task_id": str(task_id), "verified_by": verified_by,
                        "execution_kind": str((record.get("execution_fact") or {}).get("kind") or "")}
            if not snapshot or str(snapshot.get("operation_id") or "") != str(task_id):
                raise ValueError("RECOVER_TARGET_GONE: no active reservation for {}".format(task_id))
            try:
                _register_durable_execution(
                    record,
                    note="recovered durable synchronous execution; ledger registration completed",
                )
            except Exception as exc:
                record["ledger_error"] = str(exc)[:200]
                record["ledger_state"] = "PENDING"
                _persist_render_record(record)
                raise ValueError("RECOVER_LEDGER_REQUIRED: completed output has no ledger receipt") from exc
            return {"completed": True, "task_id": str(task_id), "verified_by": verified_by,
                    "execution_kind": "synchronous_nuke_execute"}
        handle = _RENDER_HANDLES.get(str(task_id))
        if handle is None or not hasattr(handle, "poll"):
            raise ValueError("RECOVER_STOP_UNCONFIRMED: owned process handle is unavailable")
        observed_rc = handle.poll()
        if observed_rc is None:
            raise ValueError("RECOVER_PROCESS_LIVE: owned process is still running")
        if observed_rc != 0:
            raise ValueError("RECOVER_PROCESS_FAILED: owned process exit code {}".format(observed_rc))
        verification = _verify(record["pattern"], int(record["frame_range"][0]), int(record["frame_range"][1]),
                               not_before=float(record.get("started_at_epoch") or 0.0),
                               frames=list(record.get("frame_set") or []) or None)
        if not (verification["ok"] and verification["fresh"]):
            raise ValueError("RECOVER_INVALID: outputs are not proven complete and fresh")
        try:
            worker_receipt = _verify_owned_worker_receipt(record)
        except ValueError as exc:
            raise ValueError("RECOVER_WORKER_EVIDENCE_UNVERIFIED: {}".format(exc)) from exc
        record["worker_receipt"] = worker_receipt
        record["exit_code"] = observed_rc
        record["frame_snapshots"] = _snapshot_frames(record["pattern"], list(record.get("frame_set") or []))
        _render_history(record, "COMPLETED", note="recovered process exit observed; ledger registration pending")
        try:
            record["artifact"] = _register_render_artifact(record)
        except Exception as exc:
            _render_history(record, "NEEDS_RECONCILE", note="recovered output ledger registration failed")
            record["ledger_error"] = str(exc)[:200]
            _persist_render_record(record)
            raise ValueError("RECOVER_LEDGER_REQUIRED: completed output has no ledger receipt") from exc
        record["history"][-1]["note"] = "recovered by control from exit+artifact evidence"
        record["stop_confirmed_at"] = _now_iso()
        scheduler.release(str(snapshot.get("owner_root")), str(snapshot.get("operation_id")),
                          str(snapshot.get("token")), stopped=True)
        record["slot_released"] = True
        _persist_render_record(record)
        return {"completed": True, "task_id": str(task_id), "verified_by": verified_by}
    if action == "adopt_launched":
        slot = (record or {}).get("slot") or {}
        if (not snapshot or not snapshot.get("active")
                or snapshot.get("operation_id") != task_id
                or snapshot.get("owner_root") != slot.get("owner_root")
                or snapshot.get("token") != slot.get("token")
                or snapshot.get("generation") != slot.get("generation")):
            raise ValueError("ADOPT_UNVERIFIED: active slot does not match the recorded attempt")
        handle = _restore_supervised_handle(record)
        if handle is None:
            raise ValueError("ADOPT_UNVERIFIED: exact supervisor start receipt is required")
        pid = handle.pid
        (record or {}).setdefault("history", []).append(
            {"from": record.get("state"), "to": record.get("state"), "note": "launched process adopted",
             "adopted_by": verified_by, "at": _now_iso()})
        _persist_render_record(record)
        return {"adopted": True, "task_id": str(task_id), "pid": pid, "verified_by": verified_by}
    raise ValueError("unsupported recovery action: {}".format(action))


def _fx_release_render_slot(task: dict[str, Any]) -> None:
    """Release the render's installation slot after an observed stop."""
    slot = task.get("slot") or {}
    if not (slot.get("owner_root") and slot.get("operation_id") and slot.get("token")):
        return
    try:
        _fx_graph_scheduler().release(slot["owner_root"], slot["operation_id"], slot["token"], stopped=True)
    except ValueError:
        pass  # already released or rotated by the control plane
_ALLOWED_IMPORTS = {"nuke", "nukescripts", "math", "re", "json", "random", "colorsys", "struct"}
_FORBIDDEN_NAMES = {"open", "eval", "exec", "compile", "getattr", "setattr", "__import__", "exit", "quit"}
_MAX_COMPOSITE_FRAME_COUNT = 10_000
_SEQUENCE_TOKEN = re.compile(r"%(?:0?[1-9][0-9]*)?d|#+")
_MAIN_THREAD_TIMEOUT_SECONDS = 120.0
_MAX_REQUEST_BYTES = 1024 * 1024
_MIN_TOKEN_LENGTH = 32
_LEGACY_UNAUTH_ENV = "NUKE_BRIDGE_ALLOW_LEGACY_UNAUTHENTICATED"
_ATEXIT_REGISTERED = False


class _MainThreadTimeoutError(TimeoutError):
    """A main-thread request did not finish within the bridge deadline."""

    def __init__(self, *, indeterminate: bool) -> None:
        self.indeterminate = bool(indeterminate)
        state = "is still running" if self.indeterminate else "was cancelled before execution"
        super().__init__(
            "Nuke main-thread callback timed out after {:.1f} seconds; {}".format(
                _MAIN_THREAD_TIMEOUT_SECONDS,
                state,
            )
        )


class _RequestLineError(ValueError):
    """A socket request exceeded the bounded, newline-delimited protocol."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _invalidate_script_registries() -> dict[str, dict[str, int]]:
    """Drop every cache whose node identities belong to the current script."""

    registries = {
        "composites": _COMPOSITES,
        "deliveries": _DELIVERIES,
        "renders": _RENDERS,
    }
    before = {name: len(registry) for name, registry in registries.items()}
    for registry in registries.values():
        registry.clear()
    after = {name: len(registry) for name, registry in registries.items()}
    return {"before": before, "after": after}


def _nuke_scene_fingerprint(task_id: str = "") -> dict[str, Any]:
    """Hash full knob script state so bridge-owned dirt can be distinguished."""

    import nuke

    errors: list[str] = []
    try:
        root = nuke.root()
        nodes = [node for node in (root, *list(nuke.allNodes(recurseGroups=True))) if node is not None]
    except Exception as exc:
        return {"scene_fingerprint": "", "fingerprint_complete": False, "fingerprint_errors": [str(exc)]}
    records: list[dict[str, Any]] = []
    record_nodes: list[Any] = []
    for node in sorted(nodes, key=_node_lineage_name):
        node_name = _node_lineage_name(node)
        try:
            knob_map = node.knobs()
        except Exception as exc:
            errors.append(f"{node_name}:knobs:{exc}")
            continue
        knobs: dict[str, str] = {}
        for name, knob in sorted(dict(knob_map or {}).items()):
            serializer = getattr(knob, "toScript", None)
            if not callable(serializer):
                errors.append(f"{node_name}.{name}:toScript unavailable")
                continue
            try:
                knobs[str(name)] = str(serializer())
            except Exception as exc:
                errors.append(f"{node_name}.{name}:toScript:{exc}")
        connections: list[str | None] = []
        dependencies: list[str] = []
        if node is not root:
            input_count = getattr(node, "inputs", None)
            input_reader = getattr(node, "input", None)
            if not callable(input_count) or not callable(input_reader):
                errors.append(f"{node_name}:input enumeration unavailable")
            else:
                try:
                    for index in range(int(input_count())):
                        source = input_reader(index)
                        connections.append(_node_lineage_name(source) if source is not None else None)
                except Exception as exc:
                    errors.append(f"{node_name}:input enumeration:{exc}")
            dependency_reader = getattr(node, "dependencies", None)
            dependency_flags = [
                getattr(nuke, name, None)
                for name in ("INPUTS", "HIDDEN_INPUTS", "EXPRESSIONS")
            ]
            if not callable(dependency_reader) or any(flag is None for flag in dependency_flags):
                errors.append(f"{node_name}:hidden dependency enumeration unavailable")
            else:
                try:
                    flags = 0
                    for flag in dependency_flags:
                        flags |= int(flag)
                    dependencies = sorted(
                        _node_lineage_name(source)
                        for source in dependency_reader(flags)
                    )
                except Exception as exc:
                    errors.append(f"{node_name}:hidden dependency enumeration:{exc}")
        try:
            node_class = str(node.Class())
        except Exception:
            node_class = ""
        record_nodes.append(node)
        records.append(
            {
                "name": node_name,
                "context": node_name.rsplit(".", 1)[0] if "." in node_name else "Root",
                "class": node_class,
                "knobs": knobs,
                "connections": connections,
                "dependencies": dependencies,
            }
        )
    task_records = [
        record for node, record in zip(record_nodes, records)
        if node is not root and task_id and _metadata(node, "bridge_task_id") == task_id
    ]
    non_task_records = [
        record for node, record in zip(record_nodes, records)
        if node is not root and (not task_id or _metadata(node, "bridge_task_id") != task_id)
    ]
    global_records = [
        record for node, record in zip(record_nodes, records)
        if node is root
    ]
    fingerprint = _canonical_payload_sha256(records) if not errors else ""
    return {
        "scene_fingerprint": fingerprint,
        "task_scene_fingerprint": _canonical_payload_sha256(task_records) if not errors else "",
        "non_task_scene_fingerprint": _canonical_payload_sha256(non_task_records) if not errors else "",
        "global_scene_fingerprint": _canonical_payload_sha256(global_records) if not errors else "",
        "fingerprint_complete": not errors and bool(records),
        "fingerprint_errors": errors[:20],
    }


def _post_scene_state(task_id: str = "") -> dict[str, Any]:
    import nuke

    try:
        modified = nuke.modified()
    except Exception:
        modified = None
    return {
        "script": str(nuke.root().name() or ""),
        "modified": modified if type(modified) is bool else None,
        **_nuke_scene_fingerprint(task_id),
    }


def _manifest_dir() -> Path:
    explicit = os.environ.get("NUKE_BRIDGE_INSTANCES_DIR")
    if explicit:
        return Path(explicit).expanduser()
    configured = os.environ.get("NUKE_PATH", "")
    for entry in configured.split(os.pathsep):
        entry = entry.strip()
        if entry and entry != "&":
            return Path(entry).expanduser() / "nuke_bridge_instances"
    return Path.home() / ".nuke" / "nuke_bridge_instances"


def _path_has_symlink(path: Path) -> bool:
    current = path.absolute()
    while True:
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _ensure_secure_manifest_dir(directory: Path) -> None:
    """Create the private state directory without following symlinks."""

    directory = directory.absolute()
    if _path_has_symlink(directory):
        raise RuntimeError("Nuke Bridge state directory must not traverse a symlink")
    ancestor = directory
    while True:
        try:
            ancestor_info = ancestor.lstat()
            break
        except FileNotFoundError:
            if ancestor.parent == ancestor:
                raise RuntimeError("Nuke Bridge state directory has no existing trusted parent")
            ancestor = ancestor.parent
    if ancestor.is_symlink() or not stat.S_ISDIR(ancestor_info.st_mode):
        raise RuntimeError("Nuke Bridge state parent must be a real directory")
    if os.name != "nt" and (
        ancestor_info.st_uid != os.getuid() or stat.S_IMODE(ancestor_info.st_mode) & 0o022
    ):
        raise RuntimeError("Nuke Bridge state parent must be owner-controlled")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'nt':
        from dcc_task_runtime.platform_support import set_private_permissions
        set_private_permissions(directory)
    info = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("Nuke Bridge state directory must be a real directory")
    if os.name != "nt" and (
        info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise RuntimeError("Nuke Bridge state directory must be owner-controlled")


def _write_private_file_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        if os.name == 'nt':
            from dcc_task_runtime.platform_support import open_private_file
            descriptor = open_private_file(path,flags)
        else:
            descriptor = os.open(str(path), flags, 0o600)
        created = True
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("short write while creating private Nuke Bridge state")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise RuntimeError("Nuke Bridge private state file is not regular")
        if os.name != "nt" and (
            info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise RuntimeError("Nuke Bridge private state file must be owner-only")
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def _validate_token(token: str) -> str:
    normalized = str(token)
    if len(normalized) < _MIN_TOKEN_LENGTH:
        raise ValueError("Nuke Bridge token must contain at least 32 characters")
    try:
        normalized.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Nuke Bridge token must be ASCII") from exc
    if any(character.isspace() for character in normalized):
        raise ValueError("Nuke Bridge token must not contain whitespace")
    return normalized


def _success(data: Any) -> dict[str, Any]:
    return {"status": "success", "data": data}


def _error(
    code: str,
    message: str,
    *,
    indeterminate: bool | None = None,
) -> dict[str, Any]:
    error = {"code": code, "message": message}
    if indeterminate is not None:
        error["indeterminate"] = bool(indeterminate)
    return {"status": "error", "error": error}


def _run_main(callback):
    import nuke

    executor = _TASK_HOST_EXECUTOR or getattr(nuke, "executeInMainThreadWithResult", None)
    if executor is None:
        return callback()

    # Nuke 17 can queue this callback and return ``None`` from a socket
    # worker.  Keep the callback's result separate from the executor's return
    # value, and guard the pending-to-running transition so a timed-out
    # callback cannot mutate a later request's scene.
    lock = threading.Lock()
    state: dict[str, Any] = {
        "phase": "pending",
        "value": None,
        "value_set": False,
        "failure": None,
    }
    completed = threading.Event()

    def wrapped():
        with lock:
            if state["phase"] != "pending":
                # The socket worker already returned a timeout.  Nuke may
                # still deliver a queued callback; never run the DCC action
                # after the bridge has cancelled it.
                completed.set()
                return None
            state["phase"] = "running"
        try:
            value = callback()
            with lock:
                state["value"] = value
                state["value_set"] = True
                if state["phase"] == "running":
                    state["phase"] = "completed"
            return value
        except BaseException as exc:
            with lock:
                state["failure"] = exc
                if state["phase"] == "running":
                    state["phase"] = "failed"
            raise
        finally:
            completed.set()

    try:
        executor(wrapped)
    except BaseException as exc:
        with lock:
            failure = state["failure"]
        raise failure or exc

    # The event is set by the wrapper even when the callback legitimately
    # returns None.  Do not use the executor result as a success signal when
    # the wrapper is still pending.
    if not completed.is_set() and not completed.wait(timeout=_MAIN_THREAD_TIMEOUT_SECONDS):
        with lock:
            phase = state["phase"]
            if phase == "pending":
                state["phase"] = "timed_out_pending"
                indeterminate = False
            elif phase == "running":
                state["phase"] = "timed_out_running"
                indeterminate = True
            else:
                # The callback can finish between Event.wait() returning
                # false and this lock acquisition.  Its terminal state is
                # authoritative, so continue to the result readback below.
                indeterminate = None
        if indeterminate is not None:
            raise _MainThreadTimeoutError(indeterminate=indeterminate)

    with lock:
        failure = state["failure"]
        value_set = bool(state["value_set"])
        value = state["value"]
    if failure:
        raise failure
    if value_set:
        return value

    # A compliant executor invokes the wrapper.  Reaching this branch means
    # it signalled completion without doing so; returning its possibly-None
    # value would turn an incomplete request into a false success.
    raise RuntimeError(
        "Nuke main-thread executor completed without invoking the callback"
    )


def _node(name: str):
    import nuke

    node = nuke.root() if name == "Root" else nuke.toNode(name)
    if node is None:
        raise ValueError(f"node not found: {name}")
    return node


def _node_observation(node, nuke) -> dict[str, Any]:
    """Keep native knob values typed, bounded and explicitly JSON representable."""
    remaining = [8192, 1024 * 1024]

    def observe(value, field, depth=0):
        remaining[0] -= 1
        if depth > 8 or remaining[0] < 0:
            raise ValueError("NODE_OBSERVATION_TOO_LARGE: " + field[:180])
        kind = type(value)
        if value is None or kind is bool:
            return value
        if kind is int:
            if value.bit_length() > 64:
                raise ValueError("NODE_OBSERVATION_INTEGER_OUT_OF_RANGE: " + field[:180])
            return value
        if kind is float:
            if not math.isfinite(value):
                raise ValueError("NODE_OBSERVATION_NONFINITE_VALUE: " + field[:180])
            return value
        if kind is str:
            remaining[1] -= len(value.encode("utf-8"))
            if len(value) > 65536 or remaining[1] < 0:
                raise ValueError("NODE_OBSERVATION_TOO_LARGE: " + field[:180])
            return value
        format_type = getattr(nuke, "Format", None)
        if isinstance(format_type, type) and isinstance(value, format_type):
            fields = {"native_type": "nuke.Format"}
            for name in ("name", "width", "height", "x", "y", "r", "t", "pixelAspect"):
                actual = getattr(value, name)()
                expected = str if name == "name" else float if name == "pixelAspect" else int
                if type(actual) is not expected and not (name == "name" and actual is None):
                    raise ValueError("NODE_OBSERVATION_FORMAT_TYPE_INVALID: " + field[:180] + "." + name)
                fields[name] = actual
            return observe(fields, field, depth + 1)
        if kind in (list, tuple):
            if len(value) > 1024:
                raise ValueError("NODE_OBSERVATION_TOO_LARGE: " + field[:180])
            return [observe(item, field + "[]", depth + 1) for item in value]
        if kind is dict:
            if len(value) > 1024 or any(type(key) is not str for key in value):
                raise ValueError("NODE_OBSERVATION_DICTIONARY_INVALID: " + field[:180])
            return {observe(key, field, depth + 1): observe(item, field + "." + key[:80], depth + 1)
                    for key, item in value.items()}
        raise ValueError("NODE_OBSERVATION_TYPE_UNSUPPORTED: " + field[:180] + " (" + kind.__name__[:80] + ")")

    knobs = node.knobs()
    if type(knobs) is not dict or len(knobs) > 1024:
        raise ValueError("NODE_OBSERVATION_KNOBS_INVALID")
    values = {}
    for name, knob in knobs.items():
        if type(name) is not str:
            raise ValueError("NODE_OBSERVATION_KNOB_NAME_INVALID")
        values[observe(name, "knob_name")] = observe(knob.value(), "knobs." + name[:80])
    count = node.inputs()
    if type(count) is not int or not 0 <= count <= 64:
        raise ValueError("NODE_OBSERVATION_INPUTS_INVALID")
    result = observe({"name": node.name(), "class": node.Class(),
                      "inputs": [source.name() if source is not None else None
                                 for source in (node.input(index) for index in range(count))]}, "node")
    result["knobs"] = values
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("NODE_OBSERVATION_TOO_LARGE")
    return result


def _safe_nuke_run(code: str) -> dict[str, Any]:
    import nuke

    tree = ast.parse(code, mode="exec")
    for item in ast.walk(tree):
        if isinstance(item, ast.Import) and any(alias.name.split(".")[0] not in _ALLOWED_IMPORTS for alias in item.names):
            raise ValueError("import is not allowlisted")
        if isinstance(item, ast.ImportFrom) and (item.module or "").split(".")[0] not in _ALLOWED_IMPORTS:
            raise ValueError("import is not allowlisted")
        if isinstance(item, ast.Name) and item.id in _FORBIDDEN_NAMES:
            raise ValueError(f"forbidden name: {item.id}")
        if isinstance(item, ast.Attribute) and item.attr.startswith("__"):
            raise ValueError("dunder attributes are forbidden")
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if root not in _ALLOWED_IMPORTS:
            raise ImportError("import is not allowlisted")
        return builtins.__import__(name, globals, locals, fromlist, level)

    scope = {"nuke": nuke, "__builtins__": {"True": True, "False": False, "None": None, "len": len, "range": range, "str": str, "int": int, "float": float, "list": list, "dict": dict, "__import__": safe_import}}
    exec(compile(tree, "<nuke-bridge>", "exec"), scope, scope)
    return {"result": scope.get("result")}


def _frame_path(pattern: str, frame: int) -> Path:
    token = _SEQUENCE_TOKEN.search(pattern)
    if token is not None:
        placeholder = token.group(0)
        if placeholder.startswith("%"):
            replacement = placeholder % frame
        else:
            replacement = f"{frame:0{len(placeholder)}d}"
        return Path(pattern[: token.start()] + replacement + pattern[token.end() :])
    return Path(pattern)


def _verify(pattern: str, first: int, last: int, min_size_kb: int = 1, stride: int = 1,
            not_before: "float | None" = None, frames: "list[int] | None" = None) -> dict[str, Any]:
    """Frame-set verification with existence, size AND freshness.

    ``not_before`` (epoch seconds) excludes frames that predate this render:
    a file merely existing is never proof that THIS render produced it.
    """
    missing = []
    too_small = []
    stale_frames = []
    unreadable = []
    decoded_pixels: dict[int, int] = {}
    stride = max(1, int(stride))
    expected = list(frames) if frames is not None else list(range(first, last + 1, stride))
    for frame in expected:
        path = _frame_path(pattern, frame)
        if not path.is_file():
            missing.append(frame)
        elif path.stat().st_size < min_size_kb * 1024:
            too_small.append(frame)
        else:
            if path.suffix.lower() == ".exr":
                try:
                    from dcc_task_runtime.exr_codec import read_exr
                    decoded = read_exr(path)
                    decoded_pixels[frame] = int(decoded.get("pixel_count") or 0)
                except (OSError, ValueError, ImportError):
                    unreadable.append(frame)
            if not_before is not None and path.stat().st_mtime < not_before:
                stale_frames.append(frame)
    return {
        "ok": not missing and not too_small and not unreadable,
        "fresh": not stale_frames,
        "missing": missing,
        "too_small": too_small,
        "unreadable": unreadable,
        "decoded_pixels": decoded_pixels,
        "stale_frames": stale_frames,
        "first": first,
        "last": last,
        "stride": stride,
        "expected_frames": expected,
    }


def _artifact(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def _snapshot_frames(pattern: str, frames: list[int]) -> dict[str, dict[str, Any]]:
    """Capture the exact pre-render state for freshness verification."""

    snapshots: dict[str, dict[str, Any]] = {}
    for frame in frames:
        path = _frame_path(pattern, frame)
        snapshots[str(frame)] = _artifact(path) if path.is_file() else {}
    return snapshots


def _stale_frames(
    pattern: str,
    frames: list[int],
    before: dict[str, dict[str, Any]] | None,
    produced: dict[str, dict[str, Any]] | None = None,
) -> list[int]:
    """Return frames without a complete, unchanged before/produced identity."""

    snapshots = before or {}
    produced_snapshots = produced or {}
    stale: list[int] = []
    for frame in frames:
        key = str(frame)
        if key not in snapshots or (produced is not None and key not in produced_snapshots):
            stale.append(frame)
            continue
        previous = snapshots.get(key) or {}
        rendered = produced_snapshots.get(key) or {}
        path = _frame_path(pattern, frame)
        if not path.is_file():
            continue
        current = _artifact(path)
        if previous and current["modified_ns"] <= int(previous.get("modified_ns") or 0):
            stale.append(frame)
            continue
        if produced is not None and (
            not rendered
            or any(
                current.get(name) != rendered.get(name)
                for name in ("bytes", "modified_ns", "sha256")
            )
        ):
            stale.append(frame)
    return stale


def _readable_frame_metadata(pattern: str, frames: list[int]) -> tuple[dict[str, Any], list[int]]:
    """Re-open every expected frame through Nuke and report unreadable frames."""

    metadata_by_frame: dict[str, Any] = {}
    unreadable: list[int] = []
    for frame in frames:
        path = _frame_path(pattern, frame)
        if not path.is_file():
            continue
        metadata = _read_image_metadata(path)
        metadata_by_frame[str(frame)] = metadata
        if metadata.get("error"):
            unreadable.append(frame)
    return metadata_by_frame, unreadable


def _values_match(requested: Any, actual: Any) -> bool:
    """Compare Nuke knob readback without accepting clamp or coercion drift."""

    if isinstance(requested, bool):
        return (
            isinstance(actual, (bool, int))
            and int(actual) in (0, 1)
            and bool(actual) is requested
        )
    if isinstance(requested, int) and not isinstance(requested, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and float(actual).is_integer() and int(actual) == requested
    if isinstance(requested, float):
        try:
            return math.isclose(float(actual), requested, rel_tol=1e-6, abs_tol=1e-7)
        except (TypeError, ValueError):
            return False
    if isinstance(requested, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(requested) != len(actual):
            return False
        return all(_values_match(left, right) for left, right in zip(requested, actual))
    return actual == requested


def _read_image_metadata(path: Path) -> dict[str, Any]:
    """Re-open one rendered frame through Nuke's reader for host-level proof."""
    import nuke

    reader = None
    try:
        reader = nuke.nodes.Read(file=str(path))
        metadata = {
            "width": int(reader.width()),
            "height": int(reader.height()),
            "channels": list(reader.channels()),
        }
        return metadata
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if reader is not None:
            try:
                nuke.delete(reader)
            except Exception:
                pass


def _set_knob(node, knob_name: str, value: Any) -> Any:
    knob = node.knob(knob_name)
    if knob is None:
        raise ValueError(f"knob not found: {node.name()}.{knob_name}")
    if isinstance(value, dict) and "animated" in value:
        knob.setAnimated()
        for frame, item in value["animated"]:
            knob.setValueAt(item, int(frame))
    else:
        knob.setValue(value)
    return knob.value()


def _task_key(task_id: str) -> str:
    key = "".join(character for character in task_id.lower() if character in "0123456789abcdef")[:16]
    if not task_id:
        raise ValueError("task_id is required")
    return key if len(key) >= 12 else hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]


def _delivery_input_item(params: dict[str, Any]) -> dict[str, Any]:
    for item in params.get("inputs") or []:
        if isinstance(item, dict) and item.get("path"):
            return dict(item)
    candidate = (params.get("constraints") or {}).get("input_path")
    if candidate:
        return {"role": "effect_render", "path": str(candidate)}
    raise ValueError("nuke.render_delivery requires an EXR input path in inputs[].path or constraints.input_path")


def _delivery_input(params: dict[str, Any]) -> str:
    return str(_delivery_input_item(params)["path"])


def _delivery_output_dir(params: dict[str, Any]) -> Path:
    configured = str((params.get("render") or {}).get("output_dir") or "").strip()
    if configured:
        directory = Path(configured).expanduser()
    else:
        import nuke

        try:
            script = Path(nuke.root().name())
        except Exception:
            script = Path.cwd() / "untitled.nk"
        directory = (script.parent if script.suffix else Path.cwd()) / "nuke_delivery" / _task_key(str(params.get("task_id")))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


_COMPOSITE_INPUT_ROLES = {"effect_render", "plate", "reference", "matte", "depth", "vector"}
_BRIDGE_METADATA = {
    "bridge_task_id",
    "bridge_input_role",
    "bridge_component_id",
    "bridge_graph_role",
    "bridge_schema_version",
    "bridge_state_json",
    "bridge_capability",
}


def _metadata(node, name: str) -> str:
    knob = node.knob(name)
    if knob is None:
        return ""
    value = knob.value()
    return "" if value is None else str(value)


def _set_hidden_metadata(node, name: str, value: Any) -> None:
    import nuke

    if name not in _BRIDGE_METADATA:
        raise ValueError(f"unsupported bridge metadata field: {name}")
    knob = node.knob(name)
    if knob is None:
        knob = nuke.String_Knob(name, name)
        try:
            knob.setVisible(False)
        except Exception:
            pass
        node.addKnob(knob)
    knob.setValue(str(value))


def _tag_node(
    node,
    task_id: str,
    *,
    input_role: str = "",
    component_id: str = "",
    graph_role: str = "",
    schema_version: str = "2.0",
    capability: str = "native",
) -> None:
    _set_hidden_metadata(node, "bridge_task_id", task_id)
    _set_hidden_metadata(node, "bridge_input_role", input_role)
    _set_hidden_metadata(node, "bridge_component_id", component_id)
    _set_hidden_metadata(node, "bridge_graph_role", graph_role)
    _set_hidden_metadata(node, "bridge_schema_version", schema_version)
    _set_hidden_metadata(node, "bridge_capability", capability)


def _set_supported_knob(node, names: list[str], value: Any) -> str | None:
    for name in names:
        if node.knob(name) is not None:
            _set_knob(node, name, value)
            return name
    return None


def _native_node(node_class: str, name: str, inputs: list[Any] | None = None):
    import nuke

    node = nuke.createNode(node_class, inpanel=False)
    try:
        try:
            node.setName(name)
        except Exception:
            pass
        for index, source in enumerate(inputs or []):
            node.setInput(index, source)
    except Exception:
        try:
            nuke.delete(node)
        except Exception:
            pass
        raise
    return node


def _optional_native_node(classes: list[str], name: str, source, requested: bool):
    last_error: Exception | None = None
    for node_class in classes:
        try:
            return _native_node(node_class, name, [source]), node_class
        except Exception as exc:
            last_error = exc
    if requested:
        raise RuntimeError(f"requested native node is unavailable ({'/'.join(classes)}): {last_error}")
    return _native_node("NoOp", name, [source]), "NoOp"


def _composite_inputs(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for raw in params.get("inputs") or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in _COMPOSITE_INPUT_ROLES:
            raise ValueError(
                "nuke.reference_composite input role must be one of: "
                + ", ".join(sorted(_COMPOSITE_INPUT_ROLES))
            )
        if role in indexed:
            raise ValueError(f"duplicate composite input role: {role}")
        path = str(raw.get("path") or "").strip()
        if not path:
            raise ValueError(f"composite input role {role} requires path")
        indexed[role] = dict(raw)
    if "effect_render" not in indexed:
        raise ValueError("nuke.reference_composite requires input role effect_render")
    return indexed


def _canonical_payload_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _declared_sha256(value: Any, label: str, *, required: bool) -> str:
    rendered = str(value or "").strip().lower()
    if not rendered:
        if required:
            raise ValueError(f"INPUT_SOURCE_IDENTITY_REQUIRED:{label}")
        return ""
    if re.fullmatch(r"[0-9a-f]{64}", rendered) is None:
        raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{label}")
    return rendered


def _local_source_artifact(value: str, label: str) -> dict[str, Any]:
    rendered = os.path.expandvars(str(value or "")).strip()
    candidate = Path(rendered).expanduser()
    if not rendered or candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError(f"INPUT_SOURCE_HASH_MISMATCH:{label}")
    artifact = _artifact(candidate.resolve())
    return {
        "path": str(Path(str(artifact["path"])).resolve()),
        "bytes": int(artifact["bytes"]),
        "sha256": str(artifact["sha256"]),
    }


def _capture_composite_input_identity(
    role: str,
    item: dict[str, Any],
    *,
    strict: bool,
    expected_frames: list[int] | None = None,
) -> dict[str, Any]:
    """Freeze one explicit input without guessing unlisted sequence frames."""

    source_pattern = str(item.get("path") or "").strip()
    raw_frames = item.get("frames")
    if raw_frames is None:
        if strict and _sequence_descriptor(source_pattern) is not None:
            raise ValueError(f"INPUT_SOURCE_IDENTITY_REQUIRED:{role}:frames")
        declared = _declared_sha256(item.get("sha256"), role, required=strict)
        if not declared:
            return {
                "mode": "unfrozen",
                "status": "unfrozen_legacy",
                "declared_sha256": "",
            }
        artifact = _local_source_artifact(source_pattern, role)
        if not hmac.compare_digest(artifact["sha256"], declared):
            raise RuntimeError(f"INPUT_SOURCE_HASH_MISMATCH:{role}")
        return {
            "mode": "static",
            "status": "frozen",
            "declared_sha256": declared,
            "path": artifact["path"],
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
        }

    if not isinstance(raw_frames, (list, tuple)) or not raw_frames:
        raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{role}:frames")
    if len(raw_frames) > _MAX_COMPOSITE_FRAME_COUNT:
        raise ValueError(
            "REFERENCE_FRAME_RANGE_LIMIT_EXCEEDED: declared {} frames; maximum is {}".format(
                len(raw_frames),
                _MAX_COMPOSITE_FRAME_COUNT,
            )
        )
    descriptor = _sequence_descriptor(source_pattern)
    if descriptor is None:
        raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{role}:sequence_pattern")
    normalized_frames: list[dict[str, Any]] = []
    seen_frames: set[int] = set()
    for index, raw in enumerate(raw_frames):
        if not isinstance(raw, dict):
            raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{role}:frame_{index}")
        frame = int(raw.get("frame", index))
        if frame in seen_frames:
            raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{role}:duplicate_frame_{frame}")
        seen_frames.add(frame)
        frame_path = str(raw.get("path") or raw.get("uri") or "").strip()
        expected_path = str(_frame_path(source_pattern, frame))
        if not (
            _same_existing_media_file(expected_path, frame_path)
            or _symbolic_sequence_key(_canonical_media_path(expected_path))
            == _symbolic_sequence_key(_canonical_media_path(frame_path))
        ):
            raise ValueError(f"INPUT_SOURCE_IDENTITY_INVALID:{role}:frame_path_{frame}")
        declared_frame = _declared_sha256(
            raw.get("sha256"),
            f"{role}:frame_{frame}",
            required=True,
        )
        artifact = _local_source_artifact(frame_path, f"{role}:frame_{frame}")
        if not hmac.compare_digest(artifact["sha256"], declared_frame):
            raise RuntimeError(f"INPUT_SOURCE_HASH_MISMATCH:{role}:frame_{frame}")
        normalized_frames.append(
            {
                "index": index,
                "frame": frame,
                "uri": artifact["path"],
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
            }
        )
    if expected_frames is not None:
        actual_frames = [int(item["frame"]) for item in normalized_frames]
        if actual_frames != list(expected_frames):
            raise ValueError(
                "INPUT_SOURCE_IDENTITY_INVALID:{}:frame_coverage".format(role)
            )
    manifest_sha256 = _canonical_payload_sha256(normalized_frames)
    declared_manifest = _declared_sha256(item.get("sha256"), role, required=strict)
    if declared_manifest and not hmac.compare_digest(manifest_sha256, declared_manifest):
        raise RuntimeError(f"INPUT_SOURCE_HASH_MISMATCH:{role}:manifest")
    return {
        "mode": "sequence",
        "status": "frozen",
        "declared_sha256": declared_manifest,
        "manifest_sha256": manifest_sha256,
        "frames": normalized_frames,
    }


def _capture_composite_input_identities(
    inputs: dict[str, dict[str, Any]],
    *,
    strict: bool,
    expected_frames: list[int] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        role: _capture_composite_input_identity(
            role,
            item,
            strict=strict,
            expected_frames=expected_frames,
        )
        for role, item in sorted(inputs.items())
    }


def _revalidate_composite_input_identity(
    role: str,
    frozen_path: str,
    identity: Any,
    *,
    strict: bool,
    expected_frames: list[int] | None = None,
) -> dict[str, Any]:
    evidence = {
        "status": "invalid",
        "mode": "",
        "matched": False,
    }
    if not isinstance(identity, dict):
        evidence["error"] = "identity_missing"
        return evidence
    mode = str(identity.get("mode") or "")
    evidence.update({"status": str(identity.get("status") or ""), "mode": mode})
    if mode == "unfrozen":
        matched = not strict and evidence["status"] == "unfrozen_legacy"
        evidence.update({"matched": matched, "error": "" if matched else "identity_required"})
        return evidence
    try:
        if mode == "static":
            expected = _declared_sha256(identity.get("sha256"), role, required=True)
            artifact = _local_source_artifact(frozen_path, role)
            matched = hmac.compare_digest(expected, artifact["sha256"])
            evidence.update({"matched": matched, "actual": artifact})
            return evidence
        if mode == "sequence":
            raw_frames = identity.get("frames")
            if not isinstance(raw_frames, list) or not raw_frames:
                evidence["error"] = "frame_manifest_missing"
                return evidence
            requested = {
                "path": frozen_path,
                "sha256": str(identity.get("manifest_sha256") or ""),
                "frames": [
                    {
                        "frame": int(frame.get("frame", index)),
                        "path": str(frame.get("uri") or frame.get("path") or ""),
                        "sha256": str(frame.get("sha256") or ""),
                    }
                    for index, frame in enumerate(raw_frames)
                    if isinstance(frame, dict)
                ],
            }
            if len(requested["frames"]) != len(raw_frames):
                evidence["error"] = "frame_manifest_invalid"
                return evidence
            current = _capture_composite_input_identity(
                role,
                requested,
                strict=True,
                expected_frames=expected_frames,
            )
            expected_manifest = str(identity.get("manifest_sha256") or "")
            matched = (
                hmac.compare_digest(str(current.get("manifest_sha256") or ""), expected_manifest)
                and current.get("frames") == raw_frames
            )
            evidence.update(
                {
                    "matched": matched,
                    "manifest_sha256": current.get("manifest_sha256"),
                    "frame_count": len(raw_frames),
                }
            )
            return evidence
    except (RuntimeError, ValueError) as exc:
        evidence["error"] = str(exc)
        return evidence
    evidence["error"] = "identity_mode_invalid"
    return evidence


def _resolved_composite_output_dir(params: dict[str, Any]) -> Path:
    configured = str((params.get("render") or {}).get("output_dir") or "").strip()
    if configured:
        directory = Path(configured).expanduser()
    else:
        directory = _delivery_output_dir(params).parent / "reference_composite" / _task_key(str(params.get("task_id")))
    return directory.resolve(strict=False)


def _composite_output_dir(params: dict[str, Any]) -> Path:
    directory = _resolved_composite_output_dir(params)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _node_lineage_name(node) -> str:
    """Return a group-qualified name when the host exposes one."""

    full_name = getattr(node, "fullName", None)
    if callable(full_name):
        try:
            value = str(full_name() or "").strip()
            if value:
                return value
        except Exception:
            pass
    return str(node.name())


def _node_class_name(node) -> str:
    node_class = getattr(node, "Class", None)
    if not callable(node_class):
        return ""
    try:
        return str(node_class() or "")
    except Exception:
        return ""


def _opaque_lineage_wrapper(node) -> bool:
    """Conservatively identify wrappers whose internals are not audited."""

    node_class = _node_class_name(node)
    lowered = node_class.casefold()
    if lowered in {"group", "gizmo", "livegroup", "precomp"}:
        return True
    if lowered.endswith(("group", "gizmo")):
        return True
    # Custom gizmos frequently expose a group-like API while reporting their
    # registered gizmo class rather than the literal ``Gizmo`` class.
    return callable(getattr(node, "nodes", None)) or callable(getattr(node, "begin", None))


def _inspect_upstream_nodes(node) -> tuple[list[Any], list[dict[str, str]]]:
    """Traverse visible and hidden dependencies without name-based aliasing."""

    result: list[Any] = []
    inspection_failures: list[dict[str, str]] = []
    pending = [node]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(current)

        try:
            input_count = int(current.inputs())
            for index in range(input_count):
                source = current.input(index)
                if source is not None:
                    pending.append(source)
        except Exception as exc:
            inspection_failures.append(
                {
                    "node": _node_lineage_name(current),
                    "reason": "input_inspection_failed",
                    "error": str(exc),
                }
            )

        dependencies = getattr(current, "dependencies", None)
        if not callable(dependencies):
            continue
        try:
            import nuke

            flags = 0
            for flag_name in ("INPUTS", "HIDDEN_INPUTS", "EXPRESSIONS"):
                flags |= int(getattr(nuke, flag_name, 0) or 0)
            hidden_sources = dependencies(flags) if flags else dependencies()
            for source in hidden_sources or []:
                if source is not None:
                    pending.append(source)
        except Exception as exc:
            inspection_failures.append(
                {
                    "node": _node_lineage_name(current),
                    "reason": "dependency_inspection_failed",
                    "error": str(exc),
                }
            )
    return result, inspection_failures


def _upstream_nodes(node) -> list[Any]:
    """Compatibility wrapper for callers that only need the node list."""

    return _inspect_upstream_nodes(node)[0]


def _canonical_media_path(value: str) -> str:
    expanded = os.path.expandvars(str(value or "")).strip()
    if not expanded:
        return ""
    return os.path.normcase(str(Path(expanded).expanduser().resolve(strict=False)))


def _same_existing_media_file(left: str, right: str) -> bool:
    left_value = os.path.expandvars(str(left or "")).strip()
    right_value = os.path.expandvars(str(right or "")).strip()
    if not left_value or not right_value:
        return False
    left_path = Path(left_value).expanduser()
    right_path = Path(right_value).expanduser()
    try:
        return left_path.exists() and right_path.exists() and os.path.samefile(left_path, right_path)
    except OSError:
        return False


def _symbolic_sequence_key(value: str) -> str:
    return value.casefold() if sys.platform == "darwin" else value


def _validated_composite_frame_range(frame_range: dict[str, Any] | None) -> tuple[int, int, int, int]:
    raw_range = frame_range or {}
    start = int(raw_range.get("start", 1))
    end = int(raw_range.get("end", start))
    step = int(raw_range.get("step", 1))
    if step <= 0:
        raise ValueError("COMPOSITE_FRAME_RANGE_INVALID: step must be greater than zero")
    if end < start:
        raise ValueError("COMPOSITE_FRAME_RANGE_INVALID: end must not be less than start")
    count = ((end - start) // step) + 1
    if count > _MAX_COMPOSITE_FRAME_COUNT:
        raise ValueError(
            "REFERENCE_FRAME_RANGE_LIMIT_EXCEEDED: declared {} frames; maximum is {}".format(
                count,
                _MAX_COMPOSITE_FRAME_COUNT,
            )
        )
    return start, end, step, count


def _sequence_descriptor(value: str) -> tuple[str, str, str] | None:
    canonical = _canonical_media_path(value)
    matches = list(_SEQUENCE_TOKEN.finditer(canonical))
    if len(matches) != 1:
        return None
    token = matches[0]
    return canonical[: token.start()], canonical[token.end() :], canonical


def _sequence_contains(pattern: str, concrete: str, frame_range: dict[str, Any] | None) -> bool:
    _validated_composite_frame_range(frame_range)
    descriptor = _sequence_descriptor(pattern)
    if descriptor is None:
        return False
    prefix, suffix, canonical_pattern = descriptor
    canonical_concrete = _canonical_media_path(concrete)
    flags = re.IGNORECASE if sys.platform == "darwin" else 0
    match = re.fullmatch(
        re.escape(prefix) + r"(-?[0-9]+)" + re.escape(suffix),
        canonical_concrete,
        flags=flags,
    )
    if match is None:
        return False
    frame = int(match.group(1))
    generated = _canonical_media_path(str(_frame_path(canonical_pattern, frame)))
    return _symbolic_sequence_key(generated) == _symbolic_sequence_key(canonical_concrete)


def _media_source_binding_matches(frozen: str, actual: str) -> bool:
    """Compare one frozen Read source with its live knob readback.

    Static paths must identify the same path/file.  Sequence expressions must
    remain sequence expressions and produce the same symbolic path family;
    this permits equivalent ``%04d``/``####`` spelling without accepting a
    single concrete frame as a replacement for a frozen sequence.
    """

    canonical_frozen = _canonical_media_path(frozen)
    canonical_actual = _canonical_media_path(actual)
    if not canonical_frozen or not canonical_actual:
        return False
    frozen_descriptor = _sequence_descriptor(frozen)
    actual_descriptor = _sequence_descriptor(actual)
    if (frozen_descriptor is None) != (actual_descriptor is None):
        return False
    if frozen_descriptor is None and actual_descriptor is None:
        return (
            _same_existing_media_file(frozen, actual)
            or _symbolic_sequence_key(canonical_frozen)
            == _symbolic_sequence_key(canonical_actual)
        )
    if frozen_descriptor is None or actual_descriptor is None:
        return False
    if tuple(_symbolic_sequence_key(item) for item in frozen_descriptor[:2]) != tuple(
        _symbolic_sequence_key(item) for item in actual_descriptor[:2]
    ):
        return False
    # Compare formatting behavior rather than token spelling.  This keeps
    # #### equivalent to %04d while distinguishing %d and %04d.
    return all(
        _symbolic_sequence_key(
            _canonical_media_path(str(_frame_path(frozen_descriptor[2], frame)))
        )
        == _symbolic_sequence_key(
            _canonical_media_path(str(_frame_path(actual_descriptor[2], frame)))
        )
        for frame in (-1, 0, 1, 12, 12345)
    )


def _media_paths_overlap(left: str, right: str, frame_range: dict[str, Any] | None = None) -> bool:
    _validated_composite_frame_range(frame_range)
    if _same_existing_media_file(left, right):
        return True
    canonical_left = _canonical_media_path(left)
    canonical_right = _canonical_media_path(right)
    if not canonical_left or not canonical_right:
        return False
    if canonical_left == canonical_right:
        return True
    left_descriptor = _sequence_descriptor(left)
    right_descriptor = _sequence_descriptor(right)
    if left_descriptor is not None and right_descriptor is not None:
        # Treat equivalent sequence locations as overlapping even when their
        # padding syntax differs.  A false positive is safer than allowing a
        # reference branch into the final Write graph.
        return tuple(_symbolic_sequence_key(item) for item in left_descriptor[:2]) == tuple(
            _symbolic_sequence_key(item) for item in right_descriptor[:2]
        )
    if left_descriptor is not None:
        return _sequence_contains(left, right, frame_range)
    if right_descriptor is not None:
        return _sequence_contains(right, left, frame_range)
    return False


def _media_path_variants(value: str, frame_range: dict[str, Any] | None = None) -> set[str]:
    # Retained as a compatibility helper, but deliberately compact: lineage
    # now compares sequence patterns symbolically instead of allocating one
    # path per declared frame.
    _validated_composite_frame_range(frame_range)
    canonical = _canonical_media_path(value)
    return {canonical} if canonical else set()


def _matches_frozen_reference_content(
    identity: Any,
    rendered_file: str,
) -> dict[str, Any]:
    evidence = {
        "matched": False,
        "checked_paths": [],
        "matched_paths": [],
        "untrusted_symlink_paths": [],
    }
    if not isinstance(identity, dict) or str(identity.get("status") or "") != "frozen":
        return evidence
    mode = str(identity.get("mode") or "")
    if not rendered_file:
        return evidence

    if mode == "sequence":
        raw_frames = identity.get("frames") or []
        if not isinstance(raw_frames, list) or not raw_frames:
            return evidence
        if _sequence_descriptor(rendered_file) is None:
            path = Path(rendered_file).expanduser()
            evidence["checked_paths"].append(str(path))
            if path.is_symlink():
                evidence["untrusted_symlink_paths"].append(str(path))
                return evidence
            if not path.is_file():
                return evidence
            artifact = _artifact(path)
            candidate_sha256 = str(artifact.get("sha256") or "")
            candidate_bytes = int(artifact.get("bytes") or -1)
            matched_frame = next(
                (
                    {
                        "frame": int(frame.get("frame", index)),
                        "sha256": str(frame.get("sha256") or ""),
                        "bytes": int(frame.get("bytes", -1)),
                    }
                    for index, frame in enumerate(raw_frames)
                    if isinstance(frame, dict)
                    and hmac.compare_digest(
                        candidate_sha256,
                        str(frame.get("sha256") or ""),
                    )
                    and candidate_bytes == int(frame.get("bytes", -1))
                ),
                None,
            )
            evidence["static_candidate"] = {
                "sha256": candidate_sha256,
                "bytes": candidate_bytes,
            }
            evidence["matched_reference_frame"] = matched_frame
            if matched_frame is not None:
                evidence["matched"] = True
                evidence["matched_paths"] = [str(path)]
            return evidence
        expected_manifest = [
            {
                "frame": int(frame.get("frame", index)),
                "sha256": str(frame.get("sha256") or ""),
                "bytes": int(frame.get("bytes", -1)),
            }
            for index, frame in enumerate(raw_frames)
            if isinstance(frame, dict)
        ]
        if len(expected_manifest) != len(raw_frames) or any(
            not item["sha256"] or item["bytes"] < 0 for item in expected_manifest
        ):
            return evidence
        candidate_manifest: list[dict[str, Any]] = []
        for expected_frame in expected_manifest:
            path = _frame_path(rendered_file, int(expected_frame["frame"]))
            evidence["checked_paths"].append(str(path))
            if path.is_symlink():
                evidence["untrusted_symlink_paths"].append(str(path))
                continue
            if not path.is_file():
                continue
            artifact = _artifact(path)
            candidate_manifest.append(
                {
                    "frame": int(expected_frame["frame"]),
                    "sha256": str(artifact["sha256"]),
                    "bytes": int(artifact["bytes"]),
                }
            )
        evidence["expected_manifest"] = expected_manifest
        evidence["candidate_manifest"] = candidate_manifest
        evidence["matched"] = candidate_manifest == expected_manifest
        if evidence["matched"]:
            evidence["matched_paths"] = list(evidence["checked_paths"])
        return evidence

    if mode != "static":
        return evidence
    expected = str(identity.get("sha256") or "")
    if not expected:
        return evidence
    candidate_paths = [Path(rendered_file).expanduser()]
    for path in candidate_paths:
        evidence["checked_paths"].append(str(path))
        # An untagged upstream Read must never use a symlink as a way to make
        # a copied frozen reference opaque to the content-identity check.  Do
        # not resolve and silently trust it: record the source as unauditable
        # so the lineage gate can fail closed.
        if path.is_symlink():
            evidence["untrusted_symlink_paths"].append(str(path))
            continue
        if not path.is_file():
            continue
        digest = str(_artifact(path)["sha256"])
        if hmac.compare_digest(digest, expected):
            evidence["matched_paths"].append(str(path))
    evidence["matched"] = bool(evidence["matched_paths"])
    return evidence


def _audit_composite_lineage(state: dict[str, Any]) -> dict[str, Any]:
    write = _node(str(state.get("write") or ""))
    upstream, inspection_failures = _inspect_upstream_nodes(write)
    frame_range = dict(state.get("frame_range") or {})
    _validated_composite_frame_range(frame_range)
    reference_sources = [str(source) for source in state.get("reference_source_paths") or []]
    reference_identity = (
        (state.get("input_source_identities") or {}).get("reference")
        if isinstance(state.get("input_source_identities"), dict)
        else None
    )
    actual_reference_sources: list[str] = []
    reference_node_name = str((state.get("input_nodes") or {}).get("reference") or "")
    if reference_node_name:
        try:
            reference_node = _node(reference_node_name)
            reference_file = reference_node.knob("file")
            if reference_file is not None and str(reference_file.value() or ""):
                actual_reference_sources.append(str(reference_file.value()))
        except Exception:
            # Topology validation owns the stable fail-closed error for a
            # missing/unreadable bound reference node.  Do not turn that into
            # trusted lineage evidence here.
            pass
    frozen_reference_paths = {
        canonical
        for source in reference_sources
        for canonical in [_canonical_media_path(source)]
        if canonical
    }
    violations: list[str] = []
    violation_details: list[dict[str, Any]] = []
    for node in upstream:
        reasons = []
        if _opaque_lineage_wrapper(node):
            reasons.append("opaque_wrapper_uninspected")
        if _metadata(node, "bridge_input_role") == "reference" or _metadata(node, "bridge_graph_role") == "reference_diagnostic":
            reasons.append("reference_metadata")
        file_knob = node.knob("file")
        rendered_file = str(file_knob.value() or "") if file_knob is not None else ""
        matches_frozen_reference = bool(rendered_file) and any(
            _media_paths_overlap(source, rendered_file, frame_range)
            for source in reference_sources
        )
        if matches_frozen_reference:
            reasons.append("frozen_reference_path")
        if not matches_frozen_reference and rendered_file and any(
            _media_paths_overlap(source, rendered_file, frame_range)
            for source in actual_reference_sources
        ):
            reasons.append("reference_readback_path")
        content_evidence = _matches_frozen_reference_content(
            reference_identity,
            rendered_file,
        )
        if content_evidence["untrusted_symlink_paths"]:
            reasons.append("source_symlink_untrusted")
        if content_evidence["matched"]:
            reasons.append("frozen_reference_content")
        if reasons:
            node_name = _node_lineage_name(node)
            violations.append(node_name)
            violation_details.append(
                {
                    "node": node_name,
                    "reasons": reasons,
                    "file": rendered_file,
                    "reference_content": content_evidence,
                }
            )
    for failure in inspection_failures:
        violations.append(failure["node"])
        violation_details.append(
            {
                "node": failure["node"],
                "reasons": [failure["reason"]],
                "file": "",
                "error": failure["error"],
            }
        )
    violations = sorted(set(violations))
    gate = {
        "name": "reference_isolated_from_final_write",
        "passed": not violations,
        "kind": "verification",
        "write": write.name(),
        "upstream": sorted(_node_lineage_name(node) for node in upstream),
        "violations": violations,
        "violation_details": sorted(violation_details, key=lambda item: item["node"]),
        "frozen_reference_paths": sorted(frozen_reference_paths),
        "reference_readback_paths": sorted(
            {
                canonical
                for source in actual_reference_sources
                for canonical in [_canonical_media_path(source)]
                if canonical
            }
        ),
        "reference_content_identity_checked": bool(
            isinstance(reference_identity, dict)
            and reference_identity.get("status") == "frozen"
        ),
    }
    return {"gates": [gate], "lineage": gate}


def _persist_composite_state(state: dict[str, Any]) -> None:
    write = _node(str(state["write"]))
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
    _set_hidden_metadata(write, "bridge_state_json", encoded)
    if _metadata(write, "bridge_state_json") != encoded:
        raise RuntimeError("STATE_PERSISTENCE_READBACK_MISMATCH: bridge_state_json")
    _COMPOSITES[str(state["task_id"])] = state


def _restore_composite_state(task_id: str) -> dict[str, Any] | None:
    import nuke

    tagged = [node for node in nuke.allNodes(recurseGroups=True) if _metadata(node, "bridge_task_id") == task_id]
    if not tagged:
        return None
    write = next((node for node in tagged if _metadata(node, "bridge_graph_role") == "final_write"), None)
    if write is None:
        return None
    state: dict[str, Any] = {}
    encoded = _metadata(write, "bridge_state_json")
    if encoded:
        try:
            decoded = json.loads(encoded)
            if isinstance(decoded, dict):
                state.update(decoded)
        except json.JSONDecodeError:
            pass
    input_nodes = {
        role: node.name()
        for node in tagged
        for role in [_metadata(node, "bridge_input_role")]
        if role in _COMPOSITE_INPUT_ROLES
        and _metadata(node, "bridge_graph_role") in {f"input_{role}", "reference_source"}
    }
    graph_nodes = {
        role: node.name()
        for node in tagged
        for role in [_metadata(node, "bridge_graph_role")]
        if role
    }
    persisted_input_nodes = state.get("input_nodes")
    persisted_graph_nodes = state.get("graph_nodes")
    state.update(
        {
            "task_id": task_id,
            "write": write.name(),
            "input_nodes": dict(persisted_input_nodes) if isinstance(persisted_input_nodes, dict) else input_nodes,
            "graph_nodes": dict(persisted_graph_nodes) if isinstance(persisted_graph_nodes, dict) else graph_nodes,
        }
    )
    # Never promote the current Read knob into a frozen source contract during
    # recovery.  The hidden state was saved with the approved source and its
    # readback binding; missing or drifted data is rejected by topology
    # validation instead of being silently re-frozen.
    if not state.get("final_pattern") and write.knob("file") is not None:
        state["final_pattern"] = str(write["file"].value())
    topology = _validate_composite_topology(state)
    if not topology["topology"]["passed"]:
        raise RuntimeError(
            "COMPOSITE_TOPOLOGY_INVALID: "
            + ", ".join(topology["topology"]["errors"])
        )
    _COMPOSITES[task_id] = state
    return state


_REQUIRED_COMPOSITE_GRAPH_ROLES = (
    "input_effect_render",
    "effect_blur",
    "effect_defocus",
    "effect_denoise",
    "effect_sharpen",
    "effect_glow",
    "effect_contrast",
    "effect_edge",
    "effect_grain",
    "effect_premult",
    "final_image",
    "final_write",
)


def _same_nuke_node(left, right) -> bool:
    return left is right or (
        left is not None
        and right is not None
        and _node_lineage_name(left) == _node_lineage_name(right)
    )


def _validate_composite_topology(state: dict[str, Any]) -> dict[str, Any]:
    """Validate the persisted graph identity, tags, and primary connections."""

    task_id = str(state.get("task_id") or "")
    graph_nodes = dict(state.get("graph_nodes") or {})
    input_nodes = dict(state.get("input_nodes") or {})
    errors: list[str] = []
    resolved_roles: dict[str, Any] = {}
    resolved_inputs: dict[str, Any] = {}

    if not task_id:
        errors.append("task_id_missing")
    for role in _REQUIRED_COMPOSITE_GRAPH_ROLES:
        if not str(graph_nodes.get(role) or ""):
            errors.append(f"graph_role_missing:{role}")
    if not str(input_nodes.get("effect_render") or ""):
        errors.append("input_role_missing:effect_render")
    if str(state.get("write") or "") != str(graph_nodes.get("final_write") or ""):
        errors.append("write_state_mismatch")

    for graph_role, node_name in graph_nodes.items():
        try:
            node = _node(str(node_name or ""))
        except Exception:
            errors.append(f"graph_node_missing:{graph_role}")
            continue
        resolved_roles[str(graph_role)] = node
        if _metadata(node, "bridge_task_id") != task_id:
            errors.append(f"graph_task_tag_mismatch:{graph_role}")
        if _metadata(node, "bridge_graph_role") != str(graph_role):
            errors.append(f"graph_role_tag_mismatch:{graph_role}")

    for input_role, node_name in input_nodes.items():
        try:
            node = _node(str(node_name or ""))
        except Exception:
            errors.append(f"input_node_missing:{input_role}")
            continue
        resolved_inputs[str(input_role)] = node
        expected_graph_role = "reference_source" if input_role == "reference" else f"input_{input_role}"
        if _metadata(node, "bridge_task_id") != task_id:
            errors.append(f"input_task_tag_mismatch:{input_role}")
        if _metadata(node, "bridge_input_role") != str(input_role):
            errors.append(f"input_role_tag_mismatch:{input_role}")
        if _metadata(node, "bridge_graph_role") != expected_graph_role:
            errors.append(f"input_graph_tag_mismatch:{input_role}")
        graph_node = resolved_roles.get(expected_graph_role)
        if graph_node is None or not _same_nuke_node(node, graph_node):
            errors.append(f"input_graph_identity_mismatch:{input_role}")

    raw_input_source_paths = state.get("input_source_paths")
    input_source_paths = (
        {str(role): str(path or "") for role, path in raw_input_source_paths.items()}
        if isinstance(raw_input_source_paths, dict)
        else {}
    )
    raw_input_source_bindings = state.get("input_source_bindings")
    input_source_bindings = (
        raw_input_source_bindings
        if isinstance(raw_input_source_bindings, dict)
        else {}
    )
    raw_input_source_identities = state.get("input_source_identities")
    input_source_identities = (
        raw_input_source_identities
        if isinstance(raw_input_source_identities, dict)
        else {}
    )
    strict_input_identity = str(state.get("input_identity_policy") or "") == "strict"
    identity_start, identity_end, identity_step, _identity_count = _validated_composite_frame_range(
        dict(state.get("frame_range") or {})
    )
    identity_frames = list(range(identity_start, identity_end + 1, identity_step))
    input_binding_evidence: dict[str, Any] = {}
    source_roles = sorted(
        set(input_nodes)
        | set(input_source_paths)
        | set(input_source_bindings)
        | set(input_source_identities)
    )
    for input_role in source_roles:
        binding_drift = input_role not in _COMPOSITE_INPUT_ROLES
        source_node = resolved_inputs.get(input_role)
        frozen_path = str(input_source_paths.get(input_role) or "")
        persisted = input_source_bindings.get(input_role)
        if not isinstance(persisted, dict):
            binding_drift = True
            persisted = {}
        actual_readback = ""
        if source_node is None:
            binding_drift = True
        else:
            file_knob = source_node.knob("file")
            if file_knob is None:
                binding_drift = True
            else:
                actual_readback = str(file_knob.value() or "")
                if not actual_readback:
                    binding_drift = True
        if input_role not in input_nodes or not frozen_path:
            binding_drift = True
        if str(persisted.get("node") or "") != str(input_nodes.get(input_role) or ""):
            binding_drift = True
        if not _media_source_binding_matches(
            frozen_path,
            str(persisted.get("frozen_path") or ""),
        ):
            binding_drift = True
        if not _media_source_binding_matches(
            actual_readback,
            str(persisted.get("readback_path") or ""),
        ):
            binding_drift = True
        if not _media_source_binding_matches(frozen_path, actual_readback):
            binding_drift = True
        identity = input_source_identities.get(input_role)
        identity_evidence = _revalidate_composite_input_identity(
            input_role,
            frozen_path,
            identity,
            strict=strict_input_identity,
            expected_frames=identity_frames,
        )
        if not identity_evidence.get("matched"):
            if identity is None:
                errors.append("INPUT_SOURCE_IDENTITY_MISSING:{}".format(input_role))
            elif str(identity_evidence.get("error") or "") == "identity_required":
                errors.append("INPUT_SOURCE_IDENTITY_REQUIRED:{}".format(input_role))
            else:
                errors.append("INPUT_SOURCE_HASH_MISMATCH:{}".format(input_role))
        if binding_drift:
            errors.append("INPUT_SOURCE_DRIFT:{}".format(input_role))
        input_binding_evidence[input_role] = {
            "frozen_path": frozen_path,
            "persisted": dict(persisted),
            "actual_readback": actual_readback,
            "matched": not binding_drift,
            "identity": identity_evidence,
        }

    reference_paths = [str(item) for item in state.get("reference_source_paths") or [] if str(item)]
    raw_reference_bindings = state.get("reference_source_bindings")
    reference_bindings = raw_reference_bindings if isinstance(raw_reference_bindings, dict) else {}
    reference_binding_evidence = dict(input_binding_evidence.get("reference") or {})
    if "reference" in input_nodes:
        for role in ("reference_source", "reference_diagnostic"):
            if role not in graph_nodes:
                errors.append(f"graph_role_missing:{role}")
        reference_drift = len(reference_paths) != 1
        frozen_reference = input_source_paths.get("reference") or ""
        if not reference_drift and not _media_source_binding_matches(
            frozen_reference,
            reference_paths[0],
        ):
            reference_drift = True
        legacy_reference = reference_bindings.get("reference")
        current_reference = input_source_bindings.get("reference")
        if not isinstance(legacy_reference, dict) or not isinstance(current_reference, dict):
            reference_drift = True
        else:
            for field in ("frozen_path", "readback_path"):
                if not _media_source_binding_matches(
                    str(current_reference.get(field) or ""),
                    str(legacy_reference.get(field) or ""),
                ):
                    reference_drift = True
            if str(current_reference.get("node") or "") != str(legacy_reference.get("node") or ""):
                reference_drift = True
        if reference_drift or not reference_binding_evidence.get("matched"):
            errors.append("REFERENCE_SOURCE_DRIFT:reference")
        reference_binding_evidence.update(
            {
                "legacy_frozen_paths": list(reference_paths),
                "legacy_persisted": dict(reference_bindings),
            }
        )
    elif reference_paths or reference_bindings:
        errors.append("REFERENCE_SOURCE_DRIFT:unexpected_binding")

    final_pattern = str(state.get("final_pattern") or "")
    raw_final_binding = state.get("final_write_binding")
    final_binding = raw_final_binding if isinstance(raw_final_binding, dict) else {}
    final_phase = str(final_binding.get("phase") or "")
    final_node = resolved_roles.get("final_write")
    final_readback = ""
    final_binding_drift = False
    if final_node is None:
        final_binding_drift = True
    else:
        final_file_knob = final_node.knob("file")
        if final_file_knob is None:
            final_binding_drift = True
        else:
            final_readback = str(final_file_knob.value() or "")
            if not final_readback:
                final_binding_drift = True
    allowed_write_paths = [final_pattern] if final_pattern else []
    preview_pattern = str(state.get("preview_pattern") or "")
    if final_phase == "preview" and preview_pattern:
        allowed_write_paths.append(preview_pattern)
    if final_phase not in {"final", "preview"}:
        final_binding_drift = True
    if str(final_binding.get("node") or "") != str(state.get("write") or ""):
        final_binding_drift = True
    if not _media_source_binding_matches(
        final_pattern,
        str(final_binding.get("frozen_path") or ""),
    ):
        final_binding_drift = True
    if not _media_source_binding_matches(
        final_readback,
        str(final_binding.get("readback_path") or ""),
    ):
        final_binding_drift = True
    if not any(
        _media_source_binding_matches(path, final_readback)
        for path in allowed_write_paths
    ):
        final_binding_drift = True
    if final_binding_drift:
        errors.append("FINAL_WRITE_SOURCE_DRIFT")
    final_write_binding_evidence = {
        "phase": final_phase,
        "frozen_path": final_pattern,
        "persisted": dict(final_binding),
        "allowed_paths": allowed_write_paths,
        "actual_readback": final_readback,
        "matched": not final_binding_drift,
    }

    for input_role, auxiliary_role in (
        ("matte", "effect_matte"),
        ("plate", "plate_merge"),
        ("depth", "depth_auxiliary"),
        ("vector", "vector_auxiliary"),
    ):
        if input_role in input_nodes and auxiliary_role not in graph_nodes:
            errors.append(f"graph_role_missing:{auxiliary_role}")

    def connected(destination_role: str, input_index: int, source_role: str) -> None:
        destination = resolved_roles.get(destination_role)
        source = resolved_roles.get(source_role)
        if destination is None or source is None:
            return
        try:
            actual = destination.input(input_index)
        except Exception:
            errors.append(f"connection_unreadable:{destination_role}:{input_index}")
            return
        if not _same_nuke_node(actual, source):
            errors.append(f"connection_mismatch:{source_role}->{destination_role}[{input_index}]")

    previous_role = "input_effect_render"
    if "matte" in input_nodes:
        connected("effect_matte", 0, previous_role)
        connected("effect_matte", 1, "input_matte")
        previous_role = "effect_matte"
    for graph_role in (
        "effect_blur",
        "effect_defocus",
        "effect_denoise",
        "effect_sharpen",
        "effect_glow",
        "effect_contrast",
        "effect_edge",
        "effect_grain",
        "effect_premult",
    ):
        connected(graph_role, 0, previous_role)
        previous_role = graph_role
    if "plate" in input_nodes:
        connected("plate_merge", 0, "input_plate")
        connected("plate_merge", 1, previous_role)
        previous_role = "plate_merge"
    connected("final_image", 0, previous_role)
    connected("final_write", 0, "final_image")

    if "reference" in input_nodes:
        connected("reference_diagnostic", 0, "reference_source")
    for input_role in ("depth", "vector"):
        if input_role in input_nodes:
            connected(f"{input_role}_auxiliary", 0, f"input_{input_role}")

    gate = {
        "name": "composite_topology_intact",
        "passed": not errors,
        "kind": "verification",
        "errors": sorted(set(errors)),
        "task_id": task_id,
        "input_bindings": input_binding_evidence,
        "reference_binding": reference_binding_evidence,
        "final_write_binding": final_write_binding_evidence,
    }
    return {"gates": [gate], "topology": gate}


def _validate_composite_input_contract(
    state: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Bind every action request back to the inputs frozen at graph build."""

    requested_inputs = _composite_inputs(params)
    frozen_paths = state.get("input_source_paths")
    frozen_identities = state.get("input_source_identities")
    if not isinstance(frozen_paths, dict) or not isinstance(frozen_identities, dict):
        raise RuntimeError("INPUT_SPEC_DRIFT:missing_frozen_contract")
    requested_roles = set(requested_inputs)
    frozen_roles = set(str(role) for role in frozen_paths)
    if requested_roles != frozen_roles:
        changed = sorted(requested_roles.symmetric_difference(frozen_roles))
        raise RuntimeError("INPUT_SPEC_DRIFT:" + ",".join(changed or ["roles"]))
    strict = (
        str(state.get("input_identity_policy") or "") == "strict"
        or str(params.get("schema_version") or "") == "2.0"
    )
    requested_identities = _capture_composite_input_identities(
        requested_inputs,
        strict=strict,
        expected_frames=list(
            range(
                int((state.get("frame_range") or {}).get("start", 1)),
                int((state.get("frame_range") or {}).get("end", 1)) + 1,
                int((state.get("frame_range") or {}).get("step", 1)),
            )
        ),
    )
    evidence: dict[str, Any] = {}
    drifted: list[str] = []
    for role in sorted(requested_roles):
        requested_path = str(requested_inputs[role].get("path") or "")
        frozen_path = str(frozen_paths.get(role) or "")
        path_matches = _media_source_binding_matches(frozen_path, requested_path)
        frozen_identity = frozen_identities.get(role)
        requested_identity = requested_identities.get(role)
        identity_matches = (
            isinstance(frozen_identity, dict)
            and isinstance(requested_identity, dict)
            and hmac.compare_digest(
                _canonical_payload_sha256(frozen_identity),
                _canonical_payload_sha256(requested_identity),
            )
        )
        if not path_matches or not identity_matches:
            drifted.append(role)
        evidence[role] = {
            "path_matched": path_matches,
            "identity_matched": identity_matches,
            "identity_status": str((frozen_identity or {}).get("status") or "missing")
            if isinstance(frozen_identity, dict)
            else "missing",
        }
    if drifted:
        raise RuntimeError("INPUT_SPEC_DRIFT:" + ",".join(drifted))
    return evidence


def _validate_composite_output_contract(
    state: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    # Validation is deliberately read-only.  A rejected request must not be
    # able to create an arbitrary directory before its frozen contract fails.
    expected_output_dir = _resolved_composite_output_dir(params)
    expected_final = str(expected_output_dir / "final.%04d.exr")
    state_output_dir = Path(str(state.get("output_dir") or "")).expanduser().resolve(strict=False)
    state_final = str(state.get("final_pattern") or "")
    start, end, step, _count = _validated_composite_frame_range(
        (params.get("render") or {}).get("frame_range") or {}
    )
    expected_range = {"start": start, "end": end, "step": step}
    binding = state.get("final_write_binding")
    errors: list[str] = []
    if state_output_dir != expected_output_dir:
        errors.append("output_dir")
    if not _media_source_binding_matches(expected_final, state_final):
        errors.append("final_pattern")
    if dict(state.get("frame_range") or {}) != expected_range:
        errors.append("frame_range")
    if not isinstance(binding, dict) or not _media_source_binding_matches(
        expected_final,
        str(binding.get("frozen_path") or ""),
    ):
        errors.append("final_write_binding")
    preview_pattern = str(state.get("preview_pattern") or "")
    if preview_pattern:
        preview_path = Path(preview_pattern).expanduser().resolve(strict=False)
        preview_name = Path(preview_pattern).name
        if (
            preview_path.parent != expected_output_dir
            or re.fullmatch(r"preview\.[A-Za-z0-9_-]{1,64}\.%04d\.exr", preview_name) is None
        ):
            errors.append("preview_pattern")
    if errors:
        raise RuntimeError("OUTPUT_SPEC_DRIFT:" + ",".join(sorted(set(errors))))
    return {
        "output_dir": str(expected_output_dir),
        "final_pattern": expected_final,
        "frame_range": expected_range,
        "preview_pattern": preview_pattern,
    }


def _composite_state(
    task_id: str,
    *,
    required_write_phase: str | None = None,
) -> dict[str, Any]:
    state = _COMPOSITES.get(task_id) or _restore_composite_state(task_id)
    if state is None:
        raise RuntimeError("composite graph missing; run agent.nuke.composite.build_graph first")
    topology = _validate_composite_topology(state)
    if not topology["topology"]["passed"]:
        raise RuntimeError(
            "COMPOSITE_TOPOLOGY_INVALID: "
            + ", ".join(topology["topology"]["errors"])
        )
    if required_write_phase is not None:
        if required_write_phase not in {"preview", "final"}:
            raise ValueError("unsupported composite Write phase")
        binding = topology["topology"].get("final_write_binding") or {}
        expected_path = str(
            state.get("preview_pattern" if required_write_phase == "preview" else "final_pattern")
            or ""
        )
        if (
            str(binding.get("phase") or "") != required_write_phase
            or not _media_source_binding_matches(
                expected_path,
                str(binding.get("actual_readback") or ""),
            )
        ):
            raise RuntimeError(
                "FINAL_WRITE_SOURCE_DRIFT:{}".format(required_write_phase)
            )
    return state


def _scalar_control(controls: dict[str, Any], name: str, default: float = 0.0) -> float:
    raw = controls.get(name, default)
    if isinstance(raw, dict):
        raw = raw.get("value", default)
    return float(raw)


_COMPOSITE_CONTROL_MAPPING = {
    "blur_size": ("effect_blur", ["size"], 0.0, 500.0),
    "defocus": ("effect_defocus", ["defocus"], 0.0, 500.0),
    "defocus_size": ("effect_defocus", ["defocus"], 0.0, 500.0),
    "denoise_mix": ("effect_denoise", ["mix"], 0.0, 1.0),
    "sharpen_size": ("effect_sharpen", ["size", "amount"], 0.0, 100.0),
    "sharpen_amount": ("effect_sharpen", ["amount", "size"], 0.0, 100.0),
    "glow_mix": ("effect_glow", ["mix", "brightness"], 0.0, 10.0),
    "glow_size": ("effect_glow", ["size", "mix", "brightness"], 0.0, 500.0),
    "glow_amount": ("effect_glow", ["brightness", "mix"], 0.0, 100.0),
    "emission_contrast": ("effect_contrast", ["contrast"], 0.0, 10.0),
    "comp_contrast": ("effect_contrast", ["contrast"], 0.0, 10.0),
    "edge_size": ("effect_edge", ["size"], 0.0, 500.0),
    "grain_mix": ("effect_grain", ["mix", "intensity"], 0.0, 10.0),
    "color_fusion_mix": ("plate_merge", ["mix"], 0.0, 1.0),
}


def _validated_composite_controls(controls: dict[str, Any]) -> dict[str, Any]:
    """Validate semantic values without requiring any Nuke nodes to exist."""

    validated: dict[str, Any] = {}
    for name, raw_value in controls.items():
        if name == "premult":
            if type(raw_value) is not bool:
                raise ValueError("premult must be a boolean")
            validated[name] = raw_value
            continue
        if name not in _COMPOSITE_CONTROL_MAPPING:
            raise ValueError(f"unsupported composite semantic control: {name}")
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("value")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        _graph_role, _knob_names, minimum, maximum = _COMPOSITE_CONTROL_MAPPING[name]
        if not math.isfinite(value) or value < minimum or value > maximum:
            raise ValueError(f"{name} must be in range {minimum}..{maximum}")
        validated[name] = value
    return validated


def _semantic_knobs_for_role(node, graph_role: str) -> list[str]:
    """Return every physical semantic knob supported by one role node."""

    supported: list[str] = []
    for mapped_role, knob_names, _minimum, _maximum in _COMPOSITE_CONTROL_MAPPING.values():
        if mapped_role != graph_role:
            continue
        for knob_name in knob_names:
            if knob_name not in supported and node.knob(knob_name) is not None:
                supported.append(knob_name)
    return supported


def _resolve_composite_control_plan(
    graph_nodes: dict[str, str],
    controls: dict[str, Any],
    node_objects: dict[str, Any] | None = None,
    *,
    preserve_existing_semantics: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve every semantic control before mutating any physical knob."""

    controls = _validated_composite_controls(controls)
    resolved: list[dict[str, Any]] = []
    primary_targets: dict[tuple[int, str], dict[str, Any]] = {}
    disable_targets: dict[tuple[int, str], dict[str, Any]] = {}

    def role_node(role: str):
        if node_objects is not None and role in node_objects:
            return node_objects[role]
        return _node(str(graph_nodes.get(role) or ""))

    def conflict(first: str, second: str, node, knob_name: str) -> None:
        raise ValueError(
            "SEMANTIC_CONTROL_ALIAS_CONFLICT: {} and {} resolve to {}.{}".format(
                first,
                second,
                node.name(),
                knob_name,
            )
        )

    for name, raw_value in controls.items():
        if name == "premult":
            node = role_node("effect_premult")
            selected = "disable"
            if node.knob(selected) is None:
                raise RuntimeError("Premult node has no disable knob")
            requested = not raw_value
            plan = {
                "kind": "premult",
                "control": name,
                "node": node,
                "knob": selected,
                "requested": requested,
                "requested_enabled": raw_value,
            }
        else:
            graph_role, knob_names, minimum, maximum = _COMPOSITE_CONTROL_MAPPING[name]
            value = float(raw_value)
            node = role_node(graph_role)
            capability = _metadata(node, "bridge_capability")
            if capability == "NoOp":
                raise RuntimeError(f"semantic control {name} is unavailable in this Nuke build")
            selected = next((knob_name for knob_name in knob_names if node.knob(knob_name) is not None), None)
            if selected is None:
                raise RuntimeError(f"node {node.name()} has no supported knob for {name}")
            requested = value
            plan = {
                "kind": "scalar",
                "control": name,
                "node": node,
                "knob": selected,
                "requested": requested,
                "graph_role": graph_role,
            }

        key = (id(node), selected)
        prior = primary_targets.get(key)
        if prior is not None:
            conflict(str(prior["owners"][0]), name, node, selected)
        prior_disable = disable_targets.get(key)
        if prior_disable is not None:
            conflict(str(prior_disable["owners"][0]), name, node, selected)
        target = {
            "node": node,
            "knob": selected,
            "requested": requested,
            "owners": [name],
        }
        primary_targets[key] = target
        plan["target"] = target
        resolved.append(plan)

    scalar_by_node: dict[int, list[dict[str, Any]]] = {}
    for plan in resolved:
        if plan["kind"] == "scalar":
            scalar_by_node.setdefault(id(plan["node"]), []).append(plan)

    for node_plans in scalar_by_node.values():
        node = node_plans[0]["node"]
        disable = node.knob("disable")
        if disable is None:
            for plan in node_plans:
                plan["disable_target"] = None
            continue
        disable_key = (id(node), "disable")
        prior_primary = primary_targets.get(disable_key)
        if prior_primary is not None:
            conflict(
                str(prior_primary["owners"][0]),
                str(node_plans[0]["control"]),
                node,
                "disable",
            )

        planned_values = {
            str(plan["knob"]): float(plan["requested"])
            for plan in node_plans
        }
        if preserve_existing_semantics and not bool(disable.value()):
            semantic_values: list[float] = []
            for knob_name in _semantic_knobs_for_role(node, str(node_plans[0]["graph_role"])):
                if knob_name in planned_values:
                    semantic_values.append(planned_values[knob_name])
                    continue
                try:
                    current_value = float(node.knob(knob_name).value())
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"node {node.name()} returned a non-numeric semantic knob: {knob_name}"
                    ) from exc
                if not math.isfinite(current_value):
                    raise RuntimeError(
                        f"node {node.name()} returned a non-finite semantic knob: {knob_name}"
                    )
                semantic_values.append(current_value)
        else:
            # A disabled node's dormant defaults must not reactivate it.  A
            # build likewise derives enablement only from declared controls.
            semantic_values = list(planned_values.values())
        requested_disabled = not any(abs(value) > 1e-9 for value in semantic_values)
        disable_target = {
            "node": node,
            "knob": "disable",
            "requested": requested_disabled,
            "owners": [str(plan["control"]) for plan in node_plans],
        }
        disable_targets[disable_key] = disable_target
        for plan in node_plans:
            plan["disable_target"] = disable_target

    physical_writes = list(primary_targets.values()) + list(disable_targets.values())
    return resolved, physical_writes


def _knob_state_query(knob, method_name: str) -> bool:
    """Read animation/expression flags across scalar and array knob APIs."""

    method = getattr(knob, method_name, None)
    if not callable(method):
        return False
    noarg_inspected = False
    try:
        noarg_inspected = True
        if bool(method()):
            return True
    except TypeError:
        pass
    except Exception as exc:
        raise RuntimeError(
            "PARAMETER_STATE_UNSUPPORTED: {} state could not be inspected: {}".format(
                method_name,
                exc,
            )
        ) from exc

    component_count = 1
    for count_name in ("arraySize", "width"):
        count_method = getattr(knob, count_name, None)
        if not callable(count_method):
            continue
        try:
            component_count = max(component_count, int(count_method()))
        except Exception:
            continue
    inspected = noarg_inspected
    for index in range(component_count):
        try:
            result = method(index)
            inspected = True
            if bool(result):
                return True
        except TypeError:
            continue
        except Exception as exc:
            raise RuntimeError(
                "PARAMETER_STATE_UNSUPPORTED: {} component {} could not be inspected: {}".format(
                    method_name,
                    index,
                    exc,
                )
            ) from exc
    if not inspected:
        raise RuntimeError(
            "PARAMETER_STATE_UNSUPPORTED: {} state could not be inspected".format(
                method_name
            )
        )
    return False


def _preflight_static_composite_knob(node, knob_name: str, knob) -> None:
    animated = _knob_state_query(knob, "isAnimated")
    expression = _knob_state_query(knob, "hasExpression")
    if animated or expression:
        state = "/".join(
            name for name, present in (("animation", animated), ("expression", expression))
            if present
        )
        raise RuntimeError(
            "PARAMETER_STATE_UNSUPPORTED: {}.{} contains {}".format(
                node.name(),
                knob_name,
                state,
            )
        )


def _write_composite_control_plan(
    physical_writes: list[dict[str, Any]],
    rollback: list[tuple[Any, str, Any, bool]],
) -> None:
    """Apply the resolved plan, then verify every request as one snapshot."""

    # Preflight the complete write set before changing even the first knob.
    # value()-only rollback cannot faithfully restore expressions or curves.
    for target in physical_writes:
        knob = target["node"].knob(str(target["knob"]))
        if knob is None:
            raise RuntimeError("resolved composite knob disappeared before write")
        _preflight_static_composite_knob(
            target["node"],
            str(target["knob"]),
            knob,
        )
        target["before"] = knob.value()
    for target in physical_writes:
        rollback.append((target["node"], str(target["knob"]), target["before"], True))
        _set_knob(target["node"], str(target["knob"]), target["requested"])
    for target in physical_writes:
        actual = target["node"].knob(str(target["knob"])).value()
        target["actual"] = actual
        if not _values_match(target["requested"], actual):
            owner_label = ",".join(str(owner) for owner in target["owners"])
            if str(target["knob"]) == "disable":
                owner_label += ".disable"
            raise RuntimeError(
                "PARAMETER_READBACK_MISMATCH: {} requested={} actual={}".format(
                    owner_label,
                    target["requested"],
                    actual,
                )
            )


def _restore_composite_mutations(
    rollback: list[tuple[Any, str, Any, bool]],
) -> list[str]:
    restore_errors: list[str] = []
    for node, knob_name, before, existed in reversed(rollback):
        try:
            if existed:
                restored = _set_knob(node, knob_name, before)
                if not _values_match(before, restored):
                    restore_errors.append(f"{node.name()}.{knob_name} readback mismatch")
            else:
                added = node.knob(knob_name)
                if added is not None:
                    remover = getattr(node, "removeKnob", None)
                    if remover is None:
                        raise RuntimeError("new knob cannot be removed")
                    remover(added)
                if node.knob(knob_name) is not None:
                    restore_errors.append(f"{node.name()}.{knob_name} still exists")
        except Exception as restore_exc:
            restore_errors.append(f"{node.name()}.{knob_name}: {restore_exc}")
    # A later restoration can itself drive or expression-link a knob that was
    # restored earlier.  Verify the complete rollback snapshot only after all
    # restoration writes have finished.
    for node, knob_name, before, existed in rollback:
        try:
            restored_knob = node.knob(knob_name)
            if existed:
                actual = restored_knob.value() if restored_knob is not None else None
                if restored_knob is None or not _values_match(before, actual):
                    restore_errors.append(f"{node.name()}.{knob_name} final readback mismatch")
            elif restored_knob is not None:
                restore_errors.append(f"{node.name()}.{knob_name} unexpectedly exists after restore")
        except Exception as restore_exc:
            restore_errors.append(f"{node.name()}.{knob_name} final readback: {restore_exc}")
    return restore_errors


def _composite_changes(resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for plan in resolved:
        target = plan["target"]
        if plan["kind"] == "premult":
            changes.append(
                {
                    "control": plan["control"],
                    "before_disabled": target["before"],
                    "requested_enabled": plan["requested_enabled"],
                    "after_enabled": not bool(target["actual"]),
                    "node": plan["node"].name(),
                    "readback_verified": True,
                }
            )
            continue
        disable_target = plan.get("disable_target")
        changes.append(
            {
                "control": plan["control"],
                "before": target["before"],
                "requested": plan["requested"],
                "after": target["actual"],
                "node": plan["node"].name(),
                "knob": plan["knob"],
                "readback_verified": True,
                "disable_readback_verified": True,
                "after_disabled": bool(disable_target["actual"]) if disable_target is not None else None,
            }
        )
    return changes


def _build_composite_graph(params: dict[str, Any]) -> dict[str, Any]:
    import nuke

    task_id = str(params.get("task_id") or "")
    raw_frame_range = (params.get("render") or {}).get("frame_range") or {}
    frame_start, frame_end, frame_step, _frame_count = _validated_composite_frame_range(raw_frame_range)
    controls = _validated_composite_controls(
        dict((params.get("constraints") or {}).get("composite_controls") or {})
    )
    inputs = _composite_inputs(params)
    strict_input_identity = str(params.get("schema_version") or "") == "2.0"
    existing = _COMPOSITES.get(task_id) or _restore_composite_state(task_id)
    if existing is not None:
        _validate_composite_input_contract(existing, params)
        _validate_composite_output_contract(existing, params)
        topology = _validate_composite_topology(existing)
        if not topology["topology"]["passed"]:
            raise RuntimeError(
                "COMPOSITE_TOPOLOGY_INVALID: "
                + ", ".join(topology["topology"]["errors"])
            )
        audit = _audit_composite_lineage(existing)
        return {
            "gates": [
                {
                    "name": "editable_native_composite_graph",
                    "passed": True,
                    "kind": "operation",
                    "write": existing.get("write"),
                    "input_roles": sorted((existing.get("input_nodes") or {}).keys()),
                    "graph_nodes": dict(existing.get("graph_nodes") or {}),
                    "restored": True,
                },
                *topology["gates"],
                *audit["gates"],
            ],
            "graph": existing,
            "restored": True,
        }

    input_source_identities = _capture_composite_input_identities(
        inputs,
        strict=strict_input_identity,
        expected_frames=list(range(frame_start, frame_end + 1, frame_step)),
    )
    if "color_fusion_mix" in controls and "plate" not in inputs:
        raise ValueError("color_fusion_mix requires a plate input")
    output_dir = _composite_output_dir(params)
    key = _task_key(task_id)
    schema_version = str(params.get("schema_version") or "1.0")
    input_nodes: dict[str, str] = {}
    graph_nodes: dict[str, str] = {}
    created_nodes: list[Any] = []
    control_rollback: list[tuple[Any, str, Any, bool]] = []
    registry_was_present = task_id in _COMPOSITES
    registry_before = _COMPOSITES.get(task_id)

    native_specs = [
        ("effect_blur", ["Blur"], "blur_size"),
        ("effect_defocus", ["Defocus"], "defocus"),
        ("effect_denoise", ["Denoise2", "Denoise"], "denoise_mix"),
        ("effect_sharpen", ["Sharpen"], "sharpen_size"),
        ("effect_glow", ["Glow"], "glow_mix"),
        ("effect_contrast", ["ColorCorrect"], "comp_contrast"),
        ("effect_edge", ["EdgeBlur"], "edge_size"),
        ("effect_grain", ["Grain2", "Grain"], "grain_mix"),
    ]

    try:
        with nuke.Undo("Bridge Skills reference composite"):
            role_nodes: dict[str, Any] = {}
            control_nodes: dict[str, Any] = {}
            for index, role in enumerate(sorted(inputs)):
                item = inputs[role]
                node = _native_node("Read", f"BRIDGE_{key}_{role.upper()}")
                created_nodes.append(node)
                _set_knob(node, "file", str(item["path"]))
                node.setXpos(index * 180)
                node.setYpos(-260 if role == "reference" else 0)
                component = str(item.get("component_id") or role)
                graph_role = "reference_source" if role == "reference" else f"input_{role}"
                _tag_node(
                    node,
                    task_id,
                    input_role=role,
                    component_id=component,
                    graph_role=graph_role,
                    schema_version=schema_version,
                )
                role_nodes[role] = node
                input_nodes[role] = node.name()
                graph_nodes[graph_role] = node.name()

            current = role_nodes["effect_render"]
            if "matte" in role_nodes:
                copy = _native_node("Copy", f"BRIDGE_{key}_MATTE_COPY", [current, role_nodes["matte"]])
                created_nodes.append(copy)
                _set_supported_knob(copy, ["from0"], "rgba.alpha")
                _set_supported_knob(copy, ["to0"], "rgba.alpha")
                _tag_node(copy, task_id, component_id="effect", graph_role="effect_matte", schema_version=schema_version)
                graph_nodes["effect_matte"] = copy.name()
                current = copy

            for graph_role, classes, _default_control in native_specs:
                role_values = [
                    float(value)
                    for name, value in controls.items()
                    if name in _COMPOSITE_CONTROL_MAPPING
                    and _COMPOSITE_CONTROL_MAPPING[name][0] == graph_role
                ]
                requested = any(abs(value) > 1e-9 for value in role_values)
                node, actual_class = _optional_native_node(
                    classes,
                    f"BRIDGE_{key}_{graph_role.upper()}",
                    current,
                    requested,
                )
                created_nodes.append(node)
                _tag_node(
                    node,
                    task_id,
                    component_id="effect",
                    graph_role=graph_role,
                    schema_version=schema_version,
                    capability=actual_class,
                )
                graph_nodes[graph_role] = node.name()
                if actual_class != "NoOp":
                    control_nodes[graph_role] = node
                current = node

            premult = _native_node("Premult", f"BRIDGE_{key}_EFFECT_PREMULT", [current])
            created_nodes.append(premult)
            _tag_node(premult, task_id, component_id="effect", graph_role="effect_premult", schema_version=schema_version)
            graph_nodes["effect_premult"] = premult.name()
            control_nodes["effect_premult"] = premult
            current = premult

            if "plate" in role_nodes:
                merge = _native_node("Merge2", f"BRIDGE_{key}_PLATE_MERGE", [role_nodes["plate"], current])
                created_nodes.append(merge)
                _set_supported_knob(merge, ["operation"], "plus")
                _tag_node(merge, task_id, component_id="composite", graph_role="plate_merge", schema_version=schema_version)
                graph_nodes["plate_merge"] = merge.name()
                control_nodes["plate_merge"] = merge
                current = merge

            build_controls = dict(controls)
            for graph_role, _classes, default_control in native_specs:
                if graph_role not in control_nodes:
                    for control_name in list(build_controls):
                        if control_name in _COMPOSITE_CONTROL_MAPPING and _COMPOSITE_CONTROL_MAPPING[control_name][0] == graph_role:
                            if abs(float(build_controls[control_name])) <= 1e-9:
                                build_controls.pop(control_name)
                    continue
                if not any(
                    name in _COMPOSITE_CONTROL_MAPPING
                    and _COMPOSITE_CONTROL_MAPPING[name][0] == graph_role
                    for name in build_controls
                ):
                    build_controls[default_control] = 0.0
            build_controls.setdefault("premult", False)
            if "plate" in role_nodes:
                build_controls.setdefault("color_fusion_mix", 1.0)

            _resolved, physical_writes = _resolve_composite_control_plan(
                graph_nodes,
                build_controls,
                control_nodes,
                preserve_existing_semantics=False,
            )
            try:
                _write_composite_control_plan(physical_writes, control_rollback)
            except Exception as exc:
                restore_errors = _restore_composite_mutations(control_rollback)
                control_rollback.clear()
                if restore_errors:
                    raise RuntimeError("PARAMETER_RESTORE_FAILED: " + "; ".join(restore_errors)) from exc
                raise

            final = _native_node("NoOp", f"BRIDGE_{key}_FINAL", [current])
            created_nodes.append(final)
            _tag_node(final, task_id, component_id="composite", graph_role="final_image", schema_version=schema_version)
            graph_nodes["final_image"] = final.name()
            write = _native_node("Write", f"BRIDGE_{key}_WRITE", [final])
            created_nodes.append(write)
            final_pattern = str(output_dir / "final.%04d.exr")
            _set_knob(write, "file", final_pattern)
            _tag_node(write, task_id, component_id="delivery", graph_role="final_write", schema_version=schema_version)
            graph_nodes["final_write"] = write.name()

            if "reference" in role_nodes:
                diagnostic = _native_node("NoOp", f"BRIDGE_{key}_REFERENCE_DIAGNOSTIC", [role_nodes["reference"]])
                created_nodes.append(diagnostic)
                diagnostic.setYpos(-440)
                _tag_node(
                    diagnostic,
                    task_id,
                    input_role="reference",
                    component_id="reference",
                    graph_role="reference_diagnostic",
                    schema_version=schema_version,
                )
                graph_nodes["reference_diagnostic"] = diagnostic.name()

            for role in ("depth", "vector"):
                if role in role_nodes:
                    diagnostic = _native_node("NoOp", f"BRIDGE_{key}_{role.upper()}_AUX", [role_nodes[role]])
                    created_nodes.append(diagnostic)
                    _tag_node(
                        diagnostic,
                        task_id,
                        input_role=role,
                        component_id=str(inputs[role].get("component_id") or role),
                        graph_role=f"{role}_auxiliary",
                        schema_version=schema_version,
                    )
                    graph_nodes[f"{role}_auxiliary"] = diagnostic.name()

        input_source_paths = {
            role: str(inputs[role]["path"])
            for role in sorted(role_nodes)
        }
        input_source_bindings: dict[str, dict[str, str]] = {}
        for role, source_node in sorted(role_nodes.items()):
            file_knob = source_node.knob("file")
            source_readback = str(file_knob.value() or "") if file_knob is not None else ""
            frozen_source = input_source_paths[role]
            if not _media_source_binding_matches(frozen_source, source_readback):
                raise RuntimeError("INPUT_SOURCE_DRIFT:{}".format(role))
            input_source_bindings[role] = {
                "node": source_node.name(),
                "frozen_path": frozen_source,
                "readback_path": source_readback,
            }
        reference_source_paths = (
            [input_source_paths["reference"]]
            if "reference" in input_source_paths
            else []
        )
        reference_source_bindings = (
            {"reference": dict(input_source_bindings["reference"])}
            if "reference" in input_source_bindings
            else {}
        )
        final_write_readback = str(write["file"].value() or "")
        if not _media_source_binding_matches(final_pattern, final_write_readback):
            raise RuntimeError("FINAL_WRITE_SOURCE_DRIFT")

        state = {
            "task_id": task_id,
            "schema_version": schema_version,
            "domain_pack": "nuke_composite_v1",
            "input_nodes": input_nodes,
            "graph_nodes": graph_nodes,
            "write": write.name(),
            "final_pattern": final_pattern,
            "output_dir": str(output_dir),
            "frame_range": {
                "start": frame_start,
                "end": frame_end,
                "step": frame_step,
            },
            "input_source_paths": input_source_paths,
            "input_source_bindings": input_source_bindings,
            "input_source_identities": input_source_identities,
            "input_identity_policy": "strict" if strict_input_identity else "legacy",
            "reference_source_paths": reference_source_paths,
            "reference_source_bindings": reference_source_bindings,
            "final_write_binding": {
                "node": write.name(),
                "phase": "final",
                "frozen_path": final_pattern,
                "readback_path": final_write_readback,
            },
        }
        topology = _validate_composite_topology(state)
        if not topology["topology"]["passed"]:
            raise RuntimeError(
                "COMPOSITE_TOPOLOGY_INVALID: "
                + ", ".join(topology["topology"]["errors"])
            )
        _persist_composite_state(state)
        audit = _audit_composite_lineage(state)
        if not audit["lineage"]["passed"]:
            raise RuntimeError("reference lineage violation after composite build")
        gates = [
            {
                "name": "editable_native_composite_graph",
                "passed": True,
                "kind": "operation",
                "write": state["write"],
                "input_roles": sorted(input_nodes),
                "graph_nodes": graph_nodes,
            },
            *topology["gates"],
            *audit["gates"],
        ]
        return {"gates": gates, "graph": state, "restored": False}
    except Exception as exc:
        restore_errors = _restore_composite_mutations(control_rollback)
        delete_node = getattr(nuke, "delete", None)
        for node in reversed(created_nodes):
            try:
                if not callable(delete_node):
                    raise RuntimeError("Nuke delete API is unavailable")
                delete_node(node)
            except Exception as delete_exc:
                restore_errors.append(f"{_node_lineage_name(node)} delete failed: {delete_exc}")
        if registry_was_present:
            _COMPOSITES[task_id] = registry_before
        else:
            _COMPOSITES.pop(task_id, None)
        if restore_errors:
            raise RuntimeError("COMPOSITE_BUILD_ROLLBACK_FAILED: " + "; ".join(restore_errors)) from exc
        raise


def _apply_composite_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    controls = dict(patch.get("controls") or patch)
    if len(controls) > 5:
        raise ValueError("a composite patch may change at most five semantic controls")
    graph_nodes = dict(state.get("graph_nodes") or {})
    resolved, physical_writes = _resolve_composite_control_plan(graph_nodes, controls)
    rollback: list[tuple[Any, str, Any, bool]] = []
    task_id = str(state.get("task_id") or "")
    registry_was_present = task_id in _COMPOSITES
    registry_before = _COMPOSITES.get(task_id)
    state_before = json.loads(json.dumps(state, ensure_ascii=False))
    write = _node(str(state.get("write") or ""))
    metadata_knob = write.knob("bridge_state_json")
    if metadata_knob is not None:
        _preflight_static_composite_knob(
            write,
            "bridge_state_json",
            metadata_knob,
        )
    try:
        _write_composite_control_plan(physical_writes, rollback)
        changes = _composite_changes(resolved)
        audit = _audit_composite_lineage(state)
        if not audit["lineage"]["passed"]:
            raise RuntimeError("reference lineage violation after composite patch")
        rollback.append(
            (
                write,
                "bridge_state_json",
                metadata_knob.value() if metadata_knob is not None else None,
                metadata_knob is not None,
            )
        )
        state.pop("final_verification", None)
        _persist_composite_state(state)
        result = {
            "gates": [
                *audit["gates"],
                {
                    "name": "composite_patch_applied",
                    "passed": True,
                    "kind": "operation",
                    "readback_verified": True,
                    "changed_controls": [item["control"] for item in changes],
                },
            ],
            "changes": changes,
            "graph": state,
        }
    except Exception as exc:
        restore_errors = _restore_composite_mutations(rollback)
        state.clear()
        state.update(state_before)
        if registry_was_present:
            _COMPOSITES[task_id] = state if registry_before is state else registry_before
        else:
            _COMPOSITES.pop(task_id, None)
        if restore_errors:
            raise RuntimeError("PARAMETER_RESTORE_FAILED: " + "; ".join(restore_errors)) from exc
        raise
    return result


def _fx_check_disk_budget(directory, estimated_bytes: int = 0) -> dict:
    """Configurable disk budget for the render output directory (R08).

    Enabled only when ``NUKE_BRIDGE_DISK_BUDGET_MB`` is set.  Refuses the
    render with evidence when usage plus the estimate would exceed the
    budget; nothing is ever deleted.
    """
    configured = str(os.environ.get("NUKE_BRIDGE_DISK_BUDGET_MB") or "").strip()
    if not configured:
        return {"enforced": False}
    try:
        limit_bytes = float(configured) * 1024.0 * 1024.0
    except ValueError:
        raise ValueError("NUKE_BRIDGE_DISK_BUDGET_MB is not a number")
    directory = Path(directory)
    usage = 0
    if directory.is_dir():
        for item in directory.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    usage += item.stat().st_size
            except OSError:
                continue
    if usage + max(0, int(estimated_bytes)) > limit_bytes:
        raise ValueError("DISK_BUDGET_EXCEEDED: task directory {} holds {} bytes; budget is {} bytes".format(
            directory, usage, int(limit_bytes)))
    return {"enforced": True, "usage_bytes": usage, "limit_bytes": int(limit_bytes)}


def _nuke_scene_version_fingerprint(nuke) -> str:
    """Scene content fingerprint bound into the request digest (C2).

    The dirty bit is deliberately not an identity.  A save operation may
    change ``modified`` while preserving the same scene, whereas a changed
    NK byte stream must produce a different request identity.
    """
    from nuke_bridge.operation_receipts import native_format_readback

    script = nuke.root()
    name = str(script.name()) if script is not None and hasattr(script, "name") and script.name() else "unsaved-script"
    version = str(getattr(nuke, "NUKE_VERSION_STRING", ""))
    scene = _nuke_scene_fingerprint("")
    fallback_nodes: list[dict[str, Any]] = []
    resolver = getattr(nuke, "toNode", None) or getattr(nuke, "node", None)
    if callable(resolver):
        for candidate in ("Write1", "Write", "Read1"):
            try:
                node = resolver(candidate)
            except Exception:
                node = None
            if node is None:
                continue
            values: dict[str, Any] = {}
            knob_reader = getattr(node, "knobs", None)
            if callable(knob_reader):
                try:
                    for knob_name, knob in sorted(dict(knob_reader() or {}).items()):
                        value_reader = getattr(knob, "value", None)
                        if callable(value_reader):
                            values[str(knob_name)] = native_format_readback(nuke, value_reader())
                except ValueError:
                    raise
                except Exception:
                    values = {}
            if not values:
                try:
                    knob = node["file"]
                    values["file"] = knob.value() if callable(getattr(knob, "value", None)) else str(knob)
                except Exception:
                    pass
            fallback_nodes.append({"name": candidate, "class": str(getattr(node, "Class", lambda: "")()), "knobs": values})
    script_sha256 = ""
    script_bytes = 0
    source = Path(name).expanduser()
    if source.is_file() and not source.is_symlink():
        try:
            artifact = _artifact(source)
            script_sha256 = str(artifact.get("sha256") or "")
            script_bytes = int(artifact.get("bytes") or 0)
        except OSError:
            script_sha256 = ""
    return _canonical_payload_sha256({
        "script": str(source),
        "version": version,
        "script_sha256": script_sha256,
        "script_bytes": script_bytes,
        "scene": scene,
        "fallback_nodes": fallback_nodes,
    })


_NUKE_BACKGROUND_LAUNCHER = None  # explicit test boundary only
_NUKE_BACKGROUND_ROUTE: dict[str, Any] | None = None


class RenderDispatchError(RuntimeError):
    """A launch failure that carries whether a child was actually started."""

    def __init__(self, message: str, *, started: bool | None):
        super().__init__(message)
        self.started = started


def _verified_executable(value: str) -> str:
    path = Path(str(value or "")).expanduser()
    if path.is_symlink() or not path.is_file() or not os.access(str(path), os.X_OK):
        raise ValueError("NUKE_EXECUTABLE_UNVERIFIED: executable must be a regular executable file")
    return str(path.resolve())


def configure_nuke_background_route(*, nuke_executable: str, worker_script: str, software_api: bool = False, supervisor_executable: str | None = None, resource_budget: dict | None = None) -> dict[str, Any]:
    """Install the controller-selected owned-worker route for this host."""
    global _NUKE_BACKGROUND_ROUTE
    executable = _verified_executable(nuke_executable)
    worker = Path(str(worker_script or "")).expanduser()
    if worker.is_symlink() or not worker.is_file():
        raise ValueError("NUKE_WORKER_UNVERIFIED: worker must be a regular file")
    if supervisor_executable is None and software_api is True:
        supervisor_executable = str(Path(sys.executable).resolve())
    supervisor = _verified_executable(supervisor_executable or "")
    _NUKE_BACKGROUND_ROUTE = {
        "supervisor_executable": supervisor,
        "executable": executable,
        "worker_script": str(worker.resolve()),
        "software_api": software_api is True,
        "resource_budget": dict(resource_budget) if resource_budget is not None else None,
    }
    return dict(_NUKE_BACKGROUND_ROUTE)


def _launch_owned_render_subprocess(task_id: str, script_path: str, node_name: str,
                                    first: int, last: int, *, pattern: str,
                                    route: dict[str, str], frame_set: "list[int] | None" = None,
                                    budget_seconds: float = 120, _cold_input_capability=None) -> dict[str, Any]:
    """Task-OWNED isolated background render subprocess (C2 chosen route).

    The trusted control side launches a VERIFIED executable with the bundled
    worker; the worker loads the task-owned NK snapshot and executes frames
    synchronously inside itself.  Software tests inject a Python worker here;
    production passes the verified Nuke executable.  Returns the persisted
    process identity; ownership is bound to THIS task's record only.
    """
    command = [route["executable"]] + ([] if route.get("software_api") is True else ["-t"]) + [route["worker_script"], str(script_path), node_name,
               str(int(first)), str(int(last)), str(pattern),
               json.dumps(list(frame_set or range(int(first), int(last) + 1)), separators=(",", ":"))]
    result_file = _render_records_dir() / (str(task_id) + ".worker-result.json")
    env = os.environ.copy()
    env["BRIDGE_NUKE_TASK_ID"] = str(task_id)
    env["BRIDGE_NUKE_RESULT_FILE"] = str(result_file)
    task = _RENDERS.get(str(task_id))
    contract = (task or {}).get('input_contract')
    contract_sha = None
    if contract is not None:
        from nuke_bridge.operation_receipts import validate_registered_input_contract
        if _cold_input_capability is None:
            validate_registered_input_contract(contract)
        else:
            from nuke_bridge.task_host import _ControllerColdInputs
            try:
                if type(_cold_input_capability) is not _ControllerColdInputs:raise ValueError('private controller capability required')
                _cold_input_capability.freeze_contract(contract)
            except Exception as exc:
                raise RenderDispatchError('controller input preflight failed: '+str(exc),started=False) from exc
        contract_path = _render_records_dir() / (str(task_id)+'.inputs.json')
        if contract_path.is_symlink():raise RenderDispatchError('input contract path is a symlink',started=False)
        content = json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        temporary = contract_path.with_suffix('.tmp-'+uuid4().hex)
        temporary.write_bytes(content);temporary.chmod(0o600);os.replace(temporary,contract_path)
        contract_sha = hashlib.sha256(content).hexdigest()
        env['BRIDGE_NUKE_INPUT_CONTRACT'] = str(contract_path)
        env['BRIDGE_NUKE_INPUT_CONTRACT_SHA256'] = contract_sha
    else:
        env.pop('BRIDGE_NUKE_INPUT_CONTRACT',None);env.pop('BRIDGE_NUKE_INPUT_CONTRACT_SHA256',None)
    composite = (task or {}).get('composite_contract')
    composite_sha = None
    if composite is not None:
        content = json.dumps(composite,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        composite_path = _render_records_dir() / (str(task_id)+'.composite.json')
        if composite_path.is_symlink():raise RenderDispatchError('composite contract path is a symlink',started=False)
        temporary = composite_path.with_suffix('.tmp-'+uuid4().hex)
        temporary.write_bytes(content);temporary.chmod(0o600);os.replace(temporary,composite_path)
        composite_sha = hashlib.sha256(content).hexdigest()
        env['BRIDGE_NUKE_COMPOSITE_CONTRACT'] = str(composite_path)
        env['BRIDGE_NUKE_COMPOSITE_CONTRACT_SHA256'] = composite_sha
        env['BRIDGE_NUKE_OWNER_TASK_ID'] = composite['task_id']
    else:
        env.pop('BRIDGE_NUKE_COMPOSITE_CONTRACT',None);env.pop('BRIDGE_NUKE_COMPOSITE_CONTRACT_SHA256',None)
        env.pop('BRIDGE_NUKE_OWNER_TASK_ID',None)
    if route.get("software_api"):
        env["BRIDGE_NUKE_SOFTWARE_API"] = "1"
    from dcc_task_runtime.owned_process import launch, SupervisorNotStarted
    identity = {"task_id": str(task_id), "operation_id": str(task_id),
                "launch_nonce": uuid4().hex,
                "snapshot_sha256": hashlib.sha256(Path(script_path).read_bytes()).hexdigest()}
    if contract_sha is not None:identity['input_contract_sha256'] = contract_sha
    if composite_sha is not None:identity.update(composite_contract_sha256=composite_sha,owner_task_id=composite['task_id'])
    directory = _render_records_dir() / (str(task_id) + ".supervisor")
    if _cold_input_capability is not None:
        # nonce已生成但尚未准入：这里只封口已完成的输入认证，不重复来源工厂。
        from nuke_bridge.task_host import (_COLD_PROOF_PATH_ENV,_COLD_PROOF_SHA_ENV,
            _COLD_NATIVE_ENV,_COLD_PROOF_ENV,_cold_record)
        try:
            for key in _COLD_NATIVE_ENV|_COLD_PROOF_ENV:env.pop(key,None)
            proof=_cold_input_capability.sign_execution_proof(snapshot_record=_cold_record(Path(script_path)),
                contract_record=_cold_record(contract_path),identity=identity,command=command,env=env,
                slot=(task or {}).get('slot'),result_path=str(result_file))
            env[_COLD_PROOF_PATH_ENV]=proof['path'];env[_COLD_PROOF_SHA_ENV]=proof['sha256']
            identity['cold_proof_sha256']=proof['sha256']
            task['controller_input_proof']=proof
        except Exception as exc:
            raise RenderDispatchError('controller input proof failed before admission: '+str(exc),started=False) from exc
    # Persist intent before spawning; an uncertain startup keeps the slot.
    if task is not None:
        task["supervisor_intent"] = {
            "directory": str(directory), "identity": identity,
            "argv": command, "worker_result": str(result_file),
            "worker_script": route["worker_script"], "argv0": route["executable"]}
        _persist_render_record(task)
    try:
        proc = launch(command, directory=directory, identity=identity,
                      supervisor_executable=route["supervisor_executable"], env=env,
                      budget_seconds=budget_seconds, resource_budget=route.get("resource_budget"),
                      **({'scope_role': 'nuke-render'} if (route.get('resource_budget') or {}).get('native_scope') else {}))
    except SupervisorNotStarted as exc:
        raise RenderDispatchError("owned render was not started: " + str(exc), started=False) from exc
    except Exception as exc:
        raise RenderDispatchError("owned render supervisor start is unconfirmed", started=True) from exc
    return {"pid": int(proc.pid), "kind": "owned_render_subprocess", "worker_result": str(result_file),
            "argv0": route["executable"], "worker_script": route["worker_script"],
            "supervisor_directory": str(directory), "supervisor_identity": identity,
            "argv": command, "handle": proc}


def _render_supervisor_stop_reason(task, observed_rc):
    from dcc_task_runtime.owned_process import read_receipt, execution_returncode
    task_id = str(task.get("task_id") or "")
    process = task.get("process") or {}
    directory = process.get("supervisor_directory")
    identity = process.get("supervisor_identity")
    expected = _render_records_dir() / (task_id + ".supervisor")
    if (not isinstance(directory,str) or Path(directory).absolute() != expected.absolute()
            or not isinstance(identity,dict) or identity.get("task_id") != task_id
            or identity.get("operation_id") != task_id):
        raise ValueError("SUPERVISOR_IDENTITY_MISMATCH")
    stopped = read_receipt(expected,"stopped",identity=identity)
    if (not stopped or stopped.get("pid") != process.get("pid")
            or execution_returncode(stopped) != observed_rc or "stop_reason" not in stopped
            or stopped["stop_reason"] not in {
                None,"CANCEL_REQUESTED","OPERATION_CANCEL_REQUESTED",
                "TIME_BUDGET_EXCEEDED","OPERATION_TIME_BUDGET_EXCEEDED",
                "LOG_BUDGET_EXCEEDED","DISK_BUDGET_EXCEEDED",
                "DISK_BUDGET_UNOBSERVABLE","OPERATION_BUDGET_UNOBSERVABLE",
                "NATIVE_SCOPE_BUDGET_EXCEEDED_OR_UNOBSERVABLE"}):
        raise ValueError("SUPERVISOR_STOP_REASON_UNCONFIRMED")
    return stopped["stop_reason"]


def _render_unconfirmed_stop(task, verification, progress, error):
    _render_history(task,"NEEDS_RECONCILE",note="owned stop evidence is unconfirmed")
    task["stop_evidence_error"] = str(error)[:200]
    _persist_render_record(task)
    return {**task,"executing":True,"progress":progress,"verification":verification,
            "process_exited":None,"stop_confirmed":False}


def _restore_supervised_handle(task):
    from dcc_task_runtime.owned_process import OwnedProcessHandle
    task_id = str(task.get("task_id") or "")
    process = task.get("process") or {}
    intent = task.get("supervisor_intent") or {}
    raw_directory = process.get("supervisor_directory") or intent.get("directory")
    identity = process.get("supervisor_identity") or intent.get("identity")
    if not raw_directory or not isinstance(identity, dict):
        return None
    expected = _render_records_dir() / (task_id + ".supervisor")
    if Path(raw_directory).absolute() != expected.absolute() or identity.get("operation_id") != task_id:
        raise ValueError("SUPERVISOR_IDENTITY_MISMATCH")
    handle = OwnedProcessHandle(expected, identity)
    if process.get("pid") is not None and process["pid"] != handle.pid:
        raise ValueError("SUPERVISOR_PID_MISMATCH")
    if not process:
        expected_argv = intent.get("argv")
        digest = hashlib.sha256(json.dumps(expected_argv, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if not expected_argv or digest != handle.started.get("argv_sha256"):
            raise ValueError("SUPERVISOR_LAUNCH_COMMAND_MISMATCH")
        task["process"] = {"pid": handle.pid, "kind": "owned_render_subprocess",
                           "supervisor_directory": str(expected), "supervisor_identity": identity,
                           **{key: intent[key] for key in ("argv", "argv0", "worker_result", "worker_script")}}
        task["backend"] = "owned_subprocess"
        task["dispatch_state"] = "launched"
        _persist_render_record(task)
    _RENDER_HANDLES[task_id] = handle
    return handle




def _validate_render_binding_owner(binding, write):
    """Keep the logical owner separate from the nrend operation identity."""
    tagged = _metadata(write, 'bridge_task_id') if callable(getattr(write,'knob',None)) else ''
    role = _metadata(write, 'bridge_graph_role') if callable(getattr(write,'knob',None)) else ''
    if binding is None:
        if tagged or role == 'final_write':
            raise ValueError('OUTPUT_BINDING_OWNER_MISMATCH: tagged composite requires an owner binding')
        return
    inputs = binding.get('input_binding') or {}
    host_owner = (_TASK_HOST_IDENTITY or {}).get('task_id')
    owner = binding.get('task_id')
    controlled = bool(host_owner or tagged or role == 'final_write' or inputs.get('schema') == 'bridge.nuke.agent-input-binding/1.0')
    # Historical, non-task-owned bootstrap Read→Write fixtures have no task_id.
    if not controlled and owner is None:
        return
    if (not isinstance(owner,str) or not owner or inputs.get('owner_task_id') != owner
            or (host_owner is not None and host_owner != owner)
            or (tagged and tagged != owner) or (role == 'final_write' and tagged != owner)):
        raise ValueError('OUTPUT_BINDING_OWNER_MISMATCH: input, graph and task-host owners differ')

def _freeze_composite_consumption(write):
    if not callable(getattr(write,'knob',None)) or _metadata(write, 'bridge_graph_role') != 'final_write':
        return None
    import nuke
    from nuke_bridge.operation_receipts import COMPOSITE_SCHEMA, composite_graph_readback
    state = _composite_state(_metadata(write, 'bridge_task_id'))
    if state.get('write') != write.name() or _audit_composite_lineage(state)['lineage']['passed'] is not True:
        raise ValueError('COMPOSITE_CONTRACT_INVALID: approved Write lineage required')
    nodes = {}
    for role, name in state['graph_nodes'].items():
        node = _node(name)
        names = _semantic_knobs_for_role(node, role)
        names += ['disable', 'bridge_task_id', 'bridge_graph_role', 'bridge_input_role']
        if node.Class() in {'Read', 'Write'}:
            names += ['file', 'colorspace', 'raw', 'premultiplied']
        nodes[name] = {'knobs':{key:None for key in dict.fromkeys(names) if node.knob(key) is not None}}
    contract = {'schema':COMPOSITE_SCHEMA, 'task_id':state['task_id'], 'write':write.name(), 'nodes':nodes}
    contract['nodes'] = composite_graph_readback(nuke, contract)
    return contract

def _snapshot_nuke_script(task_id: str, script_path: str) -> str:
    source = Path(str(script_path)).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError("NUKE_SCRIPT_SNAPSHOT_UNAVAILABLE: scriptSave did not produce a regular NK")
    target = _render_records_dir() / (str(task_id) + ".nk")
    if target.is_symlink():
        raise ValueError("NUKE_SCRIPT_SNAPSHOT_UNAVAILABLE: snapshot path is a symlink")
    data = source.read_bytes()
    temporary = target.with_suffix(".tmp-" + uuid4().hex[:8])
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return str(target)


def _nuke_render_operation(command: str, task_key: str, write, first: int, last: int, stride: int,
                           background: bool = False, request_id: "str | None" = None,
                           nuke_executable: "str | None" = None,
                           background_backend: str = "owned", colorspace: str = "",
                           premultiplied: bool | None = None,
                           frame_set: "list[int] | None" = None,
                           pattern_override: "str | None" = None,
                           input_binding: "dict[str, Any] | None" = None,
                           agent_binding: "dict[str, Any] | None" = None,
                           project_color: "dict[str, Any] | None" = None,
                           output_verification: "dict[str, Any] | None" = None,
                           budget_seconds: float = 120) -> dict[str, Any]:
    """THE one heavy-render path (C2): identity, phases, stop semantics.

    - request_id comes from the CALLER or the persistent orchestration step
      and is reused across retries; a NEW request id is a NEW execution even
      with identical output/frames.  The content digest (bound to task, scene
      fingerprint, node, frame set/stride, output, background) is stored
      separately; the same id with different content is CONTENT_CHANGED.
    - durable phases: intent -> reserved -> launched -> result.  An unknown
      dispatch never releases the slot.
    - background uses a task-OWNED controlled subprocess (real process
      identity, real stop); the native ``executeBackgroundNuke`` returns an
      INTEGER task id per the Nuke 17 contract and is handled as
      NativeTaskId - never poll/terminate an int, cancellation reported as
      unsupported.
    - status/cancel are read-only observation plus an actual stop request;
      same-id ACTIVE requests return the existing operation.
    """
    import nuke
    import math
    if type(budget_seconds) not in (int, float) or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 120:
        raise ValueError('INVALID_ARGUMENT: render budget must be finite and within 120 seconds')

    from nuke_bridge.operation_receipts import (AGENT_RENDER_COMMANDS, INPUT_SCHEMA,
        agent_input_binding_valid, registered_input_contract, freeze_agent_inputs)
    if command in AGENT_RENDER_COMMANDS and not agent_input_binding_valid(input_binding,task_id=str(task_key),revalidate=True):
        raise ValueError("INPUT_SOURCE_IDENTITY_REQUIRED: valid frozen agent inputs required")
    input_contract = None
    claimed_input_grade = (input_binding or {}).get('output_verification')
    if command == 'render_write' and isinstance(input_binding, dict) and input_binding.get('kind') == 'artifact_read':
        registry = _nuke_artifact_registry()
        artifact_id = input_binding.get('artifact_id')
        entry = registry.lookup(artifact_id)
        owner = (_TASK_HOST_IDENTITY or {}).get('task_id') or input_binding.get('owner_task_id')
        if (not entry or not owner or entry.get('task_id') != owner
                or input_binding.get('owner_task_id') != owner
                or not registry.verify(artifact_id).get('usable')):
            raise ValueError('INPUT_SOURCE_HASH_MISMATCH: registered input is missing, changed or foreign')
        selected_frames = input_binding.get('frame_set') or frame_set or list(range(int(first), int(last) + 1, max(1, int(stride))))
        if (not isinstance(selected_frames, list) or not selected_frames
                or any(type(frame) is not int or frame not in entry.get('frame_set', []) for frame in selected_frames)
                or len(set(selected_frames)) != len(selected_frames) or len(selected_frames) > 12
                or input_binding.get('read_path', entry['pattern']) != entry['pattern']):
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: registered Read pattern or frames differ')
        snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
        frozen_frames = []
        for frame in selected_frames:
            snapshot = snapshots.get(str(frame)) or {}
            frozen_frames.append({'frame':frame, 'path':snapshot.get('path'),
                                  'sha256':snapshot.get('sha256'), 'bytes':snapshot.get('bytes')})
        input_binding = freeze_agent_inputs(owner, [{'role':'render_input', 'path':entry['pattern'],
            'artifact_id':artifact_id, 'frames':frozen_frames}])
    if command == 'render_write' and isinstance(input_binding,dict) and (
            input_binding.get('schema') == INPUT_SCHEMA or 'frozen_inputs_manifest' in input_binding):
        owner = (_TASK_HOST_IDENTITY or {}).get('task_id') or input_binding.get('owner_task_id')
        input_contract = registered_input_contract(input_binding,_nuke_artifact_registry(),task_id=owner)
    ids = ([input_binding['artifact_id']] if (input_binding or {}).get('artifact_id') else
           [item.get('artifact_id') or item.get('asset_id') for item in
            (input_binding or {}).get('frozen_inputs_manifest', [])])
    registry = _nuke_artifact_registry() if ids else None
    entries = [registry.lookup(artifact_id) for artifact_id in ids]
    grades = [entry.get('output_verification') if entry else None for entry in entries]
    inherited_grade = next((grade for grade in grades if grade is not None), None)
    if inherited_grade is not None:
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        inherited_grade = ArtifactRegistry._output_verification({
            'output_verification': inherited_grade, 'completion_metadata_status': 'AVAILABLE'})
        for artifact_id, entry, grade in zip(ids, entries, grades):
            if (not entry or grade != inherited_grade
                    or entry.get('task_id') != input_binding.get('owner_task_id')
                    or not registry.verify(artifact_id).get('usable')):
                raise ValueError('OUTPUT_VERIFICATION_INPUT_MISMATCH')
    if (output_verification is not None and output_verification != inherited_grade
            or claimed_input_grade is not None and claimed_input_grade != inherited_grade):
        raise ValueError('OUTPUT_VERIFICATION_INPUT_MISMATCH')
    output_verification = json.loads(json.dumps(inherited_grade)) if inherited_grade is not None else None
    selected = [entry['project_color'] for entry in entries if entry and entry.get('project_color') is not None]
    if project_color is not None or selected:
        from dcc_task_runtime.project_color import validate_project_color
        project_color = validate_project_color(project_color if project_color is not None else selected[0])
        if not ids or project_color['colorspace'] != colorspace:
            raise ValueError('PROJECT_COLOR_INPUT_MISMATCH')
        for artifact_id, entry in zip(ids, entries):
            if (not entry or entry.get('project_color') != project_color
                    or entry.get('task_id') != input_binding.get('owner_task_id')
                    or not registry.verify(artifact_id).get('usable')):
                raise ValueError('PROJECT_COLOR_INPUT_MISMATCH')
    node_name = str(write.name())
    if frame_set is None:
        frame_count = (int(last) - int(first)) // max(1, int(stride)) + 1
        if frame_count < 1 or frame_count > 12:
            raise ValueError("INVALID_ARGUMENT: render operation frame count must be 1-12")
        frame_set = list(range(int(first), int(last) + 1, max(1, int(stride))))
    if (not isinstance(frame_set, list) or not frame_set
            or any(type(frame) is not int or frame < 1 for frame in frame_set)
            or len(frame_set) > 12 or len(set(frame_set)) != len(frame_set)):
        raise ValueError("INVALID_ARGUMENT: frame_set must contain unique positive integers (max 12)")
    first, last = min(frame_set), max(frame_set)
    stride = 1
    pattern = str(pattern_override or write["file"].value() or "")
    if not pattern:
        raise ValueError("INVALID_ARGUMENT: output pattern is required")
    if pattern_override is not None:
        knob = write["file"]
        setter = getattr(knob, "setValue", None)
        if not callable(setter):
            raise ValueError("OUTPUT_BINDING_UNAVAILABLE: Write node file knob is not writable")
        setter(str(pattern_override))
    # Materialize the task snapshot before calculating identity.  Repeated
    # requests must not differ merely because the host toggled modified=True
    # to modified=False during scriptSave.
    composite_contract = _freeze_composite_consumption(write) if background else None
    if background:
        nuke.scriptSave()
        if composite_contract is not None:
            from nuke_bridge.operation_receipts import verify_composite_graph
            verify_composite_graph(nuke, composite_contract)
    if composite_contract is not None:
        owner = composite_contract['task_id']
        if ((_TASK_HOST_IDENTITY is not None and _TASK_HOST_IDENTITY.get('task_id') != owner)
                or (input_binding and input_binding.get('owner_task_id') != owner)):
            raise ValueError('OUTPUT_BINDING_OWNER_MISMATCH: composite contract owner differs from execution')
    scene_fingerprint = _nuke_scene_version_fingerprint(nuke)
    content_digest = hashlib.sha256(json.dumps(
        {"command": command, "task_key": str(task_key), "node": node_name,
         "frames": list(frame_set), "pattern": pattern,
         "input_binding": input_binding or {},
         "background": bool(background), "scene": scene_fingerprint,
         **({"project_color": project_color} if project_color is not None else {}),
         **({"output_verification": output_verification} if output_verification is not None else {}),
         **({"input_contract_sha256": _canonical_payload_sha256(input_contract)} if input_contract is not None else {})},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if request_id is not None and str(request_id).strip():
        req = str(request_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{2,120}", req):
            raise ValueError("INVALID_ARGUMENT: request_id must be 2-120 chars of [A-Za-z0-9_.-]")
        task_id = "nrend-" + hashlib.sha256(req.encode("utf-8")).hexdigest()[:16]
        existing = _load_render_record(task_id)
        if existing is not None:
            if existing.get("input_contract") != input_contract:
                raise ValueError("CONTENT_CHANGED: registered input contract differs from recorded request")
            recorded = str(existing.get("request_sha256") or "")
            if recorded and recorded != content_digest:
                raise ValueError("CONTENT_CHANGED: request {} was recorded with different content".format(req))
            if existing.get("state") in {"RUNNING", "CANCEL_PENDING"}:
                return {**existing, "reused": True, "active": True, "operation_id": task_id}
            if existing.get("state") == "NEEDS_RECONCILE":
                # A synchronous host call may have stopped successfully while
                # only the controller ledger write failed.  Retry the same
                # request by registering that persisted fact; never execute
                # the host call again.  Unknown background outcomes remain
                # held for the existing control recovery path.
                if _has_durable_execution_success(existing):
                    try:
                        _register_durable_execution(
                            existing,
                            note="same-request retry registered a durable execution fact",
                        )
                    except Exception as exc:
                        existing["ledger_state"] = "PENDING"
                        existing["ledger_error"] = str(exc)[:200]
                        _persist_render_record(existing)
                        return {**existing, "reused": True, "active": True, "operation_id": task_id}
                    return {**existing, "reused": True, "active": False, "operation_id": task_id}
                return {**existing, "reused": True, "active": True, "operation_id": task_id}
            # Every persisted request is authoritative, including incomplete
            # terminal records.  Retrying never creates another execution.
            return {**existing, "reused": True, "active": not bool(existing.get("slot_released")), "operation_id": task_id}
    else:
        req = "auto-" + uuid4().hex
        task_id = "nrend-" + uuid4().hex[:16]
    script = nuke.root()
    script_name = str(script.name()) if script is not None and hasattr(script, "name") and script.name() else "unsaved-script"
    owner_root = "nuke:{}".format(script_name)
    phase_path = _render_records_dir() / "{}.phase.json".format(task_id)
    phase_path.write_text(json.dumps({"task_id": task_id, "phase": "intent", "request_id": req,
                                      "owner_root": owner_root,
                                      "content_digest": content_digest,
                                      "at": _now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        permit = _fx_graph_scheduler().reserve(owner_root, task_id)
    except ValueError as exc:
        phase_path.unlink(missing_ok=True)  # clean intent: nothing reserved
        raise ValueError("HEAVY_SLOT_BUSY: {}".format(exc))
    phase_path.write_text(json.dumps({"task_id": task_id, "phase": "reserved",
                                      "owner_root": owner_root, "slot_token": str(permit["token"]),
                                      "slot_generation": int(permit["generation"]),
                                      "at": _now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
    task = {"task_id": task_id, "request_id": req, "request_sha256": content_digest,
            "entry": command, "task_key": str(task_key), "background": bool(background),
            "budget_seconds": float(budget_seconds),
            "agent_binding": dict(agent_binding or {}),
            "node": node_name,
            "frame_range": [int(first), int(last)], "frame_set": list(frame_set), "stride": int(stride),
            "pattern": pattern, "scene_fingerprint": scene_fingerprint,
            "input_binding": dict(input_binding or {}),
            "owner_task_id": str((input_binding or {}).get("owner_task_id") or ""),
            "active_frames": list((input_binding or {}).get("active_frames") or frame_set),
            "visual_objective": (input_binding or {}).get("visual_objective"),
            "dependencies": [str(scene_fingerprint)] + list((input_binding or {}).get("dependencies") or []) + (["artifact:" + str(input_binding["artifact_id"])] if (input_binding or {}).get("artifact_id") else []),
            "delivery_confirmations": {
                "colorspace_confirmed": bool(str(colorspace or "")),
                "premultiplied_confirmed": type(premultiplied) is bool,
                "dependencies_confirmed": bool(scene_fingerprint),
            },
            "started_at": threading.get_ident(), "started_at_epoch": _time.time(),
            "cancel_requested": False, "cancel_requested_at": None, "stop_confirmed_at": None,
            "state": "RUNNING", "background_backend": str(background_backend or "owned"),
            "colorspace": str(colorspace or ""), "premultiplied": premultiplied,
            "slot": {"owner_root": owner_root, "operation_id": task_id,
                     "token": str(permit["token"]), "generation": int(permit["generation"])}}
    if project_color is not None:task['project_color'] = project_color
    if output_verification is not None:task['output_verification'] = output_verification
    if input_contract is not None:task['input_contract'] = input_contract
    if composite_contract is not None:
        task['composite_contract'] = composite_contract
        task['owner_task_id'] = composite_contract['task_id']
    _render_history(task, "RUNNING", note="accepted via {}".format(command))
    native_settings = _native_write_output_settings(write, pattern, scene_fingerprint)
    if native_settings:
        native_settings.update(operation_id=task_id, request_id=req)
        task["native_output_settings"] = native_settings
    _RENDERS[task_id] = task
    _persist_render_record(task)
    launched = False
    launch_attempted = False
    synchronous_returned = False
    try:
        _fx_check_disk_budget(Path(pattern).parent, estimated_bytes=len(frame_set) * 4 * 1024 * 1024)
        if background:
            # task-owned controlled subprocess backend (the C2 route)
            nuke.scriptSave()
            if composite_contract is not None:
                verify_composite_graph(nuke, composite_contract)
            if not hmac.compare_digest(_nuke_scene_version_fingerprint(nuke), scene_fingerprint):
                raise ValueError('SCENE_STATE_DRIFT: second save changed the frozen scene')
            script_path = str(nuke.root().name() or "unsaved-script")
            snapshot_path = _snapshot_nuke_script(task_id, script_path)
            task["script_snapshot"] = snapshot_path
            task["dispatch_state"] = "UNKNOWN"
            task["dispatch_started_at"] = _now_iso()
            phase_path.write_text(json.dumps({"task_id": task_id, "phase": "launching",
                                              "at": _now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
            _persist_render_record(task)
            _fx_graph_scheduler().arm(owner_root, task_id, str(permit["token"]))
            launch_attempted = True
            if _NUKE_BACKGROUND_ROUTE is not None:
                process_identity = _launch_owned_render_subprocess(
                    task_id, snapshot_path, node_name, int(first), int(last),
                    pattern=pattern, route=_NUKE_BACKGROUND_ROUTE, frame_set=list(frame_set),
                    budget_seconds=budget_seconds)
            elif _NUKE_BACKGROUND_LAUNCHER is not None:
                process_identity = _NUKE_BACKGROUND_LAUNCHER(task_id, snapshot_path, node_name, int(first), int(last))
            elif str(task.get("background_backend") or "") == "native_task_id":
                exe_path = _verified_executable(nuke_executable or "")
                native_task_id = nuke.executeBackgroundNuke(
                    exe_path, [node_name], [int(first), int(last)], [], {"maxhanbviewers": 0})
                if isinstance(native_task_id, bool) or not isinstance(native_task_id, int) or native_task_id < 0:
                    raise RenderDispatchError("NATIVE_CONTRACT_VIOLATION: invalid native task id", started=False)
                process_identity = {"native_task_id": int(native_task_id), "kind": "native_task_id"}
            else:
                raise RenderDispatchError("BACKGROUND_ROUTE_UNAVAILABLE: controller did not select a worker", started=False)
            launched = True
            # the live handle stays in memory; the PERSISTED identity is JSON
            task["process"] = {k: v for k, v in process_identity.items() if k != "handle"}
            task["backend"] = "native_task_id" if process_identity.get("kind") == "native_task_id" else "owned_subprocess"
            if process_identity.get("kind") == "native_task_id":
                task["native_task_id"] = int(process_identity["native_task_id"])
                task["native_cancel_supported"] = False
            task["dispatch_state"] = "launched"
            _fx_graph_scheduler().bind_process(owner_root, task_id, str(permit["token"]), task["process"])
            _RENDER_HANDLES[task_id] = process_identity.get("handle")
            phase_path.write_text(json.dumps({"task_id": task_id, "phase": "launched",
                                              "pid": process_identity.get("pid"),
                                              "at": _now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
            _persist_render_record(task)
        else:
            # synchronous main-thread render; deterministic frame loop, no
            # exception-driven retry of the host call
            _fx_graph_scheduler().arm(owner_root, task_id, str(permit["token"]))
            launch_attempted = True
            if frame_set == list(range(int(first), int(last) + 1)):
                # Preserve the native contiguous-range call while retaining
                # the exact frame set for sparse requests.
                nuke.execute(write, int(first), int(last))
            else:
                for frame in frame_set:
                    nuke.execute(write, int(frame), int(frame))
            synchronous_returned = True
            verification = _verify(pattern, int(first), int(last),
                                   not_before=float(task.get("started_at_epoch") or 0.0),
                                   frames=list(frame_set))
            if not (verification["ok"] and verification["fresh"]):
                raise ValueError("OUTPUT_INVALID: synchronous render did not produce fresh readable frames")
            # Commit the host execution and observed stop fact before the
            # ledger consumer.  If registration fails, this durable fact is
            # sufficient for a later same-request re-registration.
            _record_synchronous_execution_fact(task, verification)
            launched = True
            _render_history(task, "COMPLETED", note="synchronous render returned")
            task["ledger_state"] = "PENDING"
            _persist_render_record(task)
            task["artifact"] = _register_render_artifact(task)
            task["ledger_state"] = "REGISTERED"
            _fx_release_render_slot(task)  # release only after ledger evidence exists
            task["stop_confirmed_at"] = _now_iso()
            task["slot_released"] = True
            task["execution_fact"]["ledger_state"] = "REGISTERED"
            task["execution_fact"]["registered_at"] = _now_iso()
            _persist_render_record(task)
            phase_path.unlink(missing_ok=True)
    except BaseException as exc:
        _render_history(task, "FAILED", note=str(exc)[:200])
        dispatch_started = (launch_attempted and not synchronous_returned
                            and getattr(exc, "started", None) is not False)
        if launched or dispatch_started:
            task["state"] = "NEEDS_RECONCILE"
            task["dispatch_state"] = "UNKNOWN"
            task["launch_error"] = str(exc)[:200]
            if _has_durable_execution_success(task):
                # The synchronous Nuke call has returned and its execution
                # fact contains the exact output snapshot.  A ledger failure
                # therefore cannot keep the installation slot occupied.
                _mark_verified_stop_pending_ledger(
                    task,
                    note="synchronous execution stopped; artifact ledger registration is pending",
                    error=exc,
                )
            else:
                task["stop_confirmed_at"] = None
        else:
            task["stop_confirmed_at"] = _now_iso()
            _fx_release_render_slot(task)
            phase_path.unlink(missing_ok=True)
        _persist_render_record(task)
        raise
    return {"task_id": task_id, "operation_id": task_id, "reused": False, **task}


def _execute_nuke(write, start: int, end: int, stride: int, *, command: str = "agent.nuke.render",
                  task_key: str = "composite", background: bool = False,
                  request_id: "str | None" = None,
                  agent_binding: "dict[str, Any] | None" = None,
                  input_binding: "dict[str, Any] | None" = None) -> dict[str, Any]:
    """Shared heavy entry: every caller goes through _nuke_render_operation."""
    return _nuke_render_operation(command, task_key, write, start, end, stride, background=background,
                                  request_id=request_id, agent_binding=agent_binding, input_binding=input_binding)


def _agent_inputs_from_params(params):
    from nuke_bridge.operation_receipts import freeze_agent_inputs
    frozen = freeze_agent_inputs(str(params.get("task_id") or ""),params.get("inputs") or [])
    if params.get("agent_input_binding") is not None and params["agent_input_binding"] != frozen:
        raise RuntimeError("INPUT_SOURCE_HASH_MISMATCH: agent binding differs from frozen TaskSpec inputs")
    return frozen


def _require_completed_agent_render(operation):
    if (not isinstance(operation,dict) or operation.get("state") != "COMPLETED"
            or not _has_durable_execution_success(operation)):
        raise RuntimeError("RENDER_RESULT_UNCONFIRMED: operation has no durable completed execution")
    if _snapshot_frames(str(operation["pattern"]),list(operation["frame_set"])) != _immutable_execution_snapshots(operation):
        raise RuntimeError("OUTPUT_CHANGED: completed Nuke operation output changed")


def _begin_composite_write_transaction(
    state: dict[str, Any],
    write,
) -> tuple[list[tuple[Any, str, Any, bool]], dict[str, Any]]:
    rollback: list[tuple[Any, str, Any, bool]] = []
    file_knob = write.knob("file")
    if file_knob is None:
        raise RuntimeError("FINAL_WRITE_SOURCE_DRIFT:file_knob_missing")
    _preflight_static_composite_knob(write, "file", file_knob)
    rollback.append((write, "file", file_knob.value(), True))
    metadata_knob = write.knob("bridge_state_json")
    if metadata_knob is None:
        rollback.append((write, "bridge_state_json", None, False))
    else:
        _preflight_static_composite_knob(write, "bridge_state_json", metadata_knob)
        rollback.append((write, "bridge_state_json", metadata_knob.value(), True))
    return rollback, json.loads(json.dumps(state, ensure_ascii=False))


def _rollback_composite_write_transaction(
    state: dict[str, Any],
    state_before: dict[str, Any],
    rollback: list[tuple[Any, str, Any, bool]],
    cause: Exception,
) -> None:
    restore_errors = _restore_composite_mutations(rollback)
    state.clear()
    state.update(state_before)
    registry = _DELIVERIES if state_before.get("state_schema") == "bridge-skills.nuke-legacy-delivery/2.0" else _COMPOSITES
    registry[str(state_before.get("task_id") or "")] = state
    if restore_errors:
        raise RuntimeError(
            "PARAMETER_RESTORE_FAILED: " + "; ".join(restore_errors)
        ) from cause


def _set_composite_write_phase(
    state: dict[str, Any],
    write,
    *,
    phase: str,
    pattern: str,
) -> str:
    actual = str(_set_knob(write, "file", pattern) or "")
    if not _media_source_binding_matches(pattern, actual):
        raise RuntimeError(f"FINAL_WRITE_SOURCE_DRIFT:{phase}")
    state["final_write_binding"] = {
        "node": write.name(),
        "phase": phase,
        "frozen_path": str(state.get("final_pattern") or ""),
        "readback_path": actual,
    }
    return actual


def _composite_control_state(state: dict[str, Any]) -> dict[str, Any]:
    graph_nodes = dict(state.get("graph_nodes") or {})
    snapshot: dict[str, Any] = {}
    for graph_role, node_name in sorted(graph_nodes.items()):
        if graph_role not in {
            "effect_blur",
            "effect_defocus",
            "effect_denoise",
            "effect_sharpen",
            "effect_glow",
            "effect_contrast",
            "effect_edge",
            "effect_grain",
            "effect_premult",
            "plate_merge",
        }:
            continue
        node = _node(str(node_name))
        knob_names = _semantic_knobs_for_role(node, graph_role)
        if graph_role == "effect_premult":
            knob_names.append("disable")
        elif graph_role == "plate_merge":
            knob_names.extend(name for name in ("mix", "disable") if name not in knob_names)
        elif node.knob("disable") is not None:
            knob_names.append("disable")
        values: dict[str, Any] = {}
        for knob_name in sorted(set(knob_names)):
            knob = node.knob(knob_name)
            if knob is not None:
                _preflight_static_composite_knob(node, knob_name, knob)
                values[knob_name] = knob.value()
        snapshot[graph_role] = values
    return snapshot


def _final_verification_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    write = _node(str(state.get("write") or ""))
    write_file = write.knob("file")
    if write_file is None:
        raise RuntimeError("FINAL_WRITE_SOURCE_DRIFT:file_knob_missing")
    _preflight_static_composite_knob(write, "file", write_file)
    for role, node_name in sorted(dict(state.get("input_nodes") or {}).items()):
        node = _node(str(node_name))
        file_knob = node.knob("file")
        if file_knob is None:
            raise RuntimeError(f"INPUT_SOURCE_DRIFT:{role}")
        _preflight_static_composite_knob(node, "file", file_knob)
    if not isinstance(state.get("final_range"), (list, tuple)) or len(state["final_range"]) != 2:
        return {
            "passed": False,
            "reason": "final_render_missing",
            "verification": {"ok": False, "expected_frames": []},
            "stale_frames": [],
            "unreadable_frames": [],
            "metadata_by_frame": {},
            "artifacts": [],
            "audit": _audit_composite_lineage(state),
            "record": None,
        }
    verify_start, verify_end = state["final_range"]
    stride = max(1, int(state.get("expected_frame_stride") or 1))
    pattern = str(state.get("final_pattern") or "")
    verification = _verify(pattern, int(verify_start), int(verify_end), stride=stride)
    frames = list(verification["expected_frames"])
    stale = _stale_frames(
        pattern,
        frames,
        dict(state.get("final_before") or {}),
        dict(state.get("final_produced") or {}),
    )
    metadata_by_frame, unreadable = _readable_frame_metadata(
        pattern,
        frames,
    ) if verification["ok"] else ({}, [])
    audit = _audit_composite_lineage(state)
    passed = bool(
        verification["ok"]
        and not stale
        and not unreadable
        and audit["lineage"]["passed"]
    )
    artifacts = [_artifact(_frame_path(pattern, frame)) for frame in frames] if passed else []
    record = None
    if passed:
        record = {
            "schema": "bridge-skills.nuke-final-verification/1.0",
            "final_pattern": pattern,
            "first": int(verify_start),
            "last": int(verify_end),
            "stride": stride,
            "frame_count": len(frames),
            "artifact_identity_sha256": _canonical_payload_sha256(artifacts),
            "before_identity_sha256": _canonical_payload_sha256(
                dict(state.get("final_before") or {})
            ),
            "produced_identity_sha256": _canonical_payload_sha256(
                dict(state.get("final_produced") or {})
            ),
            "input_contract_sha256": _canonical_payload_sha256(
                {
                    "paths": state.get("input_source_paths") or {},
                    "bindings": state.get("input_source_bindings") or {},
                    "identities": state.get("input_source_identities") or {},
                }
            ),
            "output_contract_sha256": _canonical_payload_sha256(
                {
                    "output_dir": state.get("output_dir"),
                    "final_pattern": state.get("final_pattern"),
                    "frame_range": state.get("frame_range") or {},
                    "write_binding": state.get("final_write_binding") or {},
                }
            ),
            "graph_contract_sha256": _canonical_payload_sha256(
                {
                    "write": state.get("write"),
                    "input_nodes": state.get("input_nodes") or {},
                    "graph_nodes": state.get("graph_nodes") or {},
                    "controls": _composite_control_state(state),
                }
            ),
        }
        record["verification_identity"] = _canonical_payload_sha256(record)
    return {
        "passed": passed,
        "reason": "" if passed else "final_artifact_verification_failed",
        "verification": verification,
        "stale_frames": stale,
        "unreadable_frames": unreadable,
        "metadata_by_frame": metadata_by_frame,
        "artifacts": artifacts,
        "audit": audit,
        "record": record,
    }


def _require_current_final_verification(state: dict[str, Any]) -> dict[str, Any]:
    stored = state.get("final_verification")
    current = _final_verification_snapshot(state)
    if (
        not current["passed"]
        or not isinstance(stored, dict)
        or not isinstance(current.get("record"), dict)
        or not hmac.compare_digest(
            _canonical_payload_sha256(stored),
            _canonical_payload_sha256(current["record"]),
        )
    ):
        raise RuntimeError("FINAL_VERIFICATION_REQUIRED")
    return current


def _composite_action(command: str, params: dict[str, Any]) -> dict[str, Any]:
    import nuke

    task_id = str(params.get("task_id") or "")
    frame_range = (params.get("render") or {}).get("frame_range") or {}
    start, end, stride, _frame_count = _validated_composite_frame_range(frame_range)
    step_params = params.get("step_params") or {}
    requested_frame = step_params.get("frame")

    if command == "agent.nuke.composite.probe":
        return {
            "gates": [{"name": "nuke_composite_available", "passed": True, "kind": "capability"}],
            "capabilities": {**dispatch("capabilities.get", {}), "domain_pack": "nuke_composite_v1"},
        }
    if command == "agent.nuke.composite.inspect_inputs":
        inputs = _composite_inputs(params)
        identities = _capture_composite_input_identities(
            inputs,
            strict=str(params.get("schema_version") or "") == "2.0",
            expected_frames=list(range(start, end + 1, stride)),
        )
        evidence = []
        for role, item in sorted(inputs.items()):
            path = _frame_path(str(item["path"]), start)
            evidence.append(
                {
                    "role": role,
                    "path": str(path),
                    "exists": path.is_file(),
                    "identity": identities[role],
                }
            )
        return {
            "gates": [
                {
                    "name": "composite_inputs_exist",
                    "passed": all(item["exists"] for item in evidence),
                    "kind": "verification",
                    "inputs": evidence,
                }
            ],
            "inputs": evidence,
        }
    if command == "agent.nuke.composite.build_graph":
        return _build_composite_graph(params)

    required_write_phase = {
        "agent.nuke.composite.verify_preview": "preview",
        "agent.nuke.composite.verify_final": "final",
        "agent.nuke.composite.deliver": "final",
    }.get(command)
    state = _composite_state(task_id, required_write_phase=required_write_phase)
    _validate_composite_input_contract(state, params)
    _validate_composite_output_contract(state, params)
    if command == "agent.nuke.composite.audit_lineage":
        return _audit_composite_lineage(state)
    if command == "agent.nuke.composite.apply_patch":
        return _apply_composite_patch(state, dict(step_params.get("patch") or params.get("patch") or {}))

    write = _node(str(state["write"]))
    if command in {"agent.nuke.composite.render_preview", "agent.nuke.composite.render_final"}:
        audit = _audit_composite_lineage(state)
        if not audit["lineage"]["passed"]:
            raise RuntimeError("reference diagnostic branch is upstream of final Write")

    if command == "agent.nuke.composite.render_preview":
        frame = int(requested_frame if requested_frame is not None else start)
        variant = "".join(character for character in str(step_params.get("variant_id") or "base") if character.isalnum() or character in "-_")[:64] or "base"
        preview_pattern = str(Path(state["output_dir"]) / ("preview.{}.%04d.exr".format(variant)))
        path = _frame_path(preview_pattern, frame)
        before = _snapshot_frames(preview_pattern, [frame])
        rollback, state_before = _begin_composite_write_transaction(state, write)
        if params.get("_agent_render_binding"):
            params["_agent_render_transaction"] = (state, state_before, rollback)
        try:
            _set_composite_write_phase(
                state,
                write,
                phase="preview",
                pattern=preview_pattern,
            )
            operation_result = _execute_nuke(write, frame, frame, 1, command="agent.nuke.composite.render_preview",
                          task_key=str(state.get("task_id") or state.get("output_dir") or "composite"),
                          request_id=params.get("request_id"),
                          input_binding=_agent_inputs_from_params(params),
                          agent_binding={**dict(params.get("_agent_render_binding") or {}), "before_frames": before})
            _require_completed_agent_render(operation_result)
            if operation_result.get("reused"):
                before = dict((operation_result.get("agent_binding") or {}).get("before_frames") or {})
            produced = _snapshot_frames(preview_pattern, [frame])
            state.update(
                {
                    "preview_pattern": preview_pattern,
                    "preview_range": [frame, frame],
                    "preview_before": before,
                    "preview_produced": produced,
                }
            )
            state.pop("final_verification", None)
            topology = _validate_composite_topology(state)
            if not topology["topology"]["passed"]:
                raise RuntimeError(
                    "COMPOSITE_TOPOLOGY_INVALID: "
                    + ", ".join(topology["topology"]["errors"])
                )
            _persist_composite_state(state)
        except Exception as exc:
            _rollback_composite_write_transaction(state, state_before, rollback, exc)
            raise
        return {
            "gates": [
                {
                    "name": "composite_preview_rendered",
                    "passed": True,
                    "kind": "operation",
                    "synchronous": True,
                    "frame": frame,
                }
            ],
            "output_pattern": preview_pattern,
            "before": before,
            "produced": produced,
        }
    if command == "agent.nuke.composite.verify_preview":
        preview_start, preview_end = state.get("preview_range") or [start, start]
        verification = _verify(str(state.get("preview_pattern") or ""), int(preview_start), int(preview_end), stride=1)
        frames = list(verification["expected_frames"])
        stale = _stale_frames(
            str(state.get("preview_pattern") or ""),
            frames,
            dict(state.get("preview_before") or {}),
            dict(state.get("preview_produced") or {}),
        )
        metadata_by_frame, unreadable = _readable_frame_metadata(
            str(state.get("preview_pattern") or ""),
            frames,
        ) if verification["ok"] else ({}, [])
        passed = bool(verification["ok"] and not stale and not unreadable)
        return {
            "gates": [
                {
                    "name": "composite_preview_artifact",
                    "passed": passed,
                    "kind": "verification",
                    **verification,
                    "stale_frames": stale,
                    "unreadable_frames": unreadable,
                    "metadata_by_frame": metadata_by_frame,
                }
            ],
            "artifacts": [
                _artifact(_frame_path(str(state.get("preview_pattern") or ""), frame))
                for frame in frames
            ] if passed else [],
        }
    if command == "agent.nuke.composite.render_final":
        render_start = render_end = int(requested_frame) if requested_frame is not None else start
        if requested_frame is None:
            render_end = end
        frames = list(range(render_start, render_end + 1, stride))
        before = dict(state.get("final_before") or {})
        before.update(_snapshot_frames(str(state["final_pattern"]), frames))
        rollback, state_before = _begin_composite_write_transaction(state, write)
        if params.get("_agent_render_binding"):
            params["_agent_render_transaction"] = (state, state_before, rollback)
        try:
            _set_composite_write_phase(
                state,
                write,
                phase="final",
                pattern=str(state["final_pattern"]),
            )
            operation_result = _execute_nuke(write, render_start, render_end, stride, command="agent.nuke.composite.render_final",
                          task_key=str(state.get("task_id") or state.get("output_dir") or "composite"),
                          request_id=params.get("request_id"),
                          input_binding=_agent_inputs_from_params(params),
                          agent_binding={**dict(params.get("_agent_render_binding") or {}), "before_frames": before})
            _require_completed_agent_render(operation_result)
            if operation_result.get("reused"):
                before = dict((operation_result.get("agent_binding") or {}).get("before_frames") or {})
            produced = dict(state.get("final_produced") or {})
            produced.update(_snapshot_frames(str(state["final_pattern"]), frames))
            state.update(
                {
                    "final_before": before,
                    "final_produced": produced,
                    "final_range": [start, end],
                    "expected_frame_stride": stride,
                }
            )
            state.pop("final_verification", None)
            topology = _validate_composite_topology(state)
            if not topology["topology"]["passed"]:
                raise RuntimeError(
                    "COMPOSITE_TOPOLOGY_INVALID: "
                    + ", ".join(topology["topology"]["errors"])
                )
            _persist_composite_state(state)
        except Exception as exc:
            _rollback_composite_write_transaction(state, state_before, rollback, exc)
            raise
        return {
            "gates": [
                {
                    "name": "composite_final_rendered",
                    "passed": True,
                    "kind": "operation",
                    "synchronous": True,
                    "frames": frames,
                }
            ],
            "output_pattern": state["final_pattern"],
            "before": before,
            "produced": {str(frame): produced.get(str(frame)) or {} for frame in frames},
        }
    if command == "agent.nuke.composite.verify_final":
        snapshot = _final_verification_snapshot(state)
        rollback, state_before = _begin_composite_write_transaction(state, write)
        try:
            if snapshot["passed"]:
                state["final_verification"] = dict(snapshot["record"])
            else:
                state.pop("final_verification", None)
            _persist_composite_state(state)
        except Exception as exc:
            _rollback_composite_write_transaction(state, state_before, rollback, exc)
            raise
        verification = snapshot["verification"]
        audit = snapshot["audit"]
        return {
            "gates": [
                *audit["gates"],
                {
                    "name": "composite_final_artifacts",
                    "passed": snapshot["passed"],
                    "kind": "verification",
                    **verification,
                    "stale_frames": snapshot["stale_frames"],
                    "unreadable_frames": snapshot["unreadable_frames"],
                    "metadata_by_frame": snapshot["metadata_by_frame"],
                    "verification_identity": (
                        (snapshot.get("record") or {}).get("verification_identity")
                    ),
                },
            ],
            "artifacts": snapshot["artifacts"],
        }
    if command == "agent.nuke.composite.deliver":
        _require_current_final_verification(state)
        audit = _audit_composite_lineage(state)
        if not audit["lineage"]["passed"]:
            raise RuntimeError("reference diagnostic branch is upstream of final Write")
        script_path = Path(state["output_dir"]) / f"reference_composite_{_task_key(task_id)}.nk"
        if script_path.is_symlink():
            raise RuntimeError("DELIVERY_ARTIFACT_INVALID: target NK path is a symlink")
        before_artifact = _artifact(script_path) if script_path.is_file() else {}
        nuke.scriptSaveAs(str(script_path), overwrite=True)
        post_save = _audit_saved_composite_script(
            task_id,
            params,
            script_path,
            before_artifact,
        )
        restored = post_save["state"]
        artifact = post_save["artifact"]
        return {
            "gates": [
                *post_save["topology"]["gates"],
                *post_save["lineage"]["gates"],
                {
                    "name": "editable_composite_script",
                    "passed": True,
                    "kind": "verification",
                    "script": str(script_path),
                    "bytes": artifact["bytes"],
                    "sha256": artifact["sha256"],
                    "post_save_reopen_verified": True,
                },
            ],
            "artifacts": [artifact],
            "delivery": {
                **restored,
                "script": str(script_path),
                "script_sha256": artifact["sha256"],
                "post_save_reopen_verified": True,
            },
        }
    raise ValueError(f"unsupported Nuke composite action: {command}")


def _legacy_delivery_expected_frames(params: dict[str, Any]) -> list[int]:
    start, end, step, _count = _validated_composite_frame_range(
        (params.get("render") or {}).get("frame_range") or {}
    )
    return list(range(start, end + 1, step))


def _persist_legacy_delivery_state(state: dict[str, Any]) -> None:
    task_id = str(state.get("task_id") or "")
    if not task_id or state.get("state_schema") != "bridge-skills.nuke-legacy-delivery/2.0":
        raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID")
    write = _node(str(state.get("write") or ""))
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
    _set_hidden_metadata(write, "bridge_state_json", encoded)
    if _metadata(write, "bridge_state_json") != encoded:
        raise RuntimeError("STATE_PERSISTENCE_READBACK_MISMATCH: legacy bridge_state_json")
    _DELIVERIES[task_id] = state


def _restore_legacy_delivery_state(task_id: str) -> dict[str, Any] | None:
    import nuke

    writes = [
        node
        for node in nuke.allNodes(recurseGroups=True)
        if _metadata(node, "bridge_task_id") == task_id
        and _metadata(node, "bridge_graph_role") == "legacy_delivery_write"
    ]
    if not writes:
        return None
    if len(writes) != 1:
        raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID: ambiguous tagged Write")
    encoded = _metadata(writes[0], "bridge_state_json")
    if not encoded:
        raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID: hidden state is missing")
    try:
        state = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID: hidden state is unreadable") from exc
    if (
        not isinstance(state, dict)
        or state.get("state_schema") != "bridge-skills.nuke-legacy-delivery/2.0"
        or str(state.get("task_id") or "") != task_id
        or str(state.get("write") or "") != writes[0].name()
    ):
        raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID: hidden state subject changed")
    _DELIVERIES[task_id] = state
    return state


def _validate_legacy_delivery_graph(
    state: dict[str, Any],
    params: dict[str, Any],
    *,
    required_write_phase: str | None = None,
) -> dict[str, Any]:
    task_id = str(params.get("task_id") or "")
    if str(state.get("task_id") or "") != task_id:
        raise RuntimeError("LEGACY_DELIVERY_SPEC_DRIFT:task_id")
    requested_source = _delivery_input(params)
    source = str(state.get("source") or "")
    if not _media_source_binding_matches(source, requested_source):
        raise RuntimeError("LEGACY_DELIVERY_SPEC_DRIFT:source")
    configured_output = str((params.get("render") or {}).get("output_dir") or "").strip()
    if configured_output and (
        Path(configured_output).expanduser().resolve(strict=False)
        != Path(str(state.get("output_dir") or "")).expanduser().resolve(strict=False)
    ):
        raise RuntimeError("LEGACY_DELIVERY_SPEC_DRIFT:output_dir")

    read = _node(str(state.get("read") or ""))
    write = _node(str(state.get("write") or ""))
    if _node_class_name(read) != "Read" or _node_class_name(write) != "Write":
        raise RuntimeError("LEGACY_DELIVERY_TOPOLOGY_INVALID:node_class")
    if (
        _metadata(read, "bridge_task_id") != task_id
        or _metadata(write, "bridge_task_id") != task_id
        or _metadata(read, "bridge_graph_role") != "legacy_delivery_read"
        or _metadata(write, "bridge_graph_role") != "legacy_delivery_write"
    ):
        raise RuntimeError("LEGACY_DELIVERY_TOPOLOGY_INVALID:task_tags")
    read_file = read.knob("file")
    write_file = write.knob("file")
    if read_file is None or write_file is None:
        raise RuntimeError("LEGACY_DELIVERY_TOPOLOGY_INVALID:file_knob")
    _preflight_static_composite_knob(read, "file", read_file)
    _preflight_static_composite_knob(write, "file", write_file)
    actual_source = str(read_file.value() or "")
    actual_final = str(write_file.value() or "")
    if not _media_source_binding_matches(source, actual_source):
        raise RuntimeError("LEGACY_DELIVERY_SOURCE_DRIFT")
    write_phase = str(state.get("write_phase") or "final")
    if required_write_phase and write_phase != required_write_phase:
        raise RuntimeError(f"LEGACY_DELIVERY_OUTPUT_DRIFT:{required_write_phase}")
    expected_write = (
        str(state.get("preview_pattern") or "")
        if write_phase == "preview"
        else str(state.get("final_pattern") or "")
    )
    if write_phase not in {"preview", "final"} or not expected_write:
        raise RuntimeError("LEGACY_DELIVERY_OUTPUT_DRIFT:phase")
    if not _media_source_binding_matches(expected_write, actual_final):
        raise RuntimeError("LEGACY_DELIVERY_OUTPUT_DRIFT")
    try:
        connected = write.input(0) if int(write.inputs()) > 0 else None
    except Exception as exc:
        raise RuntimeError("LEGACY_DELIVERY_TOPOLOGY_INVALID:connection") from exc
    if connected is None or not _same_nuke_node(connected, read):
        raise RuntimeError("LEGACY_DELIVERY_TOPOLOGY_INVALID:connection")
    identity = _revalidate_composite_input_identity(
        "effect_render",
        source,
        state.get("source_identity"),
        strict=str(params.get("schema_version") or "") == "2.0",
        expected_frames=_legacy_delivery_expected_frames(params),
    )
    if not identity.get("matched"):
        raise RuntimeError("INPUT_SOURCE_HASH_MISMATCH:effect_render")
    return {
        "read": read.name(),
        "write": write.name(),
        "source": actual_source,
        "final_pattern": actual_final,
        "write_phase": write_phase,
        "source_identity": identity,
        "connected": True,
    }


def _require_legacy_final_verification(state: dict[str, Any]) -> dict[str, Any]:
    record = state.get("final_verification")
    if not isinstance(record, dict):
        raise RuntimeError("FINAL_VERIFICATION_REQUIRED: legacy delivery has no verified render")
    unsigned = {key: value for key, value in record.items() if key != "verification_identity"}
    if not hmac.compare_digest(
        str(record.get("verification_identity") or ""),
        _canonical_payload_sha256(unsigned),
    ):
        raise RuntimeError("FINAL_VERIFICATION_STALE: legacy verification identity changed")
    artifacts = []
    for frame in record.get("frames") or []:
        path = _frame_path(str(state.get("final_pattern") or ""), int(frame))
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("FINAL_VERIFICATION_STALE: legacy final artifact is missing")
        artifacts.append(_artifact(path))
    current = {
        "frames": list(record.get("frames") or []),
        "artifacts": artifacts,
        "final_pattern": str(state.get("final_pattern") or ""),
        "graph_contract": record.get("graph_contract"),
    }
    if _canonical_payload_sha256(current) != str(record.get("current_identity") or ""):
        raise RuntimeError("FINAL_VERIFICATION_STALE: legacy final artifacts changed")
    return record


def _audit_saved_legacy_script(
    task_id: str,
    params: dict[str, Any],
    state: dict[str, Any],
    script_path: Path,
    before_artifact: dict[str, Any],
) -> dict[str, Any]:
    import nuke

    if script_path.is_symlink() or not script_path.is_file():
        raise RuntimeError("DELIVERY_ARTIFACT_INVALID: saved NK is not a regular file")
    saved = _artifact(script_path)
    if before_artifact and int(saved.get("modified_ns") or 0) <= int(
        before_artifact.get("modified_ns") or 0
    ):
        raise RuntimeError("DELIVERY_ARTIFACT_STALE: Nuke did not rewrite the delivery script")
    try:
        modified = nuke.modified()
    except Exception as exc:
        raise RuntimeError("DELIVERY_POST_SAVE_DIRTY: Nuke modified state is unavailable") from exc
    if modified is not False:
        raise RuntimeError("DELIVERY_POST_SAVE_DIRTY: save callback left unsaved scene changes")
    try:
        reopen = dispatch(
            "open_script",
            {"path": str(script_path), "sha256": str(saved["sha256"])},
        )
    except Exception as exc:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: saved NK could not be safely reopened") from exc
    try:
        current = Path(str(nuke.root().name() or "")).expanduser().resolve()
        clean = nuke.modified()
    except Exception as exc:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: reopened NK state is unavailable") from exc
    if current != script_path.resolve() or clean is not False:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: reopened NK path/state did not read back")
    reopened = _artifact(script_path)
    if (
        int(reopened.get("bytes") or -1) != int(saved.get("bytes") or -2)
        or not hmac.compare_digest(str(reopened.get("sha256") or ""), str(saved.get("sha256") or ""))
    ):
        raise RuntimeError("DELIVERY_ARTIFACT_DRIFT: saved NK bytes changed during reopen")
    try:
        restored = _restore_legacy_delivery_state(task_id)
        if restored is None:
            raise RuntimeError("saved NK has no legacy delivery state")
        graph = _validate_legacy_delivery_graph(
            restored,
            params,
            required_write_phase="final",
        )
        verification = _require_legacy_final_verification(restored)
    except Exception as exc:
        raise RuntimeError("DELIVERY_POST_SAVE_AUDIT_FAILED: legacy NK contract failed") from exc
    return {
        "state": restored,
        "artifact": reopened,
        "graph": graph,
        "verification": verification,
        "reopen": reopen,
    }


def _delivery_action(command: str, params: dict[str, Any]) -> dict[str, Any]:
    import nuke

    task_id = str(params.get("task_id") or "")
    if command == "agent.nuke.probe":
        return {"gates": [{"name": "nuke_running", "passed": True, "kind": "capability"}], "capabilities": dispatch("capabilities.get", {})}
    if command == "agent.nuke.inspect_input":
        source = _delivery_input(params)
        exists = _frame_path(source, int(((params.get("render") or {}).get("frame_range") or {}).get("start", 1))).is_file()
        return {"gates": [{"name": "source_exr", "passed": exists, "kind": "verification", "path": source}]}
    if command == "agent.nuke.build_graph":
        state = _DELIVERIES.get(task_id) or _restore_legacy_delivery_state(task_id)
        if state is None:
            source_item = _delivery_input_item(params)
            source = str(source_item["path"])
            source_identity = _capture_composite_input_identity(
                "effect_render",
                source_item,
                strict=str(params.get("schema_version") or "") == "2.0",
                expected_frames=_legacy_delivery_expected_frames(params),
            )
            output_dir = _delivery_output_dir(params)
            key = _task_key(task_id)
            with nuke.Undo("Nuke Agent render delivery"):
                read = nuke.nodes.Read(name=f"AGENT_READ_{key}")
                read["file"].setValue(source)
                write = nuke.nodes.Write(name=f"AGENT_WRITE_{key}", inputs=[read])
                final_pattern = str(output_dir / "final.%04d.exr")
                write["file"].setValue(final_pattern)
                read.setXpos(0)
                write.setXpos(220)
                _tag_node(
                    read,
                    task_id,
                    input_role="effect_render",
                    graph_role="legacy_delivery_read",
                    schema_version=str(params.get("schema_version") or "1.0"),
                )
                _tag_node(
                    write,
                    task_id,
                    graph_role="legacy_delivery_write",
                    schema_version=str(params.get("schema_version") or "1.0"),
                )
            state = {
                "state_schema": "bridge-skills.nuke-legacy-delivery/2.0",
                "task_id": task_id,
                "schema_version": str(params.get("schema_version") or "1.0"),
                "read": read.name(),
                "write": write.name(),
                "source": source,
                "source_identity": source_identity,
                "final_pattern": final_pattern,
                "write_phase": "final",
                "output_dir": str(output_dir.resolve(strict=False)),
            }
            _persist_legacy_delivery_state(state)
        graph = _validate_legacy_delivery_graph(state, params)
        return {
            "gates": [
                {
                    "name": "editable_nuke_graph",
                    "passed": True,
                    "kind": "verification",
                    "source_identity": graph["source_identity"],
                    "read": state["read"],
                    "write": state["write"],
                }
            ],
            "graph": state,
        }
    state = _DELIVERIES.get(task_id) or _restore_legacy_delivery_state(task_id)
    if state is None:
        raise RuntimeError("delivery graph missing; run agent.nuke.build_graph first")
    required_write_phase = {
        "agent.nuke.verify_preview": "preview",
        "agent.nuke.verify_final": "final",
        "agent.nuke.deliver": "final",
    }.get(command)
    _validate_legacy_delivery_graph(
        state,
        params,
        required_write_phase=required_write_phase,
    )
    frame_range = (params.get("render") or {}).get("frame_range") or {}
    full_start = int(frame_range.get("start", 1) if isinstance(frame_range, dict) else 1)
    full_end = int(frame_range.get("end", full_start) if isinstance(frame_range, dict) else full_start)
    full_stride = max(1, int(frame_range.get("step", 1) if isinstance(frame_range, dict) else 1))
    start, end = full_start, full_end
    step_params = params.get("step_params") or {}
    requested_frame = step_params.get("frame")
    if requested_frame is not None:
        start = end = int(requested_frame)
    write = _node(state["write"])
    if command == "agent.nuke.render_preview":
        state.pop("final_verification", None)
        preview_pattern = str(Path(state["output_dir"]) / "preview.%04d.exr")
        write["file"].setValue(preview_pattern)
        before = dict(state.get("preview_before") or {})
        candidate = _frame_path(preview_pattern, start)
        if candidate.is_file():
            before[str(start)] = _artifact(candidate)
        else:
            before[str(start)] = {}
        operation_result = _execute_nuke(write, start, start, 1, command="agent.nuke.render_preview",
                      task_key=str(state.get("task_id") or state.get("output_dir") or "legacy"),
                      request_id=params.get("request_id"),
                      input_binding=_agent_inputs_from_params(params),
                      agent_binding={**dict(params.get("_agent_render_binding") or {}), "before_frames": before})
        _require_completed_agent_render(operation_result)
        if operation_result.get("reused"):
            before = dict((operation_result.get("agent_binding") or {}).get("before_frames") or {})
        produced = _snapshot_frames(preview_pattern, [start])
        state["preview_pattern"] = preview_pattern
        state["write_phase"] = "preview"
        state["preview_range"] = [start, start]
        state["preview_before"] = before
        state["preview_produced"] = produced
        _persist_legacy_delivery_state(state)
        return {
            "gates": [
                {
                    "name": "preview_rendered",
                    "passed": True,
                    "kind": "operation",
                    "synchronous": True,
                    "frame": start,
                }
            ],
            "output_pattern": preview_pattern,
            "before": {str(start): before[str(start)]},
            "produced": produced,
        }
    if command == "agent.nuke.verify_preview":
        verification = _verify(str(state.get("preview_pattern") or ""), start, start)
        frames = list(verification["expected_frames"])
        stale = _stale_frames(
            str(state.get("preview_pattern") or ""),
            frames,
            dict(state.get("preview_before") or {}),
            dict(state.get("preview_produced") or {}),
        )
        metadata_by_frame, unreadable = _readable_frame_metadata(
            str(state.get("preview_pattern") or ""),
            frames,
        ) if verification["ok"] else ({}, [])
        metadata = metadata_by_frame.get(str(start)) or {}
        expected = (params.get("render") or {}).get("resolution") or []
        size_ok = not expected or metadata.get("width") == int(expected[0]) and metadata.get("height") == int(expected[1])
        passed = bool(verification["ok"] and not stale and not unreadable and size_ok)
        return {
            "gates": [
                {
                    "name": "preview_artifact",
                    "passed": passed,
                    "kind": "verification",
                    **verification,
                    "stale_frames": stale,
                    "unreadable_frames": unreadable,
                    "metadata": metadata,
                    "metadata_by_frame": metadata_by_frame,
                    "resolution_ok": size_ok,
                }
            ],
            "artifacts": [_artifact(_frame_path(state["preview_pattern"], start))] if passed else [],
        }
    if command == "agent.nuke.render_final":
        state.pop("final_verification", None)
        write["file"].setValue(state["final_pattern"])
        state["write_phase"] = "final"
        before = dict(state.get("final_before") or {})
        for frame in range(start, end + 1):
            candidate = _frame_path(state["final_pattern"], frame)
            if candidate.is_file():
                before[str(frame)] = _artifact(candidate)
            else:
                before[str(frame)] = {}
        operation_result = _execute_nuke(write, start, end, full_stride, command="agent.nuke.render_final",
                      task_key=str(state.get("task_id") or state.get("output_dir") or "legacy"),
                      request_id=params.get("request_id"),
                      input_binding=_agent_inputs_from_params(params),
                      agent_binding={**dict(params.get("_agent_render_binding") or {}), "before_frames": before})
        _require_completed_agent_render(operation_result)
        if operation_result.get("reused"):
            before = dict((operation_result.get("agent_binding") or {}).get("before_frames") or {})
        produced = dict(state.get("final_produced") or {})
        produced.update(_snapshot_frames(state["final_pattern"], list(range(start, end + 1))))
        state["final_before"] = before
        state["final_produced"] = produced
        state["final_range"] = [full_start, full_end]
        state["final_stride"] = full_stride
        _persist_legacy_delivery_state(state)
        return {
            "gates": [
                {
                    "name": "final_rendered",
                    "passed": True,
                    "kind": "operation",
                    "synchronous": True,
                    "frames": list(range(start, end + 1)),
                }
            ],
            "output_pattern": state["final_pattern"],
            "before": {str(frame): before.get(str(frame)) or {} for frame in range(start, end + 1)},
            "produced": {str(frame): produced.get(str(frame)) or {} for frame in range(start, end + 1)},
        }
    if command == "agent.nuke.verify_final":
        verify_start, verify_end = state.get("final_range") or [full_start, full_end]
        verification = _verify(
            state["final_pattern"],
            int(verify_start),
            int(verify_end),
            stride=max(1, int(state.get("final_stride") or full_stride)),
        )
        frames = list(verification["expected_frames"])
        stale = _stale_frames(
            str(state["final_pattern"]),
            frames,
            dict(state.get("final_before") or {}),
            dict(state.get("final_produced") or {}),
        )
        metadata_by_frame, unreadable = _readable_frame_metadata(
            str(state["final_pattern"]),
            frames,
        ) if verification["ok"] else ({}, [])
        metadata = metadata_by_frame.get(str(int(verify_start))) or {}
        expected = (params.get("render") or {}).get("resolution") or []
        size_ok = not expected or metadata.get("width") == int(expected[0]) and metadata.get("height") == int(expected[1])
        passed = bool(verification["ok"] and not stale and not unreadable and size_ok)
        artifacts = [_artifact(_frame_path(state["final_pattern"], frame)) for frame in verification["expected_frames"]] if passed else []
        if passed:
            graph_contract = _canonical_payload_sha256(
                {
                    "task_id": task_id,
                    "read": state["read"],
                    "write": state["write"],
                    "source": state["source"],
                    "source_identity": state["source_identity"],
                    "final_pattern": state["final_pattern"],
                }
            )
            current = {
                "frames": list(verification["expected_frames"]),
                "artifacts": artifacts,
                "final_pattern": str(state["final_pattern"]),
                "graph_contract": graph_contract,
            }
            record = {
                **current,
                "graph_contract": graph_contract,
                "current_identity": _canonical_payload_sha256(current),
            }
            record["verification_identity"] = _canonical_payload_sha256(record)
            state["final_verification"] = record
        else:
            state.pop("final_verification", None)
        _persist_legacy_delivery_state(state)
        return {
            "gates": [
                {
                    "name": "final_artifacts",
                    "passed": passed,
                    "kind": "verification",
                    **verification,
                    "stale_frames": stale,
                    "unreadable_frames": unreadable,
                    "metadata": metadata,
                    "metadata_by_frame": metadata_by_frame,
                    "resolution_ok": size_ok,
                }
            ],
            "artifacts": artifacts,
        }
    if command == "agent.nuke.deliver":
        _require_legacy_final_verification(state)
        output_dir = Path(state["output_dir"])
        script_path = output_dir / ("nuke_delivery_{}.nk".format(_task_key(task_id)))
        if script_path.is_symlink():
            raise RuntimeError("DELIVERY_ARTIFACT_INVALID: target NK path is a symlink")
        before_artifact = _artifact(script_path) if script_path.is_file() else {}
        nuke.scriptSaveAs(str(script_path), overwrite=True)
        post_save = _audit_saved_legacy_script(
            task_id,
            params,
            state,
            script_path,
            before_artifact,
        )
        artifact = post_save["artifact"]
        restored = post_save["state"]
        return {
            "gates": [
                {
                    "name": "delivery_ready",
                    "passed": True,
                    "kind": "verification",
                    "script": str(script_path),
                    "bytes": artifact["bytes"],
                    "sha256": artifact["sha256"],
                    "post_save_reopen_verified": True,
                }
            ],
            "artifacts": [artifact],
            "delivery": {
                **restored,
                "script": str(script_path),
                "script_sha256": artifact["sha256"],
                "post_save_reopen_verified": True,
            },
        }
    raise ValueError(f"unsupported Nuke delivery action: {command}")


def _audit_saved_composite_script(
    task_id: str,
    params: dict[str, Any],
    script_path: Path,
    before_artifact: dict[str, Any],
) -> dict[str, Any]:
    """Reopen and validate the actual NK bytes produced by delivery."""

    import nuke

    if script_path.is_symlink() or not script_path.is_file():
        raise RuntimeError("DELIVERY_ARTIFACT_INVALID: saved NK is not a regular file")
    saved_artifact = _artifact(script_path)
    if before_artifact and int(saved_artifact.get("modified_ns") or 0) <= int(
        before_artifact.get("modified_ns") or 0
    ):
        raise RuntimeError("DELIVERY_ARTIFACT_STALE: Nuke did not rewrite the delivery script")
    try:
        modified = nuke.modified()
    except Exception as exc:
        raise RuntimeError("DELIVERY_POST_SAVE_DIRTY: Nuke modified state is unavailable") from exc
    if modified is not False:
        raise RuntimeError("DELIVERY_POST_SAVE_DIRTY: save callback left unsaved scene changes")

    try:
        reopen = dispatch(
            "open_script",
            {"path": str(script_path), "sha256": str(saved_artifact["sha256"])},
        )
    except Exception as exc:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: saved NK could not be safely reopened") from exc
    try:
        current_path = Path(str(nuke.root().name() or "")).expanduser().resolve()
        reopened_modified = nuke.modified()
    except Exception as exc:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: reopened NK state is unavailable") from exc
    if current_path != script_path.resolve() or reopened_modified is not False:
        raise RuntimeError("DELIVERY_REOPEN_FAILED: reopened NK path/state did not read back")
    reopened_artifact = _artifact(script_path)
    if (
        int(reopened_artifact.get("bytes") or -1) != int(saved_artifact.get("bytes") or -2)
        or not hmac.compare_digest(
            str(reopened_artifact.get("sha256") or ""),
            str(saved_artifact.get("sha256") or ""),
        )
    ):
        raise RuntimeError("DELIVERY_ARTIFACT_DRIFT: saved NK bytes changed during reopen")

    try:
        restored = _composite_state(task_id, required_write_phase="final")
        input_contract = _validate_composite_input_contract(restored, params)
        output_contract = _validate_composite_output_contract(restored, params)
        _require_current_final_verification(restored)
        topology = _validate_composite_topology(restored)
        lineage = _audit_composite_lineage(restored)
        if not topology["topology"]["passed"] or not lineage["lineage"]["passed"]:
            raise RuntimeError("saved NK topology or reference lineage failed")
    except Exception as exc:
        raise RuntimeError("DELIVERY_POST_SAVE_AUDIT_FAILED: saved NK contract failed") from exc
    return {
        "state": restored,
        "artifact": reopened_artifact,
        "topology": topology,
        "lineage": lineage,
        "input_contract": input_contract,
        "output_contract": output_contract,
        "reopen": reopen,
    }


_STRICTLY_READ_ONLY_AGENT_ACTIONS = {
    "agent.nuke.probe",
    "agent.nuke.inspect_input",
    "agent.nuke.verify_preview",
    "agent.nuke.verify_final",
    "agent.nuke.composite.probe",
    "agent.nuke.composite.inspect_inputs",
    "agent.nuke.composite.audit_lineage",
    "agent.nuke.composite.verify_preview",
}
_TASK_SCENE_MUTATION_ACTIONS = {
    "agent.nuke.build_graph",
    "agent.nuke.render_preview",
    "agent.nuke.render_final",
    "agent.nuke.composite.build_graph",
    "agent.nuke.composite.apply_patch",
    "agent.nuke.composite.render_preview",
    "agent.nuke.composite.render_final",
    # Final verification persists the exact artifact proof into the tagged
    # Write so delivery remains restart-safe.
    "agent.nuke.composite.verify_final",
}


def _dispatch_agent_with_scene_contract(
    command: str,
    params: dict[str, Any],
    callback,
) -> dict[str, Any]:
    task_id = str(params.get("task_id") or "")
    expected_pre = str(params.get("expected_pre_scene_fingerprint") or "").strip().lower()
    pre = _post_scene_state(task_id)
    if expected_pre:
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected_pre) is None
            or not bool(pre.get("fingerprint_complete"))
            or not hmac.compare_digest(str(pre.get("scene_fingerprint") or ""), expected_pre)
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene changed before action execution")

    params.pop("_agent_render_transaction", None)
    request = str(params.get("request_id") or "")
    render_action = command in {"agent.nuke.render_preview", "agent.nuke.render_final",
                               "agent.nuke.composite.render_preview", "agent.nuke.composite.render_final"}
    if render_action:
        params["agent_input_binding"] = _agent_inputs_from_params(params)
    operation = "nrend-" + hashlib.sha256(request.encode("utf-8")).hexdigest()[:16] if request else ""
    request_digest = _canonical_payload_sha256({key: value for key, value in params.items()
        if key not in {"request_id", "expected_pre_scene_fingerprint", "_agent_render_binding"}})
    previous = _load_render_record(operation) if operation and render_action else None
    if previous and previous.get("agent_binding"):
        bound = previous["agent_binding"]
        if bound.get("command") != command or bound.get("payload_sha256") != request_digest:
            raise RuntimeError("CONTENT_CHANGED: Nuke agent request content differs from its persisted binding")
    if previous and isinstance(previous.get("agent_result"), dict):
        binding = previous.get("agent_binding") or {}
        saved = previous["agent_result"]
        saved_post = saved.get("post_scene_state") or {}
        if (binding.get("command") != command or binding.get("payload_sha256") != request_digest
                or not pre.get("fingerprint_complete")
                or not hmac.compare_digest(str(pre.get("scene_fingerprint") or ""),
                                            str(saved_post.get("scene_fingerprint") or ""))):
            raise RuntimeError("CONTENT_CHANGED: completed Nuke agent request differs from its saved result")
        if previous.get("input_binding") != params.get("agent_input_binding"):
            raise RuntimeError("INPUT_SOURCE_HASH_MISMATCH: saved operation inputs differ")
        if previous.get("state") != "COMPLETED" or not _has_durable_execution_success(previous):
            raise RuntimeError("RENDER_RESULT_UNCONFIRMED: saved agent result lacks completed execution")
        if command.startswith("agent.nuke.composite."):
            restored = _composite_state(task_id)
            _validate_composite_input_contract(restored, params)
            _validate_composite_output_contract(restored, params)
            if not _validate_composite_topology(restored)["topology"]["passed"]:
                raise RuntimeError("COMPOSITE_TOPOLOGY_INVALID: recovered graph differs")
        else:
            restored = _DELIVERIES.get(task_id) or _restore_legacy_delivery_state(task_id)
            if restored is None:
                raise RuntimeError("LEGACY_DELIVERY_STATE_INVALID: recovered graph missing")
            _validate_legacy_delivery_graph(restored, params)
        current = _snapshot_frames(str(previous["pattern"]), list(previous["frame_set"]))
        if current != _immutable_execution_snapshots(previous):
            raise RuntimeError("OUTPUT_CHANGED: completed Nuke request output changed")
        result = json.loads(json.dumps(saved))
        result["pre_scene_state"] = pre
        result["post_scene_state"] = pre
        return result
    if render_action and request:
        params["_agent_render_binding"] = {"command": command, "payload_sha256": request_digest,
                                           "pre_scene_state": pre}
        if not command.startswith("agent.nuke.composite."):
            state = _DELIVERIES.get(task_id) or _restore_legacy_delivery_state(task_id)
            if state is not None:
                rollback, state_before = _begin_composite_write_transaction(state, _node(str(state["write"])))
                params["_agent_render_transaction"] = (state, state_before, rollback)
    try:
        result = callback()
    except Exception as exc:
        transaction = params.get("_agent_render_transaction")
        if transaction and not command.startswith("agent.nuke.composite."):
            _rollback_composite_write_transaction(*transaction, exc)
        raise
    post = _post_scene_state(task_id)
    if expected_pre and command in _STRICTLY_READ_ONLY_AGENT_ACTIONS:
        if (
            not bool(post.get("fingerprint_complete"))
            or not hmac.compare_digest(
                str(pre.get("scene_fingerprint") or ""),
                str(post.get("scene_fingerprint") or ""),
            )
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: read-only Nuke action changed the scene")
    if expected_pre and command in _TASK_SCENE_MUTATION_ACTIONS:
        for field in ("non_task_scene_fingerprint", "global_scene_fingerprint"):
            if (
                not bool(post.get("fingerprint_complete"))
                or not hmac.compare_digest(str(pre.get(field) or ""), str(post.get(field) or ""))
            ):
                raise RuntimeError(
                    "SCENE_STATE_DRIFT: Nuke action changed non-task/global scene state"
                )
    result["pre_scene_state"] = pre
    result["post_scene_state"] = post
    if render_action and operation:
        completed = _load_render_record(operation)
        if completed and completed.get("state") == "COMPLETED" and _has_durable_execution_success(completed):
            completed["agent_result"] = json.loads(json.dumps(result))
            try:
                _persist_render_record(completed)
            except Exception as exc:
                committed = _load_render_record(operation)
                if not committed or committed.get("agent_result") != completed["agent_result"]:
                    transaction = params.get("_agent_render_transaction")
                    if transaction:
                        _rollback_composite_write_transaction(*transaction, exc)
                    raise
                completed = committed
            _RENDERS[operation] = completed
    return result



def nuke_render_status(task_id: str) -> dict[str, Any]:
    """只观察持久记录、真实worker与签名停止；冷端查询不需要导入Nuke API。"""
    task = _RENDERS.get(task_id) or _load_render_record(task_id)
    if task is None:
        raise ValueError("render task not found")
    expected_frames = list(task.get("frame_set") or [])
    verification = _verify(task["pattern"], int(task["frame_range"][0]), int(task["frame_range"][1]),
                           not_before=float(task.get("started_at_epoch") or 0.0),
                           frames=expected_frames or None)
    total = len(expected_frames) or (int(task["frame_range"][1]) - int(task["frame_range"][0]) + 1)
    complete = (total - len(verification["missing"]) - len(verification["too_small"])
                - len(verification["unreadable"]) - len(verification["stale_frames"])
                )
    done = bool(verification["ok"] and verification["fresh"])
    try:
        handle = _RENDER_HANDLES.get(task_id) or _restore_supervised_handle(task)
        observed_rc = handle.poll() if handle is not None else None
    except (ValueError,OSError,KeyError,TypeError) as exc:
        return _render_unconfirmed_stop(task,verification,complete / total if total else 1.0,exc)
    if handle is not None and task.get("state") == "NEEDS_RECONCILE" and not _has_durable_execution_success(task):
        _render_history(task, "CANCEL_PENDING" if task.get("cancel_requested") else "RUNNING", note="exact owned supervisor receipt rebound")
    process_exited = observed_rc is not None if handle is not None else None
    if process_exited is None and task.get("backend") == "owned_subprocess":
        # handle lost (host restart): observe the persisted pid read-only
        pid = int((task.get("process") or {}).get("pid") or 0)
        # PID absence cannot prove this owned attempt stopped. Only the
        # original handle or a verified supervisor receipt may do so.
        process_exited = None
        if task.get("state") in {"RUNNING", "CANCEL_PENDING"}:
            _render_history(task, "NEEDS_RECONCILE", note="owned process handle unavailable; stop unconfirmed")
            _persist_render_record(task)
    if task.get("backend") == "native_task_id" and process_exited is None:
        # native int task ids have no poll/observation contract here
        process_exited = None
    if process_exited and not task.get("slot_released") and task.get("state") in ("RUNNING", "CANCEL_PENDING"):
        handle_known_rc = handle is not None  # we observed THIS process's rc
        stop_reason = None
        if task.get("state") == "CANCEL_PENDING" or (task.get('process') or {}).get('supervisor_directory'):
            try:
                stop_reason = _render_supervisor_stop_reason(task,observed_rc)
                task["supervisor_stop_reason"] = stop_reason
                task["exit_code"] = observed_rc
            except (ValueError,OSError,KeyError,TypeError) as exc:
                return _render_unconfirmed_stop(task,verification,complete / total if total else 1.0,exc)
        if stop_reason == "CANCEL_REQUESTED":
            # The signed supervisor observed and acted on this cancellation.
            _render_history(task, "CANCELLED", note="requested stop; owned process exit observed")
            task["stop_confirmed_at"] = task.get("stop_confirmed_at") or _now_iso()
            _fx_release_render_slot(task)
            task["slot_released"] = True
            _persist_render_record(task)
        elif handle_known_rc:
            # observed exit code: non-zero/unknown-output is FAILED, never COMPLETED
            rc = getattr(handle, "returncode", None)
            if rc is None:
                rc = observed_rc
            task["exit_code"] = rc
            outcome = "COMPLETED" if stop_reason is None and rc == 0 and done else "FAILED"
            if outcome == "COMPLETED":
                if (task.get("backend") == "owned_subprocess"
                        and (task.get("process") or {}).get("worker_script")):
                    try:
                        task["worker_receipt"] = _verify_owned_worker_receipt(task)
                    except ValueError as exc:
                        _render_history(task, "NEEDS_RECONCILE", note="worker completion evidence is invalid")
                        task["state"] = "NEEDS_RECONCILE"
                        task["worker_evidence_error"] = str(exc)[:200]
                        task["stop_confirmed_at"] = _now_iso()
                        _fx_release_render_slot(task)
                        task["slot_released"] = True
                        _persist_render_record(task)
                        return {**task, "executing": False, "progress": complete / total if total else 1.0,
                                "verification": verification, "process_exited": process_exited,
                                "stop_confirmed": True}
                _record_owned_execution_fact(task, verification, task.get("worker_receipt") or {}, int(rc))
                _render_history(task, "COMPLETED", note="owned process rc observed through render_status")
                task["ledger_state"] = "PENDING"
                _persist_render_record(task)
                try:
                    task["artifact"] = _register_render_artifact(task)
                    task["ledger_state"] = "REGISTERED"
                    task["execution_fact"]["ledger_state"] = "REGISTERED"
                    task["execution_fact"]["registered_at"] = _now_iso()
                except Exception as exc:
                    _mark_verified_stop_pending_ledger(
                        task,
                        note="completed process stopped; artifact ledger registration is pending",
                        error=exc,
                    )
                    _persist_render_record(task)
                    return {**task, "executing": False, "progress": complete / total if total else 1.0,
                            "verification": verification, "process_exited": process_exited,
                            "stop_confirmed": True}
            else:
                _render_history(task, outcome, note="owned process rc observed through render_status")
            task["stop_confirmed_at"] = task.get("stop_confirmed_at") or _now_iso()
            _fx_release_render_slot(task)
            task["slot_released"] = True
            _persist_render_record(task)
        else:
            # pid dead but the exit code is UNKNOWN (handle lost, restart):
            # the record is marked NEEDS_RECONCILE and the slot STAYS HELD
            # for the control plane; unknown is never treated as stopped
            if task.get("state") == "RUNNING":
                _render_history(task, "NEEDS_RECONCILE", note="process exit observed without rc after restart")
                task["state"] = "NEEDS_RECONCILE"
                _persist_render_record(task)
    return {**task, "executing": not (done and process_exited),
            "progress": complete / total if total else 1.0, "verification": verification,
            "process_exited": process_exited,
            "stop_confirmed": bool(task.get("stop_confirmed_at"))}


def dispatch(command: str, params: dict[str, Any]) -> dict[str, Any]:
    import nuke

    if command.startswith("agent.nuke.composite."):
        return _dispatch_agent_with_scene_contract(
            command,
            params,
            lambda: _composite_action(command, params),
        )
    if command.startswith("agent.nuke."):
        return _dispatch_agent_with_scene_contract(
            command,
            params,
            lambda: _delivery_action(command, params),
        )
    if command == "nuke_ping":
        # An unsaved Nuke 17 root can expose a detached PythonObject for
        # ``root().name()``.  Keep ping independent of the current script so
        # a fresh GUI instance is still discoverable and healthy.
        return {
            "pid": os.getpid(),
            "port": _SERVER.port if _SERVER else None,
            "session_id": _SERVER.session_id if _SERVER else None,
            "nuke_version": nuke.NUKE_VERSION_STRING,
            "script": "",
            "gui": bool(nuke.GUI),
        }
    if command == "list_nodes":
        wanted = params.get("filter")
        nodes = nuke.allNodes(recurseGroups=bool(params.get("recurse", False)))
        if wanted:
            nodes = [node for node in nodes if node.Class() == wanted]
        return {"nodes": [{"name": node.name(), "class": node.Class(), "xpos": node.xpos(), "ypos": node.ypos()} for node in nodes]}
    if command == "get_node":
        node = _node(str(params.get("name")))
        return _node_observation(node, nuke)
    if command == "create_node":
        with nuke.Undo("Nuke Bridge create node"):
            node = nuke.createNode(str(params.get("node_class")), inpanel=False)
            for knob, value in dict(params.get("knobs") or {}).items():
                _set_knob(node, knob, value)
            for index, source in enumerate(params.get("inputs") or []):
                if source:
                    node.setInput(index, _node(str(source)))
            if "xpos" in params:
                node.setXpos(int(params["xpos"]))
            if "ypos" in params:
                node.setYpos(int(params["ypos"]))
        return {"name": node.name(), "class": node.Class()}
    if command == "connect_nodes":
        destination = _node(str(params.get("dst")))
        if "src" not in params:
            raise ValueError("connect_nodes requires src")
        source = None if params["src"] is None else _node(str(params["src"]))
        index = int(params.get("input_index", 0))
        with nuke.Undo("Nuke Bridge connect nodes"):
            destination.setInput(index, source)
        return {"src": source.name() if source is not None else None, "dst": destination.name(), "input_index": index}
    if command == "delete_node":
        node = _node(str(params.get("name")))
        with nuke.Undo("Nuke Bridge delete node"):
            nuke.delete(node)
        return {"deleted": str(params.get("name"))}
    if command == "set_knob":
        node = _node(str(params.get("node")))
        with nuke.Undo("Nuke Bridge set knob"):
            value = _set_knob(node, str(params.get("knob")), params.get("value"))
        return {"node": node.name(), "knob": params.get("knob"), "value": value}
    if command == "batch_set_knobs":
        edits = list(params.get("edits") or [])
        values = []
        with nuke.Undo("Nuke Bridge batch set knobs"):
            for edit in edits:
                node = _node(str(edit.get("node")))
                values.append({"node": node.name(), "knob": edit.get("knob"), "value": _set_knob(node, str(edit.get("knob")), edit.get("value"))})
        return {"edits": values}
    if command == "get_project_settings":
        try:
            root = nuke.root()
            return {"fps": root["fps"].value(), "format": root["format"].value().name(), "first": root["first_frame"].value(), "last": root["last_frame"].value()}
        except Exception as exc:
            # Nuke 17 can expose a detached Root PythonObject in a fresh,
            # unsaved script.  Keep this inspection command non-fatal while
            # preserving an explicit compatibility warning for callers.
            return {"fps": None, "format": None, "first": None, "last": None, "warning": str(exc)}
    if command == "script.info":
        try:
            return {
                "script": str(nuke.root().name() or ""),
                "modified": bool(nuke.modified()),
                **_nuke_scene_fingerprint(),
            }
        except Exception as exc:
            return {
                "script": "",
                "modified": None,
                "scene_fingerprint": "",
                "fingerprint_complete": False,
                "fingerprint_errors": [str(exc)],
                "warning": str(exc),
            }
    if command == "set_project_settings":
        root = nuke.root()
        allowed = {"fps", "first_frame", "last_frame", "format"}
        with nuke.Undo("Nuke Bridge project settings"):
            for key, value in params.items():
                if key in allowed:
                    _set_knob(root, key, value)
        return dispatch("get_project_settings", {})
    if command == "open_script":
        path = Path(str(params.get("path"))).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"script not found: {path}")
        expected = str(params.get("sha256") or "").strip().lower()
        if expected:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if not hmac.compare_digest(actual, expected):
                raise ValueError("target Nuke script hash does not match its frozen manifest")
        try:
            modified = nuke.modified()
        except Exception as exc:
            raise ValueError(
                "SCENE_STATE_DRIFT: Nuke modified state is unavailable"
            ) from exc
        if type(modified) is not bool:
            raise ValueError("SCENE_STATE_DRIFT: Nuke modified state is unavailable")
        if modified:
            raise ValueError("SCENE_STATE_DRIFT: refusing to open over unsaved changes")
        nuke.scriptOpen(str(path))
        # Node objects and names in these registries are scoped to the script
        # that was active before ``scriptOpen``.  Even when the opened NK uses
        # the same task id and topology names, retaining those dictionaries
        # would let stale paths and frame contracts override the state frozen
        # in the newly opened script.  Clear only after a successful open; the
        # next structured action must recover from hidden bridge_state_json.
        registry_invalidation = _invalidate_script_registries()
        return {
            "path": str(path),
            "sha256": expected,
            "registry_cache_invalidated": True,
            "registry_entries": registry_invalidation,
        }
    if command == "save_script":
        path = Path(str(params.get("path"))).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        nuke.scriptSaveAs(str(path), overwrite=bool(params.get("overwrite", False)))
        return {"path": str(path)}
    if command == "render_write":
        binding = params.get("output_binding")
        if binding is not None:
            if (not isinstance(binding, dict) or binding.get("source") != "controller"
                    or not isinstance(binding.get("node"), str) or not binding.get("node")
                    or not isinstance(binding.get("input_binding"), dict)):
                raise ValueError("OUTPUT_BINDING_INVALID: controller binding is required")
            if str(binding.get("pattern") or "") != str(params.get("pattern") or ""):
                raise ValueError("OUTPUT_BINDING_INVALID: pattern differs from controller binding")
            if list(binding.get("frames") or []) != list(params.get("frame_set") or []):
                raise ValueError("OUTPUT_BINDING_INVALID: frame set differs from controller binding")
            node_name = str(binding["node"])
        else:
            node_name = str(params.get("node"))
        write = _node(node_name)
        if write.Class() != "Write":
            raise ValueError("render_write requires a Write node")
        _validate_render_binding_owner(binding, write)
        frame_set = params.get("frame_set")
        if frame_set is not None:
            if (not isinstance(frame_set, list) or not frame_set or len(frame_set) > 12
                    or any(type(value) is not int or value < 1 for value in frame_set)
                    or len(set(frame_set)) != len(frame_set)):
                raise ValueError("INVALID_ARGUMENT: frame_set must contain unique positive integers (max 12)")
            frame_range = [min(frame_set), max(frame_set)]
        else:
            frame_range = params.get("frame_range") or [int(nuke.root()["first_frame"].value()), int(nuke.root()["last_frame"].value())]
        if (not isinstance(frame_range, list) or len(frame_range) != 2
                or any(type(value) is not int for value in frame_range)):
            raise ValueError("INVALID_ARGUMENT: frame_range must contain exactly two integer endpoints")
        first, last = frame_range
        if first > last:
            raise ValueError("INVALID_ARGUMENT: frame_range is reversed")
        return _nuke_render_operation("render_write", "render_write", write, first, last, 1,
                                      background=bool(params.get("background", True)),
                                      request_id=params.get("request_id"),
                                      nuke_executable=params.get("nuke_executable"),
                                      background_backend=str(params.get("background_backend") or "owned"),
                                      colorspace=str(params.get("colorspace") or ""),
                                      premultiplied=(params.get("premultiplied")
                                                     if type(params.get("premultiplied")) is bool else None),
                                      frame_set=list(frame_set) if frame_set is not None else None,
                                      pattern_override=(str(params.get("pattern"))
                                                        if binding is not None else None),
                                      input_binding=(dict(binding.get("input_binding"))
                                                     if binding is not None else None),
                                      project_color=(binding.get("project_color") if binding is not None else None),
                                      output_verification=(binding.get("output_verification") if binding is not None else None),
                                      budget_seconds=params.get("budget_seconds",120))
    if command == "render_fact":
        operation_id = str(params.get("operation_id") or "")
        return _nuke_operation_fact(operation_id) or {}
    if command == "render_status":
        return nuke_render_status(str(params.get("task_id")))
    if command == "control.render_recover":
        return nuke_render_recover(params.get("task_key"))
    if command == "control.render_resolve":
        return nuke_render_resolve(str(params.get("action") or ""), str(params.get("task_id") or ""),
                                   params.get("authorization"), str(params.get("note") or ""))
    if command == "render_cancel":
        task_id = str(params.get("task_id"))
        task = _RENDERS.get(task_id) or _load_render_record(task_id)
        if task is None:
            raise ValueError("render task not found")
        if task.get("state") in {"COMPLETED", "FAILED", "CANCELLED"}:
            # a recorded terminal state is never rewritten by a later cancel
            return {"task_id": task_id, "state": task.get("state"),
                    "cancel_requested": task.get("cancel_requested", False),
                    "cancel_requested_at": task.get("cancel_requested_at"),
                    "stop_confirmed_at": task.get("stop_confirmed_at"),
                    "note": "already terminal"}
        try:
            handle = _RENDER_HANDLES.get(task_id) or _restore_supervised_handle(task)
        except (ValueError,OSError,KeyError,TypeError):
            return dispatch("render_status", {"task_id":task_id})
        if task.get("state") == "NEEDS_RECONCILE" and handle is None:
            # A restart or lost handle leaves the stop outcome unknown.  A
            # cancel request is recorded for reconciliation but cannot free
            # the shared slot or turn unknown into cancelled.
            task["cancel_requested"] = True
            task["cancel_requested_at"] = task.get("cancel_requested_at") or _now_iso()
            task["stop_request_sent"] = False
            _persist_render_record(task)
            return {"task_id": task_id, "state": "NEEDS_RECONCILE",
                    "cancel_requested": True,
                    "cancel_requested_at": task["cancel_requested_at"],
                    "stop_request_sent": False, "process_exited": None,
                    "stop_confirmed_at": task.get("stop_confirmed_at")}
        try:
            if handle is not None and handle.poll() is not None:
                return dispatch("render_status", {"task_id":task_id})
        except (ValueError,OSError,KeyError,TypeError):
            return dispatch("render_status", {"task_id":task_id})
        prior_cancel_requested = bool(task.get("cancel_requested"))
        if not prior_cancel_requested:
            task["cancel_requested"] = True
            task["cancel_requested_at"] = _now_iso()
            _render_history(task, "CANCEL_PENDING", note="cancel requested")
        stop_request_sent = bool(task.get("stop_request_sent"))
        if handle is not None and hasattr(handle, "terminate"):
            # actual stop request against THIS task's owned process only
            try:
                if handle.poll() is None:
                    handle.terminate()
                    stop_request_sent = True
                else:
                    if not prior_cancel_requested:
                        task["cancel_requested"] = False
                        task["cancel_requested_at"] = None
                        _render_history(task, "RUNNING", note="process exited before stop request")
                    return dispatch("render_status", {"task_id":task_id})
            except Exception as exc:
                task["stop_request_error"] = str(exc)[:200]
        task["stop_request_sent"] = stop_request_sent
        try:
            process_exited = handle.poll() is not None if handle is not None else None
        except (ValueError,OSError,KeyError,TypeError):
            _persist_render_record(task)
            return dispatch("render_status", {"task_id":task_id})
        if process_exited:
            _persist_render_record(task)
            return dispatch("render_status", {"task_id":task_id})
        # no handle or still running: CANCEL_PENDING and the slot stay held
        _persist_render_record(task)
        return {"task_id": task_id, "state": task.get("state"),
                "cancel_requested": task["cancel_requested"],
                "cancel_requested_at": task["cancel_requested_at"],
                "stop_request_sent": stop_request_sent,
                "process_exited": process_exited,
                "stop_confirmed_at": task.get("stop_confirmed_at")}
    if command == "verify_render":
        return _verify(
            str(params.get("path_pattern")),
            int(params.get("first")),
            int(params.get("last")),
            int(params.get("min_size_kb", 1)),
            int(params.get("step", 1)),
        )
    if command == "nuke_run":
        return _safe_nuke_run(str(params.get("code") or ""))
    if command == "capabilities.get":
        loaded_addon_path = Path(__file__).resolve()
        loaded_addon_sha256 = _artifact(loaded_addon_path)["sha256"]
        return {
            "nuke_version": nuke.NUKE_VERSION_STRING,
            "gui": bool(nuke.GUI),
            "loaded_addon_path": str(loaded_addon_path),
            "loaded_addon_sha256": loaded_addon_sha256,
            "background_render": hasattr(nuke, "executeBackgroundNuke"),
            "structured_composite": True,
            "structured_composite_domain": "nuke_composite_v1",
            "reference_lineage_audit": True,
            "persistent_graph_metadata": True,
            "expected_frame_stride": True,
            "composite_semantic_controls": [
                "blur_size", "defocus_size", "denoise_mix", "sharpen_amount",
                "glow_size", "glow_amount", "emission_contrast", "comp_contrast",
                "premult", "edge_size", "grain_mix", "color_fusion_mix",
            ],
            "v2_uses_nuke_run": False,
        }
    raise ValueError(f"unsupported command: {command}")


def _read_request_line(stream, *, max_bytes: int = _MAX_REQUEST_BYTES) -> bytes:
    """Read one bounded newline-delimited request from a socket stream."""

    limit = int(max_bytes)
    if limit <= 0:
        raise ValueError("request byte limit must be positive")
    line = stream.readline(limit + 1)
    if len(line) > limit:
        raise _RequestLineError(
            "REQUEST_TOO_LARGE",
            "Nuke Bridge request exceeds the {} byte limit".format(limit),
        )
    if not line or not line.endswith(b"\n"):
        raise _RequestLineError(
            "INVALID_REQUEST",
            "Nuke Bridge request must be one newline-terminated JSON line",
        )
    return line


def _response_line(response) -> bytes:
    try:
        return (json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        # Dispatch may already have changed the scene. An encoding failure
        # must remain an explicit error, never permission to replay the command.
        failure = _error("COMMAND_FAILED", "response JSON encoding failed (" + type(exc).__name__ + ")",
                         indeterminate=True)
        return (json.dumps(failure, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


class NukeBridgeServer:
    def __init__(
        self,
        *,
        token: str | None = None,
        allow_legacy_unauthenticated: bool = False,
    ) -> None:
        if allow_legacy_unauthenticated:
            if token not in (None, ""):
                raise ValueError(
                    "legacy unauthenticated mode cannot be combined with a token"
                )
            normalized_token = ""
        else:
            normalized_token = (
                secrets.token_urlsafe(32) if token is None else _validate_token(token)
            )
        self.port: int | None = None
        self._server = None
        self._thread = None
        self._manifest: Path | None = None
        self._token_file: Path | None = None
        self._token = normalized_token or None
        self._legacy_unauthenticated = bool(allow_legacy_unauthenticated)
        self.session_id = uuid4().hex

    def _authorize_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if self._token is None:
            return None
        supplied = request.get("token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self._token):
            return _error("AUTH_REQUIRED", "a valid Nuke Bridge token is required")
        if _TASK_HOST_IDENTITY is not None:
            params = request.get("params") or {}
            command = request.get("command")
            operation_command = command in {"render_status", "render_cancel", "render_fact", "control.render_resolve"}
            task = params.get("task_id")
            if command == 'render_write' and params.get('output_binding') is not None:
                binding = params['output_binding']
                if (not isinstance(binding,dict) or binding.get('task_id') != _TASK_HOST_IDENTITY['task_id']
                        or not isinstance(binding.get('input_binding'),dict)
                        or binding['input_binding'].get('owner_task_id') != _TASK_HOST_IDENTITY['task_id']):
                    return _error('TASK_IDENTITY_MISMATCH', 'render binding belongs to another task')
            if operation_command:
                # These APIs use task_id for the persisted render operation,
                # while agent APIs use it for the pipeline owner. Resolve the
                # former from controller storage instead of treating caller
                # fields as proof of ownership.
                operation_id = params.get("operation_id") if command == "render_fact" else task
                if (not isinstance(operation_id, str)
                        or re.fullmatch(r"nrend-[0-9a-f]{16}", operation_id) is None):
                    return _error("TASK_IDENTITY_MISMATCH", "render operation is not owned by this task")
                record = _load_render_record(operation_id)
                if (not isinstance(record, dict) or record.get("task_id") != operation_id
                        or record.get("owner_task_id") != _TASK_HOST_IDENTITY["task_id"]):
                    return _error("TASK_IDENTITY_MISMATCH", "render operation is not owned by this task")
            if ((not operation_command or command == "render_fact")
                    and task is not None and str(task) != _TASK_HOST_IDENTITY["task_id"]):
                return _error("TASK_IDENTITY_MISMATCH", "request belongs to another task")
            if request.get("command") in {"open_script", "save_script"}:
                path = Path(str((request.get("params") or {}).get("path") or "")).expanduser().resolve()
                if _TASK_HOST_ROOT is None or not path.is_relative_to(_TASK_HOST_ROOT):
                    return _error("TASK_PATH_MISMATCH", "script path is outside this task root")
        return None

    def start(self) -> int:
        if self.port is not None:
            return self.port
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    line = _read_request_line(self.rfile)
                    request = json.loads(line.decode("utf-8"))
                    if not isinstance(request, dict):
                        raise _RequestLineError(
                            "INVALID_REQUEST",
                            "Nuke Bridge request must be a JSON object",
                        )
                    authorization_error = owner._authorize_request(request)
                    if authorization_error is not None:
                        response = authorization_error
                    else:
                        def invoke():
                            result = dispatch(str(request["command"]), dict(request.get("params") or {}))
                            if request["command"] == "nuke_ping" and _TASK_HOST_IDENTITY is not None:
                                result["task_host_identity"] = dict(_TASK_HOST_IDENTITY)
                            return _success(result)
                        response = _run_main(invoke)
                except _MainThreadTimeoutError as exc:
                    response = _error(
                        "TIMEOUT",
                        str(exc),
                        indeterminate=exc.indeterminate,
                    )
                except _RequestLineError as exc:
                    response = _error(exc.code, str(exc))
                except Exception as exc:
                    response = _error("COMMAND_FAILED", str(exc))
                self.wfile.write(_response_line(response))

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = os.name != 'nt'
            daemon_threads = True

            def server_bind(self):
                if os.name == 'nt':
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()

        last_bind_error = None
        for port in range(59555, 59655):
            try:
                self._server = Server(("127.0.0.1", port), Handler)
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE and not (
                        os.name == 'nt' and getattr(exc, 'winerror', None) in (10013,10048)):
                    raise RuntimeError(
                        f"NUKE_BRIDGE_BIND_FAILED address=127.0.0.1:{port} errno={exc.errno}: {exc}"
                    ) from exc
                last_bind_error = exc
                continue
            self.port = port
            self._thread = threading.Thread(target=self._server.serve_forever, name="nuke-bridge-tcp", daemon=True)
            self._thread.start()
            try:
                self._write_manifest()
            except Exception:
                self.stop()
                raise
            return port
        raise RuntimeError(
            f"no free Nuke Bridge port in 59555..59654; errno={last_bind_error.errno}: {last_bind_error}"
        ) from last_bind_error

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._manifest is not None:
            self._manifest.unlink(missing_ok=True)
        if self._token_file is not None:
            self._token_file.unlink(missing_ok=True)
        self.port = None
        self._server = None
        self._thread = None
        self._manifest = None
        self._token_file = None

    def _write_manifest(self) -> None:
        import nuke

        directory = _manifest_dir()
        _ensure_secure_manifest_dir(directory)
        self._manifest = directory / f"{os.getpid()}.json"
        if self._token is not None:
            self._token_file = directory / "{}.{}.token".format(os.getpid(), self.session_id)
            _write_private_file_exclusive(self._token_file, self._token.encode("ascii"))
        payload = {
            "pid": os.getpid(),
            "port": self.port,
            "session_id": self.session_id,
            "nuke_version": nuke.NUKE_VERSION_STRING,
            "gui": bool(nuke.GUI),
            "token_file": self._token_file.name if self._token_file is not None else None,
        }
        temporary = directory / ".{}.{}.tmp".format(self._manifest.name, self.session_id)
        temporary_created = False
        try:
            _write_private_file_exclusive(
                temporary,
                (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            temporary_created = True
            os.replace(str(temporary), str(self._manifest))
            temporary_created = False
            manifest_info = self._manifest.lstat()
            if self._manifest.is_symlink() or not stat.S_ISREG(manifest_info.st_mode):
                raise RuntimeError("Nuke Bridge manifest is not a regular file")
            if os.name != "nt" and (
                manifest_info.st_uid != os.getuid() or stat.S_IMODE(manifest_info.st_mode) != 0o600
            ):
                raise RuntimeError("Nuke Bridge manifest must be owner-only")
        except Exception:
            if temporary_created:
                temporary.unlink(missing_ok=True)
            if self._token_file is not None:
                self._token_file.unlink(missing_ok=True)
                self._token_file = None
            raise


def autostart() -> int:
    global _ATEXIT_REGISTERED, _SERVER
    if _SERVER is None:
        _SERVER = NukeBridgeServer(
            allow_legacy_unauthenticated=(
                os.environ.get(_LEGACY_UNAUTH_ENV, "").strip() == "1"
            )
        )
    if not _ATEXIT_REGISTERED:
        atexit.register(shutdown)
        _ATEXIT_REGISTERED = True
    return _SERVER.start()


def shutdown() -> None:
    global _SERVER
    if _SERVER is not None:
        _SERVER.stop()
        _SERVER = None
