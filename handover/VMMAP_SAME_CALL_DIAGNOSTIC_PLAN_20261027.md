# 同次 vmmap 超时内部栈诊断

当前目标是定位真实 hython 身份采集中的同次慢 vmmap，不加载任何HIP、不保存工程、不导出USD、不渲染、不运行Nuke或GraphRun。该诊断不关闭最终HIP→冷开→主渲染→Nuke交付目标。

## 范围和硬限额

- 新模式 official_writer_identity_diagnostic_v1；仅 official-open-save 角色用于原运行时握手和OS身份采集，worker在该握手后直接退出，永不进入_run_owned工程业务。其他原生角色无准入额度。
- 新范围最多1次hython启动、120累计秒、512MiB、同时1重操作、零自动重试；辅助ps/sample、证据及停止清理全部包含在时间和磁盘内。
- 原始工具5秒、观察16秒、collection22秒及祖先链60秒保持；辅助诊断只使用该次工具与外层观察共同有效截止以内的剩余时间。失败后停止结算，不续用旧scope或旧剩余额度。
- 原观察最多自然发生4次vmmap（两次summary与两次原加载地址查询）；禁止补调vmmap或补采。每个存活超过0.5秒的自有vmmap最多1次sample，最多4次sample、8次前后ps；sample单次最多2.5秒，保留清理余量并早于原有效截止结束。辅助采样同时最多1个，槽忙或时间不足记不完整。
- 最大stdout 1MiB、stderr 16KiB/辅助工具；固定自有输出目录，工具组kill/reap、线程join均记录，不发送系统配置或权限修改。

## 数据与验收

1. 运行前冻结控制器、观察器、采样器和原件；固定同版hython、/bin/ps、/usr/bin/sample路径、字节及SHA。新目标目录唯一，旧03快照/回执/失败证据与旧29交付不变。
2. 签名runtime-ready后挂接实际Popen产生的vmmap PID，记录父PID、单调开始/实际spawn/有效截止、原结果及最终清理；异步观察器不改变原成功/原异常。
3. 用有界前后ps核对同一PID/PPID/出生时间、真实vmmap路径及非僵尸状态；sample报告须匹配同一PID并包含非空线程与函数调用内容。
4. 原失败必须仍是同次PROCESS_IMAGE_TIMEOUT，且在其原有效截止前取得的sample确有有效调用栈；将原超时和栈通过同一工具PID绑定进签名started中的trace文件摘要。只有此组合才称“取得同次超时调用内部栈”。
5. 身份采集成功、快速退出、未重现超时、空栈、身份不符、截断、采样失败、写盘失败或清理未知分别记录，不补值、不提升修复验收。任何辅助组清理未知阻止诊断继续；即使身份成功也不进入工程业务。
6. 采样运行属于受观测运行；有效栈只解释该次故障，不证明原路径稳定性。先根据栈和时序提出因果修复、保持等价身份检查，再准备后续整链审查。

## 当前授权与总账

软件配套及具体候选已准备；239项定向回归中235项通过、4项平台跳过，独立只读复核无剩余确定P1/P2。取得具体授权后才启动。现有累计4启动／79.923216秒保留；如果该诊断获批，所有官方实验合计上限5启动／199.923216秒。本次不包含任何后续整链重跑额度。

## 冻结的具体审查

- 候选：`outputs/official-vmmap-identity-candidate-20261027-01/`，PREPARED_NOT_AUTHORIZED、零原生启动。
- scope SHA：`c884cf0e04be22aacbbf438b0912c4e4d4ec6f3a83648f0316a20556ff563475`
- runtime-bindings SHA：`6c89fc733323a50783e3a5ca55c6c4f63452cbf0cfbde784e947d71977be629c`
- [激活审查](../outputs/official-vmmap-identity-candidate-20261027-01/engineering-activation-review.json) SHA：`3878b7fe20dbf04060b7f49d64608c4a2d66c475291445087d4b54bf5fbfd03d`
- 目标：`outputs/official-vmmap-identity-20261027-01/`，尚未创建或激活。

原03启动／就绪／停止回执及192份案例源、213份runtime源保持原样；新候选独立冻结当前源码和工具字节。Houdini停止与辅助组清理分别核验，辅助清理未知时不得称所有自有进程已停止，也不得开始下一范围。

[最终软件验证与冻结证据](evidence/20261027-vmmap-identity-readiness/result.json)。当前未激活，原生启动仍为0；尚未取得同次慢调用内部栈，也未确立vmmap因果修复。

## 实际执行状态

上述审查已由用户批准并执行，1启动／14.236163秒，范围已结束关闭。4次自然vmmap均未超时，只有成功调用栈；详见[专项实际结果](VMMAP_IDENTITY_DIAGNOSTIC_RESULT_20261027.md)。上述未授权描述属于准备时状态，不能再用该审查追加启动。
