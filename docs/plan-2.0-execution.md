# Bridge Skills 2.0 — 现状审计与执行计划

> 历史执行快照：其中 DeepSeek/WorkBuddy 专用验收行已被当前 `DoubaoDesktopRoute` 的 UI 控制门和逐领域 Skill 符合性门取代。本文件只保留审计历史，不得作为当前支持证据。

审计日期：2026-08-29
审计对象：`<repo-root>/bridge-skills/`（git `main`，工作区含大量未提交 2.0 改动）
审计方法：静态代码审计（三路并行）+ **活体实测**（Houdini 21.0.631 / 22.0.368 / Nuke 17.0v1 真实调用）
证据约定：所有结论标注 `文件:行号`；活体结论标注实测命令与输出。

---

## 决策记录（2026-08-29）

| # | 决策 | 直接后果 |
|---|---|---|
| **A** | **模型传输首版改用 WorkBuddy，替换 ZCode；由 WorkBuddy 自身执行模型角色，不委托外部应用或子 Agent** | 移除最硬的外部依赖；但"媒体隔离"与"模型身份验证"从架构强制降级，见 §A |
| **B** | R1 暂不执行，先评审计划 | 本轮不改动正式代码，只更新计划 |
| **C** | rc.2 按原计划，**不含** R2（执行引擎重建） | rc.2 仍不可执行任何领域包；需在 rc.2 内追加"协议定义 + 字段级漂移测试"作为最小防漂移措施 |
| **D** | 参考素材先用内置确定性基准，烟雾主案例保留用户真实图片 | "16 个真实参考案例"改为"1 个真实参考 + 15 个确定性基准"，验收宣称须相应收敛 |

---

## A. WorkBuddy 传输：能力边界与验收口径变化

### A.1 角色映射

| 原计划角色 | 首版实现 | 说明 |
|---|---|---|
| HY3（Vision） | WorkBuddy 多模态视觉分析 | 直接读取冻结媒体副本，按视觉 JSON schema 输出组件/ROI/轮廓/细节尺度/材质/光照/运动线索 |
| DeepSeek-v4-flash（Planner） | WorkBuddy 在受限上下文内做 `select_action` | 只接收结构化文本状态，每轮一个虚拟工具 |
| `ZCodeBrokerGateway` | **不实现**，改为 `WorkBuddyTransport` + 编排器侧强制 | scratch 隔离、临时 settings、子进程工具禁用等**不再适用**（无子进程） |

### A.2 强制点迁移（本节是全篇最关键处）

ZCode 方案的隔离来自"模型跑在一个被阉割的子进程里"。WorkBuddy 方案没有子进程，因此**全部强制力必须落到编排器侧**。

**仍然有效（审计判定 A，已有真实实现）**：

- 命令白名单 `MODEL_SAFE_COMMANDS`（`commands.py:6-28`）+ 按状态暴露命令面（`service.py:915-972`）
- 单动作 / 未知工具 / 多动作整轮拒绝（`gateways.py:173-183, 315-316`）
- 模型不可自签 grant（`service.py:89-91` 使模型侧 verify 恒 False）
- 文本-only planner 拒绝图像入参（`gateways.py:167-168`）

**必须新增（原由子进程承担，改由编排器承担）**：

1. **Planner 载荷证明**：编排器计算并记录实际送入 planner role 的 payload 哈希，并落盘一条 `media_attached: false` 断言；planner 输出若引用了结构化状态中不存在的视觉细节 → 整轮拒绝。
2. **Identity 记录（非校验）**：记录 WorkBuddy 会话 id 与运行时上报的 model name，写入运行日志。**不做密码学校验**——我无法证明自己是所声称的模型。
3. **重试与 schema repair 下沉**：429/网络三次重试、JSON 一次 schema repair 由编排器实现（当前 0% 实现，见 §2 `gateways.py:50-64, 322-323, 437`）。这一项不因换 transport 而消失。
4. **去密钥请求/响应哈希**：照常落地（无密钥，成本更低）。

### A.3 无法闭环的验收项（必须如实标注，不得用假证据顶替）

| 原验收项 | WorkBuddy 传输下 | 处理口径 |
|---|---|---|
| 模型身份密码学校验（不匹配报 `MODEL_CAPABILITY_MISMATCH`） | **无法自证** | 降级为"运行时上报 identity 并落盘"，标注 `unverified-identity`，**不宣称完成** |
| 媒体不进入 Planner（架构级隔离） | **降级为过程性**：我已在上下文中见过参考图，无法撤销 | 编排器侧仍强制"不传入"；加 A.2.1 载荷证明与输出审计；标注 `procedural-isolation`，**不宣称架构级隔离** |
| 禁用 Bash/Edit/Browser/Computer Use/MCP | 不适用（无子进程） | 等价于"模型可调用的工具面被编排器穷举限制"，此项**可以宣称完成** |

**首版可宣称**：模型行为受编排器穷举约束，全部越界尝试（多工具、任意代码、自批审批、向 planner 传媒体）均被拒绝。
**首版不可宣称**：模型未接触参考媒体；模型身份已密码学验证。

这两项在文档中须标为**未完成门禁**，与计划 §6"若 ZCode 无法证明身份则门禁保持未完成，不得改用假模型或手写 evidence"的处理口径一致。

### A.4 收益

- 移除最硬的外部依赖（原风险 #1），R1-T1.5 从 go/no-go 降级为例行验证
- 免除 ZCode 应用发现、scratch 隔离、临时 settings、子进程工具禁用——约占原网关工作量的 40%
- 视觉分析质量大概率优于本地 `http://127.0.0.1:8000/v1` 端点
- rc.2 发布不再受外部依赖阻塞

---

## 0. 结论摘要

现状比计划描述的"合同完整但仅有拓扑脚手架"更差一层，实际是三层并存：

| 层 | 状态 | 说明 |
|---|---|---|
| 合同层 | 完整且质量高 | dataclass / schema / 状态机 / 因果声明式设计扎实，是真资产 |
| 执行层 | 拓扑脚手架 | 领域包节点图语义错误，FX 路径**结构性无法渲染出 EXR** |
| 证据层 | **存在伪造** | 桥接层在 DCC 未返回 gate 时默认伪造 `passed: True`；已有 v1 活体记录的元数据与产物不符 |

