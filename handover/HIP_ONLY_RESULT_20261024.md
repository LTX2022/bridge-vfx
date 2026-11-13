# H21 HIP 原生专项执行结果

**结果：失败，未通过 HIP 原生验收。** 已按[完整计划](HIP_ONLY_PLAN_20261024.md)完成独立计划审核、限定实现、冻结审核和一次真实执行；第一阶段截止后取消并可信停止，未启动第二阶段，未重试。

| 项目 | 实际结果 |
| --- | --- |
| 场景与配置 | Houdini 21.0.631，sphere_ground_v2，用户确认 ACEScg |
| 执行范围 | 仅正式 GraphJobService 建图保存与计划中的新进程重开；未提交渲染、仿真、缓存或 Nuke |
| 资源上限 | 2 次启动、每次 120 秒、累计 240 秒、512 MiB、单作业、零自动重试 |
| 本次消耗 | 1 次 graph-worker；109.540949 秒；终态磁盘占用 4,746,291 字节 |
| 控制端结果 | HIP_GRAPH_DEADLINE，FAILED_CLOSED |
| 停止事实 | PID 36186；owned_child_wait；CANCEL_REQUESTED；退出码 -15；descendant_result_unobserved=false |
| 账本终态 | NATIVE_SCOPE_EXECUTION_FAILED，已封闭 |
| 实际交付物 | 未生成 HIP；未启动冷重开；未生成 NK 或主场景 EXR |
| 其他验收 | OS 映像 NOT_OBSERVED；生产身份、alpha、render、Nuke、视觉均 NOT_RUN；完整工程闭环及 M1 未完成 |

## 已验证的软件边界

新增 `tools/run_hip_diagnostic.py` 和 `tests/unit/test_hip_diagnostic.py`，复用现有 GraphJobService、NativeScope、GraphScheduler、OwnedProcess 和 StageJournal。生产插件、全局身份门槛与预算代码未修改；164 个既有源码/输入文件的摘要保持不变。

10 项聚焦验证通过，最终逐 ticket 120.001 秒拒绝用例通过。完整底层替身两阶段回放未通过，原日志保留；没有以预置工程、成功合同或软件回执代替原生结果。独立审核者核对 160 个冻结文件后批准本次有限执行；原生失败后，同一审核者使用冻结 API 验证了账本和原始启动/停止签名。

冻结入口 SHA-256：`34d7378122e90d2754c2419431c3113a71aac889d9ddc3e300cafc59fa291452`。

真实 scope SHA-256：`6c0c2ac4626e35ac6797ddcfc7496c23c8ac3fc71f25de291fee8d83451be0c2`；freeze SHA-256：`abc347c191af5a1c0fe7d79ab62c8614c2b994619e496d95ae27ed4aac0453a4`。冻结运行源码及既有修复均无漂移。

## 首个阻断与证据边界

监督器已创建实际 H21 child，Houdini 创建了本任务独立偏好目录的 `21.0/houdini.env`；这是当前最末可直接观察到的进展。child stdout/stderr 均为 0 字节，未生成 worker identity、error、result 或 HIP。

实际命令是固定 H21 hython、冻结 `graph_job_worker.py`、`--job` 和 JSON 参数；可执行文件、脚本及脚本导入根静态核对无确定错误。缺少 worker identity 不证明停在许可或导入：该记录位于模块导入、catalog 校验、解析、构造、编译及证据初始化之后。当前无法确定最早 Python 入口是否已经执行，不能据此认定许可证、CPU、导入、编译或 vmmap 为根因。监督器随后 `scope.finish` 抛出的封闭异常也不是已证明的首因。

下一次诊断需要在最早 Python 入口、模块导入完成、参数解析完成、证据初始化前后写入固定阶段名和时间，不写 job、环境或凭据。本次未实施此改动，也未追加原生运行；须先完成限定软件变更和复核，再另行确认新的实际运行范围。

## 原件与复验

- 原始任务目录：`/Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024`。该范围已封闭，不可续用剩余启动名额。
- [原始证据及实现验证](evidence/20261024-hip-only/)：包含计划审核、精确冻结审核、条件授权、预检、控制端结果、HMAC 复验和独立验收。
- 本机复验：`python3.11 -I -B handover/evidence/20261024-hip-only/verify-original-receipts.py`。此脚本使用冻结 API 和本机原始密钥，并获取本机控制锁，需锁文件访问权限；不启动宿主，不更改 scope 或回执内容。失败操作的停止可信不等于执行成功。
- 交付包不含 `.native-control/key`、`receipt.key`、`intent.json`、token 或环境。离线包可以核对内容摘要；没有原始本机密钥时不能独立复验 HMAC。

未改 Desktop 主工程，未合入、提交或推送 Git；历史原件保留。
