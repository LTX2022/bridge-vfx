"""Authenticate an interrupted cold reopen without granting any replay rights."""
import copy
import json
from pathlib import Path

from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import checked_bytes, file_record

from .geometry_session import GeometrySession


def _require(condition):
    if not condition:
        raise ValueError('GEOMETRY_COLD_CHECKPOINT_BINDING_INVALID')


def _read(record):
    return json.loads(checked_bytes(record))


def plan_for(original, plan_id, baseline):
    plan = copy.deepcopy(original)
    plan.update(schema='bridge.geometry-feedback-plan/1', plan_id=plan_id,
                parent_operation_id=baseline, baseline_operation_id=baseline)
    plan.pop('plan_sha256')
    plan['plan_sha256'] = canonical_sha256(plan)
    return plan


def records(session, operation):
    entry = session._read()['jobs'][operation]
    directory = Path(entry['directory'])
    return {'job': entry['job_file'], **{key: file_record(directory / name) for key, name in (
        ('journal', 'incremental-state.json'), ('error', 'error.json'),
        ('late_stop', 'late-stop-observation.json'), ('preparation', 'job-preparation.json'))}}


def inspect(payload, native, usage, *, verify_warm=False):
    """Require the original stopped cold attempt and the exact saved input."""
    checkpoint = payload['checkpoint']
    names = {'job': 'job.json', 'journal': 'incremental-state.json', 'error': 'error.json',
             'late_stop': 'late-stop-observation.json', 'preparation': 'job-preparation.json'}
    _require(set(checkpoint) == set(names))
    job = _read(checkpoint['job'])
    operation = job['operation_id']
    directory = native.root / 'jobs' / operation
    _require(Path(job['directory']) == directory
             and all(checkpoint[key]['path'] == str(directory / name) for key, name in names.items())
             and job['task_id'] == payload['task_id'] and job['revision'] == 2
             and job['schema'] == 'bridge.geometry-job/1'
             and job['preparation'] == payload['source_preparation']
             and plan_for(job['plan'], payload['plan']['plan_id'], payload['plan']['baseline_operation_id']) == payload['plan']
             and canonical_sha256({k: v for k, v in job['plan'].items() if k != 'plan_sha256'}) == job['plan']['plan_sha256']
             and not (directory / 'result.json').exists())
    error = _read(checkpoint['error'])
    _require(error['code'] == 'ENGINEERING_HOUDINI_STOP_UNKNOWN' and error['state'] == 'FAILED'
             and error['stop_confirmed'] is False and error['operation_id'] == operation
             and error['task_id'] == job['task_id'] and error['preparation_record'] == job['preparation'])
    # Reuse the original acceptance verifier, including its signed journal prefix.
    session = GeometrySession(Path(job['preparation']['path']))
    entry = session._read()['jobs'][operation]
    _require(entry['job_file'] == checkpoint['job'] and entry['state'] == 'FAILED'
             and entry.get('late_stop_observation') == checkpoint['late_stop'])
    stop = session._verify_late_stop(entry, job, checkpoint['error'], checkpoint['late_stop'])
    _require(stop['native_snapshot'] == usage and usage['closed_reason'] == 'NATIVE_SCOPE_EXECUTION_FAILED'
             and usage['tickets'] and usage['tickets'][-1]['role'] == 'houdini-host'
             and usage['dcc_starts'] + payload['budget']['max_dcc_starts'] <= native.scope['budget']['max_dcc_starts']
             and usage['total_seconds'] + payload['budget']['total_seconds'] <= native.scope['budget']['total_seconds'])
    preparation = _read(checkpoint['preparation'])
    history = directory / 'project/control'
    _require(preparation['job'] == checkpoint['job'] and preparation['control'] == str(history))
    journal = _read(checkpoint['journal'])
    stages = journal['stages']
    expected = {'baseline_reopen', 'save', 'warm_geometry', 'edit_host_stop', 'cold_reopen'}
    expected.update('feedback_' + str(i) for i in range(len(job['plan']['edits'])))
    _require(journal['job'] == checkpoint['job'] and set(stages) == expected
             and stages['cold_reopen']['state'] == 'INTENT'
             and all(stages[key]['state'] == 'DONE' for key in expected - {'cold_reopen'}))
    saved = stages['save']['result']
    hip = file_record(Path(saved['path']))
    _require(Path(hip['path']).parent == directory / 'project/saves'
             and hip['sha256'] == saved['sha256']
             and saved['scene_contract']['task_id'] == job['task_id'])
    warm = stages['warm_geometry']['result']
    if verify_warm:
        from .geometry_native_evidence import verify
        verify(warm, saved, native.binding, operation + '_warm', 'warm')
    if 'checkpoint_prior' in payload:
        _verify_stopped_replacement(payload, native, usage)
    return {'operation_id': operation, 'saved': saved, 'hip': hip, 'warm': warm,
            'history': str(history), 'scope': native.binding}


def _verify_stopped_replacement(payload, original, original_usage):
    """One explicit replacement after the cold observation rejected the same HIP."""
    from dcc_task_runtime.native_scope import NativeScope
    from .geometry_feedback import _execution_binding
    record = payload['checkpoint_prior']
    _require(set(record) == {'authority', 'job', 'error', 'journal'})
    _require('checkpoint_prior' not in _read(record['authority'])['payload'])
    previous, binding = _execution_binding(record['authority'])
    _require(previous.get('checkpoint') == payload['checkpoint']
             and 'checkpoint_prior' not in previous
             and previous['task_id'] == payload['task_id']
             and previous['project_id'] == payload['project_id']
             and previous['request_id'] != payload['request_id']
             and previous['plan']['plan_id'] != payload['plan']['plan_id'])
    prep = _read(binding['preparation'])
    prior = NativeScope(prep['scope'])
    job = _read(record['job'])
    directory = prior.root / 'jobs' / job['operation_id']
    _require(job['directory'] == str(directory) and job['task_id'] == payload['task_id']
             and job['preparation'] == binding['preparation']
             and job['feedback_authority'] == record['authority'] and job['plan'] == previous['plan']
             and all(record[key]['path'] == str(directory / name) for key, name in
                     (('job', 'job.json'), ('error', 'error.json'), ('journal', 'incremental-state.json')))
             and not (directory / 'result.json').exists())
    error, journal = _read(record['error']), _read(record['journal'])
    usage = prior.completed_snapshot()
    _require(error['code'] == 'TASK_PATH_OUTSIDE_ROOT' and error['stop_confirmed'] is True
             and error['state'] == 'FAILED' and error['operation_id'] == job['operation_id']
             and error['task_id'] == payload['task_id'] and error['preparation_record'] == job['preparation']
             and error['native_snapshot'] == usage and usage['closed_reason'] is None
             and [t['role'] for t in usage['tickets']] == ['houdini-host']
             and journal['job'] == record['job']
             and {k: v['state'] for k, v in journal['stages'].items()} ==
                 dict.fromkeys(('feedback_source', 'save', 'warm_geometry', 'cold_reopen'), 'DONE') |
                 {'cold_geometry': 'INTENT'}
             and original_usage['dcc_starts'] + usage['dcc_starts'] + payload['budget']['max_dcc_starts']
                 <= original.scope['budget']['max_dcc_starts']
             and original_usage['total_seconds'] + usage['total_seconds'] + payload['budget']['total_seconds']
                 <= original.scope['budget']['total_seconds'])
