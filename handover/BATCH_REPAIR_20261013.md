# 批量修复与剩余内容（2026-10-13）

本批基于 `0a52552f5915375dfb0f3551e08928e9e624390d` 的干净工作树继续，保留历史补丁和冻结失败日志。**全16域 M1 仍未完成。** 当前只运行 Python/TCP 软件宿主及显式底层 HOM/USD 夹具；真实 Houdini、Nuke、HY3、模型、仿真、缓存、渲染、视觉和生产验收均未执行。没有提交或推送本批新增代码。

## 本批修改

| 内容 | 当前行为与边界 |
|---|---|
| Crowd 创建顺序 | 对精确匹配已登记图的 fresh 创建，复用既有 multiparm 分配计划，在 `node.create` 中显式设置 fields=1、compression=0；Hair 同时提前分配 operations=1。这是实际写入，不是猜测原生 factory count。Crowd 导入 PackedAgent Geometry，不创建无关体积压缩实例。 |
| Crowd blend ramp | 复用 `ramp_constructor_plan`，创建时通过有界 JSON 描述构造实际 `hou.Ramp`。只接受原生 Ramp 模板、两点 Linear、固定 keys/values 和确切数值类型，拒绝 bool、非法描述及 scalar 目标。批准的 animation_blend 仍是0–10秒时长。 |
| 冻结与恢复 | 初始化参数写入 schedule 摘要和 creation journal intent，旧无分配的 journal 在执行前拒绝；既有 lease、owner、UNKNOWN 和禁止盲目重放约束保持。 |
| Crowd 测试耗时 | 全局 `sys.setprofile` 原本对每次函数调用执行，并重复序列化 stash/agent 数据。改为 `BRIDGE_TEST_CROWD_TRACE=1` 显式启用；正常路径仍使用实际监督器、TCP、addon、producer、保存/重开和完整断言。宿主测试预算使用既有合法120秒上限，生产上限不变。 |
| AOV 原生观察 | 将帮助锚点 `karma:plane:filter` 修正为两版安装 schema 的 `driver:parameters:aov:karma:filter`（string），新增 `driver:parameters:aov:husk:format`（token）。逐帧、逐 AOV、原生类型、缺值和预算校验不变；损坏 filter 字符串保留原样，不宣称执行成功。没有发明 channel_layout 字段。 |
| G03 宿主组件 | 新增 `native_geometry_controls_host.py`：认证 lease/host、采集实际 P/N/id/拓扑/接线、校验 rest basis 和服务端初始化注册；提供受封印计划、完整通道快照、写入/回滚和 userData 持久化。缺三项服务端 hook 时拒绝，不从客户 JSON 或 P 值推断静止空间来源。 |
| G03 独立整改 | reviewer 复现 plan→prepare 之间更新 epoch 并重签合法 lease 后，旧计划仍可写入。现将完整签发 host identity 纳入已封印 context；新增两版 epoch/nonce/generation 反例，旧计划零写入拒绝，新计划仍可正常写入并回滚。 |

主 agent 负责 Crowd/共享文件与正式测试；两个分文件实现 agent 分别负责 G03 和 AOV，两个独立 reviewer 不参与对应实现。创建配置按用户要求使用 `gpt-6.1-sol`、`high`。controller-entry 副本通过既有同步工具更新。

## 实际验证

解释器为项目隔离 Python 3.11.9，系统 `Windows-10-10.0.26300-SP0`。命令、退出码、源码前后 SHA 与原始日志保存在 [本批证据](evidence/20261013/README.md)，完整临时过程另留 `outputs/batch-repair-20261013/`、`outputs/all-domain-20261009/` 及 `outputs/common-closure-20261009/domain-worker/`。

- 当前正式 Crowd 正常入口先复现两版 FAIL：每版6 COMPLETE、1 UNKNOWN，缺 fields count。修复分配后暴露 compression，继续修复后达到40 COMPLETE，缺 blend ramp；均保留原失败。
- ramp 初始化后已执行全部图及保存/重开，但全局 profiler 与60秒测试宿主造成超时。一次误设180秒被既有上限在启动前拒绝，已纠正为120秒，该失败也未删除。
- 关闭默认 profiler 后，正式 Crowd 正常入口**两版通过**：退出0、110.906秒，每版68 COMPLETE、无 UNKNOWN，149条原生操作证据，trial 为 SUCCEEDED 且停止确认成立，Houdini 槽位释放。两版生成快照的131个文件当时全部匹配根源码。这里的 worker 内保存/重开不等于新 PID 实例生命周期验收。
- 首轮组件集成85项，0失败/错误/跳过，30.109秒退出0；源码前后相同。随后 G03 reviewer 发现上述 P2，不能把85项绿测试当作完整独立接收。
- G03 整改后受影响 host/program 28项全部通过，9.859秒退出0；包括旧身份计划拒绝与新身份正常路径。G03 正式接线和实际变形仍 BLOCKED。
- AOV/回执/Crowd合同/登记/副本回归41项，40通过、1个原有 macOS vendor archive 缺文件跳过，8.047秒退出0。跳过不计PASS。一次错误调用不存在的 `test_formal_output_encoding` 模块属于本批命令错误，原日志保留；修正命令后上述有效模块通过。
- 登记领域图和 graph jobs 回归28项全部通过，89.562秒退出0。

最后 G03 整改改变了全运行指纹，故同一冻结源码上的两版正式 Crowd 另作最终复验：**两版通过、115.484秒退出0**，每版68 COMPLETE、149条原生操作证据，生成快照各131文件均匹配最终根源码。独立整改复核见证据索引，不沿用整改前全树摘要。没有重复标准软件全量。

独立结论：Crowd 指定创建范围和 AOV 增量未发现确定 P1/P2；G03 唯一发现的 P2 已由原 reviewer 在最终字节上独立复验关闭，28项与两版10个身份反例成立。原始发现报告保留，[整改复核](evidence/20261013/review/output-and-geometry-p2-closure.md)另存。结论不扩大到 G03 正式图、整个 addon 或全16域 M1。53件精选原证据逐项摘要核对，14件 Python 改动及两个生成快照均绑定当前代码。

## 尚未完成与下一批顺序

1. **共用输出 producer**：有效 OCIO 配置/LUT/context/file-rule、实际输出覆盖/AOV/filter 执行及 Karma/husk beauty alpha 关联。新增 raw 字段不足以生成 AVAILABLE metadata，正式登记仍保留缺事实拒绝。
2. **G03 正式接入**：认证 frozen input/rest provenance、授权 source geometry 获取、服务端 fresh/initialization 注册；新增 geometry_deform carrier 后连接 source→deform→transform。实际变形 P、拓扑/属性、下游消费、实例保持、跨帧和新 PID 重开未验。组件继续 `BLOCKED / parameters_only`。
3. **其他控制与组合**：批准20项和B方案不再询问产品定义；A01/P02/R05等继续补真实输入依据、正式调用链、事务、反馈/重开及原生语义。
4. **完整案例和交付**：48+2正式案例、54行门槛、完整预览/产物登记/域恢复/Nuke组合、最终同源码标准全量、三类安装生命周期与全域独立复核。macOS 待目标机器复验；真实宿主/模型/视觉/生产仍分别 NOT_RUN。

不要重做已闭合的 Crowd 创建顺序、AOV 错字段或 G03 身份封印；不要通过增加默认值、减弱 SUCCEEDED 断言或把缺事实改成 PASS 来解除门槛。下一批应集中补输出观察的可信来源和控制的正式接线。
