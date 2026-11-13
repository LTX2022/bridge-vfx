"""Fixed Ocean surface masks from supplied host observations.

The host owns collection, connections, transactions, native cooking and scene
persistence. This module does not calculate cusp, execute VEX or issue receipts.
Coverage is an owned rest-cell algorithm, not native foam or physical evidence.
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
OCEAN = "water_ocean_v1"
ROLE = "ocean_masks"
SCHEMA = "bridge.trusted-ocean-mask-program/1"
PROGRAM_GENERATOR = "houdini_bridge.native_ocean_mask_program.mask_program/1"
COVERAGE_CONTRACT = "owned_ocean_native_cusp_rest_cell_coverage/1"
STATIC_SIGNATURE_SHA256 = "95bf3f1fe30cf8f28d34676890afc3c3d2ba0c6c522a7ed35eba92e706dd8033"
MAX_POINTS = 8192
_GEOMETRY_FIELDS = {"origin", "role", "node_path", "output", "space", "frame",
                    "position_precision", "point_positions", "polygons", "bbox"}
_SPECTRUM_FIELDS = {"origin", "role", "node_path", "category", "type", "task_owned",
                    "task_root", "output", "space", "frame", "sample_time", "volumes",
                    "geometry_sha256"}
_VOLUME_FIELDS = {"primitive_index", "name", "type", "resolution", "transform",
                  "storage", "primitive_attributes"}
_STAGE_FIELDS = {"origin", "role", "node_path", "category", "type", "task_owned",
                 "task_root", "space", "frame", "native_version", "vex_precision", "inputs"}
_EMIT_FIELDS = {"origin", "role", "node_path", "category", "type", "task_owned",
                "task_root", "frame", "parameters", "gates"}
_ATTRIBUTES = {"bridge_ocean_layers": "int", "bridge_ocean_cusp": "float",
               "bridge_ocean_dual_area": "float", "cusp_mask": "float", "foam_mask": "float"}


class NativeOceanMaskError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _fail(code, detail):
    raise NativeOceanMaskError(code, detail)


def _domain(pack_id, version):
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        _fail("UNSUPPORTED_NATIVE_VERSION", str(version))
    if pack_id != OCEAN:
        _fail("EXPLICIT_OCEAN_DOMAIN_REQUIRED", str(pack_id))


def _number(value, lo, hi, label):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not lo <= value <= hi or not math.isfinite(value)):
        _fail("UNSAFE_OCEAN_NUMERIC_CONTEXT", label)
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", label + ": three components")
    return [_number(v, -1e6, 1e6, label) for v in value]


def _path(value):
    return (isinstance(value, str) and value.startswith("/") and value != "/"
            and str(PurePosixPath(value)) == value
            and all(part not in (".", "..") for part in value.split("/")))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _float32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _ulp(value, precision):
    if precision == "float64":
        return math.ulp(value)
    return max(2. ** -149, math.ldexp(1., math.frexp(abs(value))[1] - 24))


def _geometry(raw, role):
    if not isinstance(raw, Mapping) or set(raw) != _GEOMETRY_FIELDS:
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", ",".join(sorted(_GEOMETRY_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != role
            or not _path(raw["node_path"]) or type(raw["output"]) is not int
            or raw["output"] != 0 or raw["space"] != "sop_local"):
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", role + ": actual SOP output 0 in sop_local space")
    frame = _number(raw["frame"], -1e6, 1e6, "geometry frame")
    positions, polygons = raw["point_positions"], raw["polygons"]
    if not isinstance(positions, (list, tuple)) or not 3 <= len(positions) <= MAX_POINTS:
        _fail("OCEAN_POINT_BUDGET_REQUIRED", "3..8192 actual points required")
    points = [_vector(p, "point_positions") for p in positions]
    precision = raw["position_precision"]
    if precision not in ("float32", "float64"):
        _fail("ACTUAL_OCEAN_PRECISION_REQUIRED", "actual P storage float32 or float64")
    if precision == "float32" and any(_float32(v) != v for p in points for v in p):
        _fail("ACTUAL_OCEAN_PRECISION_REQUIRED", "retain actual stored float32 P values")
    if not isinstance(polygons, (list, tuple)) or not polygons:
        _fail("ACTUAL_OCEAN_POLYGONS_REQUIRED", "actual ordered Polygon vertex indices")
    faces = []
    for face in polygons:
        if (not isinstance(face, (list, tuple)) or len(face) < 3
                or any(type(i) is not int or not 0 <= i < len(points) for i in face)
                or len(set(face)) != len(face)):
            _fail("ACTUAL_OCEAN_POLYGONS_REQUIRED", "non-repeated in-range ordered vertex indices")
        faces.append(list(face))
    if set(i for face in faces for i in face) != set(range(len(points))):
        _fail("ACTUAL_OCEAN_POLYGONS_REQUIRED", "every point must belong to the Polygon surface")
    bbox = raw["bbox"]
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 2:
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", "bbox=[min,max]")
    bounds = [_vector(p, "bbox") for p in bbox]
    measured = [[min(p[i] for p in points) for i in range(3)],
                [max(p[i] for p in points) for i in range(3)]]
    if bounds != measured:
        _fail("ACTUAL_OCEAN_BBOX_MISMATCH", "bbox must match collected P")
    return {"origin": "runtime_hom", "role": role, "node_path": raw["node_path"],
            "output": 0, "space": "sop_local", "frame": frame,
            "position_precision": precision, "point_positions": points,
            "polygons": faces, "bbox": bounds}


def source_geometry_sha256(geometry: Mapping, role="source") -> str:
    """Hash actual source or evaluated surface identity, frame, P and topology."""
    if role not in ("source", "evaluate"):
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", "source or evaluate role required")
    return _hash(_geometry(geometry, role))


def _rest_areas(source):
    points, precision = source["point_positions"], source["position_precision"]
    areas, spans, resolutions = [], [], []
    for face in source["polygons"]:
        vertices = [_sub(points[i], points[face[0]]) for i in face]
        span = max(_norm(v) for v in vertices)
        resolution = max(_ulp(v, precision) for i in face for v in points[i])
        epsilon = 2. ** (-23 if precision == "float32" else -52)
        tolerance = max(1e-12, 2 * resolution + 8 * epsilon * span)
        edges = [_sub(b, a) for a, b in zip(vertices, vertices[1:] + vertices[:1])]
        crosses = [_cross(a, b) for a, b in zip(vertices, vertices[1:] + vertices[:1])]
        normal = [math.fsum(v[i] for v in crosses) for i in range(3)]
        length = _norm(normal)
        if (span <= 16 * tolerance or length <= 16 * span * tolerance
                or any(_norm(e) <= 16 * tolerance for e in edges)):
            _fail("DEGENERATE_OCEAN_REST_POLYGON", "each source Polygon needs resolvable edges and nonzero area")
        unit = [v / length for v in normal]
        if any(abs(_dot(v, unit)) > tolerance for v in vertices):
            _fail("PLANAR_OCEAN_REST_POLYGON_REQUIRED", "each actual source/rest Polygon must be planar")
        # Every vertex must lie on the interior side of every ordered edge.
        # Consecutive turns alone would also accept a self-intersecting star.
        for index, edge in enumerate(edges):
            distances = [_dot(_cross(edge, _sub(v, vertices[index])), unit) / _norm(edge)
                         for v in vertices]
            if min(distances) < -tolerance or max(distances) <= 16 * tolerance:
                _fail("CONVEX_OCEAN_REST_POLYGON_REQUIRED", "concave or self-intersecting source Polygon")
        areas.append(length / 2)
        spans.append(span)
        resolutions.append(resolution)
    dual = [0.] * len(points)
    for face, area in zip(source["polygons"], areas):
        for index in face:
            dual[index] += area / len(face)
    return dual, areas, spans, resolutions


def _json_fact(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return _number(value, -1e30, 1e30, "spectrum primitive attribute")
    if isinstance(value, (list, tuple)):
        return [_json_fact(v) for v in value]
    if isinstance(value, Mapping) and all(isinstance(k, str) for k in value):
        return {k: _json_fact(v) for k, v in value.items()}
    _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "finite actual primitive attribute summary")


def _spectrum(raw, verify_hash=True):
    if not isinstance(raw, Mapping) or set(raw) != _SPECTRUM_FIELDS:
        _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", ",".join(sorted(_SPECTRUM_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != "spectrum"
            or raw["category"] != "sop" or raw["type"] != "oceanspectrum"
            or raw["task_owned"] is not True or not _path(raw["task_root"])
            or not _path(raw["node_path"]) or not raw["node_path"].startswith(raw["task_root"] + "/")
            or type(raw["output"]) is not int or raw["output"] != 0 or raw["space"] != "sop_local"):
        _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "actual owned oceanspectrum output 0")
    result = dict(raw)
    result["frame"] = _number(raw["frame"], -1e6, 1e6, "spectrum frame")
    result["sample_time"] = _number(raw["sample_time"], -1e6, 1e6, "actual hou.time()")
    rows = raw["volumes"]
    if not isinstance(rows, (list, tuple)) or not rows:
        _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "actual spectral Volume primitives required")
    volumes = []
    previous_index = -1
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _VOLUME_FIELDS:
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "complete actual Volume summary")
        index, res, transform, storage = (row["primitive_index"], row["resolution"],
                                          row["transform"], row["storage"])
        if (type(index) is not int or index <= previous_index or row["type"] != "Volume"
                or not isinstance(row["name"], str) or not row["name"]):
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "ordered unique actual Volume primitive indices and names")
        previous_index = index
        if (not isinstance(res, (list, tuple)) or len(res) != 3
                or any(type(v) is not int or v < 1 for v in res)):
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "actual positive integer Volume resolution")
        if (not isinstance(transform, Mapping) or set(transform) != {"matrix", "translation"}
                or not isinstance(transform["matrix"], (list, tuple)) or len(transform["matrix"]) != 9):
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "actual Volume 3x3 matrix and position")
        matrix = [_number(v, -1e6, 1e6, "volume transform") for v in transform["matrix"]]
        a, b, c = matrix[:3], matrix[3:6], matrix[6:9]
        if abs(_dot(a, _cross(b, c))) <= 1e-30:
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "invertible actual Volume transform")
        canonical_transform = {"matrix": matrix, "translation": _vector(transform["translation"], "volume position")}
        if (not isinstance(storage, Mapping)
                or set(storage) != {"precision", "voxel_count", "values_sha256", "border_type"}
                or storage["precision"] not in ("float32", "float64")
                or type(storage["voxel_count"]) is not int or storage["voxel_count"] != math.prod(res)
                or not _sha(storage["values_sha256"])
                or not isinstance(storage["border_type"], str) or not storage["border_type"]):
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "actual voxel storage precision, count, values digest and border type")
        attrs = row["primitive_attributes"]
        if not isinstance(attrs, Mapping) or not all(isinstance(k, str) for k in attrs):
            _fail("ACTUAL_OCEAN_SPECTRUM_REQUIRED", "actual primitive attributes")
        volumes.append({"primitive_index": index, "name": row["name"], "type": "Volume",
                        "resolution": list(res), "transform": canonical_transform,
                        "storage": dict(storage), "primitive_attributes": _json_fact(attrs)})
    named = {name: [row for row in volumes if row["name"] == name]
             for name in ("amplitude", "phase", "frequency")}
    count = len(named["amplitude"])
    if not count or any(len(named[name]) != count for name in named):
        _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "nonzero complete amplitude/phase/frequency layers")
    for layer in zip(named["amplitude"], named["phase"], named["frequency"]):
        representative = layer[0]
        res = representative["resolution"]
        if sum(v == 1 for v in res) != 1 or any(v < 2 or v & (v - 1) for v in res if v != 1):
            _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "planar power-of-two actual spectrum resolution")
        if any(row["resolution"] != res or row["transform"] != representative["transform"] for row in layer[1:]):
            _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "each layer's actual spectral volumes must correspond")
        attrs = representative["primitive_attributes"]
        if not {"chop", "timeoffset"} <= set(attrs):
            _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "actual amplitude chop and timeoffset attributes")
        for name in ("chop", "timeoffset", "timescale"):
            if name in attrs:
                _number(attrs[name], -1e6, 1e6, "actual amplitude " + name)
    result["volumes"] = volumes
    result.pop("geometry_sha256")
    digest = _hash(result)
    if verify_hash and raw["geometry_sha256"] != digest:
        _fail("OCEAN_SPECTRUM_HASH_MISMATCH", "canonical digest must match actual spectrum observations")
    result["geometry_sha256"] = digest
    return result, count


def spectrum_geometry_sha256(spectrum: Mapping) -> str:
    """Hash collected Volume summaries and context, excluding the digest itself."""
    return _spectrum(spectrum, verify_hash=False)[0]["geometry_sha256"]


def _gate_matches(fact, expected):
    value = fact.get("value")
    if type(value) is type(expected) and value == expected:
        return True
    tokens, labels = fact.get("menu_tokens", ()), fact.get("menu_labels", ())
    if not isinstance(tokens, (list, tuple)) or not isinstance(labels, (list, tuple)):
        return False
    index = tokens.index(value) if value in tokens else value if type(value) is int else -1
    return 0 <= index < len(tokens) and (tokens[index] == expected
            or (index < len(labels) and labels[index] == expected))


def _native_emit(raw):
    if not isinstance(raw, Mapping) or set(raw) != _EMIT_FIELDS:
        _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", ",".join(sorted(_EMIT_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != "foam_emit"
            or raw["category"] != "sop" or raw["type"] != "oceanfoam"
            or raw["task_owned"] is not True or not _path(raw["task_root"])
            or not _path(raw["node_path"]) or not raw["node_path"].startswith(raw["task_root"] + "/")):
        _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", "actual owned native oceanfoam")
    parameters = raw["parameters"]
    if not isinstance(parameters, Mapping) or set(parameters) != {"mincusp", "density"}:
        _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", "actual scalar mincusp and density")
    facts = {}
    for name, fact in parameters.items():
        if (not isinstance(fact, Mapping) or fact.get("origin") != "runtime_hom"
                or fact.get("type") != "float" or type(fact.get("size")) is not int
                or fact["size"] != 1 or fact.get("driven") is not False):
            _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", "actual undriven scalar " + name)
        facts[name] = {"origin": "runtime_hom", "type": "float", "size": 1,
                       "driven": False, "value": _number(fact.get("value"), 0, 100, name)}
    gates = raw["gates"]
    required = {"mode": ("ordinal", "emit"), "region": ("ordinal", "grid"),
                "domincusp": ("toggle", 1), "dominvel": ("toggle", 0),
                "dominheight": ("toggle", 0), "dodisplace": ("toggle", 0)}
    if not isinstance(gates, Mapping) or set(gates) != set(required):
        _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", "actual native emission gates")
    canonical_gates = {}
    for name, (typ, expected) in required.items():
        fact = gates[name]
        if (not isinstance(fact, Mapping) or fact.get("origin") != "runtime_hom"
                or fact.get("type") != typ or type(fact.get("size")) is not int
                or fact["size"] != 1 or fact.get("driven") is not False
                or not _gate_matches(fact, expected)):
            _fail("ACTUAL_NATIVE_OCEAN_EMIT_REQUIRED", "active undriven native " + name)
        canonical_gates[name] = {"origin": "runtime_hom", "type": typ, "size": 1,
                                 "driven": False, "value": expected}
    return {**dict(raw), "frame": _number(raw["frame"], -1e6, 1e6, "emit frame"),
            "parameters": facts, "gates": canonical_gates}


def _stage(raw, source, surface, spectrum, native_emit, version):
    if not isinstance(raw, Mapping) or set(raw) != _STAGE_FIELDS:
        _fail("ACTUAL_OWNED_OCEAN_MASK_STAGE_REQUIRED", ",".join(sorted(_STAGE_FIELDS)))
    if (raw["origin"] != "runtime_hom" or raw["role"] != ROLE
            or raw["category"] != "sop" or raw["type"] != "attribwrangle"
            or raw["task_owned"] is not True or not _path(raw["task_root"])
            or not _path(raw["node_path"]) or not raw["node_path"].startswith(raw["task_root"] + "/")
            or raw["space"] != "sop_local" or raw["native_version"] != version):
        _fail("ACTUAL_OWNED_OCEAN_MASK_STAGE_REQUIRED", "actual owned attribwrangle and version")
    if raw["vex_precision"] not in ("32", "64"):
        _fail("ACTUAL_OCEAN_PRECISION_REQUIRED", "actual explicit VEX precision 32 or 64")
    if any(g["position_precision"] == "float64" for g in (source, surface)) and raw["vex_precision"] != "64":
        _fail("ACTUAL_OCEAN_PRECISION_REQUIRED", "float64 P requires explicit 64-bit VEX")
    frame = _number(raw["frame"], -1e6, 1e6, "mask stage frame")
    inputs = raw["inputs"]
    expected = [{"input_index": i, "node_path": g["node_path"], "output": 0, "geometry_sha256": digest}
                for i, g, digest in ((0, surface, _hash(surface)),
                                     (1, spectrum, spectrum["geometry_sha256"]), (2, source, _hash(source)))]
    if (not isinstance(inputs, (list, tuple)) or len(inputs) != 3
            or any(not isinstance(row, Mapping) or set(row) != set(want)
                   or type(row["input_index"]) is not int or type(row["output"]) is not int
                   or dict(row) != want for row, want in zip(inputs, expected))):
        _fail("OCEAN_MASK_INPUT_CONTEXT_MISMATCH", "independent actual input 0=evaluate, 1=spectrum, 2=source observations")
    paths = [source["node_path"], surface["node_path"], spectrum["node_path"],
             native_emit["node_path"], raw["node_path"]]
    if (len(set(paths)) != len(paths)
            or any(not path.startswith(raw["task_root"] + "/") for path in paths)
            or any(g["task_root"] != raw["task_root"] for g in (spectrum, native_emit))):
        _fail("OCEAN_MASK_INPUT_CONTEXT_MISMATCH", "distinct owned task paths; no mask feedback or emitter substitution")
    if any(g["frame"] != frame for g in (source, surface, spectrum, native_emit)):
        _fail("OCEAN_MASK_INPUT_CONTEXT_MISMATCH", "all observations must be collected at the same actual frame")
    if (len(source["point_positions"]) != len(surface["point_positions"])
            or source["polygons"] != surface["polygons"]):
        _fail("OCEAN_REST_SURFACE_CORRESPONDENCE_REQUIRED", "same actual point count and ordered Polygon topology")
    return {**dict(raw), "frame": frame, "inputs": expected}


def mask_program(pack_id: str, version: str, *, source: Mapping, surface: Mapping,
                 spectrum: Mapping, mask_stage: Mapping, native_emit: Mapping, foam: bool) -> dict:
    """Build trusted VEX; sample time and input arrays are never baked in code."""
    _domain(pack_id, version)
    if type(foam) is not bool:
        _fail("EXPLICIT_OCEAN_FOAM_BOOL_REQUIRED", "foam must be bool")
    rest, evaluated = _geometry(source, "source"), _geometry(surface, "evaluate")
    spectra, layers = _spectrum(spectrum)
    native = _native_emit(native_emit)
    stage = _stage(mask_stage, rest, evaluated, spectra, native, version)
    dual, areas, _, _ = _rest_areas(rest)
    density, threshold = (native["parameters"][name]["value"] for name in ("density", "mincusp"))
    number = lambda value: format(0. if value == 0 else float(value), ".17g")
    lines = [
        '#include <ocean.h>',
        'vector bridge_rest = point(2, "P", @ptnum);',
        'vector bridge_disp = 0;',
        'vector bridge_velocity = 0;',
        'float bridge_cusp = 0;',
        'vector bridge_cuspdir = 0;',
        'oceanSampleLayers(@OpInput2, "", @Time, bridge_rest, 0.0, 0, 0.0, 0,',
        '                  bridge_disp, bridge_velocity, bridge_cusp, bridge_cuspdir);',
        'i@bridge_ocean_layers = nprimsByName(@OpInput2, "amplitude");',
        'f@bridge_ocean_cusp = bridge_cusp;',
        'float bridge_dual_area = 0;',
        'int bridge_polygons[] = pointprims(2, @ptnum);',
        'foreach (int bridge_prim; bridge_polygons)',
        '{',
        '    int bridge_vertices[] = primpoints(2, bridge_prim);',
        '    vector bridge_anchor = point(2, "P", bridge_vertices[0]);',
        '    vector bridge_twice_area = 0;',
        '    for (int bridge_i = 0; bridge_i < len(bridge_vertices); bridge_i++)',
        '    {',
        '        vector bridge_a = point(2, "P", bridge_vertices[bridge_i]) - bridge_anchor;',
        '        vector bridge_b = point(2, "P", bridge_vertices[(bridge_i + 1) % len(bridge_vertices)]) - bridge_anchor;',
        '        bridge_twice_area += cross(bridge_a, bridge_b);',
        '    }',
        '    bridge_dual_area += 0.5 * length(bridge_twice_area) / len(bridge_vertices);',
        '}',
        'f@bridge_ocean_dual_area = bridge_dual_area;',
        'f@cusp_mask = clamp(bridge_cusp, 0.0, 1.0);',
        ('f@foam_mask = 1.0 - exp(-' + number(density)
         + ' * bridge_dual_area * max(bridge_cusp - ' + number(threshold) + ', 0.0));'
         if foam else 'f@foam_mask = 0.0;'),
    ]
    program = "\n".join(lines) + "\n"
    guards = [{"kind": "ocean_rest_geometry", "role": "source", "geometry_sha256": _hash(rest)},
              {"kind": "ocean_evaluated_surface", "role": "evaluate", "geometry_sha256": _hash(evaluated)},
              {"kind": "ocean_spectrum", "observation": spectra},
              {"kind": "native_ocean_emit", "observation": native},
              {"kind": "owned_ocean_mask_stage", "observation": stage}]
    return {"schema": SCHEMA, "generator": PROGRAM_GENERATOR, "domain_pack": pack_id,
            "native_version": version, "semantic_contract": COVERAGE_CONTRACT,
            "static_signature_sha256": STATIC_SIGNATURE_SHA256, "role": ROLE, "parm": "snippet",
            "foam": foam, "foam_amount_native_density": density, "crest_threshold_native_mincusp": threshold,
            "area_basis": "actual_source_rest_planar_convex_polygon_dual_cells",
            "sample_time_binding": "@Time", "sample_position_binding": 'point(2,"P",@ptnum)',
            "spectrum_input_binding": "@OpInput2", "observed_layers": layers,
            "rest_polygon_areas": areas, "rest_dual_cell_areas": dual,
            "frozen_readback_guards": guards, "program": program,
            "sha256": hashlib.sha256(program.encode()).hexdigest()}


def validate_mask_program(registration: Mapping, **context) -> None:
    """Reject changed supplied context or any caller-provided program content."""
    if not isinstance(registration, Mapping) or registration.get("schema") != SCHEMA:
        _fail("UNTRUSTED_OCEAN_MASK_PROGRAM", "registered fixed generator required")
    expected = mask_program(registration.get("domain_pack"), registration.get("native_version"), **context)
    guards = registration.get("frozen_readback_guards")
    if not isinstance(guards, list) or len(guards) != 5:
        _fail("UNTRUSTED_OCEAN_MASK_PROGRAM", "five typed frozen guards required")
    for old, current, label in zip(guards, expected["frozen_readback_guards"],
                                   ("REST", "SURFACE", "SPECTRUM", "EMIT", "MASK_STAGE")):
        if old != current:
            _fail("OCEAN_" + label + "_CONTEXT_CHANGED", "frozen " + label.lower() + " observation changed")
    if dict(registration) != expected:
        _fail("UNTRUSTED_OCEAN_MASK_PROGRAM", "registration must regenerate exactly")


def control_write_plan(pack_id, version, **context):
    registration = mask_program(pack_id, version, **context)
    return [{"role": ROLE, "parm": parm, "value": value, "native_type": native_type,
             "phase": "mask_program", "require_writable": True, "require_readback": True,
             "invalidates_from": "shaping_meshing", "required_gates": [],
             "frozen_readback_guards": copy.deepcopy(registration["frozen_readback_guards"]), **extra}
            for parm, value, native_type, extra in (
                ("class", "Points", "ordinal", {"value_kind": "menu_label"}),
                ("group", "", "string", {}),
                ("snippet", registration["program"], "string", {"trusted_program": registration}))]


def validate_control_write_plan(writes, observations, **context):
    if not isinstance(writes, list) or len(writes) != 3 or not isinstance(writes[2], Mapping):
        _fail("UNTRUSTED_OCEAN_MASK_PROGRAM", "complete three-field write plan required")
    registration = writes[2].get("trusted_program")
    validate_mask_program(registration, **context)
    expected = control_write_plan(registration["domain_pack"], registration["native_version"], **context)
    if writes != expected:
        _fail("UNTRUSTED_OCEAN_MASK_PROGRAM", "fixed write plan must regenerate exactly")
    if not isinstance(observations, Mapping):
        _fail("NATIVE_CONTROL_INTERFACE_REQUIRED", "actual wrangle field observations")
    for write in writes:
        fact = observations.get((ROLE, write["parm"]), {})
        if (not isinstance(fact, Mapping) or fact.get("origin") != "runtime_hom"
                or fact.get("type") != write["native_type"] or type(fact.get("size")) is not int
                or fact["size"] != 1):
            _fail("NATIVE_CONTROL_INTERFACE_REQUIRED", ROLE + "/" + write["parm"])
        if any(fact.get(flag) is not False for flag in ("locked", "disabled", "hidden", "driven")):
            _fail("NATIVE_CONTROL_GATE_BLOCKED", ROLE + "/" + write["parm"])
        if write["parm"] == "class" and "Points" not in fact.get("menu_labels", ()):
            _fail("NATIVE_CONTROL_INTERFACE_REQUIRED", "actual Points menu label required")


def _attributes(raw, count):
    if not isinstance(raw, Mapping) or set(raw) != set(_ATTRIBUTES):
        _fail("ACTUAL_OCEAN_TYPED_POINT_ATTRIBUTES_REQUIRED", "five actual typed point attributes")
    result, precisions = {}, {}
    for name, typ in _ATTRIBUTES.items():
        fact = raw[name]
        if (not isinstance(fact, Mapping) or set(fact) != {"owner", "storage", "size", "precision", "values"}
                or fact["owner"] != "point" or fact["storage"] != typ
                or type(fact["size"]) is not int or fact["size"] != 1
                or fact["precision"] not in (("int32",) if typ == "int" else ("float32", "float64"))
                or not isinstance(fact["values"], (list, tuple)) or len(fact["values"]) != count):
            _fail("ACTUAL_OCEAN_TYPED_POINT_ATTRIBUTES_REQUIRED", name + ": actual scalar point storage and all values")
        if typ == "int":
            if any(type(v) is not int or not 0 <= v < 2 ** 31 for v in fact["values"]):
                _fail("ACTUAL_OCEAN_TYPED_POINT_ATTRIBUTES_REQUIRED", name + ": int32 values")
            values = list(fact["values"])
        else:
            values = [_number(v, -1e30, 1e30, name) for v in fact["values"]]
            if fact["precision"] == "float32" and any(_float32(v) != v for v in values):
                _fail("ACTUAL_OCEAN_PRECISION_REQUIRED", name + ": retain actual stored float32 values")
        result[name] = values
        precisions[name] = fact["precision"]
    return result, precisions


def validate_geometry_readback(registration, *, masked_geometry, **context):
    """Check masks from supplied native cusp, never a CPU cusp expectation."""
    validate_mask_program(registration, **context)
    if not isinstance(masked_geometry, Mapping) or set(masked_geometry) != _GEOMETRY_FIELDS | {"point_attributes"}:
        _fail("ACTUAL_OCEAN_GEOMETRY_REQUIRED", "actual masked geometry and typed point attributes")
    actual = _geometry({k: v for k, v in masked_geometry.items() if k != "point_attributes"}, ROLE)
    surface = _geometry(context["surface"], "evaluate")
    if (actual["node_path"] != context["mask_stage"]["node_path"] or actual["frame"] != surface["frame"]
            or actual["position_precision"] != surface["position_precision"]
            or actual["point_positions"] != surface["point_positions"] or actual["polygons"] != surface["polygons"]):
        _fail("OCEAN_MASK_SURFACE_READBACK_MISMATCH", "mask output must retain every evaluated P and ordered Polygon")
    precision = "float32" if context["mask_stage"]["vex_precision"] == "32" else "float64"
    attrs, attribute_precisions = _attributes(masked_geometry["point_attributes"], len(actual["point_positions"]))
    if any(value != registration["observed_layers"] for value in attrs["bridge_ocean_layers"]):
        _fail("VALID_OCEAN_SPECTRUM_LAYERS_REQUIRED", "all supplied native layer counts must match actual nonzero spectrum layers")
    rest = _geometry(context["source"], "source")
    dual, _, spans, resolutions = _rest_areas(rest)
    epsilon = 2. ** (-23 if precision == "float32" else -52)
    area_tolerances = [0.] * len(dual)
    for face, span, resolution in zip(rest["polygons"], spans, resolutions):
        error = len(face) * (16 * resolution * span + 32 * epsilon * span * span)
        for index in face:
            area_tolerances[index] += error / len(face)
    density, threshold = (registration[name] for name in ("foam_amount_native_density", "crest_threshold_native_mincusp"))
    maximum_area_error, maximum_mask_error = 0., 0.
    for index, area in enumerate(attrs["bridge_ocean_dual_area"]):
        area_error = abs(area - dual[index])
        area_storage = attribute_precisions["bridge_ocean_dual_area"]
        if area <= 0 or area_error > max(1e-12, area_tolerances[index] + 2 * _ulp(area, area_storage)):
            _fail("OCEAN_REST_AREA_READBACK_MISMATCH", "every supplied dual-cell area must match actual rest Polygons")
        cusp = attrs["bridge_ocean_cusp"][index]
        # A 64-bit calculation may bind to an existing 32-bit attribute. The
        # observed scalar then bounds, rather than exactly reproduces, the VEX
        # register. Do not infer attribute storage from vex_precision.
        cusp_rounding = (_ulp(cusp, "float32") if precision == "float64"
                         and attribute_precisions["bridge_ocean_cusp"] == "float32" else 0.)
        area_rounding = (_ulp(area, "float32") if precision == "float64"
                         and area_storage == "float32" else 0.)
        expected_cusp = min(1., max(0., cusp))
        expected_foam = (-math.expm1(-density * area * max(cusp - threshold, 0.))
                         if registration["foam"] else 0.)
        cusp_interval = (min(1., max(0., cusp - cusp_rounding)),
                         min(1., max(0., cusp + cusp_rounding)))
        foam_interval = ((-math.expm1(-density * max(0., area - area_rounding)
                                     * max(cusp - cusp_rounding - threshold, 0.)),
                          -math.expm1(-density * (area + area_rounding)
                                      * max(cusp + cusp_rounding - threshold, 0.)))
                         if registration["foam"] else (0., 0.))
        if foam_interval[1] - foam_interval[0] > 1e-4:
            _fail("OCEAN_MASK_NUMERIC_READBACK_UNRESOLVED", "actual cusp/area storage cannot resolve coverage to 0.0001")
        for name, expected in (("cusp_mask", expected_cusp), ("foam_mask", expected_foam)):
            value = attrs[name][index]
            error = abs(value - expected)
            if not 0 <= value <= 1 or (not registration["foam"] and name == "foam_mask" and value != 0.):
                _fail("OCEAN_MASK_ATTRIBUTE_READBACK_MISMATCH", name + ": finite coverage in [0,1]; disabled foam exactly zero")
            storage = attribute_precisions[name]
            interval = cusp_interval if name == "cusp_mask" else foam_interval
            interval_error = max(interval[0] - value, value - interval[1], 0.)
            if interval_error > max(1e-12, 32 * epsilon + 2 * _ulp(value, storage)):
                _fail("OCEAN_MASK_ATTRIBUTE_READBACK_MISMATCH", name + ": supplied native cusp/rest-area formula mismatch")
            maximum_mask_error = max(maximum_mask_error, error)
        maximum_area_error = max(maximum_area_error, area_error)
    return {"schema": "bridge.ocean-mask-observation-comparison/1",
            "scope": "supplied_runtime_hom_geometry_and_native_cusp_observations",
            "semantic_contract": COVERAGE_CONTRACT, "area_basis": registration["area_basis"],
            "sample_time": context["spectrum"]["sample_time"], "frame": actual["frame"],
            "program_sha256": registration["sha256"], "observed_layers": registration["observed_layers"],
            "attribute_precisions": attribute_precisions,
            "pointwise_mask_formula_matches": True, "evaluated_positions_and_topology_unchanged": True,
            "maximum_rest_area_error": maximum_area_error, "maximum_mask_error": maximum_mask_error}


def validate_applied_readback(writes, observations, *, masked_geometry, **context):
    validate_control_write_plan(writes, observations, **context)
    for write in writes:
        actual = observations[(ROLE, write["parm"])]
        matched = (_gate_matches(actual, write["value"]) if write["parm"] == "class"
                   else actual.get("value") == write["value"])
        if not matched:
            _fail("NATIVE_CONTROL_READBACK_MISMATCH", ROLE + "/" + write["parm"])
    return validate_geometry_readback(writes[2]["trusted_program"], masked_geometry=masked_geometry, **context)
