# 17 候选独立代码验收

审查者：`/root/live16_code_acceptance`（Bugbot，只读，未参与实现）。本文件由 root 保存审查者返回的结论；审查者没有运行测试、DCC 或 native probe。

**No P1/P2 findings.**

- 七文件 manifest：`273e077ee0d4e8e0fa851f77265d4f970b768c2b8b300120cbbc2cb9eaad197a`。
- patch：`9ef1ab943737b4816dea8650136dfc5c743d039ea5f6874b7f99fc23c1c058d7`。
- 17 scope：`a60e8000865c390946ef48110612707a29ca010ee084696cbd3f6ba0846d1633`。
- bindings：`37cb46bfeb0b7dbebc970c9d2871ffce582ac5eed19ff1dfa09a467c34f859fb`。
- review：`417b13638e217a6ff2b3453a930b028a5c38a53921e6204d4fdf44862ae0e118`。
- snapshot manifest：`1c10ef1273313f91336fec55e395f6124d627928bb4f6fd1276179e55efe0512`。

159 个 snapshot 文件全部匹配 manifest 和 activation review；与 16 执行快照只有 graph_trial、workbuddy_assembly、Houdini addon 三个生产文件不同。七文件 current 均匹配最终 manifest。

正式链显式传递并记录 `exact_type_name=True`；addon 的严格布尔校验发生在创建前。未显式提供该字段的既有调用仍保留默认行为。请求摘要、producer receipt 与 journal intent 均绑定新语义，旧 journal 不会被当作新语义复用。

`-B` 修改只同步测试 helper 对正式 supervisor argv 的严格预期，未修改生产监督器。两例测试进程列表为空的直接原因是旧 helper 在 Popen 前拒绝已有 `-B`，不是新增 exact flag 改变了进程执行。

既有 formal activation、Husk fileless hook、runtime-ready 后严格身份采集、失败即停和 8/120/600/512MiB/1-heavy/0-retry 控制未受增量影响。

实际成功路径启动顺序：alpha-husk → alpha-nuke → graph-worker → houdini-initial → houdini-reopen → main-husk（父票为 reopen）→ nuke-host → nuke-render。inventory 列表仅用于集合、配额及父子关系校验，列表排列不是执行时序。

17 仍为 PREPARED_NOT_AUTHORIZED，execution_authorized=false，native_execution_status=NOT_RUN；18 目标目录尚不存在。真实 16 已失败封闭；静态通过不代表修后真实工程完成。软件链及原始产物证据由另一位独立验收者核对。
