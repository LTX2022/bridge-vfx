# R05 可信基准、正式入口与回滚修复（2026-10-13）

本批修复 RBD `velocity_variance` 的软件安全与正式启动链；不是全16域M1完成报告。保留当前全部增量和失败原件，不自动提交、推送或重新生成安装完成版。Git基准仍为 `0a52552f5915375dfb0f3551e08928e9e624390d`。

## 已修复的实际问题

- 旧 Host 在更换实际 PID/nonce 后，仅凭可重摘要的 userData 接受原 basis/program；两版零幅度反例均失败。现在基准由当前宿主字典内的私有记录签发，绑定 task/root、完整宿主身份和实际节点session。普通 userData、异宿主 pending plan、同路径替换节点及新身份均不能授予权限；同宿主新 Host 对象可复用自有记录。
- 正式图 worker 没有 task-host 的身份字段，旧初始化把 R05 视作可选未登记载体并跳过门控，正式候选在 class 检查失败。现在复用已存在的可信 producer 身份采集，保留根租约与当前软件版本核对；生成 worker 实际初始化载体，原门控没有改成默认成功。
- 参数快照、userData和私有签发记录一起回滚。实际 addon 恢复入口先由 Host 在同一串行边界内核对有效租约、身份、节点session和参数路径，再恢复参数和登记；失去权限时不先写参数。
- 关闭迟到的 userData/FPS、源几何、驱动、节点状态和连线漂移窗口。读取 userData/FPS 后才读门控；下游实际几何采集后按 consumer→carrier→configure 逆序重采实际事实，再检查当前状态。比较的是实际读到的数据，没有从请求生成成功几何。
- 原生采集增加共享元素、顶点、属性、值、字符串及完整JSON预算；先核对计数/元数据再冻结和读取值，拒绝数组、重复属性、异常storage、循环、无效拓扑、非有限数和帧漂移。正常事实 schema、接口及两版固定样本摘要保持兼容。Host连接枚举最多读取5项并在超过4项时拒绝；collector输入枚举另有256+1上限。
- 正式只读preflight纳入既有错误处理，保留原拒绝码，避免 RPC 只返回无法定位的 `COMMAND_FAILED`。写入顺序、拒绝条件和失败释放规则保持一致。

## 最终实际验证

工作目录为仓库根，解释器为项目 `.venv/Scripts/python.exe`，Python3.11.9，Windows10.0.26300。精确命令、完整源码前后摘要、系统版本、退出码及原始日志见 [证据绑定](evidence/20261013-rbd-authority/source-binding.json) 和 [原件索引](evidence/20261013-rbd-authority/index.json)。

中央runner的源码集合不含 `tools/native_schema_test_boundary.py`；归档单独记录其当前摘要，并核对仍与上一G03绑定相同，不伪称它在本组已有完整before/after记录。同build HOM文档和vendor包摘要只提供静态接口依据，不是实际native运行证明。

| 最终命令/范围 | 实际结果 |
| --- | --- |
| `outputs/all-domain-20261009/run_tests.py rbd-authority-20261013-integration-final-v2 ...` | 97 methods，0 failure/error/skip，退出0，56.625秒，源码前后一致；包含Host/collector/永久复核反例、旧候选回滚、6项Flip/RBD合同、镜像及实际RBD activation/几何/回滚 |
| `outputs/all-domain-20261009/run_tests.py rbd-authority-20261013-formal-final-v2 test_rbd_authority_process` | 1 method覆盖两版，0 failure/error/skip，退出0，84.328秒，源码前后一致；真实生成server、TCP和受控Python/Windows Job执行链 |

正式测试的底层 packed 几何为固定原始值，与请求无关。零幅度保留原始v/w及形状；非零请求因底层没有执行VEX而被实际消费检查拒绝，参数及登记回滚。随后实际保存、确认自有worker退出、重开新PID/nonce并直接读取相同保存参数。没有 R05 verified-checkpoint 权威时，再次候选必须返回 `RBD_VELOCITY_AUTHORITY_REQUIRED`，参数不变；这验证拒绝，不能算正向R05恢复。

