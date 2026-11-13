# 渲染农场 / 素材管理 / 交付规范（学自用户笔记 三维基础.md, 2026-08-25）

来源：`C:\Users\<USERNAME>\OneDrive\Node\Node\3D\三维基础.md` 全文（约 2200 行）。
原始笔记保持只读；本文件是蒸馏版——把 Deadline / HQueue 实操参数、共享文件夹组网、
格式速查、交付规范写进来，供 houdini-bridge 提交渲染/整理交付时查阅。
所有"截图见原笔记"处对应原笔记 `./图片/` 下的截图。

## 1. Deadline 架构与安装

- AWS Thinkbox 出品，3 个基本部分：**Deadline 数据库（MongoDB）→ 仓库（Repository，先装）→ 客户端（Client，后装）**。
- MongoDB 下载时选 `zip` 包，Deadline 安装时可直接引用。
  **Deadline 10.3.2.1 对应 MongoDB 5.0.22**（`fastdl.mongodb.org/windows/mongodb-windows-x86_64-5.0.22.zip`）。
- 官网下载需注册 AWS 账号（个人注册要国际信用卡）；国内可从第三方镜像拿安装包合集。
- 三大常驻程序：
  - `Deadline Monitor`：查看/管理渲染任务（左作业 Job，右任务 Worker）。
  - `Deadline Worker`：本机性能与正在执行的任务。
  - `Deadline Pulse`（`deadlinepulse.exe`）：保护机制（防内存过曝等）；**远程控制必须开启 Pulse**。

### 安装步骤（单机）

1. 装 `DeadlineRepository`：全程默认；**勾选 `Set full read/write access for files for all users`**
   （为所有用户开读写权限）；让它自己下载 MongoDB（避免版本不匹配，无梯子时约半小时）。
2. 装 `DeadlineClient`：同样勾选 full read/write access；安装类型选 **Client**；
   连接方式选**本地文件夹连接**；开机自启 Worker 按需。

### 服务器集中式部署的 3 个坑

