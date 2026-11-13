# P1 最终独立只读复核（2026-10-05）

结论：初审“终态产物重摘要替换”P1 在本次有限软件边界关闭。接受签名终态原件 + 当前字节复核；本轮未发现新增阻断。保留 independent-review.md 作为初审反例。本结论不表示 OCIO/beauty alpha、registry 登记或完整正式链通过。

## 源码与证据核对

- client.py:306 的 seal_render_terminal 必须使用实际 signed started、当前 PID/Windows birth、task/launch_nonce，并拒绝已 stopped 子进程；复用本次 owned_process.launch 新生成的运行 key。parent/status 不调用签发，缺 started 不伪造正常路径。
- 终态原件绑定完整 producer start digest、started receipt SHA 和整个 execution_fact（包括 output_facts/frame_snapshots/EXR SHA）。已存在原件只允许完全相同 payload 的无写重试；改内容拒绝。open_private_file 默认 O_EXCL 创建永久 claim；抢占/未完成 claim 不允许补签，原件不由 mutable operations store 提供。
- client.py:451–452 在读取 COMPLETED 时先验证签名原件，再核验 record 衍生 fact、保存 HIP、实际 EXR；重新采集当前文件不能替代原件。原 P1 同时换 EXR、重算 snapshots/output_facts/execution_fact、保留 start binding 的反例现在期待 RENDER_TERMINAL_ANCHOR_MISMATCH，且原件字节和 scheduler active 保持不变。
- addon.py:13205–13209 已在生成 execution_fact 后、self._save 前，只对 COMPLETED 调用 seal；非 COMPLETED 不签发成功原件。接线为静态核对，本轮未另启动 Main 正在审计的正式通道。
- 缺原件：RENDER_TERMINAL_ANCHOR_REQUIRED；改未签 envelope：RENDER_TERMINAL_ANCHOR_INVALID；改已封 fact：RENDER_TERMINAL_ANCHOR_MISMATCH。旧 start 缺 producer_binding 仍 OPERATION_PRODUCER_BINDING_REQUIRED。reader/status 不生成原件或迁移旧 COMPLETED。

## 实际验证及其限度

已只读核对 P1-RESULT.md、p1-before.log、p1-directed-base-python.log 和对应测试源码。原 before 日志显示可替换；整改日志 14 tests/3.911s/OK，作者记录退出0。正常封存/读取、P1替换、缺失/篡改原件、parent拒签、producer改内容覆盖拒绝、相同无写重试，均来自真实 owned Python 子进程/新key/实际 codec 与文件，业务 operation 字段明确为 synthetic，非 DCC render。首个 venv 转发 PID 不匹配的失败日志仍保留；修正为真实 sys._base_executable，未放宽身份判断。本轮未重跑这14项或任何受控子进程。

本轮独立无进程短回归：实际 EXR 元数据、caller AVAILABLE 不采用、decode期间实际文件替换，3 tests/0.024s/OK，退出0。命令：

```text
.venv/Scripts/python.exe -B tests/unit/test_houdini_output_receipts.py HoudiniOutputReceiptTests.test_observes_actual_physical_metadata_without_color_or_alpha_defaults HoudiniOutputReceiptTests.test_caller_metadata_and_available_are_not_adopted HoudiniOutputReceiptTests.test_replacement_during_decode_is_not_an_immutable_observation
```

另执行 `python -B -` 纯文件拒绝探针（退出0）：setUp 创建显式 temp 文件；只 freeze_binding/persist，不调用 persist_contract_fixture/launch，不创建 signed started/key。实际输出：

```text
old_COMPLETED_without_anchor: RENDER_TERMINAL_ANCHOR_REQUIRED
status_did_not_create_anchor: True
no_actual_signed_started: RENDER_TERMINAL_PRODUCER_REQUIRED
old_start_binding: OPERATION_PRODUCER_BINDING_REQUIRED
```

## 核验 SHA256

| 文件 | SHA256 |
| --- | --- |
| root packages/houdini-bridge/src/houdini_bridge/client.py 与 controller-entry mirror | c08eedddc6e80ea8f16005971f2267eab2bae6c17259c15e0ac25c68998e337b |
| tests/unit/test_houdini_output_receipts.py | b541fcbfb1ffac3551f7e097a6fa4db53cc09d8b2002fb2595f9eaa2fa442d34 |
| plugins/houdini/_impl/houdini_bridge_addon.py | e8e7938303a1019eb5e53421db635cb3c7f71d367f4de7de7dcebe462dc177f2 |
| packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py | f5fed29bfabb96531ad965f81156d26fd57c4f6d31d3272b621a6bf0f4f4c893 |
| packages/dcc-task-runtime/src/dcc_task_runtime/platform_support.py | 7e9f165aa8ed2bcbbb6ba1696a3add12405773486180c70d511f97c8eda30723 |
| p1-before.log | 2a60fca773947ea0401770d33f3236a13d3c360ef1499a8dc2f0969c6322eac7 |
| p1-directed-base-python.log | b503795f93587f07d5455679a3d1de317f75a1b5f866aa7008042c118aaa0c08 |

开始/结束源码 hash 一致，双 client 相同。本轮只写本审查文件，不改实现。签名原件证明 producer 观测不可用普通 store 重摘要替换；不补齐原生颜色/alpha事实，completion_metadata_status 仍 BLOCKED_MISSING_NATIVE_FACTS，metadata 仍空；registry/真实 DCC/全域验收未提升。
