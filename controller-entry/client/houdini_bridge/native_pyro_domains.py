"""Trusted Pyro plans consumed by the existing host generator and transactions.

No HOM calls, node creation, task state or execution occurs here. Static plans
require runtime type, menu, gate, ownership and readback checks in the host.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import hashlib
import math
from typing import Any, Mapping

from .product_control_definitions import annotate_control_contract

SUPPORTED_VERSIONS = ("21.0.631", "22.0.429")
SMOKE = "pyro_smoke_v1"
FIRE = "pyro_fire_v1"
SCHEMA = "bridge.native-pyro-domains/1"
PROGRAM_GENERATOR = "houdini_bridge.native_pyro_domains.source_program/1"
BURN_CONTRACT = "normalized_flame_depletion_per_second/1"
SHARPEN_CONTRACT = "normalized_vendor_stencil_strength/1"
VOLUME_SAMPLES_CONTRACT = "normalized_secondary_volume_samples/1"


class NativePyroDomainError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _domain(pack_id, version):
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        raise NativePyroDomainError("UNSUPPORTED_NATIVE_VERSION", str(version))
    if pack_id not in (SMOKE, FIRE):
        raise NativePyroDomainError("UNSUPPORTED_PYRO_DOMAIN", str(pack_id))


# role, exact machine parm, minimum, maximum, public type, invalidation phase
_SMOKE = {
    "voxel_size": ("solver", "divsize", .005, 1., "float", "generation_simulation"),
    "disturbance": ("solver", "disturbance", 0., 10., "float", "generation_simulation"),
    "shredding": ("solver", "shredding", 0., 10., "float", "generation_simulation"),
    "dissipation": ("solver", "dissipation", 0., 5., "float", "generation_simulation"),
    "turbulence": ("solver", "turbulence", 0., 10., "float", "generation_simulation"),
    "volume_step_rate": ("render_settings", "volumesteprate", .01, 100., "float", "render"),
    "denoise_mix": ("external_nuke", None, 0., 1., "float", "composite"),
    "source_scale": ("source", "rad", .001, 1000., "float", "source_layout_control"),
    "density_scale": ("solver", "source_vscale1", 0., 100., "float", "source_layout_control"),
    "field_sharpen": ("field_sharpen", "convolvezz5", 0., 100., "float", "shaping_meshing"),
    "simulation_substeps": ("solver", "substeps", 1., 100., "int", "generation_simulation"),
    "volume_samples": ("render_settings", "volumequality", 1., 100000., "int", "render"),
}
_FIRE = {
    "voxel_size": ("solver", "divsize", .005, 1., "float", "generation_simulation"),
    "burn_rate": ("solver", "flames_lifespan", 0., 10., "float", "generation_simulation"),
    "cooling_rate": ("solver", "tempcooling", 0., 10., "float", "generation_simulation"),
    "flame_disturbance": ("solver", "disturbance", 0., 10., "float", "generation_simulation"),
    "flame_lift": ("solver", "buoyancylift", -10., 10., "float", "generation_simulation"),
    "fuel_rate": ("solver", "source_vscale3", 0., 1000., "float", "source_layout_control"),
    "velocity_detail": ("solver", "turbulence", 0., 100., "float", "generation_simulation"),
    "emission_contrast": ("external_nuke", None, 0., 10., "float", "composite"),
    "temperature_scale": ("solver", "source_vscale2", 0., 1000., "float", "source_layout_control"),
    "flame_height": ("flame_height", "snippet", -100., 1000., "float", "generation_simulation"),
    "emission_intensity": ("solver", "fi_int", 0., 10000., "float", "material"),
    "glow_amount": ("external_nuke", None, 0., 100., "float", "composite"),
}
_GATES = {
    "disturbance": (("solver", "enable_disturbance", 1),),
    "flame_disturbance": (("solver", "enable_disturbance", 1),),
    "shredding": (("solver", "enable_shredding", 1),),
    "dissipation": (("solver", "enable_dissipation", 1),),
    "turbulence": (("solver", "enable_turbulence", 1),),
    "velocity_detail": (("solver", "enable_turbulence", 1),),
    "flame_lift": (("solver", "enable_buoyancy", 1),),
    "burn_rate": (("solver", "addflamefield", 1),),
    "emission_intensity": (("solver", "fi_enable", 1),),
}
_BLOCKERS = {}


def _specs(pack_id):
    return _SMOKE if pack_id == SMOKE else _FIRE


@versioned_controls
def control_contract(pack_id: str, version: str) -> dict:
    _domain(pack_id, version)
    result = {}
    for name, (role, parm, lo, hi, kind, phase) in _specs(pack_id).items():
        result[name] = {"role": role, "aliases": [parm] if parm else [],
                        "minimum": lo, "maximum": hi, "value_type": kind,
                        "invalidates_from": phase, "application": "nuke" if role == "external_nuke" else "houdini",
                        "native_conversion": name, "required_gates": list(_GATES.get(name, ())),
                        "native_status": "external" if role == "external_nuke" else "blocked" if name in _BLOCKERS else "mapped"}
        if name in _BLOCKERS:
            result[name]["blocker"] = _BLOCKERS[name]
    result["voxel_size"]["targets"] = [("solver", "divsize"), ("source_volume", "voxelsize")]
    if pack_id == SMOKE:
        result["source_scale"].update(unit="scene units radius", native_size=3, forward="(radius,radius,radius)")
        result["density_scale"].update(unit="density field units per solver second", required_gates=_source_gates(1, "density"))
        result["field_sharpen"].update(semantic_contract=SHARPEN_CONTRACT, required_gates=[("solver", "conv_vdb", 0), ("field_sharpen", "normalize", 1)],
            targets=[("field_sharpen", p) for p in ("convolvezm", "convolvezz", "convolvezp")], unit="dimensionless stencil strength")
        result["shredding"]["required_gates"].append(("solver", "shredding_field", "density"))
        result["turbulence"]["required_gates"].append(("solver", "turbulence_influencefield", "density"))
        result["volume_samples"].update(semantic_contract=VOLUME_SAMPLES_CONTRACT,
            unit="indirect volume secondary samples with normalized base min=max=1",
            targets=[("render_settings", p) for p in ("varianceaa_minsamples", "varianceaa_maxsamples", "volumequality")],
            required_gates=[("render_settings", "engine", "cpu"), ("render_settings", "convergence_mode", "Variance"),
                            ("render_settings", "varianceaa_minsamples", 1), ("render_settings", "varianceaa_maxsamples", 1)],
            forward="base min=max=1; volumequality=float(samples)", inverse="base min=max=1; samples=int(volumequality)",
            renderer_support=["Karma CPU Variance"], existing_base_policy="require actual min=max=1; reject before writes otherwise")
    else:
        result["flame_height"].update(semantic_contract="signed_source_top_flame_envelope/1",
            unit="SU", requires_context="frozen_basis_and_runtime_graph",
            evidence_scope="parameters_only", native_conversion="trusted_height_program",
            required_gates=[("flame_height", name, value) for name, value in
                (("group", "@name=flame"), ("bindeach", 0), ("exportlist", "flame"),
                 ("autobind", 1), ("vex_outputmask", "flame"),
                 ("vex_geometrygenerator", 0), ("vex_precision", "64"))])
        result["burn_rate"].update(semantic_contract=BURN_CONTRACT, unit="normalized flame units per second",
            forward="lifespan=1/rate", inverse="rate=1/lifespan", zero_blocker="ZERO_FLAME_DEPLETION_NATIVE_TARGET_NOT_CAPTURED")
        result["fuel_rate"].update(unit="normalized reactant flame units per solver second", required_gates=_source_gates(3, "flame"))
        result["temperature_scale"].update(unit="temperature field units per solver second", required_gates=_source_gates(2, "temperature"))
        result["velocity_detail"]["required_gates"].append(("solver", "turbulence_influencefield", "temperature"))
        result["emission_intensity"]["unit"] = "native fire emission multiplier"
    return annotate_control_contract(pack_id, result)


def _source_gates(index, name):
    return [("solver", "source_activate" + str(index), 1),
            ("solver", "source_voperator" + str(index), "add"),
            ("solver", "source_volume" + str(index), name),
            ("solver", "source_vfield" + str(index), name),
            ("solver", "source_vnormalize" + str(index), 1)]


def _number(value, lo, hi, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi or not math.isfinite(value) or (integer and int(value) != value):
        raise NativePyroDomainError("INVALID_NATIVE_CONTROL_VALUE", name)
    return int(value) if integer else float(value)


def _write(role, parm, value, native_type="float", phase="value", **extra):
    return {"role": role, "parm": parm, "value": value, "native_type": native_type,
            "phase": phase, "require_writable": True, "require_readback": True, **extra}


def _stencil(strength):
    outer = [0., -.1, 0., -.1, -1., -.1, 0., -.1, 0.]
    center = [-.1, -1., -.1, -1., 0., -1., -.1, -1., -.1]
    a = [v * strength for v in outer]
    b = [v * strength for v in center]
    b[4] = 1 - (sum(a) * 2 + sum(b))
    return a, b, list(a)


def control_write_plan(pack_id: str, control: str, value: Any, version: str, *, height_context=None) -> list[dict]:
    contract = control_contract(pack_id, version)
    if control not in contract:
        raise NativePyroDomainError("UNKNOWN_NATIVE_CONTROL", control)
    c = contract[control]
    value = _number(value, c["minimum"], c["maximum"], control, c["value_type"] == "int")
    if c["native_status"] == "external":
        raise NativePyroDomainError("EXTERNAL_NUKE_CONTROL_REQUIRED", control)
    if c["native_status"] == "blocked":
        raise NativePyroDomainError(c["blocker"], control)
    if control == "flame_height":
        from .native_pyro_height_program import control_write_plan as height_plan
        return height_plan(version, value, height_context)
    if control == "burn_rate":
        if value == 0:
            raise NativePyroDomainError(c["zero_blocker"], control)
        lifespan = 1 / value
        if not math.isfinite(lifespan):
            raise NativePyroDomainError("INVALID_NATIVE_CONTROL_VALUE", "burn_rate reciprocal must be finite")
        writes = [_write(c["role"], c["aliases"][0], lifespan)]
    elif control == "voxel_size":
        writes = [_write(role, parm, value) for role, parm in c["targets"]]
    elif control == "volume_samples":
        writes = [_write("render_settings", "varianceaa_minsamples", 1, "integer"),
                  _write("render_settings", "varianceaa_maxsamples", 1, "integer"),
                  _write("render_settings", "volumequality", float(value))]
    elif control == "source_scale":
        writes = [_write("source", "rad", [value] * 3, "float_tuple", size=3)]
    elif control == "field_sharpen":
        writes = [_write("field_sharpen", parm, values, "float_tuple", size=9)
                  for parm, values in zip(("convolvezm", "convolvezz", "convolvezp"), _stencil(value))]
    else:
        writes = [_write(c["role"], c["aliases"][0], value, "integer" if c["value_type"] == "int" else "float")]
    for item in writes:
        item["required_gates"] = copy.deepcopy(c["required_gates"])
        item["invalidates_from"] = c["invalidates_from"]
    return writes


def candidate_write_plan(pack_id: str, controls: Mapping[str, Any], version: str, *, height_context=None) -> list[dict]:
    writes = []; values = {}
    for name, value in controls.items():
        for item in control_write_plan(pack_id, name, value, version, height_context=height_context):
            key = (item["role"], item["parm"])
            if key in values and values[key] != item["value"]:
                raise NativePyroDomainError("CONFLICTING_NATIVE_CONTROLS", "/".join(key))
            if key not in values:
                writes.append(item); values[key] = item["value"]
    return writes


def _node(role, typ, input_role=None, parms=()):
    return {"role": role, "category": "sop", "types": [typ], "input_role": input_role,
            "required_parms": [[p] for p in parms]}


def node_requirements(pack_id: str, version: str) -> list[dict]:
    _domain(pack_id, version)
    nodes = [_node("source", "sphere", parms=("rad",)),
             _node("source_points", "pyrosource", "source", ("mode", "particlesep", "attributes", "attribute#", "fval#")),
             _node("source_control", "attribwrangle", "source_points", ("class", "group", "snippet")),
             _node("source_volume", "volumerasterizeattributes", "source_control", ("attributes", "voxelsize")),
             _node("solver", "pyrosolver", "source_volume", ("divsize", "numsources", "source_activate#", "source_voperator#", "source_rank#", "source_volume#", "source_vfield#", "source_vscale#", "source_vnormalize#"))]
    if pack_id == SMOKE:
        nodes.extend([_node("field_sharpen", "volumeconvolve3", "solver", ("group", "convolvezm", "convolvezz", "convolvezp", "normalize")),
                      _node("field_clamp", "volumewrangle", "field_sharpen", ("group", "bindeach", "snippet"))])
    else:
        nodes.append(_node("flame_height", "volumewrangle", "solver",
            ("group", "bindeach", "snippet", "exportlist", "autobind", "vex_outputmask", "vex_geometrygenerator", "vex_precision")))
    nodes.append(_node("output", "null", "field_clamp" if pack_id == SMOKE else "flame_height"))
    solver = next(n for n in nodes if n["role"] == "solver")
    required = {p[0] for p in solver["required_parms"]}
    required.update(("numfields", "export_enable#", "export_fieldname#", "export_visible#", "conv_vdb", "minimalsolve", "srclimitframerange", "turbulence_influencefield"))
    for control in control_contract(pack_id, version).values():
        if control["role"] == "solver":
            required.update(control["aliases"])
        required.update(parm for role, parm, _ in control["required_gates"] if role == "solver")
    solver["required_parms"] = [[p] for p in sorted(required)]
    return nodes


def volume_sampling_initialization_plan(version: str) -> list[dict]:
    """Fresh task-owned Karma settings only; an existing base is not rewritten."""
    _domain(SMOKE, version)
    return [_write("render_settings", "engine", "cpu", "string", "gates"),
            _write("render_settings", "convergence_mode", "Variance", "string", "gates"),
            _write("render_settings", "varianceaa_minsamples", 1, "integer", "normalize_sampling_base"),
            _write("render_settings", "varianceaa_maxsamples", 1, "integer", "normalize_sampling_base")]


def connection_requirements(pack_id, version):
    return [{"source_role": node["input_role"], "source_output": 0,
             "destination_role": node["role"], "destination_input": 0}
            for node in node_requirements(pack_id, version) if node["input_role"]]


def _source_spec(raw):
    required = {"emission_windows", "direction", "spread", "speed", "particle_separation"}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise NativePyroDomainError("EXPLICIT_TYPED_SOURCE_REQUIRED", ",".join(sorted(required)))
    windows = raw["emission_windows"]
    if not isinstance(windows, (list, tuple)) or not 1 <= len(windows) <= 32:
        raise NativePyroDomainError("INVALID_SOURCE_WINDOWS", "1..32 explicit inclusive intervals required")
    normalized = []
    for pair in windows:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(type(n) is not int or not 1 <= n <= 1000000 for n in pair) or pair[0] > pair[1]:
            raise NativePyroDomainError("INVALID_SOURCE_WINDOWS", "positive integral start/end")
        if normalized and pair[0] <= normalized[-1][1]:
            raise NativePyroDomainError("INVALID_SOURCE_WINDOWS", "sorted disjoint intervals required")
        normalized.append(tuple(pair))
    direction = raw["direction"]
    if not isinstance(direction, (list, tuple)) or len(direction) != 3:
        raise NativePyroDomainError("INVALID_SOURCE_DIRECTION", "three numeric components required")
    direction = [_number(v, -1e6, 1e6, "direction") for v in direction]
    length = math.sqrt(sum(v * v for v in direction))
    if length == 0:
        raise NativePyroDomainError("INVALID_SOURCE_DIRECTION", "axis must be nonzero")
    return {"emission_windows": normalized, "direction": [v / length for v in direction],
            "spread": _number(raw["spread"], 0, 180, "spread"),
            "speed": _number(raw["speed"], 0, 1000, "speed"),
            "particle_separation": _number(raw["particle_separation"], .001, 1000, "particle_separation")}


def source_program(pack_id: str, version: str, source: Mapping) -> dict:
    """Generate fixed numeric-only VEX; no supplied code, names or expressions."""
    _domain(pack_id, version); source = _source_spec(source)
    number = lambda x: format(float(x), ".17g")
    gate = " || ".join(f"(@Frame >= {a} && @Frame < {b + 1})" for a, b in source["emission_windows"])
    lines = ["int active = (" + gate + ");",
             "vector axis = set(" + ", ".join(number(x) for x in source["direction"]) + ");",
             "vector helper = abs(axis.y) < 0.999 ? set(0, 1, 0) : set(1, 0, 0);",
             "vector side = normalize(cross(axis, helper)); vector up = cross(side, axis);",
             "float u = rand(float(@ptnum) + 17.0);",
             "float azimuth = 6.283185307179586 * rand(float(@ptnum) + 43.0);",
             "float cone_cos = 1.0 - u * (1.0 - cos(" + number(math.radians(source["spread"] / 2)) + "));",
             "float cone_sin = sqrt(max(0.0, 1.0 - cone_cos * cone_cos));",
             "vector direction = cone_cos*axis + cone_sin*(cos(azimuth)*side + sin(azimuth)*up);",
             "v@v = active * " + number(source["speed"]) + " * direction;",
             "f@density *= active; f@temperature *= active;"]
    if pack_id == FIRE:
        lines.append("f@burn *= active; f@flame = f@burn;")
    program = "\n".join(lines) + "\n"
    return {"schema": "bridge.trusted-pyro-source-program/1", "generator": PROGRAM_GENERATOR,
            "domain_pack": pack_id, "native_version": version, "source": source,
            "role": "source_control", "parm": "snippet", "program": program,
            "sha256": hashlib.sha256(program.encode()).hexdigest()}


def activation_schedule(source: Mapping) -> list[dict]:
    source = _source_spec(source)
    keys = {source["emission_windows"][0][0] - 1: 0}
    for start, end in source["emission_windows"]:
        keys[start] = 1; keys[end + 1] = 0
    return [{"frame": frame, "value": value, "interpolation": "constant"} for frame, value in sorted(keys.items())]


def trusted_initialization_plan(pack_id: str, version: str, source: Mapping, *, voxel_size: float = .1, height_context=None) -> list[dict]:
    """Fresh task-owned nodes only; allocate before resolving concrete rows.

    Install constant activation keys after all gated source-row values. The host
    snapshots each phase before its first write and rolls back allocation, rows,
    program registration and schedules through the existing transaction.
    """
    _domain(pack_id, version); source = _source_spec(source)
    voxel_size = _number(voxel_size, .005, 1., "voxel_size")
    attrs = [("density", 1.), ("temperature", 0. if pack_id == SMOKE else 1.)]
    if pack_id == FIRE:
        attrs.append(("burn", 1.))
    rows = [("density", "density", "scalar", "add", 1), ("temperature", "temperature", "scalar", "add", 1)]
    if pack_id == FIRE:
        rows.append(("flame", "flame", "scalar", "add", 1))
    rows.append(("v", "vel", "vector", "copy", 0))
    export_fields = ["density", "temperature", "vel"] + (["flame"] if pack_id == FIRE else [])
    writes = [_write("solver", "numfields", len(export_fields), "multiparm", "allocate"),
              _write("source_points", "attributes", len(attrs), "multiparm", "allocate"),
              _write("solver", "numsources", len(rows), "multiparm", "allocate"),
              _write("source_points", "mode", "2", "ordinal", "gates", value_kind="menu_token"),
              _write("source_points", "particlesep", source["particle_separation"], phase="gates"),
              _write("solver", "minimalsolve", 0, "toggle", "gates"),
              _write("solver", "srclimitframerange", 0, "toggle", "gates"),
              _write("solver", "conv_vdb", 0, "toggle", "gates")]
    for gate in ("enable_disturbance", "enable_turbulence", "enable_shredding", "enable_dissipation", "enable_buoyancy", "enablesmoke"):
        writes.append(_write("solver", gate, 1, "toggle", "gates"))
    writes.extend([_write("solver", "addflamefield", int(pack_id == FIRE), "toggle", "gates"),
                   _write("solver", "fi_enable", int(pack_id == FIRE), "toggle", "gates")])
    for index, name in enumerate(export_fields, 1):
        writes.extend([_write("solver", f"export_enable{index}", 1, "toggle", "attributes"),
                       _write("solver", f"export_fieldname{index}", name, "string", "attributes"),
                       _write("solver", f"export_visible{index}", "smoke" if name == "density" else "invisible", "ordinal", "attributes", value_kind="menu_token")])
    for index, (name, value) in enumerate(attrs, 1):
        writes.extend([_write("source_points", f"attribute{index}", name, "ordinal", "attributes", value_kind="menu_token"),
                       _write("source_points", f"fval{index}", value, phase="attributes"),
                       _write("source_points", f"scale{index}", 1., phase="attributes")])
    if pack_id == SMOKE:
        writes.extend([_write("solver", "shredding_field", "density", "string", "attributes"),
                       _write("solver", "turbulence_influencefield", "density", "string", "attributes")])
    else:
        writes.append(_write("solver", "turbulence_influencefield", "temperature", "string", "attributes"))
    registration = source_program(pack_id, version, source)
    writes.extend([_write("source_control", "class", "Points", "ordinal", "source_program", value_kind="menu_label"),
                   _write("source_control", "group", "", "string", "source_program"),
                   _write("source_control", "snippet", registration["program"], "string", "source_program", trusted_program=registration),
                   _write("source_volume", "attributes", "density temperature " + ("burn flame " if pack_id == FIRE else "") + "v", "string", "source_rows"),
                   _write("source_volume", "voxelsize", voxel_size, phase="source_rows"),
                   _write("solver", "divsize", voxel_size, phase="source_rows")])
    for index, (volume, target, rank, operation, normalize) in enumerate(rows, 1):
        writes.extend([_write("solver", f"source_activate{index}", 1, "toggle", "source_rows"),
                       _write("solver", f"source_voperator{index}", "add", "ordinal", "source_rows", value_kind="menu_token"),
                       _write("solver", f"source_rank{index}", rank, "ordinal", "source_rows", value_kind="menu_token"),
                       _write("solver", f"source_volume{index}", volume, "string", "source_rows"),
                       _write("solver", f"source_vfield{index}", target, "string", "source_rows"),
                       _write("solver", f"source_vscale{index}", 1., phase="source_rows"),
                       _write("solver", f"source_vnormalize{index}", normalize, "toggle", "source_rows")])
        if operation == "copy":
            writes.append(_write("solver", f"source_voperator{index}", "copy", "ordinal", "final_source_modes", value_kind="menu_token"))
    if pack_id == SMOKE:
        writes.extend([_write("field_sharpen", "group", "@name=density", "string", "shaping"),
                       _write("field_sharpen", "normalize", 1, "toggle", "shaping"),
                       *[_write("field_sharpen", parm, vals, "float_tuple", "shaping", size=9) for parm, vals in zip(("convolvezm", "convolvezz", "convolvezp"), _stencil(0))],
                       _write("field_clamp", "group", "@name=density", "string", "shaping"),
                       _write("field_clamp", "bindeach", 1, "toggle", "shaping"),
                       _write("field_clamp", "snippet", "@density = max(0,f@density);", "string", "shaping", trusted_program={"generator": "sidefx.setupSharpenVolume.clamp/1", "program": "@density = max(0,f@density);"})])
    if pack_id == FIRE:
        from .native_pyro_height_program import initialization_plan
        writes.extend(initialization_plan())
        if height_context is not None:
            writes.extend(control_write_plan(pack_id, "flame_height", 0., version, height_context=height_context))
    for index in range(1, len(rows) + 1):
        writes.append(_write("solver", f"source_activate{index}", activation_schedule(source), "keyframes", "schedule", interpolation="constant"))
    return writes


def overlay_host_pack(pack_id: str, pack: Mapping, version: str) -> dict:
    contract = control_contract(pack_id, version); result = copy.deepcopy(dict(pack))
    if not isinstance(result.get("controls"), dict) or set(result["controls"]) != set(contract):
        raise NativePyroDomainError("PUBLIC_CONTROL_CONTRACT_CHANGED", pack_id)
    for name, control in result["controls"].items():
        control.update(copy.deepcopy(contract[name]))
    core_roles = {n["role"] for n in node_requirements(pack_id, version)}
    described = {n['role']:n for n in result.get('nodes', ())}
    complete = core_roles.issubset(described) and all(described[n['role']].get('types') == n['types'] for n in node_requirements(pack_id, version))
    extras = [n for n in result.get("nodes", ()) if n.get("role") not in (core_roles if complete else {"source", "solver", "output"})]
    if any(n.get("role") in core_roles for n in extras):
        raise NativePyroDomainError("PYRO_SOURCE_ADAPTER_ALREADY_DECLARED", pack_id)
    result["nodes"] = node_requirements(pack_id, version) + extras
    result["connections"] = connection_requirements(pack_id, version)
    result["native_version"] = version; result["native_plan_schema"] = SCHEMA
    return result


def control_readback(pack_id: str, control: str, values: Mapping[tuple[str, str], Any], version: str, *, height_context=None):
    c = control_contract(pack_id, version).get(control)
    if c is None:
        raise NativePyroDomainError("UNKNOWN_NATIVE_CONTROL", control)
    if c["native_status"] != "mapped":
        raise NativePyroDomainError(c.get("blocker", "EXTERNAL_NUKE_CONTROL_REQUIRED"), control)
    if control == "flame_height":
        from .native_pyro_height_program import control_readback as height_readback
        return height_readback(version, height_context, values)["value"]
    if not isinstance(values, Mapping):
        raise NativePyroDomainError("NATIVE_CONTROL_READBACK_REQUIRED", control)
    targets = c.get("targets") or [(c["role"], c["aliases"][0])]
    if any(tuple(target) not in values for target in targets):
        raise NativePyroDomainError("NATIVE_CONTROL_READBACK_REQUIRED", control)
    if control == "field_sharpen":
        arrays = [values[("field_sharpen", name)] for name in ("convolvezm", "convolvezz", "convolvezp")]
        if any(not isinstance(a, (list, tuple)) or len(a) != 9 for a in arrays):
            raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", control)
        if any(type(value) not in (int, float) or not -1e12 <= value <= 1e12 or not math.isfinite(value)
               for array in arrays for value in array):
            raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", control)
        strength = -arrays[0][4]
        expected = _stencil(strength)
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not math.isclose(v, e, abs_tol=1e-9) for a, b in zip(arrays, expected) for v, e in zip(a, b)):
            raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", control)
        value = strength
    elif control == "volume_samples":
        if any(type(values[("render_settings", p)]) is not int or values[("render_settings", p)] != 1 for p in ("varianceaa_minsamples", "varianceaa_maxsamples")):
            raise NativePyroDomainError("VOLUME_SAMPLE_BASE_NOT_NORMALIZED", control)
        value = values[("render_settings", "volumequality")]
    elif control == "source_scale":
        value = values[("source", "rad")]
        if (not isinstance(value, (list, tuple)) or len(value) != 3
                or any(type(component) not in (int, float) or component != value[0] for component in value)):
            raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", control)
        value = value[0]
    else:
        value = values[(c["role"], c["aliases"][0])]
        if control == "voxel_size":
            source_value = _number(values[("source_volume", "voxelsize")], c["minimum"], c["maximum"], control)
            if value != source_value:
                raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", "source and solver resolution disagree")
        if control == "burn_rate":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise NativePyroDomainError("NATIVE_CONTROL_READBACK_MISMATCH", "flames_lifespan must be finite positive")
            value = 1 / value
    return _number(value, c["minimum"], c["maximum"], control, c["value_type"] == "int")


def validate_control_write_plan(writes: list[dict], observations: Mapping[tuple[str, str], Mapping]) -> None:
    """Candidate writes require complete actual HOM observations, never defaults."""
    for write in writes:
        if write.get("role") == "flame_height":
            from . import native_pyro_height_program as height
            context = observations.get(("flame_height", "@height_context"))
            if isinstance(context, Mapping) and context.get("origin") == "runtime_hom":
                context = context.get("context")
            registration = write.get("trusted_program", {})
            expected = height.control_write_plan(registration.get("native_version"), registration.get("value"), context)
            if height._hash([write]) != height._hash(expected):
                raise NativePyroDomainError("PYRO_HEIGHT_INVALID_PLAN", "native writes differ from fixed height generator")
        key = (write["role"], write["parm"]); actual = observations.get(key, {})
        typ = "float" if write["native_type"] == "float_tuple" else write["native_type"]
        if (actual.get("origin") != "runtime_hom" or actual.get("type") != typ
                or type(actual.get("size")) is not int or actual["size"] != write.get("size", 1)):
            raise NativePyroDomainError("NATIVE_CONTROL_INTERFACE_REQUIRED", "/".join(key))
        if any(actual.get(flag) is not False for flag in ("locked", "disabled", "hidden", "driven")):
            raise NativePyroDomainError("NATIVE_CONTROL_GATE_BLOCKED", "/".join(key))
        for role, parm, expected in write.get("required_gates", ()):
            gate = observations.get((role, parm), {})
            matched = gate.get("value") == expected and (type(gate.get("value")) is int if type(expected) is int else True)
            if not matched and isinstance(expected, str):
                tokens = gate.get("menu_tokens") or []; labels = gate.get("menu_labels") or []
                current = gate.get("value")
                index = tokens.index(current) if current in tokens else current if type(current) is int else -1
                matched = 0 <= index < len(tokens) and (tokens[index] == expected or (index < len(labels) and labels[index] == expected))
            if gate.get("origin") != "runtime_hom" or not matched:
                raise NativePyroDomainError("NATIVE_CONTROL_GATE_BLOCKED", role + "/" + parm)


def overlay_core_pack_dict(pack: Mapping, version: str) -> dict:
    pack_id = pack["id"]; contract = control_contract(pack_id, version)
    result = copy.deepcopy(dict(pack)); controls = result.get("controls")
    if not isinstance(controls, list) or len(controls) != len(contract) or {c.get("id") for c in controls} != set(contract):
        raise NativePyroDomainError("PUBLIC_CONTROL_CONTRACT_CHANGED", pack_id)
    host_nodes = []
    for node in result.get("nodes", ()):
        node = copy.deepcopy(node); node["types"] = node.pop("type_candidates", [])
        node["required_parms"] = node.pop("required_parameter_aliases", [])
        host_nodes.append(node)
    host = {"nodes": host_nodes, "controls": {c["id"]: {} for c in controls}}
    native = overlay_host_pack(pack_id, host, version)
    for c in controls:
        contract_item = copy.deepcopy(contract[c["id"]])
        c["node_role"] = contract_item.pop("role"); c["parameter_aliases"] = contract_item.pop("aliases")
        c.update(contract_item)
    result["nodes"] = []
    for n in native["nodes"]:
        n = dict(n); n["type_candidates"] = n.pop("types")
        n["required_parameter_aliases"] = n.pop("required_parms", [])
        result["nodes"].append(n)
    result["connections"] = native["connections"]; result["native_version"] = version; result["native_plan_schema"] = SCHEMA
    return result
