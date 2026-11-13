# 输出采集与漂移拒绝修复（2026-10-13）

本批继续 `0a52552f5915375dfb0f3551e08928e9e624390d` 之后未提交工作，保留 [上一批](BATCH_REPAIR_20261013.md) 的 Crowd、AOV 和 G03 修复。新增父 Houdini OCIO 观察与正式 producer 接线，关闭本批发现的两项 P2。**全16域 M1 仍未完成，输出登记仍缺三类原生执行事实。** 不把父进程配置重建提升为实际 husk/writer 证明。

## 本批实现

- 新增 `render_ocio_facts.py`：读取实际 `hou.Color.ocio_configPath()` 及有据列表接口；稳定读取配置文件。可用时重建 PyOpenColorIO Config，观察 context/cache/search/working-dir、最终覆盖路径的 file-rule，以及显式 raw Product/Var 颜色对的 processor metadata 文件引用，解析并摘要 LUT 原字节。缺模块、builtin/空路径、未知 API 与不完整闭包保留具体 gap；不复制环境变量值或异常正文。
- 正式 `_fx_render_configuration(..., output_pattern=...)` 使用逐帧最终 override 路径，分别提供两端都有实际值的 Product/Var 对，不推断覆盖优先级或默认颜色。旧材质/灯光静态读回不携带 `output_pattern`，保持原观察范围。
- 配置与 LUT 文件事实进入冻结 start binding、逐帧 output fact 和原 producer 签名终态；在帧完成、初次封存和消费读取边界重读字节。路径不符、内容改变（即使恢复 mtime）、删除、reparse/symlink 和伪造重摘要继续拒绝。旧无 preflight 回执保留 `OCIO_PREFLIGHT_OBSERVATION_REQUIRED`，不会升级。
- **P2-1 已修**：真实帧调用返回后，在原 root lease 内再次读取完整逐帧配置并与 frozen frame 比较。持续 context/cache 或配置选择漂移在记录 snapshot/output fact、追加 frames_done 之前失败，不更新原冻结基准。
- **P2-2 已修**：原可接受的17个 AOV 不因可选 processor 采集预算被拒绝。保留全部 raw USD AOV，最多采16个显式 processor 请求，另记录 omitted 数与 `PROCESSOR_REQUEST_BUDGET_EXCEEDED`；完整依赖仍为未知。

最多32个文件、单文件8 MiB、总32 MiB，参考共享预算128，API字符串8192字符。Python文件观察有界；同步原生 OCIO parser/processor 内部工作由现有宿主监督预算约束，不能声称本模块证明了原生内部时间/内存上限。配置/LUT稳定快照也不证明内存中 PXL 与真实输出驱动相同。

两名 GPT-6.1-sol high 子 agent 分别拥有采集器/自身测试和绑定反例测试；主 agent 拥有 addon/client/正式测试/镜像集成。独立 reviewer 未参与上述实现，原发现与整改复核分别保存。

## 实际验证及失败分类

解释器 Python3.11.9，Windows10.0.26300；命令、退出码、原日志及逐项摘要见 [本批证据](evidence/20261013-output/README.md)。所有项目执行仅用受控 Python/TCP/监督器和明确底层 HOM/USD/OCIO/EXR 文件夹具；没有启动真实 DCC、仿真或渲染。

| 记录 | 实际结果与边界 |
|---|---|
| 正式恢复 b 基线 | 23.437秒、退出1，登记端 `REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED`；源码前后相同。完整成功断言未降低。 |
| 采集器最终 scoped | 26方法通过、无跳过，owned source 前后相同。 |
| 绑定最终 scoped | 10方法通过、4.144秒、退出0；实际自有 Python producer 签名封存和消费，包含保持大小/mtime的 config/LUT篡改、独立重摘要伪造与损坏EXR。 |
| 首次中心组 | 110个实际方法通过，另1个错误模块名 `test_controller_client_sync` 导致命令退出1，38.032秒；原失败保留，不写为整组PASS。 |
| 正确副本模块＋正式 c | 4方法通过、28.938秒、退出0。只补正确模块 `test_controller_entry_client_sync`，没有重跑已通过110项。 |
| P2整改中心组 | 材质/灯光14方法及正式 c 通过；新漂移方法两版因测试启动夹具缺 `types` 导入失败，命令16方法、2个subtest错误、退出1，44.078秒。 |
| 漂移夹具第一次修正 | 两版在保存前被 `SCENE_CONTRACT_REQUIRED` 拒绝，50.843秒退出1；测试漏掉既有正式协议的同请求 graph_trial adopt，未放松生产校验。 |
| 漂移正式最终 | 同请求采用原完成图后，两版通过，1方法覆盖H21/H22、53.375秒退出0。每版实际完成建图/保存/重开，底层帧API写一次EXR后改变原生context cache；实际runner拒绝完成，0 frames_done、0 frame snapshots/output facts，metadata为空。 |

中心日志均保存实际 source_before/source_after。新增漂移夹具修正只影响该测试，未改生产源码；整改后的材质/灯光14方法与正常恢复 c 没有无变化重跑。此前 PASS 仅按其记录的消费字节和范围引用，不把一个命令的导入错误重标为退出0，不把若干 scoped 结果合称标准全量。

正式 c 仍消费最新保存 HIP，实际中断自有 worker、确认监督停止并恢复原工作，不重建完成图；新 preflight 被原签名 producer 回执携带，登记前明确 BLOCKED。本批原生漂移用例的失败终态是预期拒绝，不是新的软件测试失败。三个实际生成快照各132文件另与根源码核对。

原发现见 [独立初审](evidence/20261013-output/review/REPORT.md)；限定整改结论见 [独立复核](evidence/20261013-output/review/CLOSURE.md)。复核不接受整个 addon、全域生命周期或真实输出语义。

## 下一步与完成边界

1. 补**实际 husk** 配置/argv、输出覆盖、按 AOV 生效的 processor 与有序 filter 执行事实；父进程 raw 观察、配置重建及文件存在仍不能签发有效 writer metadata。Beauty alpha关联需要同版本有据语义与实际生效链，不能从A通道或像素值猜测。
2. 将已有 G03 host component 接入服务端认证 frozen/rest 输入、实际 source geometry 与 fresh/initialization 注册，再接 source→deform→transform；实际变形及跨帧、新PID生命周期仍未验。继续其余已批准控制和B组合，不重问产品定义。
3. 完成48+2正式案例、54门槛、完整输出登记/Nuke消费/域恢复；实现闭合后再做一次同源码标准软件回归、安装生命周期和全域独立接收。

macOS待目标机器同源码复验；真实 Houdini/Nuke、HY3/模型、视觉、生产接收和新安装包分别 NOT_RUN。本批无提交或推送，旧移交包、冻结日志和此前证据未覆盖。
