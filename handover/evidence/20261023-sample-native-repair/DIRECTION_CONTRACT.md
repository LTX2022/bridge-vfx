# 本轮实现与验收边界

用户授权范围：定位并最小修复真实 sample 身份采集超时；不增加生产超时、不削弱身份、不启动真实 DCC；保留 -06 至 -10 和八次预算。

## 当前采用方案

身份采集首个工具改用本机文档化的 vmmap -w -interleaved -summary PID，读取真实 Process、Parent Process、Load Address、Launch Time、Target Type；继续按原始 Load Address 独立定点查询唯一可执行主映像。05 原生对照分别用时2.083961秒和0.275768秒，均退出0、stderr空。该结果只允许实施，不代表稳定性或完整链通过。

本轮原 sample 在2.595271秒成功，没有重新制造或复现旧超时。旧02真实记录表明工具在符号处理阶段超过5秒；没有据此解释09历史TOOL_FAILED。修复目标是移除身份路径对性能剖析/符号处理的依赖，不是修改 sample 二进制。

保持现有身份schema、五头解析、定点主映像规则、前后ps、两lsof/vnode、无链接文件打开、stat/hash、双重观察和完整祖先、可信anchor、nonce与签名。不新增runtime UUID或第二份header额外门。tool5秒/freeze5秒/observe16秒/capture60秒及监督器原限制不变；删除只为sample设置的stderr例外后，所有非空stderr继续拒绝。

## 六角色职责

1. sample_direction：原生依据与强度等价、方案及验收门。
2. sample_repro：有限真实普通Python取证，原始输出/时序/回收/哈希。
3. sample_basis：本机man/help和可证边界。
4. sample_impl：唯一生产修改负责人，镜像、必要测试及新候选准备。
5. sample_code_review：Bugbot独立代码验收。
6. sample_evidence_review：独立真实采集/签名/账本/冻结证据验收。

root负责协调、原件封存、报告和交付。共享文件仅其负责人修改，审查者只读；并发上限分阶段执行。

## 冻结门

- 必要定向回归及真实OS完整observe、父子祖先正向与错误可执行文件反例。
- 实际普通Python supervisor使用writer_executable，真实collector生成完整signed started binding；核验nonce/argv/start-stop摘要/HMAC及可信停止，无模型替换。
- 一次无image-adapter的八阶段软件进程链；Houdini/Nuke API仍显式替身，真实OS采集不能被标成真实DCC/视觉/M1。首个失败停，不重复求绿。
- 代码和证据两位独立验收GO后，正式从unused -10准备新 -11，review未来 -12-authorized，默认只读预检；不激活。
- 新候选源与成功证据一致；旧06/07/08/09/10逐文件哈希不变，原始失败记录保留。预算8次/120秒/600秒/512MiB/1heavy/0retry不变。
