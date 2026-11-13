"""Loopback TCP client and live Nuke instance discovery."""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .paths import bridge_tokens_for_port, manifests_dir
from .registry import canonical_command


class NukeConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NukeInstance:
    port: int
    data: dict[str, Any]
    source: str
    token: str | None = field(default=None, repr=False)


class NukeClient:
    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        timeout_seconds: float = 5.0,
        token: str | None = None,
    ) -> None:
        self.port = int(port)
        self.host = host
        self.timeout_seconds = timeout_seconds
        self._loopback = self.host in {"127.0.0.1", "localhost", "::1"}
        supplied = str(token or "") or None
        if self._loopback and token != "":
            discovered = bridge_tokens_for_port(self.port)
        else:
            discovered = ()
        candidates = ([supplied] if supplied else []) + [
            item for item in discovered if item != supplied
        ]
        self._token_candidates = tuple(candidates)
        self.token = self._token_candidates[0] if self._token_candidates else supplied

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        canonical = canonical_command(command)
        candidates: tuple[str | None, ...] = self._token_candidates or (None,)
        result: Any = None
        for index, candidate in enumerate(candidates):
            payload = {
                "id": uuid4().hex,
                "command": canonical,
                "params": params or {},
            }
            if candidate:
                payload["token"] = candidate
            try:
                with socket.create_connection(
                    (self.host, self.port), timeout=self.timeout_seconds
                ) as connection:
                    connection.sendall(
                        (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
                    )
                    stream = connection.makefile("rb")
                    response = stream.readline()
            except OSError as exc:
                raise NukeConnectionError(
                    f"Nuke Bridge is unreachable at {self.host}:{self.port}: {exc}"
                ) from exc
            if not response:
                raise NukeConnectionError("Nuke Bridge closed the connection without a response")
            try:
                result = json.loads(response.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise NukeConnectionError("Nuke Bridge returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise NukeConnectionError("Nuke Bridge returned a non-object JSON response")
            error = result.get("error") if result.get("status") != "success" else None
            if (
                isinstance(error, dict)
                and error.get("code") == "AUTH_REQUIRED"
                and error.get("indeterminate", False) is False
                and index + 1 < len(candidates)
            ):
                continue
            if result.get("status") == "success":
                self.token = candidate
                if candidate:
                    self._token_candidates = (candidate,) + tuple(
                        item for item in self._token_candidates if item != candidate
                    )
            break
        if result.get("status") != "success":
            error = result.get("error", {})
            invalid = (not isinstance(error, dict)
                       or "indeterminate" in error and type(error["indeterminate"]) is not bool)
            if invalid:
                exc = NukeConnectionError("Nuke Bridge returned an invalid error response")
                setattr(exc, "code", "INVALID_RESPONSE")
                setattr(exc, "indeterminate", True)
                raise exc
            exc = NukeConnectionError(
                str(error.get("message") or "Nuke Bridge command failed")
            )
            setattr(exc, "code", str(error.get("code") or "BRIDGE_ERROR"))
            setattr(exc, "indeterminate", error.get("indeterminate") is True)
            raise exc
        data = result.get("data")
        return data if isinstance(data, dict) else {"value": data}

    def health(self) -> dict[str, Any]:
        return self.call("nuke_ping")


def _candidate_ports() -> Iterable[int]:
    yielded: set[int] = set()
    directory = manifests_dir()
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                port = int(json.loads(path.read_text(encoding="utf-8")).get("port"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if 59555 <= port <= 59654 and port not in yielded:
                yielded.add(port)
                yield port
    for port in range(59555, 59655):
        if port not in yielded:
            yield port


def _probe(port: int) -> NukeInstance | None:
    client = NukeClient(port, timeout_seconds=0.35)
    try:
        data = client.health()
    except Exception:
        return None
    return NukeInstance(port=port, data=data, source="health", token=client.token)


def discover_instances() -> list[NukeInstance]:
    results: list[NukeInstance] = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(_probe, port) for port in _candidate_ports()]
        for future in as_completed(futures):
            instance = future.result()
            if instance is not None:
                results.append(instance)
    return sorted(results, key=lambda item: item.port)
