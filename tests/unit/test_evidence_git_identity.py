from __future__ import annotations

import hashlib
import importlib.util
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


class EvidenceGitIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scanner = _load("_identity_node_scan", "tools/scan_node_types.py")
        cls.probe = _load("_identity_domain_probe", "tools/probe_domain_packs.py")
        cls.houdini_http = _load("_identity_houdini_http", "tools/validate_houdini_http.py")
        cls.nuke_live = _load("_identity_nuke_live", "tools/validate_nuke_live.py")
        cls.support = _load("_identity_support_verifier", "tools/verify_support_claims.py")

    def test_every_evidence_entrypoint_uses_one_complete_dirty_digest(self) -> None:
        head = "a" * 40
        status = b"?? untracked.bin\0"
        unstaged = b"unstaged-diff"
        staged = b"staged-diff"
        untracked = b"untracked-bytes"

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
            (checkout / "untracked.bin").write_bytes(untracked)
            expected = hashlib.sha256()
            expected.update(status)
            expected.update(b"\0DIFF\0")
            expected.update(unstaged)
            expected.update(b"\0STAGED\0")
            expected.update(staged)
            expected.update(b"untracked.bin")
            expected.update(hashlib.sha256(untracked).digest())
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

            with unittest.mock.patch.object(self.nuke_live, "ROOT", checkout):
                with unittest.mock.patch.object(self.nuke_live.subprocess, "run", side_effect=fake_run):
                    nuke = self.nuke_live._git_identity()
                    observed.append((nuke["git_commit"], nuke["dirty_diff_digest"]))

            with unittest.mock.patch.object(self.support.subprocess, "run", side_effect=fake_run):
                observed.append(self.support._git_state(checkout))

        self.assertEqual(observed, [(head, expected_digest)] * 5)

    def test_support_git_identity_requires_its_own_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            snapshot = parent / 'outputs' / 'source'
            snapshot.mkdir(parents=True)
            calls = []
            def ancestor_run(args, **_kwargs):
                calls.append(args)
                self.assertIn('--show-toplevel', args)
                return SimpleNamespace(stdout=(str(parent) + '\n').encode('utf-8'))
            with unittest.mock.patch.object(self.support.subprocess, 'run', side_effect=ancestor_run):
                with self.assertRaisesRegex(OSError, 'repository root does not match'):
                    self.support._git_state(snapshot)
            self.assertEqual(len(calls), 1)
            # A linked worktree has a .git file; exact top-level ownership is the guard.
            (snapshot / '.git').write_text('gitdir: /not-read-by-verifier/worktrees/linked\n')
            def exact_run(args, **_kwargs):
                if '--show-toplevel' in args:
                    return SimpleNamespace(stdout=(str(snapshot) + '\n').encode('utf-8'))
                if 'rev-parse' in args:
                    return SimpleNamespace(stdout=b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n')
                return SimpleNamespace(stdout=b'')
            with unittest.mock.patch.object(self.support.subprocess, 'run', side_effect=exact_run):
                commit, digest = self.support._git_state(snapshot)
            self.assertEqual(commit, 'a' * 40)
            self.assertEqual(len(digest), 64)

    def test_nuke_live_requires_the_topology_gate(self) -> None:
        build_result = {
            "gates": [
                {"name": "editable_native_composite_graph", "passed": True},
                {"name": "reference_isolated_from_final_write", "passed": True},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "composite_topology_intact"):
            self.nuke_live._require_build_evidence(build_result)

        build_result["gates"].append(
            {"name": "composite_topology_intact", "passed": True}
        )
        self.nuke_live._require_build_evidence(build_result)


if __name__ == "__main__":
    unittest.main()
