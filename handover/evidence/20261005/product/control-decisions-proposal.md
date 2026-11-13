# 全16域 M1 控制语义审批建议（给 main）

日期：2026-10-04；状态：**PROPOSED / NOT_CONFIRMED**。本文件是产品建议与只读盘点，不是实施记录、审批事实或验收证明。全部建议须获用户明确审批后方可实现；批准产品定义也不能代替缺失的原生事实。

## 1. 先回答：多数未定控制是否其实已实现？

**否。当前真正列为未定的20个域内控制仍全部是 `native_status='blocked'`，没有可执行的控制写入计划。** `native_pyro_domains` 1项、`native_flip_rbd_domains` 8项、`native_particle_ocean_geometry_domains` 11项，共7域。后两个模块的 `control_write_plan()` 在数值验证后、拓扑或原生写入之前直接按 blocker 拒绝；Pyro 同样先拒绝 blocked。这些不是仅缺测试或只差把文档标成完成。

反过来，不能把历史 blocker 总表当成当前缺口：Crowd `animation_blend`、`route_weight`，粒子 `force_strength`、`force_noise`、`cluster_strength`，以及 Cloth wrinkle、Ocean foam 等已存在明确合同或 semantic program。它们的实现存在与真实宿主、视觉或完整 M1 验收成立是不同结论。RBD `activation_frame` 已有定量定义，故不列入新的产品选择。

本盘点以 [REMAINING.md](../../handover/REMAINING.md)、当前 `packages/houdini-bridge/src/houdini_bridge/native_*` 为主，补读当前组合路由以覆盖第16域。并行只读搜索、源码/JSON读取、AST解析及SHA计算；**未运行测试、正式入口、生成器、DCC、模型、仿真、缓存或渲染；唯一写入是本文件。** 没有将其他版本的接口映射当作本版本事实。

### 全16域核对表

“0”仅表示本轮没有新增的整项 blocked 产品控制；不表示该域完成、所有端点可执行或所有原生事实齐备。

| 域 ID | 当前整项 blocked 数 | 当前结论／本文件位置 |
|---|---:|---|
| `pyro_smoke_v1` | 0 | 核心控制有映射；`denoise_mix` 为外部合成路线，见端点/链路表 |
| `pyro_fire_v1` | 1 | A01 `flame_height`；另有已定 `burn_rate=0` 的原生目标缺口 |
| `particles_v1` | 5 | P01–P05；粒子 force 三项、life/velocity variance 已有定义，排除 |
| `water_ocean_v1` | 1 | O01；foam/mask semantic program 已存在，排除 |
| `water_flip_v1` | 2 | A02–A03；内部场分辨率和碰撞迭代接口须分开 |
| `crowd_agents_v1` | 0 | `animation_blend=0–10秒` 已确认；route、clip/timing、原生wander等已有合同 |
| `swarm_flocking_v1` | 2 | S01–S02；seek 修正不代表这两项已补图 |
| `vellum_cloth_v1` | 0 | stiffness、thickness、wrinkle 等有定义与计划；wrinkle program 不重问 |
| `vellum_softbody_grains_v1` | 0 | 分别核对 softbody/grains；softbody 中 grains 专属项是 `branch_required`，不是语义未定 |
| `hair_fur_v1` | 0 | collision radius 有 `native_pscale_radius/1`；其原生上下文事实缺失不能改称产品未定义 |
| `rbd_destruction_v1` | 6 | R01–R06；activation_frame 已有整数帧阶跃语义，排除 |
| `procedural_geometry_v1` | 3 | G01–G03；现有 variation/scale_variance 的 `[1,1+value]` pscale 范围、Z rotation、count/density 定义排除 |
| `material_lookdev_v1` | 0 | MaterialX 11控制及已有双读回工作；本轮不另定材质语义 |
| `lighting_camera_render_v1` | 0 | shutter、denoise_mix 定义存在；零端点及双输入producer未闭合，见端点/链路表 |
| `nuke_composite_v1` | 不适用 | 不在 Houdini native registry；现有 Nuke控制/typed输出路线单独看，不能由“无 Houdini blocker”推导全合成已完成 |
| `explosion_composite_v1` | 不适用 | 当前是meta组合；继承上述blocked，另有无正式绑定的控制，见组合表；不虚构第16个 native control_contract |

## 2. 建议整体审批方案

建议一次批准 **A01–A03、R01–R06、P01–P05、S01–S02、O01、G01–G03共20项的下表产品定义及共同规则**。用户可只列不同意的编号；main 应保存用户实际回复，逐项标记已批准/仍待决定，不能因同意“完整计划执行”或沉默而将本建议标为 confirmed。组合表建议作为单独的整体选择 B；端点/链路表是实施缺口，不重复索取已存在的产品定义。

共同规则也属于建议，未被现有实现事实自动批准：

