# GraphJob A：执行、核对与恢复协议

本说明针对本批 `bridge.graph_job_evidence/2.0` 源码。测试范围是普通 Python、真实 SQLite/文件系统/可控子进程和明确标记的 fake host；没有真实 DCC、WorkBuddy/HY3 或视觉验收。用户选择的 **WorkBuddy 桌面 HY3 + 完全访问** 保持不变。协作协议不是抵御同用户任意工具的沙箱或隔离。

## 控制端入口与状态含义

`GraphJobService(..., scheduler_root=安装级持久目录)` 的 `propose`、`trial`、`status` 保留。`request_id` 必须稳定；同 ID 不同内容拒绝。`trial` 重复调用返回原 operation，不是重做授权。

新增可信控制端方法 `reconcile(operation_id, resume_not_started=False)`、`reconcile_orphan()`；保留并加强 `cancel(operation_id)`、`close()`。恢复与取消均未加入 GraphMCP 或 DiagnosticMCP 工具列表，模型不能提交结果证明、进程身份、路径或“已经停机”来释放名额。

| 状态/字段 | 含义及控制端动作 |
|---|---|
| PREPARED → STARTING → RUNNING | 每次下发由 operation、attempt token、generation 和状态 CAS 共同约束。 |
| RECONCILIATION_REQUIRED | 未知/重连/证据不全，继续占用安装级名额；不得换 request_id 或删除状态绕过。 |
| SUCCEEDED | 当前 construction-only 操作的已知结果；必须读取 validation_scope。不是仿真、模型、视觉、发布或任意宿主版本验收。 |
| FAILED | 仅对有确定结果的软件执行分支使用。真实子进程异常退出不能自动说明“没有副作用”。 |
| cancellation_requested=true | 已请求取消，不等于实际停止，也不等于撤回已发生的场景修改。 |
| stop_confirmed=true | 控制端已获得该版本协议要求的停止观察，或原子证明该许可从未下发。 |
| CANCELLED | 已确认不再运行；结果仍未回滚。错误码说明 OUTCOME_NOT_ROLLED_BACK。 |

可信控制端通常先调用 `jobs.reconcile(operation_id)`。只有安装级许可可被原子转为 FENCED_UNSTARTED，才允许在复核 proposal、compiled、catalog 和 runtime 后显式调用 `jobs.reconcile(operation_id, resume_not_started=True)`；沿用 operation ID，更新 token/generation。已经进入 DISPATCHING 的操作，无论超时、无 PID、缺少结果或重启，都不会自动再下发。

## 持久化与成功核对

每个 task root 保留 `graph_jobs.sqlite3`；每个安装级目录保留 `graph_scheduler.sqlite3`，不能把它放进随任务清理的临时目录。新 attempt 文件位于 `graph-jobs/<operation_id>/attempt-<generation>/`：proposal、compiled、inputs、worker_identity、result、completion JSON，journal、scene_lease SQLite，自有 `<operation_id>.hip` 和仅控制端可读的 error.txt。

原子 JSON 使用同目录独占临时文件、文件 fsync、replace 和目录 fsync；失败不把半份 JSON 当成有效结果。持久状态库使用 SQLite WAL，任务/调度连接显式 FULL。跨两个数据库不假装具有分布式原子提交：中断时宁可留下阻塞名额。没有提交本地 operation 的 RESERVED orphan 可由原 task root 的 `reconcile_orphan()` 原子 fence 后释放。重试许可已经轮换但本地 token 未写入时，可信恢复先 fence 该未下发的新代次，再修复本地记录；不会自动启动。

成功恢复校验 protocol、operation/graph ID、attempt token/generation、原始 intention、proposal/compiled/catalog 哈希、运行库及插件的磁盘哈希、调度器绑定的实际进程身份、inputs/identity/result/completion 哈希、自有 HIP 字节和出处、完整 COMPLETE journal 的逻辑内容摘要、已撤销 lease 摘要及对应拓扑。SQLite 摘要读取逻辑内容，不错误地只散列可能落后于 WAL 的主文件。只读取已有文件，不在核对中重开真实 DCC。

已知结果若只丢失控制端最后一次提交，可以恢复，不再次调用宿主。任一文件损坏、缺失、哈希不符、仍有 INTENT/UNKNOWN、产物越界/符号链接、进程仍运行或身份未知，均保持待核对。证据是同用户协作代码间的一致性/来源检查，**不是签名认证、抗同账号恶意篡改证明或已加载插件版本证明**。

