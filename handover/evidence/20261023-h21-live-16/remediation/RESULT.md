# H21 16 轮 graph-worker 最小修复

16 轮仍为 `GRAPH_EXECUTION_UNPROVEN / RECONCILIATION_REQUIRED`。17 条 journal 全部为 COMPLETE；最后 light 创建请求为 `light`，真实回执为 `light::2.0`，随后严格类型比对停止，未产生下一条 INTENT。该创建完成不代表整图完成。原 317 文件字节保持不变。

H21 安装的 HOM 文档声明 createNode 默认允许优先类型替换，`exact_type_name=True` 才保证声明类型。静态 HDA 库在本图的 light、rendervar、mtlxnormalmap 三处同时保有基名与 ::2.0 定义。后两处真实类型未观察，不推断为已发生故障。

正式 GraphExecutor 创建请求及 journal intent 显式绑定 exact_type_name=True；addon 严格校验布尔并转交 HOM。未指定该参数的现有调用保留原行为；类型、路径、租约、身份、回执比对均保持。catalog、v1 与域控制字段合同未改。

软件底层夹具注入上述三处优先类型行为，默认创建均复现 COMPLETE 后类型失败；精确创建完整通过。此前已修生产监督器使用的 -B 参数也已与旧恢复测试 helper 的严格预期同步。新增参数随正式 RPC 请求及原生生产回执的现有哈希绑定，发布装配从 packages 和插件原路径复制，无额外 controller 镜像文件。

验证：Py3.11 正确权限 88 例运行中 86 例通过、2 例因旧 helper argv 失败；仅修 helper 后两例复验均通过，合并覆盖为 86+2，未声称单次 88 全绿。Py3.14 直接类型及租约核心 21 例通过。新目录中的一条完整正式软件链在 59.937315 秒通过，8 票均正常结束；真实 OS 身份观测保留，HOM/USD/像素与 DCC 进程仍为明确 Python 替身，native_execution=NOT_RUN。没有模型调用或自动重试。

前置环境失败证据保留：非规范临时路径；sandbox 的 ps EPERM / PROCESS_IMAGE_TOOL_UNAVAILABLE；旧测试 helper 的 -B argv 预期。已封闭软件目录未复用。

最终 7 文件清单及前后 SHA256 见 after-sha256.json；change.patch 可从 before 原字节完整应用并得到 after；patch-roundtrip.json 验证全部 7 文件一致。后续 17 的冻结和独立审查由协调者完成，此包不激活任何真实尝试。
