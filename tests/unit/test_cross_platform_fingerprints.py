from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import build_release
import readiness_evidence
import run_logged
from dcc_task_runtime.canonical import canonical_sha256
from vfx_pipeline import graph_job_evidence


class FlavouredPath:
    """Exercise native path spelling/ordering while reading real fixture bytes."""

    def __init__(self, actual, native):
        self.actual = actual
        self.native = native

    def __truediv__(self, relative):
        return FlavouredPath(self.actual / relative, self.native / relative)

    def __lt__(self, other):
        return self.native < other.native

    def relative_to(self, root):
        return self.native.relative_to(root.native)

    def rglob(self, pattern):
        return [FlavouredPath(path, self.native / path.relative_to(self.actual).as_posix())
                for path in reversed(list(self.actual.rglob(pattern)))]

    def is_file(self):
        return self.actual.is_file()

    def is_dir(self):
        return self.actual.is_dir()

    def read_bytes(self):
        return self.actual.read_bytes()

    def open(self, *args, **kwargs):
        return self.actual.open(*args, **kwargs)

    def stat(self):
        return self.actual.stat()

    @property
    def parts(self):
        return self.native.parts

    @property
    def name(self):
        return self.native.name

    @property
    def suffix(self):
        return self.native.suffix


def tree_digest(files):
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[name]).digest())
    return digest.hexdigest()


class CrossPlatformFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bridge-fingerprint-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_files(self, files):
        for name, payload in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def flavours(self):
        return (FlavouredPath(self.root, PurePosixPath("/fixture")),
                FlavouredPath(self.root, PureWindowsPath("C:/fixture")))

    def runtime_files(self):
        return {
            "packages/dcc-task-runtime/src/Z.py": b"runtime = 1\n",
            "packages/dcc-task-runtime/src/a.py": b"lower = 2\n",
            "packages/houdini-bridge/src/a.py": b"houdini = 3\n",
            "packages/houdini-bridge/src/a/child.py": b"nested = 4\n",
            "packages/nuke-bridge/src/module.py": b"nuke = 5\n",
            "packages/vfx-pipeline/src/中文.py": b"pipeline = 6\n",
            "plugins/houdini/_impl/houdini_bridge_addon.py": b"plugin = 7\n",
        }

    def test_runtime_fingerprint_matches_posix_reference_in_both_flavours(self):
        files = self.runtime_files()
        self.write_files(files)
        self.write_files({"packages/vfx-pipeline/src/ignored.txt": b"not a Python input"})
        expected = canonical_sha256({name: hashlib.sha256(payload).hexdigest()
                                     for name, payload in files.items()})
        for root in self.flavours():
            with self.subTest(flavour=type(root.native).__name__), mock.patch.object(
                    graph_job_evidence, "owned_file", side_effect=lambda owner, path: path.actual):
                self.assertEqual(graph_job_evidence.runtime_fingerprint(root), expected)
        self.assertEqual(graph_job_evidence.runtime_fingerprint(self.root), expected)
        changed = self.root / "packages/dcc-task-runtime/src/Z.py"
        changed.write_bytes(b"runtime = 9\n")
        changed_fingerprint = graph_job_evidence.runtime_fingerprint(self.root)
        self.assertNotEqual(changed_fingerprint, expected)
        changed.rename(changed.with_name("renamed.py"))
        renamed = graph_job_evidence.runtime_fingerprint(self.root)
        self.assertNotEqual(renamed, changed_fingerprint)
        (self.root / "plugins/houdini/_impl/houdini_bridge_addon.py").unlink()
        with self.assertRaises(ValueError):
            graph_job_evidence.runtime_fingerprint(self.root)

    def test_tree_hashes_use_explicit_case_sensitive_logical_path_order(self):
        files = {"Z.txt": b"upper", "a.txt": b"lower", "a/child.txt": b"nested",
                 "中文.txt": b"unicode"}
        self.write_files(files)
        self.write_files({"outputs/ignored.txt": b"output", ".git/ignored": b"metadata",
                          "__pycache__/ignored.pyc": b"bytecode"})
        expected = tree_digest(files)
        for root in self.flavours():
            with self.subTest(flavour=type(root.native).__name__):
                with self.subTest(algorithm="logger"):
                    self.assertEqual(run_logged.build_hash(root), expected)
                with self.subTest(algorithm="noGit"), mock.patch.object(build_release, "ROOT", root), mock.patch.object(
                        build_release.subprocess, "check_output", side_effect=FileNotFoundError):
                    state = build_release._git_state()
                    self.assertEqual(state["git_revision"], "vcs_absent")
                    self.assertIsNone(state["git_dirty"])
                    self.assertEqual(state["vcs_absent_tree_sha256"], expected)
        self.assertEqual(run_logged.build_hash(self.root), expected)
        (self.root / "a.txt").write_bytes(b"changed bytes")
        self.assertNotEqual(run_logged.build_hash(self.root), expected)
        with mock.patch.object(build_release, "ROOT", self.root), mock.patch.object(
                build_release.subprocess, "check_output", side_effect=FileNotFoundError):
            self.assertNotEqual(build_release._git_state()["vcs_absent_tree_sha256"], expected)

    def test_release_file_manifest_has_the_same_logical_order_in_both_flavours(self):
        files = {"Z.txt": b"upper", "a.txt": b"lower", "a/child.txt": b"nested",
                 "中文.txt": b"unicode"}
        self.write_files(files)
        self.write_files({"outputs/ignored.txt": b"output", ".DS_Store": b"metadata",
                          "runtime-manifest.json": b"{}", "module.pyc": b"bytecode"})
        expected = [{"path": name, "bytes": len(files[name]),
                     "sha256": hashlib.sha256(files[name]).hexdigest()} for name in sorted(files)]
        expected_hash = hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest()
        for root in self.flavours():
            with self.subTest(flavour=type(root.native).__name__), mock.patch.object(
                    build_release, "Path", side_effect=lambda value: value):
                entries = build_release.shipped_file_manifest(root)
                self.assertEqual(entries, expected)
                self.assertEqual(build_release.file_manifest_sha256(entries), expected_hash)

    def test_readiness_build_id_preserves_group_order_and_content_binding(self):
        files = {"packages/Z.py": b"upper", "packages/a.py": b"lower",
                 "packages/a/child.py": b"nested", "packages/中文.py": b"unicode",
                 "plugins/plugin.py": b"plugin", "docs/basis.json": b"{}",
                 "agent-plugin/plugin.json": b'{"name":"bridge-vfx"}', "handover/plan.md": b"scope\n",
                 "pyproject.toml": b"[project]\n"}
        self.write_files(files)
        self.write_files({"packages/__pycache__/ignored.pyc": b"bytecode"})
        entries = [(name, hashlib.sha256(files[name]).hexdigest())
                   for group in ("packages", "plugins", "tools", "skills", "tests", "docs", "controller-entry", "agent-plugin", "handover")
                   for name in sorted(files) if name.startswith(group + "/")]
        entries.append(("pyproject.toml", hashlib.sha256(files["pyproject.toml"]).hexdigest()))
        expected = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
        for root in self.flavours():
            with self.subTest(flavour=type(root.native).__name__), mock.patch.object(
                    readiness_evidence, "Path", side_effect=lambda value: value):
                self.assertEqual(readiness_evidence.build_id(root), expected)
        self.assertEqual(readiness_evidence.build_id(self.root), expected)
        (self.root / "agent-plugin/plugin.json").write_bytes(b'{"name":"changed"}')
        self.assertNotEqual(readiness_evidence.build_id(self.root), expected)
        (self.root / "agent-plugin/plugin.json").write_bytes(files["agent-plugin/plugin.json"])
        (self.root / "docs/basis.json").write_bytes(b'{"changed":true}')
        self.assertNotEqual(readiness_evidence.build_id(self.root), expected)

    def test_logger_header_names_the_new_algorithm_without_launching_a_child(self):
        self.write_files({"source.py": b"source bytes"})
        log_dir = self.root / "outputs" / "logs"
        with mock.patch.object(run_logged, "ROOT", self.root), mock.patch.object(
                sys, "argv", ["run_logged.py", "--log-dir", str(log_dir), "--name", "fixture", "fixture-command"]), mock.patch.object(
                run_logged.platform, "platform", return_value="fixture-platform"), mock.patch.object(
                run_logged.platform, "machine", return_value="fixture-machine"), mock.patch.object(
                run_logged.subprocess, "run", return_value=mock.Mock(returncode=7)) as child, mock.patch(
                "sys.stdout", new_callable=io.StringIO):
            self.assertEqual(run_logged.main(), 1)
        child.assert_called_once()
        log = next(log_dir.glob("fixture-*.log")).read_text(encoding="utf-8")
        header = json.loads(log.split("=== RUN PROVENANCE (start) ===\n", 1)[1].split("=== OUTPUT ===", 1)[0])
        self.assertEqual(header["build_sha256_algorithm"], "sha256-posix-logical-path-v2")
        self.assertEqual(header["build_sha256"], tree_digest({"source.py": b"source bytes"}))
        ending = json.loads(log.split("=== RUN PROVENANCE (end) ===\n", 1)[1])
        self.assertEqual(ending["returncode"], 7)

    def test_logger_hash_ignores_only_paths_below_the_source_root(self):
        source = self.root / "outputs" / "中文 源码"
        source.mkdir(parents=True)
        (source / "source.py").write_bytes(b"source bytes")
        (source / "outputs").mkdir()
        (source / "outputs" / "log.txt").write_bytes(b"ignored")
        self.assertEqual(run_logged.build_hash(source), tree_digest({"source.py": b"source bytes"}))
        (source / "source.py").write_bytes(b"changed source bytes")
        self.assertEqual(run_logged.build_hash(source), tree_digest({"source.py": b"changed source bytes"}))


if __name__ == "__main__":
    unittest.main()
