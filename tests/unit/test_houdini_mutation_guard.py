# -*- coding: utf-8 -*-
"""R01: persistent root-lease ownership on the Houdini dispatch surface.

- Root creation goes through the dedicated ``scene.create_task_root``
  operation, which atomically records a persistent lease (exact root name,
  task, host session, generation, scope).  Plain ``node.create`` under /obj
  stays refused.
- Every dispatched mutation re-checks the lease: revoked/expired/corrupt
  records and a lost generation (takeover) fail closed; a claimed task that
  differs from the lease task is refused.
- /obj and /stage use separate lease scopes.
All state goes to a temporary HOUDINI_BRIDGE_STATE_DIR; the fake ``hou``
module only replaces the host API — the real production guard runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"

GRAPH_ROOT = "BRIDGE_GRAPH_" + "0f" * 32
STAGE_ROOT = "BRIDGE_GRAPH_" + "1a" * 32


def _load_addon():
    spec = importlib.util.spec_from_file_location("_mutation_guard_addon", ADDON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeParm:
    def __init__(self, name):
        self._name = name
        self.value = 0.0

    def name(self):
        return self._name

    def eval(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeNode:
    def __init__(self, path, children=(), node_type="geo"):
        self._path = path
        self._node_type = node_type
        self._children = list(children)
        self._parms = {"scale": _FakeParm("scale")}

    def parms(self):
        return list(self._parms.values())

    def path(self):
        return self._path

    def type(self):
        return types.SimpleNamespace(name=lambda: self._node_type)

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def children(self):
        return self._children

    def parm(self, name):
        return self._parms.get(name)

    def createNode(self, node_type, name):
        path = "{}/{}".format(self._path, name)
        child = _FakeNode(path, node_type=node_type)
        self._children.append(child)
        return child

    def cook(self, force=False):
        self.cooked = True


class MutationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mutation-guard-")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.previous_state_dir = os.environ.get("HOUDINI_BRIDGE_STATE_DIR")
        os.environ["HOUDINI_BRIDGE_STATE_DIR"] = str(self.state_dir)
        self.addCleanup(self._restore_env)
        self.addon = _load_addon()
        self.addon._LEASE_RENEW_MEMORY.clear()
        self.obj = _FakeNode("/obj")
        self.stage = _FakeNode("/stage")
        self.user_node = _FakeNode("/obj/user_camera")
        self.nodes = {"/obj": self.obj, "/stage": self.stage, "/obj/user_camera": self.user_node}
        fake_hou = types.SimpleNamespace(node=lambda path: self.nodes.get(path), undos=None)
        self.previous_hou = sys.modules.get("hou")
        sys.modules["hou"] = fake_hou
        self.addCleanup(self._restore_hou)

    def _restore_env(self):
        if self.previous_state_dir is None:
            os.environ.pop("HOUDINI_BRIDGE_STATE_DIR", None)
        else:
            os.environ["HOUDINI_BRIDGE_STATE_DIR"] = self.previous_state_dir

    def _restore_hou(self):
        if self.previous_hou is None:
            sys.modules.pop("hou", None)
        else:
            sys.modules["hou"] = self.previous_hou

    def _register_node(self, node):
        self.nodes[node.path()] = node
        return node

    def test_root_creation_is_a_dedicated_leased_operation(self) -> None:
        result = self.addon.dispatch("scene.create_task_root",
                                     {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        self.assertFalse(result["reused"])
        self._register_node(_FakeNode("/obj/" + GRAPH_ROOT))
        lease = self.addon._root_lease_read("/obj/" + GRAPH_ROOT)
        self.assertIsNotNone(lease)
        self.assertEqual(lease["task_id"], "t1")
        self.assertEqual(lease["scope"], "sop")
        self.assertEqual(lease["status"], "ACTIVE")
        # /obj 直接创建仍被拒绝
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.create", {"parent": "/obj", "type": "geo", "name": "anything"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")

    def test_root_creation_is_idempotent_for_the_same_task(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        node = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT))
        again = self.addon.dispatch("scene.create_task_root",
                                    {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        self.assertTrue(again["reused"])
        self.assertEqual(len(node._children), 0)

    def test_same_name_root_owned_by_another_task_is_refused(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        self._register_node(_FakeNode("/obj/" + GRAPH_ROOT))
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("scene.create_task_root",
                                {"task_id": "t2", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        self.assertEqual(ctx.exception.code, "SCENE_CONFLICT")

    def test_mutation_inside_leased_root_is_allowed(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        result = self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                       "value": 2.0, "task_id": "t1"})
        self.assertEqual(result["values"]["scale"], 2.0)

    def test_cross_task_mutation_is_refused(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "other-task"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")

    def test_mutation_outside_any_leased_root_is_refused(self) -> None:
        self._register_node(_FakeNode("/obj/user_camera"))
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": "/obj/user_camera", "name": "scale", "value": 1.0})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")

    def test_generation_takeover_stops_the_old_host(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        lease = self.addon._root_lease_read("/obj/" + GRAPH_ROOT)
        lease["owner_generation"] = "generation-of-the-new-host"
        self.addon._root_lease_write("/obj/" + GRAPH_ROOT, lease)
        self.addon._LEASE_RENEW_MEMORY.clear()
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "t1"})
        self.assertEqual(ctx.exception.code, "GENERATION_TAKEOVER")

    def test_corrupt_lease_fails_closed(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        lease_path = self.addon._root_lease_path("/obj/" + GRAPH_ROOT)
        lease_path.write_text("{corrupt", encoding="utf-8")
        self.addon._LEASE_RENEW_MEMORY.clear()
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "t1"})
        self.assertEqual(ctx.exception.code, "CORRUPT_LEASE")
        preserved = list(self.state_dir.glob("**/*.corrupt-*"))
        self.assertTrue(preserved, "corrupt lease bytes preserved")

    def test_stage_scope_is_separate_from_sop(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        stage_node = self._register_node(_FakeNode("/stage/" + STAGE_ROOT))
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": stage_node.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "t1"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")
        self.addon._root_lease_issue("/stage/" + STAGE_ROOT, "t1", scope="stage")
        self.addon._LEASE_RENEW_MEMORY.clear()
        result = self.addon.dispatch("node.set_parm", {"path": stage_node.path(), "name": "scale",
                                                       "value": 1.0, "task_id": "t1"})
        self.assertEqual(result["values"]["scale"], 1.0)

    def test_expired_lease_fails_closed(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        lease = self.addon._root_lease_read("/obj/" + GRAPH_ROOT)
        lease["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.addon._root_lease_write("/obj/" + GRAPH_ROOT, lease)
        self.addon._LEASE_RENEW_MEMORY.clear()
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "t1"})
        self.assertEqual(ctx.exception.code, "LEASE_EXPIRED")

    def test_revoked_lease_fails_closed(self) -> None:
        self.addon.dispatch("scene.create_task_root",
                            {"task_id": "t1", "root_name": GRAPH_ROOT, "parent": "/obj", "type": "geo"})
        solver = self._register_node(_FakeNode("/obj/" + GRAPH_ROOT + "/solver"))
        lease = self.addon._root_lease_read("/obj/" + GRAPH_ROOT)
        lease["status"] = "REVOKED"
        self.addon._root_lease_write("/obj/" + GRAPH_ROOT, lease)
        self.addon._LEASE_RENEW_MEMORY.clear()
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parm", {"path": solver.path(), "name": "scale",
                                                  "value": 1.0, "task_id": "t1"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")


if __name__ == "__main__":
    unittest.main()