**活体实测结论：15 个 Houdini 领域包，在 H21 与 H22 上都是 0 个可用。**

| 探测状态 | 包数 |
|---|---|
| `UNSUPPORTED` | 12 |
| `INCONCLUSIVE` | 3（`lighting_camera_render_v1`、`material_lookdev_v1`、`rbd_destruction_v1`） |
| 可用于生产 | **0** |

**一个决定性的好消息（原计划未纳入）**：`hython` + `husk` + Nuke CLI 在 H21/H22/Nuke17 上全部可用，且可与两个 GUI Houdini 会话**并发运行**（Commercial license，无许可争用）。这意味着 §5 的验收 harness 可以建立在**无头批量执行**之上，而不是依赖交互式桥接会话——可脚本化、可并行、每次场景状态干净、可复现。这应成为 harness 的主干设计。

---

## 1. 活体实测基线（本次新采集）

### 1.1 领域包探测全量结果

实测命令：`POST http://127.0.0.1:{8100|8101}/api` → `["mcp.execute",[],{"command":"agent.fx.probe","params":{"domain_pack":""}}]`

| 领域包 | H21 | H22 | 节点可用 | 控制可用 | 缺失节点 |
|---|---|---|---|---|---|
| crowd_agents_v1 | UNSUPPORTED | UNSUPPORTED | 2/3 | 0/12 | solver:crowdsolver |
| explosion_composite_v1 | UNSUPPORTED | UNSUPPORTED | 3/5 | 2/11 | source:sphere; particles:popnet |
| hair_fur_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 1/9 | source:sphere |
| lighting_camera_render_v1 | INCONCLUSIVE | INCONCLUSIVE | 4/4 | 6/12 | — |
| material_lookdev_v1 | INCONCLUSIVE | INCONCLUSIVE | 1/1 | 8/11 | — |
| particles_v1 | UNSUPPORTED | UNSUPPORTED | 2/4 | 0/15 | source:sphere; solver:popnet |
| procedural_geometry_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 4/10 | source:grid |
| pyro_fire_v1 | UNSUPPORTED | UNSUPPORTED | 2/3 | 5/12 | source:sphere |
| pyro_smoke_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 9/12 | source:sphere |
| rbd_destruction_v1 | INCONCLUSIVE | INCONCLUSIVE | 4/4 | 2/11 | — |
| swarm_flocking_v1 | UNSUPPORTED | UNSUPPORTED | 2/4 | 0/7 | source:sphere; solver:popnet |
| vellum_cloth_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 5/8 | source:grid |
| vellum_softbody_grains_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 4/10 | source:sphere |
| water_flip_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 2/9 | source:sphere |
| water_ocean_v1 | UNSUPPORTED | UNSUPPORTED | 3/4 | 4/9 | source:grid |

**旗舰案例 `pyro_smoke_v1` @ H21 实测输出**：

```
state: UNSUPPORTED | node_contract_available: False
  source  sop  ['sphere']                  resolved=sphere              avail=False  missing=[['radx','radius']]
  solver  sop  ['pyrosolver','pyrosolver::2.0'] resolved=pyrosolver      avail=True
  output  sop  ['null']                    resolved=null                avail=True
  render_settings lop ['karmarendersettings'] resolved=karmarendersettings avail=True
controls unavailable: ['denoise_mix','density_scale','field_sharpen']
```

11/15 个包被同一个探测 bug 卡死（`source:sphere` / `source:grid`）。

### 1.2 tuple 参数 bug：**机理与原计划描述相反**

计划 §2 写"Tuple 参数按真实 `rad/size` 模板和分量处理，不再用错误的 `radx/sizex` 模板探测"。
**这个描述是错的，按字面实现会让系统更坏。** 用 hython 实测：

```
sphere parm templates: ['type','surftype','rad','t','r','scale', ...]
parm("radx") -> <hou.Parm radx in /obj/geo1/sphere1>     ← 可寻址
parm("rad")  -> None                                      ← 不可寻址

sphere: template 'rad'  Float numComponents=3  →  可寻址 parm: radx, rady, radz
grid:   template 'size' Float numComponents=2  →  可寻址 parm: sizex, sizey
```

真实机理：

- **parm template 名字** = `rad` / `size`（元组名），`FloatParmTemplate` **没有** `parmTemplates()` 方法可展开分量。
- **可寻址 parm 名字** = `radx/rady/radz`、`sizex/sizey`。
- 探测代码 `_fx_parm_template_names`（`plugins/houdini/_impl/houdini_bridge_addon.py:1053-1070`）取的是 **template 名**（`rad`），却拿去和**别名**（`radx`）比对 → 必然失配。
- 写入代码 `_set_first_parm`（`:677-698`）用的是 `node.parm("radx")` → **能成功**。

即："探测用 parm 名、写入也用 parm 名"才是对的；bug 是**探测侧错用了 template 命名空间**。正确修法是**探测改为基于可寻址 parm 名**（`node.parm(alias) is not None`），或把 template 按 `numComponents` 展开为分量名后再比对。**绝不是把别名从 `radx` 改成 `rad`。**

### 1.3 关键节点类型真相（hython 实测，H21 vs H22）

扫描 120 个候选名 × 6 个上下文。**H21 与 H22 仅 2 处差异**（`camera`、`copytopoints` 在 H22 额外可用），证明计划"H21/H22 共用主图 + 小版本适配表"的设计是对的——差异在**参数层**而非节点层。

对重建领域包最关键的几条（H21/H22 一致）：

