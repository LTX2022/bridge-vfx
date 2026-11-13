# 第 12 轮实际产物

本轮实际文件为 alpha 校准场景 USDA 和一份校准 EXR。按执行者终态回报，校准绑定失败；工程闭环未通过。

| 文件 | 尺寸／通道 | SHA-256 |
|---|---|---|
| [alpha-chart.exr](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-12-authorized/alpha-chart/alpha-chart.exr) | 128×128，HALF RGBA | `d5ca11556f3a124e69ab630ce848bbb1f3adce1b46ddc9e84c93ace4b09b5559` |
| [alpha-chart.usda](/Users/user/Documents/Code_Project/Bridge/outputs/engineering-closure-20261023-h21-12-authorized/alpha-chart/alpha-chart.usda) | alpha 校准场景，5199 字节 | `b274f68351ee547e31f188f0fbb2329bdb39e3a280c71c0719cb23f289909189` |

EXR 已完整解码，共 16384 像素、65536 个通道样本，全部有限。中心像素 (64, 64) 的 alpha 为 0.5；RGB 为 (0.39990234375, 0.39990234375, 0.39990234375)。EXR 与 USDA 读取前后 SHA-256 一致。

HIP：**NOT_REACHED**；NK：**NOT_REACHED**；主场景 EXR：**NOT_REACHED**。

PNG 将原始线性数值限制到 0–1 后直接映射为 8 bit；未使用 OCIO、显示变换、曝光调整或反预乘，不能作为 ACEScg 显示变换或视觉验收。完整解码和有限像素不代表校准、身份绑定或工程闭环通过。

[完整审计](artifact-audit.json)

RGB 线性数值诊断图：
![RGB 线性数值诊断图](alpha-chart-rgb-linear-diagnostic.png)

Alpha 线性数值诊断图：
![Alpha 线性数值诊断图](alpha-chart-alpha-linear-diagnostic.png)
