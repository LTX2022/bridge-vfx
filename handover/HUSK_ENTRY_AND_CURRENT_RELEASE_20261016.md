# husk 保存入口与当前源码安装验证（2026-10-16）

本轮完成两项有界推进：补齐两版精确 husk 保存入口到 filename `IMG_File::create` 的静态连接，并从当前源码重建四个 wheel、三类 Skill，通过隔离安装和现有软件生命周期验证。工程闭环仍 BLOCKED，全 16 域 M1 仍 NOT_READY；生产 AVAILABLE、真实上游产物登记及 Nuke 消费尚未完成。本轮未修改生产代码或放宽事实校验。

## husk 保存入口的新证据

[精简证据](evidence/20261016-husk-entry-current-release/entry-evidence.json)和[复核脚本](evidence/20261016-husk-entry-current-release/verify-husk-entry.py)固定两个本机安装文件的 SHA-256。版本号来自安装路径，未执行二进制查询运行版本。

| 安装标签 | husk 字节 | SHA-256 | Mach-O UUID |
| --- | ---: | --- | --- |
| H21.0.631 | 2725824 | d6fadf014e002d9d04d58aa9f17a4cc292af7195b05195c1cd358d471c11196f | 964196a3-74c0-396a-9748-9925a6f1ed7f |
| H22.0.459 | 2863840 | 18076bcd3d64f18610546fcf1c5a6d1c99d28632eecd6983ba4e336f2a19b9c2 | 031979fb-e57d-323c-99bb-510877931e4d |

每版限定六个函数：`hdRenderProduct::save`、`imgSave` C1/C2、匿名 `saveData` C2、`rasterConvert::convert`、匿名 `setPlaneSemantics`。共十二个函数，以 Mach-O `LC_FUNCTION_STARTS` 与精确符号界定半开范围，连续 ARM64 解码，并对收录的直接分支独立解码机器码目标。地址是未施加 ASLR slide 的虚拟地址。

| 静态连接或调用 | H21 指令地址 | H22 指令地址 |
| --- | --- | --- |
| hdRenderProduct::save → imgSave C1 | 0x100068b28 | 0x100074cc8 |
| imgSave C1 → C2，尾分支 b | 0x1000793c8 | 0x100088258 |
| imgSave C2 → saveData C2 | 0x100078f74 | 0x100087d4c |
| saveData → filename IMG_File::create 的导入 stub | 0x10007c188 | 0x10008d74c、0x10008d930 |
| saveData → PXL_OCIO::lookupProcessor 的导入 stub | 0x10007a3b0 | 0x10008b218 |
| rasterConvert → PXL_OCIO::lookupProcessor 的导入 stub | 0x1000866b8 | 0x1000981f0 |
| rasterConvert → PXL_OCIO::transform 的导入 stub | 0x1000867b0 | 0x1000982a0 |
| saveData → IMG_File::write 的导入 stub | 0x10007c270 | 0x10008da54 |
| saveData → IMG_File::close 的导入 stub | 0x10007c454 | 0x10008ddb4 |

前四行合计九条保存连接，处理器三行合计六条指令。导入 stub 的符号来自 Mach-O 间接符号表；这不验证运行时动态链接实际目标。H22 的第二个 create 调用点明确保留，未假定其产品语义或所有分支都会执行。首次脚本假定每版仅一个 create，因 H22 观察到两个而拒绝；检查实际调用后按版本固定数量重新验证成功。该诊断不作为产品测试失败或删减证据。

同一已解码范围还可见颜色空间查找、通道语义设置及格式 gamma 参数调用；这些没有被解释成当前作业的有效颜色空间。`rasterConvert` 的 lookup 与 transform 是静态调用位置，不是执行日志，也没有证明实际 handle、输入输出像素或 AOV 逐项覆盖。未解析的间接调用和分支保留在精简证据内，不扩展为完整调用图。

上一轮 [libHoudiniUT 保存实现](WRITER_SAVE_IMPLEMENTATION_20261016.md)确认 filename create 内的格式分配及写入滤镜创建。本轮只新增 husk 自身入口，不重复该库函数体。两轮证据可以描述静态路径候选，不能据此声称一次实际输出已走过全链。

运行复核脚本只读取固定两个 husk 文件并调用 Apple `llvm-objdump`，在新建的 `/private/tmp/bridge-husk-entry-20261016-*` 目录保存有界原始反汇编与 JSON。仓库只保留精简 JSON、自编脚本和验证记录，不复制厂商程序或完整反汇编。脚本中的 `interpretation_limits` 是明确的结论边界，不是自动证明 API 支持或实际运行。

## 当前源码发布与软件安装结果

输出根为 `outputs/current-source-release-20261016-s78f3h42/`，四包和三类 Skill 均沿用既定版本 `2.0.0rc1`。本轮没有覆盖 `vendor/wheels` 中的历史包。完整交付内的 `installers/` 才是本轮构建内容，具体 SHA-256 与源文件集合由 manifest 绑定。

