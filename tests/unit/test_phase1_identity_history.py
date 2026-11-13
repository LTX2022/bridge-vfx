# -*- coding: utf-8 -*-
"""T03: request content binding, full execution history, legacy store control.

- The SAME request id with different content (frames, budget, pack binding)
  is refused with CONTENT_CHANGED instead of being treated as idempotent.
- Every state transition is appended to ``record["history"]`` with the acting
  generation; history is never truncated.
- A pre-hardening legacy store blocks the task; only the control plane can
  archive it with evidence, and the bytes are never merged or deleted.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_operation_runner_recovery import OperationRunnerCase, control_auth


class RequestContentBindingTests(OperationRunnerCase):
    def test_identical_resubmit_is_idempotent(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        first = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        again = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        self.assertTrue(again["idempotent"])
        self.assertEqual(first["operation_id"], again["operation_id"])

    def test_budget_change_on_same_request_is_refused(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        store = json.loads(m._fx_operations_store_path("t").read_text())
        record = store["operations"][op["operation_id"]]
        self.assertTrue(record["request_sha256"], "request content must be bound into the record")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"step_params": {"frames": [2, 4]}, "budget_seconds": 1.0}, "p", {})
        self.assertEqual(ctx.exception.code, "CONTENT_CHANGED")
        # the stored record stays untouched
        store = json.loads(m._fx_operations_store_path("t").read_text())
        self.assertEqual(store["operations"][op["operation_id"]]["state"], "QUEUED")

    def test_frame_set_change_maps_to_new_request_not_silent_rebind(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        runner.cancel(op["operation_id"])  # one heavy job per task at a time
        other = runner.submit({"step_params": {"frames": [2, 4, 6]}}, "p", {})
        self.assertNotEqual(op["operation_id"], other["operation_id"])
        self.assertEqual(other["record"]["state"], "QUEUED")


class ExecutionHistoryTests(OperationRunnerCase):
    def test_completed_operation_keeps_full_transition_history(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        runner.advance()
        record = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "COMPLETED")
        transitions = [(entry["from"], entry["to"]) for entry in record.get("history") or []]
        self.assertIn((None, "QUEUED"), transitions)  # submit-side initial transition
        self.assertIn(("QUEUED", "RUNNING"), transitions)
        self.assertIn(("RUNNING", "COMPLETED"), transitions)
        self.assertTrue(all(entry.get("generation") for entry in record["history"]))

    def test_reconcile_transition_is_recorded_not_silent(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        rec = store["operations"][op["operation_id"]]
        rec["state"] = "RUNNING"
        rec["claimed_by_generation"] = "dead-generation"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        fresh = m.OperationRunner("t")
        fresh.advance()
        record = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        transitions = [(entry["from"], entry["to"]) for entry in record.get("history") or []]
        self.assertIn(("RUNNING", "RECONCILE"), transitions)


class LegacyStoreControlTests(OperationRunnerCase):
    def test_legacy_block_requires_control_evidence_to_lift(self) -> None:
        m = self.m
        legacy = m._fx_legacy_operations_store_path("t")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"task_id": "t", "operations": {}}), encoding="utf-8")
        runner = m.OperationRunner("t")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "LEGACY_STORE_AMBIGUOUS")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.resolve_legacy_store({"verified_by": ""})
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")
        result = runner.resolve_legacy_store(control_auth("resolve_legacy_store", {"task_id": "t"}), "bytes reviewed")
        self.assertTrue(result["resolved"])
        self.assertTrue(Path(result["evidence"]).is_file(), "legacy bytes archived, never deleted")
        op = runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(op["record"]["state"], "QUEUED")

    def test_resolve_legacy_store_without_legacy_file_is_an_error(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.resolve_legacy_store(control_auth("resolve_legacy_store", {"task_id": "t"}))
        self.assertEqual(ctx.exception.code, "NO_LEGACY_STORE")


if __name__ == "__main__":
    unittest.main()
