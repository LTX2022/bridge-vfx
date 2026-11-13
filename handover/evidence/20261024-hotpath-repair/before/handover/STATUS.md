# Bridge 当前状态（2026-10-24）

本轮[H21建图240秒真实专项](H21_HIP_RESOURCE360_RESULT_20261024.md)已按用户批准的新资源合同和冻结审核实际执行：1次启动、229.438401秒后HIP_GRAPH_DEADLINE，可信停止且槽释放；19条构造COMPLETE、1条INTENT，无HIP，无第二冷重开，无重试，范围失败封闭。两位独立验收确认旧207原件及160冻结源码无漂移。新profile及必要软件验证已完成，旧默认保持；预算扩大仍未让完整图通过，内部耗时首因未确定，不自动追加时长或续用剩余名额。工程闭环/M1仍未通过。

最近一次[H21检查点真实专项](H21_HIP_STARTUP_LIVE_RESULT_20261024.md)已按新授权执行并失败封闭：1次启动、109.855351秒、可信停止且自身槽释放；18检查点齐全，8条建图变更记录COMPLETE，但无HIP或冷重开。首变更意图距签名启动83.85秒，最后geometry_import意图距停止仅1.41秒，不能判节点挂起。下一步先核前段耗时与期限可行性，不自动重跑或延时。完整工程闭环/M1仍未通过。

此前[H21启动检查点软件准备](WORKER_STARTUP_PREPARATION_20261024.md)已完成[计划](WORKER_STARTUP_PLAN_20261024.md)第1—5步及独立审核；新prepared候选未授权、零启动。18个固定检查点默认关闭，专项driver显式开启；Python3.11核心8/8通过，旧182原件未变。第6步须具体新授权后执行；原生首因、HIP保存/冷重开及完整工程闭环/M1仍未通过。

最近一次[H21 HIP原生专项](HIP_ONLY_RESULT_20261024.md)已按[独立审核后的完整计划](HIP_ONLY_PLAN_20261024.md)实际执行，但未通过：首次graph-worker运行109.540949秒后HIP_GRAPH_DEADLINE，取消并可信停止，1/2次启动、零重试，无HIP、无第二冷重开进程，scope已失败封闭。最早worker Python入口无检查点，首因尚未确定；不能归因于vmmap。保留已修HIP路径及全部既有源码，生产身份门槛未改。完整工程闭环与M1仍未完成。

- 可编辑HIP：未取得；本次专项在保存结果前截止。
- HIP保存退出冷重开：未到达；第二进程未启动。
- 真实alpha：18校准5个EXR已验证；主场景alpha未取得。
- 主EXR完整验证及登记：未到达。
- NK登记消费、首存、冷重开及输出：未到达。
- 实际图像：仅校准图；主球地面与Nuke结果图未取得。

此前[18真实工程验收](H21_LIVE_18_RESULT_20261023.md)：真实 alpha 校准通过，41 个构造操作完成；领域初始化将锁定 HDA 内部节点计入显式图而失败。三处节点精确类型修复已真实生效。3/8 启动均可信停止，78.699 秒，范围封闭且零重试；HIP、NK、主场景 EXR 未生成。 HDA 边界与原生类别的最小修复、必要验证及两位独立验收完成；[19 候选](../outputs/engineering-closure-20261023-h21-19/)已冻结，保持 `PREPARED_NOT_AUTHORIZED`、零启动、零票；仅指向未来独立 20，20 未激活且未获真实授权，修后真实为 `NOT_RUN`。

此前[16真实工程验收](H21_LIVE_16_RESULT_20261023.md)：真实 alpha 校准与五个 EXR 数值复核通过；正式建图因预期 `light` 与实际 `light::2.0` 不一致而未完成。3/8 次启动均可信停止，32.799 秒，零重试；16 已失败封闭，HIP、NK、主场景 EXR 未生成。精确类型创建的最小修复、必要验证及两位独立验收完成，该轮 17 候选在当时保持未授权、零启动；其后授权及18执行结果以上方18报告为准。

