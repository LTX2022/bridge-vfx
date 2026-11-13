# -*- coding: utf-8 -*-
"""节点快照 / 删除 / 恢复(深度撤销) -- 提取并适配自 Houdini-Agent-main node_ops.py

快照 = 完整子树递归(非默认参数+表达式+连接+标志位+内部连线),
删除前快照,误删后可完整恢复。

用法(bridge exec_python / Python Shell):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import undo_snapshot as us, json
    snap = us.snapshot("/obj/geo1/mynull")          # 快照(不删)
    ok, msg, snap = us.delete_with_snapshot("/obj/geo1/mynull")   # 删除前自动快照
    # 存盘: open("snap.json","w",encoding="utf-8").write(json.dumps(snap, ensure_ascii=False, indent=1))
    us.restore(snap)                                  # 从快照完整恢复
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

import hou


def _snapshot_node(node, _depth: int = 0) -> Optional[Dict[str, Any]]:
    """递归快照节点及其完整子树(深度上限 20 防栈溢出)。"""
    if _depth > 20:
        return None
    try:
        node_type = node.type()
        parent = node.parent()
        if not node_type or not parent:
            return None

        snapshot: Dict[str, Any] = {
            "parent_path": parent.path(),
            "node_type": node_type.name(),
            "node_name": node.name(),
            "position": [node.position()[0], node.position()[1]],
        }

        # 非默认参数(表达式优先保存)
        params = {}
        try:
            for parm in node.parms():
                try:
                    if parm.isLocked():
                        continue
                    # 只保存与默认值不同的参数,减小快照体积
                    default = parm.parmTemplate().defaultValue()
                    current = parm.eval()
                    try:
                        expr = parm.expression()
                        if expr:
                            params[parm.name()] = {"expr": expr,
                                                   "lang": str(parm.expressionLanguage())}
                            continue
                    except Exception:
                        pass
                    if isinstance(current, float) and isinstance(default, (float, int)):
                        if abs(current - float(default)) > 1e-9:
                            params[parm.name()] = current
                    elif current != default:
                        params[parm.name()] = current
                except Exception:
                    continue
        except Exception:
            pass
        snapshot["params"] = params

        # 输入/输出连接
        try:
            snapshot["input_connections"] = [
                {"input_index": i, "source_path": c.path()}
                for i, c in enumerate(node.inputs()) if c is not None
            ]
        except Exception:
            snapshot["input_connections"] = []
        try:
            snapshot["output_connections"] = [
                {"output_index": c.outputIndex(),
                 "dest_path": c.outputNode().path() if c.outputNode() else "",
                 "dest_input_index": c.inputIndex()}
                for c in node.outputConnections()
            ]
        except Exception:
            snapshot["output_connections"] = []

        # 标志位
        try:
            snapshot["display_flag"] = bool(node.isDisplayFlagSet())
            snapshot["render_flag"] = bool(node.isRenderFlagSet())
        except Exception:
            snapshot["display_flag"] = False
            snapshot["render_flag"] = False

        # 递归快照子节点
        children_snapshots = []
        children = []
        try:
            children = list(node.children())
        except Exception:
            pass
        for child in children:
            child_snap = _snapshot_node(child, _depth + 1)
            if child_snap:
                children_snapshots.append(child_snap)
        if children_snapshots:
            snapshot["children"] = children_snapshots

        # 子节点之间的内部连线(恢复时所有子建完后再接)
        internal = []
        try:
            child_paths = set(c.path() for c in children)
            for child in children:
                for i, inp in enumerate(child.inputs()):
                    if inp is not None and inp.path() in child_paths:
                        internal.append({"src_name": inp.name(),
                                         "dest_name": child.name(),
                                         "dest_input": i})
        except Exception:
            pass
        if internal:
            snapshot["internal_connections"] = internal
        return snapshot
    except Exception:
        return None


def snapshot(node_path: str) -> Optional[Dict[str, Any]]:
    """快照指定节点(不删除)。"""
    node = hou.node(node_path)
    if node is None:
        return None
    return _snapshot_node(node)


def delete_with_snapshot(node_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """删除前自动快照,返回 (ok, message, snapshot)。"""
    node = hou.node(node_path)
    if node is None:
        return False, f"未找到节点: {node_path}", None
    try:
        snap = _snapshot_node(node)
        full_path = node.path()
        parent_path = node.parent().path() if node.parent() else ""
        input_nodes = [n.path() for n in node.inputs() if n] if node.inputs() else []
        node.destroy()
        parts = [f"已删除节点: {full_path}"]
        if parent_path and hou.node(parent_path):
            parts.append(f"(父网络: {parent_path}, 剩余子节点: {len(hou.node(parent_path).children())})")
        if input_nodes:
            parts.append(f"原输入: {', '.join(input_nodes)}")
        return True, " ".join(parts), snap
    except Exception as exc:
        return False, f"删除失败: {exc}", None


def _restore_node(snap: Dict[str, Any], created: Dict[str, Any]) -> Optional[Any]:
    """按快照递归重建节点。created: name->node 映射(同一父网络内查线用)。"""
    parent = hou.node(snap["parent_path"])
    if parent is None:
        return None
    try:
        has_children = bool(snap.get("children"))
        # 容器节点用 load_contents=False:防 init 脚本抢先建默认子网,否则恢复的子节点会重复
        node = parent.createNode(
            snap["node_type"],
            snap["node_name"],
            run_init_scripts=not has_children,
            load_contents=not has_children,
        )
        node.setPosition(hou.Vector2(snap["position"][0], snap["position"][1]))
    except Exception:
        return None

    # 参数(先值后表达式)
    for pname, pval in (snap.get("params") or {}).items():
        parm = node.parm(pname)
        if parm is None:
            continue
        try:
            if isinstance(pval, dict) and "expr" in pval:
                lang = hou.exprLanguage.Python if "Python" in pval.get("lang", "") else hou.exprLanguage.Hscript
                parm.setExpression(pval["expr"], lang, replace_expression=True)
            else:
                parm.set(pval)
        except Exception:
            continue

    created[snap["node_name"]] = node

    # 子节点先建,再接内部线,再恢复子节点参数快照(递归已带参数)
    for child_snap in snap.get("children") or []:
        _restore_node(child_snap, created)
    for conn in snap.get("internal_connections") or []:
        try:
            src = created.get(conn["src_name"])
            dst = created.get(conn["dest_name"])
            if src is not None and dst is not None:
                dst.setInput(conn["dest_input"], src)
        except Exception:
            continue

    # 标志位(最后设,免得中途 display 闪)
    if snap.get("display_flag"):
        try:
            node.setDisplayFlag(True)
        except Exception:
            pass
    if snap.get("render_flag"):
        try:
            node.setRenderFlag(True)
        except Exception:
            pass
    return node


def restore(snap: Dict[str, Any]) -> Tuple[bool, str]:
    """从快照恢复节点树,并接回外部输入。"""
    if not snap:
        return False, "快照为空"
    created: Dict[str, Any] = {}
    top = _restore_node(snap, created)
    if top is None:
        return False, f"恢复失败: 无法在 {snap['parent_path']} 重建 {snap['node_type']}"

    # 接回外部输入(源节点必须已存在)
    wired = 0
    for conn in snap.get("input_connections") or []:
        try:
            src = hou.node(conn["source_path"])
            if src is not None:
                top.setInput(conn["input_index"], src)
                wired += 1
        except Exception:
            continue
    return True, f"已恢复 {top.path()}(外部输入接回 {wired} 条;子树 {len(created)} 节点)"
