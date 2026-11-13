# For-Each / Compile Block / Solver 速查（学自用户笔记 VEX和VOP和脚本插件编写等.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\VEX和VOP和脚本插件编写等.md` 第 1595-1958 行。
原始笔记保持只读；本文件是蒸馏版——循环、编译块、增量解算三个"让节点树重复跑起来"
的机制。截图见原笔记。

## 1. 三者区别（先分清）

| 机制 | 做什么 |
|---|---|
| For-Each / For loop | 循环：**同一帧**上重复执行一段节点树 |
| Solver | **上一帧基础上**增量解算同一段节点树（生长蔓延类最常用） |

- For-Each 属于**单线程**工作节点 → 想多线程就套 Compile Block（见下）。
- 各个 For-Each 节点其实是同一个节点（Block Begin / Block End）的不同预设。

## 2. For-Each

### 2.1 两种循环类型

- **FOR 循环**：对一个物体多次操作。如球体上移 1 米重复 10 次，循环次数可改。
- **FOR EACH 循环**：对 10 个物体每个单独操作一次。如 10 个球各上移 1 米，
  循环次数 = 物体数，不可改。需要先用 `connectivity` 给每个独立物体一个
  不同属性值来区分。

### 2.2 Block Begin / Block End 关键参数

**Block Begin（输入端）——差别全在 `Method` 参数**：

| Method | 作用 |
|---|---|
| `Fetch Input` | 复制输入内容进行输入（FOR 循环用） |
| `Extract Piece or Point` | 每次迭代输出输入几何的一个 "piece"（按片循环用） |
| `Fetch Metadata` | 获取循环元数据（detail 属性），生成 `foreach_begin1_metadata` 节点 |

**Block End（输出端）**：

- `Iteration Method`：`By Count`（按固定次数）/ `By Pieces`（对输入每个 piece 迭代一次）。
- `Gather Method`：`Merge Each Iteration` 合并每次迭代结果。
- `Piece Attribute`：指定定义片段的属性（如 connectivity 生成的 `uvs`）。
- 勾选 `Single Pass` 可单独查看某一次迭代（调试利器）。

### 2.3 循环元数据与 detail() 表达式

`foreach_count` 节点（Method = Fetch Metadata）生成的 detail 属性：

- `numiterations`：预期迭代总数
- `iteration`：当前迭代编号（从 0/1 开始，代表第几次循环）
- `value` / `ivalue`：分段循环中当前属性值（如 piecename）或整数版本
  （值超 2400 万浮点丢精度时用 ivalue）

在参数里取当前循环次数（表达式函数 `detail(surface_node, attrib_name, attrib_index)`）：

```
1+detail("../foreach_begin1_metadata1","iteration",0)
101+detail(-1,"iteration",0")
```

`-1` 这个值来自 **Spare Input0**：给节点增加 spare input 指向含循环值的节点，
就能用 `-1` 代表正在迭代的几何体（`-1, -2, -3` 往下排，与蓝线连接的 `0,1,2` 相反）。
Spare Input0 参数需要写入包含循环值的节点。

### 2.4 案例：鸟群煽翅（For-Each Number 存动画变体）

- `filecache` 缓存整个模型，`timeshift` 冻结当前循环那一帧；
  `attribcreate` 把每帧动画数据存到 `variant` 属性的不同值。
- 循环次数表达式：`101+detail(-1,"iteration",0)`（+101 是起始帧偏移）。
- foreach_begin1：`Method = Fetch Input`；
  foreach_end：`By Count` + `Merge Each Iteration`。

### 2.5 案例：叶子拆分（For-Each Connectivity）

1. `Connectivity` 节点：为每组连接的 primitive 创建唯一值属性
   （`Attribute` 参数自己起名如 `uvs`），`Connectivity Type` 选 `Primitive`。
2. foreach_begin1：`Method = Extract Piece or Point`。
3. foreach_count1：`Method = Fetch Metadata`。
4. foreach_end：`Iteration Method = By Pieces`，
   `Piece Attribute = uvs`，`Gather Method = Merge Each Iteration`。

### 2.6 VEX 里的 foreach

```c
foreach ([element_type] value; array) {

}
```

每次迭代把当前成员复制到 value，直到遍历完全部数组成员。
（完整遍历示例见 vex-vop-notes.md 第 4 节。）

## 3. Compile Block

> for 循环外面最好套上 compile block，使 for 循环模块多线程运行。

