"""Shared bounded render observations and persisted operation snapshots.

These are Python capture/read limits, not native USD/OCIO allocation guarantees.
Each configuration capture shares one allowance across every requested frame.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

MAX_CONFIGURATION_BYTES = 2 * 1024 * 1024
MAX_CONFIGURATION_VALUES = 32768
MAX_OPERATION_BYTES = 8 * 1024 * 1024
MAX_OPERATION_VALUES = 131072
MAX_STORE_BYTES = 64 * 1024 * 1024
MAX_FILE_READ_BYTES = 32 * 1024 * 1024
FILE_BUDGET_SCHEMA = "bridge.houdini.ocio-read-budget/1.0"
COMPLETION_HEADROOM_BYTES = 1024 * 1024
COMPLETION_HEADROOM_VALUES = 32768


class RenderObservationLimit(ValueError):
    pass


def json_usage(value: Any, *, max_bytes: int, max_values: int) -> tuple[int, int]:
    """Reject oversized values before constructing a complete encoded payload."""
    count = 0
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        count += 1
        if count > max_values or depth > 64:
            raise RenderObservationLimit("render observation value/depth budget exceeded")
        if type(current) is dict:
            if len(current) > max_values - count:
                raise RenderObservationLimit("render observation value budget exceeded")
            for name, item in current.items():
                if type(name) is not str or len(name) > max_bytes:
                    raise RenderObservationLimit("render observation key budget exceeded")
                pending.append((name, depth + 1))
                pending.append((item, depth + 1))
        elif type(current) in {list, tuple}:
            if len(current) > max_values - count:
                raise RenderObservationLimit("render observation value budget exceeded")
            pending.extend((item, depth + 1) for item in current)
        elif type(current) is str and len(current) > max_bytes:
            raise RenderObservationLimit("render observation text budget exceeded")
    size = 0
    for part in json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).iterencode(value):
        size += len(part.encode("utf-8"))
        if size > max_bytes:
            raise RenderObservationLimit("render observation byte budget exceeded")
    return size, count


def validate_render_record(record: dict[str, Any]) -> None:
    json_usage(record, max_bytes=MAX_OPERATION_BYTES, max_values=MAX_OPERATION_VALUES)


def reserve_render_completion(record: dict[str, Any]) -> None:
    """Account for config/output copies in the terminal fact before any render.

    Four copies conservatively cover the frozen config, observed frame facts,
    and their terminal snapshot. The remainder is reserved for frame metadata
    and lifecycle fields; no output or terminal fact is synthesized here.
    """
    size, count = json_usage(record, max_bytes=MAX_OPERATION_BYTES,
                             max_values=MAX_OPERATION_VALUES)
    if (4 * size + COMPLETION_HEADROOM_BYTES > MAX_OPERATION_BYTES
            or 4 * count + COMPLETION_HEADROOM_VALUES > MAX_OPERATION_VALUES):
        raise RenderObservationLimit("render operation lacks bounded completion-record headroom")


def read_store_payload(path: Path) -> str:
    """Read at most the store allowance and preserve the file on refusal."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_STORE_BYTES:
            raise RenderObservationLimit("render operation store exceeds its read budget; file preserved")
        chunks, size = [], 0
        while True:
            part = stream.read(min(65536, MAX_STORE_BYTES - size + 1))
            if not part:
                break
            size += len(part)
            if size > MAX_STORE_BYTES:
                raise RenderObservationLimit("render operation store grew past its read budget; file preserved")
            chunks.append(part)
        return b"".join(chunks).decode("utf-8")


