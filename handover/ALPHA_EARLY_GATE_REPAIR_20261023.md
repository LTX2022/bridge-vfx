# Alpha 身份早停与诊断修复

本轮三项软件修复及独立代码复核完成；八阶段链在显式软件 OS 工具模型下通过。`-10` 已冻结为 `PREPARED_NOT_AUTHORIZED`，0 启动、0 票据；未来 `-11-authorized` 尚不存在。**真实 sample 可靠采集未解决，真实工程闭环与 M1 未完成。**

## 当前实现

- 工具失败保留固定 argv、阶段、退出码、stderr 原字节前缀及已观察长度、截断/完整标志与 errno。argv 上限 1024 UTF-8 字节/16 项，stderr 前缀上限 4096 原始字节；诊断小于 16 KiB，不记录环境和 stdout 内容。
- 监督器把诊断连同原始错误签入 started；诊断不构成身份授权。kill/wait/close 失败不再覆盖原始 ProcessImageError，未回收明确记录 `leader_reaped=false`；工具成功但清理失败也拒绝成功。
- 每个 alpha 宿主可信停止后、签发 alpha-output 或启动下一宿主前，共享校验核对可信 executable、身份/nonce、PID、命令摘要、完整 anchor 与 start/stop 绑定。缺绑定或身份不符立即拒绝；三类真实普通 Python 监督器反例均只启动一次、Nuke 为零、无 alpha-output。
- 最终校验保留原始采集原因，按控制端签名 executable 记录重新冻结，不再以空结构掩盖错误。三份 controller 镜像逐字节同步。

生产变更限 `process_image.py`、`owned_process.py`、`alpha_calibration.py`、`tools/run_alpha_calibration.py`，以及对应三份镜像。sample/定点 vmmap、双观测、祖先链、签名和原有时限均保留。源码和测试指纹见 [最终18文件清单](evidence/20261023-alpha-early-gate/final-source-sha256.json)。

## 验证

| 最终验证组 | Python 3.14 | Python 3.11 | 原始日志 |
|---|---:|---:|---|
| 诊断/监督器核心 | 31/31 | 3/3 兼容核心 | diagnostics/green314-synchronized-final.log、green311-synchronized-final.log |
| alpha 身份及早停 | 28/28 | 28/28 | alpha/focused-314.log、focused-311.log |
| 软件工具模型/入口同步 | 5/5 | 5/5 | integration/image-model-controller-core-314.log、image-model-controller-core-311.log |
| 八阶段软件链 | 1/1，111.280 秒 | 未重跑 | integration/full-chain-controller-image-model.log |

诊断补丁6文件、alpha生产补丁2文件及测试夹具补丁7文件均在独立临时目录正向匹配当前字节、反向还原原字节；详见 production-patch-roundtrip.json 与 integration/test-patch-roundtrip.json。

以上是必要定向和软件集成验证，未运行全项目全量或重建三类 Skill 安装包。不同组存在覆盖重叠，不相加为全量测试总数。

八阶段软件链使用实际普通 Python 进程、TCP、监督器签名与账本，8 票、7 个可信停止进程组，退出码均为 0，无未知后代；软件计费 98.602906 秒、目录 41,043,108 字节。两份产物登记及 Nuke 对上游登记产物的依赖成立，来源保留 `software_test` / `NOT_OBSERVED`。158 个冻结源码与当前源码一致，175 项 immutable 校验通过，无 pyc。

### 软件边界及失败记录

软件模型仅替换 sample 和定点 vmmap 的原始输出字节。真实 ps、lsof、独立唯一 MH_EXECUTE 选择、文件 hash、正式解析、双观测、祖先链、状态机和签名保留。整段 sample header、出生时间小数、主 Load Address 和 VM 映射属于模型事实。

测试 Popen bootstrap 包装监督器及两次隔离控制端，再运行原源码、恢复原 sys.argv、透传进程参数；不能称原生启动 argv 完全未变。适配器源码内嵌并绑定摘要，替换外部模板不能影响执行。生产 `-10` 不含软件模型配置或自动降级。

四次软件整链的原始结果全部保留：

| 尝试 | 结果 | 首个阻断 |
|---|---|---|
| -01 | FAIL | 软件子进程在身份采集完成前退出 |
| -02 | FAIL | 真实 sample 在处理符号阶段超时，尚未进入 vmmap |
| -03 | FAIL | 测试隔离控制端未继承模型，双方观察异源，正式比较拒绝 |
| -04 | PASS（显式软件模型） | 无；不证明真实 OS 采集通过 |

诊断组首次收口的短等待失败也原样保留；测试已改为正式时限和事件同步，生产时限未改。完整原始日志、复现、补丁见 [证据目录](evidence/20261023-alpha-early-gate/)。

## 独立验收

[Bugbot 代码审查](evidence/20261023-alpha-early-gate/code-review.md)未发现本次范围仍待修的 P1/P2。第二验收者独立认证 -04 的 HMAC、停止事实、SQLite 账本、文件摘要、模型来源和原件保留，核对两份产物及消费依赖；结果见 [独立证据验收](evidence/20261023-alpha-early-gate/evidence-review.md)。审查受限的真实 ps 用例不计为通过；未把局部代码审查扩为全项目验收。

## 冻结候选

- 候选：[engineering-closure-20261023-h21-10](../outputs/engineering-closure-20261023-h21-10/)。
- scope SHA-256：`75baa3d5cac190d8588304b9cd236caaddca4a78a78d84e7cbb41e07366d0597`。
- bindings SHA-256：`c4031f4904ef0d7422def18a1670a7d74a19f9409fd240984b40493abb76b65d`。
- review SHA-256：`bfa0ca6aacaab899c003f54e19db56fec8187a789ff55df13a5d8ee7e6e8dab3`，仅指向未来 `engineering-closure-20261023-h21-11-authorized`；本轮未激活。
- 默认只读预检：PREPARED，blockers 为空；不代表真实采集可靠性已验证。
- 预算保持 8 次启动、每次 120 秒、累计 600 秒、512 MiB、一个重作业、零自动重试；H21.0.631 / Nuke17.0v1 / ACEScg。
- [候选核验](evidence/20261023-alpha-early-gate/integration/candidate-final-audit.json)与[实际软件链核验](evidence/20261023-alpha-early-gate/integration/software-integration-audit.json)分别记录准备状态与软件结果。

-06/-07/-08/-09 原件逐文件哈希与大小均未变，分别 242/183/183/253 文件；失败软件尝试 -01/-02/-03 也保留。未修改 Desktop 主工程，未提交或推送 Git。

## 保留限制

- 本轮未启动真实 Houdini/hython/husk、Nuke、WorkBuddy/HY3，未产生新的真实 HIP/NK 或工程渲染。
- -02 已观察到普通 Python 的真实 sample 在符号处理阶段超时，生产可靠采集未修复、未重验；这不能解释 -09 历史 TOOL_FAILED 的确切原因。
- -09 的真实校准图像及原始失败记录保持原样，不能提升为原生 alpha 通过。新候选不复用旧失败产物作为校准依据。
- 真实工程闭环、视觉、M1/HY3/生产验收仍未通过。后续真实执行必须另行明确授权新范围；未知停止占槽、失败或超预算即停、不自动重试。
