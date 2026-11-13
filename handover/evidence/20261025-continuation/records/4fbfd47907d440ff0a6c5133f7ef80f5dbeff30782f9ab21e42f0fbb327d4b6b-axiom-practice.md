# Axiom Solver 实战（Fire_shot2 / Pyro 对齐）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 接线：input 0 = VDBs（源/碰撞缓存），input 1 = Source Shapes；先看完整节点树（源→碰撞→cache→merge→solver→bake）再改参；只改参数时禁止 force cook（Axiom cook 卡 bridge）
> - Pyro→Axiom 映射：divsize→divisionSize(0.02，勿盲目回 0.01)、timescale→timeScale、wind_strength→wind、buoyancylift→buoyancy(0.27)、dissipation→densityDissipation；数值相等≠单位相同，最终以视觉微调
> - 源场命名大小写敏感：Pyro 的 burn 必须改名 fuel；Mask 不是仿真场，sourceField*Scale 才是源倍率
> - output*Scale 是降分辨率菜单(0=1/1)，不是场增益；增益靠 sourceField*Scale / emit*
> - 纯温度火默认不激活（默认靠 density 扩域）：Sparse → Activation Fields 认 temperature/fuel
> - 视口没有 Pyro 式火色，直接看 solver 只有灰烟：设 outputDensityVisualization=Invisible，或下游 temperature→flame + volumevisualization；至少 start+5~10 帧再比形态
> - 调参阶段 profileFile=""（防串台）；按钮类 string parm 设 "" 不要 set(0)
> - 改参后必须 Reset → 从 startFrame 重算，旧缓存不会自己变
> - OOM 处置：divisionSize≥0.02 + voxelLimitBehavior=0(Maintain) + voxels≈48M + collision voxelsize≥0.1 + Device Only + Bit16
> - voxelLimitBehavior 菜单：0=Maintain(48M 硬限不扩容)、1=Auto Increase(用到 95% 自动+20% 滚雪球到 OOM)；爆显存先查这个
> - 笔记本 8GB 安全区：divisionSize≥0.02 + Maintain + 32M 上限 + 16-bit(省 36%) + emitPressure≤0.5(开燃料时) + 限 bounds
> - disturbance1BlockSize 默认表达式 ch("divisionSize")*2 尺度过碎：先 deleteAllKeyframes() 再写绝对世界单位
> - 「axiom 没烟」先查下游：filecache loadfromdisk=1 且磁盘无文件会伪装成 solver 问题；updateMode.Manual 下 geometry() 常 0 prims，先切 AutoUpdate；License not found ≠ OOM，先修许可

面向 `Sop/axiom_solver::4.0`（Houdini 21）。官方手册见同目录 [axiom-reference.md](axiom-reference.md)。  
本镜头经验：`Fire_shot2_Fire_Axiom`，目标让 Axiom solver 接近 `pyrosolver1` / `/obj/fire/file1`。
⚠️ 工程中**没有** `axiom_solver1` 节点（`set_axiom1_parms.py` 的目标节点未保存进 hip）；
实际有 `axiom_solver_v1~v10` 十个旁路实验节点，主链是 `pyrobakevolume1`。

## 手册路径

| 文件 | 说明 |
|---|---|
| `references/axiom-reference.md`（本 skill） | 整理版（推荐） |
| `C:/Users/<USERNAME>/.zcode/workspace/default/axiom-reference.md` | 副本 |
| `C:/Users/<USERNAME>/.zcode/workspace/default/axiom4_docs.md` | 原始抓取 |
| `C:/Users/<USERNAME>/.zcode/workspace/default/axiom_docs.md` | 更全原始抓取 |
| 源站 | https://theoryaccelerated.notion.site/axiom-4 |

### 手册与本镜头直接相关的结论

- **激活**：默认靠 **density** 扩域；纯温度火需 Sparse → Activation Fields 认 temperature/fuel。
- **Sourcing**：VDB 名大小写敏感；Mask 不是仿真场；Scale 才是源倍率。
- **Combustion**：Burn 耗 fuel；产烟主要看 `emitDensity`。
- **Output Scale**：是 **降分辨率菜单**（1/1、1/2…），不是场增益。
- **Visualizer**：Smoke / Rainbow / Isosurface / Invisible；**没有** Pyro flame 火色。
- **Containment**：优先 Source Shape collision/sink **invert** 做 max bounds；不要乱 merge 反向 box 进 SDF。
- **Margins**：marginIterations=0 锁死初始域；velocity margin 给高速方向加 padding。

## 硬约束

