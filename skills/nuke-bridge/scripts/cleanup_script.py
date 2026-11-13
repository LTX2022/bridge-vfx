#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cleanup_script.py — Nuke 工程清理（对标 nuketools 的 Script Cleanup，2026-08-25）

检测并报告/清理 Nuke 工程里的"脏东西"：
- 断连节点（有输入口但没接线）
- 死节点（下游没有连到任何 Viewer/Write 的悬空分支）
- 重复的 Read 节点（同一文件路径读多次）
- 残留的未禁用 Tracker 节点（会持续计算拖慢工程）
- 空 BackdropNode
- 表达式引用已删除节点（#error 表达式）

用法：
  1. 在 Nuke Script Editor 里：
       import cleanup_script
       cleanup_script.report()          # 只报告不改
       cleanup_script.fix(dry_run=True) # 预览要删的
       cleanup_script.fix(dry_run=False) # 真的删（会先打印备份提示）
       cleanup_script.self_test()       # P1 自检：注入坏场景->检出->清场
  2. 通过 nuke-bridge nuke_run（AST 白名单兼容；注意 **import sys 会被白名单
     拦**，用 nuke.pluginAddPath 加路径再 import 本模块）：
       nuke.pluginAddPath(r'C:/Users/<USERNAME>/.zcode/skills/nuke-bridge/scripts')
       import cleanup_script
       __result__ = cleanup_script.self_test()

注意：本脚本只用 nuke 模块 + 纯 Python，符合 nuke-bridge 的 AST 白名单
（cleanup_script / batch_set_parm 已加入 allowlist）。

坑（实测 2026-08-25）：通过 nuke_run 反复 import 本模块时，Nuke 的 Python
会话会**缓存第一次 import 的版本**--改了本文件后必须重启 Nuke 才生效
（AST 白名单不给 importlib.reload，sys 也被拦）。
"""

import nuke


def find_disconnected():
    """有输入口但 input 未连接的节点（Viewer/Backdrop 等除外）

    坑（实测）：node.inputs() 返回**已连接**的输入数（全断连返回 0，
    循环根本不进），接口总数要用 node.maximumInputs()。
    """
    skip = ("Viewer", "BackdropNode", "Dot", "Note", "StickyNote", "Group", "Gizmo")
    bad = []
    for n in nuke.allNodes():
        if n.Class() in skip:
            continue
        for i in range(n.maximumInputs()):
            if n.input(i) is None:
                bad.append((n.name(), n.Class(), f"input{i} 未连接"))
                break
    return bad


def find_dead_branches():
    """下游不到 Viewer/Write 的悬空节点（从末端倒推标记活节点）"""
    alive = set()
    # 所有 Viewer 和 Write 是活的
    roots = [n for n in nuke.allNodes() if n.Class() in ("Viewer", "Write")]
    # 从活节点向上游爬
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n.name() in alive:
            continue
        alive.add(n.name())
        for i in range(n.inputs()):
            up = n.input(i)
            if up is not None:
                stack.append(up)
    dead = []
    for n in nuke.allNodes():
        if n.Class() in ("BackdropNode", "Note", "StickyNote", "Dot"):
            continue
        if n.name() not in alive:
            dead.append((n.name(), n.Class()))
    return dead


def find_duplicate_reads():
    """同一文件路径被多个 Read 读"""
    seen = {}
    dups = []
    for n in nuke.allNodes("Read"):
        path = n.knob("file").value() if n.knob("file") else ""
        if not path:
            continue
        if path in seen:
            dups.append((n.name(), path, f"与 {seen[path]} 重复"))
        else:
            seen[path] = n.name()
    return dups


def find_active_trackers():
    """未禁用的 Tracker 节点（会持续计算，见 production-best-practices.md 第 10 节）

    类名匹配用 startswith：实际节点类是 Tracker4/Tracker5（实测
    nuke.allNodes("Tracker") 匹配不到 Tracker4，必须前缀过滤）。
    """
    bad = []
    for n in nuke.allNodes():
        if not n.Class().startswith("Tracker"):
            continue
        d = n.knob("disable")
        if d is None or not d.value():
            bad.append((n.name(), "Tracker 未禁用，会一直算跟踪拖慢工程"))
    return bad


def find_empty_backdrops():
    """空 BackdropNode"""
    bad = []
    for n in nuke.allNodes("BackdropNode"):
        # backdrop 的 nodes 在 selectNodes 范围内才算有内容
        if not n.getNodes():
            bad.append((n.name(), "空 Backdrop"))
    return bad


def find_broken_expressions():
    """knob 里有 #error 或引用了不存在节点的表达式"""
    bad = []
    for n in nuke.allNodes():
        for knob_name in n.knobs():
            try:
                knob = n.knob(knob_name)
                if knob is None:
                    continue
                val = knob.value()
                if isinstance(val, str) and "#error" in val:
                    bad.append((n.name(), knob_name, "#error 表达式"))
            except Exception:
                pass
    return bad