1. **安装路径必须是共享路径**——装在 D 盘的话，另一台电脑开客户端连不上数据库。
2. 客户端打不开 Deadline 多半是缺 `.net` 库，**装一遍 Maya 通常就能解决**。
3. 报 `deadline.ini` 找不到：把 `ThinkboxDeadline10\bin\deadline.ini`
   拷到 `C:\ProgramData\Thinkbox\Deadline10\`。

## 2. Deadline 插件安装（Houdini / Nuke / Ae / Blender）

插件安装包统一在 `C:\DeadlineRepository10\submission\<软件>\Installers\` 下，
双击对应平台的 installer 即可。版本列表里没有当前版本时选最高版本。

### Houdini 插件（最高价值，必做 2 步修改）

1. **Python 版本对齐**：进入 `C:\ProgramData\Thinkbox\Deadline10\submitters\Houdini`，
   把 `python3.9libs` 复制一份并改名为当前 Houdini 的 python 版本
   （如 `python3.11libs`）。看哪个版本：查
   `C:\Program Files\Side Effects Software\Houdini 21.0.512\houdini\python3.11libs`。
   mac 路径：`/Users/Shared/Thinkbox/Deadline10/submitters/Houdini`。
2. **改 `Houdini.param`**：`C:/DeadlineRepository10/plugins/Houdini/Houdini.param`，
   把 `[Houdini19_5_Hython_Executable]`（约 154~161 行）和 `[Houdini19_5_SimTracker]`
   （约 250 行）两个代码块各复制一份到下方，改成当前版本的路径
   （截图见原笔记 QQ20241026-182943/1829143）。mac 路径形如：
   - `.../Houdini.framework/Versions/21.0/Resources/bin/hython`
   - `.../Houdini.framework/Versions/21.0/Resources/houdini/python3.11libs/simtracker.py`
3. 验证：`Deadline Monitor → Tools → Power User Mode（超级管理员）→ Configure Plugins...`，
   看插件配置里有没有这 2 个路径，然后试提交。

### Nuke 插件

- submission 文件夹安装，选 `Bundled Files`，环境变量选"为所有用户添加"。
- 同样要改 `C:\DeadlineRepository10\plugins\Nuke\Nuke.param`（方法同 Houdini）。

### Blender 插件

- 需要 `Submit Blender To Deadline` 辅助插件；报错时把 `DeadlineBlenderClient.py`
  拷到 Blender 脚本/插件目录。
- `Tools → Power User Mode → Configure Plugins...` 里填 Blender 安装目录（多版本填多个）。

## 3. Deadline 提交参数速查

### 通用参数

| 参数 | 含义 / 经验 |
|---|---|
| `Priority` | 0~100，越大越优先 |
| `Pool / Group` | 作业所属机器池/组 |
| `Task Timeout` | Worker 渲染单任务超时分钟数，0 = 不限 |
| `Auto Task Timeout` | 按前几帧渲染时间自动算超时（需在 Repository Options 配置） |
| `Concurrent Tasks` | 单 Worker 并发任务数；单线程渲染器+多核 CPU 有用，吃 RAM 的任务慎用 |
| `Machine Limit` | 同时渲染的最大 Worker 数，0 = 不限；配 Allow/Deny List 圈定机器 |
| `Dependencies` | 指定作业完成后才启动本作业 |
| `Submit Job As Suspended` | 挂起提交，Monitor 里手动恢复 |
| `Frame List` | 帧范围；支持 `1-100by10,1-100`（先每 10 帧渲 1 帧做预览，再补全；已渲帧不重复） |
| `Frames Per Task`（Chunk Size） | **每个 Worker 一轮任务处理多少帧**（官方定义，AWS Thinkbox Deadline 10.2 User Manual 原文：'This is the number of frames that will be rendered at a time, for each job task'）。官方建议：单帧渲染超过几分钟就保持 1；增大可摊薄网络渲染的启动开销 |
| `Submit Scene File With Job` | 场景文件随作业提交并拷到 Worker 本地。**用相对资源路径时必须禁用**（否则路径解析失败）；禁用则文件必须在共享位置。注意：不禁用时修改原文件会影响渲染作业 |

### Houdini 提交（重点实操）

- Out 环境下渲染器正常设置 → Deadline 节点设好时间线 → `Submit To Deadline`。
  也可用顶部菜单 `Submit Houdini To Deadline`（可选选中 ROP 或全部 ROP）。
- 关键参数：
  - `ROP To Render`：`Choose`（下拉选）/ `Selected`（当前选中，按选择顺序）/ `All`。
  - `Ignore Inputs`：只渲选定 ROP，不渲依赖项。
  - `Ignore Bypassed Nodes`：跳过旁路 ROP。
  - `Automatically Create Dependencies`：多 ROP 提交时把依赖关系映射成 Deadline 作业依赖。
  - `Jobs are Frame Dependent`：帧级依赖（依赖作业渲完某帧，本作业就渲该帧）。
  - `Submit Wedges as Separate Jobs`：每个 wedge 单独成作业。
- **Frames Per Task 经验**：单设备 200 帧设 40 → 后台只启动 5 次 Houdini；
  设 1 则每帧都重启 Houdini，极慢。**单设备时 Frames Per Task ≈ 总帧数**。
- **通定义 vs 特例（2026-08-25 官方文档核对后补充）**：
  - **通定义**（官方）：Frames Per Task = **每个 Worker 一轮任务处理多少帧**。
    例如总帧数 100、Frames Per Task = 10 → 分成 10 个任务，每个 Worker 一轮干 10 帧。
    官方建议：单帧渲染超过几分钟就保持 1；增大可摊薄启动开销。
  - **特例——逐帧依赖的模拟缓存**：第 N 帧依赖第 N-1 帧的结果（如 Pyro/FLIP 模拟缓存），
    如果 Frames Per Task < 总帧数，每个新任务都得从头模拟才能拿到正确初始状态，
    时间爆炸。此时 **Frames Per Task 必须 = 时间线全长**（一轮模拟完所有帧）。
  - **帧间独立的缓存**（如静态模型序列、渲染帧）可设 1 并多机并行。
- Solaris/Karma 三个坑：
  1. Deadline 读不了 `reference` 节点引用的 usd 路径 → **改用 `sublayer` 节点**。
  2. `Karma Render Settings` 的路径映射不对 → 在 `Usd Render ROP` 的
     **`Override Output Image`** 参数里直接填输出序列路径。
  3. 相对路径经常识别出错 → **一律用绝对路径**。
- 报错 `No module named 'CallDeadlineCommand'`：把服务端
  `submission/Houdini/Client/CallDeadlineCommand.py` 拷到客户端
  `C:\ProgramData\Thinkbox\Deadline10\submitters\Houdini\python3.10libs\`
  （python 版本文件夹按实际建）。

### Nuke 提交

- 顶部菜单 `Thinkbox → Submit Nuke To Deadline`。
- **Write 节点必须用 Nuke 自带的**，第三方 Write 插件会导致读取不到节点信息。
- 多 Write 节点策略（互斥选项，按需求选）：
  - `Submit Write Nodes As Separate Jobs`：每个 Write 单独成作业；
    配 `Use Node's Frame List`（用各 Write 自身帧范围）和
    `Set Dependencies Based on Write Node Render Order`（按渲染顺序建依赖）。
  - `Submit Write Nodes As Separate Tasks For The Same Job`：一个作业、每任务一个 Write。
