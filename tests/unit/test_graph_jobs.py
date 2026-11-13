"""Unit checks for the durable construction-only graph job boundary."""

from __future__ import annotations

import ast
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dcc_task_runtime.graph_compiler import GraphCompileError
from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_job_worker import GraphJobWorker, run_job
from vfx_pipeline.graph_jobs import GraphJobError, GraphJobService


def _proposal(*, nodes: int = 1, radius: float = 1.0) -> dict:
    payload = {
        "schema_version": "1.0",
        "nodes": [
            {
                "node_id": "sphere" if nodes == 1 else f"sphere_{index}",
                "node_type": "sop.sphere",
                "context": "houdini_sop",
                "parameters": {"radx": radius, "rady": 1.0, "radz": 1.0},
            }
            for index in range(nodes)
        ],
    }
    payload["outputs"] = [{"output_id": "output", "node_id": "sphere" if nodes == 1 else "sphere_0", "port": "geometry"}]
    return payload


class _Process:
    _next_pid = 1000

    def __init__(self, *, done: bool = False):
        self.pid = _Process._next_pid
        _Process._next_pid += 1
        self.done = done
        self.terminated = False

    def poll(self):
        return 0 if self.done or self.terminated else None

    def terminate(self):
        self.terminated = True


class _FakeAddon:
    def __init__(self):
        self.children = {"/obj": []}
        self.parameters = {}
        self.commands = []
        self.hip_path = str(Path.cwd() / "software-fixture-untitled.hip")
        self.scene_epoch = 0

    def graph_worker_identity(self):
        return {"session_id": "fake-session-" + str(id(self)),
                "process_generation": "fake-process-" + str(id(self)),
                "scene_id": "fake-scene-" + str(self.scene_epoch) + ":" + self.hip_path,
                "hip_path": self.hip_path}

    def dispatch(self, command, params):
        self.commands.append((command, dict(params)))
        if command == "node.children":
            nodes = []
            for path in self.children.get(params["path"], []):
                nodes.append({"path": path, "type": "geo" if path.rsplit("/", 1)[1].startswith("BRIDGE_GRAPH_") else "sphere"})
            return {"path": params["path"], "nodes": nodes}
        if command == "scene.create_task_root":
            root = params["parent"].rstrip("/") + "/" + params["root_name"]
            if not hasattr(self, "root_leases"):
                self.root_leases = {}
            if root in self.root_leases and self.root_leases[root] != params["task_id"]:
                raise AssertionError("SCENE_CONFLICT")
            if root not in self.children:
                self.children.setdefault(params["parent"], []).append(root)
                self.children[root] = []
            self.root_leases[root] = params["task_id"]
            return {"path": root, "type": params["type"], "reused": root in self.root_leases}
        if command == "node.create":
            path = params["parent"].rstrip("/") + "/" + params["name"]
            self.children.setdefault(params["parent"], []).append(path)
            self.children[path] = []
            return {"path": path, "type": params["type"]}
        if command == "node.set_parms":
            self.parameters[params["path"]] = dict(params["parms"])
            return {"path": params["path"], "values": dict(params["parms"])}
        if command == "node.connect":
            return {"source": params["source"], "destination": params["destination"]}
        if command == "node.parms":
            return {"path": params["path"], "parms": dict(self.parameters.get(params["path"], {}))}
        if command == "node.info":
            return {"path": params["path"], "errors": [], "warnings": []}
        if command == "scene.save_hip":
            Path(params["path"]).write_bytes(b"fake hip")
            self.hip_path = params["path"]
            return {"path": params["path"]}
        if command in {"scene.open_hip", "scene.reopen_owned_hip"}:
            path = Path(params["path"])
            self.hip_path = str(path)
            self.scene_epoch += 1
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "owned_headless_reopen": command == "scene.reopen_owned_hip",
                    "has_unsaved_changes": None if command == "scene.reopen_owned_hip" else False}
        raise AssertionError(f"unexpected add-on command: {command}")


class GraphJobServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]

    def test_software_launch_requires_authorization_and_frozen_content(self):
        script=self.root/'软件 bootstrap.py'
        script.write_text('raise SystemExit(0)\n',encoding='utf-8')
        for authorized in (False,None,1,'yes'):
            with self.subTest(authorized=authorized),self.assertRaisesRegex(GraphJobError,'NOT_AUTHORIZED'):
                GraphJobService(self.root,self.repo,'python',software_launch_script=script,
                    software_processes=authorized)
        frozen=hashlib.sha256(script.read_bytes()).hexdigest()
        script.write_text('raise SystemExit(1)\n',encoding='utf-8')
        with self.assertRaisesRegex(GraphJobError,'SCRIPT_CHANGED'):
            GraphJobService(self.root,self.repo,'python',software_launch_script=script,
                software_launch_script_sha256=frozen,software_processes=True)

    def test_propose_is_strict_bounded_and_idempotent(self):
        service = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=lambda job: {"construction_executed": True})
        self.addCleanup(service.close)
        proposal = _proposal()
        graph_id = service.propose(proposal, "proposal-1")
        self.assertEqual(graph_id, service.propose(dict(reversed(proposal.items())), "proposal-1"))
        with self.assertRaises(GraphJobError):
            service.propose(_proposal(radius=2.0), "proposal-1")
        with self.assertRaises(GraphJobError):
            service.propose(_proposal(nodes=9), "proposal-9")

    def test_worker_environment_uses_versioned_private_houdini_preferences(self):
        service = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=lambda job: {"construction_executed": True})
        self.addCleanup(service.close)
        task_directory = self.root / "graph-jobs" / "environment-check"
        environment = service._worker_env(task_directory)
        self.assertEqual(environment["HOUDINI_USER_PREF_DIR"], str(task_directory / "houdini-user-pref" / "__HVER__"))
        self.assertTrue((task_directory / "houdini-user-pref").is_dir())
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        for name, directory in (("HOUDINI_BRIDGE_STATE_DIR", "graph-houdini-instances"),
                                ("HOUDINI_BRIDGE_TASK_STATE_DIR", "houdini-instances"),
                                ("BRIDGE_SKILLS_STATE_ROOT", "graph-runtime-state"),
                                ("BRIDGE_ARTIFACT_LEDGER_ROOT", "artifact_ledger")):
            with mock.patch.dict('os.environ', {name: 'foreign-state-root'}):
                bounded = service._worker_env(task_directory)
            self.assertEqual(bounded[name], str(service.root.parent / directory))
        for key in ("PYTHONPATH", "PYTHONHOME", "HOUDINI_PATH", "HSITE", "HOUDINI_OTLSCAN_PATH", "HOUDINI_PACKAGE_DIR", "HOUDINI_SCRIPT_PATH"):
            self.assertNotIn(key, environment)
        with mock.patch.dict('os.environ', {'BRIDGE_OWNED_SUPERVISOR_DIR': 'foreign-directory',
                                           'BRIDGE_OWNED_SUPERVISOR_IDENTITY': '{"operation_id":"foreign"}'}):
            clean = service._worker_env(task_directory)
        self.assertNotIn('BRIDGE_OWNED_SUPERVISOR_DIR', clean)
        self.assertNotIn('BRIDGE_OWNED_SUPERVISOR_IDENTITY', clean)

    def test_trial_persists_intention_and_reuses_stable_operation(self):
        service = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=lambda job: {"construction_executed": True})
        self.addCleanup(service.close)
        graph_id = service.propose(_proposal(), "proposal-1")
        operation_id = service.trial(graph_id, "trial-1")
        self.assertEqual(operation_id, service.trial(graph_id, "trial-1"))
        for _ in range(50):
            if service.status(operation_id)["state"] == "SUCCEEDED":
                break
            time.sleep(0.01)
        self.assertEqual(service.status(operation_id)["state"], "SUCCEEDED")
        with self.assertRaises(GraphJobError):
            service.trial("graph_missing", "trial-2")

    def test_two_service_instances_reserve_one_active_slot(self):
        barrier = threading.Event()

        def worker(_job):
            barrier.wait(0.3)
            return {"construction_executed": True}

        first = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=worker)
        second = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=worker)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        graph_id = first.propose(_proposal(), "proposal-1")
        results = []

        def call(service, request):
            try:
                results.append(service.trial(graph_id, request))
            except GraphJobError:
                results.append("rejected")

        left = threading.Thread(target=call, args=(first, "trial-a"))
        right = threading.Thread(target=call, args=(second, "trial-b"))
        left.start(); right.start(); left.join(); right.join()
        barrier.set()
        for service in (first, second):
            for thread in service._threads.values():
                thread.join(timeout=1.0)
        self.assertEqual(sum(item != "rejected" for item in results), 1)

    def test_reconnect_marks_unknown_startup_without_relaunch(self):
        calls = []
        launched = threading.Event()

        def worker(job):
            calls.append(job)
            launched.set()
            return _Process()

        first = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=worker)
        self.addCleanup(first.close)
        graph_id = first.propose(_proposal(), "proposal-1")
        operation_id = first.trial(graph_id, "trial-1")
        self.assertTrue(launched.wait(5), "worker launch was not observed")
        second = GraphJobService(self.root, self.repo, "hython", scheduler_root=self.root / "installation", worker_factory=worker)
        self.addCleanup(second.close)
        self.assertEqual(second.status(operation_id)["state"], "RECONCILIATION_REQUIRED")
        self.assertEqual(len(calls), 1)

    def _start_blocked_worker(self, service):
        entered, release = threading.Event(), threading.Event()
        completed = threading.Event()
        writes = []

        def worker(job):
            entered.set()
            if not release.wait(8):
                raise TimeoutError("test worker was not released")
            output = Path(job["root"]) / "thread-finished.txt"
            output.write_text("actual in-process worker file write", encoding="utf-8")
            writes.append((output, sys.modules.get("hou")))
            completed.set()
            return {}

        service.worker_factory = worker
        operation = service.trial(service.propose(_proposal(), "close-proposal"), "close-trial")

        def cleanup():
            release.set()
            for thread in service._all_threads:
                thread.join(5)
            service.close()
            resources = getattr(service, "software_resources", None)
            if resources is not None:
                resources.cleanup()

        self.addCleanup(cleanup)
        self.assertTrue(entered.wait(5))
        return operation, release, completed, writes

    def test_default_close_reports_real_blocked_thread_and_keeps_slot(self):
        service = GraphJobService(self.root, self.repo, "NEVER_A_DCC",
                                  scheduler_root=self.root / "installation", worker_factory=lambda job: {})
        operation, release, completed, writes = self._start_blocked_worker(service)
        started = time.monotonic()
        summary = service.close()
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(summary["pending_monitors"], 1)
        self.assertIn(operation, summary["unconfirmed_workers"])
        self.assertFalse(completed.is_set())
        self.assertTrue(service._threads[operation].is_alive())
        self.assertEqual(service._row(operation)["cancel_requested"], 1)
        self.assertTrue(service.scheduler.snapshot()["active"])
        release.set()
        service._threads[operation].join(5)
        self.assertTrue(completed.is_set())
        self.assertTrue(writes[0][0].is_file())

    def _software_manifest(self, name="prepared"):
        with mock.patch.object(sys, "path", [str(self.repo / "tools"), *sys.path]):
            from prepare_workbuddy_graph import _prepare_software

        prepared = _prepare_software(self.root / name)
        manifest_path = prepared["control"] / "run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(construction_authorized=True, execution_authorized=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_software_context_drains_actual_thread_before_api_restore_on_both_exits(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade

        for exceptional_exit in (False, True):
            with self.subTest(exceptional_exit=exceptional_exit), mock.patch.dict(os.environ, {
                    "HOUDINI_BRIDGE_STATE_DIR": str(self.root / "houdini-state"),
                    "BRIDGE_SKILLS_STATE_ROOT": str(self.root / "runtime-state")}):
                manifest = self._software_manifest("prepared-" + str(exceptional_exit))
                previous_modules = {name: sys.modules.get(name) for name in ("hou", "nuke")}
                timer = release = service = None
                try:
                    try:
                        with prepared_graph_facade(manifest, repo_root=self.repo,
                                scheduler_root=self.root / "installation", backend="software") as facade:
                            service = facade.jobs_service
                            operation, release, completed, writes = self._start_blocked_worker(service)
                            fake_hou = sys.modules["hou"]
                            timer = threading.Timer(1.3, release.set)
                            timer.start()
                            if exceptional_exit:
                                raise RuntimeError("body failure")
                    except RuntimeError as error:
                        self.assertTrue(exceptional_exit)
                        self.assertEqual(str(error), "body failure")
                    self.assertTrue(completed.is_set(), "context returned while the real worker was still running")
                    self.assertFalse(service._threads[operation].is_alive())
                    self.assertIs(writes[0][1], fake_hou)
                    self.assertTrue(writes[0][0].is_file())
                finally:
                    if release is not None:
                        release.set()
                        service._threads[operation].join(5)
                    if timer is not None:
                        timer.join(5)
                    for name, previous in previous_modules.items():
                        if previous is None:
                            sys.modules.pop(name, None)
                        else:
                            sys.modules[name] = previous

    def test_in_process_drain_timeout_is_unknown_and_retains_slot(self):
        service = GraphJobService(self.root, self.repo, "NEVER_A_DCC",
                                  scheduler_root=self.root / "installation", worker_factory=lambda job: {})
        operation, release, completed, writes = self._start_blocked_worker(service)
        started = time.monotonic()
        summary = service.close(drain_in_process=True, drain_timeout_seconds=0.05)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(summary["pending_monitors"], 1)
        self.assertIn(operation, summary["unconfirmed_workers"])
        self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(completed.is_set())
        self.assertTrue(service.scheduler.snapshot()["active"])

    def test_in_process_drain_uses_remaining_original_budget(self):
        now = [time.time()]
        service = GraphJobService(self.root, self.repo, "NEVER_A_DCC", clock=lambda: now[0],
                                  scheduler_root=self.root / "installation", worker_factory=lambda job: {})
        operation, release, completed, writes = self._start_blocked_worker(service)
        original_deadline = service._row(operation)["deadline_at"]
        now[0] = original_deadline - 0.08
        started = time.monotonic()
        summary = service.close(drain_in_process=True, drain_timeout_seconds=120)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(summary["pending_monitors"], 1)
        self.assertEqual(service._row(operation)["deadline_at"], original_deadline)
        self.assertTrue(service.scheduler.snapshot()["active"])

    def test_expired_in_process_budget_gets_only_small_cleanup_allowance(self):
        now = [time.time()]
        service = GraphJobService(self.root, self.repo, "NEVER_A_DCC", clock=lambda: now[0],
                                  scheduler_root=self.root / "installation", worker_factory=lambda job: {})
        operation, release, completed, writes = self._start_blocked_worker(service)
        original_deadline = service._row(operation)["deadline_at"]
        now[0] = original_deadline + 1
        started = time.monotonic()
        summary = service.close(drain_in_process=True)
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(summary["pending_monitors"], 1)
        self.assertEqual(service._row(operation)["deadline_at"], original_deadline)
        self.assertTrue(service.scheduler.snapshot()["active"])

    def test_software_context_unconfirmed_drain_exposes_unknown_and_keeps_slot(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade

        manifest = self._software_manifest()
        previous_modules = {name: sys.modules.get(name) for name in ("hou", "nuke")}
        release = service = None
        try:
            with mock.patch.dict(os.environ, {
                    "HOUDINI_BRIDGE_STATE_DIR": str(self.root / "houdini-state"),
                    "BRIDGE_SKILLS_STATE_ROOT": str(self.root / "runtime-state")}):
                with self.assertRaisesRegex(GraphJobError, "SOFTWARE_WORKER_DRAIN_UNCONFIRMED") as raised:
                    with prepared_graph_facade(manifest, repo_root=self.repo,
                            scheduler_root=self.root / "installation", backend="software") as facade:
                        service = facade.jobs_service
                        operation, release, completed, writes = self._start_blocked_worker(service)
                        original_deadline = service._row(operation)["deadline_at"]
                        service.clock = lambda: original_deadline - 0.05
                self.assertEqual(raised.exception.close_summary["pending_monitors"], 1)
                self.assertIn(operation, raised.exception.close_summary["unconfirmed_workers"])
                self.assertFalse(completed.is_set())
                self.assertTrue(service._threads[operation].is_alive())
                self.assertTrue(service.scheduler.snapshot()["active"])
                self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
        finally:
            if release is not None:
                release.set()
                service._threads[operation].join(5)
            for name, previous in previous_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


    def test_pending_drain_preserves_body_error_and_generated_server_reports_both(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade

        manifest = self._software_manifest()
        previous_modules = {name: sys.modules.get(name) for name in ("hou", "nuke")}
        release = service = None
        original_error = RuntimeError("original body failure")
        try:
            with mock.patch.dict(os.environ, {
                    "HOUDINI_BRIDGE_STATE_DIR": str(self.root / "houdini-state"),
                    "BRIDGE_SKILLS_STATE_ROOT": str(self.root / "runtime-state")}):
                with self.assertRaises(RuntimeError) as raised:
                    with prepared_graph_facade(manifest, repo_root=self.repo,
                            scheduler_root=self.root / "installation", backend="software") as facade:
                        service = facade.jobs_service
                        operation, release, completed, writes = self._start_blocked_worker(service)
                        original_deadline = service._row(operation)["deadline_at"]
                        service.clock = lambda: original_deadline - 0.05
                        raise original_error
                self.assertIs(raised.exception, original_error)
                self.assertEqual(str(raised.exception), "original body failure")
                self.assertEqual(raised.exception.close_summary["pending_monitors"], 1)
                self.assertIn(operation, raised.exception.close_summary["unconfirmed_workers"])
                self.assertEqual(raised.exception.cleanup_issue, "SOFTWARE_WORKER_DRAIN_UNCONFIRMED")
                self.assertIn("SOFTWARE_WORKER_DRAIN_UNCONFIRMED", " ".join(raised.exception.__notes__))
                self.assertTrue(service._threads[operation].is_alive())
                self.assertFalse(completed.is_set())
                self.assertEqual(service._row(operation)["cancel_requested"], 1)
                self.assertEqual(service.status(operation)["state"], "RECONCILIATION_REQUIRED")
                self.assertTrue(service.scheduler.snapshot()["active"])

                generator = ast.parse((self.repo / "tools/prepare_workbuddy_graph.py").read_text(encoding="utf-8"))
                launcher = next(node.value for node in ast.walk(generator)
                                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                                and "with prepared_graph_facade(ROOT" in node.value)
                handler = next(node for node in ast.parse(launcher).body if isinstance(node, ast.Try)).handlers
                statement = ast.Try(body=[ast.Raise(exc=ast.Name(id="original_error", ctx=ast.Load()))],
                                    handlers=handler, orelse=[], finalbody=[])
                syntax = ast.fix_missing_locations(ast.Module(body=[statement], type_ignores=[]))
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as exited, mock.patch.object(
                        os, "_exit", side_effect=SystemExit(2)) as abort_controller:
                    exec(compile(syntax, "generated-server-error-handler", "exec"),
                         {"original_error": original_error, "facade": facade, "json": json,
                          "backend": "software", "_os": os, "sys": sys})
                self.assertEqual(exited.exception.code, 2)
                abort_controller.assert_called_once_with(2)
                receipt = json.loads(output.getvalue())
                self.assertEqual(receipt["error_type"], "RuntimeError")
                self.assertEqual(receipt["message"], "original body failure")
                self.assertEqual(receipt["close_summary"], original_error.close_summary)
                self.assertEqual(receipt["cleanup_issue"], "SOFTWARE_WORKER_DRAIN_UNCONFIRMED")
                self.assertTrue(service._threads[operation].is_alive())
        finally:
            if release is not None:
                release.set()
                service._threads[operation].join(5)
            for name, previous in previous_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous

    def test_software_close_failure_keeps_cleanup_error_visible_with_body_error(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade

        for body_failure in (False, True):
            with self.subTest(body_failure=body_failure), mock.patch.dict(os.environ, {
                    "HOUDINI_BRIDGE_STATE_DIR": str(self.root / "houdini-state"),
                    "BRIDGE_SKILLS_STATE_ROOT": str(self.root / "runtime-state")}):
                manifest = self._software_manifest("close-failure-" + str(body_failure))
                previous_modules = {name: sys.modules.get(name) for name in ("hou", "nuke")}
                original_error, cleanup_error = RuntimeError("body failure"), OSError("close failure")
                service = close_failure = None
                try:
                    try:
                        raise LookupError("unrelated caller exception")
                    except LookupError as ambient_error:
                        with self.assertRaises(RuntimeError if body_failure else OSError) as raised:
                            with prepared_graph_facade(manifest, repo_root=self.repo,
                                    scheduler_root=self.root / "installation", backend="software") as facade:
                                service = facade.jobs_service
                                close_failure = mock.patch.object(service, "close", side_effect=cleanup_error)
                                close_failure.start()
                                if body_failure:
                                    raise original_error
                        self.assertFalse(hasattr(ambient_error, "cleanup_issue"))
                    if body_failure:
                        self.assertIs(raised.exception, original_error)
                        self.assertIs(raised.exception.cleanup_error, cleanup_error)
                        self.assertEqual(raised.exception.cleanup_issue, "SOFTWARE_WORKER_CLOSE_FAILED")
                        self.assertIn("SOFTWARE_WORKER_CLOSE_FAILED", " ".join(raised.exception.__notes__))
                    else:
                        self.assertIs(raised.exception, cleanup_error)
                finally:
                    if close_failure is not None:
                        close_failure.stop()
                        service.close()
                        service.software_resources.cleanup()
                    for name, previous in previous_modules.items():
                        if previous is None:
                            sys.modules.pop(name, None)
                        else:
                            sys.modules[name] = previous


class SoftwareResourceLifecycleTests(unittest.TestCase):
    setUp = GraphJobServiceTests.setUp
    _software_manifest = GraphJobServiceTests._software_manifest
    _start_blocked_worker = GraphJobServiceTests._start_blocked_worker
    def test_legacy_outer_cleanup_destroys_resources_while_worker_is_pending(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade

        temporary = tempfile.TemporaryDirectory(dir=self.root)
        directory = Path(temporary.name)
        entered, release = threading.Event(), threading.Event()
        observed = {}
        previous_hou = sys.modules.get("hou")
        service = None

        def worker(job):
            entered.set()
            release.wait(5)
            observed.update(hou=sys.modules.get("hou"), state=os.environ.get("BRIDGE_SKILLS_STATE_ROOT"))
            try:
                (directory / "native-write.txt").write_text("native boundary write", encoding="utf-8")
            except OSError as error:
                observed["write_error"] = type(error).__name__
            return {}

        try:
            with self.assertRaises(GraphJobError):
                with temporary, mock.patch.dict(sys.modules), mock.patch.dict(os.environ, {
                        "HOUDINI_BRIDGE_STATE_DIR": str(directory / "houdini"),
                        "BRIDGE_SKILLS_STATE_ROOT": str(directory / "state")}):
                    with prepared_graph_facade(self._software_manifest(), repo_root=self.repo,
                            scheduler_root=self.root / "installation", backend="software") as facade:
                        service = facade.jobs_service
                        service.worker_factory = worker
                        operation = service.trial(service.propose(_proposal(), "outer-proposal"), "outer-trial")
                        self.assertTrue(entered.wait(5))
                        service.clock = lambda: service._row(operation)["deadline_at"] - 0.03
                        fake_hou = sys.modules["hou"]
            self.assertTrue(service._threads[operation].is_alive())
            self.assertFalse(directory.exists())
            self.assertIs(sys.modules.get("hou"), previous_hou)
            release.set()
            service._threads[operation].join(5)
            self.assertIsNot(observed["hou"], fake_hou)
            self.assertIn("write_error", observed)
        finally:
            release.set()
            if service is not None:
                for thread in service._all_threads:
                    thread.join(5)
                service.software_resources.cleanup()
            temporary.cleanup()

    def test_owned_outer_resources_retain_pending_and_cleanup_only_after_actual_thread_exit(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade, SoftwareGraphResources

        for body_failure in (False, True):
            with self.subTest(body_failure=body_failure):
                temporary = tempfile.TemporaryDirectory(dir=self.root)
                directory = Path(temporary.name)
                environment = {"HOUDINI_BRIDGE_STATE_DIR": str(directory / "houdini"),
                               "BRIDGE_SKILLS_STATE_ROOT": str(directory / "state")}
                prior_environment = {name: os.environ.get(name) for name in environment}
                prior_hou = sys.modules.get("hou")
                owner = SoftwareGraphResources(temporary_directory=temporary, environment=environment)
                entered, release = threading.Event(), threading.Event()
                observed = {}
                service = None
                original_error = RuntimeError("body failed while native worker pending")

                def worker(job):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("test release missing")
                    observed.update(hou=sys.modules.get("hou"), state=os.environ.get("BRIDGE_SKILLS_STATE_ROOT"))
                    (directory / "native-write.txt").write_text("actual worker file operation", encoding="utf-8")
                    return {}

                try:
                    with self.assertRaises(RuntimeError if body_failure else GraphJobError) as raised:
                        with owner:
                            with prepared_graph_facade(self._software_manifest("owned-" + str(body_failure)),
                                    repo_root=self.repo, scheduler_root=self.root / "installation",
                                    backend="software", software_resources=owner) as facade:
                                service = facade.jobs_service
                                service.worker_factory = worker
                                operation = service.trial(service.propose(_proposal(), "owned-proposal"), "owned-trial")
                                self.assertTrue(entered.wait(5))
                                service.clock = lambda: service._row(operation)["deadline_at"] - 0.03
                                fake_hou = sys.modules["hou"]
                                service.close(drain_in_process=True, drain_timeout_seconds=0)
                                with self.assertRaisesRegex(GraphJobError, "SOFTWARE_RESOURCES_BUSY"):
                                    owner.bind(service)
                                if body_failure:
                                    raise original_error
                    if body_failure:
                        self.assertIs(raised.exception, original_error)
                    self.assertIs(raised.exception.software_resources, owner)
                    self.assertFalse(owner.cleanup())
                    self.assertTrue(directory.is_dir())
                    self.assertIs(sys.modules["hou"], fake_hou)
                    self.assertEqual(os.environ["BRIDGE_SKILLS_STATE_ROOT"], environment["BRIDGE_SKILLS_STATE_ROOT"])
                    self.assertTrue(service._threads[operation].is_alive())
                    self.assertTrue(service.scheduler.snapshot()["active"])
                    self.assertEqual(service._row(operation)["cancel_requested"], 1)
                    with self.assertRaisesRegex(GraphJobError, "SOFTWARE_RESOURCES_BUSY"):
                        with SoftwareGraphResources():
                            self.fail("pending owner must prevent replacement of global native API modules")
                    release.set()
                    service._threads[operation].join(5)
                    self.assertFalse(service._threads[operation].is_alive())
                    self.assertIs(observed["hou"], fake_hou)
                    self.assertEqual(observed["state"], environment["BRIDGE_SKILLS_STATE_ROOT"])
                    self.assertTrue((directory / "native-write.txt").is_file())
                    self.assertTrue(owner.cleanup())
                    self.assertFalse(directory.exists())
                    self.assertIs(sys.modules.get("hou"), prior_hou)
                    for name, value in prior_environment.items():
                        self.assertEqual(os.environ.get(name), value)
                    self.assertTrue(owner.cleanup())
                finally:
                    release.set()
                    if service is not None:
                        for thread in service._all_threads:
                            thread.join(5)
                    owner.cleanup()

    def test_owned_resources_normal_and_body_error_cleanup_after_completed_thread(self):
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade, SoftwareGraphResources

        for body_failure in (False, True):
            with self.subTest(body_failure=body_failure):
                temporary = tempfile.TemporaryDirectory(dir=self.root)
                directory = Path(temporary.name)
                previous_hou = sys.modules.get("hou")
                original_error = RuntimeError("completed worker body error")
                owner = SoftwareGraphResources(temporary_directory=temporary, environment={
                    "HOUDINI_BRIDGE_STATE_DIR": str(directory / "houdini")})
                try:
                    try:
                        with owner:
                            with prepared_graph_facade(self._software_manifest("completed-" + str(body_failure)),
                                    repo_root=self.repo, scheduler_root=self.root / "installation",
                                    backend="software", software_resources=owner) as facade:
                                operation, release, completed, writes = self._start_blocked_worker(facade.jobs_service)
                                release.set()
                                facade.jobs_service._threads[operation].join(5)
                                self.assertTrue(completed.is_set())
                                if body_failure:
                                    raise original_error
                    except RuntimeError as error:
                        self.assertTrue(body_failure)
                        self.assertIs(error, original_error)
                    self.assertFalse(directory.exists())
                    self.assertIs(sys.modules.get("hou"), previous_hou)
                    self.assertFalse(owner.snapshot()["retained"])
                finally:
                    owner.cleanup()



class GraphJobWorkerTests(unittest.TestCase):
    def test_worker_keeps_execution_fact_when_artifact_reconciliation_fails(self):
        class ReopenFailureAddon(_FakeAddon):
            def dispatch(self, command, params):
                if command == "scene.reopen_owned_hip":
                    raise RuntimeError("host detail belongs only in local error.txt")
                return super().dispatch(command, params)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = Path(__file__).resolve().parents[2]
            proposal = _proposal()
            compiled = graph_catalog.compiler().compile(proposal).to_dict()
            graph_id = "graph_" + __import__("dcc_task_runtime.canonical", fromlist=["canonical_sha256"]).canonical_sha256({"compiled": compiled, "catalog_hash": graph_catalog.descriptor()["catalog_hash"]})
            operation_id = "op_reopen_failure"
            job_dir = root / "graph-jobs" / operation_id
            job_dir.mkdir(parents=True)
            (job_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
            (job_dir / "compiled.json").write_text(json.dumps(compiled), encoding="utf-8")
            job = {
                "operation_id": operation_id,
                "graph_id": graph_id,
                "root": str(root),
                "repo_root": str(repo),
                "proposal_path": str(job_dir / "proposal.json"),
                "graph_path": str(job_dir / "compiled.json"),
                "result_path": str(job_dir / "result.json"),
                "journal_path": str(job_dir / "journal.sqlite3"),
                "lease_path": str(job_dir / "lease.sqlite3"),
                "deadline_at": time.time() + 30,
            }
            addon = ReopenFailureAddon()
            hip_file = SimpleNamespace(setName=lambda path: setattr(addon, 'hip_path', path),
                                       path=lambda: addon.hip_path)
            with mock.patch.dict(sys.modules, {'hou': SimpleNamespace(hipFile=hip_file)}):
                result = run_job(job, addon=addon)
            self.assertTrue(result["construction_executed"])
            self.assertTrue(result["reconciliation_required"])
            self.assertEqual(result["diagnostics"][0]["code"], "WORKER_RECONCILIATION_REQUIRED")
            self.assertTrue((job_dir / "error.txt").is_file())

    def test_worker_recompiles_saves_reopens_and_reports_no_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = Path(__file__).resolve().parents[2]
            proposal = _proposal()
            compiled = graph_catalog.compiler().compile(proposal).to_dict()
            graph_id = "graph_" + __import__("dcc_task_runtime.canonical", fromlist=["canonical_sha256"]).canonical_sha256({"compiled": compiled, "catalog_hash": graph_catalog.descriptor()["catalog_hash"]})
            operation_id = "op_worker"
            job_dir = root / "graph-jobs" / operation_id
            job_dir.mkdir(parents=True)
            (job_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
            (job_dir / "compiled.json").write_text(json.dumps(compiled), encoding="utf-8")
            job = {
                "operation_id": operation_id,
                "graph_id": graph_id,
                "root": str(root),
                "repo_root": str(repo),
                "proposal_path": str(job_dir / "proposal.json"),
                "graph_path": str(job_dir / "compiled.json"),
                "result_path": str(job_dir / "result.json"),
                "journal_path": str(job_dir / "journal.sqlite3"),
                "lease_path": str(job_dir / "lease.sqlite3"),
                "deadline_at": time.time() + 30,
            }
            addon = _FakeAddon()
            hip_file = SimpleNamespace(setName=lambda path: setattr(addon, 'hip_path', path),
                                       path=lambda: addon.hip_path)
            with mock.patch.dict(sys.modules, {'hou': SimpleNamespace(hipFile=hip_file)}):
                result = run_job(job, addon=addon)
            self.assertTrue(result["construction_executed"])
            self.assertFalse(result["visual_verified"])
            self.assertTrue(result["verification"]["nodes_verified"])
            self.assertTrue((job_dir / "op_worker.hip").is_file())
            self.assertTrue((job_dir / "result.json").is_file())
            self.assertNotIn("node.cook", [command for command, _ in addon.commands])

    def test_worker_rejects_tampered_compiled_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = Path(__file__).resolve().parents[2]
            job_dir = root / "graph-jobs" / "op"
            job_dir.mkdir(parents=True)
            proposal = _proposal()
            (job_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
            (job_dir / "compiled.json").write_text(json.dumps({"graph_hash": "tampered"}), encoding="utf-8")
            job = {"operation_id": "op", "graph_id": "graph_tampered", "root": str(root), "repo_root": str(repo),
                   "proposal_path": str(job_dir / "proposal.json"), "graph_path": str(job_dir / "compiled.json"),
                   "result_path": str(job_dir / "result.json"), "journal_path": str(job_dir / "journal.sqlite3"),
                   "lease_path": str(job_dir / "lease.sqlite3"), "deadline_at": time.time() + 30}
            result = run_job(job, addon=_FakeAddon())
            self.assertTrue(result["reconciliation_required"])
            self.assertFalse(result["construction_executed"])


if __name__ == "__main__":
    unittest.main()