1. 长度使用 **SU（当前场景长度单位）**，速度使用 SU/s，时间读取实际FPS及时间尺度。厂商 `m1` 等标签不是项目已经确认“1 SU=1米”的证据；没有明确尺度与质量基准不宣称SI换算。
2. 下表每项单独给出0含义；不统一把0当“关闭”或“自动”。所有非有符号控制的负值拒绝。数值须有限；非法值、缺基准、矛盾组合或预算超限明确拒绝，不自动夹紧、取整、换单位或改名。
3. 新随机控制采用固定任务seed、稳定实体ID及独立控制子seed。同值重开可复现、调一项不重抽另一项。新百分比只是**有界随机幅度**，不是统计方差；不改已有粒子life/velocity variance、Crowd path_variance或Geometry scale_variance的定义。
4. 明确列出基准、坐标空间、分布、时间尺度及受控阶段。缺少参考轴、目标、冲击事件、源几何、稳定ID或基准时保持具体缺项；不凭名称补默认事实，不覆盖艺术家已有无关字段。
5. 数字范围下表首先记录**当前源码验证区间**。范围“合理”须区分数学/类型条件、厂商同版本硬约束、产品上限和场景资源预算。当前100/1000/10000等上限多数没有物理合理性证明；建议本次不修改既有区间，特殊不能执行的端点仍明确拒绝并记录原因。后续若需改变范围、别名或端点合同，必须提出具体变更供审批。
6. 读回应验证控制的实际承载物：参数、属性、通道、拓扑或semantic program及其输入SHA，而非仅返回请求值。缓存/渲染授权、12帧/120秒与总磁盘预算保持原要求；产品审批不授权真实作业。

### 原生capture共同要求 C0

以下各表“仍缺capture”均继承 C0：H21.0.631和H22.0.429各自记录原始定义/帮助/SDK来源及hash，精确operator/机器参数、类型/tuple、菜单token、默认与表达式、硬/软range、disable/hide、输入输出角色与索引、内部可编辑性及消费关系。属性路线还须记录属性class/storage/tuple、坐标空间、稳定ID和实际下游消费规则。不能把帮助anchor、label、UI滑条或另一版本token当成本版机器接口。

静态定义能支持纯合同/底层API替身的事实边界；后续实例状态、几何/字段、保存重开和动态效果另行记录，须在真实宿主具体授权后执行。本次没有capture新宿主状态。厂商源字节当前缺失时，恢复的历史JSON只是可追溯静态摘录，不是本机重新验真的原始HDA。

## 3. 20项当前真实未定控制与推荐产品定义

每行均为 **PROPOSED**。“来源”使用第7节源码索引和真实行号；每组所列writer仍拒绝对应blocked，未给出可执行别名。

### A组：Pyro火焰与FLIP碰撞（3项）

| ID／控制／当前区间／来源 | 推荐单位和产品定义 | 零值／负值 | 作用范围与基准 | 范围合理性与仍缺的具体capture |
|---|---|---|---|---|
| A01 `flame_height`；float `-100..1000`；PY:61,77,85；writer:149 | **有符号火焰高度偏移，SU**。沿可信发射上轴，最终火焰高度包络上限为 `H_base + value`；`H_base`须是显式冻结的正基准。采用自有flame字段高度塑形，而非buoyancy/lifespan别名 | 0保留基准；负数降低上限。总上限≤0时受控火焰包络为空；正数提高允许高度，**不承诺凭空产生更高火焰** | 只控制自有flame字段的高度包络，源顶点投影为起点；写入作用域不包括density/temperature/vel及火光材质。后续仿真影响仍须验证 | 有符号区间适合“偏移”是产品选择；-100/1000无原生高度证明。缺两版flame字段生产/消费边界、体积坐标/源顶/上轴/`H_base`来源、可编辑field-mask节点和参数/端口、非正包络合法输出事实。无基准时拒绝 |
| A02 `collision_separation`；float `0..100`；FR:79；writer:305 | **碰撞场体素边长，SU**，不作碰撞间隙。正数绝对分辨率；0建议表示使用该版本/图实际的原生跟随默认，必须冻结并读回有效边长 | 0不关闭碰撞；负值拒绝；正数更小意味着更细场，成本需按实际域预算核对 | 自有FLIP碰撞相关SDF/velocity场；不改particle_separation、表面mesh、碰撞padding。正值与默认联动策略不同，需显式记录 | 正边长是数学必要；0跟随是待批产品选择；100为产品上限。w4已证明内部 `overridecollisionsep/collisionsep` 和DOP `coldivsize` 的存在，**未证明可编辑SOP公共入口**。缺两版合法editable边界、override/default表达式消费、场网格单位/变换、SDF/velocity输入及0→默认还原机制 |
| A03 `collision_passes`；integer `1..1000`；FR:80；writer:305 | **每个FLIP子步内完整碰撞投影循环次数**；一次循环含SDF采样与Move-to-Iso位置纠正，计数无量纲。solver子步数保持不变 | 0/负值均不在现有合同内；1是一次循环；不能四舍五入浮点数 | 仅自有FLIP粒子碰撞迭代支路；不作substeps或particle separation iterations别名 | 整数≥1为建议产品条件，1000未有稳定性/性能依据。缺两版Gas Repeat/Move-to-Iso真实operator、次数/停止字段、合法可编辑入口、端口及SDF/粒子位置数据绑定、循环一次究竟执行什么和是否每子步运行；不要从`partsepscale`推导 |

### R组：RBD物理碎片、冲击和速度（6项）

