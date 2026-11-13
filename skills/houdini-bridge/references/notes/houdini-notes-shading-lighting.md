# Houdini 材质与灯光（学自用户笔记 Houdini.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Houdini.md` 的「材质/灯光」章节。
原始笔记保持只读；本文件是蒸馏版。截图见原笔记。

## 0. PBR 贴图速查

Houdini 中**标准灰是 0.18**。

| 贴图 | 作用 | 常见后缀识别串 |
|---|---|---|
| Diffuse / Albedo / Base Color | 基础色（宏观上三者等同） | 'diffuse', 'albedo', 'basecolor' |
| Metalness | 金属度（灰白图） | 'metalness', 'metallic', 'metal', 'm' |
| Roughness | 粗糙度 | 'roughness', 'rough', 'r' |
| Specular | 高光 | 'specular', 'spec', 's' |
| Glossiness | 光泽度（暗=粗糙亮=光滑，连 Sheen） | 'glossiness', 'gloss', 'g' |
| AO | 环境光遮蔽 | 'ambient occlusion', 'ao', 'occlusion' |
| Cavity | 混入 Diffuse 增加细节（与 ao 混合后加基本色输出到漫反射） | 'cavity' |
| Normal | 法线（只改表面光照结果） | 'normal', 'nrm' |
| Bump / Height | 凹凸/高度 | 'bump', 'heightmap' |
| Emission | 自发光 | 'emission', 'emit', 'emissive' |
| Opacity | 透明 | 'transparency', 'opacity', 'mask', 'alpha' |
| SSS | 次表面 | 'scattering', 'subsurface' |
| Translucency | 半透明（贴图要手动调值，以视觉为准） | 'translucency', 'thickness' |
| Fuzz | 绒毛（连 Sheen Roughness） | — |
| Clear Coat | 清漆 | 'clearcoat' |

- PBR 两派：`Metal/Roughness`（Base Color + Roughness + Metallic）与 `Specular/Glossiness`（Diffuse + Glossiness + Specular）；共用 AO/Normal/Height
- 没有 BaseColor 时：用 `Albedo + AO` 代替
- sss 贴图用 `Translucency`，不调值是错的，以视觉为准

## 1. Karma / MaterialX 材质

### 核心原则（实测经验）

- **透明材质（水/玻璃）用 `transmission`，不要用 `opacity`**——opacity 只是把 shader 无效化（变淡）
- 非金属不要动 `metallic`：**要么 0 要么 1**，调一半会一半金属一半其它的诡异效果
- 最常用可调参数是 `roughness`
- 水用 XPU 渲；**白水用 CPU 渲**（mtlx 材质渲染白水不行，用 vex 材质，两个分开渲）
- `OpenPBR Surface` 材质效果比 MtlX Standard Surface **更好**（多次实测）
- `Room Map` 节点可将简单纹理转 3D 空间效果；`Hex Tile shader` 可隐藏纹理平铺边界（免做复杂 UV）
- karma 渲矢量置换贴图要换空间

### MtlX Standard Surface 参数地图

| 参数块 | 用途 |
|---|---|
| Base | 漫反射基础颜色 |
| Specular | 金属度与镜面反射 |
| Coat | 顶部反光透明涂层（车漆/油层） |
| Transmission | 透射（玻璃/水） |
| Sheen | 光泽层（超细纤维/天鹅绒/缎子） |
| Subsurface | 次表面散射（皮肤/蜡） |
| Emission | 自发光 |
| Thin Film | 薄膜（抗反射涂层/肥皂泡/多色调车漆） |
| Geometry | 不透明度、法线等 |

- Subsurface 设 1 损失大量反照率；提高半透明度后把颜色加回反照率
- **薄壁半透明**：连 `subsurface_color`，加 `Subsurface` 值，勾 `Thin Walled`（双面无限薄壳；适用窗户/树叶/纸张）。启用后 Limited Transmission 和 Subsurface 生效；Thin Walled 禁用折射；只有透射颜色/粗糙度影响它；次表面只受 subsurface color 影响

### 贴图连接（MtlX Image → Standard Surface）

- `diffuse` → `base color`（signature: color）
- `normal` → `MtlX Normal Map` 的 `in` → `normal`（signature: Vector 3）
- `specular` → `specular`（signature: Float）
- `emission` → `emission_color`（signature: color）
- `displacement` → `MtlX Displacement` → 直连输出节点（signature: Float）

