# 羽毛/毛发 Grooming 实战笔记（学自用户笔记 羽毛毛发.md + Chop模块.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\羽毛毛发.md`（约 310 行）与
`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\Chop模块.md`（约 34 行）。
原始笔记保持只读；本文件是蒸馏版——聚焦笔记里的具体参数、坑、案例步骤，作为
`references/workflows/feathers.md`/`fur.md` 通用指南的实战补充。
笔记里指向图片的链接保留原样（截图见原笔记）。

## 1. 核心概念（2 个必记名称）

| 名称 | 含义 |
|---|---|
| `Shaft` | 羽毛中心的根（羽轴） |
| `Barb`（笔记写作 Baeb） | 羽毛两侧的羽毛丝（倒钩） |

## 2. Feather Template 节点组（制作羽毛）

工具架上的 `Feather Template` 节点组可快速生成一整套搭建羽毛的节点。

### Feather Shape Organize（形状组织）

- 把曲线送入羽毛形状组织：放入一些组、添加一些属性，再输入下游节点
  （按名称组织松散绘制的曲线，以便输入到 Shape 的羽毛模板）
- **输入 1**：曲线——绘制羽毛形态（**画曲线时是从下到上**）
- **输入 2**：轮廓曲线——画剖面分离曲线（引导线）

### Feather Template from Shape（从形状曲线生成羽毛模板）

利用输入的形状曲线创建羽毛模板。关键参数：

- `Shaft` 面板：`width root` / `width tip` 控制羽毛顶部和根部的粗细宽度（感觉像密度）
- `Barbs`（倒钩，从中心部分伸出的倒钩，采样离曲线的距离）：
  - `Barb Start on Shape`：第一根倒钩尖端落在形状曲线上的位置
- `Resolution`（调整密度获得更高分辨率羽毛）：
  - `Shaft Density`：杆下的细分（没有羽毛丝的底部）
  - `Barb Density`：倒钩密度（羽毛"叶"片数量，越高越多，增加中间细分）
  - `Barb Segments`：每个倒钩中的段（顶点）数量——**在几何体中是常数**
    （羽毛丝细分）

## 3. 分布到模型上：Hair Generate + Feather Template Interpolate

### Hair Generate（在表面或点生成头发）

输入端：

| 输入 | 内容 |
|---|---|
| 1 | 模型 |
| 2 | 毛发 |
| 3 | 动画 |
| 4 | 体积 |

- `Distribution` 下的 `Density`：控制头发数量密度
- `Unguided Hairs` 下的 `Length`：统一控制羽毛长度

### Feather Template Interpolate（羽化模板插值，混合一组模板曲线的值）

输入端：

| 输入 | 内容 |
|---|---|
| 1 | 指南（guide）：`Hair Generate` 生成的引导曲线 |
| 2 | 皮肤（skin）：模型 |
| 4 | 所有羽毛 |

> 羽毛的方向是曲线，所以需使用 `Guide Tangent Space` 节点给曲线增加切线空间：
> **输入 1 = 曲线，输入 2 = 模型（skin 皮肤）**。
> `Guide Groom` 用 `barborient` 属性记录方向，所以 `Guide Tangent Space`
> 中也要输出该属性作为确定的方向。

`Templates` 面板：

- `lookup method`（查找模板曲线用于插值的方法）：
  - 默认是权重数组（`Weight Arrays`），**默认会报错**，需修改查看不同结果
  - `Group`：使用最后输入的所有羽毛，在表面上排列羽毛
  - `Match by Name Attribute`：多种类型羽毛时，用此方法设置不同羽毛放不同位置

`Shaft` 面板（匹配分辨率 / 自定义分辨率）：

- `Resample Shaft`：是否重新采样羽毛模板的轴
- `Resolution Mode`：分辨率模式
- `Resolution Multiplier`：整体分辨率乘数

`Attribute` 面板：可从羽毛模板原语中转移的点/原始属性（提取属性给下游）。

> 如果下游要继承上游的羽毛宽度，最好在本节点上带上一些梳理要用的属性。

## 4. 增加细节的常用节点

结构定位（按 `Feather Template Interpolate` 的输入端上游分）：

- **羽毛部分**（输入 4 上游）：
  - `Feather Clump`：羽毛团工具——调整频率等，让羽毛成团/分裂（倒钩成团/分裂），
    然后脱落并分割
  - `Feather Resample`：调整羽毛分辨率。**非常有用**——羽毛分辨率太高可以用它变低
  - `Feather Noise`：给羽毛增加三维噪波
  - `Feather Width`：设定羽毛杆和倒钩的曲线宽度（见下）
