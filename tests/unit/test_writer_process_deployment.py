"""Trusted writer deployment and owned start bindings; no DCC/native imports."""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from dcc_task_runtime import owned_process, process_image
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.platform_support import ensure_private_directory, open_private_file
from houdini_bridge import task_host
from vfx_pipeline import production_hosts


class WriterProcessDeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='writer-deployment-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.python = str(Path(sys.executable).resolve())
        self.version = '22.0.459'
        self.writer = {
            'schema': 'bridge.process-image.executable/1', 'platform': 'darwin',
            'version': self.version,
            'image': {'path': str(self.root / '软件 writer'), 'sha256': 'a' * 64,
                      'stat': {'device': 1, 'inode': 2, 'size': 32, 'mtime_ns': 3,
                               'ctime_ns': 4, 'mode': stat.S_IFREG | 0o700,
                               'uid': 501, 'gid': 20, 'links': 1}},
        }
        self.input = {'path': self.writer['image']['path'], 'version': self.version,
                      'sha256': self.writer['image']['sha256']}
        self.identity = {'task_id': '软件任务', 'launch_nonce': 'nonce',
                         'writer_executable_sha256': canonical_sha256(self.writer)}

    def config(self, kind='houdini', **changes):
        return {'application': kind, 'lifecycle': 'task_owned',
                'version': self.version if kind == 'houdini' else '17.0v1',
                'executable': self.python, 'supervisor_executable': self.python,
                'task_root': str(self.root), 'session_seconds': 30,
                'resource_budget': {'roots': [str(self.root)], 'max_bytes': 1024 * 1024},
                'evidence_source': 'software_test', **changes}

    def validate(self, **changes):
        return production_hosts.validate_deployments(
            self.config(**changes), self.config('nuke'), controller_root=self.root,
            repo_root=ROOT, allow_software_processes=True)[0]

    def anchor(self, pid, *args, **kwargs):
        return {'schema': 'bridge.process-image.observation/1', 'platform': 'darwin',
                'pid': pid, 'parent_pid': os.getpid(),
                'birth': '2026-10-16 12:34:56.789 +0000', 'load_address': '0x100000000',
                'image': deepcopy(self.writer['image'])}

    def test_configuration_freezes_only_explicit_inputs_and_retains_full_result(self):
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer) as freeze:
            config = self.validate(writer_executable=self.input)
        freeze.assert_called_once_with(self.input['path'], self.version, self.input['sha256'])
        self.assertEqual(config['writer_executable'], self.writer)
        self.assertEqual(config['evidence_source'], 'software_test')
        self.assertNotIn('native', config)
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer) as freeze:
            self.assertEqual(self.validate(writer_executable=self.writer)['writer_executable'], self.writer)
        freeze.assert_called_once_with(self.input['path'], self.version, self.input['sha256'])
        changed = deepcopy(self.writer)
        changed['image']['stat']['inode'] += 1
        with mock.patch.object(process_image, 'freeze_executable', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'WRITER_EXECUTABLE_CHANGED'):
                self.validate(writer_executable=self.writer)
        with mock.patch.object(process_image, 'freeze_executable', side_effect=AssertionError('discovery')):
            self.assertNotIn('writer_executable', self.validate())

    def test_configuration_rejects_verified_null_wrong_version_and_non_houdini(self):
        values = [None, {}, {**self.input, 'verified': True},
                  {**self.input, 'version': '21.0.631'}]
        with mock.patch.object(process_image, 'freeze_executable') as freeze:
            for value in values:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'WRITER_'):
                    self.validate(writer_executable=value)
            with self.assertRaisesRegex(ValueError, 'WRITER_EXECUTABLE_INVALID'):
                production_hosts._validate(self.config('nuke', writer_executable=self.input),
                                           'nuke', self.root, ROOT, True)
        freeze.assert_not_called()

    def test_configuration_propagates_file_rejection_without_spawning(self):
        for reason in ('SHA256_MISMATCH', 'FILE_UNAVAILABLE', 'INVALID_PATH'):
            with self.subTest(reason=reason), \
                    mock.patch.object(process_image, 'freeze_executable', side_effect=ValueError(reason)), \
                    mock.patch.object(owned_process.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ValueError, reason):
                    self.validate(writer_executable=self.input)
                spawn.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin', 'freeze runtime is macOS only')
    def test_explicit_python_file_can_be_frozen_as_software_configuration(self):
        digest = hashlib.sha256(Path(self.python).read_bytes()).hexdigest()
        config = self.validate(writer_executable={'path': self.python, 'version': self.version,
                                                  'sha256': digest})
        frozen = config['writer_executable']
        self.assertEqual(frozen['image']['path'], self.python)
        self.assertEqual(frozen['image']['sha256'], digest)
        self.assertEqual(frozen['version'], self.version)
        self.assertEqual(config['evidence_source'], 'software_test')
        with self.assertRaisesRegex(ValueError, 'SHA256_MISMATCH'):
            self.validate(writer_executable={'path': self.python, 'version': self.version,
                                            'sha256': '0' * 64})

    def test_writer_file_identity_participates_in_existing_deployment_fingerprint(self):
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer):
            configs = [self.validate(writer_executable=self.input),
                       production_hosts._validate(self.config('nuke'), 'nuke', self.root, ROOT, True)]
        fingerprint = hashlib.sha256(json.dumps(configs, ensure_ascii=False, sort_keys=True,
                                               allow_nan=False).encode('utf-8')).hexdigest()
        production_hosts._atomic(self.root / 'production-hosts.json',
                                 {'task_id': 't', 'config_sha256': fingerprint, 'hosts': {}})
        changed = deepcopy(self.writer)
        changed['image']['stat']['inode'] += 1
        with mock.patch.object(process_image, 'freeze_executable', return_value=changed), \
                mock.patch.object(owned_process, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'PRODUCTION_DEPLOYMENT_CHANGED'):
                production_hosts.ensure_hosts(
                    self.config(writer_executable=self.input), self.config('nuke'), task_id='t',
                    controller_root=self.root, repo_root=ROOT, scheduler_root=self.root / 'scheduler',
                    allow_software_processes=True)
        launch.assert_not_called()

    def tool(self, extra):
        spec = importlib.util.spec_from_file_location('writer_configuration_tool',
                                                     ROOT / 'tools/configure_production_hosts.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.root / 'deployment.json'
        argv = ['configure', '--output', str(output), '--task-root', str(self.root),
                '--houdini-executable', self.python, '--nuke-executable', self.python,
                '--python-executable', self.python, '--houdini-version', self.version,
                '--max-bytes', '1048576', '--session-seconds', '30', *extra]
        with mock.patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()):
            code = module.main()
        return code, output

    def test_tool_requires_paired_husk_arguments_and_writes_only_deployment_inputs(self):
        for extra in (['--husk-executable', self.python], ['--husk-sha256', 'a' * 64]):
            with self.subTest(extra=extra), mock.patch.object(process_image, 'freeze_executable') as freeze:
                with self.assertRaises(SystemExit) as error:
                    self.tool(extra)
                self.assertEqual(error.exception.code, 2)
                freeze.assert_not_called()
                self.assertFalse((self.root / 'deployment.json').exists())
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer) as freeze:
            code, output = self.tool(['--husk-executable', self.input['path'],
                                      '--husk-sha256', self.input['sha256']])
        self.assertEqual(code, 0)
        freeze.assert_called_once_with(self.input['path'], self.version, self.input['sha256'])
        payload = json.loads(output.read_text())
        self.assertEqual(payload['houdini']['writer_executable'], self.input)
        self.assertNotIn('writer_executable', payload['nuke'])

    def test_tool_has_no_implicit_writer_discovery_and_refuses_failed_freeze(self):
        with mock.patch.object(process_image, 'freeze_executable', side_effect=ValueError('changed')):
            with self.assertRaises(SystemExit):
                self.tool(['--husk-executable', self.input['path'], '--husk-sha256', self.input['sha256']])
        self.assertFalse((self.root / 'deployment.json').exists())
        with mock.patch.object(process_image, 'freeze_executable', side_effect=AssertionError('discovery')):
            _, output = self.tool([])
        self.assertNotIn('writer_executable', json.loads(output.read_text())['houdini'])

    def args(self, **changes):
        return argparse.Namespace(**{
            'task_id': '软件任务', 'work_dir': str(self.root / 'work'),
            'addon_root': str(ROOT / 'plugins/houdini'), 'houdini_bin': self.python,
            'supervisor_executable': self.python, 'version': self.version,
            'writer_executable': self.writer, 'max_seconds': 30, 'ready_timeout': .1,
            'poll_seconds': .01, 'warmup': False, **changes})

    def test_production_launcher_forwards_complete_frozen_writer(self):
        config = self.config(writer_executable=self.writer)
        with mock.patch.object(task_host, 'start', return_value=0) as start:
            production_hosts._launch_h(config, self.root / 'host', 't', self.root,
                                       self.root / 'scheduler', ROOT)
        self.assertEqual(start.call_args.args[0].writer_executable, self.writer)

    def test_task_launcher_rechecks_whole_file_identity_before_workdir_or_spawn(self):
        changed = deepcopy(self.writer)
        changed['image']['stat']['ctime_ns'] += 1
        with mock.patch.object(process_image, 'freeze_executable', return_value=changed), \
                mock.patch.object(owned_process, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'WRITER_EXECUTABLE_CHANGED'):
                task_host.start(self.args())
        launch.assert_not_called()
        self.assertFalse((self.root / 'work').exists())
        with mock.patch.object(process_image, 'freeze_executable') as freeze:
            with self.assertRaisesRegex(ValueError, 'WRITER_EXECUTABLE_INVALID'):
                task_host.start(self.args(version='21.0.631'))
        freeze.assert_not_called()

    def test_task_runner_and_supervisor_share_unicode_canonical_digest(self):
        child = mock.Mock(pid=1234, returncode=7)
        child.poll.return_value = 7
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer), \
                mock.patch.object(owned_process, 'launch', return_value=child) as launch, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(task_host.start(self.args()), 2)
        self.addCleanup(task_host._ACTIVE_CHILDREN.pop, child.pid, None)
        options = launch.call_args.kwargs
        expected = hashlib.sha256(json.dumps(self.writer, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        self.assertEqual(options['writer_executable'], self.writer)
        self.assertEqual(options['identity']['writer_executable_sha256'], expected)
        self.assertEqual(json.loads(options['env']['BRIDGE_OWNED_SUPERVISOR_IDENTITY']), options['identity'])
        tree = ast.parse((self.root / 'work/task_host_runner.py').read_text())
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == 'task_host_serve')
        values = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        self.assertEqual(values['writer_executable'], self.writer)

    def test_legacy_runner_omits_writer_and_legacy_template_format_still_works(self):
        args = self.args()
        del args.writer_executable
        child = mock.Mock(pid=1235, returncode=7)
        child.poll.return_value = 7
        with mock.patch.object(process_image, 'freeze_executable', side_effect=AssertionError('discovery')), \
                mock.patch.object(owned_process, 'launch', return_value=child) as launch, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(task_host.start(args), 2)
        self.addCleanup(task_host._ACTIVE_CHILDREN.pop, child.pid, None)
        self.assertNotIn('writer_executable', launch.call_args.kwargs)
        self.assertNotIn('writer_executable_sha256', launch.call_args.kwargs['identity'])
        self.assertNotIn('writer_executable=', (self.root / 'work/task_host_runner.py').read_text())

    def test_owned_launch_validates_before_spawn_and_persists_full_intent(self):
        with mock.patch.object(process_image, 'freeze_executable', side_effect=PermissionError('denied')), \
                mock.patch.object(owned_process.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(owned_process.SupervisorNotStarted, 'denied'):
                owned_process.launch([self.python, '-c', 'pass'], directory=self.root / 'bad',
                                     identity=self.identity, supervisor_executable=self.python,
                                     writer_executable=self.writer)
        self.assertFalse((self.root / 'bad').exists())
        spawn.assert_not_called()
        child = mock.Mock()
        with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer), \
                mock.patch.object(owned_process.subprocess, 'Popen', return_value=child), \
                mock.patch.object(owned_process, 'read_receipt', return_value={'pid': 123}), \
                mock.patch.object(owned_process, 'OwnedProcessHandle'):
            owned_process.launch([self.python, '-c', 'pass'], directory=self.root / 'intent',
                                 identity=self.identity, supervisor_executable=self.python,
                                 writer_executable=self.writer)
        intent = json.loads((self.root / 'intent/intent.json').read_text())
        self.assertEqual(intent['writer_executable'], self.writer)
        self.assertEqual(intent['identity'], self.identity)

    def test_writer_launch_allows_collection_deadline_without_changing_legacy_timeout(self):
        for writer in (None, self.writer):
            with self.subTest(writer=writer is not None), \
                    mock.patch.object(process_image, 'freeze_executable', return_value=self.writer), \
                    mock.patch.object(owned_process.subprocess, 'Popen', return_value=mock.Mock()), \
                    mock.patch.object(owned_process, 'time') as clock, \
                    mock.patch.object(owned_process, 'read_receipt', return_value={'pid': 123}) as read, \
                    mock.patch.object(owned_process, 'OwnedProcessHandle') as handle:
                clock.monotonic.side_effect = [0, 11]
                options = dict(directory=self.root / ('extended' if writer else 'legacy'),
                               identity=self.identity, supervisor_executable=self.python,
                               writer_executable=writer)
                if writer is not None:
                    self.assertIs(owned_process.launch([self.python, '-c', 'pass'], **options),
                                  handle.return_value)
                    read.assert_called_once()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'SUPERVISOR_START_UNKNOWN'):
                        owned_process.launch([self.python, '-c', 'pass'], **options)
                    read.assert_not_called()

    def test_script_supervisor_loads_sibling_process_image_without_native_imports(self):
        import runpy
        namespace = runpy.run_path(owned_process.__file__, run_name='writer_deployment_support_test')
        collector = namespace['_process_images']()
        self.assertEqual(Path(collector.__file__).resolve(), Path(process_image.__file__).resolve())
        self.assertIsNone(namespace['WindowsJobProcess'] if os.name != 'nt' else None)

    def ps(self, pid, deadline, directory):
        # The OS boundary and runtime-ready event use the same fixture process.
        # Publish through the real signer so the readiness gate still verifies
        # identity, PID, command digest and nonce without timing Python imports.
        spec = owned_process._read(directory / 'intent.json')
        owned_process._signed_write(directory, {
            'schema': owned_process.SCHEMA, 'event': 'runtime-ready',
            'identity': spec['identity'], 'pid': pid,
            'argv_sha256': hashlib.sha256(owned_process._canonical(spec['command'])).hexdigest(),
            'runtime_nonce': spec['writer_runtime']['nonce'], 'observed_at': time.time(),
        })
        anchor = self.anchor(pid)
        return anchor['parent_pid'], int(process_image._birth(anchor['birth']).timestamp())

    def writer_child(self, directory, spec):
        spec = owned_process._writer_runtime_spec(directory, spec)
        owned_process._atomic(directory / 'intent.json', spec)
        process = subprocess.Popen(spec['command'], env=spec['env'], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=os.name != 'nt')
        return spec, process

    def supervise(self, name, observe, frozen=None, command=None, budget=1):
        directory = ensure_private_directory(self.root / name, exist_ok=False)
        with os.fdopen(open_private_file(directory / 'receipt.key'), 'wb') as stream:
            stream.write(os.urandom(32))
        owned_process._atomic(directory / 'intent.json', {
            'command': command or [self.python, '-c', 'pass'], 'identity': self.identity,
            'env': dict(os.environ), 'resource_budget': None, 'budget_seconds': budget,
            'writer_executable': self.writer,
        })
        with mock.patch.object(process_image, 'freeze_executable', return_value=frozen or self.writer), \
                mock.patch.object(process_image, '_ps', side_effect=lambda pid, deadline: self.ps(pid, deadline, directory)), \
                mock.patch.object(process_image, '_observe', side_effect=observe):
            result = owned_process.supervise(directory)
        started = owned_process.read_receipt(directory, 'started', identity=self.identity)
        stopped = owned_process.read_receipt(directory, 'stopped', identity=self.identity)
        return result, directory, started, stopped

    def test_supervisor_signs_complete_binding_and_stopped_chain(self):
        result, directory, started, stopped = self.supervise('valid', self.anchor)
        self.assertEqual(result, 0)
        self.assertEqual(started['writer_process_binding'], {
            'expected_executable': self.writer, 'host_anchor': self.anchor(started['pid'])})
        self.assertNotIn('writer_process_binding_error', started)
        self.assertEqual(stopped['observed_by'], 'owned_child_wait')
        self.assertEqual(stopped['started_sha256'], hashlib.sha256(owned_process._canonical(started)).hexdigest())
        packet = json.loads((directory / 'started.json').read_text())
        packet['payload']['writer_process_binding']['host_anchor']['pid'] += 1
        (directory / 'started.json').write_text(json.dumps(packet))
        with self.assertRaisesRegex(ValueError, 'SUPERVISOR_RECEIPT_MISMATCH'):
            owned_process.OwnedProcessHandle(directory, self.identity)

    def test_collection_failure_bad_anchor_and_refreeze_change_keep_signed_stop(self):
        changed = deepcopy(self.writer)
        changed['image']['stat']['inode'] += 1
        failures = [PermissionError('denied'), ValueError('PROCESS_IMAGE_TIMEOUT'),
                    lambda pid, *args, **kwargs: self.anchor(pid + 1)]
        for index, failure in enumerate(failures):
            with self.subTest(failure=index):
                result, _, started, stopped = self.supervise('failure-' + str(index), failure)
                self.assertEqual(result, stopped['supervisor_exit_code'])
                self.assertIn('writer_process_binding_error', started)
                self.assertNotIn('writer_process_binding', started)
                self.assertEqual(stopped['pid'], started['pid'])
                self.assertEqual(stopped['observed_by'], 'owned_child_wait')
                self.assertEqual(stopped['stop_reason'], 'SUPERVISOR_WRITER_COLLECTION_FAILED')
                self.assertEqual(stopped['execution_result'], 'failed')
                self.assertNotEqual(owned_process.execution_returncode(stopped), 0)
        _, _, started, stopped = self.supervise('changed', self.anchor, frozen=changed)
        self.assertIn('EXECUTABLE_CHANGED', started['writer_process_binding_error'])
        self.assertNotIn('writer_process_binding', started)
        self.assertIsNotNone(stopped)

    def test_collection_permission_error_stops_before_budget_deadline(self):
        result, _, started, stopped = self.supervise(
            'budget', PermissionError('denied'), command=[self.python, '-c', 'import time;time.sleep(30)'],
            budget=.1)
        self.assertEqual(result, 0)
        self.assertIn('writer_process_binding_error', started)
        self.assertNotEqual(owned_process.execution_returncode(stopped), 0)
        self.assertEqual(stopped['stop_reason'], 'SUPERVISOR_WRITER_COLLECTION_FAILED')
        self.assertNotEqual(stopped['exit_code'], 0)

    def slow_collection(self, stage, outcome, trigger):
        directory = ensure_private_directory(self.root / (stage + '-' + outcome + '-' + trigger))
        with os.fdopen(open_private_file(directory / 'receipt.key'), 'wb') as stream:
            stream.write(os.urandom(32))
        output = self.root / (directory.name + '-output')
        output.mkdir()
        spec = {'command': [self.python, '-c', 'import time;time.sleep(30)'],
                'identity': self.identity, 'env': dict(os.environ),
                'budget_seconds': .1 if trigger == 'session' else 2,
                'resource_budget': {'roots': [str(output)], 'max_bytes': 4096},
                'writer_executable': self.writer}
        spec, process = self.writer_child(directory, spec)
        entered = threading.Event()
        completed = threading.Event()
        release = threading.Event()
        errors = []
        signed_starts = []
        sign = owned_process._signed_write

        def record_signed(target, payload):
            if payload['event'] == 'started':
                signed_starts.append(owned_process._canonical(payload))
            return sign(target, payload)

        def slow(*args, **kwargs):
            entered.set()
            release.wait(1)
            completed.set()
            if outcome == 'error':
                raise ValueError('slow collection failed')
            return deepcopy(self.writer) if stage == 'freeze' else self.anchor(process.pid)

        def supervise():
            try:
                owned_process._supervise_owned(directory, spec, process)
            except BaseException as error:
                errors.append(error)

        freeze = slow if stage == 'freeze' else lambda *args, **kwargs: deepcopy(self.writer)
        observe = slow if stage == 'observe' else self.anchor
        worker = threading.Thread(target=supervise)
        try:
            with mock.patch.object(process_image, 'freeze_executable', side_effect=freeze), \
                    mock.patch.object(process_image, '_ps', side_effect=lambda pid, deadline: self.ps(pid, deadline, directory)), \
                    mock.patch.object(process_image, '_observe', side_effect=observe), \
                    mock.patch.object(owned_process, '_signed_write', side_effect=record_signed):
                worker.start()
                self.assertTrue(entered.wait(1), 'collector did not enter the slow phase')
                if trigger == 'cancel':
                    owned_process._atomic(directory / 'cancel.json', {'identity': self.identity})
                elif trigger == 'disk':
                    (output / 'overflow').write_bytes(b'x' * 8192)
                # Inspect the actual owned child while collection is still
                # blocked; checking a later stop receipt cannot detect P2.
                limit = time.monotonic() + .3
                while process.poll() is None and time.monotonic() < limit:
                    time.sleep(.005)
                self.assertIsNotNone(process.poll(), 'owned child survived while collection blocked supervision')
                self.assertFalse(completed.is_set(), 'collector finished before the liveness assertion')
                limit = time.monotonic() + .3
                while not (directory / 'started.json').exists() and time.monotonic() < limit:
                    time.sleep(.005)
                started = owned_process.read_receipt(directory, 'started', identity=self.identity)
                self.assertIsNotNone(started)
                self.assertIn('writer_process_binding_error', started)
                self.assertNotIn('writer_process_binding', started)
                original = (directory / 'started.json').read_bytes()
                release.set()
                self.assertTrue(completed.wait(1))
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual((directory / 'started.json').read_bytes(), original)
                self.assertEqual(len(signed_starts), 1)
                stopped = owned_process.read_receipt(directory, 'stopped', identity=self.identity)
                self.assertIsNotNone(stopped)
                self.assertEqual(stopped['stop_reason'], {'session': 'TIME_BUDGET_EXCEEDED',
                    'cancel': 'CANCEL_REQUESTED', 'disk': 'DISK_BUDGET_EXCEEDED'}[trigger])
                self.assertEqual(stopped['observed_by'], 'owned_child_wait')
                self.assertNotEqual(owned_process.execution_returncode(stopped), 0)
                self.assertEqual(stopped['started_sha256'], hashlib.sha256(
                    owned_process._canonical(started)).hexdigest())
        finally:
            release.set()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if worker.ident is not None:
                worker.join(3)

    def test_slow_freeze_and_observe_do_not_delay_session_budget_or_accept_late_anchor(self):
        for stage in ('freeze', 'observe'):
            for outcome in ('error', 'success'):
                with self.subTest(stage=stage, outcome=outcome):
                    self.slow_collection(stage, outcome, 'session')

    def test_slow_collection_keeps_cancellation_and_disk_supervision_active(self):
        for stage in ('freeze', 'observe'):
            for trigger in ('cancel', 'disk'):
                with self.subTest(stage=stage, trigger=trigger):
                    self.slow_collection(stage, 'success', trigger)

    def test_slow_success_within_budget_authenticates_live_child_once(self):
        directory = ensure_private_directory(self.root / 'slow-valid')
        with os.fdopen(open_private_file(directory / 'receipt.key'), 'wb') as stream:
            stream.write(os.urandom(32))
        command = [self.python, '-c', 'import time;time.sleep(.3)']
        spec = {'command': command, 'identity': self.identity, 'env': dict(os.environ),
                'resource_budget': None, 'budget_seconds': 1, 'writer_executable': self.writer}
        spec, process = self.writer_child(directory, spec)
        signed = []
        sign = owned_process._signed_write

        def delayed(value):
            time.sleep(.05)
            return deepcopy(value)

        def record(target, payload):
            if payload['event'] == 'started':
                self.assertIsNone(process.poll())
                signed.append(owned_process._canonical(payload))
            return sign(target, payload)

        try:
            with mock.patch.object(process_image, 'freeze_executable', side_effect=lambda *args: delayed(self.writer)), \
                    mock.patch.object(process_image, '_ps', side_effect=lambda pid, deadline: self.ps(pid, deadline, directory)), \
                    mock.patch.object(process_image, '_observe', side_effect=lambda pid, *args, **kwargs: delayed(self.anchor(pid))), \
                    mock.patch.object(owned_process, '_signed_write', side_effect=record):
                self.assertEqual(owned_process._supervise_owned(directory, spec, process), 0)
            self.assertEqual(len(signed), 1)
            started = owned_process.read_receipt(directory, 'started', identity=self.identity)
            self.assertEqual(started['writer_process_binding'], {
                'expected_executable': self.writer, 'host_anchor': self.anchor(process.pid)})
            self.assertNotIn('writer_process_binding_error', started)
            stopped = owned_process.read_receipt(directory, 'stopped', identity=self.identity)
            self.assertEqual(owned_process.execution_returncode(stopped), 0)
            self.assertIsNone(stopped['stop_reason'])
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

    def test_collection_timeout_stops_live_child_without_rewriting_start(self):
        directory = ensure_private_directory(self.root / 'collection-timeout')
        with os.fdopen(open_private_file(directory / 'receipt.key'), 'wb') as stream:
            stream.write(os.urandom(32))
        command = [self.python, '-c', 'import time;time.sleep(30)']
        spec = {'command': command, 'identity': self.identity, 'env': dict(os.environ),
                'resource_budget': None, 'budget_seconds': 2, 'writer_executable': self.writer}
        with mock.patch.object(owned_process, 'WRITER_COLLECTION_SECONDS', .1):
            spec, process = self.writer_child(directory, spec)
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        errors = []

        def blocked(pid, *args, **kwargs):
            entered.set()
            release.wait(1)
            completed.set()
            return self.anchor(pid)

        def supervise():
            try:
                owned_process._supervise_owned(directory, spec, process)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=supervise)
        try:
            with mock.patch.object(process_image, 'freeze_executable', return_value=self.writer), \
                    mock.patch.object(process_image, '_ps', side_effect=lambda pid, deadline: self.ps(pid, deadline, directory)), \
                    mock.patch.object(process_image, '_observe', side_effect=blocked), \
                    mock.patch.object(owned_process, 'WRITER_COLLECTION_SECONDS', .1):
                worker.start()
                self.assertTrue(entered.wait(1))
                limit = time.monotonic() + .5
                while not (directory / 'started.json').exists() and time.monotonic() < limit:
                    time.sleep(.005)
                started = owned_process.read_receipt(directory, 'started', identity=self.identity)
                self.assertEqual(started['writer_process_binding_error'], 'SUPERVISOR_WRITER_COLLECTION_TIMEOUT')
                self.assertNotIn('writer_process_binding', started)
                worker.join(.5)
                self.assertFalse(worker.is_alive(), 'collection timeout must stop the owned child')
                self.assertIsNotNone(process.poll())
                self.assertFalse(completed.is_set())
                original = (directory / 'started.json').read_bytes()
                release.set()
                self.assertTrue(completed.wait(1))
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual((directory / 'started.json').read_bytes(), original)
                stopped = owned_process.read_receipt(directory, 'stopped', identity=self.identity)
                self.assertEqual(stopped['stop_reason'], 'SUPERVISOR_WRITER_COLLECTION_FAILED')
                self.assertNotEqual(owned_process.execution_returncode(stopped), 0)
        finally:
            release.set()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if worker.ident is not None:
                worker.join(3)

    def ready(self):
        work = ensure_private_directory(self.root / 'ready-work')
        directory = work / 'supervisor-nonce'
        directory.mkdir()
        host_identity = {**self.identity, 'pid': 1234, 'version': self.version,
                         'plugin_build': 'build', 'session_id': 'session',
                         'process_generation': 1, 'scene_epoch': 1}
        supervisor = {'directory': str(directory), 'identity': self.identity}
        (work / 'host.ready').write_text(json.dumps({'task_host_identity': host_identity, 'port': 12345}))
        (work / 'supervisor-binding.json').write_text(json.dumps(supervisor))
        state = self.root / 'houdini-instances/instances'
        state.mkdir(parents=True)
        (state / '1234.json').write_text(json.dumps({'token_file': 'token'}))
        (state / 'token').write_text('secret')
        observed = mock.Mock(pid=1234, identity=self.identity, directory=directory)
        observed.poll.return_value = None
        observed.started = {'identity': self.identity, 'pid': 1234,
                            'writer_process_binding': {'expected_executable': deepcopy(self.writer),
                                                       'host_anchor': self.anchor(1234)}}
        return work, host_identity, observed

    def test_production_bind_requires_ready_digest_and_signed_expected_anchor(self):
        work, host_identity, observed = self.ready()
        config = self.config(writer_executable=self.writer, plugin_build='build')
        with mock.patch.object(production_hosts, 'OwnedProcessHandle', return_value=observed), \
                mock.patch.object(process_image, 'freeze_executable', return_value=self.writer), \
                mock.patch('houdini_bridge.client.HoudiniClient') as client:
            client.return_value.health.return_value = {'task_host_identity': host_identity}
            bound = production_hosts._h_config(config, work, self.root, task_id=self.identity['task_id'])
            self.assertEqual(bound['expected_identity'], host_identity)
            valid_start = deepcopy(observed.started)
            mutations = [
                lambda start: start.pop('writer_process_binding'),
                lambda start: start.update(writer_process_binding_error='denied'),
                lambda start: start['writer_process_binding']['host_anchor'].update(pid=999),
                lambda start: start['writer_process_binding']['expected_executable']['image']['stat'].update(inode=999),
                lambda start: start.update(identity={**self.identity, 'writer_executable_sha256': 'b' * 64}),
            ]
            for mutate in mutations:
                observed.started = deepcopy(valid_start)
                mutate(observed.started)
                with self.subTest(start=observed.started), self.assertRaisesRegex(ValueError, 'DEPLOYMENT_IDENTITY_MISMATCH'):
                    production_hosts._h_config(config, work, self.root, task_id=self.identity['task_id'])
            observed.started = valid_start
            invalid = {key: value for key, value in host_identity.items() if key != 'writer_executable_sha256'}
            (work / 'host.ready').write_text(json.dumps({'task_host_identity': invalid, 'port': 12345}))
            with self.assertRaisesRegex(ValueError, 'DEPLOYMENT_IDENTITY_MISMATCH'):
                production_hosts._h_config(config, work, self.root, task_id=self.identity['task_id'])

    def test_production_rechecks_health_digest_and_local_frozen_identity(self):
        work, host_identity, observed = self.ready()
        config = self.config(writer_executable=self.writer, plugin_build='build')
        with mock.patch.object(production_hosts, 'OwnedProcessHandle', return_value=observed), \
                mock.patch.object(process_image, 'freeze_executable', return_value=self.writer) as freeze, \
                mock.patch('houdini_bridge.client.HoudiniClient') as client:
            client.return_value.health.return_value = {'task_host_identity': {
                **host_identity, 'writer_executable_sha256': '0' * 64}}
            with self.assertRaisesRegex(ValueError, 'DEPLOYMENT_IDENTITY_MISMATCH'):
                production_hosts._h_config(config, work, self.root, task_id=self.identity['task_id'])
            changed = deepcopy(self.writer)
            changed['image']['stat']['size'] += 1
            freeze.return_value = changed
            with self.assertRaisesRegex(ValueError, 'DEPLOYMENT_IDENTITY_MISMATCH'):
                production_hosts._h_config(config, work, self.root, task_id=self.identity['task_id'])

    def test_canonical_payloads_use_utf8_and_reject_nan(self):
        self.assertIn('软件'.encode('utf-8'), owned_process._canonical(self.writer))
        with self.assertRaises(ValueError):
            owned_process._canonical({'value': float('nan')})


if __name__ == '__main__':
    unittest.main()
