# 实用节点 cheat-sheet（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "一些有用的节点和方法" 节。
原始笔记保持只读；本文件是 60+ 节点的精炼描述。

## 0. 核心一句话原则

- **节点不能禁用，不光会跑还需要跑表达式**——不用的节点最好删除或者断掉链接
- 合成时可能发现合成素材边缘有锯齿，可以进行边缘模糊一下
  （要保证此图像有 alpha 通道）
- 大部分节点都有一个 alpha 输入，可以定义节点影响的图像区域
- 大部分模糊节点都由 alpha 驱动
- 运动模糊通道：**motionvectors**
- 景深通道：**depth** 或 **depth_extra**

## 1. 60+ 节点速查（按类别）

### 基础合成

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Read` | 读素材 | file, first, last, colorspace |
| `Write` | 输出素材 | file, file_type, channels, create_directories |
| `Merge2` | 标准合并 | operation (plus/multiply/over/from/divide 等) |
| `Constant` | 纯色填充 | color, channels |
| `Switch` | 多输入切换 | which (可打关键帧) |
| `AppendClip` | 拼接时间线 | First Frame (改素材起始帧) |
| `TimeDissolve` | 时间过渡 | in, out, curve |
| `Add (Channels)` | 通道相加 | value, channels |
| `Copy` | 通道复制 | from0, to0 |
| `ChannelMerge` | 多通道合并 | channels |
| `Remove` | 删除通道 | channels, operation |

### 几何变换

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Transform` | 平移/旋转/缩放 | translate, rotate, scale, center |
| `CornerPin2D` | 四角钉变形 | to, from |
| `Reformat` | 改格式 | type, scale, format |
| `Crop` | 裁剪 | box, reformat |
| `Mirror` | 翻转 | flipX, flipY |
| `GridWarp` | 网格变形 | grid_size, source, destination |
| `SplineWarp` | 样条变形 | shape control |
| `IDistort` | UV 通道置换 | uv_scale, UV channels |
| `BlackOutside` | 边缘黑色 | (无参数) |
| `STMap` | UV 贴图映射 | uv channels, src, dst |
| `iSTMap` | 反向 STMap | forward, reference frame |

### 颜色 / 调色

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Grade` | 黑白点匹配、lift/gain/gamma | blackpoint, whitepoint, lift, gain, multiply, gamma, offset |
| `ColorCorrect` | 区域调色 | ranges, saturation, contrast |
| `ColorLookup` (CLUT) | LUT 加载 | file (cube 文件) |
| `HueCorrect` | 色相/饱和度曲线 | ranges (8 个区域) |
| `Saturation` | 单独饱和度 | saturation |
| `MatchGrade` | 自动匹配色彩 | Task (Match Different Clip / Match Graded Source) |
| `Curvetool` | 区域分析驱动曲线 | (用于跟踪画面变化) |
| `OCIOColorSpace` | OCIO 色彩空间转换 | in_colorspace, out_colorspace |
| `Colorspace` | 简化色彩空间转换 | colorspace_in |
| `log2lin` | log/linear 互转 | (双向) |
| `Clamp` | 数值钳位 | channels |

### 模糊 / 散焦

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Blur` | 普通模糊 | size, channels |
| `Bokeh` | **最好**的散焦节点 | filter, focus_plane, output, back_multiplier |
| `Defocus` | 模拟相机散焦 | scaling, aspect |
| `ZDefocus` | 基于深度图层 | output, depth_channel, focal_point, size |
| `Convolve` | 自定义虚焦形状 | filter 输入, transform |
| `VectorBlur` | 基于运动矢量 | uv_channels, blur_uv, motion |
| `DirectionalBlur` | 定向模糊 | angle, size |
| `iBlur` (NKPD) | 变焦模糊过渡 | size, rot (连 roto 控制模糊区域) |
| `MotionBlur` | 后期运动模糊 | shutter_samples, shutter_time |
| `MotionBlur3D` | 3D 运动模糊 | 需 camera + motion vectors |
| `Kronos` | 减速+运动模糊 | timing, motion vectors |
| `SmartVector` | AI 运动矢量 | vector_detail, strength, flicker_compensation |

