# Houdini 官方文档速查（基于 22.0.368 官方索引，2026-08-25）

> 由 `scripts/official_docs_sync.py` 生成索引（见 `references/official-docs/INDEX.md`），本文件是人工蒸馏版。
> 只收录高频页；完整列表看各 `<domain>-index.md`（47 域 / 10450 页）。
> 所有路径都是 zip 内部路径，读取方式：`python official_docs_sync.py --page vex.zip:lang.txt`。

---

## VEX（vex.zip，1178 页）

入口与语言：

| 路径 | 说明 |
|---|---|
| `index.txt` | VEX 总入口（写在哪、怎么跑） |
| `lang.txt` | VEX 语言参考：类型、运算符、函数定义、cast 规则 |
| `snippets.txt` | Wrangle 里的 VEX 片段写法（@ 绑定、`opinput:` 等） |
| `contexts/index.txt` | VEX 上下文总表（sop/cvex/fog/shading…） |
| `contexts/sop.txt` | SOP 上下文：Wrangle 可用的全局变量与规则 |
| `arrays.txt` / `dicts.txt` / `strings.txt` | 数组、字典、字符串用法 |
| `groups.txt` | 在 VEX 里读写几何组 |
| `functions/index.txt` | 全部函数目录 |
| `geometry_suite.txt` / `math_suite.txt` / `vector_suite.txt` / `matrix_suite.txt` | 按主题分的函数清单 |
| `attrib_suite.txt` | 读属性函数一族总览 |
| `cookbook.txt` | 官方案例集 |

高频函数（都在 `functions/` 下）：

| 路径 | 说明 |
|---|---|
| `point.txt` / `prim.txt` / `vertex.txt` / `detail.txt` | 读属性（跨输入节点） |
| `setpointattrib.txt` / `setprimattrib.txt` | 写属性 |
| `addpoint.txt` / `addprim.txt` / `removepoint.txt` / `removeprim.txt` | 增删几何 |
| `npoints.txt` / `nvertices.txt` | 元素计数 |
| `nearpoint.txt` / `nearpoints.txt` / `xyzdist.txt` / `primuv.txt` / `minpos.txt` | 最近点/距离/UV 查询 |
| `pcopen.txt` / `pcnumfound.txt` | 点云查询（半径内聚合） |
| `noise.txt` / `onoise.txt` / `curlnoise.txt` / `rand.txt` | 噪声与随机 |
| `fit.txt` / `fit01.txt` / `clamp.txt` / `lerp.txt` / `chramp.txt` | 重映射与插值 |
| `length.txt` / `normalize.txt` / `dot.txt` / `cross.txt` | 向量运算 |
| `quaternion.txt` / `eulertoquaternion.txt` / `qconvert.txt` / `dihedral.txt` / `maketransform.txt` | 旋转与变换 |
| `intersect.txt` | 射线求交 |
| `neighbours.txt` / `pointprims.txt` / `pointvertex.txt` / `vertexpoint.txt` | 拓扑遍历 |
| `volumesample.txt` / `volumeindextopos.txt` | 体数据采样 |
| `relbbox.txt` / `getbbox.txt` | 包围盒 |
| `sprintf.txt` / `itoa.txt` / `atoi.txt` / `split.txt` / `join.txt` | 字符串处理 |
| `append.txt` / `find.txt` / `sort.txt` / `len.txt` | 数组操作 |

## HOM / Python（hom.zip，966 页）

| 路径 | 说明 |
|---|---|
| `index.txt` | Python scripting 总入口 |
| `commandline.txt` | hython / hbatch / 命令行跑 Python |
| `expressions.txt` | 参数里的 Python 表达式 |
| `cb/index.txt` | HOM Cookbook 目录 |
| `cb/pythonsop.txt` / `pythonsop.txt` | 写 Python SOP |
| `hou/index.txt` | `hou` 模块函数总表（`hou.node`、`hou.pwd`、`hou.frame`…） |
| `hou/Node.txt` | 节点对象：创建/连线/参数/cook |
| `hou/Geometry.txt` | 几何对象：读写点/面/属性（`geo.points()` 等） |
| `hou/Point.txt` / `hou/Prim.txt` / `hou/Vertex.txt` / `hou/Attrib.txt` | 几何元素 |
| `hou/SopNode.txt` / `hou/ObjNode.txt` / `hou/DopNode.txt` / `hou/LopNode.txt` / `hou/VopNode.txt` | 各上下文节点子类 |
| `hou/Parm.txt` / `hou/ParmTuple.txt` | 参数读写、求值、表达式 |
| `hou/ParmTemplate.txt` / `hou/ParmTemplateGroup.txt` | 动态改参数界面（HDA） |
| `hou/NodeType.txt` / `hou/NodeTypeCategory.txt` | 节点类型与 `createNode` |
| `hou/Vector3.txt` / `hou/Matrix4.txt` / `hou/Quaternion.txt` / `hou/Ramp.txt` | 数学类型 |
| `hou/Keyframe.txt` | 关键帧 |
| `hou/ui.txt` | UI 交互（选文件、弹窗、光标） |
| `hou/hipFile.txt` / `hou/session.txt` | hip 文件与 session 模块 |

