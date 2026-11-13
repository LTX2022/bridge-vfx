#!/usr/bin/env hython
# -*- coding: utf-8 -*-
"""
quick_setup.py - One-call 场景起建工具（对标 fxhoudinimcp Workflows 类目，2026-08-25）

用法（hython 直跑，在已打开场景的会话里）：
    hython quick_setup.py pyro   --source /obj/geo1 --preset bonfire
    hython quick_setup.py flip   --source /obj/geo1 --preset splash
    hython quick_setup.py rbd    --source /obj/geo1 --preset fracture
    hython quick_setup.py vellum --source /obj/geo1 --preset cloth
    hython quick_setup.py --self-test          # 无头自检（P1）：四链全建全 cook，PASS/FAIL 表
    hython quick_setup.py --self-test --keep   # 自检但保留现场调试

或在 bridge exec_python 里：
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import quick_setup
    quick_setup.setup_pyro("/obj/geo1", preset="bonfire")

设计原则：
1. **建完即验证**：每条链建完立即 cook 末端节点，打印错误摘要（不静默成功）
2. **参数确认**：关键参数用 notes/ 蒸馏的实测值并打印；FLIP 精度对齐公式三条同源
3. **节点类型全部实测存在**（2026-08-25 H21.0.631 探测）：pyrosource /
   volumerasterizeattributes / flipsource / rbdmaterialfracture / rbdbulletsolver(SOP) /
   vellumconstraints / vellumsolver(SOP) / object_merge / dopimport
4. **一次 undo**：整条链包在 hou.undos.group 里

知识来源：references/notes/pyro-notes.md、flip-ocean-notes.md、
vellum-rbd-notes.md、particles-pdg-notes.md（用户笔记蒸馏的实测参数）。
"""
import hou


# ---------------------------------------------------------------- 工具

def _err_summary(node):
    """cook 后收集错误摘要"""
    errs = []
    try:
        node.cook(force=True)
    except hou.OperationFailed as e:
        errs.append(str(e))
    for n in node.allSubChildren() if hasattr(node, "allSubChildren") else []:
        for e in (n.errors() or []):
            errs.append(f"{n.path()}: {e}")
    for e in (node.errors() or []):
        errs.append(f"{node.path()}: {e}")
    return errs


def _report(chain_name, nodes, cook_node):
    print(f"\n=== {chain_name} 已创建 ===")
    for n in nodes:
        print(f"  {n.path()}")
    errs = _err_summary(cook_node)
    if errs:
        print(f"\n⚠️  cook 错误 {len(errs)} 条（必须人工检查）：")
        for e in errs[:10]:
            print(f"  - {e}")
    else:
        print("✅ 末端节点 cook 无错误")
    return errs


def _source_into(container, source_path, name="src_in"):
    """把 source_path（OBJ geo 或 SOP 路径都行）接进 container。

    SOP 输入不能直接吃 OBJ 级 geo 节点，统一走 object_merge
    （objpath 同时接受 OBJ 路径和 SOP 路径）。
    """
    src = hou.node(source_path)
    if src is None:
        raise ValueError(f"源节点不存在：{source_path}")
    om = container.createNode("object_merge", name)
    # H21 的 object_merge 是多对象结构：enable1/objpath1/group1 三元组
    om.parm("objpath1").set(source_path)
    return om


def _set(node, parm_name, value):
    """安全设参：parm 不存在就跳过（返回是否设置成功）。"""
    p = node.parm(parm_name)
    if p is None:
        return False
    try:
        p.set(value)
        return True
    except hou.PermissionError:
        return False


# ---------------------------------------------------------------- Pyro

