# H21 启动检查点软件准备结果

后续实际执行结果见[H21检查点真实专项](H21_HIP_STARTUP_LIVE_RESULT_20261024.md)。以下保留软件准备阶段的验证与未授权状态。

**[执行计划](WORKER_STARTUP_PLAN_20261024.md)第1—5步完成，第6步等待新的具体真实执行授权。** 本轮没有启动DCC，没有修复或证明上次H21停滞的内部原因。

## 实现

两处生产源码增量：worker在脚本直接执行且`BRIDGE_GRAPH_STARTUP_DIAGNOSTICS=1`时，输出最多18条固定阶段记录；专项driver仅在其隔离环境中明确设置此开关。记录复用监督器的`child.stderr.log`，通过单次短`os.write(2)`即时落盘，只含固定阶段名、单调时间、PID。

接点覆盖脚本入口、依赖导入、catalog校验、解析、编译、证据初始化，以及其中的runtime指纹、构造输入、进程身份和scheduler绑定。普通导入和默认运行静默；未新增路径输入、模型工具或执行服务，未改身份、授权、预算、取消、停止、产物或成功判定。日志不能替代签名回执和HIP读回。

新增一个核心测试文件。测试使用普通Python和明确软件边界，无真实Houdini/Nuke，不预置HIP或成功合同。

## 验证与独立复核

| 实际运行 | 结果 |
| --- | --- |
| Python 3.15，20项定向覆盖 | 18通过、2项因子agent无法写outputs目录而报PermissionError；原始日志保留 |
| Python 3.11.16，6项启动专项及上述2项 | 8/8通过、零跳过，32.655秒；权限错误已在正确权限下收口 |
| 旧原件保护 | 上次HIP专项182个受保护文件零变更 |
| 运行源码差异 | 160个原运行文件中仅worker和driver两项预期变化 |
| 补丁 | 3文件正反应用均逐字节一致 |
| 独立审核 | /root/hip_only_plan_review：最终限定差异无剩余P1/P2，软件预备APPROVED |

上述两次运行有重叠用例，不能合并成一次20项全绿。已证明默认静默、精确开关、固定阶段与隐私、暂停时日志即时可见、有界回收、解析和缺原生API时保留失败语义，以及受影响的transport、receipt拒绝、预算和漂移边界。

完整原始证据、选择器、补丁和审核绑定见[evidence/20261024-worker-startup](evidence/20261024-worker-startup/)。未重新运行慢完整HOM替身或全16域回归，未重建Skill安装发布包，未提交/推送Git或修改Desktop主工程。

## 冻结候选

- 目录：`/Users/user/Documents/Code_Project/Bridge/outputs/hip-startup-checkpoints-20261024-prepared`。
- 状态：`PREPARED_NOT_AUTHORIZED`，零启动，无activation；零启动预检通过。
- scope SHA-256：`432c4835796dd95c0eb7d3d92667c223d05e8a8dffa49c17a4d0853cd9e43451`。
- freeze SHA-256：`58f1f9b44143d4b998ffcc7726bbc743755b89bd19e02462d11b4b4b2d26c0a6`。
- source SHA-256：`4381cd5bffa439bf07719a207bfaad66113023952633a1f011ae667c25e364fc`。

## 待执行的实际步骤

新的实际目录为`outputs/hip-startup-checkpoints-20261024-authorized`，目前不存在。拟使用该冻结review激活H21.0.631、sphere_ground_v2、ACEScg，最多2次hython、每次120秒、累计240秒、512MiB、单作业、零重试；第一阶段正式建图保存且可信停止成功后，才能启动第二进程冷重开。失败、超预算或停止未知即停。

之所以尚未执行此步，是因为用户此前要求失败即停，上次真实scope已封闭。本轮软件准备和APPROVED review不作为新增原生预算授权；不复用旧剩余票据。取得新的具体确认后，直接按冻结入口执行，不再补临时脚本。

原生停滞首因、HIP保存及冷重开仍未验证；OS映像NOT_OBSERVED，渲染、Nuke及完整工程闭环/M1未完成。
