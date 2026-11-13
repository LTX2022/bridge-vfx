# P01 独立只读审查：早期具体发现

范围为 P01 新程序、Host、核心路由和 addon 接线；不是全 16 域结论。只读生产/tests，探针仅使用已有明确底层 HOM 夹具，没有仿真几何、DCC 或正式进程。

## R01 / P1：末次 native 采样后未重查完整出生率 channel

`Host.observations` 在首轮 `_native` 之后读取出生率 fact/channel，然后再次 `_binding` / `_native` 即返回；末轮 native 参数求值可以改变 constantrate，返回仍签认旧 actual_rate 为当前可信状态。

可执行探针 `actual_probes.py` 中 `foreign_channel_replacement_during_final_native_capture`：在第二次 actual constantactivate 观测回调，把底层实际 rate.source 改为 `99999.0`。两版本 `accepted=true`，返回 `actual_rate=888.4559140108928`，函数退出时 actual rate=99999。不是期待生成的成功值，改变的是实际底层表达式字段。

建议在末次完整门控/clock/identity 采样附近，补完整 actual rate channel 与参数类型/可写性/值核验，覆盖末轮回调造成的替换，且把相同语义用于 commit/release 前的读回。保留 keys/语言/外推/引用完整身份；不要把时变 evaluated 值当不可变 channel。

## R02 / P2：Host 接受不完整宿主身份（边界守卫缺口）

`Host._binding` 要求 task_id/pid/launch_nonce/scene_epoch/version，但没有要求 session_id/process_generation/plugin_build。探针移除这三字段后，initialize 和 observations 两版本仍成功。当前共享 addon 正常回调是否总提供非空这三项应一并核对；此证据证明 Host 自身不满足“full host identity required”的断言，不声称已经攻破合法生产租约。

## 已修正的并行中间状态

第一轮只读观察发现 channel 身份包含 snapshot.evaluated，可能拒绝自有时变表达式。探针实际执行前该处已由实现者改为排除 evaluated；`unchanged_owned_channel_cross_second` 两版本均成功。不能把这个已修正怀疑计作当前阻断。

R01 已在随后源码中补最终 `_channel` 比较；`probes-after-channel-check.json` / `probes-rollback-limits-v2.json` 两版本该探针已拒绝，当前暂记 **CLOSED_SCOPED**。尚需 final readback / commit 范围复核。

## R03 / P1：回滚 channel 捕获期间身份变化仍允许 native 写入

`Host.restore` 先 `_transaction` 验 binding，再 `_channel(parameter)`，之后不重新验身份即 `_restore_parm_snapshot`。`host_identity_changes_before_actual_rollback_write` 在实际 channel capture 的底层 `parameter.eval` 回调改变 `launch_nonce`；两版本 restore 均 accepted=true，`channel_changed=true`。这证明旧事务在实际 native 写入前身份已经变化仍能恢复先前 channel；不是仅报错文本不严谨。

建议在 snapshot 捕获之后、actual native rollback 写入之前重查 private transaction/binding/节点 session，再检查恢复完成后的 binding；不能仅最后拒绝但已经把新身份参数写坏。生产/tests 仍由主 agent 修改。

## R04 / P2：数学范围 helper 未贯通 actual 严格界

`actual_strict_maximum_excludes_distribution_endpoint` 给实际 rate 模板 `maxIsStrict=True`、max=1300，baseline=1200、p=30 的完整数学范围是 840..1560。当前秒的 actual_rate=888.4559，在范围内，因此 Host apply/observation 两版本 accepted=true。Host 从未采集 strict bounds，也不调用现成 `validate_rate_range`。不能用 static UI range_tokens 作为硬界，但 **实际严格界** 不应被忽略；应采集模板 strict flags/value，冻结为上下文、在写前验证整个分布，缺失/不严格时明示 hard-limits unproven。

`probes-rollback-limits-v2.json` 为 R03/R04 的有效证据，包含 source/fixture SHA。`probes-rollback-limits.json` 是并行 program 加入 import hou 时的空诊断文件，未成功执行、不作证据；已在 review 探针内显式安装 bottom hou API 模块后重跑，未改 tests。

## R05 / P2：初始化验证失败留下 private registration，阻断 fresh 重试

`Host.initialize` 先把 record 写入 authority，再调用最终 `observations`；失败没有撤销自己刚发的 record。`failed_initialization_keeps_private_record_and_blocks_fresh_retry` 在最后 native 读取把 constantactivate 改为0，两版本首次报 `PARTICLE_EMISSION_GATE_CHANGED`，但 private records=1。恢复 gate、更新实际 emission session 模拟 fresh node 重建，再 initialize 报 `PARTICLE_EMISSION_AUTHORITY_REQUIRED`。这与 addon 销毁 fresh nodes 后重新建立节点的故障恢复不兼容。

建议 provisional record 用 CAS try/except 撤销，仅撤自己本次 issued record，保留已有有效记录/其他根。有效最新探针见 `probes-initialization.json`，包含 R01–R05 各 actual API 案例、两版源码前后摘要。

## 复现

在项目根执行 `.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/actual_probes.py`。初次可保存输出见 `probes-initial.json`，含每次实际源码/fixture 前后 SHA；并行源码版本可能与更早文字检查不同，以 JSON 为准。

这只是早期 findings。实现与 host tests 仍在变化；后续只读复核将绑定更新后的源码，尚未签发最终 PASS。
