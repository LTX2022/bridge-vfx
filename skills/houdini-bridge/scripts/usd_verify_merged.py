"""校验合并后的 USD + 渲染输出完整性（渲染前必查，30 秒）

用法（任何有 pxr 的 python，或 hython）：
    python usd_verify_merged.py "C:/path/SHOT_1/usd"
    python usd_verify_merged.py "C:/path/SHOT_1/usd" --render "C:/path/SHOT_1/render"

检查项：
  1. 每个 field (density/flame/temperature) 帧覆盖无缺口
  2. filePath 引用的 VDB 文件全部存在
  3. relationships (field:*) 存在
  4. (可选 --render) 各 pass 帧数一致、EXR 非空、缺帧
"""
import os
import re
import sys
import struct
from collections import Counter
from pxr import Usd

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0].replace("\\", "/") if args else os.path.join(os.environ.get("HIP", "."), "usd")
    render_dir = None
    if "--render" in sys.argv:
        i = sys.argv.index("--render")
        render_dir = sys.argv[i + 1].replace("\\", "/") if len(sys.argv) > i + 1 else None

    merged = os.path.join(base, "fire_merged_full.usd")
    if not os.path.exists(merged):
        print("ERROR: %s not found" % merged)
        sys.exit(1)

    stage = Usd.Stage.Open(merged)
    if stage is None:
        print("ERROR: 无法打开 %s（文件损坏或格式不支持）" % merged)
        sys.exit(1)
    vol = stage.GetPrimAtPath("/Fire/volume_0")
    ok_all = True
    if not vol or not vol.IsValid():
        print("ERROR: /Fire/volume_0 prim 不存在 -> 合并结构不对，渲染必空！")
        print("stage 根层级 prim:", [p.GetPath().pathString for p in stage.Traverse()][:20])
        sys.exit(1)

    # 0. stage metadata（漏了会帧率/轴向解释错）
    meta = {k: stage.GetMetadata(k) for k in ("framesPerSecond", "timeCodesPerSecond", "metersPerUnit", "upAxis")}
    print("stage metadata:", meta)
    for k, v in meta.items():
        if v is None:
            print("  ⚠️ %s 缺失（合并脚本应复制）" % k)
            ok_all = False

    # 1. relationships
    rels = [r.GetName() for r in vol.GetRelationships()]
    print("relationships:", rels)
    for f in ("field:density", "field:flame", "field:temperature"):
        ok = f in rels and len(list(vol.GetRelationship(f).GetTargets())) > 0
        print("  %-18s %s" % (f, "OK" if ok else "MISSING!"))
        if not ok:
            ok_all = False

    # 2. 每 field 帧覆盖
    files = set()
    for child in vol.GetChildren():
        cname = child.GetName()
        fp = child.GetAttribute("filePath")
        if fp is None:
            print("  %s: NO filePath attr -> 渲染会空! (坑C)" % cname)
            ok_all = False
            continue
        times = sorted(fp.GetTimeSamples())
        gaps = [times[i] for i in range(1, len(times)) if times[i] != times[i - 1] + 1]
        n = len(times)
        if n == 0:
            print("  %-18s 0 帧 -> 渲染会空!" % cname)
            ok_all = False
            continue
        print("  %-18s %d 帧 %d-%d %s" % (cname, n, times[0], times[-1], "无缺口" if not gaps else "GAP: %s" % gaps[:3]))
        if gaps or n == 1:
            ok_all = False
        for t in times:
            v = fp.Get(t)
            if v and v.path:
                files.add(v.path)
        if times[0] != 1001:
            print("    注意：起始帧 %d != 1001" % times[0])

    # 3. VDB 文件存在性
    missing = []
    for f in sorted(files):
        p = f if os.path.isabs(f) else os.path.normpath(os.path.join(base, f.replace("./", "")))
        if not os.path.exists(p):
            missing.append(p)
    print("filePath 引用: %d 唯一文件, 缺失: %s" % (len(files), missing if missing else "无 ✅"))
    if missing:
        ok_all = False

    # 4. 渲染输出（可选）
    if render_dir:
        for d in sorted(os.listdir(render_dir)):
            sub = os.path.join(render_dir, d)
            if not os.path.isdir(sub):
                continue
            exrs = sorted(x for x in os.listdir(sub) if x.endswith(".exr"))
            if not exrs:
                print("render %s: 空目录" % d)
                continue
            numbered = []
            for x in exrs:
                m = re.search(r"\.(\d+)\.exr$", x)
                if m:
                    numbered.append((int(m.group(1)), x))
                else:
                    print("    ⚠️ 无法解析帧号: %s" % x)
            if not numbered:
                print("render %s: 无标准命名 EXR（需要 .帧号.exr）" % d)
                continue
            nums = sorted(n for n, _ in numbered)
            gaps = [nums[i] for i in range(1, len(nums)) if nums[i] != nums[i - 1] + 1]
            sizes = [os.path.getsize(os.path.join(sub, x)) for x in exrs[:3]]
            res = exr_res(os.path.join(sub, exrs[0]))
            print("render %-16s %d 帧 %d-%d 缺帧:%s 分辨率:%s 前3帧大小:%s" %
                  (d, len(exrs), nums[0], nums[-1], gaps[:3] if gaps else "无",
                   res, [s // 1024 for s in sizes]))
            # 帧范围一致性
            if d.startswith("render_") and nums[-1] - nums[0] + 1 != len(nums):
                print("    ⚠️ 帧不连续")

    print("\n结果:", "✅ 全部通过" if ok_all else "❌ 有问题，见上")

def exr_res(path):
    """读 EXR header 拿分辨率（支持 multipart 0x1000）"""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"\x76\x2f\x31\x01":
                return "?"
            version = struct.unpack("<I", f.read(4))[0]
            if version & 0x1000:  # multipart: 8-byte offset
                f.read(8)
            attrs = {}
            while True:
                name = b""
                while True:
                    c = f.read(1)
                    if not c or c == b"\x00":
                        break
                    name += c
                if not name:
                    break
                typ = b""
                while True:
                    c = f.read(1)
                    if not c or c == b"\x00":
                        break
                    typ += c
                size = struct.unpack("<i", f.read(4))[0]
                data = f.read(size)
                attrs[name.decode()] = (typ.decode(), data)
            dw = attrs.get("dataWindow")
            if dw:
                x1, y1, x2, y2 = struct.unpack("<iiii", dw[1])
                return "%dx%d" % (x2 - x1 + 1, y2 - y1 + 1)
            return "?"
    except Exception:
        return "?"

if __name__ == "__main__":
    main()
