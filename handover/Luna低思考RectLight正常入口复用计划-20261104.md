# Luna低思考：RectLight已完成官方案例正常入口复用计划

日期：2026-11-04。状态：计划与P0/传输补审PASS，Luna low首试PASS，最终独立验收PASS；本阶段完成。实际4工具/2schema/6raw、0DCC，无产品修复或复试。

## 目标和对象

由新的gpt-6-luna / low冷上下文agent，通过当前已安装Bridge插件自行找到RectLight工程，列出原任务，识别当前已完成版本，按原operation查询并取得正式HIP、NK、主EXR、Nuke EXR和观看预览，提供可用入口与准确来源。

RectLight是SideFX H21 Karma User Guide Lights的官方灯光分支，已有两轮创作及第2版正式交付。它在插件中属于creative工程，区别于上一轮Geometry Gate的geometry路径；本轮验证现有入口在另一案例、另一既有任务路径上的正常复用，不重新证明创作或渲染能力。

主工作区为`/Users/user/Documents/Code_Project/Bridge`。本轮原始证据放`/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方案例入口复用-RectLight-20261104/`。

## 固定边界

- 复用原HIP/NK/EXR、官方参考、alpha、保存/冷开/Nuke消费结果；不重跑建图、反馈、渲染、登记或整条正式链。
- 新DCC启动、连接、保存、冷开、渲染、校准与创作派发均为0。上一轮已验证自动连接，本轮已有任务查询不依赖新后台连接，不因Skill的新任务连接提示重复启动宿主。
- 原任务、原结果、回执、原准备文件、登记、校准、账本、预算和历史失败保持。入口本就会在插件私有消费者目录复制查询状态；此类本轮副本可按原实现产生，不冒称原正式状态被重接收。
- 不改灯光/曝光/降噪/显示；RectLight不套用Geometry Gate的+7EV观看图，人工审美PENDING继续有效。
- 不复制素材、不改用户GUI、不扩展恢复框架、不提交或推送Git。

## 执行步骤

### P0：离线确定当前入口及原件基准

1. 读取RectLight的现有登记、准备、状态、交付清单和既有审核，仅记录本轮消费文件及状态的摘要，不全仓冻结或重验原链。
2. 核对当前插件0.4.10的project_entry与creative_session实际路径：显式选择后列原任务，continue走已有CreativeSession及原生产验证，返回既有正式文件。不能改用内部query或本地拼接文件冒充插件成功。
3. 检查正式文件存在、当前第2版身份和既有结果路径；不启动hython读取HIP，不解码EXR或重复像素比较。
4. 准备已验收的透明官方AppServer MCP测试传输。复用上一轮实现，只将工具白名单收窄为health/projects/select/current/tasks/continue，硬拒绝connect、execute、propose等新副作用；原公开schema和响应不改写。
5. 记录源版本和本轮预算。所有P0/答案/主计划与审核资料均放测试私有区，不发给冷agent。

### P1：独立审核，必要时修改再审

独立agent只审核本计划、P0事实及本轮测试传输最小差分，不参与实现或替Luna查询。审查0DCC是否可行、creative路径与geometry路径是否区分、原件保护、冷上下文隔离、返回来源、预算与退出机制。

未通过只修具体问题，再交同一审核方。通过后按用户已授权范围直接执行，不另行重复申请，也不新增冻结审查。

### P2：Luna正常使用首试

- 使用新gpt-6-luna / low，fork none。仅给简短任务、随包Skill/真实公开schema、普通只读文件能力、透明客户端及预先为空的attempt-1输出目录。
- 不给项目ID、operation、版本答案、产物路径或内部修复方案；不提供P0或旧测试记录，不引导读取测试上级目录中的答案。
- 可从插件返回路径自行发现产品README，核对正常说明；文件读取用于正常发现和报告，不得导入内部执行器或自行实现工具后端。
- 所有Bridge操作由受限传输原样交给官方已安装插件；主agent不代选工程、代查任务或补给答案。

任务文本：

> 使用已安装Bridge插件，找到已完成的官方RectLight案例，列出原任务并继续取得当前最终版本，给我可打开的HIP、NK、主EXR、Nuke EXR和观看预览入口，说明来源。本轮只读取已有成果，不建立后台软件连接，不重新建图、渲染、保存、校准或覆盖原件；不要把工程选择说成HIP已经加载。

预期：agent自行发现工程、显式选择、列任务并判断当前版本，然后查询原ID，返回COMPLETE和正确文件；若原任务运行中只观察，失败/未知不重派、不换ID。必须区分正式产物与从产品文档另行发现的辅助说明，不把另一案例或旧版当最终版。

### P3：遇到失败时的最小处理

