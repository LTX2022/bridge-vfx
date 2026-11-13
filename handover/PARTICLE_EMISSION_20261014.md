# P01 粒子发射波动修复（2026-10-14）

本批在 `0a52552f5915375dfb0f3551e08928e9e624390d` 后的有效未提交改动上继续；保留 [R05新实例恢复](RBD_REOPEN_20261013.md)、G03及输出观察成果。新增 P01 的有条件参数表达式实现，接入实际 addon 候选、读回及原有持久化事务。**全16域 M1 仍未完成，P01实际求解消费及新PID恢复没有通过。** 没有启动真实 Houdini/Nuke、模型、仿真、缓存或渲染，没有提交或推送。

## 本批实现和根因

改前根源码 `native_particle_ocean_geometry_domains.candidate_write_plan` 对两版 P01 均返回 `PARTICLE_EMISSION_VARIANCE_NATIVE_FIELD_NOT_CAPTURED`。原件见 [基线](evidence/20261014-particle-emission/raw/outputs/particle-emission-20261014/baseline-current-entry.json)。该基线只调用实际原生候选计划入口，不冒称正式 TCP 全生命周期。

- 新增 `native_particle_emission_program.py`：采用已批准的 `birth_rate × (1 + percentage/100 × u)`，按实际出生起点起算的一场景秒桶固定 hash/seed；幅度或基础 rate 改变不重新采样随机因子。表达式显式导入 hou/math/hashlib，不依赖控制端 globals；零幅度恢复无驱动常量。有限值、路径/字节预算、数值塌陷和完整分布边界分别验证，不截断到 UI 滑条。
- 新增 `native_particle_emission_host.py`：明确配置 `constraints.fx.particle_emission_basis={"task_seed":173}` 才尝试注册；不自动虚构 seed、出生时间或网络时钟。由已租约授权的新 emission 节点、完整宿主身份和实际 session 建立私有记录。用户数据、重摘要 basis、旧 HIP 和旧身份均不能授予权限。
- 网络 clock 使用实际 HOM parameterTemplateGroup 有界扫描，按官方 Offset Time/Scale Time 标签唯一发现 machine name；不猜网络 startframe/timescale 字段。保持完整 clock channel、FPS、九项出生 gates及 probemit/seed/jitterbirthtime；网络与 solver scale 当前均要求1。缺、驱动不符或漂移明确拒绝，不扩展未经证实的时间换算。
- 原生 constantrate 的实际严格 min/max 进入冻结上下文；写前检查整个分布，写后及末端重查。缺少严格界时保留 `native_rate_hard_limits` gap，UI range 不充当硬界。
- P01 与 birth_rate 组合为同一个实际写入；修改基础 rate 保留已登记的波动幅度。复用原 shared candidate 的 root fence、参数快照、manifest保存和失败回滚，完整核对表达式语言、keys、外推、驱动及独立 evaluated rate。建图外层异常使用 exact-record CAS撤销自己发的临时注册，保留后继记录并允许 fresh retry。
- manifest 写入完成后再次核对 P01 的实际私有/原生状态，失败进入既有 manifest和参数恢复；外来 gate 的变化不会被偷偷覆盖。controller-entry 两个新模块及 core 副本已同步。
- 最后补修普通 public build 的外层事务入口，并在真实 BeforeClear/BeforeLoad/BeforeMerge callback 撤销旧场景私有记录；同路径新节点不会错误继承旧登记，缺P01配置的新场景仍可修改原birth_rate。该修复来自限定复核的R08/R09，早期REQUEST_CHANGES保留原件。

