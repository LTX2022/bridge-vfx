from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "validate_doubao_desktop.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("_doubao_probe", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class DoubaoProbeTests(unittest.TestCase):
    def test_duplicate_app_identity_and_missing_events_fail_closed(self):
        tool = load_tool()
        with mock.patch.object(tool, "installed_routes", return_value=[{"app_version": "1"}, {"app_version": "2"}]):
            result = tool.report()
        self.assertEqual(result["status"], "DOUBAO_CONTROL_UNVERIFIED")
        self.assertFalse(result["gates"][0]["passed"])

    def test_five_cycle_synthetic_isolated_manifest_can_pass_preflight(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            events = [
                {"event_id": f"read-{index}", "session_id": "test-session", "kind": "read_cycle", "cycle": index, "read_succeeded": True}
                for index in range(1, 6)
            ] + [
                {"event_id": f"observe-{subject}", "session_id": "test-session", "kind": "observation", "subject": subject, "observed": True}
                for subject in ("composer", "image_entry", "model_label")
            ] + [{"event_id": "privacy", "session_id": "test-session", "kind": "privacy", "input_class": "synthetic", "existing_conversation_accessed": False}]
            path.write_text(json.dumps({
                "schema": "bridge.doubao_ui_events/2.0",
                "route_id": "DoubaoDesktopRoute",
                "isolated_session_id": "test-session",
                "route_identity": {"route_id": "DoubaoDesktopRoute", "bundle_id": "com.bot.pc.doubao", "app_version": "2.27.10", "executable_path": "/x/Doubao", "executable_sha256": "a" * 64, "driver_sha256": "b" * 64},
                "events": events,
            }), encoding="utf-8")
            with mock.patch.object(tool, "installed_routes", return_value=[{"bundle_id": "com.bot.pc.doubao", "app_version": "2.27.10", "executable_path": "/x/Doubao", "executable_sha256": "a" * 64}]):
                result = tool.report(path)
        self.assertTrue(result["gates"][0]["passed"])
        self.assertFalse(result["support_promotion"])

    def test_outer_true_summaries_cannot_hide_failed_atomic_event(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            events = [
                {"event_id": f"read-{index}", "session_id": "s", "kind": "read_cycle", "cycle": index, "read_succeeded": index != 3}
                for index in range(1, 6)
            ] + [
                {"event_id": f"o-{subject}", "session_id": "s", "kind": "observation", "subject": subject, "observed": True}
                for subject in ("composer", "image_entry", "model_label")
            ] + [{"event_id": "p", "session_id": "s", "kind": "privacy", "input_class": "synthetic", "existing_conversation_accessed": False}]
            path.write_text(json.dumps({
                "schema": "bridge.doubao_ui_events/2.0", "route_id": "DoubaoDesktopRoute",
                "isolated_session_id": "s", "route_identity": {"route_id": "DoubaoDesktopRoute", "bundle_id": "com.bot.pc.doubao", "app_version": "2.27.10", "executable_path": "/x/Doubao", "executable_sha256": "a" * 64, "driver_sha256": "b" * 64}, "events": events,
                "read_cycles": [True] * 5, "passed": True, "composer_verified": True,
            }), encoding="utf-8")
            with mock.patch.object(tool, "installed_routes", return_value=[{"bundle_id": "com.bot.pc.doubao", "app_version": "2.27.10", "executable_path": "/x/Doubao", "executable_sha256": "a" * 64}]):
                result = tool.report(path)
        self.assertFalse(result["gates"][0]["passed"])
        self.assertIn("five_successful_cycles_required", result["ui_event_manifest"]["errors"])


if __name__ == "__main__":
    unittest.main()
