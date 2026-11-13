# -16 监督器、停止与预算独立核查

结论：`LIVE16_FAILED_STOPPED_NO_RETRY`。三组已启动子进程均有有效的原始签名停止回执，停止与账本核查通过；工程 driver 失败，不能据此判为工程验收通过。

- 实际目录：`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-16-authorized`。
- scope SHA-256：`f28c8e8d60d2df83e10bed534b62997519688d211adaf724ad7a092c1b06cf1a`；bindings SHA-256：`f0f896a54775c47995e1477fa1fbf10ee7e5f8d52e4d34ad193bc38a3dad70d7`；文件实算均匹配。
- scope 为正式已授权状态，`project_color.colorspace=ACEScg`，预算 `8 starts / 120s per operation / 600s total / 536870912 bytes / 1 heavy / 0 retry`。
- accounting key 的长度、受限权限和 scope 固定 SHA-256 有效；私钥仅在内存用于核查，未输出或复制。8 条 journal 记录的 HMAC、seq、previous 均有效；anchor 与末记录一致，state 等于 journal 末记录。
- 共 3/8 票，累计 DCC 计费 `32.79900765419006` 秒，实际逻辑数据占用 `9,693,338` bytes（按 device/inode 去重），未达到各项预算；重型票据区间无重叠。
- 最终活动票据 `0`，未知停止 `0`。账本末序号 `7` 的 `closed_reason=ENGINEERING_DRIVER_FAILED`，封闭后未增加票据。

| 角色 | PID | DCC计费秒 | 原始停止结果 |
|---|---:|---:|---|
| alpha-husk | 29011 | 13.165288925170898 | succeeded / exit 0 / supervisor 0 |
| alpha-nuke | 29214 | 6.250664949417114 | succeeded / exit 0 / supervisor 0 |
| graph-worker | 29293 | 13.38305377960205 | succeeded / exit 0 / supervisor 0 |

每组 started/stopped HMAC 有效，schema/event/identity/PID 互相匹配，`started_sha256` 匹配 started 原始 payload；`execution_protocol=1`、`observed_by=owned_child_wait`、`descendant_result_unobserved=false`、`stop_reason=null`。停止时间与准入和账本一致，账本不存在少计时。两次 alpha 还具有同 PID、argv、runtime nonce 的签名 runtime-ready，以及签名 writer_process_binding；未运行新的 OS 身份采集工具。

POSIX stopped 的可信停止含义来自固定监督器：拥有的子进程完成 `wait()` 后，再次 `killpg(pid, 0)` 确认进程组已不存在才签 stopped。没有使用外部 PID 消失、worker 的 result 或 signal 请求替代该证明。当前 authoritative/mirror 的 owned_process SHA-256 都为 `f5bb1269ffa4883fbde96e00b6136334395c0d3924da73b9310f6972926cbedf`；native_scope 都为 `10f76b1f9587e01273028adf5ae0220870b6b4ff0bf469e6920d79704c87447c`。

工程失败的公开原件是 driver 的 `ENGINEERING_OPERATION_NOT_SUCCESSFUL:RECONCILIATION_REQUIRED`；本轮 graph result 为 `construction_executed=false`、`reconciliation_required=true`，diagnostic `GRAPH_EXECUTION_UNPROVEN`。graph-worker 进程 exit 0 只代表 wrapper 正常结束，不证明图构建成功。更深层软件根因不在本次监督器核查范围内。

核查以最终原始账本读取一次完成；未调用 scope.snapshot/check/finish，未写 scope、账本、回执或源码，未启动 DCC、探针或 retry。未检查或修改 -06 至 -15 历史原件。授权 activation 的转交与 HMAC 由 root 独立核查，此报告不替代该层结论。
