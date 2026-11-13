from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
import unittest

from houdini_bridge import native_rbd_controls_program as program
from test_native_rbd_controls_program import Attribute, Geometry, Point, Primitive, packed_geometry


class BoundedGeometry:
    def __init__(self, geometry):
        self.geometry = geometry
        self.freeze_calls = 0
        self.point_reads = 0
        self.primitive_reads = 0
        self.attribute_reads = 0

    def freeze(self, read_only=True):
        self.freeze_calls += 1
        return self

    def pointCount(self):
        return len(self.geometry.point_list)

    def primCount(self):
        return len(self.geometry.primitive_list)

    def iterPoints(self):
        for point in self.geometry.point_list:
            self.point_reads += 1
            yield point

    def iterPrims(self):
        for primitive in self.geometry.primitive_list:
            self.primitive_reads += 1
            yield primitive

    def points(self):
        return tuple(self.iterPoints())

    def prims(self):
        return tuple(self.iterPrims())

    def pointAttribs(self):
        for attribute in self.geometry.point_fields:
            self.attribute_reads += 1
            yield attribute

    def primAttribs(self):
        return iter(self.geometry.primitive_fields)


def fixture(version='21.0.631'):
    geometry = BoundedGeometry(packed_geometry())
    for primitive in geometry.geometry.primitive_list:
        primitive.embedded = BoundedGeometry(primitive.embedded)
    hou = SimpleNamespace(current_frame=12.)
    hou.applicationVersionString = lambda: version
    hou.frame = lambda: hou.current_frame
    hou.setFrame = lambda frame: setattr(hou, 'current_frame', frame)
    source = SimpleNamespace(path=lambda: '/obj/task/configure')
    node = SimpleNamespace(path=source.path,
        geometryAtFrame=lambda frame, output_index=0: geometry,
        inputGeometry=lambda index: geometry,
        inputConnections=lambda: [SimpleNamespace(inputIndex=lambda: 0,
            outputIndex=lambda: 0, inputNode=lambda: source)])
    return node, hou, geometry


