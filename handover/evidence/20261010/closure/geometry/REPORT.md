# G03 geometry_deform 独立 component 移交

日期：2026-10-09。基线 HEAD：`a3e7734e0f69b663be5bbd7d1f97bbdcb2d90b7d`。最终定向验证时间：`2026-10-09T10:25:00.383001+00:00`。

结论：完成 **G03 的独立 pure plan/collector component**，13 项定向 unittest 方法通过，退出码 0。它尚未接当前 graphcarrier，**不计 native M1 PASS，不计完整 G03 接收**。主 agent 负责共享 addon/client、domain registry、controller 副本同步、正式接线和独立审查。本轮没有修改上述文件，没有 Git 提交，没有运行真实 DCC、模型、仿真、缓存或渲染。

## 所有权与选择

仅新建以下两个实现/测试文件及本目录报告：

- `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py`
- `tests/unit/test_native_geometry_controls_program.py`

先只读批准记录及建议原件，并读取当前 blocked 定义、P02/A01 设计。批准建议原件 SHA-256 实算为 `7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e`，未改变原文。

`control-static-audit.json` 保存剩余 18 个生命周期控制的两版现状、产品定义、静态候选接口/来源与具体缺口。18 个包含已有独立 R05 component 和已 mapped 的 S01/S02，不倒退已有实现；排除 A01/P02 不表示它们已完成原生验收。当前两版合同中，这 18 个有 16 个 writer blocked、2 个 mapped，但所有完整生命周期状态不能由此推出 PASS。

G03 使用两版已有 `Sop/attribwrangle` 机器接口，直接承载已批准的源静止空间正弦法向位移；无需先建立 G02 的 quaternion 乘法顺序、orient class/tuple 和 transform/copy 组合事实。G02 未实现。其他 17 控制只读盘点，未修改。

## 接线 API

模块导入：`from houdini_bridge import native_geometry_controls_program as geometry`。

1. `collect_source_geometry(already_obtained_geometry, observe_geometry)`：调用主 agent 的真实几何 collector，验证并深复制快照。模块不调用 `geometry()` / `geometryAtFrame()`，不获取或 cook 下游几何。callback 无控制请求值输入。
2. `freeze_basis(version, source, *, local_x_axis, task_id, task_root, input_version, basis_input_sha256)`：冻结实际源快照、场景版本、显式局部 +X 和输入 SHA；`source_geometry_sha256()` / `basis_content_sha256()` 提供摘要。主 host 必须先验证输入注册/身份和 rest 空间来源。内容摘要本身不是认证。
3. `initialization_plan()`：返回自有 wrangle 的显式 gates；只能用于任务新建节点。主 host 先授权创建/初始化，再以 `source_program(version, 0, context)` 得到 bootstrap 候选，实际写入并独立读回零程序及全部 gates，然后完成自有初始化登记。模块不执行初始化，不提供登记 writer，不重配置艺术家节点。主要 gates 为 point class、空 group、autobind、零显式 bindings/groupbindings、`exportlist='P'` / `vex_outputmask='P'`、`vex_updatenmls=0`、非 inplace、64-bit VEX；这些是候选设置，真实零值几何不变效果尚未验证。
4. `collect_parameters(node, observe_parameter)`：复用主 agent 的实际模板/通道 collector。当前 addon `_fx_planned_observation` 的 ordinal/multiparm 类型可对接；menu tuple/list、实际 index 和实际 evalAsString token 均处理，禁止 bool 冒充 index。主 host 将 callback 绑定到已核验的 `nodes['geometry_deform']['path']`，不得接收客户端伪造 observations。
5. `plan_control(version, value, context, parameters) -> GeometryDeformPlan`：仅在已完成初始化登记、canonical basis 一致、实际非空 snippet 完整识别为自有生成器程序时返回进程内封存计划；无写操作，无 producer 登记。空 snippet 即使 node 标记 task_owned 也拒绝，不能藉此 adopt 外来 owned driver。`value` 保持已批准 `deformation=0..100 SU`。
6. `validate_plan(plan, fresh_context, fresh_parameters, after_mutation=False) -> writes`：mutation 前在现有任务 lease/所有权事务内重新采集并核验，返回一个 `geometry_deform/snippet` string write。mutation 后用 `after_mutation=True` 核对实际参数。`control_readback(version, context, parameters)` 从实际 snippet 解码值，严格重建固定程序，不接受期望/request 值参数，始终报告 `parameters_only` 和 `BLOCKED`。
7. `rollback_plan(plan, fresh_context, fresh_parameters)`：仅在最终状态仍与计划一致时返回原 snippet。主 host 保留现有通道、连接、登记和任务事务回滚责任；发生第三方漂移时拒绝覆盖。

