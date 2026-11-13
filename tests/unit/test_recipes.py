from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from houdini_bridge.tasks import task_service as houdini_task_service
from nuke_bridge.tasks import task_service as nuke_task_service


class Client:
    def call(self, command, _params=None):
        if command == "capabilities.get":
            return {"version": "test"}
        return {"gates": [{"name": command, "passed": True}]}


class RecipeTests(unittest.TestCase):
    def test_houdini_recipe_has_real_work_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = houdini_task_service(Client(), Path(directory)).plan({"task_type": "houdini.model_to_karma", "intent": "make a crate", "target": {"application": "houdini"}})
            self.assertEqual(plan["steps"][0]["action"], "agent.model.probe")
            self.assertGreater(plan["total_units"], 90)

    def test_nuke_recipe_has_render_and_verify_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = nuke_task_service(Client(), Path(directory)).plan({"task_type": "nuke.render_delivery", "intent": "deliver an EXR", "target": {"application": "nuke"}})
            actions = [item["action"] for item in plan["steps"]]
            self.assertIn("agent.nuke.render_final", actions)
            self.assertIn("agent.nuke.verify_final", actions)

    def test_final_frames_are_durable_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = {"task_type": "houdini.model_to_karma", "intent": "make a crate", "target": {"application": "houdini"}, "render": {"frame_range": {"start": 1, "end": 3, "step": 1}}}
            plan = houdini_task_service(Client(), Path(directory)).plan(spec)
            frames = [item for item in plan["steps"] if item["action"] == "agent.model.render_final"]
            self.assertEqual([item["params"]["frame"] for item in frames], [1, 2, 3])
            self.assertEqual(len({item["id"] for item in frames}), 3)