**原理**：普通节点链每个节点都保存一份几何体（方便切换节点快速显示）；
Compiled SOPs 把节点链合并成一个整体编译执行，切换块内节点显示时编译不生效。

**三大好处**：

- **多线程 for-each**：把迭代分布到多个内核。
- **更高效用 OpenCL**：块内多个 OpenCL 节点可把数据留在显卡上不来回拷贝。
- **就地操作**：块内节点可在同一份几何体上就地工作（不允许外部引用），额外加速。

### 3.1 使用要点

- 不支持编译的节点：网络里按 `d` 打开显示，不能编译的节点旁有打叉的齿轮。
- 块内有不可编译节点但没用到 → 勾选 `Delay Incompatible Node Errors Until Cooked`
  （运行时才识别）。
- 编译失败退化常规计算 → `Fallback to Traditional Cook If Compile Fails`
  （**仅当错误发生在编译阶段**才可退化；勾了 Delay 后无法退化）。
- 输出结果没更新 → 点 `Force Compile`（compile block 在锁定的 HDA 里不会有此问题）。
- compile 可以嵌套。

### 3.2 限制（重要）

- 仅可用可编译节点；不可用 `stamp()` 表达式。
- 不可用局部变量、组件表达式（`$CEX` 之类）——按组件操作改用 VEX 节点如 attribute wrangle。
- 不可按名称引用内部几何体（`npoints("/obj/sphere1")`、`point(0,...)`）——
  用 **spare inputs** 替代（`-1` 端口引用）；通道值可以按路径引用（`ch("../sphere1/tx")`）。
- 禁用/隐藏的参数不参与计算；不支持 for-each 的 stop 条件。
- 涉及属性的连线（蓝线和紫线）都不能越过区块边界。
- 引用模块外的节点能工作但影响性能。
- 核心：任何需要从其他 SOP 读取数据的 SOP，必须在 cook 前**静态确定**，
  不能 cook 期间再确定；spare input 在编译块运行前会 re-cook。

### 3.3 编译不报错 ≠ 结果正确

`hscript command` 和 `python expression` 在循环迭代中会被**烘焙成一个固定值**，
不会随迭代变化：

```python
# python表达式（在编译块内不会每次迭代更新！）
hou.node("/obj/geo1/metadata").geometry().attribValue('iteration')
```

### 3.4 编译 For Loop 的正确姿势

- **将循环放在已编译块内**，而不是把编译块放在循环内。
- 顶层循环的 For-Each Block End 上勾选 `Multithread when compiled`
  （只在最外层循环勾，避免分布式任务爆炸）。
- 每个块的 Begin/End 节点要正确封装嵌套；编译块内的循环作为独立单元编译，
  必须在自己的 Begin/End 内。
- 官方建议：**先按正常流程完成工作，再用 Compile SOPs 优化**；
  性能提升最明显的是大量 piece 迭代处理。

### 3.5 Invoke 节点（调用编译块）

- 运行其他地方定义的编译块来处理本节点输入——复用块功能，不必复制/引用节点。
- 可指定多个输入，每个输入覆盖 block begin compile 的输入；输入名必须匹配，
  没匹配的用编译块原始输入。
- 可在编译块内暴露修改模型的参数，通过 Invoke 传入，实现"参数与行为分离"的无节点
  设置（每个点代表一个节点，`verb` 属性=节点类型、`parms` 属性=节点参数——
  apex graph 前身）。

### 3.6 parms 字典属性

- box 这类 SOP 就是一个 `verb`/`compilable` SOP，参数和建模行为是分开的；
  `attribute from parameter` 节点可在 detail attribute 里把参数列为 `parms` 字典
  （dictionary 属性）。查看 dictionary：geometry spreadsheet 里右键 inspect。
- 要通过 parms 改 box：spare input 指向 `attribute wrangle` 或
  `attribute adjust dictionary`，修改时指定 key 和数值。

## 4. Solver（生长蔓延）

- `Prev_Frame` 节点 = 上一帧的解算结果；Solver 内部在同一段节点树上逐帧增量。
- 经典做法：在上一帧模型上撒点→换成球体→与上一帧模型合并→重复，实现生长蔓延。

### 4.1 点搜索蔓延（Attribute Wrangle 完整代码）

前置：Solver 前的节点做一个 `Cd` 为黑色的撒点模型，选一个 `Cd` 为白色的点，
从白点开始蔓延。Cd 黑白都在第一个输入端。

无随机版：

