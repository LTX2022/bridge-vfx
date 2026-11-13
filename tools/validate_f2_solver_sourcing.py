#!/usr/bin/env python3
"""Validate the reviewed F2 type capture and optionally run one short segment.

The default mode is a strict, plan-only check.  It recomputes the capture
digest from the capture object (without trusting ``snapshot_sha256``), checks
the reviewed file digest and the complete native template contract, and never
imports ``hou``.

The explicit execution mode is a separate, heavily guarded host entry point.
It requires an operator confirmation plus a controller-issued operation,
scene-lease and heavy-slot authorization bundle.  It can call the real
Houdini short-segment executor when those gates and host conditions are
present, but this package never invokes that mode by default and does not
write a cache or render output as part of the short check.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping


EXPECTED_BUILD = [21, 0, 631]
EXPECTED_SNAPSHOT_SHA256 = "d1a194238b173645e278524cfc3413ee013426263fcc6e63650ff05977670234"
EXPECTED_CAPTURE_FILE_SHA256 = "3f49969013ea11850a75688a00a5850c89ffa86acf9ad08331690595ce3a88db"
EXPECTED_TEMPLATE_COUNT = 485
CAPTURE_SCHEMA = "bridge.pyro.sourcing-template-capture/1.0"
CAPTURE_EVIDENCE_KIND = "UNATTESTED_LOCAL_TYPE_CAPTURE"
VALIDATION_SCHEMA = "bridge.f2.solver-sourcing-validation/1.2"
SHORT_SEGMENT_SCOPE = "f2_solver_short_segment"
SHORT_SEGMENT_MAX_FRAMES = 12
SHORT_SEGMENT_AUTHORIZATION_SCHEMA = "bridge.f2.short-segment-authorization/3.0"
SHORT_SEGMENT_INTENT_SCHEMA = "bridge.f2.short-segment-intent/2.0"
SHORT_SEGMENT_OPERATION_SCHEMA = "bridge.f2.short-segment-operation/2.0"
SHORT_SEGMENT_FINALIZATION_SCHEMA = "bridge.f2.short-segment-finalization/1.0"
SHORT_SEGMENT_RECEIPT_SCHEMA = "bridge.f2.short-segment-receipt-binding/2.0"
SHORT_SEGMENT_OPERATION_CATEGORY = "f2_short_segment_operation"
SHORT_SEGMENT_RECEIPT_PREFIX = "f2.short-segment:"
SHORT_SEGMENT_MAX_ELAPSED_SECONDS = 120.0
SHORT_SEGMENT_MAX_COOK_SECONDS = 30.0
SHORT_SEGMENT_HOST_IDENTITY_KEYS = ("session_id", "process_generation", "scene_id", "hip_path")
SHORT_SEGMENT_SCHEDULE_SCHEMA = "bridge.f2.source-activation-schedule/1.0"
CONTROLLER_ISSUANCE_SCHEMA = "bridge.f2.s06-controller-issuance/1.0"
CONTROLLER_REQUEST_SCHEMA = "bridge.f2.s06-controller-request/1.0"
HOST_BINDING_SCHEMA = "bridge.f2.short-segment-host-binding/2.0"
PREPARATION_SCHEMA = "bridge.f2.s06-scene-preparation/1.0"
SCENE_OWNERSHIP_SCHEMA = "bridge.f2.s06-scene-ownership/1.0"
ADAPTER_SCHEMA = "bridge.f2.s06-main-thread-adapter/1.0"
ADAPTER_BUILD_COMMAND = "bridge.s06.short_segment"
ADAPTER_INSPECT_COMMAND = "bridge.s06.inspect_scene"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FRAME_KEYS = {
    "start", "end", "step", "preroll_frames", "max_elapsed_seconds", "max_cook_seconds_per_frame",
}
_SCHEDULE_KEYS = {"schema", "frame_start", "frame_end", "step", "rows"}
_SCHEDULE_INTERVAL_KEYS = {"start", "end"}
_ROOT = Path(__file__).resolve().parents[1]
_ADDON_MODULE: Any = None

# This is the control-side review summary for the exact GUI capture supplied
# to the implementation run.  A caller may provide a copy of this summary,
# but a caller cannot replace it with a self-consistent new summary.
PINNED_REVIEW_SUMMARY: dict[str, Any] = {
    "file_sha256": EXPECTED_CAPTURE_FILE_SHA256,
    "snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
    "state": "CAPTURED_NOT_BOUND",
    "version": EXPECTED_BUILD,
    "template_count": EXPECTED_TEMPLATE_COUNT,
    "errors": [],
    "warnings": [],
    "scope": "local_type_capture_only",
    "prior_failure_template": {
        "name": "fieldguidevismode",
        "type": "parmTemplateType.Ramp",
    },
}

_CAPTURE_KEYS = {
    "schema", "evidence_kind", "capture_state", "solver_sourcing_implemented",
    "registered_bindings", "runtime_verified", "visual_verified",
    "route_verified", "provider_verified", "dcc_acceptance_unlocked", "nodes",
    "errors", "failure_details", "warnings", "houdini_version", "snapshot_sha256",
}
_NODE_KEYS = {
    "requested_type", "resolved_type", "category", "available", "min_inputs",
    "max_inputs", "templates",
}
_UNAVAILABLE_NODE_KEYS = {"requested_type", "available"}
_TEMPLATE_KEYS = {
    "template_path", "name", "label", "type", "components", "folder_type",
    "children", "dynamic_menu", "menu_items", "menu_labels",
}
_STATIC_RANGE_ITEMS = ["static", "sequence"]
_STATIC_RANGE_LABELS = ["Static Frame", "Frame Range"]
_STATIC_OPERATION_ITEMS = [
    "copy", "add", "sub", "mul", "div", "max", "min", "average", "guide", "blend", "none",
]
_STATIC_OPERATION_LABELS = [
    "Copy", "Add", "Subtract", "Multiply", "Divide", "Maximum", "Minimum", "Average", "Pull", "Blend", "None",
]
_STATIC_RANK_ITEMS = ["scalar", "vector"]
_STATIC_RANK_LABELS = ["Scalar", "Vector"]


def _canonical_json(value: Any) -> str:
    """Match the capture tool's canonical JSON settings exactly."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise ValueError("non-finite JSON number")


def _decode_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def _fixed_result(
    *,
    state: str,
    reason: str,
    failures: list[str] | None = None,
    blockers: list[str] | None = None,
    operation_id: str | None = None,
    execution_started: bool = False,
    replayed: bool = False,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": VALIDATION_SCHEMA,
        "state": state,
        "execution_started": execution_started,
        "simulation_cache_written": False,
        "render_started": False,
        "reason": reason,
        "failures": list(failures or []),
        "blockers": list(blockers or []),
    }
    if operation_id is not None:
        result["operation_id"] = operation_id
    if replayed:
        result["replayed"] = True
    if details:
        result["details"] = dict(details)
    return result


def _read_capture(capture_path: Path) -> tuple[bytes | None, Any, list[str]]:
    try:
        raw = capture_path.read_bytes()
    except (OSError, ValueError):
        return None, None, ["CAPTURE_READ_FAILED"]
    try:
        return raw, _decode_json(raw), []
    except (UnicodeError, ValueError, TypeError):
        return raw, None, ["CAPTURE_JSON_INVALID"]


def _read_review(review_path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if review_path is None:
        return dict(PINNED_REVIEW_SUMMARY), []
    try:
        review = _decode_json(review_path.read_bytes())
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}, ["REVIEW_SUMMARY_READ_FAILED"]
    if not isinstance(review, dict) or review != PINNED_REVIEW_SUMMARY:
        return {}, ["REVIEW_SUMMARY_MISMATCH"]
    return review, []


