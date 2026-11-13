# 跨软件跟踪与交接 Pipeline（学自用户笔记 跟踪擦除.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\跟踪擦除.md` 全文（约 1600 行）。
原始笔记保持只读；本文件是蒸馏版——跟踪基本理论 + PFtrack / SynthEyes /
3DEqualizer4 / Mocha / AE / Silhouette 各软件工作流要点，以及与 Nuke 的交接格式。
与 `tracking-and-stabilization.md`（Nuke 内 Tracker/CameraTracker）互补，不重复。

> 用户真实 pipeline：**跟踪软件反求 → Nuke 合成擦除**。跟踪软件是上游，
> Nuke 是下游合成端；交接物 = 相机（.py / .nk / usda / fbx）+ 畸变数据 + 模型 + exr 序列。

## 0. 跟踪基本理论

- **原理**：跟某一个物体（或人、摄影机）的运动轨迹——它怎么动，我们就怎么动。
  两条轨迹重合度越高，跟踪精度越高。
- **影响准确度的因素**：
  - 素材像素模糊（原因：相机运动过快、灯光变化大）
  - 相机运动单一、场景无深度信息（原因：相机原地旋转、环形运动拍摄）
- **现场技巧**：跟踪不稳的镜头可以用慢动作拍，最后再加速。
- **标准跟踪流程**：
  1. 导入素材并检查素材
  2. 解算摄像机路径
  3. 跟踪运动物体
  4. 优化摄像机解算结果
  5. 导出到三维软件匹配并检查结果
- **接戏问题**：不考虑接戏可用一个场景做跟踪；要和别的镜头接戏（画面在同一地点）
  就得**统一场景**——用客户提供的扫描模型 1:1 匹配素材（用户举的"红海"案例）。

### 跟踪类型速查

| 类型 | 别名 | 特点 | 适用 |
|---|---|---|---|
| 变换追踪 | Transform Tracking / Matchmoving / 点跟踪 | 2D 空间，X/Y 运动；两点可测旋转缩放 | 大多数软件的简单追踪器 |
| 转角固定追踪 | Corner-Pin Tracking | 4 个追踪点，检测矩形透视/旋转变化，扭曲元素匹配 | 矩形物体（屏幕、招牌） |
| 稳定处理 | Reverse Stabilization | 变换追踪分析相机运动后反向稳定素材 | 画面稳定 |
| 3D 摄像机追踪 | 3D Camera Tracking | 最复杂，三维空间重建相机属性 | X/Y/Z 三轴都有运动的镜头 |
| 平面追踪 | Planar Tracking | 追踪整个平面特征，边角出画/遮挡仍可工作 | 透视+视差变化的平面 |
| 网格扭曲追踪 | Mesh / GridWarp Tracking | 细分表面检测运动 | 衣服、皮肤、旗帜等有机表面 |

（各类型配图截图见原笔记）

### 跟踪标记（现场）

- 标记尺寸：每张打印 20×30 英寸，可裁 16 个 5 英寸标记或 32 个 2.5 英寸标记，
  用**非光面纸**打印，贴自粘泡沫芯板（黑白版用黑芯，蓝绿幕版用白芯+蓝绿漆刷边）。
- 模板是黑白的，注意前景主体和旋转问题。
- 脸部跟踪的跟踪点**可以用点代替**。
- 蓝绿幕棚拍摄更多采用**红色和浅绿色标记**（考虑后期擦除难度）。
- 截图见原笔记（标记模板、实拍现场）。

### 反求时最好拿到的片场数据（3P 原则：Planning, Planning, Planning!）

- 相机位置及运动、相机/镜头型号参数数据
- 现场物体尺寸（放已知物理尺寸的参照物，如砖块）
- 灯光位置、环境中各种物体信息（辅助判断相机位置是否准确）
- 拍完正片后**再拍一段测量镜头**（视频或多角度照片），用于解析获取物体准确形状
- 多机位辅助：一个主镜头 + 多个不同角度固定机位同时拍，交叉确定物体位置
- witness cam（动作捕捉用相机）
- 截图见原笔记（现场记录表、跟踪点分布图）

### 物体跟踪（Object Track）要点

- 挑战：形状、尺寸与深度、变形。
- 技术路线：先 solve cam → 再 solve obj → apply survey → determine scale。
- 方法 a：直接把物体当作运动物体解算（solve obj as a moving obj）。
- 方法 b：把物体当作另一台相机解算，然后**反转运动**（reverse the motion）。

