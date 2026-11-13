# Houdini 22.0.459 原件与兼容迁移边界

当前批准目标：主版 **21.0.631**，兼容版 **22.0.459**。22.0.429 仅保留历史／兼容事实，不能通过改标其 capture 证明 459。本目录仅静态读取精确安装原件并作字节解析；没有运行 Houdini、hython、husk、HOM 实例、cook、保存、仿真、缓存或渲染。未修改产品源码。

安装资源根：`/Applications/Houdini/Houdini22.0.459/Frameworks/Houdini.framework/Versions/22.0/Resources`。本安装的 Python 原生工具源码位于 `houdini/python3.13libs`；不能假定其为 python3.11libs。

## 原件身份与解析范围

| 原件 | 大小（bytes） | SHA-256 |
|---|---:|---|
| OPlibSop.hda | 17298309 | bd7889533d374f98bd4d0d940730602be73e9e64490571f3159fc7451b4e992e |
| OPlibPopDop.hda | 1460000 | 3457429edf7d98873ab63f7b599fa3994c840689c8cfe7aab2472f4c43dc2f4d |
| OPlibDop.hda | 5568490 | bcd8f3d27f766bc324ac2439c77c8afb4667cbcfa0abfc75922ecd4f5c08ddce |
| OPlibLop.hda | 6150226 | 82ea9d10928bb8bd0fecba63f30068e60faa887abf4d2a6c25136dcc89574645 |
| OPlibDriver.hda | 798738 | 2123b13e9c0644a16dfdd4944a829469621d9616e6cc986e1ca5405889361acf |
| OPlibObject.hda | 49971216 | 8f104bc81c31d1b288125b81bef88daa35ad97df9bb33486b65718ddef402811 |

另有 MaterialX.hda、nodes/hom/ref/copy 原帮助包、SDK headers、SOHO Intrinsics、crowdstoolutils、karmautils 的精确路径、大小和 SHA，详见 JSON 来源链。

复用现有 `tools/capture_native_schema.py` 的 `index_sections`、`dialog_parameters`、`dialog_interface`，只调用纯字节解析函数，不调用宿主采集入口。七个 HDA 库独立解析到 **55 个新 459 DialogScript**，保存原始 section；其余 **28 个候选不在这些 HDA 库中**，不等于原生类型不存在，编译节点另需 SDK／原生模板事实。

比较同种历史 DialogScript 来源：**48 个 SHA 与既有 429 完全一致，2 个不同，33 个无同种可比来源或未捕获**。两个不同项是 `Sop/pyrosolver` 与 `Sop/volumewrangle`。不同来源种类（例如旧 help member）不能与新 DialogScript SHA 比较后宣称接口变更。最终精确对照为 `migration-comparison-459.json`；`migration-summary.json` 使用同一修正口径。

- `Sop/pyrosolver` 新 DialogScript SHA：`950bb643b3b71d69d83d334bfa1ad3621ab6590fbd03105abbea2e6e8d4c702d`。已解析到当前所需字段；旧记录与新记录的部分 defaults/menus/size 不同，且旧 parser 有过遗漏字段问题，不能未经原件逐行比较就断言全部都是厂商行为变化。必须以新 459 声明及实际运行时模板／门控读回为准。
- `Sop/volumewrangle` 新 DialogScript SHA：`aa477e2d5cd8364e369b5c608ce85e0f77b1f21ee5d894eef420cdefa44c18bb`。与旧 section SHA 不同，但当前采集字段对已有 supplement 同名字段没有语义变化；不据此推断真实执行相同。
- 新 459 静态参数逐域对照见 `migration-comparison-459.json:families`，覆盖 Pyro、布料／软体／颗粒、Crowd/Hair、FLIP/RBD、粒子／Swarm／海洋／程序几何、MaterialX 和 Lighting。**已捕获 HDA 的 required_parms 未见缺项**；编译节点逐项保持 `NATIVE_TEMPLATE_OR_SDK_BASIS_REQUIRED`。多参数 `#` 声明只证明 pattern，不证明实际实例字段和端口。

## 可凭新 459 原件建立的独立静态事实

### Crowd route 与 transition

以下值均从新 459 原件读取，与现有硬 SHA 一致，可为 459 建立独立版本条目；不能把 429 的来源路径改名。

