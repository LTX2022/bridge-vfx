# P01 四项修补只读复核与新末次漂移（2026-10-14）

**四个原缺陷 R02–R05 的同一实际 API 探针已关闭；整体仍 REQUEST_CHANGES，新 R06/P1。** 未等待 addon 集成夹具，不改生产/tests、不跑 DCC/正式进程/全量。

## 原修补复核

| ID | 两版本实际结果 | 本次结论 |
|---|---|---|
| R02 | 缺 session_id/process_generation/plugin_build → PARTICLE_EMISSION_AUTHENTICATED_HOST_REQUIRED | CLOSED_SCOPED |
| R03 | restore 的 channel eval 改 nonce → PARTICLE_EMISSION_TRANSACTION_REQUIRED，channel_changed=false | CLOSED_SCOPED，确认实际 rollback 写入前拒绝 |
| R04 | actual maxIsStrict=true / max=1300，基准1200、p30完整840..1560 → PARTICLE_EMISSION_NATIVE_RANGE_EXCEEDED | CLOSED_SCOPED |
| R05 | 初始化末次 gate 失效 → PARTICLE_EMISSION_GATE_CHANGED，records_after_failure=0；gate恢复及新 session fresh retry accepted=true | CLOSED_SCOPED |

旧 R01 的末次 native gates 读取期间替换 channel 两版继续拒绝；自有时变表达式跨秒两版仍通过。所有结论以同一原触发重新执行为依据。

## 新 R06/P1：final channel snapshot 的 actual eval 之后不再核对完整上下文

位置：`native_particle_emission_host.py` 的 `Host.observations` 最末 if，依次比较 `_binding`、`_native`、`_channel`。`_channel` 使用 `_snapshot_parm_state`，该 helper 实际调用 `parameter.eval()`。此最后 actual eval 可改变已经验过的上下文；之后只比较 channel 身份并返回旧 binding/native/actual_rate。

探针 `native_context_drift_during_final_channel_capture` 已精确按 phase 调度：第二次 constantactivate 原生 gate 读取开始时安装底层 rate.eval_hook；之后 `_native` 不求值出生率，下一次 actual rate.eval 因而发生在最后 `_channel` 捕获中。hook 一次改变实际底层字段，**不伪造返回 fact/snapshot、不改生产、不生成成功仿真几何**。

两版各四案均 `changed=true`、`native_gate_captures=2`、hook触发一次、`accepted=true`：

- launch_nonce 改为不同宿主身份；返回仍包含旧身份。
- FPS 从24改30；返回仍按先前时钟报告。
- constantactivate 从1改0；返回仍签认原生出生门控。
- actual strict maximum 从2e7改1300；完整分布1560越界，返回仍携带旧限值。

当前作为一个共同原因 R06/P1 记录，不拆成四个重复 finding。需要确保最后 actual parameter 求值后核对 binding/FPS/门控/限值，且不要在这些检查之后再通过含 eval 的 channel 采集打开同一窗口；可把纯通道身份读取与带 evaluated 的 rollback 快照区分。实际设计由实现者决定，本 reviewer 不修改实现。

较早 `probes-late-drift-v1.json` 用固定第3次 rate.eval 触发；现在 fixture snapshot 含两次 eval，所以该次数实际上位于前一个 channel capture，只有 strict limit 漂移未拒绝。它是中间诊断，不能用于证明最后 phase 的其他案例已关闭。`probes-late-drift-v2.json` 改为阶段定位，才是本 R06 的有效证据；这解释了先前 commentary 与最新结果的差别。

## 命令与源码绑定

实际执行 `.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/actual_probes.py`，退出0；保存完整 JSON 为 `probes-late-drift-v2.json`。原四项结果亦单独存于 `probes-four-fixes-v1.json`。Python版本/绝对实际命令及 source_before/source_after 在最新 JSON 中；四份输入源码前后 SHA 完全一致：

| 当前输入 | SHA256 |
|---|---|
| native_particle_emission_host.py | 69f6dbde1b699ba30add0127b98a3e40f7c33342e2ecb652720c542462e71f3d |
| native_particle_emission_program.py | 5bb94f7de9ea2b95d872bd514025e7e088acabee944b44142a13c5fbb8ab686e |
| native_particle_ocean_geometry_domains.py | b8334bafc4aecc137c400e66bedb5dc8057367f2294ffe192fb42f93325f25aa |
| tests/unit/test_native_particle_emission_host.py | cb230f7071899b903c7a358011b8570133f3767072cef7b75610a677c916811f |

这是参数表达式/private Host 的软件边界复核；真实子步积分/new PID持久化及正式 addon 验收继续未验证，不能报告全域或 native PASS。旧 REVIEW.md 是前一阶段快照，本报告替代其 R02–R05 当前状态；旧日志保留审计。
