# CaraVR 360 全景视频处理（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "CaraVR 360全景视频处理" 节。
原始笔记保持只读；本文件是 VR 全景缝合与合成的蒸馏版。

## 0. VR 视频缝合后期的基础流程

1. **反求摄影机并缝合视频**
2. 对缝合的视频进行纠正：去重影、拼合错位
3. **重新匹配多个摄影机的色彩**使其一致

## 1. 缝合多个视角的相机视频（C_CameraSolver）

`C_CameraSolver` 节点可以将多个视角拍摄的视频进行拼接缝合。

### 用户 8 步法

1. **单击 `Match`（匹配）**：对设置的关键帧部分重叠画面进行比对计算
2. **点击 `Solve`（解算）**：解算完成后即可看到相机重新对位后的结果
3. **在视图中切换到摄像机模式**（第三个按钮）显示叠加
   - 会显示重叠摄像机特征点以及求解它们计算的 RMS（均方根）误差
   - **绿色叠加**表示低于错误阈值的 RMS 错误
   - **红色覆盖**表示超过阈值的红色叠加
4. **通过属性面板对解算的摄影机参数做优化**（手动放置匹配标记）
   - 在 Viewer（视图）中切换到添加匹配模式（第二个按钮）
   - 按住 `Ctrl / Cmd + Alt` 并单击查看器中存在于多个摄像头中的功能
     以添加匹配标记
   - 将特征点重新手工拖动到正确匹配的位置
5. **调整 VR 全景视频的水平线**（使其看起来平整对齐）
   - **方法一**：`Setting`（设置）选项卡上的 `Transform`（变换）控件
   - **方法二**：Viewer 左上角工具栏 → 启用 `Horizon` 工具
     - 按住 `Ctrl / Cmd + Alt` 并在 Viewer 中拖动以调整水平线
6. **使用 `C_Stitcher` 节点**来进一步修正画面之间的融合度
   - 去除重影、接缝边缘小错位
   - CaraVR 会在当前帧自动添加单个关键帧
   - 手动添加关键帧：
     - 在 Viewer 中擦除 → 单击 `Add Key` 在当前帧添加关键帧
     - 单击 `Key All` 在整个序列的间隔中添加关键帧
   - 视频中有大量移动：将"步进间隔"设置为较低的值
     - 计算帧之间的较大差异可以得到更好结果
     - 静态视频则相反
   - 单击 `Import` 并选择要从中导入关键帧的节点
     - 可以从脚本中的任何 `C_CameraSolver`、`C_Stitcher` 或 `C_ColourMatcher`
       导入关键帧
   - 手动添加关键帧有助于增加插值到现有关键帧之间不准确的区域
     - 添加的关键帧越多，解算所需的时间越长，但能获得更好的结果
   - 使用球形摄像机布局：可使用 `Converge` 控件设置摄像机重叠的深度
     - 将场景中的单个关注点置于焦点
     - 假设摄像机位于球体内部中心
     - 改变球体的大小会影响摄像机会聚的角度
     - `C_Stitcher` 使用 `C_CameraSolver` 的 `Cameras` 选项卡中设置的
       `Rig Size` 来控制球体
7. **匹配不同摄影机之间的曝光、色彩**（`C_ColourMatcher`）
   - 在所有摄像机上进行颜色校正流程
   - 将 `C_ColourMatcher` 节点添加到节点图并将其连接到 `C_CameraSolver` 节点的输出
   - CaraVR 会在当前帧自动添加单个关键帧
     - 手动添加：在 Viewer 中单击 `Add Key` 在当前帧添加关键帧
   - **小雨建议**：可以将视频切成多段，分别匹配，段数越多精度越高
     - 因为 `C_ColourMatcher` 无法计算时间变化产生的色彩变化
     - 例如由于相机移动导致的颜色随时间的变化
   - 单击 `Analyse`，可从 `Match` 下拉列表中选择 `Exposure`（曝光）
     或 `Exposure and Colour`（曝光和颜色）
8. **使用 `C_GlobalWarp` 解决接缝变形流程**（如果拼接质量好，这步可忽略）
   - `C_GlobalWarp` 使用类似于 `C_CameraSolver` 所采用的特征点检测
     来定位相邻相机重叠区域中的特征
   - 然后通过扭曲画面来减少重影
   - CaraVR 会在当前帧自动添加单个关键帧
   - 默认情况下也会导入 `C_CameraSolver` 中的匹配项
     - 若不需要解算器中的匹配项，可以禁用"导入可用匹配项"
   - 单击 `Match` 比较关键帧上摄像机的重叠
   - 单击 `Camera Matches` 按钮以显示重叠区域中的匹配项
     - 默认情况下不显示匹配项
   - 单击 `Warp` 以计算扭曲

## 2. 全景合成（C_SphericalTransform）

### 原理

