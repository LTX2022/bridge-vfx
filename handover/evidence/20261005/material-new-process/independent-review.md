# 材质新 PID 软件持久化独立复核（2026-10-05）

结论：有限接受两版已运行冻结来源的11控制逐项写入/保护读回、软件 HOM 场景字节保存、新 PID/nonce 直接 load 后双读回。未发现本限定范围新的确定 P1/P2。仅审读/比较文件，不运行测试、受控进程或 DCC，不修改实现。root standard-discovery 隔离 driver 尚无本次证据，等待作者最终日志再小增量复核。

| 冻结运行 | 结果/耗时 | PID | 保存/重开相同 SHA256 |
| --- | --- | --- | --- |
| run-21.0.631-3fd0cbb9 | PASS / 5.844s | 30220 → 32692 | 332bcc31f967f6a9d9d3f56ace307d4f076852c9361a442ef693ea787aba1d85 |
| run-22.0.429-eff3bd1f | PASS / 5.891s | 28420 → 30740 | 924fd8aacd6c69156297ba2c37aed7cba4e1fb99253527455deafb2e90cdd364 |

## 原件核对与有限事实

- 两版 feedback 都覆盖 base_color、roughness、ior、transmission、subsurface、normal_strength、specular_weight、coat_weight、anisotropy、displacement_scale、emission_weight。冻结 run_version 要求每步只有当前 semantic_control 的 parameter_diff，readback_verified=true，原值确实改变；完整原生读回11字段，origin=runtime_hom，locked/disabled/hidden=false。独立文件比较11步未编辑字段的 before/after 全 observation 相同，protected_mismatch=0；result before/after 与13条 child1 native-probes 原记录逐项一致，mismatch=0，不仅采信PASS标签。
- BOOTSTRAP_NATIVE 只安装显式底层 HOM/USD API；正式 addon dispatch/writer/readback/HTTP TCP 与自有监督器未替换成功。值来自实际 native parm/ParmTuple observation 与 domain readback；candidate CHANGES 只作为输入/断言，不注入 collector。BOOTSTRAP_COLLECT 在同一子进程直接读11控制、native static topology、最终 settings_binding LOP composed stage 的 material:binding targets，以及帧1/2 _fx_render_configuration。两版 child1/child2完整 readback 相同，collector.json 与 result嵌入原件相同，render loppath 均指最终 LOP；材料 target 与静态 USD material prim 相同。这里只证明软件 stage 的绑定/配置及HOM参数，不证明原生 USD shader效果或渲染颜色。
- 两版首子进程都在 scene.save_hip 后经 task_host.stop、handle.wait/receipt 的真实签名 started/stopped 校验，exit0、child_wait_observed=true、job_active_processes=0，再进入循环启动第二子进程。21版 stop_at1791196391.2245524 < start2_at1791196391.519919；22版 stop_at1791196421.1000938 < start2_at1791196421.4211009。审读的四组实际 envelope payload 与 result一致、包含签名、start/stop birth一致；签名认证执行来源为冻结测试的原 owned_process reader，本轮不重新运行或读取/输出key。
- child2 fresh-scene count=0，PID/nonce均改变；旧nonce在真实第二实例 started receipt 上明确 SUPERVISOR_RECEIPT_MISMATCH。两版 child2 calls.jsonl 只有 dispatch(ping、scene.reopen_task_hip)，native-probes只1条reopen；未经过被监控的 build/apply/init/verified-writer。底层 _hip_load 直接解析保存的 `bridge.software_hom_snapshot/1` 节点/参数/连线字节，未调用业务 build/apply 来重建。reopen nodes/parameters/connections_verified为true，SHA等于首实例保存；两个 live collector 独立取得相同读回。

## 冻结来源与 root 差异

两版 source-manifest SHA 均 `b8fe0a283d1ca63dc1c839db05dd8efb3f99cc131444a03e5421743260c75730`；software-launch.py 均 `fab5ba5243a33bcb07f538d10495d15b15cc1d30f0bb1b3b6975bc904c625d5a`，实际文件 hash 与 result记录一致。下列限定依赖已独立核对冻结文件 hash=manifest，两版相同：

