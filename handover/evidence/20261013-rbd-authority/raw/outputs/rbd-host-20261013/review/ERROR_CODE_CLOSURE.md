# R05 最终独立复核：PASS_SCOPED / 冻结交付

2026-10-13。本报告接收最终 integration-final-v2 / formal-final-v2 实际原始结果，替代 CLOSURE.md 中“最终正式结果待提供”的状态。R01–R05 五项确定缺陷及本次公共 preflight 错误码丢失已限定关闭；当前范围无已确认剩余阻断。结论仅覆盖本批 R05 Host、collector、addon 权限/恢复/采集及受影响软件入口，不是全 16 域验收。

reviewer 未参与对应实现，本次只读核对源码、实际日志、生命周期及生成快照，不修改生产/测试/夹具，不重复大测试。写入仅在本 review 目录。全部测试冻结清单 425 项当前 SHA 与两个最终结果的 before/after 一致；两版生成快照各 135 项均与当前 root 源码一致。完整路径、SHA、实际命令、解释器/系统和历史原件摘要见 [ERROR_CODE_SOURCE_BINDING.json](ERROR_CODE_SOURCE_BINDING.json)。Git HEAD 仅标记历史基点；有工作区改动，验收绑定文件 SHA，不以 HEAD 替代。

## 最终源码

| 文件 | SHA256 |
| --- | --- |
| package / controller native_rbd_controls_host.py | 8f263e25501804ef684a0a95a4fe568050513dcebfcd7130f329c62f9260a045 |
| package / controller native_rbd_controls_program.py | 39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a |
| plugins/houdini/_impl/houdini_bridge_addon.py | 5cda9e9d35d3609c7625efd89f54b9fb9e3b5f1c0c575cf8d774d79e991ada78 |
| tests/unit/test_rbd_review_guards.py | 702ffeb8d64a643e1ff809793e39a3e89d14e50b96af385e894c1619e55202e3 |
| tests/unit/test_rbd_addon_authority.py | 20507108acfe1011faca531046f798b90901f722bb7fa40a3e2502cf6e162d50 |
| tests/unit/test_rbd_authority_process.py | 4d8a5ff944effb824e7f1f4db5b019edb8099469346627e16924993d6a2f25db |

## 实际最终结果

| 实际运行 | 方法数 | exit / failure / error / skip | wrapper 耗时 | 源码 |
| --- | --- | --- | --- | --- |
| integration-final-v2 | 97 | 0 / 0 / 0 / 0 | 56.625s | unchanged，425 项与当前一致 |
| formal-final-v2 | 1，方法内覆盖 21.0.631 / 22.0.429 | 0 / 0 / 0 / 0 | 84.328s | unchanged，425 项与当前一致 |

原件：[集成摘要](../../all-domain-20261009/rbd-authority-20261013-integration-final-v2.json)、[集成原日志](../../all-domain-20261009/rbd-authority-20261013-integration-final-v2.log)、[正式摘要](../../all-domain-20261009/rbd-authority-20261013-formal-final-v2.json)、[正式原日志](../../all-domain-20261009/rbd-authority-20261013-formal-final-v2.log)。实际命令数组保存在两个摘要和本次 source binding；Python 3.11.9，Windows 10.0.26300。上述是主集中实际运行、reviewer 读取核对的结果，不冒称 reviewer 重跑。

## 公共错误码收口

`_fx_planned_domain_prepared` 的三项既有只读 preflight 移入原 try/except；读取、检查及后续写入顺序和门槛不变。preflight 的 NativeFlipRbdError 现由既有 BridgeCommandError 包装保留原 `.code`；prepared 尚未创建时仍仅释放空集合。独立内存反向移动三项语句后，addon 完整字节 SHA 恢复旧 31147b4a7910a800cec77237d9814c5db89853f3f3eebfbad46fbeebc8f684c5，证明此次生产变化仅为异常捕获范围。

[public-wrapper-review-v1.json](public-wrapper-review-v1.json) 和 [public-wrapper-unit-v1.log](public-wrapper-unit-v1.log) 已在当前 addon SHA 上证明缺 packed API 保留 RBD_PACKED_GEOMETRY_COLLECTION_FAILED、旧进程私有身份漂移保留 RBD_VELOCITY_AUTHORITY_REQUIRED，native 参数/userData/帧均不变。最终正式 TCP / owned OS worker 两版也实际返回 **RBD_VELOCITY_AUTHORITY_REQUIRED**，不再是旧 formal-final 的 COMMAND_FAILED。

写入阶段的非零实际消费不匹配仍按原公共 candidate 合同返回 **CANDIDATE_APPLY_FAILED**，detail 含 **RBD_ACTUAL_VELOCITY_CONSUMPTION_MISMATCH**。本次只关闭 preflight 具体码丢失，不把全部写入错误改称直接 native code。