## 1. 畸变矫正与 Nuke 交接（重点）

准确还原畸变后的画面才能跟踪准确。两种常见畸变：枕形畸变、桶形畸变。

### 通用 pipeline

- `LensGrids`：拍棋盘格 → `LensDistortion` 矫正 → 采集摄像机 UV 变形图像（`UVMap`）
- `Shots`：所有素材经 UV 矫正（`STMap / UndistortShot`）→ 跟踪（`Matchmoving`）
  → 三维内容与渲染 → 合成后变形回去（`STMap / ReDistorShot`）→ 最终合成（`Merge / FineShot`）
- 没有棋盘格时：对场景中**直线物体**分析求畸变。
- 棋盘格也可对着屏幕直接拍。

### 拍摄棋盘格规范

- 打印在坚硬表面（哑光饰面），足够大覆盖整个相机视野；保持水平（手机 App 检测）。
- 对齐方法：中心点在画面中间，周围四个点与十字匹配；相机保持水平。
- 打光使棋盘格明亮、对焦清晰（可用焦点图）。
- **每个镜头放一个打板**，写上镜头焦段信息，避免后期不知道用什么镜头矫正。
- 棋盘格黑白即可；怕曝光问题把白色改为灰度 `0.18`。
- 截图见原笔记（网格图样式、夹持方式）。

### Nuke 畸变还原（笔记中的 Nuke 重点内容）

**获得矫正数据（LensDistortion 节点）**：

- `Solve Error` 参数到 `1` 以下就是比较好的结果。
- 修改跟踪点细节前，先关掉 `Analysis` 选项卡里的 `Preview`。
- 检查对齐：`LensDistortion` 选项卡 `Mode` 从 `Undistort`（矫正后）改为
  `STMap`（矫正前），查看图像中哪条线没对齐再矫正。
- `Lens Type`：`Spherical` = 球面镜头，`Anamorphic` = 变宽镜头。

**渲染 STMap**：

- `Mode` 选渲染 STMap（截图见原笔记）。
- 通道选 `all`（也可只渲染 `motion` 通道）；文件类型 `exr`；色深 `32 bit float`。
- 可写脚本：渲染完直接把结果作为 `Read` 节点建出来。

**还原（去畸变给跟踪/三维部门）**：

1. `BlackOutside` 节点：把边缘拉伸去掉变成黑边。
2. `C_STMap` 节点（GPU 加速），`Map` 参数选 `stmap -> forward` 修复畸变画面。
3. `Crop` 节点：把画面展开到框外的数值填入 `box`，恢复无畸变画面尺寸。

**恢复畸变（畸变回套）**：

1. `Reformat`：将图像恢复原尺寸。
2. `Transform`：将图像位置移回原位置。
3. `C_STMap` 节点，`Map` 参数选 `stmap -> backward` 应用畸变。
4. `Crop` 节点：点 `Reset` 按钮将 bbox 恢复到原画面尺寸。

> 工具：H_ReDistort & GeoTracker（网盘链接见原笔记）。

## 2. PFtrack

### 注意事项

- 地面跟踪点很重要，不要忽略。
- **跟踪到移动物体的点都要删除**。
- 删除东西要**点两次 delete**（第一次删除，第二次确认）。
- 拖入素材：随机选一帧拖入节点面板即可。
- 不同跟踪数据（一个跟踪环境、一个跟踪物体）必须在 `Current group` 里用
  **不同的组**，否则跟踪点混用。
- 按着 `Ctrl` 可整体移动蒙版。

### Auto Track 节点参数

| 参数 | 作用 |
|---|---|
| `Candidate number` | 每帧寻找的潜在跟踪点数量 |
| `Target number` | 在候选基础上实际保留多少个跟踪点 |
| `Min. length` | 跟踪点最少连续存在多少帧 |
| `Search Mode` | `Better Speed`（默认快）/ `Better Accuracy`（最准）/ `Optical Flow`（质量速度平衡） |
| `Deformation` | 是否考虑跟踪点变形（`Rotate / Scale / Skew`） |
| `Back-track` | 直接选上 |
| `Spread` | 让跟踪点扩散开不堆积 |
| `Blur Image` | 噪点多的镜头先模糊减噪 |
| `Illumination` | 考虑照明变化 |