## 进程、取消与服务退出

生产启动器只调用一次 Popen，并使用 `start_new_session=True`。自定义 subprocess_factory 必须接受完整 Popen 关键字合同；不能再依赖 TypeError 后换参数重试，因为 TypeError 可能发生在副作用之后。

取消只对本控制端保存的确切 Popen 对象调用 terminate；从磁盘读回的 PID 永远不会作为终止目标。Linux 使用 PID birth 信息及任务自有 session/group 的只读观察；主进程退出但同组子进程仍存活，不释放名额。其他平台对无法确定的存活进程保持未知；macOS 的真实观察、hython 行为和退出顺序待本机验证。

已经自行脱离原组、重新建立 session 的后代进程不在本软件观察保证内。不能声称当前实现包含任意宿主后台进程或同用户工具。必须在真实本机验收中确认目标宿主行为；不能仅凭当前测试宣称进程树完全隔离。

`close()` 拒绝新任务、请求停止自有进程并报告 pending_monitors/unconfirmed_workers；monitor join 总预算为 1 秒，但等待 SQLite 锁或终止调用本身不受该 join 预算限制。忙锁/宿主调用未结束时可能等待或保留未知。未停止不会因为 close 返回而释放名额，已有副作用不会被自动回滚。

## SceneLease 与宿主身份

租约代次/有效期/活动位在每次协作宿主调用前检查，并用 SQLite 写事务将该调用与 revoke/rebind 串行化。已经在途的宿主调用不能撤销；撤销完成后旧执行器不能再进入下一次调用。保存、自有 HIP 重开及验证读取也经过同一边界，过期不会授权另一个执行器接管。

插件新增私有 `graph_worker_identity()`，每次读取宿主真实当前 HIP 路径、进程标识和场景事件代次；不再回显 lease 自报身份。BeforeClear/BeforeLoad/BeforeMerge 使同路径重开也改变场景标识。事件接口缺失、回调被移除或进入 GUI 都拒绝；不为未知宿主编造替代身份。仅已验证的任务自有 save/reopen 可以重绑新的 lease 代次。

官方 API 文档核查（访问日期 2026-09-08）仅用于确认事件 API 形态，不代表本次运行过 Houdini，也不构成版本兼容认证：
`https://www.sidefx.com/docs/houdini/hom/hou/hipFile.html`
`https://www.sidefx.com/docs/houdini/hom/hou/hipFileEventType.html`

## 安装级调度与旧数据升级

同一安装下所有 task root、所有控制端进程、所有由 prepare_workbuddy_graph 生成的 launcher 必须使用同一个持久 scheduler_root。生成器现在把原安装级路径带入快照 launcher，避免每个副本各占一个名额。复制目录、另配 scheduler_root、旧版 worker 或同用户其他工具都可能绕过这个协作范围，因此绝不称作隔离。

数据库添加字段而不删除旧表/数据。v1 记录 generation=0；其旧 PID 和 result.json 缺少新协议的 attempt/来源/子进程证据，**不自动认定成功、不续跑、不因 PID 消失释放**。读取到的旧 active operation 会注册 legacy blocker。无法自动发现没有提供给控制端的所有旧任务目录；升级前必须由本机可信控制端清点旧任务并停止旧 worker，不能混跑旧/新执行器。

没有提供“忽略 legacy/强制清空槽位”的模型入口。无法证明旧任务已静止时继续保留其数据库和阻塞状态。确需迁移到新的调度命名空间，应由本机在完整停机、确认没有在途宿主工作后进行；不是本批自动迁移，也不是绕过未知作业的方法。

## 输出和调用方兼容性

graph_status 重建结构化白名单，不返回任意嵌套 parameters、traceback、命令行、原始诊断文本或绝对本机路径。HIP 只返回该 operation 的相对定位符和摘要；节点路径只允许本次编译图的生成根及有界节点名称。visual_verified 始终 false，software_test/software_fake_host 不升级成真实宿主证明。

这会改变依赖原始 parameters、诊断文本或绝对 hip_path 的旧调用方；控制端应使用自有文件解析定位符，不把这些字段重新暴露给模型。CANCELLED、cancellation_requested、stop_confirmed、validation_scope 为需要适配的新行为。B 的主编排/OperationReceipt/VisualObjective 集成尚未完成，不能把这个独立图服务当成完整主任务执行链。
