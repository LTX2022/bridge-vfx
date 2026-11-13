# -*- coding: utf-8 -*-
"""C4: the artifact ledger is anchored to OPERATION FACTS.

The ledger takes a trusted operation-fact source; registration verifies the
operation exists, COMPLETED, and matches task/frames/output/scene.  A
caller-supplied receipt hash is only compared.  Freshness uses the
PRODUCTION start time.  raw_input provenance can never reach a render class;
final promotion requires receipt-backed confirmations and per-frame observed
hashes; version history stays queryable; concurrent promotions CAS.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dcc_task_runtime.artifact_registry import (ArtifactError, ArtifactRegistry,  # noqa: E402
                                                ARTIFACT_CLASSES, frame_path)
from dcc_task_runtime.exr_codec import encode_tiny_exr  # noqa: E402

SECRET = b"unit-test-control-secret-0123456789abcdef"


def _receipt(task_id="t1", artifact_id="a1"):
    return hashlib.sha256(f"{task_id}:{artifact_id}".encode()).hexdigest()


class _FactSource:
    """Trusted operation-fact source backed by real completed operations."""

    def __init__(self):
        self.facts: dict[str, dict] = {}

    def add(self, operation_id, task_id, frame_set, output_pattern, started_at_epoch, scene_fingerprint=""):
        self.facts[str(operation_id)] = {
            "task_id": task_id, "scene_fingerprint": scene_fingerprint,
            "frame_set": sorted({int(f) for f in frame_set}),
            "output_pattern": output_pattern, "state": "COMPLETED",
            "started_at_epoch": float(started_at_epoch),
            "operation_receipt_sha256": _receipt(task_id, operation_id)}

    def __call__(self, operation_id):
        return self.facts.get(str(operation_id))


class ArtifactRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="c4-ledger-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.registry = ArtifactRegistry(self.tmp / "ledger")
        self.facts = _FactSource()
        self.registry.set_operation_source(self.facts)
        self.pattern = str(self.tmp / "out.%03d.exr")
        self.started = 1000.0
        self.facts.add("op-1", "t1", [1, 2, 3], self.pattern, self.started, scene_fingerprint="scene-v1")

    def _register_cache(self, artifact_id="cache-v1", frames=(1, 2, 3), task_id="t1",
                        operation_id="op-1", colorspace="scene_linear", premultiplied=False,
                        dependencies=("sim-v1",), payload=None):
        return self.registry.register(artifact_id=artifact_id, task_id=task_id,
                                      artifact_class="preview_temp", pattern=self.pattern,
                                      frame_set=frames, colorspace=colorspace,
                                      premultiplied=premultiplied, dependencies=dependencies,
                                      payload=payload,
                                      operation_id=operation_id,
                                      operation_receipt_sha256=_receipt(task_id, operation_id),
                                      scene_fingerprint="scene-v1")

    def _write_real_exr(self, frames=(1, 2, 3)):
        for frame in frames:
            path = frame_path(self.pattern, frame)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encode_tiny_exr(float(frame)))

    def test_registration_without_operation_facts_is_refused(self) -> None:
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="x1", task_id="t1", artifact_class="preview_temp",
                                   pattern=self.pattern, frame_set=[1], colorspace="linear",
                                   premultiplied=False, operation_id="ghost-op",
                                   operation_receipt_sha256=_receipt())
        self.assertIn("OPERATION_NOT_FOUND", str(ctx.exception))

    def test_operation_mismatch_dimensions_are_refused(self) -> None:
        self.facts.add("op-other-task", "another-task", [1, 2, 3], self.pattern, self.started)
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="x2", task_id="t1", artifact_class="preview_temp",
                                   pattern=self.pattern, frame_set=[1, 2, 3], colorspace="linear",
                                   premultiplied=False, operation_id="op-other-task",
                                   operation_receipt_sha256=_receipt("another-task", "op-other-task"))
        self.assertIn("OPERATION_TASK_MISMATCH", str(ctx.exception))
        # frame mismatch
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="x3", task_id="t1", artifact_class="preview_temp",
                                   pattern=self.pattern, frame_set=[1, 2, 3, 4], colorspace="linear",
                                   premultiplied=False, operation_id="op-1",
                                   operation_receipt_sha256=_receipt("t1", "op-1"))
        self.assertIn("OPERATION_FRAME_MISMATCH", str(ctx.exception))
        # output mismatch
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="x4", task_id="t1", artifact_class="preview_temp",
                                   pattern=str(self.tmp / "elsewhere.%03d.exr"), frame_set=[1, 2, 3],
                                   colorspace="linear", premultiplied=False, operation_id="op-1",
                                   operation_receipt_sha256=_receipt("t1", "op-1"))
        self.assertIn("OPERATION_OUTPUT_MISMATCH", str(ctx.exception))
        # caller receipt hash only COMPARED against the fact source
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="x5", task_id="t1", artifact_class="preview_temp",
                                   pattern=self.pattern, frame_set=[1, 2, 3], colorspace="linear",
                                   premultiplied=False, operation_id="op-1",
                                   operation_receipt_sha256="f" * 64)
        self.assertIn("RECEIPT_MISMATCH", str(ctx.exception))

    def test_final_cannot_be_registered_directly_and_promotion_needs_receipt_facts(self) -> None:
        self.assertEqual(ARTIFACT_CLASSES, ("raw_input", "preview_temp", "confirmed_cache", "final_delivery"))
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.register(artifact_id="d1", task_id="t1", artifact_class="final_delivery",
                                   pattern=self.pattern, frame_set=[1], colorspace="linear",
                                   premultiplied=True, operation_id="op-1",
                                   operation_receipt_sha256=_receipt("t1", "op-1"))
        self.assertIn("FINAL_DELIVERY_REQUIRES_OPERATION", str(ctx.exception))
        self._register_cache()
        self._write_real_exr()
        # missing receipt-backed confirmations
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.promote("cache-v1", "final_delivery", verified_by="controller/e1",
                                  observed_sha256={f: "0" * 64 for f in (1, 2, 3)})
        self.assertIn("DELIVERY_CONFIRMATION_MISSING", str(ctx.exception))

    def test_promotion_with_full_receipt_confirmations_succeeds(self) -> None:
        self._register_cache()
        self._write_real_exr()
        report = self.registry.verify("cache-v1")
        entry = self.registry.lookup("cache-v1")
        entry["payload"]["delivery_confirmations"] = {
            "colorspace_confirmed": True, "premultiplied_confirmed": True,
            "dependencies_confirmed": True}
        with self.registry._connect() as db:
            db.execute("UPDATE artifacts SET payload_json=? WHERE artifact_id=?",
                       (json.dumps(entry, ensure_ascii=False, sort_keys=True), "cache-v1"))
        promoted = self.registry.promote("cache-v1", "final_delivery", verified_by="controller/e2",
                                         observed_sha256={f: report["frames"][f]["sha256"] for f in (1, 2, 3)})
        self.assertEqual(promoted["artifact_class"], "final_delivery")

    def test_freshness_uses_production_start_not_registration_time(self) -> None:
        self._register_cache()
        self._write_real_exr()
        report = self.registry.verify("cache-v1")
        self.assertTrue(report["fresh"], "frames written after production start are fresh")
        self.assertGreaterEqual(min(report["frames"][f]["mtime"] for f in report["frames"]),
                                self.started, "freshness anchored to the operation start")
        # registering the same content AGAIN (later) does not invalidate output
        self._register_cache()
        report = self.registry.verify("cache-v1")
        self.assertTrue(report["fresh"], "a later registration never invalidates real outputs")
        # and the production start is recorded separately from registration
        entry = self.registry.lookup("cache-v1")
        self.assertEqual(entry["production_started_at_epoch"], self.started)

    def test_fake_exr_bytes_and_real_magic_are_distinguished(self) -> None:
        self._register_cache()
        (frame_path(self.pattern, 1)).write_bytes(b"not-a-real-exr" * 16)
        self._write_real_exr(frames=(2, 3))
        report = self.registry.verify("cache-v1")
        self.assertFalse(report["readable"], "fake EXR bytes must fail the readability check")
        self.assertEqual(report["unreadable_frames"], [1])
        self.assertFalse(report["ok"])

    def test_exr_magic_padding_and_truncation_are_not_readable(self) -> None:
        self._register_cache(artifact_id="exr-structure")
        frame_path(self.pattern, 1).write_bytes(b"\x76\x2f\x31\x01" + b"\x00" * 2048)
        frame_path(self.pattern, 2).write_bytes(b"\x76\x2f\x31\x01")
        self._write_real_exr(frames=(3,))
        report = self.registry.verify("exr-structure")
        self.assertFalse(report["readable"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["unreadable_frames"], [1, 2])

    def test_active_duplicates_fail_but_static_preroll_duplicate_is_allowed(self) -> None:
        self._register_cache(artifact_id="active-duplicate", payload={"active_frames": [2]})
        duplicate = encode_tiny_exr(1.0)
        frame_path(self.pattern, 1).write_bytes(duplicate)
        frame_path(self.pattern, 2).write_bytes(duplicate)
        frame_path(self.pattern, 3).write_bytes(encode_tiny_exr(3.0))
        active_report = self.registry.verify("active-duplicate")
        self.assertFalse(active_report["no_duplicates"])
        self.assertEqual(active_report["active_duplicate_frames"], [2])
        self.assertFalse(active_report["ok"])

        self._register_cache(artifact_id="static-duplicate", payload={"active_frames": [2]})
        frame_path(self.pattern, 1).write_bytes(duplicate)
        frame_path(self.pattern, 2).write_bytes(encode_tiny_exr(2.0))
        frame_path(self.pattern, 3).write_bytes(duplicate)
        static_report = self.registry.verify("static-duplicate")
        self.assertTrue(static_report["ok"])
        self.assertTrue(static_report["no_duplicates"])
        self.assertEqual(static_report["duplicate_frames"], [3])
        self.assertEqual(static_report["active_duplicate_frames"], [])

    def test_missing_metadata_or_dependencies_is_not_usable_or_final(self) -> None:
        self._register_cache(artifact_id="missing-metadata", colorspace="", premultiplied=None,
                             dependencies=())
        self._write_real_exr()
        report = self.registry.verify("missing-metadata")
        self.assertFalse(report["metadata_present"])
        self.assertFalse(report["dependencies_present"])
        self.assertFalse(report["usable"])
        entry = self.registry.lookup("missing-metadata")
        entry["payload"]["delivery_confirmations"] = {
            "colorspace_confirmed": True,
            "premultiplied_confirmed": True,
            "dependencies_confirmed": True,
        }
        with self.registry._connect() as db:
            db.execute("UPDATE artifacts SET payload_json=? WHERE artifact_id=?",
                       (json.dumps(entry, ensure_ascii=False, sort_keys=True), "missing-metadata"))
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.promote("missing-metadata", "final_delivery", verified_by="controller/f08",
                                  observed_sha256={f: report["frames"][f]["sha256"] for f in (1, 2, 3)})
        self.assertIn("colorspace", str(ctx.exception))

        self._register_cache(artifact_id="missing-dependency", dependencies=())
        self._write_real_exr()
        dependency_report = self.registry.verify("missing-dependency")
        dependency_entry = self.registry.lookup("missing-dependency")
        dependency_entry["payload"]["delivery_confirmations"] = {
            "colorspace_confirmed": True,
            "premultiplied_confirmed": True,
            "dependencies_confirmed": True,
        }
        with self.registry._connect() as db:
            db.execute("UPDATE artifacts SET payload_json=? WHERE artifact_id=?",
                       (json.dumps(dependency_entry, ensure_ascii=False, sort_keys=True),
                        "missing-dependency"))
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.promote("missing-dependency", "final_delivery", verified_by="controller/f08-deps",
                                  observed_sha256={f: dependency_report["frames"][f]["sha256"] for f in (1, 2, 3)})
        self.assertIn("complete", str(ctx.exception))

    def test_concurrent_registration_allocates_serial_versions_and_history(self) -> None:
        first = ArtifactRegistry(self.tmp / "ledger")
        second = ArtifactRegistry(self.tmp / "ledger")
        first.set_operation_source(self.facts)
        second.set_operation_source(self.facts)

        def register(registry, marker):
            return registry.register(
                artifact_id="concurrent-register", task_id="t1", artifact_class="preview_temp",
                pattern=self.pattern, frame_set=[1, 2, 3], colorspace="scene_linear",
                premultiplied=False, dependencies=[marker], operation_id="op-1",
                operation_receipt_sha256=_receipt("t1", "op-1"), scene_fingerprint="scene-v1",
                payload={"marker": marker})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, (first, second), ("a", "b")))
        self.assertEqual(sorted(item["version"] for item in results), [1, 2])
        history = first.history("concurrent-register")
        self.assertEqual([item["version"] for item in history], [1, 2])
        self.assertEqual(first.lookup("concurrent-register")["version"], 2)

        # Pause the real file decoder, not SQLite or a synthetic delay. An
        # unrelated writer must commit while typed validation is still paused.
        from dcc_task_runtime import artifact_registry as registry_module
        decode = registry_module.read_exr
        for window in ('validation_wait', 'replace_during_validation', 'replace_at_admission'):
            with self.subTest(window=window):
                self._write_real_exr(frames=(1,))
                path=frame_path(self.pattern,1); info=path.stat()
                self.facts.add('typed-'+window,'t1',[1],self.pattern,self.started,'scene-v1')
                self.facts.facts['typed-'+window].update(completion_metadata_status='AVAILABLE',
                    frame_snapshots={'1':{'path':str(path),'bytes':info.st_size,
                        'modified_ns':info.st_mtime_ns,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}})
                entered,release=threading.Event(),threading.Event()
                owner={}; paused=[]
                def paused_decode(path, **kwargs):
                    if threading.get_ident()==owner.get('id') and not paused:
                        paused.append(True);entered.set()
                        if not release.wait(timeout=10):raise AssertionError('validation barrier not released')
                    return decode(path,**kwargs)
                def typed_register():
                    owner['id']=threading.get_ident()
                    return first.register(artifact_id='typed-'+window,task_id='t1',artifact_class='preview_temp',
                        pattern=self.pattern,frame_set=[1],colorspace='scene_linear',premultiplied=False,
                        dependencies=['sim-v1'],operation_id='typed-'+window,scene_fingerprint='scene-v1')
                def unrelated_register():
                    return second.register(artifact_id='unrelated-'+window,task_id='t1',artifact_class='preview_temp',
                        pattern=self.pattern,frame_set=[1,2,3],operation_id='op-1',scene_fingerprint='scene-v1')
                connect=first._connect
                class Connection:
                    def __init__(self):self.db=connect()
                    def __enter__(self):self.db.__enter__();return self
                    def __exit__(self,*args):return self.db.__exit__(*args)
                    def execute(self,sql,*args):
                        result=self.db.execute(sql,*args)
                        if sql=='BEGIN IMMEDIATE' and window=='replace_at_admission':
                            if os.name == 'nt':
                                path.write_bytes(encode_tiny_exr(92.))
                            else:
                                replacement=path.with_suffix('.replacement')
                                replacement.write_bytes(encode_tiny_exr(92.));os.replace(replacement,path)
                        return result
                with mock.patch.object(registry_module,'read_exr',side_effect=paused_decode), mock.patch.object(first,'_connect',side_effect=Connection), ThreadPoolExecutor(max_workers=2) as pool:
                    validating=pool.submit(typed_register)
                    try:
                        self.assertTrue(entered.wait(timeout=5),'actual file validation was not reached')
                        other=pool.submit(unrelated_register)
                        self.assertEqual(other.result(timeout=2)['version'],1)
                        self.assertFalse(validating.done())
                        if window=='replace_during_validation':path.write_bytes(encode_tiny_exr(91.))
                    finally:
                        release.set()
                    if window!='validation_wait':
                        with self.assertRaisesRegex(ArtifactError,'COMPLETION_BYTES_UNAVAILABLE'):validating.result(timeout=5)
                        self.assertEqual(first.history('typed-'+window),[])
                    else:self.assertEqual(validating.result(timeout=5)['version'],1)

    def test_concurrent_promotion_has_one_cas_winner_and_preserves_history(self) -> None:
        self._register_cache(artifact_id="concurrent-promote")
        self._write_real_exr()
        first = ArtifactRegistry(self.tmp / "ledger")
        second = ArtifactRegistry(self.tmp / "ledger")
        first.set_operation_source(self.facts)
        second.set_operation_source(self.facts)
        barrier = threading.Barrier(2)
        for registry in (first, second):
            original_lookup = registry.lookup

            def synchronized_lookup(artifact_id, original_lookup=original_lookup):
                value = original_lookup(artifact_id)
                barrier.wait(timeout=5)
                return value

            registry.lookup = synchronized_lookup

        def promote(registry, verified_by):
            try:
                return ("ok", registry.promote("concurrent-promote", "confirmed_cache",
                                                verified_by=verified_by))
            except ArtifactError as exc:
                return ("error", str(exc))

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(promote, (first, second), ("controller/a", "controller/b")))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        errors = [value for kind, value in outcomes if kind == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("PROMOTE_CAS_CONFLICT", errors[0])
        inspector = ArtifactRegistry(self.tmp / "ledger")
        self.assertEqual([item["version"] for item in inspector.history("concurrent-promote")], [1, 2])
        self.assertEqual(inspector.lookup("concurrent-promote")["artifact_class"], "confirmed_cache")

    def test_raw_lineage_can_never_reach_a_render_class(self) -> None:
        self.facts.add("op-raw", "t1", [1], self.pattern, self.started)
        self.registry.register(artifact_id="raw-1", task_id="t1", artifact_class="raw_input",
                               pattern=self.pattern, frame_set=[1],
                               operation_id="op-raw", operation_receipt_sha256=_receipt("t1", "op-raw"))
        with self.assertRaises(ArtifactError) as ctx:
            self.registry.promote("raw-1", "preview_temp", verified_by="controller/e3")
        self.assertIn("RAW_SOURCE_CAN_NEVER_RENDER", str(ctx.exception))

    def test_version_history_is_queryable_and_cas_protects_promotion(self) -> None:
        self._register_cache()
        self._write_real_exr()
        self.registry.register(artifact_id="cache-v1", task_id="t1", artifact_class="preview_temp",
                               pattern=self.pattern, frame_set=[1, 2, 3], colorspace="scene_linear",
                               premultiplied=False, dependencies=["sim-v1"],
                               operation_id="op-1", operation_receipt_sha256=_receipt("t1", "op-1"),
                               scene_fingerprint="scene-v1")
        self.assertEqual(self.registry.lookup("cache-v1")["version"], 2)
        old = self.registry.lookup_version("cache-v1", 1)
        self.assertIsNotNone(old)
        self.assertEqual(old["frame_set"], [1, 2, 3])
        self.assertEqual(len(self.registry.history("cache-v1")), 2)
        # concurrent-change CAS: a promotion computed from a STALE read loses
        from unittest import mock
        stale = self.registry.lookup("cache-v1")
        stale["version"] = 1  # what a stale reader saw
        real_lookup = self.registry.lookup
        with mock.patch.object(self.registry, "lookup", side_effect=[stale] + [real_lookup("cache-v1")]):
            with self.assertRaises(ArtifactError) as ctx:
                self.registry.promote("cache-v1", "confirmed_cache", verified_by="controller/e4")
        self.assertIn("PROMOTE_CAS_CONFLICT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
