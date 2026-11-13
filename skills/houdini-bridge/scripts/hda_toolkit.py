#!/usr/bin/env hython
# -*- coding: utf-8 -*-
"""
hda_toolkit.py - HDA 创建/封装工具链（P2，官方手册 API 为准，2026-08-25）

H21.0.631 实测核对过的 API（hou.OpNode.createDigitalAsset 原文签名）：
    createDigitalAsset(name, hda_file_name=None, description=None,
        min_num_inputs=0, max_num_inputs=0, compress_contents=False,
        comment=None, version=None, save_as_embedded=False,
        ignore_external_references=False, change_node_type=True,
        create_backup=True, install_path=None) -> Node

用法（hython 直跑）：
    hython hda_toolkit.py --self-test          # 全链路自检
    hython hda_toolkit.py create --subnet /obj/subnet1 --name me::tool::1.0
也可 bridge exec_python import（只用 hou + 纯 Python；临时路径用
hou.text.expandString("$TEMP")，不 import os）。

官方全流程文档见 references/hda-authoring.md。
"""
import hou


# ---------------------------------------------------------------- 定位

def _find_definition(def_name):
    """按名字找 HDADefinition。接受全名（ns::name::1.0）或裸名（name）。

    依次搜：已加载的 hda 文件（hou.hda.loadedFiles()，含 Embedded）。
    """
    files = list(hou.hda.loadedFiles())
    if "Embedded" not in files:
        files.append("Embedded")
    last = def_name.split("::")[-1]
    for f in files:
        try:
            defs = hou.hda.definitionsInFile(f)
        except hou.OperationFailed:
            continue
        for d in defs:
            n = d.nodeTypeName()
            if n == def_name:
                return d
            # 裸名匹配：'me::tool::1.0' 的中间段或末段 == def_name
            parts = n.split("::")
            if def_name in (parts[-2] if len(parts) >= 2 else parts[0], last):
                return d
    raise ValueError(f"找不到 HDA 定义：{def_name}（list_installed() 看现有）")


# ---------------------------------------------------------------- 核心 API

def create_hda_from_subnet(subnet_path, name="me::asset::1.0",
                           hda_file=None, description="", min_inputs=0,
                           max_inputs=1, compress_contents=False,
                           save_as_embedded=True, change_node_type=True,
                           install_path=None):
    """把 subnet 封装成 HDA（hou.OpNode.createDigitalAsset 全参数）。

    返回新定义的 nodeTypeName（如 'me::asset::1.0'）。
    save_as_embedded=True 存进当前 hip（ Embedded）；False 则写 hda_file。
    """
    node = hou.node(subnet_path)
    if node is None:
        raise ValueError(f"subnet 不存在：{subnet_path}")
    node.createDigitalAsset(
        name=name,
        hda_file_name=hda_file,
        description=description or None,
        min_num_inputs=min_inputs,
        max_num_inputs=max_inputs,
        compress_contents=compress_contents,
        save_as_embedded=save_as_embedded,
        change_node_type=change_node_type,
        install_path=install_path,
    )
    # 坑：change_node_type=True 会替换节点类型，旧的 node 引用失效
    # （hou.ObjectWasDeleted），必须按路径重取
    node = hou.node(subnet_path)
    d = node.type().definition()
    return d.nodeTypeName()


def add_parm(def_name, parm_template_dict, create_backup=True):
    """给 HDA 定义加参数（parmTemplateGroup -> setParmTemplateGroup）。

    parm_template_dict:
        name(必), label, type: float|int|string|toggle|menu, default,
        min/max(数值型), menu_items+menu_labels(menu), folder(放哪个标签页)
    """
    d = _find_definition(def_name)
    group = d.parmTemplateGroup()

    t = parm_template_dict.get("type", "float")
    name = parm_template_dict["name"]
    label = parm_template_dict.get("label", name)
    default = parm_template_dict.get("default", 0)

    if t == "float":
        tmpl = hou.FloatParmTemplate(name, label, 1, (float(default),))
        if "min" in parm_template_dict:
            tmpl.setMinValue(parm_template_dict["min"])
        if "max" in parm_template_dict:
            tmpl.setMaxValue(parm_template_dict["max"])
    elif t == "int":
        tmpl = hou.IntParmTemplate(name, label, 1, (int(default),))
    elif t == "string":
        tmpl = hou.StringParmTemplate(name, label, 1, (str(default),))
    elif t == "toggle":
        tmpl = hou.ToggleParmTemplate(name, label, bool(default))
    elif t == "menu":
        items = tuple(parm_template_dict.get("menu_items", ()))
        labels = tuple(parm_template_dict.get("menu_labels", items))
        tmpl = hou.MenuParmTemplate(name, label, menu_items=items,
                                    menu_labels=labels,
                                    default_value=int(default))
    else:
        raise ValueError(f"不支持的参数类型：{t}")

    folder = parm_template_dict.get("folder")
    if folder:
        # 找同名 folder，没有就建一个（加到根）
        target = None
        for ft in group.entries():
            if ft.name() == folder:
                target = ft
                break
        if target is None:
            target = hou.FolderParmTemplate(folder, folder)
            group.append(target)
        group.appendToFolder(target, tmpl)
    else:
        group.append(tmpl)

    d.setParmTemplateGroup(group)
    return name


