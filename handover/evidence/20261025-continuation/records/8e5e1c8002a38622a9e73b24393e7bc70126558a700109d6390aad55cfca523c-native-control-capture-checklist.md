# 原生控制采集与验收清单：20 项定义及 B 组合

日期：2026-10-04。此文件整理后续采集要求、源码审计及本机已授权的 Windows 安装原件静态采集；**真实 DCC、原生 API 实例、仿真、缓存、渲染、HY3及模型均为 NOT_RUN**。普通 Python 的静态目录夹具回归和安装文件解析已执行，见第2/7节。没有创建新的 PASS/批准系统，没有改控制定义、原生 writer、controller、addon 或生成副本。

主仓库合流后的当前工具已补独占新输出、同一份帮助 archive 字节解析／摘要，以及实际 catalog／locator 来源核对。`windows-native-capture-current-20261004-195200.log` 实际 15 tests、0 FAIL/ERROR/SKIP、退出0；主仓库两条普通 Python CLI 采集日志为 `windows-static-hda-current-20261004-195229.log` 和 `windows-static-help-current-20261004-195230.log`，退出均0。当前静态 JSON 位于 `outputs/windows-followup-20261004/windows-native-static-current/`；旧 stage 和旧 macOS 摘录保留作来源审计，不能代替当前工具的源码绑定。

20 项定义及共同规则已批准，依据 [批准记录](../handover/CONTROL_DECISIONS_20261004.md) 和 [proposal 第 2–3 节](../outputs/windows-followup-20261004/control-decisions-proposal.md)，proposal SHA-256 为 `7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e`。当前三份 native 模块的 20 项仍为 `native_status=blocked`；独立的 `product_status=approved` 不证明机器接口或实际效果成立。

**B 第 5 节也已于 2026-10-04 批准。** 用户最新原话：“批准 B 组合方案，缺失场景输入和原生事实继续标记”。原 ROOT 的 `handover/CONTROL_DECISIONS_20261004.md` 已由 main 完成两次批准事实记录，本次只读核对其中的 B 原话及第 5 节范围。本文件未修改该记录或五个已 review 的产品元数据文件，未扩大 20 项原 hash 所绑定的第 2–3 节范围。B 沿用同一 proposal 第 5 节方案及 C0；未给定的球壳、次级碎屑、meta 输入和原生事实继续保持具体缺项。

## 1. 执行顺序与证据边界

1. 在获具体授权的目标机核对 **H21.0.631 与 H22.0.459 两个独立安装**；分别保存安装 build、平台、原始 HDA/SDK/help 字节及 SHA-256。不得用 H21 的字段、别名、端口或效果补 H22 的缺项。
2. 按 C0 和下面每项清单先补同版本接口与消费证据；同时冻结任务提供的实际 basis。标成 NOT_CAPTURED 的机器名称、属性 class 或端口不得先猜进 writer。
3. 只有合法可编辑边界、精确类型/门控/端口、实际承载物及消费关系足以支撑既有合同后，才另行最小实现 writer/collector。采到节点名或删除 blocker 均不足以解除 writer；此清单本身不解除任何一项。
4. 实现后先做现有纯合同/底层 API 验证，再在具体真实宿主授权范围内完成第 6 节的新实例正常、拒绝、保存重开证据。静态采集、软件验证与真实动态验收分开记录，不把任何一层提升为完整 M1 PASS。

长度为当前场景 SU，速度为 SU/s；真实 FPS、时间尺度和质量基准必须读回，不因厂商 `m1` 标签宣称 SI 换算。新随机控制使用固定任务 seed、稳定实体 ID 和独立子 seed；非法数值、缺 basis、矛盾组合及预算超限明确拒绝，不夹紧、取整或伪造样本。既有控制名、区间、粒子 life/velocity variance、Crowd path_variance、Geometry scale_variance 和 RBD activation_frame 定义保持原样；缓存/渲染授权及 12 帧/120 秒、总磁盘预算不变。

## 2. 最终静态工具 CLI 与本机 Windows 采集

两个脚本均用普通 Python 解析静态安装文件，不导入 `hou`、创建实例或执行原生作业。默认macOS布局保持；以下macOS命令本次未执行，输出应选全新目录，不覆盖旧摘录。

```sh
python3 tools/capture_native_schema.py --install-root /Applications/Houdini --output outputs/native-control-capture/hda-interface-capture.json
python3 tools/audit_domain_native_basis.py --output outputs/native-control-capture/domain-native-documentation.json
```

| 工具 | 源码实际参数和布局 | 能提供的证据／限制 |
|---|---|---|
| `tools/capture_native_schema.py` | 必填 `--output`；`--install-root` 默认 `/Applications/Houdini`；`--install-layout {macos,windows}` 默认macos；可重复 `--build {21.0.631,22.0.429,22.0.459}`，省略则当前21.0.631／22.0.459两版；429仅显式保留。读取所选resource目录下 `otls` | 复用原INDX/DialogScript解析器，记录archive/section hash、参数及I/O标签。类型名单仍硬编码；没有 `--version`、`--operator`、`--hda` 或运行时采集开关。缺archive、成员或DialogScript保留原状态。 |
| `tools/audit_domain_native_basis.py` | 同样支持上述四个CLI参数；读取所选resource目录下 `help/nodes.zip`，正常包导入只读domain目录 | 展开help redirect/include、审计名称/参数ID与缺项。`topology_validated`、`parameter_values_validated`、`port_semantics_validated` 与 `native_execution` 保持false，不证明机器实例。 |

共用 `tools/native_install_paths.py` 只定位精确build目录：macOS父root下 `Houdini<build>/Frameworks/Houdini.framework/Versions/<major.minor>/Resources/houdini`；Windows父root下 `Houdini <build>/houdini`。也可给精确build目录并显式 `--build` 选该版；目录名/build或layout冲突拒绝，不自动跨layout/build回退，22.0.368不在合同中。给Windows路径必须显式选择windows布局。两工具明确以UTF-8写JSON，metadata记录实际platform、安装root/layout/build、工具及locator SHA；下列历史Windows记录的原件path保持其实际Windows路径。

历史Windows采集机器曾只读确认 `C:/Program Files/Side Effects Software/Houdini 21.0.631` 与 `Houdini 22.0.429` 的真实 `otls` 和 `help/nodes.zip`。已执行下列普通Python静态命令；实际原始日志由 `tools/run_logged.py` 保存完整argv及START/END。cwd为第7节隔离copy，未启动任何Houdini/hython/Nuke/API。

