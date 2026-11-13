# Bridge C1–C6 候选变更

## 输入基线

输入包为 `input/bridge-skills-R01-R10集中返修候选-20260920.zip`，原始 SHA256：`d87a7eb922924afd3f9f0d37fc506bea6aa9c6a588c62af9a932b10aebcb620d`。修复前边界复现见 `evidence/pre-boundaries-20260930-172140.log`、`evidence/pre-generated-entry-20260930-172140.log` 与 `evidence/original/full-python311.log`。复现输出只证明对应观察，不把退出码 0 当作通过。

完整候选保留当前工作树中原有的模块与文档；`changes.patch` 用于从上述原始 ZIP 的源码树重建交付候选，不表示每一处历史差异都由 C1–C6 引入。本说明只归纳本合同六组。

## C1 — Houdini 租约身份与恢复

- 根因：续租使用旧记录全量写入，可能覆盖并发接管；重开写入的代次与后续校验身份命名空间不同；requeue 在换槽与持久记录提交之间没有可恢复阶段。
- 修改调用链：`_root_lease_write` 在每根锁域内按期望版本 CAS；租约 owner generation 取宿主进程身份；副作用前围栏重验；requeue 持久化 intent/slot 阶段，冷启动发现代次不匹配并允许可信恢复。
- 主要文件：`plugins/houdini/_impl/houdini_bridge_addon.py`、`tests/unit/test_c1_lease_identity.py`。
- 行为断言：新宿主接管后旧宿主写入被拒；旧版本续租不能覆盖新 owner；保存场景的节点、参数和连线逐项比对；requeue 中断后可发现并恢复且不重复副作用。
- 修复前失败：原始 lease 竞态、重开代次与 requeue 中断复现保存在 `evidence/original/evidence/`。未附独立停止事实的 requeue 探针保持占位并 fail-closed，不作为恢复成功证据。
- 修复后成功：最终哈希 `evidence/green-final-c1-*.log`（租约/重开/requeue 行为与同步检查）；`evidence/green-final-c1-cas-*.log`（事件屏障下接管后旧租约不能覆盖新 owner）。

## C2 — Nuke 请求、原生类型与停止恢复

- 根因：新一轮可被内容哈希误复用；调用方 request ID 与场景/控制内容未完整绑定；原生 `executeBackgroundNuke` 的整数 task ID 被误作进程句柄；未知启动阶段不能可靠恢复。
- 修改调用链：统一渲染入口使用稳定 request ID 和独立内容摘要；阶段记录持久化；自有后台 worker 走受控子进程，原生 task ID 不执行 PID 操作；查询/取消/恢复保持已知身份并等待停止事实。
- 主要文件：`plugins/nuke/nuke_bridge_addon.py`、`tests/unit/test_c2_nuke_contract.py` 及 Nuke 渲染回归测试。
- 行为断言：同 ID 同内容复用、新 ID 建立新轮、改内容拒绝；原生整数不调用 poll/terminate；控制器丢失内存句柄后仍可恢复；未确认停止不释放占位。
- 修复前失败：`evidence/pre-boundaries-20260930-172140.log` 记录严格原生签名调用在函数体前抛 TypeError、第二个 request ID 被复用为同一执行。
- 修复后成功：最终哈希 `evidence/green-final-c2c4-*.log`（C2/C4 Nuke 定向组）。

## C4 — 以可信运行事实登记产物

- 根因：调用方可用任意格式哈希登记/晋级；登记时间代替生产开始时间；无效 EXR、重复活动帧或缺少颜色/预乘确认仍可能到 final；独立包账本依赖闭包不完整。
- 修改调用链：共享账本验证可信 operation source 与 task/场景/帧集/输出/状态；保存 `production_started_at` 与登记时间；按有效图像字节、逐帧观察和宿主确认判定；不可变版本历史与 promotion CAS；Nuke 完成登记失败可作为部分完成恢复。
- 主要文件：`packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py`、`packages/vfx-pipeline/src/vfx_pipeline/artifact_registry.py`、`plugins/nuke/nuke_bridge_addon.py`、相关 Nuke/C4 测试。
- 行为断言：无 operation、伪回执、错误 EXR、跨 task、活动重复、缺失颜色/预乘或依赖均不能 final/usable；真实可信完成事实的新鲜产物可登记；较晚登记不改变生产 freshness；版本历史与并发 CAS 保留。
- 修复前失败：`evidence/pre-boundaries-20260930-172140.log` 记录不存在 operation、非法 EXR 与任意回执仍晋级，以及刚完成输出被判 stale。
- 修复后成功：最终哈希 `evidence/green-final-c2c4-*.log`（含 artifact registry 与 Nuke freshness）；`evidence/green-final-c4-*.log`（独立临时状态根）。

