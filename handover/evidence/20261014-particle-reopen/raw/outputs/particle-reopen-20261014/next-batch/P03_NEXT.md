# P03 下一批准备（只读，2026-10-14）

范围：仅 `particles_v1.collision_radius`。依据根 `AGENTS.md`、`handover/REMAINING.md` 当前段落及 `docs/native-control-capture-checklist.md:168`；未修改生产/测试文件，未运行测试、OS/进程边界验证、真实宿主、模型、仿真、缓存或渲染，未联网。仅新增本报告；未重复 P01 审查或共用恢复回归。

## 产品定义与当前缺口

- `packages/houdini-bridge/src/houdini_bridge/product_control_definitions.py:126`：P03 已批准为 float `0..1000`、场景单位 SU 的物理碰撞半径。采用独立物理 radius 载体，独立于实例 pscale；保持实例 size 和基准 v。仅适用于支持此约定的 POP 碰撞模式。
- 精确 0 是点粒子碰撞，collision detection 保持开启；负数拒绝。不得用关闭碰撞、改变 size 或切换模式静默替代。产品定义已明确，不需重新征求语义。
- 尚缺：两版各自支持的 collision shape/mode、独立 radius 的合法属性/字段及 class/storage/tuple、精确零端点、solver/object gates、SDF/geometry 输入与变换、物理消费者，以及与 render pscale 的实际隔离。现有静态名称及参数范围不证明这些消费事实。
- 当前正式核心 `packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py:163` 的 `control_contract()` 仍将该项设为 `PARTICLE_COLLISION_RADIUS_NATIVE_CONVENTION_REQUIRED`；`control_write_plan():386` 与 `control_readback():661` 拒绝该项，`candidate_write_plan():483` 复用该拒绝。这是保留缺事实的边界，不能通过删除 blocker 完成 P03。

## 已取得静态证据与可复用实现

| 路径／精确定位 | 实际已取得内容 | 对 P03 的限制 |
|---|---|---|
| `docs/native-basis/hda-interface-capture.json`；当前 Windows 原件摘要 `outputs/windows-followup-20261004/windows-native-static-current/windows-hda-interface-capture.json`；各 `versions[21.0.631/22.0.429].operators["Dop/popsolver::2.0"]` | 两版均 `CAPTURED`，DialogScript SHA `90db8ddcc3d50919629609292ab2ce5c6d8c8473527a0f650583a444c40c0d84`；已选 collision 字段为 `docollision`、`collisionresponse`、`docollisionfeedback`。`docollision` 是 toggle/1；response 是 ordinal/1，菜单含 none/die/stopped/stuck/slide。Windows 摘录还记录 docollision 受 integratepos 门控，response 受 integratepos/hitattribute/docollision 门控。 | 此摘录无独立 radius/pscale 字段；response 是碰撞响应，不是半径。`native_execution=false`，同一 section SHA 不允许共享两版实际消费证据。 |
| `docs/native-basis/domain-native-documentation.json`；当前 Windows `outputs/windows-followup-20261004/windows-native-static-current/windows-domain-native-documentation.json`；各 `versions[build].domains.particles_v1` | 两版 collision_radius 均有 `PARAMETER_ID_NOT_COMMON_TO_ALL_CANDIDATES`；候选 alias 是 collisionradius/pscale，popsolver 对应 documented aliases 为空；topology/port semantics/native execution 均 false。 | 旧候选 alias 不成为已取得原生接口，不能据其写字段。 |
| `docs/native-basis/native-boundary-metadata-supplement.json`；各版本 POP Object、POP Solver、Copy to Points 条目 | 同 build 来源、原件/member 摘要和部分精确机器字段；POP Object、Copy to Points 标注 `CAPTURED_CORE`，来源明确 defaults/gates 未解码。 | 可定位后续静态原件；不是独立物理 radius 的属性、消费或零端点证明。 |
| 当前 Windows HDA 中 `Dop/popsource::2.0` | 与 radius 相关的已选字段是 relaxpoints/relaxiterations/usemaxradius/maxradius。 | Source relaxation 不等于 POP 物理碰撞半径，不能代用。 |
| `docs/native-basis/hom-attribute-numeric-storage-static.json`、`docs/native-basis/sopnode-geometry-output-static.json` | 同 build 通用属性/数值 storage 查询、SOP geometry 读取签名；后者明确 geometry 可能触发 cook。 | 通用读取 API 不定义 POP radius 约定；本批没有调用 HOM 或 cook。Hair/Vellum 资料亦不可移植到 P03。 |

**判断：无——目前没有足够已取得原生证据，为 P03 新增合法物理半径 writer/consumer 边界。已有部分静态接口与复用组件，但不能据此解除 P03。** 这是所查材料不足，非断言原生软件不支持独立半径。