使用 Python 3.11.16，构建环境由本机 `venv/ensurepip` 离线建立。先复制包源码到自有输出目录，再以 `pip wheel --no-index --no-deps --no-build-isolation` 构建，避免向维护源码写入 build/egg-info。四个 wheel 的有效 payload 与各自当前 src 集合逐文件 SHA-256 完全一致：dcc-task-runtime 39 文件、houdini-bridge 47 文件、nuke-bridge 12 文件、vfx-pipeline 32 文件。

新建安装环境离线安装四包，清空 PYTHONPATH/PYTHONHOME，以 `-I` 验证四个模块实际导入自安装环境；`pip check` 及 houdini-bridge、nuke-bridge、vfx-pipeline 三个 CLI 的 `--help` 均 exit 0。这里未验证 FFmpeg、商业 DCC、目标机器差异或完整异机离线媒体依赖。

`tools/build_release.py` 从当前源码构建三类 Skill，随后执行 `tools/verify_skill_lifecycle.py --readonly-files`。三个包分别通过安装后的软件依赖闭包、真实模块内容升级、失败升级保留生效导入和注册、回退恢复、注册切换、保留无关设置与卸载检查。升级和故障包是明确的合成安装夹具；底层 DCC 原生 API 是显式软件替身。Python/TCP 子进程的软件通过不等于真实 Houdini 或 Nuke 运行。

发布绑定覆盖 release_layout 声明的全部文件。生命周期验证开始至结束，build_id 覆盖的源码身份未变；三类 payload 分别为 481、429、542 个文件。构建时脏工作树和 HEAD 身份保留在原 manifest，本轮不提交或推送。随后新增的本报告、handover 证据和导航不属于发布 payload，但会改变覆盖整个 handover 的整源码 build_id。因此历史生命周期中的 source_unchanged 只直接证明该次生命周期验证时间窗，不指最终文档增量后整棵树完全相同；不改写原 build_id。最终 source-manifest 另行绑定完整交付源码。

完整 raw 连同三份 evidence-sha256.json 随交付保留为无密钥审计材料，共 765 文件，包含三套各 254 个原始证据文件及其索引；其中有软件调度/任务数据库、WAL/SHM、操作身份和已签停止回执。这些材料不是安装 payload、活动调度根或可恢复执行状态。原操作均已成功终止、重槽不活跃，原隔离用户目录已删除；不保留可复用宿主认证或签名密钥。attempt_token/process_token 是已终止尝试的身份字段；signed receipts 的原字节和哈希可核对，但 HMAC 密钥不交付，无法据此重新验签、重签或恢复任务。交付另含构建脚本、结果 JSON、manifest 和全部本轮日志；排除两个 venv、build-source 缓存、原临时用户目录及全部认证/签名密钥。

## 正式链合同与仍缺的依据

重新核对的最早阻断仍是 `client.render_execution_fact` 固定生成 BLOCKED_MISSING_NATIVE_FACTS 并清空 metadata；领域 `_formal_output_encoding` 在登记前拒绝；签名终态需要原执行事实封存，不能事后补 metadata 或重签历史事实。ArtifactRegistry 和 Nuke 消费的正式字段是受绑定的产物身份、帧、字节、颜色空间及 bool premultiplied，并不要求它们直接持有 PXL 对象。实际 writer、processor、AOV、filters 和 alpha 的采集要求同时见长期缺口及 M1 记录，不能由调用方提交 verified 标记代替。

本轮未复现可脱离缺失原生事实、独立推进上述正向生产链的新代码缺陷；这不证明全仓无缺陷。已有 Nuke 颜色/alpha 继承与读回回滚整改保持原样，旧三项、38项、54项及历史全量测试没有重复运行。

仍缺的是受支持的当前 writer 实例交接、实际消费的 processor/config/context/file-rule/looks/LUT、逐产品与 AOV 有效覆盖、全链已执行的 filter/denoise/颜色/alpha/编码次序、最终 beauty alpha association 与零 alpha 处理，以及原生身份、可靠停止、成功 close/flush 和最终字节绑定。静态入口已找到，实际采集合同仍未确证；不能把现状概括为只差启动真机。

本轮没有启动真实 Houdini/husk/Nuke/WorkBuddy/HY3、模型、仿真、缓存或渲染，没有编译加载 DSO、附加调试器、发送厂商问题或改变全局配置。当前已授权的静态与软件范围已推进到上述结果。后续原生实现需要受支持的接口或实现合同；真实阶段仍受既有前置条件与具体版本、案例、路径、帧和预算约束。全 16 域、48+2 案例及原 54 行要求保持不变。

本轮[独立复核](evidence/20261016-husk-entry-current-release/review.md)、[发布结果摘要](evidence/20261016-husk-entry-current-release/release-verification.json)与[保留性核对](evidence/20261016-husk-entry-current-release/preservation.json)分别记录实际检查范围。完整 ZIP 的成员、字节和源码身份由外层 manifest 与 audit 记录，归档完整性不提升工程或 M1 状态。
