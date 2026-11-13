# 独立计划审核

审核者：`/root/hip_only_plan_review`，未参与实现。结论：**APPROVED，进入实现及冻结复核；未审核实现不得直接启动**。

源码确认GraphJobService可真实启动正式worker；公开task_host_serve(writer_executable=None,warmup=False)可产生真实task identity/ready且不执行OS映像采集；现有任务重开严格使用真实save合同和快照，恢复原HIP路径。NativeScope和GraphScheduler可复用，无需改全局预算schema或另建执行系统。

实施与冻结复核条件：

1. 共享真实TASK_STATE保存记录，同时区分worker/host各自STATE、ops、lease及runtime namespace。
2. 冷重开显式提供operation_id、request_id、完整scene_before_identity；核对真实transition及epoch，不能落入legacy分支。
3. 同一认证账本、执行锁及固定两阶段限制2次/240秒；扣停止预留，终态封闭，拒第三次调用。
4. 第二阶段NativeScope角色为light，但既有scheduler独占保持到可信停止。
5. 不用生产_h_config；可用现有validate_host(...,allow_missing_writer=True)核对诊断文件绑定，不改变生产门禁。
6. 明确冻结源码API的本机签名验证方式；交付ZIP不含私钥，保留可复验原件与方法。

审核者本轮只读，未运行测试、DCC、vmmap或SQLite。原生结果待一次真实执行判断；实现完成后仍交本审核者复查。