| 软件版本 | 原PID→新PID | 实际停止事实 | 生成快照 |
| --- | --- | --- | --- |
| 21.0.631 | 23736→39284 | 经 OwnedProcessHandle 校验；child wait成立，原PID23736，Job active=0 | 135个代码文件，当前根源码0差异 |
| 22.0.429 | 30520→17704 | 经 OwnedProcessHandle 校验；child wait成立，原PID30520，Job active=0 | 135个代码文件，当前根源码0差异 |

nonce也已改变，最终停止原件另存。停止结论来自实际监督器验证的回执，不从新PID或超时推断。安装、真实DCC、仿真、渲染、模型、视觉、生产和macOS均未运行。

## 独立复核和失败原件

未参与实现的 reviewer 发现 R01–R05 五个问题：userData晚读隐藏gate变化、恢复先写后验权、恢复缺租约复验、晚期消费者导致源事实陈旧、第二处连接枚举无界。全部已整改，永久6方法和两版原始反例已验证；[最终独立复核](evidence/20261013-rbd-authority/raw/outputs/rbd-host-20261013/review/ERROR_CODE_CLOSURE.md) 确认425项源码与两组最终记录一致，并限定关闭五项缺陷及公共拒绝码问题。局部探针退出0仅表示探针完成，必须按其中实际观察判断。

诊断不改写为PASS：最初真实Host新身份反例退出1；collector旧边界22方法出现26个失败项；正式v1/v2在建图初始化失败，v2另有测试SQLite未关闭导致的Windows清理错误；v3暴露生产身份/初始化问题；v4错误预期公共异常包装；v5使用错误停止回执字段；formal-final在新PID阶段因公共拒绝码丢失失败。integration-v2的91方法还保留一项旧macOS vendor归档路径检查跳过。它们及其后续改动阶段结果均留在原件索引，不与最终97方法合并成全绿计数。

## 仍未完成与下一步

1. R05 保存合同须增加可信完整checkpoint，并由已验证HIP/scene-contract的私有恢复入口重新签发当前身份；不能采用 userData、重摘要或新实例 reapply 代替恢复。当前新PID正向R05基准恢复明确BLOCKED。
2. 非零VEX实际执行、Bullet初始事件消费、时间/单位、完整属性保持及跨实例稳定随机分布仍缺原生事实。本批固定底层零幅度成功不替代这些事实。其余15个blocked控制、B组合、公共writer/output/filter/alpha、Nuke/降噪、48+2/54及最终全量/安装接收仍待推进。
3. 已完成的G03参数恢复与原始观察保持其限定范围，不重做，也不提升为真实变形完成。当前RBD改动不扩大实际DCC授权。

完整事实上限为2MiB；元素8192、顶点65536、属性4096、scalar1048576、单字符串4096 UTF-8字节、几何深度2。HOM自身返回容器、冻结和单个同步原生调用可能已经分配/阻塞，Python消费有界不等于原生内存或时间全部受控，仍依赖自有进程监督。双采样不是跨节点原子快照。若合法parameter setter内部随后改变宿主身份，已完成的那次参数写不能通过跨身份回滚撤销；后续登记拒绝，不宣称全事务原子恢复。

## macOS复验命令（待目标机器验证）

按 [macOS环境说明](MACOS_REVERIFY_20261004.md) 设置项目Python3.11和PYTHONPATH，在新目录保留原始证据：

```sh
python3.11 -B -m unittest -v test_native_rbd_controls_program test_rbd_host_authority test_rbd_addon_authority test_rbd_geometry_collection_bounds test_rbd_review_guards test_native_candidate_review_repairs test_controller_entry_client_sync
BRIDGE_TEST_RBD_AUTHORITY_ARCHIVE=/absolute/new/evidence/directory python3.11 -B -m unittest -v test_rbd_authority_process
```

正式测试需要同时具备H21/H22同build静态接口。核对POSIX停止事实并在目标机器适配平台字段；Windows专用 `job_active_processes` 断言不能直接充作macOS进程组证据。当前命令是待复验入口，尚未执行，不能继承Windows PASS。
