# -*- coding: utf-8 -*-
"""参考 HIP 风险分析(纯函数集) -- 提取并适配自 Houdini_agent reference_hip_learning.py

分析别人/教程的 hip 时的四件事:
  1. 路径脱敏(redact_path):把 C:/Users/xxx/... 变 [redacted-path]...\tail,输出里不泄用户名
  2. 错误分类(classify_error):license/version/corrupt/dependency 等风险码
  3. 节点分类汇总(summarize_nodes):SOP/DOP/LOP/ROP/VOP 计数 + 带非默认参数的关键节点
  4. 外部依赖汇总(summarize_external_references):texture/abc/vdb/usd 分类计数(缺贴图先看清)

与 hip_inspect.py 配套:inspect 产出 nodes/references JSON,本模块做汇总。

用法:
    hython.exe hip_reference_risk.py summary <inspect_dump.json>
    或 import:
    import hip_reference_risk as hr
    hr.summarize_nodes(nodes) / hr.summarize_external_references(refs) / hr.redact_path(p)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

MAX_SNIPPET_LENGTH = 220
MAX_SAVED_SNIPPETS = 12
SECRET_PATH_MARKERS = ("Users\\", "Users/", "Documents\\", "Documents/",
                       "Desktop\\", "Desktop/")
SUPPORTED_HIP_SUFFIXES = {".hip", ".hiplc", ".hipnc"}


def redact_path(value: str | Path | None) -> str:
    """用户路径脱敏:含 Users/Documents/Desktop 的路径只留最后两段。"""
    text = str(value or "")
    if not text:
        return text
    normalized = text.replace("/", "\\")
    lowered = normalized.lower()
    if any(marker.lower() in lowered for marker in SECRET_PATH_MARKERS):
        parts = re.split(r"[\\/]", normalized)
        tail = "\\".join(parts[-2:]) if len(parts) >= 2 else Path(normalized).name
        return f"[redacted-path]...\\{tail}"
    return text


def compact_snippet(value: object, limit: int = MAX_SNIPPET_LENGTH) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return redact_path(text)[:limit]


def classify_error(errors: List[str], stderr: str = "") -> str | None:
    """从加载错误/stderr 里分类风险码。"""
    text = " ".join([*errors, stderr]).lower()
    if "hython.exe not found" in text or ("hython" in text and "not found" in text):
        return "missing_hython"
    if "license" in text:
        return "license_error"
    if "version" in text or "newer" in text:
        return "version_mismatch"
    if "not found" in text and "hip" in text:
        return "file_not_found"
    if "corrupt" in text or "invalid" in text or "cannot open" in text:
        return "corrupt_hip"
    if "dependency" in text or "missing" in text:
        return "dependency_missing"
    if "script" in text:
        return "script_risk_blocked"
    return None


def dependency_kind(path_value: str) -> str:
    """按后缀分类外部依赖。"""
    suffix = Path(path_value).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff"}:
        return "texture"
    if suffix == ".abc":
        return "alembic"
    if suffix == ".vdb":
        return "vdb"
    if suffix in {".usd", ".usda", ".usdc"}:
        return "usd"
    if suffix in SUPPORTED_HIP_SUFFIXES:
        return "hip_reference"
    return suffix.lstrip(".") or "external_file"


def classify_node(node: Dict[str, Any]) -> str:
    """节点按上下文/类型分类。"""
    path = str(node.get("path") or "").lower()
    node_type = str(node.get("type") or "").lower()
    if path.startswith("/stage") or "lop" in node_type:
        return "LOP"
    if path.startswith("/out") or "rop" in node_type:
        return "ROP"
    if "dop" in node_type:
        return "DOP"
    if "shop" in node_type:
        return "SHOP"
    if "vop" in node_type:
        return "VOP"
    if path.startswith("/obj") or "sop" in node_type:
        return "SOP"
    return "OTHER"


def summarize_nodes(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """节点分类计数 + 关键节点(带非默认参数/错误警告的前 24 个)。"""
    counts = {"SOP": 0, "DOP": 0, "LOP": 0, "ROP": 0, "SHOP": 0, "VOP": 0, "OTHER": 0}
    key_nodes = []
    for node in nodes:
        kind = classify_node(node)
        counts[kind] = counts.get(kind, 0) + 1
        key_parameters = list(node.get("key_parameters") or [])[:6]
        if key_parameters or node.get("errors") or node.get("warnings"):
            key_nodes.append({
                "path": node.get("path"),
                "type": node.get("type"),
                "kind": kind,
                "key_parameters": [
                    {"name": p.get("name"), "label": p.get("label"),
                     "raw_value": compact_snippet(p.get("raw_value")),
                     "eval_error": p.get("eval_error")}
                    for p in key_parameters
                ],
                "errors": node.get("errors", [])[:3],
                "warnings": node.get("warnings", [])[:3],
            })
    return {"counts": counts, "key_nodes": key_nodes[:24], "node_count": len(nodes)}


def summarize_external_references(references: List[Dict[str, Any]]) -> Dict[str, Any]:
    """外部依赖分类计数(脱敏后的路径列表,前 40 条)。"""
    counts: Dict[str, int] = {}
    items = []
    for ref in references:
        path = str(ref.get("path") or "")
        kind = dependency_kind(path)
        counts[kind] = counts.get(kind, 0) + 1
        items.append({
            "node_path": ref.get("node_path"),
            "parameter": ref.get("parameter"),
            "kind": kind,
            "path": redact_path(path),
        })
    return {"counts": counts, "items": items[:40], "total": len(references)}


def extract_safe_snippets(nodes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """提取值得学的表达式/Python 片段(hou./python/@/ch(/op: 开头特征),最多 12 条。"""
    snippets: List[Dict[str, str]] = []
    for node in nodes:
        node_path = str(node.get("path") or "")
        for parm in list(node.get("key_parameters") or [])[:8]:
            raw = compact_snippet(parm.get("raw_value"))
            if not raw:
                continue
            lowered = raw.lower()
            if any(marker in lowered for marker in ("hou.", "python", "import ", "@", "ch(", "op:")):
                snippets.append({
                    "source": node_path,
                    "parameter": str(parm.get("name") or ""),
                    "summary": raw,
                })
            if len(snippets) >= MAX_SAVED_SNIPPETS:
                return snippets
    return snippets


def full_report(inspect_dump: Dict[str, Any]) -> Dict[str, Any]:
    """对 hip_inspect.py 的 dump JSON 出完整风险报告。"""
    nodes = inspect_dump.get("nodes") or []
    refs = inspect_dump.get("external_references") or inspect_dump.get("references") or []
    report: Dict[str, Any] = {
        "node_summary": summarize_nodes(nodes),
        "dependency_summary": summarize_external_references(refs),
        "learnable_snippets": extract_safe_snippets(nodes),
    }
    err = classify_error(inspect_dump.get("errors") or [], inspect_dump.get("stderr") or "")
    if err:
        report["risk_code"] = err
    return report


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "summary":
        with open(sys.argv[2], encoding="utf-8") as f:
            dump = json.load(f)
        print(json.dumps(full_report(dump), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
