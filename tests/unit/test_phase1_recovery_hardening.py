# -*- coding: utf-8 -*-
"""Phase-1 hardening regressions for OperationRunner.

Covers the acceptance gaps from the independent review:
- corrupt stores block REPEATED reads and service restarts (never empty-store);
- ``reconciled`` model params can no longer archive a RECONCILE record — the
  control channel (resolve_reconcile) is the only path;
- an idle executor must not release the installation heavy slot of another
  operation;
- distinct task ids never collide on one store; legacy stores are blocked,
  not auto-merged;
- cancellation request and confirmed stop are recorded separately.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_operation_runner_recovery import OperationRunnerCase, control_auth


class CorruptStoreBlockingTests(OperationRunnerCase):
    def test_corrupt_store_blocks_repeated_reads_and_restarts(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        runner.submit({"frames": [2]}, "p", {})
        m._fx_operations_store_path("t").write_text("{corrupt", encoding="utf-8")
        for attempt in range(2):
            with self.assertRaises(m.BridgeCommandError) as ctx:
                runner.submit({"frames": [2]}, "p", {})
            self.assertEqual(ctx.exception.code, "CORRUPT_STORE", "attempt {}".format(attempt))
        # a fresh instance (service restart) must stay blocked, not see an empty store
        fresh = m.OperationRunner("t")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            fresh.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "CORRUPT_STORE")
        blocked = self.tmp_path / "ops_t.json.corrupt-blocked"
        self.assertTrue(blocked.is_file(), "persistent block marker must exist")
        preserved = [p for p in self.tmp_path.glob("ops_t.json.corrupt-*") if p.name != "ops_t.json.corrupt-blocked"]
        self.assertTrue(preserved, "original bytes preserved")

    def test_resolve_corrupt_store_requires_operator_and_keeps_evidence(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        runner.cancel(op["operation_id"])  # terminal: slot released, store intact
        m._fx_operations_store_path("t").write_text("{corrupt", encoding="utf-8")
        with self.assertRaises(m.BridgeCommandError):
            runner.resolve_corrupt_store({"verified_by": "controller/evidence-1"})
        result = runner.resolve_corrupt_store(control_auth("resolve_corrupt_store", {"task_id": "t"}), "bytes verified")
        self.assertTrue(result["resolved"])
        evidence = Path(result["evidence"])
        self.assertTrue(evidence.is_file(), "corrupt evidence must be archived, never deleted")
        # after resolution the store accepts new work again
        op = runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(op["record"]["state"], "QUEUED")


class ReconcileControlTests(OperationRunnerCase):
    def _reconcile_record(self):
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        rec = store["operations"][op["operation_id"]]
        rec["state"] = "RECONCILE"
        rec["claimed_by_generation"] = "dead-generation"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        return m, runner, op

    def test_reconciled_param_can_no_longer_archive(self) -> None:
        m, runner, op = self._reconcile_record()
        # simulate the control plane verifying the stale holder is gone
        slot = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]["slot"]
        m._fx_graph_scheduler().release(slot["owner_root"], slot["operation_id"], slot["token"], stopped=True)
        result = runner.submit({"step_params": {"frames": [2, 4]}, "reconciled": True}, "p", {})
        self.assertEqual(result.get("blocked"), "RECONCILE")
        self.assertTrue(result.get("idempotent"))
        record = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "RECONCILE", "model params must never archive a reconcile record")
        self.assertNotIn("superseded_by_request", record)

    def test_resolve_reconcile_requeue_and_archive(self) -> None:
        m, runner, op = self._reconcile_record()
        with self.assertRaises(m.BridgeCommandError):
            runner.resolve_reconcile(op["operation_id"], "rerun", control_auth("resolve_reconcile", {"task_id": "t", "request_id": op["operation_id"], "decision": "rerun"}))
        old_generation = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]["slot"]["generation"]
        old_record = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]
        requeue_evidence = {
            "kind": "confirmed_not_started", "task_id": "t",
            "request_id": op["operation_id"],
            "slot_generation": old_record["slot"]["generation"],
            "slot_token": old_record["slot"]["token"],
            "observed_at": "2026-09-27T00:00:00+00:00", "source": "unit-test-control",
            "confirmed": True, "side_effect_started": False,
        }
        record = runner.resolve_reconcile(
            op["operation_id"], "requeue",
            control_auth("resolve_reconcile", {
                "task_id": "t", "request_id": op["operation_id"], "decision": "requeue",
                "evidence": requeue_evidence,
            }),
            "host proved no cook ran", evidence=requeue_evidence,
        )
        self.assertEqual(record["state"], "QUEUED")
        self.assertEqual(record["reconcile_resolution"]["decision"], "requeue")
        self.assertEqual(record["slot"]["generation"], old_generation + 1, "requeue must rotate to a fresh reservation")
        self.assertEqual(m._test_scheduler.snapshot()["active"], 1, "requeued work keeps holding the slot")
        # after requeue the same control channel can still archive later RECONCILE states
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        store["operations"][op["operation_id"]]["state"] = "RECONCILE"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        current = store["operations"][op["operation_id"]]
        archive_evidence = {
            "kind": "confirmed_not_started", "task_id": "t",
            "request_id": op["operation_id"],
            "slot_generation": current["slot"]["generation"],
            "slot_token": current["slot"]["token"],
            "observed_at": "2026-09-27T00:01:00+00:00", "source": "unit-test-control",
            "confirmed": True, "side_effect_started": False,
        }
        record = runner.resolve_reconcile(
            op["operation_id"], "archive",
            control_auth("resolve_reconcile", {
                "task_id": "t", "request_id": op["operation_id"], "decision": "archive",
                "evidence": archive_evidence,
            }), evidence=archive_evidence,
        )
        self.assertEqual(record["state"], "SUPERSEDED")
        self.assertEqual(m._test_scheduler.snapshot()["active"], 0, "archived record releases the slot")

    def test_live_process_shape_without_persisted_stop_fact_is_rejected(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        record["state"] = "RECONCILE"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        process = record["process"]
        evidence = {
            "kind": "confirmed_stop", "task_id": "t",
            "request_id": op["operation_id"],
            "slot_generation": record["slot"]["generation"],
            "slot_token": record["slot"]["token"],
            "observed_at": record["lifecycle_fact"]["observed_at"],
            "source": "controller/review",
            "confirmed": True, "process_exited": True, "stop_confirmed": True,
            "process_generation": process["process_generation"],
            "process_identity": process["process_identity"],
            "pid": process["pid"], "attempt_id": record["execution_id"],
            "exit_code": 0,
        }
        before_generation = int(record["slot"]["generation"])
        with self.assertRaisesRegex(m.BridgeCommandError, "persisted controller-confirmed stop"):
            runner.resolve_reconcile(
                op["operation_id"], "requeue",
                control_auth("resolve_reconcile", {
                    "task_id": "t", "request_id": op["operation_id"],
                    "decision": "requeue", "evidence": evidence,
                }), evidence=evidence)
        unchanged = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(unchanged["state"], "RECONCILE")
        self.assertEqual(int(unchanged["slot"]["generation"]), before_generation)

    def test_persisted_stop_fact_allows_confirmed_stop_archive(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        runner.advance()
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "COMPLETED")
        fact = record["lifecycle_fact"]
        record["state"] = "RECONCILE"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        evidence = {
            "kind": "confirmed_stop", "task_id": "t",
            "request_id": op["operation_id"],
            "slot_generation": record["slot"]["generation"],
            "slot_token": record["slot"]["token"],
            "observed_at": fact["observed_at"], "source": fact["source"],
            "confirmed": True, "process_exited": True, "stop_confirmed": True,
            "process_generation": fact["process_generation"],
            "process_identity": fact["process_identity"],
            "pid": fact["pid"], "attempt_id": fact["attempt_id"],
            "exit_code": 0, "lifecycle_fact_digest": fact["fact_digest"],
        }
        archived = runner.resolve_reconcile(
            op["operation_id"], "archive",
            control_auth("resolve_reconcile", {
                "task_id": "t", "request_id": op["operation_id"],
                "decision": "archive", "evidence": evidence,
            }), evidence=evidence)
        self.assertEqual(archived["state"], "SUPERSEDED")

    def test_control_signed_boolean_stop_receipt_is_rejected(self) -> None:
        """Control authority and caller booleans cannot attest an OS exit."""
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        runner.advance()  # leaves frame 4 pending and the owned process RUNNING
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "RUNNING")
        started = record["lifecycle_fact"]
        self.assertEqual(started["kind"], "STARTED")
        record["state"] = "RECONCILE"  # supervisor observed the lost controller handle
        store_path.write_text(json.dumps(store), encoding="utf-8")
        process = record["process"]
        evidence = {
            "kind": "confirmed_stop", "task_id": "t",
            "request_id": op["operation_id"],
            "slot_generation": record["slot"]["generation"],
            "slot_token": record["slot"]["token"],
            "observed_at": started["observed_at"],
            "source": "supervisor/task-host-1",
            "confirmed": True, "process_exited": True, "stop_confirmed": True,
            "process_generation": started["process_generation"],
            "process_identity": started["process_identity"],
            "pid": process["pid"], "attempt_id": started["attempt_id"],
            "exit_code": 0,
            "lifecycle_fact_digest": started["fact_digest"],
            "supervisor_receipt": {
                "schema": "bridge.houdini.supervisor_stop_receipt/1.0",
                "trusted": True,
                "started_fact_digest": started["fact_digest"],
                "process_generation": started["process_generation"],
                "process_identity": started["process_identity"],
            },
        }
        with self.assertRaises(m.BridgeCommandError):
            runner.import_external_stop_fact(
                op["operation_id"], evidence,
                control_auth("import_stop_fact", {"task_id": "t", "request_id": op["operation_id"], "evidence": evidence}))
        self.assertEqual(m._test_scheduler.snapshot()["active"], 1)

    def test_resolve_reconcile_rejects_non_reconcile_records(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})  # QUEUED, not RECONCILE
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.resolve_reconcile(op["operation_id"], "archive", control_auth("resolve_reconcile", {"task_id": "t", "request_id": op["operation_id"], "decision": "archive"}))
        self.assertEqual(ctx.exception.code, "NOT_RECONCILE")


class HeavySlotOwnershipTests(OperationRunnerCase):
    def _slot_active(self) -> bool:
        snapshot = self.m._test_scheduler.snapshot()
        return bool(snapshot and snapshot["active"])

    def test_idle_executor_does_not_release_foreign_slot(self) -> None:
        m = self.m
        a = m.OperationRunner("taskA")
        b = m.OperationRunner("taskB")
        op = a.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        a.advance()  # frame 2 done; frame 4 pending -> A still holds the slot
        # B has no active work; its advance must not free A's installation slot
        b.advance()
        self.assertTrue(self._slot_active(), "idle executor must not release the slot")
        record = json.loads(m._fx_operations_store_path("taskA").read_text())["operations"][op["request_id"]]
        self.assertEqual(record["state"], "RUNNING")
        # the OWNER's terminal state releases the slot
        a.cancel(op["request_id"])
        self.assertFalse(self._slot_active(), "owner terminal state frees the slot")

    def test_second_submit_refused_while_first_active(self) -> None:
        m = self.m
        a = m.OperationRunner("taskA")
        b = m.OperationRunner("taskB")
        op = a.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        a.advance()  # frame 2 done; frame 4 still pending -> slot held
        self.assertTrue(self._slot_active())
        with self.assertRaises(m.BridgeCommandError) as ctx:
            b.submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        a.cancel(op["request_id"])
        self.assertFalse(self._slot_active(), "cancel terminal state frees the slot")


class TaskIdentityTests(OperationRunnerCase):
    def test_distinct_task_ids_never_share_a_store_name(self) -> None:
        m = self.m
        self.assertNotEqual(m._task_name("task-01", "ops"), m._task_name("task-x01", "ops"))
        a = m.OperationRunner("task-01")
        b = m.OperationRunner("task-x01")
        self.assertNotEqual(a.path, b.path)
        op_a = a.submit({"frames": [2]}, "p", {})
        # installation slot is held by A's queued work: B cannot start yet
        with self.assertRaises(m.BridgeCommandError) as ctx:
            b.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        a.cancel(op_a["operation_id"])  # release the slot
        op_b = b.submit({"frames": [2]}, "p", {})
        store_a = json.loads(a.path.read_text())
        store_b = json.loads(b.path.read_text())
        self.assertEqual(store_a["task_id"], "task-01")
        self.assertEqual(store_b["task_id"], "task-x01")
        self.assertNotIn(op_b["operation_id"], store_a["operations"])
        self.assertNotIn(op_a["operation_id"], store_b["operations"])

    def test_store_created_for_another_task_is_conflict(self) -> None:
        m = self.m
        store = m._fx_operations_store_path("t")
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"task_id": "someone-else", "operations": {}}), encoding="utf-8")
        runner = m.OperationRunner("t")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "TASK_IDENTITY_CONFLICT")

    def test_legacy_store_is_blocked_not_merged(self) -> None:
        m = self.m
        legacy = m._fx_legacy_operations_store_path("t")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"task_id": "t", "operations": {}}), encoding="utf-8")
        runner = m.OperationRunner("t")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "LEGACY_STORE_AMBIGUOUS")


class CancellationRecordingTests(OperationRunnerCase):
    def test_cancel_before_work_records_request_and_stop(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        record = runner.cancel(op["operation_id"])
        self.assertEqual(record["state"], "CANCELLED")
        self.assertEqual(record["stage"], "cancelled_before_observed_work")
        self.assertTrue(record["cancel_requested_at"])
        self.assertTrue(record["stop_confirmed_at"])

    def test_cancel_during_cook_defers_stop_confirmation(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        runner._in_cook = True  # simulate an uninterruptible cook
        record = runner.cancel(op["operation_id"])
        self.assertEqual(record["state"], "CANCEL_PENDING")
        self.assertTrue(record["cancel_requested_at"], "request time recorded")
        self.assertIsNone(record.get("stop_confirmed_at"), "stop not yet confirmed")
        runner._in_cook = False
        runner.advance()  # observes the stop
        on_disk = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]
        self.assertEqual(on_disk["state"], "CANCELLED")
        self.assertTrue(on_disk["stop_confirmed_at"], "stop confirmed at observation")


if __name__ == "__main__":
    unittest.main()
