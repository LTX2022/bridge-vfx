import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dcc_task_runtime import alpha_calibration as calibration, owned_process


def signed_fixture(root, associated=True):
    """Own signed Python fixture; it is explicitly not native host evidence."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity = {'task_id': 'alpha-software', 'launch_nonce': 'fixture-only'}
    (root / 'receipt.key').write_bytes(b'software-fixture-key-not-production')
    start = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': identity,
             'pid': 31, 'execution_protocol': 1, 'argv_sha256': 'fixture'}
    owned_process._signed_write(root, start)
    stop = {'schema': owned_process.SCHEMA, 'event': 'stopped', 'identity': identity,
            'pid': 31, 'execution_protocol': 1, 'exit_code': 0, 'supervisor_exit_code': 0,
            'execution_result': 'succeeded', 'descendant_result_unobserved': False,
            'stop_reason': None, 'observed_by': 'owned_child_wait',
            'started_sha256': calibration._sha(start)}
    owned_process._signed_write(root, stop)
    samples = [{'alpha': a, 'rgb': [v * (a if associated else 1.) for v in calibration.EMISSION]}
               for a in calibration.OPACITIES]
    composites = [{'over_black': [v * a for v in calibration.EMISSION],
                   'over_white': [v * a + 1. - a for v in calibration.EMISSION]}
                  for a in calibration.OPACITIES]
    additive = [.125, .0625, .25]
    values = {'houdini_raw': {'schema': 'bridge.alpha-fixture-samples/1', 'samples': samples},
              'nuke_composite': {'schema': 'bridge.alpha-composite-samples/1', 'samples': composites,
                                'additive': {'alpha': 0, 'input_rgb': additive, 'over_black': additive,
                                             'over_white': [v + 1. for v in additive]}}}
    sources = {}
    for name, value in values.items():
        path = root / (name + '.json')
        raw = owned_process._canonical(value)
        path.write_bytes(raw)
        sources[name] = {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    terminal = {'schema': owned_process.SCHEMA, 'event': 'alpha-calibration', 'identity': identity,
                'started_sha256': calibration._sha(start), 'stopped_sha256': calibration._sha(stop),
                'version': '21.0.631', 'plugin_build': 'fixture-build', 'route_sha256': 'a' * 64,
                'evidence_source': 'software_test', 'sources': sources,
                'verifier_sha256': hashlib.sha256(Path(calibration.__file__).read_bytes()).hexdigest()}
    owned_process._signed_write(root, terminal)
    return {'directory': str(root), 'identity': identity, 'terminal_sha256': calibration._sha(terminal)}, terminal


class AlphaCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.binding, self.terminal = signed_fixture(Path(self.temp.name) / 'alpha')
        self.options = dict(expected_version='21.0.631', expected_plugin_build='fixture-build',
                            expected_route_sha256='a' * 64, evidence_source='software_test')

    def validate(self):
        return calibration.validate_alpha_calibration(self.binding, **self.options)

    def resign(self):
        owned_process._signed_write(Path(self.binding['directory']), self.terminal)
        self.binding['terminal_sha256'] = calibration._sha(self.terminal)

    def test_signed_associated_and_straight_preserve_additive(self):
        self.assertIs(self.validate()['associated'], True)
        self.binding, self.terminal = signed_fixture(Path(self.temp.name) / 'straight', associated=False)
        self.assertIs(self.validate()['associated'], False)

    def test_plain_pass_and_changed_source_are_rejected(self):
        with self.assertRaises(ValueError):
            calibration.validate_alpha_calibration({'associated': True, 'status': 'PASS'}, **self.options)
        Path(self.terminal['sources']['houdini_raw']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
            self.validate()

    def test_unsigned_terminal_and_wrong_route_rejected(self):
        self.options['expected_route_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'BINDING_MISMATCH'):
            self.validate()
        self.options['expected_route_sha256'] = 'a' * 64
        path = Path(self.binding['directory']) / 'alpha-calibration.json'
        envelope = json.loads(path.read_text())
        envelope['payload']['plugin_build'] = 'forged'
        path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, 'RECEIPT_MISMATCH'):
            self.validate()

    def test_signed_numeric_claim_cannot_enter_native_lane(self):
        self.terminal['evidence_source'] = self.options['evidence_source'] = 'real_host'
        self.resign()
        with self.assertRaisesRegex(ValueError, 'NATIVE_CALIBRATION_PRODUCER_REQUIRED'):
            self.validate()

    def test_fractional_probe_and_additive_are_mandatory(self):
        for kind in ('fractional', 'additive'):
            with self.subTest(kind=kind):
                self.binding, self.terminal = signed_fixture(Path(self.temp.name) / kind)
                key = 'houdini_raw' if kind == 'fractional' else 'nuke_composite'
                record = self.terminal['sources'][key]
                path = Path(record['path'])
                value = json.loads(path.read_text())
                if kind == 'fractional': value['samples'][1]['alpha'] = 1.
                else: value['additive']['over_black'] = [0., 0., 0.]
                raw = owned_process._canonical(value)
                path.write_bytes(raw)
                record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                self.resign()
                with self.assertRaises(ValueError): self.validate()

    def test_standalone_cli_help_starts_without_native_module(self):
        import subprocess
        import sys
        # Isolated Python ignores PYTHONPATH and has no native Nuke module.
        # Executing the actual file exercises __package__ == None bootstrap.
        result = subprocess.run([sys.executable, '-I', str(Path(calibration.__file__).resolve()), '--help'],
            cwd=self.temp.name, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--observe-native', result.stdout)
        self.assertIn('--project-colorspace', result.stdout)
        self.assertNotIn('ModuleNotFoundError', result.stderr)

    def test_native_observer_rejects_wrong_version_before_creating_output(self):
        from types import SimpleNamespace
        target = Path(self.temp.name) / 'must-not-exist'
        with self.assertRaisesRegex(ValueError, 'NUKE_VERSION_MISMATCH'):
            calibration.observe_native_nuke(SimpleNamespace(NUKE_VERSION_STRING='wrong'),
                chart_path='not-read.exr', output_root=target, project_colorspace='ACEScg')
        self.assertFalse(target.exists())

    def test_native_process_binding_requires_trusted_full_identity_and_ignores_diagnostic_claims(self):
        """Offline receipt validation only; these observations are explicit fixtures."""
        import copy
        import sys
        from dcc_task_runtime import process_image
        executable = Path(sys.executable).resolve()
        expected = process_image.freeze_executable(str(executable), '21.0.631',
            hashlib.sha256(executable.read_bytes()).hexdigest())
        command = [str(executable), '-B', '-c', 'pass']
        identity = {'task_id': 'signed-unit-only', 'operation_id': 'alpha-h21', 'launch_nonce': 'one'}
        anchor = {'schema': process_image.OBSERVATION_SCHEMA, 'platform': 'darwin', 'pid': 31,
            'parent_pid': 1, 'birth': '2026-10-23 10:00:00.123 +0000',
            'load_address': '0x100000000', 'image': copy.deepcopy(expected['image'])}
        start = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': identity,
            'pid': 31, 'argv_sha256': calibration._sha(command),
            'writer_process_binding': {'expected_executable': expected, 'host_anchor': anchor}}
        def stopped(value):
            return {'schema': owned_process.SCHEMA, 'event': 'stopped', 'identity': identity,
                'pid': 31, 'execution_protocol': 1, 'started_sha256': calibration._sha(value),
                'exit_code': 0, 'supervisor_exit_code': 0, 'execution_result': 'succeeded',
                'descendant_result_unobserved': False, 'stop_reason': None}
        options = dict(expected_executable=expected, identity=identity, command=command)
        self.assertEqual(calibration.validate_native_process_binding(start, stopped(start), **options),
            start['writer_process_binding'])
        for failure in ('missing', 'error', 'stopped-error', 'empty', 'bad-expected', 'wrong-version', 'wrong-pid',
                        'wrong-image', 'wrong-argv', 'wrong-identity', 'wrong-stop', 'nonzero'):
            with self.subTest(failure=failure):
                invalid = copy.deepcopy(start)
                if failure == 'missing':
                    invalid.pop('writer_process_binding')
                    invalid['writer_process_binding_diagnostic'] = {'verified': True, 'status': 'PASS'}
                elif failure in ('error', 'stopped-error'):
                    invalid.pop('writer_process_binding')
                    invalid['writer_process_binding_error'] = 'ProcessImageError:PROCESS_IMAGE_TOOL_FAILED'
                elif failure == 'empty': invalid['writer_process_binding'] = {}
                elif failure == 'bad-expected': invalid['writer_process_binding']['expected_executable'] = {}
                elif failure == 'wrong-version': invalid['writer_process_binding']['expected_executable']['version'] = 'other'
                elif failure == 'wrong-pid': invalid['writer_process_binding']['host_anchor']['pid'] = 32
                elif failure == 'wrong-image': invalid['writer_process_binding']['host_anchor']['image']['sha256'] = '0' * 64
                elif failure == 'wrong-argv': invalid['argv_sha256'] = '0' * 64
                elif failure == 'wrong-identity': invalid['identity']['launch_nonce'] = 'other'
                stop = stopped(invalid)
                if failure == 'wrong-stop': stop['started_sha256'] = '0' * 64
                elif failure == 'nonzero': stop.update(exit_code=7, execution_result='failed')
                elif failure == 'stopped-error':
                    stop.update(exit_code=-15, stop_reason='SUPERVISOR_WRITER_COLLECTION_FAILED', execution_result='failed')
                with self.assertRaises(ValueError) as error:
                    calibration.validate_native_process_binding(invalid, stop, **options)
                if failure in ('error', 'stopped-error'):
                    self.assertIn('PROCESS_IMAGE_TOOL_FAILED', str(error.exception))
                    self.assertNotIn('INVALID_STRUCTURE', str(error.exception))

    def test_final_native_authority_preserves_original_missing_writer_cause(self):
        directory = Path(self.binding['directory'])
        identity = self.binding['identity']
        start = owned_process.read_receipt(directory, 'started', identity=identity)
        start['writer_process_binding_error'] = 'ProcessImageError:PROCESS_IMAGE_TOOL_FAILED'
        start['writer_process_binding_diagnostic'] = {'status': 'PASS', 'verified': True}
        stop = owned_process.read_receipt(directory, 'stopped', identity=identity)
        stop['started_sha256'] = calibration._sha(start)
        owned_process._signed_write(directory, start)
        owned_process._signed_write(directory, stop)
        owned_process._signed_write(directory, {'schema': owned_process.SCHEMA,
            'event': 'alpha-output', 'identity': identity})
        operation = {'directory': str(directory), 'identity': identity, 'output_sha256': '0' * 64}
        terminal = {'native_operations': {'houdini': operation, 'nuke': operation}}
        with self.assertRaisesRegex(ValueError, 'ALPHA_NATIVE_WRITER_BINDING_REQUIRED:ProcessImageError:PROCESS_IMAGE_TOOL_FAILED'):
            calibration._validate_native_authority(terminal, {}, {}, {}, '21.0.631')

    def test_material_recipe_uses_exact_capture_fields(self):
        self.assertEqual(calibration.calibration_material_recipe(.5)['opacity'], (.5, .5, .5))
        self.assertEqual(calibration.calibration_material_recipe(.5)['emission_color'], (.8, .8, .8))
        with self.assertRaises(ValueError): calibration.calibration_material_recipe(.3)


if __name__ == '__main__': unittest.main()
