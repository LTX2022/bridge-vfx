"""Bounded snapshots and immutable terminal-history maintenance.

Maintenance never infers a stop or changes an operation result. Archive files
are committed before the compact snapshot, so an interrupted compaction leaves
an intact old snapshot or a complete set of immutable references.
"""
from __future__ import annotations

import hashlib
import codecs
import json
import os
from pathlib import Path
import stat
import shutil

from . import render_observation_budget as budget

ARCHIVE_SCHEMA = 'bridge.houdini.operation-archive-ref/1.0'
TERMINAL = frozenset({'COMPLETED', 'FAILED', 'CANCELLED', 'BUDGET_REACHED', 'SUPERSEDED'})
MAX_MAINTENANCE_BYTES = 512 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON member')
        result[key] = value
    return result


def _sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


ACTIVE = frozenset({'QUEUED', 'RUNNING', 'CANCEL_PENDING', 'RECONCILE', 'INTENT'})
FAMILIES = frozenset({'operations', 'scene_transitions'})


def _records(store):
    for family in FAMILIES:
        yield from store.get(family, {}).values()


def _record_identity(record, operation_id, family):
    if family == 'scene_transitions':
        return (record.get('schema') == 'bridge.houdini.scene-transition-operation/1.0'
                and record.get('operation_id') == operation_id
                and type(record.get('request_id')) is str and bool(record['request_id']))
    return (family == 'operations' and record.get('request_id') == operation_id
            and record.get('schema') != 'bridge.houdini.scene-transition-operation/1.0')


