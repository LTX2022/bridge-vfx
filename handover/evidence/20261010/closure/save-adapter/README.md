# SAVE adapter：接口与限定验证

仅修改 `tools/readiness_evidence.py`、`tests/unit/test_readiness_native_command_evidence.py`，新建 `tests/unit/test_readiness_current_save.py`。已有共享改动保留；本目录是审计材料，不是安装内容。

## 接口已冻结

`inspect_prepared_case` 保持现有返回结构，新增 `stage=save`、`proof_scope=current_task_save` 的原件证明，包含 producer canonical path/raw SHA、request_id、host_identity、当前 owned graph/version/hash/source，以及 `current_source_matches`、`domain_lifecycle_verified=False`。

`supporting_evidence.current_task_save` 包含 `typed_save_verified`、`scope=current_task_save`、`operation_id`、`current_source_matches`、`domain_lifecycle_verified=False`。通过原件而 current-src 陈旧时仍保留冻结保存事实，但返回具体 stale errors 和 `save: typed producer verified against frozen source; current-source binding stale`，不声称当前源码保存准备通过。summary-only 保留原 typed-save 缺口。

校验包括：现有 typed validator 的 request/task/operation/host before-after 绑定；controller summary 剥除附加字段后与原件 result 完全一致；当前 owned graph/version/hash/COMPLETE、反馈依赖及最新成功 task_save；controller/save/graphversion 同源冻结；原生 addon 与 producer/store/controller 源码；canonical producer-records 的 owner/operation 摘要路径与原始规范 JSON 字节；原件 scenecontract/当前 HIP 与冻结 snapshot 字节。路径读取复用现有 resolver，支持自定义导出 source/map/manifest 根，不复制 supervisor 密钥。

## actual 原件结果与中间误比

输入为 `outputs/all-domain-20261009/formal/recovery/runner-1791536968173038500/partial-case.json`，原始 SHA `aa981b16d991352fdfa1f810e8d543183ef976300351db9da50119f633789aa5`。

`before.log/json` 只读复现无条件 typed-save 缺口。`after.log/json` 是保留的失败中间结果，不能用作最终结论。我在中间实现误比 `save_receipt.process_generation=9086f1b0b354`（runner 代次）与 `operation_receipt.host_identity.process_generation=1279dd17b843`（宿主代次）；这不是源文件变更或原件损坏造成的。剥除控制端附加字段后，actual original result 与 summary 完全一致。修复不删除 typed host/request/依赖校验。

`final-existing.log/json` 已识别 `task-save-e7109b625ce84f6dacd532b5955b8b92`，仅新增一条 current_task_save 证明。54 条部分证明不是 closure；当前 `domain_readiness.py`、`render_color_facts.py` 和 addon 的源码 stale 与 render EXR payload 缺口分别保留，case 仍 BLOCKED，完整 domain、生命周期、preview、输出、恢复、Nuke 仍未成立。

`frozen-original.log`、`frozen-original-result.json` 对同一 actual SAVE 原件的 SAVE-only 视图，通过现有 PackageEvidenceResolver 验证。`frozen-original-package` 保存原文件字节和冻结源码，source 根为 `export/bridge-source`，map/manifest 位于 `metadata/`，验收时的 manifest SHA 在结果中。该正例的 current_source_matches=true 仅指与导出的冻结源码一致；不是当前 checkout freshPASS。输入原件校验后 SHA 不变，未拷贝 receipt.key。

## 定向验证

最终命令为 `python -B outputs/common-closure-20261009/save-adapter/run_targeted_tests.py`。`targeted-tests.log` 保留完整方法名、原始日志，`targeted-tests.exit.txt` 为 0：60 方法，59 通过，1 既有材料缺失 skip（既有 material causal producer 输入未提供，不请求目标执行）。没有全量测试、昂贵正式 case、真实 DCC、模型、仿真、缓存或渲染。

包括原 native adapter 19 方法；新增 current-save 14 方法（其中 fresh 公共 GraphRun.task_save 使用实际编译、原生建图初始化、正式保存及持久原件，仅底层 HOM/transport 替身）；既有 prepared adapter 8、formal typed save 7、public task_save 11 和完整矩阵拒绝守卫 1。新反例覆盖原件字节篡改、summary-only、重摘要上层替换、错误 owner/host、canonical path 伪装、HIP/snapshot 字节变更、stale current-src、冻结源损坏、不同 source、旧 graph/save 替换及错误依赖。

测试和只读复现的调试失败均留在对应 first/second/public 等日志，命令/exit 映射见 `audit.json`。`owned-changes.patch` 仅记录本任务相对开工前文件的增量，不包含已有共享改动。

主 agent 负责统一 source hash 的 fresh case c 集成验证。App 发信接口拒绝向原生父任务发送，当前环境未暴露原生协作消息接口；最终返回提供本索引和 frozen 接口。
