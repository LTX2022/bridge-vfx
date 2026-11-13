# Luna低思考正常使用验收结果

日期：2026-11-04。状态：**首试PASS，计划与最终结果独立审核PASS，本阶段完成。**

实际gpt-6-luna / low采用无实施历史的冷上下文，通过透明转发到官方AppServer的已安装Bridge VFX 0.4.10 MCP，独立完成双宿主认证、Geometry Gate显式选择、原任务查询、两版工程取得及学习观看图发现。主agent仅装配受限测试传输、关闭技术Host和记录证据，没有代替模型选择工程、查询任务或填入工程答案。

## 可以直接使用

- [两版HIP、NK和EXR](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-geometry-creative-20261030-01/README.md)
- [已确认的两版学习观看图](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-visual-delivery-20261104/README.md)
- [最终独立验收](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/最终独立验收.md)

原任务仍为COMPLETE / revision 2；两次查询返回rev1/rev2的accepted_immutable历史观察，文件、结果及accepted与原交付一致。选择工程不代表已加载HIP；本次未新做保存、冷开或消费性验证，既有工程验证继续复用。

## 实际计量

| 项目 | 结果 |
| --- | --- |
| Luna测试 | 1次，gpt-6-luna / low，fork none；provider unknown |
| Bridge工具/schema/raw | 9 / 2 / 11；独立于旧任务账 |
| 新原生宿主 | H1 / N1，合计2次；无备用组或复试 |
| 原生实际记账时间 | 240.075544宿主秒，低于480总上限 |
| 工具RPC等待合计 | 61.902秒；两次continue约20.152/22.007秒 |
| 生产源码/安装包修改 | 0，无需重建插件 |
| 新保存/冷开/渲染/校准 | 0，复用已有结果 |
| 原件保护 | 30个本轮受保护文件摘要一致；原17票及正式接收不变 |

连接标识为`connection-f25abf056d534ed7ba212000f25398e4`。Houdini21.0.631 PID81186、Nuke17.0v1 PID81237均曾真实认证CONNECTED。

实际顺序是：认证后查询两版原结果，两个后台宿主达到原120秒期限，由监督器可信停止；随后Luna显式bridge_disconnect返回DISCONNECTED。未续期、未重启，也未验证“认证后立即主动断开”。stopped回执为owned_child_wait、原生退出-15、TIME_BUDGET_EXCEEDED、监督器退出0，不把它写成原生正常退出0。独审依据等价顺序条款接收该有限结果。

官方技术AppServer PID80030另行关闭并wait退出0，转发器父进程退出0，自有原生及监督进程已停止。

## 验收边界

本次证明当前插件的公开MCP能力能被新的Luna低思考agent独立使用，取得当前已有交付。它不扩展为新创作、实际HIP加载、WorkBuddy/HY3原生UI、H22、跨域或全16域验收。学习观看图沿用用户既有确认；噪点保留、工程照明未修改。

## 证据

[冷输入](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/cold-agent-input.md) · [Luna实际回复](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/cold-agent-result.md) · [定向核对](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/normal-use-verification.json) · [计划审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/计划独立审核.md) · [测试传输补审](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge-Luna正常使用验收-20261104/测试传输适配补充审核.md)

原始请求/响应、分类计量和停止回执定位保留在本轮文档目录；没有复制工程、渲染或原素材。
