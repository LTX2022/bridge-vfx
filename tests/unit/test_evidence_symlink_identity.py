from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvidenceSymlinkIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scanner = _load("_symlink_node_scan", "tools/scan_node_types.py")
        cls.probe = _load("_symlink_domain_probe", "tools/probe_domain_packs.py")
        cls.houdini_http = _load("_symlink_houdini_http", "tools/validate_houdini_http.py")
        cls.support = _load("_symlink_support_verifier", "tools/verify_support_claims.py")
        cls.addon = _load("_symlink_houdini_addon", "plugins/houdini/_impl/houdini_bridge_addon.py")

    def test_untracked_symlink_readlink_is_bound_consistently(self) -> None:
        head = "a" * 40
        status = b"?? untracked-link\0"
        unstaged = b"unstaged-diff"
        staged = b"staged-diff"
        target = "missing-target.bin"

        def fake_run(args, **_kwargs):
            if "--show-toplevel" in args:
                return SimpleNamespace(stdout=(str(checkout.resolve()) + "\n").encode("utf-8"))
            if "rev-parse" in args:
                return SimpleNamespace(stdout=(head + "\n").encode("ascii"))
            if "status" in args:
                return SimpleNamespace(stdout=status)
            if "diff" in args and "--cached" in args:
                return SimpleNamespace(stdout=staged)
            if "diff" in args:
                return SimpleNamespace(stdout=unstaged)
            raise AssertionError("unexpected git command: {}".format(args))

        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            try:
                os.symlink(target, checkout / "untracked-link")
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise
            expected = hashlib.sha256()
            expected.update(status)
            expected.update(b"\0DIFF\0")
            expected.update(unstaged)
            expected.update(b"\0STAGED\0")
            expected.update(staged)
            expected.update(b"untracked-link")
            expected.update(b"\0SYMLINK\0")
            expected.update(target.encode("utf-8"))
            expected_digest = expected.hexdigest()

            observed = []
            for module, function_name in (
                (self.scanner, "git_state"),
                (self.probe, "git_state"),
                (self.houdini_http, "_git_state"),
            ):
                with unittest.mock.patch.object(module, "ROOT", checkout):
                    with unittest.mock.patch.object(module.subprocess, "run", side_effect=fake_run):
                        observed.append(getattr(module, function_name)())
            with unittest.mock.patch.object(self.support.subprocess, "run", side_effect=fake_run):
                observed.append(self.support._git_state(checkout))
            with unittest.mock.patch.object(self.addon, "_FX_REPOSITORY_ROOT", checkout):
                with unittest.mock.patch.object(self.addon.subprocess, "run", side_effect=fake_run):
                    observed.append(self.addon._fx_git_state())

        self.assertEqual(observed, [(head, expected_digest)] * 5)


if __name__ == "__main__":
    unittest.main()
