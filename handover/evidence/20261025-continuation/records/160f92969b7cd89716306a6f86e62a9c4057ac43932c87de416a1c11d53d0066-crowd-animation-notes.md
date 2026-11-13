# 动画/群集/绑定/APEX 实战笔记（学自用户笔记 动作动画群集绑定骨骼等模块.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\动作动画群集绑定骨骼等模块.md`（约 930 行）。
原始笔记保持只读；本文件是蒸馏版——聚焦笔记里的具体参数、坑、案例步骤，作为
`references/workflows/crowds.md`/`anim.md`/`character.md` 通用指南的实战补充。
笔记里指向图片的链接保留原样（截图见原笔记）。

## 1. 通用技巧速查

| 场景 | 方法 |
|---|---|
| 需要中间帧 / 变速 | `retime` 可以生成中间帧（截图见原笔记） |
| 用动画模型驱动物体 | `Point Deform`（见下文三输入端接法） |
| 长链机械臂 / 机械传动绑定终极 rig | `Full Body IK`（截图见原笔记） |
| 任意骨骼动画混合控制（H21 新版） | `APEX Motion Mixer NLE` 面板 |
| 让点沿路径移动（K 帧） | `Anim Along Curve`；也可直接用 `Path Deform` 节点做位移 |
| 原地动画想让它向前位移 | `FBX Animation Import` 导入 → `transform` 位移 → `ROP FBX Animation Output` 导出 |

笔记内参考链接：鸟的动画+Solaris Feather Export HDA（andreaskj.com）、Crowd 官方教程
"Zombies for Everyone"（sidefx.com/tutorials）、Fuzzy Defuzz 逻辑（sidefx.com/docs/houdini/crowds/fuzzy.html）。

## 2. Point Deform：用动画模型驱动静态模型

`Point Deform` 三个输入端的接法（笔记原话，容易接反）：

- **输入 1**：需要被驱动运动的静态模型，姿态任意，但要和输入 2 的模型姿态一致
- **输入 2**：源动画模型，但需要是静态的（用 `timeshift` 冻结），姿态与输入 1 一致
- **输入 3**：直接连有动画的模型（动画数据输入）

截图见原笔记：`![QQ20250107-153045.jpg](./图片/Houdini/QQ20250107-153045.jpg)`

## 3. 动画数据拆解：让模型定在原地运动（T-pose 转动画）

用途：方便制作布料时让布料贴合人身上的运动。步骤（笔记完整保留）：

1. 先冻结一帧（`timeshift`），将模型封装，通过 `add` 节点打包为点，
   再用 `pointdeform` 节点把模型运动转到点上
2. `pointvop1_get_transfor_matrix`（Point VOP）：将点的 `P` 通过 `Make Transform`
   构建为通用 4×4 转换矩阵，属性输出到 `nP`，再通过 `attribtransfer`
   把该属性转移到模型上
3. `move_geo_to_origin`（Point VOP）：计算 `nP` 的**逆矩阵**，然后乘 `P`（1×3），
   得到单位矩阵（全为 1）的 `P` —— 冻结模型所在位置并保留运动
4. 想还原动画（`move_geo_back`）：把 `P`（1×3）乘 `nP` 即可复原

## 4. 快速多动作合并切换（不用群集模块）

目的：持续奔跑 → 拐弯时切到别的动画 → 切回继续跑。

- `Anim Along Curve` 让点跟随路径移动（K 帧）；不用它的 Attribute Wrangle 方法，
  直接用 `Path Deform` 做位移也可以
- 使用 `Agent` 节点导入 2 个动画资产：
  - `Input` 用 `FBX` 类型；`FBX File` 参数填模型路径；
    `Current Clip` 填要运行的动画剪辑名称
- `unpack` 打开 → `convert` 把类型改为 polygon
- 两个 agent 都是循环播放，但 agent2 只需要在 `1001~1023` 播一次
  （点会在这附近停顿）→ 用 `timeshift` 限制这个范围内动画播放、范围外冻结
- `transform2`：在点停顿时把动画切换到 agent2，通过 `blendshapes1` 切换，
  然后马上切换回去 —— 实现Animation 过渡切换

## 5. 群集 Crowd 核心概念

- 人群模拟本质是**粒子模拟 + 代理集合体（Agent primitive）**：控制点，rig 和
  geometry 都附加在点上