| 计划/现有包假设 | 实测真相 |
|---|---|
| `pyrosolver` 单独作 SOP 解算烟雾 | `pyrosolver` 在 sop 与 dop 均存在，但**单独一个 SOP 不能解算**；需 `dopnet` + `smokeobject` + `pyrosolver::2.0`(dop) + `sourcevolume`(dop) + `gasresizefluiddynamic`(dop) |
| `popnet` 作 SOP 粒子网络 | **`popnet` 在全部 6 个上下文中都不存在**；`popsolver` 同样 MISSING。真实结构：`dopnet` + `popobject`(dop) + `popsource`(dop) + `popsteer*`(dop) |
| `dopimportfields` 取场 | **MISSING** → 用 `dopimport`(sop) 或 `dopio`(sop) |
| `constraintproperties` | **MISSING** → 用 `rbdconstraintproperties`(sop) |
| `flipconfigure` / `flipsourcevolume` | **MISSING**（是 shelf 生成的子网，非节点类型）→ SOP `flipsolver` + DOP `flipobject` + `volumesource`(dop) |
| `crowdsolver` 作 SOP | **MISSING as sop**；`crowdsolver` 仅在 dop。`crowdsource`/`agent`/`agentclip`/`agentlayer` 是 sop，`crowdobject`/`crowdstate`/`crowdtransition` 是 dop |
| `pyrosource` | 存在（sop），但当前包**完全没用到** |
| `motionpath` / `crowdpath` | MISSING |
| `guideskin` / `mtlxhair` | MISSING（H21 毛发材质需另行确认路径） |
| `poplifedeath`/`popcollide`/`popturbulence`/`popmetaball` | MISSING；可用替代：`popkill`(dop)、`popcollisionbehavior`(dop)、`popvop`(dop)、`popwind`(dop)、`popaxisforce`(dop)、`popattract`(dop) |

**重要方法论警告**：`hou.nodeType(cat, name)` 的存在性检查**不足以判定可用性**——部分 DOP 求解器类型只在特定父节点内才可解析。这正是计划"五层探测"要解决的问题，第 2 层（节点可创建）必须带**真实父节点**执行。

### 1.4 现有证据可信度：三条记录不可采信

| 记录 | 问题 |
|---|---|
| `outputs/live-validation/20260829T060000Z-nuke17-single/render/` | `final.0001/0002/0003.exr` 与 `preview.0001.exr` **四个文件 md5 完全相同**（`5163069177bc1886ff3e6e98c62f578f`，均 215714 字节）→ 是同一静态帧的拷贝，未真正按帧范围产出变化 |
| `outputs/live-validation/20260829T051000Z-h22-single/validation.json` | 声称 `final.0003.exr` = **130989** 字节，实测 **235741** 字节 → 元数据不是从产物计算出来的 |
| `outputs/live-validation/index.json` | `entries: []`、`generated_at: null`，自述"等 live harness 写入" |

Houdini 侧的 EXR 本身是真的（合法 OpenEXR 魔数 `76 2f 31 01`、640×360、H22 三帧 md5 互不相同）。**结论：产物层部分真实，证据层是手写元数据。** 计划 §5"旧 v1 真机证据继续保留"应限定为"保留产物、作废元数据，并在新 harness 下重跑"。

### 1.5 环境能力（原计划未纳入，建议作为 harness 主干）

| 能力 | 路径 / 状态 |
|---|---|
| Houdini 21.0.631 hython | `/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/bin/hython` ✅ |
| Houdini 22.0.368 hython | `/Applications/Houdini/Houdini22.0.368/Frameworks/Houdini.framework/Versions/22.0/Resources/bin/hython` ✅ |
| husk（Karma 无头渲染） | 两版本均有：`.../Versions/{21,22}.0/Resources/bin/husk` ✅ |
| Nuke 17.0v1 CLI | `/Applications/Nuke17.0v1/Nuke17.0v1.app/Contents/MacOS/Nuke17.0`（`-t` python / `-x` 执行 / `-F` 帧范围）✅ |
| 并发 | 两个 GUI Houdini（8100/8101）+ 两个 hython 同时跑通，license 为 Commercial，无争用 ✅ |
| GUI 桥接 | Houdini 8100/8101 已加载当前仓库源码插件（RPC 签名 `["mcp.execute",[],{command,params}]` 匹配）；Nuke 5653 为 `socketserver` 协议，与 Houdini 不同 |
| ZCode | `/Applications/ZCode.app` 与 `~/.zcode/cli` 存在；**仓库中网关代码 0% 实现**。按决策 A，首版**不使用**，改为 WorkBuddy 传输，详见 §A |
| WorkBuddy 视觉能力 | 可直接读取冻结媒体副本并输出视觉 JSON（本轮审计即以此方式读取 EXR/图片证据），可承担 HY3 role ✅ |
| WorkBuddy 无头执行 | 可通过 Bash 直接驱动 hython / husk / Nuke CLI 与桥接 RPC（本轮全部活体实测均由其完成）✅ |

---

## 2. 与计划的差距矩阵

判定：**A** 真实实现（有运行时强制力）/ **B** 仅合同层（字段存在、运行时不强制）/ **C** 缺失

### §2 核心合同与安全底座