所有 plan seals 是本进程新生成密钥下的 HMAC 守卫，不持久化、不跨进程复用、不作为 producer 事实。重开必须独立重采输入/图/参数与登记，不能反序列化旧 plan 直接执行。

## 显式输入及承载边界

`context` 为 `{'basis': frozen_basis, 'source': independently_observed_source, 'nodes': actual_nodes, 'initialization': independently_observed_owned_initialization}`。只生成 bootstrap 候选的 `source_program` 不要求 initialization；公共 `plan_control` / `control_readback` / `validate_plan` 均强制要求初始化登记。

`basis.origin='authenticated_host_basis'` 是必须由已有 host 输入注册边界保证的 provenance 标签，不能由客户端声明升级为可信。freeze_basis 重建 canonical basis：精确 source 几何 SHA、task/input_version、basis_input_sha256、局部轴/bbox/单位/静止空间；后续 basis 必须与该重建结果完全一致。host 必须从当前可信输入登记独立验证 basis_input_sha256 和 input_version，并绑定实际源节点、任务图和实际 collector。传入 JSON 可以通过数学/结构验证，但本模块没有能力鉴别纯调用者伪造的同形 JSON，因此 **不得把模块暴露为绕过已有 host 认证/所有权事务的请求入口**。

`initialization` 必须是 host 实际读回的不可变自有登记记录（例如任务受控 node metadata 配合服务端任务登记），而非请求体。精确字段为 `schema='bridge.geometry-deform-initialization/1'`、`origin='runtime_hom'`、严格 bool `initialized=True/registered=True`、generator、task_id/task_root/input_version/native_version、实际 geometry_deform node_path、canonical basis_sha256、initial_program_sha256、gates_sha256。initial_program_sha256 是实际已初始化 canonical 零程序 `float deform_amplitude = 0;\n` 的 SHA；gates_sha256 是模块 GATES 的排序紧凑 JSON SHA（allow_nan=False，tuple 按 JSON array）。初始化完成后不因后续控制值修改而重写此记录；新输入基准/图版本须经主 host 明确重新初始化登记。模块只检查记录内容一致性和后续计划封存；记录是否真实来自自有 native userdata、是否已经写入服务端登记，仍必须由 host 认证，`origin` 字符串与哈希不证明来源。

- source 快照：`origin='runtime_hom'`、实际 `node_path`、严格 output 0、实际 frame、`space='sop_local_rest'`、`unit='SU'`、1..100000 实际点，以及 polygons/primitive_types/point_attributes。
- `P` 和 `N` 必须是实际 point float/3、float32 或 float64、非 array；`N` 必须已有且单位长度（容差 1e-6）。不创建 N、不将 vertex N 默改为 point N、不隐式归一化。`id` 必须是实际唯一 point int32/1；不使用 point number 替代稳定 ID，不生成缺失 ID。
- 当前独立组件仅支持 unpacked Polygon 源，primitive 数量上限 100000、连接顶点总数上限 1000000。拒绝 packed/volume/mixed/空源和无效连接，不推导 pack 展开规则。上述是本组件读入上限，不是产品资源预算验收。
- local_x_axis 必须显式 `[1,0,0]`，从实际源 P 计算冻结 bbox 最小 X 和正跨度 Lx。Lx=0、缺轴、单位/空间矛盾、摘要漂移均拒绝；不猜波长。
- nodes 必须含 `instance_source`（sphere 或 grid）、`geometry_deform`（attribwrangle）、`instance_transform`（xform）。各节点实际 task ID/root/input_version/native_version、SOP category、editable、bypassed=False、rest 空间及绝对 path 一致；节点 distinct、同父 SOP 空间。
- 必须独立读回 `instance_source:out0 -> geometry_deform:in0 -> instance_transform:in0`，每个 destination 恰有这条连接。源没有输入，拒绝反馈环或将已变形输出当 rest basis。必须插在现有 scale/rotation 之前；不重写 xform.r/s、点 P/pscale、scatter count/density/seed。
- 程序按冻结源最小 X 和 Lx，生成 `P'=P+d*sin(2π*(P.x-xmin)/Lx)*N_base`，phase 0，仅读取当前独立上游 rest P/N。d=0 的候选文本不包含任何 P 写入；其产品意图是恢复上游源而非累计上次结果，实际 host 几何不变结论仍待同版证据。
- 所有参数必须有实际 type/tuple/菜单/value 和 driven/locked/disabled/hidden=False，实际 snippet 必须非空且可被固定生成器完整识别。冻结完整 callback 参数快照及 context；多余字段漂移也拒绝。节点/参数来源真实性与完整图保存仍由现有 host 权限边界保证。

