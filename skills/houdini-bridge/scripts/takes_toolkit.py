#!/usr/bin/env hython
# -*- coding: utf-8 -*-
"""
takes_toolkit.py - Take（方案变体）工具（P3，对标 fxhoudinimcp 4 工具，2026-08-25）

H21.0.631 实测 API（hom.zip 核对）：
- 建删：hscript `takeadd <名>` / `takerm <名>`（hou.takes 无直接 create）
- 列举/查找/切换：hou.takes.takes() / findTake(name) / setCurrentTake(take)
- 参数进 take：take.addParmTuple(node.parmTuple(parm_name))
  （在 take 为 current 时改参数值，值就记录进该 take）

用法：hython takes_toolkit.py --self-test
"""
import hou


def take_list():
    """所有 take 名（含 Main）。"""
    return [t.name() for t in hou.takes.takes()]


def take_create(name, set_current=True):
    """新建 take（hscript takeadd）。返回 hou.Take。"""
    if name in take_list():
        raise ValueError(f"take 已存在：{name}")
    hou.hscript(f"takeadd {name}")
    t = hou.takes.findTake(name)
    if t is None:
        raise RuntimeError(f"takeadd 后找不到 {name}")
    if set_current:
        hou.takes.setCurrentTake(t)
    return t


def take_set_current(name):
    """切换当前 take（Main = 根 take）。"""
    t = hou.takes.findTake(name)
    if t is None:
        raise ValueError(f"take 不存在：{name}")
    hou.takes.setCurrentTake(t)
    return hou.takes.currentTake().name()


def take_add_parm(node_path, parm_name, take_name=None):
    """把节点的参数纳入 take（默认当前 take）。之后在该 take 下改值即生效。"""
    n = hou.node(node_path)
    if n is None:
        raise ValueError(f"节点不存在：{node_path}")
    pt = n.parmTuple(parm_name)
    if pt is None:
        raise ValueError(f"{node_path} 无参数元组 {parm_name}")
    t = hou.takes.currentTake() if take_name is None \
        else hou.takes.findTake(take_name)
    if t is None:
        raise ValueError(f"take 不存在：{take_name}")
    t.addParmTuple(pt)
    return t.name()


def take_render(take_name, rop_path, frame_range="1-1"):
    """切到指定 take 并渲染 ROP（hscript render -f）。"""
    take_set_current(take_name)
    first, last = frame_range.split("-")
    out, err = hou.hscript(f"render {rop_path} -f {first} {last}")
    if err.strip():
        raise RuntimeError(f"渲染失败：{err.strip()[:200]}")
    return out.strip()[:200]


# ---------------------------------------------------------------- self-test

def self_test(keep=False):
    """验证 take 机制：两个 take 各持同一参数的不同值，切换回读。"""
    failures = {}
    t_a, t_b = "selftest_takeA", "selftest_takeB"

    # 清残留
    for name in (t_a, t_b):
        if name in take_list():
            hou.hscript(f"takerm {name}")

    # 测试载体：geo + torus 的 rows 参数
    if hou.node("/obj/takes_selftest") is not None:
        hou.node("/obj/takes_selftest").destroy()
    geo = hou.node("/obj").createNode("geo", "takes_selftest")
    torus = geo.createNode("torus", "torus")
    default_rows = torus.parm("rows").eval()

    try:
        # take A：rows=6
        take_create(t_a)
        take_add_parm(f"{torus.path()}", "rows")
        torus.parm("rows").set(6)
        # take B：rows=12
        take_create(t_b)
        take_add_parm(f"{torus.path()}", "rows")
        torus.parm("rows").set(12)

        # 切换验证
        take_set_current(t_a)
        if torus.parm("rows").eval() != 6:
            failures["takeA"] = f"takeA 下 rows={torus.parm('rows').eval()} != 6"
        take_set_current(t_b)
        if torus.parm("rows").eval() != 12:
            failures["takeB"] = f"takeB 下 rows={torus.parm('rows').eval()} != 12"
        take_set_current("Main")
        if torus.parm("rows").eval() != default_rows:
            failures["main"] = (f"Main 下 rows={torus.parm('rows').eval()} "
                                f"!= 默认 {default_rows}")

        # take_render 覆盖（P3 承诺）：dummy geometry ROP 双 take 各渲 1 帧
        out_mgr = hou.node("/out")
        if out_mgr is not None:
            try:
                # 坑：值切换测试只要 torus，没有 OUT 节点；ROP 的 soppath
                # 需要一个真实 SOP 输出，先补 null OUT（随 geo 容器一起清理）
                sop_out = geo.createNode("null", "OUT")
                sop_out.setInput(0, torus)
                tmp_bgeo = (hou.text.expandString("$TEMP")
                            + "/takes_selftest.bgeo.sc")
                rop = out_mgr.createNode("geometry", "SELFTEST_take_rop")
                rop.parm("soppath").set("/obj/takes_selftest/OUT")
                # 注意：geometry ROP 的输出参数叫 sopoutput（不是 file）
                rop.parm("sopoutput").set(tmp_bgeo)
                for tk_name in (t_a, t_b):
                    take_render(tk_name, rop.path(), frame_range="1-1")
                take_set_current("Main")
                rop.destroy()
            except Exception as exc:  # noqa: BLE001
                failures["render"] = repr(exc)
    except Exception as exc:  # noqa: BLE001
        failures["exception"] = repr(exc)
    finally:
        if not keep:
            take_set_current("Main")
            for name in (t_b, t_a):
                if name in take_list():
                    hou.hscript(f"takerm {name}")
            if hou.node("/obj/takes_selftest") is not None:
                hou.node("/obj/takes_selftest").destroy()

    print("\n" + "=" * 46)
    print("takes_toolkit self-test 结果")
    print("=" * 46)
    for k in ("takeA", "takeB", "main", "render", "exception"):
        if k in failures:
            print(f"  {k:10s} FAIL  {failures[k]}")
    if not failures:
        print("  takeA/takeB/main 值切换 + take_render 双 take 渲染全 PASS")
    print("=" * 46)
    return failures


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Take 工具")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        raise SystemExit(1 if self_test(keep=args.keep) else 0)
    ap.print_help()


if __name__ == "__main__":
    main()