def _walk_templates(rows: Any, *, parent: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(rows, list):
        return [], ["TEMPLATE_LIST_INVALID"]
    flat: list[dict[str, Any]] = []
    failures: list[str] = []
    seen: set[tuple[str, ...]] = set()

    def visit(items: list[Any], expected_parent: tuple[str, ...]) -> None:
        for item in items:
            if not isinstance(item, dict) or not _TEMPLATE_KEYS.issuperset(item.keys()):
                failures.append("TEMPLATE_ROW_INVALID")
                continue
            path = item.get("template_path")
            name = item.get("name")
            label = item.get("label")
            template_type = item.get("type")
            components = item.get("components")
            if (
                not isinstance(path, list)
                or not path
                or any(not isinstance(part, str) or not part for part in path)
                or tuple(path[:-1]) != expected_parent
                or path[-1] != name
                or not isinstance(name, str)
                or not isinstance(label, str)
                or not isinstance(template_type, str)
                or type(components) is not int
                or components < 0
            ):
                failures.append("TEMPLATE_ROW_SHAPE_INVALID")
                continue
            path_tuple = tuple(path)
            if path_tuple in seen:
                failures.append("TEMPLATE_PATH_DUPLICATE")
            seen.add(path_tuple)
            if "folder_type" in item and not isinstance(item["folder_type"], str):
                failures.append("TEMPLATE_FOLDER_TYPE_INVALID")
            if "dynamic_menu" in item and type(item["dynamic_menu"]) is not bool:
                failures.append("TEMPLATE_DYNAMIC_MENU_INVALID")
            has_items = "menu_items" in item
            has_labels = "menu_labels" in item
            if has_items != has_labels:
                failures.append("TEMPLATE_MENU_PAIR_INVALID")
            if has_items:
                if (
                    not isinstance(item["menu_items"], list)
                    or not isinstance(item["menu_labels"], list)
                    or any(not isinstance(value, str) for value in item["menu_items"])
                    or any(not isinstance(value, str) for value in item["menu_labels"])
                    or len(item["menu_items"]) != len(item["menu_labels"])
                ):
                    failures.append("TEMPLATE_MENU_SHAPE_INVALID")
            if "children" in item:
                if not isinstance(item["children"], list):
                    failures.append("TEMPLATE_CHILDREN_INVALID")
                else:
                    visit(item["children"], path_tuple)
            flat.append(item)

    visit(rows, parent)
    return flat, failures


def _require_template(
    by_path: Mapping[tuple[str, ...], dict[str, Any]],
    path: tuple[str, ...],
    template_type: str,
    components: int = 1,
    folder_type: str | None = None,
) -> list[str]:
    item = by_path.get(path)
    if item is None:
        return ["REQUIRED_TEMPLATE_MISSING:" + "/".join(path)]
    failures: list[str] = []
    if item.get("type") != template_type or item.get("components") != components:
        failures.append("REQUIRED_TEMPLATE_TYPE_MISMATCH:" + "/".join(path))
    if folder_type is not None and item.get("folder_type") != folder_type:
        failures.append("REQUIRED_FOLDER_TYPE_MISMATCH:" + "/".join(path))
    return failures


def _check_static_menu(
    by_path: Mapping[tuple[str, ...], dict[str, Any]],
    path: tuple[str, ...],
    items: list[str],
    labels: list[str],
) -> list[str]:
    row = by_path.get(path)
    if row is None:
        return ["REQUIRED_MENU_MISSING:" + "/".join(path)]
    if row.get("dynamic_menu") is not False:
        return ["STATIC_MENU_DYNAMIC:" + "/".join(path)]
    if row.get("menu_items") != items or row.get("menu_labels") != labels:
        return ["STATIC_MENU_TOKEN_MISMATCH:" + "/".join(path)]
    return []


def _check_dynamic_string(
    by_path: Mapping[tuple[str, ...], dict[str, Any]],
    path: tuple[str, ...],
) -> list[str]:
    row = by_path.get(path)
    if row is None:
        return ["REQUIRED_DYNAMIC_STRING_MISSING:" + "/".join(path)]
    if row.get("type") != "parmTemplateType.String" or row.get("components") != 1:
        return ["REQUIRED_DYNAMIC_STRING_TYPE_MISMATCH:" + "/".join(path)]
    if row.get("dynamic_menu") is not True:
        return ["REQUIRED_DYNAMIC_STRING_NOT_DYNAMIC:" + "/".join(path)]
    if "menu_items" in row or "menu_labels" in row:
        return ["REQUIRED_DYNAMIC_STRING_EXPOSES_MENU:" + "/".join(path)]
    return []


def _validate_capture_structure(capture: Any) -> tuple[list[str], int | None]:
    if not isinstance(capture, dict):
        return ["CAPTURE_NOT_OBJECT"], None
    failures: list[str] = []
    if set(capture) != _CAPTURE_KEYS:
        failures.append("CAPTURE_TOP_LEVEL_SHAPE_INVALID")
    if capture.get("schema") != CAPTURE_SCHEMA:
        failures.append("CAPTURE_SCHEMA_MISMATCH")
    if capture.get("evidence_kind") != CAPTURE_EVIDENCE_KIND:
        failures.append("CAPTURE_EVIDENCE_KIND_MISMATCH")
    if capture.get("capture_state") != "CAPTURED_NOT_BOUND":
        failures.append("CAPTURE_STATE_INVALID")
    for key in (
        "solver_sourcing_implemented", "runtime_verified", "visual_verified",
        "route_verified", "provider_verified", "dcc_acceptance_unlocked",
    ):
        if capture.get(key) is not False:
            failures.append("CAPTURE_FLAG_INVALID:" + key)
    if capture.get("registered_bindings") != []:
        failures.append("CAPTURE_BINDINGS_NOT_EMPTY")
    for key in ("errors", "failure_details", "warnings"):
        value = capture.get(key)
        if not isinstance(value, list):
            failures.append("CAPTURE_LIST_INVALID:" + key)
        elif value:
            failures.append("CAPTURE_HAS_NONEMPTY:" + key)
    version = capture.get("houdini_version")
    if (
        not isinstance(version, list)
        or len(version) != 3
        or any(type(value) is not int for value in version)
        or version != EXPECTED_BUILD
    ):
        failures.append("CAPTURE_BUILD_MISMATCH")

    nodes = capture.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 2:
        return failures + ["CAPTURE_NODE_LIST_INVALID"], None
    first, second = nodes
    if not isinstance(first, dict) or set(first) != _NODE_KEYS:
        failures.append("CAPTURE_PRIMARY_NODE_SHAPE_INVALID")
    if not isinstance(second, dict) or set(second) != _UNAVAILABLE_NODE_KEYS:
        failures.append("CAPTURE_SECONDARY_NODE_SHAPE_INVALID")
    if isinstance(first, dict):
        if (
            first.get("requested_type") != "pyrosolver"
            or first.get("resolved_type") != "pyrosolver"
            or first.get("category") != "Sop"
            or first.get("available") is not True
            or first.get("min_inputs") != 1
            or first.get("max_inputs") != 2
        ):
            failures.append("CAPTURE_PRIMARY_NODE_CONTRACT_INVALID")
    if isinstance(second, dict):
        if second.get("requested_type") != "pyrosolver::2.0" or second.get("available") is not False:
            failures.append("CAPTURE_SECONDARY_NODE_CONTRACT_INVALID")

    templates = first.get("templates") if isinstance(first, dict) else None
    flat, template_failures = _walk_templates(templates)
    failures.extend(template_failures)
    if len(flat) != EXPECTED_TEMPLATE_COUNT:
        failures.append("CAPTURE_TEMPLATE_COUNT_MISMATCH")
    by_path = {tuple(row["template_path"]): row for row in flat if isinstance(row.get("template_path"), list)}

    required = [
        (("startframe",), "parmTemplateType.Int", 1, None),
        (("folder1",), "parmTemplateType.Folder", 1, "folderType.Tabs"),
        (("folder1", "folder26"), "parmTemplateType.Folder", 1, "folderType.Collapsible"),
        (("folder1", "folder26", "timescale"), "parmTemplateType.Float", 1, None),
        (("folder1_3",), "parmTemplateType.Folder", 1, "folderType.Tabs"),
        (("folder1_3", "folder28"), "parmTemplateType.Folder", 1, "folderType.Collapsible"),
        (("folder1_3", "folder4"), "parmTemplateType.Folder", 1, "folderType.Collapsible"),
        (("folder1_3", "folder4", "numsources"), "parmTemplateType.Folder", 1, "folderType.MultiparmBlock"),
        (("folder1_3", "folder4", "numsources", "source_activate#"), "parmTemplateType.Toggle", 1, None),
        (("folder1_3", "folder4", "numsources", "folder17_#"), "parmTemplateType.Folder", 1, "folderType.Collapsible"),
        (("folder1_3", "folder28", "srcrangetype"), "parmTemplateType.Menu", 1, None),
        (("folder1_3", "folder28", "srcframe"), "parmTemplateType.Int", 1, None),
        (("folder1_3", "folder28", "srcframerange"), "parmTemplateType.Int", 2, None),
        (("folder1_3", "folder28", "srcdocycle"), "parmTemplateType.Toggle", 1, None),
        (("folder1_3", "folder28", "srccyclelength"), "parmTemplateType.Int", 1, None),
    ]
    for path, template_type, components, folder_type in required:
        failures.extend(_require_template(by_path, path, template_type, components, folder_type))
    failures.extend(_check_static_menu(
        by_path, ("folder1_3", "folder28", "srcrangetype"), _STATIC_RANGE_ITEMS, _STATIC_RANGE_LABELS,
    ))

    row_prefix = ("folder1_3", "folder4", "numsources", "folder17_#")
    row_specs = [
        ("source_voperator#", "parmTemplateType.Menu", 1),
        ("source_rank#", "parmTemplateType.Menu", 1),
        ("source_vscale#", "parmTemplateType.Float", 1),
        ("source_vnormalize#", "parmTemplateType.Toggle", 1),
        ("source_usenorm#", "parmTemplateType.Toggle", 1),
        ("source_nonneg#", "parmTemplateType.Toggle", 1),
    ]
    for name, template_type, components in row_specs:
        failures.extend(_require_template(by_path, row_prefix + (name,), template_type, components))
    for name in ("source_volume#", "source_vfield#", "source_weightvolume#", "source_vweightfield#"):
        failures.extend(_check_dynamic_string(by_path, row_prefix + (name,)))
    failures.extend(_check_static_menu(by_path, row_prefix + ("source_voperator#",), _STATIC_OPERATION_ITEMS, _STATIC_OPERATION_LABELS))
    failures.extend(_check_static_menu(by_path, row_prefix + ("source_rank#",), _STATIC_RANK_ITEMS, _STATIC_RANK_LABELS))
    return failures, len(flat)


def _canonical_snapshot_sha256(capture: dict[str, Any]) -> str:
    payload = dict(capture)
    payload.pop("snapshot_sha256", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def plan(capture_path: Path, review_summary_path: Path | None = None) -> dict[str, Any]:
    """Strictly validate one reviewed capture without importing Houdini."""

    raw, capture, failures = _read_capture(capture_path)
    review, review_failures = _read_review(review_summary_path)
    failures.extend(review_failures)
    template_count: int | None = None
    canonical_digest: str | None = None
    file_digest: str | None = None
    if raw is not None:
        file_digest = hashlib.sha256(raw).hexdigest()
        if file_digest != EXPECTED_CAPTURE_FILE_SHA256:
            failures.append("CAPTURE_FILE_HASH_MISMATCH")
    if capture is not None:
        structure_failures, template_count = _validate_capture_structure(capture)
        failures.extend(structure_failures)
        if isinstance(capture, dict):
            try:
                canonical_digest = _canonical_snapshot_sha256(capture)
            except (TypeError, ValueError, OverflowError):
                failures.append("CAPTURE_CANONICALIZATION_FAILED")
            claimed = capture.get("snapshot_sha256")
            if not isinstance(claimed, str) or not _HEX64.fullmatch(claimed):
                failures.append("CAPTURE_SNAPSHOT_HASH_INVALID")
            elif canonical_digest is not None and claimed != canonical_digest:
                failures.append("CAPTURE_SELF_HASH_MISMATCH")
            if canonical_digest != EXPECTED_SNAPSHOT_SHA256:
                failures.append("CAPTURE_CANONICAL_HASH_MISMATCH")
            if capture.get("capture_state") != PINNED_REVIEW_SUMMARY["state"]:
                failures.append("REVIEW_CAPTURE_STATE_MISMATCH")
            if capture.get("houdini_version") != PINNED_REVIEW_SUMMARY["version"]:
                failures.append("REVIEW_CAPTURE_BUILD_MISMATCH")
            if capture.get("errors") != PINNED_REVIEW_SUMMARY["errors"]:
                failures.append("REVIEW_CAPTURE_ERRORS_MISMATCH")
            if capture.get("warnings") != PINNED_REVIEW_SUMMARY["warnings"]:
                failures.append("REVIEW_CAPTURE_WARNINGS_MISMATCH")
            if template_count != PINNED_REVIEW_SUMMARY["template_count"]:
                failures.append("REVIEW_TEMPLATE_COUNT_MISMATCH")
        else:
            failures.append("CAPTURE_NOT_VALIDATED")
    else:
        failures.append("CAPTURE_NOT_VALIDATED")

    # Keep output deterministic if a malformed input triggers the same check
    # through more than one path; no exception text or arbitrary path is ever
    # copied into the report.
    failures = list(dict.fromkeys(failures))
    result: dict[str, Any] = {
        "schema": VALIDATION_SCHEMA,
        "state": "PLAN_READY" if not failures else "INCOMPLETE",
        "mode": "PLAN_ONLY_DEFAULT",
        "review_summary_verified": not review_failures,
        "execution_started": False,
        "simulation_cache_written": False,
        "render_started": False,
        "failures": failures,
    }
    if isinstance(capture, dict):
        result.update({
            "capture_state": capture.get("capture_state"),
            "binding_contract": "bridge.pyro.solver-sourcing/21.0.631",
            "reviewed_capture_file_sha256": file_digest,
            "canonical_snapshot_sha256": canonical_digest,
            "reviewed_snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
            "template_count": template_count,
            "source_target_mapping": [
                {"source_volume": "density", "target_field": "density", "rank": "scalar", "operation": "add"},
                {"source_volume": "v", "target_field": "vel", "rank": "vector", "operation": "copy"},
            ],
            "checks_passed": [
                "capture JSON shape and strict duplicate-key decoding",
                "reviewed H21.0.631 node availability and input contract",
                "485 native template rows and required Sourcing hierarchy",
                "static source/rank/range menu tokens and dynamic-string flags",
                "canonical snapshot digest independently recomputed from JSON",
                "reviewed capture file digest compared with the control summary",
            ],
            "checks_not_executed": [
                "Houdini node creation and input-0 connection",
                "set/readback of solver multiparm rows and constant activation keys",
                "12-frame synthetic short segment",
                "simulation cache, VDB, render, visual smoke evidence",
            ],
            "authorization_required_for_execution": True,
        })
    return result


def _safe_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _read_authorization_bundle(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        bundle = _decode_json(path.read_bytes())
    except (OSError, UnicodeError, ValueError, TypeError):
        return None, ["AUTHORIZATION_BUNDLE_READ_FAILED"]
    if not isinstance(bundle, dict):
        return None, ["AUTHORIZATION_BUNDLE_NOT_OBJECT"]
    return bundle, []


def _validate_source_schedule(
    schedule: Any,
    frame_start: int,
    frame_end: int,
    step: int = 1,
) -> list[str]:
    """Validate the controller-owned, half-open source activation windows."""

    failures: list[str] = []
    if not isinstance(schedule, dict) or set(schedule) != _SCHEDULE_KEYS:
        return ["SOURCE_SCHEDULE_RECORD_INVALID"]
    if schedule.get("schema") != SHORT_SEGMENT_SCHEDULE_SCHEMA:
        failures.append("SOURCE_SCHEDULE_SCHEMA_INVALID")
    schedule_start = schedule.get("frame_start")
    schedule_end = schedule.get("frame_end")
    schedule_step = schedule.get("step")
    if type(schedule_start) is not int or type(schedule_end) is not int:
        failures.append("SOURCE_SCHEDULE_RANGE_INVALID")
    else:
        if schedule_start != frame_start or schedule_end != frame_end:
            failures.append("SOURCE_SCHEDULE_RANGE_MISMATCH")
        if schedule_start < 0 or schedule_end < schedule_start:
            failures.append("SOURCE_SCHEDULE_RANGE_INVALID")
    if type(schedule_step) is not int or schedule_step != step:
        failures.append("SOURCE_SCHEDULE_STEP_INVALID")

    rows = schedule.get("rows")
    if not isinstance(rows, dict) or set(rows) != {"1", "2"}:
        failures.append("SOURCE_SCHEDULE_ROWS_INVALID")
        return list(dict.fromkeys(failures))

    normalized: dict[str, list[dict[str, int]]] = {}
    bound_step = step if type(step) is int and step > 0 else 1
    for row_name in ("1", "2"):
        intervals = rows.get(row_name)
        if not isinstance(intervals, list) or not intervals:
            failures.append("SOURCE_SCHEDULE_EMPTY")
            continue
        parsed: list[dict[str, int]] = []
        previous_start: int | None = None
        previous_end: int | None = None
        for interval in intervals:
            if not isinstance(interval, dict) or set(interval) != _SCHEDULE_INTERVAL_KEYS:
                failures.append("SOURCE_SCHEDULE_INTERVAL_INVALID")
                continue
            start = interval.get("start")
            end = interval.get("end")
            if type(start) is not int or type(end) is not int:
                failures.append("SOURCE_SCHEDULE_SUBFRAME_BOUNDARY_UNSUPPORTED")
                continue
            if start < 0 or end <= start:
                failures.append("SOURCE_SCHEDULE_INTERVAL_RANGE_INVALID")
            if type(frame_start) is int and type(frame_end) is int:
                if start < frame_start or end > frame_end + bound_step:
                    failures.append("SOURCE_SCHEDULE_INTERVAL_OUTSIDE_SEGMENT")
            if previous_start is not None and start < previous_start:
                failures.append("SOURCE_SCHEDULE_INTERVALS_NOT_SORTED")
            if previous_end is not None and start < previous_end:
                failures.append("SOURCE_SCHEDULE_INTERVALS_OVERLAP")
            previous_start = start
            previous_end = end
            parsed.append({"start": start, "end": end})
        normalized[row_name] = parsed

    if normalized.get("1") and normalized.get("2") and normalized["1"] != normalized["2"]:
        failures.append("SOURCE_SCHEDULE_ROW_MISMATCH")
    return list(dict.fromkeys(failures))


def _expected_active_windows(schedule: Mapping[str, Any], frame: int) -> dict[int, bool]:
    rows = schedule.get("rows") if isinstance(schedule, Mapping) else None
    result: dict[int, bool] = {}
    if not isinstance(rows, Mapping):
        return result
    for row_name in ("1", "2"):
        intervals = rows.get(row_name, [])
        result[int(row_name)] = bool(
            isinstance(intervals, list)
            and any(
                isinstance(interval, Mapping)
                and type(interval.get("start")) is int
                and type(interval.get("end")) is int
                and int(interval["start"]) <= frame < int(interval["end"])
                for interval in intervals
            )
        )
    return result


def _schedule_intervals(schedule: Mapping[str, Any]) -> list[tuple[int, int]]:
    rows = schedule.get("rows") if isinstance(schedule, Mapping) else None
    intervals = rows.get("1", []) if isinstance(rows, Mapping) else []
    return [
        (int(interval["start"]), int(interval["end"]))
        for interval in intervals
        if isinstance(interval, Mapping)
        and type(interval.get("start")) is int
        and type(interval.get("end")) is int
    ]


def _schedule_phase(schedule: Mapping[str, Any], frame: int) -> str:
    """Derive an event phase from the durable schedule, never from position."""

    windows = _expected_active_windows(schedule, frame)
    intervals = _schedule_intervals(schedule)
    if any(windows.values()):
        return "active"
    if not intervals:
        return "inactive"
    first_start = min(start for start, _end in intervals)
    last_end = max(end for _start, end in intervals)
    if frame < first_start:
        return "before"
    if frame >= last_end:
        return "after"
    return "gap"


def _schedule_phase_coverage(schedule: Mapping[str, Any], frames: tuple[int, ...]) -> dict[str, Any]:
    phase_by_frame = [
        {"frame": int(frame), "phase": _schedule_phase(schedule, int(frame))}
        for frame in frames
    ]
    frames_by_phase: dict[str, list[int]] = {}
    for item in phase_by_frame:
        frames_by_phase.setdefault(item["phase"], []).append(item["frame"])
    required = ["before", "active", "after"]
    if len(_schedule_intervals(schedule)) > 1:
        required.insert(2, "gap")
    missing = [phase for phase in required if phase not in frames_by_phase]
    return {
        "phase_by_frame": phase_by_frame,
        "frames_by_phase": {phase: frames_by_phase[phase] for phase in ("before", "active", "gap", "after") if phase in frames_by_phase},
        "required_phases": required,
        "missing_phases": missing,
        "complete": not missing,
    }


def _validate_controller_issuance(bundle: Mapping[str, Any]) -> list[str]:
    """Validate that this bundle came from the controller contract.

    This is an integrity/relationship check, not a cryptographic identity
    service. The controller and the same Full Access user remain cooperative
    actors. It does prevent a copied static JSON or model-supplied flag from
    entering the S-06 validator.
    """

    failures: list[str] = []
    issuance = bundle.get("controller_issuance")
    if not isinstance(issuance, dict):
        return ["CONTROLLER_ISSUANCE_MISSING"]
    expected_keys = {
        "schema", "status", "issuer", "controller_id", "request_id",
        "authorization_hash", "controller_request_hash", "controller_request",
        "scene_preparation", "preparation_record_id", "first_graph_mutation",
    }
    issuance_keys = set(issuance)
    if issuance_keys not in (expected_keys, expected_keys | {"scene_ownership"}):
        failures.append("CONTROLLER_ISSUANCE_KEYS_INVALID")
    if issuance.get("schema") != CONTROLLER_ISSUANCE_SCHEMA:
        failures.append("CONTROLLER_ISSUANCE_SCHEMA_INVALID")
    if issuance.get("status") != "ISSUED" or issuance.get("issuer") != "trusted_s06_controller":
        failures.append("CONTROLLER_ISSUANCE_NOT_TRUSTED")
    if not _safe_identifier(issuance.get("controller_id")):
        failures.append("CONTROLLER_ID_INVALID")
    if issuance.get("request_id") != bundle.get("request_id"):
        failures.append("CONTROLLER_REQUEST_ID_MISMATCH")
    if issuance.get("preparation_record_id") != bundle.get("request_id"):
        failures.append("PREPARATION_RECORD_ID_MISMATCH")
    if issuance.get("first_graph_mutation") != "pending":
        failures.append("FIRST_GRAPH_MUTATION_ALREADY_STARTED")
    preparation = issuance.get("scene_preparation")
    if not isinstance(preparation, dict) or preparation.get("schema") != PREPARATION_SCHEMA:
        failures.append("SCENE_PREPARATION_RECORD_INVALID")
    else:
        if preparation.get("status") != "SAVED_HIP_VERIFIED":
            failures.append("SCENE_PREPARATION_NOT_VERIFIED")
        if preparation.get("first_graph_mutation") != "not_started":
            failures.append("SCENE_PREPARATION_MUTATION_PHASE_INVALID")
        if preparation.get("save_preparation_and_graph_mutation_are_separate") is not True:
            failures.append("SCENE_PREPARATION_PHASES_NOT_SEPARATE")
        saved = preparation.get("saved_hip")
        ownership = preparation.get("ownership")
        if not isinstance(saved, dict) or not isinstance(ownership, dict):
            failures.append("SCENE_PREPARATION_DETAILS_INVALID")
        else:
            if saved.get("has_unsaved_changes") is not False:
                failures.append("SCENE_PREPARATION_DIRTY")
            if ownership.get("owned_project") is not True or ownership.get("fresh_project") is not True:
                failures.append("SCENE_PREPARATION_OWNERSHIP_INVALID")
            if ownership.get("read_only_capture_session") is not False:
                failures.append("SCENE_PREPARATION_CAPTURE_SESSION_REUSED")
            if ownership.get("conflicting_nodes") != [] or ownership.get("task_manifest_ids") != []:
                failures.append("SCENE_PREPARATION_CONFLICT_PRESENT")
            if not isinstance(saved.get("path"), str) or not Path(saved["path"]).is_absolute():
                failures.append("SCENE_PREPARATION_HIP_PATH_INVALID")
            if not _HEX64.fullmatch(str(saved.get("sha256") or "")):
                failures.append("SCENE_PREPARATION_HIP_HASH_INVALID")
    ownership = bundle.get("scene_ownership")
    if "scene_ownership" in issuance:
        if not isinstance(ownership, dict) or issuance.get("scene_ownership") != ownership:
            failures.append("SCENE_OWNERSHIP_BUNDLE_MISMATCH")
        try:
            contracts = _load_s06_contracts()
            if not contracts.scene_ownership_record_valid(ownership):
                failures.append("SCENE_OWNERSHIP_RECORD_INVALID")
        except Exception:
            failures.append("SCENE_OWNERSHIP_RECORD_UNAVAILABLE")
    request = issuance.get("controller_request")
    if not isinstance(request, dict):
        failures.append("CONTROLLER_REQUEST_INVALID")
    else:
        expected_request_keys = {
            "schema", "adapter", "transport", "task_id", "operation_id",
            "request_id", "execution_root", "host_identity", "frame_segment",
            "source_schedule", "source_binding", "velocity_sentinel", "authorization_hash",
            "cache_allowed", "render_allowed", "first_graph_mutation",
        }
        request_keys = set(request)
        if request_keys not in (expected_request_keys, expected_request_keys | {"scene_ownership"}):
            failures.append("CONTROLLER_REQUEST_KEYS_INVALID")
        if request.get("schema") != CONTROLLER_REQUEST_SCHEMA:
            failures.append("CONTROLLER_REQUEST_SCHEMA_INVALID")
        if request.get("adapter") != ADAPTER_SCHEMA or request.get("transport") != "houdini_main_thread":
            failures.append("CONTROLLER_REQUEST_TRANSPORT_INVALID")
        if request.get("task_id") != bundle.get("task_id") or request.get("operation_id") != bundle.get("operation_id"):
            failures.append("CONTROLLER_REQUEST_OPERATION_MISMATCH")
        if request.get("request_id") != bundle.get("request_id"):
            failures.append("CONTROLLER_REQUEST_ID_MISMATCH")
        if request.get("execution_root") != (bundle.get("host_binding") or {}).get("root"):
            failures.append("CONTROLLER_REQUEST_ROOT_MISMATCH")
        if request.get("frame_segment") != bundle.get("frame_segment"):
            failures.append("CONTROLLER_REQUEST_FRAME_MISMATCH")
        if request.get("source_schedule") != bundle.get("source_schedule"):
            failures.append("CONTROLLER_REQUEST_SCHEDULE_MISMATCH")
        if request.get("source_binding") != bundle.get("source_binding"):
            failures.append("CONTROLLER_REQUEST_SOURCE_MISMATCH")
        if request.get("velocity_sentinel") != bundle.get("velocity_sentinel"):
            failures.append("CONTROLLER_REQUEST_VELOCITY_SENTINEL_MISMATCH")
        try:
            velocity = _load_s06_velocity()
            sentinel_failures = velocity.validate_snapshot(request.get("velocity_sentinel"))
            if sentinel_failures or request.get("velocity_sentinel") != velocity.default_controller_sentinel():
                failures.append("CONTROLLER_REQUEST_VELOCITY_SENTINEL_INVALID")
        except Exception:
            failures.append("CONTROLLER_REQUEST_VELOCITY_SENTINEL_UNAVAILABLE")
        if request.get("cache_allowed") is not False or request.get("render_allowed") is not False:
            failures.append("CONTROLLER_REQUEST_SCOPE_TOO_WIDE")
        if request.get("first_graph_mutation") != "pending":
            failures.append("CONTROLLER_REQUEST_MUTATION_PHASE_INVALID")
        if "scene_ownership" in request and request.get("scene_ownership") != ownership:
            failures.append("CONTROLLER_REQUEST_OWNERSHIP_MISMATCH")
        host = bundle.get("host_binding")
        request_identity = request.get("host_identity")
        if not isinstance(host, dict) or not isinstance(request_identity, dict):
            failures.append("CONTROLLER_REQUEST_HOST_IDENTITY_INVALID")
        else:
            for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS:
                if request_identity.get(key) != host.get(key):
                    failures.append("CONTROLLER_REQUEST_HOST_IDENTITY_MISMATCH")
                    break
        try:
            contracts = _load_s06_contracts()
            if issuance.get("authorization_hash") != contracts.authorization_hash(bundle):
                failures.append("CONTROLLER_AUTHORIZATION_HASH_MISMATCH")
            if request.get("authorization_hash") != issuance.get("authorization_hash"):
                failures.append("CONTROLLER_REQUEST_AUTHORIZATION_HASH_MISMATCH")
            if issuance.get("controller_request_hash") != contracts.controller_request_hash(request):
                failures.append("CONTROLLER_REQUEST_HASH_MISMATCH")
        except Exception:
            failures.append("CONTROLLER_CANONICAL_HASH_UNAVAILABLE")
    return list(dict.fromkeys(failures))


def _validate_authorization_bundle(
    bundle: Any,
    *,
    task_id: str,
    operation_id: str,
    frame_start: int,
    frame_end: int,
    now: float,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(bundle, dict):
        return ["AUTHORIZATION_BUNDLE_NOT_OBJECT"]
    if bundle.get("schema") != SHORT_SEGMENT_AUTHORIZATION_SCHEMA:
        failures.append("AUTHORIZATION_SCHEMA_INVALID")
    if bundle.get("task_id") != task_id or bundle.get("operation_id") != operation_id:
        failures.append("OPERATION_IDENTITY_MISMATCH")
    if not _safe_identifier(bundle.get("request_id")):
        failures.append("REQUEST_ID_INVALID")
    if not _safe_identifier(task_id) or not _safe_identifier(operation_id):
        failures.append("OPERATION_ID_INVALID")
    if bundle.get("scope") != SHORT_SEGMENT_SCOPE or bundle.get("authorized") is not True:
        failures.append("SHORT_SEGMENT_AUTHORIZATION_MISSING")

    operation = bundle.get("operation")
    if not isinstance(operation, dict):
        failures.append("OPERATION_RECORD_INVALID")
    else:
        if operation.get("task_id") != task_id or operation.get("operation_id") != operation_id:
            failures.append("OPERATION_RECORD_IDENTITY_MISMATCH")
        if operation.get("state") != "AUTHORIZED" or operation.get("unknown") is not False:
            failures.append("OPERATION_NOT_RETRYABLE")
        if type(operation.get("attempt_generation")) is not int or operation["attempt_generation"] < 1:
            failures.append("OPERATION_GENERATION_INVALID")

    lease = bundle.get("scene_lease")
    if not isinstance(lease, dict):
        failures.append("SCENE_LEASE_RECORD_INVALID")
    else:
        for key in ("task_id", "session_id", "process_generation", "scene_id", "root"):
            if not isinstance(lease.get(key), str) or not lease[key].strip():
                failures.append("SCENE_LEASE_IDENTITY_INVALID")
        root = lease.get("root")
        if not isinstance(root, str) or not re.fullmatch(r"/obj/BRIDGE_GRAPH_[0-9a-f]{64}", root):
            failures.append("SCENE_LEASE_ROOT_INVALID")
        if type(lease.get("generation")) is not int or lease["generation"] < 1:
            failures.append("SCENE_LEASE_GENERATION_INVALID")
        expires_at = lease.get("expires_at")
        if type(expires_at) not in (int, float) or not math.isfinite(float(expires_at)) or float(expires_at) <= now:
            failures.append("SCENE_LEASE_EXPIRED_OR_INVALID")
        if lease.get("task_id") != task_id:
            failures.append("SCENE_LEASE_TASK_MISMATCH")

    budget = bundle.get("heavy_budget")
    if not isinstance(budget, dict):
        failures.append("HEAVY_BUDGET_RECORD_INVALID")
    else:
        if budget.get("operation_id") != operation_id:
            failures.append("HEAVY_BUDGET_OPERATION_MISMATCH")
        if budget.get("slot") != 1 or budget.get("active") is not True:
            failures.append("HEAVY_SLOT_NOT_ACTIVE")
        if budget.get("phase") != "DISPATCHING":
            failures.append("HEAVY_SLOT_NOT_DISPATCHING")
        if not isinstance(budget.get("owner_root"), str) or not budget["owner_root"].strip():
            failures.append("HEAVY_SLOT_OWNER_INVALID")
        if isinstance(lease, dict) and budget.get("owner_root") == lease.get("root"):
            failures.append("HEAVY_SLOT_OWNER_COLLIDES_WITH_GRAPH_ROOT")
        token = budget.get("token")
        if not isinstance(token, str) or not _HEX64.fullmatch(token):
            failures.append("HEAVY_SLOT_TOKEN_INVALID")
        if type(budget.get("remaining_heavy_jobs")) is not int or budget["remaining_heavy_jobs"] < 1:
            failures.append("HEAVY_BUDGET_EXHAUSTED")
        if budget.get("cache_allowed") is not False or budget.get("render_allowed") is not False:
            failures.append("SHORT_SEGMENT_SCOPE_TOO_WIDE")
        if not isinstance(budget.get("scheduler_root"), str) or not budget["scheduler_root"].strip():
            failures.append("HEAVY_SCHEDULER_ROOT_INVALID")
        if type(budget.get("generation")) is not int or budget["generation"] < 1:
            failures.append("HEAVY_SLOT_GENERATION_INVALID")

    segment = bundle.get("frame_segment")
    if not isinstance(segment, dict) or set(segment) != _FRAME_KEYS:
        failures.append("FRAME_SEGMENT_RECORD_INVALID")
    else:
        if segment.get("start") != frame_start or segment.get("end") != frame_end:
            failures.append("FRAME_SEGMENT_ARGUMENT_MISMATCH")
        if segment.get("step") != 1:
            failures.append("FRAME_SEGMENT_STEP_INVALID")
        preroll = segment.get("preroll_frames")
        if type(preroll) is not int or preroll < 0 or preroll > SHORT_SEGMENT_MAX_FRAMES:
            failures.append("FRAME_PREROLL_INVALID")
        elapsed = segment.get("max_elapsed_seconds")
        cook_budget = segment.get("max_cook_seconds_per_frame")
        if type(elapsed) not in (int, float) or not math.isfinite(float(elapsed)) or not 0 < float(elapsed) <= SHORT_SEGMENT_MAX_ELAPSED_SECONDS:
            failures.append("FRAME_ELAPSED_BUDGET_INVALID")
        if type(cook_budget) not in (int, float) or not math.isfinite(float(cook_budget)) or not 0 < float(cook_budget) <= SHORT_SEGMENT_MAX_COOK_SECONDS:
            failures.append("FRAME_COOK_BUDGET_INVALID")
        if type(frame_start) is not int or type(frame_end) is not int or frame_start < 0 or frame_end < frame_start:
            failures.append("SHORT_SEGMENT_RANGE_INVALID")
        elif frame_start - int(preroll or 0) < 0:
            failures.append("FRAME_PREROLL_OUTSIDE_RANGE")
        else:
            total = frame_end - frame_start + 1 + int(preroll or 0)
            if total > SHORT_SEGMENT_MAX_FRAMES:
                failures.append("SHORT_SEGMENT_RANGE_INVALID")
            max_frames = budget.get("max_frames") if isinstance(budget, dict) else None
            if type(max_frames) is not int or max_frames < total or max_frames > SHORT_SEGMENT_MAX_FRAMES:
                failures.append("SHORT_SEGMENT_FRAME_BUDGET_INVALID")

    schedule_start = segment.get("start") if isinstance(segment, dict) else frame_start
    schedule_end = segment.get("end") if isinstance(segment, dict) else frame_end
    schedule_step = segment.get("step") if isinstance(segment, dict) else 1
    failures.extend(_validate_source_schedule(
        bundle.get("source_schedule"), schedule_start, schedule_end, schedule_step,
    ))

    source_binding = bundle.get("source_binding")
    if source_binding != {
        "capture_file_sha256": EXPECTED_CAPTURE_FILE_SHA256,
        "snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
        "capture_state": "CAPTURED_NOT_BOUND",
    }:
        failures.append("SOURCE_BINDING_INVALID")

    host_binding = bundle.get("host_binding")
    if not isinstance(host_binding, dict):
        failures.append("HOST_BINDING_INVALID")
    else:
        if host_binding.get("schema") != HOST_BINDING_SCHEMA:
            failures.append("HOST_BINDING_SCHEMA_INVALID")
        for key in (*SHORT_SEGMENT_HOST_IDENTITY_KEYS, "root"):
            if not isinstance(host_binding.get(key), str) or not host_binding[key].strip():
                failures.append("HOST_BINDING_IDENTITY_INVALID")
        if not re.fullmatch(r"/obj/BRIDGE_GRAPH_[0-9a-f]{64}", str(host_binding.get("root") or "")):
            failures.append("HOST_BINDING_ROOT_INVALID")
        if isinstance(lease, dict) and host_binding.get("root") != lease.get("root"):
            failures.append("HOST_BINDING_ROOT_MISMATCH")

    receipt = bundle.get("execution_receipt")
    expected_key = SHORT_SEGMENT_RECEIPT_PREFIX + operation_id
    if not isinstance(receipt, dict):
        failures.append("EXECUTION_RECEIPT_BINDING_INVALID")
    else:
        if receipt.get("schema") != SHORT_SEGMENT_RECEIPT_SCHEMA:
            failures.append("EXECUTION_RECEIPT_SCHEMA_INVALID")
        if receipt.get("idempotency_key") != expected_key:
            failures.append("EXECUTION_RECEIPT_KEY_INVALID")
        if receipt.get("record_category") != SHORT_SEGMENT_OPERATION_CATEGORY or receipt.get("record_id") != operation_id:
            failures.append("EXECUTION_RECEIPT_RECORD_INVALID")
        if not isinstance(receipt.get("store_path"), str) or not receipt["store_path"].strip():
            failures.append("EXECUTION_RECEIPT_STORE_INVALID")

    lease_store = bundle.get("lease_store")
    if not isinstance(lease_store, dict) or not isinstance(lease_store.get("path"), str) or not lease_store["path"].strip():
        failures.append("SCENE_LEASE_STORE_INVALID")
    failures.extend(_validate_controller_issuance(bundle))
    return list(dict.fromkeys(failures))


def _persisted_scene_lease(bundle: Mapping[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
    try:
        lease = bundle["scene_lease"]
        lease_store = bundle["lease_store"]
        raw_path = Path(str(lease_store["path"])).expanduser()
        if raw_path.is_symlink() or not raw_path.is_file():
            return None
        path = raw_path.resolve()
        with _readonly_database(path) as db:
            row = db.execute(
                "SELECT active,payload FROM scene_leases WHERE session_id=? AND scene_id=?",
                (lease["session_id"], lease["scene_id"]),
            ).fetchone()
        if row is None or int(row[0]) != 1:
            return None
        current = _decode_json(str(row[1]).encode("utf-8"))
        if not isinstance(current, dict) or current != lease:
            return None
        if now is not None and float(current.get("expires_at", 0.0)) <= float(now):
            return None
        return current
    except (OSError, sqlite3.Error, UnicodeError, ValueError, TypeError, KeyError):
        return None


def _verify_persisted_scene_lease(bundle: Mapping[str, Any]) -> bool:
    return _persisted_scene_lease(bundle, now=time.time()) is not None


def _persisted_heavy_slot(bundle: Mapping[str, Any]) -> dict[str, Any] | None:
    value = _read_persisted_heavy_slot(bundle)
    if value is None:
        return None
    budget = bundle["heavy_budget"]
    if (
        value["active"] != 1 or value["owner_root"] != budget["owner_root"]
        or value["operation_id"] != budget["operation_id"] or value["token"] != budget["token"]
        or value["phase"] != "DISPATCHING" or value["cancel_requested"] != 0
    ):
        return None
    return value


def _read_persisted_heavy_slot(bundle: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        budget = bundle["heavy_budget"]
        scheduler_root = Path(str(budget["scheduler_root"])).expanduser()
        if scheduler_root.is_symlink() or not scheduler_root.is_dir():
            return None
        scheduler_root = scheduler_root.resolve()
        path = scheduler_root / "graph_scheduler.sqlite3"
        if path.is_symlink() or not path.is_file():
            return None
        with _readonly_database(path) as db:
            row = db.execute(
                "SELECT active,owner_root,operation_id,token,phase,cancel_requested FROM heavy_slot WHERE slot=1",
            ).fetchone()
        if row is None:
            return None
        value = {
            "active": int(row[0]), "owner_root": row[1], "operation_id": row[2],
            "token": row[3], "phase": row[4], "cancel_requested": int(row[5]),
        }
        return value
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return None


def _verify_persisted_heavy_slot(bundle: Mapping[str, Any]) -> bool:
    return _persisted_heavy_slot(bundle) is not None


def _load_hou() -> Any:
    try:
        import hou  # type: ignore
    except ImportError:
        return None
    return hou


def _load_addon() -> Any:
    global _ADDON_MODULE
    if _ADDON_MODULE is not None:
        return _ADDON_MODULE
    path = _ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("_bridge_f2_short_segment_addon", path)
    if spec is None or spec.loader is None:
        raise ImportError("add-on unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ADDON_MODULE = module
    return _ADDON_MODULE


def _install_runtime_paths() -> None:
    for relative in (
        ("packages", "dcc-task-runtime", "src"),
        ("packages", "houdini-bridge", "src"),
        ("packages", "nuke-bridge", "src"),
        ("packages", "vfx-pipeline", "src"),
    ):
        rendered = str(_ROOT.joinpath(*relative))
        if rendered not in sys.path:
            sys.path.insert(0, rendered)


def _load_s06_contracts() -> Any:
    _install_runtime_paths()
    from vfx_pipeline import s06_contracts
    return s06_contracts


def _load_s06_velocity() -> Any:
    _install_runtime_paths()
    from vfx_pipeline import s06_velocity
    return s06_velocity


@contextmanager
def _readonly_database(path: Path):
    uri = "file:{}?mode=ro".format(path.as_posix())
    db = sqlite3.connect(uri, uri=True)
    try:
        yield db
    finally:
        db.close()


def _open_pipeline_store(bundle: Mapping[str, Any]) -> Any:
    """Open the already-created PipelineStore without creating a new ledger."""

    receipt = bundle["execution_receipt"]
    raw_path = Path(str(receipt["store_path"])).expanduser()
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError("durable execution store is unavailable")
    path = raw_path.resolve()
    with _readonly_database(path) as db:
        names = {
            str(row[0]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    required = {"pipeline_tasks", "pipeline_records", "skill_execution_claims"}
    if not required.issubset(names):
        raise ValueError("durable execution store schema is incomplete")
    _install_runtime_paths()
    from dcc_task_runtime.pipeline_store import PipelineStore
    return PipelineStore(path)


def _short_segment_intent(bundle: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    return _load_s06_contracts().intent_payload(bundle, params)


def _intent_hash(intent: Mapping[str, Any]) -> str:
    # Controller and validator must hash the same canonical intent.  The
    # capture decoder intentionally keeps its historical JSON formatting, but
    # S-06 operation identity uses the shared compact contract canonicalizer.
    return _load_s06_contracts().canonical_sha256(intent)


def _persisted_operation_record(
    store: Any,
    bundle: Mapping[str, Any],
    intent: Mapping[str, Any],
    request_hash: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    task_id = str(bundle["task_id"])
    operation_id = str(bundle["operation_id"])
    try:
        store.get_task(task_id)
    except (KeyError, OSError, sqlite3.Error, ValueError, TypeError):
        return None, ["DURABLE_TASK_MISSING"]
    try:
        rows = [
            row for row in store.records(task_id, SHORT_SEGMENT_OPERATION_CATEGORY)
            if isinstance(row, dict) and row.get("operation_id") == operation_id
        ]
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None, ["DURABLE_OPERATION_RECORD_READ_FAILED"]
    if len(rows) != 1:
        failures.append("DURABLE_OPERATION_RECORD_MISSING" if not rows else "DURABLE_OPERATION_RECORD_AMBIGUOUS")
        return None, failures
    record = rows[0]
    if (
        record.get("schema") != SHORT_SEGMENT_OPERATION_SCHEMA
        or record.get("task_id") != task_id
        or record.get("operation_id") != operation_id
        or record.get("scope") != SHORT_SEGMENT_SCOPE
        or record.get("status") != "AUTHORIZED"
        or record.get("unknown") is not False
        or record.get("attempt_generation") != bundle["operation"]["attempt_generation"]
    ):
        failures.append("DURABLE_OPERATION_NOT_AUTHORIZED")
    if record.get("intent_hash") != request_hash or record.get("intent") != dict(intent):
        failures.append("OPERATION_INTENT_MISMATCH")
    return record, failures


def _claim_receipt_is_current(store: Any, bundle: Mapping[str, Any], request_hash: str) -> bool:
    receipt = bundle["execution_receipt"]
    try:
        current = store.skill_execution_receipt(bundle["task_id"], receipt["idempotency_key"])
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return False
    return bool(current and current.get("status") == "RUNNING" and current.get("request_hash") == request_hash)


def _operation_record_is_current(store: Any, bundle: Mapping[str, Any], request_hash: str) -> bool:
    try:
        rows = [
            row for row in store.records(bundle["task_id"], SHORT_SEGMENT_OPERATION_CATEGORY)
            if isinstance(row, dict) and row.get("operation_id") == bundle["operation_id"]
        ]
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return False
    if len(rows) != 1:
        return False
    record = rows[0]
    return bool(
        record.get("schema") == SHORT_SEGMENT_OPERATION_SCHEMA
        and record.get("task_id") == bundle["task_id"]
        and record.get("operation_id") == bundle["operation_id"]
        and record.get("scope") == SHORT_SEGMENT_SCOPE
        and record.get("status") == "AUTHORIZED"
        and record.get("unknown") is False
        and record.get("attempt_generation") == bundle["operation"]["attempt_generation"]
        and record.get("intent_hash") == request_hash
    )


def _finalization_payload(bundle: Mapping[str, Any]) -> dict[str, Any]:
    budget = bundle["heavy_budget"]
    return {
        "schema": SHORT_SEGMENT_FINALIZATION_SCHEMA,
        "status": "RELEASED",
        "task_id": bundle["task_id"],
        "operation_id": bundle["operation_id"],
        "attempt_generation": bundle["operation"]["attempt_generation"],
        "slot": budget["slot"],
        "owner_root": budget["owner_root"],
        "token": budget["token"],
        "receipt_status": "COMPLETED",
    }


def _finalization_is_current(record: Mapping[str, Any], bundle: Mapping[str, Any]) -> bool:
    return record.get("finalization") == _finalization_payload(bundle)


def _finalization_record(store: Any, bundle: Mapping[str, Any], request_hash: str) -> dict[str, Any] | None:
    if not _operation_record_is_current(store, bundle, request_hash):
        return None
    try:
        rows = [
            row for row in store.records(bundle["task_id"], SHORT_SEGMENT_OPERATION_CATEGORY)
            if isinstance(row, dict) and row.get("operation_id") == bundle["operation_id"]
        ]
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return None
    return rows[0] if len(rows) == 1 else None


def _finalize_completed_operation(
    store: Any,
    bundle: Mapping[str, Any],
    request_hash: str,
) -> tuple[bool, str]:
    """Release only the exact completed operation token, then persist proof."""

    try:
        record = _finalization_record(store, bundle, request_hash)
        if record is None:
            return False, "OPERATION_FINALIZATION_RECORD_CHANGED"
        if _finalization_is_current(record, bundle):
            return True, "FINALIZATION_ALREADY_RECORDED"

        budget = bundle["heavy_budget"]
        raw_slot = _read_persisted_heavy_slot(bundle)
        if raw_slot is None:
            return False, "HEAVY_SLOT_FINALIZATION_STATE_UNAVAILABLE"
        exact_active = bool(
            raw_slot.get("active") == 1
            and raw_slot.get("owner_root") == budget["owner_root"]
            and raw_slot.get("operation_id") == budget["operation_id"]
            and raw_slot.get("token") == budget["token"]
            and raw_slot.get("phase") == "DISPATCHING"
        )
        exact_released = bool(
            raw_slot.get("active") == 0
            and raw_slot.get("owner_root") == budget["owner_root"]
            and raw_slot.get("operation_id") == budget["operation_id"]
            and raw_slot.get("token") == budget["token"]
            and raw_slot.get("phase") == "RELEASED"
        )
        if not exact_active and not exact_released:
            return False, "HEAVY_SLOT_FINALIZATION_NOT_OWNED"

        if exact_active:
            _install_runtime_paths()
            from vfx_pipeline.graph_scheduler import GraphScheduler

            scheduler = GraphScheduler(Path(str(budget["scheduler_root"])))
            released = scheduler.release(
                str(budget["owner_root"]), str(budget["operation_id"]), str(budget["token"]), stopped=True,
            )
            if not released:
                return False, "HEAVY_SLOT_FINALIZATION_NOT_OWNED"
            after = _read_persisted_heavy_slot(bundle)
            if not isinstance(after, dict) or not (
                after.get("active") == 0
                and after.get("owner_root") == budget["owner_root"]
                and after.get("operation_id") == budget["operation_id"]
                and after.get("token") == budget["token"]
                and after.get("phase") == "RELEASED"
            ):
                return False, "HEAVY_SLOT_FINALIZATION_STATE_UNCERTAIN"

        current = _finalization_record(store, bundle, request_hash)
        if current is None:
            return False, "OPERATION_FINALIZATION_RECORD_CHANGED"
        updated = dict(current)
        updated["finalization"] = _finalization_payload(bundle)
        store.put_record(
            bundle["task_id"], SHORT_SEGMENT_OPERATION_CATEGORY,
            bundle["operation_id"], updated,
        )
        return True, "FINALIZATION_RECORDED"
    except Exception:
        return False, "HEAVY_SLOT_FINALIZATION_UNCERTAIN"


class _ShortSegmentControlError(RuntimeError):
    def __init__(self, reason: str, blocker: str):
        super().__init__(reason)
        self.reason = reason
        self.blocker = blocker


@contextmanager
def _operation_fence_context(bundle: Mapping[str, Any]):
    """Use the existing scheduler and SceneLease transaction boundaries."""

    _install_runtime_paths()
    from vfx_pipeline.graph_scheduler import GraphScheduler
    from vfx_pipeline.scene_lease import SceneLease, SceneLeaseStore

    budget = bundle["heavy_budget"]
    lease = SceneLease(**dict(bundle["scene_lease"]))
    scheduler = GraphScheduler(Path(str(budget["scheduler_root"])))
    lease_store = SceneLeaseStore(Path(str(bundle["lease_store"]["path"])))
    with scheduler.operation(str(budget["owner_root"]), str(budget["operation_id"]), str(budget["token"])):
        with lease_store.operation(lease):
            yield


class _ShortSegmentFrameGuard:
    """A host-call seam that enforces the durable checks at every frame."""

    def __init__(self, bundle, store, request_hash, *, clock, fence_context, host_identity_checker):
        self.bundle = bundle
        self.store = store
        self.request_hash = request_hash
        self.clock = clock
        self.fence_context = fence_context
        self.host_identity_checker = host_identity_checker
        segment = bundle["frame_segment"]
        start = int(segment["start"]) - int(segment["preroll_frames"])
        end = int(segment["end"])
        self.expected_frames = tuple(range(start, end + 1, int(segment["step"])))
        self.started_at = float(clock())
        self.host_side_effect_started = False
        self.seen_frames: list[int] = []
        self.frame_trace: list[dict[str, Any]] = []

    def _check_persistent_state(self) -> None:
        if not _verify_persisted_scene_lease(self.bundle):
            raise _ShortSegmentControlError("SCENE_LEASE_NOT_CURRENT", "PERSISTED_SCENE_LEASE_NOT_MATCHING")
        slot = _persisted_heavy_slot(self.bundle)
        if slot is None:
            raw_slot = _read_persisted_heavy_slot(self.bundle)
            if isinstance(raw_slot, dict) and raw_slot.get("cancel_requested") == 1:
                raise _ShortSegmentControlError("SHORT_SEGMENT_CANCELLED", "HEAVY_SLOT_CANCEL_REQUESTED")
            raise _ShortSegmentControlError("HEAVY_SLOT_NOT_OWNED", "PERSISTED_HEAVY_SLOT_NOT_DISPATCHING")
        if not _operation_record_is_current(self.store, self.bundle, self.request_hash):
            raise _ShortSegmentControlError("OPERATION_AUTHORIZATION_CHANGED", "DURABLE_OPERATION_RECORD_CHANGED")
        if not _claim_receipt_is_current(self.store, self.bundle, self.request_hash):
            raise _ShortSegmentControlError("EXECUTION_RECEIPT_NOT_CURRENT", "DURABLE_CLAIM_CHANGED")
        if not self.host_identity_checker():
            raise _ShortSegmentControlError("HOST_IDENTITY_CHANGED", "LIVE_HOST_SESSION_SCENE_MISMATCH")

    def _check_elapsed(self) -> None:
        limit = float(self.bundle["frame_segment"]["max_elapsed_seconds"])
        if float(self.clock()) - self.started_at > limit:
            raise _ShortSegmentControlError("SHORT_SEGMENT_TIME_BUDGET_EXCEEDED", "ELAPSED_BUDGET_EXCEEDED")

    def _check(self) -> None:
        self._check_elapsed()
        self._check_persistent_state()

    def run_host_call(self, callback: Callable[[], Any]) -> Any:
        self._check()
        with self.fence_context(self.bundle):
            self._check()
            self.host_side_effect_started = True
            value = callback()
            self._check()
            return value

    def run_frame(self, frame: int, callback: Callable[[], Any]) -> Any:
        if frame not in self.expected_frames:
            raise _ShortSegmentControlError("FRAME_OUTSIDE_AUTHORIZED_WINDOW", "FRAME_NOT_AUTHORIZED")
        if self.seen_frames and frame <= self.seen_frames[-1]:
            raise _ShortSegmentControlError("FRAME_SEQUENCE_INVALID", "FRAME_SEQUENCE_NOT_MONOTONIC")
        self._check()
        frame_started = float(self.clock())
        with self.fence_context(self.bundle):
            self._check()
            self.host_side_effect_started = True
            value = callback()
            elapsed = float(self.clock()) - frame_started
            if elapsed > float(self.bundle["frame_segment"]["max_cook_seconds_per_frame"]):
                raise _ShortSegmentControlError("FRAME_COOK_TIME_BUDGET_EXCEEDED", "FRAME_COOK_BUDGET_EXCEEDED")
            self._check()
        if not isinstance(value, dict):
            raise ValueError("frame observation is not structured")
        self.seen_frames.append(frame)
        self.frame_trace.append(dict(value))
        return value


def _read_host_identity(hou_module: Any) -> dict[str, str] | None:
    for name in ("bridge_scene_identity", "scene_identity", "graph_worker_identity"):
        getter = getattr(hou_module, name, None)
        if not callable(getter):
            continue
        try:
            value = getter()
        except Exception:
            return None
        if not isinstance(value, Mapping):
            return None
        result = {key: value.get(key) for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS}
        if all(isinstance(item, str) and item.strip() for item in result.values()):
            return result
        return None
    try:
        addon = _load_addon()
        getter = getattr(addon, "bridge_scene_identity", None)
        value = getter() if callable(getter) else None
        if isinstance(value, Mapping):
            result = {key: value.get(key) for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS}
            if all(isinstance(item, str) and item.strip() for item in result.values()):
                return result
    except Exception:
        pass
    return None


def _host_params(params: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(params)
    host_binding = bundle["host_binding"]
    result["bridge_graph_root"] = host_binding["root"]
    result["bridge_execution_binding"] = {
        "schema": HOST_BINDING_SCHEMA,
        "task_id": bundle["task_id"], "operation_id": bundle["operation_id"],
        "host_identity": {key: host_binding[key] for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS},
        "execution_root": host_binding["root"],
    }
    result["s06_controller_request"] = dict(
        (bundle.get("controller_issuance") or {}).get("controller_request") or {}
    )
    try:
        result["s06_controller_request_hash"] = _load_s06_contracts().controller_request_hash(
            result["s06_controller_request"]
        )
    except Exception:
        result["s06_controller_request_hash"] = None
    result["f2_short_segment"] = {
        "schema": SHORT_SEGMENT_INTENT_SCHEMA,
        "frame_segment": dict(bundle["frame_segment"]),
        "source_binding": dict(bundle["source_binding"]),
        "source_schedule": dict(bundle["source_schedule"]),
        "cache_allowed": False,
        "render_allowed": False,
    }
    return result


def _run_houdini_short_segment(
    hou_module: Any,
    params: dict[str, Any],
    frame_start: int,
    frame_end: int,
    bundle: Mapping[str, Any],
    frame_guard: _ShortSegmentFrameGuard,
) -> dict[str, Any]:
    """Run one explicitly authorized, non-cache, non-render host segment."""

    build_getter = getattr(hou_module, "applicationVersionString", None)
    if not callable(build_getter) or str(build_getter()) != "21.0.631":
        return _fixed_result(state="BLOCKED", reason="HOST_BUILD_UNSUPPORTED", blockers=["HOST_BUILD_NOT_21_0_631"])
    set_frame = getattr(hou_module, "setFrame", None)
    frame_getter = getattr(hou_module, "frame", None)
    node_getter = getattr(hou_module, "node", None)
    if not callable(set_frame) or not callable(frame_getter):
        return _fixed_result(state="BLOCKED", reason="HOST_FRAME_CONTROL_UNAVAILABLE", blockers=["SETFRAME_READBACK_UNAVAILABLE"])
    if not isinstance(params, dict):
        return _fixed_result(state="BLOCKED", reason="TASK_PARAMS_INVALID", blockers=["TASK_PARAMS_NOT_OBJECT"])
    addon = _load_addon()
    adapter = getattr(hou_module, "bridge_s06_short_segment_adapter", None)
    if not callable(adapter):
        adapter = getattr(addon, "bridge_s06_short_segment_adapter", None)
    if not callable(node_getter) or not callable(adapter):
        return _fixed_result(state="BLOCKED", reason="HOST_OUTPUT_PROBE_UNAVAILABLE", blockers=["S06_MAIN_THREAD_ADAPTER_UNAVAILABLE"])
    scoped_params = _host_params(params, bundle)
    result = frame_guard.run_host_call(
        lambda: adapter({**scoped_params, "s06_action": "build"})
    )
    manifest = result.get("scene_manifest") if isinstance(result, dict) else None
    nodes = manifest.get("nodes") if isinstance(manifest, dict) else None
    solver_path = nodes.get("solver") if isinstance(nodes, dict) else None
    root = str(bundle["host_binding"]["root"])
    if (
        not isinstance(manifest, dict)
        or manifest.get("task_id") != bundle["task_id"]
        or manifest.get("execution_root") != root
        or not isinstance(solver_path, str)
        or not (solver_path == root or solver_path.startswith(root + "/"))
    ):
        raise ValueError("host returned a solver outside the authorized graph root")
    solver = node_getter(solver_path)
    if solver is None:
        return _fixed_result(state="BLOCKED", reason="HOST_SOLVER_UNAVAILABLE", blockers=["TASK_OWNED_SOLVER_NOT_READABLE"])

    expected_frames = frame_guard.expected_frames
    for frame in expected_frames:
        def observe_frame(frame=frame):
            observation = adapter({
                **scoped_params,
                "s06_action": "observe",
                "frame": frame,
                "solver_path": solver_path,
                "source_path": str(nodes.get("source_volume") or nodes.get("source") or ""),
            })
            if not isinstance(observation, dict):
                raise ValueError("host output probe returned no object")
            actual = observation.get("actual_frame")
            if not isinstance(actual, int) or actual != frame:
                raise ValueError("host frame readback differs from requested frame")
            return {**observation, "phase": _schedule_phase(bundle["source_schedule"], frame)}
        frame_guard.run_frame(frame, observe_frame)
    return {
        "schema": VALIDATION_SCHEMA,
        "state": "EXECUTED_HOST_SHORT_SEGMENT",
        "execution_started": True,
        "frames_checked": len(frame_guard.frame_trace),
        "frame_trace": list(frame_guard.frame_trace),
        "host_identity": dict(bundle["host_binding"]),
        "execution_root": root,
        "simulation_cache_written": False,
        "render_started": False,
    }


def _scheduler_operation_context(bundle: Mapping[str, Any]):
    """Compatibility name retained; this is now the combined real fence."""

    return _operation_fence_context(bundle)


def _sanitize_observation(observation: Mapping[str, Any], phase: str) -> dict[str, Any]:
    velocity_evidence = observation.get("velocity_preservation")
    if not isinstance(velocity_evidence, Mapping):
        raise ValueError("structured velocity preservation evidence is required")
    safe_velocity = {
        str(key): value
        for key, value in velocity_evidence.items()
        if str(key) in {
            "schema", "frame", "applicability", "status", "reason", "tolerance",
            "comparison_method", "before_digest", "after_digest", "sample_count",
            "component_order", "coordinate_space", "units", "mismatches",
            "mismatched_fields",
            "before_aggregate", "after_aggregate", "before_failures", "after_failures",
            "sourcing_boundary", "sourcing_boundary_failures",
        }
    }
    field_readback = observation.get("velocity_field_readback")
    if not isinstance(field_readback, Mapping):
        raise ValueError("structured velocity field readback is required")
    return {
        "actual_frame": int(observation["actual_frame"]),
        "phase": phase,
        "solver_path": str(observation["solver_path"]),
        "execution_root": str(observation["execution_root"]),
        "source_fields": [str(value) for value in observation["source_fields"]],
        "target_fields": [str(value) for value in observation["target_fields"]],
        "active_source_windows": [
            {
                "row": int(item["row"]), "active": bool(item["active"]),
                "source_volume": str(item["source_volume"]), "target_field": str(item["target_field"]),
            }
            for item in observation["active_source_windows"]
        ],
        "velocity_preservation": safe_velocity,
        "velocity_field_readback": dict(field_readback),
        "output_nonempty": bool(observation["output_nonempty"]),
        "cook_succeeded": bool(observation["cook_succeeded"]),
        "cook_errors": [str(value) for value in observation.get("cook_errors", [])],
    }


def _validate_observation(
    observation: Any,
    expected_frame: int,
    root: str,
    solver_path: str,
    schedule: Mapping[str, Any],
    velocity_sentinel: Mapping[str, Any],
) -> list[str]:
    if not isinstance(observation, dict):
        return ["FRAME_OBSERVATION_INVALID"]
    failures: list[str] = []
    if type(observation.get("actual_frame")) is not int or observation.get("actual_frame") != expected_frame:
        failures.append("FRAME_READBACK_MISMATCH")
    if observation.get("solver_path") != solver_path or observation.get("execution_root") != root:
        failures.append("FRAME_SCENE_BINDING_MISMATCH")
    for key in ("source_fields", "target_fields", "active_source_windows", "cook_errors"):
        if not isinstance(observation.get(key), list):
            failures.append("FRAME_OBSERVATION_LIST_INVALID:" + key)
    if not all(isinstance(value, str) for value in observation.get("source_fields", [])):
        failures.append("FRAME_SOURCE_FIELDS_INVALID")
    if not all(isinstance(value, str) for value in observation.get("target_fields", [])):
        failures.append("FRAME_TARGET_FIELDS_INVALID")
    if "density" not in observation.get("source_fields", []) or "v" not in observation.get("source_fields", []):
        failures.append("FRAME_SOURCE_FIELDS_MISSING")
    if "density" not in observation.get("target_fields", []) or "vel" not in observation.get("target_fields", []):
        failures.append("FRAME_TARGET_FIELDS_MISSING")
    field_readback = observation.get("velocity_field_readback")
    if not isinstance(field_readback, Mapping):
        failures.append("FRAME_VELOCITY_FIELD_READBACK_INVALID")
    expected_active = _expected_active_windows(schedule, expected_frame)
    windows = observation.get("active_source_windows")
    if not isinstance(windows, list) or len(windows) != 2:
        failures.append("FRAME_SOURCE_WINDOWS_INVALID")
    else:
        expected_bindings = {
            1: ("density", "density"),
            2: ("v", "vel"),
        }
        actual_rows: dict[int, dict[str, Any]] = {}
        for item in windows:
            if (
                not isinstance(item, dict)
                or type(item.get("row")) is not int
                or type(item.get("active")) is not bool
                or not isinstance(item.get("source_volume"), str)
                or not isinstance(item.get("target_field"), str)
            ):
                failures.append("FRAME_SOURCE_WINDOW_ROW_INVALID")
                continue
            row = int(item["row"])
            if row in actual_rows:
                failures.append("FRAME_SOURCE_WINDOW_ROW_DUPLICATE")
            actual_rows[row] = item
        if set(actual_rows) != set(expected_bindings):
            failures.append("FRAME_SOURCE_WINDOW_BINDING_INVALID")
        for row, (source_volume, target_field) in expected_bindings.items():
            item = actual_rows.get(row)
            if item is None:
                continue
            if (item["source_volume"], item["target_field"]) != (source_volume, target_field):
                failures.append("FRAME_SOURCE_WINDOW_BINDING_INVALID")
            if item["active"] != expected_active.get(row, False):
                failures.append("FRAME_ACTIVE_WINDOW_MISMATCH:" + str(row))
    for key in ("output_nonempty", "cook_succeeded"):
        if type(observation.get(key)) is not bool:
            failures.append("FRAME_OBSERVATION_BOOL_INVALID:" + key)
    if observation.get("cook_succeeded") is False and not observation.get("cook_errors"):
        failures.append("FRAME_COOK_FAILURE_UNSTRUCTURED")
    row2_active = expected_active.get(2, False)
    try:
        velocity = _load_s06_velocity()
        velocity_evidence = observation.get("velocity_preservation")
        velocity_failures = velocity.validate_evidence_record(velocity_evidence, row2_active=row2_active)
        if isinstance(field_readback, Mapping):
            if field_readback.get("field") != "vel":
                velocity_failures.append("VELOCITY_READBACK_FIELD_INVALID")
            before_snapshot = field_readback.get("before_snapshot")
            after_snapshot = field_readback.get("after_snapshot")
            if isinstance(after_snapshot, Mapping):
                after_failures = velocity.validate_snapshot(after_snapshot)
                if after_failures:
                    velocity_failures.append("VELOCITY_AFTER_SNAPSHOT_INVALID")
            if row2_active:
                if before_snapshot is not None:
                    velocity_failures.append("ACTIVE_VELOCITY_BEFORE_SNAPSHOT_MUST_BE_ABSENT")
            else:
                before_failures = velocity.validate_snapshot(before_snapshot)
                after_failures = velocity.validate_snapshot(after_snapshot)
                if before_failures:
                    velocity_failures.append("VELOCITY_BEFORE_SNAPSHOT_INVALID")
                if after_failures:
                    velocity_failures.append("VELOCITY_AFTER_SNAPSHOT_INVALID")
                sourcing_boundary = field_readback.get("sourcing_boundary")
                boundary_failures = velocity.validate_sourcing_boundary(sourcing_boundary, frame=expected_frame)
                if boundary_failures:
                    velocity_failures.append("VELOCITY_SOURCING_BOUNDARY_INVALID")
                sentinel = field_readback.get("sentinel")
                inventory = field_readback.get("writer_inventory")
                if not isinstance(sentinel, Mapping) or not isinstance(inventory, Mapping):
                    velocity_failures.append("VELOCITY_SCOPE_EVIDENCE_MISSING")
                sentinel_readback = sentinel.get("readback") if isinstance(sentinel, Mapping) else None
                sentinel_failures = velocity.validate_snapshot(sentinel_readback)
                if (
                    sentinel_failures
                    or not isinstance(sentinel, Mapping)
                    or sentinel.get("status") != "pass"
                    or sentinel.get("readback_verified") is not True
                    or not isinstance(velocity_sentinel, Mapping)
                    or sentinel_readback.get("digest_sha256") != velocity_sentinel.get("digest_sha256")
                ):
                    velocity_failures.append("VELOCITY_SENTINEL_READBACK_INVALID")
                if not before_failures and not after_failures and not boundary_failures:
                    recomputed = velocity.compare_inactive_velocity(
                        before_snapshot,
                        after_snapshot,
                        frame=expected_frame,
                        before_frame=sourcing_boundary["before"].get("frame") if isinstance(sourcing_boundary, Mapping) else None,
                        after_frame=sourcing_boundary["after"].get("frame") if isinstance(sourcing_boundary, Mapping) else None,
                        row2_active_before=False,
                        row2_active_after=False,
                        source_effect_isolated=(
                            isinstance(sentinel, Mapping)
                            and sentinel.get("status") == "pass"
                            and sentinel.get("readback_verified") is True
                            and not sentinel_failures
                            and isinstance(velocity_sentinel, Mapping)
                            and sentinel_readback.get("digest_sha256") == velocity_sentinel.get("digest_sha256")
                        ) if isinstance(sentinel_readback, Mapping) else False,
                        no_other_velocity_writers=isinstance(inventory, Mapping) and inventory.get("status") == "pass",
                        sourcing_boundary=sourcing_boundary,
                    )
                    if not isinstance(velocity_evidence, Mapping) or velocity_evidence.get("status") != recomputed.get("status") or velocity_evidence.get("reason") != recomputed.get("reason"):
                        velocity_failures.append("VELOCITY_EVIDENCE_NOT_DERIVED_FROM_READBACK")
    except Exception:
        velocity_failures = ["VELOCITY_EVIDENCE_VALIDATION_FAILED"]
    failures.extend(velocity_failures)
    return list(dict.fromkeys(failures))


def _validated_host_result(result: Any, guard: _ShortSegmentFrameGuard, bundle: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("host result is not an object")
    if result.get("simulation_cache_written") is True or result.get("render_started") is True:
        raise ValueError("short segment attempted forbidden cache/render output")
    if result.get("execution_started") is not True:
        raise ValueError("host result did not attest execution start")
    if tuple(guard.seen_frames) != guard.expected_frames or len(guard.frame_trace) != len(guard.expected_frames):
        raise ValueError("host did not use the durable per-frame guard for every authorized frame")
    root = str(bundle["host_binding"]["root"])
    solver_paths = {str(item.get("solver_path")) for item in guard.frame_trace if isinstance(item, dict)}
    if len(solver_paths) != 1:
        raise ValueError("frame observations do not bind one solver")
    solver_path = next(iter(solver_paths))
    schedule = bundle["source_schedule"]
    failures: list[str] = []
    clean_trace: list[dict[str, Any]] = []
    for expected_frame, observation in zip(guard.expected_frames, guard.frame_trace):
        failures.extend(_validate_observation(
            observation,
            expected_frame,
            root,
            solver_path,
            schedule,
            bundle["velocity_sentinel"],
        ))
        if isinstance(observation, dict):
            try:
                clean_trace.append(_sanitize_observation(
                    observation, _schedule_phase(schedule, expected_frame),
                ))
            except (KeyError, TypeError, ValueError):
                failures.append("FRAME_OBSERVATION_SANITIZE_FAILED")
    if failures:
        raise ValueError(";".join(sorted(set(failures))))
    scene_manifest = result.get("scene_manifest")
    safe_manifest: dict[str, Any] | None = None
    if scene_manifest is not None:
        if not isinstance(scene_manifest, Mapping):
            raise ValueError("host scene manifest is not an object")
        manifest_nodes = scene_manifest.get("nodes")
        if (
            scene_manifest.get("task_id") != bundle["task_id"]
            or scene_manifest.get("execution_root") != root
            or scene_manifest.get("domain_pack") != "pyro_smoke_v1"
            or not isinstance(manifest_nodes, Mapping)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in manifest_nodes.items())
        ):
            raise ValueError("host scene manifest is not bound to the authorized graph")
        safe_manifest = {
            "task_id": bundle["task_id"],
            "execution_root": root,
            "domain_pack": "pyro_smoke_v1",
            "nodes": {str(key): str(value) for key, value in manifest_nodes.items()},
        }
        for path in safe_manifest["nodes"].values():
            if not (path == root or path.startswith(root + "/")):
                raise ValueError("host scene manifest contains a node outside the authorized graph")
    coverage = _schedule_phase_coverage(schedule, tuple(guard.expected_frames))
    cook_errors = [item for item in clean_trace if not item["cook_succeeded"] or item["cook_errors"]]
    empty_output = [item["actual_frame"] for item in clean_trace if not item["output_nonempty"]]
    inactive_evidence = [
        item["velocity_preservation"]
        for item in clean_trace
        if item["velocity_preservation"].get("applicability") == "applicable"
    ]
    velocity_failed = [
        item["actual_frame"]
        for item in clean_trace
        if item["velocity_preservation"].get("status") == "fail"
    ]
    velocity_unknown = [
        item["actual_frame"]
        for item in clean_trace
        if item["velocity_preservation"].get("status") == "unknown"
    ]
    velocity_not_checked = not inactive_evidence
    velocity_unverified = velocity_failed + velocity_unknown
    state = (
        "HOST_OUTPUT_INCONCLUSIVE"
        if cook_errors or empty_output or velocity_unverified or velocity_not_checked or not coverage["complete"]
        else "EXECUTED_HOST_SHORT_SEGMENT"
    )
    if cook_errors:
        reason = "HOST_COOK_ERROR"
    elif empty_output:
        reason = "HOST_OUTPUT_EMPTY"
    elif velocity_failed:
        reason = "HOST_VELOCITY_PRESERVATION_FAILED"
    elif velocity_not_checked:
        reason = "HOST_VELOCITY_PRESERVATION_NOT_CHECKED"
    elif velocity_unverified:
        reason = "HOST_VELOCITY_PRESERVATION_UNVERIFIED"
    elif not coverage["complete"]:
        reason = "SOURCE_SCHEDULE_COVERAGE_INCOMPLETE"
    else:
        reason = "SHORT_SEGMENT_VERIFIED_TECHNICALLY"
    output = {
        "schema": VALIDATION_SCHEMA,
        "state": state,
        "reason": reason,
        "execution_started": True,
        "operation_id": operation_id,
        "frames_checked": len(clean_trace),
        "frame_segment": dict(bundle["frame_segment"]),
        "frame_trace": clean_trace,
        "host_identity": dict(bundle["host_binding"]),
        "execution_root": root,
        "output_verification": {
            "phase_authority": "durable_source_schedule",
            "event_phase_coverage": coverage,
            "source_schedule_verified": True,
            "active_windows_verified": True,
            "before_active_after": all(phase in coverage["frames_by_phase"] for phase in ("before", "active", "after")),
            "missing_event_phases": list(coverage["missing_phases"]),
            "source_fields_verified": True,
            "target_fields_verified": True,
            "inactive_velocity_preserved_verified": bool(inactive_evidence) and not velocity_unverified,
            "inactive_velocity_evidence_statuses": [
                {
                    "frame": item["actual_frame"],
                    "applicability": item["velocity_preservation"].get("applicability"),
                    "status": item["velocity_preservation"].get("status"),
                    "reason": item["velocity_preservation"].get("reason"),
                }
                for item in clean_trace
            ],
            "inactive_velocity_unverified_frames": velocity_unverified,
            "empty_output_frames": empty_output,
            "cook_error_frames": [item["actual_frame"] for item in cook_errors],
        },
        "simulation_cache_written": False,
        "render_started": False,
        "visual_verified": False,
        "smoke_capability_proven": False,
    }
    if safe_manifest is not None:
        output["scene_manifest"] = safe_manifest
    return output


def execute_short_segment(
    capture_path: Path,
    authorization_path: Path,
    *,
    task_id: str,
    operation_id: str,
    frame_start: int,
    frame_end: int,
    params: dict[str, Any] | None = None,
    hou_module: Any = None,
    executor: Callable[[Any, dict[str, Any], int, int, dict[str, Any]], dict[str, Any]] | None = None,
    lease_checker: Callable[[Mapping[str, Any]], bool] | None = None,
    budget_checker: Callable[[Mapping[str, Any]], bool] | None = None,
    fence_context: Callable[[Mapping[str, Any]], Any] | None = None,
    receipt_commit_hook: Callable[[], Any] | None = None,
    finalization_hook: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Execute one durable, non-repeatable, technically observed host segment."""

    planned = plan(capture_path)
    if planned.get("state") != "PLAN_READY":
        return _fixed_result(state="BLOCKED", reason="CAPTURE_PLAN_NOT_READY", failures=list(planned.get("failures") or []))
    bundle, read_failures = _read_authorization_bundle(authorization_path)
    if read_failures:
        return _fixed_result(state="BLOCKED", reason="AUTHORIZATION_NOT_READY", failures=read_failures)
    auth_failures = _validate_authorization_bundle(
        bundle,
        task_id=task_id,
        operation_id=operation_id,
        frame_start=frame_start,
        frame_end=frame_end,
        now=float(clock()),
    )
    if auth_failures:
        return _fixed_result(state="BLOCKED", reason="AUTHORIZATION_NOT_READY", failures=auth_failures)
    assert isinstance(bundle, dict)
    if lease_checker is not None or budget_checker is not None or fence_context is not None:
        return _fixed_result(
            state="BLOCKED", reason="UNTRUSTED_EXECUTION_HOOK", operation_id=operation_id,
            blockers=["EXECUTION_HOOK_OVERRIDE_FORBIDDEN"],
        )
    if not isinstance(params, dict) or params.get("task_id") != task_id:
        return _fixed_result(state="BLOCKED", reason="TASK_PARAMS_INVALID", blockers=["TASK_IDENTITY_MISMATCH"])
    host = hou_module if hou_module is not None else _load_hou()
    if host is None:
        return _fixed_result(state="BLOCKED", reason="HOU_UNAVAILABLE", blockers=["HOU_HOST_UNAVAILABLE"])
    build_getter = getattr(host, "applicationVersionString", None)
    if not callable(build_getter) or str(build_getter()) != "21.0.631":
        return _fixed_result(state="BLOCKED", reason="HOST_BUILD_UNSUPPORTED", blockers=["HOST_BUILD_NOT_21_0_631"])
    host_identity = _read_host_identity(host)
    expected_identity = bundle.get("host_binding")
    if host_identity is None:
        return _fixed_result(state="BLOCKED", reason="HOST_IDENTITY_UNAVAILABLE", operation_id=operation_id, blockers=["LIVE_HOST_IDENTITY_UNAVAILABLE"])
    if not isinstance(expected_identity, dict) or any(host_identity.get(key) != expected_identity.get(key) for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS):
        return _fixed_result(state="BLOCKED", reason="HOST_IDENTITY_MISMATCH", operation_id=operation_id, blockers=["LIVE_HOST_SESSION_SCENE_MISMATCH"])
    try:
        intent = _short_segment_intent(bundle, params)
        request_hash = _intent_hash(intent)
        store = _open_pipeline_store(bundle)
        _record, record_failures = _persisted_operation_record(store, bundle, intent, request_hash)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, ImportError):
        return _fixed_result(state="BLOCKED", reason="DURABLE_EXECUTION_STORE_UNAVAILABLE", operation_id=operation_id, blockers=["PIPELINE_STORE_UNAVAILABLE"])
    if record_failures:
        return _fixed_result(state="BLOCKED", reason="DURABLE_OPERATION_NOT_READY", operation_id=operation_id, failures=record_failures)
    receipt_binding = bundle["execution_receipt"]
    owner_token = secrets.token_hex(32)
    try:
        claim = store.claim_skill_execution(task_id, receipt_binding["idempotency_key"], request_hash, owner_token)
    except Exception as exc:
        code = getattr(getattr(exc, "code", None), "value", getattr(exc, "code", None))
        if code == "INVALID_SPEC":
            return _fixed_result(state="BLOCKED", reason="OPERATION_INTENT_MISMATCH", operation_id=operation_id, blockers=["IDEMPOTENCY_KEY_BOUND_TO_DIFFERENT_INTENT"])
        return _fixed_result(state="BLOCKED", reason="DURABLE_CLAIM_FAILED", operation_id=operation_id, blockers=["PIPELINE_CLAIM_FAILED"])
    if claim.get("outcome") == "COMPLETED":
        prior = claim.get("result")
        if not isinstance(prior, dict):
            return _fixed_result(state="UNKNOWN", reason="DURABLE_RECEIPT_INVALID", operation_id=operation_id, blockers=["RECONCILIATION_REQUIRED"])
        finalized, finalization_blocker = _finalize_completed_operation(store, bundle, request_hash)
        if not finalized:
            return _fixed_result(
                state="UNKNOWN", reason="HEAVY_SLOT_FINALIZATION_UNCERTAIN", operation_id=operation_id,
                execution_started=bool(prior.get("execution_started")),
                blockers=[finalization_blocker, "RECONCILIATION_REQUIRED"],
            )
        replay = dict(prior)
        replay["operation_id"] = operation_id
        replay["replayed"] = True
        replay["execution_started"] = bool(prior.get("execution_started"))
        return replay
    if claim.get("outcome") != "ACQUIRED":
        return _fixed_result(state="UNKNOWN", reason="EXECUTION_ALREADY_IN_DOUBT", operation_id=operation_id, blockers=["RECONCILIATION_REQUIRED"])
    if not _verify_persisted_scene_lease(bundle):
        return _fixed_result(
            state="UNKNOWN", reason="SCENE_LEASE_NOT_CURRENT", operation_id=operation_id,
            blockers=["PERSISTED_SCENE_LEASE_NOT_MATCHING", "RECONCILIATION_REQUIRED"],
        )
    if not _verify_persisted_heavy_slot(bundle):
        return _fixed_result(
            state="UNKNOWN", reason="HEAVY_SLOT_NOT_OWNED", operation_id=operation_id,
            blockers=["PERSISTED_HEAVY_SLOT_NOT_DISPATCHING", "RECONCILIATION_REQUIRED"],
        )
    frame_guard = _ShortSegmentFrameGuard(
        bundle, store, request_hash, clock=clock, fence_context=_operation_fence_context,
        host_identity_checker=lambda: _read_host_identity(host) == {
            key: expected_identity[key] for key in SHORT_SEGMENT_HOST_IDENTITY_KEYS
        },
    )
    executor_bundle = dict(bundle)
    executor_bundle["frame_guard"] = frame_guard
    try:
        if executor is None:
            result = _run_houdini_short_segment(host, params, frame_start, frame_end, bundle, frame_guard)
        else:
            result = executor(host, executor_bundle, frame_start, frame_end, dict(params))
        result = _validated_host_result(result, frame_guard, bundle, operation_id)
    except _ShortSegmentControlError as exc:
        return _fixed_result(
            state="UNKNOWN", reason=exc.reason, operation_id=operation_id,
            execution_started=frame_guard.host_side_effect_started,
            blockers=[exc.blocker, "RECONCILIATION_REQUIRED"],
        )
    except Exception:
        return _fixed_result(
            state="UNKNOWN", reason="HOST_RESULT_OR_EXECUTOR_UNCERTAIN", operation_id=operation_id,
            execution_started=frame_guard.host_side_effect_started,
            blockers=["HOST_RESPONSE_OR_RESULT_UNCERTAIN", "RECONCILIATION_REQUIRED"],
        )
    try:
        if receipt_commit_hook is not None:
            receipt_commit_hook()
        store.complete_skill_execution(
            task_id, receipt_binding["idempotency_key"], request_hash, owner_token, result,
        )
    except Exception:
        return _fixed_result(
            state="UNKNOWN", reason="RESULT_RECEIPT_COMMIT_UNCERTAIN", operation_id=operation_id,
            execution_started=True, blockers=["RECEIPT_COMMIT_UNCERTAIN", "RECONCILIATION_REQUIRED"],
        )
    try:
        if finalization_hook is not None:
            finalization_hook()
    except Exception:
        return _fixed_result(
            state="UNKNOWN", reason="HEAVY_SLOT_FINALIZATION_UNCERTAIN", operation_id=operation_id,
            execution_started=True, blockers=["HEAVY_SLOT_FINALIZATION_UNCERTAIN", "RECONCILIATION_REQUIRED"],
        )
    finalized, finalization_blocker = _finalize_completed_operation(store, bundle, request_hash)
    if not finalized:
        return _fixed_result(
            state="UNKNOWN", reason="HEAVY_SLOT_FINALIZATION_UNCERTAIN", operation_id=operation_id,
            execution_started=True, blockers=[finalization_blocker, "RECONCILIATION_REQUIRED"],
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-json", type=Path, required=True, help="reviewed read-only GUI template capture JSON")
    parser.add_argument("--review-summary", type=Path, help="the pinned control review summary JSON")
    parser.add_argument("--execute", action="store_true", help="run only with explicit task-operation authorization")
    parser.add_argument("--confirm-short-segment-operation", action="store_true", help="confirm this specific host operation")
    parser.add_argument("--authorization-json", type=Path, help="controller-issued operation/lease/budget authorization")
    parser.add_argument("--task-id", help="task identity bound to the authorization bundle")
    parser.add_argument("--operation-id", help="operation identity bound to the authorization bundle")
    parser.add_argument("--params-json", type=Path, help="task-owned source parameters for the authorized host check")
    parser.add_argument("--frame-start", type=int, default=1)
    parser.add_argument("--frame-end", type=int, default=12)
    args = parser.parse_args(argv)
    if not args.execute:
        result = plan(args.capture_json, args.review_summary)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["state"] == "PLAN_READY" else 1
    if not args.confirm_short_segment_operation:
        print(json.dumps(_fixed_result(
            state="BLOCKED",
            reason="EXPLICIT_SHORT_SEGMENT_CONFIRMATION_REQUIRED",
            blockers=["OPERATOR_CONFIRMATION_MISSING"],
        ), ensure_ascii=False, sort_keys=True))
        return 2
    required = (args.authorization_json, args.task_id, args.operation_id, args.params_json)
    if any(value is None for value in required):
        print(json.dumps(_fixed_result(
            state="BLOCKED",
            reason="EXECUTION_ARGUMENTS_INCOMPLETE",
            blockers=["AUTHORIZATION_OPERATION_AND_PARAMS_REQUIRED"],
        ), ensure_ascii=False, sort_keys=True))
        return 2
    try:
        params = _decode_json(args.params_json.read_bytes())
    except (OSError, UnicodeError, ValueError, TypeError):
        print(json.dumps(_fixed_result(
            state="BLOCKED", reason="TASK_PARAMS_INVALID", blockers=["TASK_PARAMS_JSON_INVALID"],
        ), ensure_ascii=False, sort_keys=True))
        return 2
    result = execute_short_segment(
        args.capture_json,
        args.authorization_json,
        task_id=str(args.task_id),
        operation_id=str(args.operation_id),
        frame_start=args.frame_start,
        frame_end=args.frame_end,
        params=params if isinstance(params, dict) else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("state") == "EXECUTED_HOST_SHORT_SEGMENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