- 列表下方：`R-` 删时间线左侧跟踪数据；`Remove Key` 移除当前关键帧；`R+` 删右侧。
- `Merge` 合并选中跟踪点为一条；`Split` 删除选中点之后的跟踪信息。
- `Export` / `Import`：同一节点跟踪数据可跨素材复用。

### User Track 节点

- 跟踪点出画后再出现：选中该点，在物体再次出现的地方点一下鼠标左键即可接回。
  **所有帧必须跟踪在同一位置**。
- `Channels`：点不清晰时选 R/G/B 单通道跟踪。
- `Tracking offset`：按 `Ctrl` 拖动该点，用别的位置信息延续跟踪。
- 十字点颜色：**红 = 不确定无跟踪信息；绿 = 跟稳（不一定准确）**。
- `C`：自动寻找跟踪内容中心。
- **跟踪完一定要选 `H-` / `H+` 或 `Hide`**（该点在往后的帧不活跃，时间线棕变灰）；
  不选则软件认为该物体在轨迹外一直停在原地。
- `Polish`：微调当前帧；`K-/K+` 关键帧间切换；`<`/`>` 单帧跟踪；`<<`/`>>` 跟踪到不能跟。
- 时间线 `Step`：方向键一次跳几帧——不好跟踪时手动跳帧引导，**遮挡时很好用**。

### Camera Solver 节点

- 勾选 `Set initial frames automatically` 自动定初始/结束帧。
- `Distortion` 标签：`Low-order` 右边勾选 `Estimate` 自动估计畸变。
- `Camera` 标签：`Focal Length` 焦距——解析差距大且跟踪信息没问题时改焦距。
- `Errors` 标签：`Trim` 勾选出现黄线，黄线以上不参与解算，再点 `Refine All`。
- `Solver Log` 标签：`Error` = 误差像素值（笔记示例 2.01 像素）。

### Oriant Scene（定场景坐标/缩放）

- `Marquee` 框选点 → `Set plane` 设所在平面（如 `Y-Z Plane`）。
- `Distance`：选两个点设真实距离 → **缩放整个场景尺寸**。
- 轴颜色：红 X、绿 Y、蓝 Z。
- `Edit mode` 工具：`Translate / Rotate / Scale / Axes`（用三条线对齐画面中明显线条来定轴）。

### PFtrack 建模与物体跟踪

- 建模流程：`PhotoSurvey`（导相机数据 → `Auto Match` → `Solve All`）→
  `Orient Scene` 放世界坐标 → `Photo Mesh`（`Create` 建点云 → Mesh 面板 `Create`
  建模型，`Resolution` 控制精度 → `Export Mesh` 导出）。
- 物体跟踪双节点流（截图见原笔记）：
  - 场景流：`User Track -> Camera Solver` 得运动相机；固定机位用 `Edit Camera`。
  - 物体流：`User Track -> Camera Solver` 得运动物体；
    或 `User Track -> Edit Camera -> Camera Solver`（先 K 大致运动再反求，更准）。
- 人脸跟踪：`Geometry Track` 节点导入模型、视觉对齐后逐帧跟踪（光照/遮挡易出错）。
- 有用节点：`Undistort`（矫正）、`Texture Extraction`（上材质）、
  `Image Manipulation`（调亮好跟踪）、`Transform Clip`（改/查分辨率）。

### PFtrack 360° 全景跟踪

`Spherical Track`（跟踪+解算，可画遮罩规避移动物体；`Inlier Threshold` Low 最严）
→ `Orient Scene`（6 机位视角选点定地平面，X-Z 是地面）→ `Spherical Orient`
→ `Test Object` 放测试模型验证 → `Spherical Render` 看效果 → `Export`
（**生成 6 个摄像机视角给三维软件**）。

## 3. SynthEyes

- 场景中加任何东西都用同一个"添加"按钮（物体、跟踪点等）。截图见原笔记。
- **至少一帧要有 9 个跟踪点才安全**。
- 时间线红色 = 没有关键帧。
- 快捷键：`空格` 播放（Track 面板里边播边自动跟踪）；`Shift+C` 清理跟踪点面板；
  小键盘 `8/4/2/6` 微调点位置；`←/→` 逐帧；`↑/↓` 切换选中跟踪点。

### 素材预处理（Edit Shot -> Image Preprocessor）

