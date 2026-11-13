# Pyro 手册知识体系（官方 help zip 完整原文整理 + 工程实测）

> 来源：Houdini 21.0.631 `houdini/help/pyro.zip` 完整原文（27 个文档）+ Fire_shot1 工程实测。
> ⚠️ `sim-reference.md` 是摘录版含 32 处截断，本文档基于 zip 原文，以此为 Pyro 定义权威。
> Axiom 对照见 [axiom-practice.md](axiom-practice.md)。

## 1. 手册文档地图（pyro.zip，按用途分类）

| 类别 | 文档 | 内容 |
|---|---|---|
| **入门/概念** | `intro.txt` | 概念体系 + 节点地图 + shelf 工具 |
| | `pyro.txt` | 主文档：point sourcing / 网络结构 / 容器扩缩 |
| | `sparsity.txt` | sparse vs dense / active 场 / full tiles |
| | `differences.txt` | 新旧 pyro 差异 |
| **燃烧** | `flames.txt` | flame 场 / lifespan / 三种输出 ★核心 |
| **调参** | `lookdev.txt` | 官方工作流 + 基础参数语义 ★ |
| | `pyro_look.txt` | look development 技巧 |
| | `shading.txt` | 渲染着色 / ACES |
| **专项** | `explode.txt` | 爆炸 |
| | `sparks.txt` | 火花 |
| | `background.txt` | 理论背景 |
| | `advanced.txt` | 高级用法 |
| **instancing** | `definitions.txt` | packed set / spawn / instance 术语 |
| | `pyroinstancing.txt` / `advanced.txt` | instancing 工作流 |
| **Copernicus 2D** | `pyro_configure_*.txt` / `copintro.txt` | COP 2D pyro（与 3D solver 无关，一般用不到） |

## 2. 核心概念

### Pyro 是什么
- 体积流体模拟包：火/烟/爆炸/雾/雪崩等"类流体"现象
- **不适合液体**（液体用 FLIP;pyro 无粒子，不解表面）

### 场体系（属性名 = 场名，历史例外：`v` 属性 -> `vel` 场）
`density` `temperature` `fuel` `divergence` `burn` `heat` `velocity(v->vel)` `collision` `source` `sink` `flame`
- **flame** = 反应物（燃料）**剩余寿命**：source 注入、solver 平流并消耗；"年轻时放热，耗尽时放烟"
- **H17 起推荐 point-based sourcing**：Pyro Source SOP 生成带属性点 -> Volume Rasterize 转体素 -> Volume Source DOP 合并入场（改点属性比改体素方便，可先跑粒子 sim 再当源）

### 容器与 Sparse 模式
- 容器自动扩缩，追踪 **Reference Fields**（默认 `density flame`，Advanced > Resizing 标签）——即"有烟或有火的地方"都保留在模拟域内
- **sparse（默认）**：只算 active 子集（`active` 场=1 的区域，每步重建），高效；2D 和 OpenCL 不支持
- **full tiles**：active 区域以 16×16×16 体素块为单位；外部扩域必须整块（Volume Source 的 Enlarge Fields 与 Enlarge by Full Tiles 要同时开）
- 额外 microsolver（如 Gas Disturb）在 sparse 下要把 **Stencil Field 设为 `active`**，否则做无用功
- 两股 sparse 烟互不可见，直到 active 区域合并

## 3. 节点地图

```
SOP sourcing:                       DOP:                    输出/渲染:
pyrosource (几何->带属性点)          smokeobject_sparse      dopimportfield
volumerasterizeattributes (点->体素) volumesource (合并入场)  pyrobakevolume (视口近似渲染)
pyroburstsource (爆炸核心)          pyrosolver_sparse       pyropostprocess (省盘~90%)
pyrosourcespread (火焰蔓延)                                  volumevisualization
pyrosourcepack/spawnsources/        或 SOP 一体化:          vop/pyroadvancedshader
  sourceinstance (instancing)       pyrosolver (SOP包装)
```
- **Pyro Solver SOP = DOP 网络的 SOP 包装**（多数场景够用；Fire_shot1 就用它）
- Smoke Solver 只能烟不能火；Pyro Solver 在其上加火
- 视口默认 gamma 2.2 不适合看 pyro，建议 ACES + Color Correction

