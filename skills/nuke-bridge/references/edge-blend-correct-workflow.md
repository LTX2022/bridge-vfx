# 边缘融合正确工作流（学自用户笔记 Nuke.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 铁律顺序：抠像 → FilterErode(收缩) → Blur → EdgeExtend → Premult → Merge；顺序反了=硬边/脏边，merge 后再 extend 无效
> - 千万不要：直接 Merge 元素+Roto 蒙版；不做先 shrink 再 extend；不收缩元素边缘就 merge
> - 标准节点链及参数：Read → Roto 抠像 → FilterErode(size=-1.5，负值=收缩) → Blur(size=1.0，channels 只设 "a") → EdgeExtend(EdgeSize=3.0 去黑边、Erode=0.5) → Merge2(over，前景=A=0、背景=B=1)
> - FilterErode：负值收缩、正值扩展，单位像素；收缩到「没有模糊的边缘」为止
> - Blur 只在 alpha 通道上做（channels="a"），绝不要 blur rgba
> - Premult 必须在 Merge 之前（否则带白/黑边）；LightWrap 必须在 Premult 之后、Merge 之前（A 接前景、B 接背景再接回前景）
> - 方法选型：标准 4 步法（最常用）；IBK+收缩+边缘（绿幕有褶皱/阴影/不均匀）；核心+边缘+附加（发丝/半透明极端抠像）
> - 方法 3 结构：核心 Key(Primatte)→FilterErode+Blur，边缘 Key(IBK)→Grade 调 alpha，ChannelMerge 合并两个 alpha → Premult → Despill → 附加 Keyer(头发表) → Merge
> - 不同元素层各自处理完再合并（不要一锅烩）；每层单独做虚化
> - 不要重复做 EdgeExtend（边缘反复扩张）；合并前确认 B pipe 顺序

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "更好地进行边缘融合" 节。
原始笔记保持只读；本文件是"4 步法"边缘融合的蒸馏版。

## 0. 千万不要这么做（错误示例）

用户在笔记里直接批注了"千万不要这么做"的典型错误：

1. **直接 Merge 元素 + Roto 蒙版**（没有 Edge Extend / Filter Erode / Blur 调整）
2. **没有先 shrink 再 extend**——导致边缘硬边被无限放大
3. **没有在 merge 前对元素本身做边缘收缩**——硬边直接进入合成

**结果**：边缘硬、有色偏、放大看很脏。

## 1. 正确 4 步法

1. **先抠像扣到物体上**——先有准确的元素
2. **收缩直到没有模糊的边缘**（Filter Erode + Blur）
3. **边缘伸展以修复受损的边缘**（EdgeExtend）
4. **合并特效元素**

## 2. 三种常用方法（按场景选）

### 方法 1：标准 4 步法（最常用）

```
[Read 元素] → Roto 抠像 → FilterErode → Blur → EdgeExtend → Merge
```

- **FilterErode**：负值收缩、正值扩展
- **Blur**：柔化边缘（避免硬边）
- **EdgeExtend**：侵蚀或扩大样本区域，从遮罩内部或外部更深处提取像素，
  校正遮罩边缘

### 方法 2：IBK + 收缩 + 边缘

```
[Read] → IBK Colour (做干净绿幕) → IBK Gizmo (抠像) → Grade 调 alpha →
ChannelMerge (合并多个 alpha) → Premult → Merge
```

适用：绿幕/蓝幕有褶皱、阴影、不均匀的情况。

### 方法 3：核心 + 边缘 + 附加

```
[Read 元素] → 核心 Key (Primatte) → FilterErode + Blur →
[Read 边缘] → 边缘 Key (IBK) → Grade 调 alpha →
ChannelMerge (两个 alpha 合并) → Premult → 
Despill (去溢色) → 附加 Keyer (头发表) → Merge
```

适用：发丝、透明、半透明等极端抠像场景。

## 3. 关键节点参数详解

### FilterErode

- 负值：收缩 alpha（向内腐蚀）
- 正值：扩展 alpha（向外膨胀）
- 单位：像素
- 调大调小影响边缘锐利度

### Blur（边缘模糊节点）

- 通常是 `Blur` 节点（不是 `Bokeh`/`Defocus`）
- 数值：像素
- **作用**：让边缘平滑过渡
- **注意**：只在 alpha 通道上做模糊（不要模糊 RGB）

### EdgeExtend

- `EdgeExtend` 节点：通过侵蚀或扩大样本区域，从遮罩内部或外部更深处
  提取像素的方法，来校正遮罩边缘
- 关键参数：`EdgeSize`（加大可以去黑边）
- 关键参数：`Erode`（微调扭曲的范围）

### Premult

- `Premult` 节点：将输入的 rgb 通道乘以其 alpha
- 也就是对输入图像进行预乘
- 抠像 / 边缘处理后必须 Premult，否则会带边缘白/黑边

## 4. 关键原则

