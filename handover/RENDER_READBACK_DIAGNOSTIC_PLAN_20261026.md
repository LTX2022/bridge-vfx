# 只读渲染配置读回专项计划（2026-10-26）

状态：**计划+实现+聚焦测试已落盘；等待独立复核与用户条件授权后执行。**

## 目标与边界

只读诊断一个事实：authorized-06 已保存 HIP 中，karmarendersettings 编译 LOP 组合出的 RenderSettings prim 的 `resolution` 属性实际是什么（值、类型、著写状态、时间变异性）。该事实直接决定 `CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY: composed USD resolution differs` 的精确修复层。

- **只读**：hython 只 `hipFile.load`，不保存、不 cook、不渲染、不仿真、不写任务树（唯一输出为 dump JSON）。
- **输入**：authorized-06 正式 typed 保存 HIP `project/saves/task-save-c7ac4c49fb1e4edca8a1d0ea9e99d291.hip`（sha256 `52452cc2...`）及其 scene_contract（`d62b7b58...`），render/settings 角色路径从合同读取并绑定。
- **预算**：外层沿用标准 scope 预算（8/600s schema 硬约束），本工具内层收紧为 1 次 hython 启动、单次 120s、512MiB、零重试；第二次启动、超时、停止未知即封闭。
- **不改变**：生产门禁、工程链验收状态、范围 04/05/06 的关闭结论。诊断结果不提升任何验收，只用于设计下一修复。

## 入口与流程（tools/run_render_readback_diagnostic.py + tools/render_readback_host.py）

1. `prepare`：冻结当前源码到新目录（纯复制），字节校验 HIP/合同库/宿主二进制/OCIO 配置，写 scope/freeze/configuration；不启动 DCC。
2. 独立复核：复核者核对计划、入口、冻结内容、0 启动预检，写 `bridge.render-readback.review/1` decision=APPROVED（含候选绑定与源摘要）。
3. 条件授权：用户指令原文（"你全都可以做，做过的记得写下到文档一起提交"）记录为 `bridge.render-readback.conditional-authorization/1`，绑定同一 review。
4. `activate`：受信控制端核对 review+授权与候选绑定一致后在目标根初始化已授权 scope（HMAC 账本、签名启停）。
5. `execute`：单阶段——GraphScheduler 预留→owned_process 启动 hython 运行冻结的 `render_readback_host.py`（env 传入 HIP 路径/render 与 settings 节点路径/dump 输出路径）→ dump 落盘后宿主自退，supervisor 观察退出并产生签名 started/stopped 回执（挂死路径走 terminate→STOP_UNKNOWN 失效封闭）→ 校验 dump 头/prim/resolution 记录存在→**校验 HIP sha256 执行前后不变**→校验预算→封闭 `RENDER_READBACK_DIAGNOSTIC_TERMINAL_CLOSED`。

注：`lop.stage()` 的 stage 组合是读取该事实的必要手段（纯内存，无落盘）；除 dump 文件外诊断不写任何任务树内容。

## dump 内容（bridge.render-readback.dump/1）

- render 节点全部关键参数通道（loppath/rendersettings/override_camera/renderer/outputimage 的值/表达式/锁定/关键帧）。
- settings LOP 节点 res_mode/resolutionx/resolutiony/resolution/engine/denoiser/enablemblur/pixelAspectRatio/camera/picture 的同上通道。
- RenderSettings prim 全部已著属性（名称/类型/值@frame1/HasAuthoredValueOpinion/ValueMightBeTimeVarying/variability）与全部关系（含 forwarded targets）。
- /Render 子树前 64 个 prim 的同格式 dump（product/var 链）。

## 软件覆盖（分层，聚焦）

聚焦单测：save_entry 唯一匹配、dump 校验拒绝路径（头/prim/resolution 缺失）、admission 拒绝（已用/已关闭）、activate 的 review/授权绑定拒绝。完整单进程集成由本次有界原生诊断本身验证。

## 结果处理

dump 落盘后：分析真实组合值 → 在软件孪生中复现该组合语义（如可）→ 设计并实施第 24 次修复 → 新工程范围（07）验证完整链。诊断 HIP 不修改，06 范围证据原样保留。
