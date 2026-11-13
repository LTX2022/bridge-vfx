# 风洞 Pyro 完整配方（学自用户笔记 小案例.md，2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\小案例.md` 风洞案例节。
气流流过物体（车/猪头等）的完整工作流：发射源 + 碰撞体 + **引导线速度场** +
二次粒子。含大量实测参数和坑。

## 总心法（笔记原话）

- 想气流稳定：**发射源要大一些** + 速度场引导烟雾走向
- 模拟精度不够：**跑二次粒子模拟给它假分辨率**
- 勾 **Disturbance** 产生更好看的涡流

## 1. 发射源

- 球体摆好位置 -> `Pyro Source`（Mode=**Surface Scatter**）产出
  density/temperature 点属性
- `Volume Rasterize Attributes` 采样到体积：
  - Attributes 指定 `density temperature`（或加 `v`）
  - **Voxel Size = Particle Separation × Particle Scale ÷ 4**（口诀）
  - **Coverage Attribute 清掉**不需要；勾 `Normalize by Clamped Coverage`
    改善粒子覆盖区过渡

## 2. 碰撞体

- `trail` 算模型速度场 -> `VDB from Polygons`：
  - Distance VDB，体积名 **`collision`**
  - 点速度 `v`（trail 算的 point.v）转成 vdb 速度场 `v`

## 3. 引导线速度场（本配方灵魂）

1. `line`①：从发射体到碰撞体再往后一点；`line`②决定条数和场宽 ->
   `copytopoints`（②的点换成①）
2. `resample` 加细分
3. 投射到模型上：**在物体下方垫一个 grid** 再 `ray`（Method=**Minimum
   Distance**）——不垫的话线会投进物体内部
4. `smooth` 平滑（Strength 控制程度；可选 Recompute Affected Normals）
5. `clip` **只保留流过物体之后的线段**——保证烟雾靠近前沿直线吹、
   不会一开始就被力场吸走
6. `polyframe` 生成速度场：Style=**Tow Edges**，**Tangent Name=v**（方向反了
   就 transform 转 180°）。法线/切线/副切线=TBN 空间，必须两两垂直
7. `Volume Rasterize Attributes` 转成体积速度场

## 4. Pyro Solver 配置（逐 tab）

- **Setup**：Voxel Size 定精度
- **Collision**：Collision Type=**SDF + Volume Velocity**；Collision SDF=
  `collision`；Velocity VDB=`v`；Y Ground Plane=**Closed Below**（下方是禁区）
- **Sourcing**：只初始化 density/temperature；**烟雾断断续续就调大 density 的
  Source Scale**；有引导线速度场时新增 Source Volume：`v` -> Target Field
  `vel`（矢量场），强度不够调大 Source Scale
- **Fields**：只用 Density 的 **Dissipation**（调小=消散慢）
- **Shape**：Wind 定流向
- **Output**：只导 `density`+`vel` 两个 VDB，勾 Convert to VDB

后处理：`clean` 只保留 name 属性提性能；`blast` 分别隔离 density（渲染）和
vel（给粒子）。

## 5. 二次粒子（质感）

`popnet` 内：
- `POP Source`：Geometry Source=**Use First Context Geometry**（第一输入端的球），
  Const. Birth Rate 控量
- `POP Advect by Volumes`：SOP 路径指向 blast 出的 vel 场；
  Advection Type=**Update Velocity**；**Velocity Blend 拉满**
- `POP Wind`：速度场未成形时先给点风把粒子往模型方向吹
- 碰撞：`Static Object`（下接 static Solver）：SOP Path、勾 **Use Object
  Transform**（SOP 里有动画/缩放时必须勾）、Volume 碰撞（Mode=Volume Sample、
  Division Method 控精度、Proxy Volume 指体积路径）；物体无运动则不勾
  Create Active Object
- 删慢点：`Group Expression` 选速度慢的组 + `blast`
- `Attribute Randomize` 设粒子大小

## 旧版 pyro（Smoke Object 路线）要点

- 碰撞用 `collision source`（左右两输出：几何+VDB）：静态时关 Blend Between
  Frames、Velocity Approximation=none；**Voxel Size 必须与 dopnet 里 Static
  Object 的 Division Size 一致**
- dopnet：`Smoke Object(pyro)` + `Gas Resize Fluid Dynamic` + `Volume Source`×2
  （源/速度场）+ `Static Object`
- 导出用 `DOP Import` / `DOP Import Fields`

## DOP 坑（笔记原文，通用）

- DOP 类 RBD 对象有**两个变换**：几何体子数据里的 + 位置数据定义的。RBD
  解算器操作位置数据，**不支持缩放**——要缩放必须走几何体变换
- 干扰节点（烟雾弹案例）：见笔记烟雾弹节与 B 站教程
  《Houdini 通过多模块配合 实现烟雾弹喷射的效果》
