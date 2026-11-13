# Houdini 官方文档与工程文件索引（2026-08-25 盘点）

本机路径：`C:\Program Files\Side Effects Software\Houdini 21.0.631\houdini\help\`
（版本 21.0.631 自带完整离线文档；路径因版本而异，把 `21.0.631` 换成实际版本号即可）

**已深度蒸馏**：`pyro.zip` → `references/pyro-reference.md`（27 文档完整整理）。
**已部分索引**：`sim-reference.md` / `node-reference.md`（有截断，只当索引用）。
**其余 46 个 zip 未蒸馏**——但**不需要全部蒸馏**：bridge 自带 `help.query` / `help.search`
离线全文检索工具，随用随查比预蒸馏更准确（永远与安装版本一致）。本文件是"查什么去哪查"的地图。

## 1. 47 个官方帮助 zip（按用途分组）

### 核心求解/模拟（做效果时最常查）
| zip | 内容 | 何时查 |
|---|---|---|
| `pyro.zip` | Pyro 全部节点+手册 | ✅ 已蒸馏（pyro-reference.md） |
| `fluid.zip` | FLIP/白水/粒子流体 | 流体疑难 |
| `ocean.zip` | Ocean Spectrum/Evaluate | 海洋 |
| `vellum.zip` | Vellum 约束/求解 | 布料/柔体/头发 |
| `grains.zip` | POP Grains | 沙粒/雪 |
| `mpm/` (目录) | MPM 求解器 | 雪/泥/混合材质 |
| `finiteelements.zip` | FEM 柔体 | 肌肉/软体 |
| `destruction.zip` | RBD 破碎 | 破碎 |
| `dopparticles.zip` | POP 粒子 | 粒子 |
| `dyno.zip` | DOP 通用 | 自定义解算 |
| `crowds.zip` | 群集 | crowd |
| `muscles.zip` | 肌肉系统 | 角色 |
| `fur.zip` / `feathers.zip` | 毛发/羽毛 | grooming |
| `heightfields/` (目录) | 地形 | 地形 |
| `ml/` (目录) | ML 工具集 | ML Upres 等 |
| `copernicus/` (目录) | COPs 2.0 程序化纹理 | 新版 COP |

### 渲染/材质/合成
| zip | 内容 |
|---|---|
| `render.zip` | Karma/Mantra/ROP |
| `shade.zip` | MtlX/材质 |
| `solaris.zip` | LOP/USD/Stage |
| `composite.zip` | 旧版 COPs |
| `images.zip` | 图像 I/O |
| `visualizers.zip` | 可视化 |

### 基础/通用
| zip | 内容 |
|---|---|
| `basics.zip` | 入门概念 |
| `model.zip` | SOP 建模 |
| `anim.zip` | 动画/KineFX |
| `character.zip` | 角色绑定 |
| `audio3d.zip` | 音频/3D |
| `copy.zip` | 复制/stamp |
| `props.zip` | 道具 |

### 开发/脚本/TD
| zip | 内容 | 何时查 |
|---|---|---|
| `vex.zip` | **VEX 函数大全** | 写 wrangle 前 |
| `expressions.zip` | HScript 表达式 | 写参数表达式前 |
| `hom.zip` | **Houdini Object Model（Python API）** | 写 hou 脚本前 |
| `hapi.zip` | Houdini Engine API | 引擎集成 |
| `shelf.zip` | 工具架定制 | 做工具 |
| `network.zip` | 网络编辑器 | UI 定制 |
| `commands.zip` | hscript/hython 命令 | 命令行 |
| `tops.zip` | PDG/TOPs | 任务图 |
| `hqueue.zip` | HQueue 农场 | 农场 |
| `io.zip` | 文件 I/O | 导入导出 |

### 杂项/历史
`assets.zip`（HDA）、`gallery.zip`（画廊）、`news.zip`（版本新闻）、
`nodes.zip`（节点索引）、`ref.zip`（参考）、`start.zip`（快速开始）、
`help.zip`（帮助系统自身）、`mplay.zip`（播放器）、`maya.zip` / `unity.zip` /
`unreal.zip` / `3dsmax/`（迁移指南）、`hwebserver/`（web 服务器）、
`labs/`（Labs 工具）、`licenses/` / `licensing/`、`videos/`、`images.zip`

## 2. 官方示例工程（`.hip` 全套，本地直接打开学习）

### 节点示例库（每节点一个 hip）
`help/examples/nodes/` 下按上下文分目录，每个节点目录里是该节点的示例 hip：

| 目录 | 节点数 | 用途 |
|---|---|---|
| `sop/` | **238 个节点** | 每个 SOP 一个示例目录（add/assemble/attribpaint/...） |
| `dop/` | 86 个节点 | DOP 求解器示例 |
| `lop/` | 82 个节点 | Solaris/USD 示例 |
| `chop/` | 41 个节点 | CHOP 通道 |
| `cop2/` | 29 个节点 | 旧版 COPs |
| `obj/` `out/` `shop/` | 各 10-14 | 对象/输出/材质 |

**用法**：直接 `open_script` 打开对应节点的 hip，看官方接线。比如想看 attribpaint：
`help/examples/nodes/sop/attribpaint/*.hip`。这比看文字手册快得多——
**"想学什么节点，先开它的官方示例 hip"** 是最高效的学习路径。

### files/ 精品工程（完整可学）
| 路径 | 内容 | 价值 |
|---|---|---|
| `files/karma_user_guide/karma_user_guide.hip` | Karma 官方用户指南工程 | 渲染 |
| `files/karma_user_guide/custom_nodegraphs/` | 自定义 MtlX 节点图开发（含 .mtlx/.hda/.json 全套） | **自定义材质节点** |
| `files/expression_cookbook/` | 10 个表达式专题 hip（Sin/Ripple/Modulus/Random/Step/LogSpiral/Arc/WaveForm/Deformation/AnimationCycle） | **表达式教科书** |
| `files/pdg_examples/` | 9 个 PDG 场景（mqscheduler/feedbacksim/imagemanipulation/invoke/jsonpipeline/...） | PDG 实战 |
| `files/pdg_tutorials/` | PDG 教程 | PDG 入门 |
| `files/ifd_workflows/` | Mantra IFD 工作流 | 旧渲染器参考 |
| `files/PythonCops.hda` | Python COP 示例 HDA | 脚本化 COP |
| `files/anaglyph.hip.gz` | 3D 红蓝立体 | 杂项 |
| `files/surface_wires.hip` / `color_falloff.hip` / `multi_stamp.hip` / `vary_per_copy.hip` / `obj_xform.hip` / `xforms_from_disk.hip` | 单文件示例 | 技巧 |
| `files/motion.csv` | 运动数据样例 | CHOP |

## 3. 读取方法（三种，按场景选）

### 方法 1：bridge 内置工具（运行时首选）
```
help.search 关键词        # 全文检索离线手册（版本精确）
help.query <页面路径>      # 取某页完整内容
help.list / help.stats   # 目录/统计
```
fxhoudinimcp 的 Documentation 类目（见 market-benchmark.md）证明这是最佳实践。

### 方法 2：Python zipfile 直读（离线批处理）
```python
import zipfile
z = zipfile.ZipFile(r"C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/vex.zip")
names = [n for n in z.namelist() if n.endswith(".txt")]
# 读某函数文档
txt = z.read("source/rand.txt").decode("utf-8", errors="ignore")
```

### 方法 3：解压后 grep（一次性大排查）
```bash
cd /tmp && unzip -o ".../help/vellum.zip" -d vellum_help
grep -rn "voxelsize" vellum_help/ | head
```

## 4. 蒸馏策略备忘（为什么不做全量蒸馏）

1. **版本绑定**：文档随 Houdini 版本变化，预蒸馏会过期；`help.search` 永远版本精确
2. **体量**：47 zip ≈ 数万页，蒸馏成本远大于按需查询
3. **已蒸馏的例外**：pyro.zip（最高频+官方手册结构值得整体入脑）、axiom（Notion 官方文档）
4. **官方示例 hip 不蒸馏文本**，而是**用时直接打开**（bridge 有 open_script）或 hython 无头解析
   （方法论见 `references/tutorials/image-particle-dissolve-setup.md` 的无头解析 .hip 一节）

## 易错点

- **路径版本号**：升级 Houdini 后 `21.0.631` 要改；多版本并存时注意选对
- **help zip 是压缩文本**：不要当二进制读；编码按 utf-8 ignore 处理
- **示例 hip 打开会污染当前场景**：用独立 hython 或先 save 当前场景
- **examples/nodes 目录名带 `--`**（如 `apex--autorigcomponent`）是因为名字含 `/`，替换成了 `--`
- **sim-reference.md / node-reference.md 有截断**：只当索引用，细节回 zip 原文查
