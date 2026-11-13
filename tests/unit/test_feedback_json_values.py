from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vfx_pipeline.feedback_versions import FeedbackVersions
from vfx_pipeline.workbuddy_project import DiagnosticRun


class NativeParameterBoundary:
    """Explicit node API boundary for feedback persistence unit checks."""

    def __init__(self, *, native_tuples=False, corruption=None):
        self.values = {'color': (0.8, 0.8, 0.8), 'artist_unrelated': 9}
        self.native_tuples = native_tuples
        self.corruption = corruption
        self.writes = 0
        self.calls = 0

    def call(self, command, params):
        self.calls += 1
        if command == 'node.parms':
            values = dict(self.values)
            if self.writes and self.corruption:
                values.update(self.corruption)
            return {'parms': values if self.native_tuples else json.loads(json.dumps(values))}
        if command != 'node.set_parms':
            raise AssertionError('unexpected native API command: ' + command)
        self.writes += 1
        self.values.update(params['parms'])
        return {'path': params['path'], 'values': dict(params['parms'])}


class FeedbackJsonValueTests(unittest.TestCase):
    @contextmanager
    def fixture(self, **boundary_options):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'run.json'
            manifest.write_text(json.dumps({'schema': 'bridge.workbuddy.diagnostic_run/1.0',
                'run_id': 'test', 'assets': []}), encoding='utf-8')
            run = DiagnosticRun(manifest)
            run.pipeline_task_id = 'task'
            run.artifact_registry = None
            compiled = {'graph_hash': 'a' * 64,
                'nodes': [{'node_id': 'material', 'parameters': {'color': [0.8, 0.8, 0.8]}}],
                'connections': [], 'outputs': [{'node_id': 'material', 'output_id': 'image'}]}
            versions = FeedbackVersions(run)
            versions.register_completed('graph', compiled)
            yield versions, run, compiled, NativeParameterBoundary(**boundary_options)

    def apply_color(self, versions, compiled, client, color=(0.72, 0.72, 0.72)):
        return versions.apply('graph', compiled, '/obj/material', 'material', {'color': color}, client)

    def test_tuple_writer_and_json_readback_commit_once(self):
        with self.fixture() as (versions, run, compiled, client):
            result = self.apply_color(versions, compiled, client)
            self.assertEqual(result['state'], 'COMPLETE')
            self.assertEqual(result['version'], 1)
            self.assertEqual(result['after'], {'color': [0.72, 0.72, 0.72], 'artist_unrelated': 9})
            self.assertEqual(result['compiled']['nodes'][0]['parameters']['color'], [0.72, 0.72, 0.72])
            replayed = self.apply_color(FeedbackVersions(run), compiled, client)
            self.assertTrue(replayed['replayed'])
            self.assertEqual(replayed['version'], 1)
            self.assertEqual(client.writes, 1)

    def test_unrelated_change_and_wrong_color_still_require_reconciliation(self):
        for corruption in ({'artist_unrelated': 0}, {'color': [0.72, 0.72]}, {'color': [0.72, 0.72, 0.73]}):
            with self.subTest(corruption=corruption), self.fixture(corruption=corruption) as (versions, run, compiled, client):
                with self.assertRaisesRegex(ValueError, 'readback mismatch'):
                    self.apply_color(versions, compiled, client)
                self.assertEqual(versions.current('graph')['state'], 'DISPATCHED')
                with self.assertRaisesRegex(ValueError, 'no edit replay'):
                    self.apply_color(FeedbackVersions(run), compiled, client)
                self.assertEqual(client.writes, 1)

    def test_nonfinite_or_nonjson_write_is_rejected_before_host_call(self):
        for invalid in (float('nan'), float('inf'), -float('inf'), {0.72}):
            with self.subTest(invalid=invalid), self.fixture() as (versions, run, compiled, client):
                with self.assertRaises((ValueError, TypeError)):
                    self.apply_color(versions, compiled, client, (invalid, 0.72, 0.72))
                self.assertEqual(client.calls, 0)
                self.assertEqual(client.writes, 0)
                self.assertEqual(versions.current('graph')['version'], 0)

    def test_nonfinite_native_readback_never_commits(self):
        for after_dispatch in (False, True):
            with self.subTest(after_dispatch=after_dispatch), self.fixture(
                corruption={'color': [float('nan'), 0.72, 0.72]} if after_dispatch else None
            ) as (versions, run, compiled, client):
                if not after_dispatch:
                    client.values['color'] = (float('inf'), 0.8, 0.8)
                with self.assertRaises(ValueError):
                    self.apply_color(versions, compiled, client)
                current = versions.current('graph')
                self.assertEqual(current['state'], 'DISPATCHED' if after_dispatch else 'COMPLETE')
                self.assertEqual(current['version'], 1 if after_dispatch else 0)
                self.assertEqual(client.writes, 1 if after_dispatch else 0)

    def test_native_tuple_readback_recovers_dispatched_without_replay(self):
        with self.fixture(native_tuples=True) as (versions, run, compiled, client):
            with patch.object(versions, '_complete', side_effect=OSError('interrupted feedback commit')):
                with self.assertRaisesRegex(OSError, 'interrupted feedback commit'):
                    self.apply_color(versions, compiled, client)
            self.assertEqual(versions.current('graph')['state'], 'DISPATCHED')
            result = self.apply_color(FeedbackVersions(run), compiled, client)
            self.assertEqual(result['state'], 'COMPLETE')
            self.assertEqual(result['version'], 1)
            self.assertTrue(result['replayed'])
            self.assertEqual(client.writes, 1)

    def test_native_tuple_readback_recovers_prepared_intent(self):
        with self.fixture(native_tuples=True) as (versions, run, compiled, client):
            with patch.object(versions, '_execute', side_effect=OSError('interrupted before dispatch')):
                with self.assertRaisesRegex(OSError, 'interrupted before dispatch'):
                    self.apply_color(versions, compiled, client)
            self.assertEqual(client.writes, 0)
            self.assertEqual(versions.current('graph')['state'], 'PREPARED')
            result = self.apply_color(FeedbackVersions(run), compiled, client)
            self.assertEqual(result['state'], 'COMPLETE')
            self.assertEqual(result['version'], 1)
            self.assertTrue(result['replayed'])
            self.assertEqual(client.writes, 1)
