#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
official_docs_sync.py — Houdini 官方文档年度同步/蒸馏入口（2026-08-25）

用途
----
官方文档一年一更新（随 Houdini 大版本）。每年升级 Houdini 后跑一次本脚本，
即可把新版官方手册重新"蒸馏"成本 skill 的索引文件：

    python official_docs_sync.py                 # 自动探测最新版 Houdini
    python official_docs_sync.py --houdini "C:/Program Files/Side Effects Software/Houdini 22.0.xxx"

产出（写入 <skill>/references/official-docs/）
--------------------------------------------
- INDEX.md               总目录：版本戳、47 个域的条目数、查询方法
- <domain>-index.md      每个 help zip 一份索引：内部页面路径 + 页面标题
- （可选）--extract-mirror 时解压全部 txt 到 mirror/<domain>/ 供 grep

查询手册内容（不展开镜像时的推荐方式）
------------------------------------
    python official_docs_sync.py --query "voxelsize" --domain vellum
    python official_docs_sync.py --page vellum.zip:vellumsolver.txt

设计原则
--------
- 官方文档与 Houdini 版本绑定，不做"内容级"预蒸馏（会过期），只做"索引级"蒸馏
- 深度语义蒸馏（如 pyro-reference.md）单独做，本脚本不覆盖
- 幂等：可反复运行；版本变化时 INDEX.md 头部的版本戳会更新

