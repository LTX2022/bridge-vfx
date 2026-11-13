# 跨 DCC 杂项笔记合集（学自用户笔记 UnrealEngine.md / EmberGen.md / C4D.md / Maya.md / 游戏技术美术.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\` 下的 5 份笔记合并蒸馏。
原始笔记保持只读；本文件是蒸馏版——重点是各软件与 Houdini/Nuke 工作流的交接知识，
软件内部技巧压缩保留。截图链接保留原路径，**截图见原笔记**。

---

## 第一部分 UnrealEngine（源：UnrealEngine.md, 16KB）

### 1. MRQ 渲染预热（影视输出最重要的一节）

UE 实时效果（粒子/布料模拟、Lumen GI、动态模糊、TAA/TSR）依赖**场景历史**
（累积之前帧的信息），每个摄像机切镜的**第 1 帧没有前一帧**，直接用会出错。

**四个预热选项**（影片渲染队列 MRQ → 抗锯齿设置）：

| 选项 | 类型 | 作用 |
|---|---|---|
| 渲染预热计数 (Render Warm Up Count) | 整数 | 遗留功能；帧发 GPU 但不播放 Sequence，建图像历史（默认 32 次）。有 Lumen 后**不再推荐** |
| 引擎预热计数 (Engine Warm Up Count) | 整数 | 评估序列第 1 帧并 tick 引擎指定帧数，不发 GPU；处理 CPU 粒子/布料等纯 CPU 预热 |
| 渲染预热帧 (Render Warm Up Frames) | 布尔 | 强制把引擎预热计数/摄像机剪辑预热的帧**在 GPU 上渲染**，适合 GPU 效果；**建议始终开** |
| 使用摄像机剪辑预热 (Use Camera Cut for Warm Up) | 布尔 | 用序列资产在第 1 帧之前逐帧评估，给场景历史供数据 |

**MRQ 推荐设置（实测结论）**：抗锯齿设置里同时勾选
**`Use Camera Cut for Warm Up` + `Render Warm Up Frames`**。

- 摄像机剪辑预热的前提（4 条）：
  1. 摄影机剪辑要做成**单个镜头**（不要一个轨道里塞多个剪辑）
  2. 剪辑在镜头开始前**延伸**，延伸长度=预热帧数（可按镜头调长短）
  3. 动画和变换也要在镜头开始前延伸（否则运动模糊和模拟不正确）
  4. 此时生成资产会有问题
- 关闭摄像机剪辑预热时，MRQ 会反向评估（第 0 帧→第 1 帧→第 0 帧）模拟运动模糊，
  对布料等系统有问题；启用后**每个镜头开始前至少要有 1 帧数据**。
- MRQ 时间采样计数也会在第 1 帧之前评估，**制作内容时最好在序列前面至少多加 1 帧**。

> 对应 Houdini/Nuke 思维：这等同于 pyro/vellum 的 preroll——交序列给 UE 渲染时，
> 记得带前置帧，别从镜头第 1 帧恰好开始。

### 2. UE5 光追最终输出设置（实测流程）

**PostProcessVolume**：

- Ray Tracing Global Illumination → Samples Per Pixel：`32` 或更多（低配 `8`/`16`）
- Ray Tracing Reflections → Samples Per Pixel：`32`
- 配合下方优化代码 1-5

**Movie Render Queue**：

1. Window → Cinematics → Movie Render Queue
2. Render 选序列 → Setting 选 **Anti-aliasing**，输入 `4×4`
3. Setting 选 **PNG 序列** → Output 设路径/分辨率/帧速率 → Accept → Render

### 3. 控制台优化代码（实测值速查）

| 代码 | 作用 |
|---|---|
| `r.ScreenPercentage 200` | 提高渲染屏幕百分比 |
| `r.Tonemapper.Sharpen 1` | 画面锐化，纹理清晰 |
| `r.ForceLOD 0` | 搭建的植物模型强制 LOD0 |
| `foliage.ForceLOD 0` | 绘制的植物强制 LOD0 |
| `r.RayTracing.Geometry.InstancedStaticMeshes.Culling 0` | 解决植物阴影远景消失 |
| `r.MotionBlurQuality 4` + `r.MotionBlurSeparable 1` | 解决高速运动物体边缘锯齿、不融合背景 |
| `r.VolumetricFog.GridPixelSize 8`（默认） | 数值越小灯光雾质量越高 |
| `r.VolumetricFog.GridSizeZ 128`（默认） | 越大灯光雾质量越高 |
| `r.VolumetricFog.HistoryWeight 0.9`（默认） | 越大雾越不闪但拖尾长；建议 `0.85`~`0.95` |
| `r.DOF.Kernel.MaxBackgroundRadius 0.0015` | 提高背景模糊清晰度 |

