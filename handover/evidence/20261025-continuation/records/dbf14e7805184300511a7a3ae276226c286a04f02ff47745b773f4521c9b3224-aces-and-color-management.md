# ACES 色彩管理（学自用户笔记 Nuke.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 工程开 ACES：节点面板按 S → Color → Color management = OCIO → OCIO Config = custom → 选 config.ocio（路径必须用正斜杠 C:/path/config.ocio）
> - 全局默认配置：Edit → Preferences → Color Management → OCIO Config = custom → Choose 选 config.ocio
> - 素材空间不对就改 Read 的 Input Transform；选项选不了 → 取消勾选 Raw Data（勾上 = 不解释像素）
> - 贴图选型：非浮点（JPG/PNG）= Utility - sRGB - Texture；浮点（EXR/HDR/线性）= Utility - Linear - sRGB
> - 决策树：网图 JPG/PNG → Utility - sRGB - Texture；渲染 EXR → ACEScg / Linear；视频 → Rec.709；HDR/HDRI → Linear 或具体 IDT
> - 交付输出：Write 选 exr + ACEScg（项目、Read 输入、Write 输出全部 ACEScg）
> - 转 sRGB 预览：在节点面板粘贴 snippet 自动生成 OCIOColorSpace（scene_linear → Output - sRGB）+ Colorspace（colorspace_in = sRGB）两个节点
> - nuke-bridge 批量改：Read 统一 r["colorspace"].setValue("Utility - sRGB - Texture")；Write 统一 w["colorspace"].setValue("ACEScg")
> - 视频色彩不对先查监视器上方色彩空间（Monitor Out）；它只是显示端 LUT，不影响合成结果
> - Merge 两侧必须同色彩空间：sRGB 视频做 B 端时 Read 已转好，A 端 CG 元素要用同样空间
> - Reformat 别乱用 type：改尺寸用 to format，改比例用 scale

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` "ACES" 节。
原始笔记保持只读；本文件是 OCIO/ACES 工程设置与素材色彩转换的蒸馏版。

## 0. 概念速记

- **`Log2Lin1` 和 `ColorSpace`** 都可以换色彩空间
- Nuke 是用 `Read` 和 `Write` 节点的 **`Input Transform`** 和 **`Output Transform`**
  来进行色彩的转换
- **监控器色彩空间**：在监视器上方调节好色彩空间，以免显示器和素材色彩空间
  不同导致调色时错误调节

## 1. 工程项目色彩设置（单项目）

1. 在**节点面板**按下 `S` 键，弹出项目设置，点进去 `Color`
2. 在**色彩管理** `Color management` 中选择 `OCIO`
3. 然后在 `OCIO Config` 中选择 `custom`
4. 在 `custom OCIO Config` 中选择 `config.ocio` 文件

## 2. 每次打开都是这个配置（全局默认）

1. 打开 `Edit` → `Preferences` → `Color Management`
2. 在里面的 `OCIO Config` 中选择 `custom`
3. 在 `Choose` 中选择本地文件里的 `config.ocio` 文件

## 3. 即使项目设置了色彩空间，但素材不是所需色彩空间

> 即使项目设置了色彩空间，但是素材还不是所需色彩空间，需要转换素材的颜色空间

1. **Read 素材节点上的 `Input Transform`** 更改导入的实际颜色空间
   - 若无法选择，取消勾选 `Raw Data`
2. 如果素材是那些贴图材质等：
   - **图像不是浮点**，请使用 `Utility – sRGB – Texture`
   - 如果是**浮点**，请使用 `Utility – Linear – sRGB`

## 4. 输出 ACES

- 输出选项选择 `exr` 和 `ACEScg` 色彩空间（**全部都是 ACEScg 色彩空间**）
- 就可以输出 ACEScg 空间

## 5. 处理母版素材（标准流程）

> 材质贴图也需要这样处理然后才能放入 Houdini。
> 如果是网上下载等方式获取的素材，一般都是 sRGB 色彩空间，
> 都要在素材节点上的 `Input Transform` 更改导入的实际颜色空间，
> 再导出 `ACEScg` 色彩空间。

1. 把项目设置为 `ACEScg` 色彩空间
2. 素材选择母版的色彩空间（选 `ACEScg`——注意：图片里写"图片是错误的"）
3. 输出时，选择 `exr` 和 `ACEScg` 色彩空间（全部都是 ACEScg 色彩空间）

### 选错色彩空间的来源

> 从互联网下载的大多数纹理都是位于 `sRGB` 颜色空间中，
> 在 OCIO 中将其视为 `Utility – sRGB – Texture`（常用）
> 有更好的 `线性 EXR 纹理` 或 `HDR` 或渲染图，
> 需要的 `IDT` 则改为 `Utility – Linear – sRGB`

## 6. 转换为 sRGB（paste 节点 snippet）

复制这段代码直接粘贴到 Nuke 的节点面板：

```c
set cut_paste_input [stack 0]
version 12.1 v1
push $cut_paste_input
OCIOColorSpace {
  in_colorspace scene_linear
  out_colorspace "Output - sRGB"
  name OCIOColorSpace1
  selected true
  xpos -1044
  ypos -529
}
Colorspace {
  colorspace_in sRGB
  name Colorspace1
  selected true
  xpos -1044
  ypos -476
}
```

就可以自动生成这两个节点并改好参数（`OCIOColorSpace1` + `Colorspace1`）。

## 7. 视频素材和三维渲染素材的色彩空间一致性

> 如果是视频素材和三维渲染出来的素材，需要处于同一色彩空间才行

**两个通道命名规范**：

- 视频素材：sRGB / Rec.709
- 三维渲染：Linear / ACEScg / ACES 2065-1

**处理时**：

- 使用 `Reformat` 节点来降低素材质量从而快速处理素材

## 8. nuke-bridge 自动化：批量改 Read 节点的 Input Transform

```python
# nuke_run 中 nuke 已被注入
import nuke

