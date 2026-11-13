# G03 冻结输入批原件与源码绑定

[修复报告](../../GEOMETRY_INPUT_20261013.md)说明本批改动及剩余缺口。[index.json](index.json)包含111个原件、11,789,712原始字节的来源、大小及原始/归档SHA；`.gz` 为原字节无损压缩。[source-binding.json](source-binding.json)记录25个相关源码摘要、实际命令/退出码和最终两版各134文件的生成清单，均与当前源码一致。

- [最终95项摘要](tests/geometry-input-20261013-final-core-v2.json)、[原日志](tests/geometry-input-20261013-final-core-v2.log)：0失败/错误/跳过，退出0，源码前后不变。
- [最终两版正式摘要](tests/geometry-input-20261013-formal-final.json)、[原日志](tests/geometry-input-20261013-formal-final.log)：实际生成server、Python/TCP、监督器/Job、40KB作业文件、初始化、保存/重开与确认停止；同请求不再开启新的场景转换或worker。
- [独立限定结论](review/CLOSURE.md)及 [最终实际源码/日志核对](review/fixed-evidence-audit-final.json)：Windows长argv的P2关闭；身份hook和重试边界没有新具体阻断。独立handoff/epoch反例四方法退出0，其他边界原件与早期失败记录保留。
- `formal-final/21.0.631/`、`formal-final/22.0.429/`：实际trial/stop/rest输入、生成清单，以及筛选后的inputs/job文件、journal、软件HIP、native-operations和启动/停止原回执。
- `service/`、`generator/`、`tests/`、`review/`：实际命令、源码前后、原日志及必要复現脚本。worker早期夹具不足、真实缺输入、run manifest漂移、监督器身份不足、重复开场景与core-v1模块名称错误仍是FAIL；没有改写为PASS或累加为全域数量。

归档排除签名密钥、supervisor完整环境、凭据与个人agent会话。签名回执由实际运行时验证，归档不携带密钥，不能声称独立离线验签；SHA只检查原件字节一致。临时绝对路径用于审计定位，不是产品运行依赖。

G03仍只有认证rest输入及参数初始化证据，实际变形、跨帧/下游、新PID登记权威均未闭合。全16域、48+2/54、安装、macOS、真实DCC/模型、视觉和生产验收不能由本目录证明完成。
