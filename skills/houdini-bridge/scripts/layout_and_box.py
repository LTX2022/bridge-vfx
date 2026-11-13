# -*- coding: utf-8 -*-
"""节点布局 + NetworkBox 管理 -- 提取并适配自 Houdini-Agent-main hou_core.py

三策略布局: auto(NetworkEditor/layoutChildren 降级 moveToGoodPosition) / grid / columns(拓扑深度分列)
NetworkBox: 创建(6 语义色) / 添加节点 / 列出

用法(bridge exec_python 或 Python Shell):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import layout_and_box as lb
    lb.layout_nodes("/obj/RENDER", method="columns")              # 按拓扑分层布局
    lb.create_network_box("/obj/RENDER", "Sourcing", "发射源",
                          "input", ["/obj/RENDER/Fire"])           # 蓝=输入
    lb.list_network_boxes("/obj/RENDER")

hython 下布局只支持非 UI 方法(columns/grid):
    hython.exe layout_and_box.py layout /obj/RENDER columns
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

import hou

# 语义色预设
BOX_COLORS: Dict[str, Tuple[float, float, float]] = {
    "input":      (0.2, 0.4, 0.8),   # 蓝 - 数据输入
    "processing": (0.3, 0.7, 0.3),   # 绿 - 几何处理
    "deform":     (0.8, 0.6, 0.2),   # 橙 - 变形/动画
    "output":     (0.7, 0.2, 0.3),   # 红 - 输出/渲染
    "simulation": (0.6, 0.3, 0.7),   # 紫 - 物理模拟
    "utility":    (0.5, 0.5, 0.5),   # 灰 - 辅助工具
}


# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------
def _layout_grid(nodes: list, spacing: float = 1.0) -> None:
    """网格布局:按顺序排成 N 列网格"""
    if not nodes:
        return
    cols = max(1, int(math.ceil(math.sqrt(len(nodes)))))
    h_sp = 3.5 * spacing
    v_sp = 1.5 * spacing
    for idx, node in enumerate(nodes):
        col = idx % cols
        row = idx // cols
        node.setPosition(hou.Vector2(col * h_sp, -row * v_sp))


def _layout_columns(nodes: list, spacing: float = 1.0) -> None:
    """按拓扑深度分列:根节点最上,逐层向下(无 UI 依赖,hython 可用)"""
    if not nodes:
        return
    node_set = set(id(n) for n in nodes)
    depth_map: Dict[int, int] = {}

    def _depth(n) -> int:
        nid = id(n)
        if nid in depth_map:
            return depth_map[nid]
        inputs = [inp for inp in (n.inputs() or []) if inp and id(inp) in node_set]
        if not inputs:
            depth_map[nid] = 0
            return 0
        d = max(_depth(inp) for inp in inputs) + 1
        depth_map[nid] = d
        return d

    for n in nodes:
        _depth(n)

    layers: Dict[int, list] = {}
    for n in nodes:
        layers.setdefault(depth_map.get(id(n), 0), []).append(n)

    h_sp = 3.5 * spacing
    v_sp = 2.0 * spacing
    for depth in sorted(layers.keys()):
        layer_nodes = layers[depth]
        for idx, node in enumerate(layer_nodes):
            x = (idx - len(layer_nodes) / 2.0 + 0.5) * h_sp
            node.setPosition(hou.Vector2(x, -depth * v_sp))


def layout_nodes(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
    method: str = "auto",
    spacing: float = 1.0,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """多策略节点布局

    method: auto(优先 UI layoutNodes/layoutChildren,降级 moveToGoodPosition)
            / grid / columns(拓扑深度,无 UI 依赖)
    """
    parent = hou.node(parent_path) if parent_path else None
    if parent is None:
        # 尝试当前网络编辑器的 pwd(仅 GUI)
        try:
            editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                parent = editor.pwd()
        except Exception:
            pass
    if parent is None:
        parent = hou.node("/obj")
    if parent is None:
        return False, "未找到目标网络", []

    try:
        if node_paths:
            nodes = [hou.node(p) for p in node_paths if hou.node(p)]
            if not nodes:
                return False, "指定的节点路径均无效", []
        else:
            nodes = list(parent.children())
            if not nodes:
                return False, f"{parent.path()} 下没有子节点", []

        used = method
        if method == "auto":
            if node_paths:
                try:
                    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
                    if editor and hasattr(editor, "layoutNodes"):
                        editor.layoutNodes(nodes)
                        used = "NetworkEditor.layoutNodes"
                    else:
                        raise AttributeError("layoutNodes 不可用")
                except Exception:
                    for n in nodes:
                        try:
                            n.moveToGoodPosition()
                        except Exception:
                            pass
                    used = "moveToGoodPosition"
            else:
                try:
                    parent.layoutChildren(
                        horizontal_spacing=2.0 * spacing,
                        vertical_spacing=1.0 * spacing,
                    )
                    used = "layoutChildren"
                except TypeError:
                    parent.layoutChildren()
                    used = "layoutChildren(no-spacing)"
        elif method == "grid":
            _layout_grid(nodes, spacing)
        elif method == "columns":
            _layout_columns(nodes, spacing)
        else:
            return False, f"未知布局方法: {method}", []

        positions = []
        for n in nodes:
            pos = n.position()
            positions.append({
                "name": n.name(), "path": n.path(),
                "x": round(pos[0], 3), "y": round(pos[1], 3),
            })
        return True, f"已布局 {len(nodes)} 个节点(方法: {used})", positions
    except Exception as e:
        return False, f"布局失败: {e}", []


def get_node_positions(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """获取节点位置信息"""
    parent = hou.node(parent_path) if parent_path else hou.node("/obj")
    nodes = ([hou.node(p) for p in node_paths if hou.node(p)] if node_paths
             else (list(parent.children()) if parent else []))
    positions = [{
        "name": n.name(), "path": n.path(),
        "x": round(n.position()[0], 3), "y": round(n.position()[1], 3),
    } for n in nodes]
    return True, f"{len(positions)} 个节点", positions


# ---------------------------------------------------------------------------
# NetworkBox
# ---------------------------------------------------------------------------
def create_network_box(
    parent_path: str,
    name: str = "",
    comment: str = "",
    color_preset: str = "",
    node_paths: Optional[List[str]] = None,
):
    """创建 NetworkBox 并可选地把节点加入。color_preset 见 BOX_COLORS。"""
    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在", None
    try:
        box = parent.createNetworkBox(name or None)
        if comment:
            box.setComment(comment)
        if color_preset in BOX_COLORS:
            box.setColor(hou.Color(BOX_COLORS[color_preset]))
        added = []
        if node_paths:
            for np in node_paths:
                node = hou.node(np)
                if node:
                    box.addNode(node)
                    added.append(np)
            if added:
                box.fitAroundContents()
        msg = f"已创建 NetworkBox: {box.name()}"
        if comment:
            msg += f" ({comment})"
        if added:
            msg += f",包含 {len(added)} 个节点"
        return True, msg, box
    except Exception as e:
        return False, f"创建 NetworkBox 失败: {e}", None


def add_nodes_to_box(parent_path: str, box_name: str, node_paths: List[str],
                     auto_fit: bool = True) -> Tuple[bool, str]:
    """把节点加进已有 NetworkBox"""
    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在"
    target = next((b for b in parent.networkBoxes() if b.name() == box_name), None)
    if not target:
        return False, f"未找到 NetworkBox: {box_name}"
    added = []
    for np in node_paths:
        node = hou.node(np)
        if node:
            target.addNode(node)
            added.append(np)
    if auto_fit and added:
        target.fitAroundContents()
    return True, f"已将 {len(added)} 个节点添加到 {box_name}"


def list_network_boxes(parent_path: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """列出网络中所有 NetworkBox 及其内容(大网络用 box 归组查询省 token)"""
    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在", []
    boxes_info = []
    for box in parent.networkBoxes():
        nodes = box.nodes()
        boxes_info.append({
            "name": box.name(),
            "comment": box.comment() or "",
            "node_count": len(nodes),
            "nodes": [n.path() for n in nodes],
            "minimized": box.isMinimized(),
        })
    return True, f"找到 {len(boxes_info)} 个 NetworkBox", boxes_info


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "layout":
        ok, msg, pos = layout_nodes(sys.argv[2],
                                    method=sys.argv[3] if len(sys.argv) > 3 else "columns")
        print(json.dumps({"ok": ok, "message": msg, "count": len(pos)},
                         ensure_ascii=False))
    elif len(sys.argv) >= 3 and sys.argv[1] == "boxes":
        ok, msg, info = list_network_boxes(sys.argv[2])
        print(json.dumps({"ok": ok, "message": msg, "boxes": info},
                         ensure_ascii=False, indent=1))
    else:
        print(__doc__)
