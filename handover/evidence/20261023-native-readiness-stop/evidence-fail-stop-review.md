# READY13 fail-stop 独立代码与证据评审

结论：固定 fail-stop 候选的主修复、alpha 原因传播顺序、Windows 跳过解释及 frozen 配置测试纠正均有代码和现存绿例支持。没有对最终 ready 候选作出 GO；发现一项与 child hold 组合后的明确交互，须在最终候选中关闭并给出回归证据。

范围：只读仓库及现存报告，不执行测试、native probe 或 DCC。只在本目录从 before+patch 重建固定候选，以免把实现者正在修改的 ready 源码混入本次审查。未修改源码、06–12 原件或共享证据。

## 固定候选身份

源证据为仓库 `handover/evidence/20261023-native-readiness-stop/implementation/{before-sha256.json,before/,fail-stop-change.patch,fail-stop-after-sha256.json}`。

独立重建的 9 个文件均同时匹配 before/after SHA-256；两个 runtime 的 owned_process 和 alpha_calibration 镜像逐字一致。明细见 `fail-stop-reconstruction.json`，重建文件位于 `fail-stop-candidate/`，输入文件摘要见 `fail-stop-evidence-audit.json`。

- 固定 supervisor after SHA-256：`abe8693257931a80ae317a7088c017f6730e1ba05e77aaa9dc425f37b52382ed`。
- 固定 alpha_calibration after SHA-256：`246674ba6b359428f615e281fbbf7d2b3e70bfafb5cbcfc95a3c395884e8d2c4`。
- 固定 alpha runner after SHA-256：`7135899388b4c28665b50832d9df0e8d6030d5fa7341eee871916fe3966ab711`。

这些摘要只标识该中间 fail-stop 候选，不标识正在加入 ready 的最终候选。

## 采集错误与同轮 TERM

固定 `owned_process.py:411–433` 的 finish_start 保留首个 collection outcome/diagnostic，并在 writer error 时设置 `SUPERVISOR_WRITER_COLLECTION_FAILED`。监督循环 `603–615` 先领取 collection 或写 timeout/aborted error，随后 `616–619` 在同一轮执行 TERM 请求，之后才进入 sleep。已存在的 session/cancel/disk 原因仍优先保留，collector 原异常仍写 started，不被统一 stop_reason 覆盖。

`test_writer_tool_failure_diagnostic_is_signed_and_not_a_process_binding` 使用持续等待外部文件的真实普通 Python child。修改后的用例不再创建 release 文件；它记录真实 `_signal_group` 请求，并在看见 started 的下一次 supervisor sleep 前断言已有 signal。结尾验证 execution failed、原因、非零 execution_returncode、started/stopped 绑定和 release 不存在。它证明软件失败关闭与当轮停止调度，不是原生 vmmap 阳性证明。

collection permission/bad anchor/refreeze change、collection timeout、慢 freeze/observe、取消、session、disk、迟到结果和正常自然退出覆盖均保留。timeout 例在 collector 仍阻塞时确认 owned child 已退出，随后放开 collector，确认 signed started 原字节不被迟到结果重写。

## 执行失败与可信停止

固定候选仍在 owned process wait 之后，再核 POSIX 整组不存在或 Windows Job active=0，才签 stopped。信号请求本身不产生 stopped。没有可信 started 时，即使 child/group 已停止也返回 2，不签 unbound stopped、不调用 scope.finish；永久 started 写失败用例直接检查整组缺席、两个回执均缺失及 scope.finish 未调用。

collector error 可导致 supervisor 自身返回 0，但这只表示 supervisor 完成监督；leader 的非零码仍保留在 stopped，`execution_returncode` 返回非零。若 leader 自己返回 0 但已有 stop_reason，则 supervisor_exit_code=2、execution_result=failed。不能要求 supervisor 内部函数一律返回非零并因此误改已存在的业务/监督码分离。

POSIX signal-denial 现存用例在组尚存时逐轮断言 stopped 缺失、scope.finish 未调用；最终仅在模拟整组缺席后签停止/释放，执行仍 failed。后代仍活、cancel 请求与实际停止的分离也有保留用例。四项 Windows 运行时事实在本机未执行，见下表。

## alpha 原因传播

runner `426–435` 先通过 `read_receipt` 认证 started/stopped 原始 HMAC 与 identity；stopped 的读取同时校验 started hash、PID、owned wait 和 execution 协议。在 nonzero 路径，只有存在 signed writer error 时才调用 `validate_native_process_binding`。

validator `313–328` 先校验可信 expected executable、schema/event、完整 identity、整数 PID、stopped hash、精确 command/argv hash 和 execution_returncode 协议，再调用 `_required_writer_binding` 抛出原始采集原因；只有这些条件成立，原 collector cause 才优先于普通 nonzero 文案。validator 本身是认证后 payload 校验器，不应当被描述为自行执行 HMAC。

新增 `test_failed_writer_cause_requires_authenticated_operation_before_second_launch` 分别验证 signed cause、HMAC 篡改和 argv 不符。原 cause 仅在第一项传播；其他项保留认证/绑定错误；三项都只 dispatch 一次，未创建 alpha-output 或第二个 Nuke supervisor。该用例是明确的软件 signed receipt fixture。现存 real-Python supervisor 用例继续覆盖 missing/wrong-executable/wrong-argv，未以本新增 fixture 冒充原生全链。

## 现存验证结果与跳过

