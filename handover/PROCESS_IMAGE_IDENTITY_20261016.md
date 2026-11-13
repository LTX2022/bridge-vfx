# 可信 writer 可执行文件与进程身份接口（2026-10-16）

本轮已实现并接入生产签名链的范围是 **writer executable/process identity**：可信部署端显式冻结文件，owned supervisor 签入宿主进程锚点，私有 postframe 采集操作系统主 image 和严格祖先链，producer 与终态消费端重验原始签名启动回执。该范围不等于实际 writer 对象、颜色处理、alpha 或成功关闭合同已经补齐。

实际 husk/Houdini/Nuke 未运行，工程闭环仍 BLOCKED，全 16 域 M1 仍 NOT_READY。`render_execution_fact` 继续返回 `BLOCKED_MISSING_NATIVE_FACTS` 和空 `metadata`，Registry 继续拒绝缺失事实的产物。

## 实现与信任来源

可信配置新增可选 `writer_executable`，只接受三键 `{path, version, sha256}`。`path` 必须是操作者明确选择的绝对无链接文件路径，`version` 必须与明确的 Houdini 部署标签相同，`sha256` 必须匹配实际读取的字节。不自动查找 husk，不从相邻 hython 或文件名推断版本，不接受调用者提交的 `verified` 或预制冻结对象。版本是可信部署标签，不是从程序自行发现的版本。

配置工具新增配对的 `--husk-executable` / `--husk-sha256`，继续使用显式 `--houdini-version`。生成器只验证文件、写新配置，不启动文件。

`freeze_executable` 返回包含完整 stat 与摘要的 `bridge.process-image.executable/1`。部署指纹、task launcher、runner 和 supervisor 都传递并比较同一完整冻结对象。ready/health 和 supervisor identity 使用规范 JSON 摘要绑定它。每一处重新 freeze 均比较完整对象，既不只比较路径，也不只比较摘要。

supervisor 在原始 HMAC 签名 `started` 中写入 `writer_process_binding`，其成员为 `expected_executable` 和实际 owned child 的 `host_anchor`。采集失败签入 `writer_process_binding_error`，不能生成有效 binding，且必须继续承担已创建 child 的监督责任。writer 启动等待上限为 25 秒，未配置 writer 的旧任务仍为 10 秒。

插件启动时重新 freeze，重验原始 signed started，并观察自身进程与 signed anchor 完全一致；生产控制端还重验 ready、health、expected 对象、摘要和 anchor PID。旧任务没有 writer 配置时不自动升级为已认证。

## 操作系统采集及资源界限

当前采集实现仅支持 macOS；其他平台明确拒绝。`observe_process` 使用固定绝对系统工具路径：`/bin/ps`、`/usr/bin/vmmap`、`/usr/sbin/lsof`。主 image 由 vmmap 的主 Load Address 和唯一 `__TEXT` 映射定位，并用 lsof txt 的 device/inode/path 与持有文件描述符的 fstat/实际 SHA 对照。ps 仅提供 PID、PPID、出生时间和存活交叉检查，不采用进程显示名、argv[0] 或 sys.executable 作为主 image 证据。

单次观察按 ps → vmmap → lsof → fd/hash → lsof → vmmap → ps 交叉检查。vmmap 可能对仍活着的普通 Python 使用自动 corpse 快照；报告模式自身不证明存活，仍要求前后进程、出生、映射和文件身份全部一致。

`capture_ancestry` 只允许采集当前进程，沿有限祖先链到签名宿主锚点，并反向重新观察整条链。默认工具上限 5 秒、freeze 5 秒、单次 observe 16 秒、capture 总计 60 秒；最大 8 个节点，单 image 512 MiB，stdout 4 MiB，stderr 64 KiB。权限拒绝、工具失败、歧义、超时、漂移和不支持平台均拒绝。

三个采集 API 提供仅关键字可选 `read_budget=None`。实际 postframe 传入既有操作级持久 `FileReadBudget`：每次 `os.read` 前预留最大请求字节，包含 EOF 探读；reserve 后再次检查同一 deadline；所有祖先和两轮观察共用一个预算，不复制、不重置、不退款。既有 32 MiB aggregate 上限没有放宽。因此文件较大、祖先较多或前序读取已耗预算时可能拒绝，不能据软件正例推断真实 husk 必定可采集。

`validate_process_proof` 只做离线结构与外部 expected/anchor 一致性检查，不读取 OS、不生成 verified/AVAILABLE，也不认证任意调用者提交的 JSON。真正采纳仍依赖私有 postframe HMAC、冻结 producer、原始 signed started 和终态认证。