法线贴图方向：Houdini/Maya 默认 OpenGL；**3ds Max 是 DirectX（会把贴图反转）**。

### 常用材质节点

- `mtlx Standard Surface` / `Karma Material Builder` / `USD MaterialX Builder` / `Quick Surface Material`（免建库快速起表面材质）
- `MtlX Image`：普通贴图；`MtlX Tiled Image`：多平铺功能可直接改 UV 尺寸（替代 Transform UV）
- `MtlX Surface Unlit`：无光照表面着色器（自发光粒子/查看噪波图很有用）
- `USD Prim Var Reader`：读几何体 primvar（纹理坐标/法线/颜色）——**SOP 的 `Cd` 在 Stage 里叫 `displayColor`，`pscale` 叫 `@widths`**
- `MtlX Geometry Property Value`：读几何属性引入 Stage（常用于自定义变量）
- `MtlX Position`：参考世界单位尺寸（必须 vector3）
- `MtlX PBR Texture Set`：PBR 纹理 UV/三平面投影一键接 PBR 着色器
- `MtlX Texcoord`：关联 2D/3D 纹理坐标
- `MtlX Range`：调节参数强度
- `MtlX Remap`：值域重映射（贴图不工作在负值区；反转透明度也用它）
- 选中任一材质网络节点按 `X`：生成 `visualize` 节点查看该节点输出效果
- `Karma Cryptomatte` 节点：设置 Cryptomatte AOV

### Solaris 材质绑定节点

- `Material Library`：材质库容器（`Material Path Prefix` 命名库）；勾 `Assign to Geometry` + 指定 `Geometry Path` 可直接绑定模型；内部也可建 mantra 材质
- `Material Linker` + `Edit Material`（填 Material Path 后 Load 进去改）
- `Assign Material`：`Strength` 默认 `weaker`（只赋无材质基本体），`stronger` 强行赋予无视原材质
- `Unassign Material`：移除已分配材质（可按次序选）
- 开源材质库 AMD GPU Open：Catalog 面板里选材质保存路径即可载入；拖入 `Rules` 面板（上栏=要应用的模型，下栏=排除的模型）

### 分离模型部位

- 用 `name` 属性（`name` 节点写入）在 Solaris 分离一个物体的不同部分做材质；`path` 属性提前写好路径；最后的 `name` 覆盖原路径参数
- SOP Import 默认靠 `Import Path Prefix` 指定路径

### 实用配方

**噪波做泥土地**：`MtlX Position`（世界单位）→ `MtlX Multiply`（缩放）→ `MtlX Fractal3D`（细节）→ `MtlX Remap`（重映射到正值）→ `Karma Ramp Constant`（分位置上色）

**噪波做水面**：
- x 向拉伸（数值越小噪波越大）、y 受时间影响产生位移 → `MtlX Height to Normal` 转法线
- 节点链：`MtlX Position` → `MtlX Multiply`（x 缩放）→ `MtlX Time`（秒）→ `MtlX Divide`（降偏移速度）→ `MtlX Combine3`（只连 in2/y 轴）→ `MtlX Fractal3D` → `MtlX Remap` → `MtlX Height to Normal` → `MtlX Normalmap`
- Standard Surface：去 Base 色；Specular=1、Roughness=0、**IOR 水面折射率 1.33**；Transmission=1 可调色（深度影响水下颜色）

**噪波做树干纹理**：`MtlX Texcoord` → Multiply → 两个不同的 `MtlX Fractal3D` → `MtlX Remap` → `MtlX Height to Normal`（Scale 太高纹理会诡异地突出）→ `MtlX Normal Map` → `Karma Ramp`（不同位置颜色）

**草（Karma Hair 工作流）**：
- 视锥体剔除不参与渲染的撒点（`object_merge` 引入地面 + `group` 选组 + `blast` 删视距外 + `clip` 删河道）
- `attribute vop` 做噪波输出给 density → `scatter`；`Scatter and Align` 加随机缩放/方向属性；`attribwrangle` 加 `@id`
- 草体：`line` → `resample` → `bend`；`set_pscale`（Attribute VOP）调粗细（pscale global = multiply 节点 input2）
- 材质：`USD Prim Var Reader` 读 `id` → `MtlX Random Float` → `Karma Ramp Const`（不同 id 不同颜色）→ `Karma Hair`
- `Material Variation` 节点生成 `hue`/`gamma` primvar 属性（`value = fit01(rand(index),-0.1,0.1);`），配 `Karma AOV` 输出自定义层