- 传统 POP 求解器方式难以控制单个代理的行为（改一个影响全部）
- **`MotionPath` 工具**：把群体运动视为曲线并像曲线一样编辑，可单独编辑每条曲线
- **locomotion**：基于主关节（一般是 `hips`）计算移动距离

## 6. Agent / Agent Clip 参数详解

### Agent（创建代理图元）

两种创建方式：

1. **工具架**：选中模型点 `Agent`，弹窗填 `Clip Name` 和 `Agent Name`
2. **节点直接引用**，参数：
   - `Agent Name`：代理基本名称
   - `Character Rig`：引用 obj 层级下的模型
   - `Clip Name`：烘焙剪辑名称，动画取自当前场景
   - `Frame Range`：**最好都设为 `Scene`**，通过 `Agent Clip` 节点裁剪范围
   - `Input` 改为 `FBX` 即从 FBX 文件读取动画
   - `Include Unused Capture Regions`：仅为兼容旧场景开启，可能带来解包/合并
     多个蒙皮形状剩余几何体的问题

### Agent Clip（向代理添加动画剪辑）

`Input` 三种来源：

| Input 类型 | 用法 |
|---|---|
| `Character Rig` | 从场景中角色子网/资源创建剪辑（填包含角色绑定的对象子网路径） |
| `MotionClip` | 从第二输入口提供；剪辑名称、采样率、长度由几何体的 `clipinfo` 属性决定（名称可被 Name 参数覆盖） |
| `FBX` | 指向 FBX 文件磁盘路径；**模型比例和代理不同时可能看不见模型 → 取消勾选 `Convert Units`** |

关键参数：

- `Start/End/Inc`：第二个参数（End）设为该片段的结束帧，才视为完整片段；
  默认 `$FEND`（持续到场景最后一帧）
- `Convert to In-Place Animation`：转为就地动画。**报错
  `Missing or bad Locomotion Node '(null)' for In-Place Animation` → 没设
  `Locomotion Node`**（FBX 流程报 `Joint '' does not exist.` 同理）
- `Locomotion Node`：层级中控制角色运动变换的节点（有空间平移通道的关节），
  人物一般设 `hips` / `Hip`，从臀部控制运动
- `Set Current Clip`：检查/预览动画时勾选，设置当前播放的剪辑
- `Clip Time`：沿时间轴播放动画；不勾选 = 无动画只有静态姿势
- `Apply Clip Locomotion`：打开后按动画运动实际移动；不勾 = 只见原地动画

### 测试用角色

`Mocap Biped 3`：带动捕的男性角色、10 种纹理，**用来做测试**。动作循环分 8 类：
姿势、步行和转弯、跑步、步数、体育场、斜坡、受伤、僵尸。

### 模型没有骨骼绑定时

通过 `rop_fbx` 导出给 **Mixamo（笔记写作 Maxiom）动画库**绑定后再倒回来，
传递绑定属性（`boneCapture`）。

## 7. Crowd Source（群集来源）

- 输入 1：用于填充人群，由代理设置网络创建
- 输入 2：点云或曲面；不连则用参数 `Number of Agents`（数量）、
  `Area Size`（范围）在边界内散布

`Randomize` 选项卡：

| 参数 | 作用 |
|---|---|
| `Randomize Agent Primitive` | 随机化代理图元——人群里放不同角色（多角色必开） |
| `Randomize Initial State` | 一开始就使用不同动画（类似 Crowd MotionPath 的 Clip Groups） |
| `Randomize Clip Time` | 每个代理剪辑时间随机化，减少重复动画几率 |
| `Randomize Heading` | 初始朝向随机 |
| `Randomize Scale` | 大小随机 |
| `Randomize Current Layer` | 随机分配放置的模型层（配合 Agent Layer 留空 Set Current Layers） |

## 8. Crowd MotionPath 及相关节点

### Crowd MotionPath 本体

- 人群没在 `Agent Clip` 勾选 `Apply Clip Locomotion` 时，可在本节点
  `Clip Names` 填动画片段名，即可产生动画和运动路径
- `Clip Groups`：想做多种类型运动时加组，组内添加动画片段名；
  `Weight` 是播放权重，权重越高播放几率越大
