# Bridge 12 激活前只读核查

结果：**GO**。核查完成时间：2026-10-23T09:52:57.717007+00:00。

- scope、bindings、review 三项 SHA-256 与授权指定值完全一致。
- 11 为 PREPARED_NOT_AUTHORIZED；签名状态、journal 与 anchor 验证通过，0 票据、0 启动；无 activation receipt。
- review 仅指向 `engineering-closure-20261023-h21-12-authorized`，目标目录不存在。
- 158 个源码快照与当前仓库、review、snapshot manifest 及成功软件链 02 快照逐项一致；174 项 source_freeze、175 项 immutable 均一致，无 pyc 或符号链接。
- H21.0.631、Nuke17.0v1、ACEScg；本机 4 个宿主/监督器文件及 8 个颜色/原生依据文件的字节数与 SHA-256 全部匹配。
- 预算保持 8 次启动、每次 120 秒、累计 600 秒、512 MiB、1 个 heavy、0 自动重试。
- 冻结快照 CLI 默认只读预检返回 PREPARED，blockers 为空，stderr 为空；未执行 activation 或 --execute。
- 实际 ps 核查：0 个重型 DCC 作业；仅 sesinetd PID 443 与 hserver PID 8475 两个许可证服务。沙箱 ps 拒绝通过常规只读权限解决，未作为产品故障。
- Data 卷可用 64.933 GiB（69721178112 字节），11 目录 4769310 字节，满足 512 MiB 目录预算。
- 06 至 11 共 1227 个文件已保存字节数/摘要 baseline；默认 CLI 预检后逐文件复验不变。06 至 10 与既有 originals-before baseline 相符，软件链 01/02 原件分别 608/644 项相符。
- 本次配置均为 real_host，无软件边界、image adapter 或 bootstrap 配置；alpha 直接调用原生 husk。控制清单原有 requested_model=HY3、requested_route=WorkBuddyDesktopRoute 描述字段仍存在；冻结 driver 固定使用 server.py --backend production 的公开 stdio MCP，不调用模型或 WorkBuddy。

报告：`/private/tmp/bridge-live12-preflight/audit.json`。

原件 baseline：`/private/tmp/bridge-live12-preflight/originals-06-to-11-baseline.json`。

安装文件核对：`/private/tmp/bridge-live12-preflight/installed-file-hashes.json`。

进程库存：`/private/tmp/bridge-live12-preflight/process-inventory.txt`。

结论仅覆盖激活前核查；本角色未启动 DCC，未改仓库文件，未激活 12。