def validate_store(store: dict[str, Any]) -> None:
    if type(store) is not dict or ("operations" in store and type(store["operations"]) is not dict):
        raise ValueError("operation store and operations must be JSON objects")
    for family in ('operations', 'scene_transitions'):
        records = store.get(family, {})
        if type(records) is not dict:
            raise ValueError('operation family must be a JSON object')
        for operation_id, record in records.items():
            if type(record) is not dict:
                raise ValueError("operation record must be a JSON object")
            if record.get("kind") == "render" or family == 'scene_transitions':
                validate_render_record(record)
            if 'archive_schema' in record:
                digest = record.get('archive_sha256')
                if (record['archive_schema'] != 'bridge.houdini.operation-archive-ref/1.0'
                        or record.get('task_id') != store.get('task_id')
                        or record.get('archive_family') != family
                        or record.get('archive_operation_id') != operation_id
                        or (record.get('operation_id') if family == 'scene_transitions' else record.get('request_id')) != operation_id
                        or record.get('state') not in {'COMPLETED', 'FAILED', 'CANCELLED', 'BUDGET_REACHED', 'SUPERSEDED'}
                        or type(digest) is not str or len(digest) != 64
                        or any(ch not in '0123456789abcdef' for ch in digest)):
                    raise ValueError('invalid terminal archive reference')
    intents = store.get("render_observation_intents", {})
    if type(intents) is not dict:
        raise ValueError("render observation intents must be a JSON object")
    for intent in intents.values():
        if (type(intent) is not dict or set(intent) != {"request_sha256", "budget"}
                or type(intent["request_sha256"]) is not str or len(intent["request_sha256"]) != 64
                or type(intent["budget"]) is not dict):
            raise ValueError("invalid render observation intent")
        FileReadBudget(intent["budget"])
    json_usage(store, max_bytes=MAX_STORE_BYTES, max_values=MAX_OPERATION_VALUES * 8)


def validate_preflight_attempt(path, *, task_id, operation_id, has_budget):
    if path.is_symlink():
        raise ValueError("preflight attempt must not be a symlink")
    if not path.exists():
        return
    attempt = json.loads(read_store_payload(path))
    if (type(attempt) is not dict or attempt.get("task_id") != task_id
            or attempt.get("request_id") != operation_id or not has_budget):
        raise ValueError("unreconciled preflight attempt has no matching durable read allowance")


class FileReadBudget:
    """Prepay each Python read durably; no refund after failure or restart."""
    def __init__(self, state=None, *, persist=None):
        if state is None:
            state = {"schema": FILE_BUDGET_SCHEMA, "used_bytes": 0}
        if (type(state) is not dict or set(state) != {"schema", "used_bytes"}
                or state["schema"] != FILE_BUDGET_SCHEMA or type(state["used_bytes"]) is not int
                or not 0 <= state["used_bytes"] <= MAX_FILE_READ_BYTES):
            raise ValueError("persisted OCIO read budget is missing or invalid")
        self.state, self.persist = state, persist

    def reserve(self, byte_count):
        if (type(byte_count) is not int or byte_count < 0
                or self.state["used_bytes"] + byte_count > MAX_FILE_READ_BYTES):
            raise RenderObservationLimit("render operation OCIO Python file-read budget exceeded")
        self.state["used_bytes"] += byte_count
        if self.persist is not None:
            self.persist()


class ConfigurationObservationBudget:
    """One allowance is shared by all frames in one configuration capture."""
    def __init__(self):
        self.color_bytes = self.color_values = 0
        self.configuration_bytes = self.configuration_values = 0

    def reserve_color(self, byte_count: int, value_count: int) -> None:
        if (self.color_bytes + byte_count > MAX_CONFIGURATION_BYTES
                or self.color_values + value_count > MAX_CONFIGURATION_VALUES):
            raise RenderObservationLimit("render all-frame color observation budget exceeded")
        self.color_bytes += byte_count
        self.color_values += value_count

    def reserve_configuration(self, value: dict[str, Any]) -> None:
        size, count = json_usage(value, max_bytes=MAX_CONFIGURATION_BYTES,
                                 max_values=MAX_CONFIGURATION_VALUES)
        if (self.configuration_bytes + size > MAX_CONFIGURATION_BYTES
                or self.configuration_values + count > MAX_CONFIGURATION_VALUES):
            raise RenderObservationLimit("render all-frame configuration observation budget exceeded")
        self.configuration_bytes += size
        self.configuration_values += count
