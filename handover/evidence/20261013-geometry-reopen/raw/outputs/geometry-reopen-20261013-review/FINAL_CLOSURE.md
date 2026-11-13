# G03 恢复 authority 整改后独立复核

最终结论：**BLOCKED，仍有 2 项 P1。** 原三项整改的原始触发路径均已有对应修复效果，但不能签发整个恢复 authority 闭合。未改生产、controller 或 tests；全部审查材料只写在本目录。

## 最终绑定

| 文件 | SHA-256 |
| --- | --- |
| plugins/houdini/_impl/houdini_bridge_addon.py | 8f68f0728f60b95f32b8af6ad92bc1dc65ef62955996ebd4005d7609caa0786a |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py | 83ef5a483b431b93adf258692dc8a16e359602a24dde8f366613b6aec4fa8281 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | f826519d323fef99564a56f9cff38c7487fa08882ebb17196b4de891ac1adc4e |
| tests/unit/test_geometry_reopen_addon.py | 22fec4a0c394fe4c06ac27297b473e88618e97405746b5603db8186b52277803 |
| tests/unit/test_geometry_construction_process.py（formal-final 证据夹具） | 8f19aec6cbe88dc0ca2515778c18f4ddc0de5c18b9e340f3bdf3826e47296840 |

独立命令：`.venv/Scripts/python.exe -B outputs/geometry-reopen-20261013-review/final_probe.py`。7 场景 × H21.0.631/H22.0.429，共 14 次独立观察；10 次符合预期、4 次复现剩余问题，exit=1、source_unchanged=true，无 probe_error。原始 JSON 包含完整 transition、CAS、回执摘要核验、scope/cohort 状态、save-store 字节及 generation 恢复结果；诊断脚本 SHA 也已记录。

`final-summary-v2.json` 复核了上述源码当前 SHA，并绑定原始 probe、中心修复报告、最新 formal-final 报告及两版 lifecycle/snapshot-manifest/原始 rest 输入摘要。生产及 reopen-addon SHA 未变，独立 probes 不重复运行；仅新增正式夹具 SHA 和最新证据绑定。旧 probe-v1/v2/v3、final-summary-v1.json、REVIEW.md 未覆盖。

## 原三问题的整改效果

| 原问题 | 独立观察 | 当前限定结论 |
| --- | --- | --- |
| R01 completion 持久化失败留 authority | 两版无当前 authority、scope={}、transactions=0；INTENT，save-store/generation 已恢复；reconcile 拒绝。普通 final end 失败也满足上述条件并有有效回执摘要 | 原直接故障已修复；见 R04 的身份漂移边界 |
| R02 输入漂移拒绝后补签 | 两版 `GEOMETRY_REST_INPUT_CHANGED`，INTENT；manifest 尚在时 reconcile 拒绝，authority 不存在，save-store/generation 恢复 | 原直接路径已修复；见 R05 的缺失 manifest 边界 |
| R03 graph_bind 最终 end 失败留 manifest | 当前源码 snapshot/restore 包围 final end；两版执行同一实际 persistence/transaction body，embedded/sidecar 字节恢复，scope/transactions 清空、无当前 authority | 该内层范围关闭；没有由 reviewer 执行 public graph_bind 正式负向 process |

正常实际 addon build→apply(.3)→save→reopen 两版均保留 .3，无重复 apply；COMPLETED 与当前登记一致。parameters_only/BLOCKED 语义保持。

## G03-R04 / P1：completion 后身份漂移仍留下 COMPLETED，无 authority

触发点：`_fx_geometry_restore_transition_intent` addon:3751 使用当前 `_host_identity()` 比较已写 completion 的 `after_identity`。身份漂移本就是 `_fx_geometry_reopen_transaction` 必须拒绝的情况，此时该比较阻止撤销本次刚写的 completion。addon:12694 的 COMPLETED 早返回随后绕过 G03 checkpoint 校验。

实际复现：使用真实 build/apply/save 及 `scene.reopen_task_hip`，包装 `_fx_scene_transition_complete`：先调用其实际实现完成落盘，再只改变显式 fixture 身份的 launch_nonce。没有构造成功回执，也没有绕过 Registry。恢复上下文随后实际抛 `SCENE_STATE_DRIFT` 并撤销 cohort。

