"""Strict HDA capture using explicit non-native HOM objects; no DCC is run."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, ExitStack, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))


class Section:
    def __init__(self, contents): self.contents = contents
    def binaryContents(self): return self.contents


class Definition:
    def __init__(self, name="demo::1.0"):
        self.name = name
        self.data = {"Contents": Section(b"network\x00bytes"), "PythonModule": Section(b"script")}
        self.options = {"PythonModule/IsPython": True}
        self.info, self.library = "representative=output", "/source/demo.hda"
    def nodeTypeName(self): return self.name
    def nodeTypeCategory(self): return SimpleNamespace(name=lambda: "Sop")
    def sections(self): return self.data
    def version(self): return "1.0"
    def extraFileOptions(self): return self.options
    def extraInfo(self): return self.info
    def libraryFilePath(self): return self.library


class Parm:
    def __init__(self, node):
        self.owner, self.raw, self.value, self.reads = node, "0.5", 0.5, 0
        self.kind, self.keys = "Float", ()
    def name(self): return "gain"
    def path(self): return self.owner.path() + "/gain"
    def node(self): return self.owner
    def keyframes(self): return self.keys
    def expression(self): raise ValueError("no expression")
    def getReferencedParm(self): return self
    def parmTemplate(self): return SimpleNamespace(type=lambda: self.kind)
    def unexpandedString(self): return self.raw
    def rawValue(self): return self.raw
    def eval(self):
        self.reads += 1
        return self.value


class Node:
    def __init__(self, path, definition=None, *, internal=False):
        self.location, self.definition, self.internal = path, definition, internal
        self.descendants, self.data, self.connections, self.input_nodes = [], {}, [], []
        self.editable, self.editable_inside, self.delayed, self.hard_locked = False, False, False, False
        self.locked, self.matches = definition is not None, True
        self.sync_calls, self.sync_error = 0, None
        self.gain = Parm(self)
    def path(self): return self.location
    def type(self):
        name = self.definition.name if self.definition else "null"
        return SimpleNamespace(name=lambda: name, nameWithCategory=lambda: "Sop/" + name,
                               category=lambda: SimpleNamespace(name=lambda: "Sop"), definition=lambda: self.definition)
    def parms(self): return (self.gain,)
    def parm(self, name): return self.gain if name == "gain" else None
    def children(self): return () if self.delayed else tuple(self.descendants)
    def isNetwork(self): return bool(self.descendants)
    def allSubChildren(self, top_down=True, recurse_in_locked_nodes=True, sync_delayed_definition=False):
        result = []
        for child in self.children():
            if sync_delayed_definition and child.isDelayedDefinition():
                child.syncDelayedDefinition()
            if top_down: result.append(child)
            if recurse_in_locked_nodes or child.isEditable():
                result.extend(child.allSubChildren(top_down, recurse_in_locked_nodes, sync_delayed_definition))
            if not top_down: result.append(child)
        return tuple(result)
    def isLockedHDA(self): return self.locked
    def matchesCurrentDefinition(self): return self.matches
    def isDelayedDefinition(self): return self.delayed
    def syncDelayedDefinition(self):
        self.sync_calls += 1
        if self.sync_error is not None: raise self.sync_error
        self.delayed = False
    def isEditable(self): return self.editable
    def isEditableInsideLockedHDA(self): return self.editable_inside
    def isHardLocked(self): return self.hard_locked
    def isBypassed(self): return False
    def isDisplayFlagSet(self): return False
    def isRenderFlagSet(self): return False
    def isTemplateFlagSet(self): return False
    def userData(self, name): return self.data.get(name)
    def userDataDict(self): return self.data
    def inputs(self): return tuple(self.input_nodes)
    def inputConnections(self): return tuple(self.connections)
    def errors(self): return ()
    def warnings(self): return ()


class ObjNode:
    """HOM-shaped object node placed in another operator category."""
    def __init__(self, base, category):
        self.base, self.category = base, category
        self.display, self.selectable = False, True
        self.flag_reads = {"display": 0, "selectable": 0}
    def __getattr__(self, name):
        if name in {"isBypassed", "isHardLocked", "isRenderFlagSet", "isTemplateFlagSet"}:
            raise AttributeError(name)
        return getattr(self.base, name)
    def type(self):
        return SimpleNamespace(name=lambda: "sopnet", nameWithCategory=lambda: self.category + "/sopnet",
                               category=lambda: SimpleNamespace(name=lambda: self.category), definition=lambda: None)
    def isDisplayFlagSet(self):
        self.flag_reads["display"] += 1
        return self.display
    def isSelectableInViewport(self):
        self.flag_reads["selectable"] += 1
        return self.selectable


class SubnetIndirectInput:
    def __init__(self, parent): self.owner, self.index = parent, 0
    def parent(self): return self.owner
    def number(self): return self.index


class HdaPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("_hda_policy_addon", ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py")
        cls.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.addon)

    def model(self):
        root = Node("/obj/BRIDGE_GRAPH_" + "ab" * 32)
        root.editable = True
        asset = Node(root.path() + "/settings", Definition())
        nested = Node(asset.path() + "/nested", Definition("child::1.0"), internal=True)
        leaf = Node(nested.path() + "/leaf", internal=True)
        root.descendants, asset.descendants, nested.descendants = [asset], [nested], [leaf]
        return root, asset, nested, leaf

    @contextmanager
    def native(self, model):
        root = model[0]
        nodes = {node.path(): node for node in (root, *root.allSubChildren())}
        with patch.dict(sys.modules, {"hou": SimpleNamespace(node=nodes.get, ObjNode=ObjNode, Node=Node, SubnetIndirectInput=SubnetIndirectInput)}), patch.object(
                self.addon, "_root_lease_check"), patch.object(self.addon, "_fx_manifest", return_value=(None, {})):
            yield nodes

    def capture(self, model, policy=None):
        with self.native(model):
            return self.addon._fx_native_command_scene_contract("abc123", {"root_path": model[0].path()}, capture_policy=policy)

    @contextmanager
    def producer_host(self, model):
        root = model[0].path()
        identity = {"task_id": "abc123", "pid": os.getpid(), "scene_epoch": 0, "session_id": "explicit-unit",
                    "launch_nonce": "explicit-unit", "process_generation": "explicit-unit", "plugin_build": "explicit-unit"}
        with tempfile.TemporaryDirectory(prefix="hda-policy-", dir="/private/tmp") as directory, ExitStack() as stack:
            directory = Path(directory)
            holder = {"path": str(directory / "unsaved.hip")}
            nodes = {node.path(): node for node in (model[0], *model[0].allSubChildren())}
            lease = {"version": 1, "scene_epoch": 0, "owner_generation": "explicit-unit"}

            def save(path=None):
                target = Path(path or holder["path"])
                state = {}
                for location, node in nodes.items():
                    definition = node.definition
                    state[location] = {"raw": node.gain.raw, "value": node.gain.value, "data": node.data,
                        "definition": {"sections": {name: section.contents.hex() for name, section in definition.data.items()},
                            "options": definition.options, "info": definition.info} if definition else None}
                target.write_text(json.dumps(state, sort_keys=True))
                holder["path"] = str(target)

            def load(path, **kwargs):
                for event in ("BeforeLoad", "BeforeClear", "AfterClear", "AfterLoad"):
                    self.addon._bridge_scene_event(event)
                    self.addon._graph_worker_scene_event(event)
                for location, state in json.loads(Path(path).read_text()).items():
                    node = nodes[location]
                    node.gain.raw, node.gain.value, node.data = state["raw"], state["value"], state["data"]
                    if node.definition is not None:
                        definition = state["definition"]
                        node.definition.data = {name: Section(bytes.fromhex(contents)) for name, contents in definition["sections"].items()}
                        node.definition.options, node.definition.info = definition["options"], definition["info"]
                        node.definition.library = "Embedded"
                holder["path"] = str(path)
                identity["scene_epoch"] += 1

            def lease_write(path, rebound, *, expect_version):
                if expect_version != lease["version"]:
                    raise self.addon.BridgeCommandError("LEASE_CAS_CONFLICT", "explicit fixture CAS mismatch")
                lease.update(rebound, version=expect_version + 1)
                return dict(lease)

            hou = SimpleNamespace(node=nodes.get, ObjNode=ObjNode, _bridge_software_boundary=True, undos=None,
                applicationVersionString=lambda: "21.0.631",
                hipFileEventType=SimpleNamespace(BeforeLoad="BeforeLoad", BeforeClear="BeforeClear", BeforeMerge="BeforeMerge",
                                                AfterClear="AfterClear", AfterLoad="AfterLoad"),
                hipFile=SimpleNamespace(path=lambda: holder["path"], save=save, load=load,
                                        setName=lambda p: holder.update(path=str(Path(p).expanduser().resolve())),
                                        eventCallbacks=lambda: (self.addon._bridge_scene_event, self.addon._graph_worker_scene_event)))
            stack.enter_context(patch.dict(sys.modules, {"hou": hou}))
            for name, replacement in {
                "_fx_producer_identity": lambda task_id: dict(identity), "_host_identity": lambda: dict(identity),
                "_root_lease_check": lambda *args, **kwargs: dict(lease),
                "_task_scene_lease_fence": lambda *args, **kwargs: nullcontext(),
                "_root_lease_fence": lambda *args, **kwargs: nullcontext(dict(lease)),
                "_root_lease_write": lease_write,
                "_fx_manifest": lambda *args, **kwargs: (None, {}),
                "_fx_capture_scene_contract": lambda *args, **kwargs: None,
                "_fx_operations_store_path": lambda task_id: directory / "operations.json",
                "_task_state_root": lambda: directory,
                "_fx_host_generation": lambda: "explicit-unit",
                "_fx_registered_rebind_saved_contract": lambda *args, **kwargs: nullcontext({}),
            }.items():
                stack.enter_context(patch.object(self.addon, name, replacement))
            stack.enter_context(patch.object(self.addon, "_FX_OPERATIONS", None))
            yield directory, identity, lease

    def request(self, operation_id, root, **values):
        return {"task_id": "abc123", "operation_id": operation_id, "request_id": operation_id,
                "frozen_input_manifest": [], "root_path": root, **values}

    @contextmanager
    def creation_host(self, *, root_delayed=True, nested_delayed=True):
        model = self.model()
        root, asset, nested, leaf = model
        root.descendants = []
        asset.delayed, nested.delayed = root_delayed, nested_delayed
        with self.producer_host(model) as state:
            nodes = sys.modules["hou"].node.__self__
            created = []

            def create(node_type, name, **options):
                self.assertEqual(node_type, asset.type().name())
                self.assertEqual(name, "settings")
                created.append(asset)
                root.descendants.append(asset)
                nodes.update({node.path(): node for node in model[1:]})
                return asset

            with patch.object(root, "createNode", create, create=True):
                yield model, state, created

    def test_formal_create_loads_delayed_root_and_nested_under_mutation_fence(self):
        from houdini_bridge.operation_receipt_store import load_record
        for root_delayed in (False, True):
            with self.subTest(root_delayed=root_delayed), self.creation_host(root_delayed=root_delayed) as (model, _, created):
                root, asset, nested, _ = model
                active = []
                original_fence = self.addon._mutation_lease_fence

                @contextmanager
                def fenced(command, params):
                    with original_fence(command, params):
                        active.append(True)
                        try: yield
                        finally: active.pop()

                def observe_sync(node, original):
                    def sync():
                        self.assertTrue(active)
                        runner = self.addon.fx_operation_runner("abc123")
                        self.assertEqual(load_record(runner.path, "abc123", "create-delayed")["state"], "INTENT")
                        return original()
                    return sync

                with patch.object(self.addon, "_mutation_lease_fence", fenced), patch.object(
                        asset, "syncDelayedDefinition", observe_sync(asset, asset.syncDelayedDefinition)), patch.object(
                        nested, "syncDelayedDefinition", observe_sync(nested, nested.syncDelayedDefinition)):
                    result = self.addon.dispatch("node.create", self.request("create-delayed", root.path(),
                        parent=root.path(), type=asset.type().name(), name="settings", exact_type_name=True))
                self.assertEqual(len(created), 1)
                self.assertEqual((asset.sync_calls, nested.sync_calls), (int(root_delayed), 1))
                self.assertFalse(asset.delayed or nested.delayed)
                self.assertEqual(result["operation_receipt"]["state"], "COMPLETED")
                self.assertEqual(result["operation_receipt"]["after_scene"]["scene_contract"]["schema"],
                                 "houdini.task_scene_contract/2.1")

    def test_unbound_creation_keeps_delayed_definition_and_other_task_is_rejected(self):
        with self.creation_host() as (model, _, created):
            root, asset, nested, _ = model
            result = self.addon.dispatch("node.create", {"parent": root.path(), "type": asset.type().name(), "name": "settings"})
            self.assertEqual(result["path"], asset.path())
            self.assertEqual((asset.sync_calls, nested.sync_calls), (0, 0))
            self.assertTrue(asset.delayed and nested.delayed)
        with self.creation_host() as (model, _, created):
            root, asset, nested, _ = model
            rejection = self.addon.BridgeCommandError("LEASE_OWNERSHIP_CONFLICT", "different task")
            with patch.object(self.addon, "_root_lease_check", side_effect=rejection):
                with self.assertRaises(self.addon.BridgeCommandError):
                    self.addon.dispatch("node.create", self.request("foreign-create", root.path(),
                        task_id="other-task", parent=root.path(), type=asset.type().name(), name="settings"))
            self.assertEqual(created, [])
            self.assertEqual((asset.sync_calls, nested.sync_calls), (0, 0))

    def test_delayed_initialization_failure_is_persisted_and_cannot_replay(self):
        from houdini_bridge.operation_receipt_store import load_record
        for failing in (1, 2):
            with self.subTest(failing=failing), self.creation_host() as (model, _, created):
                root, asset, nested, _ = model
                model[failing].sync_error = RuntimeError("definition initialization failed")
                request = self.request("failed-create", root.path(), parent=root.path(),
                                       type=asset.type().name(), name="settings")
                with self.assertRaisesRegex(RuntimeError, "definition initialization failed"):
                    self.addon.dispatch("node.create", request)
                runner = self.addon.fx_operation_runner("abc123")
                self.assertEqual(load_record(runner.path, "abc123", "failed-create")["state"], "FAILED")
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.create", request)
                self.assertEqual(caught.exception.code, "PRODUCER_RECONCILE_REQUIRED")
                self.assertEqual(len(created), 1)

    def test_capture_and_verify_never_initialize_delayed_definitions(self):
        for delayed_index in (1, 2):
            model = self.model()
            contract = self.capture(model)
            model[delayed_index].delayed = True
            with self.subTest(delayed_index=delayed_index):
                with self.assertRaises(self.addon.BridgeCommandError):
                    self.capture(model)
                with self.native(model), self.assertRaises(self.addon.BridgeCommandError):
                    self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                self.assertEqual([node.sync_calls for node in model], [0, 0, 0, 0])
                self.assertTrue(model[delayed_index].delayed)

    def test_producer_selects_legacy_prior_before_capture_and_preserves_receipt_bytes(self):
        from houdini_bridge.operation_receipt_store import load_record
        model = self.model()
        with self.producer_host(model):
            request = self.request("legacy-inspect", model[0].path(), path=model[1].path())
            native = self.addon._fx_native_command_scene_contract

            def legacy(*args, **kwargs):
                kwargs["capture_policy"] = "legacy-full/2.0"
                return native(*args, **kwargs)

            with patch.object(self.addon, "_fx_native_command_scene_contract", legacy):
                created = self.addon._fx_producer_dispatch("node.info", request)
            path = Path(created["operation_store_path"])
            original = path.read_bytes()
            before_reads = model[-1].gain.reads
            replay = self.addon._fx_producer_dispatch("node.info", request)
            self.assertTrue(replay["idempotent"])
            self.assertEqual(path.read_bytes(), original)
            self.assertGreater(model[-1].gain.reads, before_reads)
            self.assertEqual(replay["operation_receipt"], created["operation_receipt"])
            runner = self.addon.fx_operation_runner("abc123")
            self.assertEqual(load_record(runner.path, "abc123", "legacy-inspect"), created["operation_receipt"])

    def test_producer_two_hda_captures_and_policy_selected_save_reopen(self):
        for legacy in (False, True):
            model = self.model()
            with self.subTest(legacy=legacy), self.producer_host(model) as (directory, identity, lease):
                root = model[0].path()
                capture = self.addon._fx_native_command_scene_contract

                def selected(*args, **kwargs):
                    if legacy: kwargs["capture_policy"] = "legacy-full/2.0"
                    return capture(*args, **kwargs)

                with patch.object(self.addon, "_fx_native_command_scene_contract", selected), patch.object(
                        self.addon, "_fx_producer_scene", wraps=self.addon._fx_producer_scene) as observed:
                    inspected = self.addon._fx_producer_dispatch("node.info", self.request("inspect", root, path=model[1].path()))
                    self.assertEqual(observed.call_count, 2)
                    saved = self.addon._fx_producer_dispatch("scene.save_hip", self.request("save", root, path=str(directory / "scene.hip")))
                receipt = saved["operation_receipt"]
                schema = "houdini.task_scene_contract/2.0" if legacy else "houdini.task_scene_contract/2.1"
                self.assertEqual(receipt["after_scene"]["scene_contract"]["schema"], schema)
                self.assertEqual(inspected["operation_receipt"]["facts"]["proof_scope"], "native_command")
                recorded_path = self.addon._fx_task_saves_path("abc123")
                original = recorded_path.read_bytes()
                result = self.addon._fx_reopen_owned_root({"task_id": "abc123", "root_path": root},
                    Path(saved["path"]), saved["sha256"])
                self.assertTrue(result["verification"]["nodes_verified"])
                self.assertEqual(result["scene_contract_sha256"], saved["scene_contract_sha256"])
                self.assertEqual(recorded_path.read_bytes(), original)
                self.assertEqual(identity["scene_epoch"], 1)
                self.assertEqual(lease["version"], 2)
                self.assertEqual(model[1].definition.library, "Embedded")

    def test_scene_callbacks_keep_bounded_event_evidence_without_changing_epoch_rules(self):
        events = SimpleNamespace(BeforeClear="BeforeClear", BeforeLoad="BeforeLoad", BeforeMerge="BeforeMerge")
        state = SimpleNamespace(scene_epoch=0)
        with patch.dict(sys.modules, {"hou": SimpleNamespace(hipFileEventType=events)}), \
                patch.object(self.addon, "_BRIDGE_SCENE_STATE", state), \
                patch.object(self.addon, "_GRAPH_WORKER_SCENE_EPOCH", 0), \
                patch.object(self.addon, "_GRAPH_WORKER_SCENE_EVENTS", []):
            for event in (events.BeforeClear, events.BeforeLoad, "AfterLoad"):
                self.addon._bridge_scene_event(event)
                self.addon._graph_worker_scene_event(event)
            self.assertEqual(state.scene_epoch, 2)
            self.assertEqual(self.addon._GRAPH_WORKER_SCENE_EPOCH, 2)
            self.assertEqual(state.recent_events, [{"event": "BeforeClear", "epoch": 1},
                                                  {"event": "BeforeLoad", "epoch": 2}, {"event": "AfterLoad", "epoch": 2}])
            self.assertEqual(self.addon._GRAPH_WORKER_SCENE_EVENTS, state.recent_events)
            for _ in range(10):
                self.addon._bridge_scene_event("x" * 100)
                self.addon._graph_worker_scene_event("x" * 100)
            self.assertEqual(len(state.recent_events), 8)
            self.assertEqual(len(self.addon._GRAPH_WORKER_SCENE_EVENTS), 8)
            self.assertTrue(all(len(item["event"]) == 80 and item["epoch"] == 2 for item in state.recent_events))

    def test_owned_load_counts_nested_clear_once_and_cleans_up_failed_sequences(self):
        events = SimpleNamespace(**{name: name for name in ("BeforeClear", "BeforeLoad", "BeforeMerge", "AfterClear", "AfterLoad")})
        hou = SimpleNamespace(hipFileEventType=events, hipFile=SimpleNamespace(eventCallbacks=lambda:
                              (self.addon._bridge_scene_event, self.addon._graph_worker_scene_event)))
        sequences = (("BeforeLoad", "BeforeClear", "AfterClear", "AfterLoad"), ("BeforeLoad", "AfterLoad"),
                     ("BeforeLoad", "BeforeClear", "BeforeClear", "AfterClear", "AfterLoad"),
                     ("BeforeLoad", "BeforeLoad", "AfterLoad"), ("BeforeLoad", "BeforeMerge", "AfterLoad"),
                     ("BeforeLoad", "BeforeClear"))
        for sequence in sequences:
            state = SimpleNamespace(scene_epoch=0)
            with self.subTest(sequence=sequence), patch.dict(sys.modules, {"hou": hou}), \
                    patch.object(self.addon, "_BRIDGE_SCENE_STATE", state), \
                    patch.object(self.addon, "_GRAPH_WORKER_SCENE_EPOCH", 0), \
                    patch.object(self.addon, "_GRAPH_WORKER_SCENE_EVENTS", []):
                expected_ok = sequence in sequences[:2]
                with nullcontext() if expected_ok else self.assertRaises(self.addon.BridgeCommandError):
                    with self.addon._fx_owned_hip_load_events():
                        for event in sequence:
                            self.addon._bridge_scene_event(event)
                            self.addon._graph_worker_scene_event(event)
                if expected_ok:
                    self.assertEqual(state.scene_epoch, 1)
                    self.assertEqual(self.addon._GRAPH_WORKER_SCENE_EPOCH, 1)
                self.assertIsNone(self.addon._FX_OWNED_HIP_LOAD)
                prior = state.scene_epoch
                for event in ("BeforeClear", "BeforeMerge"):
                    self.addon._bridge_scene_event(event)
                    self.addon._graph_worker_scene_event(event)
                self.assertEqual(state.scene_epoch, prior + 2)
                with self.assertRaises(RuntimeError):
                    with self.addon._fx_owned_hip_load_events():
                        self.addon._bridge_scene_event("BeforeLoad")
                        self.addon._graph_worker_scene_event("BeforeLoad")
                        raise RuntimeError("native load failed before AfterLoad")
                self.assertIsNone(self.addon._FX_OWNED_HIP_LOAD)
                prior = state.scene_epoch
                self.addon._bridge_scene_event("BeforeClear")
                self.addon._graph_worker_scene_event("BeforeClear")
                self.assertEqual(state.scene_epoch, prior + 1)

    def test_host_only_load_warning_counts_each_complete_load_and_rejects_incomplete_warning(self):
        class LoadWarning(Exception): pass
        events = SimpleNamespace(**{name: name for name in ("BeforeClear", "BeforeLoad", "BeforeMerge", "AfterClear", "AfterLoad")})
        hou = SimpleNamespace(LoadWarning=LoadWarning, hipFileEventType=events,
                              hipFile=SimpleNamespace(eventCallbacks=lambda: (self.addon._bridge_scene_event,)))
        state = SimpleNamespace(scene_epoch=0)
        with patch.dict(sys.modules, {"hou": hou}), patch.object(self.addon, "_BRIDGE_SCENE_STATE", state):
            with self.assertRaises(LoadWarning):
                with self.addon._fx_owned_hip_load_events():
                    for event in ("BeforeLoad", "BeforeClear", "AfterClear", "AfterLoad"):
                        self.addon._bridge_scene_event(event)
                    raise LoadWarning("native post-load warning")
            self.assertIsNone(self.addon._FX_OWNED_HIP_LOAD)
            self.assertEqual(state.scene_epoch, 1)
            with self.addon._fx_owned_hip_load_events():
                for event in ("BeforeLoad", "BeforeClear", "AfterClear", "AfterLoad"):
                    self.addon._bridge_scene_event(event)
            self.assertEqual(state.scene_epoch, 2)
            with self.assertRaises(self.addon.BridgeCommandError):
                with self.addon._fx_owned_hip_load_events():
                    self.addon._bridge_scene_event("BeforeLoad")
                    raise LoadWarning("incomplete native load")
            self.assertIsNone(self.addon._FX_OWNED_HIP_LOAD)
            prior = state.scene_epoch
            self.addon._bridge_scene_event("BeforeClear")
            self.assertEqual(state.scene_epoch, prior + 1)

    def test_owned_reopen_epoch_drift_reports_counts_without_weakening_gate(self):
        model = self.model()
        with self.producer_host(model) as (directory, identity, lease):
            saved = self.addon._fx_producer_dispatch("scene.save_hip", self.request(
                "save", model[0].path(), path=str(directory / "scene.hip")))
            native_load = sys.modules["hou"].hipFile.load
            def extra_epoch(*args, **kwargs):
                native_load(*args, **kwargs)
                identity["scene_epoch"] += 1
            with patch.object(sys.modules["hou"].hipFile, "load", side_effect=extra_epoch), \
                    patch.object(self.addon, "_fx_verify_scene_contract_nodes") as verify:
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_reopen_owned_root({"task_id": "abc123", "root_path": model[0].path()},
                                                   Path(saved["path"]), saved["sha256"])
                self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")
                self.assertIn("'producer_epochs': [0, 2]", str(caught.exception))
                self.assertIn("'host_epochs': [0, 2]", str(caught.exception))
                self.assertIn("'producer_changed_fields': []", str(caught.exception))
                self.assertNotIn(identity["session_id"], str(caught.exception))
                verify.assert_not_called()
                self.assertEqual(lease["version"], 1)

    def test_internal_hda_state_rejection_identifies_boundary_child_and_strict_flags(self):
        for method, value in (("isEditable", True), ("isEditableInsideLockedHDA", True),
                              ("isDelayedDefinition", True), ("isEditable", 1)):
            model = self.model()
            child = model[-1]
            setattr(child, method, lambda: value)
            with self.subTest(method=method, value=value), self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.capture(model)
            message = str(caught.exception)
            self.assertIn(model[1].path(), message)
            self.assertIn(child.path(), message)
            for flag in ("isEditable", "isEditableInsideLockedHDA", "isDelayedDefinition"):
                self.assertIn(flag, message)
            if type(value) is not bool: self.assertIn("isEditable_malformed", message)

    def test_loaded_hda_preparation_is_explicit_bound_and_still_verified(self):
        for case in ("success", "editable", "definition", "digest", "task", "marker", "sync_failure"):
            model = self.model()
            contract = self.capture(model)
            digest = self.addon._fx_scene_contract_digest(contract)
            nested = model[2]
            nested.delayed = True
            foreign = Node(model[0].path() + "/foreign", Definition("foreign"))
            foreign.delayed = True
            model[0].descendants.append(foreign)
            if case == "editable": model[-1].editable = True
            elif case == "definition": model[1].definition.data["Contents"].contents = b"changed"
            elif case == "digest": digest = "0" * 64
            elif case == "marker": model[0].data["agent_task_id"] = "another-task"
            elif case == "sync_failure": nested.sync_error = RuntimeError("native sync failed")
            with self.subTest(case=case), self.native(model):
                if case in {"definition", "digest", "task", "marker", "sync_failure"}:
                    with self.assertRaises((self.addon.BridgeCommandError, RuntimeError)):
                        self.addon._fx_prepare_loaded_hda_boundaries(contract, "other" if case == "task" else "abc123", digest)
                    if case != "sync_failure": self.assertEqual(nested.sync_calls, 0)
                else:
                    self.addon._fx_prepare_loaded_hda_boundaries(contract, "abc123", digest)
                    self.assertFalse(nested.delayed)
                    self.assertEqual(nested.sync_calls, 1)
                    model[0].descendants.remove(foreign)
                    if case == "editable":
                        with self.assertRaises(self.addon.BridgeCommandError):
                            self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                    else:
                        self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])
                self.assertTrue(foreign.delayed)
                self.assertEqual(foreign.sync_calls, 0)

    def test_owned_reopen_explicitly_prepares_delayed_saved_boundary_before_verify(self):
        model = self.model()
        with self.producer_host(model) as (directory, identity, lease):
            saved = self.addon._fx_producer_dispatch("scene.save_hip", self.request(
                "save", model[0].path(), path=str(directory / "scene.hip")))
            native_load = sys.modules["hou"].hipFile.load
            def load_delayed(*args, **kwargs):
                native_load(*args, **kwargs)
                model[2].delayed = True
            with patch.object(sys.modules["hou"].hipFile, "load", side_effect=load_delayed):
                result = self.addon._fx_reopen_owned_root({"task_id": "abc123", "root_path": model[0].path()},
                                                       Path(saved["path"]), saved["sha256"])
            self.assertTrue(result["verification"]["nodes_verified"])
            self.assertEqual(model[2].sync_calls, 1)
            self.assertEqual(identity["scene_epoch"], 1)

    def test_formal_task_reopen_prepares_only_after_loaded_epoch_check(self):
        model = self.model()
        with self.producer_host(model) as (directory, identity, lease):
            saved = self.addon._fx_producer_dispatch("scene.save_hip", self.request(
                "save", model[0].path(), path=str(directory / "scene.hip")))
            native_load = sys.modules["hou"].hipFile.load
            events = []
            def load_delayed(*args, **kwargs):
                native_load(*args, **kwargs)
                model[2].delayed = True
                events.append("load")
            def loaded(transition, snapshot, count, warnings):
                self.assertEqual(identity["scene_epoch"], 1)
                self.assertTrue(model[2].delayed)
                events.append("epoch_checked")
                return transition
            prepare = self.addon._fx_prepare_loaded_hda_boundaries
            def prepare_after_check(*args):
                self.assertEqual(events, ["load", "epoch_checked"])
                prepare(*args)
                events.append("prepare")
            with patch.object(sys.modules["hou"], "isUIAvailable", return_value=False, create=True), \
                    patch.object(sys.modules["hou"].hipFile, "load", side_effect=load_delayed), \
                    patch.object(sys.modules["hou"].hipFile, "setName", create=True), \
                    patch.object(self.addon, "_fx_scene_transition_snapshot", return_value={"snapshot_path": saved["path"]}), \
                    patch.object(self.addon, "_fx_scene_transition_begin", return_value={"before_scene_epoch": 0}), \
                    patch.object(self.addon, "_fx_scene_transition_replay", return_value=None), \
                    patch.object(self.addon, "_fx_task_reopen_record_loaded", side_effect=loaded), \
                    patch.object(self.addon, "_fx_prepare_loaded_hda_boundaries", side_effect=prepare_after_check), \
                    patch.object(self.addon, "_fx_verify_scene_contract", side_effect=self.addon._fx_verify_scene_contract_nodes), \
                    patch.object(self.addon, "_fx_finalize_task_reopen", side_effect=lambda *args, **kwargs: kwargs["contract_verification"]):
                result = self.addon.scene_reopen_task_hip({"task_id": "abc123", "path": saved["path"], "sha256": saved["sha256"]})
                self.assertTrue(result["nodes_verified"])
                self.assertEqual(events, ["load", "epoch_checked", "prepare"])
                self.assertEqual(model[2].sync_calls, 1)

    def test_public_scene_drift_diagnostics_are_bounded_typed_and_do_not_expose_strings(self):
        import ast
        model = self.model()
        contract = self.capture(model, "legacy-full/2.0")
        record = next(record for record in contract["nodes"] if record["path"] == model[0].path())
        record["type"] = "Sop/different"
        record["parameter_channels"]["gain"]["diagnostic_secret"] = "sensitive-value-must-not-appear"
        record["parameters"]["gain"] = 7
        record["inputs"] = ["/obj/expected_input"]
        with self.native(model), self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
        self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")
        message = str(caught.exception)
        self.assertNotIn("sensitive-value-must-not-appear", message)
        differences = ast.literal_eval(message.split("saved receipt: ", 1)[1])
        self.assertEqual(len(differences), 4)
        self.assertEqual({item["field"] for item in differences},
                         {"node_type_category", "parameter_channels.gain", "parameters.gain", "inputs"})
        channel = next(item for item in differences if item["field"] == "parameter_channels.gain")
        self.assertIn("diagnostic_secret", channel["changed_subkeys"])
        self.assertIn("sha256", channel["subkey_values"]["diagnostic_secret"]["expected"])
        value = next(item for item in differences if item["field"] == "parameters.gain")
        self.assertEqual(value["actual"]["type"], "float")
        self.assertEqual(value["expected"]["type"], "int")

    def test_public_channel_name_drift_reports_missing_and_extra_names(self):
        model = self.model()
        contract = self.capture(model, "legacy-full/2.0")
        record = next(record for record in contract["nodes"] if record["path"] == model[0].path())
        record["parameter_channels"]["missing_parameter"] = record["parameter_channels"].pop("gain")
        with self.native(model), self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
        message = str(caught.exception)
        self.assertIn("'missing_names': ['missing_parameter']", message)
        self.assertIn("'extra_names': ['gain']", message)

    def test_owned_reopen_rejects_invalid_saved_policy_before_capture_or_load(self):
        model = self.model()
        with self.producer_host(model) as (directory, identity, lease):
            saved = self.addon._fx_producer_dispatch("scene.save_hip", self.request(
                "save", model[0].path(), path=str(directory / "scene.hip")))
            receipt_path = self.addon._fx_task_saves_path("abc123")
            valid = json.loads(receipt_path.read_text())
            for field in ("capture_policy", "hda_boundaries", "schema", "owned_roots"):
                store = deepcopy(valid)
                contract = store["saves"][-1]["scene_contract"]
                if field == "schema": contract[field] = "houdini.task_scene_contract/unknown"
                else: del contract[field]
                store["saves"][-1]["scene_contract_sha256"] = self.addon._fx_scene_contract_digest(contract)
                receipt_path.write_text(json.dumps(store))
                with self.subTest(field=field), patch.object(self.addon, "_fx_producer_scene") as capture, patch.object(
                        sys.modules["hou"].hipFile, "load") as load, patch.object(
                        self.addon, "_fx_native_command_scene_contract") as native_capture:
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon._fx_reopen_owned_root({"task_id": "abc123", "root_path": model[0].path()},
                            Path(saved["path"]), saved["sha256"])
                    self.assertEqual(caught.exception.code, "ARTIFACT_CONTRACT_INVALID")
                    capture.assert_not_called()
                    native_capture.assert_not_called()
                    load.assert_not_called()
                self.assertEqual(identity["scene_epoch"], 0)
                self.assertEqual(lease["version"], 1)

    def test_incomplete_prior_is_rejected_before_any_live_capture(self):
        from houdini_bridge.operation_receipts import operation_receipt_sha256
        model = self.model()
        with self.producer_host(model):
            request = self.request("prior", model[0].path(), path=model[1].path())
            created = self.addon._fx_producer_dispatch("node.info", request)
            path = Path(created["operation_store_path"])
            for state in ("INTENT", "FAILED"):
                record = deepcopy(created["operation_receipt"])
                record["state"] = state
                record["operation_receipt_sha256"] = operation_receipt_sha256(record)
                path.write_text(json.dumps(record))
                before = path.read_bytes()
                with self.subTest(state=state), patch.object(self.addon, "_fx_producer_scene") as capture:
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon._fx_producer_dispatch("node.info", request)
                    self.assertEqual(caught.exception.code, "PRODUCER_RECONCILE_REQUIRED")
                    capture.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_locked_hda_binds_binary_definitions_and_static_state_without_internal_eval(self):
        from houdini_bridge.operation_receipts import validate_scene_contract_header
        model = self.model()
        contract = self.capture(model)
        self.assertEqual(validate_scene_contract_header(contract), "locked-hda-definition/1")
        self.assertEqual([n["path"] for n in contract["nodes"]], [n.path() for n in model[:2]])
        self.assertEqual([node.gain.reads for node in model], [1, 1, 0, 0])
        boundary = contract["hda_boundaries"][0]
        self.assertEqual(boundary["internal_node_count"], 2)
        self.assertEqual(len(boundary["definitions"]), 2)
        self.assertEqual([s["name"] for s in boundary["definition"]["sections"]], ["Contents", "PythonModule"])
        self.assertEqual(boundary["static_fingerprint"]["node_count"], 2)
        model[1].definition.library = "Embedded"
        model[2].definition.library = "Embedded"
        self.assertEqual(self.capture(model), contract)
        with self.native(model):
            self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])

    def test_new_policy_binds_static_identity_and_legacy_retains_internal_evaluated_values(self):
        model = self.model()
        current = self.capture(model)
        legacy = self.capture(model, "legacy-full/2.0")
        # A context-dependent evaluated value is outside the 2.1 internal
        # static proof. The legacy full contract continues to observe it.
        model[-1].gain.value = 0.9
        with self.native(model):
            self.assertTrue(self.addon._fx_verify_scene_contract_nodes(current, "abc123")["parameters_verified"])
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon._fx_verify_scene_contract_nodes(legacy, "abc123")
            self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def object_child_model(self, category):
        root, asset, nested, leaf = self.model()
        object_child = ObjNode(leaf, category)
        nested.descendants = [object_child]
        return root, asset, nested, object_child

    def test_object_runtime_flags_are_bound_independently_of_operator_category(self):
        for category in ("Lop", "Sop"):
            for flag in ("display", "selectable"):
                model = self.object_child_model(category)
                child = model[-1]
                self.assertFalse(hasattr(child, "isBypassed"))
                self.assertFalse(hasattr(child, "isHardLocked"))
                contract = self.capture(model)
                self.assertGreater(child.flag_reads["display"], 0)
                self.assertGreater(child.flag_reads["selectable"], 0)
                record = next(item for item in contract["hda_boundaries"][0]["internal_nodes"]
                              if item["path"] == child.path())
                self.assertEqual((record["category"], record["type"]), (category, category + "/sopnet"))
                with self.native(model):
                    self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])
                setattr(child, flag, not getattr(child, flag))
                with self.subTest(category=category, flag=flag), self.native(model):
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                    self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def test_object_runtime_missing_or_nonboolean_required_flags_are_rejected(self):
        for method in ("isDisplayFlagSet", "isSelectableInViewport"):
            for value in (None, lambda: 0):
                model = self.object_child_model("Lop")
                setattr(model[-1], method, value)
                with self.subTest(method=method, missing=value is None), self.assertRaises(
                        self.addon.BridgeCommandError) as caught:
                    self.capture(model)
                self.assertEqual(caught.exception.code, "SCENE_CONTRACT_HDA_UNPROVEN")
                self.assertIn(method, str(caught.exception))
                self.assertIn("Lop/sopnet", str(caught.exception))
                self.assertIn("ObjNode", str(caught.exception))
                self.assertIsNotNone(caught.exception.__cause__.__cause__)

    def indirect_model(self):
        model = self.model()
        root, asset, nested, leaf = model
        endpoint = SubnetIndirectInput(nested)
        state = {"upstream": None, "output": 0, "destination": 0}
        leaf.parent = lambda: nested
        wire = SimpleNamespace(subnetIndirectInput=lambda: endpoint, inputItem=lambda: endpoint,
                               inputNode=lambda: state["upstream"], outputIndex=lambda: state["output"],
                               inputIndex=lambda: state["destination"], inputItemOutputIndex=lambda: 0)
        leaf.connections = [wire]
        return model, endpoint, state, wire

    def test_indirect_wires_bind_disconnected_and_connected_endpoints(self):
        for connected in (False, True):
            for change in ("parent_path", "number", "upstream", "output", "destination"):
                model, endpoint, state, wire = self.indirect_model()
                if connected: state["upstream"] = model[1]
                contract = self.capture(model)
                with self.native(model):
                    self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])
                if change == "parent_path": endpoint.owner.location += "_changed"
                elif change == "number": endpoint.index = 1
                elif change == "upstream": state["upstream"] = model[0]
                else: state[change] = 1
                with self.subTest(connected=connected, change=change), self.native(model):
                    with self.assertRaises(self.addon.BridgeCommandError):
                        self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                self.assertEqual(model[-1].gain.reads, 0)

    def test_indirect_wires_reject_incomplete_or_invalid_endpoints(self):
        for case in ("missing", "unknown", "mismatch", "parent", "number", "nonint", "item_output", "output"):
            model, endpoint, state, wire = self.indirect_model()
            if case == "missing": del wire.inputItem
            elif case == "unknown": wire.subnetIndirectInput = lambda: object()
            elif case == "mismatch": wire.inputItem = lambda: SubnetIndirectInput(model[2])
            elif case == "parent": endpoint.owner = model[1]
            elif case == "number": endpoint.index = -1
            elif case == "nonint": endpoint.index = True
            elif case == "item_output": wire.inputItemOutputIndex = lambda: 1
            else: state["output"] = None
            with self.subTest(case=case), self.assertRaises(self.addon.BridgeCommandError):
                self.capture(model)

    def metadata_leaf_model(self):
        model = self.model()
        leaf = model[-1]
        leaf.definition = Definition("metadata_leaf")
        leaf.definition.data = {"DialogScript": Section(b"parameters"), "OnCreated": Section(b"initialize")}
        leaf.locked, leaf.matches = False, False
        return model

    def test_metadata_definition_leaf_keeps_definition_and_static_identity(self):
        model = self.metadata_leaf_model()
        contract = self.capture(model)
        boundary = contract["hda_boundaries"][0]
        self.assertEqual(len(boundary["definitions"]), 3)
        leaf_record = next(item for item in boundary["internal_nodes"] if item["path"] == model[-1].path())
        definition = next(item for item in boundary["definitions"] if item["sha256"] == leaf_record["definition_sha256"])
        self.assertEqual([item["name"] for item in definition["sections"]], ["DialogScript", "OnCreated"])
        self.assertEqual(model[-1].gain.reads, 0)
        with self.native(model):
            self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])
        for change in ("definition", "option", "static", "flag"):
            model = self.metadata_leaf_model()
            contract = self.capture(model)
            leaf = model[-1]
            if change == "definition": leaf.definition.data["OnCreated"].contents = b"changed"
            elif change == "option": leaf.definition.options["PythonModule/IsPython"] = False
            elif change == "static": leaf.gain.raw = "0.75"
            else: leaf.isBypassed = lambda: True
            with self.subTest(change=change), self.native(model):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def test_metadata_leaf_exception_refuses_network_contents_and_incomplete_apis(self):
        cases = ("network", "children", "Contents", "Contents.gz", "network_nonbool", "network_missing",
                 "children_missing", "children_invalid", "matches_nonbool", "matches_missing",
                 "editable", "editable_inside", "delayed", "root_unmatched")
        for case in cases:
            model = self.metadata_leaf_model()
            with self.native(model):
                leaf = model[-1]
                if case == "network": leaf.isNetwork = lambda: True
                elif case == "children":
                    leaf.descendants = [Node(leaf.path() + "/unexpected", internal=True)]
                    leaf.isNetwork = lambda: False
                elif case in ("Contents", "Contents.gz"): leaf.definition.data[case] = Section(b"network")
                elif case == "network_nonbool": leaf.isNetwork = lambda: 0
                elif case == "network_missing": leaf.isNetwork = None
                elif case == "children_missing": leaf.children = None
                elif case == "children_invalid": leaf.children = lambda: ""
                elif case == "matches_nonbool": leaf.matches = 0
                elif case == "matches_missing": leaf.matchesCurrentDefinition = None
                elif case == "editable": leaf.editable = True
                elif case == "editable_inside": leaf.editable_inside = True
                elif case == "delayed": leaf.delayed = True
                else: model[1].matches = False
                with self.subTest(case=case), self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_native_command_scene_contract("abc123", {"root_path": model[0].path()})
                self.assertEqual(caught.exception.code, "SCENE_CONTRACT_HDA_UNPROVEN")

    def test_definition_numeric_options_preserve_scalars_and_normalize_arrays(self):
        import hashlib
        model = self.model()
        definition = model[1].definition
        definition.options = {"enabled": True, "count": 2, "scale": 0.5, "label": "stable"}
        expected = {"type": "Sop/demo::1.0", "category": "Sop", "version": "1.0",
            "sections": [{"name": name, "bytes": len(section.contents),
                          "sha256": hashlib.sha256(section.contents).hexdigest()}
                         for name, section in sorted(definition.data.items())],
            "extra_file_options": dict(definition.options), "extra_info": definition.info}
        self.assertEqual(self.addon._fx_hda_definition_identity(model[1]),
                         {**expected, "sha256": self.addon._fx_scene_contract_digest(expected)})
        definition.options.update({"CursorA": (16, 5), "CursorB": [10, 1], "CursorC": (0, 0),
                                   "Numeric": (0.25, -2, 3.5)})
        contract = self.capture(model)
        options = contract["hda_boundaries"][0]["definition"]["extra_file_options"]
        self.assertEqual(options, {**expected["extra_file_options"], "CursorA": [16, 5],
            "CursorB": [10, 1], "CursorC": [0, 0], "Numeric": [0.25, -2, 3.5]})
        self.assertIsInstance(definition.options["CursorA"], tuple)
        with self.native(model):
            self.assertTrue(self.addon._fx_verify_scene_contract_nodes(contract, "abc123")["nodes_verified"])

    def test_definition_numeric_option_order_length_and_values_are_bound(self):
        for changed in ((5, 16), (16,), (16, 6)):
            model = self.model()
            model[1].definition.options["Cursor"] = (16, 5)
            contract = self.capture(model)
            model[1].definition.options["Cursor"] = changed
            with self.subTest(changed=changed), self.native(model):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def test_definition_options_refuse_unknown_objects_and_nonfinite_values(self):
        class NumericTuple(tuple): pass
        invalid = (object(), {"x": 1}, ("16", 5), (True, 5), ((16, 5),),
                   NumericTuple((16, 5)), (float("nan"), 5), [16, float("inf")], float("-inf"))
        for value in invalid:
            model = self.model()
            model[1].definition.options["UnsupportedOption"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaisesRegex(
                    self.addon.BridgeCommandError, "UnsupportedOption") as caught:
                self.capture(model)
            self.assertEqual(caught.exception.code, "SCENE_CONTRACT_HDA_UNPROVEN")

    def test_definition_and_static_mutations_are_rejected(self):
        cases = ("section", "option", "info", "child_definition", "static_parm", "user_data", "wire", "static_flag", "public_value", "public_driver", "public_connection")
        for case in cases:
            model = self.model()
            contract = self.capture(model)
            root, asset, nested, leaf = model
            if case == "section": asset.definition.data["PythonModule"].contents = b"changed"
            elif case == "option": asset.definition.options["PythonModule/IsPython"] = False
            elif case == "info": asset.definition.info = "changed"
            elif case == "child_definition": nested.definition.data["Contents"].contents = b"replacement"
            elif case == "static_parm": leaf.gain.raw = "0.7"
            elif case == "user_data": leaf.data["tag"] = "changed"
            elif case == "wire": leaf.connections = [SimpleNamespace(inputIndex=lambda: 0, inputNode=lambda: nested, outputIndex=lambda: 1, subnetIndirectInput=lambda: None, inputItem=lambda: nested)]
            elif case == "static_flag": leaf.isBypassed = lambda: True
            elif case == "public_value": asset.gain.value = 0.9
            elif case == "public_driver": asset.gain.expression = lambda: 'ch("../upstream/gain")'
            elif case == "public_connection": asset.input_nodes = [root]
            with self.subTest(case=case), self.native(model):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._fx_verify_scene_contract_nodes(contract, "abc123")
                self.assertEqual(caught.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def test_unproven_hda_conditions_refuse_instead_of_falling_back_to_legacy(self):
        cases = ("editable", "editable_inside", "delayed", "missing_definition", "missing_api", "bad_section",
                 "missing_section_api", "hard_lock", "data", "static_read", "unmatched", "unknown_child_definition", "missing_flag")
        for case in cases:
            model = self.model()
            root, asset, nested, leaf = model
            if case == "editable": leaf.editable = True
            elif case == "editable_inside": leaf.editable_inside = True
            elif case == "delayed": asset.delayed = True
            elif case == "missing_definition": asset.definition = None
            elif case == "missing_api": leaf.isEditableInsideLockedHDA = None
            elif case == "bad_section": asset.definition.data["Contents"].contents = "not binary"
            elif case == "missing_section_api": asset.definition.data["Contents"].binaryContents = None
            elif case == "hard_lock": leaf.hard_locked = True
            elif case == "data": leaf.gain.kind = "Data"
            elif case == "static_read":
                leaf.gain.unexpandedString = lambda: (_ for _ in ()).throw(ValueError("unreadable"))
                leaf.gain.rawValue = leaf.gain.unexpandedString
            elif case == "unmatched": asset.matches = False
            elif case == "missing_flag": leaf.isBypassed = None
            elif case == "unknown_child_definition": leaf.type = lambda: SimpleNamespace(nameWithCategory=lambda: "Sop/null", category=lambda: SimpleNamespace(name=lambda: "Sop"))
            with self.subTest(case=case):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.capture(model)
                self.assertEqual(caught.exception.code, "SCENE_CONTRACT_HDA_UNPROVEN")
                self.assertEqual(leaf.gain.reads, 0)

    def test_incomplete_static_identity_reports_bounded_errors_without_accepting(self):
        model = self.model()
        errors = ["error-{}:".format(index) + "x" * 240 for index in range(6)]
        incomplete = {"identity_complete": False, "node_count": 7, "errors": errors}
        with patch.object(self.addon, "_houdini_node_graph_fingerprint", return_value=incomplete):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.capture(model)
        self.assertEqual(caught.exception.code, "SCENE_CONTRACT_HDA_UNPROVEN")
        message = str(caught.exception)
        self.assertIn("node_count=7", message)
        for error in errors[:4]: self.assertIn(error[:200], message)
        self.assertNotIn(errors[0][:201], message)
        self.assertNotIn("error-4:", message)
        self.assertFalse(incomplete["identity_complete"])
        self.assertEqual(incomplete["errors"], errors)

    def test_explicit_internal_registration_still_has_public_evaluated_readback(self):
        model = self.model()
        root = model[0]
        manifest = {"task_id": "abc123", "execution_root": root.path(), "graph_hash": "",
                    "nodes": {"root": root.path(), "asset": model[1].path(), "explicit": model[3].path()}}
        with self.native(model), patch.object(self.addon, "_fx_manifest", return_value=(root, manifest)):
            contract = self.addon._fx_capture_scene_contract("abc123")
        self.assertIn(model[3].path(), [record["path"] for record in contract["nodes"]])
        boundary = contract["hda_boundaries"][0]
        self.assertEqual(boundary["internal_node_count"], 1)
        self.assertEqual(boundary["static_fingerprint"]["node_count"], 2)
        self.assertEqual(model[3].gain.reads, 1)
        self.assertEqual(model[2].gain.reads, 0)

    def test_legacy_full_capture_keeps_internal_values_schema_and_digest_bytes(self):
        model = self.model()
        legacy = self.capture(model, "legacy-full/2.0")
        self.assertEqual(legacy["schema"], "houdini.task_scene_contract/2.0")
        self.assertNotIn("capture_policy", legacy)
        self.assertNotIn("hda_boundaries", legacy)
        self.assertEqual(len(legacy["nodes"]), 4)
        self.assertEqual([node.gain.reads for node in model], [1, 1, 1, 1])
        before = json.dumps(legacy, separators=(",", ":"), sort_keys=True).encode()
        digest = self.addon._fx_scene_contract_digest(legacy)
        with self.native(model):
            self.addon._fx_verify_scene_contract_nodes(legacy, "abc123")
        self.assertEqual(json.dumps(legacy, separators=(",", ":"), sort_keys=True).encode(), before)
        self.assertEqual(self.addon._fx_scene_contract_digest(legacy), digest)

    def test_explicit_registered_path_is_scoped_before_any_node_read(self):
        model = self.model()
        with self.native(model), patch.object(sys.modules["hou"], "node") as lookup:
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon._fx_scene_contract_nodes([model[0].path()], {"foreign": "/obj/foreign/node"})
            self.assertEqual(caught.exception.code, "SCENE_CONTRACT_NODE_MISSING")
            lookup.assert_not_called()

    def test_ordinary_capture_remains_legacy_and_internal_nodes_still_count_toward_limit(self):
        root, *_ = self.model()
        root.descendants = []
        self.assertEqual(self.capture((root,))["schema"], "houdini.task_scene_contract/2.0")
        model = self.model()
        model[2].descendants = [Node(model[2].path() + "/n" + str(i), internal=True) for i in range(126)]
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.capture(model)
        self.assertEqual(caught.exception.code, "SCENE_CONTRACT_TOO_LARGE")


if __name__ == "__main__": unittest.main()
