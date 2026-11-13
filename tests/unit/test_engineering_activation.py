"""Trusted-controller activation simulation; fake host images are never run."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
import test_engineering_preparation as preparation_tests
from dcc_task_runtime import owned_process
from dcc_task_runtime.native_scope import NativeScope
import activate_controlled_engineering as activation
import prepare_controlled_engineering as preparation


class EngineeringActivationTests(unittest.TestCase):
    setUp = preparation_tests.EngineeringPreparationTests.setUp
    prepare = preparation_tests.EngineeringPreparationTests.prepare

    def targets(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def review(self, result, target):
        return activation.review_activation(self.scope_path, result['bindings']['path'], target,
            expected_scope_sha256=self.binding['sha256'],
            expected_bindings_sha256=result['bindings']['sha256'])['review']

    def test_successor_review_and_software_activation_preserve_source_and_old_scope(self):
        with mock.patch.object(preparation.subprocess, 'run', wraps=preparation.subprocess.run) as pure_tools:
            result = self.prepare()
        self.assertEqual([call.kwargs['timeout'] for call in pure_tools.call_args_list], [90, 90, 90])
        targets = self.targets()
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('DCC forbidden')) as launch:
            successor = activation.prepare_successor(self.scope_path, result['bindings']['path'], targets / 'candidate',
                expected_scope_sha256=self.binding['sha256'],
                expected_bindings_sha256=result['bindings']['sha256'])
            candidate = NativeScope(successor['scope'])
            self.assertFalse(candidate.scope['execution_authorized'])
            self.assertNotEqual(candidate.key_path.read_bytes(), self.native.key_path.read_bytes())
            self.assertEqual(candidate.scope['budget'], self.native.scope['budget'])
            snapshot = candidate.root / 'project/control/snapshot'
            command = [candidate.scope['hosts']['supervisor_python']['path'], '-I',
                str(snapshot / 'tools/activate_controlled_engineering.py'), 'review',
                '--scope', str(candidate.path), '--bindings', successor['bindings']['path'],
                '--output-root', str(targets / 'authorized'),
                '--expected-scope-sha256', candidate.binding['sha256'],
                '--expected-bindings-sha256', successor['bindings']['sha256']]
            reviewed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            self.assertFalse(list(snapshot.rglob('*.pyc')))
            review = json.loads(reviewed.stdout)['review']
            with mock.patch.object(preparation, '_python', wraps=preparation._python) as whole_prepare:
                activated = activation.activate_software_test(review['path'], expected_review_sha256=review['sha256'])
            whole_prepare.assert_called_once()
            self.assertEqual(whole_prepare.call_args.kwargs['timeout_seconds'], 360)
        launch.assert_not_called()
        live = NativeScope(activated['scope'])
        self.assertTrue(live.scope['execution_authorized'])
        self.assertNotEqual(live.key_path.read_bytes(), candidate.key_path.read_bytes())
        self.assertNotEqual(live.key_path.read_bytes(), self.native.key_path.read_bytes())
        self.assertNotEqual(live.scope['scope_id'], candidate.scope['scope_id'])
        self.assertEqual(live.scope['evidence_source'], 'software_test')
        self.assertEqual(live.scope['budget'], self.native.scope['budget'])
        self.assertEqual(activation.validate_activation(live, activated['bindings']['path']), activated)
        snapshot = live.root / 'project/control/snapshot'
        command = [live.scope['hosts']['supervisor_python']['path'], '-I',
            str(snapshot / 'tools/run_controlled_engineering.py'), '--scope', str(live.path),
            '--bindings', activated['bindings']['path']]
        preflight = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertEqual(json.loads(preflight.stdout)['state'], 'PREPARED')
        self.assertFalse(list(snapshot.rglob('*.pyc')))
        self.assertEqual(activation.validate_activation(live, activated['bindings']['path']), activated)
        prepared = json.loads((live.root / 'engineering-preparation.json').read_text())
        self.assertEqual(prepared['driver_preflight']['state'], 'PREPARED')
        self.assertEqual(prepared['preflight']['scope_sha256'], live.binding['sha256'])
        self.assertEqual(prepared['driver_preflight']['bindings_sha256'], activated['bindings']['sha256'])
        bindings = json.loads(Path(activated['bindings']['path']).read_text())
        for record in bindings['deployments'].values():
            deployment = json.loads(Path(record['path']).read_text())
            self.assertEqual(deployment['native_scope'], live.binding)
            self.assertEqual(deployment['resource_budget']['roots'], [str(live.root)])
        entry = live.root / 'project/control/snapshot/tools/run_controlled_engineering.py'
        spec = importlib.util.spec_from_file_location('activation_frozen_driver', entry)
        frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
        with self.assertRaisesRegex(ValueError, 'EXPLICIT_REAL_HOST_AUTHORIZATION_REQUIRED'):
            frozen.execute(live.path, activated['bindings']['path'],
                approved_scope_sha256=live.binding['sha256'],
                approved_bindings_sha256=activated['bindings']['sha256'])
        bindings_path = Path(activated['bindings']['path'])
        original_bindings = bindings_path.read_bytes()
        bindings_path.write_bytes(original_bindings + b'\n')
        with self.assertRaisesRegex(ValueError, 'RECEIPT_MISMATCH'):
            activation.validate_activation(live, bindings_path)
        bindings_path.write_bytes(original_bindings)
        receipt_path = live.root / 'engineering-activation.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['payload']['authorization'] = 'explicit_local_terminal_controller'
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'SIGNATURE_INVALID'):
            activation.validate_activation(live, bindings_path)
        self.assertEqual(self.scope_path.read_bytes(), self.scope_bytes)
        self.assertEqual(self.native.state_path.read_bytes(), self.state_bytes)
        self.assertFalse(candidate.scope['execution_authorized'])
        self.assertEqual([self.native.snapshot()['dcc_starts'], candidate.snapshot()['dcc_starts'],
                          live.snapshot()['dcc_starts']], [0, 0, 0])
        with self.assertRaisesRegex(ValueError, 'FRESH_ROOT_REQUIRED'):
            activation.activate_software_test(review['path'], expected_review_sha256=review['sha256'])

    def test_wrong_hash_source_drift_used_scope_and_budget_expansion_refused(self):
        result = self.prepare()
        target = self.targets() / 'authorized'
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            activation.review_activation(self.scope_path, result['bindings']['path'], target,
                expected_scope_sha256='0' * 64, expected_bindings_sha256=result['bindings']['sha256'])
        review = self.review(result, target)
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            activation.activate_software_test(review['path'], expected_review_sha256='0' * 64)
        source = Path(result['snapshot_root']) / 'tools/run_alpha_calibration.py'
        original = source.read_bytes()
        source.write_bytes(original + b'\n# source drift\n')
        with self.assertRaisesRegex(ValueError, 'FROZEN_FILE_CHANGED'):
            activation.activate_software_test(review['path'], expected_review_sha256=review['sha256'])
        source.write_bytes(original)
        used = dict(self.native.snapshot(), dcc_starts=1, tickets=[{'explicit': 'software'}])
        with mock.patch.object(NativeScope, 'snapshot', return_value=used):
            with self.assertRaisesRegex(ValueError, 'ALREADY_USED'):
                activation.activate_software_test(review['path'], expected_review_sha256=review['sha256'])
        changed = json.loads(self.scope_bytes)
        changed['budget']['max_dcc_starts'] = 9
        self.scope_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'BUDGET_INVALID'):
            activation.review_activation(self.scope_path, result['bindings']['path'], target,
                expected_scope_sha256=preparation.file_record(self.scope_path)['sha256'],
                expected_bindings_sha256=result['bindings']['sha256'])
        self.scope_path.write_bytes(self.scope_bytes)
        self.assertFalse(target.exists())
        self.assertEqual(self.native.state_path.read_bytes(), self.state_bytes)
        with mock.patch.object(sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'INTERACTIVE_TERMINAL_REQUIRED'):
                activation.activate_local_terminal(review['path'], expected_review_sha256=review['sha256'])

    def test_legacy_omitted_source_is_real_host_for_pure_review_only(self):
        # A source-less legacy scope has always meant real_host. Fake native
        # image fixtures still remain inert: this case only prepares and reviews.
        targets = self.targets()
        import hashlib
        import secrets
        source = dict(self.native.scope)
        source.pop('evidence_source')
        source['native_color_tokens'] = dict(source['native_color_tokens'],
            nuke='NATIVE_MENU_READBACK_REQUIRED', runtime_readback_required=True)
        key = secrets.token_bytes(32)
        root = targets / 'legacy'; root.mkdir()
        source.update(output_root=str(root), accounting={'key_path': str(root / '.native-control/key'),
            'key_sha256': hashlib.sha256(key).hexdigest()})
        record = preparation._write(root / 'scope.json', source)
        native = NativeScope.initialize({key: record[key] for key in ('path', 'sha256')}, key=key)
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('DCC forbidden')) as launch:
            prepared = preparation.prepare(native.path)
            review = activation.review_activation(native.path, prepared['bindings']['path'], targets / 'future',
                expected_scope_sha256=native.binding['sha256'],
                expected_bindings_sha256=prepared['bindings']['sha256'])['review']
            value = json.loads(Path(review['path']).read_text())
            self.assertEqual(value['evidence_source'], 'real_host')
            with self.assertRaisesRegex(ValueError, 'SOFTWARE_TEST_ONLY'):
                activation.activate_software_test(review['path'], expected_review_sha256=review['sha256'])
        launch.assert_not_called()
        self.assertFalse((targets / 'future').exists())
        self.assertNotIn('evidence_source', json.loads(native.path.read_text()))
        self.assertEqual(native.snapshot()['dcc_starts'], 0)


if __name__ == '__main__':
    unittest.main()
