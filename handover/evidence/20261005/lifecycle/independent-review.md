# SoftwareGraphResources 生命周期有限独立审查 · 2026-10-05

最新状态：**P1-L02、P2-L03 已限定关闭；当前源码正常 pending 与实际 closed-stdout 自有 Python 进程退出隔离获有限接收，未发现新增确定缺陷。** 最终日志复核见末节；完整 MCP/业务恢复/全域生命周期不关闭。以下保留初次发现及源码预复核的阶段依据。未参与实现、修改源码、运行测试或受控进程；producer_binding 接线不在本次生命周期审查范围。

**P1-L02 — pending 的强制自身退出被错误输出/flush 故障绕过。** 位置 `tools/prepare_workbuddy_graph.py:213`、`:220`–`:222`（生成 server handler）。最短反例：真实 software worker pending，原异常已带 `resource_cleanup.retained=true`；MCP 读端关闭 stdout，错误 print 或后续 stdout.flush 抛 BrokenPipeError，亦或 stderr.flush 抛 OSError。没有 finally 保证 `_os._exit(2)`，新输出错误覆盖原错并离开 handler，进入普通解释器清理，失去此补丁为 pending native API/目录提供的退出隔离。应先确定 retained，确保错误报告和 flush 即使失败也必须走自身强退，普通非 retained 分支仍保留原语义。此为确定控制流缺口；未新跑反例或宣称已有实际崩溃。

**P2-L03 — 正常正文后的 cleanup/观察异常丢失 retained 事实。** 位置 `workbuddy_assembly.py:1815`–`:1817`，消费点 `tools/prepare_workbuddy_graph.py:216`、`:219`。最短反例：正文与 facade close 正常返回，owner.cleanup 再次读 shutdown_snapshot 时抛 sqlite3.OperationalError，或转交的 TemporaryDirectory.cleanup 抛 OSError。owner 仍未 released，却直接抛只带 software_resources 的 cleanup_error，绕过后面的 resource_cleanup/snapshot-fallback；生成 server 输出 null、按普通 SystemExit 处理，不报告实际保留与观察失败。应在无正文错误的异常路线也带同一 retained/未知观察合同，同时保留清理错误原实例。该反例确定的是错误事实丢失和退出分支选择；不把此前已确认线程停止的正常路线说成实际 pending 删除事故。

已有正常路线：全局 owner 强引用在 pending 时保留 hou/nuke/scene-state、显式环境及转交目录；新 owner 被拒绝，同 owner bind 遇已绑定 controller 未关闭/pending/未知也拒绝。cleanup 检真实线程与持久状态，未关闭/仍活跃/未确认不释放；真实结束后才清目录、恢复模块与环境，成功 cleanup 可重复调用。shutdown_snapshot 不发停止命令，原 close 两字段/默认 1 秒及原作业预算保持。正文已有错误时保留原实例，并附 close/resource cleanup 事实。

当前四项短日志 `final-threads.log` 为 **4 tests / 4.453s / rc0**：pending 正常/正文异常两路线均持有 API、环境、目录，实际 worker 后续文件写入成功；线程结束后才释放，另一 owner 和同 owner 的 pending 重新绑定拒绝；完成线程的正常/正文异常清理通过，原默认与剩余预算对照保留。上述测试未覆盖 L02 输出故障、L03 正常正文后的观察/清理故障。

`isolated.log` 为早先有界隔离 harness **1 test / 1.464s / rc0**，不是整个 generated MCP server 生命周期。实际 handler 提取自生成模板并在真实自有 Python 子进程执行；stop 投影中工作 PID 26340 与 started/live/stopped 相同，identity/process_birth/Job 一致，started_sha256 独立重算匹配，child_wait_observed=true、owned_child_wait、Job active=0、退出 2。harness 通过原 process.receipt 验证后导出投影；本轮不读密钥重新验签。实际停止前 API/环境/目录及文件句柄持有，atexit 未跑，停止后才 rename；作业 RECONCILIATION_REQUIRED/stop_confirmed=0、槽 active=1 没有被伪释放，父端资源不变。

**最终同 owner/观察/BaseException 整改后的独立进程复验 NOT_RUN；观察故障与 KeyboardInterrupt 两分支只 AST，仍 NOT_RUN。** 完整生成 server MCP stdio 正常/异常生命周期及 Main 当前源码 probe 也未作为已通过证据。签名 Job stop 的早先投影不能提升为最终四源进程 PASS；修复 L02/L03 后仅需有界补这两处与当前正常路线。

