# 非颜色 writer 阻断

当前工程闭环仍为 **BLOCKED**，M1 为 **NOT_READY**。人工项目色彩选择已接入；下列三项不能由该选择、可读 EXR 或进程停止事实替代。

## 当前缺失的原生事实

| 阻断 | 已有依据 | 缺少的具体合同 |
| --- | --- | --- |
| 实际 writer、产品/AOV 与非颜色处理 | 已有 USD 配置观察、postframe 原件、writer 可执行文件及 OS 祖先链认证 | 取得本次 husk raster-save 的实际 writer 实例，绑定 product/AOV、帧、最终路径及实际执行的处理次序；不能用另建实例或某一个滤镜阶段代替 |
| 最终 alpha 关联 | EXR 结构和通道可读，SDK 有 alpha 值查询、premultiply/unpremultiply 操作及部分格式需求接口 | 当次最终 beauty 的 associated/unassociated 状态，以及影响它的处理结果；有 A 通道、格式约定或配置需求不构成该次执行证明 |
| 写出成功 | `IMG_File::write()` 和 `close()` 有错误返回；原始监督器与同步 ROP 返回用于停止判定 | 取得上述实际 writer 的 write、filter、flush、close 结果及逐产品错误传播，绑定最终文件；postframe 或 postClose 回调发生不证明这些阶段成功 |

“写出成功未证实”是当前明确保留的阻断。现有签名回执没有单独枚举此项，但其他缺项和固定 `BLOCKED_MISSING_NATIVE_FACTS` 已阻止放行。原始缺项列表参与 HMAC 和终态摘要，不追加字段或重写旧回执来制造新的观测结果。

## 接口依据与限制

版本为 **H21.0.631／H22.0.459**。本机 SDK、样例与帮助原件已由独立只读核查者对照既有大小／SHA 索引核验。安装路径不等于运行版本证明；未执行任何厂商程序或导入厂商模块。

- 两版 `toolkit/include/IMG/IMG_File.h:218–221`：直接 `close()` 可取得析构关闭无法返回给调用者的错误信息；`:332–339`：`write()` 在写入失败时返回 false。缺少的是当前实例交接及跨层结果传播，不能表述为“没有错误报告 API”。
- `IMG_File.h` 的 `postCloseAction()` 是无成功参数的 void（H21 `:618`，H22 `:620`）；`flushBytes()` 为受保护的 bool（H21 `:670`，H22 `:672`）。`toolkit/samples/IMG/IMG_Sample.C:210–215` 的样例关闭函数在 flush 后无条件返回成功，不能据其补齐传播合同。
- 两版 `IMG_File.h:470–473` 的 `getAlphaInfo()` 是读取时的 alpha 值信息；`PXL/PXL_Raster.h` 的 premultiply/unpremultiply 是操作、hasAlpha 是通道存在。H22 `IMG_File.h:594` 的格式预乘需求也不是实际最终关联态。
- 两版 `IMG_TileFile.h:95` 的 `files()` 要求已持有当前实例；`IMG_TileDevice.h:71–101` 的 factory、`IMG_Format::createFile()` 均未交付 husk 当前正在使用的默认 writer 及外层处理链。
- `toolkit/include/BRAY/BRAY_ImageFilter.h:28–29,79–105` 覆盖自身处理阶段；`toolkit/include/TIL/TIL_HuskDevice.h:29–31,65–95` 是 display 接点。两者都未提供本次最终磁盘 writer 的完整处理及成功关闭结果。
- 本机 `houdini/help/ref.zip!utils/husk.txt` 的 postframe 定义（H21 `:211–215`、H22 `:237–241`）只说明渲染帧阶段及可用变量。[官方 husk 文档](https://www.sidefx.com/docs/houdini/ref/utils/husk.html)是滚动版本补充，不替代两个精确 build 的接口保证。

原件身份与既有定位见[实际接口索引](evidence/20261016-writer-interfaces/native-interfaces.json)、[writer 链原生依据](evidence/20261016-writer-chain/native-basis.json)、[writer 来源索引](evidence/20261016-writer-capture-decision/source-index.json)、[集成来源索引](evidence/20261016-native-integration-readiness/new-sources.json)、[实际 writer 接口核查](WRITER_INTERFACES_20261016.md)及[husk 保存入口](HUSK_ENTRY_AND_CURRENT_RELEASE_20261016.md)。历史颜色追踪前置按当前人工项目色彩决定执行。

## 软件验证与独立复核

[本轮软件验证原始记录](evidence/20261019-noncolor-writer/core-tests.log)复用 10 个现有核心用例，**10/10 通过**：hook 安装／恢复与原件认证、停止未知约束、已认证进程仍不能证明 alpha、调用方不能填写 AVAILABLE、旧签名回执保持原样，以及显式软件 producer 的账本接收与读回。账本正例不证明 Houdini producer 已能生成这些事实。

[两位独立只读核查者](evidence/20261019-noncolor-writer/review.md)分别检查 writer／处理／成功返回，以及 alpha／producer／账本边界；均未发现能凭现有原生依据实施、并关闭这些阻断的代码修复。本次只更新阻断说明和接续导航，保留全部代码与测试，不重复全量、安装或打包。

## 继续条件

需要补到同 build 的受支持实例交接与结果采集合同，才能沿既有私有观察 → 原始签名 producer → AVAILABLE → 账本 → Nuke 接线。原生依据应包含对象生命周期、product/AOV/frame/path 绑定、最终 alpha、处理次序及成功／失败传播。没有该输入时，重复声明枚举、静态调用位置或安装验证不能关闭此边。

真实宿主、编译／加载新输出组件、仿真、缓存、渲染、模型及对外发送支持问题均未执行。本记录不授权这些动作，也不改变工程闭环的通过标准。
