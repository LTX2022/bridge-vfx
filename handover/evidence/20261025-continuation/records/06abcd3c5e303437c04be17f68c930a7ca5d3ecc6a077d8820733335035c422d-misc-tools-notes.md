# COPs / AI / 高斯泼溅 / 机器学习小笔记合集（学自用户笔记 Cop模块.md, Houdini+Ai.md, 高斯泼溅.md, 机器学习.md, 2026-08-25）

来源：`C:/Users/<USERNAME>/OneDrive/Node/Node/Houdini基础模块/Cop模块.md`、
`Houdini+Ai.md`、`高斯泼溅.md`、`机器学习.md` 全文。
原始笔记保持只读；本文件是蒸馏版——保留具体参数、坑、资源链接，作为
`references/workflows/copernicus`、`ml` 通用指南的实战补充。
（图片链接保留原样，截图见原笔记。）

## 1. COPs 环境（新版 Copernicus）

参考：[国外大佬文档 tokeru cgwiki](https://tokeru.com/cgwiki/HoudiniCops.html)

### 新旧版本定位（重要认知）

- 新的用 Copernicus、旧的用 COPs，里面两个环境的节点功能都不一样——**有些功能老版有、新版没有**
- **新版本不是用来做合成的**：虽然它能做一些合成的东西，但最终定位是**做程序化纹理**
- `file` 文件载入图片时会**自动乘上 alpha 通道的贴图**——想要纯取单个通道的线性图时，
  `rgbtomono` 好像没用（直接就被预处理掉了），需另想办法绕过自动预乘

### COPs 常用节点

| 节点 | 作用 |
|---|---|
| `null` | 标识节点树输出 |
| `Fetch` | 引用 Null，让 cop 环境整洁很多 |
| `ROP Image OUT` | 指定要渲染输出的 COP |
| `SOP Import` | 导入 sop 环境下的模型；**不勾选 `Use External SOP` 则是在内部创建一个 sop 环境** |

### 材质：Bake Geometry Textures（高低模烘焙）

- 烘焙几何纹理：以交互速度在**低模和高模之间**烘焙生成纹理——将高分辨率表面的详细特征
  表示为低分辨率表面上的纹理贴图
- 创建一个 `Bake Setup` 节点，将自动创建烘焙所需的多个节点
- `Tracer` 参数：要使用的光线追踪器；**OptiX 仅在 NVIDIA 硬件上可用**
- 节点下方可以切换查看不同通道
- ![QQ20251008-203440.png](./图片/Houdini/QQ20251008-203440.png)
- 脏污贴图案例（截图见原笔记：F2564A07BE8DB60FF82D6F2E95217C6F.png）

### 导入导出：导出给图片用

在贴图参数的 `Texture` 下，使用 `op:` 后面跟上 COPs 输出节点的路径，
就可以将图片输出到指定路径上：

```
op:/obj/.../cop2net1/OUT
```

![QQ20251025-084802.png](./图片/Houdini/QQ20251025-084802.png)

## 2. Houdini Agent（AI 资产管理）

- [Houdini agent——具备 AI 功能的 DCC 资产管理器](https://github.com/Kazama-Suichiku/Houdini-Agent/tree/main)
- [SideFX Houdini 21 的 agent 人工智能——本地优先，工具使用，零幻觉](https://github.com/anshul-vashist/Houdini-Agent)

## 3. 高斯泼溅（3D Gaussian Splatting）资源

| 资源 | 说明 |
|---|---|
| [AHOLO](https://www.aholo3d.cn/) | 空间智能平台：物体 3DGS 重建、空间 3DGS 重建、AI 3D 空间生成 |
| [Aholo AI Skill](https://studio.aholo3d.cn/resources/tutorials/aholo-ai-skill) | 在 AI Client 中对话实现 3DGS 物体与空间重建、AI 3D 空间生成 |
| [AHOLO Open API](https://labs.aholo3d.cn/api-docs/skills) | 开放 API |
| [COLMAP 手册](https://colmap.github.io/) / [下载资源](https://demuc.de/colmap/) | 三维重建工具；通用运动结构（SfM）和多视角立体（MVS）流水线，图形+命令行接口；自动重建功能一键完成。BSD 许可证 |
| [DIVSHOT 客户端培训平台](https://github.com/fenghuayumo/DIVSHOT) | [官网 divshot.app](https://divshot.app/)：轻量级辐射场渲染器和训练平台客户端；支持灵活编辑工具，可编辑/裁剪训练好的高斯碎片导出，渲染成图像或视频 |

Houdini 中的高斯泼溅技术（截图见原笔记：图片生成-1781511325295.jpg、
ScreenShot_2026-08-03_191548_216.jpg）
![incremental-sfm.png](./图片/Houdini/incremental-sfm.png)

## 4. Houdini 机器学习

官方文档：[Houdini 的机器学习](https://www.sidefx.com/docs/houdini/ml/index.html)

### 常用节点

| 节点 | 作用 |
|---|---|
| `ML Volume Upres` | 体积低模变高模（详见下文 Pyro 节） |
| `Neural Point Surface` | **使用预训练卷积神经网络将点云转换为 VDB 表面**（可抵消水的闪烁等，保持锐利和高频率） |

训练节点：

| 节点 | 作用 |
|---|---|
| `ML Extract Example` | 从一组示例中提取单个示例 |
| `ML Regression Inference` | 在几何网络中应用使用 ML 训练回归训练的模型 |
| `ML Train Regression` | 训练神经网络进行回归 |
| `ML Regression Linear` | 验证数据集是否正确生成——根据线性模型确定输出，该模型最佳拟合给定的标记示例 |
| `ML Train Style Transfer` | （TOP 节点）训练神经网络在图像对之间进行风格转移 |

### Neural Point Surface（NPS，神经点表面）

原文：[Neural point surfacing](https://www.sidefx.com/docs/houdini/mpm/nps.html)

`Neural Point Surface` 节点的 `Neural Model` 参数定义要用于执行推理的预训练模型。
（截图见原笔记：QQ20251008-235239.png、QQ20251009-001137.png、QQ20251009-001308.png）

使用神经点表面的利与弊：

- 优势：
  - 局部治疗，而不是具有整体影响的形态学手术
  - 一些所需的功能更容易通过示例来描述
  - 单节点解决方案，艺术家更容易快速获得美观表面
- 弊：
  - **控制较少**——一旦训练完毕，模型就会充当黑匣子
  - 面向 GPU——**CPU 基础干扰可能非常慢**

**神经模型选择速查**：

| 模型 | 特点 |
|---|---|
| `Balanced`（默认） | 大多数情况表现良好；**必须保留实体模型锐利特征时可能提供最佳结果** |
| `Smooth` | 针对平滑表面重建优化；缺乏高频细节，但可消除光滑表面上的更多颠簸 |
| `Liquid` | 优化重建液体模拟；保留光滑曲面及波浪拍打/翻滚的急剧过渡；擅长以时间稳定的方式连接附近水滴重建薄水片 |
| `Granular` | 正确捕获粗糙颗粒状表面；尝试忽略密集表面附近的松散点以减少模糊性、获得更明确形状，同时保留与表面完全分离的松散点。**对 Chunky MPM 材质特别有用** |
| `Custom` | 使用未随 Houdini 提供的自定义模型 |

### ML Volume Upres（Pyro 提分）

> 与直接提高 pyro 模拟分辨率相比，能稍快获得高分辨率结果，而且**不会改变 pyro 模拟的
> 整体形态**——可以在更低精度、更快速的模拟上花更多时间微调，然后把增强节点简单地
> 作为最终质量的一个过滤器，意味着更大的模拟不需要更多显存。
> 但训练新模型仍需投入几个小时才能获得可运行的模型。

**使用预先训练好的模型**：

- 安装 `houdini21` 版本会自带两个 `billowysmoke` 的机器学习模型，可直接使用，
  **适用范围很广**（相当多的 Pyro 模拟）
- 理论来源：[up-res（Wavelet Turbulence for Fluid Simulation）论文](https://www.cs.cornell.edu/~tedkim/WTURB/)
- （截图见原笔记：QQ20251008-230947.png、QQ20251008-230156.png）

`ML Volume Upres` 参数（使用预训练 ONNX 模型放大和锐化输入 Volume）：

| 参数 | 说明 |
|---|---|
| `2x` | 提升到 2 倍精度；**使用 2 个节点串联 = 4 倍精度** |
| `Volume` 参数 | 最好设置对应要增强的体积字段（**一般都是 `@name=density`**） |
| `Naive Upsample Other Fields` | 勾选后对已处理字段之外的其它字段启用上采样（比如温度和速度，**这样就不会出现渲染伪影**） |
| `Pre Sharpen` / `Post Sharpen` | 预锐化/后锐化，对锐化作用很大 |
| `Number of Passes` | 预锐化/后锐化的迭代次数，**5 次左右是比较好的结果** |
| —— | 这是需要自行训练的机器学习模型，所以没有太多参数选项 |

**训练新模型**：

- `ML Train Volume Upres`：用来训练新模型
- 可以自带数据训练自己的模型；其中一些训练完全摆脱了 Python，**可以只使用 SOP 完成所有训练**
- （截图见原笔记：QQ20251008-230606.png）
- 原理：直接提高分辨率会极大增加计算量；upres 方法在增加分辨率的同时尽量不增加计算
  时间——没有进行真正的流体计算，而是借用低精度的流体速度加上一些特殊噪波，
  实现更精细的速度。简单说就是一个**廉价提高精度的方式**；在 H10、H11 时代，
  这种 upres 就是工具架默认的方式

## 易错点

- **新版 Copernicus ≠ 合成器**：拿它当 Nuke 做合成是方向错误，它的定位是程序化纹理；
  且新旧两套 COP 节点功能不完全对等，老版有的功能新版可能没有。
- **`file` 载入图片自动预乘 alpha**：想取纯单通道线性图时 `rgbtomono` 会被预处理掉，
  拿不到预期结果，需要绕开自动预乘。
- **`SOP Import` 的 `Use External SOP`**：不勾选时会在节点内部创建 sop 环境，
  引用外部 SOP 忘勾会导致引用失效。
- **`Bake Geometry Textures` 的 OptiX**：只在 NVIDIA 硬件上可用，A 卡/核显选了会出错。
- **COPs 结果给其他节点用**：贴图参数走 `op:` + COPs 输出节点路径，别先落盘再读。
- **NPS 是黑匣子**：训练完毕后控制较少，且 CPU 上推理可能非常慢——优先 GPU，
  并按表面类型选对 Neural Model（锐利特征用 Balanced、液体用 Liquid、颗粒用 Granular）。
- **`ML Volume Upres` 忘设 Volume 字段**：默认不是只处理 density——不指定
  `@name=density` 会把不该增强的字段一起处理；温度/速度等字段要靠
  `Naive Upsample Other Fields` 朴素上采样，否则出现渲染伪影。
- **锐化迭代不是越多越好**：`Number of Passes` 5 次左右是比较好的结果。
- **2 个 `2x` 节点是 4 倍精度**：串联翻倍要意识到显存/数据量也是平方级增长。
