# 实际 writer 采集决策与停止条件（2026-10-16）

同日后续的[保存函数实现核查增量](WRITER_SAVE_IMPLEMENTATION_20261016.md)已检查两版精确库的限定函数体，补入 save→filename create→格式分配/写入滤镜创建的直接静态边。本文保留较早一轮声明/符号核查与3项软件用例的原始范围；下述“未检查实现”不再代表最新研究状态。完整 tile 路由、实际 husk writer 接点及其余最终事实仍未确证，BLOCKED 结论不变。

## 结论

**当前不能实施可信的 `AVAILABLE→产物登记→Nuke 消费`。** 对 H21.0.631、H22.0.459 的本机 SDK/样例及 SideFX 官方公开文档进行限定核查后，仍未取得当前 husk 实际 writer 的合法交接、实际颜色处理器的完整诊断、全链已执行顺序和最终 alpha association 的共同依据。结论是材料不足，不断言 SideFX 内部不存在相应接口。

本轮完成静态证据复核、三个已有软件拒绝用例的定向复现和可交接的厂商问题草稿；生产源码、测试、生成入口和既有 wheel 均未修改。`client.render_execution_fact` 保持 `BLOCKED_MISSING_NATIVE_FACTS`；真实 Karma 产物登记、Nuke 消费、工程闭环及完整 M1 均未通过。旧全 16 域铺开方案继续冻结，当前工程→反馈/恢复→HY3→复用顺序保持。

本轮没有启动 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、许可工具、仿真、缓存或渲染，没有编译/加载 DSO、导入厂商原生模块、发送支持工单、提交或推送。原 Desktop 主工程未改。

## 范围与可复核材料

接续 [实际 writer 接口核查](WRITER_INTERFACES_20261016.md) 与 [writer→登记→Nuke](WRITER_CHAIN_20261016.md)，本轮只处理尚未成立的保存调用链、格式工厂、processor 可见性、生命周期与 alpha 证据。已有 Nuke 颜色/alpha 继承、raw/Write alpha 读回和失败回滚不重复实现。

维护仓库是 `/Users/user/Documents/Code_Project/Bridge`，接手时 HEAD 为 `e8b9e40cde76b568e40472ae15ca19bd2099638b`，存在大量先前有效的未提交增量。HEAD 不能单独代表本轮源码。原 Codex 的 `Documents/Codex/.../bridge-1-workbuddy-hy3-bridge-houdini` 是研究目录，旧 `Desktop/bridge-skills` 不是本轮维护目标。

本轮证据位于 [evidence/20261016-writer-capture-decision](evidence/20261016-writer-capture-decision/)：

- [source-index.json](evidence/20261016-writer-capture-decision/source-index.json) 记录两个精确安装版本的核心头/样例路径、字节数与 SHA-256。24 条记录与既有研究部分重叠，不能加到历史 60 条上宣称新的唯一来源总数。
- [verify-static-sources.py](evidence/20261016-writer-capture-decision/verify-static-sources.py) 重新读取限定大小的材料，核对字节及关键声明。该工具不导入厂商模块、不构建 DSO，也不验证二进制 ABI、实际调用图或 writer 运行事实。
- [static-verification.json](evidence/20261016-writer-capture-decision/static-verification.json) 保存本轮复核结果与工具身份。
- [blocked-path-result.json](evidence/20261016-writer-capture-decision/blocked-path-result.json) 与 [原始日志](evidence/20261016-writer-capture-decision/blocked-path-tests.log) 保存三个已有软件夹具用例的命令、源码 SHA 和结果。
- [baseline.json](evidence/20261016-writer-capture-decision/baseline.json) 保存接手前4169个文件的哈希与Git状态；[preservation.json](evidence/20261016-writer-capture-decision/preservation.json) 保存本轮改动与该基线的比较，不把基线中的所有既有修改归为本轮工作。该比较覆盖既有tracked/非忽略文件，不覆盖被忽略历史输出或仓库外目录。
- [review.md](evidence/20261016-writer-capture-decision/review.md) 保存独立只读复核的范围和结论。

核心 SDK 哈希清单不复制厂商头文件正文；下面辅助初始化文件和安装帮助的行号属于限定研究的来源定位，并非全部纳入这 24 条核心哈希清单。线上文档为滚动版本，不能用作两个精确 build 的 ABI 保证。

## 接点所能证明与尚缺的事实

### 1. 保存入口与 tile factory 的连接没有证实

