# 大型案例：建筑爆炸全流程拆解（学自用户笔记 大型案例.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\大型案例.md`（约 450 行）。
原始笔记保持只读；本文件是蒸馏版。文中 `![...](./图片/Houdini/...)` 为原笔记截图相对链接，截图见原笔记。

## 案例一：学校建筑爆炸（旧版本）

### 目标

建筑爆炸摧毁效果：多材质切割（金属/砖块/木头）→ 刚体碰撞解算（冲击波驱动）→ 强弱胶约束 → Pyro 烟雾模拟 → 提取着色渲染。

### 总体流程

```
建筑建模（已完成）
  → 模型预处理 (fuse + normal)
  → rigid_destruction 内多种切割 (金属/砖块/木头)
  → 冲击波速度场 (IsoOffset + Scatter + attribwrangle)
  → 选择激活的碰撞体 (connectivity + group + active)
  → 约束 (Connect Adjacent Pieces + 强弱胶 attribwrangle)
  → DOP 碰撞解算 (rbdpackedobject + geometrywrangle 力场)
  → 碰撞制作内部材质 (unpack + inside 组 + material)
  → Pyro 模拟 (pyro_source → smoke_sim → 提取)
```

---

## 1. 前期模型处理

- 使用 `fuse` 节点简单处理一下未连接的边，然后再用 `normal` 来纠正一些法线。

## 2. 碎块处理（rigid_destruction 内部）

> 图中标明的各个切割是为了区分多个不同部位的切割方法，并不一定指实际切割的内容，可以认为是**切割方法的多样化**。

### 2.1 金属切割（撒点切割）

节点链：`Delete` → `attribwrangle1`（密度）→ `Scatter1` → `Scatter2` + `Copy` + `point jitter` → `Voronoi Fracture` → `Attribute Wrangle2`

- `Delete`：单独分割开建筑的一部分。
- `attribwrangle1`：控制物体不同部分的密度，依据不同密度撒上不同数量的点（`Scatter1`）。**注意 `Run Over` 参数使用 `Primitives`**。
- `Scatter1`：使用 `density` 进行撒点。
  - 取消勾选 `Relax Iterations`（均匀散布迭代次数）**结果更好**（可以顺便取消勾选 `Max Points Limit` 限制最大点数量）。
  - 取消 `Force Total Count` 撒点模式，勾选 `Density Attribute`，就可以用密度来撒点。
- `Scatter2` 就是普通的撒点；`Copy` 将几何体复制多个——这里是每个点在原地复制了 10 份，都在同一个位置，**需要再通过 `point jitter` 来抖动指向随机方向**，改变每一份复制出来点的位置。
- `Voronoi Fracture`：通过右边输入口对左边输入对象执行 Voronoi 分解来切割断开几何图形（**本案例没改任何参数**）。两个主要输入：要断裂的网格和构建每个 Voronoi 单元的点。
- `Attribute Wrangle2`：增加一个 `part` 属性，这样可以区分不同部位。

### 2.2 砖块切割（撒点切割 + 距离控制密度）

节点链：`Attribute Wrangle3`（距离→密度）→ `Scatter` → `Voronoi Fracture` → `Attribute Wrangle4`

- `Attribute Wrangle3`：判断和碰撞体（作为爆炸源）之间的距离，作为控制建筑被切割的数量参数。**离爆炸源越近 density（密度）越高**。
  - `getbbox_center(1)`：`1` 指第二个输入端，返回第二个输入端几何体边界框的中心点。
  - `length(@P - breakpointloc)`：计算 `@P`（各个物体自己的位置）到爆炸源中心点之间的距离。远的值就很大，近的值就很小。
  - `clamp`：输入数据限制在最小值和最大值之间。**`+ 0.002` 是为了让别的地方也有一点密度而不是 0**。
  - 核心公式：

    ```
    (ch("maxFallOffDistance") - distance)/ch("maxFallOffDistance")
    ```

    > 数学上的无穷大和无穷小问题：将 `ch("maxFallOffDistance")` 看成 `x`，则可视为 `x - distance / x`，当 `distance` 无穷大时等式值倾向于 0，当 `distance` 无穷小时等式值倾向于 1。
- `Voronoi Fracture`：同上，没改参数。
- `Attribute Wrangle4`：增加 `part` 属性区分不同部位。

