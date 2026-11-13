# R05 宿主权威定向测试

本目录只属于测试分工。实现由主 agent 修改；本分工仅新增两个测试文件和本目录记录，不修改旧源码/夹具。

## 当前结果

- `final-owned/result.json`：25 methods，两版本，0 failure/error/skip，exit 0，耗时 6.775 秒；6 项源码/夹具摘要前后完全一致。两个测试文件现已冻结。
- `current-v3/result.json`：修复前 25 methods，24 methods 通过，1 method 两版本失败，exit 1；6 项源码/夹具摘要前后完全一致，仅作为诊断。
- 已由主实现关闭：`test_last_native_fps_read_cannot_hide_previously_observed_gate_drift`。底层 `hou.fps()` 第三次读取把已观察的 `exportlist` 从 `v` 改为 `w`，返回实际 FPS 24；修复前 Host observations 仍成功，21.0.631、22.0.429 均复现。主实现把 FPS 读取移到当前帧读取后、节点/参数采集前，未增加采集循环；最终两版本均正确拒绝，本分工未修改生产代码。
- `current-v2` 的 24 methods 全通过，只覆盖该新增末端竞态之前的范围，不能替代当前 25 methods 验收。
- `historical-boundary-frozen-v2`：仅在内存中加载当前 HEAD 的 Host/program，其他入口和底层夹具保持根源码；25 methods、54 个 subtest failure、0 error、exit 1。该记录用于展示历史缺陷，不是当前源码验收。加载的两个历史模块内容摘要单独记录，未回退或写入源码。
- `baseline-host` 已存在并行落地的部分修复；19 methods、12 个失败、exit 1。`baseline-addon` 是本测试夹具缺少 bypass API 的首次诊断，2 errors、exit 1，之后在本新增测试中补齐底层 API，未放松生产校验。
- `baseline-head-memory` 是早期 Host 单模块内存对照，检测到并行 program 文件变化，只作为诊断。`current-v1` 是精确错误码断言诊断，不是新增成功证据。
- `historical-boundary-frozen` 为空目录：首次本目录 runner 根路径层数错误，未加载项目、未跑测试；修正后的命令和结果在 `historical-boundary-frozen-v2`。

## 执行命令

在项目根目录执行；每次用新的 label 保留旧日志。

```powershell
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/authority/run_authority_tests.py final-owned
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/authority/run_authority_tests.py historical-boundary-frozen-v2 --head-boundary
```

`run_authority_tests.py` 在独占 label 目录保存完整原始 unittest 日志、精确命令、解释器/系统版本、退出码、测试数量、窄范围源码前后摘要。不冻结或扫描全源码，不阻止其他 agent 写作。

最终 Host SHA256 `f6476ed4447055834646b4ff3fe5ab3274dc97e4198ac5579fb36d3ef708446b`；program `39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`；addon `2b9b2add77418841c2a092c27e085a72cf3eb58219bcac287c20ad96458c9378`。测试文件 SHA256：Host 测试 `21e794a57a98858d4b1911f3f958ab323ad226fde4d7766a1f8182be5cbc3d4b`；addon 测试 `84c88e48b97e64f90dfe7854c7443953cd5e650ea19705c48f014f576e221567`。

## 新测试文件

- `tests/unit/test_rbd_host_authority.py`：23 methods，两版本覆盖可重摘要公共 basis/program 不授予权限、公共 basis 单独挂接、重摘要 seed、更换实际宿主字典/节点对象/sessionId、完整身份字段变化、异宿主 signed pending plan、同实际宿主新 Host 对象正向零振幅读回、初次/已登记回滚，以及晚期身份、原帧、gate、驱动、FPS、对象、session、可编辑性、bypass、errors、wire 漂移。
- `tests/unit/test_rbd_addon_authority.py`：2 methods，两版本实际 addon 正常 preflight 拒绝公共登记；实际 build_preview→apply_candidate 在缺少底层 packed geometry API 时拒绝，snippet、basis/program、当前 manifest 文件和帧均不改变。

Host 正常几何是固定 `(2,-3,4)` 原始速度及固定 packed geometry；本新增 fixture 的 carrier 始终原样读回 configure 固定几何，不计算请求的非零目标结果。唯一正向写入是零振幅，只证明原始速度、实际参数/消费者观察与权限隔离。未运行真实 DCC、仿真、渲染或 OS worker；新 PID 正向私有 HIP restore 不在本分工验收范围内。
