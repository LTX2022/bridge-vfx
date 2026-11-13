# R05 五项整改独立复核：PASS_SCOPED

**最终接收更新：**integration-final-v2 与 formal-final-v2 已完成并核对当前源码；最终冻结结论及机器错误码、实际生命周期原件绑定见 [ERROR_CODE_CLOSURE.md](ERROR_CODE_CLOSURE.md) 和 [ERROR_CODE_SOURCE_BINDING.json](ERROR_CODE_SOURCE_BINDING.json)。下文“待最终日志”描述保留为此前阶段记录，不再代表当前接收状态。

原 R01–R05 五项发现已在下列源码上限定关闭。其后仅移动三项preflight进既有异常包装的addon改动已独立受影响复核，当前addon SHA更新如下。旧integration-final的97 methods通过、旧formal-final错误码断言失败均按旧SHA保留；新scoped97/正式final-v2由主集中执行，尚未在本结论登记通过。此结论不是全 16 域、安装或真实宿主验收；后续测试或生产变化需重新绑定。

本 reviewer 未参与生产整改，未修改生产、测试或夹具。只读审查当前实现及新增六项 guard 方法，重跑自有原五项秒级底层 API probe，再运行正常恢复与恢复授权补充 probe；所有写入限此 review 目录。没有重复正式进程测试，没有运行真实 Houdini、Nuke、模型、仿真、缓存或渲染。

## 源码绑定

| 文件 | SHA256 |
| --- | --- |
| package及controller的 native_rbd_controls_host.py | 8f263e25501804ef684a0a95a4fe568050513dcebfcd7130f329c62f9260a045 |
| package及controller的 native_rbd_controls_program.py | 39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a |
| plugins/houdini/_impl/houdini_bridge_addon.py | 5cda9e9d35d3609c7625efd89f54b9fb9e3b5f1c0c575cf8d774d79e991ada78 |
| tests/unit/test_rbd_review_guards.py | 702ffeb8d64a643e1ff809793e39a3e89d14e50b96af385e894c1619e55202e3 |
| tests/unit/test_rbd_addon_authority.py | 20507108acfe1011faca531046f798b90901f722bb7fa40a3e2502cf6e162d50 |
| tests/unit/test_rbd_authority_process.py | 4d8a5ff944effb824e7f1f4db5b019edb8099469346627e16924993d6a2f25db |

原五项probe的十项生产/测试摘要在closure-original-probes-v1.json前后相同，当时addon为31147b...；Host/Program及其镜像当前仍一致。当前addon只移动三项preflight进既有try，内存反向还原后字节SHA精确等于该31147b...，恢复/几何/锁等实现没有额外变化，故原五项无需重复探针；受影响错误包装另以新SHA做了实际检查。永久guard当前SHA与旧集中integration-final的before/after一致；review只读审其六个方法及主原始结果，不宣称本 reviewer 运行过该 unittest 文件。

## 五项关闭结果

| 发现 | 两版本原反例实际结果 | 实现审查与关闭范围 |
| --- | --- | --- |
| R01/P2 末端userData隐藏gate漂移 | 第三次BASIS_KEY读改exportlist，均拒绝RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED | Host._capture现在先取得node对象和userData，再读FPS/nodefacts/gates/wires；原末次userdata窗口已关闭，未增加capture轮数 |
| R02/P1 addon参数恢复早于权限检查 | 身份nonce变化均拒绝RBD_VELOCITY_AUTHORITY_REQUIRED，参数保留current-context-value | addon提前分支调用Host.restore_parameters，不再先generic恢复；同RLock内授权→实际restoreparm→再次授权→userdata恢复。原无权写入关闭 |
| R03/P2 Host恢复未查有效租约 | 底层lease明确报LEASE_LOST，两版拒绝，userdata未变 | prepare保存内部恢复binding/identity/node-session/parameter路径；_authorize_restore每次先查有效lease/task/identity/实际node/session/路径。直接Host.restore与实际addon入口均已补拒绝 |
| R04/P2 晚期solver输入隐藏configure几何变化 | 两版均拒绝RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED | 第三份几何后按solverinput→carrier→configure逆依赖重采，实际完整事实与早期事实比较，再检查当前state/frame/identity。不是计算期望几何；该原反例关闭 |
| R05/P2 第二处wire枚举无界 | 两版第2次native连接调用仅取得原连接+4条额外连接，共5条，立即拒绝；以前额外10004条 | Host.observations和_capture均用islice5，并对>4拒绝；collector自身256+1限制保留。关闭Python端迭代无界，不宣称native内部tuple分配也有界 |

五项原探针：10个双版本实际观察均满足对应拒绝/无越权写入/枚举限额。原脚本执行exit0只表示脚本完成，此次逐项检查观察值后才给上述限定关闭。

## 补充恢复检查

`closure-restore-probes-v1.json`：两版本各六项，合计12个实际观察、全部verified=true且原帧保持12，script exit0。

- 正常合法零幅write→实际addon恢复成功，snippet与userdata恢复初始状态，保留旧正常carrier流。
- 在恢复前lease失效、node-session变化、parameter路径变化、host nonce变化：均拒绝，参数与userdata均无写入。
- **material boundary：**实际setter内部、一次当前合法parameter恢复动作之后才发生身份变化：第二次授权拒绝剩余userdata恢复。已授权发生的parameter动作已发生，不宣称可被原子撤销，不称跨host完整atomic rollback；这不是R02原先“恢复前就无权还写入”的情况。

这12项补充使用实际addon的_restore_parm_snapshot及Host.restore_parameters/restore；仅补底层Parm.eval与已知合法启动任务身份，不替换高层权限验证或正常回执。fixed carrier原样返回任意固定底层几何，合法正向只有零振幅，不制造非零原生成功结果。

