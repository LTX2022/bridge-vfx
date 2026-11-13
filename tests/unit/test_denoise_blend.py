"""Controlled software tests; fixtures do not claim native denoise execution."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/dcc-task-runtime/src"))

from dcc_task_runtime.artifact_registry import ArtifactRegistry
from dcc_task_runtime.denoise_blend import blend_pixels, validate_dependency_pair
from dcc_task_runtime.exr_codec import encode_tiny_exr, read_exr


def pixels():
    names = ["R", "G", "beauty.A"]
    return {
        "width": 2, "height": 2, "channels": names,
        "channel_layout": {
            "channels": [{"name": name, "pixel_type": kind, "p_linear": 0,
                          "x_sampling": 1, "y_sampling": 1}
                         for name, kind in zip(names, (1, 2, 1))],
            "data_window": [-1, -2, 0, -1], "display_window": [-1, -2, 0, -1],
        },
        "rows": [
            {"y": -2, "channels": {"R": [0.0, 4.0], "G": [8.0, 12.0], "beauty.A": [0.25, 0.5]}},
            {"y": -1, "channels": {"R": [16.0, 20.0], "G": [24.0, 28.0], "beauty.A": [0.75, 1.0]}},
        ],
        "compression": 0, "pixel_count": 4, "sample_count": 12,
        "structural_validated": True,
    }


def denoised_pixels(raw):
    result = deepcopy(raw)
    for row in result["rows"]:
        row["channels"]["R"] = [value + 8 for value in row["channels"]["R"]]
        row["channels"]["G"] = [value - 8 for value in row["channels"]["G"]]
    return result


class DenoiseBlendTests(unittest.TestCase):
    def test_exact_endpoints_intermediate_and_alpha_invariance(self):
        raw = pixels()
        denoised = denoised_pixels(raw)
        before = deepcopy((raw, denoised))
        cases = [(0, [0, 4], [8, 12]), (0.25, [2, 6], [6, 10]),
                 (0.5, [4, 8], [4, 8]), (1, [8, 12], [0, 4])]
        for amount, red, green in cases:
            with self.subTest(amount=amount):
                result = blend_pixels(raw, denoised, amount)
                self.assertEqual(result[0]["channels"]["R"], red)
                self.assertEqual(result[0]["channels"]["G"], green)
                self.assertEqual([r["channels"]["beauty.A"] for r in result],
                                 [r["channels"]["beauty.A"] for r in raw["rows"]])
                self.assertEqual([r["y"] for r in result], [-2, -1])
        self.assertEqual((raw, denoised), before)

    def test_real_codec_samples_and_typed_layout(self):
        raw = read_exr(ROOT / "tests/fixtures/exr/openexr-3.4.15-3.exr")
        denoised = deepcopy(raw)
        for row in denoised["rows"]:
            row["channels"]["R"] = [value + 4 for value in row["channels"]["R"]]
        before = deepcopy((raw, denoised))
        self.assertEqual([c["pixel_type"] for c in raw["channel_layout"]["channels"]], [1, 2, 0])
        for amount in (0, 0.25, 1):
            result = blend_pixels(raw, denoised, amount)
            for actual, source in zip(result, raw["rows"]):
                self.assertEqual(actual["channels"]["R"], [value + 4 * amount for value in source["channels"]["R"]])
                self.assertEqual(actual["channels"]["id"], source["channels"]["id"])
                self.assertTrue(all(type(value) is int for value in actual["channels"]["id"]))
        roundtrip=deepcopy(raw);roundtrip['rows']=result
        self.assertEqual(blend_pixels(roundtrip,roundtrip,.25),result)
        changed_uint=deepcopy(denoised);changed_uint['rows'][0]['channels']['id'][0]+=1
        for amount in (0,.25,1):
            with self.subTest(changed_uint_amount=amount),self.assertRaisesRegex(ValueError,'UINT'):
                blend_pixels(raw,changed_uint,amount)
        self.assertEqual((raw, denoised), before)
        renamed = deepcopy(raw)
        names = {"depth.Z": "id", "id": "beauty.R"}
        renamed["channels"] = [names.get(name, name) for name in renamed["channels"]]
        for channel in renamed["channel_layout"]["channels"]:
            channel["name"] = names.get(channel["name"], channel["name"])
        for row in renamed["rows"]:
            row["channels"] = {names.get(name, name): values for name, values in row["channels"].items()}
        renamed_denoised = deepcopy(renamed)
        for row in renamed_denoised["rows"]:
            row["channels"]["id"] = [value + 4 for value in row["channels"]["id"]]
        for actual, source in zip(blend_pixels(renamed, renamed_denoised, 0.25), renamed["rows"]):
            self.assertEqual(actual["channels"]["id"], [value + 1 for value in source["channels"]["id"]])
            self.assertEqual(actual["channels"]["beauty.R"], source["channels"]["beauty.R"])
            self.assertTrue(all(type(value) is int for value in actual["channels"]["beauty.R"]))

    def test_invalid_amounts(self):
        for amount in (-0.1, 1.1, float("nan"), float("inf"), -float("inf"), True, "0.5", None):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                blend_pixels(pixels(), pixels(), amount)

    def test_bad_pixel_data_count_layout_and_changed_alpha(self):
        cases = []
        bad = pixels(); bad["rows"][0]["channels"]["R"][0] = float("nan"); cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["R"][0] = float("inf"); cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["R"][0] = True; cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["R"][0] = "1"; cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["R"].pop(); cases.append(bad)
        bad = pixels(); bad["rows"].pop(); cases.append(bad)
        bad = pixels(); bad["rows"][1]["y"] = -2; cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["extra"] = [1, 2]; cases.append(bad)
        bad = pixels(); bad["sample_count"] = 11; cases.append(bad)
        bad = pixels(); del bad["channel_layout"]; cases.append(bad)
        bad = pixels(); bad["channel_layout"]["channels"][0]["pixel_type"] = 2; cases.append(bad)
        bad = pixels(); bad["channel_layout"]["channels"][0]["x_sampling"] = 2; cases.append(bad)
        bad = pixels(); bad["channel_layout"]["channels"][0]["p_linear"] = 1; cases.append(bad)
        bad = pixels(); bad["channel_layout"]["display_window"] = [0, 0, 1, 1]; cases.append(bad)
        bad = pixels(); bad["rows"][0]["channels"]["beauty.A"][0] = 0.5; cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                blend_pixels(pixels(), bad, 0.5)
        changed_alpha = pixels()
        changed_alpha["rows"][0]["channels"]["beauty.A"][0] = 0.5
        for amount in (0, 1):
            with self.subTest(alpha_at_endpoint=amount), self.assertRaises(ValueError):
                blend_pixels(pixels(), changed_alpha, amount)


class DependencyPairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="denoise-blend-controlled-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.registry = ArtifactRegistry(root / "ledger")
        self.operations = {}
        self.registry.set_operation_source(self.operations.get)
        self.scene = "a" * 64
        self.entries = {}
        for role, sample in (("raw", 1.0), ("denoised", 2.0)):
            path = root / (role + ".001.exr")
            path.write_bytes(encode_tiny_exr(sample))
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            decoded = read_exr(path)
            decoded.pop("rows")
            decoded["sha256"] = sha
            decoded["colorspace"] = "scene_linear"
            decoded["premultiplied"] = True
            snapshot = {"path": str(path), "sha256": sha, "bytes": path.stat().st_size,
                        "modified_ns": path.stat().st_mtime_ns}
            op_id = "controlled-" + role
            fact = {"operation_id": op_id, "task_id": "t1", "state": "COMPLETED",
                    "execution_kind": "controlled_software_fixture", "stop_confirmed": True,
                    "scene_fingerprint": self.scene, "frame_set": [1], "output_pattern": str(path),
                    "started_at_epoch": 1.0, "operation_receipt_sha256": hashlib.sha256(op_id.encode()).hexdigest(),
                    "frame_snapshots": {"1": snapshot}, "metadata": {"1": decoded}, "dependencies": []}
            if role == "denoised":
                raw = self.entries["raw"]
                fact["dependencies"] = ["artifact:raw"]
                fact["metadata"]["source"] = {
                    "artifact_id": raw["artifact_id"], "version": raw["version"],
                    "operation_id": raw["operation_id"], "operation_receipt_sha256": raw["operation_receipt_sha256"],
                    "task_id": raw["task_id"], "frame": 1, "scene_fingerprint": raw["scene_fingerprint"],
                    "sha256": raw["payload"]["completion_snapshot"]["1"]["sha256"],
                }
            self.operations[op_id] = fact
            self.entries[role] = self.registry.register(
                artifact_id=role, task_id="t1", artifact_class="preview_temp", pattern=str(path), frame_set=[1],
                colorspace="scene_linear", premultiplied=True, dependencies=fact["dependencies"],
                operation_id=op_id, operation_receipt_sha256=fact["operation_receipt_sha256"], scene_fingerprint=self.scene)
        raw, denoised = self.entries["raw"], self.entries["denoised"]
        self.expected = {
            "task_id": "t1", "frame": 1, "scene_fingerprint": self.scene,
            "source_artifact_id": "raw", "source_version": raw["version"],
            "source_operation_id": raw["operation_id"],
            "source_sha256": raw["payload"]["completion_snapshot"]["1"]["sha256"],
            "denoised_artifact_id": "denoised", "denoised_version": denoised["version"],
            "denoise_operation_id": denoised["operation_id"],
            "artifact_source": self.registry.lookup, "operation_source": self.operations.get,
        }

    def validate(self):
        return validate_dependency_pair(self.entries["raw"], self.entries["denoised"], self.expected)

    def authoritative_fixture(self):
        self.expected["artifact_source"] = self.entries.get

    def test_registered_controller_pair_binds_distinct_output_hashes_and_producers(self):
        self.assertNotEqual(self.entries["raw"]["operation_id"], self.entries["denoised"]["operation_id"])
        self.assertNotEqual(self.entries["raw"]["payload"]["completion_snapshot"]["1"]["sha256"],
                            self.entries["denoised"]["payload"]["completion_snapshot"]["1"]["sha256"])
        self.assertIsNone(self.validate())
        denoised = self.entries["denoised"]
        self.entries["denoised"] = self.registry.register(
            artifact_id="denoised", task_id=denoised["task_id"], artifact_class=denoised["artifact_class"],
            pattern=denoised["pattern"], frame_set=denoised["frame_set"], colorspace=denoised["colorspace"],
            premultiplied=denoised["premultiplied"], dependencies=denoised["dependencies"],
            operation_id=denoised["operation_id"], operation_receipt_sha256=denoised["operation_receipt_sha256"],
            scene_fingerprint=denoised["scene_fingerprint"])
        self.expected["denoised_version"] = self.entries["denoised"]["version"]
        self.assertNotEqual(self.entries["raw"]["version"], self.entries["denoised"]["version"])
        self.assertIsNone(self.validate())

    def test_source_binding_mismatch_or_missing_is_rejected(self):
        self.authoritative_fixture()
        source = self.entries["denoised"]["payload"]["completion_metadata"]["source"]
        for key in tuple(source):
            for missing in (False, True):
                with self.subTest(field=key, missing=missing):
                    saved = deepcopy(source)
                    if missing:
                        source.pop(key)
                    else:
                        source[key] = source[key] + 1 if type(source[key]) is int else "wrong"
                    self.operations["controlled-denoised"]["metadata"] = deepcopy(self.entries["denoised"]["payload"]["completion_metadata"])
                    with self.assertRaises(ValueError): self.validate()
                    source.clear(); source.update(saved)

    def test_missing_trust_and_unknown_incomplete_producer(self):
        for key in ("artifact_source", "operation_source"):
            for source in (None, lambda identity: None):
                with self.subTest(key=key, source=source):
                    expected = {**self.expected, key: source}
                    with self.assertRaises(ValueError):
                        validate_dependency_pair(self.entries["raw"], self.entries["denoised"], expected)
        for key, value in (("state", "RUNNING"), ("stop_confirmed", False), ("execution_kind", "")):
            original = self.operations["controlled-denoised"][key]
            self.operations["controlled-denoised"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()
            self.operations["controlled-denoised"][key] = original
        for value in (float("nan"), float("inf")):
            self.operations["controlled-denoised"]["started_at_epoch"] = value
            with self.subTest(nonfinite_fact=value), self.assertRaises(ValueError): self.validate()
        self.operations["controlled-denoised"]["started_at_epoch"] = 1.0

    def test_missing_expected_identity_and_empty_facts(self):
        for key in tuple(self.expected):
            expected = dict(self.expected); expected.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_dependency_pair(self.entries["raw"], self.entries["denoised"], expected)
        for raw, denoised in (({}, self.entries["denoised"]), (self.entries["raw"], {})):
            with self.assertRaises(ValueError): validate_dependency_pair(raw, denoised, self.expected)

    def test_bound_pair_metadata_and_dependency_mismatches(self):
        self.authoritative_fixture()
        cases = [("task_id", "other"), ("scene_fingerprint", "b" * 64),
                 ("version", 2), ("operation_id", "controlled-raw"),
                 ("colorspace", "display_srgb"), ("colorspace", ""), ("premultiplied", False), ("premultiplied", None)]
        original = deepcopy(self.entries["denoised"])
        for key, value in cases:
            self.entries["denoised"] = deepcopy(original); self.entries["denoised"][key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError): self.validate()
        self.entries["denoised"] = deepcopy(original)
        for section in ("completion_metadata", "completion_snapshot", "completion_dependencies"):
            saved = self.entries["denoised"]["payload"].pop(section)
            with self.subTest(missing=section), self.assertRaises(ValueError): self.validate()
            self.entries["denoised"]["payload"][section] = saved
        self.entries["denoised"]["dependencies"] = []
        with self.assertRaises(ValueError): self.validate()

    def test_authoritative_metadata_hash_layout_and_frames_must_match(self):
        self.authoritative_fixture()
        original = deepcopy(self.entries["denoised"])
        operation = deepcopy(self.operations["controlled-denoised"])
        for field, value in (("sha256", "f" * 64), ("width", 2), ("height", 2), ("structural_validated", False)):
            self.entries["denoised"] = deepcopy(original)
            self.operations["controlled-denoised"] = deepcopy(operation)
            self.entries["denoised"]["payload"]["completion_metadata"]["1"][field] = value
            self.operations["controlled-denoised"]["metadata"] = deepcopy(self.entries["denoised"]["payload"]["completion_metadata"])
            with self.subTest(field=field), self.assertRaises(ValueError): self.validate()
        self.entries["denoised"] = deepcopy(original)
        self.operations["controlled-denoised"] = deepcopy(operation)
        self.entries["denoised"]["frame_set"] = [2]
        self.operations["controlled-denoised"]["frame_set"] = [2]
        with self.assertRaises(ValueError): self.validate()


if __name__ == "__main__":
    unittest.main()
