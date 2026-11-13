# F2 solver sourcing：R4 两次返修边界与剩余阻塞

日期：2026-09-14。状态：**SOFTWARE_BOUND_UNVERIFIED_LIVE_DCC**。

本版先后记录两次窄返修，不是 F2 solver sourcing 的真实实现，也不是烟尘能力验收。第二次只补 controller 的 completed-receipt/ownership 收尾恢复和 SideFX 原生接口只读研究；R4-D（真实宿主短段）没有执行。软件测试、fake-HOM、GUI 类型模板采集均不能升格为真实 Houdini、仿真、缓存、渲染、VDB、视觉或 smoke 证据。

## 1. 已核对的模板证据

控制端核对的只读文件：`gui-pyro-templates.json`（控制端保存的本机只读采集文件；其内容和路径不属于候选源码）。

- 文件 SHA-256：`3f49969013ea11850a75688a00a5850c89ffa86acf9ad08331690595ce3a88db`。
- `houdini_version=[21, 0, 631]`，`capture_state=CAPTURED_NOT_BOUND`，`solver_sourcing_implemented=false`，`errors=[]`，`warnings=[]`。
- canonical snapshot SHA-256：`d1a194238b173645e278524cfc3413ee013426263fcc6e63650ff05977670234`。
- 这只是原生类型模板证据，不是 live-DCC 参数写入、cook、缓存、渲染、VDB、视觉或 smoke 证据。

## 2. 绑定合同（源码范围，不代表真实宿主通过）

S-01～S-03 只使用上述构建的模板地址和 token；不按 UI label 猜测内部名，不查询或执行动态菜单。

| 行 | 源字段 | 目标字段 | rank | operator | 参数内部名 |
|---|---|---|---|---|---|
| 1 | `density` | `density` | `scalar` | `add` | `source_volume1` / `source_vfield1` / `source_rank1` / `source_voperator1` |
| 2 | `v` | `vel` | `vector` | `copy` | `source_volume2` / `source_vfield2` / `source_rank2` / `source_voperator2` |

两行都要求 `source_activate#`、`source_vscale#=1.0`、`source_vnormalize#=False`，并核对 solver 的输入 0。时间合同使用 `srcrangetype=sequence`、`srcframerange=time_range`、`srcdocycle=False`、`srccyclelength=range_length`、`startframe=range_start`；读取 `hou.fps()` 与 `timescale`，记录 `timestep_seconds=timescale/fps`，不静默把速度改成每帧位移。

停发不是把 `v` 写成零向量：两行 activation 由 controller-owned constant keyframes 控制，停发帧关闭 row 1/2，因而 `v→vel` 的 Copy 不在 inactive 帧运行。真实目标 `vel` 是否保留，必须由下面的结构化证据单独证明。

## 3. 本次 R4 窄返修

- **R4-1：controller-owned scene ownership**：`tools/s06_controller.py` 在发放授权前，以只读 scene identity、HIP `lstat`/SHA-256/file metadata 和图根约束创建 `bridge.f2.s06-scene-ownership/1.0` 持久记录；记录使用独占创建、fsync 和记录哈希。`bridge.s06.inspect_scene` 没有 controller 记录时只能返回 `record_status=ABSENT`、`owned_project=false`、`fresh_project=false`；它不能接受宿主或模型自报的两个布尔值。带记录时，addon 重新核对 identity、同一 HIP 文件证据、图路径和 phase，再由 controller 判定。
- **R4-1：首次准备与恢复分开**：记录 phase 为 `PREPARED` 时要求干净、无任务图；首个 validator 已取得 claim/lease/slot/frame 守卫后才原子更新为 `GRAPH_MUTATION_STARTED`。若 host 回执丢失或执行不确定，保留 `UNKNOWN/RECONCILIATION_REQUIRED` 和 `HOST_OPERATION_MUST_NOT_BE_RERUN`。成功返回 typed `scene_manifest` 后才记录 `GRAPH_MUTATION_COMPLETED`；完成后的同一任务恢复允许 HIP 因任务自身修改而 dirty，但仍要求磁盘证据、身份和 task-owned graph 精确匹配，外来节点仍拒绝。
- **R4-2：生产 native-host 闸门**：生产 addon 不再读取测试文件里的 `bridge_field_snapshot`、`bridge_apply_velocity_sentinel` 或 `bridge_velocity_writer_inventory`。它只接受 Houdini 提供的严格版本化对象 `hou.bridge_s06_native_adapter_v1`，且必须同时提供 `field_snapshot`、`apply_velocity_sentinel`、`velocity_writer_inventory`、`observe_sourcing_boundary` 四个 callable。缺任一接口时返回 `UNIMPLEMENTED` 能力记录，并在首次 `_fx_build_preview`/节点写入前以 `S06_HOST_CAPABILITY_UNAVAILABLE` 拒绝；不合成 sentinel、snapshot、writer inventory 或全 True transport。
- **R4-3：真实 sourcing boundary 合同**：`observe_sourcing_boundary` 必须由 native provider 返回实际操作的 `pre_sourcing_readback` 与 `post_sourcing_readback`，以及不同的 freshness token、field generation、`source_binding_write=true`、`solver_refresh=true`、输入 0 和 operation id。比较器不再把同一 frame 的重复读取当作 sourcing 证明；缺 boundary、token、generation、sentinel 或 writer inventory 时保持 `unknown`。inactive `v→vel` 仍需非零 baseline 与逐样本/逐分量比较；active 行只能是 `not_applicable`。

