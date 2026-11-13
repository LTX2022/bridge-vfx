# READY13 独立证据入口评审

结论：**条件 GO，允许已限定的普通进程验证和软件八阶段验证继续。** 本结论只覆盖进入下一证据层的源码/现存软件证据前置条件，不宣布普通进程阳性、八阶段通过、candidate13 冻结通过或真实 DCC 验收。

本角色只读审查、计算摘要并在本目录保存审查副本，没有运行任何 native target、DCC、模型或渲染，没有修改源码或 06–12 原件。

## 审查对象与现存证据

最终源码清单：`implementation/ready-after-sha256.json`，18 项，SHA-256 `70bbfe11a2d37fa057540e99e2718aabdabc336e5ca06d7d4a7a461d5c3d2564`；`ready-change.patch` SHA-256 `48ce18c233a01ca42025c791dcd9db09b0afdfc6c29273503accc2f4be56ec67`。

独立读取并保存的 18 个文件全部匹配 recorded before/after/size；读取期间 manifest 没有变化。owned_process、process_image、alpha_calibration、husk_runtime_ready 四对 authoritative/controller 镜像逐字一致。核验在 `ready-review-inputs.json` 和 `ready-evidence-audit.json`，快照在 `ready-candidate/`。

- Python 3.14 `ready-focused-py314-attempt02`：108 项，104 通过、4 Windows 跳过，0 failure/error。
- Python 3.11.16 `ready-focused-py311-attempt01`：同为 108 项，104 通过、4 Windows 跳过，0 failure/error。
- 两份原始日志条目数、通过数与 JSON 相符，source_before/source_after 和独立审查的 18 项最终清单完全相同。真实普通 Python/macOS writer test 在 focused suite 中被明确排除，不计为已执行。
- Bugbot 独立审查同一 manifest/patch，无 P1/P2；取消范围经 root 明确后，Bugbot也未发现该精确边界造成的具体 P1/P2。报告为 `/private/tmp/bridge-ready13-code-review/initial-review.md`。

## 关键实现与证据边界

ready 复用原 owned_process HMAC 回执与每次新私有目录/receipt.key。监督器在业务 Popen 前覆盖本次目录、完整 identity、runtime nonce 与期限环境；helper 的 PID 来自 os.getpid，argv 摘要来自本次 intent command。collector 认证 HMAC 后检查严格字段集、identity、PID、argv hash 和 runtime nonce，拒绝额外 supplied verified 字段、错 nonce/PID/hash/HMAC、取消、超时、缺失/异常事件及 event 文件的正常/断裂 symlink。ready 只调度原身份采集，不创建身份 schema 或放宽 strict binding。

helper 发布后持续 hold，只有认证 started 的同 PID/argv、无 writer error、完整 expected executable/host anchor 绑定才返回；错误、取消、停止、读错误或期限均拒绝。此前发现的“有效 binding 首次 started 写失败后重签可放行业务”交互已经修复：首次写失败固定 writer error，保留已存在 collector 原 cause，重签也不可解除 hold。最小核心回归已绿。

真实 source/code point 的可信来源仍是固定源码/路径/精确 argv/source_freeze。HMAC 认证本次回执，不是 macOS 原生代码签名；目标可写的 ready 声明不是 OS 映像身份证明。

## 期限、停止和取消

生产 supervise 在 Popen 前建立一次 session_end 和 collection_end=min(session_end, now+22)。refreeze 后只建立一次 observe_end=min(collection_end, session_end, now+16)，再把该 end 传入原 `_observe`。门位于首次 ps 后、首次 vmmap 前；gate 等待消耗同一次观察剩余期限，返回后检查 remaining，不重新调用领取完整 16 秒的 observe_process。工具 5、freeze 5、observe 16、capture 60、collection 22 和原业务预算没有增加。

错误在同轮 TERM dispatch 前确定 stop_reason，沿用两秒 KILL 升级；execution failed 与 owned wait/整组缺席的可信 stopped 仍分开。未知/拒绝信号或未停后代不据此签 stopped/释放 native scope。alpha 原因只在 signed operation 的结构/identity/PID/argv/hash/execution 协议通过后传播，且不能签 alpha-output 或 dispatch 下一 Nuke。

取消的精确边界为：ready 等待/返回与整次 observe 启动前检查 cancelled，阻断新观察；已经进入原严格 `_observe` 的工具沿原 tool/observe/collection/session deadline 有界结束，其晚结果丢弃、不签 binding，owned 停止请求不等待 collector。本轮没有新增逐工具可取消能力，不能声称 mid-observe 取消后绝无后续工具调用。这是 root 明确的最小范围，独立代码审查未发现具体 P1/P2。

## 官方依据、source_freeze 与未证事实

精确 H21.0.631 安装静态文档支持 prerender-script，在 USD 加载后、settings/render/products partition 前执行。当前 adapter 固定 sibling owned_process 路径、只用标准库，失败直接退出；Hython 在 import hou 后、原 writer identity/host.ready 之前调用；Nuke alpha 在 import nuke 后、native observer 之前调用。三者代码点及反循环结构可静态确认，真实 H21/Nuke 同 PID、实际时长和生命周期仍未验证。

prepare_native_alpha_scene 记录 adapter 源码身份并生成唯一 prerender 参数；run_alpha required_source_paths 已加入 adapter，preflight 核该固定 snapshot 位置、record/source_freeze hash 和精确 command。preparation 核心用例同时检查 adapter 在 snapshot/preparation/source_freeze 一致，并保留所有冻结字节/重复准备不改写的检查。Hython addon 修改随 plugin_build 进入既有冻结 admission。本轮不改写 06–12 的旧 bindings。

B1 原普通 Mach-O after 仍因路径别名被严格拒绝，B2 EPERM 没有远端就绪位阳性；它们不能作为此候选的完整原生成功依据。当前仍需后续实际普通进程原始回执、软件八阶段完整回执和 fresh candidate13 冻结审计。

## 下一层的限定检查

已读 ordinary runner：fresh prefix/私有目录拒绝复用，每 case 一个普通 Python target、30 秒 session、tool5/observe16/collection22、0 retry；positive 使用原 strict collector，不安装 image 模型，negative 仅在 `_vmmap` 边界显式抛 collector error，不冒充原生警告。其输出分离原始回执/完整工具流与本地私钥，保留同 PID、argv、签名链、gate/首次 vmmap、business release、same-loop TERM 与整组缺席事实。

本角色读取 runner 时实际 SHA-256 为 `8a455c3ff3d842bced58fe5e31445d17e3ff52a2578f1b388da2647d902e7637`，与 root 较早提供的 `3437a488…` 不同，已通知 root。条件 GO 要求执行前固定实际采用的 runner 指纹并保留原流；本报告未把较早摘要误当作当前摘要。

待真实结果落盘后需重新认证其原始 HMAC/nonce/PID/argv/期限、失败信号时序、trusted stop/scope 保留、最终 source manifest 与 candidate13/success snapshot 一致性；同时重算 1457 原件、确认 candidate13 prepared 零票和 future14 不存在。真实 H21/Nuke 启动及工程闭环继续不在本入口 GO 范围。
