# 三样本专项实际结果

用户批准审查 `17c75d1f67fa75e414f5ed4c59aeae6a8dc726ddfe1a02e7e11016ac82c3affa` 后，已执行 `outputs/official-vmmap-survey-20261027-01`。**首样本失败封闭，后两样本 NOT_RUN，未自动重试。**

首样本 H21 hython PID87581，签名停止 exit -15、`owned_child_wait`，未观测后代标记为 false。原生记账 **1启动／22.401303秒**，scope 关闭原因 `NATIVE_SCOPE_EXECUTION_FAILED`。累计官方实际消耗 **6启动／116.560682秒**，各历史原件保留。

签名 started 为 `SUPERVISOR_WRITER_COLLECTION_TIMEOUT`；未出现 runtime-ready、逐工具 trace 或子进程输出。该样本没有进入HIP业务，也未触发额外 sample。**缺少同次内部栈，尚不能把失败归因于 vmmap、许可证、导入、冻结哈希或CPU。** 普通Python只读耗时记录不是该次失败Hython的阶段耗时，不构成根因证据。

[公开原始回执与汇总](evidence/20261027-vmmap-survey-live-01/result.json)，SHA `c906e131343badb6ffe0964eaae15812719ae3a8852f77b48d5c2604a1a45d05`。该证据不含签名密钥。

没有新增官方可用HIP、NK或渲染。最新官方工作HIP仍只完成保存，未通过冷重开；旧球体案例完整链路结果按原验收边界保留。

后续范围见[一次启动前专项](VMMAP_STARTUP_DIAGNOSTIC_PLAN_20261027.md)，已获后续授权并执行，其实际结果见[启动前专项](VMMAP_STARTUP_DIAGNOSTIC_RESULT_20261027.md)。失败批次剩余名额不复用。