def setup_pyro(source_path, preset="bonfire", parent="/obj"):
    """
    起建 Pyro 发射源链（三部曲前两部：源属性 + 栅格化）+ 经典 DOP 骨架。

    SOP 链：object_merge -> pyrosource -> volumerasterizeattributes -> null
    DOP 骨架：smokeobject + volumesource(soppath 指向栅格化输出) -> pyrosolver -> output
    末端 null 接 dopimport，cook 它 = 真跑一遍第 1 帧模拟。
    """
    presets = {
        "bonfire":   {"voxel_size": 0.03, "separation": 0.06, "ambient_temp": 300.0,
                      "reference_temp": 3000.0, "buoyancy": 1.0},
        "explosion": {"voxel_size": 0.02, "separation": 0.04, "ambient_temp": 300.0,
                      "reference_temp": 5000.0, "buoyancy": 2.0},
        "smoke":     {"voxel_size": 0.03, "separation": 0.06, "ambient_temp": 300.0,
                      "reference_temp": 300.0, "buoyancy": 0.5},
    }
    p = presets.get(preset, presets["bonfire"])

    with hou.undos.group(f"quick_setup pyro {preset}"):
        geo = hou.node(parent).createNode("geo", f"pyro_{preset}")
        geo.moveToGoodPosition()

        om = _source_into(geo, source_path)

        pyrosource = geo.createNode("pyrosource", "pyrosource")
        pyrosource.setInput(0, om)
        _set(pyrosource, "particlesep", p["separation"])

        rasterize = geo.createNode("volumerasterizeattributes", "rasterize")
        rasterize.setInput(0, pyrosource)
        _set(rasterize, "voxelsize", p["voxel_size"])

        # DOP 骨架：smokeobject + volumesource -> pyrosolver -> output（经典接线）
        dopnet = geo.createNode("dopnet", "pyro_sim")
        smokeobj = dopnet.createNode("smokeobject", "smoke")
        vsrc = dopnet.createNode("volumesource", "source_volumes")
        _set(vsrc, "soppath", rasterize.path())
        merge = dopnet.createNode("merge", "merge_objects")
        merge.setInput(0, smokeobj)
        merge.setInput(1, vsrc)
        solver = dopnet.createNode("pyrosolver", "pyrosolver")
        solver.setInput(0, merge)
        _set(solver, "ambienttemp", p["ambient_temp"])
        _set(solver, "referencetemp", p["reference_temp"])
        _set(solver, "buoyancyscale", p["buoyancy"])
        out = dopnet.createNode("output", "output")
        out.setInput(0, solver)

        dopimport = geo.createNode("dopimport", "dopimport")
        _set(dopimport, "doppath", dopnet.path())
        objname = "smoke"  # smokeobject 节点名（DOP 对象名）
        _set(dopimport, "objpath", objname)
        # 注意：dopimport 的 SOP 输入不接受 volume 源（实测 InvalidInput），只设 doppath

        null_out = geo.createNode("null", "OUT_PYRO")
        null_out.setInput(0, dopimport)

    nodes = [om, pyrosource, rasterize, dopnet, dopimport, null_out]
    print(f"\n[pyro] 精度对齐检查：separation={p['separation']} × scale ÷2~4 应 ≈ "
          f"rasterize voxel={p['voxel_size']}（公式见 flip-ocean-notes.md）")
    return _report(f"Pyro ({preset})", nodes, null_out)


# ---------------------------------------------------------------- FLIP

def setup_flip(source_path, preset="splash", parent="/obj"):
    """
    起建 FLIP 场景。精度对齐公式（见 flip-ocean-notes.md）：
    Particle Separation × Particle Scale ÷2或4 = Rasterize Voxel Size = Solver Voxel Size
    """
    presets = {
        "splash": {"separation": 0.02, "particle_scale": 1.0},
        "pour":   {"separation": 0.03, "particle_scale": 1.0},
        "ocean":  {"separation": 0.05, "particle_scale": 1.0},
    }
    p = presets.get(preset, presets["splash"])

    with hou.undos.group(f"quick_setup flip {preset}"):
        geo = hou.node(parent).createNode("geo", f"flip_{preset}")
        geo.moveToGoodPosition()

        om = _source_into(geo, source_path)
        flipsource = geo.createNode("flipsource", "flipsource")
        flipsource.setInput(0, om)
        _set(flipsource, "particlesep", p["separation"])

        # DOP：flipobject(soppath 指向 flipsource) -> flipsolver -> output
        dopnet = geo.createNode("dopnet", "flip_sim")
        flipobj = dopnet.createNode("flipobject", "flipobject")
        _set(flipobj, "soppath", flipsource.path())
        _set(flipobj, "particlesep", p["separation"])
        solver = dopnet.createNode("flipsolver", "flipsolver")
        _set(solver, "particlescale", p["particle_scale"])
        solver.setInput(0, flipobj)
        out = dopnet.createNode("output", "output")
        out.setInput(0, solver)

        dopimport = geo.createNode("dopimport", "dopimport")
        _set(dopimport, "doppath", dopnet.path())
        _set(dopimport, "objpath", "flipobject")

        null_out = geo.createNode("null", "OUT_FLIP")
        null_out.setInput(0, dopimport)

    nodes = [om, flipsource, dopnet, dopimport, null_out]
    print(f"\n[flip] 精度对齐：separation={p['separation']}, scale={p['particle_scale']}, "
          f"rasterize/solver voxel 应 = {p['separation'] * p['particle_scale'] / 2:.4f}~"
          f"{p['separation'] * p['particle_scale'] / 4:.4f}")
    return _report(f"FLIP ({preset})", nodes, null_out)


