# Bridge 代码提交与接手说明（2026-10-05）

本次按用户明确要求提交此前保留的源码、测试、Plugin入口、产品定义和接手说明，基线为`d48fa10d32b95ce322e22b7b1ae39f947f3b1126`。这是继续开发的阶段提交，**全16域M1仍未完成，不是生产发布**。北京时间12:00截止未达成；缺失事实、失败、跳过及未执行项如实保留。

## 项目总目标

Bridge将参考图片/视频、制作意图、个人偏好与项目规范，转成可编辑的Houdini/Nuke工程，并通过读回、保存重开、预览反馈、受控执行和产物验证完成制作闭环。最终链路为：参考登记→结构化观察→分域视觉目标→能力组合→正式建图→保存/重开→预览→反馈修改→授权缓存/渲染→Nuke合成→验证/交付。

交付结构为四层：`packages/`执行核心；私有上下文/知识读取；`agent-plugin/`中的AI平台Plugin及MCP薄入口；精简Skill路由与按需文档。保留`plugins/`中的DCC宿主插件。Plugin和Skill都调用共享核心，不建立第二套业务实现。当前私有上下文实现为项目/版本过滤、有限只读、摘要绑定和来源引用，自动学习、发现及写回未实现。

当前16域为：烟、火、粒子、海洋、FLIP水体、人群、Swarm、布料、软体/颗粒、毛发、刚体破坏、程序化几何、材质、灯光/相机/渲染、Nuke合成、爆炸组合。对应ID和验收定义以`tools/readiness_evidence.py`及原17项合同为准；54行要求、48+2案例不能用局部用例替代。

| 里程碑 | 完成标准 | 本次提交状态 |
| --- | --- | --- |
| M1 软件准备 | 同一源码的全16域、17项合同、54矩阵、48+2案例、三类安装生命周期和独立接收 | 未完成；有限实现和软件证据已提交 |
| M2 真实宿主 | 指定Houdini/Nuke版本实际建图、重开、短帧、停止恢复和产物 | 当前版本NOT_RUN |
| M3 AI平台 | WorkBuddy/HY3或选定平台的实际附件、观察、调用、反馈与路线证据 | 当前版本NOT_RUN；独立MCP验证不等于平台UI验收 |
| M4 视觉创作 | 可编辑HIP/NK、动态输出、修改前后效果和人工视觉接收 | 未完成 |
| M5 组合与生产 | 两条组合消费可信上游，另一案例、生产恢复及交付成立 | 未完成 |

本轮执行授权仍限软件边界。Houdini21.0.631为主、22.0.429为兼容目标，Nuke17.0v1；未启动真实DCC、HY3、模型、仿真、缓存或渲染。提交代码不扩大真实作业授权，macOS结果仍待目标机器。

## 已实现及执行结果

| 工作 | 实际结果 | 范围和限制 |
| --- | --- | --- |
| Windows底座 | 共用文件锁、私有文件、原子替换、中文路径、进程身份和Job监督已适配并定向验证 | 停止事实须直接子进程等待和进程树为空；未知停止保留槽位；macOS不继承WindowsPASS |
| RBD/材质首批 | RBD时间状态、完整activation通道/回滚及两版新PID读回；材质最终绑定与渲染配置双读回；灯光实际布局断言 | 软件API证据，不能证明真实模拟或渲染 |
| Swarm S01/S02 | 两版当前底层API与正式任务宿主完成秒制目标噪声/独立受力支路、保存、新PID/nonce直接重开 | 第二实例不build/apply；旧nonce拒绝；原始两版5.797/5.688秒 |
| 材质全11控制 | 两版逐项写入、保护其他字段，保存后签名stop/Job0，再新PID直接读HOM、最终USD绑定与配置 | 初次5.844/5.891秒；最终来源两版5.985/6.000秒；不等于完整GraphRun/登记通过 |
| 新PID测试发现 | 同一父进程预导入根包，再发现Swarm/材质四方法，委派独立解释器 | 4项24.345秒，0FAIL/ERROR/SKIP；实际driver退出1被父端拒绝 |
| pending资源生命周期 | 实际资源owner保留API/环境/目录；生成handler输出故障也退出；清理错误保留原实例和未知事实 | 5项退出0；两条实际隔离Python进程exit2/Job0；L02/L03限定关闭，完整MCP中断未验 |
| 输出终态封存 | 实际producer绑定signed started和新运行key封存不可变原件，重摘要替换和controller补签拒绝 | 14项受控子进程测试通过；P1限定关闭，颜色/alpha事实仍缺 |
| 正式原生操作证据 | schema2原件以同owner/op/graph/attempt的相对locator公开；核对字节、来源、session、保存和signed stop | 正式生成入口16.875秒，52条build/edit/inspect/save；帧1/3输出解码成立，完整登记BLOCKED |
| 登记/图作业回归 | 无源码绑定的Houdini旧登记回退被拒绝，typed registry和资源owner合同保留 | 新接线29项、图作业/registry47项，均退出0、无FAIL/ERROR/SKIP |
| 粒子P02 | 有界size参数计划、稳定ID/subseed/basis与实际参数读回 | 8项退出0，仅parameters_only，尚未接入完整原生writer |
| 执行开销 | 静态模板索引复用；日志摘要提前剪除旧输出目录，扫描EIO继续传播 | 日志扫描同摘要一次比较10.437→0.125秒，修复后一次0.094秒；最终8项通过，P2-LHP01关闭；不是整项目提速倍数 |
| Plugin/私有上下文 | 独立MCP薄入口、构建校验、显式配置与受限知识读取已实现 | 旧20:55包7项stdio/6个安装生命周期只绑定其原包；当前平台UI和最终新包未验 |
| 产品定义 | 用户批准的20项定义及B组合合同、冻结输入和缺项校验已实现 | APPROVED不是native PASS；Swarm两项有限完成，其他18项仍缺完整原生实现/证据 |

