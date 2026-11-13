# 身份采集精简方案：有限原型结果

## 可执行结论

推荐在同一有界观察内，使用公开 `sample PID 1 1000 -file /dev/stdout` 取得原有五个身份头字段，再用该头的 `Load Address` 调用 `vmmap -w -interleaved PID LOAD`，验证实际存在的唯一 `r-x __TEXT` 和完整路径。其余 ps、lsof/vnode、文件 hash、前后双观察及 5/16/60 秒限制继续保留。

这一路线不把第一个 RX 映射、调用方地址或进程自报地址作为主加载身份。正常和搬移反例已在**同一 PID 内**对照原 full vmmap：五个头字段全部逐值一致；正常定点读回唯一主 TEXT，搬移后旧主加载地址处无 TEXT，仍能拒绝。原型没有接入生产，也不证明完整软件集成或原生宿主通过。

修复的因果边界是：正式身份采集不必为拿到主加载头和主映像区域，收集整个地址空间的 VM 使用统计。旧随机超时在 vmmap 内的具体停留位置仍未确定，不将其描述为已证明的 Apple 工具内部缺陷。

## 有限比较

`compare-filter.py` 在一个普通自有 Python 正常目标上比较 full、指定区域、错误地址和 summary；第二个搬移目标用于反例。每个工具硬限制 5 秒，目标退出均为 0。不存在 DCC、权限变更、超时延长或自动重试。

| 正常目标命令 | 墙钟秒 | 子进程 CPU 秒 | 输出字节 | 身份字段 |
|---|---:|---:|---:|---|
| full vmmap | 1.681 | 1.020 | 268066 | 五个均有 |
| 指定实际主地址 | 0.170 | 0.134 | 716 | 全部缺失 |
| 错误地址 0x1 | 0.155 | 0.122 | 466 | 全部缺失 |
| summary | 1.013 | 0.777 | 4997 | 五个均有，但无 TEXT |

指定地址减少了实测 CPU 和输出，却不提供身份头，因此不能单独使用。`-summary` 仍输出全地址空间统计；最后一个 `-summary` 加 address 对照同样无身份头。这些选项组合已排除，不继续穷举。

公开 `sample` 的 duration 为 0 时，本机接受命令并进入 once 模式，但输出只有 call graph，没有身份头或 Binary Images，因此排除 duration 0。1 秒、1000 毫秒间隔保留所需头字段；选用文档化的数字参数，未使用私有 `noSymbols` 等选项。

## 同 PID 等价对照

决定性数据见 [one-second-comparison.json](one-second-comparison.json)，脚本为 [compare-header-one-second.py](compare-header-one-second.py)。两种采集对同一个仍存活目标按顺序运行，真实进程由父进程最后退出并 wait；不依赖目标自报地址得出验证结论。

| 目标 | 原 full vmmap 秒 | sample 秒 | 头 Load 定点 vmmap 秒 | 五头完全相同 | 定点原主 TEXT |
|---|---:|---:|---:|---|---|
| normal，PID 31228 | 0.897 | 1.327 | 0.139 | 是 | 唯一 r-x，完整路径 |
| relocated，PID 31249 | 0.790 | 1.236 | 0.219 | 是 | 缺失，应拒绝 |

五字段为 `Process`、`Parent Process`、`Load Address`、`Launch Time`、`Target Type`。正常 Load 为 `0x100be8000`；搬移例 Load 为 `0x100498000`，sample 和原 vmmap 一致。搬移例创建同文件新 RX 后解除原主映像映射；地址采集没有改用新 RX，旧 Load 处只有非 TEXT 区域。`sample` 的 Binary Images 在搬移例也没有主执行文件；该列表未被用来替代定点映射事实。

该最后对照中正常 full vmmap 比 sample 加定点 vmmap 快，不声称对每次正常目标都加速。价值是避免全 VM 页统计/完整区域展示路径，同时保留原拒绝反例。有限组没有复现随机超时，也不能证明新的采集不会超时；仍须以相同拒绝和时间上限做正式验证。

实施细节：定点 vmmap 的行前缀为 `--->  __TEXT`，邻区行有缩进。只可窄匹配该合法前缀，继续要求区域起点恰好等于头 Load、r-x 和唯一完整路径。sample 的 stderr 会有成功进度三行，必须只在精确固定命令、同 PID 和成功退出下接受精确已知格式，其余 stderr 继续拒绝；不能全局忽略 stderr。

## 原生依据与复验材料

- [本机 vmmap man](vmmap.man.txt)：address 仅承诺显示包含地址的区域及相邻区域；`-summary` 仅显示汇总。本机 help 同样记录在目录内。
- [本机 sample man](sample.man.txt)：duration 单位秒、samplingInterval 毫秒；`-file` 指定结果文件。1 秒/1000 毫秒及 `/dev/stdout` 路径由本轮实际成功命令验证。
- [本机版本和工具哈希](local-source-facts.json)：精确记录本次采集工具；不假称工具实现源码公开或逐字等同其他版本。
- [第一组 full/address/summary 原始数据](comparison.json)、[1 秒 sample 两例](sample-comparison.json)、[0 秒/summary+address 排除数据](header-target-comparison.json)。所有 stdout/stderr 原样在本目录，未覆盖旧证据。

这是实现前的有限原型和选择依据；生产修改、核心回归、正式整链、双独立验收以及冻结由对应负责人另行完成。本执行者未修改生产、测试、-06/-07、预算或任何真实宿主状态。
