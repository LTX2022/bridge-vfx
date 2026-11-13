# Render snapshot 独立只读复核

2026-10-10，Asia/Shanghai。结论：**最新 Windows 错误分类及快照读补丁未发现确定的未闭合 P1/P2；结合同源码 21 项受影响组及 formal c 单项复验，有限关闭该快照读取故障。** 原 10 项失败组保留原结果，不将该结论提升为完整恢复组或全 16 域 M1 接收。

审查遵守 Bridge 根 AGENTS.md，已读 README.md、handover/STATUS.md、handover/REMAINING.md、handover/NEXT_AGENT.md。未参与实现，未修改 client、测试或已有日志；唯一写入为本报告。未运行测试、正式进程组、真实 DCC、HY3、模型、仿真、缓存或渲染。最新指令收窄后仅核对最终 helper、已有消费/原子写语义及相关已生成证据，没有追加执行范围。

## 本次源码绑定

路径均相对 `C:/Users/32200/Desktop/Agent/skill/Bridge`；HEAD 为 `a3e7734e0f69b663be5bbd7d1f97bbdcb2d90b7d`，评审的是工作区补丁，不是 HEAD 原件。

| 文件 | SHA256 |
|---|---|
| packages/houdini-bridge/src/houdini_bridge/client.py | a548728901af5f5b0701fb3c42e686780e853c9b0729b62b73a1a54ba55d3dbd |
| controller-entry/client/houdini_bridge/client.py | a548728901af5f5b0701fb3c42e686780e853c9b0729b62b73a1a54ba55d3dbd |
| tests/unit/test_render_store_snapshot.py | f781c67ea73ad73dae05ae8f8b9227aa9429472a9604844a87b328e8aa1bc752 |

package client 和测试的当前摘要与 `outputs/all-domain-20261009/common-snapshot-sharing-native.json` 的 source_before/source_after 分别相同，且 source_unchanged=true。主线之后同步的 controller client 与 package client 字节摘要相同；上述三个最终摘要均与 `common-snapshot-formal-final.json` 的 source_before/source_after 一致，source_unchanged=true。

## 最终 classification 与异常边界

`client.py` 的 `_read_render_store_snapshot` 使用真实 `Path.read_text(encoding='utf-8')`。重试条件为 Windows 且满足以下之一：明确 winerror 为 5/32/33；或者 winerror 为 None 且 errno 为 EACCES。Python 运算符优先级使后者要求两个条件同时成立；有明确的其他 winerror 时，EACCES 不会覆盖其分类。非 Windows 无此重试。

该补充与实际 Win32 SHARE0 拒读反例相符：先前 fixed 日志显示 pathlib/CRT 抛 errno13、winerror=None，原只检查 winerror 的方案直接失败；最新分支覆盖这一实际文件读取路径。**EACCES 本身不能证明 sharing violation，也可能是永久 ACL 拒读。** 最新实现只把它作为允许短暂重试的读取拒绝，没有声称识别了具体占用者，也不改变 ACL 或文件权限。

预算为 monotonic 起算 .5 秒，最多 20 次读取；退避为 10/20/40/50 毫秒，之后每次最多 50 毫秒且不超过当时 remaining。耗尽预算、达到次数上限或遇到不允许重试的错误时，裸 raise 重新抛出当次原始 OSError，没有转换成功、空 store 或 CORRUPT_STORE。每次尝试前重新检查 path.is_symlink，发现链接即拒绝；这一检查不等于消除了检查与打开之间的所有路径替换竞态，本补丁没有作此保证。

`.5s` 是拒读重试预算，不是文件系统调用、JSON 解码或调度的严格墙钟上限：最后一次 sleep 结束后仍可进行一次读取，单次 read_text 也没有可中断超时。现有持续持锁测试断言小于 1.5 秒，与这种预算解释一致；不应宣称函数任何情况下都在精确 0.500 秒内返回。

