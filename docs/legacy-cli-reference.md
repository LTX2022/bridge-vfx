> 历史参考：本文描述 2.0.0-rc.1 的 CLI 合同，不代表当前插件接口或全部能力已验证。当前入口以 [Agent Plugin](agent-plugin.md) 和实际工具目录为准。

# Bridge Skills 2.0 接口文档

本文档描述 `vfx-pipeline` 2.0.0-rc.1 当前已实现的 CLI 和信任边界。它不是完成证明：16 个 v2 领域包现在都是 `experimental`，尚未完成 Houdini 21、Houdini 22、Nuke 17、`DoubaoDesktopRoute` 两级验收和真实参考素材的全量验收。DeepSeek/HY3 是可选适配器；软件单元测试、模拟 DCC 或能力探测不能改变领域状态。

## 1. 运行与持久化

安装后使用 `vfx-pipeline`。从源码直接运行时，等价入口是 `python3 -m vfx_pipeline`。

```bash
vfx-pipeline --state-db /absolute/path/pipeline.sqlite3 capabilities
```

`--state-db` 是全局参数，必须写在子命令之前。如果不指定，数据库使用：

- `VFX_PIPELINE_STATE_DB` 指向的路径；或
- `~/.bridge-skills/vfx-pipeline/pipeline.sqlite3`。

SQLite 持久化任务、事件、证据、候选、工件、审批和经验。`idempotency_key` 与完整任务规格哈希绑定：相同 key 和相同规格复用原任务，相同 key 换规格会被拒绝。

## 2. 命令的信任边界

公开命令分为两个互斥集合。规划模型只能看到 MODEL_SAFE 集合；trusted human-only 命令必须由可信 UI 或操作员控制面调用，不得注册成模型工具。

### MODEL_SAFE

- `capabilities`
- `domain.list`
- `domain.show`
- `graph.catalog`
- `graph.propose`
- `graph.list`
- `execution.register-reference-analysis`
- `model.probe`
- `model.card`
- `model.skill-step`
- `task.plan`
- `task.start`
- `task.status`
- `task.events`
- `task.resume`
- `task.result`
- `feedback.diagnose`
- `candidate.list`
- `candidate.select`
- `approval.request-cache`
- `approval.request-experience`
- `cache.run`
- `verification.record`
- `experience.search`

MODEL_SAFE 的意思是“可向规划模型暴露”，不是“可以绕过审批”。例如 `cache.run` 只能消耗已由人类发放且与当前 subject 完全匹配的 grant；模型不能生成 grant。`verification.record` 只从已登记、重新校验 SHA-256 的数字工件计算分数，不接受模型自报的“已改善”布尔值。

### trusted human-only

- `approval.accept-result`
- `approval.configure-cache-resources`
- `approval.grant-cache`
- `approval.grant-experience`

当前 CLI 不再接受公开常量作为“人类证明”。可信 UI 可以针对 `scope + request/verification + actor` 签发短期流程所需的 HMAC `--trust-proof`；本地操作员也可以在真实 TTY 中使用 `--interactive`，逐字确认 CLI 展示的 scope 与 subject 尾号后，由控制面密钥签发证明。非 TTY 调用不能使用交互模式。这一层是应用控制面认证，不等同于操作系统账号或企业 SSO；生产部署仍应限制可信 UI/CLI 的调用权限，并且绝不能把签发密钥或 trusted human-only 命令暴露给豆包、DeepSeek、HY3 或其它模型。

## 3. TaskSpec v2

`task plan` 和 `task start` 的 `--spec` 必须是只含一个 JSON 对象的文件。下例中的路径和哈希是占位值，运行前必须换成真实绝对路径和内容 SHA-256。

