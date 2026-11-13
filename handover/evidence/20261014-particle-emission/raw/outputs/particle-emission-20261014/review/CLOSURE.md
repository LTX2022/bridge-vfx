# P01 最终限定审查结论（2026-10-14）

**REQUEST_CHANGES：R01–R07 CLOSED_CURRENT_SCOPED；R08、R09 两个 P2 尚未关闭。**
结论仅涵盖 P01 参数表达式与软件事务。生产/tests 只读，审查子任务到此结束，由主 agent 归档。本报告不扩大到 generated seed、新 PID 或全 16 域，也不签全域 M1。

## 最终源码与日志

- 最终 affected：24 方法，0 failure/error/skip，退出 0；command elapsed **34.844 秒**，unittest suite **34.397 秒**。命令与原件为 `outputs/all-domain-20261009/p01-closure-final-20261014.json/.log`。
- 最终快照含 **435 个 Python 文件**，source_before/source_after 相等，审查绑定时 current **0 diff**；controller Host 镜像一致，由该组 sync 测试验证。
- 前一阶段：54 方法，command **36.531 秒**、suite **36.068 秒**；0 failure/error，退出 0，两个 Oceanfoam 静态审计子用例为 **NOT_RUN/skip**，不能算通过。
- 两组有重叠，不能相加为 78 个独立方法。54 组与最终组快照实际相差 **4 个文件**：addon、Host、Host controller 镜像、addon test。最后新增外层事务由最终 24 组与只读接线检查评估，不宣称最终源码重新跑过全部 54 方法。
- 完整命令、环境、原件 SHA256、关键源码 SHA256、435 文件快照引用及当前一致性见 [SOURCE_BINDING.json](SOURCE_BINDING.json)。没有重跑正式进程或全量组。

## 已关闭

| ID | 最终限定结论与证据 |
|---|---|
| R01 | 最终 native 读取期间替换完整 channel 会被拒绝；自有表达式跨秒正常读回。 |
| R02 | 三字段完整 identity 必填；不完整 identity 拒绝。 |
| R03 | restore capture 后再次核对事务；late nonce 漂移拒绝且不写回 channel。 |
| R04 | 实际 strict bounds 冻结及完整数学分布验证；越界拒绝，UI 非严格范围不作为硬界。 |
| R05 | 初始化最后 observation 失败 CAS 撤销自己发的记录，fresh session 可重试。 |
| R06 | final channel actual eval 期间改变 nonce/FPS/gate/strict maximum，两版四案均拒绝。 |
| R07 | manifest 实际写成功后 gate 漂移，两版均 CANDIDATE_PERSIST_FAILED、pending=0；最终 addon 测试核对原 manifest/channel 回滚。 |

R01–R06 当前同一底层 API 探针原件为 [probes-final-candidate-v1.json](probes-final-candidate-v1.json)，R07 最终同一 actual addon persist 探针为 [addon-commit-final-candidate.json](addon-commit-final-candidate.json)。执行前后源码摘要相等，且与最终候选一致。底层 gate 保持外来实际变化，不将其偷偷恢复为成功状态。

新增 Host.build_transaction 的 exact-pointer CAS、outer_exception/late_gate/successor+retry 已由最终 24 组中的第五 addon 方法覆盖；该方法直接使用 Host 底层夹具，**不能替代普通 public build 接线覆盖**。

## 现有未关闭问题

### R08 / P2：scene epoch 后旧私有注册阻断 absence-config legacy control

现有 [registry-lifecycle-final-candidate.json](registry-lifecycle-final-candidate.json) 在 H21/H22 均复现：已登记 P01 → 实际 BeforeClear callback → 实际销毁旧 root → 正常无 particle_emission_basis 的新 build accepted → legacy birth_rate=1800 被拒 **PARTICLE_EMISSION_AUTHORITY_REQUIRED**。clear 与 rebuild 后 records 均仍为 1。

`plugins/houdini/_impl/houdini_bridge_addon.py:10854` 只增加 scene_epoch；`native_particle_emission_host.py:245` 的 absence-config 提前返回不清失效记录；`:285` 的 registered 按 emission path 匹配旧登记。新节点同路径被导向旧 P01 authority，而正常 legacy control 应保留。不是旧 HIP 授权或新 PID 恢复诉求。

需在可信 scene/build 生命周期使旧私有注册失效，保留身份校验及后继记录保护；不能放松 authority 检查或以 userdata 恢复权限。现有探针足以作为受影响验证，不需泛化。

### R09 / P2：普通 public P01 build 未进入新增外层事务

`plugins/houdini/_impl/houdini_bridge_addon.py:8350` 的普通 particles/no-source_plan 分支直接进入 _fx_build_preview_unfenced；新增 P01 build_transaction 只在 source transaction（:8437）及 registered initializer（:5942）接入。

现有 [public-build-scope-v1.json](public-build-scope-v1.json) 被动记录原 contextmanager 的进入次数；两版真实软件 client 普通 public build accepted，但 **build_transaction_calls=[]**。没有替换正常成功回执。第五 addon 方法在 `tests/unit/test_particle_emission_addon.py:125` 直接调用 Host contextmanager，不能证明该 public 分支受保护。

此 finding 是已证实的接线缺口。**未执行带 seed 的 fresh public build 在初始化后异常并残留 authority 的反例，不能声称已实际证明该残留。** 需将事务包住普通 P01 public build 外层，或明确该入口不承担本轮声明的初始化事务契约；本次冻结源码尚未达到所声明的 public 外层统一覆盖。

## 未核对与验收边界

- 参数 readback 仍为 BLOCKED/native_parameter_expression_only；未验证实际 POP 子步消费、跨秒积分、残余出生、仿真或成功几何。
- 未运行 generated-server P01 fresh seed 完整链、新 PID 恢复、真实 DCC、模型、渲染、macOS 或全 16 域 M1。
- arbitrary clock machine names 是显式通用底层模板 API 输入，不是同 build 捕获事实；未修改静态接口事实。
- 早期同场景 rebuild 夹具缺 number() 的诊断不列为生产 finding，也不算正常 rebuild PASS。
- 两项 P2 已有具体证据，不再新增探针或扩大范围。主 agent 的移交说明应保留这些开放项，不能将本报告转述为本批无缺口验收。

本子任务已完成；原始阶段材料保留审计用途，最终结论以本文件和 SOURCE_BINDING.json 为准。没有修改生产/tests/主移交文件，没有 commit 或运行 DCC。
