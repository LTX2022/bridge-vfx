# -*- coding: utf-8 -*-
"""写盘验证(防"假成功") -- 提取并适配自 fxhoudinimcp outputs.py

核心规则:**调用不抛异常 != 真的写了文件**。
- usdrender_rop 外壳 husk,husk 非零退出时 ROP 记 error 但 render() 正常返回
- File Cache SOP 的 pressButton() 是 fire-and-forget,写失败也不抛
- 重新渲染覆盖昨天的帧,"文件存在"不能当成功证据 -- 必须比对前后快照

用法 1(bridge exec_python / Python Shell,推荐):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import write_verdict as wv
    node = hou.node("/obj/RENDER/fire_cache_1")
    before = wv.reported_outputs(node)          # 执行前快照
    node.parm("execute").pressButton()          # 或 render() / cook()
    verdict = wv.write_verdict(node, before, action="Cache write")
    print(verdict["success"], verdict["message"])

用法 2(hython 一条龙,快照+cook+判决):
    hython.exe write_verdict.py /obj/geo1/box1 cook
    hython.exe write_verdict.py /out/usdrender_rop1 render
"""
from __future__ import annotations

import contextlib
import json
import os
from typing import Any

import hou

# 各类节点的输出路径参数名
OUTPUT_PARMS = (
    "sopoutput",
    "lopoutput",
    "picture",
    "outputimage",
    "file",
    "dopoutput",
    "copoutput",
)

# 不是文件的输出值: "__render__.usd" 是 LOP ROP 喂 husk 的内存 stage,
# ip/md 是 MPlay 目标,报缺失只会训练调用者忽略这个字段
NON_FILE_OUTPUTS = frozenset({"__render__.usd", "ip", "md"})


def reported_outputs(node: hou.Node) -> list[dict[str, Any]]:
    """节点的输出路径列表 + 磁盘上是否真有东西。"""
    found: list[dict[str, Any]] = []
    for name in OUTPUT_PARMS:
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            path = parm.eval()
        except hou.OperationFailed:
            continue
        if not path:
            # 空输出路径是最该点名的静默失败:节点跑了却没地方写
            found.append({"parm": name, "path": None, "exists": False, "empty": True})
            continue
        if path in NON_FILE_OUTPUTS:
            found.append({"parm": name, "path": path, "is_file_output": False})
            continue
        entry: dict[str, Any] = {"parm": name, "path": path}
        with contextlib.suppress(Exception):
            entry["exists"] = os.path.exists(path)
            if entry["exists"]:
                entry["size_bytes"] = os.path.getsize(path)
                entry["mtime"] = os.path.getmtime(path)
        found.append(entry)
    return found


def wrote_anything(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    """两次快照之间是否有文件输出新出现或变化。

    只有"存在"不算证据:重新渲染覆盖昨天的帧,即使什么都没跑看起来也像成功。
    """
    prior = {entry.get("path"): entry for entry in before}
    for entry in after:
        if not entry.get("exists") or entry.get("is_file_output") is False:
            continue
        was = prior.get(entry.get("path"))
        if was is None or not was.get("exists"):
            return True
        if entry.get("mtime") and was.get("mtime") and entry["mtime"] > was["mtime"]:
            return True
        if entry.get("size_bytes") != was.get("size_bytes"):
            return True
    return False


# 委托写的节点自己可能一个 error 都没有,真正干活的子节点全拿着错误,
# 所以必须有界地向内走(filecache HDA 的失败就藏在内部 /render rop_geometry 上)
_MAX_DESCENDANTS_SCANNED = 400
_MAX_MESSAGES = 12


def node_messages(node: hou.Node) -> tuple[list[str], list[str]]:
    """节点的 errors/warnings,含它委托给内部子节点的部分。"""
    errors: list[str] = []
    warnings: list[str] = []
    with contextlib.suppress(Exception):
        errors = [e.strip()[:400] for e in node.errors()]
    with contextlib.suppress(Exception):
        warnings = [w.strip()[:400] for w in node.warnings()]

    if errors:
        return errors[:_MAX_MESSAGES], warnings[:_MAX_MESSAGES]

    # 节点本身安静才向内找;有界遍历防止深 HDA 变成全场景扫描
    with contextlib.suppress(Exception):
        for index, child in enumerate(node.allSubChildren()):
            if index >= _MAX_DESCENDANTS_SCANNED:
                break
            with contextlib.suppress(Exception):
                for message in child.errors():
                    # 带上节点名:filecache 里的 "/render" 不是调用者知道该去看的地方
                    errors.append(f"{child.path()}: {message.strip()[:360]}")
                    if len(errors) >= _MAX_MESSAGES:
                        break
            if len(errors) >= _MAX_MESSAGES:
                break
    return errors[:_MAX_MESSAGES], warnings[:_MAX_MESSAGES]


def write_verdict(
    node: hou.Node,
    before: list[dict[str, Any]],
    *,
    action: str = "Render",
) -> dict[str, Any]:
    """执行刚返回的节点,报告"实际发生了什么"。

    返回 success / errors / warnings / wrote_files / outputs / message 统一结构。
    """
    errors, warnings = node_messages(node)
    after = reported_outputs(node)
    wrote = wrote_anything(before, after)
    named_a_file = any(entry.get("is_file_output") is not False for entry in after)

    verdict: dict[str, Any] = {
        "success": not errors and (wrote or not named_a_file),
        "wrote_files": wrote,
        "outputs": after,
    }
    if errors:
        verdict["errors"] = errors
        verdict["message"] = f"{action} reported {len(errors)} error(s); nothing was verified."
    elif named_a_file and not wrote:
        # 沉默不是成功:被要求写文件、没报错、什么都没产出 = 没干活
        verdict["message"] = (
            f"{action} reported no errors, but no output file appeared or changed. "
            f"Nothing was written."
        )
    elif not named_a_file:
        verdict["message"] = (
            f"{action} reported no errors. No file output was found to check, so "
            f"whether anything was written is unverified -- this is normal for a "
            f"render to MPlay."
        )
        verdict["output_verified"] = False
    else:
        verdict["message"] = f"{action} completed and wrote output."
    if warnings:
        verdict["warnings"] = warnings
    return verdict


def failure_verdict(
    node: hou.Node,
    before: list[dict[str, Any]],
    error: BaseException | str,
    *,
    action: str = "Render",
) -> dict[str, Any]:
    """执行抛异常时的同结构判决(调用者不用分支判断失败类型)。"""
    after = reported_outputs(node)
    return {
        "success": False,
        "error": str(error),
        "errors": [str(error)[:400]],
        "wrote_files": wrote_anything(before, after),
        "outputs": after,
        "message": f"{action} raised before completing; nothing was verified.",
    }


# ---------------------------------------------------------------------------
# hython 命令行一条龙:快照 -> cook/render -> 判决
# ---------------------------------------------------------------------------
def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    node = hou.node(sys.argv[1])
    if node is None:
        print(json.dumps({"success": False, "error": f"node not found: {sys.argv[1]}"}))
        sys.exit(1)
    action = sys.argv[2] if len(sys.argv) > 2 else "cook"

    before = reported_outputs(node)
    try:
        if action == "render":
            node.render()
        else:
            node.cook(force=True)
        verdict = write_verdict(node, before, action=action.capitalize())
    except Exception as exc:  # noqa: BLE001 -- 判决模块的职责就是接住一切
        verdict = failure_verdict(node, before, exc, action=action.capitalize())
    print(json.dumps(verdict, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if verdict.get("success") else 2)


if __name__ == "__main__":
    main()
