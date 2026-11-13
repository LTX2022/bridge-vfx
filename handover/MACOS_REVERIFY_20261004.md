# macOS 复验清单（待目标机器验证）

最新 [输出逐帧配置与观察预算](OUTPUT_OBSERVATION_20261014.md) 在macOS仍为NOT_RUN。按下方配置项目Python3.11和`PYTHONPATH`，将原始输出写入新目录，依次执行以下两组；正式进程组单独调度，不启动真实DCC。逐帧1/1.25/2的格式读回、非法第3帧和超预算第5帧预拒绝、实际软件帧返回后样本漂移拒绝均须核对；17-AOV/128遍历与异常正文省略保留。第一正式方法覆盖两版，第二是H21正常恢复；平台停止事实使用实际POSIX监督器，不能填Windows Job默认值。

```sh
python -B -m unittest -v test_render_color_facts test_render_configuration_time test_render_ocio_facts test_render_ocio_binding test_houdini_output_receipts test_render_store_snapshot test_native_render_domains test_controller_entry_client_sync test_registry_formal_binding_required test_graph_render_registration_retry
python -B -m unittest -v test_render_time_process test_formal_domain_recovery.FormalDomainRecoveryTests.test_c_readiness_consumes_real_recovery_and_keeps_completed_stages_when_registration_blocks
```

记录退出码、无跳过、原始日志、当前源码和实际生成源码摘要；单次2MiB预算不代表全帧/整个producer预算，软件EXR/父OCIO不解除实际writer/filter/alpha登记阻断。当前macOS、真实宿主和完整发布仍未验。

2026-10-14 最新 [P01 冻结输入与可信恢复](PARTICLE_REOPEN_20261014.md) 仍待目标机器验证。配置下方项目 Python 3.11 和 `PYTHONPATH` 后，在新的日志目录执行以下两组；正式 OS 组单独调度。保存合同/snapshot 须共享，但 RPC、runtime、lease、sidecar 与可变 operations 须隔离；新 PID/nonce 从实际保存合同恢复完整 checkpoint，直接 collect，不重新 apply。缺失/自重摘要篡改 checkpoint、最后 gates/HIP/身份漂移均须拒绝。Windows Job 字段只在 Windows 断言；macOS 使用实际 POSIX 监督器停止事实，不填默认。真实 POP/DCC、完整发布与全域验收保持 NOT_RUN/INCOMPLETE。

```sh
python3.11 -B -m unittest -v test_particle_emission_inputs test_particle_emission_state_roots test_particle_emission_checkpoint test_particle_emission_registered_worker test_particle_emission_reopen_addon test_particle_emission_handoff_marker test_geometry_registered_worker test_controller_entry_client_sync
export BRIDGE_TEST_P01_AUTHORITY_ARCHIVE="$PWD/outputs/macos-reverify/p01-reopen-UNIQUE"
python3.11 -B -m unittest -v test_particle_emission_authority_process
```

为每次运行换新的 `UNIQUE` 路径，记录实际退出码、系统/解释器、源码和生成快照摘要；这份清单没有在本机执行，当前 Windows 软件结果不能计入 macOS PASS。

2026-10-14 [P01发射波动批](PARTICLE_EMISSION_20261014.md) 在macOS保持待目标机器验证。按本文件后续配置Python3.11与PYTHONPATH后，在仓库根执行 `python3.11 -B -m unittest -v test_native_particle_emission_program test_native_particle_emission_host test_particle_emission_addon test_native_particle_size_routing test_controller_entry_client_sync`。使用新日志目录记录退出码、解释器/系统、当前源码摘要；核对跨负/零/正时间秒桶、完整keys/语言/外推、严格界、时钟和出生门控漂移、persist后拒绝、建图失败CAS/fresh retry。此命令不依赖ignored outputs中的中心runner；当前Windows参数级结果不替代macOS，也不证明原生POP积分或P01新PID恢复。若需全core静态测试，Oceanfoam缺审计材料继续NOT_RUN，不填默认。

