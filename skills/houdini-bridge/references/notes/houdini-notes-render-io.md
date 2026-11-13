# Houdini 渲染与导入导出（学自用户笔记 Houdini.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Houdini.md` 的「渲染/导入导出」章节。
原始笔记保持只读；本文件是蒸馏版。截图见原笔记。

## 0. 核心心法

- **模型全部转 USD 再渲染比较稳定**（怕显存不够时，白膜都转 USD 稳定很多）
- XPU 的 AOV 占额外显存
- 按 **Shift 框选渲染**做局部渲染；按住 Shift 点击框外取消该模式
- 别盲目拉满采样：先渲 50% 分辨率小图确认无噪点再放大

## 1. 采样与降噪（Karma）

- `Pixel Oracle`：
  - `uniform`：固定采样（每像素光线数固定；单一场景浪费算力）
  - `variance`：自适应采样（动态分配，默认）
- `Variance Threshold`：噪点容忍度，越小噪点越少
- **Karma 的 Denoiser 只优化 Beauty 通道**——其它 AOV 通道的噪点加采样也消不掉。解法：`Karma Render Settings -> Advanced -> Sampling -> Primary Samples` 的 `Pixel Oracle` 改 `Uniform`（单独通道如 shadow 层就改那个通道自己的 Render Settings）
- 降噪三参数：`min ray sample`、`noise level`（前两提高后者降低，都影响渲染速度）

### CPU / XPU 收敛模式差异

- 采样：每像素产生结果的过程；收敛：多采样汇总比对决定最终颜色
- 次级采样（Secondary Samples）处理：垂直光照（GI 按法线反弹）、透明折射（按折射率）、SSS（内部散射）
- **CPU 模式**：`Convergence Mode`：
  - `Path Traced`：所有渲染设置与 XPU 完全一致（但更适合 XPU）
  - `Automatic`：每根主采样发多根次级采样；多出 `Noise Level`（相当于次级采样的 Variance Threshold）
- **XPU 模式**：只有 `Path Traced`（一根主采样一根次级采样，GPU 并行最大化）；通常成倍提高 `Path Traced Samples`；`Light Quality` 1 就够（除非 Samples 给特别低）

### 渲染优化提速清单

1. 场景预处理：删隐藏几何体/空节点，Merge 合并重复物体；远景 `PolyReduce` 降面；procedural 材质烘焙为贴图（右键材质 → Bake Texture）
2. 渲染器核心参数：采样、折射/反射、最大最小采样、降噪
3. 精简灯光：1-2 盏主光 + HDRI 补光替代多点光；开 `Light Mix` 后期调光避免反复渲
4. 相机：非必要关 MotionBlur；裁剪 `Far Clip Plane` 排除远景
5. 分层渲染（AOVs），后期 Nuke/PS 微调——省 50% 以上返工
6. 体积：`Voxel Size` 0.1~0.3 即可；`Volume Tracer` 替代默认渲染（快 3 倍保质感）
7. 单机后台渲染勾 `Render All Frames with a Single Process`（帧间共享数据时明显快；会把每帧行为之前所有帧数据合并进一个 USD 文件）
8. 预编译渲染内核：渲染菜单 → 预编译 Karma XPU 渲染内核（需数小时，中断可续）

### Karma Render Settings 关键参数

- `Reflection Limit` / `Refraction Limit`：光线反射/折射次数
- `SSS Limit`：材质用到 Subsurface（树叶也算）要提升
- `Shared Color Limit`：场景灯光贡献超 10 就限到 10（自发光 50 只渲到 10）；**有颜色限制时得不到正确颜色**——超量物体的 Color Limit 要设相同值才能匹配
- `Dicing`：模型细分太少提高、太多降低
- 树下渲染设置：`rendersettings`（相机和渲染项）、`renderproduct`（输出图像：相机和 AOV）、`Vars`（变体）

### 运动模糊（Karma/mantra）

