# 双独立验收

## 验收1：代码与身份等价（review_identity_fix，Bugbot）

结论GO，范围限本轮进程身份采集增量。只读检查固定sample参数、同PID精确三行进度stderr与成功退出、五项唯一头字段、合法非零Load Address、定点唯一r-x __TEXT和完整路径。未知诊断、错PID、非零退出、超额和超时继续拒绝。

同PID正常和主映像搬移原件支持新旧头字段一致、旧Load无TEXT时拒绝。ps、lsof/vnode、安全打开fd/stat/hash、前后双采、完整祖先反向重验及5/16/60秒均保持。runtime及controller镜像同SHA。已只读核对两版Python各28/28日志，未重复测试。无P1/P2发现；不以此替代整链或真实宿主验收。

## 验收2：结果、原件和候选（review_results_fix）

冻结前GO：独立只读认证软件会计journal/anchor/state、8张票据及7组stop，全部exit0、无未知后代；两项账本输出的实际依赖、hash与NK Read/Write连接成立，来源software_test不变。158源码快照及175不可变文件一致，无pyc；单重作业、84.026秒会计与磁盘预算内。-06全部242文件、-07全部183文件集合和SHA一致。

冻结后GO：重新只读认证08 state/journal/anchor零票据且未授权；158快照与整链通过版本、review、当前仓库相同，175不可变文件核验；相对07只有process_image.py生产差异。scope/bindings/review三项SHA与审计匹配，review只指未来09-authorized且该目录不存在，默认预检仅PREPARED，native NOT_RUN、human PENDING。没有新进程、真实DCC或重复测试。

## 证据边界

红日志证明旧实现仍调用全量vmmap、不符合新的定点采集要求，并非本轮再次复现随机超时。有限原型未确定旧Apple工具的具体内部挂点；修复去除了全量VM统计依赖，不声称系统工具永远不会超时。sandbox拒绝日志单独保留，最终OS测试在正常工具权限下通过。

最终接收仅为本轮最小修复、当前正式软件链和08未授权候选；真实工程、视觉、M1、HY3与生产状态不提升。
