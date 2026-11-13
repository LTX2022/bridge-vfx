# 第 22 次修复结果（2026-10-25）

状态：**已实施、已定向测试、已提交本地 main（4b05e90），未推送。** 真实软件执行仍按 [FREEZE_HANDOFF_20261025.md](FREEZE_HANDOFF_20261025.md) 等待用户新范围授权；本页不恢复任何历史执行授权。

## 实施内容

`_fx_bind_graph_trial()`（plugins/houdini/_impl/houdini_bridge_addon.py）按冻结交接认可方案修改：

1. **registered 分支（schedule 已严格校验）**：manifest `nodes` 使用编译器精确 leaf 角色映射。原生确有 `source`/`output` 角色（如 pyro 域）经精确映射保留；material_lookdev_v1 无 `output` 角色，不再猜测注入别名，消除 `output` 与 `normal_map` 同路径导致的 duplicate public node（完整工程 04 task_save 的最早阻断）。
2. **leaf 冲突失效关闭**：不同 subnet 同名 node_id 会使 leaf 映射静默丢角色；现抛 `SCENE_STATE_MISMATCH "registered roles collide on public node names"`，不丢真实节点。当前所有注册域布局无此冲突，该门为防御性。
3. **legacy 分支（无 schedule）**：保留原 fallback（`/source` 匹配否则首节点；`/sink` 匹配否则末节点）与 source/output 注入，行为与改前逐字节等价。原代码 `/output` 匹配条件含 `and schedule`，legacy 从不匹配 `/output`，新代码保持一致。
4. validator（operation_receipts）未改，无笼统去重。

manifest `nodes` 的 `output` 键消费点复核：`submit`（16289 行附近）与 cook 循环（16566 行附近）缺键时分别抛 `SCENE_STATE_MISSING` / 置 FAILED，均失效关闭，且属 FX solver 执行链，material/渲染链不依赖该键；工程链工具（run_controlled_engineering 等）无 manifest `nodes.output` 依赖。

## 测试

- 新增 `tests/unit/test_bind_graph_trial_roles.py`，4/4 通过：material 无 output（精确 23 角色、capture 合同路径唯一）、registered 真有 output（经补丁布局覆盖，真实 pyro 图不受 fake-hou schema 支持）、legacy fallback 保持、leaf 冲突拒绝且 manifest 回滚。
- 回归对比：test_readiness_current_save / test_project_environment / test_production_task_hosts / test_formal_public_task_save（26 失败）与 test_scene_contract_hda_policy / test_native_render_domains / test_frozen_render_scene / test_solver_sourcing_host（18 失败），改动前后失败清单逐条一致，零新增失败。
- 复核方式：独立子代理因模型并发限制不可用，改为结构化自查（diff 一致性、函数内残留引用、消费点、角色清单、夹具隔离、测试复跑），六项均通过。后续如需可再安排独立复核。

## 冻结 HEAD 既有测试失败（非本轮引入）

冻结基线 117cb43e 上上述套件共 44 个失败，与第 21 次修复 #8（H21 USD processor 目录写入 `enableoutputprocessor_savetodirectory` 等）加入 `trusted_initialization_plan` 但未同步 fake-hou schema 有关；冻结时未重跑全量测试（交接文档已注明）。本轮未顺手修改这些无关失败，清单存 /tmp/before.txt、/tmp/before2.txt（会话级，未入 Git）。

## 下一步（需用户明确授权后进行）

按 FREEZE_HANDOFF 接手顺序第 3-6 步：`prepare-successor` 创建新完整范围（05），审核 scope/bindings/宿主/场景/预算，公共 TTY activate，实际重做 Alpha→建图→handoff/task_save→冷重开→husk 主渲染→controlled_output_v1 验证登记→Nuke 闭环。不重新执行 04，不拼接 HIP21 与 04 Alpha。
