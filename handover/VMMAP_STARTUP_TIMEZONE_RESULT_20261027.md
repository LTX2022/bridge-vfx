# 时区修正后专项实际结果

已按用户批准审查 `2c4cbd7e7c1d8ee10aec2b2d6ac7a0634bcf56f4ffe23b14f06bb546012bf022` 在 `outputs/official-startup-diagnostic-20261027-02` 执行唯一一次H21启动前取证。**原始就绪失败，sample达到辅助截止且没有栈输出；范围失败封闭，没有重试。**

## 消耗、身份与停止

原生记账 **1启动／24.547631秒**，累计 **8启动／163.422877秒**。父accounting最终写入前墙钟25.240290秒，测量点明确，封存后driver重新核60秒截止；父墙钟不改写原生停止账，不将其冒充包含自身最终写入的精确值。

Hython PID25693，监督器PID25657。签名 `owned_child_wait`、exit -15、`descendant_result_unobserved=false`，scope `NATIVE_SCOPE_EXECUTION_FAILED`。最多允许的3次辅助ps和1次sample实际均已使用，4个工具均leader reap、进程组消失和线程join确认。冻结源码在停止核验时全部匹配。无新增HIP、USD、NK、EXR，未进入业务。

## 本次实际观测

- 时区身份比较通过，已触发Hython采样；不再出现 `STARTUP_CHILD_FACT_MISMATCH`。前后ps均确认同PID/父PID/出生时间/真实路径，目标仍存活，状态Rs。
- 原collector在子Popen后0.153517秒完成冻结、0.171050秒完成原ps，0.171341秒开始等ready。
- sample在子Popen后 **15.025185秒** 启动，命令为1秒采集／1毫秒间隔／`-mayDie`。实际约2.356220秒达到辅助工作截止，进程被终止并回收；stderr仅有开始采样提示，stdout **0字节**。故没有合法调用帧，`sample_identity_matches=false`、`diagnostic_complete=false`。
- 原collector在子Popen后22.006978秒报告 `SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT`。本次没有worker首标记，也没有ready；缺失标记只界定证据前缀，不能证明实际没有执行任何Python指令。

## 只读工具核对与边界

本机Apple [sample说明](/usr/share/man/man1/sample.1)解释 `-mayDie` 会立即抓取符号位置以应对目标可能退出；工具只有采样结束后才生成报告。已对本机同一 `/usr/bin/sample` 做只读静态核对：开始消息之后依次存在可选 `preloadSymbols`、`sampleForDuration:interval:`、`stopSampling`，之后才打印完成消息。

本次没有完成消息，**不能确定耗时发生在预加载、采样还是stopSampling，更不能把符号处理说成已证实的超时根因**。也没有同次Hython内部栈，原慢启动仍无法归因于许可证、动态装载、CPU或具体导入。这里没有执行新的sample、ps或DCC来补采。

下一项仅准备[取消提前符号预加载的单变量取证](VMMAP_STARTUP_LIVE_SAMPLE_PLAN_20261027.md)：Hython要求采样前后仍为同一存活对象，去掉用于预防目标消失的 `-mayDie`，仍保留失败拒绝；原短命vmmap取证代码与原5／16／22秒时限均不改变。这是取证协议对照，**不是已证实的性能修复**。37项相关软件边界通过，仅软件；旧回归失败保留。该后续预算之后已获批准并执行，其[实际结果](VMMAP_STARTUP_LIVE_SAMPLE_RESULT_20261027.md)为身份成功但0sample、慢调用未复现。

[公开原始签名、工具输出、阶段及静态核对](evidence/20261027-startup-timezone-live-02/result.json)，SHA `2ba12ac75180e524778a0ab270dc386376fa81ca6b0ff3297ed790cb3e57d747`，不含签名密钥。
