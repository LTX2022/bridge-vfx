# HIP 专项入口实施交接

新增文件仅 `tools/run_hip_diagnostic.py` 和 `tests/unit/test_hip_diagnostic.py`；生产模块、既有 scope/数据库未修改。源码已冻结。

- 工具 SHA-256：`34d7378122e90d2754c2419431c3113a71aac889d9ddc3e300cafc59fa291452`
- 测试 SHA-256：`328f250893b7b725437f3144c07a3d6ed28bff52d7bca3b9cbaa689fe072489f`
- 聚焦软件验证：10/10，通过，67.430 秒，`implementation-tests.log`。
- 最终逐次 120 秒边界定向验证：1/1，通过，5.669 秒，`implementation-budget-final.log`。
- 完整两阶段软件替身重放：未通过，保留 `implementation-two-phase-red.log` 原始输出；不记为成功。
- 本实施者真实 DCC 启动数：0；未激活真实范围，未执行真实 HIP 专项。

软件验证覆盖：零启动准备/预检，输入/源码/计划/配置/预算漂移拒绝，条件授权及签名绑定，软件来源禁止真实入口，首阶段未知禁止第二阶段及续跑，2 次/240 秒/逐次 120 秒/磁盘限制，冷 host 干净 Python 冻结包定位与 warmup=False，冷 host 停止未知有界等待且保留 scheduler 占用，真实 addon 严格 verifier 在显式 HOM/USD 底层替身上产生的完整通道/结构/连接/UsdShade 读回及缺项拒绝，快照与签名缺失拒绝。

入口采用原 NativeScope 认证账本（外层 8/600 不变）、StageJournal、GraphScheduler 和 OwnedProcess。专项阶段按同账本检查 2/240，并在所有终态封闭；第一阶段签名成功停止后才允许冷启动。第二阶段保留 scheduler 独占，双方 TASK_STATE 共用保存记录、各自 STATE/ops/lease 独立。冷 runner 只在冻结四包路径前置后使用现有 RUNNER_TEMPLATE。OS 主映像 NOT_OBSERVED，生产身份 NOT_RUN。

## 命令

普通 Python 与所有输入必须使用规范绝对路径。以下 prepare 命令对应主控已经建立的 prepared-02 候选；该路径已存在，不重复执行。每次准备必须使用全新目录。

```sh
/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/tools/run_hip_diagnostic.py prepare --output-root /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024-prepared-02 --plan /Users/user/Documents/Code_Project/Bridge/handover/HIP_ONLY_PLAN_20261024.md --hython /Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/bin/hython --supervisor-python /opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 --ocio-config /Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/packages/ocio/houdini-config-v2.1.0_aces-v1.3_ocio-v2.3.ocio

/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024-prepared-02/control/snapshot/tools/run_hip_diagnostic.py preflight --scope /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024-prepared-02/scope.json
```

激活明确要求审核者绑定实际 candidate_scope/candidate_freeze/source_sha256/target_root 的 review JSON，以及主控记录本轮用户条件指令、同一 review 的 authorization JSON；公开 hash 不会自行授权。以下 review/authorization 文件由主控在审核通过后提供。

```sh
/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024-prepared-02/control/snapshot/tools/run_hip_diagnostic.py activate --scope /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024-prepared-02/scope.json --review /Users/user/Documents/Code_Project/Bridge/handover/evidence/20261024-hip-only/freeze-review-02.json --authorization /Users/user/Documents/Code_Project/Bridge/handover/evidence/20261024-hip-only/conditional-authorization-02.json --output-root /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024

/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/control/snapshot/tools/run_hip_diagnostic.py preflight --scope /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/scope.json

/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/control/snapshot/tools/run_hip_diagnostic.py execute --scope /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/scope.json

/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -I -B /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/control/snapshot/tools/run_hip_diagnostic.py verify-receipts --scope /Users/user/Documents/Code_Project/Bridge/outputs/hip-only-h21-20261024/scope.json
```

签名为既有 HMAC；离线复验在保留原始本机密钥处使用冻结源码读取原件。交付包排除 `.native-control/key`、`receipt.key`、`intent.json` 和 token，不声称公开 ZIP 能独立验证 HMAC。
