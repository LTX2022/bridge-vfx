# Karma 正式装配检查与预检修复

日期：2026-10-16。范围为普通 Python 软件编译、预检和两项最小修复；没有启动真实宿主或模型。M1 仍 NOT_READY。

## 已验证的正式装配

复用现有 graph_catalog.compile_proposal、registered_domain_identity、bounded_domain_schedule 和 execution_diagnostics，对 H21.0.631、H22.0.459 各自编译 lighting_camera_render_v1 与 material_lookdev_v1。灯光图为12节点/8连接、2个调度批次；材质图为19节点/13连接、3个批次，执行诊断均为空。

这是注册拓扑的静态编译结果，不证明最小案例的具体位置、颜色、相机、128×128分辨率已写入，也不证明建图、保存重开、输出或视觉通过。下一项需核对这些冻结值能否沿正式控制路径写入并读回，缺接口时先最小修复，不能以编译通过替代。

## 两项修复

1. 预检此前只将 scope.case_id 与卡片单值 case_id 比较，导致同卡 case_ids 已声明的反馈和恢复案例被误拒。现在按合法、唯一且包含主案例的 case_ids 匹配；没有该字段的旧单案例卡保持兼容，外来/畸形ID仍拒绝。
2. 预检此前只检查全局可识别版本，旧22.0.429可以满足当前要求21.0.631/22.0.459的卡。现在在全局支持范围内再落实卡片逐应用 required_versions；显式旧版卡仍可限定429。Nuke单域不增加Houdini依赖。

仅修改 tools/preflight_real_acceptance.py 和原有 tests/unit/test_readiness_delivery.py 中的必要覆盖。原生依据、资源确认、帧/时间/磁盘预算、操作快照、缓存和媒体守卫保留；未更新支持等级或放行真实运行。

## 验证与独立复核

- 两个新增表驱动方法在原实现上产生9个失败事件、无ERROR，复现案例与版本缺陷；含subtest，不把事件数当作测试数。
- 修复后原LivePreflightTests及既有视频依赖静态检查共5个方法通过，退出码0；仅在原测试类增加2个方法，未扩充大规模用例。
- 实际CLI：459反馈案例只因native interface basis unresolved拒绝；429同时因不满足卡片版本及原生依据拒绝。两份回执均host_started=false、model_called=false、passed=false。
- 沿用既有Bugbot，只读比较本轮前后两个文件，未发现本轮增量的P1/P2；未运行宿主或测试，不扩大为全项目结论。
- 未运行标准全量、发布构建或安装生命周期；历史2164项结果不提升为本次源码的全量结果。

Git内的复现、CLI和编译观察见 [本轮证据](evidence/20261016-karma-preflight/green-cli-and-assembly.json)、[红结果](evidence/20261016-karma-preflight/red-regression.json)和[红日志](evidence/20261016-karma-preflight/red-regression.log)。CLI输入确认字段来自明确标记的软件夹具，仅测试预检，不是操作者真实资源授权；这里只收录失败回执，不提供可用于真实启动的scope。

本轮审查绑定：

- tools/preflight_real_acceptance.py：a6a1771383b45236ec062172a0436797e70832b2fac1eab7ec6637c463a48972
- tests/unit/test_readiness_delivery.py：62274d8c001be4c9b1be7d1c29f56feb12e2994ec1afbbd3a350bdbfe20c6f46

官方原件和重建合同见 [最小对照案例](../docs/official-baselines/karma/README.md)。native_basis未解决、实际writer/AVAILABLE、正式反馈和共同组合路径等剩余项保持原状态。当前没有经真实宿主验证的新HIP/NK，不自动提交、推送、合入Desktop工程或执行真实作业。