- 性能参数：`Use Batch Mode`（任务间保持 Nuke 驻留内存）、
  `Render Threads = 0`（自动）、`Maximum RAM Usage`、`Reload Plugin Between Tasks`
  （任务间重启 Nuke，刷新内存但增开销）、`Continue On Error`。
- Precomp：`Render Precomp Nodes First` / `Only Render Precomp Nodes`。

### Blender 提交

- 菜单 `渲染 → Submit To Deadline`；填 `Blender File` 与 `Output File(Optional)`。

### Pools（机器分组）

`Tools → Power User Mode → Manage Pools → New` 建组 → 选中机器 `Add` 进组；
提交时用 `Pool` 选组即可定向渲染。

## 4. 多机器渲染 / 组网（Deadline 农场）

### 硬性前提

- 只需一台主机装 `DeadlineRepository`，其余装 `DeadlineClient`。
- **软件版本和插件必须完全一致**（含 Houdini 安装路径一致）。
- 两台电脑的**用户名和计算机名必须不同**（否则识别为一台）。
- 所有设备能互访，且**所有资产/工程/贴图都在共享文件夹里**——否则渲染机访问不到。
- 服务端安装：Repository 装到共享文件夹（如 NAS），但**数据库必须装本地存储，
  不要装到 NAS/网络驱动器，安装后也不要共享数据库目录**。
- 客户端安装：不用远程连接服务器，**用文件系统直连存储库**；关掉自动升级。
- 不勾选 `Require client authentication via SSL/TLS`（需要时可后配）。

### 连接排错（`Set Repository`）

- `Connection Type` = `Direct Connection`；
- `Repository Path` = 共享盘 `\DeadlineRepository10`；
- 勾选 `Database requires Client Certificate`，证书选共享盘
  `\DeadlineDatabase10\certs\Deadline10Client.pfx`；
- **`Deadline10Client.pfx` 要右键 → 属性 → 安全 → 给 `Everyone` 全部权限**，
  网络盘才访问得到；
- 打开软件后底部 2 个路径都是网络路径即成功。

### 多机互联方法

- Windows 共享文件夹：高级共享 + 权限全开；最实用的访问方式是直接输 UNC 路径
  `\\计算机名\共享名`（如 `\\Ltx\big jim2`）；可把网络盘映射为本地盘。
- 静态 IPv4 要用**公共网络**配置文件；静态地址过段时间可能断网。
- "输入网络凭据"：输目标机的用户名+开机密码。免密方案：
  1. 目标机设密码；
  2. 家庭版 Windows 无组策略编辑器，先用 bat 装 `gpedit.msc`（原笔记有完整 bat，
     核心：`dism /online /norestart /add-package` 安装 GroupPolicy 包），
     再 `Win+R → gpedit.msc` 改本地组策略，之后只用用户名即可登录。
- 虚拟组网（异地设备进同一局域网）：
  | 工具 | 额度 | 备注 |
  |---|---|---|
  | Tailscale | 3 用户 / 100 设备 | 登录同账号即成局域网，最推荐 |
  | ZeroTier | 1 管理员 / 10 设备 | 需官网注册 |
  | SoftEther VPN | — | 要自组服务器，个人不推荐 |
  | Everything HTTP 服务器 | — | 临时文件访问 |
  | IIS FTP | — | 只能传文件，不推荐 |

## 5. HQueue（Houdini 自家农场）

- 官方手册：`sidefx.com/docs/houdini/hqueue`。装好后客户端页面：
  **`http://localhost:5000/clients/`**。
- 架构：HQueue Server 接作业 → 分发给 client 场；渲染由 Output Driver 指定节点执行。
- 服务器端只装 `HQueue Server`；有共享文件夹时选对应选项。
- `hqserver.ini` 实测配置（关键项）：

