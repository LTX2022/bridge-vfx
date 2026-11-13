# macOS 清单更新结果（2026-10-05）

仅修改 `handover/MACOS_REVERIFY_20261004.md`，新增本记录；未修改任何源码、测试、其他 handover、生成副本或既有日志。未运行 Python、测试、正式进程作业、安装、打包、提交或推送。

纳入根 `outputs/windows-next-20261005/RESULT.md` 最新软件结果及边界：资源 owner／生成 handler 输出与清理故障、schema2 typed primitive public locator、不可变终态 anchor、registry 无 source 拒绝；52 条正式原件只证明 primitive，P02 只证明 parameters_only。全 16 域和完整输出登记保持 BLOCKED；全部 macOS 项为 NOT_RUN／待目标机器。

补充目标机 Python 3.11 UTF-8／禁 bytecode 的精确定向命令、当前源码导入路径与独立 macOS 日志目录。核对实际源文件后，将 Swarm／材质新 PID 的 Windows guard、Job0／child_wait_observed及固定输出目录写明；不照搬这些测试为 macOS 命令。材质输入值在测试内显式定义，历史基准仅标注来源，不是运行依赖；Main随后根据已完成实际结果修正该说明。资源生命周期隔离 harness 同样需 POSIX 对应用例；纯单元 handler `_exit` mock 与 parser stop mock 均明确不作为实际停止证明。材质全 11 项新 PID 仍待 POSIX 两版对应验证，旧正式重开仅覆盖 3 项。

实际检查仅 PowerShell 文本读取／`rg`／`Test-Path`／`Get-FileHash`：最终命令选择器检查退出 **0**，30 个命令模块均存在，指定类／方法均存在，文档 99 行。初次泛文本枚举退出 **1**，因把正文方法名和 outputs harness 当成 unit 模块；改为仅检查 unittest 命令选择器后通过。这些退出码是文档静态检查结果，任何目标机测试退出码／日志均未生成。

| 修改文件 | SHA-256 |
| --- | --- |
| 清单修改前 | `ba4f42c1042e87f80de96eeed5d48a7b1dc4842f142f467b1ac161f6c01a514f` |
| 作者交付时清单 | `5735375f9ce2c619bb101b2545aafde3289d021dd0e7506c607376b7dfc10fa2` |

文档写权释放。未执行目标机复验，不宣称 macOS、真实 DCC 或整域 PASS。
