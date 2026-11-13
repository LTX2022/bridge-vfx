# 全域修复增量与完成边界（2026-10-09）

本页记录本批实际改动和剩余条件，不能替代全 16 域 M1 接收。原始材料位于 `outputs/all-domain-20261009/`，不覆盖旧日志。未自动提交或推送本批代码。

## 目标与当前边界

Bridge 的总目标是把参考观察、业务控制、可编辑 Houdini/Nuke 工程、反馈和可信渲染合成连接起来；执行核心独立于模型，Plugin/MCP 是接入层，Skill 和私有上下文提供使用及业务知识。

用户批准范围仍是全 16 域 M1、20 项控制定义和 B 组合方案。必须保留 48 个需求案例及两条组合，扩展分支矩阵不缩小这个范围。Windows 软件验证使用项目 Python 3.11.9 和显式底层 HOM/USD/传输/进程替身。真实 Houdini、Nuke、HY3、模型、仿真、缓存、渲染、视觉及生产验收均 NOT_RUN；macOS 待目标机器复验。

## 本批实现

- P02：共用封存计划和完整参数/驱动/门控快照；从独立基准大小、任务 seed 和 stable ID 推导百分比随机范围；实际参数读回、pscale/copy 消费采集和回滚。重建已登记对象保留其随机状态，不强制改回 const。原生随机分布、跨帧/新 PID 和完整实例变换仍缺证据。
- A01：使用同版本 `Sop/volumewrangle`，只限制 flame 场的几何高度；基准高度、方向、源几何和输入版本必须显式且独立验证。私有恢复快照绑定当前签发者，程序写后从真实参数及 registration 读回。当前可证明参数/程序，动态字段生产、下游和新 PID 重开仍未闭合。
- R05：仅在初始事件、实际 packed piece ID/v/w/active 和 solver 门控成立时生成速度偏移；保留角速度，程序与基准一起事务登记。混合激活控制及缺失原生事实在写前拒绝；尚不证明整个刚体生命周期或其余五项控制。
- 正式保存：每次生成独立 HIP 和 typed operation，核对 live PID/nonce/epoch、当前冻结源、原件 producer store、实际 HIP/快照字节、scene contract 和图依赖，然后才登记 savedSceneID。
- 失败恢复：逐项汇总领域异常，继续尝试其他项及 manifest 恢复；未执行 A01 快照释放，恢复失败时保留原件。undo 的构造、进入和退出也纳入候选事务。
- readiness：已完成原生子操作与承载进程的成功退出分别核验；仅完整校验过的 primitive 原件允许非零 signed stop，默认 render/job 仍要求成功退出。PID、attempt、签名、child wait、Windows Job 清空和缺项规则保留。
- 底层输出替身：只呈现实际作者写入的 USD RenderVar/RenderProduct 属性及名称/类型；不填补颜色或 alpha 默认值。

## 为什么推进慢

当前任务同时包含修缺陷、补原生合同、领域实现和建立全链路验收。一次软件函数通过不等于对应领域完成；某些同版本接口及场景基准缺失又无法用猜测代替。共同颜色/alpha 缺口阻断多个登记/合成案例，使多域重复触发同一个失败。

执行本身也有可优化项：本批 ignored 测试启动器曾缺 Windows multiprocessing 主入口保护，已修正并保留失败日志；标准 unittest 会收集被其他模块导入的 fixture TestCase，导致同 ID 的昂贵宿主测试重复执行。标准 runner 已仅去除能证明原模块完整收集的普通 fixture 别名，保留自定义 load_tests、参数化、独立子类及 imported-only 用例。最终只读发现为 1622 个实例/1610 个唯一 ID → 1610 个实例/1610 个唯一 ID，零唯一用例丢失；删除的是重复的 ProductionTaskHostsTests 12 方法，其中一项包含两版本多域进程循环。没有单方法计时，不能声称确定加速比例。

全量也暴露了旧 OperationRunner AST 夹具遗漏当前 producer helpers、假 operation ID 不符合真实边界，以及旧产品测试要求已实现控制仍永久 BLOCKED。现已复用实际 helper/ID 派生、明确 UTF-8，并以 Git 基线保护未变合同字段及全部批准定义；没有降低生产校验。这些测试维护问题不能归因于原生事实缺失。

GraphJobRecovery 的旧进程夹具还在正常路径用上层 `_FakeAddon`，没有当前 root-create producer 回执；因此测试在首次操作就停止，丢回复和写 journal 前崩溃的故障点根本没有执行。现已改用实际 addon 与已有底层 API 夹具，在自有运行目录保留真实 producer 原件和监督身份；不手造成功回执。实际负结果退出 2，正常结果退出 0。正常恢复、两项故障及该模块 29 方法均已通过。这关闭的是过时软件夹具问题，不证明完整领域生命周期。

