"""合并 9 段 fire_usd_N.usd → fire_merged_full.usd（含 relationships + 全部 time samples）

用法（独立 hython，不占用户 Houdini 会话）：
    hython.exe usd_merge_segments.py "C:/path/SHOT_1/usd"
    hython.exe usd_merge_segments.py  # 默认 HIP/usd

关键：必须复制 volume_0 的 relationships（field:density/flame/temperature），
     否则合并后视口/渲染为空（坑 C，见 references/usd-render-practice.md）。
"""
import sys
import os
from pxr import Usd

if len(sys.argv) > 1:
    base = sys.argv[1]
else:
    # ⚠️ 强烈建议显式传 usd 目录路径！独立 hython 的 HIP 通常是启动目录，
    # 不是项目目录，静默用它会读到错误位置（甚至读到别的项目的 usd）。
    base = os.path.join(os.environ.get("HIP", "."), "usd")
    print("⚠️ 未传路径参数，回退到 HIP/usd = %s" % os.path.abspath(base))
    print("   推荐用法: hython.exe usd_merge_segments.py \"C:/path/SHOT_N/usd\"")
base = base.replace("\\", "/")

src1_path = os.path.join(base, "fire_usd_1.usd")
if not os.path.exists(src1_path):
    print("ERROR: %s 不存在 —— 目录不对或分段缓存未生成。base=%s" % (src1_path, base))
    sys.exit(1)

out_path = os.path.join(base, "fire_merged_full.usd")
if os.path.exists(out_path):
    os.remove(out_path)
dst = Usd.Stage.CreateNew(out_path)
dst.SetDefaultPrim(dst.DefinePrim("/Fire", "Xform"))
dst_vol = dst.DefinePrim("/Fire/volume_0", "Volume")

# --- 复制 stage metadata（坑：漏掉会让帧率/轴向/单位解释出错）---
src1 = Usd.Stage.Open(src1_path)
if src1 is None:
    print("ERROR: 无法打开 %s（文件损坏？）" % src1_path)
    sys.exit(1)
for key in ("framesPerSecond", "timeCodesPerSecond", "metersPerUnit", "upAxis"):
    val = src1.GetMetadata(key)
    if val is not None:
        dst.SetMetadata(key, val)
print("stage metadata:", {k: dst.GetMetadata(k) for k in ("framesPerSecond", "timeCodesPerSecond", "metersPerUnit", "upAxis")})

# --- 从第一段复制 volume_0 静态属性 + relationships ---
src_vol1 = src1.GetPrimAtPath("/Fire/volume_0")

for attr in src_vol1.GetAttributes():
    if attr.GetTimeSamples():
        continue
    try:
        val = attr.Get()
        if val is not None:
            dst_attr = dst_vol.CreateAttribute(attr.GetName(), attr.GetTypeName())
            dst_attr.Set(val)
    except Exception as e:
        print("skip attr", attr.GetName(), str(e)[:60])

for rel in src_vol1.GetRelationships():
    rname = rel.GetName()
    targets = list(rel.GetTargets())
    if targets:
        dst_rel = dst_vol.CreateRelationship(rname)
        for t in targets:
            dst_rel.AddTarget(t)
print("relationships:", [r.GetName() for r in dst_vol.GetRelationships()])

# --- 逐段复制 field prims 的全部 time samples ---
total = 0
missing_segs = []
for i in range(1, 10):
    src_path = os.path.join(base, "fire_usd_%d.usd" % i)
    if not os.path.exists(src_path):
        missing_segs.append(i)
        print("⚠️ seg%d 缺失: %s（该段帧将不在合并文件中！）" % (i, src_path))
        continue
    src = Usd.Stage.Open(src_path)
    if src is None:
        missing_segs.append(i)
        print("⚠️ seg%d 打开失败: %s" % (i, src_path))
        continue
    src_vol = src.GetPrimAtPath("/Fire/volume_0")
    if not src_vol or not src_vol.IsValid():
        missing_segs.append(i)
        print("⚠️ seg%d 无 /Fire/volume_0 prim: %s" % (i, src_path))
        continue
    for child in src_vol.GetChildren():
        cname = child.GetName()
        dst_child = dst.DefinePrim("/Fire/volume_0/" + cname, child.GetTypeName())
        for attr in child.GetAttributes():
            aname = attr.GetName()
            times = attr.GetTimeSamples()
            dst_attr = dst_child.CreateAttribute(aname, attr.GetTypeName())
            if times:
                for t in times:
                    try:
                        dst_attr.Set(attr.Get(t), t)
                        total += 1
                    except Exception as e:
                        print("skip sample", aname, t, str(e)[:60])
            else:
                try:
                    val = attr.Get()
                    if val is not None:
                        dst_attr.Set(val)
                except Exception as e:
                    print("skip static", aname, str(e)[:60])
    print("seg%d merged" % i)

dst.GetRootLayer().Save()
print("TOTAL samples:", total)
print("Output:", out_path)
if missing_segs:
    print("❌ 警告：以下分段未合并: %s —— 合并文件缺帧，渲染会有空缺！" % missing_segs)
    print("   请先补齐分段缓存（usd_segmented_cache.py）再重新合并。")
print("下一步：usd_verify_merged.py 校验")