| 计划要求 | 判定 | 证据 |
|---|---|---|
| `target.scenes.houdini` / `.nuke` 分离 | C | 仍单一 `target_scene_path`（`contracts.py:646-647`）；`target` 严格只允许 3 键（`:692`），传 `scenes` 直接报 `INVALID_SPEC` |
| v1 `scene_path` 兼容 | A | `contracts.py:768-774` 按 schema_version 分派 |
| `FrozenEvaluationContext` | C（类型）/ B（替代实现） | 类型不存在；`service.py:1468-1552` 有真实源冻结 manifest（逐字节 SHA-256 + `hmac.compare_digest` 复校 `:1561-1562`） |
| 相机矩阵/镜头/分辨率/OCIO/ACES/插件版本/包版本冻结 | C | manifest 只冻结 references/inputs/scene/seed/camera_hash/frame_range/fps/color_space |
| 调用者不得覆盖相机/种子/证据结论 | **C** | `service.py:356-363` 三个 frozen 字段**优先取调用方传入值**；不传 `camera_hash` 静默落为 `"unverified_camera"` 而非报错 |
| `ComponentGraph` 真实构建并参与路由 | C | `contracts.py:248-263` 定义，全仓库零生产使用；`domains.py:115` 实际只是 `components: tuple[str,...]` |
| `StageGraph` | A（构建）/ C（不参与路由） | `domains.py:267-295` 构建 + `:219-243` 环/反向依赖校验；但 `router.py:120-143` 完全不读它 |
| `CrossDccArtifactManifest` | C | 不存在；替代为 `ArtifactRecord`（`contracts.py:484-514`）+ `pipeline_artifacts` 表 |
| 谱系校验器（拒绝 reference 进入交付闭包） | **B** | `policy.py:129-163` 逻辑完整正确，但 `PolicyEngine` **全仓库零实例化**（仅 policy.py / 导出 / 测试命中） |
| `EvidenceRecord` 只能由 adapter 创建 | **C** | `contracts.py:335-352` 无 producer / evidence_id / 签名；`service.py:1401-1410` 直接反序列化模型 payload 的 `verdict`；`feedback.diagnose`（`:327-333`）允许模型提交 `supports/refutes` |
| Required gate 阻止 COMPLETED | A（v2）/ **C（v1）** | v2 链路封闭（`service.py:746-749, 2043-2047, 2110-2114`）；**v1 `engine.py:170, 189-191` 从不读取 `step.required`，跑完即 SUCCEEDED** |
| `INCONCLUSIVE` 无 COMPLETED 出边 | A | `pipeline_store.py:30` |
| `ANALYZING/PREVIEWING/CACHING/VERIFYING` 可恢复 | A（状态机）/ **C（恢复）** | 状态机真实（`pipeline_store.py:18-36, 228-233`）；`service.py:313-322` 的 resume 只是状态跳转，不重放 journal、不 reconcile |
| `operation_id` / dispatch journal / completion marker | C | 全部零命中；仅有 task 级 `idempotency_key`（`pipeline_store.py:166-171`） |
| 缓存 `.partial` 原子提交 | C | 不存在 |
| 输入漂移 → `APPROVAL_REVOKED` | A | `approvals.py:207-230` subject_hash 绑定真实生效 |
| **PARTIAL 死锁（计划未覆盖的现网 bug）** | — | `pipeline_store.py:32` `PARTIAL: frozenset()` 是终态，但爆炸场景主动进 PARTIAL（`service.py:531, 552, 568`），且 `task_resume` 不接受 PARTIAL（`:316`）→ 掉进去即死锁 |

### §3 RVT / 模型传输（首版 WorkBuddy，替换 ZCode）/ 因果诊断

| 计划要求 | 判定 | 证据 |
|---|---|---|
| `ZCodeBrokerGateway` | **C（0% 实现）** | 全仓库 `zcode` 仅命中 Windows 残留路径（`skills/houdini-bridge/scripts/undo_snapshot.py:8` 等 `C:/Users/<USERNAME>/.zcode/...`） |
| DeepSeek-v4-flash 接入 | B（直连，非 ZCode） | `gateways.py:210-326`，直连 `api.deepseek.com`，无 ZCode transport |
| HY3 接入 | B（本地端点） | `gateways.py:329-491`，`base_url="http://127.0.0.1:8000/v1"` 本地 OpenAI 兼容端点 |
| provider/model identity 校验 | B | 探针失败报 `MODEL_CAPABILITY_MISMATCH`（`:253`），但 provider 是**硬编码字符串**（`:254-262`），非响应回读 → 自证 |
| 隔离 scratch / 临时 settings / 禁用 Bash·Edit·Browser·MCP | C | 全部不存在 |
| 429/网络三次重试 | C | `gateways.py:50-64` 无任何重试 |
| JSON 一次 schema repair | C | 解析失败即报错（`:322-323, :437`） |
| 零/多/未知工具整轮拒绝 | **A** | `gateways.py:173-183, :315-316` |
| 去密钥请求响应哈希 | C | 不存在 |
| 硬编码凭据 / 读用户密钥 | 无（好） | `api_key` 必须注入，空则 `ValueError`（`:221-222, :341-342`）；`__repr__` 打码（`:231, :352`）；异常只带 `type(exc).__name__`（`:61`） |
| 本地候选审批面板 | C | `packages/` 下 grep `panel\|webbrowser\|tkinter\|flask\|http.server` 零命中；数据齐全（`contracts.py:442-453`）但只有 CLI 打印（`__main__.py:67-73, 162-163`） |
| 面板随机会话能力不写入模型可见状态 | C | 无此概念 |
| **双密钥分离 + 钥匙串** | **C** | 单一共享明文文件 `~/.bridge-skills/approval.key`（`houdini-bridge/paths.py:26`、`vfx-pipeline/paths.py:26`），`secrets.token_hex(32)` 写 0600 明文（`install.py:22-32`），非 Keychain；人类签名与缓存断言**共用同一把** |
| 生产模式禁用公开 grant CLI | **C** | `grant-cache`/`grant-experience` 无条件注册（`__main__.py:95-100, 184-189`），且支持 `--trust-proof` 命令行直传签名（`:99, :123-124`） |
| 复合效果逐分支签发（非通配） | **A** | grant 绑定精确 subject_hash（`approvals.py:222-230`），subject 含 component_id（`:45`），`request_id` UNIQUE（`pipeline_store.py:109`）→ 结构上不存在通配 |
| 领域包声明式因果医生（非统一乘数） | **A** | `causal.py:23-28` 核心无效果知识；原因族 `:136`、旁路探针 `:127`、方向/约束 `:189-200`、失效范围 `:202-204`、成本 `:215`、protected `:49,95` 全部落地 |
| 三方比较 reference+baseline+candidate | **C** | `VisualScorecard` 只有 before/after（`contracts.py:456-464`），无 reference 维度 |
| 15% 改善 / 30% 故障关闭 / 5% protected 容差 | **C** | 全仓库零命中。`verified = target_improved and not protected_regressions`（`:467-468`），`target_improved` 是**调用方传入的布尔值** |
| 视频原生能力单独探测 / `video_via_sequence_sampling` | C | 不存在 |
| 视觉结果及哈希真实传入 DCC | C | 仅存 metadata |

