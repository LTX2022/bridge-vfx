from __future__ import annotations

import unittest

from dcc_task_runtime import (
    CausalDoctor,
    ChangeDirection,
    ControlAdjustment,
    DiagnosisInconclusive,
    DiagnosticRule,
    DomainPack,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceVerdict,
    FeedbackRule,
    IssueDimension,
    SemanticControl,
    StageGraph,
    StageKind,
    StageNode,
    builtin_domain_registry,
)


def diagnostic_pack() -> DomainPack:
    graph = StageGraph(
        (
            StageNode("source", StageKind.SOURCE, "smoke"),
            StageNode("simulation", StageKind.SIMULATION, "smoke", ("source",)),
            StageNode("render", StageKind.RENDER, "smoke", ("simulation",)),
            StageNode("composite", StageKind.COMPOSITE, "smoke", ("render",)),
        )
    )
    controls = tuple(
        SemanticControl(f"detail_{index}", "float", 0.0, 10.0, (), ("simulation",), True)
        for index in range(5)
    ) + (
        SemanticControl("filter_width", "float", 0.0, 10.0, (), ("render",), False),
        SemanticControl("blur_size", "float", 0.0, 10.0, (), ("composite",), False),
    )
    sim_adjustments = tuple(ControlAdjustment(f"detail_{index}", "scale", (1.1, 1.25, 1.5)) for index in range(5))
    return DomainPack(
        identifier="diagnostic_smoke",
        version="1.0.0",
        label="diagnostic smoke",
        components=("smoke",),
        stage_graph=graph,
        controls=controls,
        feedback_rules=(
            FeedbackRule(("烟太模糊", "smoke is blurry"), IssueDimension.SPATIAL_DETAIL, ChangeDirection.INCREASE),
        ),
        diagnostic_rules=(
            DiagnosticRule("field", (IssueDimension.SPATIAL_DETAIL,), "simulation_field", "simulation", ("field.high_frequency",), sim_adjustments, "raw density loses detail", next_question="请提供原始 density 诊断图。"),
            DiagnosticRule("render", (IssueDimension.SPATIAL_DETAIL,), "render_filter", "render", ("render.high_frequency",), (ControlAdjustment("filter_width", "scale", (0.9, 0.75)),), "render loses field detail"),
            DiagnosticRule("comp", (IssueDimension.SPATIAL_DETAIL,), "composite_blur", "composite", ("comp.high_frequency",), (ControlAdjustment("blur_size", "scale", (0.9, 0.75)),), "composite loses render detail"),
        ),
        required_evidence=("field.high_frequency", "render.high_frequency", "comp.high_frequency"),
        artifact_kinds=("density", "precomp", "final"),
    )


def evidence(issue_id: str, *records: EvidenceRecord) -> EvidenceBundle:
    return EvidenceBundle("task", issue_id, tuple(records), 73, "camera-hash", (1, 48, 1))


