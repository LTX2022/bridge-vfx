# Bridge 冻结交接（2026-10-25）

状态：**用户要求冻结；代码停在第 21 次修复。完整工程闭环未完成。**

本记录是接手入口，优先于旧报告中的“当前”“下一步”和旧候选授权状态。冻结后未再运行真实软件、继续实现第 22 次修复或重建安装包。所有子任务已停止。

## 当前实际结果

| 环节 | 已取得的事实 | 边界 |
|---|---|---|
| H21 HIP 保存、同进程重载 | 真实通过 | 节点、参数、连接、HDA 定义/内部静态指纹及冻结场景参数一致 |
| H21 全新进程冷重开 | 真实通过，23 个公共节点，无加载警告 | HIP 专项，不能替代正式工程交接 |
| 本轮真实 Alpha 校准 | 完整工程 04 中 husk、Nuke 两个原生校准进程完成，生成 5 个 EXR | 仅校准图，不是主球/地面渲染或 Nuke 主输入消费 |
| 正式工程建图 | 完整工程 04 真实通过 | graph-worker 已保存、重载并验证工作 HIP |
| 正式交接后的 task_save | **失败**：duplicate public node | 当前最早阻断，修复尚未实施 |
| 正式工程冷重开、主场景渲染、输出验证/登记 | 未到达 | 不能用 HIP 专项拼接为正式工程通过 |
| 主输入进入 Nuke、NK 首存/冷重开、Nuke 主结果 | 未到达 | 当前没有可交付的主 NK、主 EXR 或 Nuke 主结果 |
| 视觉接收、工程闭环、M1、HY3、生产验收 | 未通过/未执行 | 各自保持原验收范围 |

实际配置为 Houdini 21.0.631、Nuke 17.0v1、sphere_ground_v2、128×128、frame 1、Karma CPU、beauty RGBA、ACEScg；没有启用 denoise、运动模糊、tiling、仿真或缓存。H22 本轮没有真实重验。原 Desktop 工程未修改。

## 已落盘代码

生产文件：

- `plugins/houdini/_impl/houdini_bridge_addon.py`
- `packages/houdini-bridge/src/houdini_bridge/native_render_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_render_scene.py`

对应测试：`test_scene_contract_hda_policy.py`、`test_native_render_domains.py`、`test_frozen_render_scene.py`、`test_solver_sourcing_host.py`（均位于 `tests/unit/`）。

已实施且保留的修复：

1. 新建任务自有 HDA 的显式 delayed-definition 实例化；保存后加载仅对已验证合同中的精确 HDA 边界准备。capture/verify 仍使用非同步观察，完整定义/锁定/可编辑状态检查保留。
2. HDA ExtraFileOptions 支持有据的有限数值数组；metadata-only 叶节点按严格条件处理；ObjNode 静态 flags 依据真实运行时类别；SubnetIndirectInput 的连接身份完整保留。
3. 原生 multiparm 的 `Parm.set` 关键字修正；菜单读取按模板能力区分，并对精确 renderer/res_mode 使用实际实例菜单。
4. 仅可信输出字段正确区分 `$F4` 原始模式与原生帧求值；声明为浮点的冻结参数在派生写入计划中规范为浮点，原配置哈希和整数比较规则不变。
5. fresh Karma 手动分辨率设置触发经同版原件确认的原生回调，再严格复验分辨率两分量；没有手工解锁或重置已有工程。
6. 原生 USD multipart 的严格 bool False 与旧 int 0 分别验证后映射到既有 canonical int 0；其他类型/值仍拒绝。缺失 userdata 的恢复幂等，其他恢复失败仍报错。
7. 单次受控 HIP load 的 BeforeLoad/嵌套 BeforeClear 只提交一次逻辑 epoch；严格事件序列、身份和 +1 门保留。独立 Clear/Merge 仍失效，异常 finally 清理；仅真实且序列完整的 hou.LoadWarning 可进入第二次加载，每次加载分别计数。
8. 仅 H21 可信初始化计划将已启用 USD processor 的目录及 husk_tiletempdir 固定到已验证输出文件的既存父目录；原类型/hidden/disabled/locked 门、写读回、existing-role/postloop 和完整保存合同保留。tile/autotile 不变，H22 不新增这些字段。
9. 失败信息补充有界节点、字段、类型、状态和摘要；未通过忽略合同字段、全局放宽比较或去重掩盖错误来取得通过。

