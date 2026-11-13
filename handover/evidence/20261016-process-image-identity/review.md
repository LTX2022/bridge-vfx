# 进程身份接口独立只读复核（2026-10-16）

复核类型为实际运行的 general-purpose 独立只读审查。Bugbot agent 类型在本环境不可用，没有 Bugbot 成功结果。审查者未修改源码、镜像、构建或交付文件。本记录由主控根据审查者回传及原始日志整理。

## 结论与已修复问题

最终冻结版中未发现仍未关闭、证据充分且可复现的新 bug。唯一确认的新增监督预算问题 **P2 CLOSED**。

修复前，`_supervise_owned` 在监督循环前同步执行 writer refreeze 和 OS observation。0.1 秒 session 预算、mock observation 阻塞 0.5 秒时，普通 Python child 在 0.5 秒处仍存活，约 0.533 秒后才被终止。

最终版由独立采集线程只提交 Queue 数据，主监督持续检查 session、cancel、operation、磁盘和日志预算，并独占一次签发 started。超限先发停止信号，再签入 binding error；迟到采集结果不能改变 started 或补入 anchor。

独立相同复现：监督约 0.125 秒返回；0.5 秒处 child 已退出；`TIME_BUDGET_EXCEEDED`、exit `-15`；`late_binding_accepted=False`；错误为 `SUPERVISOR_WRITER_COLLECTION_ABORTED:TIME_BUDGET_EXCEEDED`。新增回归直接观察仍被阻塞采集器对应的实际 child，保留 0.3 秒内退出断言；随后单独有界等待 started 发布，不以较晚 stopped 代替 liveness。

源码位置（1-based）：`packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py:249`、`:339`。回归位置：`tests/unit/test_writer_process_deployment.py:348`、`:439`、`:445`、`:451`、`:491`。

## 范围及冻结身份

11 个代码/测试目标：

- Runtime：`process_image.py`、`owned_process.py`。
- Houdini：`task_host.py`、`render_writer_facts.py`、`client.py`。
- 部署：`production_hosts.py`、`configure_production_hosts.py`。
- 插件：`plugins/houdini/_impl/houdini_bridge_addon.py` 的 `_task_writer_process_identity`、`task_host_serve` 及必要身份传播。
- 测试：`test_process_image.py`、`test_writer_process_deployment.py`、`test_writer_process_receipts.py`。

审查主 image/load address、txt vnode、出生身份与祖先双向重采、严格 proof 结构/数值类型、aggregate read budget 预留，以及 HMAC/context/producer/原始 signed started 联合绑定；关联核对持久读取预算、writer 终态恢复和无 writer 旧监督兼容。没有复核所有历史脏树。

最终两文件测试前后摘要不变：

| 文件 | SHA256 |
|---|---|
| owned_process.py | bb0606a86586dd727dfdec3ba1d3a5e5c11fc504ec961e6d8c09f5b2558b1bcc |
| test_writer_process_deployment.py | fd75d2862f31466616e7a99f730eaf3795434838d9739f1be8065312064bd059 |

11 个目标仅上述两文件发生修复漂移，其余 9 个相对审查首次读取无漂移。审查者报告的 11 文件有序清单聚合 SHA256 为 `2f4c918af506d9caaec360406f6c8d8de5af09a92f8998d184a5685c45629b5e`。5 个 controller 镜像最终与对应源码逐字节一致。逐文件最终身份另见 `final-source-freeze.json`。

## 独立执行结果

前阶段可靠边界 50 项和关联 writer 8 项，共 58/58 通过。最终冻结版运行 24 项 deployment 和 13 项 OwnedSupervisorTests，共 37 项：33 通过、4 个 Windows 专用测试跳过，exit 0，4.133 秒。作者和主控重复执行不累计为新增唯一覆盖。

最终原始日志：[independent-final.txt](independent-final.txt)，8273 字节，SHA256 `4dc06fe10d042f6143d0157b76ead4e42b77a1de7542566901247275972e833e`。日志含测试前后冻结摘要和原 P2 最终复现。

前阶段原始日志保留在 `independent-boundaries-prefixed.txt` 和 `independent-environment-limits.txt`；它们对应各自阶段，不替代最终冻结结果。

## 限制

- baseline 仅有清单/hash，无旧正文，不能把 git HEAD diff 当作本轮全部新增或精确还原改前逐行差异。
- baseline 最新扫描在原审查阶段为 14 个已有文件变化、0 缺失，其中 3 个 handover 文档在代码复核范围外；最终完整保留证明另算，后续 verifier 两文件增量单独记录。
- 环境为 Python 3.11.7、macOS 15.8.1 arm64。独立首跑真实工具两例出现 vmmap timeout，另有一次 killpg EPERM；默认 /var TMPDIR 导致六个 fixture 链接拒绝。固定 /private/tmp 的可靠边界通过，没有放宽生产守卫；该独立结果不能证明本机原生工具采集成功。
- Windows 4 项未执行。未启动真实 DCC、hou/native、DSO 编译/加载、模型；未浏览凭据或外发。
- 进程身份缺口关闭后，其他有效 writer/processor/AOV/filter/alpha/close 事实仍缺。`BLOCKED_MISSING_NATIVE_FACTS`、空 metadata、Registry 拒绝、工程 BLOCKED 和 M1 NOT_READY 保留。

## 生命周期 verifier 增量

首轮软件安装生命周期暴露 argv JSON canonical 的 ASCII/UTF-8 不一致。两文件增量的独立只读复核通过，未发现新增可复现 bug；原 P2 CLOSED 结论保持。

- `tools/verify_skill_lifecycle.py` SHA256：`8d74955d24940cfb23b47c0b7a265c50bfad0274dc16f6545264edb33ac88582`。
- `tests/unit/test_skill_lifecycle_verifier.py` SHA256：`dc636acbb6397372ea116156f257180fe16c69d12b368c1b3f3758c4efa6d99e`。

工具 :639 的 `ensure_ascii=False`、`sort_keys=True`、compact separators、`allow_nan=False` 和 UTF-8 编码与 `owned_process._canonical` 一致。比较对象仍来自 `_graph_completion`、`_signed_stop`、原始 started；bootstrap、worker 路径、argv 长度及 operation 绑定条件保留，没有接受 ASCII 转义摘要的回退或放宽验签。

既有测试使用“中文 空格”路径，并以运行时 canonical 生成 fixture。审查者独立只跑此单项（含正常、外来 worker 两个子例）：1 项通过，0.242 秒，exit 0；两文件测试前后摘要相同。正常 Unicode 命令通过，外来 worker 被拒绝；原 37 项没有重跑。此为审查者回传的独立结果，主控的 16/16 是单独运行，不能计为独立亲跑。

该单项模拟 `_graph_completion`、`_signed_stop`、宿主和会话，仅证明摘要门槛及拒绝路径，不替代新的端到端 HMAC、真实进程或三 Skill 安装验收。缺少修前正文，不能独立认证历史 diff 严格仅一行；本结论绑定上述两 SHA 和相关当前片段。最终三 Skill 的实际安装生命周期由新 release 单独证明。
