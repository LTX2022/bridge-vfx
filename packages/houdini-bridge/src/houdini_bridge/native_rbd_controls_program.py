"""R05 native carrier plans and bounded HOM observations for the host transaction."""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
import fnmatch
import hashlib
import hmac
import json
import math
import re
import secrets
import struct
from pathlib import PurePosixPath

from . import native_flip_rbd_domains as core

ROLE = 'rbd_velocity'
BASIS_SCHEMA = 'bridge.rbd-velocity-basis/1'
GEOMETRY_SCHEMA = 'bridge.rbd-packed-geometry/1'
PROGRAM_SCHEMA = 'bridge.rbd-velocity-program/1'
_SEAL_KEY = secrets.token_bytes(32)
GATES = {'class': ('ordinal', 'detail'), 'group': ('string', ''),
         'vex_precision': ('string', '64'), 'exportlist': ('string', 'v'),
         'bindings': ('multiparm', 0)}
EDGES = [('configure', 0, ROLE, 0), (ROLE, 0, 'solver', 0)]


def _fail(code, detail):
    raise core.NativeFlipRbdDomainError(code, detail)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        _fail('RBD_INVALID_NATIVE_FACT', str(error))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _vector(value, size):
    return isinstance(value, (list, tuple)) and len(value) == size and all(
        type(component) in (int, float) and math.isfinite(component) for component in value)


MAX_GEOMETRY_ELEMENTS = 8192
MAX_GEOMETRY_VERTICES = 65536
MAX_GEOMETRY_ATTRIBUTES = 4096
MAX_GEOMETRY_VALUES = 1048576
MAX_GEOMETRY_BYTES = 2097152
MAX_GEOMETRY_STRING_BYTES = 4096
MAX_GEOMETRY_DEPTH = 2


class _GeometryBudget:
    def __init__(self):
        self.elements = MAX_GEOMETRY_ELEMENTS
        self.vertices = MAX_GEOMETRY_VERTICES
        self.attributes = MAX_GEOMETRY_ATTRIBUTES
        self.values = MAX_GEOMETRY_VALUES
        self.bytes = MAX_GEOMETRY_BYTES
        self.active = set()

    def charge(self, size):
        self.bytes -= size
        if self.bytes < 0:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'serialized bytes')

    def scalar(self, value):
        self.values -= 1
        if self.values < 0:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'scalar values')
        if type(value) is str:
            if len(value) > MAX_GEOMETRY_STRING_BYTES:
                _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'string characters')
            if len(value.encode('utf-8')) > MAX_GEOMETRY_STRING_BYTES:
                _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'string UTF-8 bytes')
        elif type(value) is int:
            if not -(2 ** 63) <= value < 2 ** 63:
                _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'integer range')
        elif type(value) is float:
            if not math.isfinite(value):
                _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'nonfinite value')
        elif type(value) is not bool:
            _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'scalar type')
        self.charge(len(_json(value).encode('utf-8')) + 1)
        return value


class _GeometrySample:
    def __init__(self, hou_module, expected):
        self.hou = hou_module
        self.expected = expected

    def check(self):
        current = self.hou.frame()
        if type(current) not in (int, float) or not math.isfinite(current) or current != self.expected:
            _fail('RBD_NATIVE_SAMPLE_FRAME_CHANGED', 'native sample frame changed')

    def read(self, callback, *args, **kwargs):
        self.check()
        value = callback(*args, **kwargs)
        self.check()
        return value


def _bounded_native(values, limit, sample):
    result = []
    iterator = iter(values)
    for index in range(limit + 1):
        sample.check()
        try:
            value = next(iterator)
        except StopIteration:
            sample.check()
            return result
        sample.check()
        if index == limit:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'native enumeration')
        result.append(value)
    return result