- **先完整看完相关节点树再判断/改参**（源 → 碰撞 → cache/timeshift → merge → solver → bake/OUT）。禁止只看 `axiom_solver*`。尤其：`filecache.loadfromdisk` 与磁盘是否真有文件、`timeshift` 锁定帧、Axiom **口0=VDBs、口1=Source Shapes**。
- 用户说「只改 axiom1」时：**禁止**改 `sim_fire` / `collision_cache` / `pyrobakevolume` / container 链（除非明确允许）。
- 先对齐**本镜头参考**（`pyrosolver1` + `file1`），**不要盲目整表复制 `18_simple_fire`**。
  注意：工程中无 `axiom_solver1`/`axiom_solver2`，只有 v1~v10 旁路实验节点。
- 用户说「只改参数」时：只用 `node_set_parms` / set，**禁止 force cook**（Axiom cook 会卡 bridge）。

## Pyro ↔ Axiom 语义对照

目标：`pyrosolver1` + `/obj/fire/file1`（density/temperature/**flame**/vel）。
注意：`file1` 在 SHOT_2 中指向 SHOT_1 的 sim_fire 缓存路径（跨 shot 引用）。

| Pyro | 含义 | Axiom | 脚本值(set_axiom1_parms.py) | 工程 v7 实际 | 依据 |
|---|---|---|---|---|---|
| `divsize=0.01` | 体素 | `divisionSize` | 0.02 | **0.03** | Division size / Memory |
| `timescale=1.2` | 时间 | `timeScale` | 1.2 | **2.0** | Getting Started |
| `wind_strength=0.75` | 目标风速 | `wind` | 0.75 +X | **1.99** +X | target speed |
| `buoyancylift=0.27` | 浮力 | `buoyancy` | 0.3 | **0.27** | 单位未必 1:1 |
| `dissipation=0.02` | 密度耗散 | `densityDissipation` | 0.07 | **0.25** | percent + timescale |
| shredding on flame | 火边碎裂 | `disturbance1` | 0.45 / block 0.08 | 0.45 / block **0.108** | 无 shredding |
| `doflamedensity=0` | 火不产烟 | `emitDensity` | **0** | **0** | Combustion Emission |
| 源 `burn` | 燃烧场 | 必须叫 `fuel` | `source_burn_to_fuel` | 同 | 命名大小写敏感 |
| 视口 flame | 火色 | 无内建 Fire | `axiom1_fire_viz` / bake | 同 | Visualizer |

数值相等 ≠ 单位相同。最终以 `file1` 视觉微调。

## 必查陷阱

### profileFile 串台

- 勿指其它 solver 的 profile；调参阶段 `profileFile=""`。
- 按钮类 string parm 设 `""`，不要 `set(0)`。

### 输出 / Mask

- `output*Scale` = 分辨率菜单（0=1/1），不是增益；增益靠 `sourceField*Scale` / emit*。
- Temperature mask 推荐 `temperature` 或空；勿设成掐死自己的场名。

### 下游 filecache 空

`sim_fire` / `collision_cache` 若 `loadfromdisk=1` 且磁盘无文件 → 看起来像「axiom 没烟」。只改 axiom1 时说明状态，勿擅自改 cache。

### 灰烟 vs 火色

- 直接 display `axiom_solver` = density 灰烟。
- 应对：`outputDensityVisualization=Invisible`，或下游 `temperature→flame` + `volumevisualization`，或看 `axiom1_fire_viz`。
- 至少 start+5~10 帧再比形态。

### disturbance BlockSize 表达式

默认常有 `ch("divisionSize")*2`，尺度过碎。对齐 Pyro 前 `deleteAllKeyframes()` 再写绝对世界单位。勿 `setExpression('')` 后忘记 `set` 数值。

## 推荐调参流程

1. 读同镜头 pyro +（若有）已调好的 axiom，列映射表。
2. 一次改完核心 parms；清空 profile。
3. 用户允许 cook 时：startFrame 验 errors/场名；再 start+5~10 看形态。
4. 改参后必须 **Reset → 从 startFrame 重算**（旧缓存仍是旧样子）。

## Fire_shot2 set_axiom1_parms.py 脚本参数（4070 Laptop 8GB）

> ⚠️ **重要**：以下参数来自 `SHOT_2/set_axiom1_parms.py`（8月4日脚本），目标是 `/obj/fire/axiom_solver1`，
> 但该节点在 .002 hip 中**不存在**（hip 里只有 axiom_solver_v1~v10 十个旁路实验节点）。
> 脚本参数代表**当时的设计意图**，不代表工程实际值。
>
> SHOT_2 的 .002 hip 保存于 **8月8日**；8月9日方块烟修复后未再保存 hip。
> 工程实际值（axiom_solver_v7 / V3_v9）与脚本差异很大，详见 usd-render-practice.md §8。

