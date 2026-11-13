# 市场对标：Nuke 自动化/工具集类项目（2026-08-25 调研）

对标目的：找出市面优秀 Nuke 工具集/脚本库的设计亮点，吸收进 nuke-bridge skill。
调研来源：keheka.com "Useful Nuke Tools And Setups" 精选、Nukepedia、GitHub 各大工作室开源工具集。

---

## 1. 业界公认的工具集梯队（keheka 精选，按影响力排）

| 工具集 | 作者/工作室 | 核心亮点 | 我们 skill 的状态 |
|---|---|---|---|
| **NukeSurvivalToolkit** | Tony Lyons（CreativeLyons） | 业界最大精选集，含 RainMaker/VoronoiGradient/apChroma/X Sharpen/SpotFlare/AutoFlare/AdditiveKeyerPro | ✅ 用户笔记已装，已在 `useful-nodes-cheatsheet.md` + `ai-tools-cattery.md` 收录 |
| **Pixelfudger v3.0** | Xavier Bourque | PxF_DeepResample/DeepDefocus/IDefocus/ZDefocus/SmokeBox/Smoother/TimeMerge/AreaLight/EnvLight/GeoLight/RingLight/TubeLight/Distort/Filler | ✅ 用户笔记已装，已收录 |
| **apTools + Stamps** | Adrian Pueyo | **Stamps 是节点连接系统**（比 PostageStamp 更强的引用机制）；apTools 是一批实用 gizmo | ⚠️ Stamps 概念值得单开一节 |
| **bmTools** | Ben McEwan（128 stars） | 一批 Gizmo+Python 脚本 | ⚠️ 未深入 |
| **Buddy System** | Hiram Gifford | 节点协作工具 | ⚠️ 未深入 |
| **MJT Lab** | Mark Joey Tang | **Deep 和 Position 数据操作专长** | ✅ 已有 `deep-and-cryptomatte.md`，可再补 |
| **SpinVFX Gizmos** | SPIN VFX 工作室（Erwan Leroy 整理） | 工作室生产级 gizmo（见 §3 详解） | ⚠️ 亮点多，详见 §3 |
| **Mads Hagbarth Lund** | 个人 | 极聪明的小工具 | ⚠️ 未深入 |
| **Frank Rueter** | Nukepedia 创始人 | 老牌 OG 工具 | ⚠️ 未深入 |
| **Andrea Geremia** | 个人 | Particles Collection / Expression Node Collection / Python & TCL Snippets | ⚠️ 表达式集合值得吸收 |
| **nuketools** | Sean Danischevsky | 自动 gizmo 加载、节点排列、脚本清理、MassivePanel 批量操作 | ⚠️ 自动化思路好 |

---

## 2. 值得单独立项的工具/技巧（keheka 文章实测推荐）

### 边缘处理（我们 skill 已有 edge-blend-correct-workflow.md，补充）
- **VectorExtendEdge**：普通边缘延伸工具是把边缘像素**涂抹**出去（smear），
  这个工具是**形变**出去（warp），边缘细节保留更好
  > keheka 警告：边缘延伸要**节制使用**，用多了会杀死边缘细节
- **Perimeter – Advanced Edge Matte Tool**：比 Nuke 自带 `EdgeDetect` 强得多的
  自定义边缘蒙版工具
- **Breaking Up Edges And Surfaces In Nuke**：打破"太完美太 CG"的边缘的 setup

### CG 分层重建（AOV 管理）
- **Leeloo – Multipass Compositing Tool**：加法式 beauty 重建工具——
  多 AOV 渲染时不用每次手工搭整个 beauty rebuild，一键生成
- **Korben – Subtractive AOV Grading Tool**：减法式 beauty 重建——
  只调单个 pass 时比 Leeloo 高效
  > 对应我们 skill 的 `aov-rescue-and-reassembly.md`：Leeloo = 加法派、Korben = 减法派
- **Professional CG Compositing In Nuke**（keheka 文章）：每个 AOV 完整重建 +
  beauty 的详细 walkthrough，可作我们 aov 参考文件的扩展阅读