def _elements(geometry, budget, sample):
    counts = []
    for name in ('pointCount', 'primCount'):
        callback = getattr(geometry, name, None)
        count = sample.read(callback) if callable(callback) else None
        if count is not None and (type(count) is not int or count < 1):
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'empty or invalid native element count')
        counts.append(count)
    if sum(count for count in counts if count is not None) > budget.elements:
        _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'aggregate elements')
    result = []
    remaining = budget.elements
    for names, count in zip((('iterPoints', 'points'), ('iterPrims', 'prims')), counts):
        callback = getattr(geometry, names[0], None)
        if not callable(callback):
            callback = getattr(geometry, names[1])
        values = _bounded_native(sample.read(callback), remaining, sample)
        if not values or count is not None and len(values) != count:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'empty or inconsistent native enumeration')
        result.append(values)
        remaining -= len(values)
    return result


def _attribute_metadata(geometry, method, sample, budget):
    attributes = _bounded_native(sample.read(getattr(geometry, method)), min(128, budget.attributes), sample)
    result = []
    names = set()
    for attribute in attributes:
        name = budget.scalar(sample.read(attribute.name))
        size = sample.read(attribute.size)
        array = sample.read(attribute.isArrayType)
        if type(name) is not str or not name or name in names:
            _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'missing or duplicate attribute name')
        if array is not False or type(size) is not int or not 1 <= size <= 16:
            _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'array or tuple size')
        kind = str(sample.read(attribute.dataType))
        storage = str(sample.read(attribute.numericDataType)) if kind.rsplit('.', 1)[-1].lower() != 'string' else 'string'
        budget.scalar(kind)
        budget.scalar(storage)
        kind = kind.rsplit('.', 1)[-1].lower()
        storage = storage.rsplit('.', 1)[-1]
        if (kind not in ('string', 'float', 'int') or kind == 'string' and size != 1 or
                kind == 'float' and storage not in ('Float16', 'Float32', 'Float64') or
                kind == 'int' and storage not in ('Int8', 'UInt8', 'Int16', 'Int32', 'Int64')):
            _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'unsupported type or storage')
        names.add(name)
        result.append((name, kind, size, storage))
    return result


def _attributes(elements, metadata, sample, budget):
    result = {}
    if len(metadata) > budget.attributes:
        _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'aggregate attributes')
    ranges = {'Int8': (-128, 127), 'UInt8': (0, 255), 'Int16': (-32768, 32767),
              'Int32': (-(2 ** 31), 2 ** 31 - 1), 'Int64': (-(2 ** 63), 2 ** 63 - 1)}
    float_ranges = {'Float16': 65504., 'Float32': 3.4028234663852886e38,
                    'Float64': 1.7976931348623157e308}
    for name, kind, size, storage in metadata:
        budget.attributes -= 1
        budget.charge(64)
        values = []
        for element in elements:
            value = sample.read(element.attribValue, name)
            if size == 1:
                components = (value,)
            elif type(value) in (tuple, list) and len(value) == size:
                components = value
            else:
                _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'attribute tuple shape')
            captured = []
            for component in components:
                if (kind == 'string' and type(component) is not str or
                        kind == 'int' and (type(component) is not int or not ranges[storage][0] <= component <= ranges[storage][1]) or
                        kind == 'float' and (type(component) not in (int, float) or
                                             abs(component) > float_ranges[storage])):
                    _fail('RBD_ATTRIBUTE_STORAGE_REQUIRED', 'attribute component type or storage')
                captured.append(budget.scalar(component))
            values.append(captured[0] if size == 1 else captured)
            budget.charge(2)
        result[name] = dict(type=kind, size=size, storage=storage, values=values)
    return result


def _native_vector(value, size, budget, sample):
    if type(value) not in (tuple, list) and not hasattr(value, '__len__'):
        _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'native vector shape')
    if len(value) != size:
        _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'native vector size')
    result = _bounded_native(value, size, sample)
    if not _vector(result, size):
        _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'native vector values')
    return [budget.scalar(component) for component in result]


