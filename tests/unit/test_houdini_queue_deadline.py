"""Expired queued requests must never mutate the DCC on a later UI tick."""
import unittest
from unittest.mock import patch
from test_houdini_http_security import _load, ADDON


class HoudiniQueueDeadlineTests(unittest.TestCase):
    def test_timeout_before_dispatch_cancels_late_callback(self):
        addon = _load("_houdini_deadline_test", ADDON)
        server = addon.HoudiniBridgeServer(allowed_commands={"node.create"})
        original = addon._Request
        class ExpiredRequest(original):
            def __init__(self, command, params):
                super().__init__(command, params)
                self.done.wait = lambda timeout: False
        with patch.object(addon, "_Request", ExpiredRequest):
            response = server._submit("node.create", {})
        self.assertFalse(response["error"]["indeterminate"])
        with patch.object(addon, "dispatch", side_effect=AssertionError("late mutation")):
            server.pump()

    def test_running_timeout_does_not_claim_cancellation(self):
        addon = _load("_houdini_running_deadline_test", ADDON)
        server = addon.HoudiniBridgeServer(allowed_commands={"node.create"})
        original = addon._Request
        class RunningRequest(original):
            def __init__(self, command, params):
                super().__init__(command, params)
                self.state = "RUNNING"
                self.done.wait = lambda timeout: False
        with patch.object(addon, "_Request", RunningRequest):
            response = server._submit("node.create", {})
        self.assertTrue(response["error"]["indeterminate"])
        self.assertEqual(response["error"]["operation_state"], "RUNNING")
