# 本次实际产物

真实 alpha 校准：数值规则复核通过，associated=true；5 个 EXR 全块解码通过，当前文件字节数与 SHA-256 均匹配原始采样记录。原始观察 JSON 哈希匹配校准结果。

| 文件 | 尺寸 | 字节数 | SHA-256 |
|---|---:|---:|---|
| alpha-chart.exr | 128×128 | 142437 | `6f64f756d8d0d7a7fcbea4b3d956b211e52b1e8ef47b25bcff1114d052eca860` |
| over-black.exr | 128×128 | 10766 | `95da9ae2ae71df0b6722adae0eda3255a67ab611127667bcd8f3c4db8558dfad` |
| over-white.exr | 128×128 | 9402 | `55408dc4f533896498e33ab84f3925c25b65367e756b5cd9e7682eae4927122f` |
| additive-black.exr | 128×128 | 6630 | `eef47c4bed7bbb6bbac6d5bed46a3cdb8476761cdc5acc40d7da9ef5f6cfeaca` |
| additive-white.exr | 128×128 | 7142 | `515d6e0929438f9b2195b6c4f982792663b78eb56d9c239873a2bac500344562` |

alpha=0、0.5、1 时，源 RGB 分别为 0、0.39990234375、0.7998046875（三通道相同）。黑底输出相同；白底输出分别为 1、0.89990234375、0.7998046875。

加色探针 alpha=0，RGB=(0.125, 0.0625, 0.25)；黑底保留该值，白底=(1.125, 1.0625, 1.25)。

主工程 HIP、composite.nk、main.0001.exr、nuke.0001.exr 均未生成。本次图像为实际 alpha 校准产物，未形成球与地面工程结果或主工程 Nuke 消费验收。

![实际 alpha 校准预览](alpha-preview.png)

预览仅把实际 EXR RGB 线性数值裁剪至 [0,1] 映射到 8 位；未施加显示色彩变换，超过 1 的 HDR 数值仅在预览中裁剪。数值与校验详见 [artifacts.json](artifacts.json)。
