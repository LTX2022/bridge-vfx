from __future__ import annotations

import importlib.util
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/houdini-bridge/src"))


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"tools/{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


capture = load_tool("capture_native_schema")
documentation = load_tool("audit_domain_native_basis")
report = load_tool("audit_native_basis_report")


class NativeInstallCaptureTests(unittest.TestCase):
    def archive(self, members):
        entries = []
        payload = bytearray()
        for name, data in members.items():
            encoded = name.encode("utf-8")
            entries.append(struct.pack(">I", len(encoded)) + encoded +
                           struct.pack(">III", len(payload), len(data), 0))
            payload.extend(data)
        return b"INDX" + bytes(8) + struct.pack(">I", len(entries)) + b"".join(entries) + payload

    def install(self, root, version, layout):
        directory = (root / ("Houdini " + version) / "houdini" if layout == "windows" else
                     root / ("Houdini" + version) / "Frameworks/Houdini.framework/Versions" /
                     version[:4] / "Resources/houdini")
        (directory / "otls").mkdir(parents=True)
        (directory / "help").mkdir()
        dialog = '''{
 name source
 parm {
  name testfield
  type float
  label "测试字段"
  default { "0.5" }
 }
}
'''.encode("utf-8")
        raw = self.archive({"Sop/pyrosource": self.archive({"DialogScript": dialog})})
        (directory / "otls/OPlibSop.hda").write_bytes(raw)
        with zipfile.ZipFile(directory / "help/nodes.zip", "w") as archive:
            archive.writestr("sop/pyrosource.txt", "#context: sop\n#internal: pyrosource\n#id: testfield\n测试帮助\n".encode("utf-8"))
        return directory, raw, dialog

    def assert_captured(self, result, version, raw, dialog):
        record = result["versions"][version]
        self.assertEqual(record["archives"]["OPlibSop.hda"]["sha256"], hashlib.sha256(raw).hexdigest())
        operator = record["operators"]["Sop/pyrosource"]
        self.assertEqual(operator["section_sha256"], hashlib.sha256(dialog).hexdigest())
        self.assertEqual(operator["parameters"]["testfield"]["label"], "测试字段")
        self.assertIsNone(operator["port_signature"]["full_node_port_arity"])
        self.assertFalse(result["native_execution"])

    def test_default_macos_layout_still_reads_both_contract_builds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            originals = {version: self.install(root, version, "macos") for version in ("21.0.631", "22.0.459")}
            result = capture.capture(root)
            documented = documentation.audit(root)
            self.assertEqual(set(result["versions"]), {"21.0.631", "22.0.459"})
            self.assertEqual(set(documented["versions"]), {"21.0.631", "22.0.459"})
            for version, (directory, raw, dialog) in originals.items():
                self.assert_captured(result, version, raw, dialog)
                self.assertEqual(documented["versions"][version]["archive"], str(directory / "help/nodes.zip"))
            self.assertFalse(documented["real_dcc_executed"])

    def test_windows_parent_reads_exact_builds_without_other_build_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "安装 根"
            directory, raw, dialog = self.install(root, "21.0.631", "windows")
            self.install(root, "22.0.368", "windows")
            result = capture.capture(root, layout="windows")
            documented = documentation.audit(root, layout="windows")
            self.assert_captured(result, "21.0.631", raw, dialog)
            self.assertEqual(result["versions"]["22.0.459"]["archives"]["OPlibSop.hda"]["status"], "MISSING")
            self.assertEqual(documented["versions"]["22.0.459"]["reason"], "DOCUMENT_ARCHIVE_MISSING")
            self.assertEqual(documented["versions"]["21.0.631"]["archive_sha256"],
                             hashlib.sha256((directory / "help/nodes.zip").read_bytes()).hexdigest())
            self.assertNotIn("22.0.368", result["versions"])
            for domain in documented["versions"]["21.0.631"]["domains"].values():
                for gate in ("topology_validated", "parameter_values_validated", "port_semantics_validated", "native_execution"):
                    self.assertFalse(domain[gate])

    def test_explicit_build_directory_rejects_cross_build_and_unknown_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, raw, dialog = self.install(root, "22.0.429", "windows")
            build_root = directory.parent
            for tool in (capture.capture, documentation.audit):
                result = tool(build_root, layout="windows", versions=("22.0.429",))
                self.assertEqual(set(result["versions"]), {"22.0.429"})
                with self.assertRaises(ValueError):
                    tool(build_root, layout="windows", versions=("21.0.631",))
                with self.assertRaises(ValueError):
                    tool(root, layout="windows", versions=("22.0.368",))
                with self.assertRaises(ValueError):
                    tool(root, layout="guess")
            self.assert_captured(capture.capture(build_root, layout="windows", versions=("22.0.429",)),
                                 "22.0.429", raw, dialog)

    def test_both_cli_outputs_are_utf8_with_non_ascii_paths_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "安装 根"
            self.install(root, "21.0.631", "windows")
            for tool in (capture, documentation):
                output = Path(temporary) / (tool.__name__ + "-采集.json")
                arguments = [tool.__name__, "--install-root", str(root), "--install-layout", "windows",
                             "--build", "21.0.631", "--output", str(output)]
                encodings = []
                original_open = Path.open

                def open_output(path, mode="r", *args, **kwargs):
                    if mode == "x":
                        encodings.append(kwargs.get("encoding"))
                    return original_open(path, mode, *args, **kwargs)

                with mock.patch.object(sys, "argv", arguments), mock.patch.object(Path, "open", open_output):
                    tool.main()
                self.assertEqual(encodings, ["utf-8"])
                result = json.loads(output.read_bytes().decode("utf-8"))
                self.assertEqual(set(result["versions"]), {"21.0.631"})
                self.assertEqual(result["capture_metadata"]["install_layout"], "windows")
                self.assertEqual(result["capture_metadata"]["install_root"], str(root))
                self.assertFalse(result["native_execution"])

    def test_cli_rejects_existing_output_links_and_creation_race_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            for tool, operation in ((capture, "capture"), (documentation, "audit")):
                with self.subTest(tool=tool.__name__):
                    output = Path(temporary) / (tool.__name__ + ".json")
                    sentinel = b"original vendor or historical evidence"
                    arguments = [tool.__name__, "--output", str(output)]
                    output.write_bytes(sentinel)
                    with mock.patch.object(sys, "argv", arguments), mock.patch.object(tool, operation) as parser:
                        with self.assertRaises(FileExistsError):
                            tool.main()
                        parser.assert_not_called()
                    self.assertEqual(output.read_bytes(), sentinel)
                    output.unlink()
                    with mock.patch.object(sys, "argv", arguments), mock.patch.object(tool, operation) as parser, \
                            mock.patch.object(Path, "is_symlink", return_value=True):
                        with self.assertRaises(FileExistsError):
                            tool.main()
                        parser.assert_not_called()
                    original_open = Path.open

                    def race_open(path, mode="r", *args, **kwargs):
                        if path == output and mode == "x":
                            with original_open(path, "wb") as winner:
                                winner.write(sentinel)
                        return original_open(path, mode, *args, **kwargs)

                    with mock.patch.object(sys, "argv", arguments), mock.patch.object(tool, operation, return_value={}), \
                            mock.patch.object(Path, "open", race_open):
                        with self.assertRaises(FileExistsError):
                            tool.main()
                    self.assertEqual(output.read_bytes(), sentinel)

    def test_help_archive_replacement_cannot_split_document_and_archive_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, raw, dialog = self.install(Path(temporary), "21.0.631", "windows")
            archive = directory / "help/nodes.zip"
            with zipfile.ZipFile(archive, "w") as fixture:
                fixture.writestr("sop/sphere.txt", "#context: sop\n#internal: sphere\n#id: testfield\n")
            original_bytes = archive.read_bytes()
            original_load = documentation._load_help_docs
            original_read = Path.read_bytes
            reads = []

            def read_bytes(path):
                if path == archive:
                    reads.append(path)
                return original_read(path)

            def replace_after_load(open_archive):
                result = original_load(open_archive)
                with zipfile.ZipFile(archive, "w") as replacement:
                    replacement.writestr("sop/sphere.txt", "#context: sop\n#internal: sphere\n#id: replacement_only\n")
                return result

            with mock.patch.object(documentation, "_load_help_docs", replace_after_load), \
                    mock.patch.object(Path, "read_bytes", read_bytes):
                result = documentation.audit(Path(temporary), layout="windows", versions=("21.0.631",))
            version = result["versions"]["21.0.631"]
            self.assertEqual(len(reads), 1)
            self.assertEqual(version["archive_sha256"], hashlib.sha256(original_bytes).hexdigest())
            self.assertEqual(version["archive_size_bytes"], len(original_bytes))
            self.assertNotEqual(version["archive_sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            documents = [document for domain in version["domains"].values() for node in domain["nodes"]
                         for candidate in node["candidate_facts"] for document in candidate["documents"]]
            source = next(document for document in documents if document["entry"] == "sop/sphere.txt")
            self.assertIn("testfield", source["documented_ids"])
            self.assertNotIn("replacement_only", source["documented_ids"])

    def test_preloaded_external_catalog_and_locator_are_rejected(self):
        import houdini_bridge
        from houdini_bridge import domain_packs

        with tempfile.TemporaryDirectory() as temporary:
            foreign = str(Path(temporary) / "other-checkout.py")
            catalog = SimpleNamespace(__file__=foreign, all_domain_packs=mock.Mock(return_value=()))
            with mock.patch.object(houdini_bridge, "domain_packs", catalog), \
                    mock.patch.dict(sys.modules, {"houdini_bridge.domain_packs": catalog}):
                with self.assertRaisesRegex(ValueError, "module source"):
                    documentation.audit(Path(temporary), layout="windows")
            catalog.all_domain_packs.assert_not_called()
            self.assertEqual(Path(domain_packs.__file__).resolve(),
                             (ROOT / "packages/houdini-bridge/src/houdini_bridge/domain_packs.py").resolve())
            for tool_name in ("capture_native_schema", "audit_domain_native_basis"):
                with self.subTest(tool=tool_name), mock.patch.dict(sys.modules, {
                    "native_install_paths": SimpleNamespace(__file__=foreign),
                }):
                    with self.assertRaisesRegex(ValueError, "locator source"):
                        load_tool(tool_name)
            for tool, operation in ((capture, "capture"), (documentation, "audit")):
                with self.subTest(api=tool.__name__), mock.patch.object(tool.native_paths, "__file__", foreign):
                    with self.assertRaisesRegex(ValueError, "module source"):
                        getattr(tool, operation)(Path(temporary), layout="windows")


class NativeDialogScriptCaptureTests(unittest.TestCase):
    def test_ports_are_normalized_and_vop_declarations_are_kept_separate(self):
        source = b'''inputlabel\t1\t"Input Stage"\noutputlabel 2 "Light Output"\ninput color base_color "Base Color"\noutput surface out out\nsignature "surface shader" default { color surface }\n'''
        result = capture.dialog_interface(source)
        self.assertEqual(result["input_labels"][0]["dialogscript_index"], 1)
        self.assertEqual(result["input_labels"][0]["api_index"], 0)
        self.assertEqual(result["output_labels"][0]["dialogscript_index"], 2)
        self.assertEqual(result["output_labels"][0]["api_index"], 1)
        self.assertEqual(result["inputs"][0]["name"], "base_color")
        self.assertEqual(result["outputs"][0]["name"], "out")
        self.assertEqual(result["signatures"][0]["type_tokens"], ["color", "surface"])
        self.assertIsNone(result["port_signature"]["full_node_port_arity"])

    def test_machine_fields_following_multi_value_directives_and_valueless_flags_are_retained(self):
        source = b'''# vendor-generated header
{
 name example
 inputlabel 1 "Geometry"
 outputlabel 1 "Output"
 bindhandle tx boundingbox "Bounds" centerx ""
 parm {
  name particlesep
  type float
  default { "0.1" }
 }
 parm {
  name exponent
  type ordinal
  default { "10" }
  menu usetokenvalue { "10" "1e10" "0" "1" "-10" "1e-10" }
 }
 groupsimple {
  name general
  parm {
   name attrib
   type string
   nolabel
   joinnext
   default { "pscale" }
   disablewhen "{ enabled == 0 }"
  }
 }
}
'''
        result = capture.dialog_parameters(source)
        self.assertEqual(result["particlesep"]["default_tokens"], ["0.1"])
        self.assertEqual(result["attrib"]["default_tokens"], ["pscale"])
        self.assertEqual(result["attrib"]["disable_when"], "{ enabled == 0 }")
        self.assertEqual(result["attrib"]["ancestors"], ["example", "general"])
        self.assertIn("attrib", result["general"]["children"])
        self.assertEqual(result["exponent"]["menu_tokens"],["10","1e10","0","1","-10","1e-10"])
        self.assertTrue(result["exponent"]["menu_uses_token_value"])
        self.assertEqual(result["exponent"]["default_tokens"],["10"])

    def test_invalid_label_index_is_not_silently_treated_as_api_index(self):
        result = capture.dialog_interface(b"inputlabel 0 \"Invalid\"\n")
        self.assertIsNone(result["input_labels"][0]["api_index"])
        self.assertEqual(result["input_labels"][0]["status"], "INVALID_NONPOSITIVE_LABEL_INDEX")


class NativeHelpReferenceTests(unittest.TestCase):
    def test_alternative_node_candidates_do_not_borrow_parameter_ids(self):
        fact = documentation._documented_control_ids(
            ("radius",),
            {"domelight": set(), "light": {"radius"}},
            {"domelight": True, "light": True},
        )
        self.assertEqual(fact["documented_aliases"], [])
        self.assertEqual(fact["documented_aliases_by_candidate"], {"domelight": [], "light": ["radius"]})
        self.assertEqual(fact["status"], "CANDIDATE_SPECIFIC_ONLY")

    def test_redirect_and_fragment_include_capture_exact_ids_and_sources(self):
        docs = {
            "lop/usdrender_rop.txt": b"#context: lop\n#internal: usdrender_rop\n#redirect: /nodes/out/usdrender\n",
            "out/usdrender.txt": b"#context: out\n#internal: usdrender\n#id: execute\n:include usd#render_settings_block/:\n",
            "out/usd.txt": b":box:\n    #id: render_settings_block\n    Render Settings:\n        #id: rendersettings\n    Camera:\n        #id: override_camera\n    #id: outputimage\n:box:\n    #id: unrelated_block\n    #id: unrelated_id\n",
        }
        result = documentation._expand_doc_entry("lop/usdrender_rop.txt", docs)
        self.assertIn("#id: execute", result["text"])
        self.assertIn("#id: rendersettings", result["text"])
        self.assertIn("#id: override_camera", result["text"])
        self.assertNotIn("#id: unrelated_block", result["text"])
        self.assertEqual(result["redirect_chain"], ["lop/usdrender_rop.txt", "out/usdrender.txt"])
        self.assertEqual([item["entry"] for item in result["sources"]], ["lop/usdrender_rop.txt", "out/usdrender.txt", "out/usd.txt"])
        self.assertEqual(result["unresolved"], [])

    def test_redirect_and_include_cycles_are_reported_and_paths_cannot_escape_archive(self):
        redirect_cycle = {
            "a.txt": b"#redirect: /nodes/b\n",
            "b.txt": b"#redirect: /nodes/a\n",
        }
        result = documentation._expand_doc_entry("a.txt", redirect_cycle)
        self.assertTrue(any(item["code"] == "DOCUMENT_REFERENCE_CYCLE" for item in result["unresolved"]))
        self.assertIsNone(documentation._resolve_doc_reference("lop/a.txt", "../../outside", {"outside.txt": b""}))

    def test_documented_name_is_not_reported_missing_when_only_hda_capture_is_absent(self):
        from houdini_bridge.domain_packs import get_domain_pack

        pack = get_domain_pack("lighting_camera_render_v1")
        doc = {
            "nodes": [{
                "role": "render",
                "node_fact_status": "DOCUMENTED_NAME",
                "documents": [{"entry": "lop/usdrender_rop.txt"}],
                "controls": [],
            }],
            "unresolved": [],
        }
        result = report._domain_report(pack, doc, {})
        render_fact = next(item for item in result["node_facts"] if item["role"] == "render")
        self.assertEqual(render_fact["documentation_status"], "DOCUMENTED_NAME")
        self.assertEqual(render_fact["hda_operator_status"], "NO_STATIC_OPERATOR_CAPTURE")
        self.assertNotIn("render", [item["role"] for item in result["missing_node_facts"]])
        self.assertFalse(result["native_execution"])
        self.assertEqual(result["execution_evidence_status"], "NOT_EXECUTED")

    def test_static_parameter_ids_are_not_borrowed_across_alternative_operators(self):
        from houdini_bridge.domain_packs import get_domain_pack

        node = next(node for node in get_domain_pack("lighting_camera_render_v1").nodes if node.role == "light")
        node = replace(node, type_candidates=("domelight", "light"))
        fact = report._candidate_static_parameter_matches(node, {
            "Lop/domelight": {"status": "CAPTURED", "parameters": {"intensity": {}}},
            "Lop/light": {"status": "CAPTURED", "parameters": {"radius": {}}},
        }, ["radius"])
        self.assertEqual(fact["matches"], [])
        self.assertEqual(fact["matches_by_candidate"], {"Lop/domelight": [], "Lop/light": ["radius"]})


if __name__ == "__main__":
    unittest.main()
