from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = (
    ROOT / "tools" / "scan_node_types.py",
    ROOT / "tools" / "probe_domain_packs.py",
    ROOT / "tools" / "validate_houdini_http.py",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class HoudiniEvidenceOutputPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [
            _load("_evidence_output_{}".format(index), path)
            for index, path in enumerate(TOOLS)
        ]

    def test_all_three_allow_tmp_and_the_excluded_live_validation_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "probe.json"
            for module in self.modules:
                self.assertEqual(
                    module.validated_json_output_path(str(outside)), outside.resolve()
                )
                allowed = ROOT / "outputs" / "live-validation" / "unit-output.json"
                self.assertEqual(
                    module.validated_json_output_path(str(allowed)), allowed.resolve()
                )

    def test_all_three_reject_any_other_repository_output_before_execution(self) -> None:
        forbidden = ROOT / "tools" / "would-dirty-source-identity.json"
        for module in self.modules:
            with self.assertRaises(ValueError):
                module.validated_json_output_path(str(forbidden))
            with mock.patch.object(sys, "argv", [str(module.__file__), "--json", str(forbidden)]):
                self.assertEqual(module.main(), 2)

    def test_all_three_reject_a_symlink_escape_from_the_allowed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = base / "repo"
            allowed = repository / "outputs" / "live-validation"
            outside = base / "outside"
            allowed.mkdir(parents=True)
            outside.mkdir()
            link = allowed / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise
            for module in self.modules:
                with mock.patch.object(module, "ROOT", repository):
                    with self.assertRaises(ValueError):
                        module.validated_json_output_path(str(link / "probe.json"))


if __name__ == "__main__":
    unittest.main()