- `Initial Clip Time`：为组内所有代理设定初始剪辑时间（相对剪辑开始的偏移）
- `Random Clip Offset`：起始时就偏移一定动作做随机
- `clip speed`：动画片段播放速度乘数，可控制能走多远；参数末尾改为
  `Variance` 设置速度随机变化范围（百分比，让动画有快有慢）
- 技巧：点击 `clip speed` 骰子随机化，会生成一个 `Attribute Adjust Float` 节点

### 相关节点速查表

| 节点 | 作用 |
|---|---|
| `Crowd MotionPath Edit` | 单独编辑单条路径 |
| `Crowd MotionPath Avoid` | 放碰撞体，曲线互相避让（输入 3 是迭代次数，越多避让越好；通常最后做） |
| `Crowd MotionPath Follow` | 画一条曲线让群集跟随方向运动 |
| `Crowd MotionPath Trigger` | 按多种条件选中路径不同位置做不同操作 |
| `Crowd MotionPath Transition` | 人群运动路径上的动画过渡到另一动画 |
| `Crowd MotionPath Evaluate` | 将群集运动打包，用于渲染 |
| `Crowd MotionPath Retime` | 调整运动路径时间速度（裁剪/移动/重缩放），会重调代理速度 |
| `Crowd MotionPath Arcing Layer` | 根据转弯率在一组动画片段间混合，左右转弯过渡更自然 |
| `Crowd MotionPath Layer` | 在运动路径上叠加额外动画剪辑（边走边做其他动作） |
| `Test Simulation: Crowd Transition` | 简单人群模拟，测试片段间过渡 |
| `Agent Terrain Adaptation` | 地形适应，角色按地形高度变化改变走向（贴地不悬空） |
| `Agent Look At` | 头部/眼关节朝向目标跟踪（需先 Agent Prep） |
| `Agent Transform Group` | 创建代理变换组（如只选上半身骨骼做局部动画） |
| `Agent Relationship` | 代理间建立父子关系（骑马等） |

在 DOP 中：`pop Attract` 添加目标对象连到 `Crowd Solver`，可把群集往目标移动。

### Crowd MotionPath Trigger 详解

- `Trigger Name`：触发器名称（生成点组名称），给后续节点（如 transition）引用
- `Type`：
  - `Object Distance`：从第三输入检测离模型多近则被选中
  - `Time`：在某帧开始选中动画
- `Comparison` 选 `Outside` 可选到模型选区**之外**的路径
- `Combine Triggers`：`Union (Or)` / `Intersect (And)` / `Exclusive Or` / `Subtraction`

### Crowd MotionPath Transition 详解

- `Trigger Group`：选使用哪个触发器
- `Clip Name`：过渡后使用哪个动画片段
- `Use Clip Transition Graph`：延迟过渡到当前片段的适当点，并提供平滑融合信息
- `Clip Speed`：片段速度

### Crowd MotionPath Layer 详解

- `Trigger Group`：选取触发器；`Transform Group`：选代理变换组名
- `Clip Name`：叠加的动画名（如走路上半身变鼓掌）
- `Random Delay`：触发器为真与分层剪辑开始之间的最大延迟（秒），避免多个代理同时触发
- 勾选 `Randomize Clips` 才能随机化引入的多个动画片段
- 坑：混合后出现"边走边跳"，用 `Agent Transform Group` 限定只做上半身姿态修复

### Crowd MotionPath Arcing Layer 详解

- `Strength`：沿路径平滑转弯率数值的量，越高转弯率越远离原值
- `Reference Direction`：代理原始面向方向（计算转向率用）
- `Reference Up`：代理原始向上向量
- `Turn Rate Attribute`：查看该属性可看路径信息——左转曲线变红，右转变紫
- `Clips`：
  - `Base Clip Name`：基础片段（弧形剪辑叠加到使用该剪辑的任意点上）
  - `Arcing Clips`：`Clip Name`（弧形剪辑名）/ `Turn Direction`（转弯方向）/
    `Radius`（根据转弯率确定混合权重）

### Agent Look At 前置

使用前须用 `Agent Prep` 节点准备（调整脊柱从下背部到头部关节、可旋转眼关节）。
`Agent Prep` 在躯干（Torso）处设置 `Hips` 臀部、`Lower Back` 下背部（Spine）、
`Head` 头部，并为代理添加各种通用点属性。

## 9. 装配角色和动画（3 种方式）

