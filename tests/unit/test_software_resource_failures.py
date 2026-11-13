from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from vfx_pipeline.workbuddy_assembly import SoftwareGraphResources


class SoftwareResourceFailureTests(unittest.TestCase):
    def test_normal_body_cleanup_error_keeps_original_error_and_retained_owner(self):
        for failure in ('directory', 'observation'):
            with self.subTest(failure=failure):
                temporary = tempfile.TemporaryDirectory(dir=ROOT / 'outputs')
                original_error = OSError('actual cleanup fault')
                owner = SoftwareGraphResources(temporary_directory=temporary)
                owner.__enter__()
                try:
                    if failure == 'directory':
                        with patch.object(temporary, 'cleanup', side_effect=original_error):
                            with self.assertRaises(OSError) as raised:
                                owner.__exit__(None, None, None)
                        self.assertEqual(raised.exception.resource_cleanup['pending_monitors'], 0)
                    else:
                        with patch.object(owner, 'snapshot', side_effect=ValueError('snapshot unavailable')):
                            with patch.object(owner, 'cleanup', side_effect=original_error):
                                with self.assertRaises(OSError) as raised:
                                    owner.__exit__(None, None, None)
                        self.assertIsNone(raised.exception.resource_cleanup['pending_monitors'])
                        self.assertEqual(raised.exception.resource_cleanup['observation_error_type'], 'ValueError')
                    self.assertIs(raised.exception, original_error)
                    self.assertIs(raised.exception.software_resources, owner)
                    self.assertIs(raised.exception.resource_cleanup['retained'], True)
                    self.assertTrue(Path(temporary.name).is_dir())
                    self.assertTrue(owner.cleanup())
                    self.assertFalse(Path(temporary.name).exists())
                finally:
                    owner.cleanup()
                    temporary.cleanup()

    def handler(self):
        source = ast.parse((ROOT / 'tools/prepare_workbuddy_graph.py').read_text(encoding='utf-8'))
        launcher = next(node.value for node in ast.walk(source)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and 'with prepared_graph_facade(ROOT' in node.value)
        handlers = next(node for node in ast.parse(launcher).body if isinstance(node, ast.Try)).handlers
        statement = ast.Try(body=[ast.Raise(exc=ast.Name(id='original_error', ctx=ast.Load()))],
                            handlers=handlers, orelse=[], finalbody=[])
        return compile(ast.fix_missing_locations(ast.Module(body=[statement], type_ignores=[])),
                       'actual-generated-handler', 'exec')

    def test_pending_process_exit_cannot_be_bypassed_by_output_fault(self):
        for failure in ('print', 'stdout_flush', 'stderr_flush'):
            for error_type in (RuntimeError, KeyboardInterrupt):
                with self.subTest(failure=failure, error_type=error_type):
                    original_error = error_type('actual handler input exception')
                    original_error.resource_cleanup = {'retained': True, 'pending_monitors': 1}
                    stdout, stderr = Mock(), Mock()
                    printer = Mock()
                    if failure == 'print':
                        printer.side_effect = BrokenPipeError('MCP reader closed')
                    elif failure == 'stdout_flush':
                        stdout.flush.side_effect = BrokenPipeError('stdout flush failed')
                    else:
                        stderr.flush.side_effect = OSError('stderr flush failed')
                    terminate = Mock(side_effect=SystemExit(2))
                    with self.assertRaises(SystemExit) as raised:
                        exec(self.handler(), {'original_error': original_error, 'facade': None,
                            'json': json, 'backend': 'software', 'print': printer,
                            '_os': SimpleNamespace(_exit=terminate),
                            'sys': SimpleNamespace(stdout=stdout, stderr=stderr)})
                    self.assertEqual(raised.exception.code, 2)
                    terminate.assert_called_once_with(2)

    def test_nonpending_keyboard_interrupt_preserves_normal_propagation(self):
        original_error = KeyboardInterrupt('normal interruption')
        terminate = Mock()
        with self.assertRaises(KeyboardInterrupt) as raised:
            exec(self.handler(), {'original_error': original_error, 'facade': None,
                'json': json, 'backend': 'software', '_os': SimpleNamespace(_exit=terminate)})
        self.assertIs(raised.exception, original_error)
        terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
