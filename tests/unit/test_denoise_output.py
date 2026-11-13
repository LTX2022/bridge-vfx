"""No upstream success fixtures: only real codec bytes and missing-ledger rejection."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/dcc-task-runtime/src"))

from dcc_task_runtime.artifact_registry import ArtifactRegistry
from dcc_task_runtime.denoise_output import (
    DenoiseOutputBlocked, _digest, _publish_frame, _write_blended_frame, produce_denoise_output,
)
from dcc_task_runtime.exr_codec import ExrDecodeError, read_exr, write_exr
from dcc_task_runtime import denoise_output


class DenoiseOutputAdmissionTests(unittest.TestCase):
    def test_missing_current_upstream_artifacts_blocks_without_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            root = Path(directory)
            registry = ArtifactRegistry(root / "ledger")
            expected = {
                "task_id": "unproven-task", "frame": 1, "scene_fingerprint": "a" * 64,
                "source_artifact_id": "missing-raw", "source_version": 1,
                "source_operation_id": "missing-render", "source_sha256": "b" * 64,
                "denoised_artifact_id": "missing-denoised", "denoised_version": 1,
                "denoise_operation_id": "missing-denoise", "operation_source": lambda identity: None,
            }
            target = root / "mixed.exr"
            with self.assertRaisesRegex(DenoiseOutputBlocked, "RAW_ARTIFACT_UNAVAILABLE"):
                produce_denoise_output(registry=registry, expected_identity=expected,
                                       amount=0.5, output_path=target)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [root / "ledger"])

    def test_controller_sources_cannot_be_replaced_with_request_mappings(self):
        with self.assertRaisesRegex(DenoiseOutputBlocked, "CONTROLLER_SOURCES_REQUIRED"):
            produce_denoise_output(registry={}, expected_identity={}, amount=0.5,
                                   output_path=Path("unused.exr"))


class BlendedExrBytesTests(unittest.TestCase):
    def images(self):
        raw = read_exr(ROOT / "tests/fixtures/exr/openexr-3.4.15-3.exr")
        raw["channels"].insert(1, "beauty.A")
        raw["channel_layout"]["channels"].insert(1, {
            "name": "beauty.A", "pixel_type": 1, "p_linear": 1,
            "x_sampling": 1, "y_sampling": 1,
        })
        raw["channel_layout"]["data_window"] = [-8, -4, 23, 14]
        raw["channel_layout"]["display_window"] = [-20, -10, 40, 30]
        raw["sample_count"] += raw["pixel_count"]
        raw["header_fields"] = {"line_order": 1, "pixel_aspect_ratio": 1.25,
                                "screen_window_center": [-0.5, 2.0], "screen_window_width": 0.0}
        for row in raw["rows"]:
            row["y"] -= 4
            row["channels"]["beauty.A"] = [0.5] * raw["width"]
        derived = deepcopy(raw)
        for row in derived["rows"]:
            row["channels"]["R"] = [value + 0.5 for value in row["channels"]["R"]]
            row["channels"]["depth.Z"] = [value + 0.123456789 for value in row["channels"]["depth.Z"]]
        return raw, derived

    def test_real_two_exr_decode_blend_quantization_and_exact_layout_readback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            root = Path(directory)
            raw, derived = self.images()
            write_exr(root / "raw-fixture.exr", raw, raw["rows"])
            write_exr(root / "derived-fixture.exr", derived, derived["rows"])
            raw = read_exr(root / "raw-fixture.exr")
            derived = read_exr(root / "derived-fixture.exr")
            before = deepcopy((raw, derived))
            for amount in (0.0, 0.25, 0.5, 1.0):
                with self.subTest(amount=amount):
                    target = root / (str(amount) + ".exr")
                    snapshot, metadata = _write_blended_frame(target, raw, derived, amount)
                    actual = read_exr(target)
                    self.assertEqual(actual["channel_layout"], raw["channel_layout"])
                    self.assertEqual(actual["header_fields"], raw["header_fields"])
                    self.assertEqual(actual["compression"], 0)
                    self.assertEqual(metadata["sample_count"], raw["sample_count"])
                    self.assertEqual(snapshot["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
                    self.assertEqual(snapshot["bytes"], target.stat().st_size)
                    self.assertEqual(snapshot["modified_ns"], target.stat().st_mtime_ns)
                    self.assertEqual(metadata["sha256"], snapshot["sha256"])
                    self.assertNotIn("state", metadata)
                    self.assertNotIn("operation_id", metadata)
                    for source, changed, decoded in zip(raw["rows"], derived["rows"], actual["rows"]):
                        self.assertEqual(decoded["y"], source["y"])
                        for channel in raw["channel_layout"]["channels"]:
                            name, kind = channel["name"], channel["pixel_type"]
                            if name == "beauty.A" or kind == 0:
                                self.assertEqual(decoded["channels"][name], source["channels"][name])
                            else:
                                sample_format = {1: "<e", 2: "<f"}[kind]
                                expected = [struct.unpack(sample_format, struct.pack(sample_format,
                                            left * (1 - amount) + right * amount))[0]
                                            for left, right in zip(source["channels"][name], changed["channels"][name])]
                                self.assertEqual(decoded["channels"][name], expected)
                        self.assertTrue(all(type(value) is int for value in decoded["channels"]["id"]))
            self.assertEqual((raw, derived), before)

    def test_incompatible_or_nonfinite_samples_refuse_output(self):
        raw, derived = self.images()
        cases = []
        for name, value in (("beauty.A", 0.75), ("id", 42), ("R", float("nan")), ("R", 70000.0)):
            changed = deepcopy(derived)
            changed["rows"][0]["channels"][name][0] = value
            cases.append(changed)
        changed = deepcopy(derived)
        changed["channel_layout"]["display_window"][0] -= 1
        cases.append(changed)
        changed = deepcopy(derived)
        changed["header_fields"]["pixel_aspect_ratio"] = 2.0
        cases.append(changed)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            target = Path(directory) / "never-created.exr"
            for index, changed in enumerate(cases):
                with self.subTest(case=index), self.assertRaises((ValueError, ExrDecodeError)):
                    _write_blended_frame(target, raw, changed, 1.0)
                self.assertFalse(target.exists())
            for amount in (True, "0.5", -0.1, 1.1, float("nan"), float("inf")):
                with self.subTest(amount=amount), self.assertRaises(ValueError):
                    _write_blended_frame(target, raw, derived, amount)
                self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_dependency_digest_changes_with_consumed_version_and_content(self):
        summary = {"raw": {"artifact_id": "fixture-reference", "version": 1, "sha256": "a" * 64},
                   "denoised": {"version": 2, "sha256": "b" * 64}}
        original = _digest(summary)
        self.assertEqual(original, _digest(dict(reversed(list(summary.items())))))
        for key, value in (("version", 3), ("sha256", "c" * 64)):
            changed = deepcopy(summary)
            changed["denoised"][key] = value
            self.assertNotEqual(original, _digest(changed))

    def test_exclusive_publication_keeps_existing_bytes_and_snapshot_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            root = Path(directory)
            staged, target = root / "staged.exr", root / "output.exr"
            raw, derived = self.images()
            snapshot, _ = _write_blended_frame(staged, raw, derived, 0.25)
            _publish_frame(staged, target)
            self.assertEqual(target.stat().st_mtime_ns, snapshot["modified_ns"])
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), snapshot["sha256"])
            staged.unlink()
            self.assertEqual(read_exr(target)["channel_layout"], raw["channel_layout"])
            staged.write_bytes(b"different-producer-bytes")
            with self.assertRaises(FileExistsError):
                _publish_frame(staged, target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), snapshot["sha256"])


class RegistryCompletionMetadataTests(unittest.TestCase):
    def receipt(self, root):
        raw, derived = BlendedExrBytesTests().images()
        snapshot, metadata = _write_blended_frame(root / "mixed.exr", raw, derived, 0.25)
        metadata.update(colorspace="scene_linear", premultiplied=True)
        summary = {"raw": {"fixture": "decoded raw pixels"},
                   "denoised": {"fixture": "derived pixels; no denoiser operation"}}
        binding = {"formula": "raw*(1-amount)+denoised*amount", "amount": 0.25,
                   "dependency_summary": summary, "dependency_summary_sha256": _digest(summary)}
        return {"frame_set": [3], "output_pattern": snapshot["path"], "amount": 0.25,
                "frame_snapshots": {"3": snapshot}, "metadata": {"3": metadata, "denoise_blend": binding},
                "denoise_blend": deepcopy(binding), "dependency_summary": summary,
                "dependency_summary_sha256": _digest(summary)}

    def adapt(self, receipt):
        return denoise_output.registry_completion_metadata(receipt)

    def test_actual_typed_output_normalizes_frame_keys_and_snapshot_fields(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            receipt = self.receipt(Path(directory))
            before = deepcopy(receipt)
            self.assertNotEqual(set(receipt["metadata"]), {"3"})
            self.assertTrue({"path", "bytes", "modified_ns"}.isdisjoint(receipt["metadata"]["3"]))
            normalized = self.adapt(receipt)
            self.assertEqual(set(normalized), {"3"})
            for key, value in receipt["frame_snapshots"]["3"].items():
                self.assertEqual(normalized["3"][key], value)
            decoded = read_exr(receipt["output_pattern"])
            for key, value in decoded.items():
                if key != "rows":
                    self.assertEqual(normalized["3"][key], value)
            self.assertEqual(normalized["3"]["colorspace"], "scene_linear")
            self.assertIs(normalized["3"]["premultiplied"], True)
            for field in ("state", "operation_id", "completion_metadata_status", "denoise_blend", "rows"):
                self.assertNotIn(field, normalized["3"])
            self.assertEqual(receipt, before)
            normalized["3"]["channel_layout"]["data_window"][0] -= 1
            self.assertEqual(receipt, before)

    def test_snapshot_and_decoded_metadata_mismatches_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            receipt = self.receipt(Path(directory))
            snapshot = receipt["frame_snapshots"]["3"]
            cases = []
            for key, value in (("bytes", snapshot["bytes"] + 1),
                               ("modified_ns", snapshot["modified_ns"] + 1),
                               ("sha256", "f" * 64), ("path", "relative.exr")):
                changed = deepcopy(receipt)
                changed["frame_snapshots"]["3"][key] = value
                cases.append(changed)
            for key, value in (("width", 1), ("sha256", "f" * 64),
                               ("premultiplied", None), ("colorspace", "")):
                changed = deepcopy(receipt)
                changed["metadata"]["3"][key] = value
                cases.append(changed)
            changed = deepcopy(receipt)
            changed["metadata"]["3"]["channel_layout"]["display_window"][0] -= 1
            cases.append(changed)
            changed = deepcopy(receipt)
            changed["frame_set"] = [4]
            cases.append(changed)
            changed = deepcopy(receipt)
            changed["metadata"]["unexpected"] = {}
            cases.append(changed)
            for index, changed in enumerate(cases):
                with self.subTest(case=index), self.assertRaises(ValueError):
                    self.adapt(changed)

    def test_blend_binding_must_remain_consistent_and_is_not_discarded(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            receipt = self.receipt(Path(directory))
            cases = []
            for key, value in (("formula", "wrong"), ("amount", 0.5),
                               ("dependency_summary_sha256", "f" * 64)):
                changed = deepcopy(receipt)
                changed["denoise_blend"][key] = value
                cases.append(changed)
            changed = deepcopy(receipt)
            changed["dependency_summary"]["raw"]["fixture"] = "changed"
            cases.append(changed)
            for index, changed in enumerate(cases):
                with self.subTest(case=index), self.assertRaises(ValueError):
                    self.adapt(changed)
            before = deepcopy(receipt["denoise_blend"])
            self.adapt(receipt)
            self.assertEqual(receipt["denoise_blend"], before)

    def test_replaced_output_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            receipt = self.receipt(Path(directory))
            target = Path(receipt["output_pattern"])
            raw, _ = BlendedExrBytesTests().images()
            write_exr(target, raw, raw["rows"])
            with self.assertRaises(ValueError):
                self.adapt(receipt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
