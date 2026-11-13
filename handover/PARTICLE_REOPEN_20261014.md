# P01 冻结输入与可信新实例恢复（2026-10-14）

本批补齐 generated worker 显式 seed、可信 graph handoff、保存合同与新 PID/nonce 私有登记。Houdini 21.0.631、22.0.429 的受控 Python/TCP 正式链已实际通过；仍只证明参数表达式及其软件生命周期，不证明 POP 子步发射、实际粒子数量或真实 DCC。全 16 域 M1 尚未完成。

从 Git `0a52552f5915375dfb0f3551e08928e9e624390d` 的现有工作区继续，保留此前有效增量；未新建分支、提交或推送。环境为项目 `.venv` Python 3.11.9，Windows 10.0.26300。所有 host/worker 使用明确软件配置、底层 HOM API 夹具和实际监督器；真实 Houdini/Nuke/HY3、仿真、缓存、渲染未运行。

## 实现与边界

- `graph_construction_inputs.py` 从冻结的唯一 `particle_emission_basis` 文件稳定读取严格 UTF-8 JSON，仅接受显式非 bool 的 int32 `task_seed`；拒绝重复字段、额外字段、重复角色、超出 4 KiB、路径/内容漂移。不默认 seed，不把它替换为 POP 原生 seed。
- `graph_job_worker.py` 与 addon 在建图前核对冻结输入；其他域不能忽略 particle basis。无 seed 的旧粒子控制继续原无私有 P01 authority 路线。
- `native_particle_emission_host.py` 保存完整参数驱动、keys/表达式语言/外推、严格界、时钟/FPS、gates、节点状态、basis、角色、任务与宿主身份的有界 checkpoint。JSON facts 统一序列化，避免 tuple/list 差异掩盖实际一致性。
- 恢复必须有已登记保存合同、实际 HIP 摘要与原生节点/参数/连接核验；checkpoint 必须与加载 HIP 内的 manifest 一致。私有 scope 反复核对实际 userdata、身份、租约、artifact 和 opaque pointer；普通 embedded checkpoint 或自行重摘要不能授予恢复 authority。
- generated worker 只为带显式 `particle_emission_basis` 的 particles_v1 签发合同标记，选择正式 `scene.reopen_task_hip` 协议。控制端先核验结果/文件/停止事实，宿主再验证保存合同、精确 owned root 与租约，最后绑定图；无基准粒子和其他域保留各自已有的交接路径。
- 保存合同及不可变 snapshot 共享；RPC、runtime、root lease、task sidecar 与可变 operation store 隔离。共享可变操作记录曾使存活宿主拒绝另一进程推进，已恢复隔离，保留原失败日志。
- 重开按已核验合同的 `execution_root` 选择实际加载 manifest，避免旧 sidecar 指向旧图；只在可信恢复 scope 内同步当前 sidecar，失败恢复其原快照。未放松 task/root/hash 或原生校验。
- 完成提交后的最后 native capture 再核验 HIP/身份与登记指针，最后 node collector 后重采 gates；reconcile 在完整合同核验后重新读 checkpoint。失败仅 CAS 撤销自己的登记和精确完成记录，不覆盖 successor。
- `agent.fx.collect_evidence` 可在新实例直接读取保存后的 P01，不重新 apply；实际读回仍为 `BLOCKED/native_parameter_expression_only`，保留原生消费缺项。

## 实际验证

下列五组是 R06 修复前的阶段证据，各自前后 442 份 Python 源码相同。它们证明记录版本的 checkpoint/保存/恢复组件及后续新 PID 恢复，初次 graph handoff 当时仍走普通 open；不得据此声称新增可信初次交接已通过。最终过滤器与正式分支单独在修复后验证，未重复未改的 79/82 方法。

| 当前源码组 | 方法数 | 失败/错误/跳过 | 退出码 | 原始结果 |
| --- | ---: | --- | ---: | --- |
| P01 checkpoint / 输入 / addon / private host / mirror | 79 | 0/0/0 | 0 | `p01-reopen-final-20261014` |
| 共用输入/运输/保存/场景合同与 RBD/G03 恢复 | 82 | 0/0/0 | 0 | `p01-common-facts-final-20261014` |
| P01 正式两版正常及缺失/篡改 checkpoint | 1（含两版及各两类拒绝） | 0/0/0 | 0 | `p01-formal-current-root-20261014` |
| 受影响 RBD/G03 正式两版 | 2（各两版） | 0/0/0 | 0 | `p01-related-formal-final-20261014` |
| 共用交接材质/灯光/Crowd 正式两版 | 1（六个版本/域案例） | 0/0/0 | 0 | `p01-shared-handoff-formal-final-20261014` |

