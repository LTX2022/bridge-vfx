# H21同次慢窗口取证执行方案

状态：该审查已获批准并执行一次，范围封闭、不可复用。实际1启动／14.049615原生秒，5sample／11额外ps，5份有效对照栈；超时未复现。见[实际结果](H21_WINDOW_DIAGNOSTIC_RESULT_20261027.md)。下述为本次执行的固定合同，不授予后续运行。

## 冻结输入

- 候选：outputs/official-window-diagnostic-candidate-20261027-03
- 审查：[engineering-activation-review.json](../outputs/official-window-diagnostic-candidate-20261027-03/engineering-activation-review.json)，SHA `cd49249107404680d17d634a14647f4d094e8d304ac73303c3162f8e3bc4dac7`
- scope SHA `2c242dab6e3ac586b8bb8b799e56a3ac9729b5d34e371ac095557e1896a5fc96`
- bindings SHA `230119cfb975cdac308a0ec5c9ccd16175832042f4c6b4b483cafd801ba17e6a`
- 唯一执行目标：outputs/official-window-diagnostic-20261027-01
- 普通目标资格接收回执 SHA `b29dcbda5bd093ec1d0565023f112c1f9ec0cae615ccc1845491da545a12d7f2`

## 范围与预算

最多1次H21 hython身份采集，60秒总父墙钟，含辅助、清理、封存及最终冻结复核；512MiB；同时1重操作；零重试。原工具5秒／观察16秒／collection22秒不变，不调用HIP业务、保存、导出、渲染或Nuke。不得调用root或安装依赖。

启动后未ready时，在子Popen+2秒最多取一次基线；+8及+14秒只有当前阶段持续至少2秒才取，各点不补试。原观察最多4次自然vmmap在各自Popen+0.2秒触发，每次最多一个sample。总计最多7sample／15额外ps（每sample前后各1ps，加监督器身份ps1次）；原身份ps/lsof数量不增，不额外运行vmmap。

sample固定单次快照，单工具≤2.5秒；目标ps各≤0.35秒，原监督器身份ps≤5秒，均受父期限。串行互斥，至少保留3.3秒完整有效窗口。使用冻结ps/sample/vmmap及资格解析器，不延长工具期限。原调用正常完成可取消辅助；截止或清理不明不能伪装正常取消。取证真失败后不再启动其他辅助；原调用按原期限结束，保留真实结果。

## 验收与停止

1. 来源与时序：冻结输入无漂移；H21、监督器、工具的scope/ticket/nonce/argv、签名Popen和停止相互匹配。
2. 有效栈：固定命令和原始Analysis头PID一致，前后ps出生/父PID/映像一致，非空原生帧，采集完成且清理可信。
3. 同次慢窗口：完整采样位于原有效期限内且阶段一致；原阶段最终超时或对应vmmap明确PROCESS_IMAGE_TIMEOUT。正常调用的栈只接收为对照。
4. 期限与停止：原5／16／22秒不变，总60秒内完成清理和封存，所有原调用完成状态可追溯。失败、未复现、证据不完整或冻结漂移均结束单次范围，无自动续跑。

拿到栈后，才依据实际等待点做最小因果修复，再为真实复验及整链形成各自具体授权。既有DCC9启动／176.394983秒不变；本次合计上限10启动／236.394983原生记账秒，另受60秒父墙钟限制。最终交付仍按[完整计划](OFFICIAL_KARMA_COMPARISON_PLAN_20261026.md)验收实际HIP、NK、官方参考及主渲染和Nuke消费EXR。
