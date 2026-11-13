# 第二独立证据验收

结论：本轮真实普通 Python 身份采集与受控软件链证据通过，可准备新的未授权候选；真实 DCC、视觉、M1/HY3 和生产验收未建立。

02 在最终 process_image abb503b7 与 artifact_registry 837ad6f5 源码上通过，测试 70.975 秒。独立核对 8 张票据、7 组监督器、18 行签名 accounting：HMAC、顺序、前项摘要、末项 anchor、scope、identity、命令摘要、started/stopped 摘要与停止票据全部对应。退出码和 supervisor 码均为 0，execution_result=succeeded，descendant_result_unobserved=false；计费 66.406685114 秒，目录 51,290,625 字节。两份 alpha-output 事件独立绑定原始 start/stop 与 software_test。

真实 postframe 的两节点正反祖先链一致，进程、主像、宿主 anchor、预期 writer、hook/nonce/context/producer 摘要与 HMAC 对应，输出原字节 SHA 匹配。实际 H/N 三份可执行文件均为普通 Python Mach-O；软件 API 替身来源明确，原生进程采集使用真实 macOS 工具，未安装 image model 或 Popen bootstrap。

SQLite 原 DB 与 sidecar 仅复制到新临时目录后以 mode=ro 查询，6 个原文件前后 SHA 相等，四库 quick_check=ok。登记库 artifacts=2、versions=2、invalidations=0、registry operation receipt=1；两个产物均 version 1、AVAILABLE。Houdini 专用登记回执的自摘要、产物 payload 与帧快照一致；Nuke 冻结输入合同绑定 engineering_h21_main 的版本、payload 和 operation receipt，其 readonly-copy 消费 SHA 与实际 API 日志、原始输入 EXR 相同。Nuke 最终 NK、worker snapshot 与软件结果 SHA 一致，输出延续 software_test/NOT_OBSERVED 来源。

158 个 snapshot 文件同时匹配冻结清单与当前源码，174 个 source_freeze 文件全匹配，最终 10 文件清单及两组 controller/runtime 镜像一致，无 pyc。06–10 共 1,044 个原件逐字节不变且无新增，首轮失败 01 的 608 文件与成功 02 的 644 文件都与封存清单一致。首轮 NO_GO、原始 sample 未复现及 09 未知原因均保留原结论。

冻结限于 PREPARED_NOT_AUTHORIZED；预算保持 8 次启动/120 秒/600 秒/512 MiB/1 heavy/0 retry。完整软件链的单次成功不证明长期采集稳定性。

验收方法：独立只读 JSON/HMAC/SHA256 校验、SQLite 临时副本查询、源文件和 AST/manifest 对照；验收者未实现生产修复，未重复原生采样或启动软件链。具体路径与逐字段布尔结果见 successful-chain-02-audit.json；首失败另见 first-chain-01-audit.json。
