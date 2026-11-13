import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dcc_task_runtime.contracts import TaskSpecV2
from vfx_pipeline.service import ModelSafePipeline, PipelineExecutionError
from test_vfx_pipeline import raw_spec, fake_router


class ExternalAnalysisIngressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        ref = root / 'synthetic.png'
        ref.write_bytes(b'synthetic fixture bytes')
        self.spec = raw_spec('pyro_smoke_v1', 'detail', references=[{
            'asset_id': 'ref', 'kind': 'image', 'uri': str(ref),
            'sha256': hashlib.sha256(ref.read_bytes()).hexdigest(),
        }])
        self.pipeline = ModelSafePipeline(root / 'state.sqlite3', router=fake_router())
        self.task = self.pipeline.task_start(self.spec)['task_id']
        self.run = {'run_id': 'registered', 'route_id': 'WorkBuddyDesktopRoute', 'selected_model': 'HY3'}
        self.pipeline.store.put_record(self.task, 'external_model_run', 'registered', self.run)
        self.analysis = {'components': [], 'global_observations': {'motion': 'outward'}, 'confidence': 0.8}

    def submit(self, **kw):
        return self.pipeline.reference_analysis_submit(self.task, kw.pop('analysis', self.analysis), run_id=kw.pop('run_id', 'registered'), request_id=kw.pop('request_id', 'turn1'))

    def test_persists_without_dispatch_and_survives_restart(self):
        with patch.object(self.pipeline, '_run_initial_previews', side_effect=AssertionError('dispatch forbidden')):
            result = self.submit()
        self.assertFalse(result['dcc_dispatched'])
        restarted = ModelSafePipeline(self.pipeline.store.path, router=fake_router())
        replay = restarted.reference_analysis_submit(self.task, self.analysis, run_id='registered', request_id='turn1')
        self.assertTrue(replay['replayed'])
        self.assertEqual(result['analysis_hash'], replay['analysis_hash'])
        bound = restarted._spec_with_analysis(self.task, TaskSpecV2.from_mapping(self.spec))
        self.assertEqual(bound.metadata['reference_analysis'], self.analysis)
        self.assertIn('visual_objective', bound.metadata)
        self.assertFalse(bound.metadata['source_plan']['ready'])

    def test_motion_observations_reach_distinct_source_controls(self):
        base = {'components': [{'component_id': 'smoke', 'label': 'smoke', 'roi': [0, 0, 1, 1],
            'confidence': 0.9, 'observations': {'emission_start': 1, 'emission_end': 60,
            'direction': [0, 1, 0], 'spread_angle': 30, 'speed_tier': 'fast',
            'body_scale': 1, 'ground_spread': 2, 'protected_features': ['outline']}}],
            'global_observations': {'time_range': {'start': 1, 'end': 180, 'step': 1}}, 'confidence': 0.9}
        self.submit(analysis=base)
        first = self.pipeline.store.records(self.task, 'reference_analysis')[-1]['source_plan']
        base['components'][0]['observations']['spread_angle'] = 70
        self.submit(analysis=base, request_id='turn2')
        second = self.pipeline.store.records(self.task, 'reference_analysis')[-1]['source_plan']
        self.assertTrue(first['ready'])
        self.assertNotEqual(first, second)

    def test_reused_request_different_content_rejected(self):
        self.submit()
        with self.assertRaises(PipelineExecutionError):
            self.submit(analysis={**self.analysis, 'confidence': 0.3})
        self.assertEqual(len(self.pipeline.store.records(self.task, 'reference_analysis')), 1)

    def test_unverified_external_observation_cannot_dispatch(self):
        self.submit()
        with patch.object(self.pipeline, '_run_subtask', side_effect=AssertionError('DCC dispatch forbidden')):
            with self.assertRaises(PipelineExecutionError) as cm:
                self.pipeline._run_initial_previews(self.task, TaskSpecV2.from_mapping(self.spec), {'domains': []})
        self.assertIn('trusted session', str(cm.exception))

    def test_model_cannot_invent_route_or_verification(self):
        with self.assertRaises(PipelineExecutionError):
            self.submit(run_id='invented')
        with self.assertRaises(Exception):
            self.submit(analysis={**self.analysis, 'verified': True})
        self.assertFalse(self.pipeline.store.records(self.task, 'reference_analysis'))

    def test_changed_reference_rejected(self):
        Path(self.spec['references'][0]['uri']).write_bytes(b'changed')
        with self.assertRaises(Exception):
            self.submit()
        self.assertFalse(self.pipeline.store.records(self.task, 'reference_analysis'))

    def test_same_route_guard_runs_before_constructing_gateway(self):
        with self.assertRaises(PipelineExecutionError) as cm:
            self.pipeline.model_probe({'planner': {'provider': 'doubao-desktop'}, 'vision': {'provider': 'api'}}, self.task)
        self.assertIn('same registered', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
