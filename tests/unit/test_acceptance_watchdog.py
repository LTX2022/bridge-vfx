# -*- coding: utf-8 -*-
"""R08: exercise the shipped acceptance watchdog through its real CLI.

These tests intentionally launch ``accept_core_chain.py --watchdog-child``
instead of extracting a function from its source.  The watched processes are
test-owned Python children; no DCC or user process is touched.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "controller-entry" / "accept_core_chain.py"


def _load_entry_helpers():
    spec = importlib.util.spec_from_file_location("accept_core_chain_watchdog_helpers", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcceptanceWatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entry = _load_entry_helpers()

    def _host(self, workdir: Path, code: str, *, publish_ready=False):
        supervisor_identity = {
            "task_id": "watchdog-test-task", "operation_id": "watchdog-test-operation",
            "launch_nonce": "nonce-watchdog-test", "process_generation": "generation-watchdog-test",
        }
        if publish_ready:
            receipt = {key: supervisor_identity[key] for key in ('task_id', 'launch_nonce', 'process_generation')}
            receipt.update(port=1, protocol_version='task-host/1.0')
            prefix = (
                "import os,sys,json; from pathlib import Path; "
                "sys.path.insert(0," + repr(str(ROOT / 'packages/dcc-task-runtime/src')) + "); "
                "from dcc_task_runtime.platform_support import atomic_write; "
                "ready_payload=" + repr(receipt) + "; ready_payload['pid']=os.getpid(); "
                "atomic_write(Path(" + repr(str(workdir / 'host.ready')) + "), "
                "json.dumps(ready_payload).encode('utf-8'), owned_root=Path(" + repr(str(workdir)) + "))\n"
            )
            code = prefix + code
        if os.name == 'nt':
            from dcc_task_runtime.owned_process import launch
            interpreter = str(Path(sys._base_executable or sys.executable).resolve())
            child = launch([interpreter, '-X', 'utf8', '-c', code],
                           directory=workdir / 'owned-supervisor', identity=supervisor_identity,
                           supervisor_executable=interpreter)
        else:
            child = subprocess.Popen([sys.executable, "-c", code])
        identity = self.entry._process_identity(child.pid)
        self.assertTrue(identity, "the platform must expose a process-start identity")
        contract = {
            "task_id": "watchdog-test-task",
            "pid": child.pid,
            "launch_nonce": "nonce-watchdog-test",
            "process_generation": "generation-watchdog-test",
            "process_identity": identity,
        }
        if os.name == 'nt':
            contract.update(owned_supervisor_dir=str(child.directory),
                            owned_supervisor_identity=dict(child.identity))
        (workdir / "watchdog-contract.json").write_text(
            json.dumps(contract), encoding="utf-8")
        return child, contract

    def _plant_receipt(self, workdir: Path, contract: dict, *, generation: str | None = None):
        receipt = dict(contract)
        if generation is not None:
            receipt["process_generation"] = generation
        receipt.update({"port": 1, "protocol_version": "task-host/1.0"})
        (workdir / "host.ready").write_text(json.dumps(receipt), encoding="utf-8")

    def _run_child(self, workdir: Path, timeout: float, grace: float = 0.3,
                   *, reap_host=None):
        args = [sys.executable, str(ENTRY), "--watchdog-child",
                "--work-dir", str(workdir), "--timeout", str(timeout),
                "--grace", str(grace), "--identity-file",
                str(workdir / "watchdog-contract.json")]
        process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            if reap_host is not None:
                deadline = time.monotonic() + 15
                while process.poll() is None:
                    # The controller owns this child and must reap it before a
                    # separate watchdog can treat disappearance as confirmed.
                    reap_host.poll()
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(args, 15)
                    time.sleep(0.01)
            # Keep the controller's wait budget separate from the watchdog's
            # operation budget; process startup and machine load need margin.
            stdout, stderr = process.communicate(timeout=max(15.0, timeout + grace + 5.0))
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            raise
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)

    def _events(self, workdir: Path) -> dict:
        path = workdir / "watchdog-events.json"
        self.assertTrue(path.is_file(), "the CLI must persist watchdog evidence")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_missing_receipt_is_reported_by_real_cli(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-no-ready-") as tmp:
            workdir = Path(tmp)
            child, _ = self._host(workdir, "import time; time.sleep(2)")
            try:
                result = self._run_child(workdir, timeout=0.2)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("no_ready_receipt", [e["action"] for e in self._events(workdir)["events"]])
            finally:
                child.terminate()
                child.wait(timeout=5)

    def test_host_exiting_in_time_is_clean(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-healthy-") as tmp:
            workdir = Path(tmp)
            events_path = workdir / "watchdog-events.json"
            host_code = """import json, time
