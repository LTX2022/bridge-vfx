# 对照实验结果与第 24 次修复（2026-10-26，ITERATION27）

状态：**对照实验专项执行成功（RESOLUTION_EXPERIMENT_PASSED，1 次 hython，HIP 字节未变），真凶钉死；第 24 次修复已实施，相关套件与基线 33 完全一致零新增。工程范围 07 待用户 TTY 授权后验证完整链。**

## 对照实验结果（evidence/20261026-resolution-experiment/readback-dump.json，sha256 7e4ab06f...）

| 变体 | 组合 resolution | 结论 |
|---|---|---|
| v1_baseline_tail（链尾 settings_binding） | 2048×1152 | 重开宿主复现 06 阻断 |
| **v1_baseline_karmasettings（karma 节点自身）** | **128×128** | **karma 组合正确，污染在下游** |
| v2 重跑 res_mode 原生回调 | 2048×1152 | karma 节点侧操作救不回链尾 |
| v3 resolutionMenu 回调 | 未执行（回调是 hscript opparm，非 Python） | 记录在案 |
| v4 HOM 写 karma 128/128 | 2048×1152 | 同上 |
| v5 res_mode 重设 manual | 2048×1152 | 同上 |

**逐层意见归属**：组合 stage 有两个 LOP 编辑层对 settings prim 著写 resolution——`2048×1080`（rendersettings LOP 出厂默认，capture 证实：resolution 默认 2048/1080、res_mode 默认 autoheight、resolution_control 默认 'set'）与更强的 `2048×1152`（autoheight 按相机纵横比推导）。karma 的 128×128 意见被 forceedit 覆盖。

**真凶**：`settings_binding`（Lop/rendersettings）以 forceedit 编辑同一 RenderSettings prim 时，用**自己的出厂分辨率参数**覆盖了 karmarendersettings 已正确著写的 128×128。初始化计划从未治理过 settings_binding 的分辨率参数。

## 第 24 次修复

`native_render_scene.parameter_plan` 增加：

```python
write("settings_binding", "res_mode", "manual", "menu", "gate"),
write("settings_binding", "resolution", tuple(scene["resolution"]), "intvector2"),
```

冻结场景读回（`_fx_frozen_scene_readback`）随之自动覆盖这两个字段（读回即证明）。孪生补 `Lop/rendersettings` 的 res_mode 运行时菜单（manual）与 resolutionx/y 出厂值 2048/1080（capture 同源）。`_fx_initialize_manual_resolution` 的触发点只认 `role=="settings"`，不受影响。

测试：`test_frozen_render_scene` 的冻结字段计数期望 36→38（新增两字段为合法计划增长，注释引用本迭代）；readback 11/11、bind 4/4、typed-save 3/3、诊断 9/9 通过；8 套件批次与基线 33 失败完全一致，零新增（stash 对照法验证）。

## 治理记录

- 实验专项：candidate（scope 5cc581aa）经独立复核 APPROVED → 用户条件授权（原文"继续下一步"）→ authorized（1a046804）→ 快照入口 + PYTHONEXECUTABLE 执行成功。
- v3 发现 resolutionMenu 回调为 hscript（`opparm . resolution ...`）——未来涉及菜单按钮的实验需按 hscript 执行。

## 下一步

prepare-successor 从母范围冻结含第 24 次修复的当前源码 → 工程范围 07 → 用户 TTY AUTHORIZE → 完整链（Alpha→建图→task_save→冷重开→husk 主渲染@128×128→controlled_output_v1→Nuke 闭环）。supervisor stub 绑定缝隙仍待用户决策（ITERATION26）。
