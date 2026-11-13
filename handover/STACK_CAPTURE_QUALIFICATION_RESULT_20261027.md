# 采集器资格结果

资格02已执行一次，批准审查为 `2e3d44c7351ee9ae45412f663ca4c90fa89b4b223998ea0c5fb2abda7473ff8c`。普通Python目标PID53966，sample工具PID53969；sample完整退出0，耗时0.431801秒，stdout1269字节，取得14帧原生栈，包含 time_sleep → nanosleep → __semwait_signal。封存前实测墙钟0.559033秒。实际1普通目标、1sample、2目标ps及1原监督器身份ps；目标正常exit0，监督器回收及辅助清理确认。DCC启动0。

原控制器返回2／FAILED_STOPPED：其旧解析器要求完整持续采样报告头，实际单次快照只有Analysis头与Call graph。原失败结果不改写。资格入口补充单次快照格式适配，PID由固定sample命令、owned Popen和Analysis头共同绑定；PPID、出生和实际映像由前后ps绑定。没有虚构原报告缺失字段，完整报告解析器保持原样。

只对同次原始流、签名停止及时间顺序进行离线复核，没有重新启动目标、sample或ps。独立离线验证器实测exit0；[接收回执](evidence/20261027-stack-qualification-snapshot-verification/accepted.json) SHA `b29dcbda5bd093ec1d0565023f112c1f9ec0cae615ccc1845491da545a12d7f2`，状态 VERIFIED_ORDINARY_TARGET_STACK_EVIDENCE_ONLY；[原始失败及公开证据](evidence/20261027-stack-qualification-live-02/evidence.json)保持。

资格01的启动器与Python.app映像冻结错误及其失败原件保持；资格02已将两者分别固定。资格解析15项软件检查通过；新H21集成共93项定向检查通过。旧回归失败仍保留，不声明全量通过。

本结果只证明普通目标的取栈能力，不证明H21采集、慢调用根因或业务交付。资格结束时H21历史9启动／176.394983秒。随后另获批准的[一次H21取证](H21_WINDOW_DIAGNOSTIC_RESULT_20261027.md)已执行，当前总账10启动／190.444598秒；资格本身未授予H21或整链额度。
