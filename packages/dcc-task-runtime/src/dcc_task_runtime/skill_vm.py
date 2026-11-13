"""Deterministic executor for the bounded SkillIR model contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from .canonical import canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode, now_iso
from .skill_ir import ModelActionSelection, SkillAction, SkillIR


@dataclass(frozen=True)
class ExecutionRequest:
    skill_id: str
    skill_version: str
    state_id: str
    action_id: str
    control_id: Optional[str]
    candidate_id: Optional[str]
    idempotency_key: str

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "state_id": self.state_id,
            "action_id": self.action_id,
            "control_id": self.control_id,
            "candidate_id": self.candidate_id,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class ExecutionRecord:
    request: ExecutionRequest
    succeeded: bool
    recoverable: bool
    next_state: str
    output: Mapping[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    replayed: bool = False
    created_at: str = field(default_factory=now_iso)

    def replay_copy(self) -> "ExecutionRecord":
        return ExecutionRecord(
            request=self.request,
            succeeded=self.succeeded,
            recoverable=self.recoverable,
            next_state=self.next_state,
            output=self.output,
            error_code=self.error_code,
            error_message=self.error_message,
            replayed=True,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "succeeded": self.succeeded,
            "recoverable": self.recoverable,
            "next_state": self.next_state,
            "output": json_value(self.output),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "replayed": self.replayed,
            "created_at": self.created_at,
        }


Executor = Callable[[ExecutionRequest], Mapping[str, Any]]


class SkillExecutionVM:
    """Validate one model action and dispatch it to a trusted executor.

    The VM owns idempotency and state transitions.  Executors receive resolved
    IDs only; domain packs remain responsible for mapping those IDs to actual
    DCC parameters and paths.
    """

    def __init__(self, skill: SkillIR, executor: Executor) -> None:
        if not callable(executor):
            raise TypeError("executor must be callable")
        self.skill = skill
        self.executor = executor
        self._journal: dict[str, tuple[str, ExecutionRecord]] = {}

    @property
    def journal(self) -> tuple[ExecutionRecord, ...]:
        return tuple(record for _fingerprint, record in self._journal.values())

    def execute(
        self,
        state_id: str,
        selection: ModelActionSelection | Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> ExecutionRecord:
        state = self.skill.state(state_id)
        parsed = selection if isinstance(selection, ModelActionSelection) else ModelActionSelection.from_mapping(selection)
        action = state.action(parsed.action_id)
        self._validate_selection(action, parsed)
        key = str(idempotency_key or "").strip()
        if not key:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "idempotency_key is required")
        request = ExecutionRequest(
            skill_id=self.skill.skill_id,
            skill_version=self.skill.version,
            state_id=state.state_id,
            action_id=action.action_id,
            control_id=parsed.control_id,
            candidate_id=parsed.candidate_id,
            idempotency_key=key,
        )
        fingerprint = canonical_sha256(request.to_dict())
        existing = self._journal.get(key)
        if existing is not None:
            existing_fingerprint, record = existing
            if existing_fingerprint != fingerprint:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    "idempotency key is bound to a different action",
                    {"idempotency_key": key},
                )
            return record.replay_copy()

        try:
            raw_output = self.executor(request)
            if not isinstance(raw_output, Mapping):
                raise RuntimeV2Error(ErrorCode.INTERNAL_ERROR, "executor must return an object")
            output = json_value(raw_output)
            record = ExecutionRecord(
                request=request,
                succeeded=True,
                recoverable=False,
                next_state=action.success_state or state.state_id,
                output=output,
            )
        except RuntimeV2Error as exc:
            code = exc.code.value
            record = ExecutionRecord(
                request=request,
                succeeded=False,
                recoverable=code in action.recoverable_error_codes,
                next_state=state.state_id,
                output={"details": json_value(exc.details)},
                error_code=code,
                error_message=str(exc),
            )
        except Exception as exc:
            # Executor bugs are evidence-bearing failures too.  Preserve the
            # stable error class without leaking a traceback or pretending the
            # model can recover from an undeclared host failure.
            record = ExecutionRecord(
                request=request,
                succeeded=False,
                recoverable=False,
                next_state=state.state_id,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                error_message=f"executor failed: {type(exc).__name__}",
            )
        self._journal[key] = (fingerprint, record)
        return record

    @staticmethod
    def _validate_selection(action: SkillAction, selection: ModelActionSelection) -> None:
        if action.requires_control and selection.control_id is None:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "action requires a control_id")
        if selection.control_id is not None and selection.control_id not in action.control_ids:
            raise RuntimeV2Error(
                ErrorCode.POLICY_DENIED,
                "control_id is not allowed for this action",
                {"action_id": action.action_id, "control_id": selection.control_id},
            )
        if action.requires_candidate and selection.candidate_id is None:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "action requires a candidate_id")
        if selection.candidate_id is not None and selection.candidate_id not in action.candidate_ids:
            raise RuntimeV2Error(
                ErrorCode.POLICY_DENIED,
                "candidate_id is not allowed for this action",
                {"action_id": action.action_id, "candidate_id": selection.candidate_id},
            )
