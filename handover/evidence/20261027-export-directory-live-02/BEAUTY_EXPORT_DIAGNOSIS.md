# Beauty 导出源定位（2026-10-27）

范围：`outputs/official-karma-disklight-h21-exportdir-20261027-02`。独立只读研究者 `agent_7d09e3eb-9361-4f32-b67f-4f9184c9c489` 未修改文件、未启动DCC或身份工具、未读取密钥。使用现有H21普通Python的pxr只读USDC；该读取不等于新的Houdini实机执行。

已确认：warm与cold完整观测逐字节相等，SHA-256为 `68f7cf2dc1282a06d883e40deae013696f1f935dd9459f88bd17a4097d985678`。两者Beauty均authored `driver:parameters:aov:husk:name` string C、`driver:parameters:aov:husk:format` token color4h。磁盘USD同为12个prim，authored属性恰好缺这两项，无新增属性、值或类型变化，非空关系也一致；旧aov:name=C和aov:format=color4h仍存在。

实际观测中的原ROP物理input0仍为 `update_output_image_path`，`loppath` 则为 `bridge_rgba_output`。同版 `houdini/help/nodes.zip` 内 `out/usd.txt` 第80–81行说明：LOP网络中的USD ROP有物理输入时忽略LOP Path并使用输入数据。精确类型的 `houdini/config/CustomNodeInfo/Lop/usdrender_rop.py` 第7–11行同样从 `inputFollowingOutputs(0)` 选择Render LOP。

因此证据支持：导出绕过了新增适配节点，未走正确的最终stage；没有证据支持属性被outputprocessor过滤。最小修复为warm创建适配节点后原ROP input0改接adapter；adapter input0仍接原author。cold只读验证精确接线，保留verify_output_stage、完整USD语义比较和RGBA要求。其余原节点连线不得放宽；源HIP及旧冻结合同不改写。

软件修复将观测合同版本提升为 `bridge.official-karma-observation/3`，附带 `bridge.official-karma-output-topology/1`，明确记录唯一重接规则。旧/2观测仍由其冻结旧代码解释，不转写成新版本。真实修复后的重导、最终EXR RGBA/alpha及后续交付仍待新范围验证。
