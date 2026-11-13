"""Bounded plain-Python startup diagnostics; no native DCC is launched."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from dcc_task_runtime import owned_process
from vfx_pipeline.graph_jobs import GraphJobService
from vfx_pipeline import graph_job_worker
from test_graph_jobs import _proposal


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / 'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
FLAG = 'BRIDGE_GRAPH_STARTUP_DIAGNOSTICS'
STAGES = ['python_entry', 'imports_complete', 'catalog_validation_before',
          'catalog_validation_after', 'main_arguments_parsed', 'main_job_parsed',
          'run_compile_before', 'run_compile_after', 'initialize_evidence_before',
          'runtime_fingerprint_before', 'runtime_fingerprint_after',
          'construction_inputs_before', 'construction_inputs_after',
          'process_identity_before', 'process_identity_after',
          'scheduler_bind_process_before', 'scheduler_bind_process_after',
          'initialize_evidence_after']
RECORD = re.compile(r'bridge\.graph-worker\.startup/1 stage=([a-z_]+) '
                    r'monotonic_ns=([0-9]+) pid=([0-9]+) wall_time_ns=([0-9]+)\n')


class GraphWorkerStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='graph-startup-', dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def environment(self, flag='1'):
        environment = {'PATH': '/usr/bin:/bin', 'STARTUP_PRIVATE': 'ENV_VALUE_NOT_FOR_LOG'}
        if flag is not None:
            environment[FLAG] = flag
        return environment

    def run_worker(self, *arguments, flag='1'):
        before = time.time_ns()
        result = subprocess.run([sys.executable, '-I', '-B', str(WORKER), *arguments],
                              env=self.environment(flag), capture_output=True,
                              text=True, timeout=10)
        after = time.time_ns()
        for record in RECORD.finditer(result.stderr):
            self.assertLessEqual(before, int(record.group(4)))
            self.assertLessEqual(int(record.group(4)), after)
        return result

    def stages(self, raw):
        records = list(RECORD.finditer(raw))
        self.assertEqual(''.join(record.group(0) for record in records), raw)
        ticks = [int(record.group(2)) for record in records]
        self.assertEqual(ticks, sorted(ticks))
        self.assertTrue(all(tick > 0 for tick in ticks))
        self.assertTrue(all(int(record.group(4)) > 0 for record in records))
        self.assertLessEqual(len({record.group(3) for record in records}), 1)
        self.assertNotIn('JOB_VALUE_NOT_FOR_LOG', raw)
        self.assertNotIn('ENV_VALUE_NOT_FOR_LOG', raw)
        return [record.group(1) for record in records]

    def test_checkpoint_pairs_clocks_and_ignores_write_failure(self):
        with mock.patch.object(graph_job_worker, '_STARTUP_DIAGNOSTICS', True), \
                mock.patch.object(graph_job_worker.time, 'time_ns', return_value=123) as wall, \
                mock.patch.object(graph_job_worker.time, 'monotonic_ns', return_value=456) as mono, \
                mock.patch.object(graph_job_worker.os, 'getpid', return_value=789), \
                mock.patch.object(graph_job_worker.os, 'write') as write:
            graph_job_worker._startup_checkpoint('python_entry')
            write.assert_called_once_with(2, b'bridge.graph-worker.startup/1 stage=python_entry '
                                          b'monotonic_ns=456 pid=789 wall_time_ns=123\n')
            wall.assert_called_once_with()
            mono.assert_called_once_with()
            write.side_effect = OSError('closed diagnostic descriptor')
            graph_job_worker._startup_checkpoint('python_entry')

    def test_disabled_checkpoint_does_not_read_clocks_or_write(self):
        with mock.patch.object(graph_job_worker, '_STARTUP_DIAGNOSTICS', False), \
                mock.patch.object(graph_job_worker.time, 'time_ns') as wall, \
                mock.patch.object(graph_job_worker.time, 'monotonic_ns') as mono, \
                mock.patch.object(graph_job_worker.os, 'write') as write:
            graph_job_worker._startup_checkpoint('python_entry')
            wall.assert_not_called()
            mono.assert_not_called()
            write.assert_not_called()

    def test_script_requires_exact_opt_in_and_keeps_input_errors_private(self):
        job = json.dumps({'private': 'JOB_VALUE_NOT_FOR_LOG'})
        for flag in (None, '0', 'true', '1'):
            with self.subTest(flag=flag):
                result = self.run_worker('--job', job, flag=flag)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(self.stages(result.stderr), STAGES[:6] if flag == '1' else [])

    def test_ordinary_import_stays_silent_even_with_opt_in(self):
        code = ('import sys; sys.path[:0] = sys.argv[1:]; '
                'import vfx_pipeline.graph_job_worker')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
                                 *[str(ROOT / 'packages' / package / 'src') for package in
                                   ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')]],
                                env=self.environment(), capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((result.stdout, result.stderr), ('', ''))

    def test_malformed_job_keeps_parser_failure_and_last_stage(self):
        result = self.run_worker('--job', '{"private":"JOB_VALUE_NOT_FOR_LOG"')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.stages(result.stderr), STAGES[:5])

    def test_managed_software_job_reaches_evidence_then_fails_without_native_api(self):
        captured = []

        def capture(command, **kwargs):
            captured.append(command)
            raise OSError('explicit software transport capture; no child launched')

        service = GraphJobService(self.root / 'jobs', ROOT, 'REAL_DCC_FORBIDDEN',
                                  scheduler_root=self.root / 'scheduler',
                                  subprocess_factory=capture)
        self.addCleanup(service.close)
        graph = service.propose(_proposal(), 'startup-proposal')
        with mock.patch('vfx_pipeline.graph_jobs.threading.Thread.start'):
            operation = service.trial(graph, 'startup-trial')
        row = service._row(operation)
        service._launch(operation, service.compiled_graph(graph),
                        row['process_token'], row['attempt_generation'])
        self.assertEqual(len(captured), 1)
        job = json.loads(captured[0][captured[0].index('--job') + 1])
        job['private'] = 'JOB_VALUE_NOT_FOR_LOG'
        result = self.run_worker('--job', json.dumps(job))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.stages(result.stderr), STAGES)
        self.assertLess(len(result.stderr.encode()), 4096)
        evidence = json.loads(Path(job['result_path']).read_text())
        self.assertFalse(evidence['construction_executed'])
        self.assertTrue(evidence['reconciliation_required'])
        self.assertEqual(evidence['validation_scope'], 'software_test')
        self.assertEqual(evidence['diagnostics'][0]['code'], 'WORKER_RECONCILIATION_REQUIRED')
        self.assertTrue(Path(job['identity_path']).is_file())
        self.assertFalse(Path(job['completion_path']).exists())
        self.assertEqual(list(self.root.rglob('*.hip')), [])

    def test_paused_import_exposes_last_checkpoint_in_owned_stderr_before_exit(self):
        marker = self.root / 'import-paused'
        code = '''import builtins, os, runpy, sys, time
worker, marker = sys.argv[1:]
original = builtins.__import__
def importing(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'argparse' and globals and globals.get('__file__') == worker:
        with open(marker, 'wb') as stream:
            stream.write(b'explicit software import pause')
        time.sleep(12)
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = importing
sys.argv = [worker, '--job', '{}']
runpy.run_path(worker, run_name='__main__')
'''
        directory = self.root / 'owned-supervisor'
        handle = owned_process.launch([sys.executable, '-I', '-B', '-c', code,
                                       str(WORKER), str(marker)],
                                      directory=directory, identity={'test': 'startup-import-pause'},
                                      supervisor_executable=sys.executable,
                                      env=self.environment(), budget_seconds=8)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and handle.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.is_file())
            self.assertIsNone(handle.poll())
            raw = (directory / 'child.stderr.log').read_text()
            self.assertEqual(self.stages(raw), ['python_entry'])
            self.assertEqual(int(RECORD.fullmatch(raw).group(3)), handle.pid)
        finally:
            handle.terminate()
            handle.wait(timeout=8)
        self.assertIsNotNone(handle.poll())
        self.assertEqual(self.stages((directory / 'child.stderr.log').read_text()), ['python_entry'])

    def test_diagnostic_controller_sets_and_restores_isolated_opt_in(self):
        spec = importlib.util.spec_from_file_location('startup_hip_driver', ROOT / 'tools/run_hip_diagnostic.py')
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        data = {'root': self.root, 'control': self.root / 'control',
                'config': {'task_id': 'startup-software-only',
                           'ocio_config': {'path': str(self.root / 'not-opened.ocio')}}}
        with mock.patch.dict(os.environ, {FLAG: 'untrusted', 'STARTUP_PRIVATE': 'ENV_VALUE_NOT_FOR_LOG'}):
            previous = dict(os.environ)
            with driver.controlled_environment(data):
                self.assertEqual(os.environ[FLAG], '1')
                self.assertNotIn('STARTUP_PRIVATE', os.environ)
                self.assertNotIn('BRIDGE_OWNED_SUPERVISOR_DIR', os.environ)
                service = GraphJobService(self.root / 'jobs', ROOT, 'REAL_DCC_FORBIDDEN',
                                          scheduler_root=self.root / 'scheduler',
                                          subprocess_factory=mock.Mock(side_effect=AssertionError('launch forbidden')))
                try:
                    self.assertEqual(service._worker_env(self.root / 'attempt')[FLAG], '1')
                finally:
                    service.close()
            self.assertEqual(dict(os.environ), previous)


if __name__ == '__main__':
    unittest.main()
