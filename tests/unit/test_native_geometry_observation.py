"""Static bottom HOM readbacks only; no VEX, node cook or expected deformation."""
from __future__ import annotations

import copy
import hashlib
from itertools import repeat
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_observation as collector


class NativeEnum:
    def __init__(self, name):
        self.enum_name = name

    def name(self):
        return self.enum_name


class NativeAttribute:
    def __init__(self, name, owner, kind, size, precision, default, *, qualifier='',
                 transformed=False, options=None):
        self.attribute_name = name
        self.owner = owner
        self.kind = kind
        self.tuple_size = size
        self.precision = precision
        self.default = default
        self.qualifier_value = qualifier
        self.transformed = transformed
        self.option_values = {} if options is None else options
        self.array = False

    def name(self):
        return self.attribute_name

    def type(self):
        return NativeEnum('Global' if self.owner == 'detail' else self.owner.title())

    def dataType(self):
        return NativeEnum(self.kind)

    def numericDataType(self):
        if self.kind == 'String':
            raise AssertionError('numericDataType is not a string attribute contract')
        return NativeEnum(self.precision)

    def size(self):
        return self.tuple_size

    def isArrayType(self):
        return self.array

    def qualifier(self):
        return self.qualifier_value

    def isTransformedAsNormal(self):
        return self.transformed

    def defaultValue(self):
        return self.default

    def options(self):
        return self.option_values


class NativeElement:
    def __init__(self, number, values):
        self.element_number = number
        self.values = values

    def number(self):
        return self.element_number

    def attribValue(self, attribute):
        return self.values[attribute.name()]


class NativeVertex(NativeElement):
    def __init__(self, number, point, values):
        super().__init__(number, values)
        self.target_point = point

    def point(self):
        return self.target_point

    def linearNumber(self):
        return self.element_number


class NativePrimitive(NativeElement):
    def __init__(self, number, vertices, values):
        super().__init__(number, values)
        self.vertex_elements = vertices
        self.kind = 'Polygon'
        self.closed = True

    def type(self):
        return NativeEnum(self.kind)

    def isClosed(self):
        return self.closed

    def vertices(self):
        return self.vertex_elements


class NativeGeometry:
    def __init__(self, version='21.0.631'):
        self.version = version
        self.attributes = {
            'point': [
                NativeAttribute('P', 'point', 'Float', 3, 'Float32', (0.0, 0.0, 0.0)),
                NativeAttribute('N', 'point', 'Float', 3, 'Float64', (0.0, 1.0, 0.0),
                                qualifier='normal', transformed=True),
                NativeAttribute('id', 'point', 'Int', 1, 'Int32', 0),
                NativeAttribute('label', 'point', 'String', 1, None, '',
                                options={'tag': '实际', 'visible': True}),
            ],
            'primitive': [NativeAttribute('pair', 'primitive', 'Int', 2, 'Int16', (0, 0))],
            'vertex': [NativeAttribute('uv', 'vertex', 'Float', 2, 'Float32', (0.0, 0.0))],
            'detail': [NativeAttribute('title', 'detail', 'String', 1, None, '')],
        }
        self.point_elements = [
            NativeElement(10, {'P': (0.0, 0.0, 0.0), 'N': (0.0, 1.0, 0.0), 'id': 101,
                               'label': 'first'}),
            NativeElement(30, {'P': (2.0, 0.0, 0.0), 'N': (0.0, 1.0, 0.0), 'id': 103,
                               'label': '第二点'}),
            NativeElement(20, {'P': (0.0, 0.0, 2.0), 'N': (0.0, 1.0, 0.0), 'id': 102,
                               'label': 'third'}),
        ]
        vertices = [
            NativeVertex(2, self.point_elements[1], {'uv': (1.0, 0.0)}),
            NativeVertex(0, self.point_elements[2], {'uv': (0.0, 1.0)}),
            NativeVertex(1, self.point_elements[0], {'uv': (0.0, 0.0)}),
        ]
        self.primitive_elements = [NativePrimitive(7, vertices, {'pair': (3, -4)})]
        self.detail_values = {'title': '静态 HOM 几何'}

    def points(self):
        return self.point_elements

    def prims(self):
        return self.primitive_elements

    def pointAttribs(self):
        return self.attributes['point']

    def primAttribs(self):
        return self.attributes['primitive']

    def vertexAttribs(self):
        return self.attributes['vertex']

    def globalAttribs(self):
        return self.attributes['detail']

    def attribValue(self, attribute):
        return self.detail_values[attribute.name()]

    def geometry(self, *args):
        raise AssertionError('collector must not acquire or cook node geometry')

    def cook(self, *args):
        raise AssertionError('collector must not cook')


