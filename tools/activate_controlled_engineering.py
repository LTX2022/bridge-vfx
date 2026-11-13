#!/usr/bin/env python3
"""Review a fresh candidate and explicitly activate a separate frozen native scope.

The local terminal action is a trusted controller boundary, not protection from
other programs running as the same user. Public file hashes identify what was
reviewed; they are not an authorization credential.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
sys.dont_write_bytecode = True
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from dcc_task_runtime.native_scope import NativeScope
import prepare_controlled_engineering as preparation
from run_alpha_calibration import checked, file_record, plain


def _copy(value):
    return json.loads(json.dumps(value))


def _binding(path):
    record = file_record(plain(path))
    return {key: record[key] for key in ('path', 'sha256')}


def _unused(native):
    state = native.snapshot()
    if state['dcc_starts'] or state['closed_reason'] or state['tickets']:
        raise ValueError('ENGINEERING_ACTIVATION_SCOPE_ALREADY_USED')


def _candidate(scope_path, bindings_path, expected_scope_sha256, expected_bindings_sha256):
    scope_record, bindings_record = _binding(scope_path), file_record(plain(bindings_path))
    if (scope_record['sha256'] != expected_scope_sha256
            or bindings_record['sha256'] != expected_bindings_sha256):
        raise ValueError('ENGINEERING_ACTIVATION_REVIEW_HASH_MISMATCH')
    native = NativeScope(scope_record)
    if (native.scope.get('execution_authorized') is not False
            or native.scope.get('status') != 'PREPARED_NOT_AUTHORIZED'):
        raise ValueError('ENGINEERING_ACTIVATION_PREPARED_SCOPE_REQUIRED')
    _unused(native)
    if Path(bindings_record['path']) != native.root / 'runtime-bindings.json':
        raise ValueError('ENGINEERING_ACTIVATION_BINDINGS_PATH_INVALID')
    receipt = json.loads(plain(native.root / 'engineering-preparation.json').read_text())
    if (receipt.get('schema') != 'bridge.controlled-engineering.preparation/1'
            or receipt.get('scope_sha256') != scope_record['sha256']
            or receipt.get('bindings') != bindings_record):
        raise ValueError('ENGINEERING_ACTIVATION_PREPARATION_MISMATCH')
    for record in receipt['immutable_files']:
        checked(record)
    bindings = json.loads(checked(bindings_record).read_text())
    if (bindings.get('scope_sha256') != scope_record['sha256']
            or bindings.get('evidence_source') != native.scope.get('evidence_source', 'real_host')):
        raise ValueError('ENGINEERING_ACTIVATION_SOURCE_MISMATCH')
    snapshot = plain(receipt['snapshot_root'])
    if snapshot != native.root / 'project/control/snapshot':
        raise ValueError('ENGINEERING_ACTIVATION_SNAPSHOT_PATH_INVALID')
    sources = {str(path.relative_to(snapshot)): file_record(path)['sha256']
               for path in sorted(snapshot.rglob('*')) if path.is_file()}
    if not sources or any(bindings['source_freeze'].get(str(snapshot / name)) != digest
                          for name, digest in sources.items()):
        raise ValueError('ENGINEERING_ACTIVATION_SOURCE_MISMATCH')
    alpha = json.loads(checked(bindings['alpha_preparation']).read_text())
    from dcc_task_runtime.render_profiles import OFFICIAL
    official=native.scope.get('scene_profile')==OFFICIAL
    scene_record=native.scope['official_case']['source_contract'] if official else file_record(native.root/'frozen-inputs/frozen-scene-v2.json')
    inputs = {'scene': scene_record,
              'native_primary_sources': alpha['primary_sources'],
              'native_color_tokens': native.scope['native_color_tokens']}
    if official:
        case=native.scope['official_case']
        inputs['official_case']={key:case[key] for key in
            ('source_contract','source_hip','source_files','original_files','static_review','source_preparation')}
        for item in (case['source_contract'],case['source_hip'],case['static_review'],case['source_preparation'],*case['source_files']):
            checked(item)
        for source,digest in case['source_freeze'].items():
            if file_record(source)['sha256']!=digest:
                raise ValueError('OFFICIAL_ACTIVATION_CASE_SOURCE_CHANGED')
    for record in alpha['primary_sources'].values():
        checked(record)
    for record in native.scope['hosts'].values():
        checked(record)
    def check_inputs(value):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                checked({key: value[key] for key in ('path', 'bytes', 'sha256')})
            else:
                for item in value.values(): check_inputs(item)
        elif isinstance(value, list):
            for item in value: check_inputs(item)
    check_inputs(native.scope['native_color_tokens'])
    check_inputs(native.scope.get('alpha_fixture', {}))
    check_inputs(native.scope.get('software_native_boundaries', {}))
    check_inputs(native.scope.get('process_image_policy', {}))
    return native, bindings_record, bindings, snapshot, sources, inputs


def _fresh_root(path, source_root):
    target = plain(path)
    if (target.exists() or target.is_relative_to(source_root)
            or source_root.is_relative_to(target)):
        raise ValueError('ENGINEERING_ACTIVATION_FRESH_ROOT_REQUIRED')
    if not target.parent.is_dir():
        raise ValueError('ENGINEERING_ACTIVATION_PARENT_REQUIRED')
    return target


def _initialize(source, target, scope_id, *, authorized=False, **fields):
    key = secrets.token_bytes(32)
    value = _copy(source)
    value.setdefault('evidence_source', 'real_host')
    value.update(output_root=str(target), scope_id=scope_id,
        execution_authorized=authorized,
        status='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION' if authorized else 'PREPARED_NOT_AUTHORIZED',
        accounting={'key_path': str(target / '.native-control/key'),
                    'key_sha256': hashlib.sha256(key).hexdigest()}, **fields)
    from dcc_task_runtime.render_profiles import OFFICIAL
    if value.get('scene_profile')==OFFICIAL:
        from houdini_bridge.official_karma_preparation import relocate_case
        value['official_case']=relocate_case(source['official_case'],Path(source['output_root']),target)
    target.mkdir(mode=0o700)
    path = target / 'scope.json'
    preparation._write(path, value)
    return NativeScope.initialize(_binding(path), key=key)


def prepare_successor(scope_path, bindings_path, output_root, *, expected_scope_sha256,
                      expected_bindings_sha256):
    """Freeze current source into a distinct, still unauthorized review candidate."""
    native, original_bindings, _, _, _, inputs = _candidate(scope_path, bindings_path,
        expected_scope_sha256, expected_bindings_sha256)
    target = _fresh_root(output_root, native.root)
    from dcc_task_runtime.render_profiles import OFFICIAL
    if native.scope.get('scene_profile')==OFFICIAL:
        raise ValueError('OFFICIAL_SUCCESSOR_NOT_SUPPORTED_USE_REVIEWED_INITIAL_SCOPE')
    if file_record(ROOT / 'docs/official-baselines/karma/frozen-scene-v2.json')['sha256'] != inputs['scene']['sha256']:
        raise ValueError('ENGINEERING_ACTIVATION_INPUT_MISMATCH')
    fields = {'prepared_from': {'scope': native.binding, 'bindings': original_bindings}}
    clean = dict(native.scope)
    clean.pop('activation_review', None)
    clean.pop('prepared_from', None)
    successor = _initialize(clean, target, 'engineering-candidate-' + uuid.uuid4().hex, **fields)
    result = preparation.prepare(successor.path)
    return {'scope': successor.binding, 'bindings': result['bindings'],
            'state': 'PREPARED_NOT_AUTHORIZED', 'native_execution_status': 'NOT_RUN'}


def _review_value(native, bindings_record, bindings, snapshot, sources, inputs, target, scope_id):
    contract={key:value for key,value in native.scope.items() if key not in
        ('scope_id','output_root','accounting','execution_authorized','status','activation_review','evidence_source')}
    from dcc_task_runtime.render_profiles import OFFICIAL
    if native.scope.get('scene_profile')==OFFICIAL:
        from houdini_bridge.official_karma_preparation import relocate_case
        contract['official_case']=relocate_case(native.scope['official_case'],native.root,target)
        inputs=_copy(inputs)
        inputs['official_case']={key:contract['official_case'][key] for key in
            ('source_contract','source_hip','source_files','original_files','static_review','source_preparation')}
    return {'schema': 'bridge.controlled-engineering.activation-review/1',
        'scope': native.binding, 'bindings': bindings_record,
        'snapshot_root': str(snapshot), 'source_snapshot': sources, 'inputs': inputs,
        'evidence_source': native.scope.get('evidence_source', 'real_host'),
        'scope_contract': contract,
        'runtime_contract': {key: bindings[key] for key in
            ('main_plan', 'native_start_inventory', 'route_sha256', 'output_acceptance', 'plugin_build')},
        'target_root': str(target), 'target_scope_id': scope_id,
        'resource_roots': [str(target)], 'native_execution_status': 'NOT_RUN'}


def review_activation(scope_path, bindings_path, output_root, *, expected_scope_sha256,
                      expected_bindings_sha256):
    candidate = _candidate(scope_path, bindings_path, expected_scope_sha256, expected_bindings_sha256)
    native = candidate[0]
    target = _fresh_root(output_root, native.root)
    value = _review_value(*candidate, target, 'engineering-authorized-' + uuid.uuid4().hex)
    record = preparation._write(native.root / 'engineering-activation-review.json', value)
    return {'review': record, 'state': 'REVIEW_REQUIRED',
            'target_root': str(target), 'native_execution_status': 'NOT_RUN'}


def _review(path, digest, *, target_exists=False):
    record = file_record(plain(path))
    if record['sha256'] != digest:
        raise ValueError('ENGINEERING_ACTIVATION_REVIEW_HASH_MISMATCH')
    review = json.loads(checked(record).read_text())
    if review.get('schema') != 'bridge.controlled-engineering.activation-review/1':
        raise ValueError('ENGINEERING_ACTIVATION_REVIEW_INVALID')
    candidate = _candidate(review['scope']['path'], review['bindings']['path'],
        review['scope']['sha256'], review['bindings']['sha256'])
    target = plain(review['target_root'])
    if target_exists:
        if target.is_relative_to(candidate[0].root) or candidate[0].root.is_relative_to(target):
            raise ValueError('ENGINEERING_ACTIVATION_FRESH_ROOT_REQUIRED')
    else:
        _fresh_root(target, candidate[0].root)
    if review != _review_value(*candidate, target, review['target_scope_id']):
        raise ValueError('ENGINEERING_ACTIVATION_REVIEW_DRIFT')
    return record, review, candidate


def _activate(review_path, expected_review_sha256, authorization, *, grant=None):
    record, review, candidate = _review(review_path, expected_review_sha256)
    native, _, bindings, snapshot, _, _ = candidate
    if authorization == 'explicit_software_test_controller':
        if native.scope.get('evidence_source') != 'software_test':
            raise ValueError('ENGINEERING_ACTIVATION_SOFTWARE_TEST_ONLY')
    elif authorization == 'explicit_agent_controller':
        # Honest agent activation: the human grant is recorded verbatim and
        # the receipt never claims a hand-typed terminal action.
        if (not isinstance(grant, dict) or grant.get('authority') != 'current_user_conditional_instruction'
                or not isinstance(grant.get('instruction'), str) or not grant['instruction'].strip()):
            raise ValueError('ENGINEERING_ACTIVATION_AGENT_GRANT_REQUIRED')
    elif authorization != 'explicit_local_terminal_controller':
        raise ValueError('ENGINEERING_ACTIVATION_TRUSTED_ACTION_REQUIRED')
    source = dict(native.scope)
    source.pop('activation_review', None)
    activated = _initialize(source, Path(review['target_root']), review['target_scope_id'],
        authorized=True, activation_review=record)
    # Import only the reviewed snapshot in an isolated, fixed-Python subprocess.
    script = ('import sys; sys.path.insert(0, ' + repr(str(snapshot / 'tools')) + '); '
        'import prepare_controlled_engineering as p; import json; '
        'print(json.dumps(p._prepare(' + repr(str(activated.path)) + ', authorized=True)))')
    # Allow 90s for local freezing and each of three sequential pure-Python tools.
    result = preparation._python(native.scope, ['-c', script], bindings['environment'], timeout_seconds=360)
    payload = {'schema': 'bridge.controlled-engineering.activation/1', 'scope': activated.binding,
        'bindings': result['bindings'], 'review': record, 'authorization': authorization,
        'native_execution_status': 'NOT_RUN'}
    if grant is not None:
        payload['agent_activation_grant'] = grant
    preparation._write(activated.root / 'engineering-activation.json', activated._envelope(payload))
    validate_activation(activated, result['bindings']['path'])
    return payload


def activate_software_test(review_path, *, expected_review_sha256):
    """Explicit software-only simulation of the trusted controller action."""
    return _activate(review_path, expected_review_sha256, 'explicit_software_test_controller')


def activate_local_terminal(review_path, *, expected_review_sha256):
    """Require a human terminal action tied to the full reviewed target contract."""
    _, review, _ = _review(review_path, expected_review_sha256)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('ENGINEERING_ACTIVATION_INTERACTIVE_TERMINAL_REQUIRED')
    print(json.dumps(review, ensure_ascii=False, indent=2))
    phrase = 'AUTHORIZE ' + expected_review_sha256
    print('Type exactly ' + phrase + ' to authorize this new frozen scope:')
    if input().strip() != phrase:
        raise ValueError('ENGINEERING_ACTIVATION_EXPLICIT_APPROVAL_REQUIRED')
    return _activate(review_path, expected_review_sha256, 'explicit_local_terminal_controller')


def activate_agent(review_path, *, expected_review_sha256, instruction):
    """Explicit agent-carried activation under a recorded human grant.

    The grant text is stored verbatim in the signed receipt and the
    authorization kind stays 'explicit_agent_controller'; it never claims a
    hand-typed terminal action.
    """
    grant = {'authority': 'current_user_conditional_instruction', 'instruction': str(instruction)}
    return _activate(review_path, expected_review_sha256, 'explicit_agent_controller', grant=grant)


def validate_activation(native, bindings_path):
    """Verify controller receipt and review bindings before driver execution."""
    if (native.scope.get('execution_authorized') is not True
            or native.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('ENGINEERING_ACTIVATION_AUTHORIZED_SCOPE_REQUIRED')
    review_record = native.scope.get('activation_review')
    if not isinstance(review_record, dict):
        raise ValueError('ENGINEERING_ACTIVATION_REVIEW_REQUIRED')
    checked(review_record)
    record, review, candidate = _review(review_record['path'], review_record['sha256'], target_exists=True)
    if (str(native.root) != review['target_root'] or native.scope.get('scope_id') != review['target_scope_id']
            or native.scope['accounting']['key_sha256'] == candidate[0].scope['accounting']['key_sha256']
            or native.binding['sha256'] == candidate[0].binding['sha256']):
        raise ValueError('ENGINEERING_ACTIVATION_TARGET_MISMATCH')
    if (any(native.scope.get(key) != value for key, value in review['scope_contract'].items())
            or native.scope.get('evidence_source') != review['evidence_source']):
        raise ValueError('ENGINEERING_ACTIVATION_SCOPE_CONTRACT_MISMATCH')
    bindings_record = file_record(plain(bindings_path))
    payload = native._verify_envelope(json.loads(plain(native.root / 'engineering-activation.json').read_text()))
    if (payload.get('schema') != 'bridge.controlled-engineering.activation/1'
            or payload.get('scope') != native.binding or payload.get('bindings') != bindings_record
            or payload.get('review') != record or native.scope['activation_review'] != record
            or Path(bindings_record['path']) != native.root / 'runtime-bindings.json'
            or payload.get('authorization') not in
            ('explicit_local_terminal_controller', 'explicit_software_test_controller',
             'explicit_agent_controller')
            or (payload['authorization'] == 'explicit_software_test_controller'
                and native.scope.get('evidence_source') != 'software_test')
            or (payload['authorization'] == 'explicit_agent_controller'
                and (not isinstance(payload.get('agent_activation_grant'), dict)
                     or payload['agent_activation_grant'].get('authority') != 'current_user_conditional_instruction'
                     or not str(payload['agent_activation_grant'].get('instruction') or '').strip()))):
        raise ValueError('ENGINEERING_ACTIVATION_RECEIPT_MISMATCH')
    bindings = json.loads(checked(bindings_record).read_text())
    if (bindings.get('scope_sha256') != native.binding['sha256']
            or bindings.get('evidence_source') != review['evidence_source']
            or any(bindings.get(key) != value for key, value in review['runtime_contract'].items())):
        raise ValueError('ENGINEERING_ACTIVATION_BINDINGS_MISMATCH')
    snapshot = native.root / 'project/control/snapshot'
    actual_sources = {str(path.relative_to(snapshot)): file_record(path)['sha256']
                      for path in snapshot.rglob('*') if path.is_file()}
    if actual_sources != review['source_snapshot']:
        raise ValueError('ENGINEERING_ACTIVATION_SOURCE_MISMATCH')
    from dcc_task_runtime.render_profiles import OFFICIAL
    if native.scope.get('scene_profile')==OFFICIAL:
        case=native.scope['official_case']
        actual={key:case[key] for key in ('source_contract','source_hip','source_files','original_files','static_review','source_preparation')}
        if actual!=review['inputs']['official_case']:
            raise ValueError('OFFICIAL_ACTIVATION_INPUT_MISMATCH')
        scene=Path(case['source_contract']['path'])
        for source,digest in case['source_freeze'].items():
            if file_record(source)['sha256']!=digest:
                raise ValueError('OFFICIAL_ACTIVATION_CASE_SOURCE_CHANGED')
    else:
        scene=native.root/'frozen-inputs/frozen-scene-v2.json'
    if file_record(scene)['sha256'] != review['inputs']['scene']['sha256']:
        raise ValueError('ENGINEERING_ACTIVATION_INPUT_MISMATCH')
    alpha = json.loads(checked(bindings['alpha_preparation']).read_text())
    if alpha['primary_sources'] != review['inputs']['native_primary_sources']:
        raise ValueError('ENGINEERING_ACTIVATION_INPUT_MISMATCH')
    for deployment in bindings['deployments'].values():
        value = json.loads(checked(deployment).read_text())
        if (value.get('native_scope') != native.binding or value.get('task_root') != str(native.root)
                or value.get('resource_budget') != {'roots': review['resource_roots'],
                    'max_bytes': native.scope['budget']['max_disk_bytes'], 'native_scope': native.binding}):
            raise ValueError('ENGINEERING_ACTIVATION_RESOURCE_MISMATCH')
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare-successor', 'review'):
        command = commands.add_parser(name)
        command.add_argument('--scope', required=True)
        command.add_argument('--bindings', required=True)
        command.add_argument('--output-root', required=True)
        command.add_argument('--expected-scope-sha256', required=True)
        command.add_argument('--expected-bindings-sha256', required=True)
    command = commands.add_parser('activate')
    command.add_argument('--review', required=True)
    command.add_argument('--expected-review-sha256', required=True)
    command = commands.add_parser('activate-agent')
    command.add_argument('--review', required=True)
    command.add_argument('--expected-review-sha256', required=True)
    command.add_argument('--instruction', required=True)
    args = vars(parser.parse_args())
    name = args.pop('command')
    if name == 'activate':
        result = activate_local_terminal(args.pop('review'), **args)
    elif name == 'activate-agent':
        result = activate_agent(args.pop('review'), instruction=args.pop('instruction'), **args)
    else:
        function = prepare_successor if name == 'prepare-successor' else review_activation
        result = function(args.pop('scope'), args.pop('bindings'), args.pop('output_root'), **args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
