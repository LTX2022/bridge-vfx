"""Controller-only manual response handoff. No DCC dispatch or app automation.

CLI files are selected by the operator inside the generated control/inbox;
model tools cannot invoke this module, register authorization or supply paths.
A human-delivered response is not independent provider/transport attestation.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from .workbuddy_project import media_descriptor

MAX_RESPONSE_BYTES = 1024 * 1024


def response_contract(facade):
    if facade.trusted_execution is None:
        raise ValueError("trusted response collector is not configured")
    exported = facade.export()  # Validate the real connector event/receipt chain.
    observations = exported['observations']
    expected = set(facade.assets)
    video_observation_basis = {}
    for asset_id in expected:
        if media_descriptor(facade.assets[asset_id])['kind'] == 'video':
            recorded = [item['receipt'].get('media_basis') for item in observations if item['asset_id'] == asset_id]
            video_observation_basis[asset_id] = facade.validate_reference_media(
                asset_id, observed_basis=recorded[-1] if recorded else None)
        else:
            facade.media(asset_id)  # Rehash registered synthetic bytes; never trust the envelope.
    records = facade.trusted_execution.store.records(facade.pipeline_task_id, 'connector_observation_capture')
    matches = {}
    for observation in observations:
        receipt = observation['receipt']
        candidates = [row for row in records if row.get('run_id') == facade.run_id
                      and row.get('session_id') == facade.session_id and row.get('asset_id') == observation['asset_id']
                      and row.get('request_id') == receipt['request_id']]
        if len(candidates) != 1:
            raise ValueError("connector observation has not been captured by this controller")
        record = dict(candidates[0]); digest = record.pop('record_hash', None)
        if digest != canonical_sha256(record) or record['connector_receipt_hash'] != canonical_sha256(receipt):
            raise ValueError("connector observation capture no longer matches the actual receipt")
        matches[observation['asset_id']] = record['record_id']
    missing = sorted(expected - matches.keys())
    return {
        'task_id': facade.pipeline_task_id, 'run_id': facade.run_id, 'session_id': facade.session_id,
        'ready': not missing, 'missing_asset_observations': missing,
        'collection_mode': 'human_handoff', 'provider_identity_verified': False,
        'route_execution_verified': False, 'automated_collection': False,
        **({'video_observation_basis':video_observation_basis} if video_observation_basis else {}),
        'response_template': {
            'schema': 'bridge.workbuddy.reference_analysis_response/1.0',
            'route_id': 'WorkBuddyDesktopRoute', 'selected_model': 'HY3',
            'run_id': facade.run_id, 'session_id': facade.session_id,
            'tool_call_id': 'replace_with_stable_response_id',
            'observation_record_ids': [matches[key] for key in sorted(matches)],
            'analysis': {'components': [], 'global_observations': {}, 'confidence': 0.0},
        },
        'analysis_note': 'HY3 must supply its own typed reference analysis. The template is not a passing observation.',
    }


def _response_path_identity(path):
    identities = []
    for directory in (path.parent, *path.parent.parents):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('response path cannot traverse a link or reparse point')
        identities.append((info.st_dev, info.st_ino))
    return tuple(identities)


def _response_file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, 'st_file_attributes', 0))


def _read_windows_response(target):
    directories = _response_path_identity(target)
    before = target.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or getattr(before, 'st_file_attributes', 0) & 0x400):
        raise ValueError('response must be a regular non-linked file')
    if before.st_size > MAX_RESPONSE_BYTES:
        raise ValueError('response exceeds its size bound')
    descriptor = os.open(target, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        if _response_file_identity(os.fstat(stream.fileno())) != _response_file_identity(before):
            raise ValueError('response file changed before reading')
        raw = stream.read(MAX_RESPONSE_BYTES + 1)
        if (_response_file_identity(os.fstat(stream.fileno())) != _response_file_identity(before)
                or _response_file_identity(target.lstat()) != _response_file_identity(before)
                or _response_path_identity(target) != directories):
            raise ValueError('response file or directory changed during reading')
    return raw


def _read_response(root: Path, filename: str, expected_bytes: int, expected_sha256: str) -> bytes:
    if (not isinstance(filename, str) or Path(filename).name != filename
            or filename in {'', '.', '..'} or ':' in filename or '\\' in filename):
        raise ValueError('response must be a filename in control/inbox, not an arbitrary path')
    inbox = root / 'inbox'
    if inbox.is_symlink() or not inbox.is_dir():
        raise ValueError('control/inbox must be a regular controller directory')
    if type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_RESPONSE_BYTES:
        raise ValueError('expected response length must be between 1 and 1048576 bytes')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256 or ''):
        raise ValueError('expected response SHA256 must be supplied by the operator')
    target = inbox / filename
    if target.is_symlink():
        raise ValueError('response cannot be a symlink')
    if os.name == 'nt':
        raw = _read_windows_response(target)
    else:
        directory = os.open(inbox, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        try:
            if not stat.S_ISDIR(os.fstat(directory).st_mode):
                raise ValueError('control/inbox must be a regular controller directory')
            descriptor = os.open(filename, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
            with os.fdopen(descriptor, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('response must be a regular file')
                raw = stream.read(MAX_RESPONSE_BYTES + 1)
        finally:
            os.close(directory)
    if len(raw) != expected_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('raw response length/SHA256 mismatch: incomplete or changed handoff')
    return raw


def handoff_response(facade, *, filename, request_id, actor, expected_bytes, expected_sha256, confirm_complete):
    if not confirm_complete or not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
        raise ValueError('operator actor and explicit complete-response confirmation are required')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id or ''):
        raise ValueError('stable alphanumeric handoff request_id required')
    if facade.trusted_execution is None:
        raise ValueError('trusted response collector is not configured')
    pipeline = facade.trusted_execution.pipeline
    task_id = facade.pipeline_task_id
    with execution_lock(pipeline.database, task_id):
        contract = response_contract(facade)
        if not contract['ready']:
            raise ValueError('all registered images require actual connector observations before handoff')
        raw = _read_response(facade.root, filename, expected_bytes, expected_sha256)
        key = 'handoff_' + canonical_sha256({'task_id': task_id, 'request_id': request_id})
        request_hash = canonical_sha256({'task_id': task_id, 'run_id': facade.run_id, 'session_id': facade.session_id,
                                        'response_sha256': expected_sha256, 'actor': actor})
        prior = next((row for row in pipeline.store.records(task_id, 'manual_reference_handoff') if row['record_id'] == key), None)
        if prior:
            stored = dict(prior); digest = stored.pop('record_hash', None)
            if digest != canonical_sha256(stored) or stored['request_hash'] != request_hash:
                raise ValueError('handoff request_id is already bound to different bytes/actor or its record changed')
            if stored['state'] == 'SUBMITTED':
                return {**stored['result'], 'replayed': True}
            body = stored
        else:
            body = {'record_id': key, 'request_hash': request_hash, 'task_id': task_id, 'run_id': facade.run_id,
                    'session_id': facade.session_id, 'actor': actor, 'request_id': request_id,
                    'raw_response_base64': base64.b64encode(raw).decode('ascii'),
                    'raw_response_sha256': expected_sha256, 'raw_response_bytes': len(raw),
                    'human_intervention': True, 'automated_collection': False, 'state': 'RECEIVED'}
            pipeline.store.put_record(task_id, 'manual_reference_handoff', key, {**body, 'record_hash': canonical_sha256(body)})
        # Event-chain lookup makes replay/recovery idempotent even across a
        # crash between event append and handoff-record checkpoint.
        if not any(event['kind'] == 'human_semantic_help' and event['payload'].get('handoff_id') == key
                   for event in facade.export()['events']):
            facade.record_event('human_semantic_help', {'handoff_id': key, 'actor': actor,
                'reason': 'manual_raw_response_handoff', 'semantic_editing_claimed': False,
                'provider_identity_verified': False})
        config = {'route_id': 'WorkBuddyDesktopRoute', 'selected_model': 'HY3',
                  'collector': 'human_handoff', 'input_class': 'synthetic'}
        try:
            result = facade.capture_reference_analysis(raw, config, request_id, collection_mode='human_handoff')
        except Exception as exc:
            body.update(state='REJECTED_OR_INTERRUPTED', error_type=type(exc).__name__, error_message=str(exc))
            pipeline.store.put_record(task_id, 'manual_reference_handoff', key, {**body, 'record_hash': canonical_sha256(body)})
            raise
        result = {**result, 'handoff_id': key, 'task_id': task_id, 'run_id': facade.run_id,
                  'human_intervention': True, 'automated_collection': False,
                  'route_execution_verified': False, 'provider_identity_verified': False,
                  'real_workbuddy_acceptance': False, 'dcc_dispatched': False, 'replayed': False}
        body.update(state='SUBMITTED', result=result)
        body.pop('error_type', None); body.pop('error_message', None)
        pipeline.store.put_record(task_id, 'manual_reference_handoff', key, {**body, 'record_hash': canonical_sha256(body)})
        return result


def handoff_export(facade):
    exported = facade.export()
    if facade.trusted_execution is None:
        return {**exported, 'collector_configured': False, 'route_execution_verified': False}
    records = facade.trusted_execution.store.records(facade.pipeline_task_id, 'manual_reference_handoff')
    return {**exported, 'task_id': facade.pipeline_task_id, 'collector_configured': True,
            'human_handoffs': [{key: value for key, value in row.items() if key != 'raw_response_base64'} for row in records],
            'human_intervention_count': sum(event['kind'] == 'human_semantic_help' for event in exported['events']),
            'route_execution_verified': False, 'provider_identity_verified': False, 'real_workbuddy_acceptance': False}
