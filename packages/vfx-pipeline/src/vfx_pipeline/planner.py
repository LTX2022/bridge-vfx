"""Decision-complete cross-DCC plans built from runtime v2 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from dcc_task_runtime.contracts import IssueDimension, ReferenceKind, TaskSpecV2
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.domains import DomainPack, DomainPackRegistry, builtin_domain_registry
from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.models import ErrorCode

from .commands import MODEL_SAFE_COMMANDS, TRUSTED_CONTROL_COMMANDS
from .router import BridgeRouter, RouteLeg


EXPLOSION_COMPONENT_PACKS = (
    "pyro_fire_v1",
    "pyro_smoke_v1",
    "procedural_geometry_v1",
    "particles_v1",
    "rbd_destruction_v1",
)


@dataclass(frozen=True)
class PlannedDomain:
    pack: DomainPack
    route: tuple[RouteLeg, ...]
    component_branches: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        summary = self.pack.to_summary()
        summary["version"] = self.pack.version
        summary["route"] = [item.to_dict() for item in self.route]
        if self.pack.identifier == "explosion_composite_v1":
            summary["meta_components"] = list(EXPLOSION_COMPONENT_PACKS)
            summary["component_branches"] = [dict(item) for item in self.component_branches]
        return summary


class PipelinePlanner:
    def __init__(
        self,
        registry: Optional[DomainPackRegistry] = None,
        router: Optional[BridgeRouter] = None,
    ) -> None:
        self.registry = registry or builtin_domain_registry()
        self.router = router or BridgeRouter()

    def domains_for(self, spec: TaskSpecV2) -> tuple[DomainPack, ...]:
        if spec.domains:
            return tuple(self.registry.get(item.identifier, item.version) for item in spec.domains)
        text = f"{spec.intent}\n{spec.feedback}".casefold()
        matched = []
        for ref in self.registry.list():
            pack = self.registry.get(ref.identifier, ref.version)
            if any(term.casefold() in text for rule in pack.feedback_rules for term in rule.terms):
                matched.append(pack)
        if not matched:
            raise RuntimeV2Error(
                ErrorCode.UNSUPPORTED_DOMAIN,
                "the domain cannot be selected safely; supply domains[].identifier and version",
            )
        return tuple(matched)

    def plan(self, raw_spec: TaskSpecV2 | Mapping[str, Any]) -> dict[str, Any]:
        spec = self.prepare_spec(raw_spec)
        include_composite = bool(spec.delivery.get("composite", True))
        planned_items = []
        for pack in self.domains_for(spec):
            branches = self._explosion_branches(include_composite) if pack.identifier == "explosion_composite_v1" else ()
            planned_items.append(PlannedDomain(pack, self.router.route(pack, include_composite=include_composite), branches))
        planned = tuple(planned_items)
        stages = [
            {"id": "analyze", "state": "ANALYZING", "action": "analyze_references_and_scene"},
            {"id": "preview", "state": "PREVIEWING", "action": "run_isolated_dcc_previews"},
            {"id": "diagnose", "state": "DIAGNOSING", "action": "interpret_feedback_and_collect_stage_evidence"},
            {"id": "candidates", "state": "CANDIDATES_READY", "action": "propose_at_most_three_bounded_candidates"},
            {"id": "cache_approval", "state": "AWAITING_CACHE_APPROVAL", "action": "request_simulation_cache_approval_when_required"},
            {"id": "verify", "state": "VERIFYING", "action": "compare_preview_and_protected_attributes"},
            {"id": "experience_approval", "state": "AWAITING_EXPERIENCE_APPROVAL", "action": "request_optional_experience_promotion"},
        ]
        return {
            "schema_version": "2.0",
            "task_type": spec.task_type,
            "spec": spec.to_dict(),
            "spec_hash": spec.subject_hash,
            "domains": [item.to_dict() for item in planned],
            "stages": stages,
            "command_surfaces": {
                "model_safe": sorted(MODEL_SAFE_COMMANDS),
                "trusted_control": sorted(TRUSTED_CONTROL_COMMANDS),
            },
            "invariants": {
                "arbitrary_code": False,
                "reference_may_feed_final_write": False,
                "cache_requires_trusted_grant": True,
                "experience_requires_separate_trusted_grant": True,
                "candidate_limit": 3,
                "controls_per_candidate_limit": 5,
            },
        }

    def prepare_spec(self, raw_spec: TaskSpecV2 | Mapping[str, Any]) -> TaskSpecV2:
        """Apply the conservative temporal diagnostic default.

        Explicit frame ranges always win.  A still-image/text task whose
        matched feedback rule is motion/timing receives a fixed 2 second,
        24fps diagnostic range so the pipeline never claims dynamics from one
        frame.  Sequence/video inputs remain caller-controlled.
        """

        if isinstance(raw_spec, TaskSpecV2):
            spec = raw_spec
            # A constructed contract no longer retains presence/absence of the
            # raw key, so its normalized range is treated as deliberate.
            explicitly_ranged = True
        else:
            explicit_render = raw_spec.get("render") if isinstance(raw_spec.get("render"), Mapping) else {}
            explicitly_ranged = "frame_range" in explicit_render
            spec = TaskSpecV2.from_mapping(raw_spec)
        if explicitly_ranged or any(item.kind in {ReferenceKind.SEQUENCE, ReferenceKind.VIDEO} for item in spec.references):
            return spec
        folded = spec.feedback.casefold()
        temporal = False
        if folded:
            for pack in self.domains_for(spec):
                if any(
                    rule.dimension in {IssueDimension.MOTION, IssueDimension.TIMING}
                    and any(term.casefold() in folded for term in rule.terms)
                    for rule in pack.feedback_rules
                ):
                    temporal = True
                    break
        if not temporal:
            return spec
        render = {**dict(spec.render), "frame_range": {"start": 1, "end": 48, "step": 1}, "fps": 24}
        metadata = {
            **dict(spec.metadata),
            "temporal_diagnostic_default": {
                "reason": "motion_or_timing_feedback_without_sequence_or_video",
                "duration_seconds": 2,
                "fps": 24,
            },
        }
        return TaskSpecV2(
            intent=spec.intent,
            references=spec.references,
            feedback=spec.feedback,
            domains=spec.domains,
            inputs=spec.inputs,
            target_scene=spec.target_scene,
            target_scene_path=spec.target_scene_path,
            constraints=spec.constraints,
            render=render,
            delivery=spec.delivery,
            metadata=metadata,
            idempotency_key=spec.idempotency_key,
        )

    def list_domains(self) -> list[dict[str, Any]]:
        result = []
        for ref in self.registry.list():
            pack = self.registry.get(ref.identifier, ref.version)
            summary = pack.to_summary()
            summary["version"] = pack.version
            if pack.identifier == "explosion_composite_v1":
                summary["meta_components"] = list(EXPLOSION_COMPONENT_PACKS)
            result.append(summary)
        return result

    def _explosion_branches(self, include_composite: bool) -> tuple[Mapping[str, Any], ...]:
        branch_specs = [
            ("fire", "pyro_fire_v1", ()),
            ("smoke", "pyro_smoke_v1", ()),
            ("shockwave", "procedural_geometry_v1", ()),
            ("particles", "particles_v1", ()),
            ("rbd", "rbd_destruction_v1", ()),
        ]
        branches = []
        for branch_id, domain_id, dependencies in branch_specs:
            pack = self.registry.get(domain_id, "1.0.0")
            payload = {
                "branch_id": branch_id,
                "domain_pack": domain_id,
                "domain_version": pack.version,
                "dependencies": list(dependencies),
                "route": [item.to_dict() for item in self.router.route(pack, include_composite=False)],
            }
            payload["branch_hash"] = canonical_sha256(payload)
            branches.append(payload)
        if include_composite:
            pack = self.registry.get("nuke_composite_v1", "1.0.0")
            payload = {
                "branch_id": "composite",
                "domain_pack": pack.identifier,
                "domain_version": pack.version,
                "dependencies": ["fire", "smoke", "shockwave", "particles", "rbd"],
                "route": [item.to_dict() for item in self.router.route(pack, include_composite=True)],
            }
            payload["branch_hash"] = canonical_sha256(payload)
            branches.append(payload)
        return tuple(branches)

    def show_domain(self, identifier: str, version: str = "1.0.0") -> dict[str, Any]:
        pack = self.registry.get(identifier, version)
        result = pack.to_summary()
        result.update(
            {
                "version": pack.version,
                "stage_graph": pack.stage_graph.to_dict(),
                "controls": [
                    {
                        "name": item.name,
                        "value_type": item.value_type,
                        "minimum": item.minimum,
                        "maximum": item.maximum,
                        "choices": list(item.choices),
                        "invalidates_stage_nodes": list(item.invalidates_stage_nodes),
                        "requires_simulation_cache": item.requires_simulation_cache,
                    }
                    for item in pack.controls
                ],
                "feedback_terms": sorted({term for rule in pack.feedback_rules for term in rule.terms}),
                "diagnostic_rules": [item.identifier for item in pack.diagnostic_rules],
            }
        )
        if identifier == "explosion_composite_v1":
            result["meta_components"] = list(EXPLOSION_COMPONENT_PACKS)
        return result
