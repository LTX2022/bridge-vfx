"""Task service backed by structured Nuke Bridge commands."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from dcc_task_runtime import GateKind, GatePolicy, GateRule, RecipeRegistry, Step, TaskEngine, TaskService, TaskSpec, TaskStore

from .client import NukeClient
from .operation_receipts import AGENT_RENDER_COMMANDS, freeze_agent_inputs
from .paths import manifests_dir
from .recipes import ReferenceCompositeRecipe, RenderDeliveryRecipe


_NUKE_FIRST_PARTY_ACTIONS = {
    "nuke_ping",
    "get_project_settings",
    "agent.nuke.probe",
    "agent.nuke.inspect_input",
    "agent.nuke.build_graph",
    "agent.nuke.render_preview",
    "agent.nuke.verify_preview",
    "agent.nuke.render_final",
    "agent.nuke.verify_final",
    "agent.nuke.deliver",
    "agent.nuke.composite.probe",
    "agent.nuke.composite.inspect_inputs",
    "agent.nuke.composite.build_graph",
    "agent.nuke.composite.audit_lineage",
    "agent.nuke.composite.apply_patch",
    "agent.nuke.composite.render_preview",
    "agent.nuke.composite.verify_preview",
    "agent.nuke.composite.render_final",
    "agent.nuke.composite.verify_final",
    "agent.nuke.composite.deliver",
}
_LINEAGE_RULE = GateRule("reference_isolated_from_final_write", GateKind.VERIFICATION)
_TOPOLOGY_RULE = GateRule("composite_topology_intact", GateKind.VERIFICATION)
_NUKE_STRICT_GATE_POLICIES = {
    "nuke_ping": GatePolicy(
        "nuke_ping",
        allow_silent_operation=True,
        silent_operation_name="nuke_ping_completed",
        allowed_phases=("PROBE",),
    ),
    "get_project_settings": GatePolicy(
        "get_project_settings",
        allow_silent_operation=True,
        silent_operation_name="nuke_project_inspected",
        allowed_phases=("INSPECT",),
    ),
    "agent.nuke.probe": GatePolicy(
        "agent.nuke.probe",
        (GateRule("nuke_running", GateKind.CAPABILITY, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("nuke_running",),),
        allowed_phases=("PROBE",),
    ),
    "agent.nuke.inspect_input": GatePolicy(
        "agent.nuke.inspect_input",
        (GateRule("source_exr", GateKind.VERIFICATION),),
        (("source_exr",),),
        allowed_phases=("INSPECT",),
    ),
    "agent.nuke.build_graph": GatePolicy(
        "agent.nuke.build_graph",
        (GateRule("editable_nuke_graph", GateKind.VERIFICATION),),
        (("editable_nuke_graph",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.nuke.render_preview": GatePolicy(
        "agent.nuke.render_preview",
        (GateRule("preview_rendered", GateKind.OPERATION, aliases=("preview_render_started",), legacy_kinds=(GateKind.PROGRESS.value,)),),
        (("preview_rendered",),),
        allowed_phases=("PREVIEW_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.nuke.verify_preview": GatePolicy(
        "agent.nuke.verify_preview",
        (GateRule("preview_artifact", GateKind.VERIFICATION),),
        (("preview_artifact",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.nuke.render_final": GatePolicy(
        "agent.nuke.render_final",
        (GateRule("final_rendered", GateKind.OPERATION, aliases=("final_render_started",), legacy_kinds=(GateKind.PROGRESS.value,)),),
        (("final_rendered",),),
        allowed_phases=("FINAL_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.nuke.verify_final": GatePolicy(
        "agent.nuke.verify_final",
        (GateRule("final_artifacts", GateKind.VERIFICATION),),
        (("final_artifacts",),),
        allowed_phases=("ARTIFACT_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.nuke.deliver": GatePolicy(
        "agent.nuke.deliver",
        (GateRule("delivery_ready", GateKind.VERIFICATION),),
        (("delivery_ready",),),
        allowed_phases=("DELIVER",),
    ),
    "agent.nuke.composite.probe": GatePolicy(
        "agent.nuke.composite.probe",
        (GateRule("nuke_composite_available", GateKind.CAPABILITY),),
        (("nuke_composite_available",),),
        allowed_phases=("PROBE",),
    ),
    "agent.nuke.composite.inspect_inputs": GatePolicy(
        "agent.nuke.composite.inspect_inputs",
        (GateRule("composite_inputs_exist", GateKind.VERIFICATION),),
        (("composite_inputs_exist",),),
        allowed_phases=("INSPECT",),
    ),
    "agent.nuke.composite.build_graph": GatePolicy(
        "agent.nuke.composite.build_graph",
        (GateRule("editable_native_composite_graph", GateKind.OPERATION), _TOPOLOGY_RULE, _LINEAGE_RULE),
        (
            ("editable_native_composite_graph",),
            ("composite_topology_intact",),
            ("reference_isolated_from_final_write",),
        ),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.nuke.composite.audit_lineage": GatePolicy(
        "agent.nuke.composite.audit_lineage",
        (_LINEAGE_RULE,),
        (("reference_isolated_from_final_write",),),
        allowed_phases=("TECH_VERIFY", "ARTIFACT_VERIFY"),
        legacy_phases=("VERIFY",),
    ),
    "agent.nuke.composite.apply_patch": GatePolicy(
        "agent.nuke.composite.apply_patch",
        (GateRule("composite_patch_applied", GateKind.OPERATION), _LINEAGE_RULE),
        (("composite_patch_applied",), ("reference_isolated_from_final_write",)),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.nuke.composite.render_preview": GatePolicy(
        "agent.nuke.composite.render_preview",
        (
            GateRule(
                "composite_preview_rendered",
                GateKind.OPERATION,
                aliases=("composite_preview_render_started",),
                legacy_kinds=(GateKind.PROGRESS.value,),
            ),
        ),
        (("composite_preview_rendered",),),
        allowed_phases=("PREVIEW_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.nuke.composite.verify_preview": GatePolicy(
        "agent.nuke.composite.verify_preview",
        (GateRule("composite_preview_artifact", GateKind.VERIFICATION),),
        (("composite_preview_artifact",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.nuke.composite.render_final": GatePolicy(
        "agent.nuke.composite.render_final",
        (
            GateRule(
                "composite_final_rendered",
                GateKind.OPERATION,
                aliases=("composite_final_render_started",),
                legacy_kinds=(GateKind.PROGRESS.value,),
            ),
        ),
        (("composite_final_rendered",),),
        allowed_phases=("FINAL_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.nuke.composite.verify_final": GatePolicy(
        "agent.nuke.composite.verify_final",
        (_LINEAGE_RULE, GateRule("composite_final_artifacts", GateKind.VERIFICATION)),
        (("reference_isolated_from_final_write",), ("composite_final_artifacts",)),
        allowed_phases=("ARTIFACT_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.nuke.composite.deliver": GatePolicy(
        "agent.nuke.composite.deliver",
        (
            _TOPOLOGY_RULE,
            _LINEAGE_RULE,
            GateRule("editable_composite_script", GateKind.VERIFICATION),
        ),
        (
            ("composite_topology_intact",),
            ("reference_isolated_from_final_write",),
            ("editable_composite_script",),
        ),
        allowed_phases=("DELIVER",),
    ),
}


def nuke_gate_policy(action: str, strict: bool = True) -> GatePolicy:
    if action not in _NUKE_FIRST_PARTY_ACTIONS:
        raise RuntimeError(f"unregistered Nuke action has no gate policy: {action}")
    policy = _NUKE_STRICT_GATE_POLICIES.get(action)
    if policy is None:
        raise RuntimeError(f"Nuke action has no exact gate policy: {action}")
    return policy


class NukeCommandAdapter:
    def __init__(self, client: NukeClient) -> None:
        self.client = client
        self._owned_scene_fingerprints: dict[str, str] = {}

    def probe(self, _spec: TaskSpec) -> dict[str, Any]:
        return self.client.call("capabilities.get")

    def execute(self, step: Step, spec: TaskSpec, task_dir: Path) -> dict[str, Any]:
        if step.gate_policy not in {"strict", "legacy_first_party"}:
            raise RuntimeError("unknown Nuke step gate policy: {}".format(step.gate_policy))
        policy = nuke_gate_policy(step.action)
        policy.validate_phase(
            step.phase,
            allow_legacy=step.gate_policy == "legacy_first_party",
        )
        payload = {
            "task_id": task_dir.name,
            "schema_version": spec.schema_version,
            "intent": spec.intent,
            "constraints": spec.constraints,
            "render": spec.render,
            "delivery": spec.delivery,
            "target_scene": spec.target_scene,
            "target_scene_path": spec.target_scene_path,
            "inputs": list(spec.inputs),
            "step_params": dict(step.params),
        }
        request_id = None
        if step.action in AGENT_RENDER_COMMANDS:
            payload["agent_input_binding"] = freeze_agent_inputs(task_dir.name, list(spec.inputs))
        if step.action in {"agent.nuke.render_preview", "agent.nuke.render_final",
                           "agent.nuke.composite.render_preview", "agent.nuke.composite.render_final"}:
            request_id = self._freeze_render_request(step, spec, task_dir, payload)
        try:
            pre_scene_state = self._ensure_target_scene(spec, task_dir)
        except RuntimeError as exc:
            if request_id is None or "unowned unsaved changes" not in str(exc):
                raise
            recovered = self._recover_render_response(step, payload, request_id)
            post = recovered.get("post_scene_state") or {}
            fingerprint = self._complete_scene_fingerprint(post)
            target = Path(spec.target_scene_path).expanduser().resolve() if spec.target_scene_path else None
            if not target or self._scene_info_path(post) != target or not fingerprint:
                raise
            self._owned_scene_fingerprints[str(target)] = fingerprint
            pre_scene_state = self._ensure_target_scene(spec, task_dir)
        expected_pre_fingerprint = (
            self._complete_scene_fingerprint(pre_scene_state)
            if isinstance(pre_scene_state, dict)
            else ""
        )
        if expected_pre_fingerprint:
            payload["expected_pre_scene_fingerprint"] = expected_pre_fingerprint
        if request_id is not None:
            self._freeze_render_request(step, spec, task_dir, payload, freeze_scene=True)
            payload["request_id"] = request_id
        data = self.client.call(step.action, payload)
        if expected_pre_fingerprint:
            returned_pre = data.get("pre_scene_state")
            returned_fingerprint = (
                self._complete_scene_fingerprint(returned_pre)
                if isinstance(returned_pre, dict)
                else ""
            )
            if not returned_fingerprint or not hmac.compare_digest(
                returned_fingerprint,
                expected_pre_fingerprint,
            ):
                raise RuntimeError(
                    "SCENE_STATE_DRIFT: action did not honor the frozen pre-scene fingerprint"
                )
        gates = policy.normalize(
            step.identifier,
            data,
            allow_omitted_kind=step.gate_policy == "legacy_first_party",
        )
        if str(step.phase).upper() in {"TECH_VERIFY", "ARTIFACT_VERIFY", "DELIVER"} and not any(
            gate.get("kind") == GateKind.VERIFICATION.value and gate.get("passed") is True
            for gate in gates
        ):
            raise RuntimeError("{} requires a passing verification gate: {}".format(step.phase, gates))
        if any(not bool(gate.get("passed")) for gate in gates):
            raise RuntimeError(f"gate policy failed for {step.identifier}: {gates}")
        if spec.target_scene_path and str(step.phase).upper() != "DELIVER":
            self._record_target_scene_state(
                spec,
                task_dir,
                data.get("post_scene_state")
                if isinstance(data.get("post_scene_state"), dict)
                else None,
            )
        structured = {key: value for key, value in data.items() if key not in {"artifacts", "gates"}}
        result = {"artifacts": data.get("artifacts") or [], "gates": gates, "step_output": structured}
        outcome_state = policy.outcome_state(data, gates)
        if outcome_state:
            result["outcome_state"] = outcome_state
        return result

    def _freeze_render_request(self, step: Step, spec: TaskSpec, task_dir: Path,
                               payload: dict[str, Any], *, freeze_scene: bool = False) -> str:
        from dcc_task_runtime.execution_lock import execution_lock
        from dcc_task_runtime.owned_process import _atomic
        directory = Path(task_dir)
        if directory.is_symlink():
            raise RuntimeError("REQUEST_STATE_INVALID: Nuke task directory is a symlink")
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "nuke_render_requests.json"
        basis = {"task_directory": str(directory.resolve()), "task_spec": spec.to_dict(), "task_type": spec.task_type,
                 "step": step.to_dict(), "payload": {key: value for key, value in payload.items()
                     if key not in {"request_id", "expected_pre_scene_fingerprint"}}}
        content = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        identity = str(directory.resolve()) + "\0" + step.identifier
        explicit = step.params.get("request_id") if "request_id" in step.params else None
        if "request_id" in step.params and (not isinstance(explicit, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{2,120}", explicit.strip())):
            raise ValueError("request_id must be 2-120 chars of [A-Za-z0-9_.-]")
        request_id = explicit.strip() if explicit is not None else "nuke-step-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        record_key = step.identifier if explicit is None else step.identifier + "@" + request_id
        with execution_lock(path, directory.name):
            if path.is_symlink():
                raise RuntimeError("REQUEST_STATE_INVALID: Nuke request store is a symlink")
            if path.exists():
                try:
                    store = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise RuntimeError("REQUEST_STATE_INVALID: Nuke request store is unreadable") from exc
                if (not isinstance(store, dict) or store.get("schema") != "bridge.nuke.step-requests/1.0"
                        or store.get("task_directory") != str(directory.resolve())
                        or not isinstance(store.get("requests"), dict)):
                    raise RuntimeError("REQUEST_STATE_INVALID: Nuke request store binding changed")
            else:
                store = {"schema": "bridge.nuke.step-requests/1.0", "task_directory": str(directory.resolve()), "requests": {}}
            prior = store["requests"].get(record_key)
            if prior is not None and (not isinstance(prior, dict) or prior.get("request_id") != request_id
                                      or prior.get("content_sha256") != content):
                raise RuntimeError("CONTENT_CHANGED: Nuke task step already binds different request content")
            record = prior or {"request_id": request_id, "content_sha256": content}
            if freeze_scene:
                scene = payload.get("expected_pre_scene_fingerprint") or ""
                if "scene_fingerprint" in record and record["scene_fingerprint"] != scene:
                    recovered = self._recover_render_response(step, payload, request_id)
                    saved_post = recovered.get("post_scene_state") or {}
                    if not scene or scene != self._complete_scene_fingerprint(saved_post):
                        raise RuntimeError("CONTENT_CHANGED: Nuke render step frozen scene changed")
                record.setdefault("scene_fingerprint", scene)
            store["requests"][record_key] = record
            _atomic(path, store)
        return request_id

    def _recover_render_response(self, step: Step, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
        operation = "nrend-" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]
        try:
            record = self.client.call("render_status", {"task_id": operation})
        except Exception:
            return {}
        if not isinstance(record, dict) or record.get("state") != "COMPLETED" or record.get("request_id") != request_id:
            return {}
        binding = record.get("agent_binding") or {}
        digest = hashlib.sha256(json.dumps({key: value for key, value in payload.items()
            if key not in {"request_id", "expected_pre_scene_fingerprint", "_agent_render_binding"}},
            ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False).encode("utf-8")).hexdigest()
        if binding.get("command") != step.action or binding.get("payload_sha256") != digest:
            return {}
        result = record.get("agent_result")
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _validate_frozen_scene_file(cls, expected: Path, declared_sha256: str) -> None:
        declared = str(declared_sha256 or "").strip().lower()
        if not declared:
            return
        if not cls._is_sha256(declared):
            raise RuntimeError("SCENE_IDENTITY_REQUIRED: frozen_scene_sha256 must be 64 hex characters")
        if not expected.is_file() or expected.is_symlink():
            raise RuntimeError("SCENE_STATE_DRIFT: frozen Nuke script is missing or is a symlink")
        actual = cls._file_sha256(expected)
        if not hmac.compare_digest(actual, declared):
            raise RuntimeError("SCENE_STATE_DRIFT: frozen Nuke script bytes changed")

    @staticmethod
    def _is_sha256(value: Any) -> bool:
        text = str(value or "")
        return len(text) == 64 and all(
            character in "0123456789abcdef" for character in text.lower()
        )

    @classmethod
    def _effective_scene_sha256(cls, expected: Path, declared_sha256: str) -> str:
        declared = str(declared_sha256 or "").strip().lower()
        if declared:
            if not cls._is_sha256(declared):
                raise RuntimeError("SCENE_IDENTITY_REQUIRED: frozen_scene_sha256 must be 64 hex characters")
            return declared
        if not expected.is_file() or expected.is_symlink():
            raise RuntimeError("SCENE_STATE_DRIFT: target Nuke script is missing or is a symlink")
        return cls._file_sha256(expected)

    @staticmethod
    def _scene_info_path(info: dict[str, Any]) -> Path | None:
        raw = str(info.get("script") or "")
        return Path(raw).expanduser().resolve() if raw else None

    @staticmethod
    def _complete_scene_fingerprint(info: dict[str, Any]) -> str:
        if not bool(info.get("fingerprint_complete")):
            return ""
        fingerprint = str(info.get("scene_fingerprint") or "").lower()
        return fingerprint if NukeCommandAdapter._is_sha256(fingerprint) else ""

    @staticmethod
    def _scene_binding_path(task_dir: Path) -> Path:
        return Path(task_dir) / "nuke_scene_binding.json"

    @staticmethod
    def _binding_identity(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _loaded_addon_identity(self) -> dict[str, str]:
        capabilities = self.client.call("capabilities.get")
        path = str(capabilities.get("loaded_addon_path") or "")
        digest = str(capabilities.get("loaded_addon_sha256") or "").lower()
        if not path or not self._is_sha256(digest):
            raise RuntimeError("SCENE_STATE_DRIFT: loaded Nuke addon identity is unavailable")
        return {"loaded_addon_path": path, "loaded_addon_sha256": digest}

    def _load_persisted_scene_fingerprint(
        self,
        task_dir: Path | None,
        expected: Path,
        declared_sha256: str,
    ) -> str:
        if task_dir is None:
            return ""
        binding_path = self._scene_binding_path(task_dir)
        if not binding_path.exists():
            return ""
        if binding_path.is_symlink() or not binding_path.is_file():
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding is not a regular file")
        try:
            payload = json.loads(binding_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding is unreadable") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding is invalid")
        required_fields = {
            "schema",
            "task_id",
            "scene_path",
            "frozen_scene_sha256",
            "scene_fingerprint",
            "loaded_addon_path",
            "loaded_addon_sha256",
            "binding_identity",
        }
        if (
            set(payload) != required_fields
            or payload.get("schema") != "bridge-skills.nuke-scene-binding/1.0"
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding schema is unsupported")
        if any(
            not self._is_sha256(payload.get(field))
            for field in (
                "frozen_scene_sha256",
                "scene_fingerprint",
                "loaded_addon_sha256",
                "binding_identity",
            )
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding digest is invalid")
        if not str(payload.get("task_id") or "") or not str(payload.get("loaded_addon_path") or ""):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding subject is incomplete")
        unsigned = {key: value for key, value in payload.items() if key != "binding_identity"}
        expected_identity = self._binding_identity(unsigned)
        if not hmac.compare_digest(
            str(payload.get("binding_identity") or ""),
            expected_identity,
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding identity changed")
        current_addon = self._loaded_addon_identity()
        expected_scene_sha256 = self._effective_scene_sha256(expected, declared_sha256)
        if (
            str(payload.get("task_id") or "") != Path(task_dir).name
            or Path(str(payload.get("scene_path") or "")).expanduser().resolve() != expected
            or str(payload.get("frozen_scene_sha256") or "") != expected_scene_sha256
            or any(payload.get(key) != value for key, value in current_addon.items())
        ):
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding subject changed")
        return str(payload.get("scene_fingerprint") or "")

    def _persist_scene_fingerprint(
        self,
        task_dir: Path | None,
        expected: Path,
        declared_sha256: str,
        fingerprint: str,
    ) -> None:
        if task_dir is None:
            return
        if not self._is_sha256(fingerprint):
            raise RuntimeError("SCENE_STATE_DRIFT: full Nuke scene fingerprint is unavailable")
        directory = Path(task_dir)
        directory.mkdir(parents=True, exist_ok=True)
        binding_path = self._scene_binding_path(directory)
        if binding_path.is_symlink():
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke scene binding path is a symlink")
        payload = {
            "schema": "bridge-skills.nuke-scene-binding/1.0",
            "task_id": directory.name,
            "scene_path": str(expected),
            "frozen_scene_sha256": self._effective_scene_sha256(expected, declared_sha256),
            "scene_fingerprint": fingerprint,
            **self._loaded_addon_identity(),
        }
        payload["binding_identity"] = self._binding_identity(payload)
        temporary = directory / f".nuke_scene_binding.{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(binding_path)

    def _record_target_scene_state(
        self,
        spec: TaskSpec,
        task_dir: Path | None = None,
        post_scene_state: dict[str, Any] | None = None,
    ) -> None:
        expected = Path(str(spec.target_scene_path)).expanduser().resolve()
        if not isinstance(post_scene_state, dict):
            raise RuntimeError("SCENE_STATE_DRIFT: action omitted atomic post-scene state")
        info = post_scene_state
        if self._scene_info_path(info) != expected:
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke switched away from target.scene_path")
        if type(info.get("modified")) is not bool:
            raise RuntimeError("SCENE_STATE_DRIFT: action post-scene modified state is unavailable")
        fingerprint = self._complete_scene_fingerprint(info)
        if not fingerprint:
            raise RuntimeError("SCENE_STATE_DRIFT: full Nuke scene fingerprint is unavailable")
        self._owned_scene_fingerprints[str(expected)] = fingerprint
        self._persist_scene_fingerprint(
            task_dir,
            expected,
            str(spec.constraints.get("frozen_scene_sha256") or ""),
            fingerprint,
        )

    @staticmethod
    def _scene_target_binding(
        spec: TaskSpec,
        application: str,
    ) -> tuple[str, Optional[str], str, Optional[str], bool]:
        """Resolve a host binding while retaining legacy TaskSpec behavior."""

        constraints = getattr(spec, "constraints", {}) or {}
        if not isinstance(constraints, Mapping):
            constraints = {}
        raw_binding = constraints.get("bridge_scene_binding")
        if raw_binding is not None and not isinstance(raw_binding, Mapping):
            raise RuntimeError("AWAITING_INPUT: constraints.bridge_scene_binding must be an object")

        declared = raw_binding is not None
        binding: Any = raw_binding
        if str(getattr(spec, "schema_version", "")) == "2.1":
            resolver = getattr(spec, "scene_for", None)
            if callable(resolver):
                try:
                    binding = resolver(application)
                except Exception as exc:
                    raw_code = getattr(exc, "code", "AWAITING_INPUT")
                    code = getattr(raw_code, "value", raw_code)
                    raise RuntimeError(
                        f"{code}: could not resolve the {application} scene binding: {exc}"
                    ) from exc
            elif binding is None:
                binding = {
                    "scene_mode": getattr(spec, "target_scene", "new"),
                    "scene_path": getattr(spec, "target_scene_path", None),
                    "frozen_scene_sha256": constraints.get("frozen_scene_sha256"),
                }
            declared = True

        if not declared:
            return (
                str(getattr(spec, "target_scene", "new") or "new").strip().lower(),
                getattr(spec, "target_scene_path", None),
                str(constraints.get("frozen_scene_sha256") or "").strip().lower(),
                None,
                False,
            )

        allowed = {
            "scene_mode",
            "scene_path",
            "frozen_scene_sha256",
            "instance_identity",
        }
        if isinstance(binding, Mapping):
            unknown = sorted(str(key) for key in binding if key not in allowed)
            if unknown:
                raise RuntimeError(
                    "AWAITING_INPUT: scene binding contains unsupported fields: {}".format(
                        ", ".join(unknown)
                    )
                )
            mode = str(
                binding.get("scene_mode")
                or getattr(spec, "target_scene", "new")
                or "new"
            ).strip().lower()
            path_value = binding.get("scene_path")
            frozen_value = binding.get("frozen_scene_sha256")
            identity_value = binding.get("instance_identity")
        else:
            mode = str(getattr(binding, "scene_mode", "new") or "new").strip().lower()
            path_value = getattr(binding, "scene_path", None)
            frozen_value = getattr(binding, "frozen_scene_sha256", None)
            identity_value = getattr(binding, "instance_identity", None)
        if mode not in {"current", "existing", "new", "untitled"}:
            raise RuntimeError("AWAITING_INPUT: scene binding has an unsupported scene_mode")
        path = str(path_value).strip() if path_value else None
        if path and mode in {"new", "untitled"}:
            raise RuntimeError("AWAITING_INPUT: new/untitled Nuke scene binding must not contain scene_path")
        frozen = str(frozen_value or "").strip().lower()
        identity = str(identity_value).strip() if identity_value else None
        return mode, path, frozen, identity, True

    @staticmethod
    def _reported_scene_instance_identity(payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("instance_identity", "session", "session_id"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return None

    def _scene_instance_identity_matches(self, expected: str, observed: str) -> bool:
        if expected == observed:
            return True
        port = str(getattr(self.client, "port", "") or "").strip()
        return bool(port and expected.endswith(f":{port}:{observed}"))

    def _guard_new_scene_target(
        self,
        spec: TaskSpec,
        *,
        instance_identity: Optional[str],
    ) -> None:
        """Inspect the current script, then fail without claiming it as new."""

        info = self.client.call("script.info")
        if not isinstance(info, Mapping):
            raise RuntimeError("AWAITING_INPUT: Nuke script.info did not return an inspectable script object")
        modified = info.get("modified")
        if modified is not False:
            raise RuntimeError(
                "AWAITING_INPUT: cannot use the current Nuke script for a new target while its clean/dirty state is unknown or modified"
            )
        if not self._complete_scene_fingerprint(dict(info)):
            raise RuntimeError(
                "AWAITING_INPUT: Nuke script.info did not provide a complete scene fingerprint for a new target"
            )
        if instance_identity:
            observed = self._reported_scene_instance_identity(info)
            if observed is None:
                capabilities = self.client.call("capabilities.get")
                if isinstance(capabilities, Mapping):
                    observed = self._reported_scene_instance_identity(capabilities)
            if observed is None:
                raise RuntimeError(
                    "AWAITING_INPUT: the requested Nuke instance identity could not be confirmed"
                )
            if not self._scene_instance_identity_matches(instance_identity, observed):
                raise RuntimeError(
                    "AWAITING_INPUT: the requested Nuke instance identity does not match the inspected bridge session"
                )
        current_path = str(info.get("script") or "").strip()
        if current_path:
            raise RuntimeError(
                "AWAITING_INPUT: the current Nuke script is a user scene; it cannot be claimed as a new isolated target"
            )
        raise RuntimeError(
            "AWAITING_INPUT: Nuke Bridge has no registered isolated blank-script creation/ownership handshake"
        )

    def _ensure_target_scene(
        self,
        spec: TaskSpec,
        task_dir: Path | None = None,
    ) -> dict[str, Any] | None:
        scene_mode, target_scene_path, declared_sha256, instance_identity, binding_declared = (
            self._scene_target_binding(spec, "nuke")
        )
        if binding_declared and scene_mode in {"new", "untitled"}:
            if target_scene_path:
                raise RuntimeError("AWAITING_INPUT: new/untitled Nuke scene binding must not contain scene_path")
            self._guard_new_scene_target(
                spec,
                instance_identity=instance_identity,
            )
            return None
        if str(spec.schema_version) == "2.0":
            if not target_scene_path:
                if scene_mode not in {"new", "untitled"}:
                    raise RuntimeError(
                        "SCENE_IDENTITY_REQUIRED: strict v2 current/existing Nuke scenes "
                        "require scene_path and frozen_scene_sha256"
                    )
                return None
            if not self._is_sha256(declared_sha256):
                raise RuntimeError(
                    "SCENE_IDENTITY_REQUIRED: strict v2 Nuke scene_path requires "
                    "frozen_scene_sha256"
                )
        if not target_scene_path:
            return None
        expected = Path(target_scene_path).expanduser().resolve()
        self._validate_frozen_scene_file(expected, declared_sha256)
        # Never cache this answer across steps.  A user, callback, or another
        # bridge request can switch the current NK between any two actions.
        info = self.client.call("script.info")
        current = self._scene_info_path(info)
        modified = info.get("modified")
        fingerprint = self._complete_scene_fingerprint(info)
        if current == expected and modified is True:
            owned = self._owned_scene_fingerprints.get(str(expected)) or self._load_persisted_scene_fingerprint(
                task_dir,
                expected,
                declared_sha256,
            )
            if not owned or not fingerprint or not hmac.compare_digest(owned, fingerprint):
                raise RuntimeError(
                    "SCENE_STATE_DRIFT: target Nuke script has unowned unsaved changes"
                )
            return info
        if current == expected and modified is None:
            raise RuntimeError("SCENE_STATE_DRIFT: Nuke modified state is unavailable")
        if current == expected:
            if not fingerprint:
                raise RuntimeError("SCENE_STATE_DRIFT: full Nuke scene fingerprint is unavailable")
            self._owned_scene_fingerprints[str(expected)] = fingerprint
            return info
        if current != expected:
            if modified is not False:
                raise RuntimeError(
                    "SCENE_STATE_DRIFT: refusing to replace a Nuke script unless modified is explicitly false"
                )
            self.client.call(
                "open_script",
                {
                    "path": str(expected),
                    "sha256": declared_sha256,
                },
            )
            # The mutation command's echo is not independent evidence.  Read
            # the active Root again after open and bind the step to that value.
            reopened_info = self.client.call("script.info")
            reopened = self._scene_info_path(reopened_info)
            if reopened != expected:
                raise RuntimeError("Nuke did not open the exact target.scene_path")
            if reopened_info.get("modified") is not False:
                raise RuntimeError("SCENE_STATE_DRIFT: reopened Nuke script is unexpectedly modified")
            self._validate_frozen_scene_file(expected, declared_sha256)
            reopened_fingerprint = self._complete_scene_fingerprint(reopened_info)
            if not reopened_fingerprint:
                raise RuntimeError("SCENE_STATE_DRIFT: full Nuke scene fingerprint is unavailable")
            self._owned_scene_fingerprints[str(expected)] = reopened_fingerprint
            return reopened_info
        return None

    def repair(self, _step: Step, _spec: TaskSpec, _task_dir: Path, _failure: Exception) -> bool:
        return False


class BridgeProbeRecipe:
    identifier = "nuke.bridge_probe"

    def steps(self, _spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        return [Step("ping", "PROBE", "nuke_ping"), Step("project", "INSPECT", "get_project_settings")]


def task_service(client: NukeClient, root: Path | str | None = None) -> TaskService:
    registry = RecipeRegistry()
    registry.register(BridgeProbeRecipe())
    registry.register(RenderDeliveryRecipe())
    registry.register(ReferenceCompositeRecipe())
    store = TaskStore(Path(root) if root else manifests_dir().parent / "nuke_bridge_tasks")
    return TaskService(TaskEngine(store, NukeCommandAdapter(client), registry))
