#!/usr/bin/env python3
"""Produce a read-only, per-domain native-basis cross-check.

The report joins the declarative domain catalog, the installed-documentation
audit, and the static HDA definition capture.  It deliberately does not
launch Houdini, inspect a live node, or treat a static operator definition as
native execution evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("21.0.631", "22.0.459")
CATEGORY_PREFIX = {"sop": "Sop", "dop": "Dop", "lop": "Lop", "vop": "Vop"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_domain_packs() -> tuple[Any, ...]:
    source = ROOT / "packages/houdini-bridge/src/houdini_bridge/domain_packs.py"
    package_root = str(source.parent.parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from houdini_bridge.domain_packs import all_domain_packs  # type: ignore

    return all_domain_packs()


def _operator_keys(node: Any) -> list[str]:
    prefix = CATEGORY_PREFIX.get(node.category)
    if prefix is None:
        return []
    return [f"{prefix}/{candidate}" for candidate in node.type_candidates]


def _port_indices(labels: Any) -> set[int]:
    indices: set[int] = set()
    if not isinstance(labels, list):
        return indices
    for item in labels:
        if isinstance(item, dict):
            try:
                if item.get("api_index") is not None:
                    indices.add(int(item["api_index"]))
            except (TypeError, ValueError):
                continue
            continue
        if isinstance(item, (list, tuple)) and item:
            try:
                # Older captures stored the one-based DialogScript label index.
                indices.add(int(item[0]) - 1)
            except (TypeError, ValueError):
                continue
    return indices


def _operator_fact(key: str, operator: dict[str, Any], aliases: list[str]) -> dict[str, Any]:
    parameters = operator.get("parameters")
    parameter_ids = set(parameters) if isinstance(parameters, dict) else set()
    return {
        "operator": key,
        "library": operator.get("library"),
        "status": operator.get("status"),
        "input_labels": operator.get("input_labels", []),
        "output_labels": operator.get("output_labels", []),
        "inputs": operator.get("inputs", []),
        "outputs": operator.get("outputs", []),
        "signatures": operator.get("signatures", []),
        "port_signature": operator.get("port_signature", {"full_node_port_arity": None, "semantics_status": "NOT_CAPTURED"}),
        "static_parameter_matches": sorted(parameter_ids.intersection(aliases)),
        "section_sha256": operator.get("section_sha256"),
    }


def _candidate_static_parameter_matches(node: Any, operators: dict[str, Any], aliases: list[str]) -> dict[str, Any]:
    expected = _operator_keys(node)
    by_candidate: dict[str, list[str]] = {}
    for key in expected:
        operator = operators.get(key, {})
        parameters = operator.get("parameters")
        ids = set(parameters) if isinstance(parameters, dict) else set()
        by_candidate[key] = sorted(set(aliases) & ids) if operator.get("status") == "CAPTURED" else []
    complete = bool(expected) and all(operators.get(key, {}).get("status") == "CAPTURED" for key in expected)
    common = set.intersection(*(set(values) for values in by_candidate.values())) if by_candidate else set()
    return {
        "matches": sorted(common) if complete else [],
        "matches_by_candidate": by_candidate,
        "all_candidates_captured": complete,
    }


def _documentation_control(domain: dict[str, Any], role: str, identifier: str) -> dict[str, Any]:
    for node in domain.get("nodes", []):
        if node.get("role") != role:
            continue
        for control in node.get("controls", []):
            if control.get("control") == identifier:
                return control
    return {}


def _documentation_node(domain: dict[str, Any], role: str) -> dict[str, Any]:
    for node in domain.get("nodes", []):
        if node.get("role") == role:
            return node
    return {}


def _domain_report(pack: Any, documentation: dict[str, Any], operators: dict[str, Any]) -> dict[str, Any]:
    node_matches: dict[str, list[str]] = {}
    nodes_by_role = {node.role: node for node in pack.nodes}
    static_nodes: list[dict[str, Any]] = []
    node_facts: list[dict[str, Any]] = []
    missing_nodes: list[dict[str, Any]] = []
    port_interface_facts: list[dict[str, Any]] = []

    for node in pack.nodes:
        matches = [key for key in _operator_keys(node) if key in operators]
        node_matches[node.role] = matches
        documented = _documentation_node(documentation, node.role)
        has_documentation = documented.get("node_fact_status") == "DOCUMENTED_NAME" or bool(documented.get("documents"))
        if not matches and not has_documentation:
            missing_nodes.append({
                "role": node.role,
                "category": node.category,
                "type_candidates": list(node.type_candidates),
                "reason": "NO_DOCUMENTED_NAME_OR_STATIC_OPERATOR_CAPTURE",
            })
        if matches:
            static_nodes.append({
                "role": node.role,
                "category": node.category,
                "type_candidates": list(node.type_candidates),
                "operators": [_operator_fact(key, operators[key], []) for key in matches],
            })
            port_interface_facts.append({
                "role": node.role,
                "operators": [{
                    "operator": key,
                    "input_labels": operators[key].get("input_labels", []),
                    "output_labels": operators[key].get("output_labels", []),
                    "inputs": operators[key].get("inputs", []),
                    "outputs": operators[key].get("outputs", []),
                    "signatures": operators[key].get("signatures", []),
                    "port_signature": operators[key].get("port_signature", {"full_node_port_arity": None, "semantics_status": "NOT_CAPTURED"}),
                    "port_semantics_status": "UNVERIFIED_STATIC_DECLARATIONS_ONLY",
                } for key in matches],
            })
        node_facts.append({
            "role": node.role,
            "category": node.category,
            "type_candidates": list(node.type_candidates),
            "documentation_status": "DOCUMENTED_NAME" if has_documentation else "NOT_CAPTURED",
            "documentation_entries": [item.get("entry") for item in documented.get("documents", [])],
            "hda_operator_status": "STATIC_OPERATOR_CAPTURED" if matches else "NO_STATIC_OPERATOR_CAPTURE",
            "operators": matches,
        })

    missing_parameters: list[dict[str, Any]] = []
    parameter_facts: list[dict[str, Any]] = []
    for control in pack.controls:
        if control.application != "houdini":
            continue
        role = control.node_role
        aliases = list(control.parameter_aliases)
        documentation_control = _documentation_control(documentation, role, control.identifier)
        documented_aliases = list(documentation_control.get("documented_aliases", []))
        static_fact = _candidate_static_parameter_matches(nodes_by_role[role], operators, aliases)
        static_aliases = set(static_fact["matches"])
        fact = {
            "control": control.identifier,
            "role": role,
            "aliases": aliases,
            "documented_aliases": sorted(set(documented_aliases)),
            "documented_aliases_by_candidate": documentation_control.get("documented_aliases_by_candidate", {}),
            "static_parameter_matches": sorted(static_aliases),
            "static_parameter_matches_by_candidate": static_fact["matches_by_candidate"],
            "all_candidate_operators_captured": static_fact["all_candidates_captured"],
            "status": "DOCUMENTED_FOR_ALL_CANDIDATES" if documented_aliases else (
                "STATIC_ONLY_FOR_ALL_CANDIDATES" if static_aliases else (
                    "CANDIDATE_SPECIFIC_ONLY" if any(static_fact["matches_by_candidate"].values()) or any(documentation_control.get("documented_aliases_by_candidate", {}).values()) else "MISSING"
                )
            ),
        }
        parameter_facts.append(fact)
        if not documented_aliases and not static_aliases:
            missing_parameters.append({
                "control": control.identifier,
                "role": role,
                "aliases": aliases,
                "reason": "NO_COMMON_DOCUMENTED_OR_STATIC_PARAMETER_ID_ACROSS_CANDIDATES",
                "documented_aliases_by_candidate": documentation_control.get("documented_aliases_by_candidate", {}),
                "static_parameter_matches_by_candidate": static_fact["matches_by_candidate"],
            })

    missing_ports: list[dict[str, Any]] = []
    for node in pack.nodes:
        matches = node_matches.get(node.role, [])
        if not matches:
            missing_ports.append({
                "kind": "node_port_signature",
                "role": node.role,
                "reason": "NO_STATIC_OPERATOR_PORT_SIGNATURE_CAPTURE",
            })
            continue
        if not any(operators[key].get("input_labels") or operators[key].get("output_labels") or operators[key].get("inputs") or operators[key].get("outputs") for key in matches):
            missing_ports.append({
                "kind": "node_port_signature",
                "role": node.role,
                "operators": matches,
                "reason": "NO_DIALOGSCRIPT_PORT_DECLARATION_CAPTURED",
            })

    declared_connections = pack.declared_connections()
    if len(pack.nodes) > 1 and not declared_connections:
        missing_ports.append({
            "kind": "domain_topology",
            "roles": [node.role for node in pack.nodes],
            "reason": "NO_EXPLICIT_DECLARED_CONNECTIONS_IN_DOMAIN_CATALOG",
        })
    connection_facts: list[dict[str, Any]] = []
    for connection in declared_connections:
        source_role = connection["source_role"]
        destination_role = connection["destination_role"]
        source_matches = node_matches.get(source_role, [])
        destination_matches = node_matches.get(destination_role, [])
        source_ports = {
            index
            for key in source_matches
            for index in _port_indices(operators[key].get("output_labels", []))
        }
        destination_ports = {
            index
            for key in destination_matches
            for index in _port_indices(operators[key].get("input_labels", []))
        }
        source_output = connection["source_output"]
        destination_input = connection["destination_input"]
        missing_reason = None
        if not source_matches or not destination_matches:
            missing_reason = "SOURCE_OR_DESTINATION_OPERATOR_CAPTURE_MISSING"
        elif source_output not in source_ports or destination_input not in destination_ports:
            missing_reason = "REQUESTED_API_INDEX_NOT_PRESENT_IN_CAPTURED_LABEL_METADATA"
        connection_facts.append({
            "connection": connection,
            "source_operators": source_matches,
            "destination_operators": destination_matches,
            "normalized_label_index_check": {
                "index_basis": "zero_based_hom_index_from_one_based_dialogscript_label",
                "source_output_label_present": source_output in source_ports,
                "destination_input_label_present": destination_input in destination_ports,
            },
            "complete_signatures_captured": False,
            "port_semantics_status": "UNVERIFIED_STATIC_LABELS_ONLY",
            "connection_execution_status": "NOT_EXECUTED",
        })
        if missing_reason:
            missing_ports.append({
                "kind": "connection_port_fact",
                "connection": connection,
                "reason": missing_reason,
            })

    unresolved = list(documentation.get("unresolved", []))
    status = "STATIC_FACTS_WITH_EXPLICIT_GAPS" if (missing_nodes or missing_parameters or missing_ports or unresolved) else "STATIC_FACTS_CAPTURED_EXECUTION_UNVERIFIED"
    return {
        "status": status,
        "documentation_status": documentation.get("status"),
        "topology_validated": bool(documentation.get("topology_validated")),
        "parameter_values_validated": bool(documentation.get("parameter_values_validated")),
        "node_count": len(pack.nodes),
        "control_count": len([control for control in pack.controls if control.application == "houdini"]),
        "declared_connections": declared_connections,
        "documentation_unresolved": unresolved,
        "node_facts": node_facts,
        "missing_node_facts": missing_nodes,
        "parameter_facts": parameter_facts,
        "missing_parameter_facts": missing_parameters,
        "static_node_facts": static_nodes,
        "port_interface_facts": port_interface_facts,
        "connection_facts": connection_facts,
        "missing_port_facts": missing_ports,
        "native_execution": False,
        "execution_evidence_status": "NOT_EXECUTED",
    }


def build_report(documentation_path: Path, capture_path: Path) -> dict[str, Any]:
    documentation = json.loads(documentation_path.read_text(encoding="utf-8"))
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    source_path = ROOT / "packages/houdini-bridge/src/houdini_bridge/domain_packs.py"
    source_sha256 = _sha256(source_path)
    packs = _load_domain_packs()
    report: dict[str, Any] = {
        "schema": "bridge.native_basis_cross_check/2.0",
        "evidence_kind": "read_only_static_cross_check",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "tool_path": str(Path(__file__).resolve()),
        "tool_sha256": _sha256(Path(__file__).resolve()),
        "scope": "join installed documentation and HDA static facts with the current domain catalog; no DCC operation was executed",
        "real_dcc_executed": False,
        "native_execution": False,
        "domain_catalog": {
            "path": str(source_path.relative_to(ROOT)),
            "sha256": source_sha256,
        },
        "documentation_audit": {
            "path": str(documentation_path.relative_to(ROOT)) if documentation_path.is_relative_to(ROOT) else str(documentation_path),
            "size_bytes": documentation_path.stat().st_size,
            "sha256": _sha256(documentation_path),
            "recorded_source_sha256": documentation.get("source_sha256"),
            "source_matches_current_catalog": documentation.get("source_sha256") == source_sha256,
            "evidence_kind": documentation.get("evidence_kind"),
            "real_dcc_executed": bool(documentation.get("real_dcc_executed")),
        },
        "hda_interface_capture": {
            "path": str(capture_path.relative_to(ROOT)) if capture_path.is_relative_to(ROOT) else str(capture_path),
            "size_bytes": capture_path.stat().st_size,
            "sha256": _sha256(capture_path),
            "evidence_kind": capture.get("evidence_kind"),
            "native_execution": bool(capture.get("native_execution")),
        },
        "versions": {},
    }
    for version in VERSIONS:
        documentation_version = documentation.get("versions", {}).get(version, {})
        capture_version = capture.get("versions", {}).get(version, {})
        operators = capture_version.get("operators", {})
        domain_docs = documentation_version.get("domains", {})
        domains = {
            pack.identifier: _domain_report(pack, domain_docs.get(pack.identifier, {}), operators)
            for pack in packs
        }
        report["versions"][version] = {
            "documentation_archive_sha256": documentation_version.get("archive_sha256"),
            "static_operator_count": len(operators),
            "static_operator_names": sorted(operators),
            "domains": domains,
        }
    report["summary"] = {
        "domain_count": len(packs),
        "required_versions": list(VERSIONS),
        "domain_status_counts": {
            status: sum(
                report["versions"][version]["domains"][pack.identifier]["status"] == status
                for version in VERSIONS
                for pack in packs
            )
            for status in ("STATIC_FACTS_WITH_EXPLICIT_GAPS", "STATIC_FACTS_CAPTURED_EXECUTION_UNVERIFIED")
        },
        "documented_node_fact_count": sum(
            node_fact["documentation_status"] == "DOCUMENTED_NAME"
            for version in VERSIONS
            for domain in report["versions"][version]["domains"].values()
            for node_fact in domain["node_facts"]
        ),
        "native_execution_verified": False,
        "focus_domains": {
            "material_lookdev_v1": "static MaterialX operator only; no native render/output receipt",
            "lighting_camera_render_v1": "Lop/usdrender_rop is documented through its redirect to out/usdrender; no exact HDA capture or native render/output receipt",
            "explosion_composite_v1": "POP network/output merge facts are unresolved; no combined native output receipt",
        },
    }
    return report


def _format_list(items: list[str], empty: str = "none") -> str:
    return "; ".join(items) if items else empty


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# P3 原生依据只读交叉审计",
        "",
        "本报告只连接当前域目录、安装版 Houdini 帮助审计和静态 HDA 定义捕获。`real_dcc_executed=false`、`native_execution=false`；静态节点/参数/端口事实不等同于真实 Houdini 执行或渲染输出验收。",
        "",
        f"- 域数：{report['summary']['domain_count']}；版本：{', '.join(report['summary']['required_versions'])}",
        f"- 当前域目录哈希：`{report['domain_catalog']['sha256']}`",
        f"- 文档审计索引与当前域目录哈希一致：`{report['documentation_audit']['source_matches_current_catalog']}`",
        f"- HDA 定义捕获：`{report['hda_interface_capture']['evidence_kind']}`；原生执行：`{report['hda_interface_capture']['native_execution']}`",
        "",
    ]
    for version in VERSIONS:
        version_data = report["versions"][version]
        lines.extend([f"## Houdini {version}", ""])
        for domain, data in version_data["domains"].items():
            missing_nodes = [
                f"{item['role']} ({'/'.join(item['type_candidates'])})"
                for item in data["missing_node_facts"]
            ]
            missing_parameters = [
                f"{item['role']}.{item['control']} aliases={','.join(item['aliases'])}"
                for item in data["missing_parameter_facts"]
            ]
            missing_ports = []
            for item in data["missing_port_facts"]:
                if item.get("kind") == "connection_port_fact":
                    connection = item["connection"]
                    missing_ports.append(
                        f"{connection['source_role']}[{connection['source_output']}] -> "
                        f"{connection['destination_role']}[{connection['destination_input']}]: {item['reason']}"
                    )
                elif item.get("kind") in ("node_port_interface", "node_port_signature"):
                    missing_ports.append(f"{item['role']}: {item['reason']}")
                else:
                    missing_ports.append(f"{item.get('kind')}: {item.get('reason')}")
            lines.extend([
                f"### `{domain}` — {data['status']}",
                "",
                f"- 文档状态：`{data['documentation_status']}`；节点 {data['node_count']}；控制 {data['control_count']}；显式连接 {len(data['declared_connections'])}。",
                f"- 缺失节点事实：{_format_list(missing_nodes)}",
                f"- 缺失参数事实：{_format_list(missing_parameters)}",
                f"- 缺失端口/拓扑事实：{_format_list(missing_ports)}",
                "- 端口标签已按 HDA 一基编号映射为 HOM 零基索引；标签不证明完整接口或连线语义，且没有真实节点图回执。",
                "",
            ])
    lines.extend([
        "## 重点阻塞",
        "",
        "- `material_lookdev_v1`：静态捕获有 `Vop/mtlxstandard_surface`，但材质控制仍缺少文档或静态参数 ID 的对应事实，且没有正式 Karma/材质渲染输出入口或输出回执。",
        "- `lighting_camera_render_v1`：安装文档将 `Lop/usdrender_rop` 重定向到 `out/usdrender`，其机器参数名可从重定向文档采集；静态 HDA 接口和正式渲染输出回执仍未取得。",
        "- `explosion_composite_v1`：`Dop/Sop` 组合中的 `popnet`、`merge` 等节点事实未完整捕获，参数/端口映射未闭合；没有组合后的原生输出回执。",
        "",
        "结论：本报告支持“原生依据未闭合”的阻塞判断，不支持“16 域真实宿主验收前准备完成”或任何真实渲染/组合完成声明。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documentation", type=Path, default=ROOT / "docs/native-basis/domain-native-documentation.json")
    parser.add_argument("--hda", type=Path, default=ROOT / "docs/native-basis/hda-interface-capture.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = build_report(args.documentation.expanduser().resolve(), args.hda.expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
