# Bridge Agent Plugin

这是现有 Bridge 执行核心的薄入口：一个共享 runtime、三个精简 Skill 和 stdio MCP wrapper。图操作仍调用 `prepared_graph_facade` / `GraphMCP`，没有第二套业务实现。私有上下文直接调用 `dcc_task_runtime.private_context.PrivateContextReader`，没有文件发现、学习或写回功能。

## 已完成工程的受控接收

操作者可使用完整安装包的 `scripts/bridge_mcp.py register-delivery --project-id completed-geometry --label CompletedGeometry --source /absolute/cold-consumption/result.json` 登记已完成的真实独立几何交付。来源须通过原scope签名、typed保存和冷开、几何评审、主图登记、原生Nuke冷消费及四文件核验；模型工具不接收任意来源路径。

该工程类型为 `geometry_delivery`。新agent沿 `bridge_projects`、`bridge_select_project`、`bridge_tasks`、`bridge_continue_task` 取回四文件，首次接收会保存签名回执并推进revision，后续连接只读核验。原失败保持；NK与Nuke输出按派生文件登记，不伪造旧C2成功。该类型仅用于观察已完成成果，不开放创作、反馈、取消或作为新创建任务的模型基线。

## 默认后台连接

已有完成工程先使用下方工程选择与原任务查询，无需后台连接。需要新后台实例的任务，通过 `bridge_health` 确认入口，再自行生成稳定 `request_id` 调用 `bridge_connect`。用户无需填写软件路径、端口、token 或复制启动脚本。后台使用发行包自带 runtime 和包外私有连接配置，固定连接 Houdini 21.0.631 与 Nuke 17.0v1；每个请求最多启动各一个独立后台宿主，不打开旧工程、不恢复旧失败任务、不执行渲染。

`bridge_health` 的 `state:READY` 仅表示 `entry_ready:true`；`dcc_connected:not_checked` 明确表示尚未检查软件连接。该工具不启动软件、不做网络探测。调用 `bridge_connect(request_id)` 后保留返回的 `connection_id`，使用 `bridge_connection_status(connection_id)` 读取实际连接状态；只有两个软件的真实健康检查均通过，才可报告 `CONNECTED`。启动就绪等待最多 60 秒，连接有效期最多 120 秒，期限取两个宿主签名启动时间加 120 秒的较早值。

同一 `request_id` 重试、查询状态和重新建立 MCP 传输都不续期、不重新启动宿主；到期或失败不自动重启。需要在已授权任务内重新连接时，agent 显式用新的 `request_id` 调用 `bridge_connect`。任务结束调用 `bridge_disconnect(connection_id)`，只停止该连接自有宿主。MCP 关闭本身不结束后台连接；未显式断开时按已有宿主 lease 到期结束。状态和私有连接文件位于默认 `~/.local/share/bridge-vfx/connections/`，连接工具仅接收请求或连接 ID，不接受路径、端口及凭据。

后台连接不改变既有工程登记、原 GUI 或显式 GraphMCP 配置。已有工程仍按下方原任务 ID 继续，入口就绪、后台连通、工程执行、视觉和生产验收分别判断。

## 安装、工程选择与继续

构建输出同时包含ZIP、外部摘要清单和同源本地marketplace。使用本机官方Codex插件管理器：

```sh
codex plugin marketplace add /absolute/release/marketplace --json
codex plugin add bridge-vfx@bridge-local --json
codex plugin list --marketplace bridge-local --json
```

升级时使用新发行的独立 marketplace 身份，通过官方管理器并列安装。先用官方配置 API 将旧 Bridge selector 的 `enabled` 设为 `false`，再安装新 selector；配置写入使用当前版本号，保留其它字段。不要卸载旧版本或移动旧 cache：历史工程可能仍依赖其原路径与字节，同身份重复安装也可能清理旧版本。新默认消费者应只启用新版 Bridge，并用 `bridge_health.runtime_module` 核对实际安装路径。已加载的旧聊天保持原消费者；新启用状态由新消费者读取。

