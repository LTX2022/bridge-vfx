# 14 真实执行独立证据验收

**实际状态：LIVE14_FAILED_STOPPED_NO_RETRY。** 本次真实工程验收在首个 alpha-husk 阶段失败并可信停止；没有 HIP、NK 或 EXR，不能判为工程通过。独立证据检查全部成立，详见 `live14-review.json` 的 checks；其中 evidence_checks_passed=true 只认证本报告所述事实与封存完整性。

本角色仅做文件、签名和账本只读检查，没有启动或采样 DCC/普通原生进程，没有重跑，没有修改源码或任何原件。认证用 key 仅在内存读取，没有输出或复制 intent/env/key。

## 授权与执行对象

`authorization-source.json` 记录用户本次明确授权：按13冻结review激活14，H21＋Nuke、ACEScg、8启动预算，失败/超预算/停止未知即停，0自动重试，保留原件。activation-result 准确标注为 root 通过正式本地终端转交该授权，不声称由人实际敲入按键。

本地独立认证 `engineering-activation.json` HMAC，并核对：

- 13 review SHA-256：`72592c392e00a44747bcbe39c6dd13dc7bf35c6a5dca4f1091e6b1aa36f42535`。
- 14 scope SHA-256：`f4a65332379006a85711ac5bb837ccada49266644b281870290c5159e94470be`。
- 14 bindings SHA-256：`91f737d813268a51262e53e59863a847e2240fd986357530ce29388df4f80a8e`。

14的159个snapshot文件与13 review.source_snapshot、13冻结snapshot逐项一致；175项source_freeze及176条immutable记录均保持原大小/hash，snapshot无pyc。preflight为同scope/bindings的PREPARED、blockers=[]、执行前NOT_RUN。预算准确保留8启动/每项120秒/总600秒/512MiB/1heavy/0自动重试。

Driver PID11959的保留argv为冻结snapshot内 run_controlled_engineering.py，带`-I -B --execute`及上述两个approved hash，路径、参数和Python executable文件解析均与冻结配置相符。一次执行记录为 UTC 2026-10-23 13:05:58.783793 至13:06:08.029682，wall9.245887秒，driver退出1。

## 原始失败与可信停止

真实child stderr指向冻结adapter `packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py:8`：

`NameError: name '__file__' is not defined`

冻结第8行确实先求值 `Path(__file__)` 才能runpy加载owned_process，因此此次H21 prerender执行路径没有为该脚本提供它假定存在的`__file__`。它是本次最早明确的阻断；此前环境偏好目录警告不能替代这一具体异常归因。该事实不泛化为所有Husk/Python脚本上下文。

alpha-husk PID11967自退出2。独立认证原始started/stopped HMAC、identity/launch_nonce、PID、精确alpha command摘要及stopped.started_sha256，公开副本与私有原件逐字一致。started保留`SUPERVISOR_WRITER_CHILD_EXITED_DURING_COLLECTION`，没有writer binding；不存在runtime-ready、alpha-output或alpha-calibration-result。stopped为owned_child_wait、exit2、execution_result=failed、SUPERVISOR_WRITER_COLLECTION_FAILED、descendant_result_unobserved=false。

这不是一次TERM导致child退出的证据：原adapter失败自行退出2，不能把既有stop_reason当作TERM因果或补造信号时间线。保留的独立post-exit检查为ps rc0、owned PID/PGID11967、matching_processes=[]、signal_sent=false，与认证停止一致；本角色没有再查实时进程。

NativeScope的本地HMAC、journal seq/previous、anchor head、state封套及票据stopped hash全部独立核对。只记录1张alpha-husk票，序列4，计费8.059413秒，最终文件字节4770026，closed_reason=`NATIVE_SCOPE_EXECUTION_FAILED`。supervisor stderr中随后由scope.finish抛出的同名错误发生在已签stopped及失败账本持久化之后，不可据此抹去停止回执或误记为执行成功。配置内host_started字段不是运行计数，实际启动事实以认证票据为准。

Driver journal仅alpha INTENT并保留相同writer failure，只有supervisor-alpha-h21目录，没有后续Nuke/正式Houdini阶段或第二张票；本14范围无自动重试。完整writer映像身份链没有完成，因此不能把本次冻结命令和prerender错误升级为writer binding PASS。

## 实际产物与封存

直接扫描14整个根目录，`.hip/.hiplc/.hipnc/.nk/.exr`均为0；登记库、Nuke save receipt、alpha-calibration-result均未产生。USDA属于真实执行输入，不是成功工程或图像产物；`/private/tmp/bridge-live14-delivery/artifact-inventory.json`准确记录FAILED_NO_DELIVERABLE_IMAGE_OR_PROJECT，没有借用旧文件或生成替代预览。

- 14 seal：194个文件，大小/hash与精确文件集合全部匹配。seal manifest SHA-256为`ef729dc278e30d1a65d3344463590009e4eddef8a52bafae87da111b175caa37`。
- 06–13原件：1641个文件全部匹配；baseline SHA-256为`04480646cb15c8023fb6728fa2d9ab53798a480acd53f638f5ed61b214e5f5e0`。
- execution公开清单14项全部匹配；raw-alpha六个日志/回执副本与原件一致。复制清单明确排除intent、receipt.key和environment。

14的实际失败及原件保持不变。当前软件修复、稳定代码/测试和未来15候选另行验收，不用未完成的修复替换14原始结果。本报告不宣布整体SOFTWARE PASS，不授权任何新的真实执行；新的真实尝试仍需新的冻结review与用户授权。

独立机器可读结果：`live14-review.json`；复核脚本：`audit_live14.py`。脚本只读文件并在内存校验HMAC，不执行Bridge代码，不调用任何进程或DCC工具。
