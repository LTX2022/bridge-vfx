# AE / Fusion 与 Nuke 交接对照笔记（学自用户笔记 AE.md、达芬奇.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\AE.md`（531 行）全文 +
`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\达芬奇.md` 的 Fusion 章节。
原始笔记保持只读；本文件是蒸馏版——只收与 Nuke 工作流有交接的内容
（表达式、色彩管理、通道提取、跟踪插件），AE 纯 UI 操作与包装类插件不录。

## 1. 软件定位速记

- **AE**：图层制、基于像素（栅格）——矢量素材进时间轴必被栅格化；
  `连续栅格化` 开关让图层随变换即时重新栅格化（矢量任意缩放不糊；
  对预合成该开关变成"折叠变换"）
- **Fusion**（达芬奇内置）：节点制，与 Nuke 同源思路；`Text+` 来自 Fusion
  （吃资源，比自带 `Text` 慢且占内存）
- **Nuke**：节点制 + 深通道，电影合成标准
- 替代品备忘：`Autograph`（Maxon，节点制合成，支持 USD，个人免费，AE 平替）

## 2. 表达式对照（AE JS ↔ Fusion ↔ Nuke）

| 需求 | AE（JavaScript） | Fusion | Nuke（TCL/表达式） |
|---|---|---|---|
| 当前时间/帧 | `time`（秒） | `time`（当前帧） | `frame` |
| 随时间旋转 | `time*value` | 角度写 `time` | `frame*10` |
| 正弦摆动 | `Math.sin(time*v1)*v2` | `sin(...)` | `sin(frame*0.1)*v` |
| 抖动 | `wiggle(频率, 幅度)` | — | `random()` 系列（做镜头震动好用） |
| 层序号递变 | `index*value` | — | 无直接等价，用 `$gui` 脚本或表达式编号 |
| 计时显示 | `time.toFixed(2)` | `string.format("%.2f", time/comp.RenderEnd*100).."%"` | — |
| 随机数 | `random(min,max)` | — | `random(min,max)` |
| 采样历史帧 | `valueAtTime(time - d)` | — | 用 `TimeOffset`/`FrameHold` 节点实现拖尾 |
| 起始/结束帧 | — | `RenderStart` / `RenderEnd` / `comp.RenderEnd` | `root.first_frame` / `root.last_frame` |

**AE 运动拖尾表达式**（残影，Nuke 里用 TimeEcho/TimeOffset 节点链实现）：

```javascript
delay = 5; // 延迟帧数
d = delay*thisComp.frameDuration*(index - 1);
thisComp.layer(1).position.valueAtTime(time - d)
```

**AE 万能弹性表达式**（关键帧后弹跳，amp 振幅 / freq 频率 / decay 衰减）：

```javascript
amp = .1; freq = 2.0; decay = 2.0;
n = 0;
if (numKeys > 0){ n = nearestKey(time).index; if (key(n).time > time){n--;} }
if (n == 0){ t = 0; } else { t = time - key(n).time; }
if (n > 0){
  v = velocityAtTime(key(n).time - thisComp.frameDuration/10);
  value + v*amp*Math.sin(freq*t*2*Math.PI)/Math.exp(decay*t);
} else { value }
```

**Fusion 特有表达式**（迁移思路）：

- `Width*1.778`：16:9 素材裁正方形的宽度计算
- `Point(Width/2, 0.5)`：滑块贴左边移动；`1-Width/2` 贴右边（Height 同理）
- `24/comp:GetPrefs("Comp.FrameFormat.Rate")`：**动画时长自适应帧率**——
  当前时间线 24 帧时系数为 1，换帧率工程动画时长自动缩放
- Fusion 表达式左边 `+` 号框可拖动联动其他属性值
- 缓动查询：https://easings.net/cn

## 3. 色彩管理交接

**AE 的 ACES 流程**（对比 Nuke 流程，见 `aces-and-color-management.md`）：

1. 项目设置色彩空间选 `ACEScct`（工作/调色空间，带 toe）
2. `解释素材` 里把素材色彩设为母版色彩空间 `ACEScg`
3. 渲染队列输出 `exr` + `ACEScg`（**全部 ACEScg**）——与 Nuke 交付约定一致

**AE 的 log/linear 还原**：`Cineon 转换器` 插件——
`Log to Linear`（灰片转正常）/ `Linear to Log`（正常转灰片）。
Nuke 对应 `Log2Lin` / `Colorspace` 节点。

**变宽镜头还原**：AE 走 `解释素材 → 主要 → 像素长宽比`；
Nuke 用 `Reformat` 节点（详见 `video-camera-fundamentals-notes.md` 第 9 节）。

## 4. 通道 / AOV 交接（AE 收 EXR 的三件套 ↔ Nuke 原生能力）