宿主加载的解释器必须是Python3.11或更高版本。构建可显式指定`--python-command python3.11`；实际版本和导入位置由`bridge_health`返回。不以内存测试或开发仓库导入代替安装后的实际消费者检查。

工程由操作者明确登记到包外私有目录，0.4.13起默认`~/.local/share/bridge-vfx/projects-v3.json`；旧`projects-v2.json`及`projects.json`保留供已加载旧插件使用：

```sh
python3.11 /absolute/release/marketplace/plugins/bridge-vfx/scripts/bridge_mcp.py register-project --project-id my-project --label MyProject --preparation /absolute/creative-preparation.json
```

迁移旧登记时，在同一登记锁内将原条目逐字段复制到新版登记，不改写原文件；已有同名不同条目应报冲突。只有来源真实、准备身份完整的已有工程才可登记；不扫描磁盘或自动挑选最新HIP。自选`--projects`目录需要同时为serve配置同一路径；正常安装建议沿默认状态目录。已有显式`connection.json`继续使用下方原GraphMCP配置路线；默认无配置时提供以下入口工具：

1. `bridge_health`：读取插件、解释器和登记状态，空目录也可用；不检查 DCC 连接。
2. `bridge_projects`：列出已登记的稳定工程ID。
3. `bridge_select_project`：为本连接明确选择工程，返回实际task身份；不打开或重建DCC场景。
4. `bridge_current_project`：读本连接选择，其他连接不会改变它。
5. `bridge_tasks`：列当前工程的原任务ID；目录状态不代表已通过正式结果验证。
6. `bridge_continue_task`：按同一project_id和operation_id继续查询；已完成创作任务返回原正式HIP、NK、EXR及预览，运行中观察原任务，失败/未知返回阻断及安全错误码，不新建job或重放。

已完成 RectLight 软箱的两版原结果均可按原 ID 读取；历史版明确标记不可作为新执行输入。其观看与接收状态保存在消费者私有目录，不写回原任务。

另有 `bridge_connect(request_id)`、`bridge_connection_status(connection_id)`、`bridge_disconnect(connection_id)` 三个后台连接工具，以及既有几何工程的 catalog/media/observe/propose/execute/cancel 工具；以实际 tools/list 为准。

断开重连后，重新明确选择工程，再传同一原任务ID。消费者的结果接收状态与执行状态分开，前者写本入口私有目录，原任务、签名、账本、工程和历史结果保持原位置。图任务观察使用只读数据库连接和既有状态投影，不装配执行器或迁移RUNNING状态；需要原bound宿主观察、而缺少只读事实的类型明确阻断。该入口不承诺新增任意DCC中断自动重跑。完成产物复核读取原签名记账和可信停止事实，并核对原全局、角色及阶段限额；不把工程目录后来增长的占用写回旧执行账。新执行仍遵守实时预算检查。

模型、账户、权限、会话历史继续由宿主管理。本文说明正式接口；本机实测版本、官方安装与消费者结果见当轮交付报告，GUI点击与API验收分别记录。

几何查询的 `state:COMPLETE` 表示技术交付完成。`goal_status` 单独返回 `PASS`、`FAIL` 或 `UNKNOWN`，`goal_evaluation` 保留已验证的几何检查和测量；未携带该评估的旧接收回执返回 `UNKNOWN`，不能从 COMPLETE 推断目标通过。人工视觉接收另行判断。新生成的创作与官方对照PNG按EXR行坐标保持方向；历史PNG及其原摘要不重写，曝光仍沿原固定显示配置。

## 从现有工程创建独立任务

常规入口支持 `bridge_create_task(request_id, source_project_id, source_operation_id, goal)`。先明确选择源工程并列出已完成操作，再传选定的原 operation ID；不猜最新文件。首个模板 `geometry_from_existing_v1` 接受已接收的几何工程，保留有限模型与固定渲染rig；不代表任意HIP或所有领域均可新建。

