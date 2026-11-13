# OCIO parent preflight collector — 2026-10-13

只实现 packages/houdini-bridge/src/houdini_bridge/render_ocio_facts.py、tests/unit/test_render_ocio_facts.py 及本证据目录。未改 addon/client、镜像或原 Desktop 主工程；未提交。原缺失模块通过本目录 baseline 日志实际复现，退出 1。软件替身仅覆盖底层 HOM、OCIO 和文件 API。

## 冻结接口

```python
collect_ocio_configuration(hou_module, *, final_output_path: str,
                           ocio_module=None, transform_requests=()) -> dict
validate_ocio_configuration(fact) -> None
```

transform_requests 是 list/tuple，最多 16 个 `{label: str, source: str, destination: str}`；三字段非空、标签唯一。仅由调用者提供两端已观察到的 Product/Var raw USD 值。没有来源优先级、输出回退、默认 alpha 或有效 writer 推断。没有请求时仍可观察最终输出路径的 file-rule 求值，但不会据此生成 processor 请求。

JSON 根字段：schema=`bridge.houdini.ocio-preflight/1.0`、source=`parent_houdini_preflight`、final_output_path 原样、reconstruction_scope=`reloaded_config`、dependency_scope=`explicit_reconstructed_processors_only`、transform_requests、config、dependencies、api_facts、missing_facts。

config=`{path: HOM观察字符串或null, file: 文件事实或null}`；dependencies 是去重的文件事实列表。**文件事实固定为 `{path: 绝对本地规范路径, bytes: 非负整数, sha256: 64位小写摘要}`**。api_facts 按实际调用记录 `{observed: bool, value?: 有界JSON, error_type?: 异常类型}`，不复制异常消息/环境。对象 getter 成功只记 observed，不序列化原生对象。可比较的配置/Context/processor cache ID 是原生缓存标识，不能替代文件摘要。

Config.CreateFromFile 只使用 hou.Color.ocio_configPath 实际返回路径。空、builtin、相对、缺失、不安全或超限路径留下 CONFIG_FILE_UNOBSERVED；PyOpenColorIO 未传则只尝试正常导入，缺失成为 API gap。不会猜安装路径或用环境变量代替 HOM 路径。

显式请求调用重建 Config.getProcessor(context, source, destination)，只观察其 getProcessorMetadata().getFiles() 提供的文件名。由同一重建 Context.resolveFileLocation 解析后读取实际文件字节；没有 config 全盘 LUT 扫描、扩展名猜测、自动 source/destination 选择或 ABI 探索。成功 getFiles 空列表可以作为该重建 processor 的无外部文件观察；未知 getter 不伪造空列表。

validate 检查根 schema/source/scope、路径观察一致性、请求/API/gap/file 形状、重复文件和预算，核对 dependency 具有 API 解析参考，再重读所有已记录文件。已观察文件修改、删除、变成不安全路径或摘要/长度漂移均 ValueError；合法缺项本身不导致失败。它不认证事实来源，不检查 Houdini PXL 当前内存状态，也不签发输出准备或完成证明。传入 final_output_path 必须与调用者当前计划另行比较；校验器仅能检查该事实内的路径格式。

## 有界与证据边界

最多 32 个文件（含 config），单文件 8 MiB，总字节 32 MiB；每个 API 字符串最多 8192 字符；规则/原生列表最多 64 项；processor 参考共享最多 128 次；missing_facts 最多 64 项。祖先 symlink/reparse、非普通文件、UNC/device/ADS 路径、父路径穿越、超预算拒绝或 gap。读取前后检查文件描述符、文件身份/大小/mtime/ctime 和祖先身份，读取中也限字节；观察到的竞态不发布有效文件摘要。跨平台 reparse 常量有 getattr fallback。

这些预算约束 Python 采集/哈希；同步 OCIO 原生 parser/getProcessor 内部工作不具有本模块可证明的时间、内存或 IO 上限。重建 API 调用不是缓存中 PXL 配置或真正 writer 执行证明。文件稳定观察是有限快照，调用者须在 pre/post frame、seal/consumer 的实际边界重新验证；本模块不自行接入这些边界。

