# PITFALL D - 火层被 HDRI 污染的救赎（完整版）

> 从 SKILL.md §3 拆出的完整流程（2026-08-25 P0 瘦身）。触发词与三行决策树在
> SKILL.md，本文件是执行细节全文：pre-check、Option A/C 完整 nuke_run 代码、
> 输出验证、gotchas。任务路由器「火 pass 混了 HDRI」行直读本文件。
> （2026-08-26 审计发现本文件被意外清空，已从会话记录全文重建。）

## 3. PITFALL D - salvage a fire pass contaminated by HDRI

**Trigger phrases**: "火 pass 混了 HDRI" / "fire pass 有背景" / "渲染火把
hdri 也渲进去了" / "alpha 里有蓝天".

**Root cause (Houdini side, see houdini-bridge 坑 D)**: the two domelights
(`domelight` + `sky_hdri`) didn't have Camera Visibility off, so Karma rendered
the environment map as an opaque background (alpha≈1 in the sky).

**Hard truth: this does NOT always work in Nuke.** The salvage only succeeds
when `render_scen` is the **same shot rendered WITHOUT the fire** - identical
camera, identical lights/environment, same exposure/resolution, and with a
transparent (or at least matching) background. In that special case:

- Model: `fire = E + T·scen`  (E = flame self-emission, T = smoke transmission).
- Clean premultiplied fire layer: `E = fire − T·scen`, `alpha = 1−T`.

If `render_scen` is an **opaque beauty** (alpha≈1 everywhere), or if the two
passes differ in exposure/lighting/geometry, subtraction will leave
background/tree/building artifacts. In that case, check whether the fire EXR
contains `combinedemission` + `combinedvolume` AOVs - if so, use **Option C**
below instead of any subtraction. If neither Option C nor the pre-checks for
subtraction are satisfied, stop and fix it in Houdini (Camera Visibility off +
Matte/Holdout) then re-render. SHOT_2 in this workspace was an example: the
`scen` pass was opaque and differently lit, so `fire − scen` left tree/rock
silhouettes, but the fire EXR's own AOVs still produced a clean fire element.

### Pre-check (mandatory - do this before building the graph)

1. **Resolution**: `fire` and `scen` must match. If `scen` is 4K and `fire` is
   1080p, add a `Reformat` on `scen` to match `fire` before subtraction.
2. **Scen alpha**: one frame of `render_scen` should NOT be fully opaque. If
   `iinfo` shows alpha mean ≈ 1 and 100% ≥0.999, the subtraction model is wrong
   for this data.
3. **Background match**: in a background pixel, `fire.rgb` should be nearly
   identical to `scen.rgb`. If they differ (different sky intensity, different
   geometry shading), subtraction will leave color fringes.

### Option A - one `nuke_run` call builds the graph (only if pre-checks pass)

Fill in `FIRE`, `SCEN`, `OUT`, `FIRST`, `LAST`, then call
`nuke_run(code=...)`. Single round-trip, one undo step, no clicking.

```python
# nuke is pre-injected; do NOT import it (keeps the AST guard happy)
FIRE = r"C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_1/render/render_fire/render_fire.%04d.exr"
SCEN = r"C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_1/render/render_scen/render_scen.%04d.exr"
OUT  = r"C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_1/render/render_fire_clean/render_fire_clean.%04d.exr"
FIRST, LAST = 1001, 1250

r_fire = nuke.createNode("Read", inpanel=False)
r_fire["file"].setValue(FIRE)
r_fire["first"].setValue(FIRST); r_fire["last"].setValue(LAST)
r_fire["origfirst"].setValue(FIRST); r_fire["origlast"].setValue(LAST)

r_scen = nuke.createNode("Read", inpanel=False)
r_scen["file"].setValue(SCEN)
r_scen["first"].setValue(FIRST); r_scen["last"].setValue(LAST)
r_scen["origfirst"].setValue(FIRST); r_scen["origlast"].setValue(LAST)

# If scen resolution differs from fire, uncomment this and wire r_scen through it:
# ref = nuke.createNode("Reformat", inpanel=False)
# ref["type"].setValue("scale")
# ref["scale"].setValue(0.5)          # e.g. 4K -> 1080p
# ref["filter"].setValue("Cubic")
# ref.setInput(0, r_scen)
# r_scen = ref

# T = f_lum / max(s_lum, 1e-4), clamped to [0,1]; dark scen (s_lum<=0.003) -> 1
# This is the per-pixel smoke transmission ratio, NOT (fire/scen per channel).
texpr = "((r1+g1+b1)/3 > 0.003) ? clamp(((r+g+b)/3) / max((r1+g1+b1)/3, 0.0001), 0, 1) : 1"
T = nuke.createNode("Expression", inpanel=False)
T["expr0"].setValue(texpr)
T["expr1"].setValue(texpr)
T["expr2"].setValue(texpr)
T.setInput(0, r_fire)
T.setInput(1, r_scen)

Tscen = nuke.createNode("Merge2", inpanel=False)
Tscen["operation"].setValue("multiply")
Tscen.setInput(0, r_scen); Tscen.setInput(1, T)

E = nuke.createNode("Merge2", inpanel=False)
E["operation"].setValue("minus")
E.setInput(0, r_fire); E.setInput(1, Tscen)

# clamp E >= 0
Eclip = nuke.createNode("Expression", inpanel=False)
Eclip["expr0"].setValue("max(r,0)")
Eclip["expr1"].setValue("max(g,0)")
Eclip["expr2"].setValue("max(b,0)")
Eclip.setInput(0, E)

# alpha = 1 - T  (r2 = T.red)
A = nuke.createNode("Expression", inpanel=False)
A["expr0"].setValue("r")
A["expr1"].setValue("g")
A["expr2"].setValue("b")
A["expr3"].setValue("1 - r2")
A.setInput(0, Eclip); A.setInput(1, T)

w = nuke.createNode("Write", inpanel=False)
w["file"].setValue(OUT)
w["file_type"].setValue("exr")
w["channels"].setValue("all")
w["create_directories"].setValue(True)
w.setInput(0, A)

__result__ = {"fire": r_fire.name(), "scen": r_scen.name(),
              "clean": A.name(), "write": w.name(),
              "first": FIRST, "last": LAST, "out": OUT}
```