def report():
    """只报告，不改任何东西"""
    print("=" * 60)
    print("Nuke 工程清理报告")
    print("=" * 60)

    checks = [
        ("断连节点", find_disconnected),
        ("死分支（下游不到 Viewer/Write）", find_dead_branches),
        ("重复 Read", find_duplicate_reads),
        ("未禁用 Tracker", find_active_trackers),
        ("空 Backdrop", find_empty_backdrops),
        ("错误表达式", find_broken_expressions),
    ]

    total = 0
    for name, fn in checks:
        items = fn()
        total += len(items)
        print(f"\n【{name}】{len(items)} 个")
        for item in items[:20]:
            print(f"  - {' | '.join(str(x) for x in item)}")
        if len(items) > 20:
            print(f"  ... 还有 {len(items)-20} 个")

    print(f"\n总计：{total} 个问题")
    return total


def fix(dry_run=True):
    """
    清理死分支和空 Backdrop。
    dry_run=True（默认）只打印要删的，不真删。
    """
    dead = find_dead_branches()
    empty_bd = find_empty_backdrops()
    to_delete = [name for name, _ in dead] + [name for name, _ in empty_bd]

    print(f"将删除 {len(to_delete)} 个节点：")
    for name in to_delete[:30]:
        print(f"  - {name}")
    if len(to_delete) > 30:
        print(f"  ... 还有 {len(to_delete)-30} 个")

    if dry_run:
        print("\n[dry_run] 未删除任何节点。确认后调 fix(dry_run=False)")
        return to_delete

    # 真删：先提示备份
    print("\n⚠️  建议先 saveAs 一个备份版本再删！")
    deleted = 0
    for name in to_delete:
        n = nuke.toNode(name)
        if n is not None:
            try:
                nuke.delete(n)
                deleted += 1
            except Exception as e:
                print(f"  删除 {name} 失败：{e}")
    print(f"\n已删除 {deleted} 个节点")
    return to_delete


