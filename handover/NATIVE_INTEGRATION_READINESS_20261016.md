# 原生集成合同核对与验证准备（2026-10-16）

本轮已完成受支持输出扩展与正式验收合同的限定核查，并准备了可直接审阅的未发送支持问题和条件性实验设计。**生产原生采集组件仍因必要接口合同缺失而无法实施；AVAILABLE→登记→真实 Nuke 消费未完成，工程闭环 BLOCKED，M1 NOT_READY。** 本轮没有新增生产代码或测试通过数，没有编译、加载或运行厂商组件。

## 新增确证依据

两个精确安装的文字材料补到了以下边界；[十条来源身份](evidence/20261016-native-integration-readiness/new-sources.json)包含两版各五份材料，部分与旧索引重叠，不累加为新的唯一来源数量。只保存路径、SHA、大小和定位，不复制 SDK 正文或商业二进制。

| 依据 | 精确位置 | 能支持的结论 |
| --- | --- | --- |
| `driver:parameters:husk:image_format` | `nodes.zip!lop/renderproduct.txt`，H21 第139–140行、H22 第145–146行 | 默认按文件扩展名推断，可以显式选择格式 |
| Image Format 参数定义 | 两版 `houdini/soho/parameters/Husk_Product.ds:101`，USD 类型在108行，菜单111–118行 | string、默认空；随附固定菜单列出 Houdini/RAT/OpenEXR/TIFF/PNG/JPEG，没有任意自定义名称解析的完整保证 |
| `virtual void postCloseAction()` | H21 `IMG_File.h:618`，H22 `IMG_File.h:620` | 在输出流关闭后运行，且部分成员可能已析构；没有成功参数，不能据其发生判定 write/flush/close 全部成功 |
| `virtual IMG_File *createFile() const` | H21 `IMG_Format.h:332`，H22 `IMG_Format.h:338` | 工厂可以创建自有 writer；不交付已有默认 writer 或外层滤镜 |
| `static bool runDSO(const char* lib_path)` | 两版 `IMG_Format.h:106` | 存在格式加载函数；单独声明不证明当前 husk 的合法初始化、调用时点或覆盖范围 |

[静态复核脚本](evidence/20261016-native-integration-readiness/verify-new-sources.py)只读精确安装文本和一个限定 ZIP 成员，核对字节与空白归一化后的关键声明位置。它不证明 ABI、插件加载、调用发生、颜色语义或成功关闭。首次记录因 DS 使用编码参数名、头文件空白不同而拒绝；改为原件中的编码名称及空白归一化后记录和复核通过。这是自编索引工具的修正，不是产品测试结果。

最小候选可以收窄为独有扩展名的自有 `IMG_Format` 阶段探针：保留空 `image_format`，仅在工厂实际被调用时记录自己创建的对象及其执行阶段。它仍是新输出组件候选；当前未采用、未实现，也没有把它当作透明 EXR wrapper 或生产 AVAILABLE 的依据。还缺精确版加载/选择、对象与滤镜所有权、product/AOV/frame 交接，以及写入/关闭错误传播的合同。

## 正式要求的来源与实现边界

原“54行”是 [readiness_evidence.py](../tools/readiness_evidence.py:14) 中17项原合同、21项扩展合同及16个领域的验收矩阵，不是54个 writer 字段。每行须有当前源码、实际操作/测试、case、stage、正负证据和执行断言，校验入口在[同文件1637行](../tools/readiness_evidence.py:1637)；完整接收要求没有因本次代表链收窄而删除。

正式输出链分为以下三层：

1. **当次 producer 事实。** [client.py:165](../packages/houdini-bridge/src/houdini_bridge/client.py:165)冻结操作、进程/监督器、场景、配置、帧、路径、依赖及预算。[render_execution_fact:325](../packages/houdini-bridge/src/houdini_bridge/client.py:325)目前仍固定 `BLOCKED_MISSING_NATIVE_FACTS`（338行）及空 metadata（353行），调用方的 AVAILABLE/metadata 不被采纳。
2. **原始签名终态。** [seal_render_terminal:387](../packages/houdini-bridge/src/houdini_bridge/client.py:387)要求当前 owned child、完整帧和输出事实，重验场景/字节后封存；原件不能事后补 metadata 重签。JSON 摘要自身不替代 producer 认证。[终态认证:452](../packages/houdini-bridge/src/houdini_bridge/client.py:452)保持原始事件要求。
3. **正式登记。** [_formal_output_encoding:182](../packages/vfx-pipeline/src/vfx_pipeline/domain_readiness.py:182)要求 AVAILABLE、精确帧、非空 colorspace、严格 bool premultiplied 及一致编码。[_receipt_metadata:359](../packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py:359)再验场景、operation、来源、依赖与逐帧 path/bytes/modified_ns/sha256；[_typed_admission:682](../packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py:682)核对实际 EXR 字节、结构和物理 metadata。