def set_type_properties(def_name, description=None, icon=None, comment=None):
    """改 Type Properties 的描述/图标/注释。"""
    d = _find_definition(def_name)
    if description is not None:
        d.setDescription(description)
    if icon is not None:
        d.setIcon(icon)
    if comment is not None:
        d.setComment(comment)


def add_section(def_name, section_name, contents):
    """加 Section（OnCreated / PythonModule / DialogScript / Extra 文件）。

    官方语义：section 是 HDA 内嵌文件，节点实例可通过 opdef: 协议引用。
    """
    d = _find_definition(def_name)
    d.addSection(section_name, contents)
    return section_name


def install_hda(hda_path):
    """安装 .hda 到当前会话（hou.hda.installFile；OPlibraries 是开机自动装）。"""
    hou.hda.installFile(hda_path)
    return hda_path


def uninstall_hda(hda_path):
    """从当前会话卸载 .hda（hou.hda.uninstallFile）。"""
    hou.hda.uninstallFile(hda_path)
    return hda_path


def list_installed():
    """列出所有已加载 hda 文件及其定义。"""
    out = []
    for f in hou.hda.loadedFiles():
        try:
            defs = [d.nodeTypeName() for d in hou.hda.definitionsInFile(f)]
        except hou.OperationFailed:
            defs = ["<读取失败>"]
        out.append((f, defs))
    return out


def bump_version(def_name, major=True):
    """版本号 +1（'1.0'->'2.0' / '1.1'；hou.HDADefinition.setVersion）。"""
    d = _find_definition(def_name)
    cur = d.version() or "1.0"
    try:
        ma, mi = (cur.split(".") + ["0"])[:2]
    except ValueError:
        ma, mi = cur, "0"
    new = f"{int(ma) + 1}.0" if major else f"{ma}.{int(mi) + 1}"
    d.setVersion(new)
    return new


def update_from_node(node_path):
    """把实例节点内部的修改回存进定义（definition.updateFromNode）。

    官方版本工作流：改实例内部 -> updateFromNode 回存 -> bump_version。
    注意：改实例内部参数前需解锁（Allow Editing of Contents）--
    程序化即 node.allowEditingOfContents()（官方 API，hom.zip 原文核对）；
    改完 updateFromNode 回存，需要的话再 node.matchCurrentDefinition() 锁回。
    """
    n = hou.node(node_path)
    if n is None:
        raise ValueError(f"节点不存在：{node_path}")
    d = n.type().definition()
    if d is None:
        raise ValueError(f"{node_path} 不是 HDA 实例")
    d.updateFromNode(n)
    return d.nodeTypeName()


def export_text(target, out_dir=None):
    """文本化导出（复用 hip-convert 的 opscript+cmdread 原理）。

    target 是节点路径（/obj/xxx）：opscript 导出可 cmdread 重建的文本；
    target 是定义名：hou.hda.expandToDirectory 展开成目录镜像。
    返回写出的路径。
    """
    if target.startswith("/"):
        code, _ = hou.hscript(f"opscript -G -r {target}")
        if out_dir is None:
            out_dir = hou.text.expandString("$TEMP")
        path = f"{out_dir}/{target.strip('/').replace('/', '_')}.cmd"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        return path
    d = _find_definition(target)
    if out_dir is None:
        out_dir = f"{hou.text.expandString('$TEMP')}/{d.nodeTypeName().replace(':', '_')}"
    hou.hda.expandToDirectory(out_dir, d)
    return out_dir


# ---------------------------------------------------------------- self-test

