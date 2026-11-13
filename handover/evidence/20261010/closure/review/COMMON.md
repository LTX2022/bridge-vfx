# COMMON 独立只读复核

**当前指定范围未发现未闭合的确定 P1/P2。两项审查发现的 P2（空 recipe 标记降级、pending 缺 fresh 绑定）已按最新源码关闭。** 这只接收 primitive 创建及部分观察的安全边界，不授予完整 geometry/full semantic、Crowd producer closure 或全 16 域 M1 PASS。

2026-10-09，Asia/Shanghai；原范围读取约 18:17–18:25，stash / SAVE adapter 补审包含最后 node.children/node.info 白名单和 pending channel 增量。审查者未参与对应实现。已读根 AGENTS.md、README.md、handover/STATUS.md、handover/REMAINING.md、handover/NEXT_AGENT.md；指定目录未发现更深 AGENTS.md。未运行测试、Git、真实 DCC、模型、仿真、缓存或渲染；唯一写入为本报告。仓库相对路径均相对 C:/Users/32200/Desktop/Agent/skill/Bridge。

## 正式编码、登记重试及 Nuke 绑定

`packages/vfx-pipeline/src/vfx_pipeline/domain_readiness.py:182` 的 _formal_output_encoding 要求完成 metadata AVAILABLE、请求及 producer 帧都是严格 int、无重复且顺序/集合完全一致、metadata 键精确对应每帧。每帧 colorspace 必须是非空字符串，premultiplied 必须是严格 bool，并要求所有帧编码一致；拒绝 bool-as-int、整数 alpha、缺帧和重复帧，没有颜色/alpha 默认值。

`:208` 的 _formal_registration_retry 最多调用两次。SQLite 错误必须带严格整数 sqlite_errorcode，按低 8 位仅重试真实 BUSY/LOCKED；非 busy、无合法 code 和语义拒绝直接上抛。保留 OSError 的一次重试，不把最终失败转成成功。正式 render submit/query 和 producer 核对在 `:539` 之后完成，重试闭包仅在 `:557` 包含同一 register_render_artifact：artifact ID、class、pattern、frames、colorspace、premultiplied、operation ID 均不变，attempt 只记 stage provenance。闭包没有 render/build/save，因此 busy 重试不重渲染。

旁读 `workbuddy_graph_mcp.py:834`：重复登记须核对已有请求、当前 producer/source、当前依赖与文件，不能借重试重用变更内容。`domain_readiness.py:572` 把上述 producer 编码和消费后的 artifact binding 传给 Nuke，没有 hardcoded linear/False；此前核对 owner、operation、pattern、帧与 receipt SHA，之后核对 Read 路径、artifact、owner、帧与连接。生产 `workbuddy_assembly.py:1548` 还要求严格帧/alpha 类型、输入编码一致，以及 Read/Write 的实际颜色/路径/连接读回。本次只核对调用契约，不是完整 Nuke alpha 处理或输出验收。

缺 metadata 抛出 FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED，保留具体 missing facts；run_case 转成 BLOCKED 并保留 context。即使登记/绑定通过，完整领域语义/生命周期仍有 BLOCKED gate。

`test_formal_output_registration.py` 当前 6 项覆盖正常/缺失/不一致编码、bool-as-int/重复、真实 SQLite 锁释放后成功、非 busy/语义拒绝和持续 busy 两次上限。busy 用例真实打开两个 connection，BEGIN IMMEDIATE 后第一次 INSERT 失败，释放锁后只登记同一完成操作，最终一行；它不替代完整 producer 实跑。

## 最新颜色字段与 raw filter

已直接只读核对本机两版 `houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda` 原件，无宿主启动：

| 属性 | H21.0.631 行号 | H22.0.429 行号 | 类型 |
|---|---:|---:|---|
| driver:parameters:husk:source_colorspace | 107 | 154 | string |
| driver:parameters:husk:output_colorspace | 102 | 147 | string |
| driver:parameters:aov:husk:source_colorspace | 57 | 80 | string |
| 已有 driver:parameters:aov:husk:output_colorspace | 52 | 73 | string |

当前 `render_color_facts.py:23`、`:24`、`:31` 的三项 expected_type 都为 string。原生 GetName/GetTypeName/HasAuthoredValueOpinion/Get(frame) 路径未被替换，token 错型形成精确 property path 的 ATTRIBUTE_TYPE_UNSUPPORTED，不写 value。新 token 拒绝测试覆盖 Product/Var source/output 四种替换；原两项 Product 测试覆盖逐帧独立读取及缺失字段，不继承 AOV 默认值。空值保留 gap，未把 schema fallback 空串解析成有效转换。

