# Graph process recovery：限定软件修复与实际证据

本轮源码只修改 `tests/helpers/graph_job_process_fixture.py` 和 `tests/unit/test_graph_job_recovery.py`；有写权限的 `tests/unit/test_graph_supervised_recovery.py` 无需修改，已实际复验。其余源码、根文档、移交登记、主 agent 的输出／登记实现均未写入。不提交 Git，不运行标准全量或真实 DCC／模型／仿真／缓存／渲染。此报告不宣布全 16 域 M1 完成。

## 先复现，再适配

Windows 不能运行原 POSIX 分支，因此首次复现明确是 **Windows 下的未绑定 direct-Popen 进程边界探针**，不是 POSIX 实跑：沿用既有 descendant 测试和实际 addon + FakeSourceHost，仅把调用端 launch_worker 换为受控 Python Popen，未伪造身份／producer／停止事实。

- `unbound-direct-before.stdout.log` 实际记录 construction_executed=false、reconciliation_required=true，journal UNKNOWN，错误为 `graph command producer requires an observed task-owned launch`。stderr 同时暴露裸 Popen 无 `.started`：原测试在平台分支前访问这个属性，POSIX 同样无法使用裸 Popen。首次探针退出 1，1 ERROR，45 秒超时未触发；原始失败保留。
- 修复后另做负对照 `unbound-normal-control`，受控 child 实际退出 **2**；正常恢复用例因 completion 不存在失败，journal 保持相同监督绑定拒绝。它只确认拒绝原因，不充作修复后的 POSIX 证据。
- `supervised-before` 实际 1 test 通过，退出 0；该模块没有新发现需修复的源码问题。

每次实际命令、解释器／平台、退出码、超时、耗时、日志 SHA 和前后相关源码 SHA 都保存在同名 JSON。stdout/stderr 是原始输出；成功运行的 unittest 输出在 stderr，stdout 可为空，不把空 stdout 当证据。

## 生产已有关系及合法测试路径

实际 addon 的 `_fx_producer_identity` 通过现有 `read_receipt` 验证当前监督器签名 started、operation/attempt/generation 和当前 worker PID；缺此关系必须拒绝。`launch_worker` 既有正式 `owned_process.launch` 能生成新密钥并建立这条关系，不能仅给裸 Popen 填环境变量或拼 launchfacts。

生产 POSIX `owned_process._supervise_owned` 的真实行为是：native child poll 已退出后，调用 native wait；随后 killpg(pid, 0) 检查自有进程组。若后代仍活跃，监督器返回 **2**，不写 stopped，不杀后代，也不持续等待后代。直接把该用例换成 OwnedProcessHandle 会导致 poll 永远缺 stopped，原“父退出后仍有后代→保槽→后代自行退出→恢复成功”的正常路径无法前进。

本轮在允许的进程边界作最小适配：

1. descendant 的 POSIX 调用统一经 `launch_worker`，仍由现有生产 `launch` 创建私有目录／新密钥／真实启动绑定。Windows 默认分支仍使用原监督句柄。
2. 只有 POSIX descendant 分支和显式边界验证启用 `SoftwareChildWaitHandle`。启动的是受控 Python 监督包装进程，它原样调用 shipped `owned_process.supervise`；仅把该模块的 Popen/WindowsJobProcess 原生进程边界换成继承实现。原 native wait 返回后记录 `software-child-wait.json`，包含已验证 started 对应的实际 child PID、attempt 绑定及实际 wait 退出码。
3. 该观察文件不是签名 launchfacts 或 stopped 回执，不填 launch/stop 事实，不改变 producer 及 completion 验证，不代表后代退出。生产监督器的所有签名、组查询、取消及退出逻辑仍由原实现执行。原生产模块文件未修改。
4. 测试句柄的 poll 仅表达实际父 child wait；GraphJobService 原 `_observed_stopped` 仍用 OS 捕获的 PID/PGID/SID 和 `owned_group_status` 决定是否释放容量。活跃同组后代继续占槽，只有 release 门使后代自行退出后才允许恢复成功。没有改用杀后代的后端。
5. POSIX 原用例增加真实观察断言：父退出码 0、监督器退出码 2、没有 signed stopped、后代实际 PGID/SID 等于原父 PID；保留原容量阻断、恢复成功和仅启动一次断言。`.started` 的 Windows birth 读取移入 Windows 分支。
6. 新增一个正常边界用例，在 Windows 也实际走监督包装路径，核对真实 started/stopped、父 native wait 退出码、构建成功、只创建一次和容量释放。该用例验证新增边界代码，不模拟 POSIX 系统调用。

