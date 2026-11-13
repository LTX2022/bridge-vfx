# -*- coding: utf-8 -*-
"""分析脚本统一入口 -- 让 9 个 analyze/find/trace 脚本可在 hython/bridge 一行调用

用法:
    hython.exe run_analysis.py <skill_name> <node_or_network_path> [json_kwargs]
    示例:
    hython.exe run_analysis.py analyze_normals /obj/geo1/box1 '{"tolerance": 0.002}'
    hython.exe run_analysis.py find_dead_nodes /obj/fire
    hython.exe run_analysis.py trace_dependencies /obj/RENDER/render_scen

bridge exec_python:
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import run_analysis
    r = run_analysis.invoke("analyze_normals", "/obj/geo1/box1", {"tolerance": 0.002})
    print(r)

可用 skill:
    analyze_normals          法线质量(NaN/Inf/零向量/未归一化/翻转面)
    analyze_point_attrib     点属性统计
    analyze_cook_performance 全网 cook 耗时排名(免 perfMon)
    bounding_box_info        包围盒信息
    compare_attributes       两节点属性对比
    connectivity_analysis    连通域分析
    find_attrib_references   属性引用查找(扫 VEX/表达式/字符串参数)
    find_dead_nodes          死节点查找
    trace_dependencies       依赖追踪
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import traceback

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

SKILLS = [
    "analyze_normals", "analyze_point_attrib", "analyze_cook_performance",
    "bounding_box_info", "compare_attributes", "connectivity_analysis",
    "find_attrib_references", "find_dead_nodes", "trace_dependencies",
]


def invoke(skill_name: str, node_path: str, kwargs: dict | None = None) -> dict:
    """调用一个分析 skill,返回统一结构 {ok, skill, result|error}。"""
    if skill_name not in SKILLS:
        return {"ok": False, "skill": skill_name,
                "error": f"未知 skill: {skill_name}. 可用: {', '.join(SKILLS)}"}
    try:
        mod = importlib.import_module(skill_name)
    except Exception as e:
        return {"ok": False, "skill": skill_name, "error": f"import 失败: {e}"}

    import hou  # noqa: F401 -- 分析脚本全部依赖 hou
    if hou.node(node_path) is None:
        return {"ok": False, "skill": skill_name,
                "error": f"节点不存在: {node_path}"}

    fn = getattr(mod, "run", None)
    if fn is None:
        return {"ok": False, "skill": skill_name, "error": "模块缺少 run() 入口"}

    try:
        result = fn(node_path, **(kwargs or {}))
        return {"ok": True, "skill": skill_name, "node": node_path, "result": result}
    except TypeError as e:
        # 参数名不匹配:提示该 skill 的合法参数
        params = (mod.SKILL_INFO.get("parameters", {})
                  if hasattr(mod, "SKILL_INFO") else {})
        return {"ok": False, "skill": skill_name,
                "error": f"参数错误: {e}. 合法参数: {json.dumps(params, ensure_ascii=False)}"}
    except Exception as e:
        return {"ok": False, "skill": skill_name, "error": f"{e}",
                "traceback": traceback.format_exc()[-800:]}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    kw = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    out = invoke(sys.argv[1], sys.argv[2], kw)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if out.get("ok") else 2)