```json
{
  "schema_version": "2.0",
  "task_type": "visual.reference_rebuild",
  "intent": "按参考图重建可编辑烟雾，并修复细节模糊",
  "target": {
    "application": "pipeline",
    "scene_mode": "current",
    "scene_path": null
  },
  "inputs": [],
  "references": [
    {
      "asset_id": "smoke-reference-01",
      "kind": "image",
      "uri": "/absolute/path/smoke-reference.png",
      "sha256": "REPLACE_WITH_ACTUAL_SHA256",
      "color_space": "sRGB",
      "metadata": {}
    }
  ],
  "domains": [
    {"identifier": "pyro_smoke_v1", "version": "1.0.0"}
  ],
  "feedback": "烟太模糊、不够细",
  "constraints": {
    "preserve_existing": true,
    "allow_arbitrary_code": false,
    "protected_attributes": ["silhouette"]
  },
  "render": {
    "resolution": [1280, 720],
    "frame_range": {"start": 1, "end": 48, "step": 1},
    "fps": 24,
    "color_space": "ACEScg"
  },
  "delivery": {"mode": "merge_current", "composite": true},
  "metadata": {"seed": 42, "camera_hash": "REPLACE_WITH_CAMERA_HASH"},
  "idempotency_key": "shot010-smoke-repair-001"
}
```

固定字段为：

- `schema_version` 必须是 `2.0`。
- `task_type` 必须是 `visual.reference_rebuild`。
- `target.application` 必须是 `pipeline`。
- `references[].kind` 只能是 `image`、`sequence`、`video`、`mask`、`depth` 或 `plate`。
- `domains[].version` 当前第一方领域包为 `1.0.0`；Skill/CLI 发布版本 `2.0.0-rc.1` 不是领域包版本。
- 至少提供一个 reference 或非空 feedback。无法唯一选择领域时，显式填写 `domains`。

`task start` 会读取本地 reference、input 和显式 scene 文件并复算 SHA-256；远程 URL 必须先下载为本地不可变文件。`sequence` 必须在 `metadata.frames` 中提供至少两个 `{uri, sha256}` 帧记录，其顶层 `sha256` 是有序帧清单的规范哈希。序列型 input 同样使用显式 `frames` 清单。任一字节变化都会阻止后续执行并撤销已有缓存授权。单张静帧只能约束外观，不能证明真实运动。未显式给帧范围、但反馈命中 motion/timing 规则时，规划器会生成 1–48 帧、24fps 的诊断范围。

## 4. 能力、领域和模型探测

```bash
vfx-pipeline capabilities --refresh
vfx-pipeline domain list
vfx-pipeline domain show pyro_smoke_v1 --version 1.0.0
```

`capabilities` 只表示当前发现的 DCC 实例和其回报能力，不等于领域已经通过真机视觉验收。`domain show` 返回领域阶段 DAG、公开语义控制、缓存失效范围、所需证据和 maturity。

模型配置不允许内联 API key，只可引用环境变量：

```json
{
  "planner": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout": 30
  },
  "vision": {
    "provider": "openai-compatible",
    "model": "hy3",
    "base_url": "http://127.0.0.1:8000/v1",
    "api_key_env": "HY3_API_KEY",
    "timeout": 60
  }
}
```

```bash
vfx-pipeline model probe --config models.json --task-id TASK_ID
```

`model probe` 会实际请求端点：Planner 必须证明严格 JSON 和受限动作合同；Vision 按任务参考素材分别探测单图、多图、序列或视频。原始图像/视频只发给 Vision；Planner 只接收已持久化的结构化分析和精简状态。弱模型的唯一执行入口是下方的 `model skill-step`。

弱桌面模型使用 ID-only 接口：

```bash
vfx-pipeline model card TASK_ID
vfx-pipeline model skill-step TASK_ID --selection selection.json --idempotency-key UNIQUE_KEY
```

`model card` 每次最多返回四个状态有效动作和可选的 control/candidate ID；`selection.json` 只允许 `action_id`、`control_id`、`candidate_id`。路径、脚本、底层参数、数值和审批字段都会被拒绝。豆包桌面由受信任 UI driver 传递 PromptCard，并以 `structured_text_mediated` 记录，不能伪装成原生 tool call。

## 5. 规划、启动和状态

```bash
vfx-pipeline task plan --spec task-v2.json
vfx-pipeline task start --spec task-v2.json
vfx-pipeline task status TASK_ID
vfx-pipeline task events TASK_ID --after-seq 0
vfx-pipeline task result TASK_ID
vfx-pipeline task resume TASK_ID
```

