# Houdini 22.0.459 运行映射实施计划

活动验收目标：21.0.631 + 22.0.459；保留现有22.0.429运行兼容和原始证据。当前计划来自只读源码调查，不改变冻结源码、capture、版本或SHA。

16个直接版本模块：

- `packages/houdini-bridge/src/houdini_bridge/crowd_helpers.py`
- `packages/houdini-bridge/src/houdini_bridge/native_cloth_wrinkle_program.py`
- `packages/houdini-bridge/src/houdini_bridge/native_crowd_hair_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_crowd_route_contract.py`
- `packages/houdini-bridge/src/houdini_bridge/native_flip_rbd_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py`
- `packages/houdini-bridge/src/houdini_bridge/native_ocean_mask_program.py`
- `packages/houdini-bridge/src/houdini_bridge/native_particle_emission_program.py`
- `packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_pyro_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_render_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/native_swarm_controls.py`
- `packages/houdini-bridge/src/houdini_bridge/native_vellum_domains.py`
- `packages/houdini-bridge/src/houdini_bridge/product_control_definitions.py`
- `packages/houdini-bridge/src/houdini_bridge/render_writer_facts.py`
- `packages/houdini-bridge/src/houdini_bridge/task_host.py`

额外必要核查：`native_crowd_transition_contract.py`继承route版本表，但原生consumer/Ramp共享SHA需给459显式归属。无名为require_version的集中函数，版本守卫分散在各模块VERSIONS/SUPPORTED_VERSIONS及_domain/_version；继承消费者见JSON。

已确认的459独立原件SHA由静态worker提供，待其保存完整来源链后接入：

- `route_dialog`: `7919bf5833be4dbda326f4e47773cb35dd131712473919a368b2beef432e015f`
- `hom_geometry`: `b14324302f4481e0e4dad87e2920e0e10ea01d87182db8b0352a5b5a2cc01bae`
- `hom_parm`: `01e930c2f95921c43b962a7a4ace809b978fbe49d987d4bfe12029bfef985704`
- `hom_ramp`: `600a5069a5288905aaaa490f8e8834346a438788cd515f24db3cfed6fdaa45f3`
- `crowdstoolutils`: `1c4e4af57e9f3fb88fe2673aa5b099ab318c264c0de3c1f716c43a44a96326a8`
- `transition_perform_transition_parm`: `c6d04257dcf8d2713992b82eede36adb44732686ed0187ced74741fd16e2b9ab`
- `karma_dialog`: `cc263cb8a2e6e1f964363999322d8395f7c52d7160ea723173a24b23568783fe`

可复用范围须逐项由459原始HDA/文档/SDK与429历史记录比对成立；没有比对完成的family不能仅添加459标签。新证据独立保存；旧429源路径、capture/version及SHA原字节保留。编译builtin缺HDA保持缺口，不变成CAPTURED。

render特殊风险：429有两处pixelfilterscale gate，459原DialogScript公开scale、隐藏size。还需核同版消费者怎样将size/scale写入USD；不把隐藏size标为公开可编辑字段，不猜乘法/有效宽度。writer入口只增精确版号，实际hook/foreground模板、签名和最终字节重验保持；实际PXL/OCIO/filter/alpha缺口不升级。

静态source选择位于包外：native_schema_test_boundary以versions[exact_version]和digest-bound supplement选取；software_render_api_boundary有source_for和Crowd版本索引。由入口owner/root接入459独立新源。仅改包内版本表无法让这些工具正确读取459。shared addon、catalog和mirror由root/入口owner单写。

核心测试调整：

- `test_native_pyro_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_vellum_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_crowd_hair_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_flip_rbd_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_particle_ocean_geometry_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_render_domains`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_particle_emission_program`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_ocean_mask_program`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_geometry_controls_program`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_cloth_wrinkle_program`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_swarm_controls`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_crowd_route_contract`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_native_crowd_transition_contract`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_render_writer_facts`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。
- `test_product_control_definitions`：仅扩确证459纯API/数据选择；模块内进程/宿主测试由主控集中运行。

测试还需覆盖：459精确原件SHA/typed参数与版号绑定、旧429字节完整、无跨版本fallback、render H22 gate、writer仍BLOCKED。新增current目标21+459；历史429完整性断言不改标。JSON附全域operator/节点字段需求，供静态worker精确对照。