导入的动画越多场景越丰富，人群生成多样性越多。

### 方式一：全部使用 Agent（模型用 FBX）

- `Agent` 引入角色 + `Agent Clip` 引入动画
- 使用 `Character Rig` 进行装配

### 方式二：使用 FBX 装配角色并缓存

- `Convert`：转为 polygon，避免网格中有预打包几何体
- `Agent from Rig`：从绑定创建**无皮肤**代理（骨骼转换为群体代理）；
  设定代理名称（`Agent Name`）使代理被下游节点识别
- `Agent Layer`：将网格重新绑定到骨骼（输入 1 = 代理，输入 2 = 形状几何）；
  `Layer Name` 必须与 `Agent from Rig` 的 `Agent Name` **一致**；
  `Shape Name Attribute` 开启时从第二输入几何体按字符串属性识别形状加入形状库
- `Agent Definition Cache`：导出代理缓存——不用每次从 FBX 加载，**大幅减少加载时间**

### 方式三：使用 FBX 导入节点导入角色和动画

- **装配角色**：`FBX Character Import`（直接导入模型；模型比例不对看不见时取消
  `Convert Units`）→ `Agent from Rig` → `Agent Layer`
- **分配动画**：
  - `FBX Animation Import`：导入 FBX 动画并给片段命名
  - `Motion Clip`：将骨骼动画转换为 MotionClip，打包为原语列表；
    `Sample Rate` 调帧速率，`Frame Range` 调帧范围
  - `MotionClip Extract Locomotion`：提取运动，输出带新运动表现的 MotionClip
  - `Agent Clip`：`Input` 用 `MotionClip` 引入；`Name` 为片段命名；
    其余参数见第 6 节
  - `Crowd MotionPath`：单独看模型向前运动

**多动画**：其余同上，装配多个动画片段；`Agent Prep` 提前添加通用点属性。

## 10. 额外模型层分配到角色（帽子等）

### 旧版方法

装配角色 → 引入模型，设置 `Transform Name`（放置部位名）、
`SOP Path`（模型路径）、`Shape Name`（命名）。

### 新版方法（可分配多个物体在不同位置）

- `File` 引入模型 → `Merge Packed`（`Name` 参数为不同模型命名）→ `Agent Layer`：
  - `Set Current Layers`：默认动作层（留空则用 `Agent Clip` 上设置的默认层）
  - `Layer Name`：当前层名称
  - `Use Existing Shapes` 下：`Shape Name` = Merge Packed 里设置的 `Name`；
    `Transform Name` = 放置部位名称
- `Crowd Source`：Agent Layer 不设默认层（留空），勾选
  `Randomize` → `Randomize Current Layer` 随机分配放置的模型

### Crowd Assign Layers（只能分配不同物体在同个位置）

- `Agent Layer`：`Transform Name` 设放置部位；`Layer Name Attribute`
  （第二输入几何体上的字符串属性）指定形状被添加到的图层
- `Crowd Assign Layers`：`Percent to Select` 分配百分比（多少比例的群集有）；
  `Layer Choices` 引入要放置的模型

## 11. MotionPath 实战案例

### 案例流程骨架（群集注视模型）

`crowd source`（自设点云生成位置数量+动画随机）→ `crowd motionpath`（分配多种动画、
速度/模拟时间/初始动画随机）→ `crowd motionpath follow`（路径跟随，
`Distance Variance Smoothing` 增加平滑度和距离变化）→ `Crowd MotionPath Trigger`
（触发选择人群需要改变的部分）→ `crowd motionpath transition`（过渡动画）→
`Crowd MotionPath Avoid`（避让，通常最后做）→ `Crowd MotionPath Edit` / `Evaluate`
→ `Agent Look At`。

### 鸟群案例

- 用**点云精确控制鸟群位置和数量**（不用 crowd source 自己生成）
- `crowd source`：将鸟放到点云点位置，可设鸟大小、动画随机和大小随机
- `Crowd MotionPath`：分配多种动画、速度、模拟时间、初始动画随机
- `Crowd MotionPath Follow`：跟随绘制的曲线路径
- `Crowd MotionPath Avoid`：互相避开向前（预判避让，避免未来碰撞）
- `Crowd MotionPath Evaluate`：渲染由运动路径描述的动画

