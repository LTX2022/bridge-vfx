"""Trusted synthetic agent construction and read-only native snapshots.

No hou import, node creation, scene save/load, cook, license or render operation.
The integrating addon supplies its already-authorized HOM module.  All builder
mutations occur on a new detached hou.Geometry; readback never calls the builder.
Supported field/method contracts are bound to the versioned native basis.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import base64
import hashlib
import json
import math

SUPPORTED_VERSIONS = ("21.0.631", "22.0.429")
SNAPSHOT_SCHEMA = "bridge.w5.synthetic_agent_snapshot/1.0"
FIXTURE_CLIP = "w5_loop"
FIXTURE_LAYER = "w5_visible"
FIXTURE_SHAPE = "w5_body"


class CrowdDataError(ValueError):
    """Missing, unsupported or changed actual agent data; never a fake success."""


def _version(hou):
    version = hou.applicationVersionString()
    if version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        raise CrowdDataError("no native HOM evidence for version " + version)
    return version


def _json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CrowdDataError("non-finite native readback")
        return value
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CrowdDataError("native dictionary keys are not strings")
        return {key: _json_value(item) for key, item in value.items()}
    raise CrowdDataError("unsupported native readback value: " + type(value).__name__)


def _matrix(value):
    result = _json_value(value.asTuple())
    if len(result) != 16:
        raise CrowdDataError("native Matrix4 readback is not 16 components")
    return result


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _payload(data):
    if not isinstance(data, bytes) or not data:
        raise CrowdDataError("native serialized data is not nonempty bytes")
    return {"encoding": "base64", "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "data": base64.b64encode(data).decode("ascii")}


def _attributes_readback(geometry):
    """Public attributes as actually stored; native bgeo also retains private data."""
    points, prims = geometry.points(), geometry.prims()
    return {
        "detail": {attrib.name(): _json_value(geometry.attribValue(attrib))
                   for attrib in geometry.globalAttribs()},
        "point": {attrib.name(): [_json_value(point.attribValue(attrib)) for point in points]
                  for attrib in geometry.pointAttribs()},
        "primitive": {attrib.name(): [_json_value(prim.attribValue(attrib)) for prim in prims]
                      for attrib in geometry.primAttribs()},
        "vertex": {attrib.name(): [[_json_value(vertex.attribValue(attrib))
                                    for vertex in prim.vertices()] for prim in prims]
                   for attrib in geometry.vertexAttribs()},
    }


def _shape_readback(hou, geometry):
    """Actual shape topology; full native bgeo is captured separately."""
    points = geometry.points()
    prims = geometry.prims()
    if any(not isinstance(prim, hou.Polygon) for prim in prims):
        raise CrowdDataError("synthetic shape contains a non-polygon primitive")
    return {
        "attributes": _attributes_readback(geometry),
        "points": [{"number": point.number(), "position": _json_value(tuple(point.position()))}
                   for point in points],
        "polygons": [{"closed": prim.isClosed(),
                      "point_indices": [vertex.point().number() for vertex in prim.vertices()]}
                     for prim in prims],
    }


def snapshot_agent_geometry(hou, geometry):
    """Snapshot the supplied actual geometry, including all definition content.

    Does not cook a node, alter geometry, synthesize expected data, or restore
    anything. Supply the reopened geometry from the runtime owner's save path.
    Native payloads retain complete bgeo/clip bytes; content provides readable,
    stable comparison data without process-local shape ids or binary checksums.
    Intended for the small synthetic fixture, not arbitrary production crowds.
    """
    version = _version(hou)
    prims = geometry.prims()
    if not prims or any(not isinstance(prim, hou.Agent) for prim in prims):
        raise CrowdDataError("actual geometry does not contain only hou.Agent primitives")
    if geometry.countPrimType("PackedAgent") != len(prims):
        raise CrowdDataError("PackedAgent type count differs from actual agent count")
    agents, payloads = [], {"geometry_bgeo": _payload(geometry.data()), "agents": []}
    for agent in prims:
        definition = agent.definition()
        if definition is None:
            raise CrowdDataError("PackedAgent has no actual definition")
        rig, library = definition.rig(), definition.shapeLibrary()
        count = rig.transformCount()
        if count <= 0:
            raise CrowdDataError("agent definition has an empty rig")
        rig_data = {
            "name": rig.name(), "external_reference": rig.isExternalReference(),
            "transform_names": list(rig.transformNames()),
            "hierarchy": _json_value(rig.transformHierarchy()),
            "parents": [rig.parentIndex(index) for index in range(count)],
            "rest_local": [_matrix(rig.restLocalTransform(index)) for index in range(count)],
            "rest_world": [_matrix(rig.restWorldTransform(index)) for index in range(count)],
            "channels": [{"name": rig.channelName(index),
                          "default": _json_value(rig.channelDefaultValue(index)),
                          "transform": rig.channelTransform(index)}
                         for index in range(rig.channelCount())],
        }
        shapes = [{"name": shape.name(), "geometry": _shape_readback(hou, shape.geometry())}
                  for shape in library.shapes()]
        layers = [{"name": layer.name(), "external_reference": layer.isExternalReference(),
                   "bindings": [{"transform": binding.transformId(),
                                 "attached": binding.isAttachedToTransform(),
                                 "shape": binding.shapeName(),
                                 "deforming": binding.isDeforming(),
                                 "bounds_scale": _json_value(tuple(binding.boundsScale()))}
                                for binding in layer.bindings()]}
                  for layer in definition.layers()]
        clips = []
        clip_payloads = []
        for clip in definition.clips():
            sample_count = clip.sampleCount()
            sample_rate = _json_value(float(clip.sampleRate()))
            start_time = _json_value(float(clip.startTime()))
            length = _json_value(float(clip.length()))
            if sample_count <= 0 or sample_rate <= 0 or length < 0:
                raise CrowdDataError("invalid actual clip sample/time contract")
            sample_times = [start_time + index / sample_rate for index in range(sample_count)]
            clips.append({
                "name": clip.name(), "external_reference": clip.isExternalReference(),
                "sample_count": sample_count, "sample_rate": sample_rate,
                "start_time": start_time, "length_seconds": length,
                "local_samples": [[_matrix(xform) for xform in clip.localTransforms(index)]
                                  for index in range(sample_count)],
                "world_samples": [[_matrix(xform) for xform in clip.worldTransforms(index)]
                                  for index in range(sample_count)],
                "channels": [{"name": name,
                              "sample_times_seconds": sample_times,
                              "values": [_json_value(clip.sample(time, name)) for time in sample_times]}
                             for name in clip.channelNames()],
            })
            clip_payloads.append({"name": clip.name(), "local_clip_binary": _payload(clip.data(True))})
        metadata = definition.metadata()
        agents.append({
            "primitive_number": agent.number(), "native_type": "PackedAgent",
            "points": [_json_value(tuple(vertex.point().position())) for vertex in agent.vertices()],
            "full_transform": _matrix(agent.fullTransform()),
            "rig": rig_data,
            "shape_library": {"name": library.name(), "external_reference": library.isExternalReference(),
                              "shapes": shapes},
            "layers": layers, "clips": clips,
            "transform_groups": [{"name": group.name(), "indices": list(group.transformIndices())}
                                 for group in definition.transformGroups()],
            "metadata": _json_value(metadata.data()) if metadata is not None else None,
            "current_layers": [layer.name() for layer in agent.currentLayers()],
            "collision_layers": [layer.name() for layer in agent.collisionLayers()],
            "current_clips": [clip.name() for clip in agent.clips()],
            "clip_times": _json_value(agent.clipTimes()),
            "clip_weights": _json_value(agent.clipWeights()),
            "pose_local": [_matrix(agent.localTransform(index)) for index in range(count)],
            "pose_world": [_matrix(agent.worldTransform(index)) for index in range(count)],
            "channel_values": [_json_value(agent.channelValue(index)) for index in range(rig.channelCount())],
        })
        payloads["agents"].append({
            "rig_json": rig.asJSON(), "shape_library_bgeo": _payload(library.data().data()),
            "shapes": [{"name": shape.name(), "bgeo": _payload(shape.geometry().data())}
                       for shape in library.shapes()],
            "layers": [{"name": layer.name(), "json": layer.asJSON()} for layer in definition.layers()],
            "clips": clip_payloads,
        })
    content = _json_value({"point_count": len(geometry.points()),
                           "attributes": _attributes_readback(geometry), "agents": agents})
    return {"schema": SNAPSHOT_SCHEMA, "houdini_version": version,
            "content": content, "content_sha256": hashlib.sha256(_canonical(content)).hexdigest(),
            "native_payloads": payloads}


def validate_synthetic_snapshot(snapshot):
    """Verify invariants in actual readback. Does not replace any readback value."""
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise CrowdDataError("unknown snapshot schema")
    if snapshot.get("houdini_version") not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        raise CrowdDataError("unsupported snapshot version")
    content = snapshot["content"]
    if hashlib.sha256(_canonical(content)).hexdigest() != snapshot["content_sha256"]:
        raise CrowdDataError("snapshot content digest mismatch")
    if len(content["agents"]) != 1 or content["point_count"] != 1:
        raise CrowdDataError("synthetic fixture requires exactly one agent and one point")
    agent = content["agents"][0]
    rig = agent["rig"]
    if rig["transform_names"] != ["root", "body"] or rig["hierarchy"] != [[1], []] or rig["parents"] != [-1, 0]:
        raise CrowdDataError("actual root/body rig hierarchy differs")
    if rig["external_reference"] or agent["shape_library"]["external_reference"]:
        raise CrowdDataError("synthetic definition unexpectedly references external files")
    shapes = agent["shape_library"]["shapes"]
    if len(shapes) != 1 or shapes[0]["name"] != FIXTURE_SHAPE:
        raise CrowdDataError("actual visible body shape missing")
    shape = shapes[0]["geometry"]
    if len(shape["points"]) != 8 or len(shape["polygons"]) != 6:
        raise CrowdDataError("actual body is not the six-face closed box")
    positions = [point["position"] for point in shape["points"]]
    if any(max(p[axis] for p in positions) <= min(p[axis] for p in positions) for axis in range(3)):
        raise CrowdDataError("actual body has zero extent")
    edges = {}
    numbers = {point["number"] for point in shape["points"]}
    for polygon in shape["polygons"]:
        indices = polygon["point_indices"]
        if not polygon["closed"] or len(indices) != 4 or len(set(indices)) != 4 or not set(indices) <= numbers:
            raise CrowdDataError("actual body face is open or degenerate")
        for a, b in zip(indices, indices[1:] + indices[:1]):
            edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
    if len(edges) != 12 or any(len(uses) != 2 or uses[0] != uses[1][::-1] for uses in edges.values()):
        raise CrowdDataError("actual body is not a consistently wound closed shell")
    layers, clips = agent["layers"], agent["clips"]
    if len(layers) != 1 or layers[0]["name"] != FIXTURE_LAYER or layers[0]["external_reference"]:
        raise CrowdDataError("actual synthetic display layer differs")
    bindings = layers[0]["bindings"]
    if len(bindings) != 1 or bindings[0]["shape"] != FIXTURE_SHAPE or bindings[0]["transform"] != 1 or not bindings[0]["attached"] or bindings[0]["deforming"]:
        raise CrowdDataError("actual body shape binding differs")
    if len(clips) != 1 or clips[0]["name"] != FIXTURE_CLIP or clips[0]["external_reference"]:
        raise CrowdDataError("actual unique embedded clip differs")
    clip = clips[0]
    samples = clip["local_samples"]
    if clip["sample_count"] != 3 or len(samples) != 3 or any(len(sample) != 2 for sample in samples):
        raise CrowdDataError("actual clip does not have three two-transform samples")
    if samples[0] != samples[2] or samples[0] == samples[1] or samples[0][1] == samples[1][1]:
        raise CrowdDataError("actual clip is not nonconstant body A-B-A")
    if samples[0] != rig["rest_local"] or agent["pose_local"] != samples[0]:
        raise CrowdDataError("actual initial pose differs from clip A/rest pose")
    if not all(math.isfinite(clip[key]) for key in ("sample_rate", "start_time", "length_seconds")) or clip["sample_rate"] <= 0 or clip["length_seconds"] <= 0:
        raise CrowdDataError("invalid actual clip timing")
    if agent["current_layers"] != [FIXTURE_LAYER] or agent["current_clips"] != [FIXTURE_CLIP] or agent["clip_times"] != [clip["start_time"]] or agent["clip_weights"] != [1.0]:
        raise CrowdDataError("actual current layer/clip/time/weight differs")
    return {"clip_name": clip["name"], "state_name": clip["name"],
            "layer_name": layers[0]["name"], "sample_count": clip["sample_count"],
            "sample_rate": clip["sample_rate"], "start_time": clip["start_time"],
            "length_seconds": clip["length_seconds"], "content_sha256": snapshot["content_sha256"]}


def build_synthetic_agent_geometry(hou):
    """Return (detached geometry, actual snapshot, actual source/state handoff).

    No source/state node or persistent scene is created by this helper. Parent
    integrates the resulting data with its trusted asset materialization path.
    """
    _version(hou)
    rig = hou.AgentRig("w5_root_body", ["root", "body"], [[1], []])
    rest = [hou.Matrix4(1), hou.hmath.buildTranslate(0.0, 0.75, 0.0)]
    rig.setRestLocalTransforms(rest)
    shape_geo = hou.Geometry()
    positions = ((-0.25, -0.5, -0.2), (0.25, -0.5, -0.2),
                 (0.25, 0.5, -0.2), (-0.25, 0.5, -0.2),
                 (-0.25, -0.5, 0.2), (0.25, -0.5, 0.2),
                 (0.25, 0.5, 0.2), (-0.25, 0.5, 0.2))
    points = []
    for position in positions:
        point = shape_geo.createPoint()
        point.setPosition(position)
        points.append(point)
    for indices in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                    (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)):
        polygon = shape_geo.createPolygon(is_closed=True)
        for index in indices:
            polygon.addVertex(points[index])
    library = hou.AgentShapeLibrary()
    shape = library.addShape(FIXTURE_SHAPE, shape_geo)
    binding = hou.AgentShapeBinding(1, shape, False, bounds_scale=1.0)
    layer = hou.AgentLayer(FIXTURE_LAYER, rig, library, [binding])
    clip = hou.AgentClip(FIXTURE_CLIP, rig, 3)
    middle = [hou.Matrix4(1), hou.hmath.buildTranslate(0.15, 0.85, 0.0)]
    for sample_index, transforms in enumerate((rest, middle, rest)):
        clip.setLocalTransforms(sample_index, transforms)
    definition = hou.AgentDefinition(rig, library)
    definition.addLayer(layer)
    definition.addClip(clip)
    geometry = hou.Geometry()
    agent = geometry.createPacked("PackedAgent")
    if not isinstance(agent, hou.Agent):
        raise CrowdDataError("createPacked('PackedAgent') did not return hou.Agent")
    agent.setDefinition(definition)
    agent.setCurrentLayers([layer])
    agent.setClips([clip])
    agent.setClipTimes([clip.startTime()])
    agent.setClipWeights([1.0])
    for index, transform in enumerate(rest):
        agent.setLocalTransform(transform, index)
    snapshot = snapshot_agent_geometry(hou, geometry)
    handoff = validate_synthetic_snapshot(snapshot)
    return geometry, snapshot, handoff


def compare_agent_snapshots(before, after, tolerance=1.0e-8):
    """Compare actual readable content; binary bgeo ids may change on reopening.

    Native blobs are retained as evidence, not used as an assumed portable hash.
    Missing/changed rig, shapes, samples, pose, timings or layers are rejected.
    Does not require initial pose invariants on downstream simulated agents.
    """
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise CrowdDataError("invalid comparison tolerance")
    for snapshot in (before, after):
        if snapshot.get("schema") != SNAPSHOT_SCHEMA or snapshot.get("houdini_version") not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
            raise CrowdDataError("unsupported actual snapshot schema/version")
        if hashlib.sha256(_canonical(snapshot["content"])).hexdigest() != snapshot["content_sha256"]:
            raise CrowdDataError("actual snapshot content digest mismatch")
    if before["houdini_version"] != after["houdini_version"]:
        raise CrowdDataError("cross-version scene acceptance requires a separate migration contract")
    differences = []

    def compare(a, b, path):
        if type(a) is not type(b):
            differences.append(path + ": type changed")
        elif isinstance(a, float):
            if not math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance):
                differences.append(path + ": numeric value changed")
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                differences.append(path + ": fields changed")
            for key in a.keys() & b.keys():
                compare(a[key], b[key], path + "." + key)
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append(path + ": count changed")
            for index, (left, right) in enumerate(zip(a, b)):
                compare(left, right, path + "[" + str(index) + "]")
        elif a != b:
            differences.append(path + ": value changed")

    compare(before["content"], after["content"], "content")
    if differences:
        raise CrowdDataError("actual agent data changed: " + "; ".join(sorted(differences)))
    return {"schema": SNAPSHOT_SCHEMA, "content_equivalent": True,
            "before_sha256": before["content_sha256"], "after_sha256": after["content_sha256"],
            "absolute_float_tolerance": tolerance}