## Solaris / USD / Karma（solaris.zip，73 页）

| 路径 | 说明 |
|---|---|
| `index.txt` | Solaris and Karma 总入口 |
| `about_lops.txt` | LOPs 工作原理（层、舞台） |
| `usd.txt` / `glossary.txt` | USD 基础与术语 |
| `jumpstart.txt` | Solaris 快速上手 |
| `sop_import.txt` | SOP 几何导入 USD |
| `pattern.txt` | Prim 匹配模式语法（`/scene/*`） |
| `output.txt` | 写出 USD（USD ROP 流程） |
| `karma.txt` / `karma_xpu.txt` | Karma CPU/XPU 总览 |
| `kug/index.txt` | Karma User Guide 目录 |
| `kug/sampling.txt` / `kug/noise.txt` | 采样与降噪 |
| `kug/lights.txt` / `kug/cameras.txt` / `kug/geometry.txt` / `kug/materials.txt` | 灯光/相机/几何/材质 |
| `support/aovs.txt` | AOV 设置 |
| `support/lpe.txt` | Light Path Expressions |
| `support/point_instancing.txt` | 点实例化 |
| `support/light_filters.txt` / `support/light_instancing.txt` | 灯光滤镜/灯光实例化 |
| `materialx.txt` / `quick_materials.txt` | MaterialX 与快速材质 |
| `performance.txt` | Solaris 性能建议 |
| `vex.txt` | 在 USD 上用 VEX |

常用 LOP/ROP 节点（nodes.zip）：`lop/sublayer.txt`、`lop/reference.txt`、`lop/graftstages.txt`、`lop/sopimport.txt`、`lop/sopcreate.txt`、`lop/materiallibrary.txt`、`lop/assignmaterial.txt`、`lop/karma.txt`、`lop/karmarenderproducts.txt`、`lop/rendergeometrysettings.txt`、`lop/pointinstancer.txt`、`lop/stagemanager.txt`、`lop/usd_rop.txt`、`lop/usdrender_rop.txt`、`out/karma.txt`、`out/usdrender.txt`。

## Mantra 渲染（render.zip，41 页）

| 路径 | 说明 |
|---|---|
| `index.txt` | Mantra 总入口 |
| `render.txt` / `nodes.txt` | 怎么发起渲染 / render 节点 |
| `mug.txt` / `understanding.txt` | Mantra 用户指南与原理 |
| `quality.txt` / `sampling.txt` / `sampling_tab.txt` | 质量、速度、采样参数 |
| `noise.txt` / `optixdenoiser.txt` | 降噪 |
| `cameras.txt` / `lights.txt` / `envmaps.txt` | 相机、灯光、环境光 |
| `blur.txt` | 运动模糊 |
| `volumes.txt` | 体积渲染 |
| `deeprasters.txt` | 额外图像平面（AOV/deep） |
| `lpe.txt` | Light Path Expressions |
| `linear.txt` | 线性色彩工作流 |
| `python.txt` | Mantra 里用 Python（属性/property） |
| `ifd.txt` / `ifd_workflows.txt` | IFD 场景描述格式 |

## 材质 / 着色（shade.zip，20 页）

| 路径 | 说明 |
|---|---|
| `index.txt` / `basics.txt` | Mantra 材质入口、使用材质 |
| `build.txt` / `vops.txt` | 搭材质、VOP 网络 |
| `textures.txt` | 贴图使用 |
| `normalmaps.txt` | 法线/凹凸/置换 |
| `parms.txt` / `overrides.txt` | 材质参数、逐对象覆盖 |
| `layering.txt` | shader 分层 |
| `stylesheets.txt` | Material Stylesheets |
| `looping.txt` | VOP 里的循环与条件 |
| `glsl.txt` | 自定义视口 GLSL shader |

