# 第 16 轮真实结果与第 17 轮软件候选独立验收

结论：第 16 轮真实工程未闭环；第 17 轮软件候选可接收。两层结论独立，修后真实 Houdini／Nuke 工程仍为 `NOT_RUN`。

## 第 16 轮真实结果

按用户明确批准的 review15 `884782efbbc1f830f21a34d81ce7b259c72e29d93a243a57bf642b1e797df015` 激活的范围与原始 activation HMAC、scope、bindings 一致。159 个执行源码匹配批准快照，175 个冻结记录有效。8 条账本记录的签名、序号、前链、anchor 与末态一致。

实际启动 3/8：alpha-husk、alpha-nuke、graph-worker。三组原始 started／stopped 的 HMAC、身份、PID、started 摘要与停止结果一致，均由 `owned_child_wait` 观察；无未观察后代结果，活动票与未知停止均为 0。累计 DCC 计费 32.799007654 秒，最终 `ENGINEERING_DRIVER_FAILED`，无续接或自动重试。停止报告记录 9,693,338 字节；317 文件封存逻辑占用 9,758,874 字节，两份既有 SQLite SHM 共 65,536 字节已纳入封存。两种时点均低于预算，原始执行回执未改写。

真实 alpha 校准的原始数值与关联 alpha 结论一致；5 个 EXR 的大小、摘要、640 条扫描线覆盖、完整解码与有限数值范围均核对通过。预览仅呈现校准图与黑白底探针。主工程 HIP、NK、main EXR 与 Nuke 主输出均未生成。

从原 DB／WAL／SHM 的临时副本核对：journal 有 17 条 COMPLETE，最后一条请求 `light`，结果为 `light::2.0`，路径一致且原生命令无错误。正式图严格类型比对随后拒绝该结果；公开 graph 结果为 `construction_executed=false`、`reconciliation_required=true`、`GRAPH_EXECUTION_UNPROVEN`。wrapper exit 0 不能作为图构建成功。

06 至 15 的 2,019 个原件及停止后的 16 共 317 个文件，最终逐文件大小、SHA-256 与集合复核均未变。

## 第 17 轮软件候选

最终 7 文件的 before、after 副本分别匹配清单，after 与当前源码摘要一致；补丁往返证据与摘要一致。正式运行源码中的改动为 GraphExecutor 精确类型创建与 intent 绑定、addon 布尔校验与 HOM 透传、软件装配 API 对应参数；其余为明确软件边界、回归与旧 helper 的 `-B` 预期同步。节点类型与字段合同、严格读回、身份、停止和预算检查仍保留。

原生 H21 安装的 HOM 源码摘要已核对，说明默认创建允许优先定义替换，精确参数固定声明类型。软件红灯覆盖 light、rendervar、mtlxnormalmap 三种相同机制；后两节点在真实 16 中未到达，未把静态存在或软件复现写成其真实运行结果。

测试证据为 Python 3.11 上原 88 例中的 86 例通过，加仅修 helper 后两例复验通过；不是单次 88 例全绿。Python 3.14 类型及租约核心 21 例通过。旧 helper 的失败因果与修后两例绿灯、源码摘要对应。链 01 的 `PROCESS_IMAGE_TOOL_UNAVAILABLE` 环境失败原件保留。

链 02 的单次正式软件链 59.937315 秒通过，13 个阶段 DONE、8 张票据、7 组监督器停止、4 份 runtime-ready、2 个登记产物，签名账本链一致。其 OS 进程身份观察使用真实工具；HOM／USD／像素与 DCC 进程使用明确 Python 软件边界，没有 image model 或 Popen bootstrap。产物来源为 `software_test`，原生内部状态 `NOT_OBSERVED`，真实 DCC `NOT_RUN`。运行前后 175 个冻结记录与当前文件一致，159 个执行源码与当前源码及候选 17 完全一致。

17 为 `PREPARED_NOT_AUTHORIZED`、0 票、无 started 回执，预检 `PREPARED` 且 blockers 为空；仅生成指向未来 18 的 review，18 目录不存在。未把候选零票视作新资源授权。

| 绑定 | SHA-256 |
|---|---|
| 17 scope | `a60e8000865c390946ef48110612707a29ca010ee084696cbd3f6ba0846d1633` |
| 17 bindings | `37cb46bfeb0b7dbebc970c9d2871ffce582ac5eed19ff1dfa09a467c34f859fb` |
| 17 review | `417b13638e217a6ff2b3453a930b028a5c38a53921e6204d4fdf44862ae0e118` |
| 7 文件清单 | `273e077ee0d4e8e0fa851f77265d4f970b768c2b8b300120cbbc2cb9eaad197a` |
| 补丁 | `9ef1ab943737b4816dea8650136dfc5c743d039ea5f6874b7f99fc23c1c058d7` |

机器验收见 `candidate17-final-audit.json`，`passed=true`。本审查仅只读核对原件与临时副本、摘要、签名和 EXR 数据，未运行测试、原生探测或 DCC，未修改冻结目录。
