"""Fault injection against real SQLite/files/processes with SOFTWARE fake hosts.

No true DCC/model acceptance is generated. Assertions observe effects, blocked
capacity, persisted identities and retry count, not a copy of state-machine code.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
import stat
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_graph_jobs import _FakeAddon, _Process, _proposal
from vfx_pipeline.graph_job_evidence import atomic_json, file_sha256, process_identity, process_status, owned_file
from vfx_pipeline.graph_job_worker import DurableJournal, GraphJobWorker, run_job
from vfx_pipeline.graph_jobs import GraphJobService, GraphJobError, _public_result
from vfx_pipeline.graph_trial import GraphExecutor
from vfx_pipeline.scene_lease import SceneLeaseStore
from vfx_pipeline import graph_catalog

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests/helpers/graph_job_process_fixture.py"
sys.path.insert(0, str(HELPER.parent))
from graph_job_process_fixture import directory_alias, launch_worker, python_command


def wait_until(condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("condition did not become true before test deadline")


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.scheduler_root = self.base / "installation"
        self.services = []
        self.processes = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # Release only our controlled fixture processes; never use a PID kill.
        for directory, children, files in os.walk(self.base, followlinks=False):
            parent = Path(directory)
            children[:] = [name for name in children if not (
                getattr((parent / name).lstat(), 'st_file_attributes', 0)
                & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))]
            for marker, release in (('descendant_waiting', 'release_descendant'),
                                    ('legacy_waiting', 'release_legacy'), ('worker_waiting', 'release_worker')):
                if marker in files:
                    (parent / release).write_text("test cleanup\n")
        for process in self.processes:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=4)
        for service in self.services:
            service.close()

    def service(self, name="job", *, fault=None, factory=None, clock=time.time, repo=ROOT):
        kwargs = {}
        if fault is not None:
            def spawn(argv, **options):
                process = launch_worker(argv[-1], fault=fault, env=options['env'])
                self.processes.append(process)
                return process
            kwargs["subprocess_factory"] = spawn
        else:
            kwargs["worker_factory"] = factory or (lambda job: {"construction_executed": True})
        service = GraphJobService(self.base / name, repo, "NEVER_A_DCC", scheduler_root=self.scheduler_root,
                                  clock=clock, **kwargs)
        self.services.append(service)
        return service

    def trial(self, service, request="trial-1"):
        return service.trial(service.propose(_proposal(), "proposal-1"), request)

    def finished_thread(self, service, operation):
        wait_until(lambda: not service._threads[operation].is_alive())

    def effects(self, service, operation):
        path = service._worker_paths(operation)["directory"] / "software_host_effects.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def make_recoverable(self, name="job"):
        service = self.service(name, fault="none")
        # Real fake-host child completes/seals; fail the controller DB result
        # persistence AFTER its process has exited. No manufactured receipt.
        def lost_persistence(*args, **kwargs):
            raise sqlite3.OperationalError("SOFTWARE injected result transaction failure")
        service._finish = lost_persistence
        operation = self.trial(service)
        self.finished_thread(service, operation)
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        paths = service._worker_paths(operation)
        self.assertTrue(paths["completion"].is_file(), paths["error"].read_text() if paths["error"].exists() else "completion not written")
        self.assertEqual(sum(e["command"] == "node.create" for e in self.effects(service, operation)), 1)
        self.assertEqual(sum(e["command"] == "scene.create_task_root" for e in self.effects(service, operation)), 1)
        return service, operation

    def test_real_child_completed_result_recovers_after_controller_persistence_failure(self):
        first, operation = self.make_recoverable()
        second = self.service(fault="none")
        result = second.reconcile(operation)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertTrue(result["stop_confirmed"])
        self.assertEqual(result["result"]["validation_scope"], "software_fake_host")
        self.assertFalse(result["result"]["visual_verified"])
        self.assertEqual(operation, self.trial(second))
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(second.reconcile(operation), second.status(operation))
        self.assertFalse(second.scheduler.snapshot()["active"])
        self.assertNotIn(str(self.base), json.dumps(result))

    def test_exited_parent_with_live_owned_descendant_keeps_capacity(self):
        service = self.service(fault="same_session_descendant")
        operation = self.trial(service)
        directory = service._worker_paths(operation)["directory"]
        process = wait_until(lambda: self.processes and self.processes[0])
        wait_until(lambda: (directory / 'descendant_waiting').exists())
        if os.name == 'nt':
            identity = process.started
            direct = {'pid': process.pid, 'platform': 'windows', 'birth': identity['process_birth']}
            wait_until(lambda: process_status(direct) == 'stopped')
        else:
            self.finished_thread(service, operation)
            self.assertEqual(process.poll(), 0)
            self.assertIsNone(process.handle._supervisor.poll(),
                              'the owned supervisor must keep observing the live descendant')
            from dcc_task_runtime.owned_process import read_receipt
            self.assertIsNone(read_receipt(process.handle.directory, 'stopped', identity=process.handle.identity))
            descendant = json.loads((directory / 'descendant_waiting').read_text())
            self.assertEqual(os.getpgid(descendant['pid']), process.pid)
            self.assertEqual(os.getsid(descendant['pid']), process.pid)
        if os.name == 'nt':
            self.assertIsNone(process.poll())
        self.assertTrue((directory / "descendant_waiting").exists())
        self.assertFalse(service.status(operation)["stop_confirmed"])
        self.assertEqual(service.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
        other = self.service("other")
        with self.assertRaises(GraphJobError):
            self.trial(other)
        (directory / "release_descendant").write_text("controller test release\n")
        if os.name == 'nt':
            process.wait(timeout=4)
            self.finished_thread(service, operation)
        else:
            self.assertEqual(process.handle._supervisor.wait(timeout=4), 2)
            stopped = read_receipt(process.handle.directory, 'stopped', identity=process.handle.identity)
            self.assertIsNotNone(stopped)
            self.assertEqual(stopped['observed_by'], 'owned_child_wait')
            self.assertTrue(stopped['descendant_result_unobserved'])
        wait_until(lambda: service._observed_stopped(service._row(operation)))
        self.assertEqual(service.reconcile(operation)["state"], "SUCCEEDED")
        self.assertEqual(len(self.processes), 1)
        self.trial(other)

    def test_native_child_wait_transport_keeps_real_supervisor_and_completion(self):
        from dcc_task_runtime.owned_process import read_receipt
        def spawn(argv, **options):
            process = launch_worker(argv[-1], env=options['env'], observe_child_wait=True)
            self.processes.append(process)
            return process
        service = GraphJobService(self.base / 'job', ROOT, 'NEVER_A_DCC',
                                  scheduler_root=self.scheduler_root, subprocess_factory=spawn)
        self.services.append(service)
        operation = self.trial(service)
        thread = service._threads[operation]
        thread.join(service._remaining_seconds(service._row(operation)))
        self.assertFalse(thread.is_alive(), 'controller thread exceeded the original operation deadline')
        process = self.processes[0]
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertEqual(process.started, read_receipt(process.handle.directory, 'started',
                                                     identity=process.handle.identity))
        stopped = read_receipt(process.handle.directory, 'stopped', identity=process.handle.identity)
        self.assertEqual(stopped['pid'], process.pid)
        self.assertEqual(stopped['exit_code'], process.returncode)
        self.assertEqual(service.status(operation)['state'], 'SUCCEEDED')
        self.assertTrue(service.status(operation)['stop_confirmed'])
        self.assertFalse(service.scheduler.snapshot()['active'])
        self.assertEqual(sum(event['command'] == 'node.create' for event in self.effects(service, operation)), 1)

    def test_retry_rotation_commit_without_local_commit_can_be_fenced_and_resumed(self):
        calls = []
        first = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        first._claim_start = lambda *_: False
        operation = self.trial(first)
        self.finished_thread(first, operation)
        second = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        setter = second._set_state
        def lose_local_commit(op, state, **fields):
            if state == "PREPARED":
                raise sqlite3.OperationalError("SOFTWARE fault after global retry commit")
            return setter(op, state, **fields)
        second._set_state = lose_local_commit
        with self.assertRaises(sqlite3.OperationalError):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(calls, [])
        self.assertNotEqual(second._row(operation)["process_token"], second.scheduler.snapshot()["token"])
        third = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        self.assertEqual(third.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(calls, [])
        third.reconcile(operation, resume_not_started=True)
        self.finished_thread(third, operation)
        self.assertEqual(third.status(operation)["state"], "SUCCEEDED")
        self.assertEqual(len(calls), 1)

    def test_legacy_pid_absence_alone_cannot_release_installation(self):
        first = self.service()
        first._claim_start = lambda *_: False
        operation = self.trial(first)
        self.finished_thread(first, operation)
        row = first._row(operation)
        self.assertTrue(first.scheduler.fence_unstarted(str(first.root), operation, row["process_token"]))
        first.scheduler.release(str(first.root), operation, row["process_token"], unstarted=True)
        script = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); (p/'legacy_waiting').write_text('software only'); end=time.monotonic()+20\nwhile not (p/'release_legacy').exists() and time.monotonic()<end: time.sleep(.01)"
        child = subprocess.Popen(python_command('-c', script, self.base), start_new_session=os.name != 'nt',
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.processes.append(child)
        wait_until(lambda: (self.base / "legacy_waiting").exists())
        # A migration fixture, explicitly NOT a real-host receipt.
        with first._connect() as db:
            db.execute("UPDATE operations SET state='RUNNING',attempt_generation=0,process_token=NULL,pid=? WHERE operation_id=?", (child.pid, operation))
        second = self.service()
        other = self.service("other")
        with self.assertRaises(GraphJobError):
            self.trial(other)
        self.assertEqual(second.reconcile(operation, resume_not_started=True)["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(second.cancel(operation)["stop_confirmed"])
        self.assertIsNone(child.poll())  # Reconnected controller did not signal this PID.
        (self.base / "release_legacy").write_text("fixture release\n")
        child.wait(timeout=4)
        self.assertFalse(second.cancel(operation)["stop_confirmed"])
        self.assertEqual(second.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
        with self.assertRaises(GraphJobError):
            self.trial(other)

    def test_host_effect_with_lost_reply_never_replays(self):
        service = self.service(fault="drop_reply")
        operation = self.trial(service)
        self.finished_thread(service, operation)
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(sum(e["command"] == "node.create" for e in self.effects(service, operation)), 1)
        second = self.service(fault="none")
        for _ in range(2):
            self.assertEqual(second.reconcile(operation, resume_not_started=True)["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(self.trial(second), operation)
        self.assertEqual(len(self.processes), 1)
        self.assertTrue(second.status(operation)["stop_confirmed"])
        self.assertFalse(second.scheduler.snapshot()["active"])
        self.trial(self.service("other"), "different-request")
        journal = DurableJournal(service._worker_paths(operation)["journal"])
        with closing(sqlite3.connect(str(journal.path))) as db:
            states = [json.loads(row[0])["status"] for row in db.execute("SELECT payload FROM entries")]
        # root creation completed and was journaled before the node effect was
        # lost; the UNKNOWN entry is the node whose reply never arrived
        self.assertEqual(states, ["COMPLETE", "UNKNOWN"])

    def test_host_reply_before_journal_commit_process_crash_remains_unknown(self):
        service = self.service(fault="crash_before_journal_commit")
        operation = self.trial(service)
        self.finished_thread(service, operation)
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(self.processes[0].returncode, 93)
        self.assertEqual(sum(e["command"] == "node.create" for e in self.effects(service, operation)), 1)
        self.assertEqual(service.reconcile(operation, resume_not_started=True)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(len(self.processes), 1)
        with closing(sqlite3.connect(str(service._worker_paths(operation)["journal"]))) as db:
            # the root lease operation completed and was journaled; the node's
            # durable INTENT survives the crash with no COMPLETE record
            self.assertEqual([json.loads(r[0])["status"] for r in db.execute("SELECT payload FROM entries")], ["COMPLETE", "INTENT"])

    def test_before_dispatch_fault_explicitly_resumes_same_operation_once(self):
        calls = []
        service = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        original_claim = service._claim_start
        service._claim_start = lambda *_: False
        operation = self.trial(service)
        self.finished_thread(service, operation)
        second = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        self.assertEqual(second.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(calls, [])
        old = dict(service._row(operation))
        second.reconcile(operation, resume_not_started=True)
        self.finished_thread(second, operation)
        self.assertEqual(second.status(operation)["state"], "SUCCEEDED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.trial(second), operation)
        # An old delayed launcher cannot overwrite inputs or the new result.
        service._claim_start = original_claim
        service._launch(operation, {}, old["process_token"], old["attempt_generation"])
        self.assertEqual(second.status(operation)["state"], "SUCCEEDED")
        self.assertEqual(len(calls), 1)

    def test_old_launcher_exception_cannot_overwrite_new_reconciled_state(self):
        started, release = threading.Event(), threading.Event()
        def delayed(*args):
            started.set(); release.wait(5)
            raise OSError("old worker-thread failure")
        first = self.service()
        with patch.object(first, "_graph_record_for_operation", side_effect=delayed):
            operation = self.trial(first)
            self.assertTrue(started.wait(3))
            second = self.service()
            second.reconcile(operation, resume_not_started=True)
            self.finished_thread(second, operation)
            self.assertEqual(second.status(operation)["state"], "SUCCEEDED")
            release.set()
            self.finished_thread(first, operation)
        self.assertEqual(second.status(operation)["state"], "SUCCEEDED")

    def test_subprocess_typeerror_after_side_effect_is_not_retried(self):
        calls = []
        def factory(*args, **kwargs):
            calls.append(args)
            raise TypeError("failure AFTER an attempted process launch")
        service = GraphJobService(self.base / "job", ROOT, "NEVER_A_DCC", scheduler_root=self.scheduler_root,
                                  subprocess_factory=factory)
        self.services.append(service)
        operation = self.trial(service)
        self.finished_thread(service, operation)
        self.assertEqual(len(calls), 1)
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(service.reconcile(operation, resume_not_started=True)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(len(calls), 1)

    def test_pending_cancellation_keeps_slot_even_with_complete_result_on_disk(self):
        service = self.service(fault="ignore_terminate")
        operation = self.trial(service)
        paths = service._worker_paths(operation)
        wait_until(lambda: (paths["directory"] / "worker_waiting").exists())
        self.assertTrue(paths["completion"].is_file())
        # Completion files alone cannot release a still-live heavy process.
        self.assertEqual(service.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
        status = service.cancel(operation)
        self.assertTrue(status["cancellation_requested"])
        self.assertFalse(status["stop_confirmed"])
        self.assertEqual(status["state"], "RECONCILIATION_REQUIRED")
        other = self.service("other")
        with self.assertRaises(GraphJobError):
            self.trial(other)
        summary = service.close()
        self.assertEqual(summary["pending_monitors"], 0)
        self.assertIn(operation, summary["unconfirmed_workers"])
        self.assertTrue(service.scheduler.snapshot()["active"])
        (paths["directory"] / "release_worker").write_text("finish software process\n")
        self.processes[0].wait(timeout=4)
        self.assertEqual(service.reconcile(operation)["state"], "CANCELLED")
        new_operation = self.trial(other)
        self.finished_thread(other, new_operation)
        self.assertEqual(other.status(new_operation)["state"], "SUCCEEDED")

    def test_reconnected_controller_never_terminates_an_unowned_handle(self):
        first = self.service(fault="hang_after_completion")
        operation = self.trial(first)
        paths = first._worker_paths(operation)
        wait_until(lambda: (paths["directory"] / "worker_waiting").exists())
        second = self.service()
        before = second.reconcile(operation)
        self.assertEqual(before['state'], 'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.processes[0].poll())
        self.assertTrue(first.scheduler.snapshot()["active"])
        original_token = first._row(operation)['process_token']
        with first._connect() as database:
            database.execute('UPDATE operations SET process_token=? WHERE operation_id=?',
                             ('foreign-attempt', operation))
        refused = second.cancel(operation)
        self.assertEqual(refused['state'], 'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.processes[0].poll())
        self.assertFalse((paths['directory'] / 'owned-supervisor/cancel.json').exists())
        with first._connect() as database:
            database.execute('UPDATE operations SET process_token=? WHERE operation_id=?',
                             (original_token, operation))
        status = second.cancel(operation)
        self.assertTrue(status['cancellation_requested'])
        self.processes[0].wait(timeout=4)
        wait_until(lambda: second.reconcile(operation)['state'] == 'CANCELLED')
        self.assertFalse(first.scheduler.snapshot()['active'])

    def test_timeout_never_turns_failed_termination_into_available_capacity(self):
        class Stubborn(_Process):
            def terminate(self):
                self.terminated = True
            def poll(self):
                return 0 if self.done else None
        process, now = Stubborn(), [100.0]
        service = self.service(factory=lambda job: process, clock=lambda: now[0])
        operation = self.trial(service)
        wait_until(lambda: service.status(operation)["state"] == "RUNNING")
        now[0] = 1000
        self.finished_thread(service, operation)
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(service.status(operation)["stop_confirmed"])
        with self.assertRaises(GraphJobError):
            self.trial(self.service("other"))
        process.done = True
        self.assertEqual(service.reconcile(operation)["state"], "CANCELLED")

    def test_same_request_different_graph_is_rejected_without_second_effect(self):
        calls = []
        service = self.service(factory=lambda job: calls.append(job) or {"construction_executed": True})
        first = self.trial(service)
        self.finished_thread(service, first)
        other = service.propose(_proposal(radius=2), "other-proposal")
        with self.assertRaises(GraphJobError):
            service.trial(other, "trial-1")
        self.assertEqual(len(calls), 1)

    def test_tampered_result_project_graph_identity_and_journal_stay_blocked(self):
        for name in ("result", "artifact", "graph", "identity", "journal", "catalog"):
            with self.subTest(component=name):
                first, operation = self.make_recoverable(name)
                paths = first._worker_paths(operation)
                if name in {"result", "graph", "identity"}:
                    path = paths[name]
                    payload = json.loads(path.read_text()); payload["tampered"] = True
                    path.write_text(json.dumps(payload))
                elif name == "artifact":
                    (paths["directory"] / (operation + ".hip")).write_bytes(b"different project bytes")
                elif name == "journal":
                    with closing(sqlite3.connect(str(paths["journal"]))) as db:
                        db.execute("DELETE FROM entries WHERE operation_id=(SELECT operation_id FROM entries LIMIT 1)"); db.commit()
                else:
                    path = paths["inputs"]
                    payload = json.loads(path.read_text()); payload["catalog_hash"] = "0" * 64
                    path.write_text(json.dumps(payload))
                second = self.service(name)
                self.assertEqual(second.reconcile(operation)["state"], "RECONCILIATION_REQUIRED")
                self.assertTrue(second.status(operation)["stop_confirmed"])
                self.assertFalse(second.scheduler.snapshot()["active"])
                self.assertEqual(sum(e["command"] == "node.create" for e in self.effects(first, operation)), 1)
                self.assertEqual(sum(e["command"] == "scene.create_task_root" for e in self.effects(first, operation)), 1)
                # An observed-stopped cancellation may free capacity but does
                # not claim the tampered construction result was successful.
                self.assertEqual(second.cancel(operation)["state"], "CANCELLED")

    def test_changed_runtime_blocks_unstarted_resume(self):
        service = self.service()
        service._claim_start = lambda *_: False
        operation = self.trial(service)
        self.finished_thread(service, operation)
        with patch("vfx_pipeline.graph_jobs.runtime_fingerprint", return_value="changed-on-disk-input"):
            with self.assertRaises(GraphJobError):
                service.reconcile(operation, resume_not_started=True)
        self.assertTrue(service.scheduler.snapshot()["active"])
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")

    def test_close_rejects_new_launches(self):
        service = self.service()
        graph = service.propose(_proposal(), "proposal-1")
        self.assertEqual(service.close()["pending_monitors"], 0)
        with self.assertRaises(GraphJobError):
            service.trial(graph, "trial-1")

    def test_status_drops_nested_tracebacks_arbitrary_paths_and_claims(self):
        operation, graph_hash = "op_test", "a" * 64
        value = {"graph_hash": graph_hash, "construction_executed": True, "visual_verified": True,
                 "diagnostics": [{"code": "EXECUTION_UNKNOWN", "message": "Traceback /etc/passwd PRIVATE"}],
                 "artifact": {"path": str(self.base / "secret"), "hip_path": "C:\\Users\\PRIVATE", "nested": {"traceback": "PRIVATE"}},
                 "verification": {"nodes_verified": True, "hip_path": "/etc/passwd", "nested": "PRIVATE"},
                 "parameters": {"a": "PRIVATE"}, "topology": {"root": "/Users/PRIVATE", "nodes": {"a": "/etc/passwd"}}}
        safe = _public_result(value, root=self.base, operation_id=operation, graph_id="graph_test")
        serialized = json.dumps(safe)
        for text in ("PRIVATE", "/etc/passwd", "Traceback", str(self.base), "C:\\\\Users"):
            self.assertNotIn(text, serialized)
        self.assertFalse(safe["visual_verified"])

    def test_atomic_input_replace_failure_preserves_previous_bytes(self):
        target = self.base / "evidence.json"
        atomic_json(target, {"version": 1}, root=self.base)
        before = target.read_bytes()
        with patch("vfx_pipeline.graph_job_evidence.os.replace", side_effect=OSError("injected publish failure")):
            with self.assertRaises(OSError):
                atomic_json(target, {"version": 2}, root=self.base)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.base.glob(".*.tmp")), [])

    def test_symlink_components_and_dangling_output_links_are_rejected(self):
        real = self.base / "real"; real.mkdir()
        link = self.base / "link"; directory_alias(link, real)
        with self.assertRaises(ValueError):
            owned_file(self.base, link / "output.json", required=False)
        dangling = self.base / "dangling"
        if os.name == 'nt':
            directory_alias(dangling, self.base / 'missing')
        else:
            dangling.symlink_to(self.base / 'missing')
        with self.assertRaises(ValueError):
            atomic_json(dangling, {"bad": True}, root=self.base)

    def test_missing_process_birth_identity_is_unknown_not_stop_proof(self):
        identity = process_identity(os.getpid())
        identity["birth"] = None
        self.assertEqual(process_status(identity), "unknown")

    @unittest.skipUnless(os.name == 'posix', 'POSIX process identity')
    def test_darwin_birth_uses_shared_observation_and_unknown_stays_unknown(self):
        pid = os.getpid()
        for birth, state, expected in (('creation-token','alive','alive'),
                                       ('creation-token','stopped','stopped'),
                                       (None,'unknown','unknown')):
            with self.subTest(state=state), patch('vfx_pipeline.graph_job_evidence.sys.platform','darwin'), \
                    patch('dcc_task_runtime.platform_support.process_identity',
                          return_value={'pid':pid,'platform':'posix','birth':birth,'state':state}):
                identity = process_identity(pid)
                self.assertEqual(identity['platform'],'darwin')
                self.assertEqual(identity['birth'],birth)
                self.assertEqual(identity['pgid'],os.getpgid(pid))
                self.assertEqual(identity['sid'],os.getsid(pid))
                self.assertEqual(process_status(identity),expected)


class CrossProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.gates = self.base / "gates"; self.gates.mkdir()
        self.children = []
        self.addCleanup(self.cleanup)

    def _child_diagnostics(self):
        details = []
        for child in self.children:
            code = child.poll()
            if code is None:
                continue
            out, err = child.communicate()
            details.append(f"pid={child.pid} returncode={code} stdout={out!r} stderr={err!r}")
        return "\n".join(details)

    def _wait_gate(self, condition, label):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            diagnostics = self._child_diagnostics()
            if diagnostics:
                self.fail(f"{label}: controller exited before gate\n{diagnostics}")
            time.sleep(0.01)
        diagnostics = self._child_diagnostics()
        self.fail(f"{label}: condition did not become true before test deadline" +
                  (f"\n{diagnostics}" if diagnostics else ""))

    def cleanup(self):
        (self.gates / "release").write_text("cleanup\n")
        (self.gates / "start").write_text("cleanup\n")
        for child in self.children:
            if child.stdout is None and child.stderr is None:
                continue
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.communicate(timeout=5)

    def compete(self, same_root):
        for name in ("left", "right"):
            payload = {"root": str(self.base / ("shared" if same_root else name)),
                "scheduler": str(self.base / "installation"), "gates": str(self.gates),
                "request": "same-request" if same_root else name + "-request", "name": name}
            child = subprocess.Popen(python_command(HELPER, 'controller', '--job', json.dumps(payload)),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.children.append(child)
        self._wait_gate(lambda: all((self.gates / ("ready-"+n)).exists() for n in ("left", "right")),
                        "waiting for controller readiness")
        (self.gates / "start").write_text("start both controllers\n")
        self._wait_gate(lambda: all((self.gates / ("report-"+n)).exists() for n in ("left", "right")),
                        "waiting for controller reports")
        self._wait_gate(lambda: (self.gates / "invocations.jsonl").exists(), "waiting for invocation record")
        reports = [json.loads((self.gates / ("report-"+n)).read_text()) for n in ("left", "right")]
        self.assertEqual(len((self.gates / "invocations.jsonl").read_text().splitlines()), 1)
        (self.gates / "release").write_text("finish worker\n")
        for child in self.children:
            out, err = child.communicate(timeout=6)
            self.assertEqual(child.returncode, 0, f"stdout={out!r} stderr={err!r}")
        return reports

    def test_same_request_across_real_controller_processes_executes_at_most_once(self):
        reports = self.compete(True)
        self.assertTrue(all(report["accepted"] for report in reports))
        self.assertEqual(reports[0]["operation_id"], reports[1]["operation_id"])

    def test_different_task_directories_share_one_installation_slot_across_processes(self):
        reports = self.compete(False)
        self.assertEqual(sum(report["accepted"] for report in reports), 1)

    def test_crash_between_scheduler_and_local_commit_leaves_reconcilable_orphan(self):
        root, installation = self.base / "task", self.base / "installation"
        payload = {"root": str(root), "scheduler": str(installation), "marker": str(self.base / "orphan-committed")}
        child = subprocess.Popen(python_command(HELPER, 'orphan', '--job', json.dumps(payload)),
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.children.append(child)
        self.assertEqual(child.wait(timeout=6), 75)
        self.assertTrue((self.base / "orphan-committed").exists())
        calls = []
        service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=installation,
                                  worker_factory=lambda job: calls.append(job) or {"construction_executed": True})
        self.addCleanup(service.close)
        graph = service.propose(_proposal(), "same-proposal")
        with self.assertRaises(GraphJobError):
            service.trial(graph, "same-trial")
        self.assertTrue(service.reconcile_orphan()["released"])
        operation = service.trial(graph, "same-trial")
        wait_until(lambda: service.status(operation)["state"] == "SUCCEEDED")
        self.assertEqual(len(calls), 1)


class LeaseAndJournalFaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_revoke_waits_for_inflight_call_and_then_blocks_stale_executor(self):
        store = SceneLeaseStore(self.root / "lease.sqlite3")
        lease = store.acquire(task_id="t", session_id="s", process_generation="p", scene_id="scene", root="/obj/BRIDGE_GRAPH_t")
        entered, finish, revoke_started = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def dispatch():
            with store.operation(lease):
                calls.append("host-start"); entered.set(); finish.wait(4); calls.append("host-end")
        def revoke():
            revoke_started.set()
            store.revoke(lease, host_operations_reconciled=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            inflight = pool.submit(dispatch); self.assertTrue(entered.wait(2))
            revoked = pool.submit(revoke); self.assertTrue(revoke_started.wait(2))
            self.assertFalse(revoked.done())
            finish.set(); inflight.result(4); revoked.result(4)
        with self.assertRaises(ValueError):
            with store.operation(lease): calls.append("stale-host-call")
        self.assertEqual(calls, ["host-start", "host-end"])

    def test_journal_concurrent_claims_prevent_duplicate_host_mutations(self):
        compiled = graph_catalog.compiler().compile(_proposal())
        gate = threading.Barrier(2)
        addon = _FakeAddon()
        class Client:
            def call(self, command, params):
                if command == "node.children" and params["path"] == "/obj":
                    result = addon.dispatch(command, params)
                    gate.wait(3)
                    return result
                return addon.dispatch(command, params)
        journals = [DurableJournal(self.root / "journal.sqlite3") for _ in range(2)]
        executors = [GraphExecutor(Client(), journal, lease_guard=lambda *a: None) for journal in journals]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda executor: executor.execute("task", compiled), executors))
        creates = [p["name"] for c, p in addon.commands if c == "node.create"]
        roots = [p["root_name"] for c, p in addon.commands if c == "scene.create_task_root"]
        self.assertEqual(len(creates), len(set(creates)))
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(roots), 1, "the root must be created exactly once under the lease contract")
        self.assertTrue(any(result["construction_executed"] for result in results))

    def test_completed_journal_cannot_be_overwritten_by_late_unknown(self):
        journal = DurableJournal(self.root / "journal.sqlite3")
        intent = {"operation_id": "op", "status": "INTENT", "intent": {"kind": "create"}}
        self.assertTrue(journal.claim("op", intent))
        complete = {**intent, "status": "COMPLETE", "result": {"path": "/obj/BRIDGE_GRAPH_t/a"}}
        journal.write("op", complete)
        with self.assertRaises(ValueError):
            journal.write("op", {**intent, "status": "UNKNOWN"})
        self.assertEqual(journal.read("op"), complete)

    def standalone_worker(self, addon, *, clock=time.time):
        from dcc_task_runtime.canonical import canonical_sha256
        proposal = _proposal(); compiled = graph_catalog.compiler().compile(proposal).to_dict()
        graph_id = "graph_" + canonical_sha256({"compiled": compiled, "catalog_hash": graph_catalog.descriptor()["catalog_hash"]})
        directory = self.root / "graph-jobs" / "op_test"; directory.mkdir(parents=True)
        (directory / "proposal.json").write_text(json.dumps(proposal))
        (directory / "compiled.json").write_text(json.dumps(compiled))
        job = {"operation_id": "op_test", "graph_id": graph_id, "root": str(self.root), "repo_root": str(ROOT),
               "proposal_path": str(directory / "proposal.json"), "graph_path": str(directory / "compiled.json"),
               "result_path": str(directory / "result.json"), "journal_path": str(directory / "journal.sqlite3"),
               "lease_path": str(directory / "lease.sqlite3"), "deadline_at": clock() + 30}
        return GraphJobWorker(job, addon=addon, clock=clock)

    def test_scene_identity_change_after_host_effect_blocks_next_mutation(self):
        class ChangedHost(_FakeAddon):
            def dispatch(self, command, params):
                result = super().dispatch(command, params)
                if command == "node.create": self.scene_epoch += 1
                return result
        addon = ChangedHost(); worker = self.standalone_worker(addon)
        result = worker.run()
        self.assertTrue(result["reconciliation_required"])
        self.assertEqual(sum(c == "node.create" for c, _ in addon.commands), 1)
        self.assertNotIn("scene.save_hip", [c for c, _ in addon.commands])

    def test_lease_revoked_before_save_cannot_bypass_post_construction_fence(self):
        addon = _FakeAddon(); worker = self.standalone_worker(addon)
        original = GraphExecutor.execute
        def execute(executor, *args):
            result = original(executor, *args)
            worker.lease_store.revoke(worker.lease, host_operations_reconciled=True)
            return result
        with patch.object(GraphExecutor, "execute", execute): result = worker.run()
        self.assertTrue(result["construction_executed"])
        self.assertTrue(result["reconciliation_required"])
        self.assertNotIn("scene.save_hip", [c for c, _ in addon.commands])

    def test_expired_budget_before_save_preserves_unknown_lease_occupancy(self):
        now = [100.0]
        class ExpiringHost(_FakeAddon):
            def dispatch(self, command, params):
                result = super().dispatch(command, params)
                if command == "node.set_parms": now[0] = 1000.0
                return result
        addon = ExpiringHost(); worker = self.standalone_worker(addon, clock=lambda: now[0])
        result = worker.run()
        self.assertTrue(result["construction_executed"])
        self.assertTrue(result["reconciliation_required"])
        self.assertIsNotNone(worker.lease_store.current(worker.lease.session_id, worker.lease.scene_id))
        self.assertNotIn("scene.save_hip", [c for c, _ in addon.commands])
