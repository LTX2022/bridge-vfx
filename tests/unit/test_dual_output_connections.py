# -*- coding: utf-8 -*-
"""Dual-output wire identity through the synthetic host.

The add-on connects with the HOM three-argument form
``node.setInput(input_index, source, output_index)``.  The fixture must store
the source output index and read it back, so output0 and output1 of the same
source node are distinct wires.  These tests fail if the fixture silently
drops the third argument or if the add-on stops verifying against native port
indices.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import source_host_fixture as fixture

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def _load_addon():
    spec = importlib.util.spec_from_file_location("_dual_output_addon", ADDON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACK_ID = 'fixture_dual_output_v1'


def _dual_output_pack():
    """Generic wire fixture using the captured Vellum two-stream operators."""
    return {
        "nodes": [
            {"role": "source", "category": "sop", "types": ["vellumconstraints"], "required_parms": []},
            {"role": "solver", "category": "sop", "types": ["vellumsolver"], "required_parms": []},
            {"role": "output", "category": "sop", "types": ["null"], "required_parms": []},
        ],
        "connections": [
            {"source_role": "source", "source_output": 0, "destination_role": "solver", "destination_input": 0},
            {"source_role": "source", "source_output": 1, "destination_role": "solver", "destination_input": 1},
            {"source_role": "solver", "source_output": 0, "destination_role": "output", "destination_input": 0},
        ],
        "controls": {},
        "maturity": "experimental", "preview_kind": "topology_scaffold",
        "validated_houdini_versions": [],
    }


class DualOutputConnectionTests(unittest.TestCase):
    def test_output0_and_output1_are_distinct_wires(self) -> None:
        addon = _load_addon()
        with fixture.FakeSourceHost(addon, pack_override=_dual_output_pack(), pack_id=PACK_ID) as host:
            result = host.build(params={"task_id": "abc123", "step_params": {"domain_pack": PACK_ID}})
            self.assertEqual(result["execution_state"], "EDITABLE_DOMAIN_GRAPH")
            self.assertFalse(result["real_execution_validated"])
            manifest = host.manifest()
            verified = manifest["connections"]["verified"]
            by_wire = {(entry["destination_role"], entry["destination_input"]): entry for entry in verified}
            self.assertEqual(by_wire[("solver", 0)]["native_readback"]["source_output"], 0)
            self.assertEqual(by_wire[("solver", 1)]["native_readback"]["source_output"], 1)
            # same source node feeds both solver inputs, at different outputs
            self.assertEqual(by_wire[("solver", 0)]["native_readback"]["source_path"],
                             by_wire[("solver", 1)]["native_readback"]["source_path"])
            self.assertEqual(by_wire[("output", 0)]["native_readback"]["source_path"],
                             by_wire[("solver", 0)]["native_readback"]["source_path"].replace("FX_SOURCE", "FX_SOLVER"))
            self.assertTrue(all(entry["verified"] for entry in verified))

    def test_fixture_readback_distinguishes_output_index(self) -> None:
        addon = _load_addon()
        with fixture.FakeSourceHost(addon, pack_override=_dual_output_pack(), pack_id=PACK_ID) as host:
            host.build(params={"task_id": "abc123", "step_params": {"domain_pack": PACK_ID}})
            solver = host.role("solver")
            native = {connection.inputIndex(): connection.outputIndex()
                      for connection in solver.inputConnections()}
            self.assertEqual(native, {0: 0, 1: 1})
            # inputs() keeps returning source nodes in port order
            source = host.role("source")
            self.assertIs(solver.inputs()[0], source)
            self.assertIs(solver.inputs()[1], source)

    def test_set_input_call_record_keeps_output_index(self) -> None:
        addon = _load_addon()
        with fixture.FakeSourceHost(addon, pack_override=_dual_output_pack(), pack_id=PACK_ID) as host:
            host.build(params={"task_id": "abc123", "step_params": {"domain_pack": PACK_ID}})
            set_calls = [call for call in host.calls if call[0] == "setInput"]
            self.assertTrue(any(call[4] == 1 for call in set_calls),
                            "the output index must be recorded, not dropped")


if __name__ == "__main__":
    unittest.main()
