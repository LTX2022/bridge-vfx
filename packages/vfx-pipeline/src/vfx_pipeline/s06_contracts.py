"""Shared contracts for the controller-owned S-06 technical short segment.

This module contains only deterministic, path-free contract helpers. It does
not discover a DCC, create a scene, mint a license, or claim that a host is
safe. The controller owns issuance; the Houdini add-on only validates the
shape and routes the already-issued request on Houdini's main thread.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping


AUTHORIZATION_SCHEMA = "bridge.f2.short-segment-authorization/3.0"
INTENT_SCHEMA = "bridge.f2.short-segment-intent/2.0"
OPERATION_SCHEMA = "bridge.f2.short-segment-operation/2.0"
RECEIPT_SCHEMA = "bridge.f2.short-segment-receipt-binding/2.0"
FINALIZATION_SCHEMA = "bridge.f2.short-segment-finalization/1.0"
SCHEDULE_SCHEMA = "bridge.f2.source-activation-schedule/1.0"
CONTROLLER_ISSUANCE_SCHEMA = "bridge.f2.s06-controller-issuance/1.0"
CONTROLLER_REQUEST_SCHEMA = "bridge.f2.s06-controller-request/1.0"
HOST_BINDING_SCHEMA = "bridge.f2.short-segment-host-binding/2.0"
PREPARATION_SCHEMA = "bridge.f2.s06-scene-preparation/1.0"
SCENE_OWNERSHIP_SCHEMA = "bridge.f2.s06-scene-ownership/1.0"
SCENE_OWNERSHIP_EVIDENCE_SCHEMA = "bridge.f2.s06-scene-ownership-evidence/1.0"
ADAPTER_SCHEMA = "bridge.f2.s06-main-thread-adapter/1.0"
VELOCITY_SENTINEL_SCHEMA = "bridge.f2.s06-controller-velocity-sentinel/1.0"
ADAPTER_BUILD_COMMAND = "bridge.s06.short_segment"
ADAPTER_INSPECT_COMMAND = "bridge.s06.inspect_scene"
SCOPE = "f2_solver_short_segment"
OPERATION_CATEGORY = "f2_short_segment_operation"
PREPARATION_CATEGORY = "f2_short_segment_scene_preparation"
RECEIPT_PREFIX = "f2.short-segment:"
HOST_IDENTITY_KEYS = ("session_id", "process_generation", "scene_id", "hip_path")
ROOT_RE = re.compile(r"^/obj/BRIDGE_GRAPH_[0-9a-f]{64}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FRAME_KEYS = {
    "start",
    "end",
    "step",
    "preroll_frames",
    "max_elapsed_seconds",
    "max_cook_seconds_per_frame",
}


def canonical_json(value: Any) -> str:
    """Encode a finite JSON value with the controller's canonical settings."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def is_root(value: Any) -> bool:
    return isinstance(value, str) and bool(ROOT_RE.fullmatch(value))


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64_RE.fullmatch(value))


def scene_ownership_hash(record: Mapping[str, Any]) -> str:
    """Hash a controller-owned scene record without trusting its hash field."""

    payload = dict(record)
    payload.pop("record_hash", None)
    return canonical_sha256(payload)


def scene_ownership_record_valid(record: Any) -> bool:
    """Return whether a record is self-consistent at the contract seam."""

    if not isinstance(record, Mapping):
        return False
    if record.get("schema") != SCENE_OWNERSHIP_SCHEMA:
        return False
    record_hash = record.get("record_hash")
    return is_sha256(record_hash) and record_hash == scene_ownership_hash(record)


def finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def expected_active(schedule: Mapping[str, Any], frame: int) -> dict[int, bool]:
    rows = schedule.get("rows") if isinstance(schedule, Mapping) else None
    result: dict[int, bool] = {}
    if not isinstance(rows, Mapping):
        return result
    for name in ("1", "2"):
        intervals = rows.get(name, [])
        result[int(name)] = bool(
            isinstance(intervals, list)
            and any(
                isinstance(item, Mapping)
                and type(item.get("start")) is int
                and type(item.get("end")) is int
                and int(item["start"]) <= frame < int(item["end"])
                for item in intervals
            )
        )
    return result


def schedule_from_pulses(
    frame_start: int,
    frame_end: int,
    pulses: list[list[int]] | tuple[tuple[int, int], ...],
    *,
    step: int = 1,
) -> dict[str, Any]:
    """Build a strict half-open schedule owned by the controller."""

    if type(frame_start) is not int or type(frame_end) is not int or frame_start < 0 or frame_end < frame_start:
        raise ValueError("invalid controller frame range")
    if type(step) is not int or step != 1:
        raise ValueError("S-06 requires an integer step of one")
    normalized: list[dict[str, int]] = []
    prior_end: int | None = None
    for pulse in pulses:
        if not isinstance(pulse, (list, tuple)) or len(pulse) != 2:
            raise ValueError("each pulse must be a two-item half-open interval")
        start, end = pulse
        if type(start) is not int or type(end) is not int or start < frame_start or end <= start or end > frame_end + step:
            raise ValueError("pulse is outside the controller frame range")
        if prior_end is not None and start < prior_end:
            raise ValueError("pulses must be sorted and non-overlapping")
        normalized.append({"start": start, "end": end})
        prior_end = end
    if not normalized:
        raise ValueError("at least one pulse is required for S-06")
    return {
        "schema": SCHEDULE_SCHEMA,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "step": step,
        "rows": {"1": list(normalized), "2": list(normalized)},
    }


