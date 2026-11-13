import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys

from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_task_templates import load, bind, collector_policy


class GeometryTaskTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.criteria={'schema':'bridge.table-geometry-test-criteria/1',
                       'initial':{'width':1.2,'depth':.7,'height':.75,'top_thickness':.06,
                                  'leg_width':.08,'leg_depth':.08,'inset_x':.08,'inset_z':.08},
                       'relative_tolerance':.02,'absolute_tolerance':.002,
                       'feedback':{'width_ratio':1.2,'ratio_absolute_tolerance':.005,'preserve_absolute_tolerance':.002}}
        criteria=self.root/'criteria.json';criteria.write_text(json.dumps(self.criteria))
        image=self.root/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\nEXPLICIT_TRANSPORT_FIXTURE')
        self.template={'schema':'bridge.geometry-task-template/1','profile':'table_geometry_v1',
                       'public_brief':'A bounded table exercise with independently editable components.',
                       'feedback':'Widen the table by the declared ratio while preserving supports.',
                       'criteria':file_record(criteria),
                       'media':{k:file_record(image) for k in ('reference_front','reference_perspective')},
                       'viewing_exposure_stops':7.25}
        self.path=self.root/'template.json'

    def record(self):
        self.path.write_text(json.dumps(self.template))
        return file_record(self.path)

    def test_optional_template_preserves_legacy_path(self):
        self.assertIsNone(load(None))
        self.assertIsNone(collector_policy({},None))

    def test_explicit_historical_collector_is_preserved(self):
        original={'process_image_policy':{'policy':'legacy_vmmap_summary_v1','tools':{}}}
        selected=collector_policy(original,self.template)
        self.assertEqual(selected,original['process_image_policy'])
        self.assertIsNot(selected,original['process_image_policy'])

    @unittest.skipUnless(sys.platform=='darwin','macOS collector binaries')
    def test_new_table_scope_pins_existing_sample_header_tools(self):
        selected=collector_policy({},self.template)
        self.assertEqual(selected['policy'],'sample_header_v1')
        self.assertEqual(set(selected['tools']),{'sample','vmmap'})
        for name,record in selected['tools'].items():
            self.assertEqual(record,file_record(Path('/usr/bin')/name))

    def test_media_or_criteria_tampering_invalidates_the_registered_template(self):
        for field in ('criteria','media'):
            with self.subTest(field=field):
                record=self.record()
                source=self.template['criteria'] if field=='criteria' else self.template['media']['reference_front']
                path=Path(source['path']);original=path.read_bytes()
                path.write_bytes(original+b' ')
                try:
                    with self.assertRaises(ValueError):load(record)
                finally:path.write_bytes(original)

    def test_unknown_profiles_fields_and_nonfinite_exposure_are_rejected(self):
        original=copy.deepcopy(self.template)
        for change in ('profile','extra','exposure'):
            self.template=copy.deepcopy(original)
            if change=='profile':self.template['profile']='arbitrary_model_v1'
            elif change=='extra':self.template['worker']='/untrusted/worker'
            else:self.template['viewing_exposure_stops']=float('nan')
            with self.subTest(change=change),self.assertRaises(ValueError):load(self.record())

    def test_duplicate_json_keys_are_rejected(self):
        self.record();raw=self.path.read_text()
        self.path.write_text(raw[:-1]+',"profile":"table_geometry_v1"}')
        with self.assertRaisesRegex(ValueError,'DUPLICATE_KEY'):load(file_record(self.path))

    def test_linked_reference_is_rejected_even_when_bytes_match(self):
        item=self.template['media']['reference_front'];link=self.root/'linked.png'
        link.symlink_to(item['path']);item['path']=str(link)
        with self.assertRaisesRegex(ValueError,'PATH_INVALID'):load(self.record())

    def test_binding_is_explicit_without_changing_source_display_or_exposing_targets(self):
        record=self.record();template=load(record)
        original={'criteria':{'sha256':'a'*64},'display':{'exposure_stops':2.25,'sha256':'old','policy':{'source':'ACEScg'}}}
        frozen=copy.deepcopy(original)
        bound=bind(original,template,record,self.root,'Explicit user instruction for this table learning task.')
        self.assertEqual(original,frozen)
        self.assertEqual(bound['task_template'],record)
        self.assertFalse(bound['goal_contract']['goal_text_changes_criteria'])
        self.assertEqual(bound['display']['exposure_stops'],7.25)
        self.assertNotEqual(bound['display']['sha256'],'old')
        self.assertNotIn('width',json.dumps(bound['goal_contract']))
        self.assertEqual(bound['model_route']['selected_model'],'unknown')