| AE 做法 | 作用 | Nuke 对应 |
|---|---|---|
| `EXtractoR` 插件 | AOV 多通道 EXR 分层提取 | `Shuffle` / `Shuffle2` 原生直接取层 |
| `3D 通道提取` 系列 | 读取 RPF/EXR 内嵌 3D 信息 | 原生读 depth/normal 等层 |
| `深度遮罩`（深度/羽化/反转） | 沿 Z 轴指定位置截取蒙版 | `depth` 层 + `Grade`/`Roto`，或 `ZDefocus` |
| `ID 遮罩` | 按物体 ID/材质 ID 分离元素做蒙版 | `Cryptomatte`（见 `deep-and-cryptomatte.md`） |
| `IDentifier` | 按 ID 给元素做标志 | `Cryptomatte` 拾取 |

- AE 侧 `Alpha 遮罩` vs `保持透明度` 的区别（截图见原笔记
  `微信截图_20240327154852.png` 等三张）

## 5. 跟踪 / 擦除类工具交接

- **Mocha Pro**：平面跟踪；**能做褶皱跟踪并导出褶皱信息**（布料跟踪刚需，
  截图见原笔记）——跟踪数据可导 Nuke
- **AE 内容识别填充**（概念对应 Nuke 的 `F_ReGrain`+贴片/`Inpaint` 思路）：
  - 流程：画蒙版 → 右键 `跟踪蒙版` → 蒙版设相减 → 内容识别填充面板生成填充层
  - 填充方法三选：**对象**（移除运动物体，估算背后场景运动）/
    **表面**（静态平坦表面，用合成内估算运动）/ **边缘混合**（采样边缘像素，
    快，适合无纹理表面如纸上文字）
  - `阿尔法扩展`：扩大待填充区（蒙版不精确也没关系，多包含外围像素反而更好）
  - `光照校正`：帧间光照变化大的素材必开（先选强，过度再降中/弱）
  - `创建参考帧`：跳 Photoshop 修单帧当填充指导
- 静态镜头擦除运动元素：`Superpose` 插件（AE）
- 蒙版 1 像素留白解决不了：AE 把 `蒙版扩展` 调为 **-1**（往外延 1px）；
  **Nuke 对应：`Roto` 节点 `feather falloff` 调 0**（见 `production-best-practices.md`）

## 6. 光效插件的合成原理（Nuke 可复刻）

- **Optical Flares（AK）**：**素材必须整个画面 alpha 全为 1**，否则 alpha≠1
  的部分不出效果！！做拉丝见 `video-camera-fundamentals-notes.md`
- **Saber 黑色描边发光**：图像画好蒙版 → Saber 的 `Customize Core` 设为
  `Layer Masks` → 加 `unMult`（有颜色处 alpha=1、无颜色处 alpha=0）→
  纯黑图层 Alpha 遮罩——**unMult 的思路 = Nuke 里 Premult 的逆运算**
- Saber 光柱核心弄淡：`Halo Intensity` 调 0 + `Core Softness` 拉满（25）
- 边缘模糊（AE/Fusion/Nuke 同一思路）：rgba 复制一份 → 高斯模糊当 alpha →
  原素材被模糊 alpha 遮罩。**Nuke 正确完整工作流见 `edge-blend-correct-workflow.md`**

## 7. Fusion 节点操作要点（与 Nuke 异同）

- **简单合成**：MediaIn1 = 原视频、MediaIn2 = 透明通道；**连反了就把 merge
  用 `mask` 模式**（Nuke 里对应换 A/B 或换 Merge 操作）
- **导出**：顶部菜单 `Fusion → 渲染所有的保存器节点`，一次性渲染所有
  `Saver` / `FBXExporter`
- **FBX 导出用 `ascii` 版本**（兼容性好）
- `ACES Transform` 节点转 ACEScg（给特效部门流程，见
  `color-science-pipeline-notes.md` 第 12 节）
- Fusion 中视频坐标体系（截图见原笔记 `QQ截图20240703091544.png`）

## 8. 插件清单中值得知道名字的（交接时对方可能提到）

- 抠像/合成：**Primatte Keyer**（红巨星，专业抠像）、**Supercomp**（红巨星，
  光效合成一体化）、**Knoll Light Factory**、**Optical Glow**
- 跟踪：**King Pin Tracker**（平面跟踪）、**Spot Clone Tracker**（物体移除
  克隆跟踪）、**Lockdown**类褶皱需求 → Mocha Pro
- 镜头：**Lens Distortion Matcher**（红巨星，镜头失真匹配——Nuke 侧见
  `lens-distortion-save-load.md`）
- 色差/色散：`uni.Chromatic Aberration`、`S_WarpChroma`、`Separate RGB`、
  `EFX Chromatic Aberration`
- 三维通道：`Gaussian Splatting`（导入三维高斯场）
- 批量：`Multi Replacer`（批量替换图片）、`pt_TextEdit`（批量改文本）

## 9. AE 自带效果 ↔ Nuke 节点对照（看 AE 工程时翻译用）

