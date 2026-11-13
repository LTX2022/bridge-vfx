# G03 跨帧静止基准与原始输出采集

本批修复登记后的 G03 在非 rest 帧调用正式 `agent.fx.collect_evidence` 时被 `GEOMETRY_SOURCE_FRAME_REQUIRED` 拒绝的问题，并增加原始输出、实际输入几何及公有属性的有界采集。参数读回仍为 `BLOCKED/parameters_only`；输出记录为 `BLOCKED/raw_geometry_observations`。这些软件事实不证明真正 VEX 编译、变形公式、Copy to Points 执行或全 16 域 M1 完成。

基线 HEAD `0a52552f5915375dfb0f3551e08928e9e624390d`，保留全部既有增量。仅受控 Python、TCP、自有监督进程及明确底层 HOM 夹具；真实 Houdini/Nuke、HY3、模型、仿真、缓存和渲染未运行。本批不提交或推送，也不覆盖旧日志。

## 当前实现

Registry 优先使用同 build 已捕获的 `geometryAtFrame(rest_frame, output_index=0)` 读取实际 rest 几何；没有该 API 只允许当前帧恰好是 rest 帧。跨帧还读取当前 source，并检查 P/N/id、类型/存储、点数和多边形连接与冻结 rest 完全一致。动态 source 拒绝，不通过修改全局帧或伪造帧标签绕过守卫。Host 分别保存采样帧事实与 rest basis，原来的 basis/userData/checkpoint 严格比较保持成立；参数观察结束后重新检查身份、认证输入及帧。变化后的计划不能沿用旧采样上下文。

新 `native_geometry_observation` 只读取已取得的 HOM 几何，保留实际点/面/顶点编号、多边形闭合与连接，以及 point/primitive/vertex/detail 公有属性的元数据、默认值、options 和值。没有属性仍然缺失，不补 N/id 或其他默认成功值。`geometry_sha256` 绑定几何内容，另一个观察摘要绑定路径、帧和输出口。私有属性、组、packed/volume、数组和未知存储未被此采集器证明。单观察最多 8192 点/面、65536 顶点、256 属性、512 KiB，另有总标量、tuple 和字符串预算；同步原生 API 的时间仍由既有宿主监督约束。

正式 evidence 增加 `native_geometry_outputs[frame]`，读取固定自有 source/deform/transform/scatter/point_variation/copy 的 output 0，并读取实际下游 inputGeometry。输入数据与上游输出的摘要匹配只是观察一致性，不能证明其数学或仿真语义。source 与 deform 都采齐时记录拓扑、P 及其他公有属性的原始比较；没有按请求幅度计算“成功 P”。所有原生缺口继续列出。

采集前后核对实际节点/session、身份、冻结输入、程序/gates、固定连线、节点类型/可编辑/bypass/cook errors 和声明参数。后面的懒读取若改变早先节点或 seed/scale，整次操作拒绝。所有帧输出的完整 JSON、参数上下文、缺项和 frame key 均计入 2 MiB 预算；不足时拒绝完整操作，不返回过限证据。正常和失败调用均走原始帧恢复。

## 实际验证与独立复核

实际命令、退出码、Python/系统、源码和生成摘要以 [本批源码绑定](evidence/20261013-geometry-observation/source-binding.json) 和原日志为准。两名实现者分别独占 Host/Registry 和采集器，另一个实现者独占 addon 反例测试；主 agent 独占 addon、正式进程测试和集成，独立 reviewer 不参与对应实现。

正式基线两版在负帧被拒绝，2 个方法、2 个 subtest 错误、退出 1；失败原件保留。早期正式进程诊断正常执行但源文件在运行期间发生变化，退出 1，不能引用为当前验收。独立初审复现晚期状态、完整输出预算、参数 alias 和最终懒读取身份漂移四项问题；整改后的 18 项独立观察关闭四项问题，源码绑定和原日志均保留。

最后 33 方法集成组有 32 方法通过，另一个方法两版均发现新参数上下文的 tuple/list 持久化表示不一致，整条命令退出 1、357.531 秒，不写成整组 PASS。新字段最终使用既有 `_json_safe` 统一 JSON 表示，守卫仍比较完整原生事实；此次只复验受影响的输出/跨帧/镜像及正式进程，不重复无变化的 14 项保存恢复反例。最终表和独立补充复核绑定整改后的源码。历史阶段日志保留为诊断，不与最终结果混用。

| 实际记录 | 当前结果与边界 |
| --- | --- |
| 采集器定向 | 27 方法、退出0、无失败/跳过，0.172秒；自身生产/镜像/测试摘要与当前相同。 |
| Host/Registry/checkpoint 定向 | 84 方法、退出0、无失败/跳过，51.093秒；自身绑定的六文件未变化，未因其他路径改动重复该组。 |
| JSON整改后集成 | 输出、跨帧及镜像共19方法，233.625秒、退出0，无失败/错误/跳过，完整源码前后相同。正常保存读回以及晚期状态/seed/scale/输入/身份漂移、无预算和固定非预测几何均有断言。 |
| JSON整改后正式进程 | 1方法覆盖H21/H22，113.329秒、退出0，无失败/错误/跳过，完整源码前后相同。实际建图→修改→保存→确认退出→新PID/nonce重开→直接读回3；负/零/正帧均读取原始source P/N/id和polygon，原帧恢复，没有重新apply。 |

完整2MiB输出预算的独立边界序列实际返回2096589字节，低于2097152上限；完整JSON与frame key逐项计费，末帧未采到的输入明确missing。零剩余预算拒绝且没有输出获取。512KiB是单个collector观察上限，不是整个帧bundle上限，也不是旧RPC所有字段的总上限。

本批 [原始证据说明](evidence/20261013-geometry-observation/README.md)保存226份原件、40554634原始字节和逐项恢复摘要。两个生成快照各135文件，逐项与当前根源码一致。H21自有宿主PID11172→29176，H22为18436→31848，nonce改变且旧进程退出确认；新实例在-1/0/1/2帧直接读回保存值3和原始source，原帧1恢复。

独立 [四项整改复核](evidence/20261013-geometry-observation/raw/outputs/geometry-observation-20261013/review/CURRENT_CLOSURE.md)及JSON归一化后 [补充复核](evidence/20261013-geometry-observation/raw/outputs/geometry-observation-20261013/review/JSON_CLOSURE.md)均为PASS_SCOPED；后者验证仅一行变化、其余18文件不变、JSON值完整保持和当前计费，并未把旧18观察写成重新执行。无本批限定阻断，但仍不是全域接收。

## 仍未完成

G03 仍缺同 build 的实际 VEX 编译/非零与零值变形、完整原生属性保持、真实 transform/copy 消费、实例点 ID/P/pscale/count/seed 在修改前后的保持，以及真实跨帧/新实例语义。软件静态 source 的跨帧读回不能替代这些结果。其余 15 项控制、B 组合、公共 husk/writer/output/AOV/filter/alpha、Nuke/降噪、48+2/54、最终同源码全量、安装和全域独立接收仍未完成。macOS 待目标机器验证；真实阶段、模型、视觉与生产分别 NOT_RUN。
