"""Fixed cloth source shaping plans; no HOM, execution or operation state.

The host collects every observation, owns the shaping SOP and transaction, and
rechecks the guards before writes and after cook/save/reopen. Comparisons here
only check supplied observations against a CPU expectation; they cannot prove
that collection, native cooking, simulation or scene persistence occurred.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
import hashlib
import json
import math
from pathlib import PurePosixPath
import struct
from typing import Mapping

SUPPORTED_VERSIONS = ("21.0.631", "22.0.429")
CLOTH = "vellum_cloth_v1"
ROLE = "cloth_wrinkle"
SCHEMA = "bridge.trusted-cloth-wrinkle-source-program/1"
PROGRAM_GENERATOR = "houdini_bridge.native_cloth_wrinkle_program.source_program/1"
WAVELENGTH_CONTRACT = "planar_source_scene_unit_sine_wavelength_native_thickness_half/1"
_SOURCE_FIELDS = {"origin", "role", "node_path", "output", "space", "frame", "position_precision",
                  "point_positions", "polygons", "bbox"}
_THICKNESS_FIELDS = {"origin", "role", "node_path", "parm", "type", "size",
                     "driven", "value", "gates"}
_SHAPE_FIELDS = {"origin", "role", "node_path", "category", "type", "task_owned",
                 "task_root", "input_node_path", "input_output", "input_index",
                 "input_geometry_sha256", "space", "frame", "vex_precision", "native_version"}


class NativeClothWrinkleError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _fail(code, detail):
    raise NativeClothWrinkleError(code, detail)


def _domain(pack_id, version):
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        _fail("UNSUPPORTED_NATIVE_VERSION", str(version))
    if pack_id != CLOTH:
        _fail("EXPLICIT_CLOTH_DOMAIN_REQUIRED", str(pack_id))


def _number(value, lo, hi, label):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not lo <= value <= hi or not math.isfinite(value)):
        _fail("UNSAFE_CLOTH_NUMERIC_CONTEXT", label)
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail("ACTUAL_CLOTH_GEOMETRY_REQUIRED", label + ": three components")
    return [_number(v, -1e6, 1e6, label) for v in value]


def _path(value):
    return (isinstance(value, str) and value.startswith("/") and value != "/"
            and str(PurePosixPath(value)) == value
            and all(part not in (".", "..") for part in value.split("/")))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _canonical_unit(vector):
    length = _norm(vector)
    axis = [v / length for v in vector]
    dominant = max(range(3), key=lambda i: abs(axis[i]))
    return [-v for v in axis] if axis[dominant] < 0 else axis


def _geometry(raw, role):
    if not isinstance(raw, Mapping) or set(raw) != _SOURCE_FIELDS:
        _fail("ACTUAL_CLOTH_GEOMETRY_REQUIRED", ",".join(sorted(_SOURCE_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != role
            or not _path(raw["node_path"]) or type(raw["output"]) is not int
            or raw["output"] != 0 or raw["space"] != "sop_local"):
        _fail("ACTUAL_CLOTH_GEOMETRY_REQUIRED", role + ": runtime SOP output 0 in sop_local space")
    frame = _number(raw["frame"], -1e6, 1e6, "source frame")
    positions = raw["point_positions"]
    polygons = raw["polygons"]
    if not isinstance(positions, (list, tuple)) or len(positions) < 3:
        _fail("ACTUAL_CLOTH_GEOMETRY_REQUIRED", "at least three actual point positions")
    points = [_vector(p, "point_positions") for p in positions]
    if raw["position_precision"] not in ("float32", "float64"):
        _fail("ACTUAL_CLOTH_PRECISION_REQUIRED", "actual P numeric storage float32 or float64")
    if raw["position_precision"] == "float32" and any(
            struct.unpack("!f", struct.pack("!f", v))[0] != v for p in points for v in p):
        _fail("ACTUAL_CLOTH_PRECISION_REQUIRED", "float32 observations must retain the actual stored numeric values")
    if not isinstance(polygons, (list, tuple)) or not polygons:
        _fail("ACTUAL_CLOTH_POLYGONS_REQUIRED", "ordered vertex point indices for each Polygon")
    faces = []
    for face in polygons:
        if (not isinstance(face, (list, tuple)) or len(face) < 3
                or any(type(i) is not int or not 0 <= i < len(points) for i in face)
                or len(set(face)) != len(face)):
            _fail("ACTUAL_CLOTH_POLYGONS_REQUIRED", "non-repeated in-range vertex indices")
        faces.append(list(face))
    if set(i for face in faces for i in face) != set(range(len(points))):
        _fail("ACTUAL_CLOTH_POLYGONS_REQUIRED", "all source points must belong to the polygon surface")
    bbox = raw["bbox"]
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 2:
        _fail("ACTUAL_CLOTH_GEOMETRY_REQUIRED", "bbox=[min,max]")
    bounds = [_vector(p, "bbox") for p in bbox]
    measured = [[min(p[i] for p in points) for i in range(3)],
                [max(p[i] for p in points) for i in range(3)]]
    if bounds != measured:
        _fail("ACTUAL_CLOTH_BBOX_MISMATCH", "bbox must agree with all collected point positions")
    return {"origin": "runtime_hom", "role": role, "node_path": raw["node_path"],
            "output": 0, "space": "sop_local", "frame": frame,
            "position_precision": raw["position_precision"],
            "point_positions": points, "polygons": faces, "bbox": bounds}


def source_geometry_sha256(source: Mapping) -> str:
    """Hash collected upstream observations, including identity and sample frame."""
    return _hash(_geometry(source, "source"))


def _ulp(value, precision):
    if precision == "float64":
        return math.ulp(value)
    return max(2. ** -149, math.ldexp(1., math.frexp(abs(value))[1] - 24))


def _tolerance(geometry):
    span = _norm(_sub(geometry["bbox"][1], geometry["bbox"][0]))
    epsilon = 2. ** (-23 if geometry["position_precision"] == "float32" else -52)
    resolution = max(_ulp(v, geometry["position_precision"]) for p in geometry["point_positions"] for v in p)
    return max(1e-12, 2 * resolution + 8 * epsilon * span)


def _readback_tolerance(upstream, actual, stage, basis, wavelength, amplitude):
    # Storage rounding plus conservative dot/subtract/multiply/divide/sin error.
    # sin is 1-Lipschitz in its phase; the bound grows with the actual phase span.
    storage = max(_ulp(v, actual["position_precision"]) for p in actual["point_positions"] for v in p)
    epsilon = 2. ** (-23 if stage["vex_precision"] == "32" else -52)
    span = _norm(_sub(upstream["bbox"][1], upstream["bbox"][0]))
    phase = max(abs(_dot(_sub(p, basis["anchor"]), basis["tangent"]))
                for p in upstream["point_positions"]) / wavelength if wavelength else 0.
    bound = 3 * storage + epsilon * (16 * span + amplitude * (8 + 32 * math.tau * phase))
    return max(1e-12, bound)


def _basis(geometry):
    points, faces = geometry["point_positions"], geometry["polygons"]
    extent = _norm(_sub(geometry["bbox"][1], geometry["bbox"][0]))
    tolerance = _tolerance(geometry)
    if extent <= 16 * tolerance:
        _fail("DEGENERATE_CLOTH_SOURCE", "two resolvable planar dimensions required")
    normals, edges = [], []
    for face in faces:
        # Translate before Newell's sum to avoid cancellation at large origins.
        vertices = [_sub(points[i], points[face[0]]) for i in face]
        pairs = list(zip(vertices, vertices[1:] + vertices[:1]))
        normal = [math.fsum((a[1] - b[1]) * (a[2] + b[2]) for a, b in pairs),
                  math.fsum((a[2] - b[2]) * (a[0] + b[0]) for a, b in pairs),
                  math.fsum((a[0] - b[0]) * (a[1] + b[1]) for a, b in pairs)]
        local_extent = max(_norm(_sub(a, b)) for a, b in pairs)
        if _norm(normal) <= local_extent * tolerance:
            _fail("DEGENERATE_CLOTH_SOURCE", "each Polygon must have resolvable nonzero area")
        normals.append(_canonical_unit(normal))
        for i, j in zip(face, face[1:] + face[:1]):
            edge = _sub(points[j], points[i])
            if _norm(edge) <= tolerance:
                _fail("DEGENERATE_CLOTH_SOURCE", "each polygon edge must have resolvable length")
            edges.append(edge)
    normal = normals[0]
    anchor = points[0]
    if (any(abs(_dot(n, normal)) < 1 - 1e-6 for n in normals)
            or any(abs(_dot(_sub(p, anchor), normal)) > tolerance for p in points)):
        _fail("PLANAR_CLOTH_SOURCE_REQUIRED", "all points and Polygon normals must define one plane")
    tangent = _canonical_unit(max(edges, key=_norm))
    if abs(_dot(tangent, normal)) > 1e-6:
        _fail("PLANAR_CLOTH_SOURCE_REQUIRED", "actual polygon edge is not tangent to the source plane")
    side = [normal[1] * tangent[2] - normal[2] * tangent[1],
            normal[2] * tangent[0] - normal[0] * tangent[2],
            normal[0] * tangent[1] - normal[1] * tangent[0]]
    transverse = [_dot(_sub(p, anchor), side) for p in points]
    if max(transverse) - min(transverse) <= 16 * tolerance:
        _fail("DEGENERATE_CLOTH_SOURCE", "two resolvable planar dimensions required")
    return {"anchor": anchor, "normal": normal, "tangent": tangent}, edges


def _gate_matches(fact, expected):
    value = fact.get("value")
    if value == expected:
        return True
    tokens, labels = fact.get("menu_tokens", ()), fact.get("menu_labels", ())
    if not isinstance(tokens, (list, tuple)) or not isinstance(labels, (list, tuple)):
        return False
    index = tokens.index(value) if value in tokens else value if type(value) is int else -1
    return 0 <= index < len(tokens) and (tokens[index] == expected
            or (index < len(labels) and labels[index] == expected))


def _thickness(raw):
    if not isinstance(raw, Mapping) or set(raw) != _THICKNESS_FIELDS:
        _fail("ACTUAL_NATIVE_THICKNESS_REQUIRED", ",".join(sorted(_THICKNESS_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != "constraints"
            or raw["parm"] != "thickness" or not _path(raw["node_path"])
            or raw["type"] != "float" or type(raw["size"]) is not int
            or raw["size"] != 1 or raw["driven"] is not False):
        _fail("ACTUAL_NATIVE_THICKNESS_REQUIRED", "actual undriven scalar constraints.thickness")
    gates = raw["gates"]
    if not isinstance(gates, Mapping) or set(gates) != {"constrainttype", "dothickness"}:
        _fail("ACTUAL_NATIVE_THICKNESS_REQUIRED", "actual cloth and dothickness gates")
    for parm, typ, expected in (("constrainttype", "ordinal", "cloth"), ("dothickness", "ordinal", "on")):
        fact = gates[parm]
        if (not isinstance(fact, Mapping) or fact.get("origin") != "runtime_hom"
                or fact.get("type") != typ or type(fact.get("size")) is not int
                or fact["size"] != 1 or fact.get("driven") is not False
                or not _gate_matches(fact, expected)):
            _fail("ACTUAL_NATIVE_THICKNESS_REQUIRED", "active undriven constraints." + parm)
    return {"origin": "runtime_hom", "role": "constraints", "node_path": raw["node_path"],
            "parm": "thickness", "type": "float", "size": 1, "driven": False,
            "value": _number(raw["value"], 0, 100, "native thickness"),
            "gates": {"constrainttype": "cloth", "dothickness": "on"}}


def _shape_stage(raw, source, thickness, version):
    if not isinstance(raw, Mapping) or set(raw) != _SHAPE_FIELDS:
        _fail("ACTUAL_OWNED_CLOTH_SHAPE_STAGE_REQUIRED", ",".join(sorted(_SHAPE_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != ROLE
            or raw["category"] != "sop" or raw["type"] != "attribwrangle"
            or raw["task_owned"] is not True or not _path(raw["task_root"])
            or not _path(raw["node_path"]) or raw["node_path"] == source["node_path"]
            or not raw["node_path"].startswith(raw["task_root"] + "/")
            or not thickness["node_path"].startswith(raw["task_root"] + "/")
            or raw["input_node_path"] != source["node_path"]
            or type(raw["input_output"]) is not int or raw["input_output"] != 0
            or type(raw["input_index"]) is not int or raw["input_index"] != 0
            or raw["space"] != "sop_local" or raw["native_version"] != version):
        _fail("ACTUAL_OWNED_CLOTH_SHAPE_STAGE_REQUIRED", "owned attribwrangle input 0 directly from source[0]")
    frame = _number(raw["frame"], -1e6, 1e6, "shape frame")
    if raw["vex_precision"] not in ("32", "64"):
        _fail("ACTUAL_CLOTH_PRECISION_REQUIRED", "actual explicit vex_precision=32 or 64; auto is unresolved")
    if source["position_precision"] == "float64" and raw["vex_precision"] != "64":
        _fail("ACTUAL_CLOTH_PRECISION_REQUIRED", "float64 P requires explicit 64-bit VEX to preserve upstream positions")
    if frame != source["frame"]:
        _fail("CLOTH_SHAPE_INPUT_CONTEXT_MISMATCH", "source and shape sample frames must agree")
    if raw["input_geometry_sha256"] != _hash(source):
        _fail("CLOTH_SHAPE_INPUT_CONTEXT_MISMATCH", "independently collected input 0 must equal unmodified source")
    result = dict(raw)
    result["frame"] = frame
    return result


def _sampling(source, basis, edges, wavelength, amplitude, stage):
    tolerance = _tolerance(source)
    distances = sorted(_dot(_sub(p, basis["anchor"]), basis["tangent"]) for p in source["point_positions"])
    distinct = [distances[0]]
    for value in distances[1:]:
        if value - distinct[-1] > tolerance:
            distinct.append(value)
    span = distances[-1] - distances[0]
    max_step = max(abs(_dot(e, basis["tangent"])) for e in edges)
    if wavelength == 0:
        return {"longitudinal_span": span, "distinct_longitudinal_samples": len(distinct),
                "period_observable": False, "amplitude_observable": False,
                "maximum_projected_edge_step": max_step, "recommended_maximum_step": None,
                "required_maximum_edge_segments": 1}
    # Bound float VEX phase loss instead of silently clamping wavelength.
    epsilon = 2. ** (-23 if stage["vex_precision"] == "32" else -52)
    maximum_phase = 16384 * 2. ** -23 / epsilon
    if max(abs(v) for v in distances) / wavelength > maximum_phase or not math.isfinite(math.tau / wavelength):
        _fail("UNSAFE_CLOTH_WAVELENGTH_CONTEXT", "wavelength is below source coordinate/float phase resolution")
    maximum_gap = max((b - a for a, b in zip(distinct, distinct[1:])), default=span)
    sufficient = (span >= wavelength - tolerance and len(distinct) >= 5
                  and maximum_gap <= wavelength / 4 + tolerance
                  and max_step <= wavelength / 4 + tolerance)
    values = [math.sin(math.tau * distance / wavelength) for distance in distances]
    precision_bound = _readback_tolerance(source, source, stage, basis, wavelength, amplitude)
    amplitude_observable = amplitude > 8 * precision_bound and min(values) <= -.9 and max(values) >= .9
    return {"longitudinal_span": span, "distinct_longitudinal_samples": len(distinct),
            "period_observable": sufficient and amplitude_observable,
            "amplitude_observable": amplitude_observable,
            "maximum_projected_edge_step": max_step, "maximum_longitudinal_sample_gap": maximum_gap,
            "recommended_maximum_step": wavelength / 4,
            "required_maximum_edge_segments": max(1, math.ceil(max_step / (wavelength / 4)))}


def source_program(pack_id: str, version: str, wrinkle_scale, *, source: Mapping,
                   thickness: Mapping, shape_stage: Mapping) -> dict:
    """Generate fixed numeric VEX from host observations, never supplied code."""
    _domain(pack_id, version)
    wavelength = _number(wrinkle_scale, 0, 100, "wrinkle_scale scene-unit wavelength")
    geometry = _geometry(source, "source")
    native_thickness = _thickness(thickness)
    stage = _shape_stage(shape_stage, geometry, native_thickness, version)
    basis, edges = _basis(geometry)
    amplitude = native_thickness["value"] / 2
    sampling = _sampling(geometry, basis, edges, wavelength, amplitude, stage)
    for point in geometry["point_positions"]:
        distance = _dot(_sub(point, basis["anchor"]), basis["tangent"])
        displacement = amplitude * math.sin(math.tau * distance / wavelength) if wavelength else 0.
        if any(abs(v + n * displacement) > 1e6 for v, n in zip(point, basis["normal"])):
            _fail("UNSAFE_CLOTH_DISPLACEMENT_CONTEXT", "predicted output exceeds the finite position bounds")
    number = lambda x: format(float(x), ".17g")
    lines = ['vector bridge_source = point(0, "P", @ptnum);']
    if wavelength:
        for name in ("anchor", "normal", "tangent"):
            lines.append("vector bridge_" + name + " = set(" + ", ".join(number(v) for v in basis[name]) + ");")
        lines.extend(["float bridge_distance = dot(bridge_source - bridge_anchor, bridge_tangent);",
                      "@P = bridge_source + bridge_normal * (" + number(amplitude)
                      + " * sin(6.283185307179586 * bridge_distance / " + number(wavelength) + "));"])
    else:
        lines.append("@P = bridge_source;")
    program = "\n".join(lines) + "\n"
    guards = [{"kind": "source_geometry", "role": "source", "output": 0,
               "geometry_sha256": _hash(geometry)},
              {"kind": "native_thickness", "observation": native_thickness},
              {"kind": "owned_shape_stage", "observation": stage}]
    return {"schema": SCHEMA, "generator": PROGRAM_GENERATOR, "domain_pack": pack_id,
            "native_version": version, "semantic_contract": WAVELENGTH_CONTRACT,
            "role": ROLE, "parm": "snippet", "wrinkle_scale": wavelength,
            "amplitude": amplitude, "basis": basis, "sampling": sampling,
            "frozen_readback_guards": guards, "program": program,
            "sha256": hashlib.sha256(program.encode()).hexdigest()}


def validate_source_program(registration: Mapping, *, source: Mapping,
                            thickness: Mapping, shape_stage: Mapping) -> None:
    """Regenerate trusted code and reject any changed context or registration."""
    if not isinstance(registration, Mapping) or registration.get("schema") != SCHEMA:
        _fail("UNTRUSTED_CLOTH_SOURCE_PROGRAM", "registered fixed generator required")
    expected = source_program(registration.get("domain_pack"), registration.get("native_version"),
                              registration.get("wrinkle_scale"), source=source,
                              thickness=thickness, shape_stage=shape_stage)
    old_guards = registration.get("frozen_readback_guards")
    if not isinstance(old_guards, list) or len(old_guards) != 3:
        _fail("UNTRUSTED_CLOTH_SOURCE_PROGRAM", "three typed frozen guards required")
    for old, current, label in zip(old_guards, expected["frozen_readback_guards"], ("SOURCE", "THICKNESS", "SHAPE_STAGE")):
        if old != current:
            _fail("CLOTH_" + label + "_CONTEXT_CHANGED", "frozen " + label.lower() + " observation changed")
    if dict(registration) != expected:
        _fail("UNTRUSTED_CLOTH_SOURCE_PROGRAM", "fixed program, hash, basis and semantic registration must regenerate exactly")


def control_write_plan(pack_id, wrinkle_scale, version, *, source, thickness, shape_stage):
    registration = source_program(pack_id, version, wrinkle_scale, source=source,
                                  thickness=thickness, shape_stage=shape_stage)
    return [{"role": ROLE, "parm": parm, "value": value, "native_type": native_type,
             "phase": "source_program", "require_writable": True, "require_readback": True,
             "invalidates_from": "source_layout_control", "required_gates": [],
             "frozen_readback_guards": copy.deepcopy(registration["frozen_readback_guards"]),
             **extra}
            for parm, value, native_type, extra in (
                ("class", "Points", "ordinal", {"value_kind": "menu_label"}),
                ("group", "", "string", {}),
                ("snippet", registration["program"], "string", {"trusted_program": registration}))]


def validate_control_write_plan(writes, observations, *, source, thickness, shape_stage):
    """Validate only this complete fixed write plan and actual writable fields."""
    if not isinstance(writes, list) or len(writes) != 3 or not isinstance(writes[2], Mapping):
        _fail("UNTRUSTED_CLOTH_SOURCE_PROGRAM", "complete three-field write plan required")
    registration = writes[2].get("trusted_program")
    validate_source_program(registration, source=source, thickness=thickness, shape_stage=shape_stage)
    expected = control_write_plan(registration["domain_pack"], registration["wrinkle_scale"],
                                  registration["native_version"], source=source,
                                  thickness=thickness, shape_stage=shape_stage)
    if writes != expected:
        _fail("UNTRUSTED_CLOTH_SOURCE_PROGRAM", "write plan must regenerate exactly")
    for write in writes:
        actual = observations.get((ROLE, write["parm"]), {})
        if (actual.get("origin") != "runtime_hom" or actual.get("type") != write["native_type"]
                or type(actual.get("size")) is not int or actual["size"] != 1):
            _fail("NATIVE_CONTROL_INTERFACE_REQUIRED", ROLE + "/" + write["parm"])
        if any(actual.get(flag) is not False for flag in ("locked", "disabled", "hidden", "driven")):
            _fail("NATIVE_CONTROL_GATE_BLOCKED", ROLE + "/" + write["parm"])
        if write["parm"] == "class" and "Points" not in actual.get("menu_labels", ()):
            _fail("NATIVE_CONTROL_INTERFACE_REQUIRED", "actual class Points menu label required")


def validate_geometry_readback(registration, *, source, thickness, shape_stage, shaped_geometry):
    """Compare all supplied output points/connectivity to the fixed expectation.

    A local band or coarse source still consumes wavelength, but cannot establish
    a full observed period. Observability flags do not constitute an independent
    period fit, a native-cook receipt or physical cloth evidence.
    """
    validate_source_program(registration, source=source, thickness=thickness, shape_stage=shape_stage)
    upstream = _geometry(source, "source")
    actual = _geometry(shaped_geometry, ROLE)
    if (actual["node_path"] != shape_stage["node_path"] or actual["frame"] != upstream["frame"]
            or len(actual["point_positions"]) != len(upstream["point_positions"])
            or actual["polygons"] != upstream["polygons"]):
        _fail("CLOTH_SHAPE_READBACK_MISMATCH", "output identity, frame, point count or ordered connectivity changed")
    wavelength = registration["wrinkle_scale"]
    amplitude = registration["amplitude"]
    basis = registration["basis"]
    if actual["position_precision"] != upstream["position_precision"]:
        _fail("CLOTH_SHAPE_READBACK_MISMATCH", "P numeric storage precision changed")
    tolerance = _readback_tolerance(upstream, actual, shape_stage, basis, wavelength, amplitude)
    max_error, max_tangent_error, normal_values = 0., 0., []
    for old, new in zip(upstream["point_positions"], actual["point_positions"]):
        if not wavelength and old != new:
            _fail("CLOTH_SHAPE_READBACK_MISMATCH", "flat output must restore every unmodified source position exactly")
        distance = _dot(_sub(old, basis["anchor"]), basis["tangent"])
        expected = amplitude * math.sin(math.tau * distance / wavelength) if wavelength else 0.
        delta = _sub(new, old)
        normal = _dot(delta, basis["normal"])
        tangent_error = _norm([v - normal * n for v, n in zip(delta, basis["normal"])])
        error = _norm([v - expected * n for v, n in zip(delta, basis["normal"])])
        if error > tolerance or tangent_error > tolerance:
            _fail("CLOTH_SHAPE_READBACK_MISMATCH", "all output points must match sine normal displacement from unmodified source")
        max_error = max(max_error, error)
        max_tangent_error = max(max_tangent_error, tangent_error)
        normal_values.append(normal)
    sampling = registration["sampling"]
    amplitude_observable = (bool(wavelength and amplitude > 8 * tolerance) and min(normal_values) <= -.9 * amplitude
                            and max(normal_values) >= .9 * amplitude and sampling["amplitude_observable"])
    return {"schema": "bridge.cloth-wrinkle-observation-comparison/1",
            "scope": "supplied_runtime_hom_geometry_observations",
            "semantic_contract": WAVELENGTH_CONTRACT, "wrinkle_scale": wavelength,
            "amplitude": amplitude, "pointwise_formula_matches": True,
            "period_observable": sampling["period_observable"] and amplitude_observable,
            "amplitude_observable": amplitude_observable, "sampling": copy.deepcopy(sampling),
            "position_tolerance": tolerance, "position_precision": actual["position_precision"],
            "vex_precision": shape_stage["vex_precision"],
            "maximum_position_error": max_error, "maximum_tangent_error": max_tangent_error}


def validate_applied_readback(writes, observations, *, source, thickness, shape_stage, shaped_geometry):
    validate_control_write_plan(writes, observations, source=source, thickness=thickness, shape_stage=shape_stage)
    for write in writes:
        actual = observations[(ROLE, write["parm"])]
        matched = (_gate_matches(actual, write["value"]) if write["parm"] == "class"
                   else actual.get("value") == write["value"])
        if not matched:
            _fail("NATIVE_CONTROL_READBACK_MISMATCH", ROLE + "/" + write["parm"])
    return validate_geometry_readback(writes[2]["trusted_program"], source=source, thickness=thickness,
                                      shape_stage=shape_stage, shaped_geometry=shaped_geometry)
