"""Regression cover for DCC verification gates.

A DCC that stays silent used to be reported as a passing gate.  That made
every downstream decision -- approval, verification, completion -- rest on a
fabrication, because the orchestrator could not tell "verified" apart from
"nothing was checked".  These tests lock in that silence now fails.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dcc_task_runtime import (
    TaskSpec,
    attach_evidence_carrier,
    normalize_dcc_gates,
    verification_gates,
)
from dcc_task_runtime.engine import Step

from houdini_bridge.tasks import HoudiniCommandAdapter
from nuke_bridge.tasks import NukeCommandAdapter


class _SilentClient:
    """A DCC that answers a mutation with no gates at all."""

    def __init__(self, response=None) -> None:
        self.response = response if response is not None else {}
        self.calls = []

    def call(self, command, params=None):
        self.calls.append(command)
        return dict(self.response)


class NormalizeDccGatesTests(unittest.TestCase):
    def test_missing_gates_key_fails_with_machine_readable_reason(self) -> None:
        gates = normalize_dcc_gates("agent.fx.build_preview", {})
        self.assertEqual(len(gates), 1)
        self.assertFalse(gates[0]["passed"])
        self.assertEqual(gates[0]["reason"], "dcc_returned_no_gates")
        self.assertEqual(gates[0]["kind"], "verification")

    def test_empty_gate_list_fails(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": []})
        self.assertFalse(gates[0]["passed"])
        self.assertEqual(gates[0]["reason"], "dcc_returned_no_gates")

    def test_real_passing_gate_is_preserved(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": True}]})
        self.assertEqual(len(gates), 1)
        self.assertTrue(gates[0]["passed"])
        self.assertEqual(gates[0]["name"], "cook")
        self.assertEqual(gates[0]["kind"], "verification")

    def test_real_failing_gate_is_preserved(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": False}]})
        self.assertFalse(gates[0]["passed"])

    def test_non_boolean_passed_is_treated_as_failure(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": "yes"}]})
        self.assertFalse(gates[0]["passed"])
        self.assertEqual(gates[0]["reason"], "gate_passed_not_boolean")

    def test_non_object_gate_entry_is_treated_as_failure(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": ["cook"]})
        self.assertFalse(gates[0]["passed"])
        self.assertEqual(gates[0]["reason"], "gate_entry_not_object")

    def test_errors_in_payload_do_not_become_a_pass(self) -> None:
        # The old code derived ``passed`` from ``not data.get("errors")``,
        # so a DCC that reported errors but no gates could still be read as
        # clean by anything inspecting only the payload.
        gates = normalize_dcc_gates("step", {"errors": None, "gates": []})
        self.assertFalse(gates[0]["passed"])


class EvidenceCarrierTests(unittest.TestCase):
    def test_carrier_mirrors_passing_verification(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": True}]})
        gates = attach_evidence_carrier(gates, "step", {"scorecard": {}})
        carrier = gates[-1]
        self.assertTrue(carrier["passed"])
        self.assertEqual(carrier["kind"], "evidence_carrier")

    def test_carrier_never_passes_when_verification_fails(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": False}]})
        gates = attach_evidence_carrier(gates, "step", {"scorecard": {}})
        self.assertFalse(gates[-1]["passed"])

    def test_carrier_never_passes_without_verification(self) -> None:
        # This is the exact fabrication the old code produced: a structured
        # payload alone was enough to emit ``passed: True``.
        gates = normalize_dcc_gates("step", {})
        gates = attach_evidence_carrier(gates, "step", {"scorecard": {}})
        self.assertFalse(gates[-1]["passed"])

    def test_carrier_is_excluded_from_verification(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": True}]})
        gates = attach_evidence_carrier(gates, "step", {"scorecard": {}})
        self.assertEqual(len(gates), 2)
        self.assertEqual(len(verification_gates(gates)), 1)

    def test_carrier_still_carries_the_structured_payload(self) -> None:
        gates = normalize_dcc_gates("step", {"gates": [{"name": "cook", "passed": True}]})
        gates = attach_evidence_carrier(gates, "step", {"evidence": {"frames": [1, 5, 9]}})
        self.assertEqual(gates[-1]["details"]["evidence"]["frames"], [1, 5, 9])


class BridgeRefusesSilenceTests(unittest.TestCase):
    def _houdini_spec(self) -> TaskSpec:
        return TaskSpec(
            task_type="houdini.reference_effect",
            intent="rebuild an editable reference effect",
            target_application="houdini",
            constraints={"fx": {"domain_pack": "pyro_smoke_v1"}},
            render={"frame_range": {"start": 1, "end": 9, "step": 4}},
        )

    def _nuke_spec(self) -> TaskSpec:
        return TaskSpec(
            task_type="nuke.reference_composite",
            intent="composite the effect over the plate",
            target_application="nuke",
        )

    def test_houdini_adapter_rejects_a_silent_dcc(self) -> None:
        adapter = HoudiniCommandAdapter(_SilentClient())
        step = Step(identifier="build_preview", phase="setup", action="agent.fx.build_preview")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as caught:
                adapter.execute(step, self._houdini_spec(), Path(directory))
        self.assertIn("dcc_returned_no_gates", str(caught.exception))

    def test_houdini_adapter_rejects_silence_even_with_structured_data(self) -> None:
        # A rich payload with no gates must not be mistaken for success.
        client = _SilentClient({"scorecard": {"target": 1.0}, "evidence": {"frames": [1, 5, 9]}})
        adapter = HoudiniCommandAdapter(client)
        step = Step(identifier="verify", phase="verify", action="agent.fx.collect_evidence")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                adapter.execute(step, self._houdini_spec(), Path(directory))

    def test_nuke_adapter_rejects_a_silent_dcc(self) -> None:
        adapter = NukeCommandAdapter(_SilentClient())
        step = Step(identifier="build_composite", phase="setup", action="agent.nuke.composite.build_graph")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as caught:
                adapter.execute(step, self._nuke_spec(), Path(directory))
        self.assertIn("dcc_returned_no_gates", str(caught.exception))

    def test_a_real_gate_still_gets_through(self) -> None:
        client = _SilentClient(
            {
                "gates": [
                    {
                        "name": "editable_native_fx_topology",
                        "passed": False,
                        "kind": "topology_scaffold",
                        "status": "INCONCLUSIVE",
                    }
                ],
                "visual_validation": "INCONCLUSIVE",
            }
        )
        adapter = HoudiniCommandAdapter(client)
        step = Step(identifier="build_preview", phase="setup", action="agent.fx.build_preview")
        with tempfile.TemporaryDirectory() as directory:
            result = adapter.execute(step, self._houdini_spec(), Path(directory))
        self.assertTrue(all(gate["passed"] for gate in result["gates"]))
        self.assertEqual(result["outcome_state"], "DIAGNOSIS_INCONCLUSIVE")
        self.assertEqual(result["gates"][0]["reported_passed"], False)


if __name__ == "__main__":
    unittest.main()
