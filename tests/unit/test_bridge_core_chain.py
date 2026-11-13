# -*- coding: utf-8 -*-
"""Core-chain software gate: graph contract, unlock semantics, operation ids,
pack connections and legacy-compat behaviour (no Houdini required).

Standard-library unittest so ``tests/run_tests.py`` discovers every case.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_ADDON_DIR = Path(__file__).resolve().parents[2] / "plugins" / "houdini" / "_impl"

_contract_module = None
_packs_module = None


def _contract():
    global _contract_module
    if _contract_module is None:
        _contract_module = _load("_bridge_core_contract_test", _ADDON_DIR / "bridge_core_contract.py")
    return _contract_module


def _packs():
    global _packs_module
    if _packs_module is None:
        from houdini_bridge import domain_packs
        _packs_module = domain_packs
    return _packs_module


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- graph contract
class TestConnectionContract(unittest.TestCase):
    def test_valid_set_normalized(self) -> None:
        conns = [
            {"source_role": "source", "source_output": 0, "destination_role": "constraints", "destination_input": 0},
            {"source_role": "constraints", "source_output": 1, "destination_role": "solver", "destination_input": 1},
        ]
        result = _contract().validate_connection_set(conns, ["source", "constraints", "solver", "output"])
        self.assertIs(result["ok"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["connections"], conns)

    def test_duplicate_destination_port_rejected(self) -> None:
        conns = [
            {"source_role": "source", "source_output": 0, "destination_role": "solver", "destination_input": 0},
            {"source_role": "constraints", "source_output": 0, "destination_role": "solver", "destination_input": 0},
        ]
        result = _contract().validate_connection_set(conns, ["source", "constraints", "solver"])
        self.assertIs(result["ok"], False)
        self.assertTrue(any("duplicate" in e for e in result["errors"]))

    def test_negative_and_non_int_ports_rejected(self) -> None:
        result = _contract().validate_connection_set(
            [{"source_role": "source", "source_output": -1, "destination_role": "solver", "destination_input": True}],
            ["source", "solver"])
        self.assertIs(result["ok"], False)
        self.assertEqual(len(result["errors"]), 2)

    def test_unknown_role_rejected(self) -> None:
        result = _contract().validate_connection_set(
            [{"source_role": "ghost", "source_output": 0, "destination_role": "solver", "destination_input": 0}],
            ["solver"])
        self.assertIs(result["ok"], False)
        self.assertTrue(any("source_role" in e for e in result["errors"]))

    def test_malformed_entry_rejected_before_side_effects(self) -> None:
        result = _contract().validate_connection_set([{"nonsense": 1}, 42], ["solver"])
        self.assertIs(result["ok"], False)

    def test_non_sequence_rejected(self) -> None:
        self.assertIs(_contract().validate_connection_set({"a": 1}, ["solver"])["ok"], False)


# ---------------------------------------------------------------- vellum packs
class TestVellumPackConnections(unittest.TestCase):
    def test_softbody_pack_declares_constraint_stream(self) -> None:
        conns = _packs().get_domain_pack("vellum_softbody_grains_v1").declared_connections()
        self.assertIn({"source_role": "constraints", "source_output": 1,
                       "destination_role": "solver", "destination_input": 1}, conns)
        self.assertIn({"source_role": "constraints", "source_output": 0,
                       "destination_role": "solver", "destination_input": 0}, conns)

    def test_cloth_pack_declares_full_chain(self) -> None:
        packs = _packs()
        pack = packs.get_domain_pack("vellum_cloth_v1")
        conns = pack.declared_connections()
        roles = [n.role for n in pack.nodes]
        self.assertIs(packs.validate_connections(conns, roles)["ok"], True)
        # Native Vellum ports carry geometry, constraints and collisions
        # separately; a node/edge count cannot detect a miswired stream.
        expected = {
            ("source", 0, "constraints", 0),
            ("collision_source", 0, "collision_transform", 0),
            ("collision_transform", 0, "solver", 2),
            ("constraints", 0, "solver", 0),
            ("constraints", 1, "solver", 1),
            ("solver", 0, "output", 0),
        }
        actual = {(c["source_role"], c["source_output"], c["destination_role"], c["destination_input"])
                  for c in conns}
        self.assertEqual(actual, expected)

    def test_legacy_pack_falls_back_to_input_role(self) -> None:
        conns = _packs().get_domain_pack("hair_fur_v1").declared_connections()
        self.assertTrue(all(c["source_output"] == 0 and c["destination_input"] == 0 for c in conns))

    def test_to_dict_carries_connections(self) -> None:
        payload = _packs().get_domain_pack("vellum_softbody_grains_v1").to_dict()
        self.assertIn("connections", payload)
        self.assertEqual(len(payload["connections"]), 4)

    def test_structural_validation_of_pack_wires(self) -> None:
        pack = _packs().get_domain_pack("vellum_softbody_grains_v1")
        roles = [n.role for n in pack.nodes]
        self.assertTrue(_packs().validate_connections(pack.declared_connections(), roles)["ok"])


# ---------------------------------------------------------------- unlock semantics
class TestUnlockSemantics(unittest.TestCase):
    def test_default_unlock_non_recursive(self) -> None:
        self.assertEqual(_contract().interpret_unlock_params({}),
                         {"ok": True, "propagate": False, "deprecated_value_used": False})

    def test_propagate_true_explicit(self) -> None:
        out = _contract().interpret_unlock_params({"propagate": True})
        self.assertTrue(out["ok"] and out["propagate"] is True)

    def test_deprecated_value_true_accepted_with_flag(self) -> None:
        out = _contract().interpret_unlock_params({"value": True})
        self.assertTrue(out["ok"] and out["deprecated_value_used"] is True)

    def test_value_false_rejected_not_silently_relocked(self) -> None:
        out = _contract().interpret_unlock_params({"value": False})
        self.assertIs(out["ok"], False)
        self.assertEqual(out["error"], "UNLOCK_SEMANTICS_CHANGED")

    def test_non_bool_propagate_rejected(self) -> None:
        self.assertIs(_contract().interpret_unlock_params({"propagate": "yes"})["ok"], False)


# ---------------------------------------------------------------- operation ids
class TestOperationIds(unittest.TestCase):
    def test_stable_id_for_identical_request(self) -> None:
        a = _contract().derive_operation_id("t1", "subject", [2, 4, 6])
        b = _contract().derive_operation_id("t1", "subject", [2, 4, 6])
        self.assertEqual(a, b)
        self.assertEqual(len(a), 16)

    def test_different_frames_different_id(self) -> None:
        self.assertNotEqual(_contract().derive_operation_id("t1", "s", [2, 4]),
                            _contract().derive_operation_id("t1", "s", [2, 4, 6]))

    def test_different_task_different_id(self) -> None:
        self.assertNotEqual(_contract().derive_operation_id("t1", "s", [2]),
                            _contract().derive_operation_id("t2", "s", [2]))

    def test_frame_order_matters(self) -> None:
        self.assertNotEqual(_contract().derive_operation_id("t1", "s", [2, 4]),
                            _contract().derive_operation_id("t1", "s", [4, 2]))


# ---------------------------------------------------------------- source menu
class TestSourceMenuChoice(unittest.TestCase):
    def test_polygon_mesh_preferred(self) -> None:
        labels = ["Primitive", "Polygon", "Polygon Mesh", "NURBS", "Polygon Soup"]
        self.assertEqual(_contract().choose_polygon_menu_index(labels), 2)

    def test_fallback_polygons(self) -> None:
        self.assertEqual(_contract().choose_polygon_menu_index(["Primitive", "Polygons"]), 1)

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(_contract().choose_polygon_menu_index(["Primitive", "NURBS"]))


class TestSourceFixtureContract(unittest.TestCase):
    def test_public_controls_are_complete_and_missing_control_is_rejected(self) -> None:
        import copy
        from houdini_bridge import native_pyro_domains
        from source_host_fixture import FakeSourceHost, source_params
        from test_houdini_parm_probe import _load_addon

        addon = _load_addon()
        for version in native_pyro_domains.SUPPORTED_VERSIONS:
            with self.subTest(version=version), FakeSourceHost(addon, version=version) as host:
                _pack_id, pack = addon._fx_pack(source_params())
                self.assertEqual(set(pack['controls']), set(native_pyro_domains.control_contract(
                    native_pyro_domains.SMOKE, version)))
                broken = copy.deepcopy(addon._FX_PACKS['pyro_smoke_v1'])
                broken['controls'].pop('volume_samples')
                with unittest.mock.patch.dict(addon._FX_PACKS, {'pyro_smoke_v1': broken}):
                    with self.assertRaises(addon.BridgeCommandError) as caught:
                        host.build()
                self.assertEqual(caught.exception.code, 'PUBLIC_CONTROL_CONTRACT_CHANGED')
                self.assertEqual(host.writes(), [])
                self.assertFalse(host.state_path.exists())

    def test_captured_context_and_compiled_tuple_capacity_are_enforced(self) -> None:
        from source_host_fixture import FakeSourceHost
        from test_houdini_parm_probe import _load_addon

        with FakeSourceHost(_load_addon()) as host:
            with self.assertRaisesRegex(ValueError, 'Obj/attribwrangle'):
                host.hou.node('/obj').createNode('attribwrangle','invalid_context')
            geometry = host.hou.node('/obj').createNode('geo','tuple_fixture')
            convolve = geometry.createNode('volumeconvolve3','convolve')
            self.assertIsNone(convolve.parm('invented_control'))
            stencil = convolve.parmTuple('convolvezz')
            self.assertEqual(len(stencil), 9)
            with self.assertRaisesRegex(ValueError, 'arity'):
                stencil.set([0.0] * 8)
            stencil.set([0.0] * 4 + [1.0] + [0.0] * 4)
            self.assertEqual(stencil.eval(), (0.0,) * 4 + (1.0,) + (0.0,) * 4)

    def test_batch_keyframe_update_retains_unsupplied_frames(self) -> None:
        from source_host_fixture import FakeSourceHost
        from test_houdini_parm_probe import _load_addon

        with FakeSourceHost(_load_addon()) as host:
            geometry = host.hou.node('/obj').createNode('geo','channel_fixture')
            radius = geometry.createNode('sphere','source').parm('radx')
            for frame, value in ((1, 0.5), (9, 1.0), (1, 2.0)):
                key = host.native.Keyframe(value)
                key.setFrame(frame)
                radius.setKeyframes([key])
            self.assertEqual([(key.frame(),key.value()) for key in radius.keyframes()],
                             [(1.0,2.0),(9.0,1.0)])
            radius.deleteAllKeyframes()
            self.assertEqual(radius.keyframes(), ())


if __name__ == "__main__":
    unittest.main()