| 面板 | 关键参数 |
|---|---|
| `Rez` | `DownRez` 降分辨率、`Interpolation` 插值、`Channel` 跟踪用通道、`Channel Depths` |
| `Filtering` | `Blur` 消噪点干扰；`Hi-Pass` 高通滤波突出边缘（跟踪小黑点方便）；`Noise reduce` 降噪但变糊不好用 |
| `Color` | `3-D Color Map` 套 LUT；`Level Adjustment` gamma/亮度/对比度；`Hue / Saturation / Exposure` |
| `Stabilize` | 手动加跟踪点稳定素材 |
| `Cropping` / `ROP` | 裁掉 / 遮挡不解算的区域 |
| 右侧 `Checklines` | 加参考线检查素材是否扭曲 |

### 各面板要点

- **Lens（镜头矫正）**：可自动分析畸变；`Add Line` 拖直线辅助矫正——只矫正畸变选
  `Not oriented`；`Parallel to X Axis` 定义平行轴向；`On X Axis, with length`
  定义轴向+真实长度（场景大小随之改变）；`Kill Line` 删线。
- **Features（特征点）**：选相机运动模式 + 神经网络找点；`Blips this frame /
  playback range / all frames` 加 blip 点；可框选范围 + `Maximum Tracker Count`。
- **Solver（解算）**：`Automatic` 可切模式；删点后选 `Refine` 再点 `Go` 优化当前结果
  （**否则每次点解算都从头重算**）；`Calc. Distortion` 解算时自动分析畸变。
  **解算成功标准：右下角有跟踪信息且准确度控制在 1 以下**。
- **Roto**：`Garbage`（红框）= 垃圾遮罩不分析；`Camera`（蓝框）= 要分析的区域。
  `Import Tracker to CP`：先选跟踪点 → 点按钮 → 点 Roto 中心点，让 roto 跟随跟踪点
  （`yes` = roto 原位跟随；`No` = 中心点移到跟踪点上）。
  做好 roto 后把 2 个 alpha 数值拉到 255。流程：做完一段 roto，切下一段移动 roto 直到完全挡住。
- **Trackers**：最外层正方形 = 跟踪**范围**，最里层 = 跟踪**特征**。
  手动跟踪完的点要**锁定**，否则下次手动跟踪新点时它还会参与。
  合并两个同位跟踪点：`Shift` 多选 → 右键 `Combine trackers`。
  `Now` 设当前帧为关键帧；`Weight` 解算权重；`Exact` 强行把 2D 点设到三维位置。
- **Coordinates（世界轴）**：点 `*3` 依次选 轴心点 → X 正方向 → Z 正方向。
- **3-D 面板**：可加测试模型（`Earthling` = 人）；右键菜单 `Whole affects meshes`
  让旋转影响所有跟踪点和物体。

### 导出（File -> Export）

- **Maya**：选 `Maya ASCII Updated`，单位选 `Meters`。
- **Nuke**：选 Nuke 导出格式（截图见原笔记）；时间线不符可在导出面板移动关键帧对齐。

### 物体跟踪

1. 正常解算好世界坐标后，`Shot -> Add Moving object`，确认 `Active Tracker Host`
   是 `Object1` 模式。
2. 技巧：`Shot -> Create Lens Grid Trackers` 自动创建一批跟踪点。
3. 解算；**解算数值为 0 说明跟踪点不够多**。

## 4. 3DEqualizer4

- **每一帧起码 6 个跟踪点才安全**。
- 解算快捷键 `Alt + C`（`Calc -> Calc All From Scratch...`），解算完点 `Use Result`。
- 窗口不见了去顶部 `Config` 找；缓存文件是 `3de_bcompress`。
- 环境布局：`Enviroment -> Basic` 开始干活。
- 四种跟踪模式切换：`Manual Tracking Controls`（手动，按 `Ctrl` 加点）、
  `Distortion Grid`（畸变矫正）、`Autotracking Controls`（自动）、
  `Lineup Controls`（对齐，配 `Center 2D` 看哪个点跟得好）。

### Autotracking Settings 参数

| 参数 | 作用 |
|---|---|
| `Active Points/Frame` | 每帧跟踪点数量 |
| `Minimum Track Length` | 每个跟踪点最小跟踪长度 |
| `Search Interval` | 每多少帧添加一次跟踪点 |
| `Search Area Size` | 特征点探测区域大小 |
| `Pattern Size` | 特征点区域 |
| `Minimum Distance` | 跟踪点间隔距离 |
| `Compensate Luminance Changes` | 画面闪烁时勾选优化 |

