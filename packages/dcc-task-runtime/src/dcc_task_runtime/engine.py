"""Recipe execution with durable checkpoints, real units, and bounded repair."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from .models import ErrorCode, TaskEvent, TaskResult, TaskSpec, TaskState
from .store import TaskStore


@dataclass(frozen=True)
class Step:
    identifier: str
    phase: str
    action: str
    weight: int = 1
    required: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    gate_policy: str = "legacy_first_party"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "phase": self.phase,
            "action": self.action,
            "weight": self.weight,
            "required": self.required,
            "params": dict(self.params),
            "gate_policy": self.gate_policy,
        }


class Adapter(Protocol):
    def probe(self, spec: TaskSpec) -> dict[str, Any]:
        ...

    def execute(self, step: Step, spec: TaskSpec, task_dir: Path) -> dict[str, Any]:
        ...

    def repair(self, step: Step, spec: TaskSpec, task_dir: Path, failure: Exception) -> bool:
        ...


class Recipe(Protocol):
    identifier: str

    def steps(self, spec: TaskSpec, capabilities: Mapping[str, Any]) -> list[Step]:
        ...


class RecipeRegistry:
    def __init__(self) -> None:
        self._recipes: dict[str, Recipe] = {}

    def register(self, recipe: Recipe) -> None:
        if recipe.identifier in self._recipes:
            raise ValueError(f"duplicate recipe: {recipe.identifier}")
        self._recipes[recipe.identifier] = recipe

    def get(self, identifier: str) -> Recipe:
        try:
            return self._recipes[identifier]
        except KeyError as exc:
            raise ValueError(f"unsupported recipe: {identifier}") from exc


class TaskEngine:
    """Runs one adapter-backed task at a time per task id.

    The engine intentionally counts known plan units rather than estimating wall
    time. A recipe must reserve repair units up front if it wants monotonic
    percentage progress during repair.
    """

    def __init__(self, store: TaskStore, adapter: Adapter, recipes: RecipeRegistry, max_repairs: int = 3) -> None:
        self.store = store
        self.adapter = adapter
        self.recipes = recipes
        self.max_repairs = max_repairs
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def plan(self, raw_spec: Mapping[str, Any]) -> dict[str, Any]:
        spec = TaskSpec.from_mapping(raw_spec)
        capabilities = self.adapter.probe(spec)
        recipe = self.recipes.get(spec.task_type)
        steps = recipe.steps(spec, capabilities)
        if not steps:
            raise ValueError("recipe returned no steps")
        total = sum(max(1, step.weight) for step in steps)
        return {"spec": spec.to_dict(), "capabilities": capabilities, "steps": [step.to_dict() for step in steps], "total_units": total, "max_repairs": self.max_repairs}

    def start(self, raw_spec: Mapping[str, Any], background: bool = True) -> dict[str, Any]:
        plan = self.plan(raw_spec)
        spec = TaskSpec.from_mapping(plan["spec"])
        task_id = self.store.create(spec, plan)
        self._cancel[task_id] = threading.Event()
        if background:
            thread = threading.Thread(target=self._run, args=(task_id,), name=f"dcc-task-{task_id[:8]}", daemon=True)
            self._threads[task_id] = thread
            thread.start()
        else:
            self._run(task_id)
        return {"task_id": task_id, "status": self.store.load_status(task_id), "plan": plan}

    def cancel(self, task_id: str) -> dict[str, Any]:
        event = self._cancel.setdefault(task_id, threading.Event())
        event.set()
        return self.store.update_status(task_id, cancel_requested=True)

    def resume(self, task_id: str, background: bool = True) -> dict[str, Any]:
        status = self.store.load_status(task_id)
        if status.get("state") not in {
            TaskState.PARTIAL.value,
            TaskState.CANCELLED.value,
            TaskState.FAILED.value,
            TaskState.AWAITING_INPUT.value,
            TaskState.DIAGNOSIS_INCONCLUSIVE.value,
        }:
            raise ValueError("only PARTIAL, CANCELLED, FAILED, AWAITING_INPUT, or DIAGNOSIS_INCONCLUSIVE tasks can resume")
        if status.get("state") in {
            TaskState.AWAITING_INPUT.value,
            TaskState.DIAGNOSIS_INCONCLUSIVE.value,
        }:
            self._rewind_diagnostic_verification(task_id)
        self._cancel[task_id] = threading.Event()
        if background:
            thread = threading.Thread(target=self._run, args=(task_id,), name=f"dcc-task-{task_id[:8]}", daemon=True)
            self._threads[task_id] = thread
            thread.start()
        else:
            self._run(task_id)
        return {"task_id": task_id, "status": self.store.load_status(task_id)}

    def result(self, task_id: str) -> dict[str, Any] | None:
        return self.store.load_result(task_id)

    def _run(self, task_id: str) -> None:
        task_dir = self.store.task_dir(task_id)
        plan = json.loads((task_dir / "plan.json").read_text(encoding="utf-8"))
        spec = TaskSpec.from_mapping(json.loads((task_dir / "spec.json").read_text(encoding="utf-8")))
        steps = [
            Step(
                item["id"],
                item["phase"],
                item["action"],
                int(item.get("weight") or 1),
                bool(item.get("required", True)),
                dict(item.get("params") or {}),
                str(item.get("gate_policy") or "legacy_first_party"),
            )
            for item in plan["steps"]
        ]
        checkpoints_path = task_dir / "checkpoints.json"
        checkpoints = json.loads(checkpoints_path.read_text(encoding="utf-8")) if checkpoints_path.is_file() else {"completed": [], "artifacts": [], "gates": [], "repairs": 0, "step_outputs": {}}
        checkpoints.setdefault("step_outputs", {})
        if not isinstance(checkpoints["step_outputs"], dict):
            raise ValueError("task checkpoint step_outputs must be an object")
        completed_steps = set(checkpoints["completed"])
        completed_units = sum(step.weight for step in steps if step.identifier in completed_steps)
        started = time.monotonic()
        sequence = int(self.store.load_status(task_id).get("seq") or 0)

        def emit(step: Step, state: TaskState, message: str, error_code: Optional[str] = None) -> None:
            nonlocal sequence
            sequence += 1
            percent = round(completed_units * 100.0 / plan["total_units"], 2) if plan["total_units"] else None
            self.store.append_event(task_id, TaskEvent(sequence, task_id, step.phase, step.identifier, state, completed_units, plan["total_units"], percent, int((time.monotonic() - started) * 1000), message, error_code=error_code))

        self.store.update_status(task_id, state=TaskState.RUNNING.value, cancel_requested=False)
        for step in steps:
            if step.identifier in completed_steps:
                continue
            deferred_state = self._deferred_state(checkpoints["step_outputs"])
            if deferred_state is not TaskState.SUCCEEDED and str(step.phase).upper() in {
                "FINAL_RENDER",
                "ARTIFACT_VERIFY",
                "DELIVER",
            }:
                # A successful scaffold may continue through technical evidence
                # collection, but missing evidence must never fall through into
                # cache/final-render/delivery work.
                break
            if self._cancel.get(task_id, threading.Event()).is_set():
                emit(step, TaskState.CANCELLED, "cancellation acknowledged", ErrorCode.CANCELLED.value)
                self.store.save_result(TaskResult(task_id, TaskState.CANCELLED, tuple(checkpoints["artifacts"]), tuple(checkpoints["gates"]), next_action="Call task.resume when it is safe to continue.", step_outputs=dict(checkpoints["step_outputs"])))
                return
            emit(step, TaskState.RUNNING, f"starting {step.identifier}")
            attempt = 0
            while True:
                try:
                    result = self.adapter.execute(step, spec, task_dir)
                    if self._cancel.get(task_id, threading.Event()).is_set():
                        emit(step, TaskState.CANCELLED, "cancellation acknowledged", ErrorCode.CANCELLED.value)
                        self._write_checkpoints(checkpoints_path, checkpoints)
                        self.store.save_result(TaskResult(task_id, TaskState.CANCELLED, tuple(checkpoints["artifacts"]), tuple(checkpoints["gates"]), next_action="Call task.resume when it is safe to continue.", step_outputs=dict(checkpoints["step_outputs"])))
                        return
                    step_artifacts = list(result.get("artifacts") or [])
                    step_gates = list(result.get("gates") or [])
                    checkpoints["artifacts"].extend(step_artifacts)
                    checkpoints["gates"].extend(step_gates)
                    step_output = {
                        "step_id": step.identifier,
                        "phase": step.phase,
                        "action": step.action,
                        "artifacts": step_artifacts,
                        "gates": step_gates,
                        "output": dict(result.get("step_output") or {}),
                    }
                    outcome_state = str(result.get("outcome_state") or "").strip().upper()
                    if outcome_state == TaskState.SUCCEEDED.value:
                        for prior_output in checkpoints["step_outputs"].values():
                            if isinstance(prior_output, dict):
                                prior_output.pop("outcome_state", None)
                    elif outcome_state:
                        step_output["outcome_state"] = outcome_state
                    checkpoints["step_outputs"][step.identifier] = step_output
                    checkpoints["completed"].append(step.identifier)
                    completed_steps.add(step.identifier)
                    completed_units += step.weight
                    self._write_checkpoints(checkpoints_path, checkpoints)
                    emit(step, TaskState.RUNNING, f"completed {step.identifier}")
                    break
                except Exception as exc:
                    raw_code = getattr(exc, "code", None)
                    code = str(getattr(raw_code, "value", raw_code) or "")
                    if code == ErrorCode.AWAITING_INPUT.value or str(exc).startswith("AWAITING_INPUT:"):
                        checkpoints["waiting_step"] = step.identifier
                        self._write_checkpoints(checkpoints_path, checkpoints)
                        emit(step, TaskState.AWAITING_INPUT, str(exc), ErrorCode.AWAITING_INPUT.value)
                        self.store.save_result(TaskResult(task_id, TaskState.AWAITING_INPUT, tuple(checkpoints["artifacts"]), tuple(checkpoints["gates"]), error_code=ErrorCode.AWAITING_INPUT.value, error_message=str(exc), next_action=f"Resolve the missing input and resume gate {step.identifier}.", step_outputs=dict(checkpoints["step_outputs"])))
                        return
                    attempt += 1
                    repairable = attempt <= self.max_repairs and bool(self.adapter.repair(step, spec, task_dir, exc))
                    if repairable:
                        checkpoints["repairs"] += 1
                        self._write_checkpoints(checkpoints_path, checkpoints)
                        emit(step, TaskState.RUNNING, f"repairing {step.identifier}: {exc}")
                        continue
                    state = TaskState.PARTIAL if completed_steps else TaskState.FAILED
                    emit(step, state, f"failed {step.identifier}: {exc}", ErrorCode.REPAIR_EXHAUSTED.value if attempt > self.max_repairs else ErrorCode.INTERNAL_ERROR.value)
                    self.store.save_result(TaskResult(task_id, state, tuple(checkpoints["artifacts"]), tuple(checkpoints["gates"]), error_code=ErrorCode.REPAIR_EXHAUSTED.value if attempt > self.max_repairs else ErrorCode.INTERNAL_ERROR.value, error_message=str(exc), next_action=f"Resume from gate {step.identifier}.", step_outputs=dict(checkpoints["step_outputs"])))
                    return
        final_step = next(
            (step for step in reversed(steps) if step.identifier in completed_steps),
            steps[0],
        )
        final_state = self._deferred_state(checkpoints["step_outputs"])
        message = "all planned gates completed" if final_state is TaskState.SUCCEEDED else f"planned operations completed with {final_state.value}"
        emit(final_step, final_state, message)
        next_action = None
        if final_state is TaskState.DIAGNOSIS_INCONCLUSIVE:
            next_action = "Attach the missing field, AOV, sequence, or visual evidence and resume diagnosis."
        elif final_state is TaskState.AWAITING_INPUT:
            next_action = "Provide the requested input and resume the task."
        self.store.save_result(TaskResult(task_id, final_state, tuple(checkpoints["artifacts"]), tuple(checkpoints["gates"]), next_action=next_action, step_outputs=dict(checkpoints["step_outputs"])))

    @staticmethod
    def _write_checkpoints(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _deferred_state(step_outputs: Mapping[str, Any]) -> TaskState:
        deferred = [
            str(item.get("outcome_state") or "")
            for item in step_outputs.values()
            if isinstance(item, Mapping)
        ]
        for candidate in (
            TaskState.UNSUPPORTED,
            TaskState.AWAITING_INPUT,
            TaskState.DIAGNOSIS_INCONCLUSIVE,
            TaskState.PARTIAL,
        ):
            if candidate.value in deferred:
                return candidate
        return TaskState.SUCCEEDED

    def _rewind_diagnostic_verification(self, task_id: str) -> None:
        """Re-run evidence steps after an operator supplies missing evidence.

        Diagnostic tasks used to mark every step complete and ``resume`` then
        performed no work.  Rewinding from the first technical verification
        retains the editable build while allowing a restarted process to cook
        and inspect newly attached fields/AOVs.  Old checkpoints without
        step-owned outputs remain readable; their aggregate legacy gates are
        retained because ownership cannot be reconstructed safely.
        """

        task_dir = self.store.task_dir(task_id)
        plan = json.loads((task_dir / "plan.json").read_text(encoding="utf-8"))
        checkpoint_path = task_dir / "checkpoints.json"
        if not checkpoint_path.is_file():
            return
        checkpoints = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        completed = [str(item) for item in checkpoints.get("completed") or []]
        planned = list(plan.get("steps") or [])
        restart_index = next(
            (
                index
                for index, item in enumerate(planned)
                if str(item.get("phase") or "").upper() == "TECH_VERIFY"
            ),
            len(planned),
        )
        restart_ids = {
            str(item.get("id") or "")
            for item in planned[restart_index:]
            if str(item.get("id") or "")
        }
        if not restart_ids:
            return
        retained = [identifier for identifier in completed if identifier not in restart_ids]
        raw_outputs = checkpoints.get("step_outputs")
        outputs = dict(raw_outputs) if isinstance(raw_outputs, Mapping) else {}
        can_rebuild_aggregates = bool(outputs) and all(identifier in outputs for identifier in completed)
        for identifier in restart_ids:
            outputs.pop(identifier, None)
        checkpoints["completed"] = retained
        checkpoints["step_outputs"] = outputs
        if can_rebuild_aggregates:
            checkpoints["artifacts"] = [
                artifact
                for identifier in retained
                for artifact in list((outputs.get(identifier) or {}).get("artifacts") or [])
            ]
            checkpoints["gates"] = [
                gate
                for identifier in retained
                for gate in list((outputs.get(identifier) or {}).get("gates") or [])
            ]
        checkpoints["diagnostic_resume_count"] = int(checkpoints.get("diagnostic_resume_count") or 0) + 1
        self._write_checkpoints(checkpoint_path, checkpoints)
