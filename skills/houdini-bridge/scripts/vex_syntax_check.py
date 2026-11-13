#!/usr/bin/env hython
# -*- coding: utf-8 -*-
"""
vex_syntax_check.py — VEX 静态语法检查（对标 fxhoudinimcp 的 validate VEX，2026-08-25）

用法：
    hython vex_syntax_check.py "code.vex"            # 检查文件
    hython vex_syntax_check.py -c "v@P.y += 1;"      # 检查字符串
    hython vex_syntax_check.py -                     # 从 stdin 读

在 bridge 里用（exec_python 有 AST 白名单，os/subprocess 被拦，
所以用 hou 自带的方式，不走外部进程）：

    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    from vex_syntax_check import check_vex
    errors = check_vex(my_code_string)
    if errors: print(errors)

原理：hou 的 hscript 表达式 `vcc` 或直接把代码塞进一个临时 Attribute Wrangle
节点里 cook 一次——Houdini 会在编译 VEX 时报语法错，cook 前就能拿到错误。
这比 cook 后才发现逻辑错更早、更便宜。
"""
import hou


def check_vex(code, context="sop"):
    """
    静态检查一段 VEX 代码。
    返回错误列表（空 = 语法通过）。只做编译级检查，不代表逻辑正确。
    """
    tmp_geo = None
    tmp_wrangle = None
    try:
        # 建一个隔离的临时容器，用完删掉
        tmp_geo = hou.node("/obj").createNode("geo", "__vex_check_tmp__")
        tmp_wrangle = tmp_geo.createNode("attribwrangle", "check")
        tmp_wrangle.parm("snippet").set(code)

        # cook 触发 VEX 编译；语法错会在这里报
        try:
            tmp_wrangle.cook(force=True)
        except hou.OperationFailed as e:
            return [f"cook failed: {e}"]

        errors = list(tmp_wrangle.errors() or [])
        warnings = list(tmp_wrangle.warnings() or [])
        result = []
        for e in errors:
            result.append(f"ERROR: {e}")
        for w in warnings:
            result.append(f"WARN: {w}")
        return result
    finally:
        # 无论如何清理临时节点
        if tmp_geo is not None:
            try:
                tmp_geo.destroy()
            except Exception:
                pass


def check_vex_file(path):
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    return check_vex(code)


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="VEX 静态语法检查")
    ap.add_argument("input", help="文件路径，或 - 从 stdin，或配合 -c 用字符串")
    ap.add_argument("-c", "--code", action="store_true", help="input 是代码字符串不是文件")
    args = ap.parse_args()

    if args.code:
        code = args.input
    elif args.input == "-":
        code = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            code = f.read()

    errors = check_vex(code)
    if errors:
        print(f"发现 {len(errors)} 个问题：")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("✅ VEX 语法检查通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