两版 `toolkit/include/IMG/IMG_File.h` 第155、158行声明两个 `saveRasterAsFile` 重载，第168行声明 `saveRastersAsFiles`。随附 SDK/样例/帮助中未找到这些函数的实现或 husk 保存 callsite。多 raster 方法签名没有 raster 集合参数，`IMG_SaveRastersToFilesParms` 也没有对应字段；数据供给方式需要官方样例，不能猜测。

两版 `IMG_SaveRastersToFilesParms.h` 第39行构造参数可接收 `IMG_FileParms*` 和 `IMG_Format*`，第65、67行提供对应访问，第73、74行可显式设置；第59行 `init()` 只有声明。这证明可请求自选格式与参数，未证明返回当前 husk writer 或已执行滤镜。

两版 `IMG_TileDevice.h` 第54行附近说明 `newDevice()` 无特殊匹配时使用 file device，第89行声明 `newFileDevice()`，第97、100行说明/声明 `setFileDevCreator()`。该替换入口存在，但没有材料把保存函数与它连起来。限定 `nm` 核查表明两个 `libHoudiniUT.dylib` 都定义相关符号；符号存在既不能证明经过 factory，也不能证明绕过。

因此不能把 `setFileDevCreator()` 直接安装为“覆盖当前 husk 全部 raster 写出”的观察器。`IMG_TileFile::files()` 仍以先取得实际实例为前提。

### 2. 自定义格式是新组件候选，当前没有透明观察器

两版 `IMG_Format.h` 第79、94、101行提供格式查找/分配能力；protected `createFile()` 位于 H21 第332行、H22 第338行。工厂不接收当前 writer 或它的外层 filter，另行分配的对象不能证明就是 husk 正在使用的实例。

两版 `IMG_FormatPassThru.h` 第27行只保存调用方给定的 parent，并以 `IMG_Format(false)` 避免注册；第101行 `createFile()` 返回 `nullptr`，第107行向内查找 base file。`IMG_FileFilter.h` 第41行也只向内返回包装对象。没有由内层默认 EXR writer 寻回全部外层滤镜的公开回链。

官方教程和 `IMG_Sample.C` 确认可注册自有格式，由工厂创建自有 `IMG_File`，实现写 scanline、关闭等方法。自有组件在实际被调用时可以记录自身收到的数据和执行结果，但其上游颜色处理及最终宿主接线仍须单独证明。委托默认 EXR Format 也属于新输出组件与路由设计，不能当作既有代码的小修复，也不能自动解决 private LUT handles。

相关初始化事实仅限：

- `IMG_Format.h` 第31–35行说明 `newIMGFormat(void*)` 的参数为 null；`IMG_Sample.C` 第321、323行创建格式并自动注册，工厂在第119、121行创建具体文件对象。
- `UT_DSOVersion.h` 第52–57行声明 DSO 加载后可调用 `HoudiniDSOInit(UT_DSOInfo&)`，未保证 husk 的具体加载时点或早于 writer 创建。
- `houdini/FBformats` 第5–14行说明格式搜索与优先序，第56、57行列出 OpenEXR/OIIO；`houdini/help/ref.zip!env.txt` 的 H21 第1808行、H22 第1878行说明 `HOUDINI_IMAGE_DSO_PATH`。它们不证明所有目标产品会选中某个插件。
- `samples/standalone/tiledevice.C` 第177–186行只在 Windows 设置 MPlay creator，第194行使用 `newDevice("ip")`，没有文件 creator 或保存 raster 的演示。macOS `UT_Main.h` 第62–66行的 `UT_MAIN` 只显式调用主函数及退出处理，不能据此声称完成 IMG/格式加载初始化。`UT_SubSystem.h` 的 H21 第136行、H22 第147行另有全 subsystem 初始化声明，尚无本任务的完整启动顺序证明。
- `samples/IMG/sample_install.sh` 引用当前目录不存在的 `IMG_Raw.C`，且 `dso/fb` 与 `dso_fb` 措辞不一致，不能当作已验证的可用安装步骤。

### 3. 实际 processor、context、file-rule、LUT 与 AOV 覆盖仍缺诊断接口

两版 `IMG_FileFilterLUT.h` 第37–61行公开初始化参数，第65行可写 scanline；第70行起为 private，其中第78行 `ocioHandle()` 和第90、91行的 handles 不能由合法公共 API 读取。初始化值、scope 或重新构建的 processor 不等于实际消费的 processor。