### 只做身体部分运动转换（走上半身变鼓掌）

- `Crowd Source` → `Crowd MotionPath`（分配多种动画）
- `Crowd MotionPath Trigger`：曲线在触发器范围内被选中
- `Agent Transform Group`：`Name` 命名变换组；`Root Transforms` 选骨骼部分
  （如只选上半部分）
- `Crowd MotionPath Layer`：`Trigger Group` 选触发器；
  `Transform Group` 选命名的变换组；`Clip Name` 选动画名——只有该部分受影响改变
- `Agent Terrain Adaptation`：让代理贴地运动

### 转弯侧倾 + 多角色合并（骑马等）

**侧倾动画制作**：修改原本动画的 rig 稍微弯曲侧倾，做出左倾/右倾两个动画片段。

**装配**：装配好 2 个角色（`Attribute Create` 控制 `pscale` 大小）。

- `Agent Relationship`（代理父子关系）：
  - 输入 1 = 父代理，输入 2 = 子代理
  - `Parent Joint` / `Child Joint`：子集关节连接到父级哪个关节，整个子集角色跟随移动
  - `Translate` / `Rotate`：控制子集相对位置的旋转位移
  - `Constraint Type`：限制位置、旋转，或两者兼有
- `crowd motionpath`：骰子随机化 `clip_speed` 属性控制群体速度
- `Crowd MotionPath Trigger`：`Comparison` 选 `Outside` 选模型选区之外的路径
- `Agent Transform Group`：选取角色上半部分打组
- `crowd motionpath layer`：叠加额外动画剪辑（`Random Delay`、`Randomize Clips`）
- `Crowd MotionPath Avoid`：角色和模型之间添加避让
- `crowd motion path Arcing layer`：转弯时切换动画使转向更真实（参数见第 8 节）

## 12. 群集 + 布料解算（三大块：人物装配 / 群集解算 / 布料解算）

### 人物装配（vellum 部分不一样）

- `Attribute Wrangle`：通过 `Group` 选取需要解算的布料，赋予 `forVellum` 属性值
- `Group`：选取作为固定点（不动）的部分布料
- `Agent Layer`：形状名称属性由 `fbx_material_name` 组成

### MotionPath 群集解算（可做来回不同走向的群集）

- `Crowd Source`：用 `Randomize Agent Primitive` 随机放置多个角色到点云
- `attribwrangle`：随机赋予 1 或 2 的值到 `targetcurveid` 属性（50% 群体走第一条曲线、50% 走第二条）
- `crowdmotionpath`：生成人物朝一个方向运动
- `Curve` + `Resample`：绘制曲线并增加分辨率（细分）；`Reverse` 反转曲线顶点顺序
- `attribwrangle`：用 `curveid` 属性区分两条不同曲线
- `Crowd MotionPath Follow`：勾选 `Match by Attribute`，按属性匹配每个代理遵循的曲线
- `crowdmotionpathavoid`：设置避让半径，减少穿模（穿模会影响解算）

### 布料解算

- `Agent Vellum Unpack`：从代理原语提取几何体用于 Vellum 仿真
  - 输出端 1：用于布料解算的几何体；输出端 3：碰撞体几何
  - `Shapes to Simulate`：需要模拟的形状
  - `Transfer Attributes`：需要保留的属性
  - `Vellum Start Frame`：布料解算开始时间（此时代型保持 T 字姿态）
  - `Crowd Start Frame`：群集解算开始时间
- `timeshift` + `blendshapes`：其实可以不用设置——默认 agentvellumunpack 已设好
  T 字姿态到群集运动姿态的过渡（冻结时间停在解算开始帧，blend 从 0 过渡到 1）
- `polyfill`：填补破洞模型
- `subdivide`：布料几何体分辨率较低，模拟前增加细分级别
- `vellumcloth`（`Vellum Configure Cloth`）：Stretch 拉伸的 stiffness 刚度设高些
  （控制约束强度，将粒子拉回初始静止状态）
- `vellumattach`（`Vellum Attach to Geometry`）：`Group` 放入 `pin` 组，约束住布料
- `vellumsolver`：开始解算（默认值即可，最好给个地面做碰撞）
- `Vellum Post-Process`：对求解结果做常见后处理（渲染打包解算好的布料）
- `attribwrangle`：给布料一个路径

## 13. 群集渲染方法

