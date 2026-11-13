# AI 工具与 Cattery 模型（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "人工智能" / "Cattery" 节。
原始笔记保持只读；本文件是 Nuke 内置 AI 节点 + Cattery 模型的蒸馏版。

## 0. Cattery 是什么

[Cattery](https://community.foundry.com/cattery) 是 Foundy 官方 AI 模型市场。
模型转换为 `.cat` 文件后可在 Nuke 中本地运行。

**安装**：

- 解压后 Cattery 文件夹直接放到 `.nuke` 文件夹即可
- Nuke 启动自动识别

## 1. Cattery 模型速查（按场景选）

### 抠像 / 蒙版

| 模型 | 作用 | 关键参数 |
|---|---|---|
| **MODNet** | 将人体与图像分割开来 | (人体专用，速度快) |
| **Background Matting** | 背景遮罩（差值抠像） | (需背景干净板) |
| **Segment Anything from Meta** | 语义分割 | 点选对象或导出 cryptomatte 格式 |
| **ViTMatte** | 自然消光神经网络，从垃圾消光中提取高质量 alpha | (对显卡有要求，作者显卡不行) |
| **Face Makeup** | 面部解析 | 单独通道：嘴唇、鼻子、眼睛、眉毛、皮肤、颈部、头发 |

### 修复 / 擦除

| 模型 | 作用 | 关键参数 |
|---|---|---|
| **LaMa (Large Mask Inpainting)** | 图像区域修复 | 输入图像 + alpha 蒙版，用上下文细节填充 |

LaMa 擦除完整流程（用户笔录）：

1. 使用 `roto` 节点选取要擦除部位进行平面跟踪
2. 使用 `LaMa` 节点进行擦除
   - `Mask` 连接要擦除部位的 alpha
   - 另一端连接原素材
3. 复制粘贴刚刚的 `roto` 节点
   - 提取出擦除干净的部分
   - 进行冻结该帧所在位置
4. 使用 `roto` 生成一个 `CornerPin2D(absolute, baked)` 边角定位节点
5. 点击该节点的 `From` 选项卡
6. 在画面中将 4 个角拖到提取干净部分的 4 个角一一对应上即可

### 深度

| 模型 | 作用 | 关键参数 |
|---|---|---|
| **DepthPro** | 苹果开发的单眼深度估计 | 米为单位真实距离，物体边界清晰 |
| **MiDaS** | 单眼深度估计 | 相对深度（无米制） |

### 运动 / 跟踪

| 模型 | 作用 |
|---|---|
| **RAFT** | 机器学习运动估计器（生成准确而清晰的智能矢量） |
| **ABME** | AI 补帧（高质量机器学习运动估计器和帧插值器） |

### 语义分割

| 模型 | 作用 |
|---|---|
| **Semantic Segmentation** | 图像分割为预定义的语义类别（汽车、树木、人物、天空等） |

## 2. Nuke 内置 AI 节点（不需要 Cattery）

### CopyCat 节点

[CopyCat 教程](https://mp.weixin.qq.com/s/TNIgGX8d2N0UyRVFXOtWQQ)

> **数据量**：
>
> - 捕抓运动、光线、相机焦点有变化的图像（单个镜头）：1~30 帧的训练就可以在全部帧复制效果
> - 如果是训练通用数据集：1000~100w 张或更多
> - 大约 1~2w 张图像大小的数据集就足够训练 CopyCat 完成任务

Nuke 在 13 版本新加入的 `CopyCat` 节点是**基于深度学习**来完成**效果在不同帧的拷贝**。

> **原理**：构建人工神经网络来学习从输入到输出的权重参数。当数据输入时，
> 神经网络会给出一个输出结果，然后神经网络会通过比对自己的输出结果和
> 用户给与的示例差距在哪，来反向调整自身的权重参数，使下一次输出的
> 结果更接近用户给与的示例。

#### CopyCat 训练流程

**两个输入端**：

- `Input`：连接 RGB 图像
- `Ground Truth`：连接输出结果的示例（Alpha 通道）

**训练前**：

- 避免其他通道干扰，要 Remove 掉不需要的通道
  - `RGB` 端的 `Alpha` 删掉
  - `Alpha` 端的 `RGB` 删掉

**配置**：

- `Crop Size`：裁切大小，控制对输入数据的裁切范围
  - 在每次训练的过程中，输入图像并不是全部会输入模型
  - 而是随机一个位置裁切固定的大小来完成本次训练
  - 这个值设置的更大时，可能会提高训练结果的精度，但训练时间大幅增加
  - **一般默认 256 就可以了**
- `Data Directory`：设置一个保存检查点的路径
- 训练通道会显示 `rgb -> rgba.alpha`（输入 RGB 图像，输出的是 Alpha 通道）

**点击 `Start Training` 开始训练**

**训练结束后**：

- 点击 `Create Inference` 就可以使用最后一次保存的模型权重创建 `Inference` 节点
- `Optimize for Speed and Memory`：勾选后，节点的计算精度会从 32 位浮点
  降低到 16 位，减少计算时间和内存占用
  - **注意**：有时候勾选这个参数会造成输出出现伪影
- 也可以自己创建 `Inference` 节点，然后在 `Model File` 指定想使用的 `cat` 文件

**应用**：

- `Inference` 输入端连接到完整素材上，节点就会输出模型计算的结果
- 原始素材被裁切掉的边缘部分因为没有参与训练，可能会出现不确定的结果
- 需要用一个大的垃圾遮罩去掉
- 计算出的 Alpha 通道有时候也需要对边缘进行一些调节，并且去掉小于 0 大于 1 的值

#### 用 CopyCat 画遮罩（典型场景）

> 画 roto 是输入 RGB 颜色，然后让模型输出 Alpha 通道

**步骤**：

1. 先画几帧 roto，然后将对应帧的 RGB 颜色和 roto 的 Alpha 通道输入到 CopyCat 节点
2. CopyCat 会用 RGB 和 Alpha 不停的训练，找出 RGB 和 Alpha 的特征对应关系
3. 当模型达到一定精度的时候，就可以用来推算整个帧范围的 Alpha 了

**配置**：

- **Shuffle**：后边要自己画 roto 作为训练的 Alpha
  - 素材下边要加个 Shuffle 去掉素材自带的 Alpha
- **FrameHold**：用 FrameHold 定住选择的示例帧
- **roto**：示例帧下边加 roto 画出当前帧的 Alpha 范围
- **Switch 节点**：下边加一个 Switch 节点，按顺序连接好
  - 然后对 Switch 的 which **设置关键帧**
  - 在时间线第一帧设置为 0，第二帧设置为 1，第三帧设置为 2...
  - 以此类推直到所有示例帧都能遍历一遍
- **FrameRange 节点**：FrameRange 的起始帧设置为第一帧
  - 终止帧设置为一共有多少示例帧

#### 优化

- 训练的时候 CopyCat 会在画面随机的位置**裁切子画面**
- 为了能提高训练的效率，需要对画面进行裁切，让画面集中在人物和人物附近的区域
- `Crop` 裁切之后要勾选 `reformat` 选项去掉裁切掉的黑色区域

#### 实践注意事项

- 不要有中文路径
- 使用 NukeX 才可以使用
- `AppendClip` 会依此播放素材时间长度的一段静态视频，结束后就到下一个链接的素材
- 在 Prograss 窗口可以看见计算结果

### BigCat 节点

- 会从序列中的若干帧复制序列特定的效果（垃圾遮罩、美观修复或去模糊）
- 然后训练网络在整个序列中复制这些效果
- BigCat 会输出一个训练好的网络，格式为 `.cat` 文件
- 供推理节点应用你的效果

### SmartVector 节点（已专门整理）

详见 `references/motion-blur-and-vectors.md`

### CoTracker App（AI 跟踪）

[CoTracker3](https://github.com/facebookresearch/co-tracker)

> CoTracker 是一种基于 Transformer 的快速模型，可以跟踪视频中的任何点。
> 可以跟踪：
>
> - 视频中的任何像素
> - 一组准密集的像素
> - 可以手动选择点，也可以在任何视频帧的网格上采样

[CoTracker_Nuke_Integration_App（github）](https://github.com/fredhopp/CoTracker-Nuke)

利用 Facebook Research 的 CoTracker 在视频中进行点跟踪，并以与 Foundry Nuke 的
CornerPin2D 节点兼容的格式导出跟踪数据。

**安装**：

1. 下载好后，解压，进入解压文件夹内
2. 使用管理员打开 cmd，使用 `cd` 命令进入该文件夹
3. 创建并激活虚拟环境 `python -m venv .venv`
4. 安装依赖项 `pip install -r requirements.txt`
5. 启动应用程序 `python cotracker_nuke_app.py`
6. 打开浏览器并导航到 `http://127.0.0.1:7860`

**使用**：

1. 上传视频
2. 设置图像序列起始帧
3. 设置参考系
4. 蒙版绘制
5. 处理视频设置网格大小
6. 导出到 Nuke（生成 `.nk` 文件）
7. 还可以导出 `STMap` 序列，用于几何变换的动画 STMap 序列

### CopyCat 工程文件路径

`./脚本插件/Nuke/一些工程文件/Roto_template.nk` 这个路径找到 `Roto_template.nk`
这个工程文件

## 3. Cattery 安装与 ViTMatte 特殊说明

### 安装

```
下载好后，在文件夹里有这些东西：
  Nuke 文件夹内的所有文件直接拷贝到 C:\Users\你的用户名\.nuke
```

### ViTMatte 特殊说明

[ViTMatte GitHub](https://github.com/VEINFX/vItmATTE-FOR-nUKE?TAB=README-OV-FILE)

- 自然的消光神经网络，可以从垃圾消光（三映射）中提取高质量的 alpha
- 对显卡有一定要求（用户的显卡不行）
- 由于文件大小限制，需要从外部服务器下载：
  - [Cattery 和 TorchScript 模型](https://drive.google.com/file/d/1bXqdh4dD8bVpSEuNFk50WOEp12I2I4S4/view?usp=sharing)
  - 文件：ViTMatte.cat、VitMatte.pt（686M）

## 4. nuke-bridge 自动化 CopyCat 训练

**注意**：CopyCat 的训练主要是 GUI 交互（点 Start Training 看 Prograss 窗口），
nuke-bridge 能做的是：

1. 批量创建 Shuffle 节点切通道
2. 批量调整 Data Directory
3. 训练完成后批量创建 Inference 节点

```python
import nuke  # nuke_run 中 nuke 已被注入

# 1. 读素材
rgb = nuke.createNode("Read", inpanel=False)
rgb["file"].setValue("C:/footage/shot.%04d.exr")

# 2. 准备训练用 Shuffle（去掉 alpha）
sh = nuke.createNode("Shuffle", inpanel=False)
sh["in"].setValue("rgba")
sh["alpha"].setValue("black")  # 移除 alpha
sh.setInput(0, rgb)

# 3. 准备 Ground Truth（用 Roto 画）
roto = nuke.createNode("Roto", inpanel=False)
roto.setInput(0, rgb)

# 4. CopyCat 节点
cc = nuke.createNode("CopyCat", inpanel=False)
cc.setInput(0, sh)        # RGB
cc.setInput(1, roto)      # Ground Truth
cc["data_directory"].setValue("C:/cat_models/shot1")
cc["crop_size"].setValue(256)
# 训练是 GUI 按钮触发：cc["start_training"].execute()（取决于 Nuke 版本）
```

## 5. nuke-bridge 自动化 LaMa 擦除 + CornerPin2D

```python
import nuke

# 1. 读素材
r = nuke.createNode("Read", inpanel=False)
r["file"].setValue("C:/footage/dirty.%04d.exr")
r["first"].setValue(1001); r["last"].setValue(1250)

# 2. 画 roto 选要擦除的部位
roto = nuke.createNode("Roto", inpanel=False)
roto.setInput(0, r)

# 3. LaMa 节点
lama = nuke.createNode("LaMa", inpanel=False)
lama.setInput(0, r)        # 主输入
lama.setInput(1, roto)     # mask 输入
# 关键：mask 通道默认是 alpha，roto 输出 RGBA

# 4. 复制 roto 用于提取干净部分
roto_clean = nuke.createNode("Roto", inpanel=False)
roto_clean.setInput(0, lama)  # 输入改 lama（已擦除的）

# 5. Premult
pre = nuke.createNode("Premult", inpanel=False)
pre.setInput(0, roto_clean)

# 6. 冻结帧
fh = nuke.createNode("FrameHold", inpanel=False)
fh["first_frame"].setValue(1050)
fh.setInput(0, pre)

# 7. 提取干净部分作为边角定位目标
#    (实际工作流中需要用另一条 roto 选干净区域，再 Premult)
# 简化版：直接用 FrameHold 输出

# 8. CornerPin2D(absolute, baked) — 4 个点手动放
cp = nuke.createNode("CornerPin2D", inpanel=False)
cp["baked"].setValue(True)
# 4 个点 GUI 设置到擦除区域的 4 个角

# 9. 输出
w = nuke.createNode("Write", inpanel=False)
w["file"].setValue("C:/out/clean.%04d.exr")
w["file_type"].setValue("exr")
w["create_directories"].setValue(True)
w.setInput(0, cp)
```

## 6. AI 工具的算力要求

| 工具 | 算力需求 | 显存 |
|---|---|---|
| LaMa | 中 | 2-4GB |
| MODNet | 低 | 1-2GB |
| ViTMatte | **高** | 6GB+ |
| CopyCat | 中-高 | 4-8GB |
| BigCat | 中-高 | 4-8GB |
| Segment Anything | 高 | 6GB+ |
| Face Makeup | 中 | 2-4GB |
| RAFT | 中 | 2-4GB |
| ABME | 中-高 | 4-6GB |
| DepthPro | 中 | 2-4GB |
| MiDaS | 低-中 | 1-2GB |
| SmartVector | 低 | CPU 可用 |
| CoTracker | 中 | 2-4GB |

**用户原话**："ViTMatte 对显卡有一定要求，我的不行。"

## 7. 易错点

- **Cattery 模型下载**：每个模型单独下载（部分 686M 起步），注意磁盘空间
- **CopyCat 中文路径**：不能有中文路径——编码问题
- **CopyCat 必须 NukeX**：Indie 不可用
- **Switch 节点 which 必须打关键帧**：每帧切换不同示例帧
- **FrameRange 与示例帧数一致**：终止帧 = 示例帧数
- **Crop + reformat 配合**：裁切后勾 reformat 去黑边
- **LaMa 擦除边缘硬**：调 mask 的 blur，或多画几帧示例
- **CopyCat 训练完记得导出 .cat**：不然下次要重新训练
- **CoTracker 独立 App**：不是 nuke-bridge 工具——需要单独启动 python 服务
- **SmartVector 是 nuke 内置**：不需要额外 license；Cattery 模型需要 Cattery license
- **不要在同一项目用多个 .cat 模型同时推理**：显存可能爆
