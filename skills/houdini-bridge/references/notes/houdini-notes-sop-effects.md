# Houdini SOP 建模与效果（学自用户笔记 Houdini.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Houdini.md` 的「SOP/360全景视频处理/一些效果」章节。
原始笔记保持只读；本文件是蒸馏版。截图见原笔记。

## 1. SOP 节点速查

### 基础物体

`line` 线 / `sphere` 球 / `box` 立方体（调高度贴地：全选 `Size y` 拖到下方）/ `grid` 网格面 / `tube` 圆柱 / `torus` 圆环 / `circle` 圆圈 / `platonic` 多面体 / `Bound`（连入生成 Bounding Box）/ `Labs Lightning` 生成闪电造型

### 组

- `Group`：按条件生成点/图元/边/顶点组
- `Group Promote`：组类型转换
- **用 Bounding box 精准筛选 Primitives 组**：关联一个 `Box` 的参数实现

### 曲线

- `spiral`：蚊香曲线；`helix`（由 Spiral 演变）：弹簧，还可给 pyro 做速度场
- `curve` / `Draw Curve`：画曲线
- `resample`：重采样为等长段（变点）；**分支曲线 resample 后分支点处断线**
- `Join`：多条开口曲线首尾相连
- `Poly Bridge`：连接选定的 2 个边或点
- `PolyFill`：补洞
- `Circle from Edges`：不规则边变圆

### 点线面 / 属性

- `extractcentroid` / `Extract Centroid`：提取质心（每部分质心处创建点）
- `Sort`：重排点序号（含随机）
- `Peak`：沿法线移动点线面
- `Facet`：控制曲面平滑；勾 `Post-Compute Normals` 计算法线（`N` 在 Point 层级，模型更平滑）
- `Normal`：算法线（`N` 在 Vertex 层级）
- `ray`：投影到另一表面（小面投大面效果最佳）
- `Connect Adjacent Pieces`：碎片间连线（约束网络）
- `Connectivity`：每组连通基本体/点生成唯一值属性（默认 `class`，0 到 sets-1）
- `comb`：笔刷引导法线方向
- `reverse`：反转 UV/面
- `bend`：扭曲模型
- `Distance along Geometry`：沿几何体边/曲面测最短路径（用 center_mask 属性，从 edges Group 开始测）
- `Distance from Geometry`：每点与参考几何体的距离
- `Labs Measure Curvature`：凸=绿、凹=红
- `Points From Volume`：填充体积的规则点（粒子场/初始化）
- `Trail`：点后创建尾迹（`Result Type`: Preserve Original / Connect as Mesh / Connect as Polygons / Compute Velocity）；连线时点序号要稳定，复杂连线用 add 或 VEX

### 转换 / 生成

- `Convert`：几何类型转换（**导入模型布线不对时全转 polygon** 再细分/上材质才正常）
- `Convert Line`：转线段（Bezier 曲线先转它才能 PolyWire）
- `Quad Remesher`：三边转四边；`remesh` / `Poly Reduce` / `Labs Fast Remesh`（分区并行）：减面
- `Revolve`：曲线绕轴旋出曲面
- `trace`：黑白图（或带 alpha）上建立拓扑生成立体模型
- `Poly Wire`：曲线生成 mesh（只能 polygons 线）
- `triangulate2d`：2D 三角化
- `Divide`：转三角面
- `Convex Decomposition`：高模转低模凸面体（低分辨率碰撞体）
- `Assemble`：清理模型与 break 操作
- `Point Cloud Surface`：点云四边形重构（大规模地形扫描）
- `Labs Straight Skeleton 3D`：中心线（pyro 的 scatter+连接临近点+resample 更快）
- `Topo transfer`：高解析扫描数据转低解析可渲染网格（光流变形匹配姿势）
- `Create LOD`：PolyReduce 自动生成多 LOD 存 USD 变体
- `21 新增`：`Neural Point Surface` 机器学习工具（部分场景可替代 VDB）

### 模型处理

- `Fuse`：焊接未闭合模型；`Clean`：融合位置相近的点、删属性/点（勾 `Fix Overlaps` 清除重叠面）
- `mirror` / `Smooth` / `Twist` / `split`（分两半）
- `clip`：裁剪平面一侧几何
- `Flatten`：3D 几何展平到平面
- `Poly Hinge`：绕枢轴拉伸面（可动 90°）
- `crease`：手动加/删折痕权重（细分 SOP 用）
- `Labs Thicken`：挤出厚度（封装 Poly Extrude + Group）
- `Copy and Transform`：类 Blender 阵列修改器
- `Soft Transform`：类 Blender 衰减编辑（周围点按距离比例移动）
- `Labs Align and Distribute`：对齐排列成线性/网格（平替 Match Size）

