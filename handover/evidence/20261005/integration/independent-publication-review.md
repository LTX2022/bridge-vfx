# 正式接线独立只读审查（2026-10-05）

结论：本轮两处有限新增接线可接受；未发现确定的新 P1/P2。仅核对新增 registry guard、公开 native locator/status sanitize、readiness locator/envelope 适配及直接关联旧合同。未修改实现、未运行测试或启动任何受控 Python/TCP/DCC，不重复终态 seal 审查。

## 1. 正式 Houdini 回执禁止旧登记绕过

artifact_registry.py:229–231 在冻结可信 operation fact 后、任何 admission/SQLite 写事务前，要求 `bridge.houdini.render.execution_fact/1.0` 必须提供 receipt_source_files，否则明确 `REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED`。调用者的 colorspace/premultiplied/hash 不替代该门槛。空字典或错误类型不会走旧路径：仍先进入既有 _receipt_metadata，再进入严格 source admission；当前 BLOCKED/空 metadata 无法注册。旧无此 schema 的操作合同仍保留，final_delivery/raw provenance 原拒绝路径未撤销。

定向测试源码明确使用实际 registry 文件/数据库，拒绝后 history 为空、lookup 为 None；不以默认 linear/False 让当前 producer 通过。已有日志包含这项拒绝与原 ledger 正常/故障/CAS 回归。

## 2. 有限 native locator 公开与读取

graph_jobs.py:162–190 只输出 schema2 的白名单字段；task/op/graph_hash 与公开结果上下文一致，attempt token/generation 必须匹配实际 DB row 当前 attempt，count/bytes/SHA 有类型及边界校验。实际已验证 graph worker result 先经过原 _validated_result/validate_completion，再进入 _finish；public sanitizer 只转发 locator，不制造 producer 成功。

路径必须落在可信 jobs root 的精确 `graph-jobs/<operation>/attempt-<generation>/<operation>.native-operations.json`；复用 owned_file 拒绝 root 下 symlink/reparse。输出只有相对 locator，丢弃 private_extra 和任意嵌套路径。_finish 与 status 二次 sanitize 均传实际 owner/token/generation，重复处理保留合法 locator，不因第二次调用失去 attempt 绑定。

readiness_evidence.py:814–821 仅把上述精确相对 locator 解析到冻结 source manifest 所在 control/jobs；实际 assembly jobs root 同样是 control/jobs。解析后继续原绝对内容摘要/大小检查、schema/owner/op/graph hash、attempt/count、producer 原记录摘要与 host session/process_generation、冻结 addon/source 和真实 signed stopped 检查。未经 supervisor 证明的同进程 records 仍拒绝。

readiness_evidence.py:965–966 只为 graph_status/graph_trial 解包一层 result；外层 receipt 的 owner/graph/source/current save 和 graphversion 绑定仍检查，controller envelope 不升级为 producer 权威。primitive build/inspect/save 的 proof_scope 保留，full_semantic、task_save typed producer、preview/output/recovery/Nuke 缺项继续保留；相对 locator 能读回不等于完整 domain PASS。

## 已有验证证据（本轮不重跑）

只读核对 `native-publication.log` 与 `result-native-publication.json`：29 tests、0 failures、0 errors、0 skip、exit_code 0，source_before/after 一致，并与本轮读取的六个源码 SHA 一致。命令为 `.venv/Scripts/python.exe -B outputs/windows-next-20261005/integration/run_directed.py native-publication`。

其中 readiness 正向 parser 测试显式 patch stop admission，属于解析合同；反向未 patch 测试仍拒绝无真实监督事实的 records。因此此日志不证明 Main 当前 actual generated controller/TCP 的正式接线已实跑通过。本轮未争用该通道。

## SHA256（本轮开始/结束一致）

| 文件 | SHA256 |
| --- | --- |
| packages/dcc-task-runtime/src/dcc_task_runtime/artifact_registry.py | a01fcd9066b3a66eba9ad9c89cedd332942d5b31813b756d02b8b756e38b0ce0 |
| packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py | a1b4f14b23bb4fe6c2e1dcc90263c5f8329db9a71e79da4c6522b0e1a55a010a |
| tools/readiness_evidence.py | 9d5eb51fac5a7047b3150f9c1b812e329e5421c7590a25ba610a787dc8e5554d |
| tests/unit/test_registry_formal_binding_required.py | e03f25dc9874a889e3d8c8459b9bc09718276d6ccad2413c9e08c097c30e7b2a |
| tests/unit/test_graph_job_public_native_evidence.py | a97b3122cba58c9751d3a9cf22e089e9032a623fd929e57b3c37776550ee3e66 |
| tests/unit/test_readiness_native_command_evidence.py | 1fbbe6c9a3315fde3b1d3611d7789ac8e485d3f14be68465c0da6f1012298fdd |
| native-publication.log | a3303acc7d8ca3e8896b2ff757fed77a9c3d1ebf386e849e0bac4c80650afd97 |
| result-native-publication.json | 6fc175988e25f51b9b82cdfc416d900827e353a87b8c2c66d4457b0b2f009624 |

