"""Canonical JSON helpers used by approvals, tasks, and evidence records."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def json_value(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation.

    Hashes used for approvals must never depend on dictionary insertion order,
    platform path objects, or non-finite floating point serialization.
    """

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        rendered = [json_value(item) for item in value]
        return sorted(rendered, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite floats are not allowed in canonical payloads")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
