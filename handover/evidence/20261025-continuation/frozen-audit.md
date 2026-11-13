# Bridge 冻结交付一致性只读审计

结论：**FAIL_FROZEN_EVIDENCE_CLOSURE**。运行源码保持同源，但冻结审查链存在已复现的摘要失配，且交付缺少两份被引用证据。旧 ZIP 及仓库文件未修改；没有重跑测试、启动宿主、生成授权或激活，也未读取签名密钥。

## 已复现的问题

1. `frozen-review.json`（3264 bytes，`58cd9cfcfb40739934dda054823b9215572acdabe4db31ee33fcd1da0eb2a742`）的 `evidence.native_interface_review` 绑定 `final-review-native.json` 为 **10877 bytes / `f31f89f26422c32f80aee6adec63264060e14c89a7faf71920a579d85ef52b63`**；当前文件和旧 ZIP 内对应文件均为 **19998 bytes / `6616b43ff571eb7cea3ef272ef8f2c6773fd63e658efb5d096192d6c4c5f0766`**。旧 ZIP 任意条目均不含被绑定的旧摘要。该问题在当前目录和交付内同时成立。
2. 冻结审查直接引用 `/private/tmp/bridge-hotpath-repair-20261024/final-review-state-before-freeze.json`，其 **3122 bytes / `6737a2399f765e10ea53fbb184678666423f08f65b1dbb4677cdcd8c61786f77`** 与 review 相符，但 ZIP 任意条目均不含这些字节。
3. 当前 native review 的嵌套 `recorded_evidence[2]` 引用 `/private/tmp/bridge-hotpath-repair-20261024/project-environment/b-host-identity-fixed-files.json`，其 **817 bytes / `69d5ae5dd6bb3c60591fde6df693ac6931e36b7063d966f5112fa9049a7b952c`** 也不在 ZIP 内。其登记的七个源码摘要当前均匹配，不能代替该被引用 manifest 本身。
4. 发现 15 个临时目录引用。除以上两份外，其他现存引用字节能在 ZIP 中找到相同内容，但绝对 `/private/tmp` 引用仍不能在清洁解包后直接解析；例如 candidate audit 与 focused log 虽已另路径打包，review 仍指向临时目录。

## 当前仍然成立的证据

- 五个直接 evidence record 中，state review、candidate-02 audit、incremental core、targeted rerun 的现存字节/摘要符合绑定；native interface review 不符合。完整递归路径、摘要和 ZIP 内容映射见 `frozen-audit.json` 的 `review_dependency_records`。
- source map 为 `ca635d07a487a70d3ed3ef6fe2710dbc5a897518ca5caf5012e64fe3878d1c00`。160 份运行文件在当前源码、prepared 冻结目录、ZIP source、ZIP 冻结目录四处完全匹配；冻结目录无额外或缺失文件。
- scope SHA `c3d76e3aad8a222d8e6f698433983caa4ee43a0139dacffcd9aa50c1a9032c89`，freeze SHA `74e1a8c8a1fb23cb01e263a75c62834702ac78610206d010a09bdf63154723e4` 均匹配。配置、plan、两份宿主二进制及 OCIO 只读文件绑定也匹配。没有使用 NativeScope/accounting API。
- 四个 Python 包的 `pyproject.toml` 与 `setup.py` 共八份声明齐全，当前与 ZIP 相同。ZIP 内 6018 份 source 文件均与当前相同；6021 条 manifest 摘要全部符合，无未登记 payload。
- 旧 ZIP 为 50418396 bytes，SHA `045cd07dc203ec887aab024f7f4fcf47893d492d44ade97519108260684c1687`。完整 ZIP 清单一致不能抵销嵌套 review 的摘要失配。
- ZIP 的 README/EXPORT 明确声明源码候选、安装包未重建、真实宿主未重跑、未授权、异机需重新 prepare。当前 scope 为 `PREPARED_NOT_AUTHORIZED`、`execution_authorized=false`；没有以这些文件一致性结果替代真实 HIP/性能/工程验收。

## 根因与最小文件边界

确定根因是审查输入没有成为不可变交付：顶层 frozen review 保留较早 native review 的摘要，而当前路径及最终打包已包含后续扩写文件；另有两个审查输入只存在临时目录。`final-review-native.json` 的 mtime 比 `frozen-review.json` 晚约 0.566 秒，支持冻结后覆盖/扩写这一解释，但仅凭 mtime 不能断定具体操作者。`tools/run_hip_diagnostic.py:249-259` 的静态入口只验证顶层 scope/freeze/source/target/resource 字段，没有递归校验 `review.evidence`，所以 source hash 相同不能豁免此次缺陷。

最小修复只新增交付证据与包：保留旧 prepared、原 review、旧证据和旧 ZIP；在新的版本目录复制完整被审查输入闭包，纳入上述两份临时证据，生成含相对包内路径、bytes、SHA 的索引。由独立审查者审查固定字节后，最后生成新的 frozen review，随后以新文件名打包并从解包字节逐记录复核；生成 review 后不得再覆盖其输入。原生官方大档案及本机宿主不属于可搬移启动授权，维持现有来源/使用边界。

这个证据修复无需修改运行源码，也不要求重复 112 项软件回归；它需要重新独立 review 和交付完整性验证。真实执行授权、激活和宿主运行继续由其独立合同处理。

## 复现

运行 `python3 /private/tmp/bridge-continuation-20261025/frozen-audit-repro.py`。脚本只读取当前文件和旧 ZIP，并仅重写本目录下的 `frozen-audit.json`、`frozen-audit.md`。路径闭包、所有逐文件结果、官方帮助 member 摘要核验及 mtime 记录均保存在 JSON 中。
