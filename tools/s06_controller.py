#!/usr/bin/env python3
"""Controller-only S-06 authorization and narrow Houdini adapter entry point.

The controller is the only code path in this candidate that can issue an
S-06 authorization bundle. It performs read-only scene inspection before any
database reservation, records saved-hip preparation separately from the first
graph mutation, and then binds task, operation, intent, scene lease, heavy
slot, scene identity, schedule, and receipt to canonical hashes.

The module is deliberately cooperative rather than a security boundary. The
user's Full Access process can still bypass it. It exposes no raw Python
execution, arbitrary host command, cache, render, or simulation operation.
The execute method is an opt-in software/adapter path; this package never
starts a real DCC.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import time
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
for _package in ("dcc-task-runtime", "vfx-pipeline", "houdini-bridge", "nuke-bridge"):
    _path = ROOT / "packages" / _package / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from vfx_pipeline.s06_contracts import (
    ADAPTER_BUILD_COMMAND,
    ADAPTER_INSPECT_COMMAND,
    ADAPTER_SCHEMA,
    AUTHORIZATION_SCHEMA,
    CONTROLLER_ISSUANCE_SCHEMA,
    CONTROLLER_REQUEST_SCHEMA,
    HOST_BINDING_SCHEMA,
    OPERATION_CATEGORY,
    OPERATION_SCHEMA,
    PREPARATION_CATEGORY,
    PREPARATION_SCHEMA,
    RECEIPT_PREFIX,
    RECEIPT_SCHEMA,
    SCOPE,
    canonical_json,
    canonical_sha256,
    authorization_hash,
    controller_request_core,
    controller_request_hash,
    intent_payload,
    is_root,
    is_sha256,
    schedule_from_pulses,
    scene_ownership_hash,
    scene_ownership_record_valid,
    SCENE_OWNERSHIP_SCHEMA,
)
from vfx_pipeline.s06_velocity import default_controller_sentinel
from dcc_task_runtime.pipeline_store import PipelineStore
from vfx_pipeline.graph_scheduler import GraphScheduler
from vfx_pipeline.scene_lease import SceneLeaseStore


CAPTURE_FILE_SHA256 = "3f49969013ea11850a75688a00a5850c89ffa86acf9ad08331690595ce3a88db"
SNAPSHOT_SHA256 = "d1a194238b173645e278524cfc3413ee013426263fcc6e63650ff05977670234"
EXPECTED_BUILD = "21.0.631"
SCENE_OWNERSHIP_EVIDENCE_SCHEMA = "bridge.f2.s06-scene-ownership-evidence/1.0"
S06_HOST_CAPABILITY_SCHEMA = "bridge.f2.s06-host-capabilities/1.0"
S06_NATIVE_PROVIDER_STATUS_READY = "READY"
S06_NATIVE_ADAPTER_SCHEMA = "bridge.f2.s06-native-host-adapter/1.0"
S06_NATIVE_ADAPTER_ATTRIBUTE = "bridge_s06_native_adapter_v1"
S06_NATIVE_INTERFACE_NAMES = (
    "field_snapshot",
    "apply_velocity_sentinel",
    "velocity_writer_inventory",
    "observe_sourcing_boundary",
)
S06_COMPLETED_HOST_STATES = frozenset({"EXECUTED_HOST_SHORT_SEGMENT", "HOST_OUTPUT_INCONCLUSIVE"})
_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _strict_json_value(value: Any) -> Any:
    """Reject executable-looking or unbounded host-control payloads."""

    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            name = str(key)
            if name.lower() in {"code", "python", "exec", "eval", "command", "shell"}:
                raise ValueError("controller params may not contain executable fields")
            result[name] = _strict_json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError("controller payload list is too large")
        return [_strict_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ValueError("controller payload is not JSON-compatible")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError("authorization output must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".s06-auth-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("authorization bundle is unavailable")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("authorization bundle is not an object")
    return value


def _controller_file_evidence(path_text: Any) -> dict[str, Any] | None:
    """Re-read HIP metadata/hash in the controller process, read-only."""

    if not isinstance(path_text, str) or not Path(path_text).is_absolute():
        return None
    path = Path(path_text)
    result: dict[str, Any] = {
        "schema": "bridge.f2.s06-file-evidence/1.0",
        "path": str(path),
        "is_regular_file": False,
        "is_symlink": False,
        "parent_symlink": False,
        "uid": None,
        "gid": None,
        "mode": None,
        "device": None,
        "inode": None,
        "size": None,
        "mtime_ns": None,
        "sha256": None,
    }
    try:
        info = path.lstat()
        result.update({
            "is_regular_file": bool(stat.S_ISREG(info.st_mode)),
            "is_symlink": bool(stat.S_ISLNK(info.st_mode)),
            "uid": int(info.st_uid),
            "gid": int(info.st_gid),
            "mode": int(stat.S_IMODE(info.st_mode)),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
            "size": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
        })
        for parent in path.parents:
            try:
                if stat.S_ISLNK(parent.lstat().st_mode):
                    result["parent_symlink"] = True
                    break
            except OSError:
                result["parent_symlink"] = True
                break
        if result["is_regular_file"] and not result["is_symlink"] and not result["parent_symlink"]:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result["sha256"] = digest.hexdigest()
    except OSError:
        return None
    return result


def _host_probe_failures(probe: Any, ownership_record: Mapping[str, Any] | None = None) -> list[str]:
    if not isinstance(probe, Mapping):
        return ["SCENE_PROBE_NOT_OBJECT"]
    failures: list[str] = []
    if probe.get("houdini_version") != EXPECTED_BUILD:
        failures.append("HOST_BUILD_NOT_21_0_631")
    route = probe.get("route")
    if not isinstance(route, Mapping):
        failures.append("GUI_ROUTE_NOT_OBJECT")
    else:
        if route.get("reachable") is not True:
            failures.append("GUI_ROUTE_UNREACHABLE")
        if route.get("main_thread") is not True:
            failures.append("GUI_MAIN_THREAD_ADAPTER_UNAVAILABLE")
        if route.get("adapter") != ADAPTER_BUILD_COMMAND:
            failures.append("GUI_S06_ADAPTER_MISSING")
        if route.get("raw_code_allowed") is True:
            failures.append("GUI_ADAPTER_CODE_EXECUTION_ENABLED")
    identity = probe.get("scene_identity")
    if not isinstance(identity, Mapping):
        failures.append("SCENE_IDENTITY_NOT_OBJECT")
    else:
        for key in ("session_id", "process_generation", "scene_id", "hip_path"):
            if not isinstance(identity.get(key), str) or not identity[key].strip():
                failures.append("SCENE_IDENTITY_INCOMPLETE:" + key)
        if isinstance(identity.get("hip_path"), str) and not Path(identity["hip_path"]).is_absolute():
            failures.append("SCENE_HIP_PATH_NOT_ABSOLUTE")
    if probe.get("saved") is not True:
        failures.append("SCENE_HIP_NOT_SAVED")
    completed_ownership = isinstance(ownership_record, Mapping) and ownership_record.get("phase") == "GRAPH_MUTATION_COMPLETED"
    if not completed_ownership and probe.get("has_unsaved_changes") is not False:
        failures.append("SCENE_HIP_DIRTY_OR_UNKNOWN")
    if probe.get("read_only_capture_session") is True:
        failures.append("READ_ONLY_CAPTURE_SESSION_CANNOT_BE_REUSED")
    for key in ("conflicting_nodes", "task_manifest_ids"):
        values = probe.get(key)
        if not isinstance(values, list):
            failures.append("SCENE_CONFLICT_LIST_INVALID:" + key)
        elif values and not (completed_ownership and key == "task_manifest_ids"):
            failures.append("SCENE_CONFLICT_PRESENT:" + key)
    if not is_sha256(probe.get("hip_sha256")):
        failures.append("SCENE_HIP_HASH_UNAVAILABLE")
    capabilities = probe.get("host_capabilities")
    if not isinstance(capabilities, Mapping) or capabilities.get("schema") != S06_HOST_CAPABILITY_SCHEMA:
        failures.append("S06_HOST_CAPABILITY_RECORD_INVALID")
    elif capabilities.get("status") != S06_NATIVE_PROVIDER_STATUS_READY:
        failures.append("S06_HOST_CAPABILITY_UNAVAILABLE")
    elif (
        capabilities.get("provider_attribute") != S06_NATIVE_ADAPTER_ATTRIBUTE
        or capabilities.get("provider_schema") != S06_NATIVE_ADAPTER_SCHEMA
        or capabilities.get("required_interfaces") != list(S06_NATIVE_INTERFACE_NAMES)
        or capabilities.get("available_interfaces") != list(S06_NATIVE_INTERFACE_NAMES)
        or capabilities.get("missing_interfaces") != []
        or capabilities.get("pre_mutation_action") != "ALLOW_S06_ADAPTER"
    ):
        failures.append("S06_HOST_CAPABILITY_EVIDENCE_INCOMPLETE")

    identity = probe.get("scene_identity")
    local_file = _controller_file_evidence(identity.get("hip_path") if isinstance(identity, Mapping) else None)
    supplied_file = probe.get("file_evidence")
    if local_file is None or not isinstance(supplied_file, Mapping) or dict(supplied_file) != local_file:
        failures.append("SCENE_HIP_READ_ONLY_FILE_EVIDENCE_MISMATCH")
    elif local_file.get("sha256") != probe.get("hip_sha256"):
        failures.append("SCENE_HIP_HASH_READBACK_MISMATCH")

    evidence = probe.get("ownership_evidence")
    if ownership_record is None:
        if not isinstance(evidence, Mapping) or evidence.get("schema") != SCENE_OWNERSHIP_EVIDENCE_SCHEMA:
            failures.append("SCENE_OWNERSHIP_EVIDENCE_INVALID")
        else:
            if evidence.get("record_status") != "ABSENT":
                failures.append("SCENE_OWNERSHIP_RECORD_STATUS_INVALID")
            if probe.get("owned_project") is not False or probe.get("fresh_project") is not False:
                failures.append("SCENE_OWNERSHIP_ASSERTED_WITHOUT_CONTROLLER_RECORD")
        if probe.get("children") != []:
            failures.append("SCENE_FRESH_PROJECT_HAS_EXISTING_CHILDREN")
    else:
        if not isinstance(evidence, Mapping) or evidence.get("record_status") != "MATCHED":
            failures.append("SCENE_OWNERSHIP_READBACK_NOT_MATCHED")
        elif evidence.get("record_hash") != ownership_record.get("record_hash") or evidence.get("identity_match") is not True or evidence.get("hip_file_match") is not True or evidence.get("graph_match") is not True:
            failures.append("SCENE_OWNERSHIP_READBACK_EVIDENCE_INCOMPLETE")
        try:
            record_valid = scene_ownership_record_valid(ownership_record)
        except (TypeError, ValueError, OverflowError):
            record_valid = False
        if not record_valid:
            failures.append("SCENE_OWNERSHIP_RECORD_INVALID")
        else:
            for key in ("task_id", "operation_id", "controller_id"):
                if not isinstance(ownership_record.get(key), str) or not ownership_record[key].strip():
                    failures.append("SCENE_OWNERSHIP_RECORD_INCOMPLETE:" + key)
            if isinstance(identity, Mapping) and ownership_record.get("scene_identity") != {
                key: identity.get(key) for key in ("session_id", "process_generation", "scene_id", "hip_path")
            }:
                failures.append("SCENE_OWNERSHIP_IDENTITY_MISMATCH")
            if ownership_record.get("hip_file_evidence") != supplied_file:
                failures.append("SCENE_OWNERSHIP_FILE_EVIDENCE_MISMATCH")
            phase = ownership_record.get("phase")
            if phase == "PREPARED":
                if probe.get("owned_project") is not True or probe.get("fresh_project") is not True:
                    failures.append("SCENE_OWNERSHIP_PREPARED_READBACK_NOT_FRESH")
                if probe.get("has_unsaved_changes") is not False or probe.get("conflicting_nodes") != []:
                    failures.append("SCENE_OWNERSHIP_PREPARED_SCENE_CHANGED")
            elif phase == "GRAPH_MUTATION_COMPLETED":
                if probe.get("owned_project") is not True:
                    failures.append("SCENE_OWNERSHIP_COMPLETED_READBACK_NOT_OWNED")
                # A completed task may leave the HIP dirty.  The controller
                # only permits the exact task-owned graph and unchanged disk
                # evidence; it does not reapply a fresh/clean rule on replay.
                if probe.get("conflicting_nodes") != []:
                    failures.append("SCENE_OWNERSHIP_FOREIGN_GRAPH_PRESENT")
            elif phase == "GRAPH_MUTATION_STARTED":
                failures.append("SCENE_OWNERSHIP_MUTATION_IN_PROGRESS")
            else:
                failures.append("SCENE_OWNERSHIP_PHASE_INVALID")
    return list(dict.fromkeys(failures))


def _scene_manifest_paths(manifest: Any, graph_root: str) -> tuple[set[str] | None, list[str]]:
    """Validate the typed receipt manifest without asking the host to run it."""

    if not isinstance(manifest, Mapping):
        return None, ["SCENE_MANIFEST_MISSING"]
    if (
        manifest.get("task_id") is None
        or manifest.get("execution_root") != graph_root
        or manifest.get("domain_pack") != "pyro_smoke_v1"
    ):
        return None, ["SCENE_MANIFEST_BINDING_INVALID"]
    nodes = manifest.get("nodes")
    if not isinstance(nodes, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in nodes.items()):
        return None, ["SCENE_MANIFEST_NODES_INVALID"]
    if not isinstance(nodes.get("solver"), str) or not isinstance(nodes.get("source_volume"), str):
        return None, ["SCENE_MANIFEST_REQUIRED_NODES_MISSING"]
    paths = {graph_root}
    for value in nodes.values():
        if not (value == graph_root or value.startswith(graph_root + "/")):
            return None, ["SCENE_MANIFEST_NODE_OUTSIDE_AUTHORIZED_ROOT"]
        paths.add(value)
    return paths, []


def _preparation_from_probe(probe: Mapping[str, Any]) -> dict[str, Any]:
    identity = probe["scene_identity"]
    return {
        "schema": PREPARATION_SCHEMA,
        "status": "SAVED_HIP_VERIFIED",
        "saved_hip": {
            "path": identity["hip_path"],
            "sha256": probe["hip_sha256"],
            "has_unsaved_changes": False,
            "file_evidence": dict(probe["file_evidence"]),
        },
        "ownership": {
            "owned_project": True,
            "fresh_project": True,
            "read_only_capture_session": False,
            "conflicting_nodes": [],
            "task_manifest_ids": [],
        },
        "first_graph_mutation": "not_started",
        "save_preparation_and_graph_mutation_are_separate": True,
    }


class S06Controller:
    """Trusted cooperative issuer for one fresh technical S-06 operation."""

    def __init__(
        self,
        root_dir: Path | str,
        *,
        clock: Callable[[], float] = time.time,
        controller_id: str = "bridge-s06-controller",
        capture_file_sha256: str = CAPTURE_FILE_SHA256,
        snapshot_sha256: str = SNAPSHOT_SHA256,
    ) -> None:
        self.root_dir = Path(root_dir).expanduser().absolute()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        if not _safe_identifier(controller_id):
            raise ValueError("controller_id is not a safe identifier")
        if capture_file_sha256 != CAPTURE_FILE_SHA256 or snapshot_sha256 != SNAPSHOT_SHA256:
            raise ValueError("S-06 source evidence is pinned to the reviewed R3 capture")
        self.controller_id = controller_id
        self.source_binding = {
            "capture_file_sha256": CAPTURE_FILE_SHA256,
            "snapshot_sha256": SNAPSHOT_SHA256,
            "capture_state": "CAPTURED_NOT_BOUND",
        }
        self.store = PipelineStore(self.root_dir / "pipeline.sqlite3")
        self.lease_store = SceneLeaseStore(self.root_dir / "scene-lease.sqlite3", clock=clock)
        self.scheduler_root = self.root_dir / "scheduler"
        self.scheduler = GraphScheduler(self.scheduler_root)
        self.ownership_root = self.root_dir / "scene-ownership"

    def _ownership_path(self, operation_id: str) -> Path:
        if not _safe_identifier(operation_id):
            raise ValueError("operation id is not safe for a scene ownership record")
        return self.ownership_root / (operation_id + ".json")

    def _create_ownership_record(
        self,
        *,
        task_id: str,
        operation_id: str,
        request_id: str,
        identity: Mapping[str, Any],
        probe: Mapping[str, Any],
        graph_root: str,
    ) -> dict[str, Any]:
        file_evidence = probe.get("file_evidence")
        if not isinstance(file_evidence, Mapping):
            raise ValueError("read-only HIP file evidence is required")
        record: dict[str, Any] = {
            "schema": SCENE_OWNERSHIP_SCHEMA,
            "controller_id": self.controller_id,
            "task_id": task_id,
            "operation_id": operation_id,
            "request_id": request_id,
            "scene_identity": {key: identity.get(key) for key in ("session_id", "process_generation", "scene_id", "hip_path")},
            "hip_sha256": str(probe["hip_sha256"]),
            "hip_file_evidence": dict(file_evidence),
            "graph_root": graph_root,
            "phase": "PREPARED",
            "first_graph_mutation": "not_started",
            "task_owned_nodes": [],
            "task_manifest_ids": [],
            "record_path": str(self._ownership_path(operation_id)),
            "created_at": float(self.clock()),
            "updated_at": float(self.clock()),
        }
        record["record_hash"] = scene_ownership_hash(record)
        path = self._ownership_path(operation_id)
        if path.exists() or path.is_symlink():
            raise ValueError("scene ownership record already exists")
        self.ownership_root.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def _read_ownership_record(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        expected_operation = reference.get("operation_id")
        expected_path = self._ownership_path(str(expected_operation)).absolute()
        path = Path(str(reference.get("record_path") or "")).expanduser().absolute()
        if path != expected_path:
            raise ValueError("scene ownership record path is outside the controller store")
        if path.is_symlink() or not path.is_file():
            raise ValueError("scene ownership record is unavailable")
        record = _read_json(path)
        if not scene_ownership_record_valid(record):
            raise ValueError("scene ownership record hash is invalid")
        if record.get("operation_id") != expected_operation or record.get("controller_id") != self.controller_id:
            raise ValueError("scene ownership record identity is invalid")
        return record

    def _update_ownership_record(
        self,
        record: Mapping[str, Any],
        *,
        phase: str,
        first_graph_mutation: str,
        manifest: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self._read_ownership_record({"record_path": record.get("record_path"), "operation_id": record.get("operation_id")}) if record.get("record_path") else dict(record)
        updated = dict(current)
        updated["phase"] = phase
        updated["first_graph_mutation"] = first_graph_mutation
        updated["updated_at"] = float(self.clock())
        if phase == "GRAPH_MUTATION_COMPLETED":
            nodes = manifest.get("nodes") if isinstance(manifest, Mapping) else None
            if not isinstance(nodes, Mapping) or not all(isinstance(value, str) for value in nodes.values()):
                raise ValueError("completed S-06 result has no typed scene manifest")
            owned_nodes = sorted(set([str(updated["graph_root"]), *[str(value) for value in nodes.values()]]))
            updated["task_owned_nodes"] = owned_nodes
            updated["task_manifest_ids"] = [str(updated["operation_id"])]
            updated["manifest_sha256"] = canonical_sha256({str(key): str(value) for key, value in sorted(nodes.items(), key=lambda item: str(item[0]))})
        updated.pop("record_hash", None)
        updated["record_hash"] = scene_ownership_hash(updated)
        path = self._ownership_path(str(updated["operation_id"]))
        if path.is_symlink() or not path.is_file():
            raise ValueError("scene ownership record disappeared")
        stored = _read_json(path)
        if not scene_ownership_record_valid(stored) or stored.get("record_hash") != current.get("record_hash"):
            raise ValueError("scene ownership record changed concurrently")
        _atomic_json(path, updated)
        updated["record_path"] = str(path)
        return updated

    def _read_completed_receipt(
        self,
        bundle: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """Read one completed receipt and independently bind it to the intent.

        The return flag distinguishes a missing/RUNNING receipt from a present
        but invalid COMPLETED receipt.  RUNNING is never promoted to completed
        and is deliberately left to the normal no-rerun guard.
        """

        receipt_binding = bundle.get("execution_receipt")
        if not isinstance(receipt_binding, Mapping):
            return None, ["COMPLETED_RECEIPT_BINDING_INVALID"], True
        try:
            store_path = Path(str(receipt_binding.get("store_path") or "")).expanduser().absolute()
            if store_path != self.store.path.absolute() or store_path.is_symlink() or not store_path.is_file():
                return None, ["COMPLETED_RECEIPT_STORE_MISMATCH"], True
            safe_params = _strict_json_value(dict(params))
            safe_params["task_id"] = bundle.get("task_id")
            intent = intent_payload(bundle, safe_params)
            request_hash = canonical_sha256(intent)
            records = [
                row for row in self.store.records(str(bundle["task_id"]), OPERATION_CATEGORY)
                if isinstance(row, Mapping) and row.get("operation_id") == bundle.get("operation_id")
            ]
            if len(records) != 1:
                return None, ["COMPLETED_RECEIPT_OPERATION_RECORD_UNAVAILABLE"], True
            operation = records[0]
            if (
                operation.get("schema") != OPERATION_SCHEMA
                or operation.get("task_id") != bundle.get("task_id")
                or operation.get("operation_id") != bundle.get("operation_id")
                or operation.get("status") != "AUTHORIZED"
                or operation.get("unknown") is not False
                or operation.get("intent_hash") != request_hash
                or operation.get("intent") != intent
            ):
                return None, ["COMPLETED_RECEIPT_INTENT_OR_OPERATION_DRIFT"], True
            receipt = self.store.skill_execution_receipt(
                str(bundle["task_id"]), str(receipt_binding["idempotency_key"]),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError):
            return None, ["COMPLETED_RECEIPT_READ_FAILED"], True
        if not isinstance(receipt, Mapping) or receipt.get("status") != "COMPLETED":
            return None, [], False
        if receipt.get("request_hash") != request_hash:
            return None, ["COMPLETED_RECEIPT_INTENT_HASH_MISMATCH"], True
        result = receipt.get("result")
        if not isinstance(result, Mapping):
            return None, ["COMPLETED_RECEIPT_RESULT_INVALID"], True
        if (
            result.get("schema") != "bridge.f2.solver-sourcing-validation/1.2"
            or result.get("operation_id") != bundle.get("operation_id")
            or result.get("state") not in S06_COMPLETED_HOST_STATES
            or result.get("execution_started") is not True
            or result.get("simulation_cache_written") is not False
            or result.get("render_started") is not False
        ):
            return None, ["COMPLETED_RECEIPT_RESULT_NOT_A_STOPPED_S06_RESULT"], True
        manifest = result.get("scene_manifest")
        graph_root = str((bundle.get("host_binding") or {}).get("root") or "")
        expected_paths, manifest_failures = _scene_manifest_paths(manifest, graph_root)
        if manifest_failures:
            return None, manifest_failures, True
        if not isinstance(manifest, Mapping) or manifest.get("task_id") != bundle.get("task_id"):
            return None, ["COMPLETED_RECEIPT_MANIFEST_TASK_MISMATCH"], True
        return {
            "result": dict(result),
            "manifest": dict(manifest),
            "expected_graph_paths": sorted(expected_paths or ()),
            "request_hash": request_hash,
            "receipt": dict(receipt),
        }, [], True

    def _recovery_probe_failures(
        self,
        probe: Any,
        bundle: Mapping[str, Any],
        record: Mapping[str, Any],
        expected_graph_paths: list[str],
    ) -> list[str]:
        """Validate read-only graph evidence for a receipt-only recovery.

        The addon reports ``GRAPH_MUTATION_STARTED`` as mismatched by design.
        This method overlays a completed phase only after comparing the raw
        identity, HIP evidence, conflicts, and actual graph paths to the
        already-completed receipt manifest.  No host result is self-attested.
        """

        failures: list[str] = []
        if record.get("phase") not in {"PREPARED", "GRAPH_MUTATION_STARTED"}:
            failures.append("SCENE_OWNERSHIP_RECOVERY_PHASE_INVALID")
        expected_identity = {
            key: (bundle.get("host_binding") or {}).get(key)
            for key in ("session_id", "process_generation", "scene_id", "hip_path")
        }
        if record.get("scene_identity") != expected_identity:
            failures.append("SCENE_OWNERSHIP_RECOVERY_IDENTITY_DRIFT")
        if not isinstance(probe, Mapping):
            return ["SCENE_RECOVERY_INSPECT_NOT_OBJECT", *failures]
        if type(probe.get("has_unsaved_changes")) is not bool:
            failures.append("SCENE_RECOVERY_DIRTY_STATE_INVALID")
        if probe.get("conflicting_nodes") != []:
            failures.append("SCENE_OWNERSHIP_RECOVERY_FOREIGN_GRAPH_PRESENT")
        evidence = probe.get("ownership_evidence")
        if not isinstance(evidence, Mapping) or evidence.get("schema") != SCENE_OWNERSHIP_EVIDENCE_SCHEMA:
            failures.append("SCENE_OWNERSHIP_RECOVERY_EVIDENCE_INVALID")
        else:
            if evidence.get("identity_match") is not True:
                failures.append("SCENE_OWNERSHIP_RECOVERY_IDENTITY_READBACK_MISMATCH")
            if evidence.get("hip_file_match") is not True:
                failures.append("SCENE_OWNERSHIP_RECOVERY_FILE_READBACK_MISMATCH")
            actual = evidence.get("actual_graph_paths")
            if not isinstance(actual, list) or not all(isinstance(path, str) for path in actual):
                failures.append("SCENE_OWNERSHIP_RECOVERY_GRAPH_READBACK_INVALID")
            elif set(actual) != set(expected_graph_paths):
                failures.append("SCENE_OWNERSHIP_RECOVERY_GRAPH_DRIFT")
        # Reuse the normal host/file/capability checks with a locally derived
        # completed view.  The derived hash is not accepted from the host.
        completed_record = dict(record)
        completed_record["phase"] = "GRAPH_MUTATION_COMPLETED"
        completed_record["first_graph_mutation"] = "completed"
        completed_record["task_owned_nodes"] = list(expected_graph_paths)
        completed_record["task_manifest_ids"] = [str(record.get("operation_id"))]
        completed_record.pop("record_hash", None)
        completed_record["record_hash"] = scene_ownership_hash(completed_record)
        completed_probe = dict(probe)
        completed_probe["owned_project"] = True
        completed_probe["fresh_project"] = False
        # A completed task may be dirty; this value is used only to avoid the
        # initial-preparation clean check.  The real dirty type was checked
        # above, and file/graph evidence remains bound to the record.
        completed_probe["has_unsaved_changes"] = False
        completed_evidence = dict(evidence) if isinstance(evidence, Mapping) else {}
        completed_evidence.update({
            "record_status": "MATCHED",
            "record_hash": completed_record["record_hash"],
            "graph_match": True,
        })
        completed_probe["ownership_evidence"] = completed_evidence
        failures.extend(_host_probe_failures(completed_probe, completed_record))
        return list(dict.fromkeys(failures))

    def _recover_completed_receipt(
        self,
        bundle: Mapping[str, Any],
        ownership_record: Mapping[str, Any],
        adapter: "S06MainThreadAdapter",
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Finish a completed host operation without another adapter mutation."""

        receipt_payload, receipt_failures, completed = self._read_completed_receipt(bundle, params)
        if not completed:
            return None
        if receipt_failures or receipt_payload is None:
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_RECOVERY_REJECTED",
                "operation_id": bundle.get("operation_id"),
                "host_calls": 0,
                "execution_started": True,
                "failures": receipt_failures,
                "blockers": ["RECONCILIATION_REQUIRED", "COMPLETED_RECEIPT_INVALID"],
            }
        try:
            probe = adapter.inspect_scene(ownership_record=ownership_record)
        except Exception as exc:
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_RECOVERY_INSPECT_UNCERTAIN",
                "operation_id": bundle.get("operation_id"),
                "host_calls": 0,
                "execution_started": True,
                "failures": ["READ_ONLY_INSPECT_FAILED:" + type(exc).__name__],
                "blockers": ["RECONCILIATION_REQUIRED", "HOST_OPERATION_MUST_NOT_BE_RERUN"],
            }
        probe_failures = self._recovery_probe_failures(
            probe, bundle, ownership_record, receipt_payload["expected_graph_paths"],
        )
        if probe_failures:
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_RECOVERY_REJECTED",
                "operation_id": bundle.get("operation_id"),
                "host_calls": 0,
                "execution_started": True,
                "failures": probe_failures,
                "blockers": ["RECONCILIATION_REQUIRED", "SCENE_OWNERSHIP_RECORD_DRIFT", "HOST_OPERATION_MUST_NOT_BE_RERUN"],
            }
        validator = _load_validator()
        finalized, finalization_blocker = validator._finalize_completed_operation(
            self.store, bundle, receipt_payload["request_hash"],
        )
        if not finalized:
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_RECOVERY_FINALIZATION_UNCERTAIN",
                "operation_id": bundle.get("operation_id"),
                "host_calls": 0,
                "execution_started": True,
                "failures": [finalization_blocker],
                "blockers": ["RECONCILIATION_REQUIRED", "HOST_OPERATION_MUST_NOT_BE_RERUN"],
            }
        try:
            latest = self._read_ownership_record(bundle["scene_ownership"])
            self._update_ownership_record(
                latest,
                phase="GRAPH_MUTATION_COMPLETED",
                first_graph_mutation="completed",
                manifest=receipt_payload["manifest"],
            )
        except (OSError, ValueError, TypeError, KeyError):
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_COMPLETION_RECORD_UNCERTAIN",
                "operation_id": bundle.get("operation_id"),
                "host_calls": 0,
                "execution_started": True,
                "blockers": ["RECONCILIATION_REQUIRED", "SCENE_OWNERSHIP_RECORD_UNCERTAIN", "HOST_OPERATION_MUST_NOT_BE_RERUN"],
            }
        replay = dict(receipt_payload["result"])
        replay["operation_id"] = bundle.get("operation_id")
        replay["replayed"] = True
        replay["recovered"] = True
        replay["recovery"] = "COMPLETED_RECEIPT_AND_GRAPH_RECONCILED"
        replay["host_mutation_calls"] = 0
        return replay

    def inspect(self, scene_probe: Mapping[str, Any] | Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
        """Validate a read-only GUI probe without creating durable state."""

        probe = scene_probe() if callable(scene_probe) else scene_probe
        failures = _host_probe_failures(probe)
        if failures:
            return {
                "state": "BLOCKED",
                "reason": "SCENE_PREPARATION_NOT_READY",
                "failures": failures,
                "host_calls": 0,
                "first_graph_mutation": "not_started",
            }
        return {
            "state": "SCENE_PREPARED",
            "reason": "SAVED_HIP_AND_NATIVE_CAPABILITY_VERIFIED_UNREGISTERED",
            "host_calls": 0,
            "scene_identity": dict(probe["scene_identity"]),
            "preparation": _preparation_from_probe(probe),
            "file_evidence": dict(probe["file_evidence"]),
            "host_capabilities": dict(probe["host_capabilities"]),
        }

    def _fresh_ids(self) -> tuple[str, str, str]:
        nonce = uuid4().hex
        return "op_s06_" + nonce, "req_s06_" + nonce, nonce

    def _task_spec(self, request_id: str, hip_path: str, hip_sha256: str, frame_start: int, frame_end: int) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "task_type": "visual.reference_rebuild",
            "intent": "Controller-owned F2 S-06 technical short segment",
            "target": {
                "application": "pipeline",
                "scene_mode": "existing",
                "scene_path": hip_path,
            },
            "feedback": "technical host observation only; no smoke acceptance",
            "constraints": {
                "frozen_scene_sha256": hip_sha256,
                "cache_allowed": False,
                "render_allowed": False,
            },
            "render": {
                "resolution": [1, 1],
                "frame_range": {"start": frame_start, "end": frame_end, "step": 1},
            },
            "metadata": {
                "controller_id": self.controller_id,
                "s06_request_id": request_id,
                "smoke_capability_proven": False,
            },
            "idempotency_key": "s06-controller-" + request_id,
        }

    def prepare_authorization(
        self,
        *,
        scene_probe: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
        frame_start: int,
        frame_end: int,
        pulses: list[list[int]] | tuple[tuple[int, int], ...],
        params: Mapping[str, Any],
        authorization_path: Path | str | None = None,
        lease_ttl: float = 120.0,
        max_elapsed_seconds: float = 120.0,
        max_cook_seconds_per_frame: float = 30.0,
    ) -> dict[str, Any]:
        """Create the complete auth bundle after read-only scene preparation."""

        # Capture one read-only probe and use that exact value for both the
        # readiness check and the issued identity.  A callable probe may be a
        # live GUI request; invoking it twice could authorize one scene and
        # issue against another after a load/save event.
        probe_value = scene_probe() if callable(scene_probe) else scene_probe
        inspected = self.inspect(probe_value)
        if inspected["state"] != "SCENE_PREPARED":
            return inspected
        if type(frame_start) is not int or type(frame_end) is not int:
            return {"state": "BLOCKED", "reason": "FRAME_RANGE_INVALID", "host_calls": 0}
        try:
            safe_params = _strict_json_value(dict(params))
            schedule = schedule_from_pulses(frame_start, frame_end, pulses)
        except (TypeError, ValueError) as exc:
            return {"state": "BLOCKED", "reason": "CONTROLLER_INPUT_INVALID", "failures": [str(exc)], "host_calls": 0}
        try:
            lease_ttl_value = float(lease_ttl)
            elapsed_value = float(max_elapsed_seconds)
            cook_value = float(max_cook_seconds_per_frame)
        except (TypeError, ValueError):
            return {"state": "BLOCKED", "reason": "CONTROLLER_BUDGET_INVALID", "host_calls": 0}
        if not 0 < lease_ttl_value <= 600.0 or not 0 < elapsed_value <= 120.0 or not 0 < cook_value <= 30.0:
            return {"state": "BLOCKED", "reason": "CONTROLLER_BUDGET_INVALID", "host_calls": 0}

        identity = dict(inspected["scene_identity"])
        if not isinstance(probe_value, Mapping):
            return {"state": "BLOCKED", "reason": "SCENE_PROBE_NOT_OBJECT", "host_calls": 0}
        operation_id, request_id, nonce = self._fresh_ids()
        graph_root = "/obj/BRIDGE_GRAPH_" + hashlib.sha256(
            canonical_json([self.controller_id, request_id, identity["scene_id"]]).encode("utf-8")
        ).hexdigest()
        scheduler_owner = str((self.root_dir / "scheduler-owners" / (operation_id + "-" + nonce[:12])).absolute())
        lease = None
        reservation = None
        task_id = None
        ownership_record: dict[str, Any] | None = None
        try:
            task_id = self.store.create_task(
                self._task_spec(
                    request_id,
                    identity["hip_path"],
                    str(probe_value["hip_sha256"]),
                    frame_start,
                    frame_end,
                )
            )
            lease = self.lease_store.acquire(
                task_id=task_id,
                session_id=identity["session_id"],
                process_generation=identity["process_generation"],
                scene_id=identity["scene_id"],
                root=graph_root,
                ttl=lease_ttl_value,
            )
            ownership_record = self._create_ownership_record(
                task_id=task_id,
                operation_id=operation_id,
                request_id=request_id,
                identity=identity,
                probe=probe_value,
                graph_root=graph_root,
            )
            reservation = self.scheduler.reserve(scheduler_owner, operation_id)
            preparation = dict(inspected["preparation"])
            preparation["scene_ownership"] = {
                "schema": ownership_record["schema"],
                "record_path": ownership_record["record_path"],
                "record_hash": ownership_record["record_hash"],
                "phase": ownership_record["phase"],
            }
            self.store.put_record(task_id, PREPARATION_CATEGORY, request_id, {
                **preparation,
                "task_id": task_id,
                "operation_id": operation_id,
                "request_id": request_id,
                "controller_id": self.controller_id,
            })
            frame_segment = {
                "start": frame_start,
                "end": frame_end,
                "step": 1,
                "preroll_frames": 0,
                "max_elapsed_seconds": elapsed_value,
                "max_cook_seconds_per_frame": cook_value,
            }
            budget = {
                "slot": 1,
                "active": True,
                "owner_root": scheduler_owner,
                "operation_id": operation_id,
                "token": reservation["token"],
                "generation": reservation["generation"],
                "phase": "RESERVED",
                "max_frames": frame_end - frame_start + 1,
                "remaining_heavy_jobs": 1,
                "cache_allowed": False,
                "render_allowed": False,
                "scheduler_root": str(self.scheduler_root),
            }
            bundle: dict[str, Any] = {
                "schema": AUTHORIZATION_SCHEMA,
                "task_id": task_id,
                "operation_id": operation_id,
                "request_id": request_id,
                "scope": SCOPE,
                "authorized": True,
                "operation": {
                    "task_id": task_id,
                    "operation_id": operation_id,
                    "state": "AUTHORIZED",
                    "attempt_generation": 1,
                    "unknown": False,
                },
                "scene_lease": {
                    "task_id": lease.task_id,
                    "session_id": lease.session_id,
                    "process_generation": lease.process_generation,
                    "scene_id": lease.scene_id,
                    "root": lease.root,
                    "generation": lease.generation,
                    "expires_at": lease.expires_at,
                },
                "lease_store": {"path": str(self.lease_store.path)},
                "heavy_budget": budget,
                "frame_segment": frame_segment,
                "source_binding": dict(self.source_binding),
                "source_schedule": schedule,
                "velocity_sentinel": default_controller_sentinel(),
                "scene_ownership": dict(ownership_record),
                "host_binding": {
                    "schema": HOST_BINDING_SCHEMA,
                    "session_id": identity["session_id"],
                    "process_generation": identity["process_generation"],
                    "scene_id": identity["scene_id"],
                    "hip_path": identity["hip_path"],
                    "root": graph_root,
                },
                "execution_receipt": {
                    "schema": RECEIPT_SCHEMA,
                    "store_path": str(self.store.path),
                    "idempotency_key": RECEIPT_PREFIX + operation_id,
                    "record_category": OPERATION_CATEGORY,
                    "record_id": operation_id,
                },
            }
            self.scheduler.arm(scheduler_owner, operation_id, reservation["token"])
            budget["phase"] = "DISPATCHING"
            budget["scheduler_snapshot_hash"] = canonical_sha256(self.scheduler.snapshot() or {})
            preparation_issuance = {
                "schema": CONTROLLER_ISSUANCE_SCHEMA,
                "scene_preparation": preparation,
                "scene_ownership": dict(ownership_record),
            }
            bundle["controller_issuance"] = preparation_issuance
            auth_hash = authorization_hash(bundle)
            request = controller_request_core(
                task_id=task_id,
                operation_id=operation_id,
                request_id=request_id,
                execution_root=graph_root,
                host_identity=identity,
                frame_segment=frame_segment,
                source_schedule=schedule,
                source_binding=self.source_binding,
                velocity_sentinel=bundle["velocity_sentinel"],
                authorization_hash_value=auth_hash,
                scene_ownership=ownership_record,
            )
            bundle["controller_issuance"] = {
                "schema": CONTROLLER_ISSUANCE_SCHEMA,
                "status": "ISSUED",
                "issuer": "trusted_s06_controller",
                "controller_id": self.controller_id,
                "request_id": request_id,
                "authorization_hash": auth_hash,
                "controller_request_hash": controller_request_hash(request),
                "controller_request": request,
                "scene_preparation": preparation,
                "scene_ownership": dict(ownership_record),
                "preparation_record_id": request_id,
                "first_graph_mutation": "pending",
            }
            # The task id is created by the controller, so callers cannot know
            # it when they submit preparation params.  Bind it into the
            # durable intent here; execute() will inject the same value after
            # checking that an optional caller-supplied value is not stale.
            intent_params = dict(safe_params)
            intent_params["task_id"] = task_id
            intent = intent_payload(bundle, intent_params)
            intent_hash = canonical_sha256(intent)
            record = {
                "schema": OPERATION_SCHEMA,
                "task_id": task_id,
                "operation_id": operation_id,
                "request_id": request_id,
                "scope": SCOPE,
                "status": "AUTHORIZED",
                "unknown": False,
                "attempt_generation": 1,
                "controller_issued": True,
                "authorization_hash": auth_hash,
                "controller_request_hash": bundle["controller_issuance"]["controller_request_hash"],
                "intent_hash": intent_hash,
                "intent": intent,
                "preparation_record_id": request_id,
                "first_graph_mutation": "pending",
                "scene_ownership_record_hash": ownership_record["record_hash"],
            }
            self.store.put_record(task_id, OPERATION_CATEGORY, operation_id, record)
            output = Path(authorization_path).expanduser().absolute() if authorization_path else self.root_dir / "authorization" / (operation_id + ".json")
            _atomic_json(output, bundle)
            current_slot = self.scheduler.snapshot() or {}
            if not (
                current_slot.get("active") == 1
                and current_slot.get("phase") == "DISPATCHING"
                and current_slot.get("owner_root") == scheduler_owner
                and current_slot.get("operation_id") == operation_id
                and current_slot.get("token") == reservation["token"]
            ):
                raise RuntimeError("scheduler slot changed while issuing authorization")
            return {
                "state": "AUTHORIZED",
                "task_id": task_id,
                "operation_id": operation_id,
                "request_id": request_id,
                "authorization_path": str(output),
                "authorization_hash": auth_hash,
                "controller_request_hash": bundle["controller_issuance"]["controller_request_hash"],
                "intent_hash": intent_hash,
                "graph_root": graph_root,
                "scheduler_owner_root": scheduler_owner,
                "scene_preparation": preparation,
                "scene_ownership": dict(ownership_record),
                "bundle": bundle,
                "host_calls": 0,
                "first_graph_mutation": "pending",
                "smoke_capability_proven": False,
            }
        except Exception as exc:
            if reservation is not None:
                try:
                    self.scheduler.fence_unstarted(scheduler_owner, operation_id, reservation["token"])
                    self.scheduler.release(scheduler_owner, operation_id, reservation["token"], unstarted=True)
                except Exception:
                    pass
            if lease is not None:
                try:
                    self.lease_store.revoke(lease, host_operations_reconciled=True)
                except Exception:
                    pass
            return {
                "state": "UNKNOWN",
                "reason": "AUTHORIZATION_PREPARATION_COMMIT_UNCERTAIN",
                "failures": [type(exc).__name__ + ":" + str(exc)],
                "operation_id": operation_id,
                "task_id": task_id,
                "host_calls": 0,
                "blockers": ["RECONCILIATION_REQUIRED"],
            }

    def execute(
        self,
        prepared: Mapping[str, Any],
        adapter: "S06MainThreadAdapter",
        *,
        params: Mapping[str, Any],
        operator_confirmed: bool = False,
    ) -> dict[str, Any]:
        """Run the existing durable validator through the narrow adapter."""

        if operator_confirmed is not True:
            return {
                "state": "BLOCKED",
                "reason": "EXPLICIT_SHORT_SEGMENT_CONFIRMATION_REQUIRED",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        if prepared.get("state") != "AUTHORIZED":
            return {"state": "BLOCKED", "reason": "AUTHORIZATION_NOT_READY", "host_calls": 0}
        authorization_path = Path(str(prepared.get("authorization_path") or ""))
        bundle = _read_json(authorization_path)
        ownership_reference = bundle.get("scene_ownership")
        if not isinstance(ownership_reference, Mapping):
            return {
                "state": "BLOCKED",
                "reason": "SCENE_OWNERSHIP_RECORD_MISSING",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        try:
            ownership_record = self._read_ownership_record(ownership_reference)
        except (OSError, ValueError, TypeError, KeyError):
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_RECORD_UNAVAILABLE",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
                "blockers": ["RECONCILIATION_REQUIRED"],
            }
        if not isinstance(params, Mapping):
            return {
                "state": "BLOCKED",
                "reason": "TASK_PARAMS_INVALID",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        supplied_task_id = params.get("task_id")
        if supplied_task_id is not None and supplied_task_id != bundle["task_id"]:
            return {
                "state": "BLOCKED",
                "reason": "TASK_PARAMS_INVALID",
                "blockers": ["TASK_IDENTITY_MISMATCH"],
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        execution_params = dict(params)
        execution_params["task_id"] = bundle["task_id"]

        # A completed receipt may exist even when the controller lost the
        # final scene-marker write.  Reconcile that receipt and the current
        # task graph before the STARTED no-rerun fence.  A RUNNING/missing
        # receipt deliberately returns None and remains UNKNOWN below.
        if ownership_record.get("phase") != "GRAPH_MUTATION_COMPLETED":
            recovered = self._recover_completed_receipt(
                bundle, ownership_record, adapter, execution_params,
            )
            if recovered is not None:
                return recovered
        if ownership_record.get("phase") == "GRAPH_MUTATION_STARTED":
            return {
                "state": "UNKNOWN",
                "reason": "SCENE_OWNERSHIP_MUTATION_IN_PROGRESS",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
                "blockers": ["RECONCILIATION_REQUIRED", "HOST_OPERATION_MUST_NOT_BE_RERUN"],
            }
        probe = adapter.inspect_scene(ownership_record=ownership_record)
        failures = _host_probe_failures(probe, ownership_record)
        if failures:
            return {
                "state": "BLOCKED",
                "reason": "HOST_SCENE_CHANGED_BEFORE_DISPATCH",
                "failures": failures,
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        expected = bundle.get("host_binding") or {}
        if any(probe["scene_identity"].get(key) != expected.get(key) for key in ("session_id", "process_generation", "scene_id", "hip_path")):
            return {
                "state": "BLOCKED",
                "reason": "HOST_IDENTITY_MISMATCH",
                "operation_id": prepared.get("operation_id"),
                "host_calls": 0,
            }
        validator = _load_validator()
        host = adapter.host_metadata(probe["scene_identity"])
        frame = bundle["frame_segment"]
        host_executor = adapter.executor(bundle, dict(params))

        def start_owned_mutation(host_value, signed_bundle, start, end, received_params):
            # This call runs only after the validator has acquired the durable
            # claim, current lease, exact heavy slot, and frame guard.  The
            # record is the durable no-rerun marker if the host response is
            # later lost.
            self._update_ownership_record(
                ownership_record,
                phase="GRAPH_MUTATION_STARTED",
                first_graph_mutation="started",
            )
            return host_executor(host_value, signed_bundle, start, end, received_params)

        result = validator.execute_short_segment(
            ROOT / "tests" / "fixtures" / "pyro-sourcing-reviewed.json",
            authorization_path,
            task_id=str(bundle["task_id"]),
            operation_id=str(bundle["operation_id"]),
            frame_start=int(frame["start"]),
            frame_end=int(frame["end"]),
            params=execution_params,
            hou_module=host,
            executor=start_owned_mutation,
        )
        if result.get("state") in S06_COMPLETED_HOST_STATES and result.get("execution_started") is True:
            try:
                latest = self._read_ownership_record(ownership_reference)
                self._update_ownership_record(
                    latest,
                    phase="GRAPH_MUTATION_COMPLETED",
                    first_graph_mutation="completed",
                    manifest=result.get("scene_manifest"),
                )
            except (OSError, ValueError, TypeError, KeyError):
                return {
                    "state": "UNKNOWN",
                    "reason": "SCENE_OWNERSHIP_COMPLETION_RECORD_UNCERTAIN",
                    "operation_id": prepared.get("operation_id"),
                    "execution_started": True,
                    "blockers": ["RECONCILIATION_REQUIRED", "SCENE_OWNERSHIP_RECORD_UNCERTAIN"],
                }
        return result


def _load_validator() -> Any:
    path = ROOT / "tools" / "validate_f2_solver_sourcing.py"
    spec = importlib.util.spec_from_file_location("s06_controller_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("S-06 validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RemoteHostMetadata:
    def __init__(self, identity: Mapping[str, Any], build: str = EXPECTED_BUILD) -> None:
        self._identity = dict(identity)
        self._build = str(build)

    def applicationVersionString(self) -> str:
        return self._build

    def bridge_scene_identity(self) -> dict[str, Any]:
        return dict(self._identity)


class S06MainThreadAdapter:
    """Narrow transport: inspect, S-06 build, and S-06 frame observation only."""

    ALLOWED_COMMANDS = frozenset({ADAPTER_INSPECT_COMMAND, ADAPTER_BUILD_COMMAND})

    def __init__(self, transport: Any) -> None:
        self.transport = transport
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _call(self, command: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if command not in self.ALLOWED_COMMANDS:
            raise ValueError("S-06 adapter command is outside the narrow allowlist")
        safe = _strict_json_value(dict(params))
        if "code" in safe or "python" in safe:
            raise ValueError("S-06 adapter rejects executable payloads")
        self.calls.append((command, dict(safe)))
        result = self.transport.call(command, dict(safe))
        if isinstance(result, Mapping) and result.get("status") == "success":
            result = result.get("data")
        if not isinstance(result, Mapping):
            raise ValueError("S-06 adapter received no structured result")
        return dict(result)

    def inspect_scene(self, *, ownership_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"adapter": ADAPTER_SCHEMA, "read_only": True}
        if ownership_record is not None:
            params["ownership_record"] = dict(ownership_record)
        return self._call(ADAPTER_INSPECT_COMMAND, params)

    def host_metadata(self, identity: Mapping[str, Any]) -> _RemoteHostMetadata:
        return _RemoteHostMetadata(identity)

    def _scoped_params(self, bundle: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
        """Attach the same signed context to build and every observe call."""

        host_binding = bundle["host_binding"]
        issuance = bundle["controller_issuance"]
        request = issuance["controller_request"]
        result = dict(params)
        result["task_id"] = bundle["task_id"]
        result["bridge_graph_root"] = host_binding["root"]
        result["bridge_execution_binding"] = {
            "schema": HOST_BINDING_SCHEMA,
            "task_id": bundle["task_id"],
            "operation_id": bundle["operation_id"],
            "host_identity": {key: host_binding[key] for key in ("session_id", "process_generation", "scene_id", "hip_path")},
            "execution_root": host_binding["root"],
        }
        result["s06_controller_request"] = dict(request)
        result["s06_controller_request_hash"] = issuance["controller_request_hash"]
        result["f2_short_segment"] = {
            "schema": "bridge.f2.short-segment-intent/2.0",
            "frame_segment": dict(bundle["frame_segment"]),
            "source_binding": dict(bundle["source_binding"]),
            "source_schedule": dict(bundle["source_schedule"]),
            "cache_allowed": False,
            "render_allowed": False,
        }
        return result

    def execute_once(self, request: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("schema") != CONTROLLER_REQUEST_SCHEMA or request.get("adapter") != ADAPTER_SCHEMA:
            raise ValueError("controller request is not bound to the S-06 adapter")
        return self._call(
            ADAPTER_BUILD_COMMAND,
            {
                "s06_action": "build",
                "s06_controller_request": dict(request),
                **dict(params),
            },
        )

    def executor(self, bundle: Mapping[str, Any], params: Mapping[str, Any]) -> Callable[..., dict[str, Any]]:
        request = dict((bundle.get("controller_issuance") or {}).get("controller_request") or {})

        def run(_host: Any, signed_bundle: Mapping[str, Any], _start: int, _end: int, _params: dict[str, Any]) -> dict[str, Any]:
            guard = signed_bundle["frame_guard"]
            scoped_params = self._scoped_params(bundle, params)
            built = guard.run_host_call(lambda: self.execute_once(request, scoped_params))
            manifest = built.get("scene_manifest") if isinstance(built, Mapping) else None
            nodes = manifest.get("nodes") if isinstance(manifest, Mapping) else None
            if not isinstance(nodes, Mapping):
                raise ValueError("S-06 adapter build returned no scene manifest")
            solver_path = str(nodes.get("solver") or "")
            source_path = str(nodes.get("source_volume") or "")
            if not solver_path or not source_path:
                raise ValueError("S-06 adapter build returned no solver/source paths")
            for frame in guard.expected_frames:
                guard.run_frame(
                    frame,
                    lambda frame=frame: self._call(
                        ADAPTER_BUILD_COMMAND,
                        {
                            **scoped_params,
                            "s06_action": "observe",
                            "s06_controller_request": request,
                            "task_id": bundle["task_id"],
                            "solver_path": solver_path,
                            "source_path": source_path,
                            "frame": frame,
                        },
                    ),
                )
            return {
                "execution_started": True,
                "adapter": ADAPTER_SCHEMA,
                "scene_manifest": manifest,
            }

        return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-json", type=Path, help="read-only scene probe JSON")
    parser.add_argument("--root-dir", type=Path, required=True)
    parser.add_argument("--authorization-json", type=Path)
    parser.add_argument("--frame-start", type=int, default=1)
    parser.add_argument("--frame-end", type=int, default=3)
    parser.add_argument("--pulse", action="append", default=[], help="half-open pulse START:END; software preparation only")
    parser.add_argument("--params-json", type=Path)
    args = parser.parse_args(argv)
    controller = S06Controller(args.root_dir)
    if args.inspect_json is None:
        print(json.dumps({
            "state": "BLOCKED",
            "reason": "READ_ONLY_SCENE_PROBE_REQUIRED",
            "real_dcc_started": False,
            "simulation_cache_written": False,
            "render_started": False,
            "smoke_capability_proven": False,
        }, ensure_ascii=False, indent=2))
        return 2
    probe = json.loads(args.inspect_json.read_text(encoding="utf-8"))
    pulses = []
    for raw in args.pulse or ["2:3"]:
        start, end = raw.split(":", 1)
        pulses.append([int(start), int(end)])
    params = json.loads(args.params_json.read_text(encoding="utf-8")) if args.params_json else {"task_id": "controller-filled"}
    prepared = controller.prepare_authorization(
        scene_probe=probe,
        frame_start=args.frame_start,
        frame_end=args.frame_end,
        pulses=pulses,
        params=params,
        authorization_path=args.authorization_json,
    )
    print(json.dumps({
        **{key: value for key, value in prepared.items() if key != "bundle"},
        "real_dcc_started": False,
        "simulation_cache_written": False,
        "render_started": False,
        "smoke_capability_proven": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if prepared.get("state") == "AUTHORIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
