"""Software file/owned-process fixtures only; no native rendering claims."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('houdini-bridge', 'dcc-task-runtime'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
from houdini_bridge import controlled_output as controlled, client
from dcc_task_runtime.exr_codec import write_exr
from dcc_task_runtime import alpha_calibration, owned_process
import test_alpha_calibration as alpha_fixtures
from dcc_task_runtime.exr_codec import encode_tiny_exr
import test_houdini_output_receipts as receipt_fixtures


class ControlledOutputTests(unittest.TestCase):
    def test_output_color_route_is_bound_and_required_for_real_acceptance(self):
        route = self.readback()
        old = controlled.controlled_route_sha256(route)
        with self.assertRaisesRegex(ValueError, 'COLOR_ROUTE_REQUIRED'):
            controlled.controlled_route_sha256(route, require_color_route=True)
        current = dict(route, output_color_route={'source': 'scene_linear', 'output': 'ACEScg'})
        self.assertNotEqual(old, controlled.controlled_route_sha256(current, require_color_route=True))
        self.assertEqual(old, controlled.controlled_route_sha256(route))
        for invalid in ({'source': 'lin_rec709', 'output': 'ACEScg'},
                        {'source': 'scene_linear', 'output': 'lin_rec709'}, {}, None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'COLOR_ROUTE_INVALID'):
                controlled.controlled_route_sha256(dict(route, output_color_route=invalid))

    def test_native_color_header_must_support_project_selection(self):
        for token in ('ACEScg', 'ACES - ACEScg', 'lin_ap1'):
            controlled._validate_exr_color({'color_metadata': {'oiio:ColorSpace': token}}, 'ACEScg')
        ap1 = [0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767]
        controlled._validate_exr_color({'color_metadata': {'chromaticities': ap1}}, 'ACEScg')
        for metadata in ({'oiio:ColorSpace': 'lin_rec709'},
                         {'oiio:ColorSpace': 'ACEScg', 'chromaticities': [0.0] * 8},
                         {'oiio:ColorSpace': 'lin_rec709', 'chromaticities': ap1}):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, 'CONFLICT'):
                controlled._validate_exr_color({'color_metadata': metadata}, 'ACEScg')
        with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
            controlled._validate_exr_color({}, 'ACEScg')
        controlled._validate_exr_color({}, 'ACEScg', evidence_source='software_test')

    def test_policy_has_no_implicit_defaults_or_additional_fields(self):
        policy = copy.deepcopy(controlled._POLICY)
        self.assertEqual(controlled.validate_controlled_policy(policy), policy)
        for invalid in (None, {}, dict(policy, extra=True), dict(policy, frames=[True]),
                        dict(policy, resolution=[256, 128]), dict(policy, channels=['R', 'G', 'B'])):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                controlled.validate_controlled_policy(invalid)
        detached = controlled.validate_controlled_policy(policy)
        detached['frames'].append(2)
        self.assertEqual(policy['frames'], [1])

    def test_route_requires_all_observed_fields_and_ignores_scene_paths(self):
        route = {'resolution': [128, 128], 'denoiser': 'off', 'motion_blur': False,
                 'image_filters': [], 'renderer': 'BRAY_HdKarma', 'colorspace': 'ACEScg', 'aov_semantics': 'karma_beauty_lpe_v1', 'products': [{'kind': 'beauty', 'channels': ['R', 'G', 'B', 'A'], 'multipart': False}]}
        digest = controlled.controlled_route_sha256(route)
        self.assertEqual(digest, controlled.controlled_route_sha256(dict(route, usd_sha256='x', path='/other')))
        self.assertNotEqual(digest, controlled.controlled_route_sha256(dict(route, motion_blur=True)))
        for key in route:
            incomplete = dict(route); incomplete.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                controlled.controlled_route_sha256(incomplete)

    def test_full_pixel_decode_rejects_nonfinite_samples_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'sample.exr'
            def snapshot(payload):
                path.write_bytes(payload)
                info = path.stat()
                return {'path': str(path), 'bytes': info.st_size, 'modified_ns': info.st_mtime_ns,
                        'sha256': hashlib.sha256(payload).hexdigest()}
            original = snapshot(encode_tiny_exr())
            decoded = controlled._decode_snapshot(original)
            self.assertTrue(decoded['structural_validated'])
            self.assertNotIn('rows', decoded)
            nonfinite = snapshot(encode_tiny_exr(float('nan')))
            with self.assertRaisesRegex(ValueError, 'NONFINITE'):
                controlled._decode_snapshot(nonfinite)
            path.write_bytes(encode_tiny_exr(2.0))
            with self.assertRaises(Exception):
                controlled._decode_snapshot(original)

    def test_real_signed_python_producer_is_not_upgraded_without_frozen_opt_in(self):
        fixture = receipt_fixtures.HoudiniOutputReceiptTests()
        with mock.patch.object(tempfile, 'tempdir', '/private/tmp'):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.persist_contract_fixture()
        before = fixture.anchor_path.read_bytes()
        original = copy.deepcopy(fixture.record['execution_fact'])
        with self.assertRaisesRegex(ValueError, 'FROZEN_POLICY_REQUIRED'):
            controlled.verify_controlled_output(fixture.binding, task_id='fixture-owner',
                operation_id='fixture-operation', verification_id='verify-one',
                policy=copy.deepcopy(controlled._POLICY), alpha_calibration={'associated': True})
        self.assertEqual(fixture.anchor_path.read_bytes(), before)
        self.assertEqual(fixture.read()['execution_fact'], original)
        self.assertEqual(original['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')

    def test_explicit_saved_configuration_rejects_missing_flags(self):
        readback = self.readback()
        producer = {'project_color': {'colorspace': 'ACEScg'}, 'render_config': {'1': {'controlled_output_readback': readback,
                    'exr_format': {'storage': 'scanline', 'multipart': 0}}}}
        self.assertEqual(controlled._configuration(producer, controlled._POLICY), readback)
        for key in ('denoiser', 'motion_blur', 'image_filters', 'products', 'resolution'):
            invalid = copy.deepcopy(producer)
            invalid['render_config']['1']['controlled_output_readback'].pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                controlled._configuration(invalid, controlled._POLICY)
        invalid = copy.deepcopy(producer)
        invalid['render_config']['1']['controlled_output_readback']['motion_blur'] = 0
        with self.assertRaises(ValueError): controlled._configuration(invalid, controlled._POLICY)

    @staticmethod
    def readback():
        return {'scene_variant': 'sphere_ground_v2', 'resolution': [128, 128],
                'denoiser': 'off', 'motion_blur': False, 'image_filters': [], 'renderer': 'BRAY_HdKarma', 'colorspace': 'ACEScg', 'aov_semantics': 'karma_beauty_lpe_v1',
                'products': [{'kind': 'beauty', 'channels': ['R', 'G', 'B', 'A'], 'multipart': False}],
                'houdini_version': '21.0.631', 'plugin_build': 'fixture-build'}

    def prepared_fixture(self):
        fixture = receipt_fixtures.HoudiniOutputReceiptTests()
        with mock.patch.object(tempfile, 'tempdir', '/private/tmp'):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        channels = sorted('RGBA')
        image = {'width': 128, 'height': 128, 'channels': channels, 'compression': 0,
                 'pixel_count': 128 * 128, 'sample_count': 128 * 128 * 4, 'structural_validated': True,
                 'channel_layout': {'channels': [{'name': name, 'pixel_type': 2, 'p_linear': 0,
                     'x_sampling': 1, 'y_sampling': 1} for name in channels],
                     'data_window': [0, 0, 127, 127], 'display_window': [0, 0, 127, 127]}}
        additive = {'A': 0., 'R': .125, 'G': .0625, 'B': .25}
        rows = [{'y': y, 'channels': {name: [additive[name]] * 128 for name in channels}} for y in range(128)]
        write_exr(fixture.path, image, rows)
        fixture.record['frame_snapshots']['1'] = fixture.snapshot()
        fixture.record['output_acceptance'] = copy.deepcopy(controlled._POLICY)
        fixture.record['project_color'] = {'schema': 'bridge.project-color/1.0', 'project_id': 'software-fixture',
            'revision': 1, 'colorspace': 'ACEScg', 'source': 'human_project_selection'}
        fixture.record['render_config']['1'].update(controlled_output_readback=self.readback(),
            exr_format={'storage': 'scanline', 'multipart': 0, 'compression': 'none'})
        record = fixture.record
        record['scene_fingerprint'] = client.render_receipt_digest({
            'scene': record['scene']['snapshot_sha256'], 'config': record['render_config']})
        record['request_sha256'] = client.render_receipt_digest({
            'task_id': record['task_id'], 'frames': record['frames'], 'budget_seconds': record['budget_seconds'],
            'scene_sha256': record['scene']['snapshot_sha256'], 'render_target': record['render_target'],
            'output_pattern': record['output_pattern'], 'dependencies': record['dependencies'],
            'project_color': record['project_color'], 'output_acceptance': record['output_acceptance']})
        fixture.persist_contract_fixture()
        return fixture

    def test_authenticated_software_success_is_detached_and_revalidates_sources(self):
        fixture = self.prepared_fixture()
        authority, terminal = alpha_fixtures.signed_fixture(fixture.root / 'alpha')
        terminal['route_sha256'] = controlled.controlled_route_sha256(self.readback())
        owned_process._signed_write(Path(authority['directory']), terminal)
        authority['terminal_sha256'] = alpha_calibration._sha(terminal)
        original_anchor = fixture.anchor_path.read_bytes()
        original_exr = fixture.path.read_bytes()
        options = dict(task_id='fixture-owner', operation_id='fixture-operation', verification_id='verify-one',
            policy=copy.deepcopy(controlled._POLICY), alpha_calibration=authority, evidence_source='software_test')
        with self.assertRaises(ValueError):
            controlled.verify_controlled_output(fixture.binding, **dict(options, alpha_calibration={'associated': True, 'status': 'PASS'}))
        with self.assertRaises(ValueError):
            controlled.verify_controlled_output(fixture.binding, **dict(options, evidence_source='real_host'))
        fact = controlled.verify_controlled_output(fixture.binding, **options)
        self.assertEqual(fact['completion_metadata_status'], 'AVAILABLE')
        self.assertEqual(fact['verification_basis'], 'controlled_output_v1')
        self.assertEqual(fact['evidence_source'], 'software_test')
        self.assertEqual(fact['native_internal_status'], 'NOT_OBSERVED')
        self.assertTrue(fact['metadata']['1']['premultiplied'])
        self.assertNotIn('rows', fact['metadata']['1'])
        self.assertEqual(fact['operation_receipt_sha256'], client.render_receipt_digest(fact))
        self.assertEqual(fixture.anchor_path.read_bytes(), original_anchor)
        self.assertEqual(fixture.path.read_bytes(), original_exr)
        self.assertEqual(fixture.read()['execution_fact']['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(controlled.verify_controlled_output(fixture.binding, **options), fact)
        Path(terminal['sources']['houdini_raw']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
            controlled.verify_controlled_output(fixture.binding, **options)
        supervisor = fixture.binding['supervisor_binding']
        stopped = owned_process.read_receipt(supervisor['directory'], 'stopped', identity=supervisor['identity'])
        stopped.update(descendant_result_unobserved=True, execution_result='unknown', supervisor_exit_code=2)
        owned_process._signed_write(Path(supervisor['directory']), stopped)
        with self.assertRaisesRegex(ValueError, 'SUCCESSFUL_TREE_STOP_REQUIRED'):
            controlled.verify_controlled_output(fixture.binding, **options)

    def test_verification_identity_cannot_replace_parent(self):
        with self.assertRaisesRegex(ValueError, 'VERIFICATION_ID_INVALID'):
            controlled.verify_controlled_output({}, task_id='t', operation_id='parent', verification_id='parent',
                policy=copy.deepcopy(controlled._POLICY), alpha_calibration=None)


if __name__ == '__main__':
    unittest.main()
