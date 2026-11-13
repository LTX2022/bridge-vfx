# 本次Git内证据（2026-10-10）

本目录是精选既有日志、结果JSON与独立复核的原字节副本。`index.json`列出每个目标文件的原路径、字节数和SHA-256；不重新运行、补签、覆盖原日志或把BLOCKED改为PASS。

`source-binding.json`记录本次变更Python文件的工作区SHA与Git暂存blob SHA。运行日志绑定当时磁盘字节；Git沿既有规则归一化源码换行，不能把归一化后的字节哈希直接冒充原运行哈希或一次新测试。证据目录关闭换行转换，暂存原件的22个SHA已逐一核对。

- `all-domain/`：127项共用定向、13项stash、21项拒读/输出、最终正式恢复通过，以及修复前十项失败组。
- `closure/review/`：共用链与最终快照读限定独立复核。
- `closure/process/`：Windows八项受影响恢复及目标机未验证范围。
- `closure/domain-worker/`：Crowd两版实际失败与fields原件调查；正常失败不变。
- `closure/geometry/`：G03独立component、十三项验证与未接线说明。
- `closure/native-output/`：静态原件调查，不替代实际输出事实。
- `closure/save-adapter/`：当前SAVE原件适配范围、方法与限制说明。

软件签名密钥、authorization、凭据、整个runtime/源码快照、HIP/EXR和producer原件不在本目录。文件中的绝对路径只定位当时本机来源；复制报告和结果不能替代完整原件验签或证明新源码完整通过。历史输出目录链接可能只在原机器有效，本目录通过index映射已携带的原件。

总目标、提交范围、结果与剩余工作见 [本次提交说明](../../COMMIT_REPORT_20261010.md)。全16域M1、48+2、完整安装、真实DCC、模型、视觉、生产及macOS目标机均未由这些部分证据接收。