def self_test(keep=False):
    """全链路自检：subnet -> create -> 加参 -> OnCreated -> 实例化 cook ->
    update_from_node -> bump_version -> export -> 卸载清场。返回 failures。
    """
    failures = {}
    # 版本断言（计划全局风险项）：HDA API 在 H20/21/22 有差异，先报版本
    ver = hou.applicationVersionString()
    print(f"[self-test] Houdini {ver}（self_test 实测基线是 21.0.631；"
          f"大版本不同时 API 可能漂移，失败先看这里）")
    tmp = hou.text.expandString("$TEMP")
    hda_file = f"{tmp}/hda_selftest.hda"
    full_name = "selftest::hda_tool_test::1.0"
    bare = "hda_tool_test"

    # 0. 清场（残留自上次）
    for p in ("/obj/hda_selftest", "/obj/hda_selftest_instance"):
        n = hou.node(p)
        if n is not None:
            n.destroy()
    try:
        hou.hda.uninstallFile(hda_file)
    except hou.OperationFailed:
        pass

    # 1. 建 subnet
    subnet = hou.node("/obj").createNode("subnet", "hda_selftest")
    # OBJ 级 subnet 里只能放 OBJ 节点：torus 要套一层 geo 容器
    geo = subnet.createNode("geo", "geo_in")
    torus = geo.createNode("torus", "torus")
    subnet.layoutChildren()

    # 2. 封装成 HDA（存文件版，顺便测 install 链路）
    try:
        got = create_hda_from_subnet(
            "/obj/hda_selftest", name=full_name, hda_file=hda_file,
            description="selftest asset", min_inputs=0, max_inputs=1,
            save_as_embedded=False)
        if bare not in got:
            failures["create"] = f"返回名异常：{got}"
    except Exception as exc:  # noqa: BLE001
        failures["create"] = repr(exc)

    # 3. 加参数 + 4. OnCreated section
    if "create" not in failures:
        try:
            add_parm(full_name, {"name": "strength", "type": "float",
                                 "default": 1.5, "min": 0, "max": 10,
                                 "label": "Strength"})
            add_section(full_name, "OnCreated",
                        "# created by hda_toolkit self_test\n")
        except Exception as exc:  # noqa: BLE001
            failures["parm_section"] = repr(exc)

    # 5. 实例化 + cook + 参数回读
    if "create" not in failures:
        try:
            inst = hou.node("/obj").createNode(bare, "hda_selftest_instance")
            inst.cook(force=True)
            errs = [e for e in (inst.errors() or [])]
            if errs:
                failures["instantiate"] = f"cook errors: {errs[:2]}"
            p = inst.parm("strength")
            if p is None:
                failures["instantiate"] = "实例上没有 strength 参数"
            elif abs(p.eval() - 1.5) > 1e-6:
                failures["instantiate"] = f"strength 回读 {p.eval()} != 1.5"
            d = _find_definition(full_name)
            if not d.hasSection("OnCreated"):
                failures["instantiate"] = "OnCreated section 不存在"
        except Exception as exc:  # noqa: BLE001
            failures["instantiate"] = repr(exc)

    # 6. update_from_node（改实例内部再回存）
    if "instantiate" not in failures and "create" not in failures:
        try:
            inner = inst.node("geo_in/torus")
            # 官方解锁 API：hou.OpNode.allowEditingOfContents（不解锁直接改
            # 实例内部会 PermissionError；改完 updateFromNode 回存）
            inst.allowEditingOfContents()
            inner.parm("rows").set(10)
            update_from_node("/obj/hda_selftest_instance")
        except Exception as exc:  # noqa: BLE001
            failures["update"] = repr(exc)

    # 7. bump_version + 8. 描述
    if "create" not in failures:
        try:
            new_v = bump_version(full_name, major=True)
            if new_v != "2.0":
                failures["bump"] = f"版本变到 {new_v} != 2.0"
            set_type_properties(full_name, description="selftest asset v2")
        except Exception as exc:  # noqa: BLE001
            failures["bump"] = repr(exc)

    # 9. export_text（节点 opscript 路线）
    try:
        path = export_text("/obj/hda_selftest_instance", out_dir=tmp)
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(200)
        if "op" not in head and "set" not in head:
            failures["export"] = f"导出内容可疑：{head[:60]!r}"
    except Exception as exc:  # noqa: BLE001
        failures["export"] = repr(exc)

    # 10. 清场
    if not keep:
        for p in ("/obj/hda_selftest", "/obj/hda_selftest_instance"):
            n = hou.node(p)
            if n is not None:
                n.destroy()
        try:
            hou.hda.uninstallFile(hda_file)
        except hou.OperationFailed:
            pass
        print("（现场已清理；--keep 可保留）")

    # 11. 结果表
    steps = ["create", "parm_section", "instantiate", "update", "bump", "export"]
    print("\n" + "=" * 46)
    print("hda_toolkit self-test 结果")
    print("=" * 46)
    for s in steps:
        status = "FAIL" if s in failures else "PASS"
        print(f"  {s:14s} {status}  {failures.get(s, '')}")
    print("=" * 46)
    return failures


# ---------------------------------------------------------------- CLI

def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="HDA 工具链（官方 API）")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["create", "list", "bump", "export"])
    ap.add_argument("--subnet")
    ap.add_argument("--name", default="me::asset::1.0")
    ap.add_argument("--hda-file")
    ap.add_argument("--definition")
    args = ap.parse_args()

    if args.self_test:
        raise SystemExit(1 if self_test(keep=args.keep) else 0)
    if args.cmd == "create":
        print(create_hda_from_subnet(args.subnet, name=args.name,
                                      hda_file=args.hda_file))
    elif args.cmd == "list":
        for f, defs in list_installed():
            print(f"{f}: {defs}")
    elif args.cmd == "bump":
        print(bump_version(args.definition))
    elif args.cmd == "export":
        print(export_text(args.definition))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