def _geometry(geometry, budget, sample, *, packed, depth=0):
    if depth >= MAX_GEOMETRY_DEPTH or id(geometry) in budget.active:
        _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'geometry depth or cycle')
    budget.active.add(id(geometry))
    frozen = None
    try:
        _elements(geometry, budget, sample)
        _attribute_metadata(geometry, 'pointAttribs', sample, budget)
        _attribute_metadata(geometry, 'primAttribs', sample, budget)
        frozen = sample.read(geometry.freeze, read_only=True)
        if frozen is not geometry and id(frozen) in budget.active:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'frozen geometry cycle')
        budget.active.add(id(frozen))
        points, primitives = _elements(frozen, budget, sample)
        budget.elements -= len(points) + len(primitives)
        point_metadata = _attribute_metadata(frozen, 'pointAttribs', sample, budget)
        primitive_metadata = _attribute_metadata(frozen, 'primAttribs', sample, budget)
        result = dict(point_attributes=_attributes(points, point_metadata, sample, budget),
                      primitive_attributes=_attributes(primitives, primitive_metadata, sample, budget),
                      positions=[], primitives=[])
        budget.charge(96)
        point_numbers = [sample.read(point.number) for point in points]
        if any(type(number) is not int for number in point_numbers) or point_numbers != list(range(len(points))):
            _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'non-contiguous point numbers')
        for point in points:
            result['positions'].append(_native_vector(sample.read(point.position), 3, budget, sample))
        for primitive in primitives:
            kind = budget.scalar(sample.read(sample.read(primitive.type).name))
            if kind != ('PackedGeometry' if packed else 'Polygon'):
                _fail('RBD_PACKED_EMBEDDED_GEOMETRY_REQUIRED', 'packed root and embedded polygons required')
            vertices = _bounded_native(sample.read(primitive.vertices), budget.vertices, sample)
            budget.vertices -= len(vertices)
            indices = [sample.read(sample.read(vertex.point).number) for vertex in vertices]
            if (not indices or packed and len(indices) != 1 or
                    any(type(index) is not int or not 0 <= index < len(points) for index in indices)):
                _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'vertex point indices')
            item = dict(type=kind, vertices=[budget.scalar(index) for index in indices])
            budget.charge(96)
            if packed:
                item.update(transform=_native_vector(sample.read(sample.read(primitive.transform).asTuple), 9, budget, sample),
                            full_transform=_native_vector(sample.read(sample.read(primitive.fullTransform).asTuple), 16, budget, sample),
                            pivot=_native_vector(sample.read(primitive.intrinsicValue, 'pivot'), 3, budget, sample),
                            embedded=_geometry(sample.read(primitive.getEmbeddedGeometry), budget, sample,
                                               packed=False, depth=depth + 1))
            else:
                closed = sample.read(primitive.isClosed)
                if type(closed) is not bool:
                    _fail('RBD_PACKED_POINT_BINDING_REQUIRED', 'polygon closed metadata')
                item['closed'] = budget.scalar(closed)
            result['primitives'].append(item)
        sample.check()
        return result
    finally:
        budget.active.discard(id(geometry))
        if frozen is not None:
            budget.active.discard(id(frozen))


def collect_packed_geometry(node, frame, hou_module, *, output_index=0, input_index=None):
    version = hou_module.applicationVersionString()
    core._domain(core.RBD, version)
    if (type(frame) not in (int, float) or not math.isfinite(frame) or
            type(output_index) is not int or output_index != 0 or
            input_index is not None and (type(input_index) is not int or not 0 <= input_index <= 255)):
        _fail('RBD_NATIVE_SAMPLE_REQUIRED', 'finite frame, output zero and bounded native input index')
    previous = hou_module.frame()
    if type(previous) not in (int, float) or not math.isfinite(previous):
        _fail('RBD_NATIVE_SAMPLE_REQUIRED', 'finite original frame')
    sample = _GeometrySample(hou_module, previous)
    try:
        source_path = sample.read(node.path)
        if input_index is None:
            geometry = sample.read(node.geometryAtFrame, frame, output_index=output_index)
        else:
            connections = _bounded_native(sample.read(node.inputConnections), 256, sample)
            connections = [connection for connection in connections if sample.read(connection.inputIndex) == input_index]
            if len(connections) != 1 or sample.read(connections[0].outputIndex) != 0:
                _fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', 'native solver input')
            source_path = sample.read(sample.read(connections[0].inputNode).path)
            hou_module.setFrame(frame)
            sample.expected = frame
            sample.check()
            geometry = sample.read(node.inputGeometry, input_index)
        budget = _GeometryBudget()
        source_path = budget.scalar(source_path)
        if type(source_path) is not str:
            _fail('RBD_NATIVE_SAMPLE_REQUIRED', 'native source path')
        data = _geometry(geometry, budget, sample, packed=True)
        result = dict(schema=GEOMETRY_SCHEMA, origin='runtime_hom', native_version=version,
                      node_path=source_path, frame=frame, output_index=0, geometry=data)
        result['content_sha256'] = _digest(result)
        if len(_json(result).encode('utf-8')) > MAX_GEOMETRY_BYTES:
            _fail('RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED', 'complete serialized fact')
        _pieces(result)
        sample.check()
        return result
    except core.NativeFlipRbdDomainError:
        raise
    except Exception as error:
        _fail('RBD_PACKED_GEOMETRY_COLLECTION_FAILED', type(error).__name__)
    finally:
        try:
            if input_index is not None or hou_module.frame() != previous:
                hou_module.setFrame(previous)
                if hou_module.frame() != previous:
                    _fail('RBD_NATIVE_SAMPLE_FRAME_CHANGED', 'original frame restore failed')
        except core.NativeFlipRbdDomainError:
            raise
        except Exception:
            _fail('RBD_NATIVE_SAMPLE_FRAME_CHANGED', 'original frame restore failed')