class RbdGeometryCollectionBoundsTests(unittest.TestCase):
    def collect(self, node, hou, **kwargs):
        return program.collect_packed_geometry(node, 1, hou, **kwargs)

    def assert_budget(self, callback):
        with self.assertRaisesRegex(ValueError, 'RBD_NATIVE_GEOMETRY_BUDGET_EXCEEDED'):
            callback()

    def test_normal_fixed_geometry_retains_original_schema_and_digest(self):
        digests = {
            '21.0.631': '07bde8182e30bb0530ef673ea0ae094e6cce0021dc0944ac4434f2e82f9ba2f2',
            '22.0.429': 'beec93c86cd0b92b356e81ccbd7fdb010fa31563b472ffd5e3b1f09ff61fdffa',
        }
        for version, expected in digests.items():
            with self.subTest(version=version):
                node, hou, geometry = fixture(version)
                fact = self.collect(node, hou)
                self.assertEqual(fact['schema'], program.GEOMETRY_SCHEMA)
                self.assertEqual(fact['content_sha256'], expected)
                body = {key: value for key, value in fact.items() if key != 'content_sha256'}
                encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
                self.assertEqual(hashlib.sha256(encoded.encode()).hexdigest(), expected)
                self.assertEqual(hou.frame(), 12.)

    def test_point_count_refuses_before_freeze_and_native_enumeration(self):
        node, hou, geometry = fixture()
        geometry.pointCount = lambda: 8193
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertEqual(geometry.freeze_calls, 0)
        self.assertEqual(geometry.point_reads, 0)
        self.assertEqual(geometry.primitive_reads, 0)

    def test_aggregate_counts_refuse_before_freeze(self):
        node, hou, geometry = fixture()
        geometry.primCount = lambda: 8191
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertEqual(geometry.freeze_calls, 0)

    def test_lazy_point_enumeration_stops_at_limit_plus_one(self):
        node, hou, geometry = fixture()
        geometry.pointCount = None
        def oversized_points():
            for index in range(8200):
                geometry.point_reads += 1
                yield Point(index, (0., 0., 0.), {})
        geometry.iterPoints = oversized_points
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertLessEqual(geometry.point_reads, 8193)
        self.assertEqual(geometry.freeze_calls, 0)

    def test_lazy_primitive_enumeration_stops_at_remaining_plus_one(self):
        node, hou, geometry = fixture()
        geometry.primCount = None
        primitive = geometry.geometry.primitive_list[0]
        def oversized_primitives():
            for index in range(8200):
                geometry.primitive_reads += 1
                yield primitive
        geometry.iterPrims = oversized_primitives
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertLessEqual(geometry.primitive_reads, 8191)
        self.assertEqual(geometry.freeze_calls, 0)

    def test_attribute_enumeration_stops_at_limit_plus_one(self):
        node, hou, geometry = fixture()
        geometry.geometry.point_fields = [Attribute('a' + str(index), 'Float', 1, 'Float64')
            for index in range(140)]
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertLessEqual(geometry.attribute_reads, 129)
        self.assertEqual(geometry.freeze_calls, 0)

    def test_duplicate_attribute_name_is_not_silently_overwritten(self):
        node, hou, geometry = fixture()
        geometry.geometry.point_fields.append(Attribute('temperature', 'Float', 1, 'Float64'))
        with self.assertRaisesRegex(ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
            self.collect(node, hou)

    def test_attribute_name_budget_refuses_before_value_read(self):
        node, hou, geometry = fixture()
        attribute = Attribute('x' * 4097, 'String', 1, 'string')
        geometry.geometry.point_fields.append(attribute)
        self.assert_budget(lambda: self.collect(node, hou))

    def test_attribute_string_budget_includes_utf8_and_json_escaping(self):
        for value in ('x' * 4097, '\u4e2d' * 1366, '\n' * 4097):
            with self.subTest(length=len(value)):
                node, hou, geometry = fixture()
                geometry.geometry.point_fields.append(Attribute('label', 'String', 1, 'string'))
                for point in geometry.geometry.point_list:
                    point.values['label'] = value
                self.assert_budget(lambda: self.collect(node, hou))

    def test_nested_tuple_and_cycle_values_are_rejected_without_serializing(self):
        for value in ([[0.] * 10000] * 3, None):
            node, hou, geometry = fixture()
            if value is None:
                value = []
                value.append(value)
            geometry.geometry.point_list[0].values['v'] = value
            with self.subTest(cycle=len(value) == 1), self.assertRaisesRegex(
                    ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
                self.collect(node, hou)

    def test_unknown_kind_or_numeric_storage_is_rejected(self):
        for kind, storage in (('Dict', 'Float64'), ('Float', 'Imaginary128')):
            node, hou, geometry = fixture()
            geometry.geometry.point_fields[-1] = Attribute('temperature', kind, 1, storage)
            with self.subTest(kind=kind, storage=storage), self.assertRaisesRegex(
                    ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
                self.collect(node, hou)

    def test_nested_geometry_exhaustion_refuses_before_nested_freeze(self):
        node, hou, geometry = fixture()
        embedded = geometry.geometry.primitive_list[0].embedded
        embedded.pointCount = lambda: 8192
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertEqual(embedded.freeze_calls, 0)

    def test_geometry_cycle_refuses_before_repeated_freeze(self):
        node, hou, geometry = fixture()
        geometry.geometry.primitive_list[0].embedded = geometry
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertEqual(geometry.freeze_calls, 1)

    def test_vertex_enumeration_is_bounded(self):
        node, hou, geometry = fixture()
        embedded = geometry.geometry.primitive_list[0].embedded
        primitive = embedded.geometry.primitive_list[0]
        reads = []
        def vertices():
            for index in range(66000):
                reads.append(index)
                yield SimpleNamespace(point=lambda: embedded.geometry.point_list[0])
        primitive.vertices = vertices
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertLessEqual(len(reads), 65536)

    def test_embedded_topology_cannot_reference_missing_points(self):
        node, hou, geometry = fixture()
        embedded = geometry.geometry.primitive_list[0].embedded
        embedded.geometry.primitive_list[0].points = [Point(500, (0., 0., 0.), {})]
        with self.assertRaisesRegex(ValueError, 'RBD_PACKED_POINT_BINDING_REQUIRED'):
            self.collect(node, hou)

    def test_total_observation_bytes_stop_further_native_value_reads(self):
        node, hou, geometry = fixture()
        embedded = geometry.geometry.primitive_list[0].embedded
        embedded.geometry.point_fields = [Attribute('s' + str(index), 'String', 1, 'string')
            for index in range(128)]
        embedded.geometry.point_list = [Point(index, (0., 0., 0.), {}) for index in range(50)]
        reads = []
        for point in embedded.geometry.point_list:
            def value(name):
                reads.append(name)
                return '\u4e2d' * 1000
            point.attribValue = value
        self.assert_budget(lambda: self.collect(node, hou))
        self.assertLess(len(reads), 128 * 50)

    def test_frame_restores_after_lazy_read_on_both_native_routes(self):
        for input_index in (None, 0):
            node, hou, geometry = fixture()
            point = geometry.geometry.point_list[0]
            original = point.position
            def position():
                hou.setFrame(-99.)
                return original()
            point.position = position
            with self.subTest(input_index=input_index), self.assertRaisesRegex(
                    ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED'):
                self.collect(node, hou, input_index=input_index)
            self.assertEqual(hou.frame(), 12.)

    def test_input_acquisition_drift_refuses_before_freeze(self):
        node, hou, geometry = fixture()
        def input_geometry(index):
            hou.setFrame(-99.)
            return geometry
        node.inputGeometry = input_geometry
        with self.assertRaisesRegex(ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED'):
            self.collect(node, hou, input_index=0)
        self.assertEqual(geometry.freeze_calls, 0)
        self.assertEqual(hou.frame(), 12.)

    def test_direct_acquisition_drift_refuses_before_freeze(self):
        node, hou, geometry = fixture()
        def geometry_at_frame(frame, output_index=0):
            hou.setFrame(-99.)
            return geometry
        node.geometryAtFrame = geometry_at_frame
        with self.assertRaisesRegex(ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED'):
            self.collect(node, hou)
        self.assertEqual(geometry.freeze_calls, 0)
        self.assertEqual(hou.frame(), 12.)

    def test_normal_direct_route_never_calls_global_set_frame(self):
        node, hou, geometry = fixture()
        calls = []
        hou.setFrame = lambda frame: calls.append(frame)
        self.collect(node, hou)
        self.assertEqual(calls, [])

    def test_frame_restores_after_native_failure_on_both_routes(self):
        for input_index in (None, 0):
            node, hou, geometry = fixture()
            def failed_freeze(read_only=True):
                hou.setFrame(-99.)
                raise RuntimeError('fixed native failure')
            geometry.freeze = failed_freeze
            with self.subTest(input_index=input_index), self.assertRaisesRegex(
                    ValueError, 'RBD_PACKED_GEOMETRY_COLLECTION_FAILED'):
                self.collect(node, hou, input_index=input_index)
            self.assertEqual(hou.frame(), 12.)

    def test_freeze_frame_drift_is_rejected_on_both_routes(self):
        for input_index in (None, 0):
            node, hou, geometry = fixture()
            def freeze(read_only=True):
                hou.setFrame(-99.)
                return geometry
            geometry.freeze = freeze
            with self.subTest(input_index=input_index), self.assertRaisesRegex(
                    ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED'):
                self.collect(node, hou, input_index=input_index)
            self.assertEqual(hou.frame(), 12.)

    def test_normal_input_route_freezes_at_requested_frame_then_restores(self):
        for version in ('21.0.631', '22.0.429'):
            node, hou, geometry = fixture(version)
            observed = []
            original = geometry.freeze
            def freeze(read_only=True):
                observed.append(hou.frame())
                return original(read_only=read_only)
            geometry.freeze = freeze
            with self.subTest(version=version):
                fact = self.collect(node, hou, input_index=0)
                self.assertEqual(observed, [1])
                self.assertEqual(hou.frame(), 12.)
                self.assertEqual(fact['frame'], 1)

    def test_vector_iterator_frame_drift_is_rejected(self):
        node, hou, geometry = fixture()
        class Position:
            def __len__(self):
                return 3
            def __iter__(self):
                hou.setFrame(-99.)
                yield from (0., 0., 0.)
        geometry.geometry.point_list[0].position = Position
        with self.assertRaisesRegex(ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED'):
            self.collect(node, hou)
        self.assertEqual(hou.frame(), 12.)

    def test_native_counts_and_frozen_counts_must_match_enumeration(self):
        for mutation in ('live', 'frozen'):
            node, hou, geometry = fixture()
            if mutation == 'live':
                geometry.pointCount = lambda: 3
            else:
                frozen = BoundedGeometry(packed_geometry())
                frozen.pointCount = lambda: 8193
                geometry.freeze = lambda read_only=True: frozen
            with self.subTest(mutation=mutation):
                self.assert_budget(lambda: self.collect(node, hou))

    def test_array_attributes_are_rejected_before_freeze(self):
        node, hou, geometry = fixture()
        geometry.geometry.point_fields[0].isArrayType = lambda: True
        with self.assertRaisesRegex(ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
            self.collect(node, hou)
        self.assertEqual(geometry.freeze_calls, 0)

    def test_nested_packed_geometry_is_not_recursively_collected(self):
        node, hou, geometry = fixture()
        embedded = geometry.geometry.primitive_list[0].embedded
        deeper = BoundedGeometry(packed_geometry())
        embedded.geometry.primitive_list[0].embedded = deeper
        with self.assertRaisesRegex(ValueError, 'RBD_PACKED_EMBEDDED_GEOMETRY_REQUIRED'):
            self.collect(node, hou)
        self.assertEqual(deeper.freeze_calls, 0)

    def test_nonfinite_extra_attributes_do_not_enter_json(self):
        for value in (float('nan'), float('inf')):
            node, hou, geometry = fixture()
            geometry.geometry.point_list[0].values['temperature'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
                self.collect(node, hou)

    def test_numeric_storage_ranges_are_checked_before_json(self):
        for kind, storage, value in (('Float', 'Float16', 65505.), ('Float', 'Float32', 1e39),
                                     ('Int', 'Int8', 128), ('Int', 'UInt8', -1)):
            node, hou, geometry = fixture()
            geometry.geometry.point_fields[-1] = Attribute('temperature', kind, 1, storage)
            geometry.geometry.point_list[0].values['temperature'] = value
            with self.subTest(kind=kind, storage=storage), self.assertRaisesRegex(
                    ValueError, 'RBD_ATTRIBUTE_STORAGE_REQUIRED'):
                self.collect(node, hou)

    def test_pure_basis_keeps_collected_fixed_geometry_unchanged(self):
        for version in ('21.0.631', '22.0.429'):
            node, hou, geometry = fixture(version)
            with self.subTest(version=version):
                fact = self.collect(node, hou)
                before = json.dumps(fact, sort_keys=True)
                basis = program.velocity_basis(version, dict(task_id='task', task_root='/obj/task'), fact, 123, 1)
                self.assertEqual(basis['geometry'], fact)
                self.assertEqual(json.dumps(fact, sort_keys=True), before)
                self.assertEqual(basis['task_seed'], 123)
                self.assertEqual(hou.frame(), 12.)

    def test_boolean_point_numbers_do_not_alias_integer_indices(self):
        node, hou, geometry = fixture()
        geometry.geometry.point_list[0].number = lambda: False
        with self.assertRaisesRegex(ValueError, 'RBD_PACKED_POINT_BINDING_REQUIRED'):
            self.collect(node, hou)

    def test_restore_failure_has_specific_safe_error(self):
        node, hou, geometry = fixture()
        def set_frame(frame):
            if frame == 12.:
                raise RuntimeError('private native details')
            hou.current_frame = frame
        hou.setFrame = set_frame
        with self.assertRaisesRegex(ValueError, 'RBD_NATIVE_SAMPLE_FRAME_CHANGED') as caught:
            self.collect(node, hou, input_index=0)
        self.assertNotIn('private native details', str(caught.exception))

    def test_invalid_indices_refuse_before_native_acquisition(self):
        for kwargs in ({'output_index': False}, {'input_index': False}, {'input_index': -1},
                       {'input_index': 0.5}):
            node, hou, geometry = fixture()
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'RBD_NATIVE_SAMPLE_REQUIRED'):
                self.collect(node, hou, **kwargs)
            self.assertEqual(geometry.freeze_calls, 0)
            self.assertEqual(hou.frame(), 12.)


if __name__ == '__main__':
    unittest.main()
