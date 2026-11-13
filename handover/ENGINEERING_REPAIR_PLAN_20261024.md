# 工程闭环有限修复计划（2026-10-24）

状态：待独立只读审核；本文件不是实施、候选冻结或真实启动授权。
范围：Houdini 21.0.631／Nuke 17.0v1、sphere_ground_v2、ACEScg；全16域扩展冻结。
约束：8次启动、单次120秒、总600秒、512MiB、1个heavy、0自动重试；20真实scope未授权。
本次已确认待修：生产代码0项；现有交接文档2项。下游未知不计作代码bug。

## 一、证据与边界

已读AGENTS.md及 handover/H21_LIVE_18_RESULT_20261023.md。
本轮依据均位于 handover/evidence/20261023-h21-live-18/：software-final-review.md、remediation/RESULT.md、remediation/native-basis/read-only-findings.md。
18真实：3/8启动，全部可信停止；41个构造操作完成，domain.initialize未完成；无HIP、NK、主EXR。
19软件：HDA边界和Object类别已修，两位独立验收完成，最终62项核对通过；真实修后NOT_RUN。
19为PREPARED_NOT_AUTHORIZED、零票；20未激活。软件chain02和原生18是不同证据层，不能相互替代。
本次只读核对源码及已安装厂商Python文件，未运行测试、原生probe或DCC，未直接查询原SQLite。
现有工作树包含用户及其他执行者修改；实施者只编辑下列明确文档，不重置工作树。

## 二、正式下游核查及真实未知

|环节与精确入口|已证实事实／预期|未知与验收|
|---|---|---|
|保存及冷重开：tools/run_controlled_engineering.py::_fresh 的 task_save→houdini_initial_stop→新Controller→task_reopen；Houdini addon scene_reopen_task_hip|正式链已经含停止与新宿主重开；H21 hou.py:60804 的 save(file_name=None, save_to_recent_files=True)，61033 的 load(file_name,suppress_save_prompt=False,ignore_load_warnings=False)与当前调用参数相符；完整合同保留锁内18节点|18未到保存。须未来授权实跑证明可编辑HIP、保存摘要、可信退出、新宿主身份及完整节点/参数/连接读回。模板/menu/hidden/disabled/locked仍未观察，不能由keys推断|
|主render：同一_fresh的 houdini_render_bounded→operation_query→houdini_reopen_stop|使用已保存scene id、roles['render']、单帧及剩余预算；不能直接绕到裸husk|主USD、原生设置与主EXR未产生；实际渲染与球地面视觉结果仍未知，不猜参数修复|
|验证登记：_verify_registered→tools/verify_controlled_output.py::resume→GraphRun.verify_render_output/register_render_artifact→ArtifactRegistry.register|已存在冻结入口、alpha配置、验证和登记调用；controlled_output_v1保留来源，不改写原严格回执|主EXR完整解码/身份/alpha/颜色/AOV及可信停止后可用登记尚无真实结果；内部writer/filter/flush/close继续NOT_OBSERVED|
|NK首存消费：tools/prepare_nuke_project.py::_ensure_initial_nuke、prepare_nuke_project；_fresh.consume_artifact；plugins/nuke/nuke_bridge_addon.py|准备入口会ensure_hosts启动首个Nuke，不能按模块旧docstring误认为只写文件。addon含scriptSaveAs和scriptSave、登记来源/颜色/alpha校验|本场景Read→Write首存、消费和实际knob读回未知；不要用软件NK证明原生NK|
|NK冷重开输出：packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py:357 scriptOpen，389 verify_composite_graph；driver _final_result|已有独立后台worker读入快照并核对合同；本机Nuke17.0v1官方foundry/frameserver/nuke/workerapplication.py:289/308亦采用scriptOpen|本机官方文件仅支持该调用存在，不证明全部knob/API语义或真实成功。需原生worker身份、快照摘要、冷读合同、Write输出及登记继承证据|

本机H21官方文件：/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/houdini/python3.11libs/hou.py。
本机Nuke官方文件位于 /Applications/Nuke17.0v1/Nuke17.0v1.app/Contents/Resources/pythonextensions/site-packages/ 下的上述foundry路径。
本次未发现本轮未修的确定生产缺陷；不因下游尚未到达而增加生产补丁或扩充夹具。prepare_nuke_project模块描述与ensure_hosts不符仅为源码注释不准，不据此重冻结。

## 三、实施包（审核通过后才开始）

