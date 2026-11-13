# 生产接口补齐请求的限定核对结果（2026-10-16）

用户要求补齐生产链必要接口。本轮检查了现有正式接线与尚未排除的公开原生入口，**没有实现缺失的原生采集接口，也没有产生生产 AVAILABLE；该请求仍 BLOCKED，工程闭环未完成，M1 NOT_READY。** 未找到有依据、可以独立修复的生产漏接或错误传播反例。这个结论限于已查材料，不证明厂商内部不存在接口。

## 当前真正缺少的接口

最早缺的是适用于 H21.0.631 和 H22.0.459 的 **husk 普通 raster-save 扩展接线与对象生命周期合同**。它必须说明如何注册或取得当次实际选中的 writer，并把它与 product、RenderVar/AOV、frame、path 绑定；还须说明外层处理链的所有权，以及 write、flush、close 的成功与错误如何传播。之后仍需实际消费的 processor/config/context/file-rule/LUT、执行次序及最终 alpha 语义。既有 [未发送支持问题](evidence/20261016-native-integration-readiness/SIDEFX_SUPPORT_DRAFT.txt)已经逐项列出这些问题，本轮未重写或发送。

这份合同不能由 Bridge 新增一个接收字段的 Python 函数生成。现有 post-frame 入口确实可采集原始观察，但未交付这些实际对象和完成状态。仅有字段、签名或相同配置不能代替实际执行事实。

## 已查原生入口及其边界

两版安装随附帮助、SDK、Python 源码和样例的只读核对结果如下。原生入口研究未执行厂商程序、反汇编、编译或原生加载；交付阶段仅运行自编纯 Python 材料和 payload 校验。

| 入口 | 已确证内容 | 仍缺内容 |
| --- | --- | --- |
| husk Python hooks | H21 `help/ref.zip!utils/husk.txt:184`、H22 同成员 `:207` 文档化 stage/settings/husk_command/frame；H22 另有 postload | 没有实际 writer/delegate 对象交接，逐产品 write/flush/close 成功合同仍缺 |
| verbose callback 与日志重定向 | 两版 `karma_stats.py:673` 解析 verbosity、mode、JSON stats；同版 husk 帮助支持 stdout/stderr 重定向 | `end` 可来自收敛或时间上限，日志与回调发生不能证明成功关闭 |
| HUSD 产品和渲染回调 | H22 `HUSD_RenderSettings.h:283` 的 writer 是设置属性写入器；`HUSD_Imaging.h:133` 回调用于 GL Execute/VAO 生命周期；两版均已核对 | 没有交付普通 raster 的磁盘 writer |
| Hydra delegate/thread 接口 | `hd/renderDelegate.h:498` 的 commands 针对已有 delegate；`hd/renderThread.h:148` 配置自有线程 | 没有从当前 husk hook 取得选中 delegate/writer 的受支持路径，也没有已证实返回所需最终事实的 Karma 命令 |
| IMG_Sample.C | 两版示例字节一致，支持创建自有格式 writer | `closeFile():210` 调用 flush 后无条件返回 1；它不能补齐 husk 接线、输入/外层处理语义与成功关闭合同 |