- 遮罩：`Spline Mask Enabled` 画 roto（`Add Mask` 生成；`Alt` 选点、`Ctrl` 加点；
  `Invert Spline Mask` 反转）；`Image Mask Enabled` 导入外部 roto。
- 画面颜色：红 = 新产生的点，黄 = 之前跟踪的点，粉 = 第二次跟踪消失的点。
- aces 等色彩空间素材太暗：`Camera -> 8 Bit Color Conversion -> Gamma` 调 `2.2`。
- `Lens -> Pixel Aspect`：变宽镜头像素宽高比（如 1.5X 镜头填 1.5）。

### 手动跟踪

- `Ctrl` 点击加点；点中间方块 = 跟踪信息，最外方块 = 跟踪范围。
- `Track` 向后跟（再点停止）；`Ctrl + Shift` 往前跟；`<`/`>` 单帧。
- `Center 2D` 锁定视图居中；`End Point` 该点后续帧不参与计算；`Remove Key` 删关键帧。
- `Trackingmode`：`Pattern`（默认点跟踪）/ `Marker`（绿幕标记点）/ `Edge/Corner`（少用）。
- 时间线颜色：深色 = 参与跟踪；更深 = 手动 K 的帧；更浅 = 计算机猜测；灰色 = 不参与。

### 基本流程（项目实战版）

1. **准备**：`Basic` 环境 → 导入序列 → `Lens` 面板调相机参数（必须调）→
   `Camera Constraints` 设运动约束（`No Constraint / Fixed Camera Position /
   Plane / Line / Circle Movement Constraint`）。
2. **跟踪**：自动（必要时加 mask 挡移动物体，软件默认正反各跟一遍）；
   坏点切手动面板 `Ctrl + Alt` 框选 → `delete`。
3. **解算**：`Alt + C` → `Use Result`；右下角绿色数字 = 错误率，越小越好。
4. **优化**：
   - 删点重算（错误率如 0.7910 → 删点再算）。
   - `Parameter Adjustment`：`Focal Length` 改 `Adjust`，`Distortion - Degree 2`
     第一个选上 → `Adaptive All` → `Adjust...` 到结束 → 重新解算。
   - `Find Badly Tracked Points...`：`Error Threshold` 阈值选点，`Evaluate`
     选自动/手动/全部，`Resulting Points` 决定删除还是仅选中。
   - `Triangulate Points v1.2`：解算好后手动加个点 → 点击映射到三维空间。
5. **定场景坐标**（1 点定原点 → 2 点定 Z 轴 → 3 点定地平面）：
   - `Edit -> Move 1 Point To -> Origin`
   - `Edit -> Move 2 Points To -> Z`
   - `Edit -> Move 3 Points To -> XZ Plane`
6. **测试**：`3D Models -> Create` 放模型 / `Mesh From Points` 从点云建模，
   回 `Overview` 面板播放验证；位置不对用 `Scale` 缩放；`Alt+S` 点吸附到模型。
7. **导出**：见下方交接表。

### 变焦镜头与畸变矫正

- 变焦镜头错误率曲线基本是 **V 字形**（需修复，理想是中间线保持平坦）。
- 畸变矫正流程：拍方格图 → `Distortion Grid` 面板把点匹配到方格（`Ctrl`+方向键
  Snap；坏点 `Disable Points`）→ `Lens` 选项卡选失真模型 → 顶部
  `计算失真/相机几何体...` → `Calc Lens Parameters` → `Set Parameters & Close`。
- 失真模型选择：
  `3DE4 Radial-Standard Degree 4` / `Radial-Stabilizer Degree 6` /
  `Anamorphic-Standard Degree 4/6` / `Anamorphic-Rescaled Degree 4/6` /
  `Anamorphic-Stabilizer Degree 6` / `Classic LD Model` / `Radial-Fisheye Degree 8`。
- **3DE 官方镜头畸变插件套件**可把 3DE4 失真参数导出、导入 Nuke（生成 Nuke 节点）。
  导出畸变数据给 Nuke 的菜单截图见原笔记。

### 导入模型跟踪（Lineup 流程，干货最多的一节）

1. 导入模型，选一帧内容多的画面做**单帧对齐**（不必完美，合理范围即可）。
2. 勾选 `Is Reference Only` 低分辨率显示；`Rendering -> UV Map...` 可导入贴图参考；
   关 `Show Lines` 开 `Show Polygons`。