创建返回新的project_id和task_id。选择新工程后可查看来源模型/参考图、提交观察和新的model_graph提案。新任务从revision 0、空作业和空会计开始；旧HIP、NK、EXR、校准保留原位，只为现有验证要求复制小配置与PNG字节。相同request同参数返回同一任务，冲突拒绝；未知创建状态按原request检查，不另起ID。

新任务类型固定为 `geometry_task`，通用登记也不能把它降级为旧 `geometry`。创建只完成准备，不能将PREPARED写成作品COMPLETE。源案例的比例、私有评审与固定rig仍是模板边界，新的goal不自动扩大这些约束。

操作者首次配置创建来源（不启动软件、不授予原生执行）：

```sh
python3.11 /absolute/plugin/scripts/bridge_mcp.py configure-task-creation --source-project geometry-gate --instruction 'User authorizes independent task creation and planning only; no native execution.'
```

原生执行默认关闭。用户另行批准具体新任务执行后，操作者用CLI签发绑定task/preparation/runtime/profile的许可，沿已有执行核心工作：

```sh
python3.11 /absolute/plugin/scripts/bridge_mcp.py authorize-created-task --project-id CREATED_PROJECT_ID --instruction 'Exact user instruction authorizing this task native execution within its fixed profile.'
```

该模板内层上限固定为14次Native启动、1800秒、两个版本。不能把更低的声明额度当成执行器已经实现的限制；如用户要求更小额度，先落实相应执行限制后再签发。该CLI不重置已用会计或派发次数。创建与执行许可由包外私有签名记录管理，MCP不接受任意路径、worker、权限或预算参数。

## 为独立任务绑定有限模板

操作者可在 `configure-task-creation` 时增加 `--template /absolute/task-template.json`。该选择随创建策略签名固定；创建仍不签发原生执行许可，旧任务及其策略按原版本验签。模型继续使用同一套创建、观察、提案和执行工具，不能从MCP修改模板路径、私有评估或预算。

当前模板schema为 `bridge.geometry-task-template/1`、profile为 `table_geometry_v1`。必需字段是 `public_brief`、`feedback`、`criteria`、`media`、`viewing_exposure_stops`。criteria为 `bridge.table-geometry-test-criteria/1` 文件的FileRecord；media精确包含reference_front/reference_perspective两份PNG的FileRecord。模板及评估文档各最多64KiB，PNG各最多2MiB；未知profile、字段、重复JSON键、链接、非有限曝光或摘要改变均拒绝。JSON只从已核验字节解析。

模板将参考、公开需求和评估一起冻结到新任务，目录的 `goal_contract` 明确其评估范围；自由goal文字只描述计划，不会重新解释私有条件。桌体评估从实际闭合点面重算五个方体，检查桌面、四腿、接地、接合、内缩、对称及反馈尺寸变化。视觉验收保持独立。

观看曝光仅用于该新任务的PNG显示派生，单独记录选择来源；场景rig、线性EXR及原工程不变。现有两版和14次/1800秒/1GiB上限保持；不同模板的创建策略应使用独立受控登记目录，不能覆盖已签策略或迁移旧执行权。

新macOS桌体范围在来源没有明确采集策略时，冻结既有 `sample_header_v1` 与系统sample/vmmap文件摘要。来源已有明确策略则保留；旧范围、旧票据及其已封闭状态不改写。此选择不增加观察整体截止、Native次数或自动重试额度。

## 两版后的有限反馈续接

同一geometry/geometry_task在两版已接收后仍可查看当前目录、取回当前 `preview_N` 与 `local_N` 并提交观察，使用 `base_revision=N` 提交有限 `edits`。补充提案不启动DCC，原两版状态、grant、票据与失败保持原件。

用户授权具体反馈后，操作者签发精确单次许可：

```sh
python3.11 /absolute/plugin/scripts/bridge_mcp.py authorize-feedback --project-id PROJECT_ID --plan-id SAVED_PLAN_ID --request-id STABLE_EXECUTION_REQUEST --instruction 'Exact user instruction and this bounded feedback scope.'
```

