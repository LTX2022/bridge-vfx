from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nuke_bridge import client as client_module
from nuke_bridge import paths as paths_module


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"


def load_addon():
    spec = importlib.util.spec_from_file_location("bridge_test_nuke_transport_auth_addon", ADDON)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Nuke bridge addon")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NukePathAndTokenTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows exclusive socket semantics')
    def test_listener_skips_foreign_port_and_exclusively_owns_its_port(self):
        server = self.addon.NukeBridgeServer()
        with socket.socket() as foreign:
            foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            foreign.bind(('127.0.0.1', 0))
            foreign.listen()
            occupied = foreign.getsockname()
            with mock.patch.object(self.addon, 'range', return_value=[occupied[1], 0], create=True), \
                    mock.patch.object(server, '_write_manifest'):
                server.start()
            try:
                self.assertNotEqual(server.port, occupied[1])
                self.assertEqual(server._server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
                with socket.socket() as contender:
                    contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    with self.assertRaises(OSError):
                        contender.bind(server._server.server_address)
                with socket.create_connection(occupied, timeout=2):
                    pass
            finally:
                server.stop()

    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = load_addon()

    def test_addon_and_client_resolve_the_same_nuke_path_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"NUKE_PATH": directory, "NUKE_BRIDGE_INSTANCES_DIR": ""},
                clear=False,
            ):
                expected = Path(directory) / "nuke_bridge_instances"
                self.assertEqual(paths_module.manifests_dir(), expected)
                self.assertEqual(self.addon._manifest_dir(), expected)

    def test_first_non_default_nuke_path_entry_is_shared(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with mock.patch.dict(
                os.environ,
                {"NUKE_PATH": "&" + os.pathsep + first + os.pathsep + second},
                clear=False,
            ):
                expected = Path(first) / "nuke_bridge_instances"
                self.assertEqual(paths_module.manifests_dir(), expected)
                self.assertEqual(self.addon._manifest_dir(), expected)

    def test_private_sidecar_is_discovered_without_serializing_token(self) -> None:
        token = "t" * 32
        with tempfile.TemporaryDirectory() as directory:
            state = (Path(directory) / "instances").resolve()
            state.mkdir(mode=0o700)
            sidecar = state / "123.abc.token"
            sidecar.write_text(token, encoding="ascii")
            manifest = state / "123.json"
            manifest.write_text(
                json.dumps(
                    {
                        "pid": 123,
                        "port": 59555,
                        "session_id": "session-1",
                        "token_file": sidecar.name,
                    }
                ),
                encoding="utf-8",
            )
            if os.name != "nt":
                sidecar.chmod(0o600)
                manifest.chmod(0o600)
            with mock.patch.object(paths_module, "manifests_dir", return_value=state):
                self.assertEqual(paths_module.bridge_tokens_for_port(59555), (token,))
                self.assertEqual(paths_module.bridge_token_for_port(59555), token)
            self.assertNotIn(token, manifest.read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "POSIX ownership and mode checks are required")
    def test_insecure_sidecar_and_manifest_are_ignored(self) -> None:
        token = "u" * 32
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "instances"
            state.mkdir(mode=0o700)
            sidecar = state / "123.token"
            sidecar.write_text(token, encoding="ascii")
            manifest = state / "123.json"
            manifest.write_text(
                json.dumps({"port": 59555, "token_file": sidecar.name}),
                encoding="utf-8",
            )
            sidecar.chmod(0o600)
            manifest.chmod(0o644)
            with mock.patch.object(paths_module, "manifests_dir", return_value=state):
                self.assertEqual(paths_module.bridge_tokens_for_port(59555), ())
            manifest.chmod(0o600)
            sidecar.chmod(0o644)
            with mock.patch.object(paths_module, "manifests_dir", return_value=state):
                self.assertEqual(paths_module.bridge_tokens_for_port(59555), ())


class NukeAddonAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = load_addon()

    def test_new_server_requires_token_and_legacy_is_explicit(self) -> None:
        token = "a" * 32
        server = self.addon.NukeBridgeServer(token=token)
        self.assertEqual(server._authorize_request({})["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(
            server._authorize_request({"token": "b" * 32})["error"]["code"],
            "AUTH_REQUIRED",
        )
        self.assertIsNone(server._authorize_request({"token": token}))
        with self.assertRaises(ValueError):
            self.addon.NukeBridgeServer(token="short")
        with self.assertRaises(ValueError):
            self.addon.NukeBridgeServer(token=token, allow_legacy_unauthenticated=True)
        legacy = self.addon.NukeBridgeServer(allow_legacy_unauthenticated=True)
        self.assertIsNone(legacy._token)
        self.assertIsNone(legacy._authorize_request({}))

    def test_manifest_uses_private_sidecar_and_stop_removes_both_files(self) -> None:
        token = "s" * 32
        fake_nuke = SimpleNamespace(NUKE_VERSION_STRING="17.0v1", GUI=True)
        with tempfile.TemporaryDirectory() as directory:
            state = (Path(directory) / "instances").resolve()
            server = self.addon.NukeBridgeServer(token=token)
            server.port = 59555
            with mock.patch.object(self.addon, "_manifest_dir", return_value=state):
                with mock.patch.dict(sys.modules, {"nuke": fake_nuke}):
                    server._write_manifest()
            self.assertIsNotNone(server._manifest)
            self.assertIsNotNone(server._token_file)
            manifest = server._manifest
            sidecar = server._token_file
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["token_file"], sidecar.name)
            self.assertEqual(payload["session_id"], server.session_id)
            self.assertNotIn(token, manifest.read_text(encoding="utf-8"))
            self.assertEqual(sidecar.read_text(encoding="ascii"), token)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
            server.stop()
            self.assertFalse(manifest.exists())
            self.assertFalse(sidecar.exists())

    def test_auth_failure_does_not_echo_token(self) -> None:
        token = "q" * 32
        response = self.addon.NukeBridgeServer(token=token)._authorize_request({"token": "x" * 32})
        self.assertNotIn(token, json.dumps(response))

    def test_task_host_render_queries_resolve_persisted_operation_owner(self) -> None:
        token = 'o' * 32
        server = self.addon.NukeBridgeServer(token=token)
        operation = 'nrend-' + 'a' * 16
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(self.addon, '_TASK_HOST_IDENTITY', {'task_id':'configured-owner'}), \
                mock.patch.object(self.addon, '_render_records_dir', return_value=Path(directory)):
            path = Path(directory) / (operation + '.json')
            for command in ('render_status','render_cancel','render_fact','control.render_resolve'):
                params = {'operation_id' if command == 'render_fact' else 'task_id':operation}
                request = {'token':token,'command':command,'params':params}
                for owner in (None, 'foreign-owner', 'configured-owner'):
                    with self.subTest(command=command, owner=owner):
                        if owner is None:
                            path.unlink(missing_ok=True)
                        else:
                            path.write_text(json.dumps({'task_id':operation,'owner_task_id':owner}))
                        response = server._authorize_request(request)
                        if owner == 'configured-owner':
                            self.assertIsNone(response)
                        else:
                            self.assertEqual(response['error']['code'],'TASK_IDENTITY_MISMATCH')
                bad = {**request, 'token':'x' * 32}
                with mock.patch.object(self.addon,'_load_render_record',side_effect=AssertionError('unauthenticated read')):
                    self.assertEqual(server._authorize_request(bad)['error']['code'],'AUTH_REQUIRED')
            response = server._authorize_request({'token':token,'command':'get_node',
                'params':{'task_id':operation,'name':'Read1'}})
            self.assertEqual(response['error']['code'],'TASK_IDENTITY_MISMATCH')


class NukeClientAuthTests(unittest.TestCase):
    def test_client_discovers_and_sends_token_without_exposing_it_in_instance_repr(self) -> None:
        token = "c" * 32
        sent: list[dict] = []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def sendall(self, payload: bytes) -> None:
                sent.append(json.loads(payload.decode("utf-8")))

            def makefile(self, _mode: str):
                return io.BytesIO(b'{"status":"success","data":{"ok":true}}\n')

        with mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(token,)):
            client = client_module.NukeClient(59555)
        with mock.patch.object(client_module.socket, "create_connection", return_value=Connection()):
            self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(sent[0]["token"], token)
        instance = client_module.NukeInstance(59555, {"pid": 1}, "health", token=token)
        self.assertNotIn(token, repr(instance))

    def test_explicit_empty_token_does_not_read_sidecar(self) -> None:
        with mock.patch.object(client_module, "bridge_tokens_for_port") as discover:
            client = client_module.NukeClient(59555, token="")
        discover.assert_not_called()
        self.assertIsNone(client.token)


if __name__ == "__main__":
    unittest.main()