```powershell
& 'C:/Users/32200/Desktop/Agent/skill/Bridge/.venv/Scripts/python.exe' -B tools/capture_native_schema.py --install-root 'C:/Program Files/Side Effects Software' --install-layout windows --output outputs/windows-followup-20261004/approval-contract-evidence/windows-native-static-20261004-1935/windows-hda-interface-capture.json
& 'C:/Users/32200/Desktop/Agent/skill/Bridge/.venv/Scripts/python.exe' -B tools/audit_domain_native_basis.py --install-root 'C:/Program Files/Side Effects Software' --install-layout windows --output outputs/windows-followup-20261004/approval-contract-evidence/windows-native-static-20261004-1935/windows-domain-native-documentation.json
```

两版各解析5个真实HDA archive、43个选定接口，help各审计15域并保留缺口；JSON顶层native_execution=false。输出只在上述全新Windows目录，旧 `docs/native-basis/` JSON及其macOS provenance未覆盖或重新绑定。Windows原件hash与旧mac记录分别保存，不能混为同一平台原件；静态接口不自动解除20项writer。

固定HDA名单仍不覆盖全部待选Gas Repeat/Move-to-Iso、Trail/历史、投影、球壳/厚度或编译算子的实例接口；help只覆盖目录及可解析help。未覆盖对象须从**同版本原件**定位category/type、SDK/HDA section/内部consumer及合法编辑入口，保存原字节/hash；当前未采集这些新接口、实际消费或实例，不能因为安装存在就删除缺项。

## 3. 已有材料：静态摘录可复用，原件及实例缺口不能消失

下表简称用于逐项清单。所有简称都指 `docs/native-basis/` 内 JSON，内容按 build 分开；“已摘录”不等于本机重新验真。

| 简称／文件 | 当前可支持的静态事实 | 不能替代的采集 |
|---|---|---|
| HDA：`hda-interface-capture.json`；SUP：`native-boundary-metadata-supplement.json` | 两版 Pyro、FLIP、RBD、POP、Ocean 参数摘录；SUP 还含部分编译节点/attribwrangle/volumewrangle 摘录 | 原始安装字节、完整运行时 ParmTemplate、当前 defaults/expressions/gates、合法编辑性、实际端口/字段/属性消费。 |
| W4：`w4-glue-collision-static.json` | 两版 `Dop/flipobject.overridecollisionsep/collisionsep`、`Dop/flipconfigureobject.coldivsize` 及 SOP 内部 consumer；RBD name/constraints/overwrite 等 help | 内部字段存在不等于可写 SOP 公共入口，也没有 collision_passes 的合法映射。 |
| W2：`w2-wrangle-convolve-static.json` | 两版 `Sop/attribwrangle`、`Sop/volumewrangle` 的部分机器参数 | 20 项数学程序、实际坐标/属性/体积消费、所有端口与零值效果；不是现成 writer。 |
| SC：`scatter2-sdk-help-static.json` | 两版 Scatter2 SDK 的 `generateby/forcetotal/densityscale/npts/indepvoxel` 与 count/density 语义 | 实例 ParmTemplate/menu 表示、稳定 ID、投影、随机姿态或 count 不变的实际几何。 |
| ATTR：`hom-attribute-numeric-storage-static.json`；GEO：`sopnode-geometry-output-static.json` | 属性 precision/array/qualifier 与 geometry output/input 查询签名的同版本摘录 | 每个实际属性的 class/storage/tuple、几何输出索引及下游读取结果。 |
| VOL：`ocean-volume-hom-static.json` | Volume/HOM/SDK/binary 的静态字段与存储材料 | 当前谱体积、方向权重、能量和 endpoint 可表示性。 |
| W1：`w1-sopimport-usdrender-static.json` | 供应商 SOP Import helper 中 `soppath/pathprefix/enable_staticattribs/staticattribs` 及 USD Render 消费片段 | 粒子速度→USD velocities、点/实例表示、Karma velocity-blur 最终绑定和真实运动向量。 |
| HELP：`domain-native-documentation.json` | 同版本帮助名称、ID、redirect/include 来源及未闭合声明 | 机器参数、完整端口、实例、图正常路径或第 16 域产物链。 |

历史隔离副本曾只读检查以上 10 份 JSON 中以 `/Applications/` 开头的原件定位字符串：**62 个不同路径，在当前隔离副本所在机器的这些定位处均不存在**。检查的是摘录引用位置，未声称全盘没有安装或原件。恢复 JSON、历史 archive/section hash 和源码摘录依然可追溯，但未取得这些原始 HDA、help ZIP、SDK/header、vendor helper/binary 字节的新副本，也没有运行实例；目标机需恢复/重新采集并比对 hash。

一个须具体解决的静态矛盾：HDA 两版 `Dop/popsteerseek.goalprevious` 记为 vector/size=1，SUP 两版记为 vector/size=3。不得任选一个作为新 writer 的 tuple 事实；按同 build 原 DialogScript/SDK 及实际 ParmTuple 重新采集。source hash 与同版本内容冲突也应这样保留并解决。

### C0：每项、每个版本的最小采集包

每个 decision_id 分别交 H21.0.631、H22.0.459 两份包；共用的原件可以按 hash 引用一次，不能共用实例事实。使用现有 native-basis 与任务/操作/artifact 证据形态，无需新建批准/PASS 引擎。

- 原件：安装 build/平台/版本，archive/member/section、SDK/help/helper 的原字节定位与 SHA-256；记录工具源码 hash 和实际命令/退出码/原始日志，缺件不写 CAPTURED。
- 接口：完整 category/operator namespace/version token、实际 node path/定义库、机器 field、类型/tuple、菜单 token 与表示方式、factory default/current expression、硬/软范围、disable/hide/lock/driver、multiparm template→实际实例绑定；不得从 UI label 猜机器键。
- 端口：真实输入/输出数量与零基索引、角色、数据种类、实际连接及谁读取谁；DialogScript 标签是原始一基标签，不能仅减一就声称完整端口语义成立。内部 consumer 须另证合法可编辑性；不擅自 unlock 非自有 HDA。
- 承载物/basis：实际 geometry/field/attribute/channel/program、class/storage/tuple/qualifier、坐标和时间空间、稳定 ID、seed/子 seed、原始 basis 输入 SHA；下游消费前后读回，并留不应改变的控制/艺术家字段快照。
- 解除前必要条件：同版本原件可核对，机器入口/门控/端口及属性/字段消费已闭合，合法 endpoint 能表达、必要 basis 可提供。缺任一项保留原 blocker 或具体新增缺项；仍须实现事务围栏、真实读回与软件回归，不能仅改 `native_status`。

