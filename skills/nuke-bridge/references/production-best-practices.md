# Nuke 制作规范与高频操作（学自用户笔记 Nuke.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Nuke.md` 全文（3400 行）。
原始笔记保持只读；本文件是蒸馏版——把可复用规范、快捷键、Merge 模式 cheat-sheet
写进来，让 `nuke-bridge` 走得更顺。

## 0. 工程基本功（重要到能改整条职业生涯）

- 整理统一通道
- **同源素材引用，而不是复制**（改素材一次全改完）
- 合成遵循 **B pipe 原则**：从上到下，`A` 从左入，`mask` 从右入——
  遵循 Nuke 设计语言，所有人接手都能秒懂
- 自定义参数统一控制变量，统一的效果最后统一做
- 尽量少的 `hide input`（会引入表达式链接 bug）
- `Bake tracker` 信息，而不是把 `Tracker` 节点放入合成
- 主线尽量不放 `Merge` 以外的节点

> "越工作到后面才会越觉得这些基础性的制作规范对于这个职位来讲是多么
> 重要……感谢 pxo 和 base 帮助我完成了规范制作的改造" —— 用户原话

## 1. B pipe / A-B input 语义（必须记牢）

- `Read` 节点：直接把文件夹拖入节点面板
  - 一个**序列视频**的 `Read`（用首帧自动设项目帧范围）
  - 多个**独立图片**的 `Read` 节点
- `Merge` 节点 / 所有合并类节点：**A 输入端 = 前景**（前面元素），
  **B 输入端 = 背景**（后面元素）—— 这就是 "B pipe 原则"
  - `nuke-bridge` 中：输入 0 = A， 输入 1 = B；`create_node` 的 `inputs=[A,B]`
    自动按 A→0、B→1 连好（B-pipe 自动纠正 "A 已连" 的常见错误）

**View 节点箭头语义**（用于 3D 视图内 model 摆放）：

- **绿色**箭头：世界坐标轴是否能被看见（关掉就看不见蓝白坐标线条）
- **蓝色**箭头：选择用哪个摄像机查看场景；红色指 = 锁定视图在摄像机视角
- **红色**箭头：`View` 节点两个输入端的**叠加方法**（方便对比画面）
- 不论箭头怎么指：**A 端**都用 `Scene` 节点的画面，**B 端**都用素材的画面

## 2. 快捷键 cheat-sheet（22 个最高频）

| 操作 | 快捷键 |
|---|---|
| 3D 视图 ↔ 2D 视图快速切换 | `Tab` |
| 3D 环境移动视角 | 按住 `Alt` 键 |
| 查看 Red 通道 | 视图窗口 `R` |
| 查看 Green 通道 | 视图窗口 `G` |
| 查看 Blue 通道 | 视图窗口 `B` |
| 查看 Alpha 通道 | 视图窗口 `A` |
| 查看亮度通道 | 视图窗口 `Y` |
| 视图窗口适配 | `H`（适配高度）/ `F`（适配大小） |
| 创建 **Read** 节点 | 节点面板 `R` |
| 创建 **Blur** 节点 | `B` |
| 创建 **Merge** 节点 | `M` |
| 切换节点连接顺序 | `Shift + X` |
| 禁用/启用该节点 | `D` |
| 恢复参数到默认值 | `Ctrl + 鼠标左键点击` |
| 曲线编辑器所有曲线居中 | 曲线编辑器 `F` |
| 选中 roto 的点→变贝塞尔 | `Z` |
| 选取屏幕上某个颜色 | `Ctrl` |
| 选取屏幕上一块地方的颜色 | `Ctrl + Shift` |
| 交换 2 个节点的连接顺序 | `Shift + X` |
| 把上游节点连到下游（Y 键） | 选下游 + `Shift` 选上游 + 松开 `Shift` + `Y` |
| 启动接单预览（要在节点上） | `Alt + P` |
| 打开 Project Settings | 节点面板 `S` |
| 打开 Preferences | `Shift + S` |

**林君义 lin 工具集额外快捷键**（在 `.nuke` 装好后可用）：

- `Ctrl + R` 选中 Write 节点快速导入已输出序列
- `Ctrl + E` 多层 exr 文件一键创建 Shuffle 分层
- `Shift + B` 快速打开 Read/Write 节点指定文件夹
- `Shift + P` 拾取所选 Read 素材长度设置工程帧数
- `Shift + T` 多功能快速设置（序列→创建 shuffle + 白色 alpha；mov→创建匹配工程帧数的 Retime）
- `Ctrl + Alt + ↑↓←→` 被选中节点自动对齐
- `Ctrl + L` 按间距排列 Read 节点并创建 Backdrop
- `Alt + .` 在节点线转角位置创建骨节点

## 3. Merge 模式 cheat-sheet（所有合并类节点同款）

