# Bridge 当前方向审计（2026-10-25）

本审计只读，未修改源码、未启动宿主或模型。维护仓库：`/Users/user/Documents/Code_Project/Bridge`。当前软件修复已接收；prepared-02 为 `PREPARED_NOT_AUTHORIZED`、零启动。真实 HIP/冷重开/性能、完整工程闭环、M1、HY3、视觉及生产均未通过。

## 最早实际阻断与准确完成标准

最近一次真实 H21 graph-worker 在建图240秒阶段工作截止线失败，账本计费229.438401秒；19条构造 COMPLETE、1条 INTENT；没有 HIP 和 worker 完成结果，第二进程冷重开未运行。旧 scope 已失败封闭。最后 `material_binding → camera` 的 INTENT 仅距停止3.848618秒，不能称其挂死；内部耗时首因仍未确定。[实际结果](</Users/user/Documents/Code_Project/Bridge/handover/H21_HIP_RESOURCE360_RESULT_20261024.md:9>)（23—29行）。

当前下一门是**对本次冻结软件候选取得真实 HIP 建图、保存及新进程冷重开证据**，不是重新补齐严格 writer 全部原生内部事实。prepared-02 source SHA-256 为 `ca635d07a487a70d3ed3ef6fe2710dbc5a897518ca5caf5012e64fe3878d1c00`；只有指向其冻结 review 的新具体授权才能激活独立范围。[本轮结果](</Users/user/Documents/Code_Project/Bridge/handover/H21_HOTPATH_REPAIR_RESULT_20261025.md:23>)、[接续顺序](</Users/user/Documents/Code_Project/Bridge/handover/NEXT_AGENT.md:45>)。

此 HIP 专项的完成标准：

1. 固定 H21.0.631 / sphere_ground_v2 / ACEScg，由冻结正式 graph worker 建图并保存真实可编辑 HIP，取得原始操作与完成回执。
2. 实际 Karma HDA 满足2.1完整定义及内部静态身份强绑定；公开控制、连接、冻结参数、材质、场景/工程身份、内容摘要与精确资源/输入读回完整成立。
3. 第一整组可信停止后，用第二个新宿主冷重开，验证 Embedded 定义、HIP 内容 hash 及完整合同；原有严格保存要求保持。
4. 建图240秒、冷重开120秒、累计360秒，包含启动、前置及停止，各阶段预留10秒；最多2次 DCC 启动、512MiB、单重作业、零重试。
5. 两个宿主停止、操作终态与槽分别核验；失败即停，未知停止保槽。该门不含渲染、Nuke、HY3、仿真或缓存。

依据：[候选合同21—33行](</Users/user/Documents/Code_Project/Bridge/handover/H21_HOTPATH_CANDIDATE_20261025.md:21>)；HDA合同完整性依据：[修复计划25—39行](</Users/user/Documents/Code_Project/Bridge/handover/H21_HOTPATH_REPAIR_PLAN_20261024.md:25>)。仅这一 HIP 门通过也不能把工程闭环标为通过。

## 已接收、不得无故重做的软件成果

| 已接收内容 | 精确依据 |
|---|---|
| producer 从3次全图采集减为 before/after 两次；after 在实际任务根租约围栏内，保留CAS、并发接管与身份验证 | H21_HOTPATH_REPAIR_RESULT_20261025.md:7 |
| 显式2.1锁定HDA完整定义/内部静态身份合同及公开参数读回；旧2.0/1.0原义与摘要保留；有界双时钟诊断 | 同文件:8 |
| 首次建图前新HIP内存路径；公共/注册入口共用稳定项目 output_root 资源绑定；两次不同SaveAs、完整重开和输入hash仍严格 | 同文件:9 |
| 参数、manifest、sidecar失败回滚；残留进入reconcile；gallery精确条件分类、HOM节点语义比较 | 同文件:10 |
| 软件新宿主独立scene identity；同宿主load/reload与导入失败恢复；必要底层HOM替身接口 | 同文件:11 |
| 112项精简核心覆盖已接收（111统一通过＋1过期固定路径断言定向补验）；13/13项目环境组合；最终双人只读复核本轮无明确P1/P2 | 同文件:15—17 |
| 160冻结运行文件同源、265＋207旧原件不变、controller镜像/补丁/ZIP/清洁解包核验 | 同文件:18—19 |

保留既有 v2 双版独立 prim/有效材质软件链、v1保存/反馈/冷重开兼容；Nuke lineage、颜色/alpha继承、raw/Write读回与回滚；进程身份及停止防线。[NEXT_AGENT.md:51—53](</Users/user/Documents/Code_Project/Bridge/handover/NEXT_AGENT.md:51>)。无新代码、新失败或新风险，不重复相同全量验证。真实alpha5个EXR只保留原版本/build/路线及原授权范围事实，不代替主场景或新完整链通过。

## 从当前候选到后续各门

