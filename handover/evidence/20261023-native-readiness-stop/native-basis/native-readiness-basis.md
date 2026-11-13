# ready13 原生就绪接口依据

结论：公开 `dyld_all_image_infos.libSystemInitialized` 是有实际赋值语义的 libSystem 阶段信号；不能只凭进程已 spawn/exec、映像已映射或工具退出 0 推断该阶段完成。唯一普通 Mach-O 实验中，Python 祖先读取其 C helper 所生目标的 task_read_for_pid 在挂起前态与 main+malloc READY 后态均被 EPERM 拒绝，因而没有进入 task_info/read。当前 generic gate 没有可用性阳性证据，不能宣称软件修复成立。该结果不排除 direct-parent/签名/entitlement 不同条件。本角色没有启动或采样任何目标。

## 本轮范围

只读 `/Users/user/Documents/Code_Project/Bridge/AGENTS.md`、12 结果报告、当前运行时/宿主源码、本机 SDK/手册及精确安装文档。只写本目录。没有修改仓库、06–12、Desktop 工程，没有启动 Houdini、Nuke、WorkBuddy/HY3、模型或目标进程。唯一编译调用为 `clang -fsyntax-only`，没有产出或执行目标二进制。

本机静态信息：macOS 15.8.1 / 24H32；SDK 13.3。`what /usr/lib/dyld` 为 dyld-1286.10；kernel 为 xnu-11417.140.69.712.69。官方 dyld 依据使用相同 dyld-1286.10 tag；XNU 源码只用于核原型/权限路径参考，未声称匹配当前 kernel 补丁后缀。

## 公开 SDK：准确位置及布局

SDK 根：`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`。

| 事实 | 源文件与行号 |
| --- | --- |
| libSystemInitialized 从 version 2 起存在 | `usr/include/mach-o/dyld_images.h:122–133` |
| TASK_DYLD_INFO = 17；addr/size/format；32/64 format | `usr/include/mach/task_info.h:260–272` |
| 远端读函数需要 vm_map_read_t | `usr/include/mach/mach_vm.h:191–198` |
| task_read_t 远端 dyld images 和通知权限类型 | `usr/include/mach/task.defs:495–497,543–545` |
| task_for_pid 可见声明 | `usr/include/mach/mach_traps.h:280–283` |
| task_read_for_pid syscall 编号 539 | `usr/include/sys/syscall.h:579` |
| BSD birth 秒/微秒字段 | `usr/include/sys/proc_info.h:81–82` |
| proc_pidinfo 公开声明 | `usr/include/libproc.h:96` |

`task_read_for_pid` 本 SDK 无函数原型声明；libSystem.tbd 导出符号。Apple 官方 syscalls.master 给出准确 C 原型：`int task_read_for_pid(mach_port_name_t target_tport, int pid, mach_port_name_t *t)`。它是 BSD int/errno 接口，不应当成 kern_return_t trap 错误解释，也不能把导出符号等同完整公开 API 支持合同。

编译期断言在 `sdk-layout.c`，结果 `sdk-layout-result.json`，完整编译器布局 `sdk-layout.stdout.txt`：

| 64 位公开前缀字段 | 字节偏移/长度 |
| --- | --- |
| version | 0 / 4 |
| infoArrayCount | 4 / 4 |
| infoArray | 8 / 8 |
| notification | 16 / 8 |
| processDetachedFromSharedRegion | 24 / 1 |
| libSystemInitialized | 25 / 1 |
| dyldImageLoadAddress | 32 / 8 |

`task_dyld_info` 是 20 字节、align 4、TASK_DYLD_INFO_COUNT=5：addr offset 0/u64，size offset 8/u64，format offset 16/int。64 位 all-image-info 最小只需读 26 字节到 readiness 位；不需要解引用 infoArray、远端路径或画像列表。读取前须核 TASK_DYLD_ALL_IMAGE_INFO_64、version >= 2、地址和长度合法，读取返回值和 outsize 精确成立，且 bool 字节为规范 0/1。32 位布局不在本次适配证明中。

## 就绪位实际语义

Apple 与本机相同 dyld-1286.10 项目源码中，`DyldAPIs.cpp:3676–3682` 先执行 libSystem loader initializer，再调用外部可见状态 setter；`ExternallyViewableState.cpp:399–405` 将公开 `_allImageInfo->libSystemInitialized` 写成 true。这支持“libSystem initializer 已完成”的精确判断；它不声明所有宿主初始化/插件加载/作业已就绪，更不证明 writer 映像身份。链接保存在 `official-source-references.json`。

跨进程读取的可行性不是由字段存在推得。Apple XNU 参考实现会检查凭据、MAC/taskgated 等路径；子进程属于同一用户/由调用者启动并非 SDK 无条件授权承诺。权限被拒绝应保留原始错误并失败关闭；不得注入、调试附加、提权或绕过。普通 Mach-O 读取成功也不能直接升级为 SideFX/Foundry 签名宿主权限通过。

## 为什么不优先 dyld-process 事件接口

本机 public mach-o 头只有 dyld.h/dyld_images.h，未安装 dyld_introspection.h/dyld_process_info.h。libdyld.tbd 存在 remote-process 导出不代表 public 可用性。官方 dyld_introspection.h 将 remote process create 和 notification 标记 SPI，并仍要求 task_read_t。MAIN event 在 main 之前；BEFORE_INITIALIZERS 更早，不能据此证明 libSystem 完成。它们不解决当前权限问题，也比只读公开前缀引入更多依赖。`_dyld_register_func_for_add_image` 是本进程 image 回调，不是无需目标配合的远端就绪通知。

## 确定 pre-dyld 普通进程反例

