# 主工程 driver、运行绑定与 NK 首次保存

当前源码接续结果见 [生命周期、可信激活与 Nuke 续接](CLOSURE_CONTINUATION_20261020.md)。以下记录对应前一冻结候选及其当时的阻断，不作为当前源码结论。

当前状态：本轮软件准备已实现并冻结；正式入口仍有生命周期阻断，候选未接收。真实 Houdini/Nuke/WorkBuddy/HY3、渲染和视觉验收均未执行。保留已有源码修改与历史范围，未提交或推送 Git。

## 当前实现

- `tools/prepare_controlled_engineering.py` 使用正式生成器准备独立项目、部署、源码快照、冻结场景输入、八项启动清单、writer 计划和运行绑定。只调用固定 Python 做文本准备与预检，不授予执行权限；重复准备验证原件，不覆盖漂移或残缺成果。
- `tools/run_controlled_engineering.py` 串联 alpha、正式建图、HIP 保存/冷重开、受控输出验证与登记、NK 首次保存和已有后台 worker。默认仅预检；当前未授权范围即使 hash 匹配也拒绝执行。慢建图使用同请求完成宿主交接；状态在互斥锁内重读。
- `tools/prepare_nuke_project.py` 从真实账本消费产物，经正式 render_binding 设置并读回 Read→Write，首次保存 NK 后读回路径、节点及连接，生成认证保存回执；不重启宿主、不渲染。
- `tools/verify_controlled_output.py` 认证读取原始 alpha 校准结果，临时配置验证客户端；不改写原渲染事实或冻结配置。
- 已可信完成且验证通过的账本故障只补登记；坏 EXR、alpha 或验证来源失败不会冒充登记故障。Nuke 恢复命令在客户端与原生服务两层校验持久操作所有者，保留原 token/HMAC。

## 冻结项目与安全预检

项目：`outputs/engineering-closure-20261020-h21-03/project/`

运行绑定：`outputs/engineering-closure-20261020-h21-03/runtime-bindings.json`

- scope SHA-256：`b44e17db8a0ac6852655dd4874b33f33432739efacbd79fd734944959749a8bb`
- bindings SHA-256：`2f9bddb85e3eeb0bafc4723f364ed454efbfe2e4dde29bee63144c4ceef6ca8b`
- alpha/default-driver 预检均为 `PREPARED / NOT_RUN`，没有预检缺项。
- scope 原字节不变，`execution_authorized=false`、`PREPARED_NOT_AUTHORIZED`，DCC 启动与票据均为 0。私有 key 未复制到源码、证据或 Git。

默认预检命令（不会执行 DCC）：

```sh
/opt/homebrew/opt/python@3.11/bin/python3.11 -I /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-03/project/control/snapshot/tools/run_controlled_engineering.py --scope /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-03/scope.json --bindings /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-03/runtime-bindings.json
```

`PREPARED` 仅证明冻结材料与接线通过预检，不证明正式工程链运行成功。

## 验证与独立复核

Python 3.11.16，隔离临时目录 `/private/tmp`，显式包路径；生产边界测试仅替换底层 API、传输和 Python 子进程。

| 检查 | 结果 |
|---|---|
| alpha runner、正式生成器、handoff、准备器、driver 五组核心 | 26/26 PASS，见 `evidence/20261020-engineering-driver/core-final.log` |
| production boundary / Nuke transport auth | 24 PASS、1 Windows 专属 SKIP；独立复验相同，不重复累加 |
| 实际 -03 纯准备 | 双预检 PREPARED / NOT_RUN，见 `actual-preparation.json` |
| controller-client 源码副本 | 无差异 |
| 正式生成入口/完整建图交接单例 | FAIL，见 `formal-entry-final.log` |
| 全量回归、发布安装包、真实工程/视觉 | 未运行/未重建 |

首次四模块组合的夹具残留已修正；受沙箱限制的签名子进程测试按所需权限复验通过，未放宽生产身份校验。较宽的旧 production-hosts 模块在源码整改期间出现失败后中止（退出 130），不作为冻结版本通过证据；正式入口失败另行隔离复现并保留原始日志。driver 的正常编排测试是协议单测，不冒充全服务端到端通过。

Bugbot 未参与实现，已复核本轮整改和失败，记录见 `evidence/20261020-engineering-driver/independent-review.md`；源码指纹见同目录 `source-sha256.json`。

## 尚未关闭

1. **P2：宿主寿命与阶段预算没有闭合。** H 宿主从初始化起消耗总寿命，而建图可用满 120 秒。图完成后的正式交接仍访问原 host。单例在合法异步查询后复现 `BRIDGE_UNREACHABLE`，因此不能宣称 HIP 交接/保存/重开链通过。8100 是合法动态首选端口，并非默认客户端回退。原临时目录已清理，日志无原始 signed stop，具体退出原因不能仅凭总耗时当作已采集事实；代码已证实缺少剩余生命周期准入和过期交接处理。下一步仅修这一接点：派发前核对可用寿命与阶段预算，交接时核对可信状态；不透明多启宿主、不放宽八次/120秒范围、不用增加 sleep 代替同步。
2. **授权激活入口未实现。** 当前 False scope 的 SHA 绑定认证状态、配置和全部计划，不能事后翻值。后续取得具体授权后仍需可信的新授权范围/重新冻结入口，当前候选不可直接启动。
3. **中断续接有限。** H 补登记成功会把 verify 记 DONE 并清 pending，但从未启动的 Nuke 尾部明确返回 `QUERY_REQUIRED`；不自动发起新原生作业，也不承诺任意 INTENT 中断的自动续做。
4. 原生 alpha、HIP/NK/EXR、人工视觉、H22 兼容、HY3、反馈/实际 worker 恢复、复用与全域 M1 均保留未验收状态。