### 抠像 / 蒙版

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Roto` | 贝塞尔曲线蒙版 | shape 编辑, feather, opacity, life |
| `RotoPaint` | Roto + 绘画 | 同上 + brush |
| `Keylight` | 色度键 | screenColour, screenBalance, clipBlack, clipWhite |
| `Primatte` | 备用抠像 | operation (Clean BG Noise / Clean FG Noise) |
| `IBKColour` / `IBKColourV3` | 屏幕清洁辅助 | darks, lights, size, erode, level |
| `IBKGizmoV3` | 屏幕清洁 | 输入干净绿幕 + 含人物绿幕 |
| `IBK_lin_v1` / `_v3` | 林君义包 IBK | — |
| `ChromaKeyer` | 替代 Keylight | — |
| `DespillMadness` | 去溢色 | (简化溢色去除) |
| `EdgeExtend` | 修复受损边缘 | EdgeSize, Erode |
| `EdgeExtend_lin` | 林君义包版 | — |
| `EdgeTool_lin` | 假边 | outsideErode, insideErode, insideBlur, outsideBlur, superSkills |
| `InvertColor_lin` | 去黑边 | black, mix, alphaOpacity, Erode, blur |
| `ClampX_lin` | 去坏值 | — |
| `FilterErode` | 收缩/扩张 | size |
| `EdgeBlur` | 边缘模糊 | size |
| `LightWrap` | 光包围 | (用于极亮背景) |
| `AdditiveKeyerPro` | 保留发丝 | 输入：去褶皱前景 + 绿幕背景 + 合成背景 |
| `KeyMix` | 蒙版分层 | 输入 A/B + mask |
| `Despill` | 通用去溢色 | screen type |

### 跟踪

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Tracker` | 单/多点跟踪 | reference frame, pattern, search |
| `PlanarTracker` | 平面跟踪 | (在 Roto 内右键启用) |
| `CameraTracker` | 相机反求（NukeX） | mask, solve, refine solve, focal, position, rotation |
| `PointCloudGenerator` | 从跟踪点云生成网格 | source, camera, analyze, track point |
| `ModelBuilder` | 交互式建模 | src, cam 输入；shape 工具 |
| `PoissonMesh` | 自动 mesh 化 | scale (越低越粗糙) |
| `Project 3D` | 2D 投到 3D | cam, geometry |
| `FrameHold` | 冻结帧 | first_frame, before, after |
| `C_Tracker` | CaraVR 版 2D 跟踪 | (VR 专用) |

