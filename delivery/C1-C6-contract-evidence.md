# C1–C6 合同证据索引

| 组 | 修复前红证据 | 修复后绿证据 | 结果 |
|---|---|---|---|
| C1 租约/恢复 | `evidence/pre-boundaries-20260930-172140.log`; 原始竞态/重开/requeue复现见 `evidence/original/evidence/` | 最终哈希 `evidence/green-final-c1-*.log`；其中事件屏障 CAS 输出必须含 `takeover_preserved: true` | PASS：单测覆盖新宿主接管、旧宿主拒写、场景契约与带可信停止证据的 requeue 恢复。较早 `green-c1-requeue-20260930-172841.log` 是旧探针未提供独立停止回执的 fail-closed 结果，不作为恢复成功证据 |
| C2 Nuke 请求/停止 | `evidence/pre-boundaries-20260930-172140.log` | 最终哈希 `evidence/green-final-c2c4-*.log` | PASS：稳定 request identity、原生 task ID 类型、持久阶段及恢复/停止契约由软件测试覆盖 |
| C3 正式 MCP 入口 | `evidence/pre-generated-entry-20260930-172140.log`; `pre-boundaries-20260930-172140.log` | 最终哈希 `evidence/green-final-c3-*.log` | PASS：生成 server 子进程、正式 JSON-RPC、授权/副作用边界与操作路由 |
| C4 产物账本 | `evidence/pre-boundaries-20260930-172140.log` | 最终哈希 `evidence/green-final-c4-*.log`；C2/C4 合并用例见 `green-final-c2c4-*.log` | PASS：可信 operation、内容/新鲜度、图像字节、宿主确认与版本 CAS；无可信 operation source 的 post probe 按合同拒绝 |
| C5 watchdog CLI | `evidence/pre-boundaries-20260930-172140.log` 中正式入口 NameError | 最终哈希 `evidence/green-final-c5-*.log` | PASS：真实脚本 CLI 子进程；身份、ready、operation budget、停止观察与失败门禁 |
| C6 可复现/隔离 | 冻结输入 `evidence/original/full-python311.log` (805 tests, 36 errors)；沙箱 loopback 拒绝见历史全量日志 | 最终哈希 `evidence/green-final-c6-*.log`；全量最终日志的精确文件名见 `evidence/acceptance.json` | PASS：全量发现数不低于冻结基线，沙箱拒绝与授权 loopback 重跑分别记录 |

## 日志说明

- 原始修复前报告、复现脚本、Nuke 17.0v1 API 契约及两份 probe 脚本保存在 `evidence/original/`；C1–C6 本轮原始日志保存在 `evidence/`。
- 定向与全量日志逐字保留 stdout/stderr，并含 `run_logged.py` 启动时采集的 argv、cwd、解释器、UTC 与 build hash。只把与最终源码 build hash 相同且退出码为 0 的日志标为最终绿证据。
- `post-boundaries-20260930-172140.log` 中不带可信 operation source 的账本写入得到 `OPERATION_SOURCE_REQUIRED`；这是 C4 应拒绝的输入，不标绿。
- `green-c1-cas-20260930-172841.log` 的旧探针签名未接收 `expect_version`，未到达屏障；原始探针仍保留，以新适配器事件屏障输出和最终哈希 C1 用例作证。单独 requeue 探针未携带独立停止事实时保持占位是 fail-closed，不表述为恢复成功。
