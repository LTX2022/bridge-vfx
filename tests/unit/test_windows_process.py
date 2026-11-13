import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dcc_task_runtime.platform_support import process_identity, process_status
from dcc_task_runtime.windows_process import WindowsJobProcess


@unittest.skipUnless(os.name == 'nt', 'Windows Job Objects')
class WindowsProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='Bridge 中文 space ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def start(self, source, *arguments, env=None):
        output = open(self.root / ('out-' + str(time.monotonic_ns())), 'ab', buffering=0)
        errors = open(self.root / ('err-' + str(time.monotonic_ns())), 'ab', buffering=0)
        try:
            process = WindowsJobProcess([sys.executable, '-c', source, *map(str, arguments)],
                                        env=env, stdout=output, stderr=errors)
        finally:
            output.close()
            errors.close()
        self.addCleanup(process.close)
        return process

    def wait_for(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists())

    def wait_stopped(self, identity):
        deadline = time.monotonic() + 5
        while process_status(identity) != 'stopped' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(process_status(identity), 'stopped')

    def wait_empty(self, process):
        deadline = time.monotonic() + 5
        while process.active_processes() != 0 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(process.active_processes(), 0)

    def test_child_observes_job_membership_before_first_instruction_and_no_console(self):
        result = self.root / 'native-facts.json'
        source = '''import ctypes,json,sys
from ctypes import wintypes
from pathlib import Path
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
kernel.GetConsoleWindow.restype=wintypes.HWND
member=wintypes.BOOL()
assert kernel.IsProcessInJob(kernel.GetCurrentProcess(),None,ctypes.byref(member))
Path(sys.argv[1]).write_text(json.dumps({'in_job':bool(member.value),'console':bool(kernel.GetConsoleWindow())}))
'''
        process = self.start(source, result)
        self.assertEqual(process.wait(5), 0)
        self.assertEqual(json.loads(result.read_text()), {'in_job': True, 'console': False})
        self.wait_empty(process)
        self.assertTrue(process.birth.isdigit())

    def test_unicode_arguments_and_environment_are_forwarded_without_shell(self):
        result = self.root / '结果 ; literal.json'
        value = '中文 with spaces "quoted" ; $literal & untouched'
        process = self.start('import json,os,sys;from pathlib import Path;'
                             'Path(sys.argv[1]).write_text(json.dumps([sys.argv[2],os.environ["BRIDGE_UNIT_VALUE"]]))',
                             result, value, env={**os.environ, 'BRIDGE_UNIT_VALUE': value})
        self.assertEqual(process.wait(5), 0)
        self.assertEqual(json.loads(result.read_text()), [value, value])

    def test_direct_child_exit_does_not_hide_remaining_descendant(self):
        result = self.root / 'grandchild.json'
        source = ('import subprocess,sys,json;from pathlib import Path;'
                  'from dcc_task_runtime.platform_support import process_identity;'
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                  'creationflags=subprocess.CREATE_NO_WINDOW);'
                  'Path(sys.argv[1]).write_text(json.dumps(process_identity(child.pid)))')
        process = self.start(source, result)
        self.assertEqual(process.wait(5), 0)
        identity = json.loads(result.read_text())
        self.assertGreaterEqual(process.active_processes(), 1)
        self.assertEqual(process_status(identity), 'alive')
        process.terminate()
        self.wait_stopped(identity)
        self.wait_empty(process)

    def test_job_close_cleans_descendants_and_leaves_unrelated_process_alive(self):
        foreign = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', 'import time;time.sleep(30)'],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.stop_foreign, foreign)
        result = self.root / 'tree.json'
        source = ('import subprocess,sys,json,time;from pathlib import Path;'
                  'from dcc_task_runtime.platform_support import process_identity;'
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                  'creationflags=subprocess.CREATE_NO_WINDOW);'
                  'Path(sys.argv[1]).write_text(json.dumps(process_identity(child.pid)));time.sleep(30)')
        process = self.start(source, result)
        self.wait_for(result)
        child = process_identity(process.pid)
        descendant = json.loads(result.read_text())
        process.close()
        self.wait_stopped(child)
        self.wait_stopped(descendant)
        self.assertIsNone(foreign.poll())

    def stop_foreign(self, process):
        if process.poll() is None:
            process.kill()
        process.wait(5)

    def test_job_query_failure_is_unknown(self):
        from dcc_task_runtime import windows_process
        process = self.start('import time;time.sleep(30)')
        with patch.object(windows_process.kernel32, 'QueryInformationJobObject', return_value=0):
            self.assertIsNone(process.active_processes())

    def test_create_failure_cleans_resources_without_running_child(self):
        with open(self.root / 'stdout', 'wb') as output, open(self.root / 'stderr', 'wb') as errors:
            with self.assertRaises(OSError):
                WindowsJobProcess([str(self.root / 'missing.exe')], stdout=output, stderr=errors)