### 2.3 木头切割（拉伸切割）

节点链：`Transform`（压缩）→ 切割 → `Transform`（`1/0.01` 还原）→ `RBD Material Fracture` → `RBD Configure` → `Exploded View`

- `Iron_bar` 的切割是先将它拉伸，切割后再将其还原，所以要区分左右 2 边不同方向来压缩切割。原理：
  1. 先将原模型缩小（`x/y/z` 轴其中 1 个或 2 个）；
  2. 然后默认撒点切割；
  3. 再将缩小的轴通过 `1/0.01` 放大还原。
- `RBD Material Fracture`：可以根据物体材质类型断裂输入几何体，目前支持**混凝土、玻璃板、木材和自定义**。它们还都具有约束网络。
- `RBD Configure`：打包并创建描述刚体对象的属性。
- `Exploded View`：可以炸开模型预览切割的形态（调试利器）。
- `Attribute Wrangle4`：增加 `part` 属性区分不同部位。

## 3. 冲击波速度场

节点链：`IsoOffset` → `Scatter` → `attribwrangle10`（vex 生成速度和法线场）

- `IsoOffset`：从几何体构建偏移曲面。在给定输入的情况下构建一个隐式函数，使用隐式函数在固定与原始曲面的偏移。允许输出隐式函数直接作为卷基元（`volume`），无需进一步处理。
- `Scatter`：**加了 `IsoOffset` 后，撒点将不仅局限在模型表面，也会在内部进行撒点**。
- `attribwrangle10`：使用 vex 生成速度和法线场。
  - `getbbox_center(0)`：返回第一个输入端的几何体边界框的中心点。
  - `random(@P)`：调用 random 函数，并将当前点的位置向量 `@P` 作为参数传递，返回一个随机值。
  - `normalize(@P - center)`：计算从 `@P` 到边界框中心点的向量并归一化（长度为 1，方向不变）。
  - 方向混合公式：

    ```
    outDir * (1 - ch("random")) + outDir * posRand * ch("random")
    ```

    - `outDir * (1 - ch("random"))`：通过一个参数缩放归一化后的向量大小（`random` 越大，值越小）。
    - `outDir * posRand * ch("random")`：加入 `posRand` 随机值让速度方向更加随机，由 `ch("random")` 控制随机大小。
    - 语义：**参数 = 1 最随机，= 0 完全按照归一化后的方向**。

## 4. 选择激活的碰撞体

节点链（`attribwrangle9` 上游）：`Attribute Delete` → `connectivity` → `attribwrangle6`（name）→ `group1`（deactive）→ `attribwrangle9`（active=0）

- `Attribute Delete`：删除 `density`、`name` 属性（**`name` 属性是 `Voronoi Fracture` 生成的属性**）。
- `connectivity`：对每个单独的碎块设置一个不同的 `class` 属性值，这样就可以区分开所有不同的碎块。
- `attribwrangle6`：给每个碎块赋予一个 `name` 属性。

  ```
  sprintf("piece%d", @class)
  ```

  - `%d` 是格式说明符，表示将后面的数字参数格式化为十进制数。
  - `@class` 代表当前模型的 `class` 值，放到 `piece` 字符后面生成字符串存储到 `name` 属性中。
  - `sprintf` 函数像 `printf` 一样格式化字符串。
- `group1`：选中模型**不想被破坏影响**的地方，并使用 `deactive` 做组名。
- `attribwrangle9`：将 `deactive` 组的 `active` 属性设置为 0，否则别的模型 `active` 属性都为 1，参与动力学解算。

## 5. 约束（强弱胶水）

节点链：`Connect Adjacent Pieces` → `attribvop1`（随机颜色）→ `attribwrangle11`（强弱胶判定）→ `attribdelete2`

### 5.1 Connect Adjacent Pieces

- 在附近的模型之间创建线条（改胶水约束）。
- `Connection Type` 选择 `Adjacent Pieces from Surface Points`：曲面点的相邻件。附近模型的质心将连接在一起，相邻的模型点分散在表面，以帮助检测近距离表面。
- **新版要勾选 `Find Boundary Connections`，并在后面的 `Cluster Attribute` 选上 `class` 属性**（`connectivity` 节点创建的）——仅在具有不同聚类属性值的相邻部分之间创建连接。这对于**在不同材质类型之间的边界处**的零件之间创建约束非常有用。
- `Search Radius`：搜索附近点时允许的最大距离。
- `Max Connections`：指定每个点可以连接到的点数上限。主要在从点连接相邻点时有用，也可以改进相邻曲面检测碎片。