长期 [M1 F02](M1_GAPS_20261015.md:7)要求实际 writer 进程、processor/LUT、AOV、filters、alpha 与当次操作/帧/最终字节绑定。config/context/file-rule、有序处理和 alpha 缺项也已在 [client.py:254](../packages/houdini-bridge/src/houdini_bridge/client.py:254)保留；完整次序、零 alpha 与 close 语义是充分证明这些事实所需的细化，Registry 没有独立的 processor handle 或 close 事件字段。

合同要求本次实际输出的可信事实，没有规定每个合法新 writer 都必须窥探默认 PXL 私有对象。受控新 writer 可以证明它真正执行的转换、所用处理器和写入阶段；仍需证明 husk 本次确实选用它、输入 alpha 语义、产品/AOV覆盖、其控制范围外的前后处理，以及成功完成和最终字节。缺这些事实时，合法新 writer 和默认 writer 观察路线都无法产生完整 AVAILABLE。

本轮限定核查未找到能脱离这些缺失事实、独立推进正向生产链的明确代码修复。prepared-case 适配仍保留 persisted output/full semantic 等 missing_proofs，不能因局部未列出全部 writer 细节就宣称发现可直接修补的正向漏洞。本结论不代表全仓无缺陷。已有 Nuke 来源、颜色/alpha继承、读回与回滚修复保留原样。

## 已完成的具体准备

[SideFX支持问题正文](evidence/20261016-native-integration-readiness/SIDEFX_SUPPORT_DRAFT.txt)可单独审阅，要求两个 build 分别回答实际对象交接、自定义格式加载选择、处理器诊断、执行次序/alpha、成功关闭与故障生命周期。它只包含公开接口和合成单帧目标，未附私人工程、媒体、凭据、安装二进制、反汇编或任务密钥，**未发送**。

[条件性实验设计](evidence/20261016-native-integration-readiness/experiment-design.json)将资源建议具体化为：H21 主版、sphere_ground_v2、frame 1、128×128 Karma CPU、一个渲染作业、最多120秒；含冷重开的 DCC worker 最多启动两次，总 DCC 时间上限300秒，输出/临时/日志总量256 MiB，自动重试为0。单重作业、未知停止保槽，沿用现有 owned child 监督器；不包含 Nuke、H22、模型、反馈、仿真或仿真缓存作业。方案不是执行授权，也不构成一套已验证的启动步骤。

该设计冻结了本轮4198文件输入基线和既有安装包身份，列明未来组件源码/编译器/SDK/插件指纹、可信运行身份、正式快照及资源确认尚待取得。缺少的原生组件不存在，因此其 build 字段明确为空，没有虚构可启动命令。设计 `confirmed=false`、`phase_exception_approved=false`，不作为 preflight 输入，不伪造操作快照。当前 M1 前置矛盾及原生预检未解决，不能仅凭资源数字进入执行。

## 本轮验证和交付边界

[材料核验结果](evidence/20261016-native-integration-readiness/readiness-verification.json)记录新增来源字节、设计限制、当前四 wheel/三 Skill 的 payload 身份以及正式合同源文件身份。独立复核发现核验器的临时基线依赖与清单缺项假通过两项问题，均已修订：默认读取随包固定SHA基线，强制四包/三Skill精确无重复集合并与上轮固定身份比对；输出计数来自实际集合，`--output`写入指定的新文件。空、缺项、重复和未知集合已定向确认拒绝。首版结果仅作为[审计历史](evidence/20261016-native-integration-readiness/readiness-verification.initial.json)保留，最终结论只使用当前结果及其绑定的最终脚本。

安装包沿用[上一轮](HUSK_ENTRY_AND_CURRENT_RELEASE_20261016.md)已验证的相同字节；本轮生产/测试/payload 未变，只复核绑定，没有重建、重安装或重复全量软件测试。原生命周期 build_id、通过范围和765份无密钥审计材料保持原样，不改成“本轮重新通过”。最终新增文档由本轮 source-manifest 另行绑定。

[独立复核](evidence/20261016-native-integration-readiness/review.md)与[基线保留比较](evidence/20261016-native-integration-readiness/preservation.json)分别记录实际覆盖范围；归档校验不提升工程或M1状态。原4198文件除 STATUS/NEXT_AGENT 导航外均应保持原字节，所有历史 ZIP 不覆盖。

原生实现仍阻断于受支持接口与生命周期材料；真实宿主、编译/加载 DSO、外发支持问题和采用新输出路线均未执行。全16域、48+2案例和54行要求不变。下一次有效输入应是缺失合同的正式资料；不再重复已收口的二进制核查、声明枚举或安装生命周期来替代它。
