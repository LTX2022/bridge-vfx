# 特效行业 / 职业 / 学习资源杂记（学自用户笔记 三维基础.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\三维基础.md` 全文（约 2200 行）。
原始笔记保持只读；本文件是蒸馏版——行业术语、岗位分工、软件坐标朝向、
学习资源、简历作品集经验，供 houdini-bridge 回答行业类问题时查阅。

## 1. 行业术语速查

| 术语 | 含义 |
|---|---|
| SFX | 特殊效果/特技摄影（特摄）：用现实的东西实拍出不存在的东西（如模型模拟汽车爆炸）。真的炸一辆车不算特摄 |
| VFX | 视觉效果：拍摄完成后添加的改变画面的技术（调色、光线、光带都算）。CGI 包括 VFX 和 CFX |
| CGI | 计算机生成图像，一般指 3D：数字替身、场景建模、肌肉/流体/布料毛发模拟等（建模、动画、layout、特效、渲染、合成） |
| CFX | 后期特效 |
| CG | Computer Graphic，涵盖 2D 到 3D；实景 = 物理相机实际录制的内容 |
| DCC | Digital Content Creation：二维/三维、音视频剪辑合成、动态/互动内容、图像编辑 |
| LOD | 细节层次：对象对画面贡献越小，用越简单的版本 |
| AOVs | Arbitrary Output Variables，任意输出变量（渲染分层） |
| OpenFX (OFX) | 开放插件标准，让 PR/达芬奇/AE 等共用同一视觉效果插件 |
| HDRI | 高动态环境图（穹顶） |
| VES | 视觉效果学会 |
| MaterialX | 开放材质标准，2012 工业光魔推出，跨平台描述/交换材质 |
| OpenUSD | 高性能可扩展平台，格式涵盖几何体、着色、光照、物理 |
| Hydra | USD 的现代渲染架构：scene delegates + 渲染索引 + 渲染代理，擅长大场景和"更改处理" |
| `../../../` | 本级/上一级/上上级目录 |

## 2. 各种不同特效职业

- **视效指导/视效导演**：前期剧本创作就介入；负责画面把控、资产监修（有的另设资产总监）。
- 视效团队（The VFX team）：
  | 英文 | 中文 |
  |---|---|
  | Visual Effects Supervisor | 视效总监 |
  | Visual Effects Producer | 视效制片人 |
  | Visual Effects Production Coordinator | 视效制作统筹 |
  | Visual Effects Data Coordinator | 视效数据协调员 |
  | Visual Effects PA | 视效制片助理 |
  | Freelance Visual Effects Crew | 外聘视效人员 |
  | AD (Assistant Director) | 导演助理 |
  | Visual Effects DP | 视觉摄影导演 |
  | Blue/Green Screen DP | 蓝绿幕摄影导演 |
  | Motion Control Technician | 动作捕捉技师 |
  | Miniature Pyrotechnicians | 微型烟火师 |
- **视效总监**的职责（创意大脑 + 导演创意搭档）：
  - 创意面：保证视觉效果的创意性和连贯性；与导演完成故事板和视效预览；
    协助设计镜头、决定技术手段；没主演的镜头常兼副导演。
  - 执行面：组建团队；跟进监督所有镜头和盘带、片场随时候命；
    设计临时增加的视效镜头方案；配合剪辑团队。
- **（游戏）技术美术 TA** 技能栈：Python 基础 → DCC 脚本（Maya/Blender API、GUI）→
  引擎脚本（Unity C# / UE 蓝图或 C++）→ Shader（GLSL/HLSL、Shader Graph/Material Editor）→
  基本算法与数据结构。
- **TD（Technical Director）/ Pipeline TD**：
  - 数据 pipeline：各软件间数据的导入导出（CG 公司软件众多，数据平滑流动是关键）；
  - 流程 pipeline：项目进度运行（任务分配、提交、总监反馈、渲染农场管理、批量重命名）。
  - 技能：界面（Qt/HTML）、Python（各 CG 软件都有接口）、C++（底层数据导入导出）、
    Shell（远程渲染等终端命令）。
  - 学习入口：CG TD Pipeline 中文文档（cg-td-course.readthedocs.io）。
  - 观点：**Houdini 的 Procedural + Node-based 流程，对 Pipeline 客制化是绝对更好的选择**。
  - 飞书也算一种轻量 Pipeline（文件走飞书网盘）。

## 3. 不同软件坐标朝向（跨软件交接必查）

