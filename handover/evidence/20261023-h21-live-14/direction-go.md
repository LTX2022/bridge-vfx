# H21＋Nuke -14 方向准入

**GO：root 可按当前人类明确授权，经正式受控 TTY 将 -13 frozen review 激活为唯一 -14 目标；激活后正式预检通过，再由唯一 driver 执行。** 本方向未激活、未启动 DCC、未修改源码或旧范围。

## 当前冻结核对

只读审计 `/private/tmp/bridge-live14-direction/frozen-audit.json` 的 16 项检查全部 true：

- scope SHA：`bb4c001a00ea38b92ccd57bb6cff9c128222fdf8c02e7a6fbcc2600995386276`。
- bindings SHA：`b43dff981e21f17aa9dfa55ff210e8e80ea608f76cebea8b2f91492670380e13`。
- review SHA：`72592c392e00a44747bcbe39c6dd13dc7bf35c6a5dca4f1091e6b1aa36f42535`。
- 159 项源码快照与 review source_snapshot、当前 authoritative 源码完全一致；175 项 source_freeze、176 项 immutable 的大小／SHA 均一致。
- scope／bindings／preparation／review 的 scope_contract 与 runtime_contract 一致；evidence_source 为 real_host，无 software_native_boundaries。
- -13 仍 PREPARED_NOT_AUTHORIZED、未执行，已读状态 seq 0／0 票／无 closed_reason；正式激活工具仍须认证本地签名状态，本方向未将仅解析状态替代该认证。
- 目标精确为 `/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-14-authorized`，只读检查时不存在；resource_roots 仅此目标。

H21.0.631／Nuke17.0v1／ACEScg；8 次／每项 120 秒／累计 600 秒／512 MiB／1 heavy／0 自动重试均精确一致。-13 软件证据只能支持软件候选，不是 H21 hook 同 PID、真实输出或工程闭环证据；本次 -14 正是独立真实验收。

## TTY 与人类授权来源

已读正式 `activate_local_terminal`（tools/activate_controlled_engineering.py:213–223）。其具体合同为：先 `_review` 全量核对，stdin 与 stdout 均为 TTY，展示完整 review，再接收确切 `AUTHORIZE <本 review SHA>`。模块开头明确这是 trusted controller boundary，不是同用户程序防护；不存在必须由人类物理按键、禁止已获授权代理转交的检测或附加合同。

当前人类已经具体授权本 review、-14 目标和上述预算，因此 root 可在真实 PTY 中代为转交该短语，无须再增加确认循环。激活审计须记录当前人类授权原文、review SHA、目标、实际转交者 root／agent 与 TTY 回执；不得把代理输入写成人类亲自键入。本方向不持有或编造未提供的人类原文。

必须使用正式 CLI／activate_local_terminal，不调用私有 `_activate` 绕过边界，不用 explicit_software_test_controller，不改冻结代码，不复用旧范围签名密钥。激活只创建独立新范围和新认证，不自行执行 DCC。

## 运行与停止边界

正式 fresh driver 顺序为：原生 alpha husk → 原生 alpha Nuke → 正式 graph propose／build／save → 初始 Houdini 可信停止 → 冷重开 → 单帧受控 husk render → Houdini 可信停止 → 独立输出验证／登记 → Nuke 准备／消费／有界 render → Nuke 可信停止 → 最终原始回执与产物认证。8 次启动清单是角色上限，不是可以任意调换或补跑的次数。

首次真实失败、超预算、未知停止或身份／ready 拒绝即停止本轮后续 DCC。现有自有组停止和 native_scope 记账继续生效；未知停止不释放票据或 heavy 槽。剩余启动额度不能用来重试、续跑或自动启动另一 driver。

driver 使用 fresh 默认路线；不使用 `--continue-nuke-tail` 或 resume 进行新 DCC。源码的 RegistrationPending 分支是待登记状态而非完整成功，可能保留既有 idle Nuke；若遇到该状态，执行者必须准确记录现有宿主及停止情况，不将其写成已全部停止或工程完成，也不据此另派发 DCC。只允许当前授权内的软件诊断／修复和新冻结；后续真实运行必须新 review、新明确授权。

## 本方向结论范围

未发现当前 review／scope／bindings 差异或 TTY 合同新增阻断。正式 -14 认证、宿主占用、当前资源／磁盘和全链预算预检由对应只读预检角色及唯一激活／执行者完成；本报告不是对未发生的真实运行结果作 PASS。原 06–13、Desktop 主工程和既有严格身份／stderr 门继续保留。