当前22兼容目标已获确认改为22.0.459。独立静态采集的55个HDA定义、支持来源和原始字节分别保存于 `docs/native-basis/hda-interface-22.0.459.json`、`supporting-sources-22.0.459.json`、`h22-459-originals/`。本清单中的Windows429命令、AST与SHA属于历史记录，保持原版本；它们不能补459的compiled／运行时模板、实例或有效writer事实。

## 4. 20 项：H21/H22 分别采集后才可能解除 writer

本节保留的“H21/H22 已摘录”与HDA/SUP/W1/W2等简称指原21/429历史材料，不自动成为459事实。当前459须逐项核对其独立原件和原生模块中的 `native_basis`／阻断项，历史token只作调查起点。

以下每节的“先采集”均要求 **H21.0.631 与 H22.0.459 各自完成 C0**；目前两版全部 NOT_RUN/缺实例。列出的已有精确 token 只是调查起点；对尚未捕获的新算子、字段、属性载体或端口明确写“待采集”，不作为候选别名写入代码。范围保持当前源码。

### A01 · pyro_fire_v1.flame_height · -100..1000

Blocker：`PHYSICAL_FLAME_HEIGHT_CONTRACT_REQUIRED`。

- H21/H22 已摘录：HDA/SUP `Sop/pyrosolver` 与 sourcing；W2 `Sop/volumewrangle.snippet/group/vex_precision`。`buoyancylift`、`flames_lifespan` 是别的控制，不是高度映射。
- 先采集 operator/fields/ports/消费：精确 flame 生产/消费位置及体积坐标变换；合法自有 field-mask 算子和机器参数/输入输出（待采集）；定位其相对 source/solver 的阶段、flame 读写边界及非正包络的合法空输出。保留 density/temperature/vel 与火光材质。
- basis：显式正 `H_base`、可信发射上轴、源顶投影、体积变换及来源 SHA。正常需读回高度包络 `H_base+value`；0 保留基准，负偏移降低上限，总上限≤0输出空包络；缺基准拒绝，正数不承诺生成更高火焰。

### A02 · water_flip_v1.collision_separation · 0..100

Blocker：`FLIP_SIMULATION_COLLISION_SEPARATION_CONTRACT_NOT_CAPTURED`。

- H21/H22 已摘录：W4 `Dop/flipobject.overridecollisionsep` toggle/1、`collisionsep` float/1；`Dop/flipconfigureobject.coldivsize` float/1 默认跟随 `divsize` 表达式；SOP FLIP 内部 flipfluidobject consumer。未证 SOP 公共可写入口。
- 先采集：`Sop/flipcollide`/`Sop/flipsolver` 实际 collision SDF/velocity 场路径与消费；合法 editable 的 override/default 入口及机器键（待采集）；场网格边长/变换、SDF/velocity 端口。现合同 container→collisions→solver 的 0/1/2 路与 collision geometry→collisions 输入3，只是必须逐边读回的合同，不能替代实例证据。
- basis：实际跟随默认策略、有效边长与 domain/grid 预算。正值验证绝对边长，0验证回到本版/本图默认且碰撞仍启用；不得改 particle_separation、mesh 或 padding；负值、没有默认读回或细分预算不足拒绝。

### A03 · water_flip_v1.collision_passes · integer 1..1000

Blocker：`FLIP_COLLISION_PASSES_NATIVE_FIELD_NOT_CAPTURED`。

- H21/H22 已摘录：FLIP 分离/子步相关接口；W4 明确没有 collision_passes 映射。`partsepscale` 和 solver substeps 不能充当循环次数。
- 先采集：Gas Repeat/Move-to-Iso 是调查方向，**精确 category/type/机器次数与停止 field 均待采集**；记录合法 editable 边界、一次完整 SDF采样→位置纠正的实际 ports、粒子 P/SDF/velocity 数据绑定、每个 FLIP 子步中的执行位置与消费次数。
- basis：真实子步时序和一轮循环定义。正常核对 1 与一个预算内整数的实际循环次数、solver substeps 不变；0、负数、小数拒绝；1000 必须满足性能/时间预算，不能为通过而取整或减次数。

### R01 · rbd_destruction_v1.fracture_scale · .001..1000

Blocker：`PHYSICAL_FRAGMENT_SCALE_CONTRACT_REQUIRED`。

- H21/H22 已摘录：HDA/SUP `Sop/rbdmaterialfracture` 材料专用字段；没有通用 `piecesize` 的成立证据。
- 先采集：合法通用采样/切分 operator、目标长度/种子/密度精确 fields 和 ports（待采集）；闭合几何→sampling/cutting→实际 piece/name→packing/constraints 的完整消费。现有 fracture 0/1/2→configure 0/1/2 的三路合同须实例验证。
- basis：闭合源体积、源尺寸与 SHA、稳定 piece/cell ID、碎片预算和材料/packing/constraints 对应。正常读回每片实际体积及 `V^(1/3)`，目标更细时保留整体轮廓/尺寸；不要求所有片精确同大。0/负值、无闭合体积的曲面或预算超限拒绝。

### R02 · rbd_destruction_v1.fracture_variance · 0..100

Blocker：`FRACTURE_VARIANCE_DISTRIBUTION_CONTRACT_REQUIRED`。

- H21/H22 已摘录：断裂种子/材料字段，不证明可变目标尺度；`concrete_strengthvariance` 不是这项方差。
- 先采集：沿 R01 图的可变目标尺度消费 operator/field 或合法 program 载体与 inputs、稳定采样 cell ID、seed/子 seed 的真实来源和 clipping 后 piece 输出。分布程序及 basis SHA 必须能保存读回。
- basis：正 L、稳定 cell ID、冻结任务 seed。0验证统一 L；正常逐 cell 核对 `L*q`、q均匀区间 `[1/(1+p/100),1+p/100]`，100为 `[L/2,2L]`；实际碎片体积不是自动成为同分布证明。负值、ID/seed缺失、程序/输入漂移拒绝。

### R03 · rbd_destruction_v1.impact_spread · 0..1000

Blocker：`IMPACT_SPREAD_SEMANTIC_CONVERSION_REQUIRED`。

- H21/H22 已摘录：`Sop/rbdmaterialfracture.glass_impactspread` 是玻璃专用；W4 有 RBD name、约束与消费帮助，未捕获通用冲量分配入口。
- 先采集：合法瞬时冲量注入 operator/field/ports 和实际 packed piece 的质心、ID、空间；属性 class/storage/tuple、每片 solver 读取时刻（均需新增证据）。不得将 impact threshold、glue strength 或 World Scale 写成冲量半径。
- basis：与 R06 同一事件 ID、中心、明确命中 piece、J0 向量与激活时刻。r>0逐片验证 `max(0,1-d/r)`，r=0只命中片权重1；缺命中ID拒绝，不猜最近片。保持 fracture 拓扑和胶合；事件重放不重复注入。

