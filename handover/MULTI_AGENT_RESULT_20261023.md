# Bridge 六角色协作结果（2026-10-23）

六个职责均已实际派发并完成本轮有限工作。**本轮形成了可核对的采集方案排除证据；尚无生产修复，-07软件集成阻断保持，未生成新候选。**

## 分工与产物

| 角色 | 职责 | 本轮结果 |
|---|---|---|
| direction_owner | 把控目标和技术路线 | 固定当前工程闭环与身份合同，给出三执行合同及GO/NO_GO条件 |
| executor_native_basis | 原生依据与有限原型 | 核对本机SDK及Apple来源，验证权限限制和公开区域枚举，取得同目标差异反例 |
| executor_capture | 故障捕获与唯一生产实现所有权 | 完成提前采样；本组10个普通Python目标、20次vmmap成功，未据此改代码 |
| executor_integration | 正式链与候选冻结 | 核对07指纹、预算和正式命令，等待有效实现；未重复整链或生成空版本 |
| code_acceptance | 独立代码及身份等价验收 | 已测简化替代不等价，原可用性缺陷仍在；不批准生产接入 |
| evidence_acceptance | 独立需求、原件及证据验收 | 核对实际过程、来源与候选状态；研究产物不提升为修复或整链通过 |

主控负责冲突处理、跨角色质疑和统一接收。实际并发最多三位子agent，六职责分批运行。共享生产文件只有执行2可修改，验收者未参与实现。

## 已确认的推进结果

1. 提前到vmmap启动后采样，获得19份非空调用栈，但全部属于成功过程。这不解释旧超时，也不证明故障消失。
2. TASK_DYLD_INFO相关的task read/inspect探针被本机权限拒绝；没有修改权限、签名或系统配置。这只限制该路线。
3. 公开libproc可快速取得区域、vnode及进程字段。但实际搬移主映像后，原型仍选出唯一RX/offset0同vnode候选；在**同一PID**上，原生产observe_process在1.693秒拒绝PROCESS_IMAGE_AMBIGUOUS_MAIN_IMAGE，vmmap仍记录原Load Address。已测简化规则不保留原判断，不能直接接入生产。
4. 不把“缺少vmmap内部栈”作为唯一阻断描述。当前需要的是有因果依据的工具修复，或被证明等价的采集方案；这些仍未得到。

## 当前交付状态

- -06全部242文件、-07全部183文件逐项SHA不变；07冻结的158份生产文件仍与当前仓库一致。
- alpha color4h、监督器-B、身份/双观察/祖先链及5/16/60秒时限保持；八次启动、120秒单项、600秒累计、512MiB、单重型和零自动重试预算不变。
- 本轮未改生产代码或测试，未启动真实宿主、未重复整链、未冻结08、未激活09、未提交或推送Git。
- 本轮六角色协作完成不代表代码修复完成，更不代表真实工程闭环、M1、HY3或视觉验收完成。

## 后续任务边界

继续保留现身份合同。任何不同信任边界的提案，必须写明原主加载地址保证是否保留、实际反例及对任务所有权的影响，交用户选择后才能实现；本轮没有代替用户作此决定。不得因本轮原型失败就断言所有等价方法不可行，也不得继续无界重跑相同采样。

## 接收材料

- [六角色合同](evidence/20261023-coordination/contracts.md)
- [方向结论](evidence/20261023-coordination/direction-result.md)
- [原生依据与同目标反例](evidence/20261023-coordination/native-basis/REPORT.md)
- [采样结果](evidence/20261023-coordination/capture/result.md)
- [正式链准备](evidence/20261023-coordination/integration/readiness.json)
- [两位独立验收](evidence/20261023-coordination/independent-acceptance.md)
- [原件和源码保留核验](evidence/20261023-coordination/final-preservation.json)
