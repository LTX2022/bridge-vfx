# 本轮取消与观察边界

ready 等待、返回前及新观察启动前检查取消。已经进入的原严格 `_observe` 链可以在原 deadline 内继续，包括后续 vmmap、lsof 和 hash；晚结果丢弃，不签入 binding。自有作业的 TERM/KILL 和可信停止流程不等待该采集线程结束。

本轮保留上述既有 in-flight 观察行为，不声称支持逐工具即时取消。两个独立审查者均未发现此边界导致本轮 P1/P2 的具体证据。工具5秒、freeze5秒、observe16秒、collection22秒和capture60秒保持不变。