### 4. 虚拟拍摄：iPhone 控制 UE5 虚拟摄像机

**需开启插件**：LiveLink、VirtualCamera、RemoteSession、Apple ARKit；
手机装 **LiveLink VCAM App**。

项目设置（实测路径）：

- 项目设置 → 引擎 → 渲染 → 默认设置 → 高级 → **帧缓冲像素格式 → 8RGBA**
- 项目设置 → 插件 → UDP 消息发送 → 传输 → 单播末端 → **选与 WiFi 相同的 IP 地址**
- 手机端 LiveLink 设置：`连接类型` = `远程会话`
- 电脑端：打开 Live Link → 消息总线源（截图见原笔记）

### 5. 材质编辑器快捷键（高频）

`1/2/3/4+左键`=Constant 各维常量；`A`=Add；`M`=Multiply；`L`=Lerp；
`N`=Normalize；`O`=OneMinus（1-参数）；`P`=Panner；`T`=TextureSample；
`U`=TextureCoordinate；`S`=ScalarParameter；`V`=VectorParameter；
`Shift+C`=ComponentMask 分离通道；`Space`=刷新节点预览。

资源：**威廉大佬 EasyMapper 主材质**（百度云，提取码 `v7fs`，链接见原笔记）。

### 6. 其他 UE 要点

- `G`：物体操作轴可视；`Alt+左键`：删蓝图节点连线。
- 视口导航 Maya 模式：`Alt+左键/右键`——Maya/Houdini 用户上手 UE 的切换点。
- 物体远离后看不见阴影：截图见原笔记（`微信图片_20231231163730.png`）。
- 插件：**Miarmy Crowd for UE**（原生 UE 群集模拟）、Animcraft（动画资源库/顶点动画贴图）、
  Dash（AI 地形/散布，免费）、Motorica（AI）。