这条 POSIX 恢复路径依赖**原控制端仍持有该 attempt 的直接 wait 观察句柄**，与原用例一致。若控制端也死亡，现有生产 POSIX 监督器在同组后代活跃时已退出且不会后来补 stopped；重新连接的 `_supervised_handle` 无停止回执仍须保槽。此机制不是本轮批准的生产改动范围，未声称该更强场景闭合。既有 supervised 模块测试的是控制端死亡时 worker 本身仍活跃、随后正常退出的另一场景。

## 实际结果（Windows / Python 3.11.9）

| 证据标签 | 实际执行 | 结果 |
|---|---|---|
| unbound-direct-before | 原 descendant 用例，显式未绑定进程边界探针 | 1 ERROR，退出 1；保留修复前失败 |
| supervised-before | 完整 test_graph_supervised_recovery 模块 | 1 test，退出 0 |
| windows-descendant-after | 原活跃 owned descendant 用例 | 1 test，退出 0 |
| native-wait-after | 新增正常 native wait 边界用例 | 1 test，退出 0 |
| windows-affected-final | 最终受影响定向组，含完整 supervised 模块 | **8 tests，0 failures，0 errors，0 skips；退出 0；16.992 秒** |
| unbound-normal-control | 修复后保留未绑定负对照 | 1 FAIL，退出 1；实际 worker 退出 2 |

最终 8 项包括活跃后代保槽、新 wait 正常链、完成后控制端持久化失败恢复、node effect 后丢回复不重放、journal 提交前进程退出 93、取消未确认保槽、重连不终止非自有句柄，以及控制端死亡后恢复不重放。前三轮成功单项／模块在最终组内，不累计成不同用例。单项运行外层超时 45 秒，最终定向组外层超时 90 秒；原 worker/descendant 门和测试 wait 继续有界。所有运行均未触发超时。

最终运行前后相关源码 SHA 完全相同。`git diff --check -- tests/helpers/graph_job_process_fixture.py tests/unit/test_graph_job_recovery.py tests/unit/test_graph_supervised_recovery.py` 退出 0。旧报告的 29 项模块通过未重跑、未转称本轮最终 30 项模块通过；本轮只执行上述受影响组。

## 源码绑定

下面从首次复现前和最终定向运行后的 JSON 对比，属于本轮增量；Git 中 helper 的累计差异还包含此前已经接受的实际 addon 替换，不把它全部归给本轮。

| 源码 | 本轮前 SHA-256 | 最终 SHA-256 |
|---|---|---|
| tests/helpers/graph_job_process_fixture.py | 77684e0d475fa097903348e371db7f744e2e1def63b3c4b25ff43cdba4bc7ac6 | f1c7c1d2aea2237e88560db4bfcea6f9b5dfc587a0cba44bcda04c9229a36f6b |
| tests/unit/test_graph_job_recovery.py | cdfc8669cc27655d96658e91106b1d22d0da4bd230c13cc9c25befdaacd8df29 | ea9a51f07745bd92b7148445a7e77406455a5b98aeb867e3d2d26d02e98c1401 |
| tests/unit/test_graph_supervised_recovery.py | 33e5f7bf237d3d1d7fce4621ed17b1d94251348db7b34bb8ef3a88ff1a743071 | 33e5f7bf237d3d1d7fce4621ed17b1d94251348db7b34bb8ef3a88ff1a743071 |

各 JSON 同时记录四包全部 Python 源码、addon、相关 helper/test 的 SHA；所捕获相关生产源码在首次复现和最终组间没有变化。仅导出命令、日志、SHA 和裁剪后的负结果／journal 状态；不复制 receipt.key、authorization、签名回执或原始 runtime。

## POSIX 待目标机器验证

**POSIX 当前 NOT_RUN，不是 PASS。** 目标机使用当前源码与明确的软件底层替身，执行：

```sh
python3.11 -B -X utf8 outputs/common-closure-20261009/process/run_bounded.py posix-target test_graph_job_recovery.RecoveryTests.test_exited_parent_with_live_owned_descendant_keeps_capacity test_graph_job_recovery.RecoveryTests.test_native_child_wait_transport_keeps_real_supervisor_and_completion test_graph_supervised_recovery --timeout 90
```

该 label 在本轮未使用；运行不得覆盖既有证据。需确认父退出 0、监督器退出 2 且没有 stopped、活跃同组后代保槽、后代自行退出后容量释放及 SUCCEEDED、不重放 node effect；macOS 的组观察、孤儿／僵尸回收行为尤其需要目标机事实。无合法停止观察就保持阻断，不伪造事实或扩改生产实现。

软件定向证据有限通过；安装、新发布包、完整全域 M1、真实宿主、模型路线、视觉及生产验收均未由本轮验证。
