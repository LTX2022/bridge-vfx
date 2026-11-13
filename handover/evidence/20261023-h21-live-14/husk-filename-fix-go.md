# -14 Husk adapter 定位最小修复方向

**GO：仅软件整改。** 用当前执行帧的 `f_code.co_filename` 取得固定 adapter 的编译来源路径，替代 Husk 未提供的 `__file__`，有本轮真实事实和精确 Python 3.11 依据。-14 已失败封闭，不再启动真实 DCC；后续真实运行仍须新冻结 review、新授权。

## 因果依据

方向直接读取原件 `/Users/user/Documents/Code_Project/Bridge/handover/evidence/20261023-h21-live-14/execution/raw-alpha/child.stderr.log`。实际 traceback 的 `File` 为 -14 冻结快照中 `husk_runtime_ready.py` 的完整绝对路径，第 8 行 `Path(__file__)` 抛出 `NameError: name '__file__' is not defined`。这同时证明：本次 Husk 执行上下文没有该全局，但 Python code／traceback 已携带准确编译文件名。

运行团队回执为首 alpha 1/8、计费 8.059413 秒、PID 11967 exit 2、driver 9.2459 秒；无 runtime-ready／产物，owned 整组停止已独立认证。本方向不将该失败当作身份采集或 alpha 通过。

H21 自带 Python 3.11 标准库 `/Applications/Houdini/Houdini21.0.631/Frameworks/Python.framework/Versions/3.11/lib/python3.11/inspect.py:472,489,916–919,1751` 将当前 frame 的 `f_code`、code 的 `co_filename` 用于来源定位，且 currentframe 实现使用 `sys._getframe`。

Python 3.11 官方文档说明 `_getframe()` 的默认深度为当前帧；该 API 属 CPython 专用能力，不许缺失后寻找另一来源。`frame.f_code` 是正在执行的 code object，`co_filename` 是编译来源文件名；`compile` 的 filename 参数即产生该来源元数据。[sys._getframe](https://docs.python.org/3.11/library/sys.html#sys._getframe)、[frame 与 code 属性](https://docs.python.org/3.11/reference/datamodel.html#codeobject.co_filename)、[compile](https://docs.python.org/3.11/library/functions.html#compile)

## 唯一实现边界

- 只改 authoritative `husk_runtime_ready.py`、controller 镜像和受影响的软件 fixture／定向测试；其他源码若无同因证据不改。
- 在 adapter 自己当前执行帧读取 `sys._getframe().f_code.co_filename`，不用调用栈的外层 frame，也不依赖 `__file__`、`__name__`、`husk_command` 或原生 Python `sys.argv`。
- 先严格检查字符串、绝对规范路径、固定 adapter 文件名与邻接运行时位置；相对路径、`<string>`／空值、路径别名或链接、不存在的来源和接口不可用都走原失败关闭。不得把相对值交给 resolve 后从 cwd 补成路径；不得 fallback 到 cwd、PYTHONPATH 或调用方任意路径。
- 仅从已校验 adapter 路径的邻接 `owned_process.py` 执行既有 `runpy.run_path` 并调用同一 runtime_ready_and_wait。冻结 command／source hash 和原正式 admission 继续绑定脚本来源；编译文件名只是定位信息，不是身份 authority。
- 保留原异常打印与 `os._exit(2)`，runtime-ready 签名、nonce、PID、argv、完整 binding、非空 stderr 门、5／5／16／22／60 秒及真实 8／120／600／512 MiB／1 heavy／0 retry 全部不变。

## 复现与有限回归

原 fixture 用 runpy 执行 prerender，会自动写入 `__file__`，因此未覆盖实际上下文。H21 自带 `runpy.py:65–88` 明确在 exec 前设置该全局。

唯一实现者应先以 `exec(compile(adapter_source, actual_absolute_adapter_path, 'exec'), namespace)`、namespace 不含 `__file__` 复现旧版 NameError，再验证修后能进入同一 helper。fixture 使用实际固定绝对 hook 路径；不伪造 `__file__`，也不靠 host argv／husk_command 的未确认类型。保留相对／非规范／不可信编译来源负例及原 fail-stop 回归。

验证限最少受影响核心、该上下文红绿、镜像和一次既有无 image-model 八阶段软件链；不重复全项目、不新采样、不运行真实 DCC。两独审及新冻结后，仍不能写真实 H21 修复已通过。

## 同入口有限排查

已有限查看 fixed prerender adapter、邻接 owned_process、alpha preparation command、软件 prerender fixture，以及生成的 main Husk postframe 入口。直接依赖 Husk exec namespace 的 `__file__` 目前只在本 adapter。

`owned_process.py` 自身的 `__file__` 发生在 adapter 明确调用的 runpy.run_path 上下文，标准库会提供它；不属于本次缺失全局。生成的 postframe 顶层脚本使用冻结 source_roots 导入普通 `render_writer_facts` 模块，顶层不读 `__file__`；该模块内部的来源检查属于正常模块导入。没有因果依据将这些改为 frame 定位，保持原实现。只需新增 fixture 的无 `__file__` 上下文以覆盖这一入口，不扩展全域或重构。

已向唯一实现者 `/root/ready13_impl` 发送边界，明确不覆盖其他工作、不运行 DCC。本方向仅只读取证与写本目录报告。
