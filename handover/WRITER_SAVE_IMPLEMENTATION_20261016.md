# 保存函数实现核查增量（2026-10-16）

**已确认 H21.0.631、H22.0.459 的部分保存创建路径；工程闭环仍 BLOCKED，M1 仍 NOT_READY。** 两版二进制中的参数对象 `saveRasterAsFile` 重载都直接调用 filename `IMG_File::create`，后者有直接调用 `IMG_Format::allocValidFile` 和 `IMG_File::makeWriteFilters` 的指令。本轮消除了此前仅有声明/符号、尚无这些函数体调用证据的一个不确定性，没有取得当前 husk 实际 writer 的受支持交接。

本报告接续同日较早的[采集决策报告](WRITER_CAPTURE_DECISION_20261016.md)，该报告中的24条来源、3项软件拒绝用例及 `call_graph_verified=false` 保留为原轮结果，不改写成当时已完成二进制分析。新增证据限本报告指定的两个库和函数，不代表完整调用图验证。

## 范围、版本与方法

维护仓库为 `/Users/user/Documents/Code_Project/Bridge`；本轮开始时 HEAD 为 `e8b9e40cde76b568e40472ae15ca19bd2099638b`，有有效未提交增量，HEAD 不能单独复现工作树。原 Desktop 主工程未改。

本轮只读取以下两个 ARM64 Mach-O 文件。地址为未应用 ASLR slide 的虚拟地址，函数范围为 `LC_FUNCTION_STARTS` 与精确 `nm` 符号对应的半开区间 `[start,end)`。构建标签取自安装路径，未通过运行宿主验证版本。完整身份、UUID、mangled symbol、范围和必要调用指令见 [evidence.json](evidence/20261016-writer-save-implementation/evidence.json)。

| 安装 build | 库字节数 | SHA-256 |
|---|---:|---|
| H21.0.631 | 86,120,032 | `4b765dac5ed3797c98cb6a618881810c3b861d49f2848dbce99a273b24458d9a` |
| H22.0.459 | 90,990,000 | `0d420cfb1263acef67295c42531df85f2b3071b5668ed38f19f9453cea9862da` |

库位于各自 `/Applications/Houdini/Houdini<build>/Frameworks/Houdini.framework/Versions/<major.minor>/Libraries/libHoudiniUT.dylib`。使用 Apple LLVM 14.0.3 的 `llvm-objdump`、`/usr/bin/nm`、`/usr/bin/otool`，启用 ARM64 LSE 解码；每个函数检查指令地址连续、没有越界或未知指令。只对选定函数输出反汇编，不做整库 dump。

未启动 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、许可工具、仿真、缓存或渲染；未导入 hou、dlopen、附加调试器、编译/加载 DSO。未向厂商发送材料、提交或推送。本轮生产代码、测试、生成入口、旧 wheel 和旧交付 ZIP 均未改。

## 已确认的直接静态调用

下表是函数体内存在的 `bl` 指令，证明可能的静态调用边，不证明本次或任何实际 husk 运行已执行。

| 调用边 | H21 callsite（函数内偏移） | H22 callsite（函数内偏移） |
|---|---|---|
| 接收 `IMG_FileParms* / IMG_Format*` 的单 raster 重载 → 接收 `IMG_SaveRastersToFilesParms&` 的单 raster 重载 | `0x178d064`（`+0x34`） | `0x1963b40`（`+0x34`） |
| 参数对象单 raster 重载 → filename `IMG_File::create` | `0x178d278`（`+0x1dc`） | `0x1963d54`（`+0x1dc`） |
| `saveRastersAsFiles` → 参数对象单 raster 重载 | `0x178e388`（`+0x894`） | `0x1964f20`（`+0x950`） |
| filename `create` → `IMG_Format::allocValidFile` | `0x178c294`（`+0x510`） | `0x1962cd8`（`+0x504`） |
| filename `create` → `IMG_File::makeWriteFilters` | `0x178c2ec`（`+0x568`） | `0x1962d30`（`+0x55c`） |

filename `create` 另有调用 ostream `create` 重载的分支；ostream 重载也有调用 `allocValidFile`、`makeWriteFilters` 的直接指令。证据保留这些边，不能将不同条件分支拼成每次都会发生的执行顺序。

由此可将此前“保存入口只有声明与符号”的状态推进到部分实现调用关系已确认。调用 `makeWriteFilters` 不证明创建了哪些具体滤镜、更不证明它们已处理像素或覆盖全部 AOV。

## 间接调用与不能推出的结论

`IMG_Format::allocValidFile` 在两版均于 `+0x18` 执行 `blr x8`；最少上下文显示从 vtable 字节偏移288读取目标。具体动态类型和虚调用目标未解析。其他被查函数也含未解析虚调用、析构/写入分支及未展开 helper。

