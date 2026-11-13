# 生命周期、可信激活与 Nuke 续接

本轮三项软件整改已完成，独立复核无剩余 P1/P2。正式软件入口通过；真实 Houdini/Nuke、WorkBuddy/HY3、alpha 校准、渲染及视觉验收仍未执行，工程闭环与完整 M1 不因此标为通过。当前交付为源码及本机未授权候选；未重建安装包、未提交或推送 Git。

## 当前实现

1. **生命周期与预算**：正式控制器只验证部署，建图 worker 不空耗控制宿主；交接时启动 H1，保存后新实例 H2 重开；NK 首存时才启动唯一 Nhost。保持两 H、一 N 控制宿主及完整部署指纹，已停止/身份未知的缓存客户端不会透明增加启动。签名 started 记录实际预算；每次 H/N 派发前根据真实剩余寿命扣除 6 秒停止余量，N 插件把实际预算传到 owned worker。仍为八次启动、每操作最多 120 秒、累计 600 秒、512 MiB、同时一个重作业、自动重试 0。
2. **可信激活**：`tools/activate_controlled_engineering.py` 提供 `prepare-successor`、`review`、`activate`。后继候选与授权目标各自使用新 root/id/key；review 事先固定来源、输入、配置、资源和目标路径。真正激活需要可信本地终端明确确认对应 review，生成新授权范围及重新冻结的部署/运行绑定。公开 hash 或模型布尔不能替代该动作；driver 在执行前及锁内验证签名激活回执。这个入口是协作约束，不声称系统级隔离。
3. **Nuke 受控续接**：显式 `--execute --continue-nuke-tail` 只推进本任务尚未执行的固定尾部，重验 alpha、H 停止、登记版本/摘要、活 Nhost 身份与精确配额。已有 Nrender 意图只读持久事实，不重放；已完成 worker 的账本故障可在 Nhost 不可用时离线补登记。NK 保存成功但回执未提交时，仅凭同宿主、签名保存意图、原文件及节点/路径/连接读回核验恢复，不再次 save/render。事实不完整时保持 QUERY_REQUIRED，不自动重启宿主。
4. **冻结来源**：修复 Python -I 忽略环境字节码开关的问题。入口主动禁写缓存，固定 Python 命令采用 -I -B；快照全部文件继续严格校验，不以忽略目录消除漂移。Nuke 原始记录目录按实际宿主 `task_root/state/nuke_renders` 写入配置并核对。

## 当前候选

项目：`outputs/engineering-closure-20261020-h21-04/project/`。

- scope SHA-256：`e734404caefa859c3f21c437291c96109748e3aa645640d1bfe3f9d3529c2fdf`
- runtime bindings SHA-256：`e1fe9b870ef678c2b4a46594758b2ba51a7ab09d525fcd7a09331a7b6c34d67b`
- review SHA-256：`522b037972d355c4dabe3b79e309731953c3321a86d730a00ba26600a57f6634`
- 当前范围 PREPARED_NOT_AUTHORIZED，execution_authorized=false，DCC 启动/票据均 0；使用独立新 key，私有内容未进入源码、Git 或证据文件。
- 后续授权目标固定为 `outputs/engineering-closure-20261020-h21-05-authorized/`，该目录尚未创建，本轮没有实际激活。
- -01/-02/-03 scope 原字节不变，-03 启动仍为 0。175 项冻结文件和当前源码一致，快照无 pyc；准备及默认 driver 预检均 PREPARED / NOT_RUN。

安全默认预检：

```sh
/opt/homebrew/opt/python@3.11/bin/python3.11 -I /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-04/project/control/snapshot/tools/run_controlled_engineering.py --scope /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-04/scope.json --bindings /Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261020-h21-04/runtime-bindings.json
```

后续单独确认真实作业范围后，由可信本地终端使用冻结快照中的激活工具确认 `engineering-activation-review.json`。激活只生成授权材料，不启动 DCC；实际执行另需新范围和新 bindings 的准确 SHA。不能给旧 -03/-04 直接翻授权值，也不能使用旧 hash 执行新范围。

## 验证与证据

Python 3.11.16；TMPDIR=/private/tmp，显式软件替身仅限底层 API/传输/自有 Python 进程。

| 最终验证 | 结果 |
|---|---|
| 受影响核心、正式生成入口、保存/重开/重连、实际 Python worker 预算 | 69 项运行，68 PASS，1 Windows 专属 SKIP |
| 可信软件激活与默认 -I 入口 | 无字节码缓存；来源认证保持有效 |
| 实际 -04 纯准备及默认预检 | PREPARED / NOT_RUN |
| 冻结文件、当前源码及旧范围原件 | 一致；DCC 启动 0 |
| 独立 Bugbot | 本轮范围无剩余 P1/P2 |

最终日志为 [core-release.log](evidence/20261020-closure-continuation/core-release.log)，源码指纹、独立结论、候选准备/预检、review 和完整性结果均在同一证据目录。此前 `core-final.log` 与单例日志只证明对应中间源码，不替代最终日志。未运行项目全量、安装生命周期或任何真实宿主。

## 后续边界

当前可以审阅本轮软件候选及具体资源范围。真实阶段仍须按原计划分别完成 H21 原生 alpha 校准、HIP 冷重开、受控 EXR 验证/登记、NK 新进程重开/消费以及人工视觉检查；然后再验证 H22.0.459、反馈/实际 worker 中断恢复、HY3 和复用。被冻结的全 16 域及原 M1 要求仍保留，未在本轮扩展或宣布完成。
