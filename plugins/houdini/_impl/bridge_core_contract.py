# -*- coding: utf-8 -*-
"""Pure contract helpers for the Bridge core execution chain (no ``hou``).

Everything here must stay importable outside Houdini so the software gate can
test the connection contract, source menu choice rule, operation id derivation
and unlock parameter semantics without a live host.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable


def validate_connection_set(connections: Any, known_roles: Iterable[str]) -> dict[str, Any]:
    """Structural validation of a full connection set BEFORE any side effect.

    Rejects malformed entries, unknown roles, negative or non-integer ports,
    and duplicate destination ports.  Returns {"ok": bool, "errors": [...],
    "connections": [normalized entries]}.
    """
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen_dest: set[tuple[str, int]] = set()
    roles = set(known_roles)
    if not isinstance(connections, (list, tuple)):
        return {"ok": False, "errors": ["connections must be a sequence"], "connections": []}
    for index, raw in enumerate(connections):
        if isinstance(raw, dict):
            source_role = raw.get("source_role")
            source_output = raw.get("source_output")
            destination_role = raw.get("destination_role")
            destination_input = raw.get("destination_input")
        else:
            try:
                source_role, source_output, destination_role, destination_input = raw
            except Exception:
                errors.append("connection[{}]: malformed entry {!r}".format(index, raw))
                continue
        if not isinstance(source_role, str) or not isinstance(destination_role, str):
            errors.append("connection[{}]: roles must be strings".format(index))
            continue
        if source_role not in roles:
            errors.append("connection[{}]: unknown source_role {!r}".format(index, source_role))
        if destination_role not in roles:
            errors.append("connection[{}]: unknown destination_role {!r}".format(index, destination_role))
        for name, value in (("source_output", source_output), ("destination_input", destination_input)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append("connection[{}]: {} must be a non-negative int, got {!r}".format(index, name, value))
        key = (destination_role, destination_input if isinstance(destination_input, int) else -1)
        if key in seen_dest:
            errors.append("connection[{}]: duplicate destination port {}.input{}".format(
                index, destination_role, destination_input))
        seen_dest.add(key)
        normalized.append({
            "source_role": source_role,
            "source_output": source_output,
            "destination_role": destination_role,
            "destination_input": destination_input,
        })
    return {"ok": not errors, "errors": errors, "connections": normalized}


def choose_polygon_menu_index(labels: Iterable[str]) -> "int | None":
    """Pick the polygon-mesh entry from a native menu, template values first.

    Preference: a label containing 'polygon mesh', then any 'polygon' label.
    Never guesses integer menu values.
    """
    labels = [str(label) for label in labels]
    for pattern in (r"polygon\s*mesh", r"polygons?\b"):
        for index, label in enumerate(labels):
            if re.search(pattern, label, re.IGNORECASE):
                return index
    return None


def derive_operation_id(task_id: str, subject: str, frames: list[int]) -> str:
    """Stable operation id: identical request -> identical id (retry-safe)."""
    payload = json_dumps({"task_id": str(task_id), "subject": str(subject), "frames": [int(f) for f in frames]})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def interpret_unlock_params(params: dict[str, Any]) -> dict[str, Any]:
    """Interpret ``node.unlock_contents`` parameters with explicit semantics.

    Returns {"ok": bool, "propagate": bool, "deprecated_value_used": bool,
    "error": code, "message": str}.  The deprecated ``value`` parameter is only
    accepted when it is literally ``True``; ``value=False`` cannot be silently
    reinterpreted as a re-lock because the native API keeps unlocked contents
    editable either way.
    """
    propagate = params.get("propagate")
    if propagate is None:
        propagate = False
    if not isinstance(propagate, bool):
        return {"ok": False, "error": "INVALID_ARGUMENT",
                "message": "propagate must be a boolean, got {!r}".format(propagate)}
    if "value" in params:
        value = params.get("value")
        if value is True:
            return {"ok": True, "propagate": propagate, "deprecated_value_used": True}
        return {"ok": False, "error": "UNLOCK_SEMANTICS_CHANGED",
                "message": ("value=False cannot re-lock contents: the native API keeps an unlocked asset "
                            "editable; omit 'value' and pass propagate (default false) instead")}
    return {"ok": True, "propagate": propagate, "deprecated_value_used": False}
