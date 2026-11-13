# H21 HIP 热路径软件修复结果（2026-10-25）

本轮软件修复及限定独立复核完成，当前候选为 PREPARED_NOT_AUTHORIZED、零启动。真实 HIP 保存/冷重开、性能和完整工程闭环尚未通过。

## 已完成

1. 正式 producer 正常路径从三次全图采集改为 before/after 两次；after 与实际任务根处于同一租约围栏，保留并发接管/CAS/身份校验。
2. 锁定 HDA 使用显式2.1定义及内部静态身份合同，公开参数仍完整读回；旧2.0/1.0原语义和已保存摘要保留。诊断沿既有入口增加有界双时钟锚。
3. worker 在合法建图之前准备新HIP内存路径；公共/注册构建共用新工程资源初始化，稳定绑定项目输出目录，保留活动图片输出名、子目录、产品、帧和ACEScg。严格两次不同路径保存、完整重开及输入哈希约束不变。
4. 参数、manifest和sidecar失败回滚；回调产生的资源残留保留并进入reconcile。全局gallery按精确原生条件分类，HOM节点使用语义等价比较。
5. 软件新宿主获得独立场景身份；同宿主加载递增和插件重载稳定身份保留，导入失败恢复原状态。必要底层HOM模型补齐实际缺失接口、UI disabled语义及序列化容器恢复，不注入成功回执。

## 验证与独立接收

- Python3.11精简核心覆盖**112项**：统一批次111项通过、1项旧固定路径断言失败；该方法按已批准的稳定资源配置更新后单项补验通过（12.193秒）。最终无未解决失败/错误/跳过；原红日志保留。所有生产/夹具输入及其余测试AST逐字一致，仅重验实际改动的方法。[增量接收证明](evidence/20261024-hotpath-repair/final-core-acceptance.json)。累计验证488.078秒。[原始日志](evidence/20261024-hotpath-repair/validation/final/core-tests.log)、[输入与选中覆盖](evidence/20261024-hotpath-repair/validation/final/test-inputs.json)。不是标准全量，也不与重叠定向组累计。
- 最小污染复现链及项目环境10项组合13/13通过；包含真实软件入口两次UUID保存、完整合同/重开、资源拒绝、回滚、冷状态目录、同宿主load/reload和导入失败恢复。[组合记录](evidence/20261024-hotpath-repair/project-environment/b-host-identity-tests.log)。
- 两位独立只读审查按最终源代码及增量核对，无本轮范围内待修明确P1/P2。[状态/围栏](evidence/20261024-hotpath-repair/final-review-state.md)、[原生依据/软件边界](evidence/20261024-hotpath-repair/final-review-native.md)。
- 新候选160份冻结运行文件与当前源码一致；265+207个登记保护原件哈希均未变；preflight无阻断、无活动宿主、零启动。[候选审计](evidence/20261024-hotpath-repair/final-candidate-02-audit.md)。
- controller镜像与源库同步；补丁正反向、完整ZIP和清洁解包结果见交付内对应审计。保留此前失败原件，未改Desktop主工程、未提交或推送Git。

## 冻结与执行边界

当前候选：[prepared-02](../outputs/hip-hotpath-20261025-prepared-02/)，source SHA-256 `ca635d07a487a70d3ed3ef6fe2710dbc5a897518ca5caf5012e64fe3878d1c00`。冻结review：[frozen-review.json](evidence/20261024-hotpath-repair/frozen-review.json)。只完成prepare与不启动宿主的preflight，没有生成新授权或激活范围。

[完整执行合同](H21_HOTPATH_CANDIDATE_20261025.md)绑定热路径、首次保存和项目资源三个实施计划。下一次真实专项须另行明确授权：H21/ACEScg，建图240秒、冷重开120秒、累计360秒，最多2次启动、512MiB、单作业、零重试；失败、超预算或停止未知即停。完整工程原八次启动预算按其独立合同记录，本轮没有消耗或调整。

## 剩余事项与偏差

实际Karma HDA强绑定、Embedded重开和240秒内完成仍待原生验证。H22 gallery精确compiled模板仍NOT_CAPTURED；同版官方默认值及标明synthetic的最小软件API不能代替这一事实。主HIP、NK和主EXR、M1、HY3、视觉及生产均未完成。安装包按工程闭环通过后的计划重建；本轮为源码候选，不将旧wheel当新build。

统一回归新增确认的必要配套为旧fake缺失的HOM接口和跨软件宿主scene epoch隔离。过程中自编验证器出现缺空outputs、共享账本配置等装配偏差，相关日志标为NOT_FINAL_ACCEPTANCE保留；最终验证恢复标准测试入口的账本派生规则。不能把所有历史红例归因于账本：跨宿主污染已由三步链独立复现并在工厂修复。没有新增真实执行、权限或预算。
