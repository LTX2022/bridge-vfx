# Karma 最小场景冻结参数接线

状态：本轮软件范围通过。M1 仍 NOT_READY；真实 Houdini/Nuke、WorkBuddy/HY3、模型、Cook、仿真、缓存、渲染和视觉验收未执行。

## 当前接口

冻结配置为 [frozen-scene.json](../docs/official-baselines/karma/frozen-scene.json)，完整保留重建合同的 proposed_scene 及来源 SHA。它是控制端输入，不是媒体观察、执行授权或真实宿主事实。

控制端将该文件按已有 construction_input_manifest 登记，semantic_role 为 render_scene_configuration，包含有序 index、asset_id、绝对本地 source_uri、实际 bytes 和 SHA-256。单文件上限64KiB；重复字段、坏UTF-8、非有限数值、未知字段、脚本/原生参数/路径扩展、错误版本或文件变化均拒绝。生成器在修改目标目录前校验；worker和私有初始化器分别重验同一冻结输入。

正式 graph_propose 选择器：

```json
{"schema":"bridge.registered-domain-construction/1","domain_pack":"material_lookdev_v1","houdini_version":"21.0.631","scene_profile":"sphere_ground_v1"}
```

兼容软件检查将版本显式改为22.0.459。该profile与冻结输入必须同时存在；普通领域图不能偷偷消费该配置。生产缺配置仍拒绝，不自动选择软件替身。

## 建图与读回

复用 GraphRun、现有图编译器、分批worker、任务租约、状态机和正式保存接口。固定注册图为22节点/16连接：sphere及ground经SOP Merge进入USD，经过显式层元数据、MaterialX绑定、相机、Disk灯、Karma设置、RenderVar/Product/Settings及受控usdrender。

写入球体0.5米半径及(0,0.5,0)中心、地面XZ/y=0/零旋转、材质颜色与粗糙度、相机/灯位及原生look-at、50mm焦距、Disk半径、CPU、128×128、关闭降噪/运动模糊；法线/位移扰动置为中性。球体单位缩放明确设为1。原合同没有指定的地面尺寸等参数不新增设计值，随实际节点参数一起保存；本轮不据此宣布完整构图或视觉成立。

每项均走实际模板类型、分量、菜单、门控、锁定、写入、读回及失败回滚。configurelayer只用实际实例中唯一的Y轴菜单标签解析token，不猜ordinal；未知接口或未实际author Y-up/metres会拒绝。它的编译模板/默认值仍未取得原生运行证据。

配置摘要、实际冻结字段读回、节点参数通道和连接一并进入现有scene_contract。graph_status保持原有安全白名单，只公开结构验证和合同摘要；详细字段通过正式 task_save.scene_contract.frozen_scene_parameters 和 task_reopen 返回。worker从既有 root_lease_rebind.verification 验证重开回执。

合法颜色反馈仍走原有语义控制、快照回滚和版本机制。读回以冻结初始配置加已登记candidate_patch计算当前期望，保存/重开不把合法反馈误判为初始值漂移；配置身份不变。直接改动冻结相机参数会拒绝新保存登记。

frames=[1]是目标帧声明；它不授予作业权限，也不替代原有帧数、120秒、预算及资源确认。该profile不启动渲染，不签发最终产物，不关闭writer/OCIO/AOV等阻断。

## 验证

[原始验证日志](evidence/20261016-karma-frozen-parameters/validation.log)：Python3.11.16，54项通过，0FAIL/ERROR/SKIP，退出码0。两项核心测试包含21.0.631/22.0.459显式底层软件替身，实际运行生成的production入口、回环TCP、worker、正式颜色反馈、保存、可信停止和新Python宿主进程重开；其余覆盖已有输入隔离、材质/灯光、反馈、场景转换、图执行及旧正式入口。

[结构化结果](evidence/20261016-karma-frozen-parameters/results.json)、[源码SHA](evidence/20261016-karma-frozen-parameters/source-sha256.json)、[独立复核](evidence/20261016-karma-frozen-parameters/review.md)。Bugbot针对本轮最终增量未发现P1/P2，未扩大为全项目审查。

[兼容比较](evidence/20261016-karma-frozen-parameters/compatibility.json)：45张既有注册图的完整编译内容逐项不变，包括旧429普通图；新profile仅支持21/459。底层API替身只由测试显式选择，不提供给生产装配，也不作为459编译模板依据。

本轮没有运行全量、构建新发布包或更新离线wheel，没有提交/推送Git、修改Desktop主工程或真实验收索引。临时软件HIP是替身序列化结果，不是可交付的原生HIP；软件回执中的临时路径不作为后续真实输入。

## 尚需保持的边界

[同版本静态来源](evidence/20261016-karma-frozen-parameters/native-source-proof.json)确认SDK机器字段及HDA中的look-at/resolution等定义，未证明原生实例可写、有效世界变换、几何/材质效果或最终图像尺寸。459缺失的编译/运行模板和有效writer最终事实仍为阻断。后续继续补原生依据和正式输出登记链；真实运行仍需另行确认具体范围，不能把这份报告当作授权。