| 模式 | 做什么 | 典型场景 |
|---|---|---|
| `plus` | A + B（相加） | 黑色背景的灯光层叠加（直接/间接高光、AO） |
| `multiply` | A × B（相乘） | 调节透明度（白色背景的层：阴影/接触阴影） |
| `from` | A 减去 A 跟 B 的差异 | 频率分离（高频 = 原图 - blur） |
| `divide` | A ÷ B（除法） | 屏幕清洁（去褶皱/IBK）、`Laplacian` 高频提取 |
| `minus` | A - B（减法） | 减法合成（单提一层做调整，再合回去） |
| `screen` | 1 - (1-A)(1-B) | 叠加耀斑、glow 类的"亮上加亮" |
| `matte` | 拿 A 的 alpha 直接当输出 alpha，RGB=A | 把 2 个图层的 alpha 直接相加（不混合） |
| `out` | A 减去 A∩B（不混合） | 把 2 个图层的 alpha 直接相减 |
| `stencil` | 剔除 B 中 A 区域 | 在 A 的蒙版里扣掉 B（"out 的反向"） |
| `in` | 取 A∩B（交集） | 把垃圾蒙版合到其它蒙版上 |
| `min` | A ∩ B（取小） | 叠加 2 个 Roto 节点抠像（合并 alpha） |
| `max` | A ∪ B（取大） | 扩边/补洞 |
| `difference` | \|A - B\| | 比较 2 帧差异、训练 CopyCat 时混合反选曲线 |
| `over` | 标准合成（A over B） | 默认合成；`Premult` 后配 `add` 节点补 alpha |

**A 端 = 前景、B 端 = 背景、mask 从右入**——这条贯穿所有 Merge 模式。

**Mask alpha 操作**：大部分节点都有一个 alpha 输入，可以定义节点影响的图像区域。

## 4. Alpha 通道机制（避坑必读）

- alpha 只在 `0~1` 之间有效
- 超出范围处理（3 种）：
  1. `keyer` 节点将 alpha 钳位到 0~1
  2. `clamp` 节点同样
  3. `Expression` 节点写 `a>1?1:a` 或 `a>0?a:0`
- 给没 alpha 的素材加 alpha：
  - 简单：直接使用 `Add(Channels)` 节点添加 alpha
  - 原理：把别的颜色通道加到 alpha 上再把 alpha 的颜色拉到白色
  - 原素材有 alpha 的情况：使用 `Copy` 节点 A 端连 alpha 层、B 端连主线
- `add` 节点：将 A 输入的 alpha 通道写入 B 输入里
  - **A 连接 alpha 通道素材，B 连接需要添加 alpha 通道的素材**
- 有 alpha 通道时 Nuke 才能知道怎么合并 2 个图像

## 5. Roto / RotoPaint 关键经验（业内总结）

### Roto 制作步骤（用户笔录的内部规范）

1. 拿到素材先观察几分钟寻找思路进行 Roto 拆分，顺序是先整体后细节
2. 选择物体最全的一帧进行 Roto 的制作，这样中途不用加点
3. 在保证画面完整性的情况下尽量少加点
4. 遇到相似的帧提前 K 帧，提前确定
5. 前后帧变化非常大的镜头可尝试一帧一画一帧一扔（画一帧移到画面之外）
6. 相邻的关键帧距离不可太近，越近越要谨慎
7. 不可中途删点中途加点需谨慎
8. Roto 点的位置不可随意改动，从始至终
9. Roto 点两端的调节杆尽可能保证平滑
10. 能不 Roto 就不 Roto（先想抠，再想跟，最后想 Roto）
11. 5 帧 5 帧添加关键帧，微调

### Roto 注意事项

- 观察抠像对象运动幅度，哪些地方需要旋转，哪些地方不需要，**先分析，做好计划**
- 通过一个个 roto 包裹住整个主体来进行旋转，**单个形状尽量不要超过 5 个点**
- 养成**命名形状**的习惯
- **不要使用羽化**，羽化会产生关键帧动画。在需要羽化的地方引用模糊来解决
- 最好设置好每个形状图层的持续时间
- 打开运动模糊（在 Motionblur 窗口中可以设置全局运动模糊启用）
- 可以使用 `track` 节点跟踪来加速观察对象，然后将其信息给到 `roto`
- `Open Spline` 工具处理头发或毛皮抠像
- 做完之后最好加上 RGB 来观察结果

### 画的位置

- 画的适合放在内侧，不要画在模糊边缘
- `roto` 结束后发现 1 像素留白解决不了：`Roto` 节点的 `feather falloff` 属性调为 0
- 开启 `clip to` 旁边的 `replace` 选项：现有 alpha 在绘制前会被全清空为黑，
  绘制后只有绘制区才有 alpha；后面接 `Premult` 就有抠像效果
- 多个反转曲线：用 `difference` 模式叠加，反选其中一个

### 叠加与反选

- 2 个 Roto 节点合并：`merge` 用 `min` 模式
- 在原 alpha 基础上扣东西：`merge` 用 `stencil` 或 `out` 模式
- roto 不一直在画面里需要反选：
  1. `constant` 节点（alpha=1）
  2. `roto` 节点
  3. `merge` 节点（`minus` 模式，A=constant、B=roto）
  4. `Shuffle` 节点提取 alpha
  5. `Premult` 节点得到反选

