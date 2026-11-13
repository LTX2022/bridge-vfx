# vmmap 身份诊断：实际结果

日期：2026-10-27。状态：**诊断已执行并清理；本次未重现超时，根因尚未确立。**

已执行获批审查`3878b7fe20dbf04060b7f49d64608c4a2d66c475291445087d4b54bf5fbfd03d`，目标`outputs/official-vmmap-identity-20261027-01/`。实际1次H21 hython启动，14.236163累计秒，73MB以内磁盘占用；停止签名exit0、无未观察后代，scope以`OFFICIAL_IDENTITY_DIAGNOSTIC_FINISHED`关闭。辅助进程均记录清理完成，线程已join。没有加载或保存HIP、USD导出、渲染、Nuke或GraphRun业务。

| 原调用 | 类型 | 原工具秒 | 栈结果 |
|---|---|---:|---|
| 0 | vmmap summary | 2.514468 | 有效sample栈，PID／父PID／出生与真实帧匹配 |
| 1 | 原加载地址查询 | 0.747145 | 原调用提前成功结束，采样取消 |
| 2 | vmmap summary | 1.588604 | 原调用提前成功结束，采样取消 |
| 3 | 原加载地址查询 | 0.642250 | 原调用提前成功结束，采样取消 |

4个调用均exit0、无`PROCESS_IMAGE_TIMEOUT`。签名trace的`same_timeout_stacks_captured=[]`，其余快速调用取证不完整，因此不能称已取得同次超时内部栈或完成因果修复。

成功调用0的799个采样点经过`VMUVMRegionIdentifier`、`recordRegions`、`markMachOLibraries`，其中共享缓存库遍历与`CoreSymbolication`占据大量采样。它只说明该次成功调用中的工作位置；不能据此解释之前未捕获栈的5秒超时，也不据此修改原时限或身份检查。

[实际签名、所有辅助流及逐调用证据](evidence/20261027-vmmap-identity-live-01/result.json)。原工具5秒、观察16秒、collection22秒与全部身份门禁保持；零重试。此前4次／79.923216秒保留，当前合计**5次／94.159379秒**。新HIP、NK、EXR没有产生，最终工程交付目标保持未完成。

后续[有限三样本取证准备](VMMAP_IDENTITY_SURVEY_PLAN_20261027.md)已完成，未授权、零新启动：拟在一个新scope中按固定顺序取最多3个身份样本，统一120累计秒／512MiB，每角色只1次；前一原调用、身份和清理完整，且取证仅因原调用正常结束取消时才可进入下一样本。真实辅助超时、无效完整sample、持久化、清理或冻结错误均停止整批；任何原始失败也停止。未获新具体授权前不追加启动，不重跑整链。
