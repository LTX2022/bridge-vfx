"""Declarative first-party Houdini/Karma effect domain packs.

The host package deliberately keeps these declarations free of ``hou`` and of
Task Runtime v2 imports.  They are safe to inspect from a planner process and
are mirrored by capability probes in the in-Houdini add-on.  A pack remains
``experimental`` until its exact node/parameter contract has live evidence for
both Houdini 21 and Houdini 22.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Iterable, Mapping, Optional


STAGES = (
    "source_layout_control",
    "generation_simulation",
    "shaping_meshing",
    "material",
    "lighting_camera",
    "render",
    "composite",
    "delivery",
)


@dataclass(frozen=True)
class NodeRequirement:
    """One native Houdini node role with version-tolerant type aliases."""

    role: str
    category: str
    type_candidates: tuple[str, ...]
    required_parameter_aliases: tuple[tuple[str, ...], ...] = ()
    input_role: Optional[str] = None
    parent_role: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "role": self.role,
            "category": self.category,
            "type_candidates": list(self.type_candidates),
            "required_parameter_aliases": [list(item) for item in self.required_parameter_aliases],
            "input_role": self.input_role,
        }
        if self.parent_role:
            result["parent_role"] = self.parent_role
        return result


@dataclass(frozen=True)
class SemanticControl:
    """A bounded public control; concrete parameters are resolved in Houdini."""

    identifier: str
    node_role: str
    parameter_aliases: tuple[str, ...]
    minimum: float
    maximum: float
    invalidates_from: str
    value_type: str = "float"
    application: str = "houdini"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "node_role": self.node_role,
            "parameter_aliases": list(self.parameter_aliases),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "invalidates_from": self.invalidates_from,
            "value_type": self.value_type,
            "application": self.application,
        }


@dataclass(frozen=True)
class GraphConnection:
    """One declared wire: source role/output port into destination role/input port."""

    source_role: str
    source_output: Optional[int]
    destination_role: str
    destination_input: Optional[int]
    source_output_name: Optional[str] = None
    destination_input_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "source_role": self.source_role,
            "source_output": self.source_output,
            "destination_role": self.destination_role,
            "destination_input": self.destination_input,
        }
        for key in ("source_output", "destination_input"):
            if result[key] is None:
                del result[key]
        if self.source_output_name:
            result["source_output_name"] = self.source_output_name
        if self.destination_input_name:
            result["destination_input_name"] = self.destination_input_name
        return result


def validate_connections(connections: Iterable[Any], known_roles: Iterable[str]) -> dict[str, Any]:
    """Structural validation of a full connection set BEFORE any side effect.

    Rejects: malformed entries, unknown roles, negative/non-integer ports,
    duplicate destination ports, and missing connections for roles that a
    solver-style multi-input contract requires. Returns {"ok": bool, "errors": [...]}.
    """
    errors: list[str] = []
    seen_dest: set[tuple[str, int]] = set()
    roles = set(known_roles)
    normalized: list[dict[str, Any]] = []
    if not isinstance(connections, (list, tuple)):
        return {"ok": False, "errors": ["connections must be a sequence"], "connections": []}
    for index, raw in enumerate(connections):
        if isinstance(raw, dict):
            entry = raw
            source_role = entry.get("source_role")
            source_output = entry.get("source_output")
            destination_role = entry.get("destination_role")
            destination_input = entry.get("destination_input")
        else:
            try:
                source_role, source_output, destination_role, destination_input = raw
            except Exception:
                errors.append(f"connection[{index}]: malformed entry {raw!r}")
                continue
        if source_role not in roles:
            errors.append(f"connection[{index}]: unknown source_role {source_role!r}")
        if destination_role not in roles:
            errors.append(f"connection[{index}]: unknown destination_role {destination_role!r}")
        for name, value in (("source_output", source_output), ("destination_input", destination_input)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"connection[{index}]: {name} must be a non-negative int, got {value!r}")
        if not isinstance(source_role, str) or not isinstance(destination_role, str):
            errors.append(f"connection[{index}]: roles must be strings")
            continue
        key = (destination_role, destination_input if isinstance(destination_input, int) else -1)
        if key in seen_dest:
            errors.append(f"connection[{index}]: duplicate destination port {destination_role}.input{destination_input}")
        seen_dest.add(key)
        normalized.append({"source_role": source_role, "source_output": source_output,
                           "destination_role": destination_role, "destination_input": destination_input})
    return {"ok": not errors, "errors": errors, "connections": normalized}


def legacy_connections(nodes: Iterable[Any]) -> list[dict[str, Any]]:
    """Legacy input_role compat: source output 0 -> destination input 0."""
    out: list[dict[str, Any]] = []
    for node in nodes or []:
        role = str(node.get("role") or "") if isinstance(node, dict) else str(getattr(node, "role", ""))
        input_role = node.get("input_role") if isinstance(node, dict) else getattr(node, "input_role", None)
        if input_role:
            out.append({"source_role": str(input_role), "source_output": 0,
                        "destination_role": role, "destination_input": 0})
    return out


@dataclass(frozen=True)
class EffectDomainPack:
    identifier: str
    label: str
    component: str
    nodes: tuple[NodeRequirement, ...]
    controls: tuple[SemanticControl, ...]
    evidence: tuple[str, ...]
    metrics: tuple[str, ...]
    simulation_cache: bool
    stages: tuple[str, ...] = STAGES
    version: str = "1.0.0"
    maturity: str = "experimental"
    validated_houdini_versions: tuple[str, ...] = ()
    component_packs: tuple[str, ...] = ()
    connections: tuple[GraphConnection, ...] = ()

    def declared_connections(self) -> list[dict[str, Any]]:
        """Explicit connections if declared, else legacy input_role compat."""
        if self.connections:
            return [item.to_dict() for item in self.connections]
        return legacy_connections([node.to_dict() for node in self.nodes])

    def to_dict(self, *, native_version="21.0.631", native_branch=None) -> dict[str, Any]:
        result = {
            "id": self.identifier,
            "version": self.version,
            "label": self.label,
            "component": self.component,
            "maturity": self.maturity,
            "validated_houdini_versions": list(self.validated_houdini_versions),
            "stages": list(self.stages),
            "nodes": [item.to_dict() for item in self.nodes],
            "connections": self.declared_connections(),
            "controls": [item.to_dict() for item in self.controls],
            "evidence": list(self.evidence),
            "metrics": list(self.metrics),
            "simulation_cache": self.simulation_cache,
            "component_packs": list(self.component_packs),
        }

        if self.identifier in {"material_lookdev_v1", "lighting_camera_render_v1"}:
            from .native_render_domains import overlay_core_pack_dict
            result = overlay_core_pack_dict(result,native_version)
        elif self.identifier in {"pyro_smoke_v1", "pyro_fire_v1", "vellum_cloth_v1", "hair_fur_v1", "crowd_agents_v1", "water_flip_v1", "rbd_destruction_v1", "particles_v1", "swarm_flocking_v1", "water_ocean_v1", "procedural_geometry_v1"}:
            from .native_domain_registry import overlay_core_pack_dict
            result = overlay_core_pack_dict(result, native_version, native_branch)
        elif self.identifier == "vellum_softbody_grains_v1":
            from .native_domain_registry import overlay_core_pack_dict
            if native_branch is None:
                result["native_branch_required"] = True
                result["native_branches"] = {branch: overlay_core_pack_dict(result, native_version, branch)
                                             for branch in ("softbody", "grains")}
            else:
                result = overlay_core_pack_dict(result, native_version, native_branch)
        elif self.identifier == "explosion_composite_v1":
            from .product_composite_definitions import overlay_core_pack_dict
            result = overlay_core_pack_dict(result, native_version)
        return result


def _conn(source_role, source_output, destination_role, destination_input):
    return GraphConnection(source_role, source_output, destination_role, destination_input)


def _node(
    role: str,
    *types: str,
    category: str = "sop",
    parms: Iterable[Iterable[str]] = (),
    input_role: Optional[str] = None,
) -> NodeRequirement:
    return NodeRequirement(role, category, tuple(types), tuple(tuple(item) for item in parms), input_role)


def _control(
    identifier: str,
    role: str,
    aliases: Iterable[str],
    minimum: float,
    maximum: float,
    invalidates_from: str = "generation_simulation",
    value_type: str = "float",
    application: str = "houdini",
) -> SemanticControl:
    return SemanticControl(identifier, role, tuple(aliases), minimum, maximum, invalidates_from, value_type, application)


_SOURCE_SPHERE = _node("source", "sphere", parms=(("radx", "radius"),))
_SOURCE_GRID = _node("source", "grid", parms=(("sizex", "size1"), ("sizey", "size2")))


DOMAIN_PACKS: tuple[EffectDomainPack, ...] = (
    EffectDomainPack(
        "pyro_smoke_v1", "Pyro Smoke", "smoke",
        (_SOURCE_SPHERE, _node("solver", "pyrosolver", "pyrosolver::2.0", parms=(
            ("divsize", "voxelsize"), ("disturbance", "disturbancescale"),
            ("shredding", "shreddingscale"), ("dissipation", "dissipationscale"),
            ("turbulence", "turbulencescale"), ("densityscale", "smokeamount"),
        ), input_role="source"), _node("output", "null", input_role="solver")),
        (
            _control("voxel_size", "solver", ("divsize", "voxelsize"), 0.005, 1.0),
            _control("disturbance", "solver", ("disturbance", "disturbancescale"), 0.0, 10.0),
            _control("shredding", "solver", ("shredding", "shreddingscale"), 0.0, 10.0),
            _control("dissipation", "solver", ("dissipation", "dissipationscale"), 0.0, 5.0),
            _control("turbulence", "solver", ("turbulence", "turbulencescale"), 0.0, 10.0),
        ),
        ("density_field", "velocity_field", "temperature_field", "precomp_beauty", "final_beauty"),
        ("edge_frequency", "density_gradient", "silhouette_iou", "temporal_coherence"), True,
    ),
    EffectDomainPack(
        "pyro_fire_v1", "Pyro Fire", "fire",
        (_SOURCE_SPHERE, _node("solver", "pyrosolver", "pyrosolver::2.0", parms=(("divsize", "voxelsize"),), input_role="source"), _node("output", "null", input_role="solver")),
        (
            _control("voxel_size", "solver", ("divsize", "voxelsize"), 0.005, 1.0),
            _control("burn_rate", "solver", ("burn", "burnrate"), 0.0, 10.0),
            _control("cooling_rate", "solver", ("coolingrate", "cooling"), 0.0, 10.0),
            _control("flame_disturbance", "solver", ("disturbance", "disturbancescale"), 0.0, 10.0),
            _control("flame_lift", "solver", ("buoyancylift", "buoyancy"), -10.0, 10.0),
        ),
        ("flame_field", "temperature_field", "velocity_field", "emission_aov", "final_beauty"),
        ("flame_tip_sharpness", "emission_distribution", "motion_frequency", "temporal_coherence"), True,
    ),
    EffectDomainPack(
        "particles_v1", "Particles", "particles",
        (_node('source', 'sphere', category='sop'), _node('simulation', 'dopnet', category='sop'), _node('particle_object', 'popobject', category='dop'), _node('emission', 'popsource::2.0', category='dop'), _node('drag', 'popdrag', category='dop'), _node('solver', 'popsolver::2.0', category='dop'), _node('simulation_output', 'output', category='dop'), _node('particle_size', 'attribadjustfloat', category='sop'), _node('instance_source', 'sphere', category='sop'), _node('instances', 'copytopoints::2.0', category='sop'), _node('output', 'null', category='sop')),
        (
            _control('birth_rate', 'emission', ('constantrate',), 0.0, 10000000.0),
            _control('life', 'emission', ('life',), 0.01, 1000.0),
            _control('speed', 'emission', ('vely',), 0.0, 1000.0),
            _control('drag', 'drag', ('airresist',), 0.0, 100.0),
            _control('size', 'particle_size', ('singlevalue',), 0.0001, 100.0),
        ),
        ("particle_points", "id_age_velocity", "instanced_geometry"),
        ("count_distribution", "trajectory_coherence"), True,
        connections=(_conn('source',0,'simulation',0), _conn('particle_object',0,'solver',0), _conn('emission',0,'drag',0), _conn('drag',0,'solver',2), _conn('solver',0,'simulation_output',0), _conn('simulation',0,'particle_size',0), _conn('instance_source',0,'instances',0), _conn('particle_size',0,'instances',1), _conn('instances',0,'output',0)),
    ),
    EffectDomainPack(
        "water_ocean_v1", "Ocean Spectrum", "ocean",
        (_node("source", "grid"), _node("spectrum", "oceanspectrum"), _node("evaluate", "oceanevaluate::2.0", "oceanevaluate"), _node("output", "null", input_role="evaluate")),
        (
            _control("wave_scale", "spectrum", ("ampscale",), 0.0, 100.0),
            _control("wind_speed", "spectrum", ("windspeed", "wind"), 0.0, 200.0),
            _control("wind_direction", "spectrum", ("winddir",), -360.0, 360.0),
            _control("chop", "spectrum", ("chopscale",), 0.0, 10.0, "shaping_meshing"),
            _control("foam", "evaluate", ("enablefoam", "foam"), 0.0, 1.0, "shaping_meshing", "bool"),
        ),
        ("spectrum", "displacement", "cusp_mask", "foam_mask", "final_beauty"),
        ("wave_height_spectrum", "crest_density", "directionality", "temporal_periodicity"), False,
        connections=(_conn("source", 0, "evaluate", 0), _conn("spectrum", 0, "evaluate", 1), _conn("evaluate", 0, "output", 0)),
    ),
    EffectDomainPack(
        "water_flip_v1", "FLIP Water", "flip",
        (_node("source", "sphere"), _node("fluid_source", "flipsource", input_role="source"), _node("container", "flipcontainer"), _node("collision_source", "box"), _node("collision_transform", "xform", input_role="collision_source"), _node("collisions", "flipcollide"), _node("solver", "flipsolver"), _node("surface", "particlefluidsurface::2.0", input_role="solver"), _node("output", "null", input_role="surface")),
        (
            _control("particle_separation", "container", ("particlesep",), 0.001, 10.0),
            _control("substeps", "solver", ("minimumsubsteps",), 1.0, 20.0, value_type="int"),
            _control("viscosity", "container", ("default_viscosity",), 0.0, 100000.0),
            _control("surface_tension", "container", ("surfacetension",), 0.0, 10000.0),
            _control("surface_resolution", "surface", ("voxelsize",), 0.1, 10.0, "shaping_meshing"),
        ),
        ("flip_particles", "velocity", "surface_mesh", "curvature", "final_beauty"),
        ("splash_count", "droplet_size_distribution", "surface_roughness", "volume_conservation"), True,
        connections=(_conn("source",0,"fluid_source",0), _conn("fluid_source",0,"container",0), _conn("collision_source",0,"collision_transform",0), _conn("collision_transform",0,"collisions",3), _conn("container",0,"collisions",0), _conn("container",1,"collisions",1), _conn("container",2,"collisions",2), _conn("collisions",0,"solver",0), _conn("collisions",1,"solver",1), _conn("collisions",2,"solver",2), _conn("solver",0,"surface",0), _conn("surface",0,"output",0)),
    ),
    EffectDomainPack(
        "crowd_agents_v1", "Crowd Agents", "crowd",
        (_node("source", "crowdsource", parms=(("agentname", "agenttype"),)), _node("solver", "crowdsolver", "crowdsolver::2.0", input_role="source"), _node("output", "null", input_role="solver")),
        (
            _control("speed", "solver", ("speed", "agentspeed"), 0.0, 100.0),
            _control("avoidance", "solver", ("avoidance", "avoidancescale"), 0.0, 10.0),
            _control("behavior_variation", "solver", ("random", "variation"), 0.0, 10.0),
            _control("animation_blend", "solver", ("blend", "blendtime"), 0.0, 10.0),
        ),
        ("agent_points", "agent_ids", "clip_times", "paths", "collision_events"),
        ("speed_variance", "path_overlap", "animation_phase_entropy", "collision_rate"), True,
    ),
    EffectDomainPack(
        "swarm_flocking_v1", "Swarm Flocking", "swarm",
        (_node('source', 'sphere', category='sop'), _node('simulation', 'dopnet', category='sop'), _node('particle_object', 'popobject', category='dop'), _node('emission', 'popsource::2.0', category='dop'), _node('flock', 'popflock', category='dop'), _node('seek', 'popsteerseek', category='dop'), _node('solver', 'popsolver::2.0', category='dop'), _node('simulation_output', 'output', category='dop'), _node('particle_size', 'attribadjustfloat', category='sop'), _node('instance_source', 'sphere', category='sop'), _node('instances', 'copytopoints::2.0', category='sop'), _node('output', 'null', category='sop')),
        (
            _control('cohesion', 'flock', ('centralforce',), 0.0, 100.0),
            _control('separation', 'flock', ('interactionforce',), 0.0, 100.0),
            _control('alignment', 'flock', ('velmatchforce',), 0.0, 100.0),
            _control('neighbor_radius', 'flock', ('centermaxdist',), 0.001, 10000.0),
            _control('goal_attraction', 'seek', ('forcescale',), 0.0, 100.0),
        ),
        ("agent_points", "velocity", "neighbor_counts", "trajectories", "instanced_geometry"),
        ("cluster_count", "neighbor_variance", "alignment_score", "trajectory_coherence"), True,
        connections=(_conn('source',0,'simulation',0), _conn('particle_object',0,'solver',0), _conn('emission',0,'flock',0), _conn('flock',0,'seek',0), _conn('seek',0,'solver',2), _conn('solver',0,'simulation_output',0), _conn('simulation',0,'particle_size',0), _conn('instance_source',0,'instances',0), _conn('particle_size',0,'instances',1), _conn('instances',0,'output',0)),
    ),
    EffectDomainPack(
        "vellum_cloth_v1", "Vellum Cloth", "cloth",
        (_node("source", "grid"), _node("collision_source", "box"), _node("collision_transform", "xform", input_role="collision_source"), _node("constraints", "vellumconstraints", parms=(("constrainttype", "type"),), input_role="source"), _node("solver", "vellumsolver", input_role="constraints"), _node("output", "null", input_role="solver")),
        (
            _control("stretch_stiffness", "constraints", ("stretchstiffness",), 0.0, 1.0e12),
            _control("bend_stiffness", "constraints", ("bendstiffness",), 0.0, 1.0e12),
            _control("damping", "solver", ("veldamping",), 0.0, 100.0),
            _control("thickness", "constraints", ("thickness",), 0.0, 100.0),
            _control("substeps", "solver", ("substeps", "minsubsteps"), 1.0, 100.0, value_type="int"),
        ),
        ("cloth_mesh", "constraint_geometry", "collision_geometry", "stress", "final_beauty"),
        ("fold_frequency", "stretch_error", "penetration_count", "temporal_jitter"), True,
        connections=(
            _conn("source", 0, "constraints", 0),
            _conn("collision_source", 0, "collision_transform", 0),
            _conn("collision_transform", 0, "solver", 2),
            _conn("constraints", 0, "solver", 0),
            _conn("constraints", 1, "solver", 1),
            _conn("solver", 0, "output", 0),
        )
    ),
    EffectDomainPack(
        "vellum_softbody_grains_v1", "Vellum Softbody and Grains", "softbody_grains",
        (_SOURCE_SPHERE, _node("constraints", "vellumconstraints", parms=(("constrainttype", "type"),), input_role="source"), _node("solver", "vellumsolver", input_role="constraints"), _node("output", "null", input_role="solver")),
        (
            _control("stiffness", "constraints", ("stiffness", "stretchstiffness"), 0.0, 1.0e12),
            _control("cluster_stiffness", "constraints", ("clusterstiffness", "shapestiffness"), 0.0, 1.0e12),
            _control("friction", "solver", ("friction", "dynamicfriction"), 0.0, 10.0),
            _control("damping", "solver", ("dampingratio", "damping"), 0.0, 100.0),
            _control("substeps", "solver", ("substeps", "minsubsteps"), 1.0, 100.0, value_type="int"),
        ),
        ("simulation_geometry", "constraints", "contact_events", "stress", "final_beauty"),
        ("shape_error", "packing_density", "penetration_count", "energy_decay"), True,
        connections=(
            _conn("source", 0, "constraints", 0),
            _conn("constraints", 0, "solver", 0),
            _conn("constraints", 1, "solver", 1),
            _conn("solver", 0, "output", 0),
        )
    ),
    EffectDomainPack(
        "hair_fur_v1", "Hair and Fur", "hair_fur",
        (_SOURCE_SPHERE, _node("guides", "guidegroom", "guidegroom::2.0", input_role="source"), _node("solver", "vellumsolver", input_role="guides"), _node("output", "null", input_role="solver")),
        (
            _control("guide_length", "guides", ("length", "hairlength"), 0.0, 1000.0),
            _control("guide_density", "guides", ("density", "hairdensity"), 0.0, 10000000.0),
            _control("bend_stiffness", "solver", ("bendstiffness", "bend"), 0.0, 1.0e12),
            _control("damping", "solver", ("dampingratio", "damping"), 0.0, 100.0),
            _control("clump", "guides", ("clump", "clumpscale"), 0.0, 10.0, "shaping_meshing"),
        ),
        ("guide_curves", "skin_geometry", "collisions", "hair_id", "final_beauty"),
        ("length_distribution", "clump_frequency", "penetration_count", "temporal_jitter"), True,
    ),
    EffectDomainPack(
        "rbd_destruction_v1", "RBD Destruction", "rbd",
        (_node("source", "box"), _node("fracture", "rbdmaterialfracture", input_role="source"), _node("configure", "rbdconfigure"), _node("solver", "rbdbulletsolver"), _node("output", "null", input_role="solver")),
        (
            _control("fracture_scale", "fracture", ("piecesize", "fracturescale"), 0.001, 1000.0),
            _control("constraint_strength", "solver", ("strength", "constraintstrength"), 0.0, 1.0e12),
            _control("impact_threshold", "solver", ("impactthreshold", "threshold"), 0.0, 1.0e12),
            _control("substeps", "solver", ("substeps", "minsubsteps"), 1.0, 100.0, value_type="int"),
            _control("drag", "solver", ("drag", "airresist"), 0.0, 100.0),
        ),
        ("piece_geometry", "constraints", "piece_ids", "impacts", "velocity", "final_beauty"),
        ("piece_size_distribution", "break_timing", "energy_conservation", "penetration_count"), True,
        connections=(_conn("source",0,"fracture",0), _conn("fracture",0,"configure",0), _conn("fracture",1,"configure",1), _conn("fracture",2,"configure",2), _conn("configure",0,"solver",0), _conn("configure",1,"solver",1), _conn("configure",2,"solver",2), _conn("solver",0,"output",0)),
    ),
    EffectDomainPack(
        "procedural_geometry_v1", "Procedural Geometry", "procedural_geometry",
        (_node("source", "grid"), _node("instance_source", "sphere"), _node("instance_transform", "xform", input_role="instance_source"), _node("scatter", "scatter", "scatter::2.0", input_role="source"), _node("point_variation", "attribadjustfloat", input_role="scatter"), _node("instance", "copytopoints::2.0", "copytopoints"), _node("output", "null", input_role="instance")),
        (
            _control("scatter_density", "scatter", ("npts", "forcecount"), 0.0, 10000000.0, "source_layout_control", "int"),
            _control("seed", "scatter", ("seed", "globalseed"), 0.0, 2147483647.0, "source_layout_control", "int"),
            _control("scale", "instance_transform", ("scale",), 0.0001, 10000.0, "shaping_meshing"),
            _control("variation", "point_variation", ("rangevalue",), 0.0, 100.0, "shaping_meshing"),
        ),
        ("source_geometry", "points", "piece_ids", "final_geometry", "final_beauty"),
        ("count", "spacing_distribution", "scale_distribution", "bounds_similarity"), False,
        connections=(_conn("source", 0, "scatter", 0), _conn("instance_source", 0, "instance_transform", 0), _conn("instance_transform", 0, "instance", 0), _conn("scatter", 0, "point_variation", 0), _conn("point_variation", 0, "instance", 1), _conn("instance", 0, "output", 0)),
    ),
    EffectDomainPack(
        "material_lookdev_v1", "MaterialX Lookdev", "material",
        (_node("material", "mtlxstandard_surface", category="vop", parms=(("base_color", "basecolor"), ("specular_roughness", "rough"))),),
        (
            _control("base_color", "material", ("base_color", "basecolor"), 0.0, 1.0, "material", "color3"),
            _control("roughness", "material", ("specular_roughness", "rough"), 0.0, 1.0, "material"),
            _control("ior", "material", ("specular_ior", "ior"), 1.0, 5.0, "material"),
            _control("transmission", "material", ("transmission", "transmission_weight"), 0.0, 1.0, "material"),
            _control("subsurface", "material", ("subsurface", "subsurface_weight"), 0.0, 1.0, "material"),
        ),
        ("albedo_aov", "normal_aov", "roughness_aov", "specular_aov", "controlled_light_beauty"),
        ("highlight_width", "specular_energy", "color_error", "normal_frequency"), False,
    ),
    EffectDomainPack(
        "lighting_camera_render_v1", "Lighting, Camera and Karma", "lighting_camera_render",
        (_node("camera", "camera", category="lop", parms=(("primpath",),)), _node("light", "domelight", "light", category="lop", input_role="camera"), _node("settings", "karmarendersettings", category="lop", input_role="light"), _node("render", "usdrender_rop", category="lop", input_role="settings")),
        (
            _control("exposure", "light", ("exposure", "light_exposure"), -30.0, 30.0, "lighting_camera"),
            _control("focal_length", "camera", ("focalLength", "focal"), 1.0, 1000.0, "lighting_camera"),
            _control("pixel_samples", "settings", ("pixelsamples", "samplesperpixel"), 1.0, 100000.0, "render", "int"),
            _control("volume_step_rate", "settings", ("volumesteprate", "volume_step_rate"), 0.01, 100.0, "render"),
            _control("denoise", "settings", ("denoise", "usedenoise"), 0.0, 1.0, "render", "bool"),
        ),
        ("raw_beauty", "sample_count", "variance_aov", "depth", "normal"),
        ("noise_variance", "edge_frequency", "exposure_error", "depth_of_field_width"), False,
    ),
    EffectDomainPack(
        "explosion_composite_v1", "Explosion Components", "explosion",
        (_SOURCE_SPHERE, _node("pyro", "pyrosolver", "pyrosolver::2.0", input_role="source"), _node("particles", "popnet", input_role="source"), _node("fracture", "rbdmaterialfracture", input_role="source"), _node("output", "merge", input_role="pyro")),
        (
            _control("fire_energy", "pyro", ("burn", "burnrate"), 0.0, 10.0),
            _control("smoke_dissipation", "pyro", ("dissipation", "dissipationscale"), 0.0, 5.0),
            _control("spark_rate", "particles", ("constantrate", "birthrate"), 0.0, 10000000.0),
            _control("debris_scale", "fracture", ("piecesize", "fracturescale"), 0.001, 1000.0),
            _control("shockwave_scale", "source", ("scale", "uniformscale"), 0.001, 10000.0),
        ),
        ("density_field", "flame_field", "particle_points", "piece_geometry", "component_mattes", "final_beauty"),
        ("component_alignment", "energy_timing", "silhouette_iou", "temporal_coherence"), True,
        component_packs=("pyro_fire_v1", "pyro_smoke_v1", "particles_v1", "rbd_destruction_v1"),
    ),
)


# The shared Causal Doctor owns these public names.  Execution packs may keep
# additional artist-friendly aliases, but every runtime candidate control must
# be accepted by the host validator.  Downstream Nuke controls are present for
# contract parity and explicitly tagged so they are never applied in Houdini.
_RUNTIME_CONTROL_BRIDGE: dict[str, tuple[SemanticControl, ...]] = {
    "pyro_smoke_v1": (
        _control("volume_step_rate", "render_settings", ("volumesteprate", "volume_step_rate"), 0.01, 100.0, "render"),
        _control("denoise_mix", "external_nuke", (), 0.0, 1.0, "composite", application="nuke"),
    ),
    "pyro_fire_v1": (
        _control("fuel_rate", "solver", ("fuel", "fuelrate", "sourcefuel"), 0.0, 1000.0),
        _control("velocity_detail", "solver", ("turbulence", "disturbance", "veldisturbance"), 0.0, 100.0),
        _control("emission_contrast", "external_nuke", (), 0.0, 10.0, "composite", application="nuke"),
    ),
    "particles_v1": (
        _control("emission_variance", "solver", ("emissionvariance", "birthvariance", "variance"), 0.0, 100.0),
        _control("life_variance", "solver", ("lifevariance", "lifevar"), 0.0, 1000.0),
        _control("velocity_variance", "solver", ("velocityvariance", "velvariance"), 0.0, 1000.0),
        _control("force_noise", "solver", ("forcenoise", "noiseamplitude", "amplitude"), 0.0, 1000.0),
        _control("size_variance", "solver", ("sizevariance", "pscalevariance"), 0.0, 100.0, "shaping_meshing"),
    ),
    "water_ocean_v1": (
        _control("spectrum_amplitude", "spectrum", ("ampscale",), 0.0, 100.0),
        _control("directional_spread", "spectrum", ("directionalspread", "directionaldamping", "spread"), 0.0, 360.0),
        _control("crest_threshold", "evaluate", ("crestthreshold", "cuspthreshold"), 0.0, 100.0, "shaping_meshing"),
        _control("foam_amount", "evaluate", ("foamamount", "foamscale", "foam"), 0.0, 100.0, "shaping_meshing"),
    ),
    "water_flip_v1": (
        _control("droplet_scale", "surface", ("surfacedistance",), 0.0, 100.0, "shaping_meshing"),
        _control("meshing_detail", "surface", ("voxelsize",), 0.01, 100.0, "shaping_meshing"),
    ),
    "crowd_agents_v1": (
        _control("speed_variance", "solver", ("speedvariance", "speedvar"), 0.0, 100.0),
        _control("path_variance", "solver", ("pathvariance", "pathnoise"), 0.0, 100.0),
        _control("clip_offset", "solver", ("clipoffset", "timeoffset"), -10000.0, 10000.0),
        _control("avoidance_strength", "solver", ("avoidance", "avoidancescale"), 0.0, 100.0),
        _control("behavior_mix", "solver", ("behaviormix", "blend", "blendtime"), 0.0, 100.0),
    ),
    "swarm_flocking_v1": (
        _control("target_noise", "solver", ("targetnoise", "goalnoise", "noiseamplitude"), 0.0, 100.0),
    ),
    "vellum_softbody_grains_v1": (
        _control("constraint_stiffness", "constraints", ("stiffness", "stretchstiffness"), 0.0, 1.0e12),
        _control("collision_passes", "solver", ("collisionpasses", "maxcollisionpasses"), 1.0, 1000.0, value_type="int"),
    ),
    "hair_fur_v1": (
        _control("collision_radius", "solver", ("collisionradius", "thickness"), 0.0, 100.0),
        _control("clump_strength", "guides", ("clump", "clumpscale", "clumpstrength"), 0.0, 100.0, "shaping_meshing"),
    ),
    "rbd_destruction_v1": (
        _control("fracture_variance", "fracture", ("fracturevariance", "variation", "seed"), 0.0, 100.0),
        _control("impact_spread", "solver", ("impactspread", "propagationiterations"), 0.0, 1000.0),
        _control("piece_scale", "fracture", ("piecesize", "fracturescale"), 0.001, 1000.0),
        _control("velocity_variance", "solver", ("velocityvariance", "velvariance"), 0.0, 1000.0),
    ),
    "procedural_geometry_v1": (
        _control("scatter_variance", "scatter", ("scattervariance", "relaxiterations", "seed"), 0.0, 1000.0, "source_layout_control"),
        _control("scale_variance", "point_variation", ("rangevalue",), 0.0, 100.0, "shaping_meshing"),
        _control("rotation_variance", "instance", ("rotationvariance", "randomrotation"), 0.0, 360.0, "shaping_meshing"),
        _control("deformation", "instance", ("deformation", "deformscale"), 0.0, 100.0, "shaping_meshing"),
        _control("density", "scatter", ("npts", "forcecount", "densityscale"), 0.0, 10000000.0, "source_layout_control"),
    ),
    "material_lookdev_v1": (
        _control("normal_strength", "material", ("normal_strength", "normalstrength", "bump_scale"), 0.0, 100.0, "material"),
        _control("specular_weight", "material", ("specular", "specular_weight"), 0.0, 1.0, "material"),
        _control("coat_weight", "material", ("coat", "coat_weight"), 0.0, 1.0, "material"),
    ),
    "lighting_camera_render_v1": (
        _control("sample_quality", "settings", ("pixelsamples", "samplesperpixel"), 1.0, 100000.0, "render"),
        _control("filter_width", "settings", ("filterwidth", "pixelfilterwidth"), 0.01, 100.0, "render"),
        _control("denoise_mix", "settings", ("denoise", "usedenoise", "denoisemix"), 0.0, 1.0, "render"),
        _control("depth_of_field", "camera", ("fstop", "aperture", "depthoffield"), 0.0, 1000.0, "lighting_camera"),
    ),
    "explosion_composite_v1": (
        _control("fire_scale", "pyro", ("burn", "burnrate", "flamescale"), 0.0, 100.0),
        _control("smoke_scale", "pyro", ("densityscale", "smokeamount"), 0.0, 100.0),
        _control("debris_energy", "fracture", ("debrisenergy", "velocityscale", "impulse"), 0.0, 1000.0),
        _control("comp_contrast", "external_nuke", (), 0.0, 10.0, "composite", application="nuke"),
    ),
}


def _add_runtime_controls(pack: EffectDomainPack) -> EffectDomainPack:
    existing = {control.identifier for control in pack.controls}
    additions = tuple(control for control in _RUNTIME_CONTROL_BRIDGE.get(pack.identifier, ()) if control.identifier not in existing)
    nodes = pack.nodes
    if pack.identifier == "pyro_smoke_v1":
        nodes = nodes + (_node("render_settings", "karmarendersettings", category="lop"),)
    return replace(pack, controls=pack.controls + additions, nodes=nodes)


DOMAIN_PACKS = tuple(_add_runtime_controls(pack) for pack in DOMAIN_PACKS)


_COVERAGE_CONTROL_BRIDGE: dict[str, tuple[SemanticControl, ...]] = {
    "pyro_smoke_v1": (
        _control("source_scale", "source", ("radx", "radius", "scale"), 0.001, 1000.0, "source_layout_control"),
        _control("density_scale", "solver", ("densityscale", "smokeamount"), 0.0, 100.0),
        _control("field_sharpen", "solver", ("sharpen", "sharpening"), 0.0, 100.0),
        _control("simulation_substeps", "solver", ("substeps", "minsubsteps", "timesteps"), 1.0, 100.0, value_type="int"),
        _control("volume_samples", "render_settings", ("volumesamples", "volumequality"), 1.0, 100000.0, "render", "int"),
    ),
    "pyro_fire_v1": (
        _control("temperature_scale", "solver", ("temperaturescale", "temperature"), 0.0, 1000.0),
        _control("flame_height", "solver", ("flameheight", "buoyancylift", "buoyancy"), -100.0, 1000.0),
        _control("emission_intensity", "solver", ("emissionscale", "fireintensity"), 0.0, 10000.0, "material"),
        _control("glow_amount", "external_nuke", (), 0.0, 100.0, "composite", application="nuke"),
    ),
    "particles_v1": (
        _control("force_strength", "solver", ("forcescale", "force", "amplitude"), -10000.0, 10000.0),
        _control("collision_radius", "solver", ("collisionradius", "pscale"), 0.0, 1000.0),
        _control("trail_length", "solver", ("traillength", "trail"), 0.0, 10000.0, "shaping_meshing"),
        _control("motion_blur_scale", "solver", ("motionblurscale", "velocityscale"), 0.0, 100.0, "render"),
        _control("cluster_strength", "solver", ("clusterstrength", "cohesion"), 0.0, 100.0),
    ),
    "water_flip_v1": (
        _control("collision_separation", "solver", ("collisionseparation", "collisionpadding"), 0.0, 100.0),
        _control("collision_passes", "solver", ("collisionpasses", "maxcollisionpasses"), 1.0, 1000.0, value_type="int"),
    ),
    "crowd_agents_v1": (
        _control("route_weight", "solver", ("routeweight", "pathweight"), 0.0, 100.0),
        _control("animation_variation", "solver", ("clipvariation", "animationvariation"), 0.0, 100.0),
        _control("timing_offset", "solver", ("timeoffset", "clipoffset"), -10000.0, 10000.0),
    ),
    "swarm_flocking_v1": (
        _control("noise_strength", "solver", ("noiseamplitude", "noisestrength"), 0.0, 1000.0),
    ),
    "vellum_cloth_v1": (
        _control("collision_thickness", "constraints", ("thickness",), 0.0, 100.0),
        _control("constraint_iterations", "solver", ("niter",), 1.0, 10000.0, value_type="int"),
        _control("wrinkle_scale", "constraints", ("wrinklescale", "restlengthscale"), 0.0, 100.0),
    ),
    "vellum_softbody_grains_v1": (
        _control("grain_size", "constraints", ("particlesize", "grainsize", "pscale"), 0.0001, 1000.0),
        _control("packing", "constraints", ("packing", "packingdensity"), 0.0, 100.0),
        _control("constraint_iterations", "solver", ("niter",), 1.0, 10000.0, value_type="int"),
    ),
    "hair_fur_v1": (
        _control("wind_strength", "solver", ("windstrength", "windscale"), -10000.0, 10000.0),
        _control("hair_width", "guides", ("width", "hairwidth"), 0.00001, 100.0, "shaping_meshing"),
    ),
    "rbd_destruction_v1": (
        _control("activation_frame", "solver", ("activationframe", "startframe"), -100000.0, 100000.0, value_type="int"),
        _control("impulse_scale", "solver", ("impulsescale", "velocityscale"), 0.0, 10000.0),
    ),
    "procedural_geometry_v1": (
        _control("rotation", "instance_transform", ("rz",), -360.0, 360.0, "shaping_meshing"),
    ),
    "material_lookdev_v1": (
        _control("anisotropy", "material", ("specular_anisotropy", "anisotropy"), 0.0, 1.0, "material"),
        _control("displacement_scale", "material", ("displacement", "displacement_scale"), -1000.0, 1000.0, "material"),
        _control("emission_weight", "material", ("emission", "emission_weight"), 0.0, 10000.0, "material"),
    ),
    "lighting_camera_render_v1": (
        _control("motion_blur", "settings", ("motionblur", "enablemotionblur"), 0.0, 1.0, "render", "bool"),
        _control("shutter", "camera", ("shutter", "shuttertime"), 0.0, 10.0, "lighting_camera"),
        _control("light_size", "light", ("areasize", "radius", "size"), 0.0, 10000.0, "lighting_camera"),
    ),
    "explosion_composite_v1": (
        _control("shockwave_thickness", "source", ("thickness", "radius"), 0.0, 1000.0),
        _control("debris_amount", "fracture", ("piececount", "fracturecount"), 0.0, 1000000.0, value_type="int"),
    ),
}


_COVERAGE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "particles_v1": ("force_debug", "collision_events", "trail_geometry", "motion_vectors"),
    "material_lookdev_v1": ("normal_aov", "displacement_aov", "anisotropy_aov", "emission_aov"),
    "lighting_camera_render_v1": ("motion_vectors", "filter_response", "denoise_residual", "volume_step_comparison"),
    "vellum_cloth_v1": ("penetration_events", "bend_stress"),
    "water_flip_v1": ("collision_events", "droplet_ids"),
}


def _add_coverage_controls(pack: EffectDomainPack) -> EffectDomainPack:
    existing = {control.identifier for control in pack.controls}
    additions = tuple(control for control in _COVERAGE_CONTROL_BRIDGE.get(pack.identifier, ()) if control.identifier not in existing)
    evidence = pack.evidence + tuple(item for item in _COVERAGE_EVIDENCE.get(pack.identifier, ()) if item not in pack.evidence)
    return replace(pack, controls=pack.controls + additions, evidence=evidence)


DOMAIN_PACKS = tuple(_add_coverage_controls(pack) for pack in DOMAIN_PACKS)


def _native_render_pack(pack):
    if pack.identifier not in {"material_lookdev_v1", "lighting_camera_render_v1"}:
        return pack
    from .native_render_domains import node_requirements, connection_requirements, control_contract
    version = "21.0.631"
    native_controls = control_contract(pack.identifier,version)
    nodes = tuple(NodeRequirement(n["role"],n["category"],tuple(n["types"]),tuple(tuple(a) for a in n["required_parms"]),
                       n.get("input_role"),n.get("parent_role") or ("usd_network" if n["category"] == "lop" else "render_network" if n["category"] == "rop" else None))
                  for n in node_requirements(pack.identifier,version))
    controls = tuple(replace(c,node_role=native_controls[c.identifier]["role"],parameter_aliases=tuple(native_controls[c.identifier]["aliases"]),value_type=native_controls[c.identifier]["value_type"]) for c in pack.controls)
    connections = tuple(GraphConnection(w["source_role"],w.get("source_output"),w["destination_role"],w.get("destination_input"),
                              w.get("source_output_name"),w.get("destination_input_name")) for w in connection_requirements(pack.identifier,version))
    return replace(pack,nodes=nodes,controls=controls,connections=connections)


DOMAIN_PACKS = tuple(_native_render_pack(pack) for pack in DOMAIN_PACKS)


_BY_ID = {pack.identifier: pack for pack in DOMAIN_PACKS}


def all_domain_packs() -> tuple[EffectDomainPack, ...]:
    return DOMAIN_PACKS


def get_domain_pack(identifier: str) -> EffectDomainPack:
    try:
        return _BY_ID[str(identifier)]
    except KeyError as exc:
        raise ValueError("unsupported Houdini effect domain pack: {}".format(identifier)) from exc


def pack_catalog() -> list[dict[str, Any]]:
    return [pack.to_dict() for pack in DOMAIN_PACKS]


def validate_candidate_patch(pack: EffectDomainPack, patch: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one bounded semantic patch without allowing raw parameters."""
    if not isinstance(patch, Mapping):
        raise ValueError("candidate patch must be an object")
    if len(patch) > 5:
        raise ValueError("candidate patch may change at most five semantic controls")
    controls = {control.identifier: control for control in pack.controls}
    normalized: dict[str, Any] = {}
    for name, raw_value in patch.items():
        control = controls.get(str(name))
        if control is None:
            raise ValueError("unsupported semantic control for {}: {}".format(pack.identifier, name))
        if control.value_type == "color3":
            if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 3:
                raise ValueError("{} must be an RGB triple".format(name))
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in raw_value):
                raise ValueError("{} must contain finite numeric channels".format(name))
            value = [float(item) for item in raw_value]
            if any(item < control.minimum or item > control.maximum for item in value):
                raise ValueError("{} is outside the supported range".format(name))
        elif control.value_type == "bool":
            if not isinstance(raw_value, (bool, int)) or int(raw_value) not in (0, 1):
                raise ValueError("{} must be boolean".format(name))
            value = bool(raw_value)
        elif control.value_type == "int":
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError("{} must be an integer".format(name))
            value = raw_value
            if value < control.minimum or value > control.maximum:
                raise ValueError("{} is outside the supported range".format(name))
        else:
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(float(raw_value)):
                raise ValueError("{} must be finite numeric".format(name))
            value = float(raw_value)
            if value < control.minimum or value > control.maximum:
                raise ValueError("{} is outside the supported range".format(name))
        normalized[str(name)] = value
    return normalized
