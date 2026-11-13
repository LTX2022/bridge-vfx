# 计时与完整工作量只读核查

核查者 /root/startup_cost_direction。7个关键源码与原授权冻结SHA一致。120由trial绝对deadline贯穿worker/supervisor，110是扣10秒stop reserve的保守窗口，240按准入到可信停止累计；不是重复扣时。

runtime指纹虽有多次，worker实测0.901953250秒，入口到evidence7.105774917秒，不能解释83.85秒。目录预算和producer全场景检查有开销，但无定量归因或可删除安全校验的依据；也无显著锁等待的证据。

成功fresh路径23nodes/17connections：41mut、30build queries、1私有initializer、2save/reopen、37post queries，共110dispatch+1initializer，不含initializer内部HOM和冷重开，不能当ETA。

batch缺正式白名单/精确类型/逐节点journal合同；bounded stages非跨进程save/resume，resume_not_started不能用于本轮已执行记录。无可直接用的绕行。

未改文件或运行宿主、采样；未读密钥/完整env/intent/旧DB。推荐先确认资源合同，不给最后INTENT定罪、不承诺120可行。