### 渲染检查单个角色和材质

- `Scene Import Materials`：导入材质（路径后面都写 `*` 可导入同路径下多种角色的多个材质）
- `SOP Crowd Import`：导入角色
- 识别角色和材质路径并绑定（Attribute Wrangle 原始代码，完整保留）：

```c
string name = usd_name(0, @primpath);
string agentpath = usd_parentpath(0, usd_parentpath(0, @primpath));
string agentname = usd_name(0, agentpath);
//printf(agentname);
string mats = "/obj/vellum_on_crowd/MAT/matnet1/" + name;
// string mats = "/obj/agentTemplate/" + agentname + "/MAT/" + agentname + "/" + name;
//printf(mats);
if(!usd_isprim(0, mats)){
    return;
}else{
    usd_applyapi(0, @primpath, "UsdShadeMaterialBindingAPI");
    string targets[] = array(mats);
    usd_setrelationshiptargets(0, @primpath, "material:binding",targets);
}
```

### 程序化优化（大群集渲染）

流程：`Scene Import`（导入材质）→ `Sop Crowd Import`（导入布料解算前、群集
模拟好后的模型）→ `prune`（通过 `*forVellum` 属性剔除布料解算前的布料模型）→
`Sop Import`（导入布料解算后的布料模型）→ `USD ROP`（导出群集缓存）→
`Sublayer`（导入缓存 usd）→ `Camera` → `Houdini Procedural: Crowd`。

- `USD ROP`：因为有预拉帧（时间线外预模拟的帧，如布料解算），Houdini 可能未正确
  初始化模拟并保留旧数据——**勾选 `Initialize Simulation OPs`**
- `Houdini Procedural: Crowd`：渲染大量集群困难时的优化节点
  - `LOD Camera` 使用场景中的相机
  - `Visualize Instances` 可视化实例：白色 = 默认输入几何体；蓝色 = 实例几何体；
    绿色 = 原型几何体。尽量减少白色代理（提高 `LOD Threshold` 阈值），
    但阈值过高 + 相机太近会出现奇怪动画（按电脑性能/渲染时间尽可能设低）
  - 满意后关闭 `Visualize Instances`
- `Preview Houdini Procedurals`：视口中预览程序化即时几何体（渲染时会被优化）

## 14. DOP 模块做群集（旧方法，不建议学）

### 布料处理

- `vellumcloth`：左边连群集，右边连模型（碰撞体）；Stretch 的 stiffness 设高
- `vellumattach`：`Group` 选约束点，`Group Type` 用 `Points`
- `vellumpack`：将 Vellum 几何体和约束压缩到一个几何体中

### 群集 + 布料

- `agent` 引入角色 → `agentclip` 导入动画 → `agentlayer`（旧版）：`SOP Path` 引入布料，
  `Layer Name` 命名 `vellum_layer`，后面 `agentedit` 中引入，`Shape Name` 命名 `cloth_shape`
  → `crowdsource` 设群集源。dopnet 内部：
  - `Crowd State (rest)`：`Clip Name` 引入静态姿势
  - `Crowd State (move)`：`Clip Name` 引入多种运动姿势
  - `Crowd Object`：引入群集模型
  - `Crowd Trigger`：使用触发器
  - `Crowd Transition`：姿态过渡
  - `Crowd Solver`：解算
  - `popwrangle`：让动画时间随机（不同步使用相同运动），原始代码：

    ```c
    if(len(f[]@cliptimes)==2){
       f[]@cliptimes[1]=rand(@id)+@Time;
     }
    ```

  - `Multiple Solver`：每个时间步内多个求解器同时求解一个仿真对象
- `agentedit`：使其使用布料层 → `Agent Vellum Unpack`（解包出布料层）→
  `Vellum Solver` 直接解算

## 15. KindFX 骨骼绑定案例：花开

### 花瓣部分

- `Resample`：重采样；参数 `Curve U Attribute` 设为 `curveu`
  （创建 point 属性存储重新采样的点）
- `Sweep`：捏叶片形状
  - `Surface Shape` 设为 `Ribbon` 就不会报错
  - 进入 `UVs and Attributes` 勾选 `Compute UVs` 计算 UV；关掉
    `Length-Weighted UVs`（长度加权 UV：把超过 0~1 的部分拉长，此案例不需要）
  - 回到 `Surface` 选项卡，拉长一点 `Width`，勾选 `Apply Scale Along Curve`
    就可以开始捏叶片形态
