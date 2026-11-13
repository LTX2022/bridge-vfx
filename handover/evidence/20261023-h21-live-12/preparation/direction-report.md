# 方向只读核查：H21/Nuke 12 授权范围

结论：**GO，允许从已冻结 11 正式激活 12；未发现静态执行前缺陷。**

本角色未执行激活、预检 CLI、DCC、模型或软件链；只写本目录。真实执行仍必须以新生成 12 的正式激活回执、原件认证预算状态和冻结 snapshot 默认预检 `PREPARED / blockers=[]` 为准。11 自身保持未授权，不能对 11 执行 `--execute`。

## 冻结身份与范围

- 仓库：`/Users/user/Documents/Code_Project/Bridge`。
- 11 scope SHA-256：`d5cba25f180ed5e3cf0f85aa910a9f01e8d41b193efe22350751b775d6b44f1e`。
- 11 bindings SHA-256：`2437bfe9cc83c904a43e90a0f13e7abe2913eb1743a65a856f31f26f8871479d`。
- review SHA-256：`85feb054b064d0adce4cce34457cac0190c7505ab7e141f40c483a4a2ca5d2d5`。
- review 唯一目标：`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-12-authorized`。核查时目标尚不存在，符合 fresh-root 要求。
- `real_host`；H21.0.631、Nuke17.0v1；ACEScg / human_project_selection / revision 1。
- 8 starts、每操作 120 秒、累计 600 秒、536870912 字节、1 heavy、0 automatic retries。
- 158 snapshot 文件、174 source_freeze、175 immutable 文件当前逐字节哈希匹配。所有原生 host / OCIO / material / USD 依据记录亦匹配。无 pyc、无 tests/fixtures 路径；scope 无 software_native_boundaries；两个 deployment 无 software 边界配置。
- 当前 11 state 的原始内容为 0 tickets、closed_reason=null；本角色未认证 HMAC，须由原件验收角色/正式预检认证，不能将此未认证读回当预算认证结果。

## 正式入口

激活必须使用 11 冻结工具：

`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-11/project/control/snapshot/tools/activate_controlled_engineering.py activate --review /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-11/engineering-activation-review.json --expected-review-sha256 85feb054b064d0adce4cce34457cac0190c7505ab7e141f40c483a4a2ca5d2d5`

使用 scope 中冻结的 supervisor Python 加 `-I -B`。CLI 需要 TTY，输入精确 `AUTHORIZE 85feb054b064d0adce4cce34457cac0190c7505ab7e141f40c483a4a2ca5d2d5`。当前用户明确授权可落实为该可信本地终端控制动作；无需更改或绕过控制代码。

激活生成 12 scope、独立 key/accounting、重新绑定的 runtime-bindings 和签名 engineering-activation.json。正式 driver 路径为：

`/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-12-authorized/project/control/snapshot/tools/run_controlled_engineering.py`

先以 12 的 scope.json/runtime-bindings.json 默认预检，确认 `PREPARED / blockers=[]`，再同一路径 `--execute --approved-scope-sha256 <12实际scope摘要> --approved-bindings-sha256 <12实际bindings摘要>`。禁止把 11 摘要当 12 执行摘要。不要使用 `--continue-nuke-tail` 或恢复旧范围。

## 实际阶段顺序与真实输出

