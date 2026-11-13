# Formal readiness / feedback 有限状态交接

时间：2026-10-04，Asia/Shanghai。用户已要求停止实现并移交其他 GPT 账号。本 writer 已停止 candidate 源码及测试写入，未回退任何部分改动。本次仅创建本状态文件。阶段尚未形成冻结 HANDOFF、最终源码清单/可逆 patch 或完整入口回归，不能据局部测试将此阶段或 M1 宣布完成。

## 路径与范围

- Workroot：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930`
- Candidate：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate`
- 本阶段证据：`/Users/user/Documents/Codex/2026-09-20/bridge-1-workbuddy-hy3-bridge-houdini/work/codex-m1-takeover-20260930/candidate/outputs/m1-takeover/formal-readiness-wiring-20261003`
- 原始备份及哈希：该阶段 `before/`、`before-sourcehash.json`。candidate 不是独立 Git 仓库，未做 commit/push。
- 有限目标：lighting 正式 controller 保存 → 有界 Houdini render → query → 可信 artifact 登记 → Nuke Read/Write 输入绑定；反馈推进依赖版本后再次保存并消费新 HIP。不是 48+2、恢复组合或全 M1 完成。
- 禁止启动真实 Houdini/hython/husk/idenoise/Nuke/WorkBuddy/HY3/model；已执行验证仅使用现有 Python/TCP 原生 API 替身和 tests/fixtures/exr 既有 EXR。

## 当前改动

1. `workbuddy_assembly.py` 新增 `prepared_graph_facade` contextmanager，抽取已有 bootstrap / software / diagnostic / production 装配，生产仍由 ensure_hosts → GraphJobService / TaskGraphCoordinator → build_graph_facade 组成。校验 prepared snapshot manifest；退出只关闭本 context jobs，持久 task hosts 不由该 context 误杀。
2. `prepare_workbuddy_graph.py` 生成 server 保留 snapshot hash 验证和原 CLI/handoff 分支，改调用上述共用装配。
3. `domain_readiness.py` 增加显式 per-case `case_facade_factory`，验证 owner；lighting 主链执行共享生产 facade graph_propose/trial/save/reopen/render/query/register/consume/Nuke render_binding。两个有界帧为 `[1,3]`；候选场景验证 exposure，推进 graph_version、产生新的 saved_scene_id/sha/dependencies 后渲染。登记首次 OSError 最多重试一次，仅同 operation，不重渲染。approval_recovery 仍明确 BLOCKED；material 仍未建立本批正式输出链。旧 host_client 路径标 diagnostic，不提升正式证据。
4. `run_full_readiness_cases.py` 增加显式 `--backend production --prepared-projects <json>`；映射结构为 `{exact_houdini_version: {case_id: absolute_prepared_project_path}}`。通过 `prepared_case_factory` 使用同一共用装配，缺配置不 fallback。`--software-processes` 只能在 production 显式指定；默认诊断模式保留。
5. `workbuddy_graph_mcp.py` feedback 从可信已登记 graph 的 native_layout 解析嵌套 owned 节点。已登记 native render 域使用 `native_render_domains.control_contract/candidate_write_plan` 的公有语义名、范围、实际目标和 gates；没有放开任意 raw native path/parm。
6. `feedback_versions.py` 沿用 PREPARED / DISPATCHED / readback / COMPLETE 状态机，持久化 native domain candidate 描述及摘要。领域分支调用既有 `agent.fx.apply_candidate` 原子原生事务，并按冻结计划的 target/gate names 读回，避免 eval 无关 `initforedit` 原生表达式；恢复不重复事务，plan 被改拒绝。非目标全场景不能仅由这些 names 证明，仍依赖原 native transaction 与最终 scene_contract。
7. `test_domain_readiness_evidence.py` 增加既有底层 fixture 的双版本、build/causal 4 子用例，通过同一 shared factory，验证最新保存 HIP sha、版本、同 operation 登记重试、仅两次 native render 和 Nuke 输入绑定；可以用 `BRIDGE_FORMAL_READINESS_EVIDENCE_DIR` 保留新测试项目。
8. `test_feedback_versions.py` 增加 native candidate commit 中断后恢复不 replay、冻结 plan 篡改拒绝测试。
9. `test_production_task_hosts.py` 本 writer 曾仅在原 `test_formal_houdini_render_saved_worker_fact_ledger_and_stop` 增加 9 行 graph_version/foreign-owner 拒绝/owned exposure 编辑/version/path 断言。之后该文件明确交回 ocean 独占，本 writer 未再写它；原误设 `/stage/light` 的断言已向主控说明应为 `/usd_network/light`。下表为移交时整个共享文件当前 hash，不能把其全部 diff 归本 writer。