```
# 减烟 / 火感
emitDensity=0
sourceFieldDensityScale=0.25
densityDissipation=0.07
sourceFieldTemperatureScale=1.15
buoyancy=0.3
enableWind=1  wind=0.75  windDirection=(1,0,0)
fuelBurn=0.4
disturbance1=0.45  disturbance1BlockSize=0.08  enableDisturbance2/3=0
turbulence1=0.6  turbulence1SwirlSize=0.35

# 尺度 / 时间
startFrame=950
timeScale=1.2
divisionSize=0.02          # 勿盲目回 0.01
# subSteps 未在脚本中设置（用默认值；工程 v7/V3_v9 实际为 3）

# 显存（手册：8GB≈91M voxels；1GB≈13M @32bit）
voxels=48000000
voxelLimitBehavior=Maintain(0)
maxVelocityMargin=3
leafSize=32
memoryAllocation=Device Only(0)
memoryBuffer=1024
fieldPrecision=Bit16(0)

# 碰撞（脚本值；工程实际 collision_sdf voxelsize=0.03）
/obj/fire/collision_sdf.voxelsize=0.1  # 脚本设为 0.1，但 hip 实际已改为 0.03

# 视口：axiom1_fire_viz；profileFile=""
```

配套：`C:/Users/<USERNAME>/Documents/WORK/202607_Fire/03_HProject/SHOT_2/set_axiom1_parms.py`

接线：`source(fuel/density/temperature) + OUT_collision` → `merge_axiom_sources` → axiom **input 0**；input 1 空。

## CUDA OOM / 体素数暴涨

典型：`cudaErrorMemoryAllocation` + voxels ~493M + Shared Memory 十几 GB。

根因：

1. `divisionSize=0.01` × 大碰撞/BOUNDS 域  
2. `voxelLimitBehavior=Auto Increase`  
3. collision VDB `voxelsize=0.01` + fillinterior 进 merge  
4. Pyro 同 divsize 能跑因 sparse+clamp；Axiom 不能照抄  

处置：`divisionSize→0.02(+)`；Maintain + voxels≈48M；collision voxelsize 建议≥0.1（**工程实际已改到 0.03**）；Device Only；清 Enable / Reset。

⚠️ 注意：工程 v7/V3_v9 实际 `voxelLimitBehavior=1`（Auto Increase），未遵从脚本设的 Maintain(0)；
如果遇到 OOM，确认此参数是否被改回 Auto Increase。

**voxelLimitBehavior 菜单（已从 HDA 菜单定义证实）**：`0 = Maintain Limit`（48M 硬限制，不自动扩容）；`1 = Auto Increase`（用到 95% 自动 +20%，可滚雪球到 OOM）。

**两种 OOM 机理（Fire_shot2 实例，v4 与 v9 都爆显存但原因不同）**：
- **v4 = 静态需求超限**：0.01 细体素（同空间需 ~5.8× 体素 ≈280M）+ leafSize 8（叶节点 ×8，手册只推荐 16/32）+ emitDensity 4 + 耗散 0.02 烟不散 -> 需求远超 48M 硬限 -> 崩溃/域截断。
- **v9 = 动态失控增长**：simulationFuel=1 燃烧产压（emitPressure=1）-> 域膨胀 -> 体素涨 -> Auto Increase 自动 +20% 滚雪球（48M->57M->69M…）-> 8GB 吃光。手册 Combustion Emission 原话警告过 pressure 过大会 expand too fast。

**笔记本 8GB 安全区**：divisionSize≥0.02 + voxelLimitBehavior=0(Maintain) + 32M 上限 + 16-bit 精度（省 36%）+ emitPressure≤0.5（开燃料时）+ 限 bounds。

## Bridge / Manual / License

- `updateMode.Manual` → `geometry()` 常 0 prims；先 `AutoUpdate`。  
- Axiom cook 易超时卡 bridge → 只改参时勿 cook。  
- `License was not found`（solverCore）≠ OOM；先修许可。

## 教程目录

`C:/Users/<USERNAME>/Documents/TEST/axiom/`（含 `18_simple_fire`）。
`.hiplc`→`.hip` 完美转换（去 LC 头）见 [hip-convert.md](hip-convert.md)，用 `scripts/convert_hiplc_to_hip_full.py`。教程是语义参考，不是本镜头参数真值。