**当前 graphcarrier 兼容状态：NOT_IMPLEMENTED_BY_THIS_OWNER。** 当前图没有此新增 role 的接线和独立 rest basis 采集。若现有 instance_source 为非 Polygon 或没有实际 point N/id，明确 BLOCKED；本模块不会补造成功输入。主 agent 若只接受 component，可保持 domain registry 的 G03 原 blocker 不变。

## 原生静态来源与 SHA

完整两版字段、默认、menu tokens、gate 信息、来源 path/member/hash 及接口限制见 `native-facts.json`；八个 static basis 文件本机字节 SHA 和所有读取实现版本见 `verification.json`。

| 本机材料 | 本机 SHA-256 |
|---|---|
| docs/native-basis/w2-wrangle-convolve-static.json | `5a10fa158ae7e153cbc62054da2895fab32fc8a1a1c527d42d80a9853b05a3f6` |
| docs/native-basis/hom-attribute-numeric-storage-static.json | `2d9fb13ee492766261b6ae53e04a720d2ea52ff5fb0b3222bba97a8c8c906059` |
| docs/native-basis/sopnode-geometry-output-static.json | `f0433ca9ef58dd0bcf3b6ac0e21c2a03259f21b5cb692ebfa7371a43eebfd73f` |

| 厂商原件记录 | H21.0.631 | H22.0.429 |
|---|---|---|
| Houdini Resources/houdini/otls/OPlibSop.hda archive SHA | `5018624a3f850b498df5696e7294dae8d442a847b6c61b9717025495d76bf5e2` | `c24559e89d9f2895e32d2fc26a96b922c00a47a75de212f60a56928042df1a7f` |
| Sop/attribwrangle::DialogScript section SHA | `b47a35a99cfd15f0c85143a3fed309c1a2f30704183ef7565bd52af1f7306c77` | `b47a35a99cfd15f0c85143a3fed309c1a2f30704183ef7565bd52af1f7306c77` |
| Houdini Resources/houdini/help/hom.zip archive SHA | `e4c8f5503d1f96ab10ca17f865e468c05243d2a3fa7a96ccd0b7904b0929817c` | `143162e01defa725c5e35f9a53bfb3ba339a91fa1edd0e99d73da8499be23d0c` |
| hou/SopNode.txt member SHA | `25be4eb22b472a92559982adffead9951c109ab41dd6fb189980dae1a3c86872` | `25be4eb22b472a92559982adffead9951c109ab41dd6fb189980dae1a3c86872` |
| hou/Attrib.txt member SHA | `60fb90b8ec2fdd45c7de6cb5fc3eab9c028f2e06234c770fa0fd96dcb0e316fd` | `60fb90b8ec2fdd45c7de6cb5fc3eab9c028f2e06234c770fa0fd96dcb0e316fd` |
| hou/numericData.txt member SHA | `c919b55b1c78897eebb04b50984c7968529fc26256c8f293b0fbbf9b6f206581` | `c919b55b1c78897eebb04b50984c7968529fc26256c8f293b0fbbf9b6f206581` |

这些原件 path 是历史静态 capture 记录；本轮实算的是仓库 JSON 字节，**原厂 HDA/help archive 不在本机 docs/native-basis，未重新对原厂 archive 字节验真**。两版 captured 机器字段足以限定纯候选载体，不能等同完整原生 C0 证据。DialogScript 的 input0 label 是已规范化索引，但 `full_node_port_arity=None`，不能据 label 宣称 native 完整连接语义成立。

零值 gates 的两版静态核对：`exportlist` 是 string/1，默认 `*`、无 disable/hide，原 label 为 Attributes to Create；`vex_outputmask` 是 string/1，默认 `*`、无 disable/hide，原 label 为 Export Parameters；`vex_updatenmls` 是 toggle/1，默认 `off`、无 disable/hide。两版 raw_fields 相同，这证明机器字段和类型/默认存在，支持纯候选设置，不证明本程序在这两个 build 上零值 cook 时的 P/N/属性不变效果。尤其 exportlist 不能泛称“只允许写 P”，其帮助语义是限制创建；候选使用 outputmask 限定 export 参数，但其完整运行效果仍缺同版消费事实。

