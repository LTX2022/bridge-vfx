# Shared Houdini 有限交接状态（2026-10-04）

记录 UTC：2026-10-04T01:35:56.521391+00:00。本任务已按用户完整移交要求停止实现、candidate 源码写入和测试启动；未回退部分改动。本次唯一新增写入为本文件。该文件描述当前检查点，不宣称 M1 完成或当前整树全绿。

工作根：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930`。候选：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate`。Python：`/opt/homebrew/opt/python@3.11/bin/python3.11`。先读取工作根的 `接手执行合同.md`、`并行执行分工-20261003.md`。无真实 DCC/hython/husk/Nuke/HY3/model/互联网/仿真缓存渲染、无 Desktop 写入；native 字段/几何与通道由明确底层软件 API 模拟，生成、装配、事务、worker 生命周期与账本走正式代码。主工程未动。

## 已冻结 Crowd / Particles / Swarm（历史有限验收）

冻结阶段：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003`；入口 `HANDOFF.md`、`source-manifest.json`、`final-build-verification.json`。Crowd route 原生相对 steering factor 0–100，实际三点固定非退化 open Polygon→stash→SOP；两个 distinct clip 的 Agent payload、两个 owned states→merge→route→solver2，trigger→transition→merge→solver3；animation_blend=0–10 秒 duration，含0，实际 Linear ramp。保留合法 SOP/dopnet 布局、原 population/import、预算、lease/CAS/scene epoch/request freeze/rollback。正式保存→confirmed owned worker exit→new PID/nonce 重开直接读出几何、clip、参数与连线，未 reapply。

冻结依赖149项，build dependency manifest SHA `497dc8af78a906c9bd7f97b859317bed2fddd82518285070da01167f1f34e7f2`；六 case 每个实际复制112文件，672逐文件等值核验。核心121 tests /85.388s PASS；Crowd+Swarm两版本正式链 /38.331s PASS；Particles原7+新3控制两版本正式链 /18.292s PASS。最小 patch 实际 forward/reverse PASS。独立 Crowd formal 审查在该冻结 HANDOFF 中声明 PENDING；不得将 root 完整性核验当代码独立通过。seek 假 `uselocalnoise` 一字段 P2 已由 root 独立关闭，保留正确 popforce 字段。

- `core`：`/opt/homebrew/opt/python@3.11/bin/python3.11 -m unittest -v test_native_domain_graphs test_native_render_domains test_houdini_parm_probe test_houdini_fx_domains test_scene_lease test_c1_lease_identity test_native_crowd_hair_domains test_native_crowd_route_contract test_native_crowd_transition_contract`；exit=0，UTC 2026-10-03T14:24:24.894547+00:00 至 2026-10-03T14:25:50.656708+00:00，`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/core-green.log`，完整 argv/env/hash 在 `/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/core-argv.json`。
- `formal`：`/opt/homebrew/opt/python@3.11/bin/python3.11 -m unittest -v test_production_task_hosts.ProductionTaskHostsTests.test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen`；exit=0，UTC 2026-10-03T14:26:28.867257+00:00 至 2026-10-03T14:27:07.438449+00:00，`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/formal-green.log`，完整 argv/env/hash 在 `/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/formal-argv.json`。
- `particle`：`/opt/homebrew/opt/python@3.11/bin/python3.11 /Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/run-particle-normal-entry.py`；exit=0，UTC 2026-10-03T14:28:39.089973+00:00 至 2026-10-03T14:28:57.660439+00:00，`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/particle-green.log`，完整 argv/env/hash 在 `/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/crowd-formal-integration-20261003/particle-argv.json`。

这些结果只约束其冻结源码：当前 addon、底层 API、域图测试以及其他任务 controller/material 已继续改变；不得复用历史日志声称当前整树已通过。旧 Ocean/Hair/Cloth/source/Crowd pure/context 冻结目录均未改。

## 本批 RBD / MATERIAL：未冻结、未完成

阶段：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/domain-integration/shared-rbd-material-integration-20261003`，现仅有 `before/`、`before-manifest.json`、`owned-files.json` 和两个失败日志；没有 after manifest、正式同 build 绿、可逆补丁正反证明或完成 HANDOFF。下表为移交时实际读取 SHA256：

