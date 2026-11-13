# 进程身份失败诊断

最小修复只增加失败诊断及监督器签名透传。原有 PROCESS_IMAGE_* 异常字符串、工具拒绝条件、sample 三行规则、5/16/60 秒时限、OS 身份校验、停止逻辑和 -B 均保留。

`ProcessImageError.diagnostic` 与已认证 started 回执中的 `writer_process_binding_diagnostic` 使用 `bridge.process-image.tool-diagnostic/1`。字段包括工具 argv、执行阶段、退出码、stderr 原始字节前缀的 hex、已读字节数、诊断截断标志、stderr EOF 完整标志、stdout 已读字节计数和系统 errno。没有 stdout 内容、环境或凭据。

argv 总量上限 1024 UTF-8 字节/16 项，stderr 前缀上限 4096 原始字节，诊断 JSON 小于16 KiB。stderr_observed_bytes 仅表示实际读到的原始字节长度；stderr_complete=false 时，超时或容量上限外的未读字节总数未知。`bytes.fromhex(diagnostic['stderr_hex'])` 可恢复精确字节；仅在展示时使用 `.decode('utf-8', errors='replace')`。

真实普通 Python 工具反例覆盖非零退出、未知 stderr、非法 UTF-8 stderr、超时、stdout/stderr 容量限制和不可用工具。实际普通 Python child 的正式监督器生成并校验签名 start/stop；篡改诊断会被 HMAC 拒绝；诊断不会产生 writer_process_binding。

红测：旧生产代码缺少 diagnostic/new started 字段。绿测：Python3.14 定向30/30，Python3.11兼容2/2；日志为 green314-final.log、green311-final.log。3.14组含冻结源码无 pyc 和取消/停止/预算核心覆盖。没有启动真实 Houdini/Nuke、没有整链重跑，没有修改旧scope。

## 独立复核整改

清理失败曾覆盖原始工具错误。新增一项核心回归先复现四种路径：无效kill后的wait超时、kill权限拒绝、失败工具的pipe close拒绝、成功工具的pipe close拒绝。现保留原始 ProcessImageError 与 diagnostic；附加cleanup只记录有界阶段、异常类型、errno及leader_reaped。等待仍最多1秒，未回收时明确false；工具本身成功但清理失败也拒绝，不返回成功。未声称进程组可信停止。

最终受影响三项：Python3.14 3/3（cleanup-green314.log），Python3.11 3/3（cleanup-green311.log）；此前30/30为整改前证据，主控需在最终源码运行统一必要验证。

最终源码首次并行收口：green314-reviewed-final.log 31tests/1FAIL；green311-reviewed-final.log 3tests/7子FAIL。生产指纹稳定，测试人工0.4秒工具上限与固定0.7秒child退出导致分支提前超时/交接丢失；保留该失败证据，正在以正式工具上限及事件屏障修复测试同步。

最终同步修复后：green314-synchronized-final.log 为31/31，green311-synchronized-final.log 为3/3。工具失败用例采用生产工具5秒时限；监督器child通过实际收集队列完成后的文件屏障退出，取消固定0.7秒假设。生产源码时限完全未改。原 reviewed-final 失败日志保留；这些软件测试未调用真实sample/vmmap，不能据其执行时间推断整链真实sample超时的原因。
