# 进程身份采集修复与08候选

本轮最小修复、必要验证与双独立验收已通过，新候选为 **08，未授权、0启动**。当前正式八阶段软件链通过；真实Houdini/Nuke工程闭环、原生alpha修后结果、视觉及M1仍未通过。本轮没有启动真实宿主。

## 当前实现

旧采集为取得身份头和主映像映射，执行全地址空间vmmap报告。现在固定执行公开 `sample PID 1 1000 -file /dev/stdout` 取得PID、父PID、原主Load Address、出生时间及目标类型，再按该Load Address定点vmmap验证实际唯一r-x __TEXT完整路径。

同PID正常及搬移对照中，新旧五项身份头完全一致；搬移后仍采到旧Load，其位置没有TEXT时继续拒绝。没有采用调用方地址、首个RX映射、进程自报地址或私有API。sample仅接受固定成功命令、同PID精确三行已观察进度stderr；其他诊断继续失败关闭。

文件vnode/stat/hash、ps夹检、前后双次采集及祖先链均保留，5秒工具/16秒观察/60秒祖先时限不变。生产修改限定process_image及其controller镜像，约25行增加/6行删除；既有核心测试按新底层采集适配并补必要拒绝覆盖。相对07冻结的158份生产源码，只有process_image.py变化；alpha color4h和监督器-B修复保留。

## 验证结果

| 验证 | 结果 | 原件 |
|---|---|---|
| 原生工具有限同PID对照 | 正常五头一致、搬移继续拒绝 | [依据](evidence/20261023-vmmap-repair/basis/REPORT.md) |
| Python3.14身份核心 | 28/28 PASS，22.775秒 | [日志](evidence/20261023-vmmap-repair/implementation/green314.log) |
| Python3.11同组兼容 | 28/28 PASS，22.658秒 | [日志](evidence/20261023-vmmap-repair/implementation/green311.log) |
| 正式八阶段软件链 | 唯一一次1/1 PASS，78.054秒 | [日志](evidence/20261023-vmmap-repair/integration/full-chain.log) |
| 账本与停止审计 | 8票据、7组认证停止exit0、两项实际登记依赖 | [审计](evidence/20261023-vmmap-repair/integration/software-integration-audit.json) |
| 双独立验收 | 代码增量GO、最终候选与结果GO | [结论](evidence/20261023-vmmap-repair/independent-acceptance.md) |
| 候选冻结与默认预检 | PREPARED_NOT_AUTHORIZED / PREPARED | [审计](evidence/20261023-vmmap-repair/integration/candidate-final-audit.json) |

两版28项是兼容重复验证，不累计为56种独有覆盖。真实普通Python父子证明、伪argv和错误映像拒绝已执行。整链使用正式生成器/装配/状态机/worker/账本及显式底层原生API替身，真实OS进程/TCP边界；Houdini登记产物被Nuke实际软件输入消费，输出验证来源仍是software_test，native NOT_RUN、人工检查PENDING。

整链会计累计84.026秒（含父子计费），审计时磁盘约53MiB，重型作业不重叠；8次/120秒单项/600秒累计/512MiB/单重作业/零重试预算未扩大。158快照与通过的软件源码一致，175不可变文件核验，无pyc污染。

红日志仅证明旧全量调用未满足定点采集回归，不冒充重新捕获超时。旧随机超时在工具内部的具体停留位置仍未定位；新方案消除了全量VM使用统计的依赖，不保证OS工具永不超时，所有截止和拒绝继续生效。没有重复全量无关回归。

## 冻结候选

目录：`outputs/engineering-closure-20261023-h21-08`。

| 文件 | SHA-256 |
|---|---|
| scope.json | `15382469a659e7c3b98c95465807391f6794498d6e0a39528419406a492355c8` |
| runtime-bindings.json | `780cb08c14dbbfcc54ed65357c97c762f0d6dd45726858768eb0dff618fb5f66` |
| engineering-activation-review.json | `632071352695beeebab6c70a2f027fdddd41cf2cd42e701a1bf132a6e81aed4a` |

08由未使用07经正式prepare-successor创建独立范围和密钥；未复制私有凭据到公开交付证据。execution_authorized=false、0票据，无software_native_boundaries配置。review仅绑定未来 `outputs/engineering-closure-20261023-h21-09-authorized`；该目录未创建，未执行激活。候选evidence_source=real_host只是未来路线配置，不是实际执行事实。

-06全部242文件、-07全部183文件与本轮基线集合/摘要完全相同，包含原失败EXR、USDA、认证原件和pyc；不覆盖或清理。没有修改Desktop主工程，未重建安装包、提交或推送Git。此前诊断和失败报告保留原轮边界。

六角色按已批准分工完成：方向负责人确定可实施方案；依据、实现和集成三位执行者拥有互不冲突范围；代码与证据两位验收者独立只读，发现问题在本任务内处理。主控接收本轮软件修复和未授权候选；当前不进入真实验收。
