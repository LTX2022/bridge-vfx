"""R4 S-06 contracts, controller, and narrow fake-HOM adapter tests.

The fake host in this file is an evidence seam only.  It does not import a
Houdini installation, evaluate VEX, run a native solver, write a cache, or
render an image.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def _install_packages() -> None:
    for package in ("dcc-task-runtime", "vfx-pipeline", "houdini-bridge", "nuke-bridge"):
        path = ROOT / "packages" / package / "src"
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module could not be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Primitive:
    def __init__(self, name: str):
        self.name = name

    def intrinsicValue(self, key: str):
        if key != "name":
            raise KeyError(key)
        return self.name


class _Geometry:
    def __init__(self, names):
        self._prims = [_Primitive(name) for name in names]

    def prims(self):
        return tuple(self._prims)

    def points(self):
        return (object(),) if self._prims else ()

    def pointAttribs(self):
        return ()


class _Parm:
    def __init__(self, value):
        self.value = value

    def eval(self):
        return self.value() if callable(self.value) else self.value


class _Node:
    def __init__(self, path: str, parms=None, fields=(), snapshot=None):
        self._path = path
        self._parms = dict(parms or {})
        self._geometry = _Geometry(fields)
        self._snapshot = snapshot
        self.cook_calls = 0

    def path(self):
        return self._path

    def parm(self, name: str):
        return self._parms.get(name)

    def geometry(self):
        return self._geometry

    def errors(self):
        return ()

    def cook(self, force=False):
        self.cook_calls += 1


class _Root(_Node):
    def __init__(self, path: str, *, snapshot, writer_inventory=True):
        super().__init__(path)
        self._snapshot = snapshot
        self.writer_inventory = writer_inventory
        self.data = {}

    def userData(self, key):
        return self.data.get(key)

    def setUserData(self, key, value):
        self.data[key] = value


def _boundary(frame, operation_id="op_s06_fake"):
    return {
        "schema": "bridge.f2.sourcing-boundary/1.0",
        "frame": frame,
        "before": {
            "stage": "pre_sourcing_readback", "frame": frame,
            "freshness_token": "before-{}".format(frame), "field_generation": 10 + frame,
        },
        "operation": {
            "status": "performed", "operation_id": operation_id,
            "source_binding_write": True, "solver_refresh": True, "input_index": 0,
        },
        "after": {
            "stage": "post_sourcing_readback", "frame": frame,
            "freshness_token": "after-{}".format(frame), "field_generation": 20 + frame,
        },
    }


class _NativeProvider:
    """Fixture-only implementation of the exact versioned native seam."""

    schema = "bridge.f2.s06-native-host-adapter/1.0"

    def __init__(self, *, field=True, writer=True, boundary=True):
        if not field:
            self.field_snapshot = None
        if not writer:
            self.velocity_writer_inventory = None
        if not boundary:
            self.observe_sourcing_boundary = None

    def capabilities(self):
        interfaces = {}
        for name in (
            "field_snapshot", "apply_velocity_sentinel",
            "velocity_writer_inventory", "observe_sourcing_boundary",
        ):
            interfaces[name] = {
                "status": "verified" if callable(getattr(self, name, None)) else "unimplemented",
                "fixture_only": True,
            }
        return {
            "schema": self.schema,
            "provider_version": "1.0",
            "houdini_build": "21.0.631",
            "interfaces": interfaces,
            "ready_for_mutation": all(item["status"] == "verified" for item in interfaces.values()),
            "live_verified": False,
        }

    def field_snapshot(self, node, field, stage, frame):
        if field != "vel" or node._snapshot is None:
            return {"snapshot": None, "freshness": {}}
        return {
            "snapshot": json.loads(json.dumps(node._snapshot)),
            "freshness": {
                "stage": stage, "frame": frame,
                "freshness_token": "field-{}-{}".format(stage, frame),
                "field_generation": 1,
            },
        }

    def apply_velocity_sentinel(self, root, sentinel):
        return {
            "applied": True,
            "readback_verified": True,
            "field": "vel",
            "readback": json.loads(json.dumps(root._snapshot)),
        }

    def velocity_writer_inventory(self, root, manifest):
        return {
            "complete": True,
            "other_writers": [],
            "owned_writers": [root.path()],
            "field_writer_scope_complete": True,
        }

    def observe_sourcing_boundary(self, solver, source, frame, rows, request):
        solver.cook(force=True)
        snapshot = json.loads(json.dumps(solver._snapshot))
        return {
            "before_snapshot": snapshot,
            "after_snapshot": snapshot,
            "sourcing_boundary": _boundary(frame, request["operation_id"]),
            "cook_succeeded": True,
            "cook_errors": [],
            "output_nonempty": True,
        }


class _HoudiniDouble:
    def __init__(self, nodes, *, frame=1, native_provider=None):
        self.nodes = dict(nodes)
        self.current_frame = frame
        if native_provider is not None:
            self.bridge_s06_native_adapter_v1 = native_provider

    def node(self, path):
        return self.nodes.get(path)

    def setFrame(self, frame):
        self.current_frame = frame

    def frame(self):
        return self.current_frame

    def applicationVersionString(self):
        return "21.0.631"


class _ObjNode:
    def __init__(self, children=()):
        self._children = list(children)

    def children(self):
        return tuple(self._children)


class _GraphRoot(_Root):
    def __init__(self, path, *, children, snapshot):
        super().__init__(path, snapshot=snapshot)
        self._graph_children = list(children)

    def allSubChildren(self):
        return tuple(self._graph_children)


class _ActualInspectHarness:
    """Fixture scene that is inspected through the production addon function."""

    def __init__(self, addon, hip_path, label, snapshot):
        self.addon = addon
        self.hip_path = str(Path(hip_path).resolve())
        self.identity = {
            "session_id": "session_" + label,
            "process_generation": "process_" + label,
            "scene_id": "scene_" + label,
            "hip_path": self.hip_path,
        }
        self.provider = _NativeProvider()
        self.snapshot = snapshot
        self.root = None
        self.dirty = False

    def mark_built(self, manifest):
        nodes = manifest["nodes"]
        children = [_Node(nodes["solver"]), _Node(nodes["source_volume"])]
        self.root = _GraphRoot(manifest["execution_root"], children=children, snapshot=self.snapshot)
        self.dirty = True

    def inspect(self, record=None):
        nodes = {"/obj": _ObjNode([self.root] if self.root is not None else [])}
        if self.root is not None:
            nodes[self.root.path()] = self.root
            nodes.update({child.path(): child for child in self.root._graph_children})
        hou = SimpleNamespace(
            applicationVersionString=lambda: "21.0.631",
            hipFile=SimpleNamespace(
                path=lambda: self.hip_path,
                hasUnsavedChanges=lambda: self.dirty,
            ),
            node=lambda path: nodes.get(path),
            bridge_s06_native_adapter_v1=self.provider,
        )
        params = {"ownership_record": dict(record)} if isinstance(record, dict) else None
        with patch.dict(sys.modules, {"hou": hou}), patch.object(
            self.addon, "bridge_scene_identity", return_value=dict(self.identity),
        ):
            return self.addon.bridge_s06_inspect_scene(params)


class _ControllerTransport:
    """Structured transport double for the controller/adaptor software seam."""

    def __init__(self, probe, *, root, sentinel, inspect_callback=None, on_build=None, inconclusive=False):
        self.probe = dict(probe)
        self.root = root
        self.sentinel = sentinel
        self.inspect_callback = inspect_callback
        self.on_build = on_build
        self.inconclusive = inconclusive
        self.calls = []

    def call(self, command, params):
        self.calls.append((command, dict(params)))
        if command == "bridge.s06.inspect_scene":
            data = (
                self.inspect_callback(params.get("ownership_record"))
                if callable(self.inspect_callback)
                else dict(self.probe)
            )
            return {"status": "success", "data": data}
        if command != "bridge.s06.short_segment":
            raise AssertionError(command)
        if params.get("s06_action") == "build":
            manifest = {
                "task_id": params["s06_controller_request"]["task_id"],
                "execution_root": self.root,
                "domain_pack": "pyro_smoke_v1",
                "nodes": {
                    "solver": self.root + "/FX_SOLVER",
                    "source_volume": self.root + "/FX_SOURCE_VOLUME",
                },
            }
            if callable(self.on_build):
                self.on_build(manifest)
            return {
                "status": "success",
                "data": {
                    "scene_manifest": manifest,
                    "simulation_cache_written": False,
                    "render_started": False,
                },
            }
        if params.get("s06_action") == "observe":
            frame = params["frame"]
            active = frame == 2
            if active:
                evidence = self.velocity.not_applicable(frame=frame)
                before = None
            else:
                evidence = self.velocity.compare_inactive_velocity(
                    self.sentinel,
                    self.sentinel,
                    frame=frame,
                    before_frame=frame,
                    after_frame=frame,
                    row2_active_before=False,
                    row2_active_after=False,
                    source_effect_isolated=True,
                    no_other_velocity_writers=True,
                    sourcing_boundary=_boundary(frame),
                )
                before = self.sentinel
            return {
                "status": "success",
                "data": {
                    "actual_frame": frame,
                    "solver_path": self.root + "/FX_SOLVER",
                    "execution_root": self.root,
                    "source_fields": ["density", "v"],
                    "target_fields": ["density", "vel"],
                    "active_source_windows": [
                        {"row": 1, "active": active, "source_volume": "density", "target_field": "density"},
                        {"row": 2, "active": active, "source_volume": "v", "target_field": "vel"},
                    ],
                    "velocity_preservation": evidence,
                    "velocity_field_readback": {
                        "field": "vel",
                        "before_snapshot": before,
                        "after_snapshot": self.sentinel,
                        "same_stop_frame": {"before_frame": frame if before is not None else None, "after_frame": frame},
                        "sourcing_boundary": _boundary(frame),
                        "writer_inventory": {"status": "pass", "complete": True, "other_writers": []},
                        "sentinel": {"status": "pass", "readback_verified": True, "readback": self.sentinel},
                    },
                    "output_nonempty": not self.inconclusive,
                    "cook_succeeded": True,
                    "cook_errors": [],
                },
            }
        raise AssertionError("unknown S-06 action")


class S06R4ContractAndAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_packages()
        cls.velocity = __import__("vfx_pipeline.s06_velocity", fromlist=["s06_velocity"])
        cls.contracts = __import__("vfx_pipeline.s06_contracts", fromlist=["s06_contracts"])
        cls.addon = _load(ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py", "s06_r4_addon_under_test")
        cls.controller = _load(ROOT / "tools/s06_controller.py", "s06_r4_controller_under_test")
        cls.validator = _load(ROOT / "tools/validate_f2_solver_sourcing.py", "s06_r4_validator_under_test")

    def setUp(self):
        # The production adapter fences every observation with the persistent
        # task-root lease.  Keep this synthetic HOM fixture inside an isolated
        # lease directory rather than weakening the production fence.
        self._lease_tmp = tempfile.TemporaryDirectory(prefix="s06-r4-lease-")
        self.addCleanup(self._lease_tmp.cleanup)
        self._state_dir_patch = patch.object(
            self.addon, "_state_dir", return_value=Path(self._lease_tmp.name) / "instances"
        )
        self._state_dir_patch.start()
        self.addCleanup(self._state_dir_patch.stop)

    def _sentinel(self):
        return self.velocity.default_controller_sentinel()

    def _adapter_params(self, *, frame=1, writer_inventory=True, field_hook=True):
        root = "/obj/BRIDGE_GRAPH_" + "c" * 64
        solver_path = root + "/FX_SOLVER"
        source_path = root + "/FX_SOURCE_VOLUME"
        sentinel = self._sentinel()
        active = lambda: self.hou.current_frame in {2}
        parms = {
            "source_activate1": _Parm(active),
            "source_activate2": _Parm(active),
            "source_volume1": _Parm("density"),
            "source_vfield1": _Parm("density"),
            "source_volume2": _Parm("v"),
            "source_vfield2": _Parm("vel"),
        }
        solver = _Node(solver_path, parms=parms, fields=("density", "vel"), snapshot=sentinel if field_hook else None)
        source = _Node(source_path, fields=("density", "v"))
        root_node = _Root(root, snapshot=sentinel, writer_inventory=writer_inventory)
        self.native_provider = _NativeProvider(field=field_hook, writer=writer_inventory)
        self.hou = _HoudiniDouble(
            {root: root_node, solver_path: solver, source_path: source},
            frame=frame, native_provider=self.native_provider,
        )
        self.addon._root_lease_issue(root, "task_s06_fake", scope="sop")
        self.manifest = {
            "task_id": "task_s06_fake",
            "domain_pack": "pyro_smoke_v1",
            "execution_root": root,
            "nodes": {"solver": solver_path, "source_volume": source_path},
            "s06_adapter": {
                "velocity_sentinel": {
                    "status": "pass", "applied": True, "readback_verified": True,
                    "field": "vel", "digest_sha256": sentinel["digest_sha256"],
                    "readback": sentinel,
                },
            },
        }
        identity = {
            "session_id": "session_s06_fake",
            "process_generation": "process_s06_fake",
            "scene_id": "scene_s06_fake",
            "hip_path": str(Path(self._lease_tmp.name).resolve() / "s06-fake.hip"),
        }
        frame_segment = {
            "start": 1, "end": 3, "step": 1, "preroll_frames": 0,
            "max_elapsed_seconds": 30.0, "max_cook_seconds_per_frame": 5.0,
        }
        schedule = {
            "schema": self.contracts.SCHEDULE_SCHEMA,
            "frame_start": 1, "frame_end": 3, "step": 1,
            "rows": {"1": [{"start": 2, "end": 3}], "2": [{"start": 2, "end": 3}]},
        }
        source_binding = {
            "capture_file_sha256": self.addon._SOLVER_SOURCING_CAPTURE_SHA256,
            "snapshot_sha256": self.addon._SOLVER_SOURCING_TEMPLATE_SNAPSHOT_SHA256,
            "capture_state": "CAPTURED_NOT_BOUND",
        }
        request = self.contracts.controller_request_core(
            task_id="task_s06_fake", operation_id="op_s06_fake", request_id="req_s06_fake",
            execution_root=root, host_identity=identity, frame_segment=frame_segment,
            source_schedule=schedule, source_binding=source_binding, velocity_sentinel=sentinel,
            authorization_hash_value="a" * 64,
        )
        params = {
            "task_id": "task_s06_fake",
            "step_params": {"domain_pack": "pyro_smoke_v1", "source_plan": {}},
            "s06_action": "observe", "frame": frame,
            "solver_path": solver_path, "source_path": source_path,
            "s06_controller_request": request,
            "s06_controller_request_hash": self.contracts.controller_request_hash(request),
            "bridge_graph_root": root,
            "bridge_execution_binding": {
                "schema": self.contracts.HOST_BINDING_SCHEMA,
                "task_id": "task_s06_fake", "operation_id": "op_s06_fake",
                "host_identity": identity, "execution_root": root,
            },
            "f2_short_segment": {
                "schema": self.contracts.INTENT_SCHEMA,
                "frame_segment": frame_segment, "source_binding": source_binding,
                "source_schedule": schedule, "cache_allowed": False, "render_allowed": False,
            },
        }
        return params, root_node, solver, source, self.manifest

    def test_componentwise_comparison_rejects_same_aggregate_different_direction(self):
        before = self.velocity.make_snapshot(
            field="vel", sample_domain={"kind": "voxels", "indices": [[0], [1]]},
            coordinate_space="object", units={"velocity": "scene_units_per_second"},
            component_order=["x", "y", "z"], values=[[1, 0, 0], [-1, 0, 0]],
        )
        after = self.velocity.make_snapshot(
            field="vel", sample_domain={"kind": "voxels", "indices": [[0], [1]]},
            coordinate_space="object", units={"velocity": "scene_units_per_second"},
            component_order=["x", "y", "z"], values=[[0, 1, 0], [0, -1, 0]],
        )
        result = self.velocity.compare_inactive_velocity(
            before, after, frame=4, before_frame=4, after_frame=4,
            source_effect_isolated=True, no_other_velocity_writers=True,
            sourcing_boundary=_boundary(4),
        )
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "VELOCITY_COMPONENT_MISMATCH")
        self.assertEqual(result["before_aggregate"]["sum"], result["after_aggregate"]["sum"])

    def test_zero_baseline_missing_domain_and_other_writer_are_not_pass(self):
        zero = self.velocity.make_snapshot(
            field="vel", sample_domain={"kind": "voxels", "indices": [[0]]},
            coordinate_space="object", units={"velocity": "scene_units_per_second"},
            component_order=["x", "y", "z"], values=[[0, 0, 0]],
        )
        sentinel = self._sentinel()
        zero_result = self.velocity.compare_inactive_velocity(
            zero, zero, frame=1, before_frame=1, after_frame=1,
            source_effect_isolated=True, no_other_velocity_writers=True,
            sourcing_boundary=_boundary(1),
        )
        self.assertEqual(zero_result["status"], "unknown")
        self.assertEqual(zero_result["reason"], "VELOCITY_BASELINE_ZERO")
        wrong_domain = self.velocity.make_snapshot(
            field="vel", sample_domain={"kind": "different", "indices": [[0], [1]]},
            coordinate_space="object", units={"velocity": "scene_units_per_second"},
            component_order=["x", "y", "z"], values=sentinel["values"],
        )
        domain_result = self.velocity.compare_inactive_velocity(
            sentinel, wrong_domain, frame=1, before_frame=1, after_frame=1,
            source_effect_isolated=True, no_other_velocity_writers=True,
            sourcing_boundary=_boundary(1),
        )
        self.assertEqual(domain_result["status"], "fail")
        writer_result = self.velocity.compare_inactive_velocity(
            sentinel, sentinel, frame=1, before_frame=1, after_frame=1,
            source_effect_isolated=True, no_other_velocity_writers=False,
            sourcing_boundary=_boundary(1),
        )
        self.assertEqual(writer_result["status"], "unknown")

    def test_active_frame_is_explicitly_not_applicable(self):
        record = self.velocity.not_applicable(frame=2)
        self.assertEqual(record["applicability"], "not_applicable")
        self.assertEqual(record["status"], "not_applicable")
        self.assertEqual(self.velocity.validate_evidence_record(record, row2_active=True), [])

    def test_fake_hom_adapter_emits_structured_same_frame_velocity_evidence(self):
        params, root_node, solver, _source, manifest = self._adapter_params(frame=1)
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(self.addon, "_fx_manifest", return_value=(root_node, manifest)):
            result = self.addon.bridge_s06_short_segment_adapter(params)
        evidence = result["velocity_preservation"]
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["comparison_method"], "sourcing_boundary_componentwise")
        self.assertEqual(result["velocity_field_readback"]["before_snapshot"]["sample_count"], 2)
        self.assertEqual(result["velocity_field_readback"]["after_snapshot"]["component_order"], ["x", "y", "z"])
        self.assertEqual(result["velocity_field_readback"]["sourcing_boundary"]["before"]["stage"], "pre_sourcing_readback")
        self.assertEqual(solver.cook_calls, 1)

        params["frame"] = 2
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(self.addon, "_fx_manifest", return_value=(root_node, manifest)):
            active_result = self.addon.bridge_s06_short_segment_adapter(params)
        self.assertEqual(active_result["velocity_preservation"]["status"], "not_applicable")
        self.assertIsNone(active_result["velocity_field_readback"]["before_snapshot"])

    def test_adapter_stays_unknown_when_field_or_writer_scope_hook_is_missing(self):
        params, root_node, _solver, _source, manifest = self._adapter_params(frame=1, writer_inventory=False, field_hook=False)
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(self.addon, "_fx_manifest", return_value=(root_node, manifest)):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.bridge_s06_short_segment_adapter(params)
        self.assertEqual(caught.exception.code, "S06_HOST_CAPABILITY_UNAVAILABLE")

    def test_bare_sentinel_boolean_cannot_create_isolation_evidence(self):
        params, root_node, _solver, _source, manifest = self._adapter_params(frame=1)
        params["s06_action"] = "observe"
        manifest["s06_adapter"]["velocity_sentinel"] = {
            "status": "pass", "applied": True, "readback_verified": True,
            "field": "vel", "digest_sha256": self._sentinel()["digest_sha256"],
        }
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(self.addon, "_fx_manifest", return_value=(root_node, manifest)):
            result = self.addon.bridge_s06_short_segment_adapter(params)
        self.assertEqual(result["velocity_preservation"]["status"], "unknown")
        self.assertEqual(result["velocity_preservation"]["reason"], "SOURCE_EFFECT_NOT_ISOLATED")

    def test_actual_addon_inspect_is_unregistered_then_matches_controller_record(self):
        with tempfile.TemporaryDirectory(prefix="s06-r4-inspect-") as temporary:
            hip_path = Path(temporary).resolve() / "owned.hip"
            hip_path.write_bytes(b"fake gui hip bytes")
            identity = {
                "session_id": "session_s06_inspect",
                "process_generation": "process_s06_inspect",
                "scene_id": "scene_s06_inspect",
                "hip_path": str(hip_path),
            }
            provider = _NativeProvider()
            obj = _ObjNode()
            hou = SimpleNamespace(
                applicationVersionString=lambda: "21.0.631",
                hipFile=SimpleNamespace(path=lambda: str(hip_path), hasUnsavedChanges=lambda: False),
                node=lambda path: obj if path == "/obj" else None,
                bridge_s06_native_adapter_v1=provider,
            )
            with patch.dict(sys.modules, {"hou": hou}), patch.object(self.addon, "bridge_scene_identity", return_value=identity):
                probe = self.addon.bridge_s06_inspect_scene()
            self.assertFalse(probe["owned_project"])
            self.assertFalse(probe["fresh_project"])
            self.assertEqual(probe["ownership_evidence"]["record_status"], "ABSENT")
            self.assertEqual(probe["host_capabilities"]["status"], "READY")
            self.assertEqual(self.controller._host_probe_failures(probe), [])

            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="inspect_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]],
                params={"step_params": {"domain_pack": "pyro_smoke_v1"}},
            )
            self.assertEqual(prepared["state"], "AUTHORIZED")
            record = prepared["bundle"]["scene_ownership"]
            self.assertTrue(Path(record["record_path"]).is_file())
            with patch.dict(sys.modules, {"hou": hou}), patch.object(self.addon, "bridge_scene_identity", return_value=identity):
                resumed = self.addon.bridge_s06_inspect_scene({"ownership_record": record})
            self.assertTrue(resumed["owned_project"])
            self.assertTrue(resumed["fresh_project"])
            self.assertEqual(resumed["ownership_evidence"]["record_status"], "MATCHED")
            self.assertEqual(self.controller._host_probe_failures(resumed, record), [])

    def test_completed_controller_record_allows_dirty_task_owned_resume(self):
        with tempfile.TemporaryDirectory(prefix="s06-r4-resume-") as temporary:
            hip_path = Path(temporary).resolve() / "owned.hip"
            hip_path.write_bytes(b"fake gui hip bytes")
            identity = {
                "session_id": "session_s06_resume", "process_generation": "process_s06_resume",
                "scene_id": "scene_s06_resume", "hip_path": str(hip_path),
            }
            provider = _NativeProvider()
            initial_obj = _ObjNode()
            initial_hou = SimpleNamespace(
                applicationVersionString=lambda: "21.0.631",
                hipFile=SimpleNamespace(path=lambda: str(hip_path), hasUnsavedChanges=lambda: False),
                node=lambda path: initial_obj if path == "/obj" else None,
                bridge_s06_native_adapter_v1=provider,
            )
            with patch.dict(sys.modules, {"hou": initial_hou}), patch.object(self.addon, "bridge_scene_identity", return_value=identity):
                probe = self.addon.bridge_s06_inspect_scene()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="resume_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]],
                params={"step_params": {"domain_pack": "pyro_smoke_v1"}},
            )
            record = prepared["bundle"]["scene_ownership"]
            root = prepared["graph_root"]
            solver_path = root + "/FX_SOLVER"
            source_path = root + "/FX_SOURCE_VOLUME"
            graph_root = _GraphRoot(
                root,
                children=[_Node(solver_path), _Node(source_path)],
                snapshot=self._sentinel(),
            )
            nodes = {"/obj": _ObjNode([graph_root]), root: graph_root, solver_path: graph_root._graph_children[0], source_path: graph_root._graph_children[1]}
            dirty_hou = SimpleNamespace(
                applicationVersionString=lambda: "21.0.631",
                hipFile=SimpleNamespace(path=lambda: str(hip_path), hasUnsavedChanges=lambda: True),
                node=lambda path: nodes.get(path),
                bridge_s06_native_adapter_v1=provider,
            )
            updated = controller._update_ownership_record(
                record,
                phase="GRAPH_MUTATION_COMPLETED",
                first_graph_mutation="completed",
                manifest={"nodes": {"solver": solver_path, "source_volume": source_path}},
            )
            with patch.dict(sys.modules, {"hou": dirty_hou}), patch.object(self.addon, "bridge_scene_identity", return_value=identity):
                resumed = self.addon.bridge_s06_inspect_scene({"ownership_record": updated})
            self.assertTrue(resumed["owned_project"])
            self.assertFalse(resumed["fresh_project"])
            self.assertTrue(resumed["has_unsaved_changes"])
            self.assertEqual(self.controller._host_probe_failures(resumed, updated), [])

    def test_missing_native_capability_blocks_before_first_write(self):
        params, _root_node, _solver, _source, _manifest = self._adapter_params(frame=1)
        del self.hou.bridge_s06_native_adapter_v1
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(
            self.addon, "_fx_build_preview", side_effect=AssertionError("build must not be called"),
        ):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.bridge_s06_short_segment_adapter({**params, "s06_action": "build"})
        self.assertEqual(caught.exception.code, "S06_HOST_CAPABILITY_UNAVAILABLE")

    def test_repeated_native_boundary_token_is_rejected(self):
        params, root_node, _solver, _source, manifest = self._adapter_params(frame=1)
        original = self.native_provider.observe_sourcing_boundary
        def stale(*args):
            value = original(*args)
            value["sourcing_boundary"]["after"]["freshness_token"] = value["sourcing_boundary"]["before"]["freshness_token"]
            value["sourcing_boundary"]["after"]["field_generation"] = value["sourcing_boundary"]["before"]["field_generation"]
            return value
        self.native_provider.observe_sourcing_boundary = stale
        with patch.dict(sys.modules, {"hou": self.hou}), patch.object(self.addon, "_fx_manifest", return_value=(root_node, manifest)):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.bridge_s06_short_segment_adapter(params)
        self.assertEqual(caught.exception.code, "S06_SOURCING_BOUNDARY_UNAVAILABLE")

    def test_generic_controller_bound_fx_route_is_rejected(self):
        with patch.dict(sys.modules, {"hou": SimpleNamespace()}):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("agent.fx.build_preview", {"bridge_execution_binding": {"schema": self.contracts.HOST_BINDING_SCHEMA}})
        self.assertEqual(caught.exception.code, "S06_ADAPTER_REQUIRED")

    def _controller_probe(self, hip_path):
        hip_path = Path(hip_path).resolve()
        hip_path.write_bytes(b"fake owned HIP evidence")
        file_evidence = self.controller._controller_file_evidence(str(hip_path))
        return {
            "houdini_version": "21.0.631",
            "route": {"reachable": True, "main_thread": True, "adapter": "bridge.s06.short_segment", "raw_code_allowed": False},
            "scene_identity": {
                "session_id": "session_s06_controller", "process_generation": "process_s06_controller",
                "scene_id": "scene_s06_controller", "hip_path": str(hip_path),
            },
            "saved": True, "has_unsaved_changes": False, "owned_project": False, "fresh_project": False,
            "read_only_capture_session": False, "children": [], "conflicting_nodes": [], "task_manifest_ids": [],
            "hip_sha256": file_evidence["sha256"],
            "file_evidence": file_evidence,
            "ownership_evidence": {
                "schema": "bridge.f2.s06-scene-ownership-evidence/1.0", "record_status": "ABSENT",
                "controller_record_supplied": False, "identity_match": False,
                "hip_file_match": False, "graph_match": False,
                "freshness_basis": "unregistered_read_only_probe",
            },
            "host_capabilities": {
                "schema": "bridge.f2.s06-host-capabilities/1.0", "status": "READY",
                "provider_attribute": "bridge_s06_native_adapter_v1",
                "provider_schema": "bridge.f2.s06-native-host-adapter/1.0",
                "required_interfaces": [
                    "field_snapshot", "apply_velocity_sentinel",
                    "velocity_writer_inventory", "observe_sourcing_boundary",
                ],
                "available_interfaces": [
                    "field_snapshot", "apply_velocity_sentinel",
                    "velocity_writer_inventory", "observe_sourcing_boundary",
                ],
                "missing_interfaces": [],
                "pre_mutation_action": "ALLOW_S06_ADAPTER",
            },
        }

    def test_controller_issues_complete_relations_and_blocks_unprepared_probe(self):
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-test-") as temporary:
            probe = self._controller_probe(Path(temporary) / "owned-s06-controller.hip")
            controller = self.controller.S06Controller(Path(temporary), controller_id="test_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]],
                params={"step_params": {"domain_pack": "pyro_smoke_v1"}},
            )
            self.assertEqual(prepared["state"], "AUTHORIZED")
            bundle = prepared["bundle"]
            self.assertNotEqual(prepared["graph_root"], prepared["scheduler_owner_root"])
            self.assertEqual(bundle["controller_issuance"]["first_graph_mutation"], "pending")
            self.assertEqual(bundle["controller_issuance"]["controller_request"]["velocity_sentinel"]["field"], "vel")
            failures = self.validator._validate_authorization_bundle(
                bundle, task_id=prepared["task_id"], operation_id=prepared["operation_id"],
                frame_start=1, frame_end=3, now=0,
            )
            self.assertEqual(failures, [])
            invalid = dict(probe)
            invalid["ownership_evidence"] = dict(probe["ownership_evidence"])
            invalid["ownership_evidence"]["record_status"] = "MATCHED"
            inspected = controller.inspect(invalid)
            self.assertEqual(inspected["state"], "BLOCKED")
            self.assertIn("SCENE_OWNERSHIP_RECORD_STATUS_INVALID", inspected["failures"])

    def test_controller_public_execution_binds_one_context_through_narrow_transport(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-exec-") as temporary:
            hip_path = Path(temporary) / "owned-s06-transport.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_transport", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary), controller_id="exec_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe,
                frame_start=1,
                frame_end=3,
                pulses=[[2, 3]],
                params=params,
            )
            self.assertEqual(prepared["state"], "AUTHORIZED")
            sentinel = self._sentinel()
            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=sentinel,
                inspect_callback=scene.inspect,
                on_build=scene.mark_built,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            self.assertEqual(transport.calls, [])
            result = controller.execute(
                prepared,
                adapter,
                params=params,
                operator_confirmed=True,
            )
            self.assertEqual(result["state"], "EXECUTED_HOST_SHORT_SEGMENT")
            self.assertTrue(result["output_verification"]["inactive_velocity_preserved_verified"])
            self.assertEqual(result["frames_checked"], 3)
            self.assertEqual(
                [command for command, _params in transport.calls],
                ["bridge.s06.inspect_scene", "bridge.s06.short_segment"] * 1
                + ["bridge.s06.short_segment"] * 3,
            )
            request_hashes = {
                payload["s06_controller_request_hash"]
                for command, payload in transport.calls[1:]
                if command == "bridge.s06.short_segment"
            }
            self.assertEqual(request_hashes, {prepared["controller_request_hash"]})
            roots = {
                payload["bridge_graph_root"]
                for command, payload in transport.calls[1:]
                if command == "bridge.s06.short_segment"
            }
            self.assertEqual(roots, {prepared["graph_root"]})

    def test_completed_receipt_replays_after_task_owned_dirty_scene_without_host_rerun(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-replay-") as temporary:
            hip_path = Path(temporary) / "owned-s06-replay.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_replay", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="replay_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]], params=params,
            )
            self.assertEqual(prepared["state"], "AUTHORIZED")
            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=self._sentinel(),
                inspect_callback=scene.inspect,
                on_build=scene.mark_built,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            first = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            second = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            ownership_path = Path(prepared["bundle"]["scene_ownership"]["record_path"])
            ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        self.assertEqual(first["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertEqual(second["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertTrue(second["replayed"])
        self.assertEqual(ownership["phase"], "GRAPH_MUTATION_COMPLETED")
        self.assertEqual(
            [command for command, _params in transport.calls],
            ["bridge.s06.inspect_scene", "bridge.s06.short_segment"]
            + ["bridge.s06.short_segment"] * 3
            + ["bridge.s06.inspect_scene"],
        )

    def test_controller_recovers_after_completion_marker_write_failure_without_host_rerun(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-marker-recovery-") as temporary:
            hip_path = Path(temporary) / "owned-s06-marker-recovery.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_marker_recovery", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="marker_recovery_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]], params=params,
            )
            self.assertEqual(prepared["state"], "AUTHORIZED")
            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=self._sentinel(),
                inspect_callback=scene.inspect,
                on_build=scene.mark_built,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            original_update = controller._update_ownership_record
            completion_failure = {"remaining": 1}

            def fail_once(record, **kwargs):
                if kwargs.get("phase") == "GRAPH_MUTATION_COMPLETED" and completion_failure["remaining"]:
                    completion_failure["remaining"] -= 1
                    raise OSError("injected completion marker write failure")
                return original_update(record, **kwargs)

            with patch.object(controller, "_update_ownership_record", side_effect=fail_once):
                first = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            receipt = controller.store.skill_execution_receipt(
                prepared["task_id"], prepared["bundle"]["execution_receipt"]["idempotency_key"],
            )
            second = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            ownership_path = Path(prepared["bundle"]["scene_ownership"]["record_path"])
            ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        self.assertEqual(first["state"], "UNKNOWN")
        self.assertEqual(first["reason"], "SCENE_OWNERSHIP_COMPLETION_RECORD_UNCERTAIN")
        self.assertEqual(receipt["status"], "COMPLETED")
        self.assertEqual(second["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertTrue(second["recovered"])
        self.assertEqual(second["host_mutation_calls"], 0)
        self.assertEqual(ownership["phase"], "GRAPH_MUTATION_COMPLETED")
        self.assertEqual(
            sum(command == "bridge.s06.short_segment" and payload.get("s06_action") == "build" for command, payload in transport.calls),
            1,
        )
        self.assertEqual(transport.calls[-1][0], "bridge.s06.inspect_scene")

    def test_controller_recovers_completed_inconclusive_receipt_without_host_rerun(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-inconclusive-recovery-") as temporary:
            hip_path = Path(temporary) / "owned-s06-inconclusive-recovery.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_inconclusive_recovery", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="inconclusive_recovery_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]], params=params,
            )
            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=self._sentinel(),
                inspect_callback=scene.inspect,
                on_build=scene.mark_built,
                inconclusive=True,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            original_update = controller._update_ownership_record
            completion_failure = {"remaining": 1}

            def fail_once(record, **kwargs):
                if kwargs.get("phase") == "GRAPH_MUTATION_COMPLETED" and completion_failure["remaining"]:
                    completion_failure["remaining"] -= 1
                    raise OSError("injected inconclusive completion marker failure")
                return original_update(record, **kwargs)

            with patch.object(controller, "_update_ownership_record", side_effect=fail_once):
                first = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            second = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            ownership_path = Path(prepared["bundle"]["scene_ownership"]["record_path"])
            ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        self.assertEqual(first["state"], "UNKNOWN")
        self.assertEqual(second["state"], "HOST_OUTPUT_INCONCLUSIVE")
        self.assertEqual(second["reason"], "HOST_OUTPUT_EMPTY")
        self.assertTrue(second["recovered"])
        self.assertEqual(second["host_mutation_calls"], 0)
        self.assertEqual(ownership["phase"], "GRAPH_MUTATION_COMPLETED")
        self.assertEqual(
            sum(command == "bridge.s06.short_segment" and payload.get("s06_action") == "build" for command, payload in transport.calls),
            1,
        )

    def test_controller_rejects_completed_receipt_when_hip_evidence_drifts(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-drift-recovery-") as temporary:
            hip_path = Path(temporary) / "owned-s06-drift-recovery.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_drift_recovery", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="drift_recovery_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]], params=params,
            )
            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=self._sentinel(),
                inspect_callback=scene.inspect,
                on_build=scene.mark_built,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            original_update = controller._update_ownership_record
            completion_failure = {"remaining": 1}

            def fail_once(record, **kwargs):
                if kwargs.get("phase") == "GRAPH_MUTATION_COMPLETED" and completion_failure["remaining"]:
                    completion_failure["remaining"] -= 1
                    raise OSError("injected drift-test completion marker failure")
                return original_update(record, **kwargs)

            with patch.object(controller, "_update_ownership_record", side_effect=fail_once):
                first = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            hip_path.write_bytes(b"changed HIP evidence after host completion")
            second = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            ownership_path = Path(prepared["bundle"]["scene_ownership"]["record_path"])
            ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        self.assertEqual(first["reason"], "SCENE_OWNERSHIP_COMPLETION_RECORD_UNCERTAIN")
        self.assertEqual(second["state"], "UNKNOWN")
        self.assertEqual(second["reason"], "SCENE_OWNERSHIP_RECOVERY_REJECTED")
        self.assertIn("SCENE_OWNERSHIP_RECOVERY_FILE_READBACK_MISMATCH", second["failures"])
        self.assertFalse(second.get("recovered", False))
        self.assertEqual(ownership["phase"], "GRAPH_MUTATION_STARTED")
        self.assertEqual(
            sum(command == "bridge.s06.short_segment" for command, _payload in transport.calls),
            4,
        )
        self.assertEqual(transport.calls[-1][0], "bridge.s06.inspect_scene")

    def test_controller_never_promotes_running_receipt_after_started_marker(self):
        params = {"step_params": {"domain_pack": "pyro_smoke_v1"}, "candidate": 1}
        with tempfile.TemporaryDirectory(prefix="s06-r4-controller-running-recovery-") as temporary:
            hip_path = Path(temporary) / "owned-s06-running-recovery.hip"
            hip_path.write_bytes(b"fake owned HIP evidence")
            scene = _ActualInspectHarness(self.addon, hip_path, "actual_running_recovery", self._sentinel())
            probe = scene.inspect()
            controller = self.controller.S06Controller(Path(temporary) / "controller", controller_id="running_recovery_controller")
            prepared = controller.prepare_authorization(
                scene_probe=probe, frame_start=1, frame_end=3, pulses=[[2, 3]], params=params,
            )

            def build_then_lose_response(manifest):
                scene.mark_built(manifest)
                raise RuntimeError("simulated lost host response")

            transport = _ControllerTransport(
                probe,
                root=prepared["graph_root"],
                sentinel=self._sentinel(),
                inspect_callback=scene.inspect,
                on_build=build_then_lose_response,
            )
            transport.velocity = self.velocity
            adapter = self.controller.S06MainThreadAdapter(transport)
            first = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
            calls_after_first = list(transport.calls)
            second = controller.execute(prepared, adapter, params=params, operator_confirmed=True)
        self.assertEqual(first["state"], "UNKNOWN")
        self.assertEqual(first["reason"], "HOST_RESULT_OR_EXECUTOR_UNCERTAIN")
        self.assertEqual(second["state"], "UNKNOWN")
        self.assertEqual(second["reason"], "SCENE_OWNERSHIP_MUTATION_IN_PROGRESS")
        self.assertIn("HOST_OPERATION_MUST_NOT_BE_RERUN", second["blockers"])
        self.assertEqual(transport.calls, calls_after_first)


if __name__ == "__main__":
    unittest.main()
