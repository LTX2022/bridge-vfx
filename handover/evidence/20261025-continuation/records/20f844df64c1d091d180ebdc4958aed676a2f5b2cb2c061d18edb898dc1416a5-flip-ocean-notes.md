# FLIP 流体与海洋实战笔记（学自用户笔记 流体海洋.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 流程顺序（最大坑）：定镜头/比例 → 先做波谱（Ocean Spectrum）→ 再进 dop 解算 FLIP；海面与解算必须共用同一套波谱数据，否则无限海面重复纹理、缝隙明显，回天乏术
> - 救命三坑：mesh 闪→加粒子或用节点"球形"模式；白水缓存崩→关 `density control`；2kw 粒子爆内存→减粒子降精度 + mesh 处用 `erode`（不建议加内存条）
> - 精度别混：`Flip Object` 的 `Particle Separation`=粒子精度；`Whitewater Solve` 的 `Whitewater Scale`=白水精度，是两个不同参数
> - Ocean Spectrum 起手：`Resolution Exponent`=10 是很好起点（特写才拉高）；风速 `Speed` 标准海洋约 4（0=平静）；比例没把握放一艘船做参考
> - 分频利器：Amplitude 的 `Filter Above/Below Resolution` 删高/低频，多个 Spectrum 分开控制不同频段；两个 Spectrum 节点 merge 输出海洋更丰富
> - 海面 mask：大部分海面 speed 降到 1、Pulse Length 加到 10；`Input Range` 减小=更硬更清晰的杂色区
> - 海浪回落分层 = 粒子精度不够或 `Grid Scale` 间距偏大；Grid Scale 一般 1.5 足够，调小间距
> - 水花细节主要靠白水；粒子精度最直接（一般海洋 50 米、基础水体细分 0.03；飞出的块状水滴用 vex 删）
> - 渲染 mask 属性：`vorticity`、`v`、`P.y`、`flattened` 控制折射/反射/漫射；大水体水花不会全透明，太透明+高光太强=比例显小
> - Karma Ocean Procedural：缓存必须选 `save_spectra` 节点写盘；`Dicing Camera` 指向渲染相机；`Z Importance` 比整体 Dicing Quality 更有效（控制远处细分）
> - 无限海用工具架 Guided Ocean Layer（薄层引导式 FLIP）；渲染树别连 `Preview Houdini Procedurals`；最终渲染网格细分可低到 2
> - 碰撞体穿越解算框 → mesh 破洞进渲染序列无法挽回，必须在解算前从刚体碰撞阶段解决

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\流体海洋.md` 全文（约 550 行）。
原始笔记保持只读；本文件是蒸馏版——聚焦实测参数、坑、案例步骤，作为 `references/sim-reference.md` 等官方体系外的用户实战补充。

## 0. FLIP 原理速记

体素根据内部点的数量计算密度值：点越多密度越大；密度大的格子产生压力，指向周围比自己密度小的格子，以此解决粒子重叠。重力下部分体素为空 → 判定为空气；与空气接触的最外层体素被认为是液体表层，对表层内粒子产生力（表面张力），使模拟更光滑。

> sop 的流体虽有了，但大项目最好还是用 dop 的流体。

**精度参数对照**（容易混）：

| 节点 | 参数 | 对应 |
|---|---|---|
| `Whitewater Solve` | `Whitewater Scale` | 白水流体精度（`ww res - pts`） |
| `Flip Object` | `Particle Separation` | 粒子精度（`fluid res`） |

新工具：`White Water` 工具（逼真水坝效果）、泡沫工具、作用于几何体的 `Ripple Solver`（基于弹簧模拟，可在其它物体上生成涟漪并在涟漪上动画）。

## 1. 常见坑（先记这些能救命）

- **mesh 闪**：粒子少很难不闪；要么用节点上"球形"模式（每个粒子一个小球）就不会闪，建议加粒子
- **白水缓存总是崩**：关掉 `density control` 就好了
- **交互拖尾浪花**：通常都是 procedural 水面 + 加白水就行
- **粒子变液体 mesh**：`particle fluid surface` 节点包 mesh（每个粒子包成一个体积）；不好包可用几个 vdb 节点自己包
- **穿越解算框的 mesh 破洞**：碰撞体穿过解算框，mesh 转 mesh 时被裁掉出现漏洞 → 体积渲染出现奇怪亮斑，序列渲染后几乎无法挽回，必须在解算前从刚体碰撞体阶段解决
- 粒子数量太大（如 2kw）爆内存跑不动：`particlefluidsurface` 内部转 vdb 再转 polygon（内存爆了）→ 要么减粒子降精度、在 mesh 处用 `erode` 优化效果（建议）；要么加内存条（不建议）

## 2. 水杯不漏（经典案例，实测步骤）

原理：将杯子和杯内区域范围转成速度场；用 pop 计算杯内粒子，同时使用 pop fluid；判断水是否在杯内，在杯内就额外受该速度场驱动。

1. 简单 sop 操作做容器，**保留外壁**（外部模型就分离一下）
2. 模型外壁做布尔，用 `vellumconstraints_grain` 填充粒子（`points from volume` 也可以）
3. 加 `transform` 简单 K 一个动画，用 `extracttransform` 得到变换信息
4. `collision source` 节点输出 sdf（即 filecache1）：**substeps 设为 5**（希望解算时 substeps 是 5）；文件路径填 Python 表达式代替 `$F` / `$FF`：
   ```python
   pythonexprs("'%07.2f' %hou.frame()")
   ```
5. 回到粒子和模型：用 extracttransform 的变换信息驱动 vellum 填充好的粒子，与带变换的水杯模型 merge；再用 `collision source` 计算一次速度信息，最后转成场
6. 建 `pop network`，步幅改为 5（与上面的碰撞缓存一致）；正常引入碰撞模型和 sdf
7. `pop fluid`：让粒子解算时有类似水的形态，小规模液体下非常好用
8. `sop solver`：在 dop 里得到布尔水面时的模型（记得用变换信息驱动），做个简单组判断；`popadvectbyvolumes1` 引入上面做好的场，把 sopsolver 里判断出的组填进去——只有杯内的水被额外驱动
9. 解算；后面按速度上个颜色即可

工程文件与原文链接见原笔记（百度网盘 `klx1` / 微信公众号文章）。

## 3. 海洋与解算流体的融合（流程顺序最重要）

**正确顺序**：定好镜头、资产比例 → 先做程序化海面纹理（波谱）→ 把波谱导入 dop 算流体。

用户犯过的错误：先做了解算再后加海面 → 没有调整空间，且解算时的频谱只服务于小块范围，给到无限海面全是重复纹理，回天乏术——**海面必须和 flip 用同一套波谱数据，否则无限海面缝隙会很明显**。

融合手法：

1. 把两者的边连接起来，这样就没有解算边界
2. 解算的用 boolean 包起来套一层边过渡，无限海面挤出来，效果还能接受
3. 边界传一个 alpha 给到材质

拆分思路：把运动幅度大的水提取出来；解算出的水分两部分，一部分加光谱置换（跟海面同一个置换）。可以先算水再做海面：海面用一个 box 和 flip 合并拉出无限大的面再上材质；通过速度和涡度区分哪是解算水、哪是海洋频谱。不加海洋频谱的水结算更快更可控。

**水花细节**：粒子精度是最直接的办法（可适当提升体积精度、碰撞速度 noise 优化、碰撞体细节），但基本还是靠粒子精度——慢是做水的特点之一。一般海洋 50 米，基础水体细分 0.03；飞出来的块状水滴用 vex 删掉或在计算器里杀死。**细节主要看白水**。

**渲染质感经验**：

- 用 `vorticity`、`v`、`P.y`、`flattened` 等属性做渲染 mask，去改折射/反射/漫射
- 大体量水体即便溅起水花也不会完全透明；水花太透明 + 高光太强 → 水体比例看起来偏小，渲染风格也影响比例表现
- 合成中水雾至关重要：不仅通过 depth 通道叠雾气，还要找烟雾素材叠加（明暗和密度靠素材，素材光影太平就自己染体积叠过去）

## 4. Ocean Spectrum 参数速查

光谱只是产生了一个正在整个环境采样和平铺的场。比例不好确定时，放一艘船作参考。

| 参数 | 说明 |
|---|---|
| `Resolution Exponent` | 光谱分辨率，越高频率细节越多、计算更贵。**10 是很好的起点**，再高实际频率细节可能小于相机像素；特写镜头拉高 |
| `Grid Size` | 网格大小，海洋光谱的世界空间大小。大范围海洋网格做大，波看起来大。看到重复贴图就是因为 Grid Size 就这么大（可与 grid 节点 size 匹配；小于 grid 得到更小更高频的波） |
| `Grid Center` | 网格位置偏移 |
| `Depth` | 海洋深度，不同深度有不同波浪 |
| `Time Offset` / `Time Scale` | 时间偏移（波浪起始位置）/ 时间尺度（波浪速度） |

### Wind 选项卡

- `Spectrum Type`：
  - `TMA`（默认）：基于物理，更自然，增加风作用时间的额外参数，低 Depth 下表现更好。特有 `Swell`（增强方向性，负值消除方向性并在反方向加波）、`Fetch (km)`（风作用在海洋上的距离，通常认为是与海岸的距离；深海与海岸线海浪非常不同）
  - `Phillips`：经典光谱，控制完全开发海洋中的风向。特有 `Directional Bias`（波浪与风向对齐程度，增大抑制不符风向的波）、`Directional Movement`（低值时有逆风向的波，增大抑制只剩同方向的波）
- `Direction`：风向（度），从 X 轴顺时针
- `Speed`：风速。高风速产生更大的低频波，动态范围更大（更高的高点更低的低点，对比更强），0 = 平静海面（**标准海洋大约 4**）
- `Chop`：波浪尖锐尖顶数量，越高越尖锐

### Amplitude 选项卡

整体是乘数，大部分时候保持默认。**分频利器**：

- `Filter Above Resolution`：删除设置分辨率以上的波只留低频 → 可以不同频率做多个 `Ocean Spectrum` 分开控制
- `Filter Below Resolution`：删除设置分辨率以下的波只留高频 → 在原模拟上加高频波

### Wave Instancing 选项卡

将海浪实例化到输入点上（取一个点创建一个光谱补丁）。`Radius` 实例化波浪半径；`Rotation` 旋转；`Amplitude` 振幅缩放；`Variance` 每点随机变化量；`Rolloff` 波纹到边缘多久淡化。多个点在同一位置会叠加多个波。**两个 `Ocean Spectrum` 节点合并输出**，不同节点做不同速度和波的变换，海洋光谱更丰富。

### Mask 选项卡（抑制频谱的区域）

- 大部分海面 mask：`speed` 降低（如 1）、`Pulse Length` 增加（如 10）
- `Type`：抑制 `Suppression` / 贡献 `Contribution`（效果相反；贡献 = 让某些东西只出现在 mask 中）
- `Input Range`：减小创建更硬更清晰的杂色区域；增大柔化过渡（第一个参数是蓝色值、第二个是红色值）
- `Visualization` → `Visualize` 改 `Mask` 查看范围：蓝色是抑制、mask 应用到的地方；红色是不附加 mask、波浪保持强度的地方
- 可勾 `Blend with Spectrum` 引入新的 Ocean Spectrum
- mask 用于增强表面、让东西看起来不均匀，非常简单有效

**要非常高频的波**：Wind 的 `Speed` 调小 → 调小 `Grid Size` 和 `Resolution Exponent`；振幅混乱就改 Amplitude 的 `Scale`（受 grid 实际几何形状限制）。

**自定义 mask**（Ocean Spectrum 第二个输入）：

- 笔刷路线：`attribute paint` 绘制 → `Scatter` 用 mask 撒点 → `Attribute Wrangle` 给点 density=1 → `Volume Rasterize Attributes` 用 density 生成体积场
- VOP 路线：volume 用 density 生成体积场（`Uniform Sampling Divs` 相当于体积细分，越大精度越高）；VOP 内 `Anti-Aliased Noise`（`3D Frequency` 设噪波大小）和密度相乘；`clamp` 和 `fit` 控制密度最大最小范围（= 不同密度的波浪强度）；`Volume Mix` 混合两个 volume
- 用点的 `N`（法线）属性控制波浪流动方向
- `Ocean Evaluate` 还可以烘培导入的纹理；查看水面浪最高/最小可以用来控制浪高

**Ocean Wave**：需要更具体或几乎直接控制波浪时用，和 ocean spectrum 很像。`animation type`：`Center` 适合自己 K 帧做动画；`Wave Speed` 用自带波浪速度控制（缺点：起始帧只能从 1 开始）。`radius` 是给每段 `points per wave` 的值撒点后设置半径。

**相关节点**：`Ocean Evaluate`（根据 spectrum 体积变形输入几何体，可视化海洋）、`Ocean Foam`（生成基于颗粒的泡沫白水）、`Extrude Volume`（曲面挤出体积，做海洋深度）、插件 `ping.modify_wave.1.0.hda`（海浪生成资产，参数基本不用改）。

**网格细分经验**：做预览的网格细分给高些；做最终渲染的网格细分可以低些，**甚至只有 2**。

## 5. 海洋渲染

### Karma（Houdini Procedural: Ocean 节点）

烘培好泡沫后，在上级 `houdini ocean procedural` 节点勾选 `shading` 下的 `Foam Particles` 才能应用泡沫到场景（自动做基于相机距离的适应性网格 dicing）。

| 参数 | 说明 |
|---|---|
| `Spectrum File` | 引用 `Ocean Spectrum` 烘培出来的文件 |
| `Mask File` | 引用 `Ocean Spectrum` 分离出的 mask vdb 文件 |
| `Viewport Quality` | 实时预览质量；新版会把不在相机视口内的置换关掉，没效果就拉大它。别设过高，可能耗尽内存 |
| `Dicing Quality` | 实际渲染质量 |
| `Dicing Camera` | 指向正在渲染的相机（预览长得不像 sop 网格时调这个） |
| `Render Geometry` | 引入要渲染的海洋表面（grid） |
| `Reference Render Geometry as Interior` | 模仿水下体积 |
| `Geometry Z Measure` | 更改与相机空间或像素空间 |
| `Z Importance` | 比改整个 Dicing Quality 更有效：控制从相机到远点基于精度的细分。越大越远处细分越高、置换浪越明显 |
| `Screen Window Size` | 1.1 = 渲染相机视口 110% 范围 |
| `Downsample` | 向下采样光谱；渲染非常高质量的海洋可设置 |
| `Anti-Alias Blur` | 抗锯齿模糊，离得越远增加该参数更模糊/更锐利清晰 |
| `Point Velocity` | 让渲染速度通道正确渲染海洋运动模糊 |
| `Cusp Intensity` | Cusp 调整海洋浪尖（类似泡沫），控制浪尖的白色 |

注意：

- **一定要选 `save_spectra` 节点来缓存到磁盘**
- 视口预览分辨率看 `Viewport Quality`；渲染时看 `Dicing Quality`——sop 中创建的光谱层包含足够细节即可
- 渲染时将 `Preview Houdini Procedurals` 节点不连入渲染节点树
- 记得 `Reload Geometry` 让模型应用到场景

### Mantra

`spectrum Geometry 参数` 的来源都是指定 `Geo` 环境下 `geo1` 节点里的 `File Cache` 给 `Ocean Spectrum` 做的缓存文件。项目结构与 surface/volume 材质设置截图见原笔记。

### 渲染策略（三种）

渲染器不支持光谱数据（或想省渲染时间）时，导出 `Ocean Evaluate` 的结果网格化，需要一个分辨率让光谱实际移除一些细节：

1. 不做任何缓存直接渲染（同时处理加载，特别慢）
2. `Ocean Evaluate` 节点里直接缓存再渲染（占大量磁盘、读大量数据但不计算）
3. 给基网格（grid）渲染一帧，再对做好的光谱渲染一次（**单帧缓存光谱**；如有随时间演变的动画遮罩，需将遮罩作为序列缓存出来）

## 6. 无限海（缝合海洋 / Guided Ocean Layer）

工具架创建模拟海洋表面薄层的 FLIP 流体模拟（`guidedoceanlayer_fluid_extended`）：

- 创建海洋表面顶部薄颗粒层的引导式 FLIP 模拟
- 指定深度的海洋表面充当粒子下方的碰撞层，使粒子与海浪紧密匹配
- 粒子的边界层抑制水箱边缘的反射，将海洋速度贡献回模拟，并保持水量水平以匹配海洋
- FLIP 模拟使用引导体积方法通过模拟保持海洋速度
- 最后在 `Solaris` 里更新 `Houdini Procedural: Ocean` 节点

## 7. FLIP 浪花形态控制

| 节点 | 参数 | 说明 |
|---|---|---|
| `flip object` | `Particle Separation` | 粒子精度，越小细节越多 |
| `flip object` | `Grid Scale` | 粒子间距，**一般 1.5 足够**。海浪回落出现分层 = 粒子精度不够或间距偏大 → 调小间距 |
| `flip solver` | `Velocity Smoothing` | 降低流体模拟速度，减少紊乱、让模拟平稳 |
| `pop advectby volumes` | `Force Scale` | 越大浪花越大、速度越快（**根据整个场景尺寸设置**） |

不同沙滩模型影响浪花形态：正常沙滩是平缓型，坑坑洼洼像岩石坑的是另一种形态。

## 8. 飙血案例（游戏向，实测解法）

`pyrosource` 做发射源 → 传统 flip 流程转流体 → 颜色上顶点色。

问题：结算时容易抽搐。个人解决办法：用 `nearpoints` 查找周围点的数量，数量越少 size 越小、同时随时间 size 减小，可一定程度解决。最后导入引擎写材质，控制面数大小在 **10MB** 左右项目可用。

## 9. 小规模流体：Remesh Bubbles

`Remesh Bubbles`：在点云上生成泡沫状结构，非常适合小规模流体模拟创建气泡（如咖啡倒进杯子）。

## 10. 涟漪解算器（Ripple Solver）

三个输入：1 = 输入几何体；2 = 变换的几何体；3 = 碰撞几何体（碰撞形状是造成涟漪的原因）。

- 粒子发射器（`source_first_input`）设置截图见原笔记；`popkill` 节点用 `Bounding Box` 删粒子
- **粒子直接穿过碰撞物体时，提高子步幅可能不起作用**：必须实际限制粒子/物体穿过的速度，以便记录穿过的几何体；几何体太薄会有问题；没足够时间记录穿过就不有效。可调发射器前的 `Transform` 使其更高/更低，并增加被碰撞物体的细分

**Setup 窗口**：

- `Wave Type`：波纹类型
- `Wave Speed`：波纹传播速度
- `Rest Spring`：返回休息状态的速度
- `Conservation`：控制涟漪能量，传播更远或更近

类似下雨的模拟：需要另一个粒子模拟从粒子撞击的地方弹出粒子或小水滴。

**Thickness 窗口**：`Max Thickness` 最大厚度（调低会出现一些大飞溅消失）；`Thickness Multiplier` 厚度乘数（调低不明显）。可和 Clamping 一起尝试，摆脱真正大的飞溅回到更现实的飞溅。**Clamping** 勾选启用可得更平滑结果。

## 11. 商业项目河流（工期 1-2 周的取舍）

镜头元素只有环境和河流；河流要求超快模拟、易于迭代、只有一个方向流动。项目要求：2D 驱动模拟、使用现有工具集、基本着色器、程序化、不惜一切代价限制模拟。构建必须简单：相对容易建立的 2D 模拟系统、定向流场（向量场描述的流体方向）、找合适的拐弯弯道扭曲工具、着色器集成、能改工具底层模拟集成。

## 易错点

1. **流程顺序错误（最大坑）**：先解算后加海面 → 无调整空间且无限海面重复纹理；必须先做波谱再进 dop，海面与 flip 共用同一套波谱数据
2. **白水缓存崩**：先关 `density control` 再试
3. **粒子穿越碰撞体就加子步**：Ripple Solver 里提高子步可能无效，要限制穿过速度、加碰撞体细分、调发射器高低
4. **mesh 破洞进渲染序列**：碰撞体穿解算框导致，体积渲染出亮斑，序列渲染后无法挽回——解算前就解决
5. **精度参数混淆**：`Whitewater Solve` 的 `Whitewater Scale`（白水）≠ `Flip Object` 的 `Particle Separation`（粒子）
6. **海浪回落分层**：粒子精度不够或 `Grid Scale` 间距偏大，调小间距（1.5 一般够）
7. **忘用 `save_spectra` 缓存到磁盘** / 渲染树里连了 `Preview Houdini Procedurals` / `Dicing Camera` 没指向渲染相机
8. **大水体水花太透明 + 高光太强** → 比例看起来偏小；用 vorticity/v/P.y/flattened 做 mask 控制折射反射
9. **爆内存**：2kw 粒子直接 `particlefluidsurface` 包 mesh 会爆，减粒子 + `erode` 优化
