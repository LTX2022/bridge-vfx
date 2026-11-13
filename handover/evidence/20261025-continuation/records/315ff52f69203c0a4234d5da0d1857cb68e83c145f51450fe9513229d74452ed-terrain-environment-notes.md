# 地形与环境：HeightField 工作流与植被散布（学自用户笔记 地形环境.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\地形环境.md`（约 750 行）。
原始笔记保持只读；本文件是蒸馏版。定位：`references/workflows/heightfields.md` 等通用指南之外的**用户实战补充**——聚焦笔记里的具体参数、坑、操作习惯。文中 `![...](./图片/Houdini/...)` 为原笔记截图相对链接，截图见原笔记。

## 0. 环境制作心法

- **观察参考**：看场景里有什么物体、数量比例、分散状况、哪些物体体现**层次差异化**，抓住参考的特征。
- 构图三要素：**主、次、点缀**。
- **正方体占位法**：前期放正方体替代建筑，先做好运镜、灯光和环境大关系，再替换正方体并持续加细节。
- 真实地形模拟帮助论文：https://www.bilibili.com/read/cv28508413/
- `heightfield_flowfield` 节点全称是 `Height Field Flow Field`。

## 1. HeightField 图层体系

### 1.1 基本图层

| 图层 | 说明 |
|---|---|
| `height` | 高度 |
| `mask` | 遮罩 |
| `visualization` | 仅作用于视口及渲染着色；可用 `erode`、`visualize` 节点编辑；可作为点面颜色属性跟随几何体一起转换 |
| `alpha` | 透明度；数值仅为整数 0 或 1，影响渲染可视边缘，**无法转换为几何体边缘** |

### 1.2 特殊图层（与特定节点参数互动）

| 图层 | 生成来源 |
|---|---|
| `water` / `debris` / `sediment` / `bedrock` | 随 `erode` 节点生成（水/碎片/沉积物/基岩） |
| `flow` / `flowdir` | 随 `flowfield`、`slump` 节点生成（流动、滑落） |

用法：根据湿度层调整植被分布；用遮罩限制地形操作范围。

## 2. 核心节点速查表

| 节点 | 用途 | 输入端 |
|---|---|---|
| `Height Field` | 生成初始高度场 | — |
| `HeightField Blur` | 模糊高度/遮罩 | 1 高度 / 2 遮罩 |
| `HeightField File` | 图片灰度生成地形/蒙版 | 已有地形（图片作蒙版时） |
| `HeightField Pattern` | 斜坡/台阶/条纹/Voronoi 图案位移 | 1 高度 / 2 遮罩 |
| `HeightField Project` | 3D 几何体投影成山体或坑 | 1 地形 / 2 山体造型多边形 |
| `HeightField Flatten` | 展平遮罩区域 | 1 高度 / 2 遮罩 |
| `HeightField Isolate Layer` | 将某图层展平孤立至蒙版层 | — |
| `HeightField Layer` | 两图层混合 | 1 背景 / 2 前景 / 3 遮罩 |
| `HeightField Layer Properties` | 图层平铺 | 1 较大地形 / 2 特征地形 |
| `HeightField Layer Clear` | 用单一数值重置图层 | — |
| `HeightField Mask by Feature` | 按坡度/高度/方向特征做遮罩 | — |
| `HeightField Mask by Geometry` | 按几何体投影做遮罩 | 1 地形 / 2 参考几何体 |
| `HeightField Mask by Occlusion` | 凹陷/河床/山谷遮罩 | — |
| `HeightField Paint` | 画笔绘制高度/遮罩 | — |
| `HeightField Patch` | 特征自然缝合到另一地形 | 1 基本地形 / 2 特征地形+遮罩 |
| `HeightField Slump` | 松散材料沿坡滑落堆积 | — |
| `HeightField Resample` | 更改分辨率 | — |
| `HeightField Clip` | 高度值限制 min/max | — |
| `HeightField Cutout by Object` | 按几何体重定义地形边界 | 1 地形 / 2 几何体 |
| `HeightField Copy Layer` | 复制图层信息到其他图层 | — |
| `HeightField Crop` | 裁切长方形区域 | 1 地形 / 2 参考几何体边界 |
| `HeightField Deform` | 多边形沿地形表面移动 | 1 多边形 / 2 初始地形 / 3 实际地形 |
| `HeightField Noise` | 噪波增加地形细节 | 1 高度 / 2 遮罩 |
| `HeightField Distort by Layer` | 用一个场扭曲另一个场 | 1 受控场 / 2 控制场 |
| `HeightField Distort by Noise` | 噪声平流打破硬边缘 | 1 高度 / 2 遮罩 |
| `HeightField Draw Mask` | 套索绘制遮罩区域 | — |
| `HeightField Remap` | 重映射整体海拔及坡度 | 1 高度 / 2 遮罩 |
| `HeightField Terrace` | 斜坡转阶梯平台 | 1 高度 / 2 遮罩 |
| `HeightField Transform` | 地形整体缩放/偏移 | — |
| `HeightField Erode` | 热侵蚀+水力侵蚀 | 1 高度 / 2 遮罩 |
| `HeightField Erode Thermal` | 风化增强 | 1 带 Erode 图层地形 / 2 遮罩 |
| `HeightField Erode Hydro` | 水侵蚀增强 | 1 带 Erode 图层地形 |
| `HeightField Flow Field` | 生成流向图层 | — |
| `HeightField Scatter` | 高度场表面散布点 | 1 地形 / 2 遮罩 / 3 实例模型 |
| `Convert Heightfield` | 地形转多边形或体素 | — |
| `HeightField Quick Shade` | 为图层插入纹理 | — |
| `HeightField Visualize` | 高度/图层着色可视化 | — |
| `HeightField Tile Split` | 拆分为 a*b 块小地形 | — |
| `HeightField Output` | 高度/遮罩/层导出为图片 | — |

