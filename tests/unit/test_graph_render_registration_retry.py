"""Registration recovery with real SQLite/EXR and an explicit status transport fixture."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

from dcc_task_runtime.artifact_registry import ArtifactError
from vfx_pipeline.feedback_versions import FeedbackVersions
from vfx_pipeline.workbuddy_graph_mcp import GraphRun
import test_registry_controller_source as source_fixture
import test_registry_operation_receipts as registry_fixture


class FileFactTransport:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []

    def call(self, command, arguments):
        self.calls.append((command, dict(arguments)))
        if command != 'render.status' or arguments['task_id'] != self.fixture.fact['task_id']:
            raise AssertionError('only explicit file producer status reads are permitted')
        return {'execution_fact': self.fixture.operation_source(arguments['operation_id'])}


class GraphRenderRegistrationRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = registry_fixture.RegistryOperationReceiptTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        control = self.fixture.root / 'control'
        control.mkdir()
        source_run, host_fact, _, _ = source_fixture.RegistryControllerSourceTests().source(control)
        self.manifest = control / 'run.json'
        self.manifest.write_text(json.dumps({'schema': 'bridge.workbuddy.diagnostic_run/1.0',
            'run_id': 'file-retry-fixture', 'assets': [], 'construction_authorized': True}), encoding='utf-8')
        source_run.controller_source['manifest_sha256'] = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.source = source_run.controller_source
        self.fixture.fact.update(host_fact)
        self.transport = FileFactTransport(self.fixture)
        self.facade = self.reopen()
        feedback = FeedbackVersions(self.facade)
        with self.facade._connect() as database:
            database.execute('INSERT INTO feedback_versions VALUES (?, ?, ?, ?)',
                ('fixture-graph', 1, 'COMPLETE', json.dumps({'compiled': {'outputs': []}})))
        self.fixture.fact['dependencies'] = feedback.dependencies()
        self.fixture.replace_fact(self.fixture.fact)
        sources = self.facade._registry_receipt_sources(self.fixture.fact)
        self.entry = self.fixture.register(dependencies=self.fixture.fact['dependencies'], receipt_source_files=sources)
        self.history = self.fixture.registry.history('fixture-output')

    def reopen(self):
        facade = GraphRun(self.manifest, None, task_id=self.fixture.fact['task_id'],
            host_client=self.transport, artifact_registry=self.fixture.registry)
        facade.controller_source = dict(self.source)
        facade._register_operation('fixture-operation', 'houdini-render', 'houdini', 'fixture-operation')
        return facade

    def retry(self, facade=None, **changes):
        arguments = dict(artifact_id='fixture-output', artifact_class='preview_temp',
            pattern=self.fixture.pattern, frame_set=[1, 2], colorspace='scene_linear',
            premultiplied=False, operation_id='fixture-operation')
        arguments.update(changes)
        return (facade or self.facade).register_render_artifact(**arguments)

    def assert_preserved(self):
        self.assertEqual(self.fixture.registry.history('fixture-output'), self.history)
        self.assertTrue(all(command == 'render.status' for command, _ in self.transport.calls))

    def test_same_request_after_controller_restart_reuses_exact_version(self):
        result = self.retry(self.reopen(), frame_set=[2, 1])
        self.assertEqual(result, self.entry)
        self.assert_preserved()

    def test_foreign_registered_artifact_is_rejected_before_nuke_mutation(self):
        facade=self.reopen()
        facade.pipeline_task_id='different-owner'
        facade.save_root=str(self.fixture.root/'nuke-output')
        facade.manifest.update(execution_authorized=True,render_authorized=True)
        nuke=mock.Mock()
        nuke.render_binding.side_effect=AssertionError('foreign artifact reached Nuke mutation')
        facade.nuke_client=nuke
        with self.assertRaisesRegex(ValueError,'NUKE_INPUT_ARTIFACT_OWNER_MISMATCH'):
            facade.nuke_render_bounded('foreign-input',str(Path(facade.save_root)/'out.%03d.exr'),[1],artifact_id='fixture-output')
        nuke.render_binding.assert_not_called()
        nuke.call.assert_not_called()
        self.assert_preserved()

    def test_changed_class_color_or_alpha_cannot_reuse_previous_registration(self):
        for changes in ({'artifact_class': 'confirmed_cache'}, {'artifact_class': 'final_delivery'},
                        {'colorspace': 'other-space'}, {'premultiplied': True}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, 'registration request differs'):
                    self.retry(**changes)
        self.assert_preserved()

    def test_non_boolean_alpha_cannot_be_coerced_on_registration_retry(self):
        for value in (None, 0, 1, 'false'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'explicit color space and boolean alpha'):
                    self.retry(premultiplied=value)
        self.assert_preserved()

    def test_missing_controller_source_cannot_reuse_typed_registration(self):
        del self.facade.controller_source
        with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
            self.retry()
        self.assert_preserved()

    def test_wrong_configured_snapshot_cannot_reuse_previous_registration(self):
        self.facade.controller_source['repo_root'] = str(self.fixture.root / 'unrelated-snapshot')
        with self.assertRaisesRegex(ValueError, 'not controller-owned'):
            self.retry()
        self.assert_preserved()

    def test_changed_output_is_still_refused_after_controller_restart(self):
        path = Path(self.fixture.fact['frame_snapshots']['1']['path'])
        path.write_bytes(b'changed file input')
        with self.assertRaises(ArtifactError):
            self.retry(self.reopen())
        self.assertEqual(len(self.fixture.registry.history('fixture-output')), 1)

    def test_real_ledger_failure_retries_registration_without_a_new_producing_operation(self):
        artifact_id = 'new-file-output'
        with sqlite3.connect(self.fixture.registry.path) as locked:
            locked.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError) as caught:
                self.retry(artifact_id=artifact_id)
            self.assertIn('locked', str(caught.exception))
            locked.rollback()
        self.assertEqual(self.fixture.registry.history(artifact_id), [])
        registered = self.retry(artifact_id=artifact_id)
        repeated = self.retry(self.reopen(), artifact_id=artifact_id)
        self.assertEqual(repeated, registered)
        self.assertEqual(len(self.fixture.registry.history(artifact_id)), 1)
        self.assertEqual(registered['operation_id'], 'fixture-operation')
        self.assertTrue(all(command == 'render.status' for command, _ in self.transport.calls))
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main(verbosity=2)
