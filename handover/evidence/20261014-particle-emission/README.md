# P01 软件修复证据（2026-10-14）

这里是本批72份原始文件的不可覆盖副本，共1,310,830原始字节；原始路径、SHA256、压缩及归档字节摘要见 [index.json](index.json)。大于8192字节的非Markdown原件gzip压缩，解压后须与original_sha256一致。没有复制运行密钥、凭据或完整环境。

- 最终结果：[P01修复与缺口](../../PARTICLE_EMISSION_20261014.md)。
- 当前435个Python文件及额外静态边界：[source-binding.json](source-binding.json)。最终 `p01-lifecycle-final-20261014` 的25方法退出0、无失败/错误/跳过，50.265秒；source_before/source_after/current一致。
- 独立最终补修复核：[CLOSURE_FINAL.md](raw/outputs/particle-emission-20261014/review/CLOSURE_FINAL.md)，最终审查摘要：[SOURCE_BINDING_FINAL.json](raw/outputs/particle-emission-20261014/review/SOURCE_BINDING_FINAL.json)。R08/R09仅复跑原有两个反例；R01–R07保持较早关闭证据和最终受影响守卫测试。早期REQUEST_CHANGES及失败原件保留，不升级为PASS。
- 前一54方法组与24方法组属于各自冻结阶段，两组与最终25组重叠；54组有两个Oceanfoam静态NOT_RUN/skip，不能相加成独立方法数或全域验收。
- 全部中心原命令/日志/源码快照及原runner按index保存，能核对具体消费字节；日志内临时目录是运行时路径，任务结束后未必仍存在。

执行仅为受控底层HOM/Python表达式与真实in-process addon建图、候选和持久化事务。没有实际POP求解、P01新PID生命周期、generated P01正式链、真实DCC、模型、渲染或macOS结果。时钟模板夹具属于显式通用API观察输入，不冒称两版捕获的机器字段。

旧日志和移交包未覆盖。本批归档不是安装包，也不是全16域M1完成证明。
