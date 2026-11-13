"""Generic feedback interpretation and evidence-gated causal repair."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .contracts import (
    CandidatePatch,
    CauseHypothesis,
    ChangeDirection,
    EvidenceBundle,
    EvidenceVerdict,
    IssueDimension,
    ParameterChange,
    PerceptualIssue,
    new_identifier,
)
from .domains import DiagnosticRule, DomainPack
from .errors import DiagnosisInconclusive, RuntimeV2Error
from .models import ErrorCode


class CausalDoctor:
    """Applies domain knowledge only after inspecting explicit evidence.

    The core knows nothing about smoke, water, particles, or cloth.  It consumes
    rules and public controls supplied by a validated ``DomainPack``.
    """

    def interpret_feedback(
        self,
        feedback: str,
        domain_pack: DomainPack,
        component_id: str,
        roi: Optional[tuple[float, float, float, float]] = None,
        frame_range: Optional[tuple[int, int, int]] = None,
        protected_attributes: Sequence[str] = (),
    ) -> PerceptualIssue:
        issues = self.interpret_feedback_all(feedback, domain_pack, component_id, roi, frame_range, protected_attributes)
        return issues[0]

    def interpret_feedback_all(
        self,
        feedback: str,
        domain_pack: DomainPack,
        component_id: str,
        roi: Optional[tuple[float, float, float, float]] = None,
        frame_range: Optional[tuple[int, int, int]] = None,
        protected_attributes: Sequence[str] = (),
    ) -> tuple[PerceptualIssue, ...]:
        text = str(feedback or "").strip()
        if not text:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "feedback must not be empty")
        folded = text.casefold()
        matches: list[tuple[int, Any]] = []
        for rule in domain_pack.feedback_rules:
            score = sum(1 for term in rule.terms if term.casefold() in folded)
            if score:
                matches.append((score, rule))
        if not matches:
            return (
                PerceptualIssue(
                    new_identifier("issue"),
                    text,
                    domain_pack.ref,
                    component_id,
                    IssueDimension.OTHER,
                    ChangeDirection.UNKNOWN,
                    0.5,
                    0.2,
                    roi,
                    frame_range,
                    tuple(protected_attributes),
                ),
            )
        issues: list[PerceptualIssue] = []
        seen: set[tuple[IssueDimension, ChangeDirection]] = set()
        for score, rule in sorted(matches, key=lambda item: item[0], reverse=True):
            signature = (rule.dimension, rule.direction)
            if signature in seen:
                continue
            seen.add(signature)
            issues.append(
                PerceptualIssue(
                    new_identifier("issue"),
                    text,
                    domain_pack.ref,
                    component_id,
                    rule.dimension,
                    rule.direction,
                    rule.severity,
                    min(0.95, 0.55 + 0.1 * score),
                    roi,
                    frame_range,
                    tuple(protected_attributes),
                )
            )
        return tuple(issues)

    def diagnose(
        self,
        issue: PerceptualIssue,
        evidence: EvidenceBundle,
        domain_pack: DomainPack,
    ) -> tuple[CauseHypothesis, ...]:
        self._validate_scope(issue, evidence, domain_pack)
        applicable = [rule for rule in domain_pack.diagnostic_rules if issue.dimension in rule.dimensions]
        if not applicable:
            raise DiagnosisInconclusive(
                "the selected domain pack has no diagnostic rule for this perceptual issue",
                "请补充更具体的问题描述或选择正确的效果组件。",
                {"dimension": issue.dimension.value, "domain": domain_pack.identifier},
            )
        by_signal: dict[str, set[EvidenceVerdict]] = {}
        for record in evidence.records:
            by_signal.setdefault(record.signal, set()).add(record.verdict)
        conflicts = sorted(signal for signal, verdicts in by_signal.items() if EvidenceVerdict.SUPPORTS in verdicts and EvidenceVerdict.REFUTES in verdicts)
        if conflicts:
            raise DiagnosisInconclusive(
                "diagnostic evidence conflicts for the same signal",
                "请在固定种子、相机和帧范围下重新生成冲突阶段的诊断输出。",
                {"signals": conflicts},
            )
        ranked: list[tuple[int, int, CauseHypothesis]] = []
        stage_order = {node.node_id: index for index, node in enumerate(domain_pack.stage_graph.nodes)}
        for rule in applicable:
            verdicts = [verdict for signal in rule.evidence_signals for verdict in by_signal.get(signal, ())]
            supports = sum(verdict is EvidenceVerdict.SUPPORTS for verdict in verdicts)
            refutes = sum(verdict is EvidenceVerdict.REFUTES for verdict in verdicts)
            if not supports:
                continue
            confidence = max(0.05, min(0.95, 0.45 + 0.18 * supports - 0.22 * refutes))
            hypothesis = CauseHypothesis(
                new_identifier("hypothesis"),
                issue.issue_id,
                rule.cause_family,
                rule.stage_node_id,
                rule.explanation,
                tuple(signal for signal in rule.evidence_signals if EvidenceVerdict.SUPPORTS in by_signal.get(signal, set())),
                rule.confounders,
                confidence,
                rule.estimated_cost,
            )
            ranked.append((supports - refutes, -stage_order.get(rule.stage_node_id, 999), hypothesis))
        if not ranked:
            next_rule = min(applicable, key=lambda rule: stage_order.get(rule.stage_node_id, 999))
            missing = sorted({signal for rule in applicable for signal in rule.evidence_signals if signal not in by_signal})
            raise DiagnosisInconclusive(
                "available evidence does not support a causal hypothesis",
                next_rule.next_question,
                {"missing_signals": missing, "refuted_signals": sorted(signal for signal, verdicts in by_signal.items() if EvidenceVerdict.REFUTES in verdicts)},
            )
        ranked.sort(key=lambda item: (item[0], item[1], item[2].confidence), reverse=True)
        return tuple(item[2] for item in ranked[:3])

    def propose_candidates(
        self,
        issue: PerceptualIssue,
        hypothesis: CauseHypothesis,
        evidence: EvidenceBundle,
        domain_pack: DomainPack,
        current_parameters: Mapping[str, Any],
    ) -> tuple[CandidatePatch, ...]:
        self._validate_scope(issue, evidence, domain_pack)
        if hypothesis.issue_id != issue.issue_id:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "hypothesis is linked to a different issue")
        rules = [
            rule
            for rule in domain_pack.diagnostic_rules
            if rule.cause_family == hypothesis.cause_family and rule.stage_node_id == hypothesis.stage_node_id and issue.dimension in rule.dimensions
        ]
        if len(rules) != 1:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "hypothesis does not resolve to exactly one diagnostic rule")
        rule = rules[0]
        levels = min(3, max(len(item.amounts) for item in rule.adjustments))
        candidates = []
        for level in range(levels):
            changes = []
            affected: set[str] = set()
            invalidates_simulation = False
            invalidated_components: set[str] = set()
            for adjustment in rule.adjustments[:5]:
                if adjustment.control not in current_parameters:
                    raise DiagnosisInconclusive(
                        "a required public control is missing from the current scene snapshot",
                        f"请读取公开控制量 {adjustment.control} 的当前值。",
                        {"control": adjustment.control},
                    )
                control = domain_pack.control_map[adjustment.control]
                previous = current_parameters[adjustment.control]
                amount = adjustment.amounts[min(level, len(adjustment.amounts) - 1)]
                proposed = self._adjust(previous, adjustment.operation, amount)
                if isinstance(proposed, (int, float)):
                    if control.minimum is not None:
                        proposed = max(control.minimum, proposed)
                    if control.maximum is not None:
                        proposed = min(control.maximum, proposed)
                    if control.value_type == "int":
                        proposed = int(round(proposed))
                proposed = control.validate(proposed)
                changes.append(ParameterChange(adjustment.control, previous, proposed))
                affected.update(control.invalidates_stage_nodes)
                invalidates_simulation = invalidates_simulation or control.requires_simulation_cache
                invalidated_components.update(control.invalidates_components)
            candidates.append(
                CandidatePatch(
                    new_identifier("candidate"),
                    issue.issue_id,
                    hypothesis.hypothesis_id,
                    hypothesis.cause_family,
                    tuple(changes),
                    tuple(sorted(affected)),
                    tuple(sorted(invalidated_components)) if invalidated_components else ((issue.component_id,) if invalidates_simulation else ()),
                    evidence.fixed_seed,
                    rule.estimated_cost,
                    ("low", "medium", "high")[min(level, 2)],
                )
            )
        return self.validate_candidates(tuple(candidates), issue, hypothesis, evidence, domain_pack)

    def validate_candidates(
        self,
        candidates: Sequence[CandidatePatch],
        issue: PerceptualIssue,
        hypothesis: CauseHypothesis,
        evidence: EvidenceBundle,
        domain_pack: DomainPack,
    ) -> tuple[CandidatePatch, ...]:
        if not 1 <= len(candidates) <= 3:
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "one issue may expose between one and three candidates")
        allowed_controls = domain_pack.control_map
        for candidate in candidates:
            if candidate.issue_id != issue.issue_id or candidate.hypothesis_id != hypothesis.hypothesis_id:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "candidate is not linked to the current issue and hypothesis")
            if candidate.cause_family != hypothesis.cause_family:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "a candidate may change only one diagnosed cause family")
            if candidate.fixed_seed != evidence.fixed_seed:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "candidate preview must preserve the diagnostic seed")
            for change in candidate.changes:
                control = allowed_controls.get(change.control)
                if control is None:
                    raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"candidate uses a non-public control: {change.control}")
                control.validate(change.proposed)
        return tuple(candidates)

    @staticmethod
    def _adjust(previous: Any, operation: str, amount: Any) -> Any:
        if operation == "set":
            return amount
        if isinstance(previous, bool) or not isinstance(previous, (int, float)):
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{operation} requires a numeric current value")
        if operation == "scale":
            return previous * amount
        if operation == "add":
            return previous + amount
        raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"unsupported candidate operation: {operation}")

    @staticmethod
    def _validate_scope(issue: PerceptualIssue, evidence: EvidenceBundle, domain_pack: DomainPack) -> None:
        if issue.domain != domain_pack.ref:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "issue domain/version does not match the selected domain pack")
        if evidence.issue_id != issue.issue_id:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "evidence is linked to a different issue")
