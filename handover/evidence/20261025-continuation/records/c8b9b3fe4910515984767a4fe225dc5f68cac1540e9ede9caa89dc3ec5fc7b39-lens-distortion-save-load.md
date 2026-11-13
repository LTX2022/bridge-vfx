# 镜头畸变还原 / 套用（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "Nuke畸变还原" 节。
原始笔记保持只读；本文件是镜头畸变保存、还原、套用的蒸馏版。

> [H_ReDistort & GeoTracker](https://pan.baidu.com/s/1tJ24nnTks0miozeTcwGGCw?pwd=ntru)

## 0. 总览：4 步法（4 个关键节点）

| 步骤 | 节点 | 作用 |
|---|---|---|
| 矫正 | `LensDistortion` + `C_STMap` (forward) | 把畸变画面变成无畸变 |
| 输出 STMap | `LensDistortion` (STMap 模式) | 写出一张 STMap 文件 |
| 还原 | `C_STMap` (backward) + `Crop` | 把已合成画面贴回原畸变 |
| 恢复尺寸 | `Reformat` + `Transform` | 调整画幅和位置 |

## 1. 获得矫正数据（LensDistortion）

### Solve 阶段

1. 使用 `LensDistortion` 节点
2. **判断标准**：`Solve Error` 参数到 `1` 以下就是比较好的结果
3. 如果需要修改跟踪点细节：
   - 可以先把 `Analysis` 选项卡里的 `Preview` 关掉
   - 去到 `LensDistortion` 选项卡，将 `Mode` 从 `Undistort（矫正后）`
     改为 `STMap（矫正前）`
   - 然后查看图像中哪个线/边没对齐，再去做矫正

### 渲染 STMap

1. 使用下面的 `Mode`（STMap 输出模式）
2. 选择渲染全部通道（`all`，也可以直接只选择渲染 `motion` 通道）
3. 文件类型使用 `exr`，使用 `32 bit float` 色深
4. **可选**：写个脚本，渲染完后直接将渲染好的作为一个 `Read` 节点建立出来

```python
# 渲染完后直接将渲染好的作为一个 Read 节点建立出来
# 完整代码：
nuke.nodes.Read(file=nuke.thisNode()['file'].value())
```

## 2. 还原（应用 STMap 让素材无畸变）

1. `BlackOutside` 节点：把边缘拉伸去掉变成黑边
2. `C_STMap` 节点（有 GPU 加速）
   - `Map` 参数选择 `stmap` → `forward`
   - 可以修复畸变画面
3. `Crop` 节点
   - 把屏幕展开到框外的数值大小填入 `box` 中
   - 就可以恢复无畸变的画面尺寸

## 3. 恢复畸变（畸变回套）

**应用场景**：做完跟踪 / 三维合成后，要把画面"贴回"原始畸变镜头

1. `Reformat` 节点：为了将图像恢复成原尺寸
2. `Transform` 节点：将图像位置移动到原位置
3. `C_STMap` 节点（有 GPU 加速）
   - `Map` 参数选择 `stmap` → `backward`
   - 可以应用畸变画面
4. `Crop` 节点：点击 `Reset` 按钮就可以将 bbox 恢复到原画面尺寸

## 4. nuke-bridge 自动化镜头畸变还原图

```python
# nuke_run 中 nuke 已被注入
import nuke

# 1. 读素材
src = nuke.createNode("Read", inpanel=False)
src["file"].setValue("C:/footage/distorted.%04d.exr")
src["first"].setValue(1001); src["last"].setValue(1250)

# 2. LensDistortion 解算（关键帧匹配 + Solve 必须在 GUI 完成）
#    自动化场景：nd 读 LensDistortion 已经解算好的 .nk
distort = nuke.createNode("LensDistortion", inpanel=False)
distort.setInput(0, src)
# 关键：mode 改 STMap 才能导出
# distort["mode"].setValue("STMap")

# 3. STMap 输出（一般是先用 LensDistortion 渲染一张 stmap.exr，再用 Read 读它）
stmap = nuke.createNode("Read", inpanel=False)
stmap["file"].setValue("C:/footage/stmap.%04d.exr")

# 4. C_STMap 应用矫正
cstmap = nuke.createNode("C_STMap", inpanel=False)
cstmap.setInput(0, src)    # A: 源
cstmap.setInput(1, stmap)  # B: stmap
cstmap["forward"].setValue(True)  # forward = 矫正

# 5. BlackOutside 去拉伸
bo = nuke.createNode("BlackOutside", inpanel=False)
bo.setInput(0, cstmap)

# 6. Crop 裁回无畸变 bbox
crop = nuke.createNode("Crop", inpanel=False)
crop.setInput(0, bo)
# box 留空自动适配
```

## 5. 反向（回套畸变）

```python
# 假设已经做完跟踪 / 3D 合成，输出是 undistorted image
# 想要回套到原始镜头的畸变：

# 1. 读无畸变合成结果
comp = nuke.createNode("Read", inpanel=False)
comp["file"].setValue("C:/comp/undistorted.%04d.exr")

# 2. C_STMap 反向应用
cstmap = nuke.createNode("C_STMap", inpanel=False)
cstmap.setInput(0, comp)
cstmap.setInput(1, stmap)  # 同一张 stmap
cstmap["forward"].setValue(False)  # backward = 套回畸变

# 3. Reformat 恢复原尺寸
rf = nuke.createNode("Reformat", inpanel=False)
rf.setInput(0, cstmap)
# type = "to format"，format 用 project setting

# 4. Transform 移到原位置
tr = nuke.createNode("Transform", inpanel=False)
tr.setInput(0, rf)
# x/y/rotate 用 GUI 调到与原画面一致

# 5. Crop bbox
crop = nuke.createNode("Crop", inpanel=False)
crop.setInput(0, tr)
crop.knob("reset").execute()  # 重置到原画面尺寸
```

## 6. 易错点

- **`Solve Error > 1`**：跟踪数据不够稳，需要多看几个关键帧
- **STMap 必须 32 bit float**：8 bit 会有 banding
- **`motion` 通道**：导出 STMap 时可以选只渲染 `motion` 通道（更小）
- **C_STMap vs STMap**：C_STMap 有 GPU 加速；STMap 节点是 CPU 版
- **forward vs backward 选错**：导致方向反了，画面像被"反向压扁"
- **Crop reset 前的 box**：用用户截图里的 box 值（屏幕展开到框外）
- **BlackOutside 的位置**：必须在 C_STMap 之后；否则拉伸会进入最终画面
- **Solve 完不解算就改参数**：会丢失已算好的解
- **`LensDistortion` 节点不是稳定的"实时"节点**：换帧会重算，复杂镜头要 cache
