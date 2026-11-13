# 共用链修复与剩余阻断（2026-10-09，2026-10-10补齐记录）

当前共同输出增量见 [2026-10-13输出采集修复](OUTPUT_PREFLIGHT_20261013.md)：父OCIO观察已进正式producer，配置/LUT字节、帧后context和17-AOV预算两项P2关闭。实际husk/writer/filter/alpha仍缺；下文Crowd count及旧顺序是原阶段记录，不能再作为当前尚未修复项。

2026-10-13后续增量见 [批量修复报告](BATCH_REPAIR_20261013.md)：下文 Crowd count 创建顺序阻断已有后续修复与两版有限正式通过；G03 增加宿主组件但未完成正式接线，共同原生输出事实仍缺。下文保留原阶段证据，不作为当前所有缺口的清单。

**全16域 M1 尚未完成。** 本批关闭共用代码缺陷和证据适配，不表示48+2、安装、真实宿主、模型、视觉或生产接收。保留 a3e7734 后已有改动，2026-10-10按用户指令提交和推送，见 [提交说明](COMMIT_REPORT_20261010.md) 与 [Git内证据](evidence/20261010/README.md)。真实 DCC、仿真、缓存及渲染未执行。

## 已修改

| 内容 | 实现与边界 |
|---|---|
| 正式输出登记 | 去掉 consumer 硬编码颜色/alpha，要求 producer AVAILABLE 的逐帧 metadata；严格帧、编码和bool检查，缺事实在登记前阻断。Nuke消费同一实际编码。 |
| 登记重试 | 对真实 SQLite BUSY/LOCKED最多两次，同操作/请求/产物，仅补登记；非锁错误不重试，不重建或重渲染。保留原OSError重试上限。 |
| USD采集 | 补RenderProduct source/output colorspace，逐帧独立采AOV，按两版原schema验证string；filter只保留raw观察，不宣称执行效果。 |
| 当前SAVE适配 | 核验typed producer原件、canonical路径/字节、当前图/依赖/冻结来源、HIP/snapshot；新增current_task_save部分证明，summary-only/stale拒绝。 |
| Windows快照拒读 | 2026-10-10复验暴露render操作快照瞬时拒读。真实Win32分享拒读证明Path.read_text给errno13且无winerror；只对Windows分享/访问拒读等待最多0.5秒，永久拒读继续抛错。JSON损坏、丢文件、非分享错误不重试，不改ACL、不重做render。 |
| 恢复测试边界 | POSIX descendant经实际监督器，观察直接child wait；仍由生产组状态决定容量。Windows受影响八项通过；macOS/POSIX目标机NOT_RUN。 |
| Crowd stash | 仅本宿主/attempt实际创建并有持久原件的stash可在primitive阶段保留unavailable。空/坏recipe、旧节点/driver、非null Data拒绝；不可读Data不证明重放一致，最终save/manifest/reopen仍严格。 |
| G03载体 | 新增独立pure plan/collector，约束批准的静止空间公式、初始化所有权和basis。尚未接正式graphcarrier/addon，不计完整writer或生命周期通过。 |

采用GPT-6.1-sol high子agent分文件实施，正式进程集中调度；复核者未参与对应实现。controller-entry副本已通过现有同步工具更新；没有生成新安装包。调试材料保留outputs，不混入安装内容。

## 实际证据

