"""Deterministic Houdini task recipes exposed through the local bridge."""

from __future__ import annotations

import math
from typing import Any, Mapping

from dcc_task_runtime import Step, TaskSpec
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.models import validate_frame_range
from dcc_task_runtime.visual_objective import SourcePlan

from .domain_packs import get_domain_pack, validate_candidate_patch


MAX_RENDER_OPERATION_FRAMES = 12


def _frame_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(name + " must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + " must be an integer") from exc
    if isinstance(value, float) and (not math.isfinite(value) or value != result):
        raise ValueError(name + " must be an integer")
    return result


def _frame_range_components(raw: Mapping[str, Any], name: str, *, max_count=None):
    """Count arithmetic before any materialization, including direct TaskSpecs."""
    if not isinstance(raw, Mapping):
        raise ValueError(name + " must be an object")
    start = _frame_integer(raw.get("start", 1), name + ".start")
    end = _frame_integer(raw.get("end", start), name + ".end")
    stride = _frame_integer(raw.get("step", 1), name + ".step")
    count = validate_frame_range(start, end, stride, name, max_count=max_count)
    return start, end, stride, count


class ModelToKarmaRecipe:
    identifier = "houdini.model_to_karma"

    def steps(self, spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        frame_range = spec.render.get("frame_range") or {}
        start, end, stride, _count = _frame_range_components(
            frame_range, "model recipe frame_range; long task histories require an explicitly segmented plan",
            max_count=MAX_RENDER_OPERATION_FRAMES,
        )
        frames = list(range(start, end + 1, stride))
        steps = [
            Step("probe", "PROBE", "agent.model.probe", 2),
            Step("build_model", "AUTHOR", "agent.model.build", 16),
            Step("validate_geometry", "TECH_VERIFY", "agent.model.validate_geometry", 8),
            Step("build_lookdev", "AUTHOR", "agent.model.lookdev", 10),
            Step("build_solaris", "AUTHOR", "agent.model.solaris", 12),
            Step("preview_render", "PREVIEW_RENDER", "agent.model.render_preview", 12, params={"frame": start, "kind": "preview"}),
            Step("verify_preview", "TECH_VERIFY", "agent.model.verify_preview", 8),
        ]
        steps.extend(
            Step(
                "final_render_{:04d}".format(frame),
                "FINAL_RENDER",
                "agent.model.render_final",
                24,
                params={"frame": frame, "kind": "final"},
            )
            for frame in frames
        )
        steps.extend([
            Step("verify_final", "ARTIFACT_VERIFY", "agent.model.verify_final", 6),
            Step("deliver", "DELIVER", "agent.model.deliver", 2),
        ])
        return steps


def _fx_configuration(spec: TaskSpec) -> dict[str, Any]:
    """Read additive v2 options from the v1-compatible constraints envelope."""
    constraints = spec.constraints if isinstance(spec.constraints, Mapping) else {}
    nested = constraints.get("fx") if isinstance(constraints.get("fx"), Mapping) else {}
    result = dict(nested)
    for name in (
        "domain_pack",
        "candidate_patch",
        "cache_requested",
        "cache_output",
        "cache_approval",
        "reference_analysis",
        "visual_objective",
        "source_plan",
        "source_controls",
        "source_plan_sha256",
        "perceptual_issue",
        "protected_attributes",
        "seed",
        "run_mode",
    ):
        if name in constraints and name not in result:
            result[name] = constraints[name]
    return result


def _fx_run_mode(spec: TaskSpec) -> str:
    mode = str(_fx_configuration(spec).get("run_mode") or "delivery").strip().lower()
    if mode not in {"diagnose", "candidate_preview", "delivery"}:
        raise ValueError("constraints.fx.run_mode must be diagnose, candidate_preview, or delivery")
    return mode


def _validated_cache_approval(value: Any) -> dict[str, Any]:
    """Require a signed assertion envelope before placing it on the wire.

    Houdini still verifies the signature against its exact scene-derived
    subject.  This shape gate prevents obsolete, caller-controlled ``trusted``
    booleans from entering an executable task plan.
    """
    if not isinstance(value, Mapping):
        raise ValueError("a signed cache approval assertion is required when cache_requested=true")
    required = ("purpose", "subject_hash", "grant_id", "expires_at", "signature")
    missing = [name for name in required if not str(value.get(name) or "").strip()]
    if missing:
        raise ValueError("cache approval assertion is missing: {}".format(", ".join(missing)))
    if value.get("purpose") != "houdini_simulation_cache":
        raise ValueError("cache approval purpose must be houdini_simulation_cache")
    return dict(value)


class ReferenceEffectRecipe:
    """A bounded Houdini portion of the cross-DCC reference rebuild flow.

    The recipe is intentionally linear at the DCC boundary.  Cross-component
    branching and causal candidate selection live in the shared pipeline
    runtime; each invocation applies at most one already-selected semantic
    patch to one domain pack.
    """

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier

    def steps(self, spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        fx = _fx_configuration(spec)
        pack_id = str(fx.get("domain_pack") or "").strip()
        if not pack_id:
            raise ValueError("constraints.fx.domain_pack is required")
        pack = get_domain_pack(pack_id)
        candidate = fx.get("candidate_patch") or {}
        if isinstance(candidate, Mapping) and isinstance(candidate.get("changes"), Mapping):
            candidate = candidate["changes"]
        normalized_patch = validate_candidate_patch(pack, candidate) if candidate else {}
        controls = {control.identifier: control for control in pack.controls}
        external = sorted(name for name in normalized_patch if controls[name].application != "houdini")
        if external:
            raise ValueError("candidate controls must be routed to their owning DCC: {}".format(", ".join(external)))
        frames = self._frames(spec)
        run_mode = _fx_run_mode(spec)
        if run_mode == "candidate_preview" and not normalized_patch:
            raise ValueError("candidate_preview run_mode requires a non-empty candidate_patch")
        common = {"domain_pack": pack.identifier, "pack_version": pack.version, "run_mode": run_mode}
        if "domain_control_plan" in fx:
            from dcc_task_runtime.domain_objective import DomainControlPlan
            domain_plan = DomainControlPlan.from_mapping(fx["domain_control_plan"]).require_ready()
            if domain_plan.domain_pack != pack.identifier or fx.get("domain_control_plan_sha256") != domain_plan.plan_sha256:
                raise ValueError("domain plan is not bound to the selected pack and content hash")
            common.update(domain_control_plan=domain_plan.to_dict(), domain_control_plan_sha256=domain_plan.plan_sha256)
        if "source_plan" in fx:
            plan = SourcePlan.from_mapping(fx.get("source_plan") or {}).require_ready()
            expected_controls = {item.name: item.value for item in plan.controls + plan.defaults}
            supplied_controls = fx.get("source_controls")
            supplied_hash = str(fx.get("source_plan_sha256") or "")
            if supplied_controls != expected_controls or supplied_hash != canonical_sha256(plan.to_dict()):
                raise ValueError("constraints.fx source plan binding does not match its bounded controls")
            source_inputs = [
                {
                    "asset_id": str(item.get("asset_id") or ""),
                    "role": str(item.get("role") or ""),
                    "sha256": str(item.get("sha256") or "").lower(),
                }
                for item in spec.inputs
                if isinstance(item, Mapping) and str(item.get("sha256") or "")
            ]
            common = {
                **common,
                # The host receives the typed plan itself, not only a derived
                # metadata dictionary, so it can independently re-validate
                # the digest, control vocabulary/ranges and source binding.
                "source_plan": plan.to_dict(),
                "source_plan_sha256": supplied_hash,
                "source_controls": expected_controls,
                "source_input_binding_sha256": canonical_sha256(source_inputs),
            }
        steps = [
            Step("fx_probe", "PROBE", "agent.fx.probe", 3, params=common, gate_policy="strict"),
            Step("fx_build_preview", "AUTHOR", "agent.fx.build_preview", 18, params={**common, "frames": frames}, gate_policy="strict"),
            Step("fx_collect_evidence", "TECH_VERIFY", "agent.fx.collect_evidence", 10, params={**common, "frames": frames}, gate_policy="strict"),
        ]
        if normalized_patch and run_mode in {"candidate_preview", "delivery"}:
            steps.append(
                Step(
                    "fx_apply_candidate",
                    "AUTHOR",
                    "agent.fx.apply_candidate",
                    8,
                    params={**common, "changes": normalized_patch},
                    gate_policy="strict",
                )
            )
        steps.append(Step("fx_verify", "TECH_VERIFY", "agent.fx.verify", 10, params={**common, "frames": frames}, gate_policy="strict"))
        if run_mode == "delivery" and pack.simulation_cache and bool(fx.get("cache_requested", False)):
            approval = _validated_cache_approval(fx.get("cache_approval"))
            steps.append(
                Step(
                    "fx_cache",
                    "FINAL_RENDER",
                    "agent.fx.cache",
                    24,
                    params={
                        **common,
                        "frames": frames,
                        "output": str(fx.get("cache_output") or ""),
                        "approval": approval,
                    },
                    gate_policy="strict",
                )
            )
        if run_mode == "delivery":
            steps.append(Step("fx_deliver", "DELIVER", "agent.fx.deliver", 2, params=common, gate_policy="strict"))
        return steps

    @staticmethod
    def _frames(spec: TaskSpec) -> list[int]:
        start, end, stride, _count = _frame_range_components(
            spec.render.get("frame_range") or {}, "task frame_range",
        )
        explicit = _fx_configuration(spec).get("frames")
        if explicit is not None:
            if not isinstance(explicit, (list, tuple)) or not 0 < len(explicit) <= MAX_RENDER_OPERATION_FRAMES:
                raise ValueError("reference operation requires at most 12 explicit frames")
            frames = [_frame_integer(value, "reference operation frame") for value in explicit]
            if frames != sorted(set(frames)) or any(frame < start or frame > end or (frame - start) % stride for frame in frames):
                raise ValueError("reference operation frames must be ordered unique members of the full task range and stride")
            return frames
        _frame_range_components(
            spec.render.get("frame_range") or {},
            "reference operation frame_range; long task histories require explicit constraints.fx.frames",
            max_count=MAX_RENDER_OPERATION_FRAMES,
        )
        return list(range(start, end + 1, stride))
