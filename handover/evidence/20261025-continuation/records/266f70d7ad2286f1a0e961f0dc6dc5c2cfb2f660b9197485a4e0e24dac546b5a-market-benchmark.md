# 市场对标：Houdini 自动化/AI 助手类项目（2026-08-25 调研）

对标目的：找出市面优秀项目的设计亮点，吸收进 houdini-bridge skill。
调研对象：fxhoudinimcp（最全面）、Houdini-Agent（功能最激进）、以及同类 MCP/CLI 项目。

---

## 1. fxhoudinimcp（healkeiser/fxhoudinimcp）— 我们已部分提取

**概况**：179 tools / 22 categories / 8 resources / 6 workflow prompts，
Houdini 20.5+（支持 21.0/22.0），`pip install fxhoudinimcp` 一行安装。
架构：hwebserver + hdefereval.executeInMainThreadWithResult（与我们的 bridge 相同思路）。

### 工具目录（22 类，我们逐项对标）

| 类目 | 它们的做法 | 我们的状态 |
|---|---|---|
| **Graph Intelligence**（4） | Atomic validated network building、network verification、node doc cards、cook profiling | ⚠️ 我们有 `node.create_batch` + `perf_profile.py`；**"validated network building"（建图即验证）值得吸收** |
| **Documentation**（2） | 对手册全文检索 + 按页取回（版本精确） | ✅ 已有 `help.query`/`help.search` |
| Scene Management（7） | 开/存/导入导出/场景信息 | ✅ 已有 |
| Node Operations（17） | 建/删/拷/连/布局/flags | ✅ 已有（`node.create` 支持 parms/inputs/xpos/ypos 一站式） |
| Parameters（11） | 取值/设值/表达式/关键帧/spare 参数 | ✅ 已有 |
| Geometry (SOPs)（12） | 点/面/属性/组/采样/最近点 | ✅ 有（分析脚本覆盖） |
| LOPs/USD（18） | stage 检查/prim/layer/composition/variants/lighting | ✅ 有（`inspect_stage.py` + usd 工具） |
| DOPs（8） | sim 信息/DOP 对象/step/reset/内存 | ✅ 有 |
| PDG/TOPs（10） | cook/work items/schedulers/依赖图 | ✅ 有 |
| COPs Copernicus（7） | 图像节点/layer/VDB | ⚠️ 未做（COPs 2.0 较新） |
| HDAs（10） | 建/装/管理/sections | ⚠️ 部分（`hip-convert.md` 覆盖格式，HDA 创建弱） |
| Animation（9） | 关键帧/playbar/帧范围 | ✅ 有 |
| Rendering（9） | 视口截图/render 节点/设置/启动渲染 | ✅ 有（`viewport.screenshot`） |
| VEX（5） | 建/改 wrangle/**校验 VEX 代码** | ⚠️ **"validate VEX"值得吸收**（我们目前靠 cook 后查错） |
| Code Execution（4） | Python/HScript/表达式/环境变量 | ✅ 有（`exec_python` 有 AST 白名单） |
| Viewport/UI（13） | pane 管理/截图/状态消息/**错误检测** | ✅ 有 |
| Scene Context（8） | 网络概览/cook 链/选择/场景摘要/**错误分析** | ✅ 有（`scene_info`+错误捕获） |
| **Workflows**（8） | **One-call Pyro/RBD/FLIP/Vellum setup、SOP chains、render config** | ⚠️ **最大的对标缺口**：它们把"一句话起 Pyro 场景"做成了 8 个 one-call 工具 |
| Materials（5） | 列出/检查/创建材质与着色网络 | ✅ 有（GLB 导入 + 材质组装脚本） |
| CHOPs（4） | 通道数据/CHOP 节点/导出到参数 | ⚠️ 弱 |
| Cache（4） | 列出/检查/清理/**写 file cache** | ✅ 有（`press_button` 触发 Save to Disk） |
| Takes（4） | 列出/创建/切换/参数覆盖 | ⚠️ 未做 |

### 它们值得我们吸收的三件事

**① Workflows 类目——"一句话起场景"**
fxhoudinimcp 把 Pyro/RBD/FLIP/Vellum 各自做成一个 one-call 工具：
```python
# 它们的设计（推测）
fxhoudinimcp.call("workflow.setup_pyro", source="/obj/geo1", preset="bonfire")
# 内部一次性创建 pyrosource + rasterize + pyrosolver + 输出，返回节点路径
```
我们的做法：先读 `references/workflows/` 指南 → 手工按 5-7 步建。
**吸收方案**：把 `references/notes/pyro-notes.md` 的"发射源三部曲"+ 调参顺序做成一个
`scripts/quick_pyro_setup.py`（hython 直跑），输入源节点路径 + 预设（bonfire/explosion/
smoke），输出一条完整 Pyro 链。**这是下一步最值得做的增强**。

**② Graph Intelligence 的 "validated network building"**
它们的原子化建图带验证：每建一个节点立即确认 inputs 接对、参数生效。
我们的 `node.create_batch` 已有批量+undo；**吸收方案**：批量建完立即对每个新节点做
`node.cook` + 错误上报（我们 rules 第 2 条已要求"改完 cook 检查"），可以加一条
**"建图后立刻对末端节点 cook 一次，输出错误摘要"** 的强制规则。

**③ VEX 校验**
它们提供 "validate VEX code" 工具（wrangle 写完先静态检查语法，不 cook 就报错）。
**吸收方案**：wrangle 的 code 字符串在 set 之前过一遍 `hou.VexNet` 或编译检查，
或者直接用 `node.cook` 后立即读 error 字段。短期做法：在 `scripts/` 加一个
`vex_syntax_check.py`（用 `hou.hscript("echo ...")` 或解析错误日志）。

---

## 2. Houdini-Agent（独立项目，544 stars）— 设计更激进

**概况**：AI-powered assistant for SideFX Houdini，自主多轮工具调用、
web 搜索、VEX/Python 代码执行、**Plan 模式**、**脑启发长期记忆**、**插件钩子系统**、
用户自定义上下文规则、ToolRegistry 集中管理 + 按模式控制访问。
仓库当前 404（可能删库或私有化），但设计思路值得记录。

### 它们值得我们吸收的四件事

**① Plan 模式（先出计划再执行）**
做复杂任务（如"搭一个爆炸+碎裂+渲染"全流程）时，先让用户确认执行计划，再动手。
**吸收方案**：我们 skill 的 rules 加一条——**"3 节点以上的网络构建先给拓扑图，等确认"**；
已在 `senior-discipline.md` 的"原子建图"精神上延伸。

**② 长期记忆 / 上下文规则**
它们有"记忆系统"记住用户的项目习惯（如默认渲染器是 Karma、单位是米）。
**吸收方案**：我们已用 `~/.workbuddy/memory/MEMORY.md` + 工作区 daily log 实现同等能力；
**可以在 SKILL.md 里加一条"跨会话记住用户的渲染器/单位/路径偏好"**。

**③ 插件钩子系统**
允许社区扩展自定义工具而不改核心代码。
**吸收方案**：我们 `scripts/` 目录就是事实上的插件目录；可以加一份
`references/scripts-index.md` 列出所有脚本+用法（部分已在 SKILL.md 的 Scripts 表）。

**④ ToolRegistry + 模式访问控制**
不同模式（只读/编辑/执行）开放不同工具集，防止误操作。
**吸收方案**：我们的 `exec_python` 已有 AST 白名单；可在 SKILL.md 加一条
**"危险操作（delete/cook 大场景/save）前必须 print 影响范围再执行"**。

---

## 3. 对标结论：我们的 skill 缺什么

| 优先级 | 缺口 | 建议动作 |
|---|---|---|
| 🔴 高 | **One-call 场景起建工具**（Pyro/RBD/FLIP/Vellum） | 写 `scripts/quick_setup_pyro.py` 等 4 个 |
| 🔴 高 | **VEX 静态校验** | 写 `scripts/vex_syntax_check.py` |
| 🟡 中 | **HDA 创建工具**（HDAs 类目弱） | 把 python-hda-scripts-notes.md 的创建流程脚本化 |
| 🟡 中 | **COPs Copernicus 类目** | 查 `help/copernicus` 补一份 |
| 🟡 中 | **Takes 类目** | 用 `hou.takes` 写 4 个小工具 |
| 🟢 低 | **Plan 模式 / 模式访问控制** | SKILL.md rules 补 2 条 |
| 🟢 低 | **CHOPs 类目** | 数据少，用得少 |

---

## 4. 已蒸馏到本 skill 的 fxhoudinimcp 内容

`references/workflows/` 的 31 篇指南就是从 fxhoudinimcp 提取的
（pyro/destruction/fluid/vellum/mpm/solaris/render/shade/tops/crowds/ocean/
heightfields/copernicus/ml/model/composite 等，含 Failure signatures + Order of work）。
那是 2026-08-24 完成的。这次对标是在那个基础上查漏补缺。

---

## 易错点

- **fxhoudinimcp 的工具数在快速迭代**（168→179 只用了几天），别硬抄工具列表，抄**设计思路**
- **Houdini-Agent 仓库已 404**，内容以调研时的描述为准，别当"还在维护"引用
- **"一句话起场景"工具的危险**：Pyro 预设不对会烧显卡，one-call 工具必须带 **预览帧 + 参数确认** 两步
- **VEX 静态校验不能代替 cook**：语法对≠逻辑对，cook 后仍要查错（我们 rules 第 2 条已强制）
