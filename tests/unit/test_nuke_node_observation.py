"""Exercise native knob shapes through the shipped dispatch and binding code."""
from contextlib import contextmanager, nullcontext
import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_nuke_bridge_addon_runtime import load_addon
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary


class Format:
    """Nuke 17 Format API, including a non-zero image origin."""
    def name(self): return "native-format"
    def width(self): return 128
    def height(self): return 64
    def x(self): return -4
    def y(self): return 2
    def r(self): return 124
    def t(self): return 66
    def pixelAspect(self): return 1.25


class Knob:
    def __init__(self, value): self.current = value
    def value(self): return self.current
    def setValue(self, value): self.current = value


class Node:
    def __init__(self, name, kind):
        self._name, self.kind = name, kind
        self._knobs = {"file": Knob("/old/" + name + ".exr"), "colorspace": Knob("linear"),
                       "raw": Knob(True), "format": Knob(Format()),
                       "proxy_format": Knob(Format()), "vector": Knob((1.0, 2.0))}
        if kind == "Write": self._knobs["premultiplied"] = Knob(True)
        self._inputs = []
        self.fail_connect_once = False
    def name(self): return self._name
    def Class(self): return self.kind
    def knobs(self): return self._knobs
    def knob(self, name): return self._knobs.get(name)
    def inputs(self): return len(self._inputs)
    def input(self, index): return self._inputs[index]
    def setInput(self, index, source):
        while len(self._inputs) <= index: self._inputs.append(None)
        self._inputs[index] = source
        if self.fail_connect_once:
            self.fail_connect_once = False
            raise RuntimeError("native connection failed after changing its input")


