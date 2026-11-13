"""Supplied software fixtures only; no real cusp, HOM cook or scene receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import unittest

from houdini_bridge import native_ocean_mask_program as plans

ROOT = Path(__file__).resolve().parents[2]
DUAL = [.25, .5, .25, .25, .5, .25]


def f32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def bbox(points):
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def fact(value, typ="float"):
    return {"origin": "runtime_hom", "type": typ, "size": 1, "driven": False, "value": value}


def refresh(ctx):
    for role in ("source", "surface"):
        ctx[role]["bbox"] = bbox(ctx[role]["point_positions"])
    ctx["spectrum"]["geometry_sha256"] = plans.spectrum_geometry_sha256(ctx["spectrum"])
    ctx["mask_stage"]["inputs"] = [
        {"input_index": 0, "node_path": ctx["surface"]["node_path"], "output": 0,
         "geometry_sha256": plans.source_geometry_sha256(ctx["surface"], "evaluate")},
        {"input_index": 1, "node_path": ctx["spectrum"]["node_path"], "output": 0,
         "geometry_sha256": ctx["spectrum"]["geometry_sha256"]},
        {"input_index": 2, "node_path": ctx["source"]["node_path"], "output": 0,
         "geometry_sha256": plans.source_geometry_sha256(ctx["source"])},
    ]
    return ctx


def context(version="21.0.631", precision="float64", frame=1, foam=True, layers=2):
    points = [[0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
              [0., 0., 1.], [1., 0., 1.], [2., 0., 1.]]
    source = {"origin": "runtime_hom", "role": "source", "node_path": "/obj/task/source",
              "output": 0, "space": "sop_local", "frame": frame,
              "position_precision": precision, "point_positions": points,
              "polygons": [[0, 1, 4, 3], [1, 2, 5, 4]], "bbox": bbox(points)}
    surface = copy.deepcopy(source)
    surface.update(role="evaluate", node_path="/obj/task/evaluate")
    # Actual host fixtures may supply normally deformed, non-planar wave Quads.
    surface["point_positions"] = [[p[0], y, p[2]] for p, y in zip(points, (.2, .8, .3, .1, .4, .9))]
    if precision == "float32":
        surface["point_positions"] = [[f32(v) for v in p] for p in surface["point_positions"]]
    volumes = []
    for layer in range(layers):
        for name in ("amplitude", "phase", "frequency"):
            volumes.append({"primitive_index": len(volumes), "name": name, "type": "Volume",
                            "resolution": [4, 1, 4],
                            "transform": {"matrix": [1., 0., 0., 0., 1., 0., 0., 0., 1.],
                                          "translation": [0., 0., 0.]},
                            "storage": {"precision": "float32", "voxel_count": 16,
                                        "values_sha256": hashlib.sha256((name + str(layer)).encode()).hexdigest(),
                                        "border_type": "Repeat"},
                            "primitive_attributes": {"chop": 1., "timeoffset": 0., "timescale": 1.}
                            if name == "amplitude" else {}})
    spectrum = {"origin": "runtime_hom", "role": "spectrum", "node_path": "/obj/task/spectrum",
                "category": "sop", "type": "oceanspectrum", "task_owned": True,
                "task_root": "/obj/task", "output": 0, "space": "sop_local", "frame": frame,
                "sample_time": (frame - 1) / 24, "volumes": volumes, "geometry_sha256": ""}
    stage = {"origin": "runtime_hom", "role": plans.ROLE, "node_path": "/obj/task/ocean_masks",
             "category": "sop", "type": "attribwrangle", "task_owned": True,
             "task_root": "/obj/task", "space": "sop_local", "frame": frame,
             "native_version": version, "vex_precision": "64" if precision == "float64" else "32",
             "inputs": []}
    native = {"origin": "runtime_hom", "role": "foam_emit", "node_path": "/obj/task/foam_emit",
              "category": "sop", "type": "oceanfoam", "task_owned": True, "task_root": "/obj/task",
              "frame": frame, "parameters": {"mincusp": fact(.25), "density": fact(2.)},
              "gates": {name: fact(value, typ) for name, typ, value in (
                  ("mode", "ordinal", "emit"), ("region", "ordinal", "grid"),
                  ("domincusp", "toggle", 1), ("dominvel", "toggle", 0),
                  ("dominheight", "toggle", 0), ("dodisplace", "toggle", 0))}}
    return refresh({"source": source, "surface": surface, "spectrum": spectrum,
                    "mask_stage": stage, "native_emit": native, "foam": foam})


def observations(writes):
    result = {(plans.ROLE, w["parm"]): {**fact(w["value"], w["native_type"]),
               "locked": False, "disabled": False, "hidden": False} for w in writes}
    result[plans.ROLE, "class"].update(value=2, menu_tokens=["detail", "primitive", "point"],
                                      menu_labels=["Detail (only once)", "Primitives", "Points"])
    return result


def supplied_output(ctx, cusps=(-.2, 0., .5, 1., 2., 4.), dual=DUAL, attribute_precision=None):
    """Caller-supplied cusp values are fixtures, never computed native samples."""
    output = copy.deepcopy(ctx["surface"])
    output.update(role=plans.ROLE, node_path=ctx["mask_stage"]["node_path"])
    precision = attribute_precision or ("float32" if ctx["mask_stage"]["vex_precision"] == "32" else "float64")
    cast = f32 if precision == "float32" else float
    cusp_values = [cast(v) for v in cusps]
    areas = [cast(v) for v in dual]
    density, threshold = (ctx["native_emit"]["parameters"][name]["value"] for name in ("density", "mincusp"))
    values = {"bridge_ocean_cusp": cusp_values, "bridge_ocean_dual_area": areas,
              "cusp_mask": [cast(min(1., max(0., value))) for value in cusp_values],
              "foam_mask": [cast(-math.expm1(-density * area * max(value - threshold, 0.)))
                            if ctx["foam"] else 0. for area, value in zip(areas, cusp_values)]}
    output["point_attributes"] = {name: {"owner": "point", "storage": "float", "size": 1,
                                         "precision": precision, "values": data} for name, data in values.items()}
    output["point_attributes"]["bridge_ocean_layers"] = {
        "owner": "point", "storage": "int", "size": 1, "precision": "int32",
        "values": [len(ctx["spectrum"]["volumes"]) // 3] * len(cusps)}
    return output


class NativeOceanMaskProgramTests(unittest.TestCase):
    def registration(self, ctx):
        return plans.mask_program(plans.OCEAN, ctx["mask_stage"]["native_version"], **ctx)

    def test_both_native_interfaces_complete_string_cusp_signature_and_fixed_write_plan(self):
        basis = json.loads((ROOT / "docs/native-basis/hda-interface-capture.json").read_text())
        for version in plans.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                ctx = context(version)
                before = copy.deepcopy(ctx)
                writes = plans.control_write_plan(plans.OCEAN, version, **ctx)
                self.assertEqual(ctx, before)
                self.assertEqual([w["parm"] for w in writes], ["class", "group", "snippet"])
                for name in ("mincusp", "density"):
                    field = basis["versions"][version]["operators"]["Sop/oceanfoam"]["parameters"][name]
                    self.assertEqual((field["type"], field["size"]), ("float", 1))
                program = writes[2]["value"]
                self.assertIn('point(2, "P", @ptnum)', program)
                self.assertIn('oceanSampleLayers(@OpInput2, "", @Time, bridge_rest, 0.0, 0, 0.0, 0,', program)
                self.assertIn('bridge_disp, bridge_velocity, bridge_cusp, bridge_cuspdir)', program)
                self.assertIn('nprimsByName(@OpInput2, "amplitude")', program)
                self.assertNotIn('@P =', program)
                self.assertNotIn('oceanSampleLayers(1,', program)
                plans.validate_control_write_plan(writes, observations(writes), **ctx)

    def test_dynamic_frames_recollect_facts_without_baking_time_positions_or_layers(self):
        old, new = context(frame=1, layers=1), context(frame=25, layers=2)
        new["surface"]["point_positions"][0][1] = .75
        refresh(new)
        a, b = self.registration(old), self.registration(new)
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertNotEqual(a["frozen_readback_guards"], b["frozen_readback_guards"])
        self.assertEqual((a["observed_layers"], b["observed_layers"]), (1, 2))
        with self.assertRaisesRegex(ValueError, "OCEAN_.*_CONTEXT_CHANGED"):
            plans.validate_mask_program(a, **new)

    def test_pointwise_masks_accept_deformed_surface_both_versions_precision_and_foam_off(self):
        for version in plans.SUPPORTED_VERSIONS:
            for precision in ("float32", "float64"):
                for foam in (False, True):
                    with self.subTest(version=version, precision=precision, foam=foam):
                        ctx = context(version, precision, foam=foam)
                        writes = plans.control_write_plan(plans.OCEAN, version, **ctx)
                        actual = supplied_output(ctx)
                        comparison = plans.validate_applied_readback(writes, observations(writes), masked_geometry=actual, **ctx)
                        self.assertTrue(comparison["pointwise_mask_formula_matches"])
                        self.assertTrue(comparison["evaluated_positions_and_topology_unchanged"])
                        self.assertEqual(writes[2]["trusted_program"]["rest_dual_cell_areas"], DUAL)
                        self.assertNotIn("operation_id", comparison)

    def test_actual_attribute_storage_independent_of_vex_precision(self):
        ctx = context(precision="float64")
        actual = supplied_output(ctx, attribute_precision="float32")
        comparison = plans.validate_geometry_readback(self.registration(ctx), masked_geometry=actual, **ctx)
        self.assertEqual(comparison["attribute_precisions"]["bridge_ocean_cusp"], "float32")
        bad = copy.deepcopy(actual)
        bad["point_attributes"]["bridge_ocean_cusp"]["values"][0] = .123456789
        with self.assertRaisesRegex(ValueError, "ACTUAL_OCEAN_PRECISION_REQUIRED"):
            plans.validate_geometry_readback(self.registration(ctx), masked_geometry=bad, **ctx)
        for point in ctx["source"]["point_positions"]:
            point[0] *= 100000
            point[2] *= 100000
        refresh(ctx)
        unresolved = supplied_output(ctx, [.25] * 6, [v * 1e10 for v in DUAL], "float32")
        with self.assertRaisesRegex(ValueError, "OCEAN_MASK_NUMERIC_READBACK_UNRESOLVED"):
            plans.validate_geometry_readback(self.registration(ctx), masked_geometry=unresolved, **ctx)

    def test_feedback_wrong_input_hash_emitter_substitution_and_correspondence_rejected(self):
        cases = (
            (lambda c: c["mask_stage"]["inputs"][0].update(geometry_sha256="0" * 64), "INPUT_CONTEXT"),
            (lambda c: c["mask_stage"]["inputs"][1].update(output=1), "INPUT_CONTEXT"),
            (lambda c: c["mask_stage"].update(node_path=c["surface"]["node_path"]), "INPUT_CONTEXT"),
            (lambda c: c["surface"].update(node_path=c["native_emit"]["node_path"]), "INPUT_CONTEXT"),
            (lambda c: c["source"].update(node_path=c["mask_stage"]["node_path"]), "INPUT_CONTEXT"),
            (lambda c: c["surface"]["polygons"][0].reverse(), "CORRESPONDENCE"),
        )
        for mutate, code in cases:
            ctx = context()
            mutate(ctx)
            if code == "CORRESPONDENCE" or ctx["source"]["node_path"] == ctx["mask_stage"]["node_path"] or ctx["surface"]["node_path"] == ctx["native_emit"]["node_path"]:
                refresh(ctx)
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                self.registration(ctx)

    def test_frozen_native_context_and_untrusted_registration_rejected(self):
        ctx = context()
        registered = self.registration(ctx)
        for key in ("density", "mincusp"):
            changed = copy.deepcopy(ctx)
            changed["native_emit"]["parameters"][key]["value"] += .25
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "OCEAN_EMIT_CONTEXT_CHANGED"):
                plans.validate_mask_program(registered, **changed)
        for key, value in (("program", registered["program"] + "@P *= 2;"),
                           ("sha256", "0" * 64), ("foam", False), ("observed_layers", 1)):
            changed = copy.deepcopy(registered)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "UNTRUSTED_OCEAN_MASK_PROGRAM"):
                plans.validate_mask_program(changed, **ctx)

    def test_invalid_missing_or_mismatched_spectrum_layers_rejected(self):
        cases = (
            lambda s: s.update(volumes=[]),
            lambda s: s["volumes"].pop(),
            lambda s: s["volumes"][0]["primitive_attributes"].pop("chop"),
            lambda s: s["volumes"][1].update(resolution=[8, 1, 4]),
            lambda s: s["volumes"][0].update(type="VDB"),
            lambda s: s["volumes"][0]["storage"].update(voxel_count=0),
            lambda s: s["volumes"][0]["transform"].update(matrix=[0.] * 9),
        )
        for mutate in cases:
            ctx = context()
            mutate(ctx["spectrum"])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.registration(ctx)
        ctx = context()
        ctx["spectrum"]["volumes"][0]["storage"]["values_sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "SPECTRUM_HASH_MISMATCH"):
            self.registration(ctx)

    def test_concave_self_intersecting_nonplanar_and_degenerate_rest_rejected(self):
        cases = (
            ([[0, 0, 0], [2, 0, 0], [1, 0, .2], [2, 0, 2], [0, 0, 2]], "CONVEX"),
            ([[0, 0, 0], [1, 0, 0], [1, .5, 1], [0, 0, 1]], "PLANAR"),
            ([[0, 0, 0], [1, 0, 0], [2, 0, 0]], "DEGENERATE"),
            ([[math.cos(i * 4 * math.pi / 5), 0, math.sin(i * 4 * math.pi / 5)] for i in range(5)], "CONVEX"),
        )
        for points, code in cases:
            ctx = context()
            for name in ("source", "surface"):
                ctx[name]["point_positions"] = points
                ctx[name]["polygons"] = [list(range(len(points)))]
            refresh(ctx)
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                self.registration(ctx)

    def test_rotated_translated_convex_rest_area_and_no_grid_assumption(self):
        ctx = context()
        points = [[2., 3., 4.], [2., 4., 4.], [2., 4.5, 5.], [2., 3., 6.]]
        for name in ("source", "surface"):
            ctx[name]["point_positions"] = points
            ctx[name]["polygons"] = [[0, 1, 2, 3]]
        refresh(ctx)
        # Shoelace in the actual yz plane gives area 2.
        registered = self.registration(ctx)
        self.assertEqual(registered["rest_polygon_areas"], [2.])
        self.assertEqual(registered["rest_dual_cell_areas"], [.5] * 4)
        result = plans.validate_geometry_readback(registered, masked_geometry=supplied_output(ctx, (0., .5, 1., 2.), [.5] * 4), **ctx)
        self.assertTrue(result["pointwise_mask_formula_matches"])

    def test_typed_attribute_numeric_and_geometry_readback_failures(self):
        ctx = context()
        registered = self.registration(ctx)
        cases = (
            lambda g: g["point_attributes"]["bridge_ocean_layers"]["values"].__setitem__(0, 0),
            lambda g: g["point_attributes"]["bridge_ocean_layers"]["values"].__setitem__(0, True),
            lambda g: g["point_attributes"]["bridge_ocean_cusp"].update(storage="int"),
            lambda g: g["point_attributes"]["bridge_ocean_cusp"].update(size=3),
            lambda g: g["point_attributes"]["bridge_ocean_cusp"]["values"].__setitem__(2, math.nan),
            lambda g: g["point_attributes"]["bridge_ocean_dual_area"]["values"].__setitem__(0, .5),
            lambda g: g["point_attributes"]["cusp_mask"]["values"].__setitem__(2, .75),
            lambda g: g["point_attributes"]["foam_mask"]["values"].__setitem__(5, 0.),
            lambda g: g["point_positions"][0].__setitem__(1, .4),
            lambda g: g["polygons"][0].reverse(),
        )
        for mutate in cases:
            actual = supplied_output(ctx)
            mutate(actual)
            actual["bbox"] = bbox(actual["point_positions"])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                plans.validate_geometry_readback(registered, masked_geometry=actual, **ctx)
        ctx = context(foam=False)
        actual = supplied_output(ctx)
        actual["point_attributes"]["foam_mask"]["values"][0] = 1e-13
        with self.assertRaisesRegex(ValueError, "READBACK_MISMATCH"):
            plans.validate_geometry_readback(self.registration(ctx), masked_geometry=actual, **ctx)

    def test_native_gates_actual_writable_fields_and_applied_program_required(self):
        ctx = context()
        writes = plans.control_write_plan(plans.OCEAN, "21.0.631", **ctx)
        for mutate in (lambda c: c["native_emit"]["gates"]["domincusp"].update(value=0),
                       lambda c: c["native_emit"]["parameters"]["density"].update(type="integer"),
                       lambda c: c["native_emit"]["parameters"]["mincusp"].update(driven=True),
                       lambda c: c["native_emit"].update(frame=2)):
            bad = copy.deepcopy(ctx)
            mutate(bad)
            with self.assertRaises(ValueError):
                self.registration(bad)
        for field, value in (("locked", True), ("driven", True), ("size", 2), ("origin", "model")):
            obs = observations(writes)
            obs[plans.ROLE, "snippet"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                plans.validate_control_write_plan(writes, obs, **ctx)
        obs = observations(writes)
        obs[plans.ROLE, "snippet"]["value"] += "@P *= 2;"
        with self.assertRaisesRegex(ValueError, "NATIVE_CONTROL_READBACK_MISMATCH"):
            plans.validate_applied_readback(writes, obs, masked_geometry=supplied_output(ctx), **ctx)

    def test_budget_explicit_precision_domain_and_numeric_context(self):
        ctx = context()
        for field, value in (("vex_precision", "auto"), ("vex_precision", "32"), ("native_version", "20.5")):
            bad = copy.deepcopy(ctx)
            bad["mask_stage"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.registration(bad)
        bad = copy.deepcopy(ctx)
        bad["foam"] = 1
        with self.assertRaisesRegex(ValueError, "FOAM_BOOL"):
            self.registration(bad)
        bad = copy.deepcopy(ctx)
        bad["source"]["point_positions"] *= 1366
        with self.assertRaisesRegex(ValueError, "POINT_BUDGET"):
            self.registration(bad)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_OCEAN"):
            plans.mask_program("vellum_cloth_v1", "21.0.631", **ctx)
        for value in (math.nan, math.inf, -1., True, 101., 10 ** 1000):
            bad = copy.deepcopy(ctx)
            bad["native_emit"]["parameters"]["density"]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.registration(bad)
        ctx["native_emit"]["parameters"]["density"]["value"] = -0.
        zero = self.registration(ctx)
        self.assertNotIn("exp(--0", zero["program"])
        self.assertTrue(plans.validate_geometry_readback(zero, masked_geometry=supplied_output(ctx), **ctx)["pointwise_mask_formula_matches"])


if __name__ == "__main__":
    unittest.main()