标准库 only，无需 hou。
"""
import argparse
import datetime
import os
import re
import sys
import zipfile

DEFAULT_PROGRAM_FILES = r"C:\Program Files\Side Effects Software"
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(SKILL_ROOT, "references", "official-docs")


def find_latest_houdini(program_files=DEFAULT_PROGRAM_FILES):
    """返回最新版 Houdini 安装目录；找不到返回 None。"""
    if not os.path.isdir(program_files):
        return None
    cands = []
    for d in os.listdir(program_files):
        m = re.match(r"Houdini (\d+\.\d+\.\d+)", d)
        if m and os.path.isdir(os.path.join(program_files, d, "houdini", "help")):
            cands.append((tuple(int(x) for x in m.group(1).split(".")), d))
    if not cands:
        return None
    cands.sort(reverse=True)
    return os.path.join(program_files, cands[0][1])


def page_title(text):
    """从帮助 txt 提取标题：第一行非空文本，去掉 = 装饰。"""
    for line in text.splitlines():
        s = line.strip().strip("=").strip()
        if s:
            return s[:100]
    return "(no title)"


def build_indexes(help_dir, out_dir):
    """遍历所有 help zip，生成每域索引 + 总 INDEX.md。返回统计信息。"""
    os.makedirs(out_dir, exist_ok=True)
    version = re.search(r"Houdini (\d+\.\d+\.\d+)", help_dir)
    version = version.group(1) if version else "unknown"
    stats = []
    zips = sorted(f for f in os.listdir(help_dir) if f.endswith(".zip"))
    for zf in zips:
        domain = zf[:-4]
        zpath = os.path.join(help_dir, zf)
        try:
            z = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            continue
        entries = [n for n in z.namelist() if n.endswith(".txt")]
        lines = [f"# {domain}.zip 官方文档索引（Houdini {version}）",
                 f"",
                 f"共 {len(entries)} 页。用 `--page {domain}.zip:<内部路径>` 读取全文。",
                 f"",
                 f"| 页面 | 标题 |", f"|---|---|"]
        for name in sorted(entries):
            try:
                raw = z.read(name).decode("utf-8", errors="ignore")
                title = page_title(raw).replace("|", "\\|")
            except Exception:
                title = "(read error)"
            lines.append(f"| `{name}` | {title} |")
        with open(os.path.join(out_dir, f"{domain}-index.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        stats.append((domain, len(entries)))
        z.close()

    # 总索引
    today = datetime.date.today().isoformat()
    head = [
        f"# Houdini 官方文档总索引（版本 {version}，同步于 {today}）",
        f"",
        f"来源：`{help_dir}`（共 {len(stats)} 个域 / {sum(s[1] for s in stats)} 页）",
        f"",
        f"**年度更新入口**：升级 Houdini 后重跑 `scripts/official_docs_sync.py` 即可刷新全部索引。",
        f"",
        f"## 查询方法",
        f"",
        f"```bash",
        f"# 全文检索某域",
        f"python official_docs_sync.py --query 关键词 --domain vellum",
        f"# 读取某页全文",
        f"python official_docs_sync.py --page vellum.zip:vellumsolver.txt",
        f"```",
        f"",
        f"bridge 运行时也可用 `help.search` / `help.query`（等效，走 MCP 工具）。",
        f"",
        f"## 域目录",
        f"",
        f"| 域 | 页数 | 索引文件 |", f"|---|---|---|",
    ]
    for domain, n in stats:
        head.append(f"| {domain} | {n} | `{domain}-index.md` |")
    with open(os.path.join(out_dir, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n")
    return version, stats


def query_pages(help_dir, domain, keyword):
    """在指定域（或全域）的 txt 里做不区分大小写全文检索，打印命中行。"""
    zips = [domain + ".zip"] if domain else \
        sorted(f for f in os.listdir(help_dir) if f.endswith(".zip"))
    kw = keyword.lower()
    hits = 0
    for zf in zips:
        zpath = os.path.join(help_dir, zf)
        if not os.path.exists(zpath):
            print(f"[skip] {zf} 不存在", file=sys.stderr)
            continue
        z = zipfile.ZipFile(zpath)
        for name in sorted(z.namelist()):
            if not name.endswith(".txt"):
                continue
            try:
                raw = z.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            if kw in raw.lower():
                for i, line in enumerate(raw.splitlines(), 1):
                    if kw in line.lower():
                        print(f"{zf}:{name}:{i}: {line.strip()[:160]}")
                        hits += 1
                        break
        z.close()
    print(f"\n共命中 {hits} 页")


def read_page(help_dir, spec):
    """读取 zip 内单页全文：spec 形如 vellum.zip:vellumsolver.txt"""
    if ":" not in spec:
        print("格式：--page <domain>.zip:<内部路径>", file=sys.stderr)
        sys.exit(2)
    zf, inner = spec.split(":", 1)
    z = zipfile.ZipFile(os.path.join(help_dir, zf))
    sys.stdout.write(z.read(inner).decode("utf-8", errors="ignore"))


def extract_mirror(help_dir, out_dir):
    """可选：解压全部 txt 到 mirror/ 供本地 grep。"""
    mirror = os.path.join(out_dir, "mirror")
    for zf in sorted(f for f in os.listdir(help_dir) if f.endswith(".zip")):
        domain = zf[:-4]
        dest = os.path.join(mirror, domain)
        os.makedirs(dest, exist_ok=True)
        z = zipfile.ZipFile(os.path.join(help_dir, zf))
        for name in z.namelist():
            if name.endswith(".txt"):
                target = os.path.join(dest, name.replace("/", os.sep))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(z.read(name))
        z.close()
    print(f"镜像解压完成：{mirror}")


def main():
    ap = argparse.ArgumentParser(description="Houdini 官方文档年度同步/蒸馏入口")
    ap.add_argument("--houdini", help="Houdini 安装目录（默认自动探测最新版）")
    ap.add_argument("--query", help="全文检索关键词")
    ap.add_argument("--domain", help="限定域（zip 名去后缀，如 vellum）")
    ap.add_argument("--page", help="读取单页：domain.zip:内部路径")
    ap.add_argument("--extract-mirror", action="store_true", help="解压全部 txt 镜像")
    args = ap.parse_args()

    hdir = args.houdini or find_latest_houdini()
    if not hdir:
        print("未找到 Houdini 安装目录，请用 --houdini 指定", file=sys.stderr)
        sys.exit(1)
    help_dir = os.path.join(hdir, "houdini", "help")
    if not os.path.isdir(help_dir):
        print(f"help 目录不存在：{help_dir}", file=sys.stderr)
        sys.exit(1)

    if args.page:
        read_page(help_dir, args.page)
        return
    if args.query:
        query_pages(help_dir, args.domain, args.query)
        return
    if args.extract_mirror:
        extract_mirror(help_dir, OUT_DIR)
        return

    version, stats = build_indexes(help_dir, OUT_DIR)
    print(f"同步完成：Houdini {version}，{len(stats)} 个域，{sum(s[1] for s in stats)} 页")
    print(f"索引目录：{OUT_DIR}")
    for d, n in stats:
        print(f"  {d:20s} {n:5d} 页")


if __name__ == "__main__":
    main()
