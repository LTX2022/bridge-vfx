# G03 R04/R05 当前独立闭合结论

结论：**PASS_SCOPED。R04、R05 及实际 transition writer 落盘后抛错边界关闭。** 当前限定范围没有剩余阻断。审查者现已停写，可以归档本目录并生成索引；旧 BLOCKED 报告和原始失败 probes 全部保留。

仅复核受影响恢复授权、completion 捕获/撤销和 reconciliation，不重新执行旧正常/R01–R03、正式 process 或全量，不扩大为全域验收。生产、controller、tests 均未由审查者修改。

## 最终源码 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| plugins/houdini/_impl/houdini_bridge_addon.py | 05c284487228c272cc88beadc500812f8595c812a66ac6549481e2d3ac03df98 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py | 83ef5a483b431b93adf258692dc8a16e359602a24dde8f366613b6aec4fa8281 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | f826519d323fef99564a56f9cff38c7487fa08882ebb17196b4de891ac1adc4e |
| tests/unit/test_geometry_reopen_addon.py | b3afe27bccbf945040523f9baab8a59aede7a7a7847ee882579232505e628de5 |

上述 SHA 在独立运行前后相同，并与中心 fixes-final、formal-current 报告及当前文件匹配。机器摘要：`focused-summary-v1.json`。

## 独立观察

实际命令：`.venv/Scripts/python.exe -B outputs/geometry-reopen-20261013-review/focused_probe.py`。

5 场景 × 两版本，共 **10 次观察全部符合预期**；exit=0、source_unchanged=true、无 probe_error。原始证据：`focused-probe-v1.json`，SHA-256 `49f2d431e82bc4f750097f464ebd07bd02328e4aed759bce03ff9995f95c63c2`。该 JSON 还绑定诊断脚本和复用 helper 的 SHA、实际命令、解释器及系统版本。

| 场景 | 两版实际结果 |
| --- | --- |
| R04：真实 completion 落盘后 launch_nonce 漂移 | SCENE_STATE_DRIFT；本操作回到 INTENT，无当前 authority，scope/transactions 清空；reconcile 拒绝；save-store 字节及 runner generation 恢复 |
| R05：输入漂移拒绝后，当前 embedded manifest 和 sidecar 缺失 | GEOMETRY_REOPEN_RECONCILIATION_UNPROVEN；维持 INTENT，无当前 authority，未补签成功 |
| native writer 实际写 completion 后抛 OSError | 不依赖 completion wrapper 返回值，仍能撤销本次已落盘记录；INTENT、无 authority、CAS 递增、回执摘要有效、save-store/generation 恢复；reconcile 拒绝 |
| native writer 实际写 completion 后 nonce 漂移并抛 OSError | 同样撤销本次 exact completion；当前身份漂移不阻止回滚；其余清理与持久化恢复成立 |
| 已捕获 record 之后出现另一条不同 CAS/after_identity 的有效摘要 record | 私有 rollback guard 不撤销该替代记录；record 和新 CAS 原样保留 |

前三类恢复失败观察及 native writer 两场景都经实际 addon/底层 HOM fixture；writer 故障注入位于 `runner._save`，先执行真实 `_save` 再抛错，不制造成功回执。最后一项是显式替代 record 的私有 guard 负向 fixture，不冒充真实并发 writer 或进程生命周期证明。

## 实现复核要点

- `_fx_scene_transition_complete` 在自身实现中，写入前向 exact task/scope/operation 的私有 completion cell 深拷贝实际 completed record；当前 identity 已不匹配时先拒绝。捕获不依赖外部 wrapper 的返回。
- `_fx_geometry_restore_transition_intent` 仅在 current record 与捕获 record 完全一致、当前回执摘要有效时撤销；比较涵盖 record CAS 和 after_identity。它不再以已经漂移的当前 identity 阻止本次撤销，也不撤销另一条新 record。
- `_fx_geometry_reconcile_checkpoint` 先核验 operation 的 exact path/hash 对应 save contract，按可信 saved checkpoint 决定是否要求 G03。要求 G03 时，当前 root/manifest/domain/checkpoint 缺失或不符显式拒绝，不进入 False 的普通链分支。真实 registry checkpoint、saved contract 和参数一致性校验继续保留。

## 当前中心及正式证据

只读核验主 agent 已完成报告，未由 reviewer 重跑：

| 报告 | 实际结果 |
| --- | --- |
| geometry-reopen-20261013-fixes-final.json | 36 methods，0 failure/error/skip，exit 0，125.016 秒，source_unchanged=true |
| geometry-reopen-20261013-formal-current.json | 1 method 两版本，0 failure/error/skip，exit 0；JSON 的实际 runner elapsed 为 100.453 秒，source_unchanged=true |

两版 formal-current snapshot-manifest 各 134 条源码与当前文件比较，0 drift；两份 manifest 的 SHA 均为 `b99b3dddb3d0e13dcea418d91ef06a498d3a3c9c8b3f694ce58f2a7d8573f9bc`。

实际 lifecycle：H21 PID 36052→21416，H22 PID 33364→16968；stop confirmed、nonce 改变、registry restored=true，实际前后参数相同，直接 readback=3。两版归档 `rest-input-original.json` 的 SHA/长度与 saved checkpoint.manifest 相符，host_after.plugin_build 与本结论 addon SHA 相同。

正式 readback 仍明确是 **BLOCKED/parameters_only**。实际变形、downstream、crossframe 未在本次闭合；本结论不改变这些缺口，不代表全域、真实 DCC、模型或视觉验收。

## 归档状态

当前有效结论是本 `CURRENT_CLOSURE.md` 和 `focused-summary-v1.json`；原始独立观察为 `focused-probe-v1.json`。旧 `REVIEW.md`、`FINAL_CLOSURE.md`、旧 summary/probe 作为历史原件保留，不能将其旧 SHA 与当前结论混计。审查者已停写，不再追加无新风险验证或修改审查材料。