此前[14真实验收与15入口修复](H21_LIVE_14_RESULT_20261023.md)：14 首次 alpha-husk 因 prerender 缺少 `__file__` 失败，使用 1 次启动；修复后的 15 review 经用户另行授权，生成了本轮 16 独立真实范围。历史原件与消耗分别保留。

此前[原生就绪同步与采集失败早停](NATIVE_READINESS_STOP_REPAIR_20261023.md)：原生就绪同步与采集失败早停两项软件修复及两位独立验收已完成：双Python核心、普通进程真实macOS采集及失败停止、单次无映像模型八阶段软件链通过。该轮13候选在当时为 PREPARED_NOT_AUTHORIZED，0启动/0票据，八次启动预算不变；该软件修复轮未重跑真实宿主，真实工程闭环与M1仍未通过。

此前[12真实工程验收结果](H21_LIVE_12_RESULT_20261023.md)为 FAIL：按11 review激活12后，仅1/8次alpha husk启动，产生1份实际校准EXR，最终整组可信停止、无重试；writer采集遇到原生启动未就绪的stderr而被拒绝，另发现记录采集错误后未立即取消当前作业。HIP/NK/主场景渲染与Nuke消费未到达。12已失败封闭，不续跑；工程闭环、M1、HY3及视觉状态不提升。

此前[09真实验收结果](H21_LIVE_09_RESULT_20261023.md)：已按08review激活并执行，2/8启动后因husk身份绑定缺失及校准结构错误失败关闭；两进程可信停止、无重试。实际生成5个RGBA校准EXR，尚无HIP/NK/主渲染。-06/-07/-08及停止后09原件完整保留，当前不继续真实作业。

上轮07的原始验收记录：采用 [H21受控工程闭环](ENGINEERING_CLOSURE_20261020.md)，ACEScg已确认。[两处最小修复候选](ALPHA_FORMAT_BYTECODE_FIX_20261021.md)为-07未授权、0启动：alpha format改同版color4h，supervisor固定-B；3.14核心24/24、3.11兼容2/2通过，限定独立代码复核无剩余P1/P2。但唯一一次完整软件链在H宿主vmmap进程身份采集处PROCESS_IMAGE_TIMEOUT，整链未通过，未修改该路径/超时或重试。-06全部242文件逐项未变，未重跑真实宿主，八次预算保持。真实工程闭环、视觉与M1未通过；安装包未重建，Git未提交或推送。此前[真实首轮失败](H21_FIRST_LIVE_20261021.md)与[旧软件通过](ALPHA_FINAL_CHAIN_20261020.md)保留原轮范围。

以下为历史阶段的原范围与证据；其中“当前”“最新”和严格 writer 阻断均指各报告当时的路线，不覆盖当前 [controlled_output_v1](ENGINEERING_CLOSURE_20261020.md)。当前受控验证绑定可信停止、冻结配置、完整 EXR 和同路线原生 alpha 校准，内部 writer/filter/flush/close 保持 `NOT_OBSERVED`；旧严格回执保留原样，不得改标 AVAILABLE。工程闭环仍未通过。

项目色彩选择已接入可信配置、请求摘要、产物账本和 Nuke 消费，来源标为 `human_project_selection`；具体标准仍待各项目人工填写。旧内部颜色追踪不再阻断新请求。alpha、产品/AOV、非颜色处理、成功写出与身份验证仍保留，真实工程闭环尚未完成。当前源码尚未重建安装 ZIP。相关 producer／身份／alpha 回归、正式跨进程软件链、账本与 Nuke 传播、配置和发布兼容检查通过；本次独立代码复核未发现 P1/P2，范围限本次颜色接线。

