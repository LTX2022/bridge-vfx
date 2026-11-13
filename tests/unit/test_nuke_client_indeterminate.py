"""Real client/handler protocol with only native API and byte transport replaced."""
from contextlib import contextmanager, nullcontext
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nuke_bridge import client as client_module
from test_nuke_bridge_addon_runtime import load_addon
from test_nuke_node_observation import Format, Knob, Node
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary


class NukeClientIndeterminateTests(unittest.TestCase):
    def setUp(self):
        self.addon = load_addon()
        self.node = Node("Read1", "Read")
        self.identity = {"task_id": "owner-A", "session_id": "session", "launch_nonce": "nonce", "pid": 123,
                         "process_generation": "generation", "plugin_build": "a" * 64,
                         "scene_epoch": 0, "version": "17.0v1"}
        self.requests = []

    @contextmanager
    def transport(self, *, tokens=()):
        class Listener:
            def __init__(self, address, handler): self.handler = handler
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        server = self.addon.NukeBridgeServer(token="t" * 32)
        requests = self.requests
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def sendall(self, payload):
                self.payload = payload
                requests.append(json.loads(payload))
            def makefile(self, mode):
                listener = server._server
                handler = listener.handler.__new__(listener.handler)
                handler.rfile, handler.wfile = io.BytesIO(self.payload), io.BytesIO()
                handler.handle()
                return io.BytesIO(handler.wfile.getvalue())
        nuke = SimpleNamespace(Format=Format, toNode=lambda name: self.node if name == "Read1" else None,
                               Undo=lambda label: nullcontext(), NUKE_VERSION_STRING="17.0v1", GUI=False)
        with patch.dict(sys.modules, {"nuke": nuke}), \
                patch.object(self.addon, "_TASK_HOST_IDENTITY", self.identity), \
                patch.object(self.addon.socketserver, "ThreadingTCPServer", Listener), \
                patch.object(server, "_write_manifest"), \
                patch.object(self.addon, "_run_main", side_effect=lambda cb: cb()), \
                patch.object(client_module, "bridge_tokens_for_port", return_value=tokens), \
                patch.object(client_module.socket, "create_connection", side_effect=lambda *args, **kwargs: Connection()):
            server.start()
            try: yield server
            finally: server.stop()

    def test_completed_native_mutation_keeps_unknown_result_through_controlled_boundary(self):
        mutations = []
        class FormatKnob(Knob):
            def setValue(self, value):
                mutations.append(value)
                self.current = Format()
        self.node._knobs["format"] = FormatKnob(Format())
        with self.transport(), tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            transport = client_module.NukeClient(59555, token="t" * 32)
            boundary = _ConfiguredBoundary(kind="nuke", transport=transport, config={
                "expected_identity": self.identity, "evidence_source": "software_test", "application": "nuke",
                "version": "17.0v1", "plugin_build": "a" * 64, "transport": "tcp", "host": "127.0.0.1",
                "port": 59555, "task_root": str(root), "executable": "/not-started/Nuke"}, state_dir=root)
            boundary.bind_task("owner-A")
            with self.assertRaises(client_module.NukeConnectionError) as caught:
                boundary.call("set_knob", {"node": "Read1", "knob": "format", "value": "new-native-format"})
            self.assertEqual(caught.exception.code, "COMMAND_FAILED")
            self.assertIs(caught.exception.indeterminate, True)
            self.assertEqual(mutations, ["new-native-format"])
            self.assertEqual(sum(request["command"] == "set_knob" for request in self.requests), 1)
            self.assertEqual(boundary.call("get_node", {"name": "Read1"})["knobs"]["format"]["native_type"], "nuke.Format")
            self.assertEqual(transport.health()["nuke_version"], "17.0v1")
            self.assertEqual(mutations, ["new-native-format"])

    def test_declared_unknown_auth_error_never_refreshes_token_or_replays(self):
        with self.transport(tokens=("t" * 32,)) as server:
            client = client_module.NukeClient(59555, token="x" * 32)
            response = {"status": "error", "error": {"code": "AUTH_REQUIRED", "message": "uncertain", "indeterminate": True}}
            with patch.object(server, "_authorize_request", return_value=response), \
                    self.assertRaises(client_module.NukeConnectionError) as caught:
                client.health()
            self.assertEqual(caught.exception.code, "AUTH_REQUIRED")
            self.assertIs(caught.exception.indeterminate, True)
            self.assertEqual(len(self.requests), 1)

    def test_malformed_indeterminate_is_rejected_as_unknown_without_auth_retry(self):
        with self.transport(tokens=("t" * 32,)) as server:
            for invalid in (None, 0, 1, "false", [], {}):
                self.requests.clear()
                client = client_module.NukeClient(59555, token="x" * 32)
                response = {"status": "error", "error": {"code": "AUTH_REQUIRED", "message": "invalid flag", "indeterminate": invalid}}
                with self.subTest(invalid=invalid), patch.object(server, "_authorize_request", return_value=response), \
                        self.assertRaises(client_module.NukeConnectionError) as caught:
                    client.health()
                self.assertEqual(caught.exception.code, "INVALID_RESPONSE")
                self.assertIs(caught.exception.indeterminate, True)
                self.assertEqual(len(self.requests), 1)

    def test_definite_auth_rejection_keeps_existing_safe_token_refresh(self):
        with self.transport(tokens=("t" * 32,)):
            client = client_module.NukeClient(59555, token="x" * 32)
            self.assertEqual(client.health()["nuke_version"], "17.0v1")
            self.assertEqual(len(self.requests), 2)
            self.assertEqual(client.token, "t" * 32)

    def test_nonobject_error_payload_cannot_become_a_definite_failure(self):
        with self.transport() as server:
            for invalid in (None, [], "", False, 0):
                client = client_module.NukeClient(59555, token="t" * 32)
                response = {"status": "error", "error": invalid}
                with self.subTest(invalid=invalid), patch.object(server, "_authorize_request", return_value=response), \
                        self.assertRaises(client_module.NukeConnectionError) as caught:
                    client.health()
                self.assertEqual(caught.exception.code, "INVALID_RESPONSE")
                self.assertIs(caught.exception.indeterminate, True)

    def test_ordinary_command_error_preserves_code_and_definite_false(self):
        self.node._knobs["unknown"] = Knob(object())
        with self.transport():
            client = client_module.NukeClient(59555, token="t" * 32)
            with self.assertRaises(client_module.NukeConnectionError) as caught:
                client.call("get_node", {"name": "Read1"})
            self.assertEqual(caught.exception.code, "COMMAND_FAILED")
            self.assertIs(caught.exception.indeterminate, False)
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(client.health()["nuke_version"], "17.0v1")


if __name__ == "__main__":
    unittest.main()
