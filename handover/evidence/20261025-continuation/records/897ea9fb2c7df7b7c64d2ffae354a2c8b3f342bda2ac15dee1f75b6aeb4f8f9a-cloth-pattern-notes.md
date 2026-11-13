# 衣服制版与服装仿真（学自用户笔记 衣服制版.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\衣服制版.md`。
原始笔记保持只读；本文件是蒸馏版——服装打版底层逻辑、CLO/Marvelous Designer 操作、
GarmentCode/ContourCraft 参数化管线，以及全部实测仿真参数。

> 与 `vellum-rbd-notes.md` 的呼应：服装打版是 Vellum Cloth 的**上游**——MD/CLO 生成的
> 板片与缝合关系，对应 Vellum 里的缝合约束（stitch/weld）和布料物理属性（拉伸/弯曲/厚度/
> 摩擦）。本文件 §4.3 的 `sim_props.yaml` 参数与 Vellum Solver 的 Stretch/Bend Stiffness、
> Thickness、Friction 一一对应，做布料解算时可互相参照调参。

---

## 1. 打版底层逻辑（四大铁律）

用平面面料包裹立体人体，核心手段：**省道、分隔线、放量、弧度、移位、变形**。
不存在几百种版型，只有**一套基础原型**不断微调。

1. **万物皆由原型改**：改松量 = 宽松/紧身；改肩线 = 正肩/塌肩；改省道分割 = 立体贴合度；改轮廓弧度 = 版型风格
2. **省道（sǎng dào）= 平面变立体唯一核心**：收掉多余面料贴合胸/背/臀凸起。
   铁律：**省量守恒、位置可移、形态可变**。破缝/收褶/抽碎褶/隐形省/刀背缝本质都是省道转移
3. **线条版型逻辑**：打板是画标准、干净、顺滑的结构线。烂版型（不服帖/起吊/鼓包）只有三个原因：结构不平衡、横竖线不正、弧度有拐点尖角。**结构线正、弧度顺 = 成功大半**
4. **松量底层逻辑**：所有版型差异都是松量差异

### 松量速查表

| 版型 | 松量策略 |
|---|---|
| 弹力贴身 | 几乎无松量 |
| 合身日常 | 少量松量 |
| 微宽松 | 均匀加量，不压身不贴身 |
| 大版慵懒 | 整体放大弱化曲线；硬料适当放量、软垂料减量、厚料放宽、薄料收紧 |

**快速学会路径**：吃透上衣/裤子两大原型 → 掌握 4 种改款手法（增减松量、省道转移、调肩袖笼、微调轮廓弧度）→ 面料 + 实物验证闭环（打板→裁布→试样→纠错）。

口诀：**抓原型、懂省道、控松量、顺线条**。

---

## 2. 软件与文件格式

| 格式 | 内容 |
|---|---|
| `.avt` | 3D 虚拟模特身体（MD Avatar，可图库导入） |
| `.zpac` | 单件衣服完整可编辑数据（无模特无动画），CLO 3D / MD 原生格式 |
| `.zprj` | 整个项目（模特 + 衣服 + 场景 + 动画） |

`Garment` = 在 AVT 模特身上设计/模拟/渲染的布料裁片。

## 3. 板片识图（衬衫案例）

- 每块带箭头（**纱向线**）的版 = 独立板片；纱向线平行于缝合合并线
- 后片侧：育克（ヨーク，近脖子，可上翘/下弯）→ 后片 → 袖子；中间棱形 = 省道
- 前片侧：前片 + 前袖 + 长条**袖克夫**（カフス）+ 顶部领子（衿）
- **波浪线** = 抽褶位置（从一个顶点到刀口）
- **剪口**：对位标记；**连接符号** = 前袖后袖在此线合并为一整片
- 板片形状/剪口/连接符号截图见原笔记

---

## 4. CLO / Marvelous Designer 实操

### 4.1 根据板片图做 3D 衣服（CLO 流程）

