# Windows 原生接手修复（2026-10-04）

本批从 Git `d48fa10d32b95ce322e22b7b1ae39f947f3b1126` 继续，范围为 Windows 软件运行基础和原移交说明首批五项。当前工作区保留未提交补丁；不自动提交、推送或建立修复分支。原 ZIP、停写报告和旧冻结日志保持原样。

实际验证只使用受控 Python/TCP 进程、宿主服务和底层原生 API 替身。Houdini 21.0.631、22.0.429 和 Nuke 17.0v1 是软件合同版本；没有运行这些真实软件、WorkBuddy/HY3、模型、仿真或渲染。本批不等于全 16 域 M1 或完整发布验收。

## 当前实现

- 文件锁统一到 `dcc_task_runtime.platform_support`，Windows 使用字节范围锁，POSIX 使用 flock；部署、宿主所有权、场景租约沿用现有围栏。私有运行目录和文件在 Windows 设置当前用户及 SYSTEM 的 DACL，自有文件替换和删除处理只读属性，拒绝越界、链接和异常文件身份。
- Windows 进程查询使用只读句柄、创建时间和等待状态。监督器在 CreateProcess 时通过 Job 属性加入自有 Job；Job 关闭清理子进程。停止事实须直接子进程退出且 Job 清空；身份不符或证据缺失保持未知，不释放槽位。POSIX 继续使用进程组。
- 软件启动使用解释器、bootstrap、runner 的参数数组。`software_launch_script` 只允许明确授权的 software_test，脚本内容摘要贯通启动和图 worker；real_host 携带该字段直接拒绝。测试使用 Python 基础解释器，避免 Windows venv 重定向器造成受监督 PID 与实际 worker PID 不同。
- 每个软件 Houdini 宿主有独立可变帧状态。原生参数替身采样恢复调用前帧，不覆盖真实采样失败；RBD collector 同时读驱动、keys、外推、gates、registration、所有权和 configure 几何。保存后确认旧 worker 退出，再用新 PID/nonce 重开直接读回。
- 最终材质 settings_binding 同时核对材质关系和渲染配置，H22 还核对过滤器。灯光测试使用可信布局节点。正式控制链继续使用共享 facade、冻结计划、当前场景及保存摘要；登记失败重试同一操作，不重复渲染。
- 软件 Houdini HTTP 服务在 Windows 独占端口并继续探测下一端口，避免已有无关服务占用端口时接到外来健康响应。没有停止无关服务。
- 控制副本通过 `tools/sync_controller_client.py --write` 同步，包含基线中遗漏的既有原生模块；副本不得单独维护。

## 环境和运行

工作目录为 `C:\Users\32200\Desktop\Agent\skill\Bridge`。隔离解释器 `.venv\Scripts\python.exe` 为 Python 3.11.9 AMD64，四包从本源码 editable 安装。下载的官方 Python NuGet 包在 `outputs/windows-takeover-20261004/environment/`，SHA256 为 `9283876d58c017e0e846f95b490da3bca0fc0a6ee1134b2870677cfb7eec3c67`；旧移交 wheels 未作为当前修复实现。

PowerShell 从仓库根执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Join-Path (Get-Location) 'tests\unit')
& '.venv\Scripts\python.exe' -m pip check
& '.venv\Scripts\python.exe' tools/run_logged.py --log-dir outputs/windows-reverify/logs --name platform -- '.venv\Scripts\python.exe' -m unittest -v test_platform_support test_windows_process test_owned_process_supervisor test_task_host_lifecycle test_nuke_task_host
& '.venv\Scripts\python.exe' tools/run_logged.py --log-dir outputs/windows-reverify/logs --name native -- '.venv\Scripts\python.exe' -m unittest -v test_native_domain_graphs test_native_render_domains test_houdini_parm_probe
& '.venv\Scripts\python.exe' tools/run_logged.py --log-dir outputs/windows-reverify/logs --name controller -- '.venv\Scripts\python.exe' -m unittest -v test_domain_readiness_evidence test_c3_formal_entry test_feedback_versions test_readiness_cli test_graph_jobs
```

以测试源码中的实际模块名为准；正式入口测试的运行证据目录应每次新建。不要用旧签名回执代替实际进程停止和新实例读回。

## 验收证据和剩余项

实际命令、退出码、原始日志、失败分类、最终文件摘要及复核结论见 [本批验证报告](../outputs/windows-takeover-20261004/validation-report.md) 和 [独立复核](../outputs/windows-takeover-20261004/independent-review.md)。日志头记录启动时源码树摘要；文档更新或之后的修复不能追认此前全量结果。

标准软件全量已实际执行：1151 个测试，51 failures、167 errors、7 skipped，退出码 1。该结果保留并逐项分类，绝不写成全量通过。首批修复的定向证据与未完成的全 16 域、安装、媒体或目标平台条件分别报告。全量后的修复只运行受影响回归，避免无变化重复全量。

macOS 延续同一套源码，当前状态为待目标机器验证，运行清单见 [macOS 复验说明](MACOS_REVERIFY_20261004.md)。尚未确定的领域控制量、48+2 案例和完整发布验收仍按 [REMAINING.md](REMAINING.md) 后续处理。