| 次序 | 真实启动 | 依赖及预期 |
|---|---|---|
| 1 | alpha-husk | 冻结 USD 标板渲染；128x128 RGBA EXR；原始 signed started/stopped、writer image binding、alpha-output |
| 2 | alpha-nuke | 先认证第一阶段停止/绑定与原件；原生 Read 的 ACEScg 菜单和值读回；源像素及黑白背景合成，四份 EXR 写出再读、JSON观察、加性零alpha保留；认证 alpha-calibration-result |
| 3 | graph-worker / hython | 正式 graph_propose→graph_trial→graph_status；sphere_ground_v2 material_lookdev_v1；冻结分辨率128x128、frame1 |
| 4 | initial Houdini control host / hython | 仅在 graph 交接按需启动；graph_ready/nodes_verified 后 task_save，项目 saves 下真实 HIP；随后原宿主认证停止 |
| 5 | reopened Houdini host / hython | 新实例通过 saved_scene_id 从登记路径/摘要冷重开 HIP |
| 6 | main-husk 后代 | 绑定 reopened Houdini 父票据；真实 ROP node.render；saves/main.0001.exr；认证父/子停止后独立受控输出验证、登记 engineering_h21_main |
| 7 | initial Nuke control host | 上游已认证/登记可消费后才按需启动，准备并首存 saves/composite.nk |
| 8 | owned cold Nuke render worker | 冷加载 NK，消费绑定上游版本/摘要的登记产物；执行并读回 saves/nuke.0001.exr；原始回执与派生产物登记；最后 Nuke control host认证停止 |

inventory 是角色清单，并非启动时间顺序：其中 nuke-control 列在 graph-worker 前，不代表会提前启动。实际依赖为 driver `_fresh`、deferred host factory 和 prepare_nuke_project `_ensure_initial_nuke`，不会为控制器初始化额外预启动宿主。

## 停止门与结果解释

- run_alpha_calibration.py:424-432：每一阶段结束后重新核源码，认证 signed stop/returncode，并先验证 writer_process_binding，才封印 alpha-output；husk身份绑定失败不会再启动 alpha-nuke。
- run_controlled_engineering.py:803-836：只接受已授权 real_host、两个新摘要、已认证激活回执；必须从该项目 frozen snapshot 执行，并在共享锁内复验。
- native_scope.py:302-405：失败退出、停止不合法、时间/磁盘预算耗尽封闭范围；重操作槽与启动次数统一准入，未知停止不释放票据。源参数/颜色菜单不匹配、alpha歧义/加性RGB丢失、缺原始签名、身份不匹配均拒绝后续阶段。
- driver `_fresh` 通用异常关闭 controller，尝试正式停止已知 H/N，记录 STOP_UNKNOWN 并 fail scope，不重试；interrupted intent 不自动重放。
- **运行端必须覆盖特殊 `REGISTRATION_PENDING` 结果**：driver:711-716 在此分支有意保留 idle Nuke control host用于登记恢复，只关闭 stdio controller。按本轮“失败即停”，将该结果判作本次失败，使用 12 冻结 driver 的 `_stop_host(data, "nuke")`（同11代码320-341）认证停止，保留原件；它仅取production-hosts.json已绑定work_dir，核scope路径/摘要，调用同snapshot `nuke_bridge.task_host.stop`，并要求stopped=true及原始receipt的execution_returncode=0。随后用正式NativeScope重验票据；不得继续尾段或自动重跑。此为现存结果分支的运行处理要求，未改代码。
- driver `_final_result`:621-624 必须恰好 8 张角色匹配票且全部有可信停止；重验2个登记产物与最终NK身份。
- 全部机器门通过的最终态是 `AWAITING_HUMAN_REVIEW / human_visual_review=PENDING`。不等于视觉、M1、HY3或生产通过；writer/filter/flush/close内部仍为NOT_OBSERVED。

## 模型/夹具边界

- Controller 固定调用冻结 server.py `--backend production`；只在 software_test 分支才传 `--software-processes`，本 scope无法进入该分支。
- server 校验 snapshot-manifest 后只从 SNAPSHOT/packages导入；driver的tool_module固定ROOT/tools，execute拒绝ROOT不等于项目snapshot。
- preparation激活流程从已审核11 snapshot导入 prepare_controlled_engineering，复制为12；validate_activation要求12实际source_snapshot与review完全一致。
- run.json 的 requested_model=HY3、粘贴说明及两份PNG是冻结准备元数据。driver只读取文件身份及PNG头，明确metadata_only；graph_propose内容由固定工程PLAN直接提供。本执行链无模型API、image adapter或软件API fixture注入。

首个问题：**未发现静态缺陷；尚待正式落实的是 12 激活及其默认预检/预算原件认证。** 任何新预检阻断都应保持零DCC启动，返回精确首阻断，不在本轮绕过。
