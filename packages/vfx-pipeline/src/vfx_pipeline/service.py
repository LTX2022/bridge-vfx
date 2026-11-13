"""Persistent cross-DCC orchestration facade.

The facade keeps model-safe workflow methods separate from the trusted-human
approval control plane.  It invokes only registered high-level DCC recipes;
there is no raw Python, HScript, or ``nuke_run`` fallback.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4
from urllib.parse import unquote, unquote_to_bytes, urlparse

from dcc_task_runtime.approvals import ApprovalService, CacheApprovalSubject, ExperienceApprovalSubject
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.causal import CausalDoctor
from dcc_task_runtime.contracts import (
    ActorKind,
    ApprovalScope,
    ArtifactRecord,
    CandidatePatch,
    CauseHypothesis,
    ChangeDirection,
    DomainPackRef,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceVerdict,
    IssueDimension,
    ParameterChange,
    PerceptualIssue,
    RepairExperience,
    TaskSpecV2,
    VisualScorecard,
    new_identifier,
)
from dcc_task_runtime.errors import DiagnosisInconclusive, PolicyDenied, RuntimeV2Error
from dcc_task_runtime.execution_lock import task_exclusive
from dcc_task_runtime.experience import ExperienceService
from dcc_task_runtime.models import ErrorCode, TaskState, now_iso
from dcc_task_runtime.metrics import MetricEngine, MetricProvenance
from dcc_task_runtime.pipeline_store import PipelineStore
from dcc_task_runtime.gateways import (
    BoundedPlanner,
    DeepSeekResponsesPlannerGateway,
    OpenAICompatibleVisionGateway,
    PlannerContext,
    ToolDescriptor,
    probe_capabilities,
)
from dcc_task_runtime.skill_ir import ModelActionSelection, SkillAction, SkillCompiler, SkillIR, SkillState
from dcc_task_runtime.skill_vm import ExecutionRequest, SkillExecutionVM
from houdini_bridge import get_domain_pack as get_houdini_domain_pack
from houdini_bridge.tasks import houdini_gate_policy, task_service as houdini_task_service
from nuke_bridge.tasks import nuke_gate_policy, task_service as nuke_task_service

from . import graph_catalog
from .paths import load_approval_secret, state_database
from .decoders import ImageMagickRasterDecoder
from .planner import PipelinePlanner
from .router import BridgeRouter, RouteLeg


class PipelineExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


EXPLOSION_BRANCH_CONTROL_MAP: Mapping[str, tuple[str, str]] = {
    "fire_energy": ("fire", "burn_rate"),
    "fire_scale": ("fire", "fuel_rate"),
    "smoke_dissipation": ("smoke", "dissipation"),
    "smoke_scale": ("smoke", "density_scale"),
    "shockwave_scale": ("shockwave", "scale"),
    "spark_rate": ("particles", "birth_rate"),
    "debris_scale": ("rbd", "fracture_scale"),
    "debris_energy": ("rbd", "velocity_variance"),
    "debris_amount": ("rbd", "debris_amount"),
}


class _RejectHumanVerification:
    def verify(self, _principal_id, _proof, _scope, _request_id) -> bool:
        return False


class ModelSafePipeline:
    """Commands that may be exposed to a planner model."""

    def __init__(
        self,
        database: Path | str | None = None,
        planner: Optional[PipelinePlanner] = None,
        router: Optional[BridgeRouter] = None,
        service_factories: Optional[Mapping[str, Callable[[Any, Path], Any]]] = None,
        raster_decoder: Any = None,
    ) -> None:
        self.database = Path(database) if database is not None else state_database()
        self.store = PipelineStore(self.database)
        self.router = router or (planner.router if planner is not None else BridgeRouter())
        self.planner = planner or PipelinePlanner(router=self.router)
        self._service_factories = dict(
            service_factories
            or {
                "houdini": houdini_task_service,
                "nuke": nuke_task_service,
            }
        )
        self._subtask_root = self.database.parent / "subtasks"
        self.doctor = CausalDoctor()
        self.metrics = MetricEngine()
        self.raster_decoder = raster_decoder or ImageMagickRasterDecoder()
        # Model-safe callers can request or consume an already-authorized
        # grant, but this verifier makes it impossible for them to mint one.
        self.approvals = ApprovalService(self.store, _RejectHumanVerification())
        self.experiences = ExperienceService(self.store, self.approvals)

    def capabilities(self, refresh: bool = False) -> dict[str, Any]:
        result = self.router.capabilities(refresh=refresh)
        result.update(
            {
                "schema_version": "2.0",
                "task_type": "visual.reference_rebuild",
                "domains": self.planner.list_domains(),
                "domain_maturity_policy": "experimental_until_live_validated",
                "model_safe_grant_commands": [],
            }
        )
        return result

    def model_probe(
        self,
        config: Mapping[str, Any],
        task_id: Optional[str] = None,
        planner_gateway: Any = None,
        vision_gateway: Any = None,
    ) -> dict[str, Any]:
        """Probe configured endpoints without persisting credentials."""

        spec = None
        if task_id:
            spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
            self._assert_frozen_sources(task_id)
        planner_config = config.get("planner") or {}
        if str(planner_config.get("provider") or "") == "doubao-desktop" and spec is not None and spec.references:
            vision_config = config.get("vision") or {}
            if str(vision_config.get("provider") or "") != "doubao-desktop":
                raise PipelineExecutionError(ErrorCode.MODEL_CAPABILITY_MISMATCH.value, "Doubao reference tasks require the same registered Doubao vision route; no alternate vision fallback is permitted")
        planner_gateway = planner_gateway or self._planner_gateway(planner_config)
        planner_caps = probe_capabilities(
            planner_gateway,
            required_modalities=("text",),
            require_strict_json=True,
            require_action_contract=True,
        )
        result: dict[str, Any] = {"planner": planner_caps.to_dict(), "vision": None}
        vision_config = config.get("vision")
        if vision_gateway is not None or vision_config:
            vision_gateway = vision_gateway or self._vision_gateway(vision_config or {}, tuple(spec.references) if spec else ())
            required = ()
            if spec:
                required = tuple(
                    sorted(
                        {
                            "video" if item.kind.value in {"video", "sequence"} else "image"
                            for item in spec.references
                        }
                    )
                )
            result["vision"] = probe_capabilities(vision_gateway, required_modalities=required).to_dict()
        if task_id:
            self.store.put_record(task_id, "model_capabilities", "latest", result)
        return result

    @task_exclusive
    def model_step(
        self,
        task_id: str,
        config: Mapping[str, Any],
        planner_gateway: Any = None,
        vision_gateway: Any = None,
        *,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Execute a durable model turn; retries must reuse the same request ID."""
        identity = str(request_id or "").strip()
        if not identity or len(identity) > 200:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "model.step requires a stable request_id of 1..200 characters")
        task = self.store.get_task(task_id)
        request_hash = canonical_sha256({"spec": task["spec"], "config": dict(config)})
        key = "model_turn:" + identity
        owner = uuid4().hex
        claim = self.store.claim_skill_execution(task_id, key, request_hash, owner)
        if claim["outcome"] == "COMPLETED":
            replay = dict(claim["result"])
            if "error" in replay:
                raise PipelineExecutionError(replay["error"]["code"], replay["error"]["message"])
            return replay
        if claim["outcome"] != "ACQUIRED":
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "model turn is in doubt; reconcile its existing action before another dispatch", {"request_id": identity})
        try:
            result = self._model_step(task_id, config, planner_gateway, vision_gateway, identity)
        except Exception as exc:
            code = getattr(exc, "code", ErrorCode.INTERNAL_ERROR.value)
            failure = {"error": {"code": str(getattr(code, "value", code)), "message": "model turn failed: " + type(exc).__name__}}
            self.store.complete_skill_execution(task_id, key, request_hash, owner, failure)
            raise
        self.store.complete_skill_execution(task_id, key, request_hash, owner, result)
        return result

    def _model_step(self, task_id, config, planner_gateway, vision_gateway, request_id):
        """One bounded model exchange inside a reserved durable turn."""

        task = self.store.get_task(task_id)
        spec = TaskSpecV2.from_mapping(task["spec"])
        self._assert_frozen_sources(task_id)
        planner_gateway = planner_gateway or self._planner_gateway(config.get("planner") or {})
        vision_analysis: Mapping[str, Any] = {}
        stored_analysis = self.store.records(task_id, "reference_analysis")
        if stored_analysis:
            vision_analysis = dict(stored_analysis[-1].get("analysis") or {})
        elif spec.references:
            vision_gateway = vision_gateway or self._vision_gateway(config.get("vision") or {}, spec.references)
            probe_capabilities(
                vision_gateway,
                required_modalities=tuple(
                    sorted({"video" if item.kind.value in {"video", "sequence"} else "image" for item in spec.references})
                ),
            )
            vision_analysis = dict(
                vision_gateway.analyze(
                    spec.references,
                    {"intent": spec.intent, "feedback": spec.feedback, "domains": [item.identifier for item in spec.domains]},
                )
            )
            analysis_record = {
                "analysis_id": new_identifier("reference_analysis"),
                "reference_hashes": [item.sha256 for item in spec.references],
                "analysis": vision_analysis,
                "created_at": now_iso(),
            }
            analysis_record["analysis_hash"] = canonical_sha256(analysis_record)
            self.store.put_record(task_id, "reference_analysis", analysis_record["analysis_id"], analysis_record)
        state = TaskState(self.store.status(task_id)["state"])
        tools = self._model_tools_for_task(task_id, state)
        bounded = BoundedPlanner(planner_gateway, max_exposed_tools=4)
        prior = self.store.records(task_id, "model_step")
        context = PlannerContext(
            task_summary={
                "task_id": task_id,
                "state": state.value,
                "intent": spec.intent,
                "feedback": spec.feedback,
                "domains": [item.identifier for item in spec.domains],
            },
            vision_analysis=vision_analysis,
            scene_state={"subtask_count": len(self.store.records(task_id, "subtask")), "artifact_count": len(self.store.artifacts(task_id))},
            policy_state={"trusted_commands_exposed": False, "one_action_limit": 1, "state": state.value},
            prior_action_result=dict(prior[-1].get("action_result") or {}) if prior else None,
        )
        action = bounded.plan(context, tools)
        action_result = None
        action_record = action.to_dict()
        if action.tool is not None:
            # Legacy planner compatibility still enters through the exact same
            # ID-only SkillIR boundary as weak models.  Planner-supplied
            # parameters, paths, values, and approvals are deliberately ignored.
            selection: dict[str, Any] = {"action_id": action.tool}
            if action.tool == "candidate.select":
                selection["candidate_id"] = str(action.arguments.get("candidate_id") or "")
            vm_result = self.model_skill_step(task_id, selection, "model_action:" + request_id)
            action_result = dict((vm_result.get("execution") or {}).get("output") or {})
            action_record = {
                "tool": action.tool,
                "arguments": {key: value for key, value in selection.items() if key != "action_id"},
                "reason": action.reason,
                "request_user_input": action.request_user_input,
                "executed_via": "SkillIR",
            }
        record = {
            "step_id": "model_step:" + request_id,
            "request_id": request_id,
            "task_id": task_id,
            "state_before": state.value,
            "exposed_tools": [item.name for item in tools],
            "action": action_record,
            "action_result": action_result,
            "created_at": now_iso(),
        }
        self.store.put_record(task_id, "model_step", record["step_id"], record)
        return record

    def model_card(self, task_id: str) -> dict[str, Any]:
        """Compile the current durable state into a weak-model PromptCard."""

        task = self.store.get_task(task_id)
        state = TaskState(self.store.status(task_id)["state"])
        spec = TaskSpecV2.from_mapping(task["spec"])
        tools = self._model_tools_for_task(task_id, state)
        candidates = tuple(
            str(item.get("candidate_id") or "")
            for item in self.store.records(task_id, "candidate")
            if str(item.get("candidate_id") or "")
        )
        actions = []
        for tool in tools[:4]:
            requires_candidate = tool.name == "candidate.select"
            if requires_candidate and not candidates:
                continue
            actions.append(
                SkillAction(
                    action_id=tool.name,
                    label=tool.name,
                    description=tool.description,
                    candidate_ids=candidates if requires_candidate else (),
                    requires_candidate=requires_candidate,
                    recoverable_error_codes=(
                        ErrorCode.AWAITING_INPUT.value,
                        ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                        ErrorCode.APPROVAL_REQUIRED.value,
                    ),
                )
            )
        if not actions:
            actions = [SkillAction("task.status", "task.status", "Read the durable task state.")]
        skill = SkillIR(
            skill_id="vfx.visual_twin",
            version="2.0.0-rc.1",
            initial_state=state.value,
            states=(
                SkillState(
                    state.value,
                    "Select exactly one ID-only action. Do not invent paths, scripts, parameters, values, approvals, or multiple actions.",
                    tuple(actions),
                ),
            ),
        )
        card = SkillCompiler(skill).compile(state.value).to_dict()
        card.update(
            {
                "task_id": task_id,
                "task_state": state.value,
                "domain_ids": [item.identifier for item in spec.domains],
                "candidate_ids": list(candidates),
                "model_may_grant_approval": False,
            }
        )
        return card

    @task_exclusive
    def model_skill_step(
        self,
        task_id: str,
        selection: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Execute one ID-only SkillIR selection through a deterministic VM."""

        parsed = ModelActionSelection.from_mapping(selection)
        key = str(idempotency_key or "").strip()
        if not key:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "idempotency_key is required")
        receipt = self.store.skill_execution_receipt(task_id, key)
        if receipt is not None:
            if receipt["status"] != "COMPLETED":
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "skill execution is in doubt; reconcile its original operation")
            result = receipt.get("result") or {}
            if result.get("selection") != parsed.to_dict():
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "idempotency key belongs to a different selection")
            return {**dict(result), "replayed": True}
        card = self.model_card(task_id)
        actions = tuple(
            SkillAction(
                action_id=str(item["action_id"]),
                label=str(item["label"]),
                description=str(item.get("description") or ""),
                candidate_ids=tuple(str(value) for value in item.get("candidate_ids") or ()),
                requires_candidate=bool(item.get("requires_candidate")),
                recoverable_error_codes=(
                    ErrorCode.AWAITING_INPUT.value,
                    ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                    ErrorCode.APPROVAL_REQUIRED.value,
                ),
            )
            for item in card["actions"]
        )
        state = str(card["state_id"])
        skill = SkillIR(
            "vfx.visual_twin",
            str(card["skill_version"]),
            state,
            (SkillState(state, str(card["instruction"]), actions),),
        )
        key = str(idempotency_key or "").strip()
        if not key:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "idempotency_key is required")
        selection_dict = parsed.to_dict()
        request_hash = canonical_sha256(
            {
                "task_id": task_id,
                "skill_id": skill.skill_id,
                "skill_version": skill.version,
                "state_id": state,
                "selection": selection_dict,
            }
        )
        owner_token = uuid4().hex
        claim = self.store.claim_skill_execution(task_id, key, request_hash, owner_token)
        if claim["outcome"] == "COMPLETED":
            return {**dict(claim["result"]), "replayed": True}
        if claim["outcome"] == "IN_DOUBT":
            raise RuntimeV2Error(
                ErrorCode.POLICY_DENIED,
                "skill execution is in doubt; reconcile the original DCC operation before retrying",
                {"idempotency_key": key, "status": "RUNNING"},
            )

        def execute(request: ExecutionRequest) -> Mapping[str, Any]:
            arguments = self._deterministic_skill_arguments(task_id, request)
            try:
                return self._execute_model_action(task_id, request.action_id, arguments)
            except PipelineExecutionError as exc:
                try:
                    code = ErrorCode(str(exc.code))
                except ValueError:
                    code = ErrorCode.INTERNAL_ERROR
                raise RuntimeV2Error(code, str(exc), exc.details) from exc

        record = SkillExecutionVM(skill, execute).execute(state, parsed, idempotency_key=key).to_dict()
        payload = {
            "record_id": new_identifier("skill_vm"),
            "task_id": task_id,
            "state_id": state,
            "idempotency_key": key,
            "selection": selection_dict,
            "execution": record,
            "created_at": now_iso(),
        }
        # Complete the durable CAS before writing the append-only audit copy.
        # A crash before this point leaves RUNNING and is fail-closed; a crash
        # after it replays the exact persisted result without dispatching again.
        self.store.complete_skill_execution(task_id, key, request_hash, owner_token, payload)
        self.store.put_record(task_id, "skill_vm", payload["record_id"], payload)
        return payload

    def _deterministic_skill_arguments(self, task_id: str, request: ExecutionRequest) -> dict[str, Any]:
        if request.action_id == "candidate.select":
            return {"candidate_id": request.candidate_id}
        if request.action_id == "feedback.diagnose":
            spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
            evidence_rows = self.store.records(task_id, "reference_analysis")
            evidence = dict(evidence_rows[-1].get("analysis") or {}) if evidence_rows else {}
            domain = spec.domains[0].identifier if len(spec.domains) == 1 else None
            return {"feedback": spec.feedback, "evidence": evidence, "domain": domain}
        if request.action_id == "cache.run":
            grants = self.store.active_grants(task_id, ApprovalScope.HOUDINI_SIMULATION_CACHE.value)
            if len(grants) != 1:
                raise RuntimeV2Error(ErrorCode.APPROVAL_REQUIRED, "exactly one active cache grant is required")
            return {"grant_id": str(grants[0]["grant_id"])}
        if request.action_id == "verification.record":
            rows = self.store.records(task_id, "verification_measurement")
            if not rows:
                raise RuntimeV2Error(ErrorCode.AWAITING_INPUT, "a deterministic verification measurement is required")
            return {"measurement": dict(rows[-1].get("measurement") or {})}
        return {}

    def graph_catalog(self) -> dict[str, Any]:
        return graph_catalog.descriptor()

    @task_exclusive
    def graph_propose(
        self,
        task_id: str,
        proposal: Mapping[str, Any],
        *,
        request_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compile and durably register one task-owned graph candidate.

        The canonical ID intentionally matches :class:`GraphJobService`: it is
        a content identity for the compiled graph plus the registered catalog.
        The pre-B1 main-pipeline ID is retained only as a legacy alias.  Task
        ownership remains a separate durable fact and is always checked before
        a trial is allowed.
        """
        self.store.get_task(task_id)
        source_manifest = self._assert_frozen_sources(task_id)
        compiled = graph_catalog.compile_proposal(proposal)
        compiled_payload = compiled.to_dict()
        catalog = self.graph_catalog()
        catalog_hash = str(catalog["catalog_hash"])
        graph_id = "graph_" + canonical_sha256({"compiled": compiled_payload, "catalog_hash": catalog_hash})
        legacy_graph_id = "graph_" + canonical_sha256({"graph": compiled_payload, "catalog_hash": catalog_hash})
        proposal_payload = dict(proposal)
        proposal_hash = canonical_sha256(proposal_payload)
        graph_digest = str(compiled_payload.get("graph_hash") or canonical_sha256(compiled_payload))
        normalized_request = None
        if request_id is not None:
            normalized_request = str(request_id).strip()
            if not normalized_request or len(normalized_request) > 200 or any(ord(ch) < 0x20 for ch in normalized_request):
                raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "graph proposal requires a stable request_id")
            request_hash = canonical_sha256(
                {
                    "task_id": task_id,
                    "request_id": normalized_request,
                    "proposal_hash": proposal_hash,
                    "run_id": str(run_id or ""),
                    "session_id": str(session_id or ""),
                }
            )
            prior_request = next(
                (row for row in self.store.records(task_id, "graph_proposal_request") if row.get("request_id") == normalized_request),
                None,
            )
            if prior_request is not None:
                if prior_request.get("request_hash") != request_hash:
                    raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "graph proposal request_id was reused with different content")
                return self._registered_graph(task_id, str(prior_request.get("graph_id") or ""))
        record = {
            "schema": "bridge.task-graph-proposal/1.0",
            "task_id": task_id,
            "graph_id": graph_id,
            "legacy_graph_ids": [legacy_graph_id] if legacy_graph_id != graph_id else [],
            "catalog_hash": catalog_hash,
            "proposal_hash": proposal_hash,
            "graph_digest": graph_digest,
            "source_manifest_hash": source_manifest["manifest_hash"],
            "proposal": proposal_payload,
            "compiled": compiled_payload,
            "run_id": str(run_id) if run_id else None,
            "session_id": str(session_id) if session_id else None,
            "maturity": "experimental_candidate",
            "executed": False,
        }
        existing = next(
            (row for row in self.store.records(task_id, "graph_proposal") if row.get("graph_id") == graph_id),
            None,
        )
        if existing is not None:
            immutable = (
                "task_id", "graph_id", "catalog_hash", "proposal_hash", "graph_digest",
                "source_manifest_hash", "proposal", "compiled",
            )
            if any(existing.get(name) != record.get(name) for name in immutable):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "registered graph identity changed")
            record = dict(existing)
        else:
            self.store.put_record(task_id, "graph_proposal", graph_id, record)
        if normalized_request is not None:
            request_record = {
                "request_id": normalized_request,
                "request_hash": request_hash,
                "graph_id": graph_id,
                "proposal_hash": proposal_hash,
                "run_id": str(run_id) if run_id else None,
                "session_id": str(session_id) if session_id else None,
                "created_at": now_iso(),
            }
            self.store.put_record(
                task_id,
                "graph_proposal_request",
                "request_" + canonical_sha256({"task_id": task_id, "request_id": normalized_request}),
                request_record,
            )
        return record

    def _registered_graph(self, task_id: str, graph_id: str) -> dict[str, Any]:
        """Resolve a graph only inside its owning main-pipeline task."""
        self.store.get_task(task_id)
        requested = str(graph_id or "").strip()
        if not requested:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "graph_id is required")
        rows = self.store.records(task_id, "graph_proposal")
        record = next(
            (
                dict(row) for row in rows
                if row.get("graph_id") == requested or requested in tuple(row.get("legacy_graph_ids") or ())
            ),
            None,
        )
        if record is None:
            raise PipelineExecutionError(
                ErrorCode.POLICY_DENIED.value,
                "graph_id is not registered under this task",
                {"graph_id": requested},
            )
        compiled = graph_catalog.compile_proposal(record.get("proposal") or {}).to_dict()
        catalog_hash = str(self.graph_catalog()["catalog_hash"])
        canonical_id = "graph_" + canonical_sha256({"compiled": compiled, "catalog_hash": catalog_hash})
        if record.get("graph_id") != canonical_id or record.get("compiled") != compiled or record.get("catalog_hash") != catalog_hash:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "registered graph or catalog changed")
        source_manifest = self._assert_frozen_sources(task_id)
        if record.get("source_manifest_hash") != source_manifest.get("manifest_hash"):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "registered graph source binding changed")
        return record

    def graph_list(self, task_id: str) -> dict[str, Any]:
        self.store.get_task(task_id)
        return {"task_id": task_id, "graphs": list(self.store.records(task_id, "graph_proposal"))}

    def domain_list(self) -> dict[str, Any]:
        return {"domains": self.planner.list_domains()}

    def domain_show(self, identifier: str, version: str = "1.0.0") -> dict[str, Any]:
        return self.planner.show_domain(identifier, version)

    def task_plan(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return self.planner.plan(spec)

    def task_start(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        parsed = self.planner.prepare_spec(spec)
        source_manifest = self._freeze_task_sources(parsed)
        plan = self.planner.plan(parsed)
        task_id = self.store.create_task(parsed)
        return self._start_registered_task(task_id, parsed, plan, source_manifest)

    def reference_task_start(
        self, spec: Mapping[str, Any], *, idempotency_key: str, purpose: str = "graph_construction"
    ) -> dict[str, Any]:
        """Register a frozen reference-analysis task without discovering a DCC route.

        This is a controller bootstrap for the synthetic construction bundle.
        It deliberately stops at ``AWAITING_INPUT`` after freezing the declared
        reference bytes.  No route planning, DCC discovery, construction, or
        acceptance claim occurs here; the later graph coordinator owns its own
        explicit construction operation.
        """
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "reference task requires an idempotency_key")
        if purpose != "graph_construction":
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "unsupported reference-only task purpose")
        parsed = self.planner.prepare_spec(spec)
        if not parsed.references:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "reference-only task requires registered media")
        source_manifest = self._freeze_task_sources(parsed)
        task_id = self.store.create_task(parsed, idempotency_key=idempotency_key.strip())
        return self._start_registered_reference_task(task_id, parsed, source_manifest, purpose=purpose)

    @task_exclusive
    def _start_registered_reference_task(self, task_id, parsed, source_manifest, *, purpose: str):
        status = self.store.status(task_id)
        if status["state"] != TaskState.QUEUED.value:
            return {"task_id": task_id, "status": status, "idempotent_reuse": True}
        task = self.store.get_task(task_id)
        self.store.put_record(task_id, "source_manifest", "frozen", source_manifest)
        self.store.put_record(
            task_id,
            "control_bootstrap",
            "reference_only",
            {
                "schema": "bridge.reference-task-bootstrap/1.0",
                "purpose": purpose,
                "route_planning_deferred": True,
                "dcc_dispatched": False,
                "real_execution_validated": False,
                "source_manifest_hash": source_manifest["manifest_hash"],
            },
        )
        self.store.transition(
            task_id,
            TaskState.ANALYZING,
            "reference/input bytes frozen; DCC route planning deferred to an explicit later operation",
            payload={"spec_hash": task["spec_hash"], "source_manifest_hash": source_manifest["manifest_hash"]},
        )
        self.store.put_record(
            task_id,
            "continuation",
            "reference",
            {
                "phase": "reference_analysis",
                "resume_mode": "graph_construction_only",
                "route_planning_deferred": True,
            },
        )
        status = self.store.transition(
            task_id,
            TaskState.AWAITING_INPUT,
            "reference analysis is required before graph construction may be proposed",
        )
        return {
            "task_id": task_id,
            "status": status,
            "pending": ["reference_analysis"],
            "route_planning_deferred": True,
            "dcc_dispatched": False,
        }

    @task_exclusive
    def _start_registered_task(self, task_id, parsed, plan, source_manifest):
        status = self.store.status(task_id)
        if status["state"] != TaskState.QUEUED.value:
            return {"task_id": task_id, "status": status, "idempotent_reuse": True}
        self.store.put_record(task_id, "plan", "main", plan)
        self.store.put_record(task_id, "source_manifest", "frozen", source_manifest)
        try:
            self.store.transition(
                task_id,
                TaskState.ANALYZING,
                "reference/input bytes, explicit scene, domain packs, and routes frozen",
                payload={"spec_hash": plan["spec_hash"], "source_manifest_hash": source_manifest["manifest_hash"]},
            )
            if parsed.references:
                self.store.put_record(task_id, "continuation", "reference", {"phase": "reference_analysis"})
                status = self.store.transition(task_id, TaskState.AWAITING_INPUT, "reference analysis is required before any DCC construction")
                return {"task_id": task_id, "status": status, "plan": plan, "pending": ["reference_analysis"]}
            return self._continue_initial_previews(task_id, parsed, plan)
        except Exception as exc:
            code = str(getattr(exc, "code", ErrorCode.INTERNAL_ERROR.value))
            current = TaskState(self.store.status(task_id)["state"])
            if TaskState.FAILED in self._allowed_targets(current):
                self.store.transition(task_id, TaskState.FAILED, str(exc), error_code=code)
            self.store.save_result(task_id, {"task_id": task_id, "state": "FAILED", "error_code": code, "error_message": str(exc)})
            raise

    def _continue_initial_previews(self, task_id, parsed, plan):
        self.store.transition(task_id, TaskState.PREVIEWING, "running isolated editable DCC previews")
        pending, dcc_outcomes = self._run_initial_previews(task_id, parsed, plan)
        if dcc_outcomes:
            states = {str(item.get("state") or "") for item in dcc_outcomes}
            if states == {TaskState.UNSUPPORTED.value}:
                target_state = TaskState.UNSUPPORTED
                message = "the selected domain adapters are unsupported by the connected DCC versions"
            elif TaskState.AWAITING_INPUT.value in states:
                target_state = TaskState.AWAITING_INPUT
                message = "the DCC preview requires one additional input before diagnosis can continue"
            else:
                target_state = TaskState.DIAGNOSIS_INCONCLUSIVE
                message = "the editable DCC operation completed, but visual or field evidence is still missing"
            status = self.store.transition(
                task_id,
                target_state,
                message,
                error_code=ErrorCode.DIAGNOSIS_INCONCLUSIVE if target_state is TaskState.DIAGNOSIS_INCONCLUSIVE else None,
                payload={"dcc_outcomes": dcc_outcomes, "pending": pending},
            )
        elif pending:
            status = self.store.transition(
                task_id,
                TaskState.AWAITING_INPUT,
                pending[0],
                payload={"pending": pending},
            )
        elif parsed.feedback.strip():
            status = self.store.transition(
                task_id,
                TaskState.DIAGNOSING,
                "preview ready; stage evidence is required for causal diagnosis",
            )
        else:
            status = self.store.transition(
                task_id,
                TaskState.AWAITING_INPUT,
                "provide one concrete visual feedback statement or structured vision analysis",
            )
        summary = self._summary(task_id)
        self.store.save_result(task_id, summary)
        return {"task_id": task_id, "status": status, "plan": plan, "pending": pending, "dcc_outcomes": dcc_outcomes}

    def task_status(self, task_id: str) -> dict[str, Any]:
        return self.store.status(task_id)

    def task_events(self, task_id: str, after_seq: int = 0) -> dict[str, Any]:
        return {"task_id": task_id, "events": list(self.store.events(task_id, after_seq))}

    @task_exclusive
    def task_resume(self, task_id: str) -> dict[str, Any]:
        status = self.store.status(task_id)
        state = TaskState(status["state"])
        continuations = self.store.records(task_id, "continuation")
        construction_reference = any(
            row.get("phase") == "reference_analysis" and row.get("resume_mode") == "graph_construction_only"
            for row in continuations
        )
        if state is TaskState.AWAITING_INPUT and construction_reference:
            raise PipelineExecutionError(
                ErrorCode.AWAITING_INPUT.value,
                "construction-only reference tasks continue through the explicit graph coordinator; generic task.resume cannot discover or dispatch a DCC route",
            )
        if state is TaskState.AWAITING_INPUT and any(row.get("phase") == "reference_analysis" for row in continuations):
            self._assert_frozen_sources(task_id)
            parsed = self._spec_with_analysis(task_id, TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"]))
            result = self._continue_initial_previews(task_id, parsed, self.store.records(task_id, "plan")[-1])
            self.store.put_record(task_id, "continuation", "reference", {"phase": "initial_preview_completed"})
            return result
        if state in {TaskState.PARTIAL, TaskState.CACHING}:
            recoveries = self.store.records(task_id, "recovery")
            cache = next((item for item in recoveries if item.get("phase") == "cache"), None)
            if cache and cache.get("grant_id"):
                return self.cache_run(task_id, str(cache["grant_id"]))
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "partial task has no supported durable continuation")
        if state not in {TaskState.AWAITING_INPUT, TaskState.DIAGNOSIS_INCONCLUSIVE, TaskState.APPROVAL_REVOKED}:
            raise PipelineExecutionError(
                ErrorCode.INVALID_TRANSITION.value,
                "only AWAITING_INPUT, DIAGNOSIS_INCONCLUSIVE, or APPROVAL_REVOKED tasks can resume",
            )
        target = TaskState.DIAGNOSING if state is not TaskState.APPROVAL_REVOKED else TaskState.CANDIDATES_READY
        return {"task_id": task_id, "status": self.store.transition(task_id, target, "task resumed from durable state")}

    def task_result(self, task_id: str) -> dict[str, Any]:
        return self.store.result(task_id) or self._summary(task_id)

    @task_exclusive
    def feedback_diagnose(
        self,
        task_id: str,
        feedback: str,
        evidence_payload: Mapping[str, Any],
        domain_identifier: Optional[str] = None,
    ) -> dict[str, Any]:
        self._assert_frozen_sources(task_id)
        task = self.store.get_task(task_id)
        spec = TaskSpecV2.from_mapping(task["spec"])
        pack = self._domain_for_feedback(spec, feedback, domain_identifier)
        self._move_to_diagnosing(task_id)
        frame = spec.render.get("frame_range") or {}
        raw_range = evidence_payload.get("fixed_frame_range") or frame
        fixed_range = self._frame_tuple(raw_range)
        component_id = str(evidence_payload.get("component_id") or pack.components[0])
        issue = self.doctor.interpret_feedback(
            feedback,
            pack,
            component_id,
            roi=self._roi_tuple(evidence_payload.get("roi")),
            frame_range=fixed_range,
            protected_attributes=tuple(
                str(item)
                for item in evidence_payload.get("protected_attributes")
                or spec.constraints.get("protected_attributes")
                or ()
            ),
        )
        evidence = EvidenceBundle(
            task_id=task_id,
            issue_id=issue.issue_id,
            records=tuple(self._evidence_record(item) for item in evidence_payload.get("records") or []),
            fixed_seed=int(evidence_payload.get("fixed_seed", spec.metadata.get("seed", 1))),
            fixed_camera_hash=str(evidence_payload.get("fixed_camera_hash") or spec.metadata.get("camera_hash") or "unverified_camera"),
            fixed_frame_range=fixed_range,
        )
        self.store.put_record(task_id, "issue", issue.issue_id, issue.to_dict())
        self.store.put_record(task_id, "evidence", issue.issue_id, evidence.to_dict())
        try:
            hypotheses = self.doctor.diagnose(issue, evidence, pack)
            current_parameters = dict(evidence_payload.get("current_parameters") or {})
            proposed = self.doctor.propose_candidates(issue, hypotheses[0], evidence, pack, current_parameters)
            routed_candidates = tuple(self._executable_candidate(item, pack.ref, spec) for item in proposed)
            candidates = tuple(item for item in routed_candidates if item is not None)
            if not candidates:
                raise DiagnosisInconclusive(
                    "the diagnosed controls are not implemented by the routed DCC adapters",
                    "请选择具有已验证语义控制适配器的效果领域，或补充对应 DCC 执行器。",
                    {"domain": pack.identifier},
                )
        except DiagnosisInconclusive as exc:
            status = self.store.transition(
                task_id,
                TaskState.DIAGNOSIS_INCONCLUSIVE,
                str(exc),
                error_code=ErrorCode.DIAGNOSIS_INCONCLUSIVE,
                payload=exc.details,
            )
            result = {
                "task_id": task_id,
                "state": status["state"],
                "issue": issue.to_dict(),
                "evidence": evidence.to_dict(),
                "next_question": exc.next_question,
                "details": exc.details,
            }
            self.store.save_result(task_id, result)
            return result
        for hypothesis in hypotheses:
            self.store.put_record(task_id, "hypothesis", hypothesis.hypothesis_id, hypothesis.to_dict())
        for candidate in candidates:
            payload = candidate.to_dict()
            payload["domain"] = pack.ref.to_dict()
            self.store.put_record(task_id, "candidate", candidate.candidate_id, payload)
        status = self.store.transition(
            task_id,
            TaskState.CANDIDATES_READY,
            "evidence supports a bounded cause family and candidate previews",
            payload={"issue_id": issue.issue_id, "candidate_ids": [item.candidate_id for item in candidates]},
        )
        result = {
            "task_id": task_id,
            "state": status["state"],
            "issue": issue.to_dict(),
            "evidence": evidence.to_dict(),
            "hypotheses": [item.to_dict() for item in hypotheses],
            "candidates": [item.to_dict() for item in candidates],
        }
        self.store.save_result(task_id, result)
        return result

    def candidate_list(self, task_id: str) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "state": self.store.status(task_id)["state"],
            "candidates": list(self.store.records(task_id, "candidate")),
            "selection": list(self.store.records(task_id, "selection")),
        }

    @task_exclusive
    def candidate_select(self, task_id: str, candidate_id: str) -> dict[str, Any]:
        self._assert_frozen_sources(task_id)
        if self.store.status(task_id)["state"] != TaskState.CANDIDATES_READY.value:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "candidate selection requires CANDIDATES_READY")
        payload = next(
            (item for item in self.store.records(task_id, "candidate") if item.get("candidate_id") == candidate_id),
            None,
        )
        if payload is None:
            raise KeyError(candidate_id)
        candidate = self._candidate(payload)
        domain = DomainPackRef.from_mapping(payload["domain"])
        if domain.identifier == "explosion_composite_v1":
            return self._select_explosion_candidate(task_id, candidate, payload)
        houdini_patch, simulation_cache = self._houdini_candidate_contract(domain, candidate)
        nuke_controls = {"blur_size", "defocus", "defocus_size", "denoise_mix", "sharpen_size", "sharpen_amount", "glow_mix", "glow_size", "glow_amount", "emission_contrast", "comp_contrast", "edge_size", "grain_mix", "premult", "color_fusion_mix"}
        has_nuke_preview = any(item.get("application") == "nuke" for item in self.store.records(task_id, "subtask"))
        nuke_patch = {
            item.control: item.proposed
            for item in candidate.changes
            if item.control in nuke_controls and has_nuke_preview
        }
        routed_controls = set(houdini_patch) | set(nuke_patch)
        unrouted = sorted(item.control for item in candidate.changes if item.control not in routed_controls)
        if not routed_controls:
            raise PipelineExecutionError(
                ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                "the candidate has no semantic controls implemented by the selected DCC adapters",
                {"controls": [item.control for item in candidate.changes], "domain": domain.to_dict()},
            )
        selection = {
            "candidate": payload,
            "selected_at_state": TaskState.CANDIDATES_READY.value,
            "requires_simulation_cache": bool(houdini_patch and simulation_cache),
            "houdini_patch": houdini_patch,
            "nuke_patch": nuke_patch,
            "unrouted_controls": unrouted,
        }
        self.store.put_record(task_id, "selection", "current", selection)
        if houdini_patch:
            self.store.transition(task_id, TaskState.PREVIEWING, "rendering selected Houdini candidate in an isolated variant")
            try:
                record = self._run_selected_houdini_candidate(task_id, candidate, payload, houdini_patch)
                selection["dcc_preview"] = record
                if simulation_cache:
                    selection["host_cache_subject"] = self._extract_houdini_cache_subject(record)
                if nuke_patch:
                    selection["nuke_preview"] = self._apply_selected_nuke_candidate(task_id, candidate, nuke_patch)
            except Exception as exc:
                selection["preview_error"] = {
                    "code": str(getattr(exc, "code", ErrorCode.INTERNAL_ERROR.value)),
                    "message": str(exc),
                }
                self.store.put_record(task_id, "selection", "current", selection)
                if self.store.status(task_id)["state"] == TaskState.PREVIEWING.value:
                    self.store.transition(
                        task_id,
                        TaskState.CANDIDATES_READY,
                        "selected candidate preview failed; choose another candidate or add evidence",
                        payload={"candidate_id": candidate.candidate_id, "preview_error": selection["preview_error"]},
                    )
                raise
            self.store.put_record(task_id, "selection", "current", selection)
            if simulation_cache:
                status = self.store.transition(
                    task_id,
                    TaskState.CANDIDATES_READY,
                    "selected candidate preview is ready; cache is still unapproved",
                )
            else:
                self.store.transition(task_id, TaskState.CANDIDATES_READY, "selected non-simulation Houdini candidate preview is ready")
                status = self.store.transition(task_id, TaskState.VERIFYING, "selected non-simulation candidate is ready for visual verification")
        else:
            if nuke_patch:
                selection["nuke_preview"] = self._apply_selected_nuke_candidate(task_id, candidate, nuke_patch)
                self.store.put_record(task_id, "selection", "current", selection)
            status = self.store.transition(task_id, TaskState.VERIFYING, "selected non-simulation candidate is ready for visual verification")
        result = {"task_id": task_id, "status": status, "selection": selection}
        self.store.save_result(task_id, {**self._summary(task_id), "selection_result": result})
        return result

    def _select_explosion_candidate(
        self,
        task_id: str,
        candidate: CandidatePatch,
        candidate_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Re-run only explicitly mapped explosion component branches.

        A meta-control with no proven component adapter (currently the
        shockwave branch) is never sent to the whole explosion recipe.  The
        task terminates PARTIAL with an honest execution record instead.
        """

        mapped: dict[str, dict[str, Any]] = {}
        composite_patch: dict[str, Any] = {}
        unsupported: list[str] = []
        for change in candidate.changes:
            if change.control == "comp_contrast":
                composite_patch[change.control] = change.proposed
                continue
            target = EXPLOSION_BRANCH_CONTROL_MAP.get(change.control)
            if target is None:
                unsupported.append(change.control)
                continue
            branch_id, control = target
            mapped.setdefault(branch_id, {})[control] = change.proposed
        selection: dict[str, Any] = {
            "candidate": dict(candidate_payload),
            "selected_at_state": TaskState.CANDIDATES_READY.value,
            "component_branch_patches": mapped,
            "nuke_patch": composite_patch,
            "unrouted_controls": unsupported,
            "branch_local_recompute": bool(mapped or composite_patch) and not unsupported,
        }
        if unsupported:
            self.store.put_record(task_id, "selection", "current", selection)
            status = self.store.transition(
                task_id,
                TaskState.PARTIAL,
                "the selected explosion candidate contains controls without a proven component adapter; no partial candidate was executed",
                payload={"unrouted_controls": unsupported, "branch_local_recompute": False},
            )
            result = {"task_id": task_id, "status": status, "selection": selection}
            self.store.save_result(task_id, result)
            return result
        if composite_patch and not mapped and not unsupported:
            if not any(item.get("application") == "nuke" for item in self.store.records(task_id, "subtask")):
                unsupported.extend(composite_patch)
            else:
                selection["nuke_preview"] = self._apply_selected_nuke_candidate(task_id, candidate, composite_patch)
                selection["executed_branch_ids"] = ["composite"]
                self.store.put_record(task_id, "selection", "current", selection)
                status = self.store.transition(task_id, TaskState.VERIFYING, "only the explosion composite branch was recomputed")
                result = {"task_id": task_id, "status": status, "selection": selection}
                self.store.save_result(task_id, {**self._summary(task_id), "selection_result": result})
                return result
        if not mapped:
            self.store.put_record(task_id, "selection", "current", selection)
            status = self.store.transition(
                task_id,
                TaskState.PARTIAL,
                "explosion meta-control has no proven component branch adapter; whole-effect rerun was refused",
                payload={"unrouted_controls": unsupported, "branch_local_recompute": False},
            )
            result = {"task_id": task_id, "status": status, "selection": selection}
            self.store.save_result(task_id, result)
            return result
        if len(mapped) + (1 if composite_patch else 0) > 1:
            # One cache grant is intentionally scoped to one exact host cache
            # subject; silently combining several branches would weaken it.
            selection["branch_local_recompute"] = False
            selection["reason"] = "one candidate spans multiple simulation cache subjects"
            self.store.put_record(task_id, "selection", "current", selection)
            status = self.store.transition(
                task_id,
                TaskState.PARTIAL,
                "multi-branch explosion candidate requires independent cache subjects and cannot be committed atomically",
                payload={"branches": sorted([*mapped, *(["composite"] if composite_patch else [])]), "branch_local_recompute": False},
            )
            result = {"task_id": task_id, "status": status, "selection": selection}
            self.store.save_result(task_id, result)
            return result
        branch_id, patch = next(iter(mapped.items()))
        self.store.transition(task_id, TaskState.PREVIEWING, f"recomputing only explosion branch {branch_id}")
        try:
            record = self._run_selected_houdini_branch(task_id, candidate, branch_id, patch)
        except Exception as exc:
            selection["preview_error"] = {
                "code": str(getattr(exc, "code", ErrorCode.INTERNAL_ERROR.value)),
                "message": str(exc),
            }
            self.store.put_record(task_id, "selection", "current", selection)
            if self.store.status(task_id)["state"] == TaskState.PREVIEWING.value:
                self.store.transition(
                    task_id,
                    TaskState.CANDIDATES_READY,
                    f"explosion branch {branch_id} preview failed; choose another candidate or add evidence",
                    payload={"candidate_id": candidate.candidate_id, "branch_id": branch_id, "preview_error": selection["preview_error"]},
                )
            raise
        branch_pack = get_houdini_domain_pack(str(record["domain_pack"]))
        requires_simulation_cache = bool(branch_pack.simulation_cache)
        selection.update(
            {
                "requires_simulation_cache": requires_simulation_cache,
                "dcc_preview": record,
                "executed_branch_ids": [branch_id],
                "invalidated_downstream_branches": ["composite"],
            }
        )
        if requires_simulation_cache:
            selection["host_cache_subject"] = self._extract_houdini_cache_subject(record)
        self.store.put_record(task_id, "selection", "current", selection)
        status = self.store.transition(
            task_id,
            TaskState.CANDIDATES_READY,
            (
                f"explosion branch {branch_id} preview is ready; other simulation branches were preserved"
                if requires_simulation_cache
                else f"non-simulation explosion branch {branch_id} preview is ready"
            ),
            payload={"executed_branch_ids": [branch_id], "branch_local_recompute": True},
        )
        if not requires_simulation_cache:
            status = self.store.transition(
                task_id,
                TaskState.VERIFYING,
                f"non-simulation explosion branch {branch_id} is ready for visual verification",
            )
        result = {"task_id": task_id, "status": status, "selection": selection}
        self.store.save_result(task_id, {**self._summary(task_id), "selection_result": result})
        return result

    @task_exclusive
    def approval_request_cache(self, task_id: str) -> dict[str, Any]:
        self._assert_frozen_sources(task_id)
        selection = self._current_selection(task_id)
        if not selection.get("requires_simulation_cache"):
            raise PipelineExecutionError(ErrorCode.APPROVAL_SCOPE_MISMATCH.value, "the selected candidate does not require a Houdini simulation cache")
        host = dict(selection.get("host_cache_subject") or {})
        host_subject = dict(host.get("subject") or {})
        host_hash = str(host.get("subject_hash") or "")
        if not host_subject or not host_hash:
            raise PipelineExecutionError(ErrorCode.APPROVAL_REQUIRED.value, "selected preview did not produce a host cache subject")
        task = self.store.get_task(task_id)
        spec = TaskSpecV2.from_mapping(task["spec"])
        candidate_payload = dict(selection["candidate"])
        domain = DomainPackRef.from_mapping(candidate_payload["domain"])
        preview_domain = str((selection.get("dcc_preview") or {}).get("domain_pack") or "")
        if domain.identifier == "explosion_composite_v1" and preview_domain:
            domain = DomainPackRef(preview_domain, str((selection.get("dcc_preview") or {}).get("domain_version") or "1.0.0"))
        parameters = dict(selection.get("houdini_patch") or {})
        if not parameters and selection.get("component_branch_patches"):
            branch_patches = dict(selection["component_branch_patches"])
            executed = list(selection.get("executed_branch_ids") or [])
            parameters = dict(branch_patches.get(executed[0]) or {}) if executed else {}
        if not parameters:
            parameters = {item["control"]: item["proposed"] for item in candidate_payload.get("changes") or []}
        input_hashes = tuple(
            str(item.get("sha256")) for item in spec.inputs if item.get("sha256")
        ) or (str(host_subject.get("input_digest") or spec.subject_hash),)
        scene_hash = canonical_sha256(host_subject.get("scene") or {"scene_fingerprint": host_subject.get("scene_fingerprint")})
        raw_range = host_subject.get("frame_range") or spec.render.get("frame_range") or {}
        resource_policies = self.store.records(task_id, "cache_resource_policy")
        if not resource_policies:
            raise PipelineExecutionError(ErrorCode.APPROVAL_REQUIRED.value, "trusted controller must configure cache disk/time estimates and task roots")
        resource_policy = dict(resource_policies[-1])
        resource_contract = {**resource_policy,
            "output_path": str(host_subject.get("cache_output") or ""),
            "frame_range": list(self._frame_tuple(raw_range)),
            "content_version": scene_hash}
        subject = CacheApprovalSubject(
            task_id=task_id,
            scene_hash=scene_hash,
            input_hashes=input_hashes,
            reference_hashes=tuple(item.sha256 for item in spec.references),
            domain=domain,
            component_id=str((selection.get("executed_branch_ids") or candidate_payload.get("invalidates_components") or [domain.identifier])[0]),
            parameters=parameters,
            seed=int(host_subject.get("seed", spec.metadata.get("seed", 1))),
            frame_range=self._frame_tuple(raw_range),
            dcc_versions={"houdini": str(host_subject.get("houdini_version") or "unknown")},
            output_path=str(host_subject.get("cache_output") or ""),
            dependencies=tuple(str(item) for item in host_subject.get("related_nodes") or ()),
            metadata={
                "houdini_subject": host_subject,
                "houdini_subject_hash": host_hash,
                "dcc_subtask_id": str((selection.get("dcc_preview") or {}).get("subtask_id") or ""),
                "resource_contract": resource_contract,
                "resource_policy_hash": canonical_sha256(resource_policy),
            },
        )
        request = self.approvals.request_cache(subject)
        self.store.put_record(task_id, "cache_subject", request.request_id, subject.to_dict())
        result = request.to_dict()
        result["next_action"] = "A trusted human must grant this exact request before cache.run."
        return result

    @task_exclusive
    def cache_run(self, task_id: str, grant_id: str) -> dict[str, Any]:
        existing = next((row for row in self.store.records(task_id, "recovery") if row.get("phase") == "cache"), None)
        if existing and existing.get("grant_id") != grant_id and self.store.status(task_id)["state"] in {"PARTIAL", "CACHING"}:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "no matching cache continuation exists")
        try:
            return self._cache_run(task_id, grant_id)
        except Exception as exc:
            state = TaskState(self.store.status(task_id)["state"])
            if state in {TaskState.CACHING, TaskState.PARTIAL}:
                recovery = {
                    "phase": "cache",
                    "grant_id": grant_id,
                    "error_code": str(getattr(exc, "code", ErrorCode.INTERNAL_ERROR.value)),
                    "error_type": type(exc).__name__,
                    "requires_host_reconciliation": True,
                }
                self.store.put_record(task_id, "recovery", "cache", recovery)
                target = TaskState.PARTIAL
                if recovery["error_code"] in {
                    "SCENE_STATE_DRIFT", "APPROVAL_REVOKED", "APPROVAL_SUBJECT_MISMATCH",
                    "APPROVAL_SCOPE_MISMATCH", "APPROVAL_INVALID",
                }:
                    for active in self.store.active_grants(task_id, ApprovalScope.HOUDINI_SIMULATION_CACHE.value):
                        self.store.revoke_grant(str(active["grant_id"]))
                    target = TaskState.APPROVAL_REVOKED
                self.store.transition(
                    task_id, target,
                    "cache execution interrupted; reconcile host operation before retrying",
                    error_code=recovery["error_code"], payload=recovery,
                )
                self.store.save_result(task_id, {
                    "task_id": task_id, "state": target.value,
                    "recovery": recovery,
                })
            raise

    def _cache_run(self, task_id: str, grant_id: str) -> dict[str, Any]:
        initial_state = TaskState(self.store.status(task_id)["state"])
        recovering = initial_state in {TaskState.PARTIAL, TaskState.CACHING}
        if initial_state not in {TaskState.AWAITING_CACHE_APPROVAL, TaskState.PARTIAL, TaskState.CACHING}:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "cache.run requires AWAITING_CACHE_APPROVAL or a recoverable cache interruption")
        if recovering and not any(
            item.get("phase") == "cache" and item.get("grant_id") == grant_id
            for item in self.store.records(task_id, "recovery")
        ):
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "no matching cache continuation exists")
        try:
            self._assert_frozen_sources(task_id)
        except Exception:
            for active in self.store.active_grants(task_id, ApprovalScope.HOUDINI_SIMULATION_CACHE.value):
                self.store.revoke_grant(str(active["grant_id"]))
            current = TaskState(self.store.status(task_id)["state"])
            if TaskState.APPROVAL_REVOKED in self._allowed_targets(current):
                self.store.transition(task_id, TaskState.APPROVAL_REVOKED, "approval revoked because frozen source bytes changed")
            raise
        rows = self.store.records(task_id, "cache_subject")
        if not rows:
            raise PipelineExecutionError(ErrorCode.APPROVAL_REQUIRED.value, "no cache approval subject exists")
        subject = self._cache_subject(rows[-1])
        self._assert_cache_resource_policy(task_id, subject)
        grant = self.approvals.authorize_cache(grant_id, subject)
        selection = self._current_selection(task_id)
        preview = dict(selection.get("dcc_preview") or {})
        subtask_id = str(preview.get("subtask_id") or subject.metadata.get("dcc_subtask_id") or "")
        if not subtask_id:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "selected candidate has no persistent Houdini subtask id")
        sub_spec = dict(preview.get("spec") or {})
        constraints = dict(sub_spec.get("constraints") or {})
        fx = dict(constraints.get("fx") or {})
        approval_secret = load_approval_secret()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        host_subject_hash = str(subject.metadata["houdini_subject_hash"])
        signed = "{}:{}:{}:{}".format(
            ApprovalScope.HOUDINI_SIMULATION_CACHE.value,
            host_subject_hash,
            grant.grant_id,
            expires_at,
        )
        resource_hash = canonical_sha256(subject.metadata["resource_contract"])
        signed += ":" + resource_hash
        signature = hmac.new(approval_secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
        fx.update(
            {
                "domain_pack": subject.domain.identifier,
                "cache_output": subject.output_path,
                "resource_contract": dict(subject.metadata["resource_contract"]),
                "approval": {
                    "purpose": ApprovalScope.HOUDINI_SIMULATION_CACHE.value,
                    "subject_hash": host_subject_hash,
                    "grant_id": grant.grant_id,
                    "expires_at": expires_at,
                    "signature": signature,
                    "resource_contract_hash": resource_hash,
                },
            }
        )
        constraints["fx"] = fx
        payload = {
            "task_id": subtask_id,
            "intent": sub_spec.get("intent"),
            "constraints": constraints,
            "render": dict(sub_spec.get("render") or {}),
            "delivery": dict(sub_spec.get("delivery") or {}),
            "target_scene": (sub_spec.get("target") or {}).get("scene_mode", "current"),
            "inputs": list(sub_spec.get("inputs") or []),
            "step_params": {"domain_pack": subject.domain.identifier},
        }
        # Write intent before the state change and before any host dispatch.
        self.store.put_record(task_id, "recovery", "cache", {"phase": "cache", "grant_id": grant_id, "requires_host_reconciliation": True, "host_subject_hash": host_subject_hash})
        if initial_state is not TaskState.CACHING:
            self.store.transition(task_id, TaskState.CACHING, "trusted cache grant authorized; starting exact Houdini cache subject")
        preview_leg = RouteLeg(
            "houdini",
            str(preview.get("domain_pack") or subject.domain.identifier),
            str(preview.get("domain_version") or subject.domain.version),
            int(preview.get("port") or 0),
            str(preview.get("purpose") or "candidate_preview"),
            str(preview.get("backend_id") or ""),
            str(preview.get("protocol") or ""),
            str(preview.get("session") or ""),
        )
        client = self.router.client_for_leg(preview_leg)
        timeout = min(float(subject.metadata["resource_contract"]["max_seconds"]),
                      max(1.0, float(os.environ.get("VFX_PIPELINE_CACHE_WAIT_SECONDS", "120"))))
        deadline = time.monotonic() + timeout
        query_payload = {**payload, "expected_subject_hash": host_subject_hash}
        if recovering:
            result = client.call("agent.fx.cache_status", query_payload)
            # Only an exact-subject, explicitly absent operation may be started.
            if str((result.get("cache") or {}).get("state") or "") in {"NOT_STARTED", "SUBMISSION_PENDING"}:
                result = client.call("agent.fx.cache", payload)
        else:
            result = client.call("agent.fx.cache", payload)
        while not (
            bool(result.get("cached"))
            and str((result.get("cache") or {}).get("state") or "") == "COMPLETE"
            and bool(result.get("artifacts"))
        ):
            if str((result.get("cache") or {}).get("state") or "") in {"FAILED", "CANCELLED", "BUDGET_REACHED", "RECONCILE"}:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "host cache operation failed; inspect its recorded error before retrying", result)
            if time.monotonic() >= deadline:
                operation_id = (result.get("cache") or {}).get("operation_id")
                if operation_id:
                    try:
                        client.call("operation.cancel", {"task_id": subtask_id, "operation_id": str(operation_id)})
                    except Exception:
                        # The deadline is not proof of stop. Recovery retains
                        # the host operation identity and its occupied slot.
                        pass
                self.store.transition(
                    task_id,
                    TaskState.PARTIAL,
                    "approved Houdini cache did not complete before the bounded wait expired",
                    error_code=ErrorCode.ARTIFACT_MISSING,
                    payload={"last_cache_response": result},
                )
                raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "approved Houdini cache is incomplete", result)
            time.sleep(0.25)
            result = client.call("agent.fx.cache_status", query_payload)
        cache_policy = houdini_gate_policy("agent.fx.cache")
        gates = cache_policy.normalize("approved_houdini_cache", result)
        if any(not bool(item.get("passed")) for item in gates):
            self.store.transition(task_id, TaskState.FAILED, "Houdini cache gate failed", error_code=ErrorCode.ARTIFACT_INVALID)
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "Houdini cache gate failed", result)
        result = {**dict(result), "gates": gates}
        verified_artifacts = self._record_cache_artifacts(task_id, subject, grant.grant_id, result)
        result = {**dict(result), "verified_artifacts": verified_artifacts}
        self.store.put_record(task_id, "cache", grant.grant_id, result)
        status = self.store.transition(task_id, TaskState.VERIFYING, "approved Houdini cache started; verify artifacts and visual result")
        response = {"task_id": task_id, "status": status, "grant": grant.to_dict(), "cache": result}
        self.store.save_result(task_id, response)
        return response

    @task_exclusive
    def verification_record(self, task_id: str, measurement: Mapping[str, Any]) -> dict[str, Any]:
        """Compute and persist a technical scorecard from immutable artifacts.

        Callers select artifact IDs and an allowlisted metric policy; they do
        not supply ``target_improved`` or regression booleans.  Both artifact
        files are re-hashed before deterministic MetricEngine evaluation.
        """

        self._assert_frozen_sources(task_id)
        if self.store.status(task_id)["state"] != TaskState.VERIFYING.value:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "verification.record requires VERIFYING")
        selection = self._current_selection(task_id)
        candidate = self._candidate(selection["candidate"])
        issue_payload = next(
            (item for item in self.store.records(task_id, "issue") if item.get("issue_id") == candidate.issue_id),
            None,
        )
        if issue_payload is None:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "selected candidate has no durable issue")
        issue = self._issue(issue_payload)
        before = self._verified_artifact(task_id, str(measurement.get("before_artifact_id") or ""), allow_reference=False)
        after = self._verified_artifact(task_id, str(measurement.get("after_artifact_id") or ""), allow_reference=False)
        kind = str(measurement.get("metric_kind") or "raster")
        before_values, before_source = self._metric_values(before, kind)
        after_values, after_source = self._metric_values(after, kind)
        provenance = MetricProvenance(
            source_kind=f"{before_source}_to_{after_source}",
            artifact_ids=(str(before["artifact_id"]), str(after["artifact_id"])),
            input_hashes=(str(before["sha256"]), str(after["sha256"])),
            metadata={"task_id": task_id, "candidate_id": candidate.candidate_id},
        )
        before_metrics = self._metric_summary(kind, before_values, provenance)
        after_metrics = self._metric_summary(kind, after_values, provenance)
        target_name = str(measurement.get("target_metric") or self._default_target_metric(issue.dimension, kind))
        if target_name not in before_metrics or target_name not in after_metrics:
            raise PipelineExecutionError(
                ErrorCode.INVALID_SPEC.value,
                "target metric is unavailable for the selected metric kind",
                {"target_metric": target_name, "available": sorted(before_metrics)},
            )
        minimum_delta = float(measurement.get("minimum_delta", 0.0))
        if minimum_delta < 0:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "minimum_delta must be non-negative")
        before_target, after_target = before_metrics[target_name], after_metrics[target_name]
        if issue.direction is ChangeDirection.DECREASE:
            target_improved = after_target <= before_target - minimum_delta
        elif issue.direction is ChangeDirection.INCREASE:
            target_improved = after_target >= before_target + minimum_delta
        else:
            raise PipelineExecutionError(
                ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                "technical verification cannot infer the expected metric direction",
                {"issue_direction": issue.direction.value},
            )
        protected_regressions = self._protected_metric_regressions(
            issue,
            before_metrics,
            after_metrics,
            measurement.get("protected_metric_limits") or {},
        )
        if kind == "sequence" and before_metrics.get("sequence.temporal_delta", 0) > 0 and after_metrics.get("sequence.temporal_delta", 0) == 0:
            protected_regressions = tuple(protected_regressions) + ("motion_frozen",)
            target_improved = False
        scorecard = VisualScorecard(
            issue_id=issue.issue_id,
            candidate_id=candidate.candidate_id,
            before=before_metrics,
            after=after_metrics,
            target_improved=target_improved,
            protected_regressions=protected_regressions,
            notes=(f"MetricEngine evaluated {kind} artifacts via {before_source}/{after_source} with current SHA-256 verification.",),
        )
        payload = {
            "verification_id": new_identifier("verification"),
            "task_id": task_id,
            "issue_id": issue.issue_id,
            "candidate_id": candidate.candidate_id,
            "artifact_ids": [before["artifact_id"], after["artifact_id"]],
            "artifact_hashes": [before["sha256"], after["sha256"]],
            "metric_kind": kind,
            "target_metric": target_name,
            "scorecard": scorecard.to_dict(),
            "recorded_at": now_iso(),
        }
        payload["verification_hash"] = canonical_sha256(payload)
        self.store.put_record(task_id, "technical_verification", payload["verification_id"], payload)
        self.store.save_result(task_id, {**self._summary(task_id), "technical_verification": payload})
        return payload

    @task_exclusive
    def approval_request_experience(self, task_id: str) -> dict[str, Any]:
        rows = self.store.records(task_id, "trusted_acceptance")
        if not rows:
            raise PolicyDenied(
                ErrorCode.TRUSTED_HUMAN_REQUIRED,
                "experience promotion requires a trusted-human final-result acceptance record",
            )
        experience = self._experience(rows[-1]["experience"], expected_task_id=task_id)
        request = self.experiences.request_promotion(experience)
        self.store.put_record(
            task_id,
            "pending_experience",
            request.request_id,
            {"request_id": request.request_id, "experience": experience.to_dict()},
        )
        result = request.to_dict()
        result["next_action"] = "A separate trusted-human grant is required; the cache grant cannot promote experience."
        return result

    def experience_search(
        self,
        domain_identifier: str,
        version: str = "1.0.0",
        task_id: Optional[str] = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        domain = DomainPackRef(domain_identifier, version)
        issue = None
        if task_id:
            matches = [item for item in self.store.records(task_id, "issue") if (item.get("domain") or {}) == domain.to_dict()]
            if matches:
                issue = self._issue(matches[-1])
        return {"matches": [item.to_dict() for item in self.experiences.search(domain, issue, limit)]}

    @staticmethod
    def _api_key(config: Mapping[str, Any]) -> str:
        if "api_key" in config:
            raise PolicyDenied(ErrorCode.POLICY_DENIED, "inline model API keys are forbidden; use api_key_env")
        variable = str(config.get("api_key_env") or "").strip()
        if not variable:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "model config requires api_key_env")
        value = os.environ.get(variable, "")
        if not value:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "configured model API key environment variable is unset")
        return value

    @classmethod
    def _planner_gateway(cls, config: Mapping[str, Any]):
        provider = str(config.get("provider") or "deepseek")
        if provider == "doubao-desktop":
            raise PipelineExecutionError(
                ErrorCode.BRIDGE_UNREACHABLE.value,
                "doubao-desktop requires a trusted, injected desktop transport; config files cannot manufacture UI-control evidence",
                {"provider": provider, "route_id": "DoubaoDesktopRoute"},
            )
        if provider != "deepseek":
            raise PipelineExecutionError(ErrorCode.MODEL_CAPABILITY_MISMATCH.value, "unsupported planner provider", {"provider": provider})
        return DeepSeekResponsesPlannerGateway(
            cls._api_key(config),
            model=str(config.get("model") or "deepseek-v4-flash"),
            base_url=str(config.get("base_url") or "https://api.deepseek.com"),
            timeout=float(config.get("timeout", 30.0)),
        )

    @classmethod
    def _vision_gateway(cls, config: Mapping[str, Any], references):
        provider = str(config.get("provider") or "openai-compatible")
        if provider != "openai-compatible":
            raise PipelineExecutionError(ErrorCode.MODEL_CAPABILITY_MISMATCH.value, "unsupported vision provider", {"provider": provider})
        return OpenAICompatibleVisionGateway(
            cls._api_key(config),
            model=str(config.get("model") or "hy3"),
            base_url=str(config.get("base_url") or "http://127.0.0.1:8000/v1"),
            timeout=float(config.get("timeout", 60.0)),
            probe_references=tuple(references),
        )

    def _model_tools_for_task(self, task_id, state):
        reference_rows = [
            row for row in self.store.records(task_id, "continuation")
            if row.get("phase") == "reference_analysis"
        ]
        if (
            state is TaskState.AWAITING_INPUT
            and reference_rows
            and not any(row.get("resume_mode") == "graph_construction_only" for row in reference_rows)
        ):
            return (
                ToolDescriptor("task.status", "Read the durable task state.", {"type": "object", "properties": {}, "additionalProperties": False}),
                ToolDescriptor("task.resume", "Build the initial preview using the completed reference analysis; refuses if analysis is missing.", {"type": "object", "properties": {}, "additionalProperties": False}),
            )
        return self._model_tools_for_state(state)

    @staticmethod
    def _model_tools_for_state(state: TaskState) -> tuple[ToolDescriptor, ...]:
        no_args = {"type": "object", "properties": {}, "additionalProperties": False}
        if state in {TaskState.AWAITING_INPUT, TaskState.DIAGNOSING, TaskState.DIAGNOSIS_INCONCLUSIVE}:
            return (
                ToolDescriptor("task.status", "Read the durable task state.", no_args),
                ToolDescriptor(
                    "feedback.diagnose",
                    "Diagnose one explicit feedback issue from supplied deterministic evidence.",
                    {
                        "type": "object",
                        "properties": {
                            "feedback": {"type": "string"},
                            "evidence": {"type": "object"},
                            "domain": {"type": "string"},
                        },
                        "required": ["feedback", "evidence"],
                        "additionalProperties": False,
                    },
                ),
            )
        if state is TaskState.CANDIDATES_READY:
            return (
                ToolDescriptor("candidate.list", "List bounded candidates.", no_args),
                ToolDescriptor(
                    "candidate.select",
                    "Select one candidate for an isolated preview.",
                    {"type": "object", "properties": {"candidate_id": {"type": "string"}}, "required": ["candidate_id"], "additionalProperties": False},
                ),
                ToolDescriptor("approval.request-cache", "Request exact simulation-cache approval after candidate selection.", no_args),
            )
        if state is TaskState.AWAITING_CACHE_APPROVAL:
            return (
                ToolDescriptor(
                    "cache.run",
                    "Consume an already-issued trusted cache grant; refuses without one.",
                    {"type": "object", "properties": {"grant_id": {"type": "string"}}, "required": ["grant_id"], "additionalProperties": False},
                ),
                ToolDescriptor("task.status", "Read the durable task state.", no_args),
            )
        if state is TaskState.VERIFYING:
            return (
                ToolDescriptor(
                    "verification.record",
                    "Compute a technical scorecard from registered immutable artifact IDs.",
                    {"type": "object", "properties": {"measurement": {"type": "object"}}, "required": ["measurement"], "additionalProperties": False},
                ),
                ToolDescriptor("approval.request-experience", "Request experience promotion after trusted artist acceptance exists.", no_args),
                ToolDescriptor("task.result", "Read the current result.", no_args),
            )
        return (ToolDescriptor("task.status", "Read the durable task state.", no_args),)

    def _execute_model_action(self, task_id: str, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool not in {
            "task.status", "task.result", "task.resume", "feedback.diagnose", "candidate.list", "candidate.select",
            "approval.request-cache", "cache.run", "verification.record", "approval.request-experience",
        }:
            raise PolicyDenied(ErrorCode.POLICY_DENIED, "planner action is not model-safe")
        if tool == "task.status":
            return self.task_status(task_id)
        if tool == "task.result":
            return self.task_result(task_id)
        if tool == "task.resume":
            return self.task_resume(task_id)
        if tool == "feedback.diagnose":
            return self.feedback_diagnose(
                task_id,
                str(arguments.get("feedback") or ""),
                dict(arguments.get("evidence") or {}),
                str(arguments.get("domain")) if arguments.get("domain") else None,
            )
        if tool == "candidate.list":
            return self.candidate_list(task_id)
        if tool == "candidate.select":
            return self.candidate_select(task_id, str(arguments.get("candidate_id") or ""))
        if tool == "approval.request-cache":
            return self.approval_request_cache(task_id)
        if tool == "cache.run":
            return self.cache_run(task_id, str(arguments.get("grant_id") or ""))
        if tool == "verification.record":
            return self.verification_record(task_id, dict(arguments.get("measurement") or {}))
        return self.approval_request_experience(task_id)

    def _external_run_verification(
        self,
        task_id: str,
        run: Mapping[str, Any],
        *,
        validated_analysis: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Verify controller-originated reference-analysis binding evidence.

        Legacy placeholder registrations remain readable for observation-only
        ingress, but they never unlock DCC dispatch.  Only a self-consistent
        trusted-controller record whose media/source/output digests still match
        the task is execution-verified.
        """
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        source = self._assert_frozen_sources(task_id)
        expected_refs = [item.sha256 for item in spec.references]
        route_ok = run.get("route_id") == "WorkBuddyDesktopRoute" and str(run.get("selected_model", "")).casefold() == "hy3"
        if not route_ok:
            raise PipelineExecutionError(ErrorCode.MODEL_CAPABILITY_MISMATCH.value, "this ingress requires the registered WorkBuddy HY3 route")
        result = {
            "route_execution_verified": False,
            "provider_identity_verified": False,
            "provider_identity_scope": "unverified",
            "run_record_hash": None,
        }
        if not run.get("run_record_hash"):
            return result
        body = dict(run)
        supplied_hash = body.pop("run_record_hash", None)
        if supplied_hash != canonical_sha256(body):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run registration hash changed")
        if body.get("task_id") != task_id:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "external run belongs to a different task")
        if body.get("input_class") != "synthetic":
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "this software validation route accepts synthetic media only")
        if body.get("reference_hashes") != expected_refs or body.get("source_manifest_hash") != source.get("manifest_hash"):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run media/source binding is stale")
        if body.get("route_execution_verified") is not True or body.get("trusted_control_authorized") is not True:
            return result
        if validated_analysis is not None:
            output_hash = canonical_sha256(dict(validated_analysis))
            if body.get("analysis_output_sha256") != output_hash:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external analysis does not match the trusted tool receipt")
        receipt = body.get("tool_receipt")
        if not isinstance(receipt, Mapping):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run tool receipt is missing")
        if receipt.get("output_sha256") != body.get("analysis_output_sha256"):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run output receipt changed")
        capture_id = str(body.get("collector_record_id") or "")
        captures = [
            row for row in self.store.records(task_id, "reference_analysis_capture")
            if row.get("capture_id") == capture_id
        ]
        if len(captures) != 1:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "external run controlled response capture is missing")
        capture = dict(captures[0])
        capture_hash = capture.pop("capture_hash", None)
        if capture_hash != canonical_sha256(capture) or capture_hash != body.get("collector_record_hash"):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run controlled response capture changed")
        if (capture.get("task_id") != task_id or capture.get("run_id") != body.get("run_id")
                or capture.get("session_id") != body.get("session_id")
                or capture.get("source_manifest_hash") != body.get("source_manifest_hash")
                or capture.get("analysis_output_sha256") != body.get("analysis_output_sha256")
                or capture.get("tool_receipt") != receipt
                or capture.get("route_exchange_captured") is not True):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "external run is not bound to its controlled connector capture")
        result.update(
            route_execution_verified=True,
            provider_identity_verified=body.get("provider_identity_verified") is True,
            provider_identity_scope=str(body.get("provider_identity_scope") or "workbuddy_app_hy3_selection_only"),
            run_record_hash=supplied_hash,
        )
        return result

    @task_exclusive
    def reference_analysis_submit(
        self, task_id: str, analysis: Mapping[str, Any], *, run_id: str, request_id: str,
    ) -> dict[str, Any]:
        """Persist an external observation without dispatching any DCC work.

        The controller registers the run separately; callers cannot supply
        provenance, source hashes or verification flags in the observation.
        A reconnect may replay this idempotent ingress even after task progress.
        """
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "a stable request_id is required")
        runs = [row for row in self.store.records(task_id, "external_model_run") if row.get("run_id") == run_id]
        if len(runs) != 1:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "external run must be registered by the controller")
        run = runs[0]
        from dcc_task_runtime.visual_objective import MediaManifest, VisualObjective, validate_reference_analysis
        validated = validate_reference_analysis(analysis).to_dict()
        verification = self._external_run_verification(task_id, run, validated_analysis=validated)
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        if not spec.references:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "reference analysis requires registered media")
        self._assert_frozen_sources(task_id)
        objective = VisualObjective.from_reference_analysis(MediaManifest.from_reference_assets(spec.references), validated)
        request_hash = canonical_sha256({"run_id": run_id, "analysis": validated, "references": [r.sha256 for r in spec.references]})
        record_id = "external_" + canonical_sha256({"run_id": run_id, "request_id": request_id})
        existing = next((row for row in self.store.records(task_id, "reference_analysis") if row.get("analysis_id") == record_id), None)
        if existing is not None:
            if existing.get("request_hash") != request_hash:
                raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "request_id belongs to a different observation")
            return {"task_id": task_id, "analysis_id": record_id, "analysis_hash": existing["analysis_hash"], "replayed": True, "dcc_dispatched": False}
        if self.store.status(task_id)["state"] != TaskState.AWAITING_INPUT.value:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "initial observation may only be submitted while awaiting reference input")
        if not any(row.get("phase") == "reference_analysis" for row in self.store.records(task_id, "continuation")):
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "task is not awaiting reference analysis")
        record = {"analysis_id": record_id, "run_id": run_id, "route_id": run["route_id"],
                  "request_hash": request_hash, "reference_hashes": [r.sha256 for r in spec.references],
                  "analysis": validated, "created_at": now_iso(), "maturity": "experimental",
                  "visual_objective": objective.to_dict(), "source_plan": objective.source_plan().to_dict(),
                  "external_run_record_hash": verification["run_record_hash"],
                  "route_execution_verified": verification["route_execution_verified"],
                  "provider_identity_verified": verification["provider_identity_verified"],
                  "provider_identity_scope": verification["provider_identity_scope"]}
        record["analysis_hash"] = canonical_sha256(record)
        self.store.put_record(task_id, "reference_analysis", record_id, record)
        return {"task_id": task_id, "analysis_id": record_id, "analysis_hash": record["analysis_hash"], "replayed": False, "dcc_dispatched": False}

    def _spec_with_analysis(self, task_id: str, spec: TaskSpecV2) -> TaskSpecV2:
        if not spec.references:
            return spec
        rows = self.store.records(task_id, "reference_analysis")
        if not rows:
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value, "reference analysis has not completed")
        record = dict(rows[-1])
        expected = record.pop("analysis_hash", None)
        if expected != canonical_sha256(record) or record.get("reference_hashes") != [item.sha256 for item in spec.references]:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "reference analysis does not match frozen inputs")
        # Legacy/internal reference-analysis records do not carry an external
        # desktop route binding.  Preserve that trusted in-process path while
        # requiring every record that claims an external run/route to satisfy
        # the independent controller evidence contract below.  A model cannot
        # turn an internal record into an external authorization by supplying a
        # boolean such as ``verified``.
        verification = None
        has_external_binding = record.get("route_id") is not None or record.get("run_id") is not None
        if has_external_binding:
            if record.get("route_id") != "WorkBuddyDesktopRoute" or not record.get("run_id"):
                raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "reference analysis external route binding is invalid")
            run = next(
                (row for row in self.store.records(task_id, "external_model_run") if row.get("run_id") == record.get("run_id")),
                None,
            )
            if run is None:
                raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "external analysis run registration is missing")
            verification = self._external_run_verification(task_id, run, validated_analysis=dict(record.get("analysis") or {}))
            if record.get("external_run_record_hash") not in {None, verification.get("run_record_hash")} or record.get("route_execution_verified") not in {None, verification["route_execution_verified"]}:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "reference analysis execution binding changed")
        metadata = {**dict(spec.metadata), "reference_analysis": dict(record.get("analysis") or {})}
        for key in ("visual_objective", "source_plan"):
            if key in record:
                metadata[key] = dict(record[key])
        if verification is not None:
            metadata["external_analysis_execution_verified"] = verification["route_execution_verified"]
            metadata["provider_identity_verified"] = verification["provider_identity_verified"]
            metadata["provider_identity_scope"] = verification["provider_identity_scope"]
        return replace(spec, metadata=metadata)

    def _run_initial_previews(
        self,
        task_id: str,
        spec: TaskSpecV2,
        plan: Mapping[str, Any],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        spec = self._spec_with_analysis(task_id, spec)
        if spec.metadata.get("external_analysis_execution_verified") is False:
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value, "external analysis requires trusted session and media receipt verification before DCC execution")
        if "source_plan" in spec.metadata and not spec.metadata["source_plan"].get("ready", False):
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value, "visual source plan is missing required observations")
        pending: list[str] = []
        dcc_outcomes: list[dict[str, Any]] = []
        effect_input = self._input_by_role(spec, "effect_render")
        for domain in plan["domains"]:
            is_explosion = str(domain.get("identifier") or "") == "explosion_composite_v1"
            branches = list(domain.get("component_branches") or [])
            routed_items = [
                (branch, raw_leg)
                for branch in branches
                for raw_leg in branch.get("route") or []
            ] if branches else [(None, raw_leg) for raw_leg in domain["route"]]
            for branch, raw_leg in routed_items:
                leg = RouteLeg(
                    application=str(raw_leg["application"]),
                    domain_pack=str(raw_leg["domain_pack"]),
                    domain_version=str(raw_leg["domain_version"]),
                    port=int(raw_leg["port"]),
                    purpose=str(raw_leg["purpose"]),
                    backend_id=str(raw_leg.get("backend_id") or ""),
                    protocol=str(raw_leg.get("protocol") or ""),
                    session=str(raw_leg.get("session") or ""),
                )
                if leg.application == "nuke" and effect_input is None:
                    pending.append(
                        f"{leg.domain_pack} branch needs an effect_render sequence before Nuke compositing; Houdini's editable technical preview is not a rendered image"
                    )
                    continue
                sub_spec = self._subtask_spec(spec, leg, effect_input, run_mode="diagnose")
                result = self._run_subtask(task_id, leg, sub_spec, branch)
                child_state = str((result.get("result") or {}).get("state") or "")
                if child_state in {
                    TaskState.DIAGNOSIS_INCONCLUSIVE.value,
                    TaskState.AWAITING_INPUT.value,
                    TaskState.UNSUPPORTED.value,
                }:
                    dcc_outcomes.append(
                        {
                            "application": leg.application,
                            "domain_pack": leg.domain_pack,
                            "subtask_id": result.get("subtask_id"),
                            "state": child_state,
                            "next_action": (result.get("result") or {}).get("next_action"),
                        }
                    )
                    continue
                if leg.application == "houdini" and effect_input is None and not is_explosion:
                    effect_input = self._effect_input_from_subtask(result)
                if leg.application == "nuke":
                    self._assert_nuke_reference_isolation(result)
        return pending, dcc_outcomes

    def _run_subtask(
        self,
        task_id: str,
        leg: RouteLeg,
        spec: dict[str, Any],
        branch: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        client = self.router.client_for_leg(leg)
        root = self._subtask_root / leg.application
        service = self._service_factories[leg.application](client, root)
        started = service.start(spec, background=False)
        subtask_id = str(started["task_id"])
        result = service.result(subtask_id) or {}
        state = str(result.get("state") or (started.get("status") or {}).get("state") or "")
        record = {
            "execution_id": uuid4().hex,
            "application": leg.application,
            "domain_pack": leg.domain_pack,
            "domain_version": leg.domain_version,
            "purpose": leg.purpose,
            "port": leg.port,
            "backend_id": leg.backend_id,
            "protocol": leg.protocol,
            "session": leg.session,
            "subtask_id": subtask_id,
            "spec": spec,
            "result": result,
            "spec_hash": canonical_sha256(spec),
            "result_hash": canonical_sha256(result),
        }
        if branch is not None:
            record.update(
                {
                    "branch_id": str(branch["branch_id"]),
                    "branch_hash": str(branch["branch_hash"]),
                    "branch_dependencies": list(branch.get("dependencies") or []),
                }
            )
        self.store.put_record(task_id, "subtask", f"{leg.domain_pack}:{leg.application}:{subtask_id}", record)
        if branch is not None:
            self.store.put_record(task_id, "branch_execution", record["execution_id"], record)
        self._record_artifacts(task_id, leg, result)
        run_mode = str(((spec.get("constraints") or {}).get("fx") or {}).get("run_mode") or (spec.get("constraints") or {}).get("run_mode") or "delivery")
        nonfatal_diagnostic_states = {
            TaskState.DIAGNOSIS_INCONCLUSIVE.value,
            TaskState.AWAITING_INPUT.value,
            TaskState.UNSUPPORTED.value,
        }
        if state in nonfatal_diagnostic_states and run_mode == "diagnose":
            return record
        if state != TaskState.SUCCEEDED.value:
            code_by_state = {
                TaskState.DIAGNOSIS_INCONCLUSIVE.value: ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                TaskState.AWAITING_INPUT.value: ErrorCode.AWAITING_INPUT.value,
                TaskState.PARTIAL.value: ErrorCode.PARTIAL.value,
                TaskState.UNSUPPORTED.value: ErrorCode.UNSUPPORTED_DOMAIN.value,
                TaskState.CANCELLED.value: ErrorCode.CANCELLED.value,
                TaskState.FAILED.value: str(result.get("error_code") or ErrorCode.INTERNAL_ERROR.value),
            }
            raise PipelineExecutionError(
                code_by_state.get(state, ErrorCode.INTERNAL_ERROR.value),
                f"{leg.application} subtask did not succeed for {leg.domain_pack}",
                {"subtask_id": subtask_id, "result": result},
            )
        return record

    def _run_selected_houdini_candidate(
        self,
        task_id: str,
        candidate: CandidatePatch,
        candidate_payload: Mapping[str, Any],
        houdini_patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        spec = self._spec_with_analysis(task_id, TaskSpecV2.from_mapping(task["spec"]))
        domain = DomainPackRef.from_mapping(candidate_payload["domain"])
        plan = self.store.records(task_id, "plan")[-1]
        raw_leg = next(
            raw
            for item in plan["domains"]
            if item["identifier"] == domain.identifier and item["version"] == domain.version
            for raw in item["route"]
            if raw["application"] == "houdini"
        )
        leg = RouteLeg(
            "houdini", domain.identifier, domain.version, int(raw_leg["port"]), str(raw_leg["purpose"]),
            str(raw_leg.get("backend_id") or ""), str(raw_leg.get("protocol") or ""), str(raw_leg.get("session") or ""),
        )
        sub_spec = self._subtask_spec(
            spec,
            leg,
            self._input_by_role(spec, "effect_render"),
            run_mode="candidate_preview",
        )
        constraints = dict(sub_spec.get("constraints") or {})
        fx = dict(constraints.get("fx") or {})
        fx["candidate_patch"] = dict(houdini_patch)
        fx["perceptual_issue"] = next(
            (
                item
                for item in self.store.records(task_id, "issue")
                if item.get("issue_id") == candidate.issue_id
            ),
            {},
        )
        constraints["fx"] = fx
        sub_spec["constraints"] = constraints
        return self._run_subtask(task_id, leg, sub_spec)

    def _run_selected_houdini_branch(
        self,
        task_id: str,
        candidate: CandidatePatch,
        branch_id: str,
        patch: Mapping[str, Any],
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        spec = TaskSpecV2.from_mapping(task["spec"])
        plan = self.store.records(task_id, "plan")[-1]
        meta = next(item for item in plan["domains"] if item["identifier"] == "explosion_composite_v1")
        branch = next(item for item in meta.get("component_branches") or [] if item["branch_id"] == branch_id)
        raw_leg = next(item for item in branch["route"] if item["application"] == "houdini")
        leg = RouteLeg(
            "houdini",
            str(branch["domain_pack"]),
            str(branch["domain_version"]),
            int(raw_leg["port"]),
            str(raw_leg["purpose"]),
            str(raw_leg.get("backend_id") or ""),
            str(raw_leg.get("protocol") or ""),
            str(raw_leg.get("session") or ""),
        )
        sub_spec = self._subtask_spec(
            spec,
            leg,
            self._input_by_role(spec, "effect_render"),
            run_mode="candidate_preview",
        )
        constraints = dict(sub_spec.get("constraints") or {})
        fx = dict(constraints.get("fx") or {})
        fx["candidate_patch"] = dict(patch)
        fx["perceptual_issue"] = next(
            (item for item in self.store.records(task_id, "issue") if item.get("issue_id") == candidate.issue_id),
            {},
        )
        constraints["fx"] = fx
        sub_spec["constraints"] = constraints
        return self._run_subtask(task_id, leg, sub_spec, branch)

    @staticmethod
    def _extract_houdini_cache_subject(record: Mapping[str, Any]) -> dict[str, Any]:
        result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
        step_outputs = result.get("step_outputs") if isinstance(result.get("step_outputs"), Mapping) else {}
        gate_groups = [
            list(step.get("gates") or [])
            for step in step_outputs.values()
            if isinstance(step, Mapping)
        ]
        for step in step_outputs.values():
            if not isinstance(step, Mapping):
                continue
            output = step.get("output") if isinstance(step.get("output"), Mapping) else {}
            if output.get("cache_subject_hash") and output.get("cache_approval_subject"):
                return {
                    "subject_hash": str(output["cache_subject_hash"]),
                    "subject": dict(output["cache_approval_subject"]),
                }
        # The aggregate gate list is retained as a bounded v1 compatibility
        # fallback.  New tasks consume the exact, step-owned checkpoint first;
        # no structured payload is smuggled through an evidence-carrier gate.
        gate_groups.append(list(result.get("gates") or []))
        gates = [gate for group in gate_groups for gate in group if isinstance(gate, Mapping)]
        for gate in gates:
            if gate.get("cache_subject_hash") and gate.get("cache_approval_subject"):
                return {
                    "subject_hash": str(gate["cache_subject_hash"]),
                    "subject": dict(gate["cache_approval_subject"]),
                }
            details = gate.get("details") if isinstance(gate.get("details"), Mapping) else {}
            if details.get("cache_subject_hash") and details.get("cache_approval_subject"):
                return {
                    "subject_hash": str(details["cache_subject_hash"]),
                    "subject": dict(details["cache_approval_subject"]),
                }
        raise PipelineExecutionError(
            ErrorCode.APPROVAL_REQUIRED.value,
            "Houdini candidate preview did not persist its exact cache approval subject",
        )

    def _apply_selected_nuke_candidate(self, task_id: str, candidate: CandidatePatch, nuke_patch: Mapping[str, Any]) -> dict[str, Any]:
        record = next(
            (
                item
                for item in reversed(self.store.records(task_id, "subtask"))
                if item.get("application") == "nuke"
            ),
            None,
        )
        if record is None:
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value if hasattr(ErrorCode, "AWAITING_INPUT") else ErrorCode.INVALID_SPEC.value, "no persistent Nuke composite preview exists")
        record_leg = RouteLeg(
            "nuke",
            str(record.get("domain_pack") or "nuke_composite_v1"),
            str(record.get("domain_version") or "1.0.0"),
            int(record["port"]),
            str(record.get("purpose") or "candidate_preview"),
            str(record.get("backend_id") or ""),
            str(record.get("protocol") or ""),
            str(record.get("session") or ""),
        )
        client = self.router.client_for_leg(record_leg)
        sub_spec = dict(record["spec"])
        payload = {
            "task_id": str(record["subtask_id"]),
            "intent": sub_spec.get("intent"),
            "constraints": dict(sub_spec.get("constraints") or {}),
            "render": dict(sub_spec.get("render") or {}),
            "delivery": dict(sub_spec.get("delivery") or {}),
            "target_scene": (sub_spec.get("target") or {}).get("scene_mode", "current"),
            "inputs": list(sub_spec.get("inputs") or []),
            "step_params": {
                "patch": {"controls": dict(nuke_patch)},
            },
        }
        def checked_call(action: str) -> dict[str, Any]:
            raw = client.call(action, payload)
            policy = nuke_gate_policy(action)
            normalized = policy.normalize(action, raw)
            if any(not bool(item.get("passed")) for item in normalized):
                raise PipelineExecutionError(
                    ErrorCode.ARTIFACT_INVALID.value,
                    f"Nuke gate policy failed for {action}",
                    {"action": action, "gates": normalized},
                )
            return {**dict(raw), "gates": normalized}

        try:
            checked_call("agent.nuke.composite.audit_lineage")
        except Exception:
            script = next(
                (
                    str(item.get("path"))
                    for item in (record.get("result") or {}).get("artifacts") or []
                    if str(item.get("path") or "").endswith(".nk")
                ),
                "",
            )
            if not script:
                raise
            client.call("open_script", {"path": script})
            checked_call("agent.nuke.composite.audit_lineage")
        applied = checked_call("agent.nuke.composite.apply_patch")
        frame = int(((sub_spec.get("render") or {}).get("frame_range") or {}).get("start", 1))
        payload["step_params"] = {"frame": frame, "kind": "preview"}
        payload["step_params"]["variant_id"] = candidate.candidate_id
        rendered = checked_call("agent.nuke.composite.render_preview")
        verified = checked_call("agent.nuke.composite.verify_preview")
        leg = RouteLeg(
            "nuke",
            str(record.get("domain_pack") or "nuke_composite_v1"),
            str(record.get("domain_version") or "1.0.0"),
            int(record["port"]),
            "candidate_preview",
            record_leg.backend_id,
            record_leg.protocol,
            record_leg.session,
        )
        artifact_records = self._record_artifacts(
            task_id,
            leg,
            {"artifacts": list(verified.get("artifacts") or [])},
            kind="candidate_preview",
            final_delivery=False,
            extra_metadata={"candidate_id": candidate.candidate_id},
        )
        result = {"applied": applied, "rendered": rendered, "verified": verified, "artifact_records": artifact_records}
        self.store.put_record(task_id, "nuke_candidate_preview", candidate.candidate_id, result)
        return result

    @staticmethod
    def _houdini_candidate_contract(domain: DomainPackRef, candidate: CandidatePatch) -> tuple[dict[str, Any], bool]:
        try:
            pack = get_houdini_domain_pack(domain.identifier)
        except ValueError:
            return {}, False
        allowed = {item.identifier for item in pack.controls if item.application == "houdini"}
        patch = {item.control: item.proposed for item in candidate.changes if item.control in allowed}
        simulation_stages = {"source_layout_control", "generation_simulation"}
        requires_cache = bool(pack.simulation_cache) and any(
            item.identifier in patch and item.invalidates_from in simulation_stages
            for item in pack.controls
        )
        return patch, requires_cache

    def _executable_candidate(self, candidate: CandidatePatch, domain: DomainPackRef, spec: TaskSpecV2) -> Optional[CandidatePatch]:
        try:
            houdini_pack = get_houdini_domain_pack(domain.identifier)
            houdini_controls = {item.identifier for item in houdini_pack.controls if item.application == "houdini"}
            simulation_controls = {
                item.identifier for item in houdini_pack.controls
                if item.application == "houdini"
                and item.invalidates_from in {"source_layout_control", "generation_simulation"}
            } if houdini_pack.simulation_cache else set()
        except ValueError:
            houdini_controls = set()
            simulation_controls = set()
        nuke_controls = {"blur_size", "defocus", "defocus_size", "denoise_mix", "sharpen_size", "sharpen_amount", "glow_mix", "glow_size", "glow_amount", "emission_contrast", "comp_contrast", "edge_size", "grain_mix", "premult", "color_fusion_mix"}
        nuke_available_for_task = self._input_by_role(spec, "effect_render") is not None
        changes = tuple(
            item
            for item in candidate.changes
            if item.control in houdini_controls or (nuke_available_for_task and item.control in nuke_controls)
        )
        if not changes or len(changes) != len(candidate.changes):
            # A partial patch no longer represents the recorded hypothesis.
            return None
        has_simulation_change = any(item.control in simulation_controls for item in changes)
        return CandidatePatch(
            candidate_id=candidate.candidate_id,
            issue_id=candidate.issue_id,
            hypothesis_id=candidate.hypothesis_id,
            cause_family=candidate.cause_family,
            changes=changes,
            affected_stage_nodes=candidate.affected_stage_nodes,
            invalidates_components=candidate.invalidates_components if has_simulation_change else (),
            fixed_seed=candidate.fixed_seed,
            estimated_cost=candidate.estimated_cost,
            risk=candidate.risk,
            preview_artifact_ids=candidate.preview_artifact_ids,
        )

    @classmethod
    def _nuke_reference_input(cls, reference: Any, role: str) -> dict[str, Any]:
        item: dict[str, Any] = {
            "role": role,
            "path": reference.uri,
            "sha256": reference.sha256,
            "asset_id": reference.asset_id,
        }
        if reference.kind.value != "sequence":
            return item

        raw_frames = reference.metadata.get("frames")
        if not isinstance(raw_frames, (list, tuple)) or not raw_frames:
            raise PipelineExecutionError(
                ErrorCode.INVALID_SPEC.value,
                "sequence reference requires frozen metadata.frames before Nuke routing",
                {"asset_id": reference.asset_id},
            )
        pattern = os.path.expandvars(str(reference.uri or ""))
        token = re.search(r"%(?:0?[1-9][0-9]*)?d|#+", pattern)
        normalized_frames: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_frames):
            if not isinstance(raw, Mapping):
                raise PipelineExecutionError(
                    ErrorCode.INVALID_SPEC.value,
                    "sequence reference frame records must be objects",
                    {"asset_id": reference.asset_id, "index": index},
                )
            frame_uri = str(raw.get("path") or raw.get("uri") or "")
            frame_value = raw.get("frame")
            if frame_value is None and token is not None:
                prefix = os.path.expandvars(pattern[: token.start()])
                suffix = os.path.expandvars(pattern[token.end() :])
                matched = re.fullmatch(
                    re.escape(prefix) + r"(-?[0-9]+)" + re.escape(suffix),
                    os.path.expandvars(frame_uri),
                )
                if matched is not None:
                    frame_value = int(matched.group(1))
            if frame_value is None:
                frame_value = raw.get("index", index)
            frozen = cls._frozen_uri(
                frame_uri,
                str(raw.get("sha256") or ""),
                f"reference {reference.asset_id} frame {index}",
            )
            normalized_frames.append(
                {
                    "index": index,
                    "frame": int(frame_value),
                    "uri": frozen["uri"],
                    "path": frozen["uri"],
                    "sha256": frozen["sha256"],
                    "bytes": frozen["bytes"],
                }
            )
        # A reference manifest does not carry frame numbers, while Nuke inputs
        # do.  Bind the derived input to its own canonical ordered manifest and
        # retain the original reference identity separately for provenance.
        nuke_manifest = [
            {
                "index": frame["index"],
                "frame": frame["frame"],
                "uri": frame["uri"],
                "sha256": frame["sha256"],
                "bytes": frame["bytes"],
            }
            for frame in normalized_frames
        ]
        item.update(
            {
                "sha256": canonical_sha256(nuke_manifest),
                "source_reference_sha256": reference.sha256,
                "frames": normalized_frames,
            }
        )
        return item

    @staticmethod
    def _validated_visual_source_plan(spec: TaskSpecV2) -> Optional[dict[str, Any]]:
        raw_plan = spec.metadata.get("source_plan")
        if raw_plan is None:
            return None
        raw_objective = spec.metadata.get("visual_objective")
        if not isinstance(raw_plan, Mapping) or not isinstance(raw_objective, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "visual source plan requires its typed visual objective")
        from dcc_task_runtime.visual_objective import SourcePlan, VisualObjective

        objective = VisualObjective.from_mapping(raw_objective)
        supplied = SourcePlan.from_mapping(raw_plan)
        expected = objective.source_plan()
        if supplied.to_dict() != expected.to_dict():
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "visual source plan no longer matches the registered observations")
        supplied.require_ready()
        controls = {item.name: item.value for item in supplied.controls + supplied.defaults}
        return {
            "visual_objective": objective.to_dict(),
            "source_plan": supplied.to_dict(),
            "source_controls": controls,
            "source_plan_sha256": canonical_sha256(supplied.to_dict()),
        }

    def _subtask_spec(
        self,
        spec: TaskSpecV2,
        leg: RouteLeg,
        effect_input: Optional[Mapping[str, Any]],
        run_mode: str = "delivery",
    ) -> dict[str, Any]:
        run_mode = str(run_mode).strip().lower()
        if run_mode not in {"diagnose", "candidate_preview", "delivery"}:
            raise PipelineExecutionError(
                ErrorCode.INVALID_SPEC.value,
                "subtask run_mode must be diagnose, candidate_preview, or delivery",
                {"run_mode": run_mode},
            )
        binding = spec.scene_for(leg.application)
        if binding.instance_identity and binding.instance_identity != leg.session:
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value, "selected DCC instance differs from scene binding")
        inputs = [dict(item) for item in spec.inputs]
        roles = {str(item.get("role") or "") for item in inputs}
        for reference in spec.references:
            role = {
                "plate": "plate",
                "depth": "depth",
                "mask": "matte",
            }.get(reference.kind.value, "reference")
            if role not in roles:
                if leg.application == "nuke":
                    inputs.append(self._nuke_reference_input(reference, role))
                else:
                    inputs.append(
                        {
                            "role": role,
                            "path": reference.uri,
                            "sha256": reference.sha256,
                            "asset_id": reference.asset_id,
                        }
                    )
                roles.add(role)
        render = dict(spec.render)
        if leg.application == "houdini":
            constraints = dict(spec.constraints)
            visual_source = self._validated_visual_source_plan(spec)
            if spec.schema_version == "2.1":
                constraints["bridge_scene_binding"] = binding.to_dict()
            constraints.pop("frozen_scene_sha256", None)
            if binding.scene_path:
                constraints["frozen_scene_sha256"] = str(
                    binding.frozen_scene_sha256 or ""
                )
            constraints["fx"] = {
                **dict(constraints.get("fx") or {}),
                "domain_pack": leg.domain_pack,
                "seed": int(spec.metadata.get("seed", 1)),
                "reference_analysis": dict(spec.metadata.get("reference_analysis") or {}),
                "protected_attributes": list(spec.constraints.get("protected_attributes") or []),
                "run_mode": run_mode,
                **(visual_source or {}),
            }
            return {
                "schema_version": "1.0",
                "task_type": "houdini.reference_effect",
                "intent": spec.intent,
                "target": {
                    "application": "houdini",
                    "scene_mode": binding.scene_mode,
                    "scene_path": binding.scene_path,
                },
                "inputs": inputs,
                "constraints": constraints,
                "render": render,
                "delivery": dict(spec.delivery),
            }
        allowed = {"effect_render", "plate", "reference", "matte", "depth", "vector"}
        nuke_inputs = [item for item in inputs if str(item.get("role") or "") in allowed]
        if effect_input is not None and not any(item.get("role") == "effect_render" for item in nuke_inputs):
            nuke_inputs.insert(0, dict(effect_input))
        output_dir = str(render.get("output_dir") or "").strip()
        if output_dir:
            render["output_dir"] = str(Path(output_dir) / "nuke")
        nuke_constraints = dict(spec.constraints)
        if spec.schema_version == "2.1":
            nuke_constraints["bridge_scene_binding"] = binding.to_dict()
        nuke_constraints.pop("frozen_scene_sha256", None)
        nuke_constraints["run_mode"] = run_mode
        if binding.scene_path:
            nuke_constraints["frozen_scene_sha256"] = str(
                binding.frozen_scene_sha256 or ""
            )
        return {
            "schema_version": "1.0",
            "task_type": "nuke.reference_composite",
            "intent": spec.intent,
            "target": {
                "application": "nuke",
                "scene_mode": binding.scene_mode,
                "scene_path": binding.scene_path,
            },
            "inputs": nuke_inputs,
            "constraints": nuke_constraints,
            "render": render,
            "delivery": dict(spec.delivery),
        }

    @staticmethod
    def _input_by_role(spec: TaskSpecV2, role: str) -> Optional[Mapping[str, Any]]:
        return next((item for item in spec.inputs if str(item.get("role") or "") == role), None)

    def _domain_for_feedback(self, spec: TaskSpecV2, feedback: str, identifier: Optional[str]):
        if identifier:
            version = next((item.version for item in spec.domains if item.identifier == identifier), None)
            return self.planner.registry.get(identifier, version)
        domains = self.planner.domains_for(
            replace(spec, feedback=feedback)
        )
        if len(domains) != 1:
            raise PipelineExecutionError(
                ErrorCode.INVALID_SPEC.value,
                "feedback matches multiple domains; pass an explicit domain identifier",
                {"matches": [item.identifier for item in domains]},
            )
        return domains[0]

    def _move_to_diagnosing(self, task_id: str) -> None:
        state = TaskState(self.store.status(task_id)["state"])
        if state == TaskState.DIAGNOSING:
            return
        if state == TaskState.CANDIDATES_READY:
            self.store.transition(task_id, TaskState.PREVIEWING, "new feedback invalidates the previous candidate view")
            state = TaskState.PREVIEWING
        if state in {TaskState.AWAITING_INPUT, TaskState.DIAGNOSIS_INCONCLUSIVE, TaskState.PREVIEWING}:
            self.store.transition(task_id, TaskState.DIAGNOSING, "diagnosing explicit feedback with fixed evidence")
            return
        raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, f"feedback diagnosis is unavailable in state {state.value}")

    @staticmethod
    def _frame_tuple(value: Any) -> tuple[int, int, int]:
        if isinstance(value, Mapping):
            start = int(value.get("start", 1))
            end = int(value.get("end", start))
            step = int(value.get("step", 1))
        else:
            start, end, step = (int(item) for item in value)
        if start > end or step <= 0:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "fixed frame range is invalid")
        return start, end, step

    @staticmethod
    def _roi_tuple(value: Any) -> Optional[tuple[float, float, float, float]]:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "roi must contain four normalized numbers")
        return tuple(float(item) for item in value)  # type: ignore[return-value]

    @staticmethod
    def _evidence_record(value: Mapping[str, Any]) -> EvidenceRecord:
        return EvidenceRecord(
            stage_node_id=str(value.get("stage_node_id") or ""),
            signal=str(value.get("signal") or ""),
            verdict=EvidenceVerdict(str(value.get("verdict") or "unknown")),
            value=value.get("value"),
            observation=str(value.get("observation") or ""),
            artifact_id=str(value.get("artifact_id")) if value.get("artifact_id") else None,
        )

    def _current_selection(self, task_id: str) -> dict[str, Any]:
        rows = self.store.records(task_id, "selection")
        if not rows:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "no candidate has been selected")
        return dict(rows[-1])

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _frozen_uri(cls, uri: str, expected_sha256: str, label: str) -> dict[str, Any]:
        expected = str(expected_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise PipelineExecutionError(
                ErrorCode.INVALID_SPEC.value,
                f"{label} requires a lowercase 64-character SHA-256",
            )
        rendered = str(uri or "").strip()
        if rendered.startswith("data:"):
            try:
                header, encoded = rendered.split(",", 1)
                data = base64.b64decode(encoded, validate=True) if ";base64" in header else unquote_to_bytes(encoded)
            except (ValueError, binascii.Error) as exc:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, f"{label} data URI is invalid") from exc
            actual = hashlib.sha256(data).hexdigest()
            size = len(data)
            frozen_uri = "data:" + header.split(":", 1)[-1].split(";", 1)[0]
        elif rendered.startswith(("http://", "https://")):
            raise PipelineExecutionError(
                ErrorCode.UNSUPPORTED_INPUT_DECODER.value,
                f"{label} is remote; download it to a local immutable file before task.start",
            )
        else:
            parsed = urlparse(rendered)
            candidate = Path(unquote(parsed.path) if parsed.scheme == "file" else rendered).expanduser()
            if candidate.is_symlink():
                raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, f"{label} is a symlink", {"path": str(candidate)})
            path = candidate.resolve()
            if not path.is_file():
                raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, f"{label} is missing or is a symlink", {"path": str(path)})
            actual = cls._hash_file(path)
            size = path.stat().st_size
            frozen_uri = str(path)
        if not hmac.compare_digest(actual, expected):
            raise PipelineExecutionError(
                ErrorCode.ARTIFACT_INVALID.value,
                f"{label} bytes do not match the declared SHA-256",
                {"expected": expected, "actual": actual},
            )
        return {"uri": frozen_uri, "sha256": actual, "bytes": size}

    @classmethod
    def _freeze_task_sources(cls, spec: TaskSpecV2) -> dict[str, Any]:
        references: list[dict[str, Any]] = []
        for reference in spec.references:
            if reference.kind.value == "sequence":
                raw_frames = reference.metadata.get("frames")
                if not isinstance(raw_frames, (list, tuple)) or len(raw_frames) < 2:
                    raise PipelineExecutionError(
                        ErrorCode.INVALID_SPEC.value,
                        "sequence references require metadata.frames with at least two frozen frame records",
                        {"asset_id": reference.asset_id},
                    )
                frames = []
                for index, raw in enumerate(raw_frames):
                    if not isinstance(raw, Mapping):
                        raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "each sequence frame must be an object")
                    frozen = cls._frozen_uri(str(raw.get("uri") or ""), str(raw.get("sha256") or ""), f"reference {reference.asset_id} frame {index}")
                    frames.append({"index": index, **frozen})
                manifest_hash = canonical_sha256(frames)
                if not hmac.compare_digest(manifest_hash, reference.sha256.lower()):
                    raise PipelineExecutionError(
                        ErrorCode.ARTIFACT_INVALID.value,
                        "sequence reference SHA-256 must equal the canonical ordered frame-manifest hash",
                        {"asset_id": reference.asset_id, "actual_manifest_hash": manifest_hash},
                    )
                references.append({"asset_id": reference.asset_id, "kind": reference.kind.value, "sha256": manifest_hash, "frames": frames})
            else:
                references.append(
                    {
                        "asset_id": reference.asset_id,
                        "kind": reference.kind.value,
                        **cls._frozen_uri(reference.uri, reference.sha256, f"reference {reference.asset_id}"),
                    }
                )
        inputs: list[dict[str, Any]] = []
        for index, item in enumerate(spec.inputs):
            uri = str(item.get("path") or item.get("uri") or "")
            label = f"input {index} ({item.get('role') or 'untyped'})"
            raw_frames = item.get("frames")
            if raw_frames is not None:
                if not isinstance(raw_frames, (list, tuple)) or not raw_frames:
                    raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, f"{label}.frames must be a non-empty list")
                frames = []
                for frame_index, raw in enumerate(raw_frames):
                    if not isinstance(raw, Mapping):
                        raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, f"{label} frame records must be objects")
                    frozen = cls._frozen_uri(
                        str(raw.get("path") or raw.get("uri") or ""),
                        str(raw.get("sha256") or ""),
                        f"{label} frame {frame_index}",
                    )
                    frames.append({"index": frame_index, "frame": int(raw.get("frame", frame_index)), **frozen})
                manifest_hash = canonical_sha256(frames)
                declared = str(item.get("sha256") or "").strip().lower()
                if not hmac.compare_digest(manifest_hash, declared):
                    raise PipelineExecutionError(
                        ErrorCode.ARTIFACT_INVALID.value,
                        f"{label} SHA-256 must equal the canonical ordered frame-manifest hash",
                        {"actual_manifest_hash": manifest_hash},
                    )
                inputs.append({"index": index, "role": str(item.get("role") or ""), "uri": uri, "sha256": manifest_hash, "frames": frames})
            else:
                if any(token in uri for token in ("$F", "%0", "####")):
                    raise PipelineExecutionError(
                        ErrorCode.INVALID_SPEC.value,
                        f"{label} is a sequence pattern and requires an explicit frozen frames manifest",
                    )
                inputs.append({"index": index, "role": str(item.get("role") or ""), **cls._frozen_uri(uri, str(item.get("sha256") or ""), label)})
        scene = None
        if spec.target_scene_path:
            scene_hash = str(spec.constraints.get("frozen_scene_sha256") or spec.metadata.get("scene_sha256") or "")
            scene = cls._frozen_uri(spec.target_scene_path, scene_hash, "target.scene_path")
        manifest = {
            "schema": "bridge-skills.source-manifest/1.0",
            "references": references,
            "inputs": inputs,
            "scene": scene,
            "seed": int(spec.metadata.get("seed", 1)),
            "camera_hash": str(spec.metadata.get("camera_hash") or "unverified_camera"),
            "frame_range": dict(spec.render.get("frame_range") or {}),
            "fps": float(spec.render.get("fps", 24.0)),
            "color_space": str(spec.render.get("color_space") or "ACEScg"),
        }
        if spec.schema_version == "2.1":
            manifest["schema"] = "bridge-skills.source-manifest/2.1"
            manifest["scenes"] = {
                application: cls._frozen_uri(binding.scene_path, binding.frozen_scene_sha256 or "", "target.scenes." + application)
                for application in ("houdini", "nuke")
                for binding in (spec.scene_for(application),)
                if binding.scene_path
            }
        manifest["manifest_hash"] = canonical_sha256(manifest)
        return manifest

    def _assert_frozen_sources(self, task_id: str) -> dict[str, Any]:
        stored = self.store.records(task_id, "source_manifest")
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        current = self._freeze_task_sources(spec)
        if not stored:
            self.store.put_record(task_id, "source_manifest", "frozen", current)
            return current
        if not hmac.compare_digest(str(stored[-1].get("manifest_hash") or ""), current["manifest_hash"]):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "frozen source manifest changed after task.start")
        return current

    def _verified_artifact(self, task_id: str, artifact_id: str, allow_reference: bool) -> dict[str, Any]:
        if not artifact_id:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "artifact id is required")
        artifact = next((item for item in self.store.artifacts(task_id) if item.get("artifact_id") == artifact_id), None)
        if artifact is None:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "artifact id does not belong to this task", {"artifact_id": artifact_id})
        if artifact.get("reference_asset") and not allow_reference:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "reference assets cannot stand in for generated verification results")
        path = Path(str(artifact.get("uri") or ""))
        if not path.is_file() or path.is_symlink():
            raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "verification artifact is missing or is a symlink", {"artifact_id": artifact_id})
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(digest, str(artifact.get("sha256") or "")):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "verification artifact hash changed after registration", {"artifact_id": artifact_id})
        return dict(artifact)

    @staticmethod
    def _cache_frame_path(pattern: str, frame: int) -> Path:
        rendered = os.path.expandvars(str(pattern)).replace("$F4", f"{frame:04d}")
        if "%04d" in rendered:
            rendered = rendered.replace("%04d", f"{frame:04d}")
        if "####" in rendered:
            rendered = rendered.replace("####", f"{frame:04d}")
        candidate = Path(rendered).expanduser()
        if candidate.is_symlink():
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "cache output path may not be a symlink", {"path": str(candidate)})
        return candidate.resolve(strict=False)

    def _record_cache_artifacts(
        self,
        task_id: str,
        subject: CacheApprovalSubject,
        grant_id: str,
        result: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Re-derive and hash every exact cache output from the approved subject."""

        start, end, stride = subject.frame_range
        expected = [self._cache_frame_path(subject.output_path, frame) for frame in range(start, end + 1, stride)]
        raw_artifacts = list(result.get("artifacts") or [])
        returned: list[Path] = []
        for raw in raw_artifacts:
            if not isinstance(raw, Mapping) or not str(raw.get("path") or "").strip():
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "Houdini cache returned a malformed artifact record")
            returned.append(Path(str(raw["path"])).expanduser().resolve(strict=False))
        if returned != expected:
            raise PipelineExecutionError(
                ErrorCode.ARTIFACT_INVALID.value,
                "Houdini cache artifacts do not exactly match the approved output path and frame range",
                {"expected": [str(item) for item in expected], "returned": [str(item) for item in returned]},
            )
        records = []
        for frame, path in zip(range(start, end + 1, stride), expected):
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                raise PipelineExecutionError(
                    ErrorCode.ARTIFACT_MISSING.value,
                    "approved Houdini cache artifact is missing, empty, or a symlink",
                    {"path": str(path), "frame": frame},
                )
            digest = self._hash_file(path)
            record = ArtifactRecord(
                artifact_id=new_identifier("artifact"),
                task_id=task_id,
                kind="houdini_simulation_cache",
                uri=str(path),
                sha256=digest,
                domain=subject.domain,
                component_id=subject.component_id,
                stage_node_id="simulation",
                reference_asset=False,
                final_delivery=False,
                metadata={
                    "frame": frame,
                    "grant_id": grant_id,
                    "approval_subject_hash": subject.subject_hash,
                    "bytes": path.stat().st_size,
                },
            )
            self.store.add_artifact(record)
            records.append(record.to_dict())
        return records

    def _metric_values(self, artifact: Mapping[str, Any], kind: str) -> tuple[Any, str]:
        path = Path(str(artifact["uri"]))
        if path.stat().st_size > 64 * 1024 * 1024:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "metric artifact exceeds the 64 MiB deterministic decoder limit")
        if kind == "raster" and path.suffix.lower() in ImageMagickRasterDecoder.SUFFIXES:
            values, metadata = self.raster_decoder.decode(path)
            return values, str(metadata.get("decoder") or "visual_raster_decoder")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PipelineExecutionError(
                ErrorCode.UNSUPPORTED_INPUT_DECODER.value,
                "technical verification currently requires a JSON diagnostic artifact",
                {"artifact_id": artifact["artifact_id"], "metric_kind": kind},
            ) from exc
        key = {"raster": "raster", "sequence": "frames", "field": "field", "points": "points", "geometry": "geometry"}.get(kind)
        if key is None or not isinstance(value, Mapping) or key not in value:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "metric artifact does not contain the selected metric kind", {"metric_kind": kind})
        return value[key], f"artifact_json_{kind}"

    def _metric_summary(self, kind: str, values: Any, provenance: MetricProvenance) -> dict[str, float]:
        if kind == "raster":
            results = self.metrics.raster_summary(values, provenance)
        elif kind == "sequence":
            results = self.metrics.sequence_summary(values, provenance)
        elif kind == "field":
            results = self.metrics.scalar_field_summary(values, provenance)
        elif kind == "points":
            results = self.metrics.point_summary(values, provenance)
        elif kind == "geometry":
            if not isinstance(values, Mapping):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "geometry metric payload must be an object")
            results = self.metrics.geometry_summary(values.get("vertices") or [], values.get("faces") or [], provenance)
        else:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "metric_kind is unsupported", {"metric_kind": kind})
        return {item.name: item.value for item in results}

    @staticmethod
    def _default_target_metric(dimension: IssueDimension, kind: str) -> str:
        choices = {
            (IssueDimension.SPATIAL_DETAIL, "raster"): "raster.edge_energy",
            (IssueDimension.COMPOSITE, "raster"): "raster.edge_energy",
            (IssueDimension.DISTRIBUTION, "raster"): "raster.variance",
            (IssueDimension.ENERGY, "raster"): "raster.mean",
            (IssueDimension.MOTION, "sequence"): "sequence.temporal_delta",
            (IssueDimension.TIMING, "sequence"): "sequence.temporal_delta",
            (IssueDimension.DISTRIBUTION, "points"): "points.nearest_neighbor_variance",
            (IssueDimension.SCALE, "geometry"): "geometry.bounds_diagonal",
        }
        result = choices.get((dimension, kind))
        if result is None:
            raise PipelineExecutionError(
                ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                "no deterministic target metric is defined for this issue and artifact kind",
                {"dimension": dimension.value, "metric_kind": kind},
            )
        return result

    @staticmethod
    def _protected_metric_regressions(
        issue: PerceptualIssue,
        before: Mapping[str, float],
        after: Mapping[str, float],
        raw_limits: Any,
    ) -> tuple[str, ...]:
        if not issue.protected_attributes:
            return ()
        if not isinstance(raw_limits, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "protected_metric_limits must be an object")
        regressions = []
        for attribute in issue.protected_attributes:
            rule = raw_limits.get(attribute)
            if not isinstance(rule, Mapping):
                raise PipelineExecutionError(
                    ErrorCode.DIAGNOSIS_INCONCLUSIVE.value,
                    "every protected attribute requires a deterministic metric limit",
                    {"protected_attribute": attribute},
                )
            metric = str(rule.get("metric") or "")
            limit = float(rule.get("maximum_relative_change", -1.0))
            if metric not in before or metric not in after or limit < 0:
                raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "protected metric limit is invalid", {"protected_attribute": attribute})
            denominator = max(abs(before[metric]), 1e-12)
            relative = abs(after[metric] - before[metric]) / denominator
            if relative > limit:
                regressions.append(attribute)
        return tuple(regressions)

    @staticmethod
    def _candidate(value: Mapping[str, Any]) -> CandidatePatch:
        return CandidatePatch(
            candidate_id=str(value["candidate_id"]),
            issue_id=str(value["issue_id"]),
            hypothesis_id=str(value["hypothesis_id"]),
            cause_family=str(value["cause_family"]),
            changes=tuple(
                ParameterChange(str(item["control"]), item.get("previous"), item.get("proposed"))
                for item in value.get("changes") or []
            ),
            affected_stage_nodes=tuple(str(item) for item in value.get("affected_stage_nodes") or []),
            invalidates_components=tuple(str(item) for item in value.get("invalidates_components") or []),
            fixed_seed=int(value.get("fixed_seed", 1)),
            estimated_cost=str(value.get("estimated_cost") or "unknown"),
            risk=str(value.get("risk") or "unknown"),
            preview_artifact_ids=tuple(str(item) for item in value.get("preview_artifact_ids") or []),
        )

    @staticmethod
    def _issue(value: Mapping[str, Any]) -> PerceptualIssue:
        raw_range = value.get("frame_range")
        return PerceptualIssue(
            issue_id=str(value["issue_id"]),
            raw_feedback=str(value["raw_feedback"]),
            domain=DomainPackRef.from_mapping(value["domain"]),
            component_id=str(value["component_id"]),
            dimension=IssueDimension(str(value["dimension"])),
            direction=ChangeDirection(str(value["direction"])),
            severity=float(value["severity"]),
            confidence=float(value["confidence"]),
            roi=tuple(float(item) for item in value["roi"]) if value.get("roi") is not None else None,
            frame_range=tuple(int(item) for item in raw_range) if raw_range is not None else None,
            protected_attributes=tuple(str(item) for item in value.get("protected_attributes") or []),
        )

    @staticmethod
    def _hypothesis(value: Mapping[str, Any]) -> CauseHypothesis:
        return CauseHypothesis(
            hypothesis_id=str(value["hypothesis_id"]),
            issue_id=str(value["issue_id"]),
            cause_family=str(value["cause_family"]),
            stage_node_id=str(value["stage_node_id"]),
            explanation=str(value["explanation"]),
            evidence_signals=tuple(str(item) for item in value.get("evidence_signals") or []),
            confounders=tuple(str(item) for item in value.get("confounders") or []),
            confidence=float(value["confidence"]),
            estimated_cost=str(value.get("estimated_cost") or "unknown"),
        )

    @staticmethod
    def _cache_subject(value: Mapping[str, Any]) -> CacheApprovalSubject:
        raw_range = value.get("frame_range") or {}
        return CacheApprovalSubject(
            task_id=str(value["task_id"]),
            scene_hash=str(value["scene_hash"]),
            input_hashes=tuple(str(item) for item in value.get("input_hashes") or []),
            reference_hashes=tuple(str(item) for item in value.get("reference_hashes") or []),
            domain=DomainPackRef.from_mapping(value["domain"]),
            component_id=str(value["component_id"]),
            parameters=dict(value.get("parameters") or {}),
            seed=int(value.get("seed", 1)),
            frame_range=(int(raw_range["start"]), int(raw_range["end"]), int(raw_range["step"])),
            dcc_versions=dict(value.get("dcc_versions") or {}),
            output_path=str(value["output_path"]),
            dependencies=tuple(str(item) for item in value.get("dependencies") or []),
            metadata=dict(value.get("metadata") or {}),
        )

    def _assert_cache_resource_policy(self, task_id, subject):
        policies = self.store.records(task_id, "cache_resource_policy")
        if not policies or canonical_sha256(policies[-1]) != subject.metadata.get("resource_policy_hash"):
            raise PipelineExecutionError(ErrorCode.APPROVAL_SCOPE_MISMATCH.value, "trusted cache resource policy changed; request fresh confirmation")

    @classmethod
    def _experience(cls, value: Mapping[str, Any], expected_task_id: Optional[str] = None) -> RepairExperience:
        task_id = str(value.get("task_id") or expected_task_id or "")
        if expected_task_id and task_id != expected_task_id:
            raise PipelineExecutionError(ErrorCode.EXPERIENCE_SCOPE_MISMATCH.value, "experience belongs to a different task")
        candidate = cls._candidate(value["candidate"])
        score = value["scorecard"]
        return RepairExperience(
            experience_id=str(value.get("experience_id") or new_identifier("experience")),
            task_id=task_id,
            domain=DomainPackRef.from_mapping(value["domain"]),
            raw_feedback=str(value.get("raw_feedback") or (value.get("issue") or {}).get("raw_feedback") or ""),
            issue=cls._issue(value["issue"]),
            hypothesis=cls._hypothesis(value["hypothesis"]),
            candidate=candidate,
            scorecard=VisualScorecard(
                issue_id=str(score["issue_id"]),
                candidate_id=str(score["candidate_id"]),
                before={str(key): float(item) for key, item in dict(score.get("before") or {}).items()},
                after={str(key): float(item) for key, item in dict(score.get("after") or {}).items()},
                target_improved=bool(score.get("target_improved")),
                protected_regressions=tuple(str(item) for item in score.get("protected_regressions") or []),
                notes=tuple(str(item) for item in score.get("notes") or []),
            ),
            context=dict(value.get("context") or {}),
            verified_result_hash=str(value.get("verified_result_hash") or ""),
            user_confirmed=bool(value.get("user_confirmed")),
            created_at=str(value.get("created_at") or "") or RepairExperience.__dataclass_fields__["created_at"].default_factory(),
        )

    @staticmethod
    def _assert_nuke_reference_isolation(record: Mapping[str, Any]) -> None:
        gates = list((record.get("result") or {}).get("gates") or [])
        lineage = [item for item in gates if item.get("name") == "reference_isolated_from_final_write"]
        if not lineage or any(not bool(item.get("passed")) for item in lineage):
            raise PipelineExecutionError(
                ErrorCode.POLICY_DENIED.value,
                "Nuke result lacks a passing reference-to-final-Write lineage audit",
            )

    def _record_artifacts(
        self,
        task_id: str,
        leg: RouteLeg,
        result: Mapping[str, Any],
        *,
        kind: str = "dcc_subtask_artifact",
        final_delivery: Optional[bool] = None,
        extra_metadata: Optional[Mapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for raw in result.get("artifacts") or []:
            path = Path(str(raw.get("path") or ""))
            if path.is_symlink() or not path.is_file():
                raise PipelineExecutionError(
                    ErrorCode.ARTIFACT_MISSING.value,
                    "DCC returned an artifact that is missing or is a symlink",
                    {"path": str(path), "application": leg.application},
                )
            digest = self._hash_file(path)
            inferred_final = leg.application == "nuke" and (
                path.name.startswith("final.") or path.suffix.lower() == ".nk"
            )
            record = ArtifactRecord(
                    artifact_id=uuid4().hex,
                    task_id=task_id,
                    kind=kind,
                    uri=str(path),
                    sha256=digest,
                    domain=DomainPackRef(leg.domain_pack, leg.domain_version),
                    component_id=leg.domain_pack,
                    stage_node_id="composite" if leg.application == "nuke" else "generation",
                    reference_asset=False,
                    final_delivery=inferred_final if final_delivery is None else final_delivery,
                    metadata={"application": leg.application, "port": leg.port, **dict(extra_metadata or {})},
                )
            self.store.add_artifact(record)
            records.append(record.to_dict())
        return records

    @staticmethod
    def _effect_input_from_subtask(record: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        """Promote a real rendered Houdini artifact into the following Nuke leg."""

        raw_artifacts = list((record.get("result") or {}).get("artifacts") or [])
        paths = [
            Path(str(item.get("path") or ""))
            for item in raw_artifacts
            if isinstance(item, Mapping) and Path(str(item.get("path") or "")).suffix.lower() in {".exr", ".dpx", ".png", ".tif", ".tiff"}
        ]
        paths = [path for path in paths if path.is_file() and not path.is_symlink()]
        if not paths:
            return None
        paths.sort()
        selected = str(paths[0])
        sequence_frames: list[dict[str, Any]] = []
        if len(paths) > 1:
            matches = [re.search(r"(\d{4})(?=\.[^.]+$)", str(path)) for path in paths]
            match = matches[0]
            if match and all(item is not None for item in matches):
                candidate = selected[: match.start()] + "%04d" + selected[match.end() :]
                expanded = {
                    Path(candidate.replace("%04d", item.group(1)))
                    for item in matches
                    if item is not None
                }
                if expanded == set(paths):
                    selected = candidate
                    sequence_frames = [
                        {
                            "index": index,
                            "frame": int(item.group(1)),
                            "uri": str(path.resolve()),
                            "path": str(path.resolve()),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "bytes": path.stat().st_size,
                        }
                        for index, (path, item) in enumerate(zip(paths, matches))
                        if item is not None
                    ]
        result = {
            "role": "effect_render",
            "path": selected,
            "source": "generated_houdini_artifact",
            "artifact_sha256": hashlib.sha256(paths[0].read_bytes()).hexdigest(),
        }
        if sequence_frames:
            manifest = [
                {
                    "index": item["index"],
                    "frame": item["frame"],
                    "uri": item["uri"],
                    "sha256": item["sha256"],
                    "bytes": item["bytes"],
                }
                for item in sequence_frames
            ]
            result.update({"sha256": canonical_sha256(manifest), "frames": sequence_frames})
        else:
            result["sha256"] = result["artifact_sha256"]
        return result

    def _summary(self, task_id: str) -> dict[str, Any]:
        status = self.store.status(task_id)
        return {
            "task_id": task_id,
            "state": status["state"],
            "status": status,
            "subtasks": list(self.store.records(task_id, "subtask")),
            "issues": list(self.store.records(task_id, "issue")),
            "hypotheses": list(self.store.records(task_id, "hypothesis")),
            "candidates": list(self.store.records(task_id, "candidate")),
            "selection": list(self.store.records(task_id, "selection")),
            "artifacts": list(self.store.artifacts(task_id)),
        }

    @staticmethod
    def _allowed_targets(state: TaskState) -> frozenset[TaskState]:
        from dcc_task_runtime.pipeline_store import V2_STATE_TRANSITIONS

        return V2_STATE_TRANSITIONS.get(state, frozenset())


class _ExplicitHumanVerification:
    def verify(self, principal_id, proof, scope, request_id) -> bool:
        return TrustedApprovalControl.verify_proof(
            str(principal_id),
            str(proof),
            scope.value,
            str(request_id),
        )


class TrustedExecutionControl:
    """Controller-only evidence registration for experimental execution.

    This control is deliberately separate from :class:`ModelSafePipeline` and
    is not a model tool.  Receipt fields are compared with controller-computed
    source/config/output digests; caller-provided ``verified`` or authorization
    booleans are not accepted.
    """

    def __init__(
        self,
        pipeline: ModelSafePipeline,
        *,
        provider_witness_verifier: Optional[Callable[[Mapping[str, Any]], bool]] = None,
    ) -> None:
        self.pipeline = pipeline
        self.store = pipeline.store
        self.provider_witness_verifier = provider_witness_verifier

    @staticmethod
    def _receipt_digest(value: Any, name: str) -> str:
        rendered = str(value or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", rendered):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, f"{name} must be a SHA-256 digest")
        return rendered

    def reference_analysis_receipt_contract(
        self,
        task_id: str,
        *,
        run_id: str,
        session_id: str,
        analysis: Mapping[str, Any],
        config: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Compute the hashes a trusted front-door collector must bind."""
        from dcc_task_runtime.visual_objective import validate_reference_analysis

        self.store.get_task(task_id)
        source = self.pipeline._assert_frozen_sources(task_id)
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        if not spec.references:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "reference analysis requires registered media")
        validated = validate_reference_analysis(analysis).to_dict()
        config_payload = dict(config or {})
        config_sha256 = canonical_sha256(config_payload)
        input_payload = {
            "task_id": task_id,
            "run_id": str(run_id),
            "session_id": str(session_id),
            "route_id": "WorkBuddyDesktopRoute",
            "selected_model": "HY3",
            "source_manifest_hash": source["manifest_hash"],
            "reference_hashes": [item.sha256 for item in spec.references],
            "config_sha256": config_sha256,
        }
        return {
            "input_sha256": canonical_sha256(input_payload),
            "output_sha256": canonical_sha256(validated),
            "config_sha256": config_sha256,
            "source_manifest_hash": source["manifest_hash"],
            "reference_hashes": [item.sha256 for item in spec.references],
            "analysis": validated,
        }

    @staticmethod
    def _stable_execution_id(value: Any, name: str) -> str:
        rendered = str(value or "").strip()
        if not rendered or len(rendered) > 200 or any(ord(ch) < 0x20 for ch in rendered):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, f"{name} must be a stable identifier")
        return rendered

    def register_connector_observation(
        self,
        task_id: str,
        *,
        run_id: str,
        session_id: str,
        asset_id: str,
        observation: Mapping[str, Any],
        connector_receipt: Mapping[str, Any],
        input_class: str = "synthetic",
    ) -> dict[str, Any]:
        """Mirror one normal connector observation into the trusted ledger.

        The connector may provide observation text, but it cannot provide file
        paths, source digests, verification booleans or authorization.  Those
        are recomputed from the already frozen task and the connector's durable
        receipt.  This record alone is *not* model-execution proof.
        """
        if str(input_class) != "synthetic":
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "this collector accepts synthetic inputs only")
        run_id = self._stable_execution_id(run_id, "run_id")
        session_id = self._stable_execution_id(session_id, "session_id")
        asset_id = self._stable_execution_id(asset_id, "asset_id")
        if not isinstance(observation, Mapping) or not observation:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "connector observation must be a non-empty object")
        if not isinstance(connector_receipt, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "connector_receipt must be an object")
        source = self.pipeline._assert_frozen_sources(task_id)
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        references = {item.asset_id: item for item in spec.references}
        reference = references.get(asset_id)
        if reference is None:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "connector observation references an unregistered asset")
        if connector_receipt.get("run_id") != run_id or connector_receipt.get("asset_id") != asset_id:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector receipt run/asset binding changed")
        request_id = self._stable_execution_id(connector_receipt.get("request_id"), "connector request_id")
        receipt_event = connector_receipt.get("receipt")
        if not isinstance(receipt_event, Mapping):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector event receipt is missing")
        seq = receipt_event.get("seq")
        event_hash = self._receipt_digest(receipt_event.get("event_hash"), "connector receipt event_hash")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector receipt sequence is invalid")
        if connector_receipt.get("observation_recorded") is not True or connector_receipt.get("dcc_dispatched") is not False:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector receipt does not describe a diagnostic observation")
        observation_payload = dict(observation)
        observation_hash = canonical_sha256({"asset_id": asset_id, "observation": observation_payload})
        record_id = "connectorobs_" + canonical_sha256(
            {"task_id": task_id, "run_id": run_id, "session_id": session_id, "request_id": request_id}
        )
        body = {
            "schema": "bridge.connector-observation-capture/1.0",
            "record_id": record_id,
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "route_id": "WorkBuddyDesktopRoute",
            "selected_model": "HY3",
            "input_class": "synthetic",
            "asset_id": asset_id,
            "asset_sha256": reference.sha256,
            "source_manifest_hash": source["manifest_hash"],
            "request_id": request_id,
            "tool_call_id": "submit_observation:" + request_id,
            "observation": observation_payload,
            "observation_hash": observation_hash,
            "connector_event": {"seq": seq, "event_hash": event_hash},
            "connector_receipt_hash": canonical_sha256(dict(connector_receipt)),
            "route_execution_verified": False,
            "provider_identity_verified": False,
            "created_at": now_iso(),
        }
        existing = next(
            (row for row in self.store.records(task_id, "connector_observation_capture") if row.get("record_id") == record_id),
            None,
        )
        if existing is not None:
            existing_body = dict(existing)
            existing_hash = existing_body.pop("record_hash", None)
            candidate = dict(body)
            candidate["created_at"] = existing_body.get("created_at")
            if existing_hash != canonical_sha256(existing_body) or existing_body != candidate:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector observation capture changed")
            return {"record_id": record_id, "record_hash": existing_hash, "replayed": True, "route_execution_verified": False}
        record_hash = canonical_sha256(body)
        self.store.put_record(task_id, "connector_observation_capture", record_id, {**body, "record_hash": record_hash})
        return {"record_id": record_id, "record_hash": record_hash, "replayed": False, "route_execution_verified": False}

    def capture_reference_analysis_response(
        self,
        task_id: str,
        *,
        run_id: str,
        session_id: str,
        raw_response: bytes | str,
        config: Mapping[str, Any],
        input_class: str = "synthetic",
        collection_mode: str = "controller_transport",
    ) -> dict[str, Any]:
        """Capture a controller-observed response envelope and derive its hashes.

        ``raw_response`` is bytes supplied by the controller transport itself;
        evidence registration later resolves only the returned capture ID.  No
        arbitrary path or caller-provided response digest is accepted here.
        """
        if collection_mode not in {"controller_transport", "human_handoff"}:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "unsupported controller collection mode")
        if str(input_class) != "synthetic":
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "this collector accepts synthetic inputs only")
        run_id = self._stable_execution_id(run_id, "run_id")
        session_id = self._stable_execution_id(session_id, "session_id")
        if not isinstance(config, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "collector config must be an explicit object")
        if isinstance(raw_response, str):
            raw_bytes = raw_response.encode("utf-8")
        elif isinstance(raw_response, bytes):
            raw_bytes = raw_response
        else:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "raw_response must be controller-captured bytes or text")
        if not raw_bytes or len(raw_bytes) > 1024 * 1024:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "raw_response must be non-empty and at most 1 MiB")
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON field: " + key)
                    result[key] = value
                return result
            envelope = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=unique_object,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON: " + value)))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response must be a UTF-8 JSON envelope") from exc
        allowed = {
            "schema", "route_id", "selected_model", "run_id", "session_id", "tool_call_id",
            "observation_record_ids", "analysis",
        }
        if not isinstance(envelope, Mapping) or set(envelope) != allowed:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response envelope fields are invalid")
        if envelope.get("schema") != "bridge.workbuddy.reference_analysis_response/1.0":
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response schema is unsupported")
        if envelope.get("route_id") != "WorkBuddyDesktopRoute" or str(envelope.get("selected_model") or "").casefold() != "hy3":
            raise PipelineExecutionError(ErrorCode.MODEL_CAPABILITY_MISMATCH.value, "captured response does not claim the configured WorkBuddy HY3 route")
        if envelope.get("run_id") != run_id or envelope.get("session_id") != session_id:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "captured response run/session binding changed")
        tool_call_id = self._stable_execution_id(envelope.get("tool_call_id"), "tool_call_id")
        observation_ids = envelope.get("observation_record_ids")
        if not isinstance(observation_ids, list) or not observation_ids or any(not isinstance(item, str) for item in observation_ids):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response must reference connector observation record IDs")
        if len(set(observation_ids)) != len(observation_ids):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response observation IDs must be unique")
        source = self.pipeline._assert_frozen_sources(task_id)
        spec = TaskSpecV2.from_mapping(self.store.get_task(task_id)["spec"])
        expected_assets = {item.asset_id: item.sha256 for item in spec.references}
        captured_assets: dict[str, str] = {}
        observation_hashes: list[str] = []
        for record_id in observation_ids:
            rows = [row for row in self.store.records(task_id, "connector_observation_capture") if row.get("record_id") == record_id]
            if len(rows) != 1:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "captured response references an unknown connector observation")
            record = dict(rows[0])
            record_hash = record.pop("record_hash", None)
            if record_hash != canonical_sha256(record):
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector observation record changed")
            if record.get("task_id") != task_id or record.get("run_id") != run_id or record.get("session_id") != session_id:
                raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "connector observation belongs to a different task/run/session")
            if record.get("source_manifest_hash") != source["manifest_hash"]:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "connector observation source binding is stale")
            if str(record.get("asset_id")) in captured_assets:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "response repeats a reference asset")
            captured_assets[str(record.get("asset_id"))] = str(record.get("asset_sha256"))
            observation_hashes.append(str(record.get("observation_hash")))
        if captured_assets != expected_assets:
            raise PipelineExecutionError(ErrorCode.AWAITING_INPUT.value, "captured response must cover every frozen reference asset exactly")
        analysis = envelope.get("analysis")
        if not isinstance(analysis, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "captured response analysis must be an object")
        contract = self.reference_analysis_receipt_contract(
            task_id, run_id=run_id, session_id=session_id, analysis=analysis, config=dict(config)
        )
        provider_response_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        capture_id = "capture_" + canonical_sha256({
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "collection_mode": collection_mode,
            "provider_response_sha256": provider_response_sha256,
            "observation_record_ids": observation_ids,
            "input_sha256": contract["input_sha256"],
            "output_sha256": contract["output_sha256"],
        })
        receipt = {
            "tool_call_id": tool_call_id,
            "input_sha256": contract["input_sha256"],
            "output_sha256": contract["output_sha256"],
            "provider_response_sha256": provider_response_sha256,
        }
        body = {
            "schema": "bridge.reference-analysis-capture/1.0",
            "capture_id": capture_id,
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "route_id": "WorkBuddyDesktopRoute",
            "selected_model": "HY3",
            "input_class": "synthetic",
            "source_manifest_hash": contract["source_manifest_hash"],
            "reference_hashes": contract["reference_hashes"],
            "config_sha256": contract["config_sha256"],
            "analysis": contract["analysis"],
            "analysis_output_sha256": contract["output_sha256"],
            "observation_record_ids": list(observation_ids),
            "observation_hashes": observation_hashes,
            "tool_receipt": receipt,
            "raw_response_size": len(raw_bytes),
            "raw_response_utf8": raw_bytes.decode("utf-8"),
            "collection_mode": collection_mode,
            "human_intervention": collection_mode == "human_handoff",
            "automated_collection": collection_mode == "controller_transport",
            "controller_handoff_verified": collection_mode == "human_handoff",
            "provider_response_sha256": provider_response_sha256,
            # This proves a controller-collected route exchange, not the
            # provider identity behind the desktop UI selection.
            "route_exchange_captured": collection_mode == "controller_transport",
            "provider_identity_verified": False,
            "created_at": now_iso(),
        }
        existing = next(
            (row for row in self.store.records(task_id, "reference_analysis_capture") if row.get("capture_id") == capture_id),
            None,
        )
        if existing is not None:
            existing_body = dict(existing)
            existing_hash = existing_body.pop("capture_hash", None)
            candidate = dict(body)
            candidate["created_at"] = existing_body.get("created_at")
            if existing_hash != canonical_sha256(existing_body) or existing_body != candidate:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "reference analysis capture changed")
            return {
                "capture_id": capture_id, "capture_hash": existing_hash, "analysis": contract["analysis"],
                "tool_receipt": receipt, "replayed": True, "provider_identity_verified": False,
            }
        capture_hash = canonical_sha256(body)
        self.store.put_record(task_id, "reference_analysis_capture", capture_id, {**body, "capture_hash": capture_hash})
        return {
            "capture_id": capture_id, "capture_hash": capture_hash, "analysis": contract["analysis"],
            "tool_receipt": receipt, "replayed": False, "provider_identity_verified": False,
        }

    def _verified_capture(
        self,
        task_id: str,
        *,
        capture_id: str,
        run_id: str,
        session_id: str,
        contract: Mapping[str, Any],
    ) -> dict[str, Any]:
        capture_id = self._stable_execution_id(capture_id, "capture_id")
        rows = [row for row in self.store.records(task_id, "reference_analysis_capture") if row.get("capture_id") == capture_id]
        if len(rows) != 1:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "matching controlled response capture is missing")
        capture = dict(rows[0])
        capture_hash = capture.pop("capture_hash", None)
        if capture_hash != canonical_sha256(capture):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "reference analysis capture changed")
        if capture.get("task_id") != task_id or capture.get("run_id") != run_id or capture.get("session_id") != session_id:
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "response capture belongs to a different task/run/session")
        expected = {
            "source_manifest_hash": contract["source_manifest_hash"],
            "reference_hashes": contract["reference_hashes"],
            "config_sha256": contract["config_sha256"],
            "analysis_output_sha256": contract["output_sha256"],
        }
        if any(capture.get(key) != value for key, value in expected.items()):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "response capture no longer matches the registered analysis contract")
        manual = capture.get("collection_mode") == "human_handoff"
        if manual:
            if capture.get("controller_handoff_verified") is not True or capture.get("human_intervention") is not True:
                raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "response capture lacks manual handoff evidence")
        elif capture.get("route_exchange_captured") is not True:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "response capture lacks controlled route evidence")
        if "raw_response_utf8" in capture and hashlib.sha256(capture["raw_response_utf8"].encode("utf-8")).hexdigest() != capture.get("provider_response_sha256"):
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "stored raw response bytes changed")
        return {**capture, "capture_hash": capture_hash}

    def register_reference_analysis_run(
        self,
        task_id: str,
        *,
        run_id: str,
        session_id: str,
        analysis: Mapping[str, Any],
        tool_receipt: Optional[Mapping[str, Any]] = None,
        capture_id: Optional[str] = None,
        config: Optional[Mapping[str, Any]] = None,
        input_class: str = "synthetic",
    ) -> dict[str, Any]:
        if str(input_class) != "synthetic":
            raise PipelineExecutionError(ErrorCode.POLICY_DENIED.value, "this experimental registration accepts synthetic inputs only")
        run_id = self._stable_execution_id(run_id, "run_id")
        session_id = self._stable_execution_id(session_id, "session_id")
        if config is None or not isinstance(config, Mapping):
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "an explicit controller config object is required")
        contract = self.reference_analysis_receipt_contract(
            task_id, run_id=run_id, session_id=session_id, analysis=analysis, config=dict(config)
        )
        # A digest-shaped receipt without a controlled capture is intentionally
        # non-verifying.  Do not reserve the run_id, so a later real capture can
        # still register the same run without an artificial idempotency conflict.
        if capture_id is None:
            if tool_receipt is not None:
                if not isinstance(tool_receipt, Mapping):
                    raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "tool_receipt must be an object")
                allowed = {"tool_call_id", "input_sha256", "output_sha256", "provider_response_sha256"}
                if set(tool_receipt) != allowed:
                    raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "tool_receipt has unregistered fields")
                self._stable_execution_id(tool_receipt.get("tool_call_id"), "tool_receipt.tool_call_id")
                input_sha = self._receipt_digest(tool_receipt.get("input_sha256"), "tool_receipt.input_sha256")
                output_sha = self._receipt_digest(tool_receipt.get("output_sha256"), "tool_receipt.output_sha256")
                self._receipt_digest(tool_receipt.get("provider_response_sha256"), "tool_receipt.provider_response_sha256")
                if not hmac.compare_digest(input_sha, contract["input_sha256"]) or not hmac.compare_digest(output_sha, contract["output_sha256"]):
                    raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "tool receipt does not match registered input/output bytes")
            return {
                "task_id": task_id, "run_id": run_id, "run_record_hash": None, "replayed": False,
                "route_execution_verified": False, "provider_identity_verified": False,
                "evidence_missing": "controlled_response_capture",
            }

        capture = self._verified_capture(
            task_id, capture_id=capture_id, run_id=run_id, session_id=session_id, contract=contract
        )
        receipt = dict(capture.get("tool_receipt") or {})
        if tool_receipt is not None and dict(tool_receipt) != receipt:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "caller receipt differs from the controlled capture")
        manual_handoff = capture.get("collection_mode") == "human_handoff"
        authorization_id = "execauth_" + canonical_sha256({"task_id": task_id, "run_id": run_id, "session_id": session_id})
        body: dict[str, Any] = {
            "schema": "bridge.external-analysis-run/1.1",
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "route_id": "WorkBuddyDesktopRoute",
            "selected_model": "HY3",
            "input_class": "synthetic",
            "reference_hashes": contract["reference_hashes"],
            "source_manifest_hash": contract["source_manifest_hash"],
            "config_sha256": contract["config_sha256"],
            "analysis_output_sha256": contract["output_sha256"],
            "tool_receipt": receipt,
            "collector_record_id": capture_id,
            "collector_record_hash": capture["capture_hash"],
            "trusted_control_authorized": True,
            "authorization_id": authorization_id,
            "route_execution_verified": not manual_handoff,
            "collection_mode": capture.get("collection_mode", "controller_transport"),
            "human_intervention": manual_handoff,
            "controller_handoff_verified": manual_handoff,
            "provider_identity_verified": False,
            "provider_identity_scope": "workbuddy_app_hy3_selection_only",
            "created_at": now_iso(),
        }
        if self.provider_witness_verifier is not None and not manual_handoff:
            try:
                if self.provider_witness_verifier(dict(body)) is True:
                    body["provider_identity_verified"] = True
                    body["provider_identity_scope"] = "provider_authenticated_hy3"
            except Exception:
                body["provider_identity_verified"] = False
                body["provider_identity_scope"] = "workbuddy_app_hy3_selection_only"
        existing = [row for row in self.store.records(task_id, "external_model_run") if row.get("run_id") == run_id]
        if existing:
            if len(existing) != 1:
                raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "run_id has ambiguous execution evidence")
            existing_record = dict(existing[0])
            existing_hash = existing_record.pop("run_record_hash", None)
            candidate = dict(body)
            candidate["created_at"] = existing_record.get("created_at")
            if existing_hash != canonical_sha256(existing_record) or existing_record != candidate:
                raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "run_id is already bound to different execution evidence")
            return {
                "task_id": task_id, "run_id": run_id, "run_record_hash": existing_hash,
                "replayed": True, "route_execution_verified": not manual_handoff,
                "provider_identity_verified": existing_record["provider_identity_verified"],
                "collector_record_id": capture_id,
            }
        record_hash = canonical_sha256(body)
        self.store.put_record(task_id, "external_model_run", run_id, {**body, "run_record_hash": record_hash})
        return {
            "task_id": task_id, "run_id": run_id, "run_record_hash": record_hash,
            "replayed": False, "route_execution_verified": not manual_handoff,
            "provider_identity_verified": body["provider_identity_verified"],
            "collector_record_id": capture_id,
        }


