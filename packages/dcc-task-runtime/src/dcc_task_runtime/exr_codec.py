"""Bounded scanline OpenEXR decoder (NONE/ZIPS/ZIP) and typed NONE writer.

ZIP reconstruction follows OpenEXRCore internal_zip.c. Block coverage,
channel payloads and byte ranges are validated before samples are exposed.
"""

from __future__ import annotations

import struct
import zlib
import hashlib
import math
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO


MAGIC = b"\x76\x2f\x31\x01"
VERSION = 2
_MAX_WINDOW_COORDINATE = 0x7FFFFFFF // 2 - 1
_MIN_PIXEL_ASPECT_RATIO = struct.unpack("<f", struct.pack("<f", 1e-6))[0]


class ExrDecodeError(ValueError):
    """Raised when an EXR is structurally incomplete or unsupported."""


def _window_size(box, label: str) -> tuple[int, int]:
    # OpenEXR 3.4.15's native check reserves arithmetic headroom at
    # both ends of signed int coordinates. Python keeps span arithmetic wide.
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(v) is not int or not -_MAX_WINDOW_COORDINATE <= v <= _MAX_WINDOW_COORDINATE for v in box)
            or box[2] < box[0] or box[3] < box[1]):
        raise ExrDecodeError("invalid EXR " + label)
    width, height = box[2] - box[0] + 1, box[3] - box[1] + 1
    if not 0 < width <= 0x7FFFFFFF or not 0 < height <= 0x7FFFFFFF:
        raise ExrDecodeError("EXR " + label + " span exceeds signed int range")
    return width, height


def _validate_view(aspect: float, screen_width: float) -> None:
    if not _MIN_PIXEL_ASPECT_RATIO <= aspect <= 1e6 or screen_width < 0:
        raise ExrDecodeError("invalid EXR pixel aspect ratio or screen window width")