3. `Center Models` 居中，`Shift + 鼠标左键` 移动相机对齐模型。
4. 回 `Manual Tracking` 加跟踪点 → 去 `Lineup` 面板，选 2D 点勾选
   `Extract Polygon` 提供 3D 表示（出现绿点 = 3DE 知道该 2D 点在模型上的位置）。
5. 所有 2D 点都匹配模型；轻微对不上用 `Extract Vertex` 手动微调（解算完记得删掉这个点）。
6. `Calc all...`（黄色点 = 3D 空间中的 2D 点）。
7. 透视不对 → 焦距问题：`Parameter Adjustment` 自适应焦距；仍不对 → 先做畸变矫正再自适应。
8. **`Store Pose`**：存当前对齐帧姿势（时间线出现红色关键帧）。
9. 点打包成组、禁用并隐藏 → `Manual Tracking` 继续跟 → 回 `Lineup` 存姿势帧。
10. 全选跟踪点 → `Edit -> Project Points on 3D Models` 投影上模型；
    投影失败的点放大画面再投一次。
11. 解算后错误率高的点：设为 `Survey Free` 优化 → 或设 `Approximately Surveyed`
    给摆动空间 → 再解算，曲线会平滑很多。

### 导入模型做物体跟踪

相机解算完 → 新点组设 `Point Group Type = Object` → 导模型 → `Extract Vertex`
多点对齐（`Ctrl+Shift` 加点，`Alt` 点空白继续）→ `Store Pose` → 手动跟踪 →
`Project Points on 3D Models` → 解算；偏差点设 `Approximately Surveyed` 再算。

### 360° 全景跟踪

1. `Camera -> Long-Lat Conversion` 把全景投射成正常视角（`Horizontal Angle` 控焦距；
   `Camera Pan / Camera Tilt` 曲线调偏移可 K 帧）。
2. 全景视图打关键帧后跟踪；`Edit -> Convert Regular to Long-Lat Conversion` 互转查看。
3. 解算前：`Lens -> Angle of View -> Horizontal Angle` 设 `Fixed` 且值与
   `Long-Lat Conversion` 的焦距一致；`Pixel Aspect` 防拉伸。
- 定机位等特殊相机运动：用对应 `Camera Constraints` 约束再解算。

## 5. Mocha

### 平面跟踪参数

- `预处理`：跟踪前简单处理素材。
- `通道`：跟踪用哪个通道。
- `最小像素比`：绘制区域内用百分之多少像素跟踪（50 = 50% 内容跟上）。
- `平滑等级`：相当于模糊素材再跟踪（噪点多时）。
- 同一平面内东西可放在平面内不同地方；**层级放在下方的图层排除上面的图层**。
- 技巧：跟踪多个特征区域，出画也没事；找与目标运动平面尽可能一致的面；
  **有透视运动时 X 样条线更适合跟踪**。
- `small motion`：对象变化细微时用；`manual Tracking`：完全遮挡/不可跟时手工调整。
- 隔帧/范围跟踪（2024 新版，定格动画/闪烁画面有用）：
  - `Step`：1 = 每帧跟；2 = 每 2 帧跟一次。
  - `Skip`：如 10-30 = 跳过 10-30 帧，第 30 帧承接第 10 帧的运动惯性继续跟。
- 惯性（外推）跟踪：先正常跟几帧 → 切 `Extrapolate Track`，无画面信息也按原方向速度继续。

### Mocha 相机跟踪（3D Solve）

1. 面跟踪：先把移动的非场景部分跟踪好做遮罩层（**记得上锁**），再把地面跟踪好，
   勾选 `Perspective` 和 `Mesh`。
2. 解算：遮罩层关小齿轮、启用 `排除` → 点 `Solve` → 填已知相机焦距、`3D Motion` 模式。
   - `Motion Type`：`Normal Motion` / `Crash Pan`（赛车等快速运动）/
     `Low Detail`（绿幕等干净背景）。
   - `Zoom Lens` 变焦、`On Tripod` 三脚架、`Corners` 有建筑直角。
   - `Features`：`Min trackers/frame` 每帧跟踪点数、`Max tracker count` 总保留点数、
     `Small/Big blip size` 特征区域最小/最大像素尺寸。
3. 选点 `Align to ground` 设地面；单选一个点 `Make origin` 设原点；`Alt` 切三维视图。
   - 也可不画地面直接 `Solve`——能反求但导出时没有模型。
