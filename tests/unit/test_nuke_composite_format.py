"""Native Format values survive composite freeze and cold-process verification."""
import copy
import json
import unittest
from types import SimpleNamespace

from nuke_bridge.operation_receipts import (COMPOSITE_SCHEMA, composite_graph_readback,
                                          verify_composite_graph)


class Format:
    def __init__(self, width=128): self._width = width
    def name(self): return None
    def width(self): return self._width
    def height(self): return 64
    def x(self): return -4
    def y(self): return 2
    def r(self): return self._width - 4
    def t(self): return 66
    def pixelAspect(self): return 1.25


class Knob:
    def __init__(self, value): self.current = value
    def value(self): return self.current
    def isAnimated(self): return False
    def hasExpression(self): return False


class Node:
    def __init__(self):
        self.knobs = {key: Knob(value) for key, value in {
            'format': Format(), 'bridge_task_id': 'task-format', 'raw': False,
            'colorspace': 'ACEScg', 'file': '/output.exr', 'disable': False,
        }.items()}
    def knob(self, name): return self.knobs.get(name)
    def Class(self): return 'Reformat'
    def inputs(self): return 0


class CompositeFormatTests(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.nuke = SimpleNamespace(Format=Format, toNode=lambda name: self.node)
        self.contract = {'schema': COMPOSITE_SCHEMA, 'task_id': 'task-format',
                         'write': 'Reformat1', 'nodes': {'Reformat1': {'knobs': {
                             key: None for key in self.node.knobs}}}}

    def test_freeze_then_new_native_object_matches_serialized_contract(self):
        self.contract['nodes'] = composite_graph_readback(self.nuke, self.contract)
        frozen = json.loads(json.dumps(self.contract, allow_nan=False))
        values = frozen['nodes']['Reformat1']['knobs']
        self.assertEqual(values['format'], {'native_type': 'nuke.Format', 'name': None,
            'width': 128, 'height': 64, 'x': -4, 'y': 2, 'r': 124, 't': 66,
            'pixelAspect': 1.25})
        self.assertIs(type(values['raw']), bool)
        self.assertEqual(values['colorspace'], 'ACEScg')
        self.node.knobs['format'].current = Format()
        verify_composite_graph(self.nuke, frozen)
        self.node.knobs['format'].current = Format(256)
        with self.assertRaisesRegex(ValueError, 'COMPOSITE_SNAPSHOT_MISMATCH'):
            verify_composite_graph(self.nuke, frozen)

    def test_malformed_native_fields_and_unknown_objects_fail_closed(self):
        for value in (128.0, 2**128):
            self.node.knobs['format'].current = Format(value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Format field'):
                composite_graph_readback(self.nuke, self.contract)
        class Nonfinite(Format):
            def pixelAspect(self): return float('nan')
        self.node.knobs['format'].current = Nonfinite()
        with self.assertRaisesRegex(ValueError, 'Format field'):
            composite_graph_readback(self.nuke, self.contract)
        self.node.knobs['format'].current = object()
        with self.assertRaises(TypeError):
            composite_graph_readback(self.nuke, self.contract)

    def test_task_owner_animation_and_primitive_drift_are_still_rejected(self):
        self.contract['nodes'] = composite_graph_readback(self.nuke, self.contract)
        for key, value in (('bridge_task_id', 'other'), ('raw', True),
                           ('colorspace', 'linear'), ('file', '/other.exr')):
            with self.subTest(key=key):
                before = self.node.knobs[key].current
                self.node.knobs[key].current = value
                with self.assertRaisesRegex(ValueError, 'COMPOSITE_SNAPSHOT_MISMATCH'):
                    verify_composite_graph(self.nuke, self.contract)
                self.node.knobs[key].current = before
        self.node.knobs['format'].isAnimated = lambda: True
        with self.assertRaisesRegex(ValueError, 'non-static knob'):
            verify_composite_graph(self.nuke, self.contract)
