# READY13 有限复现结果

本包仅含普通软件进程和公开原生 API 的有限实验。没有启动 Houdini、Nuke、WorkBuddy、HY3、模型或渲染，没有修改 Bridge 源码或 06–12 已有证据。

## 监督状态机红例：已复现

`state-machine/result.json` 使用冻结的正式 `owned_process._supervise_owned`。替换的边界仅为软件采集结果：显式令 `process_image.observe_process` 抛出 `ProcessImageError:PROCESS_IMAGE_TOOL_FAILED`，并跳过本例无关的 writer 文件冻结。未执行原生工具，不把该注入称为原生启动警告复现。

自有普通 Python 子进程 PID 79913 先发 READY，再等待管道命令。正式监督器签入 `started.writer_process_binding_error` 后，控制线程才发送 PING；同一 PID 返回 ACK，控制线程记录 `poll() is None`，随后发送 RELEASE。子进程正常退出 0。整个过程中正式 `_signal_group` 请求次数为 0；监督器返回 0，已签 `stopped.execution_result=succeeded`、`stop_reason=null`，且 `stopped.started_sha256` 与认证过的 started payload 相符。

这直接复现了 writer 采集错误只被记录、未进入停止状态机的偏差。通过 started 事件与进程内 ACK 的先后关系证明错误后仍执行，没有用固定等待推测进程仍存活。

## 普通原生启动对照：有限结果

公开 SDK `sys/spawn.h:60` 定义 `POSIX_SPAWN_START_SUSPENDED`；SDK `posix_spawnattr_setflags.3:114–125` 明确其在用户态执行前挂起、由 SIGCONT 恢复。`native/ordinary_spawn.c` 只用该公开标志启动一个普通 Mach-O 目标。目标进入 main 后实际完成 malloc，再通过继承管道写 READY，继续等 RELEASE。

第一个目标 PID 80785 在挂起 before 及 READY after 各执行一次完整、未修改的 `observe_process`。工具 timeout 5 秒、观察 16 秒、外层 60 秒均未提高，未重试，也未忽略 stderr。`sys.settrace` 仅在正式 `_run_tool` 返回时读取其局部变量，保留每个工具的 argv、原始 stdout/stderr、rc、耗时和回收状态。

- before：`vmmap -w -interleaved -summary 80785` 返回 0，完整 stderr 450 字节，明确提示 launched-suspended 及找不到 libsystem_malloc；严格采集以 `PROCESS_IMAGE_TOOL_FAILED` 拒绝。该文本属于 pre-dyld 启动阶段，同 12 的 474 字节 pre-libSystem 文本不完全相同。
- after：真实 main/malloc READY 后，vmmap summary 与 addressed 两次调用均返回 0、stderr 为空；启动警告消失。完整观察仍在后续 lsof 主映像路径匹配处以 `PROCESS_IMAGE_AMBIGUOUS_IMAGE_VNODE` 拒绝。vmmap addressed 原始路径为 `/tmp/bridge-ready13-repro/native/ordinary_spawn`，lsof 原始路径为 `/private/tmp/bridge-ready13-repro/native/ordinary_spawn`。本实验实际 spawn 使用后者。没有归一化路径或放宽门，也没有为求绿更换路径再试。

因此，本例证实普通进程的启动状态会导致严格 vmmap 警告，并证实该目标 READY 后该警告消失；它未证明完整身份链成功，更未证明 husk 的就绪点。

## 跨进程 dyld 读门：当前采样不可用

第二个且最后一个普通 Mach-O 目标 PID 81575 沿用同一公开挂起／READY／RELEASE 事件控制，仅各调用一次 `task_read_for_pid`。原型由 Apple XNU `bsd/kern/syscalls.master:835` 核实；SDK 中 task dyld info 与 dyld prefix 布局由 native_basis 角色独立核实。本例未猜系统调用号或结构偏移。

before 和 READY after 均返回 -1、errno=1 (`EPERM`)、port=0。按失败封闭，未调用 task_info 或 mach_vm_read_overwrite。未提权、赋 entitlement、绕过或重试。调用者 Python 是目标的祖先，直接父进程是 C spawn helper；该结果仅覆盖这条实际 ownership/签名/权限路径，不能证明所有可能的直接父进程或签名配置都不可读。

两个普通 Mach-O 目标、两个 helper 均由 RELEASE 正常退出 0，helper waitpid 明确回收对应目标；原生工具 leader 均已回收。没有第 3 个原生目标。公开 API 字段存在与当前调用权限可用是不同结论，本轮未得到可用于 husk 的原生 libSystemInitialized 门。

## 建议修复触点及软件绿例条件

状态机触点是冻结 `owned_process.py:411–429` 的 `finish_start` 与 `599–613` 的采集处理。当前 `finish_start` 将错误签入 started，后续既不设置 stop_reason，也不调用已有 SIGTERM／升级／整组回收路径。`tools/run_alpha_calibration.py:418` 先等待、431 后验证是该偏差被晚发现的正式调用次序。

软件修复应使 writer collection 的错误、超时、无可信就绪／观察结果、过期结果及绑定验证失败进入已有立即停止路径；认证错误与 diagnostic 仍保留，diagnostic 不得成为 binding。停止回执应继续绑定 started，明确失败原因与失败执行结果。信号请求与“已停止”必须分离，只有 owned wait 和整组状态均成立才认证停止。不能靠 runner 等自然退出后才发现错误。

独立软件绿例至少应验证：错误一旦签入，无外部 RELEASE，仍在事件等待的同一自有 child 被请求停止并由 owned wait／整组缺席认证回收；`execution_result=failed`，返回非 0，不能是 `succeeded`。还须覆盖信号拒绝、后代仍活、采集线程迟到与取消、budget 到期、正常 binding／自然退出路径。原生采集正例应要求明确的实际就绪条件后，一次完整严格观察通过；本包 B1 after 不符合该正例，B2 权限失败不能充当就绪证明。

## 文件

- `state-machine/result.json`：时序、断言、签名认证后的 started／stopped payload、回收事实。
- `state-machine/supervisor/started.json`、`stopped.json`：软件红例原始签名封套。
- `state-machine/reproduce.py`：一次性软件状态机复现程序。
- `native/result.json`、`*-stdout.bin`、`*-stderr.bin`：第 1 个原生目标的固定 before／after 与完整工具原流。
- `native/helper.stdout.bin`：SPAWN／CONT／READY／REAP 事件。
- `native/ordinary_spawn.c`、`observe_before_after.py`：普通原生目标及采集程序。
- `native-read/result.json`、`helper.stdout.bin`、`helper.stderr.bin`：第 2 个目标的权限失败与回收事实。
- `native/remote_dyld_before_after.py`：准确原型与有限读取逻辑；本机实际失败在取得 port 阶段。
- `source_snapshot/`：本轮使用的正式源码快照。
- `manifest.json`：文件大小与 SHA-256；不包含临时软件测试签名 key。

临时 `state-machine/supervisor/receipt.key` 仅供本机独立复核，不纳入公开包或交付复制清单。
