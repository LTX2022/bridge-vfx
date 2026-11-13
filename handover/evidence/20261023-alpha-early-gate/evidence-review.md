# 第二独立验收

结论：本轮软件修复与 -10 未授权候选冻结可接收；真实工程闭环仍未通过。

验收者未参与实现。直接认证成功 -04 的原始结果、HMAC、8 张票据/7 组停止回执、SQLite 账本、文件摘要与 NK 快照：退出码均为0，无未知后代；两产物均version1，Nuke明确依赖 engineering_h21_main，来源保留software_test和NOT_OBSERVED。111.280秒的软件测试通过，软件计费98.602906秒。

79条模型事件同一adapter摘要，恰2次controller包装；158项冻结源码/175项immutable与成功04、当前源码和review一致，无pyc。最终7文件清单为 integration/image-model-controller-source-sha256.json，与当前文件逐一匹配；18文件总清单另见 final-source-sha256.json。

01/02/03失败、04模型通过分别保留。-06/-07/-08/-09及失败软件01/02/03的字节数与SHA均与基线相等。SQLite原db/wal/shm只复制到临时目录读，原三文件前后摘要不变。未重新采样。

独立认证10初始状态：PREPARED_NOT_AUTHORIZED，False授权，0票/0host_started；预算8/120/600/512MiB/1heavy/0retry。新32字节签名key权限0600，与旧key不同，仅检查布尔结果，未输出值。三份runtime镜像一致，候选不含software-native-boundary配置，未复用09 alpha。未来11-authorized目录不存在。

默认预检PREPARED、blockers[]、NOT_RUN。冻结SHA：

- scope: 75baa3d5cac190d8588304b9cd236caaddca4a78a78d84e7cbb41e07366d0597
- bindings: c4031f4904ef0d7422def18a1670a7d74a19f9409fd240984b40493abb76b65d
- review: bfa0ca6aacaab899c003f54e19db56fec8187a789ff55df13a5d8ee7e6e8dab3

核查使用Python3.11 -B的只读认证、文件指纹和临时数据库副本查询。未激活、未启动真实DCC、未重复采样。

限制：04显式替换sample/vmmap原始字节并包装测试controller/supervisor入口，不能证明真实生产采集可靠性已修好，也不能解释09历史TOOL_FAILED；live-readiness=NOT_ESTABLISHED。
