# H21 HIP 热路径候选与下一次专项合同

这是软件修复候选的冻结计划，不是新真实运行授权。已失败的 hip-resource360-20261024-authorized 保持封闭，原件及消耗不变。

## 软件修复范围

正式 producer 保留 before/after 两次完整采集及实际任务根围栏；锁定 HDA 使用显式2.1定义/静态身份合同，公开控制读回不省略，旧2.0/1.0保持原语义。18启动检查点与有界producer诊断增加双时钟锚，不改原预算。GraphJobWorker 在合法新HIP保存前准备内存工程名。正式公共/注册构建入口共享新工程资源初始化，绑定稳定的项目output_root，保留严格保存、两次不同路径SaveAs、冷重开与精确资源/输入校验。

参数、root userData、sidecar配置失败必须回滚；不可恢复或产生资源残留时保留现场并进入reconcile。不得覆盖旧工程、用户路径/驱动、已有资源或启用缓存。软件边界只模拟底层原生接口，不能产生真实宿主通过记录。

已确认的详细实施合同：

| 文件 | SHA-256 |
|---|---|
| [H21_HOTPATH_REPAIR_PLAN_20261024.md](H21_HOTPATH_REPAIR_PLAN_20261024.md) | `5fbdd65e9981c36eef3ef97a005beffe1e3db2a227752bdb040be47d614201b9` |
| [H21_FIRST_SAVE_CONTEXT_REPAIR_20261024.md](H21_FIRST_SAVE_CONTEXT_REPAIR_20261024.md) | `0f7b824040d8a723899c28071653dd3a81dd8e96d4c6dfcbd13291a4d6999e45` |
| [H21_PROJECT_ENVIRONMENT_REPAIR_20261025.md](H21_PROJECT_ENVIRONMENT_REPAIR_20261025.md) | `527cfade467da4e02ac510eb22e212de17b36405bbc2d125f7e0f057aefc4301` |

## 下一次真实 HIP 专项（另行授权）

固定 H21.0.631、sphere_ground_v2、ACEScg，只执行建图保存后退出及第二进程冷重开。读回节点类型、连接、冻结参数、材质绑定、场景/工程身份与内容摘要，保留原始操作和可信停止事实。不渲染、不启动Nuke/HY3，不执行仿真或缓存。

- 建图总阶段240秒、冷重开120秒、累计360秒，包含启动、前置及停止；每阶段预留10秒。
- 最多2次DCC启动、512 MiB、一个重作业、零自动重试。
- 顺序固定：预检→可信新授权激活→graph worker建图及保存→确认整组停止→新宿主重开读回→确认停止→核验回执及产物。
- 失败、预算耗尽或停止未知立即停；未知停止继续占槽。不得复用旧scope或重试寻找成功。
- 当前只prepare和不启动宿主的preflight。scope必须保持PREPARED_NOT_AUTHORIZED、execution_authorized=false、零starts/tickets、NOT_RUN，无activation或launch。

## 接收边界

当前核心软件测试与两位独立只读复核分别记录实际源码指纹及范围，不累加重叠用例。源代码、controller镜像和交付必须同源。旧原件哈希、补丁正反还原、包完整性和路径安全分别核验。

实际Karma HDA强绑定、Embedded冷重开及240秒内完成尚未证明。H22 gallery compiled模板精确信息仍有静态缺口，软件最小String API不替代该依据。完整工程HIP/NK/EXR、M1、HY3、视觉与生产状态保持未通过。
