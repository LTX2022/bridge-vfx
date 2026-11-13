from __future__ import annotations

import unittest
from dataclasses import dataclass

from vfx_pipeline.backends import (
    BackendError,
    BackendUnsupportedError,
    DccBackend,
    LegacyHoudiniHttpBackend,
    NukeBridgeBackend,
)
from vfx_pipeline.sidefx_mcp import SideFXMcpBackend


@dataclass
class Instance:
    port: int
    data: dict
    source: str = "test-discovery"
    token: str | None = None


class RecordingClient:
    def __init__(self, port, **kwargs):
        self.port = port
        self.kwargs = kwargs
        self.calls = []

    def call(self, command, params):
        self.calls.append((command, params))
        return {"command": command, "params": params, "port": self.port}


class DccBackendTests(unittest.TestCase):
    def test_houdini_discovery_client_execute_and_identity(self):
        clients = []

        def factory(port, **kwargs):
            client = RecordingClient(port, **kwargs)
            clients.append(client)
            return client

        backend = LegacyHoudiniHttpBackend(
            lambda: [Instance(8101, {"version": "22"}, token="secret")],
            factory,
        )
        self.assertIsInstance(backend, DccBackend)
        endpoints = backend.discover()
        self.assertEqual(endpoints[0].session, "houdini_legacy_http:8101")
        self.assertNotIn("credential", endpoints[0].to_dict())
        result = backend.execute("scene.info")
        self.assertEqual(result["port"], 8101)
        self.assertEqual(clients[0].kwargs, {"token": "secret"})
        self.assertEqual(
            backend.evidence_identity(),
            {
                "backend_id": "houdini_legacy_http",
                "protocol": "houdini.bridge.http",
                "session": "houdini_legacy_http:8101",
                "source": "test-discovery",
            },
        )

    def test_port_reuse_cannot_restore_previous_session(self):
        active = [Instance(8101, {"session_id": "first-process"})]
        backend = LegacyHoudiniHttpBackend(lambda: active, RecordingClient)
        original = backend.discover()[0].session
        self.assertTrue(backend.discover()[0].reported_capabilities["instance_identity_verified"])
        active[:] = [Instance(8101, {"session_id": "second-process"})]
        with self.assertRaises(BackendUnsupportedError):
            backend.client(original)
        self.assertNotEqual(original, backend.discover()[0].session)

    def test_nuke_backend_uses_injected_discovery_and_factory(self):
        created = []

        def factory(port):
            client = RecordingClient(port)
            created.append(client)
            return client

        backend = NukeBridgeBackend(lambda: [Instance(59555, {"nuke": "17"})], factory)
        self.assertEqual(backend.capabilities()["status"], "AVAILABLE")
        backend.execute("nuke_ping", {"probe": True})
        self.assertEqual(created[0].calls, [("nuke_ping", {"probe": True})])
        self.assertEqual(backend.evidence_identity()["protocol"], "nuke.bridge.tcp")

    def test_missing_session_and_unproven_cancel_are_unsupported(self):
        backend = NukeBridgeBackend(lambda: [], RecordingClient)
        self.assertEqual(backend.capabilities()["status"], "UNSUPPORTED")
        with self.assertRaises(BackendUnsupportedError) as missing:
            backend.client()
        self.assertEqual(missing.exception.code, "UNSUPPORTED")

        available = NukeBridgeBackend(lambda: [Instance(59555, {})], RecordingClient)
        with self.assertRaises(BackendUnsupportedError):
            available.cancel("operation-1")

    def test_configured_cancel_command_is_executed(self):
        backend = NukeBridgeBackend(
            lambda: [Instance(59555, {})],
            RecordingClient,
            cancel_command="task.cancel",
        )
        result = backend.cancel("operation-1")
        self.assertEqual(result["command"], "task.cancel")
        self.assertEqual(result["params"], {"operation_id": "operation-1"})

    def test_non_mapping_bridge_result_is_rejected(self):
        class BadClient(RecordingClient):
            def call(self, command, params):
                return [command]

        backend = NukeBridgeBackend(lambda: [Instance(59555, {})], BadClient)
        with self.assertRaises(BackendError) as raised:
            backend.execute("nuke_ping")
        self.assertEqual(raised.exception.code, "INVALID_RESPONSE")


class Connector:
    def __init__(self, reported):
        self.reported = reported
        self.calls = []

    def capabilities(self):
        return dict(self.reported)

    def execute(self, command, params):
        self.calls.append((command, params))
        return {"ok": True}

    def cancel(self, operation_id):
        return {"cancelled": operation_id}


class SideFXMcpTests(unittest.TestCase):
    def test_unconfigured_backend_is_stably_unsupported(self):
        backend = SideFXMcpBackend()
        first = backend.capabilities()
        second = backend.capabilities()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "UNSUPPORTED")
        self.assertEqual(first["reason"], "sidefx_mcp_not_configured")
        self.assertEqual(backend.discover(), ())
        with self.assertRaises(BackendUnsupportedError):
            backend.execute("node.create")

    def test_name_alone_does_not_prove_official_support(self):
        connector = Connector(
            {
                "protocol": "sidefx.mcp",
                "capabilities": ["execute"],
                "session": "mcp-1",
                "source": "claimed-server",
            }
        )
        backend = SideFXMcpBackend(lambda: connector)
        self.assertEqual(backend.capabilities()["status"], "UNSUPPORTED")
        with self.assertRaises(BackendUnsupportedError):
            backend.client()

    def test_verified_capabilities_enable_only_proven_operations(self):
        connector = Connector(
            {
                "protocol": "sidefx.mcp",
                "official_sidefx_mcp": True,
                "verified": True,
                "capabilities": ["execute"],
                "session": "mcp-verified-1",
                "source": "capability-handshake",
            }
        )
        backend = SideFXMcpBackend(lambda: connector)
        self.assertEqual(backend.capabilities()["status"], "AVAILABLE")
        self.assertEqual(backend.discover()[0].session, "mcp-verified-1")
        self.assertEqual(backend.execute("node.inspect"), {"ok": True})
        with self.assertRaises(BackendUnsupportedError):
            backend.cancel("op-1")
        self.assertEqual(
            backend.evidence_identity(),
            {
                "backend_id": "sidefx_mcp",
                "protocol": "sidefx.mcp",
                "session": "mcp-verified-1",
                "source": "capability-handshake",
            },
        )

    def test_cancel_requires_explicit_negotiated_capability(self):
        connector = Connector(
            {
                "protocol": "sidefx.mcp",
                "official_sidefx_mcp": True,
                "verified": True,
                "capabilities": ["execute", "cancel"],
                "session": "mcp-2",
                "source": "verified-handshake",
            }
        )
        backend = SideFXMcpBackend(lambda: connector)
        self.assertEqual(backend.cancel("op-2"), {"cancelled": "op-2"})


if __name__ == "__main__":
    unittest.main()
