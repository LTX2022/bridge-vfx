# 官方 Karma 教程对照执行计划

日期：2026-10-26。范围是本机 H21 随附 Karma User Guide 的一个 DiskLight 基础案例：建立官方案例的 CPU 对照输出，再通过 Bridge 从空工程重建、保存、冷重开、渲染并由 Nuke 消费。本轮仅编制计划；尚未实施配套改动、创建真实执行授权或启动新原生进程。预算属于待执行建议。

配套代码已开始实施；当前完成情况及未完成的运行前条件见[实现状态](OFFICIAL_KARMA_IMPLEMENTATION_20261026.md)。本计划保留制定时的范围与执行门槛，不作为准备通过或原生执行回执。

当前基线为 [H21 到 Nuke 已通过的真实单帧链](H21_NUKE_REAL_CHAIN_20261026.md)。先固化该基线与必要产物身份，保留现有工作区；官方对照排在同工程反馈／中断恢复、HY3和第二案例复用之前。本轮不包含这些后续实验，也不推进全16域M1验收。

## 官方案例与来源

选定 [Karma User Guide 的 Lights 章节 DiskLight](https://www.sidefx.com/docs/houdini/solaris/kug/lights.html#disklight)，结合 [材质绑定](https://www.sidefx.com/docs/houdini/solaris/kug/materials.html#material-bindings)和 [Rendering](https://www.sidefx.com/docs/houdini/solaris/kug/rendering.html)说明核对实际流程。网页目前为H22，执行以本机H21原件、同版定义和运行读回为准。

本机示例目录：
`/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/houdini/help/files/karma_user_guide/`

| 项目 | 已核对的静态事实 |
|---|---|
| 主工程 | `karma_user_guide.hip`，44,785,742字节 |
| SHA-256 | `831b34f61491caab897aa357eead398e3d770ac2a1c9187ea4ca4e669cc29106` |
| 配套原件 | 13个文件，合计56,200,300字节；本轮重新核对全部大小和哈希 |
| 版本 | 安装目录21.0.631，HIP保存版本21.0.440；实际加载兼容性需运行验证 |
| 选定分支 | `/stage/lights/render_disklight`，其输入为`disklight` |
| 分支选择 | `/stage/lights/switch3`的输入1为`render_disklight`；其`.chn`保存`$F-1`，按保存表达式推算frame 1原本选择输入0的RectLight |
| 渲染入口 | `/stage/lights/OUT_karma_lights`，保存`runcommand=on`、`rendercommand=husk`、`soho_foreground=off`、`lopoutput=__render__.usd` |
| 末端输出作者 | `update_output_image_path`对`/Render/Products/renderproduct`的`productName`执行set，保存表达式含`@OUT_PREFIX`并以`.jpg`结尾 |
| 几何与着色 | 选定静态上游为backdrop→camera→settings→xform→DiskLight；backdrop保存`bindmaterials=nobind`、`materials=0`，内部两个Color SOP保存白色及0.75灰，没有显式Material Library |
| 原生类型 | `disklight`为`light::2.0`；名称为`karmarendersettings`的节点实际是`karmarenderproperties` |
| 保存值 | 420×300、DiskLight半径0.45、intensity 1、exposure 0；相机焦距390，运动模糊及降噪关闭 |

这些值来自`.init`、`.def`、`.parm`和`.chn`原始成员；frame 1选择是保存表达式的静态推算，实际组合结果尚待运行读回。来源记录包含成员偏移、长度、SHA-256及未求值的通道文本。完整选定节点、输入及原件清单见 [静态来源核对](evidence/20261026-official-karma-plan/source-check.json)。

## 对照条件

官方原件保持不变。官方侧在独立工作副本中将DiskLight选择固定为静态输入1，保留其几何、颜色属性、灯光、相机与420×300构图，执行frame 1。保存、冷开及导出前均验证该选择和最终组合结果。安装中的其他示例章节不列入运行清单。

两侧统一使用Karma CPU、同一H21 OCIO配置、ACEScg、HALF RGBA，关闭运动模糊和降噪。原文件保存的渲染器是XPU，因此该结果命名为“官方案例CPU对照”，并记录渲染器、输出路径、显式色彩／通道设置等执行差异。官方说明CPU与XPU不保证逐像素兼容，本轮数值对照以本机生成的CPU结果为基准。

保持几何和着色的真实语义；Bridge节点名和组织可按正式图规范变化。依赖对应表覆盖prim路径、SOP几何来源、显式材质绑定的存在或缺失、颜色／透明度primvars、原生默认着色、最终世界变换、相机、灯光、RenderSettings、RenderProduct及RenderVars。对本例，静态基线是无显式材质绑定和Color SOP提供的颜色；运行时须核查实际`material:binding`及相关关系、`primvars:displayColor`、`primvars:displayOpacity`的值／类型／插值／索引及缺省状态。Bridge精确保留观测到的状态，不增加Material Library或Standard Surface来满足检查；若运行组合出现静态清单未解释的着色源，停止并补证。本例只接收DiskLight灯光及其现有几何／着色的复现，不接收完整MaterialX教程覆盖。

Bridge从空任务场景经既有注册图、GraphRun、任务宿主、ArtifactRegistry和Nuke入口构建。官方HIP只用于官方侧基准；Bridge重建侧不加载它，也不引用官方导出的USD来替代建图。官方USD用于审计与比较。

## 执行前必须完成的配套准备

当前代码不能直接执行本案例，需先完成以下有限扩展；此计划不实施这些改动。

| 位置 | 已确认限制 | 必要配套工作与准备出口 |
|---|---|---|
| `native_render_scene.py`、`graph_catalog.py`及Houdini宿主 | 已验证注册场景为sphere_ground_v1/v2；当前参数合同限制128×128和球／平面结构 | 增加独立`official_karma_disklight_v1`案例合同，按官方分支声明完整拓扑、几何配方、无显式材质绑定／颜色primvars／默认着色及参数映射；旧合同与源码摘要兼容规则保留 |
| `controlled_output.py`及工程准备／执行工具 | 输出政策、案例选择和最终尺寸检查固定sphere_ground_v2／128×128 | 增加仅绑定本案例、420×300、frame 1、RGBA的独立版本政策与冻结计划；继续执行颜色、原件、完整EXR、可信停止及登记校验 |
| `prepare_native_alpha_scene.py`、`alpha_calibration.py`、校准runner | 当前标板为128×128，固定采样像素及路线摘要 | 增加420×300专用配置，建议采样(70,150)、(210,150)、(350,150)；几何覆盖须由实际原生采样验证；保留opacity 0／0.5／1、黑白合成和零alpha加性RGB检查。新路线独立校准 |
| `native_scope.py`及既有准入入口 | 现有整链固定8启动，没有官方基准的3项角色 | 增加受限的官方对照资源配置，统一11项准入与600秒总账；全实验固定同一binding和记账根；所有启动继续走`owned_process`，不修改旧8启动配置、不建平行执行器 |

先用普通Python完成节点／参数／连接声明、依赖路径、版本映射、负例、冷开合同和预算预检。读取HIP成员不运行其中代码；原例加载回调、HDA、表达式及输出重定向应先静态审查。运行时求值结果必须由冻结控制器采集，再逐步核验，不能填写成功占位值。

准备检查至少覆盖：旧场景保存／冷开兼容、新案例不能降级成灰球、政策与分辨率漂移拒绝、RGBA遗漏拒绝、Nuke真实OCIO目录和tab首字段解析、启动计数及600秒耗尽拒绝、未知停止保槽、当前可用原件和失败记录不被覆盖。准备未通过时不启动DCC。

## 冻结规则与运行观测封存

首次原生启动前冻结同一scope binding、记账根、全部控制器／观察器／建图源码哈希、官方原件与成员证据、执行顺序、参数对应表模板、输出根及相对文件名、下列允许覆写规则、观测验证规则和图像容差。scope和这些输入从第一次准入起不再更换。工作副本的允许编辑与原始输入分别记账，不把编辑后的文件冒充官方原件。

| 工作副本允许编辑 | 冻结规则与验证边界 |
|---|---|
| DiskLight选择 | 仅对`/stage/lights/switch3/input`受控删除或替换原动画／表达式，并设为静态整数1；记录原`.chn`身份。保存及冷开后必须没有动态覆盖、frame 1的`eval()`为1，且实际组合的是所选DiskLight。不能只改变当前帧的键值 |
| 渲染器与共同输出设置 | 仅将声明的渲染器改为Karma CPU；固定420×300、frame 1、HALF RGBA、既定H21 OCIO／ACEScg、运动模糊及降噪关闭。保留官方几何、颜色和灯光／相机参数 |
| 只导出USD | 对官方ROP将`runcommand`固定为off并读回，禁用后台／隐式渲染；`rendercommand`保留为受记录但不可执行的husk。使用经审核的仅导出调用，将`lopoutput`固定到实验根内声明的USD路径；导出阶段不得产生husk准入或渲染输出。若该ROP不能证明仅导出，停止，不临时换导出路径 |
| Beauty输出适配 | 同版HDA的beauty prim固定为大写`/Render/Products/Vars/Beauty`；保留其`sourceName=C.*[LO]`、`sourceType=lpe`、`dataType=color4f`。两侧各增加唯一`editproperties`输出适配节点：官方固定为`/stage/lights/bridge_rgba_output`，输入仅为原末端`update_output_image_path`；仅匹配Beauty、`createprims=off`、两个control静态set，显式作者`driver:parameters:aov:husk:name=C`（string）及`driver:parameters:aov:husk:format=color4h`（token）。官方ROP的`loppath`静态指向该节点；原31节点及原连线保持逐项核对。额外节点的类型、唯一名称、输入、参数、有效stage、保存／冷开与导出结果独立读回；不解锁原HDA。Bridge同构的`beauty_binding`使注册图为35节点／30连线。此项是HALF RGBA共同输出设置的必要作者映射，不增加原生启动。 |
| 最终图像路径 | 对最后有效作者`update_output_image_path`的`productName`移除动态路径覆盖，保留set模式并写入实验根内声明的`official/official.0001.exr`绝对路径。导出后检查所选RenderProduct最终组合的`productName`及USD实际引用；不得残留`.jpg`、`@OUT_PREFIX`或其他目录。ROP／husk若支持输出覆盖，必须与该固定路径完全相同，不以覆盖参数掩盖USD中错误路径 |
| 可比较的运行设置 | 参数表模板预先列明所需字段、单位、类型、关系和允许范围。官方原例求值所得的采样及对应参数原样成为两侧共同输入；固定RNG选项只采用运行前已审核的同版支持方式，不在观察结果后改变规则 |

阶段B由冻结观察器只读采集真实模板、求值后的相机／灯光／几何／颜色参数、采样设置和完整资源闭包，生成带原始宿主身份、文件／源码摘要、采集帧和签名的观测清单。阶段C冷开再次验证同一状态与资源身份，导出后记录组合USD、RenderProduct及仅导出行为。控制器按首次启动前冻结的类型、字段、关系和白名单验证这些数据，并在阶段E的Bridge建图之前将观测清单及其内容哈希封存为建图输入；后续所有对应表、结果及回执绑定该哈希。观测清单是首次冻结时声明的运行派生产物，其后生成的哈希只进入阶段签名记录和建图请求，不回写或重新生成scope／runtime-bindings。

观测合同使用`bridge.official-karma-observation/2`。只对H21中无输入的`/stage/lights/backdrop_shallow`（`sopcreate`）隐藏Toggle字段`ineditlayerblock`不求值：固定路径、类型、组件数、隐藏状态、模板默认Python表达式及实际未求值驱动必须精确匹配`hou.pwd().inputs()[0].inEditLayerBlock()`；暖开以无求值`rawValue()`核对默认驱动，冷开允许保存后序列化的同一Python表达式。声明具体模板SHA、原因和`NOT_EVALUATED`，不将保存的0当作实际值。任何常量覆盖、表达式／语言改变或连接均拒绝。参数采集不执行UI禁用条件，`disabled`显式为null；其余构造参数仍取真实值，节点错误／警告、资源与组合USD检查保持严格。该UI字段不进入Bridge构造输入，原始HIP和HDA不修改。

这项封存是按预先声明规则接收运行数据，不修改已冻结源码、原始输入、采样决策规则、允许覆写表或容差。字段缺失、资源越界、模板／关系不符或需要新增编辑时，记录原因、结算已有消耗并停止；未执行部分保持NOT_RUN，不在阶段B之后改源码再继续本次实验。

## 分阶段执行与验收

| 阶段 | 工作 | 必须保留的结果与通过标准 |
|---|---|---|
| A 基线与输入 | 记录当前通过版本的源码及产物哈希，复制官方原件和依赖到独立根目录；按上述冻结规则固定一个binding、代码、允许覆写规则、观测模板、版本和预算 | 当前29原件保留；13个官方文件及关键`.chn`／`.parm`／`.def`成员逐项匹配；缺件、未知回调行为或未映射节点有具体阻断，不进入真实阶段 |
| B 官方打开和保存 | 第1个官方hython加载工作副本，受控移除／替换switch动画并固定input 1，按冻结表设置CPU、只导出开关及末端EXR路径；采集并签名只读运行观测，保存官方CPU基准HIP后退出 | 选择无动态覆盖且实际为DiskLight；无绑定／颜色primvars／默认着色状态已采集；依赖只落在实验根或声明的同版安装资源；无未知节点、缺失资产或未解释警告；保存身份与停止回执齐全 |
| C 官方冷开与渲染 | 第2个官方hython从保存文件冷开，验证静态input 1、实际DiskLight及结构／参数／资源身份；读回`runcommand=off`后仅导出声明的USD，验证无隐式husk并退出；单独准入唯一官方husk渲染frame 1 | 保存与冷开内容对应；最终RenderProduct为固定EXR路径、HALF RGBA，临时USD路径受控；只导出行为与一次官方husk准入有证据；实际CPU，420×300 RGBA完整有限且受光／阴影可辨；观测清单在Bridge建图前通过验证并封存；原始停止成功 |
| D 同路线alpha校准 | 新420×300标板由husk渲染，Nuke采样并在黑白背景输出／重新读取 | 原有容差保持：Karma 0.02、Nuke合成1e-4；关联／直通alpha可辨别，加性RGB保留；版本、build、分辨率、颜色与writer路线匹配本次Bridge渲染 |
| E Bridge重建与冷开 | 正式worker绑定已封存观测清单哈希，从空场景建立声明图；交接到任务宿主保存HIP并停止；新宿主冷开 | 节点类型、拓扑、实际几何、无显式绑定／颜色primvars／默认着色及参数与官方观测对应；同一HIP字节身份；没有用官方HIP／USD替代重建 |
| F Bridge渲染登记 | 由冷开工程实际执行husk；停止后独立验证并登记 | 420×300 HALF RGBA，所有像素有限；准确的ACEScg配置和文件证据；当前版本登记可用；未知writer内部事实仍标未观察 |
| G Nuke冷消费 | 按artifact ID／version／帧／哈希消费Bridge EXR；保存含OCIO与RGBA Write的NK；独立Nuke进程冷开并渲染 | NK与实际执行快照一致；420×300 RGBA；原件与Nuke输出504,000个通道样本逐一相同，alpha完整；两个登记产物均可用 |
| H 对照与交付 | 比较官方CPU与Bridge结果，生成同一显示转换的预览／差异图；核验全部停止及依赖清单 | 下列结构和图像条件全部通过；所有11个启动有可信停止；完成结果和文件哈希相互对应，人工视觉单独接收 |

若官方打开或实际组合结果与静态候选不符，先记录真实差异并停止受影响阶段，不使用默认值补齐。未执行阶段保留NOT_RUN。

## 对照验收门槛

1. **结构与语义**：匹配声明的几何拓扑、prim数量／类型、显式材质绑定的存在或缺失、相关primvars和默认着色状态；仅在运行观测确有着色器时核对其ID及连接。无显式绑定必须作为明确预期逐prim核验，不能以“无材质”为由跳过颜色／透明度属性。属性差异表只允许声明的路径映射、宿主管理元数据及执行差异。几何点、世界矩阵、相机／灯光／颜色数值绝对误差≤1e-6，枚举及整数精确匹配。
2. **共同渲染条件**：两侧同一渲染器、采样、帧号、分辨率、色彩配置、灯光与相机。执行前确认本机固定RNG选项并统一；路径变化造成的随机噪声仍按下项评估。采样值由阶段B签名观测、阶段C冷开复核，并在阶段E前按冻结规则封存，不能看过Bridge输出或差异图再调参。
3. **官方CPU对Bridge图像**：在原始线性ACEScg的RGB上，`nRMSE = RMS(B−A) / max(RMS(A), 1e-6)`≤0.05；alpha平均绝对差≤0.005、99百分位绝对差≤0.05。两侧有限值、尺寸及通道必须先通过。门槛是本计划的建议验收值，执行前冻结；超限报告差异，不在本次运行中提高容差、降分辨率或切换渲染器来取得PASS。报告另外保留RGBA各通道最大／平均／RMS误差、最差像素坐标、固定16×16像素分块误差及超限区域边界框，定位全图平均可能掩盖的局部错误；这些诊断不替换上述通过门槛。
4. **Nuke保持性**：Read→Write无创作性处理，工作／输入／输出为ACEScg；Bridge原始EXR与Nuke输出RGBA解码样本全部相同。文件头和压缩字节可以不同，文件身份分别登记。
5. **视觉**：统一观看曝光在Bridge结果产生前基于官方CPU基准固定，所有预览采用同一曝光和显示转换；并排提供官方CPU、Bridge、Nuke图及差异图；灯光位置、形状、阴影、材质和构图可辨认。人工确认单独记录。

## 统一累计预算建议

本次计划建议**11次启动、600记账秒、512MiB**的整实验上限；单操作仍≤120秒、同时≤1个重操作、零自动重试。11次比上一轮8次增加3次，必须在执行前明确确认并冻结。11项算术成立的条件是官方冷开仅导出USD、官方husk单独且仅准入一次；600秒及512MiB是否足够尚无实测保证，准备与运行时持续校验。

| 原生项 | 数量 | 角色 |
|---|---:|---|
| 官方加载／检查／保存 | 1 | hython |
| 官方新进程冷开／导出USD | 1 | hython |
| 官方CPU基准渲染 | 1 | husk |
| Bridge路线alpha图 | 1 | husk |
| alpha原生Nuke观察 | 1 | Nuke |
| Bridge正式建图worker | 1 | hython |
| Bridge交接／HIP保存宿主 | 1 | hython |
| Bridge新进程冷开宿主 | 1 | hython |
| Bridge主渲染后代 | 1 | husk |
| NK准备／保存宿主 | 1 | Nuke |
| NK冷加载渲染worker | 1 | Nuke |
| 合计 | **11** | 包含已知全部原生入口，不含额外探测或重试 |

600秒按统一监督器记账口径累计，包含宿主存活、子渲染、失败和停止清理；它不是每阶段可重新领取的600秒。软件准备耗时另记，不冒充原生运行时间。准入必须先预留剩余必要启动、剩余时间和停止余量；已停止的前段宿主不为查询结果重新启动。

全实验固定首次准入前冻结的同一个scope binding和记账根，11项角色共享该账本。执行过程中不更换scope、输出根或冻结源码，不自动调用`prepare-successor`创建新范围续跑；request ID变化也不能恢复额度。原生执行开始后若源码、原始／已封存输入或允许规则需要改变，结算已有时间和启动数、可信停止所有自有进程并终止本次实验，保留未完成阶段；定位与方案修订不授予再次原生执行额度。预算不足时提交已用数、剩余必要数及停止状态，再提出明确的新预算。未知停止阻止后续启动，旧回执、旧校准或人工PASS不能补充本次证据。

输出根运行前生成唯一目录`outputs/official-karma-disklight-h21-<id>/`。512MiB包括输入副本、HIP快照、USD、EXR、监督日志及临时文件；当前原件本身为56.2MB，准备时按实际复制／快照策略计入完整磁盘预检。不得清理既有29交付或旧失败证据来腾挪本次预算。

## 最终交付

- 官方CPU基准HIP、原生EXR和对应依赖清单；完整原始示例保留在本机工作副本。
- Bridge重建HIP、Bridge主EXR、Nuke NK及Nuke结果EXR。
- 同一显示转换的基准／Bridge／Nuke预览与差异图；原始EXR不做曝光烘焙。
- 参数／拓扑／USD语义对应表、数值图像比较、人工视觉状态、实际预算和停止证据、当前文件哈希。
- 明确的本机打开说明和依赖路径；工程须在最终固定交付路径保存，并在该路径完成本轮冷开。跨机移动不列为本轮通过条件。

正式产物与调试／审核材料分目录保存；应用原件、签名密钥和厂商全量二进制不进入Git提交。原始证据保留，最终结果不混入试错文件。

## 运行前接收条件

只有案例映射和配套代码完成、定向回归及只读独立复核通过、首次启动前的源码／输入／允许规则／11项清单／固定binding与总预算冻结且获得具体执行授权后，才进入阶段B。回归必须证明同一账本第12次启动和600秒耗尽均拒绝、只导出不产生隐式husk、未知停止阻止继续、执行后更换binding或源码不能继续本次实验；运行观测封存验证失败也必须停止。计划批准不等于本机已经完成这些准备，也不代表官方教程已经运行。

官方案例完成后，继续同工程反馈修改与真实中断恢复，再进入WorkBuddy／HY3和第二案例复用；这些阶段各自制定范围与累计预算。