随后模型仍调用正常 `bridge_execute`，参数必须与许可中plan/request完全一致。每份补充许可拥有独立执行根、新密钥和账本：最多5次启动（Houdini2、husk1、Nuke保存1、Nuke冷渲染1）、900秒、512MiB、重操作并发1、自动重派0；没有GraphRun或alpha准入。worker独立重验确定operation ID及持久派发INTENT。同一request只取原操作，UNKNOWN不自动重派，换ID不扩大许可。

执行从最新已接收父版本HIP及反馈历史继续，原任务数据库用只读SQLite backup复制；目标几何对照原始首版，公开revision与本次独立产物账本version分别记录。签名补充许可绑定parent/baseline原结果与接收回执、旧scope签名停止前缀、原grant、当前runtime、具体plan/request；新许可不迁移旧执行权。第三版及以后接收在旁路feedback-state登记，对外catalog/tasks/continue同一project可见，不改写原geometry-state的两版历史。

仅在精确监督器启动前导入失败、没有child started/stopped回执且控制/执行owner身份确认停止时，操作者可显式指定 `--supersede-operation OLD_OPERATION_ID` 为新plan/request准备替换许可。旧票据保持未确认，签名superseded记录明确不宣称原生停止；该入口不适用于正在运行、身份unknown、已产生结果或其它故障，也不是自动重试。

以上配置动作不可当作真实执行验收；创建及提案可在零DCC下完成，实际渲染完成仍需其原生结果和产物回执。

## 格式与依赖