## 3. 节点实战细节与坑

### 3.1 Height Field（初始场）

- 初始范围为 1 立方千米，自动留有 10% 边缘余量；初始海拔为海平面。
- `Grid Spacing` 值越低，细节锐度越高；**建议手动输入数值，慎用滑块**。
- ![QQ20250310-185441.jpg](./图片/Houdini/QQ20250310-185441.jpg)

### 3.2 HeightField Blur

- 消除几何体转多边形时产生的锯齿。
- `Method` 参数的 `Expand`（扩大）、`Shrink`（收缩）可沿轮廓缩放受控地形区域。

### 3.3 HeightField File（图片生成地形）

- 将导入图片的灰度值转化为地形高度或蒙版。
- **建议导入前先对图片去色处理，平衡明度、对比度**。

### 3.4 HeightField Pattern

- pattern 图案参数基于平面纹理调节，**直接生成高度后锯齿较多、高差难以控制**。
- 建议使用遮罩层进行编辑，作为"局部细节"叠加到其他遮罩上。
- 每种图案类型的可编辑参数均不同，各有鲜明特征。

### 3.5 HeightField Project

- 勾选 `Supersampling` 设置新增地形表面噪波纹理，其密度与地形网格间距有关。

### 3.6 HeightField Isolate Layer

- 在展平高度时，需先将高度数值用 `HeightField Remap` 节点调整为 0~1。

### 3.7 HeightField Layer（图层混合）

- `Remapping` 中的 `scale` 值可设定各层的厚重程度。

### 3.8 HeightField Layer Properties（图层平铺）

- 边框类型通常使用 `Repeat`（重复）类型。
- **该节点效果不会单独显示**，需要结合 `HeightField Layer` 节点将图层混合到其他地形上。

### 3.9 HeightField Layer Clear

- 图层信息重置后，图层依然存在；一个节点可同时重置多层，被重置图层不影响其他层。

### 3.10 遮罩三兄弟

- `Mask by Feature`：不同特征的 ramp 曲线定义不同，可组合或复杂化 ramp 达到丰富效果。
- `Mask by Geometry`：`Method` 可使用烟雾、体素作为参考物体，**烟雾密度决定遮罩权重**；`Masking by Geometry` 可选择只投影"地面以上"或"地面以下"的轮廓。
- `Mask by Occlusion`：在空心/凹陷处（河床、山谷）创建掩膜；`Occlusion Ramp` 控制遮光采样细节，`ViewDistance` 控制遮罩强度。

### 3.11 HeightField Paint（画笔）

- 画笔效果**并非"雕刻"而是每个像素数值的累加或衰减**，上限值不易控制——不能光从视口效果判断笔刷强弱，也不宜反复厚涂。
- 绘制遮罩建议限定笔刷强度（`value`）在 0~1 之间。
- 绘制高度时：笔刷强度值每 +1 定义为"增高 1 米"，每 -1 定义为"下凹 1 米"。
- `Stroke Quality` 控制画笔每秒着色次数，影响线条连贯性。

### 3.12 HeightField Patch（特征缝合）

