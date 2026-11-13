# 修正时区后的一次H21启动前诊断

状态：**已批准并执行，失败封闭**。实际1启动／24.547631秒，见[结果](VMMAP_STARTUP_TIMEZONE_RESULT_20261027.md)。以下为该次获批冻结范围。只有诊断出生身份时区比较被修复，原慢启动根因与同次内部栈仍未取得。[前次实际结果](VMMAP_STARTUP_DIAGNOSTIC_RESULT_20261027.md)。

## 固定范围和验收

与已批前次相同：最多1个H21 hython／60秒总墙钟／512MiB，同时1重操作、零失败重试。父总墙钟包含辅助、清理与最终封存；保留原native stopped，原工具5秒／观察16秒／collection22秒不变。只准身份阶段，禁止HIP业务、导出、渲染、Nuke、GraphRun，不含后续整链额度。

由签名子Popen PID、scope／ticket／nonce／argv及监督器出生身份绑定对象。监督器那一次额外ps继承与其签名相同的时区，仍为C语言环境；其余工具UTC和严格出生token比较不变，不将外部诊断当宿主映像证明。

最多1次Hython sample和3次额外ps，未就绪/停止时于签名子Popen后15秒触发一次1秒sample；sample工具上限2.5秒，前后ps各0.35秒、监督器ps1秒，受原collection结束前1秒与父截止前1秒共同约束。每工具stdout≤1MiB、stderr≤16KiB。不额外采样vmmap、不补调原身份工具。阶段仍最多32个／每份8192字节。

取到同次合法PID/父PID/出生/路径匹配且非空调用帧的栈，并与原始调用结果、阶段前缀和签名停止共同封存；任何原始失败、取证错误、清理不明、预算或冻结问题立即停止，不重试。提前正常结束但未取栈时报未复现；不能视为慢启动已修复。取到根因后再最小生产修复，禁止先延时或重跑整链。

## 已验证与未通过

35项定向软件检查通过，含8小时时差回放、默认UTC不变与真实出生不符仍拒绝；不是新增宿主成功记录，不与旧152项累加。旧152项中1个普通进程后代终态失败、4平台跳过及旧真实vmmap超时失败均保留，没有全绿或默认监督兼容通过的声明。[准备证据](evidence/20261027-startup-timezone-readiness/result.json)。

## 冻结审查

- 候选：`outputs/official-startup-diagnostic-candidate-20261027-02/`
- scope SHA：`8ab8506e017d403d016d449de0d6b59034915efda771dc57aca0e79536568d2b`
- bindings SHA：`4172ade13a4e14f9a2a7dd93a520b6a1d6d22a37c6d8394f7f2dbfd89db4e68c`
- [激活审查](../outputs/official-startup-diagnostic-candidate-20261027-02/engineering-activation-review.json) SHA：`2c4cbd7e7c1d8ee10aec2b2d6ac7a0634bcf56f4ffe23b14f06bb546012bf022`
- 仅拟激活目标：`outputs/official-startup-diagnostic-20261027-02/`，尚未创建。

已有原生账7启动／138.875246秒保留。若本次获批，原生账合计最多8启动／198.875246秒；本次父墙钟另严格受60秒上限，包含原生停止后辅助清理与封存。旧关闭范围不续用，后续整链须另行明确授权。