## 两版真实软件进程生命周期

| 版本 | 旧 PID → 新 PID | stop / reopen / refusal |
| --- | --- | --- |
| 21.0.631 | 23736 → 39284 | child wait 已观察、Job active=0；新 nonce/session/generation；直接参数读回保持；RBD_VELOCITY_AUTHORITY_REQUIRED |
| 22.0.429 | 30520 → 17704 | child wait 已观察、Job active=0；新 nonce/session/generation；直接参数读回保持；RBD_VELOCITY_AUTHORITY_REQUIRED |

实际原件：[H21 lifecycle](../formal-final-v2/21.0.631/lifecycle.json)、[H21 snapshot](../formal-final-v2/21.0.631/snapshot-code.json)、[H22 lifecycle](../formal-final-v2/22.0.429/lifecycle.json)、[H22 snapshot](../formal-final-v2/22.0.429/snapshot-code.json)。

正式方法两版本均走实际 generated server / TCP / 自有 OS worker。固定底层几何的 zero 正常路径成立；nonzero 不重新计算成功几何，必须因实际消费不匹配拒绝并回滚。随后保存，检查 stop_hosts 的 confirmed_exit/heavy_slot_released，并经 OwnedProcessHandle.receipt() 的实际 verified reader 获取 child_wait_observed、PID/身份/出生时间/started SHA 和空 Job。reviewer 核对该读取实现及归档事实，没有复制签名密钥，也没有对归档提取字段另作签名复验。

新 PID/nonce 直接重开后，测试核对保存的 snippet/class/group/vex_precision/exportlist/bindings，再尝试候选操作取得权限拒绝并再次核对参数不变；未通过重新 apply 恢复成功值。该结果只证明普通参数持久化和新身份的正确拒绝。生命周期 scope 原文含“verified R05 restore”，不能将该文字解释为正向 R05 权限恢复；实际 adoption_refusal 明确拒绝，geometry_registry_restored=false。

## 五项关闭及保留边界

五项原反例 10 个双版本观察及恢复补充 12 个观察详见 [CLOSURE.md](CLOSURE.md)、[原 probe](closure-original-probes-v1.json)、[恢复 probe](closure-restore-probes-v1.json)。R01 userData 提前采集；R02 实际 addon 恢复先授权；R03 lease/task/host/node-session/parameter 路径私有绑定；R04 实际几何逆序复采及最后状态检查；R05 两处 wire 的 5 项拒绝限额，均已关闭对应确定反例。public userData/pending plan 不能授予权限，旧合法 carrier/恢复正常链保留。collector 的 256+1 限额保留，不声称 native 内部枚举分配有界。

**material boundary 保留：**实际 setter 在一次当前合法 parameter 恢复之后、setter 内部才漂移身份，后续授权会拒绝剩余 userData 写入；已经合法执行的 parameter 动作不称原子撤销。因此不宣称跨 host 完整 atomic rollback。逆序内容复查也不宣称跨 node 原子快照、任意末端 native 副作用均可排除，或真实 VEX/Bullet 消费已验证。

## 历史与未验证内容

旧 formal-v1/v2、v3、v4、v5 和 formal-final 的失败 JSON/log 原件继续保留，存在的原件 SHA 及原退出/失败记录列入 source binding。特别是 [旧 formal-final 摘要](../../all-domain-20261009/rbd-authority-20261013-formal-final.json) / [原日志](../../all-domain-20261009/rbd-authority-20261013-formal-final.log) 仍是 exit1、两版 COMMAND_FAILED 断言失败，不改为 PASS；本次由新 SHA 的 final-v2 关闭该错误码问题。旧集成结果也不替代本次最终结果。

- **BLOCKED：**fresh PID 无 verified R05 checkpoint 的正向 authority 恢复；正确拒绝不是完整 reopen 功能通过。
- **NOT_RUN：**真实 Houdini/Nuke、模型、原生 VEX/Bullet 仿真、缓存、渲染、视觉与生产验收；macOS 目标机复验。
- 软件 fixture 的完整场景 identity/fingerprint 仍有缺失（playbar/fileReferences 等底层 API 未覆盖），不将任务局部 R05 流程通过扩大为完整场景身份验证。
- 全 16 域 M1 / 安装验收不在本 reviewer 结论内。

在本报告与 ERROR_CODE_SOURCE_BINDING.json 绑定的源码/测试/生成快照上，本批限定复核完成并冻结。后续源码或夹具变化需受影响复核；保留上述边界和缺口，不把本报告用于扩大验收范围。
