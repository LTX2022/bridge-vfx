# S-06 R4 第二次窄返修与原生接口研究

日期：2026-09-14。本文同时记录 A 窄修和 B 只读原生研究；不是 live Houdini、仿真、烟尘、缓存或视觉验收，也不是第二遍独立评审。

## 结论先行

- A 已补齐“宿主操作已经完成、完成 ownership marker 写失败、重试不能重建”的恢复路径。恢复只读核对同一 completed receipt、intent、HIP 文件证据和实际任务图，再完成 durable finalization/ownership marker；不再次调用 build、observe、cook 或真实 host。
- `HOST_OUTPUT_INCONCLUSIVE` 只要拥有合法 typed `scene_manifest`，也属于可恢复的 stopped completed receipt；它仍然不是成功的烟尘能力证明。
- `RUNNING` receipt 永远不提升为完成。记录为 `GRAPH_MUTATION_STARTED` 且 receipt 仍在运行时，重试继续返回 `UNKNOWN/SCENE_OWNERSHIP_MUTATION_IN_PROGRESS`，保护 `HOST_OPERATION_MUST_NOT_BE_RERUN`。
- B 确认 SideFX HOM 有读取节点类型/参数模板、连接、现有 Geometry/Volume 和现有 DOP data 的原生入口；但这不是本候选已有的绑定。动态菜单实例值、solver 当前图、写入 sentinel、完整 writer 语义和 sourcing boundary 仍缺实证。
- `hou.bridge_s06_native_adapter_v1` 是项目自定义 seam。即使属性和四个 callable 存在，也只标为 `OBSERVED_CUSTOM_SEAM_ONLY`，不清除 SideFX 原生缺口。

## 输入和证据身份

| 项目 | 事实 |
|---|---|
| 返修包 | `Bridge-S06-R4恢复缺口返修包.zip`（历史工作区归档，见交付溯源记录），SHA-256 `f1ba070d71e16cbd26f78fd8a6d94501c1b61b8bf67115a9263b5537f8da0ffe`，`testzip=None` |
| 输入源码备份 | 返修包内 `candidate-source.zip`；原始 SHA 见交付 `input-manifest.json` |
| Houdini 安装 | `/Applications/Houdini/Houdini21.0.631`；本机静态发现，不代表本轮启动成功 |
| 本机节点帮助 | `.../Resources/houdini/help/nodes.zip`，6,002,018 bytes，SHA-256 `7c83e14d77ddaebf0f918244c1747509633b2721a39468eb4ae3efc694886916` |
| 本机 Python 回归 | `/opt/homebrew/.../python3.11`，Python `3.11.16` |
| GUI 模板 JSON | 控制端核对的 `CAPTURED_NOT_BOUND` 文件；SHA-256 `3f49969013ea11850a75688a00a5850c89ffa86acf9ad08331690595ce3a88db` |
| 实机边界 | 独立 hython 退出码 3，stderr 为许可证服务器未返回数据；GUI 曾正常打开；没有修改许可证/设置，未启动真实仿真 |

本机 `nodes.zip` 的读取只用了 `unzip -l`/`unzip -p`，没有解包改写安装目录。报告中的官方文档链接用于交叉核对 HOM 语义；H21.0.631 的具体节点内部定义以本机安装帮助和后续 GUI 只读采集为准。

## A：完成回执收尾恢复

### 问题复现

供应的复现脚本在返修前得到：首次返回 `SCENE_OWNERSHIP_COMPLETION_RECORD_UNCERTAIN`；同一 operation 重试返回 `SCENE_OWNERSHIP_MUTATION_IN_PROGRESS`；host build 只调用一次，slot 已 `RELEASED`，真实 DCC 为 `false`。根因是 controller 在读取 lower completed receipt 之前就用 `GRAPH_MUTATION_STARTED` 提前拒绝。

### 实现边界

`tools/s06_controller.py` 现在按以下顺序处理：

1. 先验证 task identity、receipt store 绑定、唯一 operation record、canonical intent/request hash 和 receipt schema。
2. 仅识别 `COMPLETED` 且结果为 `EXECUTED_HOST_SHORT_SEGMENT` 或 `HOST_OUTPUT_INCONCLUSIVE`、`execution_started=true`、禁止 cache/render、带 typed scene manifest 的 stopped receipt。
3. 通过 `adapter.inspect_scene(read_only)` 重新取得 identity、HIP lstat/hash、dirty 状态、冲突节点和实际图路径。对于原始 `STARTED` 记录，允许在本地派生 completed view 复用 host 校验，但不采信宿主自报的 completed hash。
4. 将实际图路径与 receipt manifest 的 `{graph_root, solver, source_volume}` 精确比较；文件/identity/图漂移返回 `SCENE_OWNERSHIP_RECOVERY_REJECTED`，含 `HOST_OPERATION_MUST_NOT_BE_RERUN`。
5. 只调用 validator 的 `_finalize_completed_operation`（精确 owner/token，已释放时幂等），再写 `GRAPH_MUTATION_COMPLETED`。marker 写失败时仍返回 uncertain，下一次可重复上述只读收尾。