| 来源 | 已运行冻结 SHA256 |
| --- | --- |
| tests/unit/test_material_controls_new_process.py | 4ccd4f6d5a1f2e798f9aa5e0a622207099b7b1a82c1bc2f553745040ee977f03 |
| tests/unit/software_host_bootstrap.py | a642a45895da55511ffcf9b6c59e50d677a7a4480cc4c1dcc67e5799e8ecff02 |
| tests/unit/test_native_controls_new_process.py | 90baf3f14ef9b68583bae3f6b0d33c9d2050d7d485f5ddc74cff726c8ae4d98e |
| tools/software_render_api_boundary.py | 88ca23f4cd608ac3141288d69bd72b9b7cd85ea27435143fbc56676669e126ae |
| tools/native_schema_test_boundary.py | 97efe6358e39fcc58442bd13b8eeb9d049fb3887cf9dbe9bdc5ca4b2ec1a21f6 |
| plugins/houdini/_impl/houdini_bridge_addon.py | e8e7938303a1019eb5e53421db635cb3c7f71d367f4de7de7dcebe462dc177f2 |
| packages/houdini-bridge/src/houdini_bridge/native_render_domains.py | 6683a625929b39671a89c075b02f6a8ae7e57a8baa6d603cca31fded44213262 |
| packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py | f1e62d47ecc274bd2b75acf827047f2a4cdc2fb62910bb111bc21b033b5fac49 |

审读时 root material test SHA为 `63bfeb8029619051e19f55af6ab5f54d54ce05f126a2d12a15a1bf4326b7cd56`；与冻结diff仅新增 run_isolated_test import、两版测试改用该隔离driver、去掉无参数运行拒绝，run_version/BOOTSTRAP本体未变。root共享 test_native_controls_new_process.py SHA为 `79a54ec47e6fbd833bb0e78e7c5401ebcc7907d346f39d21d71fb3b73c36f191`，也不同于已运行冻结版本。其余表内限定实现依赖在审读时与root一致。此报告只接收冻结来源，未把旧PASS沿用到新增root driver/standard discovery。

## 运行原件 SHA256

以下均相对于 material-new-process/；calls/probes/collector已实际读取比对。

| 原件 | SHA256 |
| --- | --- |
| run-21.0.631-3fd0cbb9/result.json | a20a99497160fbc3ad443cccb40c5c0a328f6ba0c3a025cfa17ead6e6dca281c |
| run-22.0.429-eff3bd1f/result.json | 646ba0c49347b179ee59df31ab67751aa542c061be4765d56750ea8cbe3d9ec1 |
| run-21.0.631-3fd0cbb9/child1/collector.json | 064e549b0e10e1ea829ad2fdc3ba3c656cc6cd339d78b080131a58009571cf53 |
| run-21.0.631-3fd0cbb9/child1/native-probes.jsonl | 5c44251f98473890ae6b74ac3c2c8ed9e410c027f160b25d0f49cd08ee76057f |
| run-21.0.631-3fd0cbb9/child1/calls.jsonl | d9a214fa84669e0bfba3d678a03cb5a0b6c1dca958779d714561b312e752557f |
| run-21.0.631-3fd0cbb9/child2/collector.json | 8d4e0ff94f65494a7c5c594842d474abd7e0978dabe70f9ab2323146c60b37c6 |
| run-21.0.631-3fd0cbb9/child2/native-probes.jsonl | 011fb8e76ccb244a988ef14ee5b2530aee3767a069619427ef498848289a187b |
| run-21.0.631-3fd0cbb9/child2/calls.jsonl | 9a09b45d4c9e05c58422d0c5e3a75485bd8ac4c74118028da6f8a8a695667ef8 |
| run-22.0.429-eff3bd1f/child1/collector.json | d115e64e6b81bf2dcfa7b03b97eefb0f6b43406888083ce3dfe64d554d3b992b |
| run-22.0.429-eff3bd1f/child1/native-probes.jsonl | 5c0bf9e9feabd2a218819bcdebe66464dc9862b8ccc0a67e3222696acd4f584e |
| run-22.0.429-eff3bd1f/child1/calls.jsonl | 96696db91af8df8b1c7fc833408781331df75e8b44be44dee03157ce290d08b4 |
| run-22.0.429-eff3bd1f/child2/collector.json | 3823be47034274ead8a1e0d555051f6817c40dbb9e857ba74468424f760027ac |
| run-22.0.429-eff3bd1f/child2/native-probes.jsonl | 3fcf3f892151b5c9fb1b8b0ff2a716ab706f1ee8921f1358648e200c0b9e37e0 |
| run-22.0.429-eff3bd1f/child2/calls.jsonl | 3cc4072a14335fe39660458f10b42859537bbb224bf3fece096e7cb1b8df469c |

范围保留：这是软件 task-host API persistence；graph_status/real_host_status NOT_RUN，metadata/registry BLOCKED。registry本次未执行，result里提醒的 REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED 不计新增实际登记拒绝证据。原 full_scene_identity_verified/native_geometry_validated/cookable_domain_network 的不足仍保留；真实HIP/DCC/渲染颜色alpha/完整graph/M1不在本次接收范围。