- **体积不支持直接渲染运动模糊通道**
- `Transform Time Samples`（变换模糊，属性 `karma:object:xformsamples`）计算便宜但不捕变形；变形模糊增加 `karma:object:geosamples`
- `Velocity Blur`：`Velocity`（只有直来直去）/ `Acceleration`（转圈如风扇，属性也要给 accel）
- 视窗看不到运动模糊：karmarendersettings 加 `motionblur` 节点（相机+物体模糊结合）；只要物体自身模糊就在摄像机上游放 `cache`（读前后帧运动信息）；单独物体用 `rendergeometrysettings`
- **导出运动模糊通道（Motion Vectors）**：`Rendering -> Camera Effects` 勾 `Motion Blur` + `Disable Image Blur`（Velocity blur 必须用 `No Velocity blur` 否则渲出怪异路径）→ `Image Output -> AOVs(Render Vars)` 勾 `Utility -> Motion Vectors`
- 粒子运动模糊：用实例速度模糊 `Instance Velocity Blur: Velocity Blur`
- **加速度运动模糊做法**：
  - 法 1：wrangle 把 `force` 转移到 `accel`；此时 camera 的 `Shutter Open/Close` 拉低拉高效果更明显
  - 法 2：`trail` 节点勾 `Compute Acceleration`（存 `accel`；`Velocity Approximation` 选 `Central Difference`）；此法 camera 不用拉太高
  - Karma：勾 `Motion Blur`，`Velocity Blur` 用 `Acceleration Blur`，取消 `Motion Samples From Stage`，拉高 `Geometry/Transform Time Samples`（子帧拖尾）
  - mantra：geo 节点 `Geometry Velocity Blur` 选 `Acceleration Blur` + 渲染器 `Allow Motion Blur` + `Geo Times Samples` 拉高

### Buckets and Caching

- 桶默认 32x32 像素；几个特别贵的块时降低桶大小分散到更多线程；**但桶太小（如 4）方差估计差，会出现过早终止的黑像素**
- Bucket Order：middle/top/bottom/left/right（mplay 里可点击聚焦区域）
- Cache Memory Ratio：默认 0.25（16G 内存用 4G 统一缓存）；只用于离线渲染不用于 IPR

## 2. Solaris / USD 精要

- Solaris = 基于 USD 的灯光/视觉/布局/渲染系统；Karma = 基于 Hydra 的渲染器
- USD 核心思想：**拆模型**——大模型拆组件分别存文件，再引用组成完整模型（改组件不用整模型重读写）

### Prim / 属性概念速查

- Prim Path 用 `/` 分层；父层级后输入 `/**` = 全选该父层级下所有子层级（层级约束下直接拖父层级不识别）
- Primvar 插值：Constant（整个 Prim 一个值）/ Uniform（每面）/ Vertex（顶点线性插值）/ Face-Varying（每面每顶点，如 UV）
- `Xform`（可变换）、`Scope`（组织结构）——**Scope 不能直接位移，用 Configure Primitive 改类型为 Xform**
- `Visibility`（Off/On/Inherited）vs `Activation`（Off 时视为不存在，含子 prim、属性全忽略）
- `Purpose`：default / render（只最终渲染）/ proxy（交互预览低模）/ guide（编辑参考）
- `Kind`：group / assembly / component / subcomponent
- 可继承：Transforms、Visibility、Purpose、Primvars；不可继承：Kind、Instanceable、Relationships、VariantSets

### Sublayer vs Reference vs Payload vs Instance

| 机制 | 特点 | 适用 |
|---|---|---|
| Sublayer | 层叠加，顶层覆盖底层；**把输入 2 内容直接写进资产主文件** | 组织组合、改底层参数 |
| Reference | 引用为实例，原文件改动影响所有引用处；内容**以子文件形式另存，主文件只写引用目录**；不能直接覆盖式编辑 | 资产重用、大场景 |
| Payload | 可选加载的 Reference；默认不加载（橙色） | 内存大的资源、大场景按需加载 |
| Instance | 共享几何/材质数据，只存变换；不能从原始资产更新属性 | 大量重复（树/人群/建筑） |

- 变体集以 reference 读入显示绿色（合成弧）；**合成弧未展开时只能当总原型基元，最后一个变体覆盖前面**（USD 合成优化特性）；用 sublayer 就没有
- 组合弧优先级排序（本地继承 > 变体集 > 参考 > 负载）——**这就是不能用引用覆盖模型的原因**
- 场景图树里绿色 = Reference、橙色 = Payload；`L` 勾选强制加载 payload 作为参考
- payload 检查：末端放 `Configure Stage` 设 `Load Primitives: Set primitives to load`；不存在又想加载就加 `Loft Payload Info` 节点（**没有该节点 payload 不会加载到场景**）

### USD 文件格式

- `.usdc`（crate 二进制）：小、内存高效，适合几何/带数据文件
- `.usda`（ASCII 文本）：可读可编辑，调试用；基于 python 开发，**可让 AI 生成/修改 usda 代码**
- `.usdz`：压缩包含纹理，实时应用
- 默认存 crate；强制 ASCII：路径后加 `:SDF_FORMAT_ARGS:format=usda`（如 `/BaSiL_Big.usd:SDF_FORMAT_ARGS:format=usda`）

### 常用 LOP 节点