| 当前四源（与 source-sha.json 匹配） | SHA-256 |
|---|---|
| graph_jobs.py | `0dd2dc3bf5456a28a34298eb3365c95561b2033615d52d45625f8f951eff9c25` |
| workbuddy_assembly.py | `a76fa5128fce36f864be46a5772774c393a7435e9b5f24a1649843f32e1958bb` |
| tools/prepare_workbuddy_graph.py | `155de35c796dbbaeeb03f3f1a45f2b19b5d8644b86ca1d55ee651feec08bb204` |
| test_graph_jobs.py | `68ff9aedef8c0c4f9fd1c457e9fe94090f25b90639b52b6a3421b5523a9889a9` |

before/current 摘要均匹配，独立只读重建 delta 与 lifecycle.patch 完全相同；首末四源未变。patch SHA `9466670afc80a5e9adf24284f01708b54988a4a736960aec0e73dd35bf1fecf1`；final-threads.log SHA `2c2b757e6bf65e2c52063556f91f67e033c238972657d8dba1bf67cf0aa2cd43`；isolated.log SHA `818320bbefa17b7be85abe8e975ae5bb897a322963ffb13132dcd50275dca7b7`；stop 投影 SHA `69000eab692969873cb574363cf00ffe6fdd87436c355f24a285e4b872b0b71c`。verification.log rc0 仅 AST；baseline rc1 中旧裸外层 cleanup 的实际提前删除反例成立，新 owner 接口尚不存在。

所有保留合同仅适用于转交 owner 的资源；外部裸 cleanup/直接改 sys.modules 不受此 API 管理。没有把线程退出、进程树退出、业务结果或全域验收混为一谈；full16/approval_recovery/真实 DCC 仍不升级 PASS。

## L02/L03 源码增量预复核（Main 整改）

两处最小修复对应原发现，**源码层成立，无新增确定 P1/P2；待实际受控日志后限定关闭**。从本报告初次 lifecycle.patch/before 只读还原旧源码，与当前比较：assembly 仅调整异常保留小块；generator 仅调整错误 handler。不实现、不运行验证。

L02：handler 先计算 retained，非 retained KeyboardInterrupt 原样传播；错误 print/JSON 编码及 stdout/stderr flush 都进入 try，finally 对 retained 必须 `_os._exit(2)`。原 BrokenPipeError/OSError 绕过退出路径被封住。报文传输失败时不承诺报文送达，但自身隔离退出不再依赖传输成功。

L03：owner 在进入 __exit__ 时保存 original_error；正常正文的 cleanup 异常保留其原实例，并走 resources/retained/snapshot-fallback，最后抛同实例。已有正文异常继续作为主错。观察失败输出 pending/unconfirmed=None、实际 retained 及观察错误类型，未猜测停止成功。

新增 test_software_resource_failures.py 3 个方法：实际 TemporaryDirectory 对象 cleanup 入口注入故障并检查目录仍在、原异常实例、owner retained 和随后正常清理；cleanup/snapshot 故障对照检查 None 事实；实际生成 AST handler 在 RuntimeError/KeyboardInterrupt 与 print/stdout/stderr 故障组合下验证退出边界；非 pending KeyboardInterrupt 保留实例且不调用 _exit。未 mock facade 或 producer 成功。_exit 明确由边界 mock 代替，故它们不证明真实自身退出/Job stop；观察故障是注入单元路线，不是实际 SQLite 故障实跑。

主控报告该 3 项 0.039s/rc0，本轮已审源码但尚未收到对应独立日志路径。完整观察故障/KeyboardInterrupt 生命周期、最终 controlled pending、生成 server 与正式 metadata 入口仍 NOT_RUN/待日志；旧 isolated 投影不升级到当前 SHA。

| 本次读取最终源码 | SHA-256 |
|---|---|
| workbuddy_assembly.py | `f1e62d47ecc274bd2b75acf827047f2a4cdc2fb62910bb111bc21b033b5fac49` |
| tools/prepare_workbuddy_graph.py | `535c76cd1a26bfafd7a2b3c30bd1dee496b6e9463d9f7727b966eca9f3b27d99` |
| test_software_resource_failures.py | `1ec69f50ca51541f4b5a87d14f20b6c22c5e44e74b9e24e2ea434f67dcf90ddc` |

三个摘要首末只读取样一致。后续仅读对应实际日志和必要受影响增量，不重新扩审旧生命周期组。

