# Bridge 接续执行

当前[18真实工程验收](H21_LIVE_18_RESULT_20261023.md)：真实 alpha 校准通过，41 个构造操作完成；领域初始化将锁定 HDA 内部节点计入显式图而失败。三处节点精确类型修复已真实生效。3/8 启动均可信停止，78.699 秒，范围封闭且零重试；HIP、NK、主场景 EXR 未生成。 HDA 边界与原生类别的最小修复、必要验证及两位独立验收完成；19 已冻结，保持未授权、零启动，修后真实未重验。

此前[16真实工程验收](H21_LIVE_16_RESULT_20261023.md)：真实 alpha 校准与五个 EXR 数值复核通过；正式建图因预期 `light` 与实际 `light::2.0` 不一致而未完成。3/8 次启动均可信停止，32.799 秒，零重试；16 已失败封闭，HIP、NK、主场景 EXR 未生成。精确类型创建的最小修复、必要验证及两位独立验收完成，17 已冻结且保持未授权、零启动；修后真实工程尚未重验。

此前[14真实验收与15入口修复](H21_LIVE_14_RESULT_20261023.md)：14 首次 alpha-husk 因 prerender 缺少 `__file__` 失败，使用 1 次启动；修复后的 15 review 经用户另行授权，生成了本轮 16 独立真实范围。历史原件与消耗分别保留。

此前[原生就绪同步与采集失败早停](NATIVE_READINESS_STOP_REPAIR_20261023.md)：原生就绪同步与采集失败早停两项软件修复及两位独立验收已完成：双Python核心、普通进程真实macOS采集及失败停止、单次无映像模型八阶段软件链通过。13候选为 PREPARED_NOT_AUTHORIZED，0启动/0票据，八次启动预算不变；该软件修复轮未重跑真实宿主，真实工程闭环与M1仍未通过。

此前[12真实工程验收结果](H21_LIVE_12_RESULT_20261023.md)为 FAIL：按11 review激活12后，仅1/8次alpha husk启动，产生1份实际校准EXR，最终整组可信停止、无重试；writer采集遇到原生启动未就绪的stderr而被拒绝，另发现记录采集错误后未立即取消当前作业。HIP/NK/主场景渲染与Nuke消费未到达。12已失败封闭，不续跑；工程闭环、M1、HY3及视觉状态不提升。

此前[09真实验收结果](H21_LIVE_09_RESULT_20261023.md)：已按08review激活并执行，2/8启动后因husk身份绑定缺失及校准结构错误失败关闭；两进程可信停止、无重试。实际生成5个RGBA校准EXR，尚无HIP/NK/主渲染。-06/-07/-08及停止后09原件完整保留，当前不继续真实作业。

当前活动路线：工程闭环 → 反馈/恢复 → HY3 → 复用。旧全 16 域批量扩展冻结，16 域、48+2 案例与原 54 行长期要求保留。当前工程闭环 BLOCKED，M1 NOT_READY。

## 当前颜色规则

按[项目色彩标准决定](CONTROL_DECISIONS_20261004.md#项目色彩标准)，由人工按具体项目确认色彩标准；不把实际颜色 processor、LUT、file-rule 内部追踪作为工程闭环前置条件。本次合成球体与 alpha 校准项目已由用户确认为 **ACEScg**，其他项目仍分别确认。人工选择必须标明来源，并用于 Houdini 输出和 Nuke 输入的一致性检查。

项目选择已接入可信部署配置、producer 请求摘要、产物账本和 Nuke 消费。配置工具 `tools/configure_production_hosts.py` 支持成对的 `--project-id`、`--project-colorspace`，以及 `--project-color-revision`（默认 1）。请填写项目实际确认的输出 colorspace token；不替用户选择标准。生成的 Houdini/Nuke 配置使用相同 `project_color`，来源为 `human_project_selection`。

没有选择时允许建图配置，但正式渲染明确拒绝。项目或标准改变需更新 revision 并使用新请求；旧操作及其产物保留原选择。此字段声明项目认可的输出颜色解释，不自动转换 Houdini 场景或证明原生转换已经执行。Nuke 按登记产物设置并读回 Read/Write 的 colorspace，保持 alpha 校验。alpha、产品/AOV、非颜色处理和成功写出缺项仍阻止 AVAILABLE。

## 按顺序处理

1. 核对 Git、当前候选和调用链，保留已修成果；只复现当前正式入口中的具体问题。维护仓库为 `/Users/user/Documents/Code_Project/Bridge`。
2. 具体项目开始前由人工填写色彩选择；现有配置和产物链保留其来源与版本，不研究内部颜色处理器补证。
3. 当前批准的首例验收采用 [controlled_output_v1](ENGINEERING_CLOSURE_20261020.md)：可信停止成功后独立验证原始渲染、冻结配置、最终完整 EXR 和原生 alpha 校准，再登记供 Nuke 消费。内部 writer/filter/flush/close 保持 NOT_OBSERVED，不再阻止此层受控工程验收；旧严格回执保持原样，不能改标 AVAILABLE。
4. [12真实验收](H21_LIVE_12_RESULT_20261023.md)已按明确授权执行并失败封闭，不修改或续跑09/12。13的就绪与停止修复保留；[14真实验收及15软件修复](H21_LIVE_14_RESULT_20261023.md)已记录实际fileless脚本阻断。15未授权，review只指未来16-authorized；14已失败封闭，不续跑。重新进行真实验收需要新review及新一轮资源明确授权，不能把软件零票当原8次预算重置。06..14全部原件保持，普通Python及软件API通过不代替真实DCC通过。
5. 工程链成立后验证同一任务的反馈、失效与实际 worker 中断恢复，再进入 HY3 和第二案例复用；各阶段仍需对应授权。

## 保留的成果

- sphere_ground_v2 双版独立球/地面 prim、有效材质的软件链，以及 sphere_ground_v1 保存/反馈/冷重开兼容；见 [Karma 工程门](KARMA_ENGINEERING_GATE_20261016.md)。
- Nuke 登记来源、颜色/alpha继承、raw/Write读回及失败回滚；见 [writer 链](WRITER_CHAIN_20261016.md)。人工项目选择已接入此链，保留现有一致性校验。
- writer 可执行文件冻结、signed started 宿主锚点、OS image/祖先链、读取预算、producer/终态重验，以及慢采集监督和 Unicode 摘要修复；见 [进程身份接口](PROCESS_IMAGE_IDENTITY_20261016.md)。
- 当前四 wheel/三类 Skill 的已验证安装结果。源码未变时不重复全量和安装；后续代码改变后按受影响范围验证并同步发布副本。

## 授权与证据边界

Houdini 21.0.631 为主，22.0.459 为兼容目标，Nuke 17.0v1。旧429证据不改标为459。暂不启动 Houdini/hython/husk、Nuke、WorkBuddy/HY3、模型、仿真、缓存或渲染；2026-10-15 只读采集是已结束的一次性例外。

SideFX支持问题未发送，用户当前不要求发送。既有条件性实验设计不是运行授权。受控策略仍要求原生 alpha 校准、成功执行/可信停止、最终文件完整性和身份一致；无法确证时保持具体阻断。ACEScg 选择本身不是宿主启动授权。

共享文件同时一名实现者；审查者只读。macOS 临时路径使用真实路径；未知停止保槽，可信停止后账本恢复只补登记。不改原 Desktop 主工程，不自动提交或推送。完整历史事实按各报告当时的源码和范围读取。