## C3 — 正式生成入口与操作路由

- 根因：旧测试使用独立 launcher 并预置正式流程未创建的状态；生成 server 缺少正式 facade 依赖；schema、授权与操作 kind 路由不完整。
- 修改调用链：生成器与软件测试调用同一 `build_graph_facade()`；通过正式生成的 `control/server.py --backend software` 运行真实 JSON-RPC/MCP、GraphRun、GraphMCP、save/reopen 与插件 dispatch；fake 仅替换 HOM/进程边界。持久 operation registry 按注册 kind 路由 query/cancel，feedback 限制到已编译节点与参数目录范围。
- 主要文件：`packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py`、`workbuddy_graph_mcp.py`、`tools/prepare_workbuddy_graph.py`、`tests/unit/test_c3_formal_entry.py`。
- 行为断言：建图→保存→新进程重开→参数修改→有界帧操作；host-frame 与 Nuke operation 分别经注册路由查询/取消；同 request 复用、新 request 新轮；未知 operation 不产生 host dispatch；未授权、13 帧、超预算、NaN、陌生节点、任意路径在副作用前拒绝；有界 Nuke 输出可登记、消费及查询。
- 修复前失败：`evidence/pre-generated-entry-20260930-172140.log` 与 `evidence/pre-boundaries-20260930-172140.log` 记录正式入口拒绝缺少依赖、13 帧/999 秒穿透及帧取消误走 graph jobs。
- 修复后成功：最终哈希 `evidence/green-final-c3-*.log`（正式入口与 GraphMCP）。

## C5 — 可参与验收判定的 watchdog CLI

- 根因：旧 CLI 在函数定义前进入 watchdog mode；AST 抽函数测试没有执行正式入口；监督对象的身份/回执、ready、退出状态、操作预算及停止确认没有形成父端门禁。
- 修改调用链：`accept_core_chain.py --watchdog-child` 独立解析并通过真实子进程运行；ready、事件、stderr 与 return code 被父端验证；进程绑定 launch receipt/nonce/generation/身份，未知身份 fail-closed；预算按确认的具体 operation 逐项开始/结束；SIGTERM 后继续观察并回收监督子进程。
- 主要文件：`controller-entry/accept_core_chain.py`、`tests/unit/test_acceptance_watchdog.py`、与正式控制器客户端同步的 `owned_process.py` / `houdini_bridge/client.py` 副本。
- 行为断言：缺回执、健康退出、超时停止、停止不生效、陈旧 generation、错误 process identity、监督者异常与无关子进程存活均由真实 CLI 覆盖。
- 修复前失败：`evidence/pre-boundaries-20260930-172140.log` 记录正式 watchdog 入口 `NameError`。
- 修复后成功：最终哈希 `evidence/green-final-c5-*.log`（真实 CLI 子进程测试）。

## C6 — 可复现测试与隔离收口

- 根因：中央测试入口未统一隔离全部 state root，局部环境覆盖可能污染调用者环境，模块级状态会跨用例保留；修复前 805 项日志有 36 个环境/占槽错误事件。
- 修改调用链：`tests/run_tests.py` 为全套测试提供临时的 Houdini、Bridge state 与 scheduler 根，移除 suite-wide ledger 覆盖以让用例独立派生账本，退出时恢复既有环境并回收 temp 目录；加入隔离回归；运行统一经 `tools/run_logged.py` 记录实际 argv/cwd/interpreter/build hash/UTC/return code。
- 主要文件：`tests/run_tests.py`、`tests/unit/test_test_runner_isolation.py`、缓存清理与环境恢复测试，以及 `tools/run_logged.py`。
- 修复前失败：`evidence/original/full-python311.log`（输入基线 805 项，36 errors；独立复核记录了真实 Application Support 写入与 `HEAVY_SLOT_BUSY`）。沙箱内 loopback EPERM 及同步前失败日志完整保留，不作为最终绿证据。
- 修复后成功：最终哈希 `evidence/green-final-c6-*.log` 与 `evidence/final-full-python311-loopback-*.log`（Python 3.11 全量结果；准确发现数、摘要与退出码见 `evidence/acceptance.json`）。

## 适用范围

以上只代表本候选的 C1–C6 软件合同与 fake/software 边界证据，不代表真实 Houdini、Nuke、WorkBuddy、HY3、视觉或发布验收。