Render one frame first, then check alpha stats before committing to the full
range:

```bash
# CLI
python -m nuke_bridge call render_write --json '{"node":"Write2","frame_range":"1001-1001","background":true}'
python -m nuke_bridge call verify_render --json '{"path_pattern":"<OUT pattern>","first":1001,"last":1001}'
```

Or foreground for a single frame via `nuke_run`:

```python
n = nuke.toNode("Write2")
nuke.execute(n, 1001, 1001, 1)
__result__ = {"executed": n.name(), "frame": 1001}
```

Only if the alpha check passes, render the full range with
`render_write(node="Write2", frame_range="1001-1250", background=true)` and
finish with `verify_render` on the whole range.

### Option B - step-by-step typed tools

Same nodes as above, created one at a time with `create_node` and
`connect_nodes`. Useful when the user wants to inspect each knob.

### Option C - AOV rescue (no `scen` subtraction needed)

If the fire EXR contains Karma's volume AOVs, the clean fire element is already
inside the pass - you don't need `render_scen` at all.

The two layers that matter:
- `combinedemission` - flame self-emission, already over black.
- `combinedvolume` - lit smoke/volume contribution, already over black (no HDRI
  background plate).

Clean premultiplied fire element:
- `rgb = combinedemission + combinedvolume`
- `alpha = clamp(luma(combinedemission + combinedvolume) * gain, 0, 1)`

`gain` (typically 2–4) maps the flame core to alpha≈1. Because the
sky/background has no fire contribution, alpha falls to 0 automatically - the
HDRI can never leak into alpha. If you prefer true optical density, use the
`density` AOV (if available) instead of luma.

One `nuke_run` graph:

```python
FIRE = r"C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_2/render/render_fire/render_fire.%04d.exr"
OUT  = r"C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_2/render/render_fire_clean/render_fire_clean.%04d.exr"
FIRST, LAST = 1001, 1250
GAIN = 3.0

r_fire = nuke.createNode("Read", inpanel=False)
r_fire["file"].setValue(FIRE)
r_fire["first"].setValue(FIRST); r_fire["last"].setValue(LAST)
r_fire["origfirst"].setValue(FIRST); r_fire["origlast"].setValue(LAST)

# Downscale 4K source to 1080p comp. Omit if comp is native 4K.
ref = nuke.createNode("Reformat", inpanel=False)
ref["type"].setValue("scale"); ref["scale"].setValue(0.5); ref["filter"].setValue("Cubic")
ref.setInput(0, r_fire)

lum = "0.2126*(combinedemission.red+combinedvolume.red)+0.7152*(combinedemission.green+combinedvolume.green)+0.0722*(combinedemission.blue+combinedvolume.blue)"
e = nuke.createNode("Expression", inpanel=False)
e["expr0"].setValue("combinedemission.red + combinedvolume.red")
e["expr1"].setValue("combinedemission.green + combinedvolume.green")
e["expr2"].setValue("combinedemission.blue + combinedvolume.blue")
e["expr3"].setValue("min(max((" + lum + ")*%s,0),1)" % GAIN)
e.setInput(0, ref)

w = nuke.createNode("Write", inpanel=False)
w["file"].setValue(OUT); w["file_type"].setValue("exr"); w["channels"].setValue("all")
w["create_directories"].setValue(True)
w.setInput(0, e)

__result__ = {"read": r_fire.name(), "reformat": ref.name(), "clean": e.name(), "write": w.name()}
```

Render one frame first, then inspect alpha visually. If the flame core is not
solid white, raise `GAIN`; if smoke edges are too hard, lower it.