### 重打光
- **Relighting CG Renders In Nuke**（keheka setup）：改变 CG 渲染的灯光，
  配合我们 `aov-rescue-and-reassembly.md` 的 P_matte/eye_light 章节互补

### "I 系"工具范式（重要设计哲学）
> keheka："I-style" 类型的工具里，mask 输入和 mix 滑杆**不是控制透明度，而是控制效果强度**。
> 软蒙版会 ramp 效果：mask 白色区域 = 全效果，中间值 = 部分效果。
> 例如 blur size=20 + mask 值=1 的区域 = 完整 20 像素模糊。

**这对 nuke_run 自动化的意义**：用 `iBlur`/`ITransform` 这类"I 系"工具时，
`mask` 通道不是 alpha 而是**强度图**——写脚本时别按"透明度"理解。

---

## 3. SpinVFX Gizmos（工作室生产级，重点提取）

SPIN VFX 是 1987 年成立的电影/剧集特效工作室，这套 gizmo 是他们生产环境在用的。

### 安装
```python
# init.py
nuke.pluginAddPath('/path/to/spin_nuke_gizmos/gizmos')
```
手动装只需 `gizmos/spin_tools/` 文件夹（.nk + .gizmo）。
注意：`spin_tools_callbacks.py` 提供 UX 回调，不设也能用。

### 亮点工具（按类目）

**3D / 投影**
- **3D Noise**：基于 Position pass 在 3D 空间生成噪声，内置几个 3D 几何体的
  预制 Position pass；内部用 4D 噪声（第 4 维做 "boiling" 动态效果）
- **ReProject_3D**：用渲染的 world-space Position pass + 3D 相机做重投影，
  可重映射输入图像的所有 layer。注意：无蒙版输入或未预乘的蒙版效果最好
- **Relight_Simple**：只需法线贴图的简化重打光（不做真实 3D 空间，用图像局部空间）

**调色**
- **Match_Black_White**：把一个图（source）的黑白点匹配到另一个图（target）——
  比我们 notes 里 Grade 手动吸取黑白点的流程更自动化
- **Suppress_RGBCMY**：抑制/增强特定颜色（R/G/B/C/M/Y 六色）
- **Grain_Advanced**：合成颗粒，默认值按 HD Alexa 底片调校，可用滑杆匹配样本颗粒

**Lightwrap / 融合**
- **Lightwrap_Exponential**：比 Nuke 默认 lightwrap 更物理的响应曲线
- **Morph_Dissolve**：自动在两个运动 plate 之间做 morph，或改善手动 morph

**效果**
- **Chromatik**：用光谱波长梯度做色差（比我们 notes 里"放大 2% 红色通道"的土法精细）
- **Glow_Exponential**：指数辉光，可重调色、调衰减

**抠像 / 边缘**
- **Edge_Expand**：扩边修 fringing（对应我们的 EdgeExtend 章节）
- **Erode_Fine**：精细腐蚀——Nuke 默认 erode 只能整像素，这个能亚像素
- **Spill Correct**：去溢色，可替换为指定颜色

### 对 nuke-bridge 的吸收方案
这套 gizmo 的核心价值是**"单节点完成我们 skill 里要 3-4 节点的事"**。
比如 `Match_Black_White` = 我们 notes 里 Grade 吸黑白点的 4 步操作。
**吸收做法**：在 `references/useful-nodes-cheatsheet.md` 的"插件"一节补充这些工具，
标注"装 SpinVFX 后可用 X 替代 Y 流程"。

---

## 4. nuketools（Sean Danischevsky）— 自动化思路最值得学

### 核心亮点（对我们 nuke_run 自动化的启发）

**① 自动 gizmo 加载与消毒**
- `load_gizmos.py`：从分类目录自动加载所有 gizmo
- `sanitize_gizmos.py`：把 gizmo 文件标准化——统一命名、元数据、图标、
  帮助文本（suffix、tile_color、help、default_icon）
- **对我们的意义**：写 `nuke_run` 批量处理 gizmo 时参考它的消毒逻辑

