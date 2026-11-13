# R01–R05 永久回归测试交接

唯一源码写入是新增 `tests/unit/test_rbd_review_guards.py`，现已冻结。未修改原有两个 authority 测试、生产代码或旧夹具；未执行真实 DCC、渲染、仿真、正式进程测试、提交或推送。

最终命令：

```powershell
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/authority/run_authority_tests.py review-guards-owned-v2 --test test_rbd_review_guards
```

结果：6 methods，21.0.631 / 22.0.429 两版共 12 次观察，0 failures/errors/skips，exit 0，命令耗时 1.749 秒。原始日志和完整环境/命令/退出码在同级 `review-guards-owned-v2/raw.log`、`result.json`。既有 runner 核对的 6 项源码/夹具摘要前后一致；该 runner 的既定清单未包含本新增测试，新增测试冻结摘要单独交付，不冒称 runner 已核对该文件前后摘要。

覆盖事实：

- R01：BASIS_KEY 第三次实际 userData 读取把 exportlist 改为 w，返回值保持原样；Host observations 必须以 RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED 拒绝，无登记/程序写入，原帧保持。
- R02：实际 addon `_fx_restore_planned_item` 持有合法旧快照时出现 launch_nonce 漂移；必须拒绝，逐一验证全部实际参数/userData 无变化且底层 set/setUserData/destroyUserData 调用次数为零。显式 `_TASK_HOST_IDENTITY` 来自固定底层 fixture，未替换 addon 权限 helper 或参数恢复函数。
- R03：直接 Host.restore 的真实 fixture lease 查询返回 LEASE_LOST；必须抛该错误，实际 lease 查询确有发生，全部参数/userData 保持且底层写入次数为零。
- R04：solver.inputGeometry 每次返回从真实固定底层 API 取得的旧冻结几何（temperature 始终 20），同时 source temperature 变为 42；Host readback 必须拒绝，参数/userData 不写入且原帧保持。不根据请求计算原生成功输出。
- R05：Host 第二次实际 wire enumeration 返回 1 个真实连接和最多 10000 个额外连接；必须在单次枚举最多 5 项时拒绝，不消费 10000 项，无参数/userData 写入且原帧保持。
- 正常零振幅：实际 Host prepare/write/readback→实际 addon restore→再次合法零振幅 write 保持原始固定 v 和正常回滚流程。本用例不宣称非零 VEX、真实仿真或新 PID 正向 HIP 恢复通过。

首次 `review-guards-owned-v1` 的两版 R04 失败来自测试错误码预期与生产实际拒绝码不一致，不是生产漏拒绝。已将永久断言严格固定为实际的 RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED，同时加强 R04 为每次都返回旧固定 geometry；最终结果不把首轮失败改写为 PASS。

生产绑定：Host `8f263e25501804ef684a0a95a4fe568050513dcebfcd7130f329c62f9260a045`，program `39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`，addon `31147b4a7910a800cec77237d9814c5db89853f3f3eebfbad46fbeebc8f684c5`。后续源码修改及独立复核由主统一安排。
