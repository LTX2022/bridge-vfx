# Writer→登记→Nuke：软件整改及原生接口缺口

当前工程闭环仍为 **BLOCKED**，M1仍NOT_READY。真实Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、cook、仿真、缓存和渲染均未启动。本轮没有生成可用于真实工程验收的HIP/NK或Karma产物。

## 本轮软件改动

正式 `nuke_render_bounded` 先核对登记产物属于当前任务，异任务输入在Nuke装配前拒绝，不让后续worker拒绝替代前置所有权检查。

正式 `nuke_render_bounded` 在省略可选颜色/alpha参数时，从已验证登记产物继承，不再填写scene_linear/False。显式参数必须与登记值一致；缺失、类型不符或请求不同转换时，在Nuke宿主调用前拒绝。该Read→Write路线保留输入解释，不承担新色彩/alpha转换。

正式任务自有Nuke装配核对Read/Write的file、colorspace、raw及Write的premultiplied，显式设置并回读登记值和连接。缺失字段不能跳过；写入或回读失败恢复原knob和连接，恢复无法确认则返回明确错误，不继续提交渲染。现有 `connect_nodes` 仅增加显式 `src:null` 断开指定输入的语义，缺src仍拒绝；原字符串源语义保留。这用于恢复原先未连接的Write，不增加新的公开MCP工具或执行路线。

`render_execution_fact`、旧post-frame合同、原始终态签名、ArtifactRegistry的AVAILABLE门槛和Nuke worker私有输入副本均保持原有严格验证。本轮没有增加可以提交“可信writer事实”的模型/CLI入口，没有重签历史完成事实，也没有用配置值生成AVAILABLE。

## 验证与独立复核

Python3.11.16最终集中验证：**38项通过，0 FAIL/ERROR/SKIP，退出码0**。本次只运行受影响与本链必要覆盖，不是项目全量。未参与实现的Bugbot已核对本轮冻结7文件，独立只读复核无待修P1/P2。

[最终日志](evidence/20261016-writer-chain/validation.log)、[核心用例选择与结果](evidence/20261016-writer-chain/results.json)、[源码指纹](evidence/20261016-writer-chain/source-sha256.json)、[独立审查](evidence/20261016-writer-chain/review.md)、[既有文件保留核对](evidence/20261016-writer-chain/preservation.json)。软件验证分别覆盖：Nuke登记颜色/alpha继承、异任务输入及转换拒绝；正式装配字段/连接读回与回滚；真实SQLite/EXR软件夹具的版本、metadata和依赖登记；账本失败后仅补登记；Nuke自有Python worker/停止/私有输入副本；正式生成入口与Houdini软件producer缺原生事实时继续拒绝登记。

这些都是显式底层API/软件文件夹具的证据，不能标成真实writer→真实Karma产物→Nuke消费通过。真实产物消费仍NOT_RUN。未运行项目全量，也未构建新的wheel、Skill或发布ZIP；当前旧发布包不能当成本轮源码。

## 原生依据：已确定什么，仍缺什么

同版静态核查目标为H21.0.631和H22.0.459。[原件索引及SHA](evidence/20261016-writer-chain/native-basis.json)。本轮只读应用内文本及既有归档，没有执行原生二进制。

| 边界 | 已有依据 | 尚缺依据/事实 |
|---|---|---|
| husk post-frame | 两版官方帮助提供stage/husk_command/settings/hou.frame；Husk Post-Frame在全部render products保存后运行 | 实际变量类型/settings键、当前husk进程与操作/产品绑定、实际保存后字节尚未运行观察。普通ROP Post-Frame仅在USD生成后，不能代用 |
| 产品/AOV | HUSD_RenderProduct/RenderVar存在产品/AOV查询；XUSD存在已解析配置查询 | 从当前Python hook取得实际HUSD产品及IMG writer对象的合法接点未确证；重新解析USD不证明writer消费 |
| PXL/OCIO | PXL_OCIO公开配置路径、lookupProcessor/lookupViewProcessor；PHandle可查询有效/no-op/3D | 实际Processor为不透明实现；尚未确证writer所用processor/context/file-rule/LUT/metadata的合法采集接口，另建processor或PyOpenColorIO Config不能替代 |
| IMG writer | IMG_FileParms有LUT/scope/OCIO目标等getter；IMG_File可遍历filter | 当前hook未提供实际IMG对象接点；IMG_FileFilterLUT的ocioHandle、source/dest/looks和实际PHandle为private。setFileCreateCB仅给文件名，setFileHooks为读取流hook |
| filter | 文档说明sample/pixel/image阶段和部分追加/禁用规则 | 声明列表不证明执行顺序。21逐AOV pixel filter与459全局pixel filter/逐AOV Sample Blending语义不同，不能跨版代用 |
| alpha | getAlphaInfo/detectAlphaDetails区分alpha值类别；459增加formatNeedsPremultiplied | 值类别及格式需求均不证明beauty实际关联alpha；H21无上述新增接口 |

这同时包含**缺少实际运行观察**和**尚未确证采集接点**，不能概括为“软件全部写好，只差跑真机”。现有材料未证明接口永远不存在；这里只明确本轮可核对材料未提供所需依据。

## 尚未关闭的首个阻断与接续边界

1. 首先确定同build官方husk/HDK的实际writer实例采集接点与可观察范围；若需要新增原生采集组件，先给出准确接口和依赖设计，不猜一个Python API，也不直接引入未获准组件。
2. 依据已确证接点实现producer内采集及事实转换，绑定task/session/launch/scene/frame、实际writer身份和最终字节。旧raw观察保持旧含义；缺字段保持BLOCKED，不接受verified=true或“预期成功”标签。
3. 全部所需最终事实成立后，才可通过现有终态签名生成AVAILABLE metadata、按实际producer登记，并由正式Nuke链消费该artifact ID/version/字节/颜色。不得用本轮独立软件夹具替代上游。
4. 需要真实采集时，另行明确具体版本、案例、路径、帧和预算；当前运行禁令保持。工程门成立前不推进HY3或复用，不恢复旧全16域批量修复。

原sphere_ground_v1/v2、其他有效修复和Desktop主工程均保留；本轮不提交或推送Git，不改真实支持索引。
