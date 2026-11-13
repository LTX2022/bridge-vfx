# 官方 Karma 对照：执行前审查

日期：2026-10-27。状态：**SOFTWARE_PREPARED_AWAITING_EXPLICIT_NATIVE_AUTHORIZATION**。

软件准备与限定独立复核完成。官方案例真实启动数为0，尚未生成本案例的可用HIP、NK或渲染结果。此前范围29的交付文件重新核对SHA，保持不变。

## 固定范围

Houdini21.0.631随附DiskLight案例，frame 1、420×300、Karma CPU、H21 OCIO／ACEScg、HALF RGBA，关闭降噪和运动模糊。13个原件复制在候选的`official-inputs/`，安装原件不变。原31节点、22个SOP及原连线保持核对；两侧各有一个固定Beauty输出作者，Bridge注册图为35节点／30连线。Beauty仅为大写`/Render/Products/Vars/Beauty`。

首次原生启动后固定同一scope binding、记账根、源码、原件、允许规则及容差。官方保存／冷开观测须由原始宿主身份与签名停止证明封存，后续配置和运行清单依照固定规则派生，初始scope、runtime-bindings和run.json不回写。输入或源码需要改变时结算并停止本次实验，不自动续建范围。

## 准备验收

| 项目 | 已核验结果 |
|---|---|
| 软件回归 | Python3.11，164项定向回归通过；包含原件／观察、签名封存、派生输入、命令接口、预算、旧HIP合同、图像政策及Nuke消费配套 |
| 静态原件审查 | 全局启动、会话、嵌入定义、31节点69成员及相关HDA回调已分类；确有代码的非选中着色器章节不被描述为无代码 |
| 冻结身份 | 192项案例冻结、213项运行冻结逐一匹配；独立复核未发现新增确定P1/P2 |
| 显示链预检 | 同一冻结Python3.11.16加载H21 PyOpenColorIO2.4.1并构建指定processor通过；曝光仅从官方CPU结果计算，在Bridge结果产生前固定 |
| 预算与权限 | 签名账本零启动、零票、未关闭；`execution_authorized=false`；候选逻辑占用72,849,380 bytes（约69.5 MiB） |
| 派生输入 | `official_derivation_pending=true`；当前没有建图配置或伪造封存结果，server会在封存验证前拒绝建立执行facade |

另有既有`test_graph_job_frozen_inputs`的一个断线重接断言未通过：测试要求整个intent_json不变，而现有显式围栏重调度更新两个期限字段。相关测试及生产文件均与HEAD一致；该结果保留给后续恢复阶段，本次零重试新运行不使用该重接路径，恢复能力仍未验收。

## 具体审查身份

- 候选：`outputs/official-karma-disklight-h21-candidate-20261027-02/`
- scope SHA：`442a93b5941647786af0c04fe469d10a2a856438bff431632fcd9b7317381b54`
- runtime-bindings SHA：`78cc78c6cf4fbb9696fa3c76fe410f9c8c85ccd6e7359b248e99601786fb1c63`
- [激活审查原件](../outputs/official-karma-disklight-h21-candidate-20261027-02/engineering-activation-review.json) SHA：`3e9d86435de4faf46ff788bfde8a47daabe7815a450041939d81bed3a205671d`
- 待授权目标：`outputs/official-karma-disklight-h21-20261027-01/`，尚未创建或激活。

## 待明确批准的统一预算

整实验最多**11次原生启动、600累计记账秒、512MiB**；每操作最多120秒，同时最多1个重操作，**零自动重试**。包括失败、宿主存活、子渲染和停止清理。它不是各阶段各自领取的额度，600秒能否完成仍需实测。

| 顺序 | 真实操作 | 启动数 |
|---|---|---:|
| 1 | 官方HIP打开、允许输出设置、观察、保存、退出 | 1 |
| 2 | 独立hython冷开、复核、仅导出USD、退出 | 1 |
| 3 | 唯一官方husk CPU基准渲染 | 1 |
| 4—5 | 新420×300路线husk标板与Nuke实际采样 | 2 |
| 6 | 正式注册图GraphRun构建 | 1 |
| 7—8 | Houdini任务宿主保存、退出后独立冷重开 | 2 |
| 9 | 冷开工程的主husk渲染与登记 | 1 |
| 10—11 | Nuke任务宿主保存NK、独立Nuke冷开渲染与登记 | 2 |

任何字段、资源、模板、签名、停止或预算验证不通过即停止；未知停止保留槽位。未经具体授权不激活或启动上述软件。

## 真实验收出口

按[执行计划](OFFICIAL_KARMA_COMPARISON_PLAN_20261026.md)逐步取得官方CPU HIP／EXR、Bridge HIP、NK、Bridge／Nuke EXR和统一显示预览。每个阶段保留原始身份、文件SHA、签名停止和登记可用性。

官方CPU对Bridge：线性RGB nRMSE≤0.05，alpha MAE≤0.005、P99≤0.05；结构浮点误差≤1e-6，整数精确。Bridge对Nuke：504,000个RGBA通道样本逐一相同。全部原生进程可信停止且总预算内完成后，技术结果仍需独立人工视觉确认。

[本次软件准备证据](evidence/20261027-official-karma-readiness/result.json)与[静态审查](evidence/20261027-official-karma-readiness/static-review.json)提供当前完整记录。