1. 矩形工具拖出矩形 → 导入板片图作为贴图底图
2. **定尺寸**：对衣服尺寸要有概念——衬衫长约 50–60cm，从后颈往下量（案例实测 1102.2mm）；`G` 快速开启内部多边形绘制
3. 按纱向线分版勾勒 → 按 `I` 左键选板片（**不要把省道一起导出**，`Shift` 反选）→ 右键【勾勒为板片】→ 删除底图线
4. 按 `Z` 编辑版线：选中省道切断，删除切出的小块布料
5. 半透明预览把板片对位到底图 → **剪口工具**标记对位点
6. 连接符号处：选中要合并的线，右键合并（前袖+后袖 → 整袖）
7. 做对称板片；3D 显示异常时点【重置安排 2D 位置】复原
8. **`Shift + F`**：把布料摆放到 3D 人体对应位置
9. 缝合顺序：**先缝省道 → 再缝肩线**（按 `Shift` 可连 3 片不同位置的线）
10. 内部线间距一般 **1.5cm**；全选板片 `Ctrl+S` 硬化 → `空格` 模拟测试 → `Ctrl+H` 解除硬化；**粒子间距调低** = 网格更密更精细；删掉省道 = 宽松款式

### 4.2 MD 基础

- 打开自有数据库、自动调整板片适配穿着模型（截图见原笔记）

---

## 5. AI 参数化打版管线

### 5.1 提示词四要素

1. 给出娃体关键数据（如 ob24、胸围、腰围）
2. 详尽廓形和细节（收腰、翻领、泡泡袖……）
3. 要求给出前后片示意图
4. 指令模板：`帮我打版一个 **** 的娃衣原型纸样 要 pdf 格式的代码`

### 5.2 工具分工

