import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from windows_filesystem_fixture import fixture_symlink

from vfx_pipeline.workbuddy_project import DiagnosticRun


class DiagnosticRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = b'\x89PNG\r\n\x1a\nsynthetic fixture'
        (self.root / 'image.png').write_bytes(data)
        self.manifest = {'schema': 'bridge.workbuddy.diagnostic_run/1.0', 'run_id': 'run1', 'assets': [{
            'asset_id': 'opaque1', 'file': 'image.png', 'sha256': hashlib.sha256(data).hexdigest(),
            'classification': 'controller_generated_synthetic',
        }]}
        self.path = self.root / 'run.json'
        self.path.write_text(json.dumps(self.manifest))
        self.run = DiagnosticRun(self.path)

    def test_image_is_image_content_not_text_path(self):
        result = self.run.media('opaque1')
        self.assertEqual(result['type'], 'image')
        self.assertEqual(result['mimeType'], 'image/png')
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_unknown_path_and_changed_bytes_rejected(self):
        with self.assertRaises(ValueError): self.run.media('/private/private.hip')
        (self.root / 'image.png').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.run.media('opaque1')

    def test_media_symlink_rejected(self):
        (self.root / 'image.png').rename(self.root / 'original.png')
        if not fixture_symlink(self, self.root / 'image.png', self.root / 'original.png'):
            return
        with self.assertRaises(ValueError): self.run.media('opaque1')

    def test_observation_durable_idempotent_and_not_acceptance(self):
        payload = {'description': 'my observation', 'dominant_colors': ['unknown'], 'uncertainties': ['motion']}
        first = self.run.submit_observation('opaque1', payload, 'turn1')
        replay = DiagnosticRun(self.path).submit_observation('opaque1', payload, 'turn1')
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['receipt'], replay['receipt'])
        self.assertFalse(first['model_identity_verified'])
        with self.assertRaises(ValueError): self.run.submit_observation('opaque1', {'description': 'changed'}, 'turn1')
        exported = self.run.export()
        self.assertEqual(len(exported['observations']), 1)
        self.assertFalse(exported['release_acceptance'])

    def test_model_cannot_promote_or_register_files(self):
        for field in ('verified', 'passed', 'path', 'source_sha256', 'grant'):
            with self.assertRaises(ValueError):
                self.run.submit_observation('opaque1', {'description': 'test', field: True}, 'turn1')
        self.assertFalse(self.run.health()['dcc_dispatch_enabled'])

    def test_manifest_drift_and_event_tamper_detected(self):
        self.run.record_event('test', {'value': 1})
        with closing(sqlite3.connect(str(self.run.database))) as db, db:
            db.execute("UPDATE events SET event_hash=?", ('f'*64,))
        with self.assertRaises(ValueError): self.run.export()
        self.manifest['injected'] = True
        self.path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError): DiagnosticRun(self.path)

    def test_observation_tamper_detected(self):
        self.run.submit_observation('opaque1', {'description': 'original'}, 'turn1')
        with closing(sqlite3.connect(str(self.run.database))) as db, db:
            db.execute('UPDATE observations SET payload=?', (json.dumps({'description': 'rewritten'}),))
        with self.assertRaises(ValueError): self.run.export()


if __name__ == '__main__': unittest.main()
