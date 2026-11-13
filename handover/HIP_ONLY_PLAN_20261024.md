# H21 HIP 原生专项完整计划

本计划执行顺序：独立审核计划→整改并明确APPROVED→实施薄入口及必要软件验证→原审核者复查冻结内容→执行一次真实HIP专项→核对原始证据并交付。用户2026-10-24已指示“列出完整计划，开子agent检查计划缺陷，它说没问题就去执行”，作为本限定范围的条件执行授权；不沿用19/20或其他已封闭范围的授权。

## 目标与范围

仅Houdini21.0.631、sphere_ground_v2、ACEScg。取得正式注册生成器构建的可编辑HIP，随后由第二个全新hython进程从已验证快照重开并严格读回节点、连接、全部参数通道、材质绑定及冻结场景值。重点验证原工程路径恢复及$HIP/$HIPNAME求值一致。

使用真实HOM与USD；不使用HOM/USD/节点/参数替身，不预置成功工程。允许建图和严格读回必要的LOP/SOP静态求值，不提交渲染、仿真或缓存作业。不启动husk、Nuke、WorkBuddy/HY3、模型或其他Houdini版本，不做反馈创作/全16域扩展。

专项证明层为HIP原生功能及冷重开。保留受控启动、真实PID/出生标识、task/session/nonce、插件源码摘要及签名停止；OS主映像采集标NOT_OBSERVED，生产身份验收NOT_RUN。全局process_image、vmmap门禁、原始回执及生产入口不改，不伪造alpha/AVAILABLE/生产PASS，不用专项结果提升完整工程闭环或M1状态。

## 输入、目录与保护

- 维护仓库：/Users/user/Documents/Code_Project/Bridge。
- 新任务目录：/Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024，实际prepare前必须不存在。新任务数据库、租约、日志、临时文件、偏好、缓存路径均位于此处。
- 计划/实现/审核证据：handover/evidence/20261024-hip-only/。不连接旧SQLite；历史数据库仅允许按字节核验，不复制成功状态进入新任务。
- 当前路径修复基线addon SHA：02393327e93366fc5f3690ad3c021ab3ef7611d1e02838cf4d1deb75675d7005。保留全部有效改动、06至19及软件失败链原件；不改Desktop主工程，不自动Git提交/推送。
- 冻结四包Python源、Houdini插件/依赖及当前必要tools，采用现有prepare_workbuddy_graph.py的文件集合与manifest算法作纯复制，纳入新增专项入口。另复制frozen-scene-v2.json并绑定bytes/SHA。不得为取快照而调用带合成媒体/WorkBuddy副作用的完整prepare_graph。
- 固定本机H21实际hython和普通Python监督器的规范路径、文件身份与SHA，核对插件源码及所有运行输入。版本由实际worker读取，不另起hython --version消耗启动名额。

## 预算与启动约束

专项上限：2次hython启动、单次不超过120秒、累计不超过240秒、输出/临时文件/日志合计512MiB、同时最多1个作业、自动重试0。既有GraphJobService若有更紧的作业期限仍照用，不延长其全局限制。启动1必须可信停止且成功后才可启动2；失败、超额、停止未知即封闭专项，禁止后续启动或换request/scope续跑。

复用现有NativeScope、GraphScheduler及owned_process。NativeScope保持原8次/600秒外层上限与原角色/schema；专项在同一认证账本上执行更紧的2次/240秒内层准入，并通过固定两阶段journal禁止第三次启动。不能另造计数器、回执或并行预算系统。两阶段分别使用现有graph-worker及houdini-host预算角色；第二阶段也按实际工作保留scheduler独占，不能仅靠light角色绕开单作业限制。

所有原生launch位于同一执行锁下，前置核对登记的活动/未知重作业；存在不明活动时不启动、不擅自终止其他进程。阶段实际余量由认证账本与冻结专项上限共同计算，监督器负责运行时限/磁盘监督和自有进程组停止；为停止预留时间，不延长原身份采集时限。

## P0：计划审核与软件准备