安装根分别为 `/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/` 与 `/Applications/Houdini/Houdini22.0.459/Frameworks/Houdini.framework/Versions/22.0/Resources/`。这些定位是静态材料事实，不是运行时验证。既有来源身份和边界见 [接口核查](WRITER_INTERFACES_20261016.md)、[原生集成准备](NATIVE_INTEGRATION_READINESS_20261016.md)。官方 [USD/Hydra 说明](https://www.sidefx.com/docs/hdk/_h_d_k__u_s_d_hydra.html)只补充语义，不作为精确 build 的 ABI 保证。

## Bridge 现有接线并未缺失

只读代码复核确认以下链路已接通：

1. [正式逐帧调用](../plugins/houdini/_impl/houdini_bridge_addon.py:15068)进入 [render_writer_frame](../packages/houdini-bridge/src/houdini_bridge/render_writer_facts.py:315)，运行后认证原始观察并记录。
2. [collect_render_output_fact](../packages/houdini-bridge/src/houdini_bridge/client.py:261)保留观察，进入 execution_fact、原始签名终态和消费端重验。package 与 controller-entry 的 client、render_writer_facts、render_ocio_facts 副本一致。
3. [生产 Registry 绑定](../packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py:1594)调用当前 `render.verify`；[正式登记 facade](../packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py:1027)与 [typed metadata 验收](../packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py:359)已存在。
4. 发布失败保留签名原件；同步停止状态未知走 RECONCILE 并保槽。本轮没有发现可确证的“采集失败报成功”或“停止未知释放槽”反例。既有测试覆盖不作为本轮新运行结果。

producer 仍正确保留 `BLOCKED_MISSING_NATIVE_FACTS` 和空 metadata。没有新增可由调用者提交 verified/AVAILABLE 的入口，没有放宽 Registry 或 Nuke 校验。

## 实际 husk 身份也不能只补 PID

[可信宿主配置生成器](../tools/configure_production_hosts.py:26)和 [部署校验](../packages/vfx-pipeline/src/vfx_pipeline/production_hosts.py:42)没有冻结预期 husk 文件身份。现有 process_identity 只有 pid/platform/birth/state；owned_process 监督主 hython 和进程组/Windows Job，不提供单个 husk 的 OS image path 或祖先链认证。

仅追加 pid、ppid 或 birth 无法解除 `WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED`。完整实现需要可信预期 husk 输入，以及配置、task_host、插件、实际 hook、producer 的联合绑定。不能把邻接安装路径或进程自报的 sys.executable 自动视为可信 husk 身份。这项也没有被宣称补齐。

## 本轮实际验证、改动与保护

主控重新执行了既有 `HoudiniOutputReceiptTests.test_existing_producer_registry_refusal`：1 项通过，0 failure/error/skip，0.009 秒。该测试使用显式合成 EXR 文件和 SQLite，确认缺少可信原生 metadata 时正式登记拒绝且 history 为空；它不是原生正向验证。第一次 unittest 调用错误地把绝对文件路径当模块名，出现 ModuleNotFoundError；改为模块入口后通过。两次调用与范围记录在 [验证记录](evidence/20261016-production-interface-closure/verification.json)。没有重跑全量、安装或生命周期。

两个只读研究分工分别核查原生入口和正式接线，均未提出有依据的独立生产修复；未修改代码或执行厂商组件。归档和新交接材料由主控负责，其复核范围另行记录，不把两项研究当作对归档的独立审查。

本轮独立复核另发现归档工具的一项 P2：仅固定792个保留成员并比较打包前后哈希，不能证明它们沿用上一交付原字节。当前实际792成员均与上一交付相同，未发现材料被替换。打包器与独立回读均已改为认证最新历史ZIP固定SHA后，从同一内存字节读取原package-manifest，再对全部installers与validation/current-release成员的精确集合、bytes、SHA和重复项进行比较。纯Python检查确认完整集合通过，空、缺项、多项、同数量换名、改大小、改SHA、重复历史行七类反例全部拒绝。随ZIP的 `validation/retained-guard-verification.json` 保留结果；这属于归档工具修复，不是生产接口实现。

本轮生产范围仅新增此报告、限定证据和导航；生产代码、测试、安装 payload 与已有修复保持原字节。修改前冻结了 3330 个可交付源码文件，排除规则沿用上一轮的凭据、活动状态、缓存与商业原件规则，880 个排除项不纳入该交付基线。保留比较见 [preservation.json](evidence/20261016-production-interface-closure/preservation.json)。四 wheel、三 Skill 沿用既有相同字节；完整 ZIP 仅证明交付完整性。

未启动真实 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、仿真、缓存或渲染；未发送支持问题、采用新 writer 路线、复制密钥、修改原 Desktop 主工程、提交或推送。全 16 域、48+2 案例、54 行要求和后续依赖门保持原状态。当前交付是准确的阻断记录，**不是接口实现完成或工程测试成功的交付**。