class TrustedApprovalControl:
    """Trusted-only final acceptance and approval grants.

    This class is intentionally absent from ``MODEL_SAFE_COMMANDS``.  The CLI
    mounts it only under the approval control-plane subcommands.
    """

    PROOF_VERSION = "hmac-sha256-v1"

    def __init__(self, pipeline: ModelSafePipeline) -> None:
        self.pipeline = pipeline
        self.store = pipeline.store
        self.approvals = ApprovalService(self.store, _ExplicitHumanVerification())
        self.experiences = ExperienceService(self.store, self.approvals)

    @classmethod
    def _proof_message(cls, actor: str, scope: str, subject_id: str) -> str:
        return "{}:{}:{}:{}".format(cls.PROOF_VERSION, scope, subject_id, actor)

    @classmethod
    def sign_proof(cls, actor: str, scope: str, subject_id: str) -> str:
        """Called by the trusted interactive/UI control plane, never a model tool."""

        if not str(actor).strip() or not str(scope).strip() or not str(subject_id).strip():
            raise PolicyDenied(ErrorCode.TRUSTED_HUMAN_REQUIRED, "trusted proof requires actor, scope, and subject id")
        secret = load_approval_secret().encode("utf-8")
        return hmac.new(secret, cls._proof_message(actor, scope, subject_id).encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    def verify_proof(cls, actor: str, proof: str, scope: str, subject_id: str) -> bool:
        if not str(actor).strip() or not re.fullmatch(r"[0-9a-f]{64}", str(proof or "")):
            return False
        try:
            expected = cls.sign_proof(actor, scope, subject_id)
        except PolicyDenied:
            return False
        return hmac.compare_digest(expected, str(proof))

    @classmethod
    def _require_proof(cls, actor: str, trust_proof: str, scope: str, subject_id: str) -> None:
        if not cls.verify_proof(actor, trust_proof, scope, subject_id):
            raise PolicyDenied(
                ErrorCode.TRUSTED_HUMAN_REQUIRED,
                "trusted control command requires a valid out-of-band HMAC proof",
            )

    def accept_result(
        self,
        task_id: str,
        actor: str,
        trust_proof: str,
        verification_id: str,
        verification_hash: str,
        artist_notes: str = "",
    ) -> dict[str, Any]:
        acceptance_subject = "{}:{}".format(task_id, verification_id)
        self._require_proof(actor, trust_proof, "final_result_acceptance", acceptance_subject)
        self.pipeline._assert_frozen_sources(task_id)
        if self.store.status(task_id)["state"] != TaskState.VERIFYING.value:
            raise PipelineExecutionError(ErrorCode.INVALID_TRANSITION.value, "final acceptance requires VERIFYING")
        selection = self.pipeline._current_selection(task_id)
        candidate_payload = dict(selection["candidate"])
        candidate = self.pipeline._candidate(candidate_payload)
        issue_payload = next(
            (item for item in self.store.records(task_id, "issue") if item.get("issue_id") == candidate.issue_id),
            None,
        )
        hypothesis_payload = next(
            (item for item in self.store.records(task_id, "hypothesis") if item.get("hypothesis_id") == candidate.hypothesis_id),
            None,
        )
        if issue_payload is None or hypothesis_payload is None:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "selected candidate has no durable issue/hypothesis lineage")
        verification = next(
            (
                item
                for item in self.store.records(task_id, "technical_verification")
                if item.get("verification_id") == verification_id
            ),
            None,
        )
        if verification is None:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_MISSING.value, "technical verification record does not exist")
        stored_hash = str(verification.get("verification_hash") or "")
        unsigned = {key: value for key, value in verification.items() if key != "verification_hash"}
        if not verification_hash or not hmac.compare_digest(verification_hash, stored_hash) or canonical_sha256(unsigned) != stored_hash:
            raise PipelineExecutionError(ErrorCode.ARTIFACT_INVALID.value, "technical verification record hash is invalid")
        for artifact_id in verification.get("artifact_ids") or []:
            self.pipeline._verified_artifact(task_id, str(artifact_id), allow_reference=False)
        scorecard = dict(verification.get("scorecard") or {})
        target_improved = bool(scorecard.get("target_improved"))
        protected = tuple(str(item) for item in scorecard.get("protected_regressions") or [])
        artifact_hashes = [str(item) for item in verification.get("artifact_hashes") or []]
        result_hash = artifact_hashes[-1] if artifact_hashes else ""
        if not target_improved or protected or not result_hash:
            raise PipelineExecutionError(
                ErrorCode.VISUAL_GATE_FAILED.value,
                "trusted final acceptance requires a passing technical verification record",
            )
        domain = DomainPackRef.from_mapping(candidate_payload["domain"])
        experience_payload = {
            "experience_id": new_identifier("experience"),
            "task_id": task_id,
            "domain": domain.to_dict(),
            "raw_feedback": str(issue_payload["raw_feedback"]),
            "issue": issue_payload,
            "hypothesis": hypothesis_payload,
            "candidate": candidate_payload,
            "scorecard": scorecard,
            "context": {
                "accepted_by": actor,
                "acceptance_source": self.PROOF_VERSION,
                "technical_verification_id": verification_id,
                "technical_verification_hash": stored_hash,
                "artist_notes": str(artist_notes),
            },
            "verified_result_hash": result_hash,
            "user_confirmed": True,
            "created_at": now_iso(),
        }
        experience = self.pipeline._experience(experience_payload, expected_task_id=task_id)
        if not experience.verified:
            raise PipelineExecutionError(ErrorCode.EXPERIENCE_NOT_VERIFIED.value, "final acceptance did not produce a verified experience")
        acceptance = {
            "task_id": task_id,
            "accepted_by": actor,
            "accepted_at": now_iso(),
            "trust_proof_version": self.PROOF_VERSION,
            "technical_verification_id": verification_id,
            "technical_verification_hash": stored_hash,
            "experience": experience.to_dict(),
        }
        self.store.put_record(task_id, "trusted_acceptance", "current", acceptance)
        self.store.save_result(task_id, {**self.pipeline._summary(task_id), "trusted_acceptance": acceptance})
        return acceptance

    def grant_cache(self, request_id: str, actor: str, trust_proof: str) -> dict[str, Any]:
        self._require_proof(actor, trust_proof, ApprovalScope.HOUDINI_SIMULATION_CACHE.value, request_id)
        request = self.store.get_approval_request(request_id)
        if request["scope"] != ApprovalScope.HOUDINI_SIMULATION_CACHE.value:
            raise PolicyDenied(ErrorCode.APPROVAL_SCOPE_MISMATCH, "grant-cache cannot authorize experience promotion")
        rows = self.store.records(str(request["task_id"]), "cache_subject")
        subject = next((self.pipeline._cache_subject(row) for row in rows
                        if self.pipeline._cache_subject(row).subject_hash == request["subject_hash"]), None)
        if subject is None:
            raise PolicyDenied(ErrorCode.APPROVAL_REQUIRED, "cache request has no matching durable resource subject")
        self.pipeline._assert_cache_resource_policy(str(request["task_id"]), subject)
        return self.approvals.grant(request_id, actor, trust_proof, ActorKind.TRUSTED_HUMAN).to_dict()

    def configure_cache_resources(self, task_id: str, *, task_roots, estimated_bytes: int,
                                  max_disk_bytes: int, max_seconds: float,
                                  invalidation_scope, simulation_start_frame: int) -> dict[str, Any]:
        """Controller-only preparation; human authorization remains grant_cache."""
        import math
        self.store.get_task(task_id)
        if (type(simulation_start_frame) is not int or type(estimated_bytes) is not int or estimated_bytes <= 0 or
                type(max_disk_bytes) is not int or max_disk_bytes < estimated_bytes or
                isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or
                not math.isfinite(max_seconds) or not 0 < max_seconds <= 120):
            raise PolicyDenied(ErrorCode.APPROVAL_SCOPE_MISMATCH, "invalid trusted cache budget")
        if (not isinstance(task_roots, (list, tuple)) or not task_roots or
                any(not Path(root).is_absolute() or Path(root).is_symlink() for root in task_roots) or
                not isinstance(invalidation_scope, (list, tuple)) or not invalidation_scope or
                any(not isinstance(item, str) or not item.strip() for item in invalidation_scope)):
            raise PolicyDenied(ErrorCode.APPROVAL_SCOPE_MISMATCH, "explicit task roots and invalidation scope required")
        policy = {"task_roots": [str(Path(root).resolve()) for root in task_roots],
                  "estimated_bytes": estimated_bytes, "max_disk_bytes": max_disk_bytes,
                  "simulation_start_frame": simulation_start_frame,
                  "max_seconds": max_seconds, "invalidation_scope": list(invalidation_scope)}
        self.store.put_record(task_id, "cache_resource_policy", "current", policy)
        return policy

    def grant_experience(self, request_id: str, actor: str, trust_proof: str) -> dict[str, Any]:
        self._require_proof(actor, trust_proof, ApprovalScope.REPAIR_EXPERIENCE_PROMOTION.value, request_id)
        request = self.store.get_approval_request(request_id)
        if request["scope"] != ApprovalScope.REPAIR_EXPERIENCE_PROMOTION.value:
            raise PolicyDenied(ErrorCode.APPROVAL_SCOPE_MISMATCH, "grant-experience cannot authorize a simulation cache")
        grant = self.approvals.grant(request_id, actor, trust_proof, ActorKind.TRUSTED_HUMAN)
        pending = next(
            (
                item
                for item in self.store.records(str(request["task_id"]), "pending_experience")
                if item.get("request_id") == request_id
            ),
            None,
        )
        if pending is None:
            raise PipelineExecutionError(ErrorCode.INVALID_SPEC.value, "approved experience request has no durable pending experience")
        experience = self.pipeline._experience(pending["experience"], expected_task_id=str(request["task_id"]))
        promoted = self.experiences.promote(experience, grant.grant_id)
        status = self.store.transition(
            str(request["task_id"]),
            TaskState.COMPLETED,
            "verified repair experience promoted after separate trusted-human approval",
        )
        result = {"grant": grant.to_dict(), "experience": promoted, "status": status}
        self.store.save_result(str(request["task_id"]), result)
        return result
