# P01 独立只读阶段审查（2026-10-14）

**REQUEST_CHANGES，限定 P01 参数表达式/Host/当前核心路由与 addon 接线；不是全 16 域结论。** 本报告用于尽早交付可执行阻断，不等待尚未完成的正式夹具。仅新增 review outputs；生产和 tests 未修改，未提交，未运行 DCC/正式进程/全量测试。

## 当前 findings

| ID | 等级 | 当前状态 | 可复现问题 |
|---|---|---|---|
| R01 | P1 | CLOSED_SCOPED | 最后 native gates 读取期间替换 rate expression 后仍返回旧值。实现者已补最后完整 channel 比较；同一两版探针现在拒绝。 |
| R02 | P2 | OPEN / boundary | Host 允许缺 session_id/process_generation/plugin_build 的 identity 建立注册。生产共享 producer 回调正常场景提供且验证这些字段；不是合法租约已被攻破。 |
| R03 | P1 | OPEN | `_transaction` 验证后，实际 channel capture 的 native eval 将 nonce 改为新身份，restore 仍实际写回先前 channel。 |
| R04 | P2 | OPEN | Host 不采集实际 strict bounds，不调用已有完整数学范围 helper；strict maximum=1300、基准1200、p30 的840..1560分布仍允许写入，只验证当前秒888.4559。 |
| R05 | P2 | OPEN | 初始化末次 native 观测失败留下自己 provisional record；fresh node session 重建后合法重试被旧注册阻断。 |

具体触发、证据版本与修补建议见 `EARLY_FINDINGS.md`。优先修 R03；其次 R04/R05，R02补严格 host identity 守卫。完整关闭必须复跑这些实际 API 探针，不能只改报错文案或新增期待值替身。

## 正向检查与未验证边界

自有表达式跨秒更换 actual evaluated rate、source 未变时两版正常读回。最早 evaluated 被误收进 channel identity 的中间态在探针执行前已修正，不计当前 finding。程序使用固定 seed/秒桶、纯 math/hash、显式 Python 表达式语言，不生成仿真几何。公开 route 共用旧 constantrate 字段，birth_rate+variance 合并一个写入；Host 只能由私有记录获得 authority，userdata/caller basis digest 不授予权限。

当前 `readback.status=BLOCKED`、scope=`native_parameter_expression_only`，明确保留 native 子步消费、跨桶积分和新 PID checkpoint 缺口。不得将本批参数控制通过升级为真实 POP 生产成功。软件归档只读测到的是 actual bottom API 状态；完整 addon 正式 fixture 尚在实现，controller mirror 尚未最终同步，这些不列作已完成验收。

时钟目前依据实际 template labels 唯一发现 Offset Time/Scale Time machine names，核对真实 scalar 类型/值/驱动/可写性，network/solver scale 均要求1。scene `hou.time()` 与 `frameToTime` 核对，Offset Time 冻结为出生起点，与 [SideFX DOP Network](https://www.sidefx.com/docs/houdini/nodes/obj/dopnet.html) 的场景/仿真时钟区分相符；当前官方文档是滚动22，不冒充两版 native 运行证据。本机 same-build static 补证见已有 `native-interface-audit.md/json`，不是本审查新增的运行 PASS。

## 命令、结果和源码绑定

命令：`.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/actual_probes.py`。

`probes-initialization.json` 是当前有效阶段探针输出：六种案例×两版，共12行，脚本正常退出；返回接受/拒绝状态用于复现，并不等价12项验收PASS。每行在同一解释器加载当前生产模块，actual API 时钟/channel/identity/gate 由独立底层夹具暴露。source_before/source_after 摘要包括 Host/program/core/fixture；若后续源码改变，本报告结论必须重新绑定。没有复用旧测试签名、密钥或生成成功回执。

早期 `probes-initial.json` 证明 R01 原状态；`probes-after-channel-check.json` / `probes-rollback-limits-v2.json` 是修补后中间记录，保留必要审计。`probes-rollback-limits.json` 空文件是 import hou 夹具同步期间失败诊断，明确不作结果证据。

审查保持生产/tests只读；收到更新实现后可针对这些同一 native API 触发只读复核。当前不签最终 PASS。
