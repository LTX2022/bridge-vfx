"""CLI for the local Houdini Bridge client."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .client import BridgeError, HoudiniClient, discover_instances
from .install import install, install_all, uninstall
from .paths import package_directories
from .tasks import task_service


def _params(items: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"parameter must be key=value: {item}")
        key, raw = item.split("=", 1)
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            result[key] = raw
    return result


def _client(port: Optional[int]) -> HoudiniClient:
    if port is not None:
        return HoudiniClient(port)
    instances = discover_instances()
    if not instances:
        raise BridgeError("INSTANCE_NOT_FOUND", "No running Houdini Bridge instance was found")
    instance = instances[0]
    return HoudiniClient(instance.port, token=instance.token)


def _watch(service, task_id: str, json_events: bool, poll_interval: float) -> int:
    """Stream durable events until the task reaches a terminal state."""
    terminal = {
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "PARTIAL",
        "AWAITING_INPUT",
        "DIAGNOSIS_INCONCLUSIVE",
        "UNSUPPORTED",
    }
    sequence = 0
    try:
        while True:
            event_payload = service.events(task_id, sequence)
            for event in event_payload.get("events") or []:
                sequence = max(sequence, int(event.get("seq") or 0))
                if json_events:
                    print(json.dumps({"type": "event", **event}, ensure_ascii=False), flush=True)
                else:
                    percent = "--" if event.get("percent") is None else "{:.2f}%".format(float(event["percent"]))
                    print("{} {} {} {}/{} {}".format(event.get("phase"), event.get("step"), percent, event.get("completed_units", 0), event.get("total_units", 0), event.get("message", "")), flush=True)
            status = service.status(task_id)
            if status.get("state") in terminal:
                result = service.result(task_id)
                if json_events:
                    print(json.dumps({"type": "result", "task_id": task_id, "status": status, "result": result}, ensure_ascii=False), flush=True)
                else:
                    print(json.dumps({"task_id": task_id, "status": status, "result": result}, ensure_ascii=False, indent=2), flush=True)
                return 0 if status.get("state") == "SUCCEEDED" else 1
            time.sleep(max(0.05, poll_interval))
    except KeyboardInterrupt:
        cancelled = service.cancel(task_id)
        if json_events:
            print(json.dumps({"type": "cancel_requested", "task_id": task_id, "status": cancelled}, ensure_ascii=False), flush=True)
        else:
            print("cancel requested for task_id={}".format(task_id), flush=True)
        return 130


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="houdini-bridge")
    parser.add_argument("--port", type=int)
    commands = parser.add_subparsers(dest="subcommand")
    from . import task_host as _task_host
    _task_host.register(commands)
    commands.add_parser("health")
    commands.add_parser("instances")
    commands.add_parser("doctor")
    call = commands.add_parser("call")
    call.add_argument("command")
    call.add_argument("--param", action="append", default=[])
    call.add_argument("--json")
    install_command = commands.add_parser("install")
    install_command.add_argument("--plugin-root", type=Path, required=True)
    install_command.add_argument("--packages-dir", type=Path)
    uninstall_command = commands.add_parser("uninstall")
    uninstall_command.add_argument("--packages-dir", type=Path)
    task = commands.add_parser("task")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    for name in ("plan", "start"):
        item = task_commands.add_parser(name)
        item.add_argument("--spec", type=Path, required=True)
    for name in ("status", "cancel", "resume", "result"):
        item = task_commands.add_parser(name)
        item.add_argument("task_id")
    run = task_commands.add_parser("run", help="start a task and optionally stream progress")
    run.add_argument("--spec", type=Path)
    run.add_argument("--resume", dest="resume_task_id")
    run.add_argument("--watch", action="store_true")
    run.add_argument("--json-events", action="store_true", help="emit NDJSON event records")
    run.add_argument("--poll-interval", type=float, default=0.25)
    events = task_commands.add_parser("events")
    events.add_argument("task_id")
    events.add_argument("--after-seq", type=int, default=0)
    arguments = parser.parse_args(argv)
    if getattr(arguments, "task_host_command", None):
        return arguments.func(arguments)
    try:
        if arguments.subcommand == "instances":
            print(json.dumps([{"port": item.port, **item.data} for item in discover_instances()], ensure_ascii=False, indent=2))
            return 0
        if arguments.subcommand == "doctor":
            instances = [{"port": item.port, **item.data} for item in discover_instances()]
            print(
                json.dumps(
                    {
                        "ok": bool(instances),
                        "instances": instances,
                        "hint": None if instances else "Start Houdini with the bridge add-on installed, then run `houdini-bridge instances`.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if instances else 1
        if arguments.subcommand == "install":
            files = install_all(arguments.plugin_root, [arguments.packages_dir] if arguments.packages_dir else package_directories())
            print(json.dumps({"installed": [str(path) for path in files], "houdini_env_modified": False}, ensure_ascii=False, indent=2))
            return 0
        if arguments.subcommand == "uninstall":
            return 0 if uninstall(arguments.packages_dir) else 1
        if arguments.subcommand == "task":
            service = task_service(_client(arguments.port))
            if arguments.task_command in {"plan", "start"}:
                spec = json.loads(arguments.spec.read_text(encoding="utf-8"))
                result = service.plan(spec) if arguments.task_command == "plan" else service.start(spec)
            elif arguments.task_command == "run":
                if bool(arguments.spec) == bool(arguments.resume_task_id):
                    raise ValueError("task run requires exactly one of --spec or --resume")
                watch = bool(arguments.watch or arguments.json_events)
                if arguments.resume_task_id:
                    started = service.resume(arguments.resume_task_id, background=watch)
                else:
                    spec = json.loads(arguments.spec.read_text(encoding="utf-8"))
                    started = service.start(spec, background=watch)
                task_id = started["task_id"]
                if watch:
                    if arguments.json_events:
                        print(json.dumps({"type": "task_started", "task_id": task_id}, ensure_ascii=False), flush=True)
                    else:
                        print("task_id={} started".format(task_id), flush=True)
                    return _watch(service, task_id, bool(arguments.json_events), float(arguments.poll_interval))
                result = started
            elif arguments.task_command == "status":
                result = service.status(arguments.task_id)
            elif arguments.task_command == "events":
                result = service.events(arguments.task_id, arguments.after_seq)
            elif arguments.task_command == "cancel":
                result = service.cancel(arguments.task_id)
            elif arguments.task_command == "resume":
                result = service.resume(arguments.task_id)
            else:
                result = service.result(arguments.task_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        client = _client(arguments.port)
        if arguments.subcommand in {None, "health"}:
            print(json.dumps(client.health(), ensure_ascii=False, indent=2))
            return 0
        params = json.loads(arguments.json) if arguments.json else _params(arguments.param)
        print(json.dumps(client.call(arguments.command, params), ensure_ascii=False, indent=2))
        return 0
    except (BridgeError, ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "code": getattr(exc, "code", "INVALID_ARGUMENT"), "message": str(exc), "hint": getattr(exc, "hint", None)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