| 文件（候选相对路径） | 当前 SHA256 | 本任务状态 |
| --- | --- | --- |
| `plugins/houdini/_impl/houdini_bridge_addon.py` | `debc174d51c2c1ef12dbc3eb3568ed39483304fd65c466cd5a3fe213c8ef9ea8` | 已改 |
| `tools/native_schema_test_boundary.py` | `fe5fb1bcbc19c4eedd8533e37a4d6a501475f39c00af283cfe10d5ab63cc4500` | 已改 |
| `tools/software_render_api_boundary.py` | `fd0035f1d2ad7922a01a049a8d6dce2d6b1290048f7c468867488a71666d5ce8` | 已改 |
| `tests/unit/test_native_domain_graphs.py` | `5a6caac38d0261f2140ec69deb2a6f484227d255652d4e51bf80b54a343bbdd5` | 已改 |
| `tests/unit/test_production_task_hosts.py` | `bd8fe46b3cb3ef519daed131237de483052a0dd44e54a2b83bd0ad4b1dbd1310` | 本任务未改；保留 formal 9 行 |

before UTC `2026-10-03T14:41:10.111284+00:00`；before addon SHA `89f31c48f0dff89f5c1dc44e4bf9edd0875bb599d99eb6cb79e478877fd23f9e`，其他逐文件 before 哈希在阶段 `before-manifest.json`。本批实际改4源码，production test未改；不能覆盖已交接 formal 9 行反馈用例。

新增/部分实现：

- addon `_fx_rbd_activation_channel` 采实际 attributes multiparm activeN、编译 integer 类型、owned root/task/current host identity、完整 native keyframe identity、expressionLanguage、pre/post extrapolation、actual evalAtFrame 样本和 registration。writer 分支消费 `trusted_constant_activation_channel`，复用 `_fx_set_solver_activation_verified` 写 constant()/Hscript 两键 `(f−1,0),(f,1)`；registration 摘要绑定实际 keyframe identities。新增事务额外 snapshot/restore extrapolation 与 node userdata；原 root fence/manifest/CAS/cache 保留。RBD 初始化显式 `initialize_activation=True`；保持 overwriteattributes tokens、Glue/impact、startframe，负帧不删。几何读回拟采 configure 输出 primitive active。
- native_schema 底层新增 expressionLanguage、evalAtFrame、native extrapolation API/持久状态、整数 constant schedule 返回；software_render 底层 configure 输出按实际 attributes/gates/activeN 求值添加 primitive active，primitive 数据类型区分 Int。
- 域图测试新增一个两版本表驱动方法 `test_rbd_actual_owned_activation_channel_geometry_and_rollback`，拟验负/0/正帧、exact geometry、manifest 写盘失败 rollback、外来 extra key 拒绝。其 trusted identity 是 unit setup，不是正式 new-PID 链。当前首个反馈即失败，后续断言都未执行，不能视为已覆盖通过。

### 已执行失败命令与确定缺口

两次命令相同：候选 cwd，PYTHONPATH 为四包 `packages/dcc-task-runtime/src:packages/houdini-bridge/src:packages/nuke-bridge/src:packages/vfx-pipeline/src:tests/unit`，运行：

```sh
/opt/homebrew/opt/python@3.11/bin/python3.11 -m unittest -v test_native_domain_graphs.NativeDomainGraphTests.test_rbd_actual_owned_activation_channel_geometry_and_rollback
```

- 修改前 `baseline-rerun-red.log`：1 test /3.868s，FAILED(errors=2)，H21.0.631 与 H22.0.429 都 `ACTUAL_NATIVE_CONTEXT_REQUIRED: configure/@activation_channel`。这是本阶段新红，不是旧日志恢复；原始 argv 时间文件未记录，不可补称当时捕获完整证据。
- 修改后 `rbd-development-r1.log`：1 test /5.579s，FAILED(errors=2)，两版都在 `_fx_apply_candidate_unfenced` → pure `validate_applied_readback` → `_activation_fact` 报 `ACTIVE_CHANNEL_READBACK_MISMATCH: actual evalAtFrame samples`，随后 CANDIDATE_APPLY_FAILED。日志未输出实际样本数值。
- 只读源码核实了底层时间接点缺陷：`workbuddy_assembly.py` 当前 software_host_client 的 fake hou `setFrame=lambda f: None`、`frame=lambda:1.0`；新 native_schema evalAtFrame 仅调用该 setFrame 再 eval，因此时间未切换，四样本不会形成阶跃。这是当前读到的具体软件边界原因；还未修复/重跑，不能断言其修复后其他回归自动通过。不要改 pure 期待或按 requested frame 伪造返回；需在允许 owned 的底层 native schema/API 建立真实可变帧状态，controller 文件原属于 formal owner，应先协调。
- 仍需检查新全局 `_fx_scene_parameter_readback` 对有 keys 的 parm 无条件调用 keyframeExtrapolation，会否破坏旧不具 API 的局部 unit 替身；以及 native_schema Linear 枚举仅能保存，未证明其完整原生外推语义。只保留必要 native 支持，不降低 RBD strict guard。已有 rollback 表尚未走到，不可宣称失败回滚已通过。
- 当前还未做完整受影响核心、save/new PID reopen、全依赖共同 freeze、actual patch 正反或独立 review。