冻结源码摘要及公开验证摘要见 [freeze-summary.json](evidence/20261025-real-chain/freeze-summary.json)。

## 已知首个阻断：第 22 次只诊断，尚未实现

完整工程 04 的正式 handoff 将原始 23 角色变为 24 角色、23 个唯一路径。`normal_map` 和新注入的 `output` 都指向：

`/obj/BRIDGE_GRAPH_c7918aa8c026821f13150d74ee13d0115eb80aed04bc8754365ec159a1f93cd0/material_network/normal_map`

产生者是 `houdini_bridge_addon.py::_fx_bind_graph_trial()`：找不到旧式 `/output` 或 `/sink` 时取 actual_nodes 最后一项，并将其添加为 `output` 别名。原始 graph worker manifest 的 23 个角色没有重复；错误在正式 handoff 后产生。`_fx_capture_scene_contract()` 逐角色生成记录，`operation_receipts.py::validate_scene_contract_header()` 正确拒绝重复 public node。

冻结前只认可了修复方案：**已验证 registered schedule 应保留编译器的精确角色映射，不猜测注入 source/output；原生角色确有 source/output 时保留；无 registered schedule 的 legacy 分支保留原行为。** 不改 validator，不做笼统去重，不丢真实节点。需确认其它顶层 legacy output 字段是否被本链实际消费后再决定最小必要改动。

该方案未落盘、未测试、未完成最终代码审查；没有 prepared/authorized-05。接手 agent 应从这里继续，不能当成已修。

## 可直接核对的文件

- [已验证 HIP](evidence/20261025-real-chain/artifacts/hip21-validated.hip)：926172 字节，SHA256 `9e3798e4fd06270aec8102059f65ca28a2f3808b99b7c4905ea0098ba225b3ea`。仅是 HIP 专项通过件，不是正式工程交接最终件；保留本轮绝对输出路径，跨机器使用前须重新配置并验证。HIP 原件是复制保存，未为提交再启动软件修改。
- [Alpha 校准 EXR](evidence/20261025-real-chain/artifacts/alpha-calibration/)：5 个实际校准图，明确不是主结果。
- [定向测试原日志](evidence/20261025-real-chain/tests/)、[独立审查记录](evidence/20261025-real-chain/independent-reviews/)。这些是各修复时的原结果，不能相加当成一次全量回归。
- [完整 04 独立批准](evidence/20261025-real-chain/full04-independent-approval.json)、[执行授权来源说明](evidence/20261025-real-chain/full04-controller-authorization.json)。历史授权已随冻结停止，不授权新的真实运行。
- [逐范围消耗记录](evidence/20261025-real-chain/attempt-ledger-summary.json)、[提交文件摘要](evidence/20261025-real-chain/files.json)。

本轮没有重新跑全部测试；`operation_receipts` 的 3 个 PROJECT_ENVIRONMENT_FRESH_REQUIRED 既有错误曾在相同 HEAD 基线复现，未在本轮顺手修改。未重新构建 wheel、安装 ZIP 或发布。第 21 次的最后目录定向用例 2/2；加载 HDA 准备覆盖 34/34；其他原日志分别保留。

## 原始范围、停止和预算

以下原件仍在本机 `/Users/user/Documents/Code_Project/Bridge/outputs/`，不删除、不续跑已关闭范围：