```ini
[main]
port = 5000
scheduling_algorithm = sharecpu
active_timeout = 3
expire_jobs_days = 10
max_fails_allowed = 5
upgrade_priority = 100
max_active_jobs = -1   # 手动增加这一行（不限并发作业数）

[logging]
file = %(here)s/hqserver.log
level = INFO
max_file_size = 10
max_backup_files = 5
```

- Windows 注册为服务（**管理员 cmd**）：
  `sc create HQueueClient binPath= "C:\HQueueClient\hqclientd.bat" start= auto`
- 用户踩坑结论：**配了 NAS 之后本地成功的方法全失效，HQueue 最好纯本地执行**。
  要农场还是优先 Deadline。

### Deadline vs HQueue 速选

| 维度 | Deadline | HQueue |
|---|---|---|
| 跨 DCC | Houdini/Maya/Nuke/Blender/Ae/3dsMax 等全支持 | 基本只服务 Houdini |
| 数据库 | MongoDB，装本地别装 NAS | 无外部数据库 |
| Web 监控 | Monitor 桌面程序 | `localhost:5000` 网页 |
| 多机踩坑 | 版本/路径/共享/证书权限 | 配 NAS 后大量失效，建议单机本地 |
| 结论 | 正经农场首选 | 单机多任务分发可用 |

## 6. 格式速查

### 模型/场景格式

| 格式 | 内容 | 备注 |
|---|---|---|
| OBJ | 顶点、顶点色、法线的 txt | 无动画；导出附带 `mtl` 存材质纹理 |
| FBX | 顶点、多 UV 集、骨骼、变形、材质、贴图、单位、灯光、摄像机 | Autodesk 垄断、算法不公开，跨软件易丢信息（坐标朝向等） |
| Alembic (abc) | 缓存 | 动画/镜头交接主力 |
| USD | 几何、着色、光照、物理 | 新标准；Hydra 是其渲染架构 |
| KN5 | 赛车模拟赛道格式 | 由 FBX 经 ac 编辑器导出；**只有 KN5 改不了模型**（类比 jpg 改不了 PSD） |

### 序列图格式（为什么用序列图：视频要解码，序列图用最小硬件资源逐帧处理）

| 格式 | 特点 |
|---|---|
| JPEG | 有损、压缩率最高、有失真 |
| PNG | 无损、带 alpha；灰度 16 位、彩色 48 位 + 16 位 alpha |
| TIFF | 灵活位图，多色彩位/多色彩模式，体积大 |
| DPX | 胶片扫描的对数空间位图，保留阴影动态范围；正被 EXR 取代 |
| EXR (OpenEXR) | 开放 HDR 标准，最多 1024 通道，16F/32F/32int，现行交付主力 |

### 贴图位深

- 整数型：8bit = 256 灰阶（易色阶断层）；16bit = 65536 灰阶；都被锁在 0~1。
- 浮点型：16-bit Half / 32-bit Float，可存 >1.0 和负值；**普通 16 位比 Half 精确 32 倍**，
  但 Half 能存超范围值；浮点越接近 0 越精确（指数分布，截图见原笔记）。
- 选型经验：
  - **置换（Displacement）：8bit 和 16bit Half 都不行**，用常规 16bit 或 32bit Float。
  - 颜色/粗糙度等：不超过 0~1，常规位深够用，不需要 32F。
  - 兼容坑：Substance 不支持 16bit Half，EXR 不支持常规 16bit。

## 7. 交付规范（乙方特效师视角）

### 命名

- 工程命名：**项目名 + 镜头号 + 制作内容 + 工种 + 版本号**
  - 特效：`XXX_Shot0180a_snow_vfx_v001.hip`
  - 合成：`XXX_Shot0180a_snow_comp_v001.nk`
  - 渲染预览：`XXX_Shot0180a_snow_vfx_v001.mov`
  - 灯光例：`YJ-YJCG_shot01_Lgt_v01`
- 工程文件夹约定：
  | 文件夹 | 放什么 |
  |---|---|
  | `abc` | 上游给的镜头/模型/动画，命名 `镜头号_内容_帧范围`（如 `shot01_cam_1001-1100`） |
  | `check` | 上游交付文件的拍屏，导入 Houdini 核对 |
  | `geo` | 缓存文件 |
  | `render` | 渲染序列 |
- 提交资产：`日期` 文件夹 → `镜头号` 文件（按日期提交，对面最清晰）。

### 工程文件交不交（商业考量）

