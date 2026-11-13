"""Owned job-file transport with bounded byte and original-intent checks."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from vfx_pipeline.graph_job_worker import _parse_job, _parse_job_file
from vfx_pipeline.graph_job_evidence import MAX_JSON_BYTES
import test_graph_job_frozen_inputs as fixtures


class JobFileTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FrozenConstructionInputTests('test_missing_manifest_backward_compatible_persistence')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def captured_transport(self, *, large):
        manifest = copy.deepcopy(self.fixture.manifest)
        if large:
            manifest[0]['explicit_transport_padding'] = ['x' * 8000 for index in range(5)]
        service = self.fixture.service(manifest)
        service.worker_factory = None
        commands = []

        def transport(argv, **kwargs):
            commands.append(argv)
            raise OSError('explicit no-launch transport boundary')

        service.subprocess_factory = transport
        service._uses_default_subprocess = False
        _, operation = self.fixture.prepare(service)
        self.fixture.launch(service, operation)
        self.assertEqual(len(commands), 1)
        return commands[0], manifest

    def test_large_supported_metadata_uses_short_owned_file_and_preserves_inputs(self):
        command, manifest = self.captured_transport(large=True)
        self.assertNotIn('--job', command)
        self.assertIn('--job-file', command)
        units = len(subprocess.list2cmdline(command).encode('utf-16-le')) // 2 + 1
        self.assertLessEqual(units, 32767)
        path = command[command.index('--job-file') + 1]
        digest = command[command.index('--job-file-sha256') + 1]
        job = _parse_job_file(path, digest)
        self.assertEqual(job['frozen_input_manifest'], manifest)
        self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)
        legacy = [command[0], command[1], '--job', json.dumps(job, ensure_ascii=False)]
        self.assertGreater(len(subprocess.list2cmdline(legacy).encode('utf-16-le')) // 2 + 1, 32767)

    def test_small_jobs_keep_legacy_inline_json_transport(self):
        command, manifest = self.captured_transport(large=False)
        self.assertNotIn('--job-file', command)
        self.assertEqual(_parse_job(command[command.index('--job') + 1])['frozen_input_manifest'], manifest)

    def test_job_file_changed_after_launch_configuration_is_refused(self):
        command, manifest = self.captured_transport(large=True)
        path = Path(command[command.index('--job-file') + 1])
        digest = command[command.index('--job-file-sha256') + 1]
        job = _parse_job_file(str(path), digest)
        job['frozen_input_manifest'][0]['asset_id'] = 'tampered'
        path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(ValueError):
            _parse_job_file(str(path), digest)

    def test_matching_bytes_in_a_foreign_file_do_not_confer_attempt_ownership(self):
        command, manifest = self.captured_transport(large=True)
        path = Path(command[command.index('--job-file') + 1])
        digest = command[command.index('--job-file-sha256') + 1]
        foreign = path.parent.parent / 'worker-job.json'
        shutil.copyfile(path, foreign)
        with self.assertRaises(ValueError):
            _parse_job_file(str(foreign), digest)

    def test_oversize_job_file_is_rejected_before_opening_its_contents(self):
        command, manifest = self.captured_transport(large=True)
        path = Path(command[command.index('--job-file') + 1])
        digest = command[command.index('--job-file-sha256') + 1]
        with path.open('wb') as stream:
            stream.truncate(MAX_JSON_BYTES + 1)
        with patch('houdini_bridge.native_geometry_runtime_registry.os.open') as opened:
            with self.assertRaises(ValueError):
                _parse_job_file(str(path), digest)
            opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
