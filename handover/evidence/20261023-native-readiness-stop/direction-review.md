# Bridge ready13 最小整改方向（只读审查）

当前判定：**fail-stop 与合作式 ready 门的软件实现 GO；真实 DCC 运行 NO_GO。** 最终实施合同以同目录 `cooperative-gate-contract.md` 为准；本报告保留因果链和验收边界。本报告不授权真实启动，不解除 12 的失败封闭，不改变原 06–12 原件。

## 已确认的因果链

仓库 `/Users/user/Documents/Code_Project/Bridge`，本报告未修改仓库源码、旧冻结范围或输出。`handover/H21_LIVE_12_RESULT_20261023.md` 与原始 `writer-binding-stderr.txt` 一致：首次 vmmap summary 返回 0，但 stderr 为 474 字节，目标 dyld 已初始化而 libSystem 尚未完成启动。现行 `_run_tool` 非空 stderr 拒绝是正确的，不能据 stdout 或退出 0 认身份通过。

实际调用链为：

1. `tools/run_alpha_calibration.py:414` 调用 `owned_process.launch(..., writer_executable=expected)`。
2. `owned_process.supervise:379` 直接 Popen 自有业务进程，随后 `_supervise_owned:405` 启动后台 collector。
3. `_start_writer_collection:272` 重新冻结已指定 executable，`:275` 没有 ready 同步就调用 `observe_process(pid)`。
4. `process_image._observe:460–471` 执行完整 ps→vmmap summary→原 Load Address 定点 vmmap→lsof→stat/hash→lsof→vmmap→ps；没有允许用预期路径或进程名代替 OS 主映像。
5. `_start_writer_collection:281–289` 将采集错误与有界原始诊断放入队列。
6. `_supervise_owned.finish_start:411–429` 只把错误签入 `started`，没有设置停止原因；`:599–609` 先处理已有 stop_reason 后才取 collector 结果，错误不会触发停止。
7. alpha runner `:419` 先等待停止；`:431` 才验证完整 binding，因此 12 中当前 husk 继续自然运行约 12.5 秒。

独立状态机红例 `/private/tmp/bridge-ready13-repro/state-machine/result.json` 使用原 `owned_process.py` 快照并显式注入 collector 异常，确认：同 PID 79913 在错误已签 started 后仍 PING/ACK，信号请求为 0，人工 RELEASE 后自然 exit 0，最终 `execution_result=succeeded`、`stop_reason=null`。这是软件状态机复现，不冒充原生 warning 复现。

## 不变的接口与限额

| 项 | 当前源码值 / 必须保持 |
| --- | --- |
| tool / freeze / observe / ancestry capture | 5 / 5 / 16 / 60 秒 |
| writer collection 总限 | **22 秒**，现行源码不是 18 秒 |
| 真实范围 | 8 次 / 每项 120 秒 / 累计 600 秒 / 512 MiB / 1 heavy / 0 retry |
| 身份与认证 | 双观测、PID/PPID/birth、Load Address、双 lsof vnode、无链接 stat/hash/readback、预期 image、HMAC started→stopped 链全部保留 |
| 严格错误门 | 非空 stderr、非 0、超时、无法观测、身份变化继续 fail closed |

## 唯一实现者的最小边界

### 就绪同步

同步应放在现有 writer collector 中，位于 refreeze 成功之后、第一次完整 `observe_process(pid)` 之前；不应放在 alpha runner 的 `handle.wait()` 之后。就绪事实只允许解除“开始严格采集”的门，不构造、不修复或替代 writer binding。

整个 ready 等待与后续采集都受既有 collection/session deadline 和 cancelled 约束，不增加等待总额，不重开 observe deadline 求绿；collector 迟到结果必须继续丢弃。ready 过程中正常的 not-yet-ready 状态可以继续观察同一事实，但任何不可读、未知、结构错误、PID/birth 变化、退出或总限耗尽都是失败；不得把失败的 vmmap 再跑一次当作 ready 等待。

原生依据代理确认：公开 Apple SDK 的 `dyld_all_image_infos.libSystemInitialized` 是精确信号，读取目标却需要 task_read_t / vm_map_read_t；“自有子进程”不自动证明有读取权限，也不自动证明不可用。可在用户允许的普通自有原生目标上做一次有依据的 task-read 可用性 probe；按实际回执裁决，不猜测可用或不可用。现有 hython `host.ready` 又先等待 signed started 和自身 image observe，直接拿来 gate 会形成循环。尚未确认可用、无循环的就绪接口前，不能把精确字段存在当成实施已就绪。

另一候选的准确版本依据已经返回：H21 安装文档 `/private/tmp/bridge-ready13-native-basis/h21-husk.txt:184` 支持 `--prerender-script`，在 USD 加载后、读取 settings/开始渲染和 products partition 前执行；H21 没有 `--postload-script`，不能套用 H22。若最终采用此 hook，脚本限 stdlib，必须实际确认脚本 `os.getpid()` 等于监督器 child PID；事件只证明到达 ready 代码点，并在完整 binding 通过前阻止 hook 返回。其同 PID 与时长尚为 PENDING，不能仅凭文档宣称已验证 DCC。

