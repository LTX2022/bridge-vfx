# A 最终软件核心验证

当前冻结插件 SHA256：`831b5f6016e480a670150b9066a5e129d6a9e7555a70eefdaeec9f7a5622fbe8`。

本冻结输入下 26 项软件核心测试全部通过：

| 核心组 | 项数 | 原始日志 |
|---|---:|---|
| producer 两次采集、严格根 fence、首次根创建、根漂移/takeover、计时 | 6 | `required-fence-core.log` |
| 正式命令链、receipt 磁盘事实、writer 失败、owned reopen CAS、manifest 保存重开、旧 receipt replay | 6 | `required-fence-followup-core.log` |
| 新 2.1 HDA 强绑定、静态/公开事实漂移、拒绝策略、旧 2.0 原义与字节、policy 选择、保存重开 | 12 | `hda-policy-required-fence.log` |
| controlled 软件 HDA 边界/旧 full 合同、正式插件保存重开 | 2 | `controlled-locked-required-fence.log` |

所有测试使用 Python 3.11 `-I -B`、`TMPDIR=/private/tmp`，工作目录为本证据目录。冻结输入 hash 复核无变化，五个 owned Python 文件编译检查及 `git diff --check` 通过。

producer 保留 before/after 两次 capture；after 的实际 `execution_root` 通过 `required_root` 强制进入同一按根路径排序、按根去重的 ExitStack，调用原严格 `_root_lease_fence`。初步检查完成后、候选根枚举前发生 foreign task/generation takeover 时，即使另有合法 task root，也在进入 after capture 前拒绝。其他根的 fences、身份/frozen 输入、INTENT-before-handler、terminal CAS、失败/不重执行行为保留。

仅实际省略内部节点时使用新 2.1 `locked-hda-definition/1`。完整 binary sections、metadata/options、递归活跃子定义、内部静态 channel/keyframe/连线/flags/userData 绑定；未知 API、可编辑例外、delayed、Data/hard-lock 或不完整静态身份拒绝。无省略并按旧语义完整读取的节点保持原义 2.0。新 2.1 不证明内部 evaluated 值等价；公开参数、既有注册语义和最终输出检查保留。旧 2.0 replay/reopen 按原全内部/eval 策略且不迁移摘要。

首次保存的软件 fixture 与正式 worker 的已批准前置一致：在建图及首次根 lease 前选择尚不存在的 owned HIP 路径，内存 setName、精确读回并确认仍无文件。typed save 的公开 before/after 严格比较、fresh-path、精确 HIP hash 和 reopen epoch/CAS 均未放宽。该 manifest 保存重开项已通过；四个原 `$HIP/$HIPNAME` 差异及实施前复现日志保留为因果证据。

全部 A 文件 hash 见 `frozen-sources.json`；当前输入依赖 hash 见 `frozen-test-inputs.json`；原始前后字节见 `before/`、`after/`；完整增量见 `patches/`。P2 返修前的 `1de9...` 独立审查输入保留在 `review-input-before-required-fence/` 与 `*.before-required-fence.json`，返修增量为 `required-fence.patch`。旧完整 32 项运行因切换返修 build 主动中止，不计为新 build 通过；旧 `1de9...` 下 controlled 全 11 项的通过结果单列保留，不冒用为当前全量结论。

本机 H21 官方 API 依据见 `h21-api-evidence.json`。未启动真实 Houdini/Nuke，未执行原生 cook、渲染或许可命令。真实 Karma 是否满足全部强绑定条件、原生 Embedded 保存重开和性能/240 秒预算均为 `NOT_RUN`，本结果仅为软件核心通过。