- `SOP Import`：SOP 几何进 LOP（**不能导材质**；分组需设面层级 `path` 字符属性；勾 `Load as reference` 启用 USD 描述层）
- `Scene Import`：把 /obj 场景（含材质、相机、灯光）导入 /stage；fbx/abc 相机导入后**别在 sop 里再改相机**，否则可能进不了 Solaris
- `Sop Create` / `Sop Modify`（内部做 SOP 操作覆盖回 USD）/ `Unpack Usd`
- `Stage Manager`：资产树管理、快速导入 USD、控制层可见性、`Alt+G` 合并到组、`Alt+D` 复制；可直接变换（平替 Transform）
- `Reference`（输入 1=基本场景，输入 2=实例引入）、`Sublayer`（输入 2 可连多个子层，**信息从后向前覆盖**）、`Asset Reference`（= Reference + Xform + SetVariant 合体，快速摆资产设变体）
- `Load Layer for Editing`：加载到内存新匿名层做破坏性编辑（默认不保存）
- `Configure Layer`：设层元数据（Save Path、Default Primitive、Up Axis、Meters per Unit）；**提示没保存路径的报错都用它设 Save Path**
- `Configure Primitive`：改类型/Purpose/可见性等
- `Configure Stage`：配置加载、资产解析
- `Layer Break`：阻断层——保存到磁盘时丢弃之前所有层
- `Prune`：分类隐藏/停用 prim 简化场景；**物体分开用不同渲染器渲染：选中哪个剥离哪个；千万别用 `Prune Unselected`**（会剔除相机灯光等全部）
- `Graft Branches`：把右输入节点树附加到指定路径末尾（右树只需根目录 `/$OS`）
- `Restructure Scene Graph`：重新生成图元路径
- `Inline USD`：输 usda 代码，Alt+Enter 运行
- `Instancer`：实例化/复制到点（输入 1=场景，输入 2=原型；类似 copy to points）
- `Edit Context Options` + `Switch`：选择是否渲染某物体
- `Component Builder` 系列：`Component Geometry`（预制 render/proxy/guide 三 purpose 接口）/ `Component Geometry Variants`（多变体）/ `Component Material` / `Component Output`（命名即模型路径；`Generate Thumbnail` 快速生成预览图）
- `Create LOD` SOP：PolyReduce 自动生成多 LOD 存 USD 变体

### 变体（Variant）工作流

- `Add Variant`（输入 1=结构，输入 2=每个变体输一次；与变体无关内容放其它子层避免同名覆盖）
- `Add Variants to Existing Primitive`：不覆盖原资产，原变体集成为新变体集子集
- `Set Variant`：选择查看哪个变体（Primitives 写 `/` + Component Output 节点名）
- `Explore Variants`：平铺全部变体（只读不能创建修改）；`Layout: Stacked (XY)` + Spacing 也能看
- `@GEOVARIANTINDEX`：**变体索引值（从 0 开始），只在 Component Geometry 节点内有用**；`Variant Name Default` 可写 `` lod_`@input-1` `` 自动编号
- `Material Variation` 节点生成材质变体 primvar（`Type: Point Instances` 才能让点实例化物体有不同材质变体）
- Component Geometry Variants：`Source Mode: Inputs` 时每个 componentgeometry 节点是一个变体（名称=节点名）；`Number` 时一个节点内含多变体（名称=本节点名+数字）

### 实例化资产散步（instancer 全解）

- 核心问题：变体集要先**展平到同一层**（`Configure Layer -> Flatten Input`）才能作为独立原型被 instancer 读取
- `Prototype Primitives` 指定要散步的 USD 集合名；`Prototype Index` 改 `Random` 随机选原型；出问题勾 `Use Entire Stage as Prototype`
- 点上控制变体：给每个粒子 `index` 属性（整型）
  - 大量变体（86 个）：`i@index = int(rand(@ptnum)*86);`
  - 少量变体（4 个）：`Attribute Randomize` 设 `index`（Number of Values = 变体数，Weight 控出现频率）→ `Attribute Cast` 转整数
- 撒点密度：pointvop 里 P 连 `Turbulent Noise`（Turbulence 设 0）→ fit 到 0-1 → ramp 平滑边缘 → Cd；`Attribute Paint` 把有模型位置的 Cd 涂 0；scatter 关 `Relax Iterations` 和 `Max Point Limit`，勾 `Density Attribute` 用 Cd，`Force Total Count` 控制总数
- `Attribute Randomize` 的 pscale 用 `Exponential` 分布更接近现实
- `Scatter and Align`：`Mode: Add Attributes to Existing Point Cloud` 只加属性不建点；Orient 控制方向缩放；`Max Random Cone An...` 往法线两边倾斜
- 路径索引：`/ENV/Trees/bg_tree[*]` 全选实例；`bg_tree[0-10]` 选索引 0~10
- 灯光排除对 instancer 内部不起效（用 prune 拆父级）

### 资产分层与导出

