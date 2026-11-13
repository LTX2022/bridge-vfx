# vmmap 超时有界诊断

状态：**超时症状已复现，根因尚未确认，未实施代码修复。**

- 原链失败在 H1 的第二次 `vmmap` 身份采集；已有日志未记录当时具体工具耗时、部分输出或OS等待状态。
- 本轮用原生产 `observe_process(os.getpid())` 和普通 Python3.14 进程复现一次：ps 0.016秒、首次vmmap 5.061秒后 `PROCESS_IMAGE_TIMEOUT`，退出1。原工具结果逐字转录与同源复现脚本分别见 `repro-first-observe.log`、`repro-first-observe.py`。它证明5秒子工具截止被触发，但不证明与原H1二采的根因相同。
- 同一普通Python目标上，默认vmmap与显式forkCorpse各两次都约0.91–1.10秒完成；该对照不能证明修复。见 `repro-tool-matrix.json`。
- 对原生产管道select/read只记录时间和事件的完整observe通过，两个vmmap分别0.945/0.960秒。见 `repro-observe-instrumented.json`。
- 最后一组两个**新的**普通Python目标完整observe均通过：首采0.958/0.942秒，二采0.869/0.893秒。默认vmmap本身已返回 `Target Type: corpse`。外部监控设置超过1.5秒才采样其等待状态，但未触发，因此没有故障时的stack/wchan证据。见 `external-fresh-observe.json` 与脚本。

因此不能把根因归为管道死锁、Kqueue、活体暂停、系统负载或冷启动，也不能据此增加forkCorpse、改用临时文件、延长时限或取消二次采集。没有可证明的最小因果修复，本轮没有修改生产或测试，未重跑完整软件链，未启动真实DCC。`unchanged-source.json` 对比了分工前副本，权威process_image、controller镜像和对应测试字节保持一致。

现有5秒工具、16秒观察、60秒祖先捕获上限，前后ps/vmmap/lsof、可执行文件stat/hash、父链与出生时间校验均保持。下一项可执行诊断应在发生超时的调用内保留工具PID、分步耗时、截止来源、部分输出摘要及外部只读等待状态，再按实际阻塞点选择修复；不以重复整链碰运气替代因果证据。-06及-07原件均未修改。

## 最后一组有界捕获

主控限定最多10个新普通Python目标、总量90秒、首次失败即停。`capture-fresh-observe.py` 要求新的 `--output` 目录；没有重跑整链。实际21.366秒运行5个目标，第5个(index4)失败后立即停止；原始机器记录见 `bounded-final-capture/summary.json` 与 `target-4.json`。

该次失败前ps在0.004秒完成，vmmap入口外层观察预算尚余15.992秒；vmmap5.005秒触发原子工具上限，采集器没有读到其stdout/stderr数据。外部ps在目标启动约3.498秒时记录：Python状态Ss、vmmap状态Rs。sample命令返回0并保存 `vmmap-sample-4-62064.txt`，但其 **Call graph为空**，没有故障调用栈。不得把返回0或Binary Images列表当作已捕获根因。成功慢样本 `vmmap-sample-0-61949.txt` 含 `mach_vm_page_range_query` 等栈，但它对应最终2.216秒成功的调用，不能拿它解释失败调用。

新增证据进一步确认是5秒子工具超时，而不是16秒总观察预算被前序调用耗尽；仍不能确定vmmap未及时产出的内部原因。没有已证实的生产代码缺陷可作最小因果修复，生产代码、测试、校验策略和阈值保持原样。首个失败log为工具输出转录（并非当时直接重定向的原始日志）；最后一次target-4及sample则由诊断程序直接写入的原始证据。未修复、未重新冻结、未做成功声明。
