# Deep 深度合成 + Cryptomatte（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "深度合成" / "cryptomatte" / "AOVs" 节。
原始笔记保持只读；本文件是 Deep 节点 cheat-sheet 和 cryptomatte 安装使用的蒸馏版。

## 0. 深度合成原理

> 深度合成就是给我们提供了三维空间中的位置信息，在后期合成中主要应用前后
> 遮挡关系。现在合成中比较主流的也是我们也会使用 Cryptomatte 来提取遮罩通道。
> 但是原理和 ID 层是一样的，只是会更方便高效。
> 深度合成更多的是用于特效渲染中遮挡信息的处理，比如烟雾等流体在三维空间中的
> 位置信息和与物体交互时产生的遮挡关系。核心是将 3D 空间的位置关系通过 2D
> 合成的方式进行合成处理。

## 1. Deep 节点 cheat-sheet（13 个最常用）

| 节点 | 作用 | 典型场景 |
|---|---|---|
| `DeepRead` | 读取三维渲染出来的深度素材（深度合成的第一步） | 读 VDB / deep EXR |
| `DeepWrite` | 输出 deep+ 深度数据 | 输出深度 EXR |
| `DeepMerge` | 和常规 Merge 节点一样，用于深度素材的合并 | 合成 deep |
| `DeepTransform` | 重新定位深度数据，可平移 X、Y、Z | 移动 deep |
| `DeepToPoints` | 将深度图像的信息转换为三维空间中的点 | 在 3D 视图看空间位置 |
| `DeepToImage` | 将深度信息合并展开为传统的 2D 图像 | 把 deep 拍扁成 2D |
| `DeepReformat` | 和常规 Reformat 一样，重置深度图像的尺寸和比例 | 改尺寸 |
| `DeepSample` | 深度信息的采样 | 取特定深度位置 |
| `DeepColorCorrect` | 和 ColorCorrect 用法相似，可控制不同深度位置的阴影中间调和高光 | 深度调色 |
| `DeepCrop` | 和 Crop 一样，改变前后的深度数据 | 深度裁剪 |
| `DeepExpression` | 深度数据的 tcl 表达式编辑 | 深度计算 |
| `DeepFromImage` | 将二维图像转换为深度图像，并为 Z 通道定义深度图像 | 2D → deep |
| `DeepFromFrames` | 将多个输入帧从 2D 图像复制到单个深度图像中 | 多帧打包 |
| `DeepHoldout` | 删除或者淡化深度中的遮挡部分 | 深度遮挡移除 |
| `DeepRecolor` | 用 color 端链 2D 颜色信息，展开深度输入中对应样本的颜色产生深度输出 | deep 上色 |

## 2. Cryptomatte 加密通道

### 是什么

> `Cryptomatte` 是一种多通道图像，通常采用 EXR 格式，可存储 ID 和像素夏盖对，
> 以及存储每个 ID 原始名称的其他元数据（无论是材料名称、对象名称、还是
> 任何用户属性）。它允许根据选定的 ID 提取遮置，这些 ID 可用于在合成中
> 进行微调时屏蔽特定元素。

### 安装

**下载**：

- 官方：https://github.com/Psyop/Cryptomatte
- 备用：百度网盘 `https://pan.baidu.com/s/1oLvBhxEDwQwoERYfbxazhA=ku4j`

**步骤**：

1. 下载好后，把 Nuke 文件夹内的所有文件直接拷贝到 `C:\Users\你的用户名\.nuke`
2. 重启 Nuke，菜单里就有 Cryptomatte 节点了

### 使用

- 通过专门做的一层 "ID 层"，可以在合成快速选中那个元素
- 像遮罩一样仅修改那一个选中的元素

## 3. 3 种深度雾法

### 方法 1：基于 Deep 通道的体积雾

1. 因为 Blender 将各通道渲染的命名和 Nuke 默认使用的通道名不一样
   - 所以通过 `Copy` 节点将通道转移到默认命名的通道上
2. 第一个 `Grade` 节点：调节深度通道值为 0~1 之间（超过了也没事）
   - 通过调高 `whitepoint` 参数来调节适合的深度值
   - 通过查看深度值为多少（`Ctrl + 鼠标左键点击`）来设置 `whitepoint`
3. 第二个 `Grade` 节点：
   - 调整 `multiply` 会使图像变暗，远处灯光等也会变暗
   - `offset` 可以增加图像中的散射量，环境中就会产生雾气，也可用其调整烟雾的颜色
   - `gamma` 可以将大气效果移近或移远相机
4. `keyer` 节点是将高光提取出来，因为光的损失是基于深度的，再模糊掉模拟光线损失

### 方法 2：使用背景原本颜色调节雾气颜色

1. `Shuffle` 节点：将深度通道给 `RGBA`
2. `P_Ramp` 节点：调节深度通道进行坡度过渡
3. 下面的 `Grade` 节点：调节 `gamma` 值增加 `alpha` 的强度，然后再模糊一下 `alpha`
4. `Saturation` 节点：降低一下饱和度，并模糊 `rgba` 通道
5. 通过 `mask` 的合并来传入 `alpha` 通道
6. `Multiply` 节点调节强度，与背景合并

