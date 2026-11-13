"""Produce a bounded blended EXR from current controller-owned dependencies.

This is a single-frame byte producer, not a denoiser or operation authority.
The controller must authenticate the two upstream operation sources, own the
output destination, persist its own blend operation, and register its output.
No native executable, worker, transport, facade, or operation is created here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
from typing import Any, Mapping, TypedDict

from .artifact_registry import ArtifactRegistry, frame_path
from .denoise_blend import blend_pixels, validate_dependency_pair
from .exr_codec import read_exr, write_exr


class DenoiseOutputBlocked(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


class DenoiseOutputReceipt(TypedDict):
    schema: str
    task_id: str
    scene_fingerprint: str
    frame_set: list[int]
    output_pattern: str
    amount: float
    frame_snapshots: dict[str, dict[str, Any]]
    metadata: dict[str, Any]
    dependencies: list[str]
    dependency_summary: dict[str, Any]
    dependency_summary_sha256: str
    denoise_blend: dict[str, Any]


def _json_copy(value):
    return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))


def _digest(value) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _publish_frame(staged: Path, target: Path) -> None:
    os.link(staged, target)


def registry_completion_metadata(receipt: DenoiseOutputReceipt) -> dict[str, dict[str, Any]]:
    """Return pure frame metadata after verifying the actual output snapshot.

    Keep receipt.denoise_blend with the owned operation's separate binding;
    it contains formula, amount and dependency summary. This adapter neither
    changes the receipt nor supplies state, operation identity or AVAILABLE.
    The controller must normalize metadata before persisting its own operation
    and registering it. Color/premultiplication remain explicit declarations.
    """
    bound = _json_copy(receipt)
    frames = bound.get("frame_set")
    if (not isinstance(frames, list) or len(frames) != 1
            or type(frames[0]) is not int or frames[0] <= 0):
        raise ValueError("single exact output frame required")
    frame = str(frames[0])
    snapshots, metadata = bound.get("frame_snapshots"), bound.get("metadata")
    if (not isinstance(snapshots, dict) or set(snapshots) != {frame}
            or not isinstance(metadata, dict) or frame not in metadata
            or set(metadata) - {frame, "denoise_blend"}):
        raise ValueError("exact frame snapshot and metadata coverage required")
    blend, summary = bound.get("denoise_blend"), bound.get("dependency_summary")
    amount = bound.get("amount")
    if (not isinstance(blend, dict) or not isinstance(summary, dict) or not summary
            or type(amount) not in (int, float) or not 0 <= amount <= 1
            or blend.get("formula") != "raw*(1-amount)+denoised*amount"
            or type(blend.get("amount")) not in (int, float) or blend["amount"] != amount
            or blend.get("dependency_summary") != summary
            or blend.get("dependency_summary_sha256") != _digest(summary)
            or bound.get("dependency_summary_sha256") != _digest(summary)
            or ("denoise_blend" in metadata and metadata["denoise_blend"] != blend)):
        raise ValueError("separate denoise blend binding differs")
    snapshot, declared = snapshots[frame], metadata[frame]
    if not isinstance(snapshot, dict) or not isinstance(declared, dict):
        raise ValueError("typed output snapshot and metadata required")
    name, pattern = snapshot.get("path"), bound.get("output_pattern")
    if (not isinstance(name, str) or not Path(name).is_absolute()
            or not isinstance(pattern, str) or not Path(pattern).is_absolute()
            or str(frame_path(pattern, frames[0])) != name
            or type(snapshot.get("bytes")) is not int or not 0 < snapshot["bytes"] <= 512 * 1024 * 1024
            or type(snapshot.get("modified_ns")) is not int or snapshot["modified_ns"] <= 0
            or not isinstance(snapshot.get("sha256"), str) or len(snapshot["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in snapshot["sha256"])
            or not isinstance(declared.get("colorspace"), str) or not declared["colorspace"].strip()
            or type(declared.get("premultiplied")) is not bool or "rows" in declared):
        raise ValueError("output snapshot or color declaration is invalid")
    path = Path(name)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if path.is_symlink():
        raise ValueError("regular output bytes required")
    with tempfile.TemporaryDirectory(prefix=".denoise-metadata-", dir=path.parent) as directory:
        copy = Path(directory) / "verified.exr"
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source, copy.open("wb") as target:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_size != snapshot["bytes"]
                    or before.st_mtime_ns != snapshot["modified_ns"]):
                raise ValueError("output snapshot changed")
            digest, size = hashlib.sha256(), 0
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                size += len(chunk)
                if size > snapshot["bytes"]:
                    raise ValueError("output bytes exceed snapshot")
                digest.update(chunk)
                target.write(chunk)
            after = os.fstat(source.fileno())
        if (size != snapshot["bytes"] or digest.hexdigest() != snapshot["sha256"]
                or identity(before) != identity(after) or identity(before) != identity(path.lstat())):
            raise ValueError("output bytes differ from snapshot")
        decoded = read_exr(copy, with_pixels=True)
        actual = {key: value for key, value in decoded.items() if key != "rows"}
        if (any(declared.get(key) != value for key, value in actual.items())
                or declared.get("sha256") != snapshot["sha256"]
                or any(key in declared and declared[key] != snapshot[key]
                       for key in ("path", "bytes", "modified_ns"))
                or identity(before) != identity(path.lstat())):
            raise ValueError("decoded output metadata differs from receipt")
    return {frame: {**actual, **{key: snapshot[key] for key in ("path", "bytes", "modified_ns", "sha256")},
                    "colorspace": declared["colorspace"], "premultiplied": declared["premultiplied"]}}


def _write_blended_frame(path: Path, raw_image, denoised_image, amount):
    """Byte-only computation; decoded fixtures confer no upstream authority."""
    if raw_image.get("header_fields") != denoised_image.get("header_fields"):
        raise ValueError("raw and denoised EXR view headers differ")
    rows = blend_pixels(raw_image, denoised_image, amount)
    written = write_exr(path, raw_image, rows)
    actual = read_exr(path, with_pixels=True)
    metadata = {key: value for key, value in actual.items() if key != "rows"}
    if metadata != {key: value for key, value in written.items()
                    if key not in ("path", "bytes", "sha256")}:
        raise ValueError("blended EXR readback metadata differs")
    for expected, decoded in zip(rows, actual["rows"]):
        if decoded["y"] != expected["y"]:
            raise ValueError("blended EXR readback scanline differs")
        for channel in actual["channel_layout"]["channels"]:
            name = channel["name"]
            sample_format = {0: "<I", 1: "<e", 2: "<f"}[channel["pixel_type"]]
            quantized = [struct.unpack(sample_format, struct.pack(sample_format, value))[0]
                         for value in expected["channels"][name]]
            if decoded["channels"][name] != quantized:
                raise ValueError("blended EXR quantized samples differ")
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if (identity(before) != identity(after) or after.st_size != written["bytes"]
            or digest != written["sha256"]):
        raise ValueError("blended EXR bytes changed during readback")
    return {"path": str(path), "bytes": after.st_size, "modified_ns": after.st_mtime_ns,
            "sha256": digest}, {**metadata, "sha256": digest}


def _current_pair(registry, expected):
    entries = []
    for role, key in (("RAW", "source_artifact_id"), ("DENOISED", "denoised_artifact_id")):
        identity = expected.get(key)
        if not isinstance(identity, str) or not identity.strip():
            raise DenoiseOutputBlocked(role + "_ARTIFACT_UNAVAILABLE", "controller artifact ID required")
        try:
            entry = registry.lookup(identity)
        except ValueError as exc:
            raise DenoiseOutputBlocked(role + "_ARTIFACT_UNAVAILABLE", str(exc)) from exc
        if entry is None:
            raise DenoiseOutputBlocked(role + "_ARTIFACT_UNAVAILABLE", identity)
        entries.append(_json_copy(entry))
    try:
        validate_dependency_pair(*entries, expected)
    except ValueError as exc:
        raise DenoiseOutputBlocked("DEPENDENCY_PAIR_INVALID", str(exc)) from exc
    return entries


def _consume_frame(registry, entry, frame):
    consumed = registry.read_frame(entry["artifact_id"], frame)
    snapshot = entry["payload"]["completion_snapshot"][str(frame)]
    bound = {"artifact_id": entry["artifact_id"], "version": entry["version"],
             "operation_id": entry["operation_id"], "frame": frame,
             "sha256": snapshot["sha256"], "bytes": snapshot["bytes"]}
    if any(type(consumed.get(key)) is not type(value) or consumed.get(key) != value
           for key, value in bound.items()):
        raise DenoiseOutputBlocked("CONSUMED_IDENTITY_CHANGED", entry["artifact_id"])
    image = consumed["image"]
    metadata = entry["payload"]["completion_metadata"][str(frame)]
    for key, value in image.items():
        if key != "rows" and metadata.get(key) != value:
            raise DenoiseOutputBlocked("CONSUMED_METADATA_CHANGED", key)
    return image


def produce_denoise_output(*, registry: ArtifactRegistry, expected_identity: Mapping[str, Any],
                          amount: float, output_path: Path) -> DenoiseOutputReceipt:
    """Validate, consume, blend, write and read back one registered EXR frame.

    expected_identity follows validate_dependency_pair, except artifact_source
    is always supplied from registry.lookup. Its operation_source must be a
    controller-configured authenticated query for the approved raw and
    OIDN/OptiX producers, never a tool/model payload. This module does not
    establish the denoiser's algorithm from an execution-kind label.
    read_frame supplies actual SHA-bound pixels. Existing destinations are
    refused; publication uses an exclusive hard link on the same filesystem.

    The receipt carries layout, exact frame, declared color/premultiplication,
    output bytes and both consumed version/operation/content summaries. It
    intentionally has no COMPLETED state, operation ID, signature, artifact
    version or PASS label. The controller must bind it to its real owned
    operation before ArtifactRegistry.register; Nuke integration is separate.
    Color/premultiplication are ledger declarations, not EXR header attributes.
    """
    if not isinstance(registry, ArtifactRegistry) or not isinstance(expected_identity, Mapping):
        raise DenoiseOutputBlocked("CONTROLLER_SOURCES_REQUIRED", "registry and expected identity required")
    expected = dict(expected_identity)
    expected["artifact_source"] = registry.lookup
    entries = _current_pair(registry, expected)
    frame = expected["frame"]
    target = Path(output_path)
    if (not target.is_absolute() or target.suffix.lower() != ".exr"
            or frame_path(str(target), frame) != target or not target.parent.is_dir()
            or target.exists() or target.is_symlink()):
        raise DenoiseOutputBlocked("OUTPUT_DESTINATION_INVALID", "new absolute single-frame EXR path required")
    raw_image, denoised_image = [_consume_frame(registry, entry, frame) for entry in entries]
    if _current_pair(registry, expected) != entries:
        raise DenoiseOutputBlocked("DEPENDENCIES_CHANGED", "during pixel consumption")
    summary = {}
    for role, entry in zip(("raw", "denoised"), entries):
        summary[role] = {key: entry[key] for key in
                         ("artifact_id", "version", "operation_id", "operation_receipt_sha256",
                          "task_id", "scene_fingerprint", "colorspace", "premultiplied")}
        summary[role].update(frame=frame, snapshot=entry["payload"]["completion_snapshot"][str(frame)])
    dependencies = sorted({"artifact:" + entry["artifact_id"] for entry in entries}
                          | {dependency for entry in entries for dependency in entry["dependencies"]})
    with tempfile.TemporaryDirectory(prefix=".denoise-output-", dir=target.parent) as directory:
        staged = Path(directory) / "mixed.exr"
        snapshot, metadata = _write_blended_frame(staged, raw_image, denoised_image, amount)
        if _current_pair(registry, expected) != entries:
            raise DenoiseOutputBlocked("DEPENDENCIES_CHANGED", "before output publication")
        metadata.update(colorspace=entries[0]["colorspace"], premultiplied=entries[0]["premultiplied"])
        receipt: DenoiseOutputReceipt = {
            "schema": "bridge.denoise-output.v1", "task_id": expected["task_id"],
            "scene_fingerprint": expected["scene_fingerprint"], "frame_set": [frame],
            "output_pattern": str(target), "amount": float(amount),
            "frame_snapshots": {str(frame): {**snapshot, "path": str(target)}},
            "metadata": {str(frame): metadata, "denoise_blend": {
                "formula": "raw*(1-amount)+denoised*amount", "amount": float(amount),
                "dependency_summary": summary, "dependency_summary_sha256": _digest(summary)}},
            "dependencies": dependencies, "dependency_summary": summary,
            "dependency_summary_sha256": _digest(summary),
        }
        receipt["denoise_blend"] = _json_copy(receipt["metadata"]["denoise_blend"])
        _publish_frame(staged, target)
    return receipt