- 输入点 2 需带有遮罩信息，且遮罩信息会作为缝合遮罩被节点拾取。
- **节点运算较慢**；建议在输入地形前先调节好遮罩位置及特征局部；基本地形、特征地形使用相同的质量和尺寸。
- 缝合边缘的高度由【遮罩边缘所处基本地形位置的高度】决定。

### 3.13 HeightField Slump（滑落）

- 用于分层模拟沉积物、泥石流、融雪等细节。
- 对覆盖区域高度细节影响微弱、**对遮罩影响效果较大**——适合作为遮罩节点使用，为其他遮罩提供自然丰富的处理。
- 常用 `Slump Mode` 为 `Smooth`（平滑）模式；`Repose Angle` 可筛选受控坡度。

### 3.14 HeightField Resample（精细度）

- **减小采样对已生成的高度、遮罩效果有较大影响**；增加采样主要用于在后续节点中增加细节，对已生成信息几乎无影响。

### 3.15 HeightField Cutout by Object

- 通过拾取地形与几何体表面的交界线重新定义地形边界，制作**边界非长方体**的地形。
- 节点自动创建 `alpha` 图层记录截面信息；alpha 数值仅为整数 0 和 1（全黑/全白 → 透明/不透明）。

### 3.16 HeightField Copy Layer

- 主要用于**转换图层通道**；若要转换后与原通道**融合**、或同时**合并多个图层**，建议结合 `HeightField Layer` 节点。

### 3.17 HeightField Deform（模型贴地形）

- 常用于沿地形表面移动的动画：**动画预备阶段调好纵轴（y）位置和节点 2 的初始海拔**，使动画物体贴合地形表面；动画关键帧只在横向平面（x、z）设置。
- **可通过此节点制作道路和地形生长动画**。
- `Blur Radius` 调节地形采样。

### 3.18 噪波类

- `HeightField Noise`：**适合调节地形细节**；切换 `combine method`（混合方式）及 `noisetype`（类型），多个噪波节点串联组合出丰富效果；`Post Processing` 中的 `Gain`（增益）或 `Bias`（偏倚）调整噪波海拔。
- `HeightField Distort by Layer`：无法使用遮罩控制局部区域；扭曲效果难以预估；运行速度较慢。适用于为粗略地形添加其他地形的特征、轮廓或表面细节。
- `HeightField Distort by Noise`：适合**地形初建时调节整体造型**；可调节 offset 的 x、z 坐标寻找场景适用的扭曲分布。

### 3.19 HeightField Draw Mask

- 套索可同时框选多个区域；框选范围能与输入端已有遮罩值做**叠加、融合、减除**操作。
- 绘制套索时建议**开启地面吸附**功能。
- 每绘制一个区域，stroke 会自动添加一个操作层，可通过 stroke 管理已绘制的遮罩。

### 3.20 HeightField Remap

- 通过限定地形最高点和最低点，重新映射地形整体海拔及坡度。
- 可通过遮罩制作局部平地和孤峰；**调节局部时，建议将输出值控制在输入值区间内**；可用曲线调节对不同高度重采样的影响程度。

### 3.21 HeightField Terrace

- 节点只影响高度数值（`Min Height`、`Max Height`范围内的斜坡。
- 阶梯转换区域自动生成遮罩，同时生成底面区域（`Output Mesa Layer`）、悬崖（`Output Cliff Layer`）两个图层。

### 3.22 HeightField Transform

- 调整会**改变特征类节点的运算结果**（地形基准海拔、高度、边界等信息随参数变化）。
- 位移、缩放效果只作用于地形高度整体，**不能作用于局部或其他图层**。
- 多用于调节 `HeightField File` 导入后的初始模型参数，或用 `Height Offset` 滑块微调整体水平面。

### 3.23 侵蚀类

- `HeightField Erode`：功能型封装式节点；模拟雨水、土壤的自动山体侵蚀。**播放时间轴时自动迭代运算，选取最佳效果关键帧后勾选 `Freeze` 固定**。
- `HeightField Erode Thermal`（风化增强）/ `HeightField Erode Hydro`（水侵蚀增强）：输入点 1 需为**带有 Erode 配套图层的地形模型**；erode 节点本身参数照常运算，增强节点在其基础上影响某一局部特征的最终模拟效果。
- `HeightField Flow Field`：根据输入高度图层生成流向图层；可通过调整输入、输出所在层，改变流动层的影响范围，或使流动层与特定图层混合。

### 3.24 输出与渲染

