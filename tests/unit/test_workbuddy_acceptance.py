from __future__ import annotations

import hashlib
import plistlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from windows_filesystem_fixture import fixture_symlink

from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.workbuddy_acceptance import (
    HY3ProviderEvidence,
    IdentityLevel,
    MODEL_RUN_MANIFEST_SCHEMA,
    ModelRoundEvent,
    ModelRunManifest,
    REQUIRED_FIRST_ROUND_CORRECT,
    REQUIRED_SCENARIOS,
    WORKBUDDY_DOMAIN_PACKS,
    WorkBuddyAppIdentity,
    WorkBuddyHY3Route,
    evaluate_model_run,
    verify_workbuddy_diagnostic_gate,
)


def digest(char: str) -> str:
    return char * 64


class WorkBuddyAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        contents = Path(self._tmp.name) / "WorkBuddy.app" / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        self._plist = contents / "Info.plist"
        self._executable = contents / "MacOS" / "Electron"
        self._executable.write_bytes(b"workbuddy executable")
        self._plist.write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": "com.tencent.workbuddy.mac",
                    "CFBundleShortVersionString": "5.5.3",
                    "CFBundleExecutable": "Electron",
                }
            )
        )
        self._app = WorkBuddyAppIdentity.from_info_plist(self._plist)
        self._witness = Path(self._tmp.name) / "provider-witness.json"
        self._witness.write_bytes(b'{"exchange":"probe-1","model":"hy3"}\n')

    def app(self) -> WorkBuddyAppIdentity:
        return self._app

    def provider_evidence(self, *, session_id: str) -> HY3ProviderEvidence:
        return HY3ProviderEvidence(
            session_id=session_id,
            exchange_id="probe-1",
            model_name="hy3",
            endpoint="stdio://workbuddy",
            request_sha256=digest("c"),
            capability_probe_sha256=digest("d"),
            provider_response_sha256=digest("e"),
            witness_path=str(self._witness),
            witness_sha256=hashlib.sha256(self._witness.read_bytes()).hexdigest(),
            trusted_entry_id="front-door-entry-1",
            trusted_entry_sha256=digest("6"),
            observed_by="provider",
        )

    def trusted_provider_verifier(self, route: WorkBuddyHY3Route, manifest: ModelRunManifest) -> bool:
        evidence = route.provider_evidence
        return bool(
            evidence
            and evidence.witness_structurally_valid
            and route.app.files_structurally_valid
            and evidence.session_id == route.session_id == manifest.route.session_id
        )

    def trusted_route_verifier(self, route: WorkBuddyHY3Route, manifest: ModelRunManifest) -> bool:
        return bool(
            route.route_id == "WorkBuddyDesktopRoute"
            and route.selected_model.casefold() == "hy3"
            and route.session_id == manifest.route.session_id
            and route.app.files_structurally_valid
        )

    def route(self, *, provider_verified: bool = True, session_id: str = "workbuddy-session-1") -> WorkBuddyHY3Route:
        evidence = None
        level = IdentityLevel.APP_SELECTED
        if provider_verified:
            evidence = self.provider_evidence(session_id=session_id)
            level = IdentityLevel.PROVIDER_VERIFIED
        return WorkBuddyHY3Route(
            app=self.app(),
            session_id=session_id,
            selected_model="hy3",
            identity_level=level,
            provider_evidence=evidence,
        )

    def events(self, route: WorkBuddyHY3Route, *, wrong_first: set[int] | None = None) -> tuple[ModelRoundEvent, ...]:
        wrong_first = wrong_first or set()
        rows: list[ModelRoundEvent] = []
        cases = [(domain, scenario) for domain in sorted(WORKBUDDY_DOMAIN_PACKS) for scenario in sorted(REQUIRED_SCENARIOS)]
        for index, (domain, scenario) in enumerate(cases):
            case_id = f"case-{index:02d}"
            action_id = "wrong" if index in wrong_first else "inspect"
            rows.append(
                ModelRoundEvent(
                    event_id=f"turn-{index:02d}",
                    event_type="model_turn",
                    run_id="run-1",
                    session_id=route.session_id,
                    case_id=case_id,
                    domain_pack=domain,
                    scenario=scenario,
                    round_index=1,
                    observed_by="front_door",
                    model="hy3",
                    action_id=action_id,
                    expected_action_id="inspect",
                    action_allowed=True,
                    tool_call_id=f"tool-{index:02d}",
                    provider_response_sha256=digest("f"),
                    reference_hashes=(digest("1"),),
                    media_parts=("image_url",),
                )
            )
            rows.append(
                ModelRoundEvent(
                    event_id=f"complete-{index:02d}",
                    event_type="case_complete",
                    run_id="run-1",
                    session_id=route.session_id,
                    case_id=case_id,
                    domain_pack=domain,
                    scenario=scenario,
                    round_index=2,
                    observed_by="front_door",
                    expected_final_state="done",
                    observed_final_state="done",
                )
            )
        return tuple(rows)

    def manifest(self, *, route: WorkBuddyHY3Route | None = None, events: tuple[ModelRoundEvent, ...] | None = None, claims=None) -> ModelRunManifest:
        route = route or self.route()
        return ModelRunManifest(
            run_id="run-1",
            task_id="task-1",
            spec_hash=digest("0"),
            route=route,
            events=events or self.events(route),
            untrusted_claims=claims or {},
        )

    def test_info_plist_binds_declared_executable_without_inventing_backend_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "WorkBuddy.app" / "Contents"
            (root / "MacOS").mkdir(parents=True)
            plist = root / "Info.plist"
            executable = root / "MacOS" / "WorkBuddyMain"
            executable.write_bytes(b"workbuddy main")
            plist.write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleIdentifier": "com.tencent.workbuddy.mac",
                        "CFBundleShortVersionString": "5.5.3",
                        "CFBundleExecutable": "WorkBuddyMain",
                    }
                )
            )
            identity = WorkBuddyAppIdentity.from_info_plist(plist)
            self.assertEqual(identity.executable_name, "WorkBuddyMain")
            self.assertEqual(identity.app_version, "5.5.3")
            self.assertEqual(identity.executable_sha256, hashlib.sha256(b"workbuddy main").hexdigest())
            self.assertNotIn("backend_version", identity.to_dict())

    def test_info_plist_rejects_symlinked_or_escaping_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "WorkBuddy.app"
            contents = bundle / "Contents"
            (contents / "MacOS").mkdir(parents=True)
            plist = contents / "Info.plist"
            plist.write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleIdentifier": "com.tencent.workbuddy.mac",
                        "CFBundleVersion": "5.5.3",
                        "CFBundleExecutable": "WorkBuddyMain",
                    }
                )
            )
            outside = Path(directory) / "outside"
            outside.write_bytes(b"outside")
            with self.assertRaises(RuntimeV2Error):
                WorkBuddyAppIdentity.from_info_plist(plist, executable_path=outside)

            if fixture_symlink(self, contents / "MacOS" / "WorkBuddyMain", outside):
                with self.assertRaises(RuntimeV2Error):
                    WorkBuddyAppIdentity.from_info_plist(plist)

    def test_provider_verified_and_app_selected_are_distinct(self) -> None:
        app_selected = self.manifest(route=self.route(provider_verified=False))
        selected_result = evaluate_model_run(app_selected)
        self.assertEqual(selected_result["identity_level"], "APP_SELECTED")
        self.assertTrue(selected_result["case_conformance_passed"])
        self.assertFalse(selected_result["provider_verified"])
        self.assertFalse(selected_result["provider_claimed"])
        self.assertEqual(selected_result["provider_verification_status"], "UNVERIFIED")
        self.assertFalse(selected_result["route_acceptance_passed"])
        self.assertFalse(selected_result["release_passed"])

        selected_accepted = evaluate_model_run(
            app_selected,
            route_witness_verifier=self.trusted_route_verifier,
        )
        self.assertTrue(selected_accepted["route_acceptance_passed"])
        self.assertTrue(selected_accepted["passed"])
        self.assertFalse(selected_accepted["provider_verified"])
        self.assertFalse(selected_accepted["release_passed"])

        claimed_result = evaluate_model_run(self.manifest())
        self.assertEqual(claimed_result["identity_level"], "PROVIDER_VERIFIED")
        self.assertTrue(claimed_result["provider_claimed"])
        self.assertTrue(claimed_result["provider_witness_present"])
        self.assertFalse(claimed_result["provider_verified"])
        self.assertEqual(claimed_result["provider_verification_status"], "UNVERIFIED")
        self.assertFalse(claimed_result["release_passed"])

        verified_result = evaluate_model_run(
            self.manifest(),
            route_witness_verifier=self.trusted_route_verifier,
            provider_witness_verifier=self.trusted_provider_verifier,
        )
        self.assertEqual(verified_result["identity_level"], "PROVIDER_VERIFIED")
        self.assertTrue(verified_result["provider_verified"])
        self.assertEqual(verified_result["provider_verification_status"], "VERIFIED")
        self.assertTrue(verified_result["release_passed"])

    def test_48_cases_use_atomic_events_and_accept_46_first_rounds(self) -> None:
        result = evaluate_model_run(
            self.manifest(events=self.events(self.route(), wrong_first={0, 1})),
            route_witness_verifier=self.trusted_route_verifier,
            provider_witness_verifier=self.trusted_provider_verifier,
        )
        self.assertEqual(result["required_case_count"], 48)
        self.assertEqual(result["case_count"], 48)
        self.assertEqual(result["first_round_correct"], REQUIRED_FIRST_ROUND_CORRECT)
        self.assertTrue(result["all_final_completed"])
        self.assertTrue(result["case_conformance_passed"])
        self.assertTrue(result["passed"])

    def test_retry_correction_help_switch_and_forbidden_metrics_are_separate(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        base = rows[0]
        extras = [
            ModelRoundEvent(base.event_id + "-transport", "transport_retry", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 1, "front_door"),
            ModelRoundEvent(base.event_id + "-dcc", "dcc_retry", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 1, "dcc"),
            ModelRoundEvent(base.event_id + "-format", "format_correction", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 2, "front_door"),
            ModelRoundEvent(base.event_id + "-state", "state_correction", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 3, "front_door"),
            ModelRoundEvent(base.event_id + "-help", "human_semantic_help", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 4, "trusted_human"),
            ModelRoundEvent(base.event_id + "-switch", "model_switch", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 5, "workbuddy_runtime", from_model="hy3", to_model="other"),
            ModelRoundEvent(base.event_id + "-subagent", "subagent", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 6, "workbuddy_runtime", declared_subagent=False),
            ModelRoundEvent(base.event_id + "-forbidden", "forbidden_action", "run-1", route.session_id, base.case_id, base.domain_pack, base.scenario, 7, "front_door", action_id="code.exec_python"),
        ]
        result = evaluate_model_run(
            self.manifest(route=route, events=tuple(rows + extras)),
            route_witness_verifier=self.trusted_route_verifier,
            provider_witness_verifier=self.trusted_provider_verifier,
        )
        self.assertEqual(result["transport_retries"], 1)
        self.assertEqual(result["dcc_retries"], 1)
        self.assertEqual(result["format_corrections"], 1)
        self.assertEqual(result["state_corrections"], 1)
        self.assertEqual(result["human_semantic_help"], 1)
        self.assertEqual(result["model_switches"], 1)
        self.assertEqual(result["undeclared_subagents"], 1)
        self.assertEqual(result["forbidden_action_attempts"], 1)
        self.assertFalse(result["passed"])

    def test_model_self_reported_claims_do_not_control_evaluation(self) -> None:
        manifest = self.manifest(claims={"claimed_summary": {"passed": True, "case_count": 48, "verified": True}})
        payload = manifest.to_dict()
        reparsed = ModelRunManifest.from_mapping(payload)
        result = evaluate_model_run(
            reparsed,
            route_witness_verifier=self.trusted_route_verifier,
            provider_witness_verifier=self.trusted_provider_verifier,
        )
        self.assertTrue(result["passed"])
        with self.assertRaises(RuntimeV2Error):
            self.manifest(claims={"passed": True})

    def test_strict_schema_route_and_session_binding(self) -> None:
        payload = self.manifest().to_dict()
        self.assertEqual(payload["schema"], MODEL_RUN_MANIFEST_SCHEMA)
        payload["route"]["provider_evidence"]["backend_version"] = "claimed"
        with self.assertRaises(RuntimeV2Error):
            ModelRunManifest.from_mapping(payload)

        route = self.route()
        with self.assertRaises(RuntimeV2Error):
            WorkBuddyHY3Route(
                app=self.app(),
                session_id="route-session",
                identity_level=IdentityLevel.PROVIDER_VERIFIED,
                provider_evidence=self.provider_evidence(session_id="other-session"),
            )
        event = self.events(route)[0].to_dict()
        event["observed_by"] = "model"
        with self.assertRaises(RuntimeV2Error):
            ModelRoundEvent.from_mapping(event)

    def test_diagnostic_gate_never_promotes_release(self) -> None:
        result = verify_workbuddy_diagnostic_gate(self.manifest())
        self.assertTrue(result["case_conformance_passed"])
        self.assertFalse(result["provider_verified"])
        self.assertFalse(result["release_passed"])

    def test_provider_claim_without_witness_cannot_construct_verified_route(self) -> None:
        evidence = HY3ProviderEvidence(
            session_id="workbuddy-session-1",
            exchange_id="probe-1",
            model_name="hy3",
            endpoint="stdio://workbuddy",
            request_sha256=digest("c"),
            capability_probe_sha256=digest("d"),
            provider_response_sha256=digest("e"),
        )
        with self.assertRaises(RuntimeV2Error):
            WorkBuddyHY3Route(
                app=self.app(),
                session_id="workbuddy-session-1",
                identity_level=IdentityLevel.PROVIDER_VERIFIED,
                provider_evidence=evidence,
            )

    def test_app_selected_requires_receipt_and_reference_media(self) -> None:
        route = self.route(provider_verified=False)
        rows = list(self.events(route))
        target_index = next(
            index for index, event in enumerate(rows)
            if event.event_type == "model_turn" and event.scenario == "causal_candidate"
        )
        rows[target_index] = replace(
            rows[target_index],
            tool_call_id=None,
            provider_response_sha256=None,
            reference_hashes=(),
            media_parts=(),
        )
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        self.assertGreaterEqual(result["missing_tool_evidence"], 1)
        self.assertGreaterEqual(result["missing_reference_media"], 1)
        self.assertFalse(result["case_conformance_passed"])

    def test_task_b3_transport_retry_does_not_duplicate_model_decision(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        original = replace(rows[index], decision_id="decision-stable-1", graph_id="graph_trace_1", proposal_id="proposal-1")
        rows[index] = original
        rows.append(replace(original, event_id="transport-replayed-turn", round_index=2))
        rows.append(ModelRoundEvent(
            event_id="transport-retry-event", event_type="transport_retry", run_id="run-1",
            session_id=route.session_id, case_id=original.case_id, domain_pack=original.domain_pack,
            scenario=original.scenario, round_index=2, observed_by="front_door",
        ))
        result = evaluate_model_run(
            self.manifest(route=route, events=tuple(rows)),
            route_witness_verifier=self.trusted_route_verifier,
            provider_witness_verifier=self.trusted_provider_verifier,
        )
        case = next(item for item in result["cases"] if item["case_id"] == original.case_id)
        self.assertEqual(case["model_decisions"], 1)
        self.assertEqual(case["transport_retries"], 1)
        self.assertIn("graph_trace_1", case["trace"]["graph_ids"])

    def test_task_b3_decision_ids_are_scoped_to_cold_start_attempts(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        first = replace(rows[index], decision_id="decision-reused", tool_call_id="tool-reused")
        rows[index] = first
        rows.append(ModelRoundEvent(
            event_id="cold-start-scope", event_type="cold_start_retry", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=1, attempt_index=2, observed_by="front_door",
        ))
        rows.append(replace(
            first, event_id="cold-turn-scope", attempt_index=2, round_index=1,
            decision_id="decision-reused", tool_call_id="tool-reused",
        ))
        rows.append(ModelRoundEvent(
            event_id="cold-complete-scope", event_type="case_complete", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=2, attempt_index=2, observed_by="front_door",
            expected_final_state="done", observed_final_state="done",
        ))
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        case = next(item for item in result["cases"] if item["case_id"] == first.case_id)
        self.assertEqual(case["model_decisions"], 2)
        self.assertEqual(case["attempt_history"][0]["model_decisions"], 1)
        self.assertEqual(case["attempt_history"][1]["model_decisions"], 1)
        self.assertTrue(case["attempt_history"][1]["passed"])

    def test_task_b3_latest_valid_retest_is_independently_visible_while_failed_history_remains(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        first = replace(rows[index], action_allowed=False, action_id="blocked-first", decision_id="decision-failed")
        rows[index] = first
        rows.append(ModelRoundEvent(
            event_id="cold-start-valid-retest", event_type="cold_start_retry", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=1, attempt_index=2, observed_by="front_door",
        ))
        rows.append(replace(
            first, event_id="cold-turn-valid-retest", attempt_index=2, round_index=1,
            action_allowed=True, action_id=first.expected_action_id, decision_id="decision-valid", tool_call_id="tool-valid",
        ))
        rows.append(ModelRoundEvent(
            event_id="cold-complete-valid-retest", event_type="case_complete", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=2, attempt_index=2, observed_by="front_door",
            expected_final_state="done", observed_final_state="done",
        ))
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        case = next(item for item in result["cases"] if item["case_id"] == first.case_id)
        self.assertFalse(case["rule_compliant"])
        self.assertFalse(case["attempt_history"][0]["passed"])
        self.assertTrue(case["attempt_history"][1]["passed"])
        self.assertFalse(case["passed"])

    def test_task_b3_later_reconciliation_resolves_unknown_without_erasing_history(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        first = replace(rows[index], decision_id="decision-unknown", operation_id="op-unknown")
        rows[index] = first
        rows.append(ModelRoundEvent(
            event_id="unknown-history", event_type="unknown_result", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=3, attempt_index=1, observed_by="dcc",
            operation_id="op-unknown", error_code="HOST_OUTCOME_UNKNOWN",
        ))
        rows.append(ModelRoundEvent(
            event_id="cold-start-reconcile", event_type="cold_start_retry", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=1, attempt_index=2, observed_by="front_door",
        ))
        rows.append(ModelRoundEvent(
            event_id="reconcile-resolved", event_type="reconciliation_resolved", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=1, attempt_index=2, observed_by="dcc",
            operation_id="op-unknown",
        ))
        rows.append(replace(
            first, event_id="cold-turn-reconcile", attempt_index=2, round_index=1,
            decision_id="decision-retest", tool_call_id="tool-retest", operation_id="op-retest",
        ))
        rows.append(ModelRoundEvent(
            event_id="cold-complete-reconcile", event_type="case_complete", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack,
            scenario=first.scenario, round_index=2, attempt_index=2, observed_by="front_door",
            expected_final_state="done", observed_final_state="done",
        ))
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        case = next(item for item in result["cases"] if item["case_id"] == first.case_id)
        self.assertEqual(case["unknown_results"], 0)
        self.assertEqual(case["attempt_history"][0]["historical_unknown_results"], 1)
        self.assertEqual(case["attempt_history"][0]["unknown_results"], 0)
        self.assertTrue(case["attempt_history"][1]["passed"])
        self.assertIn("HOST_OUTCOME_UNKNOWN", {item["code"] for item in case["structured_errors"]})

    def test_task_b3_transport_replay_cannot_duplicate_a_model_round_index(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        first = next(event for event in rows if event.event_type == "model_turn")
        rows.append(replace(first, event_id="same-round-transport-replay", decision_id="same-decision"))
        with self.assertRaises(RuntimeV2Error):
            self.manifest(route=route, events=tuple(rows))

    def test_task_b3_blocked_action_is_rule_failure_even_if_case_completes(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        rows[index] = replace(rows[index], action_allowed=False, action_id="blocked_action")
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        case = next(item for item in result["cases"] if item["case_id"] == rows[index].case_id)
        self.assertFalse(case["rule_compliant"])
        self.assertGreaterEqual(case["forbidden_action_attempts"], 1)
        self.assertFalse(result["case_conformance_passed"])

    def test_task_b3_unknown_trace_and_cold_start_history_are_preserved(self) -> None:
        route = self.route()
        rows = list(self.events(route))
        turn_index = next(i for i, event in enumerate(rows) if event.event_type == "model_turn")
        first = replace(
            rows[turn_index], decision_id="decision-first", graph_id="graph_trace_2",
            operation_id="op_trace_2", artifact_ids=("artifact_owned_1",), proposal_id="proposal-model-1",
        )
        rows[turn_index] = first
        rows.append(ModelRoundEvent(
            event_id="unknown-result-1", event_type="unknown_result", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack, scenario=first.scenario,
            round_index=3, observed_by="dcc", operation_id="op_trace_2", error_code="HOST_OUTCOME_UNKNOWN",
            graph_id="graph_trace_2", artifact_ids=("artifact_owned_1",),
        ))
        rows.append(ModelRoundEvent(
            event_id="human-auth-1", event_type="human_authorization", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack, scenario=first.scenario,
            round_index=3, observed_by="trusted_human", authorization_id="authorization-human-1",
        ))
        # A later cold-start attempt is retained as attempt 2; it cannot erase
        # the unknown result from attempt 1 or turn human authorization into a
        # model proposal.
        rows.append(ModelRoundEvent(
            event_id="cold-start-1", event_type="cold_start_retry", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack, scenario=first.scenario,
            round_index=1, attempt_index=2, observed_by="front_door",
        ))
        rows.append(replace(
            first, event_id="cold-turn-2", round_index=1, attempt_index=2, decision_id="decision-second",
            proposal_id="proposal-model-2", operation_id="op_trace_3",
        ))
        rows.append(ModelRoundEvent(
            event_id="cold-complete-2", event_type="case_complete", run_id="run-1",
            session_id=route.session_id, case_id=first.case_id, domain_pack=first.domain_pack, scenario=first.scenario,
            round_index=2, attempt_index=2, observed_by="front_door", expected_final_state="done", observed_final_state="done",
        ))
        result = evaluate_model_run(self.manifest(route=route, events=tuple(rows)))
        case = next(item for item in result["cases"] if item["case_id"] == first.case_id)
        self.assertEqual(case["attempt_count"], 2)
        self.assertEqual(case["cold_start_retries"], 1)
        self.assertEqual(case["unknown_results"], 1)
        self.assertEqual(len(case["attempt_history"]), 2)
        self.assertIn("HOST_OUTCOME_UNKNOWN", {item["code"] for item in case["structured_errors"]})
        self.assertIn("authorization-human-1", case["human_authorization_ids"])
        self.assertIn("proposal-model-1", case["model_proposal_ids"])
        self.assertNotIn("authorization-human-1", case["model_proposal_ids"])
        self.assertIn("artifact_owned_1", result["trace"]["artifact_ids"])
        self.assertFalse(case["passed"])



if __name__ == "__main__":
    unittest.main()