使用官方当前推荐的根 `plugin.json`、`mcp.json` 和 `skills/<name>/SKILL.md`，声明 portable Agent Plugins 1.0.0 schema。官方说明见 [Build plugins](https://developers.openai.com/plugins/build/plugins)。本入口提供本地marketplace，不涉及公开目录提交所需的HTTPS MCP endpoint。`.codex-plugin/plugin.json` 是官方兼容格式，但本包使用推荐布局。

本机 Codex 二进制可读校验消息确认：stdio command 可用裸 executable，cwd 可用 `${PLUGIN_ROOT}`。因此默认 `python -I -B ./scripts/bridge_mcp.py serve`，cwd 为 `${PLUGIN_ROOT}`。这是本机静态兼容性检查，不是实际 Codex 安装或启动证据。宿主需要 PATH 上的 Python 3.11+；构建可用 `--python-command python3`。不内嵌解释器，不新增第三方运行依赖。Python 标准库及现有四个 Bridge 包的 src 路径由 wrapper 显式加载，不依赖开发仓库或 PYTHONPATH。

通用 MCP 的 command、args、cwd 字段依据 [Codex MCP](https://developers.openai.com/codex/mcp)。若宿主尚未支持当前 Plugin 布局，可使用 configure 输出的通用 MCP JSON，将其转录到宿主对应配置；不要把通用 JSON 当成 Codex config.toml。Codex 对应 `[mcp_servers.bridge-graph]`，command/args/cwd 值相同。安装位置及重启由主线调度，不在构建工具内自动写用户配置。

## 构建和校验

在仓库根执行一次：

```powershell
.venv/Scripts/python.exe -B -X utf8 tools/build_agent_plugin.py 0.1.0 --output outputs/agent-plugin-20261004/candidate-v0.1.0
```

输出一个平铺 ZIP 和外部 `release-manifest.json`。构建复用 `build_release` 的发布布局、复制、POSIX 路径排序、文件摘要和 ZIP 字节校验。四包仅在 `runtime/packages` 各有一份，宿主插件在 `runtime/plugins`，原 Skill references 按需复制；不复制 generated controller-entry、不携带私有上下文或运行密钥。静态原生 metadata 延续原发布工具的 provenance 例外，必须标记 `native_execution:false`，不当作本机原始 HDA 验真。

路径校验拒绝 traversal、反斜杠逻辑路径、链接/reparse、ZIP 大小写或 Unicode 别名、非普通文件与未登记成员。解包后启动会校验每个登记文件及目录，并拒绝未登记源码、模块影子、大小写别名和其他额外文件。唯一可新增文件是根 `connection.json`；外部配置无需复制进包，不删除外部配置。内部 manifest 是字节完整性清单，不是发行签名；攻击者若同时替换全部字节和清单，需由外部可信 ZIP SHA 阻止。下载 ZIP 应先用可信外部清单调用 `build_agent_plugin.validate_archive`，再解包。

## 显式配置

显式GraphMCP配置缺失准备图时拒绝；默认空配置启动提供上方工程入口。`connection.example.json` 仅示例，不视作有效配置。使用现有 `runtime/tools/prepare_workbuddy_graph.py` 的 `prepare_graph(destination, app=None, execution_profile=False)` 可生成纯软件诊断图；这一步不启动 WorkBuddy 或 DCC。它会生成每次运行所需的隔离源码快照，与安装中的单份 runtime 不同，不把历史快照混入发行包。

在解包目录执行，下列路径由操作者替换为自己的绝对路径：

```powershell
python -I -B ./scripts/bridge_mcp.py configure --prepared-run /absolute/run/control/run.json --scheduler-root /absolute/scheduler --output /absolute/private-config/connection.json
python -I -B ./scripts/bridge_mcp.py serve --config /absolute/private-config/connection.json
```

Windows 使用本机绝对路径。configure 验证后以现有 private-directory/atomic-write 写入一个新配置，并输出通用 MCP 配置；不会覆盖旧配置或修改用户 MCP 注册。Plugin 自动启动默认读已安装根 `connection.json`；可在最终安装目录显式 configure 到该文件，或用通用 MCP 注册外部 `--config`。不要在构建模板中填入个人路径。默认 backend 为 `diagnostic`；health、tools/list 和 graph_catalog 使用真实 MCP/core，但不授权 DCC dispatch。`production` 必须有准备图中明确的 production_host 和 production_nuke 配置；缺失直接拒绝。有效 production 启动可能进入真实宿主生命周期，只能在另行获具体授权后由主线运行。

## 私有上下文边界

配置可选 `private_context` 对象，固定 `root`、`project_id`、`documents`；documents 是 `相对POSIX JSON路径 -> SHA256` 的有限映射。由操作者使用 configure 的 `--context-root`、`--project-id`、`--context-documents` 三项一起设置，最后一项指向仅含映射的外部 JSON。也可显式提供同结构外部启动配置。查询不接受 root、project_id、documents 或任意文件路径。

`private_context_query` 仅接受 query、domain、version、limit、max_bytes、read_budget。上限为 4 条、16 KiB 返回、256 KiB 读取；使用核心的真实安全校验与预算。无配置返回 `status:not_configured`、空 matches，不实例化 reader、不读取私有文档。错误只返回 `PrivateContextError.code`；不把内容、路径或查询写入 GraphMCP 审计事件。结果保留 `content_role:untrusted_data`、来源、引用和内容 SHA，不升级为技术事实或执行权限。

## 最小无 DCC 验证

```powershell
.venv/Scripts/python.exe -B -X utf8 tools/run_logged.py --log-dir outputs/agent-plugin-20261004/logs --name agent-plugin-unit -- .venv/Scripts/python.exe -B -X utf8 outputs/windows-followup-20261004/run_selected_tests.py test_agent_plugin
```

测试会在含 outputs 的实际构建路径打包、校验并解包到包含空格和中文的临时清洁目录，从解包 runtime 加载既有准备工具及真实 MCP adapter，调用 initialize/tools/list/health/graph_catalog/private_context_query。传输在内存中执行；禁止 subprocess 和网络 socket，不启动真实宿主。还覆盖空包、外部预加载核心模块、未授权图在副作用前拒绝和上下文日期错误后的会话继续。独立进程 stdio 实跑另见 outputs/windows-followup-20261004/validation-report.md；Codex 平台 UI 安装、macOS、真实 Houdini/Nuke/HY3、模型与视觉验收均为 `not_run`，不能由单元或手工 stdio 结果替代。