| 来源 | 459 SHA-256 |
|---|---|
| OPlibPopDop / Dop/popsteerpath / DialogScript | 7919bf5833be4dbda326f4e47773cb35dd131712473919a368b2beef432e015f |
| hom.zip / hou/Geometry.txt | b14324302f4481e0e4dad87e2920e0e10ea01d87182db8b0352a5b5a2cc01bae |
| hom.zip / hou/Parm.txt | 01e930c2f95921c43b962a7a4ace809b978fbe49d987d4bfe12029bfef985704 |
| houdini/python3.13libs/crowdstoolutils.py | 1c4e4af57e9f3fb88fe2673aa5b099ab318c264c0de3c1f716c43a44a96326a8 |
| hom.zip / hou/Ramp.txt | 600a5069a5288905aaaa490f8e8834346a438788cd515f24db3cfed6fdaa45f3 |
| transition 内部 perform_transition.parm | c6d04257dcf8d2713992b82eede36adb44732686ed0187ced74741fd16e2b9ab |

最后一项的完整新来源链为：459 OPlibDop.hda → `Dop/crowdtransition::3.0` → `Contents.gz` → gzip 纯解压 → 4 字节 Houdini wrapper + old ASCII ODC CPIO → `hdaroot/transition/transition/perform_transition.parm`。**170 个记录完整消费、无剩余字节**；目标原始成员为 14194 bytes。本采集不执行成员中的任何脚本或命令。仍须保留现有真实几何、clip/timing、transition 及读回守卫。

### Render 宽度字段与 writer hook

新 459 `Lop/karmarendersettings/DialogScript` SHA：`cc263cb8a2e6e1f964363999322d8395f7c52d7160ea723173a24b23568783fe`。

- `pixelfilterscale`：float size 1，默认 token `1`，range `0! .. 5`，没有 invisible 标记。
- `pixelfiltersize`：float size 1，默认 token `2`，带 invisible 标记；不能当公开可编辑宽度接口。
- 新同版 `houdini/python3.13libs/husd/karmautils.py:1206` 明确 `pixelfilterscale → karma:global:pixelfilterscale`；1309–1319 保留 legacy size 的兼容写入，实际求值或动画值不等于 2 时才导出 `karma:global:pixelfiltersize`。

上述支持以新同版依据保留公开 scale 路线及 legacy guard；**不证明最终 renderer 执行了怎样的 filter**。原件、行号和完整参数记录位于 `render-459-static-consumer.json`。

`husk_tpostframe`、`husk_postframe`、`soho_foreground` 可在同版 `SohoIntrinsics.ds` 及编译 UI 原字节中定位。`compiled-ui-originals-459.json` 保存 82 条候选的编译 UI 原件 base64、路径、大小和 SHA；只作为命名／原件身份事实，未解码成可写 ParmTemplate 类型、默认值或运行状态。所有原生执行入口仍需检查实际模板、channel 和同步等待事实。

## 不可因版本接入而关闭的缺口

1. **F02 effective writer**：实际 husk 进程身份、hook globals 的真实类型、最终逐 product/AOV 的 OCIO/PXL processor/LUT/context/file-rule、有序 filter 与 beauty alpha 仍未取得。Husk 文档、SOHO 声明、父 USD、EXR 或 HMAC 均不能代替。
2. **14 项控制**：新原件可补同版基础节点／参数来源，但未自动提供碰撞独立半径、FLIP 迭代消费、真实切割、质量/约束重建、一次冲击、历史插值、render_v 最终绑定、精确角谱、同面唯一投影或可信朝向 writer。R05 仍只具 initial_active_packed_pieces 条件软件路径；O01 仍只是失效阶段整改。
3. **原生模板和运行事实**：DialogScript 是声明；ports label 不是完整 runtime 端口语义。SDK/编译 UI 也不能代替实例读回。旧真实证据不迁移成新版本通过。
4. **完整 M1**：16 域 48 案例、两个真实上游产物组合、双 denoise producer、资源/离线媒体闭包、全量及当前源码发布/独立接收仍须单独完成。

## 验证与文件使用

`verify_static_capture.py` 只重读安装文件、SHA、INDX、DialogScript 和 CPIO，验证新 raw sections、支持文件、文档、compiled UI base64 和目标 consumer 原字节一致。结果见 `static-verification.json`。声明 flags 用无序集合比较（现有 parser 的 set 迭代会改变列表顺序）；菜单顺序与全部原始字节仍严格保持。未运行任何原生 DCC 程序。

本目录新证据交版本实现者选择并审查后使用。活动版本默认／CLI／GraphRun ID／支持表和文档的源码接入由其他负责人实施；本 worker 不写它们。只读静态核验通过不等于软件全量、真实宿主、M1 或视觉验收通过。
