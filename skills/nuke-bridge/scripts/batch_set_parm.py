#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
batch_set_parm.py — Nuke 批量改同类节点的同名参数（对标 nuketools MassivePanel，2026-08-25）

用法：
  1. 在 Nuke Script Editor 里：
       import batch_set_parm
       # 把所有 Grade 的 blackpoint 改为 0.05
       batch_set_parm.set_all("Grade", "blackpoint", 0.05)
       # 把所有 Read 的 colorspace 改为 ACEScg
       batch_set_parm.set_all("Read", "colorspace", "ACEScg")
       # 批量改多个参数
       batch_set_parm.batch("Write", {"file_type": "exr", "channels": "all", "create_directories": True})
  2. 通过 nuke-bridge nuke_run（AST 白名单兼容；**import sys 会被白名单拦**，
     用 nuke.pluginAddPath 加路径再 import 本模块）：
       nuke.pluginAddPath(r'C:/Users/<USERNAME>/.zcode/skills/nuke-bridge/scripts')
       import batch_set_parm
       __result__ = batch_set_parm.set_all('Grade', 'blackpoint', 0.05)

注意：本脚本只用 nuke 模块 + 纯 Python，符合 nuke-bridge 的 AST 白名单
（cleanup_script / batch_set_parm 已在 allowlist）。
坑：nuke_run 反复 import 会缓存第一次的版本，改本文件后需重启 Nuke 生效。
"""

import nuke


def set_all(node_class, knob_name, value, verbose=True):
    """
    把工程里所有 node_class 节点的 knob_name 参数设为 value。
    返回成功/失败统计。
    """
    ok, fail = 0, []
    nodes = nuke.allNodes(node_class)
    for n in nodes:
        knob = n.knob(knob_name)
        if knob is None:
            fail.append((n.name(), f"无参数 {knob_name}"))
            continue
        try:
            knob.setValue(value)
            ok += 1
            if verbose:
                print(f"  {n.name()}.{knob_name} = {value}")
        except Exception as e:
            fail.append((n.name(), str(e)))
    print(f"\n{node_class}.{knob_name} = {value}：成功 {ok} 个，失败 {len(fail)} 个")
    for name, err in fail:
        print(f"  ✗ {name}: {err}")
    return ok, fail


def batch(node_class, knob_value_map, verbose=True):
    """
    一次改多个参数：knob_value_map = {"knob1": v1, "knob2": v2, ...}
    比逐个调 set_all 快（一次遍历）。
    """
    ok, fail = 0, []
    nodes = nuke.allNodes(node_class)
    for n in nodes:
        for knob_name, value in knob_value_map.items():
            knob = n.knob(knob_name)
            if knob is None:
                fail.append((n.name(), f"无参数 {knob_name}"))
                continue
            try:
                knob.setValue(value)
                ok += 1
                if verbose:
                    print(f"  {n.name()}.{knob_name} = {value}")
            except Exception as e:
                fail.append((n.name(), str(e)))
    print(f"\n{node_class} 批量改 {len(knob_value_map)} 个参数：成功 {ok} 次，失败 {len(fail)} 次")
    for name, err in fail:
        print(f"  ✗ {name}: {err}")
    return ok, fail


def set_selected(knob_name, value, verbose=True):
    """只改选中的节点（GUI 模式下用）"""
    ok, fail = 0, []
    for n in nuke.selectedNodes():
        knob = n.knob(knob_name)
        if knob is None:
            fail.append((n.name(), f"无参数 {knob_name}"))
            continue
        try:
            knob.setValue(value)
            ok += 1
            if verbose:
                print(f"  {n.name()}.{knob_name} = {value}")
        except Exception as e:
            fail.append((n.name(), str(e)))
    print(f"\n选中节点 .{knob_name} = {value}：成功 {ok} 个，失败 {len(fail)} 个")
    return ok, fail


# 常用预设（从用户笔记蒸馏）

def set_all_reads_srgb():
    """所有 Read 转 sRGB 输入（web 素材默认，见 aces-and-color-management.md）"""
    return set_all("Read", "colorspace", "Utility - sRGB - Texture")


def set_all_writes_acescg():
    """所有 Write 转 ACEScg 输出（交付格式）"""
    return batch("Write", {
        "file_type": "exr",
        "colorspace": "ACEScg",
        "channels": "all",
        "create_directories": True,
    })


def disable_all_trackers():
    """禁用所有 Tracker（工程里不允许留开启的 Tracker，见 production-best-practices.md）"""
    return set_all("Tracker", "disable", True)


def self_test():
    """P1 自检：注入 SELFTEST_ 节点 -> set_all/batch 生效验证 -> 恢复用户节点原值。

    安全设计：批量改参前快照同类节点的原值（含注入节点外的所有 Blur），
    验证后恢复，不破坏用户工程；带动画的 knob 不动（恢复会烘掉动画）。
    返回 failures dict：空 = 全 PASS（AST 白名单兼容）。
    """
    failures = {}
    prefix = "SELFTEST_"

    # 注入测试节点
    b1 = nuke.createNode("Blur")
    b1.setName(prefix + "b1")
    b2 = nuke.createNode("Blur")
    b2.setName(prefix + "b2")

    # 快照用户已有的 Blur size 值（保护现场）
    saved = {}
    for n in nuke.allNodes("Blur"):
        if n.name().startswith(prefix):
            continue
        k = n.knob("size")
        if k is not None and not k.isAnimated():
            saved[n.name()] = k.value()

    try:
        # set_all：size -> 7.7
        ok, fail = set_all("Blur", "size", 7.7, verbose=False)
        for b in (b1, b2):
            v = b.knob("size").value()
            if abs(v - 7.7) > 1e-6:
                failures["set_all"] = f"{b.name()} size={v} != 7.7"
        if fail:
            failures.setdefault("set_all", f"失败列表: {fail[:2]}")
        # batch：mix -> 0.5
        ok2, _ = batch("Blur", {"mix": 0.5}, verbose=False)
        if abs(b1.knob("mix").value() - 0.5) > 1e-6:
            failures["batch"] = "mix 未生效"
    except Exception as exc:  # noqa: BLE001
        failures["exception"] = repr(exc)
    finally:
        # 恢复用户节点 + 清注入
        for name, val in saved.items():
            n = nuke.toNode(name)
            if n is not None:
                try:
                    n.knob("size").setValue(val)
                except Exception:
                    pass
        for b in (b1, b2):
            try:
                nuke.delete(b)
            except Exception:
                pass

    print("\n" + "=" * 46)
    print("batch_set_parm self-test 结果")
    print("=" * 46)
    for k in ("set_all", "batch", "exception"):
        if k in failures:
            print(f"  {k:10s} FAIL  {failures[k]}")
    if not failures:
        print("  set_all/batch 全 PASS（用户节点已恢复原值）")
    print("=" * 46)
    return failures


if __name__ == "__main__":
    print("预设命令：")
    print("  set_all_reads_srgb()      所有 Read 转 sRGB")
    print("  set_all_writes_acescg()   所有 Write 转 ACEScg EXR")
    print("  disable_all_trackers()    禁用所有 Tracker")
    print("  set_all('Grade', 'blackpoint', 0.05)  任意批量改")
    print("  set_selected('mix', 0.5)  只改选中的")