> VR 全景合成原理：将 VR 视频按照一定的算法，将全景画面展平为 2D 画面，
> 并在 2D 画面中合成好画面，最后再将 2D 画面扭曲到 VR 的球体空间中去，
> 这个过程中最重要的节点是 `C_SphericalTransform`。

`C_SphericalTransform` 节点将 VR 空间中的球形画面，通过投影映射为 2D 空间
使其可以像 2D 画面一样的合成。

### 投影模式之间转换（`Projection` 参数）

- `Latlong_Rotopaint` 节点流程可以进行擦除
- `Latlong_Comp` 节点流程可以让 2D 元素图像并成到 360 度全景环境
- `Latlong_Tracked_Rotopaint` 节点可以进行 2D 跟踪后擦除
- 如果需要合成 3D 物体则需要在解算出摄影机后，创建 VR 3D 空间
  - 在 3D 空间内添加三维元素
  - 通过 `C-Rayrender` 节点进行渲染输出

## 3. 擦除（Latlong_Rotopaint）

使用 `Latlong_Rotopaint` 工具，会自动生成一组工具集节点：

- 第一个 `C_SphericalTransforms` 将图像转换为直线 2D 空间图形
  - 然后就可以像 2D 中 Rotopaint 一样可以绘画或者擦除
- 第二个 `C_SphericalTransforms` 可以将 2D 空间图形再返回到 latlong 空间
  - 它将被映射回 360 度全景空间
  - 然后通过 Merge 节点与原始图像合并

### 操作步骤

1. 将 Viewer 连接到第一个 `C_SphericalTransform` 节点
2. 打开其 Properties（属性操作）面板以激活 `directionInput` Viewer 工具
   - 用此工具进行视角移动
   - 或者按下 `Ctrl + Alt` 使用鼠标左键来拖动画面进行视角的移动
   - 可以调整 `Angle` 参数进行水平或垂直方向移动
3. 然后即可进行正常擦除工作
4. 要在 `latlong` 空间中查看绘制结果，将 Viewer 连接到第二个
   `C_SphericalTransform` 节点即可

## 4. 2D 跟踪和稳定（C_Tracker）

`C_Tracker` 可以在 latlong 空间中进行跟踪，可以在 VR 360 度环境中进行追踪。
`Latlong_Tracked_Rotopaint` 节点可以进行 2D 跟踪后擦除。

## 5. nuke-bridge 自动化：CaraVR 缝合最小组图

```python
# nuke_run 中 nuke 已被注入
import nuke

# 1. 多个 Read 节点读各摄像机
cam1 = nuke.createNode("Read", inpanel=False)
cam1["file"].setValue("C:/vr/cam1.%04d.exr")
cam1["first"].setValue(1001); cam1["last"].setValue(1250)

cam2 = nuke.createNode("Read", inpanel=False)
cam2["file"].setValue("C:/vr/cam2.%04d.exr")
cam2["first"].setValue(1001); cam2["last"].setValue(1250)

# 2. C_CameraSolver 节点（需要 CaraVR 插件）
# 2 个 read 节点接 solver 的 input 0 和 input 1
solver = nuke.createNode("C_CameraSolver", inpanel=False)
solver.setInput(0, cam1)
solver.setInput(1, cam2)
# 关键参数：Match 按钮、Solve 按钮都是 GUI 触发的；
# 自动化场景下需要在 GUI 完成关键帧匹配后再用 nuke_run 做后续

# 3. C_Stitcher 节点
stitcher = nuke.createNode("C_Stitcher", inpanel=False)
stitcher.setInput(0, solver)
# 然后匹配颜色
cm = nuke.createNode("C_ColourMatcher", inpanel=False)
cm.setInput(0, stitcher)
```

> **重要提示**：CaraVR 的核心是 GUI 交互式（Match/Solve/Add Key 等都是按钮），
> 自动化能做的部分有限。nuke-bridge 主要用于：
> 1. 批量参数调整（曝光、增益、关键帧位置）
> 2. 多个 stitcher 节点的批量创建
> 3. 渲染输出节点配置

## 6. 注意事项

- **CaraVR 是付费插件**：Nuke 单独授权，不包含在 Nuke 基础版
- **每个 C_ 节点都需要独立 license**：多个 stitcher 会消耗更多 license
- **多段匹配**：C_ColourMatcher 无法处理时间维度的色变，所以小雨建议分段
- **R 球半径**：Rig Size 影响 C_Stitcher 的视野聚散
- **`Add Key` 按钮**就是当前帧的关键帧，要配合 Viewer 的擦除操作
- **球形 vs 平面**：VR 拼接默认是球形布局，平面/柱面需要不同参数
- **导入关键帧**：可从 C_CameraSolver / C_Stitcher / C_ColourMatcher 之间
  互相 import，提高效率
- **重复 split 和 stitch**：用 `Variable Switch` 节点控制不同输入的多个
  镜头版本和监看；`Variables` 面板给不同镜头增加变量
