"""Finite, detached HOM API replacement for software checks of crowd_helpers.

All objects contain test_injected_native_api state. JSON bytes are this API's
state representation, not native bgeo, clip, HIP, or Graph data. The caller must
provide clip timing explicitly because the captured constructor docs omit it.
No hou import, node API, scene operation, business snapshot, or receipt is here.
"""
from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

ORIGIN = "test_injected_native_api"
FORMAT = "bridge.software_agent_api_geometry/1.0"


class AgentAPIError(ValueError):
    """Unsupported API contract or incomplete/malformed injected state."""


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise AgentAPIError("expected a finite number")
    return float(value)


def _sequence(value):
    if not isinstance(value, (list, tuple)):
        raise AgentAPIError("expected a sequence")
    return value


def _name(value):
    if not isinstance(value, str):
        raise AgentAPIError("expected a string name")
    return value


def _index(value, count):
    if type(value) is not int or not 0 <= value < count:
        raise AgentAPIError("index outside stored state")
    return value


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AgentAPIError("missing or unknown serialized state fields")
    return value


def _bool(value):
    if type(value) is not bool:
        raise AgentAPIError("expected bool")
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _attribute(value, default=None):
    if type(value) not in (str, int, float, list, tuple):
        raise AgentAPIError("unsupported attribute value")
    if isinstance(value, (list, tuple)):
        value = tuple(value)
        if not value or any(type(v) not in (int, float) for v in value):
            raise AgentAPIError("only nonempty numeric attribute tuples are supported")
        if len({type(v) for v in value}) != 1:
            raise AgentAPIError("attribute tuple components must share a type")
        for v in value:
            _number(v)
    elif type(value) in (int, float):
        _number(value)
    if default is not None:
        if type(value) is not type(default):
            raise AgentAPIError("attribute type differs from its declaration")
        if isinstance(default, tuple) and (len(value) != len(default) or
                any(type(a) is not type(b) for a, b in zip(value, default))):
            raise AgentAPIError("attribute tuple differs from its declaration")
    return value


