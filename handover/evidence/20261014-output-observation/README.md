# 2026-10-14 输出逐帧配置与观察预算证据

本目录保存125份原件，原始3,933,971字节。超过8KiB的非Markdown原件无损gzip；[index.json](index.json) 保存原始/归档路径、字节数和双方SHA-256。旧移交包和以前批次证据未覆盖，没有复制运行签名密钥或安装凭据。

- [最终定向报告](raw/outputs/all-domain-20261009/output-observation-unit-final-20261014.json.gz) 与 [原始日志](raw/outputs/all-domain-20261009/output-observation-unit-final-20261014.log.gz)：项目Python3.11，127方法、135.610秒、退出0，无失败/错误/跳过。
- [最终正式报告](raw/outputs/all-domain-20261009/output-observation-formal-final-20261014.json.gz) 与 [原始日志](raw/outputs/all-domain-20261009/output-observation-formal-final-20261014.log)：2方法、80.266秒、退出0。一个方法覆盖两版预执行与帧后拒绝，另一个为H21正常控制端恢复/登记阻断。
- [最终独立结论](raw/outputs/output-observation-20261014/review/FINAL_CLOSURE.md) 与 [独立绑定](raw/outputs/output-observation-20261014/review/FINAL_BINDING.json.gz)：本批软件限定范围接收，pending为空；time和budget各自独立审查原件一并保存。
- [源码绑定](source-binding.json)：两份最终报告的445份当前Python源码完全一致，额外底层边界/生成工具摘要分别记录。四个生成快照映射中，`output-time-1791963608995805300` 是修复前失败基线，不能作为当前通过；另外三个当前快照各137份Python源码与根源码一致。运行bytecode不计源码。
- [当前正式失败基线](raw/outputs/all-domain-20261009/output-time-formal-baseline-20261014.json.gz)：1方法、27.218秒、退出1、源码未变，保留未拒绝非法目标帧的事实。agent夹具错误、变更期间阶段失败、Python3.12预算诊断及整改原件分别保存，未升级为项目环境验收。
- [完整说明](../../OUTPUT_OBSERVATION_20261014.md) 与 [原生静态调查](raw/outputs/output-observation-20261014/discovery/NATIVE_OBSERVATION.md)。

raw下保留三个当前正式目录的结果、实际API调用、控制端日志、监督器开始/停止和签名终态原件；生成源码保存摘要，不复制运行配置或签名密钥。异常后0frames_done/0输出事实、正常恢复后登记仍BLOCKED均是实际测试的预期结果。

单次颜色观察2MiB/32768工作预算不保证原生API对象/耗时、整个USD或全帧操作记录的峰值资源。实际writer/backend、AOV/OCIO/filter执行、alpha关联、其他原生效果与控制、Nuke、48+2/54、最终全量/安装、全16域M1、真实宿主/模型/视觉/生产验收未完成；macOS待目标机器验证。
