# R05 独立只读复核：CHANGES_REQUIRED

结论绑定 v6 复核时的 Host `76c2b500e045955f457c9b502adef8df715133f36ace46aee52290191d723a3f`（package/controller 相同）、Program `39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`（镜像相同）、addon `ba6c275e6c4ce85a8098099d3fddc0030433c556d5940979f0db0d9a09c3d3c3`。指定六个测试/夹具及三类生产模块的完整十项摘要见 `independent-refusal-probes-v6.json`；采集前后相同。主仍在修复正式测试，后续变化不自动沿用本结论。

本 reviewer 未参与实现，未修改生产、测试或夹具，所有写入限本 review 目录。只运行秒级内存底层 API probe，未重复正式/大测试、未启动真实 DCC、模型、仿真、缓存或渲染。不是全 16 域验收。

## 尚未关闭的确定发现

| 项目 | 优先级 | 当前实际结果 | 修改位置与要求 |
| --- | --- | --- | --- |
| R02 参数回滚发生在权限验证之前 | P1 | 两版实际 addon helper 最终报 RBD_VELOCITY_AUTHORITY_REQUIRED，但 snippet 已从 current-context-value 写成空串 | addon:3878/3880；R05 Host 必须先验证 snapshot 的当前身份、node session、root/task/lease，再在同一序列化边界内恢复参数和 userData；无权时不得写任何字段 |
| R01 最后 userData 读隐藏 gate 漂移 | P2 | 两版 observations 成功，返回 exportlist=v，实际已经是 w | Host:78/224；末次 userData 在参数之后读取的窗口仍在，FPS 顺序修复不能替代此反例；拒绝漂移而不是发布陈旧 observation |
| R04 最后 solver 几何读隐藏 source 漂移 | P2 | 两版合法零幅 readback 成功，返回 temperature=20，当前 configure 已为42 | Host:184/223/224；末端只重查身份/frame/参数/wire，不重查原始几何。需实际当前 source/consumer 稳定性验证，不能用三份旧采样互相相等替代 |
| R05 observations 第二处 wire 枚举无界 | P2 | 两版最终虽拒绝，但先耗尽10000条额外连接，再在后续 bounded capture 中额外读4条；合计10004 | Host:203；每次 inputConnections 消费都需有界，不应只在前后 _capture 有界。Native API 自行分配 tuple 的内存限制另报，不把 Python iterator 有界当作 native 内存证明 |

R03：直接合法 Host.restore 在 lease 查询已明确拒绝时仍删除登记，两版复现（Host:241）。正式外层 root fence 可排除另一个合规 executor 在持锁期间接管，因此没有把直接 probe 当作“正式跨进程接管已复现”。但长事务租约到期/同进程状态变化后的恢复仍未在 Host 内验证。列为与 R02 一起收口的 P2 防御缺口，正式入口无写入反例尚待实现者补齐。

最小命令：`.venv/Scripts/python.exe -B outputs/rbd-host-20261013/review/independent_refusal_probes.py`。v5及测试调整后的v6对每版执行五项观察，约一秒，进程 exit0仅表示 probe 完成。R01/R04/R03未拒绝；R02拒绝后仍有写入；R05超限枚举后才拒绝，所以绝非PASS。固定几何不按期望结果计算成功速度；合法正向仅零幅。

## 当前实际测试结果

