"""Approved B product inputs and metadata; no native graph or write plan."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from itertools import permutations

from .product_control_definitions import (
    COMMON_CAPTURE_REQUIREMENTS,
    COMMON_RULES,
    DECISION_RECORD,
    PROPOSAL_SHA256,
)

PACK_ID = "explosion_composite_v1"
SCHEMA = "bridge.product-composite-definitions/1"
_INHERITED = {
    "fire_energy": ("fire", "pyro_fire_v1", "burn_rate"),
    "fire_scale": ("fire", "pyro_fire_v1", "fuel_rate"),
    "smoke_dissipation": ("smoke", "pyro_smoke_v1", "dissipation"),
    "smoke_scale": ("smoke", "pyro_smoke_v1", "density_scale"),
    "spark_rate": ("particles", "particles_v1", "birth_rate"),
    "debris_scale": ("rbd", "rbd_destruction_v1", "fracture_scale"),
    "debris_energy": ("rbd", "rbd_destruction_v1", "velocity_variance"),
}
_LABELS = {
    "fire_energy": "Flame depletion rate",
    "fire_scale": "Source flame input rate",
    "smoke_dissipation": "Smoke dissipation",
    "smoke_scale": "Density input rate",
    "spark_rate": "Expected particle births per second",
    "debris_scale": "Target primary fragment length",
    "debris_energy": "Initial per-axis random velocity amplitude",
}
_SHOCKWAVE_INPUTS = [
    "shockwave.source_reference", "shockwave.source_dimensions_su",
    "shockwave.center_su", "shockwave.transform",
    "shockwave.radius_trajectory.function_reference",
    "shockwave.radius_trajectory.time_interval_seconds",
    "shockwave.radius_trajectory.minimum_radius_su",
    "shockwave.geometry_budget", "shockwave.estimated_geometry_elements",
]
_DEBRIS_INPUTS = [
    "debris.source_reference", "debris.source_dimensions_su", "debris.parents",
    "debris.task_seed", "debris.control_subseed", "debris.instances",
    "debris.instance_budget",
]
_RBD_INPUTS = {
    "debris_scale": [
        "source_dimensions_su", "closed_source_volume_su3", "piece_ids",
        "fragment_budget", "estimated_fragment_count", "material_reference",
        "packing_reference", "constraints_reference",
    ],
    "debris_energy": [
        "pieces", "coordinate_space", "task_seed", "control_subseed",
        "activation_time_seconds", "fps", "time_scale",
    ],
}
_OWNED = {
    "shockwave_scale": {
        "unit": "dimensionless multiplier", "display_label": "Owned spherical shell scale",
        "definition": "Positive uniform multiplier about the trusted shell center; scale both radius and radial thickness. One preserves the owned spherical shell source.",
        "zero": "Reject.", "negative": "Reject.",
        "scope": "Owned spherical shell only, with frozen center/transform and explicit radius time function; no arbitrary geometry instance establishes a shockwave.",
        "required_basis": _SHOCKWAVE_INPUTS + ["controls.shockwave_thickness"],
        "existing_route": {"branch": "shockwave", "control": "scale"},
        "capture_blockers": ["owned spherical shell source and meta branch binding", "versioned editable shell operators, ports and center/transform/radius-time consumption"],
    },
    "shockwave_thickness": {
        "unit": "SU before uniform scale", "display_label": "Full radial shell thickness",
        "definition": "Full radial thickness t before scale: inner=radius-t/2, outer=radius+t/2. Existing uniform scale multiplies both radius and thickness.",
        "zero": "Surface without added thickness.", "negative": "Reject; also reject inner radius <= 0 throughout the supplied time interval.",
        "scope": "Owned spherical shell only; no collision-thickness alias. There is currently no registered meta route for this control.",
        "required_basis": _SHOCKWAVE_INPUTS + ["controls.shockwave_scale"],
        "existing_route": None,
        "capture_blockers": ["registered meta route for shockwave_thickness", "versioned legal shell/thickness operators, ports and actual readback"],
    },
    "debris_amount": {
        "unit": "integer total secondary geometry instances", "display_label": "Secondary geometry debris count",
        "definition": "Exact total 0..1000000, sampled by rest-parent surface area using fixed IDs, task seed, independent control sub-seed and local anchors; consume registered parent transforms. Independent of R01 primary fracture scale.",
        "zero": "Generate no secondary debris; source/sampling inputs are unnecessary for this empty product result.",
        "negative": "Reject; reject fractional counts and budget excess without rounding or truncation.",
        "scope": "Follow primary RBD pieces with secondary geometry only; add no independent physical solver, constraints or collisions. Preserve unrelated artist fields.",
        "required_basis": _DEBRIS_INPUTS,
        "existing_route": {"branch": "rbd", "control": "debris_amount"},
        "capture_blockers": ["rbd.debris_amount is not a native control contract", "versioned legal generation/rest-area sampling and exact-count graph", "stable IDs/local anchors, source dimensions, registered parent transforms and their downstream consumption"],
    },
    "comp_contrast": {
        "unit": "existing Nuke contrast control", "display_label": "Composite contrast",
        "definition": "Inherit the existing Nuke composite_patch contrast contract and 0..10 range; no new alias or color transform.",
        "zero": "Inherit the existing Nuke contrast endpoint; actual knob behavior still requires capture.",
        "negative": "Reject.",
        "scope": "Nuke composite_patch; require registered upstream artifacts and color/channel/premultiplication context.",
        "required_basis": ["composite_binding"],
        "existing_route": {"operation": "composite_patch", "control": "contrast"},
        "capture_blockers": ["Nuke 17.0v1 machine knob and color/channel/premultiplication facts", "registered upstream artifact dependencies and actual input consumption"],
    },
}


class ProductCompositeInputError(ValueError):
    def __init__(self, code, detail, *, missing_inputs=()):
        self.code = code
        self.missing_inputs = tuple(missing_inputs)
        super().__init__(f"{code}: {detail}")


def product_control_contract(version="21.0.631"):
    from . import native_flip_rbd_domains, native_particle_ocean_geometry_domains, native_pyro_domains

    modules = {
        "pyro_fire_v1": native_pyro_domains, "pyro_smoke_v1": native_pyro_domains,
        "particles_v1": native_particle_ocean_geometry_domains,
        "rbd_destruction_v1": native_flip_rbd_domains,
    }
    native_pyro_domains.control_contract("pyro_fire_v1", version)
    definitions = copy.deepcopy(_OWNED)
    for name, (branch, domain, control) in _INHERITED.items():
        inherited = modules[domain].control_contract(domain, version)[control]
        metadata = copy.deepcopy(inherited.get("product_definition", {}))
        metadata.update(
            display_label=_LABELS[name],
            unit=metadata.get("unit", inherited.get("unit", "existing smoke dissipation control")),
            definition=metadata.get("definition", f"Inherit {domain}.{control}, including its existing zero endpoint and gates."),
            zero=metadata.get("zero", "Inherit the routed domain endpoint and its native endpoint blockers."),
            negative="Reject.",
            scope=metadata.get("scope", f"Frozen {branch} branch only; preserve unrelated controls."),
            required_basis=metadata.get("required_basis", []) + [f"branch_bindings.{branch}"],
            capture_blockers=metadata.get("capture_blockers", []) + ["frozen meta-to-domain binding and actual artifact dependency consumption"],
            inherited_from={"domain": domain, "control": control, "version": version},
            inherited_contract=copy.deepcopy(inherited),
            existing_route={"branch": branch, "control": control},
        )
        if name in _RBD_INPUTS:
            metadata["required_product_inputs"] = [f"inherited_basis.{name}.{key}" for key in _RBD_INPUTS[name]]
        definitions[name] = metadata
    for definition in definitions.values():
        definition.update(
            decision_id="B", proposal_sha256=PROPOSAL_SHA256,
            decision_record=DECISION_RECORD, approved_sections=[5],
            common_rules=copy.deepcopy(COMMON_RULES),
            common_capture_requirements=copy.deepcopy(COMMON_CAPTURE_REQUIREMENTS),
            implementation_status="blocked",
        )
    return definitions


def overlay_core_pack_dict(pack, version="21.0.631"):
    result = copy.deepcopy(pack)
    if result["id"] != PACK_ID:
        return result
    definitions = product_control_contract(version)
    for control in result["controls"]:
        control.update(product_status="approved", product_definition=definitions[control["id"]])
    result.update(product_composite_schema=SCHEMA, product_input_contract={
        "validator": "houdini_bridge.product_composite_definitions.validate_product_inputs",
        "input_freeze": "frozen_input_sha256 is SHA-256 of canonical JSON inputs excluding that key; this binds supplied product inputs, not native provenance or registry truth.",
        "radius_trajectory": "Explicit function_reference, time_interval_seconds and declared conservative minimum_radius_su for the entire interval; no inferred radius, interpolation or extrapolation. Native consumption and the declared bound remain unverified.",
        "debris_parents": "Nonempty parents: id, rest_surface_area_su2 and registered transform_reference. Instances: unique id, parent_id, local_anchor_su. Actual sampling and transform registration remain unverified.",
        "native_status": "blocked",
        "native_execution": False,
    })
    return result


def _fail(detail):
    raise ProductCompositeInputError("INVALID_COMPOSITE_PRODUCT_INPUT", detail)


def _lookup(inputs, path):
    value = inputs
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _number(value, path, *, positive=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path + " must be numeric")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (positive and value <= 0) or (integer and not isinstance(value, int)):
        _fail(path + " has an invalid finite value/type/sign")
    return value


def _vector(value, path, *, size=3, positive=False):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        _fail(path + f" must contain {size} components")
    for component in value:
        _number(component, path, positive=positive)


def _reference(value, path):
    if not isinstance(value, str) or not value.strip():
        _fail(path + " must be an explicit reference")


def _validate_shockwave(controls, shell):
    _reference(shell["source_reference"], "shockwave.source_reference")
    _vector(shell["source_dimensions_su"], "shockwave.source_dimensions_su", positive=True)
    _vector(shell["center_su"], "shockwave.center_su")
    _vector(shell["transform"], "shockwave.transform", size=16)
    matrix = shell["transform"]
    determinant = 0
    try:
        for permutation in permutations(range(4)):
            inversions = sum(permutation[first] > permutation[second] for first in range(4) for second in range(first + 1, 4))
            product = math.prod(matrix[row * 4 + permutation[row]] for row in range(4))
            determinant += (-1 if inversions % 2 else 1) * product
    except OverflowError:
        _fail("shockwave.transform determinant arithmetic overflow")
    _number(determinant, "shockwave.transform determinant")
    if determinant == 0:
        _fail("shockwave.transform must be nonsingular with a finite determinant")
    trajectory = shell["radius_trajectory"]
    _reference(trajectory["function_reference"], "shockwave.radius_trajectory.function_reference")
    interval = trajectory["time_interval_seconds"]
    _vector(interval, "shockwave.radius_trajectory.time_interval_seconds", size=2)
    if interval[0] >= interval[1]:
        _fail("radius trajectory time interval must increase")
    radius = _number(trajectory["minimum_radius_su"], "minimum_radius_su", positive=True)
    thickness = controls["shockwave_thickness"]
    if radius - thickness / 2 <= 0:
        _fail("shockwave inner radius must remain positive before scale")
    scale = controls["shockwave_scale"]
    scaled_inner = (radius - thickness / 2) * scale
    scaled_outer = (radius + thickness / 2) * scale
    _number(scaled_inner, "shockwave scaled inner radius", positive=True)
    _number(scaled_outer, "shockwave scaled outer radius", positive=True)
    budget = _number(shell["geometry_budget"], "shockwave.geometry_budget", integer=True)
    estimated = _number(shell["estimated_geometry_elements"], "shockwave.estimated_geometry_elements", integer=True)
    if budget < 0 or estimated < 0 or estimated > budget:
        _fail("shockwave geometry budget exceeded or invalid")


def _validate_debris(amount, debris):
    _reference(debris["source_reference"], "debris.source_reference")
    _vector(debris["source_dimensions_su"], "debris.source_dimensions_su", positive=True)
    for key in ("task_seed", "control_subseed", "instance_budget"):
        _number(debris[key], "debris." + key, integer=True)
    if debris["instance_budget"] < amount:
        _fail("debris instance budget exceeded")
    parents = debris["parents"]
    if not isinstance(parents, (list, tuple)) or not parents:
        _fail("debris.parents must be nonempty")
    parent_ids = set()
    for parent in parents:
        if not isinstance(parent, Mapping):
            _fail("debris parent must be an object")
        _reference(parent.get("id"), "parent.id")
        _reference(parent.get("transform_reference"), "parent.transform_reference")
        _number(parent.get("rest_surface_area_su2"), "parent.rest_surface_area_su2", positive=True)
        if parent["id"] in parent_ids:
            _fail("duplicate debris parent identity")
        parent_ids.add(parent["id"])
    instances = debris["instances"]
    if not isinstance(instances, (list, tuple)) or len(instances) != amount:
        _fail("debris instances must have the exact requested total")
    identities = set()
    for instance in instances:
        if not isinstance(instance, Mapping):
            _fail("debris instance must be an object")
        _reference(instance.get("id"), "instance.id")
        _reference(instance.get("parent_id"), "instance.parent_id")
        if instance["id"] in identities or instance["parent_id"] not in parent_ids:
            _fail("duplicate debris identity or unknown parent")
        identities.add(instance["id"])
        _vector(instance.get("local_anchor_su"), "instance.local_anchor_su")


def _identities(values, path):
    if not isinstance(values, (list, tuple)) or not values:
        _fail(path + " must contain stable identities")
    for value in values:
        _reference(value, path)
    if len(set(values)) != len(values):
        _fail(path + " contains duplicate identities")


def _validate_rbd_basis(name, basis):
    if name == "debris_scale":
        _vector(basis["source_dimensions_su"], name + ".source_dimensions_su", positive=True)
        _number(basis["closed_source_volume_su3"], name + ".closed_source_volume_su3", positive=True)
        _identities(basis["piece_ids"], name + ".piece_ids")
        for key in ("material_reference", "packing_reference", "constraints_reference"):
            _reference(basis[key], name + "." + key)
        budget = _number(basis["fragment_budget"], name + ".fragment_budget", integer=True)
        estimated = _number(basis["estimated_fragment_count"], name + ".estimated_fragment_count", integer=True)
        if budget < 0 or estimated < 0 or estimated > budget:
            _fail("R01 fragment budget exceeded or invalid")
    else:
        _reference(basis["coordinate_space"], name + ".coordinate_space")
        for key in ("task_seed", "control_subseed"):
            _number(basis[key], name + "." + key, integer=True)
        for key in ("fps", "time_scale"):
            _number(basis[key], name + "." + key, positive=True)
        _number(basis["activation_time_seconds"], name + ".activation_time_seconds")
        pieces = basis["pieces"]
        if not isinstance(pieces, (list, tuple)) or not pieces:
            _fail("R05 requires pieces with baseline velocities")
        identities = []
        for piece in pieces:
            if not isinstance(piece, Mapping):
                _fail("R05 piece must be an object")
            identities.append(piece.get("id"))
            _vector(piece.get("v_base_su_per_second"), "R05 baseline velocity")
        _identities(identities, "R05 piece IDs")


def validate_product_inputs(controls, inputs, *, version="21.0.631"):
    """Validate declarations only; return blocked native status even if complete."""
    from .domain_packs import get_domain_pack, validate_candidate_patch

    definitions = product_control_contract(version)
    if not isinstance(controls, Mapping) or not controls or not isinstance(inputs, Mapping):
        _fail("nonempty controls and object inputs are required")
    pack = get_domain_pack(PACK_ID)
    normalized = {}
    for name, value in controls.items():
        try:
            normalized.update(validate_candidate_patch(pack, {name: value}))
        except (ValueError, OverflowError) as exc:
            _fail(str(exc))
    required = []
    for name in normalized:
        if name in _INHERITED:
            branch = _INHERITED[name][0]
            required.append(f"branch_bindings.{branch}")
            if name in ("debris_scale", "debris_energy"):
                required.extend(f"inherited_basis.{name}.{key}" for key in _RBD_INPUTS[name])
        elif name.startswith("shockwave_"):
            required.extend(_SHOCKWAVE_INPUTS)
        elif name == "debris_amount" and normalized[name] > 0:
            required.extend(_DEBRIS_INPUTS)
        elif name == "comp_contrast":
            required.append("composite_binding")
    if "shockwave_thickness" in normalized:
        required.append("controls.shockwave_scale")
    if "shockwave_scale" in normalized:
        required.append("controls.shockwave_thickness")
    if required:
        required.append("frozen_input_sha256")
    values = {**inputs, "controls": normalized}
    missing = sorted({path for path in required if _lookup(values, path) is None})
    if missing:
        raise ProductCompositeInputError("MISSING_COMPOSITE_PRODUCT_INPUT", ", ".join(missing), missing_inputs=missing)
    if required:
        supplied_digest = inputs["frozen_input_sha256"]
        payload = {key: value for key, value in inputs.items() if key != "frozen_input_sha256"}
        try:
            actual_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        except (TypeError, ValueError) as exc:
            _fail("inputs must be finite JSON: " + str(exc))
        if supplied_digest != actual_digest:
            _fail("frozen_input_sha256 does not bind the supplied inputs")
    for name in normalized:
        if name in _INHERITED:
            branch, domain, control = _INHERITED[name]
            binding = inputs["branch_bindings"][branch]
            if not isinstance(binding, Mapping) or binding.get("domain") != domain:
                _fail(f"branch_bindings.{branch} must bind {domain}")
            _reference(binding.get("task_reference"), f"branch_bindings.{branch}.task_reference")
            if name in ("debris_scale", "debris_energy"):
                basis = inputs["inherited_basis"][name]
                _validate_rbd_basis(name, basis)
        elif name == "comp_contrast":
            _reference(inputs["composite_binding"], "composite_binding")
    if any(name.startswith("shockwave_") for name in normalized):
        _validate_shockwave(normalized, inputs["shockwave"])
    if normalized.get("debris_amount", 0) > 0:
        _validate_debris(normalized["debris_amount"], inputs["debris"])
    return {
        "schema": SCHEMA, "product_input_status": "validated", "controls": normalized,
        "native_status": "blocked", "native_execution": False,
        "capture_blockers": {name: copy.deepcopy(definitions[name]["capture_blockers"]) for name in normalized},
        "evidence_boundary": "Only supplied product declarations were checked; trust, radius bounds, area sampling, local surface membership, registered transforms, native consumption and readback are unverified.",
    }
