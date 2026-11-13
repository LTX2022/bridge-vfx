# 原生身份采集修复与 11 候选

本轮最小修复、必要验证及两位独立验收通过。已冻结 `engineering-closure-20261023-h21-11`，状态为 **PREPARED_NOT_AUTHORIZED，0 启动、0 票据**；review 仅指向尚不存在的 `engineering-closure-20261023-h21-12-authorized`。

真实普通 Python 的 macOS 身份采集已取得定向及软件链证据；Houdini/Nuke 原生 API 仍为显式替身。**本轮未启动真实宿主，真实 H21＋Nuke 工程闭环、视觉、M1、HY3 与生产验收仍未完成。**

## 当前修复

1. 身份路径用文档化的 `/usr/bin/vmmap -w -interleaved -summary PID` 读取真实五字段，再按返回的原始 Load Address 独立查询唯一可执行主映像。移除对 sample 性能采样和符号处理的依赖，以及其专用 stderr 豁免。原解析、schema、前后 ps、两次 lsof/vnode、stat/hash、双重观察、完整祖先、anchor、nonce 与签名均保留；所有非空 stderr 仍拒绝。tool 5 秒、freeze 5 秒、observe 16 秒、capture 60 秒均未增加。
2. 正式软件链暴露登记器内部临时副本使用 macOS `/var` 别名路径后，被自身严格清理门拒绝。最小独立对照复现同一 EXR 在别名路径失败、真实路径成功。仅在 `_typed_admission` 创建内部临时目录前 canonical 化系统临时父根；不修改外部输入路径、链接拒绝、`_plain_path` 或 `read_frame`。

两份 controller/runtime 镜像逐字节一致。生产变更只涉及上述两个模块及其镜像；其余为必要测试与软件边界配置，最终 [10 文件清单](evidence/20261023-sample-native-repair/validation/final-source-10-sha256.json)对应当前代码。两组补丁均通过正反还原。

历史原始记录证明 sample 在“processing symbols”后触发单工具时限；本轮原命令在 2.595 秒成功，未重新复现旧超时。因此结论是**移除身份路径对该剖析步骤的依赖**，不是修复 Apple sample 内部故障，也不解释 09 的未知 TOOL_FAILED。

## 验证结果

| 范围 | 结果 | 证据 |
|---|---|---|
| 身份边界及软件工具夹具 | Python 3.14、3.11 各 30/30 | validation/core-314.log、core-311.log |
| 真实 macOS 完整父子证明、错可执行文件拒绝、监督器 writer 绑定及可信停止 | 3/3，32.192 秒 | validation/native-314-unsandboxed.log 与实际签名原件 |
| 登记回执、字节重验及消费核心 | Python 3.14、3.11 各 25/25 | validation/registry-temp-root-green-final-314.log、green-final-311.log |
| 实际默认 TMPDIR 因果对照 | 修前别名失败/真实父根通过；修后两者均通过 | validation/temp-path-repro/、temp-path-repro-after/ |
| 无 image model 八阶段软件链 | 02：1/1，70.975 秒 | validation/full-chain-native-image-02.log |

不同验证组不累加为全项目测试总数。本轮未重复全项目全量或重建三类 Skill 安装包。

02 使用真实普通 Python 进程、TCP、原始 macOS 工具、监督器及账本；没有 image adapter 或 Popen bootstrap。8 票、7 进程组全部可信停止；独立认证 18 行 accounting 和 21 个签名事件，退出及监督器返回码均为 0，无未知后代，计费 66.406685114 秒。登记库有 2 个产物、2 个版本、0 个失效项，其中 Houdini 有 1 份专用 registry operation receipt；Nuke 的冻结输入、只读验证副本和实际软件 API 消费均绑定上游版本及摘要。两产物继续标记 `software_test / NOT_OBSERVED`。

[第二独立证据验收](evidence/20261023-sample-native-repair/successful-chain-02-evidence-review.md)及[逐项审计 JSON](evidence/20261023-sample-native-repair/successful-chain-02-audit.json)记录上述事实。一次软件链成功不证明长期采集稳定性或真实 DCC 兼容。

### 保留的失败证据

首轮 01 在登记器 `COMPLETION_BYTES_UNAVAILABLE / TASK_PATH_LINK` 停止，6 票均可信停止、无登记和 Nuke 消费；修复后才在全新 02 目录验证。原 sandbox 的 `/bin/ps` 权限拒绝、登记测试自建根使用别名导致的外部 source 拒绝均保留原日志，不计为通过，不放宽相应校验。详见 [01 独立审计](evidence/20261023-sample-native-repair/first-chain-01-audit.json)。

原 `-06` 至 `-10` 分别 242/183/183/253/183 个文件，共 1044 项未变；首失败 01 的 608 项、成功 02 的 644 项封存后未变。签名密钥及含环境的 intent 原件仅留在本机，不复制到结果包。

## 独立验收与职责

方向、有限原生复现、本机依据、唯一实现、Bugbot 代码验收、只读证据验收共六角色分阶段协作。root 负责装配、原件封存和交付；共享生产文件仅实现者修改。

- [身份增量 Bugbot](evidence/20261023-sample-native-repair/code-review-initial.md)：无 P1/P2。
- [登记器增量 Bugbot](evidence/20261023-sample-native-repair/code-review-registry.md)：无 P1/P2；全部 10 文件匹配已审清单。
- 第二证据验收：软件链 32 项、冻结候选 22 项检查通过；未扩为真实工程验收。

## 冻结范围

- [11 候选](../outputs/engineering-closure-20261023-h21-11/)：PREPARED_NOT_AUTHORIZED，0 启动、0 票据。
- scope SHA-256：`d5cba25f180ed5e3cf0f85aa910a9f01e8d41b193efe22350751b775d6b44f1e`。
- bindings SHA-256：`2437bfe9cc83c904a43e90a0f13e7abe2913eb1743a65a856f31f26f8871479d`。
- review SHA-256：`85feb054b064d0adce4cce34457cac0190c7505ab7e141f40c483a4a2ca5d2d5`，仅指向未来 `-12-authorized`，未激活。
- 正式冻结快照默认只读预检：PREPARED，blockers 为空。
- 158 个源码快照、174 项 source_freeze 及 175 项候选 immutable 均核对通过，与成功 02 及当前源码一致，无 pyc；详见[候选核验](evidence/20261023-sample-native-repair/candidate-final-audit.json)及[独立冻结验收](evidence/20261023-sample-native-repair/candidate-11-independent-audit.json)。
- H21.0.631／Nuke17.0v1／ACEScg；8 次启动、每次 120 秒、累计 600 秒、512 MiB、一个重作业、零自动重试保持。

后续真实作业仍需对冻结 review 的新范围明确授权；失败、超预算或停止未知即停。未修改 Desktop 主工程，未提交或推送 Git；没有将软件测试产物当作真实 HIP/NK/EXR 交付。
