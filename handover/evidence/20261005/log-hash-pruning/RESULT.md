# 日志摘要扫描优化

实际只读比较先调用原tools/run_logged.py，再对相同根源码采用os.walk提前剪除既有EXCLUDED目录。两次摘要相同，实际纳入762文件；原耗时10.437秒，剪枝参考0.125秒。这是单次本机目录枚举/摘要比较，不是整个项目提速倍数；原测量工具输出已在主控调用中保留，没有为其补造运行前来源摘要。

最小修复仅将排除目录从“遍历后过滤”改为“进入前剪除”，保留大小写敏感的POSIX逻辑路径排序、文件字节摘要及算法名。PathLike实际路径使用剪枝；已有用于跨平台排序验证的非PathLike路径适配器保留原rglob接口。

首次命令：`.venv/Scripts/python.exe -X utf8 -B outputs/windows-next-20261005/integration/run_directed.py log-hash-pruning`。7项，0FAIL/ERROR/SKIP，外层0.438秒，退出0。独立复核随后发现os.walk默认吞扫描OSError的P2-LHP01，最小增加onerror，保留原PermissionError处理并传播其他异常。最终命令为同runner的`log-hash-errors`选择，8项、外层0.344秒退出0、无失败/跳过；日志及前后源码摘要在../integration/log-hash-errors.log和result-log-hash-errors.json，P2获独立限定关闭。

新用例实际观测scandir，确认全部排除目录都未进入；实际开流和迭代EIO边界均向上传播同一原异常实例，没有返回不完整摘要。既有Windows/POSIX逻辑排序、内容变更和日志真实退出码合同全部保留。原7项日志不覆盖、不混作最终8项结果。

修复后对当前根源码的独立一次实际摘要耗时0.094秒，SHA为aaa3e577207c935b60ab311ed1cfb73f7e5c155d3e63a78c699341cb3e5d38ac。该摘要仅绑定当时源码，后续修改需要新摘要；没有据此提升M1或安装状态。
