"""Host-boundary diagnostic regressions; no native DCC or socket bind occurs."""
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_nuke_transport_auth import load_addon
from dcc_task_runtime.owned_process import launch

class StartupDiagnosticsTests(unittest.TestCase):
    def test_permission_denied_is_not_reported_as_port_exhaustion(self):
        addon=load_addon();server=addon.NukeBridgeServer()
        with patch.object(addon.socketserver.TCPServer,'server_bind',side_effect=PermissionError(errno.EPERM,'fixture permission denial')) as bind:
            with self.assertRaisesRegex(RuntimeError,'NUKE_BRIDGE_BIND_FAILED.*errno=1'):
                server.start()
        self.assertEqual(bind.call_count,1)
        self.assertIsNone(server._server)

    def test_only_address_in_use_exhausts_port_range_with_original_errno(self):
        addon=load_addon();server=addon.NukeBridgeServer()
        with patch.object(addon.socketserver.TCPServer,'server_bind',side_effect=OSError(errno.EADDRINUSE,'fixture in use')) as bind:
            with self.assertRaisesRegex(RuntimeError,'no free Nuke Bridge port.*errno='+str(errno.EADDRINUSE)):
                server.start()
        self.assertEqual(bind.call_count,100)

    def test_houdini_permission_denied_preserves_errno(self):
        source = Path(__file__).resolve().parents[2] / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        spec = importlib.util.spec_from_file_location('startup_diagnostic_houdini', source)
        addon = importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
        server = addon.HoudiniBridgeServer()
        with patch.object(server, '_make_http', side_effect=PermissionError(errno.EPERM, 'fixture denial')) as bind:
            with self.assertRaisesRegex(RuntimeError, 'HOUDINI_BRIDGE_BIND_FAILED.*errno=1'):
                server.start()
        self.assertEqual(bind.call_count, 1)
        self.assertIsNone(server._http)

    def test_houdini_address_in_use_records_exhaustion(self):
        source = Path(__file__).resolve().parents[2] / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        spec = importlib.util.spec_from_file_location('startup_diagnostic_houdini', source)
        addon = importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
        server = addon.HoudiniBridgeServer()
        with patch.object(server, '_make_http', side_effect=OSError(errno.EADDRINUSE, 'fixture in use')) as bind:
            with self.assertRaisesRegex(RuntimeError, 'no free Houdini Bridge port.*errno='+str(errno.EADDRINUSE)):
                server.start()
        self.assertEqual(bind.call_count, 100)

    def test_logs_outside_output_roots_still_consume_disk_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();output=root/'output';output.mkdir()
            child=launch([sys.executable,'-c','import sys,time;sys.stdout.write("x"*65536);sys.stdout.flush();time.sleep(30)'],
                         directory=root/'supervisor',identity={'task_id':'log-budget','nonce':'one'},
                         supervisor_executable=sys.executable,resource_budget={'roots':[str(output)],'max_bytes':4096})
            try:
                self.assertNotEqual(child.wait(3),0)
                self.assertEqual(child.receipt()['stop_reason'],'DISK_BUDGET_EXCEEDED')
            finally:
                if child.poll() is None:child.terminate();child.wait(5)

    def test_logs_have_a_limit_without_an_output_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            child=launch([sys.executable,'-c','import sys,time;sys.stderr.write("x"*(2*1024*1024));sys.stderr.flush();time.sleep(30)'],
                         directory=Path(tmp)/'supervisor',identity={'task_id':'log-limit','nonce':'one'},
                         supervisor_executable=sys.executable)
            try:
                self.assertNotEqual(child.wait(3),0)
                self.assertEqual(child.receipt()['stop_reason'],'LOG_BUDGET_EXCEEDED')
            finally:
                if child.poll() is None:child.terminate();child.wait(5)

    def test_owned_child_failure_keeps_private_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'supervisor'
            child=launch([sys.executable,'-c','import sys;print("native-out");print("native-error",file=sys.stderr);sys.exit(7)'],directory=directory,
                         identity={'task_id':'diagnostic-test','nonce':'first'},supervisor_executable=sys.executable)
            self.assertEqual(child.wait(5),7)
            self.assertIn('native-out',(directory/'child.stdout.log').read_text())
            self.assertIn('native-error',(directory/'child.stderr.log').read_text())
            if os.name == 'nt':
                from dcc_task_runtime import windows_process
                from test_platform_support import private_dacl_sddl
                for filename in ('child.stdout.log', 'child.stderr.log'):
                    sddl = private_dacl_sddl(directory / filename)
                    self.assertTrue(sddl.startswith('D:P'))
                    self.assertEqual(sddl.count('(A;'), 2)
                    self.assertIn(';;;SY)', sddl)
                    self.assertIn(';;;' + windows_process._current_user_sid() + ')', sddl)
            else:
                self.assertEqual((directory/'child.stderr.log').stat().st_mode & 0o777,0o600)
            self.assertEqual(child.receipt()['exit_code'],7)
