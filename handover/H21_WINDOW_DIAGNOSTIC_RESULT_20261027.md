# H21窗口取证实际结果

本次按用户批准审查 `cd49249107404680d17d634a14647f4d094e8d304ac73303c3162f8e3bc4dac7` 执行一次H21身份诊断。状态 **TIMEOUT_NOT_REPRODUCED_VALID_CONTROL_STACKS**：已取得真实内部对照栈，未复现超时，原慢调用根因未确定。

## 预算与可信停止

| 项目 | 实际 |
|---|---|
| H21启动 | 1次，Hython PID88334；监督器PID88332 |
| 原生记账 | 14.049615秒 |
| 父采集及封存记录 | 14.096195秒，记录点在最终accounting写入前；驱动后置期限检查未报越界 |
| 辅助工具 | 5次sample、11次额外ps；全部完整结束、exit0、leader回收及进程组清理确认 |
| 自然vmmap | 4次，全为原身份链调用；未补调vmmap |
| 有效栈／同次超时栈 | 5／0 |
| 输出范围大小 | 原生范围记账72,966,612字节，低于512MiB |
| 停止 | 签名owned_child_wait，H21 exit0，execution_result=succeeded，无未观测后代；范围已封闭 |
| 累计DCC账 | 10启动／190.444598秒 |

原工具5秒／观察16秒／collection22秒未变，零重试；没有HIP业务、导出、渲染或Nuke。CLI返回2，是identity诊断状态不在通用CLI零退出白名单；结构化结果为IDENTITY_DIAGNOSTIC_FINISHED，原生签名停止为exit0。保留两者，不把CLI返回2改写为0。

## 实际时序与内部位置

以签名子Popen返回为零点：最小worker入口+7.664100秒，标准库后入口+7.664461秒，Bridge导入完成+7.784336秒，ready被观察+8.183397秒，观察完成+13.646378秒。标准库导入前标记证明本次大部分前段发生在worker最小入口之前；+2秒基线原始主线程栈显示Hython正在初始化Houdini并加载DSO，经 GU_Agent::install → UT_DSO::loadDSO → dyld符号绑定。它是正常启动中的一次快照，不证明旧慢启动的首因。

| 原始调用 | 耗时 | 原始快照中的主线程路径 |
|---|---:|---|
| vmmap summary 0 | 2.600403秒 | VMUProcessDescription → processVersionDictionary → binaryImages → CFBundle读取 → 目录枚举 |
| vmmap 定点 1 | 0.626959秒 | 区域记录 → malloc zone遍历 → CoreSymbolication → dyld进程信息 |
| vmmap summary 2 | 1.525123秒 | 同一进程描述路径 → CFBundle可执行信息 → dyld共享缓存路径查询 |
| vmmap 定点 3 | 0.627108秒 | 区域/符号识别路径，含Swift类型元数据处理 |

原超时03也是summary命令，5秒截止时没有stdout。上述两个summary对照显示同种命令可以在进程描述与映像元数据路径内耗时；这缩小了后续分析范围，**不能认定旧超时就发生于该位置**。本次所有原vmmap exit0，未取得同次超时栈；采样本身也会扰动时序。

## 离线修复与复核

原始多线程sample输出完整。冻结版本摘要解析器只识别空白开头的帧，漏掉“+”分支前缀，导致原摘要仅保留后台线程。本轮最小修复资格解析器，使其同时接受已观测的单线程和多线程分支行；PID、报告头、线程、非空原生映像地址、前后OS身份及时序检查保持。

只重解析已有5份原始报告，没有新目标、sample、ps或vmmap。29项定向软件检查通过，包含两份真实多线程fixture、主线程符号保留、无合法线程/地址/身份拒绝。修正后5份原生帧数为62、27、43、27、34。原签名window-captures及其他原件保持；离线核验分别记录原摘要与修正摘要，不回写原报告。

外部观察离线验证器exit0，核验全部16次辅助工具原始流摘要、身份与清理；原生强身份绑定、签名stop及176份冻结源码均复核。[机器验证](evidence/20261027-h21-window-live-01/verification.json)，SHA `6e9004f7ad83731c5c923c15f209341b9b2d4b1ba672a4827ca5675713b16e7f`；[接收回执与公开原始证据](evidence/20261027-h21-window-live-01/accepted.json)。旧完整软件回归问题仍保留，定向通过不代表全量通过。

## 当前边界

本次获准范围执行结束，不复用剩余名额，不自动扩样或重跑整链。可继续离线比较本次主线程栈、旧summary超时证据及所需身份字段；任何下一次原生实验须明确新的可证伪目标和预算。没有本轮新业务HIP、NK或渲染EXR，官方工程交付仍未完成，最终验收依照[官方完整计划](OFFICIAL_KARMA_COMPARISON_PLAN_20261026.md)。
