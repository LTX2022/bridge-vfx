"""Exact cache confirmation resources are part of the authorized content hash."""
import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from cache_resource_fixture import CACHE_ROOT, cache_output_path
from dcc_task_runtime.errors import RuntimeV2Error
from vfx_pipeline.service import TrustedApprovalControl, ModelSafePipeline, PipelineExecutionError
from test_approval_v2 import cache_subject, task_spec


class CacheResourceContractTests(unittest.TestCase):
    def test_subject_rejects_missing_budget_and_unbound_frames_path_version(self):
        subject = cache_subject('task')
        with self.assertRaises(RuntimeV2Error):
            replace(subject, metadata={})
        for key, value in [('estimated_bytes', 0), ('max_disk_bytes', 1),
                           ('max_seconds', 121), ('output_path', cache_output_path('wrong')),
                           ('content_version', 'another'), ('frame_range', [2, 48, 1]),
                           ('invalidation_scope', []), ('task_roots', [str(CACHE_ROOT.parent / 'other')])]:
            meta = copy.deepcopy(subject.metadata)
            meta['resource_contract'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeV2Error):
                replace(subject, metadata=meta)

        for output in ('smoke.vdb', '/cache/smoke.vdb', 'C:cache/smoke.vdb',
                       str(CACHE_ROOT / '..' / 'outside.vdb'),
                       str(CACHE_ROOT.with_name(CACHE_ROOT.name + '-other') / 'smoke.vdb')):
            meta = copy.deepcopy(subject.metadata)
            meta['resource_contract']['output_path'] = output
            with self.subTest(output=output), self.assertRaises(RuntimeV2Error):
                replace(subject, output_path=output, metadata=meta)

        for roots in ([], ['relative/cache'], ['/cache']):
            meta = copy.deepcopy(subject.metadata)
            meta['resource_contract']['task_roots'] = roots
            with self.subTest(roots=roots), self.assertRaises(RuntimeV2Error):
                replace(subject, metadata=meta)

    def test_scope_budget_change_changes_subject_digest(self):
        subject = cache_subject('task')
        meta = copy.deepcopy(subject.metadata)
        meta['resource_contract']['estimated_bytes'] = 2048
        self.assertNotEqual(subject.subject_hash, replace(subject, metadata=meta).subject_hash)

    def test_trusted_policy_is_persistent_and_changed_policy_revokes_execution(self):
        from dcc_task_runtime.canonical import canonical_sha256
        with tempfile.TemporaryDirectory() as temporary:
            pipeline = ModelSafePipeline(Path(temporary) / 'state.sqlite3')
            task_id = pipeline.store.create_task(task_spec())
            control = TrustedApprovalControl(pipeline)
            policy = control.configure_cache_resources(task_id, task_roots=[str(CACHE_ROOT)],
                estimated_bytes=1024, max_disk_bytes=4096, max_seconds=120, simulation_start_frame=1,
                invalidation_scope=['smoke.simulation', 'render'])
            subject = cache_subject(task_id)
            subject = replace(subject, metadata={**subject.metadata, 'resource_policy_hash': canonical_sha256(policy)})
            restarted = ModelSafePipeline(pipeline.database)
            restarted._assert_cache_resource_policy(task_id, subject)
            control.configure_cache_resources(task_id, task_roots=[str(CACHE_ROOT)],
                estimated_bytes=2048, max_disk_bytes=4096, max_seconds=120, simulation_start_frame=1,
                invalidation_scope=['smoke.simulation', 'render'])
            with self.assertRaisesRegex(PipelineExecutionError, 'policy changed'):
                restarted._assert_cache_resource_policy(task_id, subject)