# ---------------------------------------------------------------- RBD

def setup_rbd(source_path, preset="fracture", parent="/obj"):
    """起建 RBD 破碎场景（全 SOP 级：H21 的 rbdbulletsolver 是 SOP 节点）。"""
    with hou.undos.group(f"quick_setup rbd {preset}"):
        geo = hou.node(parent).createNode("geo", f"rbd_{preset}")
        geo.moveToGoodPosition()

        om = _source_into(geo, source_path)
        fracture = geo.createNode("rbdmaterialfracture", "fracture")
        fracture.setInput(0, om)

        rbdsolver = geo.createNode("rbdbulletsolver", "rbd_sim")
        rbdsolver.setInput(0, fracture)

        null_out = geo.createNode("null", "OUT_RBD")
        null_out.setInput(0, rbdsolver)

    nodes = [om, fracture, rbdsolver, null_out]
    errs = _report(f"RBD ({preset})", nodes, null_out)
    print("⚠️  voronoi+boolean 联合切割时内部表面必须用 subdivide 不能 divide")
    return errs


# ---------------------------------------------------------------- Vellum

def setup_vellum(source_path, preset="cloth", parent="/obj"):
    """
    起建 Vellum 场景（全 SOP 级）。注意（vellum-rbd-notes.md）：
    缝合约束(spring_ke)必须硬于拉伸(tri_ke)；迭代顺序 Substeps -> Iterations -> Collisions。
    """
    presets = {
        "cloth": {"stiffness": 50000.0, "damping": 0.075, "iterations": 200},
        "flag":  {"stiffness": 30000.0, "damping": 0.05, "iterations": 200},
        "grains": {"stiffness": 10000.0, "damping": 0.1, "iterations": 100},
    }
    p = presets.get(preset, presets["cloth"])

    with hou.undos.group(f"quick_setup vellum {preset}"):
        geo = hou.node(parent).createNode("geo", f"vellum_{preset}")
        geo.moveToGoodPosition()

        om = _source_into(geo, source_path)
        constraints = geo.createNode("vellumconstraints", "vellum_config")
        constraints.setInput(0, om)
        # 默认 constrainttype='none'（不产出任何约束 -> solver 报
        # "Not enough sources"），必须显式选型
        if preset == "grains":
            constraints.destroy()
            constraints = geo.createNode("vellumconstraints_grain", "vellum_config")
            constraints.setInput(0, om)
        else:
            _set(constraints, "constrainttype", "cloth")
            _set(constraints, "stretchstiffness", p["stiffness"])
            _set(constraints, "stretchdampingratio", p["damping"])

        vellumsolver = geo.createNode("vellumsolver", "vellum_sim")
        # 官方示例（AnimatedConstraints.hda）接线：约束输出同时接 solver 的
        # 三个输入（只接 input 0 会报 "Not enough sources specified"，实测）
        for idx in range(len(vellumsolver.inputConnectors())):
            try:
                vellumsolver.setInput(idx, constraints)
            except hou.InvalidInput:
                break
        _set(vellumsolver, "substeps", 5)
        it = vellumsolver.parm("constraintiterations") or vellumsolver.parm("iterations")
        if it is not None:
            it.set(p["iterations"])

        null_out = geo.createNode("null", "OUT_VELLUM")
        null_out.setInput(0, vellumsolver)

    nodes = [om, constraints, vellumsolver, null_out]
    errs = _report(f"Vellum ({preset})", nodes, null_out)
    print(f"[vellum] stiffness={p['stiffness']}, damping={p['damping']}, "
          f"iterations={p['iterations']}")
    print("⚠️  缝合约束必须硬于拉伸约束，否则布料撕裂")
    return errs


# ---------------------------------------------------------------- self-test