- 资产拆 geo/mtl 两层引用到资产层（重型几何特别有用）；`layer break` 分开模型和材质单独保存
- `USD ROP`：
  - `Layer Metadata` = 根基元名称
  - `Output Processing -> Use Relative Paths`（默认，存 $JOB）；`Save Paths Relative to Output Path` 使 Save Path 相对于输出文件
  - `Copy All Assets to Referencing Layer Directory`：非 USD 资产复制到 usd 同目录（`Output Subdirectory` 写 `tex` = usd 文件夹下建 tex 文件夹）
  - **Output Processing 存储顺序从上到下：先复制文件再存相对位置**才能正确指向新位置
  - `Save Style: Separate Layers (Preserve All Sublayers and References)`：不压扁变体
- 渲染元件保持在根层级（渲染器在根层级查找）
- 材质和模型路径放一起就能正确打包；proxy/render 转换原理 = Purpose 设 Render / Proxy

### 资产库（Layout Asset Gallery / 21 版改名 Asset Catalog）

- 齿轮菜单 `Create New Asset Database File...` 建 `.db` 资产库
- 自动生成的缩略图质量差 → 手动做：ComponentBuilder 内置缩略图相机（Activation=1、spin/pitch/dist=0）+ 灯光 + Karma 渲 128x128、文件名带 `thumbnail` 才能被识别（XPU 渲）→ exr 转 png：

```shell
hoiiotool .\Wild_Grass_thumbnail.exr --ociodisplay "sRGB - Display" "ACES 1.0 - SDR Video" -o .\Wild_Grass_thumbnail.png
```

- 变体入库：`sublayer`（导入多变体 usd）→ `reference` → `set variant` → `Configure Layer`（文件名 `` Wild_Grass_`@ITERATIONVALUE`.usd:SDF_FORMAT_ARGS:format=usda ``）→ `usd_rop`（tmp.usd，Save Style: Separate Layers）
- 批量渲染缩略图：TOPs `File Pattern`（`Split Files into Separate Items` 生成 directory/extension/filename 三属性）→ Solaris `Sublayer` 写 `` `@directory`/`@filename``@extension` `` → `ropfetch`（`Output Paths From: ROP Node Parameters`、`Output Parm Name: outputimage`）→ openimageio 转 png + fileremove 删 exr
- `Asset USD Builder` 插件：Source/Target 目录 + 依次点 SCAN ALL DATA 等按钮全自动

### 多镜头批量作业（Context Options + TOPs）

原理：同一个相机路径 + 多个 `camera edit`（或多个相机 + 不同 rendersettings 切换）。

1. `karmarendersettings` 设初始镜头；下方多个分支（shot），`Configure Layer` 设各镜头起止帧，`switch` 连接
2. `Context Options Editor` 设变量（String Menu 类型，Menu items 写各 shot 值）
   **重点：渲染前 `Export...` 成 json 后删掉 Context Options Editor，否则渲染时会锁死一个参数值一直渲**；需要时再 Import
3. Switch 节点：`Choose Input: By Name`，`Select Input` 写变量名，各输入 `Input Name` 写变量值
4. TOPs：`wedge` 节点建属性匹配全局变量（Attribute Name + Values）；`filterbyexpression` 剔除不需要的镜头（表达式 `strcmp(@属性名,'参数名')==0`，多变量用 AND 加 Extra Expressions）；`ROP Fetch`（ROP Path 指向 USD Render ROP；`Evaluate Using: ROP Node Configuration`）；`localscheduler` 渲图设一次一个项目（导 usd 用默认 1/4 CPU）
5. Solaris 里 `edit context options` 关联 TOP 属性名；输出路径：``$HIP/render/$HIPNAME/`@shot`/`@pass`/$OS.$F4.exr``
6. 渲染前 ROP Fetch 右键 `Dirty and Cook This Node`

### husk 命令行渲染（免 Houdini 实例渲 USD）

环境变量 PATH 加 `C:\Program Files\Side Effects Software\Houdini 20.5.370\bin`：

```shell
husk .\usd_rop1.010.FX.usd --frame 1001 --frame-count 15 --engine xpu --make-output-path --verbose a
# husk 文件路径 --frame 开始帧 --frame-count 帧数 --engine 渲染引擎 --make-output-path 自动创建输出路径 --verbose 输出日志
```

```shell
usdcat .\usd_rop1.010.Geometry.usd            # 打印 usd 文件全部内容
usdcat .\usd_rop1.010.Geometry.usd -o .\usd_rop1.010.Geometry.usda
# 转为 usda 格式（记事本可读）；usdview 打开检查任何 usd（带 Karma 支持）
```

- HuskStandaloneSubmitter：husk 提交 Deadline 渲染农场的工具（GitHub）

### Solaris 性能优化

