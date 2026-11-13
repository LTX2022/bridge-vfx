# 分辨率组合对照实验专项计划（2026-10-26）

状态：**计划+实现+聚焦测试已落盘（9/9）；待独立复核与用户条件授权后执行。**

## 目标

钉死 ITERATION26 发现的脱钩条件：同一重开宿主上，哪些操作能让组合的 RenderSettings `resolution` 采用节点参数值（128×128）而不是显示默认（2048×1152）。结果直接决定第 24 次修复的形态（重开后受控重设+证明，还是组合层改写）。

## 变体设计（单次 hython，全部内存内，不保存 HIP）

| 变体 | 操作 | 判定问题 |
|---|---|---|
| v1_baseline_tail | 按 render 节点 loppath（settings_binding）组合 + 逐层 dump resolution 意见归属 | 2048×1152 由哪一层 authoring |
| v1_baseline_karmasettings | 在 karmarendersettings 节点本身组合 | 该节点直接输出是否已脱钩 |
| v2_native_callback | 执行 res_mode 捕获回调（`updateResolutionParameters(hou.pwd())`，hou.cd 后 exec，与 HOM 菜单一致）后重组 | 回调是否使组合采用参数 |
| v3_resolution_menu | resolutionMenu 按钮捕获回调后重组 | 菜单路径差异 |
| v4_hom_set_128 | 解锁+删关键帧+set 128/128 后重组 | 参数重写是否足够 |
| v5_mode_manual | res_mode 重设 'manual' 后重组 | 模式重写是否足够 |

每个变体失败逐字段如实记录（不中断后续变体）；dump 头含 HIP 路径/版本；执行前后校验 HIP 字节不变。

## 边界与预算

复用渲染读回专项的全部治理（冻结快照、独立复核、条件授权原文、HMAC 账本、签名启停、STOP_UNKNOWN 失效封闭、1 次 hython/120s/512MiB/零重试）。授权原文为本次用户指令："继续下一步"。诊断结果不提升任何验收状态。
