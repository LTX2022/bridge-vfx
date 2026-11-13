"""Versioned native plans for the existing MaterialX and Solaris transactions.

This module creates no nodes, writes no parms, and owns no task state. Plans must
be resolved, checked for real HOM types/gates, snapshotted and committed by the
existing generator/parameter transaction. Static evidence is never cook evidence.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS, versioned_controls

import copy
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

SUPPORTED_VERSIONS = ("21.0.631", "22.0.429")
MATERIAL = "material_lookdev_v1"
LIGHTING = "lighting_camera_render_v1"
SHUTTER_CONTRACT = "centered_duration_usd_timecode/1"


class NativeRenderDomainError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _version(version: str) -> str:
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        raise NativeRenderDomainError("UNSUPPORTED_NATIVE_VERSION", str(version))
    return version


# identifier: role, exact machine parm, minimum, maximum, public value type
_MATERIAL_CONTROLS = {
    "base_color": ("material", "base_color", 0, 1, "color3"),
    "roughness": ("material", "specular_roughness", 0, 1, "float"),
    "ior": ("material", "specular_IOR", 1, 5, "float"),
    "transmission": ("material", "transmission", 0, 1, "float"),
    "subsurface": ("material", "subsurface", 0, 1, "float"),
    "normal_strength": ("normal_map", "scale", 0, 100, "float"),
    "specular_weight": ("material", "specular", 0, 1, "float"),
    "coat_weight": ("material", "coat", 0, 1, "float"),
    "anisotropy": ("material", "specular_anisotropy", 0, 1, "float"),
    "displacement_scale": ("displacement", "scale", -1000, 1000, "float"),
    "emission_weight": ("material", "emission", 0, 10000, "float"),
}
_LIGHTING_CONTROLS = {
    "exposure": ("light", "exposure", -30, 30, "float"),
    "focal_length": ("camera", "focalLength", 1, 1000, "float"),
    "pixel_samples": ("settings", "samplesperpixel", 1, 100000, "int"),
    "volume_step_rate": ("settings", "volumesteprate", .01, 100, "float"),
    "denoise": ("settings", "denoiser", 0, 1, "bool"),
    "sample_quality": ("settings", "samplesperpixel", 1, 100000, "int"),
    "filter_width": ("settings", "pixelfiltersize", .01, 100, "float"),
    "denoise_mix": ("settings", "denoiser", 0, 1, "float"),
    "depth_of_field": ("camera", "fStop", 0, 1000, "float"),
    "motion_blur": ("settings", "enablemblur", 0, 1, "bool"),
    "shutter": ("camera", "xn__shutteropen_0ta", 0, 10, "float"),
    "light_size": ("light", "radius", 0, 10000, "float"),
}
_GATES = {
    "exposure": (("light", "exposure_control", "set"),),
    "focal_length": (("camera", "focalLength_control", "set"),),
    "depth_of_field": (("camera", "fStop_control", "set"),),
    "shutter": (("camera", "xn__shutteropen_control_16a", "set"),
                ("camera", "xn__shutterclose_control_o8a", "set")),
    "light_size": (("light", "radius_control", "set"),
                   ("light", "lighttype", "UsdLuxSphereLight")),
}


def _specs(pack_id: str):
    if pack_id == MATERIAL:
        return _MATERIAL_CONTROLS
    if pack_id == LIGHTING:
        return _LIGHTING_CONTROLS
    raise NativeRenderDomainError("UNSUPPORTED_RENDER_DOMAIN", pack_id)


def _write(role: str, parm: str, value: Any, kind: str = "float", *, phase="value"):
    return {"role": role, "parm": parm, "value": value, "native_type": kind,
            "phase": phase, "require_writable": True, "require_readback": True}


@versioned_controls
def control_contract(pack_id: str, version: str) -> dict:
    """All public names remain present, including the unsupported blend interval."""
    _version(version)
    result = {}
    for name, (role, parm, lo, hi, kind) in _specs(pack_id).items():
        result[name] = {"role": role, "aliases": [parm], "minimum": lo,
                        "maximum": hi, "value_type": kind,
                        "application": "houdini", "native_conversion": name,
                        "required_gates": list(_GATES.get(name, ())) }
    if pack_id == LIGHTING:
        result["shutter"].update(unit="UsdTimeCode", semantic_contract=SHUTTER_CONTRACT,
                                 inverse="shutter_close - shutter_open",
                                 forward="(-duration / 2, duration / 2)")
        result["denoise_mix"].update(
            native_supported_values=[0, 1], interval_blocker="EXTERNAL_DENOISE_BLEND_REQUIRED",
            external_application="external_nuke",
            external_contract={"raw_beauty": "required", "denoised_beauty": "required",
                               "weight": "denoise_mix", "formula": "raw*(1-weight)+denoised*weight",
                               "operation_receipt": "required"})
        result["filter_width"]["unit"] = "pixels"
    return result


def _numeric(name: str, value: Any, spec: tuple):
    lo, hi, kind = spec[2:]
    seq = value if kind == "color3" else [value]
    if kind == "color3" and (not isinstance(value, (list, tuple)) or len(value) != 3):
        raise NativeRenderDomainError("INVALID_NATIVE_CONTROL_VALUE", name + " requires color3")
    values = []
    for item in seq:
        if isinstance(item, bool):
            if kind != "bool":
                raise NativeRenderDomainError("INVALID_NATIVE_CONTROL_VALUE", name)
            item = int(item)
        if not isinstance(item, (float, int)) or not math.isfinite(item) or not lo <= item <= hi:
            raise NativeRenderDomainError("INVALID_NATIVE_CONTROL_VALUE", name)
        if kind in {"int", "bool"} and int(item) != item:
            raise NativeRenderDomainError("INVALID_NATIVE_CONTROL_VALUE", name)
        values.append(int(item) if kind in {"int", "bool"} else float(item))
    return tuple(values) if kind == "color3" else values[0]


def control_write_plan(pack_id: str, control: str, value: Any, version: str,
                       *, shutter_contract: str | None = None,
                       denoiser: str = "oidn", light_type: str = "light") -> list[dict]:
    """Return all writes before the caller starts its existing atomic transaction.

    Control gates are requirements on existing artist nodes. The trusted init
    plan sets them only on newly created owned nodes. Candidate edits must never
    silently unlock an artist gate or change an unsuitable light type.
    """
    _version(version)
    specs = _specs(pack_id)
    if control not in specs:
        raise NativeRenderDomainError("UNKNOWN_NATIVE_CONTROL", control)
    prepared = control_contract(pack_id, version)[control]
    if prepared.get("native_status") == "blocked":
        raise NativeRenderDomainError(prepared["blocker"], control)
    role, parm, _, _, kind = specs[control]
    value = _numeric(control, value, specs[control])
    if control == "light_size" and light_type != "light":
        raise NativeRenderDomainError("UNSUPPORTED_NATIVE_CONTROL", "domelight has no radius")
    if control == "shutter":
        if shutter_contract != SHUTTER_CONTRACT:
            raise NativeRenderDomainError("SHUTTER_UNIT_CONTRACT_REQUIRED", SHUTTER_CONTRACT)
        if value == 0:
            raise NativeRenderDomainError("SHUTTER_ZERO_DURATION_UNSUPPORTED", "vendor camera contract requires close > open")
        writes = [_write(role, parm, -value / 2),
                  _write(role, "xn__shutterclose_nva", value / 2)]
    elif control in {"denoise", "denoise_mix"}:
        if denoiser not in {"oidn", "optix"}:
            raise NativeRenderDomainError("UNSUPPORTED_NATIVE_DENOISER", str(denoiser))
        if control == "denoise_mix" and value not in (0, 1):
            raise NativeRenderDomainError("EXTERNAL_DENOISE_BLEND_REQUIRED",
                                          "continuous denoise_mix requires raw/denoised Nuke inputs and an operation receipt")
        writes = [_write(role, parm, denoiser if value else "off", "string")]
    else:
        native_kind = "toggle" if kind == "bool" else "integer" if kind == "int" else kind
        writes = [_write(role, parm, bool(value) if kind == "bool" else value, native_kind)]
    for write in writes:
        write["required_gates"] = list(_GATES.get(control, ()))
        if control in {"pixel_samples", "sample_quality"}:
            write["required_gates"] = [("settings", "engine", "cpu"), ("settings", "convergence_mode", "Variance")]
        if control == "filter_width" and version in ("22.0.429", *PREPARATION_VERSIONS):
            write["required_gates"] = [("settings", "pixelfilterscale", 1.0)]
    return writes


def candidate_write_plan(pack_id: str, controls: Mapping[str, Any], version: str, **kwargs) -> list[dict]:
    """Reject contradictory aliases before any target is touched."""
    writes = []
    seen = {}
    for control, value in controls.items():
        for item in control_write_plan(pack_id, control, value, version, **kwargs):
            key = (item["role"], item["parm"])
            if key in seen:
                if seen[key] != item["value"]:
                    raise NativeRenderDomainError("CONFLICTING_NATIVE_CONTROLS", "/".join(key))
                continue
            seen[key] = item["value"]
            writes.append(item)
    return writes


def control_readback(pack_id: str, control: str, values: Mapping[tuple[str, str], Any],
                     version: str, *, shutter_contract: str | None = None):
    _version(version)
    specs = _specs(pack_id)
    if control not in specs:
        raise NativeRenderDomainError("UNKNOWN_NATIVE_CONTROL", control)
    role, parm, _, _, _ = specs[control]
    value = values[(role, parm)]
    if control == "shutter":
        if shutter_contract != SHUTTER_CONTRACT:
            raise NativeRenderDomainError("SHUTTER_UNIT_CONTRACT_REQUIRED", SHUTTER_CONTRACT)
        close = values[(role, "xn__shutterclose_nva")]
        if not isinstance(value, (int, float)) or not isinstance(close, (int, float)) or not math.isfinite(value) or not math.isfinite(close) or not math.isclose(value, -close, abs_tol=1e-9):
            raise NativeRenderDomainError("NATIVE_CONTROL_READBACK_MISMATCH", "shutter is not centered")
        value = close - value
    elif control in {"denoise", "denoise_mix"}:
        if value not in {"off", "oidn", "optix"}:
            raise NativeRenderDomainError("NATIVE_CONTROL_READBACK_MISMATCH", "denoiser")
        value = 0 if value == "off" else 1
    result = _numeric(control, value, specs[control])
    return bool(result) if specs[control][-1] == "bool" else result


def _node(role, category, typ, parms=(), parent_role=None, input_role=None):
    result = {"role": role, "category": category, "types": [typ],
              "required_parms": [[p] for p in parms], "input_role": input_role}
    parent_role = parent_role or {"lop":"usd_network","rop":"render_network"}.get(category)
    if parent_role:
        result["parent_role"] = parent_role
    return result


def _render_output_nodes(stage_role):
    """The output chain consumes its existing LOP stage without reimporting SOPs."""
    return [
        _node("camera", "lop", "camera", ("primpath", "focalLength", "fStop", "xn__shutteropen_0ta", "xn__shutterclose_nva"), input_role=stage_role),
        _node("light", "lop", "light", ("primpath", "lighttype", "radius", "exposure"), input_role="camera"),
        _node("settings", "lop", "karmarendersettings", ("primpath", "camera", "samplesperpixel", "volumesteprate", "enablemblur", "pixelfiltersize", "denoiser"), input_role="light"),
        _node("render_var", "lop", "rendervar", ("primpath", "sourceName", "sourceType", "dataType"), input_role="settings"),
        _node("render_product", "lop", "renderproduct", ("primpattern", "orderedVars", "productType", "productName", "camera"), input_role="render_var"),
        _node("settings_binding", "lop", "rendersettings", ("primpattern", "createprims", "products", "camera"), input_role="render_product"),
        _node("render", "rop", "usdrender", ("loppath", "rendersettings", "override_camera", "outputimage", "execute")),
    ]


def node_requirements(pack_id: str, version: str) -> list[dict]:
    _version(version)
    if pack_id == MATERIAL:
        return [
            _node("geometry_network", "obj", "geo"),
            _node("source", "sop", "sphere", (), "geometry_network"),
            _node("usd_network", "obj", "lopnet"),
            _node("material_network", "obj", "matnet"),
            _node("normal_map", "vop", "mtlxnormalmap", ("scale", "in"), "material_network"),
            _node("displacement", "vop", "mtlxdisplacement", ("scale", "displacement"), "material_network"),
            _node("material", "vop", "mtlxstandard_surface", tuple(s[1] for s in _MATERIAL_CONTROLS.values() if s[0] == "material"), "material_network"),
            _node("material_output", "vop", "mtlxsurfacematerial", (), "material_network"),
            _node("geometry_import", "lop", "sopimport", ("soppath", "enable_pathprefix", "pathprefix")),
            _node("material_library", "lop", "materiallibrary", ("materials",), input_role="geometry_import"),
            _node("material_binding", "lop", "assignmaterial", ("nummaterials",), input_role="material_library"),
            _node("render_network", "obj", "ropnet"),
        ] + _render_output_nodes("material_binding")
    if pack_id == LIGHTING:
        return [
            _node("geometry_network", "obj", "geo"),
            _node("source", "sop", "sphere", (), "geometry_network"),
            _node("usd_network", "obj", "lopnet"),
            _node("render_network", "obj", "ropnet"),
            _node("geometry_import", "lop", "sopimport", ("soppath", "enable_pathprefix", "pathprefix")),
        ] + _render_output_nodes("geometry_import")
    _specs(pack_id)
    return []


def connection_requirements(pack_id: str, version: str) -> list[dict]:
    nodes = node_requirements(pack_id, version)
    result = [{"source_role": n["input_role"], "source_output": 0,
               "destination_role": n["role"], "destination_input": 0,
               "require_same_parent": True}
              for n in nodes if n.get("input_role")]
    if pack_id == MATERIAL:
        result += [
            {"source_role": "normal_map", "source_output_name": "out", "destination_role": "material", "destination_input_name": "normal", "require_same_parent": True},
            {"source_role": "material", "source_output_name": "out", "destination_role": "material_output", "destination_input_name": "surfaceshader", "require_same_parent": True},
            {"source_role": "displacement", "source_output_name": "out", "destination_role": "material_output", "destination_input_name": "displacementshader", "require_same_parent": True},
        ]
    return result


def resolve_named_connections(pack_id: str, version: str, interfaces: Mapping[str, Mapping]) -> list[dict]:
    """Resolve actual HOM names; DialogScript ordinal positions are not HOM proof."""
    result = []
    for spec in connection_requirements(pack_id, version):
        item = dict(spec)
        for side, key, names in (("source", "source_output", "output_names"), ("destination", "destination_input", "input_names")):
            name = spec.get(key + "_name")
            if name is None:
                continue
            role = spec[side + "_role"]
            interface = interfaces.get(role, {})
            actual = interface.get(names)
            if interface.get("origin") != "runtime_hom" or not isinstance(actual, (tuple, list)) or actual.count(name) != 1:
                raise NativeRenderDomainError("NATIVE_PORT_INTERFACE_REQUIRED", role + "/" + name)
            item[key] = actual.index(name)
        result.append(item)
    return result


def renderer_parameter(version: str, actual_fields: Mapping[str, Mapping]) -> str:
    """Both same-version vendor creation scripts use the exact renderer field.

    H21's help anchor renderdelegate is not its machine name. The actual ROP
    must provide a scalar string menu containing BRAY_HdKarma; no alias fallback
    is authorized by the help anchor.
    """
    _version(version)
    field = actual_fields.get("renderer", {})
    if field.get("origin") != "runtime_hom" or field.get("type") != "string" or field.get("size") != 1 or "BRAY_HdKarma" not in field.get("menu_tokens", ()):
        raise NativeRenderDomainError("USD_RENDERER_INTERFACE_REQUIRED", "renderer")
    return "renderer"


def validate_control_write_plan(writes: list[dict], observations: Mapping[tuple[str, str], Mapping]) -> None:
    """Preflight the complete candidate against actual fields before any writes.

    Observations come from the existing HOM resolver, never from these plans.
    Unknown type, disabled/locked state, gate value or scalar shape blocks.
    """
    for write in writes:
        key = (write["role"], write["parm"])
        actual = observations.get(key, {})
        expected = write["native_type"]
        permitted = {"float": {"float"}, "integer": {"integer"},
                     "toggle": {"toggle"}, "string": {"string"},
                     "color3": {"color"}}[expected]
        if actual.get("origin") != "runtime_hom" or actual.get("type") not in permitted or actual.get("size") != (3 if expected == "color3" else 1):
            raise NativeRenderDomainError("NATIVE_CONTROL_INTERFACE_REQUIRED", "/".join(key))
        if actual.get("locked") is not False or actual.get("disabled") is not False or actual.get("hidden") is not False:
            raise NativeRenderDomainError("NATIVE_CONTROL_GATE_BLOCKED", "/".join(key))
        for role, parm, required in write.get("required_gates", ()):
            gate = observations.get((role, parm), {})
            if gate.get("origin") != "runtime_hom" or "value" not in gate or gate["value"] != required:
                raise NativeRenderDomainError("NATIVE_CONTROL_GATE_BLOCKED", role + "/" + parm)
        if expected == "string" and actual.get("menu_tokens") and write["value"] not in actual["menu_tokens"]:
            raise NativeRenderDomainError("NATIVE_CONTROL_GATE_BLOCKED", "/".join(key))

def overlay_host_pack(pack_id: str, pack: Mapping, version: str) -> dict:
    """Adapt the existing pack without dropping controls or rewriting its metadata."""
    contract = control_contract(pack_id, version)
    result = copy.deepcopy(dict(pack))
    controls = result["controls"]
    if not isinstance(controls, dict) or set(controls) != set(contract):
        raise NativeRenderDomainError("PUBLIC_CONTROL_CONTRACT_CHANGED", pack_id)
    for name, control in controls.items():
        control.update(contract[name])
    result["nodes"] = node_requirements(pack_id, version)
    for node in result["nodes"]:
        if node["category"] == "lop": node["parent_role"] = "usd_network"
        elif node["category"] == "rop": node["parent_role"] = "render_network"
    result["connections"] = connection_requirements(pack_id, version)
    result["native_version"] = version
    result["native_plan_schema"] = "bridge.native-render-domains/1"
    result["native_domain_id"] = pack_id
    return result


def overlay_core_pack_dict(pack: Mapping, version: str) -> dict:
    """Overlay the existing public descriptor, preserving all non-native fields.

    Named connections remain symbolic until the existing host generator resolves
    actual HOM ports. Integer-only GraphConnection validators must not guess them.
    """
    pack_id = pack["id"]
    contract = control_contract(pack_id, version)
    result = copy.deepcopy(dict(pack))
    controls = result["controls"]
    if not isinstance(controls, list) or len(controls) != len(contract) or {c.get("id") for c in controls} != set(contract):
        raise NativeRenderDomainError("PUBLIC_CONTROL_CONTRACT_CHANGED", pack_id)
    for control in controls:
        native = contract[control["id"]]
        control["node_role"] = native["role"]
        control["parameter_aliases"] = native["aliases"]
        control.update({k: copy.deepcopy(v) for k, v in native.items() if k not in {"role", "aliases"}})
    result["nodes"] = []
    for item in node_requirements(pack_id, version):
        item = dict(item)
        item["type_candidates"] = item.pop("types")
        item["required_parameter_aliases"] = item.pop("required_parms")
        result["nodes"].append(item)
    result["connections"] = connection_requirements(pack_id, version)
    result["native_version"] = version
    result["native_plan_schema"] = "bridge.native-render-domains/1"
    return result


def _absolute_path(value: Any, name: str):
    if not isinstance(value, str) or not value.startswith("/") or any(x in value for x in ("//", "..", "*", "?", "$", "[", "]", " ")):
        raise NativeRenderDomainError("EXPLICIT_NATIVE_BINDING_REQUIRED", name)
    return value


def trusted_initialization_plan(pack_id: str, version: str, bindings: Mapping[str, Any],
                                *, renderer_field: str | None = None) -> list[dict]:
    """Only for freshly created nodes owned by the existing task transaction.

    Source paths, USD paths and the actual output path are mandatory. No implicit
    camera, settings, product or material lookup can substitute for these links.
    Core compiled multiparm fields must pass runtime type/gate checks after their
    count is initialized. Unknown core defaults remain unknown until real readback.
    """
    _version(version)
    _specs(pack_id)
    source = _absolute_path(bindings.get("source_node_path"), "source_node_path")
    geometry = _absolute_path(bindings.get("geometry_prim_path"), "geometry_prim_path")
    plan = [_write("geometry_import", "soppath", source, "string"),
            _write("geometry_import", "enable_pathprefix", 1, "toggle", phase="gate"),
            _write("geometry_import", "pathprefix", geometry, "string")]
    if pack_id == MATERIAL:
        output = _absolute_path(bindings.get("material_output_node_path"), "material_output_node_path")
        material = _absolute_path(bindings.get("material_prim_path"), "material_prim_path")
        plan += [_write("material_library", "materials", 1, "integer", phase="multiparm_count"),
                 _write("material_library", "matflag1", 1, "toggle", phase="multiparm_child"),
                 _write("material_library", "assign1", 0, "toggle", phase="multiparm_child"),
                 _write("material_library", "matnode1", output, "string", phase="multiparm_child"),
                 _write("material_library", "matpath1", material, "string", phase="multiparm_child"),
                 _write("material_binding", "nummaterials", 1, "integer", phase="multiparm_count"),
                 _write("material_binding", "primpattern1", geometry, "string", phase="multiparm_child"),
                 _write("material_binding", "matspecpath1", material, "string", phase="multiparm_child"),
                 _write("normal_map", "in", (.6, .5, 1.0), "vector3"),
                 _write("displacement", "displacement", .1)]
    paths = {name: _absolute_path(bindings.get(name + "_prim_path"), name + "_prim_path")
             for name in ("camera", "light", "settings", "product", "var")}
    final_stage = _absolute_path(bindings.get("final_lop_node_path"), "final_lop_node_path")
    output = bindings.get("output_image")
    if (not isinstance(output, str) or "\x00" in output
            or not (PurePosixPath(output).is_absolute() or PureWindowsPath(output).is_absolute())):
        raise NativeRenderDomainError("EXPLICIT_NATIVE_BINDING_REQUIRED", "output_image")
    if renderer_field != "renderer":
        raise NativeRenderDomainError("USD_RENDERER_INTERFACE_REQUIRED", "resolve renderer_parameter using actual HOM")
    plan += [_write("camera", "createprims", "on", "menu", phase="gate"),
             _write("light", "createprims", "on", "menu", phase="gate"),
             _write("light", "lighttype", "UsdLuxSphereLight", "menu", phase="gate"),
             _write("settings", "engine", "cpu", "string", phase="gate"),
             _write("settings", "convergence_mode", "Variance", "string", phase="gate")]
    for role in ("camera", "light", "settings"):
        plan.append(_write(role,"primpath",paths[role],"string"))
    product_parent = paths["product"].rsplit("/",1)[0]
    if paths["product"] != product_parent + "/renderproduct":
        raise NativeRenderDomainError("EXPLICIT_NATIVE_BINDING_REQUIRED","Karma product name is renderproduct")
    plan += [_write("settings","renderproductsparentprimpath",product_parent,"string"),
             _write("settings","rendervarsparentprimpath",paths["var"].rsplit("/",1)[0] + "/Vars","string"),
             _write("settings","picture",output,"string"),
             _write("settings", "camera", paths["camera"], "string")]
    if version in ("22.0.429", *PREPARATION_VERSIONS):
        plan.append(_write("settings", "pixelfilterscale", 1.0, phase="gate"))
    for gate in ("focalLength_control", "fStop_control", "xn__shutteropen_control_16a", "xn__shutterclose_control_o8a", "xn__xformOptransform_control_6fb"):
        plan.append(_write("camera", gate, "set", "string", phase="gate"))
    for gate in ("radius_control", "exposure_control", "xn__xformOptransform_control_6fb"):
        plan.append(_write("light", gate, "set", "string", phase="gate"))
    plan += [_write("camera", "t", (0.0, 0.0, 5.0), "vector3"),
             _write("light", "t", (2.0, 2.0, 4.0), "vector3"),
             _write("render_var", "createprims", "on", "menu", phase="gate"),
             _write("render_var", "primpath", paths["var"], "string"),
             _write("render_product", "createprims", "forceedit", "menu", phase="gate"),
             _write("render_product", "primpattern", paths["product"], "string"),
             _write("settings_binding", "createprims", "forceedit", "menu", phase="gate"),
             _write("settings_binding", "primpattern", paths["settings"], "string")]
    for role, parm, value in (("render_var", "dataType", "color3f"), ("render_var", "sourceName", "C"),
                              ("render_var", "sourceType", "raw"), ("render_product", "orderedVars", paths["var"]),
                              ("render_product", "productName", output), ("render_product", "productType", "raster"),
                              ("render_product", "camera", paths["camera"]), ("settings_binding", "products", paths["product"]),
                              ("settings_binding", "camera", paths["camera"])):
        plan.append(_write(role, parm + "_control", "set", "string", phase="gate"))
        plan.append(_write(role, parm, value, "string"))
    plan += [_write("render", renderer_field, "BRAY_HdKarma", "string"),
             _write("render", "loppath", final_stage, "string"),
             _write("render", "rendersettings", paths["settings"], "string"),
             _write("render", "override_camera", paths["camera"], "string"),
             _write("render", "outputimage", output, "string"),
             # Native synchronous render requires the foreground toggle; its
             # factory state is off and no later stage enables it.
             _write("render", "soho_foreground", 1, "toggle", phase="gate")]
    if version == "21.0.631":
        output_path = PurePosixPath(output) if PurePosixPath(output).is_absolute() else PureWindowsPath(output)
        plan += [_write("render", "enableoutputprocessor_savetodirectory", 1, "toggle", phase="gate"),
                 _write("render", "savetodirectory_directory", str(output_path.parent), "string"),
                 _write("render", "husk_tiletempdir", str(output_path.parent), "string")]
    return plan


def trusted_node_flag_plan(pack_id: str, version: str) -> list[dict]:
    """Flags for newly created task-owned nodes, through the existing flag path."""
    _version(version)
    _specs(pack_id)
    if pack_id == MATERIAL:
        return [{"role": "material_output", "setter": "setMaterialFlag",
                 "getter": "isMaterialFlagSet", "value": True, "require_readback": True}]
    return []


def static_blockers(pack_id: str, version: str) -> list[dict]:
    """Facts not established by the installed DialogScript/static UI sources."""
    _version(version)
    _specs(pack_id)
    result = [{"code": "CORE_NATIVE_INTERFACE_RUNTIME_REQUIRED", "role": n["role"],
               "operator": n["category"] + "/" + n["types"][0],
               "requires": ["actual parm types/menu tokens", "multiparm expansion", "writable gates", "readback"]}
              for n in node_requirements(pack_id, version)
              if n["types"][0] in {"matnet", "sopimport", "materiallibrary", "assignmaterial", "usdrender"}]
    result.append({"code": "USD_RENDERER_RUNTIME_INTERFACE_REQUIRED", "machine_id": "renderer", "help_anchor_is_not_machine_id": version == "21.0.631"})
    if pack_id == LIGHTING:
        result += [{"code": "EXTERNAL_DENOISE_BLEND_REQUIRED", "control": "denoise_mix", "interval": "0 < weight < 1"},
                   {"code": "SHUTTER_ZERO_DURATION_UNSUPPORTED", "control": "shutter", "value": 0}]
    result.append({"code": "NATIVE_RENDER_EXECUTION_NOT_RUN", "real_dcc_verified": False})
    return result
