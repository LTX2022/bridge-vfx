# H21 live 12 独立产物验收

结论：FAIL_CLOSED_AT_ALPHA_WRITER_BINDING。driver exit 1；最早失败为 `ALPHA_NATIVE_WRITER_BINDING_REQUIRED:ProcessImageError:PROCESS_IMAGE_TOOL_FAILED`。

原始 started/stopped 两份回执 HMAC 认证通过，停止回执 execution_returncode 为 0。唯一实际作业为 alpha-husk，PID 40601；缺少 writer_process_binding。签名诊断保留 vmmap summary exit 0 及 474 字节非空 stderr，明确报告目标处于 dyld 已初始化、libSystem 尚未完整启动阶段。严格门拒绝，未生成 signed alpha-output 或校准终态，不能把进程退出或 EXR 有效性认作原生 alpha 校准通过。

校准 EXR 全量解码为 128×128、A,B,G,R 通道，16384 像素、65536 样本、128 行，全部数值有限。三个固定点 RGBA 为 [{"xy": [16, 64], "rgb": [0.0, 0.0, 0.0], "alpha": 0.0}, {"xy": [64, 64], "rgb": [0.39990234375, 0.39990234375, 0.39990234375], "alpha": 0.5}, {"xy": [112, 64], "rgb": [0.7998046875, 0.7998046875, 0.7998046875], "alpha": 1.0}]；独立数值匹配模式 associated，非平凡 fractional alpha 像素 3060。原冻结容差保持 Karma 0.02、Nuke 0.0001；Nuke 黑白合成及零 alpha 加性保留均 NOT_REACHED。

USDA 的三档 opacity、base/specular=0、emission=1、emission_color=(0.8,0.8,0.8) 与冻结配方一致；dataType=color4f、husk=color4h。该项仅是原件静态核对，原生材料模板/值读回 NOT_REACHED。H21.0.631、Nuke17.0v1、plugin build 和路线摘要已核对冻结文件及当前二进制摘要；实际 husk OS image 未完成绑定，Nuke 未启动。

HIP 保存/新进程重开、NK 保存/新进程加载及 Read→Write、主图、产物登记操作回执、上游版本/digest、Nuke 合同/只读副本消费和输出登记全部 NOT_REACHED。范围内无数据库或 sidecar，未发生原库查询；没有登记或消费 PASS 原件。用户视觉验收 PENDING，工程闭环与 M1 未通过。

来源保持 real_host 的本轮尝试标签，但未形成可认证原生 alpha 结果；writer/filter/flush/close 内部事实保持 NOT_OBSERVED。项目颜色为人工确认 ACEScg / human_project_selection；原生菜单读回未到达。

保留警告：`EnvControl: HOUDINI_USER_PREF_DIR missing __HVER__, ignored.`。

只读验收前后 227 个非私密原件的大小和 SHA-256 一致，无新增、删除或变更。未启动 DCC、probe、模型或渲染，未修改源文件；密钥仅本机认证，未复制 intent 或环境。完整数值、原件摘要和未到达项见 audit.json。