所查非 tile 函数体没有直接指向 `newDevice/newFileDevice` 的调用，但这不能证明完整路径经过或绕过 tile factory：间接被调函数、其他 helper/库和实际 husk 路由仍未覆盖。因此 `setFileDevCreator()` 仍不能被宣布为当前 husk 全部写出的观察器，也不能被本轮静态分析宣布完全无关。

filename `create` 中另见 filename-only functor 调用点：H21 `0x178c398`（`+0x614`），H22 `0x1962ddc`（`+0x608`）。局部参数准备显示 functor 对象和由文件名构造的 `UT_StringRef` 地址，未见 writer 参数。该全局槽与 `setFileCreateCB` 注册存储的同一性没有确认；本轮不再扩展追踪，不将其命名为已确证的注册 callback。

本范围未识别向已注册 callback 交出 writer 的调用，不证明这种接口不存在。更未观察实际 husk callsite、writer 实例交接或任何运行行为。内部二进制实现不提供官方 API 支持及生命周期契约。

## 复跑、人工解释与审查边界

[evidence 目录](evidence/20261016-writer-save-implementation/)保存精简原始研究证据、三个自编脚本、本轮基线、[复跑记录](evidence/20261016-writer-save-implementation/static-verification.json)和[日志](evidence/20261016-writer-save-implementation/static-rerun.log)。原库、完整厂商源码和函数体 dump 不进入源码快照；有界原始输出留在记录所指的隔离 `/private/tmp` 目录，不作为跨机器持久依赖。

主控用普通 Python 3.11.16 对交付脚本做一次限定复跑，核对库哈希、函数边界、调用指令、间接调用清单和工具身份与原研究一致。脚本先检查固定库 SHA；不匹配或缺少安装应停止，不能改预期哈希使其他 build 通过。

```sh
python3.11 -B handover/evidence/20261016-writer-save-implementation/verify-evidence.py
```

入口默认新建 `/private/tmp/bridge-save-impl-20261016-*` 隔离目录，可读取同目录两个 helper。它会输出新的精简证据和有界反汇编，不能在没有同版安装及相应 Apple 工具的机器上证明原生事实。

自动检查覆盖字节身份、精确符号/范围、连续解码和选定调用指令。`vtable offset 288`、filename 参数语义及“没有受支持 writer 交接”属于有界人工解释；脚本部分 observation 布尔值和参数说明为固定结论，不是自动数据流证明。复跑通过不能扩大这些结论。独立只读复核范围和结果见 [review.md](evidence/20261016-writer-save-implementation/review.md)。

生产与测试未改，未重跑此前3项、38项、54项或全量回归；这些历史结果保留各自日期、源码和覆盖范围。本轮不重建 wheel，也没有当前源码安装验收。归档校验另行记录，只证明包完整性。

## 对正式链的影响与停止点

`client.render_execution_fact` 继续返回 `BLOCKED_MISSING_NATIVE_FACTS`；ArtifactRegistry 的 AVAILABLE 门槛不变，真实上游登记和 Nuke 消费仍未执行。本轮没有新增接收外部“verified 事实”的入口，没有把声明、配置、重建 processor 或文件格式要求转换为完成事实。

仍需共同成立的依据包括：

- 当前 husk 实际 writer 的受支持交接与 product/AOV/frame 绑定、成功 close/flush/失败语义。
- 实际消费的 processor、config/context、命中文件规则、looks/LUT 依赖及各输出/AOV 覆盖。
- renderer filter、denoise、颜色、alpha、编码及 writer 内处理的完整已执行顺序。
- 最终 beauty alpha association 与零 alpha 处理。
- 可信执行身份、停止事实和最终输出字节绑定。

下一有效输入是精确 build 官方支持的接点/样例和生命周期材料，或能直接补齐上述具体缺口的实现依据；同日[厂商问题草稿](WRITER_CAPTURE_DECISION_20261016.md#下一步停止条件与厂商问题草稿)继续本地未发送。当前有界二进制问题已收口，不重复相同反汇编、声明枚举或软件回归以充当闭环进展。新原生组件或运行须依[既定真实阶段边界](FEASIBILITY_AND_CLOSURE_20261016.md#真实运行授权和资源确认)明确范围；本报告不授予该权限，也不复用2026-10-15的一次性例外。

[保留性结果](evidence/20261016-writer-save-implementation/preservation.json)对比本轮4178文件基线，仅允许本轮报告/证据新增及四处导航补充；保留旧轮证据，不覆盖旧交付。完整 ZIP 使用独立名称交付于桌面既有 `Bridge-S06原生定义补采` 目录，M1 NOT_READY 和工程 BLOCKED 分别保留。
