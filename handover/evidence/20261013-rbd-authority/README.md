# R05 本批冻结证据

本目录对应 [修复报告](../../RBD_AUTHORITY_20261013.md)，包含353个原件，原始总字节5732653。归档逐个解码并校验原始SHA/长度及归档SHA；保留诊断失败和跳过，不覆盖旧批材料。不包含运行签名私钥、凭据或完整进程环境。

- [源码和实际命令](source-binding.json)：最终97方法集成及两版正式流程均退出0、无失败/错误/跳过，源码前后相同。
- [原件索引](index.json)：每项原始路径、归档路径、SHA、字节及identity/gzip编码。
- [最终独立复核](raw/outputs/rbd-host-20261013/review/ERROR_CODE_CLOSURE.md)：425项当前源码及各135项生成快照均一致；五项具体缺陷及公共错误码问题限定关闭。

`raw/outputs/all-domain-20261009/` 保存全部本批中央runner阶段原日志/摘要。`raw/outputs/rbd-host-20261013/` 保存collector与authority定向命令、失败原件、同build静态接口依据、正式生命周期及复核探针。大文件除Markdown外以gzip封存，原内容须按index的encoding还原；原报告内相对链接沿用原路径，可用index寻找归档对应项。

读取基准是固定底层packed几何，零幅度正常，非零未执行VEX所以拒绝并回滚；保存参数的新PID直接读回后，没有verified R05 checkpoint的接管正确拒绝。新PID正向R05恢复、真实DCC/VEX/Bullet/渲染/模型、macOS及全16域接收仍BLOCKED或NOT_RUN。

中央runner未覆盖native_schema_test_boundary的完整before/after；另存当前摘要并核对与上一G03绑定相同，不把静态依据当实际原生运行。