- `outputs/all-domain-20261009/rbd-authority-20261013-integration-v3.json/log`：90 methods，0 failure/error/skip、exit0，36.719秒，source unchanged，读取时全部 after-source 相符。保留实际已有固定任务身份后，两项 addon底层fixture恢复；旧Flip/RBD六项合同明确选取，不包括不可用macOS vendor原件检查。通过当前这些方法仍未覆盖本review四项新反例，不能替代缺陷整改。
- `outputs/all-domain-20261009/rbd-authority-20261013-formal-v5.json/log`：1 method，两版2 error、exit1，69.281秒，source unchanged，读取时全部 after-source 相符。实际trial、零幅apply、非零拒绝+原参数回滚、task_save已越过；在 test第113行读取stopped['houdini']['stop_fact']时KeyError，尚未执行新PID/nonce重开与无checkpoint拒绝。这里只分类实际错误，不猜停止回执中缺失事实，也不宣布生命周期通过。
- integration-v2：91 methods，0 failure、2 error、1 NOT_RUN skip、exit1，36.344秒，source unchanged。两个 error 来自旧底层 SimpleNamespace 没有 hipFileEventType，新 hook 尝试真实 producer callback；后续测试在已有explicitfixtureidentity设置实际任务启动字段，没有放松生产授权。vendor archive skip 引用不可用 macOS 原件，不作 PASS。
- formal-v4：1 method，两版2 failure、exit1，67.390秒，source unchanged。实际trial/零幅apply已越过，非零实际拒绝，但公共码CANDIDATE_APPLY_FAILED与测试预期内部码不符。后续仅测试新增outer code+inner detail+rollback断言；生产门槛未变。原失败保留，不作PASS。
- integration-v1 的84方法 exit0属于旧 Host/addon SHA，保留诊断，不替代当前。formal-v1/v2 的 trial证据失败、formal-v3 的classgate拒绝均为失败原记录。
- collector `collector/bounds-20261013-v1/final.json/log`：33方法 exit0，无skip。两份 Program 与collector测试目前各自仍是该记录的同一SHA，窄范围结果仍有效；不受Host/identity hook变化扩展为整个本批通过。
- authority final-owned 的25方法来源 Host/addon旧SHA，仅历史窄范围结果；当前integration-v3实际90项有限软件方法通过，但正式v5仍失败；本review不重复主已集中执行的大组。

## 已审内容和限制

私有 authority records 从实际 Host 捕获签发，绑定完整当前 host identity、task/root、实际节点及 sessionId；public userData 与 pending plan 不能单独授予该权限；读取公共 basis 不会恢复新进程 authority。process-sealed plan 检查仍保留，旧的同context载体初始化、已有activation/非R05观察路线未删除。无 verified R05 checkpoint 的新PID必须拒绝，当前 process test 的意图正确，但完整正式流程还没有通过。

新 `_fx_owned_domain_host_identity(task_id)` 私有 hook 复用现有 `_fx_geometry_host_identity`；没有从 userData 或请求 metadata 签发身份。graph-worker 路线调用实际 `_fx_producer_identity`，会检查 scene callback、supervisor started receipt、当前pid、Windowsprocess birth和launch/operation/attempt绑定；R05 root/lease 检查仍保留。此通路的两处底层夹具错误需要修正，但本审查不建议恢复 advisory/fallback来掩盖正式初始化失败。Hook 未关闭表中晚期窗口和回滚顺序问题。

Collector 枚举、属性类型/tuple/storage、点索引、packed→embedded polygon深度/cycle、变换/pivot/实际拓扑、finite标量、完整JSON+digest 2MiB，以及采样帧异常恢复均已读审。其旧GEOMETRY_SCHEMA保持，33项当前采集测试有效。point/primitive属性已采集并比较；不能据此宣称未采集的vertex/detail属性、其他prim intrinsics也已保持。Native API 自行分配返回容器、同步native调用内存/时间不是该Python budget的证明。Host允许额外4096字节登记 envelope，但只在后续_capture检验存储字符串，不应声称写前已验证最终完整basis大小；当前review未另行构造此边界反例，因此不追加未经复现的缺陷等级。

旧test_native_rbd_controls_program有按snippet语法模拟v写入的底层载体，属于软件历史合同验证，不是实际VEX编译/原生非零效果；新authority/formal固定底层几何零幅成功、非零拒绝才是本批声明边界。没有真实Bullet消费、真实仿真、verified R05 fresh-PID恢复、macOS、最终安装或全域接收结论。

初版review材料及v2/v3/v4探针保留审计。v3刚好使用新增hook、尚未补自身fixture可信任务启动身份，因此R02出现AttributeError，未当作权限关闭；v4/v5补review内存中的已知合法启动上下文后，实际R02权限码和已写参数反例仍成立。任何生产/测试变化都需对受影响发现重跑最小probe并重新绑定SHA，不自动沿用此结论。
