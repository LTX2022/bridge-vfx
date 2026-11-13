# 第 23 次修复与范围 05 执行结果（2026-10-25）

状态：**修复已实施、测试、提交并推送（21e72fe）。范围 05 已由用户 TTY 手输授权并真实执行，推进到正式 task_save 后失效关闭；无残留 DCC 进程。**

## 范围 05 真实执行记录（engineering-chain-20261025-authorized-05）

- 授权：用户在公共 TTY 逐字输入 `AUTHORIZE 9dc8e256...`，回执 `explicit_local_terminal_controller`；scope `f32f882d`、bindings `6eb62893`，激活后预算 120s/操作、600s/累计、8 启动、512MiB、零重试。
- 执行方式：必须从冻结快照副本运行（`authorized-05/project/control/snapshot/tools/run_controlled_engineering.py`）；从仓库工作区运行会被 `ENGINEERING_FROZEN_TOOL_REQUIRED`/`ALPHA_RUNNER_FINAL_SOURCE_FREEZE_REQUIRED` 预检拦截（首次尝试 0 启动、无损）。
- 实际推进：**Alpha（husk+nuke 真实宿主）DONE、propose DONE、build DONE**；graph 交接进入 task_save 并完成 HIP 落盘（`project/saves/task-save-526f9a17928c44ddbc6f81b5138a1376.hip`，23 角色合同，无 duplicate public node——第 22 次修复在真实链路生效）。
- 失败点：保存证明层 `PRODUCER_SAVE_UNPROVEN`（saved HIP or actual contract differs from current scene）。closed_reason `ENGINEERING_DRIVER_FAILED`；Houdini 可信停止已验证，Nuke 清理记录 STOP_UNKNOWN 但复查无残留进程。
- 未到达：正式工程冷重开、husk 主渲染、controlled_output_v1 验证登记、Nuke 闭环。**不能用 05 的局部进展拼接为完整通过。**

## 第 23 次修复：保存前应用目标名

根因（两份保存合同逐参数 diff 的唯一差异）：`render` 节点 `husk_mplayname` 是跟随 `$HIPNAME` 求值的读回。`scene.save_hip` 保存即重命名 HIP；证明层的 before 捕获在旧名下、handler 回执与 after 捕获在新名下，该参数必不相等，task_save 永远无法证明。

修复（`_fx_producer_dispatch`）：

1. 全新 typed 保存（`initial_prior is None` 且显式 path）在 before 捕获前做同样新鲜路径校验并 `hou.hipFile.setName(目标路径)`，三处捕获（before / handler 回执 / after）在保存自身确立的名字下比较。
2. 幂等重放不改名、不受前置校验影响；锁内原有新鲜路径检查保留。
3. `test_scene_contract_hda_policy` 的轻量 hipFile 替身补 `setName`（与真实接口一致）。
4. 新增 `tests/unit/test_typed_save_hipname_proof.py`：改名先于 before 捕获（`before_scene.hip_path == 目标`）、完成后重放幂等不重存、非新鲜目标先拒绝且不改名。

回归：相关 8 套件（readiness_current_save / project_environment / production_task_hosts / formal_public_task_save / scene_contract_hda_policy / native_render_domains / frozen_render_scene / solver_sourcing_host）失败清单与冻结基线 44 项完全一致，零新增；定向 43/43 通过。

## 下一步

1. 从母范围重新 prepare-successor 创建 06 候选（冻结含第 23 次修复的当前源码）→ review → 用户 TTY 手输授权 → 新范围执行完整链。
2. 不重新执行 05，不拼接 05 局部结果；44 项基线夹具失败仍待单独决策（fake-hou schema 未含第 21 轮修复 #8 的 H21 USD processor 参数族）。
