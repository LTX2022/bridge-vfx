#!/usr/bin/env python3
"""One read-only H21 resolution-composition experiment.

Loads a byte-verified HIP, then runs bounded in-memory variants that record
when the composed RenderSettings ``resolution`` opinion follows the node
parameters.  Nothing is saved, cooked or rendered; the only disk write is the
experiment dump.  Variant failures are recorded verbatim, never fatal.
"""
from __future__ import annotations

import json
import os


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        return repr(value)
    except Exception:
        return "<unreprable>"


def _resolution_fact(stage, settings_path):
    record = {}
    try:
        prim = stage.GetPrimAtPath(settings_path)
        record["prim_type"] = str(prim.GetTypeName()) if prim else None
        attribute = prim.GetAttribute("resolution") if prim else None
        if attribute and attribute.IsDefined():
            info = attribute.GetResolveInfo()
            record["value"] = _json_safe(attribute.Get(1))
            record["authored"] = bool(attribute.HasAuthoredValueOpinion())
            try:
                record["resolve_source"] = str(info.GetSourceType())
                record["resolve_layer"] = str(info.GetLayer().identifier)
            except Exception as error:
                record["resolve_info"] = "unavailable: " + repr(error)
        else:
            record["value"] = None
            record["authored"] = False
    except Exception as error:
        record["error"] = repr(error)
    return record


def _layer_spec_dump(stage, settings_path):
    """Which layer in the stage's layer stack holds which resolution opinion."""
    records = []
    try:
        for layer in stage.GetLayerStack():
            entry = {"layer": str(layer.identifier), "anonymous": layer.anonymous}
            try:
                prim_spec = layer.GetPrimAtPath(settings_path)
                attribute_spec = prim_spec.attributes.get("resolution") if prim_spec else None
                if attribute_spec is None:
                    entry["opinion"] = None
                else:
                    entry["opinion"] = {
                        "default": _json_safe(attribute_spec.default),
                        "time_samples": bool(attribute_spec.HasInfo("timeSamples")),
                    }
            except Exception as error:
                entry["opinion"] = "read-failed: " + repr(error)
            records.append(entry)
    except Exception as error:
        records.append({"error": repr(error)})
    return records


def _node_state(node):
    record = {}
    for name in ("res_mode", "resolutionx", "resolutiony"):
        try:
            parm = node.parm(name)
            record[name] = None if parm is None else {
                "value": _json_safe(parm.eval()),
                "expression": parm.expression(),
                "locked": bool(parm.isLocked()),
                "keyframes": len(parm.keyframes()),
            }
        except Exception as error:
            record[name] = {"error": repr(error)}
    return record


def _run_captured_callback(callback, node):
    """Execute a captured native script callback the way HOM menus do."""
    import hou
    if not callback or not callback.strip():
        raise RuntimeError("captured callback is empty")
    hou.cd(node.path())
    exec(compile(callback.strip(), "<captured-native-callback>", "exec"), {"hou": hou})


def main():
    hip_path = os.environ["RENDER_READBACK_HIP"]
    dump_path = os.environ["RENDER_READBACK_DUMP"]
    render_path = os.environ["RENDER_READBACK_RENDER_NODE"]
    import hou

    hou.hipFile.load(hip_path, suppress_save_prompt=True, ignore_load_warnings=True)
    render_node = hou.node(render_path)
    settings_node = hou.node(os.environ.get("RENDER_READBACK_SETTINGS_NODE") or "")
    settings_prim_path = str(render_node.parm("rendersettings").eval())
    tail_node = hou.node(str(render_node.parm("loppath").eval()))

    dump = {"schema": "bridge.resolution-experiment.dump/1",
            "houdini_version": hou.applicationVersionString(),
            "hip_path": hou.hipFile.path(), "settings_prim_path": settings_prim_path,
            "variants": {}}

    def compose(source_node, tag):
        variant = {"source": source_node.path() if source_node is not None else None}
        try:
            stage = source_node.stage(frame=1, apply_viewport_overrides=False, ignore_errors=False)
            variant["resolution"] = _resolution_fact(stage, settings_prim_path)
            if tag == "baseline":
                variant["layer_specs"] = _layer_spec_dump(stage, settings_prim_path)
        except Exception as error:
            variant["error"] = repr(error)
        return variant

    # V1 baseline: compose the saved scene as loaded, at the tail node and at
    # the karmarendersettings node itself.
    dump["variants"]["v1_baseline_tail"] = compose(tail_node, "baseline")
    dump["variants"]["v1_baseline_karmasettings"] = compose(settings_node, "plain")

    # V2 re-run the native manual-resolution callback on the karmarendersettings
    # node (the exact callable captured for res_mode), then recompose.
    try:
        mode_parm = settings_node.parm("res_mode")
        callback = mode_parm.parmTemplate().scriptCallback()
        _run_captured_callback(callback, settings_node)
        dump["variants"]["v2_native_callback"] = {
            "callback": callback, "node_state_after": _node_state(settings_node)}
        dump["variants"]["v2_native_callback"].update(compose(tail_node, "after"))
    except Exception as error:
        dump["variants"]["v2_native_callback"] = {"error": repr(error)}

    # V3 press the resolutionMenu button (its own captured callback), recompose.
    try:
        menu_button = settings_node.parm("resolutionMenu")
        if menu_button is None:
            raise RuntimeError("resolutionMenu button is absent")
        button_callback = menu_button.parmTemplate().scriptCallback()
        _run_captured_callback(button_callback, settings_node)
        dump["variants"]["v3_resolution_menu"] = {
            "callback": button_callback, "node_state_after": _node_state(settings_node)}
        dump["variants"]["v3_resolution_menu"].update(compose(tail_node, "after"))
    except Exception as error:
        dump["variants"]["v3_resolution_menu"] = {"error": repr(error)}

    # V4 explicit HOM write of 128/128 (in-memory only), recompose.
    try:
        for name, value in (("resolutionx", 128), ("resolutiony", 128)):
            parm = settings_node.parm(name)
            parm.lock(False)
            parm.deleteAllKeyframes()
            parm.set(value)
        dump["variants"]["v4_hom_set_128"] = {"node_state_after": _node_state(settings_node)}
        dump["variants"]["v4_hom_set_128"].update(compose(tail_node, "after"))
    except Exception as error:
        dump["variants"]["v4_hom_set_128"] = {"error": repr(error)}

    # V5 res_mode to manual via HOM then recompose (mode semantics probe).
    try:
        settings_node.parm("res_mode").set("manual")
        dump["variants"]["v5_mode_manual"] = {"node_state_after": _node_state(settings_node)}
        dump["variants"]["v5_mode_manual"].update(compose(tail_node, "after"))
    except Exception as error:
        dump["variants"]["v5_mode_manual"] = {"error": repr(error)}

    with open(dump_path, "w", encoding="utf-8") as stream:
        json.dump(dump, stream, ensure_ascii=False, sort_keys=True)
    summary = {name: (variant.get("resolution", {}).get("value") if isinstance(variant, dict) else None)
               for name, variant in dump["variants"].items()}
    print(json.dumps({"dumped": dump_path, "resolution_by_variant": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
