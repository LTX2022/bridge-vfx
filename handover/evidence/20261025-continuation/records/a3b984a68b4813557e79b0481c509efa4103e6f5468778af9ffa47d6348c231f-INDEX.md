# References 全量索引（SKILL.md 的展开版）

> SKILL.md 的 References 节只保留「常用 6 份 + 目录级索引」；本文件是**全部
> reference 文件的逐份一句话清单**（2026-08-25 P0 瘦身时从 SKILL.md 原样迁出）。
> 找具体文件时读这份，选 1-2 份再深入。

## 单文件 references/

- `references/scatter-fix-guide.md` - instancer troubleshooting
- `references/bridge-protocol.md` - protocol notes (HTTP now; old TCP deprecated)
- `references/node-reference.md` / `sim-reference.md` - optional offline excerpts; prefer `help.search`
- `references/axiom-reference.md` - **Axiom 4 官方文档**（Notion 抓取）：Sourcing/Simulation/Combustion/Output/Settings/Memory 等
- `references/axiom-practice.md` - **Axiom 实战**：Pyro 对照、OOM、减烟最终参、陷阱、Fire_shot2 接线
- `references/hip-convert.md` - **hiplc / hdalc / hipnc / hdanc** 转换与解锁
- `references/usd-render-practice.md` - **USD/LOP 渲染缓存实战**（Fire_shot1/2 血泪）：sopimport 不落盘、分段独立 savepath、pxr 合并带 relationships、ZibraVDB 只存档不渲染、农场成本控制、渲染后校验
- `references/pyro-reference.md` - **Pyro 手册知识体系**（pyro.zip 27 文档完整原文整理）：场体系/sparse 模式/节点地图/燃烧三输出/lookdev 参数语义/官方调参顺序/instancing 术语/手册 zip 读取法
- `references/hda-authoring.md` - **HDA 创作全流程**（官方手册为准，hom.zip 原文核对+实测）：createDigitalAsset 全参数、版本工作流四步（allowEditingOfContents->updateFromNode->setVersion）、Sections/opdef、6 个实测坑
- `references/senior-discipline.md` - **资深纪律**：原子建图/不猜只查/验证再声称/cache 关卡/工具优先级 5 级/批量 vs 单建成本（10 节点单建 800ms vs 批量 66ms）/写 VEX 前必须查原生节点
- `references/node_inputs.json` - **210+ 常用节点输入端口标签缓存**（AI 接线不用试错）
- `references/market-benchmark.md` - **市场对标**（fxhoudinimcp 179 工具逐项对标 + Houdini-Agent 设计吸收）：缺口清单 + 建议动作

## workflows/（31 篇）

- `references/workflows/` - **31 篇工作流指南**（提取自 fxhoudinimcp）：pyro/destruction/fluid/vellum/mpm/solaris/render/shade/tops/crowds/ocean/heightfields/copernicus/ml/model/composite 等。做任何效果**先读对应指南**：含 Failure signatures（翻车信号）+ Order of work（5-7 步流程）+ 版本化节点词汇表（20.5/21.0/22.0 标注）
- `references/workflows-shared/` - workflows 指南的 housekeeping/layout 附则

## tutorials/（5 篇）

