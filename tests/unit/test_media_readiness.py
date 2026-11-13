# -*- coding: utf-8 -*-
"""P4 local-media, active-frame, feedback, and budget contract probes."""
from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from dcc_task_runtime.domains import builtin_domain_registry
from vfx_pipeline.media_readiness import (
    ActiveFrameDiagnostics,
    DiskBudgetWatchdog,
    FixedPngDecoder,
    LocalMediaRegistrar,
    apply_feedback_invalidation,
    confirm_cache_contract,
    reference_observations,
)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload +
            struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _png(value: int, *, width: int = 1, height: int = 1) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([value]) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) +
            _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


class MediaReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="media-readiness-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        self.registrar = LocalMediaRegistrar(self.media, decoder=FixedPngDecoder(max_bytes=1024 * 1024))

    def test_fixed_decoder_registers_local_sequence_without_model_claims(self) -> None:
        one = self.media / "plate.001.png"
        two = self.media / "plate.002.png"
        one.write_bytes(_png(20))
        two.write_bytes(_png(80))
        registered = self.registrar.register_sequence("plate", {1: one, 2: two}, fps=24.0)
        self.assertEqual(registered.manifest.assets[0].kind, "sequence")
        self.assertEqual(registered.manifest.assets[0].frame_range, (1, 2, 1))
        observations = reference_observations(registered)
        self.assertFalse(observations["model_called"])
        self.assertFalse(observations["semantic_inference"])
        self.assertEqual(len(observations["claims"]), 0)

    def test_active_frame_diagnostics_rejects_frozen_sequence_and_confirms_cache(self) -> None:
        first = self.media / "render.001.png"
        second = self.media / "render.002.png"
        first.write_bytes(_png(12))
        second.write_bytes(_png(12))
        paths = {1: first, 2: second}
        frozen = ActiveFrameDiagnostics().inspect(paths, expected_frames=[1, 2], active_frames=[1, 2])
        self.assertEqual(frozen["status"], "BLOCKED")
        self.assertTrue(frozen["frozen_active"])
        second.write_bytes(_png(200))
        confirmed = confirm_cache_contract(
            paths, expected_frames=[1, 2], active_frames=[1, 2],
            colorspace="scene_linear", premultiplied=False,
            dependencies=["operation:software-boundary"],
        )
        self.assertEqual(confirmed["status"], "PASS")
        self.assertTrue(confirmed["mechanical_only"])
        self.assertFalse(confirmed["simulation_executed"])

    def test_budget_requests_stop_and_never_deletes_task_files(self) -> None:
        cache = self.root / "cache.bin"
        cache.write_bytes(b"x" * 64)
        watchdog = DiskBudgetWatchdog(self.root, max_bytes=32, max_frames=12, max_seconds=120.0)
        preflight = watchdog.preflight(estimated_bytes=0, frames=1)
        self.assertEqual(preflight["status"], "STOP_REQUESTED")
        self.assertIn("DISK_BUDGET_EXCEEDED", preflight["reasons"])
        self.assertEqual(preflight["deleted_paths"], [])
        self.assertTrue(cache.is_file())

    def test_feedback_invalidation_is_bound_to_domain_control(self) -> None:
        pack = builtin_domain_registry().get("pyro_smoke_v1", "1.0.0")
        control = next(item for item in pack.controls if item.requires_simulation_cache)
        value = control.minimum if control.minimum is not None else 0.1
        receipt = apply_feedback_invalidation(pack, control.name, value)
        self.assertEqual(receipt["status"], "INVALIDATED")
        self.assertEqual(receipt["domain_pack"], pack.identifier)
        self.assertEqual(receipt["control"], control.name)
        self.assertEqual(receipt["invalidates_stage_nodes"], list(control.invalidates_stage_nodes))
        self.assertTrue(receipt["cache_confirmation_required"])
        self.assertFalse(receipt["model_called"])


if __name__ == "__main__":
    unittest.main()
