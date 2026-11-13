# Luna低思考跨官方案例结果：RectLight

结论：有限跨案例真实创作闭环已完成，独立验收PASS。实际模型配置为gpt-6-luna / low，路线为Codex委派受限stdio MCP；provider身份unknown，人工美术接收待确认。

[直接打开最终HIP、NK和预览](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/luna-rectlight-01/README.md) · [完整计划](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna跨案例-RectLight-20261029/完整计划.md) · [最终独立审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna跨案例-RectLight-20261029/最终独立结果审核.md) · [真实技术证据](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna跨案例-RectLight-20261029/完整真实技术验收.json)

## 实际结果

| 阶段 | 曝光 | 主版本 | 主图→Nuke逐通道样本不同数 | 相对上一图不同数 |
| --- | ---: | ---: | ---: | ---: |
| 首轮 | -0.5 | 1 | 0 / 504000 | 152943 |
| 修订 | -0.25 | 2 | 0 / 504000 | 152322 |

官方Rect参考→Bridge起始基线同样504000样本零差异。两轮HIP均真实保存、独立宿主无警告冷开并读回曝光，Karma实际渲染，Rect专属账本主v1/v2依次登记，Nuke输入合同精确绑定各自版本并冷渲染。v1为历史版本，v2是当前主版本；最终文件身份、HALF RGBA、420×300和lin_ap1核对通过。实际模型session配置、媒体传输、图片块及两轮自主计划均有收据。

## 官方来源与执行边界

源为已安装SideFX H21 Karma User Guide Lights教程中的RectLight：switch3 input0、render_rectlight、唯一USD /World/UsdLuxRectLight；完整灯光参数、宽高0.9、radius0.5及共同上游已与官方原生观察对应。复用既有GraphRun几何、工程和同版alpha；新Rect参考是该分支必要基线，没有重跑旧Disk参考、alpha或正式全链。源工程与旧Disk v4交付保持。

本阶段共17次启动、1320.860累计记账秒，有效限额17次/1800秒，固定磁盘上限640 MiB；家族累计50次全部有可信停止记录，当前槽释放。首轮Nuke启动前的上下文错误已由可信控制入口按真实未启动证据收束，旧失败和13步检查点保留，仅补Nuke一次，未重跑H/Karma/主v1。第二轮从已落盘但未完成正式回执的检查点另存新正式HIP，再独立冷开；旧INTENT保持。零原生磁盘拒绝保留，新执行使用一次固定640 MiB修订，其后唯一额外Nuke重试将有效阶段上限修订为17、家族50，时间和磁盘保持。原生同步渲染的签名COMPLETED及帧快照早于控制宿主TIME；尾部只受控验图、正常登记；49号Nuke的TIME/FAILED与产物保留，性能修复后只追加50号正常冷消费，宿主rc-15、writer独立退出码未观测和原native BLOCKED均保持，不声称独立husk rc0。[必要续接审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna跨案例-RectLight-20261029/Nuke必要续接独立审核.md)。

接收只覆盖共用上游的DiskLight和RectLight两个官方灯光分支，以及两轮曝光创作、保存/冷开/渲染/登记/Nuke闭环；不是跨领域、从空场景建图、HY3 UI、H22、全16域或生产接收。人工审美PENDING。