`karma:plane:filter` 仍为 None，表示没有原件支持的 expected_type 约束。复用有界 raw type/value 序列化：支持的 scalar 保留，若 native type 明确是支持的 scalar array，也沿用原有有界 array 路径；未知/非法值形成 gap。没有解析 JSON filter 效果、发明默认 filter、转换关系目标或完成 metadata。None 不能称原生类型已验证；本次没有验收 filter 执行效果。

collector 仍保留 OUTPUT_PATH/OCIO/RUNTIME_OVERRIDES/IMAGE_FILTER_EXECUTION/ALPHA 等未决项；`houdini_bridge/client.py:291` 仍输出 BLOCKED_MISSING_NATIVE_FACTS 与空完成 metadata。raw USD、EXR 通道和软件 stdout 都不能替代有效颜色、关联 alpha 或实际 husk/filter 事实。H22 Product 层 filter 及完整执行链不属于本次小增量的已接收范围。

## 进程观察旁路

`tests/helpers/graph_job_process_fixture.py:91` 原样调用 shipped owned_process.supervise，只在 POSIX Popen / WindowsJobProcess 原生进程边界加继承观察。ObservedChild.wait 先执行 super().wait，核对真实 signed started 的 PID/attempt，再写 software-child-wait.json。Windows wait 经 WaitForSingleObject/GetExitCodeProcess 观察真实 child。新增路径没有手造 producer、completion、started 或 stopped；该观察文件不是签名停止回执。

SoftwareChildWaitHandle 校验 PID、identity、observer 标签及严格整数 exit_code，仅描述直接 child wait，保留原停止传输。容量释放仍由 `graph_jobs.py:831` 决定：POSIX 捕获 pid=pgid=sid 后，父退出仍须 owned_group_status==stopped；活跃/未知同组后代不能释放容量。Windows descendant 使用原监督句柄，JobObject active count 为 0 才签发 stopped；新增 Windows 正常 wait 包装也保留此顺序。

POSIX 同组后代活跃时原 supervisor 返回 2 且无 stopped；测试保留父 0、监督器 2、无 stopped、PGID/SID、保槽、后代自行退出后恢复与仅创建一次。它依赖原控制端仍持有观察句柄，不能证明控制端同时死亡后的更强恢复；POSIX/macOS 本轮 NOT_RUN。helper 中其他旧 scheduler worker_factory 简单结果不用于这条新增 producer/停止证明，不把整个 helper 概括为无上层夹具。

## 最终 stash 修复的安全判断

**可以让真实 CREATE primitive 证明节点创建，同时明确 Data 未观测。当前修复已满足本次必要的 fresh / host / replay 防线；完整初始化、几何与资产仍必须严格验收。**

以 addon `f320277c...`、测试 `f0bf4035...` 为准：