非颜色 writer 的[2026-10-19阻断核查](NONCOLOR_WRITER_BLOCKERS_20261019.md)已完成：10 个现有核心软件用例通过，两位独立只读核查者均未找到可据现有接口关闭阻断的代码修复。写出成功未证实已明确列出；本次保留全部生产代码及测试，工程链仍缺实际 writer 交接、最终 alpha／处理与成功关闭结果。

配置用法见[当前接续说明](NEXT_AGENT.md)，授权依据见[项目色彩标准决定](CONTROL_DECISIONS_20261004.md#项目色彩标准)。下列报告保留其当时的源码与验证范围。工程闭环仍 BLOCKED，M1 NOT_READY。

2026-10-16[可信 writer 可执行文件与进程身份接口](PROCESS_IMAGE_IDENTITY_20261016.md)已完成局部生产接线：显式 path/version/SHA 冻结、部署与任务指纹、原始 signed started 的宿主锚点、postframe 的 OS 主 image/严格祖先链、持久 aggregate 读取预算及 producer/终态重验。慢身份采集阻塞监督的 P2 已修复并通过独立复验（P2 CLOSED）；最终受影响组80项中76通过、4个Windows跳过。生命周期工具的Unicode摘要漏配已复现并修正，16项回归全过；SHA未变的runtime26项保留此前通过，去重软件覆盖122项，重复审查不累加。普通Python真进程与mocked原生边界分别记录。该接口只关闭可执行文件/进程身份缺项，实际writer/processor/AOV/filter/alpha及成功关闭仍缺，真实husk NOT_RUN，AVAILABLE/登记/Nuke真实消费和工程闭环仍BLOCKED、M1仍NOT_READY。五份controller镜像与最终源码一致；本轮796h9zrr成功release的14/14步骤通过，四wheel/三Skill与完整当前payload匹配，隔离安装和三Skill生命周期通过。两次失败构建原始审计保留；完整ZIP身份和独立readback见报告及outputs/process-identity-handoff-20261016最终证据。

此前[生产接口补齐请求的限定核对](PRODUCTION_INTERFACE_CLOSURE_20261016.md)：现有postframe→producer→签名终态→重验与正式登记入口已接通，未发现可确证的独立漏接或错误传播修复项。仍缺同build husk raster-save实际writer交接、处理与成功关闭合同；未实现原生接口，用户的接口补齐请求保持BLOCKED。既有登记拒绝测试1项重新通过，仅证明缺事实时拒绝；生产代码、测试与安装payload未改。

2026-10-16[原生集成合同核对与验证准备](NATIVE_INTEGRATION_READINESS_20261016.md)补证产品格式选择和流关闭后回调，区分54行验收、producer事实与Registry字段；受支持加载/交接、实际处理与成功关闭合同仍缺。已完成未发送支持问题和具体条件性实验设计，原生组件及AVAILABLE仍BLOCKED。本轮未改生产代码或安装payload，沿用上一轮相同安装包，没有重复安装生命周期。

此前[husk 保存入口与当前源码安装验证](HUSK_ENTRY_AND_CURRENT_RELEASE_20261016.md)补齐两版 husk 的 hdRenderProduct::save→imgSave C1/C2→saveData→filename IMG_File::create 静态连接，H22 保留两个 create 调用点；另定位 rasterConvert 内 processor lookup/transform。实际 writer 交接、已执行覆盖和最终 alpha 等事实仍缺。当前源码四 wheel、三类 Skill 已离线构建，payload 绑定及隔离安装、升级、失败保护、回退、卸载软件验证通过；这不关闭工程或 M1。

此前[保存函数实现核查增量](WRITER_SAVE_IMPLEMENTATION_20261016.md)记录两版精确 libHoudiniUT 的 save 重载、格式分配及写入滤镜创建静态边；保留该轮结果，最新 husk 入口证据在上方增量。生产未改，AVAILABLE、真实登记及 Nuke 消费保持 BLOCKED。

此前[实际 writer 采集决策与停止条件](WRITER_CAPTURE_DECISION_20261016.md)的24条来源及3项软件拒绝用例保留原轮范围，函数体尚未检查的表述由最新增量补充。厂商问题未发送，条件性验证设计未执行。

此前[实际 writer 接口核查](WRITER_INTERFACES_20261016.md)完成60项同版静态来源与限定独立复核。本轮24条与此前部分重叠，不累加为唯一来源总数。IMG_TileFile::files()需要先取得当前实际实例；TIL/BRAY/display/stats接点不覆盖全部最终事实。

该历史阶段接续见 [writer→登记→Nuke](WRITER_CHAIN_20261016.md)：修复Nuke异任务输入前置拒绝、默认颜色/alpha及正式Read→Write的raw/Write alpha读回与回滚。两版静态原件核查仍未确证实际writer/processor/filter/alpha采集接点；AVAILABLE生产路径、真实Karma产物登记及Nuke消费保持未完成，不能概括为只差真机运行。

**工程闭环尚未通过，全 16 域 M1 仍 NOT_READY。** 旧全 16 域铺开方案先冻结，当前按[工程闭环→反馈/恢复→HY3→复用](FEASIBILITY_AND_CLOSURE_20261016.md)的依赖顺序推进。全 16 域、48+2 案例和原 54 行要求保留为长期目标与最终验收依据，不删除有效成果或改写历史结论。当前工作基准是本仓库；原 Desktop 主工程保持不变。软件、安装、原生接口、真实宿主、HY3、视觉和生产验收分别记录。

目前已验证的范围限于材料整理及冻结参数的软件建图、反馈、保存和新进程读回链。sphere_ground_v2 的球/地面独立 prim、各自 UsdShade 有效材质双版正式软件链及旧 sphere_ground_v1 保存/反馈/冷重开兼容已验证；54项受影响回归通过，最终增量独立复核无待修P1/P2，状态见 [Karma 工程门记录](KARMA_ENGINEERING_GATE_20261016.md)。

该阶段完成上述软件核验时，严格 writer 路线的具体阻断是 client.render_execution_fact 固定为 BLOCKED_MISSING_NATIVE_FACTS，尚无可信 AVAILABLE 的生产转换；artifact_registry 拒绝登记，Nuke 尚无法消费真实上游。这些是该路线的历史状态，不覆盖当前 controlled_output_v1；当前主 EXR 验证、登记和 Nuke 真实消费仍未到达。局部软件通过不能提升为工程闭环或其他闭环通过；真实宿主、HY3 或模型仍须另行具体授权。

以下保留各轮已完成项与原证据边界，不作为恢复全域批量修复的执行顺序。

本轮跨任务 orphan 授权、store 容量恢复、文本编码校验及颜色最终审计的源码整改和定向独立复核已完成，详见 [四项修复结果](CONFIRMED_FIXES_20261015.md)。该局部结果不改变完整 M1 的未完成状态；当前安装包与验证结果见本轮验证记录。

当前 M1 候选保留输出预检、媒体派生身份、发布内容绑定和 16 域操作卡，补入任务自有 husk post-frame 原始观察、R05 条件预检／任务种子／语义反馈与持久恢复、O01 谱源失效修复。writer 最终有效颜色／filter／alpha 事实、14 项控制的完整路线及组合闭环仍未完成。当前缺口见 [M1 优先级清单](M1_GAPS_20261015.md)；本轮日志、源码指纹、全量、独立审查和打包结果见 `outputs/m1-writer-controls-20261015/RESULT.md`。局部修复不改变 M1 未完成状态。

本批已实施的修复：

- Nuke 单应用正式配置、生成器、TCP 宿主、保存重开及固定后台 worker 路由；输入在 worker 内消费私有验证副本，登记前重验公共输入。
- Houdini 配置／记录／store 的整体大小限制、操作级持久 OCIO 读取预算、损坏 store 分离，以及预检期间的重槽回收围栏。
- POSIX 父进程先退出时继续监督同组后代；停止事实与整组执行成功分开。macOS 恢复身份补齐出生标识，未知身份继续拒绝。
- FLIP 注册配方在创建 container 时明确初始化 multiparm 计数，保留原生默认值未知事实。
- 恢复用例的平台断言、重复装载和过期成功期望；找回并纳入 Git 可维护的原始 Crowd／Hair 接口夹具，原 SHA 保持一致。
- 发布 ZIP 的实际内容校验、接口文档及当前源码离线 wheel 构建验证。

本批命令、原始红绿日志、最终标准回归、独立审查、源码绑定及安装结果统一见 [本批验证记录](../outputs/m1-completion-20261015/RESULT.md)。其中任何 FAIL／ERROR／SKIP／BLOCKED 都按实际范围保留；单项通过不能提升完整领域或 M1 状态。

长期完整范围的缺口见 [REMAINING.md](REMAINING.md)，当前活动顺序见 [NEXT_AGENT.md](NEXT_AGENT.md)。20 项产品定义和 B 组合已获批准，无需重新询问产品语义；当前元数据中 6 项 mapped、14 项 blocked，mapped 不代表原生效果或完整生命周期已通过，不据此重新派发全域批量修复。

用户仅另外批准了一次 H21.0.631 只读参数采集：取得 Driver/usdrender 的 140 项定义，没有建节点、cook、仿真、缓存或渲染；未取得签名停止回执，不能用于恢复或真实验收通过。[原始事实及限制](evidence/20261015-native-interface/README.md)。当前兼容目标已由用户确认改为 H22.0.459，主版仍为 H21.0.631。459 已独立静态采集 55 个 HDA 定义，见 `docs/native-basis/hda-interface-22.0.459.json`、`supporting-sources-22.0.459.json` 及 `h22-459-originals/`；缺失的 compiled／运行时模板和有效 writer 最终事实仍为阻断。22.0.429 的历史事实和显式兼容保留原版本，不改标为459。

2026-10-16 新增 [路线可行性与闭环验证记录](FEASIBILITY_AND_CLOSURE_20261016.md)，保存对长期返修的分析、工程/反馈/恢复/HY3/复用的候选验证顺序及正式入口限制。这是分析与实验设计，不是新增执行结果；M1 仍 NOT_READY，真实运行禁令不变。

2026-10-16 完成 [官方 Karma 材料静态整理与最小重建合同](../docs/official-baselines/karma/README.md)：两版各13个原文件及声明HDA核对，完整HIP静态解析，保存版本与安装标签分别记录。尚未生成经宿主验证的新HIP/NK或执行渲染；writer、反馈和组合缺口未关闭。

2026-10-16 完成 [Karma正式装配静态检查与两项预检修复](KARMA_PREFLIGHT_20261016.md)：两版灯光/材质注册拓扑可编译，预检已按声明case_ids及逐应用required_versions校验。5项定向验证通过，本轮两文件增量独立复核无待修P1/P2；实际CLI继续拒绝未解决原生依据。该轮未验证具体基准参数和真实宿主链，未重跑全量或发布包。

后续执行顺序和授权边界见 [NEXT_AGENT.md](NEXT_AGENT.md)，环境命令见 [ENVIRONMENT.md](ENVIRONMENT.md)。历史报告只证明其各自源码及范围；当前修改不自动提交、推送、合入 Desktop 主工程或启动真实作业。

2026-10-16 完成 [最小场景冻结参数正式接线](KARMA_FROZEN_PARAMETERS_20261016.md)：双版本软件正式建图、颜色反馈、保存及新进程读回通过，漂移拒绝生效；54项受影响回归通过，45张旧注册图编译内容不变，最终增量Bugbot无P1/P2。真实宿主/有效输出事实/M1仍未通过；本轮未重建发布包或全量。
