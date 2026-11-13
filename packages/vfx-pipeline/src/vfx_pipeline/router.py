"""Live DCC discovery and deterministic domain routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from dcc_task_runtime import ErrorCode
from dcc_task_runtime.domains import DomainPack
from houdini_bridge import HoudiniClient, discover_instances as discover_houdini_instances
from nuke_bridge import NukeClient, discover_instances as discover_nuke_instances

from .backends import DccBackend, LegacyHoudiniHttpBackend, NukeBridgeBackend


class RoutingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BridgeEndpoint:
    application: str
    port: int
    capabilities: Mapping[str, Any]
    source: str
    token: Optional[str] = field(default=None, repr=False, compare=False)
    backend_id: str = ""
    protocol: str = ""
    session: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "port": self.port,
            "capabilities": dict(self.capabilities),
            "source": self.source,
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "session": self.session,
        }


@dataclass(frozen=True)
class RouteLeg:
    application: str
    domain_pack: str
    domain_version: str
    port: int
    purpose: str
    backend_id: str = ""
    protocol: str = ""
    session: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "domain_pack": self.domain_pack,
            "domain_version": self.domain_version,
            "port": self.port,
            "purpose": self.purpose,
            "backend_id": self.backend_id,
            "protocol": self.protocol,
            "session": self.session,
        }


class BridgeRouter:
    """Resolve one explicit running instance for each required route leg.

    Discovery and client factories are injectable, which makes orchestration
    tests deterministic without pretending a live DCC was exercised.
    """

    def __init__(
        self,
        discoverers: Optional[Mapping[str, Callable[[], Sequence[Any]]]] = None,
        client_factories: Optional[Mapping[str, Callable[..., Any]]] = None,
        backends: Optional[Mapping[str, DccBackend]] = None,
    ) -> None:
        self._discoverers = dict(
            discoverers
            or {
                "houdini": discover_houdini_instances,
                "nuke": discover_nuke_instances,
            }
        )
        self._client_factories = dict(
            client_factories
            or {
                "houdini": HoudiniClient,
                "nuke": NukeClient,
            }
        )
        self._backends: dict[str, DccBackend] = dict(
            backends
            or {
                "houdini": LegacyHoudiniHttpBackend(
                    self._discoverers["houdini"], self._client_factories["houdini"]
                ),
                "nuke": NukeBridgeBackend(
                    self._discoverers["nuke"], self._client_factories["nuke"]
                ),
            }
        )
        if set(self._backends) != {"houdini", "nuke"}:
            raise ValueError("backends must provide houdini and nuke")
        self._inventory: dict[str, tuple[BridgeEndpoint, ...]] = {}

    def discover(self, refresh: bool = False) -> dict[str, tuple[BridgeEndpoint, ...]]:
        if self._inventory and not refresh:
            return dict(self._inventory)
        inventory: dict[str, tuple[BridgeEndpoint, ...]] = {}
        for application in ("houdini", "nuke"):
            backend = self._backends[application]
            instances = backend.discover(refresh=refresh)
            endpoints = []
            for instance in instances:
                locator = dict(getattr(instance, "locator", {}) or {})
                endpoints.append(
                    BridgeEndpoint(
                        application=application,
                        port=int(locator.get("port", 0)),
                        capabilities=dict(getattr(instance, "reported_capabilities", {}) or {}),
                        source=str(getattr(instance, "source", "discovery")),
                        token=getattr(instance, "credential", None),
                        backend_id=str(backend.backend_id),
                        protocol=str(backend.protocol),
                        session=str(getattr(instance, "session", "")),
                    )
                )
            inventory[application] = tuple(sorted(endpoints, key=lambda item: item.port))
        self._inventory = inventory
        return dict(inventory)

    def capabilities(self, refresh: bool = False) -> dict[str, Any]:
        inventory = self.discover(refresh=refresh)
        return {
            "applications": {
                application: [endpoint.to_dict() for endpoint in endpoints]
                for application, endpoints in inventory.items()
            },
            "available": [application for application, endpoints in inventory.items() if endpoints],
        }

    def client(
        self,
        application: str,
        port: Optional[int] = None,
        *,
        backend_id: Optional[str] = None,
        protocol: Optional[str] = None,
        session: Optional[str] = None,
    ):
        inventory = self.discover()
        endpoints = inventory.get(application) or ()
        endpoint = next(
            (
                item
                for item in endpoints
                if (port is None or item.port == port)
                and (backend_id is None or item.backend_id == backend_id)
                and (protocol is None or item.protocol == protocol)
                and (session is None or item.session == session)
            ),
            None,
        )
        if endpoint is None:
            identity = {
                "port": port,
                "backend_id": backend_id,
                "protocol": protocol,
                "session": session,
            }
            raise RoutingError(
                ErrorCode.INSTANCE_NOT_FOUND.value,
                f"no running {application} Bridge instance matches the requested identity {identity}",
            )
        return self._backends[application].client(endpoint.session)

    def client_for_leg(self, leg: RouteLeg):
        """Restore a client only when the complete persisted route still matches."""

        if not leg.backend_id or not leg.protocol or not leg.session:
            raise RoutingError(
                ErrorCode.INSTANCE_NOT_FOUND.value,
                "persisted route is missing backend_id, protocol, or session; rediscovery and replanning are required",
            )
        return self.client(
            leg.application,
            leg.port,
            backend_id=leg.backend_id,
            protocol=leg.protocol,
            session=leg.session,
        )

    def route(self, pack: DomainPack, include_composite: bool = True) -> tuple[RouteLeg, ...]:
        inventory = self.discover()
        declared = set(pack.dcc_applications)
        desired: list[tuple[str, str]] = []
        if pack.identifier == "nuke_composite_v1":
            desired.append(("nuke", "native_composite"))
        else:
            if "houdini" in declared:
                desired.append(("houdini", "author_simulate_render"))
            if include_composite and "nuke" in declared:
                desired.append(("nuke", "composite_delivery"))
        if not desired:
            raise RoutingError(ErrorCode.UNSUPPORTED_DOMAIN.value, f"domain {pack.identifier} has no routable DCC application")
        legs = []
        for application, purpose in desired:
            endpoints = inventory.get(application) or ()
            if not endpoints:
                raise RoutingError(
                    ErrorCode.INSTANCE_NOT_FOUND.value,
                    f"domain {pack.identifier} requires a running {application} Bridge instance",
                )
            endpoint = endpoints[0]
            legs.append(
                RouteLeg(
                    application,
                    pack.identifier,
                    pack.version,
                    endpoint.port,
                    purpose,
                    endpoint.backend_id,
                    endpoint.protocol,
                    endpoint.session,
                )
            )
        return tuple(legs)