建议 `impact_spread` 与 `impulse_scale` 共享同一显式冲击事件：可信中心、命中piece ID、基准冲量向量 `J0` 与激活时刻。没有事件不制造一个冲击。已有 `activation_frame` 的 `(f-1,0),(f,1)` 常量active阶跃保持原定义。

| ID／控制／当前区间／来源 | 推荐单位和产品定义 | 零值／负值 | 作用范围与基准 | 范围合理性与仍缺的具体capture |
|---|---|---|---|---|
| R01 `fracture_scale`；float `.001..1000`；FR:83 | **目标碎片特征边长，SU**；闭合实体使用 `V^(1/3)` 作为结果读回尺度，创建有此目标尺度的断裂采样/切分图。是创作目标，不承诺所有实际碎片精确同大 | 0/负值拒绝；更小产生更细目标碎片；不得缩放整个物体冒充 | 自有断裂生成；保留输入轮廓和总体尺寸。开口曲面无体积基准时明确缺项，不能默改用玻璃专有参数 | 正长度有依据；.001/1000为产品界限、须结合源尺寸/碎片预算。缺两版通用切分/采样operator与种子/密度/端口消费、closed-volume及piece/name属性读回、材料模式和packing/constraints的对应关系。已有fracture HDA参数表不证明存在通用piecesize |
| R02 `fracture_variance`；float `0..100`；FR:98 | **目标尺度有界随机幅度百分比**；建议每稳定采样cell的目标尺度为 `L×q`，`q`均匀采样于 `[1/(1+p/100), 1+p/100]`。100得到 `[L/2,2L]`；不称实际碎片统计方差 | 0使用同一目标L；负值拒绝；L始终正 | 作用于R01的目标尺度/种子生成，固定seed；不改约束strength variance或玻璃裂纹条数 | 百分比/倒数对称上下界是产品选择；并无厂商通用方差接口依据。缺两版可变尺度采样/切分真实消费和合法图、稳定cell ID/seed、clipping后实际piece体积/拓扑读回；不能将`concrete_strengthvariance`冒充 |
| R03 `impact_spread`；float `0..1000`；FR:99 | **冲量分配半径，SU**；每piece使用实际质心距冲击中心的距离d；r>0时权重 `max(0,1-d/r)`，乘同一J0方向。不是玻璃裂纹专用Impact Spread | r=0只给明确命中的piece权重1，其余0；负值拒绝；缺命中ID拒绝，不选“最近的”猜命中 | 共享事件的一次径向衰减脉冲；不变更fracture拓扑、glue strength或Bullet world scale | ≥0及衰减函数为产品定义；1000无一般物理依据。缺可信impact中心/命中/质心身份、两版packed attribute到solver的可编辑冲量注入节点/字段、时刻和每piece消费。现有`glass_impactspread`只能支持玻璃专用事实 |
| R04 `piece_scale`；float `.001..1000`；FR:100 | **每个实际碎片以自身静止质心为pivot的均匀几何倍率**；1原样。缩放解包几何/pack变换并使碰撞形状与实际几何一致；密度保持，质量/惯性由真实新体积更新 | 0/负值拒绝；<1缩小，>1放大 | 断裂后、configure前；质心位置不变。重建依附piece的约束锚点与碰撞shape；不使用Exploded Scale或World Scale | 正倍率为数学条件；.001/1000是产品范围，放大后重叠/资源问题不能宣称安全。缺两版packed pivot/full transform/intrinsic、碰撞shape消费、density→mass/inertia规则、constraint锚点重建及可编辑节点事实 |
| R05 `velocity_variance`；float `0..1000`；FR:101 | **初始线速度每轴±随机幅度，SU/s**。每piece `v = v_base + a×(u_x,u_y,u_z)`，三轴独立均匀[-1,1]；角速度w保持原样。不作能量或统计方差 | 0保留基准v；负值拒绝 | 初始/激活事件的自有piece，固定piece ID和seed；一次设置，不在每帧累加；保留基准运动、drag和gravity | ≥0合理；1000为产品上限，时间步/源尺度需要预算。缺两版rbdconfigure实际v属性写入路径、class/tuple/storage和基准、Bullet读取/overwrite时机、stable name/seed及重开不重抽事实；粒子POP `var`不能作为RBD接口 |
| R06 `impulse_scale`；float `0..10000`；FR:103 | **可信基准冲量J0的无量纲倍率**；每piece `J = value×weight(R03)×J0`，如采用速度注入须有真实质量并验证 `Δv=J/m`；不把力或impact threshold当冲量 | 0无此受控脉冲，保留基准v及其他力；负值拒绝；1复用J0 | 共享冲击事件一次、在激活时刻消费；J0单位为实际质量单位×SU/s。缺J0/质量/事件时拒绝 | 倍率≥0是产品选择；10000无原生稳定性证据。缺两版合法瞬时冲量入口/属性及单位、mass读取、单次事件/子步积分/重新加载消费规则、事件身份/去重及实际读回；不得套Bullet World Scale |

### P组：粒子发射、尺寸、碰撞、拖尾和渲染（5项）

