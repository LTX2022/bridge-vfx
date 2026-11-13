# ordinary positive-01 环境拒绝与报告异常

独立结论：该次执行是首个工具 spawn 被 EPERM 拒绝后的失败关闭；它不是 native collector 阳性，也不是原生 vmmap 启动警告复现。生产 18 项源码未变，06–12 共 1457 原件大小/摘要仍全部匹配。

原始 started/stopped 的 HMAC、完整 identity、PID、argv 摘要及 stopped.started_sha256 全部独立核验有效，公开复制与私有原件逐字一致。诊断准确保留 `/bin/ps`、stage=spawn、os_errno=1、exit_code=null、stderr_complete=false，stdout/stderr 都是 0 字节。工具尚未启动，空 stderr 不能解释为一次 rc=0/empty-stderr 的成功采集。此时没有 runtime-ready 文件、没有 writer binding，child stdout/stderr 亦为空，原链没有到 vmmap。

stopped 保留 owned_child_wait、exit_code=-15、execution_result=failed、SUPERVISOR_WRITER_COLLECTION_FAILED，并与认证 started 绑定。它支持失败执行和可信停止事实。该次 driver 在组状态检查后，构造摘要时对 ready=None 下标访问，抛 TypeError，未写出 result.json；这属于报告脚本错误，不能反向擦除已签停止，也不能记为产品就绪通过。

本次 profile events 在 driver 异常之前未持久化，现存 failure-audit 已明确承认这一限制。因此无法独立重建该次 TERM 请求时间或 same-loop 时序，不补造事件，不把 started.observed_at/stopped.observed_at 的差值当签写/信号时序。源码与已有核心绿例已证明同轮调度；新的实际受限验证必须保留 trace 后才报告该次实际时序。

`ordinary-positive-01-preservation.json` 封存的 11 个公开文件全部匹配大小/SHA-256；包含的旧 runner 源码副本 SHA 为 `8a455c3ff3d842bced58fe5e31445d17e3ff52a2578f1b388da2647d902e7637`，与执行前独立读到的摘要一致。副本说明准确标为从 report-only None-safe patch 反向恢复，未声称另一次执行。私有 intent/env/receipt.key 不在公开清单，报告仅保留必要白名单信息。

root 已限定后续外部执行条件变更和 fresh positive-02；None-safe runner 是验证脚本修改，先持久化 trace，不改生产源码。后续实际阳性、controlled-error 和软件八阶段各使用其自己的原始目录/回执，不能覆盖或重命名本次失败为成功。当前报告只认证本次失败归因和封存完整性，后续结果仍待实际原件。

计算明细：`ordinary-positive-01-independent-audit.json`。本角色没有运行或重试目标、原生采集或 DCC。