- `references/tutorials/` - **具体效果完整配方**（从真实工程逆向学习，hython 无头解析+实证 cook）：
  - `image-particle-dissolve-setup.md`：图像->粒子消散（trace+scatter+距轮廓mask+年龄Alpha），含换图复刻参数表、**视频序列扩展（固定点阵法防闪烁）**、**POP 优化重设计**（原版作者自评不佳勿学）与无头解析 .hip 方法论
  - `particle-animation-recipes.md`：粒子动画配方集（**variant 逐帧动画播放模式**、carve+wrap 沿轨迹、鸟群远景 VEX/POP 两法、蚊虫 Lag 跟随、抛物线 RBD、Karma 拉丝粒子 alpha 坑）
  - `wind-tunnel-pyro-setup.md`：风洞 Pyro 完整流程（发射源/碰撞体/**引导线速度场**（垫grid投射+clip防早吸+polyframe）/二次粒子，含 Voxel Size 口诀与逐 tab 配置）
  - `cloth-path-and-env-setup.md`：布料沿路径（Vellum Pin Type 选型语义：Permanent 不可解/Stopped 可解锁/Soft 弹性）、树风 Tree Wind HDA（pivot Origin 坑）、Labs Snow Buildup
  - `rocket-launch-pyro-setup.md`：火箭发射烟雾（含机翻对照表+参数速查，教程视频学习笔记）

## domains/（8 份领域知识库）

- `references/domains/` - labs/heightfields/mpm/copernicus/ml/vex_snippets/vex_attributes/houdini

## notes/（25 份用户笔记蒸馏，2026-08-25）

> 读自 OneDrive/Node/Node/，原始笔记只读未动；与 workflows/tutorials 互补--笔记视角的实测参数与坑。

- `houdini-notes-basics.md` - 快捷键/界面/ACES/报错排查/97 条常见问题优化精华
- `houdini-notes-shading-lighting.md` - PBR 贴图速查、MtlX 连线、Karma 灯光/体积雾配方
- `houdini-notes-render-io.md` - Karma 采样降噪、Solaris/USD 精要、husk/usdcat、AOV/holdout 五法、相机 Python 脚本
- `houdini-notes-sop-effects.md` - SOP 节点速查、撒点套路、沿曲线运动、Labs 效果
- `vex-vop-notes.md` - 属性速查、ch 家族、38 行高频函数表、VOP、波纹/雾气实测代码
- `foreach-compile-solver-notes.md` - For-Each 元数据、Compile Block 烘焙陷阱、Solver 生长蔓延三变体
- `python-hda-scripts-notes.md` - hou API、工具架脚本、HDA 制作陷阱、环境变量、工具包清单
- `pyro-notes.md` - 发射源三部曲、Solver 参数、蘑菇头消除（平流微解算器）、ML Upres、Axiom 补充
- `flip-ocean-notes.md` - FLIP 精度对齐公式、Ocean Spectrum 全参数、海洋渲染三策略、Ripple Solver
- `crowd-animation-notes.md` - Point Deform 三输入、Crowd 全流程、KindFX 花开绑定、APEX
- `feathers-fur-notes.md` - Feather Template 节点组、Guide Groom 笔刷、CHOP 螺旋桨
- `terrain-environment-notes.md` - HeightField 图层体系、37 节点速查、Labs 树木、DEM/OSM 真实地形
- `large-case-studies.md` - 建筑爆炸全流程拆解（材质切割->胶约束->DOP->Pyro）
- `vellum-rbd-notes.md` - Vellum 属性表、斗篷/幕布/旗帜案例、Bullet Solver 五输入语义
- `particles-pdg-notes.md` - POP 选型、1600 万沙粒经验、PDG 榨干 CPU（Total Slots=-1）
- `misc-tools-notes.md` - COPs 新旧版、3DGS 资源、ML Volume Upres 速查
- `official-docs-index.md` - **官方文档全索引**：47 个 help zip 按用途分组、官方示例 hip 地图（sop 238 节点示例）、files/ 精品工程（karma_user_guide/expression_cookbook/pdg_examples）、三种读取方法、蒸馏策略备忘
- `official-docs-quickref.md` - **官方文档人工蒸馏版**：15 域高频页速查（路由器「查官方文档」行的必读文件）
- `pipeline-farm-delivery-notes.md` - 三维基础蒸馏①：Deadline 安装/提交/多机组网、HQueue 对比、格式位深、交付命名规范
- `vfx-shot-craft-notes.md` - 三维基础蒸馏②：镜头分级方法论、畸变 STMap 流程、AOV/PBR 速查、色彩空间交付四件套
- `vfx-industry-misc-notes.md` - 三维基础蒸馏③：术语/岗位/坐标朝向/资源/简历作品集
- `blender-notes.md` - Blender 全量蒸馏：交接章节置顶（abc 相机入 Nuke、FBX 骨骼无解、ACES 配置、MultiLayer EXR）
- `cross-dcc-notes.md` - UE/EmberGen/C4D/Maya/技美五合一（MRQ 预热、VDB 三端口导出、Maya 序列前导零坑）
- `dcc-fundamentals-notes.md` - 建模/材质/灯光/动作四门基础课（IOR 速查表、光比公式、PBR 双流程）
- `cloth-pattern-notes.md` - 衣服制版：打版四大铁律、CLO/MD 实操、GarmentCode/ContourCraft 管线（与 vellum-rbd-notes 呼应）

## 其他

- `references/official-docs/` - **官方文档同步索引**（由 `scripts/official_docs_sync.py` 生成）：`INDEX.md` 总目录 + 47 个域各一份 `<domain>-index.md`。升级 Houdini 后重跑脚本即可刷新，**不用手工改**
- `references/meshy-animation/` - Meshy 592 动作目录+中英检索（动画本体在云端，需 rig API+credits）
- `references/future/blender-mcp-protocol.md` - Blender 桥接协议参考（未来 blender-bridge 用）