| ID／控制／当前区间／来源 | 推荐单位和产品定义 | 零值／负值 | 作用范围与基准 | 范围合理性与仍缺的具体capture |
|---|---|---|---|---|
| P01 `emission_variance`；float `0..100`；PG:144 | **恒定出生率的有界变化百分比**；每1场景秒一个固定seed样本u∈[-1,1]，`rate(t)=birth_rate×(1+p/100×u)`，按出生起点分桶；native对实际子步积分该rate，不逐子步重抽 | 0原birth_rate；100允许某秒接近0至2倍rate；birth_rate=0始终0；负值拒绝 | 只控制constantrate/已有持续发射，不改变寿命、速度、面积模式、impulse birth或seed | 百分比及1秒桶宽是待批产品选择；100保证非负期望rate。缺两版动态rate/expression实际消费、出生时间/FPS/timescale、亚帧采样/积分、随机seed API与准确门控；基准birth_rate上限乘随机倍率是否超native硬界需另核对 |
| P02 `size_variance`；float `0..100`；PG:148 | **基准实例pscale的有界随机幅度百分比**；`pscale=size×q`，q分布同R02；100范围是 `[size/2,2×size]`。保留独立size基准；不绑定物理碰撞半径 | 0精确恢复size；负值拒绝；所有合法倍率保持正 | 出生后按稳定particle ID固定，影响实例大小，不随帧抖动、不改collision_radius | 百分比与分布是产品选择，不是原生统计方差；新建议不改Geometry现有 `[1,1+value]` 合同。缺两版随机attrib/合法VEX、ID/seed、pscale实际class/类型及copytopoints消费、size→variation组合顺序/重开读回 |
| P03 `collision_radius`；float `0..1000`；PG:150 | **粒子物理碰撞半径，SU**；使用独立碰撞radius载体，不让实例pscale替它；对支持此radius约定的碰撞模式才有效 | 0建议为点粒子碰撞（半径0），不关闭collision detection；负值拒绝 | POP collision支路，单独的物理碰撞属性；实例size和基准v保持 | 半径≥0为产品定义；0能否原生表达仍缺事实，1000为产品上限。缺两版POP碰撞shape/模式、radius/pscale究竟如何消费、radius属性class/storage及独立render pscale方案、solver/object gates和SDF输入；Hair/Vellum半径证据不能迁用 |
| P04 `trail_length`；float `0..10000`；PG:151 | **历史时窗长度，场景帧**，允许小数；当前帧f用 `[f-L,f]` 的同ID轨迹连接。整帧位置加窗口起点线性插值，不把轨迹长度当空间距离 | 0仅输出原粒子/实例，不生成退化线；负值拒绝；小数不取整 | 自有trail几何支路，保留模拟v；只用真实登记/可追溯的历史样本。出生晚于窗口起点从出生样本起，不造出生前轨迹 | 非负时窗合理；10000无法证明预算可承担。缺两版Trail/历史读取operator与端口、ID关联/断轨/死亡粒子政策、时间采样/插值和输出curve类型、所需求解前史/缓存登记。建议死亡粒子不继续输出；历史缺失或授权不足明确拒绝，不能合成样本或悄悄截L |
| P05 `motion_blur_scale`；float `0..100`；PG:152 | **渲染速度倍率**；只形成 `render_v=value×simulation_v` 并由实际渲染器明确绑定。shutter、模拟v和粒子位置不改 | 0无该velocity blur贡献；1原样；负值拒绝。0不承诺关闭来自deformation/time samples的其他模糊 | 粒子到USD/Karma的velocity blur路线；纯deformation blur模式不能套此控制 | 无量纲≥0是产品选择；100为上限。缺两版SOP Import速度attribute→USD velocities映射、FPS/时间尺度、renderer velocity blur gates/最终绑定字段、实例/点表示支持及motion-vector读回；不是solver速度或shutter别名 |

### S组：Swarm噪声（2项）

| ID／控制／当前区间／来源 | 推荐单位和产品定义 | 零值／负值 | 作用范围与基准 | 范围合理性与仍缺的具体capture |
|---|---|---|---|---|
| S01 `target_noise`；float `0..100`；PG:162 | **目标位置扰动半径，SU**；以实际goal_base为中心，在半径a的3D球内均匀取样；每1场景秒更新并线性连接相邻样本，整个swarm共享同一移动goal | 0精确goal_base；负值拒绝 | 仅seek目标位置，不动粒子源/初始v、不替换goal_attraction或添加力；固定seed、基准goal及时间原点 | 球半径和共享目标/1秒时间尺度是产品选择；100为上限。缺两版合法goal动画/噪声图、seed/time和向量属性类型、goal输入/参照空间/表达式消费、禁用已有驱动时的保护及重开；现有seek门控只证明seek，不证明noise图 |
| S02 `noise_strength`；float `0..1000`；PG:163 | **自有POP噪声力的原生幅度标量**，采用与当前粒子force_noise一致的“原生noise amplitude、Ignore Mass”解释；不宣称SI加速度。保留已有频率/seed/roughness，缺这些上下文则先冻结明确基准 | 0该新noise力为0；负值拒绝 | 给swarm增加独立且可编辑的noise-force支路；flock、seek及各自权重不改，不把不存在的seek字段当噪声 | 非负amp是产品选择；1000及质量换算未获依据。缺两版Swarm合法POP Force支路/连线、amp/gates/时间噪声上下文与solver externalforce真实消费。粒子已实现force_noise是复用设计依据，不是Swarm图已经存在的证明 |

### O/G组：海洋角宽和程序几何（4项）