### R04 · rbd_destruction_v1.piece_scale · .001..1000

Blocker：`ACTUAL_PIECE_SCALE_GEOMETRY_CONTRACT_REQUIRED`。

- H21/H22 已摘录：rbdconfigure/solver 的 scale/density 相关字段只说明现有接口。`Sop/rbdconfigure.density#` 静态记录是 string/1，不能据名称推断实际 mass/density 属性类型；Exploded/World Scale 不是几何倍率。
- 先采集：真实 unpack/pack、pivot/full transform/intrinsic 和几何缩放的精确入口/ports；碰撞 shape 消费、density→mass/inertia、约束锚点重建及实际属性 class/storage/tuple。必须查明断裂后、configure 前如何合法接入，不保留失配的旧碰撞或锚点。
- basis：静止质心、原几何/密度/体积/constraints SHA。1为原样；缩小/放大读回质心不动、真实几何/shape及质量惯性一致；0/负值、无体积或重建事实、重叠/资源不满足时拒绝。

### R05 · rbd_destruction_v1.velocity_variance · 0..1000

Blocker：`RBD_VELOCITY_VARIANCE_ATTRIBUTE_CONTRACT_REQUIRED`。

- H21/H22 已摘录：`Sop/rbdconfigure`、`Sop/rbdbulletsolver` 与 overwrite 字段；没有已捕获的 RBD 初始 v writer。POP Source `var` 是粒子接口，不能迁用。
- 先采集：实际 v 属性合法写入位置/ports、class/storage/tuple/空间、Bullet initial/activation 与 overwrite 读取时机；configure 几何路0→solver输入0须实际验证。冻结 `v_base` 并读回角速度 w 不变；不得在每帧累加。
- basis：稳定 piece ID、任务 seed/子 seed、基准 v、激活时刻/FPS/time scale。正常逐轴验证 `v_base+a*u`、u独立均匀[-1,1]；0恢复基准，重开复现相同样本；缺ID、基准或时机证据拒绝，保留 drag/gravity。

### R06 · rbd_destruction_v1.impulse_scale · 0..10000

Blocker：`RBD_IMPULSE_SCALE_SEMANTIC_CONVERSION_REQUIRED`。

- H21/H22 已摘录：约束 impact/solver 帮助不证明瞬时冲量接口。
- 先采集：与 R03 共享的合法瞬时 impulse 输入 operator/fields/ports、mass 实际读取、属性类型/单位、一次性事件及子步积分消费、save/reload 去重。若走速度注入，采实际质量与 `delta_v=J/m` 的消费，不把力或阈值当冲量。
- basis：可信 J0（实际质量单位×SU/s）、每片质量、事件 ID/中心/命中片/激活时刻、R03权重。正常核对 `J=value*weight*J0`；0无该脉冲且基准v/其他力保留，1复用J0；缺J0/质量/事件、零质量或重复事件拒绝。

### P01 · particles_v1.emission_variance · 0..100

Blocker：`PARTICLE_EMISSION_VARIANCE_NATIVE_FIELD_NOT_CAPTURED`。

- H21/H22 已摘录：`Dop/popsource::2.0.constantrate` float/1、`seed` float/1、`doid` toggle/1；`constantactivate/impulseactiveate/scalebyarea` 门控。不证明动态 rate 消费与积分。
- 先采集：实际 rate expression/program 的合法机器载体与子步读时机、source→solver 粒子/ID ports、出生起点/FPS/timescale、seed及每1场景秒桶边界/亚帧积分；记录动态 rate 与 native 硬范围/预算关系。
- basis：birth_rate、出生时间原点、固定任务seed/子seed。核对 `rate=birth_rate*(1+p/100*u)`，同桶不重抽；0原速率、birth_rate=0始终0，100不产生负速率。缺时间/seed、错误 impulse/area模式或倍率越原生硬界拒绝；不改寿命和速度。

### P02 · particles_v1.size_variance · 0..100

Blocker：`PARTICLE_SIZE_RANDOM_RANGE_AND_BASE_SIZE_CONTRACT_REQUIRED`。

- H21/H22 已摘录：`Sop/attribadjustfloat.attrib/class/singlevalue/minvalue/rangevalue` 与 pscale 相关菜单；W2 可作合法 program 载体调查依据。
- 先采集：稳定粒子 ID 与出生时的随机属性消费、pscale class/storage/tuple、真实随机分布/program/seed、simulation→particle_size→instances 的 ports，以及 `Sop/copytopoints::2.0` 对实际 pscale 的消费。既有 uniform `[1,1+value]` 程序不能直接替代新分布。
- basis：独立 size、ID、任务seed/子seed与组合顺序。正常验证 `size*q`，q均匀 `[1/(1+p/100),1+p/100]`，100为[size/2,2size]；0精确size，跨帧/重开不抖动；physical collision radius 不变。缺ID/基准或半径与尺寸混绑拒绝。

### P03 · particles_v1.collision_radius · 0..1000

Blocker：`PARTICLE_COLLISION_RADIUS_NATIVE_CONVENTION_REQUIRED`。

- H21/H22 已摘录：`Dop/popsolver::2.0.docollision/collisionresponse`；独立物理 radius 的 carrier 与零半径模式未捕获。Hair/Vellum同名事实不适用。
- 先采集：POP collision shape/mode 与合法独立 radius 属性/fields（待采集）、class/storage/tuple、solver/object gates、SDF/geometry输入及碰撞消费者；同时采 render pscale 的独立载体与 copy消费，不能改size冒充radius。
- basis：实际 collision mode/convention、SDF变换、radius载体和基准size/v。正半径核对真实消费，0验证点粒子碰撞且 collision detection 仍开启；负值、不支持独立radius/精确0或缺SDF拒绝，不换碰撞模式静默规避。

### P04 · particles_v1.trail_length · 0..10000（允许小数）

Blocker：`PARTICLE_TRAIL_GEOMETRY_GRAPH_REQUIRED`。

