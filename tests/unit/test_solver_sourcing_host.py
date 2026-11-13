"""Behavioral tests for the captured Houdini 21.0.631 solver sourcing binding.

These tests use the real add-on dispatch path and inspect synthetic HOM writes.
They are not Houdini execution, smoke, VDB, render, or visual acceptance.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from source_host_fixture import FakeSourceHost, source_params
from test_houdini_parm_probe import _load_addon


def keyframe_events(parm):
    return [(int(key.frame()), int(key.value())) for key in parm.keyframes()]


def constant_value(events, frame):
    value = events[0][1]
    for key_frame, key_value in events:
        if frame < key_frame:
            break
        value = key_value
    return value


class SolverSourcingBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addon = _load_addon()

    def test_exact_rows_fields_connection_units_and_readback(self):
        with FakeSourceHost(self.addon) as host:
            result = host.build()
            solver = host.role("solver")
            manifest = result["scene_manifest"]
            sourcing = manifest["solver_sourcing"]

            self.assertEqual(solver.type().name(), "pyrosolver")
            self.assertEqual(solver.parm("numsources").eval(), 2)
            self.assertIs(solver.inputs()[0], host.role("source_volume"))
            self.assertEqual(sourcing["contract"], "bridge.pyro.solver-sourcing/21.0.631")
            self.assertEqual(sourcing["runtime"]["houdini_build"], "21.0.631")
            self.assertEqual(sourcing["runtime"]["fps"], 24.0)
            self.assertEqual(sourcing["runtime"]["time_scale"], 1.0)
            self.assertAlmostEqual(sourcing["runtime"]["timestep_seconds"], 1.0 / 24.0)
            self.assertTrue(sourcing["input_connection"]["readback_verified"])
            self.assertFalse(sourcing["runtime"]["dynamic_menus_executed"])

            expected = [
                ("add", "scalar", "density", "density"),
                ("copy", "vector", "v", "vel"),
            ]
            for index, row in enumerate(expected, 1):
                self.assertEqual(solver.parm("source_voperator{}".format(index)).evalAsString(), row[0])
                self.assertEqual(solver.parm("source_rank{}".format(index)).evalAsString(), row[1])
                self.assertEqual(solver.parm("source_volume{}".format(index)).eval(), row[2])
                self.assertEqual(solver.parm("source_vfield{}".format(index)).eval(), row[3])
                self.assertEqual(solver.parm("source_vscale{}".format(index)).eval(), 1.0)
                self.assertFalse(solver.parm("source_vnormalize{}".format(index)).eval())
                self.assertFalse(solver.parm("source_usenorm{}".format(index)).eval())
                self.assertFalse(solver.parm("source_nonneg{}".format(index)).eval())

                self.assertEqual(
                    keyframe_events(solver.parm("source_activate{}".format(index))),
                    keyframe_events(solver.parm("source_activate1")),
                )

            self.assertEqual(solver.parm("srcrangetype").evalAsString(), "sequence")
            self.assertEqual(solver.parmTuple("srcframerange").eval(), (1, 180))
            self.assertFalse(solver.parm("srcdocycle").eval())
            self.assertEqual(solver.parm("srccyclelength").eval(), 180)
            self.assertEqual(solver.parm("startframe").eval(), 1)
            self.assertTrue(all(item["readback_verified"] for item in manifest["source_plan_host_readback"].values()))
            self.assertFalse(manifest["execution_assessment"]["simulation_executed"])
            self.assertFalse(any(call[0] == "cook" and call[1].endswith(("FX_SOLVER", "FX_OUTPUT")) for call in host.calls))

    def test_copy_velocity_is_disabled_outside_pulses_including_after_stop(self):
        with FakeSourceHost(self.addon) as host:
            result = host.build(source_params(pulse_count=3, emission_start_frame=10, emission_end_frame=19))
            solver = host.role("solver")
            events = keyframe_events(solver.parm("source_activate2"))
            pulses = [(10, 12), (14, 16), (18, 20)]
            for frame in (1, 9, 12, 13, 16, 17, 20, 21, 180, 181, 500):
                expected = int(any(start <= frame < end for start, end in pulses))
                self.assertEqual(constant_value(events, frame), expected, frame)
            self.assertEqual(solver.parm("source_voperator2").evalAsString(), "copy")
            policy = result["scene_manifest"]["solver_sourcing"]["stop_policy"]
            self.assertIn("never active on an inactive frame", policy)
            self.assertTrue(result["scene_manifest"]["solver_sourcing"]["activation"]["zero_velocity_is_never_copied_when_inactive"])

    def test_new_task_solver_initializes_native_zero_count_only_through_owned_write(self):
        with FakeSourceHost(self.addon) as host:
            result = host.build()
            sourcing = result["scene_manifest"]["solver_sourcing"]
            self.assertEqual(sourcing["source_count_before_write"], 0)
            self.assertEqual(sourcing["source_count"], 2)
            self.assertEqual(host.role("solver").parm("numsources").eval(), 2)
            # This is a software protocol fact, not evidence of a native
            # Houdini default.  An already-populated count requires the
            # persisted Bridge-owned schedule in preflight.
            self.assertEqual(sourcing["source_count_policy"],
                             "new_task_owned_solver_count_zero_explicitly_initialized_to_two")

    def test_new_owned_counts_use_raw_hom_keyword_and_verify_or_destroy(self):
        class RawParm:
            def __init__(self, name, mode):
                self.name, self.mode, self.value = name, mode, 7
                self.writes, self.reads = [], 0
            def path(self): return "/stage/settings/" + self.name
            def isLocked(self): return False
            def isDisabled(self): return False
            def expression(self):
                if self.mode == "expression": return "$F"
                raise RuntimeError("no expression")
            def getReferencedParm(self):
                if self.mode == "reference": return SimpleNamespace(path=lambda: "/stage/other/count")
                return self
            def keyframes(self): return (object(),) if self.mode == "keyframes" else ()
            def set(self, value, language=None, follow_parm_reference=True):
                self.writes.append((value, language, follow_parm_reference))
                if self.mode == "write_failure": raise RuntimeError("native write failed")
                self.value = True if self.mode == "readback_failure" else value
            def eval(self):
                self.reads += 1
                return self.value

        for mode in ("success", "write_failure", "readback_failure", "expression", "reference", "keyframes"):
            parms = {name: RawParm(name, mode) for name in ("extrarendervars", "custom_metadata")}
            destroyed = []
            node = SimpleNamespace(type=lambda: SimpleNamespace(nameWithCategory=lambda: "Lop/karmarendersettings"),
                                   parm=parms.get, destroy=lambda: destroyed.append(True))
            with self.subTest(mode=mode):
                if mode == "success":
                    result = self.addon._fx_initialize_new_owned_counts(node)
                    self.assertEqual(set(result), set(parms))
                    for name, parm in parms.items():
                        self.assertEqual(parm.writes, [(0, None, False)])
                        self.assertGreater(parm.reads, 0)
                        self.assertEqual(result[name]["after"], 0)
                        self.assertTrue(result[name]["readback_verified"])
                    self.assertEqual(destroyed, [])
                elif mode in ("write_failure", "readback_failure"):
                    with self.assertRaises((RuntimeError, ValueError)):
                        self.addon._fx_initialize_new_owned_counts(node)
                    self.assertEqual(destroyed, [True])
                    self.assertEqual(parms["extrarendervars"].writes, [(0, None, False)])
                    self.assertEqual(parms["custom_metadata"].writes, [])
                else:
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon._fx_initialize_new_owned_counts(node)
                    self.assertEqual(caught.exception.code, "PARAMETER_STATE_UNSUPPORTED")
                    self.assertEqual(destroyed, [])
                    self.assertTrue(all(not parm.writes for parm in parms.values()))

    def test_dynamic_string_fields_are_written_as_free_text_without_menu_reads(self):
        with FakeSourceHost(self.addon) as host:
            original_menu=host.native.Template.menuItems
            menu_calls=[]

            def static_menu(template):
                menu_calls.append(template.name())
                if template.name() in {'source_volume#','source_vfield#'}:
                    raise AssertionError('dynamic string menu must not execute')
                return original_menu(template)

            with patch.object(host.native.Template,'menuItems',static_menu):
                host.build()
            row_folder = self.addon._fx_solver_find_templates(host.hou.nodeType(host.hou.sopNodeTypeCategory(), "pyrosolver"), "folder17_#")[0]
            dynamic = {
                template.name(): template
                for template in self.addon._fx_solver_find_templates(row_folder, "source_volume#")
                + self.addon._fx_solver_find_templates(row_folder, "source_vfield#")
            }
            self.assertEqual(set(dynamic), {"source_volume#", "source_vfield#"})
            self.assertTrue(set(dynamic).isdisjoint(menu_calls))
            self.assertIn('source_voperator#',menu_calls)

    def test_missing_template_or_static_token_refuses_before_scene_mutation(self):
        for mode in ("missing", "menu"):
            with self.subTest(mode=mode), FakeSourceHost(self.addon) as host:
                fields = host.catalog[('Sop','pyrosolver')]['parameters']
                if mode == "missing":
                    del fields['source_vfield#']
                else:
                    fields['source_voperator#']['menu_tokens'] = ['copy','Copy','add','Add']
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build()
                self.assertIn(caught.exception.code, {"UNSUPPORTED_SOURCE_CONTROL", "UNSUPPORTED_NODE"})
                self.assertEqual(host.writes(), [])
                self.assertFalse(host.state_path.exists())

    def test_driven_or_locked_solver_row_refuses_before_any_new_write(self):
        for guard in ("driven", "locked"):
            with self.subTest(guard=guard), FakeSourceHost(self.addon) as host:
                host.build()
                solver = host.role("solver")
                parm = solver.parm("source_voperator2")
                if guard == "driven":
                    driver=host.native.Keyframe(parm.eval())
                    driver.setFrame(host.hou.frame())
                    host.native.set_parm_state(parm,keyframes=[driver])
                else:
                    host.native.set_parm_state(parm,locked=True)
                count = len(host.writes())
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build(source_params(emission_start_frame=80, emission_end_frame=100))
                self.assertIn(caught.exception.code, {"PARAMETER_STATE_UNSUPPORTED", "PARAMETER_LOCKED"})
                self.assertEqual(len(host.writes()), count)

    def test_late_solver_readback_drift_rolls_back_rows_and_manifest(self):
        self._assert_late_activation_drift_restores_source("source_voperator2")

    def test_late_activation_callback_restores_readonly_normalize_and_full_source_state(self):
        self._assert_late_activation_drift_restores_source("source_vnormalize2")

    def test_late_activation_extrapolation_drift_restores_full_source_state(self):
        for before in (True, False):
            with self.subTest(before=before):
                self._assert_late_activation_drift_restores_source("source_activate1", extrapolation_before=before)

    def test_late_activation_callback_restores_disabled_global_cycle_length_and_gates(self):
        for close_range_gate in (False, True):
            with self.subTest(close_range_gate=close_range_gate):
                self._assert_late_activation_drift_restores_source("srccyclelength", close_range_gate=close_range_gate)

    def _assert_late_activation_drift_restores_source(self, target_name, *, extrapolation_before=None, close_range_gate=False):
        with FakeSourceHost(self.addon) as host:
            host.build()
            host.put_cache()
            host.hou.setFrame(7.25)
            original_frame = host.hou.frame()
            original_state = host.state_path.read_bytes()
            root, _manifest = self.addon._fx_manifest("abc123")
            original_embedded_manifest = root.userData("bridge_fx_manifest_v1")
            solver = host.role("solver")
            names = set(host.manifest()["solver_sourcing"]["parameter_readback"]) | {"srclimitframerange"}
            parameters = {name: solver.parm(name) or solver.parmTuple(name) for name in names}
            for name, parm in parameters.items():
                self.assertIsNotNone(parm, name)
            original_parameters = {name: parm.eval() for name, parm in parameters.items()}
            original_keys = {
                name: tuple(key.asCode() for key in solver.parm(name).keyframes())
                for name in ("source_activate1", "source_activate2")
            }
            original_extrapolation = {
                name: tuple(solver.parm(name).keyframeExtrapolation(before) for before in (True, False))
                for name in original_keys
            }
            original_program = host.role("source_control").parm("snippet").eval()
            original_radii = host.role("source").parmTuple("rad").eval()
            original_voxel = host.role("source_volume").parm("voxelsize").eval()
            target = solver.parm(target_name)
            corrupt_value = (target.parmTemplate().menuItems().index("add") if target_name == "source_voperator2"
                             else target.eval() + 1 if target_name == "srccyclelength" else 1)
            if target_name in {"source_vnormalize2", "srccyclelength"}:
                self.assertTrue(target.isDisabled())
            original_set = host.parm_class.setKeyframes
            injected = {"done": False}

            def drift_after_activation(parm, keys):
                original_set(parm, keys)
                if (parm.path() == solver.parm("source_activate2").path()
                        and not injected["done"]
                        and any(key.frame() == 80 and key.value() == 1 for key in keys)):
                    injected["done"] = True
                    if extrapolation_before is not None:
                        target._native_state["pre_extrapolation" if extrapolation_before else "post_extrapolation"] = "parmExtrapolate.Linear"
                    else:
                        target.value = corrupt_value
                    if close_range_gate:
                        solver.parm("srclimitframerange").value = 0

            with patch.object(host.parm_class, "setKeyframes", drift_after_activation):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            with self.subTest(check="injection_reached"):
                self.assertTrue(injected["done"])
            with self.subTest(check="failure_code"):
                self.assertEqual(caught.exception.code, "PARAMETER_READBACK_MISMATCH")
            for name, value in original_parameters.items():
                with self.subTest(parameter=name):
                    self.assertEqual(parameters[name].eval(), value)
            for name, keys in original_keys.items():
                with self.subTest(channel=name):
                    self.assertEqual(tuple(key.asCode() for key in solver.parm(name).keyframes()), keys)
                    self.assertEqual(
                        tuple(solver.parm(name).keyframeExtrapolation(before) for before in (True, False)),
                        original_extrapolation[name])
            with self.subTest(check="source_values"):
                self.assertEqual(host.role("source_control").parm("snippet").eval(), original_program)
                self.assertEqual(host.role("source").parmTuple("rad").eval(), original_radii)
                self.assertEqual(host.role("source_volume").parm("voxelsize").eval(), original_voxel)
            with self.subTest(check="manifest"):
                self.assertEqual(host.state_path.read_bytes(), original_state)
                self.assertEqual(root.userData("bridge_fx_manifest_v1"), original_embedded_manifest)
            with self.subTest(check="frame"):
                self.assertEqual(host.hou.frame(), original_frame)

    def test_moving_window_and_pulse_count_replace_old_activation_keys(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(pulse_count=3, emission_start_frame=10, emission_end_frame=19))
            old = {
                index: keyframe_events(host.role("solver").parm("source_activate{}".format(index)))
                for index in (1, 2)
            }
            self.assertIn(10, [frame for frame, _value in old[1]])

            host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            solver = host.role("solver")
            updated = {
                index: keyframe_events(solver.parm("source_activate{}".format(index)))
                for index in (1, 2)
            }
            expected = [(1, 0), (80, 1), (101, 0), (181, 0)]
            self.assertEqual(updated[1], expected)
            self.assertEqual(updated[2], expected)
            self.assertNotIn(10, [frame for frame, _value in updated[1]])
            self.assertNotIn(12, [frame for frame, _value in updated[1]])
            self.assertNotIn(14, [frame for frame, _value in updated[1]])
            for frame in (1, 9, 79, 101, 102, 180, 181, 500):
                self.assertEqual(constant_value(updated[2], frame), 0, frame)
            for frame in (80, 99, 100):
                self.assertEqual(constant_value(updated[2], frame), 1, frame)

    def test_activation_write_interruption_restores_owned_schedule_and_manifest(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(pulse_count=3, emission_start_frame=10, emission_end_frame=19))
            old_keys = {
                index: keyframe_events(host.role("solver").parm("source_activate{}".format(index)))
                for index in (1, 2)
            }
            original_state = host.state_path.read_bytes()
            original_set = host.parm_class.setKeyframes
            failed = {"done": False}

            def interrupt_once(parm, keys):
                original_set(parm, keys)
                if parm.name() == "source_activate1" and not failed["done"]:
                    failed["done"] = True
                    raise RuntimeError("synthetic write interruption")

            with patch.object(host.parm_class, "setKeyframes", interrupt_once):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            self.assertEqual(caught.exception.code, "PARAMETER_SET_FAILED")
            self.assertTrue(failed["done"])
            for index in (1, 2):
                self.assertEqual(keyframe_events(host.role("solver").parm("source_activate{}".format(index))), old_keys[index])
            self.assertEqual(host.state_path.read_bytes(), original_state)

    def test_activation_readback_failure_restores_owned_schedule_and_manifest(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(pulse_count=3, emission_start_frame=10, emission_end_frame=19))
            old_keys = {
                index: keyframe_events(host.role("solver").parm("source_activate{}".format(index)))
                for index in (1, 2)
            }
            original_state = host.state_path.read_bytes()
            original_set = host.parm_class.setKeyframes
            injected = {"done": False}

            def add_unexpected_key_once(parm, keys):
                original_set(parm, keys)
                if parm.name() == "source_activate1" and not injected["done"]:
                    injected["done"] = True
                    extra = host.native.Keyframe(0)
                    extra.setFrame(999)
                    extra.setValue(0)
                    extra.setExpression("constant()")
                    host.native.set_parm_state(parm,keyframes=[*parm.keyframes(),extra])

            with patch.object(host.parm_class, "setKeyframes", add_unexpected_key_once):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            self.assertEqual(caught.exception.code, "PARAMETER_READBACK_MISMATCH")
            self.assertTrue(injected["done"])
            for index in (1, 2):
                self.assertEqual(keyframe_events(host.role("solver").parm("source_activate{}".format(index))), old_keys[index])
            self.assertEqual(host.state_path.read_bytes(), original_state)

    def test_external_activation_key_is_never_deleted_on_rebuild(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(pulse_count=3, emission_start_frame=10, emission_end_frame=19))
            activation = host.role("solver").parm("source_activate1")
            external = host.native.Keyframe(0)
            external.setFrame(999)
            external.setValue(0)
            external.setExpression("constant()")
            host.native.set_parm_state(activation,keyframes=[*activation.keyframes(),external])
            before = keyframe_events(activation)
            write_count = len(host.writes())
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            self.assertEqual(caught.exception.code, "SCENE_STATE_MISMATCH")
            self.assertEqual(keyframe_events(activation), before)
            self.assertEqual(len(host.writes()), write_count)

    def test_density_update_with_inactive_future_window_preserves_solver_schedule(self):
        with FakeSourceHost(self.addon) as host:
            host.hou.setFrame(1.25)
            original_frame = host.hou.frame()
            original = host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            solver = host.role("solver")
            original_keys = {
                name: tuple(key.asCode() for key in solver.parm(name).keyframes())
                for name in ("source_activate1", "source_activate2")
            }
            original_extrapolation = {
                name: tuple(solver.parm(name).keyframeExtrapolation(before) for before in (True, False))
                for name in original_keys
            }
            original_program = host.role("source_control").parm("snippet").eval()
            self.assertEqual(host.hou.frame(), original_frame)
            self.assertTrue(solver.parm("source_vscale1").isDisabled())
            for name in original_keys:
                self.assertEqual(solver.parm(name).eval(), 0)
            host.put_cache()

            changed = host.build(source_params(
                pulse_count=1, emission_start_frame=80, emission_end_frame=100, density=2.4,
            ))
            manifest = changed["scene_manifest"]
            self.assertNotEqual(manifest["source_plan_sha256"], original["scene_manifest"]["source_plan_sha256"])
            self.assertNotEqual(host.role("source_control").parm("snippet").eval(), original_program)
            self.assertEqual(manifest["source_plan_host_controls"]["density_scale"], 1.0)
            self.assertEqual(solver.parm("source_vscale1").eval(), 1.0)
            self.assertTrue(solver.parm("source_vscale1").isDisabled())
            for name, keys in original_keys.items():
                self.assertEqual(tuple(key.asCode() for key in solver.parm(name).keyframes()), keys)
                self.assertEqual(
                    tuple(solver.parm(name).keyframeExtrapolation(before) for before in (True, False)),
                    original_extrapolation[name],
                )
                self.assertEqual(solver.parm(name).eval(), 0)
            self.assertTrue(all(item["readback_verified"] for item in manifest["source_plan_host_readback"].values()))
            self.assertTrue(manifest["solver_sourcing"]["readback_verified"])
            self.assertTrue(manifest["source_plan_cache_invalidated"])
            self.assertNotIn("cache", manifest)
            self.assertFalse(manifest["execution_assessment"]["simulation_executed"])
            self.assertFalse(any(call[0] == "cook" and call[1].endswith(("FX_SOLVER", "FX_OUTPUT")) for call in host.calls))
            self.assertEqual(host.hou.frame(), original_frame)

    def test_solver_control_change_invalidates_cache_and_does_not_cook(self):
        with FakeSourceHost(self.addon) as host:
            host.build()
            host.put_cache()
            changed = host.build(source_params(pulse_count=1, emission_start_frame=80, emission_end_frame=100))
            manifest = changed["scene_manifest"]
            self.assertTrue(manifest["source_plan_cache_invalidated"])
            self.assertNotIn("cache", manifest)
            self.assertTrue(manifest["solver_sourcing"]["readback_verified"])
            self.assertFalse(manifest["execution_assessment"]["simulation_executed"])

    def test_non_exact_build_missing_exact_solver_or_unowned_rows_is_rejected(self):
        with FakeSourceHost(self.addon) as host:
            host.hou.applicationVersionString = lambda: "21.0.631-other"
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build()
            self.assertEqual(caught.exception.code, "UNSUPPORTED_NATIVE_VERSION")
            self.assertEqual(host.writes(), [])

        with FakeSourceHost(self.addon) as host:
            del host.catalog[('Sop','pyrosolver')]
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build()
            self.assertEqual(caught.exception.code, "UNSUPPORTED_NODE")
            self.assertEqual(host.writes(), [])

        with FakeSourceHost(self.addon) as host:
            host.build()
            manifest = host.manifest()
            root = host.hou.node(manifest['execution_root'])
            manifest.pop("solver_sourcing", None)
            manifest.pop("solver_sourcing_contract", None)
            root.setUserData("bridge_fx_manifest_v1", json.dumps(manifest, sort_keys=True))
            write_count = len(host.writes())
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build(source_params(emission_start_frame=80, emission_end_frame=100))
            self.assertEqual(caught.exception.code, "SCENE_STATE_MISMATCH")
            self.assertEqual(len(host.writes()), write_count)


if __name__ == "__main__":
    unittest.main()
