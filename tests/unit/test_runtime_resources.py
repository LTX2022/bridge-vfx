from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from dcc_task_runtime.runtime_resources import (
    ResourceLookupError,
    ResourceOrigin,
    locate_package,
    locate_resource,
)


ROOT = Path(__file__).resolve().parents[2]
BUILD_RELEASE_PATH = ROOT / "tools" / "build_release.py"
BUILD_RELEASE_SPEC = importlib.util.spec_from_file_location("bridge_build_release_for_test", BUILD_RELEASE_PATH)
assert BUILD_RELEASE_SPEC is not None and BUILD_RELEASE_SPEC.loader is not None
BUILD_RELEASE = importlib.util.module_from_spec(BUILD_RELEASE_SPEC)
BUILD_RELEASE_SPEC.loader.exec_module(BUILD_RELEASE)
PORTABILITY_SPEC = importlib.util.spec_from_file_location("bridge_portability_for_test", ROOT / "tools/verify_portability.py")
assert PORTABILITY_SPEC is not None and PORTABILITY_SPEC.loader is not None
PORTABILITY = importlib.util.module_from_spec(PORTABILITY_SPEC)
PORTABILITY_SPEC.loader.exec_module(PORTABILITY)


class RuntimeResourceTests(unittest.TestCase):
    def test_release_portability_checks_manifested_bytes_and_keeps_source_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            history = root / "history.md"
            personal_path = "/Users/" + "user/private-project"
            history.write_text(personal_path, encoding="utf-8")
            archive = release / "fixture.zip"
            cases = (
                ("fixture/runtime/module.py", "可移植 source\n".encode("utf-8-sig"), False, False),
                ("fixture/runtime/module.py", personal_path.encode("utf-8"), True, False),
                ("fixture/runtime/module.py", b"\xff" + personal_path.encode("utf-8"), False, True),
                ("runtime/docs/native-basis/hda-interface-capture.json",
                 b'\xff{"native_execution": true}', False, True),
                ("runtime/docs/native-basis/hda-interface-capture.json",
                 b'{"native_execution": false}', False, False),
                ("runtime/docs/native-basis/hda-interface-22.0.459.json",
                 b'{"native_execution": false}', False, False),
                ("fixture/deploy/docs/native-basis/supporting-sources-22.0.459.json",
                 b'{"native_execution": false}', False, False),
                ("runtime/docs/native-basis/hda-interface-22.0.459.json",
                 b'\xff{"native_execution": false}', False, True),
                ("fixture/deploy/docs/native-basis/supporting-sources-22.0.459.json",
                 b'\xff{"native_execution": false}', False, True),
                ("fixture/image.png", b"\x89PNG\xff" + personal_path.encode("utf-8"), False, False),
                ("fixture/package.whl", b"PK\xff" + personal_path.encode("utf-8"), False, False),
            )
            for member, payload, rejected, invalid_utf8 in cases:
                with self.subTest(member=member, rejected=rejected, invalid_utf8=invalid_utf8):
                    with tempfile.TemporaryDirectory() as source_directory:
                        source = Path(source_directory)
                        (source / Path(member).name).write_bytes(payload)
                        if invalid_utf8:
                            with self.assertRaisesRegex(ValueError, "invalid UTF-8 text: .*decode byte offset"):
                                PORTABILITY.violations(source)
                        else:
                            self.assertEqual(bool(PORTABILITY.violations(source)), rejected)
                    with zipfile.ZipFile(archive, "w") as package:
                        package.writestr(member, payload)
                    entries = [{"path": member, "bytes": len(payload),
                                "sha256": BUILD_RELEASE.digest_bytes(payload)}]
                    artifact = {"archive": archive.name, "bytes": archive.stat().st_size,
                                "sha256": BUILD_RELEASE.digest(archive), "files": entries,
                                "file_manifest_sha256": BUILD_RELEASE.file_manifest_sha256(entries)}
                    (release / "release-manifest.json").write_text(json.dumps({"artifacts": [artifact]}), encoding="utf-8")
                    with mock.patch.dict(sys.modules, {"build_release": BUILD_RELEASE}):
                        if invalid_utf8:
                            with self.assertRaisesRegex(ValueError, "invalid UTF-8 text: fixture.zip:"):
                                PORTABILITY.release_violations(release)
                        else:
                            self.assertEqual(bool(PORTABILITY.release_violations(release)), rejected)
            self.assertTrue(PORTABILITY.violations(root))
            with self.assertRaises(ValueError):
                PORTABILITY.violations(root / "missing-source")
            archive.write_bytes(b"tampered archive")
            with mock.patch.dict(sys.modules, {"build_release": BUILD_RELEASE}), self.assertRaises((ValueError, zipfile.BadZipFile)):
                PORTABILITY.release_violations(release)

    def test_skill_static_metadata_exceptions_remain_exact_and_utf8_strict(self):
        metadata = ('hda-interface-capture.json', 'native-boundary-metadata-supplement.json',
                    'hda-interface-22.0.459.json', 'supporting-sources-22.0.459.json')
        personal = ('/Users/'+'user/private').encode()
        cases = []
        for name in metadata:
            prefix = 'deploy/docs/native-basis/'+name
            cases += [(prefix, b'{"native_execution":false,"source":"'+personal+b'"}', None),
                      (prefix, b'{"native_execution":true}', 'static evidence'),
                      (prefix, b'\xff', 'invalid UTF-8 text')]
        for name in ('deploy/docs/native-basis/h22-459-originals/raw-sections/example.txt',
                     'deploy/docs/native-basis/hda-interface-22.0.459.extra.json'):
            cases += [(name, personal, 'non-portable path'), (name,b'\xff','invalid UTF-8 text')]
        with tempfile.TemporaryDirectory() as directory:
            for index,(relative,payload,error) in enumerate(cases):
                staging=Path(directory)/str(index);path=staging/relative
                path.parent.mkdir(parents=True);path.write_bytes(payload)
                with self.subTest(relative=relative,payload=payload):
                    if error:
                        with self.assertRaisesRegex(ValueError,error):BUILD_RELEASE.assert_portable(staging)
                    else:BUILD_RELEASE.assert_portable(staging)

    def test_relocated_supervisor_loads_siblings_by_path_and_observes_owned_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'relocated-runtime'
            bundle.mkdir()
            runtime = ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime'
            for name in ('owned_process.py', 'platform_support.py', 'windows_process.py'):
                shutil.copy2(runtime / name, bundle / name)
            (root / 'platform_support.py').write_text('raise AssertionError("ambient module imported")\n', encoding='utf-8')
            source = '''import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('receipt_reader',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
identity={'task_id':'relocated','nonce':'software-only'}
handle=module.launch([sys.executable,'-c','pass'],directory=Path(sys.argv[2])/'process',identity=identity,supervisor_executable=sys.executable)
assert handle.wait(5)==0
assert module.read_receipt(handle.directory,'stopped',identity=identity)['observed_by']=='owned_child_wait'
'''
            executable = getattr(sys, '_base_executable', sys.executable)
            result = subprocess.run([executable, '-I', '-X', 'utf8', '-c', source,
                                     str(bundle / 'owned_process.py'), str(root)], cwd=root,
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 0, result.stderr)

    @staticmethod
    def _write_package(root: Path, layout: str, distribution: str, *, resource_text: str = "resource") -> Path:
        module = distribution.replace("-", "_")
        source = root / layout / distribution / "src" / module
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("# fixture\n", encoding="utf-8")
        (source / "fixture.txt").write_text(resource_text, encoding="utf-8")
        return source

    def test_developer_and_release_layouts_are_selected_from_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            developer = self._write_package(root, "packages", "demo-runtime", resource_text="developer")
            release_root = root / "standalone"
            release = self._write_package(release_root, "runtime", "demo-runtime", resource_text="release")

            development_location = locate_package("demo-runtime", start=developer / "fixture.txt", allow_installed=False)
            self.assertEqual(development_location.origin, ResourceOrigin.DEVELOPER)
            self.assertEqual(locate_resource("demo-runtime", "fixture.txt", start=root, allow_installed=False), (developer / "fixture.txt").resolve())

            release_location = locate_package("demo-runtime", start=release / "fixture.txt", allow_installed=False)
            self.assertEqual(release_location.origin, ResourceOrigin.RELEASE)
            self.assertEqual(release_location.resource("fixture.txt").read_text(encoding="utf-8"), "release")

    def test_installed_package_is_a_filesystem_fallback_and_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            package = site / "installed_runtime_fixture"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("# fixture\n", encoding="utf-8")
            (package / "fixture.txt").write_text("installed", encoding="utf-8")
            sys.path.insert(0, str(site))
            importlib.invalidate_caches()
            try:
                location = locate_package("installed-runtime-fixture", start=root / "unrelated", allow_installed=True)
                self.assertEqual(location.origin, ResourceOrigin.INSTALLED)
                self.assertEqual(locate_resource("installed-runtime-fixture", "fixture.txt", start=root), (package / "fixture.txt").resolve())
                with self.assertRaises(ValueError):
                    location.resource("../outside.txt")
                with self.assertRaises(ValueError):
                    location.resource("C:/outside.txt")
            finally:
                sys.path.remove(str(site))
                sys.modules.pop("installed_runtime_fixture", None)
                importlib.invalidate_caches()

            with self.assertRaises(ResourceLookupError):
                locate_package("missing-runtime-fixture", start=root, allow_installed=False)

    def test_manifest_tracks_shipped_bytes_without_git_and_excludes_evidence_output_and_self(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo-without-git"
            staging = repo / "demo-skill-v1.0"
            (staging / "runtime" / "demo").mkdir(parents=True)
            (staging / "runtime" / "demo" / "module.py").write_bytes(b"print('ok')\n")
            (staging / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (staging / "evidence" / "private.txt").parent.mkdir()
            (staging / "evidence" / "private.txt").write_text("omit", encoding="utf-8")
            (staging / "outputs" / "render.exr").parent.mkdir()
            (staging / "outputs" / "render.exr").write_bytes(b"omit")
            (staging / "release-manifest.json").write_text("self\n", encoding="utf-8")

            archive = repo / "demo.zip"
            entries = BUILD_RELEASE.shipped_file_manifest(staging, archive_root=repo)
            self.assertEqual(sorted(entry["path"] for entry in entries), [
                "demo-skill-v1.0/SKILL.md",
                "demo-skill-v1.0/runtime/demo/module.py",
            ])
            file_hash = BUILD_RELEASE.file_manifest_sha256(entries)
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for path in BUILD_RELEASE.iter_release_files(staging):
                    package.write(path, path.relative_to(repo))
            artifact = {
                "archive": archive.name,
                "bytes": archive.stat().st_size,
                "sha256": BUILD_RELEASE.digest(archive),
                "files": entries,
                "file_manifest_sha256": file_hash,
            }
            BUILD_RELEASE.validate_packaged_bytes(archive, artifact)
            manifest = repo / "release-manifest.json"
            manifest.write_text(json.dumps({"schema_version": 2, "artifacts": [artifact]}), encoding="utf-8")
            BUILD_RELEASE.validate_release_manifest(manifest)

            tampered_archive = repo / "tampered.zip"
            with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(tampered_archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for info in original.infolist():
                    payload = b"tampered\n" if info.filename == "demo-skill-v1.0/runtime/demo/module.py" else original.read(info)
                    package.writestr(info, payload)
            with self.assertRaises(ValueError):
                BUILD_RELEASE.validate_packaged_bytes(tampered_archive, artifact)

    def test_build_skill_uses_developer_src_and_returns_validated_file_manifest_without_git(self) -> None:
        original_root = BUILD_RELEASE.ROOT
        original_skills_root = BUILD_RELEASE.SKILLS_ROOT
        try:
            with tempfile.TemporaryDirectory() as directory:
                repo = Path(directory) / "clean-repo"
                skill = repo / "skills" / "fixture-skill"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text("fixture\n", encoding="utf-8")
                package_source = repo / "packages" / "fixture-runtime" / "src" / "fixture_runtime"
                package_source.mkdir(parents=True)
                (package_source / "__init__.py").write_text("# fixture\n", encoding="utf-8")
                (package_source / "resource.txt").write_text("runtime\n", encoding="utf-8")
                output = repo / "releases"
                output.mkdir()

                BUILD_RELEASE.ROOT = repo
                BUILD_RELEASE.SKILLS_ROOT = repo / "skills"
                artifact = BUILD_RELEASE.build_skill(
                    "fixture-skill",
                    {"files": ["SKILL.md"], "runtime_packages": ["fixture-runtime"], "plugins": [], "self_tests": []},
                    "1.0",
                    output,
                )
                BUILD_RELEASE.validate_packaged_bytes(output / artifact["archive"], artifact)
                self.assertTrue(any(item["path"].endswith("fixture_runtime/resource.txt") for item in artifact["files"]))
        finally:
            BUILD_RELEASE.ROOT = original_root
            BUILD_RELEASE.SKILLS_ROOT = original_skills_root


if __name__ == "__main__":
    unittest.main()
