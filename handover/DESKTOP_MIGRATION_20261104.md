# 桌面历史目录整理结果

三个目录均有历史用途，已迁移需要的信息并清理桌面原目录；当前主工作区为 /Users/user/Documents/Code_Project/Bridge。

当前唯一主工作目录：[Bridge](/Users/user/Documents/Code_Project/Bridge)。此目录保存历史原件和旧GUI插件的兼容依赖，不作为当前开发工作区。旧文档中的安装、执行和审核指令属于历史资料，以主项目最新约定为准。

| 原桌面目录 | 保留用途与位置 |
| --- | --- |
| Bridge-S06原生定义补采 | 独有阶段包及原始审计归档在[同名目录](/Users/user/Documents/Code_Project/Bridge/outputs/desktop-legacy-20261104/Bridge-S06原生定义补采)；34份同字节重复文件保留在主项目既有outputs中，逐件位置见清单 |
| bridge-skills | [完整旧仓库](/Users/user/Documents/Code_Project/Bridge/outputs/desktop-legacy-20261104/bridge-skills)，保留.git、全部未提交代码、资料和原工程；仅移除可重建缓存。旧GUI插件仍从这里读取同字节原实现，不在此继续开发 |
| bridge-skills-2.0-审核包 | [原始审核资料](/Users/user/Documents/Code_Project/Bridge/outputs/desktop-legacy-20261104/bridge-skills-2.0-审核包)，保留早期H21/H22探测及验收边界 |

[完整迁移与去重清单](/Users/user/Documents/Code_Project/Bridge/outputs/desktop-legacy-20261104/migration-manifest.json)记录每个旧路径、现存路径和SHA-256。原审计/任务JSON中的历史绝对路径与签名不改写；查询历史文件位置时使用此映射，不将早期记录当今日验收。

Houdini 21/22及Nuke旧GUI启动配置只替换目录前缀，其余字节保持；没有升级旧GUI插件、启动DCC或重跑工程。当前0.4.10及已完成Geometry任务的状态、canonical、accepted和Native会计文件保持不变。

已删除桌面三原目录。去重34个文件、193.07MiB；另清理210个可重建缓存文件、4.94MiB。旧仓库249项Git状态及HEAD保持。此归档被主项目既有outputs规则忽略，未提交或推送。
