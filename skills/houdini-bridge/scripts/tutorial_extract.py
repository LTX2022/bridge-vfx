# -*- coding: utf-8 -*-
"""教程视频学习管线(提取侧) -- 重组自 Houdini_agent learning 管线,OCR/落库由 LLM 视觉替代

流程: 视频/URL -> ffmpeg 场景检测抽帧(切换参数/节点时才抽,去重复) + whisper 带时间戳转录
      -> 术语纠正 -> manifest.json(帧+字幕按时间对齐)
之后由 agent 读帧(Read 看图)+ manifest 生成教程笔记进 skill references。

前置(本机已就位): ffmpeg 8.1.1 / openai-whisper(base/tiny 模型已缓存) / yt-dlp 可选

用法:
    # 本地视频
    python tutorial_extract.py "D:/tutorials/pyro_lesson1.mp4" -o "D:/tutorials/pyro_lesson1_work"
    # 在线教程(yt-dlp 自动下载,最高 720p 够读 UI)
    python tutorial_extract.py "https://www.youtube.com/watch?v=xxx" -o "D:/tutorials/xxx_work"
    # 参数
    python tutorial_extract.py video.mp4 -o out --scene 0.25 --interval 30 --model base
    #   --scene    场景检测阈值(0.2-0.4,默认 0.3;调低=抽更多)
    #   --interval 兜底固定抽帧间隔秒(默认 30;0=只用场景检测)
    #   --model    whisper 模型(tiny/base/small/...,默认 base;中文教程建议 small)
    #   --no-asr   跳过转录(只抽帧)
输出:
    out/frames/0001_00m12s.jpg ...    关键帧(已压到 1280 宽)
    out/transcript.json               whisper segments[{start,end,text}]
    out/transcript.txt                纯文本(已术语纠正)
    out/manifest.json                 帧清单+字幕+元信息(给 agent 读)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _find_ffmpeg() -> str:
    """定位 ffmpeg: 环境变量 > winget 绝对路径(glob) > PATH 探测。"""
    # 1. 显式指定
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    # 2. 常见绝对路径(沙箱下 PATH 短名执行可能被拒,优先绝对路径)
    import glob
    for pat in (
        r"C:/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe",
        r"C:/Program Files/ffmpeg/bin/ffmpeg.exe",
        r"D:/ffmpeg/bin/ffmpeg.exe",
    ):
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    # 3. PATH 探测(兜底)
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return "ffmpeg"
    except Exception as e:
        raise SystemExit(f"找不到 ffmpeg({e}),先安装: winget install Gyan.FFmpeg 或设 FFMPEG_PATH")


def _probe(ffmpeg_exe: str, video: Path) -> dict:
    """ffmpeg_exe: ffmpeg 可执行文件完整路径(用它推导同目录的 ffprobe)。"""
    ffprobe = str(ffmpeg_exe).replace("ffmpeg.exe", "ffprobe.exe")
    if ffprobe == str(ffmpeg_exe):  # 短名 "ffmpeg" 情况
        ffprobe = "ffprobe"
    r = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json",
                        "-show_format", "-show_streams", str(video)],
                       capture_output=True, text=True)
    info = json.loads(r.stdout or "{}")
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0) or 0)
    # 找视频流分辨率
    w = h = 0
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = int(s.get("width", 0)), int(s.get("height", 0))
            break
    return {"duration": duration, "width": w, "height": h}


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}m{s:02d}s"


# ---------------------------------------------------------------------------
# 步骤 1: 抽帧(场景检测 + 可选固定间隔兜底)
# ---------------------------------------------------------------------------
def extract_frames(video: Path, out_dir: Path, ffmpeg: str,
                   scene_thresh: float = 0.3, interval: int = 30,
                   max_frames: int = 200) -> list[dict]:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.jpg"):
        old.unlink()

    # 场景检测 + 间隔兜底(三条件 or):
    #   场景切换 | 距上次选中>=interval | 开头静止段(prev_selected_t=NaN)到 interval 秒
    # 注: gte(t-NaN) 返回 NaN(=false), 开头静止段必须用第三项单独覆盖
    if interval > 0:
        vf = f"select='gt(scene,{scene_thresh})+gte(t-prev_selected_t,{interval})+isnan(prev_selected_t)*gte(t,{interval})',showinfo,scale=1280:-2"
    else:
        vf = f"select='gt(scene,{scene_thresh})',showinfo,scale=1280:-2"
    cmd = [ffmpeg, "-hide_banner", "-i", str(video), "-vf", vf,
           "-vsync", "vfr", "-frames:v", str(max_frames),
           "-q:v", "3", str(frames_dir / "%04d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    # 解析 showinfo 的时间戳(与输出文件序号一一对应)
    times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr or "")]
    files = sorted(frames_dir.glob("*.jpg"))
    frames = []
    for i, f in enumerate(files):
        t = times[i] if i < len(times) else None
        stamp = _fmt_ts(t) if t is not None else f"{i+1:04d}"
        frames.append({"file": f.name, "t": t, "stamp": stamp})
    return frames


# ---------------------------------------------------------------------------
# 步骤 2: whisper 转录 + 术语纠正
# ---------------------------------------------------------------------------
def transcribe(video: Path, out_dir: Path, model_name: str = "base") -> list[dict]:
    import whisper  # 本机已装 openai-whisper
    audio = out_dir / "audio.wav"
    ffmpeg = _find_ffmpeg()
    subprocess.run([ffmpeg, "-hide_banner", "-y", "-i", str(video),
                    "-vn", "-ar", "16000", "-ac", "1", str(audio)],
                   capture_output=True)
    model = whisper.load_model(model_name)
    result = model.transcribe(str(audio), verbose=False)
    segments = [{"start": round(s["start"], 1), "end": round(s["end"], 1),
                 "text": s["text"].strip()}
                for s in result.get("segments", []) if s.get("text", "").strip()]
    try:
        audio.unlink()
    except Exception:
        pass
    return segments


def load_glossary() -> list[tuple[str, str]]:
    """Houdini 术语纠正表(源自 Houdini_agent,可自行扩展)。"""
    path = Path(__file__).parent / "houdini_glossary.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(c["from"], c["to"]) for c in data.get("corrections", []) if "from" in c]
    except Exception:
        return []


def parse_srt(srt_path: Path, last_line_only: bool = False) -> list[dict]:
    """解析 SRT 字幕 -> segments(与 whisper 输出同结构,可完全替代 ASR)。

    双语 SRT(如"原文\\n中文翻译")时 last_line_only=True 只留译文行。
    """
    raw = srt_path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\r?\n", raw.strip())
    segments = []

    def _ts_to_sec(ts: str) -> float:
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        # 找时间戳行(格式 00:00:07,318 --> 00:00:09,519)
        ts_line = next((l for l in lines if " --> " in l), None)
        if ts_line is None:
            continue
        try:
            start_s, end_s = ts_line.split("-->")
            start, end = _ts_to_sec(start_s.strip()), _ts_to_sec(end_s.strip())
        except Exception:
            continue
        # 时间戳行之后的都是文本
        text_lines = lines[lines.index(ts_line) + 1:]
        if last_line_only and len(text_lines) > 1:
            text_lines = text_lines[-1:]  # 双语字幕只留译文
        text = " ".join(t.strip() for t in text_lines).strip()
        if not text:
            continue
        segments.append({"start": round(start, 1), "end": round(end, 1), "text": text})
    return segments


def apply_glossary(text: str, corrections: list[tuple[str, str]]) -> str:
    for src, dst in corrections:
        text = re.sub(re.escape(src), dst, text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# 步骤 0(可选): yt-dlp 下载
# ---------------------------------------------------------------------------
def download(url: str, out_dir: Path) -> Path:
    try:
        import yt_dlp
    except ImportError:
        raise SystemExit("未装 yt-dlp: pip install yt-dlp")
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bv*[height<=720]+ba/b[height<=720]/b",  # 720p 足够读 UI
        "outtmpl": str(out_dir / "%(title).80s.%(ext)s"),
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        for ext in (".mp4", ".mkv", ".webm"):
            p = Path(path).with_suffix(ext)
            if p.exists():
                return p
    return Path(path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(video_path: str, out: str, scene: float = 0.3, interval: int = 30,
        model: str = "base", no_asr: bool = False,
        srt: str = "", srt_last: bool = False) -> dict:
    video = Path(video_path)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_ffmpeg()

    probe = _probe(ffmpeg, video)
    print(f"视频: {probe['width']}x{probe['height']}, 时长 {probe['duration']/60:.1f} 分钟")

    print("抽帧(场景检测)...")
    frames = extract_frames(video, out_dir, ffmpeg, scene, interval)
    print(f"  抽出 {len(frames)} 帧 -> {out_dir/'frames'}")

    segments = []
    if srt:
        # 有现成 SRT:直接解析(比 whisper 快且准),跳过 ASR
        print(f"解析 SRT 字幕: {srt}")
        segments = parse_srt(Path(srt), last_line_only=srt_last)
        no_asr = True
    elif not no_asr:
        print(f"转录(whisper {model})...")
        segments = transcribe(video, out_dir, model)

    # 术语纠正(两种来源都过一遍)
    if segments:
        corrections = load_glossary()
        for seg in segments:
            seg["text"] = apply_glossary(seg["text"], corrections)
        (out_dir / "transcript.json").write_text(
            json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / "transcript.txt").write_text(
            "\n".join(f"[{_fmt_ts(s['start'])}] {s['text']}" for s in segments),
            encoding="utf-8")
        src = "srt" if srt else "whisper"
        print(f"  {len(segments)} 段字幕({src}) -> transcript.json/txt")

    manifest = {
        "video": str(video),
        "duration_sec": probe["duration"],
        "transcript_source": "srt" if srt else ("whisper" if not no_asr else "none"),
        "frames": frames,
        "segments": segments,
        "note": "agent: 用 Read 逐帧看 frames/*.jpg(读节点图/参数面板), 对照 segments 时间戳, 生成教程笔记 md",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成: {out_dir/'manifest.json'}")
    print("下一步: 让 agent 读 manifest.json + frames/ 生成教程笔记")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="教程视频学习管线(提取侧)")
    ap.add_argument("video", help="视频文件路径或 URL(自动 yt-dlp)")
    ap.add_argument("-o", "--out", required=True, help="输出工作目录")
    ap.add_argument("--scene", type=float, default=0.3, help="场景检测阈值(默认 0.3)")
    ap.add_argument("--interval", type=int, default=30, help="兜底抽帧间隔秒(0=关,默认 30)")
    ap.add_argument("--model", default="base", help="whisper 模型(默认 base,中文建议 small)")
    ap.add_argument("--no-asr", action="store_true", help="跳过转录只抽帧")
    ap.add_argument("--srt", default="", help="SRT 字幕路径(提供则跳过 whisper,推荐)")
    ap.add_argument("--srt-last", action="store_true",
                    help="双语 SRT 只保留每段最后一行(译文行)")
    args = ap.parse_args()
    if re.match(r"https?://", args.video):
        args.video = str(download(args.video, Path(args.out)))
    run(args.video, args.out, args.scene, args.interval, args.model,
        args.no_asr, args.srt, args.srt_last)
