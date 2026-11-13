# 范围 06 执行结果与渲染阻断诊断（2026-10-26）

状态：**范围 06 真实执行推进到主渲染步；task_save/可信停止/正式冷重开首次全部真实通过（第 23 次修复在真实链路生效）。渲染步失效关闭于组合 USD 分辨率校验，根因尚未定位到可修复层。**

## 范围 06 真实执行记录（engineering-chain-20261025-authorized-06）

- 授权：用户 TTY 手输 `AUTHORIZE a0f4eb2e...`；scope `83e32e72`、bindings `6e97c04c`，快照 plugin_build `70613eff`（含第 22、23 次修复）。
- **通过**：Alpha（真实宿主）→ propose → build → **task_save（真实 HIP 落盘，第 23 次修复生效）** → houdini-initial 可信停止 → **正式全新进程冷重开**。
- **失败**：`houdini_render_bounded` 预检 `CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY: composed USD resolution differs`；closed_reason `ENGINEERING_DRIVER_FAILED`。未到达：husk 主渲染、controlled_output_v1 验证登记、Nuke 闭环。
- 剩余预算未耗尽即失败关闭；无拼接。

## 已排除的假设（全部来自真实落盘证据）

| 检查 | 证据 | 结论 |
|---|---|---|
| 节点参数 res_mode | 06 保存合同（graph 代与 task-save 代一致）：`manual` | 排除 autoheight 推导 |
| 节点分辨率 | 保存合同 `resolutionx=128 resolutiony=128`，frozen `[128,128]` | 节点级正确 |
| 表达式/锁定/关键帧 | 保存合同 channel：expression null、无 keyframes、unlocked | 排除回调残留驱动 |
| 该环境可渲染 128×128 | 06 alpha chart `uniform int2 resolution = (128, 128)` 真实 husk 渲出 | 排除环境限制 |
| 原生回调语义 | 离线读 `python3.11libs/loputils.py::updateResolutionParameters`：manual 分支仅解锁+删关键帧 | 与初始化流程一致 |

失败点：`_fx_controlled_output_readback` 中 `settings.GetAttribute('resolution').Get(frame)` ≠ `[128,128]`（或属性无效）；节点级同名检查在其之前已通过。剩余未知在 karmarendersettings 编译 LOP 的 USD 组合语义，无法离线读取，真实组合值未落盘（错误仅回传字符串）。

## 本轮其他交付

- `12979fa`：软件孪生补齐 H21 usdrender USD processor 参数族（第 21 轮 #8 的夹具欠账）。readback 套件全灭→11 失败；8 个基线套件失败清单不变。
- 第 23 次修复在真实链路验证：范围 06 的 task_save 与冷重开通过即为其真实通过证据。

## 下一步选项（需用户决定）

1. **只读诊断专项**（推荐）：新建最小授权范围，hython 只读打开 06 已保存 HIP（`project/saves/task-save-c7ac4c49....hip`），组合 stage 后 dump RenderSettings 全部已著属性（含 resolution 实际值/类型/著写状态）。约 1 次 DCC 启动、数十秒，直接给出组合值，随后即可设计精确修复。
2. 继续软件孪生修复（Template 回调元数据、pressButton、loputils 替身、USD authoring）：可加固测试边界，但孪生 USD 由参数直接 author，无法复现真实 LOP 组合语义，不能揭示真实组合值。
3. 暂停：保留全部证据，等外部输入（如 SideFX 官方文档对 karmarendersettings→USD resolution 著写规则的说明）。

剩余 readback 11 失败（reopen/hda-policy/manual-resolution 回调链）与基线 44 失败清单不变。
