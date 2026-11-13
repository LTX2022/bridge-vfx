# P01 guard 顺序及 addon 首批接线只读复核

2026-10-14。**REQUEST_CHANGES：剩余 R06/P1（部分关闭）及新增 R07/P1。** 只读生产/tests；仅 review outputs 中新增可执行实际 API 探针和本报告。未跑真实 DCC、仿真、缓存、渲染、正式子进程或全量组；不等待最终 addon tests。

## R06/P1：身份和限值已关闭，FPS/出生 gate 仍漏末次漂移

Host 末端已按 `_native` → `_channel` → `_limits` → `_binding` 顺序核对。相同 phase 定位探针重跑，nonce 和 strict maximum 漂移两版均 `PARTICLE_EMISSION_CONTEXT_CHANGED`，这两项 CLOSED_SCOPED。

但是，最终 `_channel` 的 actual rate.eval 把 FPS 24→30、或 constantactivate 1→0 后，两版仍 accepted=true，返回 old actual_rate=888.4559140108928。原因是 `_native` 仍在该含求值的 channel 读取之前，后续 `_limits` / `_binding` 不核对 FPS/gates。这是 R06 原案例尚未关闭，不是另加一层假设竞态。

建议消除最终 channel 身份采集的带求值副作用，或确保最后实际求值之后再核对原生 FPS/门控；完整 channel/语言/keys/外推仍必须核对，不能仅删除保护。复现：`actual_probes.py`，本次完整输出 `probes-guard-order-v1.json`，各输入 source_before/source_after 一致。

R02–R05 同一原探针继续正确拒绝、回滚零写入、初始化 records=0/fresh retry 成功；自有正常跨秒仍接受，R01 外来 channel 替换仍拒绝。

## R07/P1：实际 manifest 写入后缺最终 private/native 核验

共享 addon 的 `_fx_apply_candidate_unfenced` 在参数/domain readback 后执行 `_fx_cache_subject` / `_fx_store_manifest`。持久化成功就 `_fx_release_planned_items`，P01 Host.release 无 binding/native 检查，仅 pop 私有 token，最终操作 gate 依赖之前的 readback_verified。

新增 `addon_commit_probe.py` 使用实际 `test_particle_emission_addon.Fixture` 和实际 software client 的 `agent.fx.apply_candidate`，**仅在底层 actual root.setUserData 写 bridge_fx_manifest_v1 的边界插入一次 native gate 改动**：实际 emission.constantactivate.set(0)，随后调用原 setUserData，原 addon 持久化/返回均真实执行。没有替换 `_fx_store_manifest` / writer / host.readback 的正常返回，没有手写成功回执。

两版实际结果 `changed=true`、return gate passed=true、accepted=true、actual_birth_gate_after_return=0、pending_transactions=0。public candidate 以可信已应用事实成功返回时，实际出生 gate 已禁用且回滚 token 已丢弃。旧正常参数表达式 scope 仍为 BLOCKED，不能掩盖 operation gate 的错误成功。

建议在持久化之后、token release/成功返回之前，于现有 persistence try 内执行一次 P01 private/full native readback/guard；失败沿已有参数+manifest 回滚路径，保留外来 gate 当前实际状态、不擅改他人 gate，但必须拒绝 operation success。不能简单把 release 改为抛错却放在 persistence try 之外，导致已写 manifest 没有恢复机会。

命令 `.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/addon_commit_probe.py` 正常退出0，两版一次 negative API 场景，实际耗时约7.27秒；输出 `addon-commit-probe-v1.json` 绑定执行前后源码一致。

## 首批 addon test 审查

`test_particle_emission_addon.py` 三项走真实 client/candidate/manifest 逻辑，替身限在 native API。Clock 用实际 bottom Parm/TemplateGroup 泛化发现，没有向静态 capture 填造未捕获 machine 字段；固定 birth_rate/seed/gates 属显式底层输入。Python expression 实际 eval，不生成 simulation geometry。setKeyframes 修补只恢复 actual native expression/language，与完整 channel 回滚要求一致，未替换 production rollback/校验。

本次源码阅读未发现这三项独立的 P1/P2 夹具问题。第三项是保存后修改同实例 nonce 的拒绝测试，不能称新 PID 重开验证；当前 test 名和 P01 missing_evidence 没有宣称新 PID已完成。主 agent 正在跑这些 tests，本 reviewer 未重复整组，只执行上述新增 targeted negative probe。

## 当前源码 SHA256

| 文件 | SHA256 |
|---|---|
| native_particle_emission_host.py | 81a93e307a00a2717c5c86ac635d26d4e2c5b3049092f6399a43ed8f8d80ff26 |
| native_particle_emission_program.py | 5bb94f7de9ea2b95d872bd514025e7e088acabee944b44142a13c5fbb8ab686e |
| native_particle_ocean_geometry_domains.py | b8334bafc4aecc137c400e66bedb5dc8057367f2294ffe192fb42f93325f25aa |
| test_native_particle_emission_host.py | cb230f7071899b903c7a358011b8570133f3767072cef7b75610a677c916811f |
| plugins/houdini/_impl/houdini_bridge_addon.py | 22611b45c4d2a40e5575118a25d198958dedade902fa45adbc0394228a993c2e |
| tests/unit/test_particle_emission_addon.py | 5c10bfd0eb28390ac4a8c85c45decf576bd68db5a9d287ac47055ed1ccfb7c8f |

这两项关闭前，不建议把最终组当验收冻结。报告不涉及全16域完成，真实 POP子步、跨秒积分、新PID checkpoint仍未验证。