- **模型散布曲线部分**（输入 1/2 上游）：
  - `Hair Clump`：引导曲线相互连接成团，一簇一簇的发团
  - `Guide Groom`：交互式创建和修改曲线，自行梳理
- **上下游都能用**：`Guide Process`、`Guide Groom`

### Guide Process（通过 Operation 修改导线）

| Operation | 作用 |
|---|---|
| `Set Direction` | 设置导线方向，所有导线朝指定方向倾斜 |
| `Frizz` | 毛躁——添加噪波产生毛发弯曲 |
| `Set Lift` | 设置曲线交叉在一起的程度（让毛发翘起来） |
| `Set Length` | 设置毛发长度 |
| `Wave` | 给毛发自身设置波动 |
| `Bend` | 增加弯曲 |

- **输入 3 可以连接模型自己的 VDB**（毛发与体积碰撞）。

### Feather Width（宽度控制）

- `Create Shaft Width` 下 `Shaft Width`：控制整体粗细，`Ramp` 映射从顶部到根部的粗细
- `Create Barb Width` 下 `Barb Width`：控制从两边到中心杆的粗细，`Ramp` 映射
- 生成 `width_barbl` 和 `width_barbr` 属性
- **注意**：该宽度属性对视口中的曲线没有影响。需要使用 `Feather Uncondense`
  或 `Houdini Procedural: Feather` 才能观察这些属性的影响
- 技巧：让羽毛看起来更柔软 → 用 `Feather Width` 减少倒钩的宽度（`Shaft Width`）

### Guide Groom（交互式梳理）

输入端：1 = 曲线，2 = 模型，3 = VDB。

常用笔刷/工具类型：

| 类型 | 作用 |
|---|---|
| `draw` | 画一根头发 |
| `plant` | 笔刷位置散布、种植头发 |
| `brush` | 移动、梳理头发 |
| `cut` | 剪头发 |
| `sculpt` | 梳头发（要选组） |
| `adjust length` | 拉长头发 |
| `move` | 直接移动一批鼠标范围内的头发位置 |
| `Paint Mask` | 画蒙版，将不需要改变的头发作为蒙版 |
| `Transform Handle` | 手柄工具移动单根头发；Group 鼠标选中一根后右键 `Accept Selection` 可沿头皮移动发丝 |
| `Straighten` | 将头发拉直 |
| `Orient` | 手动旋转头发 |

**将每根曲线最终都转变为羽毛**：

1. 勾选 `feathers` 下的 `Create & Output Feathers`
2. `Template Geometry SOP` 放入羽毛资产
3. 点一下 `Set Feather Settings` 进行羽毛所需的典型参数设置——目前它只设置创建和
   维护 `orient` 方向属性（取向属性名称设定在羽毛所需的标准上）
4. 它会在下游创建羽毛模板化节点

> **重要**：建议把 `Guide Groom` 放在羽毛进入之前。它不是程序化节点，上游任何
> 更改都得重做；它是一个**缓存节点**，产生修改后必须清除并在每次更改时重新输入，
> 然后就可以用它当笔刷刷羽毛。

## 5. 遮罩（Masking）的 4 种使用方式

1. `Attribute Paint` 绘制遮罩，通过各毛发节点的 `Skin Attribute` 参数对某个数值附加遮罩
2. 节点内置 `Masking` 选项卡附加遮罩（如 `Guide Process`）
3. `Guide Mask` 节点程序化生成遮罩
4. VOP 节点创建遮罩属性

### Attribute Paint

- 通过 `Attribute` 选项卡添加需要的遮罩属性名字
- 在 `Attribute` 参数中选中需要绘制遮罩的属性名，开始画
- 在别的节点上的 `No Override` 选项改为 `Skin Attribute` 即可应用遮罩调制该参数

### 节点内置 Masking（以 Guide Process 为例）

- `Curve Mask`：利用斜坡（ramp）参数沿长度遮罩曲线
- `Noise Mask`：对随机选中的部分进行遮罩
- `Input Mask`：导入现有遮罩

### Guide Mask（程序化生成）

`Additional Masks` 选项卡可选模式：

| 模式 | 生成逻辑 |
|---|---|
| `Noise Mask` | 噪波作遮罩 |
| `Length Mask` | 根据长度生成遮罩 |
| `Skin Curvature` | 基于皮肤根部到顶部位置的弯曲程度 |
| `Geometry Mask` | 连接到第四输入的曲面几何体内外遮罩曲线 |
| `Random Mask` | 随机生成遮罩 |

