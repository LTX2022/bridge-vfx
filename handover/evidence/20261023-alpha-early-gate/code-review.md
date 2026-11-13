# 独立代码审查

审查者：未参与实现的 Bugbot。最终代码结论：本次受审范围无待修 P1/P2，可执行 -04 软件边界整链；整链和候选证据另由第二验收者接收。

范围为 process_image、owned_process、alpha_calibration、run_alpha_calibration、三份 controller 镜像及软件工程夹具。未跟踪文件按冻结 -08、before 文件及最小补丁直接核对，不能以空 Git diff 判定没有变化。

已关闭的问题：工具清理异常覆盖原始采集错误；软件 alpha 子进程在身份采集完成前退出；外部测试适配器未冻结；隔离控制端未继承适配器而混用实际与模型观察。整改保留原异常和有界非授权诊断，清理未回收明确 leader_reaped=false；夹具只等待当前票据的认证 started 与同 PID；适配器源码内嵌并绑定摘要；两次隔离控制端与八阶段继承链已逐项核对。

软件工具模型只替换固定 sample/定点 vmmap 原始字节。真实 ps、lsof、唯一 Mach-O MH_EXECUTE 选择、文件打开/hash、正式解析、双观测、祖先链、签名与阶段门保留。sample 整段 header、出生时间的 .000 小数、主 Load Address 和 VM 映射为模型事实。测试 Popen bootstrap 包装监督器和两次控制端，随后运行原始源码并透传原 sys.argv/进程参数；这不能被称为原生启动命令完全未变。

监督器与控制端的精确匹配、未知命令直通、模块路径/源码摘要限制已经核对。生产身份比较、签名、5/16/22/120 秒时限均未放宽。

审查中独立运行过 Python 3.14 cleanup 受影响 3 项和 fixture 同步/alpha 生成 2 项。较宽组合中的两项真实 /bin/ps 用例在审查沙箱中被系统拒绝，不计为产品通过；最终执行组测试见各原始日志。没有启动真实 DCC。

最终所审 SHA-256：

| 文件 | SHA-256 |
|---|---|
| process_image.py 及镜像 | 4b9b6bde959d9d02dac1dc8440a52bf885ecf0e4045dc361f3233a5d7354d4f4 |
| owned_process.py 及镜像 | 1939887ccec25a2cc1431cb319683886d593cda52287ad52e8f7c1d32ecf3c09 |
| alpha_calibration.py 及镜像 | 26cb5e1c87e63ca131eb574e1923d4fc4c106fbcae685f2a5598492b9d2eda43 |
| tools/run_alpha_calibration.py | c2f94788509afcab1125d830b6e4c608becbe51fe11cba0b4f5146fff8037fe6 |
| engineering_image_tool_fixture.py | d1a7391f5a13565a0551a1e0f4f7c193e299589599bf1b6b6f9cfb8c337af6c3 |
| test_engineering_full_chain.py | f6289196ebb21c3505829aa74c7d9686ef9eb645759895a1d5db175a5838ebc2 |
| engineering_houdini_api_fixture.py | 6ad5143e1f25b5b9d69cef36d49e6b173a545eac31ec1bb68adef67092cca82c |
| engineering_nuke_api_fixture.py | cc5c2b399cb863afaae20d3b7b1bb9bd1e84ebc9f17794b5aa52258a128d8ed9 |

本结论不证明真实 macOS 映像采集、真实宿主或 M1 通过。-02 真实 sample 超时仍未解决，-03 混合来源失败保留原状。
