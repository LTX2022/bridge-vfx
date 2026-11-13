# Vellum 布料/约束与 RBD 刚体破碎实战（学自用户笔记 Vellum布料等.md, Dop等刚体破碎.md, 2026-08-25）

> **⚡ TL;DR 速答卡**（读完能解决就不用往下翻）
> - Vellum Solver 按顺序调：Substeps → Constraint Iterations（越高约束越强、布料越硬）→ Collision Passes → Post Collision Passes；同成本下 2 子步+10 碰撞通常优于 1 子步+20 碰撞
> - 布料太硬先降 Constraint Iterations 而非盲目加子步；旗帜实战值：约束迭代 200、Time Scale 0.5、阻尼比 0.075，开 Secondary Constraint Pass + Multi-Pass Solve 出折痕褶皱细节
> - `stopped` 属性：0=自由、1=只旋转不动、2=只动不旋转、3=全锁；撕裂用 `breakthreshold`/`breaktype`；布料宽度=`pscale`
> - Vellum Constraints 第 3 输入=碰撞物；缝合用第二个 Constraints 选 `Weld Points`（仅解算时逻辑融合），渲染前必须过 `Vellum Post Process` 重连焊接顶点（导出动态模型也需要它）
> - 幕布驱动：Solver 内 snippet 改 `restscale`（1.5=每片解算成自身 1.5 倍）；`point(2,"mask",@ptnum)` 的 2 指向碰撞输入端，路径写错 mask 读不到
> - 旗帜/幕布褶皱难看先查模型细分是否足够高；Attribute Noise 只拉 x 轴时 `Range Values` 要设 `Zero Centered` 才能从模型中间拉伸
> - 固定布料：`Pin to Target` + Pin Type=`Soft` + 勾 `Match Animation`；真实风场链：bound→isooffset→scatter（多撒点）→pointvelocity→volumerasterizeattributes，进 Solver 内 popadvectbyvolumes 导入
> - 布料匹配原模型用 `Wrap`（原模型不能有位移；输入 1=主几何、2=动画参考姿势、3=动画网格），再用 point_mix_ql 混 P 属性
> - Grain（沙/雪）比 POP 快；MPM 适合弹塑性大变形材料（雪、土壤、金属；混凝土=弹塑性+脆性）
> - voronoi+boolean 联合切割：内部表面必须用 `subdivide` 加精度，用 `divide` boolean 结果有误
> - RBD Bullet Solver 五输入：1=渲染几何、2=约束几何（需 name/constraint_name 属性否则约束不生效）、3=代理几何、4=碰撞几何、5=引导几何
> - 碰撞粘附：`Min Sticky Collision` 必须 ≥ 0 才粘得住；`Transform Pieces`：输入 1=要变换的几何、2=带变换属性的模板几何，反了模型不动
> - RBD io 缓存选 `Simulation Point`（只存每部分变换的点序列）比逐帧缓存几何更省磁盘和加载时间

来源：`C:/Users/<USERNAME>/OneDrive/Node/Node/Houdini基础模块/Vellum布料等.md`、
`C:/Users/<USERNAME>/OneDrive/Node/Node/Houdini基础模块/Dop等刚体破碎.md` 全文。
原始笔记保持只读；本文件是蒸馏版——保留具体参数、坑、案例步骤，作为
`references/workflows/vellum`、`destruction` 通用指南的实战补充。
（图片链接保留原样，截图见原笔记。）

## 1. Vellum 布料基础

### 20.5 新功能：风力遮挡

