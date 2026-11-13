"""Production-shared fake-HOM tests for the partial S-06 native provider.

These tests exercise the same provider module loaded by the Houdini plugin.
The HOM objects are bounded in-memory doubles: they never start Houdini,
create nodes, cook, simulate, write VDB/cache files, or render.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
PROVIDER_PATH = ROOT / "plugins" / "houdini" / "_impl" / "s06_native_provider.py"
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module could not be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Type:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _BoundingBox:
    def __init__(self, minimum, maximum):
        self.minimum = tuple(minimum)
        self.maximum = tuple(maximum)

    def minvec(self):
        return self.minimum

    def maxvec(self):
        return self.maximum


class _Grid:
    def __init__(
        self,
        name,
        values,
        *,
        kind="Volume",
        resolution=(2, 1, 1),
        offset=(0, 0, 0),
        transform=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        voxel_size=(0.1, 0.1, 0.1),
        storage="float32",
        nonfinite_index=None,
    ):
        self._name = name
        self._values = dict(values)
        self._kind = kind
        self._resolution = tuple(resolution)
        self._offset = tuple(offset)
        self._transform = tuple(transform)
        self._voxel_size = tuple(voxel_size)
        self._storage = storage
        self._nonfinite_index = nonfinite_index
        self.voxel_calls = []

    def intrinsicValue(self, key):
        if key != "name":
            raise KeyError(key)
        return self._name

    def type(self):
        return _Type(self._kind)

    def resolution(self):
        return self._resolution

    def transform(self):
        return self._transform

    def voxelSize(self):
        return self._voxel_size

    def dataType(self):
        return self._storage

    def activeVoxelBoundingBox(self):
        maximum = tuple(
            self._offset[index] + self._resolution[index] - 1
            for index in range(3)
        )
        return _BoundingBox(self._offset, maximum)

    def activeVoxelCount(self):
        return len(self._values)

    def voxel(self, index):
        index = tuple(index)
        self.voxel_calls.append(index)
        if index == self._nonfinite_index:
            return float("nan")
        return self._values[index]


class _Geometry:
    def __init__(self, primitives):
        self._primitives = tuple(primitives)
        self.calls = 0

    def prims(self):
        self.calls += 1
        return self._primitives


class _FieldNode:
    def __init__(self, path, primitives):
        self._path = path
        self._geometry = _Geometry(primitives)
        self.bridge_calls = 0

    def path(self):
        return self._path

    def geometry(self):
        return self._geometry

    def bridge_field_snapshot(self, *args, **kwargs):
        self.bridge_calls += 1
        raise AssertionError("provider must not use a node bridge_* hook")


class _Hou:
    def __init__(self, *, frame=1, build="21.0.631"):
        self.current_frame = frame
        self.build = build

    def applicationVersionString(self):
        return self.build

    def frame(self):
        return self.current_frame


class _Parm:
    def __init__(self, value, *, template=None):
        self.value = value
        self.template = template

    def eval(self):
        return self.value

    def parmTemplate(self):
        return self.template


class _MenuTemplate:
    def __init__(self, items):
        self.items = tuple(items)

    def itemGeneratorScript(self):
        return ""

    def menuItems(self):
        return self.items


class _GraphNode:
    def __init__(self, path, node_type, parms=None):
        self._path = path
        self._type = _Type(node_type)
        self._parms = dict(parms or {})
        self._inputs = []
        self.cook_calls = 0

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def inputs(self):
        return tuple(self._inputs)

    def set_input(self, node):
        self._inputs = [node]

    def cook(self, *args, **kwargs):
        self.cook_calls += 1
        raise AssertionError("writer inventory must not cook")


class _GraphRoot(_GraphNode):
    def __init__(self, path, children):
        super().__init__(path, "geo")
        self._children = list(children)
        self._by_name = {child.path().rsplit("/", 1)[-1]: child for child in children}

    def children(self):
        return tuple(self._children)

    def node(self, name):
        return self._by_name.get(name)


class S06NativeProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider_module = _load(PROVIDER_PATH, "s06_native_provider_under_test")
        cls.addon = _load(ADDON_PATH, "s06_native_provider_addon_under_test")

    def provider(self, hou=None):
        return self.provider_module.S06NativeProvider(hou or _Hou())

    def component_node(self, *, mismatch=False, nonfinite=False):
        common = {
            "resolution": (2, 1, 1),
            "transform": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            "voxel_size": (0.1, 0.1, 0.1),
        }
        grids = []
        values = {
            (0, 0, 0): 1.0,
            (1, 0, 0): 0.5,
        }
        for index, name in enumerate(("vel.x", "vel.y", "vel.z")):
            options = dict(common)
            if mismatch and name == "vel.z":
                options["voxel_size"] = (0.2, 0.1, 0.1)
            grids.append(_Grid(name, values, nonfinite_index=(0, 0, 0) if nonfinite and index == 1 else None, **options))
        return _FieldNode("/obj/owned/FX_SOLVER", grids)

    def test_capabilities_are_partial_and_not_mutation_ready(self):
        capabilities = self.provider().capabilities()
        self.assertEqual(capabilities["schema"], self.provider_module.SCHEMA)
        self.assertEqual(capabilities["interfaces"]["field_snapshot"]["status"], "implemented")
        self.assertEqual(capabilities["interfaces"]["velocity_writer_inventory"]["status"], "implemented")
        self.assertEqual(capabilities["interfaces"]["apply_velocity_sentinel"]["status"], "unimplemented")
        self.assertEqual(capabilities["interfaces"]["observe_sourcing_boundary"]["status"], "unimplemented")
        self.assertFalse(capabilities["ready_for_mutation"])
        self.assertFalse(capabilities["live_verified"])
        self.assertEqual(capabilities["sourcing_contract"]["rows"][0]["source_field"], "density")
        self.assertEqual(capabilities["sourcing_contract"]["rows"][1]["target_field"], "vel")

    def test_install_is_idempotent_and_does_not_replace_unknown_provider(self):
        hou = _Hou()
        first = self.provider_module.install(hou)
        second = self.provider_module.install(hou)
        self.assertEqual(first["state"], "installed")
        self.assertEqual(second["state"], "already_installed")
        self.assertIs(first["provider"], second["provider"])

        conflict_hou = _Hou()
        existing = SimpleNamespace(schema=self.provider_module.SCHEMA)
        setattr(conflict_hou, self.provider_module.PROVIDER_ATTRIBUTE, existing)
        conflict = self.provider_module.install(conflict_hou)
        self.assertEqual(conflict["state"], "conflict")
        self.assertIs(getattr(conflict_hou, self.provider_module.PROVIDER_ATTRIBUTE), existing)

    def test_component_volume_snapshot_reads_hom_metadata_and_x_fastest_order(self):
        hou = _Hou(frame=7)
        provider = self.provider(hou)
        node = self.component_node()
        with provider.authorized_frame(7):
            result = provider.field_snapshot(node, "vel", "pre_sourcing_readback", 7)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["field"], "vel")
        self.assertEqual(snapshot["values"], [[1.0, 1.0, 1.0], [0.5, 0.5, 0.5]])
        self.assertEqual(snapshot["sample_domain"]["sampling_order"], "z_y_x_with_x_fastest")
        self.assertEqual(snapshot["sample_domain"]["indices"], [[0, 0, 0], [1, 0, 0]])
        self.assertEqual(snapshot["sample_domain"]["grid_metadata"][0]["resolution"], [2, 1, 1])
        self.assertEqual(snapshot["sample_domain"]["grid_metadata"][0]["voxel_size"], [0.1, 0.1, 0.1])
        self.assertEqual(snapshot["component_order"], ["x", "y", "z"])
        self.assertEqual(result["freshness"]["stage"], "pre_sourcing_readback")
        self.assertEqual(result["freshness"]["frame"], 7)
        self.assertEqual(node._geometry.calls, 1)
        self.assertEqual(node.bridge_calls, 0)

    def test_field_sampling_requires_authorized_frame_guard(self):
        node = self.component_node()
        with self.assertRaises(self.provider_module.NativeProviderError) as caught:
            self.provider().field_snapshot(node, "vel", "pre_sourcing_readback", 1)
        self.assertEqual(caught.exception.code, "FRAME_GUARD_REQUIRED")
        hou = _Hou(frame=2)
        provider = self.provider(hou)
        with self.assertRaises(self.provider_module.NativeProviderError) as caught:
            with provider.authorized_frame(1):
                pass
        self.assertEqual(caught.exception.code, "FRAME_GUARD_MISMATCH")

    def test_vector_vdb_snapshot_uses_active_index_offset(self):
        hou = _Hou(frame=3)
        provider = self.provider(hou)
        values = {(10, 20, 30): (1.0, 2.0, 3.0), (11, 20, 30): (4.0, 5.0, 6.0)}
        node = _FieldNode("/obj/owned/FX_SOLVER", [_Grid(
            "vel", values, kind="VDB", resolution=(2, 1, 1), offset=(10, 20, 30),
        )])
        with provider.authorized_frame(3):
            result = provider.field_snapshot(node, "vel", "post_sourcing_readback", 3)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["sample_domain"]["representation"], "vector")
        self.assertEqual(snapshot["sample_domain"]["active_index_offset"], [10, 20, 30])
        self.assertEqual(snapshot["sample_domain"]["indices"], [[10, 20, 30], [11, 20, 30]])
        self.assertEqual(snapshot["values"], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

    def test_field_binding_and_grid_errors_are_fail_closed(self):
        hou = _Hou(frame=1)
        provider = self.provider(hou)
        cases = [
            ([_Grid("vel.x", {(0, 0, 0): 1.0})], "FIELD_BINDING_INCOMPLETE"),
            ([_Grid("vel", {(0, 0, 0): 1.0})], "FIELD_COMPONENT_SHAPE_INVALID"),
            (self.component_node(mismatch=True)._geometry._primitives, "FIELD_GRID_MISMATCH"),
            (self.component_node(nonfinite=True)._geometry._primitives, "FIELD_COMPONENT_SHAPE_INVALID"),
        ]
        for primitives, code in cases:
            node = _FieldNode("/obj/owned/FX_SOLVER", primitives)
            with self.subTest(code=code):
                with self.assertRaises(self.provider_module.NativeProviderError) as caught:
                    with provider.authorized_frame(1):
                        provider.field_snapshot(node, "vel", "pre_sourcing_readback", 1)
                self.assertEqual(caught.exception.code, code)

        huge = _Grid("vel", {(0, 0, 0): (1.0, 2.0, 3.0)}, kind="VDB", resolution=(10**8, 10**8, 1))
        with self.assertRaises(self.provider_module.NativeProviderError) as caught:
            with provider.authorized_frame(1):
                provider.field_snapshot(_FieldNode("/obj/owned/FX_SOLVER", [huge]), "vel", "pre", 1)
        self.assertEqual(caught.exception.code, "FIELD_RESOLUTION_UNSAFE")

    def _fixed_graph(self):
        root_path = "/obj/BRIDGE_GRAPH_" + "a" * 64
        names = self.provider_module._GRAPH_ROLES
        nodes = {}
        source_program = self.addon._fx_source_program(
            [[1, 2]], [1.0, 0.0, 0.0], 30.0, 2.5, 1.0,
        )
        menu_templates = {
            "rank": _MenuTemplate(("scalar", "vector")),
            "operator": _MenuTemplate(("add", "copy")),
        }
        for role in names:
            parms = {}
            if role == "source_volume":
                parms["attributes"] = _Parm("density v")
            if role == "source_control":
                parms["snippet"] = _Parm(source_program)
            if role == "solver":
                parms.update({
                    "numsources": _Parm(2),
                    "source_volume1": _Parm("density"),
                    "source_vfield1": _Parm("density"),
                    "source_rank1": _Parm("scalar", template=menu_templates["rank"]),
                    "source_voperator1": _Parm("add", template=menu_templates["operator"]),
                    "source_vscale1": _Parm(1.0),
                    "source_vnormalize1": _Parm(False),
                    "source_volume2": _Parm("v"),
                    "source_vfield2": _Parm("vel"),
                    "source_rank2": _Parm("vector", template=menu_templates["rank"]),
                    "source_voperator2": _Parm("copy", template=menu_templates["operator"]),
                    "source_vscale2": _Parm(1.0),
                    "source_vnormalize2": _Parm(False),
                })
            path = root_path + "/" + self.provider_module._expected_node_name(role)
            nodes[role] = _GraphNode(path, self.provider_module._GRAPH_TYPES[role], parms)
        for destination, source_role in self.provider_module._GRAPH_EDGES:
            nodes[destination].set_input(nodes[source_role])
        root = _GraphRoot(root_path, list(nodes.values()))
        manifest = {
            "domain_pack": "pyro_smoke_v1",
            "short_segment_scoped": True,
            "execution_root": root_path,
            "nodes": {
                role: root_path + "/" + self.provider_module._expected_node_name(role)
                for role in names
            },
            "source_plan_host_controls": {"source_program": source_program},
            "source_program_registration": self.addon._fx_source_program_registration(source_program),
        }
        return root, manifest, nodes

    def test_fixed_graph_writer_inventory_is_scoped_and_read_only(self):
        root, manifest, nodes = self._fixed_graph()
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertTrue(result["complete"])
        self.assertEqual(result["status"], "implemented")
        self.assertEqual(result["other_writers"], [])
        self.assertFalse(result["global_inventory"])
        self.assertEqual(result["solver_rows"][0]["source_field"], "density")
        self.assertEqual(result["solver_rows"][1]["target_field"], "vel")
        self.assertEqual(result["source_count"], 2)
        self.assertTrue(result["source_rows_verified"])
        self.assertFalse(result["field_writer_scope_complete"])
        self.assertTrue(all(node.cook_calls == 0 for node in nodes.values()))

        downstream = self.addon._s06_velocity_writer_inventory(self.provider(), root, manifest)
        self.assertEqual(downstream["status"], "unknown")
        self.assertEqual(downstream["reason"], "WRITER_INTERNAL_SCOPE_UNVERIFIED")

    def test_writer_inventory_normalizes_strict_toggle_readback(self):
        root, manifest, nodes = self._fixed_graph()
        nodes["solver"].parm("source_vnormalize1").value = 0
        nodes["solver"].parm("source_vnormalize2").value = 0
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertTrue(result["complete"])
        self.assertFalse(result["solver_rows"][0]["use_timestep"])
        self.assertFalse(result["solver_rows"][1]["use_timestep"])

        for value, reason in (
            (1, "WRITER_SOLVER_UNITS_MISMATCH"),
            (True, "WRITER_SOLVER_UNITS_MISMATCH"),
            ("0", "WRITER_TOGGLE_TYPE_INVALID"),
            (None, "WRITER_TOGGLE_TYPE_INVALID"),
            (2, "WRITER_TOGGLE_VALUE_INVALID"),
            (float("nan"), "WRITER_TOGGLE_NONFINITE"),
        ):
            nodes["solver"].parm("source_vnormalize1").value = value
            with self.subTest(value=value):
                result = self.provider().velocity_writer_inventory(root, manifest)
                self.assertFalse(result["complete"])
                self.assertEqual(result["reason"], reason)

    def test_writer_inventory_requires_actual_two_row_numsources(self):
        root, manifest, nodes = self._fixed_graph()
        nodes["solver"]._parms.pop("numsources")
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_PARAMETER_MISSING")

        for count in (0, 1, 3, -1):
            root, manifest, nodes = self._fixed_graph()
            nodes["solver"].parm("numsources").value = count
            if count == 3:
                nodes["solver"]._parms.update({
                    "source_volume3": _Parm("v"),
                    "source_vfield3": _Parm("vel"),
                    "source_activate3": _Parm(False),
                    "source_voperator3": _Parm("copy", template=_MenuTemplate(("add", "copy"))),
                })
            with self.subTest(count=count):
                result = self.provider().velocity_writer_inventory(root, manifest)
                self.assertFalse(result["complete"])
                self.assertEqual(result["reason"], "WRITER_SOLVER_SOURCE_COUNT_INVALID")

    def test_writer_inventory_rejects_extra_input_and_untrusted_source_definition(self):
        root, manifest, nodes = self._fixed_graph()
        nodes["solver"]._inputs.append(nodes["source"])
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_GRAPH_EXTRA_INPUT")

        root, manifest, nodes = self._fixed_graph()
        nodes["source_control"].parm("snippet").value += "\n// tampered"
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_SOURCE_PROGRAM_BINDING_MISMATCH")

        root, manifest, nodes = self._fixed_graph()
        manifest["source_program_registration"]["generator"] = "unknown.generator"
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_SOURCE_PROGRAM_DEFINITION_UNKNOWN")

    def test_writer_inventory_rejects_extra_graph_node_and_binding_drift(self):
        root, manifest, nodes = self._fixed_graph()
        extra = _GraphNode(root.path() + "/UNOWNED", "null")
        root._children.append(extra)
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_GRAPH_CHILDREN_MISMATCH")

        root, manifest, nodes = self._fixed_graph()
        nodes["solver"].parm("source_vfield2").value = "density"
        result = self.provider().velocity_writer_inventory(root, manifest)
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "WRITER_SOLVER_BINDING_MISMATCH")

    def test_mutation_and_boundary_interfaces_remain_unimplemented(self):
        provider = self.provider()
        sentinel = {"field": "vel"}
        sentinel_result = provider.apply_velocity_sentinel(SimpleNamespace(), sentinel)
        boundary_result = provider.observe_sourcing_boundary(SimpleNamespace(), SimpleNamespace(), 1, (), {})
        self.assertEqual(sentinel_result["status"], "unimplemented")
        self.assertFalse(sentinel_result["applied"])
        self.assertEqual(boundary_result["status"], "unimplemented")
        self.assertFalse(boundary_result["cook_succeeded"])

    def test_addon_loader_installs_partial_provider_but_keeps_s06_blocked(self):
        hou = _Hou()
        report = self.addon._s06_install_native_provider(hou)
        self.assertTrue(report["provider_installed"])
        self.assertEqual(report["provider_state"], "installed")
        capabilities = self.addon._s06_host_capabilities(hou)
        self.assertEqual(capabilities["status"], "UNIMPLEMENTED")
        self.assertEqual(capabilities["pre_mutation_action"], "BLOCK_BEFORE_NODE_CREATION")
        self.assertEqual(
            capabilities["unverified_interfaces"],
            ["field_snapshot", "apply_velocity_sentinel", "velocity_writer_inventory", "observe_sourcing_boundary"],
        )
        self.assertIsNone(self.addon._s06_native_provider(hou))


if __name__ == "__main__":
    unittest.main()
