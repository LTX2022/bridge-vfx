"""Bounded local-media and cache-contract probes for the S-06 readiness gate.

The module is deliberately mechanical: it registers bytes from an explicitly
local task directory, decodes a fixed PNG subset, and reports hashes, frame
identity, budget state, and semantic-control invalidation.  It never calls a
model, reads a remote URI, deletes files, or claims visual acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from dcc_task_runtime.domains import DomainPack
from dcc_task_runtime.visual_objective import MediaAsset, MediaManifest


MEDIA_READINESS_SCHEMA = "bridge.full_readiness.media/1.0"
MAX_FRAMES_PER_OPERATION = 12
MAX_OPERATION_SECONDS = 120.0
DEFAULT_MAX_TRANSFER_BYTES = 64 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MediaReadinessError(ValueError):
    """A local media or bounded-cache contract cannot be proven."""


class DiskBudgetExceeded(MediaReadinessError):
    """A task-owned output directory exceeded its configured budget."""


def _sha256_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise MediaReadinessError("MEDIA_PATH_NOT_REGULAR: {}".format(path))
    size = int(path.stat().st_size)
    if size > max_bytes:
        raise MediaReadinessError("MEDIA_TRANSFER_LIMIT_EXCEEDED: {} bytes".format(size))
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            if total > max_bytes:
                raise MediaReadinessError("MEDIA_TRANSFER_LIMIT_EXCEEDED")
            digest.update(chunk)
    if total != size:
        raise MediaReadinessError("MEDIA_CHANGED_DURING_READ: {}".format(path))
    return digest.hexdigest(), total


class FixedPngDecoder:
    """Decode and validate a bounded, non-interlaced PNG raster subset."""

    name = "png_structural_decode_v1"

    def __init__(self, *, max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
                 max_dimension: int = 8192, max_decoded_bytes: int = 64 * 1024 * 1024) -> None:
        if max_bytes <= 0 or max_dimension <= 0:
            raise ValueError("PNG decoder limits must be positive")
        self.max_bytes = int(max_bytes)
        self.max_dimension = int(max_dimension)
        self.max_decoded_bytes = int(max_decoded_bytes)

    def decode(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        digest, size = _sha256_file(path, max_bytes=self.max_bytes)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise MediaReadinessError("MEDIA_CHANGED_DURING_READ")
        if data[:8] != _PNG_SIGNATURE:
            raise MediaReadinessError("PNG_SIGNATURE_INVALID: {}".format(path))
        offset = 8
        ihdr: tuple[int, int, int, int, int, int, int] | None = None
        idat: list[bytes] = []
        saw_iend = False
        palette = None
        chunk_count = 0
        while offset < len(data):
            if len(data) - offset < 12:
                raise MediaReadinessError("PNG_CHUNK_TRUNCATED: {}".format(path))
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4
            if length > len(data) - offset - 8:
                raise MediaReadinessError("PNG_CHUNK_LENGTH_INVALID: {}".format(path))
            chunk_type = data[offset:offset + 4]
            offset += 4
            payload = data[offset:offset + length]
            offset += length
            supplied_crc = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4
            actual_crc = zlib.crc32(chunk_type + payload) & 0xffffffff
            if supplied_crc != actual_crc:
                raise MediaReadinessError("PNG_CRC_INVALID: {}".format(path))
            chunk_count += 1
            if chunk_type == b"IHDR":
                if ihdr is not None or chunk_count != 1 or len(payload) != 13:
                    raise MediaReadinessError("PNG_IHDR_INVALID: {}".format(path))
                ihdr = struct.unpack(">IIBBBBB", payload)
            elif chunk_type == b"IDAT":
                idat.append(payload)
            elif chunk_type == b"PLTE":
                if palette is not None or idat or not payload or len(payload) % 3 or len(payload) > 768:
                    raise MediaReadinessError("PNG_PALETTE_INVALID")
                palette = payload
            elif chunk_type == b"IEND":
                if payload or saw_iend:
                    raise MediaReadinessError("PNG_IEND_INVALID: {}".format(path))
                saw_iend = True
                if offset != len(data):
                    raise MediaReadinessError("PNG_TRAILING_BYTES: {}".format(path))
                break
            elif not chunk_type[0] & 32:
                raise MediaReadinessError("PNG_UNKNOWN_CRITICAL_CHUNK")
        if ihdr is None or not idat or not saw_iend:
            raise MediaReadinessError("PNG_REQUIRED_CHUNKS_MISSING: {}".format(path))
        width, height, bit_depth, color_type, compression, filtering, interlace = ihdr
        if not 1 <= width <= self.max_dimension or not 1 <= height <= self.max_dimension:
            raise MediaReadinessError("PNG_DIMENSION_LIMIT_EXCEEDED: {}".format(path))
        if compression != 0 or filtering != 0 or interlace != 0:
            raise MediaReadinessError("PNG_UNSUPPORTED_ENCODING: {}".format(path))
        allowed_depths = {
            0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
            4: {8, 16}, 6: {8, 16},
        }
        if color_type not in allowed_depths or bit_depth not in allowed_depths[color_type]:
            raise MediaReadinessError("PNG_COLOR_MODEL_UNSUPPORTED: {}".format(path))
        if color_type == 3 and palette is None:
            raise MediaReadinessError("PNG_PALETTE_MISSING")
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        row_bytes = math.ceil(width * channels * bit_depth / 8)
        expected_raw_size = (row_bytes + 1) * height
        if expected_raw_size > self.max_decoded_bytes:
            raise MediaReadinessError("PNG_DECODED_SIZE_LIMIT")
        try:
            inflater = zlib.decompressobj()
            raw = inflater.decompress(b"".join(idat), expected_raw_size + 1)
        except zlib.error as exc:
            raise MediaReadinessError("PNG_IDAT_DECODE_FAILED: {}".format(path)) from exc
        if len(raw) != expected_raw_size or not inflater.eof or inflater.unused_data:
            raise MediaReadinessError(
                "PNG_SCANLINE_SIZE_INVALID: expected {}, got {}".format(expected_raw_size, len(raw)))
        if any(raw[row * (row_bytes + 1)] > 4 for row in range(height)):
            raise MediaReadinessError("PNG_FILTER_INVALID")
        return {
            "decoder": self.name,
            "format": "png",
            "width": int(width),
            "height": int(height),
            "bit_depth": int(bit_depth),
            "color_type": int(color_type),
            "channels": channels,
            "bytes": size,
            "sha256": digest,
            "chunk_count": chunk_count,
            "decoded_scanlines": int(height),
        }


def _safe_task_path(root: Path, path: Path) -> Path:
    root = Path(root).expanduser().resolve()
    path = Path(path).expanduser().absolute()
    if not root.is_dir() or root.is_symlink():
        raise MediaReadinessError("MEDIA_ROOT_INVALID: {}".format(root))
    for item in (path, *path.parents):
        if item.resolve() == root:
            break
        if item.is_symlink():
            raise MediaReadinessError("MEDIA_SYMLINK_REJECTED: {}".format(path))
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise MediaReadinessError("MEDIA_OUTSIDE_TASK_ROOT: {}".format(path)) from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise MediaReadinessError("MEDIA_SYMLINK_REJECTED: {}".format(cursor))
    return resolved


@dataclass(frozen=True)
class RegisteredMedia:
    manifest: MediaManifest
    frames: Mapping[int, Mapping[str, Any]]
    decoder: str
    transfer_limit_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MEDIA_READINESS_SCHEMA,
            "manifest": self.manifest.to_dict(),
            "frames": {str(key): dict(value) for key, value in sorted(self.frames.items())},
            "decoder": self.decoder,
            "transfer_limit_bytes": self.transfer_limit_bytes,
            "model_called": False,
        }


class LocalMediaRegistrar:
    """Register only immutable local files beneath an explicit task root."""

    def __init__(self, root: Path, *, decoder: FixedPngDecoder | None = None) -> None:
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise MediaReadinessError("MEDIA_ROOT_SYMLINK_REJECTED")
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise MediaReadinessError("MEDIA_ROOT_SYMLINK_REJECTED")
        self.decoder = decoder or FixedPngDecoder()

    def _decode(self, path: Path) -> tuple[Path, dict[str, Any]]:
        safe = _safe_task_path(self.root, path)
        return safe, self.decoder.decode(safe)

    def register_image(self, asset_id: str, path: Path) -> RegisteredMedia:
        safe, decoded = self._decode(path)
        asset = MediaAsset(
            asset_id=str(asset_id), kind="image", uri=str(safe),
            sha256=str(decoded["sha256"]), width=int(decoded["width"]),
            height=int(decoded["height"]),
        )
        return RegisteredMedia(
            manifest=MediaManifest((asset,)), frames={0: decoded},
            decoder=self.decoder.name, transfer_limit_bytes=self.decoder.max_bytes,
        )

    def register_sequence(self, asset_id: str, frames: Mapping[int, Path] | Sequence[Path], *,
                          start_frame: int = 1, fps: float | None = None) -> RegisteredMedia:
        if isinstance(frames, Mapping):
            entries = [(int(frame), Path(path)) for frame, path in frames.items()]
        else:
            entries = [(int(start_frame) + index, Path(path)) for index, path in enumerate(frames)]
        entries.sort(key=lambda item: item[0])
        if not entries or len(entries) > MAX_FRAMES_PER_OPERATION:
            raise MediaReadinessError("MEDIA_SEQUENCE_FRAME_LIMIT")
        frame_receipts: dict[int, dict[str, Any]] = {}
        for frame, path in entries:
            if frame in frame_receipts:
                raise MediaReadinessError("MEDIA_SEQUENCE_DUPLICATE_FRAME")
            _safe, decoded = self._decode(path)
            if frame_receipts:
                first = next(iter(frame_receipts.values()))
                if (decoded["width"], decoded["height"], decoded["format"]) != (first["width"], first["height"], first["format"]):
                    raise MediaReadinessError("MEDIA_SEQUENCE_FORMAT_MISMATCH")
            frame_receipts[frame] = decoded
        numbers = list(frame_receipts)
        step = numbers[1] - numbers[0] if len(numbers) > 1 else 1
        if step <= 0 or any(right - left != step for left, right in zip(numbers, numbers[1:])):
            raise MediaReadinessError("MEDIA_SEQUENCE_FRAME_RANGE_INVALID")
        aggregate = hashlib.sha256(json.dumps(
            [[frame, frame_receipts[frame]["sha256"]] for frame in numbers],
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        first = next(iter(frame_receipts.values()))
        uri = "sequence:" + str(self.root / str(asset_id))
        asset = MediaAsset(
            asset_id=str(asset_id), kind="sequence", uri=uri, sha256=aggregate,
            frame_range=(numbers[0], numbers[-1], step), fps=fps,
            width=int(first["width"]), height=int(first["height"]),
        )
        return RegisteredMedia(
            manifest=MediaManifest((asset,)), frames=frame_receipts,
            decoder=self.decoder.name, transfer_limit_bytes=self.decoder.max_bytes,
        )


def reference_observations(registered: RegisteredMedia) -> dict[str, Any]:
    """Return identity-only observations; no semantic or model inference."""
    assets = [asset.to_dict() for asset in registered.manifest.assets]
    return {
        "schema": "bridge.full_readiness.reference_observations/1.0",
        "source": "local_registered_media",
        "assets": assets,
        "frame_count": len(registered.frames),
        "model_called": False,
        "semantic_inference": False,
        "claims": [],
    }


class ActiveFrameDiagnostics:
    """Mechanical exact-frame, freshness, duplicate, and frozen-frame checks."""

    def inspect(self, frame_paths: Mapping[int, Path], *, expected_frames: Sequence[int],
                active_frames: Sequence[int] = (), not_before: float | None = None,
                min_bytes: int = 1) -> dict[str, Any]:
        expected = [int(item) for item in expected_frames]
        active = sorted({int(item) for item in (active_frames or expected)})
        missing: list[int] = []
        unreadable: list[int] = []
        stale: list[int] = []
        hashes: dict[int, str] = {}
        sizes: dict[int, int] = {}
        for frame in expected:
            path = Path(frame_paths.get(frame, ""))
            try:
                digest, size = _sha256_file(path, max_bytes=DEFAULT_MAX_TRANSFER_BYTES)
            except (OSError, MediaReadinessError):
                if not path.is_file():
                    missing.append(frame)
                else:
                    unreadable.append(frame)
                continue
            if size < min_bytes:
                unreadable.append(frame)
                continue
            if not_before is not None and path.stat().st_mtime < float(not_before):
                stale.append(frame)
            hashes[frame] = digest
            sizes[frame] = size
        seen: dict[str, int] = {}
        duplicate_frames: list[int] = []
        for frame in expected:
            digest = hashes.get(frame)
            if not digest:
                continue
            if digest in seen:
                duplicate_frames.append(frame)
            else:
                seen[digest] = frame
        active_duplicates = [frame for frame in duplicate_frames if frame in set(active)]
        active_hashes = [hashes[frame] for frame in active if frame in hashes]
        frozen = bool(len(active) > 1 and len(active_hashes) == len(active) and len(set(active_hashes)) == 1)
        ok = not missing and not unreadable and not stale and not active_duplicates and not frozen
        return {
            "schema": "bridge.full_readiness.active_frames/1.0",
            "status": "PASS" if ok else "BLOCKED",
            "expected_frames": expected,
            "active_frames": active,
            "missing": missing,
            "unreadable": unreadable,
            "stale": stale,
            "duplicate_frames": duplicate_frames,
            "active_duplicate_frames": active_duplicates,
            "frozen_active": frozen,
            "hashes": {str(frame): digest for frame, digest in sorted(hashes.items())},
            "sizes": {str(frame): size for frame, size in sorted(sizes.items())},
        }


class DiskBudgetWatchdog:
    """Preflight/runtime budget checks that request a stop but never delete."""

    def __init__(self, root: Path, *, max_bytes: int, max_frames: int = MAX_FRAMES_PER_OPERATION,
                 max_seconds: float = MAX_OPERATION_SECONDS) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or max_bytes <= 0 or max_frames <= 0 or max_seconds <= 0:
            raise ValueError("disk watchdog limits/root are invalid")
        self.max_bytes = int(max_bytes)
        self.max_frames = int(max_frames)
        self.max_seconds = float(max_seconds)
        self.stop_requested = False

    def usage_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                total += int(path.stat().st_size)
        return total

    def check(self, *, estimated_bytes: int = 0, frames: int = 0,
              elapsed_seconds: float = 0.0, phase: str = "preflight") -> dict[str, Any]:
        usage = self.usage_bytes()
        reasons: list[str] = []
        if usage + max(0, int(estimated_bytes)) > self.max_bytes:
            reasons.append("DISK_BUDGET_EXCEEDED")
        if int(frames) > self.max_frames:
            reasons.append("FRAME_LIMIT_EXCEEDED")
        if float(elapsed_seconds) > self.max_seconds:
            reasons.append("TIME_LIMIT_EXCEEDED")
        if reasons:
            self.stop_requested = True
        return {
            "schema": "bridge.full_readiness.disk_budget/1.0",
            "phase": str(phase),
            "status": "STOP_REQUESTED" if reasons else "PASS",
            "reasons": reasons,
            "usage_bytes": usage,
            "estimated_bytes": max(0, int(estimated_bytes)),
            "limit_bytes": self.max_bytes,
            "frames": int(frames), "max_frames": self.max_frames,
            "elapsed_seconds": float(elapsed_seconds), "max_seconds": self.max_seconds,
            "stop_requested": self.stop_requested,
            "deleted_paths": [],
        }

    def preflight(self, **kwargs: Any) -> dict[str, Any]:
        return self.check(phase="preflight", **kwargs)

    def runtime_check(self, **kwargs: Any) -> dict[str, Any]:
        return self.check(phase="runtime", **kwargs)

    def enforce(self, **kwargs: Any) -> dict[str, Any]:
        receipt = self.runtime_check(**kwargs)
        if receipt["status"] != "PASS":
            raise DiskBudgetExceeded(";".join(receipt["reasons"]))
        return receipt


def apply_feedback_invalidation(pack: DomainPack, control_name: str, value: Any) -> dict[str, Any]:
    """Validate one semantic control and return explicit downstream invalidation."""
    control = pack.control_map.get(str(control_name))
    if control is None:
        raise MediaReadinessError("UNKNOWN_SEMANTIC_CONTROL: {}".format(control_name))
    validated = control.validate(value)
    if isinstance(validated, tuple):
        validated = list(validated)
    return {
        "schema": "bridge.full_readiness.feedback_invalidation/1.0",
        "status": "INVALIDATED",
        "domain_pack": pack.identifier,
        "control": control.name,
        "value": validated,
        "invalidates_stage_nodes": list(control.invalidates_stage_nodes),
        "invalidates_components": list(control.invalidates_components),
        "requires_simulation_cache": bool(control.requires_simulation_cache),
        "cache_confirmation_required": bool(control.requires_simulation_cache),
        "render_revalidation_required": True,
        "model_called": False,
    }


def confirm_cache_contract(frame_paths: Mapping[int, Path], *, expected_frames: Sequence[int],
                           active_frames: Sequence[int], colorspace: str,
                           premultiplied: bool, dependencies: Sequence[str],
                           not_before: float | None = None) -> dict[str, Any]:
    """Confirm only the mechanical cache prerequisites, not a real simulation."""
    diagnostics = ActiveFrameDiagnostics().inspect(
        frame_paths, expected_frames=expected_frames, active_frames=active_frames,
        not_before=not_before,
    )
    metadata = bool(str(colorspace).strip()) and type(premultiplied) is bool
    dependencies_present = bool(dependencies) and all(str(item).strip() for item in dependencies)
    confirmed = diagnostics["status"] == "PASS" and metadata and dependencies_present
    return {
        "schema": "bridge.full_readiness.cache_confirmation/1.0",
        "status": "PASS" if confirmed else "BLOCKED",
        "confirmed": confirmed,
        "mechanical_only": True,
        "simulation_executed": False,
        "visual_verified": False,
        "metadata_present": metadata,
        "dependencies_present": dependencies_present,
        "diagnostics": diagnostics,
    }
