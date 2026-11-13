# G03 新实例登记与故障恢复修复（Windows 软件）

本批补通图 worker→任务宿主及保存→确认退出→新 PID/nonce 的 G03 服务端登记恢复。原来两版正式入口在 worker 完成后调用 `agent.fx.apply_candidate` 均报 `GEOMETRY_REGISTERED_COHORT_REQUIRED`；当前受控进程链可以修改、保存并在新实例直接读回 3，没有重新 apply。证据仍为 `BLOCKED / parameters_only`，不证明实际 VEX 变形、跨帧或下游消费，也不是全 16 域 M1 接收。

基线 HEAD 为 `0a52552f5915375dfb0f3551e08928e9e624390d`，保留全部既有未提交增量。Python 3.11.9，Windows 10.0.26300；仅实际 Python/TCP/监督器及显式底层 HOM 替身。真实 Houdini、Nuke、HY3、模型、仿真和渲染未启动，不自动提交或推送。

## 实现与恢复边界

Registry 新增有界 `checkpoint` 和事务式 `reopen`，保存认证 manifest、固定角色/pack 摘要、旧生产者 binding、实际 rest basis、registration，以及 13 个完整参数观察。checkpoint 上限 256 KiB。恢复必须获得 addon 私有的已验证 HIP/保存合同授权，并重新检查当前身份、根租约、节点实例/session、输入文件与实际 rest 几何、持久程序及 gates；仅 userData、请求 payload 或内存缓存不能恢复权威。

Addon 将 checkpoint 纳入建图/候选 manifest 和实际保存场景合同。图交接核验封存 HIP 与固定布局；保存重开核验自有保存摘要及完整场景合同，转移当前根租约后建立新登记。恢复不调用 initialize、不重新设置保存的参数。`collect_evidence` 增加 G03 的实际参数读回，当前仅验证认证 rest 帧；其他帧不能靠默认数据获得成功。

恢复事务跨越完成回执和最终登记确认。失败清理 scope/cohort、恢复 active-save/generation，并按实际完成记录的完整内容、CAS 和摘要撤销本次尚未成立的 completion。完成记录在真正落盘前由对应私有 operation scope 捕获，不能依赖已漂移的当前身份或外围返回值；其他作者的新记录不会被回退。graph_bind 的嵌入 manifest 与 sidecar 同时回滚。reconcile 先从该 operation 的可信保存合同决定是否需要 G03，缺失当前 manifest、checkpoint 或登记均拒绝补签。

## 实跑结果

| 记录 | 结果与范围 |
| --- | --- |
| 正式 baseline | 1 方法、两版均复现登记缺失，退出 1；保留原件 |
| 组件最终 | 16 方法通过，退出 0；仅组件接口/事务反例，模拟身份不替代进程验收 |
| 中心 core-v1 | 78 方法诊断、14 个拒绝用例因错误期待未包装异常而报错，整体退出 1；未计为通过 |
| fixes-v1 / 较早正式 | 33 方法及两版正常链通过；后续复核仍发现 R04/R05，因此这些记录不能代替最终故障验收 |
| 当前 fixes-final | **36 方法，0 失败/错误/跳过，125.016 秒，退出 0，源码前后不变**；覆盖 14 个 G03 方法、共同场景转换、私有重开、持久化及正式边界 |
| 当前 formal-current | **1 方法覆盖两版，0 失败/错误/跳过，100.453 秒，退出 0，源码前后不变**；实际生成 server、监督 worker、TCP 宿主、保存、确认退出和新实例直接读回 |

| 软件版本 | 最终宿主 PID | 保存值→新实例直接读回 | 边界 |
| --- | --- | --- | --- |
| 21.0.631 | 36052→21416，nonce 改变 | 3→3，未重新 apply | `BLOCKED / parameters_only` |
| 22.0.429 | 33364→16968，nonce 改变 | 3→3，未重新 apply | `BLOCKED / parameters_only` |

正常路径保留同请求只启动一次 worker 的断言、40 KB 的 Windows 文件运输，以及实际持久参数比较。原始 rest 文件、HIP、回执、运行日志、SQLite、生成清单和独立复核原件按 [索引](evidence/20261013-geometry-reopen/index.json) 归档；[源码绑定](evidence/20261013-geometry-reopen/source-binding.json) 记录实际命令、解释器/系统、退出码、源码和生成快照摘要。压缩原件可还原核对原 SHA，不覆盖旧移交包或冻结日志。签名私钥和监督器环境未归档；运行期验签成立不等于离线副本可以独立验签。

独立 reviewer 未参与实现。复核发现的 completion 失败留登记、拒绝后补签、graph_bind 持久化未回滚，以及身份漂移/manifest 缺失边界均由主实现整改。最终 [独立限定结论](evidence/20261013-geometry-reopen/raw/outputs/geometry-reopen-20261013-review/CURRENT_CLOSURE.md) 为 PASS_SCOPED：最后受影响边界两版共10次独立观察符合预期，包括真正 writer 落盘后抛错与另一作者新记录的保留。早期 BLOCKED 原件保留；正常链不能覆盖故障链，限定复核不替代全域接收。

## 下一步与未完成

G03 的新实例参数登记恢复已补；实际变形 P、拓扑/N/其他属性保持、transform/copy 消费、实例点属性/count/seed 和跨帧 rest 稳定性仍缺 native 输出证据，不能改完整生产 writer 为 AVAILABLE。20 项批准控制继续保持 5 项有条件映射、15 项 blocked；B 组合、公共 husk/writer/output/AOV/filter/alpha、完整 Nuke/降噪消费、48+2/54、最终全量、安装及全域独立接收尚未完成。后续先建立这些事实的合法采集和反例，再运行相应正式链；没有新源码变化或风险不重复已通过全量。

macOS 为待目标机器验证；真实宿主、模型、视觉与生产验收分别为 NOT_RUN。延续相同源码和 Python 3.11；命令及路径约束见 [macOS 清单](MACOS_REVERIFY_20261004.md)。
