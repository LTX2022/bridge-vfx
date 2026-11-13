# 18 修复独立代码验收

审查者 `/root/live16_code_acceptance`（Bugbot，只读，未参与实现）。root 保存审查者返回的结论；审查者未运行测试、软件链、DCC 或原生探测。

**No P1/P2 findings.** 仅覆盖本轮五文件最小增量，不代表真实工程完成。

- 最终清单：`8d452912d3486345dc350ff867bccf0d9b2fac259e9a72063bda32f65cd609f9`。
- 最终补丁：`bd7d0e5d2ad2f42e4b19f71274e6182622be431fa654c062d63778c84f97cb66`。
- 五个当前文件逐一匹配最终清单；两个生产文件的 before 字节匹配 18 实际执行快照。

`graph_initialize_registered_domain` 和 `_fx_bind_graph_trial` 的显式节点集合使用官方 `allSubChildren(recurse_in_locked_nodes=False)`。网络容器继续递归，锁定 HDA 节点本身保留，集合仍须精确匹配声明图；解锁资产及显式外来节点仍会被拒绝。

initializer、bind、静态域读回及 GraphJobWorker 重开检查，仅将预期内部 token `Obj/obj` 固定映射为 HOM 的 `Object/object`。实际类别没有做 alias 或宽松归一，伪造实际 `Obj` 仍拒绝，类型、父节点与路径检查保持。

原始场景合同、内容指纹、保存和重开验证仍完整递归，锁内 18 节点继续纳入 type、parameter channels、inputs 合同，没有被本次显式图投影剥离。17 的精确类型机制、身份、停止及预算代码保持。

软件边界准确模拟 Object、锁内 18 节点与锁定遍历语义；解锁、外来节点及错误原生类别均要求失败。锁内参数使用空的软件序列化容器，并明确 `internal_parameter_observation: NOT_MODELED`，没有虚构未知的原生参数模板、菜单或 hidden/locked 状态。保存与重开用例保持 41 个全后代、23 个显式节点和完整合同。

冻结候选的源码一致性、软件运行结果及未授权状态由最终独立证据验收另行核对。真实 18 已失败封闭，静态无发现不能提升为修后真实工程通过。

## 19 冻结附注

审查者最终只读确认：scope `ca1ad7b9fc8b53a8864b4dfa3a4c4faa07aa11f714b7ec9e0b26dfaa249612fd`，bindings `d1882a19566d244ee7de17cc39286ec46571c396cc74c3cafea92dbc8e3c5a14`，review `1d83d129bc3eb4d080f82fe3faea561bcd7e4ea263b9f619e39a22312591d3ba`。

snapshot manifest `5d90c3a47f510f1d85a45771edc441d2f17644796d034c8bbfb4b35173bbfb15` 中 159 个文件逐一匹配，与 18 执行快照相比仅上述 addon 与 GraphJobWorker 两个生产文件变化。19 snapshot、当前源码和最终修复清单一致。19 保持 PREPARED_NOT_AUTHORIZED、NOT_RUN，账本 seq=0、票据为空；未来 20 目录不存在。最终静态结论保持无 P1/P2。