这些原因要求把“软件可执行”“领域语义充分”“正式证据闭合”“真实/视觉/生产接收”分别记录；不能把持续增加测试替身视为消除原生事实缺口。

## 未完成的全域范围

| 域 | 下一项具体闭合条件 |
|---|---|
| Pyro smoke/fire | 完整原生场生产和实际消费；A01 的显式源/高度基准、字段上下游、持久化和新实例证据 |
| FLIP | A02 内部碰撞场分辨率与 A03 passes 的合法同版本节点/端口/字段、SDF 和边界值；粒子到表面全链 |
| RBD | R01–R04/R06 的尺度/分布/冲量合同及原生载体；R05 初始事件和实际求解消费；保存、停止、新 PID 生命周期 |
| Particles | P01 发射方差、P03 collision radius、P04 trail、P05 renderer velocity 绑定；P02 随机分布、跨帧和新实例稳定性 |
| Swarm | 在已有 S01/S02 有限证据上闭合该域正式作业/恢复/产物；不重复已经批准的产品定义 |
| Ocean | O01 角宽到实际谱偏置的有依据转换；正式保存/执行/产物生命周期 |
| Procedural geometry | G01 统计散布、G02 原生旋转属性、G03 变形程序及独立输入基准/实际下游 |
| Crowd | 当前两动画状态、路线和秒制过渡对应的完整正式输出/恢复 |
| Cloth / softbody / grains / hair | 正式 per-case 控制覆盖、实际 producer、保存/新实例与恢复；软体和颗粒分别断言 |
| Material / lighting | 绑定与输出配置同时保持；当前 HIP 的实际 Driver 消费；可信颜色/alpha/逐帧完成事实和正式登记 |
| Nuke | 可信上游 registry 产物、确切帧/布局/颜色/alpha、持久输出及恢复；降噪双 producer 与输出登记 |
| Explosion / 两条组合 | 使用已批准 B 方案及具体场景输入，跨域真实 operation/artifact/版本/内容依赖进入合成 |

20 项定义中，A01/P02/R05 新增的是有条件的载体及有限读回，不能作为完整控制接收。除已有 Swarm 有限证明外，其余 18 项仍各有实现或生命周期缺项。共同输出缺口是实际 OCIO/产品/AOV/filter/alpha 和不可变逐帧 EXR 完成读回，不能在 consumer 生成 AVAILABLE 或以格式猜预乘。

## 下一轮执行顺序

1. 以本批最终 SHA、原始日志和独立复核收口当前已发现的代码缺陷。标准全量中失败及跳过逐项分类，历史或源码变化中的运行不作最终同源码 PASS。
2. 补共同输出 producer 的原生事实和真实文件完成采集，再验证登记重试只补同一操作、Nuke 消费最新保存 SHA。缺真实阶段授权时仅做允许的静态/软件验证，保留真实 NOT_RUN。
3. 按上表并行实现剩余载体；每项先取得合法接口及显式输入，才实现写入/读回/事务/保存/新实例。已批准语义不重新询问。
4. 用同一正式生成入口执行每域所有语义控制、恢复和 48+2 案例；缺证据的行继续 BLOCKED。独立复核、当前安装包生命周期和 macOS 复验分别收口。

## 证据状态

