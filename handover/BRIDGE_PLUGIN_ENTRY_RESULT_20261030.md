# Bridge插件真实安装、工程选择与原任务继续结果

日期：2026-10-30。当前正式版本：0.2.3；插件ID：`bridge-vfx@bridge-local`。本轮官方安装、AppServer实际消费、工程切换、原ID重连与必要下游检查已通过；独立最终审核PASS，见[审核记录](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/最终独立结果审核.md)。

## 当前可用结果

[使用入口、安装命令及工程链接](../outputs/Bridge-plugin-entry-20261030/README.md) · [正式ZIP](../outputs/Bridge-plugin-entry-20261030/release-v0.2.3/bridge-vfx-agent-plugin-v0.2.3.zip) · [外部清单](../outputs/Bridge-plugin-entry-20261030/release-v0.2.3/release-manifest.json)。

默认没有connection.json也能握手并提供六个稳定工具：health、工程目录、显式选择、当前工程、原任务列表、原ID继续。工程由操作者明确登记到 `~/.local/share/bridge-vfx/projects.json`，选择属于当前MCP连接；断开重连须重新选择。原任务和产物仍在现有工程目录，消费者状态在包外私有目录。

| 工程 | 最终原任务 | 真实返回 | 主图SHA-256 |
| --- | --- | --- | --- |
| DiskLight | `creative_4023177d8ff79d0defa7` | COMPLETE，原主产物v4及HIP/NK/EXR/预览 | `fe039fca75078c582a34f77fad09bde2a41dda706af93c27c6c92f64666ea3ae` |
| RectLight | `creative_bff6f898fafe1db03aae` | COMPLETE，原主产物v2及HIP/NK/EXR/预览 | `a86b52dc0d2fd9132f026bf590b9ed28a6038f5f4e9e6635a370451dea624a22` |

“继续”不重放：完成则复核并返回原结果；运行中观察同ID；失败或未知阻断；错工程任务拒绝。图任务用只读数据库及既有状态投影，缺少只读宿主事实时明确阻断，不装配执行器或接管RUNNING。

## 真实验证

| 层次 | 本轮结果与证据 |
| --- | --- |
| 计划与源码审核 | [完整计划](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/完整计划.md)、[初审PASS](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/计划独立审核.md)；独立审查指出的问题均已修复并复审 |
| 改动点 | 入口16项、历史只读10项定向检查通过；覆盖空配置、选择隔离、错工程、身份漂移、原ID不重放、只读SQLite、消费者写入隔离、原全局/角色/阶段预算限制及实时超盘拒绝 |
| 正式包 | ZIP 3,364,564字节，SHA `482c0e4bd1798c3fc2a8619b663082542062680a7f5f3bbf2258effd9de008cd`；377登记文件，含内清单共378 ZIP成员，marketplace与官方安装缓存全部字节一致 |
| 官方安装 | 本机官方CLI `0.165.0-alpha.1.2` 安装和读取成功；实际停用→启用、卸载→重装成功，最终安装启用0.2.3；其他18个已安装插件与包外工程登记保持 |
| 实际加载 | 官方AppServer从 `~/.codex/plugins/cache/bridge-local/bridge-vfx/0.2.3` 加载；真实Python3.11.16，工具6个，空配置可用；不注入PYTHONPATH、PATH或BRIDGE_STATE_DIR |
| 断开与继续 | 两个真正独立的官方技术连接各自从未选择状态开始，分别切换两个工程并按原ID取得正式结果；两连接的原result和所有文件记录完全相同 |
| 必要下游 | 已安装真实核心从独立消费者的“第二轮未接收”状态接收RectLight原已完成结果，仅写消费者回执；原生产结果、原前端状态不变，不冒充新增DCC中断恢复 |
| 收尾 | 本轮技术AppServer和验收进程均退出；临时消费者副本、专用系统临时目录已清理。保留桌面宿主自己的正式插件服务及默认工程登记 |

[双官方消费者接续实证](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/双官方消费者接续验收0.2.3.json) · [前端结果补收](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/真实完成结果前端续接.json) · [官方启停重装](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/官方插件启停重装验收.json) · [重装后实际加载](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/官方最终重装后加载.json) · [安装字节核对](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/最终包与安装字节核对.json) · [收尾](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/收尾检查.json)。

复核完整历史签名链在本机DiskLight约7秒、RectLight约70秒；等待原调用返回，勿重复提交创建任务。

## 旧交付与记账更正

本轮0次Houdini/hython/husk/Nuke启动、0次模型推理，0次官方参考渲染和alpha校准。复用了现有工程、原正式产物和原验证事实。DiskLight原33票、RectLight后继家族50票均停止，没有新原生票据。

首次真实读取暴露旧验证器的副作用：它把后来增长的工程目录占用套回旧DiskLight范围，在原33票不变时追加seq15，将关闭原因写成 `NATIVE_SCOPE_DISK_EXHAUSTED`。原结果、工程和像素没有重跑或重写。

已独立审核后保全seq15的state/journal/anchor及从原journal找回的seq14完整签名状态，确认唯一业务差异为closed_reason、33票及收费/可信停止逐字段相同，再通过现有记账机制追加seq16更正。seq16业务状态等于原seq14；seq15和全部旧签名记录保留，不截断、不伪造原anchor、不新增密钥或预算。原state签名字节SHA `e0ad9b75337a215696cf510d2a13ed71e2e33ab00752c33bea74bd2afab76613` 已归档；活跃state现为新seq16，不能称原路径字节未变。

67项保护基线中66项逐字节保持，唯一变化为上述活跃记账更正。历史完成观察现只验签原记账、可信停止和原全局/角色/阶段额度，不刷新当前磁盘占用；普通worker和新执行仍走原实时预算门。

[保护核对](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/原交付最终保护核对.json) · [追加更正回执](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge插件入口-20261030/历史只读修复证据/追加更正回执.json)。

## 接收边界

本轮接收真实官方插件安装和AppServer API消费者入口；技术消费者对其他插件作进程内隔离，其他18项安装/启用配置保持不等于全插件并发兼容接收；桌面GUI点击层为NOT_RUN，未绕过宿主UI自动操作限制。未重新验收Houdini/Nuke原生链、WorkBuddy/HY3 UI、模型provider、人工美术、H22或全16域生产；这些维持各原报告边界。入口不授予自动重跑或任意宿主故障恢复权限。