### 5.2 attribvop1

- 随机赋予不同约束位置颜色（为下一步强弱胶判定做铺垫）。

### 5.3 attribwrangle11（核心：颜色判强弱胶）

**颜色产生变化的交界处设置为黑色 `弱胶`；颜色相同设置为白色作为 `强胶`。**

VEX 逐行拆解：

- `primvertex`：函数将图元/顶点对转换为线性顶点。
  - `primvertex(0, @primnum, 0)`：获取当前图元（`@primnum` 面编号）的第一个顶点（索引 0）的顶点编号。
  - `primvertex(0, @primnum, 1)`：获取当前图元第二个顶点（索引 1）所对应的点的编号。
- `vertexpoint(0, ...)`：根据上一步得到的顶点编号，找到它所属的点的编号。第一个参数用于指定几何体的输入（0 就是 1 号输入端）。
- `point(0, "Cd", pntOne)`：从输入 0 的几何体上，读取点编号为 `pntOne` 的 `Cd` 属性。
- `if(ptOneCd == ptTwoCd)`：比较两个点的颜色是否完全相同：

  ```
  s@constraint_name = "glueStrong";        // 设置约束类型名称
  f@breakforce = ch("Strongbreakforce");   // 设置断裂所需的力
  @Cd = 1;                                 // 约束本身颜色设白色（可视化）
  ```

  > `f@breakforce` 与 `DOP Network` 里 `sopsolver1` 中的值相等——设置在 sopsolver1 是方便在制作解算时调节这些参数。

函数签名备忘：

```
int primvertex(<geometry>geometry, int primnum, int vertex)
```

- `<geometry>`：指定几何体的输入；
- `primnum`：要从中获取顶点的基元数；
- `vertex`：图元内部的顶点编号，0 是第一个顶点。

### 5.4 attribdelete2

- 删除**点**的 `Cd` 属性，保留 `Primitive` 的 `Cd` 属性。

## 6. DOP 碰撞解算

### 6.1 SOP 侧打包

- `pack1`：将几何体打包到单个图元中，包装碎片。
  - `Path Attribute`：路径属性，分配给新创建打包图元一个路径（`path`）属性值。
  - `Name Attribute`：指定用于识别属于每个片段的名称属性（`name`）。
  - `Transfer Attributes`：转移属性（将 `active` 等）。
- `attribpromote1`：将 `name`、`active` 属性提升为点属性，**用点来模拟**。

### 6.2 DOP Network 内部

力：

- `rbdpackedobject1`：从 SOP 几何体创建一个表示多个 RBD 对象的 DOP 对象。
  - **把 `Geometry Source` 改为 `First Context Geometry`**——几何体来源使用连接到 DOP 网络的第一个输入的 SOP。
- `rigidbodysolver1`：设置和配置刚体动力学解算器，**不用调参数**。
- `geometrywrangle1`：核心功能——从第二个输入端的速度场中获取力信息，并根据**距离衰减**规律，将力施加到当前几何体的各个点上。
  - `Inputs` 选项卡：第一个 `Input 1` 选择 `Myself`，第二个 `Input 2` 选择 `SOP`，路径使用做出来的冲击波速度场的路径。
  - VEX 逻辑：

    ```
    nearPtNum = nearpoint(1, @P);                        // 在第二个输入(索引1)几何体中查找距当前点@P最近的点编号
    nearForce = point(1, "force", nearPtNum);            // 获取该点的 force 属性值
    force = nearForce * ch("forceScale");                // 乘手动参数，控制力的强度
    nearPtPos = point(1, "P", nearPtNum);                // 获取该点的 P 属性值
    dist = length(@P - nearPtPos);                       // 当前点与最近点之间的距离
    v@force = force * clamp((ch("fallofDist") - dist)/ch("fallofDist"), 0, 1);
    ```

  - 衰减因子 `(ch("fallofDist") - dist) / ch("fallofDist")` 再 clamp 到 0~1：
    - 当距离 `dist` 小于衰减距离 `fallofDist` 时，因子为正，且随距离增加线性减小；
    - 当距离大于等于衰减距离时，因子为 0。
  - `forceScale`：力的强度；`fallofDist`：力的衰减距离。