- `_fx_pending_stash_creations:11985` 按完整 host identity 的 canonical SHA 分组，保留真实 hou.node 对象、runner path、creation operation ID。identity 包含 owner/PID/session/nonce/generation/scene epoch/plugin build，不能由 command 名代替同一 host/attempt。
- 后续 primitive 每次重读 canonical creation 原件并执行现有 completed validator，要求原件 host 完全相同、command 是 node.create/create_batch、created_nodes 包含精确 path 与 Sop/stash。节点删除/对象替换时移除原授权；旧节点、新 nonce、缺失/无效 creation 记录都不能继承。
- 同一调用的新节点只取实际 handler 返回的 path、before_paths 不存在且实际类型为 Sop/stash 的 node 对象。先在当前 before/after 证据中限定集合，完成原件 CAS 写入后才登记到内存集合（`:12181` / `:12183`）；失败创建不产生可继承 fresh 授权。
- fallback contract `:11924` 按每个 node 是否属于集合选择 pending；严格 _fx_capture_scene_contract 仍优先且不吞错误。`:12041` 白名单在五项 construction 命令外，仅新增 node.children/node.info。两者实际 handler `:11620` / `:11624` 读取原生 children/type/path、errors/warnings、inputs/connections，不能登记新的 fresh 节点；仍需同 host 的 completed creation 原件。旧未登记 stash 的查询反例仍拒绝。scene.info/node.parms/cook/save 等未扩入白名单。
- 两个 recipe marker 要求确切 None（`:14080` / `:14081`）。空串/坏 JSON 留在原 strict snapshot 路径。stash channel 有 expression/reference/keys 或已有外部文件时拒绝；stashfile public parm 是否存在单独记录，缺 parm 不填空串。evalAsGeometry 异常记录 evaluated_available=False、data_observation_schema=bridge.pending-stash-data/1、data_state=readback_unavailable 和具体 error；不添加 geometry_contract，不读取 raw.value 补 native 结果，不把 None 猜成真实默认。实际返回非 None 即使是空 Geometry 也拒绝无 recipe 数据；显式成功返回 None 仅以 observed_null / evaluated_available=True 描述原生观察，不添加 geometry_contract，不能充作已初始化或空几何。
- unavailable Data 不加入 parameters 的 evaluated value，仅保留 channel 状态；native_command 的创建事实不等于完整 scene content。full manifest capture、initialized route/agent snapshot、save/reopen 仍默认严格；真实 recipe、Data、内容摘要与 owner 缺失继续拒绝。
- `_fx_scene_has_pending_data:12009` 识别独立 data_observation_schema；`:12073` 在 idempotent 场景判等前检查 prior.after_scene 和当前 before。即使两个 unavailable 错误相同也拒绝重用，不以摘要相同证明 Data 未漂移，不重跑不确定 create。它也保守拒绝 observed_null 的 replay。查询的 before==after 仅核对可序列化部分观察一致，不能证明未观测 Data 相等；facts.proof_scope 保持 native_command，不提升 geometry/full semantic。

**两项 P2 关闭依据：** 空 marker 改为 is None，并为 agent/route 两个空标记保留反例；先前 command-only 的全 root pending 改为上述同 host、真实新建对象及 completed 原件约束。没有参与对应实现。

`common-stash-current.json/log` 已记录 13 tests、0 fail/error/skip、exit 0、source_unchanged=true，addon/test 的 source_before==source_after==本次所读 SHA。覆盖同 host 正常后续 primitive、旧未登记 stash 拒绝、不同 nonce 拒绝、creation 原件缺失拒绝、pending idempotent 拒绝、expression driver 拒绝，新增 children/info 的 partial 查询与旧 stash 查询拒绝，并保留 unavailable/null/non-null/空坏 marker/default/save 等路径。unittest 17.487s、外层 17.766s。本审查仅读取结果，没有运行这些测试。

**Crowd 正式入口仍未关闭。** 已读 after-fresh-queries 原 unittest.log 和两版 trial.json：H21/H22 均 FAIL，预期仍为 SUCCEEDED，实际 RECONCILIATION_REQUIRED / RESULT_EVIDENCE_UNVERIFIED，未改原日志或预期。用户最新精确诊断为 6 COMPLETE + 1 UNKNOWN，stash 创建及 children 已过，下一阻断为 dopimportfield/fields 的底层 default 未捕获；该具体 fields 分类和 journal 计数为用户报告，本次未追加诊断或猜值。原日志仅独立确认失败，不用它替代 fields 的原生语义证明。13 项只验 stash 安全边界，不授 producer closure；真实 Houdini 新 stash 的实际返回/异常仍未由本轮原生运行证明。

用户最后补证：本机两版 HDA 的 DialogScript section SHA 与旧 `17ae72f9...` 一致，fields 明确为 multiparm、没有 default_tokens；Windows HDA 整体原件 SHA 与 Mac 不同，但 section 完全一致。本审查记录该来源说明，未独立读取这批 HDA，不以截短 SHA 代替原件绑定。factory/runtime count 尚未捕获，真实 HOM count 缺口必须保留，不能补 0 或把 non-value 分类当作真实实例数量证明。

## SAVE adapter 追加局部复核

按用户授权，旁读 `tools/readiness_evidence.py:892` 的 _prepared_current_save、调用侧、typed validator、canonical store 和新测试；**request / actual host / canonical store 这三项增量未发现确定 P1/P2。**

现有 typed validator 核对实际 request task/operation/request ID、request SHA、frozen inputs、严格整数 PID/scene epoch、before/after host identity、scene contract SHA、handler result、HIP/snapshot SHA。adapter 再核对原 request path、剥去控制端附加字段后的 summary==原件 result、after_scene 合同==当前 save、已有 graph_hash/root_path 不冲突、native saved path/hash/snapshot 一致。缺 graph_hash/root_path 时使用已由原件 after_scene/当前 graph 核对的上下文，不声称字段曾存在于实际请求。

