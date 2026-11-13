#!/usr/bin/env python3
"""Thin read-only H21 render-configuration readback host.

Runs inside a supervised hython.  Loads one byte-verified HIP, composes the
LOP stage at frame 1 and dumps the composed RenderSettings configuration
verbatim.  It never saves the HIP, never cooks, renders or simulates, and
never writes inside the task tree except its single output dump file.
"""
from __future__ import annotations

import json
import os
import sys


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        return repr(value)
    except Exception:
        return "<unreprable>"


def _attribute_record(attribute, frame):
    record = {"typeName": str(attribute.GetTypeName())}
    try:
        record["variability"] = str(attribute.GetVariability())
    except Exception as error:
        record["variability"] = "unavailable: " + repr(error)
    try:
        record["authored"] = bool(attribute.HasAuthoredValueOpinion())
    except Exception as error:
        record["authored"] = "unavailable: " + repr(error)
    try:
        record["time_varying"] = bool(attribute.ValueMightBeTimeVarying())
    except Exception as error:
        record["time_varying"] = "unavailable: " + repr(error)
    try:
        record["value"] = _json_safe(attribute.Get(frame))
    except Exception as error:
        record["value"] = "get-failed: " + repr(error)
    return record


def _dump_stage_prim(prim, frame):
    record = {"path": str(prim.GetPath()), "typeName": str(prim.GetTypeName()),
              "active": bool(prim.IsActive())}
    record["attributes"] = {attribute.GetName(): _attribute_record(attribute, frame)
                            for attribute in prim.GetAttributes()}
    record["relationships"] = {}
    for relationship in prim.GetRelationships():
        targets = []
        try:
            targets = [str(target) for target in relationship.GetTargets()]
            forwarded = [str(target) for target in relationship.GetForwardedTargets()]
        except Exception as error:
            targets = ["read-failed: " + repr(error)]
            forwarded = []
        record["relationships"][relationship.GetName()] = {"targets": targets,
                                                           "forwarded_targets": forwarded}
    return record


def _parm_channel_record(parm):
    """Read every channel field independently; failures are recorded verbatim."""
    if parm is None:
        return None
    record = {}
    for field, read in (
            ("value", lambda: _json_safe(parm.eval())),
            ("expression", lambda: parm.expression()),
            ("language", lambda: str(parm.expressionLanguage())),
            ("locked", lambda: bool(parm.isLocked())),
            ("keyframes", lambda: len(parm.keyframes())),
            ("template_type", lambda: str(parm.parmTemplate().type())),
            ("unexpanded", lambda: parm.unexpandedString()),
    ):
        try:
            record[field] = read()
        except Exception as error:
            record[field] = "unavailable: " + repr(error)
    return record


def main():
    hip_path = os.environ["RENDER_READBACK_HIP"]
    dump_path = os.environ["RENDER_READBACK_DUMP"]
    render_path = os.environ["RENDER_READBACK_RENDER_NODE"]
    frame = 1
    import hou

    hou.hipFile.load(hip_path, suppress_save_prompt=True, ignore_load_warnings=True)
    node = hou.node(render_path)
    dump = {
        "schema": "bridge.render-readback.dump/1",
        "houdini_version": hou.applicationVersionString(),
        "hip_path": hou.hipFile.path(),
        "frame": frame,
        "render_node": None if node is None else {
            "path": node.path(), "type": node.type().nameWithCategory(),
            "parameters": {name: _parm_channel_record(node.parm(name))
                           for name in ("loppath", "rendersettings", "override_camera",
                                        "renderer", "outputimage")}},
        "settings_node": _settings_node_record(os.environ.get("RENDER_READBACK_SETTINGS_NODE")),
        "lop_node": None, "render_settings_prim": None, "render_scope": [],
    }
    try:
        parameters = (dump["render_node"] or {}).get("parameters") or {}
        lop_value = parameters.get("loppath") or {}
        lop_path = lop_value.get("value") if isinstance(lop_value, dict) else None
        if not isinstance(lop_path, str) or not lop_path:
            raise RuntimeError("loppath value is not an addressable string: " + repr(lop_value))
        lop = hou.node(lop_path)
        if lop is None:
            raise RuntimeError("loppath does not resolve to a node: " + repr(lop_path))
        dump["lop_node"] = {"path": lop.path(), "type": lop.type().nameWithCategory()}
        settings_value = parameters.get("rendersettings") or {}
        settings_path = settings_value.get("value") if isinstance(settings_value, dict) else None
        stage = lop.stage(frame=frame, apply_viewport_overrides=False, ignore_errors=False)
        settings_prim = stage.GetPrimAtPath(str(settings_path))
        if not settings_prim or settings_prim.GetTypeName() != "RenderSettings":
            raise RuntimeError("rendersettings does not compose to a RenderSettings prim: "
                               + repr(settings_path))
        dump["render_settings_prim"] = _dump_stage_prim(settings_prim, frame)
        dump["render_scope"] = [_dump_stage_prim(prim, frame) for prim in stage.Traverse()
                                if str(prim.GetPath()).startswith("/Render")][:64]
    except Exception as error:
        dump["composition_error"] = repr(error)
    with open(dump_path, "w", encoding="utf-8") as stream:
        json.dump(dump, stream, ensure_ascii=False, sort_keys=True)
    prim = dump.get("render_settings_prim") or {}
    print(json.dumps({"dumped": dump_path, "composition_error": dump.get("composition_error"),
                      "resolution": (prim.get("attributes") or {}).get("resolution")},
                     ensure_ascii=False))


def _settings_node_record(path):
    if not path:
        return None
    import hou
    node = hou.node(path)
    if node is None:
        return {"path": path, "present": False}
    names = ("res_mode", "resolutionx", "resolutiony", "resolution", "engine", "denoiser",
             "enablemblur", "pixelAspectRatio", "camera", "picture")
    return {"path": path, "present": True,
            "parameters": {name: _parm_channel_record(node.parm(name)) for name in names}}


if __name__ == "__main__":
    main()
