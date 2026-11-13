# P01 / P03 原生接口短审计（2026-10-14）

补充核对（本机安装资源，同 build）：H21.0.631 / H22.0.429 的 `houdini/help/nodes.zip` → `obj/dopnet.txt` 明确含 `#id: startframe`（83行）、`#id: timescale`（93行）、`#id: timeoffset`（73行），另有 `timestep`（57行）和 `substep`（66行）。`sop/dopnet.txt` 不单独列时钟 id，但明确链接 Obj DOP Network。两版 `config/Dialogs/SOP/dopnet` 与 `OBJ/dopnet` 二进制均有精确独立机器名 token、同名 `.gad` / `.label` 与 `Start Frame` / `Scale Time` / `Offset Time` 标签，因而 **SOP dopnet 的 startframe/timescale/timeoffset 机器名有据**；不是 offsettime，也不是独立 scale。未解码类型、默认表达式和严格界；这些仍需 fail closed。JSON 新增 installed_clock_supplement，记录实际 Windows 文件路径、archive/member/dialog SHA 和原文行号/DS byte offsets。旧 capture 的 parameters={} 只是捕获缺口，不能解释为原生字段不存在。

范围：只读解析 `docs/native-basis` JSON，核对 H21.0.631 / H22.0.429 静态定义及 SideFX 官方文档。未启动真实 DCC、仿真或测试；仅新增本报告与同名 JSON。源码及捕获文件 SHA、逐版字段和 provenance 在 JSON；supplement 对 base capture、POP Source section 的绑定已核对。

| 项目 | 两版本结论 |
|---|---|
| 持续出生率 | `Dop/popsource::2.0.constantrate` 是 size=1 的 **float**；静态 default=5000、range_tokens=0..1e+06。范围不是已验证的原生硬界。 |
| 启动门控 | 当前 `_BIRTH_GATES` 全部存在、类型匹配：`emittype=surface`、`usecontextgeo=first`、`constantactivate=1.0`、`impulseactiveate=0.0`、`scalebyarea=0`、`emitattrib=""`、`usesimpointlimit=0`、`useframepointlimit=0`、`removeoverlap=none`。 |
| 拼写与混淆 | 真实字段是 `constantactivate`、含历史拼写的 `impulseactiveate`；检查的 POP Source 定义没有 `constactivation` / `scalesize`。面积缩放是 `scalebyarea`；`scaleradiiby` / `maxradius` 是发射散点 relaxation。 |
| 额外出生状态 | `probemit` toggle 默认1、`seed` float 默认0、`jitterbirthtime` ordinal 默认positive；现有 birth gates 不冻结它们。应读回/保存实际状态，不能因此声称粒子数量逐步确定。 |
| DOP 时钟 | 旧 supplement 是 CAPTURED_CORE、parameters={}；本机两版 help/Dialogs 补证机器名为 `startframe`、`timeoffset`、`timescale`，SOP/OBJ 均有 DS 依据。类型/默认/严格界和实际消费尚未解码/执行。 |
| Solver 时钟 | `Dop/popsolver::2.0.timescale` size=1 float、default=1；这是 solver 对实际 timestep 的缩放，与 network Scale Time 分开。 |

官方 [POP Source](https://www.sidefx.com/docs/houdini/nodes/dop/popsource.html) 说明持续发射以每秒计，impulse 按 cook 计，并说明面积、点数限制和概率发射。以上静态字段不是实际子步出生数证据。

Python 参数表达式：显式 `parm.setExpression(text, language=hou.exprLanguage.Python)` 合法；多行文本作为函数体，必须 return，`hou.pwd()` 指正在求值参数所属节点。表达式有独立命名空间，不能依赖控制端 Python globals。已有 keyframes 时 setExpression 不会自动清除所有 keys，必须按原有事务规则保存并核对完整 keys/语言/外推。见 [Python expressions](https://www.sidefx.com/docs/houdini/hom/expressions.html)、[hou.Parm](https://www.sidefx.com/docs/houdini/hom/hou/Parm.html)。

`hou.time()` 是场景播放秒，frame1=0；`hou.frameToTime(frame)` 用于场景帧→秒。`lvar("ST")` / `hou.DopSimulation.time()` 属于仿真时间，可能因 network Offset/Scale 与场景时间不同；`lvar` 仅在合法参数本地上下文可用，不能在宿主普通 Python 调用中替它造值。P01 已批准的桶宽是 **1场景秒**，不得直接把 ST 当场景秒。官方 [hou.time](https://www.sidefx.com/docs/houdini/hom/hou/time.html)、[hou.lvar](https://www.sidefx.com/docs/houdini/hom/hou/lvar.html)、[DopSimulation](https://www.sidefx.com/docs/houdini/hom/hou/DopSimulation.html)、[DOP Network](https://www.sidefx.com/docs/houdini/nodes/obj/dopnet.html) 支持此区分。

**P01 未闭合证据**：合法 API 与静态 float 字段足以约束实现，但不能证明两版 native 子步调用时刻、跨秒阶跃的积分/分桶切分、残余取整/概率出生及实际数量。birth_rate 产品上限1e7、p≤100，公式上限2e7是产品算术，不是验证过的 native 硬界。不得用 range_tokens=1e6 拒绝/截断2e7，也不得宣称2e7原生消费已通过；严格上下界需实际 `FloatParmTemplate.minIsStrict/maxIsStrict` 等事实且仍不能替代内部 solver 极限。[FloatParmTemplate](https://www.sidefx.com/docs/houdini/hom/hou/FloatParmTemplate.html)、[POP Solver](https://www.sidefx.com/docs/houdini/nodes/dop/popsolver.html)。

**P03 继续 BLOCKED**：两版已捕获 POP Solver 没有独立 radius/pscale/thickness 参数；POP Collision Detect/Behavior 未捕获，核心 POP Object 同样没有解码参数。当前官方 [碰撞概览](https://www.sidefx.com/docs/houdini/dopparticles/collisions.html)、[POP Collision Detect](https://www.sidefx.com/docs/houdini/nodes/dop/popcollisiondetect.html) 未给足合法独立半径的 same-build 消费事实。Source 的 relaxation 半径不是碰撞半径；Hair/Vellum pscale 不可迁用。缺项为独立物理属性 class/storage、真实消费节点/模式及 gates、SDF/shape 输入、半径0的点碰撞语义与渲染 pscale 保持。结论仅是已审计材料不足，不声称 Houdini 不存在可行路线。

在线官方文档为当前22.0滚动版本；不能冒充21.0.631/22.0.429运行结果。全部 URL 及结论在 JSON，native_execution=NOT_RUN。

收口说明：后续静态调查仅取得上述安装 help 的精确 #id 与 OBJ/SOP 二进制 Dialogs 的机器名/标签 token；未继续扫描安装大文件，未取得网络参数类型、默认表达式、严格界、子步积分或有效 rate 上限的新事实。以上静态依据可辅助审计，不能代替实际宿主观测。

按主实现者本次状态说明，Host 已用实际 parameterTemplateGroup、最多4096项，通过官方标签 Offset Time / Scale Time 发现机器名，动态只读观测；缺任何必要事实即拒绝，不以本报告中的 startframe/timescale 网络字段名代替实际发现；实际 solver timescale=1 约束保留。本次只读审计未独立检查或执行该实现，因此这段属于主实现者提供的实现状态，不是新增验证 PASS。审计在此收口，供 final freeze；未修改生产、tests、docs 或其他文件。