| ID／控制／当前区间／来源 | 推荐单位和产品定义 | 零值／负值 | 作用范围与基准 | 范围合理性与仍缺的具体capture |
|---|---|---|---|---|
| O01 `directional_spread`；float `0..360`；PG:174 | **以实际wind_direction为中心的完整方向支撑角宽，度**；支撑区间内方向权重均匀，并对既有径向谱归一化保持总谱能量。不是半角或标准差 | 0理想单方向；360全方向均匀；负值拒绝。0是精确端点目标，不能用未经批准epsilon伪装 | 仅方向分布；保留径向谱、波高基准、seed和谱型。可证精确转换才用native dirbias；否则需合法自有方向谱图 | 0..360具有几何意义，选择均匀支撑是产品决定。两版已捕获dirbias float和滑条0..10，但缺实际谱型公式/方向权重/端点可表示性、两版参数→谱数据消费与可编辑角谱处理端口。不得使用线性 `dirbias=(360-width)/36`、默换谱型或把滑条当硬界。精确端点无法表达时仍blocked |
| G01 `scatter_variance`；float `0..1000`；PG:186 | **已scatter点在源表面的最大位置扰动半径，SU**；局部切平面均匀圆盘取样，再投影到同一源连通表面；不是点数方差、seed或relax次数 | 0保留原点；负值拒绝 | 保留既有count/density模式、数量、seed及稳定point ID；只改P，边缘投影后的分布不冒称严格均匀 | 长度与位置解释是产品选择；1000要看源尺寸/投影成本。缺两版稳定point ID、切平面basis/表面法线、合法投影/最近点API和连接、越边/孔洞/多表面选择事实；同表面投影不唯一时拒绝，不跨面猜测。Scatter2 SDK只证明count/density等，不证明statistical variance |
| G02 `rotation_variance`；float `0..360`；PG:188 | **绕可信局部Z轴的完整随机角宽，度**；每实例独立 `δ∈[-value/2,+value/2]`，在源实例变换后沿该局部轴叠加；360覆盖全圆 | 0保留基准姿态；负值拒绝；不把360解释为±360 | 只加实例orient扰动，不改已有全局rotation的X/Y/Z基准、scale或点P；固定point ID/seed | 全宽≤360有角度依据，轴/分布/叠加顺序为产品选择。缺两版orient quaternion属性class/tuple、角度单位/变换顺序、copytopoints消费及existing orient与transform组合图；不以源xform.r全部三轴重写代替 |
| G03 `deformation`；float `0..100`；PG:189 | **实例源静止空间正弦法向位移幅度，SU**；建议 `P'=P+d×sin(2π×x/Lx)×N_base`，x相对冻结源bbox起点、Lx为源局部X跨度、相位0。先变形、再现有scale/rotation | 0恢复上游源；负值拒绝；Lx=0或N不存在时拒绝，不补任意波长 | 自有instance_source几何在copy之前变形；保留拓扑/实例点位置、count、seed和pscale。局部幅度会随已有instance scale共同放大 | 正弦类型/固定波长基准及幅度范围是产品选择；100不能保证不自交。缺两版原生wrangle/VEX或等价deformer参数/端口、P/N/bbox实际属性与单位、局部坐标/pack展开、原样零值恢复和重开读回。已有wrangle机器接口只能作部分依据 |

## 4. 语义已定但端点/原生路线仍缺：不重新询问定义

| 控制／源码 | 当前已存在定义与实际阻断 | 推荐处理／还缺的事实 |
|---|---|---|
| Pyro fire `burn_rate`；PY `control_contract():112`、`control_write_plan():159` | rate是归一化flame单位/s；正值 `lifespan=1/rate`；0明确报 `ZERO_FLAME_DEPLETION_NATIVE_TARGET_NOT_CAPTURED` | 保持“0耗尽率”含义；补两版真实不耗尽开关/字段计算及readback。不能给0塞很大lifespan冒充无限，也不能修改范围规避缺口 |
| Lighting `shutter`；RD `control_contract():94`、writer:143 | 时长是UsdTimeCode，centered open/close=`±duration/2`；0报 `SHUTTER_ZERO_DURATION_UNSUPPORTED` | 补0时长/无模糊的本版renderer与camera表达机制；当前单独motion_blur bool已存在，但是否采用关闭它需具体跨控制策略审批。不是重新决定秒还是帧 |
| Lighting/Smoke/Nuke `denoise_mix`；RD:97,150，PY:42，Nuke mapping:2780 | 连续混合定义已存在：`raw*(1-w)+denoised*w`，0..1。Lighting原生只处理0/1；中间值报 `EXTERNAL_DENOISE_BLEND_REQUIRED` | 缺两个可信独立producer、raw/denoised对应布局/帧/颜色/预乘/operation、OIDN/OptiX合法原生接口与最终Nuke混合登记。Nuke `Denoise2` 类名和mix候选不是约定算法和双输入产物链已成立的证明 |
| Hair `collision_radius`；CH:62 | 已定义native pscale radius、SU并要求实际convention/geometry上下文 | 缺context保持缺项；不因粒子P03同名而复用Hair事实，不重新定义Hair radius |
| Softbody/grains专属控制；VL `control_contract():94` | softbody中grain source控制是 `branch_required`；实际grains分支有diameter等明确含义 | 不把分支限制统计成2个未定控制；两分支仍分别验收 |
| RBD `activation_frame`；FR:102,281 | 整数 `-100000..100000` 场景帧，active常量阶跃，overwritefromsop gates及完整channel上下文 | 软件时态、实际collector/writer、持久化/新实例reopen等是实施与证据问题；不以solver.startframe别名替换，不列入20项审批 |