actual host 来自 persisted record.host_identity，未与 runner 的 process_generation 混同；原 validator 绑定 before/after，该 host.plugin_build 匹配冻结 addon。fresh 公共 task_save 测试另断言 proof host 等于实际软件 transport health 读回；不把它称当前真实宿主 health 或一般停止证明。

canonical 路径为 source manifest 父目录下 houdini-instances/fx_operations/producer-records/sha256(owner)/sha256(operation_id).json，与现有生产 record_path 规则一致。summary store path 必须精确等于该路径；原件严格等于排序规范 UTF-8 JSON 加换行，验证原始 SHA/JSON 内容，并分别核对当前 HIP 与冻结 snapshot 实际字节。上层重摘要、summary-only、复制到其他路径、追加空白均不能替换原件；导出 resolver 映射不取消 canonical owner/op 约束。

调用侧要求当前 owner/graph/version（拒绝 bool）、COMPLETE、feedback dependencies、最新成功 task_save、graph_version/save/controller 同源冻结。当前 source 陈旧时可以保留冻结 SAVE 事实，但 current_source_matches=False、stale errors、save missing_proof 都保留，domain_lifecycle_verified=False。未提升 full semantic/output/recovery/domain PASS。

所读三文件 SHA 匹配 save-adapter/audit.json；targeted-tests.log 是 60 方法、59 通过、1 既有 material 输入缺失 skip、exit 0，不能写成 60 PASS。audit 只绑定该任务文件与日志，不能覆盖随后 addon stash 修复或最终并行 build。没有复跑 60 项，未做完整 resolver/安装审查。

追加只读核对 common-formal-recovery-current：1 项通过、0 fail/error/skip、source_unchanged=true，外层 22.531s。其 addon 绑定 `163c6781...`，早于最后 whitelist 的当前 `f320277c...`，因此不是最后增量的整链 PASS。runner-1791542504687392700/partial-case.json 保留 typed_save_evidence，status=BLOCKED、output_metadata_status=BLOCKED_MISSING_NATIVE_FACTS、formal_domain_lifecycle_verified=False，缺口保留 full_semantic/preview/persisted_output/domain_recovery/nuke_producer，没有 save gap。用户说明 inspect current 已支持 current_task_save；本次未重新执行 inspect，不能把保存证明或单项通过提升为 output/registry 完成。

## 证据边界与后续

| 已读证据 | 结果与绑定 |
|---|---|
| common-registration-after.log/json | 22 项通过；domain_readiness/test SHA 属旧版，不覆盖最新 bool/重复检查 |
| common-encoding-final.json | 6 项通过；当前 encoding/retry 源码与测试匹配 |
| common-product-colors-after.json | 45 项通过；三项 None 的旧版，不覆盖 string 修改 |
| common-color-schema-final.json/log | 46 项通过；当前 collector/test 匹配，含 token 拒绝；非 final integration |
| process/windows-affected-final.json/stderr.log | 8 项通过；helper/test/group/supervisor 源码匹配，仅 Windows；unittest 16.992s 与外层 17.297s 是不同计时 |
| common-stash-channels-after.json/log | 6 项通过；是 fresh 边界修复前版本，不覆盖后来的 fresh/空 marker 改动 |
| common-stash-fresh-boundary.json/log | 11 项通过；此前版本，不覆盖最后 pending schema / 查询白名单 |
| common-stash-current.json/log | 最新 stash 边界 13 项通过；前后 SHA 与所读 addon/test 一致 |
| common-formal-recovery-current.json/log | 正式 c 单项通过；运行中 source 未变，但 addon 早于最后查询白名单 |
| domain-worker/after-fresh-queries/run.json/unittest.log | H21/H22 仍 FAIL，原入口未关闭，未把部分完成当通过；报告不声称全源码冻结 |
| save-adapter/targeted-tests.log/audit.json | 60 方法、59 pass/1 skip；仅 SAVE adapter 及该定向范围 |

addon shared 变化影响 producer scene readback；旧 6/46/8/60 组中的旧 addon 不能验收当前全部调用链。原编码/登记/Nuke 源及 SAVE adapter 核心源补读 hash 未变。源码冻结后最终相关集成由主 agent 统一执行，无需审查者重跑。软件有限证据、最终安装、真实宿主、模型路线、视觉与生产验收分别报告；后五者未由本次验证，全 16 域 M1 未完成。

