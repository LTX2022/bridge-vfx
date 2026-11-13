from __future__ import annotations

from contextlib import nullcontext

import importlib.util
import io
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_nuke_runtime_addon", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Nuke bridge addon")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MainThreadDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = load_addon()

    def test_connect_nodes_disconnects_only_explicit_none_and_preserves_string_source(self) -> None:
        class Node:
            def __init__(self, name, inputs=()):
                self._name = name
                self.inputs = list(inputs)

            def name(self):
                return self._name

            def setInput(self, index, source):
                self.inputs[index] = source

        first = Node("Read1")
        second = Node("Read2")
        destination = Node("Write1", [first, second])
        nodes = {node.name(): node for node in (first, second, destination, Node("None"))}
        fake_nuke = SimpleNamespace(toNode=nodes.get, Undo=lambda _label: nullcontext())
        with mock.patch.dict(sys.modules, {"nuke": fake_nuke}):
            result = self.addon.dispatch("connect_nodes", {"dst": "Write1", "src": None, "input_index": 1})
            self.assertEqual(result, {"src": None, "dst": "Write1", "input_index": 1})
            self.assertEqual(destination.inputs, [first, None])
            result = self.addon.dispatch("connect_nodes", {"dst": "Write1", "src": "Read2", "input_index": 1})
            self.assertEqual(result, {"src": "Read2", "dst": "Write1", "input_index": 1})
            self.assertEqual(destination.inputs, [first, second])
            for params in ({"dst": "Write1"}, {"dst": "Write1", "src": "missing"},
                           {"dst": "missing", "src": None}):
                with self.subTest(params=params), self.assertRaisesRegex(ValueError, "requires src|node not found"):
                    self.addon.dispatch("connect_nodes", params)
                self.assertEqual(destination.inputs, [first, second])

    def test_captured_none_is_a_valid_completed_result(self) -> None:
        fake_nuke = SimpleNamespace(
            executeInMainThreadWithResult=lambda callback: (callback(), None)[1]
        )
        with mock.patch.dict(sys.modules, {"nuke": fake_nuke}):
            self.assertIsNone(self.addon._run_main(lambda: None))

    def test_pending_callback_is_cancelled_after_timeout(self) -> None:
        queued: list[object] = []
        calls: list[str] = []

        def executor(callback):
            queued.append(callback)
            return None

        fake_nuke = SimpleNamespace(executeInMainThreadWithResult=executor)
        with mock.patch.dict(sys.modules, {"nuke": fake_nuke}):
            with mock.patch.object(self.addon, "_MAIN_THREAD_TIMEOUT_SECONDS", 0.01):
                with self.assertRaises(self.addon._MainThreadTimeoutError) as caught:
                    self.addon._run_main(lambda: calls.append("late"))

        self.assertFalse(caught.exception.indeterminate)
        self.assertEqual(len(queued), 1)
        self.assertIsNone(queued[0]())
        self.assertEqual(calls, [])

    def test_running_callback_timeout_is_indeterminate(self) -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls: list[str] = []
        worker: list[threading.Thread] = []

        def callback():
            started.set()
            release.wait(timeout=1.0)
            calls.append("ran")
            finished.set()
            return {"ok": True}

        def executor(callback):
            thread = threading.Thread(target=callback, daemon=True)
            worker.append(thread)
            thread.start()
            if not started.wait(timeout=1.0):
                raise AssertionError("fake main-thread callback did not start")
            return None

        fake_nuke = SimpleNamespace(executeInMainThreadWithResult=executor)
        with mock.patch.dict(sys.modules, {"nuke": fake_nuke}):
            with mock.patch.object(self.addon, "_MAIN_THREAD_TIMEOUT_SECONDS", 0.01):
                with self.assertRaises(self.addon._MainThreadTimeoutError) as caught:
                    self.addon._run_main(callback)

        self.assertTrue(caught.exception.indeterminate)
        release.set()
        self.assertTrue(finished.wait(timeout=1.0))
        worker[0].join(timeout=1.0)
        self.assertEqual(calls, ["ran"])


class RequestLineLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = load_addon()

    def test_readline_is_called_with_one_byte_of_headroom(self) -> None:
        class TrackingStream:
            def __init__(self) -> None:
                self.requested_size = None

            def readline(self, size):
                self.requested_size = size
                return b"{}\n"

        stream = TrackingStream()
        self.assertEqual(self.addon._read_request_line(stream, max_bytes=8), b"{}\n")
        self.assertEqual(stream.requested_size, 9)

    def test_oversized_request_is_rejected(self) -> None:
        with self.assertRaises(self.addon._RequestLineError) as caught:
            self.addon._read_request_line(io.BytesIO(b"123456\n"), max_bytes=5)
        self.assertEqual(caught.exception.code, "REQUEST_TOO_LARGE")

    def test_unterminated_request_is_rejected(self) -> None:
        with self.assertRaises(self.addon._RequestLineError) as caught:
            self.addon._read_request_line(io.BytesIO(b"{}"), max_bytes=8)
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