### §4 领域执行器

| 计划要求 | 判定 | 证据 |
|---|---|---|
| 版本化 `DomainGraphTemplate`（上下文/嵌套/多入多出/跨上下文导入/组件分支） | **C** | `NodeRequirement.input_role` 是单个 `Optional[str]`（`domain_packs.py:36`）→ 结构上不可能表达多输入 |
| 建链支持多输入 | **C** | `houdini_bridge_addon.py:1266` 恒 `node.setInput(0, source)` |
| `dop` 上下文 | **C** | `_fx_category`（`:1031-1035`）factories 只有 sop/lop/vop，**无 dop** |
| 跨上下文导入 | **被显式禁止** | `:1262-1263` `if node.parent() != source.parent(): raise BridgeCommandError("UNSUPPORTED_NODE", ...)` |
| 嵌套子网 | C | 仅 lop 类别临时建 subnet（`:1187-1195`），SOP 侧无 |
| 五层探测 | **1.5 层** | (a) 类型存在 ✅ `:1040-1050`；(b) 可创建 ❌ 探测期不调 createNode；(c) 端口兼容 ❌ 从不查 `maxNumInputs`/outputLabels；(d) 可写 ❌ 仅写入时检查 `:1619-1620`，可恢复 ✅ `:1286-1294`；(e) 只 cook 不渲染，且 `_fx_evidence_requirements` `:1411-1416` 无条件 `available: False` |
| 执行表由定义生成（消除双份漂移） | **C** | 三套手写表：`domain_packs.py:135-495`、`houdini_bridge_addon.py:61-407`、`domains.py:543-589`。节点层 0 漂移，但**控制字段已漂移**：`sample_quality` 宿主 `float`（`domain_packs.py:401`）vs 插件 `int`（`addon:308`），`2.5` 在宿主通过、插件静默截断为 `2`；现有测试只比 id 集合（`test_houdini_fx_domains.py:91-99`），抓不到 |
| FX 路径能渲染出 EXR | **C（结构性不能）** | `ReferenceEffectRecipe.steps()`（`recipes.py:113-146`）无 render 步骤；`_FX_PACKS` 无 `usdrender_rop`、无 `sopimport`；`karmarendersettings` 是悬空节点 |
| `nuke_composite_v1` 独立输入角色 | A | 6 个角色（`nuke_bridge/recipes.py:15-41`；`nuke_bridge_addon.py:221, 308-327`） |
| 按 alpha/效果类型选 over/plus | **C** | 硬编码 `"plus"`（`nuke_bridge_addon.py:563`）；`over`/`alpha` 在插件内零命中 |
| ACES / OCIO | **C** | `aces\|OCIO\|colorspace` 在 `nuke_bridge_addon.py` 中 **0 命中** |
| depth/vector 真实接入 | **C** | 只读进悬空 NoOp（`:591-602`），不参与合成 |
| 递归参考污染审计 | **A（全仓库最扎实）** | `_upstream_nodes` `:340-355` 真传递闭包；`_audit_composite_lineage` `:378-409` 元数据角色 + 冻结路径双判据；渲染前后重跑并阻断 `:743-746, :792-793, :802-805` |

### §5 经验系统与验收 Harness

| 计划要求 | 判定 | 证据 |
|---|---|---|
| 单入口 harness 九子命令 | **C（0/9 实现）** | grep `harness\|reconcile-cache\|revoke-evidence\|rebuild-index\|verify-index\|run-case\|checksums` 仅命中 `index.json:5` 的一句自述文字 |
| `outputs/live-validation/v2/<run-id>/` + `checksums.sha256` | C | 无目录、无文件（`find` 零命中） |
| `RepairExperience` 完整字段 | 部分 | 有：raw_feedback / issue / hypothesis / changes before-after / verified_result_hash / user_confirmed / domain.version（`contracts.py:565-578`）；**缺**：evidence_id、真实节点路径（存的是 stage node id 如 `"simulation"`）、reference/baseline/candidate 三份工件哈希、DCC build / 尺度 / 分辨率 / fps / OCIO / 输入类型 / 兼容范围 |
| 检索按领域/版本/DCC/尺度/媒体类型过滤 | 部分 | 仅 domain_id + domain_version + issue_signature（`pipeline_store.py:529-538`）；DCC build / 尺度 / 媒体类型 **C** |
| 强制重新诊断（不直接套参数） | A（结构性） | `ExperienceService` 只有 `request_promotion/promote/search`（`experience.py:19/23/40`），无 apply API |
| Evidence v2 门禁（重开 bundle 逐帧校验） | C | index.json 只有空壳 |
| 测试真实连接 DCC | **0%** | 22 个测试文件、约 100 个 test 方法，执行真实 DCC 的 **0 个**。mock 位置：`test_gateways_v2.py:22,38,43,54`；`test_vfx_pipeline.py:25,186,395,409,421,433,547`；`test_nuke_composite.py:27,38,106-112`（`sys.modules["nuke"] = SimpleNamespace(...)`）；`test_clients.py:32,57,78`（自起 127.0.0.1 回环假服务器）；`test_houdini_fx_domains.py:39` 直接返回 `"houdini_version": "contract-only"` |

---

## 3. 五个阻塞性发现（会改变计划顺序）

### F1 — 桥接层默认伪造 gate，必须先止血

```python
# nuke_bridge/tasks.py:38
gates = data.get("gates") or [{"name": step.identifier, "passed": True, "details": data}]
# houdini_bridge/tasks.py:54
gates = list(data.get("gates") or [{"name": step.identifier, "passed": not bool(data.get("errors")), ...}])
```

DCC 没返回 gate 时，"没有证据"被等价为"验证通过"。插件侧另有 8 处硬编码 `passed: True`（`houdini_bridge_addon.py:799, 972, 1005, 1351, 1637, 1728, 1807, 1819`；`nuke_bridge_addon.py:626, 720, 758, 781, 821, 842, 867, 885`）。

**后果**：在修掉它之前跑任何活体验证，得到的都是"绿灯套假证据"。这是最高杠杆的一处修复，且成本极低。**必须排在 R1 第一位。**

