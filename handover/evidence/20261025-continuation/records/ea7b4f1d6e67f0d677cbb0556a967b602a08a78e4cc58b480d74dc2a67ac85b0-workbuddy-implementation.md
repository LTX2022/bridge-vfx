# WorkBuddy 桌面 HY3：候选接入与真实验收

本轮只验证软件候选。真实 Houdini 21.0.631、Houdini 22.0.459、Nuke 17.0v1、WorkBuddy/HY3、视觉及生产验收分别待执行。历史样本不能提升本候选支持等级。

## 操作环境

用户已选择 WorkBuddy 完全访问权限，保持该设置，不调整全局配置或沙箱。Bridge 的任务所有权、租约、媒体白名单和缓存确认是协作约束，不是操作系统隔离。

用交付的三类 Skill 安装器在明确目录离线安装；通过该目录的 `run_runtime.py` 启动运行库，不能借用开发 `PYTHONPATH`。版本更新和回退需要先确认旧宿主已停止，再重启，以免现存进程保留旧模块。

项目生成器 `tools/prepare_workbuddy_graph.py --output <新的目录>` 生成项目级接入目录。诊断模式不启动 DCC；production 必须使用可信控制端提供的宿主配置。模型不能提供可执行文件路径或控制签名。使用 `tools/preflight_real_acceptance.py` 进行不启动宿主的配置/案例/资源预检。配置和操作卡未通过预检时不能进入 live。

## 路线及模型证据

记录三类独立事实：操作者在 WorkBuddy 选择 HY3 的路线记录、对应会话的工具调用/附件证据、后台模型身份。无法从可信提供方确认后台身份时记为 `unknown`。用户界面标签、模型自述、历史豆包/API 回执不证明当前后端身份。

默认只允许控制端登记的合成媒体及允许派生内容；附件失败必须显式报错，不静默只发文字。项目中的任务文字需要包含 domain ID、参考登记 ID、具体目标、允许的反馈范围和短作业预算。未经授权不传私人项目、原参考或派生内容。

## 真实验收交接

操作者先在项目目录选择 HY3 并确认连接器，记录会话与版本；依操作卡运行建图、结构读回、保存、冷重开、明确活动帧预览、反馈与失效检查。单次最多 12 个明确帧、120 秒。仿真/缓存确认单独绑定帧段、路径、估计占用、内容版本和失效范围。未知停止继续占用唯一重作业名额。

每张操作卡必须绑定原生版本、节点/连接/参数依据和用例证据，包含原始事件日志、操作身份、产物来源与停止事实。原生依据未补齐的域保持阻断，不能用统一操作文字替代精确卡片。

软件证据只写软件验收矩阵。真实通过索引仍为空；只有下一阶段经独立核对的宿主、HY3 与视觉事实可以晋级，不能自动把软件 PASS 写入 live 索引。

## 当前支持晋级证据格式

`outputs/live-validation/index.json` 的 `workbuddy_runs` 接收 `bridge.workbuddy.release_attestation/1`。每条必须记录 `evidence_id`、`route_id=WorkBuddyDesktopRoute`、`source=real_host`、`status=passed`、当前 `build_id`、仓库内 `manifest_path` 及文件 `manifest_sha256`，由独立可信操作者按现有 HMAC 机制签发 `evidence_identity/evidence_attestation`。

`witness_bindings.route` 精确包含 session_id、manifest_sha256（规范化模型运行 manifest 的摘要）、selected_model=hy3、executable_sha256。`witness_bindings.provider` 精确包含 session_id、exchange_id、model=hy3、witness_sha256、provider_response_sha256。签名绑定完整记录；验证器重新解析 manifest 并重算 48 案例事件，拒绝自述统计和缺失 provider 证据。该签发属于后续独立真实验收职责，模型或软件测试无权生成真实晋级条目。

旧 `model_routes` 与 Doubao conformance 仍可用于审计历史，其通过不替代当前 WorkBuddy/HY3 支持晋级。没有可信 provider 证据时，路线可单独记录，后台身份保持 unknown，不能升级为完整 supported。

## Nuke 任务自有控制宿主

正式入口：`python -m nuke_bridge task-host start --config <trusted-controller.json>`。可信配置指定 `task_id`、`task_root`、`nuke_executable`、`addon_path`、`supervisor_executable`、精确 `version=17.0v1`、正整数 `process_generation`、可选任务根内 `snapshot`，以及不超过 120 秒的 `budget_seconds`。模型不得提交这些可执行路径。生产 CLI 不接受 software API 注入。

该入口通过固定包内 worker 启动 Nuke `-t`，由脚本主线程处理本地 TCP 请求，并创建本任务缺失的 Read1/Write1；它不依赖 GUI 事件循环。background render 使用包内固定 worker，执行前核对真实 Write 类、file knob 和精确帧集。控制宿主、渲染 worker 分别由监督器持久化观察退出，控制宿主停止不代表渲染 worker 已停止。

`start` 回执中的 port/token/expected_identity/evidence_source 用于正式装配；身份绑定 task/session/nonce/PID/process_generation/plugin_build/scene_epoch/version。`python -m nuke_bridge task-host status --work-dir <回执目录>` 重连并验证身份；`... stop --work-dir <回执目录>` 只接受监督器实际 wait 产生的停止回执。停止未知保持 UNKNOWN。脚本重开引起 epoch 变化，旧绑定必须刷新。

原生接口依据：本机 Nuke 17.0v1 官方 PythonDevGuide 的 `command_line`（`-t script.py` 及 argv）、`nuke.createNode`、`Node.setName`、`nuke.addOnScriptLoad`、`nuke.addOnScriptClose`。软件测试替换 Nuke API，但沿同一 worker、真实 Python 子进程和回环 TCP；没有因此宣称原生 Nuke 可达性已验证。
