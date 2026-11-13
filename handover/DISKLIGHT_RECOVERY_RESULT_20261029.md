# DiskLight Nuke 执行中断与恢复结果

本轮计划已完成。独立agent计划复审、代码复审及冷渲染替代路径复审通过后，真实中断及独立控制端恢复均通过。

| 接收项 | 实际结果 |
| --- | --- |
| 根任务 | 7c65a89096e84533b8f0ace596cfe1c2 |
| 输入 | disklight_incremental_main v2 |
| 真实中断点 | Nuke17、Write1、第1帧、beforeFrameRender原生回调 |
| 旧操作 | nrend-eaa66c4a2ce53d3f，CANCELLED，签名停止和资源释放均确认 |
| 独立控制进程 | 13030 → 32820 |
| 恢复操作 | nrend-5221ad25e8d1e5dc，COMPLETED |
| 登记 | nuke-render-nrend-5221ad25e8d1e5dc v1；中断输出未登记 |
| 图像 | 420×300、frame1、RGBA HALF、ACEScg、lin_ap1 |
| 像素对照 | 主v2→恢复输出，504000个RGBA样本零差异 |
| 幂等 | 旧终态重复查询、冷端完成状态重复查询及同准备再次执行的拒绝均未新增执行或产物版本 |
| 成本 | 本阶段6次原生启动／422.584秒；上限6次／600秒 |
| 停止 | 整个任务家族21条票据全部可信停止；当前范围无关闭错误 |

[工程与文件入口](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/recovery-cold-01/README.md) · [正式清单](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/recovery-cold-01/delivery-manifest.json) · [实际执行结果](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/recovery-cold-01/recovery-result.json) · [中断证据](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/recovery-interrupt-01/interruption-result.json)

范围与事实：原范围因主动取消保持NATIVE_SCOPE_EXECUTION_FAILED，旧失败没有改写为成功；唯一后继继承所有票据及消耗。正常归属门、签名停止和正式登记合同保持。首段宿主及renderer的非零退出属于实际中断事实，不能将本阶段全部启动概括为成功退出。

原主产物v2、原反馈版本1及六份已有交付文件摘要保持。Houdini、Karma、官方参考、alpha和成功上游未重跑。此前经用户批准的旧USD语义恢复副本及摘要差异保持原状态。

定向检查为13项恢复范围/观测/普通Python暂停取消、7项边界归属/缺失残缺输出/真实SQLite资源释放、6项绑定幂等/连接/回滚，7项冷执行请求合同与异常清理，2项状态函数机械提取及2项完整正式合同，共37项均通过；零原生预检通过。恢复采用独立冷渲染续接，复用已原生保存的NK并只调整输出/保存路径；本次实际冷开和原生读回完成后才登记。控制宿主晚到回执和期限失败保持原记录。恢复中定位的原值重复绑定已修复，所有字段/类型/连接和回滚约束保持；宿主期限未延长，失败范围与原始记录保留。独立审核见[计划审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight恢复-20261029/计划独立审核.md)、[代码审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight恢复-20261029/代码独立审核.md)。

此结果仅接收Nuke帧处理入口中断恢复。Houdini图构造/求解中断、任意时刻崩溃、HY3创作、第二案例、H22、全16域、安装迁移和生产接收仍按各自范围判断；人工视觉接收仍待确认。本轮没有提交、推送或重建安装包。

查询边界：完成操作的冷端状态重复查询通过。同一准备文件再次执行会因旧失败操作记录已正常推进为FAILED而拒绝，签名记账字节未变；后续应查询已完成操作，不重发原准备。初始与最终记录摘要均保存在交付清单，原范围和签名回执保持。

[最终独立结果复核：限定技术验收PASS](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight恢复-20261029/最终独立审核.md)。