### 失败即停

collector 结果为 error、ready 失败、collection timeout 或采集期间 child exited 时，都应在监督线程本轮进入已有停止流：设置不可清除的第一 stop_reason，立即请求自有组 SIGTERM；保留现有 2 秒宽限后 SIGKILL、等待 leader、证明整组 absence，再签 stopped 和完成 native scope ticket。不得等待业务自然结束才解释错误，不得把 supervisor 能证明 stopped 误写为业务 succeeded。

取 collector 结果及错误判定必须位于同轮 stop dispatch 之前，或者错误处理直接调用同一现有 stop helper。当前先 dispatch 再 finish_start 的顺序必须修正。错误诊断签写失败也不能阻断停止请求；无法签出可信 stopped 时仍是 UNKNOWN/失败，不能伪造已停止。

`started` 应保留原 `writer_process_binding_error` 和有界诊断；`stopped` 必须绑定原 started 哈希，具有非空 stop_reason、失败 execution_result，`execution_returncode` 不得返回 0，即使业务在 TERM 竞态中自然返回 0。保留原 signal-denied 与未知后代处理。

alpha runner 继续先取得认证整组 stopped，再判定产物/下一次派发。新 fail-stop 将使 `run_alpha_calibration.py:428` 的 generic execution 错误先出现，需在认证原 started/stopped/identity 后保留已签 writer 原因，避免隐藏 `PROCESS_IMAGE_TOOL_FAILED`；不能为保留原因而绕过非零执行门。`alpha-output` 和 Nuke 第二启动仍不得产生。

生产主修改应限 `process_image.py`（已被证实的 ready 原语及边界）、`owned_process.py`（同 collector 同监督器接入）、必要的 alpha 原因传播，并同步现有 controller client 镜像。若选择需要 husk 原生 hook 的候选，还必须以官方同 PID 生命周期依据和现有正式命令的最小冻结变更为前提；不能另建 launcher、依赖启动 wrapper 或使用 DCC/model 替身宣称真实通过。

## 有限验证与准入

先冻结独立复现原件，再由唯一实现者改代码；方向和独立审查者不参与对应实现。只需覆盖实际风险：

1. 原生对照证据：同一个自有普通 Mach-O 子进程，就绪前一次、独立 ready 事件后一次；保留完整 argv/rc/stdout/stderr、同 PID 与时间顺序。不得真实启动 DCC。C main READY 对该 C 样本成立，不自动成为 husk 的就绪事实。
2. ready 门：未到达 ready 时完整 observe 调用数为 0；到达后仅执行原严格采集；读权拒绝/未知/格式错/出生变化/取消/超时均不调用或不接受采集。
3. 错误即停：复用同 PID PING/ACK 红例为负向回归，发生已签 collector 错误后无人工 release 也必须进入 TERM；整组停止且 failed、原 cause/HMAC 留存，第二 host 未派发。
4. 保留取消、session/disk/native-scope 超限、慢 freeze/observe、晚结果丢弃、拒绝信号、后代未停、正常成功等已有覆盖。只更新固化错误行为的旧断言；不删除独有故障。
5. 核对 controller 镜像及源码身份；仅在定向通过后跑既有完整无模型软件链。软件替身与原生普通进程层分开报告，真实工程/M1/HY3/视觉/生产仍未通过。

必须修改的旧断言包括 `test_owned_process_supervisor.py:93`、`test_writer_process_deployment.py:328` 的“采集失败后 supervisor 返回 0”，以及 `:530` 的“collection timeout 后 child 仍存活”。其余正常路径和原始严格门保留。

分阶段裁决：fail-stop 已有独立红例和精确调用链，**现在可由唯一实现者先修，不等待 ready 候选定案**。ready 的 GO 条件为独立依据明确且当前实际 probe/同 PID 证据成立；不能以 task_read 有权限要求单独判为不可实施。完整新候选仍须 ready 门、fail-stop、严格身份及已有故障回归均通过，并获双独立审查认可后重新冻结。当前无新真实范围授权，故真实运行始终 NO_GO；12 不可续跑。

## 阅读版本

| 文件 | SHA-256 |
| --- | --- |
| packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py | abb503b7faf3906feaa2e4fdf541bb166a66d7d29bc1e30ee304c8b7d0c9abf2 |
| packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py | 1939887ccec25a2cc1431cb319683886d593cda52287ad52e8f7c1d32ecf3c09 |
| tools/run_alpha_calibration.py | c2f94788509afcab1125d830b6e4c608becbe51fe11cba0b4f5146fff8037fe6 |
| packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py | 26cb5e1c87e63ca131eb574e1923d4fc4c106fbcae685f2a5598492b9d2eda43 |

历史上下文仅用于保留身份强度和验收边界；当前结论来自当前源码、12 原件与本轮独立红例。MemHub 查询 request 80a68ba9-33c7-4dd7-b01c-c4a3b5ef4cf1 为部分返回，采用的 12 轮历史 note 为 9467935f-c6a1-49e0-b596-e9a964ee2d0f（evidence d8d51b04-c1b1-5acb-ab57-edb51301d266），并已由当前报告核对。