def _pieces(fact):
    if (not isinstance(fact, dict) or fact.get('schema') != GEOMETRY_SCHEMA or
            fact.get('origin') != 'runtime_hom' or fact.get('native_version') not in (*core.VERSIONS, *PREPARATION_VERSIONS) or
            type(fact.get('output_index')) is not int or fact['output_index'] != 0 or
            type(fact.get('frame')) not in (int, float) or not math.isfinite(fact['frame']) or
            fact.get('content_sha256') !=
            _digest({key: value for key, value in fact.items() if key != 'content_sha256'})):
        _fail('RBD_ACTUAL_PACKED_GEOMETRY_REQUIRED', 'collector identity or content digest')
    geometry = fact.get('geometry', {})
    positions = geometry.get('positions', [])
    primitives = geometry.get('primitives', [])
    attributes = geometry.get('point_attributes', {})
    names = geometry.get('primitive_attributes', {}).get('name', {})
    if (not 1 <= len(primitives) <= 8192 or len(primitives) != len(positions) or
            names.get('type') != 'string' or names.get('size') != 1 or
            len(names.get('values', [])) != len(primitives)):
        _fail('RBD_STABLE_PACKED_PIECE_IDS_REQUIRED', 'one primitive and one unique point per piece')
    for name in ('v', 'w'):
        attribute = attributes.get(name, {})
        if (attribute.get('type') != 'float' or attribute.get('size') != 3 or
                attribute.get('storage') not in ('Float32', 'Float64') or
                len(attribute.get('values', [])) != len(positions) or
                any(not _vector(value, 3) for value in attribute['values'])):
            _fail('RBD_ACTUAL_BASE_VELOCITY_REQUIRED', 'point/' + name)
    active = attributes.get('active', {})
    if (active.get('type') != 'int' or active.get('size') != 1 or
            len(active.get('values', [])) != len(positions) or
            any(type(value) is not int or value != 1 for value in active['values'])):
        _fail('RBD_ACTIVATION_EVENT_CARRIER_REQUIRED', 'only active initial pieces supported')
    if any(not _vector(position, 3) for position in positions):
        _fail('RBD_ACTUAL_PACKED_GEOMETRY_REQUIRED', 'positions')
    ids, point_indices, rows = set(), set(), []
    for name, primitive in zip(names['values'], primitives):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,256}', name) or name in ids:
            _fail('RBD_STABLE_PACKED_PIECE_IDS_REQUIRED', 'missing, duplicate or unsupported name')
        vertices = primitive.get('vertices', [])
        if (primitive.get('type') != 'PackedGeometry' or len(vertices) != 1 or
                type(vertices[0]) is not int or not 0 <= vertices[0] < len(positions) or vertices[0] in point_indices or
                not _vector(primitive.get('transform'), 9) or not _vector(primitive.get('full_transform'), 16) or
                not _vector(primitive.get('pivot'), 3) or not primitive.get('embedded')):
            _fail('RBD_PACKED_POINT_BINDING_REQUIRED', name)
        point_index = vertices[0]
        ids.add(name)
        point_indices.add(point_index)
        rows.append(dict(name=name, point=point_index, v=attributes['v']['values'][point_index],
                         w=attributes['w']['values'][point_index]))
    return rows


