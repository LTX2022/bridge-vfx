# Common output producer：原生输出事实的可实现边界

日期：2026-10-09；独立只读诊断。源码基准 HEAD `a3e7734e0f69b663be5bbd7d1f97bbdcb2d90b7d`，工作树已有并行改动，以下 SHA-256 绑定本次读取字节，不代表最终冻结 build。仅新增本报告；未改 addon/client/登记链，未运行测试、真实 Houdini/hython/husk/Nuke、仿真、缓存或渲染。没有生成成功 metadata、签名或回执。formal recovery b 由主 agent 复现，本诊断不重复对应实现/审查。

## 关键结论

1. **存在具体、同版本有依据的采集接口，不应把所有缺口都归为“没有 API”。** H21/H22 本机帮助明确给出 husk `--preframe-script` / `--postframe-script`，脚本变量 `stage`、`settings`、`husk_command` 和 `hou.frame()`；HOM 明确有 `hou.Color.ocio_configPath()`。这些能把实际 husk 进程的配置观察与父 Houdini preflight 区分开。但本次没有执行它们，实际运行可用性仍 NOT_RUN。
2. **当前 collector 明确不能完成登记。** `render_execution_fact()` 无条件生成 `BLOCKED_MISSING_NATIVE_FACTS`、空 `metadata`；追加 USD token、角色名、环境 hash、EXR 通道或手写 `premultiplied=True` 都不能合法解锁。当前状态是输出配置/物理字节可观察，输出语义与实际执行链未闭合。
3. **现有采集还遗漏了已经有同版本帮助依据的 RenderProduct 级 source/output colorspace。** 只看 settings 的 `renderingColorSpace` 与 RenderVar 级覆盖不足以算有效变换；自动输出颜色需要最终 override 路径参与 file-rule 求值。H22 还必须观察 `--disable-slapcomp` 和重复的 `--slap-comp`，不能只看 `husk:orderedImageFilters`。
4. **alpha 是实质门槛。** 本次列明的 SDK/帮助/已有代码未提供足以判定“该帧 Karma beauty 经该输出驱动和 filter 链最终为关联/非关联 alpha”的事实接口或完整版本语义。A 通道存在、RGB 在 A=0 时非零、EXR 扩展名、颜色角色都不是证明。真实宿主运行本身也不会自动补出 alpha 合同。
5. **最短软件路径是验证观察器及拒绝链，而非伪造上游成功。** 主 agent 可在明确底层 hou/USD/OCIO/进程替身上验证字段读取、优先级、字节绑定、缺项/漂移拒绝；正式链仍诚实 BLOCKED。实际 husk 身份、执行后 filter 效果和原生 alpha 语义需要另行具体授权与事实依据。

## 当前源码真实覆盖

仓库根 R = `C:/Users/32200/Desktop/Agent/skill/Bridge`。下文文件均为 R 下原件，行号为本次阅读定位。

| 当前入口 | 已观察/约束 | 不能据此宣称 |
|---|---|---|
| `plugins/houdini/_impl/houdini_bridge_addon.py:12656` `_fx_render_configuration` | Driver/usdrender；逐帧 `parm.evalAtFrame` 的 loppath/rendersettings/override_camera/renderer；`lop.stage(frame=..., apply_viewport_overrides=False, ignore_errors=False)`；RenderSettings、单 RenderProduct、camera、lights、orderedVars；scanline/非 multipart/none-zips-zip 格式；composed stage 文本 hash | 父 hou 中 compose 的 stage 等于 husk 导出/重载后 stage；实际 argv、husk 子进程 OCIO、delegate/plugin/driver 已执行；filter 已作用于字节 |
| 同文件 `:13485` `_advance_render`，实际调用约 `:13532` | 所有权、场景与冻结配置先核对；每帧调用 `node.render(frame_range=(f,f,1), output_file=绝对路径, output_format="exr", ignore_inputs=True, to_flipbook=False)`；fresh EXR、解码、压缩核对、snapshot；collect 后才 frames_done | 这些 render kwargs 等于可核验的最终 husk argv；ROP 内部没有额外 override/script/slapcomp；husk 实际环境已采集 |
| `packages/houdini-bridge/src/houdini_bridge/render_color_facts.py:99` | 原生 `GetPrimAtPath`、属性 GetName/GetTypeName/HasAuthoredValueOpinion/Get(frame)、关系 GetTargets/GetForwardedTargets；settings→products→orderedVars；逐帧类型和值；有序 filter 配置；128 全局目标/64 filter 属性预算，失败保留 missing_facts | authored/fallback 状态等于有效颜色；原始 filter 属性等于执行效果；字符串属性可以猜成关系目标 |
| `packages/houdini-bridge/src/houdini_bridge/client.py:246` | 请求/frame/snapshot/path/hash 绑定；对同一观察字节作 EXR 解码；compression/header 与 producer snapshot 比较；返回 color_configuration_fact 和三项 missing_facts | `colorspace`、`premultiplied` 或 AVAILABLE。`:278` 仍无条件 BLOCKED，并在帧缺失时追加 FRAME_OUTPUT_OBSERVATION_REQUIRED |
| `packages/dcc-task-runtime/src/dcc_task_runtime/exr_codec.py:139,249` | scanline 单 part；UINT/HALF/FLOAT 通道布局、窗口、压缩、标准视图头；即使 with_pixels=False 也验证块/样本结构，返回 structural_validated、pixel/sample count | 通用自定义头保真、OCIO 语义、alpha 关联。解析虽接收未知头，返回仅保留支持的标准 header_fields；不能期待额外写入 `oiio:ColorSpace`/alpha 标记就被当前接口返回或判真 |
| `packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py:359,682` | `_receipt_metadata` 要求 AVAILABLE、producer receipt/frame/scene/dependencies 绑定、每帧 metadata 与 snapshot 一致、非空 colorspace、严格 bool premultiplied；`_typed_admission` 对 hash 绑定只读副本重新验证物理 metadata，保存前后文件身份核对 | 登记端代替 producer 推断/补齐颜色或 alpha；旧回执重签；仅把 status 改 AVAILABLE 就能建立真实语义 |

