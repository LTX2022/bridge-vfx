# vmmap 进程身份采集诊断结果

**超时已重复复现，内部根因仍未定位；未实施代码修复，未重新冻结候选。** 当前保留-07未授权候选，完整软件集成仍未通过。本轮未启动真实宿主。

## 当前事实

- 普通Python3.14进程调用正式 `observe_process`，首次复现vmmap 5.061秒超时。
- 有界诊断最多10个新进程、90秒；实际在21.366秒内第5个目标复现后停止。该次vmmap 5.005秒超时，进入时观察预算尚余15.992秒。
- 采集器未读取到vmmap的stdout/stderr；外部采样时vmmap为Rs、Python为Ss。失败时的sample文件Call graph为空，不能确定内部停留位置，也不能认定与原H1第二次采集失败具有同一根因。
- 其余管道计时和默认/forkCorpse对照能成功，但没有证明任何代码修改可以消除失败。默认vmmap已使用corpse。

## 验证与交付边界

独立Bugbot只读复核未发现可定位的P1/P2代码根因，同意保留阻断。没有延长5秒工具、16秒观察、60秒祖先链时限，没有削弱任何身份检查。生产代码、发布镜像及测试未修改，因此未重复全量测试或整链。

-06全部242文件、-07全部183文件逐项同SHA；原alpha修复、监督器-B修复与八次启动/120秒单项/600秒累计/512MiB预算保持。没有生成-08、激活新范围、运行DCC、提交或推送Git。

本次偏离预期交付的是：缺少支持因果修复的故障栈，因而无法交付“已修复的新候选”。下一步仍是捕获慢vmmap内部调用位置，再据此选择保留同等身份强度的采集修复；不能将偶然成功当整链通过。诊断脚本已保留，要求使用全新输出目录，避免覆盖证据。

## 证据

- [诊断明细](evidence/20261021-vmmap-fix/diagnosis.md)
- [直接捕获的超时](evidence/20261021-vmmap-fix/bounded-final-capture/target-4.json)
- [有界采样汇总](evidence/20261021-vmmap-fix/bounded-final-capture/summary.json)
- [可复用捕获脚本](evidence/20261021-vmmap-fix/capture-fresh-observe.py)
- [独立复核](evidence/20261021-vmmap-fix/independent-review.md)
- [原件保留核验](evidence/20261021-vmmap-fix/final-preservation.json)