## 正式回执接线与拒绝语义

`render_writer_frame` 从冻结 producer 与原始 signed started 取 binding，放入私有 context，并绑定当前 `process_image` 源文件摘要。postframe 采集 proof 后与原观察一起 HMAC 认证。`validate_writer_observation` 必须接收外部冻结的 host identity 与 supervisor binding，并重新读取原始 signed started；单独提交 proof、替换 context、重摘要或重签不一致结构都不能成为有效生产事实。

认证成功仅移除 `WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED`。以下缺项继续保留：

- 实际 writer/OCIO processor 实例与生命周期及 config/context/file-rule/looks/LUT。
- 实际 product/AOV 处理覆盖。
- renderer filter、denoise、颜色、alpha、编码及 writer 内部转换的完整已执行顺序。
- beauty alpha association 和零 alpha RGB 行为。
- write/flush/close 成功、错误传播，以及身份、可靠停止与最终字节的完整联合证明。

因此 AVAILABLE → 正式登记 → Nuke 真实消费仍 BLOCKED，不能把本轮接口实现、Python 安装或普通进程测试当作生产接收。

## 定向验证与独立复核修复

独立复核确认并关闭了一个新增 P2：原先 writer refreeze/OS observation 同步发生在监督循环前，短 session、取消和磁盘检查会被阻塞。最终版把采集放入有界线程，主监督持续检查预算并独占签发一次 started；超限先停止 child，再签 binding error，迟到结果不能补入 anchor。独立复现从修复前约 0.533 秒停止、0.5 秒 child 仍存活，变为约 0.125 秒返回、0.5 秒 child 已退出，迟到 binding 未被采纳，**P2 CLOSED**。

固定解释器为 Python 3.11.16，`TMPDIR=/private/tmp`，关闭用户 site 与字节码写入。最终冻结源码的受影响组实际运行 **80 项：76 通过、4 个 Windows 专用测试跳过，0 失败、0 错误，21.244 秒**。含 deployment 24 项，以及签名回执、新旧 writer/output、任务生命周期、owned supervision 和生产配置守卫。作者另跑 45 项、独立审查另跑 37 项的结果作为复核证据，不累计为额外唯一测试。

- 最终受影响组：[supervision-final.txt](evidence/20261016-process-image-identity/supervision-final.txt)。
- 未改动的 runtime 26 项已在此前稳定 63 项组中全部通过；该文件及其测试的 SHA 此后未变，保留已有覆盖，不重复运行真实系统工具。
- 首轮构建 14 步中 13 步通过，三 Skill 共同的生命周期 closure 失败定位到 verifier argv 摘要默认 ASCII 转义与 runtime UTF-8 canonical 不同。仅修复该工具一行规范化；既有集成回归使用中文空格路径和 runtime canonical 产生摘要，并继续拒绝 foreign worker。修复前同用例实际 FAIL，修复后 verifier **16/16 通过，1.172 秒**。首轮失败目录及日志保留，不能把它当成功 release。
- 原始红绿日志：[lifecycle-verifier-unicode-red.txt](evidence/20261016-process-image-identity/lifecycle-verifier-unicode-red.txt)、[lifecycle-verifier-final.txt](evidence/20261016-process-image-identity/lifecycle-verifier-final.txt)。
- 此次两组最终命令合计 96 项，92 通过、4 跳过。连同 SHA 未变的 runtime 26 项，去重软件覆盖 122 项；新建测试方法 56 项（runtime 26、deployment 24、receipt 6），既有 verifier 方法为加强覆盖，没有新增测试数。
- 修复前 102 项（98 通过、4 跳过）保留在 `verification-prefixed.json` 及原两组日志中，不充当修复后的受影响验收。完整命令、18 个源码/测试/镜像 SHA、阶段和限制见 [verification.json](evidence/20261016-process-image-identity/verification.json)。

runtime 正例确实启动了普通 Python 父子与 `/bin/sleep`，包含伪造 argv[0] 仍识别实际 image、父进程离线验证、错误 expected 拒绝。部署/监督测试使用普通 Python child，进程 observe 在该组为显式 mock；receipt 集成只在 OS/native API 边界使用替身，并执行真实 HMAC/原始 signed start/producer/终态/Registry 拒绝代码。插件 helper 通过 AST 提取测试，没有导入 hou/native。

