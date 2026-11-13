"""Typed failures for the v2 orchestration contracts."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .models import ErrorCode


class RuntimeV2Error(ValueError):
    """A stable, machine-readable runtime error.

    The message is intended for an operator.  ``code`` and ``details`` are the
    stable surface that a lower-capability planner should branch on.
    """

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.code = code if isinstance(code, ErrorCode) else ErrorCode(code)
        self.details = dict(details or {})
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.code.value, "message": str(self), "details": dict(self.details)}


class DiagnosisInconclusive(RuntimeV2Error):
    def __init__(self, message: str, next_question: str, details: Optional[Mapping[str, Any]] = None) -> None:
        payload = dict(details or {})
        payload["next_question"] = next_question
        self.next_question = next_question
        super().__init__(ErrorCode.DIAGNOSIS_INCONCLUSIVE, message, payload)


class PolicyDenied(RuntimeV2Error):
    pass
