# Hython存活期间取栈：单变量对照

状态：**已获批准并执行结束**。实际1启动／12.972106秒，身份成功、0sample、慢调用未复现；[实际结果](VMMAP_STARTUP_LIVE_SAMPLE_RESULT_20261027.md)。以下为当次获批冻结范围。上一轮[真实结果](VMMAP_STARTUP_TIMEZONE_RESULT_20261027.md)已经失败封闭：时区匹配及第15秒采样触发成功，但sample在工具截止前没有栈输出。原Hython慢启动和sample自身具体停留点仍未知。

## 唯一协议变量及证据边界

只移除Hython启动sample命令的 `-mayDie`，原1秒采样、1毫秒间隔和2.5秒工具上限不变。前后ps仍必须证明同一存活PID、父PID、出生时间和真实路径；目标退出或出生改变即拒绝，不能把未预加载的残缺栈判通过。原短命vmmap采样代码不改。

Apple本机说明将mayDie定义为为可能退出的目标提前取得符号位置；本机工具静态调用顺序为开始提示、可选preloadSymbols、sampleForDuration、stopSampling、完成提示。**这些事实不能证明前次耗时就是符号预加载**。本轮是取消一个并非存活目标验收所必需的预加载选项的对照，不能宣称已经修复超时或稳定性。

## 不变的预算和范围

- 独立scope仅1次H21 hython／60秒父总墙钟（含辅助、清理和最终封存）／512MiB，同时1重操作、零失败重试。原native stopped/记账保持，父总墙钟另报。
- 原工具5秒、观察16秒、collection22秒不变；禁止加载/保存HIP、导出、渲染、Nuke、GraphRun及整链执行。
- 签名Popen／scope／ticket／nonce／argv／监督器出生身份绑定目标；外部取证仍不替代宿主映像证明。监督器ps继承相同时区，其他工具UTC规则保持。
- 最多1sample、3额外ps，子Popen后15秒仍未ready/stop时才触发一次；sample≤2.5秒、前后ps各≤0.35秒、监督器ps≤1秒，受collection结束前1秒及父截止前1秒共同限制。各stdout≤1MiB、stderr≤16KiB；最多32阶段文件／每份8192字节。不额外调用或采样vmmap。
- 栈须具有非空调用帧，通过同次PID/父PID/出生/path与签名原始结果/停止绑定。原调用、取证、预算、冻结、写盘或清理失败立即结束，不重试；未取得栈不算成功。工具提前正常结束则如实标未复现，不自动续实验。

## 软件检查与未完成项

37项定向软件检查通过（3.256秒），覆盖出生更换拒绝、sample截止不计栈/不重试，以及既有身份、预算、早期见证和清理边界。它们与旧轮重叠，不累加。旧152项1个普通进程后代终态失败、4跳过及旧真实vmmap超时失败保留，非全绿。没有原慢启动根因、真实修复或新官方HIP/NK/EXR。[准备证据](evidence/20261027-startup-live-sample-readiness/result.json)。

## 冻结审查

- 候选：`outputs/official-startup-diagnostic-candidate-20261027-03/`
- scope SHA：`d55187ab67838ca94dfd4103c6b36e2f0149d92715951748928a00e1704abe82`
- bindings SHA：`b83b3634bddd67f60bb956e041c4540a2f3b8456dfc88f18d63492f7bc224c22`
- [激活审查](../outputs/official-startup-diagnostic-candidate-20261027-03/engineering-activation-review.json) SHA：`45a2a2dfdde4241a5f3efa8eb0e79b6559dd6fa01008a90df143cf9ab60e3d04`
- 仅拟激活目标：`outputs/official-startup-diagnostic-20261027-03/`，尚未创建。

既有原生账8启动／163.422877秒保留。新增如获批，原生账合计最多9启动／223.422877秒，本次父墙钟另外严格受60秒上限；旧关闭范围不续用，不含后续整链额度。