| 命令/材料 | 实际结果及适用范围 |
|---|---|
| `software-full/standard-20261009-161206.log`，`tests/run_tests.py` | 1579 方法，42 failure entries、62 error entries、32 skips，2493.088 秒，退出 1；wrapper 2494.674 秒。在最终复核整改前启动，期间源码变化，属于诊断全量，不是最终同源码接收 |
| `final-affected.json/.log` | 144 方法，0 failures、3 errors、0 skips，source_unchanged=true，退出 1。1 项是随后修复的菜单容器守卫；另 2 项是主代理调用不存在的恢复方法名。该命令保持失败，不改写为通过 |
| `final-particle-menu.json/.log` | 60 方法，4 个失败子断言集中在同一新增 guard 方法，2 个旧 Ocean 静态材料缺失子测试跳过，source_unchanged=true，退出 1。正常 tuple/list 兼容成立；无效输入在更早的合法性门控被拒绝，测试原先断言了错误的拒绝码。只修正测试对应码，再运行 guard 组 |
| `final-staged-guards.json/.log` | 10 方法，0 failure/error/skip，2.313 秒，退出 0、源码前后一致；含同内容 tuple/list 接受及不同 token、非法布尔表示拒绝，HMAC/完整冻结没有放宽 |
| `review-tests/candidate-repairs-canonical-20261009-164207.log` | 11 方法全部通过，19.984 秒，退出 0；真实 addon 与底层 API 故障注入覆盖 rollback 汇总、P02 重建、A01 原件保留/释放、manifest 恢复及 undo 构造/进入/退出。之后的 menu 组也执行了这 11 方法并正常通过，但整个组保持其真实退出 1 |
| `final-formal-recovery.json/.log` | 正确入口的 2 方法全部通过，37.063 秒、退出 0、源码前后一致；不将前次错误方法名算为执行 |
| `final-owner-case.json/.log` | 最终 production 源上的实际 Python/TCP 生成入口、提交后中断及控制端恢复，1 方法，19.641 秒、退出 0、源码前后一致；当前 HIP typed 保存成立，登记依然 BLOCKED，不重复建图冒充恢复 |
| `flip-rbd/optional-carrier-final-20261009-170110.log` | 当前 RBD host 的 12 方法全部通过，0 failure/error/skip、退出 0；未登记的可选 carrier 身份缺口仅返回未修改状态的 advisory，存在 basis/program 或实际申请 R05 仍严格拒绝错误身份 |
| `legacy-fixture/corrected-targeted.*`、`fixture-dependent-processes.*` | 42 + 4 方法全部通过，0 failure/error/skip；当前真实 helper 和 ID 派生，含受控进程死亡/恢复。不是完整全量 |
| `legacy-fixture/graph-helper-module-final.json/.log` | 29 方法全部通过，0 failure/error/skip、37.475 秒，退出 0、观察源码前后一致；实际 addon 加底层 API 和自有 Python 进程，覆盖完成后控制端持久化失败恢复、丢回复、journal 提交前崩溃、残留子孙、篡改和停止未知。此前正常 1 方法及两项故障也各自通过，属于重复定位验证，不相加为额外覆盖 |
| `product-contract/after.log`、`RESULT.md` | 5 方法全部通过；精确保护 20 项定义，只有明确实现字段采用逐字段豁免，其余合同和缺原生事实拒绝规则保留 |
| `discovery/final-latest.json`、`loader-tests-final.*` | 只收集不执行时唯一 ID 覆盖完全相同；12 个发现器行为测试全部通过 |

原始失败和跳过分别留存，不跨源码相加为一个全绿数量。最终源码未重跑标准全量；已知正式产物/恢复缺项仍在，不能把去重后的收集结果视为执行。跳过的旧 Ocean 静态材料和其余历史 macOS/安装缺项不能算 PASS。

GraphJobRecovery 夹具结果限定 Windows；POSIX 的 `test_graph_job_recovery.py` 仍有直接 Popen、绕过实际 supervisor 绑定的后代进程分支，需适配后在目标机器复验，不能继承 Windows PASS。具体诊断、源码 SHA 和实际正常/故障退出码见 `legacy-fixture/graph-helper-implementation-report.md`。

最新 `current-inventory-final.json` 引用 `formal/recovery/runner-1791536968173038500/partial-case.json`，实际验证当前 source、52 条原生 primitive 原件及 signed abnormal stop：19 build、30 inspect、2 edit、1 save；另保留有限 render/reopen。没有陈旧源码错误；仍有一个未登记产物的 linkage 错误及七类完整生命周期证明缺项，结果不能提升为全域 PASS。当前公共 task_save 自身的 typed 原件已经过 caller 和限定复核验证；adapter 的 domain-level save 认证仍未闭合，不等于“磁盘上没有 save 原件”。

独立只读结论位于 `review/PARTICLE_PYRO.md` 和 `review/RBD_FORMAL.md`。两份只对所列源码/SHA、指定 P02/A01/R05/保存/恢复缺陷及实际日志作限定软件关闭，所审范围无剩余确定 P1/P2；它们没有接收完整 Windows 生命周期、全部 16 域、安装或真实阶段。随后 GraphJobRecovery 夹具修复由主 agent 审查，模块 29 方法通过，不属于上述两份独立复核范围；正式产物登记等其他失败不能归并为已关闭。

源码当前在工作区，`tools/sync_controller_client.py` 默认 check 无差异，`git diff --check` 通过。软件、安装、真实宿主、模型、视觉和生产接收分别报告；不发布新的安装完成版或覆盖旧移交包。
