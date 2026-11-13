# 本轮独立复核

审查者：未参与实现的 Bugbot；范围为本轮 driver、准备器、alpha 接线、NK 首次保存和补登记边界，源码见 source-sha256.json。未启动真实宿主。

## 已整改

- 慢建图终态后，同 graph/request 再读正式 graph_trial，完成宿主交接。
- Nuke 原始事实使用正式 control/host-runtime-state/nuke_renders。
- journal 在互斥锁内重读，避免锁前陈旧状态重复执行。
- 可信完成后的账本故障保留补登记状态；没有完整受控验证事实的错误不冒充账本故障。
- Nuke complete_recovered 在生产客户端及原生服务两层检查持久操作所有者，保留 token/HMAC。
- NK 先消费登记产物，经正式 render_binding 配置并读回后保存；重试重验原始保存回执。

## 未关闭 P2

production_hosts._launch_h 将 session_seconds 作为宿主总寿命。合法建图预算可能消耗剩余宿主寿命；graph_trial 终态后的 host handoff 继续使用原连接，宿主已停止则无法完成交接。正式入口日志 formal-entry-final.log 已复现连接拒绝，不能接收工程闭环。该临时用例无保留的原始 signed stop，不将具体 stop_reason 当作已采集事实；8100 是合法动态首选端口。

最小整改须统筹阶段预算与宿主寿命：派发前验证剩余寿命，或调整受控启动时序/可信停止后的绑定；不得盲目延长等待、超出八次启动或以未知停止重启。

## 明确保留的准备限制

当前 scope 为 False/PREPARED_NOT_AUTHORIZED，缺后续具体授权到来时的可信激活与重新冻结入口；不能直接翻改 scope。Houdini 补登记后将 verify 记 DONE，但尚未启动的 Nuke 尾部停在 QUERY_REQUIRED；不承诺任意中断后的自动续做。

## 审查者复验

Python 3.11：driver 4/4；handoff 3/3；boundary/auth 24 PASS、1 Windows SKIP。与主控验证重复，不累加。软件协议单测不代表完整跨进程工程链已通过。
