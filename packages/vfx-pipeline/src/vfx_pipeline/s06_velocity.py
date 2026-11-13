"""Structured inactive-velocity evidence for the S-06 software/host boundary.

The comparator deliberately compares every sampled component in the same
sample domain. Aggregates are reported for diagnostics only and are never
used as the equality decision. The module has no Houdini dependency and can
be exercised with a fake-HOM field snapshot.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


SNAPSHOT_SCHEMA = "bridge.f2.velocity-field-snapshot/1.0"
EVIDENCE_SCHEMA = "bridge.f2.inactive-velocity-evidence/1.0"
SOURCING_BOUNDARY_SCHEMA = "bridge.f2.sourcing-boundary/1.0"
TOLERANCE = {
    "absolute": 1.0e-6,
    "relative": 1.0e-6,
    "source": "bridge-f2-s06-fixed-velocity-tolerance-v1",
}
SNAPSHOT_KEYS = {
    "schema",
    "field",
    "sample_domain",
    "coordinate_space",
    "units",
    "component_order",
    "values",
    "sample_count",
    "digest_sha256",
    "aggregate",
}
VALID_RESULTS = frozenset({"pass", "fail", "unknown", "not_applicable"})


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _numeric_row(value: Any, components: int) -> list[float] | None:
    if components == 1 and _finite(value):
        return [float(value)]
    if not isinstance(value, (list, tuple)) or len(value) != components:
        return None
    if not all(_finite(item) for item in value):
        return None
    return [float(item) for item in value]


def _aggregate(values: list[list[float]]) -> dict[str, Any]:
    if not values:
        return {"sum": [], "l2": 0.0, "min": [], "max": []}
    width = len(values[0])
    sums = [sum(row[index] for row in values) for index in range(width)]
    mins = [min(row[index] for row in values) for index in range(width)]
    maxs = [max(row[index] for row in values) for index in range(width)]
    return {
        "sum": sums,
        "l2": math.sqrt(sum(item * item for row in values for item in row)),
        "min": mins,
        "max": maxs,
    }


def make_snapshot(
    *,
    field: str,
    sample_domain: Mapping[str, Any],
    coordinate_space: str,
    units: Mapping[str, Any],
    component_order: list[str] | tuple[str, ...],
    values: list[Any] | tuple[Any, ...],
) -> dict[str, Any]:
    """Normalize a finite field readback into a hash-bound snapshot."""

    if not isinstance(field, str) or not field.strip():
        raise ValueError("velocity field name is required")
    if not isinstance(sample_domain, Mapping) or not sample_domain:
        raise ValueError("sample domain is required")
    if not isinstance(coordinate_space, str) or not coordinate_space.strip():
        raise ValueError("coordinate space is required")
    if not isinstance(units, Mapping) or not units:
        raise ValueError("velocity units are required")
    components = list(component_order)
    if not components or len(set(components)) != len(components) or not all(isinstance(item, str) and item for item in components):
        raise ValueError("component order is invalid")
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("at least one field sample is required")
    normalized: list[list[float]] = []
    for value in values:
        row = _numeric_row(value, len(components))
        if row is None:
            raise ValueError("field samples have the wrong component shape")
        normalized.append(row)
    domain = json.loads(_canonical(dict(sample_domain)))
    unit_payload = json.loads(_canonical(dict(units)))
    content = {
        "schema": SNAPSHOT_SCHEMA,
        "field": field,
        "sample_domain": domain,
        "coordinate_space": coordinate_space,
        "units": unit_payload,
        "component_order": components,
        "values": normalized,
        "sample_count": len(normalized),
    }
    return {
        **content,
        "digest_sha256": _sha(content),
        "aggregate": _aggregate(normalized),
    }


def default_controller_sentinel() -> dict[str, Any]:
    """Return the fixed nonzero sentinel requested by the trusted controller."""

    return make_snapshot(
        field="vel",
        sample_domain={
            "kind": "controller_sentinel_voxels",
            "space": "object",
            "resolution": [2, 1, 1],
            "indices": [[0, 0, 0], [1, 0, 0]],
        },
        coordinate_space="object",
        units={"velocity": "scene_units_per_second"},
        component_order=["x", "y", "z"],
        values=[[1.0, 0.5, -0.25], [0.75, -0.5, 0.125]],
    )


def validate_snapshot(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["VELOCITY_SNAPSHOT_MISSING"]
    failures: list[str] = []
    if set(value) != SNAPSHOT_KEYS:
        failures.append("VELOCITY_SNAPSHOT_KEYS_INVALID")
    if value.get("schema") != SNAPSHOT_SCHEMA:
        failures.append("VELOCITY_SNAPSHOT_SCHEMA_INVALID")
    if value.get("field") != "vel":
        failures.append("VELOCITY_FIELD_NAME_INVALID")
    domain = value.get("sample_domain")
    if not isinstance(domain, Mapping) or not domain:
        failures.append("VELOCITY_SAMPLE_DOMAIN_INVALID")
    if not isinstance(value.get("coordinate_space"), str) or not value.get("coordinate_space"):
        failures.append("VELOCITY_COORDINATE_SPACE_INVALID")
    if not isinstance(value.get("units"), Mapping) or not value.get("units"):
        failures.append("VELOCITY_UNITS_INVALID")
    components = value.get("component_order")
    if not isinstance(components, list) or not components or len(set(components)) != len(components):
        failures.append("VELOCITY_COMPONENT_ORDER_INVALID")
    elif components != ["x", "y", "z"]:
        failures.append("VELOCITY_COMPONENT_ORDER_INVALID")
    values = value.get("values")
    if not isinstance(values, list) or not values:
        failures.append("VELOCITY_VALUES_INVALID")
    elif isinstance(components, list):
        if any(_numeric_row(item, len(components)) is None for item in values):
            failures.append("VELOCITY_COMPONENT_SHAPE_INVALID")
    if type(value.get("sample_count")) is not int or value.get("sample_count") != len(values or []) or int(value.get("sample_count") or 0) > 4096:
        failures.append("VELOCITY_SAMPLE_COUNT_INVALID")
    digest = value.get("digest_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        failures.append("VELOCITY_DIGEST_INVALID")
    else:
        content = {
            "schema": value.get("schema"),
            "field": value.get("field"),
            "sample_domain": value.get("sample_domain"),
            "coordinate_space": value.get("coordinate_space"),
            "units": value.get("units"),
            "component_order": value.get("component_order"),
            "values": value.get("values"),
            "sample_count": value.get("sample_count"),
        }
        try:
            if digest != _sha(content):
                failures.append("VELOCITY_DIGEST_MISMATCH")
        except (TypeError, ValueError):
            failures.append("VELOCITY_DIGEST_UNHASHABLE")
    return list(dict.fromkeys(failures))


def _nonzero(snapshot: Mapping[str, Any]) -> bool:
    return any(abs(float(number)) > TOLERANCE["absolute"] for row in snapshot.get("values", []) for number in row)


def _within(before: float, after: float) -> bool:
    delta = abs(after - before)
    limit = TOLERANCE["absolute"] + TOLERANCE["relative"] * max(abs(before), abs(after))
    return delta <= limit


def not_applicable(*, frame: int, reason: str = "ACTIVE_SOURCE_ROW") -> dict[str, Any]:
    return {
        "schema": EVIDENCE_SCHEMA,
        "frame": int(frame),
        "applicability": "not_applicable",
        "status": "not_applicable",
        "reason": reason,
        "tolerance": dict(TOLERANCE),
    }


def validate_sourcing_boundary(value: Any, *, frame: int) -> list[str]:
    """Validate host evidence that brackets the actual sourcing operation.

    A pair of equal field reads is not a sourcing proof.  The native host
    adapter must identify a pre-sourcing read, the sourcing operation, and a
    post-sourcing read with distinct freshness tokens/generations.
    """

    if not isinstance(value, Mapping):
        return ["SOURCING_BOUNDARY_MISSING"]
    failures: list[str] = []
    if value.get("schema") != SOURCING_BOUNDARY_SCHEMA:
        failures.append("SOURCING_BOUNDARY_SCHEMA_INVALID")
    if type(value.get("frame")) is not int or value.get("frame") != frame:
        failures.append("SOURCING_BOUNDARY_FRAME_INVALID")
    before = value.get("before")
    after = value.get("after")
    operation = value.get("operation")
    for name, item, stage in (
        ("before", before, "pre_sourcing_readback"),
        ("after", after, "post_sourcing_readback"),
    ):
        if not isinstance(item, Mapping):
            failures.append("SOURCING_BOUNDARY_{}_MISSING".format(name.upper()))
            continue
        if item.get("stage") != stage:
            failures.append("SOURCING_BOUNDARY_{}_STAGE_INVALID".format(name.upper()))
        if type(item.get("frame")) is not int or item.get("frame") != frame:
            failures.append("SOURCING_BOUNDARY_{}_FRAME_INVALID".format(name.upper()))
        if not isinstance(item.get("freshness_token"), str) or not item.get("freshness_token"):
            failures.append("SOURCING_BOUNDARY_{}_TOKEN_INVALID".format(name.upper()))
        generation = item.get("field_generation")
        if type(generation) is not int or generation < 0:
            failures.append("SOURCING_BOUNDARY_{}_GENERATION_INVALID".format(name.upper()))
    if not isinstance(operation, Mapping):
        failures.append("SOURCING_BOUNDARY_OPERATION_MISSING")
    else:
        if operation.get("status") != "performed":
            failures.append("SOURCING_BOUNDARY_OPERATION_NOT_PERFORMED")
        if not isinstance(operation.get("operation_id"), str) or not operation.get("operation_id"):
            failures.append("SOURCING_BOUNDARY_OPERATION_ID_INVALID")
        if operation.get("source_binding_write") is not True:
            failures.append("SOURCING_BOUNDARY_SOURCE_WRITE_UNCONFIRMED")
        if operation.get("solver_refresh") is not True:
            failures.append("SOURCING_BOUNDARY_SOLVER_REFRESH_UNCONFIRMED")
        if operation.get("input_index") != 0:
            failures.append("SOURCING_BOUNDARY_INPUT_NOT_ZERO")
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        if before.get("freshness_token") == after.get("freshness_token"):
            failures.append("SOURCING_BOUNDARY_FRESHNESS_TOKEN_REPEATED")
        if before.get("field_generation") == after.get("field_generation"):
            failures.append("SOURCING_BOUNDARY_FIELD_GENERATION_REPEATED")
    return list(dict.fromkeys(failures))


def compare_inactive_velocity(
    before: Any,
    after: Any,
    *,
    frame: int,
    before_frame: int | None = None,
    after_frame: int | None = None,
    row2_active_before: Any = False,
    row2_active_after: Any = False,
    source_effect_isolated: Any = False,
    no_other_velocity_writers: Any = None,
    sourcing_boundary: Any = None,
) -> dict[str, Any]:
    """Compare an inactive field across a native sourcing boundary.

    The comparison is component-wise. A missing or uncontrolled precondition is
    unknown; a domain/unit/field mismatch or a changed component is fail. The
    function never treats equal sums or equal norms as equality.
    """

    base = {
        "schema": EVIDENCE_SCHEMA,
        "frame": int(frame),
        "applicability": "applicable",
        "tolerance": dict(TOLERANCE),
        "comparison_method": "sourcing_boundary_componentwise",
    }
    if row2_active_before is not False or row2_active_after is not False:
        return {**base, "status": "unknown", "reason": "INACTIVE_ROW_NOT_PROVEN"}
    if before_frame is None or after_frame is None or before_frame != after_frame or after_frame != frame:
        return {**base, "status": "unknown", "reason": "SAME_STOP_FRAME_NOT_PROVEN"}
    if source_effect_isolated is not True:
        return {**base, "status": "unknown", "reason": "SOURCE_EFFECT_NOT_ISOLATED"}
    if no_other_velocity_writers is not True:
        return {**base, "status": "unknown", "reason": "OTHER_VELOCITY_WRITER_UNCONTROLLED"}
    boundary_failures = validate_sourcing_boundary(sourcing_boundary, frame=frame)
    if boundary_failures:
        return {
            **base,
            "status": "unknown",
            "reason": "SOURCING_BOUNDARY_FRESHNESS_UNAVAILABLE",
            "sourcing_boundary_failures": boundary_failures,
        }
    before_failures = validate_snapshot(before)
    after_failures = validate_snapshot(after)
    if before_failures or after_failures:
        return {
            **base,
            "status": "unknown",
            "reason": "VELOCITY_SNAPSHOT_INVALID",
            "before_failures": before_failures,
            "after_failures": after_failures,
        }
    assert isinstance(before, Mapping) and isinstance(after, Mapping)
    shared = ("field", "sample_domain", "coordinate_space", "units", "component_order", "sample_count")
    mismatches = [key for key in shared if before.get(key) != after.get(key)]
    if mismatches:
        return {
            **base,
            "status": "fail",
            "reason": "VELOCITY_SNAPSHOT_DOMAIN_OR_UNIT_MISMATCH",
            "mismatched_fields": mismatches,
            "before_digest": before.get("digest_sha256"),
            "after_digest": after.get("digest_sha256"),
        }
    if not _nonzero(before):
        return {
            **base,
            "status": "unknown",
            "reason": "VELOCITY_BASELINE_ZERO",
            "before_digest": before.get("digest_sha256"),
            "after_digest": after.get("digest_sha256"),
        }
    mismatches = []
    for sample_index, (before_row, after_row) in enumerate(zip(before["values"], after["values"])):
        for component_index, (before_value, after_value) in enumerate(zip(before_row, after_row)):
            if not _within(float(before_value), float(after_value)):
                mismatches.append({
                    "sample_index": sample_index,
                    "component_index": component_index,
                    "before": float(before_value),
                    "after": float(after_value),
                    "delta": float(after_value) - float(before_value),
                })
    return {
        **base,
        "status": "fail" if mismatches else "pass",
        "reason": "VELOCITY_COMPONENT_MISMATCH" if mismatches else "VELOCITY_PRESERVED",
        "before_digest": before["digest_sha256"],
        "after_digest": after["digest_sha256"],
        "sample_count": before["sample_count"],
        "component_order": list(before["component_order"]),
        "coordinate_space": before["coordinate_space"],
        "units": dict(before["units"]),
        "mismatches": mismatches,
        "before_aggregate": dict(before["aggregate"]),
        "after_aggregate": dict(after["aggregate"]),
        "sourcing_boundary": dict(sourcing_boundary),
    }


def validate_evidence_record(value: Any, *, row2_active: bool) -> list[str]:
    if not isinstance(value, Mapping):
        return ["VELOCITY_EVIDENCE_MISSING"]
    failures: list[str] = []
    applicability = value.get("applicability")
    status = value.get("status")
    if value.get("schema") != EVIDENCE_SCHEMA:
        failures.append("VELOCITY_EVIDENCE_SCHEMA_INVALID")
    if type(value.get("frame")) is not int:
        failures.append("VELOCITY_EVIDENCE_FRAME_INVALID")
    if row2_active:
        if applicability != "not_applicable" or status != "not_applicable":
            failures.append("ACTIVE_VELOCITY_CHECK_MUST_BE_NOT_APPLICABLE")
        return list(dict.fromkeys(failures))
    if applicability != "applicable":
        failures.append("INACTIVE_VELOCITY_APPLICABILITY_INVALID")
    if status not in {"pass", "fail", "unknown"}:
        failures.append("INACTIVE_VELOCITY_STATUS_INVALID")
    if status == "pass":
        for key in (
            "before_digest", "after_digest", "sample_count", "component_order", "coordinate_space",
            "units", "tolerance", "sourcing_boundary",
        ):
            if key not in value:
                failures.append("VELOCITY_PASS_EVIDENCE_INCOMPLETE:" + key)
        if "sourcing_boundary" in value:
            failures.extend(validate_sourcing_boundary(value.get("sourcing_boundary"), frame=int(value.get("frame"))))
    return list(dict.fromkeys(failures))
