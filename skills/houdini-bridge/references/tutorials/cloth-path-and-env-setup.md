# 布料沿路径 + 环境效果小配方（学自用户笔记 小案例.md，2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\Houdini基础模块\小案例.md` 布料/树风/雪节。

## 布料沿路径移动（Vellum）

链路：`grid`（布料）-> `group1`（沿布料**从上往下**选一批点，作为吸附在线上、
不受布料解算位移的锚点）∥ `curve` 画路径 -> `resample`（加密）-> `smooth`
（可勾 Recompute Affected Normals）-> `pathdeform`（布料沿曲线走）->
`Vellum Cloth` 解算。

**Vellum Cloth 锚点参数语义**（笔记精华，选型依据）：

- **Pin to Animation** + **Pin Points** = group1 选的锚点组
- **Pin Type** 三选：
  - **Permanent**：mass 置 0，硬约束。**没存原 mass，之后无法解除** --一次性
    固定用它
  - **Stopped**：mass 置 stopped1，同样硬，但 **mass 未改，可后期用 POP 把
    mass 重置 stopped0 解锁**，恢复动态 --要"先固定后释放"用这个
  - **Soft**：点与目标位置之间建**零长度距离约束**（不是直接钉死），用
    Stiffness（受力时偏离目标难易）+ Damping Ratio（回弹的速度与稳定性）控制
- **Match Animation**：勾=求解期间目标随动画更新；不勾=停在初始值
- **Bend->Stiffness**：弯曲约束基于**角度差**，分辨率越高需要越高刚度才有相同
  曲率；**高分辨率+高弯曲刚度 = 收敛需要极多迭代**（性能坑）

## 树被风吹动（最快路线：HDA）

1. `Labs Tree` 做树，勾 **Pack and Instance** 实例化树叶
2. **进 Labs Tree Leaf Generator 内部**，把 `copytopoints3` 的
   **pivot Location 改为 Origin**（不改树风会绕错轴）
3. 接 `Tree Wind` 节点（HDA：`sop_hansl.tree_wind.1.0.hda`），勾 Guide 看
   引导线，各 Wind 选项卡调不同部位摆幅

（另一条自研路线见探讨文章《在Unreal和Houdini中使用PivotPainter2进行树风动画》，
笔记内有链接）

## 表面积雪

一个节点：**Labs Snow Buildup**（生成覆盖表面的雪）。
