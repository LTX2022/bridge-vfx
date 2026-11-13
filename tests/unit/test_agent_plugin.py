from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_agent_plugin


def load_file(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    with patch.object(sys, "dont_write_bytecode", True):
        specification.loader.exec_module(module)
    return module


@contextmanager
def installed_runtime(plugin):
    prefixes = ("dcc_task_runtime", "houdini_bridge", "nuke_bridge", "vfx_pipeline",
                "prepare_workbuddy", "prepare_workbuddy_graph")
    def selected(name):
        return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)

    saved_modules = {name: value for name, value in sys.modules.items() if selected(name)}
    saved_path = sys.path[:]
    for name in saved_modules:
        del sys.modules[name]
    development = {str(ROOT), str(ROOT / "tools"), str(ROOT / "tests/unit"), str(ROOT / "tests/contract"),
                   str(ROOT / "outputs/windows-followup-20261004")}
    development.update(str(ROOT / "packages" / package / "src") for package in
                       ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"))
    sys.path[:] = [item for item in sys.path if str(Path(item).absolute()) not in development]
    sys.path.insert(0, str(plugin / "runtime/tools"))
    try:
        with patch.object(sys, "dont_write_bytecode", True):
            yield
    finally:
        for name in list(sys.modules):
            if selected(name):
                del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


class PluginPortabilityTests(unittest.TestCase):
    def test_native_exceptions_ordinary_resources_and_utf8_boundaries(self):
        native_resources = ('docs/native-basis/hda-interface-capture.json',
                            'docs/native-basis/native-boundary-metadata-supplement.json',
                            'docs/native-basis/hda-interface-22.0.459.json',
                            'docs/native-basis/supporting-sources-22.0.459.json')
        ordinary = ('docs/real-acceptance-cards/nuke_composite_v1.json',
                    'docs/real-acceptance-cards/README.md', 'tools/entry.py',
                    'docs/native-basis/h22-459-originals/raw-sections/example.DialogScript.txt',
                    'docs/native-basis/hda-interface-22.0.459.extra.json')
        ordinary_payloads = (b'{"native_basis_status":"UNRESOLVED"}',
                             '# 操作卡\n'.encode('utf-8'), b'print("portable")\n', b'parm { name example }', b'{}')
        cases = [(name, payload, None) for name,payload in zip(ordinary,ordinary_payloads)]
        cases += [(name, b'\xff', 'invalid UTF-8 text') for name in ordinary]
        personal = ('/Users/'+'user/private').encode('utf-8')
        cases += [(name, personal, 'non-portable path') for name in ordinary]
        cases.append(('assets/binary.bin', b'\x00\xff', None))
        for name in native_resources:
            cases.append((name, b'{"native_execution":false,"source":"'+personal+b'"}', None))
            for payload in (b'{}', b'{"native_execution":true}', b'{"native_execution":0}'):
                cases.append((name, payload, 'native metadata must be static evidence'))
        with tempfile.TemporaryDirectory(prefix='bridge-plugin-portable-core-') as temporary:
            root=Path(temporary)
            for index,(name,payload,error) in enumerate(cases):
                staging=root/str(index); path=staging/'runtime'/name
                path.parent.mkdir(parents=True); path.write_bytes(payload)
                with self.subTest(name=name,payload=payload):
                    if error:
                        with self.assertRaisesRegex(ValueError,error):
                            build_agent_plugin.assert_plugin_portable(staging,[name])
                    else:
                        build_agent_plugin.assert_plugin_portable(staging,[name])


class AgentPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="bridge-agent-plugin-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        report = build_agent_plugin.build_plugin("0.1.0", cls.directory / "outputs" / "build")
        cls.artifact = json.loads(report.read_text(encoding="utf-8"))["artifacts"][0]
        cls.archive = report.parent / cls.artifact["archive"]
        cls.plugin = cls.directory / "clean install 中文"
        cls.plugin.mkdir()
        build_agent_plugin.validate_archive(cls.archive, cls.artifact)
        with zipfile.ZipFile(cls.archive) as package:
            package.extractall(cls.plugin)
        cls.launcher = load_file("bridge_plugin_launcher_test", cls.plugin / "scripts/bridge_mcp.py")
        cls.prepared_run = cls.directory / "prepared 中文/control/run.json"
        cls.config = cls.directory / "external-config.json"
        cls.base_config = {"prepared_run": str(cls.prepared_run), "scheduler_root": str(cls.directory / "scheduler"),
                           "backend": "diagnostic"}
        with installed_runtime(cls.plugin), patch("subprocess.Popen", side_effect=AssertionError("no child")), \
                patch("socket.socket", side_effect=AssertionError("no network")):
            cls.launcher.load_runtime(cls.plugin)
            import prepare_workbuddy_graph
            prepare_workbuddy_graph.prepare_graph(cls.prepared_run.parents[1], app=None,
                                                   scheduler_root=cls.directory / "scheduler", execution_profile=False)

    def setUp(self):
        self.config.write_text(json.dumps(self.base_config), encoding="utf-8")

    def exchange(self, calls):
        requests = [{"jsonrpc": "2.0", "id": "initialize", "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {"name": "plugin-test", "version": "1"}, "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"}]
        requests.extend({"jsonrpc": "2.0", "id": str(index), "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}}
                        for index, (name, arguments) in enumerate(calls))
        source = io.BytesIO(("\n".join(json.dumps(item) for item in requests) + "\n").encode())
        target = io.StringIO()
        with installed_runtime(self.plugin), patch("subprocess.Popen", side_effect=AssertionError("no child")), \
                patch("socket.socket", side_effect=AssertionError("no network")):
            self.launcher.serve_connection(self.config, root=self.plugin, stdin=source, stdout=target)
            import vfx_pipeline.workbuddy_graph_mcp
            self.assertTrue(Path(vfx_pipeline.workbuddy_graph_mcp.__file__).is_relative_to(self.plugin))
        responses = {item["id"]: item for item in map(json.loads, target.getvalue().splitlines())}
        self.assertTrue(all("error" not in item for item in responses.values()), responses)
        return responses

    def payload(self, responses, identifier):
        return json.loads(responses[identifier]["result"]["content"][0]["text"])

    def context(self):
        root = self.directory / "private context 中文"
        root.mkdir(exist_ok=True)
        value = {"schema": "bridge.private-context/1", "document_id": "style", "project_id": "project-a",
                 "source_type": "preference", "domain": "crowd_agents_v1", "version": "21.0.631",
                 "topic": "style", "reference": "brief#style", "content": "Prefer quiet crowd movement."}
        document = root / "style.json"
        document.write_text(json.dumps(value), encoding="utf-8")
        context = {"root": str(root), "project_id": "project-a",
                   "documents": {"style.json": hashlib.sha256(document.read_bytes()).hexdigest()}}
        self.config.write_text(json.dumps({**self.base_config, "private_context": context}), encoding="utf-8")
        return document

    def test_package_layout_one_runtime_and_posix_sorted_manifest(self):
        self.assertEqual(build_agent_plugin.validate_layout(self.plugin)["version"], "0.1.0")
        self.assertEqual(self.launcher.verify_package(self.plugin), self.plugin)
        names = [entry["path"] for entry in self.artifact["files"]]
        self.assertEqual(names, sorted(names))
        self.assertTrue(all("\\" not in name for name in names))
        for package in self.launcher.PACKAGES:
            self.assertTrue((self.plugin / "runtime/packages" / package / "src").is_dir())
        self.assertFalse(any("controller-entry" in name or name.startswith("skills/") and "/runtime/" in name for name in names))
        self.assertFalse((self.plugin / "connection.json").exists())
        with self.assertRaises(FileExistsError):
            build_agent_plugin.build_plugin("0.1.0", self.archive.parent)

    def test_real_health_catalog_tools_and_unconfigured_context(self):
        arguments = {"domain": "crowd_agents_v1", "version": "21.0.631"}
        responses = self.exchange([("health", {}), ("graph_catalog", {}), ("private_context_query", arguments)])
        tools = {tool["name"]: tool for tool in responses["tools"]["result"]["tools"]}
        self.assertTrue({"health", "graph_catalog", "graph_propose", "graph_trial", "frame_execute",
                         "private_context_query"} <= tools.keys())
        self.assertTrue(tools["private_context_query"]["annotations"]["readOnlyHint"])
        self.assertFalse(self.payload(responses, "0")["dcc_dispatch_enabled"])
        self.assertTrue(self.payload(responses, "1"))
        self.assertEqual(self.payload(responses, "2")["status"], "not_configured")
        print(json.dumps({"mcp_tools": sorted(tools), "dcc_dispatch_enabled": False,
                          "private_context": "not_configured", "transport": "in_process_jsonrpc"}))

    def test_context_real_core_scope_schema_and_budget(self):
        self.context()
        query = {"domain": "crowd_agents_v1", "version": "21.0.631", "query": "quiet"}
        attacks = [{**query, "root": "elsewhere"}, {**query, "project_id": "project-b"},
                   {**query, "documents": {}}, {**query, "limit": 5}, {**query, "read_budget": True}]
        responses = self.exchange([("private_context_query", query),
                                   ("private_context_query", {**query, "read_budget": 1}),
                                   *[("private_context_query", attack) for attack in attacks]])
        result = self.payload(responses, "0")
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["content_role"], "untrusted_data")
        self.assertEqual(result["project_id"], "project-a")
        self.assertEqual(result["matches"][0]["reference"], "brief#style")
        self.assertEqual(self.payload(responses, "1"), {"code": "read_budget_exceeded"})
        for identifier in range(2, 2 + len(attacks)):
            self.assertTrue(responses[str(identifier)]["result"]["isError"])
            self.assertEqual(self.payload(responses, str(identifier)), {"code": "INVALID_ARGUMENTS"})

    def test_context_hash_failure_returns_only_code(self):
        document = self.context()
        document.write_text("changed private secret", encoding="utf-8")
        responses = self.exchange([("private_context_query", {"domain": "crowd_agents_v1", "version": "21.0.631"})])
        self.assertEqual(self.payload(responses, "0"), {"code": "document_hash_mismatch"})
        self.assertNotIn("changed private secret", json.dumps(responses))

    def test_extreme_expiry_returns_code_and_mcp_continues(self):
        document = self.context()
        content = json.loads(document.read_text(encoding="utf-8"))
        content["expires_at"] = "0001-01-01T00:00:00+23:59"
        document.write_text(json.dumps(content), encoding="utf-8")
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["private_context"]["documents"][document.name] = hashlib.sha256(document.read_bytes()).hexdigest()
        self.config.write_text(json.dumps(config), encoding="utf-8")
        responses = self.exchange([("private_context_query", {"domain": "crowd_agents_v1", "version": "21.0.631"}),
                                   ("health", {})])
        self.assertEqual(self.payload(responses, "0"), {"code": "invalid_expiry"})
        self.assertFalse(self.payload(responses, "1")["dcc_dispatch_enabled"])
        self.assertNotIn(content["content"], json.dumps(responses))

    def test_missing_config_graph_and_production_scene_refused(self):
        with self.assertRaisesRegex(ValueError, "BRIDGE_CONFIG_REQUIRED"):
            self.launcher.connection(self.directory / "missing.json")
        cases = [({**self.base_config, "prepared_run": str(self.directory / "missing-run.json")}, "PREPARED_GRAPH_REQUIRED"),
                 ({**self.base_config, "backend": "production"}, "PRODUCTION_CONFIG_REQUIRED"),
                 ({**self.base_config, "backend": "software"}, "BRIDGE_BACKEND_INVALID"),
                 ({**self.base_config, "private_context": {"root": "relative"}}, "PRIVATE_CONTEXT_CONFIG_INVALID")]
        for value, code in cases:
            with self.subTest(code=code):
                self.config.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, code):
                    self.launcher.serve_connection(self.config, root=self.plugin)
        self.assertTrue(self.config.is_file())

    def test_unregistered_importable_files_directories_and_case_alias_rejected(self):
        extras = ["runtime/packages/vfx-pipeline/src/shadow.py", "runtime/packages/vfx-pipeline/src/shadow.pyc",
                  "runtime/packages/vfx-pipeline/src/vfx_pipeline/SHADOW.py", "runtime/tools/shadow/__init__.py"]
        for name in extras:
            path = self.plugin / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"shadow")
            try:
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "PLUGIN_UNLISTED_FILE"):
                    self.launcher.verify_package(self.plugin)
            finally:
                path.unlink()
                if path.parent.name == "shadow":
                    path.parent.rmdir()
        path = self.plugin / "runtime/tools/namespace_shadow"
        path.mkdir()
        try:
            with self.assertRaisesRegex(ValueError, "PLUGIN_UNLISTED_FILE"):
                self.launcher.verify_package(self.plugin)
        finally:
            path.rmdir()
        manifest_path = self.plugin / "runtime-manifest.json"
        original = manifest_path.read_bytes()
        manifest = json.loads(original)
        entry = dict(manifest["files"][0])
        entry["path"] = entry["path"].upper()
        manifest["files"].append(entry)
        manifest["file_manifest_sha256"] = build_agent_plugin.build_release.file_manifest_sha256(manifest["files"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError, "PLUGIN_MANIFEST_DUPLICATE"):
                self.launcher.verify_package(self.plugin)
        finally:
            manifest_path.write_bytes(original)

    def test_changed_bytes_rejected_external_and_root_config_preserved(self):
        path = self.plugin / "scripts/bridge_mcp.py"
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        try:
            with self.assertRaisesRegex(ValueError, "PLUGIN_BYTES_CHANGED"):
                self.launcher.verify_package(self.plugin)
        finally:
            path.write_bytes(original)
        config = self.plugin / "connection.json"
        config.write_bytes(self.config.read_bytes())
        try:
            self.launcher.verify_package(self.plugin)
            self.assertTrue(config.is_file())
            self.assertTrue(self.config.is_file())
        finally:
            config.unlink()

    def test_archive_path_link_case_unicode_and_manifest_attacks(self):
        cases = [[("../shadow.py", None)], [("runtime\\shadow.py", None)],
                 [("shadow.py", None), ("SHADOW.py", None)], [("é.py", None), ("e\u0301.py", None)],
                 [("shadow.py", stat.S_IFLNK | 0o777)], [("unexpected.py", None)]]
        for index, members in enumerate(cases):
            archive = self.directory / ("attack-" + str(index) + ".zip")
            with zipfile.ZipFile(archive, "w") as package:
                for name, mode in members:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (mode or stat.S_IFREG | 0o644) << 16
                    package.writestr(info, b"attack")
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_agent_plugin.validate_archive(archive, self.artifact)

    def test_empty_archive_and_manifest_are_rejected(self):
        archive = self.directory / "empty.zip"
        artifact = {"files": [], "file_manifest_sha256": build_agent_plugin.build_release.file_manifest_sha256([])}
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("runtime-manifest.json", json.dumps({"schema_version": 1, **artifact}))
        with self.assertRaisesRegex(ValueError, "missing required entrypoints"):
            build_agent_plugin.validate_archive(archive, artifact)
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            build_agent_plugin.build_release.validate_packaged_bytes(archive, artifact)

    def test_external_preloaded_core_module_is_rejected(self):
        with installed_runtime(self.plugin):
            external = types.ModuleType("vfx_pipeline.workbuddy_assembly")
            external.__file__ = str(ROOT / "packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py")
            with patch.dict(sys.modules, {external.__name__: external}):
                with self.assertRaisesRegex(ValueError, "PLUGIN_EXTERNAL_RUNTIME_MODULE"):
                    self.launcher.load_runtime(self.plugin)

    def test_unauthorized_construction_refused_before_host_or_database_creation(self):
        manifest = json.loads(self.prepared_run.read_text(encoding="utf-8"))
        manifest["production_host"] = {"lifecycle": "task_owned", "executable": "NEVER_A_DCC"}
        manifest["production_nuke"] = {"lifecycle": "task_owned", "executable": "NEVER_A_DCC"}
        self.config.write_text(json.dumps({**self.base_config, "backend": "production"}), encoding="utf-8")
        original = self.prepared_run.read_bytes()
        try:
            for value in (False, None):
                candidate = dict(manifest)
                if value is None:
                    candidate.pop("construction_authorized", None)
                else:
                    candidate["construction_authorized"] = value
                self.prepared_run.write_text(json.dumps(candidate), encoding="utf-8")
                with self.subTest(authorization=value), installed_runtime(self.plugin):
                    self.launcher.load_runtime(self.plugin)
                    with patch("vfx_pipeline.production_hosts.ensure_hosts") as ensure_hosts, \
                            patch("vfx_pipeline.service.ModelSafePipeline") as pipeline:
                        with self.assertRaisesRegex(ValueError, "construction authorization required"):
                            self.launcher.serve_connection(self.config, root=self.plugin)
                        ensure_hosts.assert_not_called()
                        pipeline.assert_not_called()
        finally:
            self.prepared_run.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
