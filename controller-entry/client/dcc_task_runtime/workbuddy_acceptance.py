"""Independent WorkBuddy/HY3 model-run identity and conformance evidence.

This module is deliberately separate from the historical desktop-model
acceptance code.  It accepts an event trace produced by the trusted front
door, derives all case metrics from atomic events, and never trusts a model
provided summary or ``verified`` flag.  The route identity records the
WorkBuddy application selected by the user separately from evidence that a
provider exchange actually used HY3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import plistlib
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

from .canonical import canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode, now_iso


MODEL_RUN_MANIFEST_SCHEMA = "bridge.workbuddy_hy3_run/1.0"
MODEL_RUN_EVALUATION_SCHEMA = "bridge.workbuddy_hy3_evaluation/1.0"
WORKBUDDY_ROUTE_ID = "WorkBuddyDesktopRoute"
WORKBUDDY_BUNDLE_ID = "com.tencent.workbuddy.mac"
HY3_MODEL_ID = "hy3"
REQUIRED_FIRST_ROUND_CORRECT = 46

WORKBUDDY_DOMAIN_PACKS = frozenset(
    {
        "pyro_smoke_v1", "pyro_fire_v1", "particles_v1", "water_ocean_v1",
        "water_flip_v1", "crowd_agents_v1", "swarm_flocking_v1",
        "vellum_cloth_v1", "vellum_softbody_grains_v1", "hair_fur_v1",
        "rbd_destruction_v1", "procedural_geometry_v1", "material_lookdev_v1",
        "lighting_camera_render_v1", "nuke_composite_v1", "explosion_composite_v1",
    }
)
REQUIRED_SCENARIOS = frozenset({"build_inspect", "causal_candidate", "approval_recovery"})
EVENT_TYPES = frozenset(
    {
        "model_turn",
        "case_complete",
        "transport_retry",
        "dcc_retry",
        "host_retry",
        "unknown_result",
        "reconciliation_resolved",
        "cold_start_retry",
        "format_correction",
        "state_correction",
        "human_semantic_help",
        "human_authorization",
        "model_switch",
        "subagent",
        "forbidden_action",
    }
)
OBSERVERS = frozenset({"front_door", "provider", "workbuddy_runtime", "dcc", "trusted_human"})
UNTRUSTED_CLAIM_KEYS = frozenset({"passed", "verified", "case_count", "first_round_accuracy", "counts"})


def _error(code: ErrorCode, message: str, details: Optional[Mapping[str, Any]] = None) -> RuntimeV2Error:
    return RuntimeV2Error(code, message, details)


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = str(value if value is not None else "").strip()
    if not result and not allow_empty:
        raise _error(ErrorCode.INVALID_SPEC, f"{name} is required")
    return result


def _identifier(value: Any, name: str) -> str:
    result = _text(value, name)
    if len(result) > 200 or any(ord(character) < 0x20 for character in result):
        raise _error(ErrorCode.INVALID_SPEC, f"{name} is not a stable identifier")
    return result


def _digest(value: Any, name: str) -> str:
    result = _text(value, name).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise _error(ErrorCode.INVALID_SPEC, f"{name} must be a SHA-256 digest")
    return result


def _strict_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise _error(ErrorCode.INVALID_SPEC, f"{name} contains unknown fields", {"fields": unknown})


def _string_tuple(value: Any, name: str, *, digest_values: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _error(ErrorCode.INVALID_SPEC, f"{name} must be a list")
    result = tuple(
        _digest(item, f"{name}[{index}]") if digest_values else _text(item, f"{name}[{index}]")
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise _error(ErrorCode.INVALID_SPEC, f"{name} contains duplicates")
    return result


def _file_sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise _error(ErrorCode.ARTIFACT_INVALID, "identity file is missing or a symlink", {"path": str(path)})
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_symlink_component(path: Path) -> bool:
    """Return true when any component of an absolute path is a symlink."""

    absolute = path.absolute()
    current = Path(absolute.anchor)
    # macOS exposes temporary files through these stable OS aliases.  Their
    # canonicalization is not an application-bundle escape; components below
    # them are still checked and a symlink at the file itself is rejected.
    trusted_os_aliases = {Path("/var"), Path("/tmp")}
    for component in absolute.parts[1:]:
        current = current / component
        try:
            if current.is_symlink():
                if current in trusted_os_aliases:
                    continue
                return True
        except OSError:
            return True
    return False


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


class IdentityLevel(str, Enum):
    """The two intentionally separate identity claims for this route."""

    APP_SELECTED = "APP_SELECTED"
    PROVIDER_VERIFIED = "PROVIDER_VERIFIED"


@dataclass(frozen=True)
class WorkBuddyAppIdentity:
    """Identity read from WorkBuddy's own Info.plist.

    ``app_version`` is the WorkBuddy application version.  It is never
    presented as a HY3/backend version; the latter is deliberately absent
    unless a future provider evidence schema adds an independently verified
    field.
    """

    bundle_id: str
    app_version: str
    executable_name: str
    executable_path: str
    plist_path: str
    executable_sha256: Optional[str] = None
    plist_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if _text(self.bundle_id, "bundle_id") != WORKBUDDY_BUNDLE_ID:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unexpected WorkBuddy bundle id")
        _text(self.app_version, "app_version")
        executable_name = _text(self.executable_name, "executable_name")
        for value, name in ((self.executable_path, "executable_path"), (self.plist_path, "plist_path")):
            path = Path(_text(value, name)).expanduser()
            if not path.is_absolute() or ".." in path.parts:
                raise _error(ErrorCode.INVALID_SPEC, f"{name} must be an absolute, unambiguous path")
        executable_path = Path(self.executable_path)
        if executable_path.name != executable_name:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "executable path does not match Info.plist declaration")
        if Path(self.plist_path).name != "Info.plist":
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "WorkBuddy identity must come from Info.plist")
        if executable_path.exists() and (_has_symlink_component(executable_path) or executable_path.is_symlink() or not executable_path.is_file()):
            raise _error(ErrorCode.ARTIFACT_INVALID, "WorkBuddy executable must be a regular file without symlink escape")
        if self.executable_sha256 is not None:
            _digest(self.executable_sha256, "executable_sha256")
        if self.plist_sha256 is not None:
            _digest(self.plist_sha256, "plist_sha256")

    @property
    def files_structurally_valid(self) -> bool:
        """Whether both identity files are present, regular, and hash-consistent."""

        plist = Path(self.plist_path)
        executable = Path(self.executable_path)
        if (
            _has_symlink_component(plist)
            or _has_symlink_component(executable)
            or plist.is_symlink()
            or executable.is_symlink()
            or not plist.is_file()
            or not executable.is_file()
            or plist.name != "Info.plist"
            or executable.name != self.executable_name
            or plist.parent.name != "Contents"
            or executable.parent != plist.parent / "MacOS"
            or not _path_inside(executable, plist.parent.parent)
        ):
            return False
        try:
            with plist.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError, TypeError):
            return False
        if not isinstance(payload, Mapping):
            return False
        if payload.get("CFBundleIdentifier") != self.bundle_id:
            return False
        if payload.get("CFBundleExecutable") != self.executable_name:
            return False
        if self.plist_sha256 and _file_sha256(plist) != self.plist_sha256:
            return False
        if self.executable_sha256 and _file_sha256(executable) != self.executable_sha256:
            return False
        return True

    @classmethod
    def from_info_plist(
        cls,
        plist_path: Path | str,
        *,
        executable_path: Path | str | None = None,
    ) -> "WorkBuddyAppIdentity":
        """Read only the application identity; never launches the app."""

        plist = Path(plist_path).expanduser()
        if (
            not plist.is_absolute()
            or _has_symlink_component(plist)
            or plist.is_symlink()
            or not plist.is_file()
            or plist.name != "Info.plist"
            or plist.parent.name != "Contents"
        ):
            raise _error(ErrorCode.ARTIFACT_MISSING, "WorkBuddy Info.plist is missing or unsafe", {"path": str(plist)})
        try:
            with plist.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            raise _error(ErrorCode.ARTIFACT_INVALID, "WorkBuddy Info.plist is not valid", {"path": str(plist)}) from exc
        if not isinstance(payload, Mapping):
            raise _error(ErrorCode.ARTIFACT_INVALID, "WorkBuddy Info.plist must contain a dictionary")
        name = _text(payload.get("CFBundleExecutable"), "CFBundleExecutable")
        app_version = _text(
            payload.get("CFBundleShortVersionString") or payload.get("CFBundleVersion"),
            "WorkBuddy application version",
        )
        executable = Path(executable_path).expanduser() if executable_path is not None else plist.parent / "MacOS" / name
        if not executable.is_absolute() or ".." in executable.parts:
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy executable path is ambiguous")
        bundle_root = plist.parent.parent
        macos_root = plist.parent / "MacOS"
        if executable.name != name or not _path_inside(executable, bundle_root) or executable.parent != macos_root:
            raise _error(ErrorCode.ARTIFACT_INVALID, "Info.plist executable escapes the application bundle")
        if _has_symlink_component(executable) or executable.is_symlink() or not executable.is_file():
            raise _error(ErrorCode.ARTIFACT_MISSING, "Info.plist executable is not a regular file", {"path": str(executable)})
        return cls(
            bundle_id=_text(payload.get("CFBundleIdentifier"), "CFBundleIdentifier"),
            app_version=app_version,
            executable_name=name,
            executable_path=str(executable),
            plist_path=str(plist),
            executable_sha256=_file_sha256(executable),
            plist_sha256=_file_sha256(plist),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkBuddyAppIdentity":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "app identity must be an object")
        _strict_keys(
            value,
            {"bundle_id", "app_version", "executable_name", "executable_path", "plist_path", "executable_sha256", "plist_sha256"},
            "app identity",
        )
        return cls(
            bundle_id=_text(value.get("bundle_id"), "bundle_id"),
            app_version=_text(value.get("app_version"), "app_version"),
            executable_name=_text(value.get("executable_name"), "executable_name"),
            executable_path=_text(value.get("executable_path"), "executable_path"),
            plist_path=_text(value.get("plist_path"), "plist_path"),
            executable_sha256=_digest(value["executable_sha256"], "executable_sha256") if value.get("executable_sha256") else None,
            plist_sha256=_digest(value["plist_sha256"], "plist_sha256") if value.get("plist_sha256") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "app_version": self.app_version,
            "executable_name": self.executable_name,
            "executable_path": self.executable_path,
            "plist_path": self.plist_path,
            "executable_sha256": self.executable_sha256,
            "plist_sha256": self.plist_sha256,
        }


@dataclass(frozen=True)
class HY3ProviderEvidence:
    """A provider exchange witness; it contains no invented backend version."""

    session_id: str
    exchange_id: str
    model_name: str
    endpoint: str
    request_sha256: str
    capability_probe_sha256: str
    provider_response_sha256: str
    witness_path: Optional[str] = None
    witness_sha256: Optional[str] = None
    trusted_entry_id: Optional[str] = None
    trusted_entry_sha256: Optional[str] = None
    observed_by: str = "provider"

    def __post_init__(self) -> None:
        _identifier(self.session_id, "provider_evidence.session_id")
        _identifier(self.exchange_id, "provider_evidence.exchange_id")
        if _text(self.model_name, "provider_evidence.model_name").casefold() != HY3_MODEL_ID:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "provider evidence is not for HY3")
        _local_endpoint(self.endpoint)
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.capability_probe_sha256, "capability_probe_sha256"),
            (self.provider_response_sha256, "provider_response_sha256"),
        ):
            _digest(value, f"provider_evidence.{name}")
        witness_fields = (
            self.witness_path,
            self.witness_sha256,
            self.trusted_entry_id,
            self.trusted_entry_sha256,
        )
        if any(field is not None for field in witness_fields) and not all(field is not None for field in witness_fields):
            raise _error(
                ErrorCode.INVALID_SPEC,
                "provider evidence witness fields must be supplied together",
            )
        if self.witness_path is not None:
            witness_path = Path(_text(self.witness_path, "provider_evidence.witness_path")).expanduser()
            if not witness_path.is_absolute() or ".." in witness_path.parts:
                raise _error(ErrorCode.INVALID_SPEC, "provider evidence witness path must be absolute and unambiguous")
            _digest(self.witness_sha256, "provider_evidence.witness_sha256")
            _identifier(self.trusted_entry_id, "provider_evidence.trusted_entry_id")
            _digest(self.trusted_entry_sha256, "provider_evidence.trusted_entry_sha256")
            if _has_symlink_component(witness_path) or witness_path.is_symlink():
                raise _error(ErrorCode.ARTIFACT_INVALID, "provider evidence witness may not use symlink escape")
            if witness_path.exists() and not witness_path.is_file():
                raise _error(ErrorCode.ARTIFACT_INVALID, "provider evidence witness must be a regular file")
        if self.observed_by not in {"provider", "front_door", "workbuddy_runtime"}:
            raise _error(ErrorCode.POLICY_DENIED, "provider evidence cannot be self-reported by the model")

    @property
    def witness_structurally_valid(self) -> bool:
        """Check local witness shape; this does not prove its trusted origin."""

        if not all(
            field is not None
            for field in (self.witness_path, self.witness_sha256, self.trusted_entry_id, self.trusted_entry_sha256)
        ):
            return False
        try:
            witness_path = Path(self.witness_path).expanduser()
            return (
                witness_path.is_absolute()
                and ".." not in witness_path.parts
                and not _has_symlink_component(witness_path)
                and not witness_path.is_symlink()
                and witness_path.is_file()
                and _file_sha256(witness_path) == self.witness_sha256
            )
        except (OSError, RuntimeV2Error, TypeError):
            return False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HY3ProviderEvidence":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "provider evidence must be an object")
        _strict_keys(
            value,
            {
                "session_id", "exchange_id", "model_name", "endpoint", "request_sha256", "capability_probe_sha256",
                "provider_response_sha256", "witness_path", "witness_sha256", "trusted_entry_id", "trusted_entry_sha256",
                "observed_by",
            },
            "provider evidence",
        )
        return cls(
            session_id=_text(value.get("session_id"), "provider_evidence.session_id"),
            exchange_id=_text(value.get("exchange_id"), "provider_evidence.exchange_id"),
            model_name=_text(value.get("model_name"), "provider_evidence.model_name"),
            endpoint=_text(value.get("endpoint"), "provider_evidence.endpoint"),
            request_sha256=_digest(value.get("request_sha256"), "provider_evidence.request_sha256"),
            capability_probe_sha256=_digest(value.get("capability_probe_sha256"), "provider_evidence.capability_probe_sha256"),
            provider_response_sha256=_digest(value.get("provider_response_sha256"), "provider_evidence.provider_response_sha256"),
            witness_path=_text(value.get("witness_path"), "provider_evidence.witness_path") if value.get("witness_path") is not None else None,
            witness_sha256=_digest(value["witness_sha256"], "provider_evidence.witness_sha256") if value.get("witness_sha256") is not None else None,
            trusted_entry_id=_identifier(value["trusted_entry_id"], "provider_evidence.trusted_entry_id") if value.get("trusted_entry_id") is not None else None,
            trusted_entry_sha256=_digest(value["trusted_entry_sha256"], "provider_evidence.trusted_entry_sha256") if value.get("trusted_entry_sha256") is not None else None,
            observed_by=_text(value.get("observed_by") or "provider", "provider_evidence.observed_by"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "exchange_id": self.exchange_id,
            "model_name": self.model_name,
            "endpoint": self.endpoint,
            "request_sha256": self.request_sha256,
            "capability_probe_sha256": self.capability_probe_sha256,
            "provider_response_sha256": self.provider_response_sha256,
            "witness_path": self.witness_path,
            "witness_sha256": self.witness_sha256,
            "trusted_entry_id": self.trusted_entry_id,
            "trusted_entry_sha256": self.trusted_entry_sha256,
            "observed_by": self.observed_by,
        }


def _local_endpoint(value: str) -> str:
    endpoint = _text(value, "endpoint")
    parsed = urlparse(endpoint)
    if parsed.scheme in {"stdio", "mcp"}:
        if parsed.netloc not in {"", "workbuddy"}:
            raise _error(ErrorCode.POLICY_DENIED, "WorkBuddy route endpoint is not local")
        return endpoint
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise _error(ErrorCode.POLICY_DENIED, "WorkBuddy HY3 endpoint must be local")
    if parsed.username or parsed.password:
        raise _error(ErrorCode.POLICY_DENIED, "provider endpoint must not contain credentials")
    return endpoint


@dataclass(frozen=True)
class WorkBuddyHY3Route:
    """A route constrained to the selected WorkBuddy application and HY3."""

    app: WorkBuddyAppIdentity
    session_id: str
    selected_model: str = HY3_MODEL_ID
    identity_level: IdentityLevel = IdentityLevel.APP_SELECTED
    provider_evidence: Optional[HY3ProviderEvidence] = None
    route_id: str = WORKBUDDY_ROUTE_ID

    def __post_init__(self) -> None:
        if not isinstance(self.app, WorkBuddyAppIdentity):
            if isinstance(self.app, Mapping):
                object.__setattr__(self, "app", WorkBuddyAppIdentity.from_mapping(self.app))
            else:
                raise _error(ErrorCode.INVALID_SPEC, "route.app must be a WorkBuddy application identity")
        if self.provider_evidence is not None and not isinstance(self.provider_evidence, HY3ProviderEvidence):
            if isinstance(self.provider_evidence, Mapping):
                object.__setattr__(self, "provider_evidence", HY3ProviderEvidence.from_mapping(self.provider_evidence))
            else:
                raise _error(ErrorCode.INVALID_SPEC, "route.provider_evidence must be an object or null")
        if self.route_id != WORKBUDDY_ROUTE_ID:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unexpected WorkBuddy route id")
        if _text(self.selected_model, "selected_model").casefold() != HY3_MODEL_ID:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "WorkBuddy route is restricted to HY3")
        _identifier(self.session_id, "route.session_id")
        if not isinstance(self.identity_level, IdentityLevel):
            try:
                object.__setattr__(self, "identity_level", IdentityLevel(str(self.identity_level)))
            except ValueError as exc:
                raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unknown WorkBuddy identity level") from exc
        if self.identity_level is IdentityLevel.APP_SELECTED and self.provider_evidence is not None:
            raise _error(ErrorCode.INVALID_SPEC, "APP_SELECTED route may not carry provider verification")
        if self.identity_level is IdentityLevel.PROVIDER_VERIFIED:
            if self.provider_evidence is None:
                raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "PROVIDER_VERIFIED requires provider evidence")
            if self.provider_evidence.session_id != self.session_id:
                raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "provider evidence session does not match route session")
            if not self.provider_evidence.witness_structurally_valid:
                raise _error(
                    ErrorCode.ARTIFACT_INVALID,
                    "PROVIDER_VERIFIED requires a present, hash-consistent provider witness",
                )
            if not self.app.files_structurally_valid:
                raise _error(
                    ErrorCode.ARTIFACT_INVALID,
                    "PROVIDER_VERIFIED requires a present, hash-consistent WorkBuddy identity",
                )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkBuddyHY3Route":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy route must be an object")
        _strict_keys(value, {"route_id", "app", "session_id", "selected_model", "identity_level", "provider_evidence"}, "WorkBuddy route")
        raw_evidence = value.get("provider_evidence")
        evidence = HY3ProviderEvidence.from_mapping(raw_evidence) if isinstance(raw_evidence, Mapping) else None
        if raw_evidence is not None and evidence is None:
            raise _error(ErrorCode.INVALID_SPEC, "provider_evidence must be an object or null")
        return cls(
            route_id=_text(value.get("route_id"), "route_id"),
            app=WorkBuddyAppIdentity.from_mapping(value.get("app") or {}),
            session_id=_text(value.get("session_id"), "route.session_id"),
            selected_model=_text(value.get("selected_model") or HY3_MODEL_ID, "selected_model"),
            identity_level=IdentityLevel(_text(value.get("identity_level"), "identity_level")),
            provider_evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "app": self.app.to_dict(),
            "session_id": self.session_id,
            "selected_model": self.selected_model,
            "identity_level": self.identity_level.value,
            "provider_evidence": self.provider_evidence.to_dict() if self.provider_evidence else None,
        }

    @property
    def app_selected(self) -> bool:
        return self.identity_level is IdentityLevel.APP_SELECTED

    @property
    def provider_verified(self) -> bool:
        return self.identity_level is IdentityLevel.PROVIDER_VERIFIED


@dataclass(frozen=True)
class ModelRoundEvent:
    """One atomic event from a WorkBuddy run.

    Retry and correction metrics are derived by counting event types.  There
    are intentionally no retry/count/verified aggregate fields here.
    """

    event_id: str
    event_type: str
    run_id: str
    session_id: str
    case_id: str
    domain_pack: str
    scenario: str
    round_index: int
    observed_by: str
    model: Optional[str] = None
    action_id: Optional[str] = None
    expected_action_id: Optional[str] = None
    action_allowed: Optional[bool] = None
    expected_final_state: Optional[str] = None
    observed_final_state: Optional[str] = None
    from_model: Optional[str] = None
    to_model: Optional[str] = None
    declared_subagent: Optional[bool] = None
    tool_call_id: Optional[str] = None
    provider_response_sha256: Optional[str] = None
    reference_hashes: tuple[str, ...] = ()
    media_parts: tuple[str, ...] = ()
    attempt_index: int = 1
    decision_id: Optional[str] = None
    graph_id: Optional[str] = None
    operation_id: Optional[str] = None
    artifact_ids: tuple[str, ...] = ()
    error_code: Optional[str] = None
    authorization_id: Optional[str] = None
    proposal_id: Optional[str] = None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        if self.event_type not in EVENT_TYPES:
            raise _error(ErrorCode.INVALID_SPEC, "unknown WorkBuddy event type", {"event_type": self.event_type})
        _identifier(self.run_id, "event.run_id")
        _identifier(self.session_id, "event.session_id")
        _identifier(self.case_id, "case_id")
        if self.domain_pack not in WORKBUDDY_DOMAIN_PACKS:
            raise _error(ErrorCode.UNSUPPORTED_DOMAIN, "unknown WorkBuddy conformance domain", {"domain_pack": self.domain_pack})
        if self.scenario not in REQUIRED_SCENARIOS:
            raise _error(ErrorCode.INVALID_SPEC, "unknown WorkBuddy conformance scenario", {"scenario": self.scenario})
        if type(self.round_index) is not int or self.round_index < 1:
            raise _error(ErrorCode.INVALID_SPEC, "event.round_index must be a positive integer")
        if type(self.attempt_index) is not int or self.attempt_index < 1:
            raise _error(ErrorCode.INVALID_SPEC, "event.attempt_index must be a positive integer")
        if self.observed_by not in OBSERVERS or self.observed_by == "model":
            raise _error(ErrorCode.POLICY_DENIED, "event cannot be self-reported by the model")
        if self.provider_response_sha256 is not None:
            _digest(self.provider_response_sha256, "event.provider_response_sha256")
        if any(media not in {"image", "video", "image_url", "video_url"} for media in self.media_parts):
            raise _error(ErrorCode.INVALID_SPEC, "event.media_parts contains an unknown media part type")
        if self.event_type == "model_turn":
            if not self.model or not self.action_id or not self.expected_action_id or type(self.action_allowed) is not bool:
                raise _error(ErrorCode.INVALID_SPEC, "model_turn requires model, action, expected action, and allowed outcome")
        if self.event_type == "case_complete":
            if not self.expected_final_state or not self.observed_final_state:
                raise _error(ErrorCode.INVALID_SPEC, "case_complete requires expected and observed final states")
        if self.event_type == "model_switch" and (not self.from_model or not self.to_model):
            raise _error(ErrorCode.INVALID_SPEC, "model_switch requires from_model and to_model")
        if self.event_type == "subagent" and type(self.declared_subagent) is not bool:
            raise _error(ErrorCode.INVALID_SPEC, "subagent requires declared_subagent")
        if self.event_type in {"human_authorization", "human_semantic_help"} and self.observed_by != "trusted_human":
            raise _error(ErrorCode.POLICY_DENIED, "human events must be observed by the trusted human channel")
        if self.event_type == "forbidden_action" and not self.action_id:
            raise _error(ErrorCode.INVALID_SPEC, "forbidden_action requires action_id")
        if self.event_type == "reconciliation_resolved" and not self.operation_id:
            raise _error(ErrorCode.INVALID_SPEC, "reconciliation_resolved requires operation_id")
        if self.event_type == "human_authorization" and not self.authorization_id:
            raise _error(ErrorCode.INVALID_SPEC, "human_authorization requires authorization_id")
        for value, name in (
            (self.tool_call_id, "event.tool_call_id"),
            (self.decision_id, "event.decision_id"),
            (self.graph_id, "event.graph_id"),
            (self.operation_id, "event.operation_id"),
            (self.authorization_id, "event.authorization_id"),
            (self.proposal_id, "event.proposal_id"),
        ):
            if value is not None:
                _identifier(value, name)
        for index, artifact_id in enumerate(self.artifact_ids):
            _identifier(artifact_id, f"event.artifact_ids[{index}]")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise _error(ErrorCode.INVALID_SPEC, "event.artifact_ids must not contain duplicates")
        if self.error_code is not None:
            code = _text(self.error_code, "event.error_code")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
                raise _error(ErrorCode.INVALID_SPEC, "event.error_code must be a structured code, not arbitrary diagnostic text")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelRoundEvent":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy event must be an object")
        allowed = {
            "event_id", "event_type", "kind", "run_id", "session_id", "case_id", "domain_pack", "scenario", "round_index",
            "observed_by", "model", "action_id", "expected_action_id", "action_allowed", "expected_final_state",
            "observed_final_state", "from_model", "to_model", "declared_subagent", "tool_call_id", "provider_response_sha256",
            "reference_hashes", "media_parts", "attempt_index", "decision_id", "graph_id", "operation_id",
            "artifact_ids", "error_code", "authorization_id", "proposal_id",
        }
        _strict_keys(value, allowed, "WorkBuddy event")
        if value.get("event_type") and value.get("kind") and value.get("event_type") != value.get("kind"):
            raise _error(ErrorCode.INVALID_SPEC, "event_type and kind disagree")
        event_type = value.get("event_type") or value.get("kind")
        if not event_type:
            raise _error(ErrorCode.INVALID_SPEC, "event_type is required")
        action_allowed = value.get("action_allowed")
        if action_allowed is not None and type(action_allowed) is not bool:
            raise _error(ErrorCode.INVALID_SPEC, "event.action_allowed must be boolean")
        declared = value.get("declared_subagent")
        if declared is not None and type(declared) is not bool:
            raise _error(ErrorCode.INVALID_SPEC, "event.declared_subagent must be boolean")
        return cls(
            event_id=_text(value.get("event_id"), "event_id"),
            event_type=_text(event_type, "event_type"),
            run_id=_text(value.get("run_id"), "event.run_id"),
            session_id=_text(value.get("session_id"), "event.session_id"),
            case_id=_text(value.get("case_id"), "case_id"),
            domain_pack=_text(value.get("domain_pack"), "domain_pack"),
            scenario=_text(value.get("scenario"), "scenario"),
            round_index=value.get("round_index"),
            observed_by=_text(value.get("observed_by"), "observed_by"),
            model=_text(value.get("model"), "model") if value.get("model") is not None else None,
            action_id=_text(value.get("action_id"), "action_id") if value.get("action_id") is not None else None,
            expected_action_id=_text(value.get("expected_action_id"), "expected_action_id") if value.get("expected_action_id") is not None else None,
            action_allowed=action_allowed,
            expected_final_state=_text(value.get("expected_final_state"), "expected_final_state") if value.get("expected_final_state") is not None else None,
            observed_final_state=_text(value.get("observed_final_state"), "observed_final_state") if value.get("observed_final_state") is not None else None,
            from_model=_text(value.get("from_model"), "from_model") if value.get("from_model") is not None else None,
            to_model=_text(value.get("to_model"), "to_model") if value.get("to_model") is not None else None,
            declared_subagent=declared,
            tool_call_id=_text(value.get("tool_call_id"), "tool_call_id") if value.get("tool_call_id") is not None else None,
            provider_response_sha256=_digest(value["provider_response_sha256"], "event.provider_response_sha256") if value.get("provider_response_sha256") else None,
            reference_hashes=_string_tuple(value.get("reference_hashes"), "event.reference_hashes", digest_values=True),
            media_parts=_string_tuple(value.get("media_parts"), "event.media_parts"),
            attempt_index=value.get("attempt_index", 1),
            decision_id=_text(value.get("decision_id"), "decision_id") if value.get("decision_id") is not None else None,
            graph_id=_text(value.get("graph_id"), "graph_id") if value.get("graph_id") is not None else None,
            operation_id=_text(value.get("operation_id"), "operation_id") if value.get("operation_id") is not None else None,
            artifact_ids=_string_tuple(value.get("artifact_ids"), "event.artifact_ids"),
            error_code=_text(value.get("error_code"), "error_code") if value.get("error_code") is not None else None,
            authorization_id=_text(value.get("authorization_id"), "authorization_id") if value.get("authorization_id") is not None else None,
            proposal_id=_text(value.get("proposal_id"), "proposal_id") if value.get("proposal_id") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "domain_pack": self.domain_pack,
            "scenario": self.scenario,
            "round_index": self.round_index,
            "observed_by": self.observed_by,
            "model": self.model,
            "action_id": self.action_id,
            "expected_action_id": self.expected_action_id,
            "action_allowed": self.action_allowed,
            "expected_final_state": self.expected_final_state,
            "observed_final_state": self.observed_final_state,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "declared_subagent": self.declared_subagent,
            "tool_call_id": self.tool_call_id,
            "provider_response_sha256": self.provider_response_sha256,
            "reference_hashes": list(self.reference_hashes),
            "media_parts": list(self.media_parts),
            "attempt_index": self.attempt_index,
            "decision_id": self.decision_id,
            "graph_id": self.graph_id,
            "operation_id": self.operation_id,
            "artifact_ids": list(self.artifact_ids),
            "error_code": self.error_code,
            "authorization_id": self.authorization_id,
            "proposal_id": self.proposal_id,
        }


@dataclass(frozen=True)
class ModelRunManifest:
    """Versioned, serializable WorkBuddy event manifest."""

    run_id: str
    task_id: str
    spec_hash: str
    route: WorkBuddyHY3Route
    events: tuple[ModelRoundEvent, ...]
    input_class: str = "synthetic"
    created_at: str = field(default_factory=now_iso)
    untrusted_claims: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.task_id, "task_id")
        _digest(self.spec_hash, "spec_hash")
        if self.input_class != "synthetic":
            raise _error(ErrorCode.POLICY_DENIED, "WorkBuddy acceptance input must be synthetic")
        if not isinstance(self.events, tuple) or not self.events:
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy run requires atomic events")
        if not isinstance(self.route, WorkBuddyHY3Route):
            raise _error(ErrorCode.INVALID_SPEC, "route must be a WorkBuddyHY3Route")
        if any(not isinstance(event, ModelRoundEvent) for event in self.events):
            raise _error(ErrorCode.INVALID_SPEC, "events must contain ModelRoundEvent objects")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy event IDs must be unique")
        case_ids: dict[tuple[str, str], str] = {}
        case_keys: dict[str, tuple[str, str]] = {}
        turn_rounds: dict[tuple[str, str], set[int]] = {}
        for event in self.events:
            if event.run_id != self.run_id or event.session_id != self.route.session_id:
                raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "event is not bound to the manifest run/session")
            key = (event.domain_pack, event.scenario)
            previous_case_id = case_ids.setdefault(key, event.case_id)
            if previous_case_id != event.case_id:
                raise _error(ErrorCode.INVALID_SPEC, "one domain/scenario may contain only one case_id")
            previous_key = case_keys.setdefault(event.case_id, key)
            if previous_key != key:
                raise _error(ErrorCode.INVALID_SPEC, "case_id is reused across domain/scenario cases")
            if event.event_type == "model_turn":
                rounds = turn_rounds.setdefault((event.domain_pack, event.scenario, event.attempt_index), set())
                if event.round_index in rounds:
                    raise _error(ErrorCode.INVALID_SPEC, "model_turn round indexes must be unique within a case")
                rounds.add(event.round_index)
        if not isinstance(self.untrusted_claims, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "untrusted_claims must be an object")
        # Claims are retained only for audit visibility.  They are never used
        # by evaluate_model_run, and status-like claim keys are rejected.
        if any(str(key) in UNTRUSTED_CLAIM_KEYS for key in self.untrusted_claims):
            raise _error(ErrorCode.POLICY_DENIED, "status/count claims are not accepted as model evidence")
        try:
            json_value(self.to_dict(include_manifest_hash=False))
        except (TypeError, ValueError) as exc:
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy manifest is not strictly serializable") from exc

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelRunManifest":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy manifest must be an object")
        allowed = {
            "schema", "run_id", "task_id", "spec_hash", "route", "events", "input_class", "created_at", "untrusted_claims", "manifest_sha256",
        }
        _strict_keys(value, allowed, "WorkBuddy manifest")
        if value.get("schema") != MODEL_RUN_MANIFEST_SCHEMA:
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unknown WorkBuddy manifest schema")
        raw_events = value.get("events")
        if not isinstance(raw_events, list):
            raise _error(ErrorCode.INVALID_SPEC, "WorkBuddy manifest events must be a list")
        events = tuple(ModelRoundEvent.from_mapping(item) for item in raw_events)
        raw_claims = value.get("untrusted_claims")
        if raw_claims is None:
            raw_claims = {}
        if not isinstance(raw_claims, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "untrusted_claims must be an object")
        manifest = cls(
            run_id=_text(value.get("run_id"), "run_id"),
            task_id=_text(value.get("task_id"), "task_id"),
            spec_hash=_digest(value.get("spec_hash"), "spec_hash"),
            route=WorkBuddyHY3Route.from_mapping(value.get("route") or {}),
            events=events,
            input_class=_text(value.get("input_class") or "synthetic", "input_class"),
            created_at=_text(value.get("created_at") or now_iso(), "created_at"),
            untrusted_claims=dict(raw_claims),
        )
        supplied = value.get("manifest_sha256")
        if supplied is not None and _digest(supplied, "manifest_sha256") != manifest.manifest_sha256:
            raise _error(ErrorCode.ARTIFACT_INVALID, "manifest_sha256 does not match atomic contents")
        return manifest

    @property
    def manifest_sha256(self) -> str:
        return canonical_sha256(self.to_dict(include_manifest_hash=False))

    def to_dict(self, *, include_manifest_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": MODEL_RUN_MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "spec_hash": self.spec_hash,
            "route": self.route.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "input_class": self.input_class,
            "created_at": self.created_at,
            "untrusted_claims": json_value(self.untrusted_claims),
        }
        if include_manifest_hash:
            payload["manifest_sha256"] = canonical_sha256(payload)
        return payload


@dataclass(frozen=True)
class _CaseOutcome:
    case_id: str
    domain_pack: str
    scenario: str
    first_round_correct: bool
    final_completed: bool
    rule_compliant: bool
    model_decisions: int
    format_corrections: int
    state_corrections: int
    transport_retries: int
    host_retries: int
    dcc_retries: int
    unknown_results: int
    cold_start_retries: int
    attempt_count: int
    human_semantic_help: int
    model_switches: int
    undeclared_subagents: int
    forbidden_action_attempts: int
    missing_tool_evidence: int
    missing_reference_media: int
    graph_ids: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    human_authorization_ids: tuple[str, ...] = ()
    model_proposal_ids: tuple[str, ...] = ()
    structured_errors: tuple[dict[str, str], ...] = ()
    attempt_history: tuple[dict[str, Any], ...] = ()
    error: Optional[str] = None

    @property
    def correction_turns(self) -> int:
        return self.format_corrections + self.state_corrections

    @property
    def passed(self) -> bool:
        return (
            self.first_round_correct
            and self.final_completed
            and self.rule_compliant
            and self.unknown_results == 0
            and self.correction_turns <= 2
            and self.human_semantic_help == 0
            and self.model_switches == 0
            and self.undeclared_subagents == 0
            and self.forbidden_action_attempts == 0
            and self.missing_tool_evidence == 0
            and self.missing_reference_media == 0
            and self.error is None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "domain_pack": self.domain_pack,
            "scenario": self.scenario,
            "first_round_correct": self.first_round_correct,
            "final_completed": self.final_completed,
            "rule_compliant": self.rule_compliant,
            "model_decisions": self.model_decisions,
            "format_corrections": self.format_corrections,
            "state_corrections": self.state_corrections,
            "correction_turns": self.correction_turns,
            "transport_retries": self.transport_retries,
            "host_retries": self.host_retries,
            "dcc_retries": self.dcc_retries,
            "unknown_results": self.unknown_results,
            "cold_start_retries": self.cold_start_retries,
            "attempt_count": self.attempt_count,
            "human_semantic_help": self.human_semantic_help,
            "model_switches": self.model_switches,
            "undeclared_subagents": self.undeclared_subagents,
            "forbidden_action_attempts": self.forbidden_action_attempts,
            "missing_tool_evidence": self.missing_tool_evidence,
            "missing_reference_media": self.missing_reference_media,
            "trace": {
                "graph_ids": list(self.graph_ids),
                "operation_ids": list(self.operation_ids),
                "action_ids": list(self.action_ids),
                "artifact_ids": list(self.artifact_ids),
            },
            "human_authorization_ids": list(self.human_authorization_ids),
            "model_proposal_ids": list(self.model_proposal_ids),
            "structured_errors": [dict(item) for item in self.structured_errors],
            "attempt_history": [dict(item) for item in self.attempt_history],
            "passed": self.passed,
            "error": self.error,
        }


def _case_keys() -> tuple[tuple[str, str], ...]:
    return tuple((pack, scenario) for pack in sorted(WORKBUDDY_DOMAIN_PACKS) for scenario in sorted(REQUIRED_SCENARIOS))


def _events_by_case(manifest: ModelRunManifest) -> dict[tuple[str, str], list[ModelRoundEvent]]:
    grouped: dict[tuple[str, str], list[ModelRoundEvent]] = {}
    for event in manifest.events:
        grouped.setdefault((event.domain_pack, event.scenario), []).append(event)
    return grouped


def _evaluate_case(key: tuple[str, str], events: Sequence[ModelRoundEvent], route: WorkBuddyHY3Route) -> _CaseOutcome:
    domain, scenario = key
    case_id = next((event.case_id for event in events), f"{domain}:{scenario}")
    ordered = sorted(events, key=lambda event: (event.attempt_index, event.round_index, event.event_id))
    raw_turns = [event for event in ordered if event.event_type == "model_turn"]

    # Transport retries can replay the same front-door decision.  Count one
    # semantic model decision per trusted decision/tool identifier; a duplicate
    # carrying different semantics is a rule/evidence failure rather than a way
    # to overwrite the previous decision.
    decisions: list[ModelRoundEvent] = []
    seen_decisions: dict[tuple[int, str], ModelRoundEvent] = {}
    duplicate_conflict = False
    duplicate_conflict_attempts: set[int] = set()
    for turn in raw_turns:
        # A cold-start attempt is a new decision namespace.  Transport replay
        # within the same attempt keeps the same decision/tool identifier and
        # is counted once; reusing that identifier in a later attempt is a new
        # model decision rather than an accidental global dedupe.
        decision_key = (turn.attempt_index, turn.decision_id or turn.tool_call_id or turn.event_id)
        prior = seen_decisions.get(decision_key)
        if prior is None:
            seen_decisions[decision_key] = turn
            decisions.append(turn)
            continue
        if (prior.action_id, prior.expected_action_id, prior.action_allowed, prior.model) != (
            turn.action_id, turn.expected_action_id, turn.action_allowed, turn.model
        ):
            duplicate_conflict = True
            duplicate_conflict_attempts.add(turn.attempt_index)

    first_correct = bool(
        decisions
        and decisions[0].action_id == decisions[0].expected_action_id
        and decisions[0].action_allowed is True
    )
    explicit_forbidden = sum(event.event_type == "forbidden_action" for event in events)
    blocked_turns = sum(turn.action_allowed is False for turn in decisions)
    forbidden = explicit_forbidden + blocked_turns
    # Rule compliance is distinct from task correctness: a wrong but allowed
    # first decision may be corrected within the acceptance budget, while any
    # blocked/unauthorized action is a rule failure even if a later turn works.
    rule_compliant = bool(decisions) and not duplicate_conflict and forbidden == 0 and all(
        turn.action_allowed is True for turn in decisions
    )

    attempts = sorted({event.attempt_index for event in events}) or [1]
    latest_attempt = attempts[-1]
    latest_events = [event for event in events if event.attempt_index == latest_attempt]
    latest_completions = [event for event in latest_events if event.event_type == "case_complete"]

    ordered_positions = {event.event_id: index for index, event in enumerate(ordered)}
    resolutions: dict[str, list[int]] = {}
    for event in ordered:
        if event.event_type == "reconciliation_resolved" and event.operation_id:
            resolutions.setdefault(event.operation_id, []).append(ordered_positions[event.event_id])
    unresolved_unknown_events = []
    for event in ordered:
        if event.event_type != "unknown_result":
            continue
        position = ordered_positions[event.event_id]
        if not event.operation_id or not any(item > position for item in resolutions.get(event.operation_id, ())):
            unresolved_unknown_events.append(event)
    latest_unknown = sum(event.attempt_index == latest_attempt for event in unresolved_unknown_events)
    final_completed = bool(
        len(latest_completions) == 1
        and latest_completions[0].expected_final_state == latest_completions[0].observed_final_state
        and latest_unknown == 0
    )

    errors: list[str] = []
    structured_errors: list[dict[str, str]] = []
    if not decisions:
        errors.append("missing model_turn")
    if duplicate_conflict:
        errors.append("duplicate decision identifier changed semantics")
        structured_errors.append({"code": "DUPLICATE_DECISION_CONFLICT", "event_id": case_id})
    if len(latest_completions) != 1:
        errors.append("latest attempt requires exactly one case_complete event")
    if any(turn.model.casefold() != HY3_MODEL_ID for turn in decisions if turn.model):
        errors.append("model turn is outside the HY3 route")
    for event in events:
        if event.error_code:
            structured_errors.append({"code": event.error_code, "event_id": event.event_id})

    format_corrections = sum(event.event_type == "format_correction" for event in events)
    state_corrections = sum(event.event_type == "state_correction" for event in events)
    transport_retries = sum(event.event_type == "transport_retry" for event in events)
    dcc_retries = sum(event.event_type == "dcc_retry" for event in events)
    host_retries = dcc_retries + sum(event.event_type == "host_retry" for event in events)
    historical_unknown_results = sum(event.event_type == "unknown_result" for event in events)
    unknown_results = len(unresolved_unknown_events)
    explicit_cold = sum(event.event_type == "cold_start_retry" for event in events)
    cold_start_retries = max(explicit_cold, max(0, len(attempts) - 1))
    human_help = sum(event.event_type == "human_semantic_help" for event in events)
    model_switches = sum(event.event_type == "model_switch" for event in events)
    model_switches += sum(turn.model and turn.model.casefold() != HY3_MODEL_ID for turn in decisions)
    undeclared_subagents = sum(event.event_type == "subagent" and event.declared_subagent is False for event in events)
    missing_tool = sum(not turn.tool_call_id or not turn.provider_response_sha256 for turn in decisions)
    media_evidence = sum(
        bool(turn.reference_hashes)
        and bool(set(turn.media_parts) & {"image", "video", "image_url", "video_url"})
        for turn in decisions
    )
    missing_media = 1 if scenario == "causal_candidate" and media_evidence == 0 else 0
    if missing_media:
        errors.append("causal_candidate lacks an observed reference-media event")
    if missing_tool:
        errors.append("model_turn lacks a provider/tool receipt")
    if unknown_results:
        errors.append("one or more execution outcomes remain unknown")

    attempt_history: list[dict[str, Any]] = []
    for attempt in attempts:
        attempt_events = [event for event in events if event.attempt_index == attempt]
        attempt_turns = [turn for turn in decisions if turn.attempt_index == attempt]
        completions = [event for event in attempt_events if event.event_type == "case_complete"]
        unresolved_in_attempt = sum(event.attempt_index == attempt for event in unresolved_unknown_events)
        blocked_in_attempt = sum(turn.action_allowed is False for turn in attempt_turns)
        forbidden_in_attempt = sum(event.event_type == "forbidden_action" for event in attempt_events) + blocked_in_attempt
        attempt_rule_compliant = bool(attempt_turns) and attempt not in duplicate_conflict_attempts and forbidden_in_attempt == 0 and all(
            turn.action_allowed is True for turn in attempt_turns
        )
        final_state_matched = bool(
            len(completions) == 1 and completions[0].expected_final_state == completions[0].observed_final_state
        )
        attempt_missing_tool = sum(not turn.tool_call_id or not turn.provider_response_sha256 for turn in attempt_turns)
        attempt_missing_media = 1 if scenario == "causal_candidate" and not any(
            bool(turn.reference_hashes) and bool(set(turn.media_parts) & {"image", "video", "image_url", "video_url"})
            for turn in attempt_turns
        ) else 0
        attempt_first_correct = bool(
            attempt_turns and attempt_turns[0].action_id == attempt_turns[0].expected_action_id and attempt_turns[0].action_allowed is True
        )
        attempt_passed = bool(
            attempt_first_correct and final_state_matched and attempt_rule_compliant and unresolved_in_attempt == 0
            and sum(event.event_type in {"format_correction", "state_correction"} for event in attempt_events) <= 2
            and not any(event.event_type in {"human_semantic_help", "model_switch", "subagent"} for event in attempt_events)
            and attempt_missing_tool == 0 and attempt_missing_media == 0
        )
        attempt_history.append(
            {
                "attempt_index": attempt,
                "model_decisions": len(attempt_turns),
                "historical_unknown_results": sum(event.event_type == "unknown_result" for event in attempt_events),
                "unknown_results": unresolved_in_attempt,
                "completion_events": len(completions),
                "final_state_matched": final_state_matched,
                "rule_compliant": attempt_rule_compliant,
                "passed": attempt_passed,
            }
        )

    return _CaseOutcome(
        case_id=case_id,
        domain_pack=domain,
        scenario=scenario,
        first_round_correct=first_correct,
        final_completed=final_completed,
        rule_compliant=rule_compliant,
        model_decisions=len(decisions),
        format_corrections=format_corrections,
        state_corrections=state_corrections,
        transport_retries=transport_retries,
        host_retries=host_retries,
        dcc_retries=dcc_retries,
        unknown_results=unknown_results,
        cold_start_retries=cold_start_retries,
        attempt_count=len(attempts),
        human_semantic_help=human_help,
        model_switches=model_switches,
        undeclared_subagents=undeclared_subagents,
        forbidden_action_attempts=forbidden,
        missing_tool_evidence=missing_tool,
        missing_reference_media=missing_media,
        graph_ids=tuple(sorted({event.graph_id for event in events if event.graph_id})),
        operation_ids=tuple(sorted({event.operation_id for event in events if event.operation_id})),
        action_ids=tuple(sorted({event.action_id for event in events if event.action_id})),
        artifact_ids=tuple(sorted({item for event in events for item in event.artifact_ids})),
        human_authorization_ids=tuple(sorted({event.authorization_id for event in events if event.event_type == "human_authorization" and event.authorization_id})),
        model_proposal_ids=tuple(sorted({event.proposal_id for event in decisions if event.proposal_id})),
        structured_errors=tuple(structured_errors),
        attempt_history=tuple(attempt_history),
        error="; ".join(errors) if errors else None,
    )


def evaluate_model_run(
    manifest: ModelRunManifest | Mapping[str, Any],
    *,
    route_witness_verifier: Optional[Callable[[WorkBuddyHY3Route, ModelRunManifest], bool]] = None,
    provider_witness_verifier: Optional[Callable[[WorkBuddyHY3Route, ModelRunManifest], bool]] = None,
) -> dict[str, Any]:
    """Derive conformance and optionally ask a trusted validator to verify origin.

    Local structure checks establish only that the declared files and hashes
    are present.  ``provider_witness_verifier`` is the trust boundary for
    binding those artifacts to the actual WorkBuddy front door and HY3
    exchange; without it a provider claim remains explicitly unverified.
    ``route_witness_verifier`` is a separate trust boundary for accepting the
    selected WorkBuddy/HY3 route when provider authentication is unavailable.
    """

    parsed = manifest if isinstance(manifest, ModelRunManifest) else ModelRunManifest.from_mapping(manifest)
    grouped = _events_by_case(parsed)
    required = set(_case_keys())
    observed = set(grouped)
    missing = sorted(f"{domain}:{scenario}" for domain, scenario in required - observed)
    extra = sorted(f"{domain}:{scenario}" for domain, scenario in observed - required)
    outcomes: list[_CaseOutcome] = []
    for key in sorted(required & observed):
        outcomes.append(_evaluate_case(key, grouped[key], parsed.route))
    first_correct = sum(outcome.first_round_correct for outcome in outcomes)
    all_final_completed = len(outcomes) == len(required) and not missing and not extra and all(outcome.final_completed for outcome in outcomes)
    behavior_passed = (
        len(outcomes) == len(required)
        and not missing
        and not extra
        and first_correct >= REQUIRED_FIRST_ROUND_CORRECT
        and all_final_completed
        and all(outcome.correction_turns <= 2 for outcome in outcomes)
        and all(outcome.rule_compliant for outcome in outcomes)
        and all(outcome.unknown_results == 0 for outcome in outcomes)
        and all(outcome.human_semantic_help == 0 for outcome in outcomes)
        and all(outcome.model_switches == 0 for outcome in outcomes)
        and all(outcome.undeclared_subagents == 0 for outcome in outcomes)
        and all(outcome.forbidden_action_attempts == 0 for outcome in outcomes)
        and all(outcome.missing_tool_evidence == 0 for outcome in outcomes)
        and all(outcome.missing_reference_media == 0 for outcome in outcomes)
        and all(outcome.error is None for outcome in outcomes)
    )
    provider_claimed = parsed.route.identity_level is IdentityLevel.PROVIDER_VERIFIED
    route_witness_present = parsed.route.app.files_structurally_valid
    route_witness_verified = False
    if route_witness_present and route_witness_verifier is not None:
        try:
            route_witness_verified = route_witness_verifier(parsed.route, parsed) is True
        except Exception:
            route_witness_verified = False
    provider_witness_present = bool(
        provider_claimed
        and parsed.route.provider_evidence is not None
        and parsed.route.provider_evidence.witness_structurally_valid
    )
    provider_verified = False
    if provider_claimed and provider_witness_present and provider_witness_verifier is not None:
        try:
            # Require the callback to return the literal boolean True; a
            # caller-provided truthy value is not a verification result.
            provider_verified = provider_witness_verifier(parsed.route, parsed) is True
        except Exception:
            provider_verified = False
    provider_verification_status = "VERIFIED" if provider_verified else "UNVERIFIED"
    route_acceptance_passed = behavior_passed and route_witness_verified
    result = {
        "schema": MODEL_RUN_EVALUATION_SCHEMA,
        "manifest_sha256": parsed.manifest_sha256,
        "run_id": parsed.run_id,
        "task_id": parsed.task_id,
        "route_id": parsed.route.route_id,
        "identity_level": parsed.route.identity_level.value,
        "identity_scope": "workbuddy_app_hy3_route",
        "app_selected": parsed.route.app_selected,
        "route_witness_present": route_witness_present,
        "route_witness_verified": route_witness_verified,
        "route_acceptance_passed": route_acceptance_passed,
        "provider_claimed": provider_claimed,
        "provider_witness_present": provider_witness_present,
        "provider_verification_status": provider_verification_status,
        "provider_verified": provider_verified,
        "case_count": len(outcomes),
        "required_case_count": len(required),
        "missing_cases": missing,
        "extra_cases": extra,
        "first_round_correct": first_correct,
        "required_first_round_correct": REQUIRED_FIRST_ROUND_CORRECT,
        "first_round_accuracy": first_correct / len(required) if required else 0.0,
        "all_final_completed": all_final_completed,
        "rule_compliant_cases": sum(outcome.rule_compliant for outcome in outcomes),
        "model_decisions": sum(outcome.model_decisions for outcome in outcomes),
        "transport_retries": sum(outcome.transport_retries for outcome in outcomes),
        "host_retries": sum(outcome.host_retries for outcome in outcomes),
        "dcc_retries": sum(outcome.dcc_retries for outcome in outcomes),
        "unknown_results": sum(outcome.unknown_results for outcome in outcomes),
        "cold_start_retries": sum(outcome.cold_start_retries for outcome in outcomes),
        "format_corrections": sum(outcome.format_corrections for outcome in outcomes),
        "state_corrections": sum(outcome.state_corrections for outcome in outcomes),
        "correction_turns": sum(outcome.correction_turns for outcome in outcomes),
        "human_semantic_help": sum(outcome.human_semantic_help for outcome in outcomes),
        "model_switches": sum(outcome.model_switches for outcome in outcomes),
        "undeclared_subagents": sum(outcome.undeclared_subagents for outcome in outcomes),
        "forbidden_action_attempts": sum(outcome.forbidden_action_attempts for outcome in outcomes),
        "missing_tool_evidence": sum(outcome.missing_tool_evidence for outcome in outcomes),
        "missing_reference_media": sum(outcome.missing_reference_media for outcome in outcomes),
        "trace": {
            "graph_ids": sorted({item for outcome in outcomes for item in outcome.graph_ids}),
            "operation_ids": sorted({item for outcome in outcomes for item in outcome.operation_ids}),
            "action_ids": sorted({item for outcome in outcomes for item in outcome.action_ids}),
            "artifact_ids": sorted({item for outcome in outcomes for item in outcome.artifact_ids}),
        },
        "human_authorization_ids": sorted({item for outcome in outcomes for item in outcome.human_authorization_ids}),
        "model_proposal_ids": sorted({item for outcome in outcomes for item in outcome.model_proposal_ids}),
        "structured_errors": [
            {"case_id": outcome.case_id, **dict(item)}
            for outcome in outcomes for item in outcome.structured_errors
        ],
        "cases": [outcome.to_dict() for outcome in outcomes],
        "case_conformance_passed": behavior_passed,
        # ``passed`` is the route-scoped acceptance result.  Provider identity
        # remains a separate release prerequisite and is never inferred from
        # this route result.
        "passed": route_acceptance_passed,
        "release_scope": "workbuddy_hy3_run_only",
        "release_passed": route_acceptance_passed and provider_verified,
    }
    result.update(
        {
            "transport_retry_count": result["transport_retries"],
            "host_retry_count": result["host_retries"],
            "dcc_retry_count": result["dcc_retries"],
            "unknown_result_count": result["unknown_results"],
            "format_state_correction_count": result["correction_turns"],
            "human_semantic_help_count": result["human_semantic_help"],
            "model_switch_count": result["model_switches"],
            "undeclared_subagent_count": result["undeclared_subagents"],
            "forbidden_action_attempt_count": result["forbidden_action_attempts"],
        }
    )
    return json_value(result)


def verify_workbuddy_release_gate(
    manifest: ModelRunManifest | Mapping[str, Any],
    *,
    route_witness_verifier: Optional[Callable[[WorkBuddyHY3Route, ModelRunManifest], bool]] = None,
    provider_witness_verifier: Optional[Callable[[WorkBuddyHY3Route, ModelRunManifest], bool]] = None,
) -> dict[str, Any]:
    """Return release status after optional trusted witness verification."""

    return evaluate_model_run(
        manifest,
        route_witness_verifier=route_witness_verifier,
        provider_witness_verifier=provider_witness_verifier,
    )


def verify_workbuddy_diagnostic_gate(
    manifest: ModelRunManifest | Mapping[str, Any],
) -> dict[str, Any]:
    """Return conformance details while preserving APP_SELECTED visibility."""

    result = evaluate_model_run(manifest)
    return {**result, "release_passed": False}


def model_run_manifest_from_mapping(value: Mapping[str, Any]) -> ModelRunManifest:
    return ModelRunManifest.from_mapping(value)


def workbuddy_evidence_from_report(value: Mapping[str, Any]) -> ModelRunManifest:
    return ModelRunManifest.from_mapping(value)


def workbuddy_app_identity_from_plist(path: Path | str, *, executable_path: Path | str | None = None) -> WorkBuddyAppIdentity:
    """Convenience entry point for the read-only Info.plist identity probe."""

    return WorkBuddyAppIdentity.from_info_plist(path, executable_path=executable_path)


__all__ = [
    "HY3_MODEL_ID",
    "IdentityLevel",
    "MODEL_RUN_EVALUATION_SCHEMA",
    "MODEL_RUN_MANIFEST_SCHEMA",
    "ModelRoundEvent",
    "ModelRunManifest",
    "HY3ProviderEvidence",
    "REQUIRED_FIRST_ROUND_CORRECT",
    "REQUIRED_SCENARIOS",
    "WORKBUDDY_BUNDLE_ID",
    "WORKBUDDY_DOMAIN_PACKS",
    "WORKBUDDY_ROUTE_ID",
    "WorkBuddyAppIdentity",
    "WorkBuddyHY3Route",
    "evaluate_model_run",
    "model_run_manifest_from_mapping",
    "verify_workbuddy_diagnostic_gate",
    "verify_workbuddy_release_gate",
    "workbuddy_evidence_from_report",
    "workbuddy_app_identity_from_plist",
]