## 模拟

### Vellum（vellum.zip，38 页）

| 路径 | 说明 |
|---|---|
| `overview.txt` / `index.txt` | Vellum 总览 |
| `vellumattributes.txt` | 全部 Vellum 属性参考（必查） |
| `clothsimulation.txt` / `lowreshighres.txt` / `quickmovingcloth.txt` | 布料工作流 |
| `softbody.txt` | 软体 |
| `configuregrains.txt` | 颗粒（沙子/雪） |
| `fluidsetups.txt` / `fluidemission.txt` / `fluidtips.txt` / `vellumvsflip.txt` | Vellum 流体及与 FLIP 的取舍 |
| `dynamicconstraints.txt` / `slidingconstraints.txt` / `pressure.txt` | 约束 |
| `breaking_tearing.txt` | 撕裂 |
| `vdbcollisions.txt` / `intersect.txt` | 碰撞 |
| `vellumtips.txt` / `minimal.txt` | 排错与 minimal 模式 |

节点：`sop/vellumsolver.txt`、`sop/vellumconstraints.txt`、`dop/vellumsolver.txt`。

### FLIP / 流体（fluid.zip，34 页）

| 路径 | 说明 |
|---|---|
| `index.txt` / `liquids.txt` | 流体入口、粒子流体基础 |
| `dopversussop.txt` | DOP 与 SOP 两条流体工作流的区别 |
| `sopminimalsetup.txt` | 最小 SOP 流体搭建 |
| `sopsourcing.txt` / `sopcollisions.txt` / `sopboundaries.txt` | 源、碰撞、边界 |
| `sopconfigflip.txt` / `sopconfigtank.txt` / `sopconfigbeach.txt` / `sopconfigwave.txt` | FLIP Configure 系列模板 |
| `narrowband.txt` / `sopnarrowband.txt` | Narrow Band 省内存 |
| `flipviscosity.txt` / `sopvischoney.txt` | 粘度（蜂蜜/岩浆） |
| `sopwhitewater.txt` / `whitewater.txt` | 白水（SOP/DOP） |
| `surfacing.txt` | 流体表面化与渲染 |
| `compress.txt` | Fluid Compression 减缓存 |
| `tips.txt` | 排错 |

节点：`sop/flipsolver.txt`、`sop/flipsource.txt`、`dop/flipsolver.txt`、`sop/whitewatersolver.txt`。

### Pyro（pyro.zip，29 页）

| 路径 | 说明 |
|---|---|
| `intro.txt` / `background.txt` | Pyro 入门与原理 |
| `differences.txt` | legacy 与 sparse pyro 差异 |
| `sparsity.txt` | 稀疏 vs 稠密 |
| `lookdev.txt` | Pyro 工作流（源→解算→lookdev） |
| `explode.txt` / `flames.txt` / `sparks.txt` | 爆炸、火焰、火花配方 |
| `shading.txt` | Pyro 着色与渲染 |
| `pyroinstancing.txt` / `advanced.txt` / `packedrbd.txt` | Pyro 实例化 |
| `copintro.txt` | COPs（Copernicus）里的 Pyro |

节点：`sop/pyrosolver.txt`、`sop/pyrosourcespread.txt`、`dop/pyrosolver.txt`、`dop/pyrosolver_sparse.txt`。

### RBD / 破坏（destruction.zip，20 页）

| 路径 | 说明 |
|---|---|
| `overview.txt` | 破坏总览 |
| `constraints.txt` | RBD 约束 |
| `glass.txt` / `concrete.txt` / `wood.txt` / `metal.txt` | 按材质破碎 |
| `plasticity.txt` | 弯曲与断裂 |
| `sop_sim.txt` | SOP 层级做 RBD 解算 |
| `guidedsims.txt` | 引导模拟 |
| `tutorials/intro_to_mbd_1.txt` | Material Based Destruction 教程 |

节点：`sop/rbdmaterialfracture.txt`、`sop/rbdconfigure.txt`、`sop/rbdpack.txt`、`dop/rbdsolver.txt`。