**LED 显示屏摩尔纹**：
- 准备 RGB 图（子像素排列）；`MtlX Absval` 控制像素尺寸、`MtlX Grid`（Thickness 0.05）分格并用 `Karma Ramp Const`/`MtlX Remap` 反转颜色、`MtlX Tiled Image`（Filtertype: closest/linear/cubic 控制黑白过渡）放 RGB 图
- 播放视频：`MtlX Tiled Image` File 写序列、`Uoffset` 微调；`MtlX Separate Color 4` 分 rgba → `MtlX Multiply`（视频通道 × 屏幕通道）→ `MtlX Add` 合 rgb → Standard Surface 的 `base_color` + `emission_color`（Emission 调高）
- **关键**：Material Library 节点勾 `Allow Shader Parameter Animation` 才有时间依赖，视频序列才播放

**菲涅尔效应（mantra 也可做）**：
- SOP 里：自定义向量=法线（省空间转换）→ 导入摄影机（必须是正确模式否则坐标错）→ pack 取中心 → 点坐标减摄影机坐标得 `dir_cam` 视线
- 材质里：导入两属性归一化后点乘（`A·B = cos(夹角)`），法线与视线同向=1（中心亮），边缘≈90°≈0（黑边）→ **1 减去结果**得类菲涅尔 → `pow` 加黑白对比（点乘已归一化在 0~1 间，pow 把灰变黑）
- 可做描边效果

**玻璃幕墙（高楼玻璃）**：基础着色器 + 反射加有趣变形 + 细微污渍（随机元素）营造真实感

**UV 传递/继承**：
- 方法 1：`remesh` 减面时勾 `Harden UV Seams` 保 UV
- 方法 2：`Labs UV Transfer` 传 UV

**贴花（Decal）**：
- 首选：`MtlX overlay` 混合材质（`MtlX Image` 放 basecolor/透明/粗糙度 + `MtlX Place2D` 调位置大小 + `MtlX PBR Texture Set` 放背景材质）
- 次选：`Labs Decal Projector`（Project 模式，Base Color 选贴图，自动生成贴合模型；给它 `name` 属性当模型处理，贴图连 Base Color 和 opacity）
- 模型贴花散布：Decal Projector 的 Place 模式（输入1=目标模型，输入2=撒点模型（`decal_index` 属性一一对应 + 随机 pscale），输入3=贴图模型（Connectivity 给每个模型单独 `decal_index`））
- 也可用 `ray` 节点投射（仅限单片高细分面模型）

### 混合运算符（Blend Operator，F=前景 B=背景通道）

| 节点 | 结果 |
|---|---|
| MtlX Plus | B+F |
| MtlX Minus | B-F |
| MtlX Difference | abs(B-F) |
| MtlX Burn | 1-(1-B)/F |
| MtlX Dodge | B/(1-F) |
| MtlX Screen | 1-(1-F)(1-B) |
| MtlX Overlay | F<0.5 时 2FB，否则 1-(1-F)(1-B) |

图案类节点：`MtlX Checkerboard`、`MtlX Crosshatch`、`MtlX Grid`、`MtlX Line`、`MtlX Tiled Circles/Cloverleafs/Hexagons`、`Karma Hex-Tiled Triplanar` / `Karma Hex-Tiled Texture`

### mantra 材质（旧）

- `Classic Shader`（全参数经典着色器）、`Principled Shader Core`（艺术家友好，参数 0~1 对应合理真实值）
- Cryptomatte：`Property` 用 `Material Name`（按材质分）或 `Object Name`（按物体名分）；自定义 ID：geometry 节点加 User Properties（String 类型写物体名），mantra Cryptomatte 面板 Property 选该名字；渲染视图里可能看不到分层，导入 Nuke 就能看到

## 2. 灯光（Solaris / Karma）

### 灯光好看五技巧（用户总结）

1. 灯光内部用图像纹理创造有趣的色彩和高光
2. 用假焦散
3. 用灯光遮光板（gobo，噪波图案板等）
4. 用丁达尔（上帝光）
5. 用光线衰减节点获得不同颜色的渐变衰减

### 常用灯光节点

**Dome Light**：
- 可加 HDRI；要渲染出 HDRi 本身勾 `Render Light Geometry`（取消渲染 HDRI 也是它）