`PXL_OCIO` 仅前置声明 `Processor`；`PHandle` 的成员指向这个不透明类型，公开 `isValid/isNoOp/is3D` 不能给出所需联合事实。`lookupProcessor` 可构造/查询用于自有转换的处理器，不能发现输出 writer 已选中的对象。`addConfigChangeCB(UT_Functor<void>)` 只通知 config reload，回调没有运行事实参数；reload 会使 processor/color-space 指针失效。

两版 `PXL_OCIO` 的位深声明存在差异：H21 直接使用 OCIO 的 `BitDepth`，H22 第35行定义镜像 enum。任何未来组件都要按各 build 编译适配；不能 cast opaque processor、复用跨版本 ABI，或用另一份重建 processor 补证实际消费。

所需的 config/context、命中文件规则、looks/LUT 依赖、输出覆盖和每 AOV 有效处理，仍没有一个已确证接点能共同报告。

### 4. 文件 hook、post-frame、滤镜和 alpha 的证据边界

`IMG_File::setFileCreateCB(UT_Functor1<int, const UT_StringRef&>)` 只传文件名；`setFileHooks` 的 hook 涉及文件名和 `UT_IStream*`。它们没有 writer、产品/AOV 或 processor 参数，未给出覆盖全部 husk 写出和成功关闭通知的契约。

husk `--postframe-script` 提供 `stage`、`settings`、`husk_command` 与当前帧，但公开说明未承诺它在实际 writer close/flush 成功后执行，也没有暴露 writer/processor。`--extra-metadata` 是调用方提供的字段。`--ocio 1` 说明使用 file rules 与 RenderVar 属性，未提供实际命中结果查询。现有私有签名 post-frame 原始观察继续保留其边界，不能因此升级为有效 writer 事实。

`getBaseFile/getUnfilteredFile` 可从已持有对象向内看包装链；TIL/BRAY/display 或自有 filter 的调用只能证明对应阶段发生。Filter List 文档保证列表内部顺序，没有覆盖 renderer、denoise、颜色、alpha、编码及 writer 内转换的全局执行次序。

`IMG_File::getAlphaInfo(float&)` 的基类默认返回 `IMG_ALPHA_VARYING`，注释关联打开参数的 alpha 检测；`formatNeedsPremultiplied()` 描述格式要求。二者不能证明该次最终 beauty 的 associated/unassociated alpha、零 alpha 像素处理历史或后续转换。仅有 alpha 通道和值也不够。

## 本轮实际验证

使用普通 Python 3.11.16，不导入 `hou` 或任何厂商原生模块。核心材料复核结果为 24 条字节/SHA 一致，两版关键声明检查均通过；明确 `runtime_version_verified=false`、`call_graph_verified=false`、`available_basis_complete=false`。

定向复用 `tests/unit/test_houdini_output_receipts.py` 的三个已有用例，结果 **3 tests，0 failure，0 error，0 skip，退出码0**：

| 用例 | 复现结果的含义 |
|---|---|
| `test_existing_producer_registry_refusal` | 正式 producer fact 仍被 ArtifactRegistry 以 `REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED` 拒绝，history 为空 |
| `test_observes_actual_physical_metadata_without_color_or_alpha_defaults` | 读取合成 EXR 的结构/内容事实，未填默认 colorspace/premultiplied，alpha 原生缺口保留 |
| `test_caller_metadata_and_available_are_not_adopted` | 调用方自行加入 metadata/AVAILABLE 不会被生产事实采纳 |

这些用例使用显式文件/传输夹具，没有运行真实 DCC，不证明实际 Karma 输出或 Nuke 消费。历史38/54项及全量结果没有在本轮重跑；生产未改，无需用重复全量替代缺失原生依据。独立复核和保留性比较详见对应证据文件，范围仅本轮增量，不代表全仓接收。

复核静态材料可在相应安装存在的机器运行：

```sh
python3.11 -B handover/evidence/20261016-writer-capture-decision/verify-static-sources.py
```

跨机器应先核对相同精确 build 并在副本中调整 source_roots；不能修改 hash 使另一版本假通过。缺少安装时复核为 BLOCKED，源码包本身不提供商业宿主。

## 下一步停止条件与厂商问题草稿

