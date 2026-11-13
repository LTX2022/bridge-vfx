"""SHOT 分段缓存脚本（方案B：每段独立 savepath → 互不覆盖）

用法（Houdini Python Shell 内）：
    exec(open(r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts/usd_segmented_cache.py").read())

流程：对每个分段：
  1. 改 Fire savepath -> fire_usd_N.usd（独立文件，不会互相覆盖）
  2. 设置该分段帧范围 (f1/f2 + trange)
  3. 点 Save to Disk（同步阻塞）

前置：/obj/RENDER/Fire 已连到 Pyro/Axiom 输出；fire_cache_1..N 已创建
"""
import hou
import time
import os

# ===== 按项目修改 =====
HIP_USD = hou.getenv("HIP") + "/usd"          # 输出目录（与 hip 同目录的 usd/）
SOPIMPORT = "/obj/RENDER/Fire"                # sopimport 节点
CACHE_PREFIX = "/obj/RENDER/fire_cache_"      # LOP filecache 前缀
# 分段定义（段号, 起始帧, 结束帧）——帧不重叠、覆盖全范围
SEGMENTS = [
    (1, 1001, 1050),
    (2, 1051, 1080),
    (3, 1081, 1100),
    (4, 1101, 1120),
    (5, 1121, 1140),
    (6, 1141, 1170),
    (7, 1171, 1200),
    (8, 1201, 1230),
    (9, 1231, 1250),
]
# ====================

fire = hou.node(SOPIMPORT)
if fire is None:
    raise RuntimeError("ERROR: %s not found" % SOPIMPORT)

print("=" * 60)
print("开始分段缓存（方案B：独立 savepath）")
print("=" * 60)

for seg_num, f1, f2 in SEGMENTS:
    savepath = os.path.join(HIP_USD, "fire_usd_%d.usd" % seg_num).replace("\\", "/")
    fire.parm("savepath").set(savepath)
    print("[seg%d] savepath -> %s" % (seg_num, savepath))

    cache = hou.node(CACHE_PREFIX + str(seg_num))
    if cache is None:
        print("[seg%d] ERROR: %s%d not found, skip" % (seg_num, CACHE_PREFIX, seg_num))
        continue
    cache.parm("f1").setExpression(str(f1))
    cache.parm("f2").setExpression(str(f2))
    cache.parm("f3").set(1)
    cache.parm("trange").set(1)
    cache.parm("loadfromdisk").set(0)
    cache.parm("savestyle").set("flattenimplicitlayers")
    print("[seg%d] frame %d-%d, savestyle=flattenimplicitlayers" % (seg_num, f1, f2))

    print("[seg%d] Save to Disk..." % seg_num)
    start = time.time()
    try:
        cache.parm("execute").pressButton()
        print("[seg%d] 完成，耗时 %.0fs" % (seg_num, time.time() - start))
    except Exception as e:
        print("[seg%d] ERROR: %s（继续下一段）" % (seg_num, e))

print("=" * 60)
print("全部 %d 段执行完毕 -> 下一步跑 usd_merge_segments.py" % len(SEGMENTS))
print("=" * 60)