### 方法 3：使用 Constant 节点调节雾气颜色

- 使用不同的 alpha 通道进行模糊，然后和原片叠加
- 适合雾气作为"前景层"的情况

### 方法 4：没渲染深度信息时（结合方法 2 用）

> 如果没使用背景渲染深度信息（可以使用此方法结合方法二来使用）

- A 通道是连接要合成素材的通道，B 通道是连接背景的通道
- 通过 `Shuffle` 节点将 `depth` 通道给 `rgba` 后，`Ctrl + 鼠标左键` 查看深度值最大是多少
- 假设深度值最大是 98，那么可以在 `Grade` 节点中的 `whitepoint` 设置在 98 左右
- 背景设置 `shuffle` 节点，增加一个 `Constant` 节点，将值设置得比最大深度值还要大一点
  - 比如 100
  - 通过 `shuffle` 把 100 的这个值传入到背景的 `depth` 通道中
  - 这样背景就有了深度值的通道
- 将 B 连接到 `merge` 中，`merge` 要开启额外通道 `depth` 才能合并深度通道

## 4. 根据相机距离自动淡化 3D cards 雾

**工作流**：

1. `DeepColorCorrect` 节点：用于深度合成的 ColorCorrect
   - 可以使用 DeepColorCorrect 创建遮罩
   - 方法是将 `Alpha` 通道的增益值设置为 0
   - 并将偏移值设置为您想要遮罩的范围内 1
2. `DeepToImage` 节点：将深度图像中的所有样本合并为常规 2D 图像
3. `DeepSample` 节点：单独连接 `ScanlineRender` 节点
   - 采样图像中各像素深度信息
   - 帮助检测和调整特定深度区域

## 5. nuke-bridge 自动化：Deep 节点连基础图

```python
# nuke_run 中 nuke 已被注入
import nuke

# 1. 读 deep EXR
r = nuke.createNode("DeepRead", inpanel=False)
r["file"].setValue("C:/footage/deep.%04d.exr")
r["first"].setValue(1001); r["last"].setValue(1250)

# 2. 在 deep 视图调节（用 GUI 选 viewer 模式）

# 3. 拍扁到 2D
d2i = nuke.createNode("DeepToImage", inpanel=False)
d2i.setInput(0, r)

# 4. 用 DeepColorCorrect 按深度做调色
dcc = nuke.createNode("DeepColorCorrect", inpanel=False)
dcc.setInput(0, d2i)
# 关键：darks/midtones/highlights 是按 Z 深度分段的，可设 3 组色温

# 5. 合成到 2D 背景上
bg = nuke.createNode("Read", inpanel=False)
bg["file"].setValue("C:/footage/bg.%04d.exr")
bg["first"].setValue(1001); bg["last"].setValue(1250)

m = nuke.createNode("Merge2", inpanel=False)
m["operation"].setValue("over")
m.setInput(0, dcc)
m.setInput(1, bg)
```

## 6. nuke-bridge 自动化：Cryptomatte 选择 mask

```python
import nuke

# 1. 读含 cryptomatte 的 EXR
r = nuke.createNode("Read", inpanel=False)
r["file"].setValue("C:/footage/render.%04d.exr")

# 2. 创建 Cryptomatte 节点
cm = nuke.createNode("Cryptomatte", inpanel=False)
cm.setInput(0, r)
# 在 GUI 里用 picker 选元素；选完后 cm["matteList"] 会自动记录 ID

# 3. 用 Shuffle 把 cryptomatte 输出变成可用的 mask
sh = nuke.createNode("Shuffle", inpanel=False)
sh["in"].setValue("cryptoAsset")  # 或 "cryptoObject"/"cryptoMaterial" 视层而定
sh["out"].setValue("rgba")
sh.setInput(0, cm)

# 4. 当 mask 用
g = nuke.createNode("Grade", inpanel=False)
g.setInput(0, r)
g.setInput(1, sh)  # B pipe: mask 从右入
```

## 7. 易错点

- **Deep EXR 渲染器要求**：Houdini Karma / Blender Cycles / RenderMan 等支持
  Deep EXR 输出的渲染器才有用；普通扫描线渲染器无深度信息
- **方法 1 vs 方法 2 选择**：方法 1 适合 deep 数据齐的，方法 2 适合背景色需保留
- **DeepColorCorrect 的 `alpha` gain=0 + offset=1** 等于"按 Z 范围做遮罩"
  - 这个 trick 经常被误用：mask 出来是反的，记得加 Invert
- **DeepToPoints 输出点云**：点的颜色是 sample 的颜色，可作 geometry 进一步处理
- **Cryptomatte 选 ID**：GUI 里点选后会把 ID 加到 `matteList` 列表
  - 自动化场景需要预先知道 ID 名称
- **`merge` 深度通道**：必须显式开 `merge` 的 `also merge` / `channels` → `depth` 通道