- `enablesolver1`：启用解算器 DOP，允许启用或禁用多个子解算器。`Enable Solvers`：控制附加的子求解器是否求解。

约束：

- `glueconrel_Weak` 和 `glueconrel_Strong` 节点都是 `Glue Constraint Relationship` 节点。
  - 对象作为一个整体对象移动，直到施加足够的力来破坏胶合。**胶水约束只能通过物体与它们碰撞来打破，从而产生冲击**。
  - `Strength`：指定胶粘的强度。**如果值为 -1，则连接永远不会中断**。
  - `Data Name`：数据名称，用于将数据附加到对象或其他数据上的名称。
- `constraintnetwork1`：根据多边形网络将 RBD 对象对约束在一起。
  - `Geometry Source`：使用 `SOP`（使用 SOP 路径参数指定的 SOP）。
  - `SOP Path`：使用在 SOP 中做好的约束。
- `sopsolver1`：使用该节点在某些强度较大的地方断开连接，但新版和这个版本的参数有些不一样故作罢，**不连接也是可以的**。

## 7. 碰撞制作内部材质

节点链：`unpack1` → `attribwrangle12`（分组）→ `normal2` → `material2` → `Delete`

- `unpack1`：将 `packed` 通道中的数据解包出来。
- `attribwrangle12`：将内部切割的面的不同材质分配到不同的组，从而上不同的内部材质。
  - **`Voronoi Fracture` 节点会自动生成 `inside` 组，包含切割过后内部所有的面**。
- `normal2`：计算一下法线。
- `material2`：将材质分配到新建的内部面的组上。
- `Delete`：区分**静态**（不参与碰撞运动）和**动态**（受 RBD 影响的运动解算），然后渲染。

## 8. geo_upresing（增加内部面细节，可选）

`geo_upresing` 节点内部的 `attribwrangle1`：

```shell
int nearprimnum = 0;
vector outUV;
xyzdist(1, @P, nearprimnum, outUV);
i@origPrimNum = nearprimnum;
```

## 9. Pyro 模拟

### 9.1 pyro_source

- **从刚刚破碎完的模拟那引入（不要解包）**。
- `unpack`：只转移 `v` 属性。
- `Debris Source`：碎片、火焰或粒子源，生成点发射源，以分离破碎的刚体对象。
  - **新版本要想和旧版本一样的效果**：修改 `Post-Process`（后期处理）下拉列表的内容：
    - `Speed Threshold`：如果传入的几何体或点具有速度属性，请使用它，根据速度仅保留几个选定的点。如果您只想从**快速移动的碎片**中发射，这很有用。
    - `Remove Unreleased`：删除尚未超出距离阈值的点。
    - `Remove at Life End`：删除已分离的点及其属性值高于其属性的点。
  - 旧版本不用修改任何参数。
- `popnet`：让粒子产生多一点。
  - `source_first_input`：
    - `Source` 选项卡：发射类型用**全部粒子**，发射来源使用第一个输入端口。
    - `Birth` 选项卡：调节一下粒子寿命，**不要太长**。
    - `Attribute` 选项卡：`Initial Velocity`（初速度）选 `Add to inherited velocity`（添加到继承速度），调节速度大小；`Variance`（方差）：上面设置的速度的方差，该节点将沿着每个轴将 `+/-` 添加到速度参数的这个数字。
- `attribwrangle1`：设置粒子大小和质量。
  - `age` 是一个不断变大的值，`1-@age` 就可以将这个粒子视为慢慢从大变小的一个过程来赋予 `pscale`。
  - `density` 是顺着 `pscale` 的变化来变化。
- `vdbfromparticles1`：将点云和/或点属性转换为 VDB 体积图元。
  - `Voxel Size`：体素大小，就是 VDB 精度。
  - 使用 `Fog VDB`（density）。
  - `Minimum Radius in Voxels`：半径小于此体素数的点将被忽略，**可能会导致锯齿伪影**。
  - `Half-Band Voxels`：半频段体素，点球体外有多少体素要填充生成的 VDB。
  - 再在 `Point Attributes` 参数处生成一个 `v` 属性。
