"""Task-bound integration between the main pipeline and durable graph trials.

This module is controller-side.  It deliberately reuses :class:`GraphJobService`
and its installation-wide scheduler rather than creating another execution
queue.  Model-facing graph tools can be backed by this facade, but the facade
itself never treats a model field as authorization or completion evidence.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from uuid import uuid4

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.models import ErrorCode, now_iso

from .service import ModelSafePipeline, PipelineExecutionError


def _stable_id(value: Any, name: str) -> str:
    rendered = str(value or "").strip()
    if not rendered or len(rendered) > 200 or any(ord(ch) < 0x20 for ch in rendered):
        raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, f"{name} must be a stable identifier")
    return rendered


class TaskGraphCoordinator:
    """Bind graph proposals/trials to one durable main-pipeline task.

    ``construction_authorized`` is supplied by the trusted controller that
    created the construction-only run.  It is not accepted from graph proposal
    payloads and this class is not itself a model-safe command surface.
    """

    def __init__(
        self,
        pipeline: ModelSafePipeline,
        task_id: str,
        jobs: Any,
        *,
        run_id: str,
        session_id: Optional[str] = None,
        construction_authorized: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.store = pipeline.store
        self.database = pipeline.database
        self.task_id = _stable_id(task_id, "task_id")
        self.run_id = _stable_id(run_id, "run_id")
        self.session_id = _stable_id(session_id, "session_id") if session_id else None
        self.jobs = jobs
        if construction_authorized is not True:
            raise PipelineExecutionError(
                ErrorCode.POLICY_DENIED.value,
                "trusted controller construction authorization is required",
            )
        self.construction_authorized = True
        self.store.get_task(self.task_id)

    def _lower_proposal_request(self, request_id: str) -> str:
        return "gp_" + canonical_sha256({"task_id": self.task_id, "request_id": request_id})

    def _lower_trial_request(self, request_id: str) -> str:
        return "gt_" + canonical_sha256({"task_id": self.task_id, "request_id": request_id})

    def _current_binding(self) -> dict[str, Any]:
        binding = self.jobs.controller_binding()
        if not isinstance(binding, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "graph controller binding is invalid")
        return dict(binding)

    def _binding_record(self, graph_id: str) -> dict[str, Any]:
        matches = [
            row for row in self.store.records(self.task_id, "graph_controller_binding")
            if row.get("graph_id") == graph_id
        ]
        if len(matches) != 1:
            raise PipelineExecutionError(
                ErrorCode.POLICY_DENIED.value,
                "graph is not bound to this task's durable trial controller",
                {"graph_id": graph_id},
            )
        record = dict(matches[0])
        expected = record.pop("binding_hash", None)
        if expected != canonical_sha256(record):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph controller binding record changed")
        current = self._current_binding()
        if record.get("controller") != current:
            raise PipelineExecutionError(
                ErrorCode.ARTIFACT_INVALID.value,
                "graph trial controller/runtime directory binding changed",
            )
        return {**record, "binding_hash": expected}

    def propose(self, proposal: Mapping[str, Any], request_id: str) -> dict[str, Any]:
        request_id = _stable_id(request_id, "request_id")
        with execution_lock(self.database, self.task_id):
            main = self.pipeline.graph_propose(
                self.task_id,
                proposal,
                request_id=request_id,
                run_id=self.run_id,
                session_id=self.session_id,
            )
            lower_request = self._lower_proposal_request(request_id)
            lower_graph_id = self.jobs.propose(proposal, lower_request)
            if lower_graph_id != main["graph_id"]:
                raise PipelineExecutionError(
                    ErrorCode.ARTIFACT_INVALID.value,
                    "main and durable graph registries compiled different graph identities",
                )
            record = {
                "schema": "bridge.task-graph-binding/1.1",
                "task_id": self.task_id,
                "graph_id": main["graph_id"],
                "graph_digest": main["graph_digest"],
                "catalog_hash": main["catalog_hash"],
                "source_manifest_hash": main["source_manifest_hash"],
                "run_id": self.run_id,
                "session_id": self.session_id,
                "controller": self._current_binding(),
                "created_at": now_iso(),
            }
            prior = next(
                (row for row in self.store.records(self.task_id, "graph_controller_binding") if row.get("graph_id") == main["graph_id"]),
                None,
            )
            if prior is not None:
                prior_copy = dict(prior)
                prior_hash = prior_copy.pop("binding_hash", None)
                if prior_hash != canonical_sha256(prior_copy):
                    raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph controller binding changed")
                # Proposal request identity belongs to the proposal registries,
                # not to the graph/controller invariant.  v1.0 records carried
                # lower_proposal_request_sha256 here; accept that legacy field
                # only after verifying the old record hash, then compare the
                # actual immutable graph/controller binding fields.
                invariant_keys = (
                    "task_id", "graph_id", "graph_digest", "catalog_hash",
                    "source_manifest_hash", "run_id", "session_id", "controller",
                )
                if any(prior_copy.get(key) != record.get(key) for key in invariant_keys):
                    raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph controller binding changed")
                record = {**prior_copy, "binding_hash": prior_hash}
            else:
                record["binding_hash"] = canonical_sha256(record)
                self.store.put_record(self.task_id, "graph_controller_binding", main["graph_id"], record)
            return {
                "task_id": self.task_id,
                "graph_id": main["graph_id"],
                "legacy_graph_ids": list(main.get("legacy_graph_ids") or []),
                "executed": False,
                "maturity": "experimental_candidate",
                "binding_hash": record["binding_hash"],
            }

    @staticmethod
    def _operation_semantics(status: Mapping[str, Any]) -> dict[str, bool]:
        state = str(status.get("state") or "")
        terminal = state in {"SUCCEEDED", "FAILED", "CANCELLED"}
        return {
            "success": state == "SUCCEEDED",
            "completed": terminal,
            "terminal": terminal,
            # Stop is an independently observed lower-level fact.  Never infer
            # it merely from a cancellation request or a terminal-looking word.
            "stopped": bool(status.get("stop_confirmed")),
        }

    def _construction_rounds(self) -> list[dict[str, Any]]:
        """Restore round order under the task lock, including pre-F1 intents.

        The monotonically increasing number is allocated *before* dispatch.
        Neither a historical status query nor a request replay allocates a round.
        """
        intents = list(self.store.records(self.task_id, "graph_trial_intent"))
        missing = [row for row in intents if "construction_round" not in row]
        if missing:
            # Migration only: deterministic creation order, never query order.
            if any("construction_round" in row for row in intents):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "mixed construction round metadata")
            intents.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["intent_id"])))
            for number, row in enumerate(intents, 1):
                row["construction_round"] = number
                self.store.put_record(self.task_id, "graph_trial_intent", row["intent_id"], row)
        numbers = [row["construction_round"] for row in intents]
        if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) != len(numbers):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "invalid construction round order")
        return sorted(intents, key=lambda row: row["construction_round"])

    def _sync_parent_state(self, operation_id=None, status=None, semantics=None) -> dict[str, Any]:
        """Project the current round AND unresolved older operations.

        Candidates may fail or be cancelled without terminating the user's
        iterative task. Only the normal task state machine writes parent state.
        Lower execution/cancellation/lease decisions remain GraphJobService's.
        """
        rounds = self._construction_rounds()
        parent = self.store.status(self.task_id)
        if not rounds:
            return parent
        stages = {}
        intents_by_id = {row["intent_id"]: row for row in rounds}
        for stored in self.store.records(self.task_id, "graph_construction_stage"):
            body = dict(stored)
            digest = body.pop("snapshot_hash", None)
            body.pop("updated_at", None)
            intent = intents_by_id.get(body.get("intent_id"))
            if (digest != canonical_sha256(body) or intent is None
                    or body.get("task_id") != self.task_id
                    or body.get("graph_id") != intent.get("graph_id")
                    or body.get("operation_id") != intent.get("operation_id")
                    or body.get("operation_id") in stages):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "construction snapshot integrity/binding changed")
            stages[body["operation_id"]] = stored
        observed = []
        for row in rounds:
            stage = stages.get(row.get("operation_id"), {})
            observed.append({
                "round": row["construction_round"], "intent_id": row["intent_id"],
                "operation_id": row.get("operation_id"),
                "state": stage.get("lower_state", "RECONCILIATION_REQUIRED" if row.get("submission_uncertain") else "PREPARED"),
                "reconciliation_required": bool(stage.get("reconciliation_required") or row.get("submission_uncertain")),
                "cancellation_requested": bool(stage.get("cancellation_requested")),
                "stop_confirmed": bool(stage.get("stop_confirmed")),
            })
        active = observed[-1]
        unresolved = [row for row in observed if row["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}
                      or not row["stop_confirmed"]]
        needs_check = any(row["reconciliation_required"] or row["state"] == "RECONCILIATION_REQUIRED"
                          or (row["cancellation_requested"] and not row["stop_confirmed"])
                          or row["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"} for row in unresolved)
        if needs_check:
            desired, message = "DIAGNOSING", "construction outcome requires reconciliation; unresolved operations remain"
        elif unresolved:
            desired, message = "ANALYZING", "construction round active; downstream task work remains"
        elif active["state"] == "SUCCEEDED":
            desired, message = "AWAITING_INPUT", "construction stage succeeded; downstream task work remains"
        elif active["state"] == "FAILED":
            desired, message = "DIAGNOSING", "construction candidate failed; inspect evidence or submit a revised candidate"
        else:
            desired, message = "AWAITING_INPUT", "construction candidate cancelled after stop confirmation; task remains open"
        projection = {
            "schema": "bridge.construction-parent-projection/1.0", "task_id": self.task_id,
            "active_round": active["round"], "active_intent_id": active["intent_id"],
            "active_operation_id": active["operation_id"], "active_lower_state": active["state"],
            "unresolved_operations": unresolved, "desired_state": desired, "message": message,
        }
        projection_hash = canonical_sha256(projection)
        prior = next(iter(self.store.records(self.task_id, "graph_construction_parent")), None)
        current = str(parent["state"])
        if current not in {"QUEUED", "ANALYZING", "DIAGNOSING", "AWAITING_INPUT"}:
            # Never roll back completed tasks or commandeer a downstream stage.
            return parent
        if prior and prior.get("projection_hash") == projection_hash and current == desired:
            return parent
        payload = {**projection, "projection_hash": projection_hash}
        if current == "QUEUED":
            self.store.transition(self.task_id, "ANALYZING", "construction trial registered", payload=payload)
            current = "ANALYZING"
        if current == "DIAGNOSING" and desired == "ANALYZING":
            self.store.transition(self.task_id, "AWAITING_INPUT", "construction recovery acknowledged; next round active", payload=payload)
        self.store.transition(self.task_id, desired, message, payload=payload, refresh_message=True)
        self.store.put_record(self.task_id, "graph_construction_parent", "current", payload)
        return self.store.status(self.task_id)

    def _sync_operation_status(
        self,
        operation_id: str,
        status: Mapping[str, Any],
        *,
        intent_id: Optional[str] = None,
        graph_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist one canonical lower-operation snapshot into the main ledger."""
        operation_id = _stable_id(operation_id, "operation_id")
        semantics = self._operation_semantics(status)
        prior_receipt = next(
            (row for row in self.store.records(self.task_id, "graph_trial_receipt") if row.get("operation_id") == operation_id),
            None,
        )
        if prior_receipt is not None:
            prior_body = dict(prior_receipt)
            prior_hash = prior_body.pop("receipt_hash", None)
            if prior_hash != canonical_sha256(prior_body):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph trial receipt changed")
            intent_id = intent_id or str(prior_body.get("intent_id") or "") or None
            graph_id = graph_id or str(prior_body.get("graph_id") or "") or None
            recorded_at = prior_body.get("recorded_at") or now_iso()
        else:
            recorded_at = now_iso()
        if not intent_id or not graph_id:
            intents = [
                row for row in self.store.records(self.task_id, "graph_trial_intent")
                if row.get("operation_id") == operation_id
            ]
            if len(intents) == 1:
                intent_id = intent_id or str(intents[0].get("intent_id") or "") or None
                graph_id = graph_id or str(intents[0].get("graph_id") or "") or None
        if not intent_id or not graph_id:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "operation has no durable main-ledger intent binding")

        snapshot = {
            "schema": "bridge.task-graph-construction-stage/1.0",
            "task_id": self.task_id,
            "graph_id": graph_id,
            "operation_id": operation_id,
            "intent_id": intent_id,
            "lower_state": status.get("state"),
            "reconciliation_required": bool(status.get("reconciliation_required")),
            "cancellation_requested": bool(status.get("cancellation_requested")),
            "stop_confirmed": bool(status.get("stop_confirmed")),
            **semantics,
        }
        snapshot_hash = canonical_sha256(snapshot)
        stage_record = {**snapshot, "snapshot_hash": snapshot_hash, "updated_at": now_iso()}
        prior_stage = next(
            (row for row in self.store.records(self.task_id, "graph_construction_stage") if row.get("operation_id") == operation_id),
            None,
        )
        prior_stage_body = dict(prior_stage or {})
        prior_stage_body.pop("snapshot_hash", None)
        prior_stage_body.pop("updated_at", None)
        if (prior_stage is None or prior_stage.get("snapshot_hash") != snapshot_hash
                or canonical_sha256(prior_stage_body) != snapshot_hash):
            # Rebuild a damaged derived snapshot only from the actual lower
            # operation observation; a historical poll cannot repair another op.
            self.store.put_record(self.task_id, "graph_construction_stage", operation_id, stage_record)
            event_id = "stage_" + canonical_sha256({"operation_id": operation_id, "snapshot_hash": snapshot_hash})
            if not any(row.get("event_id") == event_id for row in self.store.records(self.task_id, "graph_construction_event")):
                self.store.put_record(self.task_id, "graph_construction_event", event_id, {
                    "schema": "bridge.task-graph-construction-event/1.0",
                    "event_id": event_id,
                    **snapshot,
                    "observed_at": now_iso(),
                })

        intent = next(
            (row for row in self.store.records(self.task_id, "graph_trial_intent") if row.get("intent_id") == intent_id),
            None,
        )
        if intent is None:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph trial intent is missing")
        intent_update = dict(intent)
        intent_update.update({
            "operation_id": operation_id,
            "state": "LOWER_RECEIPT_RECORDED",
            "lower_state": status.get("state"),
            "reconciliation_required": bool(status.get("reconciliation_required")),
            "cancellation_requested": bool(status.get("cancellation_requested")),
            "stop_confirmed": bool(status.get("stop_confirmed")),
            "success": semantics["success"],
            "completed": semantics["completed"],
            "terminal": semantics["terminal"],
            "updated_at": now_iso(),
        })
        intent_update.pop("submission_uncertain", None)
        self.store.put_record(self.task_id, "graph_trial_intent", intent_id, intent_update)

        receipt_body = {
            "schema": "bridge.task-graph-trial-receipt/1.1",
            "task_id": self.task_id,
            "graph_id": graph_id,
            "operation_id": operation_id,
            "intent_id": intent_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "lower_state": status.get("state"),
            "reconciliation_required": bool(status.get("reconciliation_required")),
            "cancellation_requested": bool(status.get("cancellation_requested")),
            "stop_confirmed": bool(status.get("stop_confirmed")),
            **semantics,
            "recorded_at": recorded_at,
        }
        receipt_hash = canonical_sha256(receipt_body)
        if prior_receipt is None or prior_receipt.get("receipt_hash") != receipt_hash:
            self.store.put_record(
                self.task_id, "graph_trial_receipt", operation_id,
                {**receipt_body, "receipt_hash": receipt_hash},
            )
        parent = self._sync_parent_state(operation_id, status, semantics)
        return {
            "task_id": self.task_id,
            **dict(status),
            **semantics,
            "receipt_hash": receipt_hash,
            "construction_stage_hash": snapshot_hash,
            "parent_status": parent,
        }

    def trial(self, graph_id: str, request_id: str) -> dict[str, Any]:
        graph_id = _stable_id(graph_id, "graph_id")
        request_id = _stable_id(request_id, "request_id")
        with execution_lock(self.database, self.task_id):
            graph = self.pipeline._registered_graph(self.task_id, graph_id)
            graph_id = str(graph["graph_id"])
            source = self.pipeline._assert_frozen_sources(self.task_id)
            if source.get("manifest_hash") != graph.get("source_manifest_hash"):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph source binding changed")
            binding = self._binding_record(graph_id)
            if not self.jobs.has_graph(graph_id):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "durable graph registration is missing")
            request_hash = canonical_sha256({
                "task_id": self.task_id, "graph_id": graph_id, "graph_digest": graph["graph_digest"],
                "source_manifest_hash": graph["source_manifest_hash"], "binding_hash": binding["binding_hash"],
                "run_id": self.run_id, "session_id": self.session_id, "request_id": request_id,
            })
            intent_id = "intent_" + canonical_sha256({"task_id": self.task_id, "request_id": request_id})
            prior = next(
                (row for row in self.store.records(self.task_id, "graph_trial_intent") if row.get("intent_id") == intent_id),
                None,
            )
            if prior is not None and prior.get("request_hash") != request_hash:
                raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "request_id is bound to a different graph trial")
            if prior is None:
                if self.store.status(self.task_id)["state"] not in {"QUEUED", "ANALYZING", "DIAGNOSING", "AWAITING_INPUT"}:
                    raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "task is not in an iterative construction stage")
                rounds = self._construction_rounds()
                # Resolve known prior operations by observation only. Never
                # dispatch a new request past an unknown/unbound operation.
                for old in rounds:
                    old_op = old.get("operation_id")
                    if old_op is None:
                        raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "recover the original unbound trial request first")
                    lower = self.jobs.status(old_op)
                    self._sync_operation_status(old_op, lower)
                    if lower["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"} or not lower.get("stop_confirmed"):
                        raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "unresolved construction operation; recover original request first")
                prior = {
                    "schema": "bridge.task-graph-trial-intent/1.1",
                    "construction_round": max((r["construction_round"] for r in rounds), default=0) + 1, "intent_id": intent_id,
                    "task_id": self.task_id, "graph_id": graph_id, "graph_digest": graph["graph_digest"],
                    "request_id": request_id, "request_hash": request_hash, "run_id": self.run_id,
                    "session_id": self.session_id, "source_manifest_hash": graph["source_manifest_hash"],
                    "binding_hash": binding["binding_hash"], "operation_id": None,
                    "lower_trial_request_sha256": canonical_sha256(self._lower_trial_request(request_id)),
                    "state": "INTENT_RECORDED", "created_at": now_iso(),
                }
                self.store.put_record(self.task_id, "graph_trial_intent", intent_id, prior)
                self._sync_parent_state()
            else:
                # Ensure legacy intent migration also survives replays.
                prior = next(row for row in self._construction_rounds() if row["intent_id"] == intent_id)

            operation_id = prior.get("operation_id")
            lower_request = self._lower_trial_request(request_id)
            if operation_id is None:
                operation_id = self.jobs.lookup_trial(lower_request)
            if operation_id is None:
                try:
                    operation_id = self.jobs.trial(graph_id, lower_request)
                except Exception:
                    uncertain = {**prior, "submission_uncertain": True}
                    self.store.put_record(self.task_id, "graph_trial_intent", intent_id, uncertain)
                    self._sync_parent_state()
                    raise
            # Persist the lower operation identity before interpreting status so
            # a restart can reconcile the same operation without re-submission.
            intent_update = dict(prior)
            intent_update.update({"operation_id": operation_id, "state": "LOWER_OPERATION_BOUND", "updated_at": now_iso()})
            self.store.put_record(self.task_id, "graph_trial_intent", intent_id, intent_update)
            status = self.jobs.status(operation_id)
            synced = self._sync_operation_status(
                operation_id, status, intent_id=intent_id, graph_id=graph_id
            )
            return {"graph_id": graph_id, "accepted": True, **synced}

    def _owned_operation(self, operation_id: str) -> dict[str, Any]:
        operation_id = _stable_id(operation_id, "operation_id")
        rows = [row for row in self.store.records(self.task_id, "graph_trial_receipt") if row.get("operation_id") == operation_id]
        if len(rows) != 1:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "operation does not belong to this task")
        receipt = dict(rows[0])
        expected = receipt.pop("receipt_hash", None)
        if expected != canonical_sha256(receipt):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "graph trial receipt changed")
        return {**receipt, "receipt_hash": expected}

    def status(self, operation_id: str) -> dict[str, Any]:
        with execution_lock(self.database, self.task_id):
            self._owned_operation(operation_id)
            return self._sync_operation_status(operation_id, self.jobs.status(operation_id))

    def cancel(self, operation_id: str) -> dict[str, Any]:
        """Trusted-controller cancellation.  A request is not proof of stop."""
        with execution_lock(self.database, self.task_id):
            self._owned_operation(operation_id)
            return self._sync_operation_status(operation_id, self.jobs.cancel(operation_id))

    def reconcile(self, operation_id: str, *, resume_not_started: bool = False) -> dict[str, Any]:
        """Trusted-controller recovery; intentionally absent from the MCP."""
        with execution_lock(self.database, self.task_id):
            self._owned_operation(operation_id)
            return self._sync_operation_status(
                operation_id, self.jobs.reconcile(operation_id, resume_not_started=resume_not_started)
            )
