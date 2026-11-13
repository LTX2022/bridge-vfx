# Bridge 六角色本轮执行合同

目标：保持既有身份事实和校验强度，解决当前身份采集阻断，再验证正式八阶段软件链，符合条件时冻结新的未授权候选。

| 角色 | 负责人 | 文件所有权/职责 |
|---|---|---|
| 方向负责人 | direction_owner | 只读核对当前目标、依赖和完成条件；不批准扩大用户授权 |
| 执行1 | executor_native_basis | native-basis/；官方本机接口依据和有限软件原型，不改生产 |
| 执行2 | executor_capture | capture/；唯一process_image.py、controller镜像、对应测试及必要helper实现者 |
| 执行3 | executor_integration | integration/及新outputs；正式软件链和冻结入口验证，不改生产 |
| 独立验收1 | code_acceptance | 只读核对代码、身份等价、竞态、失败拒绝；不参与实现 |
| 独立验收2 | evidence_acceptance | 只读核对原始证据、软件来源、停止、依赖、源码及冻结状态 |

执行1须证明PID/PPID、精确birth、真实主MH_EXECUTE映像load/path/vnode可有界取得。执行2在证据和方案确认后最小实现；保持前后双观察、安全打开stat/hash、祖先链以及5/16/60秒上限。不能用ps名称或proc_pidpath单独代替主映像事实，不以旧事实缓存、延长期限或取消检查消除失败。

执行3只在实现冻结和定向检查通过后运行一次完整软件链。须证实8角色、认证停止、两项产物依赖、无pyc污染、源码一致。失败保留最早原始证据，不盲目重复。通过后正式prepare-successor/review/default-preflight，生成20261023-h21-08未授权候选，review仅指向未来09-authorized，不激活。

保留-06全部242文件、-07全部183文件、alpha color4h和监督器-B修复。预算8次启动/120秒单项/600秒累计/512MiB/一个重型作业/零自动重试。禁止真实DCC、HY3、模型调用、扩大16域、Git发布或重用-06授权。软件链成功不能提升真实工程闭环或M1状态。

若等价采集或最小修复证据不足，交付明确阻断和独立结论，不生成已修候选。六角色按最多三位子agent并发分批运行；主控负责装配、冲突处理和统一汇报。
