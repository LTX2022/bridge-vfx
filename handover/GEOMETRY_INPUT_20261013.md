# G03 冻结输入正式传递与 Windows 作业传输修复

继续全16域 M1 软件准备，基于 HEAD `0a52552f5915375dfb0f3551e08928e9e624390d` 和此前有效未提交增量。没有提交或推送；真实 Houdini/Nuke、HY3、模型、仿真、缓存、渲染及视觉/生产验收仍未运行。

## 本批结果

G03 冻结文件现在可以经过实际生成控制端、持久图作业和受监督 Python worker，进入宿主的登记/初始化事务。两版软件正式流程使用实际编译器、SQLite、调度器、Windows 监督器/Job、TCP、保存与停止回执；只在底层 HOM/USD/进程启动边界提供显式替身。

- 生成器新增私有 `construction_input_manifest` 参数及 `--construction-input-manifest` 文件选项。配置先校验再创建工程；不增加模型公开参数或图 selector 字段。
- `GraphJobService` 冻结元数据，绑定 `frozen_inputs_sha256`，保存在原始 intent、inputs.json 和实际启动载荷。恢复消费原 intent，配置变化拒绝；同 request 不重新执行作业。
- 每批最多32个本地文件；rest 基准64KiB，其他单文件8MiB，总计32MiB，元数据64KiB。拒绝 UNC/ADS、符号链接/reparse/hardlink、越界和非有限值；按描述符、文件/祖先身份、声明大小与 SHA 有界核验，不能修改声明去适配漂移字节。
- worker 核对启动载荷与持久输入，一致且文件有效才建图。专用初始化入口再次验证并返回输入摘要；G03 的原有任务/根/版本/帧、实际源几何和节点登记校验继续生效。
- 正式运行发现图 worker 的通用场景身份缺少 G03 所需任务/PID/nonce。补充身份来自已有 producer 的实际监督器启动回执和进程身份检查，保留当前根租约的 session/generation/epoch，不用测试预填身份代替正式来源。
- 独立审查发现合法40KB元数据会让 Windows argv 超限。小载荷保留 `--job`；超过上限使用自有 attempt 的 `worker-job.json`、文件 SHA 和短路径参数。文件有界读回、摘要和目录归属在调度器 arm 前核验，worker 再核验；旧 CLI 保持兼容。Windows 限制依据见 [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)。
- 正式重复请求又暴露了同一完成 HIP 被再次加载、继而触发 `SCENE_EPOCH_CHANGED`。成功打开并绑定后，在当前控制器实例保留完成事实；精确作业/产物/拓扑摘要及实际宿主身份一致才复用。文件变化、身份变化拒绝；重试不再加载或绑定场景。缓存不授予新 PID 或控制器重启后的登记权威。

## 实际验证

原命令、失败日志、解释器/系统版本与前后源码摘要见 [证据索引](evidence/20261013-geometry-input/README.md)；当前绑定见 [source-binding.json](evidence/20261013-geometry-input/source-binding.json)。

本批归档111个原件、11,789,712原始字节并绑定25个相关源码文件；最终两版生成快照各134文件，与当前源码没有差异。

| 运行 | 实际结果 |
| --- | --- |
| 原 worker 复现 | 补齐底层 API 后，两版均因冻结基准未传递而没有初始化 value；退出1。更早夹具 API/身份不足失败仍保留为诊断 |
| 第一组定向 | 29方法，0失败/错误/跳过，25.297秒，源码前后不变，退出0 |
| 正式 v1/v2/v3 | 分别保留测试取错字段、预先打开控制器后修改 run manifest、实际图 worker 身份不足的失败；不能计通过 |
| 正式 v4/v5 | 实际建图、保存、停止及40KB文件传输成立；额外重复请求因重开场景失败，整体退出1 |
| 中心 core-v1 | 100方法诊断包含13个导入夹具重复方法，并因同步模块名称错误整体退出1；没有当作通过数量 |
| 中心最终 core-v2 | **95方法**，0失败/错误/跳过，50.500秒，源码前后不变，退出0；覆盖新输入/生成器/worker/传输、G03 Host/Registry、同步及正式边界 |
| 正式 v6/最终 | 各1方法覆盖 H21.0.631、H22.0.429；最终57.468秒，源码前后不变，退出0。实际 worker 输入/初始化摘要一致、40KB文件运输、保存与确认停止；实际 TCP 宿主为不同 PID。重复 MCP 请求保持同 operation、同宿主身份/scene epoch、同场景转换日志，只有一个 worker attempt |

正式测试先通过真实 pipeline 的任务创建 API取得固定任务 ID，再配置明确匹配该任务/图根的底层 rest 文件，随后启动正式生成 server；没有绕过已打开控制器的 run manifest 漂移保护。未重新 apply G03 来制造初始化证据。独立审查由未参与实现者完成，初次发现与整改反例原件分别保留；[最终限定结论](evidence/20261013-geometry-input/review/CLOSURE.md)关闭Windows传输P2，身份hook及幂等handoff未发现新具体阻断，独立handoff/scene-epoch四方法通过。复核没有参与实现，也没有启动正式进程。

归档只保留必要文件，排除签名私钥及监督器环境。原 signed start/stop 记录在运行期由实际生命周期逻辑验证；缺少私钥的离线副本不能独立重验签名，文件 SHA 只证明原件字节一致。

## 当前未完成与下一步

本批证明的是 worker 的认证 rest 输入、G03 参数初始化及作业/重试边界，仍是 `BLOCKED / parameters_only`。它不证明 VEX 实际变形、copy/downstream 消费、跨帧行为，或新 PID/nonce 中恢复服务端登记。下一步优先用自有保存/场景转换事实建立新实例登记链，不能凭 userData 或内存缓存获得权威。

20项批准控制仍是5项有条件映射、15项 blocked；B组合输入与实现、公共 husk/writer/output/AOV/filter/alpha 事实、完整 Nuke/降噪消费、48+2、54门槛、最终全量、安装生命周期及全域独立接收尚未闭合。此前输出/Crowd/RBD/材质增量和旧冻结证据保留，没有无变化重复标准全量。macOS、真实宿主、模型、视觉及生产验收分别维持 NOT_RUN。
