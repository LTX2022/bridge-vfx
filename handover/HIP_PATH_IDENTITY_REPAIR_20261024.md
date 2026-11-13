# HIP 路径身份修复与当前软件阻断

**路径缺陷已修复并通过限定代码复核；完整软件链未通过，不能进入真实验收。未冻结新候选或生成新 review，不使用19 review激活20。**

## 已确认与实施

Opus指出的根因成立：保存合同包含按原HIP路径求值的参数，任务重开却加载摘要命名的快照且未恢复内存工程路径。同版Karma模板中的dcmfilename和productName默认引用$HIP/$HIPNAME；原软件边界没有模拟它们。

本次实际修改7文件，完整前后指纹及可逆补丁见[证据目录](evidence/20261024-hip-path-identity/)。修复保留已校验快照加载、原文件/hash及完整场景合同，恢复并读回原工程路径。任务重放严格绑定合同、身份和transition；正常重开与合法INTENT恢复共用交接、持久化及回滚。实际post-load身份通过既有CAS/digest记录，warning双load不靠放宽epoch校验恢复。render提交同时验证原路径、独立快照及完整合同。

独立复核发现的render路径冲突、恢复后无法重放、warning身份和重复取锁问题均在本轮整改。各域checkpoint仍由原有rebind事务在同一root fence内验证并提交重验；未改变全局锁规则或扩修冻结领域。

## 验证与复核

- 最终20方法通过，包括路径、渲染准入、恢复/重放、三域6个锁组合与失败回滚。HOM、registry metadata及监督器启动事实为明确软件替身。
- 原方案审核者和独立Bugbot对最终限定差异未发现剩余P1/P2，见[最终代码复查](evidence/20261024-hip-path-identity/review-final-code.md)。这不是整体软件或真实宿主验收。
- 7文件补丁正反应用逐字节一致，语法检查通过。源码addon SHA-256：`02393327e93366fc5f3690ad3c021ab3ef7611d1e02838cf4d1deb75675d7005`。
- 旧轮次2,875文件及19的5个控制文件保持原字节；未连接原SQLite，仅按字节核验。
- 旧geometry测试在build-preview前置类型合同处失败，已在修复前相同源码复现，未进入重开；该冻结域的这条回归仍未覆盖。本轮未修它，也未把旧79项checkpoint结果累加成最终全量通过。

## 当前首个阻断

唯一一次[八阶段软件链](evidence/20261024-hip-path-identity/software-chain-01/result.json)失败，50.179秒，源码和执行快照运行前后无漂移。只进入alpha阶段，未到HIP重开：真实macOS工具`/usr/bin/vmmap -w -interleaved -summary 74387`在read_pipes阶段触发固定5秒工具上限，stdout/stderr均0。现有证据未解释其内部原因，不推断CPU、权限或工具缺陷。

该次工作进程为普通Python软件替身，真实Houdini/Nuke未启动。原快照API核对signed started/stopped/ready，OwnedProcessHandle.poll为-15；停止回执为owned_child_wait，失败原因SUPERVISOR_WRITER_COLLECTION_FAILED，登记进程组可信停止。软件scope仅1张alpha-husk票，已带stopped摘要并失败封闭。

vmmap工具自身PID及清理后独立终态未被该诊断持久化。后续一次只读ps检查显示目标PID及vmmap进程当前均不存在；该观察不替代历史停止回执。没有重复采样、重跑整链、延长超时或放宽身份检查。

## 接续边界

下一步应定位vmmap调用的可归因证据，补齐工具PID、逐阶段耗时、截止来源、部分输出及清理终态，再决定最小修复。偶发成功不能证明修复，不用重复整链寻找PASS。

ACEScg、8次真实DCC启动、单次120秒、累计600秒、512MiB、单重作业及零自动重试保持；当前未取得新的真实执行授权。本轮不提交/推送Git，不改Desktop主工程。

真实交付状态未提升：18校准5个EXR已验证；可编辑HIP、HIP冷重开、主EXR验证登记、NK消费/重开及实际主图仍未取得。工程闭环、M1、HY3、视觉及生产验收均未完成。
