"""C2 recipe requests keep persistent step identity across adapter reconnects."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import hashlib
import unittest

from dcc_task_runtime import TaskSpec
from nuke_bridge.recipes import ReferenceCompositeRecipe, RenderDeliveryRecipe
from nuke_bridge.tasks import NukeCommandAdapter


class RecordingHost:
    def __init__(self):
        self.calls = []

    def call(self, command, params=None):
        self.calls.append((command, dict(params or {})))
        gates = {
            "agent.nuke.render_preview": "preview_rendered",
            "agent.nuke.render_final": "final_rendered",
            "agent.nuke.composite.render_preview": "composite_preview_rendered",
            "agent.nuke.composite.render_final": "composite_final_rendered",
        }
        return {"gates": [{"name": gates[command], "kind": "operation", "passed": True}]}


class NukeRecipeRequestIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "effect.%03d.exr"
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        self.frames = []
        for frame in (1,2):
            path = Path(str(self.source) % frame)
            path.write_bytes(encode_tiny_exr(float(frame)))
            self.frames.append({"frame":frame,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})

    def render_steps(self):
        for recipe in (RenderDeliveryRecipe(), ReferenceCompositeRecipe()):
            spec = TaskSpec(
                task_type=recipe.identifier, intent="C2 software request identity",
                target_application="nuke",
                inputs=({"role": "effect_render", "path": str(self.source),"frames":self.frames},),
                render={"frame_range": {"start": 1, "end": 2, "step": 1}},
            )
            for step in recipe.steps(spec, {}):
                if step.phase in {"PREVIEW_RENDER", "FINAL_RENDER"}:
                    yield spec, step

    def test_recipe_render_steps_keep_request_identity_after_reconnect(self):
        with tempfile.TemporaryDirectory() as temporary:
            task = Path(temporary) / "persistent-task"
            identities = []
            for spec, step in self.render_steps():
                with self.subTest(action=step.action, step=step.identifier):
                    first, second = RecordingHost(), RecordingHost()
                    NukeCommandAdapter(first).execute(step, spec, task)
                    NukeCommandAdapter(second).execute(step, spec, task)
                    request = first.calls[-1][1].get("request_id")
                    self.assertIsInstance(request, str)
                    self.assertTrue(request)
                    self.assertEqual(second.calls[-1][1].get("request_id"), request)
                    identities.append(request)
            self.assertEqual(len(set(identities)), len(identities), "each persistent render step has its own request")

    def test_new_task_or_explicit_iteration_produces_a_new_request(self):
        spec, step = next(self.render_steps())
        host = RecordingHost()
        adapter = NukeCommandAdapter(host)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            adapter.execute(step, spec, base / "task-one")
            adapter.execute(step, spec, base / "task-two")
            explicit = replace(step, params={**step.params, "request_id": "controller-next-round"})
            adapter.execute(explicit, spec, base / "task-one")
        requests = [params.get("request_id") for _, params in host.calls]
        self.assertEqual(len(set(requests)), 3)
        self.assertEqual(requests[-1], "controller-next-round")

    def test_changed_content_is_rejected_by_controller_before_host_dispatch(self):
        spec, step = next(self.render_steps())
        host = RecordingHost()
        with tempfile.TemporaryDirectory() as temporary:
            task = Path(temporary) / "persistent-task"
            adapter = NukeCommandAdapter(host)
            adapter.execute(step, spec, task)
            request = host.calls[-1][1]["request_id"]
            with self.assertRaisesRegex(RuntimeError, "CONTENT_CHANGED"):
                adapter.execute(replace(step, params={**step.params, "frame": 2}), spec, task)
            self.assertEqual(len(host.calls), 1)
            self.assertTrue(request)

    def test_invalid_explicit_request_is_rejected_before_host_call(self):
        spec, step = next(self.render_steps())
        for invalid in (None, True, "bad/request", "x", "x" * 121):
            with self.subTest(request_id=invalid), tempfile.TemporaryDirectory() as temporary:
                host = RecordingHost()
                explicit = replace(step, params={**step.params, "request_id": invalid})
                with self.assertRaisesRegex(ValueError, "request_id"):
                    NukeCommandAdapter(host).execute(explicit, spec, Path(temporary) / "task")
                self.assertEqual(host.calls, [])


if __name__ == "__main__":
    unittest.main()