H21/H22 均观察到：当前 authority=false、scope={}、transactions=0、save-store/generation 已恢复，但 **同一失败恢复 operation 的 transition=COMPLETED**。调用实际 `scene.reconcile_transition` 返回 COMPLETED / reconciled=false，而非拒绝。

证据：`final-probe-v1.json` 两版 `identity_drift_after_completion`。这是同 PID 的显式身份漂移反例，不冒充真实新 PID 验收。

整改条件：撤销自身 completion 的判断应绑定本次实际完成记录的身份/摘要/CAS，不能依赖已经漂移的当前身份；必须保留“不撤销其他作者新 completion”的防护。当前恢复 authority 的 reconcile 必须区分历史完成事实与当前可采信的恢复结果，不能让该早返回掩盖本次 final end 已失败。定向反例需继续检查同 operation 最终 state、当前 cohort、回执摘要及 save-store。

## G03-R05 / P1：缺失当前 manifest 会关闭 G03 校验并补签成功

触发点：`_fx_geometry_reconcile_checkpoint` addon:3765 在当前 root/manifest 缺失或 domain 非 G03 时返回 False；调用方把 False 当成普通场景链继续，最终补签。是否必须恢复 G03 被当前可丢失的 manifest 决定，而非该 operation 对应的可信 save contract。

实际复现：与已修复的输入漂移拒绝路径相同，reopen 抛 `GEOMETRY_REST_INPUT_CHANGED`、当前 authority 不存在。随后仅删除 fixture 临时场景的 embedded manifest 和 state sidecar（真实 fixture APIs/文件，未改项目源码）。可信 task save receipt 仍存在，且含该 G03 checkpoint；调用实际 `scene.reconcile_transition`。

两版均观察到：**reconciled=true、transition=COMPLETED，但当前 authority=false**。缺少生产状态被当成跳过领域前置校验，而不是拒绝。

证据：`final-probe-v1.json` 两版 `missing_manifest_after_refused_reopen`。此 case 的文件操作仅作用于 fixture TemporaryDirectory；没有删除项目内容。

整改条件：首先从 operation 的已绑定 save receipt/scene contract 判断是否要求 G03 恢复；若要求，当前 root/manifest/checkpoint/真实 registry 任一缺失或域不符必须拒绝。仅可信合同本来不含 G03 登记的旧链才能保留普通/blocked 分支。不能从陈旧 userData 重建 authority 以满足校验。

## 中心与正式证据核验

中心 `geometry-reopen-20261013-fixes-v1.json`：33 methods，0 failure/error/skip，exit=0，97.344 秒，source_unchanged=true。最新正式 `geometry-reopen-20261013-formal-final.json`：1 method 两版本，0 failure/error/skip，exit=0，报告的整个 runner 耗时 97.063 秒，source_unchanged=true。以上两份原报告的 addon SHA 均与本复核一致；未由 reviewer 重跑。

最新 formal-final 两版 snapshot-manifest 各 134 个源码条目与当前文件 SHA 比较：0 drift。lifecycle 已核对确认自有宿主退出、PID/nonce 改变、恢复成功和参数读回 3：H21 PID 13480→5380，H22 PID 38888→7508；host_after.plugin_build 与最终 addon SHA 一致。两版 parameters_after 已绑定实际 RPC 返回变量，前后参数相等；归档 rest-input-original.json 的原始字节 SHA/长度与 save contract checkpoint.manifest 完全一致。readback 明确是 BLOCKED/parameters_only。此正常生命周期的成功不能覆盖 R04/R05 的故障路径。先前 formal-v1 原件及其旧 PID 记录作为历史保留，不混计最新正式结果。

不将历史成功回执在正常更换宿主后缺少当前 registry 单独认定为 bug；R04 是同一失败操作留下的 completion，R05 是缺证据时新补签的 completion，均有实际触发与原始记录。

本次只执行受控进程内 addon/底层 HOM 的独立故障观察，并只读核对已有正式进程日志；没有执行全量、正式 process 或真实 DCC。后续只需复核 R04/R05 的整改及其受影响路径，不重复无变化全量。
