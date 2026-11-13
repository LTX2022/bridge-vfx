# 本轮限定独立只读复核（2026-10-16）

复核者：未参与本轮研究、脚本或报告实现的 general-purpose agent（`agent_b21d7d26-79b7-4656-9b1d-eb7fda598dff`）。本记录由集成负责人根据其最终回报整理；审查者未写入文件。

**结论：本轮静态证据与正文增量未发现实际影响的 P1/P2/P3；工程 BLOCKED、M1 NOT_READY 的表述与证据一致。** 此结论限下述范围，不是全仓、安装或完整工程接收。

## 实际复核范围

- 两版精确库的 SHA-256、字节数、UUID、安装 build 标签；每版9个列入函数的精确符号、`LC_FUNCTION_STARTS` 半开范围和关键调用机器码。
- 新报告 `handover/WRITER_SAVE_IMPLEMENTATION_20261016.md`，以及 README、STATUS、NEXT_AGENT、较早采集决策报告中的四处导航补充。
- `static-verification.json` 所列7个复制文件的大小/SHA；原研究证据及三个脚本与临时交付逐字节比较；研究记录与复跑记录的声明字段比较。
- 审查者未运行交付脚本、未重复主控复跑、未扩展 tracing、未执行厂商程序或导入厂商模块。

## 核对结果

直接 `bl` 调用表与原证据一致，且报告没有将可能的静态调用边写成实际 husk 运行、固定执行顺序或全部 AOV 覆盖。`allocValidFile` 的 vtable **288字节偏移**所指目标保持未解析；未见直接 tile factory 调用没有被提升为完整路径绕过。filename-only functor 没有被命名为已确认的 `setFileCreateCB` 注册槽或 writer 交接接口。

自动检查与人工解释的界限明确：库身份、函数范围、连续解码和选定调用由脚本检查；参数流、全局槽及支持契约解释属于人工判读。脚本固定 observation 布尔值没有被表述为自动数据流证明。

7个复制文件的大小/SHA全部一致；原研究证据和三个脚本与临时交付逐字节一致。研究输出（Python 3.11.7）与复跑输出（Python 3.11.16）仅忽略记录声明的 `generated_at`、`platform`、`python` 和 `raw_outputs_directory` 后完整相等，覆盖两库、18个函数、18条关键指令和间接调用清单。

四处导航保留旧轮24条来源、3项软件用例的日期与范围，新增函数体证据单列。未将内部实现证据扩大为实际 writer、processor、alpha 或官方支持事实。

## 不在本结论内的事项

本次审查未覆盖原有全部工作树、真实 husk/宿主、processor/alpha 运行语义、生产 AVAILABLE、安装包或完整 M1。保留性比较、归档构建及包完整性由集成负责人另行检查，未纳入独立审查结论。

审查读取时报告所链的本文件和 `preservation.json` 尚未生成，审查者将两项列为交付收口要求；本记录落实其中审查出口，保留性结果另见 [preservation.json](preservation.json)。不因审查无发现而推断未执行阶段通过。
