# -*- coding: utf-8 -*-
"""视口截图(flipbook 机制) -- 提取并适配自 Houdini-Agent-main client.py

用 flipbook 渲染当前 Scene Viewer 单帧 -> JPG/PNG,供视觉模型目视验证节点结果。
必须在主线程执行(bridge exec_python 天然在主线程;GUI 必须开着)。

用法(bridge exec_python / Python Shell):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import capture_viewport as cv
    r = cv.capture("/tmp/shot.jpg", width=1280, height=720)
    print(r)   # {"success": True, "path": ..., "base64": ..., "frame": ...}

    # 带保存路径:存文件;不带:只返回 base64(喂视觉模型)
"""
from __future__ import annotations

import base64
import glob
import os
import tempfile
import time
from typing import Any, Dict

import hou


def _find_scene_viewer():
    """优先 curDesktop 的 Scene Viewer,降级全局找"""
    viewer = None
    try:
        desktop = hou.ui.curDesktop()
        if desktop:
            viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    except Exception:
        pass
    if viewer is None:
        try:
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        except Exception:
            pass
    return viewer


def capture(output_path: str = "", width: int = 960, height: int = 540) -> Dict[str, Any]:
    """截取当前视口单帧。

    Args:
        output_path: 保存路径(空=只返回 base64);支持 $HIP 等变量
        width/height: 分辨率(160-1920 / 120-1080)
    """
    width = max(160, min(width, 1920))
    height = max(120, min(height, 1080))

    viewer = _find_scene_viewer()
    if viewer is None:
        return {"success": False,
                "error": "找不到 Scene Viewer 面板,请确保 GUI 开着且有 3D 视口"}

    current_frame = int(hou.frame())
    tmp_file = os.path.join(tempfile.gettempdir(),
                            f"houdini_viewport_{int(time.time() * 1000)}.jpg")

    try:
        flip = viewer.flipbookSettings().stash()
        flip.output(tmp_file)
        flip.frameRange((current_frame, current_frame))
        flip.resolution((width, height))
        flip.outputToMPlay(False)
        viewer.flipbook(viewer.curViewport(), flip)
    except Exception as e:
        return {"success": False, "error": f"Flipbook 截图失败: {e}"}

    if not os.path.exists(tmp_file):
        # flipbook 可能给文件名加帧号后缀
        candidates = sorted(glob.glob(tmp_file.replace(".jpg", "*.jpg")))
        if not candidates:
            return {"success": False, "error": "截图文件未生成,请检查视口状态"}
        tmp_file = candidates[0]

    with open(tmp_file, "rb") as f:
        img_bytes = f.read()
    if not img_bytes:
        return {"success": False, "error": "截图文件为空"}

    result: Dict[str, Any] = {
        "success": True,
        "frame": current_frame,
        "width": width,
        "height": height,
        "size_kb": round(len(img_bytes) / 1024, 1),
        "base64": base64.b64encode(img_bytes).decode("utf-8"),
    }
    # 视口/相机信息
    try:
        result["viewport"] = viewer.curViewport().name()
    except Exception:
        pass
    try:
        cam = viewer.curViewport().camera()
        if cam:
            result["camera"] = cam.path()
    except Exception:
        pass

    # 保存到目标路径(支持 Houdini 变量)
    if output_path:
        try:
            expanded = hou.text.expandString(output_path) if hasattr(hou, "text") else output_path
            os.makedirs(os.path.dirname(expanded) or ".", exist_ok=True)
            with open(expanded, "wb") as f:
                f.write(img_bytes)
            result["path"] = expanded
            result.pop("base64", None)  # 存了文件就不用拖着 base64
        except Exception as e:
            result["save_error"] = str(e)

    try:
        os.remove(tmp_file)
    except Exception:
        pass
    return result