### 海洋（ocean.zip，4 页）＋ 地形（nodes.zip）

| 路径 | 说明 |
|---|---|
| `ocean.zip:index.txt` / `oceanspectra.txt` | 海洋频谱工作流 |
| `ocean.zip:ripplesolver.txt` | SOP Ripple Solver |
| `nodes.zip:sop/oceanspectrum.txt` / `sop/oceanevaluate.txt` | 频谱生成与求值 |
| `nodes.zip:lop/karmaocean.txt` | Karma 海洋渲染 |
| `fluid.zip:oceans.txt` / `sopoceanwaves.txt` | FLIP 引导海洋 |

HeightField（没有独立域，都在 nodes.zip）：`sop/heightfield.txt`、`sop/heightfield_noise.txt`、`sop/heightfield_erode.txt`（含 `_hydro`/`_precipitation`/`_thermal` 子页）、`sop/heightfield_maskbyfeature.txt`、`sop/heightfield_project.txt`、`sop/heightfield_scatter-…txt`、`sop/heightfield_output.txt`、`sop/heightfield_layer.txt`、`sop/convertheightfield.txt`。

## 角色 / 群集

### KineFX & 角色（character.zip，143 页）

| 路径 | 说明 |
|---|---|
| `kinefx/overview.txt` | KineFX 工具集总览 |
| `kinefx/glossary.txt` | 术语（skeleton/capture/clip…） |
| `kinefx/importcharacters.txt` / `kinefx/exportcharacters.txt` | 角色数据进出 |
| `kinefx/preparingskeletons.txt` / `kinefx/capture.txt` | 骨骼准备与蒙皮 |
| `kinefx/retargeting.txt` / `kinefx/retargetcleanup.txt` | 重定向 |
| `kinefx/posing.txt` / `kinefx/animationlayers.txt` / `kinefx/motionclips.txt` | 摆姿、动画层、MotionClip |
| `kinefx/motioncapture.txt` | 动捕数据 |
| `kinefx/animatestate.txt`（及 `animatestate*` 子页） | 视口 Animate 状态 |
| `kinefx/ragdoll.txt` | 角色 Ragdoll |
| `kinefx/apexgraphbasics.txt` / `apexscriptlanguage.txt` | APEX 图与脚本 |
| `kinefx/rig_components/*.txt` | 现成 rig 组件（spine/limb/foot…） |

节点多为 `sop/kinefx--*.txt`（如 `kinefx--biped_retarget.txt`、`kinefx--characterpack.txt`）。

### 群集（crowds.zip，22 页）

| 路径 | 说明 |
|---|---|
| `basics.txt` / `setup.txt` | 群集入门与搭建 |
| `agents.txt` / `attributes.txt` | Agent Primitive 与属性 |
| `states.txt` / `triggers.txt` / `transitions.txt` | 状态机 |
| `diversity.txt` | 外观/动作多样性 |
| `terrain.txt` / `obstacles.txt` | 地形与障碍 |
| `ragdoll.txt` | 群集 Ragdoll |
| `sopcrowds.txt` / `sopcrowdsattributes.txt` | SOP motion paths |
| `fuzzy.txt` | 模糊逻辑 |

节点：`sop/agentprep.txt`、`sop/agentcliptransitiongraph.txt`、`sop/crowdsource-2.0.txt`、`dop/crowdsolver.txt`、`dop/crowdstate.txt`。

## COPs / 合成

- **Copernicus（新 COPs）**：无独立域，节点在 `nodes.zip:cop/index.txt`（"Copernicus nodes"），常用 `cop/heightfield_erode.txt`、`cop/heightfield_project.txt` 等；概念页见 `pyro.zip:copintro.txt`。
- **旧 COP2**：节点在 `nodes.zip:cop2/index.txt`（"Compositing nodes"）；概念页在 composite.zip，但索引中多为 `#index: no` 草稿标记，直接查节点页更可靠。
- VEX 写 COP 像素：`vex.zip:contexts/cop2.txt`、`cop2_sample_suite.txt`。

## PDG / TOPs（tops.zip，223 页）

