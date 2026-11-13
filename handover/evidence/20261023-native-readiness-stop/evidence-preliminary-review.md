# READY13 独立证据与边界初审

结论：红例归因成立；原生实验的有限结论成立；可信同 PID ready 控制事件可进入软件实现评审。当前没有对未稳定源码、软件绿例或真实 H21/Nuke 作出 GO。

本角色只读仓库、已存复现回执及本机 SDK/安装文档，只写本目录。未运行目标、原生采集、DCC、模型或渲染，未改源码或原件。当前授权仅覆盖软件修复与必要的软件验证。

## 独立核验结果

`preflight-checks.json` 保存本角色直接计算的核验结果。

- `/private/tmp/bridge-ready13-repro/manifest.json` 列出的 77 个文件全部存在，大小和 SHA-256 均相符；receipt.key 在排除清单中。没有复制或输出 key。
- `handover/evidence/20261023-native-readiness-stop/originals-before.json` 基线 SHA-256 为 `f851f4df31c19349ad6f53fea956614f7b28a35b89e5bb561a1c69114adb5b0e`，06–12 共 1457 个原件全部存在且大小、SHA-256 均相符。
- 软件红例的原始 started/stopped 封套 HMAC 均有效，payload 与 result.json 一致；identity、PID、命令摘要及 stopped.started_sha256 一致。
- 红例冻结 `owned_process.py` SHA-256 为 `1939887ccec25a2cc1431cb319683886d593cda52287ad52e8f7c1d32ecf3c09`，与 preserved implementation/before 原文件完全相同，`_supervise_owned` 的 AST 亦相同。

## 红例归因

A 的边界明确：替换 `observe_process` 的返回边界为显式 `ProcessImageError:PROCESS_IMAGE_TOOL_FAILED`，并跳过该例无关的 writer 文件冻结；未替换正式 `_supervise_owned`，未运行原生工具。因此它是正式监督状态机的 collector 错误处理复现，不能称为原生 vmmap 启动警告复现。

事件顺序为 child-ready → signed-started(error) → 同 PID ACK → controller 观察 poll=None → RELEASE → natural 0 → signed-stopped。签入错误至 ACK 相隔 108584 ns，ACK 在外部 RELEASE 之前，整个 signals 数组为空。stopped.execution_result=succeeded、stop_reason=null，监督器返回 0。这足以证明采集错误没有触发停止，且错误之后该进程仍执行；不依赖固定等待推断进程存活。

冻结实现的 `finish_start` 只写入错误并签 started；监督循环没有把该写入转换为 stop_reason。在错误已签入的这条路径上，真实 TERM 路径未被请求，是最小且直接的因果缺陷。不能仅在 runner 自然退出后的回执校验层修补结果。

## 原生实验可支持的结论

| 实验 | 已成立 | 尚未成立 |
| --- | --- | --- |
| B1 普通 Mach-O suspended → READY | 前态 vmmap rc=0、stderr 450 字节仍被严格拒绝；main+malloc 的同 PID READY 后两次 vmmap stderr 均为空；工具 leader 均回收 | after 完整 observe 在 lsof 主映像路径门因 `/tmp` 与 `/private/tmp` 别名拒绝，未取得 writer identity PASS；不是 H21/husk 就绪证明 |
| B2 第二且最后普通 Mach-O | before/after task_read_for_pid 均 return=-1、errno=EPERM、port=0；API 链在取得 port 前失败关闭；目标/helper 正常 0 并 wait 回收 | 没有 task_info、远端读取或 libSystemInitialized 阳性；不能把本祖先/helper ownership 路径的 EPERM 泛化成 direct-parent 或所有签名宿主都不可读 |
| 安装文档/SDK | 本机公开结构含 libSystemInitialized；START_SUSPENDED 手册支持用户态执行前挂起；H21.0.631 静态文档确实支持 prerender-script 且早于 settings/read/render | 字段存在不等于读权限可用；文档支持脚本时序设计，未证明脚本实际与监督 child 同 PID，也未证明真实 DCC 全链 |

两个普通原生目标额度已封顶。不应为获得绿例再采样、不应顺手归一化 B1 路径门，不应提权、绕过或重试 B2 权限。

## ready 控制事件的软件验收门

1. 事件只释放一次 strict observe 的调度；它不能签发或修补 host identity、writer identity、binding，也不能单独产生 READY/PASS。模型输出、调用者布尔、文件存在、spawn/exec 事实都不构成可信 ready。
2. 事件需复用 owned_process 的可信签名/nonce 体系，并与本次 launch 的 task/operation/nonce、监督 child PID、预期 argv 摘要和事件种类绑定。PID 必须来自 hook 内 `os.getpid()`；副进程、陈旧 nonce、其他 PID、其他 argv、篡改、重复和过期事件均不得放行。
3. hook 必须在文档规定的 render 前阶段阻塞，直到监督器完成既有严格 writer binding；失败或超时不得返回继续渲染。不得复用当前 host.ready 形成等待 started/observe 的循环。
4. 时间门须从本次首次等待/观察起建立一个观察 deadline，ready 等待和随后观察共享既有 16 秒剩余时间，同时受 22 秒 collection/session budget 约束。不得先等新 budget 再调用领取完整 16 秒；工具 5 秒和 capture 60 秒不得提高。
5. 取消、collection 超时、ready 无可信结果、过期结果、采集异常、无效 binding 都应进入立即停止路径。不能靠 runner 在自然结束后补判失败。
6. 原有 pre/post ps、vmmap 映像/地址、两次 lsof vnode、stat/hash、supervisor anchor 以及 stderr/nonzero/timeout 的严格门必须保留；diagnostic 仍只是诊断。

## 失败停止与最终候选验收门

- 独立绿例必须让同一自有 child 在事件处持续等待，采集失败由监督器发现后当轮请求 TERM；不允许外部 RELEASE 或自然退出代替停止。记录失败被发现、信号请求、owned wait 和整组状态的时间/事实。
- 可信停止与执行失败分开：仅 signal 请求、leader 消失或 leader wait 不足以签 stopped；须 owned wait 加整组缺席（Windows 对应 Job 事实）。已确认失败即使 leader 最终 0，execution_result 仍应 failed、return 非 0，stopped 必须绑定已认证 started。
- signal denial、group status 不可观测、仍活后代都不能签 stopped；native scope 槽应继续保留。不得仅因 TERM/KILL 尝试或 collector 完成而 release 槽。
- 迟到 collector、取消后的 frozen/observe、过期结果、超时与 child exit 竞态不能把失败翻为成功，不能重新启动观察或追加第二份 authority。
- 绿例应覆盖 collector 错误/超时/无效绑定、ready 真实性/期限/同 PID、迟到/取消、signal denial、后代存活、budget 到期、正常 binding 与自然退出；独立软件替身要明确标注。
- 最终评审需要稳定源码清单、镜像一致性、验证原始结果与对应源码摘要；按该最终 candidate 验证。当前初审不覆盖正在修改的源码。
- 软件 gate 通过最多成立为 SOFTWARE PASS。真实 H21 同 PID hook、原生采集全链及真实 H21/Nuke 工程验收均为未执行，需后续另行授权。

## 历史上下文使用

本轮查阅 MEMORY.md:139–174 的 Bridge 历史边界用于定位，所有本报告的关键证据均重新读取或计算。MemHub_context 请求 `481ebbf2-89b9-4489-9f4d-4f698c006447` 返回 partial、items=[]、timeout_budget，未提供可采纳的历史结果。没有进行共享记忆写入。