## 所读源码 SHA-256

完整文件 hash 只绑定所读函数/上下文，不声明整文件均已审查。

结束前已逐项核对表内可访问的源码/证据原件，未发现 SHA 漂移；最终 addon/test SHA 与 common-stash-current 的 before/after 完全一致。共用 integration 此时仍在运行，不在本报告盖 PASS，后续结果和范围由主 agent / docs 单独记录。

| 文件 | SHA-256 |
|---|---|
| packages/vfx-pipeline/src/vfx_pipeline/domain_readiness.py | acb62328bee3fc6c7039dab466cc5f371b8c643663007131b5a453f4cbdaa192 |
| packages/houdini-bridge/src/houdini_bridge/render_color_facts.py | f1df6b7fcde672946130d65d6c9efb658bb5e62c5c68c2273833644e4b4b0e3f |
| tests/unit/test_formal_output_registration.py | 00aaf9657f922dc1fefd4cfa532483f8d283b8936bad4cb8a5cb400d6ea893c2 |
| tests/unit/test_render_color_facts.py | 1187535946e7e557332dbe4966106f9dc546951ff656e9249699be0253ceba78 |
| tests/helpers/graph_job_process_fixture.py | f1c7c1d2aea2237e88560db4bfcea6f9b5dfc587a0cba44bcda04c9229a36f6b |
| tests/unit/test_graph_job_recovery.py | ea9a51f07745bd92b7148445a7e77406455a5b98aeb867e3d2d26d02e98c1401 |
| tests/unit/test_graph_supervised_recovery.py | 33e5f7bf237d3d1d7fce4621ed17b1d94251348db7b34bb8ef3a88ff1a743071 |
| packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py | 745efc103fe7bc4e7ba70d6851cab5cb34feaea3529b3996e585755439aa43e4 |
| packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py | f1e62d47ecc274bd2b75acf827047f2a4cdc2fb62910bb111bc21b033b5fac49 |
| packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py | a1b4f14b23bb4fe6c2e1dcc90263c5f8329db9a71e79da4c6522b0e1a55a010a |
| packages/vfx-pipeline/src/vfx_pipeline/graph_job_evidence.py | 18937a6681aaa728820b48a5de8b02fb996be175581d60e5db08fdc7954f0faa |
| packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py | f5fed29bfabb96531ad965f81156d26fd57c4f6d31d3272b621a6bf0f4f4c893 |
| packages/dcc-task-runtime/src/dcc_task_runtime/windows_process.py | 226f8793f80cc6efaf8837494ff60695ac4a2215bf532c871f7bd99767ed88e3 |
| packages/houdini-bridge/src/houdini_bridge/client.py | c08eedddc6e80ea8f16005971f2267eab2bae6c17259c15e0ac25c68998e337b |
| plugins/houdini/_impl/houdini_bridge_addon.py | f320277c6f1a5b39083019351bf26d452fc25691e2e5e2aadadf28a83aa5ceca |
| packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py | 6bb2cbc2312c5f9af4ee3e291f3779e4f4080ba3144795cf8aaf86355a5445f6 |
| tests/unit/test_intermediate_stash_readback.py | f0bf40354db15315bd34046958f3ee20aee923275ccfc49a18a769448ff24a7f |
| tools/readiness_evidence.py | 012dec73c15d625c9a46f589bea10b3b9644ef9da5406ed74e8dcc62b36ffd42 |
| tests/unit/test_readiness_current_save.py | e971d7149871f83117d7723e6325b138398676c640f9df8e238ec1f39dd9b613 |
| tests/unit/test_readiness_native_command_evidence.py | 102b7ffee0102d08821280f1a6e972efdd0ceb6905f12a7106b5b0b0b302129d |
| packages/houdini-bridge/src/houdini_bridge/operation_receipts.py | 9dee2b182c0ff329343c17a7dc161d5119d986973612afbc759482c2c9ef1448 |
| packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py | 1181a2621144f7ed6096cbe0d9efe39416c2469e79f7722e939c0f102a89d5e7 |
| tests/unit/source_host_fixture.py | 39bbebdc3861f32ae75bbf64f34ab26ec0e241211841c2c5cd17c04cbe9d0c50 |
| tools/native_schema_test_boundary.py | 97efe6358e39fcc58442bd13b8eeb9d049fb3887cf9dbe9bdc5ca4b2ec1a21f6 |

原件与关键证据 hash：