def velocity_basis(version, identity, geometry_fact, task_seed, initialization_frame):
    core._domain(core.RBD, version)
    _pieces(geometry_fact)
    basis = dict(schema=BASIS_SCHEMA, origin='runtime_hom', task_owned=True,
                 native_version=version, identity=copy.deepcopy(identity), task_seed=task_seed,
                 initialization_frame=initialization_frame, geometry=copy.deepcopy(geometry_fact))
    basis['content_sha256'] = _digest(basis)
    _basis(basis, version)
    return basis


def _basis(basis, version):
    if (not isinstance(basis, dict) or basis.get('schema') != BASIS_SCHEMA or
            basis.get('origin') != 'runtime_hom' or basis.get('task_owned') is not True or
            basis.get('native_version') != version or basis.get('content_sha256') !=
            _digest({key: value for key, value in basis.items() if key != 'content_sha256'})):
        _fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'same-version host basis')
    identity = basis.get('identity', {})
    root = identity.get('task_root')
    if (not isinstance(root, str) or not root.startswith('/obj/') or '..' in root.split('/') or
            str(PurePosixPath(root)) != root or not isinstance(identity.get('task_id'), str) or not identity['task_id'] or
            type(basis.get('task_seed')) is not int or not 0 <= basis['task_seed'] < 2 ** 31 or
            type(basis.get('initialization_frame')) is not int or not -100000 <= basis['initialization_frame'] <= 100000):
        _fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'task, seed or initialization frame')
    geometry = basis['geometry']
    if (geometry.get('native_version') != version or geometry.get('frame') != basis['initialization_frame'] or
            not geometry.get('node_path', '').startswith(root + '/')):
        _fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'native geometry sample identity')
    return _pieces(geometry)


def _context(version, observations):
    basis = observations.get((ROLE, '@basis'))
    rows = _basis(basis, version)
    upstream = observations.get(('configure', '@packed_geometry/0'))
    if upstream != basis['geometry']:
        _fail('RBD_VELOCITY_BASE_GEOMETRY_CHANGED', 'configure output differs from frozen basis')
    root = basis['identity']['task_root']
    for role, node_type in (('configure', 'rbdconfigure'), (ROLE, 'attribwrangle'), ('solver', 'rbdbulletsolver')):
        node = observations.get((role, '@node'), {})
        if (node.get('origin') != 'runtime_hom' or node.get('native_version') != version or
                node.get('task_id') != basis['identity']['task_id'] or node.get('task_root') != root or
                node.get('type') != node_type or node.get('category') != 'sop' or node.get('editable') is not True or
                not node.get('node_path', '').startswith(root + '/') or '..' in node['node_path'].split('/')):
            _fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', role)
        host_identity = node.get('host_identity', {})
        if (host_identity.get('task_id') != basis['identity']['task_id'] or host_identity.get('version') != version or
                type(host_identity.get('pid')) is not int or host_identity['pid'] < 1 or
                any(not isinstance(host_identity.get(field), str) or not host_identity[field] for field in
                    ('launch_nonce', 'session_id', 'process_generation')) or
                not re.fullmatch(r'[0-9a-f]{64}', str(host_identity.get('plugin_build', ''))) or
                type(host_identity.get('scene_epoch')) is not int or host_identity['scene_epoch'] < 0 or
                host_identity != observations.get(('configure', '@node'), {}).get('host_identity')):
            _fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', 'complete current host identity/' + role)
    if upstream['node_path'] != observations[('configure', '@node')]['node_path']:
        _fail('RBD_VELOCITY_BASE_GEOMETRY_CHANGED', 'source node differs')
    for source, output, target, input_index in EDGES:
        wire = observations.get((target, '@input/' + str(input_index)), {})
        if (wire.get('origin') != 'runtime_hom' or wire.get('source_role') != source or
                wire.get('source_output') != output or
                wire.get('source_path') != observations[(source, '@node')]['node_path']):
            _fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', target)
    for name, (kind, value) in GATES.items():
        parameter = core._runtime(observations, ROLE, name, kind)
        if any(parameter.get(flag) is not False for flag in ('locked', 'hidden', 'disabled')) or not core._gate_matches(parameter, value):
            _fail('RBD_VELOCITY_PROGRAM_GATE_BLOCKED', name)
    for name, kind in (('startframe', 'integer'), ('overwriteattributes', 'string'), ('usescale', 'toggle')):
        parameter = core._runtime(observations, 'solver', name, kind)
        if name == 'startframe' and parameter['value'] != basis['initialization_frame']:
            _fail('RBD_ACTIVATION_EVENT_CARRIER_REQUIRED', 'solver initial frame differs')
        if name == 'usescale' and parameter['value'] != 0:
            _fail('RBD_VELOCITY_UNIT_CONSUMPTION_REQUIRED', 'Bullet world scale must be disabled')
        if name == 'overwriteattributes' and any(fnmatch.fnmatchcase('v', pattern) for pattern in parameter['value'].split()):
            _fail('RBD_VELOCITY_REPEATED_OVERWRITE_FORBIDDEN', parameter['value'])
    timescale = core._runtime(observations, 'solver', 'timescale', 'float')['value']
    time_fact = observations.get(('solver', '@time'), {})
    if (time_fact.get('origin') != 'runtime_hom' or not core._typed_value(time_fact.get('fps'), 'float', 1) or
            time_fact['fps'] <= 0 or timescale != 1):
        _fail('RBD_VELOCITY_UNIT_CONSUMPTION_REQUIRED', 'positive actual FPS and native time scale one')
    core._runtime(observations, ROLE, 'snippet', 'string')
    return basis, rows


