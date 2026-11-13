"""Controller-owned media intake for the existing WorkBuddy run registry.

Only registry IDs reach model tools. Executables, provenance and task paths are
provided by the trusted controller. Software diagnostics never assert vision
acceptance. Budget cancellation uses the operation's existing stop/release path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dcc_task_runtime.metrics import MetricEngine, MetricProvenance
from .media_readiness import FixedPngDecoder, MediaReadinessError, _safe_task_path


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _integers(values: Sequence[int], maximum=12) -> list[int]:
    if (not values or len(values) > maximum or
            any(type(n) is not int or n < 0 for n in values) or
            list(values) != sorted(set(values))):
        raise MediaReadinessError('EXPLICIT_FRAME_SET_REQUIRED')
    return list(values)


class FixedVideoDecoder:
    """Fixed local demux/decoder; no caller commands, URLs or media playlists."""
    FORMATS = {'.mp4': 'mov', '.mov': 'mov', '.mkv': 'matroska', '.webm': 'matroska', '.avi': 'avi'}

    def __init__(self, executable: str, *, timeout_seconds: float = 30,
                 max_input_bytes: int = 64 * 1024 * 1024):
        path = Path(executable).expanduser()
        if (not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK)
                or (os.name == 'nt' and path.resolve().suffix.lower() not in {'.exe', '.com'})):
            raise MediaReadinessError('FIXED_VIDEO_DECODER_UNAVAILABLE')
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
            raise MediaReadinessError('VIDEO_TIMEOUT_INVALID')
        self.executable = str(path.resolve())
        self.timeout_seconds = timeout_seconds
        self.max_input_bytes = max_input_bytes

    def decode(self, source: Path, output: Path, frames: Sequence[int]) -> dict[str, Any]:
        frames = _integers(frames)
        source = Path(source)
        demuxer = self.FORMATS.get(source.suffix.lower())
        if demuxer is None or source.is_symlink() or not source.is_file():
            raise MediaReadinessError('VIDEO_FORMAT_OR_PATH_INVALID')
        if source.stat().st_size > self.max_input_bytes:
            raise MediaReadinessError('VIDEO_INPUT_LIMIT')
        digest = _digest(source)
        output = Path(output)
        output.mkdir(parents=True, exist_ok=False)
        select = '+'.join('eq(n\\,{})'.format(frame) for frame in frames)
        command = [self.executable, '-nostdin', '-hide_banner', '-loglevel', 'error',
                   '-protocol_whitelist', 'file,pipe', '-f', demuxer, '-i', str(source),
                   '-map', '0:v:0', '-an', '-sn', '-dn', '-vf',
                   "select='{}',scale=512:512:force_original_aspect_ratio=decrease,format=rgb24".format(select),
                   '-fps_mode', 'vfr', '-frames:v', str(len(frames)), '-threads', '1',
                   '-start_number', '0', str(output / 'frame-%03d.png')]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=self.timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MediaReadinessError('VIDEO_DECODE_FAILED: {}'.format(type(exc).__name__)) from exc
        if result.returncode != 0:
            raise MediaReadinessError('VIDEO_DECODE_FAILED: rc={}'.format(result.returncode))
        paths = sorted(output.glob('frame-*.png'))
        if len(paths) != len(frames) or _digest(source) != digest:
            raise MediaReadinessError('VIDEO_FRAMES_MISSING_OR_SOURCE_CHANGED')
        decoder = FixedPngDecoder(max_bytes=4 * 1024 * 1024, max_dimension=512)
        receipts = []
        for frame, path in zip(frames, paths):
            receipts.append({'source_frame': frame, 'path': str(path), **decoder.decode(path)})
        return {'source_sha256': digest, 'decoder': 'fixed_ffmpeg_png_v1', 'frames': receipts,
                'time_basis': 'zero_based_decoded_frame_index', 'visual_verified': False}


class ControllerMediaService:
    """Use DiagnosticRun's trusted asset manifest and event/SQLite store.

    Derivatives are recorded only after this controller decodes a registered
    synthetic parent. A model cannot supply classification or a filesystem path.
    """
    def __init__(self, run, *, video_decoder: FixedVideoDecoder | None = None,
                 max_attachments: int = 12, max_attachment_bytes: int = 4 * 1024 * 1024,
                 max_total_bytes: int = 16 * 1024 * 1024, max_dimension: int = 4096):
        self.run = run
        self.root = run.root
        self.video_decoder = video_decoder
        self.max_attachments = max_attachments
        self.max_attachment_bytes = max_attachment_bytes
        self.max_total_bytes = max_total_bytes
        if any(type(v) is not int or v <= 0 for v in (max_attachments, max_attachment_bytes, max_total_bytes, max_dimension)):
            raise MediaReadinessError('ATTACHMENT_LIMIT_INVALID')
        self.decoder = FixedPngDecoder(max_bytes=max_attachment_bytes, max_dimension=max_dimension)
        with self._database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_derivatives (asset_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def _database(self):
        db = self.run._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _record(self, asset_id: str, ancestry=()) -> dict[str, Any]:
        if not isinstance(asset_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', asset_id):
            raise MediaReadinessError('MEDIA_ID_INVALID')
        if asset_id in ancestry:
            raise MediaReadinessError('MEDIA_DEPENDENCY_CYCLE')
        record = self.run.assets.get(asset_id)
        if record is None:
            with self._database() as db:
                row = db.execute('SELECT payload FROM media_derivatives WHERE asset_id=?', (asset_id,)).fetchone()
            record = json.loads(row[0]) if row else None
        if not record:
            raise MediaReadinessError('MEDIA_NOT_REGISTERED')
        record = dict(record)
        classification = record.get('classification')
        if classification == 'controller_derived_synthetic':
            parent = self._record(record.get('parent_asset_id'), (*ancestry, asset_id))
            if parent['sha256'] != record.get('parent_sha256'):
                raise MediaReadinessError('MEDIA_PARENT_VERSION_CHANGED')
        elif classification != 'controller_generated_synthetic':
            raise MediaReadinessError('MEDIA_SOURCE_NOT_AUTHORIZED')
        relative = Path(record.get('file', ''))
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise MediaReadinessError('MEDIA_PATH_INVALID')
        path = _safe_task_path(self.root, self.root / relative)
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024 or _digest(path) != record.get('sha256'):
            raise MediaReadinessError('MEDIA_VERSION_CHANGED')
        record['path'] = path
        return record

    def extract_video(self, asset_id: str, frames: Sequence[int]) -> dict[str, Any]:
        record = self._record(asset_id)
        if self.video_decoder is None:
            raise MediaReadinessError('FIXED_VIDEO_DECODER_UNAVAILABLE')
        frames = _integers(frames)
        identity = hashlib.sha256(json.dumps([asset_id, record['sha256'], frames]).encode()).hexdigest()[:24]
        ids = ['derived-' + identity + '-' + str(frame) for frame in frames]
        try:
            previous = [self._record(key) for key in ids]
        except MediaReadinessError as exc:
            if str(exc) != 'MEDIA_NOT_REGISTERED':
                raise
        else:
            return self._select_video_frames(record, ids, frames, replayed=True)
        # Older selections used content-only IDs; reuse only their exact source
        # binding so another registered source with the same bytes stays independent.
        legacy_identity = hashlib.sha256(json.dumps([record['sha256'], frames]).encode()).hexdigest()[:24]
        legacy_ids = ['derived-' + legacy_identity + '-' + str(frame) for frame in frames]
        with self._database() as db:
            rows = [db.execute('SELECT payload FROM media_derivatives WHERE asset_id=?', (key,)).fetchone()
                    for key in legacy_ids]
        if all(row is not None for row in rows):
            legacy = [json.loads(row[0]) for row in rows]
            if all(item.get('parent_asset_id') == asset_id
                   and item.get('parent_sha256') == record['sha256']
                   and item.get('source_frame') == frame for item, frame in zip(legacy, frames)):
                return self._select_video_frames(record, legacy_ids, frames, replayed=True)
        derived_root = self.root / 'media-derived'
        derived_root.mkdir(exist_ok=True)
        _safe_task_path(self.root, derived_root)
        # A unique directory prevents overwriting evidence from earlier attempts.
        parent = Path(tempfile.mkdtemp(prefix=identity + '-', dir=derived_root))
        receipt = self.video_decoder.decode(record['path'], parent / 'frames', frames)
        if receipt['source_sha256'] != record['sha256']:
            raise MediaReadinessError('MEDIA_VERSION_CHANGED')
        with self._database() as db:
            db.execute('BEGIN IMMEDIATE')
            for key, decoded in zip(ids, receipt['frames']):
                value = {'asset_id': key, 'file': str(Path(decoded['path']).relative_to(self.root)),
                         'sha256': decoded['sha256'], 'width': decoded['width'], 'height': decoded['height'],
                         'version': 1, 'parent_asset_id': asset_id, 'parent_sha256': record['sha256'],
                         'source_frame': decoded['source_frame'], 'classification': 'controller_derived_synthetic'}
                db.execute('INSERT OR IGNORE INTO media_derivatives VALUES (?,?)', (key, json.dumps(value, sort_keys=True)))
            self.run._event(db, 'video_frames_registered', {'source_asset_id': asset_id, 'asset_ids': ids, 'frames': frames})
        return self._select_video_frames(record, ids, frames, replayed=False)

    def _select_video_frames(self, source, ids, frames, *, replayed):
        """Freeze each successful selection, including reuse of decoded files."""
        from .workbuddy_project import media_descriptor
        selected = []
        for key, number in zip(ids, frames):
            frame = self._record(key)
            if (frame.get('parent_asset_id') != source['asset_id']
                    or frame.get('parent_sha256') != source['sha256']
                    or frame.get('source_frame') != number):
                raise MediaReadinessError('VIDEO_SELECTION_SOURCE_CHANGED')
            selected.append(media_descriptor(frame))
        # Recheck the source after decode/replay; the fact never describes bytes
        # that changed while the controller was selecting the derived images.
        current = self._record(source['asset_id'])
        if media_descriptor(current) != media_descriptor(source):
            raise MediaReadinessError('MEDIA_VERSION_CHANGED')
        basis = {'media_basis_id': 'selection-' + uuid.uuid4().hex,
                 'source_asset_id': source['asset_id'], 'source_sha256': source['sha256'],
                 'source_mime_type': media_descriptor(source)['mime_type'], 'frames': selected,
                 'time_basis': 'zero_based_decoded_frame_index', 'motion_correctness_verified': False}
        if 'version' in source:
            basis['source_version'] = source['version']
        self.run.record_event('video_frames_selected', basis)
        return {'asset_ids': ids, 'source_asset_id': source['asset_id'], 'frames': frames,
                'media_basis_id': basis['media_basis_id'], 'replayed': replayed,
                'time_basis': basis['time_basis'], 'visual_verified': False}

    def attachments(self, asset_ids: Sequence[str]) -> list[dict[str, Any]]:
        if isinstance(asset_ids, (str, bytes)) or not asset_ids or len(asset_ids) > self.max_attachments or len(set(asset_ids)) != len(asset_ids):
            raise MediaReadinessError('ATTACHMENT_COUNT_INVALID')
        blocks, total = [], 0
        for key in asset_ids:
            record = self._record(key)
            decoded = self.decoder.decode(record['path'])
            total += decoded['bytes']
            if total > self.max_total_bytes:
                raise MediaReadinessError('ATTACHMENT_TOTAL_LIMIT')
            data = record['path'].read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise MediaReadinessError('MEDIA_CHANGED_DURING_TRANSFER')
            blocks.append({'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode('ascii')})
        return blocks

    def media(self, asset_id: str):
        return self.attachments([asset_id])[0]

    def transfer(self, asset_ids: Sequence[str], send: Callable) -> dict[str, Any]:
        blocks = self.attachments(asset_ids)
        try:
            result = send(blocks)
            if not isinstance(result, Mapping) or result.get('accepted_asset_count') != len(blocks):
                raise MediaReadinessError('ATTACHMENT_ACK_MISMATCH')
        except Exception as exc:
            self.run.record_event('media_transfer_failed', {'asset_ids': list(asset_ids), 'error': type(exc).__name__})
            raise MediaReadinessError('MEDIA_TRANSFER_FAILED') from exc
        self.run.record_event('media_transfer_accepted', {'asset_ids': list(asset_ids), 'count': len(blocks)})
        return {'status': 'ACCEPTED', 'asset_ids': list(asset_ids), 'count': len(blocks)}

    def sequence_diagnostics(self, asset_ids: Sequence[str], *, frame_numbers: Sequence[int],
                             expected_frames: Sequence[int], active_frames: Sequence[int],
                             raster_decoder, max_temporal_delta: float = 1.0) -> dict[str, Any]:
        expected = _integers(expected_frames)
        actual = _integers(frame_numbers)
        active = _integers(active_frames)
        if len(asset_ids) != len(actual) or not set(active).issubset(expected):
            raise MediaReadinessError('FRAME_IDENTITY_INVALID')
        if not math.isfinite(max_temporal_delta) or max_temporal_delta < 0:
            raise MediaReadinessError('DELTA_LIMIT_INVALID')
        records = [self._record(key) for key in asset_ids]
        decoded = []
        pixels = 0
        for record in records:
            metadata = raster_decoder.structural.decode(Path(record['path']))
            if not hmac.compare_digest(str(metadata.get('sha256') or ''), str(record['sha256'])):
                raise MediaReadinessError('MEDIA_VERSION_CHANGED')
            pixels += metadata['width'] * metadata['height']
            if pixels > 1024 * 1024:
                raise MediaReadinessError('SEQUENCE_METRIC_PIXEL_BUDGET_EXCEEDED: limit=1048576')
            raster = raster_decoder.decode(record['path'])
            if not hmac.compare_digest(str(raster[1].get('sha256') or ''), str(record['sha256'])):
                raise MediaReadinessError('MEDIA_VERSION_CHANGED')
            decoded.append(raster)
        rasters = [item[0] for item in decoded]
        pixel_digests = [item[1]['decoded_rgba_sha256'] for item in decoded]
        hashes = [record['sha256'] for record in records]
        provenance = MetricProvenance('controller_registered_media', tuple(asset_ids), tuple(hashes),
                                      metadata={'frame_numbers': actual, 'expected_frames': expected, 'active_frames': active})
        engine = MetricEngine()
        metrics = engine.sequence_summary(rasters, provenance)
        positions = {number: index for index, number in enumerate(actual)}
        active_digests = [pixel_digests[positions[n]] for n in active if n in positions]
        frozen = len(active_digests) > 1 and len(set(active_digests)) == 1
        seen = set()
        duplicates = []
        for frame, digest in zip(actual, pixel_digests):
            if digest in seen:
                duplicates.append(frame)
            seen.add(digest)
        abnormal = []
        for index in range(1, len(rasters)):
            delta = engine.compare_rasters(rasters[index - 1], rasters[index], provenance)[0].value
            if delta > max_temporal_delta:
                abnormal.append(actual[index])
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        result = {'status': 'BLOCKED' if missing or unexpected or frozen or abnormal or set(duplicates).intersection(active) else 'PASS',
                  'missing_frames': missing, 'unexpected_frames': unexpected, 'duplicate_frames': duplicates,
                  'frozen_active': frozen, 'abnormal_change_frames': abnormal,
                  'metrics': [metric.to_dict() for metric in metrics], 'visual_verified': False,
                  'motion_correctness_verified': False}
        self.run.record_event('sequence_diagnostics', result)
        return result


class OperationBudgetGuard:
    """One operation's budget; only its pre-bound cancellation callback is used."""
    def __init__(self, roots: Sequence[Path], *, max_bytes: int, owner: Mapping[str, Any],
                 stop_callback: Callable, max_seconds: float = 120.0,
                 native_scope=None, scope_role=None):
        seconds_cap = 120
        scope = None
        if native_scope is not None:
            from dcc_task_runtime.native_scope import NativeScope
            scope = NativeScope(native_scope)
            if scope_role != 'graph-worker':
                raise MediaReadinessError('OPERATION_SCOPE_ROLE_INVALID')
            seconds_cap = scope.role_seconds(scope_role)
        elif scope_role is not None:
            raise MediaReadinessError('OPERATION_SCOPE_ROLE_INVALID')
        if (type(max_bytes) is not int or max_bytes <= 0
                or type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
                or not 0 < max_seconds <= seconds_cap
                or scope is not None and max_bytes > scope.scope['budget']['max_disk_bytes']):
            raise MediaReadinessError('OPERATION_BUDGET_INVALID')
        required = {'task_id', 'operation_id', 'launch_nonce'}
        if not required.issubset(owner) or any(not owner[key] for key in required):
            raise MediaReadinessError('OPERATION_OWNER_INVALID')
        if not roots:
            raise MediaReadinessError('OPERATION_ROOTS_REQUIRED')
        self.roots = []
        for root in roots:
            path = Path(root).absolute()
            if path.is_symlink() or (scope is not None and
                    (any(parent.is_symlink() for parent in path.parents)
                     or not path.resolve().is_relative_to(scope.root))):
                raise MediaReadinessError('BUDGET_ROOT_SYMLINK')
            path.mkdir(parents=True, exist_ok=True)
            self.roots.append(path.resolve())
        self.owner = dict(owner)
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        self.stop_callback = stop_callback
        self.stop_requested = False
        self._lock = threading.Lock()

    def check(self, *, owner: Mapping[str, Any], frames: int = 0, elapsed_seconds: float = 0,
              estimated_bytes: int = 0, phase: str = 'runtime') -> dict[str, Any]:
        if dict(owner) != self.owner:
            raise MediaReadinessError('OPERATION_OWNER_MISMATCH')
        if type(frames) is not int or frames < 0 or type(estimated_bytes) is not int or estimated_bytes < 0 or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise MediaReadinessError('OPERATION_BUDGET_INPUT_INVALID')
        total, seen, unsafe = 0, set(), False
        for root in self.roots:
            if root.is_symlink() or not root.is_dir():
                unsafe = True
                continue
            for path in root.rglob('*'):
                if path.is_symlink():
                    unsafe = True
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if path.is_file() and (stat.st_dev, stat.st_ino) not in seen:
                    seen.add((stat.st_dev, stat.st_ino))
                    total += stat.st_size
        reasons = []
        if total + estimated_bytes > self.max_bytes:
            reasons.append('DISK_BUDGET_EXCEEDED')
        if elapsed_seconds > self.max_seconds:
            reasons.append('TIME_LIMIT_EXCEEDED')
        if frames > 12:
            reasons.append('FRAME_LIMIT_EXCEEDED')
        if unsafe:
            reasons.append('BUDGET_SYMLINK_UNACCOUNTED')
        if reasons and phase != 'preflight':
            with self._lock:
                if not self.stop_requested:
                    self.stop_callback(dict(self.owner))
                    self.stop_requested = True
        return {'status': 'STOP_REQUESTED' if reasons else 'PASS', 'owner': dict(self.owner),
                'usage_bytes': total, 'limit_bytes': self.max_bytes, 'reasons': reasons,
                'stop_requested': self.stop_requested, 'stop_confirmed': False,
                'slot_release_authorized': False, 'deleted_paths': []}

