# P01 最终补修复核（2026-10-14）

**CURRENT_SCOPED：R08、R09 CLOSED_CURRENT_SCOPED，本次要求范围内无剩余开放 finding。**
R01–R07 保留此前关闭记录及同一探针修补后原件；本批未重跑它们。旧 CLOSURE.md/SOURCE_BINDING.json 与冻结失败原件保持不变，本文件追加最终修补结论。审查子任务完成，交主 agent 归档。

## 本次仅复跑两个旧探针

| Finding | 两版实际结果 | 原件 |
|---|---|---|
| R08 | BeforeClear 后 records=0；实际销毁旧 root、无 P01 配置 public rebuild accepted；legacy birth_rate=1800 accepted；rebuild 后 records=0。 | [registry-lifecycle-r08-fixed.json](registry-lifecycle-r08-fixed.json) |
| R09 | 普通 particles/no-source_plan public build accepted；被动 instrument 原 Host.build_transaction，实际进入一次，旧结果为零次。 | [public-build-scope-r09-fixed.json](public-build-scope-r09-fixed.json) |

版本为 21.0.631、22.0.429，两个 probe process 均退出 0；源码执行前后相等，绑定时仍匹配当前候选。探针使用实际软件 client/dispatch 与显式底层 API，未替换正常成功回执。没有新增或扩大探针。

实际命令：
```powershell
.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/registry_lifecycle_probe.py --legacy-only
.venv/Scripts/python.exe -B outputs/particle-emission-20261014/review/public_build_scope_probe.py
```

## 只读接线核对

- trusted scene event 在 epoch 递增后调用 Host.invalidate_scene；在私有 lock 内清 records/snapshots，保留 active build scopes。
- Host.build_transaction 进入时检查旧实际节点消失/session 变化；同 root 有 pending snapshot 则拒绝，旧记录按 exact-pointer CAS 清理；原异常撤回不删除后继记录。
- public _fx_build_preview 在 root fence 同层包裹 P01 build_transaction，普通及 source-plan 两分支均位于该 scope 内；source transaction 去掉重复 P01 scope，registered initializer 保留自身 scope。
- 新永久第六 addon 方法的 actual public client 与 original scope instrumentation 已只读检查：first build 一次、clear/rebuild 两次、legacy birth_rate 成功。该方法本 reviewer 未另行执行。

以上 only-read 部分不声称新增 runtime race/source-plan/pending-token 测试通过。现有两个实际反例已关闭，未见本次改动留下对应接线缺口。

## 源码绑定与日志准确性

完整补修绑定见 [SOURCE_BINDING_FINAL.json](SOURCE_BINDING_FINAL.json)。当前 addon SHA256：
`ffa6c676f0e163b6c48ddb9d631c479584af6a229b394919ce62646e5c6b904b`；
Host SHA256：
`1bbca1fdab7e5a4bae31aaa0cdd6c5d254051846fc2b374a2c5bdadd78416ab8`；
addon test SHA256：
`bddfd000b2df850fea4a34980c23afeb88191ffd4b3485f816cf1db8553a9444`。
Host/controller 镜像字节相等。

此前 24 方法 command34.844/suite34.397 秒、435 before/after/current0diff 是**此前候选**事实。本批比该快照改了 addon、Host、Host 镜像、addon test 四文件，因此不能转述为补修后再次 24 方法通过。本 binding 以原 435 文件 source_after 加四文件实际新摘要构成当前完整源码绑定；这不是测试执行前后证明。

此前 54 方法 command36.531/suite36.068 秒及两项 Oceanfoam 静态 NOT_RUN 同样保留原边界，不重写为通过。若主 agent 补修后集中执行新 affected 组，应另附其命令/日志，不覆盖旧原件。

## 保留边界

CURRENT_SCOPED 指当前两个修补与此前 P01 参数表达式/软件事务审查发现关闭，不能升级为完整生产验收。R01–R07 依此前修补后原件继承，非本批重跑；真实 POP 子步/几何/积分、generated seed 完整链、新 PID 恢复、macOS 与全 16 域 M1 均未验证。

生产/tests/主移交文件只读，没有 commit、DCC 或全量/正式进程运行。旧诊断保持不可改写。本子任务至此结束，不继续调查或新增探针。