JSON 解码在读取 try/except 之外，损坏 JSON 不触发再次读取；Unicode 解码错误也不属于 OSError 重试。任务、request、host、supervisor 及 producer_binding 校验仍位于调用 helper 成功之后，未移入循环，语义拒绝不会通过重新读取绕过。helper 内没有重做 render、HOM 查询、execution_lock、落盘修补或异常吞噬。

## 原子写与消费语义

现有 addon `_save`（`plugins/houdini/_impl/houdini_bridge_addon.py:12890`）调用 `platform_support.atomic_write`。后者先写同目录独有临时文件，flush/fsync 后 atomic_replace，最后清理临时文件；原子替换已有 Windows 有界拒绝重试。新读取层在读操作被拒绝后重新打开路径，成功取得一个快照后才解码/绑定校验，不缓存上次内容，也不把不完整 JSON 当作可恢复成功。

正式消费入口 `workbuddy_assembly.py:1395` 对 render.status/cancel/verify 使用已保存 owner binding 调用 read_render_operation。client 原有逻辑在未取得 signed stopped 时不占 execution_lock，只有已停止 worker 的 reconciliation 才进入原有锁和写路径；本补丁只替换该分支内原来的单次快照读取。没有添加执行中 HOM 查询、额外渲染或新的锁获取。停止、terminal original 和 producer/fact 校验保持原有位置。

## 已读证据与未验证边界

原 `common-final-source-recovery.log/json` 确为 10 项、9 PASS / 1 FAIL、0 ERROR、exit 1。formal c 期望 FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED，实际 blocker 为 ops_be07477e88dd6701.json 的 Permission denied。该日志没有足够信息证明当次拒绝一定来自共享锁；当天 snapshot 后续正常可读、未 CORRUPT 的事实由主线提供，本审查没有重跑该故障或重签任何证据。

以下历史失败原件均仍保留，未覆盖：

- `outputs/all-domain-20261009/common-snapshot-sharing.log/json`：初次 5 项全部 ERROR，遗漏 time/os 导入；最新补丁已补 errno/os/time 导入。
- `outputs/all-domain-20261009/common-snapshot-sharing-fixed.log/json`：21 项中 1 FAIL / 1 ERROR，真实分享拒读没有 winerror，释放后成功路径仍失败，旧 winerror 断言也失败。
- `outputs/all-domain-20261009/common-snapshot-sharing-native.log/json`：最新 21 项全部通过，0 FAIL / ERROR / SKIP、exit 0；unittest 4.335 秒，外层 4.531 秒。包含 7 项 snapshot 和 14 项既有输出回执受影响用例，摘要与本次最终源码一致。

两条共享拒读测试确实用 CreateFileW 的 share mode 0 持有实际临时 JSON 文件，没有替换 render/runner 或合成完成事实；分别覆盖释放后真实读取成功和持续持有后 PermissionError 传播。其他用例覆盖文件不变、缺失文件不重试、坏 JSON 单次读取、symlink 拒读及明确 winerror21 单次拒绝。审查只读取主线结果，没有独立执行这些测试。

最终补审已读取 `outputs/all-domain-20261009/common-snapshot-formal-final.log/json`：正式 `test_c_readiness_consumes_real_recovery_and_keeps_completed_stages_when_registration_blocks` 单项通过，0 FAIL / ERROR / SKIP、exit 0；unittest 16.877 秒，外层 17.125 秒，source_unchanged=true，最终 package/controller client 和测试摘要均匹配。它证明这次正式软件恢复消费到达并通过原单项断言，未将缺原生输出事实改成成功；审查者没有启动该进程组。

**上述静态核对、真实文件分享拒读受影响组及最终正式 c 单项证据支持本次快照读取故障有限关闭。** 原 10 项 9 PASS / 1 FAIL 日志以及 first/fixed 失败日志保持原样；没有声称在最新源码上重跑整个 10 项组。安装、真实宿主、模型路线、视觉、生产及全 16 域接收均不在本次结论范围；不等待全域结果。