### F2 — FX 路径结构性无法渲染

三个独立的结构性缺口叠加：无 dop 工厂类别、跨上下文连接被显式禁止（Karma 必经 sopimport）、FX recipe 无 render 步骤。当前 `sphere → pyrosolver → null` 在语义上就不可能产生密度场。

**后果**：计划 §6 第 2 步"完成基础黄金链及烟雾纵向闭环"不能只补参数，必须重建执行引擎。

### F3 — 领域图不只是表达力不足，是语义错误

实测显示包定义引用了不存在的节点（`popnet`）、用了错误上下文的节点（`crowdsolver` 作 sop、`rbdbulletsolver` 作 sop 无 dopnet）、把多输入求解器表达成单链（Vellum 需 geo+constraints+collider 三路、Ocean Evaluate 需 geometry+spectrum 两路、Copy to Points 需双路）。

**后果**：§4 的每个包都需要按真实 Houdini 拓扑重写，工作量大于"加字段"。

### F4 — 验证子系统没有度量

`VisualScorecard.verified` 是调用方传入的布尔（`contracts.py:467-468`），15%/30%/5% 三类阈值**一行代码都没有**。整个"真实验收"的价值主张悬空。

**后果**：在 R6 之前，任何"验证通过"都不具备技术含义。

### F5 — 验收 harness 零实现，且现有记录不可信

九个目标子命令一个都没实现；已有 7 次运行中至少 2 次的元数据与产物不符（§1.4）。

**后果**：计划 §6 第 7 步"运行全部 v1/v2 软件回归"目前**零信号**——测试全绿不代表任何领域包能跑。必须先有 harness，回归才有意义。

---

## 4. 轮次计划

轮次编号 `2.0-R1` … `2.0-R9`。每轮出口判据均为**可机器校验**，不是主观判断。

### 2.0-R1 — 真相基线（止血 + 环境验证 + WorkBuddy 传输例行验证）

| 任务 | 内容 |
|---|---|
| T1.1 | 桥接层禁止伪造 gate：`nuke_bridge/tasks.py:38`、`houdini_bridge/tasks.py:54` 改为"无 gate → `INCONCLUSIVE` 并失败"；清理 16 处硬编码 `passed: True` |
| T1.2 | 按 §1.2 的**真实机理**修 tuple 探测：探测改用可寻址 parm 名（`node.parm(alias)`），或按 `numComponents` 展开 template 名 |
| T1.3 | 删除 `_FX_LIVE_VALIDATION` 常量（`addon:32`）与断言其为 False 的测试（`test_houdini_fx_domains.py:127`），成熟度改由证据推导 |
| T1.4 | 隔离 4 条不可信 v1 记录（Nuke 四帧同 md5、H22 字节数不符），标记 `quarantined` 而非删除 |
| T1.5 | ~~ZCode 能力 go/no-go~~ → **WorkBuddy 传输例行验证**（决策 A，不再是阻塞项）：确认可经 Bash 稳定驱动 hython/husk/Nuke CLI 与桥接 RPC；确认视觉分析可产出符合视觉 JSON schema 的结构化输出；确认多轮调用下 payload 哈希可稳定落盘 |
| T1.6 | 时长基线测量：用 hython + husk 跑一次 512px / 48 帧 / 24fps 的真实烟雾解算 + Karma 渲染 + EXR 输出，记录墙钟时间（决定全量验收是否需要并行批处理） |
| T1.7 | 全量节点类型真相表：扩展 §1.3 扫描，**第 2 层探测带真实父节点执行**（解决 `popsolver` 等"存在性检查失效"问题），产出 `docs/node-ground-truth.md` |

**出口判据**：
- `grep -rn '"passed": True' plugins/` 中不再有**无校验**的硬编码门（允许 `:1637` 一类有实测 before/set/after 的）
- 15 个包在 H21/H22 的探测中，不再出现"因探测代码 bug 导致的假失败"（`source:sphere` / `source:grid` 全部 `available: True`）
- `docs/node-ground-truth.md` 覆盖全部 16 个包所需的全部节点类型，每项标注 context 与"可创建"验证结果
- T1.5 有例行验证结论（决策 A 下不再是阻塞项）；T1.6 有数字
- `WorkBuddyTransport` 接口定义落地（含 A.2 的载荷证明与 identity 记录字段），使其后续可替换为 ZCode 而不改动编排器

### 2.0-R2 — 领域图协议 v2 + 执行引擎重建（按决策 C 拆为 R2a / R2b）

> **R2a**（并入 rc.2）：协议定义 + 校验器 + 字段级全等漂移测试，不改执行引擎。
> **R2b**（顺延 rc.3）：下方全部执行引擎重建工作。
> 拆分理由见 R5 下方"决策 C 已定"注释。

- `DomainGraphTemplate`：版本化、obj/sop/dop/lop/vop 上下文、嵌套子网、节点角色、候选类型、初始化 preset、版本条件、显式 `source_role/source_output → target_role/target_input`、多入多出、跨上下文导入、组件分支、必需参数、可写控制、输出字段/属性/AOV、缓存节点、工件类型
- 执行引擎重建：dop 工厂、父上下文解析（替代 `:1187-1195` 的 lop-only 逻辑）、多输入连线（替代 `:1266` 的恒 0 号口）、跨上下文导入（解除 `:1262-1263` 的硬禁止，改为显式声明式）
- 五层探测全部实现，任一层缺失即不得返回 `SUPPORTED`
- 执行表由领域定义生成；删除 `houdini_bridge_addon.py:61-407` 手写镜像；漂移测试改为**字段级全等**（value_type / 范围 / 别名 / 节点类型 / input_role），确保其能抓到 `sample_quality` 式漂移
- 版本适配表（H21/H22），基于 T1.7 实测差异

**出口判据**：`procedural_geometry_v1` 在 H21 与 H22 上真实构建 Copy-to-Points **双输入**网络（源几何 + Scatter 点），通过五层探测，cook 成功；字段级漂移测试在人为注入 `sample_quality` 漂移时**必须失败**。