### 3D 模块

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Scene` | 3D 场景容器 | 接收 cameras, geometries, lights |
| `Camera` | 相机 | focal_length, aperture, transform |
| `Axis` / `Card` / `Sphere` / `Cube` | 3D 几何体 | 各种显示参数 |
| `EditGeo` | 编辑几何体顶点 | mode (顶点/边/面) |
| `Phong` | 给几何体加材质 | diffuse, specular, shininess |
| `ModelBuilder` | 交互式建模 | (见跟踪节) |
| `PointCloudGenerator` | 点云生成 | (见跟踪节) |
| `ScanlineRender` | 3D 渲染输出 | camera, geometry, output 类型 |
| `Light` | 3D 灯光 | (多种类型) |
| `Material` | 材质 | shader 类型 |
| `C_Rayrender` | CaraVR 渲染 | (VR 专用) |

### 粒子 / 特效

| 节点 | 作用 | 关键参数 |
|---|---|---|
| `Particle` | 粒子系统 | (复杂) |
| `AE_Machinegun` | 子弹轨迹 | (3D 空间 Lightracer) |
| `Breakdown_lin` | 特效 demo 刷屏 | (林君义包) |
| `Rippling` | 水波纹 | (林君义包) |
| `HeatDistortion_lin` | 热浪扭曲 | (林君义包) |

### FurnaceCore（已收购工具集）

| 节点 | 作用 |
|---|---|
| `F_Align` | 镜头对齐（背景相同、前景不同的素材叠加） |
| `F_DeFlicker2` | 减少帧之间的亮度闪烁（频闪） |
| `F_ReGrain` | 噪点保留（从单张图像采样，生成与原始统计数据完全相同的无限量噪点） |
| `F_RigRemoval` | 擦除运动物体（用前后帧背景填充） |
| `F_Steadiness` | 全局运动估计（消除相机抖动） |
| `F_WireRemoval` | 半自动化擦威亚（内含跟踪器） |
| `FurnaceCore` 节点工具集 | 综合 Furnace 工具集入口 |

### AI 工具（Cattery 模型）

- `MODNet`：将人体与图像分割开来
- `Background Matting`：背景遮罩（差值抠像）
- `Segment Anything from Meta`：语义分割（点选或导出 cryptomatte）
- `LaMa`：图像区域修复（提供一张图像 + alpha 蒙版，LaMa 用上下文细节填充）
- `Face Makeup`：面部解析（嘴唇、鼻子、眼睛、眉毛、皮肤、颈部、头发）
- `Semantic Segmentation`：图像分割为预定义语义类别
- `RAFT`：机器学习运动估计器（生成准确矢量）
- `ABME`：AI 补帧（高质量运动估计器和帧插值器）
- `DepthPro`：苹果开发的单眼深度估计（米为单位）
- `MiDaS`：单眼深度估计器（相对深度）
- `CopyCat`：13 版本加入，基于深度学习的效果在不同帧的拷贝
- `BigCat`：序列效果训练，输出 .cat 文件
- `SmartVector`：生成运动矢量
- `VectorToMotion`：向量转 motion 通道（配 VectorBlur）
- `ViTMatte`：自然的消光神经网络，从垃圾消光中提取高质量 alpha

### 杂项

| 节点 | 作用 |
|---|---|
| `Sharpen` | 锐化 |
| `Flare` | 光晕 |
| `Glow` | 辉光/色散（底层是 blur plus） |
| `Multiply` | 透明度（白底层 = 透，黑底层 = 死黑） |
| `VolumeRays` | 体积光 |
| `Invert` | 反转（抠像反转） |
| `Ramp` | 渐变（看衰减） |
| `Emboss` | 浮雕 |
| `LayerContactSheet` | exr 多层展示 |
| `Grain` | 噪点（需要 alpha 通道） |
| `F_ReGrain` | Furnace 版 Grain |
| `shuffle` | 多通道素材分离 |
| `FrameRange` | 帧范围（用于训练 CopyCat） |
| `PostageStamps` | Read 节点复制粘贴替代品 |
| `DasGrain` | 林君义包降噪节点 |
| `mmColorTarget` | Reberway 颜色匹配（需 ACEScg_ColorChecker2005.exr） |
| `HeatDistortion` | 热浪 |
| `DepthFog` / `DepthFog_lin` | 智能深度层雾 |
| `Defocus` | 连 roto 做景深 |
| `SpecularFade` | 抑制过爆高光 |
| `Renovate_Footage` | 修复有错误的帧 |
| `bvfx-find-path` | 查找丢失的外部文件并重新链接 |
| `Kacz_Pixel_Sampler` | 像素级采样，精准匹配颜色色调 |
| `VectorToMotion` | 矢量转 motion 通道 |
| `ModifyMetaDate` | 修改视频元数据 |
| `AddTimeCode` | 添加时间码到元数据 |
| `GodRays` | 体积光（不能自己产生光源） |
| `SpotFlare` | 自产生光源（NukeSurvivalToolkit） |
| `DotProductVector3` | 计算 3D 向量点积 |
| `RainMaker` | 相机镜头前雨水积聚和滴落 |
| `VoronoiGradient` | 多色彩渐变 |
| `apChroma` | 边缘色差、模糊 |
| `X Sharpen XM` | GPU 加速锐化 |
| `AutoFlare` | 耀斑工具 |
| `Gradient Editor` | 可视化渐变编辑器 |
| `QC Tool` | QC 检查工具 |
| `mtAnamorphicAstigmatism` | 变形散光（彗差） |
| `Aitor_Echeveste` 系列 (aeDirtCG, aeFiller, aeBrokenEdges, aeRefracTHOR 等) | 第三方小工具集 |
| `nuke-vector-matrix` | 向量/矩阵数学工具 |
| `Slate` | 加水印 |
| `Wrap It Up` / `CopyProject_lin` | 工程自动打包工具 |
| `RenderQueueLin` | 自动批量渲染工具 |
| `BatchRenderTool_lin` | 多脚本联合渲染工具 |
| `ReduceProjects_lin` | 优化项目文件夹 |
| `FrameFix` | 坏帧替换 |
| `Neat.Video` | 降噪插件 |
| `Pixelfudger v3.0` | 深度散焦/光斑/区域光等 |

## 2. alpha 通道操作

- `Merge` 的 `matte` 模式：把 2 个图层的 alpha 直接相加（不混合）
- `Merge` 的 `out` 模式：把 2 个图层的 alpha 直接相减（A-B）
- `add` 节点：把 A 的 alpha 通道写入 B 里
- `Add(Channels)` 节点：直接添加 alpha 通道
- `Copy` 节点：A 端 alpha 通道覆盖到 B 端对应通道

## 3. Shuffle 节点的多种用法

- 通道分离：把单通道拉到 rgba
- 法线层用 Shuffle 提取一个通道当 mask
- 多层 EXR 的任意层重组
- 在 latlong 空间输出到 C_SphericalTransform 之前

## 4. Grain 节点使用注意

- `Grain` 节点必须要有 alpha 通道——所以可以在此节点前加一个 shuffle 通道节点
  增加 alpha 通道
- 添加噪点可以使得图像更加锐利更加逼真
- F_ReGrain 比 Grain 更稳定（保留原始颗粒分布）
- 降噪 + 重新加噪是行业标准流程

## 5. 表达式 cheat

- `random()`：生成随机数（做镜头震动很好用）
- `frame*0.1`：每帧偏移 0.1 帧
- 在参数中使用表达式：右键 → `Add expression`
- 参数关联：按 `Ctrl` 拖动一个参数到另一个参数
- `frame + 5`：5 帧后的帧
- `frame % 24`：每 24 帧循环

## 6. nuke-bridge 自动化节点批处理的最佳实践

```python
# 1. 批量改参数
for n in nuke.allNodes('Grade'):
    n['blackpoint'].setValue(0.05)