- `Transform` 节点在路径上游会让大量下游节点带时间依赖：加 `Cache` 节点设 `Always Cache All Frames`，或 Transform 设 `Sample Frame Range`
- 沉重动画模型用 `File Cache` 烘焙时，内部是 usd_rop + SubLayer 封装——重复保存数据非常浪费，**改用 reference 引用回去**（引用所有物体要连三次指定路径 + `Reference Primitive: Reference Specific Primitive`）；更好的做法：只缓存带繁重动画的模型再单独引用
- LOPs 导入与打包 prim 生成是高性能的；导入点只需在点上设 path 属性
- RBD 导 USD 四选项：转换 / 点实例化器 / 变形 geo / 骨架——**大量 prim 会显著拖性能，避免 RBD 写成转换层次**，选变形 geo 或骨架（骨架最省，只存关节 xform，但没法单独选一个网格隐藏）
- python LOP 不产生时间依赖（USD 真正强大之处：一次采样整个动画范围）
- flatten stage 只有三种情况必要：场景确定不改存冷盘 / 转给别人关联文件太多 / 从其它舞台合并带合成弧的 prim。渲染性能优化该做的是「同一进程渲全部帧」或 husk 渲 usd

### 相机（导入导出与烘培）

- abc 相机导入：`Alembic Archive` 节点（顶层点 build）；相机手动建但焦距等要和 abc 一致；FBX 最好也这么处理
- abc 帧起始范围：延后就 `-数值`，所有 Alembic Archive 内的 `Frame` 参数都得调
- PFtrack 跟踪相机：`Scene Import (Cameras)` 节点直接导
- **导出 abc 相机动画：先烘培再导**——空相机内部放 `Constraints Network` + `Object(Constraints)` 节点（放被烘培相机）+ `export` 节点（Display 和 output 旗帜都开）→ 相机的 `Constraints` 参数右侧按钮 `Bake Constraints` 全部烘成关键帧
- 导出：`ROP Alembic Output`（不连输入默认输出 /obj 下所有相机；指定到具体相机 obj 即可）
- 多相机一镜到底拼接：两个 `null` 把第二个相机移到默认相机位置（最靠近相机的 null 填**相反**坐标，上游才是相反旋转）→ 再用一个 null 引用第一个相机运动数据

**获取相机世界坐标（Python Source Editor，选中摄像机运行）**：

```python
import hou
nodes = hou.selectedNodes()
if not nodes:
    print("错误：请先选中一个摄像机节点")
else:
    cam = nodes[0]
    if not isinstance(cam, hou.ObjNode):
        print("错误：选中的不是Object节点")
    else:
        M = cam.worldTransform()
        M_inv = M.inverted()
        pos_inv = M_inv.extractTranslates()
        rot_inv = M_inv.extractRotates()
        print("在父级Null中设置以下数值可使摄像机归零：")
        print("位移 (tx, ty, tz): ({:.6f}, {:.6f}, {:.6f})".format(pos_inv[0], pos_inv[1], pos_inv[2]))
        print("旋转 (rx, ry, rz): ({:.6f}, {:.6f}, {:.6f})".format(rot_inv[0], rot_inv[1], rot_inv[2]))
```

**获取世界坐标（简版）**：

```python
import hou
selected = hou.selectedNodes()
if selected:
    cam = selected[0]
else:
    raise Exception("没有选中任何节点")
if not isinstance(cam, hou.ObjNode):
    raise Exception(f"节点 {cam.path()} 不是 Object 节点，无法获取世界坐标")
world_matrix = cam.worldTransform()
world_pos = world_matrix.extractTranslates()
print(f"摄像机 {cam.path()} 的世界坐标: {world_pos}")
```

### 视锥体剔除 / 相机剔除

- **pointwrangle 版（免插件）**：

```shell
vector c = toNDC(chsop("cam"),@P);
if(c.x>ch("width_1")||c.x<ch("width_2")||c.y>ch("height_1")||c.y<ch("height_2"))
removepoint(0,@ptnum);
if(c.z<-chf("depath")||c.z>-chf("depath_2"))
removepoint(0,@ptnum);
```

- VFX Tricks 工具箱 `Camera Frustum` 节点（连相机，远平面继承）；或 df_CameraCut.hda
- 节点方法：`VDB`（按相机生成视锥体素）+ `VDB Activate` + `Shrink Wrap`（凸包）+ `Remesh to Grid`
- 视图背对相机剔除：视图选项勾「移除背面」（仅着色视图模式有效；开放表面背面会消失）

### Solaris 视锥剔除（Python LOP，帧范围求交/平均两模式）

