"""Pure service/filesystem checks; dispatch and threads are explicit boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dcc_task_runtime.canonical import canonical_sha256
from vfx_pipeline.graph_construction_inputs import freeze_construction_inputs
from vfx_pipeline.graph_jobs import GraphJobError, GraphJobService


class FrozenConstructionInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "中文 空格 基准.json"
        self.path.write_bytes(b'{"explicit":"file bytes only"}')
        self.manifest = [self.item(self.path)]
        self.repo = self.root / "runtime"
        for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
            directory = self.repo / "packages" / package / "src"
            directory.mkdir(parents=True)
            (directory / "fixture.py").write_text("", encoding="utf-8")
        addon = self.repo / "plugins/houdini/_impl/houdini_bridge_addon.py"
        addon.parent.mkdir(parents=True)
        addon.write_text("", encoding="utf-8")
        self.dispatched = []

    def item(self, path, *, index=0, role="geometry_rest_basis"):
        raw = path.read_bytes()
        return {"index": index, "asset_id": "explicit-rest", "semantic_role": role,
                "source_uri": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "metadata": {"tags": ["显式来源"]}}

    def dispatch(self, job):
        self.dispatched.append(job)
        return {"construction_executed": False}

    def service(self, manifest=None):
        service = GraphJobService(self.root / "service", self.repo, "REAL_DCC_NOT_RUN",
                                  scheduler_root=self.root / "installation",
                                  worker_factory=self.dispatch, frozen_input_manifest=manifest)
        self.addCleanup(service.close)
        return service

    def prepare(self, service, request="trial-1"):
        proposal = {"schema_version": "1.0", "nodes": [{"node_id": "sphere",
                    "node_type": "sop.sphere", "context": "houdini_sop", "parameters": {}}],
                    "outputs": [{"output_id": "output", "node_id": "sphere", "port": "geometry"}]}
        graph = service.propose(proposal, "proposal-1")
        with mock.patch("vfx_pipeline.graph_jobs.threading.Thread.start"):
            operation = service.trial(graph, request)
        return graph, operation

    def launch(self, service, operation):
        row = service._row(operation)
        service._launch(operation, service.compiled_graph(row["graph_id"]),
                        row["process_token"], row["attempt_generation"])

    def tamper(self, service, operation, edit):
        row = service._row(operation)
        intent = json.loads(row["intent_json"])
        edit(intent)
        with service._connect() as database:
            database.execute("UPDATE operations SET intent_json=? WHERE operation_id=?",
                             (json.dumps(intent, ensure_ascii=False), operation))

    def test_missing_manifest_backward_compatible_persistence(self):
        self.assertEqual([], freeze_construction_inputs(None))
        service = self.service()
        _, operation = self.prepare(service)
        self.launch(service, operation)
        job = self.dispatched[0]
        self.assertEqual([], job["frozen_input_manifest"])
        self.assertEqual(canonical_sha256([]), job["frozen_inputs_sha256"])
        intent = json.loads(service._row(operation)["intent_json"])
        self.assertEqual([], intent["frozen_input_manifest"])
        self.assertEqual(canonical_sha256([]), intent["frozen_inputs_sha256"])

    def test_immutable_clone_persisted_intent_inputs_and_dispatch(self):
        expected = copy.deepcopy(self.manifest)
        service = self.service(self.manifest)
        self.manifest[0]["metadata"]["tags"].append("caller mutation")
        detached = service.frozen_input_manifest
        detached[0]["metadata"]["tags"].clear()
        with self.assertRaises(AttributeError):
            service.frozen_input_manifest = []
        _, operation = self.prepare(service)
        self.launch(service, operation)
        job = self.dispatched[0]
        inputs = json.loads(Path(job["inputs_path"]).read_text(encoding="utf-8"))
        intent = json.loads(service._row(operation)["intent_json"])
        for carrier in (job, inputs, intent):
            self.assertEqual(expected, carrier["frozen_input_manifest"])
            self.assertEqual(canonical_sha256(expected), carrier["frozen_inputs_sha256"])
        job["frozen_input_manifest"][0]["metadata"]["tags"].clear()
        self.assertEqual(expected, service.frozen_input_manifest)
        self.assertNotIn("geometry_observation", expected[0])

    def test_same_request_no_replay_even_when_file_is_later_missing(self):
        service = self.service(self.manifest)
        graph, operation = self.prepare(service)
        self.launch(service, operation)
        self.path.unlink()
        self.assertEqual(operation, service.trial(graph, "trial-1"))
        self.assertEqual(1, len(self.dispatched))

    def test_prelaunch_content_drift_never_dispatches(self):
        service = self.service(self.manifest)
        _, operation = self.prepare(service)
        self.path.write_bytes(b"X" * self.manifest[0]["bytes"])
        self.launch(service, operation)
        self.assertEqual([], self.dispatched)
        self.assertEqual("RECONCILIATION_REQUIRED", service.status(operation)["state"])
        with self.assertRaises(GraphJobError):
            service.reconcile(operation, resume_not_started=True)
        self.assertEqual(1, service._row(operation)["attempt_generation"])

    def test_drift_during_preflight_never_arms_or_dispatches(self):
        service = self.service(self.manifest)
        _, operation = self.prepare(service)

        def preflight(**kwargs):
            self.path.write_bytes(b"X" * self.manifest[0]["bytes"])
            return {"status": "PASS"}

        guard = SimpleNamespace(owner={}, check=preflight)
        service._budget_guards[operation] = guard
        service.resource_budget = {}
        self.launch(service, operation)
        self.assertEqual([], self.dispatched)
        row = service._row(operation)
        self.assertTrue(service.scheduler.fence_unstarted(
            str(service.root), operation, row["process_token"]))

    def test_persisted_manifest_and_digest_tamper_refused_without_dispatch(self):
        for field in ("frozen_input_manifest", "frozen_inputs_sha256"):
            with self.subTest(field=field):
                service = self.service(self.manifest)
                request = "trial-" + field
                graph, operation = self.prepare(service, request)
                original = json.loads(service._row(operation)["intent_json"])
                self.tamper(service, operation,
                            lambda intent: intent.update({field: [] if field.endswith("manifest") else "0" * 64}))
                with self.assertRaises(GraphJobError):
                    service.trial(graph, request)
                with self.assertRaises(GraphJobError):
                    service.reconcile(operation, resume_not_started=True)
                self.launch(service, operation)
                self.assertEqual([], self.dispatched)
                self.tamper(service, operation, lambda intent: intent.update(original))
                service.cancel(operation)
                service.close()

    def test_reconnect_refuses_new_config_even_with_rehashed_intent(self):
        first = self.service(self.manifest)
        graph, operation = self.prepare(first)
        second = self.service([])
        with self.assertRaisesRegex(GraphJobError, "drift"):
            second.trial(graph, "trial-1")
        with self.assertRaisesRegex(GraphJobError, "drift"):
            second.reconcile(operation, resume_not_started=True)
        altered = copy.deepcopy(self.manifest)
        altered[0]["asset_id"] = "different-source"
        self.tamper(first, operation, lambda intent: intent.update(
            frozen_input_manifest=altered, frozen_inputs_sha256=canonical_sha256(altered)))
        with self.assertRaisesRegex(GraphJobError, "drift"):
            first.reconcile(operation, resume_not_started=True)
        self.assertEqual([], self.dispatched)

    def test_reconnect_resumes_original_intent_once_then_retry_is_stable(self):
        first = self.service(self.manifest)
        graph, operation = self.prepare(first)
        second = self.service(copy.deepcopy(self.manifest))
        original = second._row(operation)["intent_json"]
        with mock.patch("vfx_pipeline.graph_jobs.threading.Thread.start"):
            second.reconcile(operation, resume_not_started=True)
        self.assertEqual(original, second._row(operation)["intent_json"])
        self.assertEqual(2, second._row(operation)["attempt_generation"])
        self.launch(second, operation)
        self.assertEqual(self.manifest, self.dispatched[0]["frozen_input_manifest"])
        self.assertEqual(operation, second.trial(graph, "trial-1"))
        second.reconcile(operation, resume_not_started=True)
        self.assertEqual(1, len(self.dispatched))

    def test_legacy_empty_intent_can_resume_but_cannot_acquire_new_inputs(self):
        first = self.service()
        _, operation = self.prepare(first)
        self.tamper(first, operation, lambda intent: (
            intent.pop("frozen_input_manifest"), intent.pop("frozen_inputs_sha256")))
        second = self.service()
        with mock.patch("vfx_pipeline.graph_jobs.threading.Thread.start"):
            second.reconcile(operation, resume_not_started=True)
        self.launch(second, operation)
        self.assertEqual([], self.dispatched[0]["frozen_input_manifest"])
        third = self.service(self.manifest)
        with self.assertRaisesRegex(GraphJobError, "drift"):
            third.reconcile(operation)

    def test_invalid_metadata_and_nonlocal_identities(self):
        edits = [{"index": True}, {"index": 1}, {"asset_id": ""}, {"semantic_role": None},
                 {"sha256": "A" * 64}, {"sha256": "g" * 64}, {"bytes": True}, {"bytes": -1},
                 {"metadata": {"number": float("nan")}}, {"metadata": float("inf")},
                 {"metadata": {1: "bad key"}}, {"metadata": {"bad": {1, 2}}},
                 {"geometry_observation": False}, {"source_uri": "relative.json"},
                 {"source_uri": r"\\server\share\file"}, {"source_uri": "//server/share/file"},
                 {"source_uri": str(self.path) + ":stream"}, {"source_uri": "data:text/plain,abc"},
                 {"source_uri": str(self.path.parent / ".." / self.path.name)},
                 {"identity": str(self.path.parent / "other")}, {"frames": []}]
        for edit in edits:
            with self.subTest(edit=repr(edit)):
                value = copy.deepcopy(self.manifest)
                value[0].update(edit)
                with self.assertRaises(ValueError):
                    freeze_construction_inputs(value, verify_files=False)
        identity = copy.deepcopy(self.manifest)
        identity[0]["identity"] = identity[0].pop("source_uri")
        self.assertEqual(identity, freeze_construction_inputs(identity))
        for value in ({}, (), [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                freeze_construction_inputs(value)

    def test_item_basis_other_total_and_metadata_budgets_checked_before_read(self):
        for role, size in (("geometry_rest_basis", 65537), ("other", 8 * 1024 * 1024 + 1)):
            value = copy.deepcopy(self.manifest)
            value[0].update(semantic_role=role, bytes=size)
            with self.subTest(role=role), mock.patch("os.open") as opened:
                with self.assertRaisesRegex(ValueError, "budget"):
                    freeze_construction_inputs(value)
                opened.assert_not_called()
        oversized = [dict(self.manifest[0], index=index, semantic_role="other", bytes=8 * 1024 * 1024)
                     for index in range(5)]
        too_many = [dict(self.manifest[0], index=index, bytes=0) for index in range(33)]
        metadata = [dict(self.manifest[0], metadata=["x" * 8192] * 9)]
        cyclic = []; cyclic.append(cyclic)
        for value in (oversized, too_many, metadata, cyclic):
            with self.subTest(kind=type(value).__name__), mock.patch("os.open") as opened:
                with self.assertRaises(ValueError):
                    freeze_construction_inputs(value)
                opened.assert_not_called()
        boundary = [dict(self.manifest[0], index=index, semantic_role="other", bytes=8 * 1024 * 1024)
                    for index in range(4)]
        self.assertEqual(boundary, freeze_construction_inputs(boundary, verify_files=False))
        self.path.write_bytes(b"")
        self.assertEqual(0, freeze_construction_inputs([self.item(self.path)])[0]["bytes"])

    def test_stable_descriptor_read_detects_byte_race_and_uses_bounded_reads(self):
        self.path.write_bytes(b"a" * 65536)
        value = [self.item(self.path)]
        native_read = os.read
        lengths = []

        def read(descriptor, count):
            lengths.append(count)
            block = native_read(descriptor, count)
            if len(lengths) == 1:
                self.path.write_bytes(b"b" * 65536)
            return block

        with mock.patch("os.read", side_effect=read), self.assertRaises(ValueError):
            freeze_construction_inputs(value)
        self.assertTrue(all(0 < count <= 65536 for count in lengths))

    def test_hardlinks_reparse_and_symlink_ancestors_refused(self):
        hardlink = self.root / "hardlink.json"
        os.link(self.path, hardlink)
        with self.assertRaises(ValueError):
            freeze_construction_inputs(self.manifest)
        hardlink.unlink()
        native_stat = Path.lstat

        for target, flag in ((self.path, "reparse"), (self.path.parent, "symlink")):
            def observation(path, *args, **kwargs):
                info = native_stat(path, *args, **kwargs)
                if path != target:
                    return info
                fields = {name: getattr(info, name) for name in (
                    "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")}
                if flag == "reparse":
                    fields["st_file_attributes"] = 0x400
                else:
                    fields["st_mode"] = 0o120777
                return SimpleNamespace(**fields)

            with self.subTest(flag=flag), mock.patch.object(Path, "lstat", observation):
                with self.assertRaises(ValueError):
                    freeze_construction_inputs(self.manifest)


if __name__ == "__main__":
    unittest.main()
