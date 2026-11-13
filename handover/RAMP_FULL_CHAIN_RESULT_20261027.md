# Ramp 修复后首次正式链结果（2026-10-27）

用户在本会话批准 review `0b493a61a54b5f868af6a1b9735cbfad3d3df4ab251078e09edbbf0a5373c41f`，授权原文为“允许。你一直做到任务完成吧”。独立正式范围为 `outputs/official-karma-disklight-h21-ramp-20261027-01`；范围已执行一次并失败关闭，不得继续或复用余额。

## 已认证结果

- 激活、账本及两个进程的 started、runtime-ready、stopped 回执均由冻结代码离线认证。无诊断或 DCC 子进程由结果验证器启动。
- `official-open-save`：PID 41222，退出 0，37.99800395965576 原生秒。真实 Ramp 捕获通过，产生完整观测。
- `official-cold-export`：PID 41593，退出 1，32.80227613449097 原生秒。
- 两个进程均 `owned_child_wait`，`descendant_result_unobserved=false`。范围 `NATIVE_SCOPE_EXECUTION_FAILED`，累计 2 启动／70.80028009414673 秒。
- 176 个冻结运行源文件保持哈希一致。目标目录认证时为 123592507 字节，未超 512 MiB。
- 工作 HIP 44773587 字节，SHA-256 `2eb98c327982cf3c6aa48c9b3cf4cdc1dea11e3eba215c170bd98f3127b5b12e`。独立进程已加载并完成观测，但严格冷开一致性验收失败，不能称作冷开验收通过。
- 官方实验组在旧 12 启动／222.56370401382446 秒基础上累计 14 启动／293.3639841079712 秒；球体范围29单独记账。

## 唯一已确认的冷热差异

`OFFICIAL_COLD_OBSERVATION_MISMATCH` 在 USD 导出前发生。比较两个已保存的完整 observation.json，只有以下一项 value 不同：

`/stage/lights/OUT_karma_lights` 的 `savetodirectory_directory`。

两次 raw_channels 都为 `$HOUDINI_TEMP_DIR/usd_renders/$RENDERID`，求值后分别包含 `usdrender_41222_2749_0` 与 `usdrender_41593_2742_0`。两次 `enableoutputprocessor_savetodirectory` 均为 0。其他观测项逐项相等。不能将缓存的其它章节错误认定为此不一致的原因。

最小软件修复：warm 工作副本保存前将此目录写为 frozen official_usd 的父目录；保持 processor=0，cold 阶段仅验证静态值及关闭状态，不修正 drift，不剔除任何观测字段。完整冷热相等合同、原始 HIP 和旧冻结原件均保留。

USD 导出、官方参考渲染、alpha、Bridge 重建/HIP/主渲染、NK/Nuke 独立渲染均未到达；人工视觉验收未到达。最终可用交付未完成。

## 证据

- [离线认证结果](evidence/20261027-ramp-live-01/result.json)
- [离线认证脚本](evidence/20261027-ramp-live-01/verify_result.py)
- 目标范围 `authorized-driver.log` 及两个 supervisor 目录保留原件，未修改签名回执或密钥。