```python
import hou
import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom

node = hou.pwd()
stage = node.editableStage()

camera_prim_path = Sdf.Path("/cameras/camera")
camera_prim = stage.GetPrimAtPath(camera_prim_path)
prim_paths = [Sdf.Path("/set/toys/instancer")]
time_samples = list(range(1001, 1101))

mode = "average" # "frame" or "average"
data = {}

for time_sample in time_samples:
    time_code = Usd.TimeCode(time_sample)
    camera_type_API = UsdGeom.Camera(camera_prim)
    camera_API = camera_type_API.GetCamera(time_code)
    frustum = camera_API.frustum
    bbox_cache = UsdGeom.BBoxCache(
        time_code,
        ["default", "render", "proxy", "guide"],
        useExtentsHint=False,
        ignoreVisibility=False
    )
    for prim_path in prim_paths:
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsActive():
            continue
        if not prim.IsA(UsdGeom.Boundable):
            continue
        imageable_type_API = UsdGeom.Imageable(prim)
        visibility_attr = imageable_type_API.GetVisibilityAttr()
        if prim.IsA(UsdGeom.PointInstancer):
            pointinstancer_type_API = UsdGeom.PointInstancer(prim)
            protoIndices_attr = pointinstancer_type_API.GetProtoIndicesAttr()
            if not protoIndices_attr.HasValue():
                continue
            protoIndices_attr_len = len(protoIndices_attr.Get(time_sample))
            bboxes = bbox_cache.ComputePointInstanceWorldBounds(
                pointinstancer_type_API, list(range(protoIndices_attr_len))
            )
            invisibleIds_attr_value = np.arange(protoIndices_attr_len)
            for idx, bbox in enumerate(bboxes):
                if frustum.Intersects(bbox):
                    invisibleIds_attr_value[idx] = -1
            invisibleIds_attr_value = invisibleIds_attr_value[invisibleIds_attr_value != -1]
            if len(invisibleIds_attr_value) == protoIndices_attr_len:
                visibility_attr_value = UsdGeom.Tokens.invisible
                invisibleIds_attr_value = []
            else:
                visibility_attr_value = UsdGeom.Tokens.inherited
            if mode != "frame":
                data.setdefault(prim_path, {"visibility": [], "invisibleIds": [], "invisibleIdsCount": []})
                data[prim_path]["visibility"].append(visibility_attr_value == UsdGeom.Tokens.inherited)
                data[prim_path]["invisibleIds"].append(invisibleIds_attr_value)
                data[prim_path]["invisibleIdsCount"].append(protoIndices_attr_len)
                continue
            visibility_attr.Set(UsdGeom.Tokens.inherited, time_code)
            invisibleIds_attr = pointinstancer_type_API.GetInvisibleIdsAttr()
            invisibleIds_attr.Set(invisibleIds_attr_value, time_code)
        else:
            bbox = bbox_cache.ComputeWorldBound(prim)
            intersects = frustum.Intersects(bbox)
            if mode != "frame":
                data.setdefault(prim_path, {"visibility": [], "invisibleIds": []})
                data[prim_path]["visibility"].append(visibility_attr_value == UsdGeom.Tokens.inherited)
                data[prim_path]["invisibleIds"].append(invisibleIds_attr_value)
                continue
            visibility_attr.Set(UsdGeom.Tokens.inherited
                                if intersects else UsdGeom.Tokens.invisible, time_code)

# Apply averaged result（注意：点数变化时不可用，需映射 ids 属性）
if mode == "average" and data:
    for prim_path, visibility_data in data.items():
        prim = stage.GetPrimAtPath(prim_path)
        imageable_type_API = UsdGeom.Imageable(prim)
        visibility_attr = imageable_type_API.GetVisibilityAttr()
        visibility_attr.Block()
        if visibility_data.get("invisibleIds"):
            pointinstancer_type_API = UsdGeom.PointInstancer(prim)
            invisibleIds_average = set(np.arange(max(visibility_data['invisibleIdsCount'])))
            for invisibleIds in visibility_data.get("invisibleIds"):
                invisibleIds_average = invisibleIds_average.intersection(invisibleIds)
            invisibleIds_attr = pointinstancer_type_API.GetInvisibleIdsAttr()
            invisibleIds_attr.Set(np.array(sorted(invisibleIds_average)), time_code)
            continue
        prim = stage.GetPrimAtPath(prim_path)
        imageable_type_API = UsdGeom.Imageable(prim)
        visibility_attr = imageable_type_API.GetVisibilityAttr()
        visibility_attr.Block()
        visibility_attr.Set(UsdGeom.Tokens.inherited if any(visibility_data["visibility"]) else UsdGeom.Tokens.invisible)
```

配套 wrangle（mask < 0.5 收集不可见 id）：

```shell
int @invisibleIds[];
float @mask[];
int idx = 0;
foreach(float m; @mask){
    if (m < .5 ){
        append(@invisibleIds, idx);
    }
    idx += 1;
}
```

### AOVs / 分层渲染

