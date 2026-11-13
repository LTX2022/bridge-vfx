"""Versioned, DCC-agnostic effect-domain packs and DAG validation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Optional

from .contracts import ChangeDirection, DomainPackRef, IssueDimension, StageGraph, StageKind, StageNode
from .errors import RuntimeV2Error
from .models import ErrorCode


class DomainMaturity(str, Enum):
    EXPERIMENTAL = "experimental"
    SUPPORTED = "supported"


@dataclass(frozen=True)
class FeedbackRule:
    terms: tuple[str, ...]
    dimension: IssueDimension
    direction: ChangeDirection
    severity: float = 0.6

    def __post_init__(self) -> None:
        if not self.terms or any(not item.strip() for item in self.terms):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "feedback rule terms must be non-empty")
        if not 0.0 <= self.severity <= 1.0:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "feedback rule severity must be between zero and one")


@dataclass(frozen=True)
class SemanticControl:
    name: str
    value_type: str = "float"
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple[str, ...] = ()
    invalidates_stage_nodes: tuple[str, ...] = ()
    requires_simulation_cache: bool = False
    invalidates_components: tuple[str, ...] = ()
    application: str = "houdini"

    def validate(self, value: Any) -> Any:
        if self.value_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must be numeric")
            result: Any = float(value)
            if not math.isfinite(result):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must be finite")
        elif self.value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must be an integer")
            result = value
        elif self.value_type == "bool":
            if not isinstance(value, bool):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must be boolean")
            result = value
        elif self.value_type == "enum":
            if str(value) not in self.choices:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must be one of the declared choices")
            result = str(value)
        elif self.value_type == "string":
            result = str(value)
        elif self.value_type == "color3":
            if not isinstance(value, (list, tuple)) or len(value) != 3 or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} must contain three numeric color channels")
            result = tuple(float(item) for item in value)
            if not all(math.isfinite(item) for item in result):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} channels must be finite")
        else:
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"unsupported value type for {self.name}")
        if isinstance(result, (int, float)):
            if self.minimum is not None and result < self.minimum:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} is below its safe minimum")
            if self.maximum is not None and result > self.maximum:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} is above its safe maximum")
        if self.value_type == "color3":
            if self.minimum is not None and any(item < self.minimum for item in result):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} contains a channel below its safe minimum")
            if self.maximum is not None and any(item > self.maximum for item in result):
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, f"{self.name} contains a channel above its safe maximum")
        return result


@dataclass(frozen=True)
class ControlAdjustment:
    control: str
    operation: str
    amounts: tuple[Any, ...]

    def __post_init__(self) -> None:
        if self.operation not in {"scale", "add", "set"}:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "control adjustment operation is invalid")
        if not 1 <= len(self.amounts) <= 3:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "control adjustment must define one to three candidate amounts")


@dataclass(frozen=True)
class DiagnosticRule:
    identifier: str
    dimensions: tuple[IssueDimension, ...]
    cause_family: str
    stage_node_id: str
    evidence_signals: tuple[str, ...]
    adjustments: tuple[ControlAdjustment, ...]
    explanation: str
    confounders: tuple[str, ...] = ()
    estimated_cost: str = "medium"
    next_question: str = "请提供该阶段的诊断输出，以区分剩余原因。"


@dataclass(frozen=True)
class DomainPack:
    identifier: str
    version: str
    label: str
    components: tuple[str, ...]
    stage_graph: StageGraph
    controls: tuple[SemanticControl, ...]
    feedback_rules: tuple[FeedbackRule, ...]
    diagnostic_rules: tuple[DiagnosticRule, ...]
    required_evidence: tuple[str, ...]
    artifact_kinds: tuple[str, ...]
    dcc_applications: tuple[str, ...] = ("houdini",)
    compatible_versions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    maturity: DomainMaturity = DomainMaturity.EXPERIMENTAL

    @property
    def ref(self) -> DomainPackRef:
        return DomainPackRef(self.identifier, self.version)

    @property
    def control_map(self) -> dict[str, SemanticControl]:
        return {item.name: item for item in self.controls}

    @property
    def stage_map(self) -> dict[str, StageNode]:
        return {item.node_id: item for item in self.stage_graph.nodes}

    def controls_for_application(self, application: str) -> tuple[SemanticControl, ...]:
        return tuple(control for control in self.controls if control.application == application)

    def to_summary(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "version": self.version,
            "label": self.label,
            "components": list(self.components),
            "dcc_applications": list(self.dcc_applications),
            "maturity": self.maturity.value,
            "controls": [item.name for item in self.controls],
            "control_contracts": [
                {
                    "name": item.name,
                    "application": item.application,
                    "invalidates_stage_nodes": list(item.invalidates_stage_nodes),
                    "invalidates_components": list(item.invalidates_components),
                    "requires_simulation_cache": item.requires_simulation_cache,
                }
                for item in self.controls
            ],
            "required_evidence": list(self.required_evidence),
            "artifact_kinds": list(self.artifact_kinds),
        }


_STAGE_ORDER = {
    StageKind.SOURCE: 0,
    StageKind.LAYOUT: 1,
    StageKind.CONTROL: 2,
    StageKind.GENERATION: 3,
    StageKind.SIMULATION: 4,
    StageKind.SHAPING: 5,
    StageKind.MESHING: 6,
    StageKind.MATERIAL: 7,
    StageKind.LIGHTING: 8,
    StageKind.CAMERA: 8,
    StageKind.RENDER: 9,
    StageKind.COMPOSITE: 10,
    StageKind.DELIVERY: 11,
}


class DomainPackRegistry:
    def __init__(self, packs: Iterable[DomainPack] = ()) -> None:
        self._packs: dict[tuple[str, str], DomainPack] = {}
        for pack in packs:
            self.register(pack)

    def register(self, pack: DomainPack) -> None:
        self.validate(pack)
        key = (pack.identifier, pack.version)
        if key in self._packs:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"duplicate domain pack: {pack.identifier}@{pack.version}")
        self._packs[key] = pack

    def get(self, identifier: str, version: Optional[str] = None) -> DomainPack:
        if version is not None:
            try:
                return self._packs[(identifier, version)]
            except KeyError as exc:
                raise RuntimeV2Error(ErrorCode.UNSUPPORTED_DOMAIN, f"unsupported domain pack: {identifier}@{version}") from exc
        matches = [pack for (pack_id, _), pack in self._packs.items() if pack_id == identifier]
        if len(matches) != 1:
            raise RuntimeV2Error(ErrorCode.UNSUPPORTED_DOMAIN, f"domain version must be explicit: {identifier}")
        return matches[0]

    def list(self) -> tuple[DomainPackRef, ...]:
        return tuple(self._packs[key].ref for key in sorted(self._packs))

    def describe(self, identifier: str, version: str) -> dict[str, Any]:
        return self.get(identifier, version).to_summary()

    def validate(self, pack: DomainPack) -> None:
        if not pack.identifier.strip() or not pack.version.strip() or not pack.components:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "domain pack identifier, version, and components are required")
        nodes = pack.stage_graph.nodes
        if not nodes:
            raise RuntimeV2Error(ErrorCode.INVALID_STAGE_GRAPH, "domain stage graph must contain nodes")
        node_map = {item.node_id: item for item in nodes}
        if len(node_map) != len(nodes) or any(not item.node_id.strip() for item in nodes):
            raise RuntimeV2Error(ErrorCode.INVALID_STAGE_GRAPH, "stage node ids must be non-empty and unique")
        for node in nodes:
            missing = sorted(set(node.dependencies) - set(node_map))
            if missing:
                raise RuntimeV2Error(ErrorCode.INVALID_STAGE_GRAPH, "stage graph dependency is missing", {"node": node.node_id, "missing": missing})
            for dependency in node.dependencies:
                if _STAGE_ORDER[node_map[dependency].stage] > _STAGE_ORDER[node.stage]:
                    raise RuntimeV2Error(ErrorCode.INVALID_STAGE_GRAPH, "stage graph contains a backward dependency", {"node": node.node_id, "dependency": dependency})
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise RuntimeV2Error(ErrorCode.INVALID_STAGE_GRAPH, "stage graph contains a cycle", {"node": node_id})
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in node_map[node_id].dependencies:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_map:
            visit(node_id)
        controls = pack.control_map
        if len(controls) != len(pack.controls):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "domain control names must be unique")
        for control in pack.controls:
            missing = sorted(set(control.invalidates_stage_nodes) - set(node_map))
            if missing:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "control invalidation targets are missing", {"control": control.name, "missing": missing})
            missing_components = sorted(set(control.invalidates_components) - set(pack.components))
            if missing_components:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "control invalidation components are missing", {"control": control.name, "missing": missing_components})
            if control.application not in pack.dcc_applications:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "control application is not declared by the domain pack", {"control": control.name, "application": control.application})
        for rule in pack.diagnostic_rules:
            if rule.stage_node_id not in node_map:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "diagnostic rule stage does not exist", {"rule": rule.identifier})
            referenced = {adjustment.control for adjustment in rule.adjustments}
            missing_controls = sorted(referenced - set(controls))
            if missing_controls:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "diagnostic rule references unknown controls", {"rule": rule.identifier, "missing": missing_controls})
            if len(referenced) > 5:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "a diagnostic rule may change at most five controls")


def _standard_graph(identifier: str, include_simulation: bool = True, composite_only: bool = False) -> StageGraph:
    component = identifier
    if composite_only:
        return StageGraph(
            (
                StageNode("source", StageKind.SOURCE, component),
                StageNode("composite", StageKind.COMPOSITE, component, ("source",)),
                StageNode("delivery", StageKind.DELIVERY, component, ("composite",)),
            )
        )
    nodes = [
        StageNode("source", StageKind.SOURCE, component),
        StageNode("generation", StageKind.GENERATION, component, ("source",)),
    ]
    upstream = "generation"
    if include_simulation:
        nodes.append(StageNode("simulation", StageKind.SIMULATION, component, (upstream,)))
        upstream = "simulation"
    nodes.extend(
        [
            StageNode("shaping", StageKind.SHAPING, component, (upstream,)),
            StageNode("material", StageKind.MATERIAL, component, ("shaping",)),
            StageNode("lighting_camera", StageKind.LIGHTING, component, ("material",)),
            StageNode("render", StageKind.RENDER, component, ("lighting_camera",)),
            StageNode("composite", StageKind.COMPOSITE, component, ("render",)),
            StageNode("delivery", StageKind.DELIVERY, component, ("composite",)),
        ]
    )
    return StageGraph(tuple(nodes))


def _control(
    name: str,
    node: str,
    simulation: bool = False,
    minimum: Optional[float] = 0.0,
    maximum: Optional[float] = 10.0,
    value_type: str = "float",
    invalidates_components: tuple[str, ...] = (),
    application: str = "houdini",
) -> SemanticControl:
    return SemanticControl(name, value_type, minimum, maximum, (), (node,), simulation, invalidates_components, application)


def _pack(
    identifier: str,
    label: str,
    feedback: tuple[str, ...],
    dimension: IssueDimension,
    controls: tuple[SemanticControl, ...],
    include_simulation: bool = True,
    composite_only: bool = False,
    dcc_applications: tuple[str, ...] = ("houdini",),
) -> DomainPack:
    graph = _standard_graph(identifier, include_simulation, composite_only)
    if dcc_applications == ("nuke",):
        controls = tuple(replace(control, application="nuke") for control in controls)
    stage_groups: dict[str, list[SemanticControl]] = {}
    for control in controls:
        for stage_node_id in control.invalidates_stage_nodes:
            stage_groups.setdefault(stage_node_id, []).append(control)
    diagnostic_rules = []
    required_evidence = []
    for stage_node_id, stage_controls in stage_groups.items():
        signal = f"{identifier}.{stage_node_id}_evidence"
        required_evidence.append(signal)
        adjustments = []
        for control in stage_controls:
            if len(adjustments) >= 5:
                break
            if control.value_type == "int":
                adjustments.append(ControlAdjustment(control.name, "add", (1, 2, 4)))
            elif control.value_type == "float":
                adjustments.append(ControlAdjustment(control.name, "scale", (0.9, 0.75, 0.6)))
        if not adjustments:
            continue
        diagnostic_rules.append(
            DiagnosticRule(
                f"{identifier}.{stage_node_id}",
                (dimension,),
                f"{identifier}.{stage_node_id}_cause",
                stage_node_id,
                (signal,),
                tuple(adjustments),
                f"Use {stage_node_id} evidence before changing {label} controls.",
                ("lighting", "camera", "render", "composite"),
                "medium" if any(control.requires_simulation_cache for control in stage_controls) else "low",
                f"请提供 {label} 的 {stage_node_id} 诊断输出。",
            )
        )
    return DomainPack(
        identifier=identifier,
        version="1.0.0",
        label=label,
        components=(identifier,),
        stage_graph=graph,
        controls=controls,
        feedback_rules=(FeedbackRule(feedback, dimension, ChangeDirection.INCREASE),),
        diagnostic_rules=tuple(diagnostic_rules),
        required_evidence=tuple(required_evidence),
        artifact_kinds=("diagnostic_preview", "editable_scene") + (("simulation_cache",) if include_simulation else ()),
        dcc_applications=dcc_applications,
    )


def _explosion_pack() -> DomainPack:
    components = ("fire", "smoke", "shockwave", "particles", "rbd", "composite")
    graph = StageGraph(
        (
            StageNode("source", StageKind.SOURCE, "composite"),
            StageNode("fire_generation", StageKind.GENERATION, "fire", ("source",)),
            StageNode("fire_simulation", StageKind.SIMULATION, "fire", ("fire_generation",)),
            StageNode("smoke_generation", StageKind.GENERATION, "smoke", ("source",)),
            StageNode("smoke_simulation", StageKind.SIMULATION, "smoke", ("smoke_generation",)),
            StageNode("shockwave_generation", StageKind.GENERATION, "shockwave", ("source",)),
            StageNode("shockwave_shaping", StageKind.SHAPING, "shockwave", ("shockwave_generation",)),
            StageNode("particles_generation", StageKind.GENERATION, "particles", ("source",)),
            StageNode("particles_simulation", StageKind.SIMULATION, "particles", ("particles_generation",)),
            StageNode("rbd_generation", StageKind.GENERATION, "rbd", ("source",)),
            StageNode("rbd_simulation", StageKind.SIMULATION, "rbd", ("rbd_generation",)),
            StageNode(
                "composite",
                StageKind.COMPOSITE,
                "composite",
                ("fire_simulation", "smoke_simulation", "shockwave_shaping", "particles_simulation", "rbd_simulation"),
            ),
            StageNode("delivery", StageKind.DELIVERY, "composite", ("composite",)),
        )
    )
    controls = (
        _control("fire_energy", "fire_simulation", True, 0.0, 10.0, "float", ("fire",)),
        _control("smoke_dissipation", "smoke_simulation", True, 0.0, 5.0, "float", ("smoke",)),
        _control("spark_rate", "particles_simulation", True, 0.0, 1.0e7, "float", ("particles",)),
        _control("debris_scale", "rbd_generation", True, 0.001, 1000.0, "float", ("rbd",)),
        _control("shockwave_scale", "shockwave_generation", False, 0.001, 1.0e4, "float", ("shockwave",)),
        _control("fire_scale", "fire_simulation", True, 0.0, 100.0, "float", ("fire",)),
        _control("smoke_scale", "smoke_simulation", True, 0.0, 100.0, "float", ("smoke",)),
        _control("debris_energy", "rbd_simulation", True, 0.0, 1000.0, "float", ("rbd",)),
        _control("comp_contrast", "composite", False, 0.0, 10.0, "float", ("composite",), "nuke"),
        _control("shockwave_thickness", "shockwave_generation", False, 0.0, 1000.0, "float", ("shockwave",)),
        _control("debris_amount", "rbd_generation", True, 0.0, 1.0e6, "int", ("rbd",)),
    )
    rules = []
    evidence = []
    by_stage: dict[str, list[SemanticControl]] = {}
    for control in controls:
        by_stage.setdefault(control.invalidates_stage_nodes[0], []).append(control)
    for stage, stage_controls in by_stage.items():
        for chunk_index in range(0, len(stage_controls), 5):
            chunk = stage_controls[chunk_index : chunk_index + 5]
            signal = f"explosion_composite_v1.{stage}_evidence"
            if signal not in evidence:
                evidence.append(signal)
            invalidated = {component for control in chunk for component in control.invalidates_components}
            adjustments = tuple(
                ControlAdjustment(control.name, "add" if control.value_type == "int" else "scale", (1, 2, 4) if control.value_type == "int" else (0.9, 0.75, 0.6))
                for control in chunk
            )
            rules.append(
                DiagnosticRule(
                    f"explosion_composite_v1.{stage}.{chunk_index // 5}",
                    (IssueDimension.ENERGY,),
                    f"explosion_composite_v1.{stage}_cause_{chunk_index // 5}",
                    stage,
                    (signal,),
                    adjustments,
                    f"Inspect {stage} before changing its branch controls.",
                    tuple(component for component in components if component not in invalidated),
                    "medium" if any(control.requires_simulation_cache for control in chunk) else "low",
                    f"请提供爆炸 {stage} 分支的诊断输出。",
                )
            )
    return DomainPack(
        identifier="explosion_composite_v1",
        version="1.0.0",
        label="explosion composite",
        components=components,
        stage_graph=graph,
        controls=controls,
        feedback_rules=(FeedbackRule(("爆炸没力量", "explosion feels weak"), IssueDimension.ENERGY, ChangeDirection.INCREASE),),
        diagnostic_rules=tuple(rules),
        required_evidence=tuple(evidence),
        artifact_kinds=("diagnostic_preview", "editable_scene", "simulation_cache"),
        dcc_applications=("houdini", "nuke"),
    )


_EXTRA_CONTROL_SPECS: Mapping[str, tuple[tuple[str, str, bool, Optional[float], Optional[float], str], ...]] = {
    "pyro_smoke_v1": (
        ("volume_step_rate", "render", False, 0.01, 100.0, "float"), ("denoise_mix", "composite", False, 0.0, 1.0, "float"),
        ("source_scale", "source", True, 0.001, 1000.0, "float"), ("density_scale", "simulation", True, 0.0, 100.0, "float"),
        ("field_sharpen", "simulation", True, 0.0, 100.0, "float"), ("simulation_substeps", "simulation", True, 1.0, 100.0, "int"),
        ("volume_samples", "render", False, 1.0, 1.0e5, "int"),
    ),
    "pyro_fire_v1": (
        ("fuel_rate", "simulation", True, 0.0, 1000.0, "float"), ("velocity_detail", "simulation", True, 0.0, 100.0, "float"),
        ("emission_contrast", "composite", False, 0.0, 10.0, "float"), ("temperature_scale", "simulation", True, 0.0, 1000.0, "float"),
        ("flame_height", "simulation", True, -100.0, 1000.0, "float"), ("emission_intensity", "material", False, 0.0, 1.0e4, "float"),
        ("glow_amount", "composite", False, 0.0, 100.0, "float"),
    ),
    "particles_v1": (
        ("emission_variance", "simulation", True, 0.0, 100.0, "float"), ("life_variance", "simulation", True, 0.0, 1000.0, "float"),
        ("velocity_variance", "simulation", True, 0.0, 1000.0, "float"), ("force_noise", "simulation", True, 0.0, 1000.0, "float"),
        ("size_variance", "shaping", False, 0.0, 100.0, "float"), ("force_strength", "simulation", True, -1.0e4, 1.0e4, "float"),
        ("collision_radius", "simulation", True, 0.0, 1000.0, "float"), ("trail_length", "shaping", False, 0.0, 1.0e4, "float"),
        ("motion_blur_scale", "render", False, 0.0, 100.0, "float"), ("cluster_strength", "simulation", True, 0.0, 100.0, "float"),
    ),
    "water_ocean_v1": (
        ("spectrum_amplitude", "generation", False, 0.0, 100.0, "float"), ("directional_spread", "generation", False, 0.0, 360.0, "float"),
        ("crest_threshold", "shaping", False, 0.0, 100.0, "float"), ("foam_amount", "shaping", False, 0.0, 100.0, "float"),
    ),
    "water_flip_v1": (
        ("droplet_scale", "shaping", False, 0.0, 100.0, "float"), ("meshing_detail", "shaping", False, 0.01, 100.0, "float"),
        ("collision_separation", "simulation", True, 0.0, 100.0, "float"), ("collision_passes", "simulation", True, 1.0, 1000.0, "int"),
    ),
    "crowd_agents_v1": (
        ("speed_variance", "simulation", True, 0.0, 100.0, "float"), ("path_variance", "simulation", True, 0.0, 100.0, "float"),
        ("clip_offset", "simulation", True, -1.0e4, 1.0e4, "float"), ("avoidance_strength", "simulation", True, 0.0, 100.0, "float"),
        ("behavior_mix", "simulation", True, 0.0, 100.0, "float"), ("route_weight", "simulation", True, 0.0, 100.0, "float"),
        ("animation_variation", "simulation", True, 0.0, 100.0, "float"), ("timing_offset", "simulation", True, -1.0e4, 1.0e4, "float"),
    ),
    "swarm_flocking_v1": (("target_noise", "simulation", True, 0.0, 100.0, "float"), ("noise_strength", "simulation", True, 0.0, 1000.0, "float")),
    "vellum_cloth_v1": (("collision_thickness", "simulation", True, 0.0, 100.0, "float"), ("constraint_iterations", "simulation", True, 1.0, 1.0e4, "int"), ("wrinkle_scale", "simulation", True, 0.0, 100.0, "float")),
    "vellum_softbody_grains_v1": (("constraint_stiffness", "simulation", True, 0.0, 1.0e12, "float"), ("collision_passes", "simulation", True, 1.0, 1000.0, "int"), ("grain_size", "simulation", True, 0.0001, 1000.0, "float"), ("packing", "simulation", True, 0.0, 100.0, "float"), ("constraint_iterations", "simulation", True, 1.0, 1.0e4, "int")),
    "hair_fur_v1": (("collision_radius", "simulation", True, 0.0, 100.0, "float"), ("clump_strength", "shaping", False, 0.0, 100.0, "float"), ("wind_strength", "simulation", True, -1.0e4, 1.0e4, "float"), ("hair_width", "shaping", False, 0.00001, 100.0, "float")),
    "rbd_destruction_v1": (("fracture_variance", "generation", True, 0.0, 100.0, "float"), ("impact_spread", "simulation", True, 0.0, 1000.0, "float"), ("piece_scale", "generation", True, 0.001, 1000.0, "float"), ("velocity_variance", "simulation", True, 0.0, 1000.0, "float"), ("activation_frame", "simulation", True, -1.0e5, 1.0e5, "int"), ("impulse_scale", "simulation", True, 0.0, 1.0e4, "float")),
    "procedural_geometry_v1": (("scatter_variance", "source", False, 0.0, 1000.0, "float"), ("scale_variance", "shaping", False, 0.0, 100.0, "float"), ("rotation_variance", "shaping", False, 0.0, 360.0, "float"), ("deformation", "shaping", False, 0.0, 100.0, "float"), ("density", "source", False, 0.0, 1.0e7, "float"), ("rotation", "shaping", False, -360.0, 360.0, "float")),
    "material_lookdev_v1": (("normal_strength", "material", False, 0.0, 100.0, "float"), ("specular_weight", "material", False, 0.0, 1.0, "float"), ("coat_weight", "material", False, 0.0, 1.0, "float"), ("anisotropy", "material", False, 0.0, 1.0, "float"), ("displacement_scale", "material", False, -1000.0, 1000.0, "float"), ("emission_weight", "material", False, 0.0, 1.0e4, "float")),
    "lighting_camera_render_v1": (("sample_quality", "render", False, 1.0, 1.0e5, "float"), ("filter_width", "render", False, 0.01, 100.0, "float"), ("denoise_mix", "render", False, 0.0, 1.0, "float"), ("depth_of_field", "lighting_camera", False, 0.0, 1000.0, "float"), ("motion_blur", "render", False, None, None, "bool"), ("shutter", "lighting_camera", False, 0.0, 10.0, "float"), ("light_size", "lighting_camera", False, 0.0, 1.0e4, "float")),
    "nuke_composite_v1": (("glow_mix", "composite", False, 0.0, 10.0, "float"), ("edge_size", "composite", False, 0.0, 100.0, "float"), ("grain_mix", "composite", False, 0.0, 10.0, "float"), ("premult", "composite", False, None, None, "bool")),
}


def _augment_pack(pack: DomainPack) -> DomainPack:
    extras = _EXTRA_CONTROL_SPECS.get(pack.identifier, ())
    if not extras:
        return pack
    new_controls = tuple(
        _control(*specification, application="nuke" if pack.identifier == "nuke_composite_v1" or pack.identifier in {"pyro_smoke_v1", "pyro_fire_v1"} and specification[0] in {"denoise_mix", "emission_contrast", "glow_amount"} else "houdini")
        for specification in extras
    )
    controls = pack.controls + new_controls
    rules = list(pack.diagnostic_rules)
    evidence = list(pack.required_evidence)
    by_stage: dict[str, list[SemanticControl]] = {}
    for control in new_controls:
        by_stage.setdefault(control.invalidates_stage_nodes[0], []).append(control)
    for stage, stage_controls in by_stage.items():
        for chunk_index in range(0, len(stage_controls), 5):
            chunk = stage_controls[chunk_index : chunk_index + 5]
            adjustments = []
            for control in chunk:
                if control.value_type == "int":
                    adjustments.append(ControlAdjustment(control.name, "add", (1, 2, 4)))
                elif control.value_type == "float":
                    adjustments.append(ControlAdjustment(control.name, "scale", (0.9, 0.75, 0.6)))
                elif control.value_type == "bool":
                    adjustments.append(ControlAdjustment(control.name, "set", (True,)))
            if not adjustments:
                continue
            signal = f"{pack.identifier}.{stage}_extended_evidence"
            if signal not in evidence:
                evidence.append(signal)
            dimensions = tuple(dict.fromkeys(rule.dimension for rule in pack.feedback_rules))
            rules.append(DiagnosticRule(f"{pack.identifier}.{stage}.extended_{chunk_index // 5}", dimensions, f"{pack.identifier}.{stage}_extended_{chunk_index // 5}", stage, (signal,), tuple(adjustments), f"Inspect {stage} evidence before extended controls.", (), "medium" if any(control.requires_simulation_cache for control in chunk) else "low", f"请提供 {pack.label} 的 {stage} 扩展诊断输出。"))
    return DomainPack(pack.identifier, pack.version, pack.label, pack.components, pack.stage_graph, controls, pack.feedback_rules, tuple(rules), tuple(evidence), pack.artifact_kinds, pack.dcc_applications, pack.compatible_versions, pack.maturity)


def builtin_domain_registry() -> DomainPackRegistry:
    """Return the first-party v1 domain manifests.

    These manifests define safe orchestration contracts only.  Their maturity
    intentionally remains ``experimental`` until the separate DCC validation
    suite supplies real Houdini/Nuke evidence for a concrete installation.
    """

    specifications = (
        ("pyro_smoke_v1", "Pyro smoke", ("烟太模糊", "不够细", "smoke is blurry", "not detailed"), IssueDimension.SPATIAL_DETAIL, (
            _control("voxel_size", "simulation", True, 0.005, 1.0), _control("disturbance", "simulation", True), _control("shredding", "simulation", True), _control("dissipation", "simulation", True, 0.0, 5.0), _control("turbulence", "simulation", True),
        ), True, False, ("houdini", "nuke")),
        ("pyro_fire_v1", "Pyro fire", ("火苗太钝", "火不够灵动", "flame is blunt"), IssueDimension.MORPHOLOGY, (
            _control("voxel_size", "simulation", True, 0.005, 1.0), _control("burn_rate", "simulation", True), _control("cooling_rate", "simulation", True), _control("flame_disturbance", "simulation", True), _control("flame_lift", "simulation", True, -10.0, 10.0),
        ), True, False, ("houdini", "nuke")),
        ("particles_v1", "particles", ("粒子太均匀", "particle distribution is uniform"), IssueDimension.DISTRIBUTION, (
            _control("birth_rate", "simulation", True, 0.0, 1.0e7), _control("life", "simulation", True, 0.01, 1000.0), _control("speed", "simulation", True, 0.0, 1000.0), _control("drag", "simulation", True, 0.0, 100.0), _control("size", "shaping", False, 0.0001, 100.0),
        ), True, False, ("houdini", "nuke")),
        ("water_ocean_v1", "ocean", ("浪太平", "waves are flat"), IssueDimension.ENERGY, (
            _control("wave_scale", "generation", False, 0.0, 100.0), _control("wind_speed", "generation", False, 0.0, 200.0), _control("wind_direction", "generation", False, -360.0, 360.0), _control("chop", "shaping", False, 0.0, 10.0), _control("foam", "shaping", False, None, None, "bool"),
        ), False, False, ("houdini", "nuke")),
        ("water_flip_v1", "FLIP water", ("水花不够", "液滴太少", "splash is weak"), IssueDimension.INTERACTION, (
            _control("particle_separation", "simulation", True, 0.001, 10.0), _control("substeps", "simulation", True, 1.0, 20.0, "int"), _control("viscosity", "simulation", True, 0.0, 1.0e5), _control("surface_tension", "simulation", True, 0.0, 1.0e4), _control("surface_resolution", "shaping", False, 0.1, 10.0),
        ), True, False, ("houdini", "nuke")),
        ("crowd_agents_v1", "crowd agents", ("群集太机械", "crowd is mechanical"), IssueDimension.MOTION, (
            _control("speed", "simulation", True, 0.0, 100.0), _control("avoidance", "simulation", True), _control("behavior_variation", "simulation", True), _control("animation_blend", "simulation", True),
        ), True, False, ("houdini",)),
        ("swarm_flocking_v1", "swarm flocking", ("群集太整齐", "swarm is rigid"), IssueDimension.DISTRIBUTION, (
            _control("cohesion", "simulation", True, 0.0, 100.0), _control("separation", "simulation", True, 0.0, 100.0), _control("alignment", "simulation", True, 0.0, 100.0), _control("neighbor_radius", "simulation", True, 0.001, 1.0e4), _control("goal_attraction", "simulation", True, 0.0, 100.0),
        ), True, False, ("houdini",)),
        ("vellum_cloth_v1", "Vellum cloth", ("布料太硬", "cloth is stiff"), IssueDimension.MOTION, (
            _control("stretch_stiffness", "simulation", True, 0.0, 1.0e12), _control("bend_stiffness", "simulation", True, 0.0, 1.0e12), _control("damping", "simulation", True, 0.0, 100.0), _control("thickness", "simulation", True, 0.0, 100.0), _control("substeps", "simulation", True, 1.0, 100.0, "int"),
        ), True, False, ("houdini", "nuke")),
        ("vellum_softbody_grains_v1", "Vellum soft body and grains", ("软体太硬", "颗粒太僵", "soft body is stiff"), IssueDimension.MOTION, (
            _control("stiffness", "simulation", True, 0.0, 1.0e12), _control("cluster_stiffness", "simulation", True, 0.0, 1.0e12), _control("friction", "simulation", True), _control("damping", "simulation", True, 0.0, 100.0), _control("substeps", "simulation", True, 1.0, 100.0, "int"),
        ), True, False, ("houdini",)),
        ("hair_fur_v1", "hair and fur", ("毛发太僵", "hair is rigid"), IssueDimension.MOTION, (
            _control("guide_length", "generation", True, 0.0, 1000.0), _control("guide_density", "generation", True, 0.0, 1.0e7), _control("bend_stiffness", "simulation", True, 0.0, 1.0e12), _control("damping", "simulation", True, 0.0, 100.0), _control("clump", "shaping", False),
        ), True, False, ("houdini", "nuke")),
        ("rbd_destruction_v1", "RBD destruction", ("碎裂太整齐", "破碎太假", "fracture is uniform"), IssueDimension.DISTRIBUTION, (
            _control("fracture_scale", "generation", True, 0.001, 1000.0), _control("constraint_strength", "simulation", True, 0.0, 1.0e12), _control("impact_threshold", "simulation", True, 0.0, 1.0e12), _control("substeps", "simulation", True, 1.0, 100.0, "int"), _control("drag", "simulation", True, 0.0, 100.0),
        ), True, False, ("houdini", "nuke")),
        ("procedural_geometry_v1", "procedural geometry", ("分布太均匀", "形状太规则", "geometry is uniform"), IssueDimension.DISTRIBUTION, (
            _control("scatter_density", "source", False, 0.0, 1.0e7, "int"), _control("seed", "source", False, 0.0, 2147483647.0, "int"), _control("scale", "shaping", False, 0.0001, 1.0e4), _control("variation", "shaping", False, 0.0, 100.0),
        ), False, False, ("houdini",)),
        ("material_lookdev_v1", "material lookdev", ("材质像塑料", "material looks plastic"), IssueDimension.MATERIAL, (
            _control("base_color", "material", False, 0.0, 1.0, "color3"), _control("roughness", "material", False, 0.0, 1.0), _control("ior", "material", False, 1.0, 5.0), _control("transmission", "material", False, 0.0, 1.0), _control("subsurface", "material", False, 0.0, 1.0),
        ), False, False, ("houdini", "nuke")),
        ("lighting_camera_render_v1", "lighting camera and render", ("画面太平", "渲染太糊", "render is flat", "render is blurry"), IssueDimension.RENDER, (
            _control("exposure", "lighting_camera", False, -30.0, 30.0), _control("focal_length", "lighting_camera", False, 1.0, 1000.0), _control("pixel_samples", "render", False, 1.0, 1.0e5, "int"), _control("volume_step_rate", "render", False, 0.01, 100.0), _control("denoise", "render", False, None, None, "bool"),
        ), False, False, ("houdini", "nuke")),
        ("nuke_composite_v1", "Nuke composite", ("合成太糊", "边缘太软", "composite is blurry"), IssueDimension.COMPOSITE, (
            _control("blur_size", "composite", False, 0.0, 500.0), _control("defocus_size", "composite", False, 0.0, 500.0), _control("denoise_mix", "composite", False, 0.0, 1.0), _control("sharpen_amount", "composite", False, 0.0, 100.0), _control("glow_size", "composite", False, 0.0, 500.0),
        ), False, True, ("nuke",)),
    )
    registry = DomainPackRegistry()
    for specification in specifications:
        registry.register(_augment_pack(_pack(*specification)))
    registry.register(_explosion_pack())
    return registry