def authorization_core(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact fields covered by a controller issuance hash."""

    operation = bundle.get("operation") or {}
    budget = bundle.get("heavy_budget") or {}
    receipt = bundle.get("execution_receipt") or {}
    preparation = (bundle.get("controller_issuance") or {}).get("scene_preparation") or {}
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "task_id": bundle.get("task_id"),
        "operation_id": bundle.get("operation_id"),
        "request_id": bundle.get("request_id"),
        "scope": bundle.get("scope"),
        "operation": {
            "task_id": operation.get("task_id"),
            "operation_id": operation.get("operation_id"),
            "state": operation.get("state"),
            "attempt_generation": operation.get("attempt_generation"),
            "unknown": operation.get("unknown"),
        },
        "scene_lease": dict(bundle.get("scene_lease") or {}),
        "heavy_budget": {
            "slot": budget.get("slot"),
            "owner_root": budget.get("owner_root"),
            "operation_id": budget.get("operation_id"),
            "token": budget.get("token"),
            "generation": budget.get("generation"),
            "phase": budget.get("phase"),
            "max_frames": budget.get("max_frames"),
            "remaining_heavy_jobs": budget.get("remaining_heavy_jobs"),
            "cache_allowed": budget.get("cache_allowed"),
            "render_allowed": budget.get("render_allowed"),
            "scheduler_root": budget.get("scheduler_root"),
        },
        "frame_segment": dict(bundle.get("frame_segment") or {}),
        "source_binding": dict(bundle.get("source_binding") or {}),
        "source_schedule": dict(bundle.get("source_schedule") or {}),
        "host_binding": dict(bundle.get("host_binding") or {}),
        "velocity_sentinel": dict(bundle.get("velocity_sentinel") or {}),
        "execution_receipt": {
            "schema": receipt.get("schema"),
            "store_path": receipt.get("store_path"),
            "idempotency_key": receipt.get("idempotency_key"),
            "record_category": receipt.get("record_category"),
            "record_id": receipt.get("record_id"),
        },
        "scene_preparation": dict(preparation),
        "scene_ownership": dict(bundle.get("scene_ownership") or {}),
    }


def authorization_hash(bundle: Mapping[str, Any]) -> str:
    return canonical_sha256(authorization_core(bundle))


def controller_request_core(
    *,
    task_id: str,
    operation_id: str,
    request_id: str,
    execution_root: str,
    host_identity: Mapping[str, Any],
    frame_segment: Mapping[str, Any],
    source_schedule: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    velocity_sentinel: Mapping[str, Any],
    authorization_hash_value: str,
    scene_ownership: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "schema": CONTROLLER_REQUEST_SCHEMA,
        "adapter": ADAPTER_SCHEMA,
        "transport": "houdini_main_thread",
        "task_id": task_id,
        "operation_id": operation_id,
        "request_id": request_id,
        "execution_root": execution_root,
        "host_identity": {key: host_identity.get(key) for key in HOST_IDENTITY_KEYS},
        "frame_segment": dict(frame_segment),
        "source_schedule": dict(source_schedule),
        "source_binding": dict(source_binding),
        "velocity_sentinel": dict(velocity_sentinel),
        "authorization_hash": authorization_hash_value,
        "cache_allowed": False,
        "render_allowed": False,
        "first_graph_mutation": "pending",
    }
    if scene_ownership is not None:
        request["scene_ownership"] = dict(scene_ownership)
    return request


def controller_request_hash(request: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            key: request.get(key)
            for key in (
                "schema",
                "adapter",
                "transport",
                "task_id",
                "operation_id",
                "request_id",
                "execution_root",
                "host_identity",
                "frame_segment",
                "source_schedule",
                "source_binding",
                "velocity_sentinel",
                "authorization_hash",
                "cache_allowed",
                "render_allowed",
                "first_graph_mutation",
                "scene_ownership",
            )
        }
    )


def intent_payload(bundle: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    """Build the canonical operation intent shared by controller and validator."""

    operation = bundle.get("operation") or {}
    budget = bundle.get("heavy_budget") or {}
    issuance = bundle.get("controller_issuance") or {}
    return {
        "schema": INTENT_SCHEMA,
        "task_id": bundle.get("task_id"),
        "operation_id": bundle.get("operation_id"),
        "request_id": bundle.get("request_id"),
        "scope": bundle.get("scope"),
        "attempt_generation": operation.get("attempt_generation"),
        "source_binding": dict(bundle.get("source_binding") or {}),
        "velocity_sentinel": dict(bundle.get("velocity_sentinel") or {}),
        "source_schedule": dict(bundle.get("source_schedule") or {}),
        "frame_segment": dict(bundle.get("frame_segment") or {}),
        "host_binding": dict(bundle.get("host_binding") or {}),
        "scene_lease": dict(bundle.get("scene_lease") or {}),
        "heavy_slot": {
            "slot": budget.get("slot"),
            "owner_root": budget.get("owner_root"),
            "operation_id": budget.get("operation_id"),
            "token": budget.get("token"),
            "generation": budget.get("generation"),
            "max_frames": budget.get("max_frames"),
        },
        "controller_issuance": {
            "schema": issuance.get("schema"),
            "controller_id": issuance.get("controller_id"),
            "authorization_hash": issuance.get("authorization_hash"),
            "controller_request_hash": issuance.get("controller_request_hash"),
            "preparation_record_id": issuance.get("preparation_record_id"),
        },
        "scene_ownership": dict(bundle.get("scene_ownership") or {}),
        "params": dict(params),
    }
