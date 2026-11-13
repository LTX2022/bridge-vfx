"""Fixed two-slot native scope for the Capybara softbody shot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'bridge.softbody-shot-scope/1'
PROFILE = 'h21_capybara_softbody_shot_v1'
STEPS = {
    'B': (('shot-hython', 'build'), ('shot-hython', 'cold')),
    'C': (('shot-hython', 'layers'), ('shot-hython', 'cold')),
    'D': (('shot-hython', 'usd'), ('shot-husk', 'render')),
}
CEILINGS = {'B': (240, 240), 'C': (660, 240), 'D': (180, 900)}
FRAME_END = {'B': 60, 'C': 120, 'D': 120}


def _require(condition):
    if not condition:
        raise ValueError('SOFTBODY_SHOT_SCOPE_INVALID')


def role_for_step(step):
    return 'shot-husk' if step == 'render' else 'shot-hython'


def budget_for(phase, seconds, disk):
    _require(phase in STEPS and type(seconds) is list and len(seconds) == 2)
    _require(all(type(n) is int and 0 < n <= cap for n, cap in zip(seconds, CEILINGS[phase])))
    maximum_disk = 1024**3 if phase == 'B' else 8 * 1024**3
    _require(type(disk) is int and 0 < disk <= maximum_disk)
    return {'per_operation_seconds': max(seconds), 'total_seconds': sum(seconds),
            'max_dcc_starts': 2, 'max_disk_bytes': disk,
            'max_heavy_operations': 1, 'automatic_retries': 0}


def validate_scope(scope, path):
    from .native_scope import _plain, _reuse_record_bytes

    _require(set(scope) == {'schema', 'resource_profile', 'scope_id', 'task_id', 'output_root',
             'phase', 'version', 'execution_authorized', 'status', 'authorization',
             'budget', 'dispatch', 'accounting', 'evidence_source'})
    _require(scope['schema'] == SCHEMA and scope['resource_profile'] == PROFILE
             and scope['version'] == '21.0.631' and scope['execution_authorized'] is True
             and scope['status'] == 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
             and scope['evidence_source'] == 'real_host')
    phase = scope['phase']
    root = _plain(scope['output_root'])
    _require(phase in STEPS and Path(path) == root/'scope.json'
             and scope['task_id'] == 'softbody-tear-capybara'
             and scope['scope_id'] == root.name and re.fullmatch(phase + r'-0[1-3]', root.name))
    _require(scope['authorization'] == {'authority': 'current_user_instruction',
             'instruction': 'Run the independently reviewed Capybara shot plan within the fixed stop limits.'})
    _require(scope['dispatch']['path'] == str(root/'dispatch.json'))
    plan = json.loads(_reuse_record_bytes(scope['dispatch']))
    fields = {'schema', 'phase', 'scope_id', 'root', 'source', 'frames', 'steps', 'disk',
              'worker', 'supervisor', 'hython', 'husk', 'review', 'parameters'}
    _require(set(plan) in (fields, fields | {'kinefx'}))
    _require(plan['schema'] == 'bridge.softbody-shot-dispatch/1' and plan['phase'] == phase
             and plan['scope_id'] == root.name and plan['root'] == str(root)
             and plan['frames'] == [1, FRAME_END[phase]] and len(plan['steps']) == 2)
    _require(plan['worker']['path'] == str(root/'worker.py'))
    _require(plan['parameters']['path'] == str(root/'parameters.json'))
    for field in ('worker', 'review', 'supervisor', 'hython', 'husk', 'parameters'):
        _reuse_record_bytes(plan[field])
    if 'kinefx' in plan:
        directory = Path(plan['hython']['path']).parents[1]/'packages/kinefx'
        _require([item['path'] for item in plan['kinefx']] ==
                 [str(directory/'otls/OPlibKineFX.hda'), str(directory/'dso/kinefx.dylib')])
        for item in plan['kinefx']:
            _reuse_record_bytes(item)
    parameters = json.loads(_reuse_record_bytes(plan['parameters']))
    _require(set(parameters) == {'schema', 'tuning'}
             and parameters['schema'] == 'bridge.softbody-shot-parameters/1'
             and type(parameters['tuning']) is int and 0 <= parameters['tuning'] <= 2)
    if phase == 'B':
        _require(plan['source'] is None)
    else:
        _require(plan['source']['path'] == str(root/'source.json'))
        _reuse_record_bytes(plan['source'])
    roles = {}
    seconds = {}
    for i, (entry, (role, step)) in enumerate(zip(plan['steps'], STEPS[phase]), 1):
        _require(set(entry) == {'role', 'step', 'seconds', 'directory', 'argv'})
        _require(entry['role'] == role and entry['step'] == step
                 and entry['directory'] == str(root/f'supervisor-{i}'))
        argv = [plan['hython']['path'], '-B', plan['worker']['path'], step, str(root/'dispatch.json')]
        if role == 'shot-husk':
            argv = [plan['husk']['path'], '-f', '1', '-n', '120', '-i', '1',
                    '-o', str(root/'frames/shot.$F4.exr'), str(root/'shot.usd')]
        _require(entry['argv'] == argv)
        roles[role] = roles.get(role, 0) + 1
        seconds[role] = max(seconds.get(role, 0), entry['seconds'])
    budget = budget_for(phase, [entry['seconds'] for entry in plan['steps']], plan['disk'])
    _require(scope['budget'] == budget)
    return plan, budget, roles, seconds


def check_step(scope, directory, spec):
    """Check the reserved slot and command before the supervisor spawns the DCC."""
    plan, *_ = validate_scope(scope.scope, scope.path)
    ticket = spec.get('native_scope_ticket', {})
    steps = [step for step in plan['steps'] if step['directory'] == str(directory)]
    _require(len(steps) == 1)
    step = steps[0]
    _require(ticket.get('role') == step['role'] and ticket.get('directory') == str(directory)
             and spec['command'] == step['argv'] and spec['budget_seconds'] == step['seconds']
             and spec['resource_budget'] == {'roots': [plan['root']], 'max_bytes': plan['disk'],
                                             'native_scope': scope.binding})
    usage = scope.snapshot()
    index = plan['steps'].index(step)
    _require(len(usage['tickets']) == index + 1 and usage['tickets'][-1]['id'] == ticket['id']
             and all(ticket['stopped_at'] is not None for ticket in usage['tickets'][:-1]))
    _require(spec['identity'] == ticket['identity']
             and spec['identity']['task_id'] == scope.scope['task_id']
             and spec['identity']['operation_id'] == plan['scope_id'] + '-' + step['step'])
    if 'kinefx' in plan:
        _require(spec['env'].get('HOUDINI_PATH') == str(Path(plan['kinefx'][0]['path']).parents[1])+':&'
                 and spec['env'].get('HOUDINI_PACKAGE_SKIP') == '1')
    # Prohibit bypass of the sealed attempt by reusing a supervisor directory.
    _require(hashlib.sha256((Path(directory)/'intent.json').read_bytes()).hexdigest()
             == hashlib.sha256(scope._canonical(spec)).hexdigest())
