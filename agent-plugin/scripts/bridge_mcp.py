from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline")


def read_object(path):
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError("DUPLICATE_CONFIG_KEY")
            value[name] = item
        return value

    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("CONFIG_OBJECT_REQUIRED")
    return value


def regular_file(root, name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute() or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("PLUGIN_MANIFEST_PATH_INVALID")
    path = root
    for part in name.split("/"):
        path /= part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("PLUGIN_PATH_LINK")
    if not path.is_file():
        raise ValueError("PLUGIN_FILE_MISSING")
    return path


def verify_package(root=ROOT):
    root = Path(root).absolute()
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("PLUGIN_PATH_LINK")
    manifest = read_object(regular_file(root, "runtime-manifest.json"))
    entries = manifest.get("files")
    if manifest.get("schema_version") != 1 or not isinstance(entries, list) or not entries:
        raise ValueError("PLUGIN_MANIFEST_INVALID")
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != manifest.get("file_manifest_sha256"):
        raise ValueError("PLUGIN_MANIFEST_DIGEST_MISMATCH")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("PLUGIN_MANIFEST_INVALID")
        normalized = unicodedata.normalize("NFC", entry["path"]).casefold()
        if normalized in seen:
            raise ValueError("PLUGIN_MANIFEST_DUPLICATE")
        path = regular_file(root, entry.get("path"))
        seen.add(normalized)
        if path.stat().st_size != entry.get("bytes") or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise ValueError("PLUGIN_BYTES_CHANGED")
    allowed = {entry["path"] for entry in entries} | {"runtime-manifest.json", "connection.json"}
    directories = {parent.as_posix() for name in allowed for parent in PurePosixPath(name).parents}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("PLUGIN_PATH_LINK")
        if (stat.S_ISDIR(info.st_mode) and name not in directories
                or not stat.S_ISDIR(info.st_mode) and name not in allowed):
            raise ValueError("PLUGIN_UNLISTED_FILE")
    return root


def load_runtime(root=ROOT):
    root = verify_package(root)
    runtime = root / "runtime"
    modules = tuple(name.replace("-", "_") for name in PACKAGES)
    for name, module in tuple(sys.modules.items()):
        if not any(name == prefix or name.startswith(prefix + ".") for prefix in modules):
            continue
        source = getattr(module, "__file__", None)
        locations = tuple(getattr(module, "__path__", ()))
        if (source is None or not Path(source).resolve().is_relative_to(runtime.resolve())
                or any(not Path(location).resolve().is_relative_to(runtime.resolve()) for location in locations)):
            raise ValueError("PLUGIN_EXTERNAL_RUNTIME_MODULE")
    for name in PACKAGES:
        source = runtime / "packages" / name / "src"
        if not source.is_dir():
            raise ValueError("PLUGIN_RUNTIME_MISSING")
        sys.path.insert(0, str(source))
    return runtime


def connection(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("BRIDGE_CONFIG_REQUIRED: supply --config or configure connection.json in the installed plugin root")
    value = read_object(path)
    required = {"prepared_run", "scheduler_root", "backend"}
    if not required <= value.keys() or value.keys() - required - {"private_context"}:
        raise ValueError("BRIDGE_CONFIG_FIELDS_INVALID")
    if value["backend"] not in ("diagnostic", "production"):
        raise ValueError("BRIDGE_BACKEND_INVALID")
    for name in ("prepared_run", "scheduler_root"):
        if not isinstance(value[name], str) or not value[name] or not Path(value[name]).is_absolute():
            raise ValueError("BRIDGE_ABSOLUTE_PATH_REQUIRED: " + name)
    run = Path(value["prepared_run"])
    if not run.is_file() or run.is_symlink():
        raise ValueError("PREPARED_GRAPH_REQUIRED")
    manifest = read_object(run)
    if manifest.get("schema") != "bridge.workbuddy.diagnostic_run/1.0" or not manifest.get("session_id"):
        raise ValueError("PREPARED_GRAPH_INVALID")
    if value["backend"] == "production":
        for name in ("production_host", "production_nuke"):
            if not isinstance(manifest.get(name), dict) or not manifest[name]:
                raise ValueError("PRODUCTION_CONFIG_REQUIRED: " + name)
    context = value.get("private_context")
    if context is not None:
        if (not isinstance(context, dict) or set(context) != {"root", "project_id", "documents"}
                or not isinstance(context["root"], str) or not Path(context["root"]).is_absolute()
                or not isinstance(context["project_id"], str) or not context["project_id"]
                or not isinstance(context["documents"], dict)):
            raise ValueError("PRIVATE_CONTEXT_CONFIG_INVALID")
    return value


def plugin_adapter(context):
    from dcc_task_runtime.private_context import PrivateContextError, PrivateContextReader
    from vfx_pipeline.workbuddy_graph_mcp import GraphMCP, _schema_error
    from vfx_pipeline.workbuddy_mcp import _schema, _text_content

    reader = None if context is None else PrivateContextReader(**context)
    schema = _schema({"query": {"type": "string", "maxLength": 512},
                      "domain": {"type": "string", "minLength": 1, "maxLength": 128},
                      "version": {"type": "string", "minLength": 1, "maxLength": 128},
                      "limit": {"type": "integer", "minimum": 1, "maximum": 4},
                      "max_bytes": {"type": "integer", "minimum": 1, "maximum": 16384},
                      "read_budget": {"type": "integer", "minimum": 1, "maximum": 262144}}, ("domain", "version"))

    class PluginMCP(GraphMCP):
        def __init__(self, facade):
            super().__init__(facade)
            self.server_name = "bridge-vfx-plugin"
            self.tools = [*self.tools, {"name": "private_context_query", "description":
                "Read bounded untrusted project context pinned by the controller; cannot change scope or execution permissions.",
                "inputSchema": schema, "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                                       "idempotentHint": True, "openWorldHint": False}}]

        def _call(self, params):
            if params.get("name") != "private_context_query":
                return super()._call(params)
            arguments = params.get("arguments", {})
            if (set(params) - {"name", "arguments", "_meta"} or not isinstance(arguments, dict)
                    or _schema_error(arguments, schema)):
                return {"isError": True, "content": [_text_content({"code": "INVALID_ARGUMENTS"})]}
            if reader is None:
                result = {"status": "not_configured", "content_role": "untrusted_data", "matches": []}
            else:
                try:
                    result = reader.search(**arguments)
                except PrivateContextError as error:
                    return {"isError": True, "content": [_text_content({"code": error.code})]}
            return {"isError": False, "content": [_text_content(result)]}

    return PluginMCP


def serve_connection(config, *, root=ROOT, stdin=None, stdout=None):
    value = connection(config)
    runtime = load_runtime(root)
    from vfx_pipeline.workbuddy_assembly import prepared_graph_facade
    from vfx_pipeline.workbuddy_mcp import serve

    adapter = plugin_adapter(value.get("private_context"))
    with prepared_graph_facade(value["prepared_run"], repo_root=runtime,
                               scheduler_root=Path(value["scheduler_root"]), backend=value["backend"],
                               allow_software_processes=False) as facade:
        serve(facade, stdin=stdin, stdout=stdout, adapter_class=adapter)


def serve_entry(projects=None):
    """未选工程时也启动真实插件入口，复用协议而不提前挂载生产宿主。"""
    load_runtime()
    from vfx_pipeline.project_entry import ProjectEntry, EntryMCP
    from vfx_pipeline.workbuddy_mcp import serve
    entry = ProjectEntry(projects)
    try:
        serve(entry, adapter_class=EntryMCP)
    finally:
        entry.close()


def configure(args):
    runtime = load_runtime()
    sys.path.insert(0, str(runtime / "tools"))
    from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory

    value = {"prepared_run": str(args.prepared_run.resolve()), "scheduler_root": str(args.scheduler_root.resolve()),
             "backend": args.backend}
    if any(item is not None for item in (args.context_root, args.project_id, args.context_documents)):
        if any(item is None for item in (args.context_root, args.project_id, args.context_documents)):
            raise ValueError("PRIVATE_CONTEXT_CONFIG_REQUIRED: supply root, project-id and documents together")
        value["private_context"] = {"root": str(args.context_root.absolute()), "project_id": args.project_id,
                                    "documents": read_object(args.context_documents)}
        plugin_adapter(value["private_context"])
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("CONFIG_EXISTS: choose a new config file")
    ensure_private_directory(output.parent)
    atomic_write(output, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), owned_root=output.parent)
    try:
        connection(output)
    except BaseException:
        from dcc_task_runtime.platform_support import remove_owned_path
        remove_owned_path(output, owned_root=output.parent)
        raise
    server = {"command": sys.executable, "args": ["-I", "-B", str(ROOT / "scripts/bridge_mcp.py"), "serve", "--config", str(output)],
              "cwd": str(ROOT)}
    print(json.dumps({"mcpServers": {"bridge-graph": server}}, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bridge plugin adapter for the existing prepared graph MCP")
    subparsers = parser.add_subparsers(dest="action", required=True)
    serving = subparsers.add_parser("serve")
    serving.add_argument("--config", type=Path, default=ROOT / "connection.json")
    configuring = subparsers.add_parser("configure")
    configuring.add_argument("--prepared-run", type=Path, required=True)
    configuring.add_argument("--scheduler-root", type=Path, required=True)
    configuring.add_argument("--backend", choices=("diagnostic", "production"), default="diagnostic")
    configuring.add_argument("--output", type=Path, required=True)
    configuring.add_argument("--context-root", type=Path)
    configuring.add_argument("--project-id")
    configuring.add_argument("--context-documents", type=Path)
    serving.add_argument("--projects", type=Path)
    registering = subparsers.add_parser("register-project")
    registering.add_argument("--projects", type=Path)
    registering.add_argument("--project-id", required=True)
    registering.add_argument("--label", required=True)
    source = registering.add_mutually_exclusive_group(required=True)
    source.add_argument("--preparation", type=Path, help="Existing creative or geometry preparation; kind is validated from its schema")
    source.add_argument("--prepared-run", type=Path)
    registering.add_argument("--scheduler-root", type=Path)
    registering.add_argument("--backend", choices=("diagnostic", "production"), default="diagnostic")
    delivery = subparsers.add_parser("register-delivery")
    delivery.add_argument("--projects", type=Path)
    delivery.add_argument("--project-id", required=True)
    delivery.add_argument("--label", required=True)
    delivery.add_argument("--source", type=Path, required=True)
    creation = subparsers.add_parser("configure-task-creation")
    creation.add_argument("--projects",type=Path)
    creation.add_argument("--source-project",action="append",required=True)
    creation.add_argument("--instruction",required=True)
    creation.add_argument("--template",type=Path)
    authorizing = subparsers.add_parser("authorize-created-task")
    authorizing.add_argument("--projects",type=Path)
    authorizing.add_argument("--project-id",required=True)
    authorizing.add_argument("--instruction",required=True)
    feedback = subparsers.add_parser("authorize-feedback")
    feedback.add_argument("--projects",type=Path)
    feedback.add_argument("--project-id",required=True)
    feedback.add_argument("--plan-id",required=True)
    feedback.add_argument("--request-id",required=True)
    feedback.add_argument("--instruction",required=True)
    feedback.add_argument("--supersede-operation")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 11):
            raise ValueError("PYTHON_311_REQUIRED")
        if args.action == "configure":
            configure(args)
        elif args.action in ("configure-task-creation","authorize-created-task"):
            load_runtime()
            from vfx_pipeline.project_entry import default_projects_path
            from vfx_pipeline.task_creation import configure, authorize
            registry=args.projects or default_projects_path()
            from houdini_bridge.official_karma_observation import file_record
            value=(configure(registry,args.source_project,args.instruction,template_record=file_record(args.template.resolve()) if args.template else None) if args.action=="configure-task-creation"
                   else authorize(registry,args.project_id,args.instruction))
            print(json.dumps(value,ensure_ascii=False))
        elif args.action == "authorize-feedback":
            load_runtime()
            from vfx_pipeline.project_entry import default_projects_path
            from vfx_pipeline.geometry_feedback import authorize
            print(json.dumps(authorize(args.projects or default_projects_path(),args.project_id,args.plan_id,args.request_id,args.instruction,supersede_operation=args.supersede_operation),ensure_ascii=False))
        elif args.action == "register-delivery":
            load_runtime()
            from vfx_pipeline.project_entry import default_projects_path
            from vfx_pipeline.completed_geometry_delivery import register_delivery
            print(json.dumps(register_delivery(args.projects or default_projects_path(), args.project_id,
                args.label, args.source), ensure_ascii=False))
        elif args.action == "register-project":
            load_runtime()
            from vfx_pipeline.project_entry import register_project, default_projects_path
            if args.prepared_run is not None and args.scheduler_root is None:
                raise ValueError("BRIDGE_SCHEDULER_ROOT_REQUIRED")
            print(json.dumps(register_project(args.projects or default_projects_path(), args.project_id, args.label,
                preparation=args.preparation, prepared_run=args.prepared_run,
                scheduler_root=args.scheduler_root, backend=args.backend), ensure_ascii=False))
        elif args.config.exists():
            serve_connection(args.config)
        elif args.config != ROOT / "connection.json":
            raise ValueError("BRIDGE_CONFIG_REQUIRED")
        else:
            serve_entry(args.projects)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
