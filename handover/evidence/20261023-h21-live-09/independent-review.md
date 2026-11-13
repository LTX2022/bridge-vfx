# -09 双独立验收

## 身份、预算与停止验收

审查者live09_receipt_review，只读认证激活HMAC、08review、158快照、预算及两组started/stopped/alpha-output。-09授权来源和两个hash匹配。实际2/8次启动，husk11.857391秒、Nuke4.933624秒；stop及身份摘要认证成功，native/supervisor均exit0、无未知后代，重作业串行。会计累计16.791015秒，未超限。

husk started缺writer_process_binding，error=ProcessImageError:PROCESS_IMAGE_TOOL_FAILED。Nuke有原生17.0v1绑定。空binding最终触发INVALID_STRUCTURE，不能把该结构错误误当最早工具失败的根因。-06 242/-07 183/-08 183文件集合与哈希完整保留。

## 输出、数值及执行路线验收

审查者live09_output_review，只读检查real_host配置、实际host二进制hash、无软件边界，以及两组已签输出。完整解码5 EXR均128x128 HALF RGBA、全部值有限，chart NONE压缩、Nuke4图ZIPS。文件hash/长度与原始输出回执、观察JSON一致。alpha三中心为0/.5/1、RGB0/.39990234375/.7998046875；黑白底和加色读回符合数值要求，专项数值函数关联模式为associated。

数值不替代身份校准。husk采集错误被保存但runner先检查进程退出及EXR，仍启动了Nuke；最终authority校验把缺binding变为{}，再触发结构异常。这是最早失败门未提前拒绝的缺口；没有依据认定sample权限是工具失败原因，现有记录未保存具体工具argv/returncode/stderr。

Nuke原stderr有ACEScg菜单追加警告；本次Read/Write raw=True，不能声称已观察到OCIO转换。真实HIP/NK/主场景EXR不存在，后续阶段NOT_REACHED。已看诊断图但未把其当球地面或人工视觉验收。执行者artifacts清单8项hash正确。

## 接收结论

本轮真实工程闭环FAIL，原生alpha身份专项不接收。可以交付5个实际校准EXR及数值观察，但不能交付尚未生成的HIP/NK，不能提升M1/HY3/生产状态。scope已关闭，不续跑、不重试、不额外启动DCC。两位审查者均未参与实际执行、未修改记录。