## 最终当前源码受控日志：限定关闭 L02/L03

只读 `isolated-current.log`、`isolated-current-result.json`、两份 owned-stop-current 投影、run_current_lifecycle.py 及 harness 最小增量。**5 tests / runner 1.821s / 外层 1.859s / rc0，0 FAIL/ERROR**：两条真实隔离 Python 进程，加三个 failure 单元方法。运行前后所列 7 个来源摘要相同，当前文件逐项只读核对全部匹配。

正常 pending PID **29916**、实际关闭 stdout 的 pending PID **7324**：started/live/stopped PID、nonce/owner、process_birth、Job 一致，started_sha256 独立重算匹配，停止发生在 started 之后；两例均 owned_child_wait、child_wait_observed=true、exit_code=2、Job active=0。父端在放行退出前实际观察持有 API/环境/目录和工作文件、线程 alive/pending=1；认证 process.receipt 读取后才检查未跑 atexit、目录仍在并 rename。业务 RECONCILIATION_REQUIRED/stop_confirmed=0、heavy slot active=1 断言仍成立，没有以控制进程退出伪造业务完成或释放未知槽。投影由原认证读取导出，本轮未读密钥重新验签。

harness 的 worker 正文与前次已读版本相同；只新增 closed-stdout 选择、可选新 evidence 路径及拒绝覆盖，runner 选择正常/故障两例。故障真实调用 sys.stdout.close() 后执行当前生成 handler，覆盖的是实际 closed-stream 写失败；BrokenPipe/stdout flush/stderr flush 组合由 failure 单元对照覆盖。该 handler 在真实子进程中调用真实 `_os._exit`，没有 mock 退出。由此 **L02 输出故障不能绕过退出的原缺口限定关闭**。

三个 failure 方法在此次日志均通过：正常正文的实际 TemporaryDirectory 对象 cleanup 故障入口、注入观察失败、原错误实例/retained/None 事实及后续 cleanup，对应 **L03 错误事实丢失限定关闭**；handler 的 RuntimeError/KeyboardInterrupt 故障组合与非 pending KeyboardInterrupt 原样传播成立。观察错误仍是注入单元证据，不是实际 SQLite 故障或完整 KeyboardInterrupt 进程路线。

最终主审 SHA 保持预复核值：assembly `f1e62d47ecc274bd2b75acf827047f2a4cdc2fb62910bb111bc21b033b5fac49`；generator `535c76cd1a26bfafd7a2b3c30bd1dee496b6e9463d9f7727b966eca9f3b27d99`；failure tests `1ec69f50ca51541f4b5a87d14f20b6c22c5e44e74b9e24e2ea434f67dcf90ddc`。graph_jobs 执行依赖 SHA `a1b4f14b23bb4fe6c2e1dcc90263c5f8329db9a71e79da4c6522b0e1a55a010a`，仅核摘要；其新增 public native locator 由 Curie 另审，本报告不扩审该改动。

| 本轮实际证据/新增 harness | SHA-256 |
|---|---|
| isolated-current.log | `79b720605c561f3f212c070764deee6adc9b53480340b40d0981116f7c2330f7` |
| isolated-current-result.json | `03a88a32ae5ae2df910f00b2be165fc5675478261626831ce3f19f345f7eb43e` |
| owned-stop-current-normal.json | `ee1e7865dee9da9913b1a7888942d7d442099997793d63e712fd0845eb04c312` |
| owned-stop-current-closed-stdout.json | `c63b1df0fa356066600338f29d4f3e86e52b1bfdc4015ba1a783637b8b28c085` |
| owned_pending_probe.py | `03a637d52363dd83647c0a484c6b629efd909333d2fafbfc4e9d5b8043514d70` |
| test_owned_lifecycle.py | `3799ecee6552ab383db38ed9e12bf14b8ef3d148405d410fcafc9a4192d36d85` |
| run_current_lifecycle.py | `fe57fccf65d37ae5cb9d261619fd0f7e72aca97c0817b6abb306707cae59df7e` |

剩余限制：完整 generated server MCP stdio 生命周期、完整观察故障/KeyboardInterrupt 受控进程路线仍 **NOT_RUN**。两例验证实际 owner/context 与提取的生成错误 handler，不等于整个产品入口。业务未知槽后续核对/恢复未关闭，metadata/registry/Nuke/全域验收不因本轮接收升级；真实 DCC 未验。审查未运行新测试/进程、未修改生产实现，只有本报告更新。
