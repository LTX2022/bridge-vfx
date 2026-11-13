# DiskLight 真实反馈修改结果

**本轮计划的技术闭环已完成。** 同一任务的曝光 0→1、保存、独立冷开、反馈版本与依赖失效、主产物 v2 登记、Nuke 按 v2 消费及独立冷渲染均通过。

[打开工程与图像](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/feedback-exposure-01/README.md) · [正式文件清单](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/feedback-exposure-01/delivery-manifest.json) · [执行汇总](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/feedback-exposure-01/feedback-result.json)

| 项目 | 实际结果 |
| --- | --- |
| 任务 | `7c65a89096e84533b8f0ace596cfe1c2`，`lighting_camera_render_v1@1.0.0` |
| 控制 | `light` 的曝光由 0 改为 1；1515 字段中只有这一项改变 |
| 内容版本 | 反馈版本 1，完成；重复同值请求未再次写入或新增版本 |
| 依赖 | v1 正常失效，旧行及回执保留；新操作登记 `disklight_incremental_main` v2 |
| 工程 | 常规 task_save 保存，独立 Houdini 冷开后参数与 USD 语义通过 |
| 主渲染 | Karma CPU，第 1 帧、420×300、RGBA HALF、ACEScg |
| Nuke | 派生产物 `nuke-render-nrend-a6132185b66157d0` v1；输入为主产物 v2 |
| 冷渲染 | `nrend-a6132185b66157d0` 完成，交付 NK 与实际冷渲染快照字节一致 |
| 新主图→Nuke | 504000 个 RGBA 样本，差异为 0；颜色元数据 `lin_ap1` 保留 |
| 消耗 | 本反馈阶段 7 次启动、362.968 秒；获批上限 7 次／600 秒，所有票据可信停止 |

旧图→新图有 147329 个通道样本变化，RGB 总量比例约 2.000012。Alpha 有 1130 像素变化、最大差值 0.271240234375；不将两种曝光下的 alpha 宣称为逐像素不变。新主图→Nuke 的 alpha 样本完全一致。

## USD 恢复与保留边界

旧 USD 导出缓存曾由 ROP 更新，用户已明确批准使用单独生成且通过完整语义对照的曝光 0 副本恢复。旧原始 SHA 为 `adca1726724af1af8d5fa638bcece5831e3482721fbf03fa9f4ac5e542a6ca4d`，恢复后 SHA 为 `89da8a07a3ff64d05a7beaf44a05cbc5c8d45d54e225e95b08ee0e54baf2734d`；原清单、原摘要和原回执保留。该差异不扩展到其他文件：旧 HIP、NK、EXR、官方参考及校准保持原身份。

批准与对照依据：[USD 恢复](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/feedback-exposure-01/usd-approved-recovery-result.json)、[本轮新增启动许可](/Users/user/Documents/Code_Project/Bridge/outputs/Bridge-disklight-integrated-20261028-08/continuations/feedback-nuke-02/extra-start-approval.json)。失败范围及其消耗保留；反馈阶段的 7 次启动包括两次失败或未完成的 Nuke 尝试，不能概括为 7 次全部成功退出。

## 常规实现

- 官方 DiskLight 曝光语义控制、精确原生参数、门状态及严格全场景读回接入 feedback_edit。
- 登记读取同任务历史头；跨路径修订仅允许已失效旧版、同任务同类别／帧／颜色、递增反馈内容版本、新真实生产操作和显式旧版本条件。默认身份冲突仍拒绝，旧版本不可变。
- Nuke 使用认证的显式生产来源和共享账本，区分生产控制端与账本位置；只匹配当前控制端与执行范围。
- 只读复用成功生产事实时，严格核验历史签名、停止和精确事实摘要；历史失败范围不重新取得启动权限。
- 后续入口要求执行前保存经原摘要认证的 USD 原字节备份；只允许用该同 SHA 备份恢复。

定向软件检查包括 14 项修订约束／typed 登记、4 项 Nuke 就绪后共享账本检查、额外启动批准拒绝与累计检查；本轮未运行整组软件验证、冻结审查或完整前缀。全部原生结果由实际文件、操作和签名停止证明分别记录。

本结果覆盖固定 H21/Nuke17、DiskLight 单帧控制反馈。人工视觉接收、主动中断正在执行的真实 worker 后恢复、HY3 创作、第二案例、H22 与全 16 域仍分别待验收。没有提交、推送或重新构建安装 ZIP。
