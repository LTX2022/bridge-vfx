# H21 工程闭环受控准备

2026-10-25接续：当前软件候选为 [prepared-02](../outputs/hip-hotpath-20261025-prepared-02/)，source SHA-256 `ca635d07a487a70d3ed3ef6fe2710dbc5a897518ca5caf5012e64fe3878d1c00`，保持 `PREPARED_NOT_AUTHORIZED`、未授权、零启动；冻结 review 的证据一致性正在修正。当前先取得真实 H21 HIP 建图、保存和新进程冷重开证据，之后推进主渲染、产物登记与 Nuke 消费。工程闭环采用 `controlled_output_v1`，内部 writer 事实保留 `NOT_OBSERVED`，不作为该受控层的前置条件；严格原始回执与长期验收要求保留。具体接续见[当前主计划](BRIDGE_CONTINUATION_PLAN_20261025.md)。真实 HIP、性能和完整工程闭环仍未通过。以下保留18/19及更早轮次的历史结果和完整八启动工程合同，不能据旧候选或旧授权执行当前专项。

历史[18真实工程验收](H21_LIVE_18_RESULT_20261023.md)：真实 alpha 校准通过，41 个构造操作完成；领域初始化将锁定 HDA 内部节点计入显式图而失败。三处节点精确类型修复已真实生效。3/8 启动均可信停止，78.699 秒，范围封闭且零重试；HIP、NK、主场景 EXR 未生成。 HDA 边界与原生类别的最小修复、必要验证及两位独立验收完成；当时19 已冻结，保持未授权、零启动，修后真实未重验。

此前[16真实工程验收](H21_LIVE_16_RESULT_20261023.md)：真实 alpha 校准与五个 EXR 数值复核通过；正式建图因预期 `light` 与实际 `light::2.0` 不一致而未完成。3/8 次启动均可信停止，32.799 秒，零重试；16 已失败封闭，HIP、NK、主场景 EXR 未生成。精确类型创建的最小修复、必要验证及两位独立验收完成，17 已冻结且保持未授权、零启动；修后真实工程尚未重验。

此前[14真实验收与15入口修复](H21_LIVE_14_RESULT_20261023.md)：14 首次 alpha-husk 因 prerender 缺少 `__file__` 失败，使用 1 次启动；修复后的 15 review 经用户另行授权，生成了本轮 16 独立真实范围。历史原件与消耗分别保留。

此前[原生就绪同步与采集失败早停](NATIVE_READINESS_STOP_REPAIR_20261023.md)：原生就绪同步与采集失败早停两项软件修复及两位独立验收已完成：双Python核心、普通进程真实macOS采集及失败停止、单次无映像模型八阶段软件链通过。13候选为 PREPARED_NOT_AUTHORIZED，0启动/0票据，八次启动预算不变；该软件修复轮未重跑真实宿主，真实工程闭环与M1仍未通过。

此前[12真实工程验收结果](H21_LIVE_12_RESULT_20261023.md)为 FAIL：按11 review激活12后，仅1/8次alpha husk启动，产生1份实际校准EXR，最终整组可信停止、无重试；writer采集遇到原生启动未就绪的stderr而被拒绝，另发现记录采集错误后未立即取消当前作业。HIP/NK/主场景渲染与Nuke消费未到达。12已失败封闭，不续跑；工程闭环、M1、HY3及视觉状态不提升。

本次范围为H21.0.631＋Nuke17.0v1、ACEScg独立工程。[09真实验收](H21_LIVE_09_RESULT_20261023.md)已获明确授权并运行两个校准作业，因husk身份绑定缺失及后续结构校验错误停止；已生成RGBA校准EXR，未生成HIP/NK或主渲染。09失败关闭，不续跑。以下保留工程合同，08软件通过不替代本次真实结果。

预算为每操作 120 秒、全程 600 秒、最多 8 次 DCC 启动、输出与日志合计 512 MiB、同时最多一个重操作、失败不自动重试。所有工程与输出位于冻结的新目录；用户已确认启动上限为8。-06本轮明确授权已执行第一步并失败关闭；任何后续新范围仍需具体授权。

范围包含：H21 常量发光透明度标板；Nuke 原始像素采样与黑白背景合成；正式 sphere_ground_v2 单帧 128×128 受控输出；登记产物供 Nuke 消费与写出读回。校准通过只适用于完全相同的宿主版本、插件 build 与输出路线摘要。

## 色彩

