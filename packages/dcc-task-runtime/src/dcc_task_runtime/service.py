"""A small public facade around TaskEngine for bridge CLIs and MCP adapters."""

from __future__ import annotations

from typing import Any, Mapping

from .engine import TaskEngine


class TaskService:
    def __init__(self, engine: TaskEngine) -> None:
        self.engine = engine

    def plan(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return self.engine.plan(spec)

    def start(self, spec: Mapping[str, Any], background: bool = False) -> dict[str, Any]:
        return self.engine.start(spec, background=background)

    def status(self, task_id: str) -> dict[str, Any]:
        return self.engine.store.load_status(task_id)

    def events(self, task_id: str, after_seq: int = 0) -> dict[str, Any]:
        return {"task_id": task_id, "events": list(self.engine.store.events(task_id, after_seq))}

    def cancel(self, task_id: str) -> dict[str, Any]:
        return self.engine.cancel(task_id)

    def resume(self, task_id: str, background: bool = False) -> dict[str, Any]:
        return self.engine.resume(task_id, background=background)

    def result(self, task_id: str) -> dict[str, Any] | None:
        return self.engine.result(task_id)

