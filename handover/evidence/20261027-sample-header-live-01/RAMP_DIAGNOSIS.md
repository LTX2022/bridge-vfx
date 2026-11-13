# Ramp 失败：现有证据的只读定位

日期：2026-10-27。范围：只读冻结 Python、既有诊断、原始存档静态成员与安装的 HOM/HDA 定义；未运行 Houdini、Nuke、sample、vmmap 或新增原生探测。Explore 任务 `agent_ba906583-37ab-432c-87b7-3f235502e558` 的只读结论与协调者直接核对的冻结 guard、序列化器及安装 HOM 文档一致。

## 已证明的失败条件

冻结根 `outputs/official-karma-disklight-h21-sample-header-20261027-01/project/control/snapshot/` 下：

- `packages/houdini-bridge/src/houdini_bridge/official_karma_native.py:252` 的 `parameter_value` 先执行 `native_value(parm.eval())`。
- kind 为 `Ramp` 时，只有序列化结果不是 dict 才在257行抛出 `OFFICIAL_NATIVE_RAMP_SHAPE_INVALID`。
- `native_value` 的90—92行把识别为 Ramp 的对象编码为含 basis、keys、values 的字典，没有点数检查。因此，已识别的空 Ramp 也会通过这一个 guard；不能由本次异常推断空 Ramp。
- traceback 从主节点捕获循环479行到 `capture_parameters` 311行再到257行。异常发生在主选定节点参数循环，不是 supplemental 捕获；保存 HIP 已完成，完整 observation 文件在函数返回后才写出，所以本轮没有部分观察结果。
- 现有诊断没有失败节点／参数名、原始求值类型、序列化类型或实际值。`diagnostics_incomplete=false` 只描述缓存消息采集完整，不表示参数观察成功。

## 候选参数与证据边界

Explore 静态核对原始 `.parm` 成员并按 source-contract 偏移核验：tonemapcurve 为31点且 tonemap 关闭，polyextrude1—4 的 thicknessramp／twistramp 为2点，color1／2 的颜色 ramp 为2点。安装 HDA 的静态 DialogScript 与相关默认值一致。隐藏和禁用参数仍纳入当前捕获。

这些参数只是候选；源存档点数、默认定义及遍历顺序不能证明运行时值或定位本次失败参数。不能把 tonemapcurve、color 或任意 polyextrude 认定为元凶。

## 最小候选修复方向，尚未实施

安装的 `/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/houdini/python3.11libs/hou.py:79294` 记录 `ParmTuple.evalAsRamps()` 返回包含 `hou.Ramp` 的 tuple，非 ramp 参数抛 TypeError。可将 Ramp 分支改为该明确类型 API，严格要求一项 Ramp，再生成现有单组件 payload；其他类型保留原路径。同时在异常上下文记录节点／参数／kind，以及有界的、已经求值的类型和形状，不额外求值。

该方向有 API 文档支持，但现有日志未证明 generic eval 本次具体返回什么，也未证明修后全链能通过。必要软件覆盖应包括浮点 ramp、颜色 ramp、错误返回形状及空值边界；本次只读定位未运行这些新增测试。

不得将本次修复改成放宽空 ramp：`official_karma_observation.py:170` 独立要求2—64个 keys，`official_karma_scene_host.py` 拒绝空 basis 并重建 `hou.Ramp`。空 ramp 的支持若被真实证据需要，属于另一项合同决定。

本次未修改生产源码、测试、冻结候选或目标；没有继任原生范围。当前停止和交付边界见 [真实结果](../../SAMPLE_HEADER_FULL_CHAIN_RESULT_20261027.md)。