- `HeightField Scatter`：见下节散布。
- `Convert Heightfield`：地形转多边形或体素。
- `HeightField Quick Shade`：可同时指定多个图层的贴图，图层重叠区域使用**编号靠后**的贴图；**只作用于视口效果及内置渲染器，不产生新图层**，效果不影响高度、遮罩、图层基本信息，因此**无法用常规方式导出混合加工后的贴图**。
- `HeightField Visualize`：着色效果不会对高度、遮罩、图层基本信息造成影响。
- `HeightField Tile Split`：将整块地形均匀拆成 a*b 块用于分组导出节约内存；每个单体有独立矩形 UV；**拆分后单体边缘会因格式转化或精度调整产生细节差异，重新拼合时会出现缝隙**。
- `HeightField Output`：将高度、遮罩、层信息写入图片 RGBA 通道；需逐个定义 RGB 通道含义及饱和度范围；图片尺寸、色彩模式直接影响细节精度。深度栅格格式（Houdini 格式或 EXR）可存储任意数量图层；常规图像格式通过 RGBA 打包最多存储 4 个图层。

## 4. 模型变低模

直接使用 `Convex Decomposition`（几何体）节点，将输入几何体分解为近似的凸段。

## 5. 散布（Scatter）

### 5.1 HeightField Scatter

- 输入点 1：地形；输入点 2：粒子范围遮罩；输入点 3：粒子实例模型。
- 取消勾选 `Match Normals with Terrain` 和 `Match Direction with Slope`（可以保留，树木的朝向），树木等模型就不会沿着地形进行弯曲。
- 通过 `Randomize Up` 和 `Randomize Yaw` 随机旋转模型增加随机性。

### 5.2 Scatter and Align

- 可以使用高度场里的 mask 属性在特定区域散布，然后通过 `copy to point` 将植被等替换上去。
- 如果是在 `Solaris` 中制作，只需要带入点，在点上加属性，在 Solaris 内部指定实例（见 Solaris 模块）。

## 6. 植被：Labs 树木工具链

> 需要使用 `SideFX Labs` 工具，安装 Houdini 的时候会提示是否安装。

### 6.1 快速造树

`Labs quick basic tree` 节点：在上方画曲线即可快速生成一棵树，叶子等元素也分组好了。
![QQ20250421-232505.jpg](./图片/Houdini/QQ20250421-232505.jpg)

### 6.2 tree_controller（控制树干）

- `noise` 窗口的 `Line Noise` 和 `Mesh Noise` 控制树干扭曲程度。
- `Meshing` 窗口的 `Intersection Behavior` 控制树干封口方式：默认布尔方式计算比较慢，**使用 `None` 方式会快很多**。
- `Resolution` 选项卡：树枝细分（更小则细节更多）。
- `Prune` 选项卡：修剪并删除树枝。
- `Displacement` 选项卡：应用纹理产生置换效果。
- `Meshing` 选项卡：修改每个树干的形态，`End Caps` 修改末端样子。
- `Tropis` 选项卡：
  - `Bend Along Parent`：控制影响树木弯曲程度的范围。
  - `Direction`：改变弯曲朝向。
  - `Thigmotropism`：触变性——树枝会避开移入的物体，改变树木生长轨迹。
- 需要远处树低分辨率、近处高分辨率：探索 `LOD` 和 `Visualization` 选项卡。

### 6.3 tree_trunk_generator（树干外观）

- `General` 窗口：`Length`、`Radius` 控制树高和树干粗细；勾选 `Randomize Length` 随机控制树干高度，`Randomize` 参数解锁可调。
- `Tropism` 窗口：控制树干弯曲；开启 `Override Tropism` 可控制树干弯曲方向绕过某个物体。
- `Trunk Shape` 窗口：控制树干根部粗细。
- `Noise`：树干表面噪波；`Meshing`：树干顶端封口；`Resolution`：细分；`Displacement`：位移（可放高度图等）。
- 可以添加一些线条节点等控制树干形态。
- 同名选项卡参数与 `tree_controller` 基本一致，**可用此节点覆盖 tree_controller 的参数**。

### 6.4 tree_branch_generator（枝干）

- `General > Placement`：`Branch nodes` 控制分叉枝干数量；在节点后再串联 `tree_branch_generator` 就是枝干再分叉，**越往后枝干越多**。
- `Length`、`Length Ramp` 控制枝干长度和长度在树干上的分布位置；`Angle Variation` 改变角度。
- **取消勾选 `Use Angle Ramp`，就只有枝干顶部可以有树枝**。
- `Radius`：枝干粗细。
- `Prune`：删除极端树枝、控制向光性、受重力影响等。
- `Tropism`：`Gravitropism` 重力、`Phototropism` 向光性。
- `Meshing`：`Enable Uv Blending` 启用 UV 混合，出现红色表示此顶点颜色可与两个 UV 集应用混合。

