# 只读查询回执修复进度（2026-10-27）

用户持续授权完成任务及全部必要预算。该授权不复用关闭范围，每轮保留新冻结及独立预检。

menu-01实际建图超时后，已定位owned-root node.children查询每次做两次完整场景capture。实现独立query事实合同，默认mutation/full-scene operation保持；query显式full_scene_identity_verified=false。core03软件79项通过，3项需要真实OS或独立软件宿主的测试排除；只读Git另记。独立复审确认query证据读取、wrong-root/cross-schema拒绝、SAVE拒绝及unmanaged不opt-in边界。三旧测试错误为HOM新旧状态对象错绑，实测cached epoch12/current epoch0；只修测试host绑定，未清epoch或放宽生产。

query-20261027-01真实官方封存及alpha完成，graph-worker根创建后提前返回RECONCILIATION_REQUIRED（进程exit0不等于业务成功），六进程签名可信停止，总106.32190251350403秒。官方组累计33启动／868.1278023719788秒。范围ENGINEERING_DRIVER_FAILED关闭，余额不复用。

真实根租约owner使用_host_identity，生产者在graph-worker内使用独立graph_worker_identity；两者session/generation不同是合法事实。query/1错误要求它们相同，导致查询记录在INTENT前被拒绝。新query/2分别记录host_identity与lease_identity，租约owner/session/epoch绑定后者，两套身份前后相等；默认生产者绑定仍保留。新增不同身份和lease三字段篡改测试，core04软件80项通过（排除同3项），无被禁止启动。

独立审查agent_a34c5a65已补读生产端来源，确认_fx_producer_identity与_host_identity分别取真实身份、renew=False；未发现P1/P2。新query2候选176快照、218immutable、184bundle与80测试哈希核验通过，零启动后按原授权激活并执行。

新正式目标：`outputs/official-karma-disklight-h21-query2-20261027-01`。
Scope SHA `7448290cfb2bc62d22cd26b6322d5cd48b5b91629e00183902eee07206a9de8d`；bindings `f88b0bdef1eec5ef916fe2f04512cf56d2ed240086a0df544b6d4696110229f4`；review `b31aab3c830cdacbcf7f58ea7d0f44f75c4fd284b443a0723b219df50c664dd0`。预算11启动／600秒／512MiB／每操作120秒／并发1／零自动重试。当前运行结果待核验，不能声称性能、Bridge HIP、NK或渲染对照通过。

证据：`evidence/20261027-producer-query-integration/core-04/result.json`、`freeze-check-02.json`、`authorized-activation-02.json`；旧query结果 `evidence/20261027-producer-query-live-01/result.json`。旧原件未改写，无正常采样专项。
