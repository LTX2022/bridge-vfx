# G03 跨帧静态 source 读取交付

本批限定软件组件修复完成。只修改指定的 Host/Registry 两个模块及 package/controller 镜像，以及两个指定测试模块。未修改 addon、正式测试、通用输出 collector、项目状态文档；未提交、推送或运行真实 DCC。

## 集成接口

- `_fx_geometry_source_geometry(node, provenance)` 签名不变，返回显式 rest frame 几何。Registry 优先调用实际 `node.geometryAtFrame(provenance['frame'], output_index=provenance['output'])`；没有此 API 时，仅当前帧恰为 rest frame 可沿用原 `geometry` 路径。跨帧缺 API 拒绝。
- 跨帧分别观察 rest 和 `node.geometry(output_index=0)` 的当前输出；当前 P/N/id、类型/精度/tuple/array 存储、点数与 Polygon 拓扑必须与实际 rest 完全一致。rest 完整哈希须匹配认证冻结输入。比较几何内容时只排除观察帧标签；当前观测保留实际 current frame，并独立计算包含该帧的哈希。
- Host 增加 `context['source_sampling'] = {rest_frame, current_frame, current_source_geometry_sha256, static_source_verified}`，只作为观察事实。`context['source']['frame']` 保留实际 rest frame；basis、userData、registration 和完整 checkpoint 格式及严格比较不变。参数 readback 仍为 `BLOCKED/parameters_only`。
- 原 context/身份/文件/节点守卫保留。前后 frame 覆盖 rest/current 延迟几何读取；实际参数采集完成后再次核对 binding、Registry-authenticated provenance（重新读取并验证实际文件哈希）及 before/after frame。无 setFrame 或客户端默认授权。
- 采样信息进入现有冻结 plan context，因此准备后切换采样帧拒绝写入；失败恢复保留原有针对实际自有目标的 restore 权威，不用已漂移的外部输入授予 forward 权威。
- Registry 和 Host 都检查当前 source，避免直接使用 Registry hook 或直接注入 Host hook 时绕过静态 source 验证。

## 实际验证

Python 3.11.9，Windows-10-10.0.26300-SP0。全部仅显式底层 API；未运行真实 VEX、solver、render 或 DCC。正式 addon/client/进程集成由主 agent 负责，本交付不将组件通过冒充正式通过。

最终命令：

```powershell
.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/agent-crossframe/run_tests.py final-v1 test_native_geometry_controls_host test_native_geometry_runtime_registry test_geometry_registry_checkpoint
```

84 methods，0 failures，0 errors，0 skips，exit 0，51.093 秒；指定六个源码/测试文件运行前后 SHA 不变。原始日志 `final-v1.log`，完整命令、解释器、平台、源码 SHA 见 `final-v1.json`。

覆盖两 build 静态负/零/正帧读回、跨帧写入及恢复、动画 P/N/id/拓扑/精度拒绝、缺 rest/current/API 拒绝、两阶段延迟 frame/input/node/identity 漂移、参数末端 frame/input/node/identity 漂移、准备后换帧拒绝、写后实际输入文件损坏回滚，以及跨帧前后完整 checkpoint/userData 严格相等。16 个原 checkpoint/reopen 组件方法保持通过；不据此声称本轮实际 new PID 正式进程验证。

`baseline.log/json` 为改生产源码前的实际单项复现（exit 1）：H21 在 frame 2 明确报 `GEOMETRY_SOURCE_FRAME_REQUIRED`；该初版循环未在失败后清理 cohort，H22 次错误为夹具身份遗留，并非第二个独立跨帧复现。失败夹具已修正 try/finally，最终双 build 均通过；主 agent 另有独立双 build 正式 baseline。

`targeted-v1`：62 methods/1 failure，exit 1；精度反例初值误设为原 float64，无实际变化，已改为切换 float32/float64，保留失败原件。`targeted-v2`：65 methods pass；`targeted-v3`：66 methods pass；`checkpoint-compatibility-v1`：16 methods pass。这些均为阶段记录，最终结论绑定 final-v1。

## 源码绑定

- Host package/controller：`746d67950a12007461a4d5b4882eed071f41368bc7707254d2ef7ca930e26d9b`。
- Registry package/controller：`3c1f762a54fbaff37b6c31c1987f84fb15fb79fa864abdc1fc0caa7e54c50e23`。
- 两对镜像完全一致且 AST 可解析，原核对见 `mirror-verification.json`。六文件完整 SHA 见 `final-v1.json`。
- 同 build 接口依据：仓库已捕获 `docs/native-basis/sopnode-geometry-output-static.json`，两 build `geometryAtFrame(frame, output_index=0)` 返回指定帧的 frozen Geometry；`geometry` 为当前输出，非 frozen，不修改它。

## 未宣称完成

实际变形输出、其他属性保持、下游 transform/copy 消费与实例 count/seed、真实原生跨帧 cook、正式保存重开和全域验收仍需各自证据。固定 @P 程序只对已检查的静态 source 开放软件跨帧参数路径；动画 source 不采用猜测公式或重新授权。