`task plan` 只解析和路由，返回 `spec_hash`、领域、组件分支、DCC route、阶段和安全不变量。`task start` 创建持久化任务并运行初始隔离预览；它需要所选 route 的 DCC Bridge 实例已经运行。`task resume` 只允许从 `AWAITING_INPUT`、`DIAGNOSIS_INCONCLUSIVE` 或 `APPROVAL_REVOKED` 恢复。

DCC 子任务使用显式 `run_mode`：

- `diagnose` 只执行能力探测、可编辑构建、证据采集和技术验证，不执行缓存、最终渲染或 delivery。
- `candidate_preview` 必须带一个非空、最多 5 个公开语义控制的候选；Houdini/Nuke 都先真实写入并读回，再渲染预览，不能把 base 预览冒充候选。
- `delivery` 只有在后续技术证据已经解除早期 `DIAGNOSIS_INCONCLUSIVE` 后，才可进入缓存、最终工件验证和 delivery。

Houdini 成功建立实验性 topology scaffold 会返回 `operation` 成功，同时把结构化结果标记为 `DIAGNOSIS_INCONCLUSIVE`。引擎继续执行 evidence/verify，但暂停在缓存和 delivery 之前；补充字段、AOV 或预览后调用子任务 `resume` 会从第一项技术验证重新采集，不会无操作地返回旧结果。

每个第一方 action 都绑定精确 `GatePolicy`。`capability`、`operation`、`progress`、`verification` 和 `not_applicable` 不能互换；严格任务的 gate 必须显式提供 kind 和布尔 `passed`。`TECH_VERIFY`、`ARTIFACT_VERIFY`、`DELIVER` 至少要有一个 action 名称匹配的 `verification`。结构化响应写入 `TaskResult.step_outputs`/checkpoint，不再寄生在 gate 中；旧 checkpoint 没有 `step_outputs` 时仍可恢复。

主状态链为：

```text
QUEUED -> ANALYZING -> PREVIEWING -> DIAGNOSING -> CANDIDATES_READY
       -> AWAITING_CACHE_APPROVAL -> CACHING -> VERIFYING
       -> AWAITING_EXPERIENCE_APPROVAL -> COMPLETED
```

非模拟候选从 `CANDIDATES_READY` 直接进入 `VERIFYING`。其它可见状态包括 `AWAITING_INPUT`、`DIAGNOSIS_INCONCLUSIVE`、`APPROVAL_REVOKED`、`PARTIAL`、`UNSUPPORTED`、`FAILED` 和 `CANCELLED`。

## 6. 诊断和候选

`feedback diagnose` 不会把“烟太模糊”直接翻译成某个参数。它先生成 `PerceptualIssue`，再根据领域包声明的 signal 和证据 verdict 选择原因族。证据不足时返回 `DIAGNOSIS_INCONCLUSIVE` 和一个 `next_question`。

一个可解析的 smoke evidence 文件示例：

```json
{
  "component_id": "pyro_smoke_v1",
  "roi": [0.1, 0.1, 0.9, 0.9],
  "fixed_frame_range": {"start": 1, "end": 48, "step": 1},
  "fixed_seed": 42,
  "fixed_camera_hash": "REPLACE_WITH_CAMERA_HASH",
  "protected_attributes": ["silhouette"],
  "records": [
    {
      "stage_node_id": "simulation",
      "signal": "pyro_smoke_v1.simulation_evidence",
      "verdict": "supports",
      "value": {"detail_frequency": 0.18},
      "observation": "固定相机与种子后，原始密度场已缺少高频细节",
      "artifact_id": "density-diagnostic-before"
    }
  ],
  "current_parameters": {
    "voxel_size": 0.1,
    "disturbance": 1.0,
    "shredding": 1.0,
    "dissipation": 0.2,
    "turbulence": 1.0
  }
}
```

```bash
vfx-pipeline feedback diagnose TASK_ID --feedback "烟太模糊、不够细" --evidence evidence.json --domain pyro_smoke_v1
vfx-pipeline candidate list TASK_ID
vfx-pipeline candidate select TASK_ID CANDIDATE_ID
```

