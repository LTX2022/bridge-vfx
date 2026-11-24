---
name: houdini-project-recipes
description: 在 Houdini 根据目标效果查 SOP 接线和关键参数，沿节点检查实际分支，并用可编辑小样验证换输入、时序和冷开。适用于破碎、Pyro、河流与白水、群集、羽毛和程序化造型。
---

## 找接法

[实测接线表](references/实测接线.md)收录 91 个自建小样，每项都有控制参数、观测结果、可编辑 HIP 和视口图。按操作顺序查[89 章课程路线](references/课程路线.md)。在本目录使用 Python 3 查关键词，按完整 ID 导出小样到新的文件名，保留原扩展名。

    python3 scripts/example.py 白水
    python3 scripts/example.py river_smoke_advection --export ./river-test.hip

| 要做的效果 | 接线与观测 |
|---|---|
| 河流随烟速度流动 | 用二维烟求解器分别处理源和障碍，采 `vel` 积分画出点轨迹。检查流向后，把速度和 FLIP 边界接在同一坐标空间。[河流速度场](assets/examples/river_smoke_advection.hip.gz) · [FLIP 边界传输](assets/examples/river_external_boundary.hip.gz) |
| 建筑局部激活 | 给碎块写稳定身份与激活组，把几何和约束分别接入 Bullet。按帧比较开口内外碎块的位移。[局部激活](assets/examples/building_local_activation.hip.gz) |
| 白水调参 | 固定液源、机位和采样帧，逐项改寿命、平流、排斥或分辨率，同时看覆盖面积、点数和速度。[七组白水对照](references/白水七组参数对照.md) |
| 带色烟和反向拖尾 | 把颜色分子 `Cd * Alpha` 和权重分别栅格化，在固定坐标归一化。保留碎屑原 `v`，另写反向 `trailv` 驱动尾部。[带色烟源](assets/examples/weighted_smoke_color.hip.gz) · [反向拖尾](assets/examples/reverse_debris_trail.hip.gz) |
| 冲击环与群集烟雾联动 | 改发射启动帧与碰撞输入做两组对照，区分预览接触、出生、延迟支路的首帧。群集与烟采同一速度场时，分别测角色位移和烟密度。[冲击环](assets/examples/shockwave_timeline.hip.gz) · [共享速度场](assets/examples/shared_crowd_smoke_v.hip.gz) |
| 羽毛模板和动态 | 羽轴加两侧轮廓构造模板，用稳定的皮肤图元与 UV 绑定根点。去交叠前先查导向，用三角羽面交点比较结果。低模羽面 Cloth 固定根点，以静止和运动羽面驱动详细羽毛。[单羽模板](assets/examples/feather_template.hip.gz) · [导向](assets/examples/feather_guides.hip.gz) · [羽面随动](assets/examples/feather_cloth.hip.gz) |

## 追分支和换输入

从目标输出向上追输入端口、Object Merge、Switch 和时间表达式。遇到 File Cache 先看读盘开关和所求帧，再追生产节点。比如 `$F+100` 在镜头 F1001 请求源 F1101，源模拟要从自己的起始帧顺算到请求帧。

固定源、帧和求解分辨率，只改一个参数，然后调回。几何查稳定 ID、点位和位移；约束查关系类型、断开数量和首次断开的子步；体积查字段名、有效体素和固定位置的采样值。替换输入后独立冷开，并检查目标输出确实随输入变化。能直接替换 SOP 输入口的几何或标量场可在 Houdini 的 hython 中运行 `scripts/check_sop_inputs.py --help`，动态网络需同时考虑历史状态。

引用结果时注明所用工程、主机版本、实际输出和对应帧段。小水槽测得的覆盖量、代理面交点和源体素读数各自对应表内场景，整镜头的相机、灯光和画面须另行验收。