## 当前文件 SHA-256

| 文件（相对 candidate） | SHA-256 |
| --- | --- |
| `packages/vfx-pipeline/src/vfx_pipeline/domain_readiness.py` | `aebb30510bb883d71cecfdc8a503c304af63b7c3deb40dded14874e1a423606f` |
| `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py` | `c8a532c07c94d72d39beba052643a0371a20e8abfa4de40b04f428f4389eb0a1` |
| `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py` | `d40f9a7ad5d666506cd48e8d83e2f9bd12dbdfaa027e777703067dfc06febf6d` |
| `packages/vfx-pipeline/src/vfx_pipeline/feedback_versions.py` | `2a5f2b266cbb3adf2571f5d8c75a7a9d481ee15d69fac77ae21683a204e1c39a` |
| `tools/run_full_readiness_cases.py` | `77eee24ad44b916e9dbd6094a514f5a88a19e6e6d6eaa4d134753abc0099ead0` |
| `tools/prepare_workbuddy_graph.py` | `491a2ff6dc968be560e1f258e953aea35479191101a8de3f77a232c4d3b93a4a` |
| `tests/unit/test_production_task_hosts.py` | `bd8fe46b3cb3ef519daed131237de483052a0dd44e54a2b83bd0ad4b1dbd1310` |
| `tests/unit/test_domain_readiness_evidence.py` | `28fa78e6d6cad50fdf75e42e2cf3c5b97481f8be2397ef773d0fcb40528ae86b` |
| `tests/unit/test_feedback_versions.py` | `bb446ad15b3fb9a9cd3148466f2f90923402661a121fb35e7ad650684e18477e` |

## 已运行命令与实际结果

下列命令均在 candidate 下。通用前缀：

```sh
PYTHONPATH=packages/vfx-pipeline/src:packages/dcc-task-runtime/src:packages/houdini-bridge/src:packages/nuke-bridge/src:tests/unit:tools /opt/homebrew/opt/python@3.11/bin/python3.11 -m unittest
```