最多返回 3 个候选，每个候选最多修改 5 个公开语义控制量，且固定种子、相机和帧范围。候选只在隔离变体中预览。复合爆炸包含 fire、smoke、shockwave、particles、RBD 与 composite 分支，只重算已明确映射的单个错误分支；任何未映射控制都会使整个候选在执行前返回 `PARTIAL`，多个模拟分支不会被悄悄合并到一个缓存授权中。

## 7. 第一次审批：Houdini 模拟缓存

仅当已选候选声明 `requires_simulation_cache=true` 时执行：

```bash
vfx-pipeline approval request-cache TASK_ID
vfx-pipeline approval grant-cache REQUEST_ID --actor ARTIST_ID --interactive
vfx-pipeline cache run TASK_ID --grant-id GRANT_ID
```

`request-cache` 把 scene/input/reference 哈希、领域及版本、组件、参数、种子、帧范围、Houdini 版本、依赖和输出路径绑到 `subject_hash`。`grant-cache` 只能授予 `houdini_simulation_cache` scope。`cache run` 再次校验 grant/subject，并向 Houdini 发送有时限的 HMAC 断言；缺失、伪造或已失效授权都被拒绝。

默认共享签名密钥为 `~/.bridge-skills/approval.key`，必须是 owner-only 的普通文件。可用 `BRIDGE_SKILLS_APPROVAL_SECRET_FILE` 替换文件路径，或用进程级 `HOUDINI_BRIDGE_APPROVAL_SECRET` 覆盖；密钥不得写入任务或模型配置。可信 UI 的程序化调用用 `--trust-proof SIGNED_HEX` 代替 `--interactive`，二者不能同时提供。

程序化几何、材质、灯光/相机、渲染参数和 Nuke-only 修复不得请求模拟缓存审批，候选选定后直接进入 `VERIFYING`。

## 8. 技术验证与艺术家确认

`verification record` 只能在 `VERIFYING` 状态运行。before/after 必须是当前任务已登记的、非 reference 的普通文件；文件不能是符号链接，当前 SHA-256 必须与工件记录一致。`raster` 可直接读取不超过 64 MiB 的 EXR、DPX、PNG、TIFF 或 JPEG，并通过固定的 64×64 ImageMagick 灰度采样计算空间指标；JSON 诊断工件继续支持 raster、sequence、field、points 和 geometry。VDB、bgeo 和视频仍需由领域/DCC 诊断导出为带来源哈希的数字工件。

度量文件：

```json
{
  "before_artifact_id": "smoke-detail-before",
  "after_artifact_id": "smoke-detail-after",
  "metric_kind": "raster",
  "target_metric": "raster.edge_energy",
  "minimum_delta": 0.02,
  "protected_metric_limits": {
    "silhouette": {
      "metric": "raster.mean",
      "maximum_relative_change": 0.05
    }
  }
}
```

```bash
vfx-pipeline verification record TASK_ID --measurement measurement.json
vfx-pipeline approval accept-result TASK_ID --actor ARTIST_ID --interactive --verification-id VERIFICATION_ID --verification-hash VERIFICATION_HASH --artist-notes "A/B 确认有效"
```

可用 `metric_kind` 为 `raster`、`sequence`、`field`、`points` 或 `geometry`。对应 JSON 顶层 key 分别是 `raster`、`frames`、`field`、`points` 和 `geometry`。只有目标指标按 issue direction 改善、受保护属性未越界、验证记录未篡改且艺术家显式确认时，`accept-result` 才会创建一份待提升的已验证经验。它不会自动保存经验。

## 9. 第二次审批：经验提升

完成技术验证和 `accept-result` 后：

```bash
vfx-pipeline approval request-experience TASK_ID
vfx-pipeline approval grant-experience REQUEST_ID --actor ARTIST_ID --interactive
vfx-pipeline experience search --domain pyro_smoke_v1 --version 1.0.0 --task-id TASK_ID --limit 5
```

`grant-experience` 只能授予 `repair_experience_promotion` scope，成功提升后任务进入 `COMPLETED`。模拟缓存 grant 不能保存经验，经验 grant 不能写模拟缓存。经验检索按领域和版本精确限定；命中项只能作为新任务的诊断优先级和首选预览，不得跨领域套用，也不得绕过新的验证和缓存审批。

### 操作 store 容量维护

