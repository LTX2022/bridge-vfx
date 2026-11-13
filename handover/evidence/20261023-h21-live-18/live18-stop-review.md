# -18 监督器、停止与预算独立核查

结论：`LIVE18_FAILED_STOPPED_NO_RETRY`。已启动进程的停止回执与原始预算账本核查通过；工程 driver 失败，工程验收没有通过。

- 实际目录：`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-18-authorized`。
- scope SHA-256：`b6eaedd9eeb14233a4631d3ac8c4a8c941c2b0f736119a6f54ade7c7fb43a73c`；bindings SHA-256：`e46827eeaa3cb838c93f2c107c4fcbdee88383534cf5b48854b6660bb911771f`；文件实算匹配。
- 正式授权 scope，`project_color.colorspace=ACEScg`；预算为 `8 starts / 120s per operation / 600s total / 536870912 bytes / 1 heavy / 0 retry`。
- 账本共 8 条：每条 HMAC、seq、previous 有效，anchor 与末记录一致，state 等于 journal 末记录。accounting key 长度、受限权限及 scope 固定 SHA-256 有效；密钥仅在内存用于核查，未输出或复制。
- 共 3/8 票，累计 DCC 计费 `78.69885492324829` 秒；实际逻辑数据占用 `62,241,557` bytes，按 device/inode 去重。各票均低于 120 秒，总计低于 600 秒，数据低于 512 MiB，重型票据区间无重叠。
- 活动票据 `0`，未知停止 `0`；末序号 7 的 `closed_reason=ENGINEERING_DRIVER_FAILED`，封闭后没有新票据。独立审核错误为 0。

| 角色 | PID | DCC计费秒 | 原始停止结果 |
|---|---:|---:|---|
| alpha-husk | 46414 | 12.699989080429077 | succeeded / exit 0 / supervisor 0 |
| alpha-nuke | 46521 | 5.947853088378906 | succeeded / exit 0 / supervisor 0 |
| graph-worker | 46582 | 60.05101275444031 | succeeded / exit 0 / supervisor 0 |

每组原始 started/stopped HMAC 有效，schema/event/identity/PID 匹配，`started_sha256` 绑定原始 started payload；均为 `execution_protocol=1`、`observed_by=owned_child_wait`、`descendant_result_unobserved=false`、`stop_reason=null`。停止时间与准入和账本一致，没有少计时。两次 alpha 都有同 PID、argv、runtime nonce 的签名 runtime-ready 及 writer_process_binding；未运行新 OS 身份采集工具。

固定 POSIX 监督器拥有子进程，完成 wait 后还须确认进程组不存在才签 stopped。冻结 snapshot 的 owned_process SHA-256 为 `f5bb1269ffa4883fbde96e00b6136334395c0d3924da73b9310f6972926cbedf`；native_scope 为 `10f76b1f9587e01273028adf5ae0220870b6b4ff0bf469e6920d79704c87447c`。本次停止核查不以外部 PID 消失、signal 请求或 worker result 代替该签名路径。

原始 engineering-driver-state 的失败为 `ENGINEERING_OPERATION_NOT_SUCCESSFUL:RECONCILIATION_REQUIRED`，cleanup 为 `{}`；阶段提交 alpha/propose/build 均为 DONE。graph-worker 正常退出只代表该 worker 进程结束，不能证明图构建或工程完成。深层图构建失败原因由工程诊断另行核查。

本次读取的是 driver 结束后的原始账本，一次核查完成；未调用项目模块或 scope.snapshot/check/finish，未打开 SQLite，未生成任何项目 DB/WAL/SHM sidecar，未启动 DCC、native probe 或 retry。只写临时目录中的审核脚本与报告；没有修改 -16、-17、-18 原件及冻结源码。activation 转交及授权 HMAC 由 root 负责独立核查。