先前夹具曾不必要观察外部 shell 而被权限拒绝；修正夹具为 owned 进程，未放宽生产规则。默认 `/var` 临时路径别名曾触发已有链接守卫，使用 `/private/tmp`。既有父先退出用例曾一次触发其 5 秒测试等待上限，单独及后续组合通过，未修改既有测试。初次失败不隐藏，也不计为最终源码失败。

## 独立复核、安装与交付

Bugbot agent 类型在本环境不可用；本轮采用实际 general-purpose 独立只读复核，不声称执行过 Bugbot。最终复核结论、修复与范围以 [review.md](evidence/20261016-process-image-identity/review.md) 为准。

controller-entry 的五份受影响镜像在同步前核对：均与修改前 baseline 中镜像一致，且 baseline 镜像与当时源码一致，没有覆盖其他人的独有修改。同步后与当前源码逐字节一致。

本轮成功 release 为 `outputs/process-identity-release-20261016-796h9zrr`。四 wheel 当前源码 payload、隔离安装、`pip check`、四模块导入、三 CLI help、三类 Skill 构建及安装/升级/失败回滚/rollback/registration/设置保留/uninstall/依赖闭包软件生命周期均通过，**14/14 步骤 exit 0**。三类 Skill 各 8 项生命周期检查和 18 项 closure 子检查全部 true。生命周期 35.496 秒，`source_unchanged=true`、`readonly_files=true`；没有触碰真实宿主安装，没有保留签名密钥或可恢复运行目录。

完整 release seal 绑定 797 个成员、31,866,610 payload bytes，manifest 自身 231,397 字节，SHA256 `42753d7ea80d0287904e23c854bd89dcc7a1c0f068a8694be9034cd32efa540d`。768 份无密钥 raw 审计文件及索引的 exact 集合和逐 SHA 已核验。`skill-lifecycle.log` 为空，成功依据是完整 JSON、raw 和 manifest，不是空日志。[release-binding.json](evidence/20261016-process-image-identity/release-binding.json) 绑定 result/steps/lifecycle/Skill manifest 的完整身份与失败尝试。

首轮 `84n_bjlz` 因 Unicode canonical 漏配失败；第二轮 `0fgojv8h` 的三 Skill 功能检查均通过，但主控并行写入 handover 触发 `source_unchanged=false`，仍整体失败。两失败目录及原始审计原字节保留；第三轮冻结全部 build_id 覆盖范围后通过。后续只补最终 handover 证据，不改变生产 payload；保留证明和归档再绑定最终文档，不能把运行窗口的 build_id 误称为后续所有文档的当前指纹。

完整新交付路径为 `/Users/user/Desktop/Bridge-S06原生定义补采/Bridge-完整源码与进程身份接口-20261016.zip`，由 `outputs/process-identity-handoff-20261016/package_archive.py` 在最终证据与保留证明齐备后排他创建，随后 `verify_archive.py` 独立读回。交付包含完整选定当前源码、四 wheel、三类 Skill、完整成功 release 和无密钥 raw 审计；whole ZIP SHA 在相邻 `.sha256`，最终读回结果在 handoff 的 `final-verification.json`。此报告不自包含尚未创建的 ZIP hash，防止归档自引用。历史七份 ZIP 保留原字节，不递归嵌套，也不把旧安装包当本轮当前包。

修改前 baseline 为 `bridge.process-identity-baseline/1`，选定文件 3336、排除 880，SHA-256 `9daaa5890800673e4b71e55a799eb94b96130ecd6f3ca82596606061534b401e`。保留检查见 [preservation.json](evidence/20261016-process-image-identity/preservation.json)。该 baseline 是已过滤的源码归档范围，不宣称涵盖私有运行状态或被排除的商业原件。

## 接续边界

本轮已从“无可信 husk 文件与进程绑定”推进到接入正式签名链的局部生产接口。下一实际输入仍是同 build 下受支持的实际 writer 交接、实际处理与成功关闭合同；没有这些依据时继续拒绝 AVAILABLE，不猜原生 API，不增加接收 verified 事实的入口。

真实 husk/Houdini/Nuke、WorkBuddy/HY3、模型、仿真、缓存、渲染、原生模块/DSO 均 NOT_RUN；本轮未获得新的真实运行授权，未发送厂商问题，未改原 Desktop 主工程，未自动提交或推送。活动顺序仍为工程闭环 → 反馈/恢复 → HY3 → 复用，全 16 域、48+2 案例与原 54 行验收保持原要求。