可信控制端可调用 `control.resolve`，参数为 `action: "compact_store"`、实际 `task_id`、可选 `note` 和 `authorization`。签名的规范化 JSON payload 为 `{"action":"compact_store","task_id":"实际任务 ID"}`，沿用现有控制授权密钥与 `verified_by`／HMAC 校验；密钥不能放入模型参数、示例配置或日志。模型工具面不提供此动作。

已有客户端通用入口为 `houdini-bridge --port <端口> call control.resolve --json <完整参数 JSON>`。控制端必须使用实际签发的授权及可信控制通道；维护不接受仅有 `verified_by` 的对象。它只处理指定任务的元数据，不启动宿主作业，不改变结果，不释放任何重作业槽。

正常 store 读写仍受 64 MiB 限制。operations 与 scene_transitions 均按每条记录最多 8 MiB 校验，活跃操作及场景转换 INTENT 各自保留终态容量；非空历史预检预算表始终独立保留一份预检额度，不按历史 ID 数量重复计入，也不抵扣活动操作的额度；容量不足时保留旧文件并返回 `RENDER_OBSERVATION_BUDGET_EXCEEDED`。维护入口按流处理不超过 512 MiB 的现有历史 store，保留原样带摘要快照，先逐条写入两类记录的不可变终态档案，再原子替换为带 family／任务／操作身份的轻量索引；未知／活跃操作保持原状。磁盘可用空间不足、单条超限、身份不符、重复 JSON 键、损坏档案或符号链接均拒绝，不删减历史来换取成功。

成功响应 `compacted` 中含 `archived_operations`、`source_sha256`、`preserved_snapshot` 和 `operation_store_path`。终态查询及同 request ID 重试按 ID 校验并读取原档案，内容变化仍拒绝；不会重新执行。已可信停止、但旧满 store 无法写入终态时，先完成此维护，再用原 binding 重试状态恢复；该恢复自行验证原监督器停止回执并释放本操作的槽。维护中断保留旧 snapshot 或已完整落地的引用，重复维护可继续使用既有档案。维护上限之外或不可压缩的活跃数据仍明确阻断，需要另行核查，不能改成空 store。

## 10. 错误输出和恢复

成功时 stdout 输出缩进 JSON，返回码为 0。已捕获的合同、策略、路由或 I/O 错误在 stderr 输出一行 JSON，返回码为 2：

```json
{
  "status": "error",
  "error_code": "DIAGNOSIS_INCONCLUSIVE",
  "message": "available evidence does not support a causal hypothesis",
  "details": {"missing_signals": ["..."]}
}
```

调用方应根据 `error_code`、当前 state 和 `details` 恢复，不要从英文 message 猜分支。`DIAGNOSIS_INCONCLUSIVE` 只询问返回的一项 `next_question`；`APPROVAL_SUBJECT_MISMATCH` 或 `APPROVAL_REVOKED` 需要基于当前完整 subject 重新请求审批；`INSTANCE_NOT_FOUND` 先启动并检查相应 DCC Bridge。

## 11. 当前实现边界

- 16 个领域包已登记语义合同、阶段 DAG、公开控制、诊断规则和路由，但当前 maturity 全部仍为 `experimental`。
- Houdini 领域适配当前是 topology scaffold/experimental，不得作为 15 个 Houdini/Karma 领域已真实支持的证据。
- 当前指标引擎已支持确定性数字 JSON，并可通过固定 ImageMagick 代理直接采样单帧 EXR/常见 raster；ACES 精确颜色、AOV 语义、VDB/bgeo 和视频解码与全部真机视觉门禁仍需完成。
- 没有已索引的 Houdini 21、Houdini 22、Nuke 17、`DoubaoDesktopRoute` UI 控制、逐领域 Skill 符合性和每领域真实参考案例证据时，不得宣布“全覆盖完成”。DeepSeek/HY3 证据只能证明可选适配器。
- 真实证据与 maturity 以 `outputs/live-validation/index.json` 和 `docs/domain-support.md` 为准。既有 v1.4 证据不自动升级为 v2 领域证据。

本接口不提供任意 Python、HScript 或 Nuke 脚本执行。参考素材只能进入诊断分支，不得出现在最终 Nuke Write 的递归上游。