缺原生 OCIO/beauty alpha 及完整域事实仍 BLOCKED；本次不宣称 registry 成功、正式完整链或全域 PASS。

## 最终实际证据追加接收（2026-10-05）

限定结论：接收当前 generated controller/Python TCP 正式软件入口上的 native locator 传播、52条有限命令原记录验真、帧1/3物理 EXR decoder/终态封存读取，以及 registry 缺绑定的预期拒绝。前文“该正式接线尚未实跑证明”的限制由本次实际执行记录补充；完整 case 仍 BLOCKED。本轮只读用户指定六份最终证据，不重审源码、重跑验证或启动进程。

`formal-native-published.log` 与 `summary.json` 一致：16.875秒，exit_code 0，scope 为实际 generated controller 加显式底层 API/进程边界，native_execution_status NOT_RUN，source_before/after 相同。graph_jobs/readiness/registry 三份 SHA 与前述审查一致；client/addon 仍为 c08eeddd…/e8e79383…，完整源码绑定保留于 summary。

`observations.json` 的 graph_trial 成功 envelope 已公开本 task/op/graph_hash/attempt-1 的相对 schema2 locator，count52、bytes84896、packet SHA `6f48c7df707a9a58b887ea599fc87cea13ce82df56dbdc1189f07e14f7875766`。`native-primitive-validation.json` 验真输出52条：build19、edit2、inspect30、save1；所有 current_source_matches=true，current_source_differences为空，owner/graph/hash与该公开 locator 一致。接收的是沿前审真实 signed graph-worker stopped 门槛完成的有限 primitive 验真记录，本轮不另重验签；不把52条提升为全域语义/恢复证明。

最后 operation_query 的 formal-render 为 COMPLETED，frames_done 与 frame_set 都是[1,3]，receipt SHA `22a57ec3b583ae3b19f14fe73289c8769e2c169d497ff7ab7321ee0de8873314`，producer start digest `49136bd0f11793dc27b42436ed743b7767d497ee47e840a0e1157e46b7514df2`。当前已审 reader 要求签名 terminal 原件，因而此次实际读取补齐封存接线的有限软件正常路径。两帧为实际 decoder 观测的32×19 ZIPS EXR，4956/4940 bytes，SHA分别 `e133ff5dfb64764d97a36c9443d52b48d33b745c731ebfac32d53f9e208112f9`、`8ff06bc121b1da58b239def040c3adac57e9258aafb395f2c7d624aad35bce06`，structural_validated=true；channels为R/depth.Z/id，不据此推断alpha。

render completion_metadata_status 保持 BLOCKED_MISSING_NATIVE_FACTS、metadata为空。collector保留缺失AOV/颜色属性、productName/productType的观测string与预期token不符，以及有效OCIO/override/filter/alpha缺项。summary 的 registry blocker 为 REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED，full_case_status=BLOCKED；rc0表示审计按预期完成，包括拒绝路径，不表示登记成功。summary中的 Houdini 自有子进程 stopped 为exit0/child_wait_observed/job_active_processes0；Nuke为CANCEL_REQUESTED/exit1的停止，仅接受停止观测，不计Nuke成功。

`lifecycle-integration.log` 与 `result-lifecycle-integration.json` 对应47项 graph_jobs/controller-source/typed registry 回归：47 tests、0 failures、0 errors、0 skip、exit0，日志18.697秒/runner总计18.922秒，source_before/after一致。它们是本批回归证据，不能代替缺失的native颜色/alpha及完整M1。

| 本次审读证据 | SHA256 |
| --- | --- |
| formal-native-published.log | 66a4acdc789da7c7785c3ee62083016538041f3ef9e43871adca111ecbb79a10 |
| formal-native-published/summary.json | 08fab17fea6d91b07ec77eafb0ce84d70f33a14bef68b99bef4c76fdc96bea6e |
| formal-native-published/observations.json | 82eccd29de7bd7eba67cf1ea964d76ac4f87d73c6e3674d4104c20a5fb57057c |
| formal-native-published/native-primitive-validation.json | c57315954d85e0acb5c9ef9d61b654f497b5e593248a109c836e1afb400343cc |
| lifecycle-integration.log | 3291c5d553d4e20f9e71a689cfe7645b8314e8258fd4adad5bb56cc607575dd4 |
| result-lifecycle-integration.json | d8b1cc72f937c0accae752f34947e09083f4db4aac69c469da217a8b4128141b |