`_bridge_scene_fingerprints`（addon `:9208`）记录父 Houdini 的 OCIO、HOUDINI_OCIO_FILENAME、picker gamma，hash 显式路径；无路径标为 houdini_builtin/available。**这是 preflight 场景漂移材料，不是 actual husk effective OCIO 证据**：未读当前配置 API、LUT、context、file rules；同一 config 文件而 LUT/context 变化亦不能被该 config-only hash 充分覆盖。

## 已有原生依据及具体采集 API

### Runtime output override / renderer / driver

- `usdrender-renderer-machine-field-audit.json` 中两版本创建脚本均直接 `opparm ... renderer`；help 的 `#id renderdelegate` 只是文档锚点，不能当 parm 名。当前源码使用 renderer 有静态原件依据。
- `w1-sopimport-usdrender-static.json` 的 vendor `hqrop.py:114–123` 明确读取 usdrender/usdrender_rop 的 `outputimage`，非空优先，空则查 USD RenderSettings；帮助 `out/usdrender.txt:113–117` 还说明逐帧与单进程帧占位符不同。这是路径规则依据，不能把 productName 当最终文件路径。
- H21 `ref.zip!utils/husk.txt:184,191,211`，H22 `:210,217,237`：pre/post frame hooks 可直接观察 `stage`、`settings`、`husk_command`、`hou.frame()`。**应读 documented `husk_command`，不能用脚本自己的 `sys.argv` 冒充完整 husk 命令。** 记录其原始值与类型；帮助没有保证它的序列/字符串表示或 settings 字典键集，软件实现不得编造键名或用 POSIX shlex 静默解析 Windows 命令。
- 同版本帮助列明 `-o/--output`、`-s/--settings`、`-R/--renderer`、`--ocio 0|1`；后者关闭时回退 Houdini 图像格式固有假设，不能算 OCIO file-rule 路线。输出路径需结合实际命令、所选 product 和落盘字节，严格限定现有单 product/单帧路线。
- H22 帮助说明 renderer 优先级 CLI → `husk:delegate` → 环境；其中环境名写作 `HOUDINI_HUSK_DEFATULT_DELEGATE`，与现有代码读取的 `HOUDINI_HUSK_DEFAULT_DELEGATE` 拼写不同。不得照帮助 typo 猜运行选择，也不得用当前环境字符串声称实际 delegate；要求显式 renderer/运行观察。创建脚本的 HOUDINI_DEFAULT_ROP_RENDER_DELEGATE/HOUDINI_DEFAULT_RENDER_DELEGATE 是另一层，不能混用。
- SDK `HUSD/XUSD_RenderSettings.h` 的 `XUSD_RenderSettingsContext::overrideProductName()`、`defaultProductName()`、`overrideSettings()`、`defaultAovDescriptor()` 和 productName(frame) 证明原生存在 override/default 决策层。**它们是 C++ 接口/扩展点，并非已暴露的 husk Python getter，更不是已发生执行的证明。** 当前最短路线应使用正式 hook 和现有 runner，不重写 HDK renderer。
- `out/usdrender.txt:364,459` 的 Print Command/Run command-off 可以导出 USD 和打印预定命令，但这仍需运行真实 Houdini/ROP、可能 cook，上述授权禁止；即使另行授权 dry export，它也只证明“拟执行命令”，不证明 husk 执行。

