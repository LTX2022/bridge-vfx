from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import shutil
import tempfile
import unicodedata
import zipfile

import build_release


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "agent-plugin"
SKILL_ROUTES = {"houdini-bridge": "bridge-houdini", "nuke-bridge": "bridge-nuke", "vfx-visual-twin": "bridge-vfx"}
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
# 构建准备器会逐字复制此静态基线；安装runtime必须随包提供，不依赖开发检出。
PREPARATION_RESOURCES = frozenset({"docs/official-baselines/karma/frozen-scene-v2.json"})


def checked_files(root):
    root = Path(root)
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("plugin sources must not traverse links: " + path.relative_to(root).as_posix())
    yield from build_release.iter_release_files(root)


def validate_layout(root):
    root = Path(root)
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    if (manifest.get("$schema") != PLUGIN_SCHEMA or manifest.get("name") != "bridge-vfx"
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", str(manifest.get("version")))):
        raise ValueError("invalid portable plugin identity")
    mcp = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    if mcp.get("$schema") != MCP_SCHEMA or set(mcp.get("mcpServers", {})) != {"bridge-graph"}:
        raise ValueError("invalid portable MCP configuration")
    server = mcp["mcpServers"]["bridge-graph"]
    if (server.get("type") != "stdio" or server.get("cwd") != "${PLUGIN_ROOT}"
            or server.get("args") != ["-I", "-B", "./scripts/bridge_mcp.py", "serve"]
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(server.get("command")))):
        raise ValueError("plugin MCP command must be a bare interpreter and a contained launcher")
    for name in SKILL_ROUTES.values():
        if not (root / "skills" / name / "SKILL.md").is_file():
            raise ValueError("missing routing skill: " + name)
    return manifest


def validate_archive(archive, artifact):
    required = {"plugin.json", "mcp.json", "scripts/bridge_mcp.py"}
    required.update("runtime/" + name for name in PREPARATION_RESOURCES)
    required.update("skills/" + name + "/SKILL.md" for name in SKILL_ROUTES.values())
    required.update("runtime/packages/" + distribution + "/src/" + module + "/__init__.py"
                    for distribution, module in (("dcc-task-runtime", "dcc_task_runtime"),
                    ("houdini-bridge", "houdini_bridge"), ("nuke-bridge", "nuke_bridge"),
                    ("vfx-pipeline", "vfx_pipeline")))
    if not required <= {entry["path"] for entry in artifact["files"]}:
        raise ValueError("plugin archive is missing required entrypoints")
    seen = set()
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            build_release._validate_archive_member(info.filename)
            normalized = unicodedata.normalize("NFC", info.filename).casefold()
            if normalized in seen:
                raise ValueError("case or Unicode archive path collision")
            seen.add(normalized)
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError("plugin archive must contain only regular files")
        if package.testzip() is not None:
            raise ValueError("plugin archive CRC mismatch")
        expected = {entry["path"] for entry in artifact["files"]} | {"runtime-manifest.json"}
        if set(package.namelist()) != expected:
            raise ValueError("unexpected plugin archive member")
        manifest = json.loads(package.read("runtime-manifest.json"))
        if (manifest.get("schema_version") != 1 or manifest.get("files") != artifact["files"]
                or manifest.get("file_manifest_sha256") != artifact["file_manifest_sha256"]):
            raise ValueError("plugin runtime manifest mismatch")
    build_release.validate_packaged_bytes(archive, artifact)


def assert_plugin_portable(staging, resources):
    from verify_portability import TEXT_SUFFIXES
    native_metadata = {"docs/native-basis/hda-interface-capture.json",
                       "docs/native-basis/native-boundary-metadata-supplement.json",
                       "docs/native-basis/hda-interface-22.0.459.json",
                       "docs/native-basis/supporting-sources-22.0.459.json"}
    static_resources = {"runtime/" + name for name in resources if name in native_metadata}
    for path in checked_files(staging):
        relative = path.relative_to(staging).as_posix()
        if relative in static_resources:
            if json.loads(path.read_text(encoding="utf-8")).get("native_execution") is not False:
                raise ValueError("deployment native metadata must be static evidence")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            if path.suffix.lower() in TEXT_SUFFIXES:
                raise ValueError("invalid UTF-8 text: {} (decode byte offset {})".format(
                    relative, error.start)) from error
            continue
        if any(pattern.search(text) for pattern in build_release.PERSONAL_PATH_PATTERNS):
            raise ValueError("non-portable path in plugin: " + relative)


