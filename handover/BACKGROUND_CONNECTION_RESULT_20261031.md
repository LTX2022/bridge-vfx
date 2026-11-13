# 新 agent 自动后台连接交付

Bridge VFX 0.4.0已由官方管理器安装，401文件与正式包/ZIP逐字一致。默认新agent通过公开工具启动独立后台Houdini与Nuke，配置在Bridge私有连接目录中生成；用户GUI的package/init、当前工程和桌面旧源码保持。

## 使用

新agent使用Bridge Skill，先读 `bridge_health`，再以自己生成的唯一 `request_id` 调用 `bridge_connect`。等待时只对返回的 `connection_id` 调用 `bridge_connection_status`；双宿主均通过真实认证才返回CONNECTED。完成后调用 `bridge_disconnect`。

模型无需提供软件路径、端口、token或初始化脚本。本版自动定位本机已知兼容的Houdini21.0.631与Nuke17.0v1；控制器使用Python3.11。未找到兼容安装会明确返回错误，不下载软件或改变许可证。

每个宿主会话沿用120秒期限，组期限是两者较早值。状态与期限在响应中返回；MCP重连不续期。过期后新任务使用新请求创建会话；同请求只取回原连接，不自动重启。

## 真实结果

无实现历史的gpt-6-luna/low，仅获得公开schema与官方MCP客户端，自行完成：

| 项目 | Houdini | Nuke |
| --- | --- | --- |
| 实际版本 | 21.0.631 | 17.0v1 |
| PID | 72722 | 72783 |
| session | 2dd27e37d5ce4b68abe54bb3a92d4ee1 | e39020a80cb64f009722ee6d7f4f03dc |
| 初次认证 | CONNECTED | CONNECTED |
| 新MCP进程重连 | 同PID/session | 同PID/session |
| 最终状态 | 已停止 | 已停止 |

连接ID：`connection-aec0d2a27a4c43cdbfc1ee583ba9571d`。一次新connect加原request_id重读未生成第二组实例；两次MCP进程均正常退出。总5次工具调用、2次schema发现，无渲染、仿真或作品修改。

后台18项和入口8项定向软件检查通过；真实连接、重连、停止另据正式回执验收。[独立代码审核](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge新Agent自动连接-20261031/独立代码审核.md) · [真实最终验收](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge新Agent自动连接-20261031/真实连接最终验收.md) · [实际调用记录](/Users/user/Documents/work/doll-outfit-ai-docs/Bridge新Agent自动连接-20261031/真实双宿主接通.json)。

该交付验证自动接通能力。120秒不表示长期常驻服务；新后台连接不解除旧失败任务、迁移旧预算或替代正式图/产物权限。旧几何仍15次关闭状态，第二版Nuke作品尾部未因此完成。
