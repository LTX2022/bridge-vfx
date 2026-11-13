"""Bounded readback of an already acquired HOM geometry.

The caller owns cook authorization, frame stability and native-call timeouts.
This collector reads public HOM attributes only, never requests geometry from
a node, writes native data, predicts deformation, or grants an evidence status.
Vertex values follow primitive traversal; vertex_numbers retain their actual
detail-wide linear numbers. Missing attributes remain absent.
"""
from __future__ import annotations

import hashlib
from itertools import islice
import json
import math
from pathlib import PurePosixPath

SCHEMA = 'bridge.geometry-observation/1'
MAX_POINTS = 8192
MAX_PRIMITIVES = 8192
MAX_VERTICES = 65536
MAX_ATTRIBUTES = 256
MAX_TUPLE_SIZE = 64
MAX_VALUES = 1048576
MAX_BYTES = 524288
MAX_STRING_BYTES = 4096
MAX_TOTAL_STRING_BYTES = 1048576
MAX_OPTIONS = 64
CONTENT_FIELDS = (
    'attribute_scope', 'points', 'primitives', 'vertices', 'point_numbers', 'primitive_numbers',
    'vertex_numbers', 'primitive_types', 'primitive_closed', 'polygons',
    'polygon_vertices', 'attributes',
)
ERROR_CODES = (
    'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED',
    'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_TYPE',
    'GEOMETRY_OBSERVATION_INVALID_TOPOLOGY',
    'GEOMETRY_OBSERVATION_INVALID_VALUE',
    'GEOMETRY_OBSERVATION_NONFINITE_VALUE',
    'GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED',
    'GEOMETRY_OBSERVATION_INVALID_METADATA',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_ARRAY',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_STORAGE',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_METADATA',
    'GEOMETRY_OBSERVATION_INVALID_CONTEXT',
    'GEOMETRY_OBSERVATION_UNSUPPORTED_PRIMITIVE',
)
_INTEGER_RANGES = {
    'int8': (-128, 127), 'uint8': (0, 255),
    'int16': (-32768, 32767), 'int32': (-2147483648, 2147483647),
    'int64': (-9223372036854775808, 9223372036854775807),
}
_FLOAT_RANGES = {
    'float16': 65504.0, 'float32': 3.4028234663852886e38,
    'float64': 1.7976931348623157e308,
}


class GeometryObservationError(ValueError):
    def __init__(self, code):
        if type(code) is not str or code not in ERROR_CODES:
            code = 'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED'
        self.code = code
        super().__init__(code + ': native geometry observation refused')


def _fail(code):
    raise GeometryObservationError(code)


def _call(callback, *args):
    try:
        return callback(*args)
    except Exception:
        raise GeometryObservationError('GEOMETRY_OBSERVATION_NATIVE_READ_FAILED') from None


def _bounded(values, limit):
    try:
        result = tuple(islice(iter(values), limit + 1))
    except Exception:
        raise GeometryObservationError('GEOMETRY_OBSERVATION_NATIVE_READ_FAILED') from None
    if len(result) > limit:
        _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
    return result


def _enum(value):
    name = _call(value.name)
    if type(name) is not str or len(name) > 64:
        _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_TYPE')
    return name.lower()


def _integer(value):
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
    return value


class _Budget:
    def __init__(self):
        self.values = 0
        self.bytes = 0
        self.string_bytes = 0
        self.attributes = 0

    def reserve(self, count):
        if self.values + count > MAX_VALUES:
            _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')

    def scalar(self, value):
        self.reserve(1)
        self.values += 1
        if type(value) is str:
            if len(value) > MAX_STRING_BYTES:
                _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
            try:
                length = len(value.encode('utf-8'))
            except UnicodeError:
                raise GeometryObservationError('GEOMETRY_OBSERVATION_INVALID_VALUE') from None
            self.string_bytes += length
            if length > MAX_STRING_BYTES or self.string_bytes > MAX_TOTAL_STRING_BYTES:
                _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        if type(value) is int and not -9223372036854775808 <= value <= 9223372036854775807:
            _fail('GEOMETRY_OBSERVATION_INVALID_VALUE')
        if type(value) is float and not math.isfinite(value):
            _fail('GEOMETRY_OBSERVATION_NONFINITE_VALUE')
        if type(value) not in (str, int, float, bool):
            _fail('GEOMETRY_OBSERVATION_INVALID_VALUE')
        self.bytes += len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) + 1
        if self.bytes > MAX_BYTES:
            _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        return value