### 2.0-R3 — 基础黄金链（4 包）

`procedural_geometry_v1`、`material_lookdev_v1`、`lighting_camera_render_v1`、`nuke_composite_v1`

- FX recipe 增加 render 步骤；Karma CPU/XPU 能力选择；真实 EXR/AOV 输出
- Nuke：按 alpha 与效果类型实现 over/plus 选择（替换 `:563` 硬编码）、完整 ACES/OCIO、depth/vector 真实接入主链
- 修复 `material_lookdev_v1` 单节点问题（当前只有 `mtlxstandard_surface`，无 materiallibrary / assign / OUT，材质不作用于任何几何体）
- 修复 PARTIAL 死锁（`pipeline_store.py:32`）

**出口判据**：每个包 ≥1 次真实 H21 运行 + ≥1 次真实 H22 运行（Nuke 包为 Nuke17），产出真实 EXR，逐帧 md5 互不相同，`index.json` 写入不可变条目且通过重开校验。

### 2.0-R4 — 冻结上下文 + 证据谱系 + 恢复

- TaskSpec `scenes.houdini` / `scenes.nuke` 分离，v1 兼容保留
- `FrozenEvaluationContext` 补齐相机矩阵/镜头/分辨率/OCIO 配置哈希/ACES role/插件与包版本；**强制拒绝**调用方覆盖（`service.py:356-363` 反转为报错）
- `operation_id` + dispatch journal + completion marker + reconcile；resume 从状态跳转升级为真正续跑
- `EvidenceRecord` 增加 evidence_id + producer 签名；模型侧 `feedback.diagnose` 不再接受 `supports/refutes` verdict
- `CrossDccArtifactManifest` + 把 `policy.py:129-163` 的谱系校验器**接入生产**
- 关闭 v1 `engine.py` 的 `Step.required` 空洞（`:170, 189-191`）
- 缓存 `.partial` → 原子提交

**出口判据**（对抗测试）：模型尝试覆盖 seed/相机/verdict → 全部被拒；含 reference 的谱系 → delivery 被拒；缓存中途 kill 进程 → resume 后恰好完成一次、不重复求解；输入漂移 → `APPROVAL_REVOKED`；PARTIAL 可恢复。

### 2.0-R5 — WorkBuddy 传输 + 审批面板 + 视觉主流程 → **发布 2.0.0-rc.2**

- `WorkBuddyTransport`（决策 A，替换 `ZCodeBrokerGateway`）：视觉 role 直接消费冻结媒体副本；planner role 只收结构化文本；编排器侧实现 429/网络三次重试、JSON 一次 schema repair、去密钥请求/响应哈希、会话 id 与运行时上报 model name 落盘
- **Planner 载荷证明**（A.2.1）：payload 哈希 + `media_attached: false` 断言落盘；输出引用状态外视觉细节即整轮拒绝
- 双密钥分离 + macOS Keychain；生产模式禁用公开 grant CLI；本地候选墙面板
- Vision-first 顺序：冻结来源 → 视觉分析 → ComponentGraph → 领域选择 → StageGraph → DCC baseline → 诊断 → 候选
- `ComponentGraph` 真实构建、持久化并**参与路由**（当前零使用）

**出口判据**：多工具 / 任意代码 / 自批审批 / 向 planner 传媒体 → 全部拒绝；零调用与多调用 → 整轮拒绝；载荷证明可复现。
**明确不宣称**：模型身份验证（标 `unverified-identity`）、架构级媒体隔离（标 `procedural-isolation`）——见 §A.3。

> **决策 C 已定：rc.2 不含 R2 执行引擎重建。** 记录后果与最小缓解：
>
> - **后果**：rc.2 仍无法执行任何 FX 领域包，性质上是"合同完整但不可执行"的第二个版本。领域包执行能力顺延至 rc.3。
> - **最小缓解（建议纳入 rc.2，成本远低于引擎重建）**：把 R2 拆为 **R2a / R2b**。
>   - **R2a（并入 rc.2）**：只做 `DomainGraphTemplate` **协议定义 + 校验器 + 字段级全等漂移测试**（抓 `sample_quality` 式漂移）。不改执行引擎，因此不解锁任何包，但能**立即冻结两份手写表的进一步漂移**（`domain_packs.py:401` float vs `addon:308` int 目前仍在 CI 全绿下存活）。
>   - **R2b（顺延 rc.3）**：dop 工厂、父上下文解析、多输入连线、跨上下文导入、五层探测。
> - 若 rc.2 连 R2a 都不含，则 R2b 开工时两份表会继续漂移，返工成本随包数量线性增长。

### 2.0-R6 — 因果度量 + 烟雾纵向闭环

- 三方比较 reference + baseline + candidate；**15% 主指标改善 / 30% 故障差距关闭 / 5% protected 容差**写入代码并有单测
- Metrics adapter 成为 evidence producer
- 烟雾三因注入：simulation 模糊（体素/源场/细节不足）、Karma 模糊（volume step/采样/滤镜/降噪）、Nuke 模糊（blur/denoise/defocus/错误锐化链）
- 经验系统补齐字段（evidence ID、真实节点路径、三份工件与指标哈希、DCC build、尺度、分辨率、fps、OCIO、输入类型、兼容范围）与多维检索

**出口判据**：同一句"太模糊"三因分别定位到三个不同阶段，且只重算对应分支；不达阈值的候选**由代码拒绝**（非断言）；用户不保存经验时任务仍 `COMPLETED` 且记录 `experience_saved=false`。

### 2.0-R7 — Pyro / 粒子 / 水体（5 包）

`pyro_fire_v1`、`particles_v1`、`swarm_flocking_v1`、`water_ocean_v1`、`water_flip_v1`
（POP 需用 `dopnet + popobject + popsteer*` 真实拓扑，见 §1.3）

### 2.0-R8 — Vellum / Crowd / 毛发 / RBD（5 包）

