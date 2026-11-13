# 2026-10-13本批证据

[修复与剩余内容](../../BATCH_REPAIR_20261013.md)说明本批边界。这里只保存精选原日志、实际命令/退出结果和复核材料，不携带凭据、运行签名密钥、完整临时目录或安装包。源日志字节不改写，`.gitattributes` 对本目录关闭换行归一化；[index.json](index.json)逐项记录来源、字节数与SHA-256。两个大 journal 使用无损 `journal.sqlite3.gz`，索引另列原件SHA/字节数，已校验解压后逐字节一致；outputs 原件不改动。

- [源码绑定](source-binding.json)：本批14个改动 Python 文件的当前字节，及最终正式 Crowd 两版生成快照各131个文件与根源码的核对。不是全16域接收。
- [最终 Crowd 命令和退出码](crowd/final-frozen-source-20261013/run.json)、[原日志](crowd/final-frozen-source-20261013/unittest.log)：两版正常正式软件入口通过，115.484秒退出0。
- `crowd/final/<版本>/`：实际 trial、生成 snapshot manifest、worker result、journal、停止摘要及 Houdini/worker/Nuke 原始签名停止回执。每版68 COMPLETE、149条原生操作证据；worker内保存/重开不是新PID重开验收。
- [初始失败](crowd/baseline-20261013/unittest.log)及其余 `crowd/*/`：fields→compression→blend→profiler/预算的实际失败过程，没有重标PASS。一次180秒无效配置被启动前拒绝，保留原件。
- [组件85项日志](tests/batch-20261013-components-final.log)：G03独立整改前的范围绑定结果；不能替代新增身份反例。[整改后28项](tests/batch-20261013-g03-plan-identity.log)验证G03最终host/program。
- [AOV/回执/合同/副本41项](tests/batch-20261013-render-corrected.log)：40通过、1个macOS原件缺文件跳过，不计PASS。[错误模块名原日志](tests/batch-20261013-render-integration.log)另保留。
- [领域图与作业28项](tests/batch-20261013-domain-catalog.log)：原模块定向通过，不表示标准全量。
- [AOV原生接口原件与复现](output/COLLECTOR_REPORT.md)、[安装文件/member摘要](output/collector-native-basis.json)：静态接口及底层软件观察，实际OCIO/alpha/filter执行仍BLOCKED。
- [Crowd独立复核](review/crowd.md)、[AOV/G03初始复核与P2反例](review/output-and-geometry.md)、[G03 P2独立关闭](review/output-and-geometry-p2-closure.md)：最终身份封印经28项及两版10个独立身份反例验证，原反例保留。结论限本批指定组件，不授完整G03/全域接收。

本机完整过程留在 outputs。安装、macOS目标机、真实宿主、HY3/模型、视觉和生产验收均NOT_RUN。复核/日志中的绝对临时路径只描述当时实际运行；接收者不能假定清理后的路径仍存在，也不能用历史密钥重新签发。

仅复验本批单元模块时，在仓库根使用现有解释器和底层夹具：

```powershell
.venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_native_geometry_controls_host.py -v
.venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_render_color_facts.py -v
```

正式 Crowd 必须保留实际生成控制端/任务宿主；集中执行，环境 `BRIDGE_TEST_CROWD_VERSIONS=21.0.631,22.0.429`，不启用 `BRIDGE_TEST_CROWD_TRACE`。完整本机命令、解释器和原运行目录以对应run.json为准；本目录归档的脚本/报告不是替代生产runner。
