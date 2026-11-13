"""Exported strict JSON schemas for model and bridge boundaries."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping


_DRAFT = "https://json-schema.org/draft/2020-12/schema"


TASK_SPEC_V2_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/task-spec-v2.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "task_type", "intent", "target"],
        "properties": {
            "schema_version": {"const": "2.0"},
            "task_type": {"const": "visual.reference_rebuild"},
            "intent": {"type": "string", "minLength": 1},
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": ["application"],
                "properties": {
                    "application": {"const": "pipeline"},
                    "scene_mode": {"type": "string"},
                    "scene_path": {"type": ["string", "null"]},
                },
            },
            "inputs": {"type": "array", "items": {"type": "object"}},
            "references": {"type": "array", "items": {"$ref": "#/$defs/referenceAsset"}},
            "domains": {"type": "array", "items": {"$ref": "#/$defs/domainRef"}},
            "feedback": {"type": "string"},
            "constraints": {"type": "object"},
            "render": {"type": "object"},
            "delivery": {"type": "object"},
            "metadata": {"type": "object"},
            "idempotency_key": {"type": ["string", "null"]},
        },
        "$defs": {
            "referenceAsset": {
                "type": "object",
                "additionalProperties": False,
                "required": ["asset_id", "kind", "uri", "sha256"],
                "properties": {
                    "asset_id": {"type": "string", "minLength": 1},
                    "kind": {"enum": ["image", "sequence", "video", "mask", "depth", "plate"]},
                    "uri": {"type": "string", "minLength": 1},
                    "sha256": {"type": "string", "minLength": 1},
                    "color_space": {"type": "string"},
                    "frame_range": {"type": "object"},
                    "metadata": {"type": "object"},
                },
            },
            "domainRef": {
                "type": "object",
                "additionalProperties": False,
                "required": ["identifier", "version"],
                "properties": {"identifier": {"type": "string", "minLength": 1}, "version": {"type": "string", "minLength": 1}},
            },
        },
    }
)


_v21 = deepcopy(dict(TASK_SPEC_V2_SCHEMA))
_v21["$id"] = "bridge-skills://schemas/task-spec-v21.json"
_v21["properties"]["schema_version"] = {"const": "2.1"}
_scene_binding_schema = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "scene_mode": {"enum": ["current", "existing", "new", "untitled"]},
        "scene_path": {"type": ["string", "null"]},
        "frozen_scene_sha256": {"type": ["string", "null"], "pattern": "^[a-fA-F0-9]{64}$"},
        "instance_identity": {"type": ["string", "null"]},
    },
}
_v21["properties"]["target"]["properties"]["scenes"] = {
    "type": "object", "additionalProperties": False,
    "properties": {host: deepcopy(_scene_binding_schema) for host in ("houdini", "nuke")},
}
_v21["properties"]["target"]["allOf"] = [{
    "if": {"required": ["scenes"]},
    "then": {"not": {"anyOf": [{"required": ["scene_mode"]}, {"required": ["scene_path"]}]}},
}]
TASK_SPEC_V21_SCHEMA: Mapping[str, Any] = MappingProxyType(_v21)


PLANNER_ACTION_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/planner-action.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["tool", "arguments", "reason", "request_user_input"],
        "properties": {
            "tool": {"type": ["string", "null"]},
            "arguments": {"type": "object"},
            "reason": {"type": "string"},
            "request_user_input": {"type": ["string", "null"]},
        },
        "oneOf": [
            {"properties": {"tool": {"type": "string"}, "request_user_input": {"type": "null"}}},
            {"properties": {"tool": {"type": "null"}, "request_user_input": {"type": "string", "minLength": 1}}},
        ],
    }
)


VISION_ANALYSIS_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/vision-analysis.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["components", "global_observations", "confidence"],
        "properties": {
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["component_id", "label", "roi", "observations", "confidence"],
                    "properties": {
                        "component_id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "roi": {"type": ["array", "null"], "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4},
                        "observations": {"type": "object"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "global_observations": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
)


EVIDENCE_BUNDLE_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/evidence-bundle.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["task_id", "issue_id", "records", "fixed_seed", "fixed_camera_hash", "fixed_frame_range"],
        "properties": {
            "task_id": {"type": "string"},
            "issue_id": {"type": "string"},
            "records": {"type": "array", "items": {"type": "object"}},
            "fixed_seed": {"type": "integer"},
            "fixed_camera_hash": {"type": "string"},
            "fixed_frame_range": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
        },
    }
)


CANDIDATE_PATCH_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/candidate-patch.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate_id", "issue_id", "hypothesis_id", "cause_family", "changes", "affected_stage_nodes", "invalidates_components", "fixed_seed", "estimated_cost", "risk", "preview_artifact_ids"],
        "properties": {
            "candidate_id": {"type": "string"},
            "issue_id": {"type": "string"},
            "hypothesis_id": {"type": "string"},
            "cause_family": {"type": "string"},
            "changes": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "object"}},
            "affected_stage_nodes": {"type": "array", "items": {"type": "string"}},
            "invalidates_components": {"type": "array", "items": {"type": "string"}},
            "fixed_seed": {"type": "integer"},
            "estimated_cost": {"type": "string"},
            "risk": {"type": "string"},
            "preview_artifact_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
)


APPROVAL_REQUEST_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": _DRAFT,
        "$id": "bridge-skills://schemas/approval-request.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["request_id", "task_id", "scope", "subject_hash", "subject", "status", "created_at"],
        "properties": {
            "request_id": {"type": "string"},
            "task_id": {"type": "string"},
            "scope": {"enum": ["houdini_simulation_cache", "repair_experience_promotion"]},
            "subject_hash": {"type": "string"},
            "subject": {"type": "object"},
            "status": {"enum": ["PENDING", "GRANTED", "REVOKED"]},
            "created_at": {"type": "string"},
        },
    }
)


PUBLIC_JSON_SCHEMAS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "task_spec_v2": TASK_SPEC_V2_SCHEMA,
        "task_spec_v21": TASK_SPEC_V21_SCHEMA,
        "planner_action": PLANNER_ACTION_SCHEMA,
        "vision_analysis": VISION_ANALYSIS_SCHEMA,
        "evidence_bundle": EVIDENCE_BUNDLE_SCHEMA,
        "candidate_patch": CANDIDATE_PATCH_SCHEMA,
        "approval_request": APPROVAL_REQUEST_SCHEMA,
    }
)


def public_json_schema(name: str) -> dict[str, Any]:
    try:
        return deepcopy(dict(PUBLIC_JSON_SCHEMAS[name]))
    except KeyError as exc:
        raise KeyError(f"unknown public JSON schema: {name}") from exc


def all_public_json_schemas() -> dict[str, dict[str, Any]]:
    return {name: public_json_schema(name) for name in PUBLIC_JSON_SCHEMAS}