class GeometryObservationTests(unittest.TestCase):
    def collect(self, geometry, **kwargs):
        return collector.collect(geometry, node_path='/obj/owned/actual_output', frame=1, **kwargs)

    def refuse(self, geometry, code):
        with self.assertRaises(collector.GeometryObservationError) as caught:
            self.collect(geometry)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code + ': native geometry observation refused')

    def test_four_owner_metadata_and_actual_values_both_fixture_versions(self):
        for version in ('21.0.631', '22.0.429'):
            with self.subTest(version=version):
                geometry = NativeGeometry(version)
                before = copy.deepcopy(geometry.__dict__)
                observed = self.collect(geometry)
                self.assertEqual(observed['origin'], 'runtime_hom')
                self.assertEqual(observed['attribute_scope'], 'public')
                self.assertEqual(set(observed['attributes']), {'point', 'primitive', 'vertex', 'detail'})
                self.assertEqual(observed['attributes']['point']['id']['values'], [101, 103, 102])
                self.assertEqual(observed['attributes']['primitive']['pair']['values'], [[3, -4]])
                self.assertEqual(observed['attributes']['vertex']['uv']['values'],
                                 [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
                self.assertEqual(observed['attributes']['detail']['title']['values'], ['静态 HOM 几何'])
                self.assertEqual(observed['attributes']['point']['N']['precision'], 'float64')
                self.assertTrue(observed['attributes']['point']['N']['transformed_as_normal'])
                self.assertEqual(observed['attributes']['point']['N']['qualifier'], 'normal')
                self.assertEqual(observed['attributes']['point']['label']['precision'], None)
                self.assertEqual(observed['attributes']['point']['label']['options'],
                                 {'tag': '实际', 'visible': True})
                self.assertEqual(geometry.point_elements[0].values, before['point_elements'][0].values)
                self.assertEqual(geometry.attributes['point'][1].__dict__,
                                 before['attributes']['point'][1].__dict__)
                self.assertNotIn('status', observed)
                self.assertNotIn('available', observed)

    def test_connectivity_maps_nonsequential_point_numbers_and_linear_vertices(self):
        observed = self.collect(NativeGeometry())
        self.assertEqual(observed['point_numbers'], [10, 30, 20])
        self.assertEqual(observed['primitive_numbers'], [7])
        self.assertEqual(observed['polygons'], [[1, 2, 0]])
        self.assertEqual(observed['vertex_numbers'], [2, 0, 1])
        self.assertEqual(observed['polygon_vertices'], [[0, 1, 2]])

    def test_missing_normals_and_ids_remain_absent(self):
        geometry = NativeGeometry()
        geometry.attributes['point'] = [attribute for attribute in geometry.attributes['point']
                                        if attribute.name() not in ('N', 'id')]
        observed = self.collect(geometry)
        self.assertEqual(set(observed['attributes']['point']), {'P', 'label'})

    def test_changes_in_topology_normals_and_extra_attributes_are_observable(self):
        original = NativeGeometry()
        changed = copy.deepcopy(original)
        changed.primitive_elements[0].vertex_elements.reverse()
        changed.point_elements[0].values['N'] = (1.0, 0.0, 0.0)
        changed.attributes['point'].append(NativeAttribute('extra', 'point', 'Int', 1, 'UInt8', 0))
        for point in changed.point_elements:
            point.values['extra'] = 4
        before, after = self.collect(original), self.collect(changed)
        self.assertNotEqual(before['observation_sha256'], after['observation_sha256'])
        self.assertNotEqual(before['polygons'], after['polygons'])
        self.assertNotEqual(before['attributes']['point']['N'], after['attributes']['point']['N'])
        self.assertEqual(before['attributes']['point']['P'], after['attributes']['point']['P'])
        self.assertEqual(before['attributes']['point']['label'], after['attributes']['point']['label'])
        self.assertIn('extra', after['attributes']['point'])

    def test_digest_is_actual_canonical_json_and_attribute_order_independent(self):
        geometry = NativeGeometry()
        observed = self.collect(geometry)
        digest = observed.pop('observation_sha256')
        encoded = json.dumps(observed, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(digest, hashlib.sha256(encoded).hexdigest())
        geometry.attributes['point'].reverse()
        self.assertEqual(digest, self.collect(geometry)['observation_sha256'])

    def test_empty_geometry_and_open_polygon_are_actual_facts(self):
        geometry = NativeGeometry()
        geometry.primitive_elements[0].closed = False
        self.assertEqual(self.collect(geometry)['primitive_closed'], [False])
        geometry.point_elements = []
        geometry.primitive_elements = []
        observed = self.collect(geometry)
        self.assertEqual((observed['points'], observed['primitives'], observed['vertices']), (0, 0, 0))
        self.assertEqual(observed['attributes']['point']['P']['values'], [])

    def test_geometry_digest_excludes_wrapper_path_frame_output(self):
        geometry = NativeGeometry()
        before = self.collect(geometry)
        after = collector.collect(geometry, node_path='/obj/other/output', frame=42, output_index=1)
        self.assertEqual(before['geometry_sha256'], after['geometry_sha256'])
        self.assertNotEqual(before['observation_sha256'], after['observation_sha256'])
        content = {name: before[name] for name in collector.CONTENT_FIELDS}
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(before['geometry_sha256'], hashlib.sha256(encoded).hexdigest())

    def test_complete_output_including_digests_respects_byte_cap(self):
        observed = self.collect(NativeGeometry())
        encoded = json.dumps(observed, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(collector.MAX_BYTES, 512 * 1024)
        with patch.object(collector, 'MAX_BYTES', len(encoded) - 1):
            self.refuse(NativeGeometry(), 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        with patch.object(collector, 'MAX_BYTES', len(encoded)):
            self.assertEqual(self.collect(NativeGeometry()), observed)

    def test_rejects_packed_volume_curve_and_unknown_primitives(self):
        for kind in ('PackedGeometry', 'Volume', 'VDB', 'BezierCurve', 'unknown'):
            with self.subTest(kind=kind):
                geometry = NativeGeometry()
                geometry.primitive_elements[0].kind = kind
                self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_PRIMITIVE')

    def test_rejects_array_and_dictionary_attributes(self):
        geometry = NativeGeometry()
        geometry.attributes['point'][0].array = True
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_ARRAY')
        geometry.attributes['point'][0].array = False
        geometry.attributes['point'][0].kind = 'Dict'
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE')

    def test_rejects_nonfinite_native_values_and_defaults(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                geometry = NativeGeometry()
                geometry.point_elements[0].values['P'] = (value, 0.0, 0.0)
                self.refuse(geometry, 'GEOMETRY_OBSERVATION_NONFINITE_VALUE')
                geometry.point_elements[0].values['P'] = (0.0, 0.0, 0.0)
                geometry.attributes['point'][0].default = (value, 0.0, 0.0)
                self.refuse(geometry, 'GEOMETRY_OBSERVATION_NONFINITE_VALUE')

    def test_rejects_scalar_tuple_and_storage_type_changes(self):
        for value in ((0.0, 0.0), (1, 0.0, 0.0), 'secret', (0.0, 0.0, True)):
            geometry = NativeGeometry()
            geometry.point_elements[0].values['P'] = value
            self.refuse(geometry, 'GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
        geometry = NativeGeometry()
        geometry.point_elements[0].values['id'] = True
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')

    def test_rejects_metadata_drift_during_value_read(self):
        geometry = NativeGeometry()
        point = geometry.point_elements[0]
        actual_read = point.attribValue

        def changed_read(attribute):
            value = actual_read(attribute)
            if attribute.name() == 'P':
                attribute.qualifier_value = 'changed'
            return value

        point.attribValue = changed_read
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')

    def test_rejects_unknown_and_mismatched_storage(self):
        for precision in ('half', 'UInt64', 'Int32'):
            geometry = NativeGeometry()
            geometry.attributes['point'][0].precision = precision
            self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_STORAGE')
        geometry = NativeGeometry()
        geometry.point_elements[0].values['id'] = 2147483648
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_VALUE')
        geometry = NativeGeometry()
        geometry.point_elements[0].values['P'] = (4e38, 0.0, 0.0)
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_VALUE')

    def test_supports_every_documented_numeric_storage_enum(self):
        for precision, kind, value, default in (
                ('Int8', 'Int', -2, 0), ('UInt8', 'Int', 255, 0),
                ('Int16', 'Int', -300, 0), ('Int32', 'Int', 120000, 0),
                ('Int64', 'Int', 9007199254740993, 0),
                ('Float16', 'Float', 2.0, 0.0), ('Float32', 'Float', 4.0, 0.0),
                ('Float64', 'Float', 8.0, 0.0)):
            geometry = NativeGeometry()
            geometry.attributes['detail'] = [NativeAttribute('value', 'detail', kind, 1, precision, default)]
            geometry.detail_values = {'value': value}
            observed = self.collect(geometry)['attributes']['detail']['value']
            self.assertEqual(observed['precision'], precision.lower())
            self.assertEqual(observed['values'], [value])

    def test_rejects_invalid_owner_and_duplicate_attributes(self):
        geometry = NativeGeometry()
        geometry.attributes['point'][0].owner = 'vertex'
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_ATTRIBUTE_TYPE_CHANGED')
        geometry = NativeGeometry()
        geometry.attributes['point'].append(geometry.attributes['point'][0])
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_METADATA')

    def test_rejects_duplicate_points_vertices_primitives_and_dangling_connectivity(self):
        geometry = NativeGeometry()
        geometry.point_elements[1].element_number = 10
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
        geometry = NativeGeometry()
        geometry.primitive_elements[0].vertex_elements[1].element_number = 2
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
        geometry = NativeGeometry()
        geometry.primitive_elements.append(geometry.primitive_elements[0])
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')
        geometry = NativeGeometry()
        geometry.primitive_elements[0].vertex_elements[0].target_point = NativeElement(999, {})
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_TOPOLOGY')

    def test_infinite_point_and_primitive_iterators_are_bounded(self):
        for method, item in (('points', NativeGeometry().point_elements[0]),
                             ('prims', NativeGeometry().primitive_elements[0])):
            geometry = NativeGeometry()
            counter = []

            def infinite_read():
                for value in repeat(item):
                    counter.append(1)
                    yield value

            setattr(geometry, method, infinite_read)
            self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
            self.assertEqual(len(counter), 8193)

    def test_infinite_vertex_iterator_and_cumulative_vertex_budget_are_bounded(self):
        geometry = NativeGeometry()
        vertex = geometry.primitive_elements[0].vertex_elements[0]
        counter = []

        def infinite_read():
            for value in repeat(vertex):
                counter.append(1)
                yield value

        geometry.primitive_elements[0].vertices = infinite_read
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        self.assertEqual(len(counter), 65537)
        geometry = NativeGeometry()
        primitive = copy.deepcopy(geometry.primitive_elements[0])
        primitive.element_number = 8
        geometry.primitive_elements.append(primitive)
        with patch.object(collector, 'MAX_VERTICES', 5):
            self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')

    def test_infinite_attribute_iterator_and_cumulative_attribute_budget_are_bounded(self):
        geometry = NativeGeometry()
        attribute = geometry.attributes['point'][0]
        counter = []

        def infinite_read():
            for value in repeat(attribute):
                counter.append(1)
                yield value

        geometry.pointAttribs = infinite_read
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        self.assertEqual(len(counter), collector.MAX_ATTRIBUTES + 1)
        with patch.object(collector, 'MAX_ATTRIBUTES', 5):
            self.refuse(NativeGeometry(), 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')

    def test_value_byte_string_tuple_and_options_budgets(self):
        for constant, cap in (('MAX_VALUES', 15), ('MAX_BYTES', 1024),
                              ('MAX_TOTAL_STRING_BYTES', 20), ('MAX_TUPLE_SIZE', 2)):
            with self.subTest(constant=constant), patch.object(collector, constant, cap):
                self.refuse(NativeGeometry(), 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        geometry = NativeGeometry()
        geometry.point_elements[0].values['label'] = '中' * 1400
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        geometry = NativeGeometry()
        geometry.attributes['point'][0].option_values = {str(index): 0 for index in range(65)}
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_METADATA')

    def test_error_details_do_not_leak_native_exception_or_attribute_data(self):
        geometry = NativeGeometry()

        def secret_read():
            raise RuntimeError('PRIVATE_NATIVE_PATH_AND_PAYLOAD')

        geometry.points = secret_read
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED')

        def broken_iterator():
            yield geometry.point_elements[0]
            raise RuntimeError('PRIVATE_ITERATOR_PAYLOAD')

        geometry.points = broken_iterator
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED')
        geometry = NativeGeometry()
        geometry.attributes['point'][0].attribute_name = '\ud800'
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_VALUE')

    def test_native_error_code_cannot_inject_private_detail(self):
        class BrokenGeometry:
            @property
            def points(self):
                error = collector.GeometryObservationError('GEOMETRY_OBSERVATION_INVALID_VALUE')
                error.code = 'PRIVATE_PATH_OR_DATA'
                raise error

        self.refuse(BrokenGeometry(), 'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED')

    def test_value_budget_aborts_before_remaining_native_value_reads(self):
        geometry = NativeGeometry()
        reads = []
        for point in geometry.point_elements:
            actual_read = point.attribValue

            def tracked_read(attribute, callback=actual_read):
                reads.append(attribute.name())
                return callback(attribute)

            point.attribValue = tracked_read
        with patch.object(collector, 'MAX_VALUES', 12):
            self.refuse(geometry, 'GEOMETRY_OBSERVATION_BUDGET_EXCEEDED')
        self.assertEqual(reads, [])

    def test_rejects_unknown_metadata_values_and_string_tuple_attributes(self):
        geometry = NativeGeometry()
        geometry.attributes['point'][0].option_values = {'private': {'secret': 1}}
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_INVALID_VALUE')
        geometry = NativeGeometry()
        geometry.attributes['point'][3].tuple_size = 2
        self.refuse(geometry, 'GEOMETRY_OBSERVATION_UNSUPPORTED_ATTRIBUTE')

    def test_context_requires_explicit_valid_native_path_frame_and_output(self):
        for changes in ({'node_path': '/'}, {'node_path': '/obj/../secret'},
                        {'frame': float('nan')}, {'frame': True},
                        {'output_index': -1}, {'output_index': True}):
            context = dict(node_path='/obj/owned/output', frame=1, output_index=0)
            context.update(changes)
            with self.assertRaises(collector.GeometryObservationError) as caught:
                collector.collect(NativeGeometry(), **context)
            self.assertEqual(caught.exception.code, 'GEOMETRY_OBSERVATION_INVALID_CONTEXT')
        observed = collector.collect(NativeGeometry(), node_path='/obj/中文/output', frame=-2.5,
                                     output_index=1)
        self.assertEqual((observed['frame'], observed['output']), (-2.5, 1))

    def test_package_controller_mirror_is_byte_identical(self):
        root = Path(__file__).resolve().parents[2]
        package = root / 'packages/houdini-bridge/src/houdini_bridge/native_geometry_observation.py'
        mirror = root / 'controller-entry/client/houdini_bridge/native_geometry_observation.py'
        self.assertEqual(package.read_bytes(), mirror.read_bytes())


if __name__ == '__main__':
    unittest.main()