各计数来自不同阶段，不能相加成为同源码全量通过。历史标准软件全量为1281项、1FAIL、4ERROR、31SKIP；五条异常完成相应定向整改，**没有重跑最终当前源码的全绿全量**。正式入口审计退出0表示正常采集及预期拒绝成立，完整case仍为`BLOCKED`，不是成功登记。

## 必须继续的未完成内容

| 优先级 | 未完成项 | 下一步与完成条件 |
| --- | --- | --- |
| P0 | 可信输出颜色/alpha及完整登记 | 取得有效OCIO配置/LUT/context/file-rule、实际最终输出/AOV、有序filter执行与beauty alpha关联；绑定原件和实际输出后再登记，不填写默认linear或premultiplied |
| P1 | 其余18项批准控制 | Pyro flame_height；FLIP collision_separation/collision_passes；RBD fracture_scale/fracture_variance/impact_spread/piece_scale/velocity_variance/impulse_scale；粒子emission_variance/size_variance/collision_radius/trail_length/motion_blur_scale；Ocean directional_spread；几何scatter_variance/rotation_variance/deformation。需要同版本合法接口、真实basis/稳定ID、writer/collector/事务回滚和下游消费；P02 helper不代替完整控制 |
| P1 | 正式控制端与恢复 | typed primitive不能代替完整域语义；继续typed当前task_save、preview/cache、持久输出及Nuke producer；中断该案例实际执行进程，恢复同一操作/版本，不重复渲染，最新保存HIP须被下游消费 |
| P1 | B组合与降噪 | 球壳中心/半径时间函数、屑源尺寸/父片/稳定ID/登记变换需显式输入；两条组合实际消费登记上游。raw/denoised两个独立可信producer、帧/layout/颜色/alpha及正式混合/登记未闭合 |
| P1 | 全域案例与矩阵 | 完成16域三场景48项和2条组合，逐行补54要求；缺失、陈旧、not_run或诊断回执不是PASS，不把52条primitive自动提升为全域证明 |
| P2 | 最终软件与安装接收 | 实现稳定后冻结一次当前源码，运行一次标准软件全量并分类失败/跳过；新三类Skill/Plugin包安装升级/失败回退/只读卸载、generated server→默认监督worker及独立接收均需绑定该build |
| 后续 | 目标机和产品验收 | 按[macOS清单](MACOS_REVERIFY_20261004.md)补POSIX实跑；真实DCC/HY3/模型/视觉/生产阶段另需具体授权和输入，不沿用旧或Windows证据 |

产品定义无需重复批准：[批准记录](CONTROL_DECISIONS_20261004.md)和[原批准建议原字节](evidence/20261005/product/control-decisions-proposal.md)。缺失原生事实必须继续明确；项目不允许通过弱化校验或生成成功回执来补证据。

## 证据、源码与接手入口

- [Git内证据说明](evidence/20261005/README.md)、[文件来源及SHA清单](evidence/20261005/index.json)：保存精选实际日志、结果JSON、独立复核和批准建议原字节。原始完整运行目录保留本机`outputs/`，未将运行key或认证token带入Git；本证据集不是可重验签的完整运行包。
- [最新进展](PROGRESS_20261005.md)、[项目状态](STATUS.md)、[完整计划](MASTER_PLAN_20261004.md)、[剩余项](REMAINING.md)、[下一位Agent](NEXT_AGENT.md)及[环境说明](ENVIRONMENT.md)。先按本文和这些文档继续当前源码，不重复已经关闭的局部修复。
- Git内代码包含`packages/`、`plugins/`、`tools/`、`tests/`、`agent-plugin/`、`skills/`和`controller-entry/`。后者为生成镜像；本次最终同步check无差异，修改后仍按正式生成流程验证。
- 提交前开发源码冻结759文件，相对d48fa10的216项变更，正向/恢复补丁均实际重放且字节清单相同。该冻结见[原结果](evidence/20261005/source-patch-final-v3/result.json)，是补充本文/入库证据前的开发快照，不等于此次提交文件数或已通过M1。完整补丁及旧移交包仍保留本机。

此提交保留当前有效开发方案与必要审计说明。没有覆盖旧移交包、回退有效改动或修改原Desktop主工程。后续实际执行应记录命令、退出码、原始日志、解释器/系统、源码和生成快照摘要；无新修改或风险不重复全量。
