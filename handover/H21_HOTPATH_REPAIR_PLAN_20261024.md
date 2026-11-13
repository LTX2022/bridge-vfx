# H21 HIP热路径完整修复计划

用户授权本轮软件修复；真实宿主不在此次执行范围。输入为上一轮已封闭的HIP240实际冻结源码，所有有效修改保留。

执行顺序：输入与原件冻结 → 独立方案审查 → A插件/B消费端/C时钟并行实施 → 核心定向验证 → 两位独立复核并整改 → 候选冻结与统一交付。

完成条件：两次快照及新旧合同路径的软件正常/拒绝/兼容行为成立，诊断有界，发布副本同源，旧原件未变；真实HIP保存/冷重开仍须新范围实跑，不作性能通过声明。原预算240/120/360秒、2启动、512MiB、单作业、零重试不变，所有旧scope保持封闭。

# Bridge 建图热路径最小执行合同

**交付边界**：仅 sphere_ground_v2 已诊断链路；本方案未改代码、未启动 DCC。源码定位基于 `outputs/hip-resource360-20261024-authorized/control/snapshot`。本轮在独立候选仓库 /Users/user/Documents/Code_Project/Bridge 的既有dirty工作区作增量修复，实施前已有160源文件基线及265上轮原件保护记录；冻结证据、Desktop 主工程、预算与已封闭 native scope 均不改。验收分为软件反例通过、原生待验证，不能互相替代。

| 所有者 | 唯一文件责任 | 必须成立的前后行为 |
|---|---|---|
| A：root 指定的插件单写者 | `plugins/houdini/_impl/houdini_bridge_addon.py`；`tests/unit/test_houdini_operation_receipts.py` 及其必要现有 fake fixture | producer 正常路径从 3 次全图 capture 降为 before/after 两次；统一新合同的 HDA 边界与旧合同分支。该大文件只交一人修改；root 的根因补丁如触及该文件，也须由此单写者统一落盘。 |
| B：第三 worker，消费端兼容 | `packages/houdini-bridge/src/houdini_bridge/operation_receipts.py`；`tools/run_hip_diagnostic.py:360`；`tools/readiness_evidence.py:580,585`；对应 schema/receipt/readiness 测试 | 共享严格 header/policy 校验，保留原 digest/CAS，所有消费者接受经验证的 2.1；readiness 的 channel 校验须同时覆盖 2.0/2.1，不能仅放宽 schema 集合。controller-entry 打包镜像由 root 的既有准备/发布链重建并核对，禁止手改冻结镜像或漏发消费端。 |
| C：已派 timing worker | `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py`；`tests/unit/test_graph_worker_startup.py` | 先只在原 startup 标记增加 realtime/monotonic 同点锚；更多分段入口先约定字段再由对应文件单写者落盘。插件计时调用由 A 落入同一文件；不新增执行器、调度器或状态数据库。 |

## 1. 两次采集，保持 fence/CAS

删除 `_fx_producer_dispatch:13272` 的 `produced_scene` 全图采集，保留 `:13208` before 与 `:13274` **同一实际 root lease fence 内** after。进入 fence 的 root：优先采用已验证 before contract；首次 `scene.create_task_root` 用既有严格请求推导出的 root，并核对 handler result path；无 before 的 build_preview 只采用既有任务路径/已验证 manifest 根。request、before、handler、manifest 根不一致或无法唯一确定，阻断；不得用模型任意 root 或额外全图采集“探路”。after execution_root 必须等于所锁根。原身份前后校验、frozen 输入检查、INTENT 先于 mutation、COMPLETED CAS、保存 fresh-path 规则与停止/unknown 语义不改。多 owned-roots 继续由既有 `_task_scene_lease_fence` 获取，不把 fence 外快照挪入作为证明。

## 2. 新 2.1 合同，旧 2.0 保持原义

仅当新 capture 实际含需折叠的锁定 HDA 时，使用 `schema=houdini.task_scene_contract/2.1`、`capture_policy=locked-hda-definition/1`、非空 `hda_boundaries=[...]`。普通无 opaque HDA 场景继续输出原义 2.0，减少无关 fixture/消费者变化；发现锁定 HDA 但缺强绑定证明时，禁止降级 2.0 成功。不能在 2.0 上悄悄改变 nodes 的含义。producer fallback `:13068`、manifest capture `:15855`、save handler `:12773`、verify `:15961`、owned reopen `:16025` 共用同一收集策略：公开拓扑采用现有初始化/绑定 `:6283/:6422` 的 `recurse_in_locked_nodes=False`；显式 manifest 注册节点始终保留；公开节点全部参数仍调用原 `_fx_scene_parameter_readback`，不改为 rawValue、不省掉驱动/值/输入/配置验收。

**每个被折叠的锁定 HDA 必须额外强绑定**：实例路径/精确 type/category、`isLockedHDA=True`、`matchesCurrentDefinition=True`；定义所有 `sections()` 的排序 name + `binaryContents()` 字节数/SHA（不得只取 Contents 或 version），并绑定 `extraFileOptions()`、`extraInfo()`、version/type/category；递归绑定实际内部节点解析到的所有子 HDA 定义，防止同名子定义被替换。`libraryFilePath()` 只作 provenance，语义身份以完整活跃定义内容为准，支持同内容 Embedded 保存/重开，不能只 hash 磁盘库路径。

