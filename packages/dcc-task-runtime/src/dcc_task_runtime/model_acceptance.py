"""Fail-closed acceptance contracts for the Doubao desktop release route."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode, now_iso


DOUBAO_ROUTE_ID = "DoubaoDesktopRoute"
FIRST_PARTY_DOMAIN_PACKS = frozenset(
    {
        "pyro_smoke_v1", "pyro_fire_v1", "particles_v1", "water_ocean_v1",
        "water_flip_v1", "crowd_agents_v1", "swarm_flocking_v1",
        "vellum_cloth_v1", "vellum_softbody_grains_v1", "hair_fur_v1",
        "rbd_destruction_v1", "procedural_geometry_v1", "material_lookdev_v1",
        "lighting_camera_render_v1", "nuke_composite_v1", "explosion_composite_v1",
    }
)
REQUIRED_SCENARIOS = frozenset({"build_inspect", "causal_candidate", "approval_recovery"})
UI_EVENT_SCHEMA = "bridge.doubao_ui_events/2.0"
CONFORMANCE_REPORT_SCHEMA = "bridge.doubao_skill_conformance/1.0"


def _sha256(value: str, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, f"{name} must be a SHA-256 digest")
    return text


class AcceptanceLevel(str, Enum):
    UI_CONTROL = "DOUBAO_UI_CONTROLLED"
    SKILL_CONFORMANCE = "DOUBAO_SKILL_CONFORMANT"


@dataclass(frozen=True)
class ModelRouteIdentity:
    route_id: str
    bundle_id: str
    app_version: str
    executable_path: str
    executable_sha256: str
    code_signature: str
    driver_sha256: str
    observed_model_label: str = ""
    model_revision_verified: bool = False

    def __post_init__(self) -> None:
        if self.route_id != DOUBAO_ROUTE_ID:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unexpected model route")
        if self.bundle_id != "com.bot.pc.doubao":
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unexpected Doubao bundle id")
        if not self.app_version or not self.code_signature:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao application identity is incomplete")
        path = Path(self.executable_path)
        if not path.is_absolute() or path.name != "Doubao":
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao executable path must be absolute and exact")
        _sha256(self.executable_sha256, "executable_sha256")
        _sha256(self.driver_sha256, "driver_sha256")

    @property
    def subject_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "route_kind": "desktop_ui",
            "bundle_id": self.bundle_id,
            "app_version": self.app_version,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "code_signature": self.code_signature,
            "driver_sha256": self.driver_sha256,
            "observed_model_label": self.observed_model_label,
            "model_revision_verified": self.model_revision_verified,
            "claimable_identity": self.observed_model_label if self.model_revision_verified else DOUBAO_ROUTE_ID,
        }


@dataclass(frozen=True)
class DoubaoUiControlEvidence:
    evidence_id: str
    route: ModelRouteIdentity
    isolated_session_id: str
    read_cycles: tuple[bool, ...]
    event_manifest_sha256: str
    synthetic_inputs_only: bool
    existing_conversations_touched: bool
    composer_verified: bool
    image_entry_verified: bool
    model_label_observed: bool
    created_at: str = field(default_factory=now_iso)

    @property
    def passed(self) -> bool:
        return (
            bool(self.evidence_id and self.isolated_session_id)
            and len(self.read_cycles) >= 5
            and all(value is True for value in self.read_cycles)
            and self.synthetic_inputs_only is True
            and self.existing_conversations_touched is False
            and self.composer_verified is True
            and self.image_entry_verified is True
            and self.model_label_observed is True
        )

    @property
    def subject_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "level": AcceptanceLevel.UI_CONTROL.value,
            "route": self.route.to_dict(),
            "route_subject_hash": self.route.subject_hash,
            "isolated_session_id": self.isolated_session_id,
            "read_cycles": list(self.read_cycles),
            "event_manifest_sha256": _sha256(self.event_manifest_sha256, "event_manifest_sha256"),
            "synthetic_inputs_only": self.synthetic_inputs_only,
            "existing_conversations_touched": self.existing_conversations_touched,
            "composer_verified": self.composer_verified,
            "image_entry_verified": self.image_entry_verified,
            "model_label_observed": self.model_label_observed,
            "passed": self.passed,
            "created_at": self.created_at,
        }


def ui_evidence_from_event_manifest(
    payload: Mapping[str, Any],
    route: ModelRouteIdentity,
    *,
    evidence_id: str,
    event_manifest_sha256: str,
) -> DoubaoUiControlEvidence:
    """Derive UI evidence from atomic observations, never summary booleans."""

    if payload.get("schema") != UI_EVENT_SCHEMA or payload.get("route_id") != DOUBAO_ROUTE_ID:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unknown Doubao UI event manifest")
    if payload.get("route_subject_hash") != route.subject_hash:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "UI events are not bound to the exact route identity")
    route_identity = payload.get("route_identity")
    expected_identity = route.to_dict()
    if not isinstance(route_identity, dict) or any(
        str(route_identity.get(field) or "") != str(expected_identity.get(field) or "")
        for field in ("route_id", "bundle_id", "app_version", "executable_path", "executable_sha256", "driver_sha256")
    ):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "UI route identity fields mismatch")
    session_id = str(payload.get("isolated_session_id") or "").strip()
    events = payload.get("events")
    if not session_id or not isinstance(events, list) or not events:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "UI manifest requires a session and events")
    ids: set[str] = set()
    read_cycles: dict[int, bool] = {}
    observations: dict[str, bool] = {}
    synthetic_only = True
    existing_touched = False
    for raw in events:
        if not isinstance(raw, dict):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "UI event must be an object")
        event_id = str(raw.get("event_id") or "").strip()
        if not event_id or event_id in ids or raw.get("session_id") != session_id:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "UI event identity/session mismatch")
        ids.add(event_id)
        kind = raw.get("kind")
        if kind == "read_cycle":
            cycle = raw.get("cycle")
            if type(cycle) is not int or cycle < 1 or cycle > 5 or cycle in read_cycles:
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "read cycles must be unique 1..5")
            read_cycles[cycle] = raw.get("read_succeeded") is True
        elif kind == "observation":
            subject = raw.get("subject")
            if subject not in {"composer", "image_entry", "model_label"} or subject in observations:
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "invalid or duplicate UI observation")
            observations[str(subject)] = raw.get("observed") is True
        elif kind == "privacy":
            if raw.get("input_class") != "synthetic":
                synthetic_only = False
            if raw.get("existing_conversation_accessed") is not False:
                existing_touched = True
        else:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unknown UI event kind")
    if set(read_cycles) != set(range(1, 6)):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "exactly five read cycles are required")
    if not any(raw.get("kind") == "privacy" for raw in events if isinstance(raw, dict)):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "privacy event is required")
    return DoubaoUiControlEvidence(
        evidence_id=evidence_id,
        route=route,
        isolated_session_id=session_id,
        read_cycles=tuple(read_cycles[index] for index in range(1, 6)),
        event_manifest_sha256=event_manifest_sha256,
        synthetic_inputs_only=synthetic_only,
        existing_conversations_touched=existing_touched,
        composer_verified=observations.get("composer", False),
        image_entry_verified=observations.get("image_entry", False),
        model_label_observed=observations.get("model_label", False),
    )


@dataclass(frozen=True)
class SkillConformanceCase:
    case_id: str
    domain_pack: str
    scenario: str
    first_action_correct: bool
    completed: bool
    correction_turns: int
    forbidden_action_attempted: bool
    reference_media_verified: bool = False

    def __post_init__(self) -> None:
        if self.domain_pack not in FIRST_PARTY_DOMAIN_PACKS:
            raise RuntimeV2Error(ErrorCode.UNSUPPORTED_DOMAIN, "unknown conformance domain pack")
        if self.scenario not in REQUIRED_SCENARIOS:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "unknown conformance scenario")
        if self.correction_turns < 0 or self.correction_turns > 2:
            raise RuntimeV2Error(ErrorCode.REPAIR_EXHAUSTED, "conformance correction turns exceed the bounded limit")
        if any(type(value) is not bool for value in (
            self.first_action_correct, self.completed,
            self.forbidden_action_attempted, self.reference_media_verified,
        )):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "conformance outcomes must be booleans")

    @property
    def passed(self) -> bool:
        return self.completed is True and self.forbidden_action_attempted is False and self.correction_turns <= 2

    def to_dict(self) -> dict[str, Any]:
        return json_value(self.__dict__)


@dataclass(frozen=True)
class DoubaoSkillConformanceEvidence:
    evidence_id: str
    ui_control_subject_hash: str
    suite_id: str
    suite_version: str
    suite_sha256: str
    driver_sha256: str
    cases: tuple[SkillConformanceCase, ...]
    created_at: str = field(default_factory=now_iso)

    def evaluate(self, required_packs: Sequence[str] = tuple(sorted(FIRST_PARTY_DOMAIN_PACKS))) -> dict[str, Any]:
        required = set(required_packs)
        case_keys = {(case.domain_pack, case.scenario) for case in self.cases}
        missing = sorted(
            f"{pack}:{scenario}"
            for pack in required
            for scenario in REQUIRED_SCENARIOS
            if (pack, scenario) not in case_keys
        )
        relevant = [case for case in self.cases if case.domain_pack in required]
        first_action_rate = (
            sum(case.first_action_correct is True for case in relevant) / len(relevant)
            if relevant else 0.0
        )
        media_missing = sorted(
            pack for pack in required
            if not any(
                case.domain_pack == pack
                and case.scenario == "causal_candidate"
                and case.reference_media_verified is True
                for case in relevant
            )
        )
        passed = (
            not missing
            and len(relevant) == len(required) * len(REQUIRED_SCENARIOS)
            and len(case_keys) == len(self.cases)
            and not media_missing
            and all(case.passed for case in relevant)
            and first_action_rate >= 0.95
            and bool(relevant)
        )
        return {
            "passed": passed,
            "missing_cases": missing,
            "missing_reference_media": media_missing,
            "first_action_accuracy": first_action_rate,
            "case_count": len(relevant),
            "forbidden_action_count": sum(case.forbidden_action_attempted is True for case in relevant),
        }


    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "level": AcceptanceLevel.SKILL_CONFORMANCE.value,
            "ui_control_subject_hash": _sha256(self.ui_control_subject_hash, "ui_control_subject_hash"),
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "suite_sha256": _sha256(self.suite_sha256, "suite_sha256"),
            "driver_sha256": _sha256(self.driver_sha256, "driver_sha256"),
            "cases": [case.to_dict() for case in self.cases],
            "created_at": self.created_at,
        }


def skill_evidence_from_report(payload: Mapping[str, Any]) -> DoubaoSkillConformanceEvidence:
    """Parse atomic case traces and recompute every conformance outcome."""

    if payload.get("schema") != CONFORMANCE_REPORT_SCHEMA:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unknown conformance report schema")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "conformance report cases must be a list")
    cases: list[SkillConformanceCase] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "conformance case must be an object")
        case_id = str(raw.get("case_id") or "").strip()
        pack = str(raw.get("domain_pack") or "")
        scenario = str(raw.get("scenario") or "")
        key = (pack, scenario)
        if not case_id or case_id in seen_ids or key in seen_keys:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "duplicate conformance case")
        seen_ids.add(case_id)
        seen_keys.add(key)
        actions = raw.get("actions")
        corrections = raw.get("corrections")
        media = raw.get("reference_media")
        if not isinstance(actions, list) or not actions or not all(isinstance(action, dict) for action in actions):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "case requires an action trace")
        if not isinstance(corrections, list):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "case corrections must be a list")
        if raw.get("input_class") != "synthetic":
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "conformance input must be synthetic")
        if len(corrections) > 2:
            raise RuntimeV2Error(ErrorCode.REPAIR_EXHAUSTED, "conformance correction turns exceed the bounded limit")
        expected_action = str(raw.get("expected_first_action_id") or "")
        expected_state = str(raw.get("expected_final_state") or "")
        observed_state = str(raw.get("observed_final_state") or "")
        cases.append(SkillConformanceCase(
            case_id=case_id,
            domain_pack=pack,
            scenario=scenario,
            first_action_correct=bool(expected_action and str(actions[0].get("action_id") or "") == expected_action),
            completed=bool(expected_state and observed_state == expected_state),
            correction_turns=len(corrections),
            forbidden_action_attempted=any(action.get("allowed") is not True for action in actions),
            reference_media_verified=(
                isinstance(media, dict)
                and media.get("provided") is True
                and media.get("synthetic") is True
            ),
        ))
    evidence = DoubaoSkillConformanceEvidence(
        evidence_id=str(payload.get("evidence_id") or ""),
        ui_control_subject_hash=str(payload.get("ui_control_subject_hash") or ""),
        suite_id=str(payload.get("suite_id") or ""),
        suite_version=str(payload.get("suite_version") or ""),
        suite_sha256=str(payload.get("suite_sha256") or ""),
        driver_sha256=str(payload.get("driver_sha256") or ""),
        cases=tuple(cases),
        created_at=str(payload.get("created_at") or now_iso()),
    )
    expected_keys = {(pack, scenario) for pack in FIRST_PARTY_DOMAIN_PACKS for scenario in REQUIRED_SCENARIOS}
    if seen_keys != expected_keys:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "report must contain exactly 16 domains x 3 scenarios")
    return evidence



def verify_doubao_diagnostic_gate(
    ui_evidence: DoubaoUiControlEvidence,
    skill_evidence: DoubaoSkillConformanceEvidence,
    required_packs: Sequence[str],
) -> Mapping[str, Any]:
    """Evaluate an explicit domain subset; never attest a complete release."""
    required = tuple(required_packs)
    if not required or len(set(required)) != len(required) or not set(required).issubset(FIRST_PARTY_DOMAIN_PACKS):
        raise RuntimeV2Error(ErrorCode.UNSUPPORTED_DOMAIN, "diagnostic gate requires a nonempty unique known domain set")
    # Validate content identities even when evidence was constructed directly.
    skill_evidence.to_dict()
    metadata_complete = all(str(value).strip() for value in (
        skill_evidence.evidence_id, skill_evidence.suite_id, skill_evidence.suite_version,
    ))
    ui_passed = ui_evidence.passed
    identity_matches = skill_evidence.ui_control_subject_hash == ui_evidence.subject_hash
    driver_matches = skill_evidence.driver_sha256 == ui_evidence.route.driver_sha256
    conformance = skill_evidence.evaluate(required)
    return {
        "route_id": DOUBAO_ROUTE_ID, "scope": "domain_diagnostic", "release_passed": False,
        "required_packs": sorted(required),
        "ui_control": ui_passed, "identity_matches": identity_matches,
        "driver_matches": driver_matches, "metadata_complete": metadata_complete,
        "skill_conformance": conformance,
        "passed": ui_passed and identity_matches and driver_matches and metadata_complete and conformance["passed"],
    }


def verify_doubao_release_gate(
    ui_evidence: DoubaoUiControlEvidence,
    skill_evidence: DoubaoSkillConformanceEvidence,
    required_packs: Sequence[str] = tuple(sorted(FIRST_PARTY_DOMAIN_PACKS)),
) -> Mapping[str, Any]:
    """Whole-release acceptance cannot be weakened by caller-selected packs."""
    required = tuple(required_packs)
    if len(required) != len(FIRST_PARTY_DOMAIN_PACKS) or set(required) != FIRST_PARTY_DOMAIN_PACKS:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "release gate requires all 16 domains; use diagnostic gate for subsets")
    result = dict(verify_doubao_diagnostic_gate(ui_evidence, skill_evidence, required))
    result.update({"scope": "full_release", "release_passed": result["passed"]})
    return result