- 合成必备特殊层：**景深 + 运动模糊**（渲时不渲，合成加；但 karma 内 `Camera Effects` 的 `Motion Blur` 仍要勾）
- 层含义：`beauty`（各灯光层叠加，一般不用——没法单独调灯光层）/ `direct diffuse`（主光）/ `indirect diffuse`（辅光）/ `direct specular` / `indirect specular` / `reflection` / `sss`（透光层）
- 每灯分层：Light 节点 `Karma` 选项卡 `LPE Tag` 设不同标签
- 简单层：`Diffuse、Reflections and Refractions、Lights and Emission、Volume` 勾 `Combined...`
- `Render Var` 节点：自定义变量 AOV（着色器输出或 LPE）；`Additional Render Vars` 批量建
- 深度层最大最小值不对：改深度通道的 `precision` 精度模式试试
- aovs 层的 `CPU time` 可看每帧耗时找瓶颈
- 自定义 AOV：`attribute Paint` 画 mask 属性 → `MtlX Geometry Property Value` 引入 → `Karma AOV` 输出
- **渲染深度层必须关闭 karma fog box**
- Karma Cryptomatte：节点连 Karma 即可（Primitives/Materials 勾选分层）；或 `Extra Render Vars` 下拉选 Cryptomatte；自定义：`Material Variation` 设同名参数 `matte` 给每个物体颜色 → Karma Cryptomatte 引用

### Holdout / 阴影层五法（Karma）

| 方法 | 效果 | 做法 |
|---|---|---|
| 1 | 画面只有物体，阴影单独 AOV | 承影模型连 `rendergeometrysettings`，`shading -> Holdout Mode` = **`Background`**（用 Matte 背景阴影也会渲出来）；AOVs 的 `Extra Render Vars` 加自定义层 `holdouts;shadow;CDL` |
| 2 | 同上，用 Background Plate 节点 | `Background Plate`：Primitives 放承影模型、`Holdout AOVs` 出层、`Shadows` 单 AOV 或按 LPE 分、Diffuse/Emission/Glossy Reflection 出不同类型；Karma 节点勾 `Import Render Vars From Second Input` |
| 3 | 只有物体和影子，没地面 | `Karma Shadow Catcher` 节点 + Render Settings 勾 `Add Holdout Shadows To Beauty` |
| 4 | 带地面，阴影单独 AOV（作用不大） | Beauty 里直接勾 `Shadow` |
| 5 | 只有地面和影子，没物体 | `Render Geometry Settings` 的 Primitives 放不渲模型，`Render Visibility` 加 `-primary`（对主光线不可见） |
| 遮罩 | 渲染遮罩 | `Render Geometry Settings` 的 `Holdout Mode` = Matte |

- 只渲 AO：Karma 选 **CPU 模式**，勾 `Simplified Shading`（XPU Engine 参数旁；禁用所有着色照明的全局 AO 预览模式）
- Background Plate：IPR 可见、最终渲染不含；要输出背景：Karma Render Setting 下新建 Render Setting 节点，`karma -> Global -> Image -> Use Background` 设 On

### 缓存/序列导入（Solaris）

- `volume` 节点导入 vdb（density/scatter 字段；序列可缓存或采样帧范围删时间依赖）
- `geometry clip sequence`：加载大量缓存（流体模拟等 bgeo/usd 序列不转成单个 usd）：
  1. 取消 `Get Geometry From Second Input`
  2. `Load Clip File Path` 设文件
  3. 路径后加 `:SDF_FORMAT_ARGS:sampleframe=$F`（bgeo 需时间参考才能用序列全部帧：`....bgeo.sc:SDF_FORMAT_ARGS:sampleframe=$F`）
  4. 勾 `All Clip Files Have Matching Scene Graph Structure`（序列层次结构一致时加速读取——默认每帧都处理）
  5. 取消 `Flatten Clip Files`（没加载 usd 就没组合弧）
  6. 设起始帧并缓存摆脱时间依赖
- **大数据量缓存别用传统格式做 clip**（加载时先读一遍所有帧才能进场景）；geo clip sequence 缺点：改一个参数就缓存一次

### SOP ↔ LOP 互导

- LOP → SOP：`LOP Import`（导打包 USD 图元）+ `USD Unpack`（解包到多边形）。**同时选父和子 Prim 会得重复几何体且导入时间翻倍**；USD Unpack 默认遍历到 GPrims，不必自己选叶子网格
- SOP 导入 SOP 网络中间有缓存几何可能不同步（写 .bgeo.sc 后 LOP 层次结构改了，重新缓存前层次不对）
- File Cache 节点可导出 abc 或 usd 给 Nuke 用

### Maya 资产转 Solaris（有 Arnold 时）

Maya：模型组导出 obj + Arnold 菜单导出 shader。
Houdini `Component Builder` → component geometry 内：

