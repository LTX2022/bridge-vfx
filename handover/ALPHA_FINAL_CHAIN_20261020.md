# Alpha 可信入口与八阶段软件集成

本轮软件整改、必要验证、独立复核及候选重新冻结已完成。完整软件链为 `SOFTWARE_CHAIN_COMPLETED`，真实宿主保持 `NOT_RUN`；这不构成 H21＋Nuke 真实工程闭环、视觉或全 16 域 M1 通过。

## 实现结果

- Alpha 独立执行入口在进入预算操作前及取得共享执行锁后，分别重验范围、运行绑定与可信激活原件。必须是本地终端明确授权的 `real_host`；公开摘要、软件授权、陈旧回执及并发占用均不能获得真实执行权限。拒绝路径不关闭合法范围。
- 正式八阶段使用同一生成器、driver、worker、持久操作、监督器与账本。软件替身仅显式替换底层原生 API 和可执行边界，未模拟调度、停止或登记成功。
- 修复正式装配重复校验时拒绝已冻结 writer 身份、合法 JSON 业务回复累积触发日志上限，以及受控宿主就绪等待与既有阶段预算不一致的问题。实际执行上限未扩展。
- H21 `sphere_ground_v2` 使用 stock beauty 开关与实际 Vars 路径；保留 v1 合同。软件 Stage 从实际参数读回，EXR 夹具按实际产品压缩属性写出并由生产解码器全像素复验；未放宽生产输出校验。
- 预算账本的递归磁盘扫描移到事务锁外，入锁后仍重读最新认证状态。目录扫描中真实消失可继续，权限失败及替换仍拒绝。信号被拒不制造停止事实；首个观察异常保存签名诊断。诊断及首次 pending-writer 启动回执写入失败不能阻断原 TERM 路径。
- Nuke 宿主及固定 worker 从可信部署与持久 H 操作所有权重开相同离线来源，复验原渲染、停止、alpha 和 EXR。错误任务、范围、账本、来源及原件漂移均拒绝；不重启 H，不调用 H RPC。普通 Nuke-only 路线保留。

## 最终验证

| 验证 | 实际结果 | 原始证据 |
|---|---|---|
| 完整八阶段软件集成 | 1/1 PASS，83.720 秒 | [原始日志](evidence/20261020-alpha-final-chain/full-chain-final.log) |
| 最终受影响核心回归 | 42/42 PASS，15.951 秒，无跳过 | [原始日志](evidence/20261020-alpha-final-chain/core-final-current.log) |
| 运行库 controller 镜像 | 与权威源码一致，无需同步修改 | `tools/sync_controller_client.py` 只读检查 |
| 独立代码及集成证据复核 | 本轮限定范围无剩余 P1/P2 | [复核记录](evidence/20261020-alpha-final-chain/independent-review.md) |
| 候选冻结与只读预检 | PREPARED，未授权，0 启动 | [冻结核验](evidence/20261020-alpha-final-chain/candidate-final-audit.json)、[预检](evidence/20261020-alpha-final-chain/candidate-driver-preflight.json) |

八阶段依次为 alpha-husk、alpha-nuke、graph-worker、首次 H 宿主、重开 H 宿主、main-husk、Nuke 首存宿主、Nuke render worker。8 张预算票据均由签名停止原件确认成功；main-husk 与第二个 H 宿主共用整组停止事实，共 7 组独立停止记录。重操作区间无重叠。

软件链完成建图、保存、跨进程重开、参数与结构读回、渲染、独立输出验证、H 产物登记、NK 首存、固定 worker 冷加载和 Nuke 派生输出登记。两项产物保留相同 `controlled_output_v1/software_test` 来源；Nuke 依赖实际登记的 H 产物。最终 NK 与 worker 快照摘要一致；替换 NK 字节后最终验证拒绝，且不增加启动。原软件准备候选保持未授权、0 启动。

软件 API 夹具中的 HIP/NK 是受限序列化场景，不是已经通过原生应用验证的可交付工程。结果、来源与审计见 [软件集成结果](evidence/20261020-alpha-final-chain/software-full-chain-result.json)、[软件审计](evidence/20261020-alpha-final-chain/software-final-audit.json)。28 项本轮源码/测试指纹见 [源码清单](evidence/20261020-alpha-final-chain/source-sha256.json)。本轮没有重新运行全仓历史测试或重建安装包。

此前失败尝试的原始软件工作区与日志保留。full09 在相同源码下出现建图启动耗时异常；未证明具体环境原因。full10 的观察异常未留下原始异常类型，不能把后续复现的目录消失竞态断言为其根因。后续已补首次签名诊断。锁内核心回执读取/fsync 自身长期阻塞，以及持续性核心存储写失败，未被本轮精确修复宣称全面解决。

## 最新未授权候选

目录：`outputs/engineering-closure-20261020-h21-05`。158 项源码/静态快照文件与当前仓库及本次通过的软件链快照逐项同 SHA；准备回执另绑定 175 项不可变文件；旧 -01 至 -04 范围原件摘要未变。

| 原件 | SHA-256 |
|---|---|
| `scope.json` | `96e3c29e4406b7ac389133384b9d1a08bb0c00e1ba189a12c0c10c6f5f189019` |
| `runtime-bindings.json` | `a81b2ee018ced248fae2fd1e92f1aa73ac00baff6b418a065b58da36515dc1a8` |
| `engineering-activation-review.json` | `00b502eb6df2bf397b35b48ace554c9da4771ea2a85e9aadca003d1cdb2df0cc` |

候选为 `PREPARED_NOT_AUTHORIZED`、`execution_authorized=false`、0 票据；没有软件 API 替身配置。review 仅绑定未来的新目录 `outputs/engineering-closure-20261020-h21-06-authorized`，该目录尚未创建，未执行激活。

预算保持 8 次启动、单次 120 秒、累计 600 秒、512 MiB、同时一个重操作、自动重试 0。纯准备工具的总包装等待覆盖其顺序子工具，不增加上述 DCC 预算。

## 真实验收前边界

H21.0.631、Nuke 17.0v1、ACEScg 和八次资源预算沿用已确认决定。以后进入真实执行仍须明确授权上述最新 scope、运行绑定及新目标目录，并通过可信本地终端激活；不能改写旧范围。原生 alpha/预乘、许可证与启动、H21 stock beauty 的实际输出、Nuke ACEScg 设置及原生 HIP/NK 保存重开，均待真实阶段验证。内部 writer/filter/flush/close 继续为 `NOT_OBSERVED`，人工视觉检查为 `PENDING`。

本轮未启动真实 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、仿真、缓存或渲染；未改 Desktop 主工程，未提交或推送 Git。
