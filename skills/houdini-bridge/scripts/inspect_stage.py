# -*- coding: utf-8 -*-
"""USD Stage 内省(session 级,纯只读) -- 提取并适配自 Houdini_agent bridge_v2 inspect_stage

与 usd_verify_merged.py(文件级校验)互补:这个查**LOP 节点输出的活动 stage**--
prim 真实状态/材质绑定/材质输出网络/PointInstancer 解析/shader 属性(info:id、inputs:file)。

用法(bridge exec_python / Python Shell,需 Houdini):
    import sys; sys.path.insert(0, r"C:/Users/<USERNAME>/.zcode/skills/houdini-bridge/scripts")
    import inspect_stage as ist
    r = ist.inspect("/obj/RENDER/fire_loaded")                     # 层信息+default prim
    r = ist.inspect("/obj/RENDER/OUT_SCENE",
                    prim_paths=["/Fire/volume_0"],                  # 查指定 prim
                    find_materials=True, find_bindings=True)        # 全 stage 材质扫描
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def inspect(node_path: str,
            prim_paths: List[str] | None = None,
            find_materials: bool = False,
            find_bindings: bool = False) -> Dict[str, Any]:
    """查询 LOP 节点输出的 USD stage。纯只读,不 cook 不改场景。"""
    import hou
    from pxr import Usd, UsdShade, UsdGeom

    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"节点不存在: {node_path}")
    if not hasattr(node, "stage"):
        raise ValueError(f"节点 {node_path} 没有 stage() 方法,不是 LOP 节点")
    stage = node.stage()
    if stage is None:
        raise ValueError("stage 为空(节点可能没 cook 或输入缺失)")

    result: Dict[str, Any] = {
        "node": node_path,
        "prims": {},
        "materials_found": [],
        "bindings_found": [],
    }
    try:
        result["stage_layer_count"] = len(stage.GetLayerStack())
    except Exception:
        pass
    try:
        dp = stage.GetDefaultPrim()
        if dp and dp.IsValid():
            result["stage_default_prim"] = dp.GetPath().pathString
    except Exception:
        pass

    # ---- 指定 prim 逐个查 ----
    for pp in (prim_paths or []):
        prim = stage.GetPrimAtPath(pp)
        if not prim or not prim.IsValid():
            result["prims"][pp] = {"exists": False}
            continue
        info: Dict[str, Any] = {
            "exists": True,
            "type": prim.GetTypeName(),
            "active": prim.IsActive(),
        }
        # 材质绑定
        try:
            binding = UsdShade.MaterialBindingAPI(prim)
            direct = binding.GetDirectBinding()
            info["material_binding"] = (
                {"path": direct.GetMaterial().GetPath().pathString,
                 "purpose": direct.GetMaterialPurpose()}
                if direct and direct.GetMaterial() else None
            )
        except Exception as exc:
            info["material_binding_error"] = str(exc)
        # prim 本身是材质:看输出网络
        try:
            if prim.IsA(UsdShade.Material):
                mat = UsdShade.Material(prim)
                info["is_material"] = True
                outputs = []
                for out in mat.GetOutputs():
                    try:
                        conn = out.GetConnectedSource()
                        outputs.append({
                            "name": out.GetBaseName(),
                            "connected_to": conn[0].GetPath().pathString if conn and conn[0] else None,
                        })
                    except Exception:
                        pass
                info["material_outputs"] = outputs
        except Exception:
            pass
        # 子 prim(最多 20)
        try:
            info["children"] = [
                {"path": c.GetPath().pathString, "type": c.GetTypeName()}
                for c in prim.GetChildren()
            ][:20]
        except Exception:
            pass
        # PointInstancer 深度解析
        if str(prim.GetTypeName()) == "PointInstancer":
            try:
                pi = UsdGeom.PointInstancer(prim)
                info["prototypes"] = [str(p.pathString) for p in pi.GetPrototypesRel().GetTargets()]
                pos = pi.GetPositionsAttr()
                if pos:
                    positions = pos.Get()
                    info["positions_count"] = len(positions) if positions is not None else 0
                    if positions:
                        info["positions_sample_first"] = [list(p) for p in positions[:5]]
                        info["positions_sample_last"] = [list(p) for p in positions[-3:]]
                # protoIndices:统计每个 prototype 被用几次
                idx_attr = pi.GetProtoIndicesAttr()
                if idx_attr:
                    indices = idx_attr.Get()
                    if indices is not None:
                        counts: Dict[int, int] = {}
                        for i in indices:
                            counts[int(i)] = counts.get(int(i), 0) + 1
                        info["proto_usage"] = {str(k): v for k, v in sorted(counts.items())}
                # 被隐藏的实例
                try:
                    inactive = pi.GetInactiveIdsAttr()
                    if inactive:
                        ids = inactive.Get()
                        info["inactive_ids_count"] = len(ids) if ids is not None else 0
                except Exception:
                    pass
            except Exception as exc:
                info["instancer_error"] = str(exc)
        # 属性摘要(前 50 个,含 shader 的 info:id / inputs:file)
        attrs: Dict[str, Any] = {}
        try:
            for attr in prim.GetAttributes():
                if len(attrs) >= 50:
                    break
                name = attr.GetName()
                try:
                    val = attr.Get()
                except Exception:
                    continue
                if val is None:
                    continue
                if isinstance(val, (int, float, str, bool)):
                    attrs[name] = val
                elif isinstance(val, (tuple, list)) and len(str(val)) < 120:
                    attrs[name] = str(val)
            info["attributes"] = attrs
        except Exception:
            pass
        result["prims"][pp] = info

    # ---- 全 stage 材质扫描 ----
    if find_materials:
        try:
            for prim in stage.Traverse():
                if prim.IsA(UsdShade.Material):
                    result["materials_found"].append(prim.GetPath().pathString)
        except Exception:
            pass

    # ---- 全 stage 绑定关系扫描 ----
    if find_bindings:
        try:
            for prim in stage.Traverse():
                try:
                    binding = UsdShade.MaterialBindingAPI(prim)
                    direct = binding.GetDirectBinding()
                    if direct and direct.GetMaterial():
                        result["bindings_found"].append({
                            "prim": prim.GetPath().pathString,
                            "material": direct.GetMaterial().GetPath().pathString,
                        })
                except Exception:
                    continue
        except Exception:
            pass

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pp = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    out = inspect(sys.argv[1], prim_paths=pp)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