可复用的具体组件：

- `packages/houdini-bridge/src/houdini_bridge/native_particle_size_host.py` 的 `Host.binding():37`、`Host.geometry():110`、`Host.observations():298` 可复用身份、实际属性和接线采集；`Host.prepare():162`、`Host.write():216`、`Host.restore():250` 是已有 P02 事务组件，不提供 P03 radius 语义。不能把 basis 中的 size 当物理半径。
- `packages/houdini-bridge/src/houdini_bridge/native_particle_size_program.py` 的 `_geometry_consumption():433`、`validate_geometry_consumption():502` 已比较 simulation→particle_size 的非 pscale 属性、P/ID/拓扑保持，并检查实际 unpacked copy 的 pscale 消费。后续可复用为实例大小隔离证据；它不观察 POP 物理 radius 的消费者，也不证明碰撞效果。
- `tests/unit/test_native_particle_size_routing.py` 的 `ParticleSizeRoutingTests` 仅是 P02 正式核心路由/collector 回归，不能升级为 P03 接受测试。

## 下一条复现入口／命令（仅记录，未执行）

正式调用链：`plugins/houdini/_impl/houdini_bridge_addon.py:_fx_planned_domain_prepared():4482` → `_fx_planned_write_plan():4379` → 上述核心 `candidate_write_plan()` → `control_write_plan()`。对 particles_v1 的单项合法零值 `{'collision_radius': 0.0}`，两版预计均在派生写入前以现有 blocker 拒绝；本批仅静态确认代码，没有声称已复现执行失败。

最窄现有测试方法为 `tests/unit/test_native_particle_ocean_geometry_domains.py:151` 的 `NativeParticleOceanGeometryTests.test_unknown_controls_inputs_and_blocked_controls_fail_closed`。它已包含两版 P03 的零值 candidate 拒绝和 readback 拒绝；同方法还遍历其他 blocked 项，仓库暂无所见独立 P03 方法。供下一批在本仓库运行的 PowerShell 命令如下，保存并恢复 PYTHONPATH，不运行全量或 P01 进程验证：

```powershell
$p03PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = 'C:/Users/32200/Desktop/Agent/skill/Bridge/tests/unit;C:/Users/32200/Desktop/Agent/skill/Bridge/packages/houdini-bridge/src;C:/Users/32200/Desktop/Agent/skill/Bridge/packages/dcc-task-runtime/src;C:/Users/32200/Desktop/Agent/skill/Bridge/packages/nuke-bridge/src;C:/Users/32200/Desktop/Agent/skill/Bridge/packages/vfx-pipeline/src'
    & 'C:/Users/32200/Desktop/Agent/skill/Bridge/.venv/Scripts/python.exe' -B -m unittest test_native_particle_ocean_geometry_domains.NativeParticleOceanGeometryTests.test_unknown_controls_inputs_and_blocked_controls_fail_closed -v
} finally {
    $env:PYTHONPATH = $p03PreviousPythonPath
}
```

此测试预期验证正确拒绝而通过，不是 P03 已实现的证据；本批测试状态为 NOT_RUN。

## 最小可行下一批（3 步）

1. **可执行的软件准备，交由主 agent 冻结后安排：** 先运行上述现有最窄回归，保留两版 P03 拒绝证据；沿已标明 member/original path 只读补查同 build 安装静态文档与接口，取得明确 carrier/mode/类型/门控的正面事实。没有新失败或新风险不改生产代码，不重复 P01/共用全量，也不增加一个由预期值生成 geometry 的夹具。
2. **需要事实；真实阶段另行具体授权：** 若静态资料仍不能证明独立半径和精确 0，则分别取得 H21.0.631/H22.0.429 自有 POP 图实际 radius carrier、collision/SDF 端口及变换、solver/object gates、baseline size/v 与消费采集；0/正半径必须证明检测开启、物理消费者确实消费，render pscale 独立。本批及现有软件授权不涵盖这项真实操作；缺事实继续 BLOCKED，不自创属性名或模式。
3. **取得足够事实后才可软件实现：** 在上述正式核心/addon 事务链最小增加 P03 planner/writer/collector，复用现有身份、快照回滚及 P02 属性保持/实例消费覆盖，软件替身只模拟已证明的底层 API/运输/进程边界。先复现实际拒绝再修复；保存/重开与真实碰撞消费依证据分开验收，保持 size/v 和碰撞开启，缺 SDF/类型/零端点/消费继续拒绝。不得按控制期望生成 geometry，也不得把软件通过记为宿主、视觉或生产 PASS。