普通执行也会为 `HOST_OUTPUT_INCONCLUSIVE` 写 completed ownership marker，避免“不确定输出但实际操作已完成”再次落在 STARTED 状态。

### A 回归覆盖

`tests/unit/test_s06_r4_contracts_adapter.py` 增加并通过：

- 完成 marker 写失败后只读恢复，`build` 仍为 1 次、恢复结果 `host_mutation_calls=0`；
- typed `HOST_OUTPUT_INCONCLUSIVE/HOST_OUTPUT_EMPTY` receipt 的 marker 写失败恢复；
- HIP 文件证据漂移拒绝，ownership 仍为 `GRAPH_MUTATION_STARTED`，不重跑；
- `RUNNING` receipt 不得提升，第二次调用连 inspect/host 都不重跑；
- 原有 completed receipt replay、task-owned dirty resume 保持通过。

## B：SideFX 原生接口研究

### 已有原生证据

本机 H21.0.631 `nodes.zip` 的相关成员给出以下**节点帮助级**事实（不是实例绑定）：

| 原生定义 | 本机帮助中的内部标识/字段 | 可用于后续绑定的事实 |
|---|---|---|
| DOP Pyro Solver | `pyrosolver::2.0`；`timescale`；输入包含 sourcing/velocity-update 语义 | 时间缩放影响 timestep；不能由帮助文字推出实例菜单 token |
| DOP Volume Source | `volumesource`；`soppath`、`numvolumes`、`volume#`、`vfield#`、`vscale#`、`vnormalize#`、`voperator#` | Source Volume/Target Field 与 Copy/Add 等合并语义；`vnormalize` 按 timestep/24 fps 归一化 |
| SOP Pyro Solver | `pyrosolver`；`srclimitframerange`、`srcrangetype`、`srcframe`、`srcframerange`、`srccyclelength`、`numsources`、`source_voperator#`、`source_voluem#`、`source_vfield#`、`source_vscale#`、`source_vnormalize#` | source range/cycle 可表达停发窗口；最终 token 和实例行仍需真实模板/实例只读 readback |
| Gas Advect Field | `gasadvectfield::2.0`；`field`、`velocity`、`advectscheme` | 目标 field 列表和 velocity field 是原生参数概念 |
| Gas Match Field | `gasmatchfield`；`field`、`referencefield`、SOP reference 语义 | 可用于保证 field 的分辨率/size；会改数据，不能在本轮触发 |
| Gas Calculate | `gascalculate`；`destfield`、`sourcefield`、blend/scale 语义 | 目标字段写入方式必须由实际网络和实验确认 |

SideFX 官方 HOM 文档交叉核对了这些可读取入口：