| 文件 | SHA-256 |
|---|---|
| C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda | c17d9c9601cefcfcd4a0e154f8d27051b209dd25ed63ef9544549330a1e2e5ae |
| C:/Program Files/Side Effects Software/Houdini 22.0.429/houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda | f8d861f754ba66b534eb49ac6a8f10af516d8aa7ef302e14e38caa2befcd556d |
| outputs/all-domain-20261009/common-registration-after.log | 53666379fe54e6773480d7c2be78e15d6a92c93024cb9a812776911947278002 |
| outputs/all-domain-20261009/common-encoding-final.json | 3de296fb77caa47f44fd5f96667c7c1a9678ce8bc5db28df576383e3c01b9309 |
| outputs/all-domain-20261009/common-product-colors-after.json | 296e1e5d28bb446d68a7144f29cabbbd125de062e355b49ec1bf132166b8c316 |
| outputs/all-domain-20261009/common-color-schema-final.json | 91ce643ea1c4adafc435743b4f2724475fcf970654d3a5412963c9bcbdddeeb4 |
| outputs/all-domain-20261009/common-stash-fresh-boundary.json | edbec0264f096be429e5655eadc7f96d44397e2a5dd610c0ad3b84dd71465e0b |
| outputs/all-domain-20261009/common-stash-fresh-boundary.log | 0a252ab882e9c8f73f8d978c01778508f59569c360c74b3ec94f3a92857cb9af |
| outputs/all-domain-20261009/common-stash-current.json | 9b6cafc4a9e5e86bb91154c96b403825da94d8a0b45b065e29422b2db590fb7f |
| outputs/all-domain-20261009/common-stash-current.log | 0f87f1e6e7d17781f610d733d6668652176b18e82bf175e070da1bc297e98638 |
| outputs/all-domain-20261009/common-formal-recovery-current.json | 0bee5e70e805f394526e2c200157a19cc7a30ac3a2fb6ce24d3dcee63b40fc44 |
| outputs/all-domain-20261009/common-formal-recovery-current.log | f41803c63d78bb329c4db4be21f5e3315a6c772f009bd204518fe481bde62408 |
| outputs/all-domain-20261009/formal/recovery/runner-1791542504687392700/partial-case.json | dc2e754ac64e2332100b41fc92b1c5db2e52a401b2602e8d1f3a04cc70bc30bf |
| outputs/common-closure-20261009/domain-worker/after-fresh-queries/run.json | 4133c0f60b7420710e33aa534ab9f8c04fe53331863edb6e15ded7f2efeba876 |
| outputs/common-closure-20261009/domain-worker/after-fresh-queries/unittest.log | 8afd93afa9d661d913654419792cb04acbfd7b629883547c30f4325d7c6cf964 |
| outputs/common-closure-20261009/process/windows-affected-final.json | 59dbe8c922b28e738909c1f2cd8f7195c3d8dceb03c14c8d77a3fb442e68c978 |
| outputs/common-closure-20261009/process/windows-affected-final.stderr.log | 468e024b4a60432ce5f5bb794b68c5c52babc32909e834f9ade7f3017679a6d2 |
| outputs/common-closure-20261009/process/process-recovery-report.md | 752d3c9e69d9e5aeb5eebae843f3eceb9abf6384f03c08a5257df9cf65b4c8de |
| outputs/common-closure-20261009/native-output/REPORT.md（所读类型补证版本） | abff24fcec38a538ac0c7343ea2f98adc5b9cbf1d3e3460cc3fe5b13d583c5f9 |
| outputs/common-closure-20261009/domain-worker/after-pending-channel/run.json | 0c75e405d80120ff776eae05818adae230d911453363aea88834d7b1986d5e30 |
| outputs/common-closure-20261009/domain-worker/after-pending-channel/unittest.log | 5eaccdf175981998902f9460b8a62cc86307587b941da2dba06fc9c7519de5b2 |
| outputs/common-closure-20261009/save-adapter/README.md | 03944eef2f907ede0074a7ac6413fb8fcdce62acbfc2f1ecf0b9ba9ac97fc031 |
| outputs/common-closure-20261009/save-adapter/audit.json | 7ebe44c4633df41878c1eac7d78b81c564d7a0e8787e880667d044673a7d7678 |
| outputs/common-closure-20261009/save-adapter/targeted-tests.log | 9974c76278936112b6f980d9738499b15ca14915ea7b9a49ec862e3b76dc356e |