## 本轮命令与界限

```powershell
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/review/independent_refusal_probes.py
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/review/closure_restore_probes.py
```

原probe约1.35秒，补充约3.19秒。解释器Python3.11.9 / Windows10.0.26300。完整原输出分别归档 `closure-original-probes-v1.json` 与 `closure-restore-probes-v1.json`。当前原probe摘要已包含_root_for_path字符串兼容修正，两份Host镜像一致；其真实addon接口签名_root_for_path返回str，本审查没有恢复旧root.path实现。此前review-fix-smoke中的旧兼容错误仍是诊断，不作PASS。

只读核对新增永久test_rbd_review_guards.py：五项原反例均走实际Host/addon，明确观察拒绝码、native无写入/帧及限额，另有正常零幅恢复/同context重用。其主owned-v2及集中integration-final的实际结果见下节，review未替主重复运行。

## 三项preflight公共错误包装补充复核

`public-wrapper-review-v1.json`记录新addon及七个其他scope文件的before/afterSHA，完全相同，exit0。执行自有review_public_error_wrapper.py，未改生产/测试/夹具，没有正式OS进程重跑。

1. 只在内存把三项preflight从try内移回原位，得到旧addon完整字节SHA31147b4a7910a800cec77237d9814c5db89853f3f3eebfbad46fbeebc8f684c5，证明本addon变化仅为该包装范围。读取、派生、检查、写入顺序保留；preflight异常仍走现有getattr(exc,'code',...)，此时prepared未创建，释放空集合而非修改native。
2. 实际公共addon缺packed API单方法，两版本，exit0、0failure/error/skip，5.915秒；期待BridgeCommandError但具体RBD_PACKED_GEOMETRY_COLLECTION_FAILED保留，snippet/basis/program/manifest/frame均不改变。原始日志public-wrapper-unit-v1.log。
3. 两版本当前合法零幅登记后仅改变底层PID/nonce/session/generation，调用实际_fx_planned_domain_prepared：均得到BridgeCommandError/RBD_VELOCITY_AUTHORITY_REQUIRED，全部native参数/userData以及原帧不变。这个内存底层身份反例证明prepared入口结构化错误不再丢失，不冒充真实新PID/TCP生命周期。

结论：此小改动PASS_SCOPED；原五项关闭继续有效，material boundary说明原样保留。正式TCP/ownedworker完整结果待主freshfinal-v2日志，不以该局部方法和内存probe替代。

## 前一冻结版本的实际日志核对

- `outputs/rbd-host-20261013/authority/review-guards-owned-v2/result.json/raw.log`：6 methods、0failure/error/skip、exit0，raw unittest耗时1.001秒，源码前后相同。窄runner未将新增guard文件自身写入六项hash清单，因此不单靠这份结果声称其测试文件绑定完整；下面集中final补齐该SHA。
- `outputs/all-domain-20261009/rbd-authority-20261013-integration-final.json/log`：97 methods、0failure/error/skip、exit0、48.969秒（wrapper），源码前后完全相同，读取时全部after-source均与当前文件一致。包括永久6guard、旧RBDactivation实际owned channel/geometry/rollback正常链、Host/collector以及镜像一致性测试。原始日志结尾Ran97/OK已核对，未重新运行。
- `outputs/all-domain-20261009/rbd-authority-20261013-formal-final.json/log`：1 method、两版本2failure、0error/skip、exit1、81.250秒（wrapper），源码前后相同。两版都在test第136行的新PID调用拒绝码断言失败：公共码COMMAND_FAILED，预期RBD_VELOCITY_AUTHORITY_REQUIRED。该with assertRaises前的trial/zero/非零拒绝与回滚/save/verified stop字段/newPID/nonce/参数重开断言已经越过，但错误码失败后无“拒绝后参数未变”断言或完整lifecycle发布证据，故不将整条正式链判PASS。尚未由该原始日志证明COMMAND_FAILED内层细节，不能仅凭generic拒绝猜内部正确。

上述只是只读核对当时已完成日志；主若提供后续正式summary，将另行核对当前SHA与原始证据再更新正式结论。保留formal-final失败原件，不用97项或五项probe掩盖该失败。此问题不复活R01–R05已用原反例关闭的具体缺陷，也不表示freshPID正向R05checkpoint实现完成。

正式test现在检查stop_hosts实际receipt.confirmed_exit/heavy_slot_released，再使用OwnedProcessHandle.receipt()读取经read_receipt校验的停止事实，核对pid/child_wait_observed/job_active_processes=0。读取实现确认receipt()确实验证签名、started SHA、identity、process birth、Job及Windows停止字段，而非仅读JSON。此为静态审查，不替代主提供实际generatedserver/TCP/ownedOSworker最终日志。

public userData与pendingplan仍不能授予进程内authority；freshPID无verified R05 checkpoint仍必须拒绝。普通保存参数重开不等于R05恢复正向完成。逆序双采样能关闭已复现原问题，但不宣称跨node原子快照、不覆盖任意晚期API副作用、也不证明真实VEX/Bullet仿真消费。nativeDataID静态文档建议仅作辅助，当前实现没有用constant/默认ID绕过实际内容复查。

截至此轮已确认五项中无剩余阻断；当前production/newguardSHA已绑定，公共preflight包装也已限定通过。旧97项通过与formal-final失败均保留其旧SHA，当前freshscoped97/formal-final-v2待实际原日志补充。后续生产/夹具变化需对应受影响复核。正式生命周期最终接收、新PID正向R05checkpoint、实际native效果及全域验收继续分别记录，不以旧整组或局部probe作为全批PASS。