**不能只 skip 内部**：仍作无 eval 的内部遍历，复用现有 `_houdini_node_graph_fingerprint:10085-10195` 绑定当前内部静态 channel/keyframe、连线、flags、userData；要求 `identity_complete=True`。逐个被省略内部节点检查 `isEditable()` 与 `isEditableInsideLockedHDA()`；任一可编辑例外、delayed definition、定义/section/静态事实不可读均明确阻断。Data/hard-lock 内容在调用现有 fingerprint 的 geometry 分支前先拒绝，除非已有无求值的完整身份事实；不得靠新 geometry/stage/cook 观察建立“提速证明”。边界表须绑定公开 HDA 路径、内部 path/type/definition 集、静态摘要及计数；缺一项即拒绝。不得退回“跳过后成功”，不得调用 syncDelayedDefinition/matchCurrentDefinition/unlock 作为验证副作用。保留原总节点/每节点参数/输出合同字节上限，内部静态遍历仍计入原节点约束；不跨快照缓存可变定义。若现有 fingerprint 在该 HDA 上无法完整且无副作用地绑定，先阻断该新 policy 的成功，交原生证据补齐，不能假称等价。

**兼容选择必须先于 live capture**：旧 2.0 缺 policy 时按旧完整内部/eval 语义采集与验证；现存 1.0 仅保留原已支持验证入口。producer 在既有 runner lock 下先只读 prior/header 以选 prior 的 capture policy，再采 before，随后原 lock/CAS 重新校验 prior 未变；旧完成 receipt replay 不得拿新 2.1 before 与旧 after 直接比较，旧 INTENT/FAILED 继续拒绝自动执行。owned reopen 在现有 root fence 内先读并验 saved receipt/hash，再按其 policy 采 live/比较，load 后同 policy 验证；2.0 不补字段、不迁移、不重算 digest。2.1 缺/错 policy、未知 schema、边界表缺项或被删、定义/静态身份漂移一律拒绝。新旧 save 的精确 HIP hash、scene epoch +1 与 root CAS 行为保留。

### 新合同的验收范围

2.1是显式的新证明合同，不宣称定义内容和内部静态身份等同于旧2.0的全部内部evaluated值。时间、输入stage与外部引用可以改变内部求值；旧2.0的原完整内部验证保持原义。

新2.1仅在原验收所需的公开控制值、通道、连接及既有注册语义/最终输出检查仍完整成立时接受；定义与静态摘要不能替代这些结果。每条producer仍只证明其声明的native_command/task_scene事实，不因此提升AVAILABLE、HIP/工程闭环或真实支持等级。无法证明所需公开及语义覆盖时拒绝成功，不允许通过省略字段、字符串替代实际值或软件回放来收口。

软件验证仅证明协议、正常软件路径与拒绝行为。实际Karma定义完整性、Embedded重开、所需语义覆盖及运行性能均保留原生待验证；本轮不启动宿主。

## 3. 最小计时与核心反例

仅沿现有 `BRIDGE_GRAPH_STARTUP_DIAGNOSTICS` opt-in、owned stderr 加有界标记；每点同取 `time.time_ns()` 与 `time.monotonic_ns()`、pid/native operation ID。本轮阶段限定为既有worker 18个启动标记，以及producer before、native handler、fence内after、receipt validation、INTENT/terminal persist；不增加worker receipt/disk readback或journal completion计时。附公开/内部节点、parm-readback、定义数量；不读取参数内容，不增加 cookCount/needsToCook/stage 诊断求值。日志不写入 scene contract/receipt identity，不改变 inspect equality/请求 hash；写日志失败不得掩盖原异常或修改调度结果。预算仍由原 wall + monotonic 双检查决定，新增锚不重置 deadline。

核心反例只补在现有测试链：正常新 producer capture 恰好 2 次、after 在正确 fence；root 不一致/租约 takeover/身份变更拒绝且不落 COMPLETED；公开参数或 driver/连接漂移拒绝；同 type/version 但任一 section/ExtraFileOptions/子 HDA 定义/内部静态状态改变拒绝；锁定 HDA 的 editable 内部、缺定义/API、delayed definition、不完整静态身份拒绝；新合同缺 policy/边界表被删拒绝；旧 2.0 含内部回执 replay、HIP 保存重开与旧 digest 字节不变；旧 incomplete 不重执行；INTENT/terminal fsync 故障与 reopen CAS 现有反例继续通过；诊断关闭零新增标记、开启可还原 wall↔monotonic、时钟跳变不放宽原预算。

**H21 可依赖的官方接口证据**：本机 `Houdini21.0.631/.../houdini/help/hom.zip`：`hou/HDADefinition.txt:44-72,176-182,339-344,392-396,449-463`；`hou/HDASection.txt:67-73`（Python 3 binary bytes）；`hou/OpNode.txt:794-838`（locked/matches/editable/delayed）；`hou/Node.txt:84-103,146-166`。定义成员 SHA256 `4aa881aa20326c8d03971fd1d3bb55db679b68156daa97f6b3115546a1b56e10`，HDASection 成员 `e3e1dfec18631c7a4f476ebeaae663ae54f832c8142787897258f0a975ccda10`。这些证明接口存在及语义，**不证明实际 Karma HDA 已满足强绑定条件，也不证明 240 秒内完成**；本轮原生未运行，性能、Embedded 重开与定义完整性保留为 native 待验证。
