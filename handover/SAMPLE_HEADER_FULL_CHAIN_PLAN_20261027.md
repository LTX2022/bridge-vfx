# Sample 身份头修复后的正式整链申请（2026-10-27）

本轮按用户最小方案完成修复、软件集成及独立冻结审查；审查无可操作P1／P2，建议 `READY_PENDING_EXPLICIT_USER_APPROVAL`。新的正式候选保持未授权。正式 H21／Nuke 链尚未执行，本报告不宣称已经交付新的官方案例 HIP、NK 或 EXR。[独立冻结审查结果](evidence/20261027-sample-header-integration/frozen-integration-review.json)限定于本次176文件运行快照，不授予真实执行或验收。

## 冻结身份与批准对象

- 候选：`outputs/official-karma-disklight-h21-sample-header-candidate-20261027-01/`。
- Scope SHA-256：`340dbe0c1380949114f5e1bcb0b8542943d15382846ba6e460bde268dcc2012a`。
- Runtime bindings SHA-256：`8f78dd4a6a42af7e19f1b43e215043d41b4ea9239fa65482f036dc33bdd36905`。
- [激活审查记录](../outputs/official-karma-disklight-h21-sample-header-candidate-20261027-01/engineering-activation-review.json) SHA-256：`3b1b0bc6e70d1c8a65b704616bec8c49a38da2f7ca262ea946f2347858493336`。
- 拟执行目标：`/Users/user/Documents/Code_Project/Bridge/outputs/official-karma-disklight-h21-sample-header-20261027-01/`；审查时该目录尚不存在。
- 当前 `PREPARED_NOT_AUTHORIZED`、`execution_authorized=false`、0启动、0票据、`NOT_RUN`。只生成 review，未执行 activate 或真实链。

176份运行源码与当前权威源码和冻结副本逐字节匹配。工具策略、输入、原件、宿主、环境、输出政策、参数、容差、启动清单和目标路径均由上述审查绑定。激活须从这份已审查 snapshot 派生，使用新账本和新签名密钥；不得切换到后来的活动源码。批准不覆盖后续改源码、重试、追加正常样本或扩大预算。

## 修复内容

固定 `sample PID 1 1000 -file /dev/stdout` 提供 Process、Parent Process、Load Address、Launch Time、Target Type 五头。仍按原 Load Address 查询唯一主映像 `__TEXT`，保留 ps、lsof/vnode、stat/hash、父锚点、双观察和祖先链前后复验。

仅该固定命令、同PID、exit0的完整三行成功进度 stderr 可接受；空 stderr 沿用成功行为。错PID、附加参数、改间隔、未知／截断／额外stderr、非零退出、超时均拒绝，无回退或重试。工具5秒、观察16秒、collection22秒、祖先总采集60秒不变。

新增明确的 `process_image_policy`：本候选为 `sample_header_v1`，固定 sample和vmmap的路径、字节数、SHA。缺少该字段的历史 scope 使用 `legacy_vmmap_summary_v1`。新诊断合同精确核对2次定点vmmap，旧合同精确4次；没有放宽为任意次数。生产身份工具记录与额外诊断工具分开。本候选无execution_mode、writer_trace_tools或stack_qualification，不启用额外窗口／正常栈采样。

每次完整 `_observe` 为2次ps、2次lsof、2次固定身份头sample、2次原Load Address定点vmmap。collector就绪前原有1次ps另计，祖先证明会按既有链路重复观察；这些身份工具调用不等同于11次DCC准入，均受原身份期限约束。运行中不为诊断再添加采样命令。去掉未使用汇总不证明旧超时唯一根因，也不保证sample每次更快。

## 软件验证与执行偏差

- 严格离线原件回放34项通过；审计钩子禁止所有进程，启动0、被阻止尝试0。正常头一致、搬移主映像仍拒绝、精确stderr及原截止通过。该组运行于策略集成前的核心补丁SHA `0ceca241…`，不是最终冻结文件的34项重跑；独立审查确认关键匹配器、工具执行、ps／lsof／hash及离线证明验证函数与提案相同。最终集成由下述232项及软件链覆盖。
- 受影响统一回归232项通过，0失败／0错误／0跳过；使用framework Python3.11和`TMPDIR=/private/tmp`，禁止DCC、sample、vmmap，实际无被阻止尝试。
- 新策略八启动软件链通过，明确使用普通Python与底层原生API／进程工具替身，验证真实签名回执、保存／冷开、登记、NK消费及完成门。它不是十一启动官方真实验收，也不证明600秒足够。
- 部署／回执定向38项通过，与统一组有重叠，不相加。首轮Anaconda／临时路径错误及旧部署夹具失败日志保留；修复夹具补齐首轮ps与带签名runtime-ready，原截止和断言不变。
- 实现子任务误执行了包含macOS真采集的两条广泛测试命令，共五次真实测试执行，违反本轮不再采正常样本的要求。涉及普通Python／sleep的真实身份采集，不计作纯软件回归；[执行偏差记录](evidence/20261027-sample-header-integration/EXECUTION_DEVIATION.md)列明测试、已保留日志、清理观察及无法证明精确工具次数的限制。未启动Houdini、Nuke或正式业务链。后续过滤三个真实测试并加拦截的残余组110通过、4个Windows跳过，0失败／0错误／0被阻止原生尝试，与232项重叠，不累加。不能据统一受控回归为0调用而宣称本轮总体无sample／vmmap执行。

