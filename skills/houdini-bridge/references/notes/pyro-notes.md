# Pyro 烟火实战笔记（学自用户笔记 Pyro等烟火.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 标准流程：点属性（Pyro Source + Attribute Noise 打破均一）→ `Volume Rasterize Attributes` → `Pyro Solver`；Solver 接口 1=发射源、2=碰撞物
> - 精度对齐公式（最常见错误）：Pyro Source 的 Particle Separation × Particle Scale ÷ 2（或 ÷4）= Rasterize 的 Voxel Size = Solver 的 Voxel Size，三者不一致细节错乱
> - temperature 数值 1=3000K、0=300K；驱动烟只需 density + temperature 两个场
> - 调参入口：升力=shape→Buoyancy→Reference Temp / Buoyancy Scale；烟消散=Fields→Density→Dissipation（0.5=每秒消散 50%）；子步=setup→simulation→Min/Max Substeps（CFL 控制自适应）
> - 三大扰动力（shape 面板）：Turbulence 大细节小圆头（值别太高）；Disturbance 打碎边缘网格状烟（蘑菇云处勾 Use Control Field，用温度或速度场：慢不加快加）；Shredding 大块撕碎
> - 碰撞体：trail（Compute Velocity）→ vdb from polygons（勾 surface、Attribute=point.v、VDB name=v、vector type=Displacement/Velocity/Acceleration）→ Solver 的 Collision Type 改 `SDF + Volume Velocity`（SDF 用 surface、Velocity 用 v）
> - 火焰蘑菇头：time scale 拉到 3 倍左右（1:1 时间做火难出形态）；正解是平流微解算器；火焰粘度 ≥ 体素大小 × 10
> - Gas Curve Force 没效果 → Sourcing 的 v 或 Buoyancy Scale 太大把曲线力盖掉了
> - 导出：Solver 输出是 Volume 不是 VDB，必须 Convert VDB；export 只留 density + vel；速度场用 Volume Resample 降精度瘦身
> - OpenCL：sparse 只有 `Minimal OpenCL Solve`（实时调参用，渲染后关）；`Use OpenCL` 不支持 sparse
> - 体积渲染巨慢 = 勾了 volume_indirect AOV + 多灯分层，GPU 基本闲置回 CPU；体积只留 direct + indirect 两层
> - 循环爆炸：Sourcing 勾 `Limit Source Range`，设 Frame Range 和 Cycle Length（如 120 帧读完从 0 重读）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\Pyro等烟火.md` 全文（约 800 行），含 `Axiom.md` 补充。
原始笔记保持只读；本文件是蒸馏版——聚焦实测参数、坑、案例步骤，是 `references/pyro-reference.md`（官方手册体系）之外的用户实战视角补充。

## 0. 总思路（三步走）

1. 先创建点属性
2. 属性栅格化转成体积（`Volume Rasterize Attributes`）
3. 解算（`Pyro Solver`）

体素信息最常见的有 `向量` 和 `浮点` 类数据，体素本质上是三维像素。用点给特定位置的体素格子设置属性值（点有位置坐标），再把点转为 `Fog VDB`，送入 `pyro solver`。

## 1. 原理：场与属性

输入的场：

| 场 | 含义 |
|---|---|
| `density` | 烟雾密度，越高越浓密（density 场就是最常见的 Fog VDB；某些区域体素为 0 就是有形状的雾） |
| `temperature` | 温度。数值 `1` = 3000K（约 270℃），`0` = 300K（约 27℃）。温差驱动浮力，力场驱动烟雾流动 |
| `Velocity` | 速度。点属性通用名是 `v`，vdb 里是 `vel` |
| `Burn` / `Fuel` | 燃烧 / 燃料（火焰的冲击波、爆轰产物） |
| `divergence` | 膨胀和收缩，负值 = 吸收 |
| `flame` | 导出用：有颜色属性和亮度信息（火焰） |

火三角（燃烧三角）：热量、燃料、氧气 + 化学反应。

**SDF VDB**：在模型上放一个场填充体素，计算每个体素离模型表面的最短距离，用 `-+` 判断体素在模型内部还是外部。离表面最近的格子被保留。

**黑体辐射**：不反射光的物体不同温度发出的辐射电磁波（含可见光）。渲染火焰材质的 Physics Blackbody 就是以纯物理方式为火焰体积计算着色。火焰变暗时不会变棕色，而是从白→黄→橙→红（变暗时更饱和）。

**vdb vs volume**：几乎是一个东西，可相互转化。`volume` 是 SideFX 自研，`vdb` 开源；vdb 是 sop 和 dop 的桥梁，常用于构建模型表面、生成力、碰撞体。

### ZibraVDB（Houdini 21 自带，压缩大型体积数据）

- 需另下工具库 + 官网申请免费许可证密钥；节点包共三个：`Labs ZibraVDB Compress` / `Decompress` / `File Cache`，`Quality` 控制压缩比
- 安装：任意 Zibra VDB 节点 → `Open Plugin Management` → 解压 `zibra` 文件夹到 User Pref Directory → `Load Library` → 输入密钥
- 限制：向量场不支持直接压缩（官方有方案，日常生产可用）；SDF VDB 支持不好，需转 FOG VDB，效果不佳不建议用

## 2. 发射源三部曲（实测参数）

### 2.1 Pyro Source

- `Initialize`：属性预设（驱动烟：`density` 和 `temperature`）
- `Mode`：
  - `Surface Scatter` 表面撒点
  - `Keep Input` 把顶点变点当输入
  - `Volume Scatter` 体积内部撒点（类似 `pointsfromvolume` / `vdbfrompolygons`，物体必须闭合）
- `Particle Separation`：粒子间距，越小粒子越多；与 `Particle Scale` 相乘控制点大小
- 初始速度：可在 `Attribute` 上加数值选 `Velocity`，或在外面加 `attribute noise`

### 2.2 Attribute Noise（打破默认值全 1 的均一感）

- `attribute names` 改为 `density temperature`（都是浮点，类型改 `float`）
- `Attribute Class` 设为点级别（`Point`）
- `Noise Value` → `Operation`：`positive` 正数 / `zero centered` 以 0 为中心 / `Min/max` 控制输出范围 / `Negative` 负数
- `Amplitude`：noise 大小
- `Element Size`：噪波图大小；`offset` 平移
- `Animation` 打勾 = 动态 noise（等同 mountain 节点 offset 加 `$FF`），`Pulse Duration` 调动画快慢
- `Fractal` → `Roughness` 控制粗糙度
- `Post-Process` → `minimum`/`maximum` 钳制输出上下限

### 2.3 Volume Rasterize Attributes

- 输入点，为浮点/矢量属性创建 VDB。`Attributes` 填 `density、temperature、v`
- `Voxel Size`：体素大小 = 气体精度（上游 `Pscale` 别高于精度）
- `Particle Scale`：与 Pscale 相乘
- `Coverage Attribute`：控制该场对模拟影响的强度/范围（0 = 不产生影响；在速度场上测试最容易看出来）
- 打开 `Normalize by Clamped Coverage`：采样体积乘以覆盖率，颗粒覆盖区域间平滑过渡

## 3. Pyro Solver 参数速查

接口：1 = 发射源，2 = 碰撞物。`Reset Simulation` 重解算到内存。

### 精度对齐公式（重要）

```
Pyro Source 的 Particle Separation * Particle Scale / 2 或 / 4
  = Volume Rasterize Attributes 的 Voxel Size
  = Pyro Solver 的 Voxel Size（setup 面板 General 下，0.1 = 0.1 米）