公开 `sys/spawn.h:55–60` 定义 Apple 扩展 `POSIX_SPAWN_START_SUSPENDED = 0x0080`。本机手册 `usr/share/man/man3/posix_spawnattr_setflags.3:114–125` 明确 child 在用户态开始前暂停，支持 early dyld 观察，SIGCONT 才恢复。因此可在唯一普通目标实验中先读取/采样该状态，然后恢复到自有 main() 的 pipe-ready 后读取/采样；它避免“刚 spawn 大概还没就绪”的时序猜测。所有目标与采样由 repro 唯一执行。

## 既有宿主和 H21 hook

Hython 当前 `task_host.py:274–303` 已有 launch_nonce/PID 绑定与 host.ready 检查。addon `task_host_serve:16218–16281` 已进入 hou runtime、启动 bridge 后才 ready，但 `16277` 先调用 `_task_writer_process_identity`；该函数 `16195–16202` 等监督器 signed started 并 observe self。因此直接用当前 host.ready 来放行监督器首次 observe 会形成循环。不要这样接。

Nuke `task_host_worker.py:15–53` 在 import nuke、建节点、server.start 后写 ready；launcher `task_host.py:195–209` 验 PID/完整 expected identity 并进行现有健康握手。这是现成宿主级 ready，但 alpha Nuke 脚本与普通 task host 路由须分别确认，不能拿它覆盖 alpha husk。

当前 alpha H21 命令在 `tools/run_alpha_calibration.py:214–215`，没有 ready hook/通道。精确 H21.0.631 安装 `ref.zip -> utils/husk.txt` 已静态提取为 `h21-husk.txt`，184–187 行支持 `--prerender-script`：USD 已加载，settings 读取/渲染前，products partition 也在脚本之后。H21 文档没有 `--postload-script`；不能把 H22 当前文档中的选项套给 H21。archive/member 哈希在 `h21-husk-capture.json`。

文档提供 stage/husk_command 上下文，支持同宿主解释器的设计推断，但本轮未取得同 PID 运行事实。若远端公开前缀方案实际不可用，候选最小协作路径是冻结的纯 stdlib prerender hook 发送一次 existing nonce + expected child PID 的控制事件，并在绑定成功前不返回；必须 `os.getpid() == supervised child PID`，不能由子解释器/副进程事件放行。事件只决定开始采集，不产生身份 authority，不创建身份 schema。只使用 stdlib，不调用 hou/Houdini 库；当前官方许可 FAQ 说明调用这些库可能额外 checkout Engine/Core/FX。hook 同 PID、H21 实际时序、权限和 deadline 均保留真实验证待办，不能声称已通过。

## 最小适配结论

公开前缀 generic gate 仍是代码最少的候选，但本次实际读取被拒绝，不能作为已证可用方案。若后续在另行批准的条件下证实 task_read + task_info + 26-byte read 可用，可在现有 process_image/collector 内实现小型读取 gate；无需新增原生 runtime 模块或逐 DCC hook。gate 只在现有首次 observe 之前等待公开位，不替代 ps、vmmap、两次 lsof vnode、stat/hash、supervisor anchor，不放宽 stderr/nonzero/timeout 规则。准确位置是 `process_image._observe:460` 的首个 ps 之后、`461` 的首个 vmmap 之前，使用 `459` 已建立的同一 deadline；不能先在 collector 等待，再调用 `observe_process:487` 重新领取 16 秒。它必须共享现有 collection 22 秒和 observe 16 秒剩余，工具 5 秒、capture 60 秒不增加，取消后不得再启动采集。任何异常仍回到既有立即停止失败路径。

若实际读权被拒绝，报告该限制并转入官方 host hook 控制事件方案的软件实现评审；不要仅因权限类型推定不可用，也不要用固定启动延迟或重试 vmmap 规避。普通自有目标成功和软件 gate 通过，仍只构成软件/原生 API 证据，真实 H21/Nuke 必须另行授权后才可验。

## 唯一实验回执分层

已只读核对 repro 保存的两个 result.json，并复制原字节到本目录 `repro-native-result.json`、`repro-native-read-result.json`，复制哈希在 `repro-result-capture.json`。所有目标/工具由 repro 角色执行，本角色仅核回执。

- B1 / PID 80785：START_SUSPENDED 前态 vmmap rc 0、完整 stderr 450 字节，严格门拒绝。恢复到 main-entered + malloc-completed 的一次 READY 后，两次 vmmap 均 stderr 0；完整 observe 因 `/tmp` 与 `/private/tmp` 路径差异在 lsof 映像路径门拒绝，不能称 identity PASS，也不在本任务顺手修复路径规则。
- B2 / PID 81575：同一自有 Mach-O 第二且最后目标；Python 为祖先进程，C helper 为直接父进程。before/after 各一次 task_read_for_pid 都是 return -1、errno 1/EPERM、port 0；严格停止该 API 链，没有 task_info/远端读取、没有重试或权限绕过。不能把这两个拒绝泛化成 direct-parent 或所有签名宿主必然被拒绝。
- 两个目标/helper 均正常退出 0、wait 回收，目标总额已封顶。后态 vmmap 没有警告只支持本次普通目标状态改变，不证明 DCC 真实 writer 身份，也不完成正式全链。

因此本轮可供实现者采用的是：保留失败关闭与立即停止修复；原生 ready 的实际接点仍须在 generic 读权和官方 prerender 控制事件之间作明确评审决定。若采用 H21 hook，最小 stdlib 事件不需要新原生 runtime 模块，但同 PID/时长/反循环/渲染前阻塞必须以软件测试加后续另行授权真实验证分层收口。