- [hou.NodeTypeCategory](https://www.sidefx.com/docs/houdini/hom/hou/NodeTypeCategory.html) 的 `nodeTypes()`/`nodeType()` 可按 category 和精确内部名取得类型；[hou.NodeType](https://www.sidefx.com/docs/houdini/hom/hou/NodeType.html) 的 `parmTemplateGroup()`/`parmTemplates()` 可读取参数接口。
- [hou.MenuParmTemplate](https://www.sidefx.com/docs/houdini/hom/hou/MenuParmTemplate.html) 的 `menuItems()`、`menuLabels()`、`menuUseToken()` 和动态 item-generator 标识可区分 token/label 与动态菜单；[hou.Parm](https://www.sidefx.com/docs/houdini/hom/hou/Parm.html) 的 `eval()`/`evalAsString()` 只适合在明确 node path 和 parm name 后读取实例值。
- [hou.Node](https://www.sidefx.com/docs/houdini/hom/hou/Node) 的 `inputNames()`、`inputs()`、`inputConnections()` 和连接的 input/output index 可读回输入拓扑；这些方法不能替代对 solver 行为的 cook 验证。
- [hou.Volume](https://www.sidefx.com/docs/houdini/hom/hou/Volume.html) 的 `resolution()`、`voxelSize()`、`voxel()`、`sample()`、`allVoxels()` 可读取已有 Geometry 中的体积；[hou.Prim](https://www.sidefx.com/docs/houdini/hom/hou/Prim.html) 可读取 primitive 类型、intrinsic 和名称。
- [hou.DopData](https://www.sidefx.com/docs/houdini/hom/hou/DopData.html) 的 `fieldGeometry()`/`geometry()` 能取得现有 DOP field/geometry 的只读 `hou.Geometry`；[hou.DopSimulation](https://www.sidefx.com/docs/houdini/hom/hou/DopSimulation.html) 的 `findData()`、`time()`、`timestep()` 面向已有当前帧 simulation state。访问 simulation 并不自动证明它是本任务产生的，时间移动也不属于本轮只读采集。
- [Pyro Solver](https://www.sidefx.com/docs/houdini/nodes/sop/pyrosolver.html)、[DOP Volume Source](https://www.sidefx.com/docs/houdini/nodes/dop/volumesource.html)、[DOP Pyro Solver](https://www.sidefx.com/docs/houdini/nodes/dop/pyrosolver.html)、[Gas Advect Field](https://www.sidefx.com/docs/houdini/nodes/dop/gasadvectfield.html)、[Gas Match Field](https://www.sidefx.com/docs/houdini/nodes/dop/gasmatchfield.html) 和 [Gas Calculate](https://www.sidefx.com/docs/houdini/nodes/dop/gascalculate.html) 说明了原生 source/target/timestep/solver 语义，但没有给本候选的实际 node path、动态菜单当前返回值或 writer 效果证据。

### 能力分类与缺口

| S-06 所需证据 | 原生可行性 | 本轮状态 | 不应伪造的部分 |
|---|---|---|---|
| H21.0.631 build、category、exact node type、parm template、静态 menu token | 可用 HOM 只读取得 | 已加入 `tools/probe_s06_native_api_evidence.py`；默认不写场景 | 不能把 type definition 当作实例当前值 |
| solver/source 参数内部名、当前值、动态菜单 token/label | API 路径可用，但必须有明确现有 node path 和 parm name | 缺实际实例；collector 支持显式 `parameter_readbacks`，不猜名称 | 不从中文 label 或旧模板推 token |
| input 0 连接 | `inputNames`/`inputs`/`inputConnections` 可只读取得 | collector 可读现有 `/obj` 拓扑；当前空白 GUI 没有任务图证据 | 连接存在不等于 sourcing 生效 |
| density→density、v→vel field snapshot | 对已有 SOP/DOP Geometry/Volume 有原生读回路径 | 仅有接口和静态文档证据；没有本任务 live field | 不从 fake-HOM 或模板 JSON 声称源/目标效果 |
| velocity sentinel 写入与 readback | `hou.Parm.set`、`hou.Volume.setVoxel` 等写 API 存在，之后还需合法刷新和只读读回 | **需要真实 construction experiment**；本轮禁止 | 只读采集不应要求或生成 sentinel 结果 |
| 完整 velocity writer inventory | 图节点和连接可读；public HOM 没有一个等价于“所有字段 writer 效果”的完整枚举接口 | **public HOM 不足以单独完成**；需实际网络定义/受控实验 | 不把节点列表当成 field-level writer 证明 |
| sourcing boundary（source write、solver refresh、不同 token/generation 的前后读回） | 需要写入、刷新/cook、前后同帧读回和 freshness 设计 | **需要真实 construction experiment**；本轮未做 | 不能用两次相同 snapshot 或自定义 provider 存在性替代 |
| smoke capability | 不是 HOM 类型/绑定 API 的静态属性 | **未证明** | 软件回归、collector、fake-HOM、模板、空白 GUI 都不通过 smoke |

### 补采入口与确切缺证需求

新增 `tools/probe_s06_native_api_evidence.py`。它实际采集：

- `hou` 的 HOM 类/函数可用性；
- H21.0.631 中精确列出的 DOP/SOP node type definition、parm template、静态 menu item/label/token 使用方式和动态 generator 是否存在（只记录 generator hash，不输出/执行脚本）；
- 现有 `/obj` 下 node path、类型、输入输出名称、连接 index/path；
- 只有调用者显式提供 `parameter_readbacks={"/exact/node": ("exact_parm",)}` 时，才读取该实例的 `evalAsString`/`eval`；动态 menu items 还必须显式设置 `read_dynamic_menus=True`，不猜测也不隐式运行动态菜单生成器；
- 项目自定义 provider 仅作 `OBSERVED_CUSTOM_SEAM_ONLY` 旁证，固定 `qualifies_as_sidefx_native=false`。

在后续取得**明确现有 solver/source node path** 后，补采命令可用下列形式（仍然不建节点、不 set、不 cook）：

```python
import runpy, json, pathlib, hou
probe = runpy.run_path("/path/to/tools/probe_s06_native_api_evidence.py")
result = probe["capture"](
    hou,
    node_paths=("/exact/solver/path", "/exact/source/path"),
    parameter_readbacks={
        "/exact/solver/path": ("exact_sourcing_parm",),
        "/exact/source/path": ("exact_source_parm",),
    },
    read_dynamic_menus=True,
)
pathlib.Path("/local/workdir/s06-native-api-evidence.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
)
```

如果这些 exact path/parm name 仍不存在，下一条只读需求应直接补“当前 `/obj`/DOP 网络的现有节点路径、`type().name()`、`parmTemplateGroup` 和 input connection readback”；不能要求用户用写入/cook 去制造 sentinel 或 boundary 结果来满足只读采集。只有在另行授权并准备独立 HIP 后，才可进行 construction experiment，并且仍需明确 `density→density`、`v→vel`、rank、坐标/采样域、单位、`vscale`、timestep、frame window、停发时不覆盖既有 `vel` 的证据。

## 本次交付结论

本次是软件候选返修和原生接口研究包：A 的 recovery/no-rerun 逻辑已由 fake-HOM/SQLite 和 supplied reproduction 覆盖；B 给出本机安装帮助、SideFX 官方 HOM 入口和可执行只读 collector。F2 solver sourcing 仍未实现为真实 Houdini 绑定，未运行真实 DCC/simulation/cache/render，也未完成真实 smoke 或生产验收。
