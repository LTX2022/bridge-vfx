#!/usr/bin/env python3
"""Run real mapped unittest cases and bind the results to this source build."""
import argparse
import ast
import contextlib
import inspect
import json
import os
from pathlib import Path
from functools import lru_cache
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock
from readiness_evidence import (REQUIRED, build_id, digest, validate_contract,
                                validate_contract_rows, _canonical_sha256)
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=256)
def _assertion_lines(path):
    try:
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            lines.add(node.lineno)
        elif isinstance(node, ast.Call):
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else (
                function.id if isinstance(function, ast.Name) else '')
            if name.startswith('assert') or name == 'fail':
                lines.add(node.lineno)
    return lines


@lru_cache(maxsize=256)
def _source_binding(path):
    try:
        resolved = Path(path).resolve()
        relative = resolved.relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return None
    if not relative.startswith('tests/') or not resolved.is_file() or resolved.is_symlink():
        return None
    return {'path': relative, 'sha256': digest(resolved)}

class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}
        self.test_executions = {}
        self._active = None
        self._prior_trace = None
        self._executed_build = build_id(ROOT)

    def startTest(self, test):
        super().startTest(test)
        method = getattr(test, getattr(test, '_testMethodName', ''), None)
        method_path = inspect.getsourcefile(method) if method is not None else None
        binding = _source_binding(method_path) if method_path else None
        self._active = {
            'source_files': {binding['path']: binding} if binding else {},
            'assertion_refs': set(),
            'subtests': [],
            'provider_facts': [],
            'static_invocations': [],
        }
        self._prior_trace = sys.gettrace()
        sys.settrace(self._trace)

    def _trace(self, frame, event, arg):
        if event == 'return' and self._active is not None:
            filename = Path(frame.f_code.co_filename).resolve()
            caller = frame.f_back
            nuke_producer = (frame.f_code.co_name == 'finalize_render_operation'
                and filename == (ROOT / 'packages/nuke-bridge/src/nuke_bridge/operation_receipts.py').resolve()
                and caller is not None and caller.f_code.co_name == '_nuke_operation_fact'
                and Path(caller.f_code.co_filename).resolve() == (ROOT / 'plugins/nuke/nuke_bridge_addon.py').resolve())
            houdini_render_producer = (frame.f_code.co_name in {'render_execution_fact', 'read_render_operation'}
                and filename == (ROOT / 'packages/houdini-bridge/src/houdini_bridge/client.py').resolve()
                and (frame.f_code.co_name == 'read_render_operation' or (
                    caller is not None and caller.f_code.co_name == '_fx_render_execution_fact'
                    and Path(caller.f_code.co_filename).resolve() == (
                        ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py').resolve())))
            provider = arg
            if houdini_render_producer and frame.f_code.co_name == 'read_render_operation':
                provider = arg.get('execution_fact') if isinstance(arg, dict) else None
            if ((frame.f_code.co_name == '_fx_scene_transition_complete'
                    and Path(frame.f_code.co_filename).resolve() == (
                        ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py').resolve()
                    and isinstance(arg, dict)
                    and arg.get('schema') == 'bridge.houdini.scene-transition-operation/1.0')
                    or (nuke_producer and isinstance(provider, dict)
                        and provider.get('schema') == 'bridge.nuke.render-operation/1.0')
                    or (houdini_render_producer and isinstance(provider, dict)
                        and provider.get('schema') == 'bridge.houdini.render.execution_fact/1.0')):
                context = frame.f_back
                case_id = None
                while context is not None:
                    value = context.f_locals.get('case_id')
                    if isinstance(value, str) and value:
                        case_id = value
                        break
                    context = context.f_back
                self._active['provider_facts'].append({
                    'build_id': self._executed_build, 'case_id': case_id,
                    'operation_receipt_sha256': provider.get('operation_receipt_sha256'),
                    'provider_sha256': _canonical_sha256(provider),
                })
            elif (frame.f_globals.get('__name__') == 'subprocess'
                  and frame.f_code.co_name == 'run' and hasattr(arg, 'returncode')):
                self._active['static_invocations'].append({
                    'argv': list(arg.args) if isinstance(arg.args, (list, tuple)) else arg.args,
                    'returncode': arg.returncode, 'stdout': arg.stdout, 'stderr': arg.stderr,
                })
        if event == 'line' and self._active is not None:
            filename = frame.f_code.co_filename
            if not filename.startswith(str(ROOT / 'tests') + os.sep):
                return self._trace
            binding = _source_binding(filename)
            if binding is not None and frame.f_lineno in _assertion_lines(filename):
                self._active['source_files'][binding['path']] = binding
                self._active['assertion_refs'].add(f"{binding['path']}:{frame.f_lineno}")
        return self._trace

    def _set_outcome(self, test, outcome):
        test_id = test.id()
        self.outcomes[test_id] = outcome

    def addSuccess(self, test):
        super().addSuccess(test); self._set_outcome(test, 'PASS')
    def addFailure(self, test, err):
        super().addFailure(test, err); self._set_outcome(test, 'FAIL')
    def addError(self, test, err):
        super().addError(test, err); self._set_outcome(test, 'ERROR')
    def addSkip(self, test, reason):
        super().addSkip(test, reason); self._set_outcome(test, 'SKIP')
    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err); self._set_outcome(test, 'EXPECTED_FAILURE')
    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test); self._set_outcome(test, 'UNEXPECTED_SUCCESS')
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if self._active is not None:
            params = getattr(subtest, 'params', None)
            self._active['subtests'].append({
                'context': {str(key): repr(value) for key, value in dict(params or {}).items()},
                'outcome': 'FAIL' if err is not None else 'PASS',
            })
        if err is not None: self._set_outcome(test, 'FAIL')

    def stopTest(self, test):
        super().stopTest(test)
        sys.settrace(self._prior_trace)
        self._prior_trace = None
        active = self._active or {}
        self.test_executions[test.id()] = {
            'outcome': self.outcomes.get(test.id(), 'NOT_RECORDED'),
            'source_files': sorted(active.get('source_files', {}).values(), key=lambda item:item['path']),
            'assertion_refs': sorted(active.get('assertion_refs', set())),
            'subtests': list(active.get('subtests', [])),
            'executed_at': datetime.now(timezone.utc).isoformat(),
            'provider_facts': list(active.get('provider_facts', [])),
            'static_invocations': list(active.get('static_invocations', [])),
        }
        self._active = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.mapping.read_text())['rows']
    if len(rows) != len(REQUIRED) or {r['id'] for r in rows} != set(REQUIRED):
        raise ValueError('mapping must cover every required ID exactly once')
    before = build_id(ROOT)
    mapping_errors = validate_contract_rows(
        {'build_id': before, 'rows': rows}, ROOT,
        check_results=False, check_artifacts=False)
    if mapping_errors:
        details = '; '.join(
            identifier + ': ' + ', '.join(messages)
            for identifier, messages in sorted(mapping_errors.items()))
        raise ValueError('mapping evidence identity is invalid: ' + details)
    names = set()
    for row in rows:
        for kind in ('positive_tests', 'negative_tests'):
            if not row.get(kind): raise ValueError(row['id'] + ': missing ' + kind)
            names.update(row[kind])
    for package in (ROOT / 'packages').glob('*/src'):
        sys.path.insert(0, str(package))
    for kind in ('unit','contract','integration'):
        sys.path.insert(0, str(ROOT / 'tests' / kind))
    sys.path.insert(0, str(ROOT))
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix('.log')
    with tempfile.TemporaryDirectory(prefix='bridge-contract-state-') as state:
        environment = {
            'BRIDGE_SKILLS_STATE_ROOT': state,
            'HOUDINI_BRIDGE_STATE_DIR': str(Path(state) / 'houdini'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT': str(Path(state) / 'scheduler'),
            'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(Path(state) / 'approval.key'),
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            with log.open('w') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromNames(sorted(names)))
    clean = result.wasSuccessful() and not result.skipped and not result.expectedFailures and before == build_id(ROOT)
    payload = dict(schema='bridge.readiness.executed_contracts/2', build_id=before, rows=rows,
                   test_results=result.outcomes, test_executions=result.test_executions,
                   test_count=result.testsRun, returncode=0 if clean else 1,
                   log={'path':str(log), 'sha256':digest(log)})
    # A green unittest run is not enough to make the contract evidence
    # consumable.  Re-read every production file and persisted operation/event
    # receipt after execution; missing or synthetic bindings keep the evidence
    # failed and visible to the readiness report.
    validation_errors = validate_contract(payload, ROOT)
    if validation_errors:
        payload['returncode'] = 1
        payload['validation_errors'] = validation_errors
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return payload['returncode']

if __name__ == '__main__':
    raise SystemExit(main())