def encoded_store(store):
    budget.validate_store(store)
    payload = json.dumps(store, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    values = budget.json_usage(store, max_bytes=budget.MAX_STORE_BYTES,
                               max_values=budget.MAX_OPERATION_VALUES * 8)[1]
    reserved_bytes = reserved_values = 0
    for record in _records(store):
        size, count = budget.json_usage(record, max_bytes=budget.MAX_OPERATION_BYTES,
                                        max_values=budget.MAX_OPERATION_VALUES)
        if record.get('state') in ACTIVE:
            reserved_bytes += budget.MAX_OPERATION_BYTES - size
            reserved_values += budget.MAX_OPERATION_VALUES - count
    # Historical intents retain cumulative same-ID read allowances. Reserve
    # one allowance independently of active completions so a terminal state
    # cannot suddenly add capacity that its accepted INTENT did not reserve.
    if store.get('render_observation_intents'):
        reserved_bytes += budget.MAX_OPERATION_BYTES
        reserved_values += budget.MAX_OPERATION_VALUES
    if (len(payload) + reserved_bytes > budget.MAX_STORE_BYTES
            or values + reserved_values > budget.MAX_OPERATION_VALUES * 8):
        raise budget.RenderObservationLimit('operation store lacks reserved terminal capacity; compact terminal history through control.resolve compact_store')
    return payload


def write_snapshot(path, store):
    from dcc_task_runtime.platform_support import atomic_write
    payload = encoded_store(store)
    atomic_write(Path(path), payload, owned_root=Path(path).parent)


def resolve_record(path, store, operation_id, *, family='operations'):
    if family not in FAMILIES:
        raise ValueError('unknown operation archive family')
    reference = store.get(family, {}).get(operation_id)
    if not reference or reference.get('archive_schema') != ARCHIVE_SCHEMA:
        return reference
    digest = reference.get('archive_sha256', '')
    if (not isinstance(digest, str) or len(digest) != 64
            or any(ch not in '0123456789abcdef' for ch in digest)
            or reference.get('state') not in TERMINAL
            or reference.get('archive_family') != family
            or reference.get('archive_operation_id') != operation_id):
        raise ValueError('invalid terminal archive reference')
    from dcc_task_runtime.platform_support import _plain_path
    archive = _plain_path(Path(path).with_name(Path(path).name + '.archive') / (digest + '.json'))
    raw = _read_bounded(archive, budget.MAX_OPERATION_BYTES)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('operation archive content hash differs')
    record = json.loads(raw, object_pairs_hook=_unique_object)
    budget.json_usage(record, max_bytes=budget.MAX_OPERATION_BYTES, max_values=budget.MAX_OPERATION_VALUES)
    if (type(record) is not dict or any(record.get(key) != reference.get(key)
            for key in ('task_id', 'operation_id', 'request_id', 'request_sha256', 'kind', 'state', 'slot'))
            or record.get('task_id') != store.get('task_id')
            or not _record_identity(record, operation_id, family)):
        raise ValueError('operation archive identity differs')
    return record


def _read_bounded(path, limit):
    from dcc_task_runtime.platform_support import _plain_path
    path = _plain_path(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('operation store must be a regular file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise budget.RenderObservationLimit('operation archive exceeds per-record budget')
    return raw


class _JsonStream:
    """Decode one bounded member at a time without loading a historical store."""
    def __init__(self, stream):
        self.stream, self.buffer, self.eof = stream, '', False
        self.decoder = json.JSONDecoder(object_pairs_hook=_unique_object)

    def fill(self):
        part = self.stream.read(65536)
        self.buffer += part
        self.eof = not part

    def whitespace(self):
        while True:
            self.buffer = self.buffer.lstrip()
            if self.buffer or self.eof:
                return
            self.fill()

    def token(self, expected):
        self.whitespace()
        if not self.buffer.startswith(expected):
            raise ValueError('invalid historical store JSON structure')
        self.buffer = self.buffer[len(expected):]

    def value(self):
        self.whitespace()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
                # A number at a buffer boundary may be only its prefix.
                partial_number = (type(value) in {int, float} and end < len(self.buffer)
                                  and self.buffer[end] in '.eE+-0123456789')
                if (end == len(self.buffer) or partial_number) and not self.eof:
                    if len(self.buffer) > budget.MAX_OPERATION_BYTES:
                        raise budget.RenderObservationLimit('historical store number exceeds parser budget')
                    self.fill()
                    continue
                self.buffer = self.buffer[end:]
                budget.json_usage(value, max_bytes=budget.MAX_OPERATION_BYTES,
                                   max_values=budget.MAX_OPERATION_VALUES)
                return value
            except json.JSONDecodeError:
                if self.eof:
                    raise
                if len(self.buffer) > budget.MAX_OPERATION_BYTES:
                    raise budget.RenderObservationLimit('historical store member exceeds bounded maintenance parser')
                self.fill()

    def members(self):
        self.token('{')
        seen = set()
        self.whitespace()
        if self.buffer.startswith('}'):
            self.token('}')
            return
        while True:
            name = self.value()
            if type(name) is not str or name in seen:
                raise ValueError('historical store has invalid or duplicate keys')
            seen.add(name)
            if len(seen) > budget.MAX_OPERATION_VALUES * 8:
                raise budget.RenderObservationLimit('maintenance key count exceeded')
            self.token(':')
            yield name
            self.whitespace()
            if self.buffer.startswith('}'):
                self.token('}')
                return
            self.token(',')


class _VerifiedMaintenanceReader:
    def __init__(self, path, expected_digest):
        from dcc_task_runtime.platform_support import _plain_path
        path = _plain_path(path)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        self.stream = os.fdopen(os.open(path, flags), 'rb')
        self.before = os.fstat(self.stream.fileno())
        if not stat.S_ISREG(self.before.st_mode) or self.before.st_size > MAX_MAINTENANCE_BYTES:
            self.stream.close()
            raise budget.RenderObservationLimit('maintenance snapshot exceeds bounded regular-file allowance')
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.digest, self.expected_digest = hashlib.sha256(), expected_digest
        self.bytes_read, self.eof = 0, False

    def read(self, size):
        while not self.eof:
            raw = self.stream.read(min(size, MAX_MAINTENANCE_BYTES - self.bytes_read + 1))
            self.bytes_read += len(raw)
            if self.bytes_read > MAX_MAINTENANCE_BYTES:
                raise budget.RenderObservationLimit('maintenance snapshot grew beyond read allowance')
            self.digest.update(raw)
            self.eof = not raw
            text = self.decoder.decode(raw, final=self.eof)
            if text or self.eof:
                return text
        return ''

    def verify(self):
        after = os.fstat(self.stream.fileno())
        if (not self.eof or self.digest.hexdigest() != self.expected_digest
                or (self.before.st_size, self.before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise ValueError('maintenance snapshot changed while parsed')

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.stream.close()


def _digest(path, copy_to=None):
    from dcc_task_runtime.platform_support import _plain_path
    path = _plain_path(path)
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('historical store must be a regular file')
        read_size = 0
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            read_size += len(chunk)
            if read_size > MAX_MAINTENANCE_BYTES:
                raise budget.RenderObservationLimit('store grew beyond bounded maintenance input allowance')
            digest.update(chunk)
            if copy_to is not None:
                copy_to.write(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('historical store changed while observed')
    return digest.hexdigest()


def compact_store(path, task_id):
    """Caller holds the task execution lock and verifies control authorization."""
    from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory, open_private_file, _plain_path
    from uuid import uuid4
    path = _plain_path(path)
    source_size = path.stat().st_size
    if source_size > MAX_MAINTENANCE_BYTES:
        raise budget.RenderObservationLimit('store exceeds bounded maintenance input allowance')
    if shutil.disk_usage(path.parent).free < 3 * source_size + budget.MAX_STORE_BYTES:
        raise budget.RenderObservationLimit('insufficient disk budget for immutable maintenance backup and archives')
    directory = path.with_name(path.name + '.archive')
    if directory.is_symlink():
        raise ValueError('archive directory cannot be a symlink')
    ensure_private_directory(directory)
    temporary = directory / ('snapshot-' + uuid4().hex + '.pending')
    try:
        with os.fdopen(open_private_file(temporary), 'wb') as stream:
            source_sha256 = _digest(path, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    backup = directory / ('snapshot-' + source_sha256 + '.json')
    if backup.exists():
        if _digest(backup) != source_sha256:
            raise ValueError('immutable store backup differs')
        temporary.unlink()
    else:
        os.replace(temporary, backup)
    result, archived = {}, 0
    index_bytes, index_values = 2, 1
    reserved_bytes = reserved_values = 0
    def account(name, value, *, operation=False):
        nonlocal index_bytes, index_values, reserved_bytes, reserved_values
        size, count = budget.json_usage(value, max_bytes=budget.MAX_OPERATION_BYTES,
                                        max_values=budget.MAX_OPERATION_VALUES)
        key_bytes, key_count = budget.json_usage(name, max_bytes=budget.MAX_OPERATION_BYTES,
                                                max_values=budget.MAX_OPERATION_VALUES)
        index_bytes += size + key_bytes + 2
        index_values += count + key_count
        if operation and value.get('state') in ACTIVE:
            reserved_bytes += budget.MAX_OPERATION_BYTES - size
            reserved_values += budget.MAX_OPERATION_VALUES - count
        elif (not operation and name == 'render_observation_intents' and type(value) is dict and value):
            reserved_bytes += budget.MAX_OPERATION_BYTES
            reserved_values += budget.MAX_OPERATION_VALUES
        if (index_bytes + reserved_bytes > budget.MAX_STORE_BYTES
                or index_values + reserved_values > budget.MAX_OPERATION_VALUES * 8):
            raise budget.RenderObservationLimit('compact operation index exceeds reserved capacity')
    with _VerifiedMaintenanceReader(backup, source_sha256) as stream:
        parser = _JsonStream(stream)
        for key in parser.members():
            if key not in FAMILIES:
                value = parser.value()
                account(key, value)
                result[key] = value
                continue
            account(key, {})
            family = key
            operations = result[family] = {}
            for operation_id in parser.members():
                record = parser.value()
                if (type(record) is not dict or record.get('task_id') != task_id
                        or not (record.get('archive_schema') == ARCHIVE_SCHEMA
                                or _record_identity(record, operation_id, family))):
                    raise ValueError('historical operation identity differs')
                if record.get('archive_schema') == ARCHIVE_SCHEMA:
                    resolve_record(path, {'task_id': task_id, family: {operation_id: record}}, operation_id, family=family)
                elif record.get('state') in TERMINAL:
                    raw = json.dumps(record, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')
                    digest = hashlib.sha256(raw).hexdigest()
                    destination = directory / (digest + '.json')
                    if destination.exists():
                        if _read_bounded(destination, budget.MAX_OPERATION_BYTES) != raw:
                            raise ValueError('immutable operation archive differs')
                    else:
                        atomic_write(destination, raw, owned_root=directory)
                    record = {key: record.get(key) for key in
                              ('task_id', 'operation_id', 'request_id', 'request_sha256', 'kind', 'state', 'slot')}
                    record.update(archive_schema=ARCHIVE_SCHEMA, archive_sha256=digest,
                                  archive_family=family, archive_operation_id=operation_id)
                    archived += 1
                account(operation_id, record, operation=True)
                operations[operation_id] = record
        parser.whitespace()
        if parser.buffer or not parser.eof:
            raise ValueError('historical store contains trailing data')
        stream.verify()
    if result.get('task_id') != task_id:
        raise ValueError('historical store belongs to another task')
    encoded_store(result)
    if _digest(path) != source_sha256:
        raise ValueError('operation store changed before maintenance commit')
    _sync_directory(directory)
    _sync_directory(path.parent)
    write_snapshot(path, result)
    _sync_directory(path.parent)
    return {'archived_operations': archived, 'source_sha256': source_sha256,
            'preserved_snapshot': str(backup), 'operation_store_path': str(path)}
