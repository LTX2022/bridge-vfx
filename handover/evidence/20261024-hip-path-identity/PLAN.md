# HIP 快照重开路径身份修复合同

方案：`/root/hip_path_repair_planner`。独立审核：`/root/hip_path_plan_reviewer`，APPROVED。
范围：现有H21球地面工程闭环的软件整改，真实DCC禁止运行。保留19及06至18原件，不激活20。

## 根因与依据

正式任务重开从已核验的快照加载，未恢复原保存路径。保存合同在原路径捕获全部参数求值结果，Karma settings的dcmfilename及productName默认表达式依赖$HIP/$HIPNAME，重开后值漂移。原始表达式及同版HOM语义见native-basis.json。

H21官方setName仅改变内存工程路径，不保存。hython的hasUnsavedChanges始终True，因此重放必须走完整场景合同证明，不能依赖fake的False返回。

## 批准的最小实现

生产仅修改plugins/houdini/_impl/houdini_bridge_addon.py：

1. scene_reopen_task_hip的两种snapshot load路径之后，共同出口setName原路径并读回规范化路径；命名放在load异常捕获之外。失败发生在租约转移、active_scene写入、transition完成之前。不重新save、不重载补偿、不改原文件/快照/合同、不手动推进epoch。
2. 注册rebind的路径参数同步使用原保存路径，保留原hash、身份、CAS、completion token及generation/saves/manifest回滚。
3. scene.reopen_task_hip的COMPLETED replay要求request/result/current/active_scene原路径、hash、合同摘要和transition绑定一致；保留完整after_identity及receipt证明，unsaved=True仍验完整合同。其他命令语义保持。replay不load/setName/save；旧快照路径不能伪装幂等。
4. 同一命令INTENT reconcile要求原路径、原文件hash、已登记且摘要有效的完整保存合同和当前场景证明。各域checkpoint由既有rebind事务在对应root fence内完整验证、恢复及提交重验，task最终化不得再次调用重新获取同根锁的checkpoint helper；其他命令原有checkpoint路径保持。不得把命名前中断补成成功；也不能强制要求已写active_scene，须允许命名和读回后、写active_scene前的合法中断。正常task reopen与reconcile共用现有交接最终化逻辑，完成lease/generation/rebind/active_scene及transition绑定后才能COMPLETED，失败保留原回滚；reconcile不得再次load/setName/save。
5. 保留无operation identity低层调用、v1/v2合同及旧owned_roots兼容。不改指纹算法；成功后全局指纹hip_path应为原路径。
6. 两种load路径的共同出口持久记录实际post-load identity，先验证非epoch身份与INTENT一致，通过现有锁/CAS及receipt digest绑定同一INTENT。恢复精确匹配该身份，缺记录或漂移拒绝；不以任意接受+1/+2代替证明。覆盖warning双load后中断，不改变其他命令的epoch规则。
7. submit_render的运行中场景身份验证采用已绑定原路径，同时保留独立snapshot/hash、active identity及完整合同证明。

软件边界限定workbuddy_assembly.py的既有software_host_client、native_schema_test_boundary.py的既有求值、software_render_api_boundary.py的settings默认参数；复用现有fixture。让$HIP/$HIPNAME依赖当前hipFile.path，保留未展开通道，只增加两个有原生依据的默认表达式，不将其硬编码成绝对路径。

## 必要验证

- 先以现有正式handoff/task_reopen路径复现原生默认表达式引出的软件红例。
- 正常与warning加载均从snapshot读取、恢复原路径，合同精确一致，源文件/快照hash不变。
- setName抛错或路径读回错误：原定load次数，无租约转移/active_scene/完成副作用。
- unsaved=True重放：同绑定成功且零load/setName/save；路径、参数、identity、合同摘要或另一transition的active_scene均拒绝。
- INTENT：快照路径、参数漂移、不完整合同拒绝；原路径且完整证明可恢复，不依赖尚未写入的active_scene。
- 正常及warning双load中断、无/旧active_scene经恢复后，同请求可无副作用重放；故障在正式调用边界注入，不手改operation制造成功。
- task reopen后的render提交可进入受控监督器边界；错误原路径、损坏snapshot或合同/身份漂移仍拒绝。
- rebind或完成故障后保留既有generation/saves/manifest回滚及INTENT；必要的geometry/RBD/particle旧回归保持。
- 用有限组合测试覆盖实际rebind持锁范围的正常完成与失败回滚，拒绝同根锁重复获取，不修改全局锁语义。
- 复用核心覆盖，仅验证受影响范围；最后单次既有八阶段软件链，明确DCC/API/像素为替身，不当作真实成功。
- OS身份工具软件检查直接使用escalated、规范/private/tmp、Python3.11及-I/-B，不再重复已知sandbox失败。

执行者拥有上述实现和必要现有测试文件；主控拥有本目录证据、候选装配及交接文档。共享文件仅一名实现者，审查者不参与实现。

实施后先交同一审核者复查，再做独立代码/证据验收。仅在必要验证和审查整改完成后冻结新候选、新review；旧19不改，新源码不能沿用19 review授权。ACEScg及8次启动/120秒/600秒/512MiB/单重作业/零重试保持。