上述 production seam 保留 controller 的 task/operation/intent/lease/slot/scene/schedule/receipt 绑定和 durable UNKNOWN/no-rerun 约束。`hou.bridge_s06_native_adapter_v1` 是项目自定义 seam，即便属性/schema/callable 存在，也不是 SideFX 原生 API 证据；测试中的 `_NativeProvider` 只是假宿主，不能代表真实 Houdini 已提供这些能力。controller 之外的 `agent.fx.build_preview` 不能承载 controller-bound S-06 请求。

## 4. 软件验证

新增 fake-HOM/SQLite 用例覆盖：实际 addon inspect 的无记录/匹配记录格式、完成回执后 task-owned dirty resume、缺 native capability 在首写前拒绝、组件方向不同但 aggregate 相同、错域、零 baseline、缺 snapshot、其他 velocity writer、active `not_applicable`、`density→density` / `v→vel` 读回、重复 freshness token、controller 公共签发与窄 transport 全链、统一 request hash/root，以及普通 generic FX 路由拒绝。

返修输入复现（改动前）为：`probe_owned=false`、`probe_fresh=false`；controller 拒绝 `SCENE_OWNERSHIP_NOT_CONFIRMED` 和 `SCENE_NOT_FRESH_TASK_OWNED_PROJECT`。这份复现没有启动真实 DCC。

有效定向入口：

```sh
PYTHONPATH=tests/unit python3.11 -m unittest \
  tests.unit.test_s06_r4_contracts_adapter \
  tests.unit.test_solver_sourcing_host \
  tests.unit.test_f2_solver_validator
```

完整入口：`python3.11 tests/run_tests.py`。本轮 Python 3.11.16 授权本机回归为 663 tests：662 通过，唯一失败是既有 Git-less `HEAD` 身份检查；没有初始化假 Git。受限沙箱中的另一遍额外出现 3 个 loopback bind `PermissionError`，已与源码结果分开记录，不是返修失败。

默认只规划入口：

```sh
python3.11 tools/validate_f2_solver_sourcing.py --capture-json <reviewed-capture.json>
```

该入口实际返回 `PLAN_READY`，明确列出未执行的节点创建、set/readback、短段 cook、模拟缓存、VDB、渲染和视觉检查。`--execute` 另需 controller-issued bundle、operator confirmation、当前 lease/slot/identity；本包不调用。

## 5. 尚未证明的事项与只读补采需求

仍未证明：F2 solver sourcing 的真实实现；真实 Houdini/HOM 写入和 readback；动态菜单实例；真实 solver cook；源/目标体积效果；目标 `vel` 保留；VDB/烟尘；视觉；route/provider；人工 handoff；许可证可用性及任何生产验收。当前模板 JSON 的 `CAPTURED_NOT_BOUND` 和 `solver_sourcing_implemented=false` 不能改写成 live binding。

