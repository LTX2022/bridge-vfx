from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from dcc_task_runtime import TaskSpec
from nuke_bridge.recipes import ReferenceCompositeRecipe, RenderDeliveryRecipe
from nuke_bridge.tasks import NukeCommandAdapter, task_service


ROOT = Path(__file__).resolve().parents[2]


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, command, _params=None):
        self.calls.append(command)
        if command == "capabilities.get":
            return {"nuke_version": "fake-17", "structured_composite": True}
        return {"gates": [{"name": command, "passed": True}]}


class FakeKnob:
    def __init__(self, value="") -> None:
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value) -> None:
        self._value = value


class FakeNode:
    def __init__(self, name: str, sources=None, metadata=None) -> None:
        self._name = name
        self._sources = list(sources or [])
        self._knobs = {key: FakeKnob(value) for key, value in dict(metadata or {}).items()}

    def name(self):
        return self._name

    def inputs(self):
        return len(self._sources)

    def input(self, index):
        return self._sources[index]

    def knob(self, name):
        return self._knobs.get(name)

    def __getitem__(self, name):
        return self._knobs[name]


def load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_nuke_addon", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NukeCompositeRecipeTests(unittest.TestCase):
    def test_build_adapter_requires_and_accepts_topology_verification(self) -> None:
        spec = TaskSpec(
            task_type="nuke.reference_composite",
            intent="verify strict composite build gates",
            target_application="nuke",
            inputs=({"role": "effect_render", "path": "/show/effect.%04d.exr"},),
            constraints={"run_mode": "diagnose"},
        )
        build_step = next(
            step
            for step in ReferenceCompositeRecipe().steps(spec, {})
            if step.action == "agent.nuke.composite.build_graph"
        )

        class BuildClient:
            def __init__(self, include_topology: bool) -> None:
                self.include_topology = include_topology

            def call(self, command, _params=None):
                self.asserted_command = command
                gates = [
                    {"name": "editable_native_composite_graph", "passed": True, "kind": "operation"},
                    {"name": "reference_isolated_from_final_write", "passed": True, "kind": "verification"},
                ]
                if self.include_topology:
                    gates.insert(
                        1,
                        {"name": "composite_topology_intact", "passed": True, "kind": "verification"},
                    )
                return {"gates": gates}

        with tempfile.TemporaryDirectory() as directory:
            accepted = NukeCommandAdapter(BuildClient(True)).execute(
                build_step,
                spec,
                Path(directory),
            )
            with self.assertRaisesRegex(RuntimeError, "gate policy failed"):
                NukeCommandAdapter(BuildClient(False)).execute(
                    build_step,
                    spec,
                    Path(directory),
                )

        self.assertEqual(
            {gate["name"] for gate in accepted["gates"]},
            {
                "editable_native_composite_graph",
                "composite_topology_intact",
                "reference_isolated_from_final_write",
            },
        )

    def test_hand_built_specs_are_bounded_before_recipe_frame_expansion(self) -> None:
        delivery_spec = TaskSpec(
            task_type="nuke.render_delivery",
            intent="render a hand-built sequence",
            target_application="nuke",
            render={"frame_range": {"start": 1, "end": 10_001, "step": 1}},
        )
        composite_spec = TaskSpec(
            task_type="nuke.reference_composite",
            intent="composite a hand-built sequence",
            target_application="nuke",
            inputs=({"role": "effect_render", "path": "/show/effect.%04d.exr"},),
            constraints={"run_mode": "diagnose"},
            render={"frame_range": {"start": 1, "end": 10_001, "step": 1}},
        )
        for recipe, spec in (
            (RenderDeliveryRecipe(), delivery_spec),
            (ReferenceCompositeRecipe(), composite_spec),
        ):
            with self.subTest(recipe=recipe.identifier):
                with self.assertRaisesRegex(ValueError, "at most 10000 frames"):
                    recipe.steps(spec, {})

        boundary = TaskSpec(
            task_type="nuke.render_delivery",
            intent="render the maximum bounded sequence",
            target_application="nuke",
            render={"frame_range": {"start": 1, "end": 10_000, "step": 1}},
        )
        steps = RenderDeliveryRecipe().steps(boundary, {})
        self.assertEqual(
            sum(step.action == "agent.nuke.render_final" for step in steps),
            10_000,
        )

    def test_recipe_uses_only_structured_actions_and_honors_stride(self) -> None:
        client = RecordingClient()
        spec = {
            "schema_version": "2.0",
            "task_type": "nuke.reference_composite",
            "intent": "composite a smoke element without contaminating it with the reference",
            "target": {"application": "nuke"},
            "inputs": [
                {"role": "effect_render", "path": "/show/fx.%04d.exr"},
                {"role": "reference", "path": "/show/reference.png"},
            ],
            "render": {"frame_range": {"start": 1, "end": 5, "step": 2}},
        }
        with tempfile.TemporaryDirectory() as directory:
            plan = task_service(client, Path(directory)).plan(spec)
        actions = [item["action"] for item in plan["steps"]]
        rendered = [item["params"]["frame"] for item in plan["steps"] if item["action"] == "agent.nuke.composite.render_final"]
        self.assertEqual(rendered, [1, 3, 5])
        self.assertIn("agent.nuke.composite.audit_lineage", actions)
        self.assertNotIn("nuke_run", actions)
        self.assertTrue(all(action.startswith("agent.nuke.composite.") for action in actions))

    def test_recipe_requires_explicit_effect_render_role(self) -> None:
        spec = {
            "task_type": "nuke.reference_composite",
            "intent": "bad inputs",
            "target": {"application": "nuke"},
            "inputs": [{"role": "reference", "path": "/show/reference.png"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "effect_render"):
                task_service(RecordingClient(), Path(directory)).plan(spec)

    def test_candidate_preview_requires_and_applies_one_candidate(self) -> None:
        base = {
            "task_type": "nuke.reference_composite",
            "intent": "preview one bounded composite repair",
            "target": {"application": "nuke"},
            "inputs": [{"role": "effect_render", "path": "/show/effect.%04d.exr"}],
            "constraints": {"run_mode": "candidate_preview"},
            "render": {"frame_range": {"start": 1, "end": 3, "step": 1}},
        }
        with tempfile.TemporaryDirectory() as directory:
            service = task_service(RecordingClient(), Path(directory))
            with self.assertRaisesRegex(ValueError, "non-empty composite candidate"):
                service.plan(base)
            spec = {
                **base,
                "constraints": {
                    "run_mode": "candidate_preview",
                    "composite_candidate_patch": {"controls": {"blur_size": 1.5}},
                },
            }
            plan = service.plan(spec)
        actions = [item["action"] for item in plan["steps"]]
        self.assertEqual(actions.count("agent.nuke.composite.apply_patch"), 1)
        self.assertNotIn("agent.nuke.composite.render_final", actions)
        self.assertNotIn("agent.nuke.composite.deliver", actions)


class NukeReferenceLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_nuke = sys.modules.get("nuke")

    def tearDown(self) -> None:
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def test_reference_branch_is_not_upstream_of_final_write(self) -> None:
        addon = load_addon()
        effect = FakeNode("EFFECT", metadata={"bridge_input_role": "effect_render"})
        reference = FakeNode("REFERENCE", metadata={"bridge_input_role": "reference"})
        final = FakeNode("FINAL", [effect], {"bridge_graph_role": "final_image"})
        write = FakeNode("WRITE", [final], {"bridge_graph_role": "final_write"})
        nodes = {node.name(): node for node in [effect, reference, final, write]}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        result = addon._audit_composite_lineage({"write": "WRITE"})
        self.assertTrue(result["lineage"]["passed"])
        self.assertNotIn("REFERENCE", result["lineage"]["upstream"])

    def test_reference_contamination_fails_lineage_gate(self) -> None:
        addon = load_addon()
        reference = FakeNode("REFERENCE", metadata={"bridge_input_role": "reference"})
        final = FakeNode("FINAL", [reference], {"bridge_graph_role": "final_image"})
        write = FakeNode("WRITE", [final], {"bridge_graph_role": "final_write"})
        nodes = {node.name(): node for node in [reference, final, write]}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        result = addon._audit_composite_lineage({"write": "WRITE"})
        self.assertFalse(result["lineage"]["passed"])
        self.assertEqual(result["lineage"]["violations"], ["REFERENCE"])

    def test_untagged_read_of_frozen_reference_path_fails_lineage_gate(self) -> None:
        addon = load_addon()
        untagged = FakeNode("UNTAGGED_READ", metadata={"file": "/show/reference.png"})
        final = FakeNode("FINAL", [untagged], {"bridge_graph_role": "final_image"})
        write = FakeNode("WRITE", [final], {"bridge_graph_role": "final_write", "file": "/show/final.%04d.exr"})
        nodes = {node.name(): node for node in [untagged, final, write]}
        sys.modules["nuke"] = types.SimpleNamespace(toNode=nodes.get, root=lambda: None)
        result = addon._audit_composite_lineage(
            {
                "write": "WRITE",
                "reference_source_paths": ["/show/reference.png"],
                "frame_range": {"start": 1, "end": 1, "step": 1},
            }
        )
        self.assertFalse(result["lineage"]["passed"])
        self.assertEqual(result["lineage"]["violations"], ["UNTAGGED_READ"])
        self.assertEqual(result["lineage"]["violation_details"][0]["reasons"], ["frozen_reference_path"])

    def test_hidden_metadata_rebuilds_state_after_restart(self) -> None:
        addon = load_addon()
        effect_path = "/show/effect.%04d.exr"
        effect = FakeNode(
            "EFFECT",
            metadata={
                "bridge_task_id": "task-restart",
                "bridge_input_role": "effect_render",
                "bridge_graph_role": "input_effect_render",
                "file": effect_path,
            },
        )
        chain = []
        graph_nodes = {"input_effect_render": "EFFECT"}
        current = effect
        for graph_role in (
            "effect_blur",
            "effect_defocus",
            "effect_denoise",
            "effect_sharpen",
            "effect_glow",
            "effect_contrast",
            "effect_edge",
            "effect_grain",
            "effect_premult",
        ):
            node = FakeNode(
                graph_role.upper(),
                [current],
                {"bridge_task_id": "task-restart", "bridge_graph_role": graph_role},
            )
            chain.append(node)
            graph_nodes[graph_role] = node.name()
            current = node
        final = FakeNode(
            "FINAL",
            [current],
            {"bridge_task_id": "task-restart", "bridge_graph_role": "final_image"},
        )
        graph_nodes["final_image"] = "FINAL"
        graph_nodes["final_write"] = "WRITE"
        hidden_state = {
            "task_id": "task-restart",
            "schema_version": "1.0",
            "write": "WRITE",
            "input_nodes": {"effect_render": "EFFECT"},
            "graph_nodes": graph_nodes,
            "final_pattern": "/show/final.%04d.exr",
            "input_source_paths": {"effect_render": effect_path},
            "input_source_bindings": {
                "effect_render": {
                    "node": "EFFECT",
                    "frozen_path": effect_path,
                    "readback_path": effect_path,
                }
            },
            "input_source_identities": {
                "effect_render": {
                    "mode": "unfrozen",
                    "status": "unfrozen_legacy",
                    "declared_sha256": "",
                }
            },
            "input_identity_policy": "legacy",
            "reference_source_paths": [],
            "reference_source_bindings": {},
            "final_write_binding": {
                "node": "WRITE",
                "phase": "final",
                "frozen_path": "/show/final.%04d.exr",
                "readback_path": "/show/final.%04d.exr",
            },
        }
        write = FakeNode(
            "WRITE",
            [final],
            {
                "bridge_task_id": "task-restart",
                "bridge_graph_role": "final_write",
                "bridge_state_json": json.dumps(hidden_state, sort_keys=True),
                "file": "/show/final.%04d.exr",
            },
        )
        nodes = {node.name(): node for node in [effect, *chain, final, write]}
        sys.modules["nuke"] = types.SimpleNamespace(
            toNode=nodes.get,
            allNodes=lambda recurseGroups=True: list(nodes.values()),
            root=lambda: None,
        )
        addon._COMPOSITES.clear()
        state = addon._composite_state("task-restart")
        self.assertEqual(state["write"], "WRITE")
        self.assertEqual(state["input_nodes"], {"effect_render": "EFFECT"})
        self.assertEqual(state["graph_nodes"]["final_write"], "WRITE")
        self.assertTrue(addon._audit_composite_lineage(state)["lineage"]["passed"])

    def test_legacy_hidden_state_without_source_bindings_fails_closed(self) -> None:
        addon = load_addon()
        effect = FakeNode(
            "LEGACY_EFFECT",
            metadata={
                "bridge_task_id": "legacy-task",
                "bridge_input_role": "effect_render",
                "bridge_graph_role": "input_effect_render",
                "file": "/show/effect.%04d.exr",
            },
        )
        chain = []
        current = effect
        graph_nodes = {"input_effect_render": effect.name()}
        for graph_role in (
            "effect_blur",
            "effect_defocus",
            "effect_denoise",
            "effect_sharpen",
            "effect_glow",
            "effect_contrast",
            "effect_edge",
            "effect_grain",
            "effect_premult",
        ):
            node = FakeNode(
                "LEGACY_" + graph_role.upper(),
                [current],
                {"bridge_task_id": "legacy-task", "bridge_graph_role": graph_role},
            )
            chain.append(node)
            graph_nodes[graph_role] = node.name()
            current = node
        final = FakeNode(
            "LEGACY_FINAL",
            [current],
            {"bridge_task_id": "legacy-task", "bridge_graph_role": "final_image"},
        )
        graph_nodes["final_image"] = final.name()
        graph_nodes["final_write"] = "LEGACY_WRITE"
        write = FakeNode(
            "LEGACY_WRITE",
            [final],
            {
                "bridge_task_id": "legacy-task",
                "bridge_graph_role": "final_write",
                "bridge_state_json": json.dumps(
                    {
                        "task_id": "legacy-task",
                        "write": "LEGACY_WRITE",
                        "input_nodes": {"effect_render": effect.name()},
                        "graph_nodes": graph_nodes,
                        "final_pattern": "/show/final.%04d.exr",
                    }
                ),
                "file": "/show/final.%04d.exr",
            },
        )
        nodes = {node.name(): node for node in [effect, *chain, final, write]}
        sys.modules["nuke"] = types.SimpleNamespace(
            toNode=nodes.get,
            allNodes=lambda recurseGroups=True: list(nodes.values()),
            root=lambda: None,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "INPUT_SOURCE_(?:DRIFT|IDENTITY_MISSING):effect_render",
        ):
            addon._composite_state("legacy-task")


if __name__ == "__main__":
    unittest.main()