def _typed_value(value, metadata, budget):
    size = metadata['size']
    if size == 1:
        components = (value,)
    else:
        if type(value) not in (tuple, list) or len(value) != size:
            _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
        components = value
    result = []
    for component in components:
        kind = metadata['type']
        precision = metadata['precision']
        if kind == 'integer':
            if type(component) is not int:
                _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
            lower, upper = _INTEGER_RANGES[precision]
            if not lower <= component <= upper:
                _fail('GEOMETRY_OBSERVATION_INVALID_VALUE')
        elif kind == 'float':
            if type(component) is not float:
                _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
            if not math.isfinite(component):
                _fail('GEOMETRY_OBSERVATION_NONFINITE_VALUE')
            if abs(component) > _FLOAT_RANGES[precision]:
                _fail('GEOMETRY_OBSERVATION_INVALID_VALUE')
        elif type(component) is not str:
            _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
        result.append(budget.scalar(component))
    return result[0] if size == 1 else result


def _metadata(attribute, owner, budget):
    name = budget.scalar(_call(attribute.name))
    qualifier = budget.scalar(_call(attribute.qualifier))
    if type(name) is not str or not name or type(qualifier) is not str:
        _fail('GEOMETRY_OBSERVATION_INVALID_METADATA')
    actual_owner = _enum(_call(attribute.type))
    if actual_owner != ('global' if owner == 'detail' else owner):
        _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
    kind = _enum(_call(attribute.dataType))
    if kind == 'int':
        kind = 'integer'
    if kind not in ('integer', 'float', 'string'):
        _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE')
    size = _call(attribute.size)
    is_array = _call(attribute.isArrayType)
    if type(is_array) is not bool:
        _fail('GEOMETRY_OBSERVATION_INVALID_METADATA')
    if is_array:
        _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_ARRAY')
    if type(size) is not int or not 1 <= size <= MAX_TUPLE_SIZE:
        _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
    if kind == 'string' and size != 1:
        _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE')
    precision = None
    if kind != 'string':
        precision = _enum(_call(attribute.numericDataType))
        allowed = _INTEGER_RANGES if kind == 'integer' else _FLOAT_RANGES
        if precision not in allowed:
            _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_STORAGE')
    transformed = _call(attribute.isTransformedAsNormal)
    if type(transformed) is not bool:
        _fail('GEOMETRY_OBSERVATION_INVALID_METADATA')
    metadata = dict(owner=owner, type=kind, size=size, precision=precision,
                    is_array=is_array, qualifier=qualifier,
                    transformed_as_normal=transformed)
    metadata['default'] = _typed_value(_call(attribute.defaultValue), metadata, budget)
    options = _call(attribute.options)
    if type(options) is not dict or len(options) > MAX_OPTIONS:
        _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_METADATA')
    captured_options = {}
    for key, value in options.items():
        if type(key) is not str:
            _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_METADATA')
        captured_options[budget.scalar(key)] = budget.scalar(value)
    metadata['options'] = captured_options
    return name, metadata