```

### 高频参数

| 想改什么 | 在哪改 |
|---|---|
| 升力 | `shape` → `Buoyancy` → `Reference Temp(K)`（参考温度）；`Buoyancy Scale` 是升力数值（百分比）。sparse 在 `Simulation` → `Temperature` |
| 烟消散 | `Fields` → `Density` → `Dissipation`（每秒消散前一秒的百分之几：0.5 = 消散 50%，0.01 = 1%）。sparse 在 `shape` 面板 |
| 初始速度 | `Sourcing` 面板的 `v`，越大越快（升力也影响 v） |
| 烟太白没细节 | 没灯光，加灯 |
| 重力 | `shape` → `Buoyancy` → `Gravity Acceleration`（一般不改）/ `Gravity Direction`。sparse 在 `Simulation` → `Gravity` |
| 子步幅 | `setup` → `simulation` → `Min/Max Substeps`；`CFL Condition` 判断单位时间内穿过 Voxel 的数量。sparse 在 `Simulation` → `Advanced` |
| 循环爆炸 | `Sourcing` → 勾选 `Limit Source Range`；`Frame Range` 发射源帧数；`Cycle Length` 读完 N 帧后从 0 帧重读（如 120） |
| Bounding Box | `Bound` 窗口 `Size`/`Center`；`Limit Maximum Size` 限最大尺寸；可用 box 连 bounding box（初始大小不会很大）。表达式：`centroid("../box1",D_Y)`、`bbox("../box1/",D_XSIZE)` |
| OpenCL 加速 | `Minimal OpenCL Solve` 是 sparse 独有 GPU 加速器，实时调烟雾用，渲染后最好关掉。`Advanced` → `Use OpenCL` 不支持 sparse |

### 三大扰动力（shape 面板，sparse 同在 Shape）

| 力 | 作用 | 关键参数 |
|---|---|---|
| `Turbulence` 湍流 | 大细节扰动，增加小圆头（值别太高） | `Swirl Size` 噪波大小（1 = 1 米，场景 5 米则小细节 1 米）；`Roughness` 颗粒感；`Pulse Length` noise 快慢；`Threshold Field`（sparse 叫 `Influence Field`）影响哪个场（temperature 影响上升趋势）；`Control Field` 在哪加（0 不加，1 百分百加，中间线性） |
| `Disturbance` 扰流 | 小细节扰动，打碎边缘网格状烟，速度越快越明显 | `Base Block Size` 噪波大小（可与 Swirl Size 呈倍数：Swirl Size = Base Block Size * 2）；蘑菇云常出现在速度快的地方，勾 `Use Control Field`，Control Field 用温度场或速度场（慢不加、快加） |
| `Shredding` 撕碎 | 大块撕碎，大型扰动 | 同样有 Swirl Size / Roughness / Pulse Length / Threshold Field / Control Field |

速度场是向量（有大小有方向）；要只有大小的 `speed` 场：`Fields` 面板点 `speed` 按键自动算（sparse 在 `Simulation` → `Calculate Speed Field`）。

### Sourcing 面板

- 没有燃烧的火焰，可把带 `burn` 属性的参数删掉
- `v` 属性处数值是 `1`，所以乘数是 `1`（速度 * 1）

## 4. 碰撞体接入（实测流程）

碰撞体接 pyro solver 右边输入口（接口 2）。

1. `trail` 节点算出物体速度方向得 `v`（point 级别）：`Result Type` 用 `Compute Velocity`
2. `vdb from polygons` 转 VDB：
   - 勾选 `surface` 体积类型
   - `Attribute` 选 `point.v`
   - `VDB name` 用 `v`
   - `vector type` 选 `Displacement/Velocity/Acceleration`（置换/速度/加速度）
3. pyro solver `collision` 选项卡：
   - `Collision Type` 改为 `SDF + Volume Velocity`
   - `Collision SDF` 用 `surface` 属性（碰撞物表面在哪）
   - `Velocity Volume` 用 `v` 属性（都在 vdbfrompolygons 生成）

移动碰撞体（sparse dop 流程）：`Initialize` 改为碰撞物 `collision`；`Volumes` 选项卡下 `collision` 的 `Source Volume` 改为 `surface`。静止碰撞体只需 `Static Object` 引入模型。

体积源（`volumerasterizeattributes` 后的 null）：勾 `Volumes` 选项卡下的 `Enlarge Fields to Contain Sources`。

> 烟雾爆炸后要缠绕在模型上：把模型的运动/位移作为速度加到模拟里，再作为碰撞体。

## 5. 微解算器 Gas Curve Force（控制烟的方向）

没被吸过去 = 力太小。

- `Geometry Source` 选曲线（用 `Curve` 画）
- `Global Scale` 力场；`Max Influence Radius` 最大影响范围
- `Individual Forces`：`Follow Scale` 跟随曲线强度 / `Suction Scale` 吸附到曲线周围 / `Orbit Scale` 旋转 / `Inherit Velocity Scale` 继承曲线速度场
- 各 `falloff` 面板：长度 = curve 长度，0 源头 1 末尾
- `Global Forces` → `Global Force Falloff from Curve`：从曲线到 Max Influence Radius 的所有力衰减
- 没效果 → pyrosolver `Sourcing` 的 `v` 太大，或 `Shape` 的 `Buoyancy Scale` 太大

## 6. Dopnet 内新旧解算器接口

**旧版 Pyro Solver**：1 = object；2 = gas resize fluid dynamic（每步自动调整流体容器大小）；3 = velocity update；4 = Advection；5 = source。

**Sparse Pyro Solver**：1 = object；2 = Advection；3 = source；4 = Forces（本质 velocity update）。

**提取 dopnet 内容**：

- `Dop Import Fields`：从 dopnet 里拿场。`Preset` 选 `smoke` 会生成预设场，需关掉多余的
- `Pyro Post-Process`：pyro 后处理，此处作用是把 `Volume` 转 `VDB`

## 7. 导出与优化缓存

- 解算输出的是 `Volume` 不是 `VDB`，用 `Convert VDB` 节点转换后导出
- export 面板关掉除了 `density`、`vel` 以外的属性（都不需要）
- `vel` 有 x y z 三个，可以 merge 一个 vel 场：用 `Volume Resample` 节点的 `Source Group` 选好即可
- 速度场用来渲染运动模糊：勾 `Resample Volumes` 降低精度（`Voxel Size Scale` 控制降低倍数）
- 点 `Post-Process` 面板下的 `Convert to VDB` 占用内存更小
- pyro 刚解算体积大，需要缩小速度场瘦身，不影响渲染效果
- 删除属性的缓存只是基础，渲染还需其它搭配（TOP、ROP 节点）
- AOV 没有 `indirect` 时很快；一旦有 `volume_indirect` 层 GPU 占用极少，基本回到 CPU 渲染；层越多越慢，多灯光各自分层巨慢。体积就两层：`direct` + `indirect`

## 8. 火焰蘑菇头消除（重点专题）

- 火焰把 `time scale` 拉到 **3 倍左右**，1:1 时间做火难出形态
- 蘑菇头成因：默认解算器不可压缩 + 空气阻力
- **平流微解算器**（正解）：可压缩特性的驱动力，速度场驱动速度场——解算完默认不可压缩力之后，再用自身速度场以可压缩形式驱动自身速度场，把蘑菇头提前顶出去（让空间中都有热气流上升，而非火焰范围内才有上升力）。强度由 `timescale`（时间步长）控制
- 邪修：`gas vorticle geometry` 配合 `gas vorticle forces` 直接暴力扰乱速度场，消灭一切蘑菇头
- `gasdistrub`：把 density field 改成 `flame`，`gasshredding` 开起来
- 最简单：做一个同方向的速度场抵消空气阻力（但未必像真实物理表现）
- dop 加噪波（风力）思路：火焰自身速度快的噪波弱（上升力抵消部分风力），自身速度慢的噪波最强

**火焰细节经验**：

1. 发射源的稀碎程度决定火焰根部镂空细节多少；发射源分布面积、演变速度决定最终火焰轮廓美观度
2. 火焰粘度值 = 体素大小的 **10 倍或更高**
3. 火焰底部镂空：根据发射源范围造自定义场，累积消散，最终在材质里作为颜色使用
4. 中小型火焰细腻感：加 `Buoyancy`（控制大型）和 `Turbulence`（控制自身扭动变化）
5. Karma xpu 渲染的阴影会差一点；火焰散射强度太高会导致开始白茫茫没细节

## 9. 修复断层（高速移动 + 旋转的 pyro）

网上方法（trail 拖尾拉线、解算 pop 拖尾）对质量要求高时解决不彻底。用 dop 内粒子插值、调换添加速度顺序的思路：

1. 处理发射源
2. 碰撞体的处理
3. 发射源的温度浓度等和速度时间的比值
4. 添加速度场的顺序
5. 加速度场
6. CFL（自适应子步调整）或手动 key 子步——暴力算就行

> 有些时候高速烟火就是会断层，不断层才假。

## 10. 机器学习 Upres

- 原理：不真正做流体计算，借低精度流体速度 + 特殊噪波实现更精细速度；低精度模拟上调形态、末端当质量过滤器，显存不涨
- Houdini 21 自带两个 `billowysmoke` 预训练模型，适用范围广
- `ML Volume Upres`：预训练 ONNX 模型放大锐化 Volume
  - `2x` 提升两倍精度；两个节点串联 = 4 倍
  - `Volume` 参数指定要增强的字段（一般 `@name=density`）
  - `Naive Upsample Other Fields`：勾上对其它字段（温度、速度）上采样，避免渲染伪影
  - `Pre Sharpen` / `Post Sharpen` 对锐化作用很大；`Number of Passes` 迭代次数，**5 次左右**较好
- `ML Train Volume Upres`：训练新模型（几小时）；部分训练流程完全摆脱 Python 只用 sop
- 理论背景：[Wavelet Turbulence for Fluid Simulation](https://www.cs.cornell.edu/~tedkim/WTURB/)

## 11. 爆炸参考分析（实拍原理 → CG 还原要点）

- 实拍爆破基本是把物体推向空中的爆炸物组成；炸碎结构空中并不自行解体（空气阻力相比钢筋抗拉可忽略），钻孔爆破的框剪楼落地后常整体完整
- 汽油点燃不爆炸只在表面燃烧；混合气体（很多液滴表面积）才会爆炸性火球：先把气体液滴扔到空中，被余烬/火花/热量点燃形成巨大火球——**先迸发燃料，再在燃料中爆发爆炸**
- CG 爆炸应有多个阶段：初始扩散/气体喷射 → 火焰点燃，而不是直接出现火焰
- 压力波穿过火焰时颜色变化（变明亮黄色再变暗），且**不统一**；爆炸本质是压力、膨胀、冲击波，把握巨大扩张和控制节奏感
- 核弹：炽热火球在外部冷却成烟的包裹中滚动；外部冷却变黑烟、内部仍热（深红）。小炸弹不会形成蘑菇云
- 火只向它点燃的物体方向移动；燃料在爆炸顶部，想让火球前冲燃料需要引领它
- 错误特征：火焰自发产生无来源；外热内黑（热点应在内部）；棕色烟雾（应火焰变红）；平滑圆形火球颜色全相同
- 合成是获得好爆炸的重要步骤，颜色可能在合成中被破坏

**冲击波思路**（截图见原笔记）：生长求解器做冲击波蔓延，时间与参考视频对齐；从生长边缘发射粒子向前射出，转化成烟雾输入模拟。可按与相机距离分 4 个模拟。可以用雪等素材调黑当灰烬混进合成。

## 12. 案例配方

### 快速高细节烟雾（最快出活）

工具架 `Pyro FX -> Sparse Billowy Smoke` → 在 `billowy_smoke` 节点内创建 `attribute noise` 给 `temperature` 和 `density` 生成噪波 → 在 `billowysmoke_simulation` 里调 `pyro_solver`。（截图见原笔记）

### 云中发光（快速实现）

- 主力节点是 `cloudlight`：用漫射光填满一个体积，调节多个光场叠加云层中的发光效果
- 流程：`squab` 自带模型转体积 → `attribute wrangle` 加重 `density` → 撒点设置亮起位置 → `cloudlight`
- `cloudlight` 只支持标准 Houdini 卷，不支持 VDB——最后用 `convertvdb` 和 `vdbvectormerge` 转化合并成 vdb 场
- `volumeslice` 看光传播距离；`volumevisualization` 设置预览颜色
- 渲染：`Karma Pyro Shader` 的 `Bindings` 导入制作的 `Ce` 场（光影响范围），`Fire` 选项卡调颜色强度

### 云案例

- `Cloud Shape Generate` 用不同类型云的预设生成基本形状 → 创建骨架线、散布点、制作体积 → 新 `Cloud Clip` 工具裁剪
- 参考：[创建低空云](https://sergeneren.com/2019/08/21/creating-low-altitude-clouds/)、[Cloudscapes 云景](https://sergeneren.com/2019/09/07/creating-cloudscapes/)

### 沙尘暴（可压缩性思路）

常规往 vel 上加力会全局全程翻滚蘑菇头；真实沙尘暴翻滚但不是全局全程翻。做法：加上可压缩性，加几个可压缩的 pyro 力场，在 dop 内部控制 pyro 大形（而非拼块流程）。前提是掌握 turb + disturb 噪波根据常用场控制 pyro 动态的基础技术。

### 其它

- **导弹尾烟 / 直升机烟雾 / 平地爆炸**：截图见原笔记
- **枪火**：应合成 3 个元素——核心、尖峰、烟雾；方法一用程序化体积，不模拟
- 常用节点：`Labs Fire Presets`（火焰预设快速生成）、`COP Sparse Pyro`（带配方实时模拟的快速体积求解器）、`Pyro Thruster Exhaust`（火焰推进器排气，无需模拟，21 新版）、`Labs Volume Adjust Look SOP`（体积转灰度/法线/运动矢量可视化，调密度、视口渲染质量，对带状伪影有影响）
- 不错的发射方法工程文件：[wttrlabs fire-fx](https://wttrlabs.kit.com/project-files-fire-fx)

## 13. Axiom 补充（GPU 流体插件，学自 Axiom.md）

官方文档：<https://theoryaccelerated.notion.site/>；中文文档：<https://github.com/ShintoKosei/Axiom-CN-Documentation/blob/main/README.md>

安装：

1. 下载解压，放入 `C:\Users\<用户名>\Documents\houdini20.0\packages`（Linux：`/home/<用户名>/houdini20.0`；macOS：`/Users/<用户名>/Library/Preferences/houdini/20.0`）
2. 破解：添加环境变量（系统变量或 houdini.env）
   ```
   AXIOM_LICENSE_PORT = 8086
   AXIOM_LICENSE_HOST = 你的计算机名
   ```
3. 双击运行 `licenseServer2.0.117.exe`
   - 需创建入站规则：允许 TCP 协议 8086 端口
   - 该程序运行时才有破解效果，关了就没
4. 没有对应 Houdini 版本时：修改 json 文件中 `"AXIOM_4_0_CONDITIONAL_TOOLS"` 和 `"HOUDINI_PATH"` 两个键的值

Sample 截图见原笔记。更多 Axiom 内容见 `references/axiom-reference.md` / `axiom-practice.md`。

## 易错点

1. **精度不一致**：发射源（Particle Separation × Particle Scale ÷ 2 或 4）、Volume Rasterize 的 Voxel Size、Solver 的 Voxel Size 三者必须满足对齐公式，否则细节错乱
2. **Minimal OpenCL Solve 渲染后忘关**；`Use OpenCL` 不支持 sparse 解算器，勾了没加速还可能出问题
3. **碰撞体用 VDB 但 Collision Type 没改成 `SDF + Volume Velocity`**，或 Collision SDF / Velocity Volume 没指向 vdbfrompolygons 生成的 `surface` / `v`
4. **导出忘 Convert VDB**：solver 出来的是 Volume 不是 VDB；export 面板没关多余属性、速度场没降精度 → 缓存巨大
5. **火焰 1:1 时间做不出形态**：time scale 要拉到 3 倍左右；火焰粘度值应 ≥ 体素大小 × 10
6. **体积渲染巨慢**：勾了 `volume_indirect` AOV 层 + 多灯光分层，GPU 基本闲置回 CPU
7. **Gas Curve Force 没效果**：先检查 Sourcing 的 `v` 和 `Buoyancy Scale` 是不是太大把曲线力盖掉了
8. **ZibraVDB 压 SDF VDB**：支持不好需转 FOG，效果差不建议
9. **Axiom 破解失效**：licenseServer 程序被关了，或防火墙没放行 TCP 8086
