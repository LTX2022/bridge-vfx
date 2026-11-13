# R05 可信保存与新实例恢复（2026-10-13）

本批继续全16域M1的软件修复，补齐上一批明确未完成的R05 verified-checkpoint正向恢复；不代表全域完成。Git基准仍为 `0a52552f5915375dfb0f3551e08928e9e624390d`，保留既有全部改动和历史失败，不自动提交或推送。

## 实现与可信边界

- 保存时从当前宿主私有authority及实际HOM收集完整checkpoint：实际task/root、同build身份、版本、布局、连线、节点状态、FPS/帧、全部carrier门控/snippet和solver参数、完整basis/program字符串。checkpoint为有界完整JSON，上限2MiB；scene-contract的整体2MiB预算另行保留，超限拒绝，不截断。
- checkpoint同时进入场景manifest和正式保存合同。恢复仅发生在已登记保存回执、已核验HIP字节摘要、场景合同、当前根租约及当前宿主身份的私有scope内。新PID/nonce和实际节点session可变化；实际参数、基准、随机seed、登记、布局和消费几何须保持一致。
- 恢复仅重新签发当前实例的私有记录，不重新initialize、apply，不写原生参数或userData。临时登记持有opaque事务，末端再次核对完整事实及HIP摘要/身份；失败撤销自己的登记，并保留其他根和CAS后继记录。
- `agent.fx.collect_evidence` 在保存的RBD velocity登记存在时直接读取当前实际载体/solver输入及实际登记值；保留activation原读回，组合场景另加`initial_velocity`字段。失败仍恢复原帧，不从请求生成成功几何。
- 普通graph-trial摘要或embedded userData不能授予R05恢复权限。新图无登记可正常handoff；已保存R05需由正式保存合同恢复，或已有当前实例私有authority证明其原生记录。保留G03现有实现和测试，不扩大其证据范围。

## 本批验证

解释器为项目Python3.11.9，系统Windows10.0.26300。最终命令、退出码、428项源码前后摘要和原始日志见 [本批源码绑定](evidence/20261013-rbd-reopen/source-binding.json) 与 [原件索引](evidence/20261013-rbd-reopen/index.json)。中央runner不含`tools/native_schema_test_boundary.py`；归档单独核对其当前摘要与上一R05绑定一致，不伪称本组已记录该文件的运行前后摘要。

[Git内封存证据](evidence/20261013-rbd-reopen/README.md) 保留195份原件、7,587,175原始字节，归档与解码摘要均已核对；不含运行签名密钥或认证配置。

| 最终范围 | 结果 |
| --- | --- |
| `outputs/all-domain-20261009/run_tests.py rbd-reopen-20261013-integration-final-v2 test_rbd_checkpoint test_rbd_reopen_addon test_rbd_reopen_review_guards test_controller_entry_client_sync` | 34方法、34唯一ID，0 failure/error/skip，退出0，156.359秒，源码前后一致 |
| `outputs/all-domain-20261009/run_tests.py rbd-reopen-20261013-formal-final-v2 test_rbd_authority_process` | 1方法覆盖两版本，0 failure/error/skip，退出0，93.078秒，源码前后一致 |

正式命令设置`BRIDGE_TEST_RBD_AUTHORITY_ARCHIVE=outputs/rbd-reopen-20261013/formal-final-v2`解析后的绝对路径，均以项目`.venv/Scripts/python.exe -B`执行。

| 软件版本 | 原PID→新PID | 实际停止及直接读取 | 当前生成副本 |
| --- | --- | --- | --- |
| 21.0.631 | 5648→28908 | 经OwnedProcessHandle核验的原PID退出、child wait成立、Job active=0；新nonce，公开读回velocity_variance=0 | 135代码文件，根源码0差异 |
| 22.0.429 | 6132→33204 | 经OwnedProcessHandle核验的原PID退出、child wait成立、Job active=0；新nonce，公开读回velocity_variance=0 | 135代码文件，根源码0差异 |

正式底层packed几何为固定原始事实，与请求无关。零幅度实际v/w及形状保持；非零请求因该底层没有执行VEX而拒绝并回滚。新PID直接读回只证明零幅度软件恢复；不证明VEX、Bullet或真实仿真。

## 独立复核与失败保留

独立reviewer未参与对应实现。三项最终门槛为R01失败仍残留`COMPLETED`、R02普通graph handoff可授予RBD权威、R03末端原生读取导致门控/几何/HIP事实陈旧。现在完成上下文接入既有exact-record CAS恢复；graph handoff不再签发恢复权威；末端重复完整checkpoint，包含实际configure/carrier/solver输入几何，再核对当前HIP摘要及身份，随后才移除token。永久反例和 [最终独立复核](evidence/20261013-rbd-reopen/raw/outputs/rbd-reopen-20261013/review/CLOSURE.md) 保留，不把probe进程退出0或并发源码变化当作验收PASS。

异常正式回执只用于拒绝测试。两版新实例缺checkpoint返回`RBD_REOPEN_CHECKPOINT_REQUIRED`，篡改后重新摘要的合同仍返回`RBD_CHECKPOINT_INVALID`；实际底层trace确认正常直接读回无参数/userData写入，拒绝阶段在load完成后也没有这些写入。单元和独立反例另覆盖持久化后异常、末端身份/门控/HIP字节/几何漂移及CAS后继保护。

基线缺接口1方法的3子项失败仍保留。首次集成170次方法执行（157唯一ID，其中13次为导入的TestCase重复）没有测试断言失败，但在R03整改时源码改变，runner退出1，不能计为当前通过；首次正式1方法98.563秒通过仅绑定整改前源码，保留为阶段证据。重复导入已改为module引用，末端几何整改后只复验受影响34方法及正式两版，不重复无变化的旧97项和G03组。初期只读HIP写入的PermissionError仅为诊断；永久反例实际改变自有临时HIP字节，不能用该权限错误替代字节漂移证据。

HOM多节点没有原子快照，本批通过重复实际观察拒绝已覆盖的迟到变化；不宣称消除所有原生并发窗口。单次阻塞原生调用的时限仍依赖监督器，不把checkpoint预算当作原生API内部内存保证。历史同PID新API实例与本批实际进程生命周期分别报告。

## 未完成与下一步

R05非零VEX执行、Bullet初始化/activation消费、完整单位和属性保持、稳定随机分布仍缺原生事实。其余15控制、B组合、实际husk/writer/output/filter/alpha、Nuke与降噪、48+2/54、最终全量、安装及全域独立接收未完成；本批不更改领域可用性声明。

macOS为待目标机器验证；当前正式测试使用Windows Job实际停止字段，移植测试时必须改为真实POSIX进程组事实，不能填默认。真实Houdini/Nuke、WorkBuddy/HY3、模型、仿真、缓存、渲染、视觉及生产验收均未运行。
