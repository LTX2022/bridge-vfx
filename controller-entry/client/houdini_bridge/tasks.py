"""Task service backed by structured Houdini Bridge commands."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from urllib.parse import unquote, unquote_to_bytes, urlparse
from uuid import uuid4

from dcc_task_runtime import GateKind, GatePolicy, GateRule, RecipeRegistry, Step, TaskEngine, TaskService, TaskSpec, TaskStore
from dcc_task_runtime.canonical import canonical_sha256

from .client import BridgeError, HoudiniClient
from .paths import user_state_dir
from .recipes import ModelToKarmaRecipe, ReferenceEffectRecipe, MAX_RENDER_OPERATION_FRAMES, _frame_range_components, _frame_integer


_HOUDINI_FIRST_PARTY_ACTIONS = {
    "ping",
    "scene.info",
    "agent.model.probe",
    "agent.model.build",
    "agent.model.validate_geometry",
    "agent.model.lookdev",
    "agent.model.solaris",
    "agent.model.render_preview",
    "agent.model.verify_preview",
    "agent.model.render_final",
    "agent.model.verify_final",
    "agent.model.deliver",
    "agent.fx.probe",
    "agent.fx.build_preview",
    "agent.fx.collect_evidence",
    "agent.fx.apply_candidate",
    "agent.fx.verify",
    "agent.fx.cache",
    "agent.fx.deliver",
}
_HOUDINI_STRICT_GATE_POLICIES = {
    "ping": GatePolicy(
        "ping",
        allow_silent_operation=True,
        silent_operation_name="houdini_ping_completed",
        allowed_phases=("PROBE",),
    ),
    "scene.info": GatePolicy(
        "scene.info",
        allow_silent_operation=True,
        silent_operation_name="houdini_scene_inspected",
        allowed_phases=("INSPECT",),
    ),
    "agent.model.probe": GatePolicy(
        "agent.model.probe",
        (GateRule("houdini_running", GateKind.CAPABILITY, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("houdini_running",),),
        allowed_phases=("PROBE",),
    ),
    "agent.model.build": GatePolicy(
        "agent.model.build",
        (GateRule("editable_sop_model", GateKind.OPERATION, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("editable_sop_model",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.model.validate_geometry": GatePolicy(
        "agent.model.validate_geometry",
        (GateRule("geometry", GateKind.VERIFICATION),),
        (("geometry",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.model.lookdev": GatePolicy(
        "agent.model.lookdev",
        (GateRule("material_created", GateKind.OPERATION, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("material_created",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.model.solaris": GatePolicy(
        "agent.model.solaris",
        (GateRule("solaris_stage", GateKind.OPERATION, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("solaris_stage",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.model.render_preview": GatePolicy(
        "agent.model.render_preview",
        (GateRule("preview_rendered", GateKind.OPERATION, aliases=("preview_render_started",), legacy_kinds=(GateKind.PROGRESS.value,)),),
        (("preview_rendered",),),
        allowed_phases=("PREVIEW_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.model.verify_preview": GatePolicy(
        "agent.model.verify_preview",
        (GateRule("preview_artifacts", GateKind.VERIFICATION),),
        (("preview_artifacts",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.model.render_final": GatePolicy(
        "agent.model.render_final",
        (GateRule("final_rendered", GateKind.OPERATION, aliases=("final_render_started",), legacy_kinds=(GateKind.PROGRESS.value,)),),
        (("final_rendered",),),
        allowed_phases=("FINAL_RENDER",),
        legacy_phases=("RENDER",),
    ),
    "agent.model.verify_final": GatePolicy(
        "agent.model.verify_final",
        (GateRule("final_artifacts", GateKind.VERIFICATION),),
        (("final_artifacts",),),
        allowed_phases=("ARTIFACT_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.model.deliver": GatePolicy(
        "agent.model.deliver",
        (GateRule("delivery_ready", GateKind.VERIFICATION),),
        (("delivery_ready",),),
        allowed_phases=("DELIVER",),
    ),
    "agent.fx.probe": GatePolicy(
        "agent.fx.probe",
        (GateRule("fx_node_contract_probe", GateKind.CAPABILITY, legacy_kinds=(GateKind.VERIFICATION.value,)),),
        (("fx_node_contract_probe",),),
        allowed_phases=("PROBE",),
    ),
    "agent.fx.build_preview": GatePolicy(
        "agent.fx.build_preview",
        (
            GateRule(
                "editable_native_fx_topology",
                GateKind.OPERATION,
                legacy_kinds=("topology_scaffold", GateKind.VERIFICATION.value),
                operation_success_states=("DIAGNOSIS_INCONCLUSIVE",),
            ),
        ),
        (("editable_native_fx_topology",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.fx.collect_evidence": GatePolicy(
        "agent.fx.collect_evidence",
        (GateRule("houdini_fx_technical_evidence", GateKind.VERIFICATION),),
        (("houdini_fx_technical_evidence",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.fx.apply_candidate": GatePolicy(
        "agent.fx.apply_candidate",
        (
            GateRule(
                "candidate_patch_applied",
                GateKind.OPERATION,
                aliases=("bounded_semantic_patch",),
                legacy_kinds=(GateKind.VERIFICATION.value,),
            ),
        ),
        (("candidate_patch_applied",),),
        allowed_phases=("AUTHOR",),
        legacy_phases=("SETUP",),
    ),
    "agent.fx.verify": GatePolicy(
        "agent.fx.verify",
        (GateRule("houdini_fx_technical_evidence", GateKind.VERIFICATION),),
        (("houdini_fx_technical_evidence",),),
        allowed_phases=("TECH_VERIFY",),
        legacy_phases=("VERIFY",),
    ),
    "agent.fx.cache": GatePolicy(
        "agent.fx.cache",
        (
            GateRule("approved_simulation_cache", GateKind.VERIFICATION),
            GateRule("simulation_cache_not_applicable", GateKind.NOT_APPLICABLE),
        ),
        (("approved_simulation_cache", "simulation_cache_not_applicable"),),
        allowed_phases=("FINAL_RENDER",),
    ),
    "agent.fx.deliver": GatePolicy(
        "agent.fx.deliver",
        (GateRule("editable_fx_delivery", GateKind.VERIFICATION),),
        (("editable_fx_delivery",),),
        allowed_phases=("DELIVER",),
    ),
}


def houdini_gate_policy(action: str) -> GatePolicy:
    """Return the exact policy for one task-level first-party action.

    Low-level bridge commands are intentionally not accepted here.  Task
    execution may only cross the DCC boundary through the registered recipe
    actions whose evidence contracts are declared above.
    """

    if action not in _HOUDINI_FIRST_PARTY_ACTIONS:
        raise RuntimeError(f"unregistered Houdini action has no gate policy: {action}")
    policy = _HOUDINI_STRICT_GATE_POLICIES.get(action)
    if policy is None:
        raise RuntimeError(f"Houdini action has no exact gate policy: {action}")
    return policy


class HoudiniCommandAdapter:
    def __init__(self, client: HoudiniClient) -> None:
        self.client = client
        # A dirty HIP can be legitimate after this adapter has completed a
        # structured mutation.  Authorize only the exact task-owned node
        # fingerprint observed after that successful action.  This is an
        # in-process continuation token, not a claim that unrelated scene
        # nodes are frozen; restart/external drift therefore fails closed.
        self._trusted_scene_mutations: dict[tuple[str, str], dict[str, str]] = {}
        self._scene_non_task_baselines: dict[tuple[str, str], str] = {}
        self._scene_global_baselines: dict[tuple[str, str], str] = {}
        self._scene_external_baselines: dict[tuple[str, str], str] = {}
        self._scene_input_baselines: dict[tuple[str, str], str] = {}

    def probe(self, _spec: TaskSpec) -> dict[str, Any]:
        return self.client.call("capabilities.get")

    def execute(self, step: Step, spec: TaskSpec, task_dir: Path) -> dict[str, Any]:
        if step.gate_policy not in {"strict", "legacy_first_party"}:
            raise RuntimeError("unknown Houdini step gate policy: {}".format(step.gate_policy))
        policy = houdini_gate_policy(step.action)
        policy.validate_phase(
            step.phase,
            allow_legacy=step.gate_policy == "legacy_first_party",
        )
        operation_range = None
        if step.action in {"agent.model.render_preview", "agent.model.render_final",
                           "agent.model.verify_preview", "agent.model.verify_final"}:
            operation_range = self._render_operation_range(spec, step)
            if step.action.endswith(("render_preview", "render_final")):
                self._render_wait_seconds()
        scene_precondition = self._ensure_target_scene(spec, task_dir.name, task_dir)
        payload = {
            "task_id": task_dir.name,
            "intent": spec.intent,
            "constraints": spec.constraints,
            "render": spec.render,
            "delivery": spec.delivery,
            "target_scene": spec.target_scene,
            "target_scene_path": spec.target_scene_path,
            "inputs": list(spec.inputs),
            "step_params": dict(step.params),
        }
        if operation_range is not None:
            payload["task_frame_range"] = dict(spec.render.get("frame_range") or {})
            payload["render"] = {**spec.render, "frame_range": operation_range}
        if scene_precondition is not None:
            payload["expected_scene_fingerprints"] = scene_precondition
            payload["frozen_inputs_sha256"] = scene_precondition[
                "frozen_inputs_sha256"
            ]
        # Verification is deliberately host-side by default.  The render ROP
        # launches husk asynchronously, and asking the embedded Houdini
        # interpreter to inspect a stage immediately afterwards can contend
        # for its Python GIL while husk is shutting down.  The host already
        # has the exact output paths and can perform a deterministic file gate;
        # set DCC_BRIDGE_HOST_VERIFY=0 to use the optional in-DCC verifier.
        if step.action in {"agent.model.verify_preview", "agent.model.verify_final"} and os.environ.get("DCC_BRIDGE_HOST_VERIFY", "1") != "0":
            data = self._verify_outputs(spec, step)
        else:
            data = self.client.call(step.action, payload)
        self._wait_for_render_outputs(step, spec, data)
        if step.action == "agent.fx.cache" and bool(data.get("cache_required")):
            data = self._wait_for_fx_cache(data, payload)
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
        self._record_target_scene_mutation(spec, task_dir.name, task_dir, data)
        structured = {
            key: value
            for key, value in data.items()
            if key not in {"artifacts", "gates", "bridge_scene_fingerprints"}
        }
        result = {"artifacts": data.get("artifacts") or [], "gates": gates, "step_output": structured}
        outcome_state = policy.outcome_state(data, gates)
        if outcome_state:
            result["outcome_state"] = outcome_state
        return result

    @staticmethod
    def _scene_binding_path(task_dir: Optional[Path]) -> Optional[Path]:
        return task_dir / "houdini-scene-binding.json" if task_dir is not None else None

    @staticmethod
    def _frozen_inputs_manifest(spec: TaskSpec) -> list[dict[str, Any]]:
        """Verify every declared external input and hash its bounded manifest."""

        records: list[dict[str, Any]] = []
        if not spec.inputs:
            return records
        strict_v2 = str(spec.schema_version or "") == "2.0"
        frame_start, frame_end, frame_step, expected_count = _frame_range_components(
            spec.render.get("frame_range") or {}, "input task frame_range",
        )
        sequence_token = re.compile(r"(%0?\d*d|\$F\d*|#+)")

        def sequence_path(pattern: str, frame: int) -> str:
            token = sequence_token.search(pattern)
            if token is None:
                raise BridgeError(
                    "SCENE_STATE_DRIFT",
                    "sequence input path has no supported frame token",
                    "AWAITING_INPUT: use %04d, $F4, or #### and freeze every frame.",
                )
            placeholder = token.group(0)
            if placeholder.startswith("%"):
                try:
                    replacement = placeholder % frame
                except (TypeError, ValueError) as exc:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT", "sequence input path has an invalid percent token"
                    ) from exc
            elif placeholder.startswith("$F"):
                width = placeholder[2:]
                replacement = str(frame).zfill(int(width)) if width else str(frame)
            else:
                replacement = str(frame).zfill(len(placeholder))
            return pattern[: token.start()] + replacement + pattern[token.end() :]

        def declared_sha256(value: Any, label: str, *, required: bool) -> str:
            rendered = str(value or "").strip().lower()
            if not rendered:
                if required:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "{} has no frozen SHA-256".format(label),
                        "AWAITING_INPUT: freeze the exact manifest before continuing.",
                    )
                return ""
            if len(rendered) != 64 or any(
                character not in "0123456789abcdef" for character in rendered
            ):
                raise BridgeError(
                    "SCENE_STATE_DRIFT", "{} has an invalid SHA-256".format(label)
                )
            return rendered

        def verify(uri: str, expected: str, label: str) -> dict[str, Any]:
            supplied = declared_sha256(expected, label, required=True)
            rendered = str(uri or "").strip()
            if rendered.startswith("data:"):
                try:
                    header, encoded = rendered.split(",", 1)
                    content = (
                        base64.b64decode(encoded, validate=True)
                        if ";base64" in header
                        else unquote_to_bytes(encoded)
                    )
                except (ValueError, binascii.Error) as exc:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT", "{} data URI is invalid".format(label)
                    ) from exc
                actual = hashlib.sha256(content).hexdigest()
                identity = "data:" + header.split(":", 1)[-1].split(";", 1)[0]
                byte_count = len(content)
            else:
                parsed = urlparse(rendered)
                if parsed.scheme in {"http", "https"}:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "{} is remote and cannot be re-verified locally".format(label),
                        "AWAITING_INPUT: download and freeze the source locally.",
                    )
                candidate = Path(
                    unquote(parsed.path) if parsed.scheme == "file" else rendered
                ).expanduser()
                if candidate.is_symlink():
                    raise BridgeError(
                        "SCENE_STATE_DRIFT", "{} traverses a symlink".format(label)
                    )
                resolved = candidate.resolve()
                if not resolved.is_file():
                    raise BridgeError(
                        "SCENE_STATE_DRIFT", "{} is missing".format(label)
                    )
                digest = hashlib.sha256()
                with resolved.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                actual = digest.hexdigest()
                identity = str(resolved)
                byte_count = int(resolved.stat().st_size)
            if actual != supplied:
                raise BridgeError(
                    "SCENE_STATE_DRIFT",
                    "{} bytes changed after they were frozen".format(label),
                    "AWAITING_INPUT: restore or explicitly re-freeze the input.",
                )
            return {"identity": identity, "sha256": actual, "bytes": byte_count}

        for index, item in enumerate(spec.inputs):
            frames = item.get("frames")
            if frames is not None:
                if not isinstance(frames, (list, tuple)) or not frames:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "input {} has an incomplete sequence manifest".format(index),
                    )
                if strict_v2 and len(frames) != expected_count:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "input {} sequence does not exactly cover render.frame_range".format(index),
                        "AWAITING_INPUT: provide one ordered unique frame record for every declared render frame.",
                    )
                pattern = str(item.get("path") or item.get("uri") or "").strip()
                if sequence_token.search(pattern) is None:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "input {} sequence manifest has no supported path pattern".format(index),
                    )
                frozen_frames: list[dict[str, Any]] = []
                seen_frames: set[int] = set()
                for frame_index, frame in enumerate(frames):
                    if not isinstance(frame, dict):
                        raise BridgeError(
                            "SCENE_STATE_DRIFT",
                            "input {} has a non-object sequence frame".format(index),
                        )
                    target_frame = int(frame.get("frame", frame_index))
                    if strict_v2 and target_frame != frame_start + frame_index * frame_step:
                        raise BridgeError(
                            "SCENE_STATE_DRIFT",
                            "input {} sequence does not exactly cover render.frame_range".format(index),
                            "AWAITING_INPUT: provide one ordered unique frame record for every declared render frame.",
                        )
                    if target_frame in seen_frames:
                        raise BridgeError(
                            "SCENE_STATE_DRIFT",
                            "input {} has duplicate sequence frame {}".format(index, target_frame),
                        )
                    seen_frames.add(target_frame)
                    source_frame = int(frame.get("source_frame", target_frame))
                    supplied_path = str(frame.get("path") or frame.get("uri") or "").strip()
                    expected_path = sequence_path(pattern, source_frame)
                    verified = verify(
                        supplied_path,
                        str(frame.get("sha256") or ""),
                        "input {} frame {}".format(index, target_frame),
                    )
                    expected_identity = Path(expected_path).expanduser().resolve(strict=False)
                    if str(expected_identity) != str(verified["identity"]):
                        raise BridgeError(
                            "SCENE_STATE_DRIFT",
                            "input {} frame {} does not match its declared sequence pattern".format(
                                index, target_frame
                            ),
                        )
                    declared_bytes = frame.get("bytes", frame.get("size"))
                    if declared_bytes is not None and int(declared_bytes) != int(verified["bytes"]):
                        raise BridgeError(
                            "SCENE_STATE_DRIFT",
                            "input {} frame {} size changed after it was frozen".format(
                                index, target_frame
                            ),
                        )
                    normalized = {
                        "index": frame_index,
                        "frame": target_frame,
                        "uri": verified["identity"],
                        "sha256": verified["sha256"],
                        "bytes": verified["bytes"],
                    }
                    if source_frame != target_frame:
                        normalized["source_frame"] = source_frame
                    frozen_frames.append(normalized)
                manifest_sha256 = canonical_sha256(frozen_frames)
                declared_manifest = declared_sha256(
                    item.get("sha256"), "input {} sequence manifest".format(index), required=strict_v2
                )
                if declared_manifest and declared_manifest != manifest_sha256:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "input {} sequence manifest identity changed".format(index),
                    )
                records.append(
                    {
                        "index": index,
                        "role": str(item.get("role") or ""),
                        "pattern": pattern,
                        "declared_sha256": declared_manifest,
                        "manifest_sha256": manifest_sha256,
                        "frames": frozen_frames,
                    }
                )
                continue
            source_uri = str(item.get("path") or item.get("uri") or "")
            verified = verify(
                source_uri,
                str(item.get("sha256") or ""),
                "input {}".format(index),
            )
            declared_bytes = item.get("bytes", item.get("size"))
            if declared_bytes is not None and int(declared_bytes) != int(verified["bytes"]):
                raise BridgeError(
                    "SCENE_STATE_DRIFT", "input {} size changed after it was frozen".format(index)
                )
            suffix = Path(urlparse(source_uri).path).suffix.lower()
            time_range: Optional[dict[str, float]] = None
            if strict_v2 and suffix in {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".webm"}:
                raw_time_range = item.get("time_range")
                if isinstance(raw_time_range, dict):
                    time_start = float(raw_time_range.get("start", 0.0))
                    time_end = float(raw_time_range.get("end", time_start))
                elif isinstance(raw_time_range, (list, tuple)) and len(raw_time_range) == 2:
                    time_start, time_end = float(raw_time_range[0]), float(raw_time_range[1])
                else:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT",
                        "input {} video has no frozen time_range".format(index),
                        "AWAITING_INPUT: bind the container SHA-256 and explicit start/end time.",
                    )
                if not math.isfinite(time_start) or not math.isfinite(time_end) or time_start < 0.0 or time_end < time_start:
                    raise BridgeError(
                        "SCENE_STATE_DRIFT", "input {} video time_range is invalid".format(index)
                    )
                time_range = {"start": time_start, "end": time_end}
            records.append(
                {
                    "index": index,
                    "role": str(item.get("role") or ""),
                    **verified,
                    **({"source_uri": source_uri} if source_uri.startswith("data:") else {}),
                    **({"time_range": time_range} if time_range is not None else {}),
                }
            )
        return records

    @staticmethod
    def _frozen_inputs_sha256(spec: TaskSpec) -> str:
        return canonical_sha256(HoudiniCommandAdapter._frozen_inputs_manifest(spec))

    def _load_scene_binding(
        self,
        task_dir: Optional[Path],
        *,
        expected: Path,
        task_id: str,
        frozen_sha256: str,
    ) -> Optional[dict[str, Any]]:
        path = self._scene_binding_path(task_dir)
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "houdini.scene_binding/1.1"
            or str(payload.get("scene_path") or "") != str(expected)
            or str(payload.get("task_id") or "") != task_id
            or str(payload.get("frozen_scene_sha256") or "") != frozen_sha256
            or payload.get("full_scene_identity_verified") is not False
        ):
            return None
        task_digest = str(payload.get("bridge_task_sha256") or "")
        non_task_digest = str(payload.get("non_task_scene_sha256") or "")
        global_digest = str(payload.get("global_scene_sha256") or "")
        external_digest = str(payload.get("external_reference_sha256") or "")
        input_digest = str(payload.get("frozen_inputs_sha256") or "")
        if any(
            len(item) != 64
            for item in (
                task_digest,
                non_task_digest,
                global_digest,
                external_digest,
                input_digest,
            )
        ):
            return None
        return {
            "task": task_digest,
            "non_task": non_task_digest,
            "global": global_digest,
            "external": external_digest,
            "inputs": input_digest,
        }

    @staticmethod
    def _scene_target_binding(
        spec: TaskSpec,
        application: str,
    ) -> tuple[str, Optional[str], str, Optional[str], bool]:
        """Resolve one host binding without treating a v2.1 new scene as current.

        ``TaskSpecV2`` carries its binding behind ``scene_for``.  The pipeline
        currently lowers a v2.1 leg to the v1-compatible ``TaskSpec`` envelope,
        so the small ``constraints.bridge_scene_binding`` carrier is accepted
        as the equivalent host-scoped binding.  Older specs keep their legacy
        target fields and behavior.
        """

        constraints = getattr(spec, "constraints", {}) or {}
        if not isinstance(constraints, Mapping):
            constraints = {}
        raw_binding = constraints.get("bridge_scene_binding")
        if raw_binding is not None and not isinstance(raw_binding, Mapping):
            raise BridgeError(
                "AWAITING_INPUT",
                "constraints.bridge_scene_binding must be an object",
            )

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
                    raise BridgeError(
                        str(code),
                        f"could not resolve the {application} scene binding: {exc}",
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
                raise BridgeError(
                    "AWAITING_INPUT",
                    "scene binding contains unsupported fields: {}".format(
                        ", ".join(unknown)
                    ),
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
            raise BridgeError("AWAITING_INPUT", "scene binding has an unsupported scene_mode")
        path = str(path_value).strip() if path_value else None
        if path and mode in {"new", "untitled"}:
            raise BridgeError(
                "AWAITING_INPUT",
                "new/untitled Houdini scene binding must not contain scene_path",
            )
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
        # Legacy HTTP backends persist a route identity as
        # ``backend:port:session_id`` while the host inspection may expose
        # only its stable session UUID.  Bind the UUID to this client's port
        # before accepting that representation.
        port = str(getattr(self.client, "port", "") or "").strip()
        return bool(port and expected.endswith(f":{port}:{observed}"))

    def _guard_new_scene_target(
        self,
        spec: TaskSpec,
        *,
        task_id: Optional[str],
        instance_identity: Optional[str],
    ) -> None:
        """Read the current HIP, then fail until an isolated-scene handshake exists.

        Houdini's registered command surface has no blank-scene creation or
        ownership command.  A clean untitled HIP is still indistinguishable
        from a user's clean scene, so inspection alone cannot authorize a
        mutation.  This method deliberately performs no open/clear/save call.
        """

        scene_info_params = {
            "task_id": task_id,
            "inputs": list(getattr(spec, "inputs", ()) or ()),
        } if task_id else {"inputs": list(getattr(spec, "inputs", ()) or ())}
        info = self.client.call("scene.info", scene_info_params)
        if not isinstance(info, Mapping):
            raise BridgeError(
                "AWAITING_INPUT",
                "Houdini scene.info did not return an inspectable scene object",
            )
        dirty_state = info.get("has_unsaved_changes")
        if dirty_state is not False:
            raise BridgeError(
                "AWAITING_INPUT",
                "cannot use the current Houdini scene for a new target while its clean/dirty state is unknown or dirty",
                "Save/discard the current scene, then provide an isolated Houdini instance or scene-creation handshake.",
            )
        if info.get("scene_graph_identity_complete") is not True:
            raise BridgeError(
                "AWAITING_INPUT",
                "Houdini scene.info did not provide a complete scene fingerprint for a new target",
            )
        if instance_identity:
            observed = self._reported_scene_instance_identity(info)
            if observed is None:
                capabilities = self.client.call("capabilities.get")
                if isinstance(capabilities, Mapping):
                    observed = self._reported_scene_instance_identity(capabilities)
            if observed is None:
                raise BridgeError(
                    "AWAITING_INPUT",
                    "the requested Houdini instance identity could not be confirmed",
                )
            if not self._scene_instance_identity_matches(instance_identity, observed):
                raise BridgeError(
                    "AWAITING_INPUT",
                    "the requested Houdini instance identity does not match the inspected bridge session",
                )
        current_path = str(info.get("hip_path") or "").strip()
        if current_path:
            raise BridgeError(
                "AWAITING_INPUT",
                "the current Houdini HIP is a user scene; it cannot be claimed as a new isolated target",
            )
        raise BridgeError(
            "AWAITING_INPUT",
            "Houdini Bridge has no registered isolated blank-scene creation/ownership handshake",
            "Start a dedicated clean Houdini instance or add a host handshake that returns its session and new-scene ownership before resuming.",
        )

    def _ensure_target_scene(
        self,
        spec: TaskSpec,
        task_id: Optional[str] = None,
        task_dir: Optional[Path] = None,
    ) -> Optional[dict[str, str]]:
        """Open an explicitly frozen HIP before the first mutating action.

        Planning remains read-only.  Execution refuses to silently operate on
        whichever HIP happens to be current when ``target.scene_path`` was
        supplied by the caller.
        """

        scene_mode, target_scene_path, frozen_sha256, instance_identity, binding_declared = (
            self._scene_target_binding(spec, "houdini")
        )
        if binding_declared and scene_mode in {"new", "untitled"}:
            if target_scene_path:
                raise BridgeError(
                    "AWAITING_INPUT",
                    "new/untitled Houdini scene binding must not contain scene_path",
                )
            self._guard_new_scene_target(
                spec,
                task_id=task_id,
                instance_identity=instance_identity,
            )
            return None
        if not target_scene_path:
            return None
        expected = Path(target_scene_path).expanduser().resolve()
        if str(spec.schema_version or "") == "2.0":
            if scene_mode in {"new", "untitled"}:
                raise BridgeError(
                    "AWAITING_INPUT",
                    "a new/untitled v2 target must not be opened from target.scene_path",
                )
            if scene_mode in {"current", "existing"} and (
                len(frozen_sha256) != 64
                or any(character not in "0123456789abcdef" for character in frozen_sha256)
            ):
                raise BridgeError(
                    "AWAITING_INPUT",
                    "v2 existing/current target.scene_path requires a frozen scene SHA-256",
                )
        frozen_input_manifest = (
            self._frozen_inputs_manifest(spec) if frozen_sha256 else []
        )
        frozen_inputs_sha256 = (
            canonical_sha256(frozen_input_manifest) if frozen_sha256 else ""
        )
        binding_key = (str(expected), str(task_id or ""))
        if frozen_sha256 and task_id and binding_key not in self._trusted_scene_mutations:
            persisted = self._load_scene_binding(
                task_dir,
                expected=expected,
                task_id=task_id,
                frozen_sha256=frozen_sha256,
            )
            if persisted is not None:
                self._trusted_scene_mutations[binding_key] = persisted
                self._scene_non_task_baselines[binding_key] = persisted["non_task"]
                self._scene_global_baselines[binding_key] = persisted["global"]
                self._scene_external_baselines[binding_key] = persisted["external"]
                self._scene_input_baselines[binding_key] = persisted["inputs"]

        def disk_sha256(path: Path) -> str:
            if not path.is_file():
                raise BridgeError(
                    "SCENE_STATE_DRIFT",
                    "the frozen Houdini scene is missing: {}".format(path),
                    "AWAITING_INPUT: restore or re-freeze the exact target HIP.",
                )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()

        def fail_drift(message: str) -> None:
            raise BridgeError(
                "SCENE_STATE_DRIFT",
                message,
                "AWAITING_INPUT: save/discard the scene edits or provide a newly frozen scene.",
            )

        def complete_digest(payload: dict[str, Any], name: str) -> str:
            record = payload.get(name)
            if not isinstance(record, dict) or record.get("identity_complete") is not True:
                return ""
            digest = str(record.get("sha256") or "")
            return digest if len(digest) == 64 else ""

        def precondition(payload: dict[str, Any]) -> dict[str, Any]:
            task_record = payload.get("bridge_task_fingerprint")
            task_digest = ""
            if task_record is not None:
                task_digest = complete_digest(payload, "bridge_task_fingerprint")
                if not task_digest:
                    fail_drift("Houdini could not establish complete task scene identity")
            non_task_digest = complete_digest(payload, "non_task_scene_fingerprint")
            global_digest = complete_digest(payload, "global_scene_fingerprint")
            external_digest = complete_digest(payload, "external_reference_fingerprint")
            if (
                payload.get("scene_graph_identity_complete") is not True
                or not non_task_digest
                or not global_digest
                or not external_digest
            ):
                fail_drift("Houdini could not establish complete frozen scene identity")
            return {
                "bridge_task_sha256": task_digest,
                "non_task_scene_sha256": non_task_digest,
                "global_scene_sha256": global_digest,
                "external_reference_sha256": external_digest,
                "frozen_inputs_sha256": frozen_inputs_sha256,
                "frozen_input_manifest": frozen_input_manifest,
            }

        scene_info_params = {
            "task_id": task_id,
            "inputs": list(spec.inputs),
        } if task_id else {"inputs": list(spec.inputs)}
        info = self.client.call("scene.info", scene_info_params)
        current_raw = str(info.get("hip_path") or "")
        current = Path(current_raw).expanduser().resolve() if current_raw else None
        dirty_state = info.get("has_unsaved_changes")
        dirty = dirty_state is True
        if frozen_sha256:
            if dirty_state is not False:
                if dirty_state is not True:
                    fail_drift(
                        "Houdini did not provide an explicit clean/dirty scene readback"
                    )
                trusted = self._trusted_scene_mutations.get(binding_key)
                observed_task = complete_digest(info, "bridge_task_fingerprint")
                observed_non_task = complete_digest(info, "non_task_scene_fingerprint")
                observed_global = complete_digest(info, "global_scene_fingerprint")
                observed_external = complete_digest(info, "external_reference_fingerprint")
                if (
                    current != expected
                    or not trusted
                    or observed_task != trusted.get("task")
                    or observed_non_task != trusted.get("non_task")
                    or observed_global != trusted.get("global")
                    or observed_external != trusted.get("external")
                    or frozen_inputs_sha256 != trusted.get("inputs")
                    or info.get("scene_graph_identity_complete") is not True
                ):
                    fail_drift(
                        "the target Houdini scene has unverified unsaved changes"
                    )
            actual_disk_sha256 = disk_sha256(expected)
            if actual_disk_sha256 != frozen_sha256:
                fail_drift("the target Houdini scene bytes changed after they were frozen")
            if current == expected:
                reported_sha256 = str(info.get("hip_sha256") or "").lower()
                if reported_sha256 != actual_disk_sha256:
                    fail_drift("Houdini scene.info did not confirm the frozen scene hash")
                if not dirty:
                    non_task = complete_digest(info, "non_task_scene_fingerprint")
                    if non_task:
                        self._scene_non_task_baselines[binding_key] = non_task
                    global_digest = complete_digest(info, "global_scene_fingerprint")
                    external_digest = complete_digest(
                        info, "external_reference_fingerprint"
                    )
                    if (
                        info.get("scene_graph_identity_complete") is not True
                        or not global_digest
                        or not non_task
                        or not external_digest
                    ):
                        fail_drift(
                            "Houdini could not establish complete global scene identity"
                        )
                    self._scene_global_baselines[binding_key] = global_digest
                    self._scene_external_baselines[binding_key] = external_digest
                    self._scene_input_baselines[binding_key] = frozen_inputs_sha256
                    self._trusted_scene_mutations.pop(binding_key, None)
                return precondition(info)
        if current != expected:
            if dirty_state is not False:
                fail_drift(
                    "Houdini did not explicitly confirm the current scene is clean before open"
                )
            self.client.call(
                "scene.open_hip",
                {
                    "path": str(expected),
                    "sha256": frozen_sha256,
                },
            )
            info = self.client.call("scene.info", scene_info_params)
            reopened = Path(str(info.get("hip_path") or "")).expanduser().resolve()
            if reopened != expected:
                raise RuntimeError("Houdini did not open the exact target.scene_path")
            if frozen_sha256:
                if info.get("has_unsaved_changes") is not False:
                    fail_drift(
                        "Houdini did not explicitly confirm the reopened frozen scene is clean"
                    )
                disk_after = disk_sha256(expected)
                reported_after = str(info.get("hip_sha256") or "").lower()
                if disk_after != frozen_sha256 or reported_after != frozen_sha256:
                    fail_drift("the reopened Houdini scene failed independent frozen-hash readback")
                non_task = complete_digest(info, "non_task_scene_fingerprint")
                if non_task:
                    self._scene_non_task_baselines[binding_key] = non_task
                global_digest = complete_digest(info, "global_scene_fingerprint")
                external_digest = complete_digest(
                    info, "external_reference_fingerprint"
                )
                if (
                    info.get("scene_graph_identity_complete") is not True
                    or not global_digest
                    or not non_task
                    or not external_digest
                ):
                    fail_drift(
                        "Houdini could not establish complete global scene identity"
                    )
                self._scene_global_baselines[binding_key] = global_digest
                self._scene_external_baselines[binding_key] = external_digest
                self._scene_input_baselines[binding_key] = frozen_inputs_sha256
                self._trusted_scene_mutations.pop(binding_key, None)
                return precondition(info)
        return None

    def _record_target_scene_mutation(
        self,
        spec: TaskSpec,
        task_id: str,
        task_dir: Path,
        action_result: dict[str, Any],
    ) -> None:
        """Persist the action's atomic task/non-task post-mutation fingerprints."""

        if not spec.target_scene_path or not str(
            spec.constraints.get("frozen_scene_sha256") or ""
        ).strip():
            return
        expected = Path(spec.target_scene_path).expanduser().resolve()
        binding_key = (str(expected), task_id)
        fingerprints = action_result.get("bridge_scene_fingerprints")
        if not isinstance(fingerprints, dict):
            return
        task_record = fingerprints.get("bridge_task_fingerprint")
        non_task_record = fingerprints.get("non_task_scene_fingerprint")
        global_record = fingerprints.get("global_scene_fingerprint")
        external_record = fingerprints.get("external_reference_fingerprint")
        task_digest = str(task_record.get("sha256") or "") if isinstance(task_record, dict) else ""
        non_task_digest = str(non_task_record.get("sha256") or "") if isinstance(non_task_record, dict) else ""
        global_digest = str(global_record.get("sha256") or "") if isinstance(global_record, dict) else ""
        external_digest = str(external_record.get("sha256") or "") if isinstance(external_record, dict) else ""
        # Read-only probe actions legitimately have no task-owned nodes yet.
        # They do not authorize a dirty continuation.
        if not task_digest:
            return
        baseline = self._scene_non_task_baselines.get(binding_key)
        global_baseline = self._scene_global_baselines.get(binding_key)
        external_baseline = self._scene_external_baselines.get(binding_key)
        input_baseline = self._scene_input_baselines.get(binding_key)
        current_inputs = self._frozen_inputs_sha256(spec)
        if (
            len(task_digest) != 64
            or len(non_task_digest) != 64
            or len(global_digest) != 64
            or len(external_digest) != 64
            or not isinstance(task_record, dict)
            or task_record.get("identity_complete") is not True
            or not isinstance(non_task_record, dict)
            or non_task_record.get("identity_complete") is not True
            or not isinstance(global_record, dict)
            or global_record.get("identity_complete") is not True
            or not isinstance(external_record, dict)
            or external_record.get("identity_complete") is not True
            or not baseline
            or non_task_digest != baseline
            or not global_baseline
            or global_digest != global_baseline
            or not external_baseline
            or external_digest != external_baseline
            or not input_baseline
            or current_inputs != input_baseline
            or fingerprints.get("scene_graph_identity_complete") is not True
            or fingerprints.get("full_scene_identity_verified") is not False
        ):
            self._trusted_scene_mutations.pop(binding_key, None)
            raise BridgeError(
                "SCENE_STATE_DRIFT",
                "the structured action changed or could not identify non-task scene nodes",
                "AWAITING_INPUT: inspect external scene edits before resuming.",
            )
        binding = {
            "task": task_digest,
            "non_task": non_task_digest,
            "global": global_digest,
            "external": external_digest,
            "inputs": current_inputs,
        }
        self._trusted_scene_mutations[binding_key] = binding
        payload = {
            "schema": "houdini.scene_binding/1.1",
            "scene_path": str(expected),
            "task_id": task_id,
            "frozen_scene_sha256": str(
                spec.constraints.get("frozen_scene_sha256") or ""
            ).strip().lower(),
            "bridge_task_sha256": task_digest,
            "non_task_scene_sha256": non_task_digest,
            "global_scene_sha256": global_digest,
            "external_reference_sha256": external_digest,
            "frozen_inputs_sha256": current_inputs,
            "task_scope": str(task_record.get("scope") or ""),
            "non_task_scope": str(non_task_record.get("scope") or ""),
            "full_scene_identity_verified": False,
        }
        path = self._scene_binding_path(task_dir)
        if path is None:
            return
        temporary = path.with_name(".{}.{}.tmp".format(path.name, uuid4().hex))
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)

    @staticmethod
    def _render_operation_range(spec: TaskSpec, step: Step) -> dict[str, int]:
        """Validate a short operation inside the compact full task history."""
        full_start, full_end, full_stride, _ = _frame_range_components(
            spec.render.get("frame_range") or {}, "task frame_range",
        )
        requested = step.params.get("frame")
        segment = step.params.get("frame_range")
        if requested is not None and segment is not None:
            raise ValueError("render operation must declare frame or frame_range, not both")
        preview = step.action.endswith(("render_preview", "verify_preview"))
        if requested is not None:
            start = end = _frame_integer(requested, "render operation frame")
            stride, count = 1, 1
        elif segment is not None:
            start, end, stride, count = _frame_range_components(
                segment, "render operation frame_range", max_count=MAX_RENDER_OPERATION_FRAMES,
            )
        elif preview:
            start = end = full_start
            stride, count = 1, 1
        else:
            start, end, stride, count = _frame_range_components(
                spec.render.get("frame_range") or {}, "render operation frame_range",
                max_count=MAX_RENDER_OPERATION_FRAMES,
            )
        last = start + (count - 1) * stride
        if start < full_start or last > full_end or (start - full_start) % full_stride or (count > 1 and stride % full_stride):
            raise ValueError("render operation frames must belong to the full task frame range and stride")
        if preview and count != 1:
            raise ValueError("preview operation must request exactly one frame")
        return {"start": start, "end": last, "step": stride}

    @staticmethod
    def _render_operation_frames(spec: TaskSpec, step: Step) -> list[int]:
        bounded = HoudiniCommandAdapter._render_operation_range(spec, step)
        return list(range(bounded["start"], bounded["end"] + 1, bounded["step"]))

    @staticmethod
    def _render_wait_seconds() -> float:
        timeout = float(os.environ.get("DCC_BRIDGE_RENDER_WAIT_SECONDS", "120"))
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("render operation wait must be finite and at most 120 seconds")
        return timeout

    @staticmethod
    def _verify_outputs(spec: TaskSpec, step: Step) -> dict[str, Any]:
        render = spec.render
        output_dir = Path(os.path.expandvars(str(render.get("output_dir") or ""))).expanduser()
        frames = HoudiniCommandAdapter._render_operation_frames(spec, step)
        kind = "preview" if step.action.endswith("verify_preview") else "final"
        paths = [output_dir / f"{kind}.{frame:04d}.exr" for frame in frames]
        missing = [frame for frame, path in zip(frames, paths) if not path.is_file()]
        empty = [frame for frame, path in zip(frames, paths) if path.is_file() and path.stat().st_size <= 0]
        passed = not missing and not empty
        artifacts = [HoudiniCommandAdapter._artifact(path) for path in paths] if passed else []
        gate_name = "preview_artifacts" if kind == "preview" else "final_artifacts"
        return {
            "gates": [{"name": gate_name, "passed": passed, "kind": GateKind.VERIFICATION.value, "missing_frames": missing, "empty_frames": empty, "stale_frames": [], "host_filesystem_verified": True}],
            "artifacts": artifacts,
        }

    @staticmethod
    def _artifact(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {"path": str(path), "bytes": stat.st_size, "modified_ns": stat.st_mtime_ns}

    @staticmethod
    def _wait_for_render_outputs(step: Step, spec: TaskSpec, data: dict[str, Any]) -> None:
        """Wait outside Houdini for async ROP output before entering verify.

        Houdini's ``execute`` button starts husk asynchronously and returns to
        the UI immediately.  Advancing straight to the verify step races that
        child process.  Polling from the host adapter keeps the UI event loop
        free while making the task checkpoint honest and resumable.
        """
        pattern = str(data.get("output_pattern") or "")
        if not pattern or not step.action.endswith(("render_preview", "render_final")):
            return
        frames = HoudiniCommandAdapter._render_operation_frames(spec, step)
        if data.get("frame") is not None and (len(frames) != 1 or _frame_integer(data["frame"], "render result frame") != frames[0]):
            raise RuntimeError("render result frame does not match the bounded operation")

        def frame_path(frame: int) -> Path:
            if "$F4" in pattern:
                return Path(pattern.replace("$F4", f"{frame:04d}"))
            if "%04d" in pattern:
                return Path(pattern.replace("%04d", f"{frame:04d}"))
            if "####" in pattern:
                return Path(pattern.replace("####", f"{frame:04d}"))
            return Path(pattern)

        timeout = HoudiniCommandAdapter._render_wait_seconds()
        deadline = time.monotonic() + timeout
        before = data.get("before") or {}
        while True:
            paths = [frame_path(frame) for frame in frames]
            if all(
                path.is_file()
                and path.stat().st_size > 0
                and path.stat().st_mtime_ns > int((before.get(str(frame)) or {}).get("modified_ns") or 0)
                for frame, path in zip(frames, paths)
            ):
                return
            if time.monotonic() >= deadline:
                missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size == 0]
                raise RuntimeError("render output timeout; missing or empty frames: " + ", ".join(missing))
            time.sleep(0.25)

    def _wait_for_fx_cache(self, data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        import math
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
        nested_fx = constraints.get("fx") if isinstance(constraints.get("fx"), dict) else {}
        fx = dict(nested_fx)
        fx.update(payload.get("step_params") if isinstance(payload.get("step_params"), dict) else {})
        resource = fx.get("resource_contract") or (payload.get("fx") or {}).get("resource_contract") or {}
        timeout = float(resource.get("max_seconds") or 0)
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise RuntimeError("cache wait requires the approved resource time budget")
        deadline = time.monotonic() + timeout
        while True:
            cache = data.get("cache") if isinstance(data.get("cache"), dict) else {}
            if (data.get("cached") is True and cache.get("state") == "COMPLETE"
                    and cache.get("stop_confirmed") is True and data.get("artifacts")):
                return data
            if cache.get("state") in {"FAILED", "CANCELLED", "BUDGET_REACHED", "RECONCILE"}:
                raise RuntimeError("simulation cache requires recovery: " + str(cache.get("state")))
            if time.monotonic() >= deadline:
                operation_id = cache.get("operation_id")
                if operation_id:
                    try:
                        self.client.call("operation.cancel", {"task_id": payload["task_id"], "operation_id": operation_id})
                    except Exception:
                        pass  # A cancelled request or transport failure never proves stop.
                raise RuntimeError("simulation cache timed out; operation stop remains subject to supervisor evidence")
            time.sleep(0.25)
            data = self.client.call("agent.fx.cache_status", payload)

    def repair(self, _step: Step, _spec: TaskSpec, _task_dir: Path, _failure: Exception) -> bool:
        return False


class BridgeProbeRecipe:
    identifier = "houdini.bridge_probe"

    def steps(self, _spec: TaskSpec, _capabilities: dict[str, Any]) -> list[Step]:
        return [Step("ping", "PROBE", "ping"), Step("scene_info", "INSPECT", "scene.info")]


def task_service(client: HoudiniClient, root: Optional[Union[Path, str]] = None) -> TaskService:
    registry = RecipeRegistry()
    registry.register(BridgeProbeRecipe())
    registry.register(ModelToKarmaRecipe())
    registry.register(ReferenceEffectRecipe("houdini.reference_effect"))
    registry.register(ReferenceEffectRecipe("visual.reference_rebuild"))
    store = TaskStore(Path(root) if root else user_state_dir() / "tasks")
    return TaskService(TaskEngine(store, HoudiniCommandAdapter(client), registry))
