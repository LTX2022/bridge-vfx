"""Explicit software boundaries for project selection, never native color proof."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from houdini_bridge import client
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary, ProductionBoundaryError
import test_houdini_output_receipts as receipts

COLOR = {'schema': 'bridge.project-color/1.0', 'project_id': 'example-project',
         'revision': 1, 'colorspace': 'project-linear', 'source': 'human_project_selection'}


class ProjectColorChainTests(unittest.TestCase):
    def setUp(self):
        fixture = receipts.HoudiniOutputReceiptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.record = fixture.record
        self.record['project_color'] = copy.deepcopy(COLOR)
        self.record['request_sha256'] = client.render_receipt_digest({
            'task_id': self.record['task_id'], 'frames': [1], 'budget_seconds': 1.0,
            'scene_sha256': self.record['scene']['snapshot_sha256'],
            'render_target': self.record['render_target'], 'output_pattern': self.record['output_pattern'],
            'dependencies': self.record['dependencies'], 'project_color': COLOR})

    def test_selection_is_frozen_and_does_not_prove_alpha_or_write(self):
        producer = client.render_producer_binding(self.record)
        self.assertEqual(producer['project_color'], COLOR)
        output = client.collect_render_output_fact(self.record, 1)
        self.assertEqual(output['project_color'], COLOR)
        self.assertEqual(output['metadata']['colorspace'], COLOR['colorspace'])
        self.assertEqual(output['metadata']['project_color'], COLOR)
        self.assertNotIn('premultiplied', output['metadata'])
        self.record['output_facts'] = {'1': output}
        fact = client.render_execution_fact(self.record)
        self.assertEqual(fact['project_color'], COLOR)
        gaps = fact['completion_metadata_missing_facts']
        self.assertNotIn('EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED', gaps)
        self.assertNotIn('OCIO_PREFLIGHT_OBSERVATION_REQUIRED', gaps)
        self.assertIn('KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED', gaps)
        self.assertIn('OUTPUT_OVERRIDE_AOV_AND_ORDERED_FILTER_EXECUTION_REQUIRED', gaps)
        self.assertIn('HUSK_POSTFRAME_OBSERVATION_REQUIRED', gaps)
        self.assertEqual(fact['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(fact['metadata'], {})
        for key, value in (('project_id', 'other'), ('revision', 2), ('colorspace', 'other-linear')):
            changed = copy.deepcopy(self.record)
            changed['project_color'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(client.BridgeError, 'changed'):
                client.render_producer_binding(changed)

    def test_legacy_record_requires_selection_not_internal_color_trace(self):
        fixture = receipts.HoudiniOutputReceiptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fact = client.render_execution_fact(fixture.record)
        gaps = fact['completion_metadata_missing_facts']
        self.assertIn('PROJECT_COLOR_SELECTION_REQUIRED', gaps)
        self.assertNotIn('EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED', gaps)
        self.assertNotIn('OCIO_PREFLIGHT_OBSERVATION_REQUIRED', gaps)

    def test_old_signed_receipt_shape_is_not_upgraded(self):
        fixture = receipts.HoudiniOutputReceiptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        record = fixture.record
        # An immutable pre-policy receipt must reproduce its original digest.
        old = client.render_execution_fact(record)
        old['completion_metadata_missing_facts'] = [
            'EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED',
            'OUTPUT_OVERRIDE_AOV_AND_ORDERED_FILTER_EXECUTION_REQUIRED',
            'KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED',
            'OCIO_PREFLIGHT_OBSERVATION_REQUIRED',
            'FRAME_OUTPUT_OBSERVATION_REQUIRED', 'HUSK_POSTFRAME_OBSERVATION_REQUIRED']
        old['operation_receipt_sha256'] = client.render_receipt_digest(old)
        record['execution_fact'] = copy.deepcopy(old)
        self.assertEqual(client.render_execution_fact(record), old)
        self.assertNotIn('project_color', old)
        self.assertEqual(old['metadata'], {})

    def test_controller_injects_selection_and_rejects_caller_override(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        transport = mock.Mock()
        identity = copy.deepcopy(self.record['host_identity'])
        identity['task_id'] = self.record['task_id']
        self.record['host_identity'] = identity
        transport.call.return_value = {'operation_id': self.record['request_id'],
                                      'record': self.record, 'operation_store_path': str(root / 'operations.json')}
        boundary = _ConfiguredBoundary(kind='houdini', transport=transport,
            config={'transport': 'http', 'project_color': COLOR}, state_dir=root)
        boundary.bound_task_id = self.record['task_id']
        boundary._verify_identity = mock.Mock(return_value={'task_host_identity': identity})
        boundary.call('render.start', {'request_id': self.record['request_id']})
        self.assertEqual(transport.call.call_args.args[1]['project_color'], COLOR)
        transport.reset_mock()
        with self.assertRaisesRegex(ProductionBoundaryError, 'PROJECT_COLOR'):
            boundary.call('render.start', {'project_color': dict(COLOR, revision=2)})
        transport.call.assert_not_called()
        boundary.production_config.pop('project_color')
        with self.assertRaisesRegex(ProductionBoundaryError, 'PROJECT_COLOR_SELECTION_REQUIRED'):
            boundary.call('render.start', {})
        transport.call.assert_not_called()

    def test_host_cannot_return_another_selection(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        transport = mock.Mock()
        identity = dict(self.record['host_identity'], task_id=self.record['task_id'])
        self.record['host_identity'] = identity
        transport.call.return_value = {'operation_id': self.record['request_id'],
                                      'record': self.record}
        boundary = _ConfiguredBoundary(kind='houdini', transport=transport,
            config={'transport': 'http', 'project_color': dict(COLOR, revision=2)}, state_dir=root)
        boundary.bound_task_id = self.record['task_id']
        boundary._verify_identity = mock.Mock(return_value={'task_host_identity': identity})
        with self.assertRaisesRegex(ProductionBoundaryError, 'PROJECT_COLOR'):
            boundary.call('render.start', {})


if __name__ == '__main__':
    unittest.main()
