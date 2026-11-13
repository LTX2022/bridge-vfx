from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from dcc_task_runtime.exr_codec import encode_tiny_exr, read_exr
from nuke_bridge.operation_receipts import receipt_errors
from nuke_bridge.tasks import task_service
from test_nuke_task_host import FAKE


def native_nuke_api():
    api = types.ModuleType("nuke")
    exec(FAKE, api.__dict__)

    class NativeKnob(api.Knob):
        def toScript(self):
            return json.dumps(self.value(), sort_keys=True)

        def isAnimated(self):
            return False

        def hasExpression(self):
            return False

        def setVisible(self, visible):
            self.visible = visible

    class NativeNode(api.Node):
        def __init__(self, kind, name=None, inputs=(), **knobs):
            super().__init__(kind, name or f"{kind}{len(api._nodes) + 1}")
            for index, source in enumerate(inputs):
                self.setInput(index, source)
            for knob_name, value in knobs.items():
                self[knob_name].setValue(value)

        def addKnob(self, knob):
            self._knobs[knob.label] = knob

        def setXpos(self, position):
            self["xpos"].setValue(position)

        def dependencies(self, flags):
            return [source for source in self._inputs if source is not None]

        def width(self):
            return read_exr(self["file"].value(), with_pixels=False)["width"]

        def height(self):
            return read_exr(self["file"].value(), with_pixels=False)["height"]

        def channels(self):
            return read_exr(self["file"].value(), with_pixels=False)["channels"]

    def string_knob(name, label):
        knob = NativeKnob("")
        knob.label = name
        return knob

    def script_open(path):
        api._assert()
        raw = Path(path).read_text(encoding="utf-8")
        prefix, payload = raw.split("\n", 1)
        if prefix != "bridge.test_nuke_snapshot/1":
            raise ValueError("unsupported native fixture snapshot")
        snapshot = json.loads(payload)
        api._nodes.clear()
        for item in snapshot["nodes"]:
            NativeNode(item["class"], item["name"], **item["knobs"])
        for item in snapshot["nodes"]:
            node = api.toNode(item["name"])
            for index, source in enumerate(item["inputs"]):
                node.setInput(index, api.toNode(source) if source is not None else None)
        api._root_path = str(path)
        api.opened_scripts.append(str(path))
        for callback in api._callbacks:
            callback()

    def execute(write, first, last):
        api._assert()
        if write.Class() != "Write" or write.input(0).Class() != "Read":
            raise ValueError("native fixture requires a connected Read/Write graph")
        source = Path(write.input(0)["file"].value())
        read_exr(source)
        pattern = write["file"].value()
        api.execute_calls.append((write.name(), first, last, pattern))
        for frame in range(first, last + 1):
            target = Path(pattern % frame)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    api.Knob = NativeKnob
    api.Node = NativeNode
    api.String_Knob = string_knob
    api.nodes = types.SimpleNamespace(
        Read=lambda **knobs: NativeNode("Read", **knobs),
        Write=lambda **knobs: NativeNode("Write", **knobs),
    )
    api.INPUTS, api.HIDDEN_INPUTS, api.EXPRESSIONS = 1, 2, 4
    api._Root.Class = lambda self: "Root"
    api.scriptOpen = script_open
    api.execute = execute
    api.execute_calls = []
    api.opened_scripts = []
    return api


class NativeDispatchClient:
    def __init__(self, addon):
        self.addon = addon
        self.calls: list[str] = []

    def call(self, command, params=None):
        self.calls.append(command)
        return self.addon.dispatch(command, params or {})


