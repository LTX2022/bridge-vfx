# H21＋Nuke 第14轮实际产物清单

状态：首个 alpha-husk 阶段失败并停止；未生成可交付 HIP、NK 或 EXR。

## 已到达

- 真实输入：`alpha-chart/alpha-chart.usda`，5199 bytes。
- 真实启动及失败证据：原始 child/supervisor 日志、started/stopped 回执、driver journal。
- 原生首错：`husk_runtime_ready.py:8` 使用 `__file__`，该 prerender 执行环境没有定义此名称，触发 `NameError`。

## 未到达

- runtime-ready、alpha 渲染输出与校准结果。
- 球地面 HIP、保存／新进程重开及主 EXR。
- 主产物登记、Nuke 首次保存／重开、消费及合成 EXR。

本轮没有可展示的真实预览图；未从历史轮次复制图片或工程冒充本轮产物。

实际预算记录：1/8 次启动；已计费 DCC 时间 8.059413194656372 秒；该范围已关闭，不续跑剩余启动。

## 公开原始文件 SHA-256

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `outputs/engineering-closure-20261023-h21-14-authorized/alpha-chart/alpha-chart.usda` | 5199 | `99f4c924a8ae5a6117b37b645c18ee6d809e6ea16e6e7d88e457b3fd96d38a2f` |
| `outputs/engineering-closure-20261023-h21-14-authorized/alpha-chart/preparation.json` | 4080 | `130c1cb37c253924b96a11ac42ce88f3ca288235edcb7c85b74bb2e1939a4502` |
| `outputs/engineering-closure-20261023-h21-14-authorized/engineering-driver-state.json` | 551 | `6fcb1a2831a6752a390188f2c4ab9494cae352d1433b2f87419c8c380a91f4e4` |
| `outputs/engineering-closure-20261023-h21-14-authorized/native-scope-state.json` | 932 | `b2bc9f7200b1c14f1ae5c15fefc91dacb9ae23c2f0acb4c5a6f5cb6ae297adc9` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/started.json` | 1042 | `4de0a0bf6b82ece66207c3df61275d7a20d6fbc34a67c3cbdd77e8db06b85922` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/stopped.json` | 685 | `840378ab5345a01232e2917f58c14b20749f3d7f688c66bd5c432069dcde91d6` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/child.stderr.log` | 494 | `3243dca10b55044f166bbf612538a0a90d128478310db1e5e9433accf056f091` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/child.stdout.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/supervisor.stderr.log` | 1256 | `4a1be3bb0d093c8fbec11fb46dad3255a6e9fa2f4527df34679f7937ff3b5877` |
| `outputs/engineering-closure-20261023-h21-14-authorized/supervisor-alpha-h21/supervisor.stdout.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `handover/evidence/20261023-h21-live-14/execution/driver.stderr.log` | 4127 | `d57c0bbcfe8c1c7ff4d399cfb048e108904cc364d3e5b9a8b8b03c06ee3ada84` |
| `handover/evidence/20261023-h21-live-14/execution/driver.stdout.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `handover/evidence/20261023-h21-live-14/execution/driver-execution.json` | 1466 | `b09cd1a61328c4bf08d62840cc2ee144d6c74793db3ce50d1834ba466c4faea1` |
| `handover/evidence/20261023-h21-live-14/execution/authenticated-stop-review.json` | 2152 | `1bc0638cf031874e7ee8de0e2ccca164dc196e8d5cbeb700cfa3a79f273acb7f` |
| `handover/evidence/20261023-h21-live-14/execution/post-exit-owned-group.json` | 263 | `d658d249fa53eafcd40064be5336fbd946c02e1cd8309eedccccbea5b952e9a6` |

以上逐文件摘要仅指本轮公开输入和执行证据；未复制 intent、环境变量或私有认证材料。