当前重复静态枚举已达到本轮停止条件。只重新运行相同软件测试、查看相同声明或累加符号，不能消除下面的缺口。下一有效输入应是适用于两个 build 的正式 API/示例、生命周期保证或原生实现材料。以下内容只是本地准备的支持问题草稿，**未发送给 SideFX**，不包含私人工程、媒体、凭据或任务密钥：

1. 对 Houdini 21.0.631 和 22.0.459 分别说明：husk 保存 raster product 时怎样取得实际选中的 `IMG_File`/writer 实例，以及成功 close/flush/失败事件？如何绑定 product、AOV、frame、输出文件？是否正式经过 `IMG_TileDevice::setFileDevCreator()`；若不经过，受支持接点是什么？
2. 怎样查询该次真正执行的颜色 processor、config/context、命中的 file rule、looks/LUT 依赖和各 AOV/输出覆盖？若 `IMG_FileFilterLUT`/`PXL_OCIO::PHandle` 无公共诊断，是否有受支持的 observer 或可替换输出管线？不能仅提供重建等价 processor 的例子。
3. 是否有包含 renderer image filters、denoise、颜色、premultiply/unpremultiply 和编码的实际执行次序报告？如何证明其没有遗漏后续 writer 转换？
4. 最终 beauty 的 alpha association、零 alpha 处理及输出编码有什么正式保证和可查询事实？请区分格式要求、输入约定与该次最终写出。
5. 如推荐自定义 `IMG_Format`：请提供两个精确 build 的 husk 选择/插件加载和初始化样例、所有目标 raster 产品覆盖、外层 writer filters 的创建/交接顺序、`saveRastersAsFiles` 的数据供给方式，以及合法的 processor 诊断方式。

收到材料后先逐项核对版本与事实覆盖；任一必需事实仍仅有配置值、格式要求或 opaque handle，就保持 BLOCKED。即使静态接口成立，生产转换还须实现可靠身份/停止与最终输出字节绑定，随后才能分别验证登记与 Nuke 消费。

## 条件性原生验证设计（未执行、不是授权）

若以后获准开发新组件，最小隔离验证可先用合成 raster 分别测试两个单 raster 保存重载，以 `newDevice(普通文件路径)` 作为 creator probe 阳性对照，再观察保存调用是否触发同一 probe。多 raster 方法先索取官方数据供给样例，不猜调用。另测显式自定义 Format 委托预先捕获的默认 EXR Format，记录创建/返回对象链、写入及关闭结果并与默认输出比较。两者只能验证对应新组件，不能自动证明真实 husk writer 绑定、外层 processor 或最终 alpha。

该设计缺具体源码/构建指纹、初始化方案、版本/案例、总作业数、帧、路径、磁盘/时间累计预算、停止方式和媒体范围，故不可直接执行。任何真实宿主、厂商模块、编译/加载 DSO 或渲染步骤，都须满足 [现有真实阶段边界](FEASIBILITY_AND_CLOSURE_20261016.md#真实运行授权和资源确认) 并有具体范围；本文不复用2026-10-15的一次性例外，也不改变 M1/M2 前置。实现候选前仍须明确它是新输出路由，并评估其是否满足原验收要求。

## 官方在线来源

以下页面用于说明公开契约边界，访问研究日期为2026-10-16。husk 页面标为 Houdini 22.0；公开 HDK 页面未提供可绑定本任务两个精确 build 的标记。Major Changes 未列 observer 不能证明 observer 不存在。

- [IMG_File.h](https://www.sidefx.com/docs/hdk/_i_m_g___file_8h_source.html)
- [PXL_OCIO.h](https://www.sidefx.com/docs/hdk/_p_x_l___o_c_i_o_8h_source.html)
- [IMG_FileFilterLUT](https://www.sidefx.com/docs/hdk/class_i_m_g___file_filter_l_u_t.html)
- [HDK 自定义图像格式教程](https://www.sidefx.com/docs/hdk/_h_d_k__image__extend.html)
- [IMG_Sample 官方样例](https://www.sidefx.com/docs/hdk/_i_m_g_2_i_m_g__sample_8_c-example.html)
- [husk 命令参考](https://www.sidefx.com/docs/houdini/ref/utils/husk.html)
- [Copernicus Filter List](https://www.sidefx.com/docs/houdini/copernicus/filter_list.html)
- [H21 HDK Major Changes](https://www.sidefx.com/docs/hdk/_h_d_k__changes_21_0.html)
- [H22 HDK Major Changes](https://www.sidefx.com/docs/hdk/_h_d_k__changes_22_0.html)