- **共用链集中定向：127方法，0失败/错误/跳过，退出0，67.735秒，捕获源码前后相同。** 日志和命令：`outputs/all-domain-20261009/common-current-integration.log/json`；覆盖stash、正式编码/登记、USD/输出回执、SAVE原件和G03。此后client快照读取有新增修复，127结果不当作新增client的完整回归。
- Windows八项恢复原组：16.992秒退出0；详见 `outputs/common-closure-20261009/process/process-recovery-report.md`。旧29方法结果不改称当前30方法全模块通过。
- SAVE适配原组60方法：59通过、一项既有缺材料跳过，退出0；见 `save-adapter/README.md`。跳过不计PASS；相关当前适配方法包含在上述127项中。
- stash最新13方法通过，17.766秒；G03 pure component13方法通过。这些均包含在127项中，不累计重复方法。
- 正式lighting恢复单项：22.531秒通过，使用实际受控worker中断/监督停止/控制端恢复，不重建已完成图，消费当前保存HIP；输出因三类原生事实缺失在登记前BLOCKED。原日志 `common-formal-recovery-current`；随后只读查询白名单有增量，最终源码恢复组另行记录。
- 当时实际恢复case适配55条部分原件证明，含current_task_save，没有无条件SAVE缺口；完整输出/登记、语义、preview、领域恢复与Nuke仍缺。`common-current-save-and-recovery.json`仅绑定当时源码。
- 2026-10-10最终源码恢复组 `common-final-source-recovery`：10方法、9通过、1失败，退出1。失败是formal c轮询快照PermissionError，原失败保留。受影响修复后 `common-snapshot-sharing-native`：21方法全部通过、无跳过，4.531秒，包括真实分享拒读释放/持续拒读上限和既有输出不可变/绑定拒绝。不是用重复运行掩盖失败。
- 修复后同源码正式恢复 `common-snapshot-formal-final`：单项通过、无跳过，17.125秒，捕获源码前后相同。新 `common-snapshot-final-inventory.json` 再次识别实际current_task_save，完整登记/输出及其他阶段缺口仍在，不记全域通过。controller副本同步及git diff --check均通过。
- 正式Crowd正常两版 `after-fresh-queries` 仍FAIL：六COMPLETE、一UNKNOWN，当前缺dopimportfield.fields的底层multiparm count。保留SUCCEEDED断言；[原件调查](evidence/20261010/closure/domain-worker/FIELDS_DEFAULT.md)不猜默认。
- [独立复核](evidence/20261010/closure/review/COMMON.md)在指定范围无未闭合确定P1/P2；空recipe和缺fresh来源两项P2已关闭。结论限primitive安全、登记/采集/SAVE指定范围，不授Crowd完整接收或全域PASS。
- [Windows快照修复独立复核](evidence/20261010/closure/review/RENDER_SNAPSHOT.md)核对最终client分类、21项受影响日志及formal c通过，限定范围无确定P1/P2；只关闭快照读取故障，不将持续拒读、未运行或全域结果提升为通过。

标准1579方法诊断失败、当时源码变化，保留原日志，不能作最终接收。没有再次运行标准全量；已知阻断未关闭，重复全量不会补齐事实。

## 剩余工作与顺序

1. Crowd：补合法multiparm factory/current count采集或新建初始化顺序，复验两版同一正常正式入口；不把父Folder跳过或缺值填0。
2. 共用输出producer：补有效OCIO config/LUT/context/file rules、实际output/AOV/filter顺序与覆盖、Karma/husk beauty alpha关联。raw USD、静态schema、文件存在不足以生成完成metadata。
3. 控制：已批准20项与B组合不再询问；G03/R05等载体补host认证、事务、实际上下游和新PID直接读回，再解除对应writer。其余逐项补合法接口、basis、实现和生命周期。
4. 48+2：每域三个正式案例及两组合；primitive/current_task_save不能替代full_semantic、preview、registered output、domain recovery和Nuke composite。
5. 冻结交付：确定缺口关闭后，一次最终标准软件回归、全域独立复核和安装生命周期；macOS待目标机同源码复验。真实宿主、模型、视觉和生产分别验收，当前NOT_RUN。

进度慢的主要原因是代码缺陷、未实现功能、未观测原生事实此前混在同一链路，前一处通过后才显露后面的独立缺口。以上按依赖区分，避免重复修改已闭合代码。当前授权仅软件替身；需要真实阶段补事实时仍须具体授权。不得复用旧签名密钥或覆盖冻结失败日志。