### MATERIAL 模块与共享缺口

媒体模块已冻结：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/material-render-output-20261003/HANDOFF.md` / `shared-adapter-contract.json`。14 core PASS 是其 same-process native software 有限证据；正式新 PID 链尚待。原11材质 roles/controls 保留，新增 render tail 至19 roles：material_binding→camera→light→settings→render_var→render_product→settings_binding，Driver render.loppath 指最终 stage，仅一 SOPimport。LIGHTING 不变；不添加通用 DOMAIN_IDS。现 `_fx_initialize_render_domain` 动态 role/renderer bindings 已可消费。

共享 `_fx_static_domain_readback` 仍是 material 分支只核 material binding，else 才核 `_fx_render_configuration` 与 H22 pixel filter，尚未修改。下一步应在最终 settings_binding stage 对 MATERIAL 同时核 material relationship+actual render_config/H22 filter，保留既有 typed native gates/rollback/persistence，不能重新 SOPimport 丢材质。

生产测试 formal 新增9行 lighting feedback 保留原字节；最后仍 `.endswith('/stage/light')`。root 已确认实际可信 layout 为 `/usd_network/light`，授权最小修正由本 owner 单写，但停止指令前尚未实施。这是交接后明确待改项，不应归因产品语义。

## 当前相关冻结模块哈希

- `packages/houdini-bridge/src/houdini_bridge/native_flip_rbd_domains.py`：`67da3db4a4fb97bec3f31131f535366ace3cf8012262493a4d0d6ec10efca956`
- `tests/unit/test_native_flip_rbd_domains.py`：`64261e31e142d1be9ad33b7319fdb6594674219860a14135ce7d7c9e3397e695`
- `packages/houdini-bridge/src/houdini_bridge/native_render_domains.py`：`4c9738133412c4b29b78a036c39a50dc9f024802b447543d55073d7f575089f1`
- `tests/unit/test_native_render_domains.py`：`7335433bb51a4eb996a15fbef2d481299227fc046b18a84fe1ac24bf1a5ec372`
- `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py`：`c8a532c07c94d72d39beba052643a0371a20e8abfa4de40b04f428f4389eb0a1`

RBD pure stage `flip-rbd-controls-20261003` 默认 trusted init 维持旧 Glue；只有显式 initialize_activation=True 分配 active row/gates。pure 合同独立复核当时因 thread limit 尚未取得；6 core/完整性审计不等于独立通过。接手先核对主控最新 review 状态。

## 自有后台进程及停止事实

baseline unit session12487此前完成 exit1；开发 unit session58447本次只轮询已有 session，返回 exit1，无新增测试。只读 `ps -axo pid,ppid,stat,lstart,command | rg 'python|rbd-native-channel|rbd-addon-channel|native_domain_graphs|bridge-host|production_task_hosts'` 于本机2026-10-04 09:33:24仅显示该 ps/rg检查命令，没有残留 Python/test/bridge-host。两个 `/private/tmp/rbd-native-channel-api.py`、`/private/tmp/rbd-addon-channel.py` 为已经执行完的临时编辑脚本，非进程；源码更改已留在候选，禁止重执行以免重复插入。不需要 kill，不操作他人进程。最终自有 candidate 写入/测试均停止；只读取状态并生成此文档。

## 移交后的最小行动顺序

1. 保存当前4文件部分改动与 before 哈希；不要回退或覆盖旧冻结证据。先修真实软件时间状态并重跑上述单一 RBD 表，实际采失败样本；再验证 first-write/已有 registration/第二阶段/manifest failure 完整 rollback、外来驱动/keys/extrapolation 拒绝，保持身份/lease/CAS。
2. 在既有正式域 case 加 activation_frame，反馈负/0/正帧；task_save→confirmed owned worker exit→新 PID/nonce task_reopen，不 reapply，直接 evalAtFrame/实际 configure active0/1、keys/extrapolation/gates/所有权。模型不提供 context/geometry，不 literal f→active，不改 solver.startframe。
3. 对 MATERIAL 双重 USD/render readback 接点与 production lighting `/usd_network/light` 最小修正；复用正式生成器/worker/save/reopen 证明 material绑定和render tail均保持。
4. 与 formal/controller 与模块 owner 协调短共同源码 freeze，核对生成前/实际复制/测试后全依赖哈希。完成必要 core/正式案例、actual patch 正反、源 manifest/日志/HANDOFF 后再独立 review。本批停止时不存在 final samebuild PASS。

保留限制：全16 M1范围不变但本次仅有限接点；48+2真实进程中断恢复、真实 DCC/全16验收及其他 blocked controls仍未完成。flame_height负值人类语义 pending 不动；不再追加开发包。本任务不负责云效仓库创建/上传，该动作由主控统一移交安排。