[本轮证据目录](evidence/20261027-sample-header-integration/)保留原失败日志、严格离线、统一回归、软件链、冻结检查和历史保护记录。旧球体范围29、旧官方候选及迟采样证据等1304文件／320,163,464字节复核不变；旧官方实验组11启动／202.874349原生秒保持独立历史，不复用剩余额度。软件真采集偏差不是正式H21组的新增DCC消费，必须另列。

## 待批准的正式范围

使用Houdini21.0.631与Nuke17.0v1。官方原例为`karma_user_guide.hip`的`/stage/lights/render_disklight`，输出经`/stage/lights/OUT_karma_lights`。13份原件56,200,300字节保持不变。只编辑独立工作副本：移除switch动态驱动并固定input1，固定共同CPU／输出设置，添加既定Beauty RGBA适配，官方ROP仅USD导出禁止隐式husk。

统一frame1、420×300、Karma CPU、同版OCIO／ACEScg、HALF RGBA、关闭运动模糊和降噪。保留实测几何、displayColor／displayOpacity与有无材质绑定；不补造材质。官方31节点和允许适配逐项核对，Bridge正式注册图35节点／30连接，必须从空工程构造，不能加载官方HIP或USD代替。

| 顺序 | 操作 | 原生启动 |
|---|---|---:|
| 1 | 官方打开、允许编辑、签名观测、HIP保存、退出 | 1 hython |
| 2 | 独立冷开官方HIP、验证、仅导出USD、退出 | 1 hython |
| 3 | 官方CPU参考渲染 | 1 husk |
| 4 | 新420×300同路线alpha校准渲染 | 1 husk |
| 5 | Nuke原生alpha采样与黑白合成验证 | 1 Nuke |
| 6 | 正式GraphRun从空工程构造Bridge图 | 1 hython |
| 7 | 任务宿主交接并保存Bridge HIP、退出 | 1 hython |
| 8 | 新进程冷开同一Bridge HIP | 1 hython |
| 9 | 冷开宿主执行主渲染、验证、登记 | 1 husk子进程 |
| 10 | 消费已登记EXR，保存含OCIO和RGBA Write的NK | 1 Nuke |
| 11 | 独立冷开NK、渲染和登记Nuke结果 | 1 Nuke |

每一步先通过身份门。身份、冻结、输入、预算、文件或可信停止有一项不成立就结算停止；未到达阶段保持NOT_RUN。门通过即在同一scope继续业务，不在身份成功后另开正常样本专项。所有启动受同一账本约束，不用successor或新request恢复额度。

## 总预算

| 资源 | 冻结上限 |
|---|---|
| DCC启动 | 最多11次：hython5、husk3、Nuke3 |
| 累计原生时间 | 600秒，一个总账；宿主与渲染子进程存活时间各自计入 |
| 单操作 | ≤120秒；不是11×120的总授权 |
| 磁盘 | 536,870,912字节（512MiB），含输入副本、HIP、USD、EXR、日志和临时文件 |
| 并发 | 同时1重操作；轻量宿主可在其子渲染期间存活并计时 |
| 重试 | 0；失败关闭，不复用未消耗名额 |
| 身份期限 | 单工具5秒／观察16秒／collection22秒，保持 |
| 额外诊断 | 0项；不添加正常栈采样窗口 |

候选当前约72,987,829字节（69.61MiB）。最终目标目录和执行产物受512MiB约束；准备候选与执行目标分别保留。600秒和512MiB尚无本修复十一启动实测足够的保证。运行准入持续校验剩余启动、时间、磁盘和停止余量。若本范围全部消耗，正式官方组历史加本次上限为22启动／802.874349原生秒；实际失败按消耗报告。

## 必须交付与验收

拟执行目标内交付官方`official/official-cpu.hip`、`official/official.usd`、`official/official.0001.exr`，Bridge保存且独立冷开的HIP及`project/saves/main.0001.exr`，`project/saves/composite.nk`与`project/saves/nuke.0001.exr`；同时提供依赖清单、正式打开说明、产物登记来源、预算及11份可信停止证据。Bridge HIP实际路径由正式保存回执确认，不能只交占位文件。

结构浮点误差≤1e-6，整数／枚举精确；官方→Bridge线性RGB nRMSE≤0.05，alpha MAE≤0.005、P99≤0.05。Bridge→Nuke全部504,000个RGBA解码样本相同，420×300、通道完整且有限，两个登记产物可用。新的同路线alpha校准必须通过。

提供`previews/official.png`、`bridge.png`、`nuke.png`、`difference.png`及经验证索引；观看曝光在Bridge输出前从官方基准固定，统一sRGB Display／ACES1 SDR Video，原始EXR不烘焙曝光。文件身份、显示processor、PNG结构／CRC／尺寸和来源重验通过。机器验收与人工视觉接收分别记录。

本申请批准的是上述review所绑定的一次完整正式链。当前仍待用户明确批准，不将本文件生成、软件通过或review文件存在视为执行授权。
