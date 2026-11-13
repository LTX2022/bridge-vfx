# 两处修复及新候选独立复核

结论：本轮限定代码与候选核对无剩余P1/P2；**完整软件集成仍未通过**，不能按整体软件完成接收。

独立审查者未参与对应实现，没有运行测试、监督进程或DCC，没有读取/复制私钥、令牌或intent/env内容。

- Alpha仅将husk format改为color4h，H21同版karmautils的color4默认精度及写入路径支持该修改；保留dataType=color4f、单C/beauty、RGBA门及数值容差。
- Supervisor的唯一生产修改是在Python启动参数中增加-B，两份运行库镜像一致；业务child命令、预算与停止事实不变。
- 底层alpha夹具从实际USDA解析格式、引用、产品、分辨率、路径及emission/opacity；旧float拒绝，合法color4h才生成half RGBA，不替代签名、操作或账本。
- 监督器回归去掉bytecode环境变量，以真实Python3.14监督普通子进程，认证started/stopped并比较文件全集及摘要。旧实现红，修后绿。
- 新07的158项快照与当前源码及本次软件尝试一致；相对05只有两项生产源文件不同，175项不可变记录存在，无pyc。07未授权、0票据，8/120/600/512MiB/heavy1/retry0预算保持，未来08目标不存在。
- 06保全记录为242/242文件不变，7个pyc及私有认证原件保留。
- 日志明确记录3.14核心24/24 PASS、3.11兼容2/2 PASS；唯一完整软件链1 FAIL/42.966s。Alpha与graph worker停止成功，H1因vmmap进程身份观测超时执行失败；4张票据均停止，无未知后代。158项软件快照无新增/缺失/变更，pyc为0。

PROCESS_IMAGE_TIMEOUT的具体根因未由本轮确认，不作为已经修复或已证实与两修改无关的问题。候选审计保留overall_software_acceptance=NOT_PASSED。本轮不修改身份模块、增加超时或重试整链。

最终报告由主控按上述证据整理；本复核范围为实现、测试断言、日志、范围与冻结事实，未据此宣布原生alpha、真实工程闭环、M1或视觉通过。
