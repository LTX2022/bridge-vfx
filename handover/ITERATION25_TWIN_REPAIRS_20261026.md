# 孪生语义修复与基线收敛（2026-10-26，ITERATION25）

状态：**软件孪生三类语义缺口已修复并推送（7d8ae06）；冻结基线失败 44→33；test_controlled_native_readback 11/11 首次全绿。只读诊断专项范围设计中。**

## 修复内容（无生产代码改动，全部对齐真实原生语义）

### 1. 原生脚本回调（tools/native_schema_test_boundary.py）

- `Template.scriptCallback()/scriptCallbackLanguage()`：从 capture 的 `tags_tokens` 读取（`docs/native-basis/hda-interface-capture.json` 是真实原生证据，res_mode 的回调就在其中，无需编造）。
- `Parm.pressButton()`：经显式 `hou._bridge_callback_environment` 执行捕获回调；无环境或回调缺失即失效关闭。
- `CallbackEnvironment.updateResolutionParameters`：逐行镜像 SideFX H21 `python3.11libs/loputils.py` 4210-4245——manual 解锁双分量并删表达式，autowidth/autoheight 将另一轴锁定在 `computeResolutionParameter` pythonexprf 驱动之后。**不发明任何分辨率值**。
- `Parm._components`（单分量）、`ParmTuple.__getitem__`、`node.updateParmStates`（显式 no-op）。

### 2. fake hou HIP 加载事件（packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py）

- 补 `hipFileEventType.AfterClear/AfterLoad` 与 `hou.LoadWarning`（真实类型）。
- load 事件序列补全为 addon 严格合同要求的 `BeforeLoad → BeforeClear → AfterClear → AfterLoad`。

### 3. 测试替身过期修正（tests/unit/test_controlled_native_readback.py）

- 两处"软件加载警告"从 `RuntimeError` 改为 `hou.LoadWarning`：冻结提交 117cb43（修复 #7）把第二次加载的门从 `except Exception` 收紧为 `except hou.LoadWarning`，测试必须用真实原生警告类型才能走到该路径。`assertRaises(RuntimeError)` 目标是 finalize 中断，不受影响。

## 结果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| test_controlled_native_readback | 0/15（setUp 全灭） | **11/11 全绿**（用例合并后） |
| 冻结基线 8 套件失败 | 44 | **33** |
| 新增失败 | — | 0 |

readback 首次全绿意味着：composed USD resolution 孪生校验、fake HIP 保存重开、严格加载事件序列、警告驱动的二次加载全部在孪生中可验证。

## 渲染阻断（composed USD resolution differs）状态

孪生侧的 authoring 路径已可验证，但孪生 USD 由参数直接构造，**无法复现真实 karmarendersettings 编译 LOP 的组合语义**；真实组合值仍未落盘。排除清单见 [ITERATION24_STATUS_20261026.md](ITERATION24_STATUS_20261026.md)。下一步：只读诊断专项（hython 只读打开 authorized-06 已保存 HIP，dump RenderSettings 已著属性），范围设计中，等用户授权。

## 剩余 33 个基线失败

清单在 /tmp/after_twin.txt（会话级），家族分布：project_environment（8）、production_task_hosts（2）、frozen_render_scene（1）等，属孪生其余缺口（project environment 事务、deployment 写入路径），留待后续逐家族修复。