from pathlib import Path
events = Path({!r})
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    try:
        if any(item.get("action") == "watching"
               for item in json.loads(events.read_text()).get("events", [])):
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.01)
time.sleep(0.2)
""".format(str(events_path))
            child, contract = self._host(workdir, host_code, publish_ready=True)
            try:
                result = self._run_child(workdir, timeout=5.0, reap_host=child)
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            actions = [e["action"] for e in self._events(workdir)["events"]]
            self.assertIn("watching", actions)
            self.assertIn("host_exited_before_deadline", actions)
            self.assertNotIn("escalate_terminate_owned_pid", actions)

    def test_hung_host_is_stopped_and_unrelated_child_survives(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-hung-") as tmp:
            workdir = Path(tmp)
            child, contract = self._host(workdir, "import time; time.sleep(60)", publish_ready=True)
            unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                result = self._run_child(workdir, timeout=0.2, grace=0.2, reap_host=child)
                self.assertEqual(result.returncode, 3, {"stderr": result.stderr,
                                                       "events": self._events(workdir)})
                final = self._events(workdir)
                actions = [e["action"] for e in final["events"]]
                self.assertIn("timeout_stop_file", actions)
                self.assertIn("escalate_terminate_owned_job" if os.name == 'nt' else "escalate_terminate_owned_pid", actions)
                self.assertIn("stop_confirmed_after_supervisor" if os.name == 'nt' else "stop_confirmed_after_sigterm", actions)
                self.assertIsNotNone(child.poll(), "the owned host must be terminated")
                self.assertIsNone(unrelated.poll(), "an unrelated process must remain alive")
                gate_errors = self.entry.validate_watchdog_evidence({
                    **final, "present": True, "returncode": result.returncode,
                    "stderr": result.stderr, "expected_identity": contract})
                self.assertNotIn("watchdog stop/shutdown is unconfirmed", gate_errors)
                self.assertIn("watchdog returncode=3", gate_errors)
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)
                unrelated.terminate()
                unrelated.wait(timeout=5)

    @unittest.skipIf(os.name == 'nt', 'POSIX SIGTERM-ignore behavior; Windows Job stop is tested separately')
    def test_stop_not_effective_is_not_reported_as_confirmed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-ignore-stop-") as tmp:
            workdir = Path(tmp)
            child, contract = self._host(
                workdir, "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
            self._plant_receipt(workdir, contract)
            try:
                result = self._run_child(workdir, timeout=0.1, grace=0.1)
                self.assertEqual(result.returncode, 4, result.stderr)
                final = self._events(workdir)
                self.assertIn("stop_unconfirmed", [e["action"] for e in final["events"]])
                self.assertFalse(final["events"][-1].get("stop_confirmed", True))
                self.assertIsNone(child.poll())
            finally:
                child.kill()
                child.wait(timeout=5)

    def test_stale_generation_blocks_without_signalling_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-stale-") as tmp:
            workdir = Path(tmp)
            child, contract = self._host(workdir, "import time; time.sleep(60)")
            self._plant_receipt(workdir, contract, generation="generation-stale")
            try:
                result = self._run_child(workdir, timeout=0.5)
                self.assertEqual(result.returncode, 4, result.stderr)
                actions = [e["action"] for e in self._events(workdir)["events"]]
                self.assertIn("identity_mismatch", actions)
                self.assertIsNone(child.poll(), "a stale receipt must never be signalled")
            finally:
                child.terminate()
                child.wait(timeout=5)

    def test_process_identity_mismatch_never_signals_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-wrong-process-") as tmp:
            workdir = Path(tmp)
            child, contract = self._host(workdir, "import time; time.sleep(60)")
            wrong_contract = dict(contract, process_identity="proc-start:not-the-current-process")
            (workdir / "watchdog-contract.json").write_text(
                json.dumps(wrong_contract), encoding="utf-8")
            self._plant_receipt(workdir, wrong_contract)
            try:
                result = self._run_child(workdir, timeout=0.5)
                self.assertEqual(result.returncode, 4, result.stderr)
                events = self._events(workdir)["events"]
                self.assertIn("identity_mismatch", [event["action"] for event in events])
                mismatch = next(event for event in events if event["action"] == "identity_mismatch")
                self.assertEqual(mismatch.get("field"), "process_identity")
                self.assertIsNone(child.poll(), "an unverified PID must never be signalled")
            finally:
                child.terminate()
                child.wait(timeout=5)

    def test_operation_budget_starts_on_each_acknowledged_operation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-operation-budget-") as tmp:
            workdir = Path(tmp)
            stop_file = workdir / "host.stop"
            host_code = """import time