### OCIO config / LUT / context / file-rule

| 层级 | 可实现读取 | 边界 |
|---|---|---|
| 同进程 HOM | `hou.Color.ocio_configPath()`；`ocio_spaces()`、`ocio_roles()`、`ocio_activeDisplays()`、`ocio_views(display)`；本机 `hom.zip!hou/Color.txt` 两版均有 | 路径/列表可查询，但不自动拿到实际 writer 使用的 processor；不调用 reloadOCIO 或编辑配置 |
| OCIO 配置 | `PyOpenColorIO.Config.CreateFromFile(实际路径)` 或版本核验后的 GetCurrentConfig；配置序列化与原始文件 SHA-256；Config getCurrentContext/getCacheID/getSearchPath/getWorkingDir/getFileRules | CreateFromFile 得到重新加载的 config，是可重放解释，不能自动等同于 Houdini PXL 已缓存的有效 config。GetCurrentConfig 也不能未经同进程一致性验证就认定等于 PXL/writer 配置 |
| 有效上下文 | Context getStringVarNameByIndex/getStringVarByIndex/getNumStringVars、working dir/search path，必要时 usedContextVars；对依赖相关变量精确采集 | 仅 OCIO env 路径不足；禁止复制整份环境中的凭据；未知/无法解析变量留下 gap |
| 规则求值 | Config `getColorSpaceFromFilepath(final_output_path)`；C++ 另有 ruleIndex 重载，FileRules 可枚举规则名/模式/扩展/目标空间 | 用最终 override 后路径；不得用 pattern/productName/临时副本名求规则。SDK C++ 重载不是已验证 Python 签名，Python 规则索引能力需同版本 binding 检查 |
| 角色/processor/LUT | 解析实际源/目标空间及 role；Config getProcessor(context, src, dst)；processor getProcessorMetadata；C++ ProcessorMetadata getNumFiles/getFile；Context resolveFileLocation；hash 解析出的 LUT 原始字节 | 只保证该重建 processor 的依赖；Python metadata 的 files 访问方式须查绑定，不能照抄 C++。Processor/config cache ID 不是密码学文件 hash。无外部 LUT 可以合法为空，但须来自成功的 processor 观察，不能省略观察就填空 |

API 原件是两版本 `toolkit/include/OpenColorIO/OpenColorIO.h`；`PXL/PXL_OCIO.h:51` 给出 `PXL_OCIO::configFilePath()`，但没有由此证明 Python 能获取 PXL 当前 processor 或 LUT/context 全闭包。H21 vendor `python3.11libs/ocio/editor.py:11,763–780` 实际使用 PyOpenColorIO、hou.getenv、CreateFromFile/CreateFromEnv，并带查找 fallback。它的 editor 会剥离 USDZ rules/修改配置，不适合作为只读有效采集入口。

本机 H22 相应 Python 原件实际在 **python3.13libs**，不是沿用 H21 的 python3.11libs；这不改变仓库 Bridge 软件 Python 3.11 要求，但跨宿主进程不可假定相同 OCIO Python binding/解释器。该路径差异已只读确认，未导入 hou/宿主模块。

### AOV / filter / alpha

