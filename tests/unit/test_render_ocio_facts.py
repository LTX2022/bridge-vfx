"""Explicit bottom-level HOM, OCIO and filesystem substitutes; no DCC execution."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "packages/houdini-bridge/src/houdini_bridge/render_ocio_facts.py"
SPEC = importlib.util.spec_from_file_location("bridge_test_render_ocio_facts", MODULE_PATH)
ocio_facts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ocio_facts)
collect = ocio_facts.collect_ocio_configuration
validate = ocio_facts.validate_ocio_configuration


class NativeColor:
    def __init__(self, path):
        self.path = path

    def ocio_configPath(self):
        return self.path

    def ocio_spaces(self):
        return ("scene_linear", "output_space")

    def ocio_roles(self):
        return ("scene_linear",)

    def ocio_activeDisplays(self):
        return ("display",)

    def ocio_activeViews(self):
        return ("view",)


class NativeContext:
    def __init__(self, directory):
        self.directory = directory
        self.references = []

    def getCacheID(self):
        return "context-cache"

    def getSearchPath(self):
        return "LUT 目录"

    def getWorkingDir(self):
        return str(self.directory)

    def resolveFileLocation(self, reference):
        self.references.append(reference)
        return str(self.directory / reference)

    def getStringVars(self):
        raise AssertionError("must not enumerate environment credentials")


class NativeFileRules:
    def getNumEntries(self):
        return 1

    def getName(self, index):
        return "Default"

    def getColorSpace(self, index):
        return "output_space"

    def getPattern(self, index):
        return ""

    def getExtension(self, index):
        return ""

    def getRegex(self, index):
        return ""


class NativeMetadata:
    def __init__(self, references):
        self.references = references

    def getFiles(self):
        return tuple(self.references)


class NativeProcessor:
    def __init__(self, references):
        self.metadata = NativeMetadata(references)

    def getCacheID(self):
        return "processor-cache"

    def getProcessorMetadata(self):
        return self.metadata


class NativeConfig:
    def __init__(self, directory, references=()):
        self.context = NativeContext(directory)
        self.processor = NativeProcessor(references)
        self.rules = NativeFileRules()
        self.output_paths = []
        self.processor_requests = []

    def getCacheID(self):
        return "config-cache-is-not-file-sha"

    def getSearchPath(self):
        return "LUT 目录"

    def getWorkingDir(self):
        return str(self.context.directory)

    def getCurrentContext(self):
        return self.context

    def getFileRules(self):
        return self.rules

    def getColorSpaceFromFilepath(self, path):
        self.output_paths.append(path)
        return ("output_space", 0)

    def getProcessor(self, context, source, destination):
        self.processor_requests.append((context, source, destination))
        return self.processor


class OcioPreflightTests(unittest.TestCase):
    def test_shared_read_allowance_counts_collection_rehash_and_restart(self):
        from houdini_bridge.render_observation_budget import FileReadBudget
        saved = self.directory / 'read-allowance.json'
        allowance = FileReadBudget(persist=lambda: saved.write_text(json.dumps(allowance.state)))
        facts = self.facts(read_budget=allowance)
        unit = self.config_path.stat().st_size + self.lut_path.stat().st_size + 2
        self.assertEqual(allowance.state['used_bytes'], 2 * unit)
        restarted = FileReadBudget(json.loads(saved.read_text()), persist=lambda: saved.write_text(json.dumps(restarted.state)))
        validate(facts, read_budget=restarted)
        self.assertEqual(restarted.state['used_bytes'], 3 * unit)
        for frame in range(1, 13):
            self.facts(final_output_path=self.output_path + str(frame), read_budget=restarted)
        self.assertEqual(restarted.state['used_bytes'], 27 * unit)

    def test_read_allowance_is_persisted_before_a_crash_and_budget_failure_is_not_a_gap(self):
        from houdini_bridge.render_observation_budget import FileReadBudget, MAX_FILE_READ_BYTES
        saved = self.directory / 'crash-allowance.json'
        allowance = FileReadBudget(persist=lambda: saved.write_text(json.dumps(allowance.state)))
        class SimulatedCrash(BaseException):
            pass
        with patch.object(ocio_facts.os, 'read', side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.facts(read_budget=allowance)
        before = self.config_path.stat().st_size + 1
        self.assertEqual(json.loads(saved.read_text())['used_bytes'], before)
        restored = FileReadBudget(json.loads(saved.read_text()))
        self.facts(read_budget=restored)
        self.assertGreater(restored.state['used_bytes'], before)
        restored.state['used_bytes'] = MAX_FILE_READ_BYTES
        with patch.object(ocio_facts.os, 'read', side_effect=AssertionError('budget refusal must precede any bytes')):
            with self.assertRaisesRegex(ValueError, 'file-read budget'):
                self.facts(read_budget=restored)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bridge-ocio-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "中文 空格"
        self.directory.mkdir()
        self.config_path = self.directory / "配置 config.ocio"
        self.config_path.write_bytes(b"native configuration fixture")
        self.lut_path = self.directory / "查找 table.cube"
        self.lut_path.write_bytes(b"native LUT fixture")
        self.hou = SimpleNamespace(Color=NativeColor(str(self.config_path)))
        self.config = NativeConfig(self.directory, (self.lut_path.name,))
        self.created_paths = []

        def create(path):
            self.created_paths.append(path)
            return self.config

        self.ocio = SimpleNamespace(Config=SimpleNamespace(CreateFromFile=create))
        self.output_path = str(self.directory / "最终 图像.0001.exr")
        self.requests = [{"label": "product:/Render/中文", "source": "scene_linear",
                          "destination": "output_space"}]

    def facts(self, **kwargs):
        arguments = {"final_output_path": self.output_path, "ocio_module": self.ocio,
                     "transform_requests": self.requests}
        arguments.update(kwargs)
        return collect(self.hou, **arguments)

    def codes(self, facts):
        return {gap["code"] for gap in facts["missing_facts"]}

    def test_static_basis_and_exact_chinese_paths(self):
        report = (ROOT / "handover/evidence/20261010/closure/native-output/REPORT.md").read_text("utf-8")
        self.assertIn("hou.Color.ocio_configPath()", report)
        self.assertIn("CreateFromFile", report)
        facts = self.facts()
        self.assertEqual(facts["schema"], "bridge.houdini.ocio-preflight/1.0")
        self.assertEqual(facts["source"], "parent_houdini_preflight")
        self.assertEqual(facts["final_output_path"], self.output_path)
        self.assertEqual(self.config.output_paths, [self.output_path])
        self.assertEqual(self.created_paths, [str(self.config_path)])
        self.assertEqual(self.config.processor_requests,
                         [(self.config.context, "scene_linear", "output_space")])
        self.assertEqual(facts["config"]["file"], {
            "path": str(self.config_path), "bytes": self.config_path.stat().st_size,
            "sha256": hashlib.sha256(self.config_path.read_bytes()).hexdigest()})
        self.assertEqual(facts["dependencies"], [{
            "path": str(self.lut_path), "bytes": self.lut_path.stat().st_size,
            "sha256": hashlib.sha256(self.lut_path.read_bytes()).hexdigest()}])
        self.assertEqual(facts, json.loads(json.dumps(facts, ensure_ascii=False)))
        validate(facts)
        self.assertEqual(facts, self.facts())

    def test_no_availability_or_effective_writer_proof(self):
        facts = self.facts()
        self.assertIn("PXL_EFFECTIVE_CONFIGURATION_UNOBSERVED", self.codes(facts))
        self.assertIn("DEPENDENCY_CLOSURE_UNOBSERVED", self.codes(facts))
        self.assertIn("WRITER_COLOR_ALPHA_UNOBSERVED", self.codes(facts))
        self.assertEqual(facts["reconstruction_scope"], "reloaded_config")
        for forbidden in ("AVAILABLE", "completion_metadata_status", "premultiplied",
                          '"effective_colorspace"', '"executed"'):
            self.assertNotIn(forbidden, json.dumps(facts))

    def test_missing_module_still_hashes_observed_config(self):
        with patch.object(ocio_facts.importlib, "import_module", side_effect=ModuleNotFoundError):
            facts = self.facts(ocio_module=None)
        self.assertIsNotNone(facts["config"]["file"])
        self.assertFalse(facts["api_facts"]["import.PyOpenColorIO"]["observed"])
        self.assertEqual(facts["dependencies"], [])
        validate(facts)

    def test_optional_import_uses_only_pyopencolorio(self):
        with patch.object(ocio_facts.importlib, "import_module", return_value=self.ocio) as importer:
            facts = self.facts(ocio_module=None)
        importer.assert_called_once_with("PyOpenColorIO")
        self.assertEqual(len(facts["dependencies"]), 1)

    def test_empty_builtin_relative_and_missing_paths_are_gaps(self):
        for path in ("", "ocio://builtin-config", "relative.ocio", str(self.directory / "absent.ocio")):
            with self.subTest(path=path):
                self.hou.Color.path = path
                facts = self.facts()
                self.assertEqual(facts["config"]["path"], path)
                self.assertIsNone(facts["config"]["file"])
                self.assertIn("CONFIG_FILE_UNOBSERVED", self.codes(facts))
                validate(facts)
        self.assertEqual(self.created_paths, [])

    def test_unknown_hom_and_ocio_apis_remain_gaps(self):
        facts = collect(SimpleNamespace(), final_output_path=self.output_path,
                        ocio_module=SimpleNamespace())
        self.assertIsNone(facts["config"]["path"])
        self.assertIn("API_UNAVAILABLE", self.codes(facts))
        validate(facts)
        facts = self.facts(ocio_module=SimpleNamespace())
        self.assertFalse(facts["api_facts"]["Config.CreateFromFile"]["observed"])
        validate(facts)

    def test_unknown_processor_metadata_has_no_fake_empty_observation(self):
        self.config.processor.metadata = SimpleNamespace(files=[str(self.lut_path)])
        facts = self.facts()
        self.assertFalse(facts["api_facts"]["Processor.0.ProcessorMetadata.getFiles"]["observed"])
        self.assertEqual(facts["dependencies"], [])
        self.assertIn("API_UNAVAILABLE", self.codes(facts))
        validate(facts)

    def test_no_requests_never_infers_processor_from_file_rule(self):
        facts = self.facts(transform_requests=())
        self.assertEqual(self.config.processor_requests, [])
        self.assertEqual(facts["api_facts"]["Config.getColorSpaceFromFilepath"]["value"],
                         ["output_space", 0])
        self.assertIn("PROCESSOR_REQUESTS_ABSENT", self.codes(facts))
        validate(facts)

    def test_successful_processor_can_observe_no_external_files(self):
        self.config.processor.metadata.references = ()
        facts = self.facts()
        self.assertEqual(facts["api_facts"]["Processor.0.ProcessorMetadata.getFiles"],
                         {"observed": True, "value": []})
        self.assertEqual(facts["dependencies"], [])
        validate(facts)

    def test_duplicate_dependency_deduplicates_across_explicit_pairs(self):
        self.config.processor.metadata.references = (self.lut_path.name, self.lut_path.name)
        facts = self.facts(transform_requests=self.requests + [
            {"label": "var:/Render/AOV", "source": "raw", "destination": "output_space"}])
        self.assertEqual(len(facts["dependencies"]), 1)
        self.assertEqual(len(self.config.processor_requests), 2)
        validate(facts)

    def test_config_and_lut_byte_drift_even_with_preserved_mtime(self):
        for path in (self.config_path, self.lut_path):
            with self.subTest(path=path):
                original = path.read_bytes()
                facts = self.facts()
                before = path.stat()
                path.write_bytes(b"X" * len(original))
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                with self.assertRaisesRegex(ValueError, "bytes drifted"):
                    validate(facts)
                path.write_bytes(original)

    def test_observed_file_removed_is_rejected(self):
        facts = self.facts()
        self.lut_path.unlink()
        with self.assertRaises(ValueError):
            validate(facts)

    def test_dependency_resolution_error_records_type_without_secret(self):
        self.config.context.resolveFileLocation = lambda reference: (_ for _ in ()).throw(
            RuntimeError("credential=DO_NOT_COPY"))
        facts = self.facts()
        self.assertNotIn("DO_NOT_COPY", json.dumps(facts))
        self.assertEqual(facts["dependencies"], [])
        self.assertIn("API_READ_FAILED", self.codes(facts))
        validate(facts)

    def test_file_and_total_byte_budgets(self):
        with patch.object(ocio_facts, "MAX_FILE_BYTES", 4):
            facts = self.facts()
            self.assertIsNone(facts["config"]["file"])
            self.assertEqual(self.created_paths, [])
        with patch.object(ocio_facts, "MAX_TOTAL_BYTES", self.config_path.stat().st_size + 1):
            facts = self.facts()
            self.assertEqual(facts["dependencies"], [])
            self.assertIn("DEPENDENCY_UNOBSERVED", self.codes(facts))

    def test_file_count_and_metadata_reference_budgets(self):
        second = self.directory / "second.cube"
        second.write_bytes(b"second")
        self.config.processor.metadata.references = (self.lut_path.name, second.name)
        with patch.object(ocio_facts, "MAX_FILES", 2):
            facts = self.facts()
            self.assertEqual(len(facts["dependencies"]), 1)
            self.assertIn("DEPENDENCY_UNOBSERVED", self.codes(facts))
        self.config.processor.metadata.references = ["unused"] * (ocio_facts.MAX_ITEMS + 1)
        facts = self.facts()
        self.assertFalse(facts["api_facts"]["Processor.0.ProcessorMetadata.getFiles"]["observed"])
        self.assertLessEqual(len(facts["missing_facts"]), ocio_facts.MAX_MISSING_FACTS)

    def test_invalid_requests_and_final_paths_rejected(self):
        for requests in ({}, [{"source": "a", "destination": "b"}],
                         [{"label": "p", "source": "", "destination": "b"}],
                         self.requests * 2, self.requests * 17):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                self.facts(transform_requests=requests)
        for path in (None, "", b"path", "nul\0path", "x" * (ocio_facts.MAX_STRING_LENGTH + 1)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.facts(final_output_path=path)

    def test_unknown_rule_signature_is_not_assumed_space(self):
        self.config.getColorSpaceFromFilepath = lambda path: "output_space"
        facts = self.facts()
        self.assertFalse(facts["api_facts"]["Config.getColorSpaceFromFilepath"]["observed"])
        validate(facts)

    def test_undocumented_hom_role_mapping_records_shape_gap(self):
        self.hou.Color.ocio_roles = lambda: {"scene_linear": "ACEScg"}
        facts = self.facts()
        self.assertEqual(facts["api_facts"]["hou.Color.ocio_roles"],
                         {"observed": False, "error_type": "ValueError"})
        validate(facts)

    def test_posix_stat_without_windows_reparse_constant(self):
        original = getattr(ocio_facts.stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
        if original is not None:
            del ocio_facts.stat.FILE_ATTRIBUTE_REPARSE_POINT
        try:
            facts = self.facts()
            validate(facts)
            self.assertIsNotNone(facts["config"]["file"])
        finally:
            if original is not None:
                ocio_facts.stat.FILE_ATTRIBUTE_REPARSE_POINT = original

    def test_malformed_contract_and_false_success_fields_rejected(self):
        fact = self.facts()
        mutations = [("schema", "wrong"), ("source", "effective_husk"),
                     ("final_output_path", ""), ("final_output_path", 1),
                     ("dependencies", {}), ("missing_facts", []), ("api_facts", []),
                     ("completion_metadata_status", "AVAILABLE"), ("transform_requests", {})]
        for key, value in mutations:
            changed = copy.deepcopy(fact)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(changed)
        for value in (None, [], {}, {"schema": ocio_facts.SCHEMA}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_malformed_file_facts_and_unbacked_dependencies_rejected(self):
        fact = self.facts()
        for key, value in (("path", "relative.cube"), ("path", ""), ("bytes", True),
                           ("bytes", -1), ("sha256", "cache-id"), ("path", self.output_path)):
            changed = copy.deepcopy(fact)
            changed["dependencies"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate(changed)
        changed = copy.deepcopy(fact)
        changed["api_facts"].pop("Processor.0.ProcessorMetadata.getFiles")
        with self.assertRaises(ValueError):
            validate(changed)
        changed = copy.deepcopy(fact)
        changed["dependencies"].append(copy.deepcopy(changed["dependencies"][0]))
        with self.assertRaises(ValueError):
            validate(changed)

    def test_path_observation_mismatch_and_malformed_api_record_rejected(self):
        facts = self.facts()
        changed = copy.deepcopy(facts)
        changed["config"]["path"] = str(self.lut_path)
        with self.assertRaises(ValueError):
            validate(changed)
        for record in ({"observed": "yes"}, {"observed": False, "value": "space"},
                       {"observed": True, "value": object()}):
            changed = copy.deepcopy(facts)
            changed["api_facts"]["Config.getCacheID"] = record
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate(changed)

    def test_reparse_and_symlink_ancestors_refused_before_open(self):
        native_lstat = Path.lstat
        for target, mode in ((self.config_path, "reparse"), (self.directory, "symlink")):
            def lstat(path):
                info = native_lstat(path)
                if path == target:
                    return SimpleNamespace(st_mode=(0o120777 if mode == "symlink" else info.st_mode),
                                           st_file_attributes=(1024 if mode == "reparse" else 0))
                return info
            with self.subTest(mode=mode), patch.object(Path, "lstat", lstat), \
                    patch.object(ocio_facts.os, "open", side_effect=AssertionError("must not open")):
                facts = self.facts()
                self.assertIsNone(facts["config"]["file"])
                self.assertIn("CONFIG_FILE_UNOBSERVED", self.codes(facts))

    def test_directory_as_config_refused(self):
        self.hou.Color.path = str(self.directory)
        facts = self.facts()
        self.assertIsNone(facts["config"]["file"])
        validate(facts)

    def test_file_growth_race_never_publishes_hash(self):
        native_read = os.read
        changed = False

        def read(descriptor, count):
            nonlocal changed
            if not changed:
                changed = True
                with self.config_path.open("ab") as handle:
                    handle.write(b"raced")
            return native_read(descriptor, count)

        with patch.object(ocio_facts.os, "read", read):
            facts = self.facts()
        self.assertIsNone(facts["config"]["file"])
        self.assertIn("CONFIG_FILE_UNOBSERVED", self.codes(facts))

    def test_reconstruction_race_invalidates_collected_file_evidence(self):
        def create(path):
            self.config_path.write_bytes(b"changed during native reload")
            return self.config

        self.ocio.Config.CreateFromFile = create
        facts = self.facts()
        self.assertIsNone(facts["config"]["file"])
        self.assertEqual(facts["dependencies"], [])
        self.assertIn("FILES_CHANGED_DURING_COLLECTION", self.codes(facts))
        validate(facts)


if __name__ == "__main__":
    unittest.main()
