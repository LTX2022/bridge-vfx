# 运动模糊与运动矢量（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "SmartVector" / "运动模糊" 节。
原始笔记保持只读；本文件是 AI 运动矢量与运动模糊的蒸馏版。

## 0. 两条主路：渲染时 vs 后期

| 维度 | 渲染时运动模糊 | 后期运动模糊 |
|---|---|---|
| 触发 | 渲染器开关 | 合成时 |
| 速度 | 渲染时长**成倍**增加 | 仅增加合成时间 |
| 精度 | 真实 3D 速度场 | 二维逐像素矢量（单一向量值） |
| 透明度/遮挡 | 正确 | **无法还原真实运动模糊的透明度和遮挡关系** |
| 推荐 | 大场景 | 单帧 1~3 个物体 |

> 镜头虚焦模糊同样存在后期无法保留真实空间的遮挡和透明度问题。
> 后期添加的虚焦无法保留真实空间的遮挡和透明度关系。

## 1. MotionBlur 节点（基础）

- `Source` 端连接素材
- `Shutter Samples`：采样率，叠多少画面做模糊
  - 采样率 3 = 3 等分 → 叠 3 个重影
  - 重影是运动模糊节点通过运动矢量计算出来的
- `Shutter Time`：时间跨度，定义运动模糊有多大
  - 时间跨度越远 → 运动模糊拉得越长

**注意**：如果镜头中还有其他快运动的物体，把需要做运动模糊的地方单独
裁切出来做运动模糊，再合成回去。

> `cc force motion blur`（属于矢量运动模糊）只能作用于 AE 中有关键帧动画
> 的数据信息，是基于 K 的动画轨迹来模拟出运动模糊效果。
> `rsmb` 和**像素运动模糊**就是基于视频画面的每一帧的像素位移来计算。

## 2. VectorBlur 节点（基于 motion vectors 通道）

**前置条件**：

- 渲染的物体上有 `v` 速度属性（Houdini SOP Attribute Wrangle 加
  `@v = @P - @P.opinput(1);` 即可拿到逐点速度）
- 在 `uv channels` 选中正确的**运动矢量通道**（一般 `motionvectors`）

**关键参数**：

- `blur uv` 参数使用 `Linear` 的模糊更加真实

**报错解决**：`VectorBlur: Input is missing motionvectors.red, motionvectors.green`

- 使用前，需要把运动模糊的 xyz 传输到运动模糊的 rgb 通道上：
  1. 用 `Shuffle` 节点把 `motionvectors` 层复制到 rgba（仅 R、G 通道）
  2. 或者用 `VectorToMotion` 把矢量转为 motion 通道再走

nuke-bridge 自动化：

```python
# 把 motionvectors 通道 shuffle 到 rgba.rgba
sh = nuke.createNode("Shuffle", inpanel=False)
sh["in"].setValue("motionvectors")
sh["out"].setValue("rgba")
sh["red"].setValue("red")
sh["green"].setValue("green")
sh["blue"].setValue("red")  # 占位，blur 只看 rg
sh["alpha"].setValue("red")
sh.setInput(0, read)

vb = nuke.createNode("VectorBlur", inpanel=False)
vb["uv_channels"].setValue("rgba")  # 使用前面 shuffle 出的 rgba
vb["blur_uv"].setValue("linear")
vb.setInput(0, sh)
```

## 3. SmartVector（最稳的 AI 运动矢量生成器）

**用户 9 步法（已多次实践）**：

1. `SmartVector` 节点连接到 `Read` 节点
2. **设置 `Vector Detail`** 控制到所需的详细信息级别
   - 默认值 `0.3` 对于**低细节和低移动的序列**已经足够
   - 正在处理的区域相对较小 → 默认值 0.3 可能无法正确捕捉运动
     → 增加到 `1.0` 捕获更多细节
   - 高细节矢量需要更长的渲染时间
3. 设置 `Strength` 控制以强制帧之间像素匹配
   - 较高的值：精确匹配局部细节，但运动场可能参差不齐
   - 较低的值：可能错过局部细节但能提供更平滑的结果
4. 前景中有很多移动 → **需要添加遮罩**（减少边缘伪影）
5. 将**运动矢量写入磁盘**：单击 `Export Write` 自动添加 Write 节点
   - 只能将运动矢量写入 `.exr` 格式
   - channels 设 `all`、file type `exr`
6. 路径填好后单击 `Render`
   - SmartVector 默认不输出 `motion` / `forward` / `backward` 通道
   - 需要这些通道：在 SmartVector 节点之后添加 `VectorToMotion` 节点
   - `VectorToMotion` 可与 `VectorBlur` 一起使用创建运动模糊
7. 启用 `Advanced > Flicker Compensation` 减少亮度和整体闪烁的变化
   - 例：从有光泽表面反射的光
8. `Tolerances` 的 `Advanced` 部分：调整计算图像亮度时每个颜色通道的权重
   - 很少需要调整，但可增加特定颜色的权重
9. **将绘画添加到源** 或 **向源添加图像**（用 `Viewer` 实时预览）

