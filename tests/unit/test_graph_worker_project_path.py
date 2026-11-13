"""First-save path preparation at an explicit plain-Python HOM boundary."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock

from vfx_pipeline import graph_job_worker as module


class GraphWorkerProjectPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='/private/tmp', prefix='worker-project-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.attempt = self.root / 'attempt'
        self.attempt.mkdir()
        self.events = []
        self.worker = module.GraphJobWorker.__new__(module.GraphJobWorker)
        self.worker.root = self.root
        self.worker.result_path = self.attempt / 'result.json'
        self.worker.operation_id = 'op_first_save'
        self.worker.graph_id = 'graph_test'
        self.worker.job = {'attempt_token': 'test-token', 'validation_scope': 'software_test'}
        self.worker.scheduler = None
        self.worker.clock = lambda: 10.0
        self.worker.deadline_at = 30.0
        self.worker._deadline_monotonic = float('inf')
        self.target = self.attempt / 'op_first_save.hip'
        self.name = 'untitled.hip'
        self.hip = SimpleNamespace(setName=self.set_name, path=self.read_name,
                                   save=mock.Mock(), load=mock.Mock(), clear=mock.Mock())
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(sys.modules, {'hou': SimpleNamespace(hipFile=self.hip)}).start()

    def set_name(self, name):
        self.assertFalse(self.target.exists())
        self.events.append('setName')
        self.name = name

    def read_name(self):
        self.events.append('path')
        return self.name

    def assert_no_file_operations(self):
        self.hip.save.assert_not_called()
        self.hip.load.assert_not_called()
        self.hip.clear.assert_not_called()

    def test_names_fresh_target_under_scheduler_fence_without_resetting_budget(self):
        @contextmanager
        def operation(root, operation_id, token):
            self.assertEqual((root, operation_id, token), (str(self.root), 'op_first_save', 'test-token'))
            self.events.append('fence_enter')
            yield
            self.events.append('fence_exit')
        self.worker.scheduler = SimpleNamespace(operation=operation)
        budget = self.worker._check_budget
        def check():
            self.events.append('budget')
            budget()
        self.worker._check_budget = check
        self.assertEqual(self.worker._prepare_project_path(), self.target)
        self.assertEqual(self.events, ['fence_enter', 'budget', 'setName', 'path', 'budget', 'fence_exit'])
        self.assertEqual(self.worker.deadline_at, 30.0)
        self.assertEqual(self.worker._deadline_monotonic, float('inf'))
        self.assertFalse(self.target.exists())
        self.assert_no_file_operations()

    def test_rejects_unsafe_or_nonfresh_paths_before_native_call(self):
        for case in ('file', 'directory', 'dangling', 'intermediate_link', 'outside', 'missing_parent', 'invalid_name'):
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
                    owned = Path(tmp); attempt = owned / 'attempt'; attempt.mkdir()
                    self.worker.root = owned
                    self.worker.operation_id = 'op_first_save'
                    self.worker.result_path = attempt / 'result.json'
                    target = attempt / 'op_first_save.hip'
                    if case == 'file': target.write_bytes(b'existing')
                    elif case == 'directory': target.mkdir()
                    elif case == 'dangling': target.symlink_to(owned / 'missing')
                    elif case == 'intermediate_link':
                        link = owned / 'linked'; link.symlink_to(attempt, target_is_directory=True)
                        self.worker.result_path = link / 'result.json'
                    elif case == 'outside': self.worker.result_path = owned.parent / 'result.json'
                    elif case == 'missing_parent': self.worker.result_path = owned / 'missing' / 'result.json'
                    elif case == 'invalid_name': self.worker.operation_id = '../wrong'
                    self.events.clear()
                    with self.assertRaises(ValueError): self.worker._prepare_project_path()
                    self.assertNotIn('setName', self.events)
                    self.assert_no_file_operations()

    def test_missing_failing_or_inconsistent_native_api_fails_closed(self):
        for case in ('missing_module', 'missing_setName', 'missing_path', 'exception', 'readback', 'file_created', 'link_created'):
            with self.subTest(case=case):
                hip = SimpleNamespace(setName=self.set_name, path=self.read_name)
                if case == 'missing_setName': del hip.setName
                elif case == 'missing_path': del hip.path
                elif case == 'exception': hip.setName = mock.Mock(side_effect=RuntimeError('native failure'))
                elif case == 'readback': hip.path = lambda: 'different.hip'
                elif case == 'file_created':
                    def write(name): self.name = name; Path(name).write_bytes(b'not allowed')
                    hip.setName = write
                elif case == 'link_created':
                    def link(name): self.name = name; Path(name).symlink_to(self.root / 'missing')
                    hip.setName = link
                with mock.patch.dict(sys.modules, {'hou': None if case == 'missing_module' else SimpleNamespace(hipFile=hip)}):
                    with self.assertRaises((ValueError, AttributeError, RuntimeError, ModuleNotFoundError)):
                        self.worker._prepare_project_path()
                if self.target.exists() or self.target.is_symlink(): self.target.unlink()
                self.assert_no_file_operations()

    def test_expired_or_revoked_authority_cannot_name_target(self):
        for case in ('wall_before', 'mono_before', 'wall_after', 'mono_after', 'revoked'):
            with self.subTest(case=case):
                self.events.clear()
                self.worker.scheduler = None
                self.worker.deadline_at = 30.0
                self.worker._deadline_monotonic = 30.0
                self.worker.clock = mock.Mock(side_effect=[31.0] if case == 'wall_before' else [10.0, 31.0] if case == 'wall_after' else [10.0, 10.0])
                ticks = [31.0] if case == 'mono_before' else [10.0, 31.0] if case == 'mono_after' else [10.0, 10.0]
                if case == 'revoked':
                    self.worker.scheduler = SimpleNamespace(operation=mock.Mock(side_effect=RuntimeError('revoked')))
                with mock.patch.object(module.time, 'monotonic', side_effect=ticks):
                    with self.assertRaises((TimeoutError, RuntimeError)): self.worker._prepare_project_path()
                self.assertEqual('setName' in self.events, case in ('wall_after', 'mono_after'))
                self.assertFalse(self.target.exists())

    def test_run_validates_and_loads_before_naming_then_enters_first_lease(self):
        worker = self.worker
        worker.injected_addon = False
        worker.addon = None
        worker.repo_root = self.root
        worker._record_error = mock.Mock()
        worker._compile_registered = lambda: self.events.append('compile') or object()
        worker._initialize_evidence = lambda compiled: self.events.append('evidence')
        def lease(compiled):
            self.assertEqual(self.name, str(self.target))
            self.assertFalse(self.target.exists())
            self.events.append('lease')
            raise RuntimeError('stop before graph execution')
        worker._lease = lease
        with mock.patch.object(module, '_install_runtime_paths'), mock.patch.object(module, '_load_addon',
                side_effect=lambda root: self.events.append('addon_load') or object()):
            result = worker.run()
        self.assertEqual(self.events, ['compile', 'evidence', 'addon_load', 'setName', 'path', 'lease'])
        self.assertFalse(result['construction_executed'])
        self.assert_no_file_operations()

    def test_run_does_not_reach_native_or_lease_after_validation_or_preparation_failure(self):
        for stage in ('compile', 'evidence', 'addon_load', 'prepare'):
            with self.subTest(stage=stage):
                worker = self.worker
                worker.injected_addon = False; worker.addon = None; worker.repo_root = self.root
                worker._record_error = mock.Mock(); worker._lease = mock.Mock()
                worker._compile_registered = mock.Mock(side_effect=ValueError('invalid') if stage == 'compile' else None)
                worker._initialize_evidence = mock.Mock(side_effect=ValueError('invalid') if stage == 'evidence' else None)
                with mock.patch.object(module, '_install_runtime_paths'), mock.patch.object(module, '_load_addon',
                        side_effect=ValueError('invalid') if stage == 'addon_load' else None), \
                        mock.patch.object(worker, '_prepare_project_path', side_effect=ValueError('invalid')) as prepare:
                    result = worker.run()
                worker._lease.assert_not_called()
                self.assertEqual(prepare.called, stage == 'prepare')
                self.assertFalse(result['construction_executed'])
                self.assertTrue(result['reconciliation_required'])