- H21/H22 已摘录：GEO 提供几何输入/输出查询签名；当前材料未证明 Trail/历史支路的精确 operator/fields。
- 先采集：合法历史读取和 curve 输出 operator、machine fields/ports、ID关联/断轨/出生/死亡策略，场景帧样本及窗口起点线性插值的真实消费；前史来自已登记/可追溯样本，记录授权、operation/artifact 与内容SHA。
- basis：当前f、稳定ID、实际历史/出生帧和资源预算。验证窗口[f-L,f]、小数不取整、出生晚于起点从出生样本开始、死亡粒子不继续输出；0只原粒子/实例。历史缺失或未经授权拒绝，不造样本、不悄悄截L，simulation v 保留。

### P05 · particles_v1.motion_blur_scale · 0..100

Blocker：`PARTICLE_RENDER_MOTION_BLUR_BINDING_REQUIRED`。

- H21/H22 已摘录：W1 的 SOP Import helper 与 USD Render 路径，不包含这项完整 velocity-blur 绑定；帮助/LOP类名不能当 renderer instance。
- 先采集：真实 SOP Import velocity attribute→USD `velocities` 映射，精确机器 field/gates、点/实例 prim类型、ports/路径、FPS/time samples、Karma velocity-blur最终消费与 motion-vector读回；`render_v` 是产品概念，实际 carrier/绑定名称待采集，不能假定同名native属性存在。
- basis：实际 simulation_v、FPS/timescale、表示方式及 renderer绑定。0无该 velocity贡献、1原样，shutter/模拟v/P保持；不承诺关掉其他模糊。pure deformation模式、缺绑定或单位/时间错配拒绝。

### S01 · swarm_flocking_v1.target_noise · 0..100

Blocker：`SWARM_TARGET_NOISE_NATIVE_GRAPH_REQUIRED`。

- H21/H22 已摘录：`Dop/popsteerseek.goal` vector/3、`attracttype/forcescale/uselocalgoal`；`goalprevious` 的 HDA/SUP tuple矛盾须按第3节处理。
- 先采集：合法 goal 动画/noise operator/field 或表达式载体、真实向量/tuple/参考空间、每1场景秒采样与线性连接消费、seed/time来源、seek/solver ports；既有 goal 驱动保护及保存重开规则。不得借不存在的seek噪声字段执行。
- basis：actual goal_base、时间原点/FPS/timescale、seed/子seed。整个swarm共享球内均匀目标样本，不给每粒子另造goal；0精确基准。缺基准、覆盖未授权driver、tuple冲突或时间来源不明拒绝，不改源/初始v/goal_attraction。

### S02 · swarm_flocking_v1.noise_strength · 0..1000

Blocker：`SWARM_FORCE_NOISE_NATIVE_GRAPH_REQUIRED`。

- H21/H22 已摘录：`Dop/popforce.amp` float/1、`swirlscale` float/3、`rough` float/1、`offset` float/4、`activate/ignoremass/uselocalnoise`；`Dop/popsolver::2.0.externalforce/integratevel/integratepos`。这是粒子可复用设计依据，不证明swarm已接噪声图。
- 先采集：swarm中独立、自有、可编辑 POP Force 支路的实际类型、门控与 ports/连线及 solver force消费；频率/roughness/时间噪声/随机来源完整读回。seed采用真实来源，不能因产品seed规则猜 POP Force 有一个 `seed` 机器键。
- basis：明确冻结 frequency/seed/roughness、Ignore Mass 与time context。0该新force为0，正值amp实际生效；flock/seek与权重不动，不宣称SI加速度。缺上下文、未接入externalforce或改变既有受力拒绝。

### O01 · water_ocean_v1.directional_spread · 0..360

Blocker：`OCEAN_ANGULAR_SPREAD_TO_NATIVE_BIAS_CONVERSION_REQUIRED`。

- H21/H22 已摘录：`Sop/oceanspectrum.dirbias` float/1，默认2、滑条0..10；`winddir` float/1；VOL 的静态体积材料。滑条不是硬范围，未有完整角宽转换公式。
- 先采集：本版谱型/方向权重公式、`dirbias` 的真实消费与精确endpoint可表示性；若不能精确转换，采合法自有角谱处理operator/fields/ports（待采集）及真实谱输出→evaluate消费、体积类型/变换/权重归一化。
- basis：actual wind_direction、原径向谱/能量/波高基准、seed/谱型。验证完整支撑角宽、均匀角权与总能量不变，0精确单方向、360全方向；不得用epsilon或 `(360-width)/36` 线性别名、换谱型。端点不具备事实时继续blocked。

### G01 · procedural_geometry_v1.scatter_variance · 0..1000

Blocker：`SCATTER_STATISTICAL_VARIANCE_CONVERSION_REQUIRED`。

- H21/H22 已摘录：SC 的 Scatter2 count/density键，SUP/W2 的 scatter/attribwrangle候选接口；未证位置扰动/同连通表面投影。
- 先采集：稳定point ID、源连通表面/法线/切平面basis，合法投影/最近点operator/API与精确 fields/ports（待采集）；source→scatter 与扰动→instance 点输入的真实消费，越边/孔洞/多表面选择与唯一性。
- basis：源表面SHA、原P/count/density模式/seed、稳定ID/子seed。验证局部切平面均匀圆盘采样→同表面投影，仅P改变；0原P，数量不变，不把edge结果冒称均匀。投影歧义或跨连通面拒绝，不改relax/count/seed替代。

### G02 · procedural_geometry_v1.rotation_variance · 0..360

Blocker：`INSTANCE_RANDOM_ROTATION_ATTRIBUTE_GRAPH_REQUIRED`。

- H21/H22 已摘录：SUP `Sop/xform.r` float/3、`scale` float/1，copytopoints候选；没有新orient随机图的实际消费证据。
- 先采集：orient quaternion 的class/storage/tuple、可信局部Z轴、弧度/度转换与组合次序、合法随机program/field、源变换/实例点→`Sop/copytopoints::2.0`精确ports和orient消费；必须确认existing orient与transform如何组合。
- basis：原orient/源实例变换、稳定point ID、seed/子seed、可信局部轴。验证源变换后局部Z扰动均匀[-value/2,+value/2]，360为全圆；0原姿态，P/scale与已有X/Y/Z基准不变。缺轴/ID或全三轴覆盖现有旋转拒绝。

### G03 · procedural_geometry_v1.deformation · 0..100

Blocker：`INSTANCE_DEFORMATION_NATIVE_GRAPH_REQUIRED`。

