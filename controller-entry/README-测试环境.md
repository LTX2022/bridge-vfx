# 测试环境与依赖（R5）

- Python: 3.11（主控复现环境 3.11.16；开发环境 anaconda 3.11）。
- 依赖: 仅 `pytest`（纯软件测试）。安装: `python3.11 -m pip install pytest`。
- 运行定向回归（无需 Houdini）:
  `PYTHONPATH=delivery/controller-entry/client python3.11 -m pytest candidate/tests/unit/test_operation_runner_recovery.py candidate/tests/unit/test_bridge_core_chain.py -q`
- 运行受影响既有回归:
  `PYTHONPATH=candidate/packages/dcc-task-runtime/src:candidate/packages/houdini-bridge/src python3.11 -m pytest candidate/tests/unit/test_houdini_fx_domains.py candidate/tests/unit/test_owned_headless_reopen.py -q`
- 复核方 reproduce.py 的四项行为在本候选上的期望：全部不再复现（query 不启动执行/跨任务名额互斥/损坏记录拒绝并保留/旧代次仅 RECONCILE）。可直接用原脚本对照。
