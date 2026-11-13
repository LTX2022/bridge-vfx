# 第二独立最终源码审查

**APPROVED，限指定源码副本。** 插件 SHA256：`da52a167cf56b7a227527967b21de5e2a10b551ca6b40958126ba958ced076b9`，974338 bytes。未发现尚未处理的明确 P1/P2 源码问题。

本次增量已核对：实际输出文件名/子目录保留且 resolve 前做 owned-path 检查；回调产生的资源残留保留并进入 reconcile；全局 gallery 只接受真实 `/stage` LOP network、同版官方默认且无 driver/key/既有资源或 links。HOM 节点比较已经由 Python `is` 修为 `!=`，符合本机 H21 官方 Node 运算符文档。actual root takeover 的 mandatory fence 修复也已复核。

两入口共用新工程资源事务，公开两次不同 UUID 保存仍保留完整 strict before/after/handler 比较、HIP hash 和依赖断言；冷宿主保持保存的项目目录；旧 2.0/HIP 不迁移。新 2.1 仅覆盖实际省略内部的 HDA，定义/静态证明不冒充旧内部 evaluated snapshot。公开参数 eval、预算、身份与停止约束保留。

H21/H22 来源独立；gallery compiled 模板缺口仍明确未采集。软件 String API、合成 HDA 和最低 manager 替身仅证明软件逻辑。UI disabled 不等于 locked。project_environment 继承既有 controller output_root，不声明新增原生授权。

**B 最终夹具增量已通过只读复核。** 三个冻结哈希为 software boundary `f67a51b1…dda50`、native schema boundary `7a9ee509…16026`、project environment tests `fbe8f5dd…977f`。保存临时 STATE_KEY 不污染运行 userdata/静态合同，load 恢复同名原用户值；DefinitionNode 补齐删除 userdata API。不同代理/global/frozen-input 分类定点通过；最终注册工程两次保存与完整重开定点日志通过，18.436 秒。此前缺删除 API 的组合红例保留，未伪称整组通过。统一 core/integration 由 root 另行核验，本报告不预先声称其结果。 本报告没有启动宿主、没有原生重跑或全量测试；真实 HIP/冷重开、Karma 能力、240 秒性能、视觉及生产均为 **NOT_RUN**。详见同名 JSON 的源码绑定与关闭项。

软件宿主身份与最小 HOM API 增量亦通过只读复核：assembly `89a68102…77c`、project tests `fbe8f5dd…977f`、HDA policy tests `bfaae6ba…ae7f`、C1 tests `1ed98510…0170`，当前与冻结副本一致。新 fake HOM 的 UUID/epoch 由真实 addon 创建；同宿主 reload 保留状态、load 仅递增本宿主 epoch，导入失败恢复旧 `hou`/状态键及原缺键状态。生产 addon 与 fresh 门未改。最小 userdata/普通节点遍历与 memory-only setName 接口符合本机 H21 文档；没有新增 HDA 证明或成功回执。原三选择器 epoch 泄漏红例与新前缀通过记录均保留，C1 两定点记录通过 3.371 秒；新组件日志虽已记录 13 例通过，也仅属软件组件证据，不代表 root 最终 core 或原生整体验收。

最终 test-only 附录：`test_controlled_native_readback.py` 冻结为 `2a2d8e81…268d`，仅修正 `test_locked_definition_nodes_survive_fake_hip_save_reopen` 的 fresh 工程资源期望。期望来自经生产 readback 校验的 manifest environment，精确匹配 role/path/type/parameter 并在保存前核对 raw/eval；保存/重开后仍严格比较全合同、定义 digest 和公开资源值，legacy 分支保留。独立逐字节核对 v5 的 1,026 个输入，仅此测试文件变化；移除该唯一方法后的完整模块 AST 相同。v5 原始结果保持 **111 PASS / 1 FAIL / 0 ERROR / 0 SKIP**；补验完整单项 **PASS，12.193 秒**。因此可报告“111 项原运行通过 + 1 项单独补验通过，合并覆盖 112 项”，不能声称一次 112 项全绿。此增量无新 P1/P2，不改变既有原生 NOT_RUN 边界。