```c
string names[] = split(s@shop_materialpath,"/");
string sg = names[-1];
s@name = sg;
removeprimattrib(0, "path");
s@shop_materialpath = '/mat/' + sg;
```

→ 按材质球命名自动分组 Mesh → /mat 下自动建好所有 shader → 拷贝进 Material Library → 按大纲一键赋材质 → Component Output 输出。

### 自动绑定材质（Attribute Wrangle，按 prim 名）

```shell
//get the prim name
string prim_path_parts[] = split(@primpath, "/");
string prim_name = pop(prim_path_parts);

//set material path
string material_path_string = "/materials/" + prim_name;
string materialpath[];
append(materialpath, material_path_string);

string binding_rel = "material:binding";
string binding_api = "MaterialBindingAPI";

usd_setrelationshiptargets(0, @primpath, binding_rel, materialpath);
usd_applyapi(0, @primpath, binding_api);
```

### 材质路径批量改写（多变体资产）

- `usd_addattrib(0, @primpath, 'inputs:file', 'asset');` —— 在图元上创建 asset 类型属性（`inputs:file` 必须以正确类型存在，否则内部 image 节点优先级更高不生效）
- `Attribute Wrangle` 里 `` `_%s%s.jpg', chs('Res'), @primname `` ：第一个 `%s` 取 for_each 参数、第二个取 `@primname`（对应 Material Library 内 MtlX Image 节点名）
- 引用所有需改路径的材质：`Primitives` 参数写 `%shadertype:ND_image_*`
- `For Each`：`Iteration Method: For Each String in Parameter`（Iterate Over Strings 是循环的字符串列表）；勾 `Set Last Modified Primitives from Iteration Input`

### 导入导出（传统格式）

| 操作 | 节点 / 要点 |
|---|---|
| FBX 带动画模型 | `FBX Character Import`（更简洁） |
| FBX 带蒙皮材质 | `FBX Skin Import` |
| abc 导入 | `Alembic Archive`；Load as: Delayed Load Primitives（轻量、视口快但光线追踪不准）/ Load Houdini Geometry |
| abc 导出 | `ROP Alembic Output`；**别的软件认 `shop_materialpath` 不认 `name`**；maya 无顶点——UV 转到点上再输出；导破碎一定导点驱动（Dop import field 不能直接导碎块） |
| 导出多物体独立命名 | `name` 节点给不同名 + `rop_alembic` 勾 `Build Hierarchy from Attribute`（ROP FBX Output 同） |
| 导出 vdb | `convertvdb` + `filecache`，类型改 vdb 后缀 |
| 组导入导出 | Houdini primitive 层级 group ↔ c4d 面选集互相识别 |
| 导出点/粒子 | `rop_alembic`；属性只留 P（必要）Cd（颜色）v（运动模糊） |
| 导出带动画 FBX | 菜单 `File -> Export -> Filmbox FBX` 或 `ROP FBX Character Output`（先确保模型有 name） |
| 导出 OBJ | `File` 节点连模型设 Geometry File 点 Reload Geometry（或 ROP Geometry Output） |
| LOD 导出 FBX | `Labs LOD Hierarchy` |
| 图片处理 | `img -> image Network - old`（监看用 Composite View） |
| 导入方向不对 | Object 环境该节点上游放 Null 控旋转/缩放/位移 |
| 嵌套导入变形 | Object Merge 的 Transform 选 `Into this Object`（Into Specified Object = 直接取最内部无嵌套影响） |
| 导出整个场景（含相机灯光） | 保存为 USD 并作为子层加载回来 |

## 易错点

1. **AOV 噪点消不掉**：Denoiser 只管 Beauty；Pixel Oracle 改 Uniform
2. **Reference 不能覆盖模型**：组合弧优先级（本地 > 变体 > 引用 > 负载）
3. **payload 不加载**：缺 `Loft Payload Info` 节点；检查用 Configure Stage
4. **变体实例化失败**：变体集没展平（Configure Layer 的 Flatten Input）
5. **Prune Unselected 是坑**：反选会剔除相机灯光等所有内容——用选中式 prune
6. **Context Options 渲染锁死**：渲染前 Export json 再删掉编辑器
7. **USD ROP 输出顺序**：先 Copy Assets 再 Save Relative，反了路径指向错
8. **桶设太小（4px）出现黑像素**：方差估计过早终止
9. **母/子 Prim 同时选导入**：几何重复 + 时间翻倍
10. **bgeo 序列走 clip**：大数据先读一遍全部帧才能进场景
11. **深度层错误**：忘关 karma fog box；或深度通道 precision 没调
12. **holdout 用 Matte 时背景阴影也被渲出**：改用 Background 模式
13. **SOP 中间缓存与 LOP 不同步**：改层次后要重新缓存
14. **fbx/abc 相机导入 Solaris 后别在 sop 改相机**，可能导入不了
