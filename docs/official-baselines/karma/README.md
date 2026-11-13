# 官方 Karma 最小对照案例

日期：2026-10-16。当前完成的是**官方材料归档、静态分析及重建合同**，没有生成经宿主验证的新 HIP，没有执行建图、cook、渲染、Nuke 或 HY3。完整 M1 仍 NOT_READY。

后续真实对照见 [官方Karma DiskLight执行计划](../../../handover/OFFICIAL_KARMA_COMPARISON_PLAN_20261026.md)。已通过的派生球体／地面工程链见 [2026-10-26真实结果](../../../handover/H21_NUKE_REAL_CHAIN_20261026.md)。

## 来源与可复验材料

SideFX 的 [Karma User Guide](https://www.sidefx.com/docs/houdini/solaris/kug/index.html) 明确说明各章示例随 Houdini 安装，位置为 `$HFS/houdini/help/files/karma_user_guide`。优先使用本机精确安装目录的原件，不将滚动网页当作每个 build 的运行证据。

| 安装目录标签 | 主 HIP SHA-256 | stage.userdata 中的版本 | CPIO 成员数 | 保存的 usdrender_rop 节点数 |
|---|---|---|---|---|
| 21.0.631 | `831b34f61491caab897aa357eead398e3d770ac2a1c9187ea4ca4e669cc29106` | 21.0.440 | 23039 | 96 |
| 22.0.459 | `2e38501cfe5b59f3d085d48be3fee29d35761f754c5e950a1a4562531745ea88` | 22.0.372 | 26153 | 113 |

安装目录版本与场景中保存的版本是两种事实；本次没有启动应用来重新确认运行版本或打开兼容性。成员数和节点数只证明文件内容，不是执行通过数。

每版各 13 个原文件：主 HIP、两份 custom_nodegraphs HIP、HDA、MaterialX/JSON 资源和 5 张 EXR 贴图。两版主 HIP 不同，其余 12 个相对文件同字节。逐文件大小/SHA、选定节点的成员偏移/SHA、保存的参数与连接见：

- [H21 静态观察](karma-21.0.631.json)
- [H22 静态观察](karma-22.0.459.json)
- [机器可读重建合同](rebuild-contract.json)
- [只读复验工具](../../../tools/inspect_official_karma_example.py)

原例文件本地工作副本放在仓库 `outputs/official-karma-20261016/vendor-originals/<安装目录标签>/`，复制后逐文件核对大小/SHA；不修改应用原件。Git 保存上述报告、来源与重建要求，不收录整套厂商二进制。新机器从自己相同版本的安装目录取得原件并核对摘要。

原例声明两项 HDA：`$HIP/hda/helper_tools.hda` 和 `$HFS/houdini/help/examples/nodes/sop/laplacian/LaplacianSmoothing.hda`，本机两版均存在，摘要见各版报告。前者随本地工作副本保留，后者由相应安装提供。这里只核对声明文件；表达式、op引用、内嵌定义、回调和实际读取未求值，**资源依赖闭包尚未证明**。

## 已查明的接口差异

| 原文件位置 | 保存事实 | 对实现的约束 |
|---|---|---|
| `/stage/sphere`、`/stage/backdrop` | `sopcreate`，有内部几何网络 | 适合核对几何到 USD 的组织；不能把存在节点视为已产生几何 |
| `/stage/materiallibrary3` | `materiallibrary`，材质前缀 `/World/Materials/` | 材质建立与绑定须分别验证，不能只创建库 |
| `/stage/lights/camera1` | `camera`，`/World/Camera`、focalLength 保存值 390 | 保存值依赖原场景尺度，不能直接套到新的单球场景 |
| `/stage/lights/light1` | `light::2.0`，`UsdLuxDiskLight`，编码的 intensity/exposure/radius 字段 | 核对实际同版 operator 和可编辑字段；节点名、语义控制名与原生字段不能混用 |
| `/stage/lights/karmarendersettings` | **实际类型 `karmarenderproperties`**，非同名的现代类型；保存 420×300、motion blur off、denoiser off | 不能按节点名字推导类型或复制所有旧字段 |
| `/stage/lights/OUT_karma_lights` | `usdrender_rop`，保存 renderer 为 `BRAY_HdKarmaXPU`；输入经过 update_output_image_path；loppath 带表达式 | 不能跳过原依赖后直接复用输出，也不能把保存的 XPU token 当作本机可用证据 |

SideFX 已将 [Karma Render Properties](https://www.sidefx.com/docs/houdini/nodes/lop/karmarenderproperties.html) 标为自 21.0 起弃用并指向 `karmarendersettings`。Bridge 新图按当前正式映射核对 `karmarendersettings`，原例保留为旧设置的对照；迁移映射及实际效果尚未验证，不直接修改厂商工程。

静态报告记录的是选定节点的原始保存 tokens，未运行 HScript/Python/VEX，未评估参数引用，也未取得实际 USD、writer 或颜色事实。

## 软件装配与预检结果

2026-10-16 已静态编译两版灯光/材质注册图，并修复预检的案例选择与逐卡版本约束；5项定向验证和有限范围独立复核完成。当前CLI仍因原生依据未解决而拒绝；该轮范围见 [预检结果](../../../handover/KARMA_PREFLIGHT_20261016.md)。最小场景冻结参数现已接入正式软件建图/颜色反馈/保存与新进程读回，54项受影响回归通过，接口及边界见 [冻结参数接线](../../../handover/KARMA_FROZEN_PARAMETERS_20261016.md)；这不代表真实宿主、输出或视觉通过。

## 最小重建目标

这是从官方组织方式派生的**新对照场景设计**，并非从主 HIP 提取后已经可运行的子工程，也不要求与某一官方示例逐像素一致。

- 一颗不透明球体、一个地面、一种 MaterialX Standard Surface、一盏 Disk Light、一台固定相机。
- Y-up、米制；球半径 0.5、中心 `(0, 0.5, 0)`；地面在 y=0。
- 相机位置 `(3, 2, 4)`、看向 `(0, 0.5, 0)`，焦距建议 50mm；灯位置 `(2, 3, 2)`、指向球体，半径建议 0.5。
- 材质 base_color 建议 `(0.18, 0.18, 0.18)`、roughness 0.5；无外部贴图、无位移、无仿真、无运动模糊和降噪。
- 首次目标是 frame 1、128×128、Karma CPU 的静态图；之后另行确认反馈作业，再将 base_color 改为 `(0.5, 0.18, 0.18)`，检查材质变化及无关工程保持。

以上数值是待执行案例的设计值，不是原工程的观察值或资源授权。Karma CPU 选择用于隔离首例的引擎变量；实际引擎与进程事实仍需核对。

### 需要建立的连接

1. 几何经正式导入进入受控 USD Stage；地面和球体有不同且稳定的 prim 路径。
2. MaterialX 图输出实际 surface/material，材质对球体的绑定能读回；地面外观明确。
3. 相机、灯光与材质处于该 Stage；实际 RenderSettings 绑定该相机、一个 RenderProduct 及所需 RenderVars。
4. 正式 Driver/usdrender 与保存的源 LOP 绑定，按任务目录产生精确帧输出；不能用一根跨上下文连线替代路径绑定。
5. 真正完成的输出由控制端登记，再作为 Nuke 的输入；Read→Write 验证与完整合成图分开报告。

使用既有 `prepare_workbuddy_graph.py`、注册域/图目录、GraphRun 和任务宿主，不创建另一套执行器。最小案例不等于完整领域通过：关联 `lighting_camera_render_v1`、`material_lookdev_v1`、`nuke_composite_v1` 的原有 case/要求，未覆盖控制保持未完成。正式目录、图大小或字段无法表达该图时，先记录具体缺口，不能手改 manifest、调用私有 RPC 或加载现成 HIP 冒充重建。

## 验收步骤与当前状态

| 步骤 | 必须验证的实际结果 | 当前状态 |
|---|---|---|
| 1. 官方对照 | 原件及副本 SHA 对应，所需依赖与许可/宿主可用；获准后验证可打开 | 原件/副本静态核对完成；打开 NOT_RUN |
| 2. 正式重建 | 从干净任务场景建立上述角色与连接，完整参数/材质绑定读回 | NOT_RUN |
| 3. 保存/重开 | 保存内容、回执与版本绑定；旧自有 worker 可信退出，新身份重开后结构一致 | NOT_RUN |
| 4. 短帧与登记 | 真实执行 frame 1；确认自有停止；writer/颜色/AOV/filter/alpha 与最终 EXR 关联；登记成功 | BLOCKED：effective writer/AVAILABLE 等共用链缺口仍在 |
| 5. Nuke | 按登记 artifact ID/version/帧/颜色/字节消费，保存/重开 NK，实际 Write 可读 | NOT_RUN；正式消费与完整合成接线仍需补齐 |
| 6. 反馈 | 正式 base_color 修改、语义读回、新版本与失效范围正确；反馈后结果满足目标 | NOT_RUN；完整反馈驱动需按当前缺口核对 |
| 7. 复用/恢复 | 第二输入无案例专用分支；中断实际工作进程并可信恢复，副作用不重复 | NOT_RUN |

正式链的已知阻断见 [路线记录](../../../handover/FEASIBILITY_AND_CLOSURE_20261016.md) 和 [M1 缺口](../../../handover/M1_GAPS_20261015.md)。本轮静态结果没有关闭这些问题。

## 实际运行前需确认的具体范围

先提出单独的 M1 前有限实验例外；当前仍禁止启动真实宿主。以下是**未确认的资源建议**，不写入任何 confirmed scope 或真实支持索引：

- 主版 H21.0.631；兼容版 H22.0.459 在主版证据成立后单独执行，不能复用主版回执。
- 初次只做一次建图/保存/新进程重开和 frame 1 的 128×128 CPU 输出；是否包含 Nuke 17.0v1 与具体帧另行列明。反馈与恢复属于后续独立作业，不自动授权。
- 每个公开短作业不超过 120 秒、单重型作业；初次实验建议输出/临时/日志总预算 256 MiB。宿主启动/重开监督以及实验累计时间上限也要明确，不能按每次调用重复获得新预算。
- 新任务根建议放在 `outputs/official-karma-20261016/live/<独立实验ID>/`，实际 scope 冻结绝对路径、request/content/build、可信可执行文件和插件 build、总作业数与累计预算；不复用历史身份。
- 无仿真缓存，无模型调用或素材上传；若后续接入 HY3，仅传已登记且获准的合成材料。
- 缺完整原生依据或现有预检拒绝时保留 BLOCKED。有限实验授权不自动绕过 native_basis、AVAILABLE 或资源门槛；所需采集/软件修复应先按具体范围完成。

## 只读复验方法

在仓库根使用普通 Python 3.11，**不要使用 hython**。`HFS_PATH` 是操作者指定的安装 Resources 路径；工具只读文件，不运行该目录中的程序。

```sh
python3.11 -B tools/inspect_official_karma_example.py \
  --resources "$HFS_PATH" --installed-build 21.0.631 \
  --output /private/tmp/karma-21.0.631-new-inspection.json
```

输出目标必须是新文件；H22 使用自己的 Resources 和 22.0.459 标签。标签只是来源记录，工具明确 `runtime_version_verified=false`。对照 source_sha256、资源清单、成员 SHA/offset 和节点 tokens；不以本轮新文档改变旧 frozen build 的结论。

本轮验证包括两份实际 HIP 的完整边界解析、确定性复验和少量损坏归档反例。未运行生产全量；生产代码、Skill、支持等级和真实验收索引均未修改。Git 接手者可用上述工具和本机原件复验静态事实，不能将本材料包描述成真实宿主或完整 M1 已通过。
