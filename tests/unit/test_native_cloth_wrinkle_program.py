"""CPU interface fixtures only; no native collection, cook or scene evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import unittest

from houdini_bridge import native_cloth_wrinkle_program as plans

ROOT = Path(__file__).resolve().parents[2]


def float32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def bounds(points):
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def context(version="21.0.631", precision="float64", transform=None, columns=9, thickness=.04):
    points = [[i * .25, j * .125, 0.] for j in range(3) for i in range(columns)]
    if transform:
        points = [transform(p) for p in points]
    if precision == "float32":
        points = [[float32(v) for v in p] for p in points]
    faces = [[j * columns + i, j * columns + i + 1,
              (j + 1) * columns + i + 1, (j + 1) * columns + i]
             for j in range(2) for i in range(columns - 1)]
    source = {"origin": "runtime_hom", "role": "source", "node_path": "/obj/task/source",
              "output": 0, "space": "sop_local", "frame": 1,
              "position_precision": precision, "point_positions": points,
              "polygons": faces, "bbox": bounds(points)}
    native = {"origin": "runtime_hom", "role": "constraints", "node_path": "/obj/task/constraints",
              "parm": "thickness", "type": "float", "size": 1, "driven": False,
              "value": thickness, "gates": {
                  "constrainttype": {"origin": "runtime_hom", "type": "ordinal", "size": 1,
                                     "driven": False, "value": 0,
                                     "menu_tokens": ["cloth"], "menu_labels": ["Cloth"]},
                  "dothickness": {"origin": "runtime_hom", "type": "ordinal", "size": 1,
                                  "driven": False, "value": "on",
                                  "menu_tokens": ["off", "on"], "menu_labels": ["Off", "On"]}}}
    stage = {"origin": "runtime_hom", "role": plans.ROLE, "node_path": "/obj/task/cloth_wrinkle",
             "category": "sop", "type": "attribwrangle", "task_owned": True,
             "task_root": "/obj/task", "input_node_path": source["node_path"],
             "input_output": 0, "input_index": 0,
             "input_geometry_sha256": plans.source_geometry_sha256(source),
             "space": "sop_local", "frame": 1, "native_version": version,
             "vex_precision": "32" if precision == "float32" else "64"}
    return {"source": source, "thickness": native, "shape_stage": stage}


def supplied_output_fixture(registration, ctx):
    """Independent arithmetic expectation, deliberately not an actual receipt."""
    source = ctx["source"]
    basis = registration["basis"]
    wavelength = registration["wrinkle_scale"]
    output = copy.deepcopy(source)
    output.update(role=plans.ROLE, node_path=ctx["shape_stage"]["node_path"])
    points = []
    for old in source["point_positions"]:
        distance = sum((v - a) * t for v, a, t in zip(old, basis["anchor"], basis["tangent"]))
        displacement = (ctx["thickness"]["value"] / 2 * math.sin(2 * math.pi * distance / wavelength)
                        if wavelength else 0.)
        position = [v + n * displacement for v, n in zip(old, basis["normal"])]
        if source["position_precision"] == "float32":
            position = [float32(v) for v in position]
        points.append(position)
    output["point_positions"] = points
    output["bbox"] = bounds(points)
    return output


def observations(writes):
    result = {(w["role"], w["parm"]): {"origin": "runtime_hom", "type": w["native_type"],
              "size": 1, "locked": False, "disabled": False, "hidden": False,
              "driven": False, "value": w["value"]} for w in writes}
    result[(plans.ROLE, "class")].update(value=2, menu_tokens=["detail", "primitive", "point"],
                                         menu_labels=["Detail (only once)", "Primitives", "Points"])
    return result


class NativeClothWrinkleProgramTests(unittest.TestCase):
    def registration(self, ctx, value):
        return plans.source_program(plans.CLOTH, ctx["shape_stage"]["native_version"], value, **ctx)

    def test_captured_both_version_interface_and_trusted_three_field_write_plan(self):
        metadata = json.loads((ROOT / "docs/native-basis/w2-wrangle-convolve-static.json").read_text())
        for version in plans.SUPPORTED_VERSIONS:
            ctx = context(version)
            frozen = copy.deepcopy(ctx)
            writes = plans.control_write_plan(plans.CLOTH, 1, version, **ctx)
            self.assertEqual(ctx, frozen)
            self.assertEqual([w["parm"] for w in writes], ["class", "group", "snippet"])
            native = metadata["versions"][version]["operators"]["Sop/attribwrangle"]
            self.assertEqual(native["status"], "CAPTURED")
            for write in writes:
                self.assertEqual(write["native_type"], native["parameters"][write["parm"]]["type"])
            self.assertIn("Points", native["parameters"]["class"]["menu_tokens"][1::2])
            self.assertEqual(native["parameters"]["vex_precision"]["type"], "string")
            self.assertTrue({"32", "64"}.issubset(native["parameters"]["vex_precision"]["menu_tokens"][::2]))
            registration = writes[2]["trusted_program"]
            self.assertEqual(registration["sha256"], hashlib.sha256(registration["program"].encode()).hexdigest())
            self.assertIn('point(0, "P", @ptnum)', registration["program"])
            self.assertNotIn("@P +=", registration["program"])
            self.assertNotIn("restlength", registration["program"])
            self.assertNotIn("bendstiffness", registration["program"])
            readback = plans.validate_applied_readback(writes, observations(writes), **ctx,
                         shaped_geometry=supplied_output_fixture(registration, ctx))
            self.assertTrue(readback["pointwise_formula_matches"])
            self.assertTrue(readback["period_observable"])

    def test_flat_and_feedback_replace_from_unmodified_upstream(self):
        for version in plans.SUPPORTED_VERSIONS:
            ctx = context(version)
            source_before = copy.deepcopy(ctx["source"])
            for value in (1., .5, 0., 1., 0.):
                with self.subTest(version=version, value=value):
                    registration = self.registration(ctx, value)
                    output = supplied_output_fixture(registration, ctx)
                    comparison = plans.validate_geometry_readback(registration, **ctx, shaped_geometry=output)
                    self.assertEqual(ctx["source"], source_before)
                    if value == 0:
                        self.assertEqual(output["point_positions"], source_before["point_positions"])
                        self.assertNotIn("sin(", registration["program"])
                        self.assertFalse(comparison["period_observable"])
                        corrupted = copy.deepcopy(output)
                        corrupted["point_positions"][0][2] = 1e-14
                        corrupted["bbox"] = bounds(corrupted["point_positions"])
                        with self.assertRaisesRegex(plans.NativeClothWrinkleError, "READBACK_MISMATCH"):
                            plans.validate_geometry_readback(registration, **ctx, shaped_geometry=corrupted)

    def test_actual_polygon_basis_handles_rotated_plane_and_normal_displacement(self):
        def rotate(p):
            return [p[0] / math.sqrt(5), 2 * p[0] / math.sqrt(5), p[1] + 3]
        ctx = context(transform=rotate)
        registration = self.registration(ctx, 1.)
        normal = registration["basis"]["normal"]
        tangent = registration["basis"]["tangent"]
        self.assertAlmostEqual(sum(n * t for n, t in zip(normal, tangent)), 0.)
        self.assertAlmostEqual(sum(n * n for n in normal), 1.)
        self.assertAlmostEqual(normal[2], 0.)
        output = supplied_output_fixture(registration, ctx)
        self.assertTrue(plans.validate_geometry_readback(registration, **ctx, shaped_geometry=output)["period_observable"])

    def test_local_band_coarse_source_and_zero_or_unresolvable_amplitude_do_not_claim_period(self):
        for wavelength, native, columns in ((100., .04, 9), (.5, .04, 3), (1., 0., 9), (1., 1e-8, 9)):
            with self.subTest(wavelength=wavelength, native=native, columns=columns):
                ctx = context(precision="float32", columns=columns, thickness=native)
                registration = self.registration(ctx, wavelength)
                result = plans.validate_geometry_readback(registration, **ctx,
                         shaped_geometry=supplied_output_fixture(registration, ctx))
                self.assertTrue(result["pointwise_formula_matches"])
                self.assertFalse(result["period_observable"])
                self.assertIn("recommended_maximum_step", result["sampling"])
                if native <= 1e-8:
                    self.assertFalse(result["amplitude_observable"])

    def test_finite_float32_position_storage_readback_uses_explicit_bounded_precision(self):
        ctx = context(precision="float32", thickness=.035)
        registration = self.registration(ctx, 1.)
        output = supplied_output_fixture(registration, ctx)
        result = plans.validate_geometry_readback(registration, **ctx, shaped_geometry=output)
        self.assertGreater(result["maximum_position_error"], 0.)
        self.assertLess(result["maximum_position_error"], result["position_tolerance"])
        self.assertLess(result["position_tolerance"], 1e-4)
        self.assertTrue(result["period_observable"])

    def test_source_dimension_normal_topology_thickness_and_owned_stage_changes_are_guarded(self):
        ctx = context()
        registration = self.registration(ctx, 1.)
        changes = []
        dimension = copy.deepcopy(ctx)
        dimension["source"]["point_positions"] = [[2 * p[0], p[1], p[2]] for p in dimension["source"]["point_positions"]]
        changes.append(dimension)
        plane = copy.deepcopy(ctx)
        plane["source"]["point_positions"] = [[p[0], 0., p[1]] for p in plane["source"]["point_positions"]]
        changes.append(plane)
        contents = copy.deepcopy(ctx)
        contents["source"]["point_positions"][4][0] += .001
        changes.append(contents)
        topology = copy.deepcopy(ctx)
        topology["source"]["polygons"][0].reverse()
        changes.append(topology)
        thickness = copy.deepcopy(ctx)
        thickness["thickness"]["value"] *= 2
        changes.append(thickness)
        stage = copy.deepcopy(ctx)
        stage["shape_stage"]["node_path"] = "/obj/task/other_shape"
        changes.append(stage)
        for changed in changes:
            with self.subTest(changed=changed):
                changed["source"]["bbox"] = bounds(changed["source"]["point_positions"])
                changed["shape_stage"]["input_geometry_sha256"] = plans.source_geometry_sha256(changed["source"])
                with self.assertRaisesRegex(plans.NativeClothWrinkleError, "CONTEXT_CHANGED"):
                    plans.validate_source_program(registration, **changed)

    def test_missing_nonplanar_degenerate_and_unsafe_contexts_fail_without_axis_guess_or_clamp(self):
        ctx = context()
        changed_contexts = []
        for key, value in (("task_owned", False), ("input_index", 1), ("type", "unknown"),
                           ("vex_precision", "auto"), ("vex_precision", "32")):
            changed = copy.deepcopy(ctx)
            changed["shape_stage"][key] = value
            changed_contexts.append(changed)
        changed = copy.deepcopy(ctx)
        changed["source"]["point_positions"][4][2] = .1
        changed["source"]["bbox"] = bounds(changed["source"]["point_positions"])
        changed["shape_stage"]["input_geometry_sha256"] = plans.source_geometry_sha256(changed["source"])
        changed_contexts.append(changed)
        changed = copy.deepcopy(ctx)
        changed["source"]["point_positions"] = [[p[0], 0., 0.] for p in changed["source"]["point_positions"]]
        changed["source"]["bbox"] = bounds(changed["source"]["point_positions"])
        changed["shape_stage"]["input_geometry_sha256"] = plans.source_geometry_sha256(changed["source"])
        changed_contexts.append(changed)
        for value in (float("nan"), float("inf"), -.1, 101., True, "1; @P=0", 1e-320, 10 ** 1000):
            with self.subTest(value=value), self.assertRaises(plans.NativeClothWrinkleError):
                self.registration(ctx, value)
        for changed in changed_contexts:
            with self.subTest(changed=changed), self.assertRaises(plans.NativeClothWrinkleError):
                self.registration(changed, 1.)
        self.assertFalse(self.registration(ctx, .0001)["sampling"]["period_observable"])
        with self.assertRaisesRegex(plans.NativeClothWrinkleError, "UNSAFE_CLOTH_WAVELENGTH_CONTEXT"):
            self.registration(context(precision="float32"), .0001)
        missing = copy.deepcopy(ctx)
        del missing["source"]["position_precision"]
        with self.assertRaises(plans.NativeClothWrinkleError):
            self.registration(missing, 1.)
        for changed_gate in ("constrainttype", "dothickness"):
            changed = copy.deepcopy(ctx)
            changed["thickness"]["gates"][changed_gate]["driven"] = True
            with self.assertRaisesRegex(plans.NativeClothWrinkleError, "ACTUAL_NATIVE_THICKNESS_REQUIRED"):
                self.registration(changed, 1.)

    def test_all_point_readback_rejects_wrong_wave_amplitude_tangent_connectivity_and_finite_data(self):
        ctx = context()
        registration = self.registration(ctx, 1.)
        correct = supplied_output_fixture(registration, ctx)
        outputs = []
        wrong_wave = supplied_output_fixture(self.registration(ctx, .5), ctx)
        outputs.append(wrong_wave)
        doubled = copy.deepcopy(correct)
        doubled["point_positions"] = [[p[0], p[1], 2 * p[2]] for p in doubled["point_positions"]]
        outputs.append(doubled)
        tangent = copy.deepcopy(correct)
        tangent["point_positions"][4][0] += .01
        outputs.append(tangent)
        connectivity = copy.deepcopy(correct)
        connectivity["polygons"][0].reverse()
        outputs.append(connectivity)
        nonfinite = copy.deepcopy(correct)
        nonfinite["point_positions"][4][2] = float("inf")
        outputs.append(nonfinite)
        for output in outputs:
            output["bbox"] = bounds(output["point_positions"])
            with self.subTest(output=output), self.assertRaises(plans.NativeClothWrinkleError):
                plans.validate_geometry_readback(registration, **ctx, shaped_geometry=output)
        accumulated = copy.deepcopy(correct)
        accumulated["point_positions"] = [[v + (v - old) for v, old in zip(p, source)]
                                          for p, source in zip(correct["point_positions"], ctx["source"]["point_positions"])]
        accumulated["bbox"] = bounds(accumulated["point_positions"])
        with self.assertRaisesRegex(plans.NativeClothWrinkleError, "READBACK_MISMATCH"):
            plans.validate_geometry_readback(registration, **ctx, shaped_geometry=accumulated)

    def test_regeneration_rejects_code_write_plan_and_runtime_field_corruption(self):
        ctx = context()
        writes = plans.control_write_plan(plans.CLOTH, 1., "21.0.631", **ctx)
        observed = observations(writes)
        plans.validate_control_write_plan(writes, observed, **ctx)
        for field in ("program", "sha256", "basis", "generator"):
            changed = copy.deepcopy(writes[2]["trusted_program"])
            changed[field] = "external supplied value"
            with self.subTest(field=field), self.assertRaisesRegex(plans.NativeClothWrinkleError, "UNTRUSTED"):
                plans.validate_source_program(changed, **ctx)
        changed = copy.deepcopy(writes)
        changed[0]["parm"] = "restlengthscale"
        with self.assertRaisesRegex(plans.NativeClothWrinkleError, "UNTRUSTED"):
            plans.validate_control_write_plan(changed, observed, **ctx)
        for key, value in (("type", "float"), ("driven", True), ("locked", True), ("origin", "static")):
            changed = copy.deepcopy(observed)
            changed[(plans.ROLE, "snippet")][key] = value
            with self.subTest(key=key), self.assertRaises(plans.NativeClothWrinkleError):
                plans.validate_control_write_plan(writes, changed, **ctx)
        changed = copy.deepcopy(observed)
        changed[(plans.ROLE, "snippet")]["value"] += "@P=0;"
        with self.assertRaisesRegex(plans.NativeClothWrinkleError, "NATIVE_CONTROL_READBACK_MISMATCH"):
            plans.validate_applied_readback(writes, changed, **ctx,
                        shaped_geometry=supplied_output_fixture(writes[2]["trusted_program"], ctx))


if __name__ == "__main__":
    unittest.main()
