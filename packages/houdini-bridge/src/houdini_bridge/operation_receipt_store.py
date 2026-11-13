"""Private per-operation files; callers hold the existing runner task lock.

This module stores the producer's unchanged receipt schema and facts. It never
executes an operation, acquires a second lock, reads the legacy taskstore, or
creates a receipt digest. Legacy lookup/admission remains with the caller.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from dcc_task_runtime import platform_support
from .operation_receipts import validate_operation_receipt


def record_path(runner_path: Path, task_id: str, operation_id: str) -> Path:
    """Return a strict owned path without creating directories or following links."""
    runner = Path(runner_path)
    if not runner.is_absolute():
        raise ValueError('PRODUCER_STORE_ABSOLUTE_RUNNER_REQUIRED')
    if not isinstance(task_id, str) or not task_id or '\x00' in task_id:
        raise ValueError('PRODUCER_STORE_TASK_REQUIRED')
    if not isinstance(operation_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', operation_id):
        raise ValueError('PRODUCER_STORE_BOUNDED_OPERATION_REQUIRED')
    runner = platform_support._owned_path(runner, runner.parent)
    task_digest = hashlib.sha256(task_id.encode('utf-8')).hexdigest()
    operation_digest = hashlib.sha256(operation_id.encode('utf-8')).hexdigest()
    path = runner.parent / 'producer-records' / task_digest / (operation_digest + '.json')
    return platform_support._owned_path(path, runner.parent)


def _validate_record(record: dict[str, Any], task_id: str, operation_id: str) -> None:
    if not isinstance(record, dict) or record.get('task_id') != task_id or record.get('operation_id') != operation_id:
        raise ValueError('PRODUCER_STORE_RECORD_BINDING_MISMATCH')
    validate_operation_receipt(record, require_completed=False)


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('PRODUCER_STORE_DUPLICATE_JSON_KEY')
        result[name] = value
    return result


def load_record(runner_path: Path, task_id: str, operation_id: str) -> dict[str, Any] | None:
    """Read only this operation; missing is None, corrupt/unowned is an error."""
    path = record_path(runner_path, task_id, operation_id)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, 'rb') as stream:
        if not platform_support.private_permissions_valid(path, file_descriptor=stream.fileno()):
            raise ValueError('PRODUCER_STORE_FILE_NOT_PRIVATE')
        record = json.loads(stream.read().decode('utf-8'), object_pairs_hook=_unique_object)
    _validate_record(record, task_id, operation_id)
    return record


def write_record(runner_path: Path, task_id: str, operation_id: str,
                 record: dict[str, Any], *, expected: dict[str, Any] | None = None) -> Path:
    """Under runner._locked(), create INTENT or CAS that exact INTENT to terminal.

    No existing record can be replaced by a fresh intention or a migration.
    The caller retains incomplete-attempt refusal and legacy compatibility.
    """
    path = record_path(runner_path, task_id, operation_id)
    _validate_record(record, task_id, operation_id)
    prior = load_record(runner_path, task_id, operation_id)
    if expected is None:
        if prior is not None or record['state'] != 'INTENT':
            raise ValueError('PRODUCER_STORE_INTENT_ALREADY_EXISTS_OR_REQUIRED')
    else:
        if (prior is None or prior != expected or prior['state'] != 'INTENT'
                or record['state'] not in {'COMPLETED', 'FAILED'}
                or any(record.get(name) != value for name, value in prior.items()
                       if name not in {'state', 'operation_receipt_sha256'})):
            raise ValueError('PRODUCER_STORE_INTENT_TRANSITION_MISMATCH')
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    platform_support.ensure_private_directory(path.parent.parent)
    platform_support.ensure_private_directory(path.parent)
    platform_support.atomic_write(path, payload, owned_root=Path(runner_path).parent)
    return path