- `volumevop1`：给 `density` 增加一个噪波，让其更不规律一些。
- `vdbfrompolygons1`：将多边形表面和/或表面属性转换为 VDB 体积，**做碰撞体**。

### 9.2 smoke_sim（旧版 pyro）

- `sourcevolume_emitter` 和 `sourcevolume_collision` 是使用 `Source Volume` 节点引用的**爆炸源**和**碰撞体**。
  - `Initialize` 参数可以控制是爆炸源 `Source Smoke` 还是碰撞体 `Collision`。
- `smokeobject`：在 DOP 模拟中创建一个烟雾对象。
  - `Division Size`：体素的大小。
  - `Size`：体素网格的整体规模大小。
  - `Center`：体素网格中心在世界空间中的位置（**加代码是因为在爆炸源那用了 Transform 改变了位置**——中心需手动对齐）。
  - **勾选 `Initial Data` 选项卡里的 `Add Rest Field`**：添加一个名为 rest 的额外字段，可用于存储着色器的休息位置。
- `Pyro Solver`：主解算器。
- `drag Force`：对抵抗其当前运动方向的物体施加力和扭矩（阻力）。
- `gravity1`：重力。

微解算器：

| 微解算器 | 作用 |
|---|---|
| `Gas Resize Fluid Dynamic` | 调整流体大小以匹配模拟流体边界 |
| `Gas Disturb` | 对速度场施加"扰动"力，为烟雾模拟添加精细细节 |
| `Gas Turbulence` | 将湍流应用于指定的速度场 |
| `Gas Shred` | 将粉碎力（Shredding Force）应用于指定的速度场 |

### 9.3 提取 DOP net 里的 Pyro

- `Dop I/O`：（此节点已弃用）从 DOP 模拟导入字段；新版有对应替代节点。
- `Delete` 和 `Volume Ramp`：将 `density` 转为 `Cd`，根据斜坡重新映射体积，增加一个 `Cd` 的属性层。
- `volumevop_coloring`：增加一点烟雾范围。
- `pyrobakevolume1`：帮助开发火焰解算后视口显示和渲染的体积外观。

## 易错点

1. **密度 wrangle 的 `Run Over` 必须用 `Primitives`**——用错作用域密度控制完全失效。
2. **Scatter 用密度撒点**：取消 `Force Total Count`、勾选 `Density Attribute`；**取消勾选 `Relax Iterations` 结果反而更好**。
3. **`Copy` 原地复制多份全部叠在同一位置**——必须接 `point jitter` 抖动，否则 Voronoi 切割点无效。
4. **爆炸源密度公式要 `+ 0.002`**——保证离爆源远处也有一点密度而不是 0，避免完全切不开。
5. **`name` 属性是 `Voronoi Fracture` 自动生成的**——后续 `Attribute Delete` 清理时别漏；区分碎块靠 `connectivity` 的 `class` + `sprintf("piece%d", @class)` 重建 name。
6. **新版 `Connect Adjacent Pieces` 要勾 `Find Boundary Connections` 并把 `Cluster Attribute` 指到 `class`**——否则跨材质边界的约束建不出来，破碎层次感缺失。
7. **`Glue Constraint Relationship` 的 `Strength = -1` 时连接永远不会断**——调试破碎范围时优先检查这里。
8. **`rbdpackedobject1` 的 `Geometry Source` 要改成 `First Context Geometry`**——默认不从 DOP 输入端取几何体。
9. **`pyro_source` 从破碎模拟引入时不要解包**（`unpack` 只为转移 `v` 属性），否则发射源数据丢失。
10. **`Debris Source` 新旧版本默认行为不同**——新版要手动设置 `Post-Process`（`Speed Threshold` 等）才能得到旧版效果。
11. **`smokeobject` 的 `Center` 不会自动跟随**——爆炸源若用 Transform 移过位置，烟雾网格中心要手动加代码对齐。
12. **木头/条状物切割用"压缩→切割→`1/0.01` 还原"的拉伸切割法**——直接撒点切割条状模型效果差。
13. **`Voronoi Fracture` 自动生成 `inside` 组**——上内部材质直接用它，不用自己重建组。
14. **区分静态/动态再渲染**——渲染前用 `Delete` 把不参与解算的静态部分分离，避免无谓开销。
