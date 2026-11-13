"""Concrete, fail-closed macOS Accessibility transport for the Doubao app.

The native helper is intentionally a small, fixed operation vocabulary.  This
module never accepts scripts, coordinates, or an injected shell command.  The
only outbound content accepted by the driver is a typed synthetic benchmark
prompt; callers must provide that authorization explicitly.  B1 deliberately
has no attachment, screenshot, or vision upload transport.  AX permission is
granted to this helper executable's macOS TCC identity, not implicitly to
Codex or to the Doubao application.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4


SCHEMA = "bridge.doubao_ax/1.0"
ROUTE_ID = "DoubaoDesktopRoute"
BUNDLE_ID = "com.bot.pc.doubao"
MAX_HELPER_OUTPUT = 1024 * 1024
MAX_PROMPT_CHARS = 64 * 1024
MAX_WAIT_SECONDS = 120.0
DEFAULT_CALL_TIMEOUT = 8.0
RESPONSE_STABLE_POLLS = 2
_BOOTSTRAP_TEXT = "Return exactly this JSON object and no other text: {\"bridge_probe\":\"doubao_ax_v1\",\"ok\":true}"
_BOOTSTRAP_EXPECTED = {"bridge_probe": "doubao_ax_v1", "ok": True}
_SESSION_RE = re.compile(r"^[0-9a-f]{32}$")


class DesktopErrorCode(str, Enum):
    AX_PERMISSION_REQUIRED = "AX_PERMISSION_REQUIRED"
    UI_CONTROL_UNVERIFIED = "UI_CONTROL_UNVERIFIED"
    PRIVACY_DENIED = "PRIVACY_DENIED"
    HELPER_UNAVAILABLE = "HELPER_UNAVAILABLE"
    HELPER_PROTOCOL_ERROR = "HELPER_PROTOCOL_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
class DoubaoDesktopError(RuntimeError):
    """Stable driver failure without exposing prompt contents or process data."""
    def __init__(
        self,
        code: DesktopErrorCode | str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
        *,
        indeterminate: bool = False,
    ) -> None:
        self.code = code.value if isinstance(code, DesktopErrorCode) else str(code)
        self.details = dict(details or {})
        self.indeterminate = bool(indeterminate)
        super().__init__(message)
    def to_dict(self) -> dict[str, Any]:
        result = {"error_code": self.code, "message": str(self), "details": dict(self.details)}
        if self.indeterminate:
            result["indeterminate"] = True
        return result
@dataclass(frozen=True)
class SyntheticOutboundAuthorization:
    """Typed permission for a synthetic benchmark outbound request."""
    input_class: str = "synthetic"
    scope: str = "synthetic_benchmark"
    existing_conversation_accessed: bool = False
    @classmethod
    def benchmark(cls) -> "SyntheticOutboundAuthorization":
        return cls()
    def __post_init__(self) -> None:
        if self.input_class != "synthetic" or self.scope != "synthetic_benchmark":
            raise DoubaoDesktopError(
                DesktopErrorCode.PRIVACY_DENIED,
                "Doubao desktop outbound content requires synthetic benchmark authorization",
            )
        if self.existing_conversation_accessed:
            raise DoubaoDesktopError(
                DesktopErrorCode.PRIVACY_DENIED,
                "existing Doubao conversations are outside the authorized outbound scope",
            )
@dataclass(frozen=True)
class SyntheticPrompt:
    text: str
    authorization: SyntheticOutboundAuthorization
    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "synthetic prompt text is required")
        if len(self.text) > MAX_PROMPT_CHARS:
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "synthetic prompt exceeds the bounded size")
        # Paths, byte payloads, and media objects have no field in this type.
        if "\x00" in self.text:
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "synthetic prompt contains an invalid character")
        if not isinstance(self.authorization, SyntheticOutboundAuthorization):
            raise DoubaoDesktopError(DesktopErrorCode.PRIVACY_DENIED, "typed synthetic authorization is required")
@dataclass(frozen=True)
class AXControl:
    kind: str
    available: bool
    role: str = ""
    identifier: str = ""
    title: str = ""
    enabled: bool = False
    value_length: int = 0
    value_digest: str = ""
    candidate_count: int = 0
    @classmethod
    def from_mapping(cls, kind: str, value: Mapping[str, Any]) -> "AXControl":
        available = value.get("available") is True
        length = value.get("value_length", 0)
        if not isinstance(length, int) or length < 0:
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX control value length is invalid")
        digest = str(value.get("value_digest") or "")
        if digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower())):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX control digest is invalid")
        count = value.get("candidate_count", 0)
        if not isinstance(count, int) or count < 0:
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX control candidate count is invalid")
        return cls(
            kind=kind,
            available=available,
            role=str(value.get("role") or ""),
            identifier=str(value.get("identifier") or ""),
            title=str(value.get("title") or ""),
            enabled=value.get("enabled") is True,
            value_length=length,
            value_digest=digest,
            candidate_count=count,
        )
    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "available": self.available,
            "role": self.role,
            "identifier": self.identifier,
            "title": self.title,
            "enabled": self.enabled,
            "value_length": self.value_length,
            "value_digest": self.value_digest,
            "candidate_count": self.candidate_count,
        }
@dataclass(frozen=True)
class AXSnapshot:
    app_path: str
    bundle_id: str
    app_version: str
    pid: int
    controls: Mapping[str, AXControl]
    fingerprint: str
    session_id: str = ""
    code_signature: str = ""
    executable_sha256: str = ""
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "app_path": self.app_path,
            "bundle_id": self.bundle_id,
            "app_version": self.app_version,
            "pid": self.pid,
            "session_id": self.session_id,
            "code_signature": self.code_signature,
            "executable_sha256": self.executable_sha256,
            "fingerprint": self.fingerprint,
            "controls": {key: value.to_dict() for key, value in self.controls.items()},
        }
    def require(self, *kinds: str) -> None:
        missing = sorted(kind for kind in kinds if not self.controls.get(kind, AXControl(kind, False)).available)
        if missing:
            raise DoubaoDesktopError(
                DesktopErrorCode.UI_CONTROL_UNVERIFIED,
                "required Doubao Accessibility controls were not verified",
                {"missing_controls": missing, "fingerprint": self.fingerprint},
            )
@dataclass(frozen=True)
class DoubaoResponse:
    session_id: str
    text: str
    status: str
    snapshot: Optional[AXSnapshot] = None
def _repo_root() -> Path:
    # .../packages/dcc-task-runtime/src/dcc_task_runtime/doubao_desktop.py
    return Path(__file__).resolve().parents[4]
def resolve_helper_path(explicit: Optional[Path | str] = None) -> Path:
    """Resolve the known first-party helper without accepting a shell command."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_UNAVAILABLE, "helper path must be absolute")
        if path.is_file() and os.access(path, os.X_OK):
            return path
        raise DoubaoDesktopError(DesktopErrorCode.HELPER_UNAVAILABLE, "configured AX helper is unavailable")
    candidates = (
        _repo_root() / "tools" / "doubao" / "doubao_ax_helper",
        Path("/usr/local/libexec/bridge-skills/doubao_ax_helper"),
        Path("/opt/homebrew/libexec/bridge-skills/doubao_ax_helper"),
        Path.home() / ".local" / "libexec" / "bridge-skills" / "doubao_ax_helper",
    )
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise DoubaoDesktopError(
        DesktopErrorCode.HELPER_UNAVAILABLE,
        "the first-party Doubao AX helper is not installed",
        {"expected_paths": [str(path) for path in candidates]},
    )