项目选择为 `engineering-closure-h21-20261020`、revision 1、`ACEScg`、`human_project_selection`。安装的 Houdini `packages/ocio/houdini-config-v2.1.0_aces-v1.3_ocio-v2.3.ocio` 显式声明 `ACEScg`，其原件身份已冻结。真实阶段仍需原生 Houdini/Nuke 菜单与实际设置读回；静态 token 存在不替代原生应用结果。Nuke 未通过可见配置原件确认 token，保持原生读回要求。

## alpha 校准合同

固定标板为 128×128，在 `(16,64)`、`(64,64)`、`(112,64)` 分别采样 opacity `0`、`0.5`、`1`。常量发光颜色为 `(0.8,0.8,0.8)`，base/specular 为 0，emission 为 1。`docs/native-basis/hda-interface-capture.json` 的 H21 `Vop/mtlxstandard_surface` 明确定义这些 Float/Color tuple 参数；`alpha_calibration.calibration_material_recipe` 给出精确写入值，`validate_material_readback` 检查原生类型、模板、可写性与最终值，不执行写入或 cook。

08保留的alpha RenderVar保留`dataType=color4f`，husk format采用同版Karma四分量精度`color4h`。09已生成真实HALF RGBA并取得符合预期的数值，但身份校准失败，不能标原生alpha专项通过；原容差与RGBA合同不变。

Karma RGB/alpha 绝对误差为 0.02；Nuke 合成误差为 1e-4。必须存在非平凡 fractional alpha，并能唯一分辨 associated 与 straight。Nuke 在原生 Read 中采样源标板，按测得的 association 进行必要 Premult，经 Constant/Merge2 在黑白背景合成，Write EXR 后重新 Read 与采样。另用 `(0.125,0.0625,0.25,0)` 加性样本验证零 alpha 的 RGB 保留。不得将任意真实图像的 alpha=0 推断为 RGB=0。

固定 Nuke 观察器为 `packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py`，由 Nuke 原生脚本入口调用：`--observe-native --chart <校准原始 EXR> --output-root <尚不存在的独立输出目录> --project-colorspace ACEScg`。这是专用合成标板入口，不开放通用未登记渲染图消费；它不登记正式产物、不授予校准 PASS。

## 原始认证绑定

`validate_alpha_calibration(binding, *, expected_version, expected_plugin_build, expected_route_sha256, evidence_source)` 返回测得的 `associated`、原始文件摘要和证据来源。普通布尔值、调用方 PASS 与无签名数值不构成校准依据。

`binding` 包含 supervisor `directory`、`identity`、固定 `terminal_sha256`。原始 `alpha-calibration` HMAC event 绑定原始 signed started/stopped 摘要、版本、build、路线、观察器源码摘要及 `houdini_raw`/`nuke_composite` 两份有大小和 SHA-256 的 JSON 原件。每次验证重新认证签名并重新哈希当前文件；进程成功必须由 `execution_returncode` 确认。

真实证据还包含 `native_operations.houdini` 与 `.nuke`，各绑定其原始 supervisor、identity 和 `output_sha256`。各自的 signed `alpha-output` event 必须绑定：固定源码记录、原始 started/stopped 摘要、精确 command、路线、build 与 `real_host` 来源。原始 started 必须含 supervisor 采集的 `writer_process_binding`，包括原生 executable 与同 PID 的 OS image；验证时重验其结构和当前 executable 字节。

H21 固定源码为 `tools/prepare_native_alpha_scene.py`；event 还需 `scene` 与 `chart` 原件记录，scene 路径必须在真实命令中。Nuke event 绑定上述同一 chart、两份观察 JSON 与四份黑白/加性 EXR 原件，命令必须包含固定 Nuke 观察器源码路径。四份图像都重新哈希。完整合同所需原始操作或文件缺失时拒绝，不用标志位代替。

## 当前验收边界

软件已具备数值判定、精确材料配方/读回检查、原始签名与文件绑定验证、可调用原生 Nuke 观察器及具体执行范围。校准测试使用自身签名的 Python 数值夹具，明确标为 `software_test`，不能证明原生接口或视觉输出。-06第一步原生husk已执行，但EXR通道失败，校准未通过；Nuke观察及后续工程阶段为NOT_RUN。后续新范围仍须产生并认证两组完整原始操作与输出，不能复用本次失败产物作为校准依据。

## 正式流程与预算预检