R06/R07 阶段的 `p01-marker-fixed-final-20261014` 实际通过 52 方法，退出 0、无失败/错误/跳过；随后已执行的 `p01-verified-formal-final-20261014` 中 P01/RBD 通过，G03 拒绝，整体退出 1，其他三域未执行，不能算正式全组通过。最终路由收窄后的 `p01-routing-final-20261014` 通过 61 方法，93.406 秒；`p01-routing-formal-final-20261014` 通过 4 方法，765.281 秒，包含六域两版。两组均退出 0，无失败/错误/跳过，443 份源码前后及当前一致。

| 最终当前源码 | 方法数 | 失败/错误/跳过 | 退出码 |
| --- | ---: | --- | ---: |
| `p01-routing-final-20261014`：marker/两域 worker/共用输入与调度 | 61 | 0/0/0 | 0 |
| `p01-routing-formal-final-20261014`：六域两版正式软件链 | 4（涵盖六域两版） | 0/0/0 | 0 |

当前 P01 正式原件记录 H21 PID 21804→21488、H22 PID 38508→39092，nonce 亦不同；实际 operation store 记录初次 handoff 为 `scene.reopen_task_hip/COMPLETED`，摘要保留到最终 trial verification。每版 generated worker 使用显式 task seed 173，原生 emission seed 保持 17；实际候选 45% 与 birth_rate 2300 保存后，新 PID 直接读回完整表达式/驱动/gates/时钟/参数，恢复原帧，没有 load 后原生写入。原监督器记录直接子进程等待、Job active_processes=0 和槽位释放；缺失 checkpoint、自改表达式并重摘要的保存合同在新 PID 拒绝。

实际命令完整保存在对应 JSON 的 `command`，中心 runner 为 `outputs/all-domain-20261009/run_tests.py`，冻结前后摘要包含 packages/plugins/tests/controller 及指定边界/runner。例如：

```powershell
$env:BRIDGE_TEST_P01_AUTHORITY_ARCHIVE = Join-Path (Get-Location) 'outputs/particle-reopen-20261014/formal-routing-final'
$env:BRIDGE_TEST_RBD_AUTHORITY_ARCHIVE = Join-Path (Get-Location) 'outputs/particle-reopen-20261014/related-rbd-routing-final'
$env:BRIDGE_TEST_GEOMETRY_INPUT_ARCHIVE = Join-Path (Get-Location) 'outputs/particle-reopen-20261014/related-g03-routing-final'
$env:BRIDGE_TEST_REGISTERED_DOMAINS = 'material_lookdev_v1,lighting_camera_render_v1,crowd_agents_v1'
$env:BRIDGE_REGISTERED_DOMAIN_EVIDENCE_DIR = Join-Path (Get-Location) 'outputs/particle-reopen-20261014/related-registered-routing-final'
.venv/Scripts/python.exe -B outputs/all-domain-20261009/run_tests.py p01-routing-formal-final-20261014 test_particle_emission_authority_process test_rbd_authority_process test_geometry_construction_process test_production_task_hosts.ProductionTaskHostsTests.test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen --failfast
```

这个 label 和 archive 已存在，复验必须换新名字，禁止覆盖。离线目标机可按 [macOS 清单](MACOS_REVERIFY_20261004.md) 使用标准 unittest，不依赖 ignored outputs 的 runner。

## 诊断与独立复核

先前 `p01-registered-baseline-20261014` 两版实际入口拒绝 `PARTICLE_EMISSION_AUTHORITY_REQUIRED`，证实 frozen seed 没有消费。后续诊断记录依次暴露 JSON 类型差异、旧底层夹具缺必要节点 API、producer identity 字段不完整、实际 addon state suffix、共享可变 operation store 冲突、旧 sidecar 选择错误；原件均保留为 FAIL，不计入最终通过。