- `Distance along Geometry`：测量沿几何体边/曲面最短路径与每个起点的距离；
  用 `center_mask` 属性，从 `edges`（给边缘一个 `Group`）开始测量
  （红色最外边是 1，中间紫色是 0）
- `Attribute Wrangle`：先用 `amount` 变量存储位移长度，用 ramp 通过
  `f@center_mask` 属性范围控制位移范围，最后在 `@P.x` 上减去位移长度：

  ```python
  float amount = chf("amount");
  amount *= chramp("edge_mask",f@center_mask);
  @P.x -= amount;
  ```

### 花瓣骨骼部分

- `Orientation along Curve`：计算沿曲线方向（参考系）的 3×3 变换矩阵属性
  - 勾选 `3x3 transform` 生成 `transform` 属性（识别关节方向的属性，对应沿曲线、
    缩放和剪切的方向）
  - 需要额外勾选 `Apply Roll or Twist` 添加额外旋转，确保所有关节按特定方式定位
- `Group Range`：按范围创建点和基本体组
- `Rig Doctor`：初始化骨骼
  - 输入：多边形线（拓扑已在上游修改的骨架几何体）
  - 输出：骨架（拓扑 "frozen" 的输入骨架副本）
  - 提供在网络中放置"断点(breakpoints)"的便捷方法；常量副本基于帧或手动存储，
    属性从输入传输到此副本（**name**）
  - `Initialize Transforms`：启用后，如果缺少点则在点上创建属性并初始化为
    `identity.3@transform`

## 16. APEX（H20+ 新动画图系统）

houdini 新系统，做绑定：

- **快速绑定**：将骨骼从窗口边拖入放置
- **做骨骼绑定 / 物理动画**（笔记步骤，快捷键完整保留）：
  1. 选择 Selection Sets 里的 `All Control -> Ball -> Control`，然后 K 动画
  2. K 完后在视图中按 `C`，选择 `Dynamic Motion`；按下 `H`，"Center of Mass"
     （选中 Control），生成动画曲线
  3. 时间线移到动画开始帧按 `H`，移到一段动画最后一帧再按 `H`——自动修复这段 K 帧动画
  4. 按下 `G` 打开 Dynamic Motion 面板的 Dynamic Motion 选项卡，用 `Advanced Mode`
     编辑动画图层名称，然后同意
  5. 之后可编辑更物理学的动画：选择 control 即可编辑 H 选定的那部分位置

## 易错点

- **Agent Clip 勾 `Convert to In-Place Animation` 报错**
  `Missing or bad Locomotion Node '(null)'`（FBX 流程报 `Joint '' does not exist.`）
  → 忘了设 `Locomotion Node`（人物一般 `hips`）
- **FBX 导入后模型看不见** → 模型比例和代理不同，取消勾选 `Convert Units`
- **Agent Layer 的 `Layer Name` 必须与 `Agent from Rig` 的 `Agent Name` 一致**，
  否则下游不识别
- **多动画循环同步（动作整齐划一）** → 用 `Randomize Clip Time` /
  `Random Clip Offset` / popwrangle 随机化 `cliptimes`，减少重复动画
- **想预览动画却只有静态姿势** → `Agent Clip` 的 `Clip Time` 没勾；
  想向前移动却原地动 → `Apply Clip Locomotion` 没勾
- **`Crowd MotionPath Layer` 混合出现"边走边跳"** → 用 `Agent Transform Group`
  限定只有上半身姿态做叠加动画
- **群集+布料导 USD 有预拉帧、导出旧数据** → `USD ROP` 勾
  `Initialize Simulation OPs`
- **群集穿模影响布料解算** → 加 `Crowd MotionPath Avoid` 设避让半径；
  通常先做人群路径运动，最后做避让
- **`LOD Threshold` 过高 + 相机近 → 奇怪动画**：阈值按性能尽可能设低，
  用 `Visualize Instances` 检查白色代理数量
- **多角色随机放置** → `Crowd Source` 必须开 `Randomize Agent Primitive`，
  否则分配不了多个角色
- **`Agent Definition Cache` 不缓存** → 每次都从 FBX 加载代理，加载时间大幅增加
