"""Native property identities in the explicit bottom USD authoring fixture."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/houdini-bridge/src'))
from houdini_bridge.render_color_facts import collect_render_color_facts

spec = importlib.util.spec_from_file_location('render_property_boundary', ROOT / 'tools/software_render_api_boundary.py')
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


class ParameterInput:
    def __init__(self, value):
        self.value = value

    def parmTemplate(self):
        return SimpleNamespace(menuItems=lambda: ())

    def eval(self):
        return self.value


class NodeInput:
    def __init__(self, kind, parameters, upstream=()):
        self.kind, self.parameters, self.upstream = kind, parameters, upstream

    def path(self):
        return '/stage/' + self.kind

    def type(self):
        return SimpleNamespace(name=lambda: self.kind)

    def inputs(self):
        return self.upstream

    def parm(self, name):
        return ParameterInput(self.parameters[name]) if name in self.parameters else None


class SoftwareRenderPropertyIdentityTests(unittest.TestCase):
    def settings(self):
        return NodeInput('karmarendersettings', dict(primpath='/Render/settings', pixelfiltersize=2,
            pixelfilterscale=1, renderproductsparentprimpath='/Render', picture='beauty.$F4.exr',
            camera='/Camera/main', custom_metadata=1, metadata_type_1='string',
            metadata_key_1='artist', metadata_string_1='explicit-input', image_exr_compression='none'))

    def product(self, upstream=()):
        return NodeInput('renderproduct', dict(createprims='forceedit' if upstream else 'on',
            primpattern='/Render/renderproduct', primpath='/Render/renderproduct',
            productName_control='set', productName='current/beauty.$F4.exr',
            productType_control='set', productType='raster'), upstream)

    def stage(self, node, version='21.0.631'):
        with mock.patch.dict(sys.modules, hou=SimpleNamespace(applicationVersionString=lambda: version)):
            return boundary.Stage(node, 1)

    def test_authored_attributes_keep_identity_in_both_lookup_methods(self):
        for version in ('21.0.631', '22.0.429'):
            stage = self.stage(self.settings(), version)
            for prim in stage.Traverse():
                for name, stored in prim.attributes.items():
                    with self.subTest(version=version, name=name):
                        self.assertIs(prim.GetAttribute(name), stored)
                        self.assertEqual(stored.GetName(), name)
                self.assertEqual({attribute.GetName() for attribute in prim.GetAttributes()}, set(prim.attributes))

    def test_settings_product_name_uses_schema_token_and_actual_input(self):
        product = self.stage(self.settings()).GetPrimAtPath('/Render/renderproduct')
        attribute = product.GetAttribute('productName')
        self.assertEqual(attribute.GetName(), 'productName')
        self.assertEqual(attribute.GetTypeName(), 'token')
        self.assertEqual(attribute.Get(1), 'beauty.$F4.exr')

    def test_created_and_force_edited_product_preserve_native_token_properties(self):
        for upstream in ((), (self.settings(),)):
            product = self.stage(self.product(upstream)).GetPrimAtPath('/Render/renderproduct')
            for name, expected in (('productName', 'current/beauty.$F4.exr'), ('productType', 'raster')):
                with self.subTest(upstream=bool(upstream), name=name):
                    attribute = product.GetAttribute(name)
                    self.assertEqual(attribute.GetName(), name)
                    self.assertEqual(attribute.GetTypeName(), 'token')
                    self.assertEqual(attribute.Get(1), expected)

    def test_composed_product_observation_preserves_missing_color_and_alpha(self):
        stage = self.stage(self.product((self.settings(),)))
        fact = collect_render_color_facts(stage, frame=1, settings_path='/Render/settings')
        product = fact['products'][0]
        for name, expected in (('productName', 'current/beauty.$F4.exr'), ('productType', 'raster')):
            self.assertEqual(product['attributes'][name]['value'], expected)
        self.assertFalse(any(gap['code'] == 'ATTRIBUTE_PATH_MISMATCH' for gap in fact['missing_facts']))
        gaps = {gap['code'] for gap in fact['missing_facts']}
        self.assertIn('OCIO_CONFIGURATION_UNRESOLVED', gaps)
        self.assertIn('ALPHA_ASSOCIATION_UNPROVEN', gaps)
        self.assertNotIn('AVAILABLE', str(fact))

    def test_render_var_reads_authored_source_and_type_without_success_defaults(self):
        parameters=dict(createprims='on',primpath='/Render/Vars/beauty',
            sourceName_control='set',sourceName='C',sourceType_control='set',sourceType='raw',
            dataType_control='set',dataType='color3f')
        for version in ('21.0.631','22.0.429'):
            for source_name in ('C','alternate_native_source'):
                parameters['sourceName']=source_name
                prim=self.stage(NodeInput('rendervar',parameters),version).GetPrimAtPath('/Render/Vars/beauty')
                for name,kind,expected in (('sourceName','string',source_name),
                        ('sourceType','token','raw'),('dataType','token','color3f')):
                    with self.subTest(version=version,name=name,source=source_name):
                        attribute=prim.GetAttribute(name)
                        self.assertEqual((attribute.GetName(),attribute.GetTypeName(),attribute.Get(1)),
                            (name,kind,expected))
                self.assertFalse(prim.GetAttribute('driver:parameters:aov:husk:output_colorspace'))
            parameters['sourceName_control']='none'
            prim=self.stage(NodeInput('rendervar',parameters),version).GetPrimAtPath('/Render/Vars/beauty')
            self.assertFalse(prim.GetAttribute('sourceName'))
            parameters['sourceName_control']='set'

    def test_explicit_rendering_color_space_is_preserved_as_configuration_only(self):
        settings=NodeInput('rendersettings',dict(createprims='on',primpath='/Render/settings',
            renderingColorSpace_control='set',renderingColorSpace='explicit-working-space'))
        for version in ('21.0.631','22.0.429'):
            stage=self.stage(settings,version)
            observation=collect_render_color_facts(stage,frame=1,settings_path='/Render/settings')
            attribute=observation['settings']['attributes']['renderingColorSpace']
            self.assertEqual(attribute['value'],'explicit-working-space')
            self.assertIn('OCIO_CONFIGURATION_UNRESOLVED',
                {gap['code'] for gap in observation['missing_facts']})
            self.assertNotIn('AVAILABLE',str(observation))


if __name__ == '__main__':
    unittest.main(verbosity=2)
