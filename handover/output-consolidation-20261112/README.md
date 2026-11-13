# 执行经验与保留材料

整理完成日期：2026-11-13。本索引覆盖本轮开始时 `outputs` 的 317 个一级目录和 59 个顶层文件。按目录清点实际结果、摘要、回执及失败边界后提炼可复用知识；不把全部日志复制进 skill，也不把失败实验写成成功配方。两处仅有锁信息的目录按证据不足保留。

## 已归入 skill 的知识

| 入口 | 已吸收内容 |
| --- | --- |
| [工程与恢复经验](../../skills/vfx-visual-twin/references/engineering-lessons.md) | 任务恢复、控制器边界、产物身份、输出预算、打包、依赖保留和清理 |
| [原生执行经验](../../skills/houdini-bridge/references/native-execution-lessons.md) | 真实参数类型、宿主观察、冷开、保存、导出、Karma 写出及登记边界 |
| [制作与反馈经验](../../skills/vfx-visual-twin/references/production-feedback-lessons.md) | 几何目标语义、增量修订、接收恢复、观看图与软体实验的实际能力边界 |
| [软体诊断入口](../../skills/bridge-houdini-softbody/SKILL.md) | 已有专项诊断、有限修复和停止边界，新增原生执行经验入口 |

主 SKILL、插件模板和发布文件清单已接入这些参考。独立安装的 `bridge-houdini-softbody` 文档已同步；已安装的正式 `bridge-vfx 0.4.20` 包保持原字节，未以文档更新替换受签运行时代码。本地工程入口通过 README 与 AGENTS 指向以上知识。

## 清理结果

- 净删除 **112,775 个文件，5,550,444,544 字节已分配空间，约 5.17 GiB**。
- `outputs` 实测约 **16.72 GiB → 11.55 GiB**。这是目录占用口径，不等同于期间系统磁盘可用空间的净变化。
- 清理对象包括退役验证环境、递归复制的执行源码树、确认属于软件测试的临时数据库，以及 42 份内容相同的官方示例 HIP 输入副本。
- 42 份 HIP 副本均保留对应原件。H21 标准原件为 `outputs/official-karma-20261016/vendor-originals/21.0.631/karma_user_guide.hip`，SHA-256 为 `831b34f61491caab897aa357eead398e3d770ac2a1c9187ea4ca4e669cc29106`。
- 正式 HIP/NK/EXR、可用部分成果、原始素材、签名结果/停止/许可、密钥、仍被查询使用的源码和插件副本继续保留。尚不能证明无依赖的材料未删除。
- 退役路径不能用于直接重放旧执行；保留的 ZIP 与官方输入可供核对或按需恢复，未来新执行须按当时有效任务范围准备。

`net-retired-files.json.gz` 是最终净删除清单；`removed-files.json.gz` 是首次删除记录，应结合两份 `restored-*.json` 阅读，不能当作最终缺失清单。

## 核对结果与限制

- 763 项受保护内容中，761 项 SHA-256 未变；另外两项为按本任务新增知识索引的根目录 README 与 AGENTS。无非预期的受保护内容变化，见 `final-preservation-check.json`。
- 首次删除后，一份未选中的 `hserver.log` 增长 91 字节；最终核对还观察到该日志和 `.DS_Store` 的变化，以及结果查询期间 4 份宿主 binding 和 5 份 SQLite 共享内存文件的元数据变化。删除脚本未写入这些文件，不能宣称整个目录完全静止；其路径和前后身份单独保留。日志的实际写入来源未确认。
- 从 5 份工程登记表及动态任务/反馈状态展开，检查 2,057 份 JSON、16,640 条路径引用。首次扫描遗漏了动态状态中的旧包依赖；已从原 ZIP 恢复 22 份完整旧包、9,323 个原文件，并核对成员字节。补查中与清理集合相交的缺失依赖现为 **0**。
- 8 个原可选择工程的选择/任务目录保持一致；`completed-geometry-20261105` 在清理前已无法选择。目录一致不代表结果读取通过。
- 正规第三版通过正常入口重新读回 **COMPLETE / goal PASS**；前两版分别保持 PASS / FAIL。读取过程没有启动、重派或重做原生制作。
- 清理后的历史读取检查曾受版本准入和历史消费规则阻断。后续复核确认 **0.4.20 安装包自身 429 个文件与清单全部一致**；Geometry Gate 报错是读取器误用旧 0.4.9 清单比较新版模块，不是安装包损坏。读取器修复和安装验收另见 [历史读取修复](../history-reader-repair-20261113/README.md)。清理任务未改写旧结果或账本。

详细统计见 [net-cleanup-summary.json](net-cleanup-summary.json)。查询结果及定位证据见 `completed-results-readback.json`、`v3-readback.json`、`post-restoration-readback.json` 和 `reader-diagnostics.json`。

后续退役测试环境与源码快照的归档整理另见 [测试环境整理](../environment-consolidation-20261113/README.md)，其统计独立于本页原清理批次。

## 覆盖清单

- [早期工程与软件验证：116 目录](legacy-coverage.json)
- [宿主与原生验证：125 目录](native-coverage.json)
- [近期制作与反馈：76 目录](recent-coverage.json)
- [顶层文件：59 项](topfiles-coverage.json)
- [软件临时数据退役依据](software-fixture-retirement.json)
- [官方输入去重依据](official-input-deduplication.json)

以上清单用于追溯知识来源和材料保留原因，不替代正式项目的原生、视觉或生产验收。