## 6. 更多节点

| 节点 | 作用 |
|---|---|
| `Feather Uncondense` | 将羽毛变为曲线——**只有转化为曲线才能被别的工具修改**；`Output Groups` 参数可将羽毛杆和倒钩（羽毛丝）分组区分开 |
| `Guide Tangent Space` | 给曲线增加切线空间（输入 1 = 曲线，输入 2 = skin 模型）；把在曲线上做好的程序化细节还原给羽毛 |
| `Feather Visualize` | 改变视窗中羽毛的可视化——修改参数时看不清就用它 |

## 7. Feather 在 Solaris 中的渲染设置

- 引入羽毛和模型
- 使用 `Houdini Procedural: Feather` 程序化生成用于渲染的羽毛：
  - `Procedural Prim` 参数引用羽毛路径
  - `Groom Rest` 参数引用羽毛曲线
- 通过 `Houdini Preview Procedurals` 节点预览生成用作渲染的羽毛

渲染器/材质注意：

- **Mantra 渲染器**：不能用当前模板化的方式渲染——需要用 `Feather Uncondense`
  把羽毛转化为曲线再渲染
- 需要使用羽毛的 `Cd` 颜色时，用 `MtlX Geometry Color` 节点获取羽毛颜色信息

（笔记结尾"对毛发添加动力学解算"章节尚为空白，原笔记无内容。）

## 8. CHOP 模块小笔记（动画通道——螺旋桨旋转案例）

> CHOP（Channel Operator）用波形图驱动通道。笔记只有一个案例，记录如下。

**螺旋桨旋转**完整步骤：

1. 建好大概的螺旋桨模型，在 `chop network` 里创建波形控制螺旋桨旋转
2. 两个 `wave` 节点：
   - 左边的 `wave`：生成直线上升、又马上降到底部的波形（旋转的往复）
   - 右边的 `wave`：生成从无到有的波形，用来控制生成时间
   - 使用 `Channel Name` 参数**命名该通道名称**
3. `limit` 节点：限制最大最小范围
4. `Warp` 节点：用第二个通道对第一个输入的通道进行时间扭曲变形
5. `Shift` 节点：左右平移波形图
6. `Math` 节点：放大波形图，让 `0~1` 的值产生 `0~359.9` 的旋转角度
   > **不能用 360**：360 和 0 产生冲突，会导致每旋转一周可能卡壳 1 帧
7. `Export` 节点：将名为 `chan1` 的波形图导出到 `Transform` 节点 `Rotate` 的
   `y` 通道（ry）——**在节点上点击 `Export` 图标才能导出**

CHOP 节点速查：

| 节点 | 作用 |
|---|---|
| `wave` | 生成波形（用 `Channel Name` 命名通道） |
| `limit` | 限制波形最大最小范围 |
| `Warp` | 用第二个通道对第一个通道做时间扭曲 |
| `Shift` | 左右平移波形 |
| `Math` | 放大/运算波形（0~1 → 0~359.9 角度） |
| `Export` | 导出通道到目标节点参数（需点 Export 图标） |

## 易错点

- **`Feather Template Interpolate` 默认 lookup method（`Weight Arrays`）会报错** →
  改为 `Group` 或 `Match by Name Attribute`
- **羽毛方向乱** → 没用 `Guide Tangent Space` 设置切线空间（输入 1 = 曲线、
  输入 2 = skin）；且要输出 `barborient` 属性与 `Guide Groom` 的方向记录对应
- **`Feather Width` 的宽度属性在视口看不到效果** → 该属性对视口曲线无影响，
  需要 `Feather Uncondense` 或 `Houdini Procedural: Feather` 才能观察
- **`Guide Groom` 修改上游后不更新/出错** → 它是缓存节点且非程序化：每次更改
  上游必须清除它并重新输入；建议放在羽毛进入之前
- **画羽毛形状曲线要从下到上**（`Feather Shape Organize` 输入 1 的约定）
- **Mantra 不能直接渲染模板化羽毛** → 先 `Feather Uncondense` 转曲线
- **要羽毛 Cd 颜色** → 用 `MtlX Geometry Color` 节点获取
- **CHOP 角度放大不要用 360**：360 与 0 冲突，每旋转一周可能卡壳 1 帧；
  用 `0~359.9`
- **CHOP 导出不生效** → `Export` 节点要在节点上点击 `Export` 图标才能导出，
  且波形需用 `Channel Name` 命名、与目标通道（如 ry）对应
