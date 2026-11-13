import json
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from dcc_task_runtime import owned_process
from dcc_task_runtime.owned_process import launch, OwnedProcessHandle, read_receipt
from dcc_task_runtime.platform_support import ensure_private_directory, open_private_file, process_identity, process_status

class OwnedSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.identity={'task_id':'t','operation_id':'op','nonce':'unique-launch'}

    def test_writer_readiness_uses_remaining_collection_budget_and_preserves_identity(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from unittest.mock import Mock
        import queue
        scenarios = ('late_ready', 'expired_ready', 'parent_changed', 'birth_changed',
                     'cancel_ready', 'cancel_observe', 'late_observe')
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                clock = [0.0]
                holder = {}
                class Thread:
                    def __init__(self, target, **kwargs): self.target = target
                    def start(self): holder['run'] = self.target
                images = SimpleNamespace(OBSERVE_TIMEOUT_SECONDS=16,
                    ProcessImageError=type('ImageError', (Exception,), {}),
                    _ps=Mock(return_value=(10, 100)),
                    _birth=lambda value: datetime.fromtimestamp(value, timezone.utc))
                def ready(directory, spec, pid, cancelled, deadline):
                    self.assertEqual(deadline, 22)
                    clock[0] = 23 if scenario == 'expired_ready' else 17
                    if clock[0] >= deadline: raise ValueError('SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT')
                    if scenario == 'cancel_ready': cancelled.set()
                def observe(pid, deadline):
                    self.assertEqual(deadline, 22)
                    clock[0] = 23 if scenario == 'late_observe' else 18
                    if scenario == 'cancel_observe': cancelled.set()
                    return {'pid': pid, 'parent_pid': 11 if scenario == 'parent_changed' else 10,
                            'birth': 101 if scenario == 'birth_changed' else 100}
                images._observe = Mock(side_effect=observe)
                with patch.object(owned_process, '_process_images', return_value=images), \
                     patch.object(owned_process, '_freeze_writer_executable', return_value={}), \
                     patch.object(owned_process, '_wait_writer_runtime_ready', side_effect=ready), \
                     patch.object(owned_process.threading, 'Thread', Thread), \
                     patch.object(owned_process.time, 'monotonic', side_effect=lambda: clock[0]):
                    results, cancelled = owned_process._start_writer_collection({}, 123,
                        spec={'writer_runtime': {'collection_end': 22, 'session_end': 120}})
                    holder['run']()
                if scenario.startswith('cancel'):
                    self.assertTrue(results.empty())
                else:
                    kind, result = results.get_nowait()
                    self.assertEqual(kind, 'writer_process_binding' if scenario == 'late_ready' else 'writer_process_binding_error')
                    if scenario in ('parent_changed', 'birth_changed'):
                        self.assertIn('ANCHOR_CHANGED', result)
                    if scenario == 'late_observe': self.assertIn('COLLECTION_TIMEOUT', result)
                if scenario in ('cancel_ready', 'expired_ready'): images._observe.assert_not_called()

    def test_runtime_ready_authenticates_exact_attempt_and_rejects_invalid_events(self):
        import threading
        from copy import deepcopy
        for failure in ('valid', 'signature', 'nonce', 'pid', 'argv', 'identity', 'symlink', 'broken-symlink', 'cancelled', 'timeout', 'missing', 'malformed'):
            with self.subTest(failure=failure):
                directory = self.root.resolve()/('ready-'+failure); directory.mkdir()
                (directory/'receipt.key').write_bytes(os.urandom(32))
                spec = owned_process._writer_runtime_spec(directory, {'identity':self.identity,
                    'command':['fixed-software-writer'], 'budget_seconds':1, 'writer_executable':{},
                    'env':{key:'stale' for key in owned_process._READY_ENV}})
                self.assertEqual(spec['env']['BRIDGE_OWNED_SUPERVISOR_DIR'], str(directory))
                self.assertEqual(spec['env']['BRIDGE_OWNED_SUPERVISOR_IDENTITY'],
                    owned_process._canonical(self.identity).decode())
                payload = {'schema':owned_process.SCHEMA, 'event':'runtime-ready', 'identity':deepcopy(self.identity),
                    'pid':1234, 'argv_sha256':hashlib.sha256(owned_process._canonical(spec['command'])).hexdigest(),
                    'runtime_nonce':spec['writer_runtime']['nonce'], 'observed_at':time.time()}
                if failure == 'nonce': payload['runtime_nonce'] = '0'*32
                elif failure == 'pid': payload['pid'] += 1
                elif failure == 'argv': payload['argv_sha256'] = '0'*64
                elif failure == 'identity': payload['identity']['nonce'] = 'other-attempt'
                elif failure == 'malformed': payload['verified'] = True
                if failure != 'missing': owned_process._signed_write(directory, payload)
                if failure == 'signature':
                    envelope = json.loads((directory/'runtime-ready.json').read_text())
                    envelope['signature']='0'*64;(directory/'runtime-ready.json').write_text(json.dumps(envelope))
                elif failure == 'symlink':
                    (directory/'runtime-ready.json').rename(directory/'event-original')
                    (directory/'runtime-ready.json').symlink_to(directory/'event-original')
                elif failure == 'broken-symlink':
                    (directory/'runtime-ready.json').unlink()
                    (directory/'runtime-ready.json').symlink_to(directory/'missing-event')
                cancelled = threading.Event()
                if failure == 'cancelled': cancelled.set()
                deadline = time.monotonic()-1 if failure == 'timeout' else spec['writer_runtime']['collection_end']
                if failure == 'missing':
                    with patch.object(owned_process.time,'monotonic',side_effect=[deadline-.1,deadline]), \
                         patch.object(owned_process.time,'sleep'), self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):
                        owned_process._wait_writer_runtime_ready(directory,spec,1234,cancelled,deadline)
                elif failure == 'valid':
                    owned_process._wait_writer_runtime_ready(directory,spec,1234,cancelled,deadline)
                else:
                    with self.assertRaises(ValueError):
                        owned_process._wait_writer_runtime_ready(directory,spec,1234,cancelled,deadline)

    def test_runtime_ready_child_holds_for_binding_and_never_continues_after_failure(self):
        from copy import deepcopy
        for outcome in ('binding', 'writer-error', 'cancel', 'timeout', 'environment', 'wrong-child'):
            with self.subTest(outcome=outcome):
                directory = self.root.resolve()/('hold-'+outcome);directory.mkdir()
                (directory/'receipt.key').write_bytes(os.urandom(32))
                spec = owned_process._writer_runtime_spec(directory, {'identity':self.identity,
                    'command':['fixed-software-writer'], 'budget_seconds':1, 'writer_executable':{}, 'env':{}})
                owned_process._atomic(directory/'intent.json',spec)
                command_hash=hashlib.sha256(owned_process._canonical(spec['command'])).hexdigest()
                started={'schema':owned_process.SCHEMA,'event':'started','identity':self.identity,
                    'pid':os.getpid(),'argv_sha256':command_hash,
                    'writer_process_binding':{'expected_executable':{},'host_anchor':{'pid':os.getpid()}}}
                clock=[time.monotonic()];holds=[]
                def release(seconds):
                    ready=read_receipt(directory,'runtime-ready',identity=self.identity)
                    self.assertEqual(ready['pid'],os.getpid())
                    self.assertEqual(ready['argv_sha256'],command_hash)
                    self.assertIsNone(read_receipt(directory,'started',identity=self.identity))
                    holds.append(True)
                    if outcome=='cancel':owned_process._atomic(directory/'cancel.json',{'identity':self.identity})
                    elif outcome=='timeout':clock[0]=spec['writer_runtime']['collection_end']
                    else:
                        result=deepcopy(started)
                        if outcome=='writer-error':
                            result.pop('writer_process_binding');result['writer_process_binding_error']='original writer cause'
                        elif outcome=='wrong-child':result['pid']+=1
                        owned_process._signed_write(directory,result)
                environment=dict(spec['env'])
                if outcome=='environment':environment['BRIDGE_OWNED_SUPERVISOR_IDENTITY']='{}'
                with patch.dict(os.environ,environment,clear=True), \
                     patch.object(owned_process.time,'monotonic',side_effect=lambda:clock[0]), \
                     patch.object(owned_process.time,'sleep',side_effect=release):
                    if outcome=='binding':owned_process.runtime_ready_and_wait()
                    else:
                        with self.assertRaises(ValueError):owned_process.runtime_ready_and_wait()
                self.assertEqual(len(holds),0 if outcome=='environment' else 1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX software child supervision')
    def test_wrong_pid_ready_event_stops_owned_child_before_any_vmmap(self):
        from dcc_task_runtime import process_image
        directory=self.root.resolve()/'wrong-pid-ready';directory.mkdir()
        (directory/'receipt.key').write_bytes(os.urandom(32))
        command=[sys.executable,'-c','import time;time.sleep(30)']
        spec=owned_process._writer_runtime_spec(directory,{'identity':self.identity,'command':command,
            'budget_seconds':2,'writer_executable':{},'env':dict(os.environ)})
        child=subprocess.Popen(command,start_new_session=True)
        owned_process._signed_write(directory,{'schema':owned_process.SCHEMA,'event':'runtime-ready',
            'identity':self.identity,'pid':child.pid+1,'runtime_nonce':spec['writer_runtime']['nonce'],
            'argv_sha256':hashlib.sha256(owned_process._canonical(command)).hexdigest(),'observed_at':time.time()})
        try:
            with patch.object(owned_process,'_freeze_writer_executable',return_value={}), \
                 patch.object(process_image,'_ps',return_value=(os.getpid(),1234)), \
                 patch.object(process_image,'_vmmap',side_effect=AssertionError('ready must precede vmmap')) as vmmap:
                owned_process._supervise_owned(directory,spec,child)
            vmmap.assert_not_called()
            started=read_receipt(directory,'started',identity=self.identity)
            stopped=read_receipt(directory,'stopped',identity=self.identity)
            self.assertIn('RUNTIME_READY_MISMATCH',started['writer_process_binding_error'])
            self.assertEqual(stopped['execution_result'],'failed')
            self.assertEqual(stopped['stop_reason'],'SUPERVISOR_WRITER_COLLECTION_FAILED')
            self.assertNotEqual(owned_process.execution_returncode(stopped),0)
        finally:
            if child.poll() is None:child.kill()
            child.wait(timeout=3)

    @unittest.skipUnless(os.name == 'posix', 'POSIX software supervision state machine')
    def test_started_write_recovery_cannot_release_a_valid_binding_after_failure(self):
        import errno, queue, threading, signal
        from types import SimpleNamespace
        from unittest.mock import Mock
        directory=self.root.resolve()/'start-recovery';directory.mkdir()
        (directory/'receipt.key').write_bytes(os.urandom(32))
        clock=[0.];process=SimpleNamespace(pid=123456,poll=lambda:None if clock[0]<1 else 0,wait=lambda:0)
        results=queue.Queue();results.put(('writer_process_binding',{'expected_executable':{},'host_anchor':{'pid':process.pid}}))
        scope=Mock();original=owned_process._signed_write;writes=[]
        def write(target,payload):
            writes.append(payload['event'])
            if payload['event']=='started' and writes.count('started')==1:
                raise OSError(errno.ENOSPC,'fixture initial write failed')
            return original(target,payload)
        def signal_group(pid,signum):
            if signum==0:raise ProcessLookupError()
        spec={'identity':self.identity,'command':['fixed-software-writer'],'budget_seconds':2,
              'writer_executable':{},'native_scope_ticket':'ticket'}
        with patch.object(owned_process,'_signed_write',side_effect=write), \
             patch.object(owned_process,'_start_writer_collection',return_value=(results,threading.Event())), \
             patch.object(owned_process.os,'killpg',side_effect=signal_group) as signals, \
             patch.object(owned_process.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(owned_process.time,'sleep',side_effect=lambda _:clock.__setitem__(0,clock[0]+.5)):
            self.assertEqual(owned_process._supervise_owned(directory,spec,process,native_scope=scope),2)
        started=read_receipt(directory,'started',identity=self.identity)
        self.assertIn('writer_process_binding',started)
        self.assertEqual(started['writer_process_binding_error'],'SUPERVISOR_WRITER_START_WRITE_FAILED')
        self.assertIn(unittest.mock.call(process.pid,signal.SIGTERM),signals.call_args_list)
        stopped=read_receipt(directory,'stopped',identity=self.identity)
        self.assertEqual(stopped['stop_reason'],'SUPERVISOR_WRITER_START_WRITE_FAILED')
        self.assertEqual(stopped['execution_result'],'failed')

    def test_shared_native_scope_observes_real_software_child_and_denies_unscoped_retry(self):
        from dcc_task_runtime.native_scope import NativeScope, _BUDGET
        from test_native_scope import software_scope
        root=self.root.resolve()
        frozen=root/'frozen'/'dcc_task_runtime';frozen.mkdir(parents=True)
        runtime=Path(owned_process.__file__).resolve().parent
        for source in runtime.rglob('*.py'):
            target=frozen/source.relative_to(runtime)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        def fingerprint():
            return {str(path.relative_to(frozen)):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in frozen.rglob('*') if path.is_file()}
        original=fingerprint()
        controller_import=patch.object(sys,'dont_write_bytecode',True)
        controller_import.start();self.addCleanup(controller_import.stop)
        spec=importlib.util.spec_from_file_location('frozen_owned_supervisor',frozen/'owned_process.py')
        supervisor=importlib.util.module_from_spec(spec);spec.loader.exec_module(supervisor)
        binding=software_scope(root)
        budget={'roots':[str(root)],'max_bytes':_BUDGET['max_disk_bytes'],'native_scope':binding}
        directory=root/'scoped-python'
        environment={key:value for key,value in os.environ.items()
                     if key not in ('PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX')}
        # The supervisor inherits the controller environment independently of
        # the explicit business-child environment. Neither may mask this check.
        with patch.dict(os.environ,environment,clear=True):
            handle=supervisor.launch([sys.executable,'-c','pass'],directory=directory,identity=self.identity,
                supervisor_executable=sys.executable,env=environment,resource_budget=budget,scope_role='alpha-husk')
            try:self.assertEqual(handle.wait(5),0)
            finally:
                if handle.poll() is None:handle.terminate();handle.wait(5)
        self.assertEqual(supervisor.read_receipt(directory,'started',identity=self.identity)['identity'],self.identity)
        self.assertEqual(supervisor.execution_returncode(supervisor.read_receipt(directory,'stopped',identity=self.identity)),0)
        current=fingerprint()
        self.assertEqual(set(current),set(original))
        self.assertEqual(current,original)
        state=NativeScope(binding).check()
        self.assertEqual(state['dcc_starts'],1)
        snapshot=NativeScope(binding).snapshot()
        self.assertIsNotNone(snapshot['tickets'][0]['stopped_at'])
        with self.assertRaisesRegex(ValueError,'AUTOMATIC_RETRY_FORBIDDEN'):
            launch([sys.executable,'-c','pass'],directory=directory,identity=self.identity,
                supervisor_executable=sys.executable,resource_budget=budget,scope_role='alpha-husk')
        with self.assertRaisesRegex(ValueError,'PROPAGATION_REQUIRED'):
            launch([sys.executable,'-c','pass'],directory=root/'outside-budget',identity={'task_id':'other'},
                supervisor_executable=sys.executable,env={'BRIDGE_NATIVE_SCOPE_BINDING':json.dumps(binding)})
        self.assertFalse((root/'outside-budget').exists())
    @unittest.skipUnless(os.name == 'posix', 'POSIX software child supervision')
    def test_writer_tool_failure_diagnostic_is_signed_and_not_a_process_binding(self):
        from dcc_task_runtime import process_image
        directory = self.root.resolve()/'writer-failure';directory.mkdir()
        (directory/'receipt.key').write_bytes(os.urandom(32))
        release = directory/'binding-collected'
        command = [sys.executable, '-B', '-c',
                   'import pathlib,sys,time;p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.01)',
                   str(release)]
        child = subprocess.Popen(command, start_new_session=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        tool = [str(Path(sys.executable).resolve()), '-B', '-c',
                'import sys;sys.stderr.buffer.write(bytes([255,0,254]));sys.exit(7)']
        def observe(pid, *args, **kwargs):
            self.assertEqual(pid, child.pid)
            return process_image._run_tool(tool, time.monotonic()+process_image.TOOL_TIMEOUT_SECONDS+1)
        spec = {'identity': self.identity, 'command': command, 'budget_seconds': 5,
                'writer_executable': {'software_test_only': True}}
        signals = []
        send_signal = owned_process._signal_group
        sleep = time.sleep
        def request_signal(process, signum):
            signals.append(signum)
            return send_signal(process, signum)
        def wait_for_collection(seconds):
            if (directory/'started.json').exists():
                self.assertTrue(signals, 'signed collection error must signal before the next supervisor sleep')
            sleep(seconds)
        with patch.object(owned_process, '_freeze_writer_executable', return_value={}), \
             patch.object(owned_process, '_wait_writer_runtime_ready', return_value=None), \
             patch.object(process_image, '_observe', side_effect=observe), \
             patch.object(owned_process, '_signal_group', side_effect=request_signal), \
             patch.object(owned_process.time, 'sleep', side_effect=wait_for_collection):
            result = owned_process._supervise_owned(directory, spec, child)
        started = read_receipt(directory, 'started', identity=self.identity)
        self.assertEqual(started['writer_process_binding_error'], 'ProcessImageError:PROCESS_IMAGE_TOOL_FAILED')
        self.assertNotIn('writer_process_binding', started)
        diagnostic = started['writer_process_binding_diagnostic']
        self.assertEqual(diagnostic['exit_code'], 7)
        self.assertEqual(diagnostic['tool_argv'], tool)
        self.assertEqual(bytes.fromhex(diagnostic['stderr_hex']), bytes([255,0,254]))
        stopped = read_receipt(directory, 'stopped', identity=self.identity)
        self.assertEqual(result, stopped['supervisor_exit_code'])
        self.assertNotEqual(owned_process.execution_returncode(stopped), 0)
        self.assertEqual(stopped['execution_result'], 'failed')
        self.assertEqual(stopped['stop_reason'], 'SUPERVISOR_WRITER_COLLECTION_FAILED')
        self.assertFalse(release.exists())
        self.assertEqual(stopped['started_sha256'], hashlib.sha256(owned_process._canonical(started)).hexdigest())
        envelope = json.loads((directory/'started.json').read_text())
        envelope['payload']['writer_process_binding_diagnostic']['exit_code'] = 0
        (directory/'started.json').write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, 'RECEIPT_MISMATCH'):
            read_receipt(directory, 'started', identity=self.identity)
        with patch.object(owned_process, '_process_images', side_effect=ImportError('software missing module')):
            result, cancelled = owned_process._start_writer_collection({}, child.pid)
            self.assertEqual(result.get(timeout=1), ('writer_process_binding_error', 'ImportError:software missing module'))
            cancelled.set()

    @unittest.skipUnless(os.name == 'posix', 'POSIX software child supervision')
    def test_writer_error_receipt_io_failure_still_stops_without_releasing_scope(self):
        import errno
        from unittest.mock import Mock
        from dcc_task_runtime import process_image
        directory = self.root.resolve()/'writer-write-failure'; directory.mkdir()
        (directory/'receipt.key').write_bytes(os.urandom(32))
        command = [sys.executable, '-c', 'import time;time.sleep(30)']
        child = subprocess.Popen(command, start_new_session=True)
        scope = Mock()
        scope.scope = {}  # Explicit legacy scope; collection failure below is intentional.
        spec = {'identity': self.identity, 'command': command, 'budget_seconds': 5,
                'writer_executable': {}, 'native_scope_ticket': 'unreleased'}
        sign = owned_process._signed_write
        def write(target, payload):
            if payload['event'] == 'started':
                self.assertEqual(payload['writer_process_binding_error'], 'ValueError:original collection cause')
                raise OSError(errno.ENOSPC, 'fixture started write denied')
            return sign(target, payload)
        try:
            with patch.object(owned_process, '_freeze_writer_executable', return_value={}), \
                 patch.object(owned_process, '_wait_writer_runtime_ready', return_value=None), \
                 patch.object(process_image, '_observe', side_effect=ValueError('original collection cause')), \
                 patch.object(owned_process, '_signed_write', side_effect=write):
                self.assertEqual(owned_process._supervise_owned(directory, spec, child, native_scope=scope), 2)
            self.assertIsNotNone(child.poll())
            with self.assertRaises(ProcessLookupError): os.killpg(child.pid, 0)
            self.assertIsNone(read_receipt(directory, 'started', identity=self.identity))
            self.assertIsNone(read_receipt(directory, 'stopped', identity=self.identity))
            scope.finish.assert_not_called()
        finally:
            if child.poll() is None: child.kill()
            child.wait(timeout=3)

    @unittest.skipUnless(sys.platform == 'darwin', 'real macOS writer process collection')
    def test_real_writer_executable_binding_is_signed_and_stopped(self):
        from dcc_task_runtime import process_image
        retained=os.environ.get('BRIDGE_PROCESS_WRITER_EVIDENCE')
        directory=Path(retained) if retained else self.root.resolve()/'native-writer'
        release=directory.parent/(directory.name+'-release')
        executable=(Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python').resolve()
        expected=process_image.freeze_executable(str(executable),'ordinary-python-writer-test',
            hashlib.sha256(executable.read_bytes()).hexdigest())
        command=[str(executable),'-B','-c',
            'import pathlib,sys,time;sys.path.insert(0,sys.argv[2]);'
            'from dcc_task_runtime.owned_process import runtime_ready_and_wait;runtime_ready_and_wait();'
            'p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.01)',
            str(release),str(Path(owned_process.__file__).resolve().parents[1])]
        handle=launch(command,directory=directory,identity=self.identity,
            supervisor_executable=sys.executable,writer_executable=expected)
        try:
            started=read_receipt(directory,'started',identity=self.identity)
            self.assertNotIn('writer_process_binding_error',started)
            binding=started['writer_process_binding']
            self.assertEqual(binding['expected_executable'],expected)
            anchor=binding['host_anchor']
            process_image._validate_observation(anchor)
            self.assertEqual(anchor['pid'],started['pid'])
            self.assertEqual(anchor['image'],expected['image'])
            self.assertEqual(started['identity'],self.identity)
            self.assertEqual(started['argv_sha256'],hashlib.sha256(owned_process._canonical(command)).hexdigest())
            ready=read_receipt(directory,'runtime-ready',identity=self.identity)
            self.assertEqual(ready['pid'],started['pid'])
            release.touch()
            self.assertEqual(handle.wait(10),0)
            stopped=read_receipt(directory,'stopped',identity=self.identity)
            self.assertEqual(owned_process.execution_returncode(stopped),0)
            self.assertEqual(stopped['identity'],self.identity)
            self.assertEqual(stopped['started_sha256'],hashlib.sha256(owned_process._canonical(started)).hexdigest())
        finally:
            release.touch()
            if handle.poll() is None:
                handle.terminate();handle.wait(10)

    def test_restarted_controller_reads_observed_owned_exit(self):
        release=self.root/'release'
        handle=launch([sys.executable,'-c', 'import pathlib,time,sys; p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.01)',str(release)],directory=self.root/'process',identity=self.identity,supervisor_executable=sys.executable)
        self.assertIsNone(handle.poll())
        del handle
        release.touch()
        fresh=OwnedProcessHandle(self.root/'process',self.identity)
        self.assertEqual(fresh.wait(5),0)
        self.assertEqual(fresh.receipt()['observed_by'],'owned_child_wait')
        self.assertGreaterEqual(fresh.receipt()['observed_at'],fresh.started['observed_at'])
    def test_signed_receipt_requires_exact_started_attempt(self):
        handle=launch([sys.executable,'-c','pass'],directory=self.root/'process',identity=self.identity,supervisor_executable=sys.executable)
        handle.wait(5)
        stopped = handle.receipt()
        self.assertEqual(owned_process.execution_returncode(stopped), 0)
        self.assertEqual(owned_process.execution_returncode({'exit_code': 0}), 2)
        self.assertEqual(owned_process.execution_returncode({'exit_code': 7}), 7)
        for change in ({'supervisor_exit_code': False}, {'execution_result': 'unknown'},
                       {'descendant_result_unobserved': None}, {'execution_protocol': True}):
            with self.subTest(change=change):
                owned_process._signed_write(handle.directory, {**stopped, **change})
                with self.assertRaisesRegex(ValueError, 'EXECUTION_NOT_BOUND'):
                    handle.poll()
        for missing in ('execution_protocol', 'supervisor_exit_code', 'execution_result',
                        'descendant_result_unobserved'):
            with self.subTest(missing=missing):
                owned_process._signed_write(handle.directory,
                    {key: value for key, value in stopped.items() if key != missing})
                with self.assertRaisesRegex(ValueError, 'EXECUTION_NOT_BOUND'):
                    handle.poll()
        owned_process._signed_write(handle.directory, stopped)
        with self.assertRaises(ValueError):OwnedProcessHandle(self.root/'process',{**self.identity,'nonce':'wrong'})
        p=self.root/'process'/'stopped.json';v=json.loads(p.read_text());v['payload']['exit_code']=99;p.write_text(json.dumps(v))
        with self.assertRaises(ValueError):handle.poll()
    def test_cancel_is_request_until_supervisor_observes_exit(self):
        handle=launch([sys.executable,'-c','import time; time.sleep(30)'],directory=self.root/'process',identity=self.identity,supervisor_executable=sys.executable)
        self.assertIsNone(handle.poll());handle.terminate()
        self.assertNotEqual(handle.wait(5),0)
        self.assertIsNotNone(handle.receipt())

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
    def test_denied_group_signals_keep_observing_without_releasing_scope(self):
        import errno
        import signal
        from types import SimpleNamespace
        from unittest.mock import Mock
        for deny_term in (True, False):
            with self.subTest(deny_term=deny_term):
                directory = self.root / str(deny_term); directory.mkdir()
                (directory / 'receipt.key').write_bytes(os.urandom(32))
                clock = [0.]
                process = SimpleNamespace(pid=123456, poll=lambda: None if clock[0] < 1. else 0,
                                          wait=lambda: 0)
                scope = Mock()
                calls = []
                def signal_group(pid, signum):
                    self.assertEqual(pid, process.pid)
                    if signum == 0:
                        if clock[0] >= 5.5:
                            raise ProcessLookupError()
                        if deny_term and clock[0] < 2.:
                            raise PermissionError(errno.EPERM, 'fixture group state denied')
                        return
                    calls.append((signum, clock[0]))
                    if signum == signal.SIGKILL or deny_term:
                        raise PermissionError(errno.EPERM, 'fixture signal denied')
                def advance(seconds):
                    self.assertIsNone(read_receipt(directory, 'stopped', identity=self.identity))
                    scope.finish.assert_not_called()
                    clock[0] += .5
                spec = {'identity': self.identity, 'command': ['software-fixture'],
                        'budget_seconds': .1, 'native_scope_ticket': {'id': 'fixture'}}
                with patch.object(owned_process.os, 'killpg', side_effect=signal_group), \
                     patch.object(owned_process.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(owned_process.time, 'sleep', side_effect=advance), \
                     patch.object(owned_process, 'process_identity', return_value={'pid': 42}), \
                     patch.object(owned_process, '_disk_usage', return_value=0):
                    self.assertEqual(owned_process._supervise_owned(directory, spec, process, native_scope=scope), 2)
                self.assertEqual([sig for sig, _ in calls].count(signal.SIGTERM), 1)
                kills = [when for sig, when in calls if sig == signal.SIGKILL]
                self.assertEqual(len(kills), 2)
                self.assertGreaterEqual(kills[1] - kills[0], 2.)
                start = read_receipt(directory, 'started', identity=self.identity)
                for sig in ([0, signal.SIGTERM] if deny_term else []) + [signal.SIGKILL]:
                    denial = read_receipt(directory, 'signal-denied-' + str(int(sig)), identity=self.identity)
                    self.assertEqual(denial['pid'], process.pid)
                    self.assertEqual(denial['signal'], sig)
                    self.assertEqual(denial['started_sha256'], owned_process.hashlib.sha256(owned_process._canonical(start)).hexdigest())
                    self.assertEqual(denial['errno'], errno.EPERM)
                    self.assertEqual(denial['stop_reason'], 'TIME_BUDGET_EXCEEDED')
                stopped = read_receipt(directory, 'stopped', identity=self.identity)
                self.assertEqual(stopped['execution_result'], 'failed')
                self.assertEqual(stopped['stop_reason'], 'TIME_BUDGET_EXCEEDED')
                scope.finish.assert_called_once_with(spec['native_scope_ticket'])

    def test_runtime_disk_growth_stops_owned_child_and_persists_reason(self):
        output=(self.root/'output').resolve();output.mkdir()
        command=[sys.executable,'-c',
                 'import pathlib,time,sys;pathlib.Path(sys.argv[1]).write_bytes(b"x"*8192);time.sleep(30)',
                 str(output/'cache.bin')]
        handle=launch(command,directory=self.root/'process',identity=self.identity,
                      supervisor_executable=sys.executable,
                      resource_budget={'roots':[str(output)],'max_bytes':4096})
        self.assertNotEqual(handle.wait(5),0)
        self.assertEqual(handle.receipt()['stop_reason'],'DISK_BUDGET_EXCEEDED')
        self.assertTrue((output/'cache.bin').exists())
        self.assertGreater(handle.receipt()['observed_bytes'],4096)

    def test_disk_preflight_rejects_before_spawn(self):
        from dcc_task_runtime.owned_process import SupervisorNotStarted
        output=(self.root/'output').resolve();output.mkdir();(output/'existing').write_bytes(b'x'*20)
        marker=self.root/'must-not-exist'
        with self.assertRaisesRegex(SupervisorNotStarted,'DISK_BUDGET_EXCEEDED'):
            launch([sys.executable,'-c','import pathlib,sys;pathlib.Path(sys.argv[1]).touch()',str(marker)],
                   directory=self.root/'process',identity=self.identity,supervisor_executable=sys.executable,
                   resource_budget={'roots':[str(output)],'max_bytes':10})
        self.assertFalse(marker.exists());self.assertFalse((self.root/'process').exists())

    def test_disk_directory_disappearance_after_lstat_is_not_an_unknown_observation(self):
        import errno
        original_iterdir = Path.iterdir
        for action in ('removed', 'permission_denied', 'replaced_by_file'):
            with self.subTest(action=action):
                root = (self.root/action).resolve(); root.mkdir()
                disappearing = root/'temporary'; disappearing.mkdir()
                def raced_iterdir(path):
                    if path == disappearing:
                        if action == 'permission_denied':
                            raise PermissionError(errno.EACCES, 'fixture denied', str(path))
                        disappearing.rmdir()
                        if action == 'replaced_by_file': disappearing.write_bytes(b'changed type')
                    return original_iterdir(path)
                with patch.object(Path, 'iterdir', raced_iterdir):
                    budget = {'roots':[str(root)], 'max_bytes':1024}
                    if action == 'removed':
                        self.assertEqual(owned_process._disk_usage(budget), 0)
                    else:
                        with self.assertRaises(PermissionError if action == 'permission_denied' else NotADirectoryError):
                            owned_process._disk_usage(budget)

    def test_observation_failure_is_signed_once_and_diagnostic_io_failure_cannot_block_stop(self):
        import errno
        import io
        import queue
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock
        for phase, diagnostic_fails, writer_pending in [('native_scope.check',False,False), ('disk_usage',False,False),
                                        ('both',False,False), ('native_scope.check',True,False),
                                        ('native_scope.check',True,True)]:
            with self.subTest(phase=phase, diagnostic_fails=diagnostic_fails, writer_pending=writer_pending):
                directory=(self.root/(phase+str(diagnostic_fails)+str(writer_pending))).resolve();directory.mkdir()
                (directory/'receipt.key').write_bytes(os.urandom(32))
                clock=[0.]; process=SimpleNamespace(pid=123456,poll=lambda:None if clock[0]<1. else 0,wait=lambda:0)
                failure=PermissionError(errno.EACCES,'x'*1024,'p'*1024)
                scope=Mock()
                if phase != 'disk_usage':scope.check.side_effect=failure
                original_write=owned_process._signed_write
                writes=[]
                def write(path,payload):
                    writes.append(payload['event'])
                    if writer_pending and payload['event']=='started' and writes.count('started')==1:
                        raise OSError(errno.ENOSPC,'fixture pending started write failed')
                    if diagnostic_fails and payload['event']=='observation-failed':
                        raise OSError(errno.ENOSPC,'fixture diagnostic write failed')
                    return original_write(path,payload)
                def advance(seconds):
                    self.assertIsNone(read_receipt(directory,'stopped',identity=self.identity))
                    scope.finish.assert_not_called();clock[0]+=.5
                def disk(budget):
                    if phase in ('disk_usage','both'):raise failure
                    return 0
                stderr=io.StringIO()
                with patch.object(owned_process,'_signed_write',side_effect=write), \
                     patch.object(owned_process,'_disk_usage',side_effect=disk), \
                     patch.object(owned_process,'process_identity',return_value={'pid':42}), \
                     patch.object(owned_process,'_start_writer_collection',return_value=(queue.Queue(),threading.Event())), \
                     patch.object(owned_process.os,'killpg',side_effect=lambda pid,sig:(_ for _ in ()).throw(ProcessLookupError()) if sig==0 else None) as signals, \
                     patch.object(owned_process.time,'monotonic',side_effect=lambda:clock[0]), \
                     patch.object(owned_process.time,'sleep',side_effect=advance), \
                     patch.object(owned_process.sys,'stderr',stderr):
                    spec={'identity':self.identity,'command':['software-fixture'],'budget_seconds':10.,'native_scope_ticket':'ticket'}
                    if writer_pending:spec['writer_executable']={}
                    self.assertEqual(owned_process._supervise_owned(directory,spec,process,native_scope=scope),2)
                self.assertEqual(writes.count('observation-failed'),0 if writer_pending else 1)
                self.assertEqual(writes.count('started'),2 if writer_pending else 1);self.assertEqual(writes.count('stopped'),1)
                import signal
                self.assertIn(unittest.mock.call(process.pid,signal.SIGTERM),signals.call_args_list)
                stop=read_receipt(directory,'stopped',identity=self.identity)
                self.assertEqual(stop['stop_reason'],'DISK_BUDGET_UNOBSERVABLE' if phase in ('disk_usage','both') else 'NATIVE_SCOPE_BUDGET_EXCEEDED_OR_UNOBSERVABLE')
                self.assertEqual(stop['execution_result'],'failed');scope.finish.assert_called_once_with('ticket')
                diagnostic=read_receipt(directory,'observation-failed',identity=self.identity)
                if diagnostic_fails:
                    self.assertIsNone(diagnostic)
                    self.assertEqual(stderr.getvalue(),'SUPERVISOR_OBSERVATION_DIAGNOSTIC_WRITE_FAILED\n')
                else:
                    self.assertEqual(diagnostic['phase'],'disk_usage' if phase=='disk_usage' else 'native_scope.check')
                    self.assertEqual(diagnostic['exception_type'],'PermissionError')
                    self.assertEqual(diagnostic['errno'],errno.EACCES)
                    self.assertLessEqual(len(diagnostic['message']),512);self.assertLessEqual(len(diagnostic['filename']),512)
                    self.assertEqual(diagnostic['pid'],process.pid)
                    start=read_receipt(directory,'started',identity=self.identity)
                    self.assertEqual(diagnostic['started_sha256'],owned_process.hashlib.sha256(owned_process._canonical(start)).hexdigest())

    def test_timeout_stops_owned_tree_and_persists_actual_reason(self):
        handle = launch([sys.executable, '-c', 'import time;time.sleep(30)'],
                        directory=self.root / 'process', identity=self.identity,
                        supervisor_executable=sys.executable, budget_seconds=.15)
        self.assertNotEqual(handle.wait(5), 0)
        self.assertEqual(handle.receipt()['stop_reason'], 'TIME_BUDGET_EXCEEDED')

    def test_log_budget_stops_owned_child(self):
        source = 'import sys,time;sys.stdout.buffer.write(b"x"*(2*1024*1024));sys.stdout.flush();time.sleep(30)'
        handle = launch([sys.executable, '-c', source], directory=self.root / 'process',
                        identity=self.identity, supervisor_executable=sys.executable)
        self.assertNotEqual(handle.wait(5), 0)
        self.assertEqual(handle.receipt()['stop_reason'], 'LOG_BUDGET_EXCEEDED')

    def test_unicode_and_space_directory_supports_script_supervisor(self):
        directory = self.root / '中文 task space'
        handle = launch([sys.executable, '-c', 'pass'], directory=directory,
                        identity={**self.identity, 'task_id': '中文 task'},
                        supervisor_executable=sys.executable)
        self.assertEqual(handle.wait(5), 0)
        self.assertEqual(handle.receipt()['identity']['task_id'], '中文 task')
        for filename in ('supervisor.stdout.log', 'supervisor.stderr.log'):
            path = directory / filename
            path.unlink()
            self.assertFalse(path.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
    def test_parent_exit_keeps_supervision_until_same_group_child_exits(self):
        child_source = (
            'import os,pathlib,sys,time; parent=int(sys.argv[1]); '
            'marker=pathlib.Path(sys.argv[2]); release=pathlib.Path(sys.argv[3]);\n'
            'while True:\n'
            ' try: os.kill(parent,0)\n'
            ' except ProcessLookupError: break\n'
            ' time.sleep(.01)\n'
            'marker.touch()\n'
            'deadline=time.monotonic()+5\n'
            'while not release.exists() and time.monotonic()<deadline: time.sleep(.01)\n'
            'os._exit(int(sys.argv[4]))\n'
        )
        parent_source = (
            'import os,subprocess,sys; '
            'subprocess.Popen([sys.executable,"-c",sys.argv[1],str(os.getpid()),'
            'sys.argv[2],sys.argv[3],sys.argv[4]]); os._exit(0)'
        )
        for action, child_exit in [('leader', None), ('leader-failed', None), ('release', 0), ('release', 2),
                                   ('cancel', 0), ('budget', 0)]:
            with self.subTest(action=action, child_exit=child_exit):
                label = action + '-' + str(child_exit)
                parent_gone = self.root / (label + '-parent-gone')
                release = self.root / (label + '-release')
                leader_exit = 7 if action == 'leader-failed' else 0
                command = ([sys.executable, '-c', 'raise SystemExit(' + str(leader_exit) + ')'] if child_exit is None else
                           [sys.executable, '-c', parent_source, child_source,
                            str(parent_gone), str(release), str(child_exit)])
                handle = launch(command, directory=self.root / label, identity=self.identity,
                                supervisor_executable=sys.executable,
                                budget_seconds=1 if action == 'budget' else 5)
                try:
                    if child_exit is not None:
                        self.wait_marker(parent_gone)
                        self.assertIsNone(handle.poll())
                        with self.assertRaises(subprocess.TimeoutExpired):
                            handle._supervisor.wait(timeout=.1)
                        if action == 'cancel':
                            handle.terminate()
                        elif action == 'release':
                            release.touch()
                    expected = leader_exit if child_exit is None else 2
                    self.assertEqual(handle.wait(5), expected)
                    self.assertEqual(handle.poll(), expected)
                    self.assertEqual(handle._supervisor.returncode, 0 if child_exit is None else 2)
                    receipt = handle.receipt()
                    self.assertEqual(receipt['exit_code'], leader_exit)
                    self.assertEqual(receipt['supervisor_exit_code'], 0 if child_exit is None else 2)
                    self.assertEqual(receipt['execution_result'],
                                     'failed' if leader_exit else 'succeeded' if child_exit is None else
                                     'failed' if action in ('cancel', 'budget') else 'unknown')
                    self.assertEqual(OwnedProcessHandle(handle.directory, self.identity).wait(1), expected)
                    if action in ('cancel', 'budget'):
                        self.assertEqual(receipt['stop_reason'], 'CANCEL_REQUESTED' if action == 'cancel'
                                         else 'TIME_BUDGET_EXCEEDED')
                    else:
                        self.assertIsNone(receipt['stop_reason'])
                finally:
                    release.touch()

    @unittest.skipUnless(os.name == 'nt', 'Windows receipt facts')
    def test_windows_receipt_binds_birth_job_and_wait_observations(self):
        handle = launch([sys.executable, '-c', 'pass'], directory=self.root / 'process',
                        identity=self.identity, supervisor_executable=sys.executable)
        handle.wait(5)
        start = handle.started
        stopped = handle.receipt()
        self.assertEqual(stopped['process_birth'], start['process_birth'])
        self.assertEqual(stopped['job'], start['job'])
        self.assertTrue(stopped['child_wait_observed'])
        self.assertEqual(stopped['job_active_processes'], 0)
        for mutation in ({'process_birth': 'other'}, {'job': {**start['job'], 'name': 'other-job'}},
                         {'job_active_processes': 1}, {'job_active_processes': False},
                         {'child_wait_observed': False}, {'platform': 'posix'}):
            with self.subTest(mutation=mutation):
                owned_process._signed_write(handle.directory, {**stopped, **mutation})
                with self.assertRaisesRegex(ValueError, 'WINDOWS_STOP_NOT_BOUND'):
                    handle.poll()
        owned_process._signed_write(handle.directory, stopped)
        for missing in ('process_birth', 'job', 'platform'):
            with self.subTest(missing=missing):
                invalid = {name: value for name, value in start.items() if name != missing}
                owned_process._signed_write(handle.directory, invalid)
                with self.assertRaisesRegex(ValueError, 'WINDOWS_START_NOT_BOUND'):
                    read_receipt(handle.directory, 'started', identity=self.identity)
        owned_process._signed_write(handle.directory, start)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job tree')
    def test_parent_exit_keeps_reservation_until_job_descendants_stop(self):
        marker = self.root / 'descendant.json'
        source = ('import subprocess,sys,json;from pathlib import Path;'
                  'from dcc_task_runtime.platform_support import process_identity;'
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                  'creationflags=subprocess.CREATE_NO_WINDOW);'
                  'Path(sys.argv[1]).write_text(json.dumps(process_identity(child.pid)))')
        handle = launch([sys.executable, '-c', source, str(marker)], directory=self.root / 'process',
                        identity=self.identity, supervisor_executable=sys.executable)
        self.addCleanup(self.cancel_owned, handle)
        self.wait_marker(marker)
        descendant = json.loads(marker.read_text())
        direct = {'pid': handle.pid, 'platform': 'windows', 'birth': handle.started['process_birth']}
        self.wait_stopped(direct)
        self.assertIsNone(handle.poll())
        self.assertEqual(process_status(descendant), 'alive')
        handle.terminate()
        self.assertEqual(handle.wait(5), 2)
        self.assertEqual(handle.receipt()['job_active_processes'], 0)
        self.assertEqual(handle.receipt()['exit_code'], 0)
        self.assertEqual(handle.receipt()['execution_result'], 'failed')
        self.wait_stopped(descendant)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job queries')
    def test_unknown_job_query_never_signs_stop(self):
        directory = ensure_private_directory(self.root / 'process', exist_ok=False)
        with os.fdopen(open_private_file(directory / 'receipt.key'), 'wb') as stream:
            stream.write(os.urandom(32))
        owned_process._atomic(directory / 'intent.json', {
            'command': [sys.executable, '-c', 'import time;time.sleep(30)'],
            'identity': self.identity, 'env': dict(os.environ), 'budget_seconds': 2,
            'resource_budget': None,
        })
        with patch.object(owned_process.WindowsJobProcess, 'active_processes', return_value=None):
            self.assertEqual(owned_process.supervise(directory), 2)
        started = read_receipt(directory, 'started', identity=self.identity)
        self.assertIsNotNone(started)
        self.assertIsNone(read_receipt(directory, 'stopped', identity=self.identity))
        self.wait_stopped({'pid': started['pid'], 'platform': 'windows',
                           'birth': started['process_birth']})
        for name in ('child.stdout.log', 'child.stderr.log'):
            (directory / name).unlink()
        self.assertIsNone(read_receipt(directory, 'stopped', identity=self.identity))

    @unittest.skipUnless(os.name == 'nt', 'Windows kill-on-close')
    def test_supervisor_crash_cleans_job_without_manufacturing_stop(self):
        foreign = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', 'import time;time.sleep(30)'],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.stop_foreign, foreign)
        marker = self.root / 'descendant.json'
        source = ('import subprocess,sys,json,time;from pathlib import Path;'
                  'from dcc_task_runtime.platform_support import process_identity;'
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                  'creationflags=subprocess.CREATE_NO_WINDOW);'
                  'Path(sys.argv[1]).write_text(json.dumps(process_identity(child.pid)));time.sleep(30)')
        handle = launch([sys.executable, '-c', source, str(marker)], directory=self.root / 'process',
                        identity=self.identity, supervisor_executable=sys.executable)
        self.wait_marker(marker)
        descendant = json.loads(marker.read_text())
        supervisor = handle.started['supervisor_identity']
        from ctypes import wintypes
        import ctypes
        from dcc_task_runtime import windows_process
        windows_process._bind(windows_process.kernel32, 'TerminateProcess', wintypes.BOOL,
                              [wintypes.HANDLE, wintypes.UINT])
        native = windows_process.kernel32.OpenProcess(0x1 | 0x1000 | 0x100000, False, supervisor['pid'])
        windows_process._check(native)
        try:
            self.assertEqual(windows_process._birth(native), supervisor['birth'])
            windows_process._check(windows_process.kernel32.TerminateProcess(native, 17))
            self.assertEqual(windows_process.kernel32.WaitForSingleObject(native, 5000), 0)
        finally:
            windows_process.kernel32.CloseHandle(native)
        direct = {'pid': handle.pid, 'platform': 'windows', 'birth': handle.started['process_birth']}
        self.wait_stopped(direct)
        self.wait_stopped(descendant)
        self.assertIsNone(handle.poll())
        self.assertIsNone(OwnedProcessHandle(handle.directory, self.identity).poll())
        self.assertIsNone(foreign.poll())

    def wait_marker(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists())

    def wait_stopped(self, identity):
        deadline = time.monotonic() + 5
        while process_status(identity) != 'stopped' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(process_status(identity), 'stopped')

    def cancel_owned(self, handle):
        if handle.poll() is None:
            handle.terminate()
            handle.wait(5)

    def stop_foreign(self, process):
        if process.poll() is None:
            process.kill()
        process.wait(5)

class HoudiniSupervisorRecoveryTests(unittest.TestCase):
    def test_inflight_process_death_then_new_runner_import_and_archive(self):
        from test_operation_runner_recovery import build_runner_module, control_auth
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); child=root/'host.py'; ready=root/'started.json'
            repository=Path(__file__).resolve().parents[2]
            child.write_text("""import sys,json,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from test_operation_runner_recovery import build_runner_module
root=Path(sys.argv[2]); m=build_runner_module(root); runner=m.OperationRunner('t')
op=runner.submit({'step_params':{'frames':[2,4]}},'p',{}); runner.advance()
(root/'started.json').write_text(json.dumps({'operation_id':op['operation_id'],'state':runner.status(op['operation_id'])['state']}))
while True: time.sleep(.01)
""")
            identity={'task_id':'t','launch_nonce':'recovery-test'}
            directory=root/'supervisor'
            env=dict(os.environ)
            env['HOUDINI_BRIDGE_APPROVAL_SECRET']='unit-test-control-secret-0123456789abcdef'
            env['BRIDGE_OWNED_SUPERVISOR_DIR']=str(directory)
            env['BRIDGE_OWNED_SUPERVISOR_IDENTITY']=json.dumps(identity)
            executable=getattr(sys,'_base_executable',sys.executable)
            handle=launch([executable,'-X','utf8',str(child),str(repository/'tests/unit'),str(root)],directory=directory,identity=identity,supervisor_executable=executable,env=env)
            import time
            deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(ready.exists(),(directory/'child.stderr.log').read_text(encoding='utf-8'))
            state=json.loads(ready.read_text()); self.assertEqual(state['state'],'RUNNING')
            handle.terminate(); handle.wait(5)
            with patch.dict(os.environ,{'HOUDINI_BRIDGE_APPROVAL_SECRET':env['HOUDINI_BRIDGE_APPROVAL_SECRET']}):
                m=build_runner_module(root); runner=m.OperationRunner('t')
                runner.advance()
                operation_id=state['operation_id']
                self.assertEqual(runner.status(operation_id)['state'],'RECONCILE')
                evidence=runner.supervisor_stop_evidence(operation_id)
                result=runner.import_external_stop_fact(operation_id,evidence,control_auth('import_stop_fact',{'task_id':'t','request_id':operation_id,'evidence':evidence}))
                receipt=result['reconcile_evidence']
                final=runner.resolve_reconcile(operation_id,'archive',control_auth('resolve_reconcile',{'task_id':'t','request_id':operation_id,'decision':'archive','evidence':receipt}),evidence=receipt)
                self.assertEqual(final['state'],'SUPERSEDED')
                self.assertEqual(m._test_scheduler.snapshot()['active'],0)
