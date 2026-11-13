# AOV 救场 + 分层重新组装（学自用户笔记 Nuke.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - 合并口诀：黑色背景的灯光层（direct/indirect diffuse/specular、reflection、sss、AO）用 Merge2 `plus`；白色背景层（阴影/影子/接触阴影）用 `multiply`；alpha 层用 Copy（A=alpha 层，B=主线）
> - 火烟救场（Option C）：rgb = combinedemission + combinedvolume；alpha = clamp(luma(rgb) × GAIN, 0, 1)，GAIN 取 2~4 把火焰核心推到 alpha≈1
> - Option C 验证：sky/background 区 alpha 必须≈0；火焰核心不实白→升 GAIN，烟边缘过硬→降 GAIN
> - AOV 标准合并链：diffuse_direct + diffuse_indirect(plus) → 总漫反射；specular 同理；再 + reflection + sss + emission + ao
> - 合成顺序：基础层(漫反射/Albedo)放 B 端，黑底灯光层 plus 用 A 端，白底层 multiply 用 A 端；先低频后高频、先整后细
> - 调色顺序：亮度 → 颜色 → 光影 → 黑值 → 物理（如冲镜光前物体应暗）；硬边是大忌，注意冷暖对比
> - 法线层重打光：P_matte 的 position data 选法线层、center 选灯光方向色、matteShape=Sphere(点光)/Cube(平行光)，输入需先有 alpha；eye_light 的 N channel 选法线层，直接输出 rgb、不用加 alpha
> - 抠绿救场：IBKColourV3 选色 → Merge(divide) 去绿幕 → 纯绿背景合成回去；size 调大折痕模糊是错的——绿幕背景要尽可能精确
> - ChannelMerge 专门合并 CORE KEY + EDGE KEY 两个 alpha；LayerContactSheet 一屏看全 EXR 的 AOV 层
> - 频率分离：Blur(低频) → Merge(from) 提取高频 → Merge(plus) 合并；低频用 Inpaint 擦不需要的光；Laplacian 可直接提取高频
> - 大忌：不要用 beauty 替直接光做调节（叠加结果无法单层调）；不混用 plus/multiply；matte 模式只搬 alpha 不动 RGB

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` 全文（3400 行）。
原始笔记保持只读；本文件是 AOV 救场与分层 re-assembly 的蒸馏版。

## 0. AOV 通道语义（背下来再合成）

| 层 | 含义 | 背景色 | 合并方式 |
|---|---|---|---|
| `rgba` | 总层（所有叠加后） | — | — |
| `beauty` | 各个灯光层叠加在一起 | — | 一般不用（无法对单独灯光层调节） |
| `direct diffuse` | 直接光照（主光） | 黑色 | `plus`（A 端连前景） |
| `indirect diffuse` | 间接光照（辅光） | 黑色 | `plus` |
| `direct specular` | 直接高光 | 黑色 | `plus` |
| `indirect specular` | 间接高光 | 黑色 | `plus` |
| `reflection` | 反射 | 黑色 | `plus` |
| `sss` | 透光层 | 黑色 | `plus` |
| `AO` | 环境遮蔽（增加整体立体感） | 黑色 | `plus` |
| 接触阴影 / 阴影层 / 影子层 | 阴影 | **白色** | `multiply`（A 端连前景） |
| alpha 层 | 透明度 | — | `Copy` 节点 A 端连 alpha 层、B 端连主线 |

> **口诀**：黑色背景的灯光层用加法（`plus`），白色背景的层用乘法（`multiply`）

## 1. AOV 救场（Option C：火 / 烟 / 任何 volume）

**主 SKILL.md 已有 Option A（scen 减法）和 Option C（combinedemission + combinedvolume），
这里补一份用户笔记里的补充判断和易错点。**

### 何时用 Option C

- 渲染 EXR 里有 `combinedemission` 和 `combinedvolume` AOV
- 不想要/没有干净的 `render_scen` 通道
- 火/烟本体已经自带 alpha 信号（不管天空/HDRI 是什么）

### Option C 数学（与主 SKILL.md 一致）

```text
rgb   = combinedemission + combinedvolume
alpha = clamp(luma(combinedemission + combinedvolume) * GAIN, 0, 1)
```

`GAIN` 通常 2~4，把火焰核心推到 alpha≈1。因为 sky/background 没有 fire
贡献，alpha 自动归 0——HDRI 永远进不了 alpha。

**用户原话佐证**："因为火的 pass 自带 AOV，sky 不会有 fire 贡献，所以
alpha 自然为 0，HDRI 不会泄露进 alpha"。

### 验证后必须检查

- Save 一帧 → 查 EXR alpha 统计：sky/background 像素必须 alpha ≈ 0
- 火焰核心不实白：升 `GAIN`；烟边缘过硬：降 `GAIN`
- `screenshot(node=<write name>, frame=1100, max_long_edge=1600)` 快速目视

## 2. 减法合成（当 AOV 有坏层想恢复 beauty）

**核心思路**：假设渲染通道内存在坏层（无法还原 beauty），
用减法单独提取需要调整的一层，最后再合并回去。

**渲染出来的 AOV 通常按以下顺序 merge（用 `plus` / `multiply`）**：

```text
diffuse_indirect + diffuse_direct → 总漫反射
specular_indirect + specular_direct → 总高光
+ reflection + sss + emission + ao
```

nuke-bridge 自动化：

```python
# 假设有 read_diffuse_direct, read_diffuse_indirect 两个 Read 节点
merge_diff = nuke.createNode("Merge2", inpanel=False)
merge_diff["operation"].setValue("plus")
merge_diff.setInput(0, read_diffuse_direct)
merge_diff.setInput(1, read_diffuse_indirect)
# 输出送入下一层 merge，依此类推
```

## 3. 合成顺序（先低频后高频，先整后细）

**调节方法**（用户笔录的合成师工作流）：

1. **找基础层**（漫反射层、diffuse、Albedo，用 B 端连接）
2. **黑色背景图层**用加法（`plus`，用 A 端连接）
3. **白色背景图层**用减法（`multiply`，用 A 端连接）
4. **alpha 层**：创建个 `copy`，A 端连接 alpha 层，B 端连接主线

> 影子通常都是白色背景的层（接触阴影、阴影层、影子层）。
> 各种光的影响基本都是黑色的背景（高光、反射）。

**调节步骤**：

- 先修改每个层，再调节整体
- 先调节明显问题，再修改细节
- 有参考就看参考；没参考就看场景中类似物体做参考
- 顺序：亮度 → 颜色 → 光影 → 黑值 → 物理（比如背景有很强冲镜的光，前方物体应该是暗的）
- 注意有没有色偏
- 硬边是合成的一大忌，尽量避免硬边
- 画面注意冷暖对比
- 可以用 keyer 选出范围，用 mask 连到 Grade 节点上，`lift` 参数调颜色
- `Position To Points`：将像素值当作三维空间位置属性映射到三维空间

## 4. 法线层用法（"重新打光"）

法线层本质就是当 mask 用，可以单独查看法线层的 RGB 通道检查颜色分布。

### 方法 1：手动提取通道

```python
# 把法线层的红色通道提取出来当 mask
shuffle = nuke.createNode("Shuffle", inpanel=False)
shuffle["in"].setValue("forward")          # 输入是 normal
shuffle["red"].setValue("red")             # 只取 R 通道
shuffle["out"].setValue("rgba")
shuffle["postage_stamp"].setValue(True)
# 用 Grade 节点增加对比度，然后 Multiply
```

### 方法 2：P_matte + eye_light（更系统化）

`P_matte` 节点（MoreRealistic Tools）：

- `position data` 参数选中**法线层**（Normal）才可以使用其调整颜色
- `center` 参数选取颜色（选择灯光从哪个方向角度照射过来），输出给 alpha 通道
- `matteShape` 参数选择 `Sphere`（类似点光源）还是 `Cube`（类似平行光源）
- `uniform scale` 控制灯光强度
- `falloff` 参数控制灯光从有到无的过渡柔和度
- **需要在输入时提前就给一个 alpha 通道**，否则会没有输出

`eye_light` 节点（MoreRealistic Tools）：

- `N channel` 选择法线层（可能在不同的通道名）
- `center` 选取灯光方向颜色，输出直接给 rgb 通道
- `gamma` 和 `value` 调节灯光颜色和强度
- `value` 像乘法值，`decay` 是增加过渡强度
- `size x/y` 可以控制灯光变形
- **不用额外添加 alpha 通道**，只需要在 `rgb` 上即可

## 5. 抠绿/抠蓝的 AOV 思路（IBK 救场）

**先制作干净绿幕背景**（用户笔记"方法 2"）：

1. 通过 `IBKColourV3` 选取颜色
2. `Merge(divide)` 通过 A/B 把绿幕元素去除掉
3. 选绿幕颜色做一个纯绿幕背景 `Merge`
4. 把背景和前景合并在一起

> 如果 `size` 参数调大，所有的折痕和细节都会模糊，这是不对的——
> 因为目的是要告诉分割（Merge 的 `divide` 分割模式）我们要保留什么，
> 绿幕背景要尽可能精确。

**ChannelMerge 节点**允许将每个输入中的一个通道合并在一起，并将结果保存在
选定的输出通道中。默认情况下合并输入的 alpha——这个对**合并 CORE KEY 和
EDGE KEY 两个 alpha 通道**特别有用。

**LayerContactSheet 节点**可以直接把 exr 里的多层全部展示出来——看 AOV 必备。

## 6. 频率分离（合并分割法的正确公式）

**Merge Divide** 是一种在合成中常用的方法，此技术可以恢复精细的细节，
还会保持擦除地方的颜色和光线保持不变。主要用于从镜头中移除元素，
以及演员进行减龄或老化（去除皱纹或增加皱纹），不仅可以增加精度，
也能让工作变得更快。

传统方法是对贴在素材上新的图像部分进行调光，让其区域的照明和色相相匹配
（缓慢且不精确）。新方法能在不改变细节的情况下改变光照，
或对失焦的照片进行锐化——这些操作可以从图像中提取精细的细节。

此技术的术语是 **Image Frequency Separation（图像频率分离）**。

**原理**：让图像分成 2 个通道（可以同时修改一个或两个通道并且互不影响）：

- **低频通道**：表现脸部的着色或光线
- **高频通道**：可以从中提取精细的细节

**操作**（按顺序）：

1. `Blur` 节点把图像变模糊（去掉微小细节）；可改变 `filtering` 中的精细度
2. `Merge` 节点调为 `from` 模式：把模糊图像从原图中"删掉"，只留下细节
3. 合并：用 `Merge` 开启 `plus` 模式——在高频的基础上加上低频的细节通道
4. 低频通道可用 `Inpaint` 节点来擦掉不需要的光线信息

**Laplacian 节点**可以直接提取高频细节（原理一样）。
**先将合并操作设置为 `divide`，再将模糊后的图像正片叠底在上面**——所以这就是
"Merge Divide" 名字的由来。

## 7. nuke-bridge 操作 AOV 的两个最常用动作

### 自动分层（按 direct/indirect 配对）

```python
# 完整脚本见 references/scripts-and-productivity.md
# 这里给精简逻辑：
read = nuke.toNode("Read1")
layers = sorted(set(c.split('.')[0] for c in nuke.channels(read)
                    if 'rgba' not in c))
direct = [l for l in layers if 'direct' in l.lower()]
indirect = [l for l in layers if 'indirect' in l.lower()]
# ...每对用 plus 模式 merge
```

### 把 EXR 里所有 AOV 一键堆到一个合成树

```python
import nuke
read = nuke.toNode("Read1")  # 或用 nuke.createNode("Read") 新建
# 详见 references/scripts-and-productivity.md 的完整脚本
```

## 8. AOV 常见错误

- **不要 beauty 替直接光**：beauty 是叠加结果，无法对单层做调整
- **不要混用 `plus` 和 `multiply`**：黑色层用 `plus`、白色层（阴影）用 `multiply`
- **避免硬边**：所有灯光/阴影层都需要做"先 blur 再合并"或"先 divide 再 plus"
- **不要在 matte 模式下做颜色叠加**：`matte` 只搬 alpha，不动 RGB——需要先合并 RGB 再处理 alpha
- **`Mask alpha` 的语义**：matte input 用 roto 的 alpha 通道（不是 rgba）
- **`direct/indirect` 配对顺序不影响结果**：`plus` 是可交换的
