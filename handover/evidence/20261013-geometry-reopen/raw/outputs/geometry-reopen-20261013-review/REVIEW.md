# G03 恢复 authority 独立只读复核

结论：当前冻结版本存在 3 项具体阻断，不能签发本轮恢复链闭合。审查者未改生产、controller 副本或 tests；仅在本目录保存诊断代码及原始观察。没有执行正式 process 或全量测试。

## 冻结源码绑定

两次有效定向观察的 `source_unchanged=true`，对应同一源码：

| 文件 | SHA-256 |
| --- | --- |
| plugins/houdini/_impl/houdini_bridge_addon.py | 58ae9c9cddbf6388e9fbb1e988cc7948262bbecb76843356a7813f3d98e4a0b4 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py | 83ef5a483b431b93adf258692dc8a16e359602a24dde8f366613b6aec4fa8281 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | f826519d323fef99564a56f9cff38c7487fa08882ebb17196b4de891ac1adc4e |
| tests/unit/test_geometry_reopen_addon.py | 351266b7ee5edfe16a366af2cbf4098a7f0565e5b8d6447b13bdfc749e85826a |

## G03-R01 / P1：transition 持久化失败发生在 authority 提交之后

触发点：addon:3728 的 `_fx_geometry_rebind_saved_contract` 返回时，内层 transaction 已在 addon:3706 `registry.end(token, commit=True)`；随后 `scene_reopen_task_hip` 才在 addon:14724 调用 `_fx_scene_transition_complete`。

实际 build → apply(.3) → save → 清除旧 registry → reopen，唯一故障注入是 completion 持久化函数抛 OSError。两版均返回异常，但保留 1 个当前 committed cohort；`_fx_geometry_host().observations` 仍能验证 .3 的 parameters_only authority，durable transition 仍是 INTENT。active transaction 为 0，不能再通过原 token 回滚。scope 清空本身没有解决已提交 cohort 的留存。

证据：`probe-v2.json` 的 `completion_write_failure`，H21.0.631 / H22.0.429。这证明 addon 异常路径留下当前 authority，不证明控制端已经接受成功或真实输出可用。

整改应把 caller 的必要持久化/完成确认纳入同一个可回滚的恢复生命周期，或建立显式持久化的 pending 恢复状态并拒绝其写 authority。不要简单在 finally 清空所有任务的 registry。反例需在回执落盘失败后同时检查 scope、transactions、当前 committed cohort、当前 observations 及恢复重试。

## G03-R02 / P1：G03 恢复拒绝可以被通用 transition reconciliation 改为 COMPLETED

触发点：addon:14686 先写新 `active_scene`，接着转移 ACTIVE 租约，addon:14717 才认证 G03 checkpoint/冻结输入。认证失败仍留下普通 scene transition INTENT。addon:12612 `_fx_scene_transition_reconcile` 只检查 epoch + HIP snapshot，并在 addon:12639 补签完成，没有验证该 `scene.reopen_task_hip` 的 G03 恢复前置条件或拒绝事实。

实际 build → apply(.3) → save → 清除旧 registry；显式更换同 PID 的 nonce/session/generation，修改 rest 输入末字节且长度不变。reopen 两版均报 `GEOMETRY_REST_INPUT_CHANGED`；当前 authority 不存在，但 lease 已从旧 session/generation/epoch 转移到新值，saves.active_scene 也已写新身份。紧接着调用实际 `scene.reconcile_transition`：两版均返回 `reconciled=true`、state=COMPLETED，G03 registry 仍不存在。

证据：`probe-v2.json` 的 `input_drift_then_reconcile`。这里的身份变更是组件内显式模拟，不是 save→stop→实际新 PID 的进程验收。没有构造成功回执；COMPLETED 由实际 addon 产生。

必须区分“确实加载了该 HIP”与“本恢复操作全部前置条件成立”；可以保留真实加载事实，但不能把已拒绝/未完成的 G03 恢复补签为完整完成。失败后已发生的租约与 active_scene 变更也应有可审计的 pending/失败状态，不能依赖一次 generic epoch 检查。补反例应核验通用 reconcile 在持续输入漂移、checkpoint 缺失、登记确认失败时继续拒绝。

## G03-R03 / P2：graph_bind 登记最终提交失败未回滚 manifest 持久化

触发点：addon:5852 的 graph_bind transaction 在 body 内通过 addon:5853 `_fx_store_manifest` 写 root userData 与 state sidecar，离开 body 后才做最终 registry 验证/提交。没有使用已有 `_fx_snapshot_manifest_persistence` / `_fx_restore_manifest_persistence` 包围这个恢复分支。

定向观察执行该分支相同的实际 transaction → `_fx_store_manifest` body，使用实际已保存/已加载的 HIP、lease 与 checkpoint，不制造 worker-stop 成功回执。在最终 `Registry.end(commit=True)` 注入 `GEOMETRY_CHECKPOINT_CHANGED`。两版均拒绝，scope={}、active transactions=0、无当前 authority；但 embedded_manifest_restored=false、sidecar_restored=false，persisted checkpoint epoch 已从 0 改为 1。

证据：`probe-v3.json` 的 `graph_bind_body_commit_failure`。这是实际 graph_bind 内层事务/持久化 body 的定向复现，未执行完整 public graph_bind 或受控 process；源码明确显示同一缺失的 persistence 回滚。

整改应在恢复前保存 embedded/sidecar 状态，将该次持久化和 registry 最终确认放入同一回滚边界；失败只还原本任务自有状态。补全 graph_bind 正式负向用例需主 agent 集中调度，不由 reviewer 运行。

## 已关闭检查及检查边界

- 当前已有 registration carrier、saved contract 缺 checkpoint 时，两版均显式报 `GEOMETRY_REOPEN_CHECKPOINT_REQUIRED`，scope={}，无当前 observations authority：该旧缺口已关闭，不列为阻断。
- Registry 本身的恢复不重写 snippet/gates；checkpoint 精确比较原生 basis、record、参数及当前 node/session，rollback 保留无关 cohort。R01/R03 是 addon caller 的事务范围缺口，不是要求放松 Registry.end 的最终校验。
- worker→taskhost 的 graph_bind 路径仍通过当前 HIP hash、固定图结构/roles、当前 lease 和私有 scope 进入 registry；本次未发现可直接仅凭陈旧 carrier userData 收编的额外证据。此次观察不替代主 agent 的新 PID/nonce 正式验证。
- collect_evidence 当前 G03 readback 仍经 registry/底层读回，状态保持 BLOCKED/parameters_only；审查不把参数 authority 或通用 transition COMPLETED 当作实际变形、跨帧或下游事实。

## 复现与原始观察

实际执行命令：`.venv/Scripts/python.exe -B outputs/geometry-reopen-20261013-review/probe.py`。`probe-v2.json` 记录 6 次观察，exit 0；`probe-v3.json` 记录 2 次观察，exit 0。运行时 Python/Windows/命令及前后源码 SHA 在各 JSON 中。exit 0 表示诊断完成，不表示上述异常行为通过验收。

`probe-v1.json` 为诊断原件，exit 1：当时脚本把已经正确抛出的缺 checkpoint 拒绝当作 probe_error；其正常拒绝已在 v2 正确分类，原件保留但不计通过。

`probe.py` 当前 main 只选择 v3 的 graph_bind body 故障注入；其他已归档场景仍可通过该脚本的 `probe(version, case)` 函数定向调用，case 名与 JSON 一致。所有 fixture 内容留在其临时目录，无凭据或签名密钥归档。

当前结论绑定以上 SHA。整改后只复核受影响失败路径及新的源码绑定；不复跑无变化全量。