def self_test(keep=False):
    """无头自检（P1）：临时源 -> 四链全建全 cook -> 参数回读 -> PASS/FAIL 表。

    返回 failures dict：空 = 全 PASS。--keep 保留现场。
    """
    failures = {}

    # 1. 临时源容器
    old = hou.node("/obj/geo_selftest")
    if old is not None:
        old.destroy()
    container = hou.node("/obj").createNode("geo", "geo_selftest")
    src = container.createNode("torus", "SRC")
    _set(src, "rows", 6)
    _set(src, "cols", 12)

    # 2. 逐链跑（source 用 OBJ 路径 = 文档用法，覆盖 object_merge 分支）
    runs = [
        ("pyro", setup_pyro, {"voxel_size": 0.03}),
        ("flip", setup_flip, {"separation": 0.02}),
        ("rbd", setup_rbd, {}),
        ("vellum", setup_vellum, {"stiffness": 50000.0}),
    ]
    # self-test 建出的容器名（与函数内一致）
    created = {
        "pyro": "/obj/pyro_bonfire",
        "flip": "/obj/flip_splash",
        "rbd": "/obj/rbd_fracture",
        "vellum": "/obj/vellum_cloth",
    }

    for name, fn, expect in runs:
        try:
            errs = fn("/obj/geo_selftest")
        except Exception as exc:  # noqa: BLE001 - 自检要抓一切崩
            failures[name] = f"EXCEPTION: {exc!r}"
            continue
        if errs:
            failures[name] = f"cook errors: {errs[:2]}"
            continue
        # 参数回读
        root = hou.node(created[name])
        if root is None:
            failures[name] = f"容器未创建: {created[name]}"
            continue
        if name == "pyro":
            vra = hou.node(created[name] + "/rasterize")
            got = vra.parm("voxelsize").eval() if vra else None
            if abs((got or 0) - expect["voxel_size"]) > 1e-6:
                failures[name] = f"voxelsize 回读 {got} != {expect['voxel_size']}"
        elif name == "flip":
            fo = hou.node(created[name] + "/flip_sim/flipobject")
            got = fo.parm("particlesep").eval() if fo else None
            if abs((got or 0) - expect["separation"]) > 1e-6:
                failures[name] = f"particlesep 回读 {got} != {expect['separation']}"
        elif name == "vellum":
            vc = hou.node(created[name] + "/vellum_config")
            got = vc.parm("stretchstiffness").eval() if vc else None
            if abs((got or 0) - expect["stiffness"]) > 1e-3:
                failures[name] = f"stretchstiffness 回读 {got} != {expect['stiffness']}"

    # 3. PASS/FAIL 表
    print("\n" + "=" * 46)
    print("quick_setup self-test 结果")
    print("=" * 46)
    for name, _, _ in runs:
        status = "FAIL" if name in failures else "PASS"
        print(f"  {name:8s} {status}  {failures.get(name, '')}")
    print("=" * 46)

    # 4. 清理
    if not keep:
        for path in ["/obj/geo_selftest"] + list(created.values()):
            n = hou.node(path)
            if n is not None:
                n.destroy()
        print("（现场已清理；--keep 可保留）")
    else:
        print("（--keep：现场保留在 " + ", ".join(created.values()) + "）")

    return failures


# ---------------------------------------------------------------- CLI

def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="One-call 场景起建")
    ap.add_argument("kind", nargs="?", choices=["pyro", "flip", "rbd", "vellum", "selftest"])
    ap.add_argument("--source", default=None, help="源节点路径（OBJ geo 或 SOP，如 /obj/geo1）")
    ap.add_argument("--preset", default=None, help="预设名")
    ap.add_argument("--parent", default="/obj", help="创建到哪个容器下")
    ap.add_argument("--self-test", action="store_true", help="无头自检（P1 验收）")
    ap.add_argument("--keep", action="store_true", help="self-test 后保留现场")
    args = ap.parse_args()

    if args.self_test or args.kind == "selftest":
        failures = self_test(keep=args.keep)
        raise SystemExit(1 if failures else 0)

    if not args.kind or not args.source:
        ap.error("需要 kind + --source，或用 --self-test")

    defaults = {"pyro": "bonfire", "flip": "splash", "rbd": "fracture", "vellum": "cloth"}
    preset = args.preset or defaults[args.kind]

    fn = {"pyro": setup_pyro, "flip": setup_flip,
          "rbd": setup_rbd, "vellum": setup_vellum}[args.kind]
    errs = fn(args.source, preset=preset, parent=args.parent)
    raise SystemExit(1 if errs else 0)


if __name__ == "__main__":
    main()