## 6. 关键帧（动画）

- 当前帧为关键帧：参数显示**蓝色**
- 当前帧不为关键帧：参数显示**淡蓝色**
- 当前帧无关键帧：参数正常显示**灰色**
- 右键参数：
  - `Set key` 增加关键帧
  - `Delete key` 删除关键帧
  - `No animation` 取消这个参数的关键帧
  - `Set to default` 设置为默认值
  - `Curve editor...` 打开曲线编辑器
  - `Dope sheet...` 时间轴编辑器
- 节点右上角带 `S` 标志：表明此节点有关键帧动画
- 在参数中使用表达式：右键 → `Add expression`，如 `frame*10`、`height/2`
- `random()`：生成随机数（做镜头震动很好用）
- `frame*0.1`：每帧偏移 0.1 帧
- **不用的节点最好删除或断掉链接**（禁用也会跑表达式）

## 7. 时间线 / 素材剪辑

### 时间线偏移

- `Append Clip` 节点直接修改 `First Frame` 即可把素材起始帧改为修改的帧

### 两条素材剪辑

- 方法 1（不推荐）：两段 `Merge` 起来，用 `Multiply` 调透明度打关键帧
- 方法 2（推荐）：`TimeDissolve` 节点
  - A 在 B 的前面
  - `in`：A→B 的开始时间
  - `out`：A→B 的结束时间
  - `curve`：B 素材的透明度变化曲线（左 0、右 1，1 会掩盖 A）

### 速度变换（3 个节点按场景选）

- `retime`：改变视频播放速度
  - `speed`：加速/减速倍数
  - `before` / `after`：视频前/后的动作（black = 透明）
  - `shutter`：快门速度（值高 = 动态模糊强）
- `Kronos`：减速或加速画面（需要精确运动矢量）
- `oflow`：光流法变速（更贵但更准）

## 8. 边界 / 边界框（bbox）

- `Q` 键开/关边界框
- 边界框定义了图像的边界
- 四周虚线意味着有一个更大的边界框，Nuke 会计算外面的像素
- `View` 右键 → `Show Overscan` 显示边界框
- 用 `crop` 节点 → `Reset` 即可裁掉边界框
- 带这个参数的节点：在上下左右往外扩大增加 1 个黑色像素做黑边

## 9. 路径 / 工程交付

### 相对路径（工程交付务必使用）

- `S` 打开项目设置 → 按 `Script Directory` 按钮，`Read` 节点可直接用相对路径
- 或者在素材路径写：`[ file dirname [value root.name] ]`
- 这样别人打开工程不用重新引入素材

### 批量替换丢失/移位的文件

- 全选 `Shift +` 加选所有报错文件
- `Ctrl + Shift + /` 弹出替换框
- 上方旧路径，下方新路径
- **下划线用 `/`**，不能用复制的 `\`（Windows 习惯）

### 批量渲染

- `F5` 弹出批量渲染界面
- 有 `Write` 节点会加入进来
- 建议：用 `deadline` 配一个本地的，直接跑满，方便管理渲染追查

## 10. 不要把 Tracker 留在工程里

- 工程里不允许出现开启的 `Tracker` 节点
- `Tracker` 会一直计算跟踪，连工程里预览什么的会一直计算，多了就卡
- 导出带跟踪数据的 `Transform` 后禁用或删掉原 Tracker
- `Bake tracker` 信息，而不是把 tracker 放入合成

## 11. nuke-bridge 自动化该知道的"Nuke 习惯"

- **nuke_run 注入的 `nuke`**：bridge 已经在 `nuke_run` 调用时把 `nuke` 模块注入了命名空间，
  **不要 import nuke**（会触发 AST allowlist 检查）。
  直接 `nuke.createNode("Read")`、`nuke.toNode("Write2")` 即可。
- **`nuke.filename(node)` 解析带 `[value xxx]` 表达式的路径**：
  当 Write 节点路径是相对路径或带表达式时，可拿到实际渲染路径。
- **路径正斜杠**（重要，Windows 坑）：Nuke Write 节点对 `C:\path\file.exr` 反斜杠
  报 "Can't write, Invalid argument"，必须用 `C:/path/file.exr` 正斜杠。
  bridge 的 `open_script` / `save_script` / `screenshot` 已自动归一，
  自己写 `nuke_run` 时也用正斜杠。
- **Write 节点 `create_directories`**：bridge 默认会打开，避免写盘失败。
- **`nuke.toNode("Root")` 返回 None**：要读项目设置用 `get_project_settings()`，
  不要 `nuke.toNode("Root")`。
- **Merge2 B-pipe**：bridge 的 `create_node("Merge2", inputs=[A,B])` 已自动按 A→0、B→1，
  B-pipe 自动纠正常见的 "A 已连" 错误。
