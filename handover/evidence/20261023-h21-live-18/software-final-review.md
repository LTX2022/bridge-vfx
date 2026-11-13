# 第 18 轮真实结果与第 19 轮软件候选独立验收

结论：第 18 轮真实工程未闭环；第 19 轮软件候选可接收。修后真实 Houdini／Nuke 工程为 `NOT_RUN`。

## 真实结果

沿用已完成的第 18 轮独立核查：54 项通过，3/8 次启动均可信停止，活动及未知停止为 0；累计 DCC 计费 78.698854923 秒，逻辑占用 62,241,557 字节。真实基础构建 `construction_executed=true`，随后 `domain.initialize` 未完成并要求 reconciliation；三处精确类型修复已生效。5 个真实 alpha EXR 有效，HIP、NK 与主工程 EXR 均未生成。2,520 个既有文件及 355 个停止态文件的保存结论不变。本阶段未重复运行真实层检查。

## 软件候选

最终 5 文件的 before／after 副本分别匹配清单，after 与当前源码一致；补丁往返证据有效。159 个执行源码仅有 addon、graph_job_worker 两处生产改动，与批准 review、成功链 02 的实际执行快照及当前源码逐文件一致，175 个冻结记录有效。

改动按 HOM 的 `Object` 类别严格匹配；声明图的等集合比较采用排除锁定资产内部的递归遍历。完整场景合同与重开核对仍保留内部节点。软件边界实际启用 Object 类别、18 个锁定内部节点和精确类型偏好，不把内部空参数容器解释成真实模板或状态观察。

成功链 02 单次运行 54.090006 秒，13 个阶段完成，8 张票据、7 组监督器停止、4 份 runtime-ready、2 个登记产物。源码与冻结记录运行前后未变，进程身份观察使用真实 OS 工具，DCC／HOM／USD／像素为明确软件边界，产物来源 `software_test`，原生 DCC `NOT_RUN`。

保存回执、GraphJobWorker 重开后验证、driver 的 `scene.reopen_task_hip` 已完成转换及最终 active_scene 原件共同证明：保存与重开后保留 41 个唯一后代节点，即 23 个声明节点与 18 个内部节点，内部路径和类型仍在完整合同中。未伪造独立的 reopen producer 回执。内部参数／通道在软件边界为空并明确 `NOT_MODELED`；原生参数模板、menu tokens、hidden／disabled／locked 参数状态仍未观察。

核心证据为 34 例通过，随后新增的保存重开回归 1 例通过；这是组合覆盖，不是一次 35 例全绿。两个生产源码在核心、成功软件链与最终候选中同 SHA-256。链 01 的软件 DefinitionNode 缺少序列化容器失败记录保留，修后链 02 通过，两个生产源码没有因该夹具失败而改动。

19 为 `PREPARED_NOT_AUTHORIZED`、0 票，无真实启动；预检 `PREPARED` 且 blockers 为空，仅生成指向未来 20 的 review，20 目录不存在。软件通过不构成真实新轮执行授权。

| 绑定 | SHA-256 |
|---|---|
| 19 scope | `ca1ad7b9fc8b53a8864b4dfa3a4c4faa07aa11f714b7ec9e0b26dfaa249612fd` |
| 19 bindings | `d1882a19566d244ee7de17cc39286ec46571c396cc74c3cafea92dbc8e3c5a14` |
| 19 review | `1d83d129bc3eb4d080f82fe3faea561bcd7e4ea263b9f619e39a22312591d3ba` |
| 5 文件清单 | `8d452912d3486345dc350ff867bccf0d9b2fac259e9a72063bda32f65cd609f9` |
| 补丁 | `bd7d0e5d2ad2f42e4b19f71274e6182622be431fa654c062d63778c84f97cb66` |

机器验收见 `candidate19-final-audit.json`：`passed=true`，62 项核对无错误。审查仅只读核对源码与原始证据，未实现改动、未运行测试、原生探测或 DCC。