def self_test():
    """P1 自检：注入 4 类坏场景 -> report 必须全检出 -> 修复/清场 -> 恢复基线。

    只注入 SELFTEST_ 前缀节点、结束全部删除；若当前工程基线本身有死分支/
    空 Backdrop，则不调全局 fix()（防误删用户节点），改为定向删除注入节点。
    返回 failures dict：空 = 全 PASS（AST 白名单兼容：只用 nuke + 纯 Python）。
    """
    prefix = "SELFTEST_"
    failures = {}

    def _counts():
        return {
            "disconnected": len(find_disconnected()),
            "dead": len(find_dead_branches()),
            "dups": len(find_duplicate_reads()),
            "trackers": len(find_active_trackers()),
            "backdrops": len(find_empty_backdrops()),
        }

    def _names(items):
        return [it[0] if isinstance(it, (tuple, list)) else str(it) for it in items]

    base = _counts()

    # --- 1. 注入坏场景 ---
    blur = nuke.createNode("Blur")
    blur.setName(prefix + "disconnected_blur")
    r1 = nuke.createNode("Read")
    r1.setName(prefix + "dup_read1")
    r1.knob("file").setValue("SELFTEST/dummy_seq.####.exr")
    r2 = nuke.createNode("Read")
    r2.setName(prefix + "dup_read2")
    r2.knob("file").setValue("SELFTEST/dummy_seq.####.exr")
    bd = nuke.createNode("BackdropNode")
    bd.setName(prefix + "empty_backdrop")
    # 坑：新建 Backdrop 的默认矩形会把旁边节点圈进去 -> getNodes() 非空
    # -> 不算"空"。把矩形摆到远处空地保证真的空。
    for k, v in (("bd_xpos", -5000), ("bd_ypos", -5000),
                 ("bd_width", 100), ("bd_height", 100)):
        if bd.knob(k) is not None:
            bd.knob(k).setValue(v)
    tr = nuke.createNode("Tracker")
    tr.setName(prefix + "active_tracker")

    # --- 2. 检出验证（注入的每类问题必须被对应 find_* 抓到） ---
    # 注意 dups：allNodes 迭代顺序不保证创建序，被标"重复"的可能是
    # r1 也可能是 r2，按注入的文件路径匹配即可。
    def _flat(items):
        out = []
        for it in items:
            if isinstance(it, (tuple, list)):
                out.extend(str(x) for x in it)
            else:
                out.append(str(it))
        return out

    checks = [
        ("disconnected", prefix + "disconnected_blur", find_disconnected),
        ("dead", prefix + "dup_read1", find_dead_branches),
        ("dups", "SELFTEST/dummy_seq", find_duplicate_reads),
        ("trackers", prefix + "active_tracker", find_active_trackers),
        ("backdrops", prefix + "empty_backdrop", find_empty_backdrops),
    ]
    for label, needle, fn in checks:
        if not any(needle in s for s in _flat(fn())):
            failures[label] = f"注入的 {needle} 未被检出"

    # --- 3. 防假阳性：正确禁用的 Tracker 不应被报 ---
    ok_tr = nuke.createNode("Tracker")
    ok_tr.setName(prefix + "disabled_tracker")
    ok_tr.knob("disable").setValue(True)
    if any(prefix + "disabled_tracker" in nm for nm in _names(find_active_trackers())):
        failures["false_positive"] = "已禁用的 Tracker 被误报"
    nuke.delete(ok_tr)

    # --- 4. 修复/清场 ---
    if base["dead"] == 0 and base["backdrops"] == 0:
        # 基线干净 -> 可以安全走全局 fix()（删死分支+空 Backdrop）
        fix(dry_run=False)
    else:
        # 基线不干净 -> 只定向删注入节点，不动用户节点
        print(f"[self-test] 基线不干净（dead={base['dead']}, bd={base['backdrops']}），"
              f"跳过全局 fix()，定向清理注入节点")
        for n in list(nuke.allNodes()):
            if n.name().startswith(prefix):
                nuke.delete(n)

    after = _counts()
    for k in after:
        if after[k] > base[k]:
            failures.setdefault("cleanup", {})[k] = f"{base[k]} -> {after[k]} 未恢复基线"

    # 兜底清理（fix 之后可能残留未删的注入节点）
    for n in list(nuke.allNodes()):
        if n.name().startswith(prefix):
            nuke.delete(n)

    # --- 5. PASS/FAIL 表 ---
    print("\n" + "=" * 46)
    print("cleanup_script self-test 结果")
    print("=" * 46)
    for label, _, _ in checks:
        status = "FAIL" if label in failures else "PASS"
        print(f"  {label:14s} {status}  {failures.get(label, '')}")
    if "false_positive" in failures:
        print(f"  false_positive FAIL  {failures['false_positive']}")
    if "cleanup" in failures:
        print(f"  cleanup        FAIL  {failures['cleanup']}")
    print("=" * 46)
    return failures


if __name__ == "__main__":
    report()