## 4. 燃烧：flame 场与三种输出（flames.txt 核心）

**Lifespan 官方公式：耗尽时间 = L × f**（L=Flame Lifespan, f=初始 flame 值）。
**值越大反应越慢**；lifespan=2 -> flame 值 1 要 2 秒耗尽。

三种输出（Flames 标签，各自独立：基础乘数 + Flame Range + 可选 ramp 重映射）：

| 输出 | 写入场 | 基础乘数 | 参数名（solver） | 效果 |
|---|---|---|---|---|
| smoke（soot） | `density` | Emission Scale | `soot_amount` | **烟的可见浓度** |
| temperature | `temperature` | Temperature Amount | | 放热->浮力 |
| expansion | `divergence` | Expansion Rate | | 膨胀爆开 |

计算顺序：flame 值按 **Flame Range**（`soot_controlrangemin/max`）fit 到 0-1 ->
（可选 Remap Flame ramp）-> × 基础乘数 -> Max/Add 合并入目标场。
**sourcing 推荐用 Maximum 合并**（刷新源处 flame 但避免 Add 的过度累积）。
调 Flame Range 前先算清楚 source 进来的 flame 最大值。

## 5. 参数语义速查（lookdev.txt + 工程实测）

### 基础（Smoke Object / Properties）
| 参数 | 语义 | 要点 |
|---|---|---|
| **Voxel Size** | 模拟分辨率（越小越精） | **按场景尺度设**：单位级爆炸用默认 0.1，百单位级场景相应放大；先大 voxel 快试再细化 |
| Boundary Conditions | 边界 | 加地面/墙时用 |

### Solver 基础
| 参数 | 语义 | 要点 |
|---|---|---|
| **Max Timesteps** | 每帧最大子步 | 烟默认 1 够；高速流体要加 |
| **Padding** | 烟周围预留空间 | 要容纳一个 timestep 内的运动；太大拖慢模拟（参数名 `resize_padding`；sparse 另有 `sparse_padding`/`sparse_maxpadding`） |
| Enable Sparse Solving | sparse 开关 | `sparse_dosolve`（solver 与 object 都要开，默认开） |
| Reset Fields | sparse 重置的场 | `sparse_resetfields`（Fire_shot1 工程实测="vel temperature Cd Alpha"） |

### 温度/浮力（bulk 运动的关键）
| 参数 | 语义 | 要点 |
|---|---|---|
| **Ambient Temp (K)** | 周围空气温度（temperature 场 0 映射到此） | 开尔文；C+273.15 / (F-32)×5/9+273.15 |
| **Reference Temp (K)** | temperature 场值 1 对应的物理温度 | **最高源温度 = Ambient + T×(Ref-Ambient)**；调到视口 emission 颜色正确为止 |
| **Gravity** | 重力（影响浮力强度） | 按场景尺度调一次就别动 |
| **Buoyancy Scale** | 浮力乘数 | 微调烟升速度用这个，别改温度范围（参数名 `enable_buoyancy`/`buoyancylift`，Fire_shot1 实测 lift=0.27） |
| **Cooling Rate** | temperature 向环境温度冷却速率 | 看烟升速开始变慢的地方定值（参数名 `tempcooling`，Fire_shot1 实测=0.7） |

### 燃烧（Flames 标签）
| 参数 | 节点参数名 | 语义 |
|---|---|---|
| **Flame Lifespan** | `flames_lifespan` | 消耗速率，公式 L×f，**越大烧越慢** |
| **Emission Scale** | `soot_amount` | 产烟浓度 |
| **Flame Range** | `soot_controlrangemin/max` | 放烟/放热区间（flame 消耗到此区间时输出最旺） |
| flame source scale | source_volumes 的 `vscale3` | **每帧注入反应物量，火旺程度**（volume3=burn->vfield3=flame） |

## 6. 官方调参工作流（lookdev.txt 顺序）

1. **Source 几何**：定源头（pyrosource 散点 + attribnoise 加随机）
2. **基础参数**：Voxel Size（按尺度）+ Max Timesteps（看速度）——设一次基本不动
3. **温度/浮力**：Ambient/Reference Temp(K) 定物理含义 -> Gravity 按尺度 -> Buoyancy Scale 微调升速 -> Cooling Rate
4. **Flames**：先 **Flame Lifespan**（火持续多久）-> 再开输出调 Flame Range
5. **Shape operators**（disturbance/turbulence 等）：bulk 形态满意后才做细节