此表均未运行或复验。当前返回具体拒绝不等于全域完成，也不意味着允许长期UNSUPPORTED后宣布M1成立。

## 5. 第16域组合：当前路由事实与整体建议B

`native_domain_registry.DOMAIN_IDS`有12个基础域；Material/Lighting由render overlay另外处理。Explosion没有自己的versioned native合同或semantic program。当前 `EXPLOSION_BRANCH_CONTROL_MAP` 是**代码中的路由事实**，不是用户已经批准这些名字所暗示的能量/尺寸语义。不要用旧Houdini host泛型别名列表执行整个explosion模板代替正式分域图。

| 当前组合控制／现有路由 | 是否新增未定定义 | 建议B：产品呈现、范围/零值及缺capture |
|---|---|---|
| `fire_energy→fire.burn_rate`；`fire_scale→fire.fuel_rate`；`smoke_dissipation→smoke.dissipation`；`smoke_scale→smoke.density_scale`；`spark_rate→particles.birth_rate` | 核心单位/控制已有定义；组合名称容易误导 | 建议采用分域合同，并在UI明确“火焰耗尽率/源flame输入率/烟消散/密度输入率/粒子每秒出生率”，不宣称joule或整体几何scale；保留现名与现范围，不自建新别名。0沿被路由控制含义与现有端点缺口；还需当前任务分域绑定与产物依赖读回 |
| `debris_scale→rbd.fracture_scale`；组合 `.001..1000` | 继承R01，不新增独立参数事实 | 建议采用R01目标碎片长度，0/负值拒绝；不是全模型缩放。缺R01capture和meta→实际rbd branch冻结绑定 |
| `debris_energy→rbd.velocity_variance`；组合 `0..1000` | 继承R05，但“能量”名尚需明确接受解释 | 建议采用R05每轴±随机初始速度幅度、SU/s，0无新增随机速度；不当作Joule或冲量。若用户坚持物理能量，则需重新提具体质量/速度转换方案，不能维持现路由却声称energy |
| `shockwave_scale→shockwave.scale`；planner shockwave分支是procedural_geometry；组合 `.001..10000` | 几何scale倍率已定义；**实际shockwave形状和动画缺绑定** | 建议源采用自有球壳，中心来自可信源配置，半径时间函数须作为显式冻结输入；scale为球壳源的均匀倍率，1原样、0/负值拒绝。缺球壳真实源图、中心/transform和半径时间函数消费、meta branch→该源的绑定；不能用任意grid/sphere实例宣称冲击波成立。范围为产品选择；当前注释称unproven不能作PASS |
| `shockwave_thickness`；runtime float `0..1000`；不在PG native合同，也不在branch map | **额外未绑定产品项**，不计入20个native blocked | 建议为上述球壳在scale前的完整径向厚度、SU，以基准半径两侧各厚度/2构成；0为未增厚表面，负值或厚度大到使内半径≤0时明确拒绝。现有均匀scale同时乘半径/厚度。缺合法shell/thickness operator、两版端口/读取和meta路由；不能映射到solver collision_thickness |
| `debris_amount`；runtime integer `0..1000000`；map指向 `rbd.debris_amount`，FR合同无此项 | **额外未绑定产品项**，不计入20个native blocked | 建议为“随主RBD碎片运动的次级几何屑实例总数”：按静止父片表面积采样、固定ID/seed和局部锚点，跟随已登记父片变换，不新增独立物理解算/约束或碰撞。0不生成次级屑，负值/小数拒绝；总数与R01主片尺度独立且计入预算。缺合法生成/采样/稳定ID图、exact count和父片变换消费、实例源尺寸基准/meta绑定；不能由同名路由推断FR已有接口 |
| `comp_contrast→Nuke composite_patch`；`0..10` | 已有ColorCorrect contrast候选，不新增能量/物理尺度定义 | 建议沿Nuke实际contrast合同；不改范围/别名。仍需Nuke17.0v1机器knob、颜色/通道/预乘与真实双输入产物消费证据，不能由ColorCorrect类名证明完整组合已成立 |

B组建议不包含任何默改路由：main应先把继承R01/R05与额外shockwave/debris产品定义一起供审批。`debris_amount`的“跟随父片的次级几何屑”和shockwave球壳是**新建议，不是从现代码推断的事实**。若用户需要独立弹道/碰撞的次级debris或其他冲击波形状，应调整B方案再审批；未给定球壳半径时间函数、源尺寸、中心等具体场景输入时保持缺项，不猜创作数值。本次没有增加新的native字段或批准标签。

## 6. 已用静态事实、没有用作事实的历史材料

