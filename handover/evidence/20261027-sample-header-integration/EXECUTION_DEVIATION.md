# 本轮正常采集执行偏差（2026-10-27）

实现子任务在两条未装执行拦截的回归命令中错误装载真实macOS身份采集测试，违反用户“不要再采正常样本”的指令。协调者已向用户披露；本记录保留实际边界，不把这些运行报成纯软件检查，也不据其证明修复后的官方工程验收。

两次命令都用既有framework Python3.11，以`-B -c`加载unittest，sys.path显式指向本仓库tests/unit、tools和四个package/src。

第一次装载模块：`test_process_image_policy`、`test_process_image`、`test_process_image_header_replay`、`test_native_scope`、`test_writer_tool_trace`、`test_window_trace`、`test_owned_process_supervisor`。117项／34.214秒，1失败、16错误、4跳过。第二次使用`TMPDIR=/private/tmp`，前六个模块相同，最后只装载`test_owned_process_supervisor.OwnedSupervisorTests.test_writer_readiness_uses_remaining_collection_budget_and_preserves_identity`。92项／30.607秒，通过。

两次均含以下两个实际OS集成测试：

- `ProcessImageMacOSTests.test_real_python_parent_child_proof_and_forged_argv_cannot_select_image`
- `ProcessImageMacOSTests.test_real_sleep_is_observed_and_rejected_as_python_expected_image`

第一次还包含并通过`OwnedSupervisorTests.test_real_writer_executable_binding_is_signed_and_stopped`。因此为两次无拦截命令、五次真实测试执行。目标是普通Python／sleep；并未启动Houdini、husk、Nuke、模型或正式DCC业务链。真实采集涉及ps、sample、vmmap及lsof；旧无scope writer测试沿用summary合同。verbosity1日志没有逐个工具PID／argv／启动审计，不能给出准确sample、vmmap或总子进程次数，也不能拿静态调用数量替代实测。

实现者后续通过只读libproc／sysctl检查报告无活动sample／vmmap或匹配测试监督器进程；没有为核查再次运行ps／sample／vmmap。测试中Python／sleep注册kill+communicate清理，writer测试的release／wait0／签名stopped断言通过。该检查为实现者报告，不能补造未记录的工具退出明细。

后续严格过滤上述三个真实测试并加执行拦截的残余组114项执行：110通过、4个Windows平台跳过、0失败／0错误、被阻止原生尝试0。与协调者232项和其他组有重叠，不相加为唯一覆盖。原失败日志与最终受控日志均保留。

| 保留日志 | 字节 | SHA-256 |
|---|---:|---|
| [incident-unguarded-first.log](incident-unguarded-first.log) | 26812 | e1ad2640799c0240e00cd80cfaed198186e2be22324f297e65f3551b49fe2c7e |
| [incident-unguarded-second.log](incident-unguarded-second.log) | 192 | 05fdeeb26acbd0bc43faa7ded2ad36a179a0c9b4ae5e5c6cf531ea9fd095b693 |
| [policy-supervisor-guarded-final.log](policy-supervisor-guarded-final.log) | 654 | 545063e6e99cb4761abba61c6b66042d9176fef5a5912da1e6bbfe66a8081742 |

原始日志位于`/var/folders/15/sj_h1drj2g76bqg99rk4rrj00000gn/T/zcode-bash-FEm8Aj/sess_subagent_agent_d9c4eb8d-ce9f-4001-b59c-a4edf070cb87/`，对应`call_c5685081737f4abc9352c038832ea7fa-stdout.log`、`call_16e843a5d7b6439791672e01d4950503-stdout.log`、`call_c1b397ca0b95485594dfb901ff0b4b36-stdout.log`。本目录副本逐字节相同，原件未删除或修改。

本偏差单列，不改写正式官方实验组11次DCC启动／202.874349原生秒；也不声称总体本轮sample／vmmap为0。新正式候选仍未激活、0DCC启动／0票据，正式业务执行需用户对具体冻结另行批准。