def resolve_app_path(explicit: Optional[Path | str] = None) -> Path:
    """Resolve an exact Doubao executable path, never a bundle-id-only match."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        _validate_app_path(path, require_exists=False)
        return path
    candidates = (
        Path("/Applications/Doubao.app/Contents/MacOS/Doubao"),
        Path.home() / "Applications" / "Doubao.app/Contents/MacOS/Doubao",
    )
    existing = [path for path in candidates if path.is_file()]
    if len(existing) == 1:
        _validate_app_path(existing[0], require_exists=True)
        return existing[0]
    if len(existing) > 1:
        raise DoubaoDesktopError(
            DesktopErrorCode.UI_CONTROL_UNVERIFIED,
            "multiple exact Doubao app executables were found",
            {"candidates": [str(path) for path in existing]},
        )
    raise DoubaoDesktopError(
        DesktopErrorCode.UI_CONTROL_UNVERIFIED,
        "the exact Doubao app executable was not found",
        {"candidates": [str(path) for path in candidates]},
    )
def _validate_app_path(path: Path, *, require_exists: bool) -> None:
    if not path.is_absolute() or path.name != "Doubao" or path.parts[-3:] != ("Contents", "MacOS", "Doubao") or path.parents[2].suffix != ".app":
        raise DoubaoDesktopError(
            DesktopErrorCode.UI_CONTROL_UNVERIFIED,
            "Doubao app identity requires an exact Contents/MacOS/Doubao path",
        )
    if path.exists() and path.resolve() != path:
        raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "Doubao app executable may not be reached through a symlink")
    if require_exists and not path.is_file():
        raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "exact Doubao executable is unavailable")
class DoubaoDesktopAXDriver:
    """Fixed-vocabulary AX driver suitable for a mediated planner gateway."""
    _OPERATIONS = frozenset({"probe", "snapshot", "new_task", "send_synthetic", "read_response"})
    def __init__(
        self,
        *,
        helper_path: Optional[Path | str] = None,
        app_path: Optional[Path | str] = None,
        outbound_authorization: Optional[SyntheticOutboundAuthorization] = None,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
    ) -> None:
        self.helper_path = resolve_helper_path(helper_path)
        self.app_path = resolve_app_path(app_path)
        if call_timeout <= 0 or call_timeout > MAX_WAIT_SECONDS:
            raise ValueError("call_timeout must be positive and bounded")
        self.call_timeout = float(call_timeout)
        if outbound_authorization is not None and not isinstance(outbound_authorization, SyntheticOutboundAuthorization):
            raise TypeError("outbound_authorization must be SyntheticOutboundAuthorization")
        self.outbound_authorization = outbound_authorization
        self._session_id: Optional[str] = None
        self._session_phase = "idle"
        self._last_prompt_text: Optional[str] = None
        self._cached_response: Optional[DoubaoResponse] = None
        self._strict_json_verified = False
        self._snapshot: Optional[AXSnapshot] = None
    @property
    def session_id(self) -> Optional[str]:
        """The UUID passed to every helper subprocess in this driver lifetime."""
        return self._session_id
    def capabilities(self) -> Mapping[str, Any]:
        """Report B1's real surface; attachment and vision upload are absent."""
        return {
            "snapshot_controls": ["composer", "response", "new_task"],
            "text_submission": True,
            "attachments": False,
            "image_input": False,
            "vision_upload": False,
            "media_reason": "B1 native AX transport is text-only and never uploads local media",
        }
    def __repr__(self) -> str:
        return f"DoubaoDesktopAXDriver(app_path={str(self.app_path)!r}, helper_path={str(self.helper_path)!r})"
    def _run_helper(self, operation: str, options: Sequence[str] = (), *, timeout: Optional[float] = None) -> Mapping[str, Any]:
        if operation not in self._OPERATIONS:
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "unsupported AX helper operation")
        argv = [str(self.helper_path), "--operation", operation, "--app-path", str(self.app_path)]
        argv.extend(str(item) for item in options)
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=float(timeout if timeout is not None else self.call_timeout),
            )
        except subprocess.TimeoutExpired as exc:
            raise DoubaoDesktopError(
                DesktopErrorCode.TIMEOUT,
                "Doubao AX helper did not finish within the bounded timeout",
                {"operation": operation},
                indeterminate=operation in {"new_task", "send_synthetic"},
            ) from exc
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise DoubaoDesktopError(
                DesktopErrorCode.HELPER_UNAVAILABLE,
                "the first-party Doubao AX helper could not be executed",
                {"operation": operation, "reason": type(exc).__name__},
            ) from exc
        raw = bytes(completed.stdout or b"")
        if len(raw) > MAX_HELPER_OUTPUT:
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX helper output exceeded the bound")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DoubaoDesktopError(
                DesktopErrorCode.HELPER_PROTOCOL_ERROR,
                "AX helper returned invalid JSON",
                {"operation": operation, "returncode": completed.returncode},
            ) from exc
        if not isinstance(decoded, Mapping) or decoded.get("schema") != SCHEMA:
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX helper returned an invalid protocol object")
        if decoded.get("ok") is not True:
            code = str(decoded.get("code") or DesktopErrorCode.HELPER_PROTOCOL_ERROR.value)
            message = str(decoded.get("message") or "Doubao AX helper reported a failure")
            details = decoded.get("details") if isinstance(decoded.get("details"), Mapping) else {}
            raise DoubaoDesktopError(code, message, details)
        result = decoded.get("result")
        if not isinstance(result, Mapping):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX helper success has no result object")
        return result
    def _snapshot_from_result(self, result: Mapping[str, Any]) -> AXSnapshot:
        controls_raw = result.get("controls")
        if not isinstance(controls_raw, Mapping):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX snapshot controls are missing")
        controls = {kind: AXControl.from_mapping(kind, value) for kind, value in controls_raw.items() if isinstance(value, Mapping)}
        expected = {"composer", "response", "new_task"}
        if not expected.issubset(controls):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX snapshot control set is incomplete")
        fingerprint = str(result.get("fingerprint") or "")
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint.lower()):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX snapshot fingerprint is invalid")
        app_path = str(result.get("app_path") or "")
        _validate_app_path(Path(app_path), require_exists=False)
        if app_path != str(self.app_path):
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "AX helper app identity does not match the requested executable")
        if str(result.get("bundle_id") or "") != BUNDLE_ID:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "AX helper bundle identity is not Doubao")
        pid = result.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX snapshot pid is invalid")
        session_id = str(result.get("session_id") or "")
        if session_id and not _SESSION_RE.fullmatch(session_id):
            raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX snapshot session id is invalid")
        return AXSnapshot(
            app_path=app_path,
            bundle_id=BUNDLE_ID,
            app_version=str(result.get("app_version") or ""),
            pid=pid,
            controls=controls,
            fingerprint=fingerprint,
            session_id=session_id,
            code_signature=str(result.get("code_signature") or ""),
            executable_sha256=str(result.get("executable_sha256") or ""),
        )
    def snapshot(self, *, require_controls: bool = False) -> AXSnapshot:
        options = (["--session-id", self._session_id] if self._session_id else [])
        snapshot = self._snapshot_from_result(self._run_helper("snapshot", options))
        if self._session_id and snapshot.session_id != self._session_id:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "AX snapshot session identity changed")
        self._snapshot = snapshot
        if require_controls:
            snapshot.require("composer", "response", "new_task")
        return snapshot
    def probe(self) -> Mapping[str, Any]:
        snapshot = self.snapshot(require_controls=False)
        snapshot.require("composer", "new_task")
        if self._strict_json_verified:
            snapshot.require("response")
        helper_sha = _sha256_file(self.helper_path)
        app_sha = snapshot.executable_sha256 or _sha256_file(Path(snapshot.app_path))
        isolated = bool(self._strict_json_verified and self._session_id and snapshot.session_id == self._session_id)
        # These flags describe observed facts only.  Strict model JSON and a
        # usable isolated session require the caller to complete the bootstrap.
        return {
            "route_id": ROUTE_ID,
            "bundle_id": snapshot.bundle_id,
            "app_version": snapshot.app_version,
            "executable_path": snapshot.app_path,
            "executable_sha256": app_sha,
            "code_signature": snapshot.code_signature,
            "driver_sha256": helper_sha,
            "ui_control_verified": True,
            "strict_json_verified": self._strict_json_verified,
            "isolated_session_verified": isolated,
            "attachments_verified": False,
            "image_input_verified": False,
            "vision_upload_verified": False,
            "session_id": self._session_id or "",
            "snapshot_fingerprint": snapshot.fingerprint,
        }
    def new_task_session(self) -> str:
        before = self.snapshot(require_controls=False)
        before.require("new_task")
        session_id = uuid4().hex
        try:
            result = self._run_helper("new_task", ["--session-id", session_id, "--guard-fingerprint", before.fingerprint])
            returned = str(result.get("session_id") or session_id)
            if not _SESSION_RE.fullmatch(returned):
                raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "AX helper returned an invalid session id")
            if returned != session_id:
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "new task helper changed the generated session identity")
            snapshot_raw = result.get("snapshot")
            if not isinstance(snapshot_raw, Mapping):
                raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "new task did not return a fresh snapshot")
            snapshot = self._snapshot_from_result(snapshot_raw)
            if snapshot.session_id != returned:
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "new task snapshot session identity is inconsistent")
            snapshot.require("composer")
        except DoubaoDesktopError:
            # The button may have been pressed even when the helper timed out
            # or its acknowledgement was malformed.  Do not silently retry.
            self._session_phase = "indeterminate"
            raise
        self._session_id = returned
        self._session_phase = "ready"
        self._last_prompt_text = None
        self._cached_response = None
        self._strict_json_verified = False
        self._snapshot = snapshot
        return returned
    # Short alias for callers that treat sessions as a normal driver resource.
    new_task = new_task_session
    def bootstrap(self, timeout_seconds: float = 30.0) -> Mapping[str, Any]:
        """Prove strict JSON on a fresh synthetic session before planner use."""
        if self.outbound_authorization is None:
            raise DoubaoDesktopError(DesktopErrorCode.PRIVACY_DENIED, "bootstrap requires synthetic benchmark authorization")
        session_id = self.new_task_session()
        self.send_synthetic(SyntheticPrompt(_BOOTSTRAP_TEXT, self.outbound_authorization))
        response = self.wait_for_response(timeout_seconds=timeout_seconds)
        if response.session_id != session_id or response.snapshot is None or response.snapshot.session_id != session_id:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "bootstrap response was not bound to the fresh session")
        try:
            decoded = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "bootstrap response was not strict JSON") from exc
        if not isinstance(decoded, Mapping) or dict(decoded) != _BOOTSTRAP_EXPECTED:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "bootstrap JSON challenge did not match exactly")
        self._strict_json_verified = True
        return self.probe()
    def send_synthetic(self, prompt: SyntheticPrompt) -> Mapping[str, Any]:
        if not isinstance(prompt, SyntheticPrompt):
            raise DoubaoDesktopError(DesktopErrorCode.PRIVACY_DENIED, "send_synthetic requires a typed SyntheticPrompt")
        if self.outbound_authorization is None:
            raise DoubaoDesktopError(DesktopErrorCode.PRIVACY_DENIED, "send_synthetic requires synthetic benchmark authorization")
        if prompt.authorization != self.outbound_authorization:
            raise DoubaoDesktopError(DesktopErrorCode.PRIVACY_DENIED, "synthetic authorization does not match this driver")
        if self._session_phase == "submitted":
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "a synthetic prompt is already submitted; wait for its response")
        if self._session_phase == "completed":
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "a completed session cannot be submitted twice; start a new task")
        if self._session_phase == "indeterminate":
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "the previous synthetic submission is indeterminate; start a new task")
        session_id, snapshot = self._require_session(require_response=False)
        try:
            self._session_phase = "submitting"
            result = self._run_helper(
                "send_synthetic",
                ["--session-id", session_id, "--guard-fingerprint", snapshot.fingerprint, "--input-class", "synthetic", "--text", prompt.text],
            )
            if result.get("accepted") is not True:
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "Doubao did not verify synthetic prompt submission")
            fresh = result.get("snapshot")
            if not isinstance(fresh, Mapping):
                raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "synthetic submission did not return a guarded snapshot")
            self._snapshot = self._snapshot_from_result(fresh)
            if self._snapshot.session_id != session_id:
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "synthetic submission changed session identity")
        except DoubaoDesktopError:
            # Submission is a side effect; an acknowledgement failure leaves
            # the state unknown and requires a fresh session before retrying.
            self._session_phase = "indeterminate"
            raise
        self._last_prompt_text = prompt.text
        self._cached_response = None
        self._session_phase = "submitted"
        return {"session_id": session_id, "accepted": True, "snapshot_fingerprint": self._snapshot.fingerprint}
    def wait_for_response(self, timeout_seconds: float = 30.0, poll_seconds: float = 0.25) -> DoubaoResponse:
        if timeout_seconds <= 0 or timeout_seconds > MAX_WAIT_SECONDS:
            raise ValueError("timeout_seconds must be positive and bounded")
        if poll_seconds <= 0 or poll_seconds > 5:
            raise ValueError("poll_seconds must be positive and bounded")
        if self._session_phase == "completed" and self._cached_response is not None:
            return self._cached_response
        if self._session_phase == "indeterminate":
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "the synthetic submission state is indeterminate; start a new task")
        if self._session_phase != "submitted":
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "submit one synthetic prompt before waiting for a response")
        session_id, snapshot = self._require_session(require_response=False)
        deadline = time.monotonic() + float(timeout_seconds)
        stable_text = ""
        stable_polls = 0
        while True:
            try:
                result = self._run_helper(
                    "read_response",
                    ["--session-id", session_id, "--guard-fingerprint", snapshot.fingerprint],
                    timeout=min(self.call_timeout, max(0.25, deadline - time.monotonic())),
                )
            except DoubaoDesktopError as exc:
                if exc.code != DesktopErrorCode.UI_CONTROL_UNVERIFIED.value or exc.details.get("reason") != "snapshot_changed":
                    raise
                refreshed = self.snapshot(require_controls=False)
                refreshed.require("composer", "new_task")
                snapshot = refreshed
                continue
            status = str(result.get("status") or "pending")
            returned_session = str(result.get("session_id") or "")
            if returned_session != session_id:
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "response helper changed the session identity")
            if status == "ready" and result.get("complete") is True:
                text = result.get("text")
                if not isinstance(text, str):
                    raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "ready response has no text")
                fresh = self._fresh_snapshot(result)
                if fresh is None:
                    raise DoubaoDesktopError(DesktopErrorCode.HELPER_PROTOCOL_ERROR, "ready response has no guarded snapshot")
                snapshot = fresh
                prompt = (self._last_prompt_text or "").strip()
                candidate = text.strip()
                if prompt and (candidate == prompt or prompt in candidate):
                    status = "pending"
                elif text == stable_text:
                    stable_polls += 1
                else:
                    stable_text = text
                    stable_polls = 1
                if status == "ready" and stable_polls >= RESPONSE_STABLE_POLLS:
                    response = DoubaoResponse(session_id, text, status, fresh)
                    self._cached_response = response
                    self._session_phase = "completed"
                    return response
                # A complete-looking value must remain unchanged across the
                # stability window before it can be returned.
                status = "pending"
            elif status == "ready":
                status = "pending"
            if status != "pending":
                raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "Doubao response status is unrecognized", {"status": status})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DoubaoDesktopError(DesktopErrorCode.TIMEOUT, "Doubao response did not arrive within the bounded wait", {"session_id": session_id})
            time.sleep(min(float(poll_seconds), remaining))
    def exchange(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Exchange one strict JSON prompt card after typed authorization."""
        if self.outbound_authorization is None:
            raise DoubaoDesktopError(
                DesktopErrorCode.PRIVACY_DENIED,
                "configure SyntheticOutboundAuthorization before sending a Doubao prompt card",
            )
        if not isinstance(payload, Mapping):
            raise DoubaoDesktopError(DesktopErrorCode.INVALID_REQUEST, "Doubao prompt card must be an object")
        prompt = SyntheticPrompt(json.dumps(payload, ensure_ascii=False, sort_keys=True), self.outbound_authorization)
        self.send_synthetic(prompt)
        response = self.wait_for_response()
        try:
            decoded = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "Doubao response was not strict JSON") from exc
        if not isinstance(decoded, Mapping):
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "Doubao response JSON was not an object")
        return dict(decoded)
    def _fresh_snapshot(self, result: Mapping[str, Any]) -> Optional[AXSnapshot]:
        raw = result.get("snapshot")
        if not isinstance(raw, Mapping):
            return None
        snapshot = self._snapshot_from_result(raw)
        if self._session_id and snapshot.session_id != self._session_id:
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "response snapshot changed session identity")
        self._snapshot = snapshot
        return snapshot
    def _require_session(self, *, require_response: bool = True) -> tuple[str, AXSnapshot]:
        if not self._session_id or not _SESSION_RE.fullmatch(self._session_id):
            raise DoubaoDesktopError(DesktopErrorCode.UI_CONTROL_UNVERIFIED, "start a fresh Doubao task session first")
        current = self.snapshot(require_controls=False)
        current.require("composer", "new_task")
        if require_response:
            current.require("response")
        return self._session_id, current
def _sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return ""
__all__ = (
    "AXControl",
    "AXSnapshot",
    "DesktopErrorCode",
    "DoubaoDesktopAXDriver",
    "DoubaoDesktopError",
    "DoubaoResponse",
    "SyntheticOutboundAuthorization",
    "SyntheticPrompt",
    "resolve_app_path",
    "resolve_helper_path",
)