class PngMetricDecoder:
    """Bounded numeric raster plus exact canonical RGBA pixel identity."""
    def __init__(self, max_dimension=4096, max_metric_pixels=256 * 1024):
        self.structural = FixedPngDecoder(max_dimension=max_dimension)
        self.max_metric_pixels = max_metric_pixels

    def decode(self, path):
        import struct
        import zlib
        path = Path(path)
        meta = self.structural.decode(path)
        if meta['width'] * meta['height'] > self.max_metric_pixels:
            raise MediaReadinessError('PNG_METRIC_PIXEL_BUDGET_EXCEEDED: limit=' + str(self.max_metric_pixels))
        if meta['bit_depth'] != 8 or meta['color_type'] not in {0, 2, 4, 6}:
            raise MediaReadinessError('PNG_METRIC_COLOR_MODEL_UNSUPPORTED')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise MediaReadinessError('MEDIA_VERSION_CHANGED')
        offset, compressed, transparent = 8, [], None
        while offset < len(data):
            length = struct.unpack('>I', data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            if kind == b'IDAT':
                compressed.append(data[offset + 8:offset + 8 + length])
            elif kind == b'tRNS':
                payload = data[offset + 8:offset + 8 + length]
                count = {0:1,2:3}.get(meta['color_type'])
                if transparent is not None or count is None or len(payload) != count * 2:
                    raise MediaReadinessError('PNG_METRIC_TRANSPARENCY_UNSUPPORTED')
                transparent = struct.unpack('>' + 'H' * count, payload)
                if any(value > 255 for value in transparent):
                    raise MediaReadinessError('PNG_METRIC_TRANSPARENCY_UNSUPPORTED')
            offset += length + 12
        channels, width, height = meta['channels'], meta['width'], meta['height']
        stride = channels * width
        raw = zlib.decompressobj().decompress(b''.join(compressed), (stride + 1) * height + 1)
        previous = bytearray(stride)
        raster = []
        digest = hashlib.sha256(struct.pack('>II', width, height))
        for y in range(height):
            filter_type = raw[y * (stride + 1)]
            row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
            for x in range(stride):
                left = row[x - channels] if x >= channels else 0
                above = previous[x]
                upper_left = previous[x - channels] if x >= channels else 0
                if filter_type == 1:
                    prediction = left
                elif filter_type == 2:
                    prediction = above
                elif filter_type == 3:
                    prediction = (left + above) // 2
                elif filter_type == 4:
                    p = left + above - upper_left
                    distances = (abs(p - left), abs(p - above), abs(p - upper_left))
                    prediction = (left, above, upper_left)[distances.index(min(distances))]
                else:
                    prediction = 0
                row[x] = (row[x] + prediction) & 255
            canonical = bytearray()
            values = []
            for x in range(width):
                pixel = row[x * channels:(x + 1) * channels]
                if meta['color_type'] in {0,4}:
                    color = (pixel[0],) * 3
                    alpha = pixel[1] if channels == 2 else (0 if transparent == (pixel[0],) else 255)
                else:
                    color = tuple(pixel[:3])
                    alpha = pixel[3] if channels == 4 else (0 if transparent == color else 255)
                canonical.extend((*color, alpha))
                values.append(sum(color) / 765)
            digest.update(canonical)
            raster.append(values)
            previous = row
        meta['decoded_rgba_sha256'] = digest.hexdigest()
        return raster, meta