### SmartVector 实践参数详解

- `Vector Detail`：记录位移的准确度
  - 数值越大，矢量图精度越高，保留更多细节度及运动准确性
  - 更长的处理及渲染时间
- `Strength`：需要花多大强度与前一帧的图像做对比
  - 数值越大，更注重细微运动变化，但可能导致更多抖动
  - 数值越小，更平滑的运动曲线，但可能降低精度
- `Export Write`：创建 Write 节点，将矢量图写入磁盘
- `Reference Frame`：参考帧
  - 在哪一帧对原图进行修改，就填入哪一帧
- `Frame Distance`：想变形的帧数距离参考帧多少内精度比较高
  - 数值越小，离参考帧越近的效果越好
  - 数值越大，离参考帧越远的效果越好
  - **多尝试几个数值**，获得最佳效果

### 矢量图边缘问题

> 矢量图在生成的时候没办法判断边缘的点是怎么运动的，所以边缘会有很明显的拉伸，
> 需要的则是在之前 roto 出需要做后期的部分即可（roto 就不用跟踪了）

### 遮蔽前景和背景区域

视频内容是由在背景上移动的前景对象组成的，运动估计可能会在两者之间的边缘混淆。

1. 在源的下游添加 `Roto` 节点
2. 在要标记为前景或背景的区域周围绘制遮罩
3. 设置：
   - `Matte Channel` 至 `Matte Alpha`
   - `Output` 控制到 `Foreground` 或 `Background`
4. 如果正在使用 `Background` 向量，可以启用 `Inpaint Matte Region`
   - 使用最近的可用背景矢量自动填充丢失的前景矢量
   - `Matte Dilation` 滑块控制应用修复之前的遮罩扩散量
5. 可以使用修复来有效地忽略前景，从而允许在遮罩区域中使用背景矢量

## 4. RSMB（行业金标准）

- **网友说法**：可以用蓝宝石插件的 rsmb 节点，但是 Rsmb 只有 xy 方向
  （REVisionFX Effections）
- 蓝宝石插件平替
- VectorMotionGroup（林君义 lin 插件包）的优势：
  1. nuke 自带节点 兼容度好 不卡不崩
  2. 结算过程可以渲染预合成 速度快
  3. 效果几乎和 RSMB 一样
  4. 大小可控
  5. 给别人交换工程对方不需要安装插件就能打开

## 5. Kronos / oflow / retime（变速 + 自动运动模糊）

- `Kronos`：减速或加速画面（需要精确控制用于较大的时间范围，即很高的快门时间的运动矢量）
- `oflow`：光流法变速
- `retime`：单纯改速度，**没有**运动模糊

## 6. SmartVector 配合 VectorDistort 做"修改区域擦除/添加"

`SmartVector` + `VectorDistort` 的常见用法：

- SmartVector：生成矢量图（位移信息）
- VectorDistort：读取矢量图（使用矢量图进行扭曲）
- 矢量图记录的便是画面中任何一个像素点，与前一帧相比，其发生的位移数值
- 会尽可能记录下图像中每一个点和它所移动的方向和距离

**操作流程**：

1. 在 Read 后挂 `SmartVector` → 生成运动矢量
2. 调整 `Vector Detail` / `Strength`（角度和环境光都可能会影响）
3. 在 `VectorDistort` 的 `Reference Frame` 填入"哪一帧对原图进行了修改"
4. 在 `Frame Distance` 内插值
5. 在"进行修改区域"里放上要擦除、添加的任何素材
6. 用 `FrameHold` 冻结该帧所在位置（如需）

## 7. nuke-bridge 自动化 SmartVector 节点的最小工作流

```python
import nuke  # nuke_run 中 nuke 已被注入，不要 import
r = nuke.toNode("Read1")  # 假设已有 Read 节点
sv = nuke.createNode("SmartVector", inpanel=False)
sv.setInput(0, r)
sv["vector_detail"].setValue(0.3)         # 静态场景 0.3 即可
sv["strength"].setValue(0.5)              # 平衡值
sv["flicker_compensation"].setValue(True)  # 减少亮度闪烁伪影

# 写到磁盘
w = nuke.createNode("Write", inpanel=False)
w.setInput(0, sv)
w["file"].setValue("C:/out/motionvectors/v.%04d.exr")
w["file_type"].setValue("exr")
w["channels"].setValue("all")
w["create_directories"].setValue(True)
# 渲染
nuke.execute(w, 1001, 1001, 1)
```

## 8. 易错点

- **不要在禁用 `VectorBlur` 的状态下交付**：它每帧都会重算，禁用也在跑
- **运动矢量文件大小**：默认 4K EXR 单帧 ~50MB；规划磁盘
- **`SmartVector` 必须挂 `Read` 后面**：它要从原始 RGB 计算
- **矢量图边缘拉伸**：用 roto 把要做后期的部分抠出来，roto 不用跟踪
- **Nuke 16+ 用 PySide6**（老插件要改 import），SmartVector 本身不受影响
