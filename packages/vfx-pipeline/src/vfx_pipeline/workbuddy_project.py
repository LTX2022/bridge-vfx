"""Persistent, synthetic-only WorkBuddy diagnostic runs.

This facade deliberately has no DCC client or approval-key access. Passing a
diagnostic is not permission to dispatch a host operation. The native app's
other tools and model identity require separate live evidence.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from dcc_task_runtime.pipeline_store import _ClosingSQLiteConnection
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def media_descriptor(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify only the controller manifest's supported media types."""
    mime = record.get('mime_type', 'image/png')
    if mime == 'image/png':
        kind = 'image'
    elif mime in {'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm', 'video/x-msvideo'}:
        kind = 'video'
    else:
        raise ValueError('unsupported registered media MIME type')
    result = {'asset_id':record['asset_id'], 'kind':kind, 'mime_type':mime, 'sha256':record['sha256']}
    for key in ('version', 'parent_asset_id', 'parent_sha256', 'source_frame', 'width', 'height'):
        if key in record:
            result[key] = record[key]
    return result


class DiagnosticRun:
    """Controller-created run; the model cannot register files or grant access."""

    def __init__(self, manifest_path: Path | str):
        source = Path(manifest_path)
        if source.is_symlink() or not source.is_file():
            raise ValueError("regular controller manifest required")
        self.root = source.resolve().parent
        self.manifest = json.loads(source.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != "bridge.workbuddy.diagnostic_run/1.0":
            raise ValueError("unsupported diagnostic manifest")
        self.run_id = self.manifest["run_id"]
        if not isinstance(self.run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", self.run_id):
            raise ValueError("invalid run identity")
        self.assets = {item["asset_id"]: item for item in self.manifest["assets"]}
        if len(self.assets) != len(self.manifest["assets"]):
            raise ValueError("duplicate assets")
        self.manifest_hash = _sha(self.manifest)
        self.database = self.root / "diagnostic.sqlite3"
        if self.database.is_symlink():
            raise ValueError("diagnostic database cannot be a symlink")
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS run_identity (id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations (request_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL, receipt TEXT NOT NULL);
            """)
            row = db.execute("SELECT id, manifest_hash FROM run_identity").fetchall()
            if row and row != [(self.run_id, self.manifest_hash)]:
                raise ValueError("run manifest drift; prepare a fresh run")
            db.execute("INSERT OR IGNORE INTO run_identity VALUES (?, ?)", (self.run_id, self.manifest_hash))

    def _connect(self):
        db = sqlite3.connect(str(self.database), timeout=5, factory=_ClosingSQLiteConnection)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _event(self, db, kind: str, payload: Mapping[str, Any]):
        row = db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else "0" * 64
        event = {"run_id": self.run_id, "kind": kind, "at": datetime.now(timezone.utc).isoformat(), "payload": dict(payload)}
        encoded = _canonical(event)
        digest = _sha({"previous_hash": previous, "event": event})
        cursor = db.execute("INSERT INTO events(payload,previous_hash,event_hash) VALUES (?,?,?)", (encoded, previous, digest))
        return {"seq": cursor.lastrowid, "event_hash": digest}

    def record_event(self, kind: str, payload: Mapping[str, Any]):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._event(db, kind, payload)

    def health(self):
        return {"schema": "bridge.workbuddy.diagnostic_health/1.0", "run_id": self.run_id,
                "manifest_hash": self.manifest_hash, "mode": "synthetic_diagnostic_only",
                "requested_route": "WorkBuddyDesktopRoute", "requested_model": "HY3",
                "model_identity_verified": False, "boundary_verified": False,
                "dcc_dispatch_enabled": False, "release_acceptance": False}

    def catalog(self):
        assets = []
        for key in sorted(self.assets):
            item = media_descriptor(self.assets[key])
            if item['kind'] == 'video':
                item.update(observation_asset_id=key, observation_basis='registered_decoded_frames',
                            required_tools=['media_video_frames', 'media_attachments'],
                            observation_instruction='Extract and read registered frames, then submit this source asset ID and the returned media_basis_id with observations limited to those frames.')
            assets.append(item)
        service = getattr(self, 'media_service', None)
        if service is not None:
            with self._connect() as db:
                rows = db.execute('SELECT asset_id FROM media_derivatives ORDER BY asset_id').fetchall()
            for (key,) in rows:
                item = media_descriptor(service._record(key))
                item['observation_asset_id'] = item['parent_asset_id']
                assets.append(item)
        return {"run_id": self.run_id, "assets": assets,
                "purpose": "Read registered images or extracted video frames, then submit your own bounded observations.",
                "dcc_dispatch_enabled": False}

    def media(self, asset_id: str):
        if not isinstance(asset_id, str) or asset_id not in self.assets:
            raise ValueError("unknown registered asset")
        record = self.assets[asset_id]
        if media_descriptor(record)['kind'] != 'image':
            raise ValueError('video observations require registered extracted frames; use media_video_frames and media_attachments')
        if record.get("classification") != "controller_generated_synthetic":
            raise ValueError("asset is not authorized for this diagnostic")
        relative = Path(record["file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid registered asset location")
        path = self.root / relative
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("symlinked media denied")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("media outside controller root")
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("media missing or too large")
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("registered media changed")
        return {"type": "image", "mimeType": "image/png", "data": base64.b64encode(data).decode("ascii")}

    def _video_observation_basis(self, asset_id: str, media_basis_id=None) -> dict[str, Any]:
        service = getattr(self, 'media_service', None)
        if service is None:
            raise ValueError('video observations require the controller media service')
        if media_basis_id is not None and (not isinstance(media_basis_id, str)
                or not re.fullmatch(r'selection-[0-9a-f]{32}', media_basis_id)):
            raise ValueError('controller media_basis_id required for video observation')
        basis = None
        with self._connect() as db:
            for seq, payload, previous, digest in db.execute('SELECT seq,payload,previous_hash,event_hash FROM events ORDER BY seq DESC'):
                event = json.loads(payload)
                selected = event['payload']
                if (event['kind'] == 'video_frames_selected'
                        and selected.get('source_asset_id') == asset_id
                        and (media_basis_id is None or selected.get('media_basis_id') == media_basis_id)):
                    if event.get('run_id') != self.run_id or digest != _sha({'previous_hash':previous, 'event':event}):
                        raise ValueError('video selection fact changed')
                    basis = {**selected, 'selection_receipt':{'seq':seq, 'event_hash':digest}}
                    break
        if basis is None:
            raise ValueError('video observations require media_video_frames before observing the source asset')
        return basis

    def _validate_video_basis(self, basis: Mapping[str, Any]):
        service = getattr(self, 'media_service', None)
        if service is None or not isinstance(basis, Mapping):
            raise ValueError('video observation media basis unavailable')
        selection_id = basis.get('media_basis_id')
        if not selection_id or basis != self._video_observation_basis(basis['source_asset_id'], selection_id):
            raise ValueError('video observation selection changed')
        source = service._record(basis['source_asset_id'])
        if source['sha256'] != basis['source_sha256'] or media_descriptor(source)['mime_type'] != basis['source_mime_type']:
            raise ValueError('video observation source changed')
        if basis.get('source_version') != source.get('version'):
            raise ValueError('video observation source version changed')
        frames = basis['frames']
        if not frames:
            raise ValueError('video observation frames missing')
        service.attachments([frame['asset_id'] for frame in frames])
        for frame in frames:
            if frame.get('parent_asset_id') != source['asset_id'] or frame.get('parent_sha256') != source['sha256']:
                raise ValueError('video observation frame parent changed')
            if media_descriptor(service._record(frame['asset_id'])) != frame:
                raise ValueError('video observation frame changed')

    def validate_reference_media(self, asset_id: str, *, observed_basis=None):
        """Rehash a frozen source and its controller-recorded observation input."""
        if asset_id not in self.assets:
            raise ValueError('unknown registered source asset')
        if media_descriptor(self.assets[asset_id])['kind'] == 'video':
            basis = self._video_observation_basis(asset_id) if observed_basis is None else observed_basis
            if basis.get('source_asset_id') != asset_id:
                raise ValueError('video observation source identity changed')
            self._validate_video_basis(basis)
            return basis
        self.media(asset_id)
        return None

    def submit_observation(self, asset_id: str, observation: Mapping[str, Any], request_id: str, media_basis_id=None):
        if asset_id not in self.assets:
            service = getattr(self, 'media_service', None)
            if service is not None:
                frame = service._record(asset_id)
                if frame.get('parent_asset_id'):
                    raise ValueError('submit extracted frame observations using their source asset_id')
            raise ValueError('unknown registered observation asset')
        basis = None
        if media_descriptor(self.assets[asset_id])['kind'] == 'video':
            if media_basis_id is None:
                raise ValueError('controller media_basis_id required for video observation')
            basis = self.validate_reference_media(asset_id, observed_basis=self._video_observation_basis(asset_id, media_basis_id))
        else:
            if media_basis_id is not None:
                raise ValueError('media_basis_id is only valid for source video observations')
            self.media(asset_id)  # Validate immutable registered bytes again.
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_id):
            raise ValueError("stable alphanumeric request_id required")
        if not isinstance(observation, Mapping) or not observation:
            raise ValueError("observation must be a nonempty object")
        allowed = {"description", "dominant_colors", "shape", "direction", "uncertainties"}
        if set(observation) - allowed or not isinstance(observation.get("description"), str) or not observation["description"].strip():
            raise ValueError("observation requires description and only documented observation fields")
        for key in ("shape", "direction"):
            if key in observation and not isinstance(observation[key], str):
                raise ValueError("shape and direction must be text")
        for key in ("dominant_colors", "uncertainties"):
            if key in observation and (not isinstance(observation[key], list) or not all(isinstance(v, str) for v in observation[key])):
                raise ValueError("colors and uncertainties must be text arrays")
        encoded = _canonical(dict(observation))
        if len(encoded.encode()) > 16384:
            raise ValueError("observation too large")
        identity = _sha({"asset_id": asset_id, "observation": dict(observation), **({'media_basis':basis} if basis else {})})
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_hash, receipt FROM observations WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != identity:
                    raise ValueError("request_id already belongs to another observation")
                return {**json.loads(row[1]), "replayed": True}
            event = self._event(db, "observation_received", {"request_id": request_id, "asset_id": asset_id, "observation_hash": identity,
                                                            **({'media_basis':basis} if basis else {})})
            result = {"run_id": self.run_id, "asset_id": asset_id, "request_id": request_id, "receipt": event,
                      "observation_recorded": True, "visual_correctness_verified": False,
                      "model_identity_verified": False, "dcc_dispatched": False, "replayed": False,
                      **({'media_basis':basis} if basis else {})}
            db.execute("INSERT INTO observations VALUES (?,?,?,?,?)", (request_id, asset_id, identity, encoded, _canonical(result)))
        return result

    def export(self):
        with self._connect() as db:
            events = db.execute("SELECT seq,payload,previous_hash,event_hash FROM events ORDER BY seq").fetchall()
            observations = db.execute("SELECT request_id,asset_id,request_hash,payload,receipt FROM observations ORDER BY rowid").fetchall()
        previous = "0" * 64
        decoded = []
        for seq, payload, prior, digest in events:
            event = json.loads(payload)
            if prior != previous or digest != _sha({"previous_hash": prior, "event": event}):
                raise ValueError("diagnostic event chain changed")
            previous = digest
            decoded.append({"seq": seq, **event, "event_hash": digest})
        by_sequence = {event['seq']: event for event in decoded}
        verified_observations = []
        for request_id, asset_id, request_hash, payload, receipt in observations:
            observation, result = json.loads(payload), json.loads(receipt)
            basis = result.get('media_basis')
            if basis:
                self.validate_reference_media(asset_id, observed_basis=basis)
            identity = _sha({'asset_id': asset_id, 'observation': observation, **({'media_basis':basis} if basis else {})})
            event = by_sequence.get(result.get('receipt', {}).get('seq'), {})
            if (identity != request_hash or event.get('kind') != 'observation_received'
                    or event.get('event_hash') != result.get('receipt', {}).get('event_hash')
                    or event.get('payload') != {'request_id': request_id, 'asset_id': asset_id, 'observation_hash': identity,
                                                **({'media_basis':basis} if basis else {})}
                    or result.get('run_id') != self.run_id or result.get('asset_id') != asset_id
                    or result.get('request_id') != request_id):
                raise ValueError('diagnostic observation or receipt changed')
            verified_observations.append({'asset_id': asset_id, 'observation': observation, 'receipt': result})
        return {"schema": "bridge.workbuddy.diagnostic_export/1.0", "run_id": self.run_id,
                "manifest_hash": self.manifest_hash, "events": decoded,
                "observations": verified_observations,
                "evidence_level": "local_connector_records_only", "release_acceptance": False,
                "remaining": ["actual_workbuddy_session_binding", "HY3_selection", "vision_correctness", "permission_boundary", "real_DCC", "visual_acceptance"]}
