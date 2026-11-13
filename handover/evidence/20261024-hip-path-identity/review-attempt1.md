# 首次实施独立复查

审核输入addon SHA-256：`c62c856ace1be9e05a263917cbc0aa77cd06f56929df510a6dd3b5154991f44a`。
原方案审核者：`/root/hip_path_plan_reviewer`；独立代码审查：`/root/hip_path_code_audit`（Bugbot）。结论：**退回整改，未运行完整链，未冻结候选**。

确认的直接关联问题：

- P1：submit_render仍要求当前HIP内存路径等于snapshot，与恢复原路径冲突。须核对原路径并保留snapshot/hash、identity及完整合同围栏。
- P2：reconcile未重建正常任务交接的active_scene/generation/transition绑定就COMPLETED，恢复后同请求重放必然拒绝。须共用交接最终化及回滚，再补恢复→重放验证。
- P2：warning分支可能执行两次load，恢复硬编码before_epoch+1会拒绝已命名的合法状态。须持久绑定实际post-load身份并精确比较，不放宽身份规则。

原审核者已批准限定补修：仅现有addon与核心测试、必要私有helper；共用最终化、通过现有锁/CAS记录受控load事实、render保留全部原有围栏。测试须使用正式调用边界的中断注入，不手改operation制造完成。

其余所查共同出口命名、路径rebind、旧合同与无operation兼容符合方案。首批日志为17项transition/owned、79项checkpoint、1项compatibility通过；controlled主组9通过+1个fixture缺项错误，补齐fixture后该方法单独通过，不是一次全绿。原件保留，后续整改版本另行验证。
