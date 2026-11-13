# -*- coding: utf-8 -*-
"""Reverse tests: connection semantics must participate in contract comparison.

The verifier builds the host-side canonical contract (including connections)
and compares it with the add-on's ``_fx_pack_semantic_contract``.  These tests
pin both directions: identical packs produce no drift, and ANY change to a
wire (source_output, destination_input, dropped connection, legacy input_role)
is detected by the verifier instead of being silently ignored.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
HOST_CATALOG_PATH = ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py"
VERIFIER_PATH = ROOT / "tools" / "verify_support_claims.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SemanticContractConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load("_semantic_contract_addon", ADDON_PATH)
        cls.verifier = _load("_semantic_contract_verifier", VERIFIER_PATH)
        from houdini_bridge import domain_packs
        cls.host = domain_packs

    def _host_pack(self, pack_id: str):
        return self.host.get_domain_pack(pack_id)

    def test_every_pack_matches_host_contract(self) -> None:
        for pack_id in sorted(self.addon._FX_PACKS):
            drift = self.verifier._pack_semantic_drift(
                self.addon, self.addon._FX_PACKS[pack_id], self._host_pack(pack_id))
            self.assertEqual(drift, [], "{} must match the host contract".format(pack_id))

    def test_connections_are_part_of_the_contract(self) -> None:
        contract = self.addon._fx_pack_semantic_contract(self.addon._FX_PACKS["vellum_softbody_grains_v1"])
        self.assertIn("connections", contract)
        self.assertTrue(contract["connections"], "vellum pack must declare wires")

    def test_verifier_loads_source_catalog_with_relative_native_imports(self) -> None:
        before = dict(sys.modules)
        hashes, _legacy, _controls, _drift = self.verifier._domain_contract_hashes(ROOT)
        self.assertEqual(set(hashes), self.verifier.PACKS)
        self.assertEqual(
            {name: module for name, module in sys.modules.items()
             if name.startswith("_support_claims_houdini_host_catalog")},
            {name: module for name, module in before.items()
             if name.startswith("_support_claims_houdini_host_catalog")})

    def test_changed_source_output_is_detected(self) -> None:
        pack = copy.deepcopy(self.addon._FX_PACKS["vellum_softbody_grains_v1"])
        pack["connections"][0]["source_output"] = int(pack["connections"][0]["source_output"]) + 1
        drift = self.verifier._pack_semantic_drift(
            self.addon, pack, self._host_pack("vellum_softbody_grains_v1"))
        self.assertTrue(drift, "changed source_output must be detected")

    def test_changed_destination_input_is_detected(self) -> None:
        pack = copy.deepcopy(self.addon._FX_PACKS["vellum_cloth_v1"])
        pack["connections"][0]["destination_input"] = int(pack["connections"][0]["destination_input"]) + 1
        drift = self.verifier._pack_semantic_drift(
            self.addon, pack, self._host_pack("vellum_cloth_v1"))
        self.assertTrue(drift, "changed destination_input must be detected")

    def test_dropped_wire_is_detected(self) -> None:
        pack = copy.deepcopy(self.addon._FX_PACKS["vellum_cloth_v1"])
        pack["connections"] = pack["connections"][1:]
        drift = self.verifier._pack_semantic_drift(
            self.addon, pack, self._host_pack("vellum_cloth_v1"))
        self.assertTrue(drift, "a dropped connection must be detected")

    def test_legacy_input_role_change_is_detected(self) -> None:
        pack = copy.deepcopy(self.addon._FX_PACKS["hair_fur_v1"])
        legacy_index = next(i for i, node in enumerate(pack["nodes"]) if node.get("input_role"))
        pack["nodes"][legacy_index]["input_role"] = str(pack["nodes"][legacy_index]["input_role"]) + "_renamed"
        drift = self.verifier._pack_semantic_drift(
            self.addon, pack, self._host_pack("hair_fur_v1"))
        self.assertTrue(drift, "changed legacy input_role must change the derived wires and be detected")


if __name__ == "__main__":
    unittest.main()
