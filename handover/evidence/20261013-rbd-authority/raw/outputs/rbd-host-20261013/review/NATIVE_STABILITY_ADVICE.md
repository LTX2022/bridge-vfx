# R04 同 build 文档依据与建议

已仅只读检索本机 H21.0.631/H22.0.429 `houdini/help/hom.zip`，无真实 native 运行。完整摘录、两份 archive SHA、Geometry/Attrib/SopNode member SHA和具体行号保存在 `same-build-stability-docs.json`，自有采集脚本为 `capture_stability_docs.py`。该材料是原生接口静态依据，不是本轮宿主有效性事实。

两版一致的可读接口：Geometry.txt:681 `vexAttribDataId()`、:689 `modificationCounter()`、:712 `primitiveIntrinsicsDataId()`、:723 `topologyDataId()`；Attrib.txt:244 `dataId()`。前者是文档明确描述的保守变化检查，包含 modificationCounter。modificationCounter 不跨 geometry 唯一，不能直接比较不同几何；跨 geometry 应用文档指定的 vexAttribDataId，仍需实际取得同 frame/output/source 的当前 geometry。

`freeze(read_only=True, clone_data_ids=...)` 两版分别 Geometry.txt:1533/:1539。普通复制默认产生不同 data IDs；需要比较ID时不能误把该默认复制行为视为原source变化。文档确认 geometryAtFrame 返回 frozen geometry、inputGeometry 返回 live unfrozen geometry，所以早期冻结对象不会在源后续变化时跟随更新；只再检查旧 frozen 对象不能关闭 R04。

不能单靠 IDs 签发一致：SopNode.txt:420 `managesAttribDataIds()`、:426 `setManagesAttribDataIds()` 明确存在由 cook代码自行管理ID的路线，且 cook外修改没有自动增量，需要修改者主动更新。此次允许固定底层事实的software边界也不得生成默认constant IDs来假装已观察稳定。没有发现跨 configure/carrier/consumer 的原子只读快照或全局几何版本锁接口依据。

建议保留用户提出的实际双观察内容冻结比对：重取 actual configure/carrier/solver-input 同一帧的原始事实，将 source/consumer内容摘要、上下文、wire、node session核对；三节点以及 packed embedded geometry 的实际版本/拓扑/intrinsics IDs可作为补充快速变化拒绝，不能作为缺少内容时的PASS回退。最后仍应检查身份/lease/frame/FPS/gates/wire，并保持帧恢复。该建议不授权 native执行、不计算请求的期待成功geometry。

另一确定 P2 为 R05/Host:203 的第二处 inputConnections遍历无界，两版最小probe先读10000条多余连接才由后续_capture拒绝。CURRENT_REVIEW.md及v6探针已含本项，可在同一修复批次收口；此前只提R01–R04的计划没有覆盖它。

接到主“停止重复同问题各版本”后未继续运行拒绝探针；此补充仅静态文档检索。当前CHANGES_REQUIRED与原SHA绑定仍为已审版本结论，整改版本须另行受影响复核，不能自动转PASS。