`p01-unit-integration-diagnostic-20261014` 的 39 方法断言通过，但运行期间另一源码文件变化，runner 退出 1，因此不计冻结验收。较早 common-environment 30 方法仅对应当时源码。本批不重复全 16 域全量，没有以旧 PASS 替代本批结果。

独立 reviewer 未参与对应实现，R01–R05 限定发现已整改；随后 R06 发现公有结果过滤器丢失真实保存合同摘要，原先成功的后续新 PID 恢复不能证明初次 trusted handoff。现已在两次 schema 过滤及 operation 存取中保留严格 64 位小写十六进制摘要，present 但不合法直接拒绝，不降级到普通 open。R07 随后实际入口暴露新分支漏传必填 HIP SHA，现已传已有核验摘要，原控制端校验不变。

初次 marker 单元组 52 方法中新增 SQLite 夹具错误导致 1 FAIL/1 ERROR：误读 job 顶层 graph_hash，及临时目录删后 cleanup 访问数据库。已改用实际 compiled 文件并调整 cleanup 顺序，最终同组通过。旧 marker 正式诊断被定位为同一缺 SHA 错误后停止，实际退出 1；其日志及已结束案例保留为诊断，不算通过。中心 runner 新增显式 `--failfast`，后续首个失败即停止并执行原 finally 清理，避免跨版本/域重复同一根因。

R08 的静态链路显示：把本批 P01 初次恢复协议扩到 G03 后，task reopen 与现有 graph bind 两处都会调用恢复登记；已恢复 cohort 再遇旧 CP 时仍受精确身份/替换校验。实际正式入口以 `GEOMETRY_REGISTERED_COHORT_REQUIRED` 拒绝，具体哪一条比较发出该码未追加 trace，不冒认更细事实。修复是约束协议适用范围：仅显式 P01 基准签发标记，G03/RBD/材质/灯光/Crowd 和旧无基准粒子延续原验证路径；没有放松 cohort 或新建重复授权接口。对应 worker 的正向及 marker 存在/缺席断言、六域两版兼容回归均实际通过。新增初次 trusted route 只在显式 P01 验证，不宣称其余五域使用新协议。

独立复核结论为 **R01–R08 CLOSED_SCOPED**，最终 `pending=[]`、无本批具体 P1/P2 阻断，绑定当前 443 份源码、两份最终报告、实际日志与生命周期。详见 [独立结论](evidence/20261014-particle-reopen/raw/outputs/particle-reopen-20261014/review/CLOSURE_FINAL.md) 及 [证据与复验入口](evidence/20261014-particle-reopen/README.md)。它只接收 P01 新初次 trusted handoff 和必要的其他域兼容回归，不是全域或真实宿主接收。

Git 内新证据目录保留 1,537 份原件、原始总计 69,414,120 字节；超过 8 KiB 的非 Markdown 原件无损 gzip，记录原始/归档 SHA-256 并逐件解压核验。包含失败原件、正式生命周期、native API 调用、生成快照与底层边界摘要，不复制运行签名密钥。查看 [索引](evidence/20261014-particle-reopen/index.json) 和 [源码绑定](evidence/20261014-particle-reopen/source-binding.json)；前置阶段与最终源码有明确差异列表，未要求旧全仓库摘要冒充当前摘要。实际结果仍为软件参数范围，不授予缺失的原生消费事实。

下一批 P03 的只读准备见 [采集与入口清单](evidence/20261014-particle-reopen/raw/outputs/particle-reopen-20261014/next-batch/P03_NEXT.md)：产品定义明确，静态资料不足以实现独立物理半径消费者；其中命令未执行，不计本批 PASS。

## 剩余范围与下一步

P01 尚缺同 build 的实际 POP 子步时间、发射积分/数量与最高速率消费事实，真实新实例行为也未验证。P03 物理半径、G03/R05 非零原生效果、其余未闭合控制、B 组合输入/消费、实际 writer/output/filter/alpha、降噪/Nuke、48+2/54 矩阵、最终全量/安装与全域独立接收仍缺。macOS 待目标机器验证。

后续保留本批 trusted save/reopen、实际状态隔离和最终采集守卫，先推进可合法取得的公共输出执行观察和 P03 消费边界；缺真实原生事实明确拒绝，不能按期望生成成功值。真实阶段需要另行具体授权。