| AE 效果 | 作用 | Nuke 对应 |
|---|---|---|
| `动态拼贴` | 素材上下左右复制拼接变大 | `Tile` / `Mirror` + Transform |
| `CC Lens` | 边缘失真（桶形/枕形） | `LensDistortion`（见 `lens-distortion-save-load.md`） |
| `Echo` | 回声残影 | `TimeEcho` / `TimeOffset` 链 |
| `S_Shake`（蓝宝石） | 相机抖动 | `Transform` + `random()` 表达式 |
| `CC RepeTile` | 突破图层尺寸限制重复平铺 | 扩大 bbox 后 `Tile` |
| 高斯模糊 | — | `Blur`（`B` 键） |
| `径向模糊` | 旋焦效果 | `DirBlur` |
| `镜头模糊` | 相机景深模糊 | `ZDefocus`（需 depth 层） |
| `自动追踪`（Auto-trace） | 按通道自动生成蒙版，动态素材也可以 | `Roto` 无直接等价，可用 keyer+luminance key 思路 |
| 棱镜模糊 | 好看的模糊畸变（蒙版反选主体后上效果） | `ChromaticAberration` 类 gizmo / `DirBlur`+通道偏移 |
| 摇摆器（Wiggler） | 按频率/幅度给属性批量 K 随机帧 | 表达式 `random()` 直接写，不用 K 帧 |
| 动态草图（Motion Sketch） | 手绘轨迹自动生成位置关键帧 | 无等价，用 Tracker 或手 K |

**AE 生成自定义路径**（createPath 表达式，点+切线句柄造贝塞尔路径）：

```javascript
A = thisComp.layer("形状图层 2").transform.position;
B = thisComp.layer("形状图层 1").transform.position;
C = thisComp.layer("空 3").transform.position;
D = thisComp.layer("空 4").transform.position;
createPath(points = [A, B], inTangents = [A, C], outTangents = [D, B], isClosed = false)
```

**序列图层**（AE 把多图层按时间首尾相接/重叠排列）：右键
`关键帧辅助 → 序列图层`；重叠填负值 = 图层间留间隙。Nuke 里对应
`AppendClip` / `TimeDissolve` 时间线操作（见 `production-best-practices.md` 第 7 节）。

## 10. AE 快捷键最小集（进 AE 工程救场时）

| 键 | 功能 |
|---|---|
| `P` / `S` / `T` / `R` | 位置 / 缩放 / 透明度 / 旋转 |
| `M` / `F` | 遮罩 / 遮罩羽化 |
| `U` | 显示所有关键帧 |
| `F9` | 关键帧缓动 |
| `Ctrl+Shift+C` | 预合成 |
| `Page Up/Down` | 前进/后退一帧 |
| `Ctrl+Alt+F` | 缩放至合成大小 |

- AE 切换中英文：改 `Support Files\AMT\application.xml` 里
  `installedLanguages` 的 `zh_CN ↔ en_US`（Mac 在
  `/Library/Application Support/Adobe/After Effects/<版本>/AMT`）

## 易错点

- **AE 的 `time` 是秒不是帧**：迁移表达式到 Nuke 时 `time` → `frame`，
  所有系数要按帧率重算（Nuke 的 `frame` 是帧号）
- **AE 图层制思维带进 Nuke**：AE 靠图层上下遮挡，Nuke 靠 B-pipe 数据流；
  AE 的"预合成"≈ Nuke 的 Group，但预合成会折叠变换/栅格化时机不同
- **EXtractoR 思维**：AE 要插件才能取 EXR 分层，Nuke 原生 Shuffle 直接读——
  别让 AE 流程把多层 EXR 先拆成单层文件再给你，直接要原始多层 EXR
- **Optical Flares alpha 坑**：alpha 不全 1 就不出光——Nuke 里复刻镜头光效时，
  先确认上游 alpha 通道状态
- **Fusion merge 的 mask 模式 ≠ Nuke 的 mask 输入**：Fusion 连反素材时改 merge
  模式解决；Nuke 里对应的是换 A/B 输入或 `stencil` 等模式，别混淆概念
- **Cineon 转换器当色彩管理用**：AE 的 `Log to Linear` 只是 gamma 曲线转换，
  不含色域矩阵；完整 ACES 转换必须走项目色彩空间 + 解释素材，别拿
  Cineon 转换器冒充 IDT
- **AE 内容识别填充硬上大位移镜头**：对象法只估算有限运动，运动剧烈的镜头
  填充会穿帮；这类活在 Nuke 里用跟踪贴片更稳
- **蒙版 -1 扩展滥用**：AE 蒙版扩展 -1 只救 1px 留白，更大的边缘问题在 Nuke
  里用 erode/edge 流程解决（见 `production-best-practices.md` Roto 节）
- **FBX 忘选 ascii**：Fusion 导出的二进制 FBX 部分软件读不了，统一用 ascii
- **帧率自适应公式漏写**：Fusion 表达式写死时长，换帧率工程动画全错；
  用 `24/comp:GetPrefs("Comp.FrameFormat.Rate")` 做动态系数
