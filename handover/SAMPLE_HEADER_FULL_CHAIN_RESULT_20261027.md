# sample 身份头正式链：第一次真实执行结果

日期：2026-10-27。状态：**FAILED_CLOSED，整链未验收**。

用户明确批准“批准，要按照计划一直执行下去”后，使用审查对应的冻结激活器和冻结 driver 执行正式链。新身份门在本次 Houdini 21.0.631 启动通过，官方 CPU 工作 HIP 已保存；随后参数观测抛出 `OFFICIAL_NATIVE_RAMP_SHAPE_INVALID`，worker exit1，范围以 `NATIVE_SCOPE_EXECUTION_FAILED` 失败关闭。没有重试，也没有启动后续阶段。

## 认证与实际消耗

[离线核验结果](evidence/20261027-sample-header-live-01/result.json)由[核验脚本](evidence/20261027-sample-header-live-01/verify_result.py)使用目标内冻结模块生成。脚本以 audit hook 禁止子进程执行；成功核验时无被拦截执行尝试。初次核验脚本误将账本的规范化 payload 摘要与 envelope 文件摘要比较，断言失败；依据冻结合同改为规范化 payload 摘要后通过。未改签名回执或账本。

- 激活审查 SHA：`3b1b0bc6e70d1c8a65b704616bec8c49a38da2f7ca262ea946f2347858493336`。
- 目标：`outputs/official-karma-disklight-h21-sample-header-20261027-01`。
- 激活 scope SHA：`5e81b7f6a56b2a97f6fab15bae8e5298908c527ce3d225ab73b6c29db5e93051`。
- 激活 runtime-bindings SHA：`811170ca43c80f6c29fb8e156e99b3c21a781b9040577f95bbb73fab7abaff30`。
- 原批准上限：11 启动／600 累计原生秒／512 MiB，每操作 ≤120 秒，同时最多 1 重操作，零自动重试。
- 实际：**1 启动／19.68935513496399 原生秒**，输出根文件合计 **117,700,636 bytes（约112.25 MiB）**。
- started、runtime-ready、stopped 和 official-diagnostic 签名均认证通过；激活授权和 NativeScope 账本认证通过。
- 唯一进程 PID 20865，停止来源 `owned_child_wait`，exit1，`descendant_result_unobserved=false`；全部已准入票据可信停止。
- 176 份冻结运行源码均匹配审查；诊断详情和保存 HIP 的字节数、SHA 均与签名关联记录匹配。
- 官方实验组历史 11 启动／202.87434887886047 秒，加本轮为 **12 启动／222.56370401382446 秒**。球体范围29及其他范围分开记账，不纳入该合计。

预算的剩余额度不能用于重开失败范围；本轮没有新建或执行继任真实范围。

## 已保存文件及交付边界

[官方 CPU 工作 HIP](../outputs/official-karma-disklight-h21-sample-header-20261027-01/official/official-cpu.hip)：44,773,632 bytes，SHA `e5abe01251fa104da03aeb6d65b089f86c27ff827068dc9483ddd2b18d239f29`。

这份文件只证明保存及字节完整性，**未通过冷重开或渲染验收，不能作为可用正式交付**。官方冷开、USD 导出、CPU 参考渲染、原生 alpha 校准、Bridge 注册图重建／HIP／主渲染、NK 保存及独立 Nuke 消费均为 `NOT_RUN`。本轮未交付新的 NK 或 EXR，人工视觉验收未到达。

## 现有诊断能证明什么

冻结 traceback 定位到 `official_karma_native.py` 的 `parameter_value` ramp 形状校验，经过 `capture_parameters` 和 `capture_observation`，发生在 HIP 保存之后。缓存诊断完整，列出的 32 个节点 errors、warnings、messages 均为空；诊断未记录导致异常的具体参数路径或 keys／values／basis。

因此，本次阻断是参数观察阶段的形状拒绝；新身份采集在本次运行通过。不能由一次成功推出 sample 永不超时，也不能据此认定旧 vmmap 超时的唯一根因已经消除。[只读 ramp 定位](evidence/20261027-sample-header-live-01/RAMP_DIAGNOSIS.md)已确认：此 guard 只拒绝非字典序列化结果，具体参数和返回类型未知；明确类型 API `ParmTuple.evalAsRamps()` 是尚未实施的候选修复，不放宽现有2—64点合同。

## 保留与接续约束

候选、激活目标、冻结源码、原始输入、失败回执和历史证据保留。未修改原 Desktop 主工程，未提交或推送 Git，未安装环境或模型。此前实现子任务误运行正常 Python／sleep 身份测试的偏差继续保留于 [执行偏差记录](evidence/20261027-sample-header-integration/EXECUTION_DEVIATION.md)，不能把整个修复轮描述为零采集。

当前正式范围已结束。任何针对 ramp 的生产修复均须先基于现有证据完成软件验证和新冻结审查；修后真实执行需新的具体授权，不能跳过校验、改写冻结源或复用本轮额度。最终可用 HIP、NK、渲染交付仍未完成。