- H21/H22 已摘录：W2 `Sop/attribwrangle.class/snippet/group/vex_precision`；仅支持合法载体调查，不证明变形已实现。
- 先采集：实际 rest-space P/N/bbox属性与class/storage/tuple、pack展开和局部空间、原生wrangle/VEX或等价deformer精确fields/ports；instance_source在copy前、既有scale/rotation前的真实消费及program/输入SHA读回。
- basis：冻结源bbox起点/非零局部X跨度Lx、N_base和原几何。验证 `P'=P+d*sin(2*pi*x/Lx)*N_base`、相位0、拓扑/实例点/count/seed/pscale保留；0恢复上游，后续scale共同放大幅度。Lx=0、缺N或错误阶段拒绝，不猜波长；自交/预算另核对。

## 5. B：已批准的球壳、次级碎屑及 meta 映射仍须采集

B不新增或解除上述20项机器映射，也不把Explosion虚构成第16个versioned native合同。当前planner的 `shockwave` branch是 `procedural_geometry_v1`；branch名称和hash不证明源就是球壳。以下每项在H21.0.631和H22.0.459分别继承C0及第6节；涉及最终合成时再单独取得Nuke17.0v1的真实证据，不能用Houdini静态材料替代。

### B 的当前映射与继承缺口

| 当前组合控制／原区间 | 当前源码路由与已批准解释 | 合流/执行前必须补的事实 |
|---|---|---|
| `fire_energy` 0..10；`fire_scale` 0..100 | `fire.burn_rate`／`fire.fuel_rate`；火焰耗尽率／源flame输入率，不宣称Joule或整体几何scale | 冻结meta→fire domain/native version/control的实际绑定与上下文；真实source rows/field消费。burn_rate=0仍有 `ZERO_FLAME_DEPLETION_NATIVE_TARGET_NOT_CAPTURED`；不可塞很大lifespan规避。组合fire_scale上限保持100，不能放大成分域fuel_rate的1000。 |
| `smoke_dissipation` 0..5；`smoke_scale` 0..100 | `smoke.dissipation`／`smoke.density_scale`；烟消散／density输入率 | 任务自有smoke图、solver门控及density源输入/产物绑定；0沿分域含义读回，不由组合名生成通用原生别名。 |
| `spark_rate` 0..10000000 | `particles.birth_rate`；粒子每秒出生率 | POP Source实际持续发射门控、FPS/time scale、子步积分与粒子branch产物/seed；不新增未批准的impulse或面积语义。 |
| `debris_scale` .001..1000 | `rbd.fracture_scale`；继承R01目标碎片长度 | R01完整采集及meta→实际RBD图/冻结源/版本/产物绑定；不是整体模型缩放。 |
| `debris_energy` 0..1000 | `rbd.velocity_variance`；继承R05每轴±随机初始速度幅度SU/s | R05完整采集、baseline v/稳定piece ID/seed/激活时刻与meta绑定；0无新增随机v，不当Joule或冲量。 |
| `shockwave_scale` .001..10000 | `shockwave.scale`，planner选procedural_geometry；已批准自有球壳源均匀倍率，1原样 | 下面球壳输入/合法图/实际半径时间函数与meta source绑定；通用 `Sop/xform.scale` 存在不证明球壳/动画成立。 |
| `shockwave_thickness` 0..1000 | 现runtime有控制，但不在 `EXPLOSION_BRANCH_CONTROL_MAP` 或PG native合同；已批准scale前完整径向厚度SU | 下面完整厚度承载物、合法shell/thickness算子、两版ports/读回和明确meta路由；不能映射solver collision_thickness。 |
| `debris_amount` integer 0..1000000 | map指向 `rbd.debris_amount`，但FR合同无此项；已批准随父RBD片运动的次级几何屑总数 | 下面次级屑采样/稳定ID/锚点/父变换消费及正式meta绑定；同名map不证明RBD已有writer，不将generic piececount/fracturecount当接口。 |
| `comp_contrast` 0..10 | Nuke composite_patch路线，当前addon `effect_contrast` 候选 `contrast`；沿实际Nuke contrast合同 | Nuke17.0v1真实ColorCorrect/knob、颜色/通道/预乘及图端口读回；实际消费登记的分域产物与需要的可信双输入。类名、候选knob或手写成功gates不能证明完整链。 |

以上路由是当前copy源码事实；旧Explosion泛型 `burn/burnrate/piecesize/uniformscale/...` 候选列表不提供新原生事实，也不能替代分域写入计划。参数区间不改；缺路由、缺输入或分域blocked时明确拒绝，不能只因B已批准接受图摘要/任意几何。

### B 球壳：必须冻结的输入与两版采集

- 场景输入：可信源中心及坐标/变换、**显式冻结的基准半径时间函数**与时间原点/FPS/time scale、源几何/单位、scale与完整厚度的输入SHA。B没有给定具体中心、初始半径、扩张速度或动画曲线；不得猜创作数值。
- 精确接口：SUP有 `Sop/sphere.rad` float/3、`scale` float/1和 `Sop/xform.scale` 的静态记录，但球壳/厚度算子及动画承载fields/ports仍待采集。分别取得本版合法源/shell/thickness/animation算子完整名称、机器参数/tuple/menu/driver/可编辑性与真实连接，证明输出是球壳，不是默认grid/sphere实例。
- 消费与读回：在scale前以基准半径两侧各厚度/2构成，scale同乘半径和厚度；读实际内外半径、中心、topology/normal/transform及时间采样，绑定PG shockwave源与正式输出/产物。0厚度为未增厚表面；负值或使内半径≤0的厚度拒绝。不能通过任意epsilon/夹紧偷偷保留非零内半径。
- 正常/反例：1倍率原样、正倍率及两次明确时间样本与冻结函数吻合；0厚度读回表面。缺中心/半径函数/时间基准、错源、厚度过大、非自有图、动画或meta绑定漂移均拒绝；保存重开必须复现原曲线/driver和实际几何，不重新apply生成成功证据。

### B 次级碎屑：必须冻结的输入与两版采集

- 场景输入：已登记主RBD碎片产物ID/版本/operation/内容SHA、稳定父piece ID、静止父片表面积与采样坐标、**次级实例源尺寸/几何基准**、固定任务seed/独立子seed、精确总数和预算。未给实例源尺寸或父变换样本继续缺项，不能选择默认大小或任意父片。
- 精确接口：按静止父片表面积采样的合法原生operator/fields/ports、stable parent/child ID、局部锚点、实际父片transform/intrinsic与 `Sop/copytopoints::2.0` 实例消费须分别采集。SC只证明已有count/density语义，不证明父片面积分配、exact total、稳定锚点或运行跟随；具体新attribute名/class/storage/tuple与meta字段仍待事实支持。
- 消费与读回：总数是次级几何屑实例，独立于R01主片尺度；逐child绑定父piece与静止局部锚点，再消费**登记的**父变换。保留主fracture、constraints与实际主RBD运动；不新增独立弹道、物理解算、约束或碰撞。不把多断主片数冒充debris_amount。
- 正常/反例：0不产生次级屑；预算内整数读回exact count、按面积来源/seed重开稳定且随父变换移动；主片数量/拓扑保持。负数/小数、父产物过期/未登记、ID/源尺寸/transform缺失、面积不可用、计数或预算超限拒绝；不得四舍五入或重抽样。

