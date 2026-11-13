#!/usr/bin/env hython
# -*- coding: utf-8 -*-
"""
cops_toolkit.py - Copernicus (新 COPs) 工具（P3，对标 fxhoudinimcp 7 工具，2026-08-25）

H21.0.631 无头实测事实（重要，全踩过）：
- 新 COPs（Copernicus）节点建在 **/img/copnet**（类别 hou.copNodeTypeCategory，
  名字 "Cop"）；旧 COP2 在 /img/img（"Cop2"）--建错容器节点类型全找不到
- **算子输入是类型化的**（Mono/Height/Color 层）：sopimport 出的 Geometry
  线缆**必须经 geotolayer 转图层**才能进 blur 等算子（否则
  "Can't convert Geometry to Mono"）
- **file 节点直连算子在无头环境报 "source is missing"**（JPG/PNG 都一样，
  file 自身 cook 无错、null 直连能过--GUI 里是否正常待验证）。无头喂图走
  SOP 源 + sopimport + geotolayer 这条已验证的路
- 可用算子实测：blur（size_pixel）crop/transform?/layerproperties/mono_flop/
  resize/brightness 等名字属于类别表，但同名（grade/transform/merge）在
  Copernicus 里不存在（那是旧 COP2）--先查 hou.copNodeTypeCategory()

用法：hython cops_toolkit.py --self-test
"""
import hou


def create_cop_network(parent="/img", name="cop_net"):
    """建 Copernicus 网络（/img 下的 copnet 容器）。"""
    return hou.node(parent).createNode("copnet", name)


def cop_create(node_type, parent, parms=None, inputs=None, name=None):
    """在 Copernicus 网络里建节点。inputs 按序接输入口（节点名或路径）。"""
    n = hou.node(parent).createNode(node_type, name)
    if n is None:
        raise ValueError(f"节点类型不存在：{node_type}（查 "
                         f"hou.copNodeTypeCategory().nodeTypes()）")
    for k, v in (parms or {}).items():
        p = n.parm(k)
        if p is not None:
            p.set(v)
    for i, src in enumerate(inputs or []):
        s = hou.node(src if "/" in src else f"{parent}/{src}")
        if s is not None:
            n.setInput(i, s)
    return n


def cop_set_parm(path, parm, value):
    n = hou.node(path)
    if n is None:
        raise ValueError(f"节点不存在：{path}")
    p = n.parm(parm)
    if p is None:
        raise ValueError(f"{path} 无参数 {parm}")
    p.set(value)
    return value


def cop_cook(path, frame=None):
    """cook 节点，返回错误列表（空 = 干净）。"""
    if frame is not None:
        hou.setFrame(frame)
    n = hou.node(path)
    if n is None:
        raise ValueError(f"节点不存在：{path}")
    errs = []
    try:
        n.cook(force=True)
    except hou.OperationFailed as e:
        errs.append(str(e))
    errs.extend(n.errors() or [])
    return errs


def sop_image_chain(copnet_path, sop_path, name_prefix="img"):
    """已验证的无头喂图链：sopimport -> geotolayer（返回 geotolayer 节点）。

    后续算子接它的输出。SOP 源建议用 heightfield（体素 -> Height 层）。
    """
    si = cop_create("sopimport", copnet_path,
                    parms={"usesoppath": 1, "soppath": sop_path},
                    name=f"{name_prefix}_sopimport")
    gt = cop_create("geotolayer", copnet_path, inputs=[si.name()],
                    name=f"{name_prefix}_layer")
    return gt


def cop_list_presets():
    """常用链速查（键 -> 说明）。全部基于无头实测。"""
    return {
        "无头喂图（唯一可靠）": "SOP(heightfield) -> sopimport(usesoppath=1, "
            "soppath=...) -> geotolayer -> 算子 -> null",
        "模糊": "geotolayer -> blur(size_pixel=N) -> null",
        "输出写盘": "算子 -> output(交互) / rop_image(写盘)",
        "file 节点": "无头环境直连算子报 source is missing，勿用（GUI 待验证）",
        "类型坑": "算子输入是类型化线缆；Geometry 必须经 geotolayer 转图层",
    }


# ---------------------------------------------------------------- self-test

def self_test(keep=False):
    """链路：heightfield SOP -> sopimport -> geotolayer -> blur -> null，
    cook 验收 + 参数回读。返回 failures（空 = PASS）。"""
    failures = {}
    types = hou.copNodeTypeCategory().nodeTypes()
    need = ("sopimport", "geotolayer", "blur", "null")
    missing = [t for t in need if t not in types]
    if missing:
        print(f"[self-test] SKIP：无 Copernicus 节点（缺 {missing}，需 H20.5+）")
        return {"__skip__": f"Copernicus 不可用：{missing}"}

    # 清残留
    for p in ("/obj/COPS_SELFTEST", "/img/cops_selftest"):
        n = hou.node(p)
        if n is not None:
            n.destroy()

    try:
        # SOP 源：heightfield -> null
        g = hou.node("/obj").createNode("geo", "COPS_SELFTEST")
        hf = g.createNode("heightfield", "heightfield")
        sop_out = g.createNode("null", "OUT")
        sop_out.setInput(0, hf)

        # Copernicus 链
        net = create_cop_network(name="cops_selftest")
        gt = sop_image_chain(net.path(), "/obj/COPS_SELFTEST/OUT")
        b = cop_create("blur", net.path(), parms={"size_pixel": 2.0},
                       inputs=[gt.name()], name="bl")
        n = cop_create("null", net.path(), inputs=["bl"], name="OUT")

        errs = cop_cook(n.path(), frame=1)
        if errs:
            failures["cook"] = f"错误：{errs[:2]}"
        got = b.parm("size_pixel").eval()
        if abs(got - 2.0) > 1e-6:
            failures["parm"] = f"size_pixel 回读 {got} != 2.0"
    except Exception as exc:  # noqa: BLE001
        failures["exception"] = repr(exc)
    finally:
        if not keep:
            for p in ("/obj/COPS_SELFTEST", "/img/cops_selftest"):
                n2 = hou.node(p)
                if n2 is not None:
                    n2.destroy()

    print("\n" + "=" * 46)
    print("cops_toolkit self-test 结果")
    print("=" * 46)
    for k in ("cook", "parm", "exception"):
        if k in failures:
            print(f"  {k:10s} FAIL  {failures[k]}")
    if not failures:
        print("  cook/parm 全 PASS（sopimport->geotolayer->blur->null）")
    print("=" * 46)
    return failures


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Copernicus 工具")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        f = self_test(keep=args.keep)
        # graceful skip 不算 FAIL（退出码 0），真实失败 1
        raise SystemExit(1 if (f and "__skip__" not in f) else 0)
    ap.print_help()


if __name__ == "__main__":
    main()
