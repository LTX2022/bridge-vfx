"""Production media registry, fixed decoder and operation budget contracts."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vfx_pipeline.controller_media import (ControllerMediaService, FixedVideoDecoder,
    OperationBudgetGuard, PngMetricDecoder)
from vfx_pipeline.media_readiness import MediaReadinessError, FixedPngDecoder
from vfx_pipeline.workbuddy_project import DiagnosticRun
from test_media_readiness import _png


class ControllerMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = []
        for i, value in enumerate((5, 25, 240)):
            path = self.root / ('frame%s.png' % i)
            path.write_bytes(_png(value, width=4, height=4))
            self.assets.append({'asset_id': 'asset%s' % i, 'file': path.name,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'classification': 'controller_generated_synthetic'})

    def run_manifest(self, **limits):
        path = self.root / 'run.json'
        path.write_text(json.dumps({'schema': 'bridge.workbuddy.diagnostic_run/1.0',
            'run_id': 'media-test', 'assets': self.assets}))
        run = DiagnosticRun(path)
        return run, ControllerMediaService(run, **limits)

    def test_registered_attachment_identity_limits_transfer_failure(self):
        run, service = self.run_manifest(max_attachments=2, max_total_bytes=140)
        self.assertEqual(service.media('asset0')['type'], 'image')
        with self.assertRaisesRegex(MediaReadinessError, 'COUNT'):
            service.attachments(['asset0', 'asset1', 'asset2'])
        with self.assertRaisesRegex(MediaReadinessError, 'TOTAL'):
            service.attachments(['asset0', 'asset1'])
        with self.assertRaisesRegex(MediaReadinessError, 'TRANSFER_FAILED'):
            service.transfer(['asset0'], lambda blocks: {'accepted_asset_count': 0})
        self.assertEqual(service.transfer(['asset0'], lambda blocks: {'accepted_asset_count': len(blocks)})['status'], 'ACCEPTED')
        (self.root / 'frame0.png').write_bytes(_png(1))
        with self.assertRaisesRegex(MediaReadinessError, 'VERSION_CHANGED'):
            service.media('asset0')

    def test_sequence_registered_identity_survives_decode_read_boundary(self):
        _, service = self.run_manifest()
        original = service._record
        def replace_after_registration(key):
            record = original(key)
            Path(record['path']).write_bytes(_png(120, width=4, height=4))
            return record
        with mock.patch.object(service, '_record', side_effect=replace_after_registration):
            with self.assertRaisesRegex(MediaReadinessError, 'MEDIA_VERSION_CHANGED'):
                service.sequence_diagnostics(['asset0'], frame_numbers=[0],
                    expected_frames=[0], active_frames=[0], raster_decoder=PngMetricDecoder())
        (self.root / 'frame0.png').write_bytes(_png(5,width=4,height=4))
        decoder = PngMetricDecoder()
        structural = decoder.structural.decode
        reads = []
        def replace_after_structural(path):
            metadata = structural(path)
            reads.append(metadata)
            if len(reads) == 1:
                Path(path).write_bytes(_png(220,width=4,height=4))
            return metadata
        with mock.patch.object(decoder.structural,'decode',side_effect=replace_after_structural):
            with self.assertRaisesRegex(MediaReadinessError,'MEDIA_VERSION_CHANGED'):
                service.sequence_diagnostics(['asset0'],frame_numbers=[0],
                    expected_frames=[0],active_frames=[0],raster_decoder=decoder)


    def test_private_asset_rejected(self):
        self.assets[0]['classification'] = 'private'
        run, service = self.run_manifest()
        with self.assertRaisesRegex(MediaReadinessError, 'SOURCE_NOT_AUTHORIZED'):
            service.media('asset0')

    def test_symlink_rejected(self):
        _, service = self.run_manifest()
        original = self.root / 'frame1.png'
        original.rename(self.root / 'original.png')
        try:
            original.symlink_to(self.root / 'original.png')
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('NOT_RUN: Windows symbolic-link privilege unavailable')
            raise
        with self.assertRaisesRegex(MediaReadinessError, 'SYMLINK'):
            service.media('asset1')

    def test_symlink_guard_at_filesystem_boundary(self):
        _, service = self.run_manifest()
        original = Path.is_symlink
        blocked = self.root / 'frame1.png'
        with mock.patch.object(Path, 'is_symlink', lambda path: path == blocked or original(path)):
            with self.assertRaisesRegex(MediaReadinessError, 'SYMLINK'):
                service.media('asset1')

    def test_pixel_metrics_freeze_gaps_and_abnormal_changes(self):
        run, service = self.run_manifest()
        decoder = PngMetricDecoder()
        normal = service.sequence_diagnostics(['asset0', 'asset1'], frame_numbers=[0, 1],
            expected_frames=[0, 1], active_frames=[0, 1], raster_decoder=decoder)
        self.assertEqual(normal['status'], 'PASS')
        self.assertFalse(normal['motion_correctness_verified'])
        frozen = service.sequence_diagnostics(['asset0', 'asset0'], frame_numbers=[0, 1],
            expected_frames=[0, 1], active_frames=[0, 1], raster_decoder=decoder)
        self.assertTrue(frozen['frozen_active'])
        self.assertEqual(frozen['status'], 'BLOCKED')
        bad = service.sequence_diagnostics(['asset0', 'asset2'], frame_numbers=[0, 2],
            expected_frames=[0, 1, 2], active_frames=[0, 1, 2], raster_decoder=decoder, max_temporal_delta=.5)
        self.assertEqual(bad['missing_frames'], [1])
        self.assertEqual(bad['abnormal_change_frames'], [2])

    def test_full_channel_identity_encoding_alpha_and_metric_pixel_budget(self):
        import struct
        import zlib
        from test_media_readiness import _chunk
        def png(pixel, level=6, width=1, height=1):
            channels = len(pixel)
            header = struct.pack('>IIBBBBB',width,height,8,6 if channels == 4 else 2,0,0,0)
            raw = b''.join(b'\0' + bytes(pixel) * width for _ in range(height))
            return b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR',header) + _chunk(b'IDAT',zlib.compress(raw,level)) + _chunk(b'IEND',b'')
        decoder = PngMetricDecoder()
        self.assets = []
        for name, pixel, level in [('red',(255,0,0),6),('green',(0,255,0),6),('red-reencoded',(255,0,0),0),('red-alpha',(255,0,0,128),6)]:
            path = self.root / (name+'.png'); path.write_bytes(png(pixel,level))
            self.assets.append({'asset_id':name,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'classification':'controller_generated_synthetic'})
        _, service = self.run_manifest()
        def inspect(a,b):
            return service.sequence_diagnostics([a,b],frame_numbers=[0,1],expected_frames=[0,1],active_frames=[0,1],raster_decoder=decoder)
        self.assertEqual(inspect('red','green')['status'],'PASS')
        self.assertEqual(inspect('red','red-alpha')['status'],'PASS')
        self.assertTrue(inspect('red','red-reencoded')['frozen_active'])
        self.assertNotEqual(self.assets[0]['sha256'],self.assets[2]['sha256'])
        path = self.root / 'oversized.png'; path.write_bytes(png((0,0,0),width=513,height=512))
        with self.assertRaisesRegex(MediaReadinessError,'PNG_METRIC_PIXEL_BUDGET_EXCEEDED'):
            decoder.decode(path)

    def test_fixed_video_actual_decode_replay_restart_and_missing_frame(self):
        executable = shutil.which('ffmpeg')
        self.assertIsNotNone(executable, 'fixed ffmpeg dependency must be available for the release verification')
        movie = self.root / 'synthetic.mp4'
        generated = subprocess.run([executable, '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc=size=16x16:rate=2:duration=2', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p',
            '-threads', '1', str(movie)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assets.append({'asset_id': 'video', 'file': movie.name,
            'sha256': hashlib.sha256(movie.read_bytes()).hexdigest(),
            'classification': 'controller_generated_synthetic'})
        decoder = FixedVideoDecoder(executable)
        run, service = self.run_manifest(video_decoder=decoder)
        extracted = service.extract_video('video', [0, 2])
        self.assertEqual(len(extracted['asset_ids']), 2)
        self.assertEqual(len(service.attachments(extracted['asset_ids'])), 2)
        restarted = ControllerMediaService(DiagnosticRun(self.root / 'run.json'), video_decoder=decoder)
        self.assertTrue(restarted.extract_video('video', [0, 2])['replayed'])
        with self.assertRaisesRegex(MediaReadinessError, 'FRAMES_MISSING'):
            service.extract_video('video', [100])
        movie.write_bytes(b'changed')
        with self.assertRaisesRegex(MediaReadinessError, 'VERSION_CHANGED'):
            restarted.media(extracted['asset_ids'][0])

    def test_identical_video_bytes_keep_distinct_registered_source_ancestry(self):
        class DecoderBoundary:
            calls = 0
            def decode(boundary, source, output, frames):
                boundary.calls += 1
                output.mkdir()
                receipts = []
                for frame in frames:
                    path = output / ('frame-%03d.png' % frame)
                    path.write_bytes(_png(frame + 10, width=4, height=4))
                    receipts.append({'source_frame': frame, 'path': str(path),
                        **FixedPngDecoder().decode(path)})
                return {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'frames': receipts}

        for name in ('first', 'second'):
            path = self.root / (name + '.mp4')
            path.write_bytes(b'identical registered synthetic video bytes')
            self.assets.append({'asset_id': name, 'file': path.name,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'classification': 'controller_generated_synthetic'})
        decoder = DecoderBoundary()
        run, service = self.run_manifest(video_decoder=decoder)
        source_sha256 = self.assets[-2]['sha256']
        legacy_identity = hashlib.sha256(json.dumps([source_sha256, [0, 2]]).encode()).hexdigest()[:24]
        legacy_ids = ['derived-' + legacy_identity + '-' + str(frame) for frame in (0, 2)]
        receipt = decoder.decode(self.root / 'first.mp4', self.root / 'legacy-frames', [0, 2])
        with service._database() as db:
            for key, frame in zip(legacy_ids, receipt['frames']):
                payload = {'asset_id': key, 'file': str(Path(frame['path']).relative_to(self.root)),
                    'sha256': frame['sha256'], 'width': frame['width'], 'height': frame['height'],
                    'version': 1, 'parent_asset_id': 'first', 'parent_sha256': source_sha256,
                    'source_frame': frame['source_frame'], 'classification': 'controller_derived_synthetic'}
                db.execute('INSERT INTO media_derivatives VALUES (?,?)', (key, json.dumps(payload)))
        decoder.calls = 0
        first = service.extract_video('first', [0, 2])
        self.assertTrue(first['replayed'])
        self.assertEqual(first['asset_ids'], legacy_ids)
        self.assertEqual(decoder.calls, 0)
        second = service.extract_video('second', [0, 2])
        self.assertEqual(decoder.calls, 1)
        self.assertTrue(set(first['asset_ids']).isdisjoint(second['asset_ids']))
        for selected in (first, second):
            for key in selected['asset_ids']:
                self.assertEqual(service._record(key)['parent_asset_id'], selected['source_asset_id'])
            self.assertEqual(len(service.attachments(selected['asset_ids'])), 2)
        restarted = ControllerMediaService(DiagnosticRun(self.root / 'run.json'), video_decoder=DecoderBoundary())
        self.assertTrue(restarted.extract_video('second', [0, 2])['replayed'])
        self.assertEqual(restarted.extract_video('first', [0, 2])['asset_ids'], first['asset_ids'])
        (self.root / 'first.mp4').write_bytes(b'changed source')
        with self.assertRaisesRegex(MediaReadinessError, 'MEDIA_VERSION_CHANGED'):
            restarted.media(first['asset_ids'][0])
        self.assertEqual(len(restarted.attachments(second['asset_ids'])), 2)

    def test_missing_decoder_bad_video_and_bomb_rejected(self):
        with self.assertRaisesRegex(MediaReadinessError, 'UNAVAILABLE'):
            FixedVideoDecoder('/not/a/decoder')
        with self.assertRaisesRegex(MediaReadinessError, 'DIMENSION'):
            FixedPngDecoder(max_dimension=1).decode(self.root / 'frame0.png')
        _, service = self.run_manifest()
        with self.assertRaisesRegex(MediaReadinessError, 'UNAVAILABLE'):
            service.extract_video('asset0', [0])

    def test_owned_budget_multiple_roots_cancel_once_and_unknown_never_release(self):
        roots = [self.root / name for name in ('output', 'cache', 'tmp')]
        owner = {'task_id': 'task', 'operation_id': 'operation', 'launch_nonce': 'nonce'}
        cancellations = []
        guard = OperationBudgetGuard(roots, max_bytes=100, owner=owner, stop_callback=cancellations.append)
        self.assertEqual(guard.check(owner=owner, phase='preflight')['status'], 'PASS')
        for root in roots:
            (root / 'payload').write_bytes(b'x' * 40)
        with self.assertRaisesRegex(MediaReadinessError, 'OWNER_MISMATCH'):
            guard.check(owner={**owner, 'operation_id': 'other'})
        receipt = guard.check(owner=owner)
        self.assertEqual(receipt['usage_bytes'], 120)
        self.assertFalse(receipt['slot_release_authorized'])
        self.assertFalse(receipt['stop_confirmed'])
        guard.check(owner=owner)
        self.assertEqual(cancellations, [owner])
        self.assertTrue(all((root / 'payload').is_file() for root in roots))
        self.assertFalse(guard.check(owner=owner, phase='preflight')['slot_release_authorized'])


if __name__ == '__main__':
    unittest.main()