| 只读来源 | 本次可支持的事实 | 不能据此宣称的内容 |
|---|---|---|
| `docs/native-basis/w4-glue-collision-static.json` | 两版DOP flipobject `overridecollisionsep/collisionsep`；flipconfigureobject `coldivsize`；SOP FLIP内部consumer记录；碰撞字段分辨率而非间隙；文档列出的粒子分离迭代不建立collision passes映射 | 可写SOP公共接口、解锁授权、Gas Repeat/Move-to-Iso字段与端口、0的产品含义 |
| `docs/native-basis/hda-interface-capture.json`；`native-boundary-metadata-supplement.json` | 两版Ocean `dirbias` float、默认2、滑条0..10；RBD glass专用Impact Spread与strength variance；POP Source lifevar/var和POP碰撞模式机器字段 | angular width→bias公式；通用fracture尺度/方差；独立粒子物理radius；宿主实例写入/cook |
| `docs/native-basis/scatter2-sdk-help-static.json` | 两版Scatter2机器键/enum及count/density门控的静态来源 | 位置/统计variance、运行时ParmTemplate/default/visibility、实际投影效果 |
| `docs/native-basis/w2-wrangle-convolve-static.json` | 两版wrangle/convolve机器接口摘录，可供合法semantic program选型 | 本表20项VEX数学/字段消费已实现或有效；实际几何/体积效果 |
| `docs/native-basis/domain-native-documentation.json` | 15个Houdini域的既有厂商帮助来源与未闭合声明；两版各自版本化 | 当前软件PASS、全部端口/控制语义或第16域meta原生输出成立 |
| `outputs/m1-takeover/flip-rbd-domains/source-refs.json` | 已恢复的历史source-ref字节可只读追溯 | 历史运行结果是当前build或历史decision得到用户批准 |

历史 `remaining-nine-decisions.md`、`remaining-rbd-six-decisions.json`、`current-control-blockers-20261003.json` 的定位由REMAINING给出。本次本仓库未发现这三份决策原文；恢复脚本记载的 `C:/Users/32200/Desktop/Bridge-完整项目移交-20261004.zip` 本次 `Test-Path=False`，已做有限的ZIP路径定位，没有读取到该包。因此**没有把历史decision内容/状态当作已核对事实**，不解压/覆盖任何历史目录。

现有 `recovered-static-evidence.json` 记录原ZIP SHA为 `7f3478dcaa090d9c15a4df5ce7efe68353cb2d14ecbdb4d0b98a5f944b40897b`；这是已有记录值，本次未重新计算不存在的ZIP。缺旧decision不影响当前20项blocked的源码清单；如后续提供原ZIP，只需核对可能已批准的具体定义及原文，不重复实现/执行。

## 7. 源码绑定与函数引用

读取时Git HEAD：`d48fa10d32b95ce322e22b7b1ae39f947f3b1126`。工作区有保留的未提交补丁；HEAD不能代表实际读取字节，以下**SHA-256绑定本次工作区内容**。对同一HEAD的后续修改，main须核对文件SHA和真实行号再使用本结论；本报告不冻结其他实现者。

路径前缀 `H = packages/houdini-bridge/src/houdini_bridge/`；表中行号为本次真实一基行号。第3节的 `PY/FR/PG` 是下表文件索引，不是新产品别名。

