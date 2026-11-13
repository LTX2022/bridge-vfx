"""Deterministic, structured Nuke recipes.

``nuke.render_delivery`` remains the stable v1 recipe.  The reference
composite recipe is deliberately made from high-level bridge actions: no
model-provided Python is evaluated inside Nuke.
"""

from __future__ import annotations

from typing import Any, Mapping

from dcc_task_runtime import Step, TaskSpec
from dcc_task_runtime.models import validate_frame_range


COMPOSITE_INPUT_ROLES = frozenset(
    {"effect_render", "plate", "reference", "matte", "depth", "vector"}
)
REQUIRED_COMPOSITE_INPUT_ROLES = frozenset({"effect_render"})


def _planned_frames(spec: TaskSpec) -> tuple[int, int, range]:
    """Return a lazy, bounded frame sequence for parsed or hand-built specs."""

    frame_range = spec.render.get("frame_range") or {}
    if not isinstance(frame_range, Mapping):
        raise ValueError("render.frame_range must be an object")
    start = int(frame_range.get("start", 1))
    end = int(frame_range.get("end", start))
    stride = int(frame_range.get("step", 1))
    validate_frame_range(start, end, stride, "render.frame_range")
    return start, stride, range(start, end + 1, stride)


def _composite_run_mode(spec: TaskSpec) -> str:
    mode = str(spec.constraints.get("run_mode") or "delivery").strip().lower()
    if mode not in {"diagnose", "candidate_preview", "delivery"}:
        raise ValueError("constraints.run_mode must be diagnose, candidate_preview, or delivery")
    return mode


def _composite_candidate_patch(spec: TaskSpec) -> dict[str, Any]:
    raw = spec.constraints.get("composite_candidate_patch")
    if raw is None:
        raw = spec.constraints.get("candidate_patch")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("composite candidate patch must be an object")
    controls = raw.get("controls") if isinstance(raw.get("controls"), Mapping) else raw
    patch = {str(name): value for name, value in controls.items()}
    if len(patch) > 5:
        raise ValueError("a composite candidate may change at most five semantic controls")
    return patch


def composite_inputs(spec: TaskSpec) -> dict[str, dict[str, Any]]:
    """Validate and index the explicit inputs for the composite recipe."""

    indexed: dict[str, dict[str, Any]] = {}
    for item in spec.inputs:
        role = str(item.get("role") or "").strip().lower()
        if role not in COMPOSITE_INPUT_ROLES:
            raise ValueError(
                "nuke.reference_composite inputs require one of these roles: "
                + ", ".join(sorted(COMPOSITE_INPUT_ROLES))
            )
        if role in indexed:
            raise ValueError(f"nuke.reference_composite accepts at most one {role} input")
        path = str(item.get("path") or "").strip()
        if not path:
            raise ValueError(f"nuke.reference_composite input role {role} requires path")
        indexed[role] = dict(item)
    missing = sorted(REQUIRED_COMPOSITE_INPUT_ROLES.difference(indexed))
    if missing:
        raise ValueError("nuke.reference_composite is missing required input role(s): " + ", ".join(missing))
    return indexed


class RenderDeliveryRecipe:
    identifier = "nuke.render_delivery"

    def steps(self, spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        start, _stride, frames = _planned_frames(spec)
        steps = [
            Step("probe", "PROBE", "agent.nuke.probe", 2),
            Step("inspect_input", "INSPECT", "agent.nuke.inspect_input", 8),
            Step("build_graph", "AUTHOR", "agent.nuke.build_graph", 18),
            Step("preview_render", "PREVIEW_RENDER", "agent.nuke.render_preview", 12, params={"frame": start, "kind": "preview"}),
            Step("verify_preview", "TECH_VERIFY", "agent.nuke.verify_preview", 8),
        ]
        steps.extend(
            Step(
                "final_render_{:04d}".format(frame),
                "FINAL_RENDER",
                "agent.nuke.render_final",
                38,
                params={"frame": frame, "kind": "final"},
            )
            for frame in frames
        )
        steps.extend([
            Step("verify_final", "ARTIFACT_VERIFY", "agent.nuke.verify_final", 12),
            Step("deliver", "DELIVER", "agent.nuke.deliver", 2),
        ])
        return steps


class ReferenceCompositeRecipe:
    """Build and render an editable, reference-isolated native Nuke graph."""

    identifier = "nuke.reference_composite"
    domain_pack = "nuke_composite_v1"

    def steps(self, spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        inputs = composite_inputs(spec)
        run_mode = _composite_run_mode(spec)
        candidate_patch = _composite_candidate_patch(spec)
        if run_mode == "candidate_preview" and not candidate_patch:
            raise ValueError("candidate_preview run_mode requires a non-empty composite candidate patch")
        start, stride, frames = _planned_frames(spec)
        common = {
            "domain_pack": self.domain_pack,
            "expected_frame_stride": stride,
            "input_roles": sorted(inputs),
            "run_mode": run_mode,
        }
        steps = [
            Step("composite_probe", "PROBE", "agent.nuke.composite.probe", 2, params=common, gate_policy="strict"),
            Step("inspect_composite_inputs", "INSPECT", "agent.nuke.composite.inspect_inputs", 8, params=common, gate_policy="strict"),
            Step("build_composite_graph", "AUTHOR", "agent.nuke.composite.build_graph", 18, params=common, gate_policy="strict"),
        ]
        if candidate_patch and run_mode in {"candidate_preview", "delivery"}:
            steps.append(
                Step(
                    "apply_composite_candidate",
                    "AUTHOR",
                    "agent.nuke.composite.apply_patch",
                    8,
                    params={**common, "patch": {"controls": candidate_patch}},
                    gate_policy="strict",
                )
            )
        steps.extend(
            [
                Step("audit_preview_lineage", "TECH_VERIFY", "agent.nuke.composite.audit_lineage", 5, params={**common, "render_kind": "preview"}, gate_policy="strict"),
                Step(
                    "composite_preview_render",
                    "PREVIEW_RENDER",
                    "agent.nuke.composite.render_preview",
                    12,
                    params={**common, "frame": start, "kind": "preview"},
                    gate_policy="strict",
                ),
                Step("verify_composite_preview", "TECH_VERIFY", "agent.nuke.composite.verify_preview", 8, params={**common, "frame": start}, gate_policy="strict"),
            ]
        )
        if run_mode != "delivery":
            return steps
        steps.append(Step("audit_final_lineage", "ARTIFACT_VERIFY", "agent.nuke.composite.audit_lineage", 5, params={**common, "render_kind": "final"}, gate_policy="strict"))
        steps.extend(
            Step(
                f"composite_final_render_{frame:04d}",
                "FINAL_RENDER",
                "agent.nuke.composite.render_final",
                38,
                params={**common, "frame": frame, "kind": "final"},
                gate_policy="strict",
            )
            for frame in frames
        )
        steps.extend(
            [
                Step("verify_composite_final", "ARTIFACT_VERIFY", "agent.nuke.composite.verify_final", 12, params=common, gate_policy="strict"),
                Step("deliver_composite", "DELIVER", "agent.nuke.composite.deliver", 2, params=common, gate_policy="strict"),
            ]
        )
        return steps