### 6.5 tree_leaf_generator / tree_simple_leaf（叶子）

`tree_leaf_generator` 在树枝上生成叶子：

- `Prune` 面板：`Random Threshold` 随机删除叶子；`Prune by Light Availability` 控制向光性。
- `Advanced` 面板：`Offset From Branch` 从父分支偏移叶子的距离；`Grid Behavior` 如何处理与栅格平面相交的叶片；`Normal Method` 计算叶几何形状法线的方法。

`tree_simple_leaf` 简单叶子生成器：

- `Size and Segments`：叶子大小和分段数。
- `shape`：叶子形状。
- `Point Jitter`：叶子随机性（点噪波）。
- `Color`：叶子颜色。

着色：使用 `Labs Quick Material` 节点快速上材质（笔记此处使用了 `Bridge` 里的材质）。

### 6.6 烘培树（Labs maps baker）

流程：`Grid` → `uvproject` → `Labs maps baker`。

- `Grid` 节点：打开正视图，参数 `Size` 要相同（确保正方形），`columns` 和 `rows` 为 `2`（细分）。
- `uvproject` 节点：`Initialize` 面板下点击 `Initialize` 按钮，自动适配 UV 到网格。
- `Labs maps baker` 节点：**接口 1 底模，接口 2 高模**。
  - `Max Trace Distance` 旁边勾选 `Visualize`，即可看见烘焙模型指定的描摹距离。
  - 目前所有颜色都是以顶点颜色存储的。
  - `Preview Channel`：视口中显示的通道。
  - `Generate` 生成的通道意义：

| 通道 | 意义 |
|---|---|
| `Vertex Color` | 顶点颜色贴图 |
| `AO` | 环境光遮蔽贴图 |
| `Thickness` | 厚度图 |
| `Curvature` | 曲率图 |
| `World Normal` | 世界法线图 |
| `Height` | 高度图 |
| `Range` | 非 HDR 文件格式时将高度重映射到 0-1 使用的范围 |
| `Alpha` | Alpha 映射 |
| `UV Fill` | Alpha 贴图生成显示 UV 外壳的蒙版，而非显示哪些像素属于有效追踪几何 |
| `Position` | 位置图 |

  - `Transfer` 的通道：`Diffuse Map` 漫反射、`Normal Map` 法线、`Opacity Map` 不透明度、`Roughness Map` 粗糙度、`Metallic Map` 金属。
  - 不透明度将效果映射到跟踪距离：启用后 baker 在跟踪高多边形时考虑不透明度贴图——例如在应用模板的情况下烘焙卡片几何体，且仅在 alpha 大于 0 时获得命中。
  - `Sample`：增加每个像素的采样。**此数字会增加 COP 中的渲染大小，可能超过 COP 允许的最大分辨率**；为避免此问题，请在 `Edit > Preferences > Compositing` 里的 `Cooking` 下增加分辨率限制。

### 6.7 批量生成不同版本的树

项目中需要很多不同的树时：

1. `Labs Tree Trunk Generator` 中用 `Min Length` / `Max Length` 限定树干长度。
2. 在 `Randomize` 中使用 `$F` 函数来随机树干。
3. 勾选 `Noise -> Line Noise -> Randomize Offset` 增加随机性。
4. `Labs Tree Branch Generator`、`Labs Tree Leaf Generator` 里的 `Randomize` 也可以这么设置。
5. 通过 `Labs Maps Baker` 烘焙出不同版本的树：使用 `Frames` 下的 `Frame Range` 控制数目数量（帧范围），**记得在名称中加入 `$F` 函数来区分不同的树**。

### 6.8 Solaris 中做树和树的材质

- Solaris 资产树、树叶材质、树干材质的节点网络截图见原笔记：
  - ![QQ20250619-175257.jpg](./图片/Houdini/QQ20250619-175257.jpg)
  - 树叶：![QQ20250619-175631.jpg](./图片/Houdini/QQ20250619-175631.jpg)
  - 树干：![QQ20250619-180743.jpg](./图片/Houdini/QQ20250619-180743.jpg)

## 7. 草 / 近景草