| 范围 | 结果与消耗 |
|---|---|
| `hip-chain-20261025-authorized-21` | HIP_NATIVE_PASSED；graph 84.928431 秒、新 host cold 8.002232 秒，总 92.930663 秒；2 次启动、两组原始签名启停已验证；HIP_DIAGNOSTIC_TERMINAL_CLOSED |
| `engineering-chain-20261025-authorized-04` | Alpha DONE、build DONE、task_save 失败；11.685583 + 6.020470 + 82.793878 + 18.016962 = 118.516893 秒；4 次启动、原始签名启停已验证；ENGINEERING_DRIVER_FAILED |

完整 04 的 scope SHA256 为 `7acc9813a8044b75dc11b39d22ec4902f5f08013f956a615465e333ebcb969a3`，bindings SHA256 为 `28de6791c8ea542330db8f46aff303151a2b07ac5dcae51a96a4d8850454bc02`。所有本轮已记录进程均停止，无遗留运行任务。

HIP 原预算为 graph240/cold120/total360 秒、最多2启动；完整工程为每操作120/累计600秒、最多8启动。两者均512MiB、单重作业、零自动重试，保留停机余量。之前失败的逐范围费用没有删除或转成通过；本轮记录合计 28 次原生启动、1056.946123 秒（多次修复后的独立范围累计），不是单个范围的预算额度；累计账本见 JSON。已关闭完整04不能拿“剩余4次”继续执行。

原始签名密钥、私有运行控制目录、含 nonce 的原生回执不进入 Git。公开报告记录了本机原件验签结果，单凭这些摘要不能在别的机器重新认证；在本机复核应使用原冻结源码及原本地密钥，不导出、复制或复用旧密钥。

## 接手操作顺序

1. 先核当前提交、上述源码摘要和冻结状态；不要触碰 `/Users/user/Desktop/bridge-skills`。
2. 修复 `_fx_bind_graph_trial()` 的 registered 角色污染。定向覆盖 material 无 output、registered 确有 output、legacy fallback，以及冲突/重复仍拒绝；独立只读复核后冻结新源码。
3. 用户恢复真实执行授权后，创建新的完整范围（例如05），审核 scope/bindings/宿主/场景/预算。不要重新执行04，也不要拼接 HIP21 与04 Alpha为完整 PASS。
4. 本轮从公共 `tools/activate_controlled_engineering.py prepare-successor` 创建完整候选，随后 `review`、公共 TTY `activate`、新范围预检和冻结 `run_controlled_engineering.py --execute`。授权确认必须如实记录操作者与来源，不能声称 agent 回填是人手输入。
5. 在新范围实际重做 Alpha→正式 graph→handoff/task_save→全新正式 host 冷重开→husk 主渲染→可信停止→controlled_output_v1 验证/登记→Nuke Read/Write/NK 首存→新渲染进程 scriptOpen/execute→输出登记与停止。
6. 最终交付实际 HIP、NK、主 EXR、Nuke EXR 和由真实 EXR 转出的预览；图像核验与人工视觉接收单列。不得再次以局部测试或打包代替真实链路。

本机完整候选的原母范围是 `outputs/engineering-closure-20261023-h21-19`（未启动，只作 prepare-successor 输入）：scope SHA256 `ca1ad7b9fc8b53a8864b4dfa3a4c4faa07aa11f714b7ec9e0b26dfaa249612fd`，bindings SHA256 `d1882a19566d244ee7de17cc39286ec46571c396cc74c3cafea92dbc8e3c5a14`。母范围旧快照不是当前源码，应使用当前公共 prepare-successor 重新冻结。完整链固定 Python 为 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/bin/python3.14`；HIP 专项使用3.11.16。避免使用指向其它补丁版本的 symlink。

当前忽略的 `outputs/` 原范围、签名密钥与聊天 `work/` 不是可移植 Git 内容。另一台机器须重新建立真实宿主/来源绑定和具体授权，不能伪造原绝对路径或旧回执。长期缺口仍见 [REMAINING.md](REMAINING.md)，执行依赖仍为工程闭环→反馈/恢复→HY3→复用，全16域M1未接收。