### UV

- 组合链：`Labs Auto UV` → `UV Auto Seam` → `UV Flatten` → `UV Layout`
- `UV Project`（Projection 选投影形状；`U/V Range` 改拉伸）/ `UV Texture` / `UV Quick Shade`（快速测 UV）
- `UV Flatten from Points`：容易 UV 重叠
- 传递 UV：`remesh` 勾 `Harden UV Seams`；或 `Labs UV Transfer`

### VDB / 体积

- `VDB from Polygons`：模型转 VDB（`Voxel Size` 控精度）
- `VDB Smooth SDF`：平滑
- `Convert VDB`：转回其它类型
- `VDB Activate`：激活体素区域
- `VDB Vector from Scalar`：三标量 VDB 合矢量（须同分辨率同变换）
- `Labs Loop Volume`：无缝循环体积动画
- **VDB 重布线原理**（自制 Remesh_Polygons_by_VDB）：VDB from Polygons → Convert VDB → Poly Reduce

### Stash：模型存进 hip

- 点击 `Stash input` 缓存输入几何进节点（删掉上游也能用）；断开输入再点 = 放弃缓存
- **不能保存带动画的**
- `Move Stash to New File` 外置减小 hip；`Load Stash from File` 加载回来

## 2. 建模操作技巧

- Obj 环境右键物体坐标轴中心 → `Start Orientation Picking` 拾取中心轴到指定位置；右键勾 `Pivot Mode` 后中心点可自由移动，取消勾选锁定
- `M` 切换本地/全局坐标轴；`Shift + "` 调坐标轴中心位置
- 连续选面：按 `A`；选点长按 `A` 出现黑边按中键全选；按 `H` 后 `Shift+H+中键` 选边中间内容
- `j` 键绘制路径自动连接节点（多输入时画哪边连哪边）
- 视图居中：`F` 主物体 / `G` 原点

### 案例：激光

`Tube` 当激光笔（带动画一端缩小，否则投影一半前景一半后景出 bug）→ 保留发射口模型面 → `ray` 投射到背景 → 发射端/被投射面给不同 `name` + `extractcentroid` → merge 后 `add` 连两点 → `polywire` 转模型

### 案例：苹果

`Curve` 画轮廓 → `revolve` 旋转 → `convert` 转 polygon → `fuse` 焊接 → `bend` 扭曲 → `UV project` 圆形投影

## 3. 散步 / 实例（SOP 级）

- `Scatter and Align`：Scatter 增强版（点上加 orient/scale 属性）；性能瓶颈在保持分布间隔、Avoid Constraint Points、Relax Iterations
- 删模型保留点：`add` 节点
- 排一条线的点：模型参数 `Primitive Type` 选 `Points`
- `Layout` 节点：笔刷式散步 USD 资产（单个放置/画笔散布/编辑实例）
- `Dop Import Field` 碎块导出注意：不能直接导碎块，**要导点来驱动**（导破碎一定导点驱动）
- 快速散步资产（LOP）详见 render-io 笔记的 instancer 章节

### 撒点密度控制（噪波密度图，通用套路）

- `pointvop`：P 连 `Turbulent Noise` 的 pos（`Turbulence` 设 0 更平滑）→ `fit` 缩放到 0-1 → `ramp` 平滑边缘过渡 → 输出 Cd
- ramp 参数会在 pointvop 节点层级暴露，在外部调过渡范围
- 有模型的位置要把 Cd 涂 0：`Attribute Paint`（值设黑色再画）
- `scatter`：关 `Relax Iterations` / `Max Point Limit`，勾 `Density Attribute` 用 Cd，`Force Total Count` 控总数
- `Attribute Randomize` 给 `pscale` 用 `Exponential` 分布（Middle Value / Min / Max Limit）更接近现实
- `Attribute Delete` 删 Cd；wrangle `@N = {0,1,0};` 保证法线朝上
- `Scatter and Align` 的 `Mode: Add Attributes to Existing Point Cloud` 只加属性不建点（输入 1=散点表面，输入 2=约束点）；`Orientation` 下 `Max Random Cone An...` 往法线两边倾斜，`Min/Max/Offset Angle` 沿法线旋转

### 粒子渲染大小（两条路）

1. 粒子节点树末端加 `attribute create`（设 pscale）
2. Object 层 geometry 节点上直接设点大小

## 4. 沿曲线运动