- RenderVar 现有 sourceName/sourceType/dataType、husk name/channel prefix/lower_rgb/source/output colorspace 的逐帧 Get 观察是合法配置事实。可进一步观察实际 `driver:parameters:aov:husk:format` 与 channel_layout 的输出类型/命名映射，不能仅凭 RenderVar 的节点名等于 EXR 通道名。
- **必须补采 Product** 的 `driver:parameters:husk:source_colorspace` 与 `driver:parameters:husk:output_colorspace`：两版本本机 `nodes.zip!lop/renderproduct.txt:142–148` 有依据。该段 Output Color Space 描述误复用“source”字样；因此可以保留 raw 属性和值，但不要凭这一句错误描述发明冲突优先级。RenderVar help `:184–189` 分别说明源空间、输出转换和默认 file_rules，non-color AOV 通常 raw；“通常”不能变成实例默认事实。
- 现有 Product 属性集仅 productName/productType，未覆盖上述两级颜色继承。sourceType=raw 表示 USD AOV 来源机制，与 OCIO raw 色彩空间不是同一枚举；dataType=color3f 也不独立证明最终 writer 颜色空间。
- `karma:plane:filter` 是每 AOV 样本重建 filter，RenderVar help `:90–96` 定义 JSON filter 列表；它与 `husk:orderedImageFilters` 的保存处理/Slap Comp 链不同，必须分别保留。当前 collector 没有专门读 karma:plane:filter。
- H22 `ref.zip!utils/husk.txt:380` 明确 `--disable-slapcomp` 可禁用 RenderSettings 的 orderedImageFilters，`--slap-comp` 可重复、按顺序执行。因此 stage 中有 filter 且关系顺序正确仍不足。旧 ROP 的 COP filter list/file slapcomp 来源也应按实际 argv 观察，不凭 HDA 字段存在断言已执行。
- H22 SDK `HUSD/UsdHoudini/houdiniImageFilterList.h` / `houdiniImageFilter.h` 可只读核对真实 schema/property/AOV 作用域。现有 collector 对关系会遍历 filter prim 属性；若是同名 attribute 则原样保留并标语义未决。不能猜 attribute→relationship；不能靠“已遍历全部属性”声称完整 graph、外部资源、输入输出 AOV、颜色/alpha effect 已读全。
- 官方在线 [Filter List](https://www.sidefx.com/docs/houdini/copernicus/filter_list.html) 支持有序 image filters 与 husk 路线，不能反向证明 H21 具备 H22 同样接口。官方 [husk](https://www.sidefx.com/docs/houdini/ref/utils/husk.html) 亦支持 hook/禁用语义；优先采用本机精确 build 帮助。
- **alpha 未获足够事实**：没有发现上述 collector、HUSD RenderSettings API 或原件提供帧输出关联态 getter。通用 Premultiply COP、PNG/TGA 导出选项、shader opacity、OpenEXR 格式惯例、Nuke Read 的解释选项不能证明这次 Karma/husk beauty。用户 metadata 可以任意写入 `--extra-metadata`，只能当声明。必须另取版本/渲染器/驱动的权威语义，加上实际生效配置与已执行 filter 对 alpha 的影响；未知 filter 必须阻断。
- 即便执行已授权的受控透明度/边缘/发光小场景，像素也只能反证错误假设或支持限定路径，不能将 RGB≤A、A=0、A全1等统计作为任意 HDR/emissive beauty 关联判定算法。若未来选择显式转换使 alpha 语义可证明，应作为实际派生 producer、保留 raw lineage；不能给未知原图贴标签。本次不建议未经授权新增转换。

## 最短软件可验证路径（供主 agent 实现，诊断不参与实现）

1. **保留现有正式 runner 与缺事实拒绝。** 从 `_fx_render_configuration`、`collect_render_color_facts`、`collect_render_output_fact` 延伸观察模型，分开记录父 preflight、husk preframe/postframe、最终 EXR 的来源/帧/operation/进程身份。本报告不设计替代成功 metadata 或新的验收体系。
2. **先验证纯观察器。** 在既有底层 USD/hou 替身读取 Product/Var 颜色、AOV 采样 filter 与 image filter，保留 authored/fallback/缺值/原生类型和 ordered forwarding；在底层 OCIO boundary 验证 context/LUT/最终路径 rule，不替换 runner、client collector、registry 或上层成功回执。可用非宿主 OCIO 库对明确微型 config/LUT 做真实解析，但本次未导入/安装/运行，安装的两个宿主版本 binding 仍需各自验证。
3. **软件 hook contract 独立于真实执行。** 通过普通受控 Python 子进程或明确注入 globals 的底层替身，给观察脚本提供 documented stage/settings/husk_command/frame，验证原始值、bounded capture、单帧/单 product、时序、进程 nonce 与输出字节绑定；标为 software hook fixture。husk_command 类型、settings 键、writer 当前 config 一致性未验证时必须保留 gap，不能硬造 keys。真实 `node.render` 内部子进程的身份绑定仍是集成需解决的问题，不能凭路径 sidecar 或日志文本当 producer 证明。
4. **复用最小覆盖，不再跑全域计划。** 现有 `test_render_color_facts.py` 已有逐帧/forwarding/类型/预算/缺事实/属性不冒充关系等路径，`test_software_render_property_identity.py` 验证底层身份；EXR codec 与登记既有字节替换/物理 metadata coverage 复用。新增只需针对本次新风险：Product→Var覆盖、最终路径 rule 与 pattern 不同、同 config hash 下 LUT/context 漂移、--ocio=0、disable-slapcomp/重复 slapcomp、未知 alpha/filters 拒绝、preflight 成功但 runtime 缺失拒绝。此处是建议，未重跑/宣称通过任何测试。
5. **软件结果上限：采集/拒绝路径可验证。** 全帧 byte observation 可以存在，缺真实 husk/alpha 时 completion 仍 BLOCKED；若主 agent 修复 formal recovery，使恢复到登记时报具体缺事实而非泛化失败，那是正确软件行为，不等于产物可供 Nuke 正式可信消费。

## 确需另行授权的真实阶段与停止门槛

| 需要真实执行的事实 | 本次限制/门槛 |
|---|---|
| 两版本实际 LOP compose/export→husk load、hook globals、actual command/env/config、delegate/plugin/driver 选择 | 真实 Houdini/hython/husk 不得启动；当前只能静态/API和软件替身；dry export 亦未授权 |
| 实际 husk 内 HOM/PXL/OCIO 配置一致性、ctx/LUT/file-rule 与 writer 生效路线 | 父 preflight 环境和单独 CreateFromFile 不替代；需要实际 husk hook 或受支持 writer instrumentation，事前冻结捕获边界 |
| 最终 filter/slapcomp 执行、AOV 映射、色彩变换后真实帧文件、停止与 nonce/owner 绑定 | 需要真实渲染及实际 native hook/日志/字节证据；presnapshot 不是最终帧完成，采用已保存全部 product 的 postframe 再复验字节 |
| Karma beauty alpha 关联 | 先取权威原生语义或受支持观察点；真实跑一帧并不能自动关闭。filter 能修改 alpha/beauty 或未覆盖版本路径时继续阻断 |

当前结论分别为：静态原生/API边界诊断完成；软件实现及验证本次 NOT_RUN；真实宿主/渲染 NOT_RUN；安装、HY3/模型、视觉与生产验收不在本诊断范围。没有“全域 PASS”或“common producer 闭合”的结论。

## 本地原件 SHA-256 索引

以下均实际只读计算，不含凭据/旧签名密钥。ZIP `!member` 摘要针对解压后的成员原始字节；不把旧 macOS 路径当当前 Windows 安装路径。静态 JSON 自身携带的 vendor/HDA digest 是历史采集断言；本次核对到的 Windows 相同成员另列。并行实现可能使源码 hash 变化，集成时必须按当前 build 重新核对。

### 仓库原件（相对 R）

| 文件 | SHA-256 |
|---|---|
| docs/native-basis/usdrender-renderer-machine-field-audit.json | `dfb3e6f0eb0c3c49621edb1a995b1540d5474cbbd627638794886880b99f0b16` |
| docs/native-basis/w1-sopimport-usdrender-static.json | `e2e88bdbeb9270e4bcf3fd5242958c9dc618faae123247995c63db0718f7162e` |
| docs/native-basis/lop-render-hda-followup.json | `ba655e0cf95feaf14381753cbbbd8afce37dccbfce4b928968a9a9d2091f1b90` |
| plugins/houdini/_impl/houdini_bridge_addon.py | `011085514d30e58dcdbbb7401a505f06d32f66fbe0aa5f89fc731341c66262eb` |
| packages/houdini-bridge/src/houdini_bridge/client.py | `c08eedddc6e80ea8f16005971f2267eab2bae6c17259c15e0ac25c68998e337b` |
| packages/houdini-bridge/src/houdini_bridge/render_color_facts.py | `5af14343f9dfba0f4da301098c2a79524c7a40e50ed6c08cab3c8b3d6ded8b3a` |
| packages/dcc-task-runtime/src/dcc_task_runtime/exr_codec.py | `84227c881af2e5f39c6764ad9987c6034036c506e4e52a4477c9d772e5c576a6` |
| packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py | `a01fcd9066b3a66eba9ad9c89cedd332942d5b31813b756d02b8b756e38b0ce0` |
| tools/software_render_api_boundary.py | `496afdb6eb7956d74f24f63fe6a4164906afd8f18a020468b62db3842a85c2c2` |
| tests/unit/test_render_color_facts.py | `7822f43595a87fcc58d5d6ef4ee8dac45f59da278afd34978eeb53f8dc5a43d2` |
| tests/unit/test_software_render_property_identity.py | `6a5cd52e414a4be454ae45ba2f844e5f7a39a7282d984782499a1182f4fc3d5b` |

HDA JSON 内 rendersettings DialogScript section 摘要：H21 `64a2c91d781a30a2a8919c704e8cc880164793bbd58aeacc78f9e8940c7a15a2`，H22 `325937f14987a4b23ec74be88ac1bb0a424e351a469776e41b15952dbef9ac3d`；renderproduct section H21 `9c9e358b0cd04af37199cae174c6e4a790b5caf4b08d0f0d7fdf17199db5c8d1`、H22 `db75399202e08a57d1c5a1b29b42a2f871b690b9f23fe5db955a185bcb015cab`。它们证明参数/控制项静态载体，不证明 cooked USD、默认门控、实际输出或 alpha。JSON 明示 native_execution NOT_RUN。

### 本机 vendor 原件

S21 = `C:/Program Files/Side Effects Software/Houdini 21.0.631`；S22 = `C:/Program Files/Side Effects Software/Houdini 22.0.429`。以下路径相对对应 S；ZIP 行号指成员文本。

| 路径 | H21 SHA-256 | H22 SHA-256 |
|---|---|---|
| houdini/scripts/out/usdrender.cmd | `63a12109739a6a9d5cf99f635e3b25a4370af968f116012aec6ecd1df8973f72` | `63a12109739a6a9d5cf99f635e3b25a4370af968f116012aec6ecd1df8973f72` |
| houdini/help/nodes.zip!out/usdrender.txt | `b051a6a7534d9a03dd7c6766f9f35b7b3af6b8a9bd40d96ddef2e3fa9811528b` | `d5b42ffa8f2e94c697526bf1ab03d0a7e1484e31a3e259ed28081f714218163d` |
| houdini/help/nodes.zip!lop/renderproduct.txt | `0d6a6258c9c120a5461cbbf7c7003fd704c20d836a3542b3dfba842d4cd91115` | `989df33e12f44b0883e20691d9c59dd0e6837af88af9436d8d770dcb6ccb32dc` |
| houdini/help/nodes.zip!lop/rendervar.txt | `8b89b47153c3da8f8fa2a173a4ee78f18582b91fc2547cb248900a757094d542` | `d8584b92a5816165bcdd613d4d34bdb25f514e6858c3e4026d4bd4a59cd8bb8b` |
| houdini/help/ref.zip!utils/husk.txt | `2fec082cc5dc408bf7b7548af57241d1de6f809c9b3228842a67bd02c3ac00fc` | `c40fd248372322c73f8beb8e75dad8a3f82654061960fd6d051f843724b70f2b` |
| houdini/help/hom.zip!hou/Color.txt | `5c585a264795d9d3ff053afc8bb500a48186b16c6b8919d872b91cc0b4518260` | `0d826bc346e925a8c547d05c3c4fe8f99312748f7aabffc800acb8696bc7c733` |
| houdini/help/solaris.zip!ocio.txt | `2e570d3152da2226b6b015c7843721d7ceab46f6df8b3e5e25cdf4c569ea534e` | `1ae45987b4b12c0ef99d87f6f12f05329c5b7a014ea05eb6f706a8afea775b75` |
| toolkit/include/OpenColorIO/OpenColorIO.h | `fbddc381400b8f007d787fef9bc6b5845e502ba60a2aed2a128ab9571c3ba547` | `71ebcb7fd4ce8ea9ed22fb87ca08e6f218705515b71868466df59f88afcda100` |
| toolkit/include/PXL/PXL_OCIO.h | `0d24679ac8724f3795b5427c975426ee6ecf69c866cbab8f04d0ea8aae897471` | `6b9a66835c04d614747f5c6d9a1af69842e8afbdb092ca903c404f72d6532223` |
| toolkit/include/HUSD/XUSD_RenderSettings.h | `ece03a0c62364c01f105d7a3f5aa8e844c4859f160ea4b7b1c6ec5b00c83fca0` | `1cd5a4c6c6be648135c3c57963a404c06fc55de7a88c3f229526c3700bc66b7c` |

版本特定 Python 源：S21 `houdini/python3.11libs/ocio/editor.py` = `02392dc611cd8a076788f31eaf7ac2c1884f3d3c77dacc8d678318ca3fe680df`；S21 `houdini/python3.11libs/hqrop.py` = `a56a25a7e63b89e680eb7455b81ce6061daaa2078e3beb3f51865d67370acf89`；S22 `houdini/python3.13libs/ocio/editor.py` = `4fe01e146de50ef8d9662195a2f4d90e9cb738484728a2b031b731a79dc26d92`；S22 `houdini/python3.13libs/hqrop.py` = `e9282f5b172f2a5a5ac829eff46c250673b59d97740e3f3cb2a0603ab5fc67e0`。

S22 `toolkit/include/HUSD/UsdHoudini/houdiniImageFilterList.h` = `6d40f69e81f58d90bcad6b2e643d3e52342a91aef6737607b3699cd971ed55ba`；`houdiniImageFilter.h` = `ffe7d8f184212f4390b9c3861d588249d1329495fdb2efa81dd009203e74db64`。

只读过程中先按 H21 目录假定查找 H22 python3.11/3.12 路径，得到文件不存在；后以文件枚举确认 python3.13 原件并另算摘要。未把缺失读当通过，也未启动任何宿主寻找路径。

## 快速接入补充：唯一建议入口

建议主 agent 接入 **`collect_render_preflight_environment(node, frame)`**，每帧在 `_fx_render_configuration` 调用一次，保存为 `values["preflight_environment_fact"]`。此函数读取所在 Houdini 进程的环境和 ROP 参数，不启动进程、不 setFrame、不 cook stage、不加载/修改 OCIO。软件验证以底层 hou/parm/env 替身执行同一个函数；真实宿主调用仍需授权。以下为待主 agent 实现的完整最小函数草案，未写入共享源码、未运行、未视为已实现证据：

```python
def collect_render_preflight_environment(node, frame):
    import os
    import hou

    if type(frame) is not int:
        raise ValueError("integer request frame required")

    def observe_string(reader):
        try:
            value = reader()
            if value is not None and (
                    not isinstance(value, str) or len(value) > 8192):
                raise ValueError("bounded native string or None required")
            return {"observed": True, "value": value}
        except Exception as error:
            return {"observed": False, "error_type": type(error).__name__}

    environment_names = (
        "OCIO", "HOUDINI_OCIO_FILENAME",
        "OCIO_ACTIVE_DISPLAYS", "OCIO_ACTIVE_VIEWS",
        "HOUDINI_DEFAULT_ROP_RENDER_DELEGATE",
        "HOUDINI_DEFAULT_RENDER_DELEGATE", "HOUDINI_HUSK_DEFAULT_DELEGATE",
    )
    parameters = {}
    for name in ("loppath", "rendersettings", "override_camera", "renderer", "outputimage"):
        try:
            parameter = node.parm(name)
            parameters[name] = (
                {"present": False} if parameter is None else
                {"present": True, **observe_string(
                    lambda: parameter.evalAtFrame(frame))})
        except Exception as error:
            parameters[name] = {"observed": False, "error_type": type(error).__name__}

    return {
        "schema": "bridge.houdini.render-preflight-environment/1.0",
        "scope": "houdini_process_preflight",
        "frame": frame,
        "process_id": os.getpid(),
        "render_target": node.path(),
        "houdini_build": hou.applicationVersionString(),
        "environment": {
            name: {
                "hou": observe_string(lambda: hou.getenv(name)),
                "process": observe_string(lambda: os.environ.get(name)),
            } for name in environment_names
        },
        "ocio_config_path": observe_string(lambda: hou.Color.ocio_configPath()),
        "rop_parameters": parameters,
    }
```

**放置与持久化**：可由主 agent 在 `render_color_facts.py` 实现该函数，在 addon 原每帧配置循环调用。已有 `render_config[frame]` 随 request/producer binding 冻结和持久化，无需另写旁路成功回执。同帧 render 前重读时沿用现有配置相等核对，可检测这些环境/参数的漂移。不要加入采集时间字段，否则当前整个配置相等比较会每次失败；process_id 只描述本进程，不是 husk PID 或认证 owner。重开新 PID 的新操作应正常重新冻结；旧操作恢复不得绕过既有 owner 约束。

**值与错误**：unset 保留 None，空串保留空串；不存在参数记录 present=False，读取失败记录 observed=False。不要把缺 hou.Color API 替身当成“builtin config”，软件边界应显式提供该 API，另保留 absent/raise 用例。这里只记录白名单环境；error_type 避免异常文本意外携带环境秘密。`ocio_config_path` 来自实际 HOM API，是本进程加载配置路径的观察；没有 hash/config/LUT/context/processor 闭包，不能称 effective OCIO。若下一步附加 config hash，应对这个 API 返回的实际文件作既有稳定字节观察，不能按 OCIO/HOUDINI_OCIO_FILENAME 二选一推断当前加载文件。

**输出覆盖**：`rop_parameters.outputimage` 是参数读回。当前 `_advance_render` 又传 `node.render(output_file=...)`，所以最终计划输出应继续绑定现有 `record.output_pattern` / frame_path 与真实调用参数；不要让该 outputimage 字段覆盖 request 的输出路径，也不要标 actual husk output override。

**不提升 gate**：该事实不填写 colorspace/premultiplied、completion_metadata_status、effective_husk 或 executed，也不删三项 native missing_facts。能立即增加的是原生环境/逐帧参数观察与漂移检测；formal b 缺事实仍应报告精确 `FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED`。用户提供的 hardcoded linear/False、SQLite busy 重试及 22 tests 结果是主 agent 本轮进展，本诊断未执行或独立接收它们。

本补充再次只读核对 addon/client/render_color_facts 的 SHA-256，分别仍为上述 `011085...262eb`、`c08eed...e337b`、`5af143...ed8b3a`。HOM `ocio_configPath` 原件复核为 H21 `hom.zip!hou/Color.txt:128`，成员摘要仍为索引中的 `5c585a...18260`。同时纠正上文列表 API 名为 `ocio_activeDisplays()`，不沿用不存在依据的 `ocio_displays()`。

## Product 类型补证与 raw hook 的最小建议

新增只读查到精确版本 usdHusk schema 原件，两个 Product 属性均有明确 `string` 声明，可以采用 expected_type="string"，无需退为 None：

| 版本 | schema.usda（相对对应 S 的 houdini/dso/usd_plugins/usdHusk/resources/usdHusk/） | generatedSchema.usda（相对 resources/） |
|---|---|---|
| H21.0.631 | HuskRenderProductAPI 从 :124；output_colorspace :193；source_colorspace :204 | Product API :64；output :102；source :107 |
| H22.0.429 | HuskRenderProductAPI 从 :129；output_colorspace :203；source_colorspace :214 | Product API :89；output :147；source :154 |

原文机器属性声明：`string driver:parameters:husk:output_colorspace = ""` 与 `string driver:parameters:husk:source_colorspace = ""`。空串是 schema fallback，依然不可解析为已有效转换或读取失败；现有 collector 可以保留 present/type_name/authored 及空值 gap，不补成功值。

SHA-256：S21 schema.usda `3fcfcc5846fcea161ca938a5c7a80b96a2acfd04dc359a432a4c41bc95332627`；S21 generatedSchema.usda `c17d9c9601cefcfcd4a0e154f8d27051b209dd25ed63ef9544549330a1e2e5ae`；S22 schema.usda `3360753147a7f0ff1f29d8cda37a831660649b52fb0e62681212f7e73cea59f4`；S22 generatedSchema.usda `f8d861f754ba66b534eb49ac6a8f10af516d8aa7ef302e14e38caa2befcd556d`。

help 机器 #id 辅证：S21 `nodes.zip!lop/renderproduct.txt:142–147`，S22 `:148–153`；前文帮助摘要有效。类型结论来自 schema 声明，非 label。两个 Product 属性均不含 `aov:`，与 Var 级命名区分。

独立 raw hook **值得优先于扩展 preflight 做**，因为观察输入对应未来真实 husk 文档钩子，避免只在父进程读配置。最小建议：`collect_husk_hook_raw(stage, settings, husk_command, frame, ocio_config_path, *, settings_path, phase)`；仅对明确注入的输入做观察，复用 `collect_render_color_facts(stage, frame=frame, settings_path=settings_path)`。增加 settings_path 是为了不猜 documented settings 字典的私有键；phase 限 preframe/postframe，避免混淆采集时点。

返回 raw hook schema、phase/frame/settings_path、bounded raw husk_command/settings/ocio_config_path、composed color facts、明确缺项。husk_command 原始字符串或有序字符串列表均可按类型保存，不拆命令；settings 仅保存有界、有限数值的支持类型树，未知原生对象记类型/缺项，不 repr/str 假转换；不从其未知键解析最终 product/argv/renderer。输入来自软件替身时明确标 software_fixture，collector 不自行推断 actual_husk 身份。留 identity/nonce 的认证绑定给既有 producer/进程边界，采集器不签发完成、不写 AVAILABLE。未来 thin hook wrapper 才可读取 documented globals、hou.frame()、hou.Color.ocio_configPath()；本次不运行或接入真实 hook。

最低验证是调用同一个 collector 的普通软件执行：逐帧 stage 值不同、settings_path 显式选择、字符串/列表命令保持原样、未知 settings 值和超预算拒绝/留 gap、pre/post phase 区分，并保持现有 native missing_facts。Product 原件新增也显示 H22 orderedImageFilters 为关系，存在于 Product 与 Settings API；本次仅补类型证据，不自行改现有 filter 作用域实现。