1. 独立只读审核者检查本计划、正式调用链、共享状态/身份来源、预算及授权边界。未APPROVED不实施；有具体缺陷先修订计划并交同一审核者复查。
2. 单一执行者新增tools/run_hip_diagnostic.py或同等最小专用入口，仅编排既有正式组件；如确需很薄的冷重开启动脚本可另设一个固定文件。不得复制建图算法、增加MCP模型面的跳过身份开关或修改生产门禁。
3. 默认prepare/preflight不启动DCC；执行必须绑定冻结plan/source/config及APPROVED结果，并由可信控制端记录本次用户条件授权，不能用公开hash或调用方PASS自动授权。
4. 最少软件覆盖：入口两阶段编排、输入/路径/摘要漂移拒绝、第一阶段失败或停止未知禁止第二次、第三次启动拒绝、预算/磁盘拒绝、冷进程不预建图、缺结构/参数证据拒绝。聚焦测试与只读核查可以分层证明这些边界；既有严格读回组件测试只证明对应组件。完整底层替身回放未通过时如实记录，不以预制成功合同换绿；完整两进程集成由本次有界原生诊断验证，真实接收条件不变。优先复用既有测试，不跑全16域或反复全量。
5. 冻结完成后原审核者核对实现与计划、执行文件/命令、全部指纹、0原生启动预检。只读代码问题在本任务内整改；通过后由主控执行用户已授权的一次专项，不逐小项交回询问。

## P1：真实进程1——正式建图、保存与停止

1. 用冻结runtime中的GraphJobService，显式新jobs/scheduler/task root与frozen_input_manifest，不传worker_factory、subprocess_factory、software_launch_script或软件process标志。
2. 正式propose/material_lookdev_v1/sphere_ground_v2/H21.0.631→trial。保留服务自动产生的proposal、compiled、输入摘要、attempt token/generation和持久操作journal；不手造成功job。
3. GraphJobWorker调用现有GraphExecutor/addon建图、初始化、scene.save_hip、同PID的scene.reopen_owned_hip及严格verify。这里的load只计同进程检查，不能冒充冷重开。
4. 只接受SUCCEEDED、construction_executed=true、明确非software boundary、HIP及合同摘要有效、完整冻结场景读回通过；节点错误/未解释加载警告保留未通过状态。
5. 验证原始signed started/stopped、child PID/birth及owned_child_wait成功、全组已停止，再检查文件与预算。不得以结果文件/exit0/PID消失单独判成功。任何失败保留原始HIP（若已生成，标未验证）、journal、stderr和回执，不启动第二进程。

## P2：真实进程2——新进程任务重开与严格读回

1. 由现有owned_process启动第二个真实hython，使用同Task的真实共享保存记录及新的launch nonce/PID/birth/session；绝不先建球地面场景。按正式映射共用HOUDINI_BRIDGE_TASK_STATE_DIR=<control>/houdini-instances；worker的STATE为graph-houdini-instances、runtime为graph-runtime-state，第二host的STATE为houdini-instances、runtime为host-runtime-state。双方ops/lease保持各自正确namespace，由真实重开/接管逻辑恢复，不把旧worker租约或identity手工复制给新host。
2. 复用现有公开task_host_serve的诊断级task bootstrap（warmup=False、writer_executable=None），由真实代码产生task host identity/ready和认证token；不得手填_TASK_HOST_IDENTITY或伪造ready。不经过要求writer OS映像的production_host绑定器，也不让这个诊断host被生产身份门接受。
3. 可信专项控制端仅连接本机task-private服务，核对ready、nonce、PID/出生、版本、plugin hash及监督器绑定。用已有HoudiniClient/既有重开命令及正式operation/request标识调用scene.reopen_task_hip；保存合同来自第一阶段真实回执，不预置manifest或改成功状态。
4. 核对实际快照加载、原HIP内存路径恢复、source/snapshot SHA、完整scene_contract及冻结参数。保留实际节点类型/连接/参数通道和UsdShade绑定，锁内节点不得省略；$HIP/$HIPNAME默认参数必须与保存时一致。必要时只调用现有只读inspect，不另写验收假图。
5. 保存冷重开前后两进程身份及原始返回值，证明PID/birth不同；检查原HIP及快照字节未变。关闭自有host并取得可信成功停止。停止未知时保留占用和未完成状态。

## P3：接收与交付

同一审核者只读核对源/命令/原始回执、两个不同进程、保存与冷重开完整读回、预算及失败停止事实。软件、原生HIP、OS映像和视觉状态分别记录。成功只写“H21 HIP原生建图与冷重开专项通过”，保留OS映像NOT_OBSERVED、alpha/render/Nuke/完整工程闭环未验。

交付实际HIP、保存/冷重开结构与参数报告、材质绑定、原始journal/签名停止记录、冻结源码与输入manifest、审核结果、ZIP及SHA-256，集中放既有桌面Bridge-S06原生定义补采目录。不把软件HIP/NK/EXR作为真实产物，不发布私钥、intent环境或用户私人材料。

真实失败即停本专项；可以继续已授权的软件诊断/最小修复/必要验证与复核，但不自动重跑真实宿主。若缺少必需接口事实或无法保持上述身份/预算边界，报告具体阻断，不猜接口或降低通过标准。
