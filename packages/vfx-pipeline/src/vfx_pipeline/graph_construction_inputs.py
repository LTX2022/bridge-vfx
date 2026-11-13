"""Bounded controller input snapshots; file facts do not attest geometry."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from typing import Any

from houdini_bridge.render_ocio_facts import _chain, _file_path, _signature


MAX_MANIFEST_ITEMS = 32
MAX_REST_BYTES = 64 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_PARTICLE_BASIS_BYTES = 4096
MAX_RENDER_SCENE_BYTES = 64 * 1024


def _clone_json(value: Any, budget: list[int], depth: int = 0) -> Any:
    budget[0] -= 1
    if budget[0] < 0 or depth > 16:
        raise ValueError("construction input metadata complexity budget exceeded")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if value.bit_length() > 64:
            raise ValueError("construction input integer budget exceeded")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("construction input nonfinite metadata refused")
        return value
    if type(value) is str:
        if len(value) > 8192 or "\0" in value:
            raise ValueError("construction input string budget exceeded")
        try:
            budget[1] -= len(value.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("construction input invalid Unicode metadata") from error
        if budget[1] < 0:
            raise ValueError("construction input metadata byte budget exceeded")
        return value
    if type(value) is list:
        if len(value) > 4096:
            raise ValueError("construction input list budget exceeded")
        return [_clone_json(item, budget, depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 4096 or any(type(key) is not str for key in value):
            raise ValueError("construction input JSON object required")
        return {_clone_json(key, budget, depth + 1): _clone_json(item, budget, depth + 1)
                for key, item in value.items()}
    raise ValueError("construction input JSON metadata required")


def _verify_file(item: dict[str, Any], *, capture: bool = False) -> bytes | None:
    path = _file_path(item.get("source_uri") or item.get("identity"))
    chain = _chain(path)
    before = path.lstat()
    if before.st_nlink != 1 or before.st_size != item["bytes"]:
        raise ValueError("construction input file identity or bytes changed")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or _signature(opened) != _signature(before) or _chain(path) != chain):
            raise ValueError("construction input file changed before read")
        digest = hashlib.sha256()
        size = 0
        captured = []
        while True:
            block = os.read(descriptor, min(65536, item["bytes"] - size + 1))
            if not block:
                break
            size += len(block)
            if size > item["bytes"]:
                raise ValueError("construction input file byte budget exceeded")
            digest.update(block)
            if capture:
                captured.append(block)
        if (size != item["bytes"] or digest.hexdigest() != item["sha256"]
                or _signature(os.fstat(descriptor)) != _signature(before)
                or os.fstat(descriptor).st_nlink != 1
                or _signature(path.lstat()) != _signature(before)
                or path.lstat().st_nlink != 1 or _chain(path) != chain):
            raise ValueError("construction input file changed during read")
        return b"".join(captured) if capture else None
    finally:
        os.close(descriptor)


def freeze_construction_inputs(value: Any, *, verify_files: bool = True) -> list[dict[str, Any]]:
    """Clone explicit JSON metadata and optionally verify bounded stable file bytes."""
    if type(verify_files) is not bool:
        raise ValueError("verify_files must be an explicit boolean")
    if value is None:
        value = []
    if type(value) is not list or len(value) > MAX_MANIFEST_ITEMS:
        raise ValueError("construction input manifest requires at most 32 items")
    manifest = _clone_json(value, [4096, MAX_METADATA_BYTES])
    total = 0
    for index, item in enumerate(manifest):
        if (type(item) is not dict or type(item.get("index")) is not int
                or item["index"] != index or "frames" in item):
            raise ValueError("construction input ordered file records required")
        for key in ("asset_id", "semantic_role"):
            if type(item.get(key)) is not str or not item[key].strip():
                raise ValueError("construction input explicit asset_id and semantic_role required")
        names = [item[key] for key in ("source_uri", "identity") if key in item]
        if not names:
            raise ValueError("construction input explicit local file identity required")
        for name in names:
            path = _file_path(name)
            if str(path) != name or name.startswith(("//", "\\\\")):
                raise ValueError("construction input canonical local file identity required")
        if len(names) == 2 and names[0] != names[1]:
            raise ValueError("construction input file identities disagree")
        if (type(item.get("sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("construction input declared lowercase sha256 required")
        limit = (MAX_REST_BYTES if item["semantic_role"] == "geometry_rest_basis" else
                 MAX_PARTICLE_BASIS_BYTES if item["semantic_role"] == "particle_emission_basis" else
                 MAX_RENDER_SCENE_BYTES if item["semantic_role"] == "render_scene_configuration" else MAX_INPUT_BYTES)
        if type(item.get("bytes")) is not int or not 0 <= item["bytes"] <= limit:
            raise ValueError("construction input file byte budget exceeded")
        if "geometry_observation" in item and (
                type(item["geometry_observation"]) is not str or not item["geometry_observation"].strip()):
            raise ValueError("construction input invalid geometry_observation metadata")
        total += item["bytes"]
    if total > MAX_TOTAL_BYTES:
        raise ValueError("construction input total byte budget exceeded")
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("construction input metadata byte budget exceeded")
    if verify_files:
        try:
            for item in manifest:
                _verify_file(item)
        except (OSError, RuntimeError) as error:
            raise ValueError("construction input local file verification refused") from error
    return manifest


def particle_emission_configuration(value: Any) -> dict[str, int] | None:
    manifest = freeze_construction_inputs(value, verify_files=False)
    matches = [item for item in manifest if item["semantic_role"] == "particle_emission_basis"]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("one explicit particle emission basis file required")
    try:
        raw = _verify_file(matches[0], capture=True)
        def unique_fields(pairs):
            result = {}
            for name, item in pairs:
                if name in result:
                    raise ValueError("duplicate particle emission basis fields refused")
                result[name] = item
            return result
        supplied = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("particle emission basis file verification refused") from error
    if (type(supplied) is not dict or set(supplied) != {"task_seed"}
            or type(supplied["task_seed"]) is not int or not 0 <= supplied["task_seed"] <= 2147483647):
        raise ValueError("explicit nonnegative int32 particle task_seed required")
    return supplied


def render_scene_configuration(value: Any, version: str | None = None) -> dict | None:
    """Read the controller-frozen semantic scene file, never native code/paths."""
    from houdini_bridge.native_render_scene import validate_configuration
    manifest = freeze_construction_inputs(value, verify_files=False)
    matches = [item for item in manifest if item["semantic_role"] == "render_scene_configuration"]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("one explicit render scene configuration file required")
    def unique_fields(pairs):
        result = {}
        for name, item in pairs:
            if name in result:
                raise ValueError("duplicate render scene configuration fields refused")
            result[name] = item
        return result
    try:
        raw = _verify_file(matches[0], capture=True)
        supplied = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("render scene configuration verification refused") from error
    return validate_configuration(supplied, version)
