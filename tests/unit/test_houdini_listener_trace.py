"""Listener diagnostics are bounded, private and cannot change host behavior."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


class ListenerTraceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='listener-trace-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        modules = patch.dict(sys.modules)
        modules.start(); self.addCleanup(modules.stop)
        environment = patch.dict(os.environ, {'HOUDINI_BRIDGE_TASK_STATE_DIR': str(self.root / 'state'),
                                              'HOUDINI_BRIDGE_STATE_DIR': str(self.root / 'instances')})
        environment.start(); self.addCleanup(environment.stop)
        from vfx_pipeline.workbuddy_assembly import software_host_client
        _, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.root / 'host')
        self.hou = sys.modules['hou']
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd); self.addCleanup(os.close, write_fd)
        class Listener:
            closed = False
            def fileno(self): return read_fd
            def getsockname(self): return ('127.0.0.1', 8100)
            def getsockopt(self, *_args): return 0 if self.closed else 1
            def accept(self):
                if self.closed: raise OSError('closed')
                return 'accepted'
            def close(self): self.closed = True
        self.listener = Listener()
        self.server = self.addon.HoudiniBridgeServer()
        self.server._token = 'DO-NOT-LOG-SECRET'
        self.server.session_id = 'DO-NOT-LOG-IDENTITY'
        self.server._http = SimpleNamespace(socket=self.listener, shutdown=lambda: None,
                                            server_close=self.listener.close)
        self.server._thread = SimpleNamespace(is_alive=lambda: True)
        self.addon._SERVER = self.server
        self.path = self.root / 'state/listener-trace.jsonl'

    def rows(self):
        return [json.loads(row) for row in self.path.read_text().splitlines()]

    def test_trace_retains_descriptor_ownership_and_is_bounded_and_redacted(self):
        for _ in range(80):
            self.addon._fx_listener_trace('test', expected_server=self.server)
        rows = self.rows()
        self.assertEqual(len(rows), 64)
        self.assertLessEqual(self.path.stat().st_size, 65536)
        self.assertEqual(os.fstat(self.listener.fileno()).st_ino, rows[0]['fstat_ino'])
        self.assertTrue(rows[0]['same_server']); self.assertTrue(rows[0]['thread_alive'])
        self.assertEqual(rows[0]['bound_port'], 8100); self.assertTrue(rows[0]['accepting'])
        self.assertEqual(self.listener.accept(), 'accepted')
        self.assertFalse(self.listener.closed)
        text = self.path.read_text()
        self.assertNotIn('DO-NOT-LOG', text)
        self.assertNotIn('nonce', text); self.assertNotIn('token', text)

    def test_load_before_after_and_stop_observations_do_not_change_commands(self):
        self.hou.hipFile.eventCallbacks = lambda: [self.addon._bridge_scene_event]
        events = self.hou.hipFileEventType
        with self.addon._fx_owned_hip_load_events(trace_phase='task_reopen_load'):
            for event in (events.BeforeLoad, events.BeforeClear, events.AfterClear, events.AfterLoad):
                self.addon._bridge_scene_event(event)
        rows = self.rows()
        self.assertEqual([row['phase'] for row in rows], ['task_reopen_load_before', 'task_reopen_load_after'])
        self.assertEqual(rows[1]['scene_epoch'], rows[0]['scene_epoch'] + 1)
        self.assertEqual(self.listener.accept(), 'accepted')
        self.server.stop()
        stopped = self.rows()[-1]
        self.assertEqual(stopped['phase'], 'listener_stop')
        self.assertEqual(stopped['stop_reason'], 'explicit_stop')
        self.assertTrue(stopped['accepting'])
        self.assertLessEqual(len(stopped['stack']), 5)
        self.assertTrue(self.listener.closed)

    def test_observation_failure_preserves_success_and_original_load_exception(self):
        self.hou.hipFile.eventCallbacks = lambda: [self.addon._bridge_scene_event]
        events = self.hou.hipFileEventType
        with patch.object(self.addon.os, 'open', side_effect=OSError('diagnostic filesystem unavailable')):
            with self.addon._fx_owned_hip_load_events():
                for event in (events.BeforeLoad, events.BeforeClear, events.AfterClear, events.AfterLoad):
                    self.addon._bridge_scene_event(event)
            with self.assertRaisesRegex(RuntimeError, 'original native load failure'):
                with self.addon._fx_owned_hip_load_events():
                    raise RuntimeError('original native load failure')
        self.assertIsNone(self.addon._FX_OWNED_HIP_LOAD)
        self.assertEqual(self.listener.accept(), 'accepted')
        self.assertFalse(self.listener.closed)

    def test_busy_trace_lock_skips_observation_without_blocking_native_command(self):
        self.hou.hipFile.eventCallbacks = lambda: [self.addon._bridge_scene_event]
        events = self.hou.hipFileEventType
        done, failures = threading.Event(), []
        def command():
            try:
                with self.addon._fx_owned_hip_load_events():
                    for event in (events.BeforeLoad, events.BeforeClear, events.AfterClear, events.AfterLoad):
                        self.addon._bridge_scene_event(event)
            except Exception as error:
                failures.append(error)
            finally:
                done.set()
        lock = self.addon._FX_LISTENER_TRACE_LOCK
        lock.acquire()
        worker = threading.Thread(target=command, daemon=True)
        try:
            worker.start()
            self.assertTrue(done.wait(1.0), 'listener observation blocked the native command on its busy lock')
            self.assertEqual(failures, [])
            self.assertFalse(self.path.exists())
            self.assertEqual(self.listener.accept(), 'accepted')
        finally:
            lock.release()
            worker.join(timeout=1.0)


if __name__ == '__main__':
    unittest.main()
