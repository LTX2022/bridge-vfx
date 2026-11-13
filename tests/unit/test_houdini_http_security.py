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
import unittest.mock
import urllib.error
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HoudiniHttpSecurityTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows exclusive socket semantics')
    def test_http_listener_exclusively_binds_and_preserves_foreign_listener(self):
        server=self.addon.HoudiniBridgeServer()
        with socket.socket() as foreign:
            foreign.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            foreign.bind(('127.0.0.1',0))
            foreign.listen()
            occupied=foreign.getsockname()
            with self.assertRaises(OSError):
                server._make_http(occupied[1])
            self.assertEqual(foreign.getsockname(),occupied)
            with socket.create_connection(occupied,timeout=2):
                pass
        http=server._make_http(0)
        try:
            self.assertEqual(http.socket.getsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE),1)
            with socket.socket() as contender:
                contender.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                with self.assertRaises(OSError):
                    contender.bind(http.server_address)
        finally:
            http.server_close()
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load("_houdini_http_security_addon", ADDON)

    def test_token_origin_and_allowlist_fail_closed(self) -> None:
        token = "t" * 32
        server = self.addon.HoudiniBridgeServer(
            token=token,
            allowed_commands={"ping", "capabilities.get", "agent.fx.probe"},
        )
        server.port = 8117
        self.assertEqual(server._authorize_http({})["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(
            server._authorize_http({"Authorization": "Bearer " + token, "Origin": "https://evil.invalid"})["error"]["code"],
            "CROSS_SITE_ORIGIN_REJECTED",
        )
        self.assertIsNone(server._authorize_http({"Authorization": "Bearer " + token}))
        self.assertIsNone(
            server._authorize_http(
                {"Authorization": "Bearer " + token, "Origin": "http://127.0.0.1:8117"}
            )
        )
        blocked = server._submit("code.exec_python", {"code": "result = 1"})
        self.assertEqual(blocked["error"]["code"], "COMMAND_NOT_ALLOWED")

    def test_default_server_is_authenticated_and_blocks_arbitrary_code(self) -> None:
        server = self.addon.HoudiniBridgeServer()
        server.port = 8118
        self.assertGreaterEqual(len(server._token or ""), 32)
        self.assertEqual(server._authorize_http({})["error"]["code"], "AUTH_REQUIRED")
        self.assertNotIn("code.exec_python", server._allowed_commands)
        blocked = server._submit("code.exec_python", {"code": "result = 1"})
        self.assertEqual(blocked["error"]["code"], "COMMAND_NOT_ALLOWED")

    def test_legacy_unauthenticated_server_requires_explicit_opt_in(self) -> None:
        server = self.addon.HoudiniBridgeServer(allow_legacy_unauthenticated=True)
        server.port = 8118
        self.assertIsNone(server._authorize_http({}))
        self.assertNotIn("code.exec_python", server._allowed_commands)
        with self.assertRaises(ValueError):
            self.addon.HoudiniBridgeServer(
                token="t" * 32,
                allow_legacy_unauthenticated=True,
            )
        with self.assertRaises(ValueError):
            self.addon.HoudiniBridgeServer(token="too-short")

    def test_production_autostart_creates_an_authenticated_server(self) -> None:
        captured = {}

        class FakeServer:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

            def start(self) -> int:
                return 8199

        original_server = self.addon._SERVER
        self.addon._SERVER = None
        try:
            with unittest.mock.patch.dict(
                os.environ,
                {self.addon._CODE_EXEC_OPT_IN_ENV: ""},
                clear=False,
            ):
                with unittest.mock.patch.object(self.addon, "HoudiniBridgeServer", FakeServer):
                    self.assertEqual(self.addon.autostart(), 8199)
        finally:
            self.addon._SERVER = original_server
        self.assertGreaterEqual(len(captured.get("token") or ""), 32)
        self.assertNotIn("code.exec_python", captured["allowed_commands"])

    def test_human_launch_can_explicitly_opt_in_to_legacy_code_exec(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {self.addon._CODE_EXEC_OPT_IN_ENV: "1"},
            clear=False,
        ):
            allowed = self.addon._production_allowed_commands()
        self.assertIn("code.exec_python", allowed)
        self.assertIn("exec_python", allowed)

    def test_manifest_uses_private_token_sidecar_and_stop_removes_it(self) -> None:
        token = "s" * 32
        fake_hou = SimpleNamespace(
            applicationVersionString=lambda: "unit-build",
            licenseCategory=lambda: SimpleNamespace(name=lambda: "Education"),
            hipFile=SimpleNamespace(path=lambda: "untitled.hip"),
            isUIAvailable=lambda: False,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve()
            server = self.addon.HoudiniBridgeServer(token=token, allowed_commands={"ping"})
            server.port = 8119
            with unittest.mock.patch.object(self.addon, "_state_dir", return_value=state):
                with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                    server._write_manifest()
            manifest = server._manifest
            token_file = server._token_file
            self.assertIsNotNone(manifest)
            self.assertIsNotNone(token_file)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertNotIn("token", payload)
            self.assertEqual(payload["token_file"], token_file.name)
            self.assertEqual(token_file.read_text(encoding="ascii"), token)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)
            server.stop()
            self.assertFalse(manifest.exists())
            self.assertFalse(token_file.exists())

    @unittest.skipIf(os.name == "nt", "directory symlink behavior differs on Windows")
    def test_manifest_writer_rejects_symlinked_state_directory(self) -> None:
        fake_hou = SimpleNamespace(
            applicationVersionString=lambda: "unit-build",
            licenseCategory=lambda: SimpleNamespace(name=lambda: "Education"),
            hipFile=SimpleNamespace(path=lambda: "untitled.hip"),
            isUIAvailable=lambda: False,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            real_state = root / "real"
            real_state.mkdir()
            linked_state = root / "instances"
            linked_state.symlink_to(real_state, target_is_directory=True)
            server = self.addon.HoudiniBridgeServer(token="w" * 32, allowed_commands={"ping"})
            server.port = 8123
            with unittest.mock.patch.object(self.addon, "_state_dir", return_value=linked_state):
                with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                    with self.assertRaisesRegex(RuntimeError, "must not traverse a symlink"):
                        server._write_manifest()
            self.assertEqual(list(real_state.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX directory modes are required for this security check")
    def test_manifest_writer_rejects_group_or_world_writable_state_directory(self) -> None:
        fake_hou = SimpleNamespace(
            applicationVersionString=lambda: "unit-build",
            licenseCategory=lambda: SimpleNamespace(name=lambda: "Education"),
            hipFile=SimpleNamespace(path=lambda: "untitled.hip"),
            isUIAvailable=lambda: False,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve() / "instances"
            state.mkdir()
            state.chmod(0o777)
            server = self.addon.HoudiniBridgeServer(token="x" * 32, allowed_commands={"ping"})
            server.port = 8124
            try:
                with unittest.mock.patch.object(self.addon, "_state_dir", return_value=state):
                    with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                        with self.assertRaisesRegex(RuntimeError, "must be owner-controlled"):
                            server._write_manifest()
            finally:
                state.chmod(0o700)
            self.assertEqual(list(state.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlink behavior differs on Windows")
    def test_manifest_writer_never_follows_a_preplanted_temporary_symlink(self) -> None:
        fake_hou = SimpleNamespace(
            applicationVersionString=lambda: "unit-build",
            licenseCategory=lambda: SimpleNamespace(name=lambda: "Education"),
            hipFile=SimpleNamespace(path=lambda: "untitled.hip"),
            isUIAvailable=lambda: False,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve()
            victim = state / "victim.txt"
            victim.write_text("do-not-touch", encoding="utf-8")
            temporary = state / ".{}.json.fixed.tmp".format(os.getpid())
            temporary.symlink_to(victim)
            server = self.addon.HoudiniBridgeServer(
                allow_legacy_unauthenticated=True,
                allowed_commands={"ping"},
            )
            server.port = 8125
            with unittest.mock.patch.object(self.addon, "_state_dir", return_value=state):
                with unittest.mock.patch.object(
                    self.addon,
                    "uuid4",
                    return_value=SimpleNamespace(hex="fixed"),
                ):
                    with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                        with self.assertRaises(FileExistsError):
                            server._write_manifest()
            self.assertEqual(victim.read_text(encoding="utf-8"), "do-not-touch")
            self.assertTrue(temporary.is_symlink())


class ManifestCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _load(
            "_houdini_paths_security",
            ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "paths.py",
        )

    def test_new_private_sidecar_and_legacy_manifest_are_both_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory)
            (manifests / "legacy.json").write_text(json.dumps({"port": 8110}), encoding="utf-8")
            token_file = manifests / "new.token"
            token_file.write_text("z" * 32, encoding="ascii")
            if os.name != "nt":
                token_file.chmod(0o600)
            new_manifest = manifests / "new.json"
            new_manifest.write_text(
                json.dumps({"port": 8111, "token_file": token_file.name}),
                encoding="utf-8",
            )
            if os.name != "nt":
                new_manifest.chmod(0o600)
            with unittest.mock.patch.object(self.paths, "manifests_dir", return_value=manifests):
                self.assertIsNone(self.paths.bridge_token_for_port(8110))
                self.assertEqual(self.paths.bridge_token_for_port(8111), "z" * 32)

    def test_same_port_returns_every_valid_token_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory)
            rows = (("100-old", "o" * 32, 1_000), ("999-new", "n" * 32, 2_000))
            for name, token, modified_ns in rows:
                token_file = manifests / (name + ".token")
                token_file.write_text(token, encoding="ascii")
                manifest = manifests / (name + ".json")
                manifest.write_text(
                    json.dumps({"port": 8114, "token_file": token_file.name}),
                    encoding="utf-8",
                )
                if os.name != "nt":
                    token_file.chmod(0o600)
                    manifest.chmod(0o600)
                os.utime(manifest, ns=(modified_ns, modified_ns))
            with unittest.mock.patch.object(self.paths, "manifests_dir", return_value=manifests):
                self.assertEqual(self.paths.bridge_tokens_for_port(8114), ("n" * 32, "o" * 32))
                self.assertEqual(self.paths.bridge_token_for_port(8114), "n" * 32)

    @unittest.skipIf(os.name == "nt", "POSIX file modes are required for this security check")
    def test_insecure_manifest_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory)
            token_file = manifests / "bridge.token"
            token_file.write_text("m" * 32, encoding="ascii")
            token_file.chmod(0o600)
            manifest = manifests / "instance.json"
            manifest.write_text(
                json.dumps({"port": 8120, "token_file": token_file.name}),
                encoding="utf-8",
            )
            manifest.chmod(0o666)
            with unittest.mock.patch.object(self.paths, "manifests_dir", return_value=manifests):
                self.assertIsNone(self.paths.bridge_token_for_port(8120))

    @unittest.skipIf(os.name == "nt", "directory symlink behavior differs on Windows")
    def test_symlinked_instances_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_manifests = root / "real-instances"
            real_manifests.mkdir()
            token_file = real_manifests / "bridge.token"
            token_file.write_text("n" * 32, encoding="ascii")
            token_file.chmod(0o600)
            manifest = real_manifests / "instance.json"
            manifest.write_text(
                json.dumps({"port": 8121, "token_file": token_file.name}),
                encoding="utf-8",
            )
            manifest.chmod(0o600)
            linked_manifests = root / "instances"
            linked_manifests.symlink_to(real_manifests, target_is_directory=True)
            with unittest.mock.patch.object(self.paths, "manifests_dir", return_value=linked_manifests):
                self.assertIsNone(self.paths.bridge_token_for_port(8121))

    @unittest.skipIf(os.name == "nt", "POSIX directory modes are required for this security check")
    def test_group_or_world_writable_instances_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifests = Path(directory) / "instances"
            manifests.mkdir()
            token_file = manifests / "bridge.token"
            token_file.write_text("p" * 32, encoding="ascii")
            token_file.chmod(0o600)
            manifest = manifests / "instance.json"
            manifest.write_text(
                json.dumps({"port": 8122, "token_file": token_file.name}),
                encoding="utf-8",
            )
            manifest.chmod(0o600)
            manifests.chmod(0o777)
            with unittest.mock.patch.object(self.paths, "manifests_dir", return_value=manifests):
                self.assertIsNone(self.paths.bridge_token_for_port(8122))

    def test_client_auto_loads_token_and_sends_bearer_while_legacy_stays_empty(self) -> None:
        from houdini_bridge import client as client_module

        token = "q" * 32
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(token,)):
            secured = client_module.HoudiniClient(8111)
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=()):
            legacy = client_module.HoudiniClient(8110)
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(token,)) as explicit_empty_lookup:
            explicit_empty = client_module.HoudiniClient(8110, token="")
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(token,)) as token_lookup:
            remote = client_module.HoudiniClient(8111, host="render.example")
        self.assertEqual(secured.token, token)
        self.assertIsNone(legacy.token)
        self.assertIsNone(explicit_empty.token)
        explicit_empty_lookup.assert_not_called()
        self.assertIsNone(remote.token)
        token_lookup.assert_not_called()
        instance = client_module.HoudiniInstance(8111, {"pid": 1}, "health", token=token)
        self.assertEqual(instance.token, token)

        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"success","data":{"pid":1}}'

        def fake_urlopen(request, **_kwargs):
            captured["authorization"] = request.get_header("Authorization")
            return Response()

        with unittest.mock.patch.object(client_module.urllib.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(secured.health()["pid"], 1)
        self.assertEqual(captured["authorization"], "Bearer " + token)

    def test_client_retries_stale_token_and_binds_the_successful_candidate(self) -> None:
        from houdini_bridge import client as client_module

        stale, current = "s" * 32, "c" * 32
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(current,)):
            client = client_module.HoudiniClient(8115, token=stale)
        observed = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"success","data":{"pid":15}}'

        def fake_urlopen(request, **_kwargs):
            authorization = request.get_header("Authorization")
            observed.append(authorization)
            if authorization == "Bearer " + stale:
                raise urllib.error.HTTPError(
                    request.full_url,
                    403,
                    "Forbidden",
                    None,
                    io.BytesIO(b'{"status":"error","error":{"code":"AUTH_REQUIRED","message":"bad token"}}'),
                )
            return Response()

        with unittest.mock.patch.object(client_module.urllib.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(client.health()["pid"], 15)
        self.assertEqual(observed, ["Bearer " + stale, "Bearer " + current])
        self.assertEqual(client.token, current)
        self.assertEqual(client._token_candidates[0], current)

    def test_client_reports_auth_required_after_every_candidate_fails(self) -> None:
        from houdini_bridge import client as client_module

        first, second = "a" * 32, "b" * 32
        with unittest.mock.patch.object(client_module, "bridge_tokens_for_port", return_value=(second,)):
            client = client_module.HoudiniClient(8116, token=first)

        def reject(request, **_kwargs):
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                None,
                io.BytesIO(b'{"status":"error","error":{"code":"AUTH_REQUIRED","message":"bad token"}}'),
            )

        with unittest.mock.patch.object(client_module.urllib.request, "urlopen", side_effect=reject) as urlopen:
            with self.assertRaises(client_module.BridgeError) as caught:
                client.health()
        self.assertEqual(caught.exception.code, "AUTH_REQUIRED")
        self.assertEqual(urlopen.call_count, 2)

    def test_cli_preserves_discovered_token(self) -> None:
        from houdini_bridge import __main__ as cli_module
        from houdini_bridge.client import HoudiniInstance

        token = "c" * 32
        instance = HoudiniInstance(8112, {"pid": 2}, "health", token=token)
        sentinel = object()
        with unittest.mock.patch.object(cli_module, "discover_instances", return_value=[instance]):
            with unittest.mock.patch.object(cli_module, "HoudiniClient", return_value=sentinel) as client:
                self.assertIs(cli_module._client(None), sentinel)
        client.assert_called_once_with(8112, token=token)

    def test_pipeline_router_preserves_token_but_does_not_serialize_it(self) -> None:
        from vfx_pipeline.router import BridgeRouter

        token = "r" * 32
        instance = SimpleNamespace(port=8113, data={"pid": 3}, source="health", token=token)
        constructed = object()
        factory = unittest.mock.Mock(return_value=constructed)
        router = BridgeRouter(
            discoverers={
                "houdini": lambda: [instance],
                "nuke": lambda: [],
            },
            client_factories={
                "houdini": factory,
                "nuke": unittest.mock.Mock(),
            },
        )

        inventory = router.discover()
        endpoint = inventory["houdini"][0]
        self.assertEqual(endpoint.token, token)
        self.assertNotIn("token", endpoint.to_dict())
        self.assertNotIn(token, repr(endpoint))
        self.assertIs(router.client("houdini"), constructed)
        factory.assert_called_once_with(8113, token=token)


if __name__ == "__main__":
    unittest.main()
