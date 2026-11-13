# Houdini 基础与工程规范（学自用户笔记 Houdini.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\Houdini.md` 的「快捷键/界面/项目规范/ACES/Houdini报错/小技巧/常见问题优化」章节。
原始笔记保持只读；本文件是蒸馏版。

## 0. 通用约定

- 项目命名：`项目名_场次_镜头号_版本号`，如 `dianta_efx_test_v001.hip`
- `$HFS` 安装根目录（macOS 示例：`/Applications/Houdini/Houdini19.5.493/Frameworks/Houdini.framework/Versions/19.5/Resources`）
  - 自带纹理：`$HFS/houdini/pic/texture/`
  - 自带 HDRI：`$HFS/houdini/pic/hdri/`
- IPR = 交互式真实照片级渲染（预览渲染视图）
- 常用资源：[官方文档](https://www.sidefx.com/docs/houdini/index.html)、[tokeru cgwiki](https://tokeru.com/cgwiki/)、[AMD GPU Open MaterialX Library](https://matlib.gpuopen.com/main/materials/all)

## 1. 快捷键 cheat-sheet

### 全局 / 面板

| 快捷键 | 功能 |
|---|---|
| `Alt + 1/2/3...` | 切换面板（1 场景 / 2 节点 / 3 参数 / 4 大纲 / 5 命令行 / 6 动画编辑器 / 7 材质编辑器 / 8 几何体信息 / 9 渲染视图 / 0 合成） |
| `Ctrl + 1/2/3/4` | 切换多视图布局 |
| `Ctrl + S` | 保存 |
| `Ctrl + W` / `Ctrl + B` / `Ctrl + T` | 关闭面板 / 全屏面板 / 新标签页 |
| `Alt + [` 或 `Alt + ]` | 上下 / 左右分割新面板 |
| `Ctrl + D` (win) | Dashbox 查找面板 |
| `Ctrl + F` 或 `/` | 查找节点 |
| `shift+alt+i` | 项目设置 |
| `Shift + Alt + W` | 单独弹出窗口 |
| `Ctrl + Alt + S` | 隐藏大部分 UI 元素 |

### 节点树窗口

| 快捷键 | 功能 |
|---|---|
| `Tab` | 调出节点 |
| `L` / `Shift+L` `A` | 全局 / 选中节点整理排列 |
| `I` / `U` | 进入该节点 / 返回上级 |
| `Q` 或 `B` | 禁用节点（bypass） |
| `N` | 切换工作环境（Obj → Out 等） |
| `A` + 左键拖拽 / 按住 `A` 在节点上向 上左/下右 拖 | 按鼠标方向排序 / 自动布局上游/下游节点 |
| `Shift + C` | 封装节点（Collapse） |
| `Shift + R` | 切换节点左右两端接口连接 |
| `J` 依次点节点 | 按点击顺序连接节点 |
| 选中多节点拉线时按 `Alt` | 自动创建 Merge 节点连接（拖两节点下方按 `Alt`/`option` 同理） |
| 连线时按 `Alt` | 在线上加一个点（弯线） |
| `z` / `c` | 节点形状 / 颜色面板（选中后按住 `Ctrl` 再选 = 设为该节点默认） |
| 选中节点按 `P` | 打开浮动参数面板 |
| `O` | 网络概览小窗 |
| `Y` | 剪刀工具（剪连线） |
| `Ctrl` 移动节点 | 带着下游一起移动；`Shift` 带上游；`Shift+Ctrl` 全部 |
| `Shift+点击参数` / `ctrl+shift+点击参数` | 弹曲线编辑器 / 清除关键帧或 VEX |

### 视图窗口

| 快捷键 | 功能 |
|---|---|
| `空格 + G / H / A` | 当前物体 / 还原 / 所有物体视图 |
| `1/2/3/4/5`（查看模式） | 透视 / 顶 / 前 / 侧 / UV 视图 |
| `1/2/3/4/5`（编辑模式） | 物体 / 点 / 线 / 面 / 顶点选择 |
| `E/R/T/Y` | 缩放 / 旋转 / 移动 / 循环切换 |
| `Shift + G/S` | 扩大 / 缩小选择 |
| `W` / `Shift + W` | 线框 / 光滑显示 |
| `Y` | 切换外部对象（ghost）可见性 |
| `O` | 正交/透视切换 |
| `B` | 单/多视角 |
| `D` | 视图设置（Display Options） |
| `S` | 进入选择模式 |
| `M` | 第一人称控制（FPV） |
| `X` | 吸附面板 |
| `Ctrl + I/L` | 反选 |
| `Ctrl + Shift + E` | 选中循环边 |
| 方向键（时间线） | 上=播放 下=回初始帧 左/右=退进一帧 |
| `/` 和 `*` | 缩放手柄视图大小 |

### 显示/渲染标志（节点树上 `W/E/R/T` 点击节点）

- `W`：强制显示该节点
- `E`：正常显示
- `R`：渲染使用该节点（渲染旗帜——无论显示标志在哪，只渲染带渲染标志的节点）
- `T`：以线框作参考模型 / `E` 以实体作参考

### 其它高频

- `Ctrl + 鼠标中键`：参数重置为默认
- `Ctrl+1/2/3/4/5` 存储当前节点面板路径，`空格+1/2/3/4/5` 跳转（跳转不同节点面板路径麻烦时用）
- 拍屏（Viewport Flipbook）：`Limit Frame Time` 是拍屏时每帧时长；对比不同版本拍屏用 `Sequence List` 面板（MPlay 里 `Alt+L`）
- 关键帧颜色：当前帧有 key = 蓝色；无 key = 淡蓝；无关 = 灰色

## 2. 界面要点（按 D 键的 Display Options 重点）

- **Badges 面板**：`Time Dependent Badge` 设为 `Large`——一眼看出哪些节点依赖时间；**有变换的节点放下游**，不依赖的放上方
- **Guides 面板**：开 `Draw Time (FPS)` 查看视口刷新率判断性能
- **Geometry 面板**：`Volume Quality` 调低体素预览质量防卡；粒子显示 `Display particles as` 建议改 `Pixels`（流体等）
- **Texture 面板**：`Limit Resolution` 限制 3D 纹理（体积）分辨率
- **Optimize 面板**：视口出现正方形框 = 内置 Packed Geometry 边界框代理（取消 `Distance-based Packed Geometry Culling` 可关，但视图可能变卡！）
- `Reload Current Desktop` 复原乱掉的界面；自定义桌面存 `.\Houdini 19.5.403\houdini\desktop`
- 近切远切看不到画面：视图 D 面板调 `Homing Auto Adjusts` 及 `Near/Far`；摄像机在参数面板 `View` 窗口调
- Performance Monitor：点 `Record` 播放时间线，红色节点最耗性能
- 节点依赖关系显示开启后，跨环境节点也有链接标志，右键可跳转上下游
- 时间线右下：脑图标=开关自动解算模拟；`Auto Update / On Mouse Up / Manual` = 实时刷新 / 停手刷新 / 手动加载刷新
- 关键帧默认曲线改线性：偏好设置 `Animation` 里 `bezier()` → `Linear()`
- Cache manager：窗口菜单打开，管理当前/最大缓存大小

## 3. 各环境（Context）速查

| 缩写 | 路径 | 含义 |
|---|---|---|
| SOPs | /obj/geometry/ | Surface Operators（几何层） |
| DOPs / POPs | — | 动力学 / 粒子 |
| VOPs | 多处 | VEX Builder |
| SHOPs | /shop/ | Shaders（旧） |
| MAT | /mat/ | 材质（本质是 VOPs） |
| ROPs | /out/ | 输出/渲染 |
| CHOPs | /ch/ | 通道/Motion FX |
| LOPs | /stage/ | Solaris（USD） |
| TOPs | /tasks/ | 任务 |
| COMP | /img/ | 合成 |

## 4. 项目规范（个人工作流）

- `Null` 输出节点统一以大写 `OUT` 开头（如 `OUT_GEO`）
- 渲染器（ROP）节点命名 = `Render` + 对应 Geo 节点名，一一对应

## 5. ACES 配置

### Houdini 20+（内置 OCIO 支持）

- Color setting 面板里文件规则**越往上优先级越高**
- 要渲出 `ACEScg` 的 exr：**输出序列命名里必须带 `ACEScg` 字样**，否则输出空间是 `Linear Rec.709 (sRGB)`
- 只有 **exr** 能保存 ACES 色彩空间，其它格式都不行

### Houdini 19.5 及以前

1. 下载 [aces config](https://github.com/colour-science/OpenColorIO-Configs) 放任意目录
2. `文档/Houdini 文件夹/houdini.env` 里写 OCIO 路径
3. 重启后 Color setting 自动读取，视图/渲染全变 ACEScg

## 6. 报错排查（实测案例）

| 报错 | 原因 / 解法 |
|---|---|
| 启动报未识别显卡、回退 CPU 核显 | `Edit - Preferences - Miscellaneous - OpenCL Device` 设为独立显卡 |
| `Error building YAML: Colorspace associated to the role 'color_picking', does not exist` | OCIO 路径含相对变量。出错点通常在 `packages/Labs_OpenColorIO.json`——**把 OCIO 改为绝对路径**。相关文件：`Documents/houdini20.0/houdini.env`、`packages/Labs_OpenColorIO.json`、`packages/ocio.json`、安装目录 `packages/ocio.json`、`sidefx_packages/SideFXLabs.../Labs_OpenColorIO.json` |
| `Unable to initialize rendering module with given camera` | 重新指定一个摄像机为渲染相机 |
| 编译参数错误、不认识 `out_2` | 材质编辑处有 2 个 `out` 参数同时导出到材质输出节点，断开一个 |
| 显卡过旧打不开 Houdini | 环境变量加 `HOUDINI_OCL_DEVICETYPE=CPU` |
| 修改系统日期后图标变黑块 | 系统日期导致（ licence 相关） |
| 帮助提示消失 | `$HOME/houdiniXX.X/common.pref` 写 `helpTags := 1` |

OCIO 推荐写法（houdini.env）：

```shell
OCIO = "${OCIO-C:/Users/User1/Documents/houdini20.0/ocio/houdini-config-v1.0.0_aces-v1.3_ocio-v2.1.ocio}"
```

## 7. 小技巧精选

### 性能（内置节点变快的 9 条）

1. 禁止基于点/面计算的表达式函数或 python
2. 尽量避免 foreach（用也要设计成支持多线程的网络）
3. 尽量多用 VEX（线程利用率高）
4. 用更快的 VEX 函数，避免冗余代码
5. 时间依赖代码集中在尽量少的 wrangle 里
6. 时间依赖节点尽可能晚出现、数量尽可能少
7. 选更高性能的算法
8. OpenCL 加速
9. 视图设为 BoundingBox 降低 fps 影响

### 缓存与解算

- **Dop Network 崩溃后续算**：dopnet 的 cache 选项卡设 `Save Checkpoints`（`Checkpoint Trail Length` 设 3~5 避免最后两帧数据不完整），file cache 缓存；崩溃后把 `.sim` 放进 dopnet `Simulation -> Initial State`，点 `Reset Simulation`（不要改起始帧），再在 File Cache 勾 `Initialize Simulation OPs` 从中断帧继续
- 导入 sim 缓存用 `$SF`，不要用 `$F`
- `Cache` 节点：内存缓存，可倒放、实时回放，代价是内存
- `Stash` 节点：把几何存进 hip 文件内（**不能存带动画的**）；`Move Stash to New File` 可外置减小 hip 体积
- substeps 子步数：越大越精确越慢

### 旧版/隐藏节点

- `Alt + Shift + T` 开 Textport：`ophide Sop` 查看隐藏节点，`opunhide Sop fluidsource` 解除隐藏
- 旧版节点：`Assets` 菜单 `Asset Definition Toolbar` 选 `show always`
- hiplc → hip 转换：Textport 里 `opscript -G -r / > $TEMP/temp.cmd`，新 hip 里 `cmdread $TEMP/temp.cmd`（HDA 可能丢节点；备用法：全部拖上工具架再拖下来）

### 其它

- `Save as Default`：参数保存为默认
- 参数右键 `Motion FX -> Noise` 做关键帧抖动（弹出 chopnet 调曲线）
- 自动保存间隔：偏好 `Save and Load Options -> Auto Save Every`
- `Time Shift` 做时间冻结
- 模型长度单位**不要超万级**——数值误差导致扭曲，精度越高越明显（obj 级没问题）
- 界面正方形框 = packed 几何的边界框代理，`Optimize` 面板关 `Distance-based Packed Geometry Culling`（视图可能变卡）
- Recipes（20.5+）：`Save Node Preset`（参数预设）/ `Save Selected Items as Tool`（节点组存成 Tab 工具）/ `Save Selected Items as Decoration`
- `Extract Transform` 继承物体旋转位移，copy 上去即可
- 模型摆正：`transform` 移到中心 → `Labs Straighten`（`Up Group` 选 y 轴面、`Forward Group` 选 x 轴面）
- Python shell 执行 Hscript 命令：命令前加 `%`
- 帮助标签见上文报错表

## 8. 常见问题优化（原文 97 条精华版）

### VEX / 表达式

- `@` 语法控制 group 参数：**不加数据类型，比较符号两边不留空格**
- `pcfilter` 不能读整数属性（用 `pcimportbyidxi` 代替）
- `noise/onoise/turb` 对整数采样结果为 0（表达式层面），换 `snoise/anoise/xnoise`
- VEX 不支持递归（可结合 foreach feedback 模拟）
- wrangle 里 `chramp` 输入默认无 0-1 限制，vop 里有
- 参数里写 python：结果 `return` 返回，return 不能在第一行；Hscript 的 return 必须包在 `{}` 里
- `lvar` 调用变量用 `@` 形式：`lvar("Time")` 对、`lvar("T")` 报错
- 矩阵复合变换是顺序操作，四元数复合变换是逆序操作
- 浮点/坐标向量用 `lerp` 插值，**方向向量用 `slerp`**
- `primuv()` 不支持读字符串属性（先读预存点序号再 `point()` 读）
- `intersect` 对四边面精度不如三角面，映射出错先转三角面
- 变换方向向量：必须分别变换起点与终点再确定新向量
- obj 下用帧表达式控制变换参数用 `$FF` 而非 `$F`，否则运动模糊渲染无效

### DOP / 解算

- FEM 用 `pintoanimation` 约束必须加数据类型；wire 对象不用
- 属性控制材质时，material 节点之后也**不要删控制属性**（属性都在解析材质之前处理）
- VEX/VOP 改 pack 对象方位：用 `setprimintrinsic()`，不能用矩阵乘
- `animated` 导入变形刚体只能导入 pack 后的移动+旋转；变形需用 `deforming`
- vellum weld 约束前不要用 voronoi fracture 做布料碎块（焊接不上，可碎块后加 fuse 修正）
- `pop spin` 会覆盖粒子 z 轴与 v 对齐并重置局部坐标系，需手动初始化 `orient`
- 串联 pop 网络：pop 节点只影响最近上游粒子流（分组也不行）——用 merge 并联或连 pre-solve 端口
- dop 数据 apply data 从左到右，重名时左边覆盖右边
- cluster 流体与刚体合并后刚体消失：刚体合并在流体**右侧**
- dop 会给 pack 刚体加 rest 属性，unpack 时排除 rest 防止原始 rest 被覆盖
- pack 刚体更新 `w` 有效、`orient` 无效；粒子相反（`w` 无效、`orient` 有效）
- 粒子系统以 `pscale` 为半径做碰撞检测，解算前先检查 pscale
- 群集（crowd）作刚体连 multisolver 时应连在其它刚体之前
- 刚体和 flip 碰撞拓扑尽量别变，否则 flip 碰撞不稳定
- `sop geometry` 导入外部几何体覆盖 Geometry 数据时 `set always` 会出错，导入外部几何体即可
- top 多线程输出 dop：关缓存，`rop geometry` 的 `All Frames In One Batch` 打开，保证一个 dop 序列在一个线程内输出
- 稀疏解算想让流体框初始包住发射器：volume source 开 `Enlarge Fields to contain sources`

### FLIP / 海洋 / 白水

- flip 粘性与密度缩放参数只影响效果不影响属性值
- flip 空气压力要关流体框自动匹配，且不支持压力自适应计算；Narrow Band 需流体框封闭 + reseed 打开
- flip 解算应记录 dopnet 缓存（变形刚体碰撞才准）；flip 太重时可只关 flipobject 的 `Allow Caching`
- 粒子包面要经过 `fluid compress` 流体压缩节点（narrow band 下才能包出完整表面）
- 白水 repellant 需 volume source 导入 **vdb** 的 surface 与 vel（不能是 volume）；最简单：flip 数据加 fluid compress
- 白水导入 vdb surface 用 `maximum half-width` 设计算范围；是 volume 则必须关
- 白水内置碰撞物必须是 sdf，不能是几何模型
- 海洋置换：mask 与 pointmask 一并输出到频域文件，材质 `spectrum geometry` 导入即可（无需设 mask geometry）
- 海洋材质置换时 `ocean foam` 要关 `displace particles` 才能与置换匹配
- 海面模型尺寸大于频谱节点 `Grid Size` 会在边缘产生接缝（波浪大更明显）——**海面模型尺寸应小于 Grid Size**
- 条纹波浪：scale 设 0、wave instance 的 wavelength 调大；`particle fluid mask` 的 `remove non-spectral waves` 可屏蔽
- 发射器多流体框：场名和序号间加下划线且从 0 开始（`density_0、density_1...`）
- volume 值为零的区域转出的 vdb 分辨率为零
- flip 液面降低：不提精度可用 `gas equalize volume` 或注入散度
- flip 开张力后可通过 `surfacepressure` 自定义流体压力
- dual rest 用 `dopimportfield` 导回（会创建 `rest*_ratio`，否则手动设）
- dopnet 直接导回 sop 不带速度，用 `dop import` 类节点

### SOP / 几何

- `attribute copy` 节点有 bug，树里有但运行不正常就重建一个新的
- 不要输出 bgeo 格式的 pack 序列模型（极慢且文件巨大）；pack 动态模型输出 **abc**
- solver 里要输出 input1 并保留属性累积：在 input1 的 wrangle 里累加 Prev_Frame 对应属性
- 自定义属性改材质库物理材质球要进内部改，不要在 mat 下直接改（渲染出错）
- `unpack` 会按原始 name 值打断点（不同 name 表面之间的点）
- `volume wrangle` 里按 voxel 位置建点需存在场的调用（如 `@density=@density`）
- Boolean 尽量不要含自相交表面（出错概率大增）
- 分支曲线 resample 后分支点处线会断开（产生新 ptnum）
- `xyzdist` 吸附多边形表面时点大量落在顶点/边上是正确结果；想减少就加模型精度
- degenerate primitives（蜕变模型）导致渲染极慢，先清除
- 点云搜索最近点：`pcimport()` 内置 `point.number` 与 `point.distance`，不用事先存属性
- cone 约束也有 `restlength`（默认 1），初始稳定需设正确值
- chop 的 foreach 的 channel group 不支持 `[]` 语法也不能直接写 `*`，写 `chan*`；循环变量用 `ch` 读 For 节点 `Current Loop Index`

### 渲染

- 置换渲染速度随模型精度提高明显变慢——权衡精度或降材质率
- 经典材质（非 pbr）透明度：关渲染器 `stochastic Transparency` 降噪
- mantra 输出 exr：不分材质层输出快很多（尤其大图）
- 提高 motion factor 可提速景深与运动模糊
- COP 里可直接用 Intel Denoiser 与 Optix Denoiser
- PBR 材质优先级：打开 mantra 总开关 `Enable Absorption and Nested Dielectrics`
- 材质中读点云文件只能从硬盘读，`op:` 路径无效
- 整型 point 属性在材质中无效、整型 prim 属性有效；浮点 point/prim 均有效但 **pack 几何体里浮点属性也无效**（用材质样式表）
- pyro sop 发射器初始不发 density 烟火会滞后于发射器模型（density 对 flame 有校正）
- Mocap Biped 要关 `In-Place`（原地动画在 out 的 agent 输出动画素材里设）
- agent edit 关节矫正对 crowd source 无效，用 motion clip 导入新动作
- gas blur 做流体融合需加 gas extrapolate，且外推距离=模糊距离
- 用点云时整数属性问题的完整对照见上文 VEX 节

### Python / 杂项

- python 执行输出节点 `pressButton` 是等输出全部结束再执行后面语句
- 用 python 控制 font 节点输出字符串：先打关键帧再 `change language to python`，结果用 return 返回
- 按选择顺序把点序号加进字符串：`hou.ui.paneTabs()[1].selectGeometry(ordered=1).selectionStrings()`
- `hou.ui.addEventLoopCallback()` 获取事件循环，约 50ms 频率
- 用 ML 库就装 python3.x 版本的 Houdini
- 自定义菜单 xml 放 `$HOME/houdiniXX.X` 会自动与系统默认菜单合并
- VEX 主攻密集型属性计算与建模；python 主攻脚本；传统表达式主攻节点间通信
- 能用 foreach 就不用 copy stamp；能不用 foreach 就不用；compile foreach 可并行——具体评估速度再选（普通 sop 网络也建议 compile block 提速）

## 9. houdini-bridge 使用相关注意

- Windows 下 houdini 命令行工具（husk/hoiiotool 等）需把 `C:\Program Files\Side Effects Software\Houdini <ver>\bin` 加入 PATH
- hip 内部路径引用节点时，相同内容放在不同位置的模型**路径名不能相同**，否则后者覆盖前者

## 易错点

1. **ACES 输出坑**：序列名不带 `ACEScg` 字样就渲成 Linear Rec.709；非 exr 格式保存不了 ACES
2. **OCIO 报错九成是相对路径**：`packages/Labs_OpenColorIO.json` 里的 `OCIO` 改绝对路径
3. **`@` group 语法**：不加类型前缀、比较符两边不留空格（`@Cd.x<0.5` 对，`@Cd.x < 0.5` 错）
4. **bgeo 存 pack 序列 = 灾难**：改存 abc 或先 unpack
5. **obj 级运动模糊**：表达式用 `$FF` 而非 `$F`
6. **pscale 决定粒子碰撞半径**：解算前必须检查
7. **dop 缓存续算**：`.sim` 放 Initial State 后不要改起始帧，File Cache 勾 `Initialize Simulation OPs`
8. **pop 串联失效**：pop 只作用于最近上游流，用 merge 并联或 pre-solve
9. **pack 几何体上浮点属性在材质中无效**——换材质样式表（Material Style Sheet）
10. **模型单位超万级会扭曲**：不能完全按真实比例摆场景