def _collect(geometry, *, node_path, frame, output_index):
    if (type(node_path) is not str or len(node_path) > MAX_STRING_BYTES
            or not node_path.startswith('/') or node_path == '/'
            or str(PurePosixPath(node_path)) != node_path
            or any(part in ('.', '..') for part in node_path.split('/'))
            or type(frame) not in (int, float) or not math.isfinite(frame)
            or not -1e12 <= frame <= 1e12
            or type(output_index) is not int or not 0 <= output_index <= 1024):
        _fail('GEOMETRY_OBSERVATION_INVALID_CONTEXT')
    budget = _Budget()
    budget.scalar(node_path)
    points = _bounded(_call(geometry.points), MAX_POINTS)
    primitives = _bounded(_call(geometry.prims), MAX_PRIMITIVES)
    point_numbers = [_integer(_call(point.number)) for point in points]
    primitive_numbers = [_integer(_call(primitive.number)) for primitive in primitives]
    if len(set(point_numbers)) != len(points) or len(set(primitive_numbers)) != len(primitives):
        _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
    point_indices = {number: index for index, number in enumerate(point_numbers)}
    polygons, primitive_types, primitive_closed = [], [], []
    vertices, vertex_numbers, polygon_vertices = [], [], []
    for primitive in primitives:
        if _enum(_call(primitive.type)) != 'polygon':
            _fail('GEOMETRY_OBSERVATION_UNSUPPORTED_PRIMITIVE')
        closed = _call(primitive.isClosed)
        if type(closed) is not bool:
            _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
        native_vertices = _bounded(_call(primitive.vertices), MAX_VERTICES - len(vertices))
        if len(native_vertices) < (3 if closed else 2):
            _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
        polygon = []
        indices = []
        for vertex in native_vertices:
            number = _integer(_call(_call(vertex.point).number))
            if number not in point_indices:
                _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
            polygon.append(point_indices[number])
            indices.append(len(vertices))
            vertices.append(vertex)
            vertex_numbers.append(_integer(_call(vertex.linearNumber)))
        primitive_types.append('Polygon')
        primitive_closed.append(closed)
        polygons.append(polygon)
        polygon_vertices.append(indices)
    if set(vertex_numbers) != set(range(len(vertices))):
        _fail('GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
    attributes = {}
    for owner, callback, elements in (
            ('point', geometry.pointAttribs, points),
            ('primitive', geometry.primAttribs, primitives),
            ('vertex', geometry.vertexAttribs, vertices),
            ('detail', geometry.globalAttribs, (geometry,))):
        native_attributes = _bounded(_call(callback), MAX_ATTRIBUTES - budget.attributes)
        budget.attributes += len(native_attributes)
        captured = {}
        for attribute in native_attributes:
            name, metadata = _metadata(attribute, owner, budget)
            if name in captured:
                _fail('GEOMETRY_OBSERVATION_INVALID_METADATA')
            budget.reserve(len(elements) * metadata['size'])
            values = [_typed_value(_call(element.attribValue, attribute), metadata, budget)
                      for element in elements]
            after_name, after_metadata = _metadata(attribute, owner, budget)
            if after_name != name or after_metadata != metadata:
                _fail('GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
            captured[name] = dict(metadata, values=values)
        attributes[owner] = captured
    observation = dict(schema=SCHEMA, origin='runtime_hom', node_path=node_path,
                       attribute_scope='public',
                       frame=frame, output=output_index, points=len(points),
                       primitives=len(primitives), vertices=len(vertices),
                       point_numbers=point_numbers, primitive_numbers=primitive_numbers,
                       vertex_numbers=vertex_numbers, primitive_types=primitive_types,
                       primitive_closed=primitive_closed, polygons=polygons,
                       polygon_vertices=polygon_vertices, attributes=attributes)
    content = {name: observation[name] for name in CONTENT_FIELDS}
    content_encoded = json.dumps(content, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), allow_nan=False).encode('utf-8')
    observation['geometry_sha256'] = hashlib.sha256(content_encoded).hexdigest()
    encoded = json.dumps(observation, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
    observation['observation_sha256'] = hashlib.sha256(encoded).hexdigest()
    if len(json.dumps(observation, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')) > MAX_BYTES:
        _fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
    return observation


def collect(geometry, *, node_path, frame, output_index=0):
    """Return actual bounded JSON facts; the caller authenticates their context."""
    try:
        return _collect(geometry, node_path=node_path, frame=frame, output_index=output_index)
    except GeometryObservationError as error:
        raise GeometryObservationError(error.code) from None
    except Exception:
        raise GeometryObservationError('GEOMETRY_OBSERVATION_NATIVE_READ_FAILED') from None

