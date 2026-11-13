# 官方 Karma 对照：当前真实结果

2026-10-28新增 [DiskLight增量使用交付](../outputs/Bridge-learning-20261028/README.md)：已生成重建HIP/USD/EXR和最终对照NK/Nuke EXR。HIP独立冷开无警告，NK独立冷开渲染成功；两段图像对照均504000个RGBA样本完全相同，色彩lin_ap1。按用户最新决定仅续跑相关步骤，官方参考与alpha复用；不改写旧正式GraphRun失败或将本次声明为其签名登记通过。人工视觉仍由用户验收。以下为旧完整正式链的历史结果。

最新 [菜单修复正式链](NATIVE_MENU_FULL_CHAIN_RESULT_20261027.md)：官方前缀及原生alpha已完成，Bridge建图到30条COMPLETE后单操作时间超限，6进程均签名可信停止。该范围关闭，6启动／222.439225秒；官方累计27启动／761.805900秒。Bridge HIP/NK/主图和人工视觉尚未完成。下文是此前各轮原状态，不覆盖本段最新结论。

最新为 [固定目录正式链结果](EXPORT_DIRECTORY_FULL_CHAIN_RESULT_20261027.md)：完整冷热观测相等，HIP和USD生成；导出后Beauty属性 `driver:parameters:aov:husk:name` 缺失而失败关闭。2启动／71.781315秒、全部签名可信停止，176冻结源不变；官方累计16启动／365.145299秒。参考渲染、alpha、Bridge、NK/Nuke未到达。此前 [Ramp轮](RAMP_FULL_CHAIN_RESULT_20261027.md)的目录值差异已由新轮实机关闭；以下保留历史汇总，不覆盖本段最新结果。

日期：2026-10-27。当前状态：**最新获批sample-header整链已执行，新身份门通过，HIP保存后因ramp参数观察失败封闭；真实整链未通过**。

[最新正式执行结果](SAMPLE_HEADER_FULL_CHAIN_RESULT_20261027.md)：1启动／19.689355秒，`OFFICIAL_NATIVE_RAMP_SHAPE_INVALID`，可信exit1且无未观测后代，零重试。激活、签名回执、账本、176冻结源码和HIP字节均已离线核验。官方实验组累计12启动／222.563704秒，冷开／USD／渲染／Bridge／NK／Nuke均未完成，当前无待执行新原生范围。新身份门仅证明本次通过，不构成旧超时唯一根因或普遍性能证明。此前[迟触发窗口取证](VMMAP_LATE_WINDOW_RESULT_20261027.md)的3份有效对照栈和未复现结论保留。

## 真实结果与消耗

| 实验 | 启动 | 记账秒 | 结果 |
|---|---:|---:|---|
| 官方目标01 | 1 | 17.579465 | 保存前菜单读回错误 |
| 官方目标02 | 1 | 18.705256 | 已保存HIP，相机缓存诊断检查失败 |
| 限定诊断01 | 1 | 28.111844 | 已保存HIP，取得32节点完整诊断原文 |
| 官方目标03 | 1 | 15.526651 | HIP业务释放前vmmap身份采集超时，未保存新业务HIP |
| 身份诊断01 | 1 | 14.236163 | 身份与清理成功，本次未重现vmmap超时 |
| 三样本专项01 | 1 | 22.401303 | 首样本就绪前collection超时，其余NOT_RUN |
| 启动前专项01 | 1 | 22.314564 | 就绪前超时，额外采样被诊断时区错误拒绝 |
| 启动前专项02 | 1 | 24.547631 | 时区通过、sample截止无栈、原就绪失败 |
| 启动前专项03 | 1 | 12.972106 | 身份成功、15秒前就绪，0sample、慢调用未复现 |
| 窗口取证01 | 1 | 14.049615 | 5份有效对照栈，超时未复现 |
| 迟触发窗口01 | 1 | 12.429751 | 3份有效对照栈，超时未复现 |
| sample-header整链01 | 1 | 19.689355 | 新身份门通过，HIP保存后ramp观察失败 |
| 合计 | **12** | **222.563704** | 均可信停止并关闭，零自动重试 |

此合计仅指本表官方实验组；旧球体链及其他历史范围分别记账。

此前限定诊断已执行获批审查`60b72d36eb0019074fdfc183da9c23928de92fd3db55845a1afc079236efafac`，仅一次`official-open-save`。签名停止为`owned_child_wait`、exit1、无未观测后代；`diagnostics_incomplete=false`。完整链路验收保持失败，诊断取证目的已完成。[实际诊断与身份证据](evidence/20261027-official-karma-diagnostic-01/result.json)包含原始公开签名回执与日志，不含密钥；[目标01](evidence/20261027-official-karma-live-01/result.json)、[目标02](evidence/20261027-official-karma-live-02/result.json)记录原样保留。

[最新保存的官方工作HIP](../outputs/official-karma-disklight-h21-sample-header-20261027-01/official/official-cpu.hip)：44,773,632 bytes，SHA `e5abe01251fa104da03aeb6d65b089f86c27ff827068dc9483ddd2b18d239f29`。**只证明保存，未通过冷重开、有效USD或渲染验收。** 本次官方案例尚无新的Bridge HIP、NK、主EXR或Nuke EXR。旧范围29已接收技术链路保留，其验收边界不变。下文各历史段落的“最新”“下一次”均按当时阶段读取，当前状态以本文开头和sample-header结果为准。

## 最新目标03：身份采集阻断