- 方法一（同 Geo 层）：`resample` → `Path Deform`（`Capture and Align` 窗口参数不影响性能，`Capture` 别关）；`Chain` 节点（18.5+）沿曲线自适应摆放
- 方法二（Follow Path 工具架）：选物体回车 → 选曲线回车 → 选 look-at 对象回车（无则直接回车）→ 选 look-up 对象回车（无则直接回车用默认/无对象）
- 后两个没有就直接回车跳过

## 5. 实用效果速查（Labs）

| 效果 | 节点 |
|---|---|
| 模型破损 | `Labs edge damage`（边缘磨损） |
| 电线 | `Labs Cable Generator`（Simulation 选项卡选动力学垂下效果；输入 2 连碰撞体） |
| 积雪 | `Labs Snow Buildup` |
| 自动旋转展示 | `Labs Turntable`（连模型末端，调转速） |
| 闪电模型 | `Labs Lightning` |
| 缠绕绳索 | `Labs Simple Rope Wrap` |

### Labs Simple Rope Wrap 参数细节

- 输入 1：缠绕的地方（与输入模型有交集处都生成缠绕线）
- 输入 2：被缠绕的模型
- 输入 3：缠绕线形态曲线（`Style` 选 Custom 时启用）
- `Resolution`：分辨率受重力影响
- `Optimize Curves`：只在受弯曲影响处布线（`Tolerance` 容差决定删点）
- `Simulation`：做 vellum 模拟
- `Optimize Surface`：四边面转三边面

## 6. 贴花 / 破洞修补

### 贴花（材质/模型贴合目标对象）

- 首选 `MtlX overlay` 混合材质（详见 shading-lighting 笔记）
- `Labs Decal Projector`：Project 模式投影贴图；Place 模式撒点散步贴花模型（`decal_index` 属性一一对应）
- `ray` 节点投射：仅限单片高细分面模型

### 修补裂缝破损的面

- 方法一：`Group`（选修补处点编组）→ `fuse` 缝合生成新面 → 套 `For-Loop with Feedback` 迭代至填满
- 方法二（只缝内部不缝外部）：编组缝合点 + 编组缝合边 → `Labs Edge Group To Curve` 边组转曲线 → `blast` 删最外面那条曲线（反选）→ 排除后重新编组 → `fuse` → For-Loop 迭代 → `boolean` 修重合面

## 7. 其它高频技巧

- `Time Shift`：时间冻结
- 关键帧抖动：参数右键 `Motion FX -> Noise`（chopnet 调曲线）
- `Extract Transform`：继承物体旋转位移生成点，copy 上去
- 模型摆正：`transform` 移到世界中心 → `Labs Straighten`（`Up Group` 选 y 轴面、`Forward Group` 选 x 轴面）
- 渲染粒子过大：粒子树末端加 `attribute create`，或在 Object 层 geometry 节点上设点大小
- `Fetch` 节点：建立指向其它网络 ROP 的依赖，获取渲染/缓存
- `Labs File Cache`：带 wedge 楔形功能
- hiplc → hip 转换、隐藏节点调用（`opunhide Sop fluidsource`）见 basics 笔记
- 解包模型：`unpack` 暴露原始点/面/全部属性但性能下降——不必解包时可打包后对点操作驱动模型
- 抖动：`noise(X, Y, Z)` 函数
- 动作捕捉：官方 `kinefx--mocapstream`
- 跟踪点（空对象）实体化：前提是空对象命名顺序有规律
- 反求相机后绿幕贴 grid：直接贴即可
- 改变场景尺寸单位：单位设置面板
- Modeler 插件安装：modeler + packages 文件夹复制到用户偏好目录（Windows: `Documents\houdini20.5`），删 `config/Icons` 图标缓存，运行后添加 Modeler 工具架组并保存桌面

## 8. 360 全景视频

- **Mantra**：直接支持全景序列渲染
- **Karma**：20 版本以后才有全景渲染支持

## 易错点

1. **`ray` 投射前先缩小投影源模型一端**：否则投影一部分在前景一部分在后景出 bug
2. **PolyWire 只吃 polygons 曲线**：Bezier 先过 `Convert Line`
3. **resample 断分支**：分支曲线 resample 在分支点处产生新点断线
4. **Stash 存不了带动画的几何**
5. **trail 连线要求点序号稳定**：复杂连线改用 add 或 VEX
6. **unpack 性能代价**：不是所有模型都要解包——打包状态下对点操作也能驱动模型
7. **`UV Flatten from Points` 易 UV 重叠**
8. **remesh 减面会丢 UV**：勾 `Harden UV Seams`
9. **模型布线不对先 `Convert` 全转 polygon**，否则细分/上材质不正常
10. **蜕变模型（Degenerate Primitives）导致渲染极慢**：先清除
