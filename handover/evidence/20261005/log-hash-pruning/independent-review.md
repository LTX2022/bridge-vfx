# 日志摘要剪枝独立复核（2026-10-05）

结论：正常可读目录树的剪枝、POSIX排序和adapter回退可限定接收；仍有一项确定P2，不能认定与原算法的失败语义完全兼容。仅只读源码/既有测试/日志和当前解释器标准库；未运行测试、子进程或软件，未修改实现及worker/provider。

**P2-LHP01 — 目录扫描异常被吞，可能签出不完整源码摘要。** `tools/run_logged.py:31` 调用 `os.walk(root)` 未设`onerror`。当前日志绑定Python 3.11.9，其`Lib/os.py:359`、`:371`捕获scandir打开/迭代的所有OSError并直接返回；例如纳入范围的`packages`目录扫描发生EIO时，该子树会被静默省略，`build_hash`仍返回普通SHA并被记录到日志header。原`Path.rglob('*')`在该版本`Lib/pathlib.py:353-375`、`:383-415`只吞PermissionError，EIO会向上传播而阻止生成正常provenance。因此此项是新异常路径回归，正常根上的SHA一致及7项通过不能覆盖它。最小修复应保留进入前剪枝，同时显式处理扫描异常，至少传播原算法会抛出的非PermissionError；scandir迭代出错也需同样处理。本次不实施、不补跑复现。

其余限定结论：

- `children[:]`在进入子目录前按原EXCLUDED精确名称剪除；文件名同样过滤，最终仍按root-relative路径过滤，根路径上层含`outputs`不导致误排除。
- 全部候选统一按`relative_to(root).as_posix()`大小写敏感排序，哈希仍为逻辑路径UTF-8、NUL、文件字节SHA256串联；算法名保留`sha256-posix-logical-path-v2`。
- 非PathLike的`FlavouredPath`保留原`rglob`；真实路径走`os.walk`，未改变Windows/POSIX逻辑拼写测试接口。
- 新测试实际观察scandir并断言所有排除目录未进入；既有6项测试覆盖两种路径flavour、内容变化、根下相对排除、算法标识及真实returncode传递。没有扫描异常测试；日志未显示此故障已执行或被处理。

证据：`../integration/log-hash-pruning.log`为7 tests / 0.205s / OK；`result-log-hash-pruning.json`为7项、0 failure/error/skip、外层0.438s、exit 0、source_before/source_after一致。当前三个文件SHA独立读取均匹配该JSON：

- `tools/run_logged.py`：`5423f73b0a35f0b40eb0827145649ddf62a2383395990a58f5f279adffbe4d4e`
- `tests/unit/test_log_hash_pruning.py`：`5546be688663e558da520fa76eede094e43946c4b6357e07c79dd21ca0cb654d`
- `tests/unit/test_cross_platform_fingerprints.py`：`4571b263a67e4b46b97067dbe0aa184377b0a2f49b9b2de010789533e1ddce45`
- 测试日志：`9bc3065ddb9b1da8704df818cb4d1350ec7c30e0627d2a922120e46f2870ea42`；结果JSON：`ff4ccecd39bb41ecaa353f7bd65c3be843d061555df31faa84b402ba27ff1fce`。

RESULT.md记载的同根762文件SHA相同、10.437s→0.125s及修复后0.094s，属于作者已有单次测量，本审查未重测；不外推全项目速度或正式快照/生产验收。仅需处理上述异常边界，不要求全量重跑或扩大改动。

## P2-LHP01 整改增量复核：限定关闭

当前结论取代上文“仍需处理”的状态：P2-LHP01已关闭，日志摘要剪枝改动可限定接收；本增量未发现新的确定P1/P2。`tools/run_logged.py:27`新增`_scan_error`仅忽略PermissionError，其他异常以`raise error`传播原实例；`:36`将它接入`os.walk(onerror=...)`，覆盖scandir打开及迭代失败。非PathLike的rglob回退、排除目录进入前剪枝、POSIX排序及哈希算法名/拼接规则保留。

新增`test_scandir_open_and_iteration_io_errors_propagate_before_hashing`在纳入范围的packages目录分别注入实际`os.scandir`打开/iterator EIO，调用真实`build_hash`，断言抛出的就是原异常实例，故不能正常返回摘要；其余7项正常路线继续保留。PermissionError忽略由当前源码分支确认，本新增用例未单独注入该异常，不宣称已测。

既有`../integration/log-hash-errors.log`为8 tests / 0.112s / OK；对应`result-log-hash-errors.json`为8项、0 failure/error/skip、外层0.344s、exit 0、source_before/source_after一致。当前读取SHA与该JSON一致：

- `tools/run_logged.py`：`28185d01ef84eb54a81e3dacc1b0ad68b297486b2f72ef450ab6a698aa55fb0a`
- `tests/unit/test_log_hash_pruning.py`：`ef7dd5b25fca92350434492acadf376c930206d6010874b33a02967907a9efc3`
- 既有跨平台测试仍为：`4571b263a67e4b46b97067dbe0aa184377b0a2f49b9b2de010789533e1ddce45`
- 新日志：`67c8d85fce0d6c4b8753efa66ab65d19bdb85c6d456e7dfd97d34438727f03f1`；新结果JSON：`3a28cac19205a697bdd9e7649acdafd47bd09eb7fdffef5ab0b2d5c44282250c`。

仅只读复核上述增量及既有证据，追加本报告；未运行测试/进程，未改实现，未扩审项目或提升正式验收状态。
