# H21 sphere_ground_v2 既有事实核查

范围仅为18轮已停止图及同图 initializer→bind/inspect→save/reopen。未运行DCC、原生probe或测试，未读取原SQLite；查询使用 /private/tmp 的数据库副本。

- 第41条为最后 COMPLETE（material→material_output连接）；第42条为 domain.initialize INTENT。
- 第41条原生回执完整合同42条：root + 23显式图节点 + settings/karmarendersettings内部18节点。即41后代；initializer只声明23节点，因此全递归集合比较误报外来节点。
- H21已安装hou.py中allSubChildren正式参数recurse_in_locked_nodes默认为True。False时保留锁定资产本身，排除其内部；非锁定节点继续递归。不是单层children，也不是按名字过滤。
- 显式图等集合检查只修 graph_initialize_registered_domain(原6283) 与 _fx_bind_graph_trial(原6419)。GraphJobWorker._verify仅查询显式父网络，本身不进入HDA。
- 原生操作scene_contract(原13074)、保存capture(原15761)、重开完整verify(原15843)和指纹遍历保持完整递归，保留锁定内部原始事实。
- 真实回执root与四个网络为Object/subnet、Object/geo、Object/matnet、Object/ropnet、Object/lopnet。catalog内部token为Obj/obj；仅预期固定映射到原生Object/object后严格比较，原始事实不归一化。
- 同图必需参数keys已对照最后COMPLETE真实合同，全部存在。tuple按真实组件还原：normal_map.in对应inx/iny/inz，t/r/rad/lookatposition对应xyz，settings.resolution对应resolutionx/y，material.base_color对应base_colorr/g/b；materials与nummaterials均有第一行子字段。
- 真实合同不提供模板类型、menu tokens或hidden/disabled/locked状态；这些验证仍未知，参数keys存在不代表它们通过。

源点依据：本机H21 hou.py 的 allSubChildren说明；18停止后完整producer回执；本仓库可信registered-domain与frozen-scene参数计划。以上是只读证据核查结论，不是原生验收。