| 里程碑 | 依赖与必须交付 | 需具体新授权 |
|---|---|---|
| A 当前软件候选 | 已完成prepare、冻结review和无宿主preflight | 当前不启动宿主 |
| B H21 HIP | A＋上列真实HIP完整完成标准 | 本次冻结review；H21/240、120、360秒/2启动/512MiB/单作业/零重试 |
| C H21主渲染→登记→Nuke | B成立；同路线原生alpha、主场景128×128单帧完整EXR、成功执行/可信停止、冻结配置与身份；controlled_output_v1独立验证；真实artifact ID/version/frame/colorspace/hash登记，Nuke消费，NK首存/冷重开/执行/写出读回及可读HIP/NK/图像 | husk渲染及Nuke的新独立范围。原完整工程8启动、每操作120秒/累计600秒/512MiB合同独立；不能续用HIP剩余额度或旧范围，也不能自行拼改缩减范围 |
| D 同任务反馈/恢复 | C成立；一个批准控制的实际反馈、新版本/失效/影响范围；另次实际worker中断、可信停止、重启控制端恢复、不重复副作用，产物与槽分开核验 | 对应宿主、反馈执行、中断恢复及预算 |
| H22.0.459兼容 | 独立兼容支线；补gallery精确compiled HOM模板/禁用条件，再按同版实际验证。当前文档没有规定H22必须在D后、HY3前，不新增硬依赖 | H22精确版本/build/case/采集或执行/预算/产物/停止的新范围；不把H21或旧429证据重标459 |
| E WorkBuddy桌面HY3 | C＋D成立；真实附件观察、计划、工具调用与反馈前后结果；会话/附件/身份齐备，人工补救单列 | WorkBuddy/HY3启动、外部模型/媒体传送、会话、素材、费用和时间范围 |
| F 第二输入复用 | E成立后冻结首例能力；构型/分布/目标明显不同的第二合成参考，同组合器/接口执行；不能新增案例专用分支或预置工程；同域和跨域分别判定 | 第二输入及其宿主/模型执行；动态smoke另列历史帧、仿真、缓存、空间与预算 |
| G 发布和长期验收 | 工程闭环后从冻结源码重建安装包；全16域48＋2、原54行及M1—M5仍按原标准分别接收 | 不自动恢复全域批量实现或真实作业 |

依赖主链依据：[NEXT_AGENT.md:45—58](</Users/user/Documents/Code_Project/Bridge/handover/NEXT_AGENT.md:45>)；[闭环门表68—81行](</Users/user/Documents/Code_Project/Bridge/handover/FEASIBILITY_AND_CLOSURE_20261016.md:68>)；[八启动合同55—69行](</Users/user/Documents/Code_Project/Bridge/handover/ENGINEERING_CLOSURE_20261020.md:55>)。H22缺口：[本轮结果29行](</Users/user/Documents/Code_Project/Bridge/handover/H21_HOTPATH_REPAIR_RESULT_20261025.md:29>)、[资源合同26行](</Users/user/Documents/Code_Project/Bridge/handover/H21_PROJECT_ENVIRONMENT_REPAIR_20261025.md:26>)。每次新申请的源码/build/任务/宿主/操作/媒体/总资源/停止要求见[授权要素119—128行](</Users/user/Documents/Code_Project/Bridge/handover/FEASIBILITY_AND_CLOSURE_20261016.md:119>)。

## 会误导下一步的文档事实

1. **活动路线文档保留了过期“当前阻断”。** [FEASIBILITY_AND_CLOSURE_20261016.md:13](</Users/user/Documents/Code_Project/Bridge/handover/FEASIBILITY_AND_CLOSURE_20261016.md:13>)、68、108、161仍把 `client.render_execution_fact` 固定BLOCKED、缺AVAILABLE转换及严格writer/颜色处理原生事实写为当前下一阻断和派工方向。与[NEXT_AGENT.md:45—46](</Users/user/Documents/Code_Project/Bridge/handover/NEXT_AGENT.md:45>)的controlled_output_v1及当前HIP门冲突；[STATUS.md:33](</Users/user/Documents/Code_Project/Bridge/handover/STATUS.md:33>)、61已明确固定BLOCKED属于历史严格路线。可能误派重复writer/processor研究或遗漏当前prepared-02。应最小标明历史范围并链接当前路线，保持原严格回执不变。
2. **被当前接续文档链接的工程合同仍以旧候选开头。** [ENGINEERING_CLOSURE_20261020.md:3](</Users/user/Documents/Code_Project/Bridge/handover/ENGINEERING_CLOSURE_20261020.md:3>)仍称18为“当前”真实验收、19为冻结候选；而[STATUS.md:2—4](</Users/user/Documents/Code_Project/Bridge/handover/STATUS.md:2>)和[NEXT_AGENT.md:2—4](</Users/user/Documents/Code_Project/Bridge/handover/NEXT_AGENT.md:2>)已经更新至HIP240失败及prepared-02。单独打开旧合同可能选择错误候选或误读旧授权。首段宜标为历史18轮并导航当前；完整8启动合同仍保留独立预算。

其余STATUS/NEXT_AGENT历史writer和旧候选段落已明确标历史适用范围，不把旧数值一律报为矛盾。112核心覆盖的定向补验与13项目组合已说明不累加，也不是计数矛盾。审计未修改以上文档。

本审计仅用记忆索引确认维护仓库和读取最新状态的边界，全部当前结论均由本次仓库文件核对；记忆引用：MEMORY.md:177—178，rollout `01a0be59-ac4f-7ac3-b77f-377255ad7186`。

