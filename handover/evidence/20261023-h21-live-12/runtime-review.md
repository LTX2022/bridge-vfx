# 12 真实运行：独立身份、停止与预算验收

结论：**FAIL**。首个失败阶段是 alpha husk 的完整 writer 身份绑定；本轮另有“失败即停”时序偏差。**最终整组可信停止成立**，不等于工程验收通过。

| 项目 | 判定 |
|---|---|
| 11 review → 12 激活 → real_host 合同 | GO |
| 158 源码快照、174 source_freeze、175 immutable | GO，逐字节匹配 review、冻结清单与当前源码 |
| 实际宿主 main image/host anchor/完整 writer 身份 | UNKNOWN；绑定缺失，身份门 FAIL |
| 最终整组停止 | GO，原始 HMAC 认证的 owned_child_wait |
| 预算、首阶段拒绝、无后续派发/自动重试 | GO |
| 采集错误后立即停止当前作业 | FAIL，当前 husk 自然退出后才通过身份门拒绝 |
| Nuke、主 HIP/NK/EXR、视觉、M1、HY3、生产 | NOT_RUN / NOT_ACCEPTED |

直接核对原件，未依赖 execution-terminal 汇总作通过依据。56 项事实核对通过，包括 canonical HMAC、accounting 序号/前项摘要/末项 anchor、scope 与 review、nonce/argv 摘要、ticket/start/stop/计费绑定和原始文件封存。身份失败本身列为明确 FAIL，不混入核对通过数量当成功。

只使用 1 张 alpha-husk 票，PID 40601，监督器 PID 40597。5 条 accounting 记录签名链闭合；计费 14.783262014 秒，driver 退出 1、总时长 17.041498250 秒；目录复算 4,907,694 字节。预算仍为 8 启动、单次 120 秒、累计 600 秒、512 MiB、1 heavy、0 自动重试。票已绑定 stopped 摘要并关闭，unknown stop=0。冻结清单外没有额外 scope 票或下一阶段 start。

`started.json` 的 argv 摘要和私有 intent 命令一致，并匹配冻结 alpha preparation。预期 husk 是本机 H21.0.631 Mach-O，文件 SHA 和完整 stat 与冻结值相符。但签名 started 没有 `writer_process_binding`，因此实际进程主像、host anchor 与完整身份不可判为已证明。

签名诊断原字节显示 `/usr/bin/vmmap -w -interleaved -summary 40601` exit 0，stdout 3176 字节，完整非截断 stderr 474 字节。stderr 明确 `dyld has initialized but libSystem has not`，并报告无法找到目标 `libsystem_malloc`。这是启动期采集错误，**本次没有超时证据**；原非空 stderr 拒绝门生效，未忽略或豁免该输出。

“失败即停”存在独立时序偏差：vmmap stderr 最后时间为 09:59:33.232Z；started 文件 mtime 为 09:59:33.398566Z；签名 stopped 时间为 09:59:45.866576Z。相差分别 12.634576 秒与 12.468010 秒。前者是签入诊断的工具日志时间，后者是补充文件系统证据；不能当成精确的采集完成签名时间。停止回执 `stop_reason=null`、leader exit 0、`execution_result=succeeded`、`descendant_result_unobserved=false`，表明作业自然完成且整组已停止。身份门随后才拒绝，不应写成“采集失败时立即取消”。

对应冻结源码：

- `project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py:411`：`finish_start` 只签入采集错误，未设置 `stop_reason`；599–613 行继续监督循环。
- `project/control/snapshot/tools/run_alpha_calibration.py:418`：先等待整组退出，431 行才验证 writer 绑定；失败发生于签 alpha-output 和下一次 Nuke 启动之前。
- `project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py:277`：工具 exit 非零或 stderr 非空均拒绝，保留原诊断。

原 06..11 六目录共 1227 文件与本轮基线逐文件 SHA/字节/文件集合相同。executor 封存的 244 条原件均逐项匹配，12 scope 文件集合完整匹配。未复制私钥或环境；仅在本机内存读取作校验。未写 scope/源码，未运行 DCC、采样、stop、signal 或重试。

存在未认证的 alpha-chart.exr（142,212 字节），没有 alpha-output 或校准终态，不能作为已验收输出；主工程 HIP/NK/EXR不存在，Nuke没有启动。child stderr 另有 `HOUDINI_USER_PREF_DIR missing __HVER__, ignored` 61 字节警告；它与 vmmap stderr 拒绝不同，本次未改动。scope `host_started=false` 和激活/准备记录 `NOT_RUN` 是准备期字段，本轮运行事实以签名票与 start/stop 为准。

精确文件摘要与逐项事实位于同目录 `runtime-audit.json`。所有结论限于本次封存的 12 scope。