永久保留 PXL_EFFECTIVE_CONFIGURATION_UNOBSERVED、DEPENDENCY_CLOSURE_UNOBSERVED、CONTEXT_VARIABLE_VALUES_UNCOLLECTED、WRITER_COLOR_ALPHA_UNOBSERVED。context 只读 cache/search/working-dir，未枚举可能包含全部环境的变量值。完整依赖闭包、有效 writer、颜色/alpha、真实宿主、安装、视觉、生产验收均未提升。

## 原生签名核对

- 静态基准：handover/evidence/20261010/closure/native-output/REPORT.md。
- 实际只读本机 H21.0.631/H22.0.429 `houdini/help/hom.zip!hou/Color.txt`：ocio_configPath :128、spaces :123、activeDisplays :133、activeViews :138、roles :148。roles 文档明确 tuple of str；spaces 文档列表且示例元组。两版 `toolkit/include/HOM/HOM_Color.h:79–84` 进一步声明这些列表为 std::vector<std::string>，没有 role→colorspace map。未知字典形状诚实记录 API_READ_FAILED/ValueError。
- H21 Color.txt SHA-256：`5c585a264795d9d3ff053afc8bb500a48186b16c6b8919d872b91cc0b4518260`；H22：`0d826bc346e925a8c547d05c3c4fe8f99312748f7aabffc800acb8696bc7c733`，与静态基准一致。
- [SideFX HOM 官方文档](https://www.sidefx.com/docs/houdini/hom/hou/Color.html) 核对同样签名。没有运行 hou、hython 或 husk 来探测。
- [OCIO v2.4.2 Config 官方 Python 文档](https://opencolorio.readthedocs.io/en/v2.4.2/api/config.html)、[Context](https://opencolorio.readthedocs.io/en/latest/api/context.html)、[FileRules](https://opencolorio.readthedocs.io/en/v2.4.2/api/rules.html) 支持 CreateFromFile、cache/context/search/working-dir、规则字段与显式 processor getter。
- [官方 PyConfig.cpp](https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/v2.4.2/src/bindings/python/PyConfig.cpp#L608) 确认 file-rule 返回 `(spaceName, ruleIndex)`，不是单个颜色空间字符串；同文件 :638 确认 context/src/dst 三参数重载。
- [官方 PyProcessorMetadata.cpp](https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/v2.4.2/src/bindings/python/PyProcessorMetadata.cpp#L40) 确认 Python API 为 getFiles()，返回支持 len/index 的 FileIterator；[PyProcessor.cpp](https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/v2.4.2/src/bindings/python/PyProcessor.cpp#L36) 确认 getProcessorMetadata()。不照抄 C++ getNumFiles/getFile。实际 binding 不支持时留下 gap。

## 验证

仅执行本目录 run_checks.py 包装的 scoped unittest discover，pattern=test_render_ocio_facts.py。日志记录 Python 路径/版本、实际 argv/cwd、UTC、两个自有源码 SHA-256、原始输出及真实子进程退出码；最终日志补充自有源码前后 hash 一致性。不扫描/冻结其他写入者源码，中心测试与最终集成来源绑定由主实现者处理。

当前 26 tests 通过、退出 0、无 skip；覆盖静态基准、中文空格路径、准确 API 参数与 file-rule 结果、重复/空/缺失 metadata、无模块/未知 API、无 false AVAILABLE、配置/LUT 内容漂移（保持 mtime）、缺文件、文件/总量/数量预算、畸形合同/文件事实、reparse/symlink 底层替身、增长竞态与重建期间配置漂移，以及模拟 POSIX stat 缺 Windows 常量。未运行全局测试、真实 DCC/HY3/render/sim；macOS 实机验证 NOT_RUN。

冻结日志：[unit-20261013T053119776698Z.log](unit-20261013T053119776698Z.log)，26 tests、退出 0、owned_source_unchanged=true。模块 SHA-256：`dcb6f361cf5452ffdab51e82a8b48f13d1d1df142ce81845f1d25fcdd60244a8`；单测：`c67e5085582194860104b7b5f1bd8b501580869b677407202708071acca0c51f`。此后停止自有源码写入，供主实现者镜像/正式定向测试及独立审查。