## 最终 discovery driver 增量复核（2026-10-05）

限定结论：接受最终两测试文件的标准 discovery 隔离兼容证据，解除上文“root driver 尚待日志”的待核项；未发现本增量明确 P1/P2。只读取最终 driver、指定日志与四次运行的有限记录/冻结测试，不重跑、不改实现、不扩审共享实现。

- 实际 root、四次运行 frozen Swarm test、四份 driver command 的对应 SHA 一致：`79a54ec47e6fbd833bb0e78e7c5401ebcc7907d346f39d21d71fb3b73c36f191`；两次材质 frozen/root/command SHA 一致：`63bfeb8029619051e19f55af6ab5f54d54ce05f126a2d12a15a1bf4326b7cd56`。新运行直接绑定最终文件，不沿用旧来源的 PASS。
- discovery-probe.py 在同父 PID26904 预导入 root task_host/native_render_domains/owned_process/workbuddy_assembly，再对两个精确文件执行 unittest discover，要求恰好4方法。machine result、stderr、stdout、exit.txt相互一致：4 tests，24.345s，0fail/0error/0skip，rc0。stdout 指向四份实际 command；它们 parent_pid 均26904，driver PID为24712/30296/32044/11736，rc均0、timed_out=false，各 stderr 仅所选单方法正常结束。
- run_isolated_test 的最小隔离入口使用实际独立 Python、精确脚本/方法、受限环境和120s timeout，只有直接脚本且显式选中方法才进入原 run_version；父入口不复用已 preload 的业务模块来执行该链。失败/超时后仍断言拒绝并保留日志。这里只接收实际成功和退出1拒绝证据，未新增声称执行 timeout 分支。
- 四次结果共有8个实际受监督软件 host PID：Swarm21 13176→26120、Swarm22 31336→4752、material21 1844→2912、material22 5536→12756。八份 stopped 记录均 exit0、child_wait_observed=true、Job0；各首实例停止时间早于第二实例启动，nonce改变。每个第二实例 calls 仅 ping/reopen，双 collector readback 相同，oldnonce 均 SUPERVISOR_RECEIPT_MISMATCH。签名认证仍以已运行冻结测试的 owned_process reader 为执行来源，本轮不读取密钥或重新认证。
- 最终材质运行 `run-21.0.631-ff106998` / `run-22.0.429-ad7272c8` 实际 result 为 PASS，分别5.985s/6.000s，feedback各11项；driver stdout精确指向这两个 result。两版新 source-manifest 实际 SHA 均 `8fe1bc6c608a92fca625c63bbcfb5263dc79d411f442478f8bb6882188c08b3f`，等于result声明，software-launch声明保持原 `fab5ba52…`。本增量核对来源与隔离兼容，不重复前节逐项保护字段审查。
- 独立 negative 的真正 child driver PID16108、exit1，stderr明确 INTENTIONAL_DRIVER_FAILURE_WITHOUT_WORKHOST；parent PID15216 接获断言，rejection.json记 parent_rejected_failure=true，外层 negative probe rc0表示拒绝验证成功，不能误作 child rc0。该负例不启动 workhost。

| 新原件 | SHA256 |
| --- | --- |
| discovery-probe.result.json | 06f7d4ea8527d7d296e0bf2fb9221013b8698c1417cb8fa76dee29605bb8d3e5 |
| discovery-after.stderr.log | 19430d13a1420246e1f5c9516cbb11a6c1cab61a459658e490836d90db9d1ea0 |
| discovery-after.stdout.log | 1add5f62566242e412a869272d8beb564e20dc6c7a0b471026930cf2f7d66871 |
| run-21.0.631-ff106998/result.json | 589d7e75d76ce304300830d451cf9a8ad059e1ef701db16a1c5c65d8dd9ec4cf |
| run-22.0.429-ad7272c8/result.json | 91471e26d65274fff4a85f24c42d95123e6391fc5304800ebf0b27b777c337dc |
| driver-failure/rejection.json | 44072ae9ce700d2f41747ebed64a3dd9395ebc1c5163c970c3ca7537db4c5d2e |

接受范围仍仅两版 Swarm/material 的软件持久化与四方法 discovery 兼容；registry/metadata仍BLOCKED，完整graph/真实宿主仍NOT_RUN，原生颜色/alpha及完整M1未获证明。本轮未运行任何测试、driver、受控host或DCC。