```c
int pts[] = nearpoints(0,@P,0.5,500);
// 0：第一个输入端口  @P：使用当前点位置来查找  0.5：搜索半径  500：最大数量返回值  
// 返回一个点编号数组，记录几何上最近点的编号。（返回搜索距离内的点号数组）

foreach(int pt; pts)// 遍历所有满足pts条件的点，保存在pt内
// 循环pts数组.对于每次迭代，它会将当前成员复制到 pt ，然后执行循环，直到遍历完全部数组成员
{
    vector Cd2 = point(0, "Cd", pt);// 读取第一个输入端口中编号为pt的点的Cd属性值
    @Cd += Cd2;             // 把新的颜色属性和原来的颜色属性进行叠加
    @Cd = clamp(@Cd, 0, 1);//限制值在0~1之间
}
```

加随机版（VOP 里加 `Turbulent Noise`，用 `Pnoise` 记录随机值，
只把搜索位置换成 `v@Pnoise`）：

```c
int pts[] = nearpoints(0,v@Pnoise,0.5,500);
// 只修改了 v@Pnoise

foreach(int pt; pts)
{
    vector Cd2 = point(0, "Cd", pt);
    @Cd += Cd2;
    @Cd = clamp(@Cd, 0, 1);
}
```

### 4.2 VOP 点云方案

- `Point Cloud Open（pcopen）`：打开点云并搜索源位置周围的点。
  参数 `file`（要加载的文件）、`P`（查询位置）、`radius`（搜索半径）。
- `Point Cloud Filter（pcfilter）`：过滤 pcopen 查询到的点，参数 `handle`
  为用于筛选的点云。

### 4.3 Solver 案例的三个变体（原笔记 Solver1/2/3）

- **Solver1**（代码实现，推荐）：Cd 黑白点都在第一个输入端，单个
  `Attribute Wrangle` 即可完成蔓延（即 4.1 的 nearpoints 代码）；
  要随机性就在 Solver 前的 VOP 里加 `Turbulent Noise`，把随机值存进
  `v@Pnoise`，再把搜索位置从 `@P` 换成 `v@Pnoise`。
- **Solver2**（VOP 实现）：用 `pcopen + pcfilter` 节点树替代 wrangle，
  无随机和有随机是两套节点树（截图见原笔记）。
- **Solver3**：另一套节点树变体（截图见原笔记）。

共同前置：Solver 上游先做一个 `Cd` 全黑的撒点模型，并选一个 `Cd`
为白色的点作为蔓延种子——没有白点整段解算不会有任何变化。

### 4.4 什么时候用 Solver 而不是 For-Each

- 需要"历史信息"（这一帧依赖上一帧结果）→ **Solver**；
  生长、蔓延、积雪、感染扩散都是这一类。
- 同一帧内对一批元素各做一遍、互不影响 → **For-Each**（可套编译块多线程）。
- 两者可以组合：Solver 内部放 For-Each，逐帧对每片做增量处理。
- 判断口诀：要"记忆"用 Solver，要"批量"用 For-Each。
- Solver 想停在某帧看中间状态：直接在时间线上拖帧，每帧都是真实解算结果。

## 5. 易错点

- **For-Each 是单线程**：大量 piece 迭代务必套 Compile Block +
  `Multithread when compiled`，否则慢一个数量级。
- **编译块内 python/hscript 表达式被烘焙成固定值**：块不报错但结果错，
  迭代相关逻辑改用 VEX 或 `detail(-1, ...)` + spare input。
- spare input 端口号是 **-1、-2、-3**（与蓝线 0、1、2 相反），别写成正数。
- `Fallback to Traditional Cook` 只救"编译阶段"的错误；勾了
  `Delay Incompatible Node Errors` 后无法退化。
- Compile Block 输出"看起来没更新"先点 `Force Compile`；块内切节点显示时
  编译本来就不生效，别误判为坏了。
- For-Each 按片循环前必须先 `Connectivity` 造 piece 属性，否则所有片被当成一片。
- Solver 内引用 `Prev_Frame` 才有"上一帧"；直接引用输入 1 每帧都从原始几何开始。
- 鸟群类"存动画变体"案例中 timeshift 的帧号表达式记得加起始帧偏移
  （如 `101+detail(-1,"iteration",0)`），否则从第 0 帧取。
- Solver 蔓延不起作用时先查种子：没有一个 `Cd` 为白色的点，解算永远停在初始状态。
- 官方不建议把"尽量用编译块提性能"放第一位：**先正常流程做完，再用
  Compile SOPs 优化**；收益最明显的是大量 piece 迭代场景。
