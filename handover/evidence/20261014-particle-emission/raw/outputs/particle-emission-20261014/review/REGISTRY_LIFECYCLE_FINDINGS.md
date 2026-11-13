# P01 生命周期阶段审查：新 R08/P2

2026-10-14，限定当前软件底层 scope，生产/tests只读。**R08/P2 REQUEST_CHANGES：scene epoch 后旧 private registry 干扰 absenceconfig 的 legacy control。**

## 同一 actual addon/public command 的有效复现

`registry_lifecycle_probe.py` 第二案使用已有 addon Fixture 的已注册 P01、p=0 当前场景，然后调用真正 addon `_bridge_scene_event(BeforeClear)`，实际 destroy 该软件场景 owned root，再调用正常 `agent.fx.build_preview`（不携带 particle_emission_basis），最后调用正常 `agent.fx.apply_candidate({'birth_rate':1800})`。

两版相同：records_after_clear=1，fresh rebuild accepted=true，records_after_rebuild=1，但 legacy_candidate refused `PARTICLE_EMISSION_AUTHORITY_REQUIRED`。新 build 已实际创建新节点并发当前 epoch 租约；不是 raw saved HIP重开，也不是试图恢复旧 P01 authority，不在 new PID恢复范围。

根因：`_bridge_scene_event` 只递增 epoch，不清 P01私有 records/snapshots；Host.initialize 在 absenceconfig 立即返回 BLOCKED，不清失效记录；Host.registered 仅按 emission path 匹配旧记录，不比较当前身份/session，因此同名新节点的 legacy birth_rate 被路由到 P01 Host.observations，后者正确拒旧 identity，却错误阻断本应无 P01 的普通 legacycontrol。

建议在 scene event 中按私有 lock 使旧 P01 records/snapshots失效；也可在可信新 build lifecycle 内定向 CAS移除已证明失效的 registration，再决定 legacy/P01 routing。不能简单把 observations 的身份校验放松，不能用 raw HIP/userdata重建 authority。保留当前场景有效注册、正常候选失败前有效记录和其他根；若设计 scene clear/merge 全部失效，应显式覆盖事件及待恢复 token。

## 其他生命周期检查的范围限制

第一案 same-scene rebuild 后 P01 context 仍与旧 context完全一致，但 build 本身提前被旧 particle_size collector 的底层夹具 API 缺 `number()` 拒绝。此案是 fixture 边界诊断，不作为生产 P01 rebuild失败 finding，也不声明正常 rebuild PASS。没有改掉该生产校验，更没有生成粒子消费成功几何。

Host 自己 initialize最终 observation失败后的 CAS撤回已由 R05探针验证；shared addon outer build后续失败没有观察到专门 P01 build transaction清理。尚未用 fresh build后续 failure证明其具体破坏，因此不另立猜测 finding。已有有效 native注册在 unrelated build失败时不应被无差别删除。

raw saved HIP改 identity 被拒是正确行为，本轮不需要 new PID恢复。inprocess actual client scope和Clock symbolic generic API测试继续明确软件边界，不是 same-build原生事实或手写 normal receipt。

## 证据绑定

命令 `.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/registry_lifecycle_probe.py`；退出0，四个场景（两类×两版），初次约10秒后返回 session，随后完成。完整结果 `registry-lifecycle-v1.json`，source_before/source_after 一致：

- addon `c58095a3099b13ce46a7708582184f7d59768ccf2da267da12ea95403b9bc1cb`
- Host `29f8c99c33198278ef1a722efbb37e36adf0efbbe6c44d881a2df11822f9d731`
- addon fixture `a5780a1f671d89013b781aafb396b48b3e96b18b3079626432c4bf8c57ec4099`

## R07 小修复核

实现者已在 `_fx_store_manifest` 后、persistence try 内加入仅 P01 prepared items 触发的 frozen_writes 完整域读回；原 typed controls路径保持不变。独立同一 actual root.setUserData API race probe在当前候选上重跑，两版均 `CANDIDATE_PERSIST_FAILED`、actual gate仍0、private pending=0，不再误报成功；本触发 R07记 CLOSED_SCOPED。输出 `addon-commit-after-guard-v1.json`，源码前后一致，仍绑定 addon c58095... / Host29f8... / fixturea5780...。生产/tests未修改，未构造 normalreceipt。

该 targeted probe正常结束约7.32秒；真实参数+manifest具体复原断言还须纳入最终 frozen affected组，当前仅关此实际触发的 operation误成功。本报告为阶段 finding，不是最终冻结验收。