**② Arrange By：智能节点排列**
按 class / 位置 / 元数据排列节点——**比我们目前的 layout 思路更细**。
`arrange_by_sd.arrange_by(nuke.selectedNodes(), sortKey='class')`

**③ MassivePanel：批量节点操作面板**
批量改多个节点的属性——对 nuke_run 批量改参有参考价值。

**④ Script Cleanup**
工程脚本清理优化（死节点、断连、无效表达式）——
对应我们 houdini 侧的 `find_dead_nodes` 思路，**Nuke 侧还没有，值得加**。

**⑤ 一堆 Viewer 增强**
Flip/Flop 镜像、Grid 叠加、Saturation 分析、Laplacian 边缘检测、
CheckFrozen 冻结帧检测、Scroll（CornerPin 可视化）、Screengrab 截图、Thumbnails

### 对 nuke-bridge 的吸收方案
- `scripts/cleanup_script.py`（Nuke 版死节点/断连清理）——**值得写**
- `scripts/batch_set_parm.py`（批量改同类节点的同名参数）——**值得写**
- Viewer 增强类不吸收（GUI 交互为主，自动化用不上）

---

## 5. 对标结论：我们的 skill 缺什么

| 优先级 | 缺口 | 建议动作 |
|---|---|---|
| 🔴 高 | **Leeloo / Korben 的 AOV 重建思路没进 skill** | `aov-rescue-and-reassembly.md` 加"加法派 vs 减法派"一节 |
| 🔴 高 | **Nuke 侧脚本清理工具缺失** | 写 `scripts/cleanup_script.py` |
| 🟡 中 | **SpinVFX 单节点替代多节点流程** | `useful-nodes-cheatsheet.md` 插件节补充 |
| 🟡 中 | **Stamps 节点引用系统**（比 PostageStamp 强） | 单独研究后补一节 |
| 🟡 中 | **I 系工具的 mask=强度语义** | 在 `useful-nodes-cheatsheet.md` 加警告 |
| 🟡 中 | **Andrea Geremia 的表达式集合** | 吸收进 `scripts-and-productivity.md` 表达式节 |
| 🟢 低 | **nuketools 的 Arrange By / MassivePanel** | 写 `batch_set_parm.py` 时参考 |

---

## 6. 我们 skill 已有的优势（对标后确认领先的部分）

- **火 pass HDRI 救赎**（Option A/B/C 三方案 + 预检）：业界没有同级别的现成方案
- **AOV 减法合成**（用户笔记 + 官方流程对照）：keheka 也只提了 Leeloo/Korben 工具，没给数学
- **频率分离 Merge Divide**：已收录完整
- **CameraTracker 6 步精修**：比官方文档更实战
- **跨软件跟踪 pipeline**（跟踪擦除.md 蒸馏）：PFtrack/SynthEyes/3DE4/Mocha/AE/Silhouette 全覆盖
- **CaraVR 360 全景 8 步法**：官方教程级完整度
- **CopyCat/LaMa/Cattery AI 工具链**：含显存要求、训练数据量等实测数据
- **Write 节点 Windows 正斜杠坑**：实测踩出来的，公开资料少见

---

## 易错点

- **SpinVFX / NukeSurvivalToolkit 等 gizmo 是 .gizmo 文件**：跨工作室交付工程时对方没装就会报错——
  用它们之前先确认交付环境，或用 `export as gizmo` 转 Group（见 Nuke.md 笔记的"自己做插件"节）
- **I 系工具的 mask 是强度不是透明度**：写脚本时别按 alpha 理解
- **Leeloo 加法重建 vs Korben 减法重建**：Leeloo 适合多 AOV 全重建、Korben 适合只调单 pass——
  别用错场景
- **对标信息时效**：这些工具集的 Nuke 版本兼容性要实测（尤其 Nuke 16+ 的 PySide6 迁移）
- **不要硬抄工具列表**：抄**设计思路**（单节点替代多节点、自动化消毒、批量操作），
  具体 gizmo 参数以实际安装后的版本为准
