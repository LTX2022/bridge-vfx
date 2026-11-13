"""FAKE type-interface diagnostics only: these are NOT solver-adapter tests."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / 'tools/probe_pyro_sourcing_templates.py'
SPEC = importlib.util.spec_from_file_location('synthetic_pyro_capture', PATH)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class SyntheticTemplate:
    """Intentionally synthetic names; never represent a real Houdini binding."""
    def __init__(self, dynamic=False): self.dynamic = dynamic
    def name(self): return 'FAKE_operation#'
    def label(self): return 'FAKE operation'
    def type(self): return 'FAKE_Menu'
    def numComponents(self): return 1
    def itemGeneratorScript(self): return 'PRIVATE_GENERATOR_DO_NOT_EMIT' if self.dynamic else ''
    def menuItems(self):
        if self.dynamic: raise AssertionError('dynamic menu must not be inspected or executed')
        return ('FAKE_add', 'FAKE_copy')
    def menuLabels(self): return ('FAKE Add', 'FAKE Copy')


class SyntheticFolder:
    def __init__(self, children): self.children = children
    def name(self): return 'FAKE_sources'
    def label(self): return 'FAKE Sources'
    def type(self): return 'FAKE_Folder'
    def numComponents(self): return 1
    def parmTemplates(self): return self.children
    def folderType(self): return 'FAKE_MultiparmBlock'


class SyntheticRamp:
    """Synthetic Ramp shape: child templates are valid, folderType is absent."""
    def __init__(self, children=None):
        self.children = children if children is not None else [SyntheticTemplate()]
    def name(self): return 'FAKE_ramp'
    def label(self): return 'FAKE Ramp'
    def type(self): return 'parmTemplateType.Ramp'
    def numComponents(self): return 1
    def parmTemplates(self): return self.children


class SyntheticOtherWithChildren:
    """Unknown synthetic type with children: must be diagnosed, not treated as Folder."""
    def __init__(self, children=None):
        self.children = children if children is not None else [SyntheticTemplate()]
    def name(self): return 'FAKE_other'
    def label(self): return 'FAKE Other'
    def type(self): return 'FAKE_Other'
    def numComponents(self): return 1
    def parmTemplates(self): return self.children


class SyntheticHost:
    def __init__(self, templates=None, missing=False):
        self.templates = templates if templates is not None else [SyntheticFolder([SyntheticTemplate()])]
        self.missing = missing
        self.lookups = []
        self.parmTemplateType = SimpleNamespace(
            Folder='FAKE_Folder', Ramp='parmTemplateType.Ramp')
    def applicationVersion(self): return (0, 0, 0)  # FAKE, never a native build claim
    def sopNodeTypeCategory(self): return 'FAKE_Sop_category'
    def nodeType(self, category, name):
        self.lookups.append((category, name))
        if self.missing or name != 'pyrosolver': return None
        return SimpleNamespace(name=lambda:name, category=lambda:SimpleNamespace(name=lambda:'Sop'),
            minNumInputs=lambda:1,maxNumInputs=lambda:2,
            parmTemplateGroup=lambda:SimpleNamespace(entries=lambda:self.templates))
    def __getattr__(self, name):
        raise AssertionError('forbidden scene/geometry/write API: '+name)


def _attribute_error(*_args, **_kwargs):
    raise AttributeError('suppressed test failure')


def _host_with_attribute_failure(interface):
    folder = SyntheticFolder([SyntheticTemplate()])
    template_entries = [folder] if interface in {
        'hou.FolderParmTemplate.folderType',
        'hou.FolderParmTemplate.parmTemplates',
    } else [SyntheticTemplate()]
    host = SyntheticHost(template_entries)

    if interface == 'hou.applicationVersion':
        host.applicationVersion = _attribute_error
        return host
    if interface == 'hou.sopNodeTypeCategory':
        host.sopNodeTypeCategory = _attribute_error
        return host
    if interface == 'hou.nodeType':
        host.nodeType = _attribute_error
        return host

    category = host.sopNodeTypeCategory()
    native = host.nodeType(category, 'pyrosolver')
    native_category = native.category()
    native.category = lambda: native_category
    group = native.parmTemplateGroup()
    native.parmTemplateGroup = lambda: group
    template = template_entries[0]
    if isinstance(template, SyntheticFolder):
        template = template.children[0]

    def route(_category, name):
        return native if name == 'pyrosolver' else None

    host.nodeType = route
    if interface == 'hou.NodeType.category':
        native.category = _attribute_error
    elif interface == 'hou.NodeTypeCategory.name':
        native_category.name = _attribute_error
    elif interface == 'hou.NodeType.name':
        native.name = _attribute_error
    elif interface == 'hou.NodeType.minNumInputs':
        native.minNumInputs = _attribute_error
    elif interface == 'hou.NodeType.maxNumInputs':
        native.maxNumInputs = _attribute_error
    elif interface == 'hou.NodeType.parmTemplateGroup':
        native.parmTemplateGroup = _attribute_error
    elif interface == 'hou.ParmTemplateGroup.entries':
        group.entries = _attribute_error
    elif interface == 'hou.ParmTemplate.name':
        template.name = _attribute_error
    elif interface == 'hou.ParmTemplate.label':
        template.label = _attribute_error
    elif interface == 'hou.ParmTemplate.type':
        template.type = _attribute_error
    elif interface == 'hou.ParmTemplate.numComponents':
        template.numComponents = _attribute_error
    elif interface == 'hou.FolderParmTemplate.folderType':
        template_entry = template_entries[0]
        template_entry.folderType = _attribute_error
    elif interface == 'hou.FolderParmTemplate.parmTemplates':
        template_entry = template_entries[0]
        template_entry.parmTemplates = _attribute_error
    elif interface == 'hou.MenuParmTemplate.itemGeneratorScript':
        template.itemGeneratorScript = _attribute_error
    elif interface == 'hou.MenuParmTemplate.menuItems':
        template.menuItems = _attribute_error
    elif interface == 'hou.MenuParmTemplate.menuLabels':
        template.menuLabels = _attribute_error
    else:
        raise AssertionError('unhandled failure interface: ' + interface)
    return host


ATTRIBUTE_FAILURE_CASES = (
    ('hou.applicationVersion', 'host.version'),
    ('hou.sopNodeTypeCategory', 'host.sop_category'),
    ('hou.nodeType', 'node.lookup'),
    ('hou.NodeType.category', 'node.category'),
    ('hou.NodeTypeCategory.name', 'node.category_name'),
    ('hou.NodeType.name', 'node.name'),
    ('hou.NodeType.minNumInputs', 'node.min_inputs'),
    ('hou.NodeType.maxNumInputs', 'node.max_inputs'),
    ('hou.NodeType.parmTemplateGroup', 'node.parm_template_group'),
    ('hou.ParmTemplateGroup.entries', 'node.parm_template_entries'),
    ('hou.ParmTemplate.name', 'template.name'),
    ('hou.ParmTemplate.label', 'template.label'),
    ('hou.ParmTemplate.type', 'template.type'),
    ('hou.ParmTemplate.numComponents', 'template.components'),
    ('hou.FolderParmTemplate.parmTemplates', 'template.children'),
    ('hou.MenuParmTemplate.itemGeneratorScript', 'template.item_generator_script'),
    ('hou.MenuParmTemplate.menuItems', 'template.menu_items'),
    ('hou.MenuParmTemplate.menuLabels', 'template.menu_labels'),
)


class SourcingTemplateCaptureTests(unittest.TestCase):
    def test_public_capture_preserves_observed_names_multiparm_and_menu_without_scene_access(self):
        host = SyntheticHost()
        result = PROBE.capture(host, synthetic=True)
        self.assertEqual(result['capture_state'], 'CAPTURED_NOT_BOUND')
        self.assertEqual(result['evidence_kind'], 'FAKE_HOM_SOFTWARE_ONLY')
        self.assertEqual(host.lookups, [('FAKE_Sop_category', name) for name in PROBE.NODE_TYPES])
        template = result['nodes'][0]['templates'][0]['children'][0]
        self.assertEqual(template['name'], 'FAKE_operation#')
        self.assertEqual(template['template_path'], ['FAKE_sources', 'FAKE_operation#'])
        self.assertEqual(template['menu_items'], ['FAKE_add','FAKE_copy'])
        self.assertEqual(result['nodes'][0]['min_inputs'], 1)
        self.assertEqual(result['nodes'][0]['max_inputs'], 2)
        self.assertEqual(result['registered_bindings'], [])
        self.assertEqual(result['failure_details'], [])
        self.assertEqual(result['warnings'], [])
        for key in ('runtime_verified','visual_verified','route_verified','provider_verified',
                    'dcc_acceptance_unlocked','solver_sourcing_implemented'):
            self.assertFalse(result[key])

    def test_each_hom_attribute_error_reports_stable_stage_and_interface(self):
        for interface, stage in ATTRIBUTE_FAILURE_CASES:
            with self.subTest(interface=interface):
                result = PROBE.capture(
                    _host_with_attribute_failure(interface), synthetic=True)
                self.assertEqual(result['capture_state'], 'INCOMPLETE')
                self.assertTrue(any(
                    detail['stage'] == stage
                    and detail['interface'] == interface
                    and detail['exception_type'] == 'AttributeError'
                    for detail in result['failure_details']))
                self.assertTrue(any(
                    error.startswith(
                        'TYPE_CAPTURE_FAILED:stage={}:interface={}:exception=AttributeError'.format(
                            stage, interface))
                    for error in result['errors']))
                encoded = json.dumps(result, ensure_ascii=False)
                self.assertNotIn('suppressed test failure', encoded)
                self.assertFalse(result['solver_sourcing_implemented'])
                self.assertFalse(result['dcc_acceptance_unlocked'])

    def test_folder_type_attribute_error_is_optional_and_keeps_node_metadata(self):
        result = PROBE.capture(
            _host_with_attribute_failure('hou.FolderParmTemplate.folderType'),
            synthetic=True)
        self.assertEqual(result['capture_state'], 'INCOMPLETE')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['failure_details'], [])
        self.assertEqual(len(result['warnings']), 1)
        warning = result['warnings'][0]
        self.assertEqual(warning['kind'], 'OPTIONAL_METADATA_UNAVAILABLE')
        self.assertEqual(warning['stage'], 'template.folder_type')
        self.assertEqual(warning['interface'], 'hou.FolderParmTemplate.folderType')
        self.assertEqual(warning['exception_type'], 'AttributeError')
        node = result['nodes'][0]
        self.assertTrue(node['available'])
        self.assertIn('children', node['templates'][0])
        self.assertNotIn('folder_type', node['templates'][0])
        self.assertFalse(result['solver_sourcing_implemented'])
        self.assertFalse(result['dcc_acceptance_unlocked'])

    def test_ramp_type_keeps_children_without_folder_type(self):
        result = PROBE.capture(
            SyntheticHost([SyntheticRamp()]), synthetic=True)
        self.assertEqual(result['capture_state'], 'CAPTURED_NOT_BOUND')
        self.assertEqual(result['warnings'], [])
        ramp = result['nodes'][0]['templates'][0]
        self.assertEqual(ramp['type'], 'parmTemplateType.Ramp')
        self.assertIn('children', ramp)
        self.assertNotIn('folder_type', ramp)
        self.assertEqual(ramp['children'][0]['name'], 'FAKE_operation#')
        self.assertFalse(result['solver_sourcing_implemented'])

    def test_unknown_nonfolder_children_are_preserved_with_specific_diagnostic(self):
        result = PROBE.capture(
            SyntheticHost([SyntheticOtherWithChildren()]), synthetic=True)
        self.assertEqual(result['capture_state'], 'INCOMPLETE')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['failure_details'], [])
        self.assertEqual(len(result['warnings']), 1)
        warning = result['warnings'][0]
        self.assertEqual(warning['kind'], 'UNKNOWN_CHILD_TEMPLATE_OWNER')
        self.assertEqual(warning['stage'], 'template.type_dispatch')
        self.assertEqual(warning['interface'], 'capture.template_type_dispatch')
        self.assertEqual(warning['exception_type'], 'ValueError')
        self.assertEqual(warning['observed_type'], 'FAKE_Other')
        other = result['nodes'][0]['templates'][0]
        self.assertEqual(other['type'], 'FAKE_Other')
        self.assertIn('children', other)
        self.assertNotIn('folder_type', other)
        self.assertFalse(result['solver_sourcing_implemented'])

    def test_dynamic_menu_body_and_items_are_not_emitted_or_executed(self):
        result = PROBE.capture(SyntheticHost([SyntheticTemplate(dynamic=True)]), synthetic=True)
        template = result['nodes'][0]['templates'][0]
        self.assertTrue(template['dynamic_menu'])
        self.assertNotIn('menu_items', template)
        self.assertNotIn('PRIVATE_GENERATOR', json.dumps(result))
        self.assertEqual(result['registered_bindings'], [])

    def test_missing_type_and_exception_do_not_become_capability_or_execution_proof(self):
        missing = PROBE.capture(SyntheticHost(missing=True), synthetic=True)
        self.assertEqual(missing['capture_state'], 'INCOMPLETE')
        self.assertEqual(missing['errors'], ['NO_REGISTERED_SOLVER_TYPE'])
        host = SyntheticHost()
        host.nodeType = lambda *args: (_ for _ in ()).throw(RuntimeError('/PRIVATE/SECRET_FILE'))
        failed = PROBE.capture(host, synthetic=True)
        self.assertEqual(failed['capture_state'], 'INCOMPLETE')
        self.assertNotIn('SECRET_FILE', json.dumps(failed))
        self.assertEqual(failed['failure_details'][0]['exception_type'], 'RuntimeError')
        self.assertFalse(failed['solver_sourcing_implemented'])

    def test_template_bounds_and_malformed_menu_fail_closed(self):
        with patch.object(PROBE, 'MAX_TEMPLATES', 1):
            result = PROBE.capture(SyntheticHost(), synthetic=True)
        self.assertEqual(result['capture_state'], 'INCOMPLETE')
        template = SyntheticTemplate()
        template.menuLabels = lambda: ('only-one-label',)
        result = PROBE.capture(SyntheticHost([template]), synthetic=True)
        self.assertEqual(result['capture_state'], 'INCOMPLETE')
        self.assertTrue(result['errors'])
        self.assertFalse(result['dcc_acceptance_unlocked'])

    def test_cli_requires_explicit_confirmation_before_importing_hou(self):
        with patch.object(PROBE.importlib, 'import_module', side_effect=AssertionError('must not import')) as load:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(PROBE.main([]), 2)
            load.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['capture_state'], 'NOT_RUN')

    def test_cli_captures_types_without_starting_host_and_missing_hou_is_not_pass(self):
        with patch.object(PROBE.importlib, 'import_module', return_value=SyntheticHost()) as load:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(PROBE.main(['--confirm-read-only-type-capture']), 0)
        load.assert_called_once_with('hou')
        self.assertEqual(json.loads(out.getvalue())['capture_state'], 'CAPTURED_NOT_BOUND')
        with patch.object(PROBE.importlib, 'import_module', side_effect=ImportError('missing')):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(PROBE.main(['--confirm-read-only-type-capture']), 2)
        self.assertEqual(json.loads(out.getvalue())['reason'], 'HOU_UNAVAILABLE')
