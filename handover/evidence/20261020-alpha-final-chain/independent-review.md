# 独立代码复核

范围：alpha 独立入口与 driver 的可信激活/共享锁、writer 完整身份重复验证、H21 v2 beauty 路由、诊断日志、owned_process 的 EPERM 路径及其 controller-entry 镜像。复核者未参与这些实现。

结论：原进程组信号被拒后监督器崩溃的 P2 已整改；最终限定代码复核无剩余 P1/P2。TERM 拒绝不制造停止事实，KILL 每两秒限速；首个拒绝事件绑定身份、PID、signal 和 started 摘要。确认整个组消失前，不写 stopped、不结束票据。两份运行库镜像字节一致。

独立运行新增拒绝回归：规范化 /private 临时目录下 1/1 通过。首次默认 /var 临时目录因既有 TASK_PATH_LINK 防线出现两个 ERROR；未放宽生产路径规则。普通监督器其他回归和八阶段集成不由这一单例证明。

Alpha 公开入口保留入口前与锁内两次激活校验，必须为可信本地终端授权的 real_host；软件替身不能调用该入口获得原生执行权限。v2 beauty 参数、orderedVars 路径和重复 writer 身份冻结未发现 P1/P2。

限制：此为代码和定向软件复核，不构成完整软件集成、真实宿主、alpha 数值、视觉或 M1 通过结论。完整链结果单独记录。

纯准备预算按层级分别约束：单工具仍为90秒，激活整体准备允许360秒，覆盖本地冻结和三个顺序子工具；DCC的8次/120秒/600秒预算保持原合同。独立只读复核未发现 P1/P2。

受控 H/N 就绪等待的最终增量复核：无 P1/P2。仅可信 native_scope 路径使用已经校验的 session/budget（最多120秒）作为就绪等待上限；普通路径维持10秒（N为min(10,budget)）。实际 owned supervisor 与 NativeScope 的时间/启动上限均未扩展，nonce/PID/health和未知停止回收门不变。该项复核未重复运行测试，不能代替完整链实证。

会计并发增量：最终源/镜像字节一致。递归磁盘扫描已移到会计锁外，snapshot/check/admit/finish入锁后仍重读最新认证状态，处理票据并提交；保留1秒竞争策略和主driver互斥。独立只读复核无P1/P2，关闭实际复现的长磁盘扫描占锁故障。执行者事件屏障红绿及7项模块回归单独记录，复核者未重复运行。锁内回执读取/fsync若自身超过1秒的风险尚未复现，不宣称消除所有I/O延迟。

压缩夹具增量：独立只读复核无P1/P2。主render child加载保存HIP后，从实际ROP、Stage和唯一RenderProduct属性读取压缩配置；none/zips以外拒绝。ZIPS对typed scanline执行byte-shuffle、predictor及zlib，重建offset表后由生产read_exr完整解码逐行等值自验。仍通过原postframe采集入口，不生成停止/登记回执，也未放宽生产codec或校验器。此结论仅验证软件原生API替身边界，不替代完整链或真实husk。

目录与观察诊断增量：最终源/镜像一致，无剩余P1/P2。只有目录扫描发生FileNotFound且再次lstat确认真实消失才继续；权限拒绝及文件替换仍拒绝。首个观察异常为身份绑定的签名事件。独立复核指出pending-writer首次started写失败可能在TERM前逸出的P2，执行者已先红复现并修复：finish_start、诊断构造与写入位于同一OSError保护，失败回到原停止流程。增强用例验证首次ENOSPC仍TERM，未提前生成stopped或finish票据。持续性核心回执存储失败的旧物理I/O边界未在本轮扩展。

Nuke来源增量：无剩余P1/P2。固定launch.json及摘要只用于恢复入口，仍核对认证scope、同任务可信部署、H owner/parent/producer与路径/来源。H detached output.verify.status重新认证原render、成功整组停止、alpha与当前EXR；宿主及固定worker共用这条来源，不调用H health/RPC或ensure_hosts。无受控配置的普通Nuke路线不引入H依赖。执行者4项定向结果单独保留，审查者未重复运行。

完整full12证据：无P1/P2。只读核对现有测试断言、实际认证budget/started/stopped及两个账本产物。8个software tickets全部停止成功；main-husk共用第二H宿主整组stop。heavy区间不重叠，累计约71.87秒、48,496,903字节。Nuke产物依赖登记H产物，两者保留相同controlled_output_v1/software_test来源；NK与固定render worker快照同SHA。准备candidate仍False/0启动。关键冻结源码与当前源码一致，最终结果为SOFTWARE_CHAIN_COMPLETED、原生NOT_RUN、人工PENDING。审查者没有运行测试/进程；主控原始full12为1/1 PASS（83.720秒），最终受影响核心回归另为42/42 PASS（15.951秒）。不据此宣布原生HIP/NK、真实DCC、视觉或M1完成。

最终候选及文档复核：无P1/P2。-05的scope、bindings与review摘要和报告一致，False/0启动，未来-06-authorized不存在；预算保持8次/120秒/600秒/512MiB/one-heavy/retry0。158项源码/静态快照与当前仓库及通过的full12逐项同SHA，准备回执另绑定175项不可变文件。核心日志42项无跳过。当前导航和报告准确区分软件完成与真实/M1未通过，未将准备或review当作授权。审查者未读取私钥、token或环境秘密，未运行进程。
