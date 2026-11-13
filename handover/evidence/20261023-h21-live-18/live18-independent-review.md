# 第 18 轮真实结果独立验收

结论：`LIVE18_FAILED_STOPPED_NO_RETRY`。停止、预算、授权与原件核对通过；真实工程仍未闭环。

用户明确批准按 review17 `417b13638e217a6ff2b3453a930b028a5c38a53921e6204d4fdf44862ae0e118` 激活独立新轮。激活 HMAC、scope `b6eaedd9eeb14233a4631d3ac8c4a8c941c2b0f736119a6f54ade7c7fb43a73c`、bindings `e46827eeaa3cb838c93f2c107c4fcbdee88383534cf5b48854b6660bb911771f`、159 个批准执行源码及 175 个冻结记录均匹配。范围沿用 ACEScg、8 次启动、单次 120 秒、累计 600 秒、512 MiB、一个重作业、零自动重试。

实际仅启动 alpha-husk、alpha-nuke、graph-worker，3/8 张票据。8 条账本 HMAC、序号、前链、anchor 与末态一致；三组原始 started／stopped 的签名、身份、PID、开始摘要与停止时间互相绑定，均为成功的 owned-child-wait 停止，无未观察后代结果。两次 alpha 另有签名 runtime-ready 与 writer_process_binding。累计 DCC 计费 78.698854923 秒，封存逻辑占用 62,241,557 字节，均低于预算；重作业区间不重叠，活动票与未知停止均为 0。范围最终为 ENGINEERING_DRIVER_FAILED，失败后没有新票据或自动重试。

真实基础构建取得进展：原始 graph 结果为 construction_executed=true，同时 reconciliation_required=true，diagnostic 为 WORKER_RECONCILIATION_REQUIRED，visual_verified=false。从原 DB／WAL／SHM 的临时副本核对，42 条 journal 中 41 条 COMPLETE，最后 domain.initialize 仍为 INTENT。light、rendervar、mtlxnormalmap 三处实际类型分别精确读回声明基名，17 的精确类型修复已在本轮真实运行中生效。基础构建已执行不等于 initializer 完成，更不等于整个图或工程通过；wrapper 的 exit 0 也不改变该结论。

真实 alpha 校准的原始 JSON 摘要、关联 alpha 数值与 5 个 EXR 均匹配；独立 stdlib 解码完成 640 条扫描线，覆盖与字节边界有效，全部样本有限，通道范围吻合原产物记录。HIP、NK、main EXR 与主场景 Nuke 输出均未生成，5 个 EXR 只证明 alpha 校准产物。

原件保存核对：既有 2,520 个文件和停止后的 18 共 355 个文件，文件集合、大小及 SHA-256 均匹配基线。未在原位打开 SQLite，未增加原目录 sidecar。此次审查仅执行只读证据脚本，未导入项目模块、未运行测试、原生探测或 DCC。

机器结果见 live18-independent-audit.json：passed=true，54 项核对无错误。修后 19 软件候选尚待提供，本报告不评价其源码、软件链或未来真实结果。
