# 原生就绪同步与采集失败早停：13 软件候选

本轮完成两项软件修复、必要验证及两位独立验收，冻结候选为 `engineering-closure-20261023-h21-13`，状态 `PREPARED_NOT_AUTHORIZED`，0 次宿主启动、0 票据。真实 H21／Nuke 未重跑；真实工程闭环、视觉、M1、HY3 和生产验收仍未通过。

## 根因与当前行为

1. **采集早于原生运行时就绪。** -12 的 vmmap 返回码为 0，但 stderr 明确记录 dyld 已初始化、libSystem 尚未启动，严格采集因此拒绝。普通 Mach-O 对照复现了启动前态的警告；main/malloc 就绪后该警告消失，但该对照因路径别名未通过完整身份门，不计为完整身份阳性。task_read_for_pid 在本次受控关系中返回 EPERM，未作为生产路线。
2. **已记录的采集错误未进入停止状态机。** 修前正式监督循环的受控反例显示：签入 writer 错误后，原子进程仍响应握手，随后自然退出并被记作成功，没有整组停止请求。修复后，ready、采集或 started 写入失败均先固定失败状态，在同一循环请求 TERM，沿用原有 KILL、整组消失和 wait 验证。首次 started 写失败后的重签也保留错误，不能放行业务。

就绪控制复用 `owned_process` 的私有目录、intent 和签名回执，严格绑定本次 identity、nonce、Popen PID、argv 摘要与权威环境。子进程发布 `runtime-ready` 后等待完整、认证的原 writer binding；ready 本身不构成身份授权。

- H21 husk：精确版本官方 `--prerender-script`，使用已冻结的纯标准库 adapter。
- Hython：`import hou` 后、原 writer 身份路径前。
- Nuke alpha：`import nuke` 后、原生观察前。

监督器在 Popen 前确定同一 session／collection 期限；ready 等待与原完整观察共用一次 observe deadline。tool 5 秒、freeze 5 秒、observe 16 秒、collection 22 秒、capture 60 秒均未增加。vmmap stderr、双重映像观察、vnode、hash、祖先、身份及签名检查保持。

取消在 ready 等待、返回前及新观察启动前检查。已经进入的 `_observe` 链可在原 deadline 内继续，包括后续工具调用；结果丢弃，不签入 binding。自有作业停止不等待采集线程，不宣称逐工具即时取消。

Alpha 在认证身份和停止回执后保留原采集原因；监督器成功观察停止与业务执行失败分别记录。普通失败反例的监督器返回码为 0、业务退出码为 -15，不能只看监督器返回码推导业务成功。

## 验证范围

| 验证 | 结果 | 证据 |
|---|---|---|
| Python 3.14 核心 | 104 通过、4 Windows 专项跳过，0 FAIL/ERROR | validation/ready-focused-py314-attempt02.* |
| Python 3.11 核心 | 104 通过、4 Windows 专项跳过，0 FAIL/ERROR | validation/ready-focused-py311-attempt01.* |
| 普通 Python 真实 macOS 采集 | positive-02 通过，2.553 秒，17 项检查；8 次原系统工具均 rc0、stderr 完整且为空 | validation/ordinary-positive-02/ |
| 采集失败停止 | collector-error-01 通过，0.131 秒，13 项检查；显式 collector 注入、同轮 TERM、无业务 marker、业务失败且整组可信停止 | validation/ordinary-collector-error-01/ |
| 无映像模型八阶段软件链 | 单次 1/1 通过，55.186 秒，无 FAIL/ERROR/SKIP；8 票、7 个可信停止进程组、13 项 DONE 阶段、两份软件产物及上游消费 | validation/software-chain-native-01/ |

证据根为 [本轮验证目录](evidence/20261023-native-readiness-stop/)。核心组显式排除普通原生 writer 用例，由后续独立进程验证承担，不计为跳过后通过；不同组重叠，不合计成全项目测试总数。未重复全项目全量或重建三类 Skill。

