"""Observe an accepted creative result before a later failed attempt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dcc_task_runtime.native_scope import _accounting_lock
from dcc_task_runtime.owned_process import execution_returncode
from .official_karma_observation import checked_bytes


def completed_creative_prefix(scope, current, result_record, supervisor, operation_id):
    """Return only an authenticated, fully stopped original completion prefix.

    The current signed ledger and its failed suffix remain intact. This reader
    neither clears failure nor supplies a scope usable for new execution.
    """
    def reject(code='PREFIX_REQUIRED'):
        raise ValueError('CONTROLLED_OUTPUT_CREATIVE_HISTORY_' + code)
    result = json.loads(checked_bytes(result_record))
    phase = scope.scope.get('creative_phase')
    control = Path(str(result.get('control', '')))
    saved = result.get('scope', {})
    prefix = saved.get('tickets')
    if (not isinstance(phase, dict) or scope.scope.get('feedback_phase') is not None
            or current.get('closed_reason') != 'NATIVE_SCOPE_EXECUTION_FAILED'
            or result.get('schema') != 'bridge.hy3-creative-revision/1' or result.get('state') != 'COMPLETE'
            or result.get('task_id') != phase.get('task_id') or result.get('operation_id', '') + '_render' != operation_id
            or not control.is_absolute() or control != control.resolve() or not control.is_relative_to(scope.root)
            or Path(result_record['path']) != control.parent.parent/'result.json'
            or Path(supervisor['directory']).parent != control/'houdini-task-host'
            or saved.get('scope_sha256') != scope.binding['sha256'] or saved.get('closed_reason') is not None
            or type(prefix) is not list or not prefix or len(prefix) >= len(current['tickets'])
            or saved.get('dcc_starts') != len(prefix) or current['tickets'][:len(prefix)] != prefix
            or any(t.get('stopped_at') is None for t in current['tickets'])):
        reject()
    # The journal is authenticated against its anchor, then the candidate
    # prefix must occur as an original signed, open completion state.
    with _accounting_lock(scope.state_path):
        accounted, _, _ = scope._load_accounted()
        if accounted['tickets'] != current['tickets'] or accounted['closed_reason'] != current['closed_reason']:
            reject('STATE_CHANGED')
        journal = scope.journal_path.read_bytes()
        matched = False
        for line in journal.splitlines():
            state = scope._verify_envelope(json.loads(line))['state']
            if (state.get('scope_sha256') == scope.binding['sha256'] and state.get('closed_reason') is None
                    and state.get('tickets') == prefix):
                matched = True
        if not matched:
            reject('SIGNED_PREFIX_REQUIRED')
    completion_time = max(t['stopped_at'] for t in prefix)
    suffix = current['tickets'][len(prefix):]
    if any(t['admitted_at'] <= completion_time for t in suffix):
        reject('LATER_FAILURE_REQUIRED')
    stops = []
    stop_seals = []
    for ticket in current['tickets']:
        stop = scope._stop(ticket)
        if (not stop or ticket['stopped_at'] != stop.get('observed_at')
                or ticket.get('stopped_sha256') != hashlib.sha256(scope._canonical(stop)).hexdigest()):
            reject('SIGNED_STOP_REQUIRED')
        stop_seals.append(scope._canonical(stop))
        stops.append(json.loads(stop_seals[-1]))
    if not any(execution_returncode(stop) != 0 for stop in stops[len(prefix):]):
        reject('LATER_FAILURE_REQUIRED')
    hosts = [i for i, t in enumerate(prefix) if t['role'] == 'houdini-host' and t.get('parent') is None
             and t['directory'] == supervisor['directory'] and t['identity'] == supervisor['identity']]
    if len(hosts) != 1:
        reject('PRODUCER_REQUIRED')
    host = prefix[hosts[0]]
    husks = [i for i, t in enumerate(prefix) if t['role'] == 'main-husk' and t.get('parent') == host['id']
             and t['directory'] == supervisor['directory'] and t['identity'] == supervisor['identity']]
    nuke_operation = result.get('nuke', {}).get('operation_id')
    expected_nuke = 'nrend-' + hashlib.sha256((result['operation_id'] + '_nuke').encode()).hexdigest()[:16]
    nukes = [i for i, t in enumerate(prefix) if t['role'] == 'nuke-render'
             and t.get('identity', {}).get('operation_id') == nuke_operation]
    if (len(husks) != 1 or len(nukes) != 1 or nuke_operation != expected_nuke
            or any(execution_returncode(stops[i]) != 0 or stops[i].get('stop_reason') is not None
                   for i in hosts + husks + nukes)):
        reject('SUCCESSFUL_PRODUCERS_REQUIRED')
    charges = [max(t['charged_seconds'], t['stopped_at'] - t['admitted_at']) for t in prefix]
    base = scope._creative_base_state['tickets']
    if (prefix[:len(base)] != base or len(prefix) > scope.scope['budget']['max_dcc_starts']
            or len(prefix) - len(base) > scope.effective_creative_starts()
            or sum(charges) > scope.scope['budget']['total_seconds']
            or sum(charges[len(base):]) > phase['seconds']
            or any(charge > scope.role_seconds(ticket['role']) for ticket, charge in zip(prefix, charges))):
        reject('BUDGET_EXCEEDED')
    with _accounting_lock(scope.state_path):
        accounted, _, _ = scope._load_accounted()
        if (scope.journal_path.read_bytes() != journal or accounted['tickets'] != current['tickets']
                or accounted['closed_reason'] != current['closed_reason']):
            reject('STATE_CHANGED')
    checked_bytes(result_record)
    for ticket, sealed in zip(current['tickets'], stop_seals):
        if scope._canonical(scope._stop(ticket)) != sealed:
            reject('SIGNED_STOP_CHANGED')
    return prefix
