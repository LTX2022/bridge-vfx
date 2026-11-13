# H21 18 轮图初始化修复

18 轮原结果保持：41 条 COMPLETE 后，domain.initialize 为第42条 INTENT，未save。原始完整producer合同记录root + 23声明节点 + Karma settings锁定HDA内部18节点；initializer将41个后代与23个声明节点比较而停止。light、rendervar、mtlxnormalmap的精确类型创建已真实生效。

显式图检查在initializer及图交接两处使用同版HOM正式参数 `allSubChildren(recurse_in_locked_nodes=False)`。锁定资产本身仍严格比较，解锁内部及外来显式节点仍拒绝。原生操作、保存、重开及指纹的完整scene_contract遍历保持全递归。catalog内部Obj/obj只在预期端固定转换为原生Object/object，真实类别继续严格比对。

五文件最终字节和补丁见 after-sha256.json、change.patch。正向应用得到全部after字节，反向恢复全部before字节，当前源码一致，见patch-roundtrip.json。既有16精确类型及身份/预算修复保留。

验证：Py3.11必要核心34例通过；补充底层假HIP保存/冷重开1例通过。完整正式软件链02在54.090006秒通过，保持8次工作进程预算、真实OS身份观测和0自动重试；HOM/USD、内部节点及像素仍为明确软件替身，native_dcc_execution=NOT_RUN。实际软件输出确认23声明节点、42个graph operations全部COMPLETE；原始save回执和最终active saved contract仍包含内部18节点，重开节点/参数/连接核对通过。详细事实见software-chain-native-02/native-api-differences.json。

软件链01在保存时因底层DefinitionNode缺少假HIP序列化器的parms_dict接口而失败，原件保留；只补该软件容器并直接验证持久化后，使用新目录完成软件链02。未重复已覆盖34例，也未重跑真实任务。

真实参数keys核查未发现紧邻计划缺字段；模板类型、menu tokens与hidden/disabled/locked事实未观察，仍为NOT_OBSERVED。软件内部18节点仅模拟路径/类型/锁定遍历，其真实内部参数未建模。本包不作为原生验收，不激活未来真实尝试。

18原件保存验证见stopped-18-preserved.json；所有SQLite查询仅使用/private/tmp中的原字节副本。根因白名单与同版API依据见root-cause-whitelist.json和native-basis/read-only-findings.md。
