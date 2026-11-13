# P01 当前阶段限定结论

2026-10-14。**Host：PASS_SCOPED；addon 提交闭环：REQUEST_CHANGES，剩余 R07/P1。** 这是冻结前阶段复核，不是最终 affected 组、全域或 native 验收绑定。

R01–R06 原探针在 H21/H22 均符合预期：自有跨秒可读；外来表达式/不完整身份/旧 nonce rollback/严格范围越界被拒绝；初始化失败 CAS 清除及 fresh session 重试成功；最终 channel actual eval 中改变 nonce/FPS/gate/strict maximum 四案全部拒绝。当前 Host SHA256 为 `29f8c99c33198278ef1a722efbb37e36adf0efbbe6c44d881a2df11822f9d731`。执行前后源码一致，完整结果 `probes-stage-guard-v1.json`。

R07/P1 仍存在：actual manifest userdata 写入期间把 actual constantactivate 改为0，addon 仍 accepted=true、operation gate passed=true，两版复现。当前实际执行 `addon_commit_probe.py`，约7.69秒、退出0；没有重跑已通过的三项正常 addon 方法/全量/正式进程。结果 `addon-commit-probe-stage-v2.json`，source_before/source_after 一致，绑定同一当前 Host、addon SHA `22611b45c4d2a40e5575118a25d198958dedade902fa45adbc0394228a993c2e`、addon test SHA `5c10bfd0eb28390ac4a8c85c45decf576bd68db5a9d287ac47055ed1ccfb7c8f`。

因此需要先在持久化 try 内、actual manifest 写入后及释放 private token 前进行最终 P01 full native/private guard。该 guard 失败须走已有参数/manifest恢复，不宣告 candidate成功；不要改实际外来 gate。具体触发及建议沿用 `GUARD_ADDON_RECHECK.md` 的 R07，仅 R06状态由本报告更新为已关闭。

Clock 泛化 API 测试中的 arbitrary machine names 是显式 bottom symbolic 输入，不作 same-build machine facts。staticinterfaces/capture 未因此扩写；缺失实际 clock模板/类型/有效字段必须拒绝，原拒绝探针继续保留。三方法23.501秒通过是主 agent 本轮提供的阶段结果，本 reviewer 不冒充自己已复跑其整组。

生产/tests 只读。待实现者处理 R07、testsworker freeze并集中一次 final affected 组后，reviewer 再针对最终源码及实际日志做最终绑定。真实 POP子步/跨桶积分/新PID checkpoint仍未验证，不能升级 native PASS。
