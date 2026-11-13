from __future__ import annotations

import unittest
from pathlib import Path

from dcc_task_runtime.model_acceptance import (
    DoubaoSkillConformanceEvidence,
    DoubaoUiControlEvidence,
    ModelRouteIdentity,
    SkillConformanceCase,
    skill_evidence_from_report,
    ui_evidence_from_event_manifest,
    verify_doubao_release_gate,
    verify_doubao_diagnostic_gate,
    FIRST_PARTY_DOMAIN_PACKS,
)


class DoubaoAcceptanceTests(unittest.TestCase):
    def route(self):
        return ModelRouteIdentity(
            "DoubaoDesktopRoute", "com.bot.pc.doubao", "2.27.10",
            str(Path(__file__).resolve().parent / "synthetic-applications" / "Doubao.app" / "Contents" / "MacOS" / "Doubao"), "a" * 64,
            "Developer ID Application", "b" * 64, "豆包", False,
        )

    def ui(self):
        return DoubaoUiControlEvidence(
            "ui-1", self.route(), "isolated-1", (True,) * 5, "c" * 64,
            True, False, True, True, True,
        )

    def cases(self, packs=("pyro_smoke_v1",)):
        return tuple(
            SkillConformanceCase(
                f"{pack}-{scenario}", pack, scenario, True, True, 0, False,
                reference_media_verified=scenario == "causal_candidate",
            )
            for pack in packs
            for scenario in ("build_inspect", "causal_candidate", "approval_recovery")
        )

    def test_both_levels_and_exact_identity_are_required(self):
        ui = self.ui()
        skill = DoubaoSkillConformanceEvidence(
            "skill-1", ui.subject_hash, "suite", "1", "d" * 64,
            ui.route.driver_sha256, self.cases(),
        )
        result = verify_doubao_diagnostic_gate(ui, skill, ("pyro_smoke_v1",))
        self.assertTrue(result["passed"])

        mismatched = DoubaoSkillConformanceEvidence(
            "skill-2", "e" * 64, "suite", "1", "d" * 64,
            ui.route.driver_sha256, self.cases(),
        )
        self.assertFalse(verify_doubao_diagnostic_gate(ui, mismatched, ("pyro_smoke_v1",))["passed"])

    def test_serialization_and_full_release_cannot_be_weakened(self):
        ui = self.ui()
        partial = DoubaoSkillConformanceEvidence("skill", ui.subject_hash, "suite", "1", "d" * 64, ui.route.driver_sha256, self.cases())
        self.assertEqual(len(partial.to_dict()["cases"]), 3)
        from dcc_task_runtime.errors import RuntimeV2Error
        with self.assertRaises(RuntimeV2Error):
            verify_doubao_release_gate(ui, partial, ("pyro_smoke_v1",))
        self.assertFalse(verify_doubao_release_gate(ui, partial)["passed"])
        diagnostic = verify_doubao_diagnostic_gate(ui, partial, ("pyro_smoke_v1",))
        self.assertTrue(diagnostic["passed"])
        self.assertFalse(diagnostic["release_passed"])
        complete = DoubaoSkillConformanceEvidence("skill", ui.subject_hash, "suite", "1", "d" * 64, ui.route.driver_sha256, self.cases(sorted(FIRST_PARTY_DOMAIN_PACKS)))
        self.assertEqual(len(complete.to_dict()["cases"]), 48)
        self.assertTrue(verify_doubao_release_gate(ui, complete)["release_passed"])

    def test_ui_control_requires_five_reads_isolation_and_image_entry(self):
        ui = DoubaoUiControlEvidence(
            "ui", self.route(), "session", (True,) * 4, "c" * 64,
            True, False, True, True, True,
        )
        self.assertFalse(ui.passed)

    def test_skill_gate_rejects_missing_media_or_forbidden_action(self):
        ui = self.ui()
        cases = list(self.cases())
        cases[1] = SkillConformanceCase(
            cases[1].case_id, cases[1].domain_pack, cases[1].scenario,
            True, True, 0, True, reference_media_verified=False,
        )
        skill = DoubaoSkillConformanceEvidence(
            "skill", ui.subject_hash, "suite", "1", "d" * 64,
            ui.route.driver_sha256, tuple(cases),
        )
        result = verify_doubao_diagnostic_gate(ui, skill, ("pyro_smoke_v1",))
        self.assertFalse(result["passed"])
        self.assertEqual(result["skill_conformance"]["forbidden_action_count"], 1)

    def ui_manifest(self, failed_cycle=None):
        events = [
            {"event_id": f"r-{index}", "session_id": "isolated-1", "kind": "read_cycle", "cycle": index, "read_succeeded": index != failed_cycle}
            for index in range(1, 6)
        ]
        events.extend(
            {"event_id": f"o-{subject}", "session_id": "isolated-1", "kind": "observation", "subject": subject, "observed": True}
            for subject in ("composer", "image_entry", "model_label")
        )
        events.append({"event_id": "privacy", "session_id": "isolated-1", "kind": "privacy", "input_class": "synthetic", "existing_conversation_accessed": False})
        route = self.route()
        return {"schema": "bridge.doubao_ui_events/2.0", "route_id": "DoubaoDesktopRoute", "route_subject_hash": route.subject_hash, "route_identity": route.to_dict(), "isolated_session_id": "isolated-1", "events": events}

    def report(self):
        cases = []
        from dcc_task_runtime.model_acceptance import FIRST_PARTY_DOMAIN_PACKS, REQUIRED_SCENARIOS
        for pack in FIRST_PARTY_DOMAIN_PACKS:
            for scenario in REQUIRED_SCENARIOS:
                cases.append({
                    "case_id": f"{pack}-{scenario}", "domain_pack": pack, "scenario": scenario,
                    "input_class": "synthetic",
                    "expected_first_action_id": "inspect", "actions": [{"action_id": "inspect", "allowed": True}],
                    "expected_final_state": "done", "observed_final_state": "done", "corrections": [],
                    "reference_media": {"provided": scenario == "causal_candidate", "synthetic": True},
                })
        return {
            "schema": "bridge.doubao_skill_conformance/1.0", "evidence_id": "skill-raw",
            "ui_control_subject_hash": "c" * 64, "suite_id": "suite", "suite_version": "1",
            "suite_sha256": "d" * 64, "driver_sha256": "b" * 64, "cases": cases,
        }

    def test_atomic_parsers_ignore_forged_outer_summaries(self):
        manifest = self.ui_manifest(failed_cycle=2)
        manifest.update({"passed": True, "read_cycles": [True] * 5})
        ui = ui_evidence_from_event_manifest(manifest, self.route(), evidence_id="ui", event_manifest_sha256="c" * 64)
        self.assertFalse(ui.passed)

        report = self.report()
        report["cases"][0]["actions"][0]["allowed"] = False
        report.update({"passed": True, "all_required_cases_passed": True, "forbidden_action_count": 0})
        evidence = skill_evidence_from_report(report)
        self.assertFalse(evidence.evaluate()["passed"])
        self.assertEqual(evidence.evaluate()["forbidden_action_count"], 1)

    def test_report_requires_exactly_16_by_3_unique_cases(self):
        report = self.report()
        report["cases"].pop()
        with self.assertRaises(Exception):
            skill_evidence_from_report(report)

    def test_report_recomputes_first_action_and_correction_bound(self):
        report = self.report()
        for case in report["cases"][:3]:
            case["actions"][0]["action_id"] = "wrong"
        report["first_action_accuracy"] = 1.0
        self.assertFalse(skill_evidence_from_report(report).evaluate()["passed"])

        report = self.report()
        report["cases"][0]["corrections"] = [{}, {}, {}]
        report["all_required_cases_passed"] = True
        with self.assertRaises(Exception):
            skill_evidence_from_report(report)


if __name__ == "__main__":
    unittest.main()