普通正例验证了 ready 认证先于首次 vmmap、完整主映像身份、同一 deadline 和业务在认证 started 后才执行。失败反例只保留真实 ps，随后显式注入 collector 错误，不声称复现了原生 vmmap 失败。单次软件链使用真实普通 Python、TCP、macOS 工具、监督器和账本；Houdini/Nuke API 为明确替身，没有 image model 或 Popen bootstrap，产物保持 `software_test`／`NOT_OBSERVED` 来源。

### 保留的失败事实

ordinary-positive-01 被工具沙箱在首个 `/bin/ps` spawn 阶段以 EPERM 拒绝，未到 ready/vmmap；已认证业务失败、退出 -15 和整组停止。该次报告器处理缺失 ready 时又产生 TypeError，未落完整 profile trace，因此不能独立重建该次 TERM 精确时序。11 个公开文件及私有原件保持，报告器的异常单独记录。只在明确改变工具权限、修复报告器后进入全新 positive-02，生产 18 项源码未变。

候选准备的首次 CLI 使用相对路径，被绝对路径门在创建候选前拒绝；改用规定的绝对路径后成功。上述调用方错误没有转成产品通过，也没有放宽生产门。

## 独立验收与源码

六角色分阶段协作：方向、有限复现、本机原生依据、唯一实现、独立 Bugbot、独立证据验收；root 负责装配、封存和交付。生产文件及其镜像由单一实现者修改。

- [最终代码审查](evidence/20261023-native-readiness-stop/code-review-final.md)：18/18 当前源码匹配已审清单，无待修 P1/P2；未重跑测试或真实 DCC。
- [最终证据验收](evidence/20261023-native-readiness-stop/evidence-final-review.md)：SOFTWARE PASS；原始回执、时序、软件链账本及13冻结范围通过独立认证，真实DCC层仍未证。
- [18 项源码清单](evidence/20261023-native-readiness-stop/implementation/ready-after-sha256.json)，SHA-256 `70bbfe11a2d37fa057540e99e2718aabdabc336e5ca06d7d4a7a461d5c3d2564`。
- `ready-change.patch` 是包含两项修复的总补丁，不能与中间 `fail-stop-change.patch` 顺序叠加；before 副本及补丁正反验证记录一并提供。

## 冻结范围

- [13 候选](../outputs/engineering-closure-20261023-h21-13/)：`PREPARED_NOT_AUTHORIZED`，0 启动、0 票据。
- scope SHA-256：`bb4c001a00ea38b92ccd57bb6cff9c128222fdf8c02e7a6fbcc2600995386276`。
- bindings SHA-256：`b43dff981e21f17aa9dfa55ff210e8e80ea608f76cebea8b2f91492670380e13`。
- review SHA-256：`72592c392e00a44747bcbe39c6dd13dc7bf35c6a5dca4f1091e6b1aa36f42535`；只指向尚未创建的 `engineering-closure-20261023-h21-14-authorized`，本轮未激活。
- 冻结快照正式 CLI 默认只读预检：PREPARED、blockers 为空、native_execution_status 为 NOT_RUN。
- 159 项源码快照、175 项 source_freeze、176 项 immutable；新 adapter 随正式源树和精确 argv 冻结，无 pyc。
- H21.0.631／Nuke17.0v1／ACEScg；8 次启动、每次 120 秒、累计 600 秒、512 MiB、一个重作业、零自动重试不变。

-06 至 -12 共 1457 个原文件按大小及 SHA-256 保持；真实失败范围未续跑。未修改 Desktop 主工程，未提交或推送 Git。私钥及含环境的 intent 仅保留本机原位，不复制到交付包。

普通 Python 原生采集及软件链通过不能证明真实 husk hook 的同 PID、脚本生命周期、H21/Nuke 启动时长或真实输出。后续真实验收仍须对新冻结 review 明确授权；未知停止继续占槽，失败或超预算即停、不自动重试。