| 索引／文件 | 工作区 SHA-256 | 函数／当前行号 |
|---|---|---|
| PY `H/native_pyro_domains.py` | `db869128564fdcfed9b0b584df45773028eeb3b2d64e2182a66926a6161d4c9b` | `_FIRE`:51；`_BLOCKERS`:76；`control_contract`:85；`control_write_plan`:149；`control_readback`:388 |
| FR `H/native_flip_rbd_domains.py` | `67da3db4a4fb97bec3f31131f535366ace3cf8012262493a4d0d6ec10efca956` | `control_contract`:56；`_activation_write_plan`:281；`control_write_plan`:305；`control_readback`:461 |
| PG `H/native_particle_ocean_geometry_domains.py` | `1ec2053bd44f3475a9a1423be938069d147f2d0780229b92c10c3133fda55438` | `control_contract`:135；`node_requirements`:206；`control_write_plan`:352；`control_readback`:490 |
| CH `H/native_crowd_hair_domains.py` | `f21a161a60b6cb215b73791ed4bd9c0949a29e72f96c14ffe6dab8400a3d464d` | `control_contract`:52；`control_write_plan`:161 |
| VL `H/native_vellum_domains.py` | `1a2c99e1c8d8c576d15867e4f8c3bc46d5a5a6e1a56c5ca9ff80e1eab044df89` | `control_contract`:49；`control_write_plan`:142；`control_readback`:300 |
| RD `H/native_render_domains.py` | `6683a625929b39671a89c075b02f6a8ae7e57a8baa6d603cca31fded44213262` | `control_contract`:84；`control_write_plan`:126；`control_readback`:185 |
| `H/native_domain_registry.py` | `5cd62e5bcdd30e7dae85933f3d95ab15a96bf4c91b62b9017effc34cd0d4f035` | `DOMAIN_IDS`:16；`module_for`:21；`branches`:35 |
| `H/native_cloth_wrinkle_program.py` | `bc93ed4b39b39e4729393d588623e58ff641775ae876d2f39283ba142edc2be6` | `control_write_plan`:361；`validate_geometry_readback`:397 |
| `H/native_ocean_mask_program.py` | `10891a89c790d8705d65be732428925418597ed01984f9c6c6c2340851af836a` | `control_write_plan`:459；`validate_geometry_readback`:518 |
| `H/native_crowd_route_contract.py` | `2ec0cd9c40b8938d11678c56c95ef0f892da626fb6be750889d29ebaa3d52bde` | `readback_plan`:382；`validate_readback`:390 |
| `H/native_crowd_transition_contract.py` | `ba4a0f637094d2c6c76b5dd3715083b31b57549f8685fc4802877088dd0806bb` | `readback_plan`:477；`validate_readback`:485 |
| `H/domain_packs.py` | `fa8fb28cd42a4fd64ebed32c5fdf5a65b62632ed65a223d6a913d40296d374f7` | `EffectDomainPack.to_dict`:187；Explosion基础控制:462；runtime增量:548 |
| `packages/vfx-pipeline/src/vfx_pipeline/service.py` | `71a198a6b44f25a68d125e763ee8a2f4c812fdb2869271c3017490b558971d28` | `EXPLOSION_BRANCH_CONTROL_MAP`:81；`_select_explosion_candidate`:999；`_run_selected_houdini_branch`:1971 |
| `packages/vfx-pipeline/src/vfx_pipeline/planner.py` | `59ba56fc7ec810caf1d1080680e6c25cbf94d4e9b5d10206dd95a3ad7317da1b` | `PipelinePlanner._explosion_branches`:174 |
| `packages/dcc-task-runtime/src/dcc_task_runtime/domains.py` | `2916642848a05924a4418e47dc96d6e92be37790b5c4ea6580ce89369babfbda` | Explosion controls:402；`shockwave_thickness`:411；`debris_amount`:412 |
| `plugins/nuke/nuke_bridge_addon.py` | `821cacc40fc1c280a20a04542d2ec6739f9107442315799a626b04753749ae83` | `_COMPOSITE_CONTROL_MAPPING`:2776；`_validated_composite_controls`:2794；Denoise候选:3216 |
| `tools/readiness_evidence.py` | `2ccd4ebd36351bd296d13c21ff7f9c655ed683d88f78614e3b70f14f0bec85fd` | `DOMAINS`:14（全16域枚举） |

### 交接与静态摘录SHA-256

| 文件 | 本次读取字节 SHA-256 |
|---|---|
| `README.md` | `25728ab5dd1abfc4ca10969a2bdfa8c7540afd0e811e5db57fff28f73380de64` |
| `handover/STATUS.md` | `8234d911f950698cfa5cf9275428681192e26cef6250415fd85599b46bc9e3d9` |
| `handover/REMAINING.md` | `e22d6ad535c1036d6970500e5c508962f307a5845fec766b3481220cf7b8fe2b` |
| `handover/NEXT_AGENT.md` | `f129fdb6349e602353796c5d617334ab3d065e832090d54a73b9767d6c95a283` |
| `docs/native-basis/domain-native-documentation.json` | `43ba32c0d518d94b0dbf57e6f8bc395c2c8f38718a51b26bb969669ce5d45d8c` |
| `docs/native-basis/hda-interface-capture.json` | `a0e96e0d1ce57f91c53b2f00c1a0993df60f091f8b3b67fa267070340cac7dac` |
| `docs/native-basis/native-boundary-metadata-supplement.json` | `416d63f1f6c4d9183fbd8dfe83adbb8dcfaa6fc6965fd698318b42fca4e3ce3f` |
| `docs/native-basis/w4-glue-collision-static.json` | `68faaeb702b4e23a24df2ca7ca38b620cea71c87eaf2e041cc4f3852e8da5779` |
| `docs/native-basis/scatter2-sdk-help-static.json` | `08a1ede5c3535184b974505d81ca2f644172d68ba6442a20bcac399b128aec52` |
| `docs/native-basis/w2-wrangle-convolve-static.json` | `5a10fa158ae7e153cbc62054da2895fab32fc8a1a1c527d42d80a9853b05a3f6` |
| `outputs/m1-takeover/flip-rbd-domains/source-refs.json` | `81d95c43af9bb7ad31f1f7b38b0af958db351c291c589c61a635a2822710e064` |

## 8. main的接收与后续顺序

本次交付只到建议文档。软件实现、安装、真实宿主、模型路线、视觉和生产验收均未在此执行或建立PASS。除本文件外不修改README、handover、源码、测试、生产、发布副本或历史证据。

建议main给用户的整体审批文字：

> 建议采用本文件第2–3节的20项产品定义与共同规则；保留当前控制名和数值区间，按表中的0/负值含义处理，原生接口缺证据时保持具体阻断。请审批此整体方案，或列出需要调整的编号。另请单独选择是否接受第5节组合建议B（球壳冲击波、随父片运动的次级几何屑，以及组合控制继承分域定义）。实际场景基准输入仍须明确提供。

用户批准后，main应先记录具体批准版本/编号/条款，按每行capture清单补同版本事实，再以现有核心合同、原生program、writer/collector和正式反馈事务最小实现。复用现有测试，不从本提案生成“期望结果即成功”的替身；有源码变化/新风险才执行受影响验证。当前受控writer的blocked代码须随真正闭合的实现逐项解除，不能只删除拒绝或把proposal状态改成confirmed。