### B meta 与真实产物依赖

冻结并读回同任务的 branch ID、domain/version、控制路由及control/basis SHA、当前owner/native plan/graph版本/HIP SHA；fire/smoke/shockwave/particles/RBD的实际产物分别绑定operation、artifact ID、帧集合、场景逻辑身份及内容SHA。Nuke消费这些登记产物的实际文件、颜色/布局/预乘/帧，不由branch名、branch_hash或独立合成EXR推导上游成功。旧request改内容、错误owner、过期graph/HIP、缺branch路由/producer、外部未登记输入均须在既有合同处拒绝。此清单不改 controller 或引入新批准层；B可review metadata由main后续单独明确。

## 6. 两个版本的新实例、保存重开与正常/反例证据

| 目标 | 当前状态 | 授权后的最小真实证据 |
|---|---|---|
| H21.0.631 | 实例/仿真/缓存/渲染/重开 **NOT_RUN** | 本版原件/C0；每项正常及反例实际trace；新自有实例写入/消费、保存HIP SHA、确认旧自有worker退出、新PID/nonce实例重开与原生直接读回。 |
| H22.0.459 | 实例/仿真/缓存/渲染/重开 **NOT_RUN** | 独立取得本版同样证据；不得引用H21的node/tuple/token/ports/结果替代。 |
| B最终Nuke17.0v1消费 | 真实NK/渲染/交付 **NOT_RUN** | 另行具体授权后真实task-service计划/运行/结果、登记输入/版本/帧/内容SHA与ColorCorrect消费；NK保存、新实例重开及最终输出。Houdini两版各自分域产物链单独绑定。 |

所有操作都复用现有任务服务、事务围栏、scheduler、操作记录、artifact registry和授权合同；不要另写“符合清单即PASS”的引擎。以下是待执行证据要求，不是本次已运行命令：

1. **正常路径**：冻结本decision/basis与build、native version/plan、owner/graph/scene身份；在fresh自有图实际承载物中写入、观察consumer，保存每节规定的0/1/正值/合法负偏移/小数帧/完整角宽端点。不能执行的原生端点继续具体blocked，不能先写请求值再当读回。
2. **保存与新实例重开**：保存HIP及SHA、原生参数/属性/channel/program/拓扑和输入SHA；监督器确认旧自有worker停止后新PID/nonce加载同HIP，直接读取，不重新apply、不重抽seed、不烘焙后再回填checkpoint。记录恢复当前frame和FPS/time scale；不要因保存过请求JSON宣称图持久化成立。
3. **共用拒绝路径**：有限数值与原区间、bool/小数整数误用、未授权cache/render、缺/错误basis、错误版本/alias/tuple/port/menu、lock/disabled/hidden、非自有driver、旧owner/graph/HIP、程序或输入SHA漂移；拒绝发生在实际写入前，并留完整回滚/不污染无关字段证据。
4. **随机/事件/动态**：固定任务seed+stable ID+独立子seed与实际样本对应；换一控制不重抽其他控制，同值新实例可复现。R03/R06及R05只在约定事件消费一次；同request重试不重做，旧ID改内容拒绝。历史不足、精确端点不具备事实和事件去重缺失均不能伪成功。
5. **产物与资源**：如果授权包含动态/缓存/渲染，记录真实场/geometry/EXR/运动向量等产物的完整内容SHA、frame/layout/消费、operation停止事实及登记；严格保持12帧/120秒和总磁盘预算。域shape/数据一致性与人工视觉结论分别报告，单个参数readback不等于效果成立。

## 7. 本次只读源 hash 与 commands 审计

工作目录：`C:/Users/32200/Desktop/Agent/skill/Bridge/outputs/windows-followup-20261004/repair-staging/approval-contracts`。工具/源码/旧静态JSON从此copy读取；批准记录和proposal仅从原仓库只读，未复制或修改。下面保留**最初单doc阶段**23项历史字节SHA；此后获授权修改两个工具/共用locator/现有capture test，并追加本机静态输出。原ROOT批准记录已追加B，表中该记录及两个工具的历史SHA不代表最终字节；最终五文件由旁置 `aftermanifest.json` 绑定。批准定义及三native模块仍与表中一致。

