# ready13 最终验收清单

**范围结论：是。** 本轮仅收口“原生启动就绪与身份采集同步”和“就绪／身份采集失败立即停止自有作业”两项软件修复；完成条件限于以下必要证据。

- [ ] 受影响核心与 controller 镜像检查通过：ready 事件绑定本次目录、HMAC、nonce、实际 PID 和 argv；ready 等待与原完整身份观察共用既有期限；失败立即进入既有 owned stop；原始原因、诊断和 started→stopped 认证链保留。保留既有独有故障及正常路径覆盖。
- [ ] 改后的正式 ready 路径完成有限 ordinary Python 真实 OS 验证：同 PID 发布 ready 后才执行原严格采集，认证完整 binding 与整组停止；负例证明错误不继续作业。明确其为普通进程／软件协议证据，不冒充 DCC。
- [ ] 一次无 image-model 的既有八阶段软件链完成，并准确标明 Houdini／Nuke API 软件替身；无重试求绿，不用 sample／vmmap 模型替代 OS 身份事实。
- [ ] 独立代码审查与独立证据审查均达到本次修复范围的 GO，未解决的实质问题明确阻断，不能用测试数量替代证据。
- [ ] 13 新候选按原正式准备链重新冻结，源码、镜像、hook、精确 argv、部署、snapshot、source_freeze／immutable 一致，预检 PREPARED 且无 blocker；尚未授权执行，无真实启动／票据消耗。
- [ ] 原 06–12 原件保留；12 维持失败封闭。8 次／120 秒／600 秒／512 MiB／1 heavy／0 retry，以及 tool 5／freeze 5／observe 16／capture 60／collection 22 秒均未增加。

上述证据全部成立，可报告“本轮两项软件修复完成，13 PREPARED_NOT_AUTHORIZED”。不扩展到 M1、全量工程验收或三类 Skill；它们不是本轮软件修复完成条件。

真实 H21 prerender hook 的实际同 PID、脚本生命周期与阻塞／继续行为、真实耗时及 H21／Nuke 工程闭环仍为 PENDING，必须另获对应新范围授权后实测。普通 Python、软件八阶段、双审和 PREPARED 均不能替代这层验收。
