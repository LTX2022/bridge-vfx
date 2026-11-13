"""Protocol-neutral DCC backend contracts and legacy bridge adapters.

The adapters in this module deliberately describe transport capability only.
They do not promote a DCC/domain to ``supported``; that remains the job of the
live-validation evidence index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable


class BackendError(RuntimeError):
    """Stable backend failure with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        super().__init__(message)


class BackendUnsupportedError(BackendError):
    def __init__(self, message: str) -> None:
        super().__init__("UNSUPPORTED", message)


@dataclass(frozen=True)
class BackendEndpoint:
    """One discovered backend session without transport-specific assumptions."""

    session: str
    source: str
    locator: Mapping[str, Any] = field(default_factory=dict)
    reported_capabilities: Mapping[str, Any] = field(default_factory=dict)
    credential: Optional[str] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "source": self.source,
            "locator": dict(self.locator),
            "reported_capabilities": dict(self.reported_capabilities),
        }


@dataclass(frozen=True)
class BackendEvidenceIdentity:
    """Minimum provenance attached to every backend-produced observation."""

    backend_id: str
    protocol: str
    session: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "session": self.session,
            "source": self.source,
        }


@runtime_checkable
class DccBackend(Protocol):
    backend_id: str
    protocol: str

    def discover(self, refresh: bool = False) -> tuple[BackendEndpoint, ...]: ...

    def capabilities(self, refresh: bool = False) -> Mapping[str, Any]: ...

    def client(self, session: Optional[str] = None) -> Any: ...

    def execute(
        self,
        command: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        session: Optional[str] = None,
    ) -> Mapping[str, Any]: ...

    def cancel(self, operation_id: str, *, session: Optional[str] = None) -> Mapping[str, Any]: ...

    def evidence_identity(self, session: Optional[str] = None) -> Mapping[str, str]: ...


def _field(instance: Any, name: str, default: Any = None) -> Any:
    if isinstance(instance, Mapping):
        return instance.get(name, default)
    return getattr(instance, name, default)


class _LegacyBridgeBackend:
    """Shared adapter for the existing loopback Houdini and Nuke bridges."""

    backend_id = ""
    protocol = ""
    application = ""

    def __init__(
        self,
        discoverer: Callable[[], Sequence[Any]],
        client_factory: Callable[..., Any],
        *,
        cancel_command: Optional[str] = None,
    ) -> None:
        self._discoverer = discoverer
        self._client_factory = client_factory
        self._cancel_command = str(cancel_command) if cancel_command else None
        self._inventory: tuple[BackendEndpoint, ...] = ()
        self._has_discovered = False

    def discover(self, refresh: bool = False) -> tuple[BackendEndpoint, ...]:
        if self._has_discovered and not refresh:
            return self._inventory
        endpoints = []
        for instance in self._discoverer():
            port = int(_field(instance, "port"))
            source = str(_field(instance, "source", "discovery"))
            capabilities = dict(_field(instance, "data", {}) or {})
            identity = str(capabilities.get("session_id") or "")
            capabilities["instance_identity_verified"] = bool(identity)
            endpoints.append(
                BackendEndpoint(
                    session=f"{self.backend_id}:{port}" + (":" + identity if identity else ""),
                    source=source,
                    locator={"host": "127.0.0.1", "port": port},
                    reported_capabilities=capabilities,
                    credential=(str(_field(instance, "token", "") or "") or None),
                )
            )
        self._inventory = tuple(sorted(endpoints, key=lambda item: int(item.locator["port"])))
        self._has_discovered = True
        return self._inventory

    def capabilities(self, refresh: bool = False) -> Mapping[str, Any]:
        endpoints = self.discover(refresh=refresh)
        return {
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "status": "AVAILABLE" if endpoints else "UNSUPPORTED",
            "available": bool(endpoints),
            "cancel": self._cancel_command is not None,
            "sessions": [endpoint.to_dict() for endpoint in endpoints],
        }

    def _endpoint(self, session: Optional[str]) -> BackendEndpoint:
        endpoints = self.discover()
        endpoint = next((item for item in endpoints if session is None or item.session == session), None)
        if endpoint is None:
            requested = session or "default"
            raise BackendUnsupportedError(f"{self.backend_id} session {requested!r} is not available")
        return endpoint

    def client(self, session: Optional[str] = None) -> Any:
        self.discover(refresh=True)
        endpoint = self._endpoint(session)
        port = int(endpoint.locator["port"])
        return self._build_client(port, endpoint)

    def _build_client(self, port: int, endpoint: BackendEndpoint) -> Any:
        return self._client_factory(port)

    def execute(
        self,
        command: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        session: Optional[str] = None,
    ) -> Mapping[str, Any]:
        result = self.client(session).call(str(command), dict(params or {}))
        if not isinstance(result, Mapping):
            raise BackendError("INVALID_RESPONSE", f"{self.backend_id} returned a non-object result")
        return dict(result)

    def cancel(self, operation_id: str, *, session: Optional[str] = None) -> Mapping[str, Any]:
        if not self._cancel_command:
            raise BackendUnsupportedError(f"{self.backend_id} has not proven a cancellation capability")
        return self.execute(self._cancel_command, {"operation_id": str(operation_id)}, session=session)

    def evidence_identity(self, session: Optional[str] = None) -> Mapping[str, str]:
        endpoint = self._endpoint(session)
        return BackendEvidenceIdentity(
            backend_id=self.backend_id,
            protocol=self.protocol,
            session=endpoint.session,
            source=endpoint.source,
        ).to_dict()


class LegacyHoudiniHttpBackend(_LegacyBridgeBackend):
    backend_id = "houdini_legacy_http"
    protocol = "houdini.bridge.http"
    application = "houdini"

    def __init__(
        self,
        discoverer: Optional[Callable[[], Sequence[Any]]] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        *,
        cancel_command: Optional[str] = None,
    ) -> None:
        if discoverer is None or client_factory is None:
            module = import_module("houdini_bridge")
            discoverer = discoverer or module.discover_instances
            client_factory = client_factory or module.HoudiniClient
        super().__init__(discoverer, client_factory, cancel_command=cancel_command)

    def _build_client(self, port: int, endpoint: BackendEndpoint) -> Any:
        if endpoint.credential:
            return self._client_factory(port, token=endpoint.credential)
        return self._client_factory(port)


class NukeBridgeBackend(_LegacyBridgeBackend):
    backend_id = "nuke_bridge"
    protocol = "nuke.bridge.tcp"
    application = "nuke"

    def __init__(
        self,
        discoverer: Optional[Callable[[], Sequence[Any]]] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        *,
        cancel_command: Optional[str] = None,
    ) -> None:
        if discoverer is None or client_factory is None:
            module = import_module("nuke_bridge")
            discoverer = discoverer or module.discover_instances
            client_factory = client_factory or module.NukeClient
        super().__init__(discoverer, client_factory, cancel_command=cancel_command)


__all__ = (
    "BackendEndpoint",
    "BackendError",
    "BackendEvidenceIdentity",
    "BackendUnsupportedError",
    "DccBackend",
    "LegacyHoudiniHttpBackend",
    "NukeBridgeBackend",
)