另只读核对 [SideFX Attribute Wrangle 当前帮助](https://www.sidefx.com/docs/houdini/nodes/sop/attribwrangle.html)及 [sin 当前帮助](https://www.sidefx.com/docs/houdini/vex/functions/sin.html)；sin 的输入为弧度。当前帮助说明 exportlist 限制新属性创建、outputmask 可限制写出/创建但保留读绑定、update normals 开关控制位移后的法线更新。这些当前网页仅为语法/语义补充，不冒充 H21.0.631/H22.0.429 同 build 编译或宿主证据。

## 实际验证

命令：`.venv/Scripts/python.exe -B outputs/common-closure-20261009/geometry/run_geometry_checks.py`。最终输出见 `targeted-tests.log` / `verification.json`，13 方法、0 failure、0 error、0 skip、退出码 0。读取和测试前后源码 hash 一致。`git diff --check` 实跑退出码 0；不运行标准全量，不修改/删除既有测试。

`baseline.json` 保存当前 **公共 domain control_write_plan** 两版 G02/G03 拒绝：`INSTANCE_RANDOM_ROTATION_ATTRIBUTE_GRAPH_REQUIRED` / `INSTANCE_DEFORMATION_NATIVE_GRAPH_REQUIRED`。先前直接调用当前 G03 入口实跑退出码 1，随后定向测试核验两版拒绝。这是控制合同入口复现，不是正式 controller 全图生命周期验收；后者属主 agent 范围。

测试底层替身仅是 BottomParameter 的 template/eval/set 存储和 BottomGeometry 的明确源几何输入快照。真实 module planner、guards、readback parser、rollback 全部执行；没有替换 facade、registry、writer 成功回执、原生 VEX random/cook、solver、producer 或下游结果。没有使用请求值制造几何成功。特别反例：request=100，实际 snippet=1，readback 得 1，而该 request 对应 validate_plan(after_mutation=True) 拒绝。

覆盖两个 captured 接口、0/正/100、非法数值、缺基准、bbox/axis/单位/空间漂移、N 缺失/类型/非单位长度、ID 缺失/重复/bool/storage、packed/非法拓扑、任务所有权/版本/连接/反馈环、菜单 representation、驱动/锁/隐藏/禁用、艺术家 snippet、seal/完整参数快照篡改及 guarded rollback。新增反例覆盖 owned 空 snippet、未初始化/未登记、caller origin、外来 canonical basis/task、错误初始零程序/gates SHA；都拒绝。这仅验证组件边界，不证明 caller 来源已认证。

必要调试审计保留：`initial-targeted-tests.log` / `initial-verification.json` 是 12 方法中 1 个测试 fixture 错误（篡改 digest 后测试又重算恢复 digest），已最小修正 fixture；中间合法版本日志保留在 `pre-*-targeted-tests.log` / `pre-*-verification.json`。它们不是当前有效候选。最初报告 runner 的 list-vs-dict 静态材料结构读取错误也已只修报告器，未改变原生材料。

## 最终源码 hash

| 文件 | SHA-256 |
|---|---|
| native_geometry_controls_program.py | `6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf` |
| test_native_geometry_controls_program.py | `3e1e7ca6ecaf31363427d08a759b68af7b6cc52bf00b2b203963979e5d4d8460` |
| 本目录 run_geometry_checks.py | `f99d0900c8ea7304c2110fe314903d750f0a645e4670b1db75f8b2756443715a` |

## 未完成 scope 与状态

软件 component 定向验证：PASS。当前 graphcarrier 接线、controller 副本 sync、正式登记/反馈/save/reopen/recovery：未在本独立任务实现，由主 agent 接线和审查。native G03/full-16-domain M1：BLOCKED。安装：NOT_RUN。真实 Houdini/Nuke、WorkBuddy/HY3/模型、仿真/缓存/渲染、视觉和生产：NOT_RUN。

缺少同 build VEX 编译及实际变形 P、零程序在 exportlist/outputmask/no updateN 下实际 P/N 不变行为、实际保留拓扑/N/其他属性、现有 xform 与 Copy-to-Points 实际下游消费、实例点 ID/P/pscale/count/seed 保留读回、save/reopen/cross-frame rest basis 稳定性。源可编辑性、真实 ID 和 point N、真实自有初始化登记也必须由 host 取得，不能用这 13 项纯组件测试填补。缺事实时保持上述缺项，不生成 native 成功，也不把已批准产品定义当作宿主事实。