- 不涉及自研工具/自用代码/特殊方案：常规工程提交没问题。
- 涉及时 3 个选项：
  1. 不予提交或部分提交（看技术稀缺性）；
  2. **优化后再交**——自用工具部分用缓存/烘焙只保留结果、不保留工具本身；
  3. 把工程文件价值计入报价。
- 核心逻辑：**特效团队的优势 = 技术积累，而积累直接体现在工程文件里**；
  甲方要存档/验流程也有合理性。在公司上班则无此纠结——产出归公司。

## 8. 杂项运维

### 下载文件被 Windows 系统删除

- 还原：`设置 → 隐私和安全性 → Windows 安全中心 → 病毒和威胁防护 → 保护历史记录`，
  在被隔离项里选中被删软件 → 还原（截图见原笔记）。
- 压缩包每次被杀：进"病毒和威胁防护"的 `管理设置` → **关实时保护**（用完记得开回）。

### Breakdown（VFX 分解视频）

- 定位：宣传物料，用冻结/放大/分解手法逐层揭示镜头构成。
- 批判视角：它强化"无痕合成"印象，却抹除了错误、算法偏差、渲染时间等"隐形劳动"，
  营造计算机自主快速生成的幻象——做 breakdown 时可自觉对抗这种表面化。

### 设备 / GPU 渲染管线（常识速记）

- 3 步：顶点着色 → 光栅化 → 片段着色；遮挡用 Z 缓冲区（深度小者胜出）；
  斜切像素边缘锯齿用超级采样抗锯齿（SSAA）。
- 3D→2D 三次转换：模型空间 → 世界空间 → 相机空间 → 透视到视图屏幕（矩阵相乘）。
- 性能自测：Maxon Cinebench；**GPU 1 万分以下谨慎用于重度渲染**。

## 9. 素材管理 / Pipeline 软件

- 素材管理：**Eagle**（视频图片）、**Pixcall**（全文件、多端协作）、
  **Kiosk**（纹理/模型/HDRI 可视化库，可导出进 Blender/Houdini/Maya/C4D 且材质已连线）。
- Pipeline 系统：
  | 软件 | 定位 |
  |---|---|
  | CGTeamwork | 国内 CG 行业最常用；项目/文件/流程/审片一体，绑百度网盘企业版，960 元/人/年（62 人以下） |
  | Prism Pipeline | 开源，自动处理格式/目录/命名；插件下不动就去 GitHub 仓库手动拿 |
  | ShotGrid | Autodesk Flow Production Tracking，版本跟踪/排期/监修 |
  | ftrack | 云端镜头管理+媒体审阅（类分秒帧） |
  | stock_manager | 开源 Nuke 素材管理 |
- 用户经验：MoreRealistic Personal Pipeline 不好用，且**会影响 Deadline 提交项目**。
- Multishot 工作流：单个 hip 文件含多个镜头，比每镜头一个 hip 更适合单人艺术家。

## 易错点

1. **Deadline 数据库装到 NAS 上** → 必须装本地存储，且不要共享数据库目录；
   Repository 才放共享盘。
2. Houdini 插件忘记把 `python3.9libs` 复制改名成当前版本（如 `python3.11libs`），
   或忘记改 `Houdini.param` 里的 `Hython_Executable` / `SimTracker` 两段 → 提交即失败。
3. `Deadline10Client.pfx` 没给 `Everyone` 权限 → 网络盘读不到证书，客户端连不上库。
4. 场景文件用了相对资源路径还勾 `Submit Scene File With Job` → 渲染失败；必须禁用。
5. 逐帧依赖的模拟缓存把 `Frames Per Task` 设小了 → 每个任务从头模拟，时间爆炸。
   **注意区分通定义**（每个 Worker 一轮处理多少帧，官方定义）和**特例**（逐帧依赖的模拟缓存必须 = 时间线全长）。
6. 两台电脑用户名/计算机名相同 → Deadline 识别为一台设备。
7. 资产不在共享文件夹 → 渲染机访问不到直接报错；所有贴图/缓存/工程必须先进共享盘。
8. Solaris 里用 `reference` 节点引 USD → Deadline 读不到路径，换 `sublayer`；
   Karma 输出路径映射不对时在 `Usd Render ROP` 的 `Override Output Image` 里写绝对路径。
9. Nuke 提交用了第三方 Write 插件 → 读不到节点信息，必须用自带 Write。
10. 静态 IP 设在"专用网络"配置文件上、或路由器 IP 漂移 → 互访失败；用公共网络，
    必要时路由器把 IP 和 MAC 绑定。
