# 菜单合同修复后的真实整链（2026-10-27）

范围 `outputs/official-karma-disklight-h21-menu-20261027-01` 经66项受控软件回归、独立菜单合同复审、完整冻结核验及预算预检，在用户授权“批准你获得能够完成计划的全部预算 / 允许。你一直做到任务完成吧 / 继续”下运行一次。

## 真实进展

官方HIP保存、独立冷开、有效USD导出、CPU参考渲染、签名观测封存、正式派生输入与显示策略冻结均完成；Houdini及Nuke原生alpha校准完成。随后正式GraphRun从空场景构建Bridge图，因单操作工作截止时间失败，未生成Bridge HIP、主图、NK或Nuke主输出。

六次原生进程均已离线认证started/stopped签名及账本停止摘要，均owned_child_wait且无未观测后代。前五项exit0；graph-worker exit−15、TIME_BUDGET_EXCEEDED。共222.4392249584198秒，其中graph-worker109.92293500900269秒。176冻结源不变；范围NATIVE_SCOPE_EXECUTION_FAILED关闭、零自动重试、余额不可复用。官方实验组累计27启动／761.8058998584747秒，旧球体范围29单独记账。

[原始停止认证摘要](evidence/20261027-native-menu-live-01/result.json)。

## 已有证据定位

graph-worker stdout/stderr均为空。journal.sqlite3以mode=ro读取：30条操作全部COMPLETE，无INTENT/UNKNOWN；最后创建geometry_network/grouprange1。不能因此认定该节点卡住或下一节点开始。

supervisor在120秒硬边界内保留最后10秒停止收尾，约110秒停止符合已有合同，不能据此指控deadline错误。总范围仅222/600秒，未耗尽总预算。

30份回执started_at到completed_at合计32.951809秒，首条开始至末条完成101.792615秒，68.840806秒在这些区间外；不能将此间隙完全归因某项函数。静态调用链确定GraphExecutor每create前node.children在owned root内被转成producer-operation，addon在只列直接子节点的handler前后各捕获一次完整任务树参数合同。before捕获又在回执started_at前，因此会落在上述间隙。

最小优化方向：仅managed worker显式选择node.children独立查询事实合同，保留租约/归属、宿主与场景身份、请求结果摘要及持久化校验；明确不证明全场景未变。变更操作仍保持完整before/after场景回执。该改动需软件回归、独立审查及全新冻结后才能真实验证；不盲目增加单操作时长，不复用关闭范围。