**Advantages**
- No `scen` pass required.
- No subtraction artifacts.
- Impossible for HDRI/sky to appear in alpha, because alpha is derived only
  from fire's own AOVs.

Use Option C whenever `combinedemission` + `combinedvolume` are present. If they
are missing, fall back to Option A (strictly matched `scen` subtraction) or
accept that a Houdini-side fix + re-render is required.

### Verify before trusting the output

- Save one frame and inspect EXR alpha stats: sky/background pixels must have
  alpha ≈ 0. If alpha mean is still high, the pre-checks failed - stop.
- `screenshot(node=<write name>, frame=1100, max_long_edge=1600)` for a quick
  visual check: look for tree/rock/edge artifacts; if they appear, the passes
  are mismatched and this workflow won't save the shot.
- The batch/EXR-native reference is `fire_scen_subtract_salvage.py` in
  houdini-bridge `scripts/`. It uses the same math; run it headless on one
  frame first.

### Gotchas (don't skip)

- **The old per-channel `fire/scen` formula is wrong.** A previous version of
  this skill documented `T = clamp((r+g+b)/3, 0, 1)` applied to `fire/scen`.
  That inverts bright flame and has been corrected to the luminance-ratio
  formula above.
- **Subtracting only the `combinedvolume_domelight` + `combinedvolume_sky_hdri`
  AOVs is NOT enough** - that removes only HDRI's *lighting* on the smoke; the
  opaque background-sky pixels remain. Option C instead uses `combinedemission`
  + `combinedvolume`, which are the volume's own contribution over black and
  contain no background at all.
- **`render_write(background=True)` 已实测可用（2026-08-24，Nuke 17.0v1）**：
  3 帧后台渲染成功落盘，task_id 可用。注意 `render_status` 的
  `executing/progress` 对后台子进程渲染恒为 false/0（那是 GUI 进程自己的
  执行状态）--判断后台渲染是否完成靠 `verify_render` 查文件，别信 progress。
  旧版本"传字符串帧范围会失败请绕行 nuke_run 阻塞渲染"的警告已删除
  （addon 已构造 FrameRanges）。
  另注意 Windows 路径坑（实测）：Nuke Write 节点对**反斜杠**路径报
  "Can't write, Invalid argument"，正斜杠路径正常。bridge 的
  open_script/save_script/screenshot 已统一归一为正斜杠；自己写
  nuke_run 时也一律用 `C:/...` 正斜杠。
- **客户端自动发现已修复（2026-08-24）**：不再依赖 manifest 单一路径。
  并行端口扫描（~0.6s）在 manifest 丢失/被清理/目录不可解析时仍能自动找到
  listener；旧串行扫描在 Windows 上 2.5s 预算只够扫前 8 个端口，永远找不到
  offset > 8 的实例（`59555 + pid%100`）。`health`/所有工具调用/`list_instances`
  都有扫描回退（扫描从 nuke_ping 响应重建 pid/version/gui，所以在
  USERPROFILE/HOME 缺失的 MCP 进程环境里也能用）。`NUKE_BRIDGE_PORT` 现在
  仅用于手动指定。另注意：不要删 `~/.nuke/nuke_bridge_instances/` 里的
  `*.json`（那是实例注册表）。
- **manifest 反复消失的真凶（2026-08-25 NTFS 审计实锤）**：不是外部程序，
  是 addon 自己的 bug--`listener.py` 曾用 `nuke.addOnDestroy(_clear_manifest)`
  做"退出清理"，但该回调在**每次节点被销毁**时触发（不是进程退出时），于是
  任何 delete_node / screenshot 内部清理 / 用户在 GUI 按 Delete 都会顺手删掉
  manifest，在节点操作频繁的会话里表现为"manifest 永远不存在"。已改用
  `atexit`（真实进程退出钩子）并回归验证：删节点后 manifest 存活。教训：
  `nuke.addOnDestroy` 是节点级回调，别拿它当进程退出钩子用。
- **Premultiplication**: the output `(E, alpha=1−T)` is premultiplied and ready
  to `over` a background. Don't re-premultiply.
- **When in doubt, try Option C first.** AOV rescue is deterministic and cheap.
  If the required AOVs are missing, or the result still looks wrong, treat it as
  a failed rescue and fix it in Houdini (both domelights off, geometry matte)
  then re-render.

## 4. Cross-reference

- **houdini-bridge skill -> 坑 D**: the Houdini-side fix so the *next* render
  doesn't burn money again - turn off both domelights' Camera Visibility
  (`domelight` **and** `sky_hdri`, one is not enough) and set scene geometry to
  Matte/Holdout. Plus the 30-second pre-flight alpha check before sending to
  the farm.
- **`fire_scen_subtract_salvage.py`** (in houdini-bridge `scripts/`): the
  EXR-native batch version of this exact math (OpenEXR read/write), if you'd
  rather process 250 frames headless without Nuke open.
