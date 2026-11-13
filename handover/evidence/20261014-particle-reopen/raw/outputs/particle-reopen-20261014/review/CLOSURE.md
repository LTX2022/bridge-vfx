# P01 独立只读审查闭环（范围内）

历史闭环快照；最终增量与中央证据状态以 `CLOSURE_FINAL.md` 为准。最后发现 R06 OPEN P2（正式结果过滤丢弃 saved-contract marker），不能把本文的旧范围内闭环结论理解为当前全批验收。

结论：**R01–R05 CLOSED_SCOPED**。新增可信保存重开→graph bind 路径在本轮限定范围内未发现其他可复现 P1/P2。此结论是组件与静态审查闭环，不是本批正式跨进程验收或全项目完成声明。

本审查未参与生产实现；只写本 review 目录，未修改生产、测试或 docs。实际源码、证据及审查脚本 SHA-256 绑定在 `REVIEW_SOURCE_BINDING_01.json`。绑定记录的前后摘要一致不等于主 agent 已宣告冻结；后续变更需只复核受影响部分。

| 项目 | 结论及证据边界 |
| --- | --- |
| R01：末端 native capture 后 HIP 漂移 | Host.end 末端保留 artifact authority + opaque pointer CAS 后再提交。原故障在 `PHASE_PROBES_04.json` 两版拒绝；该证据保留原阶段 SHA，随后 Host checkpoint 的 R03 修复使整文件摘要变化。当前源码静态确认末端保护仍在，当前 Host SHA 与 `R02_R03_RECHECK_01.json` 一致；不把 R01 旧阶段运行宣称为当前整文件运行。 |
| R02：零振幅种子改写及自重摘要 | supplied CP 必须等于 immutable HIP manifest CP；每次私有授权重读实际 root userdata，完整非 identity 内容必须不变，identity 仅允许旧 CP 或当前完整身份。`R02_R03_RECHECK_01.json` 两版拒绝；`AUTHORIZATION_ENV_RECHECK_01.json` 允许真实 identity-only manifest 更新，拒绝删 CP、改 basis 或外来 nonce，并退回 INTENT。旧阶段证据不冒充当前全源码执行。 |
| R03：最后节点读改变既有 gate | 最后 checkpoint node collector 后再 observations + private pointer CAS；异常 Host 自动清理后 addon 仅在 token 仍存在时 abort。原故障两版拒绝，证据 `R02_R03_RECHECK_01.json`。 |
| R04：reconcile 先取 CP 后读合同的陈旧事实 | 完整合同核验后重新读取实际 CP。当前原 probe `R04_RECONCILE_RECHECK_04.json` 两版均拒绝 `PARTICLE_EMISSION_GATE_CHANGED`，退出码 0、源码前后一致。该证据是实际 reconcile 组件，没有伪造 public COMPLETED。 |
| R05：合同不可见与随后共享可变操作状态 | 最终正确规则为保存合同与 immutable snapshots 共享，RPC/runtime、lease、fx_tasks、live/legacy operations、software operations 隔离。`R05_NAMESPACE_RECHECK_04.json` 实际调用环境与 addon helper，含中文/空格路径、外来 env 覆盖、实际 snapshot 内容摘要，所有对应事实成立，退出码 0、源码前后一致。 |

R05 的 `_02` 证据对应“共享所有 task facts”的中间方案；`_03` 对应规则变更时的过渡检查。它们不用于最终 namespace 验收。此前失败的正式日志均保留；共享 mutable operations 导致并发推进的问题已由主 agent 的实际 stop 原因定位，本审查不把旧非零退出结果计入成功。

## 新增可信 graph handoff

- Worker 的 `registered_scene_contract_sha256` 来自实际 `scene.save_hip` 返回合同，不从 caller marker 或 embedded CP 派生，且包含在控制端 receipt 摘要的 verification 中。
- Production client 在核验 sealed artifact、当前 task identity、终止结果及实际文件摘要后，对带注册合同的结果调用既有 `scene.reopen_task_hip`，传精确合同 SHA，再 bind；普通无注册合同 graph 保留既有 open 路线。
- Task reopen 从实际保存存储核对 task/path/HIP bytes 与精确合同摘要，加载核验后的 immutable snapshot，完成原生节点、参数及连接核验。仅在合同根与 loaded manifest 相符、实际完整节点核验通过、确切 `/obj` owned root 标记为 1 且当前 lease 缺失时签发该根 lease；已有租约走原显式 takeover/CAS，不在 bind 根据 request 重写 owner。
- Graph CP helper 仅在 active_scene 的 snapshot_path、内容摘要和完整当前 identity 同时相符时映射回原始保存 path；仍要求实际保存合同 task/root/graph/hash、CP 与 loaded immutable HIP manifest 全等以及完整 native 核验。普通 embedded CP、自重摘要或 caller receipt 单独不能提供私有重开权威。原 helper 拒绝证据保留在 `PHASE_GRAPH_HANDOFF.json`；最新 snapshot 映射与 missing-lease 路线为静态审查，实际 public 跨进程正常路径由中央 final 验证。
- Domain identity 保留实际 task_id、pid、launch_nonce、version、plugin_build、session_id、process_generation、scene_epoch 八字段。Producer 的额外 supervisor_identity 不是跨宿主 CP 的恒定字段；监督授权仍由其既有实际 producer 校验承担。

Seed 路线此前已核对唯一 semantic role、non-bool nonnegative int32、4 KiB ceiling、严格 UTF-8、重复字段拒绝、中文/空格路径、late bytes/digest 核验与 wrong-domain-before-construction；缺 seed 延续无默认 legacy 路径。本轮未重复旧 P01 数学/ordinary guards 或 39 项中央测试。

完成记录异常使用 exact completed record→INTENT CAS；私有注册清理使用 opaque pointer CAS，保留 successor。正常授权不使用手写成功回执或替换正常校验返回值。

## 未验证及待中央收口

本审查未执行 formal OS、真实 DCC、模型、仿真、缓存、渲染、视觉或安装验收，未扩展全 16 域。底层 HOM 同进程组件不能证明新 PID/nonce 恢复、真实 POP/native 行为或 public 正式链运行成功。

最终源码的中央真实 OS 软件进程 final、监督 stop 事实及跨 PID public reopen→bind→collect/save 结果仍须由主 agent 绑定日志完成。此前 `p01-formal-verified-handoff-20261014` 记录退出 1、两版失败，不能引用为本批 PASS。中央后续成功结果未在此报告中预判。