- `test_production_task_hosts.ProductionTaskHostsTests.test_formal_houdini_render_saved_worker_fact_ledger_and_stop`：修前正式 generated server 红测，退出 1，1 项 / 4.505 秒；`red-formal-feedback.log`，owned lighting exposure 返回 GRAPH_REQUEST_REJECTED。
- 同一命令的第一次实现后尝试：退出 1，1 项 / 4.587 秒；文件名 `green-formal-feedback.log` **实际仍是失败日志，不是绿证据**。错误为全量 `node.parms` eval `/usd_network/light/initforedit`。随后改为冻结 native plan targets+gates 的 names 读取；本 writer 没有在最终源码上重跑此 generated-server 单测，后续应向 ocean 核对其新结果。
- `test_feedback_versions`：3 项，退出 0；`feedback-unit.log`。当时尚未加新测试，仅旧回归。
- `test_domain_readiness_evidence test_feedback_versions`：6 项，退出 0；`readiness-feedback-unit-attempt01.log`。当时尚未加新集成测试。
- `test_feedback_versions`：扩展后 4 项，退出 0；`feedback-expanded-attempt01.log`。
- `test_domain_readiness_evidence.DomainReadinessEvidenceTests.test_prepared_lighting_controller_saved_feedback_render_ledger_and_nuke_binding`，`BRIDGE_FORMAL_READINESS_EVIDENCE_DIR=outputs/m1-takeover/formal-readiness-wiring-20261003/native-attempt01`：退出 1，4 子用例失败，28.287 秒；`formal-runner-attempt01.log`。实际到达正式持久 render QUEUED，但 runner 漏把 QUEUED 当进行中状态，过早判失败。已补 QUEUED；失败目录保留。
- 同一集成命令，目录 `native-attempt02`：退出 1，4 errors，30.219 秒；`formal-runner-attempt02.log`。正式主链成功返回时 `ReadinessCase.to_dict` 收到重复 boundary_kind；已改在构造 ReadinessCase 前 pop 实际 boundary_kind。失败目录保留。
- 最后命令：`BRIDGE_FORMAL_READINESS_EVIDENCE_DIR=outputs/m1-takeover/formal-readiness-wiring-20261003/native-attempt03` 加上述通用前缀 `test_domain_readiness_evidence test_feedback_versions`：**退出 0，8 项，36.298 秒**；`core-attempt03.log`。其中集成方法含 Houdini `21.0.631` / `22.0.429` 各 build_inspect / causal_candidate，四个 readiness.json 均记录局部 PASS、graph_version 分别 0 / 1。这只确认此受控软件边界下的局部断言通过；没有冻结全依赖 build，不能视为正式发布/真实宿主/视觉/全领域验收。

最后四个实际回执位置：`native-attempt03/<21.0.631或22.0.429>/<build_inspect或causal_candidate>/readiness.json`，完整原生 fixture 项目、保存 HIP、frame EXR、ledger/operation 记录保留于相邻路径。

## 进程确认

本 writer unified exec sessions：19681（sandbox TCP bind失败，退出1）、99547（正式红，退出1）、72183（表达式失败，退出1）、91233（runner attempt01，退出1）、8294（attempt02，退出1）、53200（最后 core attempt03，已读取 completion，退出0）。所有已退出。

移交时只读执行 `ps -axo pid,ppid,command` 过滤本阶段路径和上述测试名：仅匹配本次 ps/rg 自身，没有测试 runner 或本阶段 fixture 宿主进程。最后集成测试各 case 的 finally 已调用 stop_hosts；本次没有再运行任何测试。其他 writer 的进程不由本 writer 断言或操作。

## 未完成与下一步最小行动

1. 核对上述当前 hash 与同账号移交 bundle 后保留 partial candidate，不回退。先核对 ocean 对共享 production_task_hosts 单测的实际结果与写入范围。
2. shared factory 修改后尚未完成原 generated-server/software/diagnostic/handoff CLI 兼容组回归；`run_full_readiness_cases.py` production CLI 配置缺失分支和完整命令尚未运行。已有8项绿不能代替这些入口验证。
3. 实现尚未经独立最终代码审阅；需尤其检查 per-case owner/source、native domain candidate 的持久计划与 scope、故障恢复、跨 graph/current scene 的拒绝边界；不得为使测试通过修改原生替身能力。
4. 全阶段尚未生成 after-sourcehash / 最小可逆 patch / 冻结 HANDOFF 和正式 final-build 核验。before备份已在本阶段，可在确定最终范围后从备份生成仅本 writer 文件的 patch；共享 tests文件须按 ocean 最终归属整合。
5. 不扩大本批为 48+2、材料渲染、组合恢复或 M1 完成。真实 Houdini/Nuke/WorkBuddy/HY3/model、真实 render/visual/release 均未验证。

candidate 源码和测试写入已停止。此次状态文件写完后，本 writer 不再写任何文件。
