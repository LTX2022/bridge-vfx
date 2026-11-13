# DiskLight 常规入口与任务产物登记

日期：2026-10-28。范围：Houdini 21.0.631、Karma CPU、Nuke 17.0v1 的固定官方 DiskLight 单帧案例。

## 当前结果

**已完成本案例的常规入口接入、同任务工程接收、主产物登记和 Nuke 真实消费。**

[直接打开文件与使用说明](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/README.md) · [最终文件身份](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/delivery-manifest.json) · [执行结果](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/nuke-write-01/incremental-result.json)

| 项目 | 实际结果 |
|---|---|
| 任务 | `7c65a89096e84533b8f0ace596cfe1c2`；领域 `lighting_camera_render_v1@1.0.0` |
| GraphRun | `op_a43657769c4b87c428f9a275f2d867f7fcaaa5ac233d76cd0f7f15705f1467e6` 已成功接收；后续复用该完成结果，没有重新建图 |
| 保存工程 | 常规 `task_save` 生成 `scene-914bbf84b3aec0ec`，独立 Houdini 宿主冷开通过 |
| 主渲染 | Karma CPU 实际写出 `main.0001.exr`，完整 EXR 和受控输出验证通过 |
| 登记 | `disklight_incremental_main`，版本 1；Registry 可用 |
| Nuke | 按登记来源消费主图，保存 `composite.nk`，独立 Nuke 进程冷开并输出单帧 |
| 文件和格式 | 420×300、frame 1、RGBA HALF、ACEScg；NK 与冷渲染快照字节相同 |
| 图像对照 | 官方→Bridge、Bridge→Nuke，两段各 504000 个通道样本；差异样本数均为 0 |

人工视觉接收由用户观看决定。结果只覆盖上述固定配方、版本与第 1 帧。

## 常规源码入口

入口为 [continue_official_karma.py](/Users/user/Documents/Code_Project/Bridge/tools/continue_official_karma.py)，沿现有 `prepare_graph`、GraphRun、任务保存重开、产物 Registry 和 Nuke 接口执行。

- `prepare`：复用封存观测、模板、官方参考及 alpha，准备新的独立任务。
- `prepare-resume`：重验已成功 GraphRun，在同一任务中从宿主交接继续。
- `prepare-nuke-resume`：重验已经登记的主产物，只继续 Nuke 消费和写出。
- `run --preparation <绝对路径>`：只执行准备记录中列出的步骤；已有 INTENT 不自动重派发。

已有文件直接使用本文顶部入口。新执行使用准备命令返回的快照入口；不调用旧失败整链重做官方打开、参考渲染或 alpha 校准。

## 已接入的必要处理

- 认证完整官方参数模板，只为确有叶模板差异的相机、灯光和 payload 节点安装；保留匹配的原生文件夹布局。
- 恢复封存锁定状态、分辨率模式和 Ramp 实例通道，保持 1515 项参数及 USD 语义严格读回。
- 固定官方图使用有界原生建图阶段，保留图来源、围栏、日志和保存重开证明。
- 任务领域按正式配置登记，避免将照明任务归入默认烟雾领域。
- 启动就绪等待纳入已有宿主会话，实际映像观察仍限 16 秒；旧预算配置保持兼容。
- 续执行使用独立记账命名空间、唯一 successor 围栏和继承票据，保留旧失败及全部已耗时间。
- Nuke 写出先选择 EXR，再严格绑定颜色、RGBA 和完整继承元数据。
- 历史输入重验只读取已经成功且全体停止的来源，继续检查预算、生产者签名、EXR、原 Registry 实现与原事实一致性；不会把旧范围重新授权为可启动。

## 证据与验证边界

实际执行使用 `Bridge-disklight-integrated-20261028-08` 及其 `handoff-01`、`nuke-write-01` 续范围。同一任务族累计 8 次启动、279.420 记账秒，均有可信停止记录；其中保留一次早期 Hhost 启动失败和一次未完成 Nuke 写出准备的消耗。最终 Nuke 续段只新增 2 个 Nuke 进程，上游保存、冷开、渲染和登记全部复用。此前增量定位范围分别保留，不计作本任务族的成功运行。

定向检查位于仓库外：

- [模板、来源与 Nuke 续接检查](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight-entry-20261028/)
- [预算、启动窗口与命名空间检查](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight接入-20261028/)

旧官方 query2 失败回执、原工程、参考和 alpha 原件均保留。新增闭环不改写旧失败，也不代表全 16 域 M1、主动中断真实 worker 的恢复、HY3 创作闭环、跨机安装或生产接收完成。当前安装 ZIP 未重新构建，Git 未提交或推送。

内部 writer/filter/flush/close 和具体颜色处理器追踪保持原来的未观察边界；受控输出可用不将这些标为已证明。

共享交接原文已保存到 MemHub，可检索；提炼状态为等待模型。写入回执：`83448485-1e99-4d61-bb5d-c1854cc45d52`。

Nuke 输入账本的 start、reconnect 与部署记录已统一传递实际生产者账本，并补充目录、数据库存在性和符号链接拒绝检查。该最后修复通过定向数据流及缺失目录、缺失数据库、数据库符号链接拒绝检查，没有再次渲染。已完成运行继续以当时冻结快照、原启动文件、输入来源指针和回执为证；旧部署派生字段保留原样，详见[输入账本来源只读对照](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-DiskLight-entry-20261028/Nuke输入账本来源只读对照_20261028.md)。