# 2. 批量创建节点（模板 + 列表）
node_types = ['Read', 'Write', 'Merge2', 'Grade']
for t in node_types:
    nuke.createNode(t)

# 3. 批量连接
reads = nuke.allNodes('Read')
for i, r in enumerate(reads[:-1]):
    m = nuke.createNode('Merge2', inpanel=False)
    m.setInput(0, r)
    m.setInput(1, reads[i+1])

# 4. 批量复制节点参数
src = nuke.toNode('Read1')
for knob in src.knobs():
    if knob in target.knobs():
        target[knob].setValue(src[knob].value())

# 5. 选区内批量重命名
for n in nuke.selectedNodes():
    n['name'].setValue('MyNode_' + n['name'].value())
```

## 7. 易错点

- **节点禁用也要算**：能删就删
- **Shuffle 的 `out = rgba` 必须明确**：默认输出可能不是 rgba
- **Multiply 黑底 = 黑**：`Multiply` 节点 = 相乘，黑底会让前景变黑
- **Bokeh 不基于 0~1 深度**：基于深度通道的实际值，先用 DeepColorCorrect 校准
- **Blur 默认全通道模糊**：`channels` 参数记得设 `a` 或 `rgba`
- **EdgeExtend 不能叠加**：多次做会反复扩张
- **每个节点输出通道是有限集合**：`Write` 默认只写 RGBA；要写全部要 `all`
- **B-pipe 永远正确**：A=前景、B=背景、mask 从右入——这是合并类的铁律