`vellum_cloth_v1`、`vellum_softbody_grains_v1`（softbody 与 grains 两个 variant **都通过才算包通过**）、`crowd_agents_v1`、`hair_fur_v1`、`rbd_destruction_v1`
（Crowd 缺 agent/clip、布料缺拓扑、毛发缺 skin/guides 时进入 `AWAITING_INPUT`，只问一个最关键缺项）

### 2.0-R9 — 爆炸复合 + 全量验收 + 发布 2.0.0

- `explosion_composite_v1` 改为组件编排器：Fire/Smoke/Shockwave/Particles/RBD 各自用已验收包，独立 EXR + component matte + depth/vector + 缓存，Nuke 按 manifest 汇合，逐分支独立 grant + 原子 composite commit
- Live harness 九子命令全部实现，建立在 hython + husk + Nuke CLI 无头批量之上
- 30 个 H21/H22 领域运行 + 全部 Nuke 交付 + **1 个真实参考（烟雾）+ 15 个确定性基准**的故障案例（决策 D）
- Evidence v2 校验器自动推导全部 16 包为 `supported`；**代码与包版本变化自动失效旧证据并追加 tombstone**

---

## 5. 自审：风险、边界与盲点

### 风险（按严重度）

1. ~~**ZCode 是硬性外部依赖**~~ → **已由决策 A 解除**。替换为下列新风险：
   - **1a. 媒体隔离不可验证（新增，严重）**：WorkBuddy 传输下，我已在同一上下文中见过参考媒体，无法撤销。编排器只能保证"不传入、且拒绝引用状态外视觉细节的输出"，**不能保证规划决策未受视觉信息影响**。这削弱了"弱模型受限规划"这一设计前提的证据力。缓解手段见 §A.2.1，但**无法通过机器验收闭环**，须在文档中持续标注为未完成门禁。
   - **1b. 模型身份不可自证（新增）**：无法密码学验证"我是所声称的模型"。降级为运行时上报并落盘，标注 `unverified-identity`。
   - **1c. 单点耦合（新增）**：首版把传输与编排耦合在同一执行体。缓解方式是把 `WorkBuddyTransport` 做成可替换接口（已列为 R1 出口判据），使 ZCode 后续可直接替换而不动编排器。
2. ~~**HY3 走本地端点时 identity 校验意义有限**~~ → 决策 A 后 HY3 端点不再是首版路径；该风险随 ZCode 一并移出首版范围。若后续恢复 ZCode 路径，本条重新生效。
3. **全量验收时间未知。** 30 个领域运行 × (解算 + 渲染) 的墙钟时间在 T1.6 之前是盲区。若单域单次耗时过长，需要并行批处理策略，而并行又会引入缓存/许可/磁盘竞争。T1.6 必须先出数字。
4. ~~**15 个非烟雾领域的真实参考素材尚未落实**~~ → **决策 D 已解决**：改用内置确定性基准。但验收宣称须同步收敛——原计划"16 个真实参考案例"改为**1 个真实参考（用户烟雾图片）+ 15 个确定性基准**。`docs/domain-support.md` 与最终发布说明不得把基准资产验收描述为"真实参考验收"。
5. **Windows 残留路径散布在 skills 脚本中**（`C:/Users/<legacy-user>/.zcode/...`），代码从 Windows 迁移而来，这些脚本在 macOS 下会失效，属于隐性技术债。

### 边界（本计划不做）

- 第三方 HDA、求解器、渲染器、Nuke gizmo 不进入完成矩阵（沿用计划决策）
- 不承诺从任意普通几何自动恢复制作级输入（Crowd agent/clip、布料拓扑、skin/guides）
- 轻量验收只证明 512px / 48 帧档位，文档不得宣称已验证 1080p 或影视制作质量
- **首版不得宣称**（§A.3）：模型身份已验证；媒体未进入规划模型（架构级隔离）；15 个基准领域已通过"真实参考"验收
- 本轮只做审计与计划，不改任何正式代码（工作区未提交改动保持原样）

### 盲点（诚实列出）

- **`hou.nodeType()` 存在性检查不完备**：部分 DOP 求解器只在特定父节点内可解析，`popsolver` 等"MISSING"可能是扫描方法局限而非真的不存在。已在 R1-T1.7 用"带真实父节点创建"的二级探测兜底。
- **未实测真实烟雾解算的端到端时长与画质**：T1.6 尚未执行，R3 之后的排期依赖该数字。
- **Nuke 端协议与 Houdini 不同**（`socketserver` vs HTTP），本次只确认了端口在监听，未做端到端调用验证，R1 需要补。
- **未审计 `skills/` 下大量参考文档**（约 5 万行）与 `docs/` 的一致性；文档与实际能力可能存在第二重漂移。
- **未验证 hython 与 GUI 会话同时操作同一 .hip 文件的冲突语义**；harness 若复用 GUI 的 hip 路径会有竞态，建议 harness 强制独立 hip/nk 路径（与计划 §5 一致）。

---

## 6. 决策状态

| # | 决策点 | 结论 | 落地位置 |
|---|---|---|---|
| D1 | 是否立即开工 R1 | **暂不执行，先评审计划** | 本轮未改动任何正式代码 |
| D2 | rc.2 是否包含 R2 | **按原计划，不含**。R2 拆为 R2a（并入 rc.2）/ R2b（顺延 rc.3） | §4 R2、R5 注释 |
| D3 | 15 个非烟雾领域的参考素材 | **先用内置确定性基准**，烟雾主案例保留用户真实图片 | §5 风险 #4、R9、边界 |
| A | 模型传输 | **WorkBuddy 替换 ZCode，由 WorkBuddy 自身执行** | §A、R1-T1.5、R5、§5 风险 #1 |

### 评审通过后我接下来会做什么

按你的"你自己执行"，R1 由我直接跑，不委托子 Agent：

1. T1.1 → T1.7 顺序执行，每完成一项给出**可复现的验证输出**（不是自述）
2. R1 出口判据逐条机器校验，不通过就停在原地并说明原因
3. 完成后交付：`docs/node-ground-truth.md`、时长基线数字、15 包探测前后对比表、WorkBuddy 传输验证记录
4. 交你核验后再进入 R2a