def install_agent_api(hou):
    """Install only the finite detached API on an explicitly configured fixture.

    Required hou._software_agent_api_state keys are origin, clip_sample_rate,
    and clip_start_time. Existing version and scene APIs are never overwritten.
    Each installation has independent classes and timing state.
    """
    state = _keys(getattr(hou, "_software_agent_api_state", None),
                  ("origin", "clip_sample_rate", "clip_start_time"))
    if state["origin"] != ORIGIN:
        raise AgentAPIError("API installation requires explicit test injection")
    rate, start = _number(state["clip_sample_rate"]), _number(state["clip_start_time"])
    if rate <= 0:
        raise AgentAPIError("injected clip sample rate must be positive")
    if hou.applicationVersionString() not in ("21.0.631", "22.0.429", "22.0.459"):
        raise AgentAPIError("no captured API contract for this version")

    class Matrix4:
        __slots__ = ("_values",)

        def __init__(self, values=0.0):
            if isinstance(values, Matrix4):
                values = values.asTuple()
            if type(values) in (int, float):
                scalar = _number(values)
                values = [scalar if row == col else 0.0
                          for row in range(4) for col in range(4)]
            else:
                values = _sequence(values)
                if len(values) == 4 and all(isinstance(v, (list, tuple)) for v in values):
                    if any(len(row) != 4 for row in values):
                        raise AgentAPIError("Matrix4 rows require four components")
                    values = [v for row in values for v in row]
                if len(values) != 16:
                    raise AgentAPIError("Matrix4 requires sixteen components")
            self._values = tuple(_number(v) for v in values)

        def asTuple(self):
            return self._values

        def __mul__(self, matrix4_or_scalar):
            if isinstance(matrix4_or_scalar, Matrix4):
                a, b = self._values, matrix4_or_scalar._values
                return Matrix4([sum(a[r*4+k]*b[k*4+c] for k in range(4))
                                for r in range(4) for c in range(4)])
            scalar = _number(matrix4_or_scalar)
            return Matrix4([v * scalar for v in self._values])

    def translate(tx, ty=None, tz=None):
        if ty is None and tz is None:
            values = _sequence(tx)
            if len(values) != 3:
                raise AgentAPIError("translation requires three components")
            tx, ty, tz = values
        values = list(Matrix4(1).asTuple())
        values[12:15] = [_number(tx), _number(ty), _number(tz)]
        return Matrix4(values)

    def matrices(values, count):
        values = _sequence(values)
        if len(values) != count or any(not isinstance(v, Matrix4) for v in values):
            raise AgentAPIError("transform count/type differs from rig")
        return [Matrix4(v) for v in values]

    def stored_matrix(value):
        if len(_sequence(value)) != 16:
            raise AgentAPIError("serialized matrix requires sixteen stored components")
        return Matrix4(value)

    def worlds(rig, locals_):
        locals_ = matrices(locals_, rig.transformCount())
        result = [None] * len(locals_)

        def visit(index):
            if result[index] is None:
                parent = rig.parentIndex(index)
                result[index] = locals_[index] if parent == -1 else locals_[index] * visit(parent)
            return result[index]

        return tuple(visit(i) for i in range(len(locals_)))

    class Attrib:
        __slots__ = ("_geo", "_scope", "_name", "_default", "_normal", "_variable")

        def __init__(self, geo, scope, name, default, normal=False, variable=False):
            self._geo, self._scope, self._name = geo, scope, _name(name)
            self._default = _attribute(default)
            self._normal, self._variable = _bool(normal), _bool(variable)

        def name(self):
            return self._name

    class Element:
        __slots__ = ("_geo", "_number", "_attrs")
        _scope = None

        def __init__(self, geometry, number):
            if not isinstance(geometry, Geometry) or type(number) is not int or number < 0:
                raise AgentAPIError("element requires its owning Geometry and index")
            self._geo, self._number = geometry, number
            self._attrs = geometry._defaults(self._scope)

        def number(self):
            return self._number

        def attribValue(self, name_or_attrib):
            name = self._geo._resolve(self._scope, name_or_attrib)
            return self._attrs[name]

        def setAttribValue(self, name_or_attrib, attrib_value):
            name = self._geo._resolve(self._scope, name_or_attrib)
            self._attrs[name] = _attribute(attrib_value, self._geo._attrs[self._scope][name]._default)

    class Point(Element):
        __slots__ = ("_weight",)
        _scope = "point"

        def __init__(self, geometry, number):
            super().__init__(geometry, number)
            self._weight = 1.0

        def setPosition(self, position):
            position = _sequence(position)
            if len(position) not in (3, 4):
                raise AgentAPIError("point position requires three or four components")
            self._attrs["P"] = tuple(_number(v) for v in position[:3])
            if len(position) == 4:
                self._weight = _number(position[3])

        def position(self):
            return self._attrs["P"]

    class Vertex(Element):
        __slots__ = ("_point",)
        _scope = "vertex"

        def __init__(self, geometry, number, point):
            super().__init__(geometry, number)
            self._point = point

        def point(self):
            return self._point

    class Primitive(Element):
        __slots__ = ("_vertices",)
        _scope = "primitive"
        _kind = None

        def __init__(self, geometry, number):
            super().__init__(geometry, number)
            self._vertices = []

        def vertices(self):
            return tuple(self._vertices)

        def type(self):
            return SimpleNamespace(name=lambda: self._kind)

        def _vertex(self, point):
            if not isinstance(point, Point) or point._geo is not self._geo or point not in self._geo._points:
                raise AgentAPIError("vertex point must belong to this Geometry")
            vertex = Vertex(self._geo, len(self._vertices), point)
            self._vertices.append(vertex)
            return vertex

    class Polygon(Primitive):
        __slots__ = ("_closed",)
        _kind = "Polygon"

        def __init__(self, geometry, number, is_closed=True):
            super().__init__(geometry, number)
            self._closed = _bool(is_closed)

        def addVertex(self, point):
            return self._vertex(point)

        def isClosed(self):
            return self._closed

        def setIsClosed(self, on):
            self._closed = _bool(on)

    class AgentRig:
        __slots__ = ("_name", "_names", "_hierarchy", "_parents", "_rest", "_origin")

        def __init__(self, name, transform_names, hierarchy):
            self._name, self._origin = _name(name), ORIGIN
            self._names = tuple(_name(n) for n in _sequence(transform_names))
            if len(set(self._names)) != len(self._names):
                raise AgentAPIError("rig transform names must be unique")
            rows = _sequence(hierarchy)
            if len(rows) != len(self._names):
                raise AgentAPIError("rig hierarchy count differs from transform count")
            self._hierarchy = tuple(tuple(_index(i, len(rows)) for i in _sequence(row)) for row in rows)
            self._parents = [-1] * len(rows)
            for parent, children in enumerate(self._hierarchy):
                for child in children:
                    if self._parents[child] != -1 or child == parent:
                        raise AgentAPIError("rig hierarchy has duplicate parents or self-edge")
                    self._parents[child] = parent
            for i in range(len(rows)):
                seen = set()
                while i != -1:
                    if i in seen:
                        raise AgentAPIError("rig hierarchy has a cycle")
                    seen.add(i)
                    i = self._parents[i]
            self._rest = [Matrix4(1) for _ in rows]

        def name(self): return self._name
        def isExternalReference(self): return False
        def transformCount(self): return len(self._names)
        def transformNames(self): return self._names
        def transformHierarchy(self): return self._hierarchy
        def parentIndex(self, transform): return self._parents[_index(transform, self.transformCount())]
        def setRestLocalTransforms(self, xforms): self._rest = matrices(xforms, self.transformCount())
        def restLocalTransform(self, transform): return Matrix4(self._rest[_index(transform, self.transformCount())])
        def restWorldTransform(self, transform): return worlds(self, self._rest)[_index(transform, self.transformCount())]
        def channelCount(self): return 0
        def channelName(self, channel_index): raise AgentAPIError("rig has no additional channels")
        def channelDefaultValue(self, channel_index): raise AgentAPIError("rig has no additional channels")
        def channelTransform(self, channel_index): raise AgentAPIError("rig has no additional channels")
        def asJSON(self): return _json(self._state())

        def _state(self):
            return {"origin": self._origin, "name": self._name, "transform_names": self._names,
                    "hierarchy": self._hierarchy, "rest_local": [m.asTuple() for m in self._rest], "channels": []}

    class Shape:
        __slots__ = ("_name", "_geometry", "_library")

        def __init__(self, name, geometry, library):
            self._name, self._geometry, self._library = _name(name), geometry, library

        def name(self): return self._name
        def geometry(self): return self._geometry

    class AgentShapeLibrary:
        __slots__ = ("_name", "_shapes", "_origin")

        def __init__(self, geometry=None, name=""):
            self._name, self._shapes, self._origin = _name(name), [], ORIGIN
            if geometry is None:
                if name:
                    raise AgentAPIError("empty shape library constructor takes no name")
            elif isinstance(geometry, Geometry) and geometry._library_state is not None:
                restored = load_library(geometry._library_state)
                self._name = name or restored._name
                for shape in restored.shapes():
                    self.addShape(shape.name(), shape.geometry())
            else:
                raise AgentAPIError("only detached shape-library geometry representation is supported")

        def addShape(self, name, geometry):
            name = _name(name)
            if not isinstance(geometry, Geometry) or any(s.name() == name for s in self._shapes):
                raise AgentAPIError("shape geometry type or unique name contract violated")
            shape = Shape(name, Geometry(geometry), self)
            self._shapes.append(shape)
            return shape

        def name(self): return self._name
        def isExternalReference(self): return False
        def shapes(self): return tuple(self._shapes)

        def data(self):
            geometry = Geometry()
            geometry._library_state = self._state()
            return geometry

        def _state(self):
            return {"origin": self._origin, "name": self._name,
                    "shapes": [{"name": s.name(), "geometry": s.geometry()._state()} for s in self._shapes]}

    class AgentShapeBinding:
        __slots__ = ("_transform", "_shape", "_deforming", "_scale")

        def __init__(self, transform, shape, deforming, bounds_scale=1.0):
            if type(transform) is not int or transform < 0 or not isinstance(shape, Shape):
                raise AgentAPIError("binding requires a transform index and stored shape")
            self._transform, self._shape, self._deforming = transform, shape, _bool(deforming)
            if type(bounds_scale) in (int, float):
                self._scale = (_number(bounds_scale),) * 3
            else:
                values = _sequence(bounds_scale)
                if len(values) != 3:
                    raise AgentAPIError("bounds_scale requires one or three components")
                self._scale = tuple(_number(v) for v in values)

        def transformId(self): return self._transform
        def isAttachedToTransform(self): return True
        def shapeName(self): return self._shape.name()
        def isDeforming(self): return self._deforming
        def boundsScale(self): return self._scale

        def _state(self):
            return {"transform": self._transform, "shape": self.shapeName(),
                    "deforming": self._deforming, "bounds_scale": self._scale}

    class AgentLayer:
        __slots__ = ("_name", "_rig", "_library", "_bindings", "_origin")

        def __init__(self, name, rig, shapelib, shape_bindings, source_layer=None):
            if not isinstance(rig, AgentRig) or not isinstance(shapelib, AgentShapeLibrary):
                raise AgentAPIError("layer requires its rig and shape library")
            self._name, self._rig, self._library, self._origin = _name(name), rig, shapelib, ORIGIN
            bindings = list(_sequence(shape_bindings))
            if source_layer is not None:
                if not isinstance(source_layer, AgentLayer) or source_layer._rig is not rig or source_layer._library is not shapelib:
                    raise AgentAPIError("source layer must share rig and shape library")
                bindings = list(source_layer.bindings()) + bindings
            if any(not isinstance(b, AgentShapeBinding) or b._shape._library is not shapelib
                   or b.transformId() >= rig.transformCount() for b in bindings):
                raise AgentAPIError("layer binding refers to another library or invalid transform")
            self._bindings = tuple(bindings)

        def name(self): return self._name
        def isExternalReference(self): return False
        def bindings(self): return self._bindings
        def asJSON(self): return _json(self._state())
        def _state(self): return {"origin": self._origin, "name": self._name, "bindings": [b._state() for b in self._bindings]}

    class AgentClip:
        __slots__ = ("_name", "_rig", "_samples", "_rate", "_start", "_origin")

        def __init__(self, name, rig, sample_count):
            if not isinstance(rig, AgentRig) or type(sample_count) is not int or sample_count <= 0:
                raise AgentAPIError("clip requires an AgentRig and positive integer sample_count")
            self._name, self._rig, self._origin = _name(name), rig, ORIGIN
            self._rate, self._start = rate, start
            self._samples = [[Matrix4(1) for _ in range(rig.transformCount())] for _ in range(sample_count)]

        def setLocalTransforms(self, sample, xforms): self._samples[_index(sample, self.sampleCount())] = matrices(xforms, self._rig.transformCount())
        def sampleCount(self): return len(self._samples)
        def sampleRate(self): return self._rate
        def startTime(self): return self._start
        def length(self): return (self.sampleCount() - 1) / self._rate
        def localTransforms(self, sample): return tuple(Matrix4(m) for m in self._samples[_index(sample, self.sampleCount())])
        def worldTransforms(self, sample): return worlds(self._rig, self.localTransforms(sample))
        def channelNames(self): return ()
        def sample(self, time, channel_name): raise AgentAPIError("clip has no additional channels")
        def name(self): return self._name
        def isExternalReference(self): return False

        def data(self, binary, worldspace=False):
            _bool(binary); _bool(worldspace)
            state = self._state()
            if worldspace:
                state["samples"] = [[m.asTuple() for m in self.worldTransforms(i)] for i in range(self.sampleCount())]
            return _json({"format": "bridge.software_agent_api_clip/1.0", "worldspace": worldspace,
                          "binary_requested": binary, "clip": state}).encode("utf-8")

        def _state(self):
            return {"origin": self._origin, "name": self._name, "sample_rate": self._rate,
                    "start_time": self._start, "samples": [[m.asTuple() for m in row] for row in self._samples], "channels": []}

    class AgentDefinition:
        __slots__ = ("_rig", "_library", "_layers", "_clips")

        def __init__(self, rig, shapelib):
            if not isinstance(rig, AgentRig) or not isinstance(shapelib, AgentShapeLibrary):
                raise AgentAPIError("definition requires its rig and shape library")
            self._rig, self._library, self._layers, self._clips = rig, shapelib, [], []

        def addLayer(self, layer):
            if not isinstance(layer, AgentLayer) or layer._rig is not self._rig or layer._library is not self._library or any(l.name() == layer.name() for l in self._layers):
                raise AgentAPIError("definition layer association or unique name contract violated")
            self._layers.append(layer)

        def addClip(self, clip):
            if not isinstance(clip, AgentClip) or clip._rig is not self._rig or any(c.name() == clip.name() for c in self._clips):
                raise AgentAPIError("definition clip association or unique name contract violated")
            self._clips.append(clip)

        def rig(self): return self._rig
        def shapeLibrary(self): return self._library
        def layers(self): return tuple(self._layers)
        def clips(self): return tuple(self._clips)
        def transformGroups(self): return ()
        def metadata(self): return None

        def _state(self):
            return {"rig": self._rig._state(), "library": self._library._state(),
                    "layers": [l._state() for l in self._layers], "clips": [c._state() for c in self._clips],
                    "transform_groups": [], "metadata": None}

    class Agent(Primitive):
        __slots__ = ("_definition", "_layers", "_collision", "_clips", "_times", "_weights", "_pose", "_packed")
        _kind = "PackedAgent"

        def __init__(self, geometry, number):
            super().__init__(geometry, number)
            self._definition = None
            self._layers, self._collision, self._clips, self._times, self._weights, self._pose = [], [], [], [], [], []
            self._packed = Matrix4(1)

        def definition(self): return self._definition

        def setDefinition(self, definition):
            if not isinstance(definition, AgentDefinition):
                raise AgentAPIError("agent requires a stored AgentDefinition")
            if len(self._pose) != definition.rig().transformCount():
                self._pose = [Matrix4(1) for _ in range(definition.rig().transformCount())]
            self._definition = definition
            self._layers = [l for l in definition.layers() if l.name() in {v.name() for v in self._layers}]
            self._collision = [l for l in definition.layers() if l.name() in {v.name() for v in self._collision}]
            old_names = [c.name() for c in self._clips]
            new_by_name = {c.name(): c for c in definition.clips()}
            if all(n in new_by_name for n in old_names):
                self._clips = [new_by_name[n] for n in old_names]
            else:
                self._clips, self._times, self._weights = [], [], []

        def _require(self):
            if self._definition is None:
                raise AgentAPIError("PackedAgent has no stored definition")
            return self._definition

        def setCurrentLayers(self, layers):
            layers = list(_sequence(layers))
            if any(l not in self._require().layers() for l in layers):
                raise AgentAPIError("current layers must belong to agent definition")
            self._layers = layers

        def setClips(self, clips):
            clips = list(_sequence(clips))
            if any(c not in self._require().clips() for c in clips):
                raise AgentAPIError("current clips must belong to agent definition")
            self._clips, self._times, self._weights = clips, [0.0]*len(clips), [1.0]*len(clips)

        def _clip_values(self, values):
            values = _sequence(values)
            if len(values) != len(self._clips):
                raise AgentAPIError("clip value count differs from bound clips")
            return [_number(v) for v in values]

        def setClipTimes(self, times): self._times = self._clip_values(times)
        def setClipWeights(self, weights): self._weights = self._clip_values(weights)
        def setLocalTransform(self, xform, index): self._pose[_index(index, self._require().rig().transformCount())] = matrices([xform], 1)[0]
        def currentLayers(self): return tuple(self._layers)
        def collisionLayers(self): return tuple(self._collision)
        def clips(self): return tuple(self._clips)
        def clipTimes(self): return tuple(self._times)
        def clipWeights(self): return tuple(self._weights)
        def localTransform(self, transform): return Matrix4(self._pose[_index(transform, self._require().rig().transformCount())])
        def worldTransform(self, transform): return worlds(self._require().rig(), self._pose)[_index(transform, len(self._pose))]
        def channelValue(self, channel_index): raise AgentAPIError("rig has no additional channels")
        def fullTransform(self): return self._packed * translate(self._vertices[0].point().position())

        def _state(self):
            return {"definition": self._require()._state(), "current_layers": [l.name() for l in self._layers],
                    "collision_layers": [l.name() for l in self._collision], "current_clips": [c.name() for c in self._clips],
                    "clip_times": self._times, "clip_weights": self._weights,
                    "pose_local": [m.asTuple() for m in self._pose], "packed_transform": self._packed.asTuple()}

    class Geometry:
        __slots__ = ("_points", "_prims", "_attrs", "_globals", "_library_state", "_origin")

        def __init__(self, src_geo=None, clone_data_ids=False):
            _bool(clone_data_ids)
            self._points, self._prims, self._globals, self._library_state, self._origin = [], [], {}, None, ORIGIN
            self._attrs = {s: {} for s in ("detail", "point", "primitive", "vertex")}
            self._attrs["point"]["P"] = Attrib(self, "point", "P", (0.0, 0.0, 0.0))
            if src_geo is not None:
                if not isinstance(src_geo, Geometry):
                    raise AgentAPIError("Geometry source must be detached fixture Geometry")
                self.loadFromString(src_geo.data())

        def _defaults(self, scope):
            return {n: copy.deepcopy(a._default) for n, a in self._attrs[scope].items()}

        def _resolve(self, scope, value):
            if isinstance(value, Attrib):
                if value._geo is not self or value._scope != scope:
                    raise AgentAPIError("attribute belongs to another geometry or scope")
                value = value.name()
            if not isinstance(value, str) or value not in self._attrs[scope]:
                raise AgentAPIError("attribute is not declared in this scope")
            return value

        def addAttrib(self, type, name, default_value, transform_as_normal=False, create_local_variable=False):
            scope = None
            for native, key in (("Global", "detail"), ("Point", "point"), ("Prim", "primitive"), ("Vertex", "vertex")):
                if hasattr(hou, "attribType") and type == getattr(hou.attribType, native):
                    scope = key
            if scope is None or name in self._attrs[scope]:
                raise AgentAPIError("unsupported attribute scope or duplicate name")
            attr = Attrib(self, scope, name, default_value, transform_as_normal, create_local_variable)
            self._attrs[scope][name] = attr
            if scope == "detail":
                self._globals[name] = copy.deepcopy(attr._default)
            else:
                elements = self._points if scope == "point" else self._prims if scope == "primitive" else [v for p in self._prims for v in p.vertices()]
                for item in elements:
                    item._attrs[name] = copy.deepcopy(attr._default)
            return attr

        def globalAttribs(self): return tuple(self._attrs["detail"].values())
        def pointAttribs(self): return tuple(self._attrs["point"].values())
        def primAttribs(self): return tuple(self._attrs["primitive"].values())
        def vertexAttribs(self): return tuple(self._attrs["vertex"].values())
        def attribValue(self, name_or_attrib): return self._globals[self._resolve("detail", name_or_attrib)]
        def setGlobalAttribValue(self, name_or_attrib, attrib_value):
            name = self._resolve("detail", name_or_attrib)
            self._globals[name] = _attribute(attrib_value, self._attrs["detail"][name]._default)
        def points(self): return tuple(self._points)
        def prims(self): return tuple(self._prims)

        def createPoint(self):
            point = Point(self, len(self._points))
            self._points.append(point)
            return point

        def createPolygon(self, is_closed=True):
            polygon = Polygon(self, len(self._prims), is_closed)
            self._prims.append(polygon)
            return polygon

        def createPacked(self, typename, point=None):
            if typename != "PackedAgent":
                raise AgentAPIError("only PackedAgent is supported by this detached API")
            if point is not None and (not isinstance(point, Point) or point._geo is not self or point not in self._points):
                raise AgentAPIError("packed point must belong to this Geometry")
            agent = Agent(self, len(self._prims))
            agent._vertex(self.createPoint() if point is None else point)
            self._prims.append(agent)
            return agent

        def countPrimType(self, typename):
            if typename not in ("PackedAgent", "Polygon"):
                raise AgentAPIError("unknown primitive type in detached API")
            return sum(p._kind == typename for p in self._prims)

        def _state(self):
            prims = []
            for p in self._prims:
                row = {"kind": p._kind, "attributes": p._attrs,
                       "vertices": [{"point": v.point().number(), "attributes": v._attrs} for v in p.vertices()]}
                row["closed" if isinstance(p, Polygon) else "agent"] = p.isClosed() if isinstance(p, Polygon) else p._state()
                prims.append(row)
            return {"origin": self._origin, "attributes": {scope: [{"name": a.name(), "default": a._default,
                    "transform_as_normal": a._normal, "create_local_variable": a._variable} for a in attrs.values()]
                    for scope, attrs in self._attrs.items()}, "global_values": self._globals,
                    "points": [{"attributes": p._attrs, "weight": p._weight} for p in self._points],
                    "primitives": prims, "shape_library": self._library_state}

        def data(self):
            return _json({"format": FORMAT, "origin": ORIGIN, "geometry": self._state()}).encode("utf-8")

        def loadFromString(self, data):
            if not isinstance(data, bytes) or not data:
                raise AgentAPIError("serialized detached geometry requires nonempty bytes")
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise AgentAPIError("duplicate serialized state key")
                    result[key] = value
                return result
            try:
                envelope = json.loads(data, object_pairs_hook=pairs,
                                      parse_constant=lambda value: (_ for _ in ()).throw(AgentAPIError("nonfinite JSON")))
                _keys(envelope, ("format", "origin", "geometry"))
                if envelope["format"] != FORMAT or envelope["origin"] != ORIGIN:
                    raise AgentAPIError("unknown detached geometry format or origin")
                fresh = load_geometry(envelope["geometry"])
            except (TypeError, KeyError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
                raise AgentAPIError("malformed detached geometry state") from exc
            self._points, self._prims, self._attrs, self._globals = fresh._points, fresh._prims, fresh._attrs, fresh._globals
            self._library_state = fresh._library_state
            for attrs in self._attrs.values():
                for a in attrs.values(): a._geo = self
            for item in self._points + self._prims + [v for p in self._prims for v in p.vertices()]: item._geo = self

    def origin(row):
        if row["origin"] != ORIGIN:
            raise AgentAPIError("serialized component lacks injected API origin")

    def load_rig(row):
        _keys(row, ("origin", "name", "transform_names", "hierarchy", "rest_local", "channels")); origin(row)
        if row["channels"] != []:
            raise AgentAPIError("additional rig channels are outside this finite API")
        rig = AgentRig(row["name"], row["transform_names"], row["hierarchy"])
        rig.setRestLocalTransforms([stored_matrix(m) for m in _sequence(row["rest_local"])])
        return rig

    def load_library(row):
        _keys(row, ("origin", "name", "shapes")); origin(row)
        library = AgentShapeLibrary(); library._name = _name(row["name"])
        for shape in _sequence(row["shapes"]):
            _keys(shape, ("name", "geometry"))
            library.addShape(shape["name"], load_geometry(shape["geometry"]))
        return library

    def load_definition(row):
        _keys(row, ("rig", "library", "layers", "clips", "transform_groups", "metadata"))
        if row["transform_groups"] != [] or row["metadata"] is not None:
            raise AgentAPIError("groups/metadata are outside this finite API")
        rig, library = load_rig(row["rig"]), load_library(row["library"])
        definition = AgentDefinition(rig, library); shapes = {s.name(): s for s in library.shapes()}
        for layer in _sequence(row["layers"]):
            _keys(layer, ("origin", "name", "bindings")); origin(layer)
            bindings = []
            for binding in _sequence(layer["bindings"]):
                _keys(binding, ("transform", "shape", "deforming", "bounds_scale"))
                if binding["shape"] not in shapes:
                    raise AgentAPIError("layer refers to a missing shape")
                bindings.append(AgentShapeBinding(binding["transform"], shapes[binding["shape"]], binding["deforming"], binding["bounds_scale"]))
            definition.addLayer(AgentLayer(layer["name"], rig, library, bindings))
        for row in _sequence(row["clips"]):
            _keys(row, ("origin", "name", "sample_rate", "start_time", "samples", "channels")); origin(row)
            if row["channels"] != []:
                raise AgentAPIError("additional clip channels are outside this finite API")
            samples = _sequence(row["samples"])
            clip = AgentClip(row["name"], rig, len(samples))
            clip._rate, clip._start = _number(row["sample_rate"]), _number(row["start_time"])
            if clip._rate <= 0:
                raise AgentAPIError("stored sample rate must be positive")
            for i, sample in enumerate(samples):
                clip.setLocalTransforms(i, [stored_matrix(m) for m in _sequence(sample)])
            definition.addClip(clip)
        return definition

    def values(geometry, scope, row):
        _keys(row, geometry._attrs[scope])
        return {name: _attribute(value, geometry._attrs[scope][name]._default) for name, value in row.items()}

    def named(rows, names):
        by_name = {r.name(): r for r in rows}
        names = _sequence(names)
        if any(not isinstance(n, str) or n not in by_name for n in names):
            raise AgentAPIError("binding refers to missing definition content")
        return [by_name[n] for n in names]

    def load_geometry(row):
        _keys(row, ("origin", "attributes", "global_values", "points", "primitives", "shape_library")); origin(row)
        geometry = Geometry(); geometry._attrs = {s: {} for s in geometry._attrs}
        _keys(row["attributes"], geometry._attrs)
        for scope, attrs in row["attributes"].items():
            for a in _sequence(attrs):
                _keys(a, ("name", "default", "transform_as_normal", "create_local_variable"))
                name = _name(a["name"])
                if name in geometry._attrs[scope]:
                    raise AgentAPIError("duplicate stored attribute declaration")
                geometry._attrs[scope][name] = Attrib(geometry, scope, name, a["default"], a["transform_as_normal"], a["create_local_variable"])
        p = geometry._attrs["point"].get("P")
        if p is None or p._default != (0.0, 0.0, 0.0) or any(type(v) is not float for v in p._default):
            raise AgentAPIError("missing or malformed point position declaration")
        geometry._globals = values(geometry, "detail", row["global_values"])
        for p in _sequence(row["points"]):
            _keys(p, ("attributes", "weight"))
            point = geometry.createPoint(); point._attrs = values(geometry, "point", p["attributes"])
            point._weight = _number(p["weight"])
        for p in _sequence(row["primitives"]):
            if not isinstance(p, dict) or p.get("kind") not in ("Polygon", "PackedAgent"):
                raise AgentAPIError("unknown stored primitive type")
            polygon = p["kind"] == "Polygon"
            _keys(p, ("kind", "attributes", "vertices", "closed" if polygon else "agent"))
            prim = geometry.createPolygon(p["closed"]) if polygon else Agent(geometry, len(geometry._prims))
            if not polygon: geometry._prims.append(prim)
            prim._attrs = values(geometry, "primitive", p["attributes"])
            for v in _sequence(p["vertices"]):
                _keys(v, ("point", "attributes"))
                vertex = prim._vertex(geometry._points[_index(v["point"], len(geometry._points))])
                vertex._attrs = values(geometry, "vertex", v["attributes"])
            if not polygon:
                if len(prim.vertices()) != 1:
                    raise AgentAPIError("PackedAgent must have one point vertex")
                a = _keys(p["agent"], ("definition", "current_layers", "collision_layers", "current_clips", "clip_times", "clip_weights", "pose_local", "packed_transform"))
                definition = load_definition(a["definition"]); prim.setDefinition(definition)
                prim.setCurrentLayers(named(definition.layers(), a["current_layers"]))
                prim._collision = named(definition.layers(), a["collision_layers"])
                prim.setClips(named(definition.clips(), a["current_clips"]))
                prim.setClipTimes(a["clip_times"]); prim.setClipWeights(a["clip_weights"])
                prim._pose = matrices([stored_matrix(m) for m in _sequence(a["pose_local"])], definition.rig().transformCount())
                prim._packed = stored_matrix(a["packed_transform"])
        if row["shape_library"] is not None:
            geometry._library_state = load_library(row["shape_library"])._state()
        return geometry

    for name, value in (("Geometry", Geometry), ("Point", Point), ("Polygon", Polygon),
                        ("AgentRig", AgentRig), ("AgentShapeLibrary", AgentShapeLibrary),
                        ("AgentShapeBinding", AgentShapeBinding), ("AgentLayer", AgentLayer),
                        ("AgentClip", AgentClip), ("AgentDefinition", AgentDefinition),
                        ("Agent", Agent), ("Matrix4", Matrix4),
                        ("hmath", SimpleNamespace(buildTranslate=translate))):
        setattr(hou, name, value)