from pathlib import Path
stop = Path({!r})
deadline = time.monotonic() + 20
while time.monotonic() < deadline and not stop.is_file():
    time.sleep(0.01)
""".format(str(stop_file))
            child, contract = self._host(workdir, host_code, publish_ready=True)
            messages = workdir / "watchdog-messages"
            acknowledgements = workdir / "watchdog-acks"
            events = workdir / "watchdog-events.json"
            args = [sys.executable, str(ENTRY), "--watchdog-child",
                    "--work-dir", str(workdir), "--timeout", "0.25", "--grace", "0.2",
                    "--identity-file", str(workdir / "watchdog-contract.json"),
                    "--messages-dir", str(messages), "--acks-dir", str(acknowledgements),
                    "--shutdown-file", str(workdir / "watchdog-shutdown")]
            watchdog = None

            def wait_for(predicate, timeout=5.0):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    value = predicate()
                    if value:
                        return value
                    if watchdog is not None and watchdog.poll() is not None:
                        break
                    time.sleep(0.01)
                return None

            def send(seq, kind, operation_id):
                message = {"protocol_version": "watchdog-v2", "seq": seq,
                           "kind": kind, "operation_id": operation_id,
                           "task_id": contract["task_id"], "pid": contract["pid"],
                           "launch_nonce": contract["launch_nonce"],
                           "process_generation": contract["process_generation"],
                           "process_identity": contract["process_identity"]}
                # Publish the same atomic envelope used by the controller;
                # the watchdog deliberately rejects partially written JSON.
                self.entry._write_json_atomic(messages / ("%020d.json" % seq), message)
                ack_path = acknowledgements / ("%020d.json" % seq)
                ack = wait_for(lambda: json.loads(ack_path.read_text(encoding="utf-8"))
                               if ack_path.is_file() else None)
                self.assertEqual((ack or {}).get("status"), "accepted",
                                 "the CLI must durably acknowledge each operation message; "
                                 "rc={!r}, events={!r}".format(
                                     watchdog.poll(), self.entry._read_json_file(events)))

            try:
                # The tiny operation ceiling must not race the separately
                # spawned host's imports and atomic readiness publication.
                ready = wait_for(lambda: self.entry._read_json_file(workdir / 'host.ready'))
                self.assertIsInstance(ready, dict, 'owned host did not publish its ready receipt')
                for key in ('task_id', 'pid', 'launch_nonce', 'process_generation'):
                    self.assertEqual(ready.get(key), contract[key], ready)
                self.assertEqual(ready.get('protocol_version'), 'task-host/1.0', ready)
                watchdog = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True)
                watching = wait_for(lambda: next((event for event in
                    (json.loads(events.read_text(encoding="utf-8")).get("events") or [])
                    if event.get("action") == "watching"), None) if events.is_file() else None)
                self.assertIsNotNone(watching,
                    'the real watchdog CLI must confirm ready before timing operations; rc={!r}, events={!r}'.format(
                        watchdog.poll(), self.entry._read_json_file(events)))

                # Host startup and idle time between operations do not consume
                # the per-operation ceiling.
                time.sleep(0.35)
                self.assertIsNone(watchdog.poll(), "idle watchdog must remain alive beyond one operation budget")
                self.assertIsNone(child.poll())
                self.assertFalse(stop_file.exists())

                send(1, "start", "operation-one")
                time.sleep(0.1)
                send(2, "complete", "operation-one")
                time.sleep(0.35)
                self.assertIsNone(watchdog.poll(), "completed work must clear its deadline")
                self.assertIsNone(child.poll())
                self.assertFalse(stop_file.exists())

                send(3, "start", "operation-two")
                deadline = time.monotonic() + 5.0
                while watchdog.poll() is None and time.monotonic() < deadline:
                    child.poll()  # controller-side wait/reap of its owned child
                    time.sleep(0.01)
                stdout, stderr = watchdog.communicate(timeout=5)
                child.wait(timeout=5)
                self.assertEqual(watchdog.returncode, 3, {"stdout": stdout, "stderr": stderr})
                self.assertFalse(stderr.strip(), stderr)
                actions = self._events(workdir)["events"]
                started = [event["operation_id"] for event in actions
                           if event["action"] == "operation_started"]
                self.assertEqual(started, ["operation-one", "operation-two"])
                completed = [event["operation_id"] for event in actions
                             if event["action"] == "operation_completed"]
                self.assertEqual(completed, ["operation-one"])
                timeout = next(event for event in actions if event["action"] == "timeout_stop_file")
                self.assertEqual(timeout.get("operation_id"), "operation-two")
                stopped = next(event for event in actions
                               if event["action"] == "stopped_after_stop_file")
                self.assertEqual(stopped.get("operation_id"), "operation-two")
            finally:
                if watchdog is not None and watchdog.poll() is None:
                    watchdog.kill()
                    watchdog.communicate(timeout=5)
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)

    def test_supervisor_exception_without_events_fails_parent_gate_with_exit_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory(prefix="watchdog-supervisor-failure-") as tmp:
            workdir = Path(tmp)
            child, contract = self._host(workdir, "import time; time.sleep(60)")
            watchdog = None
            try:
                owned = SimpleNamespace(_ACTIVE_CHILDREN={child.pid: child})
                with mock.patch.object(self.entry, "th", owned):
                    watchdog = self.entry.start_watchdog(
                        workdir, timeout=0.5, receipt=contract, operation_mode=False)
                    # Force only the event destination into an unwritable shape
                    # after the real CLI starts, so its failure cannot be
                    # mistaken for a missing or successful readiness event.
                    watchdog._bridge_watchdog["events"].mkdir()
                    self.assertFalse(self.entry.wait_watchdog_ready(watchdog, timeout=5))
                    watchdog.wait(timeout=5)
                    evidence = self.entry.watchdog_process_evidence(watchdog)
                self.assertEqual(evidence["returncode"], 70, evidence)
                self.assertFalse(evidence["present"], evidence)
                self.assertIn("watchdog_exception_evidence_unavailable", evidence["stderr"])
                self.assertTrue(evidence["stderr_file"])
                self.assertIn("watchdog returncode=70", self.entry.validate_watchdog_evidence(
                    evidence, expected_operations=("operation-without-evidence",)))
                failures = self.entry.validate_watchdog_evidence(
                    evidence, expected_operations=("operation-without-evidence",))
                self.assertIn("watchdog events/ready evidence missing", failures)
                self.assertIn("watchdog missing ready/watch event", failures)
            finally:
                if watchdog is not None and watchdog.poll() is None:
                    watchdog.kill()
                    watchdog.wait(timeout=5)
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