- [GarmentCode](https://github.com/maria-korosteleva/GarmentCode)：参数化版片引擎，**JSON → 2D 版片**（"平面面料 + 结构调整"的全部信息载体）
- [ContourCraft](https://dolorousrtur.github.io/contourcraft/)：专为版片缝合优化，神经多服装模拟中解析交叉点，**把衣服"落"到身体上做碰撞仿真**

### 5.3 GarmentCodeRC 能力边界

**支持**：上衣（Shirt/FittedShirt）；袖（无袖/短袖/长袖/袖口/荷叶边/肩部变化）；领口（圆/V/方/梯形/贝塞尔/翻领/立领/帽子）；下装（裤/直筒裙/铅笔裙/圆裙/多片裙/分层裙/godet 插片裙）；上衣+下装+腰带组合（连衣裙/套装）

**不适合**：非参数库特殊结构；多层复杂娃娃裙/蕾丝/密集褶皱/蝴蝶结/披肩斗篷；工业级省道放缝缝份推档；单张照片反推背面/内侧/缝线结构

> 定位：可穿着形体验证 + 自动生成基础板片，**不等于**版师的工厂纸样。

**两级配置要分清**：

- 第一层（易）：在已支持结构里配参数范围/默认值/款式预设（改 design.yaml）
- 第二层（难）：新增服装结构（斗篷、洛丽塔多层裙）要写新 GarmentCode 程序：定义板片、边、曲线、缝合关系、3D 初始摆放、人体接口

### 5.4 GarmentCode 输入（实测字段）

人体尺寸（body yaml）：

```yaml
height / bust / waist / hips / shoulder_w / back_width
neck_w / arm_length / wrist / waist_line / bust_line / armscye_depth
```

设计参数（design.yaml）——**大多是相对人体的比例，不是厘米**（`shirt.length` 乘 `waist_line`，`shirt.width` 乘 `bust`，袖长乘 `arm_length`）：

```yaml
meta: { upper: Shirt, bottom: null, wb: null }
shirt:  { width: 1.05, length: 1.21, flare: 0.997, openfront: false }
sleeve: { sleeveless: false, length: 0.231, armhole_shape: ArmholeSquare,
          sleeve_angle: 18, end_width: 0.949, connecting_width: 0.197,
          connect_ruffle: 1.13 }
collar: { f_collar: CircleNeckHalf, b_collar: CircleNeckHalf,
          width: 0.209, fc_depth: 0.3, bc_depth: 0.00305 }
```

### 5.5 ContourCraft 输入与仿真参数（实测值，最高价值）

四件套输入：`specification.json`（GarmentCode 版片）+ body 文件 + `sim_props.yaml` + `system.json`

body 文件：
- YAML 尺寸（非 SMPL）：`mean_all.yaml`（标准平均）/ `mean_female.yaml` / `mean_male.yaml`
- OBJ 网格（接 SMPL）：`f_smpl_average_A40.obj` / `f_smpl_template.obj` / `f_smpl_template_TA_pose.obj`

`sim_props.yaml` 核心参数（与 Vellum 概念对照，呼应 `vellum-rbd-notes.md`）：

```yaml
sim:
  config:
    max_sim_steps: 2400           # 仿真总步数
    resolution_scale: 1.0         # 网格分辨率 ≈ Vellum particle spacing
    material:
      garment_tri_ke: 10000.0     # 三角弹性(拉伸) ≈ Vellum Stretch Stiffness
      garment_edge_ke: 1.0        # 边弹性     ≈ Vellum Bend Stiffness
      spring_ke: 50000.0          # 缝合弹簧强度(关键! 把版片拉合) ≈ Vellum Stitch 约束
      fabric_density: 1.0         # 布料密度
      fabric_thickness: 0.1       # 布料厚度   ≈ Vellum Thickness
      fabric_friction: 0.5        # 布料摩擦   ≈ Vellum Friction
    options:
      enable_body_collision_filters: true   # 与身体碰撞
      enable_edge_edge_collisions: true     # 自碰撞
      attachment_stiffness: [1000, 1000, 1000, 1000]  # 与身体贴合约束 ≈ Vellum Attach to Geometry
```

### 5.6 AI 做娃衣全流程

```
娃娃参考图
  ↓ 视觉模型识别（件数/类别/上衣下装/袖/领/开襟/长度/宽松度）
  ↓ 参数约束映射（转成 design.yaml，禁止输出 GarmentCode 不支持的结构）
  ↓ GarmentCode 生成（specification.json + SVG + PNG）
  ↓ ContourCraft / CLO / MD 验证（OBJ 模型 + 可导入板片格式）
```

---

## 易错点

1. **省道连同板片一起导出**：CLO 勾勒板片时必须 `Shift` 反选去掉省道区域，且导出后用 `Z` 切断省道删掉小块布料——带着省道导出版型全错。
2. **缝合顺序颠倒**：必须先缝省道再缝肩线侧缝；顺序反了布料拉扯变形、模拟炸开。
3. **未硬化直接模拟**：全选板片 `Ctrl+S` 硬化后再按空格模拟，否则初态穿插、缝合弹簧（`spring_ke`）拉扯出撕裂感；调完记得 `Ctrl+H` 解除硬化再改版。
4. **参数单位误解**：GarmentCode 设计参数是**相对人体比例**不是厘米，把 `length: 1.21` 当 1.21cm 会得到废纸；人体尺寸 yaml 才是绝对单位。
5. **让 AI 输出不支持的结构**：视觉模型识别后必须做参数约束映射，禁止输出参数库外结构（斗篷/多层裙/蝴蝶结），否则 GarmentCode 直接失败。
6. **仿真参数错配**：`spring_ke`（50000）比 `garment_tri_ke`（10000）大一个量级是刻意的——缝合必须比布料本身硬；布料撕裂先查 spring_ke，布料像橡胶先查 tri_ke。Vellum 里同理：Stitch 约束强度要高于 Stretch。
7. **粒子间距过大**：CLO 粒子间距不调低，板片网格太疏，领口袖口等细节全糊；对应 Houdini 侧是 Vellum particle spacing 太大。
8. **纸样 ≠ 成衣**：GarmentCode 输出只到"可穿着形体验证"，缺工业级放缝/缝份/推档——拿它直接当工厂纸样会出生产事故。