- **硬边是合成的一大忌**，尽量避免硬边
- 边缘处理的顺序不能反：先 shrink → 再 blur → 再 extend → 再 merge
- 不要在 merge 后再 extend（无效）
- 不同元素层各自处理完再合并，不要一锅烩
- 如果存在一些边缘处的虚化问题，最好单独在每一个物体层中做虚化

## 5. nuke-bridge 自动化：4 步法最小图

```python
# nuke_run 中 nuke 已被注入
import nuke

# 1. 读元素
fg = nuke.createNode("Read", inpanel=False)
fg["file"].setValue("C:/footage/element.%04d.exr")

# 2. 抠像（假设已用 Keylight 或 Primatte 完成抠像，输出带 alpha）
# keyl = nuke.createNode("Keylight", inpanel=False)
# keyl.setInput(0, fg)
# 自动化场景：假设 fg 节点 Read 出来的图像已经带正确 alpha

# 3. 收缩边缘（FilterErode）
fe = nuke.createNode("FilterErode", inpanel=False)
fe["size"].setValue(-1.5)  # 负值 = 收缩
fe.setInput(0, fg)

# 4. 模糊边缘（Blur）
blur = nuke.createNode("Blur", inpanel=False)
blur["size"].setValue(1.0)
# 关键：只在 alpha 上 blur
blur["channels"].setValue("a")  # 重要！
blur.setInput(0, fe)

# 5. 边缘伸展（EdgeExtend）
ee = nuke.createNode("EdgeExtend", inpanel=False)
ee["EdgeSize"].setValue(3.0)  # 加大可以很好地去掉一些黑边
ee["Erode"].setValue(0.5)
ee.setInput(0, blur)

# 6. 读背景
bg = nuke.createNode("Read", inpanel=False)
bg["file"].setValue("C:/footage/bg.%04d.exr")

# 7. 合并
m = nuke.createNode("Merge2", inpanel=False)
m["operation"].setValue("over")
m.setInput(0, ee)   # A = 前景
m.setInput(1, bg)   # B = 背景
```

## 6. nuke-bridge 自动化：方法 3（核心 + 边缘 + 附加）

```python
# 1. 读两个 mask（核心 + 边缘）
core_mask = nuke.createNode("Read", inpanel=False)
core_mask["file"].setValue("C:/footage/core_mask.%04d.exr")
# 边缘 mask（IBK 输出）
edge_mask = nuke.createNode("Read", inpanel=False)
edge_mask["file"].setValue("C:/footage/edge_mask.%04d.exr")

# 2. ChannelMerge 把两个 alpha 合并
cm = nuke.createNode("ChannelMerge", inpanel=False)
cm["channels"].setValue("a")  # 输出 alpha
cm.setInput(0, core_mask)  # A: core
cm.setInput(1, edge_mask)  # B: edge

# 3. 读去除溢色后的 RGB
rgb = nuke.createNode("Read", inpanel=False)
rgb["file"].setValue("C:/footage/despilled.%04d.exr")

# 4. Copy 把 alpha 写到 rgb
copy = nuke.createNode("Copy", inpanel=False)
copy["from0"].setValue("a")  # 把 alpha 从 cm 拷过来
copy["to0"].setValue("a")
copy.setInput(0, rgb)
copy.setInput(1, cm)

# 5. Premult
pre = nuke.createNode("Premult", inpanel=False)
pre.setInput(0, copy)

# 6. 读背景
bg = nuke.createNode("Read", inpanel=False)
bg["file"].setValue("C:/footage/bg.%04d.exr")

# 7. 合并
m = nuke.createNode("Merge2", inpanel=False)
m["operation"].setValue("over")
m.setInput(0, pre)
m.setInput(1, bg)
```

## 7. 关键易错点

- **FilterErode 的方向**：负值 = 收缩（你要的"收缩直到没有模糊的边缘"）
- **Blur 只在 alpha 上**：blur 节点 `channels` 设为 `a`，不要 blur `rgba`
- **EdgeExtend 顺序**：必须在 FilterErode + Blur 之后
- **Premult 顺序**：必须在 Merge 之前；否则会带白/黑边
- **LightWrap 位置**：必须在 Premult 之后、Merge 之前
  - LightWrap 通过将光线从背景"包裹"到前景对象边缘的反射，帮助对象合成到
    非常亮的背景中
  - A 端连接前景，B 端连接背景，然后再接回原来的前景素材
- **AdditiveKeyerPro**：保留细节，属于 NukeSurvivalToolkit 的插件
  - 需要输入清理了褶皱的"绿幕前景"和"绿幕背景"，还有用于图片合成上去的
    "背景素材"，便可以输出一个保留边缘、提取头发的所有细节的附加抠像结果
- **不要重复做 EdgeExtend**：多次叠加会导致边缘反复扩张
- **Clear B 端口**：合并前确认 B pipe 顺序（前景 = A=0，背景 = B=1）
