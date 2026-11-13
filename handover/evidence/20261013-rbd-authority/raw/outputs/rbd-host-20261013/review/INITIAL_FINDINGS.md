# R05 独立只读复核：首次确定发现

结论：CHANGES_REQUIRED。仅审查本批 R05 Host、collector、addon 接口及指定测试，不是全 16 域接收。未参与实现；仅本 review 目录有写入。所有 probe 只在内存修改底层 API 对象，未运行真实 DCC、仿真、渲染、模型或正式进程大测试。

## R02 / P1：权限检查之前已执行参数回滚

`plugins/houdini/_impl/houdini_bridge_addon.py:3874` 的 `_fx_restore_planned_item` 先调用 `_restore_parm_snapshot`，再调用 R05 `Host.restore`。当前 Host 的身份/node-session 检查因此只能拒绝后续 userData 写入，不能阻止已经完成的 snippet/channel 写入。

最小 probe 使用实际 addon 恢复函数及其实际 `_restore_parm_snapshot`，仅补底层 Parm.eval；持有原本合法的 snapshot，之后修改实际 launch_nonce，当前参数为 `current-context-value`。两版均抛 `RBD_VELOCITY_AUTHORITY_REQUIRED`，但参数已经被写成空串。value_only_compat 是生产 helper 明确支持的底层 API 路线；实际 channel 路线同样在身份检查前执行 deleteAllKeyframes/set，未重复制造真实宿主事实。外层 lease fence 能阻止另一个合规 executor 抢锁，不能撤销本次已发生的身份/scene 变化。

最小修复要求：由拥有快照的 R05 Host 在任何参数/userData/native side effect 前验证当前身份、节点 session、task/root 及有效 lease；恢复动作和身份检查保持同一序列化边界。不得以“最终报拒绝”当作无越权写入。补实际 addon 恢复反例，身份变化后 snippet/userData 均保持当前值。

## R01 / P2：最后 userData 读取可隐藏先前采集 gate 的漂移

`native_rbd_controls_host.py:81` 在参数、wire 读取之后读取 userData。`observations:253` 的两个 `_capture` 都不是完整末端 fence：最后一次 userData 底层读取可以改动此前已观察的 gate，而最终只检查身份和 frame。

最小 probe 在第三次 BASIS_KEY 的实际底层 userData 读取时把 exportlist 从 `v` 改成 `w`，其返回值不变。两版 `observations` 均成功，返回 gate=`v`，实际 gate=`w`。已有 FPS 漂移反例通过不覆盖此时序。

最小修复要求：关闭这一晚期读取窗口并保留有界检查；至少给出末端 userData→gate/native state 漂移反例，发生漂移必须拒绝，不能仅继续增加有限次数且末次仍盲区相同的 capture。

## R03 / P2 待正式约束核定：Host.restore 不检查有效租约

合法 prepare/write 后只将底层 lease 查询设为明确拒绝，Host.restore 仍成功并删除当前登记。该直接 Host probe 已复现；未宣称另一个合规进程能绕过外层 root lock。正式外层 fence 在入口验证一次 lease，长操作内 lease 到期或同进程状态变化后，当前恢复路径仍不验证；建议与 R02 一起由 Host 完成 side-effect 前有效 lease 检查。

## 已读取的结果及源码绑定

- 主 integration-v1：84 methods、exit 0、source_before==source_after；读取原始 log/json，不重跑。
- formal-v1：1 method、两版本 2 failure、exit 1；在 trial 阶段 RECONCILIATION_REQUIRED / RESULT_EVIDENCE_UNVERIFIED，不能当作完整 zero→save→stop→fresh PID 拒绝验证。正式测试正由主定位，未判 PASS。
- authority final-owned：25 methods、exit 0，collector final：33 methods、exit 0；仅窄范围软件事实。
- Host 两份 SHA256：`f6476ed4447055834646b4ff3fe5ab3274dc97e4198ac5579fb36d3ef708446b`。
- Program 两份 SHA256：`39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`。
- addon SHA256：`2b9b2add77418841c2a092c27e085a72cf3eb58219bcac287c20ad96458c9378`。
- 最小探针命令：`.venv/Scripts/python.exe -B outputs/rbd-host-20261013/review/independent_refusal_probes.py`，exit 0；六项实际观察及十项源码前后相同摘要见 `independent-refusal-probes-v2.json`。exit 0 表示 probe 完成，绝非被测边界通过。
- `independent-refusal-probes-v1.json` 首次路径定位错误，未加载测试；空输出不可当作测试证据，修正仅涉及 review 自有脚本。

源码或 fixture 改变后需受影响复核。fresh PID 未实现 verified R05 checkpoint 时仍应拒绝，不能把通用参数重开提升为完整 R05 恢复。
