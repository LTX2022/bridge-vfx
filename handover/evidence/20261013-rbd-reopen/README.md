# R05可信恢复批证据

本目录封存195份原件，原始总字节数7,587,175。`index.json`列出原路径、字节数、原件SHA256、归档路径、归档SHA256和压缩方式；全部归档均已解码核对原件摘要。`source-binding.json`绑定最终34方法和正式两版本的实际命令、系统/解释器、428项相同源码，以及外部静态边界的单独当前摘要。新增本说明不计入原件195份。

大于8192字节的非Markdown原件使用gzip；Markdown保持原文便于查看。按索引的`archive`路径读取，`encoding=gzip`时先解码，再核对`sha256`。原Markdown中的相对JSON/log链接可能需按索引查找对应`.gz`文件。

独立复核为 [CLOSURE.md](raw/outputs/rbd-reopen-20261013/review/CLOSURE.md)，源码和实际日志限定为PASS_SCOPED。早期缺接口、并发源码变化、只读HIP写入PermissionError和整改前阶段结果保留为诊断，不提升为当前PASS。首次170次集成有13次重复导入；最终34方法均为唯一ID。

归档不含运行签名密钥、完整环境或认证配置。实际停止事实由测试在运行时通过OwnedProcessHandle核验；本目录可复查事实/测试/字节摘要，不能在缺签名密钥时自行宣称重新完成离线签名验证。

固定底层几何、零幅度、Python/TCP/Windows Job验证不等于非零VEX/Bullet、真实DCC、渲染、macOS、安装或全16域接收。详见 [本批修复报告](../../RBD_REOPEN_20261013.md)。