2026-10-13最新 [R05可信恢复批](RBD_REOPEN_20261013.md) 在macOS仍待目标机器验证。配置下方项目Python3.11环境后，执行 `python3.11 -B outputs/all-domain-20261009/run_tests.py macos-rbd-reopen-UNIQUE test_rbd_checkpoint test_rbd_reopen_addon test_rbd_reopen_review_guards test_controller_entry_client_sync`；使用新label及新`BRIDGE_TEST_RBD_AUTHORITY_ARCHIVE`目录单独执行`test_rbd_authority_process`。正式测试须先把Windows Job停止字段改为目标机实际POSIX进程组事实，不填默认、不沿用Windows PASS。核对完整checkpoint、公开直接读回、无重新apply、新PID/nonce、缺/篡改checkpoint拒绝、完成后异常与末端门控/实际几何/HIP漂移。当前Windows正向恢复只证明零幅度软件边界；真实非零消费、实际DCC和全域接收仍未运行或未完成。

2026-10-13本批待目标机复验见 [G03跨帧与原始输出采集](GEOMETRY_OBSERVATION_20261013.md)。按下方Python3.11环境配置后执行 `python -B -m unittest -v test_native_geometry_observation test_native_geometry_controls_host test_native_geometry_runtime_registry test_geometry_registry_checkpoint test_geometry_output_addon test_geometry_crossframe_addon test_geometry_reopen_addon test_controller_entry_client_sync`，再单独执行 `python -B -m unittest -v test_geometry_construction_process`；设置 `BRIDGE_TEST_GEOMETRY_INPUT_ARCHIVE` 为新的独立目录。核对两版负/零/正帧、原帧恢复、rest/current不一致拒绝、末端状态/声明参数/身份漂移、完整输出预算及新PID/nonce。仅受控Python进程和底层HOM夹具，不启动真实DCC；Windows结果不替代macOS。真实变形/下游执行和全域验收继续NOT_RUN/INCOMPLETE。

2026-10-13最新 [G03新实例恢复批](GEOMETRY_REOPEN_20261013.md) 仍待目标机器验证，macOS保持NOT_RUN。先按下方配置PYTHONPATH、项目Python3.11及解析后的本地临时目录，执行 `python3.11 -B outputs/all-domain-20261009/run_tests.py macos-g03-reopen-UNIQUE test_geometry_registry_checkpoint test_geometry_reopen_addon test_scene_transition_contract test_owned_headless_reopen test_software_scene_persistence test_r5_production_boundary`；再换新label执行 `test_geometry_construction_process` 的实际受控Python/TCP保存→确认退出→新PID/nonce链，设置新的 `BRIDGE_TEST_GEOMETRY_INPUT_ARCHIVE` 保留原件。必须检查输入/程序漂移、完成后身份漂移、回执落盘后异常、缺manifest补签和最终登记失败，且不能重新apply制造持久化。记录解释器、TMPDIR、退出码、源码及生成摘要，不把 `/var` 别名当作无symlink规范路径。通过仍仅为parameters_only，不证明真实DCC、实际变形/跨帧/下游或全域接收。

2026-10-13增量以 [G03接线与事务修复](GEOMETRY_WIRING_20261013.md) 和 [输出采集修复](OUTPUT_PREFLIGHT_20261013.md) 为准。目标机先按下方安装配置 `PYTHONPATH`，再用项目 Python 3.11 执行 `python -B -m unittest -v test_native_geometry_runtime_registry test_native_geometry_controls_host test_native_geometry_addon_wiring test_native_particle_ocean_geometry_domains test_controller_entry_client_sync`；核对输入漂移回滚、延迟读取帧变化、只读预检快照释放和中文/空格路径。正式软件进程复验使用 `BRIDGE_TEST_REGISTERED_DOMAINS=procedural_geometry_v1` 过滤现有 `test_production_task_hosts.ProductionTaskHostsTests.test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen`，证据写入新目录。G03实际变形/新PID登记、实际writer输出事实、真实宿主和全域验收仍缺；本机未执行macOS命令。