| 路径 | 说明 |
|---|---|
| `intro.txt` / `index.txt` | PDG/TOPs 入门 |
| `nodes.txt` | 常用 TOP 节点清单 |
| `cooking.txt` | 执行 TOP 网络 |
| `attributes.txt` | work item 属性用法 |
| `paths.txt` / `filetags.txt` | 文件路径与标签 |
| `partitioners_overview.txt` | 分区器 |
| `looping.txt` | 反馈循环 |
| `custom_scheduler.txt` | 自定义调度器 |
| `examples.txt` / `commonhowto.txt` | 官方示例与常见做法 |
| `pdg/WorkItem.txt` / `pdg/Graph.txt` / `pdg/Node.txt` | pdg Python API |

节点：`top/filepattern.txt`、`top/ropfetch.txt`、`top/geometryimport.txt`、`top/wedge.txt`、`top/pythonscript.txt`、`top/hdaprocessor.txt`、`top/partitionbyattribute.txt`、`top/waitforall.txt`、`top/localscheduler.txt`。

## 表达式 / HScript / 环境

| 域 | 路径 | 说明 |
|---|---|---|
| expressions.zip（478 页） | `index.txt` | 表达式函数总表 |
| | `ch.txt` / `chf.txt` / `chs.txt` | 参数引用（最常用） |
| | `point.txt` / `prim.txt` / `detail.txt` | 表达式版读属性 |
| | `bbox.txt` / `centroid.txt` / `npoints.txt` | 几何信息 |
| | `stamp.txt` / `opinputpath.txt` / `padzero.txt` | copy-stamp、输入路径、帧号填充 |
| commands.zip（442 页） | `_guide.txt` | HScript 语言指南；其余基本是单条 hscript 命令 |
| ref.zip | `env.txt` | 全部环境变量（HOUDINI_PATH 等） |
| | `commandline.txt` | 命令行启动 Houdini |
| | `utils/husk.txt` / `utils/hrender.txt` | 命令行渲染 |
| basics.zip | `config_env.txt` / `houdinipath.txt` / `config.txt` | 配置、HOUDINI_PATH、环境变量 |

## 怎么用

1. **不知道去哪查**：先读本文件定位域 → 开 `references/official-docs/<domain>-index.md` 全表。
2. **关键词全文搜**：
   ```bash
   python official_docs_sync.py --query 关键词 --domain vellum   # 只搜某域
   python official_docs_sync.py --query 关键词                    # 全 47 域
   ```
   bridge 运行时等价于 MCP 工具 `help.search` / `help.query`。
3. **读某页全文**：
   ```bash
   python official_docs_sync.py --page vellum.zip:vellumattributes.txt
   ```
   路径格式 `<domain>.zip:<zip内路径>`，zip 内路径从本速查表或 index 文件里抄（去掉行首 `| \`` 和结尾 `\``）。
4. **大域只挑入口**：vex/hom/nodes 合计 7000+ 页，别通读索引；vex 先看 `lang.txt`/`functions/index.txt`，hom 先看 `hou/index.txt`/`hou/Node.txt`/`hou/Geometry.txt`，nodes 用 `--query` 按节点名直搜。

## 易错点

- **索引标题不可信**：nodes.zip 大量条目是 `#type: node`、composite/anim 有 `#index: no`、`#type: include` 是被 include 的片段——判断内容以路径为准。
- **同名多版本**：`-2.0.txt`、`-…txt` 后缀是节点版本分支（如 `copytopoints-.txt`/`copytopoints.txt`），一般用无后缀的最新版，老场景才对版本页。
- **copernicus 没有独立域**：新 COPs 在 `nodes.zip:cop/`，旧合成在 `cop2/` + composite.zip；别想当然搜 `copernicus.zip`。
- **没有 heightfields 域**：HeightField 全是 `nodes.zip:sop/heightfield_*`，概念散在 gallery/examples。
- **TOP 节点页在 nodes.zip 不在 tops.zip**：tops.zip 是概念 + `pdg/` Python API；单个 TOP 节点查 `nodes.zip:top/<name>.txt`。
- **VEX 与表达式同名不同物**：`ch`、`point`、`detail` 在 expressions.zip 是 hscript 表达式，在 vex.zip 是 VEX 函数，域别抄错。
- **karma 有两个层级**：概念/参数在 solaris.zip（`karma*.txt`、`kug/*`），ROP 节点页在 nodes.zip（`out/karma.txt`、`lop/karma.txt`）。
- **重跑脚本会覆盖索引**：`official-docs/` 下文件全部由 sync 脚本生成，升级 Houdini 后重跑即可，手改无效。
