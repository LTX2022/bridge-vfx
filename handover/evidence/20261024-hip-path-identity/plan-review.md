# 方案独立审核

审核者：`/root/hip_path_plan_reviewer`。结论：**APPROVED**。

task reopen加载快照未恢复工程路径、replay接受快照路径、reconcile未证明material完整场景之间存在直接因果关系；批准PLAN.md的限定修复。

必要条件：

1. setName位于两种load共同出口和异常捕获外；失败不增加load、不转移租约、不写active_scene或完成记录。rebind改为原路径，保留原hash校验。
2. 加强的路径及active_scene证明只作用于scene.reopen_task_hip；request/result/current/active_scene的原路径、hash、合同摘要、身份及本transition绑定一致。unsaved=True仍验完整合同。replay无load/setName/save。
3. task reconcile验证原路径、原文件hash、已登记且摘要有效的完整合同及当前场景，再保留三个checkpoint；不能要求active_scene必已存在，否则排除命名读回后、active_scene写入前的合法中断。
4. 保留无operation identity的低层调用、v1/v2及旧owned_roots兼容；其他命令不变，旧快照态formal replay拒绝属于预期。
5. 保留geometry restore intent、completion token、generation/saves/manifest回滚；新active_scene绑定字段在同一原子写入及回滚范围内。
6. 指纹算法不变，成功后全局指纹hip_path为原路径。

必要验证还包括命名抛错/错误读回无持久副作用、同路径hash但另一transition的active_scene拒绝、合法INTENT恢复、参数漂移拒绝和完成故障回滚。

审核者未写文件、未运行测试、DCC或数据库；本机H21默认表达式及HOM官方语义采用主控已核实输入。本记录保存其返回结论与条件，实施后仍交同一审核者复查。
