# 2026-10-13输出采集修复证据

[本批修复与剩余内容](../../OUTPUT_PREFLIGHT_20261013.md)是当前结论。这里保留47件精选原始材料，共1,076,884字节；[index.json](index.json)记录每件来源、字节数及SHA-256。原日志不改写，三个较大的正式结果使用无损gzip，索引保留压缩前后摘要，已验证解压字节与原件相同。不携带运行签名私钥、凭据、完整临时目录或安装内容。

[source-binding.json](source-binding.json)绑定本批9个 Python 文件及实际生成的三个快照，每个132文件、0不匹配。只证明所列范围；旧 Crowd 和先前证据保持原字节，不因本批变更重新签发或算作完整当前验收。

- [正式恢复 b 基线](tests/output-followup-20261013-formal-baseline.log)：登记缺事实失败，完整成功断言保留。
- [中心组原日志](tests/output-followup-20261013-components-final.log)：110个实际方法通过，另1个错误模块名导入失败，整体命令仍退出1。
- [正确副本模块与原正式 c](tests/output-followup-20261013-formal-and-sync.log)：4方法通过，属于两项P2整改之前的阶段。
- [整改后中心日志](tests/output-followup-20261013-review-fixes.log)：材质/灯光14方法与正式 c 通过；新漂移方法因启动夹具缺导入失败，整体命令仍退出1。
- [漂移第二次失败](tests/output-followup-20261013-context-drift-final.log)：保存前缺正式 adoption，被生产校验拒绝，未进入帧执行。
- [漂移最终正式日志](tests/output-followup-20261013-context-drift-adopted.log)及[命令／版本／源码前后](tests/output-followup-20261013-context-drift-adopted.json)：1方法覆盖两版本、53.375秒、退出0；每版帧API执行一次后context改变，实际runner拒绝完成。
- `formal/recovery/`：整改后正常恢复 c 的原始partial-case.json.gz、native audit/render调用与实际生成清单。恢复/保存/重开成立，原生输出登记仍BLOCKED。
- `formal/context-drift-21.0.631/`、`formal/context-drift-22.0.429/`：两版原始拒绝终态、native调用和生成清单。FAILED是预期安全拒绝，不是渲染语义通过。
- [采集器原生接口与26项验证](ocio/REPORT.md)、[10项实际文件／签名producer反例](binding-tests/REPORT.md)：底层API软件边界；无默认颜色或alpha。
- [独立发现](review/REPORT.md)、[原失败反例](review/counterexamples.log)、[限定整改复核](review/CLOSURE.md)、[最终独立反例](review/closure_counterexamples_final.log)：两项P2关闭，不授全域或真实输出接收。

原报告为保持证据字节使用原相对链接，迁入本目录后部分原链接不适用；查来源使用index，查归档使用本README。运行临时路径只描述当时来源，不能假设未来仍存在或用历史身份／密钥重签。没有标准软件全量、安装、macOS目标机、真实Houdini/Nuke、HY3/模型、视觉或生产验收。
