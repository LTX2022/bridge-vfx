"""Domain-dispatched observations and bounded plans, independent of native DCCs.

A plan being ready means its required observations are present. It is not a
claim that a native graph, simulation, render, or visual target was verified.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import canonical_sha256
from .domains import builtin_domain_registry
from .errors import RuntimeV2Error
from .models import ErrorCode
from .visual_objective import MediaManifest, SemanticValue, validate_reference_analysis

DOMAIN_OBJECTIVE_SCHEMA = "bridge.domain_visual_objective/1.0"
DOMAIN_PLAN_SCHEMA = "bridge.domain_control_plan/1.0"
REQUIRED_CONTROLS = {
    "pyro_smoke_v1": ("voxel_size", "dissipation", "source_scale", "density_scale"),
    "pyro_fire_v1": ("voxel_size", "burn_rate", "fuel_rate", "temperature_scale"),
    "particles_v1": ("birth_rate", "life", "speed", "drag", "size"),
    "water_ocean_v1": ("wave_scale", "wind_speed", "wind_direction", "chop"),
    "water_flip_v1": ("particle_separation", "substeps", "viscosity", "surface_resolution"),
    "crowd_agents_v1": ("speed", "avoidance", "behavior_variation", "animation_blend"),
    "swarm_flocking_v1": ("cohesion", "separation", "alignment", "neighbor_radius", "goal_attraction"),
    "vellum_cloth_v1": ("stretch_stiffness", "bend_stiffness", "thickness", "substeps"),
    "vellum_softbody_grains_v1": ("stiffness", "friction", "substeps", "grain_size"),
    "hair_fur_v1": ("guide_length", "guide_density", "bend_stiffness", "clump"),
    "rbd_destruction_v1": ("fracture_scale", "constraint_strength", "impact_threshold", "substeps"),
    "procedural_geometry_v1": ("scatter_density", "seed", "scale", "variation"),
    "material_lookdev_v1": ("base_color", "roughness", "ior", "transmission"),
    "lighting_camera_render_v1": ("exposure", "focal_length", "pixel_samples"),
    "nuke_composite_v1": ("blur_size", "premult"),
    "explosion_composite_v1": ("fire_energy", "smoke_dissipation", "spark_rate", "debris_scale", "shockwave_scale"),
}


def _invalid(message: str, **details: Any) -> RuntimeV2Error:
    return RuntimeV2Error(ErrorCode.INVALID_SPEC, message, details)


def _pack(domain: str):
    if domain not in REQUIRED_CONTROLS:
        raise _invalid("unregistered domain objective", domain_pack=domain)
    return builtin_domain_registry().get(domain, "1.0.0")


@dataclass(frozen=True)
class DomainVisualObjective:
    domain_pack: str
    media_manifest: MediaManifest
    controls: tuple[tuple[str, SemanticValue], ...]
    schema_version: str = DOMAIN_OBJECTIVE_SCHEMA

    def __post_init__(self):
        pack = _pack(self.domain_pack)
        if self.schema_version != DOMAIN_OBJECTIVE_SCHEMA or not isinstance(self.media_manifest, MediaManifest):
            raise _invalid("invalid domain objective schema or media manifest")
        values = {}
        for name, semantic in self.controls:
            if name in values or name not in pack.control_map or not isinstance(semantic, SemanticValue):
                raise _invalid("unknown, duplicate, or untyped domain control", control=name)
            if semantic.is_known:
                value = pack.control_map[name].validate(semantic.value)
                semantic = SemanticValue(value, semantic.provenance, semantic.confidence, semantic.basis)
            values[name] = semantic
        for name in REQUIRED_CONTROLS[self.domain_pack]:
            values.setdefault(name, SemanticValue.unknown("analysis.missing." + name))
        object.__setattr__(self, "controls", tuple(sorted(values.items())))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]):
        expected = {"schema_version", "domain_pack", "media_manifest", "controls"}
        if not isinstance(value, Mapping) or set(value) != expected or not isinstance(value["controls"], Mapping):
            raise _invalid("domain objective requires exactly schema_version/domain_pack/media_manifest/controls")
        return cls(str(value["domain_pack"]), MediaManifest.from_mapping(value["media_manifest"]),
                   tuple((name, SemanticValue.from_mapping(semantic)) for name, semantic in value["controls"].items()),
                   str(value["schema_version"]))

    @classmethod
    def from_reference_analysis(cls, domain_pack: str, media_manifest: MediaManifest, analysis: Any):
        typed = validate_reference_analysis(analysis)
        pack = _pack(domain_pack)
        identifiers = {domain_pack, domain_pack.removesuffix("_v1"), *pack.components}
        matches = [c for c in typed.components if c.component_id in identifiers]
        if len(matches) != 1:
            raise _invalid("analysis must identify exactly one target component", domain_pack=domain_pack,
                           matching_components=[c.component_id for c in matches])
        component = matches[0]
        supplied = component.observations.get("controls", {})
        if not isinstance(supplied, Mapping):
            raise _invalid("component observations.controls must be an object")
        # Provenance is mandatory. Raw numbers are not silently called observations.
        controls = tuple((name, SemanticValue.from_mapping(raw)) for name, raw in supplied.items())
        return cls(domain_pack, media_manifest, controls)

    @property
    def missing_semantics(self):
        return tuple(name for name, value in self.controls if not value.is_known)

    @property
    def is_sufficient(self):
        return not self.missing_semantics

    @property
    def objective_hash(self):
        return canonical_sha256(self.to_dict())

    def to_dict(self):
        return {"schema_version": self.schema_version, "domain_pack": self.domain_pack,
                "media_manifest": self.media_manifest.to_dict(),
                "controls": {name: value.to_dict() for name, value in self.controls}}

    def source_plan(self):
        return DomainControlPlan(self)

    to_source_plan = source_plan


@dataclass(frozen=True)
class DomainControlPlan:
    objective: DomainVisualObjective

    @property
    def domain_pack(self):
        return self.objective.domain_pack

    @property
    def ready(self):
        return self.objective.is_sufficient

    @property
    def plan_sha256(self):
        return canonical_sha256(self.to_dict())

    @property
    def plan_hash(self):
        return self.plan_sha256

    def require_ready(self):
        if not self.ready:
            raise _invalid("domain plan lacks required observations", missing_semantics=list(self.objective.missing_semantics))
        return self

    def controls_for_application(self, application):
        pack = _pack(self.domain_pack)
        return {name: value.value for name, value in self.objective.controls
                if value.is_known and pack.control_map[name].application == application}

    def to_dict(self):
        pack = _pack(self.domain_pack)
        controls = []
        for name, semantic in self.objective.controls:
            if not semantic.is_known:
                continue
            control = pack.control_map[name]
            controls.append({"name": name, **semantic.to_dict(), "value_type": control.value_type,
                             "application": control.application,
                             "invalidates_stage_nodes": list(control.invalidates_stage_nodes),
                             "invalidates_components": list(control.invalidates_components),
                             "requires_simulation_cache": control.requires_simulation_cache})
        return {"schema_version": DOMAIN_PLAN_SCHEMA, "domain_pack": self.domain_pack,
                "pack_version": pack.version, "objective": self.objective.to_dict(),
                "objective_sha256": self.objective.objective_hash,
                "media_manifest_sha256": self.objective.media_manifest.content_sha256,
                "ready": self.ready, "missing_semantics": list(self.objective.missing_semantics),
                "controls": controls}

    @classmethod
    def from_mapping(cls, raw):
        if not isinstance(raw, Mapping):
            raise _invalid("domain control plan must be an object")
        result = cls(DomainVisualObjective.from_mapping(raw.get("objective", {})))
        if result.to_dict() != dict(raw):
            raise _invalid("domain plan differs from its registered objective and control contract")
        return result


def build_domain_control_plan(objective: DomainVisualObjective) -> DomainControlPlan:
    if not isinstance(objective, DomainVisualObjective):
        raise _invalid("domain plan requires a typed domain objective")
    return objective.source_plan()
