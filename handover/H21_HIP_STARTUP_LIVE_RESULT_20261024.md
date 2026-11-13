# H21 检查点真实专项结果

**本轮实际执行失败，HIP验收未通过；启动检查点已真实生效。** 用户明确授权按review `1036aecdd4c7c676a1349697fe23dc4282fb20fb6682d37d50a2f33d46016e5e` 激活新的 `hip-startup-checkpoints-20261024-authorized` 范围。仅执行一次冻结driver，第一阶段截止后取消并可信停止，未启动第二阶段、未重试。

## 实际结果

| 项目 | 事实 |
| --- | --- |
| 配置 | H21.0.631、sphere_ground_v2、用户确认ACEScg |
| 上限 | 2次hython、单次120秒、累计240秒、512MiB、单作业、零重试 |
| 本次耗用 | 1次graph-worker，PID54168，109.855351秒，5,930,686字节 |
| 控制端终态 | FAILED_CLOSED / HIP_GRAPH_DEADLINE |
| 可信停止 | owned_child_wait，CANCEL_REQUESTED，退出码-15，descendant_result_unobserved=false |
| scope终态 | NATIVE_SCOPE_EXECUTION_FAILED，已封闭，不续剩余票 |
| 调度终态 | job CANCELLED、stop_confirmed=1；自身槽active=0、RELEASED，无遗留阻塞 |
| 实际进展 | 18条启动检查点齐全；worker identity及journal已生成 |
| 建图记录 | journal为8 COMPLETE、1 INTENT；producer为16 COMPLETED、1 INTENT，其中8条完成记录是查询 |
| 工程与图像 | 无HIP、无worker result/completion、无第二冷重开进程；渲染与Nuke未运行 |

本轮检查点覆盖入口、依赖导入、catalog、解析、编译、runtime指纹、构造输入、进程身份及调度绑定。从 `python_entry` 到 `initialize_evidence_after` 的同进程单调时钟跨度为7.105774917秒。后续已到达真实addon加载、宿主身份读取、lease及GraphExecutor。

## 直接停止原因与首因边界

已确认直接停止原因是整体阶段期限到达。签名启动时间为UTC 11:27:59.095803，首条建图变更producer INTENT为11:29:22.949221，两者相隔83.853418秒；此间包含启动及前置工作，不能将其全部称为纯原生启动耗时。该比较基于同一系统墙钟期间没有跳变的前提。

8条建图变更均记录COMPLETE：task root、geometry/material/render/USD四个网络、ground/grid、ground_import/sopimport、source/sphere。各自producer起止耗时为0.38—1.64秒，不包括操作之间的查询、检查和落盘。

最后 `geometry_import/sopimport` 的producer INTENT始于UTC 11:29:46.725061，可信停止在11:29:48.130936，仅相隔1.405875秒。此前同类型ground_import已成功完成。现有证据与“仍在正常推进时整体期限到达”一致，不能判定geometry_import挂起、createNode异常，或该节点最终必然成功。

最后未证实区间位于 `_fx_producer_dispatch`：INTENT已持久化，尚无COMPLETED/FAILED；其后包含原生命令、创建后场景读取、验证及终态落盘，不能进一步归因到某一调用。原生初始化内部耗时来源仍未知；没有Python首标记的同墙钟锚点，不使用跨时钟相减编造精确原生启动耗时。本轮未调用writer OS映像采集，不把失败归因于vmmap。

## 独立验收与保护

独立审查者 `/root/hip_only_plan_review` 使用冻结API验证账本及started/stopped HMAC和关联摘要；另以只读SQLite核对jobs及scheduler终态，两库检查前后摘要一致。`/root/startup_probe_route` 只读核查检查点、journal和producer时间线。两位均未参与本轮实现或进程操作。

冻结scope SHA-256：`434ec025356c3a433dd856cdf7730a308e031d9b95f6d3e4e302bb056906d0f4`；freeze：`c017a213bec307d1f9f1e5216596933f6bddc42882b39f1ddb86edf5d29c0556`；source：`4381cd5bffa439bf07719a207bfaad66113023952633a1f011ae667c25e364fc`。冻结源码无漂移，上次182个受保护原件全部未变；未改生产代码、Desktop主工程，未提交/推送Git。

原件位于 `outputs/hip-startup-checkpoints-20261024-authorized`；授权、激活、原始结果、本机复验及独立核查见[evidence/20261024-hip-startup-live](evidence/20261024-hip-startup-live/)。HMAC复验使用本机原始密钥，控制端API会获取本机控制锁；交付包不导出私钥、intent、环境或token，也不声称无原始密钥即可离线复验HMAC。

## 后续范围

先分析首条建图变更前约83.85秒的工作及完整图在既定期限内的可行性，再决定最小软件调整或提出具体资源变更。不给最后INTENT直接定罪，不重置就绪后的时钟，不自动延长120秒、追加启动或运行更多宿主。

HIP保存与冷重开、完整工程闭环和M1仍未通过；OS映像NOT_OBSERVED，渲染、Nuke、HY3、视觉及生产验收未执行。本轮授权范围已结束。
