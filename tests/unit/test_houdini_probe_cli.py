from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools" / "probe_domain_packs.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("_houdini_probe_cli", PROBE)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HoudiniProbeCliTests(unittest.TestCase):
    def test_runtime_resolver_failure_writes_json_then_returns_nonzero(self) -> None:
        probe = _load_probe()
        fake_hou = SimpleNamespace(applicationVersionString=lambda: "unit-build")
        failed = {
            "all_verified": False,
            "results": [{"alias": "sizex", "restore_verified": False}],
            "failure_reasons": ["sizex:PARAMETER_READBACK_MISMATCH"],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            arguments = [str(PROBE), "--level", "runtime", "--json", str(output)]
            with unittest.mock.patch.object(probe, "load_addon", return_value=object()):
                with unittest.mock.patch.object(probe, "probe_all", return_value={}):
                    with unittest.mock.patch.object(probe, "probe_resolver_targets", return_value=failed):
                        with unittest.mock.patch.object(probe, "git_state", return_value=("a" * 40, "b" * 64)):
                            with unittest.mock.patch.object(sys, "argv", arguments):
                                with unittest.mock.patch.dict(sys.modules, {"hou": fake_hou}):
                                    code = probe.main()
            self.assertEqual(code, 1)
            self.assertTrue(output.is_file())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["resolver_target_probes"], failed)
            unsigned = {key: value for key, value in payload.items() if key != "evidence_identity"}
            expected = hashlib.sha256(
                json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
            self.assertEqual(payload["evidence_identity"], expected)


if __name__ == "__main__":
    unittest.main()
