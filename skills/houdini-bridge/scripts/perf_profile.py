# -*- coding: utf-8 -*-
"""perfMon 性能分析 -- 提取并适配自 Houdini-Agent-main client.py

一条龙: startProfile -> force cook 目标节点(或整链) -> stop -> 按 cook 耗时排序报告。
定位慢节点用它;免 perfMon 的全网排名另有 analyze_cook_performance.py。

用法(bridge exec_python / Python Shell):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import perf_profile as pp
    report = pp.profile_cook("/obj/RENDER/OUT_SCENE")   # force cook 并返回耗时排名
    print(report["message"])

hython:
    hython.exe perf_profile.py /obj/RENDER/OUT_SCENE
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import hou


def profile_cook(node_path: str, title: str = "perf_profile",
                 save_hperf: str = "") -> Dict[str, Any]:
    """启动 perfMon -> force cook 节点 -> 停止 -> 返回耗时排名。

    Args:
        node_path: 要强制 cook 的节点(会 cook 整条上游链)
        title: profile 标题
        save_hperf: 可选,保存 .hperf 文件路径(Houdini 性能面板可打开)
    """
    node = hou.node(node_path)
    if node is None:
        return {"success": False, "error": f"节点不存在: {node_path}"}

    try:
        profile = hou.perfMon.startProfile(title)
    except Exception as e:
        return {"success": False, "error": f"启动 perfMon 失败: {e}"}

    cook_error = ""
    try:
        node.cook(force=True)
    except Exception as e:
        cook_error = str(e)

    try:
        profile.stop()
    except Exception:
        pass

    if save_hperf:
        try:
            profile.save(save_hperf)
        except Exception:
            pass

    # 收集 cook 事件,按耗时排序
    events: List[Dict[str, Any]] = []
    try:
        for ev in profile.events():
            try:
                # 只看节点 cook 类事件(有对象引用的)
                obj = ev.object()
                if obj is None:
                    continue
                ms = ev.time() * 1000.0
                if ms <= 0:
                    continue
                events.append({
                    "node": obj.path(),
                    "ms": round(ms, 1),
                    "count": ev.count(),
                })
            except Exception:
                continue
    except Exception:
        pass

    events.sort(key=lambda x: -x["ms"])
    top = events[:20]

    lines = [f"cook 完成: {node_path}"]
    if cook_error:
        lines.append(f"cook 报错: {cook_error}")
    lines.append(f"共 {len(events)} 个耗时节点,Top {len(top)}:")
    for ev in top:
        lines.append(f"  {ev['ms']:>10.1f} ms  x{ev['count']:<3d} {ev['node']}")
    total = sum(e["ms"] for e in events)
    if total:
        lines.append(f"合计: {total:.0f} ms")

    return {
        "success": not cook_error,
        "message": "\n".join(lines),
        "events": events,
        "total_ms": round(total, 1),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    r = profile_cook(sys.argv[1])
    print(json.dumps({"success": r.get("success"),
                      "message": r.get("message", r.get("error", ""))},
                     ensure_ascii=False, indent=1))
