"""Pure denoise amount validation and scanline sample mixing.

The controller must inject its configured artifact and validated operation
sources. This helper compares their facts; it cannot authenticate a receipt,
establish producer existence independently, write an EXR, or publish output.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from .artifact_registry import frame_path

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, dict) and bool(value), label + " is required")
    return value


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _finite_json(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must contain finite JSON facts") from exc


def _header(image: Any) -> tuple[Any, ...]:
    image = _mapping(image, "decoded EXR metadata")
    width, height = image.get("width"), image.get("height")
    _require(type(width) is int and type(height) is int and width > 0 and height > 0
             and width * height <= 100_000_000, "invalid EXR dimensions")
    names = image.get("channels")
    _require(isinstance(names, list) and bool(names) and all(_text(n) for n in names)
             and len(set(names)) == len(names), "invalid EXR channel names")
    layout = _mapping(image.get("channel_layout"), "typed EXR channel layout")
    channels = layout.get("channels")
    _require(isinstance(channels, list) and len(channels) == len(names), "incomplete typed channel layout")
    for name, channel in zip(names, channels):
        _require(isinstance(channel, dict) and channel.get("name") == name
                 and type(channel.get("pixel_type")) is int and channel["pixel_type"] in (0, 1, 2)
                 and type(channel.get("p_linear")) is int and channel["p_linear"] in (0, 1)
                 and type(channel.get("x_sampling")) is int and channel["x_sampling"] == 1
                 and type(channel.get("y_sampling")) is int and channel["y_sampling"] == 1,
                 "invalid or unsupported typed channel layout")
    for key in ("data_window", "display_window"):
        window = layout.get(key)
        _require(isinstance(window, (list, tuple)) and len(window) == 4
                 and all(type(v) is int for v in window)
                 and window[2] >= window[0] and window[3] >= window[1], "invalid EXR " + key)
    window = layout["data_window"]
    _require(window[2] - window[0] + 1 == width and window[3] - window[1] + 1 == height,
             "EXR dimensions differ from data window")
    _require(type(image.get("pixel_count")) is int and image["pixel_count"] == width * height
             and type(image.get("sample_count")) is int
             and image["sample_count"] == width * height * len(names)
             and image.get("structural_validated") is True, "EXR sample coverage is unverified")
    return width, height, names, layout


def _lookup(source, identity: str, label: str) -> Mapping[str, Any]:
    try:
        value = source(identity)
    except Exception as exc:
        raise ValueError(label + " lookup failed") from exc
    value = _mapping(value, label)
    _finite_json(value, label)
    return value


def _dependency(entry, expected, *, denoised: bool):
    entry = _mapping(entry, "registered artifact")
    _finite_json(entry, "registered artifact")
    artifact_key = "denoised_artifact_id" if denoised else "source_artifact_id"
    version_key = "denoised_version" if denoised else "source_version"
    operation_key = "denoise_operation_id" if denoised else "source_operation_id"
    artifact_id, operation_id = expected[artifact_key], expected[operation_key]
    _require(entry == _lookup(expected["artifact_source"], artifact_id, "controller artifact"),
             "artifact differs from current controller ledger entry")
    _require(entry.get("artifact_id") == artifact_id and type(entry.get("version")) is int
             and entry["version"] == expected[version_key]
             and entry.get("operation_id") == operation_id
             and entry.get("task_id") == expected["task_id"]
             and entry.get("scene_fingerprint") == expected["scene_fingerprint"]
             and entry.get("artifact_class") in ("preview_temp", "confirmed_cache", "final_delivery")
             and _sha(entry.get("operation_receipt_sha256")), "artifact identity is not bound")
    _require(_text(entry.get("colorspace")) and type(entry.get("premultiplied")) is bool,
             "explicit colorspace and premultiplication are required")
    frames = entry.get("frame_set")
    _require(isinstance(frames, list) and bool(frames)
             and all(type(f) is int and f > 0 for f in frames)
             and len(set(frames)) == len(frames) and expected["frame"] in frames,
             "artifact frame is not bound")
    producer = _lookup(expected["operation_source"], operation_id, "controller producer")
    _require(producer.get("operation_id") == operation_id and producer.get("state") == "COMPLETED"
             and producer.get("stop_confirmed") is True and _text(producer.get("execution_kind"))
             and producer.get("task_id") == entry["task_id"]
             and producer.get("scene_fingerprint") == entry["scene_fingerprint"]
             and producer.get("frame_set") == frames and producer.get("output_pattern") == entry.get("pattern")
             and producer.get("operation_receipt_sha256") == entry["operation_receipt_sha256"],
             "completed runtime producer is not bound to artifact")
    payload = _mapping(entry.get("payload"), "artifact completion payload")
    snapshots = _mapping(payload.get("completion_snapshot"), "completion snapshot")
    metadata = _mapping(payload.get("completion_metadata"), "completion metadata")
    _require(snapshots == (producer.get("frame_snapshots") or producer.get("output_snapshot"))
             and metadata == producer.get("metadata"), "completion evidence differs from producer facts")
    dependencies = payload.get("completion_dependencies")
    _require(isinstance(dependencies, list) and all(_text(d) for d in dependencies)
             and dependencies == producer.get("dependencies"), "completion dependencies are not bound")
    _require(isinstance(entry.get("dependencies"), list)
             and all(_text(d) for d in entry["dependencies"]), "registered dependencies are missing")
    frame = str(expected["frame"])
    snapshot = _mapping(snapshots.get(frame), "frame completion snapshot")
    _require(_text(snapshot.get("path")) and Path(snapshot["path"]).is_absolute()
             and _text(entry.get("pattern")) and Path(entry["pattern"]).is_absolute()
             and snapshot["path"] == str(frame_path(entry["pattern"], expected["frame"]))
             and type(snapshot.get("bytes")) is int and snapshot["bytes"] > 0
             and type(snapshot.get("modified_ns")) is int and snapshot["modified_ns"] > 0
             and _sha(snapshot.get("sha256")), "frame output snapshot is invalid")
    image = _mapping(metadata.get(frame), "actual frame EXR metadata")
    header = _header(image)
    _require(image.get("sha256") == snapshot["sha256"]
             and image.get("colorspace") == entry["colorspace"]
             and type(image.get("premultiplied")) is bool
             and image["premultiplied"] == entry["premultiplied"], "actual output metadata is not bound")
    return snapshot, metadata, header, dependencies


def validate_dependency_pair(raw_fact, denoised_fact, expected_identity) -> None:
    """Compare actual registered outputs using controller-configured sources.

    ``raw_fact`` and ``denoised_fact`` are ArtifactRegistry lookup entries.
    ``expected_identity`` contains controller-injected ``artifact_source(id)``
    and ``operation_source(id)`` callables, plus task_id, frame,
    scene_fingerprint, source_artifact_id, source_version, source_operation_id,
    source_sha256, denoised_artifact_id, denoised_version, denoise_operation_id.
    These callables must never come from a model/tool request or JSON payload;
    their receipt authentication and invalidation checks belong to the controller.

    The operation source provides an already validated completed runtime fact.
    Its actual metadata is copied by ArtifactRegistry to completion_metadata:
    the string frame key holds codec metadata plus sha256/colorspace/premultiplied.
    The denoise producer additionally records metadata.source with the consumed
    raw artifact_id/version/operation_id/operation_receipt_sha256/task_id/frame/
    scene_fingerprint/sha256. That source version is the raw content version;
    the denoised artifact has its own independently allocated ledger version.
    Both the ledger and producer dependency lists include artifact:<raw id>.
    This function returns no receipt or authorization.
    """
    expected = _mapping(expected_identity, "controller expected identity")
    for field in ("task_id", "source_artifact_id", "source_operation_id",
                  "denoised_artifact_id", "denoise_operation_id"):
        _require(_text(expected.get(field)), "missing controller identity: " + field)
    for field in ("frame", "source_version", "denoised_version"):
        _require(type(expected.get(field)) is int and expected[field] > 0,
                 "missing controller identity: " + field)
    for field in ("scene_fingerprint", "source_sha256"):
        _require(_sha(expected.get(field)), "missing controller SHA-256: " + field)
    for field in ("artifact_source", "operation_source"):
        _require(callable(expected.get(field)), "controller-configured source required: " + field)
    _require(expected["source_artifact_id"] != expected["denoised_artifact_id"]
             and expected["source_operation_id"] != expected["denoise_operation_id"],
             "denoised output requires its own artifact and producing operation")
    raw_snapshot, _, raw_header, _ = _dependency(raw_fact, expected, denoised=False)
    _, denoised_metadata, denoised_header, dependencies = _dependency(denoised_fact, expected, denoised=True)
    _require(raw_snapshot["sha256"] == expected["source_sha256"], "raw source bytes differ from frozen identity")
    _require(raw_header == denoised_header and raw_fact["colorspace"] == denoised_fact["colorspace"]
             and raw_fact["premultiplied"] == denoised_fact["premultiplied"], "raw and denoised image layouts differ")
    source = _mapping(denoised_metadata.get("source"), "consumed raw source identity")
    bound = {"artifact_id": raw_fact["artifact_id"], "version": raw_fact["version"],
             "operation_id": raw_fact["operation_id"], "operation_receipt_sha256": raw_fact["operation_receipt_sha256"],
             "task_id": raw_fact["task_id"], "frame": expected["frame"],
             "scene_fingerprint": raw_fact["scene_fingerprint"], "sha256": raw_snapshot["sha256"]}
    _require(all(type(source.get(key)) is type(value) and source.get(key) == value
                 for key, value in bound.items()), "denoised producer consumed a different raw source")
    dependency = "artifact:" + raw_fact["artifact_id"]
    _require(dependency in dependencies and dependency in denoised_fact["dependencies"],
             "denoised producer is missing the registered raw dependency")


def _rows(image, header):
    width, height, names, layout = header
    rows = image.get("rows")
    _require(isinstance(rows, list) and len(rows) == height, "incomplete decoded pixel rows")
    first_y = layout["data_window"][1]
    for index, row in enumerate(rows):
        _require(isinstance(row, dict) and type(row.get("y")) is int and row["y"] == first_y + index,
                 "pixel rows do not cover the data window")
        channels = row.get("channels")
        _require(isinstance(channels, dict) and set(channels) == set(names), "pixel channel names differ")
        for channel in layout["channels"]:
            values = channels[channel["name"]]
            _require(isinstance(values, list) and len(values) == width, "pixel channel sample count differs")
            for value in values:
                try:
                    valid = type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    valid = False
                _require(valid, "pixel samples must be finite numbers")
                if channel["pixel_type"] == 0:
                    _require(type(value) is int and 0 <= value <= 0xFFFFFFFF, "invalid UINT EXR sample")
    return rows


def blend_pixels(raw_pixels, denoised_pixels, amount) -> list[dict[str, Any]]:
    """Return new codec-shaped rows with raw*(1-a)+denoised*a samples.

    Inputs are read_exr(..., with_pixels=True) mappings with actual typed
    channel_layout. UINT samples and alpha (A/alpha, including layer suffixes)
    must match exactly and are copied from raw. Inputs are never modified. Returned rows
    are values only; this function performs no file or executable operation.
    """
    _require(type(amount) in (int, float), "denoise amount must be numeric")
    try:
        valid_amount = math.isfinite(amount) and 0 <= amount <= 1
    except OverflowError:
        valid_amount = False
    _require(valid_amount, "denoise amount must be finite and within [0, 1]")
    raw_header, denoised_header = _header(raw_pixels), _header(denoised_pixels)
    _require(raw_header == denoised_header, "raw and denoised pixel layouts differ")
    raw_rows, denoised_rows = _rows(raw_pixels, raw_header), _rows(denoised_pixels, denoised_header)
    result = []
    for raw, denoised in zip(raw_rows, denoised_rows):
        channels = {}
        for channel in raw_header[3]["channels"]:
            name = channel["name"]
            raw_values, denoised_values = raw["channels"][name], denoised["channels"][name]
            uint = channel["pixel_type"] == 0
            alpha = name.rsplit(".", 1)[-1].lower() in ("a", "alpha")
            if uint:
                _require(raw_values == denoised_values, "denoised UINT differs from raw UINT")
            if alpha:
                _require(raw_values == denoised_values, "denoised alpha differs from raw alpha")
            if uint or alpha or amount == 0:
                values = list(raw_values)
            elif amount == 1:
                values = list(denoised_values)
            else:
                values = [raw_value * (1 - amount) + denoised_value * amount
                          for raw_value, denoised_value in zip(raw_values, denoised_values)]
            _require(all(math.isfinite(v) for v in values), "blended samples must remain finite")
            channels[name] = values
        result.append({"y": raw["y"], "channels": channels})
    return result