def _velocities(basis, rows, amplitude):
    storage = basis['geometry']['geometry']['point_attributes']['v']['storage']
    result = []
    for row in rows:
        velocity = []
        for axis in range(3):
            random_hash = hashlib.sha256(_json(['R05/initial-v/1', basis['task_seed'], row['name'], axis]).encode()).digest()
            unit = (int.from_bytes(random_hash[:8], 'big') >> 11) / float(2 ** 53)
            value = row['v'][axis] + amplitude * (2 * unit - 1)
            try:
                value = struct.unpack('f', struct.pack('f', value))[0] if storage == 'Float32' else value
            except (OverflowError, struct.error):
                _fail('RBD_VELOCITY_NATIVE_STORAGE_OVERFLOW', row['name'])
            if not math.isfinite(value):
                _fail('RBD_VELOCITY_NATIVE_STORAGE_OVERFLOW', row['name'])
            velocity.append(value)
        result.append(velocity)
    return result


def _snippet(rows, velocities):
    names = ','.join(json.dumps(row['name']) for row in rows)
    vectors = ','.join('set(' + ','.join(repr(value) for value in velocity) + ')' for velocity in velocities)
    return ('string piece_ids[] = array(' + names + ');\nvector initial_velocities[] = array(' + vectors + ');\n'
            'for (int primitive_index = 0; primitive_index < nprimitives(0); primitive_index++) {\n'
            '    string piece_id = prim(0, "name", primitive_index);\n'
            '    int piece_index = find(piece_ids, piece_id);\n'
            '    if (piece_index >= 0) {\n'
            '        int point_index = primpoint(0, primitive_index, 0);\n'
            '        setpointattrib(0, "v", point_index, initial_velocities[piece_index], "set");\n'
            '    }\n}\n')


