# 本轮限定独立复核（2026-10-16）

本轮两项互不重叠的只读复核均已完成。审查者未参与相应实现，未修改仓库或证据；以下为主控据审查返回记录整理，不把范围之外的项目改写为通过。

## husk 静态证据与正文

审查者 `agent_ed4e9b42-2335-4e05-9a58-aaa24bdf68cb` 独立检查两个 husk 文件的 SHA-256、大小与 arm64 UUID。自行解析 LC_FUNCTION_STARTS 并与 Apple 工具完整表比较（H21 3420 项、H22 3612 项）；十二个选定函数的符号起点、相邻 starts 半开边界、文件偏移、函数字节 SHA 及连续解码全部相符。

九条保存连接、六条 processor 指令均独立检查机器码 opcode、带符号分支位移、目标和导入 stub。H22 两个 filename create 调用点均存在；相关 stub 的 ADRP/LDR/BR、间接指针槽、间接符号表、nlist 和库 ordinal 相符。证据收录的 47 条选定调用/分支记录全部匹配，所列直接调用点数量已全查。仓库的 JSON 和脚本与主控指定的 tmp 原件字节相同。

审查覆盖[新正文](../../HUSK_ENTRY_AND_CURRENT_RELEASE_20261016.md)原生部分及 STATUS/NEXT_AGENT 顶部。静态/runtime、API 支持、逐产品/AOV、完整 filter 次序、实际 processor/config/context/LUT 和最终 alpha/零 alpha 的边界充分；未宣称完整调用图或提高 AVAILABLE。范围内未发现待修问题。

审查未运行主控脚本或厂商程序，没有 dlopen、原生模块导入、debugger/DSO、安装生命周期或生产运行。首次唯一 create 假定的历史失败日志、保留性与最终 ZIP 不在该独立审查范围。

## 当前源码发布与安装结果

审查者 `agent_b324a01f-ba6b-491a-ac01-95edde680d2c` 只读核对四 wheel 的 SHA、size、RECORD、metadata、当前 src 及留存安装 payload；三 Skill 的 ZIP 成员、manifest 摘要、当前 source binding；三套各 254 个原始证据的哈希与 inline closure。未重复安装或生命周期。

四 wheel payload 文件数 39/47/12/32，三 Skill 文件数 481/429/542 均正确。每套安装事件为 install(0)、install(0)、合成失败 install(1)、rollback(0)、uninstall(0)；失败安装属于预期故障保护用例。未发现发布范围内 P1/P2 或 PASS 误报。

两处 P3 建议已采纳并关闭：source_unchanged 精确指生命周期验证开始至结束 build_id 覆盖身份不变；完整 raw 中的软件任务数据库、WAL/SHM、身份及 signed receipts 明确作为无密钥审计快照随交付保留。最终措辞范围内无新增问题。

交付白名单共 792 文件：artifacts 8、build_and_verify.py 1、evidence 顶层 JSON 4、完整 skill-lifecycle-raw 765、logs 14。三套 operation 均 SUCCEEDED、stop_confirmed=1；scheduler 槽均 active=0；隔离用户根已删除。未发现签名密钥或可复用宿主认证文件。attempt/process token 属已终止尝试身份；HMAC 密钥不保留，signed receipts 仅支持原字节与哈希审计，不能据此重新验签、重签或恢复执行。

软件依赖闭包限四个本地 Python 包、软件 OBJ/SOP 链及已验证静态资源，不证明 FFmpeg/ImageMagick、真实 DCC/HY3、模型或工程闭环。两个 venv、build-source、原临时用户目录与全部认证/签名密钥不交付。

## 最终状态与未审范围

本轮指定静态与软件发布范围独立复核完成，无待修发现。工程闭环保持 BLOCKED，M1 保持 NOT_READY。新增 review/preservation 文件、最终源码集合和 ZIP 成员/CRC/SHA/历史交付保留由主控另外核对，不冒充为上述独立审查结果。历史 3/38/54 项及全量没有在本轮重跑。
