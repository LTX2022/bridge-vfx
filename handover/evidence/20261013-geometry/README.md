# G03 接线修复原件与当前源码

[修复报告](../../GEOMETRY_WIRING_20261013.md)描述改动、实际结果和剩余内容。[index.json](index.json)记录78个原件的来源、原始大小/SHA和归档SHA；`.gz` 为无损原字节压缩，解压后摘要须与index一致。此目录不含运行签名私钥或凭据，不重新签发历史事实。

- [source-binding.json](source-binding.json)：17个相关源码文件、当前HEAD及四个实际生成清单。`formal-final` 两版各133文件与当前源码一致；较早`formal`两版明确保留Host/Registry后来变化记录。
- [control-inventory.json](control-inventory.json)：20项批准控制当前5项有条件映射、15项blocked；映射不代表原生输出、生命周期或M1通过。
- `tests/`：中心实际命令、Python/系统版本、源码前后、退出码及原日志。大日志为`.log.gz`；97/11/65方法命令的失败状态没有重写。
- [最终65方法原命令/摘要](tests/geometry-wiring-20261013-review-fixes-final.json)及[原日志](tests/geometry-wiring-20261013-review-fixes-final.log)：两版正式流程和其余受影响方法通过，输入漂移方法错误断言包装码造成两项子项失败；整体仍FAIL。
- [纠正断言后的两版定向摘要](tests/geometry-wiring-20261013-input-drift-corrected.json)和[原日志](tests/geometry-wiring-20261013-input-drift-corrected.log)：最后单项退出0，参数/登记/清单回滚与后续拒绝全部成立，不重新跑已通过组。
- `formal-final/21.0.631/`、`formal-final/22.0.429/`：实际trial、反馈、save/reopen、目标参数、停止及前后宿主身份。`geometry_refusals.json` 证明两个实例均拒绝无基准G03写入；它不是G03完整正常链证明。大型saved.json和软件HIP以原字节压缩保存。
- [独立原发现](review/final-review.md)、[最终限定关闭](review/CLOSURE.md)、[整改反例原日志](review/round6-fix-closure-execution.log)：P1写后输入漂移回滚、P2延迟读取帧变化及快照泄漏关闭。更早全局Python/错误断言失败原件只保留为审计，不算项目解释器通过。
- `domain/` 和 `integration/`：当前直接拒绝基线及最初接线调试。并行写入阶段或缺正确源路径的结果明确是诊断，不算最终冻结接收。

所有临时路径只用于原始来源定位。此批只验证受控软件参数和生命周期边界；G03实际变形、worker冻结基准传输、新PID登记恢复、公共writer输出事实、48+2、安装/macOS和真实/视觉/生产验收仍缺。
