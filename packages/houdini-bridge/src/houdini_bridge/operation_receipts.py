"""Bounded producer facts emitted by the Houdini addon, not acceptance verdicts."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "bridge.houdini.producer-operation/1.0"
QUERY_SCHEMA = "bridge.houdini.producer-query/2"
CHILDREN_INSPECT_POLICY = "owned-root-children/1"
QUERY_MAX_CHILDREN = 512
QUERY_MAX_RESULT_BYTES = 256 * 1024
COMMAND_KINDS = {
    "scene.create_task_root": "build",
    "node.create": "build",
    "node.create_batch": "build",
    "node.connect": "build",
    "node.set_parm": "edit",
    "node.set_parms": "edit",
    "node.children": "inspect",
    "node.info": "inspect",
    "node.parms": "inspect",
    "node.cook": "cook",
    "agent.fx.build_preview": "build",
    "scene.info": "inspect",
    "agent.fx.apply_candidate": "edit",
    "scene.save_hip": "save",
}


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def operation_receipt_sha256(record: dict[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in record.items()
                             if key != "operation_receipt_sha256"})


OFFICIAL_CAPTURE_SCHEMA = "houdini.task_scene_contract/2.2"
OFFICIAL_CAPTURE_POLICY = "official-locked-hda-definition/1"
OFFICIAL_CAPTURE_LIMITS = {"total_nodes": 512, "parameters_per_node": 1024, "max_bytes": 2 * 1024 * 1024}


def scene_capture_limits(native_scope=None):
    """认证的官方原范围和增量范围共用原上限，其他场景仍使用普通上限。"""
    if native_scope is None:
        return {"total_nodes":128,"parameters_per_node":512,"max_bytes":2*1024*1024}
    from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
    scope=NativeScope(native_scope)
    from dcc_task_runtime.rectlight_shape_scope import RESOURCE_PROFILE as RECT_SHAPE_PROFILE
    if scope.resource_profile not in (OFFICIAL_RESOURCE_PROFILE, OFFICIAL_INCREMENTAL_RESOURCE_PROFILE, RECT_SHAPE_PROFILE):
        raise ValueError("SCENE_CONTRACT_INVALID: official native scope required")
    return dict(OFFICIAL_CAPTURE_LIMITS)


def validate_scene_contract_header(contract: dict[str, Any], *, task_id: str | None = None,
                                   allow_legacy_v1: bool = False) -> str:
    """Validate a capture policy without mutating or migrating its identity.

    Definition/static identity in 2.1 does not prove internal evaluated values.
    Consumers retain their public-channel and semantic-output checks.
    """
    def require(condition: bool, field: str) -> None:
        if not condition:
            raise ValueError("SCENE_CONTRACT_INVALID: " + field)

    def sha256(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def text(value: Any) -> bool:
        return isinstance(value, str) and bool(value) and "\x00" not in value

    def path(value: Any) -> bool:
        return (text(value) and value.startswith("/") and value != "/"
                and all(part not in {"", ".", ".."} for part in value.split("/")[1:]))

    require(isinstance(contract, dict), "contract object")
    require(text(contract.get("task_id"))
            and (task_id is None or contract["task_id"] == task_id), "task identity")
    nodes = contract.get("nodes")
    require(isinstance(nodes, list) and bool(nodes), "public nodes")
    schema = contract.get("schema")
    official = schema == OFFICIAL_CAPTURE_SCHEMA
    limits = scene_capture_limits(contract.get("native_scope")) if official else scene_capture_limits()
    if official:
        require(contract.get("native_scope") is not None
                and contract.get("capture_limits") == OFFICIAL_CAPTURE_LIMITS
                and all(type(v) is int for v in contract["capture_limits"].values()), "official capture limits")
    else:
        require("native_scope" not in contract and "capture_limits" not in contract, "legacy capture limits")
    require(isinstance(schema, str), "schema")
    if schema in {"houdini.task_scene_contract/2.0", "houdini.task_scene_contract/1.0"}:
        require(schema != "houdini.task_scene_contract/1.0" or allow_legacy_v1, "legacy schema")
        require("capture_policy" not in contract and "hda_boundaries" not in contract,
                "legacy capture policy")
        return "legacy-full/2.0"
    require((schema == "houdini.task_scene_contract/2.1" and contract.get("capture_policy") == "locked-hda-definition/1")
            or (official and contract.get("capture_policy") == OFFICIAL_CAPTURE_POLICY), "schema/capture policy")
    try:
        encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("SCENE_CONTRACT_INVALID: JSON identity") from error
    require(len(encoded) <= limits["max_bytes"], "contract byte limit")
    execution_root = contract.get("execution_root")
    owned_roots = contract.get("owned_roots")
    require(path(execution_root) and isinstance(owned_roots, list) and bool(owned_roots)
            and all(path(root) for root in owned_roots)
            and len(owned_roots) == len(set(owned_roots))
            and execution_root in owned_roots, "owned execution roots")

    def owned(node_path: str) -> bool:
        return any(node_path == root or node_path.startswith(root + "/") for root in owned_roots)

    public = {}
    for node in nodes:
        require(isinstance(node, dict) and path(node.get("path")) and text(node.get("type"))
                and text(node.get("category"))
                and node["type"].startswith(node["category"] + "/"), "public node identity")
        require(owned(node["path"]), "public node outside owned roots")
        require(node["path"] not in public, "duplicate public node")
        require(isinstance(node.get("parameters"), dict)
                and len(node["parameters"]) <= limits["parameters_per_node"]
                and isinstance(node.get("parameter_channels"), dict)
                and len(node["parameter_channels"]) <= limits["parameters_per_node"]
                and isinstance(node.get("inputs"), list), "public node readback")
        public[node["path"]] = node

    def definition_identity(definition: Any) -> str:
        fields = {"type", "category", "version", "sections", "extra_file_options", "extra_info", "sha256"}
        require(isinstance(definition, dict) and set(definition) == fields, "definition fields")
        require(text(definition.get("type")) and text(definition.get("category"))
                and definition["type"].startswith(definition["category"] + "/")
                and isinstance(definition.get("version"), str)
                and isinstance(definition.get("extra_info"), str)
                and isinstance(definition.get("extra_file_options"), dict), "definition identity")
        sections = definition.get("sections")
        require(isinstance(sections, list), "definition sections")
        names = []
        for section in sections:
            require(isinstance(section, dict) and set(section) == {"name", "bytes", "sha256"}
                    and text(section.get("name")) and type(section.get("bytes")) is int
                    and section["bytes"] >= 0 and sha256(section.get("sha256")), "definition section identity")
            names.append(section["name"])
        require(names == sorted(set(names)), "definition section ordering")
        digest = definition.get("sha256")
        require(sha256(digest) and digest == canonical_sha256(
            {key: value for key, value in definition.items() if key != "sha256"}), "definition digest")
        return digest

    boundaries = contract.get("hda_boundaries")
    require(isinstance(boundaries, list) and (bool(boundaries) or official), "HDA boundaries")
    boundary_paths = []
    omitted_paths = set()
    for boundary in boundaries:
        require(isinstance(boundary, dict) and path(boundary.get("path")), "HDA boundary path")
        boundary_path = boundary["path"]
        boundary_paths.append(boundary_path)
        node = public.get(boundary_path)
        require(node is not None and boundary.get("type") == node["type"]
                and boundary.get("category") == node["category"]
                and boundary.get("is_locked_hda") is True
                and boundary.get("matches_current_definition") is True, "locked HDA identity")
        definitions = boundary.get("definitions")
        require(isinstance(definitions, list) and bool(definitions), "HDA definitions")
        digests = [definition_identity(item) for item in definitions]
        require(digests == sorted(set(digests)), "HDA definition ordering")
        by_digest = dict(zip(digests, definitions))
        definition_types = {(item["type"], item["category"]) for item in definitions}
        main = boundary.get("definition")
        main_digest = definition_identity(main)
        require(main.get("type") == node["type"] and main.get("category") == node["category"]
                and by_digest.get(main_digest) == main, "HDA active definition binding")
        internal = boundary.get("internal_nodes")
        require(isinstance(internal, list) and bool(internal)
                and type(boundary.get("internal_node_count")) is int
                and boundary["internal_node_count"] == len(internal), "HDA internal count")
        internal_paths = []
        for item in internal:
            require(isinstance(item, dict)
                    and set(item) == {"path", "type", "category", "definition_sha256"}
                    and path(item.get("path")) and item["path"].startswith(boundary_path + "/")
                    and item["path"] not in public and item["path"] not in omitted_paths
                    and text(item.get("type")) and text(item.get("category"))
                    and item["type"].startswith(item["category"] + "/"), "HDA internal identity")
            require(owned(item["path"]), "HDA internal outside owned roots")
            internal_paths.append(item["path"])
            omitted_paths.add(item["path"])
            digest = item.get("definition_sha256")
            if digest is not None:
                definition = by_digest.get(digest) if isinstance(digest, str) else None
                require(definition is not None and definition["type"] == item["type"]
                        and definition["category"] == item["category"], "HDA child definition binding")
            else:
                require((item["type"], item["category"]) not in definition_types,
                        "HDA child definition binding")
        require(internal_paths == sorted(set(internal_paths)), "HDA internal ordering")
        static = boundary.get("static_fingerprint")
        public_descendants = sum(p.startswith(boundary_path + "/") for p in public)
        require(isinstance(static, dict) and sha256(static.get("sha256"))
                and static.get("scope") == "locked-hda-internal/1"
                and static.get("identity_complete") is True and static.get("errors") == []
                and static.get("full_scene_identity_verified") is False
                and type(static.get("node_count")) is int
                and static["node_count"] == len(internal) + public_descendants,
                "HDA static identity")
    require(boundary_paths == sorted(set(boundary_paths))
            and not any(p.startswith(other + "/") for p in boundary_paths
                        for other in boundary_paths if p != other), "HDA boundary ordering/scope")
    require(len(public) <= 128 and len(public) + len(omitted_paths) <= limits["total_nodes"], "node limit")
    return OFFICIAL_CAPTURE_POLICY if official else "locked-hda-definition/1"


def validate_query_receipt(record: dict[str, Any], *, require_completed: bool = True) -> None:
    """Direct children facts only; never a mutation or full scene identity proof."""
    def require(condition, field):
        if not condition:
            raise ValueError("PRODUCER_QUERY_INVALID: " + field)

    def path(value):
        return (isinstance(value, str) and value.startswith("/obj/") and "\x00" not in value
                and all(part not in {"", ".", ".."} for part in value.split("/")[1:]))

    require(isinstance(record, dict) and record.get("schema") == QUERY_SCHEMA
            and record.get("command") == "node.children"
            and record.get("kind") == record.get("stage") == "inspect"
            and record.get("state") in {"INTENT", "COMPLETED", "FAILED"}
            and (not require_completed or record["state"] == "COMPLETED"), "schema/command/state")
    require(not any(name in record for name in ("before_scene", "after_scene", "scene_contract")),
            "query cannot carry full scene evidence")
    for name in ("task_id", "operation_id", "request_id"):
        require(isinstance(record.get(name), str) and bool(record[name]) and "\x00" not in record[name], name)
    for name in ("operation_id", "request_id"):
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", record[name]) is not None, name)
    identity = record.get("host_identity")
    require(isinstance(identity, dict) and identity.get("task_id") == record["task_id"]
            and type(identity.get("pid")) is int and identity["pid"] > 0
            and type(identity.get("scene_epoch")) is int and identity["scene_epoch"] >= 0
            and all(isinstance(identity.get(name), str) and identity[name] for name in
                    ("session_id", "launch_nonce", "process_generation", "plugin_build")), "owned host identity")
    request = record.get("request")
    require(isinstance(request, dict) and set(request) <= {
        "task_id", "operation_id", "request_id", "path", "root_path", "inspect_policy", "frozen_input_manifest"}
            and request.get("task_id") == record["task_id"]
            and request.get("operation_id") == record["operation_id"]
            and request.get("request_id", record["operation_id"]) == record["request_id"]
            and request.get("inspect_policy") == CHILDREN_INSPECT_POLICY, "exact children request")
    root, target = request.get("root_path"), request.get("path")
    require(path(root) and len(root.split("/")) == 3 and path(target)
            and (target == root or target.startswith(root + "/")), "owned query root")
    require(isinstance(record.get("frozen_input_manifest"), list)
            and record["frozen_input_manifest"] == request.get("frozen_input_manifest")
            and record.get("frozen_inputs_sha256") == canonical_sha256(record["frozen_input_manifest"])
            and record.get("request_sha256") == canonical_sha256({
                "task_id": record["task_id"], "command": record["command"],
                "request_id": record["request_id"], "request": request}), "request/input digest")
    before = record.get("before_query")
    require(isinstance(before, dict) and set(before) == {"host_identity", "lease_identity", "hip_path", "hip_sha256", "root_lease"}
            and before["host_identity"] == identity
            and isinstance(before.get("hip_path"), str) and "\x00" not in before["hip_path"]
            and (before["hip_path"].startswith("/") or (
                len(before["hip_path"]) >= 3 and before["hip_path"][0].isascii()
                and before["hip_path"][0].isalpha() and before["hip_path"][1] == ":"
                and before["hip_path"][2] in "/\\"))
            and (before.get("hip_sha256") is None or re.fullmatch(r"[0-9a-f]{64}", str(before["hip_sha256"]))),
            "native query identity")
    lease_identity=before.get('lease_identity')
    require(isinstance(lease_identity,dict)
            and all(isinstance(lease_identity.get(key),str) and lease_identity[key]
                    for key in ('session_id','process_generation'))
            and type(lease_identity.get('scene_epoch')) is int and lease_identity['scene_epoch']>=0,
            'native lease identity')
    lease = before.get("root_lease")
    require(isinstance(lease, dict) and lease.get("root") == root and lease.get("task_id") == record["task_id"]
            and lease.get("scope") == "sop" and lease.get("status") == "ACTIVE"
            and lease.get("owner_session_id") == lease_identity["session_id"]
            and lease.get("owner_generation") == lease_identity["process_generation"]
            and type(lease.get("scene_epoch")) is int and lease["scene_epoch"] == lease_identity["scene_epoch"]
            and type(lease.get("version")) is int and lease["version"] > 0, "root lease ownership")
    if record["state"] == "COMPLETED":
        require(record.get("after_query") == before, "host/epoch/HIP/lease changed")
        result = record.get("result")
        require(isinstance(result, dict) and set(result) == {"path", "nodes"}
                and result.get("path") == target and isinstance(result.get("nodes"), list)
                and len(result["nodes"]) <= QUERY_MAX_CHILDREN, "bounded children result")
        paths = []
        for child in result["nodes"]:
            require(isinstance(child, dict) and set(child) == {"path", "name", "type"}
                    and path(child.get("path")) and child["path"].rsplit("/", 1)[0] == target
                    and child.get("name") == child["path"].rsplit("/", 1)[1]
                    and isinstance(child.get("type"), str) and bool(child["type"]), "direct child identity")
            paths.append(child["path"])
        require(len(paths) == len(set(paths)) and len(json.dumps(result, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) <= QUERY_MAX_RESULT_BYTES,
                "children result bounds")
        facts = record.get("facts")
        require(isinstance(facts, dict) and set(facts) == {
            "scope", "proof_scope", "full_scene_identity_verified", "handler_result_sha256"}
                and facts.get("scope") == "inspect" and facts.get("proof_scope") == "owned_root_children"
                and facts.get("full_scene_identity_verified") is False
                and facts.get("handler_result_sha256") == canonical_sha256(result), "query facts")
    require(record.get("operation_receipt_sha256") == operation_receipt_sha256(record), "receipt digest")


def validate_operation_receipt(record: dict[str, Any], *, require_completed: bool = True) -> None:
    """Validate integrity and bindings; consumers must still verify current bytes/owner."""
    if isinstance(record, dict) and record.get("schema") == QUERY_SCHEMA:
        return validate_query_receipt(record, require_completed=require_completed)
    if (not isinstance(record, dict) or record.get("schema") != SCHEMA
            or record.get("command") not in COMMAND_KINDS
            or record.get("kind") != COMMAND_KINDS[record["command"]]
            or record.get("stage") != record.get("kind")
            or record.get("state") not in {"INTENT", "COMPLETED", "FAILED"}
            or (require_completed and record["state"] != "COMPLETED")):
        raise ValueError("PRODUCER_RECEIPT_INVALID: schema, command or state")
    for name in ("task_id", "operation_id", "request_id"):
        if not isinstance(record.get(name), str) or not record[name]:
            raise ValueError("PRODUCER_RECEIPT_INVALID: " + name)
    for name in ("operation_id", "request_id"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", record[name]):
            raise ValueError("PRODUCER_RECEIPT_INVALID: bounded " + name)
    identity = record.get("host_identity")
    if (not isinstance(identity, dict) or identity.get("task_id") != record["task_id"]
            or type(identity.get("pid")) is not int or identity["pid"] <= 0
            or type(identity.get("scene_epoch")) is not int or identity["scene_epoch"] < 0
            or any(not identity.get(name) for name in
                   ("session_id", "launch_nonce", "process_generation", "plugin_build"))):
        raise ValueError("PRODUCER_RECEIPT_INVALID: owned host identity")
    if record.get("operation_receipt_sha256") != operation_receipt_sha256(record):
        raise ValueError("PRODUCER_RECEIPT_INVALID: receipt digest")
    request = record.get("request")
    if (not isinstance(request, dict)
            or record.get("request_sha256") != canonical_sha256(
                {"task_id": record["task_id"], "command": record["command"],
                 "request_id": record["request_id"], "request": request})
            or request.get("task_id") != record["task_id"]
            or request.get("operation_id") != record["operation_id"]
            or request.get("request_id", record["operation_id"]) != record["request_id"]
            or not isinstance(record.get("frozen_input_manifest"), list)
            or record["frozen_input_manifest"] != request.get("frozen_input_manifest")
            or record.get("frozen_inputs_sha256") != canonical_sha256(record["frozen_input_manifest"])):
        raise ValueError("PRODUCER_RECEIPT_INVALID: frozen request or input digest")
    for name in ("before_scene", "after_scene"):
        if name not in record and name == "after_scene" and record["state"] != "COMPLETED":
            continue
        scene = record.get(name)
        if not isinstance(scene, dict) or scene.get("host_identity") != identity:
            raise ValueError("PRODUCER_RECEIPT_INVALID: scene identity")
        contract = scene.get("scene_contract")
        if contract is None and name == "before_scene" and record["kind"] == "build":
            continue
        validate_scene_contract_header(contract, task_id=record["task_id"])
        if scene.get("scene_contract_sha256") != canonical_sha256(contract):
            raise ValueError("PRODUCER_RECEIPT_INVALID: scene contract")
    if record["state"] == "COMPLETED":
        facts = record.get("facts")
        if (not isinstance(facts, dict) or facts.get("scope") != record["kind"]
                or not isinstance(record.get("result"), dict)
                or facts.get("handler_result_sha256") != canonical_sha256(record["result"])):
            raise ValueError("PRODUCER_RECEIPT_INVALID: handler facts")
        if record["kind"] == "save":
            saved = facts.get("saved_scene")
            if (not isinstance(saved, dict) or not saved.get("path") or not saved.get("snapshot_path")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(saved.get("sha256") or ""))
                    or saved.get("sha256") != saved.get("snapshot_sha256")
                    or saved.get("sha256") != record["after_scene"].get("hip_sha256")
                    or saved.get("path") != record["after_scene"].get("hip_path")):
                raise ValueError("PRODUCER_RECEIPT_INVALID: saved bytes")
