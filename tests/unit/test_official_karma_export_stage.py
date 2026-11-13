"""Software-only output-stage regressions; no native export or DCC execution.

Real code under test: official_karma_native.verify_output_stage (including its
native_value conversion). USD attributes/prims/relationships/stages and HOM
nodes/parameters below are small, in-memory API substitutes; no pxr/hou import,
file export, subprocess, render, or sampling is involved.

The explicitly named ROP source-selection substitute supplies the rule that
physical input 0 takes precedence over loppath. Its selected stage is checked by
the real verifier; this does not attest native ROP selection or USD export.
Beauty fixture types are string/name and token/format. The current verifier
checks their presence and values, but does not enforce those two USD types.
"""
from types import SimpleNamespace
import unittest

from houdini_bridge import official_karma_native as native


OUTPUT = '/software-fixture/official.0001.exr'
AUTHOR = '/stage/lights/update_output_image_path'
BEAUTY_NAME = 'driver:parameters:aov:husk:name'
BEAUTY_FORMAT = 'driver:parameters:aov:husk:format'


class _Attribute:
    def __init__(self, value, usd_type):
        self.value = value
        self.usd_type = usd_type

    def Get(self, frame): return self.value
    def GetTypeName(self): return self.usd_type
    def HasAuthoredValueOpinion(self): return True


class _Relationship:
    def __init__(self, *targets): self.targets = targets
    def GetTargets(self): return self.targets


class _Prim:
    def __init__(self, attributes, relationships=None):
        self.attributes = attributes
        self.relationships = {} if relationships is None else relationships

    def GetAttribute(self, name): return self.attributes.get(name)
    def GetRelationship(self, name): return self.relationships.get(name)


class _Stage:
    def __init__(self, prims): self.prims = prims
    def GetPrimAtPath(self, path): return self.prims.get(path)


def _complete_stage():
    """All effective output fields, with independently declared types/values."""
    return _Stage({
        native.SETTINGS: _Prim({
            'resolution': _Attribute((420, 300), 'int2'),
        }, {'products': _Relationship(native.PRODUCT)}),
        native.PRODUCT: _Prim({
            'productName': _Attribute(OUTPUT, 'token'),
            'productType': _Attribute('raster', 'token'),
            'driver:parameters:husk:source_colorspace': _Attribute('scene_linear', 'string'),
            'driver:parameters:husk:output_colorspace': _Attribute('ACEScg', 'string'),
            'driver:parameters:husk:OpenEXR:storage': _Attribute('scanline', 'string'),
            'driver:parameters:husk:OpenEXR:multipart': _Attribute(False, 'bool'),
            'driver:parameters:husk:OpenEXR:compression': _Attribute('zips', 'string'),
        }, {'orderedVars': _Relationship(native.BEAUTY)}),
        native.BEAUTY: _Prim({
            'sourceName': _Attribute('C.*[LO]', 'string'),
            'sourceType': _Attribute('lpe', 'token'),
            'dataType': _Attribute('color4f', 'token'),
            BEAUTY_NAME: _Attribute('C', 'string'),
            BEAUTY_FORMAT: _Attribute('color4h', 'token'),
        }),
    })


class _Lop:
    def __init__(self, path, stage):
        self._path = path
        self._stage = stage

    def path(self): return self._path
    def stage(self): return self._stage


class _Rop:
    def __init__(self, physical_input, loppath):
        self.physical_input = physical_input
        self.loppath = loppath

    def input(self, index):
        assert index == 0
        return self.physical_input

    def setInput(self, index, source):
        assert index == 0
        self.physical_input = source

    def parm(self, name):
        assert name == 'loppath'
        return SimpleNamespace(evalAsString=lambda: self.loppath)


def _rop_source_selection_substitute(hou, rop):
    """Explicit software policy substitute, never a native export operation."""
    source = rop.input(0)
    return source if source is not None else hou.node(rop.parm('loppath').evalAsString())