- Vellum Solver 内置风力遮挡，让布料受风更真实。
- 位置：`Force` 标签下的 `Wind Shadowing` 下拉菜单，**默认开启**。
- 参考：[高速移动布料官方文档](https://www.sidefx.com/docs/houdini/vellum/quickmovingcloth.html)

### 布料常用属性速查

| 类别 | 属性 | 类型 | 作用 |
|---|---|---|---|
| parameters | `friction`, `dynamicfriction` | float | 摩擦力 |
| parameters | `pressurescale` | float | 压力 |
| state | `stopped` | integer | 定义哪些点参与解算（见下表） |
| Collision | `pscale` | float | 布料宽度 |
| Breaking | `breakthreshold` | float | 定义布料什么时候撕裂 |
| Breaking | `breaktype` | string | 撕裂种类 |
| Dynamics | `rest` | vector | 布料静止状态下的位置信息 |
| Dynamics | `stiffness` | float | 布料强度 |
| Dynamics | `compressionstiffness` | float | 约束强度 |

**`stopped` 属性取值**（控制点解算行为）：

| 值 | 行为 |
|---|---|
| 0 | Particle is free，可参与任何解算 |
| 1 | 只能旋转，但被定住不能移动 |
| 2 | 不能旋转，但可在空间中任意移动 |
| 3 | 位移、旋转都不行 |

## 2. Vellum 常用节点

- `Vellum Constraints`
  - **第三个输入端是碰撞物**
  - `Constraint Type` 可选 vellum 的种类
  - TAB 键搜索有很多 `vellum configure` 预设：`balloon`、`cloth`、`Fluid` 等，最常用 `cloth`
  - ![QQ20250831-033239.jpg](./图片/Houdini/QQ20250831-033239.jpg)
- `Vellum Solver` 调节步骤（按顺序调）：
  1. `Substeps`：子步骤，一帧解算几次
  2. `Constraint Iterations`：约束迭代——增加约束解算次数变更精确；
     值越高约束越强，布料看起来越硬
  3. `Collision Passes`：解算过程中提高碰撞精度
     - 拥有 2 个子步骤和 10 次碰撞的成本，与 1 个子步骤和 20 次碰撞的成本大致相同，
       **但前者效果可能会更好**
  4. `Post Collision Passes`：解算完成后再用算法提高碰撞精度
  - ![QQ20250831-033502.jpg](./图片/Houdini/QQ20250831-033502.jpg)
- `Vellum Brush`
  - 不用解算，直接画布料形态，回车后直接开画
  - `Reset All Changes` 把画过的布料重置
  - `Brush` 选项卡 → `Shape` 改变画笔形态（`Surface` 和 `screen` 最常用），按 B 键或右键选择
  - `Brush` 选项卡 → `Mode` 改变笔刷类型（1~6），右键可直接选择
  - ![QQ20250831-031714.jpg](./图片/Houdini/QQ20250831-031714.jpg)

## 3. Vellum 案例

### 3.1 斗篷（布料缝合）

- `Vellum Constraints cloth` 节点：描述所有牛皮纸材料类型，`Constraint Type` 选约束类型
- `Planar Patch` 节点：创建均匀细分的三角形块；可精确指定边界点计数，用于程序拼接

**布料缝合方法一**：

- 给周边创建点，通过相同的 `Edge Length` 控制相同数量的焊接点
  - ![QQ截图20240529164206.png](./图片/Houdini/QQ截图20240529164206.png)
- 通过 `Vellum Drape` 焊接并控制布料形状；`Vellum Cloth` 第三个输入连不动的碰撞体
  - ![QQ截图20240529165637.png](./图片/Houdini/QQ截图20240529165637.png)

**布料缝合方法二**：

- 先在模型左右两边的周围选好区域
- 第一个 `Vellum Constraints` 的 `Constraint Type` 选 `Cloth`，整体可用 Cloth 布料模拟
- 第二个 `Vellum Constraints` 的 `Constraint Type` 选 `Weld Points`，使相关点在求解过程中
  逻辑上融合成一个点（其他情况下点仍保持独立）
- `Vellum Post Process` 可在模拟之后重新连接焊接的顶点，使几何在渲染时看起来是连接的
  - ![QQ20251010-194303.png](./图片/Houdini/QQ20251010-194303.png)

`Vellum Cloth` 节点：`Pin to Animation` 参数用来放要固定位置的点。
（截图见原笔记：QQ截图20240529224403.png、QQ截图20240529155450.png、d88a2ddb-69d9-4dfe-a5b6-ca59c1e2c79b.png）

### 3.2 幕布

**方法一（VEX 改 restscale）**：在 `Vellum Solver` 内部加 snippet：

```shell
restscale = 1;
if(point(2, "mask", @ptnum)>0.1)
    restscale = 1.5;
```

- 修改 `restscale` 可修改每一小片解算时要等于自身的几倍（`1.5` = 变为 1.5 倍，`1` = 无变化）
- `point()` 是从几何图形中读取点属性值（第一个参数 `2` 指向碰撞输入端）
- 截图见原笔记：QQ20240713-114300.png、QQ20240713-114120.png、QQ20240714-122756.png、QQ20240714-122917.png

**方法二（噪波拉伸 + Blend Shapes 收拢）**：

- `Planar Patch`：生成网格并设置边长（调整三角形细分尺寸）；提供顶点、侧边、缝隙等组
  - **记得勾选 `Top Seam`**，才有顶部选区作为一组来储存做约束的组
  - ![WX20250414-151416@2x](./图片/Houdini/WX20250414-151416@2x.png)
- `Attribute Noise`：
  - 设置 `P` 属性且**只影响 x 轴**，只会影响 x 轴的拉伸
  - `Noise Value` 中的 `Range Values` 设为 `Zero Centered`，缩放 `Amplitude` 时才能从模型中间开始拉伸
  - 通过 `Noise Pattern` 的 `Element Size` 和 `Offset` 设置噪波频率和大小
  - ![WX20250414-151950@2x](./图片/Houdini/WX20250414-151950@2x.png)
- `Transform`：把模型在 x 轴上压缩为原尺寸的一半（多少都行），把顶部点位置压到原来的一半，
  驱动下方布料摆动
- `Blend Shapes`：在 `blend1` 参数下 K 帧，实现时间范围内从展开形态形变为收起状态
  （从左边向右边输入变化）
- `Rest`：在几何体上创建静止属性，让程序化纹理在变形时保持在表面上
- `Vellum Constraints` ×2：
  - 第一个：`Constraint Type` = `Cloth`（布料约束）
  - 第二个：`Constraint Type` = `Pin to Target`，组类型设为点并选顶部点的约束组；
    `Pin to Animation` 下的 `Pin Type` 设为 `Soft`（建立点与目标位置间的零长度距离约束），
    并勾选 `Match Animation`（解算期间是否从动画更新目标）
  - ![WX20250414-171848@2x](./图片/Houdini/WX20250414-171848@2x.png)
  - ![WX20250414-171812@2x](./图片/Houdini/WX20250414-171812@2x.png)
- 最后加 `Vellum Solver` 直接解算

### 3.3 旗帜（含旗杆抖动 + 真实风场）

船的帆布抖动也可以用这个方法制作。

**模型处理**：

- 旗帜**必须细分足够高**，不然褶皱不会好看

**旗杆抖动**：

- `softtransform`：先让杆子整体抖动；再用第二个 `softtransform` 让杆子某个小位置移动幅度更大
- `blend shapes`：设置一开始旗杆先不受位移影响（避免影响布料模拟），然后慢慢转变成有形变的杆子

**速度场（模拟真实风的流动）**——节点链：

| 节点 | 作用 |
|---|---|
| `bound2` | 设置风的边界（速度场范围） |
| `isooffset2` | 从几何体构建偏移曲面生成 volume，内部可撒点 |
| `scatter2` | 撒点，点撒多一些 |
| `pointvelocity` | 计算几何体点的速度，设置风的初始速度和大小。第一个设基础速度场，第二个再叠加一个不同噪波的速度场（继承上一节点） |
| `volumerasterizeattributes2` | 将点属性采样放置到 VDB 中 |

（截图见原笔记：QQ20251018-001425.png、QQ20251018-001656.png、QQ20251018-184856.png）

**布料解算**：

- `group3`：选择旗帜和旗杆接触的边，用来做固定约束
- `vellumcloth2`：约束类型 `Cloth`；`Bend` 弯曲下改 `Stiffness`（刚度）设置折弯约束刚度，
  `Rest Angle Scale`（静止角度比例）修改折弯约束静止角与原始二面体三角形间的角度
  - ![QQ20251018-002011.png](./图片/Houdini/QQ20251018-002011.png)
- `vellumconstraints2`：`Constraint Type` = `Attach to Geometry`（附加到几何体），
  将指定点附加到第三个输入的几何体；它们在附加框架上存储最近点，并创建绑定距离约束。
  **用来设置固定不变的点**。目标几何体 `Target Geometry` 可以不设置，此组指定 `Stitch`
  缝合约束的后半部分（缝合点：使用距离将同一几何中的点拼接在一起的约束）
  - ![QQ20251018-002525.png](./图片/Houdini/QQ20251018-002525.png)
- `vellumsolver2` 参数（旗帜实战值）：
  - 增加子步幅；**约束迭代增加到 200**——不会拉伸太多，僵硬的约束需要更多迭代才能收敛
  - **时间尺度（Time Scale）减到 0.5**：移动更慢、更逼真
  - `Force` 选项卡：**阻尼比增加到 0.075**；`Velocity Damping` 是更暴力的降速方法，
    速度直接按此量缩放，突然的运动被快速增加阻尼
  - `Advanced` 高级选项卡：打开辅助约束通道（`Secondary Constraint Pass`）和多通道解算
    （`Multi-Pass Solve`）——**实现抖动时产生更多小细节（折痕、褶皱）**
  - 进入 Solver 内部设置风：
    - `popadvectbyvolumes1`：导入速度场，用速度体积移动粒子
    - `popforce1`：对粒子施力；不想设速度场时可给 `Force` K 关键帧实现更仿真的风
    - （截图见原笔记：QQ20251018-010657.png、QQ20251018-003821.png）
- `vellumpostprocess1`：对解算**结果**做常见处理；**使用该节点才可导出动态模型出去**

**匹配模型**（幕布与原模型不匹配时修，需装额外脚本）：

- 布料选区：
  - `Rest` 节点：`Mode` 设 `Extract Rest`——从属性检索当前剩余值并更新位置，
    使 geometry 恢复到原始 REST 设置
  - `timeshift2`：将旗帜冻结在第一帧（未解算时）
  - `attrib_ramp_ql2`：用 Cd 设 ramp 选区，选取旗杆连接处
  - ![QQ20251018-014351.png](./图片/Houdini/QQ20251018-014351.png)
- 修复：
  - `Wrap`：将几何体包裹到动画网格（包裹变形器）。作为 `Point Deform` 的替代方法，
    此节点考虑表面方向以构建完整偏移矩阵，可包裹到点、线和多边形。
    **注意：原模型不能够位移**。它可以将物体的形变和原本形态混合在一起。接法：
    - 第一个输入：主几何体（选区选好的几何体）
    - 第二个输入：动画参考姿势（没有做形变的几何体）
    - 第三个输入：动画网格
- 混合：
  - `attribcopy2`：将 Cd 属性复制到另一个物体
  - `point_mix_ql`：通过控制属性混合两个输入之间的 `P` 属性（混合位置）
  - 最后删除 `Cd` 属性
  - ![QQ20251018-184506.png](./图片/Houdini/QQ20251018-184506.png)

## 4. Vellum Grain（沙/雪颗粒）

- 虽然也可以用 POP 做 grain，但**没有 vellum 快**
- 一般做沙子、雪等
- MPM 适合弹塑性/完全弹性材料、大变形：雪、土壤、金属是弹塑性物体；混凝土是弹塑性+脆性混合体

### Grain 常用节点（Vellum Constraints Grain）

| 参数 | 作用 |
|---|---|
| `Create Points from Volume` | 为体积创建点，基础沙子颗粒 |
| `Particle Size` | 改变粒子大小（每粒子直径）；pscale 属性会被设成直径的半径 |
| `Packing Density` | 粒子排布密度（会有穿插） |
| `Jitter Scale` | 让粒子排布更随机 |
| `Adjust Radius to Avoid Overlap` | 为防穿插微调粒子大小 |

![QQ20250831-031047.jpg](./图片/Houdini/QQ20250831-031047.jpg)

### 案例：粒子落下形成图案

- `Vellum Configure Grain`：`Create Points from Volume` / `Particle Size` / `Jitter Scale` 同上
- `Vellum Solver`：
  - `Substeps`：增加子步数可增加精度，但增加计算时间
  - `Constraint Iterations`：粒子不需要太高，可以降低
  - `Smoothing Iterations`：平滑迭代，粒子不需要太高，可以降低
- `Time Shift`：将时间冻结在粒子快不动的那一帧，平铺图片会更好
- `UV texture`：选择展开好 UV
- `Point VOP`：将 UV 纹理应用到点上
- `Attribute from Map`：`Texture Map` 选择需要贴上去的图片

## 5. RBD 刚体破碎

### 关键经验

- 在使用 `voronoi` 与 `boolean` 联合切割碎块时，voronoi 出来的**内部表面应该用
  `subdivide` 节点添加精度，而不要用 `divide`**，否则 boolean 结果有误
- 碰撞物体 `collision` 和 `collisionvel`、`divergence` 场是膨胀和收缩，**设置负值就是吸收**
- 参考笔记：[Applied_houdini 破碎模块学习笔记](https://www.jianshu.com/p/497890c36298)

### 常用节点

| 节点 | 作用 |
|---|---|
| `MPM Post-Fracture and Deform Pieces` | 破碎后变形（21 新版） |
| `Labs PolySlice` | 将面切片为面或多段线 |
| `polysplit` | 多边形**切割**（类似 Blender 按 K 的切割工具） |
| `polyslice` | 将多边形**切片**为多边形或折线 |
| `Assemble` | 将同一碎片的 Primitive 组合在一起，清理断裂内部面，准备刚体模拟几何（整理内部） |
| `Join` | 将多条开口曲线/边界边首尾相连，合并成连续曲线或封闭面 |
| `Glue Pieces` | 在 DOP 动力学模拟中创建粘合约束（物理约束而非视觉几何连接） |
| `DOP Import Field` | 从 DOP 模拟导入标量场和矢量场，简化流体场导入 SOP |
| `DOP import` | 从 DOP 模拟导入几何体或变换（从 DOP 网络中的对象或关系导入） |
| `RBD io` | 打包 RBD 破裂几何体，保存到磁盘再加载回来（见下） |

### 在任何 DOP 网络内添加碰撞（简易快捷方法）

（截图见原笔记：QQ20260309-194919.png）

### RBD Bullet Solver 输入端语义（必须记牢）

`RBD Bullet Solver` 是 DOP 网络的包装器，用于简化 Bullet Solver 模拟。

| 输入端 | 内容 |
|---|---|
| 第 1 输入 | **渲染几何体**。若第 3 输入未提供几何，则此几何用作模拟几何 |
| 第 2 输入 | **约束几何**：实例化动态约束（模拟片段之间的关系）。可由 RBD 材料断裂 SOP、来自线/曲线/规则的 RBD 约束等创建；需要点属性将它们连接到各自部分，需要基元属性匹配约束关系 DOP 的数据名称（`name`/`constraint_name`，可用 RBD 约束属性 SOP 设置） |
| 第 3 输入 | **代理几何体**：渲染体的简化表示，更适合快速模拟；提供时用作模拟几何 |
| 第 4 输入 | **碰撞几何**：可识别填充几何形状，可用 RBD Configure SOP 单独驱动行为（部分动画化、部分变形、部分用球体表示） |
| 第 5 输入 | **引导几何**：打包几何或可按连通性拆分打包成离散碎片的网格；未打包时内部会转为打包片段 |

### 小案例：沿抛物线抛出

（截图见原笔记：QQ20250913-144046.png、QQ20250913-144235.png、QQ20250913-144309.png）

- `Point Velocity`：设置好抛出去的初速度
- `assemble`：清理中断边并创建生成部分——这里只用作生成一个 `name` 和一些属性，
  使 `Sphere` 和 `rubbertoy` 模型对应；这样就可以通过 `Transform Pieces` 节点，
  根据**模板几何（第二个输入端）**上的变换属性变换**输入几何体（第一个输入端）**
- `DOP Import`：从 DOP 模拟导入几何体或变换，路径为：`../rbdbulletsolver1/dopnet/`

### 简单碰撞

- `RBD Configure` 节点：打包并创建描述刚体对象的属性
  - `Active`：将属性设置为指定的值，默认值为 1
  - `Min Sticky Collisio...`：碰撞产生的最小脉冲，将导致该物体粘附在另一个物体上；
    **此值必须大于或等于 0 才能使对象粘附**
- `RBD Bullet Solver`：运行动态 Bullet 模拟；`Ground Type` 选择要使用的地面碰撞类型
- （截图见原笔记：微信截图_20240127155842.png、微信截图_20240127154927.png）

### RBD io 的 Storage Type（缓存策略）

| 类型 | 行为 |
|---|---|
| `Geometry Only` | 存储一个解压缩的几何体序列，只是几何体 |
| `Packed Geometry, Constraints and Proxy` | 将几何体、约束和代理几何打包成三个打包基元，三元组保存为单个几何序列；第 1/2/3 输出分别是解包的几何体、约束和代理几何 |
| `Simulation Point` | 存储描述每个部分变换的模拟点序列——比每帧缓存转换的片段更高效（磁盘/加载时间）；此模式下第 2、3 输出始终为空。`Quick Setup` 菜单：`Transform High-Res Geometry` 将变换应用于几何体（出来点的位置）；`Cache High-Res Geometry` 缓存第一个输入中的其余几何体 |

（截图见原笔记：WX20240904-123855@2x.png、WX20240904-124054@2x.png）

### Solaris 中的 RBD

- `RBD Destruction` 节点：USD 中的裂缝模拟示例，也可用作固定效果；具有将打包图元作为
  骨架动画导入的参考实现。**依赖 Python 做繁重数据提升，不能很好地扩展**
- `Bake Skinning`：将 UsdSkel 驱动的动画"烘焙"为转换和点位置；
  **此节点仅对场景中的所有骨架调用 USD 的函数**，把蒙皮结果直接烘焙到点和变换中，
  将骨架姿势的基元转换为普通几何体缓存（无特殊骨架行为）
- 将 `Output type` 设为 `Dynamic Skinning`：将破裂几何体创建为静态网格体 +
  表示部分变换的 USD Skel
- `Agent Layer`：将新的形状和层添加到代理基元中（形状绑定引用代理形状库中的形状，
  指定使用的变形器或要附加静态形状的关节）
- 原生导入 Solaris 也可走 KineFX / Crowd Agent 路线
  （截图见原笔记：WX20250409-193408@2x.png、WX20250409-193500@2x.png、
  QQ20250409-195545.png、WX20250409-200038@2x.png）

### 车祸

[官方教程：车祸 RBD SIM](https://www.sidefx.com/tutorials/car-crash-rbd-sim/)

- `RBD Car Fracture`：破碎切割节点（21 版加入）
- `RBD Car Transform`（21 版加入）

### 玻璃破裂

[使用玻璃破碎官方手册](https://www.sidefx.com/docs/houdini/destruction/glass.html)

## 易错点

- **voronoi + boolean 联合切割**：内部表面必须用 `subdivide` 加精度，用 `divide` 会
  导致 boolean 结果有误。
- **约束迭代与布料硬度**：`Constraint Iterations` 越高约束越强、布料越硬——布料太硬
  先降迭代而不是盲目加子步。2 子步 + 10 碰撞通常优于 1 子步 + 20 碰撞（成本相同）。
- **旗帜/幕布褶皱难看**：先检查模型**细分是否足够高**，再调 Solver。
- **`Weld Points` 缝合后渲染断开**：焊接点只在解算时逻辑融合，渲染前必须过
  `Vellum Post Process` 重新连接焊接顶点；且导出动态模型也需要该节点。
- **Vellum Solver 内 VEX 的 `point(2, ...)`**：第一个参数 `2` 指的是碰撞输入端，
  路径写错 mask 读不到。
- **`Attribute Noise` 只拉 x 轴**：`Range Values` 忘设 `Zero Centered` 时，
  `Amplitude` 缩放不会从模型中间开始拉伸。
- **`Wrap` 节点限制**：原模型不能有位移；三输入接错（主几何/参考姿势/动画网格）
  形变混合结果就错。
- **`Min Sticky Collision` 想粘附却粘不住**：值必须 ≥ 0 才生效。
- **`RBD Bullet Solver` 输入端**：约束几何连到第 2 输入、代理几何连第 3 输入——
  顺序不能想当然；缺 `name`/`constraint_name` 属性时约束不生效。
- **`Transform Pieces`**：第一个输入是输入几何体，第二个输入是带变换属性的模板几何，
  方向反了模型不动。
