# 一次H21启动前专项

状态：**已获批准并执行，失败封闭。** 实际1启动／22.314564秒，结果见[实际报告](VMMAP_STARTUP_DIAGNOSTIC_RESULT_20261027.md)。以下为获批时冻结范围。 目的：取得与本次慢Hython启动对应的阶段前缀及内部栈，定位发生在 runtime-ready 前的停留位置。上轮[实际结果](VMMAP_SURVEY_RESULT_20261027.md)已封闭；根因尚未确立。

## 范围与预算

- 只准 `official-open-save` 身份阶段，最多 **1次H21 hython／60累计秒／512MiB**，同时1重操作、零失败重试。worker 在身份就绪后直接签名退出，不进入HIP业务；禁止HIP加载/保存/导出、渲染、Nuke、GraphRun。
- 父控制器从启动前计时，60秒包含启动、辅助工具、清理尾段和取证封存。最终 accounting 写入前字段标明测量点；返回后再次核绝对截止，最终写入越界即拒绝。原签名 native stopped 与原生存活账不改写，父总墙钟另报，禁止两者混称。
- 原工具5秒、观察16秒、collection22秒及祖先60秒上限不变，不延长原调用，不省略冻结或身份校验。
- 在监督器 Popen 后立即建立外部见证；由监督器签名的 owned Popen 子PID、父出生身份、scope、ticket、nonce和argv摘要绑定目标。此临时事实只用于选定诊断PID，**不得替代宿主映像证明或放行业务**。
- 额外工具最多 **1次sample、3次ps**（监督器身份1次，Hython前后2次）。只在签名子Popen后15秒仍无有效ready/stop时，采Hython本身1秒栈；sample工具最多2.5秒，前后ps各最多0.35秒，监督器ps最多1秒。共同受collection结束前1秒及父总截止前1秒约束，不足即失败停止。本专项不额外采样vmmap。
- 每辅助进程 stdout≤1MiB、stderr≤16KiB，失败或取消均核 leader reap、进程组消失与线程join；未知状态拒绝通过。已有原身份采集若自然到达仍保持原样，不新增vmmap调用。
- 新增固定阶段：worker Python入口、Bridge导入、authority/intent/scope、冻结校验前后、准入、runtime-ready与返回；监督器端记录collector、冻结、ps、ready等待与原观察阶段。最多32个阶段文件、每份≤8192字节。阶段缺失只能说明证据前缀，不能据此断定不存在该阶段。

## 验收与停止

取得合法PID/父PID/出生时间/可执行路径匹配且具有调用帧的栈，并绑定本次签名子进程和最终原始结果；阶段文件与外部证据完整封存。原始失败仍优先报告，即便取到栈也不能把执行判成功。工具提前正常结束造成未采样时如实报未复现；取证、身份、写盘、清理、预算或冻结失败立即结束，不续跑。

这次只补证据。只有证据能解释具体停留与因果机制后才做最小生产修复；软件测试不能替代真实修复、冷重开或全链验收。下一轮完整链路需独立冻结与明确额度，本次不授予。

## 软件边界结果

本次152项有限回归保留1项失败、4项平台跳过，非全绿。失败为普通Python父进程先退出、后代release/exit0分支的 `execution_result=failed` 与预期unknown不符；未采到具体stop_reason，原因未定，不归因负载或修宽时限。新13项startup边界在同批均通过，但不表示原生诊断成功。沙箱首次回归另有5项受 `/bin/ps` EPERM影响，原日志保留。此前246项中的真实vmmap超时失败本次排除、未改标通过。[完整准备证据](evidence/20261027-startup-diagnostic-readiness/result.json)。此候选只用于定位，不能据此提升整链或功能验收。

## 冻结对象

候选 `outputs/official-startup-diagnostic-candidate-20261027-01/`：

- scope SHA `e7fab412345a9bdf33b28b30b86707e31164e7452b3e18c4603ce70f63b8b7f5`
- bindings SHA `92ca9c744fb5bc08251c2cbf75bfde31d314360bb7a282a3bf9a047f72c23354`
- [激活审查](../outputs/official-startup-diagnostic-candidate-20261027-01/engineering-activation-review.json) SHA `86efae3dce4c43f1ae6d706ba75c3afdc998a8ba21c5368fb8bf8d646daabd55`
- 仅拟激活至 `outputs/official-startup-diagnostic-20261027-01/`，该目标尚未创建。

实际已用6启动／116.560682秒保留；本次如获批，合计最多 **7启动／176.560682秒**。失败三样本批次未用两名额不复用。