class NukeNodeObservationTests(unittest.TestCase):
    def setUp(self):
        self.addon = load_addon()
        self.nodes = {name: Node(name, kind) for name, kind in
                      (("Read1", "Read"), ("Write1", "Write"), ("ReadOld", "Read"))}
        self.nuke = SimpleNamespace(Format=Format, toNode=self.nodes.get,
                                    Undo=lambda label: nullcontext(), NUKE_VERSION_STRING="17.0v1", GUI=False)
        self.native = patch.dict(sys.modules, {"nuke": self.nuke})
        self.native.start()
        self.addCleanup(self.native.stop)

    def test_read_write_format_is_explicit_and_binding_knob_types_are_preserved(self):
        for name in ("Read1", "Write1"):
            result = self.addon.dispatch("get_node", {"name": name})
            decoded = json.loads(json.dumps(result, allow_nan=False))
            knobs = decoded["knobs"]
            self.assertEqual(knobs["format"], {"native_type": "nuke.Format", "name": "native-format",
                "width": 128, "height": 64, "x": -4, "y": 2, "r": 124, "t": 66, "pixelAspect": 1.25})
            self.assertEqual(knobs["proxy_format"], knobs["format"])
            self.assertIs(type(knobs["file"]), str)
            self.assertIs(type(knobs["colorspace"]), str)
            self.assertIs(type(knobs["raw"]), bool)
            self.assertEqual(knobs["vector"], [1.0, 2.0])
            if name == "Write1": self.assertIs(type(knobs["premultiplied"]), bool)

    def test_unknown_malformed_nonfinite_and_unbounded_values_are_rejected(self):
        class Unknown:
            def __str__(self): raise AssertionError("unknown objects must never be stringified")
        class BadFormat(Format):
            def width(self): return 128.0
        cycle = []; cycle.append(cycle)
        cases = ((Unknown(), "TYPE_UNSUPPORTED"), (BadFormat(), "FORMAT_TYPE_INVALID"),
                 (float("nan"), "NONFINITE"), ("x" * 65537, "TOO_LARGE"),
                 (list(range(1025)), "TOO_LARGE"), (cycle, "TOO_LARGE"), ({1: "bad"}, "DICTIONARY_INVALID"))
        for value, message in cases:
            self.nodes["Read1"]._knobs["unsupported"] = Knob(value)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.addon.dispatch("get_node", {"name": "Read1"})

    def test_unnamed_format_preserves_null_name_without_string_coercion(self):
        class UnnamedFormat(Format):
            def name(self): return None
        self.nodes["Read1"]._knobs["format"] = Knob(UnnamedFormat())
        result = self.addon.dispatch("get_node", {"name": "Read1"})
        self.assertIsNone(result["knobs"]["format"]["name"])
        self.assertIsNone(json.loads(json.dumps(result))["knobs"]["format"]["name"])

    @contextmanager
    def server(self):
        class Listener:
            def __init__(self, address, handler): self.handler = handler
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        server = self.addon.NukeBridgeServer(token="t" * 32)
        with patch.object(self.addon.socketserver, "ThreadingTCPServer", Listener), \
                patch.object(server, "_write_manifest"), patch.object(self.addon, "_run_main", side_effect=lambda cb: cb()):
            server.start()
            try: yield server._server
            finally: server.stop()

    def request(self, listener, command, params=None):
        handler = listener.handler.__new__(listener.handler)
        handler.rfile = io.BytesIO((json.dumps({"token": "t" * 32, "command": command, "params": params or {}}) + "\n").encode())
        handler.wfile = io.BytesIO()
        handler.handle()
        return json.loads(handler.wfile.getvalue())

    def test_service_get_node_handles_format_unknown_failure_and_remains_available(self):
        with self.server() as address:
            response = self.request(address, "get_node", {"name": "Read1"})
            self.assertEqual(response["status"], "success")
            self.assertEqual(response["data"]["knobs"]["format"]["native_type"], "nuke.Format")
            self.nodes["Read1"]._knobs["unknown"] = Knob(object())
            failed = self.request(address, "get_node", {"name": "Read1"})
            self.assertEqual(failed["error"]["code"], "COMMAND_FAILED")
            self.assertIn("TYPE_UNSUPPORTED", failed["error"]["message"])
            self.assertEqual(self.request(address, "nuke_ping")["status"], "success")
            del self.nodes["Read1"]._knobs["unknown"]
            self.assertEqual(self.request(address, "get_node", {"name": "Write1"})["status"], "success")

    def test_service_response_encoding_failure_is_structured_and_indeterminate(self):
        original = self.addon.dispatch
        def dispatch(command, params):
            return {"native": object()} if command == "unencodable" else original(command, params)
        with patch.object(self.addon, "dispatch", side_effect=dispatch), self.server() as address:
            failed = self.request(address, "unencodable")
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["error"]["code"], "COMMAND_FAILED")
            self.assertIs(failed["error"]["indeterminate"], True)
            self.assertEqual(self.request(address, "nuke_ping")["status"], "success")
        for value in (float("nan"), "\ud800"):
            failed = json.loads(self.addon._response_line(self.addon._success(value)))
            self.assertEqual(failed["error"]["code"], "COMMAND_FAILED")

    def boundary(self, root):
        identity = {"task_id": "owner-A", "session_id": "session", "launch_nonce": "nonce", "pid": 123,
                    "process_generation": "generation", "plugin_build": "a" * 64, "scene_epoch": 0, "version": "17.0v1"}
        addon = self.addon
        class Transport:
            def health(self): return {"task_host_identity": dict(identity)}
            def call(self, command, params): return addon.dispatch(command, params)
        client = _ConfiguredBoundary(kind="nuke", transport=Transport(), config={
            "expected_identity": identity, "evidence_source": "software_test", "application": "nuke",
            "version": "17.0v1", "plugin_build": "a" * 64, "transport": "tcp", "host": "127.0.0.1",
            "port": 54321, "task_root": str(root), "executable": "/not-started/Nuke"}, state_dir=root)
        client.bind_task("owner-A")
        return client

    def test_native_format_observation_allows_exact_render_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); client = self.boundary(root)
            artifact = {"artifact_id": "input-1", "pattern": str(root / "main.%04d.exr"),
                        "usable_as_render_input": True, "verification": {"frame_set": [1]},
                        "colorspace": "ACEScg", "premultiplied": False}
            result = client.render_binding("owner-A", str(root / "nuke.%04d.exr"), [1], "ACEScg", False,
                                           artifact_binding=artifact)
            self.assertIs(result["input_binding"]["connection_verified"], True)
            read, write = self.nodes["Read1"], self.nodes["Write1"]
            self.assertIs(write.input(0), read)
            self.assertEqual(read.knob("file").value(), artifact["pattern"])
            self.assertEqual(write.knob("file").value(), str(root / "nuke.%04d.exr"))
            self.assertIs(read.knob("raw").value(), False)
            self.assertIs(write.knob("premultiplied").value(), False)

    def test_failed_binding_restores_knob_types_values_and_original_connection(self):
        read, write, old = (self.nodes[name] for name in ("Read1", "Write1", "ReadOld"))
        write.setInput(0, old)
        write.fail_connect_once = True
        before = {node.name(): {name: node.knob(name).value() for name in ("file", "colorspace", "raw")}
                  for node in (read, write)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); client = self.boundary(root)
            artifact = {"artifact_id": "input-1", "pattern": str(root / "main.%04d.exr"),
                        "usable_as_render_input": True, "verification": {"frame_set": [1]},
                        "colorspace": "ACEScg", "premultiplied": False}
            with self.assertRaisesRegex(RuntimeError, "native connection failed"):
                client.render_binding("owner-A", str(root / "nuke.%04d.exr"), [1], "ACEScg", False,
                                      artifact_binding=artifact)
        self.assertIs(write.input(0), old)
        self.assertIs(write.knob("premultiplied").value(), True)
        for node in (read, write):
            for name, value in before[node.name()].items():
                self.assertIs(type(node.knob(name).value()), type(value))
                self.assertEqual(node.knob(name).value(), value)


if __name__ == "__main__":
    unittest.main()