若后续单独授权 R4-D，只能在 H21.0.631、明确任务自有且已保存的独立 HIP 中补采以下只读/受限证据：`bridge_scene_identity()` 四元组与文件 hash；solver/source 的实际 node path、`type().name()`、`parmTemplateGroup`、当前 parameter readback（含动态字段的具体 token/label）；输入 0 连接；source/target 的 `density`、`v`、`vel` 采样域、坐标空间、单位、分量。当前缺证时使用 `tools/probe_s06_native_api_evidence.py`，它读取 SideFX HOM 类/函数、精确节点类型定义、parm template/static menu、现有拓扑，并且只有显式提供 exact node/parm 名才读实例值；它不把自定义 provider 标 native，也不要求写入/cook sentinel 或 boundary。可核对的 sentinel readback、完整 velocity-writer inventory，以及带不同 token/generation 的 sourcing boundary 属于后续 construction experiment，不是只读采集项。不能提供这些接口证据时，保持具体 `unknown`/`inconclusive`，不猜测菜单或内部节点。旧的 `tools/probe_s06_host_evidence.py` 只保留身份/文件/自定义 seam 旁证，`status=OBSERVED_CUSTOM_SEAM_ONLY` 不代表 SideFX 原生实现。

不执行用户正在编辑的 GUI 工程清空、另存、真实模拟、缓存、渲染、许可证/设置修改；WorkBuddy 完全访问仍只是协作约束，人工 handoff 仍不证明 route/provider。C/D 与教程继续暂停。

## 6. 第二次返修：completed receipt 收尾

`tools/s06_controller.py` 在 ownership phase 为 `PREPARED` 或 `GRAPH_MUTATION_STARTED` 时，先读取并独立校验 lower `COMPLETED` receipt，再只读核对同一 HIP/identity/实际图路径，最后幂等释放精确 slot owner/token 并补写 completed marker。它覆盖 `EXECUTED_HOST_SHORT_SEGMENT` 和 `HOST_OUTPUT_INCONCLUSIVE`，不提升 `RUNNING`，不重跑 host operation。漂移保持 `UNKNOWN/RECONCILIATION_REQUIRED`。

`tests/unit/test_s06_r4_contracts_adapter.py` 的第二次返修用例和输入复现均为软件/fake-HOM/SQLite 证据，不是真实 DCC 或 smoke 证据。

## 7. R4 原生 Provider 实现批次（2026-09-14）

本批新增 Bridge 自己的 `S06NativeProvider` 和插件启动装载链。它不属于 SideFX
内置 API；四个接口不再以 callable 存在性判定 READY，而是通过 capability registry
分别报告 `implemented`、`unimplemented`、`unsupported` 或 `verified`。当前实际
源码状态为：`field_snapshot=implemented`、`velocity_writer_inventory=implemented`，
`apply_velocity_sentinel=unimplemented`、`observe_sourcing_boundary=unimplemented`，
`ready_for_mutation=false`。所以安装 provider 后仍应报告
`BLOCK_BEFORE_NODE_CREATION`，不能推进真实 S-06。

`field_snapshot` 只在明确 `authorized_frame(frame)` 内读取已有
`hou.Geometry.prims()` 的 Volume/VDB；支持 `vel.x/vel.y/vel.z` scalar components
或一个 vector `vel`，记录 resolution、active index/bounding box、transform、voxel
size、units 和固定采样顺序，拒绝不完整、歧义、非有限和超预算数据。普通能力探测
不读取 geometry，也不调用节点 `bridge_*` hook。

`velocity_writer_inventory` 只核对 task-owned 的固定六节点 SOP 图、input 0 和
`density→density` / `v→vel` 两行参数。定向返修后它还必须读回实际
`numsources=2`、逐节点 input 0/额外连接、构建器登记的完整 source program 及合法
`source_control/snippet` 绑定；第三行即使未激活也会返回 `unknown`。结果中的
`complete=true` 仅表示这个固定图/源行 scope，明确
`field_writer_scope_complete=false`、`source_effect_isolated=false`；addon 下游不会
把它当作 solver 内部 writer 全知或 `NO_OTHER_VELOCITY_WRITERS`。它不声称图外
writer 或 cook 后效果已知。sentinel 写入和 sourcing boundary 仍需要另行授权的
独立 owned HIP 受控实验，不能修改只读 `solver.geometry()`、不能以相同 snapshot
或自定义 provider 存在性替代。详见 `docs/s06-r4-native-provider-implementation.md`、
`REMAINING.md` 和 `REVIEW.md`。

## 8. Luna N1/N2 定向返修（2026-09-14）

N1 对 `source_vnormalize#` 只接受 bool、整数 `0/1` 和等值有限浮点
`0.0/1.0`，固定合同要求归一化后为关闭；字符串、`None`、其他整数、其他浮点值和
非有限值均 fail-closed。N2 通过实际 `numsources`、完整 input topology、构建器
`_fx_source_program_registration` 精确程序/绑定和两行 readback 防止第三行或篡改
source program 被漏报为完整。缺失/未知注册定义保持 `unknown`，不发明哈希自证。