# 把所有 Read 节点统一改成 sRGB 输入（web 素材默认）
for r in nuke.allNodes('Read'):
    r["colorspace"].setValue("Utility - sRGB - Texture")

# 把所有 Write 节点统一改成 ACEScg 输出（交付格式）
for w in nuke.allNodes('Write'):
    w["colorspace"].setValue("ACEScg")
```

## 9. nuke-bridge 自动化：OCIOColorSpace + Colorspace 一键生成

```python
# 把 read1 转 sRGB 输出
read = nuke.toNode("Read1")
ocio = nuke.createNode("OCIOColorSpace", inpanel=False)
ocio["in_colorspace"].setValue("scene_linear")
ocio["out_colorspace"].setValue("Output - sRGB")
ocio.setInput(0, read)

cs = nuke.createNode("Colorspace", inpanel=False)
cs["colorspace_in"].setValue("sRGB")
cs.setInput(0, ocio)
```

## 10. 监控器色彩管理

- **Thumbnails** = 缩略图
- **Monitor Out** = 显示器输出
- 如果发现视频色彩不对，记得一定要在监视器上方调节好色彩空间，
  以免显示器和素材色彩空间不同导致调色时错误调节

## 11. 色彩空间关键决策树

```
你的素材是什么？
├── 在线下载的 JPG/PNG（一般是 sRGB）
│   → Read Input Transform: "Utility - sRGB - Texture"
│   → ACES 项目下: Read Input Transform: "sRGB - Texture"
├── 渲染的 EXR（线性）
│   → Read Input Transform: "ACEScg" 或 "Linear"
│   → 或 "Utility - Linear - sRGB"
├── 视频素材（Rec.709）
│   → Read Input Transform: "Rec.709"
└── HDR / HDRI
    → Read Input Transform: "Linear" 或具体 IDT
```

## 12. 关键易错点

- **Image 不是浮点 ≠ 浮点**：JPG/PNG 是 8bit INT，HDR/EXR 是 32bit Float
  - 这个判断决定了 `Utility - sRGB - Texture` vs `Utility - Linear - sRGB`
- **Raw Data 复选框**：勾上后 Input Transform 不能选——这是为了"不解释像素"
  - 只有当你的素材是已经被某个色彩空间解释过的、并知道原始空间时才不勾
- **A 端 vs B 端色彩空间**：sRGB 视频作为 B 端时，Read 节点已经转好
  - A 端（CG 元素）必须用同样色彩空间 merge
- **OCIO Config 路径**：必须用正斜杠 `C:/path/config.ocio`
- **`monitor_out` 改变不影响合成**：仅是显示器端 LUT
- **ACES IDT/ODT**：不同渲染器有不同 IDT（Blender / Maya / Houdini 各有 ACES 配置）
- **`Reformat` 不要乱用 type**：改 size 用 `to format`，改比例用 `scale`