class OfficialKarmaExportStageTests(unittest.TestCase):
    def test_complete_typed_stage_passes_real_verifier(self):
        self.assertEqual(native.verify_output_stage(_complete_stage(), OUTPUT), {
            'resolution': [420, 300],
            'product': native.PRODUCT,
            'beauty': native.BEAUTY,
            'product_name': OUTPUT,
            'attributes': {
                'driver:parameters:husk:source_colorspace': 'scene_linear',
                'driver:parameters:husk:output_colorspace': 'ACEScg',
                'driver:parameters:husk:OpenEXR:storage': 'scanline',
                'driver:parameters:husk:OpenEXR:multipart': False,
                'driver:parameters:husk:OpenEXR:compression': 'zips',
            },
            'rgba_beauty': {
                'sourceName': 'C.*[LO]', 'sourceType': 'lpe', 'dataType': 'color4f',
                BEAUTY_NAME: 'C', BEAUTY_FORMAT: 'color4h',
            },
        })

    def test_missing_either_beauty_driver_attribute_is_rejected(self):
        for name in (BEAUTY_NAME, BEAUTY_FORMAT):
            with self.subTest(attribute=name):
                stage = _complete_stage()
                del stage.GetPrimAtPath(native.BEAUTY).attributes[name]
                with self.assertRaises(ValueError) as caught:
                    native.verify_output_stage(stage, OUTPUT)
                self.assertEqual(str(caught.exception),
                                 'OFFICIAL_OUTPUT_ATTRIBUTE_REQUIRED:' + name)

    def test_wrong_beauty_driver_values_are_rejected(self):
        for name, value in ((BEAUTY_NAME, 'RGBA'), (BEAUTY_FORMAT, 'color3h')):
            with self.subTest(attribute=name, value=value):
                stage = _complete_stage()
                stage.GetPrimAtPath(native.BEAUTY).GetAttribute(name).value = value
                with self.assertRaises(ValueError) as caught:
                    native.verify_output_stage(stage, OUTPUT)
                self.assertEqual(str(caught.exception), 'OFFICIAL_OUTPUT_RGBA_BEAUTY_REQUIRED')

    def test_rop_source_substitute_rejects_old_input_then_accepts_adapter(self):
        legacy_stage = _complete_stage()
        for name in (BEAUTY_NAME, BEAUTY_FORMAT):
            del legacy_stage.GetPrimAtPath(native.BEAUTY).attributes[name]
        author = _Lop(AUTHOR, legacy_stage)
        adapter = _Lop(native.BEAUTY_ADAPTER, _complete_stage())
        nodes = {source.path(): source for source in (author, adapter)}
        hou = SimpleNamespace(node=nodes.get)
        rop = _Rop(author, adapter.path())

        # Correct loppath alone cannot override the stale physical connection
        # under this explicit substitute's selection rule.
        selected = _rop_source_selection_substitute(hou, rop)
        self.assertIs(selected, author)
        with self.assertRaises(ValueError) as caught:
            native.verify_output_stage(selected.stage(), OUTPUT)
        self.assertEqual(str(caught.exception), 'OFFICIAL_OUTPUT_ATTRIBUTE_REQUIRED:' + BEAUTY_NAME)

        rop.setInput(0, adapter)
        selected = _rop_source_selection_substitute(hou, rop)
        self.assertIs(selected, adapter)
        self.assertEqual(native.verify_output_stage(selected.stage(), OUTPUT)['rgba_beauty'], {
            'sourceName': 'C.*[LO]', 'sourceType': 'lpe', 'dataType': 'color4f',
            BEAUTY_NAME: 'C', BEAUTY_FORMAT: 'color4h',
        })

    def test_rop_source_substitute_uses_loppath_when_input_is_absent(self):
        adapter = _Lop(native.BEAUTY_ADAPTER, _complete_stage())
        hou = SimpleNamespace(node={adapter.path(): adapter}.get)
        selected = _rop_source_selection_substitute(hou, _Rop(None, adapter.path()))
        self.assertIs(selected, adapter)
        self.assertEqual(native.verify_output_stage(selected.stage(), OUTPUT)['product_name'], OUTPUT)


if __name__ == '__main__':
    unittest.main()
