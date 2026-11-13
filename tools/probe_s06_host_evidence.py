#!/usr/bin/env python3
"""Read-only supplement for the missing native S-06 host interfaces.

Paste the ``capture(hou)`` call in Houdini's Python Shell.  This script only
reads the current application version, saved HIP/file facts, /obj names, and
the exact versioned provider attribute/method names.  It never creates a node,
sets a parameter or frame, cooks, saves, caches, renders, or imports a scene.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


PROVIDER_ATTRIBUTE = "bridge_s06_native_adapter_v1"
PROVIDER_SCHEMA = "bridge.f2.s06-native-host-adapter/1.0"
REQUIRED_INTERFACES = (
    "field_snapshot",
    "apply_velocity_sentinel",
    "velocity_writer_inventory",
    "observe_sourcing_boundary",
)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _file_facts(path_text: str) -> dict[str, Any]:
    path = Path(path_text).expanduser() if path_text else None
    facts: dict[str, Any] = {
        "path": str(path) if path is not None else "",
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
    if path is None:
        return facts
    try:
        info = path.lstat()
        facts.update({
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
                    facts["parent_symlink"] = True
                    break
            except OSError:
                facts["parent_symlink"] = True
                break
        if facts["is_regular_file"] and not facts["is_symlink"] and not facts["parent_symlink"]:
            facts["sha256"] = _sha256(path)
    except OSError:
        pass
    return facts


def _identity(hou: Any) -> tuple[dict[str, Any], str | None]:
    getter = getattr(hou, "bridge_scene_identity", None)
    if not callable(getter):
        return {}, "bridge_scene_identity_unavailable"
    try:
        value = getter()
    except Exception as exc:  # pragma: no cover - host-specific
        return {}, type(exc).__name__
    if not isinstance(value, dict):
        return {}, "bridge_scene_identity_not_object"
    return {str(key): value.get(key) for key in ("session_id", "process_generation", "scene_id", "hip_path")}, None


def capture(hou: Any) -> dict[str, Any]:
    """Capture host capability facts without mutating Houdini."""

    version_getter = getattr(hou, "applicationVersionString", None)
    version = str(version_getter()) if callable(version_getter) else ""
    identity, identity_error = _identity(hou)
    hip_path = str(identity.get("hip_path") or "")
    hip_file = getattr(hou, "hipFile", None)
    if not hip_path and hip_file is not None:
        path_getter = getattr(hip_file, "path", None)
        if callable(path_getter):
            try:
                hip_path = str(path_getter() or "")
            except Exception:
                hip_path = ""
    dirty = None
    if hip_file is not None:
        dirty_getter = getattr(hip_file, "hasUnsavedChanges", None)
        if callable(dirty_getter):
            try:
                dirty = bool(dirty_getter())
            except Exception:
                dirty = None
    provider = getattr(hou, PROVIDER_ATTRIBUTE, None)
    schema = getattr(provider, "schema", None) if provider is not None else None
    if callable(schema):
        try:
            schema = schema()
        except Exception:
            schema = None
    available = [name for name in REQUIRED_INTERFACES if callable(getattr(provider, name, None))] if provider is not None else []
    missing = [name for name in REQUIRED_INTERFACES if name not in available]
    exact = schema == PROVIDER_SCHEMA and not missing
    provider_capabilities = None
    provider_capabilities_error = None
    if provider is not None:
        capabilities_getter = getattr(provider, "capabilities", None)
        if not callable(capabilities_getter):
            provider_capabilities_error = "PROVIDER_CAPABILITIES_METHOD_MISSING"
        else:
            try:
                candidate = capabilities_getter()
                if isinstance(candidate, dict):
                    provider_capabilities = candidate
                else:
                    provider_capabilities_error = "PROVIDER_CAPABILITIES_NOT_OBJECT"
            except Exception as exc:
                provider_capabilities_error = "PROVIDER_CAPABILITIES_ERROR:{}".format(type(exc).__name__)
    mutation_ready = bool(
        exact
        and isinstance(provider_capabilities, dict)
        and provider_capabilities.get("schema") == PROVIDER_SCHEMA
        and provider_capabilities.get("ready_for_mutation") is True
        and isinstance(provider_capabilities.get("interfaces"), dict)
        and all(
            isinstance(provider_capabilities["interfaces"].get(name), dict)
            and provider_capabilities["interfaces"][name].get("status") == "verified"
            for name in REQUIRED_INTERFACES
        )
    )
    children: list[str] = []
    try:
        obj = hou.node("/obj")
        if obj is not None:
            children = sorted(str(item.path()) for item in obj.children())
    except Exception:
        children = []
    return {
        "schema": "bridge.f2.s06-host-evidence-supplement/1.0",
        "capture_state": "READ_ONLY_HOST_INTERFACE_PROBE",
        "houdini_version": version,
        "scene_identity": identity,
        "identity_error": identity_error,
        "file_evidence": _file_facts(hip_path),
        "has_unsaved_changes": dirty,
        "obj_children": children,
        "native_provider": {
            "attribute": PROVIDER_ATTRIBUTE,
            "expected_schema": PROVIDER_SCHEMA,
            "reported_schema": schema if isinstance(schema, str) else None,
            "available_interfaces": available,
            "missing_interfaces": [] if exact else missing or ["versioned_native_provider"],
            "provider_capabilities": provider_capabilities,
            "provider_capabilities_error": provider_capabilities_error,
            "mutation_ready": mutation_ready,
            "status": "OBSERVED_CUSTOM_SEAM_ONLY" if exact else "UNIMPLEMENTED",
            "qualifies_as_sidefx_native": False,
            "native_api_probe": "tools/probe_s06_native_api_evidence.py",
        },
        "read_only_contract": {
            "writes_scene": False,
            "reads_existing_scene_parameters": False,
            "sets_frame": False,
            "cooks": False,
            "writes_cache": False,
            "renders": False,
            "saves": False,
        },
    }


if __name__ == "__main__":
    try:
        import hou  # type: ignore
    except ImportError:
        raise SystemExit("Run this script from Houdini's Python Shell with hou available")
    print(json.dumps(capture(hou), ensure_ascii=False, indent=2, sort_keys=True))
