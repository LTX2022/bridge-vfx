"""Capability-negotiated placeholder for a future official SideFX MCP.

Nothing in this adapter assumes that an official MCP is installed or that a
reported server can perform Houdini operations.  A connector must explicitly
prove its protocol identity and required capabilities before use.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from .backends import BackendEndpoint, BackendEvidenceIdentity, BackendError, BackendUnsupportedError


class SideFXMcpBackend:
    backend_id = "sidefx_mcp"
    protocol = "sidefx.mcp"

    def __init__(
        self,
        connector_factory: Optional[Callable[[], Any]] = None,
        *,
        required_capabilities: Sequence[str] = ("execute",),
    ) -> None:
        self._connector_factory = connector_factory
        self._required = tuple(sorted({str(item) for item in required_capabilities if str(item)}))
        self._connector: Any = None
        self._negotiation: Optional[dict[str, Any]] = None

    def _unsupported(self, reason: str) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "status": "UNSUPPORTED",
            "available": False,
            "reason": reason,
            "required_capabilities": list(self._required),
            "proven_capabilities": [],
        }

    def _negotiate(self, refresh: bool = False) -> dict[str, Any]:
        if self._negotiation is not None and not refresh:
            return dict(self._negotiation)
        if self._connector_factory is None:
            self._negotiation = self._unsupported("sidefx_mcp_not_configured")
            return dict(self._negotiation)
        try:
            connector = self._connector_factory()
            reported = connector.capabilities()
        except Exception as exc:
            self._connector = None
            self._negotiation = self._unsupported(f"capability_negotiation_failed:{type(exc).__name__}")
            return dict(self._negotiation)
        if not isinstance(reported, Mapping):
            self._negotiation = self._unsupported("invalid_capability_response")
            return dict(self._negotiation)
        proven = {str(item) for item in reported.get("capabilities", ())}
        protocol_proven = reported.get("protocol") == self.protocol
        provider_proven = reported.get("official_sidefx_mcp") is True
        verified = reported.get("verified") is True
        missing = sorted(set(self._required) - proven)
        if not protocol_proven or not provider_proven or not verified or missing:
            reason = "capability_identity_not_proven"
            if protocol_proven and provider_proven and verified and missing:
                reason = "required_capabilities_missing"
            result = self._unsupported(reason)
            result["proven_capabilities"] = sorted(proven)
            result["missing_capabilities"] = missing
            self._connector = None
            self._negotiation = result
            return dict(result)
        session = str(reported.get("session") or "")
        source = str(reported.get("source") or "")
        if not session or not source:
            self._connector = None
            self._negotiation = self._unsupported("evidence_identity_not_proven")
            return dict(self._negotiation)
        self._connector = connector
        self._negotiation = {
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "status": "AVAILABLE",
            "available": True,
            "session": session,
            "source": source,
            "required_capabilities": list(self._required),
            "proven_capabilities": sorted(proven),
        }
        return dict(self._negotiation)

    def discover(self, refresh: bool = False) -> tuple[BackendEndpoint, ...]:
        capabilities = self._negotiate(refresh=refresh)
        if not capabilities["available"]:
            return ()
        return (
            BackendEndpoint(
                session=str(capabilities["session"]),
                source=str(capabilities["source"]),
                locator={"protocol": self.protocol},
                reported_capabilities={
                    "capabilities": list(capabilities["proven_capabilities"]),
                },
            ),
        )

    def capabilities(self, refresh: bool = False) -> Mapping[str, Any]:
        return self._negotiate(refresh=refresh)

    def client(self, session: Optional[str] = None) -> Any:
        capabilities = self._negotiate()
        if not capabilities["available"] or self._connector is None:
            raise BackendUnsupportedError(str(capabilities.get("reason") or "SideFX MCP is unavailable"))
        if session is not None and session != capabilities["session"]:
            raise BackendUnsupportedError(f"SideFX MCP session {session!r} is not available")
        return self._connector

    def execute(
        self,
        command: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        session: Optional[str] = None,
    ) -> Mapping[str, Any]:
        connector = self.client(session)
        result = connector.execute(str(command), dict(params or {}))
        if not isinstance(result, Mapping):
            raise BackendError("INVALID_RESPONSE", "SideFX MCP returned a non-object result")
        return dict(result)

    def cancel(self, operation_id: str, *, session: Optional[str] = None) -> Mapping[str, Any]:
        capabilities = self._negotiate()
        if "cancel" not in capabilities.get("proven_capabilities", ()):
            raise BackendUnsupportedError("SideFX MCP has not proven a cancellation capability")
        connector = self.client(session)
        result = connector.cancel(str(operation_id))
        if not isinstance(result, Mapping):
            raise BackendError("INVALID_RESPONSE", "SideFX MCP returned a non-object cancellation result")
        return dict(result)

    def evidence_identity(self, session: Optional[str] = None) -> Mapping[str, str]:
        capabilities = self._negotiate()
        self.client(session)
        return BackendEvidenceIdentity(
            backend_id=self.backend_id,
            protocol=self.protocol,
            session=str(capabilities["session"]),
            source=str(capabilities["source"]),
        ).to_dict()


__all__ = ("SideFXMcpBackend",)
