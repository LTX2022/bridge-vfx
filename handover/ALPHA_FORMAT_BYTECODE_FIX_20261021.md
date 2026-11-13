# Alpha 格式与监督器 bytecode 修复候选

两处最小修复已完成并冻结为 **-07 未授权候选**。Python 3.14 受影响核心24/24及Python 3.11兼容2/2通过；但唯一一次完整软件集成在 H 宿主进程身份采集处超时，**整链软件验收未通过**。本轮未重跑真实宿主，不能宣布修后原生 alpha 或工程闭环通过。

## 修复范围

| 问题 | 最小实现 | 验证边界 |
|---|---|---|
| Alpha 的 color4 数据被标量精度覆盖 | `tools/prepare_native_alpha_scene.py` 将 husk format 从 `float` 改为同版官方默认 `color4h`，保留 `dataType=color4f`、单一 beauty C、RGBA门及原数值容差 | 同版H21 `karmautils.py:425/488/534–535`支持该精度；本轮没有真实重新渲染 |
| Supervisor 写 pyc 改变冻结快照 | `owned_process.py` 启动监督器的 Python 命令固定增加 `-B`，同步 controller 镜像 | 不依赖环境变量，不改业务child命令、预算、停止事实或来源清单；不忽略/清理pyc |

软件alpha边界按实际USDA的RenderVar、format、产品引用、输出路径、分辨率、emission与opacity生成half RGBA；旧float明确拒绝且不产EXR，材质控制改变会改变像素。它不替代监督器、操作记录、签名回执、账本或原生husk事实。

监督器回归将实际运行库复制到临时冻结目录，显式清除 `PYTHONDONTWRITEBYTECODE` 和 `PYTHONPYCACHEPREFIX`，运行真正Python子进程；认证started/stopped，并比较全文件集合及摘要。旧实现先红，产生6个pyc；修后不产生新增文件。该用例无writer采集，不声称复演-06全部原生路径中的7个pyc。

相对原-05的158项生产快照，只有上述两个源文件变化；controller镜像与权威运行库一致。六份本轮源码/测试指纹见[清单](evidence/20261021-alpha-format-bytecode/source-sha256.json)。没有重做其他模块。

## 最终验证

| 验证 | 结果 | 证据 |
|---|---|---|
| Python3.14受影响核心 | 24/24 PASS，14.846秒，无跳过 | [日志](evidence/20261021-alpha-format-bytecode/core-final.log) |
| Python3.11两项兼容核心 | 2/2 PASS，1.069秒 | [日志](evidence/20261021-alpha-format-bytecode/compatibility-311.log) |
| 监督器旧版反例 | FAIL，捕获冻结目录新增pyc | [原始红日志](evidence/20261021-alpha-format-bytecode/supervisor-bytecode-20261021-red.log) |
| 唯一一次完整软件链 | **1 FAIL，42.966秒** | [原始日志](evidence/20261021-alpha-format-bytecode/full-chain-final.log) |
| 新候选默认预检 | PREPARED，0启动、未授权 | [预检](evidence/20261021-alpha-format-bytecode/candidate-preflight.json) |
| 两模块独立代码复核 | 限定范围无剩余P1/P2，整链失败仍保留 | [独立复核](evidence/20261021-alpha-format-bytecode/independent-review.md) |

完整软件链使用Python3.14，清除上述环境变量，不启动真实DCC。Alpha阶段已完成；随后首次H宿主在 `task_host_serve → observe_process → vmmap → _remaining` 抛出 `PROCESS_IMAGE_TIMEOUT`，范围以 `NATIVE_SCOPE_EXECUTION_FAILED` 关闭。

该软件范围有4张票据：alpha-husk、alpha-nuke、graph-worker停止成功；首个H宿主停止确认但执行失败。四者均有原始认证停止且无未知后代，见[认证停止审计](evidence/20261021-alpha-format-bytecode/software-integration-audit.json)。累计约34.4601秒，未触及600秒/512MiB上限；158项软件快照字节一致、无pyc或其他新增文件。后续阶段没有完成，不能登记完整链PASS。

身份采集路径及其时限本轮未改，超时具体根因尚未确定；未加长超时、放宽身份校验或重复整链。本次结果不能证明该失败与两项修复存在或不存在因果关系。它是后续接收前仍须处理的软件集成阻断。

## 新候选与保留证据

目录：`outputs/engineering-closure-20261021-h21-07`。158项源码/静态快照与当前仓库及本次软件验证快照逐项同SHA；准备回执的175项不可变文件核验通过。

| 原件 | SHA-256 |
|---|---|
| scope | `4e9533ca678aa3dd4f0d70b64691656d3f9d011b5b57dddd998ca9b5c6deea35` |
| runtime bindings | `90f653026ed5ebb32ac906a1d9ece54905c9852fc6d3d2cac5594eeba5c205be` |
| activation review | `f4f0e1ad7f8fadf75bd279491b5e50b9bfa936dd14e60968ccba5c222b2ecf4b` |

- 状态为 `PREPARED_NOT_AUTHORIZED`、`execution_authorized=false`、0票据，没有软件替身配置。
- 预算保持8次启动、每项120秒、累计600秒、512MiB、单重作业、零自动重试；ACEScg与H21.0.631/Nuke17.0v1保持。
- review只绑定未来新目录 `outputs/engineering-closure-20261021-h21-08-authorized`；该目录不存在，未激活。预检PREPARED仅证明配置完备，不改变整链未通过结论。
- 使用未执行的-05作为准备输入，没有复用失败-06的密钥或账本。新候选核验见[审计](evidence/20261021-alpha-format-bytecode/candidate-final-audit.json)。

真实失败范围-06的全部 **242个文件** 与修复前基线逐项同SHA，包含原EXR、USDA、签名回执、私有认证原件和7个pyc；没有新增、删除或修改。见[保留核验](evidence/20261021-alpha-format-bytecode/frozen-06-preservation.json)。保留清单仅记录摘要，不复制密钥值；原[首轮真实失败报告](H21_FIRST_LIVE_20261021.md)不改写。

本轮没有重跑Houdini/husk/Nuke、WorkBuddy/HY3、模型、仿真、缓存或渲染；没有调整RGBA门、容差、执行预算或来源规则，没有重建安装包、提交或推送Git，也没有修改Desktop主工程。真实工程闭环、全16域M1、HY3、视觉及生产验收仍未通过。
