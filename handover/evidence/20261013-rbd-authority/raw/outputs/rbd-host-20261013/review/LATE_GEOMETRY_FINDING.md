# R04 / P2：晚期 inputGeometry 可使已冻结 configure 事实陈旧

此项是 INITIAL_FINDINGS.md 的追加，不替代其中的源码绑定与其他发现。

实际生产 Host `observations` 在末端重新检查身份、帧、参数、gates、wires 和 node-session，但未重新检查 configure/carrier 几何。实际 solver 的 inputGeometry 调用能在取得固定旧输入几何后改变 configure 的几何属性；后续状态检查全部相同，三份返回事实仍一致，却已经不代表当前 source。

最小 probe：合法 zero prepare/write 后，在 solver.inputGeometry 底层调用中冻结其实际旧输入，再将 configure 原始 temperature 从 20 改为 42，返回冻结的旧输入。没有根据请求计算成功几何；carrier 固定原样读回 configure，无高层权限/回执替身。

H21/H22 均 `Host.readback(...velocity_variance=0)` 成功，返回 consumer temperature=20，实际 source temperature=42。应拒绝，不能签发当前 basis/source 仍一致的结论。位置：`native_rbd_controls_host.py:215` 首次 configure 采样、`:252` solver 最后输入采样、`:253` 仅状态复验。

最小修复要求：为会改变实际原始几何的晚期 native 调用提供可验证的当前几何稳定性 fence；至少覆盖此固定事实反例，发生源/consumer 漂移拒绝并保留原帧。不能把重新计算期望输出或简单观察到旧数据一致当作当前事实稳定。

探针脚本 `independent_refusal_probes.py` 新增 R04，完整八项双版本记录见 `independent-refusal-probes-v3.json`。正式 v1/v2 失败仍是诊断，当前正式 v3 由主集中运行，本 reviewer 不重跑大测试。
