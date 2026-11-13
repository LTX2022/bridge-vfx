#!/usr/bin/env python3
"""Operator entry for the isolated, independently reviewed Capybara shot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'packages/dcc-task-runtime/src'))

from dcc_task_runtime import owned_process
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory
from dcc_task_runtime.softbody_shot_scope import SCHEMA, PROFILE, STEPS, CEILINGS, FRAME_END, budget_for

VERSION = '21.0.631'
TASK = 'softbody-tear-capybara'
HFS = Path('/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources')
KINEFX = HFS/'packages/kinefx'
REVIEW_ROOT = ROOT/'outputs/Bridge-softbody-tear-v2-20261107'
REVIEW = REVIEW_ROOT/'执行计划.md'
CASE = REVIEW_ROOT/'run'
ATTEMPT_CAP = {'B': 3, 'C': 2, 'D': 2}
MAX_STARTS = 14
MAX_SECONDS = 5400
MAX_DISK = 8 * 1024**3
MAX_WALL = 8 * 3600
STOP_RESERVE = 20
AUTHORIZATION = {'authority': 'current_user_instruction',
    'instruction': 'Run the independently reviewed Capybara shot plan within the fixed stop limits.'}
WORKER = ROOT/'tools/softbody_shot_worker.py'
REVIEW_START = datetime(2026, 11, 7, 6, 57, 17, tzinfo=timezone.utc).timestamp()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_record(raw):
    path = Path(raw)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'SHOT_PLAIN_FILE_REQUIRED')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    require(before.st_size > 0 and before.st_nlink == 1 and
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'SHOT_FILE_CHANGED')
    return {'path': str(path), 'bytes': before.st_size, 'sha256': digest}


def verify_record(record):
    require(file_record(record['path']) == record, 'SHOT_FROZEN_FILE_CHANGED')
    return Path(record['path'])


def write(path, data):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), 'SHOT_RECORD_ALREADY_EXISTS')
    atomic_write(path, NativeScope._canonical(data), owned_root=path.parent)
    return file_record(path)


def read(path):
    path = Path(path)
    require(path.resolve() == path and not path.is_symlink(), 'SHOT_PLAIN_FILE_REQUIRED')
    return json.loads(path.read_bytes())


def binding(path):
    row = file_record(path)
    return {key: row[key] for key in ('path', 'sha256')}


def signature(native, body):
    return hmac.new(native._key(), b'bridge.softbody-attempt-result/1\x00' +
                    NativeScope._canonical(body), hashlib.sha256).hexdigest()


def disk_used(path):
    return owned_process._disk_usage({'roots': [str(path)], 'max_bytes': MAX_DISK})


def terminal(native, usage, state, error=None, files=None):
    body = {'schema': 'bridge.softbody-attempt-result/1', 'scope': native.binding,
            'state': state, 'usage': usage, 'error': error, 'files': files or {}}
    write(native.root/'terminal.json', {'payload': body, 'signature': signature(native, body)})
    return body


def summarize(case):
    rows = []
    attempts = case/'attempts'
    for directory in sorted(attempts.iterdir()):
        require(directory.is_dir() and not directory.is_symlink(), 'SHOT_ATTEMPT_DIRECTORY_INVALID')
        require((directory/'dispatch.json').is_file(), 'SHOT_INCOMPLETE_INTENT')
        native = NativeScope(binding(directory/'scope.json'))
        record = read(directory/'terminal.json') if (directory/'terminal.json').is_file() else None
        usage = native.snapshot()
        if record is None:
            rows.append({'attempt': directory.name, 'state': 'UNKNOWN', 'usage': usage})
            continue
        result = record['payload']
        require(hmac.compare_digest(record['signature'], signature(native, result))
                and result['scope'] == native.binding, 'SHOT_TERMINAL_SIGNATURE_INVALID')
        for field in ('dcc_starts', 'total_seconds', 'tickets', 'closed_reason'):
            require(result['usage'][field] == usage[field], 'SHOT_NATIVE_LEDGER_CHANGED')
        for ticket in usage['tickets']:
            require(ticket['stopped_at'] is not None and native._stop(ticket) is not None,
                    'SHOT_PRIOR_STOP_UNKNOWN')
        rows.append({'attempt': directory.name, **result})
    return {'attempts': rows, 'attempt_count': len(rows),
            'starts': sum(row['usage']['dcc_starts'] for row in rows),
            'seconds': sum(row['usage']['total_seconds'] for row in rows),
            'disk_bytes': disk_used(case)}


def next_parameters(summary, phase, start):
    require(phase in ATTEMPT_CAP, 'SHOT_PHASE_INVALID')
    require(all(row['state'] in ('PASS', 'FAILED') for row in summary['attempts']),
            'SHOT_PRIOR_STOP_OR_COMPLETION_UNKNOWN')
    existing = [row for row in summary['attempts'] if row['attempt'].startswith(phase)]
    require(not any(row['state'] == 'PASS' for row in existing), 'SHOT_PHASE_ALREADY_ACCEPTED')
    require(len(existing) < ATTEMPT_CAP[phase] and summary['attempt_count'] < sum(ATTEMPT_CAP.values()),
            'SHOT_ATTEMPT_LIMIT')
    require(summary['starts'] + 2 <= MAX_STARTS, 'SHOT_START_LIMIT')
    seconds = list(CEILINGS[phase])
    require(summary['seconds'] + sum(seconds) <= MAX_SECONDS, 'SHOT_NATIVE_TIME_LIMIT')
    require(0 <= time.time() - start and time.time() - start + sum(seconds) + STOP_RESERVE < MAX_WALL,
            'SHOT_WALL_LIMIT')
    disk = min(1024**3 if phase == 'B' else MAX_DISK, MAX_DISK - summary['disk_bytes'] - 8*1024**2)
    require(disk >= 128*1024**2, 'SHOT_DISK_LIMIT')
    return phase + '-0' + str(len(existing) + 1), seconds, disk


def make_scope(directory, phase, seconds, disk, review, source=None, tuning=0):
    ensure_private_directory(directory, exist_ok=False)
    program = directory/'worker.py'
    shutil.copyfile(WORKER, program)
    verify_record(review)
    if phase != 'B':
        source_record = write(directory/'source.json', source)
    else:
        source_record = None
    hython = file_record(HFS/'bin/hython')
    husk = file_record(HFS/'bin/husk')
    steps = []
    for index, ((role, step), duration) in enumerate(zip(STEPS[phase], seconds), 1):
        argv = [hython['path'], '-B', str(program), step, str(directory/'dispatch.json')]
        if role == 'shot-husk':
            argv = [husk['path'], '-f', '1', '-n', '120', '-i', '1', '-o',
                    str(directory/'frames/shot.$F4.exr'), str(directory/'shot.usd')]
        steps.append({'role': role, 'step': step, 'seconds': duration,
                      'directory': str(directory/f'supervisor-{index}'), 'argv': argv})
    write(directory/'parameters.json', {'schema': 'bridge.softbody-shot-parameters/1', 'tuning': tuning})
    plan = {'schema': 'bridge.softbody-shot-dispatch/1', 'phase': phase, 'scope_id': directory.name,
            'root': str(directory), 'source': source_record, 'frames': [1, FRAME_END[phase]],
            'steps': steps, 'disk': disk, 'worker': file_record(program),
            'supervisor': file_record(Path(sys.executable).resolve()), 'hython': hython, 'husk': husk,
            'review': review, 'parameters': file_record(directory/'parameters.json'),
            'kinefx': [file_record(KINEFX/'otls/OPlibKineFX.hda'),
                       file_record(KINEFX/'dso/kinefx.dylib')]}
    dispatch = write(directory/'dispatch.json', plan)
    key = secrets.token_bytes(32)
    scope = {'schema': SCHEMA, 'resource_profile': PROFILE, 'scope_id': directory.name,
             'task_id': TASK, 'output_root': str(directory), 'phase': phase, 'version': VERSION,
             'execution_authorized': True, 'status': 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION',
             'authorization': AUTHORIZATION, 'budget': budget_for(phase, seconds, disk),
             'dispatch': dispatch, 'evidence_source': 'real_host',
             'accounting': {'key_path': str(directory/'.native-control/key'),
                            'key_sha256': hashlib.sha256(key).hexdigest()}}
    write(directory/'scope.json', scope)
    native = NativeScope.initialize(binding(directory/'scope.json'), key=key)
    return plan, native


def environment(root):
    paths = {key: root/'runtime'/key for key in ('tmp', 'config', 'cache', 'houdini-prefs-21.0')}
    for value in paths.values():
        ensure_private_directory(value)
    result = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
    result.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='en_US.UTF-8', TZ='UTC',
                  PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                  HOUDINI_USER_PREF_DIR=str(root/'runtime/houdini-prefs-__HVER__'),
                  HOUDINI_TEMP_DIR=str(paths['tmp']), TMPDIR=str(paths['tmp']),
                  XDG_CACHE_HOME=str(paths['cache']), XDG_CONFIG_HOME=str(paths['config']),
                  HOUDINI_PACKAGE_SKIP='1', HOUDINI_PATH=str(KINEFX)+':&', HOUDINI_MAXTHREADS='8')
    return result


def run_step(native, plan, step):
    verify_record(native.scope['dispatch'])
    for field in ('worker', 'review', 'parameters', 'supervisor', 'hython', 'husk'):
        verify_record(plan[field])
    if plan['source'] is not None:
        verify_record(plan['source'])
    identity = {'task_id': TASK, 'operation_id': plan['scope_id'] + '-' + step['step'],
                'launch_nonce': secrets.token_hex(16)}
    directory = Path(step['directory'])
    handle = None
    try:
        handle = owned_process.launch(step['argv'], directory=directory, identity=identity,
            supervisor_executable=plan['supervisor']['path'], env=environment(native.root),
            budget_seconds=step['seconds'], scope_role=step['role'],
            resource_budget={'roots': [plan['root']], 'max_bytes': plan['disk'], 'native_scope': native.binding})
        print(f"{plan['scope_id']} {step['step']} STARTED {handle.pid}", flush=True)
        code = handle.wait(timeout=step['seconds'] + STOP_RESERVE)
        require(code == 0, f"SHOT_NATIVE_STEP_FAILED:{step['step']}:{code}")
    except BaseException:
        if handle is not None and handle.poll() is None:
            handle.terminate()
            handle.wait(timeout=STOP_RESERVE)
        elif directory.is_dir() and owned_process.read_receipt(directory, 'stopped', identity=identity) is None:
            owned_process._atomic(directory/'cancel.json', {'identity': identity})
            deadline = time.monotonic() + STOP_RESERVE
            while time.monotonic() < deadline and owned_process.read_receipt(directory, 'stopped', identity=identity) is None:
                time.sleep(.2)
        raise
    finally:
        # Reconciliation records actual, signed stops; a missing proof leaves the ticket active.
        native.check()


def create_case():
    ensure_private_directory(CASE, exist_ok=False)
    ensure_private_directory(CASE/'attempts', exist_ok=False)
    write(CASE/'review.json', {'state': 'PASS', 'reviewer': 'softbody_plan_review',
          'plan': file_record(REVIEW), 'begin_at': REVIEW_START,
          'limits': {'starts': MAX_STARTS, 'seconds': MAX_SECONDS, 'disk': MAX_DISK,
                     'wall': MAX_WALL, 'attempts': ATTEMPT_CAP}})


def source_for(summary, phase):
    if phase == 'B':
        require(not any(row['attempt'][0] in 'CD' for row in summary['attempts']), 'SHOT_PHASE_ORDER')
        return None
    previous = 'B' if phase == 'C' else 'C'
    matches = [row for row in summary['attempts']
               if row['attempt'].startswith(previous) and row['state'] == 'PASS']
    require(len(matches) == 1, 'SHOT_ACCEPTED_SOURCE_REQUIRED')
    result = matches[0]
    for item in result['files'].values():
        verify_record(item)
    return {'scope': result['scope'], 'phase': previous, 'files': result['files']}


def execute(phase, tuning):
    require(not (CASE/'conclusion.json').exists(), 'SHOT_GOAL_TERMINATED')
    with execution_lock(CASE, TASK):
        preflight_path = CASE/'preflight-r2.json'
        gate = read(preflight_path if preflight_path.is_file() else CASE/'preflight.json')
        review = read(CASE/'review.json')
        verify_record(review['plan'])
        summary = summarize(CASE)
        source = source_for(summary, phase)
        name, seconds, disk = next_parameters(summary, phase, review['begin_at'])
        if name == 'B-03':
            adjustment = read(CASE/'B-03-adjustment.json')
            require(adjustment['attempt'] == name and
                    adjustment['preflight'] == file_record(preflight_path) and
                    adjustment['prior'] == file_record(CASE/'attempts/B-02/terminal.json'),
                    'SHOT_ADJUSTMENT_BINDING')
            gate = adjustment
        verify_record(gate['software'])
        if phase == 'B':
            verify_record(gate['worker'])
        require(type(tuning) is int and 0 <= tuning < ATTEMPT_CAP[phase], 'SHOT_TUNING_INVALID')
        require(shutil.disk_usage(CASE).free >= disk + 4*1024**3, 'SHOT_FREE_SPACE_LIMIT')
        plan, native = make_scope(CASE/'attempts'/name, phase, seconds, disk, review['plan'], source, tuning)
        error = None
        files = {}
        try:
            for step in plan['steps']:
                run_step(native, plan, step)
            files = verify_output(native, phase)
        except Exception as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        usage = native.snapshot()
        if any(ticket['stopped_at'] is None for ticket in usage['tickets']):
            print(json.dumps({'attempt': name, 'state': 'UNKNOWN', 'error': error, 'usage': usage}), flush=True)
            return 3
        result = terminal(native, usage, 'PASS' if error is None else 'FAILED', error, files)
        print(json.dumps({'attempt': name, **result}), flush=True)
        return 0 if error is None else 1


def verify_output(native, phase):
    root = native.root
    require(phase != 'D', 'SHOT_RENDER_VALIDATOR_NOT_READY')
    warm = read(root/'warm.json')
    cold = read(root/'cold.json')
    require(warm == cold and warm['state'] == 'PASS' and warm['version'] == VERSION,
            'SHOT_COLD_OBSERVATION_MISMATCH')
    return {name: file_record(root/filename) for name, filename in
            (('hip', 'shot.hip'), ('warm', 'warm.json'), ('cold', 'cold.json'),
             ('cache', 'cache-manifest.json'), ('preview', 'preview-data.json'))}


def preflight():
    import threading
    from unittest.mock import patch
    from dcc_task_runtime.errors import RuntimeV2Error
    from dcc_task_runtime.softbody_shot_scope import validate_scope, check_step
    from dcc_task_runtime.native_scope import _reuse_record_bytes
    compiler = compile(WORKER.read_text(), str(WORKER), 'exec')
    require(compiler is not None, 'SHOT_WORKER_SYNTAX')
    ensure_private_directory(CASE)
    review = read(CASE/'review.json')
    checked = []
    with patch.object(owned_process, 'launch', side_effect=AssertionError('PREFLIGHT_NATIVE_LAUNCH')):
        with tempfile.TemporaryDirectory(dir=CASE, prefix='verify-') as temporary:
            temporary = Path(temporary)
            for phase in STEPS:
                plan, native = make_scope(temporary/(phase+'-01'), phase, list(CEILINGS[phase]),
                    1024**3, review['plan'], None if phase == 'B' else {'software_fixture': True})
                validate_scope(native.scope, native.path)
                require(native.completed_snapshot()['dcc_starts'] == 0, 'SHOT_PREFLIGHT_NATIVE_COUNT')
                broken = dict(native.scope, phase='A')
                assert_rejected(lambda: validate_scope(broken, native.path), 'invalid_phase', checked)
                broken = dict(native.scope, dispatch=dict(native.scope['dispatch'], sha256='0'*64))
                assert_rejected(lambda: validate_scope(broken, native.path), 'changed_dispatch', checked)
                if phase == 'D':
                    require(plan['steps'][0]['role'] == 'shot-hython' and
                            plan['steps'][1]['role'] == 'shot-husk', 'SHOT_RENDER_ROLE_ORDER')
                    second = plan['steps'][1]
                    step_dir = Path(second['directory'])
                    step_dir.mkdir()
                    identity = {'task_id': TASK, 'operation_id': 'D-01-render'}
                    ticket = {'role': 'shot-husk', 'directory': str(step_dir), 'id': 'fixture2',
                              'identity': identity, 'stopped_at': None}
                    spec = {'command': second['argv'], 'native_scope_ticket': ticket,
                            'budget_seconds': second['seconds'], 'identity': identity,
                            'env': {'HOUDINI_PATH':str(KINEFX)+':&','HOUDINI_PACKAGE_SKIP':'1'},
                            'resource_budget': {'roots': [plan['root']], 'max_bytes': plan['disk'],
                                                'native_scope': native.binding}}
                    write(step_dir/'intent.json', spec)
                    with patch.object(native, 'snapshot', return_value={'tickets': [ticket]}):
                        assert_rejected(lambda: check_step(native, step_dir, spec), 'render_without_prior_stop', checked)
                    with patch.object(native, 'snapshot', return_value={'tickets': [{'stopped_at': 1.0}, ticket]}):
                        check_step(native, step_dir, spec)
                        checked.append('render_after_prior_stop')
                start = plan['steps'][0]
                wrong = dict(command=start['argv']+['unexpected'], native_scope_ticket={
                    'role': start['role'], 'directory': start['directory']},
                    budget_seconds=start['seconds'],
                    resource_budget={'roots': [plan['root']], 'max_bytes': plan['disk'],
                                     'native_scope': native.binding})
                assert_rejected(lambda: check_step(native, start['directory'], wrong), 'changed_command', checked)
                plan['worker']['sha256'] = '0'*64
                assert_rejected(lambda: _reuse_record_bytes(plan['worker']), 'changed_worker', checked)
            held = []
            def concurrent():
                try:
                    with execution_lock(CASE, TASK):
                        held.append('entered')
                except RuntimeV2Error:
                    held.append('rejected')
            with execution_lock(CASE, TASK):
                contender = threading.Thread(target=concurrent)
                contender.start()
                contender.join()
            require(held == ['rejected'], 'SHOT_CONCURRENT_EXECUTE_NOT_REJECTED')
            checked.append('concurrent_execute')
            empty = {'attempts': [], 'attempt_count': 0, 'starts': 0, 'seconds': 0, 'disk_bytes': 0}
            require(next_parameters(empty, 'B', review['begin_at'])[0] == 'B-01', 'SHOT_FIRST_ATTEMPT')
            for key, exhausted in (('starts', MAX_STARTS-1), ('seconds', MAX_SECONDS),
                                    ('disk_bytes', MAX_DISK), ('attempt_count', 7),
                                    ('attempts', [{'state': 'UNKNOWN'}]),
                                    ('attempts', [{'state': 'FAILED', 'attempt': f'B-0{i}'} for i in range(1, 4)])):
                assert_rejected(lambda: next_parameters(dict(empty, **{key: exhausted}), 'B', review['begin_at']),
                                'limit_'+key, checked)
            assert_rejected(lambda: next_parameters(empty, 'B', time.time()-MAX_WALL), 'wall_limit', checked)
            assert_rejected(lambda: budget_for('B', [241, 240], 1024**3), 'per_step_time_limit', checked)
            assert_rejected(lambda: budget_for('B', [240, 240], 1024**3+1), 'per_attempt_disk_limit', checked)
            assert_rejected(lambda: source_for(empty, 'C'), 'no_accepted_source', checked)
            done = dict(empty, attempts=[{'attempt':'B-01', 'state':'PASS'}], attempt_count=1)
            assert_rejected(lambda: next_parameters(done, 'B', review['begin_at']), 'accepted_replay', checked)
    record = {'state': 'PASS', 'native_starts': 0, 'verified_guards': checked,
              'software': file_record(Path(__file__).resolve()), 'worker': file_record(WORKER)}
    first = CASE/'preflight.json'
    write(CASE/'preflight-r2.json' if first.exists() else first, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def assert_rejected(action, label, checked):
    try:
        action()
    except (ValueError, KeyError):
        checked.append(label)
    else:
        raise AssertionError('SHOT_PREFLIGHT_DID_NOT_REJECT:' + label)


def check_core_adjustment():
    """Static check for the final allowed B attempt, with the prior stop bound."""
    with execution_lock(CASE, TASK):
        summary = summarize(CASE)
        review = read(CASE/'review.json')
        require(next_parameters(summary, 'B', review['begin_at'])[0] == 'B-03'
                and summary['attempts'][-1]['state'] == 'FAILED', 'SHOT_CORE_ADJUSTMENT_NOT_APPLICABLE')
        compile(WORKER.read_text(),str(WORKER),'exec')
        from dcc_task_runtime.softbody_shot_scope import validate_scope
        with tempfile.TemporaryDirectory(dir=CASE, prefix='proxy-check-') as folder:
            _, native = make_scope(Path(folder)/'B-03', 'B', list(CEILINGS['B']), 1024**3,
                                   review['plan'], tuning=1)
            validate_scope(native.scope, native.path)
            require(native.completed_snapshot()['dcc_starts'] == 0, 'SHOT_PREFLIGHT_NATIVE_COUNT')
        write(CASE/'B-03-adjustment.json', {'state': 'PASS', 'attempt': 'B-03', 'native_starts': 0,
              'prior': file_record(CASE/'attempts/B-02/terminal.json'),
              'preflight':file_record(CASE/'preflight-r2.json'),
              'software':file_record(Path(__file__).resolve()), 'worker':file_record(WORKER)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'check-core-adjustment', 'execute', 'status', 'conclude'))
    parser.add_argument('--phase', choices=tuple(ATTEMPT_CAP))
    parser.add_argument('--tuning', type=int, default=0)
    parser.add_argument('--reason')
    options = parser.parse_args()
    if options.command == 'prepare':
        create_case()
    elif options.command == 'preflight':
        preflight()
    elif options.command == 'check-core-adjustment':
        check_core_adjustment()
    elif options.command == 'execute':
        return execute(options.phase, options.tuning)
    elif options.command == 'conclude':
        with execution_lock(CASE, TASK):
            require(bool(options.reason), 'SHOT_CONCLUSION_REASON_REQUIRED')
            write(CASE/'conclusion.json', {'state': 'TERMINATED', 'reason': options.reason,
                 'summary': summarize(CASE)})
    else:
        print(json.dumps(summarize(CASE), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