- [多通道渲染输出参考文章](https://mp.weixin.qq.com/s/GGo9XhjlGy7NHr9UMoz9PQ)。

---

## 第二部分 EmberGen（源：EmberGen.md, 4KB）

实时流体软件，**与 Houdini 交接的核心是 VDB**。

### 1. 基本流程（6 步节点链）

1. `shape` 类节点 = 发射源模型（选中后 `Q` 移动 / `R` 旋转 / `E` 缩放）
2. 连 `Emitter Volume`（发射器体积块）→ 生成流体所需属性
3. 连 `Simulate`（模拟）→ 模拟流体
4. 连 `Volume Processing`（体积处理）→ 裁切流体体积
5. 连 `Scene`（场景）→ 流体放进场景
6. Scene 里接 `Shader`（着色器）显示流体 + `Light` 照亮流体

- Scene 的 `Skybox` 端口引环境天空盒（均匀/颜色/大气层+亮度）；
  `Light:Directional` 控制太阳方向；`Ground` 端口引地面。
- Simulate 的 `Forces` 端口引力场噪波改变流体形状。
- 灯光 4 种：点光源 / 定向光 / 环境光 / 聚光灯。
- 外部模型：`import` 节点选路径导入，可用模型的一部分做燃烧源。

### 2. 导出（3 个端口 = 3 种交接格式）

| 端口（从哪连） | 节点 | 导出物 |
|---|---|---|
| Scene → `Export` | `Render` 节点 | **序列帧** |
| Volume Processing → `VDB` | `Export:VDB` 节点 | **体积序列 VDB**（→ Houdini/Blender） |
| Simulate → `Particles` | `Export:Particles` 节点 | **粒子** |

### 3. EmberGen → Blender 渲染（VDB 交接实测流程）

1. `Export:VDB` 节点 → 点 `Export Now` 导出 vdb
2. Blender 用 `导入 openvdb...` 工具导入
3. `物体数据属性` 里有 vdb 的燃烧属性（flames/temperature/density 等场）
4. Shading 界面设材质，渲染器用 **Cycles**，**必须加灯光**（没灯不显示）：
   - `原理化体积`节点调材质（用户原话"非常难调好，和实际有很大差异"）：
     - `黑体色调` = 火焰颜色
     - `密度` = 烟雾细致程度
     - `各向异性` = 烟雾随方向变化的差异性质
     - `温度属性` 按实际选 `flames` 或 `temperature`
   - **更快方案：直接用 `True VDB` 插件里的材质**

> Houdini 侧对照：EmberGen 的 VDB 同样可直接进 Houdini 渲染（Karma/Mantra），
> 注意核对场名（flames vs temperature）和 Houdini volume 的字段匹配。

### 4. 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+S` | 保存 |
| `R` | 重置模拟 |
| `右键+W/A/S/D` | 游戏视角移动 |
| `Ctrl+左键` | 精确移动 |
| `B` | 隐藏/显示流体模拟框 |
| `Z` | 下一帧 |
| `Ctrl+G` | 便签打包节点+备注 |
| `Alt+A` | 全选再按=排列所有节点 |
| `Shift+S` | 显示统计（粒子数量/视窗分辨率等） |

**坑：不能在中文输入法下使用快捷键。**

---

## 第三部分 C4D（源：C4D.md, 1.3KB）

### 烘焙材质

**警告：模型自带 UV 的话不要使用 `自动 UV` 功能。**

1. 前提：模型必须有 **`UVM` 标签**才能上材质。
   没有则物体右键 `材质标签 → 从投射设置 UVM` 新建（提示"没有找到有效 UVM"时关掉自动 UV）。
2. 对象面板里右键材质/模型 → `材质标签 → 烘培材质`，建立"烘焙"标签。
3. 在烘焙标签里设贴图**保存路径、大小、格式**。
4. 点`选项`选要导出什么材质通道；某些通道（如`法线`）下方出新下拉，
   源选物体本身；自动 UV 选`立方`保证贴图质量无锯齿。
5. 点`烘焙`。

---

## 第四部分 Maya（源：Maya.md, 712B）

### 1. 序列识别规则（交接素材时注意）

- Maya 只认 **`名字_数字.格式`**（下划线分隔），如 `名称_1.jpg`、`_1.jpg`。
- **数字是 1 时不能写成 `01`/`001`**——前导零识别不了。
  （与 Nuke/Houdini 的 `%04d` 帧编号习惯冲突，跨软件发序列给 Maya 要改名。）

### 2. 最基本渲染流程

- 灯光：**使用 HDRI 但不渲染 HDRI 做背景**（截图见原笔记）。
- 渲染设置 3 张截图见原笔记；启动渲染前**记得设置摄像机**。

---

## 第五部分 游戏技术美术（源：游戏技术美术.md, 1.4KB）

### 渲染管线（Rendering Pipeline）速记

将 3D 场景渲染成 2D 图像的流程（全部截图见原笔记）：

1. **Mesh 数据储存在顶点上**
2. **三角形处理阶段**：背面剔除 / 正面剔除 / 不做操作
3. **光栅化**
4. **片元处理**（片元可理解为像素）
5. **帧缓冲**

> 这是理解 Houdini→引擎交接（为什么顶点属性/法线/UV 命名重要）和
> 渲染调试（剔除、深度、帧缓冲）的基础概念。

---

## 易错点

1. **UE MRQ 渲染不做预热 = 镜头第 1 帧必错**（Lumen/TAA/布料/粒子全依赖历史帧）；
   标准答案：勾 `Use Camera Cut for Warm Up` + `Render Warm Up Frames`，
   序列内容前至少多留 1 帧——等同于 Houdini 模拟的 preroll 思维。
2. UE 植物阴影远景消失：不是灯光问题，跑
   `r.RayTracing.Geometry.InstancedStaticMeshes.Culling 0`。
3. EmberGen **中文输入法下快捷键全部失效**；体积渲染必须给灯光否则全黑；
   Blender 侧温度场名要选 `flames` 还是 `temperature` 看实际 VDB 内容。
4. C4D 烘焙材质：**自带 UV 的模型开自动 UV 会毁 UV**；没有 UVM 标签根本无法烘焙。
5. Maya 序列**不认前导零**（`01`/`001` 不行），跨软件交接序列帧命名要对齐。
6. UE 虚拟摄像机连不上手机：先查帧缓冲像素格式是否 8RGBA、UDP 单播 IP 是否与 WiFi 同网段。