def build_plugin(version, output, *, python_command="python"):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("version must be semantic version text")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", python_command):
        raise ValueError("python-command must be a bare executable name")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite plugin build: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    layout = build_release.load_layout()
    if set(layout) != set(SKILL_ROUTES):
        raise ValueError("existing three-skill release layout is required")
    with tempfile.TemporaryDirectory(prefix="bridge-agent-plugin-", dir=output.parent) as temporary:
        staging = Path(temporary) / "plugin"
        staging.mkdir()
        for path in checked_files(TEMPLATE):
            build_release.copy_relative(TEMPLATE, staging, path.relative_to(TEMPLATE).as_posix())
        manifest = validate_layout(staging)
        manifest["version"] = version
        (staging / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mcp = json.loads((staging / "mcp.json").read_text(encoding="utf-8"))
        mcp["mcpServers"]["bridge-graph"]["command"] = python_command
        (staging / "mcp.json").write_text(json.dumps(mcp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packages = sorted({str(name) for config in layout.values() for name in config["runtime_packages"]})
        for name in packages:
            source = build_release.locate_package_source(name, start=ROOT, allow_installed=False).parent
            list(checked_files(source))
            build_release.copy_tree(source, staging / "runtime/packages" / name)
        for name in sorted({str(name) for config in layout.values() for name in config["plugins"]}):
            source = ROOT / "plugins" / name
            list(checked_files(source))
            build_release.copy_tree(source, staging / "runtime/plugins" / name)
        list(checked_files(ROOT / "tools"))
        build_release.copy_tree(ROOT / "tools", staging / "runtime/tools")
        resources = sorted({str(name) for config in layout.values() for name in config["deployment_resources"]})
        if not PREPARATION_RESOURCES <= set(resources):
            raise ValueError("plugin layout is missing construction preparation resources")
        for name in resources:
            if (ROOT / name).is_symlink():
                raise ValueError("linked deployment resource")
            build_release.copy_relative(ROOT, staging / "runtime", name)
        for distribution, route in SKILL_ROUTES.items():
            for name in layout[distribution]["files"]:
                if name.startswith("references/"):
                    build_release.copy_relative(ROOT / "skills" / distribution, staging / "skills" / route, name)
        build_release.copy_relative(ROOT, staging, "docs/agent-plugin.md")
        validate_layout(staging)
        assert_plugin_portable(staging, resources)
        entries = build_release.shipped_file_manifest(staging)
        file_hash = build_release.file_manifest_sha256(entries)
        runtime_manifest = {"schema_version": 1, "files": entries, "file_manifest_sha256": file_hash,
                            "runtime_packages": packages, "codex_installation": "not_run", "real_host_acceptance": "not_run"}
        (staging / "runtime-manifest.json").write_text(json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prepared = Path(temporary) / "output"
        prepared.mkdir()
        archive = prepared / ("bridge-vfx-agent-plugin-v" + version + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for path in checked_files(staging):
                info = zipfile.ZipInfo(path.relative_to(staging).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(info, path.read_bytes(), compresslevel=9)
            info = zipfile.ZipInfo("runtime-manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, (staging / "runtime-manifest.json").read_bytes(), compresslevel=9)
        artifact = {"archive": archive.name, "bytes": archive.stat().st_size, "sha256": build_release.digest(archive),
                    "files": entries, "file_manifest_sha256": file_hash}
        validate_archive(archive, artifact)
        # 最终目录源与ZIP使用同一份已核验字节，可直接交给官方本地插件管理器。
        market = prepared / "marketplace"
        shutil.copytree(staging, market / "plugins" / manifest["name"])
        catalog = {"name": "bridge-local", "interface": {"displayName": "Bridge Local"}, "plugins": [{
            "name": manifest["name"], "source": {"source": "local", "path": "./plugins/" + manifest["name"]},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}
        catalog_path = market / ".agents/plugins/marketplace.json"
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = {"schema_version": 2, "name": manifest["name"], "version": version, "artifacts": [artifact],
                  "codex_installation": "not_run", "real_host_acceptance": "not_run",
                  "marketplace": {"root": "marketplace", "name": "bridge-local", "selector": "bridge-vfx@bridge-local"}}
        (prepared / "release-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prepared.replace(output)
    return output / "release-manifest.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the thin Bridge Agent Plugin with one shared runtime")
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-command", default="python")
    args = parser.parse_args(argv)
    print(build_plugin(args.version, args.output, python_command=args.python_command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
