# G03 新实例恢复批证据

当前结果见 [修复报告](../../GEOMETRY_REOPEN_20261013.md)、[源码绑定](source-binding.json) 和 [原件索引](index.json)。共197份原件、原始40,000,848字节；大文件采用可还原 gzip，索引分别记录原始与归档字节数/SHA。两个最终生成快照各134项，当前源码摘要差异为0。

正式验收原件是 `geometry-reopen-20261013-fixes-final`（36方法）与 `geometry-reopen-20261013-formal-current`（1方法覆盖两版）的 JSON/log。均退出0、无失败/错误/跳过、源码前后不变。两版新PID/nonce、旧宿主确认退出、保存参数和直接读回记录保存在 `raw/outputs/geometry-reopen-20261013/formal-current/`；HIP、原始rest输入和必要监督器/作业日志一并归档。

当前 [独立结论](raw/outputs/geometry-reopen-20261013-review/CURRENT_CLOSURE.md) 为 PASS_SCOPED，受影响边界两版共10次独立观察通过。旧 REVIEW/FINAL_CLOSURE、旧 source SHA、失败 probes 和较早通过日志均是历史，不计当前通过数量。组件16方法的模拟身份不替代真实受控进程证明。

没有复制签名私钥或监督器环境。生命周期签名由运行期实际逻辑验证；无私钥的归档副本只能核验原件字节，不能独立重验签名。没有运行真实DCC、模型、仿真或渲染。G03实际变形/跨帧/下游仍BLOCKED，全16域M1仍未完成，macOS待目标机器验证。