用户已明确批准审查`0b15640fcd5b3c29a51da13edc9bb51ac2021fb6e732f8195e4594e0c7b875ad`及11启动／600累计秒／512MiB预算。目标03激活scope SHA为`83ba26feaf17539c70c39e4b11614ca1d9f212e24879f7b4d8764adaa235b409`，runtime-bindings SHA为`1359db050fe7a1547ab8e3df345ff833b160ccd30a59a0741ed0681c7c8c09d8`。

原始签名started明确记录`ProcessImageError:PROCESS_IMAGE_TIMEOUT`：`/usr/bin/vmmap -w -interleaved -summary 37323`在`read_pipes`阶段超时，stdout与stderr均未读到字节。runtime-ready签名存在；认证started未放行业务，监督器随后终止Houdini。可信停止`owned_child_wait`、exit-15，`descendant_result_unobserved=false`；scope已失败封闭，未自动重试。[目标03实际证据](evidence/20261027-official-karma-live-03/result.json)。

本轮未生成新的业务HIP、USD、EXR或NK；UI观察器修复尚未运行到，不能判为真实修复通过或失败。案例192份及runtime213份冻结源均核对未变化。历史同类vmmap超时尚无因果修复；之后观察到的主机负载仅是环境背景，不能解释本次内部停留位置。

现已补工具PID、阶段／总耗时、5秒工具与外层截止来源、正常kill/reap终态诊断。51项相关软件测试通过、4项平台跳过，独立只读复核无确定P1/P2；原身份检查及5／16／60秒上限不变。该增量只改善诊断，不补回03缺失的工具内部栈，也不等于修复vmmap。[诊断准备记录](evidence/20261027-official-karma-live-03/diagnostic-preparation.json)。

## UI表达式根因与最小修复

唯一非空缓存消息位于camera1，明确指向：

```
IndexError: tuple index out of range
(/stage/lights/backdrop_shallow/ineditlayerblock)
```

安装的同版SOPCreate定义将该隐藏Toggle默认设为Python表达式`hou.pwd().inputs()[0].inEditLayerBlock()`。backdrop无输入；冻结观察器在采集参数时直接求值该字段，UI禁用状态查询也会间接求值它。随后相机的缓存错误指向这一上游字段。相机六个存档成员逐字节不变，backdrop定义与连接也不变；保存后产生的字段0及默认Python通道不代表实际观察值。

观察器改为schema2，仅在固定路径、SOPCreate类型、无输入、隐藏Toggle模板与真实未求值驱动精确匹配时跳过该UI字段；无keyframe通过`rawValue()`核验，有keyframe核对实际表达式与Python语言。记录模板SHA及`NOT_EVALUATED`；UI禁用状态显式null，构造值继续实际求值。其他节点错误／警告、资源闭包和有效USD检查仍严格。原件、HDA、相机和几何不修改。

172项定向软件回归通过，独立只读复核指出的无keyframe常量冒充驱动问题已修复，复核无剩余确定P1/P2。[修复和准备证据](evidence/20261027-official-karma-diagnostic-01/repair-readiness.json)。**修复效果仍须在新获批原生完整链路中验证。**

## 已批准并执行的完整链路审查

- 候选：`outputs/official-karma-disklight-h21-candidate-20261027-04/`，已用于激活目标03；候选本身不启动DCC。
- scope SHA：`3f5c83c1c4dc7a4caef4a543b8584e4e7aa5ed617ef643922872515dbb6c3818`
- runtime-bindings SHA：`bbe6bb54cc135c7ad57cce6743334c073931e1c66040807442f83fc0736d951d`
- [激活审查](../outputs/official-karma-disklight-h21-candidate-20261027-04/engineering-activation-review.json) SHA：`0b15640fcd5b3c29a51da13edc9bb51ac2021fb6e732f8195e4594e0c7b875ad`
- 目标：`outputs/official-karma-disklight-h21-20261027-03/`，已激活并执行1次启动，失败封闭。

该轮批准预算为11启动／600累计秒／512MiB，每操作≤120秒、最多1重操作、零自动重试。实际只用1启动／15.526651秒；原计划明确失败即结算停止，不能用剩余额度重新开始。所有既有实际消耗累计4启动／79.923216秒，证据保留。

下一次最小取证应限定在真实hython的业务释放前，针对同一次慢vmmap记录工具身份／时间／管道和最终reap，并在原5秒截止前由独立有界观察器取得其状态及非空线程栈。空栈或取证失败单独标不完整，不能替换TIMEOUT、放行业务、增时或重试。该原生取证的专用准备已完成：[同次调用专项计划](VMMAP_SAME_CALL_DIAGNOSTIC_PLAN_20261027.md)，审查`3878b7fe20dbf04060b7f49d64608c4a2d66c475291445087d4b54bf5fbfd03d`已批准并执行，1启动／14.236163秒，范围结束。239项软件回归中235通过、4平台跳过，独立复核无剩余确定P1/P2；这不表示内部栈已取得。没有冻结新整链候选，不重复旧普通Python随机采样或申请盲目整链重跑。

## 最新身份专项结果

审查3878b7fe已获批准并实际执行；1启动／14.236163秒，scope诊断结束关闭。4次vmmap均未超时，取得一次成功调用内部栈，仍未取得同次超时栈或因果修复。累计5启动／94.159379秒。新HIP／NK／EXR未产生，详见[专项实际报告](VMMAP_IDENTITY_DIAGNOSTIC_RESULT_20261027.md)。原有案例及失败回执保持。

上述身份专项与三样本范围均已结束。最新启动前专项也已失败封闭；取消Hython采样提前符号预加载的单变量对照也已结束，当前没有待执行真实范围，不含整链授权。历史真实OS超时与普通进程后代终态回归失败保留。
