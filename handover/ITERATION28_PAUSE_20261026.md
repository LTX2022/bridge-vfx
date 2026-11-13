# 工程链暂停点：主 EXR 已真实渲出，Nuke 段收尾中断（2026-10-26，ITERATION28）

状态：**用户指示暂停写代码。链路历史性推进：主渲染真实出图、controlled_output_v1 验证登记通过、渲染后可信停止通过；仅剩 Nuke 消费段收尾（下一个也是最后一个已知阻断已定位未修）。无残留 DCC 进程。工作区干净，HEAD 716b15a 已推送。**

## 范围 17 已达成的真实事实（engineering-chain-20261026-authorized-17，scope 46946a80→28f89b0b→…→ 见 accounting；候选链 08→17）

| 环节 | 状态 | 证据 |
|---|---|---|
| Alpha（husk+nuke 真实宿主） | DONE | 签名启停对完整 |
| propose / build | DONE | graph worker 真实建图 |
| task_save | DONE | 真实 HIP 落盘（第 22/23 次修复真实生效） |
| houdini 初始/重开宿主可信停止 | DONE | 签名回执 |
| **husk 主渲染** | **DONE，真实出图** | **`project/saves/main.0001.exr`（sha256 `72b1e371028757e36033...`），128×128、frame 1、Karma CPU、beauty RGBA、ACEScg** |
| **controlled_output_v1 输出验证** | **DONE** | verify 阶段完成 |
| Nuke prepare | INTENT（被上一错误中断） | — |

**这是本项目数月来首次在真实 Houdini 21.0.631 宿主上完成受控主渲染与受控输出验证。**

## 下一个（已知未修的）阻断：Nuke 消费段

范围 16/17 的 Nuke 段失败链已诊断到根因、**修复未写**：

1. ~~范围 16：Nuke 宿主启动即败~~ 已修（`716b15a`：task_host 环境剔除 PYTHONEXECUTABLE/PYTHONHOME，内嵌 3.11 的 binascii 导入恢复）。
2. **范围 17（当前）**：Nuke 宿主启动成功，但处理命令时服务线程崩溃断连（`Nuke Bridge closed the connection without a response`）。根因已从 `nuke-host-*/supervisor/child.stderr.log` 定位：某响应含原生 **`Format` 对象不可 JSON 序列化**（`nuke_bridge_addon.py` handle → json.dumps TypeError）。泄漏点未最后确认（怀疑 alpha 校准结果回读或 EXR 读取路径的 `reader.format()` 之类原生对象直接进入响应）；`grep Format` 未命中源码字符串，需在 Nuke 宿主日志的请求上下文里追（`nuke-host-*/supervisor/` 下 intent/stopped 与 child.stderr 的回溯行 6047）。

## 本轮（迭代 24 系列）全部修复清单

| 提交 | 内容 |
|---|---|
| 4b05e90/56c1daa | 第 22 次：registered 交接保留编译器精确角色映射 |
| 21e72fe/a0f3a28 | 第 23 次：typed 保存先应用目标名再证明捕获 |
| 12979fa | 孪生补 H21 usdrender USD processor 参数族（基线 44→33） |
| 7d8ae06 | 孪生补原生回调/HIP 加载事件/LoadWarning 语义（readback 11/11） |
| 0fa5f26→b789018 | 渲染读回专项 + 复核修正 |
| d15e2f1 | 诊断宿主逐字段容错 |
| 91a0d1b | 分辨率对照实验专项（六变体） |
| 3ce62d0 | 第 24 次主修复：settings_binding 自身分辨率治理（实验钉死真凶） |
| 6375609/e401fdf | 治理变更：activate-agent（用户选项 B，授权原文逐字入签名回执），全部门接受 explicit_agent_controller |
| ceccbb2 | 渲染记录场景引用化+合同证据键（预算超限） |
| 1d2d622/6c5b856/47aeeb9 | soho_foreground=1（身份比较 bug 修复）、husk_tpostframe=0 |
| 716b15a | Nuke 宿主环境去 PYTHONEXECUTABLE 泄漏 |

## 治理与执行方式记录

- 用户选项 B：新增 `activate-agent`，`explicit_agent_controller` 类型，grant（authority=current_user_conditional_instruction，instruction=用户原文"B"）进入 HMAC 签名回执，绝不冒充手输。所有执行从冻结快照入口运行 + `PYTHONEXECUTABLE=<绑定 stub>`（独立复核已评估：软一致性守卫，对抗边界在 HMAC 账本）。
- 候选 07（review 95fa8100，等 TTY AUTHORIZE）与 08（agent 激活后因执行器哈希传反、激活门未及修而废弃）均未消耗预算或已如实封闭；有效执行范围 09–17 全部走完整治理链。
- **supervisor stub 绑定缝隙仍待决策**（ITERATION26）：绑定的是 launcher stub 文件哈希，实际解释器由 PATH/opt 链接决定；05/06 与本轮实际解释器推定 3.14.9（PYTHONEXECUTABLE 只修展示）。

## 剩余工作（恢复时的顺序）

1. Nuke `Format` 序列化泄漏修复（定位→最小修复→孪生回归）。
2. 新候选（18）执行 Nuke 段：prepare→consume_artifact→nuke_render_bounded→Nuke EXR 输出→nuke_stop→最终 result。
3. 主视觉人工接收（`main.0001.exr` 已在位）与 Nuke EXR 后的人工检查单列。
4. 基线 33 项孪生失败家族（project_environment 等）继续还债。
5. supervisor 绑定缝隙生产修复（待决策）。
