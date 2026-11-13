# 本轮独立复核

审查者：未参与对应实现的 Bugbot（`/root/bugbot_completion_1015`）。只读审查；未执行测试、宿主或模型。

最终结论：本次冻结增量无待修P1/P2。范围限独立几何/有效材质及其兼容整改，不代表全项目无缺陷或原生验收通过。

旧 `sphere_ground_v1` 保留单SOP Merge角色、连接、source reference及原SceneContract字段；新 `sphere_ground_v2` 独立注册双SOP Import。GraphMCP、worker和私有初始化均要求配置profile与提案profile相同。旧JSON原字节及源码/controller镜像保持；v2的USD prim/有效材质验证不倒灌旧v1。显式软件替身仅提供底层API，不构造正式图或成功回执。

必要审计记录：初审发现同名v1被原地改图，旧保存工程无法重开（P2）。已通过独立v2及原v1严格读回分支整改，复审关闭。源码和受影响测试指纹见同目录 `source-sha256.json`；下列是审查者确认的最终指纹。

| 文件 | SHA-256 |
|---|---|
| graph_catalog.py | 78717e7693cdc91d8fab2568c9e2ba0180f1fa64fbf090e0c5e16f7415ae8ec6 |
| graph_job_worker.py | fba435d86d690ee7e753dbcb98c52d63e5ab5f4b4e1ec18aed9822a9e2ca6374 |
| workbuddy_graph_mcp.py | b9fcbb109632afdf5cdea44fd9e22be99b00af7367be4b5d72e203576080e414 |
| native_render_scene.py及controller镜像 | a20259f554c16661602a5f4ed2c7baed16b54e5d621c2a5900646aea75b06058 |
| houdini_bridge_addon.py | 9bf5b8c008424e8ee7b2a7e88adb9d21730dbfdf4af1e09931f39a27472986be |
| software_render_api_boundary.py | c2e5331f23b7b72091c9306c2ecee5ed97f9edbc0c2025ef38d24c389c10edbc |
| test_frozen_render_scene.py | 90d67676ebe0635be66dc7529794c27495159b15dc2b19305d0ecf692b7dd27c |
| frozen-scene.json | 66b6147ab6fc84d9827e587edd97b1ec46e5c27e3c625ba098685b2b3fcabfc3 |
| frozen-scene-v2.json | 59a9b54e5d201345dc7ac95487bb668a5c66f3ce8f2b573c4a7ccb209b9f56b6 |
