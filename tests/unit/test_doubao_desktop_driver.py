from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from dcc_task_runtime.doubao_desktop import (
    BUNDLE_ID,
    SCHEMA,
    DesktopErrorCode,
    DoubaoDesktopAXDriver,
    DoubaoDesktopError,
    SyntheticOutboundAuthorization,
    SyntheticPrompt,
    resolve_app_path,
)


APP_PATH = str(Path(__file__).resolve().parent / "synthetic-applications" / "Doubao.app" / "Contents" / "MacOS" / "Doubao")
FINGERPRINT = "a" * 64


def _fixture_source(log_path: Path, *, response: str = '{"tool":null,"arguments":{},"reason":"fixture"}', pending: bool = False, missing: str = "") -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env python3
        import json, sys
        LOG = {str(log_path)!r}
        SCHEMA = {SCHEMA!r}
        APP = {APP_PATH!r}
        FINGERPRINT = {FINGERPRINT!r}
        RESPONSE = {response!r}
        PENDING = {pending!r}
        MISSING = {missing!r}
        args = sys.argv[1:]
        with open(LOG, "a", encoding="utf-8") as handle:
            json.dump(args, handle)
            handle.write("\\n")
        def controls(session):
            value = {{"available": True, "role": "AXStaticText", "identifier": "fixture", "title": "fixture", "enabled": True, "candidate_count": 1}}
            result = {{
                "composer": {{"available": MISSING != "composer", "role": "AXTextArea", "identifier": "composer", "title": "", "enabled": True, "candidate_count": 1}},
                "response": {{"available": MISSING != "response", **value}},
                "new_task": {{"available": MISSING != "new_task", "role": "AXButton", "identifier": "new", "title": "New Chat", "enabled": True, "candidate_count": 1}},
            }}
            return {{"app_path": APP, "bundle_id": {BUNDLE_ID!r}, "app_version": "fixture", "pid": 4242, "session_id": session, "code_signature": "fixture", "executable_sha256": "b" * 64, "fingerprint": FINGERPRINT, "controls": result}}
        def option(name):
            try: return args[args.index(name) + 1]
            except (ValueError, IndexError): return ""
        operation = option("--operation")
        session = option("--session-id")
        if operation in ("snapshot", "probe"):
            result = controls(session)
        elif operation == "new_task":
            result = {{"session_id": session, "snapshot": controls(session)}}
        elif operation == "send_synthetic":
            result = {{"session_id": session, "accepted": True, "snapshot": controls(session)}}
        elif operation == "read_response":
            result = {{"session_id": session, "status": "pending" if PENDING else "ready", "complete": False if PENDING else True}}
            if not PENDING: result.update({{"text": RESPONSE, "snapshot": controls(session)}})
        else:
            print(json.dumps({{"schema": SCHEMA, "ok": False, "code": "INVALID_REQUEST", "message": "fixture"}}))
            raise SystemExit(1)
        print(json.dumps({{"schema": SCHEMA, "ok": True, "operation": operation, "result": result}}))
        """
    ).lstrip()


class DoubaoDesktopDriverTests(unittest.TestCase):
    def fixture(self, *, response: str = '{"tool":null,"arguments":{},"reason":"fixture"}', pending: bool = False, missing: str = ""):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        log = root / "argv.jsonl"
        helper = root / "doubao_ax_helper.py"
        helper.write_text(_fixture_source(log, response=response, pending=pending, missing=missing), encoding="utf-8")
        helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
        self.addCleanup(directory.cleanup)
        run = subprocess.run

        def run_fixture(argv, **kwargs):
            self.assertEqual(argv[0], str(helper))
            return run([sys.executable, str(helper), *argv[1:]], **kwargs)

        boundary = mock.patch("dcc_task_runtime.doubao_desktop.subprocess.run", side_effect=run_fixture)
        boundary.start()
        self.addCleanup(boundary.stop)
        return helper, log

    def driver(self, helper: Path, *, authorization=None) -> DoubaoDesktopAXDriver:
        return DoubaoDesktopAXDriver(
            helper_path=helper,
            app_path=APP_PATH,
            outbound_authorization=authorization,
            call_timeout=0.5,
        )

    def test_exact_app_path_is_required(self):
        self.assertEqual(str(resolve_app_path(APP_PATH)), APP_PATH)
        with self.assertRaises(DoubaoDesktopError) as raised:
            resolve_app_path(str(Path(APP_PATH).parents[2] / "Doubao"))
        self.assertEqual(raised.exception.code, DesktopErrorCode.UI_CONTROL_UNVERIFIED.value)

    def test_snapshot_reads_typed_controls_and_identity(self):
        helper, _ = self.fixture()
        snapshot = self.driver(helper).snapshot(require_controls=True)
        self.assertEqual(snapshot.bundle_id, BUNDLE_ID)
        self.assertTrue(snapshot.controls["composer"].available)
        self.assertTrue(snapshot.controls["response"].available)
        self.assertEqual(snapshot.controls["new_task"].role, "AXButton")

    def test_missing_control_is_a_clear_unverified_failure(self):
        helper, _ = self.fixture(missing="composer")
        with self.assertRaises(DoubaoDesktopError) as raised:
            self.driver(helper).snapshot(require_controls=True)
        self.assertEqual(raised.exception.code, DesktopErrorCode.UI_CONTROL_UNVERIFIED.value)
        self.assertIn("composer", raised.exception.details["missing_controls"])

    def test_permission_error_from_helper_is_preserved(self):
        helper, _ = self.fixture()
        error_json = json.dumps({"schema": SCHEMA, "ok": False, "code": "AX_PERMISSION_REQUIRED", "message": "permission required", "details": {"permission_target": "/private/tmp/doubao_ax_helper", "permission_scope": "Accessibility"}})
        completed = mock.Mock(returncode=1, stdout=(error_json + "\n").encode())
        with mock.patch("dcc_task_runtime.doubao_desktop.subprocess.run", return_value=completed):
            with self.assertRaises(DoubaoDesktopError) as raised:
                self.driver(helper).snapshot()
        self.assertEqual(raised.exception.code, DesktopErrorCode.AX_PERMISSION_REQUIRED.value)
        self.assertEqual(raised.exception.details["permission_scope"], "Accessibility")
        self.assertEqual(raised.exception.details["permission_target"], "/private/tmp/doubao_ax_helper")

    def test_new_task_send_and_bounded_read_form_one_session(self):
        helper, log = self.fixture(response='{"tool":"scene.inspect","arguments":{},"reason":"fixture"}')
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        session = driver.new_task_session()
        self.assertRegex(session, r"^[0-9a-f]{32}$")
        accepted = driver.send_synthetic(SyntheticPrompt("synthetic prompt card", authorization))
        self.assertTrue(accepted["accepted"])
        response = driver.wait_for_response(timeout_seconds=2, poll_seconds=0.01)
        self.assertEqual(response.session_id, session)
        self.assertEqual(json.loads(response.text)["tool"], "scene.inspect")
        invocations = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(invocations), 6)
        self.assertTrue(all("--app-path" in invocation for invocation in invocations))
        self.assertTrue(all("--coordinate" not in invocation and "--script" not in invocation for invocation in invocations))
        session_args = [invocation[invocation.index("--session-id") + 1] for invocation in invocations if "--session-id" in invocation]
        self.assertTrue(session_args)
        self.assertTrue(all(value == session for value in session_args))
        send = next(invocation for invocation in invocations if "send_synthetic" in invocation)
        self.assertIn("--input-class", send)
        self.assertEqual(send[send.index("--input-class") + 1], "synthetic")

    def test_duplicate_send_is_rejected_without_a_second_ui_submission(self):
        helper, log = self.fixture()
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        driver.new_task_session()
        prompt = SyntheticPrompt("one prompt", authorization)
        driver.send_synthetic(prompt)
        before = log.read_text(encoding="utf-8").count("send_synthetic")
        with self.assertRaises(DoubaoDesktopError) as raised:
            driver.send_synthetic(prompt)
        self.assertEqual(raised.exception.code, DesktopErrorCode.INVALID_REQUEST.value)
        self.assertEqual(log.read_text(encoding="utf-8").count("send_synthetic"), before)

    def test_completed_response_is_cached_after_stable_reads(self):
        helper, log = self.fixture(response='{"tool":"scene.inspect","arguments":{},"reason":"fixture"}')
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        driver.new_task_session()
        driver.send_synthetic(SyntheticPrompt("one prompt", authorization))
        response = driver.wait_for_response(timeout_seconds=2, poll_seconds=0.01)
        read_count = log.read_text(encoding="utf-8").count("read_response")
        self.assertGreaterEqual(read_count, 2)
        self.assertIs(driver.wait_for_response(timeout_seconds=0.01), response)
        self.assertEqual(log.read_text(encoding="utf-8").count("read_response"), read_count)

    def test_exchange_requires_typed_synthetic_authorization(self):
        helper, _ = self.fixture()
        driver = self.driver(helper)
        with self.assertRaises(DoubaoDesktopError) as raised:
            driver.exchange({"context": {}})
        self.assertEqual(raised.exception.code, DesktopErrorCode.PRIVACY_DENIED.value)

    def test_invalid_outbound_scope_is_rejected(self):
        with self.assertRaises(DoubaoDesktopError) as raised:
            SyntheticOutboundAuthorization(input_class="private")
        self.assertEqual(raised.exception.code, DesktopErrorCode.PRIVACY_DENIED.value)
        authorization = SyntheticOutboundAuthorization.benchmark()
        with self.assertRaises(DoubaoDesktopError):
            SyntheticPrompt("x", authorization=None)  # type: ignore[arg-type]

    def test_pending_read_times_out_without_claiming_a_response(self):
        helper, _ = self.fixture(pending=True)
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        driver.new_task_session()
        driver.send_synthetic(SyntheticPrompt("pending prompt", authorization))
        with self.assertRaises(DoubaoDesktopError) as raised:
            driver.wait_for_response(timeout_seconds=0.05, poll_seconds=0.01)
        self.assertEqual(raised.exception.code, DesktopErrorCode.TIMEOUT.value)
        self.assertFalse(raised.exception.indeterminate)

    def test_prompt_echo_is_not_accepted_as_a_response(self):
        helper, _ = self.fixture(response="pending prompt")
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        driver.new_task_session()
        driver.send_synthetic(SyntheticPrompt("pending prompt", authorization))
        with self.assertRaises(DoubaoDesktopError) as raised:
            driver.wait_for_response(timeout_seconds=0.05, poll_seconds=0.01)
        self.assertEqual(raised.exception.code, DesktopErrorCode.TIMEOUT.value)

    def test_bootstrap_sets_strict_json_only_after_matching_response(self):
        helper, _ = self.fixture(response='{"bridge_probe":"doubao_ax_v1","ok":true}')
        authorization = SyntheticOutboundAuthorization.benchmark()
        driver = self.driver(helper, authorization=authorization)
        probe = driver.bootstrap(timeout_seconds=2)
        self.assertTrue(probe["strict_json_verified"])
        self.assertTrue(probe["isolated_session_verified"])
        self.assertEqual(probe["session_id"], driver.session_id)

    def test_capabilities_report_missing_media_transport(self):
        helper, _ = self.fixture()
        capabilities = self.driver(helper).capabilities()
        self.assertFalse(capabilities["attachments"])
        self.assertFalse(capabilities["image_input"])
        self.assertFalse(capabilities["vision_upload"])

    def test_subprocess_invocation_is_argv_only_and_bounded(self):
        helper, _ = self.fixture()
        payload = {"app_path": APP_PATH, "bundle_id": BUNDLE_ID, "app_version": "x", "pid": 1, "fingerprint": FINGERPRINT, "controls": {kind: {"available": True, "candidate_count": 1} for kind in ("composer", "response", "new_task")}}
        completed = mock.Mock(returncode=0, stdout=json.dumps({"schema": SCHEMA, "ok": True, "result": payload}).encode())
        with mock.patch("dcc_task_runtime.doubao_desktop.subprocess.run", return_value=completed) as run:
            self.driver(helper).snapshot()
        argv = run.call_args.args[0]
        self.assertIsInstance(argv, list)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertFalse(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 0.5)
        self.assertEqual(argv[0], str(helper))
        self.assertEqual(argv[argv.index("--app-path") + 1], APP_PATH)
        self.assertNotIn("--script", argv)
        self.assertNotIn("--coordinate", argv)


if __name__ == "__main__":
    unittest.main()
