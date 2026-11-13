"""Small-model-safe intermediate representation for Bridge Skills.

The model-facing contract deliberately contains identifiers only.  Paths,
scripts, parameter values, and executor arguments remain in trusted domain
packs and the execution VM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Optional, Sequence

from .canonical import json_value
from .errors import RuntimeV2Error
from .models import ErrorCode


MAX_ACTIONS_PER_PROMPT_CARD = 4
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


def _identifier(value: Any, name: str) -> str:
    rendered = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(rendered):
        raise RuntimeV2Error(
            ErrorCode.INVALID_SPEC,
            f"{name} must be a stable identifier",
            {"field": name},
        )
    return rendered


def _unique_identifiers(values: Sequence[str], name: str) -> tuple[str, ...]:
    result = tuple(_identifier(value, name) for value in values)
    if len(result) != len(set(result)):
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} contains duplicates")
    return result


@dataclass(frozen=True)
class SkillAction:
    """Trusted action definition exposed to a model as bounded IDs."""

    action_id: str
    label: str
    description: str = ""
    control_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    requires_control: bool = False
    requires_candidate: bool = False
    success_state: Optional[str] = None
    recoverable_error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        if not str(self.label).strip():
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "action label is required")
        object.__setattr__(self, "control_ids", _unique_identifiers(self.control_ids, "control_id"))
        object.__setattr__(self, "candidate_ids", _unique_identifiers(self.candidate_ids, "candidate_id"))
        if self.requires_control and not self.control_ids:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "required control has no allowed IDs")
        if self.requires_candidate and not self.candidate_ids:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "required candidate has no allowed IDs")
        if self.success_state is not None:
            object.__setattr__(self, "success_state", _identifier(self.success_state, "success_state"))
        error_codes = tuple(str(value).strip() for value in self.recoverable_error_codes)
        if any(not value for value in error_codes) or len(error_codes) != len(set(error_codes)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "recoverable_error_codes must be unique non-empty strings")
        object.__setattr__(self, "recoverable_error_codes", error_codes)

    def to_prompt_dict(self) -> dict[str, Any]:
        """Return the complete and only model-visible action surface."""

        return {
            "action_id": self.action_id,
            "label": self.label,
            "description": self.description,
            "control_ids": list(self.control_ids),
            "candidate_ids": list(self.candidate_ids),
            "requires_control": self.requires_control,
            "requires_candidate": self.requires_candidate,
        }


@dataclass(frozen=True)
class SkillState:
    state_id: str
    instruction: str
    actions: tuple[SkillAction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_id", _identifier(self.state_id, "state_id"))
        if not str(self.instruction).strip():
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "state instruction is required")
        actions = tuple(self.actions)
        object.__setattr__(self, "actions", actions)
        if not actions:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "a skill state must expose at least one action")
        if len(actions) > MAX_ACTIONS_PER_PROMPT_CARD:
            raise RuntimeV2Error(
                ErrorCode.TOOL_BUDGET_EXCEEDED,
                "a skill state may expose at most four actions",
                {"state_id": self.state_id, "maximum": MAX_ACTIONS_PER_PROMPT_CARD},
            )
        identifiers = tuple(action.action_id for action in actions)
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "action IDs must be unique within a state")

    def action(self, action_id: str) -> SkillAction:
        for action in self.actions:
            if action.action_id == action_id:
                return action
        raise RuntimeV2Error(
            ErrorCode.POLICY_DENIED,
            "action is not allowed in the current state",
            {"state_id": self.state_id, "action_id": action_id},
        )


@dataclass(frozen=True)
class SkillIR:
    skill_id: str
    version: str
    initial_state: str
    states: tuple[SkillState, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _identifier(self.skill_id, "skill_id"))
        if not str(self.version).strip():
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "skill version is required")
        object.__setattr__(self, "initial_state", _identifier(self.initial_state, "initial_state"))
        states = tuple(self.states)
        object.__setattr__(self, "states", states)
        identifiers = tuple(state.state_id for state in states)
        if not states or len(identifiers) != len(set(identifiers)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "skill states must be non-empty and unique")
        if self.initial_state not in identifiers:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "initial_state is not declared")
        known = set(identifiers)
        for state in states:
            for action in state.actions:
                if action.success_state is not None and action.success_state not in known:
                    raise RuntimeV2Error(
                        ErrorCode.INVALID_SPEC,
                        "action success_state is not declared",
                        {"action_id": action.action_id, "success_state": action.success_state},
                    )

    def state(self, state_id: str) -> SkillState:
        for state in self.states:
            if state.state_id == state_id:
                return state
        raise RuntimeV2Error(ErrorCode.INVALID_TRANSITION, "unknown skill state", {"state_id": state_id})


@dataclass(frozen=True)
class ModelActionSelection:
    """Strict single-action response accepted from a planning model."""

    action_id: str
    control_id: Optional[str] = None
    candidate_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        if self.control_id is not None:
            object.__setattr__(self, "control_id", _identifier(self.control_id, "control_id"))
        if self.candidate_id is not None:
            object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelActionSelection":
        if not isinstance(value, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model selection must be one object")
        allowed = {"action_id", "control_id", "candidate_id"}
        unknown = sorted(str(key) for key in value if key not in allowed)
        if unknown:
            raise RuntimeV2Error(
                ErrorCode.POLICY_DENIED,
                "model selection contains forbidden fields",
                {"fields": unknown},
            )
        return cls(
            action_id=value.get("action_id"),
            control_id=value.get("control_id"),
            candidate_id=value.get("candidate_id"),
        )

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "action_id": self.action_id,
            "control_id": self.control_id,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True)
class PromptCard:
    skill_id: str
    skill_version: str
    state_id: str
    instruction: str
    actions: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.actions) <= MAX_ACTIONS_PER_PROMPT_CARD:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "PromptCard must contain one to four actions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "state_id": self.state_id,
            "instruction": self.instruction,
            "response_schema": {
                "required": ["action_id"],
                "optional": ["control_id", "candidate_id"],
                "additional_properties": False,
            },
            "actions": [json_value(action) for action in self.actions],
        }


class SkillCompiler:
    """Compile trusted, explicit state definitions into compact PromptCards."""

    def __init__(self, skill: SkillIR) -> None:
        self.skill = skill

    def compile(self, state_id: str) -> PromptCard:
        state = self.skill.state(state_id)
        return PromptCard(
            skill_id=self.skill.skill_id,
            skill_version=self.skill.version,
            state_id=state.state_id,
            instruction=state.instruction,
            actions=tuple(action.to_prompt_dict() for action in state.actions),
        )
