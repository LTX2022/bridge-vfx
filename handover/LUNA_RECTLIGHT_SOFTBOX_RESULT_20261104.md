# Luna 低思考：RectLight 等面积软箱创作交付

日期：2026-11-04。状态：**COMPLETE / revision 2；独立实际技术验收 PASS；用户接受最终学习观看图。**

[直接打开两版 HIP、NK、EXR 和预览](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-rectlight-softbox-20261104-01/README.md) · [独立最终验收](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方RectLight新目标创作-20261104/最终独立验收.md) · [真实结果和累计用量](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方RectLight新目标创作-20261104/final-real-delivery-evidence.json)

## 最终作品

同一 gpt-6-luna／low 会话通过任务隔离的正式 Bridge 0.4.11 stdio MCP，自主完成两轮不同目标参数：

| 版本 | Width × Height | 比例 | 面积 | 曝光 |
| --- | --- | --- | --- | --- |
| 1 | 1.35 × 0.6 | 2.25:1 | 0.81 | -0.25 |
| 2 | 1.62 × 0.5 | 3.24:1 | 0.81 | -0.25 |

第二轮来自真实首轮图上的“更横向、更薄”定性反馈。两次参数均由 Luna 选择，主 agent 未给第二组数值。模型按配置路由留证，provider 身份仍为 unknown。

两版 HIP 均真实保存并在独立 Houdini 中冷开；Karma 单帧和主产物 v1/v2 分别登记，Nuke 独立冷输出确切消费对应主版本。两版各 504,000 个 RGBA 样本 Karma→Nuke 零差，格式420×300、RGBA HALF、ACEScg／lin_ap1。基线→首版 134,609 个样本变化；首版→第二版 118,524 个样本变化，属于本目标预期真实差异。

用户明确回复：“接受，作为学习观看交付”。该确认适用于本次最终学习观看图，原官方案例及其它作品的美术状态保持。

## 实际验收和用量

- 全轮 11 次 Native，H7／husk2／Nuke2，累计498.1363046宿主秒。包含3次前置失败Houdini消耗128.822485秒，未清零；最终正常阶段8次、369.313820秒。
- 原12次／1800秒总额未增加；分项经独审明确调剂并收紧为11次／H7+husk2+Nuke2。单角色120秒、一个重操作及1GiB保持。
- 实际76工具／6schema／82raw，低于80／10／90；所有失败和候选切换计数保留。6个技术MCP连接及全部11份Native启动/停止均有正常退出记录。
- 原来源、sidecar、校准、原任务数据库和全局三个登记工程保持。官方参考、alpha与原正式链均复用。
- [清理回执](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方RectLight新目标创作-20261104/cleanup-receipt.json)：本轮软件fixture已清，自有异步控制器和MCP无存活进程；正式文件及必要失败/审计记录保留。

## 使用入口与当前范围

[可复用MCP配置](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-rectlight-softbox-20261104-01/mcp-rectlight-softbox.json)列出私有工程 `rectlight-softbox`。当前任务 `luna_rectlight_softbox_20261104_01`，当前第二版operation为 `rshape_73cdac9a8a587a7ca28e071a`。新agent可选该工程后查询既有任务，无需新开DCC、参考或校准。

本次使用隔离的正式0.4.11包；全局安装仍为0.4.10，旧三个登记工程保持。此结果是同一已认证官方RectLight的新目标创作，不扩大为新光型、HY3界面、H22或全16域验收。

[学习文件清单](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-rectlight-softbox-20261104-01/delivery-manifest.json) · [Luna与真实反馈证据](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna官方RectLight新目标创作-20261104/Luna创作与实际反馈记录.md) · [已审原计划](/Users/user/Documents/Code_Project/Bridge/handover/Luna官方RectLight等面积软箱创作计划-20261104.md)
