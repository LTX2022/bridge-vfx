# 导出拓扑修复真实结果（2026-10-27）

`outputs/official-karma-disklight-h21-topology-20261027-01` 在用户持续执行授权下经独立局部代码审查、完整机械冻结核验、64项软件回归和预算预检后执行一次。原ROP物理input0改接adapter，观察合同/3记录唯一接线变化；旧冻结/2不改写。

真实结果：warm保存成功，完整warm/cold观测相等；USD实际导出并通过Beauty RGBA属性验证。后续严格USD语义比较仅有 `/metadata/upAxis/authored` 从false变true，范围因此失败关闭。2启动／79.54253506660461秒，全部签名可信停止，无未观测后代；176冻结源未变。官方实验组累计18启动／444.68783378601074秒，旧范围余额不复用。

[认证结果](evidence/20261027-export-topology-live-01/result.json)绑定真实HIP、USD、停止与冻结源。最终官方参考渲染/alpha/Bridge HIP/NK/渲染均未达到，人工视觉未达到。

后续只读核实：H21.0.631内置USD25.05 fallback upAxis=Y；warm stage有效Y、authored=false；磁盘导出有效Y、authored=true。仅export比较显式采用 `h21_export_fallback_y_v1` 可将这一个布尔位false→true视作表示等价，要求字段完整、共同值Y，其余所有差异保持严格。原始观测与哈希不改，equivalence单独记录；默认与Bridge重建不启用。该软件修复65项受控回归通过、独立边界复审READY，真实修复后验证由新的axis范围进行。
