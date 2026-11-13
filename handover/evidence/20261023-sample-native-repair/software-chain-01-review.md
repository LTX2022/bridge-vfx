# 首轮软件链独立验收

审查者：只读证据角色 `sample_evidence_review`。对象：`outputs/software-engineering-20261023-native-image-01`，实际 macOS 进程与身份工具，Houdini/Nuke 原生 API 为显式软件替身。

结果：FAIL，测试耗时 98.039 秒。首阻为 Houdini 产物登记 `COMPLETION_BYTES_UNAVAILABLE / TASK_PATH_LINK`；随后读取不存在的 NK 是次生测试错误。账本中产物、版本及操作回执均为零，Nuke 未消费上游产物，不能据 render DONE 宣称工程闭环。

独立核验：6 张启动票据、5 个监督器进程组全部可信停止，返回码和监督器退出均为 0，无未知后代；13 行 accounting 的 HMAC、序号、前链及终态一致。6 票的 started/stopped 签名、nonce、命令摘要和 start/stop 摘要一致，主渲染子票共享已绑定宿主停止。4 个要求 writer 绑定的宿主取得真实完整绑定；graph worker 不要求该绑定。

主 writer postframe 的 observation 签名、context/hook/producer 摘要一致；真实子进程至宿主的正反两节点链一致，实际映像和锚点有效。输出 EXR 摘要匹配，但未登记。42 条 construction journal 全部 COMPLETE。原始数据库在临时副本查询前后哈希未变。

158 个快照文件与当时源码一致，174 项 source_freeze 一致，无 pyc；无 image model、模板或 Popen/image 注入。软件计费 101.647027731 秒；8 次/120 秒/600 秒/512 MiB/一个重作业/零自动重试上限保持。原 `-06` 至 `-10` 共 1044 文件未变。

结论只覆盖普通 Python 的真实 OS 采集及软件链失败事实。首轮冻结门为 NO_GO，不启动真实 DCC，不以辅助采集成功代替真实工程验收。
