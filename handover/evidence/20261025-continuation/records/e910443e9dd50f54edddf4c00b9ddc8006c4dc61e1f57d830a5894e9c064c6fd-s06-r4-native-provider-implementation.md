# S-06 R4 原生 Provider 实现与证据边界

日期：2026-09-14。本文记录本批源码实现和软件/fake-HOM 回归，不是
Houdini 21.0.631 真机、F2 solver、烟尘、仿真、缓存、渲染或视觉验收。

## 结论

本批新增了 Bridge 自己的 `S06NativeProvider`，并把它接入 Houdini 插件
启动链。它不是 SideFX 内置 provider，也没有把四个 callable 当作 READY。
插件启动时只在 `hou.bridge_s06_native_adapter_v1` 没有既有对象时幂等安装；未知
对象不覆盖。能力注册表要求每个接口单独报告
`implemented`、`unimplemented`、`unsupported` 或 `verified`，只有四个接口均为
`verified` 且 `ready_for_mutation=true` 才允许 S-06 首次图写入。

在当前证据条件下，安装后的状态应为：

| 接口 | 状态 | 实现范围 | 仍缺什么 |
|---|---|---|---|
| `field_snapshot` | `implemented` | 受 `authorized_frame(frame)` 保护，读取现有 `hou.Geometry.prims()` 中的 `hou.Volume`/`hou.VDB` | H21.0.631 实例 readback 尚未验证 |
| `velocity_writer_inventory` | `implemented` | 仅核对任务自有的六个 SOP 子节点、五条 input 0 连接和 solver 两行绑定 | 不能推断图外 writer 或 cook 后 field effect |
| `apply_velocity_sentinel` | `unimplemented` | 不写任何 geometry | 缺可写、可回滚、可 readback 的任务体积句柄 |
| `observe_sourcing_boundary` | `unimplemented` | 不 cook、不刷新、不生成 boundary | 缺 source write、solver refresh、同帧前后不同 freshness 的受控实验 |

因此插件正常加载并不改变 controller 的安全结论：当前仍然
`BLOCK_BEFORE_NODE_CREATION`，不能执行真实 S-06 short segment。

## 字段读取合同

`field_snapshot(node, "vel", stage, frame)` 只接受目标字段 `vel`，并要求调用者
先进入 `authorized_frame(frame)`。它不调用节点上的 `bridge_*` 方法，不合成字段，
也不在 capability probe 中读取 geometry。

支持两种实际 primitive 组织：

1. 恰好一个 `vel.x`、`vel.y`、`vel.z`，每个均为 Volume 或 VDB scalar grid；
2. 恰好一个 `vel`，其 `voxel(index)` 返回三分量 vector。

读取结果包括分辨率、VDB active index offset/bounding box、transform、voxel size、
存储类型（若 HOM 暴露）、primitive 名称、采样 index 和采样顺序。分辨率不超过
4096 个 voxel 时按 `z → y → x` 遍历（x-fastest）；更大网格使用固定上限 4096
个均匀 flat-index 样本。所有数值均检查有限性和分量形状。

快照使用现有 `bridge.f2.velocity-field-snapshot/1.0` 合同，单位字段写为
`scene_units_per_second`，并同时标明这是 solver contract 的单位来源，尚未进行
H21.0.631 live unit verification。一次 guarded HOM read 的 freshness token 只能
标识该读回，不是 sourcing boundary 证据。

## 固定 solver/source 绑定

源码保留并通过 provider 能力合同明确以下地址，地址来自已核对的 H21.0.631
模板快照；动态字段不查询菜单生成器：

| 行 | 源 → 目标 | rank | 合并 | 参数内部名 | token |
|---|---|---|---|---|---|
| 1 | `density → density` | `scalar` | `add` | `source_volume1` / `source_vfield1` / `source_rank1` / `source_voperator1` | `density`、`density`、`scalar`、`add` |
| 2 | `v → vel` | `vector` | `copy` | `source_volume2` / `source_vfield2` / `source_rank2` / `source_voperator2` | `v`、`vel`、`vector`、`copy` |

两行的 `source_vscale#` 为 `1.0`，`source_vnormalize#`（Use Timestep）为
`False`。全局时间字段是 `startframe`、`srcrangetype=sequence`、
`srcframerange`、`srcdocycle=False`、`srccyclelength`；运行时记录
`timescale / hou.fps()`，不把速度静默改成每帧位移。帧窗由 controller-owned
`source_activate#` constant keyframes 控制；停发时关闭 row 2，绝不把 `v` 写成
零向量，因此不会因停发本身覆盖已有 `vel`。是否实际保持仍需要未执行的
source/cook/readback boundary 实验。

## writer 盘点范围

`velocity_writer_inventory` 只接受短段 manifest 的以下固定子图：

`FX_SOURCE (sphere)` → `FX_SOURCE_POINTS (pyrosource)` →
`FX_SOURCE_CONTROL (attribwrangle)` → `FX_SOURCE_VOLUME
(volumerasterizeattributes)` → `FX_SOLVER (pyrosolver)` → `FX_OUTPUT (null)`。

它要求 manifest 角色、直接子节点、精确类型、实际 `numsources=2`、input 0 连接
且没有额外连接、source volume 的 `density v` 属性、构建器登记的完整 source
program 与合法 `source_control/snippet` 绑定，以及两行 solver 字段/菜单/scale/
Use Timestep readback 全部匹配。仅包含 `v@v`/`f@density` 片段不再足以通过。它返回
`global_inventory=false`；`complete=true` 的语义只限上述固定图/源行 scope，并同时
返回 `field_writer_scope_complete=false`、`source_effect_isolated=false`，明确图外
writer 和 solver 内部动力学 writer 未知。addon 下游要求独立的
`field_writer_scope_complete=true` 才能报告 writer isolation；因此固定图盘点不会
打开错误的 source-effect 通路。任何额外子节点、额外连接、类型漂移、参数漂移、
缺失/未知 source program 注册或 `numsources` 非 2 均返回 `complete=false`。

## 受控实验缺口

不能用本 provider 自己的存在、相同 snapshot、fake-HOM、静态模板或 collector
替代以下证据。若要补齐接口，必须另行授权一份已保存且任务自有的独立 HIP：

- 只在授权帧和 bounded ROI 建立 sentinel 的可写 Volume/VDB 句柄，记录首写前
  快照、写入结果、readback 和失败回滚；不得修改只读 `solver.geometry()`；
- 在 source pulse/gap 的短帧窗中只保留一个 velocity writer，记录 input 0、
  `density→density` 与 `v→vel` 参数 readback、`timescale`、`fps`、时间步和
  `source_activate#` 停发状态；
- 在一次明确 operation 中分别取得 `pre_sourcing_readback` 和
  `post_sourcing_readback`，两者须有不同 freshness token/generation；
- 受控实验默认不运行，且不写模拟缓存、不渲染、不外传媒体。实验失败时应保留
  `unimplemented`/`unknown`，不能把软件回归升级为真实验收。
