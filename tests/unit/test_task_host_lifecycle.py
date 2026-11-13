# -*- coding: utf-8 -*-
"""T04: task-host lifecycle under controlled subprocesses (no real DCC).

A Python bootstrap injects native APIs into the shipped add-on so the
LAUNCHER contract is exercised for real:

- start atomically claims the work directory: concurrent launches cannot
  double-start (one wins, the loser gets ACTIVE_OWNER);
- the ready receipt is fully verified (nonce AND live pid AND task id AND
  protocol AND build hash AND port); a mismatched receipt refuses and reclaims
  the launcher's own child;
- ready timeout reclaims (stop file -> grace -> terminate);
- stop returns non-zero unless the process exit is confirmed; the shutdown
  receipt alone is not sufficient.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

import houdini_bridge.task_host as task_host  # noqa: E402

from software_host_bootstrap import LIFECYCLE_BOOTSTRAP, SOFTWARE_PYTHON


class TaskHostLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="task-host-lifecycle-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.fake_hython = self.tmp / "fake-hython.py"
        self.fake_hython.write_text(LIFECYCLE_BOOTSTRAP, encoding="utf-8")
        self.addon_root = ROOT / "plugins" / "houdini"
        self.addCleanup(self._cleanup_hosts)

    def _cleanup_hosts(self):
        from dcc_task_runtime.owned_process import OwnedProcessHandle
        for path in self.tmp.rglob("supervisor-binding.json"):
            binding = json.loads(path.read_text(encoding="utf-8"))
            child = OwnedProcessHandle(binding["directory"], binding["identity"])
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            task_host._ACTIVE_CHILDREN.pop(child.pid, None)

    def _args(self, workdir: Path, scenario: str, ready_timeout: float = 15.0, **extra):
        return argparse.Namespace(task_id="lifecycle-task", work_dir=str(workdir),
                                  addon_root=str(self.addon_root), houdini_bin=str(SOFTWARE_PYTHON),
                                  supervisor_executable=str(SOFTWARE_PYTHON),
                                  software_launch_script=str(self.fake_hython), evidence_source="software_test",
                                  allow_software_processes=True,
                                  environment={"FAKE_HOST_SCENARIO": scenario,
                                      "HOUDINI_BRIDGE_STATE_DIR": str(self.tmp / "instances"),
                                      "BRIDGE_SKILLS_STATE_ROOT": str(self.tmp / "runtime")},
                                  max_seconds=120, ready_timeout=ready_timeout,
                                  poll_seconds=0.02, warmup=False, **extra)

    def _start(self, workdir: Path, scenario: str, ready_timeout: float = 15.0, **extra):
        captured = io.StringIO()
        with redirect_stdout(captured):
            rc = task_host.start(self._args(workdir, scenario, ready_timeout, **extra))
        return rc, captured.getvalue()

    def _stop(self, workdir: Path, timeout: float = 10.0, **extra):
        captured = io.StringIO()
        with redirect_stdout(captured):
            rc = task_host.stop(argparse.Namespace(work_dir=str(workdir), timeout=timeout, **extra))
        return rc, captured.getvalue()

    def test_start_ok_full_receipt_and_confirmed_stop(self) -> None:
        workdir = self.tmp / "宿主 空格" / "wd-ok"
        rc, out = self._start(workdir, "ok")
        self.assertEqual(rc, 0, out)
        receipt = json.loads(out)
        self.assertEqual(receipt["task_id"], "lifecycle-task")
        self.assertEqual(receipt["protocol_version"], "task-host/1.0")
        self.assertTrue(receipt.get("launcher_generation"))
        self.assertEqual(receipt["addon_sha256"], hashlib.sha256(
            (self.addon_root / "_impl/houdini_bridge_addon.py").read_bytes()).hexdigest())
        self.assertEqual(receipt["task_host_identity"]["pid"], receipt["pid"])
        self.assertTrue(task_host._pid_alive(receipt["pid"]))
        rc, out = self._stop(workdir, timeout=10.0)
        self.assertEqual(rc, 0, out)
        result = json.loads(out)
        self.assertTrue(result["confirmed_exit"])
        self.assertTrue(result["heavy_slot_released"])
        from dcc_task_runtime.owned_process import read_receipt, execution_returncode
        binding=json.loads((workdir/'supervisor-binding.json').read_text())
        stopped=read_receipt(binding['directory'],'stopped',identity=binding['identity'])
        self.assertEqual(execution_returncode(stopped),0)

    def test_concurrent_start_cannot_double_start(self) -> None:
        workdir = self.tmp / "wd-race"
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(
            str(ROOT / "packages" / package / "src")
            for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline")))
        command = "import argparse,json,sys;from houdini_bridge import task_host;sys.exit(task_host.start(argparse.Namespace(**json.loads(sys.argv[1]))))"
        launchers = [subprocess.Popen([str(SOFTWARE_PYTHON), "-c", command,
            json.dumps(vars(self._args(workdir, "ok")))], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(2)]
        results = []
        for launcher in launchers:
            try:
                output, errors = launcher.communicate(timeout=30)
            finally:
                if launcher.poll() is None:
                    launcher.kill()
                    launcher.communicate()
            self.assertEqual(errors, "")
            results.append((launcher.returncode, output))
        codes = sorted(rc for rc, _ in results)
        self.assertEqual(codes[0], 0, results)
        self.assertEqual(codes[1], 5, "the loser must refuse with ACTIVE_OWNER, results=%r" % (results,))
        rc, out = self._stop(workdir, timeout=10.0)
        self.assertEqual(rc, 0, out)

    def test_mismatched_receipt_refuses_and_reclaims(self) -> None:
        for scenario in ("dead_pid", "bad_protocol"):
            with self.subTest(scenario=scenario):
                workdir = self.tmp / "wd-{}".format(scenario)
                rc, out = self._start(workdir, scenario)
                self.assertEqual(rc, 7, out)
                payload = json.loads(out)
                self.assertEqual(payload["error"], "RECEIPT_VERIFICATION_FAILED")
                self.assertTrue(payload["problems"])
                # the launcher's own child was reclaimed
                time.sleep(0.3)
                self.assertFalse(task_host.active_owner_present(workdir))

    def test_ready_timeout_reclaims_child(self) -> None:
        workdir = self.tmp / "wd-hang"
        rc, out = self._start(workdir, "hang", ready_timeout=1.5)
        self.assertEqual(rc, 3, out)
        self.assertEqual(json.loads(out)["error"], "HOST_READY_TIMEOUT_RECLAIMED")
        time.sleep(0.3)
        self.assertFalse(task_host.active_owner_present(workdir))

    def test_host_exit_reports_nonzero(self) -> None:
        workdir = self.tmp / "wd-exit"
        rc, out = self._start(workdir, "exit", ready_timeout=10.0)
        self.assertEqual(rc, 2, out)
        result = json.loads(out)
        self.assertEqual(result["error"], "HOST_EXITED")
        self.assertEqual(result["returncode"], 7)
        self.assertTrue(Path(result["log"]).is_file())
        self.assertIn("fixture startup failure", Path(result["stderr_log"]).read_text())

    def test_stop_without_confirmed_exit_is_nonzero(self) -> None:
        workdir = self.tmp / "wd-ignore"
        rc, out = self._start(workdir, "ignore_stop")
        self.assertEqual(rc, 0, out)
        rc, out = self._stop(workdir, timeout=0.5, exit_grace=1.0)
        self.assertEqual(rc, 4, out)
        result = json.loads(out)
        self.assertFalse(result["confirmed_exit"])
        self.assertFalse(result["heavy_slot_released"], "unconfirmed stop must not claim slot release")
        self._cleanup_hosts()


class SoftwareLaunchConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.script = self.root / "软件 bootstrap.py"
        self.script.write_text(LIFECYCLE_BOOTSTRAP, encoding="utf-8")

    def _args(self, **changes):
        return argparse.Namespace(**{
            "software_launch_script": str(self.script),
            "evidence_source": "software_test", "allow_software_processes": True,
            "work_dir": str(self.root / "work"), "task_id": "argv-test",
            "addon_root": str(ROOT / "plugins/houdini"),
            "houdini_bin": str(SOFTWARE_PYTHON), "supervisor_executable": str(SOFTWARE_PYTHON),
            "max_seconds": 30, "ready_timeout": 1, "poll_seconds": .01, "warmup": False,
            **changes,
        })

    def test_script_authorization_precedes_workdir_mutation(self):
        for changes in ({"evidence_source": "real_host"}, {"allow_software_processes": False},
                        {"allow_software_processes": 1}, {"evidence_source": None}):
            with self.subTest(changes=changes), mock.patch("dcc_task_runtime.owned_process.launch") as launch:
                with self.assertRaisesRegex(ValueError, "NOT_AUTHORIZED"):
                    task_host.start(self._args(**changes))
                launch.assert_not_called()
                self.assertFalse((self.root / "work").exists())

    def test_script_file_and_digest_are_checked(self):
        digest = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.assertEqual(task_host._software_launch_script(
            self._args(software_launch_script_sha256=digest)), self.script)
        self.script.write_text(LIFECYCLE_BOOTSTRAP + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SCRIPT_CHANGED"):
            task_host.start(self._args(software_launch_script_sha256=digest))
        for path in (None, "", "relative.py", str(self.root), str(self.root / "missing.py")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "SCRIPT_INVALID"):
                task_host.start(self._args(software_launch_script=path))
        with mock.patch.object(Path, "is_symlink", lambda path: path == self.script):
            with self.assertRaisesRegex(ValueError, "SCRIPT_INVALID"):
                task_host.start(self._args())

    def test_launcher_argv_has_only_the_authorized_script_prefix(self):
        for software in (True, False):
            with self.subTest(software=software):
                args = self._args()
                if not software:
                    del args.software_launch_script
                    args.evidence_source = "real_host"
                    args.allow_software_processes = False
                work = Path(args.work_dir)
                work.mkdir(exist_ok=True)
                process = mock.Mock(pid=123, returncode=7)
                process.poll.return_value = 7
                with mock.patch("dcc_task_runtime.owned_process.launch", return_value=process) as launch:
                    with redirect_stdout(io.StringIO()):
                        result = task_host._start_locked(args, work, work / "host.ready", work / "host.stop")
                self.assertEqual(result, 2)
                expected = [str(SOFTWARE_PYTHON)]
                if software:
                    expected.append(str(self.script))
                expected.append(str(work / "task_host_runner.py"))
                self.assertEqual(launch.call_args.args[0], expected)
                self.assertEqual(launch.call_args.kwargs["supervisor_executable"], str(SOFTWARE_PYTHON))
                task_host._ACTIVE_CHILDREN.pop(process.pid, None)

    def test_bootstrap_preserves_windows_runner_paths_without_regex(self):
        import ast
        stop = r"C:\测试 空格\host.stop"
        ready = r"C:\测试 空格\host.ready"
        runner = task_host.RUNNER_TEMPLATE.format(addon_libs=r"C:\Bridge\plugins\houdini\python3.11libs",
            task_id="测试任务", stop_file=stop, ready_file=ready, poll_seconds=.01,
            max_seconds=30, warmup=False, launch_nonce="test-nonce")
        tree = ast.parse(runner)
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "task_host_serve")
        params = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        self.assertEqual(params["stop_file"], stop)
        self.assertEqual(params["ready_file"], ready)
        compile(LIFECYCLE_BOOTSTRAP, "software-lifecycle-bootstrap.py", "exec")


if __name__ == "__main__":
    unittest.main()
