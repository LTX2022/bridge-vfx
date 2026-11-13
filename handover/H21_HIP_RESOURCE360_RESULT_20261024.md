# H21 建图240秒专项：实际结果

**本轮已按批准预算执行，HIP专项未通过。** 第一阶段在工作截止线到达后取消并可信停止；范围已失败封闭，未使用第二次启动名额，没有重试。

## 实际执行

| 项目 | 结果 |
| --- | --- |
| 软件与场景 | Houdini 21.0.631 / sphere_ground_v2 / ACEScg |
| 授权资源 | 建图240秒、冷重开120秒、累计360秒；各含10秒停止预留；2次启动、512MiB、单作业、零重试 |
| 实际启动 | 1次 graph-worker，PID 88463，attempt generation 1 |
| 可信账本计费 | 229.438401秒；未超过建图240秒或累计360秒 |
| 终态 | FAILED_CLOSED / HIP_GRAPH_DEADLINE |
| 停止 | owned_child_wait / CANCEL_REQUESTED / 退出码143；descendant_result_unobserved=false |
| 重作业槽 | stop_confirmed=1；active=0 / RELEASED；无legacy blocker |
| 空间 | 停止记录12,817,119字节，最终观测约12.3MiB；低于512MiB，独立验收未采样全程峰值 |
| 实际进展 | 18个启动检查点；journal 19 COMPLETE、1 INTENT；producer 35 COMPLETED、1 INTENT |
| 工程交付 | 无HIP、无worker result/completion；第二新进程冷重开未运行 |
| 其余阶段 | 不渲染；Nuke、alpha、HY3和视觉均未运行 |

原件：[实际运行目录](../outputs/hip-resource360-20261024-authorized/)。授权、激活、原始stdout、停止复验、两份独立验收和统计见[evidence/20261024-hip360](evidence/20261024-hip360/)。停止后进程清单未发现活动DCC。

## 阻断与可证明范围

直接停止原因是整体建图阶段工作截止线到达。首次producer意图距签名启动74.455233秒；此间包含原生启动和前置工作，不能全部归为原生初始化。

最后未完成操作为 `material_binding → camera` 连接，其producer意图距停止3.848618秒。缺少完成记录只界定未完成位置，不能证明该连接挂死。时间差使用同机墙钟，假设期间无时钟跳变。

本次预算扩大让实际进展增加，但仍未证明完整建图在240秒内可行。内部耗时首因尚未定位，不能据此继续增加预算或更改节点。下一项应先核查正式建图中的重复场景读回、验证及证据持久化成本；目前不将这些候选位置写成已确认根因。本轮不再启动或续用剩余票据。

## 已完成的软件改动与验证

新资源profile `h21_hip_graph_240_cold_120_v1` 显式绑定原生范围、角色和持久期限；旧120秒默认及旧scope语义保持。GraphJobService、worker、监督器和专项driver共用该合同，启动耗时计入期限，不能在ready或重启后重新计时。较紧预算保留；监督器在控制端退出时也独立预留10秒停止时间；旧fenced未启动重排路径保持兼容。

Python3.11定向验证分三组：25/25、15/15、5/5通过；未重复全域全量。13文件增量补丁正反向均逐字节还原，160文件冻结源码匹配。两位独立验收者核对本轮失败闭环；旧207个受保护文件均无变化。软件通过不等于HIP通过。

## 冻结与复验

- review：`a71465dcd171effd94c35b521e5a8c0c6893d64e91783adee991edbd83781418`
- 授权scope：`cd4c4c21afcbe9a9591377ebedbfba384057dcb6e51f0521384990dfc072019c`
- 授权freeze：`bd4fdf7608a8fc6b431421d4da58413911f09b04d5a0797a3b5f8c9eaa7d8aa4`
- 源码清单：`1a57b881a9a35ca18adc2fdd28c29ebe13c7e77e6356a86bb12ca624a99b78ab`

本机冻结CLI已使用原始密钥复验1组started/stopped签名。交付包保留公开回执和验证结果，不导出签名密钥、宿主token、intent或环境；没有原始密钥的接收者不能自行宣称离线HMAC复验通过。

**HIP专项、H21＋Nuke工程闭环与完整M1仍未通过。** 桌面原主工程未改，Git未提交或推送。