4. 导出：**Nuke 用 `usda` 直接拖进节点面板**；别的软件用 `FBX 7.7.0 3D Data (*.fbx)`。

### Mocha AI 遮罩与擦除

- `Object Brush` 点目标直接建遮罩；`Matte Assist ML` 基于样条自动建垃圾遮罩。
  **用 Remove 模块（擦除）时用它建更精确的遮罩**。
- AE 侧：复制的 mocha 遮罩数据可直接粘贴；粘贴相机数据需装
  `Paste Mocha Camera` 插件（链接见原笔记）。

## 6. After Effects / Silhouette

- **AE 脸部跟踪**：画好脸部蒙版 → 选中蒙版 → 跟踪器方法选"脸部"。
- **Silhouette AI 抠像流程**（新版本 `Mask ML` 节点）：
  1. 拖入 `Matte Assist ML` 节点 → 点 `Create Mask ML Node` 生成 `Mask ML`。
  2. 双击 `Mask ML`，在图像上点选要抠的部分（自动生成关键帧，多位置点选）。
  3. 新建 `Matte Refine ML` 自动修边缘：`Model` 选边缘模型
     （`Softer` 软边缘适合头发 / `Sharper` 硬边缘）；右侧调 `Shrink+Grow`
     收缩边缘修主体遮罩。
  4. `Alpha Composite` 合并两个遮罩 → `output` 输出。

## 7. 与 Nuke 交接格式速查

| 软件 | 导出给 Nuke | 导出给其他 DCC | 备注 |
|---|---|---|---|
| PFtrack | 相机/场景导出（常规 Export） | 360 导出 6 个摄像机视角 | 跟踪数据可 `Export/Import` 跨素材复用 |
| SynthEyes | Nuke 专用格式（可移关键帧对齐时间线） | `Maya ASCII Updated`（单位 Meters） | — |
| 3DE4 | **畸变插件套件**导出 Nuke 节点；序列命名同 Nuke 用 `####`（如 `name.####.exr`） | Houdini：`.py` 全选复制进 Python Shell（起始帧 = 序列首帧 - 1，如 6847 → 6846）；Maya 专用导出 | 模型单独导出 |
| Mocha | **`usda` 直接拖入 Nuke 节点面板** | `FBX 7.7.0 3D Data (*.fbx)` | AE 需 `Paste Mocha Camera` 插件 |
| Nuke 内部 | `LensDistortion` → STMap exr（32 bit float）→ `C_STMap` forward/backward | — | 见第 1 节 |

## 8. 易错点

- **各软件安全点数不同**：SynthEyes ≥ 9 点/帧，3DE4 ≥ 6 点/帧——别记混。
- **解算误差标准**：Nuke `LensDistortion` 的 `Solve Error` 和 SynthEyes 准确度都要 < 1；
  3DE4 右下角错误率越小越好，靠删点 + `Parameter Adjustment` 压下去。
- **SynthEyes 解算模式**：删点后不切 `Refine` 会从头重算，丢失已有好结果。
- **SynthEyes 手动点要锁定**，否则跟踪新点时旧点还会参与跟踪被带跑。
- **PFtrack 跟踪完必须 `H-/H+` 或 `Hide`**，否则软件认为物体在轨迹外悬停不动。
- **PFtrack 删除要按两次 delete**；环境/物体跟踪必须分 `Current group`，否则点混用。
- **3DE4 变焦镜头错误率曲线呈 V 形**是正常的，但要按第 4 节流程修复到平坦。
- **3DE4 `Extract Vertex` 微调点**：解算完记得删掉，否则污染结果。
- **3DE4 导 Houdini 起始帧差 1**：序列首帧 6847 → 导出工具填 6846。
- **畸变回套顺序**：合成完才 `C_STMap backward` 回套畸变——顺序反了 CG 和实拍打不上。
- **STMap 必须 `exr` + `32 bit float`**，低色深会让畸变数据精度不够。
- **变宽镜头别忘了 `Pixel Aspect`**（3DE4 在 Lens 选项卡；Nuke `LensDistortion`
  选 `Anamorphic`），否则反求比例全错。
- **Mocha 遮罩层做完要上锁**，不然跟地面时会跟踪到遮罩层。
- **Mocha 导 Nuke 用 usda**，FBX 是给别的软件的，别选错。
- 擦除相关：Mocha Remove 模块配 `Matte Assist ML` 建遮罩最精确；
  Silhouette 修边缘别忘 `Shrink+Grow` 收边。