class WeakModelClient:
    """Old fabricated success gates retained only as a rejection fixture."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, command: str, _params=None):
        self.calls.append(command)
        if command == "capabilities.get":
            return {"nuke_version": "test", "gui": True}
        gate_contracts = {
            "agent.nuke.probe": ("nuke_running", "capability"),
            "agent.nuke.inspect_input": ("source_exr", "verification"),
            "agent.nuke.build_graph": ("editable_nuke_graph", "verification"),
            "agent.nuke.render_preview": ("preview_rendered", "operation"),
            "agent.nuke.verify_preview": ("preview_artifact", "verification"),
            "agent.nuke.render_final": ("final_rendered", "operation"),
            "agent.nuke.verify_final": ("final_artifacts", "verification"),
            "agent.nuke.deliver": ("delivery_ready", "verification"),
        }
        name, kind = gate_contracts[command]
        return {"gates": [{"name": name, "passed": True, "kind": kind}]}


class WeakModelGoldenPathTests(unittest.TestCase):
    def test_plan_start_result_never_exposes_raw_mutation_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.exr"
            source.write_bytes(encode_tiny_exr())
            addon_path = Path(__file__).resolve().parents[2] / "plugins/nuke/nuke_bridge_addon.py"
            module_spec = importlib.util.spec_from_file_location("weak_model_native_addon", addon_path)
            addon = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(addon)
            api = native_nuke_api()
            client = NativeDispatchClient(addon)
            spec = {
                "task_type": "nuke.render_delivery",
                "intent": "deliver a verified EXR",
                "target": {"application": "nuke"},
                "inputs": [{"role": "effect_render", "path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
                "render": {"resolution": [1, 1], "frame_range": {"start": 1, "end": 3, "step": 1}, "output_dir": str(root / "delivery")},
            }
            environment = {
                "BRIDGE_SKILLS_STATE_ROOT": str(root / "state"),
                "BRIDGE_SKILLS_SCHEDULER_ROOT": str(root / "scheduler"),
                "BRIDGE_ARTIFACT_LEDGER_ROOT": str(root / "ledger"),
                "NUKE_BRIDGE_INSTANCES_DIR": str(root / "instances"),
            }
            with mock.patch.dict(sys.modules, {"nuke": api}), mock.patch.dict(os.environ, environment):
                service = task_service(client, root / "tasks")
                plan = service.plan(spec)
                started = service.start(spec, background=False)
                result = service.result(started["task_id"])
                self.assertEqual(result["state"], "SUCCEEDED", result)
                self.assertEqual([(first, last) for _, first, last, _ in api.execute_calls], [(1, 1), (1, 1), (2, 2), (3, 3)])
                self.assertEqual(len(api.opened_scripts), 1)
                self.assertEqual(len(result["artifacts"]), 5)
                for artifact in result["artifacts"]:
                    path = Path(artifact["path"])
                    self.assertTrue(path.is_file(), artifact)
                    self.assertEqual(artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                delivery = next(gate for gate in result["gates"] if gate["name"] == "delivery_ready")
                self.assertTrue(delivery["post_save_reopen_verified"])
                records = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "state/nuke_renders").glob("nrend-*.json")]
                self.assertEqual(len(records), 4)
                self.assertTrue(all(record["state"] == "COMPLETED" and record["slot_released"] and record["ledger_state"] == "REGISTERED" for record in records))
                for record in records:
                    fact = addon._nuke_operation_fact(record["task_id"])
                    self.assertTrue(fact["stop_confirmed"], fact)
                    receipt = fact["formal_receipt"]
                    self.assertIsInstance(receipt, dict, fact)
                    self.assertEqual(receipt_errors(receipt), [])
                    self.assertEqual(receipt["task_id"], started["task_id"])
        self.assertGreater(plan["total_units"], 0)
        self.assertEqual(client.calls[0], "capabilities.get")
        self.assertNotIn("nuke_run", client.calls)
        self.assertTrue(all(command.startswith(("capabilities.", "agent.nuke.")) for command in client.calls[1:]))

    def test_handwritten_success_gates_cannot_complete_delivery(self) -> None:
        client = WeakModelClient()
        spec = {
            "task_type": "nuke.render_delivery",
            "intent": "deliver a verified EXR",
            "target": {"application": "nuke"},
            "render": {"frame_range": {"start": 1, "end": 3, "step": 1}},
        }
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(client, Path(directory))
            plan = service.plan(spec)
            started = service.start(spec, background=False)
            result = service.result(started["task_id"])
        self.assertGreater(plan["total_units"], 0)
        self.assertEqual(result["state"], "PARTIAL", result)
        self.assertIn("INPUT_SOURCE_IDENTITY_REQUIRED", result["error_message"])
        self.assertEqual(result["artifacts"], [])
        self.assertNotIn("agent.nuke.render_preview", client.calls)
        self.assertNotIn("agent.nuke.deliver", client.calls)