实际 POP Source 常量出生率按秒计，Python多行表达式作为函数体执行；场景时间与 DOP 时间可能不同。滚动官方文档只约束合法接口，不充当两版运行证据。[POP Source](https://www.sidefx.com/docs/houdini/nodes/dop/popsource.html)、[Python expressions](https://www.sidefx.com/docs/houdini/hom/expressions.html)、[DOP Network](https://www.sidefx.com/docs/houdini/nodes/obj/dopnet.html)

## 验证、整改和证据

项目 Python3.11.9，Windows10.0.26300。三个 GPT-6.1-sol high 子 agent 分别编写纯程序、编写底层宿主测试和只读查原生接口；主 agent负责 Host、shared core/addon和集成。独立 reviewer没有实现本批代码。完整命令、退出码、原日志和 source_before/source_after 见 [证据索引](evidence/20261014-particle-emission/index.json)；源码绑定覆盖435个 Python文件，另列 native_schema_test_boundary 摘要。

| 执行记录 | 结果和限制 |
|---|---|
| `p01-final-20261014` | 54方法、0失败/错误，退出0，36.531秒，源码前后不变。两个 Oceanfoam 静态审计子用例缺原件，保留 NOT_RUN/skip；不是完整静态验收。 |
| `p01-closure-final-20261014` | 建图外层事务的组件补修后，受影响 Host/addon/controller 24方法，0失败/错误/跳过，退出0，34.844秒；该阶段435源码前后相同，随后R08/R09复核发现普通分支遗漏。 |
| `p01-lifecycle-final-20261014` | R08/R09接线补修后的当前最终组：25方法，0失败/错误/跳过，退出0，50.265秒；435源码前后及当前一致。实际public建图进入事务、清场→新建→legacy birth_rate路径通过。上行24组为较早冻结阶段，不冒充当前源码复跑。 |
| 纯程序/旧 P02及 core 回归 | 第一组保留14项纯程序和原有路由/副本验证；其消费模块字节未因最后建图补修改变。两组有重叠，不能相加为78个唯一用例或宣称当前54方法全量重跑。 |
| 独立审查 | R01–R09 的实际底层API反例、manifest落盘边界及场景/建图接线探针分别保留，整改后复核绑定最终字节；结论范围见 [限定复核](evidence/20261014-particle-emission/raw/outputs/particle-emission-20261014/review/CLOSURE_FINAL.md)。 |

正常集成使用实际 software_host_client、addon dispatch、建图、公开 apply_candidate、scene.save_hip和manifest恢复；HOM/UI时钟模板及 Python channel 求值是显式底层API夹具。测试中的时钟 machine names为独立通用模板观察输入，不声称同build静态捕获。P01初始化组件在已建自有图上单独验证；公开建图事务使用原contextmanager的被动记录核对。本批没有运行 generated server/TCP 的 P01 fresh init完整链、新PID重开或原生子步求解。

保留首次schema拒绝未知机器字段、错误候选参数位置、错误save命令和未补齐setKeyframes表达式读回等测试接线失败原件。修复仅扩充测试自身所需的合法底层通道API，没有放松生产快照/回滚，也没有把历史失败重标PASS。动态 evaluated 值不属于恒定 channel定义身份，仍与实际原生求值独立核对。

## 未完成及下一步

1. P01仍返回 `BLOCKED/native_parameter_expression_only`：实际 POP子步调用时间、跨秒积分/残余取整/概率出生、最高 rate消费、完整 producer恢复及 verified new-PID checkpoint缺证据。当前只支持已观测的单位 network/solver time scale，不能默认推导其他倍率。
2. P03独立物理碰撞 radius继续 BLOCKED：已审计资料不证明独立于render pscale的合法消费；Source relaxation radius和Hair/Vellum事实不能代用。其余已批准控制、G03实际变形/实例消费、R05非零效果和B组合继续实施，缺输入不默认。
3. 公共输出仍缺实际 husk/writer生效配置、每AOV processor、有序filters及alpha关联；父 OCIO稳定快照不代替输出事实。Nuke可信双producer/raw-denoised混合、48+2/54完整案例、最终同源码全量、安装和全域独立接收仍未完成。
4. macOS沿用源码但待目标机验证，见 [复验清单](MACOS_REVERIFY_20261004.md)。不要无变化重跑已关闭的R05/G03故障组，也不要从软件期望值生成非零成功几何。

没有新增完整发布包，本批证据归档不覆盖旧包、历史日志或其他账号工程。现有 task/graph/producer状态机保持原验收门槛。
