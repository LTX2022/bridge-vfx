# 取消提前符号预加载对照：实际结果

已按用户批准审查 `45a2a2dfdde4241a5f3efa8eb0e79b6559dd6fa01008a90df143cf9ab60e3d04`，在 `outputs/official-startup-diagnostic-20261027-03` 执行唯一一次H21身份阶段。**原身份成功并正常停止；慢调用未复现，sample分支未执行，取内部栈目标未达成。**

## 实际消耗与停止

本次原生记账 **1启动／12.972106秒**；累计 **9启动／176.394983秒**。父accounting在最终accounting写入前测得13.010031秒，测量点明确，封存返回后原driver另核60秒截止，不改写native stopped。

Hython PID29979，由监督器PID29977签名 `owned_child_wait`、exit0、`execution_result=succeeded`、`stop_reason=null`，无未观测后代。scope关闭原因 `OFFICIAL_IDENTITY_DIAGNOSTIC_FINISHED`。真实OS映像锚点、runtime-ready、original identity结果与停止摘要均已核验。

本次额外工具仅1次监督器ps，**0次sample**，没有前后Hython额外ps。辅助leader reap、进程组消失与线程join确认。所有冻结源核对一致，零自动重试。

控制器输出结构化 `IDENTITY_DIAGNOSTIC_FINISHED`，明确 `full_chain_accepted=false`、`hip_business=NOT_RUN`。既有CLI只把PREPARED/AWAITING_HUMAN_REVIEW列为exit0状态，因此shell返回2；这不是原生失败，不能因此重试。本轮不改CLI源码。

## 同次时序

| 相对子Popen | 阶段 |
|---:|---|
| 0.024762秒 | collector开始等待ready |
| 6.246432秒 | 首个worker标记，标准库导入后 |
| 6.358283秒 | Bridge模块导入完成 |
| 6.360927—6.738836秒 | worker冻结校验，耗时0.377909秒 |
| 6.746103秒 | collector确认ready，外部见证取消尚未触发的第15秒采样 |
| 6.746513—12.488676秒 | 原OS身份观察，耗时5.742163秒 |
| 12.507839秒 | worker签名身份结果并退出 |

取证accounting的 `diagnostic_complete=true` 表示该次见证、取消、封存和清理完整，**不表示已取得栈**；实际状态为 `SKIPPED_READY_OR_STOPPED`、`sample_identity_matches=false`。

## 可确认与不可确认

本次没有运行去掉mayDie后的sample语句，因此不能把12.97秒成功归功于这个变更，也不能证明它解决sample截止。没有新的超时同次栈，原vmmap间歇性超时及Hython慢启动根因仍未确定。此前21秒首标记与本次6.25秒属于不同次启动，不能直接当作因果对照。

按已批边界，未进入HIP加载/保存、导出、渲染或Nuke；**没有新增官方可用HIP、NK、USD或EXR，真实整链未通过**。没有源码变化，不重复软件回归；此前37项软件检查及旧真实OS/普通后代终态失败仍按原证据保留。

该scope已结束，剩余启动/时长不复用。本轮没有激活或冻结下一次真实范围；不自动重复相同第15秒方案。后续取证应先设计能覆盖实际慢窗口的观测，再以具体范围和预算取得授权，不能从本次正常结束推导整链GO。

[公开签名、完整阶段与核验](evidence/20261027-startup-live-sample-live-03/result.json)，SHA `38f1302cec62a4139db425337c9e395460ea9ac0b4673450feab5164e154c3d2`，不含签名密钥。
