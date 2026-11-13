# Karma 工程闭环：独立几何与有效材质

当前状态：本轮只验证明确的软件边界；工程闭环仍 BLOCKED，M1 仍 NOT_READY。真实 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、cook、仿真、缓存、渲染和视觉验收未执行。

## 正式场景接口

新场景选择器使用 `scene_profile=sphere_ground_v2`，冻结输入为 [frozen-scene-v2.json](../docs/official-baselines/karma/frozen-scene-v2.json)。版本明确选择21.0.631或22.0.459。继续复用现有 construction_input_manifest 的 `render_scene_configuration`、正式生成器、图编译器、worker、任务租约、图/场景合同和反馈/保存/重开接口。

v2为23个节点、17条连接。Sphere与Ground分别从受控SOP Import进入USD，前缀为任务命名空间下的 `/Geometry/Sphere`、`/Geometry/Ground`；通过LOP Merge汇合，再进入层元数据、材质库/绑定、相机、灯光、RenderSettings/Product/Var和既有Driver。配置中的球半径/位置、地面方向、材质、相机、灯光、分辨率与原冻结合同相同，不另加未约定构图值。

保存与新进程重开时，按实际角色核对SOP源路径、节点类型、完整连线、冻结字段和USD元数据；分别读取两组非空且互不重叠的可渲染prim，再调用 `UsdShade.MaterialBindingAPI.ComputeBoundMaterial()` 解析各自实际生效的材质和winning relationship。不从节点存在或预期路径推导成功。[OpenUSD原生接口说明](https://openusd.org/24.08/api/class_usd_shade_material_binding_a_p_i.html)是API依据，不是本机Houdini运行证据。

v1继续使用原22节点/16连接的SOP Merge拓扑、原冻结文件、原图摘要和保存回执格式；没有新增geometry字段，也不自动迁移旧工程。worker、提案入口和私有初始化器分别验证配置profile与选择器完全相同，不能交叉使用v1/v2配置。

## 软件验证

Python3.11.16：54项受影响回归通过，0 FAIL/ERROR/SKIP，退出码0，用时103.935秒。最终增量独立复核无待修P1/P2。[验证日志](evidence/20261016-karma-engineering/validation.log)、[结构化结果](evidence/20261016-karma-engineering/results.json)、[兼容比较](evidence/20261016-karma-engineering/compatibility.json)、[源码指纹](evidence/20261016-karma-engineering/source-sha256.json)、[独立复核](evidence/20261016-karma-engineering/review.md)。47张既有图的完整编译字典及schedule逐项不变，包括两个旧v1图和旧429普通图。测试只显式替换底层HOM/USD和原生进程启动：正式入口、worker、状态机、TCP、反馈和保存重开使用生产代码。MaterialBindingAPI替身只解析已经由实际连接生成的软件Stage，不提供预置成功场景；测试显式注入，生产缺原生接口继续拒绝。

两版v2均检查正式建图、合法颜色反馈、保存、旧Python宿主可信停止和新身份重开；旧v1另外检查原回执形状、反馈和冷重开。缺失地面prim、错误材质、错误SOP源和冻结相机漂移均拒绝保存。软件临时HIP是替身序列化内容，不能作为可用原生HIP交付。

这未验证真实compiled模板、cook几何、有效世界变换、像素、原生writer或真实工程文件可用。`native_geometry_validated`、`render_executed`、`visual_verified`继续为false；未改真实支持索引。保存/反馈的局部软件证据也不关闭“同一产物链的反馈与实际worker中断恢复”整门。

## 工程门的下一处阻断

`houdini_bridge.client.render_execution_fact()`仍固定输出 `BLOCKED_MISSING_NATIVE_FACTS`、空metadata；post-frame原始观察不能证明effective writer/PXL/OCIO、AOV覆盖、有序filter、alpha及writer进程身份。当前没有从可信最终观察生成AVAILABLE元数据的生产正向路径。

因此ArtifactRegistry继续拒绝缺失producer/scene/dependency/final-byte绑定的登记，Nuke尚不能消费这条链实际产生并登记的Karma产物。不能把AVAILABLE改成常量、填写设计值，或用合成EXR代替Houdini上游来关闭该缺口。

接续仅处理这一依赖：先核对精确版本的可用writer观察接口与来源，再实现受身份/场景/帧/最终字节围栏约束的事实转换和必要软件反例；原生依据不足的字段明确BLOCKED。`soho_foreground`实际默认值仍未知，不用替身默认值推断运行结果。真实采集或渲染仍需另行明确授权及资源范围。

## 活动路线与停止条件

| 依赖门 | 通过条件 | 当前状态/停止点 |
|---|---|---|
| 工程 | 可编辑HIP/NK、保存与新进程重开、精确帧最终产物登记且Nuke实际消费 | BLOCKED：可信writer事实及AVAILABLE生产路径未完成；本轮仅几何/材质软件子步骤 |
| 反馈与恢复 | 同一工程/产物链反馈、版本和失效范围正确；中断实际工作进程，可信停止后恢复且无重复副作用 | NOT_RUN：不能用本轮Python冷重开替代 |
| HY3创作 | 实际附件、观察/计划/工具/反馈及人工补救可追溯 | NOT_RUN：前序门及具体授权未满足 |
| 复用 | 第二参考与动态烟雾复用共同链，记录代码变化/耗时/成本/人工介入 | NOT_RUN：不增加案例专用成功分支 |

旧全16域铺开方案冻结，原16域/48+2/54行长期要求保留；本轮不恢复批量修复。未运行全量、重建wheel/Skill发布包、提交或推送Git，未改Desktop主工程。后续安装候选必须从最终冻结源码重新构建，不能把当前旧wheel当成本轮源码。
