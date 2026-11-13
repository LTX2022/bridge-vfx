# -09 实际输出清单

本轮在 alpha 校准阶段停止，工程闭环未通过。没有生成球地面 HIP、NK 或主场景 EXR。以下五个文件是已停止真实作业生成的校准 EXR，完整解码不代表 alpha 校准通过。

阻断：`PROCESS_IMAGE_INVALID_STRUCTURE`；上游身份采集报告 `PROCESS_IMAGE_TOOL_FAILED`，husk started 回执缺少 `writer_process_binding`。

诊断 PNG 直接将线性通道数值限制到 0–1 后映射为 8 bit；未进行 OCIO、显示变换、曝光调整或反预乘，不能用于确认 ACEScg 最终显示效果。

| 实际文件 | 尺寸／通道 | EXR SHA-256 |
|---|---|---|
| [alpha-chart.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-09-authorized/alpha-chart/alpha-chart.exr) | 128×128，HALF RGBA | `e1278f61ab2bbce4b5de4838914f23f136797f0df37d077d3f1a8b9b3bffe392` |
| [over-black.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-09-authorized/alpha-nuke/over-black.exr) | 128×128，HALF RGBA | `44b571719e4a0457fd1bc907931fd9b44034915dc44efec6e1eb817437d2c39f` |
| [over-white.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-09-authorized/alpha-nuke/over-white.exr) | 128×128，HALF RGBA | `3354a5266af6c1546e6e39a5f013b8f4a1cf9a1ba88ac28808f4a1d26bf16b41` |
| [additive-black.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-09-authorized/alpha-nuke/additive-black.exr) | 128×128，HALF RGBA | `eef47c4bed7bbb6bbac6d5bed46a3cdb8476761cdc5acc40d7da9ef5f6cfeaca` |
| [additive-white.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-09-authorized/alpha-nuke/additive-white.exr) | 128×128，HALF RGBA | `515d6e0929438f9b2195b6c4f982792663b78eb56d9c239873a2bac500344562` |

[完整像素统计和结构审计](artifact-audit.json)

## 诊断预览

alpha-chart.exr：
![alpha-chart.exr 线性数值诊断预览](alpha-chart-rgb-linear-diagnostic.png)

over-black.exr：
![over-black.exr 线性数值诊断预览](over-black-rgb-linear-diagnostic.png)

over-white.exr：
![over-white.exr 线性数值诊断预览](over-white-rgb-linear-diagnostic.png)

additive-black.exr：
![additive-black.exr 线性数值诊断预览](additive-black-rgb-linear-diagnostic.png)

additive-white.exr：
![additive-white.exr 线性数值诊断预览](additive-white-rgb-linear-diagnostic.png)

alpha-chart 的 A 通道：
![alpha-chart A 通道线性数值诊断预览](alpha-chart-alpha-linear-diagnostic.png)