class CausalDoctorTests(unittest.TestCase):
    def test_language_maps_through_domain_rules_not_core_effect_names(self) -> None:
        doctor = CausalDoctor()
        pack = diagnostic_pack()
        chinese = doctor.interpret_feedback("这次烟太模糊", pack, "smoke")
        english = doctor.interpret_feedback("the smoke is blurry", pack, "smoke")
        self.assertEqual(chinese.dimension, IssueDimension.SPATIAL_DETAIL)
        self.assertEqual(english.direction, ChangeDirection.INCREASE)

        registry = builtin_domain_registry()
        cloth = registry.get("vellum_cloth_v1", "1.0.0")
        cloth_issue = doctor.interpret_feedback("布料太硬", cloth, "cloth")
        self.assertEqual(cloth_issue.dimension, IssueDimension.MOTION)

    def test_earliest_supported_stage_drives_bounded_candidates(self) -> None:
        doctor = CausalDoctor()
        pack = diagnostic_pack()
        issue = doctor.interpret_feedback("烟太模糊", pack, "smoke")
        bundle = evidence(
            issue.issue_id,
            EvidenceRecord("simulation", "field.high_frequency", EvidenceVerdict.SUPPORTS),
            EvidenceRecord("render", "render.high_frequency", EvidenceVerdict.SUPPORTS),
        )
        hypotheses = doctor.diagnose(issue, bundle, pack)
        self.assertEqual(hypotheses[0].cause_family, "simulation_field")
        current = {f"detail_{index}": 1.0 for index in range(5)}
        candidates = doctor.propose_candidates(issue, hypotheses[0], bundle, pack, current)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(len(candidate.changes) == 5 for candidate in candidates))
        self.assertTrue(all(candidate.fixed_seed == 73 for candidate in candidates))
        self.assertTrue(all(candidate.invalidates_components == ("smoke",) for candidate in candidates))

    def test_render_and_composite_faults_do_not_invalidate_simulation(self) -> None:
        doctor = CausalDoctor()
        pack = diagnostic_pack()
        issue = doctor.interpret_feedback("smoke is blurry", pack, "smoke")
        bundle = evidence(issue.issue_id, EvidenceRecord("render", "render.high_frequency", EvidenceVerdict.SUPPORTS))
        hypothesis = doctor.diagnose(issue, bundle, pack)[0]
        candidate = doctor.propose_candidates(issue, hypothesis, bundle, pack, {"filter_width": 2.0})[0]
        self.assertEqual(hypothesis.cause_family, "render_filter")
        self.assertEqual(candidate.invalidates_components, ())

    def test_missing_or_conflicting_evidence_is_inconclusive(self) -> None:
        doctor = CausalDoctor()
        pack = diagnostic_pack()
        issue = doctor.interpret_feedback("烟太模糊", pack, "smoke")
        with self.assertRaises(DiagnosisInconclusive) as missing:
            doctor.diagnose(issue, evidence(issue.issue_id), pack)
        self.assertIn("density", missing.exception.next_question)

        conflicted = evidence(
            issue.issue_id,
            EvidenceRecord("simulation", "field.high_frequency", EvidenceVerdict.SUPPORTS),
            EvidenceRecord("simulation", "field.high_frequency", EvidenceVerdict.REFUTES),
        )
        with self.assertRaises(DiagnosisInconclusive):
            doctor.diagnose(issue, conflicted, pack)

    def test_integer_controls_remain_integers(self) -> None:
        doctor = CausalDoctor()
        pack = builtin_domain_registry().get("water_flip_v1", "1.0.0")
        issue = doctor.interpret_feedback("水花不够", pack, "flip")
        bundle = evidence(issue.issue_id, EvidenceRecord("simulation", "water_flip_v1.simulation_evidence", EvidenceVerdict.SUPPORTS))
        hypothesis = doctor.diagnose(issue, bundle, pack)[0]
        current = {"particle_separation": 0.1, "substeps": 2, "viscosity": 0.0, "surface_tension": 0.0}
        candidates = doctor.propose_candidates(issue, hypothesis, bundle, pack, current)
        substep_values = [change.proposed for change in candidates[0].changes if change.control == "substeps"]
        self.assertEqual(substep_values, [3])
        self.assertIsInstance(substep_values[0], int)

    def test_explosion_candidate_invalidates_only_its_branch(self) -> None:
        doctor = CausalDoctor()
        pack = builtin_domain_registry().get("explosion_composite_v1", "1.0.0")
        issue = doctor.interpret_feedback("爆炸没力量", pack, "explosion")
        bundle = evidence(issue.issue_id, EvidenceRecord("smoke_simulation", "explosion_composite_v1.smoke_simulation_evidence", EvidenceVerdict.SUPPORTS))
        hypothesis = doctor.diagnose(issue, bundle, pack)[0]
        candidate = doctor.propose_candidates(issue, hypothesis, bundle, pack, {"smoke_dissipation": 1.0, "smoke_scale": 1.0})[0]
        self.assertEqual(candidate.invalidates_components, ("smoke",))
        self.assertNotIn("fire", candidate.invalidates_components)


if __name__ == "__main__":
    unittest.main()