def _cstring(data: bytes, cursor: int, *, label: str) -> tuple[str, int]:
    end = data.find(b"\0", cursor)
    if end < 0:
        raise ExrDecodeError(f"truncated {label}")
    try:
        value = data[cursor:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ExrDecodeError(f"invalid {label}") from exc
    return value, end + 1


def _attribute(name: str, kind: str, payload: bytes) -> bytes:
    return (
        name.encode("ascii")
        + b"\0"
        + kind.encode("ascii")
        + b"\0"
        + struct.pack("<I", len(payload))
        + payload
    )


def encode_tiny_exr(sample: float = 1.0) -> bytes:
    """Return a valid 1x1, single-channel, uncompressed scanline EXR."""

    channels = (
        b"R\0"
        + struct.pack("<i", 1)  # HALF
        + b"\0\0\0\0"  # pLinear/reserved
        + struct.pack("<ii", 1, 1)
        + b"\0"
    )
    box = struct.pack("<iiii", 0, 0, 0, 0)
    header = b"".join(
        (
            _attribute("channels", "chlist", channels),
            _attribute("dataWindow", "box2i", box),
            _attribute("displayWindow", "box2i", box),
            _attribute("lineOrder", "lineOrder", b"\0"),
            _attribute("compression", "compression", b"\0"),
            _attribute("pixelAspectRatio", "float", struct.pack("<f", 1.0)),
            _attribute("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0)),
            _attribute("screenWindowWidth", "float", struct.pack("<f", 1.0)),
            _attribute("comments", "string", b"bridge-tiny-exr" + b"x" * 1900),
            b"\0",
        )
    )
    scanline = struct.pack("<iI", 0, 2) + struct.pack("<e", float(sample))
    offset = 4 + 4 + len(header) + 8
    return MAGIC + struct.pack("<I", VERSION) + header + struct.pack("<Q", offset) + scanline


def _read_exact(stream: BinaryIO, size: int, *, label: str) -> bytes:
    if size < 0:
        raise ExrDecodeError(f"invalid {label} size")
    payload = stream.read(size)
    if len(payload) != size:
        raise ExrDecodeError(f"truncated {label}")
    return payload


def _parse_channels(payload: bytes) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    cursor = 0
    names = set()
    while True:
        name, cursor = _cstring(payload, cursor, label="channel name")
        if not name:
            break
        if name in names:
            raise ExrDecodeError("duplicate EXR channel name")
        if channels and name < channels[-1]["name"]:
            raise ExrDecodeError("unsupported noncanonical EXR channel order")
        names.add(name)
        if cursor + 16 > len(payload):
            raise ExrDecodeError("truncated channel record")
        pixel_type, p_linear = struct.unpack_from("<iB", payload, cursor)
        cursor += 5
        cursor += 3  # reserved
        x_sampling, y_sampling = struct.unpack_from("<ii", payload, cursor)
        cursor += 8
        if pixel_type not in (0, 1, 2):
            raise ExrDecodeError("unsupported channel pixel type")
        if p_linear not in (0, 1) or x_sampling != 1 or y_sampling != 1:
            raise ExrDecodeError("unsupported channel sampling")
        channels.append({"name": name, "pixel_type": pixel_type, "p_linear":p_linear,
                         "x_sampling":x_sampling,"y_sampling":y_sampling})
    if not channels or cursor != len(payload):
        raise ExrDecodeError("invalid channel list")
    return channels


def _parse_header(data: bytes) -> tuple[dict[str, Any], int]:
    if len(data) < 8 or data[:4] != MAGIC:
        raise ExrDecodeError("invalid EXR magic")
    version_flags = struct.unpack_from("<I", data, 4)[0]
    # LONG_NAMES is compatible with this decoder; tiled/deep/multipart
    # layouts require a different chunk table and must never parse as scanlines.
    if version_flags & 0xFF != VERSION or version_flags & ~(0xFF | 0x400):
        raise ExrDecodeError("unsupported EXR version or flags")

    attrs: dict[str, tuple[str, bytes]] = {}
    cursor = 8
    while True:
        if cursor >= len(data):
            raise ExrDecodeError("truncated EXR header")
        if data[cursor] == 0:
            cursor += 1
            break
        name, cursor = _cstring(data, cursor, label="attribute name")
        kind, cursor = _cstring(data, cursor, label="attribute type")
        if cursor + 4 > len(data):
            raise ExrDecodeError("truncated attribute size")
        size = struct.unpack_from("<I", data, cursor)[0]
        cursor += 4
        if size > len(data) - cursor:
            raise ExrDecodeError("truncated attribute payload")
        if name in attrs:
            raise ExrDecodeError("duplicate EXR attribute")
        attrs[name] = (kind, data[cursor : cursor + size])
        cursor += size

    color_metadata = {}
    if "oiio:ColorSpace" in attrs:
        kind, raw = attrs["oiio:ColorSpace"]
        if kind != "string" or not raw or len(raw) > 1024 or b"\0" in raw:
            raise ExrDecodeError("invalid EXR color space")
        try:
            color_metadata["oiio:ColorSpace"] = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ExrDecodeError("invalid EXR color space") from exc
    if "chromaticities" in attrs:
        kind, raw = attrs["chromaticities"]
        if kind != "chromaticities" or len(raw) != 32:
            raise ExrDecodeError("invalid EXR chromaticities")
        values = list(struct.unpack("<8f", raw))
        if not all(math.isfinite(value) for value in values):
            raise ExrDecodeError("invalid EXR chromaticities")
        color_metadata["chromaticities"] = values

    required = {"channels", "dataWindow", "displayWindow", "compression", "lineOrder"}
    if not required.issubset(attrs):
        raise ExrDecodeError("missing required EXR attributes")
    if attrs["channels"][0] != "chlist":
        raise ExrDecodeError("invalid channels attribute")
    channels = _parse_channels(attrs["channels"][1])
    if attrs["dataWindow"][0] != "box2i" or len(attrs["dataWindow"][1]) != 16:
        raise ExrDecodeError("invalid dataWindow")
    min_x, min_y, max_x, max_y = struct.unpack("<iiii", attrs["dataWindow"][1])
    width, height = _window_size((min_x, min_y, max_x, max_y), "dataWindow")
    if attrs["displayWindow"][0] != "box2i" or len(attrs["displayWindow"][1]) != 16:
        raise ExrDecodeError("invalid displayWindow")
    display_window = struct.unpack('<iiii',attrs['displayWindow'][1])
    _window_size(display_window, "displayWindow")
    if (attrs["compression"][0] != "compression"
            or len(attrs["compression"][1]) != 1
            or attrs["compression"][1][0] not in (0, 2, 3)):
        raise ExrDecodeError("unsupported compression")
    compression = attrs["compression"][1][0]
    if attrs["lineOrder"][0] != "lineOrder" or attrs["lineOrder"][1] not in (b"\0", b"\1"):
        raise ExrDecodeError("invalid line order")
    header_fields = {"line_order": attrs["lineOrder"][1][0]}
    for name, kind, fmt, key, default in (
        ("pixelAspectRatio", "float", "<f", "pixel_aspect_ratio", (1.0,)),
        ("screenWindowCenter", "v2f", "<ff", "screen_window_center", (0.0, 0.0)),
        ("screenWindowWidth", "float", "<f", "screen_window_width", (1.0,)),
    ):
        value = default
        if name in attrs:
            attr_kind, payload = attrs[name]
            if attr_kind != kind or len(payload) != struct.calcsize(fmt):
                raise ExrDecodeError("invalid " + name)
            value = struct.unpack(fmt, payload)
        if not all(math.isfinite(v) for v in value):
            raise ExrDecodeError("invalid " + name)
        header_fields[key] = list(value) if len(value) == 2 else value[0]
    _validate_view(header_fields["pixel_aspect_ratio"], header_fields["screen_window_width"])

    if width <= 0 or height <= 0 or width * height > 100_000_000:
        raise ExrDecodeError("invalid EXR dimensions")
    return (
        {
            "channels": channels,
            "compression": compression,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width": width,
            "height": height,
            "display_window":display_window,
            "header_fields": header_fields,
            "color_metadata": color_metadata,
        },
        cursor,
    )


def _decode_zip(payload: bytes, size: int) -> bytes:
    # OpenEXR writes raw bytes when compressed bytes would not be smaller.
    if len(payload) == size:
        return payload
    if not payload or len(payload) > size:
        raise ExrDecodeError("invalid compressed EXR block size")
    try:
        decoder = zlib.decompressobj()
        reordered = bytearray(decoder.decompress(payload, size + 1))
    except zlib.error as exc:
        raise ExrDecodeError("invalid EXR ZIP stream") from exc
    if (len(reordered) != size or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail):
        raise ExrDecodeError("EXR ZIP decoded size or stream boundary mismatch")
    for i in range(1, size):
        reordered[i] = (reordered[i - 1] + reordered[i] - 128) & 255
    split = (size + 1) // 2
    decoded = bytearray(size)
    decoded[::2] = reordered[:split]
    decoded[1::2] = reordered[split:]
    return bytes(decoded)


def read_exr(path: str | Path, *, with_pixels: bool = True) -> dict[str, Any]:
    """Validate all blocks; retain pixel lists only for explicit image analysis."""
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ExrDecodeError("EXR input exceeds decoder byte budget")
    raw = path.read_bytes()
    header, cursor = _parse_header(raw)
    width, height, channels = header["width"], header["height"], header["channels"]
    bytes_per_sample = {0: 4, 1: 2, 2: 4}
    row_size = sum(bytes_per_sample[c["pixel_type"]] for c in channels) * width
    if row_size * height > 512 * 1024 * 1024:
        raise ExrDecodeError("EXR decoded image exceeds byte budget")
    if with_pixels and width * height * len(channels) * 40 > 256 * 1024 * 1024:
        raise ExrDecodeError("EXR pixel objects exceed analysis memory budget")
    block_lines = 16 if header["compression"] == 3 else 1
    block_count = (height + block_lines - 1) // block_lines
    if block_count > 1_000_000:
        raise ExrDecodeError("EXR chunk metadata exceeds decoder budget")
    if cursor + block_count * 8 > len(raw):
        raise ExrDecodeError("truncated EXR offset table")
    offsets = struct.unpack_from(f"<{block_count}Q", raw, cursor)
    cursor += block_count * 8
    if any(offset < cursor or offset + 8 > len(raw) for offset in offsets):
        raise ExrDecodeError("invalid EXR scanline offset")
    if len(set(offsets)) != len(offsets):
        raise ExrDecodeError("duplicate EXR scanline offset")
    rows, seen_blocks, ranges = [], set(), []
    for offset in offsets:
        y, payload_size = struct.unpack_from("<iI", raw, offset)
        if (y < header["min_y"] or y > header["max_y"]
                or (y - header["min_y"]) % block_lines):
            raise ExrDecodeError("EXR block outside dataWindow or misaligned")
        if y in seen_blocks:
            raise ExrDecodeError("duplicate EXR scanline block")
        seen_blocks.add(y)
        count = min(block_lines, header["max_y"] - y + 1)
        expected_size = row_size * count
        if expected_size > 64 * 1024 * 1024:
            raise ExrDecodeError("EXR decoded block exceeds decoder budget")
        payload_start, payload_end = offset + 8, offset + 8 + payload_size
        if payload_end > len(raw) or not payload_size:
            raise ExrDecodeError("truncated EXR scanline block")
        packed = raw[payload_start:payload_end]
        if header["compression"]:
            decoded = _decode_zip(packed, expected_size)
        else:
            if payload_size != expected_size:
                raise ExrDecodeError("invalid EXR scanline size")
            decoded = packed
        ranges.append((offset, payload_end))
        pos = 0
        for line in range(y, y + count):
            values = {}
            for channel in channels:
                kind = channel["pixel_type"]
                fmt = {0: "I", 1: "e", 2: "f"}[kind]
                if with_pixels:
                    values[channel["name"]] = list(struct.unpack_from(f"<{width}{fmt}", decoded, pos))
                else:
                    # Decode a sample after validating the complete channel byte span.
                    struct.unpack_from("<" + fmt, decoded, pos)
                pos += bytes_per_sample[kind] * width
            if with_pixels:
                rows.append({"y": line, "channels": values})
        if pos != expected_size:
            raise ExrDecodeError("invalid EXR decoded payload")
    if len(seen_blocks) != block_count:
        raise ExrDecodeError("EXR scanline coverage is incomplete")
    ranges.sort()
    if any(end > start for (_, end), (start, _) in zip(ranges, ranges[1:])):
        raise ExrDecodeError("overlapping EXR scanline records")
    rows.sort(key=lambda row: row["y"])
    return {"width": width, "height": height,
            "channels": [c["name"] for c in channels], "rows": rows,
            "channel_layout":{"channels":channels,
                "data_window":[header['min_x'],header['min_y'],header['max_x'],header['max_y']],
                "display_window":list(header['display_window'])},
            "compression": header["compression"], "pixel_count": width * height,
            "sample_count": width * height * len(channels), "structural_validated": True,
            "header_fields": header["header_fields"], "color_metadata": header["color_metadata"]}


def _encoded_sample(value, pixel_type: int) -> bytes:
    if pixel_type == 0:
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ExrDecodeError("invalid UINT EXR sample")
        return struct.pack("<I", value)
    try:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ExrDecodeError("EXR writer samples must be finite numbers")
        fmt = "<e" if pixel_type == 1 else "<f"
        encoded = struct.pack(fmt, value)
        if not math.isfinite(struct.unpack(fmt, encoded)[0]):
            raise ExrDecodeError("EXR sample quantized to a nonfinite value")
        return encoded
    except (OverflowError, struct.error) as exc:
        raise ExrDecodeError("EXR sample exceeds its pixel type range") from exc


def _writer_layout(image, rows):
    if not isinstance(image, dict) or not isinstance(image.get("channel_layout"), dict):
        raise ExrDecodeError("typed EXR writer metadata required")
    width, height = image.get("width"), image.get("height")
    if (type(width) is not int or type(height) is not int or min(width, height) <= 0
            or width * height > 100_000_000):
        raise ExrDecodeError("invalid EXR writer dimensions")
    layout = image["channel_layout"]
    if set(layout) != {"channels", "data_window", "display_window"}:
        raise ExrDecodeError("invalid EXR writer layout")
    channels = layout["channels"]
    if not isinstance(channels, list) or not 1 <= len(channels) <= 1024:
        raise ExrDecodeError("invalid EXR writer channels")
    names = []
    for channel in channels:
        if (not isinstance(channel, dict) or set(channel) != {"name", "pixel_type", "p_linear", "x_sampling", "y_sampling"}
                or type(channel["pixel_type"]) is not int or channel["pixel_type"] not in (0, 1, 2)
                or type(channel["p_linear"]) is not int or channel["p_linear"] not in (0, 1)
                or type(channel["x_sampling"]) is not int or channel["x_sampling"] != 1
                or type(channel["y_sampling"]) is not int or channel["y_sampling"] != 1):
            raise ExrDecodeError("invalid or unsupported EXR writer channel layout")
        name = channel["name"]
        try:
            valid_name = isinstance(name, str) and 1 <= len(name.encode("ascii")) <= 255 and "\0" not in name
        except UnicodeEncodeError:
            valid_name = False
        if not valid_name or name in names:
            raise ExrDecodeError("invalid EXR writer channel name")
        if names and name < names[-1]:
            raise ExrDecodeError("unsupported noncanonical EXR channel order")
        names.append(name)
    if image.get("channels") != names:
        raise ExrDecodeError("EXR writer channel names differ from typed layout")
    for key in ("data_window", "display_window"):
        _window_size(layout[key], "writer " + key)
    box = layout["data_window"]
    if box[2] - box[0] + 1 != width or box[3] - box[1] + 1 != height:
        raise ExrDecodeError("EXR writer dimensions differ from data window")
    if (type(image.get("pixel_count")) is not int or image["pixel_count"] != width * height
            or type(image.get("sample_count")) is not int or image["sample_count"] != width * height * len(channels)
            or image.get("structural_validated") is not True
            or type(image.get("compression")) is not int or image["compression"] not in (0, 2, 3)):
        raise ExrDecodeError("EXR writer sample coverage is unverified")
    row_size = width * sum(2 if c["pixel_type"] == 1 else 4 for c in channels)
    # A conservative shape estimate limits additional readback allocation;
    # caller memory usage is not measured. Include narrow-row containers.
    object_bytes = width * height * len(channels) * 40 + height * (256 + 160 * len(channels))
    if (row_size > 64 * 1024 * 1024 or row_size * height > 512 * 1024 * 1024
            or object_bytes > 128 * 1024 * 1024 or height > 1_000_000):
        raise ExrDecodeError("EXR writer exceeds byte or readback object budget")
    if not isinstance(rows, list) or len(rows) != height:
        raise ExrDecodeError("incomplete EXR writer pixel rows")
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or set(row) != {"y", "channels"}
                or type(row["y"]) is not int or row["y"] != box[1] + index
                or not isinstance(row["channels"], dict) or set(row["channels"]) != set(names)):
            raise ExrDecodeError("EXR writer rows do not cover the typed data window")
        for channel in channels:
            values = row["channels"][channel["name"]]
            if not isinstance(values, list) or len(values) != width:
                raise ExrDecodeError("EXR writer channel sample count differs")
            for value in values:
                _encoded_sample(value, channel["pixel_type"])
    return channels, row_size


def write_exr(path: str | Path, decoded_header: dict[str, Any], blended_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Atomically write bounded typed scanlines with NONE compression.

    Accept read_exr metadata and codec-shaped rows, including blend_pixels
    output. HALF/FLOAT values are quantized to their declared EXR type; UINT
    remains exact. Channel names must be in canonical lexical ASCII order;
    unsupported order is rejected without reordering metadata or samples.
    Supported standard header fields and native color metadata are preserved. The
    scanline line order must be INCREASING_Y or DECREASING_Y. The
    returned metadata/hash describe bytes, not producer or denoise acceptance.
    """
    channels, row_size = _writer_layout(decoded_header, blended_rows)
    fields = decoded_header.get("header_fields", {"line_order": 0, "pixel_aspect_ratio": 1.0,
        "screen_window_center": [0.0, 0.0], "screen_window_width": 1.0})
    if (not isinstance(fields, dict) or set(fields) != {"line_order", "pixel_aspect_ratio", "screen_window_center", "screen_window_width"}
            or type(fields["line_order"]) is not int or fields["line_order"] not in (0, 1)
            or not isinstance(fields["screen_window_center"], (list, tuple)) or len(fields["screen_window_center"]) != 2):
        raise ExrDecodeError("invalid EXR writer header fields")
    view = [_encoded_sample(fields["pixel_aspect_ratio"], 2),
            *[_encoded_sample(v, 2) for v in fields["screen_window_center"]],
            _encoded_sample(fields["screen_window_width"], 2)]
    _validate_view(struct.unpack("<f", view[0])[0], struct.unpack("<f", view[3])[0])
    chlist = b"".join(c["name"].encode("ascii") + b"\0" + struct.pack("<iB3xii", c["pixel_type"], c["p_linear"], c["x_sampling"], c["y_sampling"]) for c in channels) + b"\0"
    layout = decoded_header["channel_layout"]
    color = decoded_header.get("color_metadata", {})
    if not isinstance(color, dict) or set(color) - {"oiio:ColorSpace", "chromaticities"}:
        raise ExrDecodeError("invalid EXR color metadata")
    color_attrs = b""
    if "oiio:ColorSpace" in color:
        token = color["oiio:ColorSpace"]
        if not isinstance(token, str) or not token or "\0" in token or len(token.encode("utf-8")) > 1024:
            raise ExrDecodeError("invalid EXR color space")
        color_attrs += _attribute("oiio:ColorSpace", "string", token.encode("utf-8"))
    if "chromaticities" in color:
        values = color["chromaticities"]
        if (not isinstance(values, (list, tuple)) or len(values) != 8
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise ExrDecodeError("invalid EXR chromaticities")
        color_attrs += _attribute("chromaticities", "chromaticities", struct.pack("<8f", *values))
    header = b"".join((
        _attribute("channels", "chlist", chlist),
        _attribute("dataWindow", "box2i", struct.pack("<iiii", *layout["data_window"])),
        _attribute("displayWindow", "box2i", struct.pack("<iiii", *layout["display_window"])),
        _attribute("lineOrder", "lineOrder", bytes([fields["line_order"]])),
        _attribute("compression", "compression", b"\0"),
        _attribute("pixelAspectRatio", "float", view[0]),
        _attribute("screenWindowCenter", "v2f", view[1] + view[2]),
        _attribute("screenWindowWidth", "float", view[3]), color_attrs, b"\0"))
    height = decoded_header["height"]
    first_chunk = 8 + len(header) + height * 8
    size = first_chunk + height * (8 + row_size)
    if size > 512 * 1024 * 1024:
        raise ExrDecodeError("EXR writer file exceeds decoder byte budget")
    path = Path(path)
    if path.is_symlink():
        raise ExrDecodeError("EXR writer target cannot be a symlink")
    temp = None
    try:
        fd, filename = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temp = Path(filename)
        with os.fdopen(fd, "wb") as stream:
            flags = 0x400 if any(len(c["name"]) > 31 for c in channels) else 0
            stream.write(MAGIC + struct.pack("<I", VERSION | flags) + header)
            for index in range(height):
                physical = height - 1 - index if fields["line_order"] == 1 else index
                stream.write(struct.pack("<Q", first_chunk + physical * (8 + row_size)))
            rows = reversed(blended_rows) if fields["line_order"] == 1 else iter(blended_rows)
            for row in rows:
                stream.write(struct.pack("<iI", row["y"], row_size))
                for channel in channels:
                    for value in row["channels"][channel["name"]]:
                        stream.write(_encoded_sample(value, channel["pixel_type"]))
            stream.flush()
            os.fsync(stream.fileno())
        actual = read_exr(temp)
        expected_color = dict(color)
        if "chromaticities" in expected_color:
            expected_color["chromaticities"] = list(struct.unpack("<8f", struct.pack("<8f", *expected_color["chromaticities"])))
        expected_fields = {"line_order": fields["line_order"], "pixel_aspect_ratio": struct.unpack("<f", view[0])[0],
            "screen_window_center": list(struct.unpack("<ff", view[1] + view[2])), "screen_window_width": struct.unpack("<f", view[3])[0]}
        expected_layout = {"channels": channels, "data_window": list(layout["data_window"]), "display_window": list(layout["display_window"])}
        if (actual["color_metadata"] != expected_color
                or actual["channel_layout"] != expected_layout or actual["header_fields"] != expected_fields
                or actual["compression"] != 0 or actual["channels"] != decoded_header["channels"]
                or actual["width"] != decoded_header["width"] or actual["height"] != height
                or actual["pixel_count"] != decoded_header["pixel_count"]
                or actual["sample_count"] != decoded_header["sample_count"] or len(actual["rows"]) != height):
            raise ExrDecodeError("EXR writer typed readback differs")
        for expected, decoded in zip(blended_rows, actual["rows"]):
            if decoded["y"] != expected["y"]:
                raise ExrDecodeError("EXR writer scanline readback differs")
            for channel in channels:
                name, kind = channel["name"], channel["pixel_type"]
                if len(decoded["channels"][name]) != decoded_header["width"] or any(_encoded_sample(a, kind) != _encoded_sample(b, kind)
                       for a, b in zip(expected["channels"][name], decoded["channels"][name])):
                    raise ExrDecodeError("EXR writer quantized pixel readback differs")
        digest = hashlib.sha256()
        with temp.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if temp.stat().st_size != size:
            raise ExrDecodeError("EXR writer byte coverage differs")
        result = {key: value for key, value in actual.items() if key != "rows"}
        result.update(path=str(path), bytes=size, sha256=digest.hexdigest())
        os.replace(temp, path)
        return result
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