最终现存日志与 JSON 一致：`fail-stop-targeted-02` 为 18 执行、0 失败/错误/跳过；`fail-stop-regression-02` 为 72 项，其中 68 通过、4 跳过，0 失败/错误。前一轮未带 -02 的失败结果保留为过程证据，不能并入最终绿例。

| 跳过用例 | 原因与边界 |
| --- | --- |
| test_parent_exit_keeps_reservation_until_job_descendants_stop | 仅 Windows Job tree；macOS 未运行 |
| test_supervisor_crash_cleans_job_without_manufacturing_stop | 仅 Windows kill-on-close；macOS 未运行 |
| test_unknown_job_query_never_signs_stop | 仅 Windows Job query；macOS 未运行 |
| test_windows_receipt_binds_birth_job_and_wait_observations | 仅 Windows birth/Job/wait receipt facts；macOS 未运行 |

四项是平台装饰器造成的明确跳过，不是通过。另一个 `test_real_writer_executable_binding_is_signed_and_stopped` 被整个 suite 显式排除，因为普通 native probe 额度保留给唯一 repro 角色；它不计入上述 72 项，也不能声称该回归已运行真实 collector 阳性。

本角色没有重跑这些测试，以上是独立读取固定源码/测试及现存原始日志后的审查结论；当前日志 JSON 没有记录完整执行命令、解释器版本和测试时 source manifest，最终候选应补齐这些最小元数据。

## 有效 frozen 配置的测试纠正

生产 `production_hosts.py:109–124` 既有合同允许 path/version/sha256 输入或完整 frozen schema/platform/version/image 结果；后者通过 `_freeze_writer_executable` 再冻结并逐字比对。旧测试把本来有效的 `self.writer` 放在 invalid 列表，还要求 freeze 不调用，导致 MagicMock 无法序列化及 assert_not_called 双错误；`deployment-preexisting-before` 保存了该既有失败。

本次只纠正测试：完整 frozen 配置移至阳性，明确 assert freeze 参数与完整返回值；另增加 stat inode 漂移时拒绝 `WRITER_EXECUTABLE_CHANGED`。None/empty/supplied verified/wrong version/non-Houdini 阴性仍保留，且维持“输入结构拒绝前不得调用 freeze”。没有放宽生产配置合同。

AST 统计表明四个模块未删除独有测试：writer deployment 24→24，其中三项按新行为重命名；alpha calibration 10→10；alpha runner 18→19；owned supervisor 20→21。正常、竞态和故障覆盖未因纠正误分类而缩减。

## 正式冻结依赖与待关闭交互

现有正式 preparation 先创建项目 snapshot，再从 snapshot 运行 alpha preparation，扫描 project 全部文件和 alpha-chart 形成 immutable/source_freeze；runner preflight 检查 required_source_paths、所有实际摘要及 plugin_build，执行前后再逐项核 hash。原 fail-stop 修改的 owned_process、alpha_calibration 和 run_alpha_calibration 都处于既有必需 source 列表，镜像保持一致。现有过程不是给 06–12 旧 bindings 回填新 hash 的授权。

最终 ready 引入 adapter、helper/接点与 process_image 调度后，必须由同一正式 snapshot/preparation/source_freeze 链新生成候选：adapter 固定路径与源码 record、唯一 prerender 参数、完整 runtime 支撑依赖、Hython addon plugin_build、authoritative/controller 镜像、alpha 真实 command 都应重新形成一致冻结。不能仅证明源码文件存在或单元绿例就宣布冻结链已通过。

已发现并交实现者处理的组合交互：finish_start 已取得 valid binding 后，第一次写 started 发生瞬时 OSError；当前固定候选保留该 binding，observation_failed 中重试成功可签出没有 writer error 的 valid started，然后监督器才请求 TERM。ready child hold 若仅看 valid started/binding，可能短暂放行业务。实现者已确认将固定首写失败 writer error（不覆盖已有 collector 原 cause），并增加“valid binding + 首写失败 + 重写成功 + helper 拒绝继续”最小回归。本报告不假定该修复已完成，最终认证前必须收到新源码摘要与绿例。

## 最终候选冻结审计的最小输入

1. 唯一实现者明确声明源码稳定，给出本次实际改动文件的最终 before/after 摘要或完整 patch、authoritative/controller 镜像摘要及 adapter 固定位置；明确包含上述 started 写失败交互的修复。
2. 最终 candidate 的正式软件 preparation/snapshot/source_freeze 原始回执及 manifest；给出每个新增必需源码、plugin_build、adapter record、完整 alpha argv 与所在 snapshot 的一致对应。不改或复用 06–12 原件、旧 receipt.key。
3. 该 candidate 上的测试命令、解释器/平台、开始结束时间、原始 stdout/stderr、结果 JSON、执行前后 source manifest；列明 skips 和排除项。仅需本次风险和既有受影响覆盖，无需再采 native。
4. 软件 ready 正负例的原始 signed runtime-ready/started/stopped（私钥保留本地不复制）、nonce/PID/argv/phase 与 deadline 事实、首次 vmmap 调用前后的顺序、取消/过期/错 PID/错 hash/HMAC/late result、child hold 解除或拒绝事实。
5. collector 失败发现→TERM 请求→owned wait→整组 absence 的事件证据，以及 signal denied/unknown/后代未停时 stopped 缺失与 scope 槽仍保留；alpha 原 cause、无 alpha-output、无第二次 native dispatch。
6. 06–12 的 1457 原件最终 hash 复核及 scope/真实启动状态说明。当前只接受软件验收；真实 H21/Nuke 同 PID 与工程闭环继续 NOT_RUN，须另行授权。
