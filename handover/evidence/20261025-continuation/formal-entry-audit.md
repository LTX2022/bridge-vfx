# H21 HIP 正式入口有限只读审查

结论：在本次限定合法正常路径内，未发现可确定触发的新增 P1/P2 软件阻断；没有提出源码修改。此结论不等同真实 HIP 保存、冷重开或性能通过。

当前候选：`/Users/user/Documents/Code_Project/Bridge/outputs/hip-hotpath-20261025-prepared-02`。冻结 source SHA-256：`ca635d07a487a70d3ed3ef6fe2710dbc5a897518ca5caf5012e64fe3878d1c00`。

已审查的10个关键运行文件与 prepared-02 冻结源、当前源码和先前核心测试输入哈希均一致：True。

资源合同保持建图240秒、冷重开120秒、累计360秒，最多2次启动、512MiB、单重作业、零自动重试。

## prepare_activate_execute

- prepare freezes explicit host/configuration/proposal/source records without launching a native executable.
- activate consumes candidate-bound independent review and current resource confirmation into a fresh scope.
- execute requires frozen entry, matching controller interpreter, real_host/software_test separation, one execution journal, and fail-closed terminal state.

定位：`tools/run_hip_diagnostic.py:145-284`, `tools/run_hip_diagnostic.py:682-782`。

## argument_production_consumption

- Service persists original operation intent and emits matching attempt identity, paths, frozen manifest and budget fields to the actual worker CLI.
- The file transport rewrites --job into --job-file and --job-file-sha256 and the worker verifies its bounded bytes and attempt-owned path.
- Worker budget validation compares job, inputs.json and original SQLite operation before construction.

定位：`packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:763-865`, `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py:244-397`, `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py:1016-1074`。

## lease_identity_stop

- Fresh owned HIP naming occurs under the scheduler fence before host scene identity and scene lease acquisition.
- Construction dispatch compares live scene identity and persisted scene lease; save/reopen rebinds the scene lease.
- A successful graph requires stopped state, completion validation, signed owned-child stop and matching worker PID; cold launch obtains a new process and task-host identity.
- Cancellation signals the owned handle before durable fence operations; stop unknown retains the slot and the enclosing diagnostic fails closed.

定位：`packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py:437-603`, `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py:721-850`, `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:938-1115`, `tools/run_hip_diagnostic.py:340-347`, `tools/run_hip_diagnostic.py:540-661`。

## save_warm_and_cold_readback

- The normal graph path executes actual addon save and owned reopen dispatch, then reads node types, compiled parameters and connections from the reopened host.
- Producer save compares before/after actual contracts, saved-file identity and immutable snapshot rather than trusting the handler success flag alone.
- Cold reopen loads the saved HIP through scene.reopen_task_hip, checks complete node/channel/connection state and frozen scene geometry/material readback, and binds the result to the expected transition and snapshot.
- The HIP consumer validates both supported legacy and locked-HDA contract policy through validate_scene_contract_header; no repeat of already completed 2.1 repairs is proposed.

定位：`plugins/houdini/_impl/houdini_bridge_addon.py:13035-13177`, `plugins/houdini/_impl/houdini_bridge_addon.py:13830-13989`, `plugins/houdini/_impl/houdini_bridge_addon.py:16499-16904`, `tools/run_hip_diagnostic.py:350-381`, `tools/run_hip_diagnostic.py:508-526`。

## budget_start_and_stop_reserve

- Graph trial persists its original created_at plus 240 seconds; launch/worker validation and recovery consume that original operation deadline.
- The driver takes the minimum of its outer hard bound and persisted operation remaining, then opens a 230-second work window with the final 10 seconds reserved for stop.
- The scoped supervisor independently derives remaining from admission and bounds its work by the same ten-second stop reserve; the driver and supervisor use the minimum deadline and do not add their reserves together.
- For the resource profile cold runner receives 110 work seconds, while driver and scoped supervisor retain a 120-second hard cap; cold runner does not subtract another ten seconds.
- NativeScope enforces role-specific 240/120 charges and 360 cumulative charge, two starts, one heavy operation, disk cap and no automatic retry.

定位：`tools/run_hip_diagnostic.py:300-317`, `tools/run_hip_diagnostic.py:384-416`, `tools/run_hip_diagnostic.py:529-588`, `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:572-590`, `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:632-673`, `packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py:414-423`, `packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py:529-574`。

## verify_receipts

- Offline verification reauthenticates local signed start/stop pairs using original local keys and reports execution return codes; it explicitly reports native_execution_status NOT_RUN and does not perform a host acceptance run.

定位：`tools/run_hip_diagnostic.py:747-765`。

## 证据边界

复用现有核心接收记录（111个未变化通过项加1个纠正后单项通过，共112个唯一用例）；本审查核对关键源码指纹，未重复测试、未新增软件替身。没有启动任何DCC、模型或真实采样，没有创建激活或授权，没有改动源码和旧证据。

实际H21 Karma HDA强绑定、Embedded读回、240秒/120秒内完成仍是原生未知；不能据此推断软件缺陷，也不能将本报告升级为真实验收。完整工程、M1、HY3、渲染、视觉与生产验收均未提升。
