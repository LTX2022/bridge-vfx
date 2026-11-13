"""Reject stale native receipts; no managed launch or positive dispatch claim.

Records originate from the actual addon using explicit in-process HOM APIs.
Each test first accepts that unmodified record through the pure validator;
this control proves no managed launch, transport or positive worker execution.
Only rejection cases rewrite identity and recompute public integrity digests.
No supervisor started receipt, worker process, TCP or real DCC is created.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))
sys.path.insert(0, str(ROOT / "tests/unit"))

from source_host_fixture import FakeSourceHost
from houdini_bridge.operation_receipts import operation_receipt_sha256, validate_operation_receipt
from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_job_worker import GraphJobWorker, _verify_native_dispatch_receipt


class GraphJobNativeReceiptRejectionTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py"
        spec = importlib.util.spec_from_file_location("_native_receipt_rejection_addon", source)
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)
        host = self.enterContext(FakeSourceHost(self.addon))
        self.task_id = "native-receipt-rejection-unit"
        self.launch_nonce = "explicit-inproc-unit-boundary"
        self.addon._TASK_HOST_IDENTITY = dict(
            self.addon._host_identity(), task_id=self.task_id, pid=os.getpid(),
            launch_nonce=self.launch_nonce, plugin_build=self.addon._FX_LOADED_ADDON_SHA256,
            version=host.version)
        self.request = {
            "task_id": self.task_id, "operation_id": "historical-native-root",
            "request_id": "historical-native-root", "frozen_input_manifest": [],
            "parent": "/obj", "type": "geo", "root_name": "BRIDGE_GRAPH_" + "ab" * 32,
        }
        self.result = self.addon.dispatch("scene.create_task_root", self.request)
        self.receipt = deepcopy(self.result["operation_receipt"])
        validate_operation_receipt(self.receipt)
        self.expected = {
            "command": "scene.create_task_root", "request": deepcopy(self.request),
            "result": deepcopy(self.result), "task_id": self.task_id,
            "host_identity": self.addon._host_identity(),
            "launch_nonce": self.launch_nonce, "plugin_build": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        self.assertEqual(self.expected["plugin_build"], self.addon._FX_LOADED_ADDON_SHA256)
        self.assertEqual(self.expected["host_identity"], self.receipt["host_identity"])
        verified = _verify_native_dispatch_receipt(self.receipt, **self.expected)
        self.assertEqual(verified, self.receipt)
        self.assertIsNot(verified, self.receipt)

    def reject(self, receipt=None, **changes):
        record = deepcopy(self.receipt if receipt is None else receipt)
        validate_operation_receipt(record)
        before = deepcopy(record)
        with self.assertRaisesRegex(ValueError, "native producer does not bind actual dispatch/request/process/result"):
            _verify_native_dispatch_receipt(record, **(self.expected | changes))
        self.assertEqual(record, before)

    def stale_host_record(self, field, value):
        record = deepcopy(self.receipt)
        record["host_identity"][field] = value
        self.assertEqual([key for key in record["host_identity"]
                          if record["host_identity"][key] != self.receipt["host_identity"][key]], [field])
        for phase in ("before_scene", "after_scene"):
            record[phase]["host_identity"] = deepcopy(record["host_identity"])
        record["operation_receipt_sha256"] = operation_receipt_sha256(record)
        return record

    def test_previous_operation_request_and_command_are_rejected(self):
        for field in ("operation_id", "request_id"):
            with self.subTest(field=field):
                request = deepcopy(self.request)
                request[field] = "current-injected-native-id"
                self.reject(request=request)
        request = deepcopy(self.request)
        request["root_name"] += "_changed_request"
        self.reject(request=request)
        self.reject(command="node.create")

    def test_previous_task_owner_is_rejected(self):
        self.reject(task_id="current-task-owner")

    def test_different_actual_handler_result_is_rejected(self):
        result = deepcopy(self.result)
        result["path"] += "_different_current_result"
        self.reject(result=result)

    def test_previous_pid_attempt_session_and_process_generation_are_rejected(self):
        identity = self.receipt["host_identity"]
        for field, value in (
            ("pid", os.getpid() + 1), ("launch_nonce", identity["launch_nonce"] + "_old_attempt"),
            ("session_id", identity["session_id"] + "_old_session"),
            ("process_generation", identity["process_generation"] + "_old_generation"),
        ):
            with self.subTest(field=field):
                self.reject(self.stale_host_record(field, value))

    def test_receipt_from_different_loaded_addon_source_is_rejected(self):
        stale_sha = "0" * 64 if self.expected["plugin_build"] != "0" * 64 else "1" * 64
        self.reject(self.stale_host_record("plugin_build", stale_sha))

    def persisted_evidence_control(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / "outputs")))
        runner = self.addon.fx_operation_runner(self.task_id)
        path = Path(self.result["operation_store_path"])
        payload = path.read_bytes()
        self.assertEqual(self.result["operation_store_format"], "producer_record")
        self.assertEqual(json.loads(payload), self.receipt)
        self.assertTrue(path.is_relative_to(runner.path.parent))
        descriptor = {key: self.receipt[key] for key in (
            "schema", "task_id", "operation_id", "request_id", "command", "kind", "state",
            "operation_receipt_sha256", "request_sha256", "host_identity")}
        descriptor.update(handler_result_sha256=self.receipt["facts"]["handler_result_sha256"],
                          storage_format=self.result["operation_store_format"], path=str(path),
                          bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        compiled = graph_catalog.compile_proposal({
            "schema_version": "1.0", "nodes": [{"node_id": "sphere", "node_type": "sop.sphere",
                "context": "houdini_sop", "parameters": {"radx": 1.0, "rady": 1.0, "radz": 1.0}}],
            "outputs": [{"output_id": "output", "node_id": "sphere", "port": "geometry"}],
        })
        worker = GraphJobWorker.__new__(GraphJobWorker)
        worker.addon, worker.root, worker.execution_task_id = self.addon, root, self.task_id
        worker.operation_id, worker.result_path = "inproc-publication-control", root / "result.json"
        worker.job = {"attempt_token": self.launch_nonce, "attempt_generation": 1}
        worker.native_operation_receipts = [deepcopy(descriptor)]
        published = worker._native_receipt_evidence(compiled)
        publication = Path(published["path"])
        actual = publication.read_bytes()
        self.assertEqual(published["schema"], "bridge.houdini.native-command-evidence/2.0")
        self.assertEqual(json.loads(actual)["receipts"], [descriptor])
        self.assertEqual(published["bytes"], len(actual))
        self.assertEqual(published["sha256"], hashlib.sha256(actual).hexdigest())
        self.assertEqual(path.read_bytes(), payload)
        publication.unlink()
        return worker, compiled, path, payload, publication

    def test_persisted_producer_tampering_refused_before_publication(self):
        worker, compiled, path, payload, publication = self.persisted_evidence_control()
        self.assertTrue(payload.endswith(b"\n"))
        for label, changed in (("same_bytes_changed_sha", payload[:-1] + b" "),
                               ("changed_byte_count", payload + b"\n")):
            with self.subTest(boundary=label):
                path.write_bytes(changed)
                self.assertEqual(json.loads(changed), self.receipt)
                with self.assertRaisesRegex(ValueError, "native producer evidence bytes changed before publication"):
                    worker._native_receipt_evidence(compiled)
                self.assertFalse(publication.exists())

    def test_persisted_producer_deletion_refused_before_publication(self):
        worker, compiled, path, _, publication = self.persisted_evidence_control()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "evidence file is missing"):
            worker._native_receipt_evidence(compiled)
        self.assertFalse(publication.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
