# 历史结果读取修复与验收

Bridge **0.4.23** 已并列安装并设为默认入口。安装后的全新消费者通过正常 MCP 查询入口选择默认目录内的 **9 个工程**，读回其中 **14 个已完成结果**；其余 2 个工程只有创建或提案记录。本轮不制作、不渲染、不启动 Houdini/Nuke，原生执行工具调用为 **0**。

## 定位与修复

| 问题 | 根因 | 当前处理 |
| --- | --- | --- |
| 旧结果被版本检查拒绝 | 读取器没有明确接纳新版只读消费者 | 显式接纳已支持的读取器版本；未知版本继续拒绝 |
| Geometry Gate 报模块与安装清单不一致 | 将原生产环境的 0.4.9 清单用于比较当前读取器模块 | 原生产包、实际快照与当前读取包分别验证，各自保持完整来源约束 |
| 创作 V1 在 V2 后无法读取 | 正常消费要求当前有效版本，历史观察沿用了该条件 | 已接收的历史结果可只读观察；被替代产物标记 `historical:true, consumable:false`，不恢复执行或消费权限 |
| RectLight V1 被后续失败影响 | 原范围后来追加失败票据，且原 Nuke 停止记录位于较早调度器 | 从已签记录验证原完成前缀；按原启动签名定位同任务、同根目录的有效祖先调度器，首尾复核记录 |

**更正旧诊断：原 0.4.20 安装包没有内部损坏。** 原包 429 个清单成员均与文件一致，也与保留的发布 ZIP 一致。错误出在跨版本读取时的清单选择。详见 [原包诊断](package-diagnosis.json)。

历史观察仍验证原授权、正式包、实际快照、结果签名、文件摘要及可信停止；人工失效、篡改、无来源的版本替代和失败停止记录不会被当作成功。当前生产消费路径仍要求有效的当前版本。

## 正常入口读回

验收使用安装目录内的 `bridge_mcp.py serve` 启动全新消费者，仅调用 `bridge_health / bridge_projects / bridge_select_project / bridge_tasks / bridge_continue_task`。

| 默认登记工程 | 已完成结果数 | 读回结果 |
| --- | ---: | --- |
| completed-geometry-20261105 | 1 | COMPLETE；原目标 UNKNOWN 保留 |
| created_41332fa685540f5259aa7301 | 2 | V1、V2 均 COMPLETE / goal PASS |
| created_5413674dd70746566288c34f | 3 | V1 PASS、V2 FAIL、正规 V3 PASS；均为技术 COMPLETE |
| DiskLight | 2 | V1、V2 均 COMPLETE |
| Geometry Gate | 2 | V1、V2 均 COMPLETE / goal PASS |
| RectLight | 2 | V1、V2 均 COMPLETE |
| RectLight Softbox | 2 | V1、V2 均 COMPLETE |

`created_29314c25c97c257d7cdb2e87` 与 `created_e70e336c786e674d71bfa597` 可选择、可列原任务，没有已完成结果可验收。独立登记目录不包含在上述默认目录计数内；本次也不将既有失败操作改为成功。

[完整安装后读回](installed-readback.json) · [简要结果清单](readback-summary.json) · [独立最终核对](final-independent-check.json)

## 定向验证与安装

- 48 项相关定向用例最终通过，覆盖读取版本、旧/新包来源、历史产物、已签范围前缀和原 Nuke 停止调度器。并发验收时一个 Python 子进程曾触及 30 秒等待上限；单独复测通过，没有放宽断言。没有运行无关全量回归。
- 独立代码复核未发现待修复的 P1/P2 问题。
- 从保留的原 0.4.20 发布包重建隔离来源，仅加入本次修复：12 个文件新增或变化、无删除，未打入工作目录的其他未提交改动。
- 新包 **431 个清单成员**逐一验证，安装文件与候选一致。清单摘要为 `4ef303d591e334676f8fdbc53f0a3568b3f55370b92d82608a0dfff3574bdb5c`。
- 原安装与选定的正式结果、接收回执、授权和范围账本共 **569 个受保护文件**在读回后摘要保持不变，详见独立最终核对。

当前默认：`bridge-vfx@bridge-local-v0423-history-reader`。

安装目录：`/Users/user/.codex/plugins/cache/bridge-local-v0423-history-reader/bridge-vfx/0.4.23`。

本聊天已加载的旧 MCP 连接仍是 0.4.20；默认设置变更不会替换这个已运行连接。**上述完整验收来自全新启动的已安装 0.4.23 消费者**，后续新会话使用新版默认入口。未重启其他会话或应用。

[安装核验](installation.json) · [包差异](final-package-diff.json) · [发布包入口](../../outputs/Bridge-history-reader-20261113/README.md)

本轮验收只证明历史读取兼容及安装内容一致；没有新增制作、视觉或完整教程复现验收。原失败、未确认票据与历史授权保持原状态。