`tools/run_alpha_calibration.py` 默认只读预检；执行需要精确范围与运行绑定两个 SHA。匹配公开 SHA 不构成真实执行授权：还必须存在经原始 review 与激活回执认证的 `execution_authorized=true`、`status=AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION` 及可信本地终端授权来源，并在共享执行锁内复验。准备候选 -05 保持 `PREPARED_NOT_AUTHORIZED`、`execution_authorized=false`，该工具不提供自动授权开关。它负责校准阶段；完整编排由 `run_controlled_engineering.py` 实现。-06已获本轮明确授权并执行第一步后失败关闭；不得复用该范围，新范围执行需另行具体授权。

校准 runner 使用 `dcc_task_runtime.native_scope.NativeScope` 的统一状态 `native-scope-state.json`。`ScopeBudget` 仅提供该状态的只读工具视图；实际启动通过 `owned_process.launch` 的 `resource_budget.native_scope` 与角色 `alpha-husk`／`alpha-nuke` 准入，由原监督器认证停止并结束票据。runner 不另建预算账本，也不重复准入或结束票据。进程成功后的数值或文件校验失败通过同一 `NativeScope.fail` 封闭范围，未知停止继续保留票据。

正式生成器将校准准备、校准执行及独立验证工具一并复制到项目 `control/snapshot/tools/`。后续必须从该冻结快照执行校准，原始回执绑定其中的生成器与观察器路径；不得以开发目录生成的回执冒充冻结项目来源。宿主退出后的验证/补登记使用该快照中的 `verify_controlled_output.py`，不会调用宿主启动或重连。

现有正式流程的最少启动清单如下：

| 阶段 | DCC 启动次数 | 正式入口 |
|---|---:|---|
| alpha 标板 | 1 husk | `run_alpha_calibration.py` |
| alpha 合成观察 | 1 Nuke | 同上固定观察器 |
| 正式建图 | 1 hython | `graph_jobs.py` 建图 worker，控制宿主尚未启动 |
| 图交接及 HIP 保存 | 1 hython | `workbuddy_assembly.py` → 单 H 按需启动 |
| 保存后新实例重开 HIP | 1 hython | 停止原任务宿主后重新启动 |
| Karma 渲染 | 1 husk 后代 | USD Render ROP `node.render` |
| NK 首存 | 1 Nuke | 可信 helper → 单 N 按需启动 |
| 冷加载 NK 并执行 | 1 Nuke | 固定 owned render worker |
| 合计 | **8** | 不含重试 |

新范围的启动上限为 8，完整清单恰好使用 8 次，不包含重试。统一预算入口已接入 `production_hosts`、`GraphJobService`、Nuke owned worker 及 husk 后代；空闲控制宿主不占重操作槽，仍计入启动次数和累计时间。预检要求 8 个真实启动项的精确角色、host、heavy、重开宿主父子关系，以及全部入口源码哈希、部署配置和正式 driver 计划。完整八阶段软件夹具已通过，-05 历史只读预检为 PREPARED；这不授予原生执行权限。控制宿主不再从初始化空耗寿命，每个子渲染预算按签名剩余时间收紧并预留停止时间。

05历史运行绑定见 `outputs/engineering-closure-20261020-h21-05/runtime-bindings.json`，包含正式 writer 命令、来源指纹和八项启动计划；预检通过不代表真实工程链通过，结果与边界见 [本轮报告](ALPHA_FINAL_CHAIN_20261020.md)。以下 -03 原件沿革与认证规则保留。新范围 ID 为 `engineering-closure-20261020-h21-03`，输出目录与该 ID 对应。其 `supersedes` 绑定范围 `engineering-closure-20261020-h21-02` 的 SHA-256 `af17d2817af2a0d2fdb845cbdc4758a128b7b94fad6127f62b72d9f5ca842c95`；`-01` 与 `-02` 的原始 `scope.json` 字节保留，不能用于新认证账本范围的执行。

## 认证预算原件

`-03` 范围的 `accounting` 仅冻结私有 key 的本机路径和 SHA-256。首次 prepare 生成独立 32 字节 key，写定范围后，由 `NativeScope.initialize` 一次创建 key、state、journal 和独立 anchor；key 权限为 0600，内容不进入范围 JSON、日志、交付包或 Git。重复 prepare 复核同一范围原字节及认证 snapshot，不生成新 key 或新摘要。任一认证原件缺失、回滚或不一致均拒绝，不按空预算继续，也不自动补建。