1. **STATUS.md当前状态修正**：症状是开头以轮次和软件修复为主，后文仍有“render_execution_fact固定BLOCKED、尚无可信AVAILABLE生产转换”等旧路线现时措辞。根因是历史阶段顺序累积，容易盖过controlled_output_v1现路线。仅将开头改成以下六项实物状态；给相关旧段落明确当时范围或改为历史链接，保留原证据与长期要求。不得重写历史报告、增加新平台或新验收矩阵。
2. **NEXT_AGENT.md执行指针修正**：症状为“按顺序处理”第4条仍指15 review→16，而顶部已是19→未来20；根因是接续步骤未同步。只替换此过期指针，写明严格顺序、当前候选、无授权、预算及真实停止点；置顶同样六项实物状态。其余有效颜色、恢复及长期要求保留。

六项主进度（在两个现有文件复用同样的简短列表，不另建台账）：
- 可编辑HIP：未取得；18停在domain.initialize。
- HIP保存退出冷重开：未到达；19只有软件证据。
- 真实alpha：18校准5个EXR已验证；主场景alpha未取得。
- 主EXR完整验证及登记：未到达。
- NK登记消费、首存、冷重开及输出：未到达。
- 实际图像：仅校准图；主球地面与Nuke结果图未取得。

实施者只拥有 handover/STATUS.md、handover/NEXT_AGENT.md；本计划由计划agent创建，审核者保持只读。
不得重做HDA边界、Object映射、exact_type_name、__file__、-B、就绪/早停、已有序列化容器修复，不覆盖19或18原件。

## 四、最小验证与停止条件

严格次序：计划完成→另一只读agent审核明确通过→执行agent改上述两文档→同一审核agent复查。审核未通过时只修计划，不开始实施。
文档验证仅检查diff、相对链接目标、六项状态与18原证据一致、19/20指针一致、历史未丢失和生产源码指纹未变；无需pytest、全链、发布安装或DCC。
本次不安排OSproof；以后因确切代码风险确需OSproof时，直接escalated、canonical /private/tmp、Python3.11、清空PYTHONPATH并使用现有正式软件边界，禁止用sandbox失败推断产品bug或循环重跑。
若核查新发现确定代码缺陷，先保留具体源行与原生依据，停止当前实施包并交同一审核者增量审查；不得猜接口后补测试自证。
只有生产发布源发生已审核变更时才讨论新候选，并核对发布镜像与冻结内容；docs/test变化不生成新候选、不重冻结19。
未知原生行为保留到另行明确授权的真实范围。未授权时，完成文档复查即停止，不创建/激活20、不消耗启动票、不启动任意DCC/native probe。
未来真实授权后，仍由既有正式driver按8阶段顺序执行；任一失败可信停止并封闭，不重试、不续用旧票；回报六实物状态及最早失败原件，不以软件绿数提升状态。

## 五、只读核查时源码及拟改文档SHA-256

以下用于实施前漂移检查；不是新发布清单，也不要求重冻结。

|文件|SHA-256|
|---|---|
|tools/run_controlled_engineering.py|15f84e4602b3309f36bb112268c52aa4250da8b00b2336d780cd39e6c8521e8d|
|tools/prepare_nuke_project.py|cf004460cb47a008bef09d8605fc7bd308a537d7ee443999b7e2af2216401716|
|tools/verify_controlled_output.py|79054abc30150a465a8b0d18b7e6067e2293a021e573135500619c552344b090|
|plugins/houdini/_impl/houdini_bridge_addon.py|22c88201eb5928c89a0dfcaf3d6e4941929f0885cd72ca6d335cb48a1f0837b6|
|plugins/nuke/nuke_bridge_addon.py|8de13a059e39ab96d72f828eea2aef3aa0da19db9d2ffc94056e380699465bfb|
|packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py|c16ef75c35f57c1d137ab0df801f56a239b73ef4dc362ab8e9c06c2ae96b29d7|
|packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py|837ad6f544cd4b1f35744b8a6e1169a1fe97f1258abcb8f29353748944d97f72|
|packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py|632c8a737fc80ad3a08de0a5c6f5add55067f7a2ae6acd511ebcb48cc7b4d016|
|handover/STATUS.md|866e0c677f1efea60dac79659a32d0b19897e899f3d9598a363bebc415f1a2ac|
|handover/NEXT_AGENT.md|0e0e85ea41096f0dfdfa0373d7fb6dbe56d59622d49166273ac9f71bfd02bbea|
