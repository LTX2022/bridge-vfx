# 固定导出目录与清单顺序修复：真实结果（2026-10-27）

修复与冻结证据在 `evidence/20261027-export-directory-integration/`。目录固定回归35项通过，清单生成顺序回归3项通过；各自有逐项日志、源码哈希和无被禁止启动记录。第二候选独立审查 READY，184项bundle、176份快照、217项绑定、218项不可变记录一致。第一候选清单失配保留未启动；未原地覆盖。

用户已授权完成任务所需预算与持续执行。按 review `af9405462bca21be631202c861e457b304a50f1860c2a132f50fd2c6fbf285b1` 激活新范围 `outputs/official-karma-disklight-h21-exportdir-20261027-02`，冻结驱动预检无阻断，执行一次后失败关闭，零自动重试。

- 2次启动、71.78131461143494原生秒。保存阶段退出0，冷开导出阶段退出1。全部 started/runtime-ready/stopped 已由冻结代码认证，均为 owned_child_wait，无未观测后代。
- **完整warm/cold observation逐项相等**，固定目录修复在本轮实机生效，Ramp采集也通过。
- 工作HIP与官方USD实际生成；USD导出后 `verify_output_stage` 失败于 `OFFICIAL_OUTPUT_ATTRIBUTE_REQUIRED:driver:parameters:aov:husk:name`。仅生成USD不代表其语义或RGBA合同验收通过。
- 176份冻结运行源未变。认证时根目录123617491字节，未超512MiB。
- 官方组累计16启动／365.1452987194061秒，旧球体范围29单独记账；本次关闭范围和余额不得复用。
- 官方参考渲染、原生alpha、Bridge重建/HIP/渲染、NK及Nuke独立渲染未到达；人工视觉验收未到达，最终可用交付仍未完成。

[离线认证结果](evidence/20261027-export-directory-live-02/result.json)绑定HIP/USD、激活、签名停止和冻结源。下一最早实际阻断是Beauty属性在导出后缺失，需基于此USD与同版原生参数定义定位，不放宽RGBA验证或跳过失败阶段。