| 读取来源 | SHA-256 |
|---|---|
| 原ROOT `handover/CONTROL_DECISIONS_20261004.md`（首次读取的20项记录，历史SHA；当前已追加B） | `0105a8b314d6efd3c41b010d7fba5413c681ced0d67ef0291ff4670a3553876b` |
| 原ROOT `outputs/windows-followup-20261004/control-decisions-proposal.md` | `7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e` |
| `tools/capture_native_schema.py` | `2efbe1f9a5cb4b8666f85733cf29632389879e15c191aff62fca7b79800d5d12` |
| `tools/audit_domain_native_basis.py` | `c86040cee043d08c43b83333c99742b81111ceb4467273a4790e1b978f8f5603` |
| `packages/houdini-bridge/src/houdini_bridge/product_control_definitions.py` | `8a2f459fe27abe2efb4116a8c9c54a88c84608a93a4d1947578b50681007d871` |
| `packages/houdini-bridge/src/houdini_bridge/native_pyro_domains.py` | `de7a6ccc82fed8c42f58b42d119edb125f7c0c1bae5ba1010ed385eb42122ebe` |
| `packages/houdini-bridge/src/houdini_bridge/native_flip_rbd_domains.py` | `4358611600482eb7b6f6e6242a516329fef64911a07a95c0b52a1809225968f5` |
| `packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py` | `3532f99cca9873ea06759f8369587922db0cd9db9b976a2ae561408b873179be` |
| `docs/native-basis/hda-interface-capture.json` | `a0e96e0d1ce57f91c53b2f00c1a0993df60f091f8b3b67fa267070340cac7dac` |
| `docs/native-basis/native-boundary-metadata-supplement.json` | `416d63f1f6c4d9183fbd8dfe83adbb8dcfaa6fc6965fd698318b42fca4e3ce3f` |
| `docs/native-basis/w4-glue-collision-static.json` | `68faaeb702b4e23a24df2ca7ca38b620cea71c87eaf2e041cc4f3852e8da5779` |
| `docs/native-basis/w2-wrangle-convolve-static.json` | `5a10fa158ae7e153cbc62054da2895fab32fc8a1a1c527d42d80a9853b05a3f6` |
| `docs/native-basis/scatter2-sdk-help-static.json` | `08a1ede5c3535184b974505d81ca2f644172d68ba6442a20bcac399b128aec52` |
| `docs/native-basis/hom-attribute-numeric-storage-static.json` | `2d9fb13ee492766261b6ae53e04a720d2ea52ff5fb0b3222bba97a8c8c906059` |
| `docs/native-basis/sopnode-geometry-output-static.json` | `f0433ca9ef58dd0bcf3b6ac0e21c2a03259f21b5cb692ebfa7371a43eebfd73f` |
| `docs/native-basis/ocean-volume-hom-static.json` | `c0940b9eaf056cd4b8c86a917b4388eb532dfa126ec546ffaa38f1a801118fc7` |
| `docs/native-basis/w1-sopimport-usdrender-static.json` | `e2e88bdbeb9270e4bcf3fd5242958c9dc618faae123247995c63db0718f7162e` |
| `docs/native-basis/domain-native-documentation.json` | `43ba32c0d518d94b0dbf57e6f8bc395c2c8f38718a51b26bb969669ce5d45d8c` |
| `packages/vfx-pipeline/src/vfx_pipeline/service.py` | `71a198a6b44f25a68d125e763ee8a2f4c812fdb2869271c3017490b558971d28` |
| `packages/vfx-pipeline/src/vfx_pipeline/planner.py` | `59ba56fc7ec810caf1d1080680e6c25cbf94d4e9b5d10206dd95a3ad7317da1b` |
| `packages/dcc-task-runtime/src/dcc_task_runtime/domains.py` | `2916642848a05924a4418e47dc96d6e92be37790b5c4ea6580ce89369babfbda` |
| `packages/houdini-bridge/src/houdini_bridge/domain_packs.py` | `fa8fb28cd42a4fd64ebed32c5fdf5a65b62632ed65a223d6a913d40296d374f7` |
| `plugins/nuke/nuke_bridge_addon.py` | `821cacc40fc1c280a20a04542d2ec6739f9107442315799a626b04753749ae83` |

最初单doc阶段的只读命令类别：PowerShell `rg --files`、`rg -n`、`Get-Content`（含定向 `Select-Object`）；普通仓库Python `-B -c` 只读文件、JSON与CLI AST、检查引用路径和计算hash。当时没有执行采集工具、测试或联网，写入仅本doc。后续静态采集子任务的实际命令和结果如下；两个阶段均没有导入/调用Houdini或Nuke API。

历史CLI AST审计：当时capture为 `{--output, --install-root}`，audit只有 `{--output}`。**历史最终两工具均为 `{--output(required, Path), --install-root(Path, default=/Applications/Houdini), --install-layout(choices=macos/windows, default=macos), --build(append, choices=21.0.631/22.0.429)}`**；第2节Windows命令对应当时两版；当前CLI的默认及choices见第2节现行接口表。

新增文档前，copy的725个非outputs/非pycache/非git/非venv文件按相对POSIX路径→原字节SHA保存于内存；该JSON（`sort_keys=True,separators=(',', ':')`、UTF-8）的SHA为 `2f733f2688cfed2144798f94b629c37c8ccef1f02a3e283806fc25850ad75d5d`。首次终端输出中五个中文路径出现解码替代字符，交付核对已按各自目录及唯一匹配的内容SHA对应原路径，未将其当成删除/新增文件。

单doc阶段交付核对：725个既有文件内容SHA一致，唯一新增本doc；20个decision_id集合与20个blocker核对一致。追加静态工具任务后，冻结五文件、weak-model/9fixtures及旧native-basis JSON仍不改；最终changed paths仅本doc和指定四个代码/test文件，详细字节核对见 `outputs/windows-followup-20261004/approval-contract-evidence/windows-native-static-20261004-1935/aftermanifest.json`。本审计不是运行验收，实例及真实阶段仍NOT_RUN。

### 追加静态任务：实际结果及审计文件

- 纯目录/INDX/help ZIP夹具复现：12项，4ERROR/1FAIL；最终12项全过。macOS默认两版、Windows精确parent/build目录、不向22.0.368回退、UTF-8非ASCII输出及实例gate仍false均有回归。既有双候选拒绝夹具与main当前修复保持一致，不削减覆盖。未重跑全量/正式进程。
- 最终定向命令：原仓库普通Python `-B -m unittest discover -s tests/unit -p test_native_basis_capture.py -v`，通过现有logger记录。日志位于 `outputs/windows-followup-20261004/approval-contract-evidence/windows-native-capture-before-20261004-193228.log` 与 `windows-native-capture-after-final-20261004-193735.log`；最终returncode=0。
- 本机静态原始日志：同目录 `windows-native-static-hda-20261004-193430.log` 和 `windows-native-static-help-20261004-193431.log`，均returncode=0；完整argv、cwd、解释器、真实source tree hash和UTC在原日志中。未执行DCC/hython/API/联网。
- Windows新JSON SHA-256：HDA为 `e84fe04d2f6a995fa757dbf0bd8766252c1a80501a92536c8a2fefd243501558`；help为 `2b566b729ef3a32fe30e98f76a36585dc500c949ac05e81b560c53eca2f0d5fd`。
- 对旧记录差异：两版各5个HDA archive及1个help ZIP的hash均与历史mac记录不同，不能把旧archive SHA替换成Windows SHA；每版40个选定DialogScript hash相同，`Vop/mtlxdisplacement`、`Vop/mtlxnormalmap`、`Vop/mtlxsurfacematerial` 三个不同。参数输出还包含已存在解析器相对旧摘录的元数据恢复差异，不能将全部参数差异归因Windows原生变化。help按当前domain目录重新审计，目录版本差异和原件差异不能混为厂商变化。
- 全部12个原件实际path/size/SHA、旧path/hash、逐operator差异摘要与help缺口变化保存在 `outputs/windows-followup-20261004/approval-contract-evidence/windows-native-static-20261004-1935/static-capture-audit.json`。最小补丁 `minimal.patch` 只含四个指定代码/test文件及本doc；不含stage旧改动。最终五文件及保护文件SHA由同目录 `aftermanifest.json` 绑定。
- C0只推进已选静态原件部分；20项及B仍缺上文明确basis、新原生入口、真实ports/属性消费、保存重开/正常反例。`native_status=blocked` 不变，不能由静态CAPTURED推导实例/视觉/生产PASS。
