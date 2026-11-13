"""Bounded deterministic decoders for immutable visual artifacts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.models import ErrorCode


class ImageMagickRasterDecoder:
    """Sample one raster/EXR through a fixed, non-shell ImageMagick command.

    The decoder is intentionally small: one frame, one image plane, 64x64
    grayscale samples.  It never evaluates a caller command and never writes
    an output file.  ACES/chromatic judgements still belong to the DCC/AOV
    validation path; this proxy supports deterministic spatial comparisons.
    """

    SUFFIXES = frozenset({".exr", ".dpx", ".png", ".tif", ".tiff", ".jpg", ".jpeg"})

    def __init__(self, executable: str | None = None, width: int = 64, height: int = 64) -> None:
        configured = executable or os.environ.get("BRIDGE_SKILLS_MAGICK") or shutil.which("magick")
        self.executable = str(Path(configured).expanduser().resolve()) if configured else ""
        self.width = int(width)
        self.height = int(height)
        if self.width <= 1 or self.height <= 1 or self.width * self.height > 65536:
            raise ValueError("raster sample grid is invalid")

    @property
    def available(self) -> bool:
        return bool(self.executable and Path(self.executable).is_file())

    def decode(self, path: Path) -> tuple[list[list[float]], dict[str, Any]]:
        path = Path(path)
        if path.suffix.lower() not in self.SUFFIXES:
            raise RuntimeV2Error(ErrorCode.UNSUPPORTED_INPUT_DECODER, "visual artifact suffix is unsupported")
        if not self.available:
            raise RuntimeV2Error(
                ErrorCode.UNSUPPORTED_INPUT_DECODER,
                "ImageMagick is unavailable; set BRIDGE_SKILLS_MAGICK or provide a JSON diagnostic artifact",
            )
        command = [
            self.executable,
            str(path) + "[0]",
            "-alpha",
            "off",
            "-colorspace",
            "Gray",
            "-resize",
            f"{self.width}x{self.height}!",
            "-depth",
            "16",
            "txt:-",
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeV2Error(ErrorCode.UNSUPPORTED_INPUT_DECODER, "bounded ImageMagick decode failed") from exc
        if completed.returncode != 0 or len(completed.stdout) > 8 * 1024 * 1024:
            raise RuntimeV2Error(
                ErrorCode.UNSUPPORTED_INPUT_DECODER,
                "ImageMagick rejected the visual artifact",
                {"return_code": completed.returncode},
            )
        samples: dict[tuple[int, int], float] = {}
        for line in completed.stdout.splitlines():
            match = re.match(r"^(\d+),(\d+):.*gray\(([-+0-9.eE]+)(%)?\)", line)
            if not match:
                continue
            x, y = int(match.group(1)), int(match.group(2))
            value = float(match.group(3))
            if match.group(4):
                value /= 100.0
            elif value > 1.0:
                value /= 65535.0
            samples[(x, y)] = value
        expected = self.width * self.height
        if len(samples) != expected:
            raise RuntimeV2Error(
                ErrorCode.UNSUPPORTED_INPUT_DECODER,
                "ImageMagick did not return the exact deterministic sample grid",
                {"expected_samples": expected, "actual_samples": len(samples)},
            )
        raster = [[samples[(x, y)] for x in range(self.width)] for y in range(self.height)]
        return raster, {
            "decoder": "imagemagick_txt_gray_v1",
            "sample_width": self.width,
            "sample_height": self.height,
            "executable": self.executable,
        }
