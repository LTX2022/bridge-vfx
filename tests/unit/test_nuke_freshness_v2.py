from __future__ import annotations

import importlib.util
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from windows_filesystem_fixture import fixture_symlink


ROOT = Path(__file__).resolve().parents[2]
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from dcc_task_runtime.exr_codec import encode_tiny_exr  # noqa: E402


def _write_structural_exr(path: Path, payload: bytes = b"software-test-frame") -> None:
    """Write the smallest deterministic EXR-shaped test artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_tiny_exr(float(sum(payload) % 2000 + 1)))


def _fake_render(addon, write, first, last, stride=1) -> None:
    pattern = str(write["file"].value())
    for frame in range(int(first), int(last) + 1, int(stride or 1)):
        _write_structural_exr(addon._frame_path(pattern, frame), f"frame-{frame}".encode("ascii"))


def _freeze_test_inputs(params, directory):
    from nuke_bridge.operation_receipts import freeze_agent_inputs
    inputs = params.get("inputs") or [{"role":"effect_render"}]
    bounds = (params.get("render") or {}).get("frame_range") or {}
    start, end, step = bounds.get("start",1), bounds.get("end",1), bounds.get("step",1)
    for index, item in enumerate(inputs):
        item.setdefault("role", "effect_render")
        if item.get("sha256") or item.get("frames"):
            continue
        pattern = str(Path(directory) / ("source-%d.%%04d.exr" % index))
        frames = []
        for frame in range(start,end+1,step):
            path = Path(pattern % frame)
            _write_structural_exr(path, f"source-{index}-{frame}".encode())
            frames.append({"frame":frame,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        item.update(path=pattern,frames=frames)
    params["inputs"] = inputs
    params["agent_input_binding"] = freeze_agent_inputs(params["task_id"],inputs)


def load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_nuke_freshness_addon", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_nuke_live_harness():
    path = ROOT / "tools" / "validate_nuke_live.py"
    spec = importlib.util.spec_from_file_location("bridge_test_validate_nuke_live", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeKnob:
    def __init__(
        self,
        value="",
        *,
        clamp: float | None = None,
        reject: bool = False,
        animated: bool = False,
        expression: bool = False,
    ) -> None:
        self._value = value
        self._clamp = clamp
        self._reject = reject
        self._animated = animated
        self._expression = expression

    def value(self):
        return self._value

    def setValue(self, value) -> None:
        if self._reject:
            return
        if self._clamp is not None and isinstance(value, (int, float)):
            self._value = min(float(value), self._clamp)
        else:
            self._value = value

    def setVisible(self, _visible) -> None:
        return None

    def isAnimated(self, *_args) -> bool:
        return self._animated

    def hasExpression(self, *_args) -> bool:
        return self._expression


class FakeNode:
    def __init__(self, name: str, *, knobs=None, sources=None, node_class="", full_name=None) -> None:
        self._name = name
        self._knobs = dict(knobs or {})
        self._sources = list(sources or [])
        self._node_class = node_class
        self._full_name = full_name or name
        self._xpos = 0
        self._ypos = 0

    def name(self):
        return self._name

    def fullName(self):
        return self._full_name

    def Class(self):
        return self._node_class

    def setName(self, name):
        self._name = name
        self._full_name = name

    def knob(self, name):
        return self._knobs.get(name)

    def __getitem__(self, name):
        return self._knobs[name]

    def inputs(self):
        return len(self._sources)

    def input(self, index):
        return self._sources[index]

    def setInput(self, index, source):
        while len(self._sources) <= index:
            self._sources.append(None)
        self._sources[index] = source

    def setXpos(self, value):
        self._xpos = value

    def setYpos(self, value):
        self._ypos = value

    def addKnob(self, knob):
        self._knobs[knob._name] = knob

    def removeKnob(self, knob):
        for name, candidate in list(self._knobs.items()):
            if candidate is knob:
                del self._knobs[name]


class NamedFakeKnob(FakeKnob):
    def __init__(self, name, value="") -> None:
        super().__init__(value)
        self._name = name


class CoupledFakeKnob(FakeKnob):
    def __init__(self, value, on_set) -> None:
        super().__init__(value)
        self._on_set = on_set

    def setValue(self, value) -> None:
        super().setValue(value)
        self._on_set(value)


class FakeUndo:
    def __init__(self, _label) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class FakeBuildNuke:
    def __init__(self, *, sharpen_has_amount=True) -> None:
        self.created = []
        self.deleted = []
        self._by_name = {}
        self._sharpen_has_amount = sharpen_has_amount
        self.Undo = FakeUndo
        self.nodes = types.SimpleNamespace(
            Read=self._create_read,
            Write=self._create_write,
        )

    def _create_read(self, name=None, file=None, **_kwargs):
        node = self.createNode("Read")
        if name:
            node.setName(name)
        if file is not None:
            node["file"].setValue(file)
        return node

    def _create_write(self, name=None, inputs=None, **_kwargs):
        node = self.createNode("Write")
        if name:
            node.setName(name)
        for index, source in enumerate(inputs or []):
            node.setInput(index, source)
        return node

    @staticmethod
    def String_Knob(name, _label):
        return NamedFakeKnob(name)

    def createNode(self, node_class, inpanel=False):
        del inpanel
        knobs = {
            "Read": {"file": FakeKnob("")},
            "Copy": {"from0": FakeKnob(""), "to0": FakeKnob("")},
            "Blur": {"size": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Defocus": {"defocus": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Denoise2": {"mix": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Denoise": {"mix": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Sharpen": {"size": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Glow": {
                "size": FakeKnob(0.0),
                "mix": FakeKnob(0.0),
                "brightness": FakeKnob(0.0),
                "disable": FakeKnob(True),
            },
            "ColorCorrect": {"contrast": FakeKnob(0.0), "disable": FakeKnob(True)},
            "EdgeBlur": {"size": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Grain2": {"mix": FakeKnob(0.0), "intensity": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Grain": {"mix": FakeKnob(0.0), "intensity": FakeKnob(0.0), "disable": FakeKnob(True)},
            "Premult": {"disable": FakeKnob(True)},
            "Merge2": {"operation": FakeKnob("over"), "mix": FakeKnob(1.0), "disable": FakeKnob(False)},
            "NoOp": {},
            "Write": {"file": FakeKnob("")},
        }[node_class]
        if node_class == "Sharpen" and self._sharpen_has_amount:
            knobs["amount"] = FakeKnob(0.0)
        node = FakeNode(
            f"{node_class}_{len(self.created)}",
            knobs=knobs,
            node_class=node_class,
        )
        original_set_name = node.setName

        def set_name(name):
            original_set_name(name)
            self._by_name[name] = node

        node.setName = set_name
        self.created.append(node)
        return node

    def toNode(self, name):
        return self._by_name.get(name)

    def root(self):
        return None

    def allNodes(self, recurseGroups=False):
        del recurseGroups
        return [node for node in self.created if node not in self.deleted]

    def delete(self, node):
        self.deleted.append(node)
        self._by_name.pop(node.name(), None)


class NukeFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_nuke = sys.modules.get("nuke")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        isolated = Path(temporary.name)
        environment = mock.patch.dict(os.environ,{"BRIDGE_SKILLS_STATE_ROOT":str(isolated/"state"),"BRIDGE_SKILLS_SCHEDULER_ROOT":str(isolated/"scheduler")})
        environment.start()
        self.addCleanup(environment.stop)

    def tearDown(self) -> None:
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def test_live_harness_confines_repository_outputs_before_execution(self) -> None:
        harness = load_nuke_live_harness()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "repo"
            allowed = root / "outputs" / "live-validation"
            outside = Path(directory).resolve() / "outside"
            allowed.mkdir(parents=True)
            outside.mkdir()
            with mock.patch.object(harness, "ROOT", root):
                self.assertEqual(
                    harness.validated_output_directory(str(allowed / "nuke-run")),
                    (allowed / "nuke-run").resolve(),
                )
                self.assertEqual(
                    harness.validated_json_output_path(str(outside / "evidence.json")),
                    (outside / "evidence.json").resolve(),
                )
                with self.assertRaises(ValueError):
                    harness.validated_output_directory(str(root / "plugins" / "nuke-output"))
                with self.assertRaises(ValueError):
                    harness.validated_json_output_path(str(root / "tools" / "evidence.json"))

                escape = allowed / "escape"
                if fixture_symlink(self, escape, outside, target_is_directory=True):
                    with self.assertRaises(ValueError):
                        harness.validated_output_directory(str(escape / "run"))
                    with self.assertRaises(ValueError):
                        harness.validated_json_output_path(str(escape / "evidence.json"))

                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        str(harness.__file__),
                        "--port",
                        "59555",
                        "--output-dir",
                        str(root / "plugins" / "nuke-output"),
                        "--json",
                        str(allowed / "evidence.json"),
                    ],
                ), mock.patch.object(harness, "run") as run:
                    self.assertEqual(harness.main(), 2)
                    run.assert_not_called()

    def test_old_preview_is_rejected_and_fresh_preview_passes(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        addon._read_image_metadata = lambda _path: {"width": 64, "height": 64, "channels": ["rgba.red"]}

        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "freshness-task",
                "inputs": [{"path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": directory,
                    "frame_range": {"start": 1, "end": 1, "step": 1},
                    "resolution": [64, 64],
                },
            }
            _freeze_test_inputs(params, directory)
            state = addon._delivery_action("agent.nuke.build_graph", params)["graph"]
            write = fake_nuke.toNode(state["write"])
            pattern = str(Path(directory) / "preview.%04d.exr")
            frame_path = Path(pattern % 1)
            _write_structural_exr(frame_path)
            snapshot = addon._artifact(frame_path)
            state["preview_pattern"] = pattern
            state["preview_before"] = {"1": snapshot}
            state["write_phase"] = "preview"
            write["file"].setValue(pattern)

            stale = addon._delivery_action("agent.nuke.verify_preview", params)
            stale_gate = stale["gates"][0]
            self.assertFalse(stale_gate["passed"])
            self.assertEqual(stale_gate["stale_frames"], [1])
            self.assertEqual(stale["artifacts"], [])

            newer_ns = snapshot["modified_ns"] + 10_000_000
            os.utime(frame_path, ns=(newer_ns, newer_ns))
            still_unproven = addon._delivery_action("agent.nuke.verify_preview", params)
            self.assertFalse(still_unproven["gates"][0]["passed"])
            self.assertEqual(still_unproven["gates"][0]["stale_frames"], [1])

            def execute_render(node, frame_start, _frame_end):
                output = Path(str(node["file"].value()) % frame_start)
                content = output.read_bytes()
                output.write_bytes(content)
                rendered_ns = output.stat().st_mtime_ns + 10_000_000
                os.utime(output, ns=(rendered_ns, rendered_ns))

            fake_nuke.execute = execute_render
            render = addon._delivery_action("agent.nuke.render_preview", params)
            self.assertIn("sha256", render["produced"]["1"])
            self.assertEqual(render["before"]["1"]["sha256"], render["produced"]["1"]["sha256"])
            fresh = addon._delivery_action("agent.nuke.verify_preview", params)
            fresh_gate = fresh["gates"][0]
            self.assertTrue(fresh_gate["passed"])
            self.assertEqual(fresh_gate["stale_frames"], [])
            self.assertEqual(fresh_gate["unreadable_frames"], [])
            self.assertEqual(len(fresh["artifacts"]), 1)

    def test_synchronous_render_returns_operation_not_progress(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        fake_nuke.execute = lambda write, first, last, *rest: _fake_render(
            addon, write, first, last, *(rest[:1] or [1])
        )
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "render-task",
                "inputs": [{"path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": directory,
                    "frame_range": {"start": 1, "end": 1, "step": 1},
                },
            }
            _freeze_test_inputs(params, directory)
            addon._delivery_action("agent.nuke.build_graph", params)
            result = addon._delivery_action("agent.nuke.render_preview", params)
        self.assertEqual(result["gates"], [{"name": "preview_rendered", "passed": True, "kind": "operation", "synchronous": True, "frame": 1}])

    def test_capabilities_bind_the_loaded_addon_source_identity(self) -> None:
        addon = load_addon()
        sys.modules["nuke"] = types.SimpleNamespace(NUKE_VERSION_STRING="17.0v1", GUI=False)

        capabilities = addon.dispatch("capabilities.get", {})
        loaded_path = Path(capabilities["loaded_addon_path"])

        self.assertEqual(loaded_path, (ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py").resolve())
        self.assertEqual(capabilities["loaded_addon_sha256"], addon._artifact(loaded_path)["sha256"])

    def test_scene_fingerprint_changes_when_only_a_connection_changes(self) -> None:
        addon = load_addon()

        class ScriptKnob:
            def __init__(self, value):
                self.value = value

            def toScript(self):
                return str(self.value)

        class SceneNode:
            def __init__(self, name, sources=None):
                self._name = name
                self.sources = list(sources or [])

            def fullName(self):
                return self._name

            def name(self):
                return self._name

            def Class(self):
                return "NoOp"

            def knobs(self):
                return {"label": ScriptKnob("same")}

            def inputs(self):
                return len(self.sources)

            def input(self, index):
                return self.sources[index]

            def dependencies(self, _flags):
                return list(self.sources)

        root = SceneNode("Root")
        left = SceneNode("Root.LEFT")
        right = SceneNode("Root.RIGHT")
        merge = SceneNode("Root.MERGE", [left])
        nodes = [left, right, merge]
        sys.modules["nuke"] = types.SimpleNamespace(
            root=lambda: root,
            allNodes=lambda recurseGroups=True: list(nodes),
            INPUTS=1,
            HIDDEN_INPUTS=2,
            EXPRESSIONS=4,
        )

        first = addon._nuke_scene_fingerprint()
        merge.sources = [right]
        second = addon._nuke_scene_fingerprint()

        self.assertTrue(first["fingerprint_complete"])
        self.assertTrue(second["fingerprint_complete"])
        self.assertNotEqual(first["scene_fingerprint"], second["scene_fingerprint"])

    def test_agent_dispatch_rejects_pre_action_and_non_task_scene_drift(self) -> None:
        addon = load_addon()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        frozen = {"task_id":"legacy-scene-contract-task"}
        _freeze_test_inputs(frozen,temporary.name)
        expected = "1" * 64

        def state(full, task="2", non_task="3", global_state="4"):
            return {
                "script": "/show/scene.nk",
                "modified": False,
                "scene_fingerprint": full * 64,
                "task_scene_fingerprint": task * 64,
                "non_task_scene_fingerprint": non_task * 64,
                "global_scene_fingerprint": global_state * 64,
                "fingerprint_complete": True,
                "fingerprint_errors": [],
            }

        action = mock.Mock(return_value={"gates": []})
        with mock.patch.object(addon, "_post_scene_state", return_value=state("5")):
            with self.assertRaisesRegex(RuntimeError, "changed before action"):
                addon._dispatch_agent_with_scene_contract(
                    "agent.nuke.composite.probe",
                    {
                        "task_id": "scene-contract-task",
                        "expected_pre_scene_fingerprint": expected,
                    },
                    action,
                )
        action.assert_not_called()

        action.reset_mock()
        with mock.patch.object(
            addon,
            "_post_scene_state",
            side_effect=[state("1"), state("6")],
        ):
            with self.assertRaisesRegex(RuntimeError, "read-only Nuke action changed"):
                addon._dispatch_agent_with_scene_contract(
                    "agent.nuke.composite.audit_lineage",
                    {
                        "task_id": "scene-contract-task",
                        "expected_pre_scene_fingerprint": expected,
                    },
                    action,
                )
        action.assert_called_once()

        # The v1 first-party render path is governed by the same boundary;
        # its tagged Read/Write may change, but an unrelated node may not.
        action.reset_mock()
        with mock.patch.object(
            addon,
            "_post_scene_state",
            side_effect=[
                state("1", task="2", non_task="3", global_state="4"),
                state("a", task="b", non_task="c", global_state="4"),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "non-task/global"):
                addon._dispatch_agent_with_scene_contract(
                    "agent.nuke.render_final",
                    {
                        **frozen,
                        "expected_pre_scene_fingerprint": expected,
                    },
                    action,
                )
        action.assert_called_once()

        action.reset_mock()
        with mock.patch.object(
            addon,
            "_post_scene_state",
            side_effect=[
                state("1", task="2", non_task="3", global_state="4"),
                state("7", task="8", non_task="9", global_state="4"),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "non-task/global"):
                addon._dispatch_agent_with_scene_contract(
                    "agent.nuke.composite.apply_patch",
                    {
                        "task_id": "scene-contract-task",
                        "expected_pre_scene_fingerprint": expected,
                    },
                    action,
                )
        action.assert_called_once()

    def test_final_gate_checks_every_frame_for_freshness_and_readability(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        addon._read_image_metadata = lambda _path: {"width": 64, "height": 64, "channels": ["rgba.red"]}

        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "final-task",
                "inputs": [{"path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": directory,
                    "frame_range": {"start": 1, "end": 2, "step": 1},
                    "resolution": [64, 64],
                },
            }
            state = addon._delivery_action("agent.nuke.build_graph", params)["graph"]
            pattern = str(Path(directory) / "final.%04d.exr")
            paths = [Path(pattern % frame) for frame in (1, 2)]
            for path in paths:
                _write_structural_exr(path)
            before = {str(frame): addon._artifact(path) for frame, path in zip((1, 2), paths)}
            state["final_before"] = before
            state["final_range"] = [1, 2]
            state["final_stride"] = 1

            first_new_ns = before["1"]["modified_ns"] + 10_000_000
            os.utime(paths[0], ns=(first_new_ns, first_new_ns))
            state["final_produced"] = {
                "1": addon._artifact(paths[0]),
                "2": before["2"],
            }
            stale = addon._delivery_action("agent.nuke.verify_final", params)
            self.assertFalse(stale["gates"][0]["passed"])
            self.assertEqual(stale["gates"][0]["stale_frames"], [2])

            second_new_ns = before["2"]["modified_ns"] + 10_000_000
            os.utime(paths[1], ns=(second_new_ns, second_new_ns))
            state["final_produced"]["2"] = addon._artifact(paths[1])
            fresh = addon._delivery_action("agent.nuke.verify_final", params)
            gate = fresh["gates"][0]
            self.assertTrue(gate["passed"])
            self.assertEqual(gate["stale_frames"], [])
            self.assertEqual(gate["unreadable_frames"], [])
            self.assertEqual(sorted(gate["metadata_by_frame"]), ["1", "2"])
            self.assertEqual(len(fresh["artifacts"]), 2)

    def test_animated_or_expression_knob_fails_before_any_patch_mutation(self) -> None:
        for state_kind in ("animated", "expression"):
            with self.subTest(state_kind=state_kind):
                addon = load_addon()
                glow_amount = FakeKnob(1.0)
                glow_disable = FakeKnob(False)
                blur_size = FakeKnob(
                    2.0,
                    animated=state_kind == "animated",
                    expression=state_kind == "expression",
                )
                blur_disable = FakeKnob(False)
                glow = FakeNode(
                    "GLOW",
                    knobs={
                        "size": FakeKnob(3.0),
                        "mix": FakeKnob(1.0),
                        "brightness": glow_amount,
                        "disable": glow_disable,
                        "bridge_capability": FakeKnob("native"),
                    },
                )
                blur = FakeNode(
                    "BLUR",
                    knobs={
                        "size": blur_size,
                        "disable": blur_disable,
                        "bridge_capability": FakeKnob("native"),
                    },
                )
                state_metadata = FakeKnob("frozen-state")
                write = FakeNode(
                    "WRITE",
                    knobs={
                        "file": FakeKnob("/tmp/final.%04d.exr"),
                        "bridge_state_json": state_metadata,
                    },
                )
                nodes = {"GLOW": glow, "BLUR": blur, "WRITE": write}
                sys.modules["nuke"] = types.SimpleNamespace(
                    toNode=nodes.get,
                    root=lambda: None,
                )

                with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
                    addon._apply_composite_patch(
                        {
                            "task_id": "animated-expression-task-" + state_kind,
                            "write": "WRITE",
                            "graph_nodes": {
                                "effect_glow": "GLOW",
                                "effect_blur": "BLUR",
                            },
                        },
                        {
                            "controls": {
                                "glow_amount": 4.0,
                                "blur_size": 5.0,
                            }
                        },
                    )

                # Blur is deliberately the second primary target.  Glow must
                # remain untouched, proving the whole plan was preflighted.
                self.assertEqual(glow_amount.value(), 1.0)
                self.assertFalse(glow_disable.value())
                self.assertEqual(blur_size.value(), 2.0)
                self.assertFalse(blur_disable.value())
                self.assertEqual(state_metadata.value(), "frozen-state")

    def test_animated_hidden_state_metadata_fails_before_control_write(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": size,
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        state_metadata = FakeKnob("frozen-state", animated=True)
        write = FakeNode(
            "WRITE",
            knobs={
                "file": FakeKnob("/tmp/final.%04d.exr"),
                "bridge_state_json": state_metadata,
            },
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)

        with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
            addon._apply_composite_patch(
                {
                    "task_id": "animated-metadata-task",
                    "write": "WRITE",
                    "graph_nodes": {"effect_blur": "BLUR"},
                },
                {"controls": {"blur_size": 4.0}},
            )

        self.assertEqual(size.value(), 2.0)
        self.assertEqual(state_metadata.value(), "frozen-state")

    def test_knob_clamp_is_a_readback_mismatch_and_is_restored(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0, clamp=10.0)
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": size,
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        patch_state = {
            "task_id": "patch-task",
            "write": "WRITE",
            "graph_nodes": {"effect_blur": "BLUR"},
            "final_verification": {"verification_identity": "still-valid"},
        }
        with self.assertRaisesRegex(RuntimeError, "PARAMETER_READBACK_MISMATCH"):
            addon._apply_composite_patch(
                patch_state,
                {"controls": {"blur_size": 20.0}},
            )
        self.assertEqual(size.value(), 2.0)
        self.assertEqual(
            patch_state["final_verification"],
            {"verification_identity": "still-valid"},
        )

    def test_exact_knob_readback_emits_operation_gate(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": size,
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        result = addon._apply_composite_patch(
            {"task_id": "patch-task", "write": "WRITE", "graph_nodes": {"effect_blur": "BLUR"}},
            {"controls": {"blur_size": 4.5}},
        )
        gate = next(item for item in result["gates"] if item["name"] == "composite_patch_applied")
        self.assertEqual(gate["kind"], "operation")
        self.assertTrue(gate["passed"])
        self.assertTrue(result["changes"][0]["readback_verified"])
        self.assertEqual(result["changes"][0]["after"], 4.5)

    def test_multi_control_mid_transaction_failure_preserves_every_static_knob(self) -> None:
        addon = load_addon()
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": FakeKnob(2.0),
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        defocus = FakeNode(
            "DEFOCUS",
            knobs={
                "defocus": FakeKnob(1.0, clamp=5.0),
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"BLUR": blur, "DEFOCUS": defocus, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        with self.assertRaisesRegex(RuntimeError, "PARAMETER_READBACK_MISMATCH"):
            addon._apply_composite_patch(
                {
                    "task_id": "transaction-task",
                    "write": "WRITE",
                    "graph_nodes": {"effect_blur": "BLUR", "effect_defocus": "DEFOCUS"},
                },
                {"controls": {"blur_size": 4.5, "defocus": 20.0}},
            )
        self.assertEqual(blur["size"].value(), 2.0)
        self.assertFalse(blur["disable"].value())
        self.assertEqual(defocus["defocus"].value(), 1.0)
        self.assertFalse(defocus["disable"].value())

    def test_state_persistence_failure_rolls_back_knobs_metadata_and_registry(self) -> None:
        addon = load_addon()
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": FakeKnob(2.0),
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        state_metadata = FakeKnob("frozen-state")
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": state_metadata},
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        previous_registry_state = {"sentinel": "previous"}
        addon._COMPOSITES["persist-task"] = previous_registry_state
        patch_state = {
            "task_id": "persist-task",
            "write": "WRITE",
            "graph_nodes": {"effect_blur": "BLUR"},
            "final_verification": {"verification_identity": "persisted-proof"},
        }

        def fail_after_partial_persist(_state):
            state_metadata.setValue("partial-state")
            addon._COMPOSITES["persist-task"] = {"sentinel": "partial"}
            raise RuntimeError("persist failed")

        with mock.patch.object(addon, "_persist_composite_state", side_effect=fail_after_partial_persist):
            with self.assertRaisesRegex(RuntimeError, "persist failed"):
                addon._apply_composite_patch(
                    patch_state,
                    {"controls": {"blur_size": 4.5}},
                )

        self.assertEqual(blur["size"].value(), 2.0)
        self.assertFalse(blur["disable"].value())
        self.assertEqual(state_metadata.value(), "frozen-state")
        self.assertIs(addon._COMPOSITES["persist-task"], previous_registry_state)
        self.assertEqual(
            patch_state["final_verification"],
            {"verification_identity": "persisted-proof"},
        )

    def test_patch_lineage_failure_restores_final_verification_and_controls(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": size,
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("frozen")},
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        state = {
            "task_id": "lineage-rollback-task",
            "write": "WRITE",
            "graph_nodes": {"effect_blur": "BLUR"},
            "final_verification": {"verification_identity": "lineage-proof"},
        }
        failed_audit = {
            "gates": [
                {
                    "name": "reference_isolated_from_final_write",
                    "passed": False,
                    "kind": "verification",
                }
            ],
            "lineage": {"passed": False},
        }
        with mock.patch.object(addon, "_audit_composite_lineage", return_value=failed_audit):
            with self.assertRaisesRegex(RuntimeError, "reference lineage violation"):
                addon._apply_composite_patch(
                    state,
                    {"controls": {"blur_size": 4.5}},
                )
        self.assertEqual(size.value(), 2.0)
        self.assertEqual(
            state["final_verification"],
            {"verification_identity": "lineage-proof"},
        )

    def test_disable_knob_refusal_fails_patch_and_restores_primary_control(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        disable = FakeKnob(False, reject=True)
        blur = FakeNode(
            "BLUR",
            knobs={
                "size": size,
                "disable": disable,
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("frozen")},
        )
        nodes = {"BLUR": blur, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)

        with self.assertRaisesRegex(RuntimeError, "PARAMETER_READBACK_MISMATCH: blur_size.disable"):
            addon._apply_composite_patch(
                {
                    "task_id": "disable-refusal-task",
                    "write": "WRITE",
                    "graph_nodes": {"effect_blur": "BLUR"},
                },
                {"controls": {"blur_size": 0.0}},
            )

        self.assertEqual(size.value(), 2.0)
        self.assertFalse(disable.value())
        self.assertNotIn("disable-refusal-task", addon._COMPOSITES)

    def test_premult_rejects_string_boolean_without_mutating_knob(self) -> None:
        addon = load_addon()
        disable = FakeKnob(False)
        premult = FakeNode("PREMULT", knobs={"disable": disable})
        addon._COMPOSITES.clear()
        with unittest.mock.patch.object(addon, "_node", return_value=premult):
            with self.assertRaisesRegex(ValueError, "premult must be a boolean"):
                addon._apply_composite_patch(
                    {
                        "task_id": "premult-type-task",
                        "graph_nodes": {"effect_premult": "PREMULT"},
                    },
                    {"controls": {"premult": "false"}},
                )
        self.assertFalse(disable.value())
        self.assertNotIn("premult-type-task", addon._COMPOSITES)

    def test_middle_reference_sequence_frame_cannot_bypass_lineage(self) -> None:
        addon = load_addon()
        reference = FakeNode(
            "UNTAGGED_REFERENCE_FRAME",
            knobs={"file": FakeKnob("/tmp/reference.0002.exr")},
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr")},
            sources=[reference],
        )
        sys.modules["nuke"] = types.SimpleNamespace(toNode=lambda name: write if name == "WRITE" else None)
        result = addon._audit_composite_lineage(
            {
                "write": "WRITE",
                "reference_source_paths": ["/tmp/reference.%04d.exr"],
                "frame_range": {"start": 1, "end": 3, "step": 1},
            }
        )
        gate = result["lineage"]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["violations"], ["UNTAGGED_REFERENCE_FRAME"])
        self.assertIn("frozen_reference_path", gate["violation_details"][0]["reasons"])

    def test_embedded_hash_sequence_token_matches_concrete_reference_frame(self) -> None:
        addon = load_addon()
        frame_range = {"start": 1, "end": 48, "step": 1}
        self.assertEqual(
            addon._frame_path("/tmp/ref_####_beauty.exr", 12),
            Path("/tmp/ref_0012_beauty.exr"),
        )
        self.assertTrue(
            addon._media_paths_overlap(
                "/tmp/ref_####_beauty.exr",
                "/tmp/ref_0012_beauty.exr",
                frame_range,
            )
        )
        self.assertTrue(
            addon._media_paths_overlap(
                "/tmp/ref_####_beauty.exr",
                "/tmp/ref_%04d_beauty.exr",
                frame_range,
            )
        )
        self.assertEqual(
            addon._frame_path("/tmp/100%_effect.exr", 12),
            Path("/tmp/100%_effect.exr"),
        )

    def test_reference_sequence_is_symbolic_and_oversized_ranges_fail_closed(self) -> None:
        addon = load_addon()
        last_frame = addon._MAX_COMPOSITE_FRAME_COUNT
        reference = FakeNode(
            "UNTAGGED_LAST_REFERENCE_FRAME",
            knobs={"file": FakeKnob(f"/tmp/reference.{last_frame:04d}.exr")},
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr")},
            sources=[reference],
        )
        sys.modules["nuke"] = types.SimpleNamespace(toNode=lambda name: write if name == "WRITE" else None)

        allowed = addon._audit_composite_lineage(
            {
                "write": "WRITE",
                "reference_source_paths": ["/tmp/reference.%04d.exr"],
                "frame_range": {"start": 1, "end": last_frame, "step": 1},
            }
        )
        self.assertFalse(allowed["lineage"]["passed"])
        self.assertEqual(allowed["lineage"]["violations"], ["UNTAGGED_LAST_REFERENCE_FRAME"])

        with self.assertRaisesRegex(ValueError, "REFERENCE_FRAME_RANGE_LIMIT_EXCEEDED"):
            addon._composite_action(
                "agent.nuke.composite.probe",
                {
                    "task_id": "oversized-reference-range",
                    "render": {"frame_range": {"start": 1, "end": last_frame + 1, "step": 1}},
                },
            )

    def test_patch_rejects_aliases_that_resolve_to_one_physical_knob(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        disable = FakeKnob(False)
        sharpen = FakeNode(
            "SHARPEN",
            knobs={
                "size": size,
                "disable": disable,
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"SHARPEN": sharpen, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)

        with self.assertRaisesRegex(ValueError, "SEMANTIC_CONTROL_ALIAS_CONFLICT"):
            addon._apply_composite_patch(
                {
                    "task_id": "alias-conflict-task",
                    "write": "WRITE",
                    "graph_nodes": {"effect_sharpen": "SHARPEN"},
                },
                {"controls": {"sharpen_size": 4.0, "sharpen_amount": 6.0}},
            )

        self.assertEqual(size.value(), 2.0)
        self.assertFalse(disable.value())
        self.assertNotIn("alias-conflict-task", addon._COMPOSITES)

    def test_patch_prefers_distinct_amount_knobs_and_combines_shared_disable(self) -> None:
        addon = load_addon()
        sharpen = FakeNode(
            "SHARPEN",
            knobs={
                "size": FakeKnob(1.0),
                "amount": FakeKnob(1.0),
                "disable": FakeKnob(True),
                "bridge_capability": FakeKnob("native"),
            },
        )
        glow = FakeNode(
            "GLOW",
            knobs={
                "size": FakeKnob(1.0),
                "mix": FakeKnob(1.0),
                "brightness": FakeKnob(1.0),
                "disable": FakeKnob(True),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"SHARPEN": sharpen, "GLOW": glow, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)

        result = addon._apply_composite_patch(
            {
                "task_id": "distinct-alias-task",
                "write": "WRITE",
                "graph_nodes": {"effect_sharpen": "SHARPEN", "effect_glow": "GLOW"},
            },
            {
                "controls": {
                    "sharpen_size": 0.0,
                    "sharpen_amount": 3.0,
                    "glow_mix": 0.0,
                    "glow_amount": 2.0,
                }
            },
        )

        changed_knobs = {item["control"]: item["knob"] for item in result["changes"]}
        self.assertEqual(changed_knobs["sharpen_size"], "size")
        self.assertEqual(changed_knobs["sharpen_amount"], "amount")
        self.assertEqual(changed_knobs["glow_mix"], "mix")
        self.assertEqual(changed_knobs["glow_amount"], "brightness")
        self.assertFalse(sharpen["disable"].value())
        self.assertFalse(glow["disable"].value())

    def test_later_zero_patch_preserves_an_existing_nonzero_glow_control(self) -> None:
        addon = load_addon()
        glow = FakeNode(
            "GLOW",
            knobs={
                "size": FakeKnob(0.0),
                "mix": FakeKnob(0.0),
                "brightness": FakeKnob(0.0),
                "disable": FakeKnob(True),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"GLOW": glow, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        state = {
            "task_id": "sequential-glow-task",
            "write": "WRITE",
            "graph_nodes": {"effect_glow": "GLOW"},
        }

        addon._apply_composite_patch(state, {"controls": {"glow_size": 10.0}})
        self.assertFalse(glow["disable"].value())
        addon._apply_composite_patch(state, {"controls": {"glow_amount": 0.0}})

        self.assertEqual(glow["size"].value(), 10.0)
        self.assertEqual(glow["brightness"].value(), 0.0)
        self.assertFalse(glow["disable"].value())

    def test_final_aggregate_readback_catches_cross_knob_overwrite_and_restores(self) -> None:
        addon = load_addon()
        size = FakeKnob(2.0)
        amount = CoupledFakeKnob(1.0, lambda _value: size.setValue(99.0))
        sharpen = FakeNode(
            "SHARPEN",
            knobs={
                "size": size,
                "amount": amount,
                "disable": FakeKnob(False),
                "bridge_capability": FakeKnob("native"),
            },
        )
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr"), "bridge_state_json": FakeKnob("")},
        )
        nodes = {"SHARPEN": sharpen, "WRITE": write}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)

        with self.assertRaisesRegex(RuntimeError, "PARAMETER_READBACK_MISMATCH"):
            addon._apply_composite_patch(
                {
                    "task_id": "coupled-knob-task",
                    "write": "WRITE",
                    "graph_nodes": {"effect_sharpen": "SHARPEN"},
                },
                {"controls": {"sharpen_size": 4.0, "sharpen_amount": 3.0}},
            )

        self.assertEqual(size.value(), 2.0)
        self.assertEqual(amount.value(), 1.0)

    def test_rollback_verifies_the_final_combined_snapshot(self) -> None:
        addon = load_addon()
        amount = FakeKnob(1.0)
        size = CoupledFakeKnob(2.0, lambda _value: amount.setValue(99.0))
        node = FakeNode("COUPLED", knobs={"size": size, "amount": amount})
        size._value = 4.0
        amount._value = 3.0

        errors = addon._restore_composite_mutations(
            [(node, "size", 2.0, True), (node, "amount", 1.0, True)]
        )

        self.assertIn("COUPLED.amount final readback mismatch", errors)

    def test_initial_build_uses_distinct_aliases_and_combines_shared_disable(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke

        with tempfile.TemporaryDirectory() as directory:
            result = addon._build_composite_graph(
                {
                    "task_id": "build-controls-task",
                    "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                    "render": {
                        "output_dir": directory,
                        "frame_range": {"start": 1, "end": 1, "step": 1},
                    },
                    "constraints": {
                        "composite_controls": {
                            "sharpen_size": 0.0,
                            "sharpen_amount": 3.0,
                        }
                    },
                }
            )

        sharpen = next(node for node in fake_nuke.created if node.Class() == "Sharpen")
        self.assertEqual(sharpen["size"].value(), 0.0)
        self.assertEqual(sharpen["amount"].value(), 3.0)
        self.assertFalse(sharpen["disable"].value())
        self.assertTrue(next(g for g in result["gates"] if g["name"] == "editable_native_composite_graph")["passed"])
        self.assertTrue(next(g for g in result["gates"] if g["name"] == "composite_topology_intact")["passed"])

    def test_initial_build_rejects_alias_conflict_and_deletes_partial_graph(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke(sharpen_has_amount=False)
        sys.modules["nuke"] = fake_nuke

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "SEMANTIC_CONTROL_ALIAS_CONFLICT"):
                addon._build_composite_graph(
                    {
                        "task_id": "build-alias-conflict-task",
                        "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                        "render": {"output_dir": directory},
                        "constraints": {
                            "composite_controls": {
                                "sharpen_size": 4.0,
                                "sharpen_amount": 6.0,
                            }
                        },
                    }
                )

        self.assertEqual(len(fake_nuke.deleted), len(fake_nuke.created))
        self.assertNotIn("build-alias-conflict-task", addon._COMPOSITES)

    def test_initial_build_rejects_string_premult_before_creating_nodes(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke

        with self.assertRaisesRegex(ValueError, "premult must be a boolean"):
            addon._build_composite_graph(
                {
                    "task_id": "build-premult-type-task",
                    "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                    "constraints": {"composite_controls": {"premult": "false"}},
                }
            )

        self.assertEqual(fake_nuke.created, [])
        self.assertNotIn("build-premult-type-task", addon._COMPOSITES)

    def test_initial_build_rolls_back_when_a_target_knob_is_animated(self) -> None:
        addon = load_addon()

        class AnimatedBuildNuke(FakeBuildNuke):
            def createNode(self, node_class, inpanel=False):
                node = super().createNode(node_class, inpanel=inpanel)
                if node_class == "Blur":
                    node["size"]._animated = True
                return node

        fake_nuke = AnimatedBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
                addon._build_composite_graph(
                    {
                        "task_id": "build-animated-knob-task",
                        "inputs": [
                            {"role": "effect_render", "path": "/tmp/effect.%04d.exr"}
                        ],
                        "constraints": {"composite_controls": {"blur_size": 2.0}},
                        "render": {"output_dir": directory},
                    }
                )

        self.assertEqual(fake_nuke.allNodes(), [])
        self.assertNotIn("build-animated-knob-task", addon._COMPOSITES)

    def test_existing_static_reference_alias_uses_file_identity(self) -> None:
        addon = load_addon()
        with tempfile.TemporaryDirectory() as directory:
            upper = Path(directory) / "Reference.EXR"
            lower = Path(directory) / "reference.exr"
            upper.write_bytes(b"reference")
            try:
                os.link(upper, lower)
            except FileExistsError:
                pass
            self.assertTrue(addon._media_paths_overlap(str(upper), str(lower)))

    def test_darwin_sequence_case_and_out_of_delivery_range_fail_closed(self) -> None:
        addon = load_addon()
        with mock.patch.object(addon.sys, "platform", "darwin"):
            self.assertTrue(
                addon._media_paths_overlap(
                    "/tmp/Smoke_####.EXR",
                    "/tmp/smoke_0001.exr",
                    {"start": 20, "end": 30, "step": 1},
                )
            )

    def test_reference_binding_accepts_equivalent_symbolic_tokens_only(self) -> None:
        addon = load_addon()
        self.assertTrue(
            addon._media_source_binding_matches(
                "/tmp/reference.%04d.exr",
                "/tmp/reference.####.exr",
            )
        )
        self.assertFalse(
            addon._media_source_binding_matches(
                "/tmp/reference.%04d.exr",
                "/tmp/reference.0001.exr",
            )
        )
        self.assertFalse(
            addon._media_source_binding_matches(
                "/tmp/reference.%04d.exr",
                "/tmp/reference.%d.exr",
            )
        )

    def test_opaque_group_and_hidden_dependency_cannot_bypass_lineage(self) -> None:
        addon = load_addon()
        internal_reference = FakeNode(
            "REFERENCE_INSIDE_GROUP",
            knobs={"file": FakeKnob("/tmp/reference.0001.exr")},
            node_class="Read",
            full_name="OPAQUE_GROUP.REFERENCE_INSIDE_GROUP",
        )

        class FakeGroup(FakeNode):
            def nodes(self):
                return [internal_reference]

        group = FakeGroup("OPAQUE_GROUP", node_class="Group")
        write = FakeNode("WRITE", knobs={"file": FakeKnob("/tmp/final.%04d.exr")}, sources=[group])
        sys.modules["nuke"] = types.SimpleNamespace(toNode=lambda name: write if name == "WRITE" else None)
        group_result = addon._audit_composite_lineage(
            {
                "write": "WRITE",
                "reference_source_paths": ["/tmp/reference.%04d.exr"],
                "frame_range": {"start": 1, "end": 1, "step": 1},
            }
        )
        self.assertFalse(group_result["lineage"]["passed"])
        self.assertIn("opaque_wrapper_uninspected", group_result["lineage"]["violation_details"][0]["reasons"])

        class HiddenDependencyNode(FakeNode):
            def dependencies(self, _flags=0):
                return [internal_reference]

        hidden = HiddenDependencyNode("HIDDEN_DEPENDENCY")
        hidden_write = FakeNode("WRITE_HIDDEN", knobs={"file": FakeKnob("/tmp/final.%04d.exr")}, sources=[hidden])
        sys.modules["nuke"] = types.SimpleNamespace(
            toNode=lambda name: hidden_write if name == "WRITE_HIDDEN" else None,
            INPUTS=1,
            HIDDEN_INPUTS=2,
            EXPRESSIONS=4,
        )
        hidden_result = addon._audit_composite_lineage(
            {
                "write": "WRITE_HIDDEN",
                "reference_source_paths": ["/tmp/reference.%04d.exr"],
                "frame_range": {"start": 1, "end": 1, "step": 1},
            }
        )
        self.assertFalse(hidden_result["lineage"]["passed"])
        self.assertIn("OPAQUE_GROUP.REFERENCE_INSIDE_GROUP", hidden_result["lineage"]["violations"])

    def test_distinct_same_named_nodes_are_both_audited(self) -> None:
        addon = load_addon()
        reference = FakeNode(
            "DUPLICATE",
            full_name="Root.BranchB.DUPLICATE",
            knobs={"file": FakeKnob("/tmp/reference.0001.exr")},
        )
        benign = FakeNode("DUPLICATE", full_name="Root.BranchA.DUPLICATE")
        write = FakeNode(
            "WRITE",
            knobs={"file": FakeKnob("/tmp/final.%04d.exr")},
            sources=[reference, benign],
        )
        sys.modules["nuke"] = types.SimpleNamespace(toNode=lambda name: write if name == "WRITE" else None)

        result = addon._audit_composite_lineage(
            {
                "write": "WRITE",
                "reference_source_paths": ["/tmp/reference.%04d.exr"],
                "frame_range": {"start": 1, "end": 1, "step": 1},
            }
        )
        self.assertFalse(result["lineage"]["passed"])
        self.assertIn("Root.BranchB.DUPLICATE", result["lineage"]["violations"])

    def test_composite_state_rejects_deleted_effect_input_before_render(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            built = addon._build_composite_graph(
                {
                    "task_id": "deleted-effect-task",
                    "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                    "render": {"output_dir": directory},
                }
            )
        effect_name = built["graph"]["input_nodes"]["effect_render"]
        fake_nuke.delete(fake_nuke.toNode(effect_name))

        with self.assertRaisesRegex(RuntimeError, "COMPOSITE_TOPOLOGY_INVALID"):
            addon._composite_state("deleted-effect-task")

    def test_composite_state_rejects_deleted_reference_diagnostic(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            built = addon._build_composite_graph(
                {
                    "task_id": "deleted-reference-task",
                    "inputs": [
                        {"role": "effect_render", "path": "/tmp/effect.%04d.exr"},
                        {"role": "reference", "path": "/tmp/reference.%04d.exr"},
                    ],
                    "render": {"output_dir": directory},
                }
            )
        diagnostic_name = built["graph"]["graph_nodes"]["reference_diagnostic"]
        fake_nuke.delete(fake_nuke.toNode(diagnostic_name))
        addon._COMPOSITES.clear()

        with self.assertRaisesRegex(RuntimeError, "COMPOSITE_TOPOLOGY_INVALID"):
            addon._composite_state("deleted-reference-task")

    def test_composite_state_rejects_wrong_graph_role_tag(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            built = addon._build_composite_graph(
                {
                    "task_id": "wrong-tag-task",
                    "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                    "render": {"output_dir": directory},
                }
            )
        blur_name = built["graph"]["graph_nodes"]["effect_blur"]
        fake_nuke.toNode(blur_name)["bridge_graph_role"].setValue("effect_glow")

        with self.assertRaisesRegex(RuntimeError, "graph_role_tag_mismatch:effect_blur"):
            addon._composite_state("wrong-tag-task")

    def test_idempotent_composite_build_keeps_operation_and_lineage_gates(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "existing-task",
                "inputs": [{"role": "effect_render", "path": "/tmp/effect.%04d.exr"}],
                "render": {"output_dir": directory},
            }
            addon._build_composite_graph(params)
            result = addon._build_composite_graph(params)
        by_name = {gate["name"]: gate for gate in result["gates"]}
        self.assertTrue(by_name["editable_native_composite_graph"]["passed"])
        self.assertEqual(by_name["editable_native_composite_graph"]["kind"], "operation")
        self.assertTrue(by_name["composite_topology_intact"]["passed"])
        self.assertTrue(by_name["reference_isolated_from_final_write"]["passed"])
        self.assertEqual(by_name["reference_isolated_from_final_write"]["kind"], "verification")
        self.assertTrue(result["restored"])

    def test_all_file_backed_inputs_are_bound_and_effect_drift_is_rejected(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        inputs = [
            {"role": role, "path": f"/show/{role}.%04d.exr"}
            for role in ("effect_render", "plate", "reference", "matte", "depth", "vector")
        ]
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "all-input-bindings-task",
                "inputs": inputs,
                "render": {"output_dir": directory},
            }
            state = addon._build_composite_graph(params)["graph"]

        expected_roles = {item["role"] for item in inputs}
        self.assertEqual(set(state["input_source_paths"]), expected_roles)
        self.assertEqual(set(state["input_source_bindings"]), expected_roles)
        self.assertEqual(set(state["input_source_identities"]), expected_roles)
        topology = addon._validate_composite_topology(state)["topology"]
        self.assertTrue(topology["passed"])
        self.assertEqual(set(topology["input_bindings"]), expected_roles)

        effect_node = fake_nuke.toNode(state["input_nodes"]["effect_render"])
        effect_node["file"].setValue("/show/effect-b.%04d.exr")
        with self.assertRaisesRegex(RuntimeError, "INPUT_SOURCE_DRIFT:effect_render"):
            addon._composite_state(params["task_id"])

        # Even a tampered hidden state that is internally self-consistent must
        # still be rejected when the next action carries the original TaskSpec.
        state["input_source_paths"]["effect_render"] = "/show/effect-b.%04d.exr"
        state["input_source_bindings"]["effect_render"].update(
            {
                "frozen_path": "/show/effect-b.%04d.exr",
                "readback_path": "/show/effect-b.%04d.exr",
            }
        )
        addon._persist_composite_state(state)
        self.assertTrue(addon._validate_composite_topology(state)["topology"]["passed"])
        with self.assertRaisesRegex(RuntimeError, "INPUT_SPEC_DRIFT:effect_render"):
            addon._validate_composite_input_contract(state, params)

    def test_strict_static_input_hash_detects_same_path_byte_replacement(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "effect.exr"
            source.write_bytes(b"effect-a")
            declared = hashlib.sha256(source.read_bytes()).hexdigest()
            params = {
                "task_id": "static-hash-task",
                "schema_version": "2.0",
                "inputs": [
                    {"role": "effect_render", "path": str(source), "sha256": declared}
                ],
                "render": {"output_dir": str(Path(directory) / "output")},
            }
            state = addon._build_composite_graph(params)["graph"]
            self.assertEqual(
                state["input_source_identities"]["effect_render"]["sha256"],
                declared,
            )
            source.write_bytes(b"effect-b")

            with self.assertRaisesRegex(RuntimeError, "INPUT_SOURCE_HASH_MISMATCH:effect_render"):
                addon._composite_state(params["task_id"])

    def test_strict_sequence_manifest_detects_one_replaced_frame(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame_paths = [root / f"effect.{frame:04d}.exr" for frame in (1, 2)]
            for frame, path in zip((1, 2), frame_paths):
                path.write_bytes((f"frame-{frame}-a").encode("ascii"))
            raw_frames = [
                {
                    "frame": frame,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for frame, path in zip((1, 2), frame_paths)
            ]
            pattern = str(root / "effect.%04d.exr")
            provisional = addon._capture_composite_input_identity(
                "effect_render",
                {"path": pattern, "frames": raw_frames},
                strict=False,
            )
            params = {
                "task_id": "sequence-hash-task",
                "schema_version": "2.0",
                "inputs": [
                    {
                        "role": "effect_render",
                        "path": pattern,
                        "sha256": provisional["manifest_sha256"],
                        "frames": raw_frames,
                    }
                ],
                "render": {
                    "output_dir": str(root / "output"),
                    "frame_range": {"start": 1, "end": 2, "step": 1},
                },
            }
            addon._build_composite_graph(params)
            frame_paths[1].write_bytes(b"frame-2-replaced")

            with self.assertRaisesRegex(RuntimeError, "INPUT_SOURCE_HASH_MISMATCH:effect_render"):
                addon._composite_state(params["task_id"])

    def test_sequence_manifest_must_exactly_cover_declared_stride(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {frame: root / f"effect.{frame:04d}.exr" for frame in (1, 3, 5)}
            for frame, path in paths.items():
                path.write_bytes(f"frame-{frame}".encode("ascii"))

            def frame_record(frame):
                path = paths[frame]
                return {
                    "frame": frame,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            pattern = str(root / "effect.%04d.exr")
            incomplete = [frame_record(1)]
            incomplete_identity = addon._capture_composite_input_identity(
                "effect_render",
                {"path": pattern, "frames": incomplete},
                strict=False,
            )
            with self.assertRaisesRegex(ValueError, "frame_coverage"):
                addon._build_composite_graph(
                    {
                        "task_id": "incomplete-stride-task",
                        "schema_version": "2.0",
                        "inputs": [
                            {
                                "role": "effect_render",
                                "path": pattern,
                                "sha256": incomplete_identity["manifest_sha256"],
                                "frames": incomplete,
                            }
                        ],
                        "render": {
                            "output_dir": str(root / "incomplete"),
                            "frame_range": {"start": 1, "end": 5, "step": 2},
                        },
                    }
                )

            complete = [frame_record(frame) for frame in (1, 3, 5)]
            complete_identity = addon._capture_composite_input_identity(
                "effect_render",
                {"path": pattern, "frames": complete},
                strict=False,
            )
            built = addon._build_composite_graph(
                {
                    "task_id": "complete-stride-task",
                    "schema_version": "2.0",
                    "inputs": [
                        {
                            "role": "effect_render",
                            "path": pattern,
                            "sha256": complete_identity["manifest_sha256"],
                            "frames": complete,
                        }
                    ],
                    "render": {
                        "output_dir": str(root / "complete"),
                        "frame_range": {"start": 1, "end": 5, "step": 2},
                    },
                }
            )
            self.assertEqual(
                [
                    frame["frame"]
                    for frame in built["graph"]["input_source_identities"]["effect_render"]["frames"]
                ],
                [1, 3, 5],
            )

    def test_strict_v2_requires_source_identity_before_graph_mutation(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "INPUT_SOURCE_IDENTITY_REQUIRED:effect_render"):
                addon._build_composite_graph(
                    {
                        "task_id": "missing-hash-task",
                        "schema_version": "2.0",
                        "inputs": [{"role": "effect_render", "path": "/show/effect.exr"}],
                        "render": {"output_dir": directory},
                    }
                )
        self.assertEqual(fake_nuke.created, [])

    def test_final_write_tamper_and_preview_phase_delivery_are_rejected(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "final-binding-task",
                "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": directory,
                    "frame_range": {"start": 1, "end": 1, "step": 1},
                },
            }
            _freeze_test_inputs(params, directory)
            state = addon._build_composite_graph(params)["graph"]
            write = fake_nuke.toNode(state["write"])
            write["file"].setValue("/show/hijacked.%04d.exr")
            with self.assertRaisesRegex(RuntimeError, "FINAL_WRITE_SOURCE_DRIFT"):
                addon._composite_state(params["task_id"])
            with self.assertRaisesRegex(RuntimeError, "FINAL_WRITE_SOURCE_DRIFT"):
                addon._composite_action("agent.nuke.composite.deliver", params)

            write["file"].setValue(state["final_pattern"])
            fake_nuke.execute = lambda write, first, last, *rest: _fake_render(
                addon, write, first, last, *(rest[:1] or [1])
            )
            addon._composite_action("agent.nuke.composite.render_preview", params)
            preview_state = addon._composite_state(
                params["task_id"], required_write_phase="preview"
            )
            self.assertEqual(preview_state["final_write_binding"]["phase"], "preview")
            with self.assertRaisesRegex(RuntimeError, "FINAL_WRITE_SOURCE_DRIFT:final"):
                addon._composite_action("agent.nuke.composite.deliver", params)

    def test_hidden_output_drift_and_idempotent_new_output_dir_are_rejected(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        fake_nuke.execute = lambda write, first, last, *rest: _fake_render(
            addon, write, first, last, *(rest[:1] or [1])
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            params = {
                "task_id": "output-contract-task",
                "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": str(root / "intended"),
                    "frame_range": {"start": 1, "end": 3, "step": 1},
                },
            }
            state = addon._build_composite_graph(params)["graph"]
            different_params = {
                **params,
                "render": {
                    **params["render"],
                    "output_dir": str(root / "different"),
                },
            }
            self.assertFalse((root / "different").exists())
            with self.assertRaisesRegex(RuntimeError, "OUTPUT_SPEC_DRIFT"):
                addon._build_composite_graph(different_params)
            self.assertFalse((root / "different").exists())

            hijacked_dir = root / "hijacked"
            hijacked_pattern = str(hijacked_dir / "undeclared.%04d.exr")
            state["output_dir"] = str(hijacked_dir)
            state["final_pattern"] = hijacked_pattern
            state["final_write_binding"].update(
                {
                    "frozen_path": hijacked_pattern,
                    "readback_path": hijacked_pattern,
                }
            )
            fake_nuke.toNode(state["write"])["file"].setValue(hijacked_pattern)
            addon._persist_composite_state(state)

            with self.assertRaisesRegex(RuntimeError, "OUTPUT_SPEC_DRIFT"):
                addon._composite_action("agent.nuke.composite.render_final", params)

    def test_preview_variant_is_confined_to_declared_output_directory(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        fake_nuke.execute = lambda write, first, last, *rest: _fake_render(
            addon, write, first, last, *(rest[:1] or [1])
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "declared"
            params = {
                "task_id": "preview-confinement-task",
                "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
                "render": {"output_dir": str(output_dir)},
                "step_params": {"variant_id": "../../outside path"},
            }
            _freeze_test_inputs(params, directory)
            addon._build_composite_graph(params)
            rendered = addon._composite_action(
                "agent.nuke.composite.render_preview",
                params,
            )
            preview = Path(str(rendered["output_pattern"]))
            self.assertEqual(preview.parent.resolve(), output_dir.resolve())
            self.assertEqual(preview.name, "preview.outsidepath.%04d.exr")

    def test_preview_final_verify_deliver_chain_updates_write_binding(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        addon._read_image_metadata = lambda _path: {
            "width": 64,
            "height": 64,
            "channels": ["rgba.red"],
        }

        def execute(write, start, end, stride=1):
            for frame in range(start, end + 1, stride):
                path = addon._frame_path(str(write["file"].value()), frame)
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_structural_exr(path, f"render-{frame}".encode("ascii"))

        fake_nuke.execute = execute
        current_script = {"path": "/show/source.nk"}

        def save_script(path, overwrite=True):
            del overwrite
            Path(path).write_text("bridge nk", encoding="utf-8")
            current_script["path"] = str(Path(path).resolve())

        fake_nuke.scriptSaveAs = save_script
        fake_nuke.scriptOpen = lambda path: current_script.update(
            {"path": str(Path(path).resolve())}
        )
        fake_nuke.root = lambda: types.SimpleNamespace(
            name=lambda: current_script["path"]
        )
        fake_nuke.modified = lambda: False
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "phase-chain-task",
                "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
                "render": {
                    "output_dir": directory,
                    "frame_range": {"start": 1, "end": 1, "step": 1},
                },
            }
            _freeze_test_inputs(params, directory)
            state = addon._build_composite_graph(params)["graph"]
            with self.assertRaisesRegex(RuntimeError, "FINAL_VERIFICATION_REQUIRED"):
                addon._composite_action("agent.nuke.composite.deliver", params)
            addon._composite_action("agent.nuke.composite.render_preview", params)
            preview = addon._composite_action("agent.nuke.composite.verify_preview", params)
            self.assertTrue(preview["gates"][0]["passed"])
            self.assertEqual(state["final_write_binding"]["phase"], "preview")

            addon._composite_action("agent.nuke.composite.render_final", params)
            with self.assertRaisesRegex(RuntimeError, "FINAL_VERIFICATION_REQUIRED"):
                addon._composite_action("agent.nuke.composite.deliver", params)
            final = addon._composite_action("agent.nuke.composite.verify_final", params)
            self.assertTrue(next(g for g in final["gates"] if g["name"] == "composite_final_artifacts")["passed"])
            delivered = addon._composite_action("agent.nuke.composite.deliver", params)
            self.assertTrue(next(g for g in delivered["gates"] if g["name"] == "editable_composite_script")["passed"])
            self.assertEqual(state["final_write_binding"]["phase"], "final")
            self.assertEqual(
                fake_nuke.toNode(state["write"])["file"].value(),
                state["final_pattern"],
            )
            addon._COMPOSITES.clear()
            reopened_delivery = addon._composite_action(
                "agent.nuke.composite.deliver",
                params,
            )
            self.assertTrue(
                next(
                    gate
                    for gate in reopened_delivery["gates"]
                    if gate["name"] == "editable_composite_script"
                )["passed"]
            )
            blur = fake_nuke.toNode(state["graph_nodes"]["effect_blur"])
            blur["size"]._expression = True
            with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
                addon._composite_action("agent.nuke.composite.deliver", params)
            blur["size"]._expression = False
            write_file = fake_nuke.toNode(state["write"])["file"]
            write_file._animated = True
            with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
                addon._composite_action("agent.nuke.composite.deliver", params)
            write_file._animated = False
            effect_file = fake_nuke.toNode(state["input_nodes"]["effect_render"])["file"]
            effect_file._expression = True
            with self.assertRaisesRegex(RuntimeError, "PARAMETER_STATE_UNSUPPORTED"):
                addon._composite_action("agent.nuke.composite.deliver", params)

    def test_delivery_fails_closed_on_save_callback_dirty_tamper_or_reopen_failure(self) -> None:
        for scenario, expected_error in (
            ("topology_tamper", "DELIVERY_POST_SAVE_AUDIT_FAILED"),
            ("dirty_callback", "DELIVERY_POST_SAVE_DIRTY"),
            ("reopen_failure", "DELIVERY_REOPEN_FAILED"),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                addon = load_addon()
                fake_nuke = FakeBuildNuke()
                sys.modules["nuke"] = fake_nuke
                addon._read_image_metadata = lambda _path: {
                    "width": 64,
                    "height": 64,
                    "channels": ["rgba.red"],
                }

                def execute(write, start, end, stride=1):
                    for frame in range(start, end + 1, stride):
                        path = addon._frame_path(str(write["file"].value()), frame)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _write_structural_exr(path, f"render-{frame}".encode("ascii"))

                fake_nuke.execute = execute
                current_script = {"path": "/show/source.nk"}
                dirty = {"value": False}
                params = {
                    "task_id": f"delivery-post-save-{scenario}",
                    "inputs": [
                        {"role": "effect_render", "path": "/show/effect.%04d.exr"},
                        {"role": "reference", "path": "/show/reference.%04d.exr"},
                    ],
                    "render": {
                        "output_dir": directory,
                        "frame_range": {"start": 1, "end": 1, "step": 1},
                    },
                }
                _freeze_test_inputs(params, directory)
                state = addon._build_composite_graph(params)["graph"]
                addon._composite_action("agent.nuke.composite.render_final", params)
                addon._composite_action("agent.nuke.composite.verify_final", params)

                def save_script(path, overwrite=True):
                    del overwrite
                    if scenario == "topology_tamper":
                        final = fake_nuke.toNode(state["graph_nodes"]["final_image"])
                        reference = fake_nuke.toNode(state["input_nodes"]["reference"])
                        final.setInput(0, reference)
                    Path(path).write_text("bridge nk", encoding="utf-8")
                    current_script["path"] = str(Path(path).resolve())
                    if scenario == "dirty_callback":
                        dirty["value"] = True

                def open_script(path):
                    if scenario == "reopen_failure":
                        raise RuntimeError("injected reopen failure")
                    current_script["path"] = str(Path(path).resolve())

                fake_nuke.scriptSaveAs = save_script
                fake_nuke.scriptOpen = open_script
                fake_nuke.root = lambda: types.SimpleNamespace(
                    name=lambda: current_script["path"]
                )
                fake_nuke.modified = lambda: dirty["value"]

                with self.assertRaisesRegex(RuntimeError, expected_error):
                    addon._composite_action("agent.nuke.composite.deliver", params)

    def test_legacy_delivery_reopens_and_rejects_callback_tamper_or_stale_nk(self) -> None:
        for scenario in ("valid", "topology_tamper", "stale_file"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                addon = load_addon()
                fake_nuke = FakeBuildNuke()
                sys.modules["nuke"] = fake_nuke
                addon._read_image_metadata = lambda _path: {
                    "width": 64,
                    "height": 64,
                    "channels": ["rgba.red"],
                }
                root = Path(directory)
                source = root / "effect.exr"
                source.write_bytes(b"frozen effect")
                output = root / "output"
                params = {
                    "task_id": f"legacy-delivery-{scenario}",
                    "schema_version": "2.0",
                    "inputs": [
                        {
                            "role": "effect_render",
                            "path": str(source),
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    ],
                    "render": {
                        "output_dir": str(output),
                        "frame_range": {"start": 1, "end": 1, "step": 1},
                    },
                }

                def execute(write, start, end, stride=1):
                    for frame in range(start, end + 1, stride):
                        path = addon._frame_path(str(write["file"].value()), frame)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _write_structural_exr(path, f"render-{frame}".encode("ascii"))

                fake_nuke.execute = execute
                state = addon._delivery_action("agent.nuke.build_graph", params)["graph"]
                with self.assertRaisesRegex(RuntimeError, "FINAL_VERIFICATION_REQUIRED"):
                    addon._delivery_action("agent.nuke.deliver", params)
                addon._delivery_action("agent.nuke.render_final", params)
                verified = addon._delivery_action("agent.nuke.verify_final", params)
                self.assertTrue(verified["gates"][0]["passed"])

                script_path = output / (
                    "nuke_delivery_{}.nk".format(addon._task_key(params["task_id"]))
                )
                current_script = {"path": "/show/source.nk"}
                if scenario == "stale_file":
                    script_path.write_text("old nk", encoding="utf-8")
                    old_ns = script_path.stat().st_mtime_ns
                    os.utime(script_path, ns=(old_ns, old_ns))

                def save_script(path, overwrite=True):
                    del overwrite
                    if scenario == "stale_file":
                        return
                    if scenario == "topology_tamper":
                        fake_nuke.toNode(state["write"]).setInput(0, None)
                    Path(path).write_text("new nk", encoding="utf-8")
                    current_script["path"] = str(Path(path).resolve())

                fake_nuke.scriptSaveAs = save_script
                fake_nuke.scriptOpen = lambda path: current_script.update(
                    {"path": str(Path(path).resolve())}
                )
                fake_nuke.root = lambda: types.SimpleNamespace(
                    name=lambda: current_script["path"]
                )
                fake_nuke.modified = lambda: False

                if scenario == "valid":
                    # A resumed TaskEngine may enter deliver in a fresh addon
                    # process after build/render/verify checkpoints completed.
                    addon._DELIVERIES.clear()
                    delivered = addon._delivery_action("agent.nuke.deliver", params)
                    gate = delivered["gates"][0]
                    self.assertTrue(gate["passed"])
                    self.assertTrue(gate["post_save_reopen_verified"])
                    self.assertEqual(gate["sha256"], addon._artifact(script_path)["sha256"])
                else:
                    error = (
                        "DELIVERY_POST_SAVE_AUDIT_FAILED"
                        if scenario == "topology_tamper"
                        else "DELIVERY_ARTIFACT_STALE"
                    )
                    with self.assertRaisesRegex(RuntimeError, error):
                        addon._delivery_action("agent.nuke.deliver", params)

    def test_preview_persistence_failure_restores_write_binding_and_metadata(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        fake_nuke.execute = lambda write, first, last, *rest: _fake_render(
            addon, write, first, last, *(rest[:1] or [1])
        )
        with tempfile.TemporaryDirectory() as directory:
            params = {
                "task_id": "preview-rollback-task",
                "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
                "render": {"output_dir": directory},
            }
            _freeze_test_inputs(params, directory)
            state = addon._build_composite_graph(params)["graph"]
            write = fake_nuke.toNode(state["write"])
            before_file = write["file"].value()
            before_metadata = write["bridge_state_json"].value()
            before_binding = dict(state["final_write_binding"])
            original_persist = addon._persist_composite_state

            def persist_then_fail(value):
                original_persist(value)
                raise RuntimeError("injected persist failure")

            with mock.patch.object(addon, "_persist_composite_state", persist_then_fail):
                with self.assertRaisesRegex(RuntimeError, "injected persist failure"):
                    addon._composite_action("agent.nuke.composite.render_preview", params)

            self.assertEqual(write["file"].value(), before_file)
            self.assertEqual(write["bridge_state_json"].value(), before_metadata)
            self.assertEqual(state["final_write_binding"], before_binding)

    def test_reference_read_knob_drift_fails_cached_and_hidden_state_validation(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            built = addon._build_composite_graph(
                {
                    "task_id": "reference-drift-task",
                    "inputs": [
                        {"role": "effect_render", "path": "/show/effect.%04d.exr"},
                        {"role": "reference", "path": "/show/reference-a.%04d.exr"},
                    ],
                    "render": {"output_dir": directory},
                }
            )
        reference_name = built["graph"]["input_nodes"]["reference"]
        fake_nuke.toNode(reference_name)["file"].setValue("/show/reference-b.####.exr")

        with self.assertRaisesRegex(RuntimeError, "REFERENCE_SOURCE_DRIFT:reference"):
            addon._composite_state("reference-drift-task")
        addon._COMPOSITES.clear()
        with self.assertRaisesRegex(RuntimeError, "REFERENCE_SOURCE_DRIFT:reference"):
            addon._composite_state("reference-drift-task")

    def test_drifted_reference_readback_exposes_untagged_new_source_upstream(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            built = addon._build_composite_graph(
                {
                    "task_id": "reference-upstream-drift-task",
                    "inputs": [
                        {"role": "effect_render", "path": "/show/effect.%04d.exr"},
                        {"role": "reference", "path": "/show/reference-a.%04d.exr"},
                    ],
                    "render": {"output_dir": directory},
                }
            )
        state = built["graph"]
        reference = fake_nuke.toNode(state["input_nodes"]["reference"])
        reference["file"].setValue("/show/reference-b.####.exr")
        untagged_b = FakeNode(
            "UNTAGGED_REFERENCE_B",
            knobs={"file": FakeKnob("/show/reference-b.%04d.exr")},
            node_class="Read",
        )
        fake_nuke.created.append(untagged_b)
        fake_nuke._by_name[untagged_b.name()] = untagged_b
        final = fake_nuke.toNode(state["graph_nodes"]["final_image"])
        final.setInput(0, untagged_b)

        topology = addon._validate_composite_topology(state)["topology"]
        self.assertFalse(topology["passed"])
        self.assertIn("REFERENCE_SOURCE_DRIFT:reference", topology["errors"])
        lineage = addon._audit_composite_lineage(state)["lineage"]
        self.assertFalse(lineage["passed"])
        self.assertIn("UNTAGGED_REFERENCE_B", lineage["violations"])
        detail = next(
            item for item in lineage["violation_details"]
            if item["node"] == "UNTAGGED_REFERENCE_B"
        )
        self.assertIn("reference_readback_path", detail["reasons"])

    def test_copied_reference_bytes_cannot_bypass_lineage_by_changing_path(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effect = root / "effect.exr"
            reference = root / "reference.exr"
            copied = root / "renamed-copy.exr"
            different = root / "different.exr"
            effect.write_bytes(b"effect")
            reference.write_bytes(b"frozen-reference")
            copied.write_bytes(reference.read_bytes())
            different.write_bytes(b"different-content")
            params = {
                "task_id": "reference-content-task",
                "schema_version": "2.0",
                "inputs": [
                    {
                        "role": "effect_render",
                        "path": str(effect),
                        "sha256": hashlib.sha256(effect.read_bytes()).hexdigest(),
                    },
                    {
                        "role": "reference",
                        "path": str(reference),
                        "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                    },
                ],
                "render": {"output_dir": str(root / "output")},
            }
            state = addon._build_composite_graph(params)["graph"]
            final = fake_nuke.toNode(state["graph_nodes"]["final_image"])
            copied_read = FakeNode(
                "COPIED_REFERENCE",
                knobs={"file": FakeKnob(str(copied))},
                node_class="Read",
            )
            final.setInput(0, copied_read)
            copied_audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertFalse(copied_audit["passed"])
            copied_detail = next(
                item for item in copied_audit["violation_details"]
                if item["node"] == "COPIED_REFERENCE"
            )
            self.assertIn("frozen_reference_content", copied_detail["reasons"])

            different_read = FakeNode(
                "DIFFERENT_INPUT",
                knobs={"file": FakeKnob(str(different))},
                node_class="Read",
            )
            final.setInput(0, different_read)
            different_audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertTrue(different_audit["passed"])

    def test_copied_reference_symlink_cannot_bypass_lineage(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effect = root / "effect.exr"
            reference = root / "reference.exr"
            copied = root / "renamed-copy.exr"
            alias = root / "alias.exr"
            effect.write_bytes(b"effect")
            reference.write_bytes(b"frozen-reference")
            copied.write_bytes(reference.read_bytes())
            if not fixture_symlink(self, alias, copied):
                return
            params = {
                "task_id": "reference-content-symlink-task",
                "schema_version": "2.0",
                "inputs": [
                    {
                        "role": "effect_render",
                        "path": str(effect),
                        "sha256": hashlib.sha256(effect.read_bytes()).hexdigest(),
                    },
                    {
                        "role": "reference",
                        "path": str(reference),
                        "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                    },
                ],
                "render": {"output_dir": str(root / "output")},
            }
            state = addon._build_composite_graph(params)["graph"]
            final = fake_nuke.toNode(state["graph_nodes"]["final_image"])
            alias_read = FakeNode(
                "COPIED_REFERENCE_SYMLINK",
                knobs={"file": FakeKnob(str(alias))},
                node_class="Read",
            )
            final.setInput(0, alias_read)

            audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertFalse(audit["passed"])
            detail = next(
                item for item in audit["violation_details"]
                if item["node"] == "COPIED_REFERENCE_SYMLINK"
            )
            self.assertIn("source_symlink_untrusted", detail["reasons"])
            self.assertEqual(
                detail["reference_content"]["untrusted_symlink_paths"],
                [str(alias)],
            )

    def test_sequence_reference_content_requires_the_entire_ordered_manifest(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write_sequence(prefix, payloads):
                paths = []
                for frame, payload in enumerate(payloads, start=1):
                    path = root / f"{prefix}.{frame:04d}.exr"
                    path.write_bytes(payload)
                    paths.append(path)
                pattern = str(root / f"{prefix}.%04d.exr")
                frames = [
                    {
                        "frame": frame,
                        "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for frame, path in enumerate(paths, start=1)
                ]
                identity = addon._capture_composite_input_identity(
                    prefix,
                    {"path": pattern, "frames": frames},
                    strict=False,
                )
                return pattern, frames, identity["manifest_sha256"]

            effect_pattern, effect_frames, effect_manifest = write_sequence(
                "effect", [b"effect-1", b"effect-2"]
            )
            reference_pattern, reference_frames, reference_manifest = write_sequence(
                "reference", [b"common-black-frame", b"reference-2"]
            )
            partial_pattern, _partial_frames, _partial_manifest = write_sequence(
                "partial-copy", [b"common-black-frame", b"different-2"]
            )
            full_pattern, _full_frames, _full_manifest = write_sequence(
                "full-copy", [b"common-black-frame", b"reference-2"]
            )
            static_frame_copy = root / "static-reference-frame-copy.exr"
            static_frame_copy.write_bytes(b"reference-2")
            params = {
                "task_id": "reference-sequence-content-task",
                "schema_version": "2.0",
                "inputs": [
                    {
                        "role": "effect_render",
                        "path": effect_pattern,
                        "sha256": effect_manifest,
                        "frames": effect_frames,
                    },
                    {
                        "role": "reference",
                        "path": reference_pattern,
                        "sha256": reference_manifest,
                        "frames": reference_frames,
                    },
                ],
                "render": {
                    "output_dir": str(root / "output"),
                    "frame_range": {"start": 1, "end": 2, "step": 1},
                },
            }
            state = addon._build_composite_graph(params)["graph"]
            final = fake_nuke.toNode(state["graph_nodes"]["final_image"])

            partial_read = FakeNode(
                "PARTIAL_REFERENCE_SEQUENCE",
                knobs={"file": FakeKnob(partial_pattern)},
                node_class="Read",
            )
            final.setInput(0, partial_read)
            partial_audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertTrue(partial_audit["passed"])

            static_copy_read = FakeNode(
                "STATIC_REFERENCE_FRAME_COPY",
                knobs={"file": FakeKnob(str(static_frame_copy))},
                node_class="Read",
            )
            final.setInput(0, static_copy_read)
            static_copy_audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertFalse(static_copy_audit["passed"])
            static_detail = next(
                item for item in static_copy_audit["violation_details"]
                if item["node"] == "STATIC_REFERENCE_FRAME_COPY"
            )
            self.assertIn("frozen_reference_content", static_detail["reasons"])
            self.assertEqual(
                static_detail["reference_content"]["matched_reference_frame"]["frame"],
                2,
            )

            full_read = FakeNode(
                "FULL_REFERENCE_SEQUENCE",
                knobs={"file": FakeKnob(full_pattern)},
                node_class="Read",
            )
            final.setInput(0, full_read)
            full_audit = addon._audit_composite_lineage(state)["lineage"]
            self.assertFalse(full_audit["passed"])
            detail = next(
                item for item in full_audit["violation_details"]
                if item["node"] == "FULL_REFERENCE_SEQUENCE"
            )
            self.assertIn("frozen_reference_content", detail["reasons"])

    def test_open_script_invalidates_registries_and_restores_state_b_from_hidden_metadata(self) -> None:
        addon = load_addon()
        fake_nuke = FakeBuildNuke()
        sys.modules["nuke"] = fake_nuke
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_b = root / "state-b-output"
            params_b = {
                "task_id": "same-task-same-topology",
                "inputs": [
                    {"role": "effect_render", "path": "/show/effect-b.%04d.exr"},
                    {"role": "reference", "path": "/show/reference-b.####.exr"},
                ],
                "render": {
                    "output_dir": str(output_b),
                    "frame_range": {"start": 11, "end": 19, "step": 2},
                },
            }
            state_b = addon._build_composite_graph(params_b)["graph"]
            script_b = root / "state-b.nk"
            script_b.write_text("state b", encoding="utf-8")

            state_a = {
                **state_b,
                "output_dir": str(root / "state-a-output"),
                "final_pattern": str(root / "state-a-output" / "final.%04d.exr"),
                "frame_range": {"start": 1, "end": 3, "step": 1},
                "reference_source_paths": ["/show/reference-a.%04d.exr"],
                "reference_source_bindings": {
                    "reference": {
                        "node": state_b["input_nodes"]["reference"],
                        "frozen_path": "/show/reference-a.%04d.exr",
                        "readback_path": "/show/reference-a.%04d.exr",
                    }
                },
            }
            addon._COMPOSITES[params_b["task_id"]] = state_a
            addon._DELIVERIES["old-delivery"] = {"write": "OLD_WRITE"}
            addon._RENDERS["old-render"] = {"node": "OLD_WRITE"}
            opened: list[str] = []
            fake_nuke.root = lambda: types.SimpleNamespace(
                name=lambda: str(root / "state-a.nk")
            )
            fake_nuke.modified = lambda: False
            fake_nuke.scriptOpen = lambda path: opened.append(path)

            reopen = addon.dispatch("open_script", {"path": str(script_b)})

        self.assertEqual(opened, [str(script_b.resolve())])
        self.assertTrue(reopen["registry_cache_invalidated"])
        self.assertEqual(
            reopen["registry_entries"]["before"],
            {"composites": 1, "deliveries": 1, "renders": 1},
        )
        self.assertEqual(
            reopen["registry_entries"]["after"],
            {"composites": 0, "deliveries": 0, "renders": 0},
        )
        self.assertEqual(addon._DELIVERIES, {})
        self.assertEqual(addon._RENDERS, {})

        restored = addon._composite_state(params_b["task_id"])
        for field in (
            "output_dir",
            "final_pattern",
            "frame_range",
            "reference_source_paths",
            "reference_source_bindings",
        ):
            self.assertEqual(restored[field], state_b[field])
        self.assertNotEqual(restored["output_dir"], state_a["output_dir"])

    def test_open_script_never_overwrites_dirty_or_unknown_modified_state(self) -> None:
        addon = load_addon()
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "same.nk"
            script.write_text("Root {}", encoding="utf-8")
            opened: list[str] = []
            base = {
                "root": lambda: types.SimpleNamespace(name=lambda: str(script)),
                "scriptOpen": lambda path: opened.append(path),
            }
            sys.modules["nuke"] = types.SimpleNamespace(
                **base,
                modified=lambda: True,
            )
            with self.assertRaisesRegex(ValueError, "SCENE_STATE_DRIFT"):
                addon.dispatch("open_script", {"path": str(script)})

            def modified_error():
                raise RuntimeError("host query failed")

            sys.modules["nuke"] = types.SimpleNamespace(
                **base,
                modified=modified_error,
            )
            with self.assertRaisesRegex(ValueError, "SCENE_STATE_DRIFT"):
                addon.dispatch("open_script", {"path": str(script)})

        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