## 7. instancing 术语速查（definitions.txt）

| 术语 | 定义 |
|---|---|
| **packed source set** | 打包的源体素+合并规则（`name`/`frame_length`/`source_rules` 属性）；pyrosourcepack 创建 |
| **library** | 多个 packed set 合并的源库 |
| **spawn point** | 实例配方（无时间性）：`startframe`/`endframe`/`looplength`/`sourcespeed` 等属性控制何时/多快/循环播放 |
| **instance point** | 实际激活的实例：`frame_offset`（用源序列哪一帧）+ `source_rules`（怎么合并入场） |
| **rule overrides** | 同一源不同实例可覆盖规则（如同源出热烟冷烟）；spawn 上直接设值，instance 上用点属性当调整值 |

时间线不从 1 开始（如从 1001）时，**所有 Reference Frame 参数**（pyrosourcepack/pyrosourceinstance/solver 的 source+collider 两个）要统一改成 1001，否则 packed set 被 timeshift 到够不到的帧。

## 8. 调参案例：v1 -> v2（Fire_shot1 实测）

v1 = 工程原值（pyrosolver1/2 当前）；v2 = 拟改值：

| 参数 | v1 | v2 | 单项效果 |
|---|---|---|---|
| flame source scale (vscale3) | 1.3 | 0.5 | 注入反应物降到 38%：火苗小一圈，更快跌进放烟区间 |
| density source scale (vscale1) | 1 | 1 | 源头直灌烟不变 |
| Emission Scale (soot_amount) | 4 | 2 | 产烟浓度减半 |
| flame lifespan (flames_lifespan) | 1 | 0.7 | 耗尽 = L×f：1s -> 0.7s，烧完快 43% |

**综合：v1=大火浓烟持续烧；v2=小火薄烟快转余烬**。四个参数全朝弱化调会互相放大
（火小->放烟窗口短 × emission 减半 -> 总烟量降超 50%）。
**建议分开调**：先动 flame scale + lifespan，soot_amount 留着看效果再定。

## 9. hython 查这些参数（离线，不开 GUI）

```python
# "C:\Program Files\Side Effects Software\Houdini 21.0.631\bin\hython.exe"
import hou
hou.hipFile.load(r'C:/path/shot.hip')
sv = hou.node('/obj/fire/pyrosolver1/dopnet1/source_volumes')
print(sv.parm('vscale1').eval(), sv.parm('vscale2').eval(), sv.parm('vscale3').eval())
# 字段映射：sv.parm('volume1').eval() / sv.parm('vfield3').eval()
s = hou.node('/obj/fire/pyrosolver1')
print(s.parm('flames_lifespan').eval(), s.parm('soot_amount').eval(),
      s.parm('soot_controlrangemin').eval(), s.parm('soot_controlrangemax').eval())
```

## 10. 查官方手册完整原文

```python
import zipfile
# zip 目录：C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/
z = zipfile.ZipFile(r"C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/pyro.zip")
text = z.read("flames.txt").decode("utf-8", errors="replace")  # 文件名见 §1 地图
```

bridge 在线搜（Houdini 开着，`mcp.execute` + `help.search`，无 limit 参数）：
```
POST http://127.0.0.1:8100/api  json=["mcp.execute",[],{"command":"help.search","params":{"query":"lifespan"}}]
# 返回 scope+file 字段 -> 按文件名去 zip 读全文
# help.query 只支持 node/vex/hom/solaris；概念文档（pyro/flames 等）用 zip
```
其他手册 zip 同理：`anim.zip` `basics.zip` `commands.zip` 等（目录同上）。

## 11. 一句话记忆

> flame=燃料剩余寿命，耗尽=L×f（lifespan 越大烧越慢）；soot_amount=烟浓度，vscale3=火旺度（在 source_volumes 不在 solver）；
> Voxel Size 按场景尺度；浮力用 Buoyancy Scale 微调；先 bulk（temp/buoyancy）后细节（shape）；
> sparse 只算 active 区（16³ tiles）；查定义读 help zip 原文，sim-reference.md 有截断。
