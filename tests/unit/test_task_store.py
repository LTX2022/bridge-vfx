from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from dcc_task_runtime import TaskEvent, TaskSpec, TaskState, TaskStore
from dcc_task_runtime import RecipeRegistry, Step, TaskEngine, compact_context


class TaskStoreTests(unittest.TestCase):
    def test_events_are_ordered_and_status_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            spec = TaskSpec.from_mapping({"task_type": "houdini.model_to_karma", "intent": "build a crate", "target": {"application": "houdini"}})
            task_id = store.create(spec, {"total_units": 4})
            event = TaskEvent(1, task_id, "PLAN", "probe", TaskState.RUNNING, 1, 4, 25.0, 10, "probe complete")
            store.append_event(task_id, event)
            self.assertEqual(store.load_status(task_id)["state"], "RUNNING")
            self.assertEqual(list(store.events(task_id)), [event.to_dict()])
            with self.assertRaises(ValueError):
                store.append_event(task_id, event)

    def test_engine_uses_durable_checkpoints(self) -> None:
        class Recipe:
            identifier = "houdini.test"

            def steps(self, _spec, _capabilities):
                return [Step("probe", "PROBE", "probe"), Step("build", "EXECUTE", "build")]

        class Adapter:
            def probe(self, _spec):
                return {"ok": True}

            def execute(self, step, _spec, _task_dir):
                return {"gates": [{"name": step.identifier, "passed": True}]}

            def repair(self, _step, _spec, _task_dir, _failure):
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            registry = RecipeRegistry()
            registry.register(Recipe())
            engine = TaskEngine(store, Adapter(), registry)
            started = engine.start({"task_type": "houdini.test", "intent": "test", "target": {"application": "houdini"}}, background=False)
            result = engine.result(started["task_id"])
            self.assertEqual(result["state"], "SUCCEEDED")
            self.assertEqual(len(list(store.events(started["task_id"]))), 5)

    def test_missing_scene_input_waits_without_attempting_repair(self):
        class MissingInput(Exception):
            code = "AWAITING_INPUT"
        class Recipe:
            identifier = "houdini.missing_scene"
            def steps(self, _spec, _capabilities):
                return [Step("scene", "AUTHOR", "scene")]
        class Adapter:
            def probe(self, _spec):
                return {}
            def execute(self, *_args):
                raise MissingInput("isolated scene not bound")
            def repair(self, *_args):
                raise AssertionError("missing input must not trigger a mutating repair")
        with tempfile.TemporaryDirectory() as directory:
            registry = RecipeRegistry()
            registry.register(Recipe())
            engine = TaskEngine(TaskStore(Path(directory)), Adapter(), registry)
            task = engine.start({"task_type": Recipe.identifier, "intent": "test", "target": {"application": "houdini"}}, background=False)
            result = engine.result(task["task_id"])
            self.assertEqual(result["state"], "AWAITING_INPUT")
            self.assertEqual(result["error_code"], "AWAITING_INPUT")

    def test_spec_defaults_and_context_are_bounded(self) -> None:
        spec = TaskSpec.from_mapping({"task_type": "houdini.model_to_karma", "intent": "crate", "target": {"application": "houdini"}})
        self.assertEqual(spec.render["resolution"], [1280, 720])
        self.assertEqual(spec.render["renderer"], "auto")
        context = compact_context({"task_id": "a", "state": "RUNNING", "phase": "PROBE", "step": "probe"})
        self.assertEqual(
            context["allowed_commands"],
            ["capabilities.get", "get_project_settings", "node.children", "node.info", "nuke_ping", "scene.info"],
        )
        with self.assertRaises(ValueError):
            TaskSpec.from_mapping({"task_type": "houdini.model_to_karma", "intent": "wrong target", "target": {"application": "nuke"}})

    def test_cancel_after_adapter_and_resume_from_checkpoint(self) -> None:
        second_started = threading.Event()
        release_second = threading.Event()

        class Recipe:
            identifier = "houdini.cancel_resume"

            def steps(self, _spec, _capabilities):
                return [Step("first", "AUTHOR", "first"), Step("second", "AUTHOR", "second")]

        class Adapter:
            def probe(self, _spec):
                return {"ok": True}

            def execute(self, step, _spec, _task_dir):
                if step.identifier == "second":
                    second_started.set()
                    release_second.wait(2)
                return {"gates": [{"name": step.identifier, "passed": True}]}

            def repair(self, _step, _spec, _task_dir, _failure):
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory))
            registry = RecipeRegistry()
            registry.register(Recipe())
            engine = TaskEngine(store, Adapter(), registry)
            started = engine.start({"task_type": "houdini.cancel_resume", "intent": "test", "target": {"application": "houdini"}}, background=True)
            task_id = started["task_id"]
            self.assertTrue(second_started.wait(2))
            engine.cancel(task_id)
            release_second.set()
            deadline = time.monotonic() + 2
            while store.load_status(task_id).get("state") == "RUNNING" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(store.load_status(task_id)["state"], "CANCELLED")
            engine.resume(task_id, background=False)
            self.assertEqual(engine.result(task_id)["state"], "SUCCEEDED")