| 软件 | 前 | 上 |
|---|---|---|
| Maya | Z 轴 | Y 轴 |
| Blender | X 轴 | Z 轴 |
| Houdini | Z 轴 | Y 轴 |
| Nuke | Z 轴 | Y 轴 |
| UE | Y 轴 | Z 轴 |
| PFTrack | X 轴 | Y 轴 |

## 4. 模型经验

1. **生物建模必须全四边面**，三角面动画会变形。
2. 硬表面可以有三角面（规则运动、基本不形变，可用来表现结构）。
3. 三角面导致不好循环边，不利于卡线和分 UV（效率问题）。
4. 大部分模型保持四边面网格状，利于统一编辑计算；一堆四边面里冒一个三角面
   不好统计，也可能形变。

## 5. 学习资源与工具

- **基准测试**：Maxon Cinebench（免费测渲染性能；GPU 1 万分以下谨慎重度渲染）。
- **CG TD Pipeline 中文教程**：cg-td-course.readthedocs.io/zh-cn/latest/
- **迪士尼莫阿纳岛数据集**（disneyanimation.com/resources/moana-island-scene）：
  渲染《海洋奇缘》莫图努伊岛所需的一切，练渲染/管线的好素材。
- **VFX 参考平台**（vfxplatform.com）：行业统一的工具/库版本目标平台，
  减少软件包不兼容，鼓励 Linux。
- **PBR 学习**：PBR 白皮书（QianMo/PBR-White-Paper）、
  腾讯 ISUX《The PBR Guide》、Chaos 官方 PBR 完整指南。
- 小众/实用软件：
  | 工具 | 用途 |
  |---|---|
  | Excalidraw | 开源画布，画思路 |
  | usdview | USD 资产快速浏览 |
  | Autograph (Maxon) | 带三维集成的合成软件，个人免费，支持 USD，可平替 AE；搭 Google Filament 实时渲染 |
  | Animcraft | 可协作角色动画效率软件 |
  | PTGui | 全景图拼接 |
  | QuiltiX | 编辑 MaterialX 材质，支持 Hydra 渲染器预览 |
  | Figma | 浏览器协作 UI 设计 |

## 6. 动作捕捉（mocap）

- **SysMocap**（github.com/xianfei/SysMocap）：本科毕设作品，轻量动捕。
- **Uthana**：AI 3D 角色动画生成平台。

## 7. FluidX3D（博士自研开源流体）

- github.com/ProjectPhysX/FluidX3D；GPU 编程实现，**不挑硬件，8K 水飞溅模拟只要 8 小时**。
- 截图见原笔记 QQ20241212-171103。

## 8. AI 结合特效

- **AI 绿幕 EZ-CorridorKey**：github.com/nikopueringer/CorridorKey
  （下载在 gumroad：edenaion.gumroad.com）。

## 9. 简历与作品集（用户经验）

### 简历不要做

- **堆量不聚焦**：练手小效果别全塞，针对性放岗位相关作品
  （特效岗突出流体/粒子，建模岗侧重拓扑细节）。
- **缺过程缺思路**：只放成品像炫技；加 2 句节点逻辑或创作思路
  （如"用 VEX 优化了烟雾缓存效率"）立刻显专业。

### 正确做法

- 1 个完整项目（带前后对比）+ 2 个技术亮点（附节点截图）+ 简洁说明（不超过 3 行）。
- **宁愿 3 个精致小案例，不要 10 个潦草大杂烩**。

### 作品集核心原则

1. 以本人参与项目经历设置案例，是工作经验的总结。
2. 目标导向：展示在标准化产业链中如何胜任岗位，研究成功大 IP 案例；
   模仿与对标——对标国内优秀电影，挖掘与好莱坞同类型场景气氛的美学共性。
3. 不搞个人风格探索，不追网络流行。
4. 展示创作过程而不只是结果；质量 > 数量。
5. 主流卖座商业电影涵盖的元素方向：**战争/浩劫、军事、废墟、科幻感**。

## 易错点

1. 跨软件导模型不看坐标朝向 → FBX 容易在 Maya(Z 前)/Blender(X 前)/UE(Y 前) 之间丢信息、
   朝向错乱；交接前先核对上表。
2. 生物角色模型带三角面 → 动画一形变就穿帮；生物必须全四边面。
3. 简历堆 10 个练手效果 → 不如 1 完整项目 + 2 技术亮点 + 3 行说明。
4. 作品集追个人风格/网络流行 → 商业产业链看的是目标导向和对标能力。
5. 把 SFX 和 VFX 混用：真炸车是实拍不是特摄；后期加的任何画面改动才是 VFX。