**Point Light**：
- 默认无限小、光很硬——`Type` 设 `Sphere（球形光）`变柔和；但大小影响强度，勾 `Base Properties -> Normalize Power` 后大小只影响影子柔化不影响强度
- 聚光灯：`Shaping` 里勾 `spotlight`（**Type 最好设 `Rectangle`**，否则有奇怪形态）
- `Karma` 选项卡 `Contributions` 可设灯光只影响哪些 AOV（写 `* ^volume` = 不影响体积层）
- 顶部菜单放置模式：`Specular`（摆到反射方向）/ `Diffuse`（摆在法线处）/ `Shadow`（点物体 + Shift 点要产生影子的位置）

**Karma Physical Sky**：
- = Karma Sky Dome + Sun Light 装备；`Sky Mode` 改 `Atmospheric` 得体积散射（出现 Atmosphere 选项卡）
- `sun` 下 `Angular Size` 控制太阳大小：**越小影子越锐利，越大越软**（设 0 得特别直的光线）

**Light Mixer**：交互编辑多光源；`Sliders` 左=强度右=曝光，上方按钮可精确数值、独立显示、禁用此灯

**Light Linker**：按灯光做包含/排除（灯光排除对 `instancer` 内部**不起效**——用 `prune` 拆成两个场景给不同父级再排除）

**Karma Fog Box（体积雾）**：
- 体积雾要贯穿整个场景来容纳光线
- **渲染深度层时必须关闭 karma fog box 才能得到正确的值**
- 丁达尔：灯光 + Karma Fog Box，设 `Scattering Phase` 再减轻 `Shadow Density`

### 自发光（Geometry Light）

**21 新版**：一个 `Geometry Light` 节点连模型即可：
- `Primitives`：模型路径
- `Material Sync Mode`：`Material Glow Tints Light`（材质发光与灯光色混合）/ `Independent`（模型呈现自己发光、照亮四周用灯光色）/ `No Material Response`（忽略材质只用灯光色）

**20.5 以前旧版**：
- `Render Geometry Settings` → `Light` → `Treat As Light Source` = Yes（模型当光源，渲染快很多）
- Karma Render Setting 勾 `Split per LPE Tag` + `Geo Light Primitives` 写自发光模型路径
- **场景中必须有一个灯才能激活物体自发光**（哪怕这个灯不发光）
- 粒子自发光：`MtlX Surface Unlit`；AOVs 中自发光粒子选 `Lights and Emission` 下的 `Visible Lights` 层

**只渲被物体灯光照射的部分、不渲物体**：见 render-io 笔记的 holdout 部分。

**做一层自发光影响的灯光层 + 灯光自发光本身**：
1. `prune` 排除所有灯光影响
2. 避免噪点：`rendersettings edit` 拉高 `Path Traced Sam...`，`Pixel Oracle` 改 `uniform`
3. 除自发光模型外全设为承接背景：`rendergeometrysettings` → `Holdout Mode` = Matte
4. `Additional Render Vars` 加自发光灯光层
5. RenderVar 组合到一个文件（Beauty + holdout）
6. 最后一个灯光强度设 0

### 相机相关

- 景深：`Shift + F` 激活对焦面板；按住 `Shift + Ctrl` 点选焦点位置；渲染器勾 `Enable depth of field`
- 全景：Mantra 直接设；Karma 20 版本后支持

## 易错点

1. **透明 ≠ opacity**：水/玻璃用 `transmission`；opacity 只是 shader 淡化
2. **metallic 只能 0 或 1**：中间值出怪异混合材质
3. **白水必须 CPU 渲 + vex 材质**：mtlx 材质渲白水不行，与水分开渲
4. **DirectX 法线贴图会反转**（3ds Max 导出注意）；Houdini/Maya 是 OpenGL
5. **小物件关置换**：置换按世界坐标计算，模型小则置换值相对巨大
6. **Subsurface=1 损失反照率**：把颜色加回反照率补偿
7. **灯光排除对 instancer 内部无效**：用 prune 拆场景换父级
8. **渲染深度层必须关 Karma Fog Box**，否则深度值错误
9. **场景没灯时自发光不激活**：放一个强度 0 的灯
10. **视频序列贴图不播放**：Material Library 忘勾 `Allow Shader Parameter Animation`
11. **SOP 属性进 Stage 会改名**：Cd→displayColor、pscale→@widths，Prim Var Reader 里要写 Stage 名
12. **Point Light 球形模式强度随大小变**：勾 `Normalize Power`
