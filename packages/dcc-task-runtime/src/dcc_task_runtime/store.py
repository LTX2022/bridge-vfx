"""Atomic local persistence for task status, events, and result evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from uuid import uuid4

from .models import TaskEvent, TaskResult, TaskSpec, TaskState


class TaskStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def create(self, spec: TaskSpec, plan: dict[str, Any]) -> str:
        task_id = uuid4().hex
        directory = self.task_dir(task_id)
        directory.mkdir(parents=True, exist_ok=False)
        self._write_json(directory / "spec.json", spec.to_dict())
        self._write_json(directory / "plan.json", plan)
        self._write_json(directory / "status.json", {"task_id": task_id, "state": TaskState.QUEUED.value, "completed_units": 0, "total_units": int(plan.get("total_units") or 0), "seq": 0})
        (directory / "events.jsonl").touch()
        return task_id

    def task_dir(self, task_id: str) -> Path:
        if not task_id or any(character not in "0123456789abcdef" for character in task_id):
            raise ValueError("invalid task id")
        return self.root / task_id

    def load_status(self, task_id: str) -> dict[str, Any]:
        return self._read_json(self.task_dir(task_id) / "status.json")

    def update_status(self, task_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            status = self.load_status(task_id)
            status.update(changes)
            self._write_json(self.task_dir(task_id) / "status.json", status)
            return status

    def append_event(self, task_id: str, event: TaskEvent) -> None:
        with self._lock:
            status = self.load_status(task_id)
            if event.seq <= int(status.get("seq") or 0):
                raise ValueError("event sequence must increase")
            event_path = self.task_dir(task_id) / "events.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            status.update({"seq": event.seq, "state": event.state.value, "completed_units": event.completed_units, "total_units": event.total_units, "percent": event.percent, "phase": event.phase, "step": event.step})
            self._write_json(self.task_dir(task_id) / "status.json", status)

    def events(self, task_id: str, after_seq: int = 0) -> Iterable[dict[str, Any]]:
        path = self.task_dir(task_id) / "events.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    event = json.loads(line)
                    if int(event["seq"]) > after_seq:
                        yield event

    def save_result(self, result: TaskResult) -> None:
        self._write_json(self.task_dir(result.task_id) / "result.json", result.to_dict())
        self.update_status(result.task_id, state=result.state.value)

    def load_result(self, task_id: str) -> dict[str, Any] | None:
        path = self.task_dir(task_id) / "result.json"
        return self._read_json(path) if path.is_file() else None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

