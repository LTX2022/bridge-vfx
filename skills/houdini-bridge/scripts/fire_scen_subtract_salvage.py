# fire_scen_subtract_salvage.py — HDRI/背景混入 fire pass 的批量救赎（坑 D）
#
# 原理：fire = E + T·scen（E=火焰自发光，T=烟透射率，scen=同帧无火场景 pass）
#   解出干净预乘火层：RGB = E = fire − T·scen，alpha = 1 − T
#   合成：final = E + (1−alpha)·plate，对任意背景板正确（HDRI 不会漏入）
# 数学已在 SHOT_1 frame 1100 验证：重建 fire beauty 平均误差 0.5%。
#
# 依赖：pip install OpenEXR numpy（OpenEXR>=3.2 有 Windows 预编译 wheel）
# 用法：
#   python fire_scen_subtract_salvage.py <fire_dir> <scen_dir> <out_dir> [起始帧 结束帧]
# 例：
#   python fire_scen_subtract_salvage.py SHOT_1/render/render_fire SHOT_1/render/render_scen SHOT_1/render/fire_clean 1001 1250
#
# 注意：
# - fire/scen 必须同帧同机位同灯光（同一工程渲染的两个 pass）。
# - scen 极暗区域（亮度<0.003，如夜空）比率不稳，自动回退 T=1（该处 alpha=0）。
# - 输出 RGBA float32 EXR，E 已预乘；Nuke 里 Read 按 premultiplied 处理，直接 over 即可。
# - 也可以不进 Nuke：若最终背景就是 scen pass，E over scen == 原 fire beauty（已验证）。
import os
import re
import sys

import numpy as np
import OpenEXR
import Imath

DARK_LUM = 0.003  # scen 亮度低于此值认为比率不可靠
_FLOAT = Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))


def read_rgba(path):
    """读 EXR 的 C 层（多 part 文件取 part 0）-> HxWx4 float32"""
    f = OpenEXR.InputFile(path)
    h = f.header()
    dw = h["dataWindow"]
    w = dw.max.x - dw.min.x + 1
    hh = dw.max.y - dw.min.y + 1
    chans = h["channels"].keys()
    cols = []
    for c in ("R", "G", "B", "A"):
        if c in chans:
            buf = f.channel(c, Imath.PixelType(Imath.PixelType.FLOAT))
            cols.append(np.frombuffer(buf, np.float32).reshape(hh, w))
        else:
            cols.append(np.ones((hh, w), np.float32) if c == "A" else np.zeros((hh, w), np.float32))
    f.close()
    return np.stack(cols, axis=-1)


def write_rgba(path, img):
    h, w = img.shape[:2]
    hdr = OpenEXR.Header(w, h)
    hdr["channels"] = {"R": _FLOAT, "G": _FLOAT, "B": _FLOAT, "A": _FLOAT}
    out = OpenEXR.OutputFile(path, hdr)
    out.writePixels({c: np.ascontiguousarray(img[..., i]).tobytes() for i, c in enumerate("RGBA")})
    out.close()


def salvage(fire, scen):
    """fire/scen: HxWx4 float32 -> 干净预乘火层 HxWx4 float32"""
    fire = np.nan_to_num(fire.astype(np.float32))
    scen = np.nan_to_num(scen.astype(np.float32))
    f_rgb, s_rgb = fire[..., :3], scen[..., :3]
    f_lum = f_rgb.mean(axis=-1)
    s_lum = s_rgb.mean(axis=-1)
    T = np.where(s_lum > DARK_LUM, f_lum / np.maximum(s_lum, 1e-4), 1.0)
    T = np.clip(T, 0.0, 1.0)
    E = np.clip(f_rgb - T[..., None] * s_rgb, 0, None)
    alpha = 1.0 - T
    return np.concatenate([E, alpha[..., None]], axis=-1).astype(np.float32)


def frame_num(name):
    m = re.search(r"\.(\d+)\.exr$", name)
    return int(m.group(1)) if m else None


def main():
    fire_dir, scen_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    f1 = int(sys.argv[4]) if len(sys.argv) > 4 else None
    f2 = int(sys.argv[5]) if len(sys.argv) > 5 else None
    os.makedirs(out_dir, exist_ok=True)

    scen_map = {}
    for x in os.listdir(scen_dir):
        n = frame_num(x)
        if n is not None:
            scen_map[n] = os.path.join(scen_dir, x)

    jobs = []
    for x in sorted(os.listdir(fire_dir)):
        n = frame_num(x)
        if n is None:
            continue
        if f1 is not None and n < f1:
            continue
        if f2 is not None and n > f2:
            continue
        if n not in scen_map:
            print("跳过 %d：scen pass 缺这一帧" % n)
            continue
        jobs.append((n, os.path.join(fire_dir, x), scen_map[n]))

    print("共 %d 帧待处理" % len(jobs))
    ok = 0
    for n, fpath, spath in jobs:
        try:
            out = salvage(read_rgba(fpath), read_rgba(spath))
            write_rgba(os.path.join(out_dir, "fire_clean.%04d.exr" % n), out)
            ok += 1
            if ok % 10 == 0 or ok == 1:
                print("已完成 %d/%d（帧 %d）" % (ok, len(jobs), n))
        except Exception as e:
            print("帧 %d 失败: %s" % (n, e))
    print("完成 %d/%d -> %s" % (ok, len(jobs), out_dir))
    print("合成公式：E over plate（E 已预乘）。救赎后建议抽查 3 帧确认无 HDRI 泄漏。")


if __name__ == "__main__":
    main()