本机只完成 Windows 软件验证。macOS 结果全部为 **NOT_RUN／待目标机器**，不得从 Windows PASS 或历史日志推导。最新软件修复以 [2026-10-05 当前结果](../outputs/windows-next-20261005/RESULT.md) 为准；接手时带上当前补丁、源码摘要和原始日志，在 macOS 当前源码上执行以下命令。保持 Houdini 21.0.631、22.0.429 和 Nuke 17.0v1 合同；不启动真实 DCC、HY3、模型、仿真、缓存或渲染。本次仅更新清单，未执行下列命令。

## 安装与平台层

在仓库根使用项目隔离 Python 3.11，离线依赖需事先准备，勿安装旧源码 wheel 代替本批 editable 源码：

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install 'setuptools>=61' wheel
python -m pip install --no-build-isolation --no-deps -e packages/dcc-task-runtime -e packages/houdini-bridge -e packages/nuke-bridge -e packages/vfx-pipeline
python -m pip check
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
export PYTHONPATH="$PWD/tools:$PWD/tests/unit:$PWD/packages/dcc-task-runtime/src:$PWD/packages/houdini-bridge/src:$PWD/packages/nuke-bridge/src:$PWD/packages/vfx-pipeline/src"
mkdir -p outputs/macos-reverify
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name platform -- python -m unittest -v test_platform_support test_owned_process_supervisor test_task_host_lifecycle test_nuke_task_host test_houdini_http_security
```

核对 flock 跨进程互斥、持锁崩溃释放、进程身份查询、旧身份拒绝、子孙残留和监督器异常清理。停止须证据成立才释放槽位，无关进程保持存活。Windows Job 和 DACL 用例在 macOS 的 skip 不是 macOS 通过证明。中文和空格路径须覆盖。

## 原生边界与正式链

```sh
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name native -- python -m unittest -v test_native_domain_graphs test_native_render_domains test_houdini_parm_probe
export BRIDGE_TEST_REGISTERED_DOMAINS=material_lookdev_v1,lighting_camera_render_v1,rbd_destruction_v1,crowd_agents_v1
export BRIDGE_REGISTERED_DOMAIN_EVIDENCE_DIR="$PWD/outputs/macos-reverify/registered-domains"
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name reopen -- python -m unittest -v test_production_task_hosts.ProductionTaskHostsTests.test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen
unset BRIDGE_TEST_REGISTERED_DOMAINS
export BRIDGE_FORMAL_READINESS_EVIDENCE_DIR="$PWD/outputs/macos-reverify/formal-readiness"
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name controller -- python -m unittest -v test_domain_readiness_evidence test_domain_readiness_formal_contract test_c3_formal_entry test_feedback_versions test_readiness_cli test_graph_jobs
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name prepared-evidence -- python -m unittest -v test_readiness_prepared_evidence test_readiness_delivery.ReadinessEvidenceTests.test_prepared_claims_preserve_full_matrix_refusal
```

执行前从当前测试文件核对类和方法名。RBD 必须覆盖负、零、正激活帧、失败后帧恢复、外来驱动和错误外推拒绝、manifest 失败回滚。重开时确认旧 worker 已退出，新 PID/nonce 直接读 keys、gates、configure 几何，不重新 apply。材质关系或渲染配置任意一项损坏都必须拒绝，H22 过滤器也必须验真。

正式链核对最新 HIP 消费、owner、冻结计划、图版本、当前场景和保存摘要。登记重试不得增加实际渲染次数。正常成功路径必须运行实际软件监督器、TCP 和宿主服务。

prepared evidence 的 POSIX 停止证据须经实际签名／started 身份验证，并确认 owned_child_wait、正确 PID 和退出码；不要求 Windows Job 专属字段。目标机正向生命周期仍需实跑，不能用错误字段拒绝测试代替。当前保存 HIP、render scene 及其不可变 snapshot 必须绑定相同内容；基于 Windows 历史 HIP 的负例若在 macOS 缺少夹具而跳过，保持 SKIP 并以目标机两个真实不同保存内容补验，不能算 PASS。

## 2026-10-05 增量复验（全部 NOT_RUN）

Windows 最新有限结果：资源生命周期 5 项，包含两个真实隔离 Python 子进程；终态锚点 14 项；公开原生证据接线 29 项；图作业／typed registry 47 项。正式生成控制端读回 52 条 build/edit/inspect/save 原件并核对实际签名停止，完整输出登记仍 BLOCKED。粒子 P02 的 8 项只证明 parameters_only。各批不能相加为全量或迁移成 macOS PASS；全 16 域、approval_recovery、OCIO／输出／AOV／filter／beauty alpha 完整事实仍未闭合。

以下模块和方法已从当前源码核对，使用仓库根的隔离 Python 3.11、上面的源路径配置及目标机新日志目录。前三组为线程／文件／解析单元覆盖；不会替代正式进程停止证据。

```sh
mkdir -p outputs/macos-reverify/20261005
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name resource-owner-handler -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_graph_jobs.SoftwareResourceLifecycleTests test_graph_jobs.GraphJobServiceTests.test_default_close_reports_real_blocked_thread_and_keeps_slot test_graph_jobs.GraphJobServiceTests.test_in_process_drain_uses_remaining_original_budget test_graph_jobs.GraphJobServiceTests.test_expired_in_process_budget_gets_only_small_cleanup_allowance test_software_resource_failures
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name typed-public-locator -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_graph_job_public_native_evidence test_readiness_native_command_evidence test_graph_job_native_receipts
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name registry-source-required -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_registry_formal_binding_required test_registry_controller_source
```

- 资源 owner：真实后台线程 pending 时 API／环境／转交目录保留，正常及正文异常路径均须在实际线程结束后才清理；默认 1 秒 close 和原作业剩余预算不放宽，未知停止继续占槽。生成 handler 的 print／stdout／stderr 故障不能绕过 retained 退出；非 pending KeyboardInterrupt 原样传播。`test_software_resource_failures` 中 `_exit` 是显式边界 mock，观察／清理异常也是注入，不能算实际进程退出。
- typed primitive public locator：schema2 相对 locator 必须绑定 task／operation／graph／attempt token 和 generation；反复 sanitize 不泄漏私有路径。消费当前冻结 packet／producer 原件，拒绝 owner／session／generation 漂移、重复和重叠操作、路径越界、删除／重摘要篡改。正向 parser 用例替代了 `_prepared_stop_at`，只证明解析与 primitive 范围；缺监督器的同 PID 记录仍拒绝。macOS 正式 52 条原件发布／消费及实际停止接线仍 NOT_RUN，不能直接复用 Windows 固定目录审计脚本。
- registry 无 source：缺 `receipt_source_files` 的 Houdini typed fact 必须报 `REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED`，不产生 history／lookup 记录；source map 的冻结字节、第二来源 pin、错误宿主、缺配置及越界路径拒绝须保留。该负例通过不证明完整登记成功。

终态 anchor 模块使用实际受控 Python 文件 producer、codec 和签名监督器；未发现 Windows-only Job 字段硬断言，producer birth 校验仅在 Windows 分支启用。目标机需单独串行运行，与其他正式 Python／TCP／监督器作业共用一个执行通道；它不启动真实 DCC 或渲染。

```sh
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name terminal-original -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_houdini_output_receipts
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name swarm-inprocess -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_native_swarm_controls
.venv/bin/python3.11 -X utf8 -B tools/run_logged.py --log-dir outputs/macos-reverify/20261005/logs --name particle-p02-parameters -- .venv/bin/python3.11 -X utf8 -B -m unittest -v test_native_particle_size_program
```

anchor 须由当前存活 producer 封存，绑定原始启动 digest／签名 started、task／operation／配置／保存 HIP／帧／完整终态事实。相同内容重试不重写；EXR 与可变 store 同时重摘要仍拒绝；缺失／篡改原件不能由 controller 或 status 补签，旧绑定不能升级。OCIO／alpha 缺事实继续 BLOCKED，不填颜色或预乘默认值。Swarm 单元命令只验证同 PID 底层 API 的两版控制／冲突／几何合同；P02 只验证参数计划与实际参数读回，均不证明新 PID 重开或完整原生消费。

以下目标机进程项仍 **NOT_RUN／当前缺 POSIX 对应用例**，不提供会误计为通过的 Windows 命令：

| 项目 | 当前入口限制与 macOS 必验事实 |
| --- | --- |
| 资源 owner／生成 handler 的真实退出 | `outputs/windows-next-20261005/lifecycle/test_owned_lifecycle.py` 硬断言 Job0／child_wait_observed；`run_current_lifecycle.py` 写固定 Windows 审计目录。需 POSIX 对应正常 pending 与实际关闭 stdout 两例，停止前持有 API／目录／句柄，签名 started/stopped 同 PID／nonce、owned_child_wait、实际退出 2／进程组无残留，停止后才释放目录；业务未知槽仍保留。完整 generated MCP stdio、实际观察故障／KeyboardInterrupt 进程路线仍待验。 |
| Swarm S01/S02 新 PID | `test_native_controls_new_process.NativeControlsNewProcessTests.test_swarm_houdini21_new_process`／`test_swarm_houdini22_new_process` 有 `skipUnless(os.name == 'nt')`、Job0 断言及固定 Windows 输出目录；macOS skip 不算 PASS。需 POSIX 对应测试：保存→认证停止旧自有进程树→新 PID／nonce 加载同一 HIP，直接读完整 keys／seconds／noise／context／gates，第二进程不 build／apply，旧 nonce 拒绝。 |
| 材质全 11 控制新 PID | 当前 `test_material_controls_new_process.MaterialControlsNewProcessTests.test_material_houdini21_new_process`／`test_material_houdini22_new_process` 有 Windows guard／Job0／固定输出目录；两版Windows实跑与四方法discovery隔离已获限定独立接收。输入值在测试内显式定义，历史基准仅作来源标注，不读取旧结果生成成功。macOS 须有自身当前来源与 POSIX 两版用例，完整 11 项保存后新 PID／nonce 直接读原生材质关系／配置，不重 apply；上面的旧正式 reopen 命令仅覆盖 3 个材质控制，不能替代。 |

POSIX 对应用例须使用目标机新目录与当前源码冻结、实际签名监督器 child wait／进程组退出事实，不能把 Windows Job 字段删掉后直接计 PASS，或复用旧 HIP／manifest／签名 key。待用例接线与目标机实跑后再登记命令、退出码、日志和范围；真实宿主仍未授权。

## 全量和接收

后续 Plugin、私有上下文和安装整改使用同一源码复验，均不得启动真实宿主：

```sh
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name plugin-context -- python -m unittest -v test_agent_plugin test_private_context test_solver_sourcing_host test_skill_lifecycle_verifier
python tools/build_agent_plugin.py 0.1.0 --python-command python3 --output outputs/macos-reverify/agent-plugin
python tools/build_release.py 2.0.0rc1-macos --output outputs/macos-reverify/releases
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name install-normal -- python tools/verify_skill_lifecycle.py --release-dir outputs/macos-reverify/releases/v2.0.0rc1-macos --output outputs/macos-reverify/install-normal.json
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name install-readonly -- python tools/verify_skill_lifecycle.py --release-dir outputs/macos-reverify/releases/v2.0.0rc1-macos --readonly-files --output outputs/macos-reverify/install-readonly.json
```

Plugin 解包后按 docs/agent-plugin.md 显式配置诊断图，并在独立 Python 进程完成 stdio 握手、工具列表、health 与范围受限的合成上下文查询。宿主 UI 是否实际加载 Plugin 另列验收，不能以手工启动同等 MCP 命令替代。保留空包拒绝、授权检查前无宿主启动、外部预加载模块拒绝和极端日期错误后的会话继续四项故障覆盖。

平台及定向稳定后，在目标机运行一次标准软件全量：

```sh
python tools/run_logged.py --log-dir outputs/macos-reverify/logs --name full -- python tests/run_tests.py
```

保存命令、真实退出码、原始日志、解释器与系统版本、源码和生成快照摘要，分类失败与跳过。不得把平台不适用、环境缺失、未执行或旧日志标为 PASS。若发现与平台有关的缺陷，按原文件所有权最小修复并重新复核受影响部分；本批及 M1 接收门槛分别报告。