参考要素：**散落分布的石头、绿色为主体的绿草、干草、枯草、大石头、树枝、立起来的树枝干、落叶**。

分布规律：

- 草是**一簇一簇**地分布，比干草高一些。
- 干草整块垫在下方。
- 碎石也**一块一块**地聚在一起。
- 枯枝落叶散布不多，还有卷曲的草。

**把这些资产分布后合在一起就出来感觉了**。截图见原笔记：
![QQ20250304-173846.jpg](./图片/Houdini/QQ20250304-173846.jpg)
![QQ20250309-215616.jpg](./图片/Houdini/QQ20250309-215616.jpg)

## 8. 真实地形数据（DEM / OSM 工作流）

数据源：

- freegisdata：https://freegisdata.rtwilson.com/#elevation
- OpenDEM：https://www.opendem.info/
- OpenStreetMap：https://osm.mapplus.cn/export
- 路网和建筑数据：bbbike https://extract.bbbike.org/?lang=enosm
- 地形数据是网络上公开的 12.5 米 DEM（数字高程模型）。

> 注意：Mapbox 的变更导致 SideFX 无法继续支持 SideFX Labs Mapbox 工具，该工具已从今后所有 Houdini 版本中移除。

OSM 流程：

1. 打开网站，找到需要的地形，然后下载。
2. 导入 Houdini：
   - `osm_import` 节点导入 OSM 数据
   - `osm filter` 筛选出街道和建筑等
   - `osm buildings` 生成建筑
   - `split` 筛选出建筑细节，再通过 `split prim by normal` 筛选出更多信息
   - `road generator` 生成街道
   - `polyextrude` 挤出一些街道的高度等
3. 后期可以使用 `ray` 节点，将路网和建筑与地形对齐。

## 9. 在 Solaris (Karma) 里做环境

- 使用代理：导出后的模型都有 render 和 proxy 的变体。
- 在 `componentgeometry` 节点里，有完善的模型代理节点。

## 10. Labs Building 工具

有 A、B 模块，C 是 B 的变体。运算符：

| 运算符 | 含义 |
|---|---|
| `[A]` | 只放置 A 一个元素一次 |
| `<A>` | 放置 A 一直到结尾 |
| `<A-B>` | AB 交替放置直到结尾 |
| `<B*>` | 放置 B 一直到结尾，然后随机使用 B 的变体 C 来替换掉 B |

![QQ20251222-173931.png](./图片/Houdini/QQ20251222-173931.png)

## 易错点

1. **`Grid Spacing` 慎用滑块**——容易误拖导致精度错乱，建议手动输入数值。
2. **`HeightField Paint` 不是雕刻**：是像素数值累加/衰减，上限不可控，不能光看视口判断笔刷强弱，遮罩务必限制 value 在 0~1。
3. **`HeightField Resample` 减小采样**会严重破坏已生成的高度、遮罩效果；只做"增采样加细节"最安全。
4. **`HeightField Quick Shade` 无法导出混合贴图**——它只影响视口/内置渲染器，不产生新图层；要导出贴图需用 `HeightField Output`。
5. **`HeightField Tile Split` 拼合有缝隙**——拆分后单体边缘有细节差异，重新拼合时会出现缝隙，慎用于无缝大地图。
6. **`alpha` 图层只有 0/1 整数**，影响渲染可视边缘，无法转换为几何体边缘。
7. **`HeightField Isolate Layer` 展平高度前**，必须先用 `HeightField Remap` 把高度调成 0~1。
8. **`HeightField Pattern` 直接生成高度锯齿多**——应作为遮罩层的"局部细节"叠加使用。
9. **`HeightField Distort by Layer` 无法用遮罩控制局部**、扭曲难预估、运行慢——只适合整体添加特征。
10. **`HeightField Erode` 是随时间轴迭代的**——播放选最佳帧后记得勾 `Freeze` 固定，否则结果不稳定。
11. **`HeightField Transform` 会改变特征类节点的运算结果**——先 Transform 再做特征遮罩，顺序不能反。
12. **`HeightField Patch` 很慢**——输入前先调好遮罩位置与特征局部，两份地形保持相同质量和尺寸。
13. **烘培树 `Sample` 过高会超过 COP 最大分辨率**——在 `Edit > Preferences > Compositing > Cooking` 下提高分辨率限制。
14. **批量烘培多版本树**记得文件名加 `$F`，否则每帧互相覆盖。
15. **Debris Source / 散布树**：`Match Normals with Terrain` 等勾选项决定树木是否贴地形弯曲，按需求取舍。
