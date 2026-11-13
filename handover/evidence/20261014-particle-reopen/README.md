# 2026-10-14 P01 可信恢复证据

本目录保存本批 1,537 份原件、原始 69,414,120 字节。超过 8 KiB 的非 Markdown 文件采用无损 gzip；[index.json](index.json) 记录原始与归档路径、字节数、双方 SHA-256 和压缩标记。当前 [源码绑定](source-binding.json) 为 443 份 Python 文件及额外底层 schema 边界文件；历史失败和阶段结果分别保留，不冒充当前全仓库通过。

最终当前结果：61 个定向方法、4 个正式方法（覆盖 P01、RBD、G03、材质、灯光、Crowd 两版）；两组退出 0、失败/错误/跳过 0、前后及当前源码一致。新初次 task-reopen 协议只对显式 P01 基准启用，其他五域是原验证路径的兼容回归。

- [当前定向报告](raw/outputs/all-domain-20261009/p01-routing-final-20261014.json.gz) 与 [日志](raw/outputs/all-domain-20261009/p01-routing-final-20261014.log.gz)。
- [当前正式报告](raw/outputs/all-domain-20261009/p01-routing-formal-final-20261014.json.gz) 与 [日志](raw/outputs/all-domain-20261009/p01-routing-formal-final-20261014.log)。
- [独立结论](raw/outputs/particle-reopen-20261014/review/CLOSURE_FINAL.md)：R01–R08 CLOSED_SCOPED；[原始绑定](raw/outputs/particle-reopen-20261014/review/FINAL_EVIDENCE_REVIEW_02.json.gz) 为当前 443 份源码、两份最终报告，`pending=[]`。
- [完整本批说明](../../PARTICLE_REOPEN_20261014.md) 与 [P03 下一批只读准备](raw/outputs/particle-reopen-20261014/next-batch/P03_NEXT.md)。

raw 下保留正式生命周期、实际 node/parameter API 调用、生成源码/底层边界 SHA、任务保存与监督器停止事实、诊断失败及阶段审查。运行签名密钥未复制，旧运行签名不作为新运行权威；复验应使用新的运行目录和密钥。

P01 读回仍为 BLOCKED/native_parameter_expression_only。实际 POP 子步/积分/数量、G03/RBD 非零原生效果、P03 独立物理半径、其余控制、公共 writer/filter/alpha、Nuke、48+2/54、最终全量/安装、全 16 域与真实阶段未接收。macOS 待目标机器验证。