1. 先保留实际工具返回、错误码、耗时和本轮私有消费者状态，找最早失败环节。
2. 只修实际暴露的入口、可发现性、历史结果读取或必要兼容问题；文件/签名/登记身份不匹配不能靠删检查、宽泛兼容、伪造COMPLETE或重签旧回执通过。
3. 已验证的旧成果不得因查询错误重新渲染或重建。若需处理历史兼容，保持当前实时验证严格，历史观察与可用于新执行的消费资格分别表达；只核对应输入和必要下游。
4. 只做一个必要修复轮次、至多一个冷上下文复试；成功步骤和证据复用，不原样重试同一错误。
5. 若产品需更新包，沿现有打包/安装流程只发布本次改动，定向核实际入口；不重跑安装全生命周期、整组软件或原正式链。
6. 如发现必须新增DCC或重签旧正式结果才能继续，属于计划外范围：保留具体事实，不擅自启动或用替代结果假装完成。

### P4：定向核对与独立结果审核

只核本轮实际调用和必要改动：

- 实际模型为Luna low冷上下文，主agent没有代操作，provider无证据仍unknown。
- 工程来自登记列表；所选对象为RectLight，当前结果revision2/主产物v2，operation为任务列表中的原ID。
- 正常continue真实返回COMPLETE；HIP/NK/主EXR/Nuke EXR/preview及result身份与原清单一致，路径可用。
- 返回的官方案例来源可对应现有RectLight交付说明；不把选择或链接当作新的HIP加载/冷开证明。
- 本轮只读消费未改变原任务、回执、预算、文件及其它已登记案例；合法新消费者副本另记。
- 所有新DCC/渲染派发为0，技术Host关闭并wait退出；没有悬挂查询或测试进程。

独立agent据实际请求/响应、原件摘要和Luna回复给最终PASS或具体缺口；不重做旧链验证。只有取回文件且身份正确才算通过，READY、工具无报错或文件存在不足以单独验收。

### P5：交付、交接和清理

提供简明结果及原工程/预览入口；无需复制原成果，也不要求用户重新确认旧预览。更新START_HERE、当前交接与本计划状态，明确是第二案例入口复用完成，不提升新创作、审美、UI或全域状态。

保留原始工具记录、精确分类计量、必要定向检查及独审。关闭本轮技术AppServer与转发器，清理空测试目录、派生响应副本和自有一次性文件，保留必要证据；共享记忆只保存确认后的交接事实。

## 拟定预算与不盲等规则

| 项目 | 本轮总上限 |
| --- | --- |
| Luna | 初试1次；仅必要修复后再做1次冷复试 |
| 新Native/DCC/连接/保存/冷开/渲染/校准/创作 | 全部0，由测试传输白名单在派发前拒绝 |
| Bridge工具 | 16次，含必要复试；超额派发前拒绝，失败不退次数 |
| 工具描述查询 | 4次；与工具分开记账；raw总上限20 |
| 正式工具RPC等待 | 单次最多180秒；超时记UNKNOWN，停止并wait实际控制进程，收尾另记，不自动重发 |
| 操作等待/本地处理 | 累计目标600秒，技术传输实际累计；模型排队和独审时间另记 |
| 控制Host关闭 | 依既有客户端先等15秒，再terminate等10秒；无法确认停止不得假报退出 |
| 新证据 | 目标20MiB以内，不复制工程/渲染/素材 |

每60秒给有事实的进度。长调用观察原请求与本次进程，不轮询health消耗额度；不以客户端超时或Python future停止等同服务端已停止。超时或未知不换ID重放，不通过重启Host重置预算。

## 完成标准

冷Luna在已安装插件的正常入口独立找到并取回RectLight当前最终交付，原文件/状态保持，真实调用计量与0DCC边界满足，独立最终审核PASS，交接和清理完成。本次不要求再做已完成的两轮创作、官方参考、alpha或人工审美接收。

## 当前依据

- [RectLight当前工程入口](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/luna-rectlight-01/README.md)
- [RectLight既有真实结果](/Users/user/Documents/Code_Project/Bridge/handover/LUNA_RECTLIGHT_RESULT_20261029.md)
- [上一阶段正常使用验收](/Users/user/Documents/Code_Project/Bridge/handover/LUNA_NORMAL_USE_RESULT_20261104.md)
- [当前插件使用说明](/Users/user/Documents/Code_Project/Bridge/docs/agent-plugin.md)

## 完成结果

[实际交付与范围](/Users/user/Documents/Code_Project/Bridge/handover/LUNA_RECTLIGHT_ENTRY_REUSE_RESULT_20261104.md) · [独立最终验收](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方案例入口复用-RectLight-20261104/最终独立验收.md)。原件及原任务保持，仅查询当前已有结果；原审核版保存在本轮文档目录approved-plan.md，供核对原审核摘要。