def velocity_write_plan(value, version, observations):
    value = core._number(value, 0, 1000, 'velocity_variance')
    basis, rows = _context(version, observations)
    snippet = _snippet(rows, _velocities(basis, rows, value))
    written = core._write(ROLE, 'snippet', snippet, 'string', value_kind='trusted_rbd_velocity_program',
                         public_value=value, native_version=version)
    keys = [(ROLE, '@basis'), ('configure', '@packed_geometry/0')]
    keys += [(role, '@node') for role in ('configure', ROLE, 'solver')]
    keys += [(target, '@input/' + str(input_index)) for _, _, target, input_index in EDGES]
    keys += [(ROLE, name) for name in (*GATES, 'snippet')]
    keys += [('solver', name) for name in ('startframe', 'overwriteattributes', 'usescale', 'timescale', '@time')]
    guards = [dict(role=role, parm=name, value=copy.deepcopy(observations[(role, name)])) for role, name in keys if name.startswith('@')]
    guards += [core._guard(role, name, observations[(role, name)]) for role, name in keys if not name.startswith('@')]
    written['frozen_readback_guards'] = guards
    written['registration'] = dict(schema=PROGRAM_SCHEMA, native_version=version, value=value,
        basis_sha256=basis['content_sha256'], snippet_sha256=hashlib.sha256(snippet.encode()).hexdigest())
    frozen = _json(written)
    written['frozen_velocity_json'] = frozen
    written['velocity_seal'] = hmac.new(_SEAL_KEY, frozen.encode(), hashlib.sha256).hexdigest()
    validate_velocity_plan([written], observations)
    return [written]


def validate_velocity_plan(writes, observations, *, after_mutation=False):
    for write in writes:
        if write.get('role') != ROLE or write.get('parm') != 'snippet':
            continue
        frozen = write.get('frozen_velocity_json', '')
        if (not isinstance(frozen, str) or not hmac.compare_digest(
                hmac.new(_SEAL_KEY, frozen.encode(), hashlib.sha256).hexdigest(), str(write.get('velocity_seal', ''))) or
                _json({key: value for key, value in write.items() if key not in ('frozen_velocity_json', 'velocity_seal')}) != frozen):
            _fail('UNTRUSTED_RBD_VELOCITY_WRITE', 'issued plan changed or another process')
        basis, rows = _context(write['native_version'], observations)
        if write['value'] != _snippet(rows, _velocities(basis, rows, write['public_value'])):
            _fail('UNTRUSTED_RBD_VELOCITY_WRITE', 'program differs from frozen native basis')
        if after_mutation:
            validate_velocity_readback([write], observations)


def validate_velocity_readback(writes, observations):
    results = []
    for write in writes:
        if write.get('value_kind') != 'trusted_rbd_velocity_program':
            continue
        basis, rows = _context(write['native_version'], observations)
        if observations[(ROLE, 'snippet')]['value'] != write['value']:
            _fail('RBD_ACTUAL_VELOCITY_PROGRAM_REGISTRATION_REQUIRED', 'native snippet differs')
        if observations.get((ROLE, '@program')) != dict(origin='runtime_hom', **write['registration']):
            _fail('RBD_ACTUAL_VELOCITY_PROGRAM_REGISTRATION_REQUIRED', 'saved program differs')
        expected = copy.deepcopy(basis['geometry']['geometry'])
        velocities = _velocities(basis, rows, write['public_value'])
        for row, velocity in zip(rows, velocities):
            expected['point_attributes']['v']['values'][row['point']] = velocity
        for role, field in ((ROLE, '@packed_geometry/0'), ('solver', '@input_geometry/0')):
            actual = observations.get((role, field), {})
            _pieces(actual)
            source_role = ROLE
            if (actual.get('node_path') != observations[(source_role, '@node')]['node_path'] or
                    actual.get('native_version') != write['native_version'] or
                    actual.get('frame') != basis['initialization_frame'] or actual['geometry'] != expected):
                _fail('RBD_ACTUAL_VELOCITY_CONSUMPTION_MISMATCH', role + '/' + field)
        results.append(dict(value=write['public_value'], evidence_scope='packed_initial_velocity_carrier',
                            basis_sha256=basis['content_sha256'], pieces=len(rows),
                            native_simulation='NOT_RUN'))
    return results


def velocity_control_readback(version, observations):
    registration = observations.get((ROLE, '@program'), {})
    if registration.get('origin') != 'runtime_hom' or registration.get('schema') != PROGRAM_SCHEMA:
        _fail('RBD_ACTUAL_VELOCITY_PROGRAM_REGISTRATION_REQUIRED', 'native saved registration required')
    writes = velocity_write_plan(registration.get('value'), version, observations)
    core.validate_applied_readback(writes, observations)
    return validate_velocity_readback(writes, observations)[0]['value']
